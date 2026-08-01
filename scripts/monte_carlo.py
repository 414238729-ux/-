"""通用蒙特卡洛执行器。"""

from __future__ import annotations

import random
from numbers import Real
from typing import Callable, Iterable

from ._validation import ensure_int_at_least, make_rng
from .summary import DEFAULT_QUANTILES, SimulationSummary, summarize_samples

Trial = Callable[[random.Random], Real]


def run_monte_carlo(
    trial: Trial,
    trials: int,
    seed: object | None = None,
    *,
    quantiles: Iterable[Real] = DEFAULT_QUANTILES,
) -> SimulationSummary:
    """重复执行数值型随机试验并返回统一统计摘要。

    ``trial`` 每次接收同一个局部 ``random.Random`` 实例。函数不修改
    ``random`` 模块的全局随机状态。
    """

    if not callable(trial):
        raise TypeError("trial 必须是可调用对象")
    ensure_int_at_least(trials, "试验次数", 1)
    rng = make_rng(seed)

    samples: list[Real] = []
    for index in range(trials):
        try:
            samples.append(trial(rng))
        except Exception as exc:
            raise RuntimeError(
                f"第 {index + 1} 次蒙特卡洛试验执行失败：{exc}"
            ) from exc

    return summarize_samples(
        samples,
        quantiles=quantiles,
        metadata={"trials": trials, "seed": seed},
    )
