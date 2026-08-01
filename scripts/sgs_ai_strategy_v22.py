"""三国杀武将 AI 与反制规范 V2.2 的轻量、可解释策略层。

本模块不改写卡牌或技能规则，也不维护第二份武将数据库。调用方应先由
规则层产生完整合法动作，再把当前依法可知的信息交给这里评分。策略层
不得删除合法目标；尤其“响应”和“不响应”必须同时进入候选。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Iterable, Mapping, Sequence

from ._validation import ensure_finite_real, ensure_int_at_least


STRATEGY_VERSION = "V2.2"


def _nonempty(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label}必须是非空字符串")
    return value.strip()


def _boolean(value: object, label: str) -> bool:
    if not isinstance(value, bool):
        raise TypeError(f"{label}必须是布尔值")
    return value


def _finite(value: object, label: str) -> float:
    return ensure_finite_real(value, label)


def _nonnegative(value: object, label: str) -> float:
    number = _finite(value, label)
    if number < 0:
        raise ValueError(f"{label}必须是非负有限数值")
    return number


def _coerce_enum(value: object, enum_type: type[Enum], label: str) -> Enum:
    if isinstance(value, enum_type):
        return value
    try:
        return enum_type(value)
    except (TypeError, ValueError) as exc:
        allowed = "、".join(str(member.value) for member in enum_type)
        raise ValueError(f"{label}只能是：{allowed}") from exc


def _text_tuple(values: Iterable[str], label: str) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise TypeError(f"{label}必须是字符串序列")
    result = tuple(_nonempty(item, label) for item in values)
    if len(set(result)) != len(result):
        raise ValueError(f"{label}不能重复")
    return result


@dataclass(frozen=True)
class GeneralPolicy:
    """按需记录参战武将的策略差异，不重复存储技能全文。"""

    core_plan: str
    core_resources: tuple[str, ...] = ()
    skill_synergies: tuple[str, ...] = ()
    card_synergies: tuple[str, ...] = ()
    power_spikes: tuple[str, ...] = ()
    failure_states: tuple[str, ...] = ()
    hold_rules: tuple[str, ...] = ()
    activation_rules: tuple[str, ...] = ()
    action_order_rules: tuple[str, ...] = ()
    identity_adjustments: tuple[str, ...] = ()
    seat_adjustments: tuple[str, ...] = ()
    opponent_counterplay: tuple[str, ...] = ()
    audit_metrics: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "core_plan", _nonempty(self.core_plan, "核心计划"))
        for field_name in vars(self):
            if field_name == "core_plan":
                continue
            object.__setattr__(
                self,
                field_name,
                _text_tuple(getattr(self, field_name), field_name),
            )


@dataclass(frozen=True)
class CounterplayProfile:
    depends_on: tuple[str, ...] = ()
    power_spikes: tuple[str, ...] = ()
    vulnerable_to: tuple[str, ...] = ()
    threat_tags: tuple[str, ...] = ()
    archetype_overrides: tuple[str, ...] = ()
    specific_matchups: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for field_name in vars(self):
            object.__setattr__(
                self,
                field_name,
                _text_tuple(getattr(self, field_name), field_name),
            )


@dataclass(frozen=True)
class DynamicCardValue:
    base_utility: float = 0.0
    skill_synergy: float = 0.0
    sequence_plan_value: float = 0.0
    kill_or_rescue_value: float = 0.0
    opportunity_cost: float = 0.0
    counterplay_risk: float = 0.0

    def __post_init__(self) -> None:
        for field_name, value in vars(self).items():
            object.__setattr__(self, field_name, _finite(value, field_name))

    @property
    def total(self) -> float:
        return (
            self.base_utility
            + self.skill_synergy
            + self.sequence_plan_value
            + self.kill_or_rescue_value
            - self.opportunity_cost
            - self.counterplay_risk
        )


@dataclass(frozen=True)
class StrategyAction:
    """规则层生成的一个动作；合法动作不得因策略偏好被删除。"""

    action_id: str
    legal: bool = True
    target_id: str | None = None
    immediate_value: float = 0.0
    followup_value: float = 0.0
    synergy_value: float = 0.0
    opportunity_cost: float = 0.0
    counter_risk: float = 0.0
    reason: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "action_id", _nonempty(self.action_id, "动作标识"))
        object.__setattr__(self, "legal", _boolean(self.legal, "动作合法标识"))
        if self.target_id is not None:
            object.__setattr__(self, "target_id", _nonempty(self.target_id, "目标标识"))
        for field_name in (
            "immediate_value",
            "followup_value",
            "synergy_value",
            "opportunity_cost",
            "counter_risk",
        ):
            object.__setattr__(self, field_name, _finite(getattr(self, field_name), field_name))
        if not isinstance(self.reason, str):
            raise TypeError("动作理由必须是字符串")

    @property
    def total_value(self) -> float:
        return (
            self.immediate_value
            + self.followup_value
            + self.synergy_value
            - self.opportunity_cost
            - self.counter_risk
        )


@dataclass(frozen=True)
class V22AuditMetrics:
    """专项武将的统一计数；合法动作误剪枝必须始终为零。"""

    core_combo_attempts: int = 0
    core_combo_successes: int = 0
    ordinary_attack_skipped_to_hold_resources: int = 0
    opponent_specific_counterplays: int = 0
    incorrectly_pruned_legal_actions: int = 0

    def __post_init__(self) -> None:
        for field_name, value in vars(self).items():
            ensure_int_at_least(value, field_name, 0)
        if self.core_combo_successes > self.core_combo_attempts:
            raise ValueError("核心组合成功次数不能超过尝试次数")
        if self.incorrectly_pruned_legal_actions != 0:
            raise ValueError("V2.2 不允许因策略剪枝删除合法动作")


@dataclass(frozen=True)
class DecisionAudit:
    strategy_version: str
    legal_actions: tuple[str, ...]
    rejected_actions: tuple[str, ...]
    chosen_action: str
    immediate_value: float
    followup_value: float
    synergy_value: float
    opportunity_cost: float
    counter_risk: float
    hidden_information_used: tuple[str, ...]
    rule_or_strategy_source: str
    reason: str
    incorrectly_pruned_legal_actions: int = 0
    special_metrics: V22AuditMetrics = field(default_factory=V22AuditMetrics)


def choose_v22_action(
    actions: Sequence[StrategyAction],
    *,
    hidden_information_used: Iterable[str] = (),
    authorized_information: Iterable[str] = (),
    source: str = "分析约定：统一AI武将与反制规范V2.2",
    special_metrics: V22AuditMetrics | None = None,
) -> DecisionAudit:
    """对全部合法动作评分，并生成可审计且不含越权信息的选择。"""

    if isinstance(actions, (str, bytes)) or not isinstance(actions, Sequence):
        raise TypeError("策略动作必须是序列")
    candidates = tuple(actions)
    if not candidates:
        raise ValueError("至少需要一个策略动作")
    if any(not isinstance(action, StrategyAction) for action in candidates):
        raise TypeError("策略动作必须是 StrategyAction")
    action_ids = tuple(action.action_id for action in candidates)
    if len(set(action_ids)) != len(action_ids):
        raise ValueError("策略动作标识不能重复")

    used = _text_tuple(hidden_information_used, "使用的信息字段")
    authorized = set(_text_tuple(authorized_information, "授权信息字段"))
    unauthorized = tuple(item for item in used if item not in authorized)
    if unauthorized:
        raise ValueError("决策使用了未授权隐藏信息：" + "、".join(unauthorized))
    if special_metrics is None:
        metrics = V22AuditMetrics()
    elif isinstance(special_metrics, V22AuditMetrics):
        metrics = special_metrics
    else:
        raise TypeError("专项审计指标必须是 V22AuditMetrics 或 None")

    legal = tuple(action for action in candidates if action.legal)
    if not legal:
        raise ValueError("当前没有合法动作")
    chosen = max(legal, key=lambda action: action.total_value)
    rejected = tuple(
        action.action_id
        for action in candidates
        if action.action_id != chosen.action_id
    )
    reason = chosen.reason.strip() or (
        f"在 {len(legal)} 个完整合法候选中总价值最高：{chosen.total_value:.3f}"
    )
    return DecisionAudit(
        strategy_version=STRATEGY_VERSION,
        legal_actions=tuple(action.action_id for action in legal),
        rejected_actions=rejected,
        chosen_action=chosen.action_id,
        immediate_value=chosen.immediate_value,
        followup_value=chosen.followup_value,
        synergy_value=chosen.synergy_value,
        opportunity_cost=chosen.opportunity_cost,
        counter_risk=chosen.counter_risk,
        hidden_information_used=used,
        rule_or_strategy_source=_nonempty(source, "规则或策略来源"),
        reason=reason,
        incorrectly_pruned_legal_actions=0,
        special_metrics=metrics,
    )


def build_optional_response_actions(
    *,
    effect_cost: float,
    response_card_cost: float,
    response_followup_risk: float = 0.0,
    no_response_followup_value: float = 0.0,
    response_card_available: bool = True,
    skill_response_available: bool = False,
    skill_response_cost: float = 0.0,
) -> tuple[StrategyAction, ...]:
    """同时生成实体响应、不响应及可选技能响应，不执行“有牌必响应”。"""

    cost = _nonnegative(effect_cost, "不响应效果成本")
    card_cost = _nonnegative(response_card_cost, "响应牌机会成本")
    followup_risk = _nonnegative(response_followup_risk, "响应后续风险")
    no_response_value = _finite(no_response_followup_value, "不响应后续价值")
    card_available = _boolean(response_card_available, "实体响应牌可用标识")
    skill_available = _boolean(skill_response_available, "技能响应可用标识")
    skill_cost = _nonnegative(skill_response_cost, "技能响应成本")
    actions = [
        StrategyAction(
            "do_not_respond",
            immediate_value=-cost,
            followup_value=no_response_value,
            reason="不响应并承受效果，同时保留响应资源",
        ),
    ]
    if card_available:
        actions.insert(
            0,
            StrategyAction(
                "respond_with_card",
                immediate_value=cost,
                opportunity_cost=card_cost,
                counter_risk=followup_risk,
                reason="使用或打出响应牌，避免当前效果但支付牌与后续风险",
            ),
        )
    if skill_available:
        actions.append(
            StrategyAction(
                "respond_with_skill_or_equipment",
                immediate_value=cost,
                opportunity_cost=skill_cost,
                reason="以技能或装备提供当前响应",
            )
        )
    return tuple(actions)


@dataclass(frozen=True)
class DynamicTauntInput:
    target_id: str
    kill_and_number_value: float = 0.0
    immediate_threat: float = 0.0
    counter_value: float = 0.0
    growth_and_burst_value: float = 0.0
    near_term_kill_probability_value: float = 0.0
    team_focus_efficiency: float = 0.0
    resource_and_turn_cost: float = 0.0
    defense_and_rescue_cost: float = 0.0
    on_damage_and_retaliation_risk: float = 0.0
    death_or_identity_penalty: float = 0.0
    inaccessible_cost: float = 0.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "target_id", _nonempty(self.target_id, "嘲讽目标"))
        for field_name in vars(self):
            if field_name != "target_id":
                object.__setattr__(self, field_name, _finite(getattr(self, field_name), field_name))

    @property
    def score(self) -> float:
        return (
            self.kill_and_number_value
            + self.immediate_threat
            + self.counter_value
            + self.growth_and_burst_value
            + self.near_term_kill_probability_value
            + self.team_focus_efficiency
            - self.resource_and_turn_cost
            - self.defense_and_rescue_cost
            - self.on_damage_and_retaliation_risk
            - self.death_or_identity_penalty
            - self.inaccessible_cost
        )


# ---------------------------------------------------------------------------
# 沙摩柯


@dataclass(frozen=True)
class ShamokeWeaponDecision:
    should_swap: bool
    keep_value: float
    swap_value: float
    reason: str


def evaluate_shamoke_weapon_swap(
    *,
    high_range_triggered: bool,
    original_weapon_value: float,
    replacement_weapon_name: str,
    replacement_weapon_value: float,
    slash_count: int = 0,
    need_original_reach: bool = False,
    next_turn_jili_value: float = 0.0,
    exposure_risk: float = 0.0,
    immediate_kill_value: float = 0.0,
    unrealized_current_jili_value: float = 0.0,
) -> ShamokeWeaponDecision:
    """高范围档位兑现后重新评价换装；低范围不自动等于应换。"""

    triggered = _boolean(high_range_triggered, "高范围蒺藜已触发标识")
    original = _finite(original_weapon_value, "原武器价值")
    name = _nonempty(replacement_weapon_name, "替换武器名称")
    replacement = _finite(replacement_weapon_value, "替换武器价值")
    slashes = ensure_int_at_least(slash_count, "当前可用杀数量", 0)
    need_reach = _boolean(need_original_reach, "仍需原武器距离标识")
    next_jili = _finite(next_turn_jili_value, "下回合蒺藜价值")
    exposure = _nonnegative(exposure_risk, "提前暴露风险")
    kill_value = _nonnegative(immediate_kill_value, "替换武器即时击杀价值")
    unrealized = _nonnegative(unrealized_current_jili_value, "尚未兑现的本回合蒺藜价值")
    keep_value = original + (2.0 if need_reach else 0.0) + (0.0 if triggered else unrealized)
    crossbow_value = 1.25 * max(slashes - 1, 0) if name == "诸葛连弩" else 0.0
    swap_value = replacement + crossbow_value + next_jili + kill_value - exposure
    should_swap = swap_value > keep_value
    if not triggered and should_swap:
        reason = "虽未兑现当前高范围档位，但替换武器的即时击杀或组合净值更高"
    elif not triggered:
        reason = "尚未兑现的当前蒺藜档位与原武器价值更高，暂不提前换装"
    elif should_swap:
        reason = "原武器本回合档位已兑现，替换武器的连续输出与后续牌序净值更高"
    else:
        reason = "保留原武器的距离或即时技能价值仍不低于换装收益"
    return ShamokeWeaponDecision(should_swap, keep_value, swap_value, reason)


@dataclass(frozen=True)
class ShamokeDisruptionDecision:
    wait_for_count_advance: bool
    direct_value: float
    delayed_value: float
    reason: str


def evaluate_shamoke_weapon_disruption(
    *,
    current_count: int,
    current_range: int,
    response_likely: bool,
    can_force_response_before_disruption: bool,
    key_weapon_removal_value: float = 0.0,
    immediate_kill_value: float = 0.0,
    nullification_risk: float = 0.0,
    post_removal_attack_range: int = 1,
) -> ShamokeDisruptionDecision:
    count = ensure_int_at_least(current_count, "沙摩柯本回合计数", 0)
    attack_range = ensure_int_at_least(current_range, "沙摩柯攻击范围", 1)
    response = _boolean(response_likely, "沙摩柯响应可能标识")
    force = _boolean(can_force_response_before_disruption, "可先推进计数标识")
    key_value = _nonnegative(key_weapon_removal_value, "关键武器移除价值")
    kill_value = _nonnegative(immediate_kill_value, "即时击杀价值")
    nullification = _nonnegative(nullification_risk, "无懈风险")
    post_range = ensure_int_at_least(post_removal_attack_range, "拆除后实际攻击范围", 1)
    gifted_draw = (
        float(post_range)
        if attack_range != post_range and response and count + 1 == post_range
        else 0.0
    )
    direct = key_value + kill_value - gifted_draw - nullification
    delayed = key_value + kill_value - 0.25 * nullification if force and gifted_draw else direct
    wait = force and gifted_draw > 0 and delayed > direct and kill_value < 3.0
    reason = (
        "先令其实际使用或打出牌推进计数，再拆武器，避免拆成范围1后赠送摸牌"
        if wait
        else "关键装备或击杀即时价值更高，或当前无法可靠推进计数"
    )
    return ShamokeDisruptionDecision(wait, direct, delayed, reason)


@dataclass(frozen=True)
class ShamokeProbeDecision:
    adjusted_attack_value: float
    critical_response_would_trigger_jili: bool
    should_probe: bool
    reason: str


def evaluate_attack_into_shamoke(
    *,
    current_count: int,
    attack_range: int,
    base_attack_value: float,
    response_likely: bool,
    certain_kill: bool = False,
    strong_control: bool = False,
    target_known_unable_to_respond: bool = False,
) -> ShamokeProbeDecision:
    """评估攻击方是否应在蒺藜回合外临界计数继续普通试探。"""

    count = ensure_int_at_least(current_count, "沙摩柯本回合计数", 0)
    attack = ensure_int_at_least(attack_range, "沙摩柯攻击范围", 1)
    base = _finite(base_attack_value, "普通试探基础价值")
    response = _boolean(response_likely, "沙摩柯可能响应标识")
    kill = _boolean(certain_kill, "确定击杀标识")
    control = _boolean(strong_control, "强控制标识")
    unable = _boolean(target_known_unable_to_respond, "已知不能响应标识")
    critical = count + 1 == attack and response and not unable
    penalty = float(attack) if critical and not (kill or control) else 0.0
    bonus = 5.0 if kill else (2.5 if control else 0.0)
    adjusted = base + bonus - penalty
    should_probe = adjusted > 0
    reason = (
        "临界响应会触发蒺藜，普通试探降权"
        if critical and not (kill or control)
        else "击杀、强控制或已知不能响应覆盖临界计数顾虑"
    )
    return ShamokeProbeDecision(adjusted, critical, should_probe, reason)


def choose_shamoke_slash_response(
    *,
    current_count: int,
    attack_range: int,
    damage: int = 1,
    first_qinglong_slash: bool = False,
    likely_followup_slash: bool = False,
    lethal: bool = False,
    wine_buffed: bool = False,
    dangerous_elemental_chain: bool = False,
    high_hit_bonus: bool = False,
    response_card_cost: float = 1.0,
    response_card_available: bool = True,
) -> DecisionAudit:
    """青龙首杀也保留“不闪”候选；致命、酒杀和危险属性链可覆盖。"""

    count = ensure_int_at_least(current_count, "沙摩柯本回合计数", 0)
    attack = ensure_int_at_least(attack_range, "沙摩柯攻击范围", 1)
    points = ensure_int_at_least(damage, "杀伤害", 1)
    first = _boolean(first_qinglong_slash, "青龙首杀标识")
    followup = _boolean(likely_followup_slash, "后续杀可能标识")
    danger = any(
        _boolean(value, label)
        for value, label in (
            (lethal, "致命标识"),
            (wine_buffed, "酒杀标识"),
            (dangerous_elemental_chain, "危险属性链标识"),
            (high_hit_bonus, "高额命中收益标识"),
        )
    )
    card_cost = _nonnegative(response_card_cost, "闪机会成本")
    card_available = _boolean(response_card_available, "闪可用标识")
    jili_trigger = count + 1 == attack
    respond_risk = (attack if jili_trigger else 0.0) + (1.5 if first and followup else 0.0)
    damage_cost = float(points) + (5.0 if danger else 0.0)
    actions = build_optional_response_actions(
        effect_cost=damage_cost,
        response_card_cost=card_cost,
        response_followup_risk=respond_risk,
        no_response_followup_value=(1.5 if first and followup and not danger else 0.0),
        response_card_available=card_available,
    )
    return choose_v22_action(actions, source="分析约定：沙摩柯青龙与蒺藜响应策略")


# ---------------------------------------------------------------------------
# 曹纯


class CaochunVersion(Enum):
    OLD = "旧版"
    NEW = "新版"


@dataclass(frozen=True)
class CaochunCounterDecision:
    version: CaochunVersion
    activation_timing: str
    target_zone: str
    hand_pressure_bonus: float
    reason: str


def evaluate_caochun_counterplay(
    *,
    version: CaochunVersion | str,
    lost_equipment_count: int,
    can_target_hand: bool,
    key_equipment_value: float = 0.0,
    immediate_kill_value: float = 0.0,
) -> CaochunCounterDecision:
    parsed = _coerce_enum(version, CaochunVersion, "曹纯版本")
    lost = ensure_int_at_least(lost_equipment_count, "累计失去装备数", 0)
    hand_available = _boolean(can_target_hand, "可选择手牌标识")
    equipment_value = _nonnegative(key_equipment_value, "关键装备价值")
    kill_value = _nonnegative(immediate_kill_value, "即时击杀价值")
    timing = "出牌阶段开始时" if parsed is CaochunVersion.OLD else "出牌阶段内可选择时机"
    hand_bonus = 1.5 if lost <= 1 else 0.25
    equipment_score = equipment_value + kill_value - (1.0 if lost <= 1 else 0.0)
    if equipment_score > hand_bonus or not hand_available:
        zone = "装备区"
        reason = "关键装备或即时击杀价值覆盖了帮助曹纯累计失去装备的风险"
    else:
        zone = "手牌"
        reason = "低启动进度优先压缩摸3后的筛选空间，不无目的帮助装备成长"
    return CaochunCounterDecision(parsed, timing, zone, hand_bonus, reason)


# ---------------------------------------------------------------------------
# 张琪瑛


@dataclass(frozen=True)
class GouchenDecision:
    activate: bool
    gained_categories: tuple[str, ...]
    category_choice_available: bool
    activation_value: float
    hold_value: float
    reason: str

    @property
    def prospective_categories(self) -> tuple[str, str, str]:
        """发动时固定随机取得的三类；不把未发动误记为已经获得。"""

        return ("基本牌", "锦囊牌", "装备牌")


def evaluate_gouchen_activation(
    *,
    mark_available: bool,
    immediate_three_card_value: float,
    topdeck_control_value: float = 0.0,
    expected_mark_recovery_value: float = 0.0,
) -> GouchenDecision:
    available = _boolean(mark_available, "勾陈标记可用标识")
    activation = _finite(immediate_three_card_value, "三类随机牌即时价值") + _finite(
        expected_mark_recovery_value, "恢复勾陈期望价值"
    )
    hold = _finite(topdeck_control_value, "点化牌堆顶控制价值")
    activate = available and activation > hold
    if not available:
        reason = "当前没有可消耗的勾陈标记"
    elif activate:
        reason = "随机获得基本、锦囊、装备各一张的即时收益高于保留标记价值"
    else:
        reason = "保留标记对点化深度或关键牌堆顶控制更重要"
    return GouchenDecision(
        activate,
        ("基本牌", "锦囊牌", "装备牌") if activate else (),
        False,
        activation,
        hold,
        reason,
    )


# ---------------------------------------------------------------------------
# 清河公主


QINGHE_COMBO_SEQUENCE = ("虚拟杀", "虚拟酒", "闪诬", "实体杀")


@dataclass(frozen=True)
class QingheComboResult:
    sequence: tuple[str, str, str, str]
    first_slash_responded: bool
    wine_slash_responded: bool
    damage: int
    hp_loss_from_slander: int
    total_hp_loss: int
    slander_first_used_card_checked: bool
    reason: str


def evaluate_qinghe_combo(
    *,
    first_slash_responded: bool,
    wine_slash_responded: bool,
) -> QingheComboResult:
    first = _boolean(first_slash_responded, "虚拟杀出闪标识")
    second = _boolean(wine_slash_responded, "酒杀出闪标识")
    if first and second:
        raise ValueError("限定场景只有一张可用闪，不能同时响应两张杀")
    first_damage = 0 if first else 1
    wine_damage = 0 if second else 2
    slander_loss = 1 if second else 0
    total_damage = first_damage + wine_damage
    total = total_damage + slander_loss
    if first:
        reason = "第一张虚拟杀消耗唯一闪，后续酒杀造成2点伤害"
    elif second:
        reason = "第一张杀造成1点，后续闪属于使用牌并触发闪诬失去1点体力"
    else:
        reason = "两张杀均未响应，依次造成1点和2点伤害"
    return QingheComboResult(
        QINGHE_COMBO_SEQUENCE,
        first,
        second,
        total_damage,
        slander_loss,
        total,
        second,
        reason,
    )


@dataclass(frozen=True)
class QingheLastSlashDecision:
    hold_last_slash: bool
    hold_value: float
    spend_value: float
    reason: str


def evaluate_qinghe_last_slash_hold(
    *,
    qinghe_has_not_acted: bool,
    qinghe_acts_soon: bool,
    holder_is_likely_target: bool,
    current_slash_value: float,
    immediate_kill_value: float = 0.0,
    would_be_discarded: bool = False,
    multi_slash_or_chain_value: float = 0.0,
) -> QingheLastSlashDecision:
    not_acted = _boolean(qinghe_has_not_acted, "清河尚未发动谮构标识")
    soon = _boolean(qinghe_acts_soon, "清河即将行动标识")
    likely = _boolean(holder_is_likely_target, "可能成为目标标识")
    discard = _boolean(would_be_discarded, "弃牌阶段将弃置标识")
    spend = _finite(current_slash_value, "当前杀收益") + _nonnegative(
        immediate_kill_value, "即时击杀价值"
    ) + _nonnegative(multi_slash_or_chain_value, "多杀或属性链价值")
    hold = (2.5 if not_acted and soon and likely else 0.0) - (2.0 if discard else 0.0)
    choice = hold > spend
    reason = (
        "保留最后一张杀可阻止谮构生成虚拟杀"
        if choice
        else "当前击杀、连击或即将弃置的机会成本更高，不机械保留最后一张杀"
    )
    return QingheLastSlashDecision(choice, hold, spend, reason)


# ---------------------------------------------------------------------------
# 傅佥


class FuqianMode(Enum):
    DUEL = "单挑"
    TEAM = "团队"


@dataclass(frozen=True)
class PressureCard:
    card_id: str
    opportunity_cost: float
    expected_end_effect: float
    legal_at_end_phase: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "card_id", _nonempty(self.card_id, "施压牌标识"))
        object.__setattr__(self, "opportunity_cost", _nonnegative(self.opportunity_cost, "施压牌机会成本"))
        object.__setattr__(self, "expected_end_effect", _finite(self.expected_end_effect, "结束阶段预期牌效"))
        object.__setattr__(self, "legal_at_end_phase", _boolean(self.legal_at_end_phase, "结束阶段合法标识"))

    @property
    def pressure_value(self) -> float:
        return self.expected_end_effect - self.opportunity_cost


@dataclass(frozen=True)
class FuqianPressureDecision:
    plan: str
    committed_card_ids: tuple[str, ...]
    mode_multiplier: float
    reason: str


def evaluate_fuqian_pressure(
    *,
    current_hp: int,
    current_jue_count: int,
    cards: Sequence[PressureCard],
    passed_play_phase: bool,
    opponent_has_stable_engine: bool,
    opponent_can_accumulate_burst: bool,
    mode: FuqianMode | str,
    minimum_long_pressure_value: float = 0.5,
) -> FuqianPressureDecision:
    hp = ensure_int_at_least(current_hp, "傅佥当前体力", 1)
    jue = ensure_int_at_least(current_jue_count, "当前绝数量", 0)
    if jue > hp:
        raise ValueError("绝数量不能高于当前体力容量")
    if isinstance(cards, (str, bytes)) or not isinstance(cards, Sequence):
        raise TypeError("施压牌必须是序列")
    options = tuple(cards)
    if any(not isinstance(card, PressureCard) for card in options):
        raise TypeError("施压牌必须是 PressureCard")
    if len({card.card_id for card in options}) != len(options):
        raise ValueError("施压牌标识不能重复")
    passed = _boolean(passed_play_phase, "傅佥已过出牌阶段标识")
    stable = _boolean(opponent_has_stable_engine, "对手稳定运营标识")
    burst = _boolean(opponent_can_accumulate_burst, "对手可积累爆发标识")
    parsed_mode = _coerce_enum(mode, FuqianMode, "傅佥对局模式")
    multiplier = 1.0 if parsed_mode is FuqianMode.DUEL else 0.7
    pressure_threshold = _nonnegative(minimum_long_pressure_value, "长期施压最低价值")
    legal = tuple(
        sorted(
            (card for card in options if card.legal_at_end_phase and card.pressure_value > 0),
            key=lambda card: (-card.pressure_value, card.opportunity_cost, card.card_id),
        )
    )
    room = max(hp - jue, 0)
    if hp <= 1:
        plan = "转入总攻"
        commit_limit = min(room, len(legal))
    elif hp == 2:
        plan = "储备并寻找总攻窗口"
        commit_limit = min(1, room, len(legal))
    elif stable and not burst:
        plan = "长期逼破降"
        # 经过出牌阶段后可以增加低成本投入，但仍不无脑塞入所有高价值牌。
        low_cost = tuple(
            sorted(
                (
                    card
                    for card in legal
                    if card.opportunity_cost <= 1.0
                    and card.pressure_value * multiplier > pressure_threshold
                ),
                key=lambda card: (
                    -(card.pressure_value * multiplier),
                    card.opportunity_cost,
                    card.card_id,
                ),
            )
        )
        commit_limit = min(room, len(low_cost), 2 if passed else 1)
        legal = low_cost
    else:
        plan = "保留资源等待集中突破"
        commit_limit = 0
    committed = tuple(card.card_id for card in legal[:commit_limit])
    reason = (
        f"{parsed_mode.value}估值系数为{multiplier:.1f}；模式修正后的牌效须超过{pressure_threshold:.2f}，并只投入必要牌，避免一次破降清空多张高价值绝"
    )
    return FuqianPressureDecision(plan, committed, multiplier, reason)


@dataclass(frozen=True)
class PojiangDecision:
    activate: bool
    activation_value: float
    endure_value: float
    reason: str


def evaluate_pojiang_activation(
    *,
    current_hp: int,
    draw_and_transfer_value: float,
    expected_end_effect_cost: float,
    reliable_rescue: bool,
) -> PojiangDecision:
    hp = ensure_int_at_least(current_hp, "傅佥当前体力", 1)
    rescue = _boolean(reliable_rescue, "可靠救援标识")
    activation = _finite(draw_and_transfer_value, "摸3交牌清绝收益") - 1.0
    if hp == 1 and not rescue:
        activation -= 6.0
    endure = -_nonnegative(expected_end_effect_cost, "承受结束阶段牌效成本")
    use = activation > endure
    reason = "比较摸3、交牌、清绝收益与失去1体力及结束阶段牌效，不见一张绝就自动破降"
    return PojiangDecision(use, activation, endure, reason)


# ---------------------------------------------------------------------------
# 吴文鸯


class QuediBranch(Enum):
    NONE = "不发动"
    TAKE_HAND = "只取得目标手牌"
    DAMAGE_PLUS = "只弃基本牌使伤害+1"
    BACKSWATER = "背水"


@dataclass(frozen=True)
class WuyangQuediDecision:
    chosen_branch: QuediBranch
    branch_scores: Mapping[QuediBranch, float]
    branch_legal: Mapping[QuediBranch, bool]
    hp_after_max_hp_loss: int
    actual_hp_loss: int
    reason: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "branch_scores", MappingProxyType(dict(self.branch_scores)))
        object.__setattr__(self, "branch_legal", MappingProxyType(dict(self.branch_legal)))


def evaluate_wuyang_quedi(
    *,
    current_hp: int,
    current_max_hp: int,
    take_hand_value: float,
    damage_plus_value: float,
    basic_card_cost: float,
    future_max_hp_cost: float,
    both_effects_indispensable: bool,
    key_kill_value: float = 0.0,
    prevent_team_loss_value: float = 0.0,
    target_has_hand: bool = True,
    basic_material_available_before: bool = True,
    taken_card_is_basic: bool = False,
) -> WuyangQuediDecision:
    hp = ensure_int_at_least(current_hp, "吴文鸯当前体力", 1)
    max_hp = ensure_int_at_least(current_max_hp, "吴文鸯当前体力上限", 1)
    if hp > max_hp:
        raise ValueError("当前体力不能高于当前体力上限")
    take = _finite(take_hand_value, "取得手牌价值")
    damage = _finite(damage_plus_value, "增伤价值")
    material = _nonnegative(basic_card_cost, "基本牌材料成本")
    future = _nonnegative(future_max_hp_cost, "未来体力上限成本")
    indispensable = _boolean(both_effects_indispensable, "两项均不可替代标识")
    kill = _nonnegative(key_kill_value, "关键击杀价值")
    save = _nonnegative(prevent_team_loss_value, "阻止己方失败价值")
    has_hand = _boolean(target_has_hand, "目标有手牌标识")
    material_before = _boolean(basic_material_available_before, "夺牌前基本牌材料可用标识")
    taken_basic = _boolean(taken_card_is_basic, "新取得牌为基本牌标识")
    if taken_basic and not has_hand:
        raise ValueError("目标没有手牌时，不可能取得基本牌")
    hp_after = min(hp, max_hp - 1)
    actual_hp_loss = hp - hp_after
    actual_loss_cost = 2.5 * actual_hp_loss
    legal = {
        QuediBranch.NONE: True,
        QuediBranch.TAKE_HAND: has_hand,
        QuediBranch.DAMAGE_PLUS: material_before,
        # 背水先取得手牌，故新取得的基本牌可以成为随后增伤的材料。
        QuediBranch.BACKSWATER: has_hand and (material_before or taken_basic),
    }
    raw_scores = {
        QuediBranch.NONE: 0.0,
        QuediBranch.TAKE_HAND: take,
        QuediBranch.DAMAGE_PLUS: damage + kill + save - material,
        QuediBranch.BACKSWATER: (
            take
            + damage
            + kill
            + save
            - material
            - future
            - actual_loss_cost
            + (2.0 if indispensable else -2.0)
        ),
    }
    scores = {
        branch: (score if legal[branch] else float("-inf"))
        for branch, score in raw_scores.items()
    }
    chosen = max(scores, key=scores.__getitem__)
    reason = (
        "完整比较不发动、夺牌、增伤和背水；满体力减少上限会同时损失当前体力，普通收益不足以支持背水"
        if actual_hp_loss
        else "减少上限未降低当前体力，但仍比较回复空间、材料与未来击杀风险，不因低体力自动禁止背水"
    )
    return WuyangQuediDecision(chosen, scores, legal, hp_after, actual_hp_loss, reason)


@dataclass(frozen=True)
class WuyangSlashTarget:
    target_id: str
    target_has_equipment: bool
    material_equipment_cost: float
    expected_damage_value: float
    kill_value: float = 0.0
    on_damage_benefit: float = 0.0
    flash_probability_cost: float = 0.0
    focus_value: float = 0.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "target_id", _nonempty(self.target_id, "吴文鸯转杀目标"))
        object.__setattr__(self, "target_has_equipment", _boolean(self.target_has_equipment, "目标有装备标识"))
        for field_name in (
            "material_equipment_cost",
            "expected_damage_value",
            "kill_value",
            "on_damage_benefit",
            "flash_probability_cost",
            "focus_value",
        ):
            object.__setattr__(self, field_name, _finite(getattr(self, field_name), field_name))

    @property
    def score(self) -> float:
        equipment_bonus = 1.0 if self.target_has_equipment else 0.0
        return (
            self.expected_damage_value
            + self.kill_value
            + self.focus_value
            + equipment_bonus
            - self.material_equipment_cost
            - self.on_damage_benefit
            - self.flash_probability_cost
        )


def choose_wuyang_equipment_slash_target(
    targets: Sequence[WuyangSlashTarget],
) -> WuyangSlashTarget:
    """装备目标有加分但不保证优先；仍比较材料、卖血、闪和击杀。"""

    if isinstance(targets, (str, bytes)) or not isinstance(targets, Sequence):
        raise TypeError("吴文鸯转杀目标必须是序列")
    options = tuple(targets)
    if not options:
        raise ValueError("至少需要一个合法转杀目标")
    if any(not isinstance(target, WuyangSlashTarget) for target in options):
        raise TypeError("吴文鸯转杀目标必须是 WuyangSlashTarget")
    if len({target.target_id for target in options}) != len(options):
        raise ValueError("吴文鸯转杀目标标识不能重复")
    return max(options, key=lambda target: target.score)


def chongjian_equipment_gain_count(
    *,
    target_killed: bool,
    target_equipment_count: int,
    damage_dealt: int,
) -> int:
    """目标直接死亡时，其装备已随死亡离开，冲坚不能再取得。"""

    killed = _boolean(target_killed, "目标死亡标识")
    equipment = ensure_int_at_least(target_equipment_count, "目标装备数", 0)
    damage = ensure_int_at_least(damage_dealt, "造成伤害", 0)
    if killed:
        return 0
    return min(equipment, damage)


__all__ = [
    "STRATEGY_VERSION",
    "CaochunCounterDecision",
    "CaochunVersion",
    "CounterplayProfile",
    "DecisionAudit",
    "DynamicCardValue",
    "DynamicTauntInput",
    "FuqianMode",
    "FuqianPressureDecision",
    "GeneralPolicy",
    "GouchenDecision",
    "PojiangDecision",
    "PressureCard",
    "QINGHE_COMBO_SEQUENCE",
    "QingheComboResult",
    "QingheLastSlashDecision",
    "QuediBranch",
    "ShamokeDisruptionDecision",
    "ShamokeProbeDecision",
    "ShamokeWeaponDecision",
    "StrategyAction",
    "WuyangQuediDecision",
    "WuyangSlashTarget",
    "V22AuditMetrics",
    "build_optional_response_actions",
    "choose_shamoke_slash_response",
    "choose_v22_action",
    "choose_wuyang_equipment_slash_target",
    "chongjian_equipment_gain_count",
    "evaluate_caochun_counterplay",
    "evaluate_fuqian_pressure",
    "evaluate_gouchen_activation",
    "evaluate_pojiang_activation",
    "evaluate_qinghe_combo",
    "evaluate_qinghe_last_slash_hold",
    "evaluate_shamoke_weapon_disruption",
    "evaluate_shamoke_weapon_swap",
    "evaluate_attack_into_shamoke",
    "evaluate_wuyang_quedi",
]
