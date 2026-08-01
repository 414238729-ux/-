import random

import pytest

from scripts import run_monte_carlo


def test_deterministic_trial_has_exact_summary() -> None:
    summary = run_monte_carlo(lambda rng: 3, trials=20, seed=123)

    assert summary.mean == 3
    assert summary.median == 3
    assert summary.std_dev == 0
    assert summary.metadata == {"trials": 20, "seed": 123}


def test_fixed_seed_is_reproducible() -> None:
    first = run_monte_carlo(
        lambda rng: rng.randint(1, 6),
        trials=1_000,
        seed=2026,
    )
    second = run_monte_carlo(
        lambda rng: rng.randint(1, 6),
        trials=1_000,
        seed=2026,
    )

    assert first == second


def test_runner_does_not_change_global_random_state() -> None:
    random.seed(99)
    expected = random.random()

    random.seed(99)
    run_monte_carlo(lambda rng: rng.random(), trials=10, seed=1)
    actual = random.random()

    assert actual == expected


@pytest.mark.parametrize("trials", [0, -1])
def test_non_positive_trial_count_is_rejected(trials: int) -> None:
    with pytest.raises(ValueError, match="试验次数"):
        run_monte_carlo(lambda rng: 1, trials=trials)


def test_non_numeric_trial_result_is_rejected() -> None:
    with pytest.raises(TypeError, match="实数"):
        run_monte_carlo(lambda rng: "not-a-number", trials=1)
