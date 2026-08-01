import pytest

from scripts import draw_without_replacement, simulate_draws


def test_empty_deck_allows_zero_draws() -> None:
    assert draw_without_replacement([], 0, seed=0) == []


def test_empty_deck_rejects_positive_draws() -> None:
    with pytest.raises(ValueError, match="不能超过"):
        draw_without_replacement([], 1, seed=0)


def test_draw_count_larger_than_deck_is_rejected() -> None:
    with pytest.raises(ValueError, match="不能超过"):
        draw_without_replacement([1, 2], 3, seed=0)


def test_negative_draw_count_is_rejected() -> None:
    with pytest.raises(ValueError, match="抽取数量"):
        draw_without_replacement([1], -1, seed=0)


def test_direct_draw_is_reproducible_with_fixed_seed() -> None:
    deck = list(range(20))

    assert draw_without_replacement(deck, 5, seed=42) == (
        draw_without_replacement(deck, 5, seed=42)
    )


def test_simulation_matches_exact_without_replacement_distribution() -> None:
    # 四个位置中有两个成功和两个失败。不计顺序抽两张时：
    # P(0 成功)=1/6，P(1 成功)=4/6，P(2 成功)=1/6。
    summary = simulate_draws(
        [1, 1, 0, 0],
        draw_count=2,
        score=sum,
        trials=50_000,
        seed=20260725,
    )
    exact = {0: 1 / 6, 1: 4 / 6, 2: 1 / 6}

    for outcome, probability in exact.items():
        assert abs(
            summary.distribution[outcome].probability - probability
        ) < 0.02
    assert abs(summary.mean - 1.0) < 0.02


def test_draw_simulation_is_reproducible() -> None:
    kwargs = {
        "deck": ["A", "A", "B", "C"],
        "draw_count": 2,
        "score": lambda hand: hand.count("A"),
        "trials": 1_000,
        "seed": 7,
    }

    assert simulate_draws(**kwargs) == simulate_draws(**kwargs)
