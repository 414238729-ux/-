"""三国杀跨武将技能类型与通用结算的轻量状态模型。

本模块只实现 Knowledge 已由用户确认的跨武将边界，不尝试成为完整游戏
引擎，也不补全具体武将技能。技能失效、失去技能、转换状态与蓄力资源均
独立保存，调用方可在固定阵容模拟中按需组合。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from enum import Enum
from typing import Callable, Iterable

from ._validation import ensure_int_at_least


def _nonempty_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label}必须是非空字符串")
    return value.strip()


def _coerce_enum(value: object, enum_type: type[Enum], label: str) -> Enum:
    if isinstance(value, enum_type):
        return value
    try:
        return enum_type(value)
    except (TypeError, ValueError) as exc:
        allowed = "、".join(member.value for member in enum_type)
        raise ValueError(f"{label}只能是：{allowed}") from exc


def _coerce_bool(value: object, label: str) -> bool:
    if not isinstance(value, bool):
        raise TypeError(f"{label}必须是布尔值")
    return value


class SkillType(Enum):
    """可组合的技能类型标签；成员之间并非互斥关系。"""

    LOCKED = "锁定技"
    LIMITED = "限定技"
    AWAKENING = "觉醒技"
    MISSION = "使命技"
    PERSEVERING = "持恒技"
    CONVERSION = "转换技"
    CHARGE = "蓄力技"


class SkillSource(Enum):
    """技能当前来源，用于区分武将牌技能与其他来源。"""

    GENERAL_CARD = "武将牌"
    IDENTITY = "身份"
    GRANTED_BY_CHARACTER = "其他角色授予"
    EQUIPMENT = "装备"
    MODE = "模式状态"
    OTHER = "其他来源"


class SkillInvalidationScope(Enum):
    """失效效果文字所指向的范围。"""

    GENERAL_CARD_ONLY = "武将牌上的技能失效"
    ALL_OWNED_SKILLS = "技能失效"


class InvalidationKind(Enum):
    TEMPORARY = "临时失效"
    SEMI_PERMANENT = "半永久失效"


class MissionState(Enum):
    UNRESOLVED = "未决"
    SUCCESS = "成功"
    FAILURE = "失败"


class ConversionState(Enum):
    YANG = "阳"
    YIN = "阴"


class CardZone(Enum):
    HAND = "手牌区"
    EQUIPMENT = "装备区"
    JUDGMENT = "判定区"


class CardTerm(Enum):
    CARD = "牌"
    HAND_CARD = "手牌"
    CARDS_IN_ZONES = "区域内的牌"


def normalize_skill_tags(
    tags: Iterable[SkillType | str],
) -> frozenset[SkillType]:
    """校验并保留任意组合的技能类型标签。"""

    if tags is None or isinstance(tags, (str, bytes)):
        raise TypeError("技能类型标签必须是可迭代集合，不能是单个字符串")
    try:
        values = tuple(tags)
    except TypeError as exc:
        raise TypeError("技能类型标签必须是可迭代集合") from exc
    return frozenset(
        _coerce_enum(item, SkillType, "技能类型标签") for item in values
    )


@dataclass(frozen=True)
class SkillInvalidation:
    """一次技能失效状态；它与永久的技能丢失严格分离。"""

    kind: InvalidationKind | str
    duration: str | None = None
    recovery_condition: str | None = None

    def __post_init__(self) -> None:
        kind = _coerce_enum(self.kind, InvalidationKind, "失效类型")
        object.__setattr__(self, "kind", kind)
        duration = (
            None
            if self.duration is None
            else _nonempty_text(self.duration, "失效持续时间")
        )
        recovery = (
            None
            if self.recovery_condition is None
            else _nonempty_text(self.recovery_condition, "失效恢复条件")
        )
        if kind is InvalidationKind.TEMPORARY and duration is None:
            raise ValueError("临时失效必须注明持续时间或恢复时点")
        if kind is InvalidationKind.SEMI_PERMANENT and recovery is None:
            raise ValueError("半永久失效必须注明恢复条件")
        object.__setattr__(self, "duration", duration)
        object.__setattr__(self, "recovery_condition", recovery)

    def can_recover(self, event: str) -> bool:
        """判断当前事件是否满足本次失效的恢复条件。"""

        resolved_event = _nonempty_text(event, "恢复事件")
        expected = self.recovery_condition or self.duration
        return resolved_event == expected


@dataclass(frozen=True)
class SkillState:
    """一项技能的拥有、来源、失效及失去状态。"""

    skill_name: str
    type_tags: frozenset[SkillType] | Iterable[SkillType | str] = frozenset()
    source: SkillSource | str = SkillSource.GENERAL_CARD
    invalidation: SkillInvalidation | None = None
    lost: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "skill_name", _nonempty_text(self.skill_name, "技能名称"))
        object.__setattr__(self, "type_tags", normalize_skill_tags(self.type_tags))
        object.__setattr__(self, "source", _coerce_enum(self.source, SkillSource, "技能来源"))
        _coerce_bool(self.lost, "技能是否已失去")
        if self.invalidation is not None and not isinstance(
            self.invalidation, SkillInvalidation
        ):
            raise TypeError("技能失效状态必须是 SkillInvalidation 或 None")
        if self.lost and self.invalidation is not None:
            raise ValueError("已经失去的技能不能同时保留失效状态")
        if self.is_persevering and self.invalidation is not None:
            raise ValueError("持恒技不能直接构造为失效状态")

    @property
    def owned(self) -> bool:
        return not self.lost

    @property
    def is_persevering(self) -> bool:
        return SkillType.PERSEVERING in self.type_tags

    @property
    def invalidated(self) -> bool:
        return self.invalidation is not None

    @property
    def effective(self) -> bool:
        return self.owned and not self.invalidated

    def invalidate(self, effect: SkillInvalidation) -> "SkillState":
        """应用失效；持恒技和已失去技能不会进入失效状态。"""

        if not isinstance(effect, SkillInvalidation):
            raise TypeError("失效效果必须是 SkillInvalidation")
        if self.lost or self.is_persevering:
            return self
        return replace(self, invalidation=effect)

    def lose(self) -> "SkillState":
        """明确失去技能；持恒技也可被明确的失去效果移除。"""

        return replace(self, lost=True, invalidation=None)

    def recover(self, event: str) -> "SkillState":
        """只在当前失效条件满足时恢复；不会恢复已失去的技能。"""

        if self.lost or self.invalidation is None:
            return self
        if self.invalidation.can_recover(event):
            return replace(self, invalidation=None)
        return self


def invalidate_skills(
    skills: Iterable[SkillState],
    *,
    scope: SkillInvalidationScope | str,
    effect: SkillInvalidation,
) -> tuple[SkillState, ...]:
    """按“武将牌技能”或“全部技能”范围应用失效。

    两种范围都自动排除持恒技；普通“技能失效”会覆盖身份技能、他授
    技能、装备与模式技能，而武将牌范围只触及 ``GENERAL_CARD``。
    """

    if skills is None:
        raise TypeError("技能列表不能是 None")
    try:
        values = tuple(skills)
    except TypeError as exc:
        raise TypeError("技能列表必须是可迭代对象") from exc
    if any(not isinstance(skill, SkillState) for skill in values):
        raise TypeError("技能列表中的每一项都必须是 SkillState")
    resolved_scope = _coerce_enum(scope, SkillInvalidationScope, "技能失效范围")
    if not isinstance(effect, SkillInvalidation):
        raise TypeError("失效效果必须是 SkillInvalidation")
    return tuple(
        skill.invalidate(effect)
        if (
            resolved_scope is SkillInvalidationScope.ALL_OWNED_SKILLS
            or skill.source is SkillSource.GENERAL_CARD
        )
        else skill
        for skill in values
    )


def activation_is_mandatory(
    skill: SkillState,
    *,
    conditions_met: bool,
    text_allows_choice: bool = False,
) -> bool:
    """判断技能是否必须发动，避免把客户端“被动”当作锁定技。

    觉醒技在有效且满足条件时必须完成；锁定技仅在文字没有明确“可以”
    时强制生效。
    """

    if not isinstance(skill, SkillState):
        raise TypeError("技能状态必须是 SkillState")
    _coerce_bool(conditions_met, "技能条件是否满足")
    _coerce_bool(text_allows_choice, "技能文字是否允许选择")
    if not conditions_met or not skill.effective:
        return False
    if SkillType.AWAKENING in skill.type_tags:
        return True
    return SkillType.LOCKED in skill.type_tags and not text_allows_choice


@dataclass(frozen=True)
class LimitedSkillState:
    """默认整局一次、且可由明确规则恢复次数的限定技状态。"""

    consumed: bool = False

    def __post_init__(self) -> None:
        _coerce_bool(self.consumed, "限定技次数是否已消耗")

    @property
    def can_activate(self) -> bool:
        return not self.consumed

    def consume(self) -> "LimitedSkillState":
        if self.consumed:
            raise ValueError("限定技次数已经消耗，不能再次发动")
        return LimitedSkillState(consumed=True)

    def restore(self) -> "LimitedSkillState":
        """只应由明确写有恢复限定次数的具体效果调用。"""

        return LimitedSkillState(consumed=False)


@dataclass(frozen=True)
class AwakeningSkillState:
    """满足条件后必须完成、默认整局一次的觉醒技状态。"""

    awakened: bool = False

    def __post_init__(self) -> None:
        _coerce_bool(self.awakened, "觉醒是否完成")

    def resolve(self, *, conditions_met: bool) -> "AwakeningSkillState":
        _coerce_bool(conditions_met, "觉醒条件是否满足")
        if self.awakened:
            raise ValueError("觉醒技已经完成，不能重复觉醒")
        if not conditions_met:
            raise ValueError("觉醒条件尚未满足，不能完成觉醒")
        return AwakeningSkillState(awakened=True)


@dataclass(frozen=True)
class MissionSkillState:
    """使命技的未决、成功、失败三态。"""

    status: MissionState | str = MissionState.UNRESOLVED

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", _coerce_enum(self.status, MissionState, "使命状态"))

    def resolve(self, outcome: MissionState | str) -> "MissionSkillState":
        resolved = _coerce_enum(outcome, MissionState, "使命结果")
        if resolved is MissionState.UNRESOLVED:
            raise ValueError("使命结算结果不能仍为未决")
        if self.status is not MissionState.UNRESOLVED:
            raise ValueError("使命已经结算，不能重复改写结果")
        return MissionSkillState(status=resolved)


@dataclass(frozen=True)
class ConversionSkillState:
    """默认阳起始、效果完成后切换阴阳的转换技状态。"""

    state: ConversionState | str = ConversionState.YANG
    initial_state: ConversionState | str = ConversionState.YANG
    toggle_after_effect: bool = True
    state_specific_limit: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "state", _coerce_enum(self.state, ConversionState, "转换技状态"))
        object.__setattr__(
            self,
            "initial_state",
            _coerce_enum(self.initial_state, ConversionState, "转换技初始状态"),
        )
        _coerce_bool(self.toggle_after_effect, "效果后是否切换状态")
        if self.state_specific_limit is not None:
            ensure_int_at_least(self.state_specific_limit, "转换技明确次数限制", 1)

    def can_resolve(self, *, uses_in_scope: int = 0) -> bool:
        used = ensure_int_at_least(uses_in_scope, "当前范围内已发动次数", 0)
        return self.state_specific_limit is None or used < self.state_specific_limit

    def resolve_effect(self, *, uses_in_scope: int = 0) -> "ConversionSkillState":
        if not self.can_resolve(uses_in_scope=uses_in_scope):
            raise ValueError("转换技已达到技能文字明确规定的次数限制")
        if not self.toggle_after_effect:
            return self
        next_state = (
            ConversionState.YIN
            if self.state is ConversionState.YANG
            else ConversionState.YANG
        )
        return replace(self, state=next_state)


_CHARGE_NOTATION = re.compile(r"^\s*(\d+)\s*/\s*(\d+)\s*$")


@dataclass(frozen=True)
class ChargeState:
    """一项独立蓄力资源的初始值、当前值和上限。"""

    resource_key: str
    initial: int
    maximum: int
    current: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "resource_key", _nonempty_text(self.resource_key, "蓄力资源标识"))
        initial = ensure_int_at_least(self.initial, "初始蓄力点", 0)
        maximum = ensure_int_at_least(self.maximum, "蓄力上限", 0)
        current = ensure_int_at_least(self.current, "当前蓄力点", 0)
        if initial > maximum:
            raise ValueError("初始蓄力点不能超过蓄力上限")
        if current > maximum:
            raise ValueError("当前蓄力点不能超过蓄力上限")

    @classmethod
    def parse(cls, notation: str, *, resource_key: str = "蓄力") -> "ChargeState":
        """把 ``3/4`` 解析为初始3点、上限4点。"""

        if not isinstance(notation, str):
            raise TypeError("蓄力记法必须是类似 3/4 的字符串")
        matched = _CHARGE_NOTATION.fullmatch(notation)
        if matched is None:
            raise ValueError("蓄力记法必须是“初始点数/上限”格式，例如 3/4")
        initial, maximum = (int(item) for item in matched.groups())
        if initial > maximum:
            raise ValueError("初始蓄力点不能超过蓄力上限")
        return cls(
            resource_key=resource_key,
            initial=initial,
            maximum=maximum,
            current=initial,
        )

    def gain(self, amount: int) -> "ChargeState":
        gained = ensure_int_at_least(amount, "获得蓄力点", 0)
        return replace(self, current=min(self.maximum, self.current + gained))

    def spend(self, amount: int) -> "ChargeState":
        spent = ensure_int_at_least(amount, "消耗蓄力点", 0)
        if spent > self.current:
            raise ValueError(
                f"消耗蓄力点不能超过当前点数 {self.current}，请求消耗 {spent}"
            )
        return replace(self, current=self.current - spent)


@dataclass(frozen=True)
class DamageAfterSkillResult:
    """普通“受到伤害后”技能与濒死救援的顺序结果。"""

    hp_after_damage: int
    final_hp: int
    entered_dying: bool
    rescued: bool
    died: bool
    after_damage_skill_resolved: bool
    event_log: tuple[str, ...]


def resolve_damage_then_after_damage_skill(
    current_hp: int,
    damage_amount: int,
    *,
    rescue_amounts: Iterable[int] = (),
    on_after_damage: Callable[[int], object] | None = None,
) -> DamageAfterSkillResult:
    """先处理濒死救援，再决定是否结算普通受到伤害后技能。

    本函数刻意不表示“进入濒死时”类技能；那类技能应由完整濒死流程另行
    插入。若救援失败并正式死亡，普通卖血技能不会被调用。
    """

    hp = ensure_int_at_least(current_hp, "受伤前体力", 1)
    damage = ensure_int_at_least(damage_amount, "伤害点数", 1)
    if rescue_amounts is None:
        raise TypeError("救援回复量不能是 None")
    try:
        rescues = tuple(
            ensure_int_at_least(amount, "单次救援回复量", 1)
            for amount in rescue_amounts
        )
    except TypeError as exc:
        raise TypeError("救援回复量必须是正整数组成的可迭代对象") from exc
    if on_after_damage is not None and not callable(on_after_damage):
        raise TypeError("受到伤害后技能处理器必须是可调用对象或 None")

    hp_after_damage = hp - damage
    final_hp = hp_after_damage
    events: list[str] = ["受到伤害"]
    entered_dying = final_hp <= 0
    rescued = False
    if entered_dying:
        events.append("进入濒死")
        for amount in rescues:
            if final_hp >= 1:
                break
            final_hp += amount
            events.append(f"救援回复{amount}点体力")
        rescued = final_hp >= 1
        if rescued:
            events.append("脱离濒死")
        else:
            events.append("确认死亡")

    died = entered_dying and not rescued
    resolved = not died
    if resolved:
        if on_after_damage is not None:
            on_after_damage(final_hp)
        events.append("结算普通受到伤害后技能")
    return DamageAfterSkillResult(
        hp_after_damage=hp_after_damage,
        final_hp=final_hp,
        entered_dying=entered_dying,
        rescued=rescued,
        died=died,
        after_damage_skill_resolved=resolved,
        event_log=tuple(events),
    )


def zones_for_card_term(term: CardTerm | str) -> frozenset[CardZone]:
    """按用户确认口径返回“手牌”“牌”“区域内的牌”的区域范围。"""

    resolved = _coerce_enum(term, CardTerm, "牌区域术语")
    if resolved is CardTerm.HAND_CARD:
        return frozenset({CardZone.HAND})
    if resolved is CardTerm.CARD:
        return frozenset({CardZone.HAND, CardZone.EQUIPMENT})
    return frozenset({CardZone.HAND, CardZone.EQUIPMENT, CardZone.JUDGMENT})


@dataclass(frozen=True)
class CardUseResolution:
    """合法使用牌后，即使效果无效也保留使用事件及计数。"""

    card_name: str
    use_sequence: int
    turn_use_count: int
    use_event_recorded: bool
    effect_invalidated: bool
    effect_completed: bool
    after_resolution_event_recorded: bool


def record_card_use(
    card_name: str,
    *,
    prior_turn_use_count: int = 0,
    effect_invalidated: bool = False,
) -> CardUseResolution:
    """记录一次已经合法发生的使用牌事件。"""

    name = _nonempty_text(card_name, "卡牌名称")
    prior = ensure_int_at_least(prior_turn_use_count, "本回合此前使用牌数", 0)
    invalidated = _coerce_bool(effect_invalidated, "牌效果是否无效")
    sequence = prior + 1
    return CardUseResolution(
        card_name=name,
        use_sequence=sequence,
        turn_use_count=sequence,
        use_event_recorded=True,
        effect_invalidated=invalidated,
        effect_completed=not invalidated,
        after_resolution_event_recorded=not invalidated,
    )


@dataclass(frozen=True)
class EquipmentEffectFrequency:
    """装备效果的明确次数限制；``None`` 表示规则文字未限制。"""

    explicit_limit: int | None = None
    limit_scope: str | None = None

    def __post_init__(self) -> None:
        if self.explicit_limit is None:
            if self.limit_scope is not None:
                raise ValueError("未设置装备效果次数上限时不能单独设置限制范围")
            return
        ensure_int_at_least(self.explicit_limit, "装备效果明确次数上限", 1)
        object.__setattr__(self, "limit_scope", _nonempty_text(self.limit_scope, "装备效果限制范围"))

    def can_trigger(self, already_triggered: int) -> bool:
        triggered = ensure_int_at_least(already_triggered, "当前范围内已触发次数", 0)
        return self.explicit_limit is None or triggered < self.explicit_limit
