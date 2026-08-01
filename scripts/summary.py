"""通用数值样本摘要、分位数和置信区间。"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field
from numbers import Real
from typing import Iterable, Mapping, Sequence

from ._validation import ensure_finite_real, ensure_int_at_least

DEFAULT_QUANTILES: tuple[float, ...] = (0.05, 0.25, 0.5, 0.75, 0.95)
Z_95 = 1.959963984540054


@dataclass(frozen=True)
class ConfidenceInterval:
    """闭区间形式的置信区间。"""

    lower: float
    upper: float

    def to_dict(self) -> dict[str, float]:
        return {"lower": self.lower, "upper": self.upper}


@dataclass(frozen=True)
class DistributionEstimate:
    """一个离散结果的经验概率与抽样误差。"""

    count: int
    probability: float
    standard_error: float
    confidence_interval_95: ConfidenceInterval

    def to_dict(self) -> dict[str, object]:
        return {
            "count": self.count,
            "probability": self.probability,
            "standard_error": self.standard_error,
            "confidence_interval_95": self.confidence_interval_95.to_dict(),
        }


@dataclass(frozen=True)
class SimulationSummary:
    """数值型模拟样本的统一统计结果。"""

    sample_count: int
    mean: float
    median: float
    std_dev: float
    mean_standard_error: float
    mean_confidence_interval_95: ConfidenceInterval
    quantiles: dict[float, float]
    distribution: dict[Real, DistributionEstimate]
    metadata: Mapping[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "sample_count": self.sample_count,
            "mean": self.mean,
            "median": self.median,
            "std_dev": self.std_dev,
            "mean_standard_error": self.mean_standard_error,
            "mean_confidence_interval_95": (
                self.mean_confidence_interval_95.to_dict()
            ),
            "quantiles": dict(self.quantiles),
            "distribution": {
                str(outcome): estimate.to_dict()
                for outcome, estimate in self.distribution.items()
            },
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class ExactDistributionSummary:
    """已知离散概率质量函数的精确统计结果。"""

    mean: float
    median: float
    std_dev: float
    quantiles: dict[float, float]
    probabilities: dict[Real, float]

    def to_dict(self) -> dict[str, object]:
        return {
            "method": "exact",
            "mean": self.mean,
            "median": self.median,
            "std_dev": self.std_dev,
            "quantiles": dict(self.quantiles),
            "probabilities": {
                str(outcome): probability
                for outcome, probability in self.probabilities.items()
            },
        }


def validate_quantiles(quantiles: Iterable[Real]) -> tuple[float, ...]:
    """校验并按从小到大返回不重复分位点。"""

    try:
        raw_quantiles = list(quantiles)
    except TypeError as exc:
        raise TypeError("分位点必须是可迭代的实数集合") from exc

    validated: list[float] = []
    for index, quantile in enumerate(raw_quantiles):
        value = ensure_finite_real(quantile, f"第 {index + 1} 个分位点")
        if not 0.0 <= value <= 1.0:
            raise ValueError(f"分位点必须位于 [0, 1]，当前值为 {value}")
        validated.append(value)
    return tuple(sorted(set(validated)))


def linear_quantile(sorted_values: Sequence[float], quantile: float) -> float:
    """使用常见的 Type-7 线性插值计算经验分位数。"""

    if not sorted_values:
        raise ValueError("计算分位数时样本不能为空")
    if len(sorted_values) == 1:
        return sorted_values[0]

    position = (len(sorted_values) - 1) * quantile
    lower_index = math.floor(position)
    upper_index = math.ceil(position)
    if lower_index == upper_index:
        return sorted_values[lower_index]

    fraction = position - lower_index
    return (
        sorted_values[lower_index] * (1.0 - fraction)
        + sorted_values[upper_index] * fraction
    )


def wilson_confidence_interval(
    successes: int,
    total: int,
    *,
    z: float = Z_95,
) -> ConfidenceInterval:
    """计算二项比例的 Wilson 置信区间。"""

    ensure_int_at_least(total, "总次数", 1)
    ensure_int_at_least(successes, "成功次数", 0)
    if successes > total:
        raise ValueError(
            f"成功次数不能超过总次数，当前为 {successes}/{total}"
        )
    z_value = ensure_finite_real(z, "z 值")
    if z_value <= 0:
        raise ValueError("z 值必须大于 0")

    probability = successes / total
    z_squared = z_value * z_value
    denominator = 1.0 + z_squared / total
    center = (probability + z_squared / (2.0 * total)) / denominator
    margin = (
        z_value
        * math.sqrt(
            probability * (1.0 - probability) / total
            + z_squared / (4.0 * total * total)
        )
        / denominator
    )
    return ConfidenceInterval(
        lower=max(0.0, center - margin),
        upper=min(1.0, center + margin),
    )


def estimate_probability(successes: int, total: int) -> DistributionEstimate:
    """生成一个事件概率的估计摘要。"""

    interval = wilson_confidence_interval(successes, total)
    probability = successes / total
    standard_error = math.sqrt(
        probability * (1.0 - probability) / total
    )
    return DistributionEstimate(
        count=successes,
        probability=probability,
        standard_error=standard_error,
        confidence_interval_95=interval,
    )


def summarize_samples(
    samples: Iterable[Real],
    *,
    quantiles: Iterable[Real] = DEFAULT_QUANTILES,
    metadata: Mapping[str, object] | None = None,
) -> SimulationSummary:
    """统计有限数值样本。

    标准差按总体标准差计算；均值区间使用正态近似；离散概率区间使用
    Wilson 方法。
    """

    try:
        raw_values = list(samples)
    except TypeError as exc:
        raise TypeError("样本必须是可迭代的实数集合") from exc
    if not raw_values:
        raise ValueError("样本不能为空")

    numeric_values: list[float] = []
    for index, value in enumerate(raw_values):
        numeric_values.append(
            ensure_finite_real(value, f"第 {index + 1} 个样本")
        )
        try:
            hash(value)
        except TypeError as exc:
            raise TypeError(f"第 {index + 1} 个样本必须可作为分布键") from exc

    requested_quantiles = validate_quantiles(quantiles)
    sorted_values = sorted(numeric_values)
    sample_count = len(numeric_values)
    mean = math.fsum(numeric_values) / sample_count
    variance = (
        math.fsum((value - mean) ** 2 for value in numeric_values)
        / sample_count
    )
    std_dev = math.sqrt(max(0.0, variance))
    mean_standard_error = std_dev / math.sqrt(sample_count)
    mean_margin = Z_95 * mean_standard_error

    counts = Counter(raw_values)
    distribution = {
        outcome: estimate_probability(count, sample_count)
        for outcome, count in sorted(counts.items(), key=lambda item: float(item[0]))
    }

    return SimulationSummary(
        sample_count=sample_count,
        mean=mean,
        median=linear_quantile(sorted_values, 0.5),
        std_dev=std_dev,
        mean_standard_error=mean_standard_error,
        mean_confidence_interval_95=ConfidenceInterval(
            lower=mean - mean_margin,
            upper=mean + mean_margin,
        ),
        quantiles={
            quantile: linear_quantile(sorted_values, quantile)
            for quantile in requested_quantiles
        },
        distribution=distribution,
        metadata=dict(metadata or {}),
    )
