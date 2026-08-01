"""移动版八人军争“主公立储与内奸择途”的轻量规则模型。

本模块只处理“立储与内奸择途”变体新增或覆盖的规则边界，不复制
标准八人军争身份规则，也不是完整游戏引擎。所有特殊操作都要求显式
启用 ``mobile_8p_heir_and_spy_choice``，避免与标准八人军争静默混用。
该标识和模块标题均为项目内部描述，不是官方正式模式名称。
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from types import MappingProxyType
from typing import Callable, Generic, Iterable, Mapping, TypeVar

from ._validation import ensure_int_at_least
from .sgs_extended_rules import LivingSeatRing
from .sgs_modes import SGS_PRIMARY_PLATFORM, TurnOccurrence

T = TypeVar("T")
S = TypeVar("S")


class ModeVariant(Enum):
    """本模块允许区分的八人军争模式。"""

    STANDARD_EIGHT_PLAYER = "standard_8p_identity"
    MOBILE_HEIR_AND_SPY_CHOICE = "mobile_8p_heir_and_spy_choice"


LIMITED_MODE_VARIANT = ModeVariant.MOBILE_HEIR_AND_SPY_CHOICE.value
LIMITED_MODE_DECK_ID = "sgs_mobile_non_special_20260725_unofficial"


@dataclass(frozen=True)
class LimitedModeMetadata:
    """八人特殊玩法的宣传文字、内部标识与最后核验状态。"""

    descriptive_title: str
    platform: str
    official_display_text: str
    official_formal_name: str | None
    internal_mode_id: str
    deck_id: str
    availability_label: str
    first_known_promotion_or_open_date: str
    rules_version: str | None
    end_date: str | None
    permanent_status: str
    last_verified_date: str
    available_on_last_verification: bool


def limited_mode_metadata() -> LimitedModeMetadata:
    """返回用户当前确认的模式元数据，不虚构官方正式名称。"""

    return LimitedModeMetadata(
        descriptive_title="移动版八人军争特殊玩法：主公立储与内奸择途",
        platform=SGS_PRIMARY_PLATFORM,
        official_display_text=(
            "军争全新玩法：主公立储，内奸择途，限时开启。"
        ),
        official_formal_name=None,
        internal_mode_id=LIMITED_MODE_VARIANT,
        deck_id=LIMITED_MODE_DECK_ID,
        availability_label="限时开启",
        first_known_promotion_or_open_date="2026-05-16",
        rules_version=None,
        end_date=None,
        permanent_status="未知",
        last_verified_date="2026-07-26",
        available_on_last_verification=True,
    )


def limited_mode_is_available(
    *,
    game_version: str | None = None,
    confirmed_removed_or_closed: bool = False,
) -> bool:
    """沿用最后确认的开放状态，普通版本变化不会自动令玩法失效。"""

    if game_version is not None and (
        not isinstance(game_version, str) or not game_version.strip()
    ):
        raise ValueError("游戏版本必须是非空字符串或 None")
    if not isinstance(confirmed_removed_or_closed, bool):
        raise TypeError("确认关闭标识必须是布尔值")
    return not confirmed_removed_or_closed


class CurrentRole(Enum):
    """事件发生时使用的当前真实身份。"""

    LORD = "主公"
    LOYALIST = "忠臣"
    REBEL = "反贼"
    SPY = "内奸"
    AMBITIONIST = "野心家"


class SpyPathChoice(Enum):
    LOYALIST = "忠臣"
    AMBITIONIST = "野心家"


class CardRegion(Enum):
    HAND = "手牌区"
    EQUIPMENT = "装备区"
    JUDGMENT = "判定区"


class VirtualPeachTiming(Enum):
    OWN_PLAY_PHASE = "自己的出牌阶段"
    DYING_RESCUE = "濒死救援"


class VariantVictory(Enum):
    ONGOING = "游戏继续"
    LORD_AND_LOYALISTS = "主公与忠臣获胜"
    REBELS = "反贼获胜"
    SPY = "内奸获胜"
    AMBITIONIST = "野心家获胜"


def _coerce_mode(value: ModeVariant | str) -> ModeVariant:
    if isinstance(value, ModeVariant):
        return value
    try:
        return ModeVariant(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "模式标识必须是 standard_8p_identity 或 "
            "mobile_8p_heir_and_spy_choice"
        ) from exc


def _coerce_role(value: CurrentRole | str) -> CurrentRole:
    if isinstance(value, CurrentRole):
        return value
    try:
        return CurrentRole(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("当前身份必须是主公、忠臣、反贼、内奸或野心家") from exc


def _coerce_spy_choice(value: SpyPathChoice | str) -> SpyPathChoice:
    if isinstance(value, SpyPathChoice):
        return value
    try:
        return SpyPathChoice(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("内奸择途只能选择忠臣或野心家") from exc


def _coerce_region(value: CardRegion | str) -> CardRegion:
    if isinstance(value, CardRegion):
        return value
    try:
        return CardRegion(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("区域必须是手牌区、装备区或判定区") from exc


def _coerce_peach_timing(value: VirtualPeachTiming | str) -> VirtualPeachTiming:
    if isinstance(value, VirtualPeachTiming):
        return value
    try:
        return VirtualPeachTiming(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("虚拟桃时机必须是自己的出牌阶段或濒死救援") from exc


def _tuple(values: Iterable[T], name: str) -> tuple[T, ...]:
    if values is None:
        raise TypeError(f"{name}不能是 None")
    try:
        return tuple(values)
    except TypeError as exc:
        raise TypeError(f"{name}必须是可迭代对象") from exc


def _ensure_int(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name}必须是整数，当前值为 {value!r}")
    return value


def _ensure_variant(mode_variant: ModeVariant | str) -> ModeVariant:
    mode = _coerce_mode(mode_variant)
    if mode is not ModeVariant.MOBILE_HEIR_AND_SPY_CHOICE:
        raise ValueError("该操作仅在移动版八人军争限时变体中可用")
    return mode


@dataclass(frozen=True)
class VariantFeatures:
    mode_variant: ModeVariant
    special_rules_loaded: bool
    heir_selection_enabled: bool
    spy_path_enabled: bool


def load_variant_features(mode_variant: ModeVariant | str) -> VariantFeatures:
    """只在显式启用限时变体时加载立储与择途。"""

    mode = _coerce_mode(mode_variant)
    enabled = mode is ModeVariant.MOBILE_HEIR_AND_SPY_CHOICE
    return VariantFeatures(mode, enabled, enabled, enabled)


@dataclass(frozen=True)
class PlayerRoleState:
    """同时保留开局身份和事件发生时的当前身份。"""

    role_original: CurrentRole
    role_current: CurrentRole
    identity_revealed: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "role_original", _coerce_role(self.role_original))
        object.__setattr__(self, "role_current", _coerce_role(self.role_current))


def reveal_current_identity_after_confirmed_death(
    role_state: PlayerRoleState,
) -> PlayerRoleState:
    """确认死亡后按当时的当前真实身份公开，而不是开局身份。"""

    if not isinstance(role_state, PlayerRoleState):
        raise TypeError("身份状态必须是 PlayerRoleState")
    return replace(role_state, identity_revealed=True)


@dataclass(frozen=True)
class HeirSelectionState:
    mode_variant: ModeVariant
    original_lord_player_id: int
    current_lord_player_id: int
    heir_player_id: int | None
    heir_selected: bool
    heir_selection_available: bool
    heir_selection_used: bool
    heir_information_owner: int | None


def initial_heir_selection_state(
    mode_variant: ModeVariant | str,
    lord_player_id: int,
) -> HeirSelectionState:
    """建立开局立储状态；标准模式不会加载立储机会。"""

    mode = _coerce_mode(mode_variant)
    lord = ensure_int_at_least(lord_player_id, "主公玩家标识", 1)
    enabled = mode is ModeVariant.MOBILE_HEIR_AND_SPY_CHOICE
    return HeirSelectionState(
        mode_variant=mode,
        original_lord_player_id=lord,
        current_lord_player_id=lord,
        heir_player_id=None,
        heir_selected=False,
        heir_selection_available=enabled,
        heir_selection_used=False,
        heir_information_owner=lord if enabled else None,
    )


def select_heir(
    state: HeirSelectionState,
    target_player_id: int,
    *,
    alive_players: Iterable[int],
    first_round_active: bool,
) -> HeirSelectionState:
    """在第一轮任意时点秘密选择一名仍在场的其他角色。"""

    if not isinstance(state, HeirSelectionState):
        raise TypeError("立储状态必须是 HeirSelectionState")
    _ensure_variant(state.mode_variant)
    target = ensure_int_at_least(target_player_id, "储君玩家标识", 1)
    alive = frozenset(_tuple(alive_players, "存活玩家"))
    if not first_round_active:
        raise ValueError("第一轮已经结束，不能再立储")
    if not state.heir_selection_available or state.heir_selection_used:
        raise ValueError("主公的立储机会已经使用或失效")
    if state.current_lord_player_id != state.original_lord_player_id:
        raise ValueError("继位产生的新主公不能再次立储")
    if target == state.current_lord_player_id:
        raise ValueError("主公不能选择自己作为储君")
    if target not in alive:
        raise ValueError("储君目标必须是仍在场的其他角色")
    return replace(
        state,
        heir_player_id=target,
        heir_selected=True,
        heir_selection_available=False,
        heir_selection_used=True,
    )


def select_heir_in_turn(
    state: HeirSelectionState,
    target_player_id: int,
    *,
    alive_players: Iterable[int],
    turn: TurnOccurrence,
) -> HeirSelectionState:
    """按轮次状态立储；第一轮额外回合仍属于合法窗口。"""

    if not isinstance(turn, TurnOccurrence):
        raise TypeError("立储回合信息必须是 TurnOccurrence")
    return select_heir(
        state,
        target_player_id,
        alive_players=alive_players,
        first_round_active=turn.round_number == 1,
    )


def expire_heir_selection(state: HeirSelectionState) -> HeirSelectionState:
    """第一轮结束时令未使用的立储机会失效。"""

    if not isinstance(state, HeirSelectionState):
        raise TypeError("立储状态必须是 HeirSelectionState")
    return replace(state, heir_selection_available=False)


@dataclass(frozen=True)
class HeirInformationView:
    selection_status_known: bool
    heir_selected: bool | None
    heir_player_id: int | None


def view_heir_information(
    state: HeirSelectionState,
    viewer_player_id: int,
) -> HeirInformationView:
    """只有立储信息所有者知道是否已立储及具体目标。"""

    if not isinstance(state, HeirSelectionState):
        raise TypeError("立储状态必须是 HeirSelectionState")
    viewer = ensure_int_at_least(viewer_player_id, "查看者玩家标识", 1)
    if viewer == state.heir_information_owner:
        return HeirInformationView(True, state.heir_selected, state.heir_player_id)
    return HeirInformationView(False, None, None)


@dataclass(frozen=True)
class HeirDeathResult:
    triggered: bool
    lord_hp_before: int
    lord_hp_after: int
    hp_loss_amount: int
    is_damage: bool
    damage_source: None
    damage_type: None
    triggers_damage_events: bool
    lord_enters_dying: bool
    heir_state_after: HeirSelectionState


def resolve_heir_confirmed_death(
    state: HeirSelectionState,
    dead_player_id: int,
    *,
    current_lord_player_id: int,
    alive_players_before_death: Iterable[int],
    current_lord_hp: int,
) -> HeirDeathResult:
    """储君确认死亡时令仍在场的当前主公失去一点体力。

    该结算不读取储君当前身份，且明确不是伤害事件。
    """

    if not isinstance(state, HeirSelectionState):
        raise TypeError("立储状态必须是 HeirSelectionState")
    dead = ensure_int_at_least(dead_player_id, "死亡玩家标识", 1)
    lord = ensure_int_at_least(current_lord_player_id, "当前主公标识", 1)
    hp = _ensure_int(current_lord_hp, "当前主公体力")
    alive = frozenset(_tuple(alive_players_before_death, "死亡前存活玩家"))
    is_heir = state.heir_selected and state.heir_player_id == dead
    lord_is_alive = lord in alive and lord != dead
    triggered = bool(is_heir and lord_is_alive)
    hp_after = hp - 1 if triggered else hp
    state_after = state
    if is_heir:
        state_after = replace(
            state,
            heir_player_id=None,
            heir_selected=False,
            heir_selection_available=False,
        )
    return HeirDeathResult(
        triggered=triggered,
        lord_hp_before=hp,
        lord_hp_after=hp_after,
        hp_loss_amount=1 if triggered else 0,
        is_damage=False,
        damage_source=None,
        damage_type=None,
        triggers_damage_events=False,
        lord_enters_dying=triggered and hp_after <= 0,
        heir_state_after=state_after,
    )


def can_heir_succeed(
    state: HeirSelectionState,
    roles_current: Mapping[int, CurrentRole | str],
    alive_players: Iterable[int],
) -> bool:
    """继位时只检查存活、在场及当前真实身份为忠臣。"""

    if not isinstance(state, HeirSelectionState):
        raise TypeError("立储状态必须是 HeirSelectionState")
    if not state.heir_selected or state.heir_player_id is None:
        return False
    alive = frozenset(_tuple(alive_players, "存活玩家"))
    heir = state.heir_player_id
    try:
        role = _coerce_role(roles_current[heir])
    except KeyError:
        return False
    return heir in alive and role is CurrentRole.LOYALIST


@dataclass(frozen=True)
class LordRegions(Generic[T]):
    hand: tuple[T, ...] = ()
    equipment: tuple[T, ...] = ()
    judgment: tuple[T, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "hand", _tuple(self.hand, "原主公手牌区"))
        object.__setattr__(self, "equipment", _tuple(self.equipment, "原主公装备区"))
        object.__setattr__(self, "judgment", _tuple(self.judgment, "原主公判定区"))


@dataclass(frozen=True)
class RegionCardChoice:
    region: CardRegion
    index: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "region", _coerce_region(self.region))
        ensure_int_at_least(self.index, "所选牌索引", 0)


@dataclass(frozen=True)
class SuccessionResult(Generic[T]):
    """继位检查结果；成功时仍处于原主公正式死亡之前。

    因此 ``living_seat_ring`` 在成功结果中仍包含原主公。只有随后调用
    :func:`finalize_old_lord_formal_death_after_succession`，才会把原主公
    从存活角色环移除。
    """

    succeeded: bool
    failure_reason: str | None
    checked_after_rescue_failure: bool
    checked_before_formal_death: bool
    succession_completed_before_formal_death: bool
    current_lord_player_id: int
    roles_current: Mapping[int, CurrentRole]
    living_seat_ring: LivingSeatRing
    obtained_card: T | None
    obtained_from: CardRegion | None
    new_lord_hand: tuple[T, ...]
    remaining_old_lord_regions: LordRegions[T]
    new_lord_maximum_hp: int | None
    new_lord_current_hp: int | None
    new_lord_identity_revealed: bool
    lord_skill_enabled: bool
    heir_state_after: HeirSelectionState
    seats_renumbered: bool
    extra_turn_granted: bool
    rebel_instant_win_from_old_lord_death: bool
    completed_event_order: tuple[str, ...]
    next_required_event: str | None


def _remove_region_card(
    regions: LordRegions[T],
    choice: RegionCardChoice | None,
) -> tuple[T | None, CardRegion | None, LordRegions[T]]:
    if choice is None:
        return None, None, regions
    field_name = {
        CardRegion.HAND: "hand",
        CardRegion.EQUIPMENT: "equipment",
        CardRegion.JUDGMENT: "judgment",
    }[choice.region]
    cards = list(getattr(regions, field_name))
    if choice.index >= len(cards):
        raise ValueError(f"{choice.region.value}中不存在索引为 {choice.index} 的牌")
    obtained = cards.pop(choice.index)
    remaining = replace(regions, **{field_name: tuple(cards)})
    return obtained, choice.region, remaining


def resolve_heir_succession_after_failed_rescue(
    state: HeirSelectionState,
    *,
    rescue_failed: bool,
    roles_current: Mapping[int, CurrentRole | str],
    living_seat_ring: LivingSeatRing,
    old_lord_regions: LordRegions[T],
    new_lord_hand_before: Iterable[T] = (),
    new_lord_maximum_hp_before: int,
    new_lord_current_hp_before: int,
    selected_card: RegionCardChoice | None = None,
    new_lord_has_lord_skill: bool = False,
) -> SuccessionResult[T]:
    """救援失败后、原主公正式死亡前尝试完成合法储君继位。"""

    if not isinstance(state, HeirSelectionState):
        raise TypeError("立储状态必须是 HeirSelectionState")
    _ensure_variant(state.mode_variant)
    if not isinstance(living_seat_ring, LivingSeatRing):
        raise TypeError("存活座次环必须是 LivingSeatRing")
    if not isinstance(old_lord_regions, LordRegions):
        raise TypeError("原主公区域必须是 LordRegions")
    maximum = ensure_int_at_least(new_lord_maximum_hp_before, "继位前体力上限", 1)
    hp = ensure_int_at_least(new_lord_current_hp_before, "继位前当前体力", 1)
    if hp > maximum:
        raise ValueError("继位前当前体力不能超过体力上限")
    hand_before = _tuple(new_lord_hand_before, "新主公原有手牌")
    prepared_roles = {
        player: _coerce_role(role) for player, role in roles_current.items()
    }
    roles_view = MappingProxyType(prepared_roles)

    reason: str | None = None
    if not rescue_failed:
        reason = "原主公已经脱离濒死，不进行继位检查"
    elif not can_heir_succeed(state, prepared_roles, living_seat_ring.alive_players):
        reason = "不存在仍存活且当前身份为忠臣的合法储君"

    if reason is not None:
        completed_events = (
            ("完成濒死救援", "检查合法储君")
            if rescue_failed
            else ("完成濒死救援并成功脱离濒死",)
        )
        return SuccessionResult(
            succeeded=False,
            failure_reason=reason,
            checked_after_rescue_failure=rescue_failed,
            checked_before_formal_death=rescue_failed,
            succession_completed_before_formal_death=False,
            current_lord_player_id=state.current_lord_player_id,
            roles_current=roles_view,
            living_seat_ring=living_seat_ring,
            obtained_card=None,
            obtained_from=None,
            new_lord_hand=hand_before,
            remaining_old_lord_regions=old_lord_regions,
            new_lord_maximum_hp=None,
            new_lord_current_hp=None,
            new_lord_identity_revealed=False,
            lord_skill_enabled=False,
            heir_state_after=state,
            seats_renumbered=False,
            extra_turn_granted=False,
            rebel_instant_win_from_old_lord_death=False,
            completed_event_order=completed_events,
            next_required_event=("确认原主公正式死亡" if rescue_failed else None),
        )

    heir = state.heir_player_id
    assert heir is not None
    old_lord = state.current_lord_player_id
    if old_lord not in living_seat_ring.alive_players:
        raise ValueError("原主公必须在正式死亡处理前仍位于存活角色环")
    obtained, obtained_from, remaining = _remove_region_card(
        old_lord_regions, selected_card
    )
    hand_after = hand_before + (() if obtained is None else (obtained,))
    prepared_roles[heir] = CurrentRole.LORD
    new_maximum = maximum + 1
    new_hp = min(new_maximum, hp + 1)
    closed_heir_state = replace(
        state,
        current_lord_player_id=heir,
        heir_player_id=None,
        heir_selected=False,
        heir_selection_available=False,
        heir_selection_used=True,
        heir_information_owner=None,
    )
    return SuccessionResult(
        succeeded=True,
        failure_reason=None,
        checked_after_rescue_failure=True,
        checked_before_formal_death=True,
        succession_completed_before_formal_death=True,
        current_lord_player_id=heir,
        roles_current=MappingProxyType(prepared_roles),
        living_seat_ring=living_seat_ring,
        obtained_card=obtained,
        obtained_from=obtained_from,
        new_lord_hand=hand_after,
        remaining_old_lord_regions=remaining,
        new_lord_maximum_hp=new_maximum,
        new_lord_current_hp=new_hp,
        new_lord_identity_revealed=True,
        lord_skill_enabled=bool(new_lord_has_lord_skill),
        heir_state_after=closed_heir_state,
        seats_renumbered=False,
        extra_turn_granted=False,
        rebel_instant_win_from_old_lord_death=False,
        completed_event_order=(
            "完成濒死救援",
            "检查合法储君",
            "处理从原主公区域内获得至多1张牌的选择",
            "公开新主公身份并更新当前主公",
            "新主公体力上限增加1",
            "新主公回复1点体力",
            "启用新主公自身的主公技",
        ),
        next_required_event="确认原主公正式死亡",
    )


def finalize_old_lord_formal_death_after_succession(
    succession: SuccessionResult[T],
    old_lord_player_id: int,
) -> LivingSeatRing:
    """继位完成后，正式确认原主公死亡并将其移出存活角色环。"""

    if not isinstance(succession, SuccessionResult):
        raise TypeError("继位结果必须是 SuccessionResult")
    old_lord = ensure_int_at_least(old_lord_player_id, "原主公玩家标识", 1)
    if not succession.succeeded or not succession.succession_completed_before_formal_death:
        raise ValueError("只有继位已经完成时才能继续确认原主公正式死亡")
    if old_lord == succession.current_lord_player_id:
        raise ValueError("新主公不能作为本次待确认死亡的原主公")
    if old_lord not in succession.living_seat_ring.alive_players:
        raise ValueError("原主公已经不在存活角色环中，不能重复确认死亡")
    return succession.living_seat_ring.with_player_dead(old_lord)


def finalize_old_lord_formal_death_without_succession(
    succession_check: SuccessionResult[T],
    old_lord_player_id: int,
) -> LivingSeatRing:
    """救援失败且没有合法储君时，正式确认原主公死亡。"""

    if not isinstance(succession_check, SuccessionResult):
        raise TypeError("继位检查结果必须是 SuccessionResult")
    old_lord = ensure_int_at_least(old_lord_player_id, "原主公玩家标识", 1)
    if succession_check.succeeded:
        raise ValueError("合法继位已完成时必须使用继位后的正式死亡流程")
    if not succession_check.checked_after_rescue_failure:
        raise ValueError("原主公已获救时不能确认其死亡")
    if succession_check.next_required_event != "确认原主公正式死亡":
        raise ValueError("当前状态尚未进入正式死亡节点")
    if old_lord not in succession_check.living_seat_ring.alive_players:
        raise ValueError("原主公已经不在存活角色环中，不能重复确认死亡")
    return succession_check.living_seat_ring.with_player_dead(old_lord)


@dataclass(frozen=True)
class SpyPathState:
    """内奸择途的锁定状态。

    spy_path_effective_turn_player_id 仅为兼容旧调用保留；最新规则不再
    预先绑定某名玩家或某个座次，因此由本模块创建的状态始终将其保持为
    None。spy_path_pending 表示等待下一次实际发生的存活角色回合开始
    事件。
    """

    mode_variant: ModeVariant
    spy_path_choice: SpyPathChoice | None = None
    spy_path_pending: bool = False
    spy_path_locked: bool = False
    spy_path_effective_turn_player_id: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "mode_variant", _coerce_mode(self.mode_variant))
        if self.spy_path_choice is not None:
            object.__setattr__(
                self,
                "spy_path_choice",
                _coerce_spy_choice(self.spy_path_choice),
            )
        if not isinstance(self.spy_path_pending, bool):
            raise TypeError("择途待生效状态必须是布尔值")
        if not isinstance(self.spy_path_locked, bool):
            raise TypeError("择途锁定状态必须是布尔值")
        if self.spy_path_effective_turn_player_id is not None:
            ensure_int_at_least(
                self.spy_path_effective_turn_player_id,
                "旧版择途生效回合玩家标识",
                1,
            )


def initial_spy_path_state(mode_variant: ModeVariant | str) -> SpyPathState:
    return SpyPathState(_coerce_mode(mode_variant))


def can_choose_spy_path(
    mode_variant: ModeVariant | str,
    *,
    role_current: CurrentRole | str,
    player_alive: bool,
    alive_player_count: int,
    lord_or_loyalist_confirmed_dead: bool,
    already_locked: bool = False,
) -> bool:
    """判断仍为内奸的存活角色现在能否新作择途选择。"""

    mode = _coerce_mode(mode_variant)
    count = ensure_int_at_least(alive_player_count, "存活人数", 0)
    return (
        mode is ModeVariant.MOBILE_HEIR_AND_SPY_CHOICE
        and _coerce_role(role_current) is CurrentRole.SPY
        and bool(player_alive)
        and count > 4
        and bool(lord_or_loyalist_confirmed_dead)
        and not already_locked
    )


def counts_as_lord_or_loyalist_death_for_spy_path(
    role_current_at_death: CurrentRole | str,
    *,
    was_current_lord: bool = False,
) -> bool:
    """判断一次确认死亡是否满足择途所需的“主忠已有角色阵亡”。

    原主公在继位后死亡仍可由 ``was_current_lord`` 或其当时的主公身份
    记录；正式转忠者则按死亡时的当前忠臣身份判断。
    """

    if not isinstance(was_current_lord, bool):
        raise TypeError("是否为当前主公必须是布尔值")
    role = _coerce_role(role_current_at_death)
    return was_current_lord or role in {CurrentRole.LORD, CurrentRole.LOYALIST}


def next_living_player_after(
    living_seat_ring: LivingSeatRing,
    current_turn_player_id: int,
) -> int:
    """按当前正常座次顺序取得下一名存活角色，自动跳过死亡者。"""

    if not isinstance(living_seat_ring, LivingSeatRing):
        raise TypeError("存活座次环必须是 LivingSeatRing")
    order = living_seat_ring.turn_order_from(current_turn_player_id)
    if len(order) < 2:
        raise ValueError("至少需要两名存活角色才能确定下一名角色")
    return order[1]


def retarget_pending_spy_path_after_seat_death(
    state: SpyPathState,
    living_seat_ring: LivingSeatRing,
) -> SpyPathState:
    """兼容旧调用；死亡不会再触发择途生效目标的重新绑定。

    最新规则不预定某名玩家或座次。预计下家或连续角色死亡时没有回合
    开始事件，已锁定选择保持等待，自然顺延到下一次真实发生的存活角色
    回合开始。此函数只校验输入并清除可能来自旧状态的预定玩家字段。
    """

    if not isinstance(state, SpyPathState):
        raise TypeError("内奸择途状态必须是 SpyPathState")
    _ensure_variant(state.mode_variant)
    if not isinstance(living_seat_ring, LivingSeatRing):
        raise TypeError("存活座次环必须是 LivingSeatRing")
    return replace(state, spy_path_effective_turn_player_id=None)


def choose_spy_path(
    state: SpyPathState,
    choice: SpyPathChoice | str,
    *,
    role_current: CurrentRole | str,
    player_alive: bool,
    alive_player_count: int,
    lord_or_loyalist_confirmed_dead: bool,
    effective_turn_player_id: int | None = None,
) -> SpyPathState:
    """锁定择途结果；选择当时不改变身份。

    effective_turn_player_id 是旧接口的兼容参数。即使调用者仍传入，
    也只校验格式而不写入状态、不绑定玩家或座次。
    """

    if not isinstance(state, SpyPathState):
        raise TypeError("内奸择途状态必须是 SpyPathState")
    if state.spy_path_locked:
        raise ValueError("内奸择途结果已经锁定，不能取消或改选")
    if not can_choose_spy_path(
        state.mode_variant,
        role_current=role_current,
        player_alive=player_alive,
        alive_player_count=alive_player_count,
        lord_or_loyalist_confirmed_dead=lord_or_loyalist_confirmed_dead,
    ):
        raise ValueError("当前不满足内奸择途条件")
    if effective_turn_player_id is not None:
        ensure_int_at_least(
            effective_turn_player_id,
            "旧版择途生效回合玩家标识",
            1,
        )
    return SpyPathState(
        mode_variant=state.mode_variant,
        spy_path_choice=_coerce_spy_choice(choice),
        spy_path_pending=True,
        spy_path_locked=True,
        spy_path_effective_turn_player_id=None,
    )


@dataclass(frozen=True)
class AmbitionistMark:
    """独立资源标记；不是卡牌，也不属于任何卡牌区域。"""

    available: bool = True
    is_card: bool = False
    card_zone: None = None
    suit: None = None
    color: None = None
    rank: None = None

    @property
    def count(self) -> int:
        return 1 if self.available else 0


@dataclass(frozen=True)
class SpyPathApplication:
    applied: bool
    role_state_after: PlayerRoleState
    spy_path_state_after: SpyPathState
    public_conversion_event: bool
    converted_player_identity_revealed: bool
    spy_became_loyalist_announced: bool
    converted_loyalist_identity_revealed: bool
    ambitionist_identity_revealed: bool
    granted_skills: tuple[str, ...]
    ambitionist_mark: AmbitionistMark | None
    cancelled: bool = False
    cancellation_reason: str | None = None


def apply_spy_path_at_turn_start(
    state: SpyPathState,
    role_state: PlayerRoleState,
    *,
    turn_player_id: int,
    turn_player_alive: bool = True,
    chooser_alive: bool = True,
    alive_player_count: int | None = None,
    game_over: bool = False,
) -> SpyPathApplication:
    """在锁定后的下一次真实存活角色回合开始事件正式改变身份。

    不比较预定玩家标识或座次。turn_player_alive=False 表示该预计角色
    已经死亡、因而没有实际产生回合开始事件；此时保持等待。选择锁定后
    不再以存活人数或主忠死亡条件取消选择；alive_player_count 仅供调用
    方记录事件状态。若游戏已经结束或选择者已死亡，则取消待生效状态
    且不转化。
    """

    if not isinstance(state, SpyPathState):
        raise TypeError("内奸择途状态必须是 SpyPathState")
    _ensure_variant(state.mode_variant)
    if not isinstance(role_state, PlayerRoleState):
        raise TypeError("身份状态必须是 PlayerRoleState")
    ensure_int_at_least(turn_player_id, "当前回合玩家标识", 1)
    if not isinstance(turn_player_alive, bool):
        raise TypeError("当前回合玩家存活状态必须是布尔值")
    if not isinstance(chooser_alive, bool):
        raise TypeError("择途选择者存活状态必须是布尔值")
    if alive_player_count is not None:
        ensure_int_at_least(alive_player_count, "生效事件时存活人数", 0)
    if not isinstance(game_over, bool):
        raise TypeError("游戏结束状态必须是布尔值")

    def unchanged(
        state_after: SpyPathState,
        *,
        cancelled: bool = False,
        reason: str | None = None,
    ) -> SpyPathApplication:
        return SpyPathApplication(
            applied=False,
            role_state_after=role_state,
            spy_path_state_after=state_after,
            public_conversion_event=False,
            converted_player_identity_revealed=role_state.identity_revealed,
            spy_became_loyalist_announced=False,
            converted_loyalist_identity_revealed=False,
            ambitionist_identity_revealed=False,
            granted_skills=(),
            ambitionist_mark=None,
            cancelled=cancelled,
            cancellation_reason=reason,
        )

    if not state.spy_path_pending or not state.spy_path_locked:
        return unchanged(
            replace(state, spy_path_effective_turn_player_id=None)
        )
    if game_over:
        return unchanged(
            replace(
                state,
                spy_path_pending=False,
                spy_path_effective_turn_player_id=None,
            ),
            cancelled=True,
            reason="游戏已结束",
        )
    if not chooser_alive:
        return unchanged(
            replace(
                state,
                spy_path_pending=False,
                spy_path_effective_turn_player_id=None,
            ),
            cancelled=True,
            reason="择途选择者已死亡",
        )
    if not turn_player_alive:
        return unchanged(
            replace(state, spy_path_effective_turn_player_id=None)
        )
    if role_state.role_current is not CurrentRole.SPY:
        raise ValueError("只有尚未转化的内奸才能应用已锁定的择途结果")
    if state.spy_path_choice is None:
        raise ValueError("已锁定的择途状态缺少选择结果")

    completed = replace(
        state,
        spy_path_pending=False,
        spy_path_effective_turn_player_id=None,
    )
    if state.spy_path_choice is SpyPathChoice.LOYALIST:
        role_after = replace(
            role_state,
            role_current=CurrentRole.LOYALIST,
            identity_revealed=False,
        )
        return SpyPathApplication(
            applied=True,
            role_state_after=role_after,
            spy_path_state_after=completed,
            public_conversion_event=True,
            converted_player_identity_revealed=False,
            spy_became_loyalist_announced=True,
            converted_loyalist_identity_revealed=False,
            ambitionist_identity_revealed=False,
            granted_skills=(),
            ambitionist_mark=None,
        )

    role_after = replace(
        role_state,
        role_current=CurrentRole.AMBITIONIST,
        identity_revealed=True,
    )
    return SpyPathApplication(
        applied=True,
        role_state_after=role_after,
        spy_path_state_after=completed,
        public_conversion_event=True,
        converted_player_identity_revealed=True,
        spy_became_loyalist_announced=False,
        converted_loyalist_identity_revealed=False,
        ambitionist_identity_revealed=True,
        granted_skills=("飞扬", "跋扈"),
        ambitionist_mark=AmbitionistMark(),
    )


def ambitionist_mode_skills_active(alive_player_count: int) -> bool:
    """按用户确认实际表现动态检查飞扬、跋扈：至少三人存活。"""

    count = ensure_int_at_least(alive_player_count, "存活人数", 0)
    return count >= 3


def ordinary_card_effect_can_affect_ambitionist_mark() -> bool:
    """过河拆桥、顺手牵羊及普通牌区操作均不能影响该标记。"""

    return False


def _consume_mark(mark: AmbitionistMark) -> AmbitionistMark:
    if not isinstance(mark, AmbitionistMark):
        raise TypeError("野心家标记必须是 AmbitionistMark")
    if not mark.available:
        raise ValueError("野心家标记已经移去，不能再次使用")
    return replace(mark, available=False)


@dataclass(frozen=True)
class VirtualPeachUse:
    target_player_id: int
    mark_after: AmbitionistMark
    card_name: str = "桃"
    virtual_card: bool = True
    counts_as_card_use: bool = True
    counts_as_peach_use: bool = True
    recovery_amount: int = 1
    used_from_hand: bool = False
    physical_card_lost: bool = False
    counts_as_discard: bool = False
    suit: None = None
    color: None = None
    rank: None = None


def use_ambitionist_mark_as_peach(
    mark: AmbitionistMark,
    *,
    user_player_id: int,
    target_player_id: int,
    timing: VirtualPeachTiming | str,
    target_is_dying: bool = False,
    peach_use_is_legal: bool = True,
) -> VirtualPeachUse:
    """移去标记并完整视为使用虚拟桃，但不失去实体手牌。"""

    user = ensure_int_at_least(user_player_id, "野心家玩家标识", 1)
    target = ensure_int_at_least(target_player_id, "桃的目标玩家标识", 1)
    resolved_timing = _coerce_peach_timing(timing)
    if not peach_use_is_legal:
        raise ValueError("当前不满足普通桃的合法使用条件")
    if resolved_timing is VirtualPeachTiming.OWN_PLAY_PHASE and target != user:
        raise ValueError("自己的出牌阶段只能按普通桃规则对自己使用")
    if resolved_timing is VirtualPeachTiming.DYING_RESCUE and not target_is_dying:
        raise ValueError("濒死救援时目标必须正处于濒死状态")
    return VirtualPeachUse(target_player_id=target, mark_after=_consume_mark(mark))


@dataclass(frozen=True)
class MarkDrawResult:
    draw_count: int
    mark_after: AmbitionistMark
    counts_as_card_use: bool = False
    physical_card_lost: bool = False


def use_ambitionist_mark_to_draw_two(
    mark: AmbitionistMark,
    *,
    in_own_play_phase: bool,
) -> MarkDrawResult:
    """自己的出牌阶段移去标记摸两张，不视为使用卡牌。"""

    if not in_own_play_phase:
        raise ValueError("野心家标记摸两张只能在自己的出牌阶段使用")
    return MarkDrawResult(2, _consume_mark(mark))


@dataclass(frozen=True)
class VariantKillReward:
    identity_reward_available: bool
    identity_draw_count: int
    identity_reward_event_count: int
    standard_rebel_reward_suppressed: bool
    lord_killed_current_loyalist_penalty_applies: bool
    independent_skill_draw_count: int
    total_draw_count: int


def resolve_variant_identity_kill_reward(
    killer_role_current: CurrentRole | str,
    victim_role_current: CurrentRole | str,
    *,
    ambitionist_accepts_reward: bool = True,
    independent_skill_draw_count: int = 0,
) -> VariantKillReward:
    """计算限时变体的身份摸牌奖励，并阻止同一击杀叠加两次三张。

    独立武将技能摸牌单独保留，不受身份奖励去重影响。
    """

    killer = _coerce_role(killer_role_current)
    victim = _coerce_role(victim_role_current)
    skill_draw = ensure_int_at_least(
        independent_skill_draw_count, "独立武将技能摸牌数", 0
    )
    if killer is CurrentRole.AMBITIONIST:
        identity_draw = 3 if ambitionist_accepts_reward else 0
        return VariantKillReward(
            identity_reward_available=True,
            identity_draw_count=identity_draw,
            identity_reward_event_count=1,
            standard_rebel_reward_suppressed=victim is CurrentRole.REBEL,
            lord_killed_current_loyalist_penalty_applies=False,
            independent_skill_draw_count=skill_draw,
            total_draw_count=identity_draw + skill_draw,
        )
    if victim is CurrentRole.REBEL:
        return VariantKillReward(
            identity_reward_available=True,
            identity_draw_count=3,
            identity_reward_event_count=1,
            standard_rebel_reward_suppressed=False,
            lord_killed_current_loyalist_penalty_applies=False,
            independent_skill_draw_count=skill_draw,
            total_draw_count=3 + skill_draw,
        )
    lord_penalty = killer is CurrentRole.LORD and victim is CurrentRole.LOYALIST
    return VariantKillReward(
        identity_reward_available=False,
        identity_draw_count=0,
        identity_reward_event_count=0,
        standard_rebel_reward_suppressed=False,
        lord_killed_current_loyalist_penalty_applies=lord_penalty,
        independent_skill_draw_count=skill_draw,
        total_draw_count=skill_draw,
    )


def determine_variant_victory(
    roles_current: Mapping[int, CurrentRole | str],
    alive_players: Iterable[int],
    *,
    current_lord_player_id: int,
) -> VariantVictory:
    """始终使用当前身份和当前主公指针判断限时变体胜负。"""

    if not isinstance(roles_current, Mapping) or not roles_current:
        raise ValueError("当前身份映射不能为空")
    roles = {player: _coerce_role(role) for player, role in roles_current.items()}
    lord = ensure_int_at_least(current_lord_player_id, "当前主公玩家标识", 1)
    if lord not in roles:
        raise ValueError("当前主公必须存在于当前身份映射中")
    alive = frozenset(_tuple(alive_players, "存活玩家"))
    if not alive.issubset(roles):
        raise ValueError("存活玩家中包含没有当前身份记录的玩家")
    if lord in alive:
        alive_roles = {roles[player] for player in alive}
        if CurrentRole.AMBITIONIST in alive_roles:
            return VariantVictory.ONGOING
        if alive_roles.issubset({CurrentRole.LORD, CurrentRole.LOYALIST}):
            return VariantVictory.LORD_AND_LOYALISTS
        return VariantVictory.ONGOING
    if len(alive) == 1:
        sole_role = roles[next(iter(alive))]
        if sole_role is CurrentRole.SPY:
            return VariantVictory.SPY
        if sole_role is CurrentRole.AMBITIONIST:
            return VariantVictory.AMBITIONIST
    return VariantVictory.REBELS


@dataclass(frozen=True)
class VariantIdentityDeathResolution:
    """特殊玩法一次死亡的胜利检查与身份奖惩结果。"""

    victim_player_id: int
    victory: VariantVictory
    game_over: bool
    identity_reward_processed: bool
    identity_reward: VariantKillReward | None


def resolve_variant_identity_death(
    roles_current: Mapping[int, CurrentRole | str],
    alive_players_after_death: Iterable[int],
    *,
    current_lord_player_id: int,
    killer_player_id: int,
    victim_player_id: int,
    victory_prerequisites_completed: bool,
    ambitionist_accepts_reward: bool = True,
) -> VariantIdentityDeathResolution:
    """完成胜利前置状态后先查胜负，游戏继续时才处理身份奖惩。

    ``victory_prerequisites_completed`` 表示调用方已经完成濒死救援、
    当前真实身份确认、合法储君继位及其他直接决定胜利的状态更新。
    本函数只控制模式身份奖惩，不统一跳过或重排具体武将死亡技能。
    """

    if not isinstance(victory_prerequisites_completed, bool):
        raise TypeError("胜利前置状态完成标识必须是布尔值")
    if not victory_prerequisites_completed:
        raise ValueError("必须先完成濒死、当前身份与合法储君继位等胜利前置状态")
    if not isinstance(roles_current, Mapping) or not roles_current:
        raise ValueError("当前身份映射不能为空")
    killer = ensure_int_at_least(killer_player_id, "击杀者玩家标识", 1)
    victim = ensure_int_at_least(victim_player_id, "死亡玩家标识", 1)
    if killer not in roles_current:
        raise ValueError("击杀者必须存在于当前身份映射中")
    if victim not in roles_current:
        raise ValueError("死亡玩家必须存在于当前身份映射中")
    if not isinstance(ambitionist_accepts_reward, bool):
        raise TypeError("野心家奖励选择必须是布尔值")
    alive = frozenset(_tuple(alive_players_after_death, "死亡后的存活玩家"))
    if victim in alive:
        raise ValueError("已正式死亡的玩家不能仍在存活玩家集合中")

    victory = determine_variant_victory(
        roles_current,
        alive,
        current_lord_player_id=current_lord_player_id,
    )
    if victory is not VariantVictory.ONGOING:
        return VariantIdentityDeathResolution(
            victim_player_id=victim,
            victory=victory,
            game_over=True,
            identity_reward_processed=False,
            identity_reward=None,
        )

    reward = resolve_variant_identity_kill_reward(
        roles_current[killer],
        roles_current[victim],
        ambitionist_accepts_reward=ambitionist_accepts_reward,
    )
    return VariantIdentityDeathResolution(
        victim_player_id=victim,
        victory=victory,
        game_over=False,
        identity_reward_processed=True,
        identity_reward=reward,
    )


@dataclass(frozen=True)
class CurrentRoleDeathStep:
    player_id: int
    role_current_at_death: CurrentRole


@dataclass(frozen=True)
class VariantSequentialResult(Generic[S]):
    processed_steps: tuple[CurrentRoleDeathStep, ...]
    final_state: S
    stopped_by_game_over: bool


def resolve_variant_sequential_deaths(
    targets: Iterable[int],
    initial_state: S,
    current_role_getter: Callable[[S, int], CurrentRole | str],
    resolve_one_death: Callable[[S, int, CurrentRole], S],
    is_game_over: Callable[[S], bool],
) -> VariantSequentialResult[S]:
    """逐人读取当时的当前身份并完整处理死亡，胜负确定后立即停止。

    ``resolve_one_death`` 应先完成该玩家的濒死、当前身份、合法继位及
    其他胜利前置状态，再检查胜负；胜利成立时不执行身份击杀奖惩，
    只有游戏继续时才处理奖惩。具体武将死亡技能仍按其自身时序处理。
    """

    if not all(callable(item) for item in (current_role_getter, resolve_one_death, is_game_over)):
        raise TypeError("身份读取器、死亡结算器和游戏结束判断器必须可调用")
    state = initial_state
    steps: list[CurrentRoleDeathStep] = []
    stopped = bool(is_game_over(state))
    if not stopped:
        for target in _tuple(targets, "连续死亡目标"):
            player = ensure_int_at_least(target, "死亡玩家标识", 1)
            role = _coerce_role(current_role_getter(state, player))
            state = resolve_one_death(state, player, role)
            steps.append(CurrentRoleDeathStep(player, role))
            if is_game_over(state):
                stopped = True
                break
    return VariantSequentialResult(tuple(steps), state, stopped)


__all__ = [
    "LIMITED_MODE_VARIANT",
    "LIMITED_MODE_DECK_ID",
    "AmbitionistMark",
    "CardRegion",
    "CurrentRole",
    "CurrentRoleDeathStep",
    "HeirDeathResult",
    "HeirInformationView",
    "HeirSelectionState",
    "LordRegions",
    "LimitedModeMetadata",
    "MarkDrawResult",
    "ModeVariant",
    "PlayerRoleState",
    "RegionCardChoice",
    "SpyPathApplication",
    "SpyPathChoice",
    "SpyPathState",
    "SuccessionResult",
    "VariantFeatures",
    "VariantKillReward",
    "VariantIdentityDeathResolution",
    "VariantSequentialResult",
    "VariantVictory",
    "VirtualPeachTiming",
    "VirtualPeachUse",
    "ambitionist_mode_skills_active",
    "apply_spy_path_at_turn_start",
    "can_choose_spy_path",
    "can_heir_succeed",
    "counts_as_lord_or_loyalist_death_for_spy_path",
    "choose_spy_path",
    "determine_variant_victory",
    "expire_heir_selection",
    "finalize_old_lord_formal_death_after_succession",
    "finalize_old_lord_formal_death_without_succession",
    "initial_heir_selection_state",
    "initial_spy_path_state",
    "load_variant_features",
    "limited_mode_is_available",
    "limited_mode_metadata",
    "next_living_player_after",
    "ordinary_card_effect_can_affect_ambitionist_mark",
    "retarget_pending_spy_path_after_seat_death",
    "reveal_current_identity_after_confirmed_death",
    "resolve_heir_confirmed_death",
    "resolve_heir_succession_after_failed_rescue",
    "resolve_variant_identity_kill_reward",
    "resolve_variant_identity_death",
    "resolve_variant_sequential_deaths",
    "select_heir",
    "select_heir_in_turn",
    "use_ambitionist_mark_as_peach",
    "use_ambitionist_mark_to_draw_two",
    "view_heir_information",
]
