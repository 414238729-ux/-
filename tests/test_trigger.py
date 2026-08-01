import pytest

from scripts import run_trigger_chain, simulate_trigger_chain


def test_false_condition_never_triggers() -> None:
    result = run_trigger_chain(
        initial_state=0,
        should_trigger=lambda state: False,
        resolve_trigger=lambda state, rng: state + 1,
        max_triggers=5,
        seed=0,
    )

    assert result.final_state == 0
    assert result.trigger_count == 0
    assert result.reached_limit is False


def test_trigger_chain_stops_naturally() -> None:
    result = run_trigger_chain(
        initial_state=0,
        should_trigger=lambda state: state < 3,
        resolve_trigger=lambda state, rng: state + 1,
        max_triggers=10,
        seed=0,
    )

    assert result.final_state == 3
    assert result.trigger_count == 3
    assert result.reached_limit is False


def test_trigger_chain_reports_hard_limit() -> None:
    result = run_trigger_chain(
        initial_state=0,
        should_trigger=lambda state: state < 3,
        resolve_trigger=lambda state, rng: state + 1,
        max_triggers=2,
        seed=0,
    )

    assert result.final_state == 2
    assert result.trigger_count == 2
    assert result.reached_limit is True


def test_trigger_simulation_reports_truncation_probability() -> None:
    summary = simulate_trigger_chain(
        initial_state_factory=lambda: 0,
        should_trigger=lambda state: True,
        resolve_trigger=lambda state, rng: state + 1,
        score=lambda result: result.trigger_count,
        trials=20,
        max_triggers=3,
        seed=0,
    )

    assert summary.mean == 3
    assert summary.metadata["truncation"]["count"] == 20
    assert summary.metadata["truncation"]["probability"] == 1


def test_trigger_simulation_is_reproducible() -> None:
    kwargs = {
        "initial_state_factory": lambda: 0,
        "should_trigger": lambda state: state < 10,
        "resolve_trigger": (
            lambda state, rng: state + 1 if rng.random() < 0.5 else 10
        ),
        "score": lambda result: result.trigger_count,
        "trials": 500,
        "max_triggers": 10,
        "seed": 42,
    }

    assert simulate_trigger_chain(**kwargs) == simulate_trigger_chain(**kwargs)


def test_invalid_trigger_limit_is_rejected() -> None:
    with pytest.raises(ValueError, match="最大触发次数"):
        run_trigger_chain(
            0,
            lambda state: True,
            lambda state, rng: state,
            max_triggers=0,
        )
