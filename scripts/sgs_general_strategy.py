"""三国杀固定阵容的按需武将画像与透明目标优先级参数。

本模块只实现轻量、可解释的策略输入层。它不维护完整武将数据库，也不
凭模型记忆补全技能；调用方只需为本次实际参战武将提供已知资料。这里的
权重属于可调计算参数，不是游戏规则或官方 AI 参数。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Mapping, Sequence

from ._validation import ensure_finite_real, ensure_int_at_least


class StrengthTier(Enum):
    WEAK = "较弱"
    MEDIUM = "中等"
    STRONG = "较强"
    OUTLIER = "明显高于评测档位"


class StrategyLevel(Enum):
    NONE = "无"
    LIGHT = "轻度"
    MEDIUM = "中等"
    STRONG = "强"


def _nonempty(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label}必须是非空字符串")
    return value.strip()


def _optional_text(value: object, label: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError(f"{label}必须是字符串或 None")
    return value.strip() or None


def _nonnegative(value: object, label: str) -> float:
    number = ensure_finite_real(value, label)
    if number < 0:
        raise ValueError(f"{label}必须是非负有限数值")
    return number


def _coerce_enum(value: object, enum_type: type[Enum], label: str) -> Enum:
    if isinstance(value, enum_type):
        return value
    try:
        return enum_type(value)
    except (TypeError, ValueError) as exc:
        allowed = "、".join(member.value for member in enum_type)
        raise ValueError(f"{label}只能是：{allowed}") from exc


@dataclass(frozen=True)
class GeneralProfile:
    """仅针对本次参战武将建立的资料画像。空字段保持未知。"""

    general_name: str
    base_hp: int | None = None
    base_max_hp: int | None = None
    skill_text: str | None = None
    skill_version: str | None = None
    strength_tier: StrengthTier | str = StrengthTier.MEDIUM
    defense_value: float | None = None
    on_damage_benefit: float | None = None
    retaliation_risk: float | None = None
    burst_threat: float | None = None
    control_threat: float | None = None
    growth_threat: float | None = None
    hand_dependency: float | None = None
    equipment_dependency: float | None = None
    kill_difficulty: float | None = None
    special_interactions: tuple[str, ...] = ()
    source: str | None = None
    confidence: str = "待核验"
    parsed_skill_rules: tuple[str, ...] = ()
    unresolved_interactions: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "general_name", _nonempty(self.general_name, "武将名称"))
        if self.base_hp is not None:
            object.__setattr__(self, "base_hp", ensure_int_at_least(self.base_hp, "基础体力", 1))
        if self.base_max_hp is not None:
            object.__setattr__(
                self,
                "base_max_hp",
                ensure_int_at_least(self.base_max_hp, "基础体力上限", 1),
            )
        if (
            self.base_hp is not None
            and self.base_max_hp is not None
            and self.base_hp > self.base_max_hp
        ):
            raise ValueError("基础体力不能高于基础体力上限")
        for name in ("skill_text", "skill_version", "source"):
            object.__setattr__(self, name, _optional_text(getattr(self, name), name))
        tier = _coerce_enum(self.strength_tier, StrengthTier, "强度档位")
        object.__setattr__(self, "strength_tier", tier)
        for name in (
            "defense_value",
            "on_damage_benefit",
            "retaliation_risk",
            "burst_threat",
            "control_threat",
            "growth_threat",
            "hand_dependency",
            "equipment_dependency",
            "kill_difficulty",
        ):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, _nonnegative(value, name))
        for name in (
            "special_interactions",
            "parsed_skill_rules",
            "unresolved_interactions",
        ):
            values = getattr(self, name)
            if not isinstance(values, tuple) or any(
                not isinstance(item, str) or not item.strip() for item in values
            ):
                raise ValueError(f"{name}必须是非空字符串组成的元组")
        if self.confidence not in {
            "当前确认",
            "用户整理解释",
            "文本推导",
            "模拟假设",
            "待核验",
            "历史规则",
            "分析约定",
        }:
            raise ValueError("画像置信状态必须使用项目允许的状态标签")

    @property
    def missing_fields(self) -> tuple[str, ...]:
        fields: list[str] = []
        for name in ("base_hp", "base_max_hp", "skill_text", "skill_version", "source"):
            if getattr(self, name) is None:
                fields.append(name)
        return tuple(fields)


@dataclass(frozen=True)
class FixedLineupProfiles:
    profiles: Mapping[str, GeneralProfile]
    missing_general_inputs: tuple[str, ...]
    complete_general_database_required: bool = False
    common_rules_simulation_available: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "profiles", MappingProxyType(dict(self.profiles)))


def build_on_demand_general_profiles(
    participant_names: Sequence[str],
    supplied_profiles: Mapping[str, GeneralProfile | Mapping[str, object]],
) -> FixedLineupProfiles:
    """只为实际参战武将建立画像；未提供者保留空壳与明确缺口。"""

    if not isinstance(participant_names, Sequence) or isinstance(participant_names, str):
        raise TypeError("参战武将必须是名称序列")
    if not isinstance(supplied_profiles, Mapping):
        raise TypeError("已提供武将画像必须是字段映射")
    names = tuple(_nonempty(name, "参战武将名称") for name in participant_names)
    if not names:
        raise ValueError("固定阵容至少需要一名参战武将")
    if len(set(names)) != len(names):
        raise ValueError("固定阵容中的武将名称不能重复")

    profiles: dict[str, GeneralProfile] = {}
    missing: list[str] = []
    for name in names:
        raw = supplied_profiles.get(name)
        if raw is None:
            profiles[name] = GeneralProfile(general_name=name)
            missing.append(name)
        elif isinstance(raw, GeneralProfile):
            if raw.general_name != name:
                raise ValueError(f"画像键 {name!r} 与画像内武将名称不一致")
            profiles[name] = raw
        elif isinstance(raw, Mapping):
            values = dict(raw)
            values.setdefault("general_name", name)
            profile = GeneralProfile(**values)
            if profile.general_name != name:
                raise ValueError(f"画像键 {name!r} 与画像内武将名称不一致")
            profiles[name] = profile
        else:
            raise TypeError(f"武将 {name} 的画像必须是 GeneralProfile 或字段映射")
    return FixedLineupProfiles(
        profiles=profiles,
        missing_general_inputs=tuple(missing),
    )


@dataclass(frozen=True)
class TauntDefaults:
    """透明、可复现的首版目标优先级参数。"""

    weak_static: float = -0.8
    medium_static: float = 0.0
    strong_static: float = 0.8
    outlier_static: float = 1.6
    missing_hp_point: float = 0.45
    hand_below_four_point: float = 0.15
    hand_above_four_point: float = -0.15
    light_defense: float = 0.4
    medium_defense: float = 0.8
    strong_defense: float = 1.4
    light_on_damage: float = 0.4
    medium_on_damage: float = 0.9
    strong_on_damage: float = 1.5
    immediate_kill_bonus: float = 2.5
    emergency_lethal_min: float = 1.5
    emergency_lethal_max: float = 3.0
    focus_continuity_bonus: float = 0.4
    hand_based_threat_per_extra_card: float = 0.25

    def __post_init__(self) -> None:
        for name, value in vars(self).items():
            object.__setattr__(self, name, ensure_finite_real(value, name))
        if not 0.15 <= self.hand_based_threat_per_extra_card <= 0.4:
            raise ValueError("手牌依赖威胁系数必须在 0.15 至 0.4 之间")
        if self.emergency_lethal_min > self.emergency_lethal_max:
            raise ValueError("紧急威胁下界不能高于上界")

    def report(self) -> Mapping[str, float]:
        return MappingProxyType(dict(vars(self)))


@dataclass(frozen=True)
class TargetSituation:
    target_id: str
    strength_tier: StrengthTier | str = StrengthTier.MEDIUM
    base_max_hp: int = 4
    initial_hp: int = 4
    current_hp: int = 4
    hand_count: int = 4
    defense_level: StrategyLevel | str = StrategyLevel.NONE
    on_damage_level: StrategyLevel | str = StrategyLevel.NONE
    current_threat: float = 0.0
    growth_threat: float = 0.0
    kill_efficiency: float = 0.0
    retaliation_risk: float = 0.0
    post_failure_risk: float = 0.0
    counter_value: float = 0.0
    hand_dependent: bool = False
    immediate_kill_available: bool = False
    emergency_lethal_intensity: float = 0.0
    focus_accessibility: float = 1.0
    already_primary_focus: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "target_id", _nonempty(self.target_id, "目标标识"))
        object.__setattr__(self, "strength_tier", _coerce_enum(self.strength_tier, StrengthTier, "强度档位"))
        object.__setattr__(self, "defense_level", _coerce_enum(self.defense_level, StrategyLevel, "防御等级"))
        object.__setattr__(self, "on_damage_level", _coerce_enum(self.on_damage_level, StrategyLevel, "卖血等级"))
        ensure_int_at_least(self.base_max_hp, "基础体力上限", 1)
        initial = ensure_int_at_least(self.initial_hp, "初始体力", 1)
        if isinstance(self.current_hp, bool) or not isinstance(self.current_hp, int):
            raise TypeError("当前体力必须是整数")
        if self.current_hp > initial:
            raise ValueError("当前体力不能高于本次评分采用的初始体力")
        ensure_int_at_least(self.hand_count, "手牌数", 0)
        for name in (
            "current_threat",
            "growth_threat",
            "kill_efficiency",
            "retaliation_risk",
            "post_failure_risk",
            "counter_value",
            "emergency_lethal_intensity",
        ):
            object.__setattr__(self, name, _nonnegative(getattr(self, name), name))
        if not 0 <= self.emergency_lethal_intensity <= 1:
            raise ValueError("紧急致命威胁强度必须在 0 至 1 之间")
        accessibility = ensure_finite_real(self.focus_accessibility, "集火可达性")
        if not 0 <= accessibility <= 1:
            raise ValueError("集火可达性必须在 0 至 1 之间")
        for name in ("hand_dependent", "immediate_kill_available", "already_primary_focus"):
            if not isinstance(getattr(self, name), bool):
                raise TypeError(f"{name}必须是布尔值")


@dataclass(frozen=True)
class TargetPriorityBreakdown:
    target_id: str
    static_threat: float
    current_threat: float
    kill_efficiency: float
    defense_cost: float
    on_damage_benefit: float
    retaliation_risk: float
    immediate_lethal_threat: float
    focus_accessibility: float
    focus_continuity: float
    hand_based_threat_bonus: float
    base_hp_vulnerability: float
    target_priority: float
    parameters: Mapping[str, float]
    reasons: tuple[str, ...]


def calculate_target_priority(
    situation: TargetSituation,
    *,
    defaults: TauntDefaults | None = None,
) -> TargetPriorityBreakdown:
    """按拆分字段计算目标优先级，并回显本次采用的全部参数。"""

    if not isinstance(situation, TargetSituation):
        raise TypeError("目标局面必须是 TargetSituation")
    values = defaults or TauntDefaults()
    if not isinstance(values, TauntDefaults):
        raise TypeError("嘲讽参数必须是 TauntDefaults")

    static_by_tier = {
        StrengthTier.WEAK: values.weak_static,
        StrengthTier.MEDIUM: values.medium_static,
        StrengthTier.STRONG: values.strong_static,
        StrengthTier.OUTLIER: values.outlier_static,
    }
    defense_by_level = {
        StrategyLevel.NONE: 0.0,
        StrategyLevel.LIGHT: values.light_defense,
        StrategyLevel.MEDIUM: values.medium_defense,
        StrategyLevel.STRONG: values.strong_defense,
    }
    on_damage_by_level = {
        StrategyLevel.NONE: 0.0,
        StrategyLevel.LIGHT: values.light_on_damage,
        StrategyLevel.MEDIUM: values.medium_on_damage,
        StrategyLevel.STRONG: values.strong_on_damage,
    }
    static_threat = static_by_tier[situation.strength_tier]
    # 基础三体力武将比默认四体力武将少一个固有生存单位。这里复用公开的
    # 每点体力权重，避免另藏一套不可解释参数；主公/地主的赛前 +1 不会
    # 反向改写武将的 base_max_hp。
    base_hp_vulnerability = max(0, 4 - situation.base_max_hp) * values.missing_hp_point
    missing_hp_bonus = max(0, situation.initial_hp - situation.current_hp) * values.missing_hp_point
    hand_delta = situation.hand_count - 4
    hand_killability = (
        -hand_delta * values.hand_below_four_point
        if hand_delta < 0
        else hand_delta * values.hand_above_four_point
    )
    hand_threat = (
        max(0, hand_delta) * values.hand_based_threat_per_extra_card
        if situation.hand_dependent
        else 0.0
    )
    defense_cost = defense_by_level[situation.defense_level]
    on_damage_cost = on_damage_by_level[situation.on_damage_level]
    lethal_bonus = (
        values.emergency_lethal_min
        + situation.emergency_lethal_intensity
        * (values.emergency_lethal_max - values.emergency_lethal_min)
        if situation.emergency_lethal_intensity > 0
        else 0.0
    )
    immediate_kill = values.immediate_kill_bonus if situation.immediate_kill_available else 0.0
    focus_continuity = values.focus_continuity_bonus if situation.already_primary_focus else 0.0
    accessibility_penalty = (1.0 - situation.focus_accessibility) * 3.0
    priority = (
        static_threat
        + situation.current_threat
        + situation.growth_threat
        + situation.kill_efficiency
        + base_hp_vulnerability
        + missing_hp_bonus
        + hand_killability
        + hand_threat
        + immediate_kill
        + lethal_bonus
        + focus_continuity
        + situation.counter_value
        - defense_cost
        - on_damage_cost
        - situation.retaliation_risk
        - situation.post_failure_risk
        - accessibility_penalty
    )
    reasons: list[str] = []
    if immediate_kill:
        reasons.append("当前存在高概率即时击杀，显著提高优先级")
    if lethal_bonus:
        reasons.append("目标下次行动可能形成致命威胁")
    if defense_cost:
        reasons.append("防御提高预计击杀资源成本")
    if on_damage_cost:
        reasons.append("未能集中击杀时会给予目标卖血收益")
    if hand_threat:
        reasons.append("手牌提高该手牌依赖型武将的当前威胁")
    if situation.focus_accessibility < 1:
        reasons.append("理论高优先目标当前不完全可达")
    if focus_continuity:
        reasons.append("延续已有集火成果，避免无理由切换")
    if base_hp_vulnerability:
        reasons.append("基础体力上限低于四体力基准，预计击杀资源更少")
    if not reasons:
        reasons.append("按静态强度、当前威胁与击杀效率综合比较")
    return TargetPriorityBreakdown(
        target_id=situation.target_id,
        static_threat=static_threat,
        current_threat=situation.current_threat + situation.growth_threat,
        kill_efficiency=(
            situation.kill_efficiency
            + base_hp_vulnerability
            + missing_hp_bonus
            + hand_killability
            + immediate_kill
        ),
        defense_cost=defense_cost,
        on_damage_benefit=on_damage_cost,
        retaliation_risk=situation.retaliation_risk + situation.post_failure_risk,
        immediate_lethal_threat=lethal_bonus,
        focus_accessibility=situation.focus_accessibility,
        focus_continuity=focus_continuity,
        hand_based_threat_bonus=hand_threat,
        base_hp_vulnerability=base_hp_vulnerability,
        target_priority=priority,
        parameters=values.report(),
        reasons=tuple(reasons),
    )


def choose_executable_priority_target(
    situations: Sequence[TargetSituation],
    *,
    defaults: TauntDefaults | None = None,
) -> tuple[TargetPriorityBreakdown, tuple[TargetPriorityBreakdown, ...]]:
    """区分理论最高优先目标与当前可执行目标，保持输入顺序同分稳定。"""

    if not isinstance(situations, Sequence) or isinstance(situations, (str, bytes)):
        raise TypeError("候选目标必须是局面序列")
    if not situations:
        raise ValueError("候选目标不能为空")
    scored = tuple(calculate_target_priority(item, defaults=defaults) for item in situations)
    executable = [score for score in scored if score.focus_accessibility > 0]
    if not executable:
        raise ValueError("当前没有可执行的攻击目标")
    selected = max(executable, key=lambda score: score.target_priority)
    return selected, scored
