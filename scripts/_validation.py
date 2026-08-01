"""内部输入校验工具。"""

from __future__ import annotations

import math
import random
from numbers import Real
from typing import Any


def ensure_int_at_least(value: Any, name: str, minimum: int) -> int:
    """校验整数下限，并拒绝容易被误当作整数的布尔值。"""

    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name}必须是整数，当前值为 {value!r}")
    if value < minimum:
        raise ValueError(f"{name}必须大于或等于 {minimum}，当前值为 {value}")
    return value


def ensure_finite_real(value: Any, name: str) -> float:
    """把有限实数转换为 float。"""

    if not isinstance(value, Real):
        raise TypeError(f"{name}必须是实数，当前值为 {value!r}")
    try:
        converted = float(value)
    except (OverflowError, TypeError, ValueError) as exc:
        raise ValueError(f"{name}无法转换为有限实数，当前值为 {value!r}") from exc
    if not math.isfinite(converted):
        raise ValueError(f"{name}必须是有限实数，当前值为 {value!r}")
    return converted


def make_rng(seed: object | None) -> random.Random:
    """创建独立随机数生成器，并把种子错误转换成中文提示。"""

    try:
        return random.Random(seed)
    except (TypeError, ValueError) as exc:
        raise TypeError(
            "随机种子必须是 None、int、float、str、bytes 或 bytearray"
        ) from exc
