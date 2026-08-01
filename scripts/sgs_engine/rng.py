"""可审计、可复现的确定性随机数流。

本模块只负责随机数消费与调用记录，不包含任何游戏规则。每一局游戏应只
创建一个 :class:`DeterministicRNG` 实例，并把它传给所有需要随机性的组件；
不要在摸牌、判定或 AI 决策时重新用同一个种子创建实例。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass
from enum import Enum
import hashlib
import json
import math
from numbers import Real
from pathlib import Path
import random
from types import MappingProxyType
from typing import Any, Mapping, MutableSequence, Sequence, TypeVar


T = TypeVar("T")


RNG_STATE_SCHEMA = "sgs-deterministic-rng-state-v1"
RNG_IMPLEMENTATION = "python.random.Random"
RNG_ALGORITHM = "MT19937"


def _deep_freeze(value: Any) -> Any:
    """递归冻结已经规范化的 JSON 值。"""

    if isinstance(value, Mapping):
        return MappingProxyType({key: _deep_freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_deep_freeze(item) for item in value)
    if isinstance(value, tuple):
        return tuple(_deep_freeze(item) for item in value)
    return value


def _deep_copy_json(value: Any) -> Any:
    """把冻结值转回一份调用方可修改的独立 JSON 副本。"""

    if isinstance(value, Mapping):
        return {key: _deep_copy_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_deep_copy_json(item) for item in value]
    if isinstance(value, list):
        return [_deep_copy_json(item) for item in value]
    return value


def _canonical_json(value: Any) -> str:
    """Return a stable JSON representation for an already auditable value."""

    return json.dumps(
        _json_value(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _sha256_json(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _require_integer(value: Any, name: str, *, minimum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} 必须是整数，不能使用布尔值或其他类型")
    if minimum is not None and value < minimum:
        raise ValueError(f"{name} 必须不小于 {minimum}")
    return value


def _require_finite_number(value: Any, name: str) -> int | float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise TypeError(f"{name} 必须是有限实数，不能使用布尔值或其他类型")
    try:
        finite = math.isfinite(value)
    except (OverflowError, TypeError, ValueError) as exc:
        raise ValueError(f"{name} 必须是有限实数") from exc
    if not finite:
        raise ValueError(f"{name} 必须是有限实数")
    if not isinstance(value, (int, float)):
        raise TypeError(f"{name} 目前只支持整数或浮点数")
    return value


def _json_value(value: Any, *, path: str = "$") -> Any:
    """把审计值转换为稳定、无歧义的 JSON 值。

    游戏对象若需要进入随机候选集合，应实现 ``to_replay_dict()``，或使用
    dataclass。拒绝以默认 ``repr`` 兜底，因为对象地址会破坏跨进程复现。
    """

    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"随机审计值 {path} 必须是有限数值")
        return value
    if isinstance(value, Enum):
        return _json_value(value.value, path=path)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, bytes):
        return {"__bytes_hex__": value.hex()}
    if isinstance(value, range):
        return list(value)
    if is_dataclass(value) and not isinstance(value, type):
        return _json_value(asdict(value), path=path)
    to_replay_dict = getattr(value, "to_replay_dict", None)
    if callable(to_replay_dict):
        return _json_value(to_replay_dict(), path=path)
    if isinstance(value, Mapping):
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError(f"随机审计映射 {path} 的键必须是字符串")
            normalized[key] = _json_value(item, path=f"{path}.{key}")
        return normalized
    if isinstance(value, (list, tuple)):
        return [
            _json_value(item, path=f"{path}[{index}]")
            for index, item in enumerate(value)
        ]
    if isinstance(value, (set, frozenset)):
        items = [_json_value(item, path=f"{path}[]") for item in value]
        return sorted(
            items,
            key=lambda item: json.dumps(
                item, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ),
        )
    raise TypeError(
        f"随机审计值 {path} 的类型 {type(value).__name__} 无法稳定序列化；"
        "请使用 dataclass 或实现 to_replay_dict()"
    )


@dataclass(frozen=True, slots=True)
class RNGCall:
    """一次随机调用的审计记录。"""

    index: int
    method: str
    arguments: Mapping[str, Any]
    result: Any

    def __post_init__(self) -> None:
        _require_integer(self.index, "随机调用 index", minimum=0)
        if not isinstance(self.method, str) or not self.method:
            raise ValueError("随机调用 method 必须是非空字符串")
        if not isinstance(self.arguments, Mapping):
            raise TypeError("随机调用 arguments 必须是映射")
        normalized_arguments = _json_value(
            self.arguments, path="$.arguments"
        )
        normalized_result = _json_value(self.result, path="$.result")
        object.__setattr__(
            self, "arguments", _deep_freeze(normalized_arguments)
        )
        object.__setattr__(self, "result", _deep_freeze(normalized_result))

    @property
    def sequence(self) -> int:
        """``index`` 的可读别名，序号从 0 开始。"""

        return self.index

    def to_dict(self) -> dict[str, Any]:
        return _deep_copy_json({
            "index": self.index,
            "method": self.method,
            "arguments": self.arguments,
            "result": self.result,
        })


class DeterministicRNG:
    """一局游戏共享的持久确定性随机数流。

    该类不提供重新播种方法，避免运行途中意外重置序列。需要另一条随机流
    时必须显式创建另一个实例，并记录不同的种子。
    """

    def __init__(self, seed: int) -> None:
        if isinstance(seed, bool) or not isinstance(seed, int):
            raise TypeError("随机种子必须是整数")
        self._seed = seed
        self._random = random.Random(seed)
        self._calls: list[RNGCall] = []
        self._initial_state = _deep_freeze(self._state_payload(call_count=0))

    @property
    def seed(self) -> int:
        return self._seed

    @property
    def calls(self) -> tuple[RNGCall, ...]:
        """返回只读调用快照，外部不能清空或改写内部审计记录。"""

        return tuple(self._calls)

    @property
    def call_count(self) -> int:
        return len(self._calls)

    def export_calls(self) -> list[dict[str, Any]]:
        """返回可直接写入回放的 JSON 兼容调用列表。"""

        return [call.to_dict() for call in self._calls]

    def _state_payload(self, *, call_count: int) -> dict[str, Any]:
        """Build the complete, canonical replay checkpoint for this stream."""

        return {
            "schema": RNG_STATE_SCHEMA,
            "implementation": RNG_IMPLEMENTATION,
            "algorithm": RNG_ALGORITHM,
            "state_version": random.Random.VERSION,
            "seed": self._seed,
            "call_count": call_count,
            "getstate": _json_value(self._random.getstate(), path="$.getstate"),
        }

    def export_initial_state(self) -> dict[str, Any]:
        """返回首次随机消费前的完整状态独立副本。

        快照包含算法标识、``random.Random.VERSION``、种子、调用计数和完整
        ``getstate()``。调用方修改返回值不会影响内部保存的初始状态。
        """

        return _deep_copy_json(self._initial_state)

    def export_current_state(self) -> dict[str, Any]:
        """返回当前随机流的完整状态独立副本，且不消费随机数。"""

        return _deep_copy_json(self._state_payload(call_count=self.call_count))

    @property
    def initial_state_sha256(self) -> str:
        """首次随机消费前状态的规范 JSON SHA-256。"""

        return _sha256_json(self._initial_state)

    @property
    def current_state_sha256(self) -> str:
        """当前状态的规范 JSON SHA-256；读取本属性不会消费随机数。"""

        return _sha256_json(self._state_payload(call_count=self.call_count))

    def _record(self, method: str, arguments: Mapping[str, Any], result: Any) -> None:
        normalized_arguments = _json_value(dict(arguments), path="$.arguments")
        normalized_result = _json_value(result, path="$.result")
        self._calls.append(
            RNGCall(
                index=len(self._calls),
                method=method,
                arguments=_deep_freeze(normalized_arguments),
                result=_deep_freeze(normalized_result),
            )
        )

    def random(self) -> float:
        result = self._random.random()
        self._record("random", {}, result)
        return result

    def getrandbits(self, k: int) -> int:
        _require_integer(k, "getrandbits 的位数", minimum=0)
        result = self._random.getrandbits(k)
        self._record("getrandbits", {"k": k}, result)
        return result

    def randrange(
        self, start: int, stop: int | None = None, step: int = 1
    ) -> int:
        _require_integer(start, "randrange 的 start")
        if stop is not None:
            _require_integer(stop, "randrange 的 stop")
        _require_integer(step, "randrange 的 step")
        if step == 0:
            raise ValueError("randrange 的 step 不能为 0")
        try:
            if stop is None:
                result = self._random.randrange(start)
                arguments = {"start": 0, "stop": start, "step": 1}
            else:
                result = self._random.randrange(start, stop, step)
                arguments = {"start": start, "stop": stop, "step": step}
        except (TypeError, ValueError) as exc:
            raise ValueError(f"randrange 参数无效：{exc}") from exc
        self._record("randrange", arguments, result)
        return result

    def randint(self, a: int, b: int) -> int:
        _require_integer(a, "randint 的下界")
        _require_integer(b, "randint 的上界")
        try:
            result = self._random.randint(a, b)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"randint 参数无效：{exc}") from exc
        self._record("randint", {"a": a, "b": b}, result)
        return result

    def uniform(self, a: float, b: float) -> float:
        _require_finite_number(a, "uniform 的下界")
        _require_finite_number(b, "uniform 的上界")
        result = self._random.uniform(a, b)
        if not math.isfinite(result):
            raise ValueError("uniform 的结果不是有限数值，请缩小上下界")
        self._record("uniform", {"a": a, "b": b}, result)
        return result

    def choice(self, population: Sequence[T]) -> T:
        if len(population) == 0:
            raise ValueError("choice 的候选序列不能为空")
        arguments = {"population": list(population)}
        _json_value(arguments, path="$.arguments")
        result = self._random.choice(population)
        self._record("choice", arguments, result)
        return result

    def choices(
        self,
        population: Sequence[T],
        weights: Sequence[float] | None = None,
        *,
        cum_weights: Sequence[float] | None = None,
        k: int = 1,
    ) -> list[T]:
        if len(population) == 0:
            raise ValueError("choices 的候选序列不能为空")
        _require_integer(k, "choices 的 k", minimum=0)
        if weights is not None and cum_weights is not None:
            raise ValueError("choices 不能同时提供 weights 和 cum_weights")
        if weights is not None:
            if len(weights) != len(population):
                raise ValueError("choices 的 weights 数量必须与候选数量一致")
            checked_weights = [
                _require_finite_number(weight, f"choices 的 weights[{index}]")
                for index, weight in enumerate(weights)
            ]
            if any(weight < 0 for weight in checked_weights):
                raise ValueError("choices 的 weights 不能包含负数")
            total = sum(checked_weights)
            if not math.isfinite(total) or total <= 0:
                raise ValueError("choices 的 weights 总和必须是正的有限数值")
        if cum_weights is not None:
            if len(cum_weights) != len(population):
                raise ValueError("choices 的 cum_weights 数量必须与候选数量一致")
            checked_cumulative = [
                _require_finite_number(weight, f"choices 的 cum_weights[{index}]")
                for index, weight in enumerate(cum_weights)
            ]
            if any(weight < 0 for weight in checked_cumulative):
                raise ValueError("choices 的 cum_weights 不能包含负数")
            if any(
                current < previous
                for previous, current in zip(
                    checked_cumulative, checked_cumulative[1:]
                )
            ):
                raise ValueError("choices 的 cum_weights 必须单调不减")
            if checked_cumulative[-1] <= 0:
                raise ValueError("choices 的 cum_weights 末值必须大于 0")
        arguments = {
            "population": list(population),
            "weights": None if weights is None else list(weights),
            "cum_weights": None if cum_weights is None else list(cum_weights),
            "k": k,
        }
        _json_value(arguments, path="$.arguments")
        try:
            result = self._random.choices(
                population, weights=weights, cum_weights=cum_weights, k=k
            )
        except (TypeError, ValueError) as exc:
            raise ValueError(f"choices 参数无效：{exc}") from exc
        self._record("choices", arguments, result)
        return result

    def sample(
        self,
        population: Sequence[T],
        k: int,
        *,
        counts: Sequence[int] | None = None,
    ) -> list[T]:
        _require_integer(k, "sample 的 k", minimum=0)
        if counts is not None:
            if len(counts) != len(population):
                raise ValueError("sample 的 counts 数量必须与候选数量一致")
            for index, count in enumerate(counts):
                _require_integer(count, f"sample 的 counts[{index}]", minimum=0)
        arguments = {
            "population": list(population),
            "k": k,
            "counts": None if counts is None else list(counts),
        }
        _json_value(arguments, path="$.arguments")
        try:
            result = self._random.sample(population, k, counts=counts)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"sample 参数无效：{exc}") from exc
        self._record("sample", arguments, result)
        return result

    def shuffle(self, values: MutableSequence[T]) -> None:
        before = list(values)
        _json_value({"before": before}, path="$.arguments")
        self._random.shuffle(values)
        self._record("shuffle", {"before": before}, {"after": list(values)})


__all__ = [
    "RNG_ALGORITHM",
    "RNG_IMPLEMENTATION",
    "RNG_STATE_SCHEMA",
    "DeterministicRNG",
    "RNGCall",
]
