"""伤害样本与精确离散伤害分布统计。"""

from __future__ import annotations

import math
from numbers import Real
from typing import Iterable, Mapping

from ._validation import ensure_finite_real
from .summary import (
    DEFAULT_QUANTILES,
    ExactDistributionSummary,
    SimulationSummary,
    summarize_samples,
    validate_quantiles,
)

PROBABILITY_TOLERANCE = 1e-9


def analyze_damage_samples(
    samples: Iterable[Real],
    *,
    quantiles: Iterable[Real] = DEFAULT_QUANTILES,
) -> SimulationSummary:
    """统计实测或模拟得到的非负伤害样本。"""

    try:
        values = list(samples)
    except TypeError as exc:
        raise TypeError("伤害样本必须是可迭代的实数集合") from exc
    for index, value in enumerate(values):
        numeric = ensure_finite_real(value, f"第 {index + 1} 个伤害样本")
        if numeric < 0:
            raise ValueError(
                f"伤害样本不能为负数，第 {index + 1} 个值为 {numeric}"
            )
    return summarize_samples(
        values,
        quantiles=quantiles,
        metadata={"method": "sample"},
    )


def _inverse_cdf(
    entries: list[tuple[Real, float, float]],
    quantile: float,
) -> float:
    positive_entries = [entry for entry in entries if entry[2] > 0.0]
    if quantile <= 0.0:
        return positive_entries[0][1]

    cumulative = 0.0
    for _, damage, probability in positive_entries:
        cumulative += probability
        if cumulative + PROBABILITY_TOLERANCE >= quantile:
            return damage
    return positive_entries[-1][1]


def analyze_exact_damage_distribution(
    probabilities: Mapping[Real, Real],
    *,
    quantiles: Iterable[Real] = DEFAULT_QUANTILES,
) -> ExactDistributionSummary:
    """对离散伤害概率质量函数进行精确统计。"""

    if not isinstance(probabilities, Mapping):
        raise TypeError("伤害分布必须是“伤害值 -> 概率”的映射")
    if not probabilities:
        raise ValueError("伤害分布不能为空")

    entries: list[tuple[Real, float, float]] = []
    for damage, probability in probabilities.items():
        damage_value = ensure_finite_real(damage, f"伤害值 {damage!r}")
        if damage_value < 0:
            raise ValueError(f"伤害值不能为负数，当前值为 {damage_value}")
        probability_value = ensure_finite_real(
            probability,
            f"伤害值 {damage!r} 的概率",
        )
        if probability_value < 0:
            raise ValueError(
                f"概率不能为负数，伤害值 {damage!r} 的概率为 "
                f"{probability_value}"
            )
        entries.append((damage, damage_value, probability_value))

    entries.sort(key=lambda entry: entry[1])
    total_probability = math.fsum(entry[2] for entry in entries)
    if not math.isclose(
        total_probability,
        1.0,
        rel_tol=0.0,
        abs_tol=PROBABILITY_TOLERANCE,
    ):
        raise ValueError(
            "伤害分布的概率和必须为 1，"
            f"当前概率和为 {total_probability:.12g}"
        )
    if not any(entry[2] > 0.0 for entry in entries):
        raise ValueError("伤害分布必须至少包含一个正概率结果")

    requested_quantiles = validate_quantiles(quantiles)
    mean = math.fsum(damage * probability for _, damage, probability in entries)
    variance = math.fsum(
        probability * (damage - mean) ** 2
        for _, damage, probability in entries
    )

    return ExactDistributionSummary(
        mean=mean,
        median=_inverse_cdf(entries, 0.5),
        std_dev=math.sqrt(max(0.0, variance)),
        quantiles={
            quantile: _inverse_cdf(entries, quantile)
            for quantile in requested_quantiles
        },
        probabilities={
            original_damage: probability
            for original_damage, _, probability in entries
        },
    )
