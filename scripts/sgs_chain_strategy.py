"""【铁索连环】组合的轻量理性决策模型。

本模块只评估用户指定候选策略的团队期望净收益，不改变卡牌合法效果，
也不读取角色依法不知道的阵营或手牌信息。
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from enum import Enum
from math import isfinite
from typing import Iterable, Sequence

from ._validation import ensure_int_at_least


class ChainStrategyKind(Enum):
    ENEMY_CHAIN = "只横置敌方"
    DIRECT_FIRE_ATTACK = "直接火攻敌方"
    SELF_IGNITION = "自我引火传导"
    ALLY_IGNITION = "友军引火传导"
    HOLD_OR_RECAST = "保留或重铸"


@dataclass(frozen=True)
class ChainPropagationAssessment:
    will_propagate: bool
    conditional_certainty: bool
    reason: str


def assess_chain_propagation(
    *,
    entry_actual_damage: int,
    entry_was_chained: bool,
    target_still_chained: bool,
    game_over_before_target: bool,
) -> ChainPropagationAssessment:
    """判断初始属性伤害成功后，指定目标是否进入铁索传导。"""

    damage = ensure_int_at_least(entry_actual_damage, "传导入口实际属性伤害", 0)
    for value, name in (
        (entry_was_chained, "传导入口横置标识"),
        (target_still_chained, "目标当前横置标识"),
        (game_over_before_target, "目标前游戏结束标识"),
    ):
        if not isinstance(value, bool):
            raise TypeError(f"{name}必须是布尔值")
    if damage == 0:
        return ChainPropagationAssessment(False, False, "初始属性伤害未实际造成")
    if not entry_was_chained:
        return ChainPropagationAssessment(False, False, "传导入口受伤时未横置")
    if game_over_before_target:
        return ChainPropagationAssessment(False, False, "目标结算前游戏已经结束")
    if not target_still_chained:
        return ChainPropagationAssessment(False, False, "目标在传导时点已解除横置")
    return ChainPropagationAssessment(
        True,
        True,
        "初始属性伤害已经造成，目标仍横置且游戏未结束；传导不再要求闪或重新火攻",
    )


@dataclass(frozen=True)
class FireAttackSuccessEstimate:
    probability: float | None
    exact: bool
    uses_omniscient_information: bool
    reason: str


def _prepare_suits(suits: Sequence[str], name: str) -> tuple[str, ...]:
    if suits is None:
        raise TypeError(f"{name}不能是 None")
    try:
        prepared = tuple(suits)
    except TypeError as exc:
        raise TypeError(f"{name}必须是可迭代序列") from exc
    if any(not isinstance(suit, str) or not suit.strip() for suit in prepared):
        raise ValueError(f"{name}中的花色必须是非空字符串")
    return prepared


def estimate_cooperative_fire_attack_success(
    target_hand_suits: Sequence[str],
    discarder_available_suits: Sequence[str],
    *,
    same_character: bool,
    target_hand_fully_known: bool,
    unknown_success_probability: float | None = None,
    uses_omniscient_information: bool = False,
) -> FireAttackSuccessEstimate:
    """估计自我或友军火攻的展示与同花色弃牌成功率。"""

    target_suits = _prepare_suits(target_hand_suits, "目标手牌花色")
    discard_suits = _prepare_suits(discarder_available_suits, "可弃手牌花色")
    for value, name in (
        (same_character, "是否为自我火攻"),
        (target_hand_fully_known, "目标手牌完全已知标识"),
        (uses_omniscient_information, "全知信息标识"),
    ):
        if not isinstance(value, bool):
            raise TypeError(f"{name}必须是布尔值")

    if not target_suits:
        return FireAttackSuccessEstimate(0.0, True, uses_omniscient_information, "目标没有手牌")
    if target_hand_fully_known:
        if same_character:
            counts = Counter(target_suits)
            success = any(
                count >= 2 and suit in discard_suits
                for suit, count in counts.items()
            )
            reason = (
                "存在两张不同实体的同花色手牌，可分别用于展示和弃置"
                if success
                else "没有两张可分别承担展示与弃置的同花色实体手牌"
            )
        else:
            success = bool(set(target_suits) & set(discard_suits))
            reason = (
                "已知队友可展示使用者能够另行弃置同花色牌的手牌"
                if success
                else "已知队友手牌花色与使用者可弃花色不匹配"
            )
        return FireAttackSuccessEstimate(
            1.0 if success else 0.0,
            True,
            uses_omniscient_information,
            reason,
        )

    if unknown_success_probability is None:
        return FireAttackSuccessEstimate(
            None,
            False,
            uses_omniscient_information,
            "目标手牌信息不完整，必须另行提供概率模型，不能自动按100%",
        )
    probability = float(unknown_success_probability)
    if not isfinite(probability) or probability < 0 or probability > 1:
        raise ValueError("未知手牌下的火攻成功概率必须是0到1之间的有限数值")
    return FireAttackSuccessEstimate(
        probability,
        False,
        uses_omniscient_information,
        "根据合法已知信息与显式概率模型估计，不是必然成功",
    )


def _finite_nonnegative(value: float, name: str) -> float:
    number = float(value)
    if not isfinite(number) or number < 0:
        raise ValueError(f"{name}必须是非负有限数值")
    return number


@dataclass(frozen=True)
class ChainStrategyEvaluation:
    strategy: ChainStrategyKind
    legal: bool
    information_legal: bool
    success_probability: float
    score: float
    uses_omniscient_information: bool
    omniscient_assumption_disclosed: bool


def evaluate_chain_strategy(
    strategy: ChainStrategyKind | str,
    *,
    legal: bool = True,
    information_legal: bool = True,
    success_probability: float = 1.0,
    enemy_expected_hp_loss: float = 0.0,
    enemy_kill_value: float = 0.0,
    friendly_damage_skill_benefit: float = 0.0,
    enemy_action_denial_value: float = 0.0,
    multi_target_value: float = 0.0,
    friendly_expected_hp_loss: float = 0.0,
    friendly_death_risk: float = 0.0,
    rescue_resource_cost: float = 0.0,
    card_resource_cost: float = 0.0,
    enemy_damage_benefit: float = 0.0,
    failure_cost: float = 0.0,
    reverse_chain_risk: float = 0.0,
    uses_omniscient_information: bool = False,
    omniscient_assumption_disclosed: bool = False,
) -> ChainStrategyEvaluation:
    """按团队净收益计算一项合法候选策略的分数。"""

    if isinstance(strategy, str):
        try:
            strategy = ChainStrategyKind(strategy)
        except ValueError as exc:
            raise ValueError("未知的铁索组合策略") from exc
    if not isinstance(strategy, ChainStrategyKind):
        raise TypeError("铁索组合策略必须是 ChainStrategyKind 或其中文值")
    for value, name in (
        (legal, "规则合法标识"),
        (information_legal, "信息合法标识"),
        (uses_omniscient_information, "全知信息标识"),
        (omniscient_assumption_disclosed, "全知假设披露标识"),
    ):
        if not isinstance(value, bool):
            raise TypeError(f"{name}必须是布尔值")
    if uses_omniscient_information and not omniscient_assumption_disclosed:
        raise ValueError("使用全知身份或手牌信息时必须明确披露为计算假设")

    probability = float(success_probability)
    if not isfinite(probability) or probability < 0 or probability > 1:
        raise ValueError("策略成功概率必须是0到1之间的有限数值")
    positives = sum(
        _finite_nonnegative(value, name)
        for value, name in (
            (enemy_expected_hp_loss, "敌方预期体力损失"),
            (enemy_kill_value, "敌方击杀价值"),
            (friendly_damage_skill_benefit, "己方受伤技能收益"),
            (enemy_action_denial_value, "敌方行动受限价值"),
            (multi_target_value, "多目标传导价值"),
        )
    )
    success_costs = sum(
        _finite_nonnegative(value, name)
        for value, name in (
            (friendly_expected_hp_loss, "己方预期体力损失"),
            (friendly_death_risk, "己方死亡风险"),
            (rescue_resource_cost, "救援资源成本"),
            (enemy_damage_benefit, "敌方受伤收益"),
            (reverse_chain_risk, "反向属性伤害风险"),
        )
    )
    fixed_card_cost = _finite_nonnegative(card_resource_cost, "卡牌资源成本")
    failed_cost = _finite_nonnegative(failure_cost, "失败概率成本")
    score = probability * (positives - success_costs) - fixed_card_cost
    score -= (1 - probability) * failed_cost
    return ChainStrategyEvaluation(
        strategy=strategy,
        legal=legal,
        information_legal=information_legal,
        success_probability=probability,
        score=score,
        uses_omniscient_information=uses_omniscient_information,
        omniscient_assumption_disclosed=omniscient_assumption_disclosed,
    )


def select_best_chain_strategy(
    candidates: Iterable[ChainStrategyEvaluation],
) -> ChainStrategyEvaluation:
    """稳定选择团队净收益最高的合法方案，不进行随机目标选择。"""

    if candidates is None:
        raise TypeError("铁索策略候选不能是 None")
    try:
        prepared = tuple(candidates)
    except TypeError as exc:
        raise TypeError("铁索策略候选必须是可迭代序列") from exc
    if not prepared:
        raise ValueError("铁索策略候选不能为空")
    if any(not isinstance(item, ChainStrategyEvaluation) for item in prepared):
        raise TypeError("每个铁索策略候选都必须是 ChainStrategyEvaluation")
    legal = [item for item in prepared if item.legal and item.information_legal]
    if not legal:
        raise ValueError("没有同时满足规则与信息限制的铁索策略")
    return max(legal, key=lambda item: item.score)
