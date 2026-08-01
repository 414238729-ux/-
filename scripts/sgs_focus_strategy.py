"""三国杀集火、目标锁定与单牌行动规划的轻量理性策略。

本模块不实现完整游戏引擎，也不把策略写成卡牌或模式强制规则。调用方
负责根据合法可见信息构造候选目标；本模块只做确定性评分、锁定、切换和
可解释行动分配。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Iterable, Mapping, Sequence

from ._validation import ensure_finite_real, ensure_int_at_least


class FocusRecalculationEvent(Enum):
    INITIAL = "初始选择"
    HP_CHANGE = "体力变化"
    HAND_OR_EQUIPMENT_CHANGE = "手牌或装备明显变化"
    SKILL_OR_MARK_CHANGE = "技能或标记变化"
    TURN_ADVANCE = "回合顺序推进"
    DYING_OR_DEATH = "进入濒死或死亡"
    DISTANCE_CHANGE = "攻击距离变化"
    TEAM_FOCUS_CHANGE = "队友集火能力变化"
    RESCUE_RESOURCE_CHANGE = "救援资源变化"
    VICTORY_OR_IDENTITY_CHANGE = "胜利条件或身份信息变化"


class FocusSwitchReason(Enum):
    INITIAL_SELECTION = "建立主要集火目标"
    KEEP_FOCUS = "保持主要集火目标"
    TARGET_DEAD = "原目标已死亡或离场"
    TARGET_UNREACHABLE = "原目标当前不可合法触及"
    TARGET_DEFENSE_SPIKE = "原目标短期防御显著提高"
    OTHER_IMMEDIATE_KILL = "另一目标进入高概率即时击杀状态"
    OTHER_LETHAL_THREAT = "另一目标形成致命即时威胁"
    NEGATIVE_ON_DAMAGE_TRADE = "继续攻击的卖血或反制净收益为负"
    TEAM_FOCUS_LOST = "队友无法继续配合集火"
    VICTORY_OR_IDENTITY_CHANGED = "胜利条件或身份信息已经变化"
    TARGET_NO_LONGER_KILLABLE = "原目标已无合理近期击杀前景"
    NO_EXECUTABLE_TARGET = "当前没有正收益且可执行的集火目标"


class FocusActionKind(Enum):
    SINGLE_TARGET_DAMAGE = "单体伤害"
    DUEL = "决斗"
    DISRUPT_DEFENSE_OR_RESCUE = "拆除防御或救援"
    CONTROL = "控制"
    CHAIN_OR_FIRE_COMBO = "铁索或火攻组合"
    PRESERVE_TEAM_RESOURCE = "保留己方集火能力"
    HOLD = "保留资源"


def _ensure_bool(value: object, name: str) -> bool:
    if not isinstance(value, bool):
        raise TypeError(f"{name}必须是布尔值")
    return value


def _finite_nonnegative(value: object, name: str) -> float:
    number = ensure_finite_real(value, name)
    if number < 0:
        raise ValueError(f"{name}必须是非负有限数值")
    return number


def _probability(value: object, name: str) -> float:
    number = _finite_nonnegative(value, name)
    if number > 1:
        raise ValueError(f"{name}必须在0到1之间")
    return number


def _coerce_enum(value: object, enum_type: type[Enum], name: str) -> Enum:
    if isinstance(value, enum_type):
        return value
    try:
        return enum_type(value)
    except (TypeError, ValueError) as exc:
        allowed = "、".join(str(member.value) for member in enum_type)
        raise ValueError(f"{name}只能为：{allowed}") from exc


@dataclass(frozen=True)
class FocusScoringWeights:
    static_power: float = 0.7
    current_threat: float = 1.5
    immediate_lethal_threat: float = 4.0
    estimated_kill_value: float = 1.0
    number_advantage_value: float = 1.5
    victory_progress_value: float = 4.0
    counter_value: float = 1.0
    growth_threat: float = 1.0
    hand_readiness: float = 1.0
    kill_probability: float = 5.0
    team_focus_support: float = 1.5
    resource_cost: float = 1.2
    turn_cost: float = 1.0
    defense_cost: float = 1.0
    rescue_cost: float = 1.0
    on_damage_benefit: float = 1.5
    retaliation_risk: float = 1.2
    post_failure_threat: float = 1.4
    death_effect_risk: float = 1.2
    kill_penalty: float = 1.5
    accessibility_penalty: float = 8.0

    def __post_init__(self) -> None:
        for name, value in vars(self).items():
            object.__setattr__(self, name, _finite_nonnegative(value, name))


@dataclass(frozen=True)
class FocusPolicy:
    minimum_target_score: float = 0.0
    reasonable_kill_probability: float = 0.15
    immediate_kill_probability: float = 0.80
    immediate_kill_max_turns: float = 1.0
    emergency_threat_threshold: float = 7.0
    emergency_threat_margin: float = 1.0
    switch_score_margin: float = 3.0
    max_reasonable_turns_to_kill: float = 3.0

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "minimum_target_score",
            ensure_finite_real(self.minimum_target_score, "最低目标分数"),
        )
        for name in (
            "reasonable_kill_probability",
            "immediate_kill_probability",
        ):
            object.__setattr__(self, name, _probability(getattr(self, name), name))
        for name in (
            "immediate_kill_max_turns",
            "emergency_threat_threshold",
            "emergency_threat_margin",
            "switch_score_margin",
            "max_reasonable_turns_to_kill",
        ):
            object.__setattr__(
                self,
                name,
                _finite_nonnegative(getattr(self, name), name),
            )


@dataclass(frozen=True)
class TargetAssessment:
    """一名候选敌方在当前合法信息视图下的动态输入。"""

    target_id: str
    static_power: float = 0.0
    current_threat: float = 0.0
    immediate_lethal_threat: float = 0.0
    kill_probability: float = 0.0
    expected_resources_to_kill: float = 0.0
    expected_turns_to_kill: float = 0.0
    defensive_value: float = 0.0
    on_damage_benefit: float = 0.0
    retaliation_risk: float = 0.0
    growth_threat: float = 0.0
    hand_dependency: float = 0.0
    resource_readiness: float = 0.0
    focus_accessibility: float = 1.0
    death_effect_risk: float = 0.0
    estimated_kill_value: float = 0.0
    number_advantage_value: float = 0.0
    victory_progress_value: float = 0.0
    counter_value: float = 0.0
    rescue_cost: float = 0.0
    post_failure_threat: float = 0.0
    kill_reward_value: float = 0.0
    kill_penalty: float = 0.0
    team_focus_support: float = 1.0
    alive: bool = True
    legal_target: bool = True
    defense_spike: bool = False
    continue_focus_negative: bool = False
    information_legal: bool = True
    uses_omniscient_information: bool = False
    omniscient_assumption_disclosed: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.target_id, str) or not self.target_id.strip():
            raise ValueError("目标标识必须是非空字符串")
        object.__setattr__(self, "target_id", self.target_id.strip())
        for name in (
            "static_power",
            "current_threat",
            "immediate_lethal_threat",
            "expected_resources_to_kill",
            "expected_turns_to_kill",
            "defensive_value",
            "on_damage_benefit",
            "retaliation_risk",
            "growth_threat",
            "hand_dependency",
            "death_effect_risk",
            "estimated_kill_value",
            "number_advantage_value",
            "victory_progress_value",
            "counter_value",
            "rescue_cost",
            "post_failure_threat",
            "kill_reward_value",
            "kill_penalty",
        ):
            object.__setattr__(
                self,
                name,
                _finite_nonnegative(getattr(self, name), name),
            )
        for name in (
            "kill_probability",
            "resource_readiness",
            "focus_accessibility",
            "team_focus_support",
        ):
            object.__setattr__(self, name, _probability(getattr(self, name), name))
        for name in (
            "alive",
            "legal_target",
            "defense_spike",
            "continue_focus_negative",
            "information_legal",
            "uses_omniscient_information",
            "omniscient_assumption_disclosed",
        ):
            _ensure_bool(getattr(self, name), name)
        if (
            self.uses_omniscient_information
            and not self.omniscient_assumption_disclosed
        ):
            raise ValueError("使用全知身份或手牌信息时必须明确披露为计算假设")


@dataclass(frozen=True)
class TargetScore:
    target_id: str
    theoretical_priority_score: float
    target_priority_score: float
    executable: bool
    positive_components: Mapping[str, float]
    negative_components: Mapping[str, float]
    reasons: tuple[str, ...]
    assessment: TargetAssessment


def score_focus_target(
    target: TargetAssessment,
    *,
    weights: FocusScoringWeights | None = None,
) -> TargetScore:
    """同时计算理论优先级和当前可执行优先级。"""

    if not isinstance(target, TargetAssessment):
        raise TypeError("目标输入必须是 TargetAssessment")
    resolved_weights = weights or FocusScoringWeights()
    if not isinstance(resolved_weights, FocusScoringWeights):
        raise TypeError("目标评分权重必须是 FocusScoringWeights")

    kill_package = target.kill_probability * (
        target.estimated_kill_value * resolved_weights.estimated_kill_value
        + target.number_advantage_value * resolved_weights.number_advantage_value
        + target.victory_progress_value * resolved_weights.victory_progress_value
        + target.kill_reward_value
    )
    threat_package = (
        target.static_power * resolved_weights.static_power
        + target.current_threat * resolved_weights.current_threat
        + target.immediate_lethal_threat
        * resolved_weights.immediate_lethal_threat
        + target.counter_value * resolved_weights.counter_value
    )
    growth_package = (
        target.growth_threat
        * (0.5 + target.resource_readiness)
        * resolved_weights.growth_threat
        + target.hand_dependency
        * target.resource_readiness
        * resolved_weights.hand_readiness
    )
    efficiency_package = (
        target.kill_probability * resolved_weights.kill_probability
        + target.team_focus_support * resolved_weights.team_focus_support
    )

    resource_cost = (
        target.expected_resources_to_kill * resolved_weights.resource_cost
        + target.expected_turns_to_kill * resolved_weights.turn_cost
    )
    defense_and_rescue_cost = (
        target.defensive_value * resolved_weights.defense_cost
        + target.rescue_cost * resolved_weights.rescue_cost
    )
    failure_probability = 1.0 - target.kill_probability
    damage_and_counter_cost = failure_probability * (
        target.on_damage_benefit * resolved_weights.on_damage_benefit
        + target.retaliation_risk * resolved_weights.retaliation_risk
        + target.post_failure_threat * resolved_weights.post_failure_threat
    )
    death_and_identity_cost = target.kill_probability * (
        target.death_effect_risk * resolved_weights.death_effect_risk
        + target.kill_penalty * resolved_weights.kill_penalty
    )

    positives = MappingProxyType(
        {
            "预计击杀与人数优势价值": kill_package,
            "当前即时威胁与克制价值": threat_package,
            "阻止成长与资源爆发价值": growth_package,
            "近期击杀与队友集火效率": efficiency_package,
        }
    )
    negatives = MappingProxyType(
        {
            "预计击杀资源与回合成本": resource_cost,
            "防御与救援成本": defense_and_rescue_cost,
            "卖血、反制与未击杀反扑风险": damage_and_counter_cost,
            "危险死亡效果与身份惩罚": death_and_identity_cost,
        }
    )
    theoretical = sum(positives.values()) - sum(negatives.values())
    priority = theoretical - (
        1.0 - target.focus_accessibility
    ) * resolved_weights.accessibility_penalty
    executable = bool(
        target.alive
        and target.information_legal
        and target.legal_target
        and target.focus_accessibility > 0
    )

    reasons: list[str] = []
    if target.victory_progress_value > 0:
        reasons.append("击杀可直接推进或满足胜利条件")
    if target.immediate_lethal_threat > 0:
        reasons.append("其下一行动存在即时致命威胁")
    if target.kill_probability >= 0.8:
        reasons.append("近期完成击杀的概率较高")
    if target.expected_resources_to_kill <= 1 and target.defensive_value <= 1:
        reasons.append("防御与预计击杀资源成本较低")
    if target.resource_readiness >= 0.75 and (
        target.growth_threat > 0 or target.hand_dependency > 0
    ):
        reasons.append("资源已接近爆发阈值")
    if target.on_damage_benefit > 0 and target.kill_probability < 0.5:
        reasons.append("无法击杀时会给予较高卖血收益")
    if target.death_effect_risk > 0 or target.kill_penalty > 0:
        reasons.append("击杀存在死亡效果或身份奖惩风险")
    if not target.legal_target or target.focus_accessibility == 0:
        reasons.append("当前不可作为实际集火目标")
    if not reasons:
        ranked_positive = max(positives, key=positives.__getitem__)
        reasons.append(f"主要正向因素为{ranked_positive}")

    return TargetScore(
        target_id=target.target_id,
        theoretical_priority_score=theoretical,
        target_priority_score=priority,
        executable=executable,
        positive_components=positives,
        negative_components=negatives,
        reasons=tuple(reasons),
        assessment=target,
    )


def score_focus_targets(
    targets: Iterable[TargetAssessment],
    *,
    weights: FocusScoringWeights | None = None,
) -> tuple[TargetScore, ...]:
    if targets is None:
        raise TypeError("候选目标不能是 None")
    try:
        prepared = tuple(targets)
    except TypeError as exc:
        raise TypeError("候选目标必须是可迭代序列") from exc
    if not prepared:
        raise ValueError("候选目标不能为空")
    if any(not isinstance(target, TargetAssessment) for target in prepared):
        raise TypeError("每个候选目标都必须是 TargetAssessment")
    ids = [target.target_id for target in prepared]
    if len(ids) != len(set(ids)):
        raise ValueError("候选目标标识不能重复")
    return tuple(score_focus_target(target, weights=weights) for target in prepared)


@dataclass(frozen=True)
class FocusState:
    primary_focus_target: str | None = None
    focus_target_lock: bool = False

    def __post_init__(self) -> None:
        if self.primary_focus_target is not None and (
            not isinstance(self.primary_focus_target, str)
            or not self.primary_focus_target.strip()
        ):
            raise ValueError("主要集火目标必须是非空字符串或 None")
        if self.primary_focus_target is not None:
            object.__setattr__(
                self, "primary_focus_target", self.primary_focus_target.strip()
            )
        _ensure_bool(self.focus_target_lock, "集火锁定标识")
        if self.focus_target_lock and self.primary_focus_target is None:
            raise ValueError("锁定集火时必须指定主要目标")


@dataclass(frozen=True)
class FocusDecision:
    primary_focus_target: str | None
    theoretical_priority_target: str | None
    focus_target_lock: bool
    focus_target_switch_reason: FocusSwitchReason
    target_priority_score: float | None
    ranked_targets: tuple[TargetScore, ...]
    recalculation_event: FocusRecalculationEvent
    explanation: str


def _is_immediate_kill(score: TargetScore, policy: FocusPolicy) -> bool:
    target = score.assessment
    return bool(
        target.kill_probability >= policy.immediate_kill_probability
        and target.expected_turns_to_kill <= policy.immediate_kill_max_turns
    )


def _has_reasonable_kill_path(score: TargetScore, policy: FocusPolicy) -> bool:
    target = score.assessment
    return bool(
        target.kill_probability >= policy.reasonable_kill_probability
        and target.expected_turns_to_kill <= policy.max_reasonable_turns_to_kill
        and not target.continue_focus_negative
    )


def _decision_explanation(
    selected: TargetScore | None,
    reason: FocusSwitchReason,
    *,
    previous_target: str | None,
    theoretical_target: str | None,
) -> str:
    if selected is None:
        suffix = (
            f"；理论优先级最高者为{theoretical_target}，但当前不可合法集火"
            if theoretical_target is not None
            else ""
        )
        return f"暂不建立单体集火目标：当前没有正收益且可执行的目标{suffix}。"
    leading = {
        FocusSwitchReason.INITIAL_SELECTION: f"选择集火{selected.target_id}",
        FocusSwitchReason.KEEP_FOCUS: f"保持集火{selected.target_id}",
    }.get(reason, f"从{previous_target}切换至{selected.target_id}")
    detail = "，且".join(selected.reasons[:2])
    return f"{leading}：{reason.value}；{detail}。"


def select_focus_target(
    targets: Iterable[TargetAssessment],
    *,
    state: FocusState | None = None,
    recalculation_event: FocusRecalculationEvent | str = (
        FocusRecalculationEvent.INITIAL
    ),
    weights: FocusScoringWeights | None = None,
    policy: FocusPolicy | None = None,
) -> FocusDecision:
    """选择或保持主要集火目标，并给出确定性的切换原因。"""

    resolved_state = state or FocusState()
    if not isinstance(resolved_state, FocusState):
        raise TypeError("集火状态必须是 FocusState")
    event = _coerce_enum(
        recalculation_event,
        FocusRecalculationEvent,
        "目标重算事件",
    )
    assert isinstance(event, FocusRecalculationEvent)
    resolved_policy = policy or FocusPolicy()
    if not isinstance(resolved_policy, FocusPolicy):
        raise TypeError("集火策略必须是 FocusPolicy")
    scored = score_focus_targets(targets, weights=weights)
    index = {score.target_id: position for position, score in enumerate(scored)}
    ranked = tuple(
        sorted(
            (
                score
                for score in scored
                if score.assessment.alive and score.assessment.information_legal
            ),
            key=lambda score: (-score.target_priority_score, index[score.target_id]),
        )
    )
    theoretical_candidates = [
        score
        for score in scored
        if score.assessment.alive and score.assessment.information_legal
    ]
    theoretical = max(
        theoretical_candidates,
        key=lambda score: (
            score.theoretical_priority_score,
            -index[score.target_id],
        ),
        default=None,
    )
    executable = [
        score
        for score in ranked
        if score.executable
        and score.target_priority_score >= resolved_policy.minimum_target_score
    ]
    best = executable[0] if executable else None

    def finish(
        selected: TargetScore | None,
        reason: FocusSwitchReason,
    ) -> FocusDecision:
        return FocusDecision(
            primary_focus_target=(selected.target_id if selected else None),
            theoretical_priority_target=(
                theoretical.target_id if theoretical else None
            ),
            focus_target_lock=selected is not None,
            focus_target_switch_reason=reason,
            target_priority_score=(
                selected.target_priority_score if selected else None
            ),
            ranked_targets=ranked,
            recalculation_event=event,
            explanation=_decision_explanation(
                selected,
                reason,
                previous_target=resolved_state.primary_focus_target,
                theoretical_target=(theoretical.target_id if theoretical else None),
            ),
        )

    current_id = resolved_state.primary_focus_target
    if not resolved_state.focus_target_lock or current_id is None:
        return finish(
            best,
            FocusSwitchReason.INITIAL_SELECTION
            if best is not None
            else FocusSwitchReason.NO_EXECUTABLE_TARGET,
        )

    current = next((score for score in scored if score.target_id == current_id), None)
    alternatives = [score for score in executable if score.target_id != current_id]
    best_alternative = alternatives[0] if alternatives else None

    if current is None or not current.assessment.alive:
        return finish(best_alternative, FocusSwitchReason.TARGET_DEAD)
    if event is FocusRecalculationEvent.VICTORY_OR_IDENTITY_CHANGE:
        selected = best if best is not None else None
        return finish(selected, FocusSwitchReason.VICTORY_OR_IDENTITY_CHANGED)
    if not current.executable:
        return finish(best_alternative, FocusSwitchReason.TARGET_UNREACHABLE)
    if current.assessment.defense_spike:
        return finish(best_alternative, FocusSwitchReason.TARGET_DEFENSE_SPIKE)
    if (
        current.assessment.continue_focus_negative
        or current.target_priority_score < resolved_policy.minimum_target_score
    ):
        return finish(
            best_alternative,
            FocusSwitchReason.NEGATIVE_ON_DAMAGE_TRADE,
        )
    if (
        event is FocusRecalculationEvent.TEAM_FOCUS_CHANGE
        and current.assessment.team_focus_support == 0
    ):
        return finish(best_alternative, FocusSwitchReason.TEAM_FOCUS_LOST)

    emergency = next(
        (
            score
            for score in alternatives
            if score.assessment.immediate_lethal_threat
            >= resolved_policy.emergency_threat_threshold
            and score.assessment.immediate_lethal_threat
            >= current.assessment.immediate_lethal_threat
            + resolved_policy.emergency_threat_margin
        ),
        None,
    )
    if emergency is not None:
        return finish(emergency, FocusSwitchReason.OTHER_LETHAL_THREAT)

    immediate_kill = next(
        (score for score in alternatives if _is_immediate_kill(score, resolved_policy)),
        None,
    )
    if immediate_kill is not None and not _is_immediate_kill(current, resolved_policy):
        return finish(immediate_kill, FocusSwitchReason.OTHER_IMMEDIATE_KILL)

    if _has_reasonable_kill_path(current, resolved_policy):
        return finish(current, FocusSwitchReason.KEEP_FOCUS)
    if (
        best_alternative is not None
        and best_alternative.target_priority_score
        >= current.target_priority_score + resolved_policy.switch_score_margin
    ):
        return finish(
            best_alternative,
            FocusSwitchReason.TARGET_NO_LONGER_KILLABLE,
        )
    return finish(current, FocusSwitchReason.KEEP_FOCUS)


def allocate_single_target_attacks(
    action_count: int,
    decision: FocusDecision,
    legal_targets: Sequence[str],
) -> tuple[str, ...]:
    """把可用单体攻击集中到主要目标，不做轮流或平均分配。"""

    count = ensure_int_at_least(action_count, "单体攻击数量", 0)
    if not isinstance(decision, FocusDecision):
        raise TypeError("集火决策必须是 FocusDecision")
    if legal_targets is None:
        raise TypeError("合法目标不能是 None")
    try:
        prepared = tuple(legal_targets)
    except TypeError as exc:
        raise TypeError("合法目标必须是可迭代序列") from exc
    if any(not isinstance(target, str) or not target.strip() for target in prepared):
        raise ValueError("合法目标必须是非空字符串")
    primary = decision.primary_focus_target
    if count == 0 or primary is None or primary not in prepared:
        return ()
    return (primary,) * count


@dataclass(frozen=True)
class FocusActionCandidate:
    action_id: str
    action_kind: FocusActionKind
    legal_targets: tuple[str, ...] = ()
    tactical_value_by_target: Mapping[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.action_id, str) or not self.action_id.strip():
            raise ValueError("行动标识必须是非空字符串")
        object.__setattr__(self, "action_id", self.action_id.strip())
        object.__setattr__(
            self,
            "action_kind",
            _coerce_enum(self.action_kind, FocusActionKind, "行动类型"),
        )
        try:
            targets = tuple(self.legal_targets)
        except TypeError as exc:
            raise TypeError("行动合法目标必须是可迭代序列") from exc
        if any(not isinstance(target, str) or not target.strip() for target in targets):
            raise ValueError("行动合法目标必须是非空字符串")
        if len(targets) != len(set(targets)):
            raise ValueError("同一行动的合法目标不能重复")
        object.__setattr__(self, "legal_targets", targets)
        if not isinstance(self.tactical_value_by_target, Mapping):
            raise TypeError("行动战术价值必须是目标到数值的映射")
        values: dict[str, float] = {}
        for target, value in self.tactical_value_by_target.items():
            if target not in targets:
                raise ValueError("行动战术价值只能填写合法目标")
            values[target] = ensure_finite_real(value, "行动战术价值")
        object.__setattr__(
            self,
            "tactical_value_by_target",
            MappingProxyType(values),
        )


@dataclass(frozen=True)
class PlannedFocusAction:
    action_id: str
    action_kind: FocusActionKind
    target_id: str | None
    serves_primary_focus: bool
    reason: str


def plan_focus_actions(
    actions: Iterable[FocusActionCandidate],
    decision: FocusDecision,
) -> tuple[PlannedFocusAction, ...]:
    """让单牌行动服务主要击杀目标，同时允许控制次要致命威胁。"""

    if not isinstance(decision, FocusDecision):
        raise TypeError("集火决策必须是 FocusDecision")
    if actions is None:
        raise TypeError("候选行动不能是 None")
    try:
        prepared = tuple(actions)
    except TypeError as exc:
        raise TypeError("候选行动必须是可迭代序列") from exc
    if any(not isinstance(action, FocusActionCandidate) for action in prepared):
        raise TypeError("每个候选行动都必须是 FocusActionCandidate")
    if len({action.action_id for action in prepared}) != len(prepared):
        raise ValueError("行动标识不能重复")

    scores = {score.target_id: score for score in decision.ranked_targets}
    primary = decision.primary_focus_target
    focus_first_kinds = {
        FocusActionKind.SINGLE_TARGET_DAMAGE,
        FocusActionKind.DUEL,
        FocusActionKind.DISRUPT_DEFENSE_OR_RESCUE,
        FocusActionKind.CHAIN_OR_FIRE_COMBO,
    }
    planned: list[PlannedFocusAction] = []
    for action in prepared:
        kind = action.action_kind
        if kind in {
            FocusActionKind.PRESERVE_TEAM_RESOURCE,
            FocusActionKind.HOLD,
        }:
            planned.append(
                PlannedFocusAction(
                    action.action_id,
                    kind,
                    None,
                    False,
                    "保留关键资源以维持后续集火或救援能力",
                )
            )
            continue
        legal_scores = [
            scores[target]
            for target in action.legal_targets
            if target in scores and scores[target].executable
        ]
        if not legal_scores:
            planned.append(
                PlannedFocusAction(
                    action.action_id,
                    kind,
                    None,
                    False,
                    "当前没有合法目标，保留资源或调整距离",
                )
            )
            continue

        selected: TargetScore
        if kind in focus_first_kinds and primary in action.legal_targets:
            selected = scores[primary]
        elif kind is FocusActionKind.CONTROL:
            selected = max(
                legal_scores,
                key=lambda score: (
                    score.assessment.immediate_lethal_threat * 4
                    + score.assessment.current_threat
                    + action.tactical_value_by_target.get(score.target_id, 0),
                    score.target_priority_score,
                    -action.legal_targets.index(score.target_id),
                ),
            )
        else:
            selected = max(
                legal_scores,
                key=lambda score: (
                    score.target_priority_score
                    + action.tactical_value_by_target.get(score.target_id, 0),
                    -action.legal_targets.index(score.target_id),
                ),
            )

        serves_focus = selected.target_id == primary
        if kind is FocusActionKind.DISRUPT_DEFENSE_OR_RESCUE and serves_focus:
            reason = "优先移除主要集火目标的防御或救援资源"
        elif kind is FocusActionKind.CONTROL and not serves_focus:
            reason = "控制非主要目标的即时威胁，保护集火过程"
        elif kind is FocusActionKind.CHAIN_OR_FIRE_COMBO and serves_focus:
            reason = "铁索或火攻组合服务于主要目标的实际击杀"
        elif serves_focus:
            reason = "单体资源继续投入主要集火目标，避免平均分散"
        else:
            reason = "主要目标当前不在本行动合法范围，选择当前最优合法目标"
        planned.append(
            PlannedFocusAction(
                action.action_id,
                kind,
                selected.target_id,
                serves_focus,
                reason,
            )
        )
    return tuple(planned)
