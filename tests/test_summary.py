import math

import pytest

from scripts import summarize_samples, wilson_confidence_interval


def test_constant_samples_have_zero_variance_and_error() -> None:
    summary = summarize_samples([7, 7, 7, 7])

    assert summary.sample_count == 4
    assert summary.mean == 7
    assert summary.median == 7
    assert summary.std_dev == 0
    assert summary.mean_standard_error == 0
    assert summary.mean_confidence_interval_95.lower == 7
    assert summary.mean_confidence_interval_95.upper == 7
    assert set(summary.quantiles.values()) == {7}
    assert summary.distribution[7].count == 4
    assert summary.distribution[7].probability == 1


def test_type7_quantile_interpolation() -> None:
    summary = summarize_samples(
        [0, 10],
        quantiles=(0, 0.25, 0.5, 0.75, 1),
    )

    assert summary.quantiles == {
        0.0: 0,
        0.25: 2.5,
        0.5: 5,
        0.75: 7.5,
        1.0: 10,
    }


def test_extreme_finite_samples_are_supported() -> None:
    summary = summarize_samples([-1e150, 1e150])

    assert summary.mean == 0
    assert math.isclose(summary.std_dev, 1e150)


@pytest.mark.parametrize("samples", [[], [math.nan], [math.inf]])
def test_invalid_samples_raise_clear_errors(samples: list[float]) -> None:
    with pytest.raises(ValueError):
        summarize_samples(samples)


def test_invalid_quantile_is_rejected() -> None:
    with pytest.raises(ValueError, match="分位点"):
        summarize_samples([1], quantiles=(-0.01,))


def test_wilson_interval_contains_empirical_probability() -> None:
    interval = wilson_confidence_interval(25, 100)

    assert interval.lower < 0.25 < interval.upper


def test_wilson_interval_rejects_impossible_counts() -> None:
    with pytest.raises(ValueError, match="不能超过"):
        wilson_confidence_interval(2, 1)
