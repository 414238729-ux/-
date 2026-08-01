"""三国杀卡牌术语与结算规则的轻量模型。

本模块只实现 Knowledge 中由用户明确确认、且适合独立测试的规则。
它不负责目标合法性、技能时机穷举或完整对局状态，因此不是游戏引擎。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Callable, Iterable, Mapping, Sequence

from ._validation import ensure_int_at_least
from .sgs_modes import (
    TwoVsTwoDistanceState,
    get_actual_distance,
    is_in_attack_range,
)


class CardZone(Enum):
    """本项目当前使用的三个牌区。"""

    HAND = "手牌区"
    EQUIPMENT = "装备区"
    JUDGMENT = "判定区"


class CardSelectionWording(Enum):
    """需要严格区分的两种规则措辞。"""

    CARD = "牌"
    CARDS_IN_ZONES = "区域内的牌"


class TrickTimingCode(Enum):
    """结构化锦囊字段采用的基础时机代码。"""

    PLAY_PHASE = "trick_play_phase"
    RESPONSE_WINDOW = "trick_response_window"


class TrickUseLimitCode(Enum):
    """结构化锦囊字段采用的基础次数代码。"""

    UNLIMITED = "unlimited"


def _coerce_enum(value: object, enum_type: type[Enum], name: str) -> Enum:
    if isinstance(value, enum_type):
        return value
    try:
        return enum_type(value)
    except (TypeError, ValueError) as exc:
        allowed = "、".join(str(member.value) for member in enum_type)
        raise ValueError(f"{name}只能为：{allowed}") from exc


def selectable_card_zones(
    wording: CardSelectionWording | str,
) -> frozenset[CardZone]:
    """返回通用措辞允许选择的牌区。

    单独写“牌”时只包括手牌区和装备区；写“区域内的牌”时才包括
    判定区。具体卡牌或技能另有明确限制时，应由调用者优先应用该限制。
    """

    resolved = _coerce_enum(wording, CardSelectionWording, "规则措辞")
    if resolved is CardSelectionWording.CARD:
        return frozenset({CardZone.HAND, CardZone.EQUIPMENT})
    return frozenset(CardZone)


def can_pay_stone_axe_cost(
    selected_zones: Sequence[CardZone | str],
) -> bool:
    """判断两张牌能否支付【贯石斧】的“弃置两张牌”成本。"""

    if selected_zones is None:
        raise TypeError("贯石斧成本所选牌区不能是 None")
    try:
        prepared = tuple(
            _coerce_enum(zone, CardZone, "牌区") for zone in selected_zones
        )
    except TypeError as exc:
        raise TypeError("贯石斧成本所选牌区必须是可迭代序列") from exc
    if len(prepared) != 2:
        return False
    legal = selectable_card_zones(CardSelectionWording.CARD)
    return all(zone in legal for zone in prepared)


def can_target_distance_one_trick(
    source_player: int,
    target_player: int,
    state: TwoVsTwoDistanceState,
) -> bool:
    """统一判断文本写明“实际距离为 1”的锦囊目标。"""

    if source_player == target_player:
        return False
    return get_actual_distance(source_player, target_player, state) == 1


def can_target_snatch(
    source_player: int,
    target_player: int,
    state: TwoVsTwoDistanceState,
) -> bool:
    """判断【顺手牵羊】目标；只检查实际距离，不检查攻击范围。"""

    return can_target_distance_one_trick(source_player, target_player, state)


def can_target_supply_shortage(
    source_player: int,
    target_player: int,
    state: TwoVsTwoDistanceState,
) -> bool:
    """判断【兵粮寸断】目标；与【顺手牵羊】复用同一距离逻辑。"""

    return can_target_distance_one_trick(source_player, target_player, state)


def can_target_attack_range_effect(
    source_player: int,
    target_player: int,
    state: TwoVsTwoDistanceState,
) -> bool:
    """判断明确写“攻击范围内”的效果，不代替“距离为 1”判断。"""

    if source_player == target_player:
        return False
    return is_in_attack_range(source_player, target_player, state)


def can_target_with_slash(
    source_player: int,
    target_player: int,
    state: TwoVsTwoDistanceState,
) -> bool:
    """按当前轻量模型判断通常【杀】的攻击范围目标。"""

    return can_target_attack_range_effect(source_player, target_player, state)


def _ensure_bool(value: object, name: str) -> bool:
    if not isinstance(value, bool):
        raise TypeError(f"{name}必须是布尔值")
    return value


def _parse_structured_bool(value: object, name: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "是"}:
            return True
        if normalized in {"false", "否"}:
            return False
    raise ValueError(f"{name}必须明确填写 true/false 或 是/否")


@dataclass(frozen=True)
class TrickUsageRule:
    """由卡牌特例和锦囊通用字段合并得到的有效使用规则。"""

    specific_timing: str | None
    inherited_generic_timing: str | None
    effective_timing: str
    base_use_limit: str
    inherits_generic_use_limit: bool
    response_only: bool
    skill_override_allowed: bool
    skill_override_applied: bool


def resolve_structured_trick_usage(
    row: Mapping[str, object],
    *,
    skill_override_timing: str | None = None,
) -> TrickUsageRule:
    """按“具体特例优先，否则继承通用规则”解析一条锦囊记录。

    空的 ``specific_timing`` 仅表示没有独立时机特例；若同时没有明确的
    ``inherits_generic_timing``，会直接报错，绝不解释成任意时机。
    """

    if not isinstance(row, Mapping):
        raise TypeError("结构化卡牌记录必须是字段映射")
    if str(row.get("category", "")).strip() != "锦囊牌":
        raise ValueError("只有锦囊牌记录才能继承锦囊通用使用规则")

    specific = str(row.get("specific_timing", "")).strip() or None
    inherited_raw = str(row.get("inherits_generic_timing", "")).strip()
    inherited = None if inherited_raw.lower() == "false" else inherited_raw or None
    if specific is not None:
        effective = specific
    elif inherited is not None:
        effective = inherited
    else:
        raise ValueError("具体时机为空时必须明确填写继承的锦囊通用时机")

    base_limit = str(row.get("base_use_limit", "")).strip()
    if not base_limit:
        raise ValueError("锦囊牌必须明确填写基础使用次数规则")
    inherits_limit = _parse_structured_bool(
        row.get("inherits_generic_use_limit", ""),
        "锦囊通用次数继承字段",
    )
    response_only = _parse_structured_bool(
        row.get("response_only", ""),
        "仅响应使用字段",
    )
    override_allowed = _parse_structured_bool(
        row.get("skill_override_allowed", ""),
        "技能覆盖允许字段",
    )

    override_applied = skill_override_timing is not None
    if override_applied:
        if not override_allowed:
            raise ValueError("该锦囊记录不允许技能覆盖基础使用时机")
        if not isinstance(skill_override_timing, str) or not skill_override_timing.strip():
            raise ValueError("技能覆盖时机必须是非空字符串")
        effective = skill_override_timing.strip()

    return TrickUsageRule(
        specific_timing=specific,
        inherited_generic_timing=inherited,
        effective_timing=effective,
        base_use_limit=base_limit,
        inherits_generic_use_limit=inherits_limit,
        response_only=response_only,
        skill_override_allowed=override_allowed,
        skill_override_applied=override_applied,
    )


def can_use_trick_at_timing(
    rule: TrickUsageRule,
    current_timing: TrickTimingCode | str,
    *,
    has_legal_target: bool,
    has_card_or_conversion: bool,
    response_window_open: bool = False,
    prior_uses_in_play_phase: int = 0,
) -> bool:
    """检查轻量锦囊时机；无限制不等于忽略目标、牌源或响应窗口。"""

    if not isinstance(rule, TrickUsageRule):
        raise TypeError("锦囊使用规则必须是 TrickUsageRule")
    timing = (
        current_timing.value
        if isinstance(current_timing, TrickTimingCode)
        else current_timing
    )
    if not isinstance(timing, str) or not timing.strip():
        raise ValueError("当前使用时机必须是非空字符串")
    _ensure_bool(has_legal_target, "合法目标标识")
    _ensure_bool(has_card_or_conversion, "合法牌或转化标识")
    _ensure_bool(response_window_open, "锦囊响应窗口标识")
    ensure_int_at_least(prior_uses_in_play_phase, "本出牌阶段此前锦囊使用数", 0)

    if not has_legal_target or not has_card_or_conversion:
        return False
    if timing != rule.effective_timing:
        return False
    if rule.response_only and not response_window_open:
        return False
    if rule.base_use_limit == TrickUseLimitCode.UNLIMITED.value:
        return True
    raise ValueError(f"当前轻量模型不认识基础次数规则：{rule.base_use_limit}")


class CardUseContext(Enum):
    """【桃】【酒】与装备牌当前确认的使用上下文代码。"""

    OWN_PLAY_PHASE_SELF_HEAL = "own_play_phase_self_heal"
    DYING_SELF_RESCUE = "dying_self_rescue"
    RESCUE_OTHER_DYING_CHARACTER = "rescue_other_dying_character"
    PLAY_PHASE_SLASH_BUFF = "play_phase_slash_buff"
    EQUIP = "equip"


class CardUseEvent(Enum):
    """区分“已经使用”和“效果已经结算”的最小事件集合。"""

    CARD_USE_DECLARED = "card_use_declared"
    CARD_USE_COST_PAID = "card_use_cost_paid"
    CARD_USED = "card_used"
    BEFORE_CARD_EFFECT_RESOLUTION = "before_card_effect_resolution"
    CARD_EFFECT_INVALIDATED = "card_effect_invalidated"
    CARD_EFFECT_RESOLVED = "card_effect_resolved"
    AFTER_CARD_EFFECT_RESOLVED = "after_card_effect_resolved"


_NONRESPONSIVE_CARD_NAMES = frozenset({"桃", "酒"})


def _is_supported_nonresponsive_card(card_name: str, category: str) -> bool:
    return card_name in _NONRESPONSIVE_CARD_NAMES or category == "装备牌"


def can_ordinary_card_respond_to_use(card_name: str, category: str) -> bool:
    """【桃】【酒】和装备牌的使用本身不建立普通卡牌响应窗口。"""

    if not isinstance(card_name, str) or not card_name.strip():
        raise ValueError("卡牌名称必须是非空字符串")
    if not isinstance(category, str) or not category.strip():
        raise ValueError("卡牌类别必须是非空字符串")
    if not _is_supported_nonresponsive_card(card_name.strip(), category.strip()):
        raise ValueError("当前轻量接口只判断【桃】【酒】和装备牌的普通响应")
    return False


def can_nullification_respond_to_card_use(card_name: str, category: str) -> bool:
    """明确阻止把【无懈可击】当作桃、酒或装备牌的响应牌。"""

    return can_ordinary_card_respond_to_use(card_name, category)


@dataclass(frozen=True)
class CardUseResolution:
    card_name: str
    category: str
    use_context: CardUseContext
    events: tuple[CardUseEvent, ...]
    ordinary_response_window_open: bool
    invalidated_by_skill: bool
    counts_as_used: bool
    effect_resolved: bool
    after_resolution_triggered: bool

    @property
    def event_codes(self) -> tuple[str, ...]:
        return tuple(event.value for event in self.events)

    @property
    def use_trigger_available(self) -> bool:
        return CardUseEvent.CARD_USED in self.events

    @property
    def after_resolution_trigger_available(self) -> bool:
        return CardUseEvent.AFTER_CARD_EFFECT_RESOLVED in self.events


def resolve_nonresponsive_card_use(
    card_name: str,
    category: str,
    use_context: CardUseContext | str,
    *,
    has_card_or_conversion: bool = True,
    ordinary_card_response_attempted: bool = False,
    invalidated_by_skill: bool = False,
    skill_explicitly_can_invalidate: bool = False,
) -> CardUseResolution:
    """结算桃、酒或装备牌的使用声明与可能的技能无效化。

    普通卡牌响应和技能无效化是两条独立路径。技能无效化发生时，实体牌
    或转化成本已经支付、次数额度已经消耗且 ``card_used`` 已产生，但
    不产生效果结算成功及结算后事件。
    """

    if not isinstance(card_name, str) or not card_name.strip():
        raise ValueError("卡牌名称必须是非空字符串")
    if not isinstance(category, str) or not category.strip():
        raise ValueError("卡牌类别必须是非空字符串")
    name = card_name.strip()
    resolved_category = category.strip()
    if not _is_supported_nonresponsive_card(name, resolved_category):
        raise ValueError("当前轻量接口只处理【桃】【酒】和装备牌")
    context = _coerce_enum(use_context, CardUseContext, "卡牌使用上下文")
    assert isinstance(context, CardUseContext)
    for value, label in (
        (has_card_or_conversion, "实体牌或合法转化标识"),
        (ordinary_card_response_attempted, "普通卡牌响应尝试标识"),
        (invalidated_by_skill, "技能无效化标识"),
        (skill_explicitly_can_invalidate, "技能明确允许无效化标识"),
    ):
        _ensure_bool(value, label)
    if not has_card_or_conversion:
        raise ValueError("没有实体牌或合法技能转化时不能使用该牌")
    if ordinary_card_response_attempted:
        raise ValueError("【桃】【酒】和装备牌的使用本身不产生普通卡牌响应窗口")
    if invalidated_by_skill and not skill_explicitly_can_invalidate:
        raise ValueError("只有明确允许的技能或特殊效果才能令该牌效果无效")

    events = [
        CardUseEvent.CARD_USE_DECLARED,
        CardUseEvent.CARD_USE_COST_PAID,
        CardUseEvent.CARD_USED,
        CardUseEvent.BEFORE_CARD_EFFECT_RESOLUTION,
    ]
    if invalidated_by_skill:
        events.append(CardUseEvent.CARD_EFFECT_INVALIDATED)
    else:
        events.extend(
            (
                CardUseEvent.CARD_EFFECT_RESOLVED,
                CardUseEvent.AFTER_CARD_EFFECT_RESOLVED,
            )
        )
    return CardUseResolution(
        card_name=name,
        category=resolved_category,
        use_context=context,
        events=tuple(events),
        ordinary_response_window_open=False,
        invalidated_by_skill=invalidated_by_skill,
        counts_as_used=True,
        effect_resolved=not invalidated_by_skill,
        after_resolution_triggered=not invalidated_by_skill,
    )


@dataclass(frozen=True)
class DyingRecoveryUseResult:
    user_player_id: int
    target_player_id: int
    hp_before: int
    hp_after: int
    recovery_amount: int
    remains_dying: bool
    rescue_ended: bool
    use_resolution: CardUseResolution


@dataclass(frozen=True)
class PeachPlayPhaseUseResult:
    user_player_id: int
    target_player_id: int
    hp_before: int
    hp_after: int
    maximum_hp: int
    recovery_amount: int
    reached_maximum_hp: bool
    use_resolution: CardUseResolution


def use_peach_for_self_heal(
    *,
    user_player_id: int,
    target_player_id: int,
    current_hp: int,
    maximum_hp: int,
    in_own_play_phase: bool = True,
    has_card_or_conversion: bool = True,
    invalidated_by_skill: bool = False,
    skill_explicitly_can_invalidate: bool = False,
) -> PeachPlayPhaseUseResult:
    """在自己的出牌阶段对受伤的自己使用一张【桃】。

    每次调用代表一次实体牌或合法转化的使用；函数不维护跨上下文的
    统一次数计数器。只要仍受伤并有合法资源，调用者可以继续使用。
    """

    user = ensure_int_at_least(user_player_id, "使用者玩家标识", 1)
    target = ensure_int_at_least(target_player_id, "桃的目标玩家标识", 1)
    if isinstance(current_hp, bool) or not isinstance(current_hp, int):
        raise TypeError("当前体力必须是整数")
    maximum = ensure_int_at_least(maximum_hp, "体力上限", 1)
    _ensure_bool(in_own_play_phase, "是否处于自己的出牌阶段")
    if not in_own_play_phase:
        raise ValueError("普通自我回复用途的【桃】只能在自己的出牌阶段使用")
    if user != target:
        raise ValueError("自己的出牌阶段只能对自己使用【桃】进行普通回复")
    if current_hp <= 0:
        raise ValueError("角色正处于濒死状态，应使用濒死救援上下文")
    if current_hp > maximum:
        raise ValueError("当前体力不能高于体力上限")
    if current_hp == maximum:
        raise ValueError("角色未受伤，不能以普通回复用途使用【桃】")

    resolution = resolve_nonresponsive_card_use(
        "桃",
        "基本牌",
        CardUseContext.OWN_PLAY_PHASE_SELF_HEAL,
        has_card_or_conversion=has_card_or_conversion,
        invalidated_by_skill=invalidated_by_skill,
        skill_explicitly_can_invalidate=skill_explicitly_can_invalidate,
    )
    recovery = 1 if resolution.effect_resolved else 0
    hp_after = min(maximum, current_hp + recovery)
    return PeachPlayPhaseUseResult(
        user_player_id=user,
        target_player_id=target,
        hp_before=current_hp,
        hp_after=hp_after,
        maximum_hp=maximum,
        recovery_amount=recovery,
        reached_maximum_hp=hp_after == maximum,
        use_resolution=resolution,
    )


def use_dying_recovery_card(
    card_name: str,
    *,
    user_player_id: int,
    target_player_id: int,
    current_hp: int,
    legal_rescue_window: bool = True,
    has_card_or_conversion: bool = True,
    invalidated_by_skill: bool = False,
    skill_explicitly_can_invalidate: bool = False,
) -> DyingRecoveryUseResult:
    """在仍处于濒死时使用一张桃或自救酒；每次调用代表一个实体使用。"""

    if card_name not in {"桃", "酒"}:
        raise ValueError("濒死恢复牌只能是【桃】或【酒】")
    user = ensure_int_at_least(user_player_id, "使用者玩家标识", 1)
    target = ensure_int_at_least(target_player_id, "濒死目标玩家标识", 1)
    if isinstance(current_hp, bool) or not isinstance(current_hp, int):
        raise TypeError("当前体力必须是整数")
    _ensure_bool(legal_rescue_window, "合法濒死救援时机标识")
    if not legal_rescue_window:
        raise ValueError("当前不在该角色的合法濒死救援时机")
    if current_hp >= 1:
        raise ValueError("目标已脱离濒死，不能继续为本轮濒死使用恢复牌")
    if card_name == "酒" and user != target:
        raise ValueError("【酒】的濒死自救用途只能对自己使用")
    context = (
        CardUseContext.DYING_SELF_RESCUE
        if user == target
        else CardUseContext.RESCUE_OTHER_DYING_CHARACTER
    )
    resolution = resolve_nonresponsive_card_use(
        card_name,
        "基本牌",
        context,
        has_card_or_conversion=has_card_or_conversion,
        invalidated_by_skill=invalidated_by_skill,
        skill_explicitly_can_invalidate=skill_explicitly_can_invalidate,
    )
    recovery = 1 if resolution.effect_resolved else 0
    hp_after = current_hp + recovery
    remains_dying = hp_after < 1
    return DyingRecoveryUseResult(
        user_player_id=user,
        target_player_id=target,
        hp_before=current_hp,
        hp_after=hp_after,
        recovery_amount=recovery,
        remains_dying=remains_dying,
        rescue_ended=not remains_dying,
        use_resolution=resolution,
    )


@dataclass(frozen=True)
class WinePlayPhaseState:
    play_phase_id: int
    slash_buff_use_consumed: bool = False
    slash_damage_bonus: int = 0

    def __post_init__(self) -> None:
        ensure_int_at_least(self.play_phase_id, "独立出牌阶段标识", 1)
        _ensure_bool(self.slash_buff_use_consumed, "酒强化杀额度消耗标识")
        ensure_int_at_least(self.slash_damage_bonus, "下一张杀伤害加成", 0)


@dataclass(frozen=True)
class WinePlayPhaseUseResult:
    state_after: WinePlayPhaseState
    use_resolution: CardUseResolution


def use_wine_for_slash_buff(
    state: WinePlayPhaseState,
    *,
    in_own_play_phase: bool = True,
    has_card_or_conversion: bool = True,
    invalidated_by_skill: bool = False,
    skill_explicitly_can_invalidate: bool = False,
) -> WinePlayPhaseUseResult:
    """使用出牌阶段强化杀的酒；每个独立出牌阶段额度为一次。"""

    if not isinstance(state, WinePlayPhaseState):
        raise TypeError("酒的出牌阶段状态必须是 WinePlayPhaseState")
    _ensure_bool(in_own_play_phase, "是否处于自己的出牌阶段")
    if not in_own_play_phase:
        raise ValueError("强化下一张杀的【酒】只能在自己的出牌阶段使用")
    if state.slash_buff_use_consumed:
        raise ValueError("本出牌阶段强化杀的【酒】额度已经使用")
    resolution = resolve_nonresponsive_card_use(
        "酒",
        "基本牌",
        CardUseContext.PLAY_PHASE_SLASH_BUFF,
        has_card_or_conversion=has_card_or_conversion,
        invalidated_by_skill=invalidated_by_skill,
        skill_explicitly_can_invalidate=skill_explicitly_can_invalidate,
    )
    return WinePlayPhaseUseResult(
        state_after=WinePlayPhaseState(
            play_phase_id=state.play_phase_id,
            slash_buff_use_consumed=True,
            slash_damage_bonus=1 if resolution.effect_resolved else 0,
        ),
        use_resolution=resolution,
    )


@dataclass(frozen=True)
class EquipmentState:
    slots: Mapping[str, str]

    def __post_init__(self) -> None:
        if not isinstance(self.slots, Mapping):
            raise TypeError("装备栏状态必须是字段映射")
        prepared: dict[str, str] = {}
        for slot, card in self.slots.items():
            if not isinstance(slot, str) or not slot.strip():
                raise ValueError("装备栏名称必须是非空字符串")
            if not isinstance(card, str) or not card.strip():
                raise ValueError("装备牌名称必须是非空字符串")
            prepared[slot.strip()] = card.strip()
        object.__setattr__(self, "slots", MappingProxyType(prepared))


class EquipmentSlot(Enum):
    """当前轻量模型使用的互斥装备栏。"""

    WEAPON = "weapon"
    ARMOR = "armor"
    ATTACK_HORSE = "attack_horse"
    DEFENSE_HORSE = "defense_horse"
    TREASURE = "treasure"


@dataclass(frozen=True)
class NamedMountDefinition:
    card_name: str
    equipment_slot: EquipmentSlot
    distance_modifier: int


NAMED_MOUNT_RULES: Mapping[str, NamedMountDefinition] = MappingProxyType(
    {
        name: NamedMountDefinition(name, EquipmentSlot.ATTACK_HORSE, -1)
        for name in ("紫骍", "赤兔", "大宛")
    }
    | {
        name: NamedMountDefinition(name, EquipmentSlot.DEFENSE_HORSE, 1)
        for name in ("骅骝", "的卢", "爪黄飞电", "绝影")
    }
)


@dataclass(frozen=True)
class EquipmentUseResult:
    state_after: EquipmentState
    replaced_card: str | None
    entered_equipment_zone: bool
    equipment_success_triggered: bool
    use_resolution: CardUseResolution


def use_equipment_card(
    state: EquipmentState,
    card_name: str,
    equipment_slot: str,
    *,
    in_own_play_phase: bool = True,
    skill_timing_override: bool = False,
    has_card_or_conversion: bool = True,
    invalidated_by_skill: bool = False,
    skill_explicitly_can_invalidate: bool = False,
) -> EquipmentUseResult:
    """使用一张装备牌；无基础次数上限，但仍检查时机和装备栏替换。"""

    if not isinstance(state, EquipmentState):
        raise TypeError("装备栏状态必须是 EquipmentState")
    if not isinstance(card_name, str) or not card_name.strip():
        raise ValueError("装备牌名称必须是非空字符串")
    if not isinstance(equipment_slot, str) or not equipment_slot.strip():
        raise ValueError("装备栏名称必须是非空字符串")
    _ensure_bool(in_own_play_phase, "是否处于自己的出牌阶段")
    _ensure_bool(skill_timing_override, "技能时机覆盖标识")
    if not in_own_play_phase and not skill_timing_override:
        raise ValueError("装备牌通常只能在自己的出牌阶段主动使用")
    resolution = resolve_nonresponsive_card_use(
        card_name.strip(),
        "装备牌",
        CardUseContext.EQUIP,
        has_card_or_conversion=has_card_or_conversion,
        invalidated_by_skill=invalidated_by_skill,
        skill_explicitly_can_invalidate=skill_explicitly_can_invalidate,
    )
    slot = equipment_slot.strip()
    replaced = state.slots.get(slot)
    if not resolution.effect_resolved:
        return EquipmentUseResult(
            state_after=state,
            replaced_card=None,
            entered_equipment_zone=False,
            equipment_success_triggered=False,
            use_resolution=resolution,
        )
    slots = dict(state.slots)
    slots[slot] = card_name.strip()
    return EquipmentUseResult(
        state_after=EquipmentState(slots),
        replaced_card=replaced,
        entered_equipment_zone=True,
        equipment_success_triggered=True,
        use_resolution=resolution,
    )


def use_named_mount(
    state: EquipmentState,
    card_name: str,
    **kwargs: object,
) -> EquipmentUseResult:
    """按具名坐骑映射进入攻击或防御坐骑栏。"""

    if not isinstance(card_name, str) or not card_name.strip():
        raise ValueError("具名坐骑名称必须是非空字符串")
    try:
        definition = NAMED_MOUNT_RULES[card_name.strip()]
    except KeyError as exc:
        raise ValueError(f"没有具名坐骑映射：{card_name}") from exc
    return use_equipment_card(
        state,
        definition.card_name,
        definition.equipment_slot.value,
        **kwargs,
    )


@dataclass(frozen=True)
class EquipmentEffectRule:
    """装备效果的明确次数限制与独立模拟保护上限。"""

    explicit_limit: int | None = None
    simulation_hard_limit: int = 100

    def __post_init__(self) -> None:
        if self.explicit_limit is not None:
            ensure_int_at_least(self.explicit_limit, "装备效果明确次数限制", 1)
        ensure_int_at_least(self.simulation_hard_limit, "装备效果模拟硬上限", 1)


@dataclass(frozen=True)
class EquipmentEffectCheck:
    can_trigger: bool
    stopped_by_rule_limit: bool
    truncated_by_simulation_limit: bool
    reason: str


def check_equipment_effect_trigger(
    rule: EquipmentEffectRule,
    *,
    prior_activations: int,
    condition_met: bool,
    cost_paid: bool = True,
) -> EquipmentEffectCheck:
    """未写规则次数限制时，每次满足条件均可发动，硬上限只防死循环。"""

    if not isinstance(rule, EquipmentEffectRule):
        raise TypeError("装备效果规则必须是 EquipmentEffectRule")
    ensure_int_at_least(prior_activations, "此前发动次数", 0)
    _ensure_bool(condition_met, "触发条件满足标识")
    _ensure_bool(cost_paid, "发动代价支付标识")
    if not condition_met or not cost_paid:
        return EquipmentEffectCheck(False, False, False, "触发条件或支付条件不满足")
    if rule.explicit_limit is not None and prior_activations >= rule.explicit_limit:
        return EquipmentEffectCheck(False, True, False, "已达到规则文字明确的次数限制")
    if prior_activations >= rule.simulation_hard_limit:
        return EquipmentEffectCheck(
            False,
            False,
            True,
            "达到程序循环保护上限；这不是游戏规则次数限制",
        )
    return EquipmentEffectCheck(
        True,
        False,
        False,
        "当前事件满足条件；规则未另写限制时可以发动或生效",
    )


@dataclass(frozen=True)
class StructuredCardUseRule:
    card_name: str
    use_context: str
    default_timing: str
    base_use_limit: str
    response_window: str
    can_be_responded_by_card: bool
    can_be_invalidated_by_skill: bool
    counts_as_used_if_invalidated: bool
    effect_resolved_if_invalidated: bool
    after_resolution_trigger_if_invalidated: bool
    inherits_generic_rule: bool
    target_scope: str | None
    requires_wounded: bool | None
    requires_target_dying: bool | None


def resolve_structured_card_usage(
    row: Mapping[str, object],
    *,
    use_context: CardUseContext | str | None = None,
    use_mode_row: Mapping[str, object] | None = None,
) -> StructuredCardUseRule:
    """解析桃、酒或装备牌的明确结构字段，不把空值解释成任意规则。

    多用途牌优先读取独立的 ``use_mode_row``。为兼容旧资料，未传入
    独立用途记录时仍可读取卡牌定义行中的 ``use_modes`` JSON。
    """

    if not isinstance(row, Mapping):
        raise TypeError("结构化卡牌记录必须是字段映射")
    name = str(row.get("card_name", "")).strip()
    category = str(row.get("category", "")).strip()
    if not _is_supported_nonresponsive_card(name, category):
        raise ValueError("当前结构化解析器只处理【桃】【酒】和装备牌")

    top_context = str(row.get("use_context", "")).strip()
    timing = str(row.get("default_timing", "")).strip()
    limit = str(row.get("base_use_limit", "")).strip()
    target_scope: str | None = None
    requires_wounded: bool | None = None
    requires_target_dying: bool | None = None
    selected_context = (
        use_context.value if isinstance(use_context, CardUseContext) else use_context
    )
    if selected_context is not None:
        if not isinstance(selected_context, str) or not selected_context.strip():
            raise ValueError("使用上下文必须是非空字符串")
        selected_context = selected_context.strip()

    if use_mode_row is not None and not isinstance(use_mode_row, Mapping):
        raise TypeError("独立卡牌用途记录必须是字段映射")

    if top_context == "multiple_modes":
        if selected_context is None:
            raise ValueError("多用途卡牌必须明确指定要解析的使用上下文")
        if use_mode_row is not None:
            card_key = str(use_mode_row.get("card_key", "")).strip()
            definition_key = str(row.get("card_id", row.get("card_key", ""))).strip()
            if card_key and definition_key and card_key != definition_key:
                raise ValueError("独立用途记录与卡牌定义的 card_key 不一致")
            mode_context = str(use_mode_row.get("use_mode", "")).strip()
            if mode_context != selected_context:
                raise ValueError("独立用途记录与指定的使用上下文不一致")
            timing = str(use_mode_row.get("timing", "")).strip()
            raw_limit = str(use_mode_row.get("limit_count", "")).strip()
            limit_scope = str(use_mode_row.get("limit_scope", "")).strip()
            if raw_limit == "unlimited":
                limit = "unlimited"
            elif raw_limit == "1" and limit_scope == "play_phase":
                limit = "once_per_play_phase"
            else:
                raise ValueError("独立用途记录包含当前解析器不认识的次数规则")
            target_scope = str(use_mode_row.get("target_scope", "")).strip() or None
            condition = str(use_mode_row.get("condition", "")).strip()
            requires_wounded = condition == "wounded"
            requires_target_dying = condition in {"dying", "target_dying"}
        else:
            raw_modes = str(row.get("use_modes", "")).strip()
            if not raw_modes:
                raise ValueError("多用途卡牌必须提供独立用途记录或旧版 use_modes 结构")
            try:
                modes = json.loads(raw_modes)
            except json.JSONDecodeError as exc:
                raise ValueError("use_modes 必须是合法 JSON 对象") from exc
            if not isinstance(modes, dict) or selected_context not in modes:
                raise ValueError(f"结构化记录没有使用上下文：{selected_context}")
            mode = modes[selected_context]
            if not isinstance(mode, dict):
                raise ValueError("use_modes 中的每个上下文必须是字段对象")
            timing = str(mode.get("default_timing", "")).strip()
            limit = str(mode.get("base_use_limit", "")).strip()
            raw_target_scope = mode.get("target_scope")
            if raw_target_scope is not None:
                target_scope = str(raw_target_scope).strip()
            if "requires_wounded" in mode:
                requires_wounded = _parse_structured_bool(
                    mode["requires_wounded"], "受伤条件字段"
                )
            if "requires_target_dying" in mode:
                requires_target_dying = _parse_structured_bool(
                    mode["requires_target_dying"], "濒死条件字段"
                )
        effective_context = selected_context
    else:
        if selected_context is not None and selected_context != top_context:
            raise ValueError("指定的使用上下文与结构化记录不一致")
        effective_context = top_context

    unresolved = {"", "未提供", "unknown", "context_dependent"}
    if effective_context in unresolved:
        raise ValueError("结构化记录没有明确可解析的使用上下文")
    if timing in unresolved:
        raise ValueError("结构化记录没有明确使用时机，不能解释成任意时机")
    if limit in unresolved:
        raise ValueError("结构化记录没有明确次数限制，不能解释成无限制")
    if name == "桃":
        if not target_scope:
            raise ValueError("【桃】的每个使用上下文必须明确目标范围")
        if requires_wounded is None or requires_target_dying is None:
            raise ValueError("【桃】的每个使用上下文必须明确受伤与濒死条件")
    response_window = str(row.get("response_window", "")).strip()
    if response_window in {"", "未提供", "unknown"}:
        raise ValueError("结构化记录没有明确普通响应窗口")

    return StructuredCardUseRule(
        card_name=name,
        use_context=effective_context,
        default_timing=timing,
        base_use_limit=limit,
        response_window=response_window,
        can_be_responded_by_card=_parse_structured_bool(
            row.get("can_be_responded_by_card", ""),
            "普通卡牌响应字段",
        ),
        can_be_invalidated_by_skill=_parse_structured_bool(
            row.get("can_be_invalidated_by_skill", ""),
            "技能无效化字段",
        ),
        counts_as_used_if_invalidated=_parse_structured_bool(
            row.get("counts_as_used_if_invalidated", ""),
            "无效化后仍算使用字段",
        ),
        effect_resolved_if_invalidated=_parse_structured_bool(
            row.get("effect_resolved_if_invalidated", ""),
            "无效化后效果结算字段",
        ),
        after_resolution_trigger_if_invalidated=_parse_structured_bool(
            row.get("after_resolution_trigger_if_invalidated", ""),
            "无效化后结算后触发字段",
        ),
        inherits_generic_rule=_parse_structured_bool(
            row.get("inherits_generic_rule", ""),
            "通用规则继承字段",
        ),
        target_scope=target_scope,
        requires_wounded=requires_wounded,
        requires_target_dying=requires_target_dying,
    )


def can_nullify_trick_effect(
    *,
    is_trick: bool,
    effect_targets_character: bool,
    deals_damage: bool | None = None,
    is_harmful: bool | None = None,
) -> bool:
    """判断某个即将对角色产生的效果是否属于无懈适用范围。

    ``deals_damage`` 与 ``is_harmful`` 仅用于让调用者显式记录信息；
    它们不参与适用性判断，避免把无懈错误限定为伤害或负面锦囊。
    """

    _ensure_bool(is_trick, "是否为锦囊牌")
    _ensure_bool(effect_targets_character, "是否对角色产生效果")
    if deals_damage is not None:
        _ensure_bool(deals_damage, "是否造成伤害")
    if is_harmful is not None:
        _ensure_bool(is_harmful, "是否为负面效果")
    return is_trick and effect_targets_character


@dataclass(frozen=True)
class NullificationChainResult:
    """连续若干张【无懈可击】后的最终状态。"""

    response_count: int
    original_effect_cancelled: bool


def resolve_nullification_chain(
    response_count: int,
) -> NullificationChainResult:
    """按奇偶关系结算连续无懈，不设置人为响应张数上限。"""

    ensure_int_at_least(response_count, "无懈可击响应张数", 0)
    return NullificationChainResult(
        response_count=response_count,
        original_effect_cancelled=response_count % 2 == 1,
    )


@dataclass(frozen=True)
class TargetTrickResolution:
    """多目标锦囊对一名目标的独立无懈结算。"""

    target: str
    nullification_count: int
    effect_applies: bool


def resolve_multi_target_trick(
    targets: Sequence[str],
    nullification_counts: Mapping[str, int] | None = None,
) -> tuple[TargetTrickResolution, ...]:
    """逐名目标结算无懈；一名目标被抵消不影响其他目标。"""

    if targets is None:
        raise TypeError("锦囊目标不能是 None")
    try:
        prepared = tuple(targets)
    except TypeError as exc:
        raise TypeError("锦囊目标必须是可迭代序列") from exc
    if not prepared:
        raise ValueError("锦囊目标不能为空")
    if any(not isinstance(target, str) or not target.strip() for target in prepared):
        raise ValueError("锦囊目标必须是非空字符串")
    if len(set(prepared)) != len(prepared):
        raise ValueError("同一轮多目标结算中不能出现重复目标")
    counts = {} if nullification_counts is None else nullification_counts
    if not isinstance(counts, Mapping):
        raise TypeError("各目标无懈张数必须是映射")
    unknown = set(counts) - set(prepared)
    if unknown:
        raise ValueError("无懈记录包含不在本次锦囊中的目标：" + "、".join(sorted(unknown)))

    results: list[TargetTrickResolution] = []
    for target in prepared:
        chain = resolve_nullification_chain(counts.get(target, 0))
        results.append(
            TargetTrickResolution(
                target=target,
                nullification_count=chain.response_count,
                effect_applies=not chain.original_effect_cancelled,
            )
        )
    return tuple(results)


class DelayedTrickMoment(Enum):
    """与延时锦囊无懈时机有关的两个节点。"""

    ENTERED_JUDGMENT_ZONE = "刚被使用并进入判定区"
    BEFORE_JUDGMENT = "判定阶段即将判定并决定是否生效前"


def is_delayed_trick_nullification_window(
    moment: DelayedTrickMoment | str,
) -> bool:
    """只有判定阶段即将判定前才进入延时锦囊的无懈时机。"""

    resolved = _coerce_enum(moment, DelayedTrickMoment, "延时锦囊时机")
    return resolved is DelayedTrickMoment.BEFORE_JUDGMENT


class DelayedTrick(Enum):
    INDULGENCE = "乐不思蜀"
    SUPPLY_SHORTAGE = "兵粮寸断"
    LIGHTNING = "闪电"


class DelayedTrickDestination(Enum):
    DISCARD_PILE = "弃牌堆"
    NEXT_PLAYER_JUDGMENT_ZONE = "下家判定区"


_SUITS = frozenset({"红桃", "方块", "梅花", "黑桃"})


@dataclass(frozen=True)
class DelayedTrickResolution:
    """一张延时锦囊在判定阶段的轻量结算结果。"""

    card: DelayedTrick
    nullified: bool
    judgment_performed: bool
    judgment_suit: str | None
    judgment_rank: int | str | None
    effect_applied: bool
    skipped_phase: str | None
    damage_amount: int
    damage_type: str | None
    destination: DelayedTrickDestination
    next_seat: int | None
    movement_wording: str
    resolution_steps: tuple[str, ...]
    discard_action_performed: bool = False


def _next_seat(
    current_seat: int,
    player_count: int,
    living_seats: Iterable[int] | None = None,
) -> int:
    ensure_int_at_least(player_count, "玩家人数", 2)
    ensure_int_at_least(current_seat, "当前座次", 1)
    if current_seat > player_count:
        raise ValueError(
            f"当前座次不能超过玩家人数 {player_count}，当前为 {current_seat}"
        )
    if living_seats is None:
        return current_seat % player_count + 1

    try:
        prepared = tuple(living_seats)
    except TypeError as exc:
        raise TypeError("存活座位必须是可迭代对象") from exc
    for seat in prepared:
        ensure_int_at_least(seat, "存活座位", 1)
        if seat > player_count:
            raise ValueError(f"存活座位不能超过玩家人数 {player_count}")
    if len(prepared) != len(set(prepared)):
        raise ValueError("存活座位不能重复")
    living = frozenset(prepared)
    if current_seat not in living:
        raise ValueError("闪电当前结算座位必须属于存活座位")
    if len(living) < 2:
        raise ValueError("确定闪电下家时至少需要两名存活角色")
    for offset in range(1, player_count):
        candidate = (current_seat - 1 + offset) % player_count + 1
        if candidate in living:
            return candidate
    raise RuntimeError("未能从存活座位中确定闪电下家")


def _discarded_delayed_result(
    card: DelayedTrick,
    *,
    nullified: bool,
    judgment_performed: bool,
    judgment_suit: str | None,
    judgment_rank: int | str | None,
    effect_applied: bool,
    skipped_phase: str | None = None,
    damage_amount: int = 0,
    damage_type: str | None = None,
) -> DelayedTrickResolution:
    if nullified:
        steps = ("无懈可击抵消", "置入弃牌堆")
    elif damage_amount > 0:
        steps = (
            "进行判定",
            f"造成{damage_amount}点{damage_type}伤害",
            "完整结算伤害及其引发的技能、濒死和死亡",
            "置入弃牌堆",
        )
    elif skipped_phase is not None:
        steps = ("进行判定", f"跳过{skipped_phase}", "置入弃牌堆")
    else:
        steps = ("进行判定", "效果不生效", "置入弃牌堆")
    return DelayedTrickResolution(
        card=card,
        nullified=nullified,
        judgment_performed=judgment_performed,
        judgment_suit=judgment_suit,
        judgment_rank=judgment_rank,
        effect_applied=effect_applied,
        skipped_phase=skipped_phase,
        damage_amount=damage_amount,
        damage_type=damage_type,
        destination=DelayedTrickDestination.DISCARD_PILE,
        next_seat=None,
        movement_wording="置入弃牌堆",
        resolution_steps=steps,
        discard_action_performed=False,
    )


def _transferred_delayed_result(
    card: DelayedTrick,
    *,
    nullified: bool,
    judgment_performed: bool,
    judgment_suit: str | None,
    judgment_rank: int | str | None,
    current_seat: int,
    player_count: int,
    living_seats: Iterable[int] | None,
) -> DelayedTrickResolution:
    steps = (
        ("无懈可击抵消", "移至下家判定区")
        if nullified
        else ("进行判定", "判定未命中", "移至下家判定区")
    )
    return DelayedTrickResolution(
        card=card,
        nullified=nullified,
        judgment_performed=judgment_performed,
        judgment_suit=judgment_suit,
        judgment_rank=judgment_rank,
        effect_applied=False,
        skipped_phase=None,
        damage_amount=0,
        damage_type=None,
        destination=DelayedTrickDestination.NEXT_PLAYER_JUDGMENT_ZONE,
        next_seat=_next_seat(current_seat, player_count, living_seats),
        movement_wording="移至下家判定区",
        resolution_steps=steps,
        discard_action_performed=False,
    )


def resolve_delayed_trick(
    card: DelayedTrick | str,
    *,
    nullified: bool,
    judgment_suit: str | None = None,
    judgment_rank: int | str | None = None,
    current_seat: int | None = None,
    player_count: int | None = None,
    living_seats: Iterable[int] | None = None,
) -> DelayedTrickResolution:
    """在判定前无懈时机后，结算三种已确认的延时锦囊。

    本函数表达的是延时锦囊已经到达判定阶段的流程。刚被使用并进入
    判定区的时点请使用 :func:`is_delayed_trick_nullification_window` 判断。
    结算【闪电】时可传入 ``living_seats``，其下家会沿当前座次数递增
    方向跳过已确认死亡的座位。
    """

    resolved = _coerce_enum(card, DelayedTrick, "延时锦囊")
    _ensure_bool(nullified, "是否被无懈可击抵消")

    if resolved is DelayedTrick.LIGHTNING and (
        current_seat is None or player_count is None
    ):
        raise ValueError("结算闪电必须提供当前座次和玩家人数以确定下家")

    if nullified:
        if resolved is DelayedTrick.LIGHTNING:
            return _transferred_delayed_result(
                resolved,
                nullified=True,
                judgment_performed=False,
                judgment_suit=None,
                judgment_rank=None,
                current_seat=current_seat,
                player_count=player_count,
                living_seats=living_seats,
            )
        return _discarded_delayed_result(
            resolved,
            nullified=True,
            judgment_performed=False,
            judgment_suit=None,
            judgment_rank=None,
            effect_applied=False,
        )

    if judgment_suit not in _SUITS:
        raise ValueError("未被无懈抵消时，判定花色必须为红桃、方块、梅花或黑桃")

    if resolved is DelayedTrick.INDULGENCE:
        applied = judgment_suit != "红桃"
        return _discarded_delayed_result(
            resolved,
            nullified=False,
            judgment_performed=True,
            judgment_suit=judgment_suit,
            judgment_rank=judgment_rank,
            effect_applied=applied,
            skipped_phase="出牌阶段" if applied else None,
        )

    if resolved is DelayedTrick.SUPPLY_SHORTAGE:
        applied = judgment_suit != "梅花"
        return _discarded_delayed_result(
            resolved,
            nullified=False,
            judgment_performed=True,
            judgment_suit=judgment_suit,
            judgment_rank=judgment_rank,
            effect_applied=applied,
            skipped_phase="摸牌阶段" if applied else None,
        )

    if isinstance(judgment_rank, bool) or not isinstance(judgment_rank, int):
        raise TypeError("闪电判定点数必须是整数")
    hit = judgment_suit == "黑桃" and 2 <= judgment_rank <= 9
    if hit:
        return _discarded_delayed_result(
            resolved,
            nullified=False,
            judgment_performed=True,
            judgment_suit=judgment_suit,
            judgment_rank=judgment_rank,
            effect_applied=True,
            damage_amount=3,
            damage_type="雷属性",
        )
    return _transferred_delayed_result(
        resolved,
        nullified=False,
        judgment_performed=True,
        judgment_suit=judgment_suit,
        judgment_rank=judgment_rank,
        current_seat=current_seat,
        player_count=player_count,
        living_seats=living_seats,
    )


class DamageType(Enum):
    UNATTRIBUTED = "无属性"
    FIRE = "火属性"
    THUNDER = "雷属性"


_ELEMENTAL_DAMAGE_TYPES = frozenset({DamageType.FIRE, DamageType.THUNDER})
_UNSPECIFIED_DAMAGE_SOURCE = object()


@dataclass(frozen=True)
class CardDamageDefaults:
    """一项卡牌伤害按通用规则补齐后的属性与来源。"""

    card_name: str
    damage_type: DamageType
    source: str | None


def resolve_card_damage_defaults(
    card_name: str,
    user: str,
    *,
    stated_damage_type: DamageType | str | None = None,
    stated_source: str | None | object = _UNSPECIFIED_DAMAGE_SOURCE,
) -> CardDamageDefaults:
    """补齐未注明属性与来源的卡牌伤害。

    未注明属性时为无属性；未注明来源时以使用者为来源。【闪电】按
    当前已确认的具体规则补为雷属性、无来源伤害。调用者也可用
    ``stated_source=None`` 表达其他规则明确写明的无来源伤害。
    """

    if not isinstance(card_name, str) or not card_name.strip():
        raise ValueError("卡牌名称不能为空")
    if not isinstance(user, str) or not user.strip():
        raise ValueError("卡牌使用者不能为空")
    if stated_damage_type is None:
        damage_type = (
            DamageType.THUNDER
            if card_name == "闪电"
            else DamageType.UNATTRIBUTED
        )
    else:
        damage_type = _coerce_enum(
            stated_damage_type,
            DamageType,
            "伤害属性",
        )
    if card_name == "闪电":
        source = None
    elif stated_source is _UNSPECIFIED_DAMAGE_SOURCE:
        source = user
    elif stated_source is None:
        source = None
    elif isinstance(stated_source, str) and stated_source.strip():
        source = stated_source
    else:
        raise ValueError("明确伤害来源必须是非空字符串或 None")
    return CardDamageDefaults(
        card_name=card_name,
        damage_type=damage_type,
        source=source,
    )


def can_target_fire_attack(target_hand_count: int) -> bool:
    """【火攻】只能选择至少有一张手牌的角色。"""

    ensure_int_at_least(target_hand_count, "火攻目标手牌数", 0)
    return target_hand_count > 0


@dataclass(frozen=True)
class FireAttackResolution:
    """【火攻】到展示步骤时的轻量流程状态。"""

    hand_count_when_used: int
    hand_count_at_reveal: int
    hand_card_revealed: bool
    matching_suit_discard_step_available: bool
    fire_damage_step_available: bool
    ended_due_to_no_hand: bool


def resolve_fire_attack(
    target_hand_count_when_used: int,
    target_hand_count_at_reveal: int,
) -> FireAttackResolution:
    """处理合法使用【火攻】后，目标到展示步骤时是否仍有手牌。"""

    if not can_target_fire_attack(target_hand_count_when_used):
        raise ValueError("使用火攻时，目标必须至少有一张手牌")
    ensure_int_at_least(
        target_hand_count_at_reveal,
        "火攻展示步骤的目标手牌数",
        0,
    )
    has_hand = target_hand_count_at_reveal > 0
    return FireAttackResolution(
        hand_count_when_used=target_hand_count_when_used,
        hand_count_at_reveal=target_hand_count_at_reveal,
        hand_card_revealed=has_hand,
        matching_suit_discard_step_available=has_hand,
        fire_damage_step_available=has_hand,
        ended_due_to_no_hand=not has_hand,
    )


class CardEffectKind(Enum):
    """当前藤甲轻量结算需要区分的卡牌形态。"""

    NORMAL_SLASH = "普通杀"
    FIRE_SLASH = "火杀"
    THUNDER_SLASH = "雷杀"
    BARBARIAN_INVASION = "南蛮入侵"
    ARCHERY_ATTACK = "万箭齐发"
    OTHER = "其他卡牌"


@dataclass(frozen=True)
class VineArmorResolution:
    """藤甲检查完成后的卡牌有效性与可能伤害属性。"""

    original_card: CardEffectKind
    card_at_armor_check: CardEffectKind
    armor_active: bool
    card_effective: bool
    reaches_damage_stage: bool
    damage_type: DamageType | None
    fire_damage_bonus: int
    reason: str


def _card_effect_base_damage_type(
    card_effect: CardEffectKind,
) -> DamageType:
    if card_effect is CardEffectKind.FIRE_SLASH:
        return DamageType.FIRE
    if card_effect is CardEffectKind.THUNDER_SLASH:
        return DamageType.THUNDER
    return DamageType.UNATTRIBUTED


def resolve_vine_armor(
    card_effect: CardEffectKind | str,
    *,
    armor_active: bool = True,
    converted_before_armor_check: CardEffectKind | str | None = None,
    late_damage_type: DamageType | str | None = None,
) -> VineArmorResolution:
    """区分藤甲无效化检查前后的牌形态与伤害属性转换。

    ``converted_before_armor_check`` 只表达普通【杀】在藤甲检查前已经
    转成【火杀】或【雷杀】；``late_damage_type`` 只表达牌仍保持原形态、
    到将造成伤害时才修改伤害属性。后者不能让已被藤甲无效的牌复效。
    """

    original = _coerce_enum(card_effect, CardEffectKind, "卡牌效果")
    _ensure_bool(armor_active, "藤甲是否有效")
    current = original
    if converted_before_armor_check is not None:
        converted = _coerce_enum(
            converted_before_armor_check,
            CardEffectKind,
            "藤甲检查前的卡牌形态",
        )
        if original is not CardEffectKind.NORMAL_SLASH or converted not in {
            CardEffectKind.FIRE_SLASH,
            CardEffectKind.THUNDER_SLASH,
        }:
            raise ValueError("藤甲检查前转换只支持普通杀转为火杀或雷杀")
        current = converted
    late_type = (
        None
        if late_damage_type is None
        else _coerce_enum(late_damage_type, DamageType, "较晚修改的伤害属性")
    )

    blocked = armor_active and current in {
        CardEffectKind.NORMAL_SLASH,
        CardEffectKind.BARBARIAN_INVASION,
        CardEffectKind.ARCHERY_ATTACK,
    }
    if blocked:
        return VineArmorResolution(
            original_card=original,
            card_at_armor_check=current,
            armor_active=True,
            card_effective=False,
            reaches_damage_stage=False,
            damage_type=None,
            fire_damage_bonus=0,
            reason="藤甲在伤害阶段前已令该牌对目标无效",
        )

    damage_type = late_type or _card_effect_base_damage_type(current)
    return VineArmorResolution(
        original_card=original,
        card_at_armor_check=current,
        armor_active=armor_active,
        card_effective=True,
        reaches_damage_stage=True,
        damage_type=damage_type,
        fire_damage_bonus=(
            1 if armor_active and damage_type is DamageType.FIRE else 0
        ),
        reason=(
            "藤甲无效或未生效，按卡牌正常结算"
            if not armor_active
            else "该牌不属于藤甲无效的卡牌形态"
        ),
    )


def apply_silver_lion_damage(
    damage_amount: int,
    damage_type: DamageType | str,
    *,
    source: str | None = None,
) -> int:
    """应用【白银狮子】对任意属性、任意来源伤害的强制修正。"""

    ensure_int_at_least(damage_amount, "伤害点数", 0)
    _coerce_enum(damage_type, DamageType, "伤害属性")
    if source is not None and (
        not isinstance(source, str) or not source.strip()
    ):
        raise ValueError("伤害来源必须是非空字符串或 None")
    return 1 if damage_amount >= 2 else damage_amount


def apply_silver_lion_to_hp_loss(loss_amount: int) -> int:
    """“失去体力”不是伤害，因此白银狮子不修改其数值。"""

    ensure_int_at_least(loss_amount, "失去体力点数", 0)
    return loss_amount


@dataclass(frozen=True)
class SilverLionLeaveResolution:
    """白银狮子以任意方式离开装备区后的恢复结果。"""

    leaving_reason: str
    hp_before: int
    maximum_hp: int
    recovered_amount: int
    hp_after: int


def resolve_silver_lion_leaving(
    current_hp: int,
    maximum_hp: int,
    leaving_reason: str,
) -> SilverLionLeaveResolution:
    """只要白银狮子离开装备区便恢复 1 点，且不超过体力上限。"""

    if isinstance(current_hp, bool) or not isinstance(current_hp, int):
        raise TypeError("当前体力必须是整数")
    ensure_int_at_least(maximum_hp, "体力上限", 1)
    if current_hp > maximum_hp:
        raise ValueError("当前体力不能超过体力上限")
    if not isinstance(leaving_reason, str) or not leaving_reason.strip():
        raise ValueError("离开装备区的方式不能为空")
    hp_after = min(maximum_hp, current_hp + 1)
    return SilverLionLeaveResolution(
        leaving_reason=leaving_reason,
        hp_before=current_hp,
        maximum_hp=maximum_hp,
        recovered_amount=hp_after - current_hp,
        hp_after=hp_after,
    )


@dataclass(frozen=True)
class ChainParticipant:
    """参与轻量传导结算的一名角色及其当前状态。"""

    character_id: str
    seat: int
    chained: bool = True
    alive: bool = True


class ChainBattleState:
    """供结算回调读取或动态修改的当前角色状态。"""

    def __init__(
        self,
        participants: Sequence[ChainParticipant],
        player_count: int,
    ) -> None:
        ensure_int_at_least(player_count, "玩家人数", 2)
        if participants is None:
            raise TypeError("参与角色不能是 None")
        try:
            prepared = tuple(participants)
        except TypeError as exc:
            raise TypeError("参与角色必须是可迭代序列") from exc
        if not prepared:
            raise ValueError("参与角色不能为空")
        ids: set[str] = set()
        seats: set[int] = set()
        self._participants: dict[str, ChainParticipant] = {}
        for participant in prepared:
            if not isinstance(participant, ChainParticipant):
                raise TypeError("参与角色必须使用 ChainParticipant 表示")
            if (
                not isinstance(participant.character_id, str)
                or not participant.character_id.strip()
            ):
                raise ValueError("角色标识不能为空")
            if participant.character_id in ids:
                raise ValueError(f"角色标识不能重复：{participant.character_id}")
            ensure_int_at_least(participant.seat, "当前座次", 1)
            if participant.seat > player_count:
                raise ValueError(
                    f"当前座次不能超过玩家人数 {player_count}，"
                    f"当前为 {participant.seat}"
                )
            if participant.seat in seats:
                raise ValueError(f"当前座次不能重复：{participant.seat}")
            _ensure_bool(participant.chained, "横置状态")
            _ensure_bool(participant.alive, "存活状态")
            ids.add(participant.character_id)
            seats.add(participant.seat)
            self._participants[participant.character_id] = participant
        self.player_count = player_count
        self.game_over = False

    def participant(self, character_id: str) -> ChainParticipant:
        try:
            return self._participants[character_id]
        except KeyError as exc:
            raise ValueError(f"不存在角色：{character_id}") from exc

    def set_chained(self, character_id: str, chained: bool) -> None:
        _ensure_bool(chained, "横置状态")
        old = self.participant(character_id)
        self._participants[character_id] = ChainParticipant(
            old.character_id,
            old.seat,
            chained,
            old.alive,
        )

    def set_alive(self, character_id: str, alive: bool) -> None:
        _ensure_bool(alive, "存活状态")
        old = self.participant(character_id)
        self._participants[character_id] = ChainParticipant(
            old.character_id,
            old.seat,
            old.chained,
            alive,
        )

    def end_game(self) -> None:
        """由回调在胜负条件已令游戏立即结束时显式调用。"""

        self.game_over = True

    def ordered_character_ids(self, start_seat: int) -> tuple[str, ...]:
        ensure_int_at_least(start_seat, "当前回合座次", 1)
        if start_seat > self.player_count:
            raise ValueError(
                f"当前回合座次不能超过玩家人数 {self.player_count}"
            )
        by_seat = {
            participant.seat: participant.character_id
            for participant in self._participants.values()
        }
        order = tuple(
            ((start_seat - 1 + offset) % self.player_count) + 1
            for offset in range(self.player_count)
        )
        return tuple(by_seat[seat] for seat in order if seat in by_seat)

    def snapshot(self) -> tuple[ChainParticipant, ...]:
        return tuple(
            sorted(self._participants.values(), key=lambda item: item.seat)
        )


@dataclass(frozen=True)
class DamageEvent:
    """一项已经完成自身增减后的实际伤害事件。"""

    target: str
    actual_damage: int
    damage_type: DamageType | str
    source: str | None = None


@dataclass(frozen=True)
class RecipientDamageOutcome:
    """一名传导角色完整处理自身效果后的结果。"""

    actual_damage: int
    subsequent_chain_base_damage: int | None = None
    died: bool = False
    spawned_events: tuple[DamageEvent, ...] = ()


@dataclass(frozen=True)
class ChainDamageStep:
    """一次原始伤害或传导伤害的事件日志。"""

    event_id: int
    parent_event_id: int | None
    round_id: int | None
    target: str
    seat: int
    role: str
    actual_damage: int
    damage_type: DamageType
    source: str | None
    chain_base_damage_before: int | None
    chain_base_damage_after: int | None
    chained_before: bool
    chained_after: bool
    prevented: bool
    died: bool
    nested_depth: int


@dataclass(frozen=True)
class ChainDamageResolution:
    """一次伤害及其全部嵌套传导完成后的轻量结果。"""

    steps: tuple[ChainDamageStep, ...]
    final_participants: tuple[ChainParticipant, ...]
    rounds_started: int
    rounds_terminated_by_zero: int
    game_over: bool


RecipientResolver = Callable[
    [str, int, DamageType, str | None, ChainBattleState],
    RecipientDamageOutcome,
]
AfterDamageHandler = Callable[
    [ChainDamageStep, ChainBattleState],
    Iterable[DamageEvent] | None,
]
DamageSourceResolver = Callable[
    [str, str | None, ChainBattleState],
    str | None,
]


def _coerce_damage_event(event: DamageEvent, state: ChainBattleState) -> DamageEvent:
    if not isinstance(event, DamageEvent):
        raise TypeError("伤害事件必须使用 DamageEvent 表示")
    state.participant(event.target)
    ensure_int_at_least(event.actual_damage, "实际伤害点数", 0)
    damage_type = _coerce_enum(event.damage_type, DamageType, "伤害属性")
    if event.source is not None and not isinstance(event.source, str):
        raise TypeError("伤害来源必须是字符串或 None")
    return DamageEvent(
        target=event.target,
        actual_damage=event.actual_damage,
        damage_type=damage_type,
        source=event.source,
    )


def _default_recipient_resolver(
    _target: str,
    chain_base_damage: int,
    _damage_type: DamageType,
    _source: str | None,
    _state: ChainBattleState,
) -> RecipientDamageOutcome:
    return RecipientDamageOutcome(actual_damage=chain_base_damage)


def resolve_chain_damage(
    participants: Sequence[ChainParticipant],
    original_event: DamageEvent,
    *,
    player_count: int,
    current_turn_seat: int,
    recipient_resolver: RecipientResolver | None = None,
    after_damage: AfterDamageHandler | None = None,
    damage_source_resolver: DamageSourceResolver | None = None,
    max_damage_events: int = 1000,
) -> ChainDamageResolution:
    """依序结算一次伤害及其引发的铁索传导。

    ``original_event.actual_damage`` 是原始目标经过自身增减后最终实际
    受到的点数，并据此确定传导基础伤害。``recipient_resolver`` 负责
    后续每名角色自身的防具、技能、体力、濒死和死亡等完整处理；只有
    其返回 ``subsequent_chain_base_damage`` 时，才修改后续基础伤害。
    ``after_damage`` 可动态修改横置状态、宣布游戏结束，或返回独立的
    新伤害事件；新事件会完整结算后再回到原传导。若提供
    ``damage_source_resolver``，每名尚未开始结算的传导目标都会重新解析
    当前伤害来源，供“来源代理中途死亡后恢复原来源”等状态效果使用；
    不提供时保持整轮沿用原事件来源的既有行为。
    """

    ensure_int_at_least(max_damage_events, "独立伤害事件安全上限", 1)
    state = ChainBattleState(participants, player_count)
    ensure_int_at_least(current_turn_seat, "当前回合座次", 1)
    if current_turn_seat > player_count:
        raise ValueError("当前回合座次不能超过玩家人数")
    if recipient_resolver is not None and not callable(recipient_resolver):
        raise TypeError("传导角色结算器必须可调用")
    if after_damage is not None and not callable(after_damage):
        raise TypeError("伤害后处理器必须可调用")
    if damage_source_resolver is not None and not callable(damage_source_resolver):
        raise TypeError("动态伤害来源解析器必须可调用")
    resolver = recipient_resolver or _default_recipient_resolver

    steps: list[ChainDamageStep] = []
    event_counter = 0
    round_counter = 0
    terminated_rounds = 0

    def append_step(
        *,
        event_id: int,
        parent_event_id: int | None,
        round_id: int | None,
        target: str,
        role: str,
        actual_damage: int,
        damage_type: DamageType,
        source: str | None,
        base_before: int | None,
        base_after: int | None,
        chained_before: bool,
        chained_after: bool,
        prevented: bool,
        died: bool,
        depth: int,
    ) -> ChainDamageStep:
        step = ChainDamageStep(
            event_id=event_id,
            parent_event_id=parent_event_id,
            round_id=round_id,
            target=target,
            seat=state.participant(target).seat,
            role=role,
            actual_damage=actual_damage,
            damage_type=damage_type,
            source=source,
            chain_base_damage_before=base_before,
            chain_base_damage_after=base_after,
            chained_before=chained_before,
            chained_after=chained_after,
            prevented=prevented,
            died=died,
            nested_depth=depth,
        )
        steps.append(step)
        return step

    def run_after_damage(
        step: ChainDamageStep,
        *,
        parent_id: int,
        depth: int,
        spawned: Iterable[DamageEvent] = (),
    ) -> None:
        nested = list(spawned)
        if after_damage is not None:
            extra = after_damage(step, state)
            if extra is not None:
                try:
                    nested.extend(extra)
                except TypeError as exc:
                    raise TypeError("伤害后处理器必须返回伤害事件的可迭代对象或 None") from exc
        if state.game_over:
            return
        for new_event in nested:
            process_event(new_event, parent_event_id=parent_id, depth=depth + 1)
            if state.game_over:
                return

    def process_event(
        raw_event: DamageEvent,
        *,
        parent_event_id: int | None,
        depth: int,
    ) -> None:
        nonlocal event_counter, round_counter, terminated_rounds
        event_counter += 1
        if event_counter > max_damage_events:
            raise RuntimeError(
                "独立伤害事件超过安全上限；请检查伤害后处理器是否产生无限递归"
            )
        event_id = event_counter
        event = _coerce_damage_event(raw_event, state)
        damage_type = event.damage_type
        target_before = state.participant(event.target)
        triggers_chain = (
            event.actual_damage > 0
            and damage_type in _ELEMENTAL_DAMAGE_TYPES
            and target_before.chained
            and target_before.alive
        )

        current_round_id: int | None = None
        if triggers_chain:
            round_counter += 1
            current_round_id = round_counter
            state.set_chained(event.target, False)

        original_step = append_step(
            event_id=event_id,
            parent_event_id=parent_event_id,
            round_id=current_round_id,
            target=event.target,
            role="原始伤害",
            actual_damage=event.actual_damage,
            damage_type=damage_type,
            source=event.source,
            base_before=event.actual_damage if triggers_chain else None,
            base_after=event.actual_damage if triggers_chain else None,
            chained_before=target_before.chained,
            chained_after=state.participant(event.target).chained,
            prevented=event.actual_damage == 0,
            died=False,
            depth=depth,
        )

        if event.actual_damage > 0:
            run_after_damage(
                original_step,
                parent_id=event_id,
                depth=depth,
            )
        if state.game_over or not triggers_chain:
            return

        chain_base_damage = event.actual_damage
        order = state.ordered_character_ids(current_turn_seat)
        for character_id in order:
            if state.game_over:
                return
            if character_id == event.target:
                continue
            current = state.participant(character_id)
            if not current.alive or not current.chained:
                continue

            current_source = (
                event.source
                if damage_source_resolver is None
                else damage_source_resolver(character_id, event.source, state)
            )
            if current_source is not None and not isinstance(current_source, str):
                raise TypeError("动态伤害来源解析器必须返回字符串或 None")
            outcome = resolver(
                character_id,
                chain_base_damage,
                damage_type,
                current_source,
                state,
            )
            if not isinstance(outcome, RecipientDamageOutcome):
                raise TypeError("传导角色结算器必须返回 RecipientDamageOutcome")
            ensure_int_at_least(outcome.actual_damage, "传导实际伤害", 0)
            if outcome.subsequent_chain_base_damage is not None:
                ensure_int_at_least(
                    outcome.subsequent_chain_base_damage,
                    "后续传导基础伤害",
                    0,
                )
            _ensure_bool(outcome.died, "角色死亡状态")
            try:
                spawned = tuple(outcome.spawned_events)
            except TypeError as exc:
                raise TypeError("新伤害事件必须是可迭代序列") from exc

            if outcome.actual_damage == 0:
                # 规则确认：完全防止为 0 时不解除当前角色的横置状态。
                state.set_chained(character_id, True)
                append_step(
                    event_id=event_id,
                    parent_event_id=parent_event_id,
                    round_id=current_round_id,
                    target=character_id,
                    role="传导伤害",
                    actual_damage=0,
                    damage_type=damage_type,
                    source=current_source,
                    base_before=chain_base_damage,
                    base_after=chain_base_damage,
                    chained_before=True,
                    chained_after=True,
                    prevented=True,
                    died=False,
                    depth=depth,
                )
                terminated_rounds += 1
                break

            state.set_chained(character_id, False)
            if outcome.died:
                state.set_alive(character_id, False)
            next_base = (
                chain_base_damage
                if outcome.subsequent_chain_base_damage is None
                else outcome.subsequent_chain_base_damage
            )
            step = append_step(
                event_id=event_id,
                parent_event_id=parent_event_id,
                round_id=current_round_id,
                target=character_id,
                role="传导伤害",
                actual_damage=outcome.actual_damage,
                damage_type=damage_type,
                source=current_source,
                base_before=chain_base_damage,
                base_after=next_base,
                chained_before=True,
                chained_after=False,
                prevented=False,
                died=outcome.died,
                depth=depth,
            )
            chain_base_damage = next_base
            run_after_damage(
                step,
                parent_id=event_id,
                depth=depth,
                spawned=spawned,
            )

    process_event(original_event, parent_event_id=None, depth=0)
    return ChainDamageResolution(
        steps=tuple(steps),
        final_participants=state.snapshot(),
        rounds_started=round_counter,
        rounds_terminated_by_zero=terminated_rounds,
        game_over=state.game_over,
    )


@dataclass(frozen=True)
class TransformedSlash:
    """【丈八蛇矛】两张手牌转化出的普通【杀】。"""

    card_name: str
    color: str
    suit: str | None
    suit_status: str
    rank: None
    damage_type: DamageType


def transform_zhangba_spear(
    first_color: str,
    second_color: str,
    *,
    first_rank: int | str | None = None,
    second_rank: int | str | None = None,
) -> TransformedSlash:
    """返回丈八蛇矛转化牌；原牌点数无论为何都不会被继承或计算。"""

    allowed = {"红色", "黑色"}
    if first_color not in allowed or second_color not in allowed:
        raise ValueError("两张原手牌的颜色只能为“红色”或“黑色”")
    color = first_color if first_color == second_color else "无色"
    # 显式不读取 first_rank/second_rank，防止继承、求和或取极值。
    _ = first_rank, second_rank
    return TransformedSlash(
        card_name="杀",
        color=color,
        suit=None,
        suit_status="当前确认",
        rank=None,
        damage_type=DamageType.UNATTRIBUTED,
    )
