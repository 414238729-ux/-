"""条件触发与重复触发模拟器。"""

from __future__ import annotations

import random
from dataclasses import dataclass
from numbers import Real
from typing import Callable, Generic, Iterable, TypeVar

from ._validation import ensure_int_at_least, make_rng
from .summary import (
    DEFAULT_QUANTILES,
    SimulationSummary,
    estimate_probability,
    summarize_samples,
)

StateT = TypeVar("StateT")


@dataclass(frozen=True)
class TriggerResult(Generic[StateT]):
    """一次触发链的终态。"""

    final_state: StateT
    trigger_count: int
    reached_limit: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "final_state": self.final_state,
            "trigger_count": self.trigger_count,
            "reached_limit": self.reached_limit,
        }


def _validate_trigger_callables(
    should_trigger: Callable[[StateT], bool],
    resolve_trigger: Callable[[StateT, random.Random], StateT],
) -> None:
    if not callable(should_trigger):
        raise TypeError("should_trigger 必须是可调用对象")
    if not callable(resolve_trigger):
        raise TypeError("resolve_trigger 必须是可调用对象")


def _run_trigger_chain_with_rng(
    initial_state: StateT,
    should_trigger: Callable[[StateT], bool],
    resolve_trigger: Callable[[StateT, random.Random], StateT],
    max_triggers: int,
    rng: random.Random,
) -> TriggerResult[StateT]:
    state = initial_state
    trigger_count = 0

    while trigger_count < max_triggers:
        try:
            can_trigger = bool(should_trigger(state))
        except Exception as exc:
            raise RuntimeError(
                f"第 {trigger_count + 1} 次触发条件检查失败：{exc}"
            ) from exc
        if not can_trigger:
            return TriggerResult(
                final_state=state,
                trigger_count=trigger_count,
                reached_limit=False,
            )

        try:
            state = resolve_trigger(state, rng)
        except Exception as exc:
            raise RuntimeError(
                f"第 {trigger_count + 1} 次触发结算失败：{exc}"
            ) from exc
        trigger_count += 1

    try:
        reached_limit = bool(should_trigger(state))
    except Exception as exc:
        raise RuntimeError(f"达到上限后的触发条件检查失败：{exc}") from exc
    return TriggerResult(
        final_state=state,
        trigger_count=trigger_count,
        reached_limit=reached_limit,
    )


def run_trigger_chain(
    initial_state: StateT,
    should_trigger: Callable[[StateT], bool],
    resolve_trigger: Callable[[StateT, random.Random], StateT],
    max_triggers: int,
    seed: object | None = None,
) -> TriggerResult[StateT]:
    """执行一次有硬上限的条件触发链。"""

    _validate_trigger_callables(should_trigger, resolve_trigger)
    ensure_int_at_least(max_triggers, "最大触发次数", 1)
    return _run_trigger_chain_with_rng(
        initial_state,
        should_trigger,
        resolve_trigger,
        max_triggers,
        make_rng(seed),
    )


def simulate_trigger_chain(
    initial_state_factory: Callable[[], StateT],
    should_trigger: Callable[[StateT], bool],
    resolve_trigger: Callable[[StateT, random.Random], StateT],
    score: Callable[[TriggerResult[StateT]], Real],
    trials: int,
    max_triggers: int,
    seed: object | None = None,
    *,
    quantiles: Iterable[Real] = DEFAULT_QUANTILES,
) -> SimulationSummary:
    """重复执行触发链并统计评分，同时报告被硬上限截断的比例。"""

    if not callable(initial_state_factory):
        raise TypeError("initial_state_factory 必须是可调用对象")
    _validate_trigger_callables(should_trigger, resolve_trigger)
    if not callable(score):
        raise TypeError("score 必须是可调用对象")
    ensure_int_at_least(trials, "试验次数", 1)
    ensure_int_at_least(max_triggers, "最大触发次数", 1)

    rng = make_rng(seed)
    scores: list[Real] = []
    truncated_count = 0

    for trial_index in range(trials):
        try:
            initial_state = initial_state_factory()
            result = _run_trigger_chain_with_rng(
                initial_state,
                should_trigger,
                resolve_trigger,
                max_triggers,
                rng,
            )
            scores.append(score(result))
        except Exception as exc:
            raise RuntimeError(
                f"第 {trial_index + 1} 次触发链模拟失败：{exc}"
            ) from exc
        if result.reached_limit:
            truncated_count += 1

    truncation = estimate_probability(truncated_count, trials)
    return summarize_samples(
        scores,
        quantiles=quantiles,
        metadata={
            "trials": trials,
            "seed": seed,
            "max_triggers": max_triggers,
            "truncation": truncation.to_dict(),
        },
    )
