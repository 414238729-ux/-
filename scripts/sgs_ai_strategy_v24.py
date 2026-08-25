"""V2.4 武将专项 AI 扩展。

本模块复用 :mod:`scripts.sgs_ai_strategy_v22` 的“先列出合法候选、再评分”
框架，只保存势·孙綝、势·辛宪英、SP郭女王和神吕布重制原型的差异化
估值与审计字段。它不是第二套规则数据库；技能是否合法仍由规则模块判断。
所有权重均为可调分析参数，不代表官方 AI 或唯一正确策略。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import isfinite
from types import MappingProxyType
from typing import Iterable, Mapping, Sequence


V24_CONTENT_PROFILE = "V2.4-pending"


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label}必须是非空字符串")
    return value.strip()


def _finite(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{label}必须是有限数值")
    result = float(value)
    if not isfinite(result):
        raise ValueError(f"{label}必须是有限数值")
    return result


def _nonnegative(value: object, label: str) -> float:
    result = _finite(value, label)
    if result < 0:
        raise ValueError(f"{label}不能小于0")
    return result


NINE_LEVEL_STRENGTH: Mapping[str, int] = MappingProxyType(
    {
        "上上": 9,
        "上中": 8,
        "上下": 7,
        "中上": 6,
        "中中": 5,
        "中下": 4,
        "下上": 3,
        "下中": 2,
        "下下": 1,
    }
)


@dataclass(frozen=True)
class StrengthReference:
    """非官方、可替换的模式强度参照。"""

    general_name: str
    landlord: float
    two_v_two: float
    identity: float
    tier: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "general_name", _text(self.general_name, "武将名"))
        for name in ("landlord", "two_v_two", "identity"):
            score = _finite(getattr(self, name), f"{name}分数")
            if not 0 <= score <= 9:
                raise ValueError("九级参照分数必须在0到9之间")
            object.__setattr__(self, name, score)
        if self.tier not in NINE_LEVEL_STRENGTH:
            raise ValueError("强度层级不在当前九级参照中")

    @property
    def equal_weight_average(self) -> float:
        return (self.landlord + self.two_v_two + self.identity) / 3


V24_STRENGTH_REFERENCES: Mapping[str, StrengthReference] = MappingProxyType(
    {
        "势·辛宪英": StrengthReference("势·辛宪英", 8.17, 8.75, 7.50, "上中"),
        "鲍信": StrengthReference("鲍信", 6.50, 6.75, 5.00, "中上"),
    }
)


SUN_CHEN_AUDIT_FIELDS = (
    "nigu.multi_discard_to_clear_categories",
    "nigu.no_card_non_givers",
    "nigu.damage_charges_created",
    "nigu.prevented_damage_charges_consumed",
    "lulian.triggers_by_basic",
    "lulian.triggers_by_trick",
    "lulian.triggers_by_equipment",
    "lulian.triggers_by_peach_or_wine_outside_turn",
    "lulian.dead_targets_filtered",
    "lulian.full_effect",
    "chengshi.forced_uses",
    "chengshi.target_self",
    "chengshi.no_legal_target",
    "chengshi.chain_damage_sequences",
)

XIN_XIANYING_AUDIT_FIELDS = (
    "xin_xianying.round_state.current_max_suit_count",
    "xin_xianying.round_state.forced_qingshi_used",
    "xin_xianying.round_state.view_events",
    "jiejie.self_activations",
    "jiejie.ally_activations",
    "jiejie.enemy_activations",
    "jiejie.cancelled_after_view",
    "jiejie.selected_suits",
    "jiejie.off_suit_cards_discarded",
    "jiejie.unlimited_slash_uses",
    "jiejie.unlimited_wine_uses",
    "jiejie.missing_suit_search_success",
    "jiejie.missing_suit_search_failure",
    "qingshi.damage_triggers",
    "qingshi.forced_triggers",
    "qingshi.self_draw_two",
    "qingshi.ally_split_draw",
    "qingshi.enemy_mutual_discard",
    "qingshi.enemy_only_discard_due_self_empty",
    "qingshi.camp_relations_revealed",
)

GUO_NUWANG_AUDIT_FIELDS = (
    "yichong.activations",
    "yichong.empty_suit_marks_created",
    "yichong.equipment_cards_gained",
    "yichong.random_hand_cards_gained",
    "bird.interceptions",
    "bird.intercepted_first_matching_card",
    "bird.original_recipient_gain_time_effects",
    "bird.original_recipient_zone_entries_blocked",
    "bird.expired_on_holder_death",
    "wufei.source_replacements",
    "wufei.lightning_exclusions",
    "wufei.source_only_effects",
    "wufei.user_only_effects",
    "wufei.same_user_source_effects_blocked",
    "wufei.source_restored_after_bird_death",
    "wufei.kills_attributed_to_bird",
)

SHEN_LUBU_AUDIT_FIELDS = (
    "shen_lubu.pool_scope",
    "shen_lubu.evidence.screenshot_or_text_a_used",
    "shen_lubu.evidence.client_observation_b_used",
    "shen_lubu.evidence.conversation_confirmation_c_used",
    "shen_lubu.rage.initial",
    "shen_lubu.rage.gained_from_dealing",
    "shen_lubu.rage.gained_from_receiving",
    "shen_lubu.rage.current",
    "wumou.converted_tricks",
    "wumou.original_target_template_used",
    "wuqian.rage_spent",
    "wuqian.marked_target_count_x",
    "wuqian.armor_invalid_target",
    "wuqian.wushuang_variant_active",
    "wuqian.slash_use_count_bonus_x",
    "wuqian.damage_card_used_without_damage",
    "wuqian.state_ended",
    "wuqian.end_phase_had_damage_card",
    "wuqian.end_phase_random_damage_card_gained",
    "wuqian.lightning_used_triggered_end",
    "wushuang_variant.slash_target_two_jink_required",
    "wushuang_variant.duel_opponent_two_slash_required",
    "wushuang_variant.one_response_card_insufficient",
    "shenfen.uses_this_play_phase",
    "shenfen.rage_spent",
    "shenfen.other_players_damage",
    "shenfen.all_equipment_discarded",
    "shenfen.four_hand_cards_discarded",
    "shenfen.final_flip",
)


@dataclass(frozen=True)
class V24DecisionAudit:
    general_name: str
    chosen_action: str
    reason: str
    legal_actions: tuple[str, ...]
    scores: Mapping[str, float]
    strategy_version: str = "V2.2"
    content_profile: str = V24_CONTENT_PROFILE
    metrics: Mapping[str, int | float | str | bool] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "general_name", _text(self.general_name, "武将名"))
        object.__setattr__(self, "chosen_action", _text(self.chosen_action, "选择动作"))
        object.__setattr__(self, "reason", _text(self.reason, "选择理由"))
        if self.chosen_action not in self.legal_actions:
            raise ValueError("选择动作必须位于合法动作集合中")
        if len(self.legal_actions) != len(set(self.legal_actions)):
            raise ValueError("合法动作不能重复")
        normalized = {key: _finite(value, f"动作 {key} 的分数") for key, value in self.scores.items()}
        if set(normalized) != set(self.legal_actions):
            raise ValueError("每个合法动作必须且只能有一个分数")
        object.__setattr__(self, "scores", MappingProxyType(normalized))
        object.__setattr__(self, "metrics", MappingProxyType(dict(self.metrics)))


@dataclass(frozen=True)
class NiguDiscardOption:
    option_id: str
    card_ids: tuple[str, ...]
    suits: tuple[str, ...]
    resource_cost: float
    cleared_category_count: int
    participant_count: int
    expected_non_givers: float
    expected_damage_events: float
    expected_cards_received: float = 0.0
    loses_required_attack_range: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "option_id", _text(self.option_id, "逆固方案ID"))
        if not 1 <= len(self.card_ids) <= 4:
            raise ValueError("逆固弃牌方案必须包含1至4张牌")
        if len(self.card_ids) != len(set(self.card_ids)):
            raise ValueError("逆固弃牌方案不能重复使用同一实体牌")
        if len(self.suits) != len(self.card_ids) or len(set(self.suits)) != len(self.suits):
            raise ValueError("逆固弃牌的花色必须与牌一一对应且两两不同")
        object.__setattr__(self, "resource_cost", _nonnegative(self.resource_cost, "弃牌资源成本"))
        if self.cleared_category_count < 0 or self.participant_count < 0:
            raise ValueError("类别数和参与者数不能小于0")
        for name in ("expected_non_givers", "expected_damage_events", "expected_cards_received"):
            value = _nonnegative(getattr(self, name), name)
            object.__setattr__(self, name, value)
        if self.expected_non_givers > self.participant_count:
            raise ValueError("预计不交牌人数不能超过参与者数")


def score_nigu_discard_option(
    option: NiguDiscardOption,
    *,
    damage_bonus_value: float = 1.0,
    category_clear_value: float = 0.8,
    received_card_value: float = 0.6,
    lost_range_penalty: float = 1.2,
) -> float:
    """按透明权重评价异花色弃牌方案。"""

    usable_charges = min(option.expected_non_givers, option.expected_damage_events)
    return (
        usable_charges * _nonnegative(damage_bonus_value, "加伤价值")
        + option.cleared_category_count * _nonnegative(category_clear_value, "清类别价值")
        + option.expected_cards_received * _nonnegative(received_card_value, "获得牌价值")
        - option.resource_cost
        - (lost_range_penalty if option.loses_required_attack_range else 0.0)
    )


def choose_sunchen_nigu_option(
    options: Sequence[NiguDiscardOption],
) -> tuple[NiguDiscardOption, V24DecisionAudit]:
    if not options:
        raise ValueError("至少需要一个合法的逆固弃牌方案")
    scores = {option.option_id: score_nigu_discard_option(option) for option in options}
    chosen = max(options, key=lambda option: scores[option.option_id])
    reason = (
        f"选择{chosen.option_id}：预计清除{chosen.cleared_category_count}个手牌类别，"
        f"可利用约{min(chosen.expected_non_givers, chosen.expected_damage_events):g}次加伤。"
    )
    return chosen, V24DecisionAudit(
        general_name="势·孙綝",
        chosen_action=chosen.option_id,
        reason=reason,
        legal_actions=tuple(option.option_id for option in options),
        scores=scores,
        metrics={
            "nigu.multi_discard_to_clear_categories": int(len(chosen.card_ids) > 1),
            "nigu.damage_charges_created": chosen.expected_non_givers,
        },
    )


def choose_sunchen_action_order(
    *,
    nigu_first_value: float,
    lulian_first_value: float,
    nigu_clears_blocking_category: bool,
) -> str:
    nigu = _finite(nigu_first_value, "先逆固价值")
    lulian = _finite(lulian_first_value, "先戮连价值")
    if nigu_clears_blocking_category:
        nigu += 0.8
    return "先逆固" if nigu >= lulian else "先使用目标牌触发戮连"


def should_give_card_to_sunchen(
    *,
    card_opportunity_cost: float,
    prevented_bonus_damage_value: float,
    prevents_immediate_kill: bool,
    card_is_equipment: bool,
) -> bool:
    cost = _nonnegative(card_opportunity_cost, "交牌机会成本")
    benefit = _nonnegative(prevented_bonus_damage_value, "阻止加伤价值")
    if card_is_equipment:
        cost += 0.5
    if prevents_immediate_kill:
        benefit += 3.0
    return benefit > cost


@dataclass(frozen=True)
class JiejieChoiceOption:
    choice: str
    front_effect_value: float
    forced_qingshi_value: float
    discarded_card_cost: float = 0.0
    enemy_benefit: float = 0.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "choice", _text(self.choice, "诫节选择"))
        if self.choice not in {"黑桃", "红桃", "梅花", "方块", "取消"}:
            raise ValueError("诫节选择只能是四种花色或取消")
        for name in (
            "front_effect_value",
            "forced_qingshi_value",
            "discarded_card_cost",
            "enemy_benefit",
        ):
            object.__setattr__(self, name, _finite(getattr(self, name), name))

    @property
    def score(self) -> float:
        return (
            self.front_effect_value
            + self.forced_qingshi_value
            - self.discarded_card_cost
            - self.enemy_benefit
        )


def choose_jiejie_option(
    options: Sequence[JiejieChoiceOption],
    *,
    actor_relation: str,
) -> tuple[JiejieChoiceOption, V24DecisionAudit]:
    if not options:
        raise ValueError("至少需要一个诫节合法选择")
    relation = _text(actor_relation, "当前回合角色关系")
    chosen = max(options, key=lambda option: option.score)
    scores = {option.choice: option.score for option in options}
    return chosen, V24DecisionAudit(
        general_name="势·辛宪英",
        chosen_action=chosen.choice,
        reason=f"对{relation}选择{chosen.choice}：按前段收益、清识收益、弃牌成本和资敌风险综合最高。",
        legal_actions=tuple(option.choice for option in options),
        scores=scores,
        metrics={f"jiejie.{relation}_activations": 1, "jiejie.cancelled_after_view": int(chosen.choice == "取消")},
    )


def plan_jiejie_suit_count_order(viewed_suit_counts: Iterable[int]) -> tuple[int, ...]:
    """优先按严格递增次序安排己方观看记录，最多保留两次强制收益。"""

    counts = tuple(viewed_suit_counts)
    if any(isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 4 for value in counts):
        raise ValueError("观看手牌花色数必须是1至4的整数")
    unique = sorted(set(counts))
    return tuple(unique[:2]) + tuple(value for value in counts if value not in unique[:2])


def should_xin_xianying_accept_damage(
    *,
    damage_cost: float,
    qingshi_expected_value: float,
    death_probability: float,
) -> bool:
    cost = _nonnegative(damage_cost, "伤害成本")
    value = _finite(qingshi_expected_value, "清识预期价值")
    death = _nonnegative(death_probability, "死亡概率")
    if death > 1:
        raise ValueError("死亡概率不能大于1")
    return value - cost - 4.0 * death > 0


@dataclass(frozen=True)
class YichongChoice:
    choice_id: str
    target_id: str
    suit: str
    immediate_equipment_value: float
    expected_hand_card_value: float
    expected_interception_value: float
    source_proxy_value: float
    source_benefit_to_holder: float = 0.0
    ally_resource_loss: float = 0.0
    gain_time_denial_value: float = 0.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "choice_id", _text(self.choice_id, "易宠方案ID"))
        object.__setattr__(self, "target_id", _text(self.target_id, "易宠目标"))
        if self.suit not in {"黑桃", "红桃", "梅花", "方块"}:
            raise ValueError("易宠必须指定一种标准花色")
        for name in (
            "immediate_equipment_value",
            "expected_hand_card_value",
            "expected_interception_value",
            "source_proxy_value",
            "source_benefit_to_holder",
            "ally_resource_loss",
            "gain_time_denial_value",
        ):
            object.__setattr__(self, name, _finite(getattr(self, name), name))

    @property
    def score(self) -> float:
        return (
            self.immediate_equipment_value
            + self.expected_hand_card_value
            + self.expected_interception_value
            + self.source_proxy_value
            + self.gain_time_denial_value
            - self.source_benefit_to_holder
            - self.ally_resource_loss
        )


def choose_yichong_target(
    choices: Sequence[YichongChoice],
) -> tuple[YichongChoice, V24DecisionAudit]:
    if not choices:
        raise ValueError("至少需要一个合法的易宠目标与花色组合")
    chosen = max(choices, key=lambda choice: choice.score)
    scores = {choice.choice_id: choice.score for choice in choices}
    return chosen, V24DecisionAudit(
        general_name="SP郭女王",
        chosen_action=chosen.choice_id,
        reason=f"选择{chosen.target_id}并指定{chosen.suit}：立即取牌、后续截牌和来源代理净收益最高。",
        legal_actions=tuple(choice.choice_id for choice in choices),
        scores=scores,
        metrics={"yichong.target": chosen.target_id, "yichong.suit": chosen.suit},
    )


def should_guo_use_damage_while_enemy_is_bird(
    *,
    direct_damage_value: float,
    enemy_source_benefit: float,
    immediate_kill_or_win_value: float = 0.0,
) -> bool:
    return (
        _finite(direct_damage_value, "直接伤害价值")
        + _finite(immediate_kill_or_win_value, "击杀或胜利价值")
        > _nonnegative(enemy_source_benefit, "敌方来源收益")
    )


def wuqian_preservation_probability(no_damage_probabilities: Iterable[float]) -> float:
    """按各目标零伤害事件独立的分析假设，估计整次用牌造成任一伤害的概率。"""

    values = tuple(no_damage_probabilities)
    if not values:
        raise ValueError("无前保留概率至少需要一个目标的零伤害概率")
    all_targets_take_no_damage = 1.0
    for value in values:
        probability = _finite(value, "零伤害概率")
        if not 0 <= probability <= 1:
            raise ValueError("零伤害概率必须在0到1之间")
        all_targets_take_no_damage *= probability
    return 1.0 - all_targets_take_no_damage


def shenfen_net_rage(actual_damage_recipient_count: int) -> int:
    if isinstance(actual_damage_recipient_count, bool) or not isinstance(actual_damage_recipient_count, int):
        raise TypeError("神愤实际受伤人数必须是整数")
    if actual_damage_recipient_count < 0:
        raise ValueError("神愤实际受伤人数不能小于0")
    return actual_damage_recipient_count - 6


@dataclass(frozen=True)
class ShenLubuRagePlan:
    action: str
    rage_cost: int
    expected_net_value: float
    preserves_wuqian: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "action", _text(self.action, "神吕布动作"))
        if isinstance(self.rage_cost, bool) or not isinstance(self.rage_cost, int) or self.rage_cost < 0:
            raise ValueError("暴怒成本必须是非负整数")
        object.__setattr__(self, "expected_net_value", _finite(self.expected_net_value, "动作预期价值"))
        if not isinstance(self.preserves_wuqian, bool):
            raise TypeError("方案是否保留无前必须是布尔值")


def choose_shen_lubu_rage_plan(
    current_rage: int,
    plans: Sequence[ShenLubuRagePlan],
) -> tuple[ShenLubuRagePlan, V24DecisionAudit]:
    if isinstance(current_rage, bool) or not isinstance(current_rage, int) or current_rage < 0:
        raise ValueError("当前暴怒必须是非负整数")
    legal = tuple(plan for plan in plans if plan.rage_cost <= current_rage)
    if not legal:
        raise ValueError("没有暴怒足够的合法方案")
    chosen = max(
        legal,
        key=lambda plan: (plan.expected_net_value, plan.preserves_wuqian),
    )
    scores = {plan.action: plan.expected_net_value for plan in legal}
    metrics: dict[str, int | float | str | bool] = {
        "shen_lubu.rage.current": current_rage,
    }
    rage_spent_key = {
        "无前": "wuqian.rage_spent",
        "神愤": "shenfen.rage_spent",
    }.get(chosen.action)
    if rage_spent_key is not None:
        metrics[rage_spent_key] = chosen.rage_cost
    return chosen, V24DecisionAudit(
        general_name="神吕布重制原型",
        chosen_action=chosen.action,
        reason=f"选择{chosen.action}：在当前{current_rage}点暴怒预算下预期净收益最高。",
        legal_actions=tuple(plan.action for plan in legal),
        scores=scores,
        metrics=metrics,
    )


def should_activate_shenfen(
    *,
    expected_enemy_loss: float,
    expected_ally_loss: float,
    lethal_or_win_value: float,
    future_rage_opportunity_cost: float,
) -> bool:
    return (
        _finite(expected_enemy_loss, "敌方预期损失")
        + _finite(lethal_or_win_value, "击杀或胜利价值")
        - _nonnegative(expected_ally_loss, "己方预期损失")
        - _nonnegative(future_rage_opportunity_cost, "未来暴怒机会成本")
        > 0
    )

