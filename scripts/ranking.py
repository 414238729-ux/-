"""加权评分与稳定稠密排名。"""

from __future__ import annotations

import math
from dataclasses import dataclass
from numbers import Real
from typing import Mapping

from ._validation import ensure_finite_real

HIGHER = "higher"
LOWER = "lower"
VALID_DIRECTIONS = {HIGHER, LOWER}


@dataclass(frozen=True)
class RankedItem:
    """一个对象的综合评分、排名和指标贡献。"""

    name: str
    rank: int
    score: float
    normalized_scores: dict[str, float]
    contributions: dict[str, float]

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "rank": self.rank,
            "score": self.score,
            "normalized_scores": dict(self.normalized_scores),
            "contributions": dict(self.contributions),
        }


def rank_items(
    items: Mapping[str, Mapping[str, Real]],
    weights: Mapping[str, Real],
    directions: Mapping[str, str] | None = None,
    *,
    normalize: bool = True,
) -> list[RankedItem]:
    """按权重和指标方向计算综合分，并使用稳定的稠密排名。

    默认对各指标做 min-max 标准化。某指标所有对象取值相同时，所有对象
    在该指标上的标准化得分均为 0.5。未在 ``directions`` 中出现的指标
    默认按 ``higher`` 处理。
    """

    if not isinstance(items, Mapping):
        raise TypeError("items 必须是“对象名 -> 指标映射”的映射")
    if not items:
        raise ValueError("待排名对象不能为空")
    if not isinstance(weights, Mapping):
        raise TypeError("weights 必须是“指标名 -> 权重”的映射")
    if not weights:
        raise ValueError("权重不能为空")
    if directions is not None and not isinstance(directions, Mapping):
        raise TypeError("directions 必须是“指标名 -> 方向”的映射")
    if not isinstance(normalize, bool):
        raise TypeError("normalize 必须是布尔值")

    criteria = list(weights.keys())
    for criterion in criteria:
        if not isinstance(criterion, str) or not criterion:
            raise TypeError("指标名必须是非空字符串")

    numeric_weights: dict[str, float] = {}
    for criterion, weight in weights.items():
        value = ensure_finite_real(weight, f"指标“{criterion}”的权重")
        if value < 0:
            raise ValueError(f"指标“{criterion}”的权重不能为负数")
        numeric_weights[criterion] = value
    total_weight = math.fsum(numeric_weights.values())
    if total_weight <= 0:
        raise ValueError("至少一个指标权重必须大于 0")
    normalized_weights = {
        criterion: weight / total_weight
        for criterion, weight in numeric_weights.items()
    }

    direction_map = {criterion: HIGHER for criterion in criteria}
    if directions is not None:
        unknown_directions = set(directions) - set(criteria)
        if unknown_directions:
            names = "、".join(sorted(str(name) for name in unknown_directions))
            raise ValueError(f"方向映射包含未加权指标：{names}")
        for criterion, direction in directions.items():
            if direction not in VALID_DIRECTIONS:
                raise ValueError(
                    f"指标“{criterion}”的方向必须是 "
                    f"'{HIGHER}' 或 '{LOWER}'"
                )
            direction_map[criterion] = direction

    numeric_items: list[tuple[int, str, dict[str, float]]] = []
    for index, (name, values) in enumerate(items.items()):
        if not isinstance(name, str) or not name:
            raise TypeError("对象名必须是非空字符串")
        if not isinstance(values, Mapping):
            raise TypeError(f"对象“{name}”的指标必须是映射")
        missing = [criterion for criterion in criteria if criterion not in values]
        if missing:
            raise ValueError(
                f"对象“{name}”缺少指标：{'、'.join(missing)}"
            )
        numeric_values = {
            criterion: ensure_finite_real(
                values[criterion],
                f"对象“{name}”的指标“{criterion}”",
            )
            for criterion in criteria
        }
        numeric_items.append((index, name, numeric_values))

    criterion_ranges = {
        criterion: (
            min(values[criterion] for _, _, values in numeric_items),
            max(values[criterion] for _, _, values in numeric_items),
        )
        for criterion in criteria
    }

    scored: list[
        tuple[int, str, float, dict[str, float], dict[str, float]]
    ] = []
    for index, name, values in numeric_items:
        criterion_scores: dict[str, float] = {}
        contributions: dict[str, float] = {}

        for criterion in criteria:
            value = values[criterion]
            direction = direction_map[criterion]
            if normalize:
                minimum, maximum = criterion_ranges[criterion]
                if math.isclose(
                    minimum,
                    maximum,
                    rel_tol=0.0,
                    abs_tol=0.0,
                ):
                    criterion_score = 0.5
                elif direction == HIGHER:
                    criterion_score = (value - minimum) / (maximum - minimum)
                else:
                    criterion_score = (maximum - value) / (maximum - minimum)
            else:
                criterion_score = value if direction == HIGHER else -value

            criterion_scores[criterion] = criterion_score
            contributions[criterion] = (
                criterion_score * normalized_weights[criterion]
            )

        total_score = math.fsum(contributions.values())
        scored.append(
            (index, name, total_score, criterion_scores, contributions)
        )

    scored.sort(key=lambda item: (-item[2], item[0]))
    ranked: list[RankedItem] = []
    current_rank = 0
    previous_score: float | None = None
    for _, name, score, criterion_scores, contributions in scored:
        if previous_score is None or not math.isclose(
            score,
            previous_score,
            rel_tol=1e-12,
            abs_tol=1e-12,
        ):
            current_rank += 1
            previous_score = score
        ranked.append(
            RankedItem(
                name=name,
                rank=current_rank,
                score=score,
                normalized_scores=criterion_scores,
                contributions=contributions,
            )
        )
    return ranked
