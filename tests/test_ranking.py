import math

import pytest

from scripts import rank_items


def test_ranking_respects_weight_and_direction() -> None:
    results = rank_items(
        items={
            "方案甲": {"伤害": 10, "耗时": 3},
            "方案乙": {"伤害": 8, "耗时": 2},
        },
        weights={"伤害": 0.6, "耗时": 0.4},
        directions={"伤害": "higher", "耗时": "lower"},
    )

    assert [result.name for result in results] == ["方案甲", "方案乙"]
    assert [result.rank for result in results] == [1, 2]
    assert math.isclose(results[0].score, 0.6)
    assert math.isclose(results[1].score, 0.4)


def test_equal_criterion_uses_neutral_half_score() -> None:
    results = rank_items(
        items={"甲": {"指标": 5}, "乙": {"指标": 5}},
        weights={"指标": 1},
    )

    assert [result.rank for result in results] == [1, 1]
    assert [result.score for result in results] == [0.5, 0.5]
    assert all(
        result.normalized_scores["指标"] == 0.5 for result in results
    )


def test_ties_use_dense_ranks_and_preserve_input_order() -> None:
    results = rank_items(
        items={
            "甲": {"指标": 10},
            "乙": {"指标": 10},
            "丙": {"指标": 0},
        },
        weights={"指标": 1},
    )

    assert [result.name for result in results] == ["甲", "乙", "丙"]
    assert [result.rank for result in results] == [1, 1, 2]


def test_weights_are_normalized() -> None:
    results = rank_items(
        items={"甲": {"A": 1, "B": 1}, "乙": {"A": 0, "B": 0}},
        weights={"A": 2, "B": 2},
    )

    assert results[0].score == 1
    assert results[0].contributions == {"A": 0.5, "B": 0.5}


@pytest.mark.parametrize(
    "weights",
    [
        {"指标": -1},
        {"指标": 0},
        {"指标": math.inf},
    ],
)
def test_invalid_weights_are_rejected(weights: dict[str, float]) -> None:
    with pytest.raises(ValueError):
        rank_items({"甲": {"指标": 1}}, weights)


def test_missing_metric_is_rejected() -> None:
    with pytest.raises(ValueError, match="缺少指标"):
        rank_items(
            {"甲": {"A": 1}, "乙": {"B": 2}},
            {"A": 1},
        )


def test_invalid_direction_is_rejected() -> None:
    with pytest.raises(ValueError, match="方向必须"):
        rank_items(
            {"甲": {"指标": 1}},
            {"指标": 1},
            {"指标": "sideways"},
        )
