import math

import pytest

from scripts import (
    analyze_damage_samples,
    analyze_exact_damage_distribution,
)


def test_damage_samples_are_summarized() -> None:
    summary = analyze_damage_samples([0, 2, 2, 2])

    assert summary.mean == 1.5
    assert summary.median == 2
    assert math.isclose(summary.std_dev, math.sqrt(0.75))
    assert summary.distribution[0].probability == 0.25
    assert summary.distribution[2].probability == 0.75
    assert summary.metadata["method"] == "sample"


def test_exact_damage_distribution_statistics() -> None:
    summary = analyze_exact_damage_distribution({0: 0.25, 2: 0.75})

    assert summary.mean == 1.5
    assert summary.median == 2
    assert math.isclose(summary.std_dev, math.sqrt(0.75))
    assert summary.quantiles[0.05] == 0
    assert summary.quantiles[0.25] == 0
    assert summary.quantiles[0.5] == 2


def test_zero_probability_value_is_not_part_of_quantile_support() -> None:
    summary = analyze_exact_damage_distribution(
        {0: 0, 1: 1},
        quantiles=(0, 0.5, 1),
    )

    assert summary.quantiles == {0.0: 1, 0.5: 1, 1.0: 1}


def test_probability_sum_must_equal_one() -> None:
    with pytest.raises(ValueError, match="概率和必须为 1"):
        analyze_exact_damage_distribution({0: 0.2, 1: 0.7})


@pytest.mark.parametrize(
    "distribution",
    [
        {-1: 1.0},
        {0: -0.1, 1: 1.1},
        {0: math.nan, 1: 1.0},
        {},
    ],
)
def test_invalid_exact_damage_distributions_are_rejected(
    distribution: dict[float, float],
) -> None:
    with pytest.raises(ValueError):
        analyze_exact_damage_distribution(distribution)


def test_negative_damage_sample_is_rejected() -> None:
    with pytest.raises(ValueError, match="不能为负数"):
        analyze_damage_samples([1, -1])


def test_empty_damage_samples_are_rejected() -> None:
    with pytest.raises(ValueError, match="样本不能为空"):
        analyze_damage_samples([])
