"""三国杀单牌与多人牌的轻量理性决策策略。

本模块只处理调用方已经判定为合法的候选行动，不定义卡牌效果，也不实现完整
游戏引擎。所有评分均为透明、可调整的计算参数；候选中的已知信息必须来自
当前角色依法可见的信息，不能用隐藏手牌或隐藏身份冒充实战信息。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Iterable, Mapping

from ._validation import ensure_finite_real


ParameterValue = float | int | bool | str


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name}必须是非空字符串")
    return value.strip()


def _bool(value: object, name: str) -> bool:
    if not isinstance(value, bool):
        raise TypeError(f"{name}必须是布尔值")
    return value


def _number(value: object, name: str) -> float:
    return ensure_finite_real(value, name)


def _nonnegative(value: object, name: str) -> float:
    number = _number(value, name)
    if number < 0:
        raise ValueError(f"{name}必须是非负有限数值")
    return number


def _probability(value: object, name: str) -> float:
    number = _nonnegative(value, name)
    if number > 1:
        raise ValueError(f"{name}必须在0到1之间")
    return number


def _parameters(values: Mapping[str, ParameterValue]) -> Mapping[str, ParameterValue]:
    """复制参数并返回只读映射，避免调用方事后修改日志。"""

    return MappingProxyType(dict(values))


@dataclass(frozen=True)
class StrategyDecision:
    """一个稳定、可解释的策略决定。"""

    decision: str
    should_act: bool
    score: float
    reason: str
    target_id: str | None = None
    parameters: Mapping[str, ParameterValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "decision", _text(self.decision, "决策名称"))
        object.__setattr__(self, "should_act", _bool(self.should_act, "是否行动"))
        object.__setattr__(self, "score", _number(self.score, "策略分数"))
        object.__setattr__(self, "reason", _text(self.reason, "决策理由"))
        if self.target_id is not None:
            object.__setattr__(self, "target_id", _text(self.target_id, "目标标识"))
        if not isinstance(self.parameters, Mapping):
            raise TypeError("策略参数必须是映射")
        object.__setattr__(self, "parameters", _parameters(self.parameters))


@dataclass(frozen=True)
class HarvestStrategyWeights:
    focus_distance: float = 6.0
    required_slash: float = 5.0
    team_rescue_peach: float = 5.0
    deny_enemy_peach: float = 4.0
    safe_ally_peach_deferral: float = 2.5
    unsafe_pick_order: float = 2.0

    def __post_init__(self) -> None:
        for name, value in vars(self).items():
            object.__setattr__(self, name, _nonnegative(value, name))


@dataclass(frozen=True)
class HarvestCardOption:
    option_id: str
    card_name: str
    base_marginal_value: float = 0.0
    enables_focus_distance: bool = False
    is_slash: bool = False
    is_peach: bool = False
    information_legal: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "option_id", _text(self.option_id, "五谷候选标识"))
        object.__setattr__(self, "card_name", _text(self.card_name, "五谷候选牌名"))
        object.__setattr__(
            self,
            "base_marginal_value",
            _number(self.base_marginal_value, "五谷候选基础边际价值"),
        )
        for name in ("enables_focus_distance", "is_slash", "is_peach", "information_legal"):
            object.__setattr__(self, name, _bool(getattr(self, name), name))


def select_harvest_card(
    options: Iterable[HarvestCardOption],
    *,
    needs_distance_to_focus: bool = False,
    slash_dependent_skill: bool = False,
    has_slash: bool = True,
    team_needs_rescue: bool = False,
    deny_enemy_rescue: bool = False,
    reliable_ally_can_take_peach: bool = False,
    weights: HarvestStrategyWeights | None = None,
) -> StrategyDecision:
    """按当前边际收益选择【五谷丰登】中的一张公开牌。"""

    try:
        prepared = tuple(options)
    except TypeError as exc:
        raise TypeError("五谷候选牌必须是可迭代对象") from exc
    if not prepared:
        raise ValueError("五谷候选牌不能为空")
    if any(not isinstance(option, HarvestCardOption) for option in prepared):
        raise TypeError("每个五谷候选都必须是 HarvestCardOption")
    for value, name in (
        (needs_distance_to_focus, "是否需要距离牌"),
        (slash_dependent_skill, "技能是否依赖杀"),
        (has_slash, "当前是否有杀"),
        (team_needs_rescue, "队伍是否需要救援"),
        (deny_enemy_rescue, "是否需要阻止敌方取得桃"),
        (reliable_ally_can_take_peach, "可靠队友是否能安全取得桃"),
    ):
        _bool(value, name)
    policy = weights or HarvestStrategyWeights()

    ranked: list[tuple[float, int, HarvestCardOption, tuple[str, ...]]] = []
    for index, option in enumerate(prepared):
        if not option.information_legal:
            continue
        score = option.base_marginal_value
        reasons: list[str] = ["计入当前局面的基础边际价值"]
        if needs_distance_to_focus and option.enables_focus_distance:
            score += policy.focus_distance
            reasons.append("该牌能使当前角色攻击主要集火目标")
        if slash_dependent_skill and not has_slash and option.is_slash:
            score += policy.required_slash
            reasons.append("当前技能依赖【杀】且手中没有【杀】")
        if option.is_peach and team_needs_rescue:
            score += policy.team_rescue_peach
            reasons.append("己方当前存在明确救援需求")
        if option.is_peach and deny_enemy_rescue:
            score += policy.deny_enemy_peach
            reasons.append("取得【桃】可阻止敌方获得关键救援资源")
        if (
            option.is_peach
            and reliable_ally_can_take_peach
            and not team_needs_rescue
            and not deny_enemy_rescue
        ):
            score -= policy.safe_ally_peach_deferral
            reasons.append("后续可靠队友能安全取得【桃】，当前可让出")
        ranked.append((score, -index, option, tuple(reasons)))
    if not ranked:
        raise ValueError("没有只依赖合法可见信息的五谷候选牌")

    score, _, option, reasons = max(ranked, key=lambda item: (item[0], item[1]))
    return StrategyDecision(
        decision=f"选择{option.card_name}",
        should_act=True,
        score=score,
        target_id=option.option_id,
        reason=f"选择【{option.card_name}】：" + "；".join(reasons),
        parameters={
            "focus_distance_weight": policy.focus_distance,
            "required_slash_weight": policy.required_slash,
            "team_rescue_peach_weight": policy.team_rescue_peach,
            "deny_enemy_peach_weight": policy.deny_enemy_peach,
            "safe_ally_peach_deferral": policy.safe_ally_peach_deferral,
        },
    )


def evaluate_harvest_use(
    *,
    friendly_expected_gain: float,
    enemy_expected_gain: float,
    two_enemies_before_next_ally: bool,
    friendly_nullification_available: bool,
    critical_flip_value: float = 0.0,
    weights: HarvestStrategyWeights | None = None,
) -> StrategyDecision:
    """比较使用【五谷丰登】的团队净收益与当前取牌顺序风险。"""

    friendly = _nonnegative(friendly_expected_gain, "己方预期取牌收益")
    enemy = _nonnegative(enemy_expected_gain, "敌方预期取牌收益")
    critical = _nonnegative(critical_flip_value, "关键翻盘或击杀收益")
    _bool(two_enemies_before_next_ally, "己方下次取牌前是否有两名敌人")
    _bool(friendly_nullification_available, "己方是否有可用无懈可击")
    policy = weights or HarvestStrategyWeights()
    unsafe = two_enemies_before_next_ally and not friendly_nullification_available
    penalty = policy.unsafe_pick_order if unsafe else 0.0
    score = friendly + critical - enemy - penalty
    reasons = [f"团队净收益为 {score:.2f}"]
    if unsafe:
        reasons.append("己方下次取牌前有两名敌人连续取牌且己方没有可用无懈")
    if critical:
        reasons.append("计入关键翻盘、击杀牌或阻断救援的覆盖收益")
    should_use = score > 0
    reasons.append("净收益为正，建议使用" if should_use else "净收益不为正，通常保留")
    return StrategyDecision(
        decision="使用五谷丰登" if should_use else "不使用五谷丰登",
        should_act=should_use,
        score=score,
        reason="；".join(reasons),
        parameters={
            "friendly_expected_gain": friendly,
            "enemy_expected_gain": enemy,
            "critical_flip_value": critical,
            "unsafe_pick_order_penalty": penalty,
        },
    )


class Relationship(Enum):
    ALLY = "己方"
    ENEMY = "敌方"
    UNKNOWN = "未知"


def _relationship(value: Relationship | str, name: str) -> Relationship:
    if isinstance(value, Relationship):
        return value
    try:
        return Relationship(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name}只能为己方、敌方或未知") from exc


def evaluate_borrowed_sword_response(
    *,
    user_relationship: Relationship | str,
    target_relationship: Relationship | str,
    has_slash: bool,
    target_is_legal: bool,
    teammate_needs_weapon: bool = False,
    weapon_retention_value: float = 0.0,
    slash_effect_value: float = 0.0,
    teammate_damage_cost: float = 0.0,
    crossbow_combo_value: float = 0.0,
    retaliation_or_death_risk: float = 0.0,
) -> StrategyDecision:
    """比较被【借刀杀人】要求出【杀】与交出武器的净收益。"""

    user = _relationship(user_relationship, "借刀使用者关系")
    target = _relationship(target_relationship, "指定杀目标关系")
    for value, name in (
        (has_slash, "是否有合法杀"),
        (target_is_legal, "指定目标是否合法"),
        (teammate_needs_weapon, "队友是否明确需要武器"),
    ):
        _bool(value, name)
    retention = _nonnegative(weapon_retention_value, "保留武器价值")
    attack = _number(slash_effect_value, "出杀效果价值")
    ally_cost = _nonnegative(teammate_damage_cost, "伤害队友成本")
    crossbow = _nonnegative(crossbow_combo_value, "连弩组合价值")
    risk = _nonnegative(retaliation_or_death_risk, "反制、死亡或身份惩罚风险")

    if not has_slash or not target_is_legal:
        return StrategyDecision(
            "不出杀并交出武器",
            False,
            -(retention + crossbow),
            "没有可用【杀】或指定目标不合法，不能按要求出【杀】",
            parameters={"weapon_retention_value": retention, "crossbow_combo_value": crossbow},
        )
    if user is Relationship.ALLY and teammate_needs_weapon:
        return StrategyDecision(
            "不出杀并让武器转移给队友",
            False,
            0.0,
            "队友明确需要当前武器，通常配合交出武器",
            parameters={"teammate_needs_weapon": True, "weapon_retention_value": retention},
        )

    score = retention + crossbow + attack - risk
    reasons = ["比较保留武器、出杀效果与风险"]
    if target is Relationship.ENEMY:
        reasons.append("指定目标为敌方，出杀同时保留武器")
    elif target is Relationship.ALLY:
        score -= ally_cost
        reasons.append("指定目标为队友，扣除队友受伤与团队风险")
    else:
        reasons.append("指定目标阵营未知，未把隐藏身份当作己方或敌方")
    if crossbow:
        reasons.append("计入诸葛连弩等高收益武器组合价值")
    should_slash = score > 0
    reasons.append("出杀净收益为正" if should_slash else "出杀净收益不为正")
    return StrategyDecision(
        "出杀并保留武器" if should_slash else "不出杀并交出武器",
        should_slash,
        score,
        "；".join(reasons),
        parameters={
            "weapon_retention_value": retention,
            "slash_effect_value": attack,
            "teammate_damage_cost": ally_cost,
            "crossbow_combo_value": crossbow,
            "retaliation_or_death_risk": risk,
        },
    )


def evaluate_defense_card_spend(
    *,
    tactical_gain: float,
    defense_value: float,
    immediate_kill_value: float = 0.0,
    prevent_team_death_value: float = 0.0,
    number_advantage_value: float = 0.0,
    other_resource_cost: float = 0.0,
) -> StrategyDecision:
    """决定是否把【闪】【桃】等关键防御牌作为火攻、技能或转化成本。"""

    tactical = _nonnegative(tactical_gain, "战术收益")
    defense = _nonnegative(defense_value, "防御保留价值")
    kill = _nonnegative(immediate_kill_value, "即时击杀价值")
    survival = _nonnegative(prevent_team_death_value, "阻止己方死亡价值")
    advantage = _nonnegative(number_advantage_value, "人数优势价值")
    other = _nonnegative(other_resource_cost, "其他资源成本")
    score = tactical + kill + survival + advantage - defense - other
    spend = score > 0
    return StrategyDecision(
        "消耗防御牌" if spend else "保留防御牌",
        spend,
        score,
        (
            "即时击杀、阻止己方死亡或人数优势使总收益高于防御保留价值"
            if spend
            else "当前收益不足以补偿关键防御牌及其他资源成本"
        ),
        parameters={
            "tactical_gain": tactical,
            "defense_value": defense,
            "immediate_kill_value": kill,
            "prevent_team_death_value": survival,
            "number_advantage_value": advantage,
            "other_resource_cost": other,
        },
    )


@dataclass(frozen=True)
class DisruptionTarget:
    target_id: str
    card_id: str
    base_expected_value: float = 0.0
    dangerous_delayed_on_ally: bool = False
    focus_target_plus_one_horse: bool = False
    focus_target_armor: bool = False
    known_peach: bool = False
    known_nullification: bool = False
    enemy_crossbow_burst: bool = False
    high_value_weapon_or_attack_horse: bool = False
    armor_effective_against_plan: bool = True
    information_legal: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "target_id", _text(self.target_id, "拆顺目标角色"))
        object.__setattr__(self, "card_id", _text(self.card_id, "拆顺目标牌"))
        object.__setattr__(
            self,
            "base_expected_value",
            _number(self.base_expected_value, "拆顺基础预期价值"),
        )
        for name in (
            "dangerous_delayed_on_ally",
            "focus_target_plus_one_horse",
            "focus_target_armor",
            "known_peach",
            "known_nullification",
            "enemy_crossbow_burst",
            "high_value_weapon_or_attack_horse",
            "armor_effective_against_plan",
            "information_legal",
        ):
            object.__setattr__(self, name, _bool(getattr(self, name), name))


@dataclass(frozen=True)
class DisruptionWeights:
    ally_dangerous_delayed: float = 9.0
    focus_plus_one_horse: float = 6.0
    focus_armor: float = 5.5
    known_rescue_or_nullification: float = 5.0
    enemy_crossbow_burst: float = 8.0
    other_high_value_equipment: float = 3.0
    ineffective_armor_discount: float = 4.0

    def __post_init__(self) -> None:
        for name, value in vars(self).items():
            object.__setattr__(self, name, _nonnegative(value, name))


def select_disruption_target(
    candidates: Iterable[DisruptionTarget],
    *,
    weights: DisruptionWeights | None = None,
) -> StrategyDecision:
    """为【顺手牵羊】或【过河拆桥】选择公开信息下的最高价值目标牌。"""

    try:
        prepared = tuple(candidates)
    except TypeError as exc:
        raise TypeError("拆顺候选必须是可迭代对象") from exc
    if not prepared:
        raise ValueError("拆顺候选不能为空")
    if any(not isinstance(item, DisruptionTarget) for item in prepared):
        raise TypeError("每个拆顺候选都必须是 DisruptionTarget")
    policy = weights or DisruptionWeights()
    scored: list[tuple[float, int, DisruptionTarget, list[str]]] = []
    for index, item in enumerate(prepared):
        if not item.information_legal:
            continue
        score = item.base_expected_value
        reasons = ["计入公开信息下的基础预期价值"]
        if item.dangerous_delayed_on_ally:
            score += policy.ally_dangerous_delayed
            reasons.append("优先解除己方判定区的危险延时锦囊")
        if item.focus_target_plus_one_horse:
            score += policy.focus_plus_one_horse
            reasons.append("移除主要集火目标的+1坐骑以改善可达性")
        if item.focus_target_armor:
            bonus = policy.focus_armor
            if not item.armor_effective_against_plan:
                bonus -= policy.ineffective_armor_discount
                reasons.append("该防具对当前攻击方案效果较低，已下调优先级")
            else:
                reasons.append("移除主要集火目标的有效防具")
            score += bonus
        if item.known_peach or item.known_nullification:
            score += policy.known_rescue_or_nullification
            reasons.append("该已知手牌是关键救援或无懈资源")
        if item.enemy_crossbow_burst:
            score += policy.enemy_crossbow_burst
            reasons.append("敌方诸葛连弩已形成高爆发威胁")
        elif item.high_value_weapon_or_attack_horse:
            score += policy.other_high_value_equipment
            reasons.append("移除敌方高价值武器或-1坐骑")
        scored.append((score, -index, item, reasons))
    if not scored:
        raise ValueError("没有只依赖合法可见信息的拆顺候选")
    score, _, chosen, reasons = max(scored, key=lambda row: (row[0], row[1]))
    return StrategyDecision(
        "选择拆顺目标",
        True,
        score,
        f"选择角色{chosen.target_id}的{chosen.card_id}：" + "；".join(reasons),
        target_id=f"{chosen.target_id}:{chosen.card_id}",
        parameters={
            "ally_dangerous_delayed_weight": policy.ally_dangerous_delayed,
            "focus_plus_one_horse_weight": policy.focus_plus_one_horse,
            "focus_armor_weight": policy.focus_armor,
            "known_rescue_or_nullification_weight": policy.known_rescue_or_nullification,
            "enemy_crossbow_burst_weight": policy.enemy_crossbow_burst,
        },
    )


@dataclass(frozen=True)
class DelayedTrickAssessment:
    target_id: str
    score: float
    reason: str
    parameters: Mapping[str, ParameterValue]

    def __post_init__(self) -> None:
        object.__setattr__(self, "target_id", _text(self.target_id, "延时锦囊目标"))
        object.__setattr__(self, "score", _number(self.score, "延时锦囊目标分数"))
        object.__setattr__(self, "reason", _text(self.reason, "延时锦囊评分理由"))
        if not isinstance(self.parameters, Mapping):
            raise TypeError("延时锦囊参数必须是映射")
        object.__setattr__(self, "parameters", _parameters(self.parameters))


def score_indulgence_target(
    target_id: str,
    *,
    base_threat: float,
    hand_count: int,
    hand_limit: int,
    expected_play_phase_loss: float,
    next_to_act: bool,
    removal_probability_before_judgment: float = 0.0,
    next_action_bonus: float = 1.0,
) -> DelayedTrickAssessment:
    """评价【乐不思蜀】目标，显式计入溢出弃牌与判定前移除风险。"""

    target = _text(target_id, "乐不思蜀目标")
    if isinstance(hand_count, bool) or not isinstance(hand_count, int) or hand_count < 0:
        raise ValueError("手牌数必须是非负整数")
    if isinstance(hand_limit, bool) or not isinstance(hand_limit, int) or hand_limit < 0:
        raise ValueError("手牌上限必须是非负整数")
    threat = _nonnegative(base_threat, "基础威胁")
    play_loss = _nonnegative(expected_play_phase_loss, "预计跳过出牌阶段损失")
    _bool(next_to_act, "是否第一个即将行动的敌人")
    removal = _probability(removal_probability_before_judgment, "判定前移除概率")
    action_bonus = _nonnegative(next_action_bonus, "即将行动修正")
    overflow = max(0, hand_count - hand_limit)
    raw = threat + play_loss + overflow * 0.5 + (action_bonus if next_to_act else 0.0)
    score = raw * (1 - removal)
    return DelayedTrickAssessment(
        target,
        score,
        (
            f"基础威胁、出牌阶段损失与预计溢出{overflow}张手牌合计后，"
            f"按判定前被移除概率{removal:.0%}折算"
            + ("；该目标最先行动，计入时序修正" if next_to_act else "")
        ),
        {
            "base_threat": threat,
            "expected_play_phase_loss": play_loss,
            "hand_overflow": overflow,
            "next_action_bonus": action_bonus if next_to_act else 0.0,
            "removal_probability": removal,
        },
    )


def score_supply_shortage_target(
    target_id: str,
    *,
    base_threat: float,
    hand_count: int,
    draw_phase_dependency: float,
    extra_draw_resilience: float = 0.0,
    next_to_act: bool,
    removal_probability_before_judgment: float = 0.0,
    low_hand_bonus_per_card: float = 0.2,
    next_action_bonus: float = 0.65,
) -> DelayedTrickAssessment:
    """评价【兵粮寸断】目标，区分低手牌、摸牌依赖和额外摸牌韧性。"""

    target = _text(target_id, "兵粮寸断目标")
    if isinstance(hand_count, bool) or not isinstance(hand_count, int) or hand_count < 0:
        raise ValueError("手牌数必须是非负整数")
    threat = _nonnegative(base_threat, "基础威胁")
    dependency = _nonnegative(draw_phase_dependency, "摸牌阶段依赖")
    resilience = _nonnegative(extra_draw_resilience, "额外摸牌韧性")
    _bool(next_to_act, "是否第一个即将行动的敌人")
    removal = _probability(removal_probability_before_judgment, "判定前移除概率")
    low_hand_weight = _nonnegative(low_hand_bonus_per_card, "低手牌每张修正")
    action_bonus = _nonnegative(next_action_bonus, "即将行动修正")
    low_hand = max(0, 4 - hand_count)
    raw = (
        threat
        + dependency
        + low_hand * low_hand_weight
        + (action_bonus if next_to_act else 0.0)
        - resilience
    )
    score = raw * (1 - removal)
    return DelayedTrickAssessment(
        target,
        score,
        (
            f"计入低于4张的手牌缺口{low_hand}、摸牌阶段依赖和额外摸牌韧性，"
            f"再按判定前被移除概率{removal:.0%}折算"
            + ("；该目标最先行动，计入时序修正" if next_to_act else "")
        ),
        {
            "base_threat": threat,
            "low_hand_cards": low_hand,
            "low_hand_bonus_per_card": low_hand_weight,
            "draw_phase_dependency": dependency,
            "extra_draw_resilience": resilience,
            "next_action_bonus": action_bonus if next_to_act else 0.0,
            "removal_probability": removal,
        },
    )


class GroupCardKind(Enum):
    PEACH_GARDEN = "桃园结义"
    BARBARIAN_INVASION = "南蛮入侵"
    ARCHERY_ATTACK = "万箭齐发"


def _group_card(value: GroupCardKind | str) -> GroupCardKind:
    if isinstance(value, GroupCardKind):
        return value
    try:
        return GroupCardKind(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("多人牌只能为桃园结义、南蛮入侵或万箭齐发") from exc


def evaluate_group_card_use(
    card: GroupCardKind | str,
    *,
    enemy_expected_loss: float = 0.0,
    enemy_kill_value: float = 0.0,
    friendly_damage_benefit: float = 0.0,
    friendly_heal_value: float = 0.0,
    friendly_expected_loss: float = 0.0,
    ally_dying_risk_cost: float = 0.0,
    enemy_on_damage_benefit: float = 0.0,
    rescue_resource_cost: float = 0.0,
    enemy_heal_value: float = 0.0,
    focus_kill_line_loss: float = 0.0,
    game_over: bool = False,
) -> StrategyDecision:
    """按团队净收益决定是否使用【桃园结义】、【南蛮】或【万箭】。"""

    kind = _group_card(card)
    values = {
        "enemy_expected_loss": _nonnegative(enemy_expected_loss, "敌方预期损失"),
        "enemy_kill_value": _nonnegative(enemy_kill_value, "敌方击杀价值"),
        "friendly_damage_benefit": _nonnegative(friendly_damage_benefit, "己方受伤收益"),
        "friendly_heal_value": _nonnegative(friendly_heal_value, "己方回复价值"),
        "friendly_expected_loss": _nonnegative(friendly_expected_loss, "己方预期损失"),
        "ally_dying_risk_cost": _nonnegative(ally_dying_risk_cost, "队友濒死风险成本"),
        "enemy_on_damage_benefit": _nonnegative(enemy_on_damage_benefit, "敌方卖血收益"),
        "rescue_resource_cost": _nonnegative(rescue_resource_cost, "救援资源成本"),
        "enemy_heal_value": _nonnegative(enemy_heal_value, "敌方回复价值"),
        "focus_kill_line_loss": _nonnegative(focus_kill_line_loss, "破坏集火击杀线成本"),
    }
    _bool(game_over, "游戏是否结束")
    positives = (
        values["enemy_expected_loss"]
        + values["enemy_kill_value"]
        + values["friendly_damage_benefit"]
        + values["friendly_heal_value"]
    )
    costs = (
        values["friendly_expected_loss"]
        + values["ally_dying_risk_cost"]
        + values["enemy_on_damage_benefit"]
        + values["rescue_resource_cost"]
        + values["enemy_heal_value"]
        + values["focus_kill_line_loss"]
    )
    score = positives - costs
    should_use = score > 0 and not game_over
    reasons = [f"{kind.value}的团队净收益为 {score:.2f}"]
    if values["focus_kill_line_loss"]:
        reasons.append("该牌会破坏当前主要目标的击杀线")
    if values["ally_dying_risk_cost"]:
        reasons.append("计入队友进入不可接受危险血线的成本")
    if values["enemy_on_damage_benefit"]:
        reasons.append("计入敌方卖血收益")
    if values["enemy_kill_value"]:
        reasons.append("计入可完成击杀的价值")
    if game_over:
        reasons.append("游戏已经结束，不再开始新的多人牌结算")
    else:
        reasons.append("净收益为正，建议使用" if should_use else "净收益不为正，通常保留")
    return StrategyDecision(
        f"使用{kind.value}" if should_use else f"不使用{kind.value}",
        should_use,
        score,
        "；".join(reasons),
        parameters=values,
    )

