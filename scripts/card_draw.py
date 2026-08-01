"""不放回抽取与抽牌模拟。"""

from __future__ import annotations

import random
from numbers import Real
from typing import Callable, Iterable, Sequence, TypeVar

from ._validation import ensure_int_at_least, make_rng
from .monte_carlo import run_monte_carlo
from .summary import DEFAULT_QUANTILES, SimulationSummary

T = TypeVar("T")


def _prepare_deck(deck: Sequence[T]) -> tuple[T, ...]:
    if deck is None:
        raise TypeError("牌堆不能是 None")
    try:
        return tuple(deck)
    except TypeError as exc:
        raise TypeError("牌堆必须是可迭代序列") from exc


def _validate_draw_count(draw_count: int, deck_size: int) -> None:
    ensure_int_at_least(draw_count, "抽取数量", 0)
    if draw_count > deck_size:
        raise ValueError(
            f"抽取数量不能超过牌堆大小，当前为 {draw_count}>{deck_size}"
        )


def _draw_with_rng(
    deck: tuple[T, ...],
    draw_count: int,
    rng: random.Random,
) -> list[T]:
    return rng.sample(deck, draw_count)


def draw_without_replacement(
    deck: Sequence[T],
    draw_count: int,
    seed: object | None = None,
) -> list[T]:
    """从序列中按位置均匀不放回抽取。

    牌面值可以重复；重复牌仍按牌堆中的不同位置参与抽取。
    """

    prepared_deck = _prepare_deck(deck)
    _validate_draw_count(draw_count, len(prepared_deck))
    return _draw_with_rng(prepared_deck, draw_count, make_rng(seed))


def simulate_draws(
    deck: Sequence[T],
    draw_count: int,
    score: Callable[[list[T]], Real],
    trials: int,
    seed: object | None = None,
    *,
    quantiles: Iterable[Real] = DEFAULT_QUANTILES,
) -> SimulationSummary:
    """重复不放回抽取，并对每手牌的数值评分做统计。"""

    prepared_deck = _prepare_deck(deck)
    _validate_draw_count(draw_count, len(prepared_deck))
    ensure_int_at_least(trials, "试验次数", 1)
    if not callable(score):
        raise TypeError("score 必须是可调用对象")

    return run_monte_carlo(
        lambda rng: score(
            _draw_with_rng(prepared_deck, draw_count, rng)
        ),
        trials=trials,
        seed=seed,
        quantiles=quantiles,
    )
