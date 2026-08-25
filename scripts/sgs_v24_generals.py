"""V2.4 增量武将的轻量规则状态机。

本模块只实现用户已确认且能用有限状态表达的边界，不是完整游戏引擎。
势·孙綝、势·辛宪英、SP郭女王和未上线的神吕布重制原型的基础体力
统一登记在 :mod:`scripts.sgs_general_rules`；这里不重复维护，也不会因建立
规则接口而自动加入任何正式候选池。
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Callable, Iterable, Sequence

from ._validation import ensure_int_at_least, make_rng
from .sgs_incremental_mechanics import (
    ActualZoneEntry,
    DamageContext,
    GainEventContext,
    GainTimeEffect,
    PendingGainCard,
    resolve_gain_time_queue,
)


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label}必须是非空字符串")
    return value.strip()


def _bool(value: object, label: str) -> bool:
    if not isinstance(value, bool):
        raise TypeError(f"{label}必须是布尔值")
    return value


def _items(values: Iterable[object], label: str) -> tuple[object, ...]:
    if values is None or isinstance(values, (str, bytes)):
        raise TypeError(f"{label}必须是可迭代对象")
    try:
        return tuple(values)
    except TypeError as exc:
        raise TypeError(f"{label}必须是可迭代对象") from exc


_SUIT_ALIASES = {
    "♠": "♠",
    "黑桃": "♠",
    "♥": "♥",
    "红桃": "♥",
    "♣": "♣",
    "梅花": "♣",
    "♦": "♦",
    "方块": "♦",
}


def _suit(value: object, label: str = "花色") -> str:
    raw = _text(value, label)
    try:
        return _SUIT_ALIASES[raw]
    except KeyError as exc:
        raise ValueError(f"{label}只能是黑桃、红桃、梅花或方块") from exc


class CardZone(str, Enum):
    HAND = "手牌区"
    EQUIPMENT = "装备区"
    JUDGMENT = "判定区"
    SPECIAL = "特殊区"
    DRAW_PILE = "牌堆"


def _zone(value: CardZone | str) -> CardZone:
    if isinstance(value, CardZone):
        return value
    try:
        return CardZone(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("卡牌区域无效") from exc


@dataclass(frozen=True)
class V24Card:
    card_id: str
    card_name: str
    suit: str | None = None
    zone: CardZone | str = CardZone.HAND
    category: str | None = None
    static_damage_card: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "card_id", _text(self.card_id, "卡牌编号"))
        object.__setattr__(self, "card_name", _text(self.card_name, "卡牌名"))
        if self.suit is not None:
            object.__setattr__(self, "suit", _suit(self.suit))
        object.__setattr__(self, "zone", _zone(self.zone))
        if self.category is not None:
            object.__setattr__(self, "category", _text(self.category, "卡牌类别"))
        _bool(self.static_damage_card, "静态伤害牌标识")


# ---------------------------------------------------------------------------
# 势·孙綝：逆固、戮连、乘势


@dataclass(frozen=True)
class NiguParticipant:
    player_id: str
    actual_distance: int
    has_card: bool
    chooses_to_give: bool
    given_card_id: str | None = None
    alive: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "player_id", _text(self.player_id, "逆固参与角色"))
        ensure_int_at_least(self.actual_distance, "与势·孙綝的实际距离", 0)
        _bool(self.has_card, "参与角色是否有牌")
        _bool(self.chooses_to_give, "参与角色是否选择交牌")
        _bool(self.alive, "参与角色存活状态")
        if self.given_card_id is not None:
            object.__setattr__(self, "given_card_id", _text(self.given_card_id, "交出牌编号"))
        if self.has_card and self.chooses_to_give and self.given_card_id is None:
            raise ValueError("有牌且选择交牌时必须提供交出牌编号")


@dataclass(frozen=True)
class NiguState:
    used_this_play_phase: bool = False
    damage_bonus_charges: int = 0

    def __post_init__(self) -> None:
        _bool(self.used_this_play_phase, "逆固本阶段使用状态")
        ensure_int_at_least(self.damage_bonus_charges, "逆固加伤额度", 0)


@dataclass(frozen=True)
class NiguResult:
    state_after: NiguState
    discarded_card_ids: tuple[str, ...]
    participants: tuple[str, ...]
    cards_given_face_down: tuple[str, ...]
    non_giver_ids: tuple[str, ...]
    attack_range_used: int


def start_nigu_play_phase(state: NiguState | None = None) -> NiguState:
    current = state or NiguState()
    if not isinstance(current, NiguState):
        raise TypeError("逆固状态必须使用 NiguState 表示")
    return replace(current, used_this_play_phase=False)


def resolve_nigu(
    state: NiguState,
    *,
    owner_id: str,
    discarded_cards: Sequence[V24Card],
    attack_range_after_discard: int,
    participants: Sequence[NiguParticipant],
) -> NiguResult:
    """支付弃牌后才读取攻击范围，并锁定所有人的同时交牌选择。"""

    if not isinstance(state, NiguState):
        raise TypeError("逆固状态必须使用 NiguState 表示")
    owner = _text(owner_id, "势·孙綝角色标识")
    if state.used_this_play_phase:
        raise ValueError("【逆固】每个出牌阶段限一次")
    if isinstance(discarded_cards, (str, bytes)) or not isinstance(discarded_cards, Sequence):
        raise TypeError("逆固弃牌必须是序列")
    discarded = tuple(discarded_cards)
    if not discarded:
        raise ValueError("【逆固】至少弃置一张牌，不能弃置零张")
    if len(discarded) > 4:
        raise ValueError("四种花色两两不同，逆固至多弃置四张牌")
    if any(not isinstance(card, V24Card) for card in discarded):
        raise TypeError("逆固弃牌必须使用 V24Card 表示")
    if any(card.zone not in {CardZone.HAND, CardZone.EQUIPMENT} for card in discarded):
        raise ValueError("【逆固】只能弃置手牌区或装备区内的牌")
    if any(card.suit is None for card in discarded):
        raise ValueError("【逆固】弃置牌必须具有已知花色")
    suits = tuple(card.suit for card in discarded)
    if len(suits) != len(set(suits)):
        raise ValueError("【逆固】弃置多张牌时花色必须两两不同")
    attack_range = ensure_int_at_least(attack_range_after_discard, "弃牌后的攻击范围", 0)

    if isinstance(participants, (str, bytes)) or not isinstance(participants, Sequence):
        raise TypeError("逆固角色选择必须是序列")
    candidates = tuple(participants)
    if any(not isinstance(item, NiguParticipant) for item in candidates):
        raise TypeError("逆固角色选择必须使用 NiguParticipant 表示")
    ids = tuple(item.player_id for item in candidates)
    if len(ids) != len(set(ids)):
        raise ValueError("逆固角色选择不能重复")

    eligible = tuple(
        item
        for item in candidates
        if item.alive and item.player_id != owner and item.actual_distance <= attack_range
    )
    given = tuple(
        item.given_card_id
        for item in eligible
        if item.has_card and item.chooses_to_give and item.given_card_id is not None
    )
    non_givers = tuple(
        item.player_id
        for item in eligible
        if not item.has_card or not item.chooses_to_give
    )
    after = NiguState(
        used_this_play_phase=True,
        damage_bonus_charges=state.damage_bonus_charges + len(non_givers),
    )
    return NiguResult(
        state_after=after,
        discarded_card_ids=tuple(card.card_id for card in discarded),
        participants=tuple(item.player_id for item in eligible),
        cards_given_face_down=given,
        non_giver_ids=non_givers,
        attack_range_used=attack_range,
    )


@dataclass(frozen=True)
class NiguDamageResult:
    state_after: NiguState
    bonus_applied: int
    actual_damage: int
    charge_consumed: bool
    prevented: bool


def apply_nigu_damage_charge(
    state: NiguState,
    *,
    base_damage: int,
    prevented: bool = False,
) -> NiguDamageResult:
    """每个独立伤害事件至多消耗一份额度；完全防止也不返还。"""

    if not isinstance(state, NiguState):
        raise TypeError("逆固状态必须使用 NiguState 表示")
    base = ensure_int_at_least(base_damage, "逆固处理前伤害", 0)
    blocked = _bool(prevented, "伤害是否被完全防止")
    consume = state.damage_bonus_charges > 0
    bonus = 1 if consume else 0
    after = replace(
        state,
        damage_bonus_charges=state.damage_bonus_charges - bonus,
    )
    return NiguDamageResult(after, bonus, 0 if blocked else base + bonus, consume, blocked)


@dataclass(frozen=True)
class LulianTarget:
    player_id: str
    hp: int
    equipment_count: int
    alive: bool = True
    in_game: bool = True
    chained: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "player_id", _text(self.player_id, "戮连目标"))
        if isinstance(self.hp, bool) or not isinstance(self.hp, int):
            raise TypeError("戮连目标体力必须是整数")
        ensure_int_at_least(self.equipment_count, "戮连目标装备数", 0)
        _bool(self.alive, "戮连目标存活状态")
        _bool(self.in_game, "戮连目标在场状态")
        _bool(self.chained, "戮连目标横置状态")


@dataclass(frozen=True)
class LulianUseContext:
    category: str
    from_owner_hand_before_use: bool = True
    actually_used: bool = True
    only_played: bool = False
    pure_virtual: bool = False
    from_special_zone: bool = False
    used_other_players_hand: bool = False
    resolution_completed: bool = True
    same_category_hand_count_after: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "category", _text(self.category, "实际使用牌类别"))
        for name in (
            "from_owner_hand_before_use",
            "actually_used",
            "only_played",
            "pure_virtual",
            "from_special_zone",
            "used_other_players_hand",
            "resolution_completed",
        ):
            _bool(getattr(self, name), name)
        ensure_int_at_least(self.same_category_hand_count_after, "结算后同类别手牌数", 0)


@dataclass(frozen=True)
class LulianResult:
    triggered: bool
    reason: str
    surviving_target_ids: tuple[str, ...]
    hp_condition_met: bool
    equipment_condition_met: bool
    targets_after: tuple[LulianTarget, ...]
    draw_count: int
    chengshi_granted: bool
    chengshi_legal_targets: tuple[str, ...]


def legal_chengshi_targets(characters: Sequence[LulianTarget]) -> tuple[str, ...]:
    if isinstance(characters, (str, bytes)) or not isinstance(characters, Sequence):
        raise TypeError("乘势全场角色必须是序列")
    if any(not isinstance(item, LulianTarget) for item in characters):
        raise TypeError("乘势角色必须使用 LulianTarget 表示")
    alive = tuple(item for item in characters if item.alive and item.in_game)
    if not alive:
        return ()
    minimum = min(item.hp for item in alive)
    return tuple(item.player_id for item in alive if item.hp != minimum)


def resolve_lulian(
    context: LulianUseContext,
    *,
    owner_hp: int,
    owner_equipment_count: int,
    original_targets: Sequence[LulianTarget],
    all_alive_characters: Sequence[LulianTarget],
) -> LulianResult:
    """结算完原手牌后锁定类别归零，再过滤目标并依次处理两项条件。"""

    if not isinstance(context, LulianUseContext):
        raise TypeError("戮连用牌上下文必须使用 LulianUseContext 表示")
    if isinstance(owner_hp, bool) or not isinstance(owner_hp, int):
        raise TypeError("势·孙綝体力必须是整数")
    owner_equip = ensure_int_at_least(owner_equipment_count, "势·孙綝装备数", 0)
    if isinstance(original_targets, (str, bytes)) or not isinstance(original_targets, Sequence):
        raise TypeError("戮连原目标必须是序列")
    targets = tuple(original_targets)
    if any(not isinstance(item, LulianTarget) for item in targets):
        raise TypeError("戮连原目标必须使用 LulianTarget 表示")
    if len({item.player_id for item in targets}) != len(targets):
        raise ValueError("戮连原目标不能重复")

    eligibility = (
        context.from_owner_hand_before_use
        and context.actually_used
        and not context.only_played
        and not context.pure_virtual
        and not context.from_special_zone
        and not context.used_other_players_hand
        and context.resolution_completed
        and context.same_category_hand_count_after == 0
    )
    surviving = tuple(item for item in targets if item.alive and item.in_game)
    if not eligibility or not surviving:
        return LulianResult(
            False,
            "触发牌来源、动作、结算、类别归零或存活目标条件不满足",
            tuple(item.player_id for item in surviving),
            False,
            False,
            surviving,
            0,
            False,
            (),
        )

    hp_condition = any(item.hp <= owner_hp for item in surviving)
    equipment_condition = any(item.equipment_count <= owner_equip for item in surviving)
    after = tuple(replace(item, chained=True) if hp_condition else item for item in surviving)
    full = hp_condition and equipment_condition
    legal = legal_chengshi_targets(all_alive_characters) if full else ()
    return LulianResult(
        True,
        "原牌完成结算、类别归零并已过滤死亡目标",
        tuple(item.player_id for item in surviving),
        hp_condition,
        equipment_condition,
        after,
        1 if equipment_condition else 0,
        full,
        legal,
    )


# ---------------------------------------------------------------------------
# 势·辛宪英：清识、诫节


@dataclass(frozen=True)
class QingshiResult:
    draw_by_owner: int
    draw_by_target: int
    discarded_by_owner: tuple[str, ...]
    discarded_by_target: tuple[str, ...]
    same_camp_result_public: bool


def qingshi_trigger_count(*, actual_damage: int, survived_after_rescue: bool) -> int:
    damage = ensure_int_at_least(actual_damage, "清识对应实际伤害", 0)
    survived = _bool(survived_after_rescue, "辛宪英是否在救援后存活")
    return 1 if damage > 0 and survived else 0


def _select_area_card(cards: Sequence[V24Card], selected_id: str | None, label: str) -> tuple[str, ...]:
    eligible = tuple(card for card in cards if card.zone in {CardZone.HAND, CardZone.EQUIPMENT})
    if not eligible:
        return ()
    if selected_id is None:
        return (eligible[0].card_id,)
    selected = _text(selected_id, label)
    if selected not in {card.card_id for card in eligible}:
        raise ValueError(f"{label}不在可弃置的手牌区或装备区牌中")
    return (selected,)


def resolve_qingshi(
    *,
    owner_id: str,
    target_id: str,
    same_camp: bool,
    owner_cards: Sequence[V24Card] = (),
    target_cards: Sequence[V24Card] = (),
    owner_discard_card_id: str | None = None,
    target_discard_card_id: str | None = None,
) -> QingshiResult:
    owner = _text(owner_id, "辛宪英角色标识")
    target = _text(target_id, "清识目标")
    same = _bool(same_camp, "是否同阵营")
    own = tuple(owner_cards)
    other = tuple(target_cards)
    if any(not isinstance(card, V24Card) for card in own + other):
        raise TypeError("清识可弃置牌必须使用 V24Card 表示")
    if target == owner:
        if not same:
            raise ValueError("辛宪英与自己必定视为同阵营")
        return QingshiResult(2, 0, (), (), True)
    if same:
        return QingshiResult(1, 1, (), (), True)
    return QingshiResult(
        0,
        0,
        _select_area_card(own, owner_discard_card_id, "辛宪英弃置牌"),
        _select_area_card(other, target_discard_card_id, "目标弃置牌"),
        False,
    )


class JiejieSelection(str, Enum):
    SPADE = "♠"
    HEART = "♥"
    CLUB = "♣"
    DIAMOND = "♦"
    CANCEL = "取消"


def _jiejie_selection(value: JiejieSelection | str) -> JiejieSelection:
    if isinstance(value, JiejieSelection):
        return value
    if value == "取消":
        return JiejieSelection.CANCEL
    try:
        return JiejieSelection(_suit(value, "诫节选择"))
    except (TypeError, ValueError) as exc:
        raise ValueError("诫节只能选择四种花色之一或取消") from exc


@dataclass(frozen=True)
class JiejieViewRecord:
    player_id: str
    play_phase_id: str
    original_suit_count: int
    selection: JiejieSelection
    forced_qingshi: bool


@dataclass(frozen=True)
class JiejieRoundState:
    current_max_suit_count: int = 0
    forced_qingshi_used: int = 0
    used_play_phase_ids: frozenset[str] = field(default_factory=frozenset)
    view_records: tuple[JiejieViewRecord, ...] = ()

    def __post_init__(self) -> None:
        ensure_int_at_least(self.current_max_suit_count, "诫节本轮最高花色数", 0)
        used = ensure_int_at_least(self.forced_qingshi_used, "诫节本轮强制清识次数", 0)
        if used > 2:
            raise ValueError("诫节每轮强制清识次数不能超过两次")
        object.__setattr__(
            self,
            "used_play_phase_ids",
            frozenset(_text(item, "诫节出牌阶段标识") for item in self.used_play_phase_ids),
        )
        if any(not isinstance(item, JiejieViewRecord) for item in self.view_records):
            raise TypeError("诫节观看记录必须使用 JiejieViewRecord 表示")


@dataclass(frozen=True)
class JiejieResult:
    state_after: JiejieRoundState
    original_suit_count: int
    selection: JiejieSelection
    discarded_card_ids: tuple[str, ...]
    remaining_hand: tuple[V24Card, ...]
    gained_card: V24Card | None
    remaining_draw_pile: tuple[V24Card, ...]
    unlimited_suit: str | None
    forced_qingshi: bool
    forced_qingshi_target_id: str | None


def resolve_jiejie(
    state: JiejieRoundState,
    *,
    current_player_id: str,
    play_phase_id: str,
    viewed_hand: Sequence[V24Card],
    selection: JiejieSelection | str,
    draw_pile: Sequence[V24Card] = (),
    seed: object | None = None,
) -> JiejieResult:
    """观看时记录原始花色数；选择或取消后再检查严格递增与两次额度。"""

    if not isinstance(state, JiejieRoundState):
        raise TypeError("诫节轮状态必须使用 JiejieRoundState 表示")
    player = _text(current_player_id, "当前回合角色")
    phase = _text(play_phase_id, "独立出牌阶段标识")
    if phase in state.used_play_phase_ids:
        raise ValueError("每名角色的每个独立出牌阶段限发动一次【诫节】")
    if isinstance(viewed_hand, (str, bytes)) or not isinstance(viewed_hand, Sequence):
        raise TypeError("诫节观看手牌必须是序列")
    hand = tuple(viewed_hand)
    if not hand:
        raise ValueError("当前回合角色没有手牌，不能发动【诫节】")
    if any(not isinstance(card, V24Card) or card.zone is not CardZone.HAND for card in hand):
        raise ValueError("诫节观看对象必须全部是普通手牌")
    if any(card.suit is None for card in hand):
        raise ValueError("诫节需要已知手牌花色，不能把空花色自动归类")
    pile = tuple(draw_pile)
    if any(not isinstance(card, V24Card) or card.zone is not CardZone.DRAW_PILE for card in pile):
        raise ValueError("诫节缺失花色检索只读取当前牌堆")

    choice = _jiejie_selection(selection)
    original_count = len({card.suit for card in hand})
    discarded: tuple[str, ...] = ()
    remaining = hand
    gained: V24Card | None = None
    remaining_pile = pile
    unlimited: str | None = None
    if choice is not JiejieSelection.CANCEL:
        selected_suit = choice.value
        if any(card.suit == selected_suit for card in hand):
            discarded = tuple(card.card_id for card in hand if card.suit != selected_suit)
            remaining = tuple(card for card in hand if card.suit == selected_suit)
            unlimited = selected_suit
        else:
            indices = [index for index, card in enumerate(pile) if card.suit == selected_suit]
            if indices:
                selected_index = make_rng(seed).choice(indices)
                gained = replace(pile[selected_index], zone=CardZone.HAND)
                remaining_pile = pile[:selected_index] + pile[selected_index + 1 :]

    strictly_higher = original_count > state.current_max_suit_count
    forced = strictly_higher and state.forced_qingshi_used < 2
    record = JiejieViewRecord(player, phase, original_count, choice, forced)
    after = JiejieRoundState(
        current_max_suit_count=max(state.current_max_suit_count, original_count),
        forced_qingshi_used=state.forced_qingshi_used + int(forced),
        used_play_phase_ids=state.used_play_phase_ids | {phase},
        view_records=state.view_records + (record,),
    )
    return JiejieResult(
        state_after=after,
        original_suit_count=original_count,
        selection=choice,
        discarded_card_ids=discarded,
        remaining_hand=remaining,
        gained_card=gained,
        remaining_draw_pile=remaining_pile,
        unlimited_suit=unlimited,
        forced_qingshi=forced,
        forced_qingshi_target_id=player if forced else None,
    )


@dataclass(frozen=True)
class JiejieUsePermission:
    ignores_card_use_limit: bool
    ignores_timing: bool = False
    ignores_target_rule: bool = False
    ignores_distance: bool = False
    ignores_other_conditions: bool = False


def jiejie_use_permission(
    *,
    unlimited_suit: str | None,
    actual_used_card_suit: str | None,
) -> JiejieUsePermission:
    """只解除所选花色牌自身的次数限制，不产生其他合法性覆盖。"""

    if unlimited_suit is None or actual_used_card_suit is None:
        return JiejieUsePermission(False)
    return JiejieUsePermission(_suit(unlimited_suit) == _suit(actual_used_card_suit))


# ---------------------------------------------------------------------------
# SP郭女王：易宠、雀、诬诽


@dataclass(frozen=True)
class BirdMarkState:
    guo_nuwang_id: str
    holder_id: str
    designated_suit: str
    expires_at: str
    interception_pending: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "guo_nuwang_id", _text(self.guo_nuwang_id, "SP郭女王角色标识"))
        object.__setattr__(self, "holder_id", _text(self.holder_id, "雀标记角色"))
        if self.holder_id == self.guo_nuwang_id:
            raise ValueError("【易宠】只能选择一名其他角色")
        object.__setattr__(self, "designated_suit", _suit(self.designated_suit, "雀指定花色"))
        object.__setattr__(self, "expires_at", _text(self.expires_at, "雀标记到期时点"))
        _bool(self.interception_pending, "雀花色拦截资格")


@dataclass(frozen=True)
class YichongResult:
    bird_state: BirdMarkState
    equipment_cards_gained: tuple[V24Card, ...]
    random_hand_card_gained: V24Card | None
    target_hand_after: tuple[V24Card, ...]
    target_equipment_after: tuple[V24Card, ...]
    previous_bird_transferred: bool


def resolve_yichong(
    *,
    guo_nuwang_id: str,
    target_id: str,
    designated_suit: str,
    target_hand: Sequence[V24Card] = (),
    target_equipment: Sequence[V24Card] = (),
    previous_bird: BirdMarkState | None = None,
    expires_at: str = "SP郭女王下个回合开始",
    seed: object | None = None,
) -> YichongResult:
    guo = _text(guo_nuwang_id, "SP郭女王角色标识")
    target = _text(target_id, "易宠目标")
    if target == guo:
        raise ValueError("【易宠】不能选择SP郭女王自己")
    suit = _suit(designated_suit, "易宠指定花色")
    hand = tuple(target_hand)
    equipment = tuple(target_equipment)
    if any(not isinstance(card, V24Card) or card.zone is not CardZone.HAND for card in hand):
        raise ValueError("易宠手牌输入必须全部来自目标手牌区")
    if any(not isinstance(card, V24Card) or card.zone is not CardZone.EQUIPMENT for card in equipment):
        raise ValueError("易宠装备输入必须全部来自目标装备区")

    gained_equipment = tuple(card for card in equipment if card.suit == suit)
    matching_hand = tuple(card for card in hand if card.suit == suit)
    random_hand = make_rng(seed).choice(matching_hand) if matching_hand else None
    gained_ids = {card.card_id for card in gained_equipment}
    if random_hand is not None:
        gained_ids.add(random_hand.card_id)
    state = BirdMarkState(guo, target, suit, expires_at, True)
    return YichongResult(
        bird_state=state,
        equipment_cards_gained=tuple(replace(card, zone=CardZone.HAND) for card in gained_equipment),
        random_hand_card_gained=(replace(random_hand, zone=CardZone.HAND) if random_hand else None),
        target_hand_after=tuple(card for card in hand if card.card_id not in gained_ids),
        target_equipment_after=tuple(card for card in equipment if card.card_id not in gained_ids),
        previous_bird_transferred=previous_bird is not None,
    )


@dataclass(frozen=True)
class BirdGainResult:
    bird_state_after: BirdMarkState
    intercepted_card_id: str | None
    original_gain_time_seen_card_ids: tuple[str, ...]
    effect_order: tuple[str, ...]
    actual_zone_entries: tuple[ActualZoneEntry, ...]


def resolve_bird_gain_event(
    state: BirdMarkState,
    *,
    original_recipient_id: str,
    pending_cards: Sequence[PendingGainCard],
    actor_order: Sequence[str],
) -> BirdGainResult:
    """在实际入区前按当前角色顺序处理原目标获得时效果与易宠拦截。"""

    if not isinstance(state, BirdMarkState):
        raise TypeError("雀标记必须使用 BirdMarkState 表示")
    recipient = _text(original_recipient_id, "原定获得者")
    intercepted: list[str] = []

    def original_gain_time(_context: GainEventContext) -> None:
        return None

    def yichong_interception(context: GainEventContext) -> None:
        if recipient != state.holder_id or not state.interception_pending:
            return
        candidates = [
            card
            for card in context.pending_cards
            if card.suit is not None and _suit(card.suit) == state.designated_suit
        ]
        if not candidates:
            return
        selected = candidates[0]
        context.redirect_card(
            selected.card_id,
            recipient_id=state.guo_nuwang_id,
            zone="手牌区",
        )
        intercepted.append(selected.card_id)

    effects = (
        GainTimeEffect(recipient, "original_recipient_gain_time", original_gain_time),
        GainTimeEffect(state.guo_nuwang_id, "yichong_interception", yichong_interception),
    )
    resolved = resolve_gain_time_queue(
        original_recipient_id=recipient,
        pending_cards=pending_cards,
        actor_order=actor_order,
        effects=effects,
    )
    seen = next(
        observation.pending_card_ids
        for observation in resolved.observations
        if observation.effect_id == "original_recipient_gain_time"
    )
    after = replace(state, interception_pending=False) if intercepted else state
    return BirdGainResult(
        bird_state_after=after,
        intercepted_card_id=intercepted[0] if intercepted else None,
        original_gain_time_seen_card_ids=seen,
        effect_order=resolved.effect_order,
        actual_zone_entries=resolved.actual_zone_entries,
    )


def clear_bird_when_holder_leaves(
    state: BirdMarkState | None,
    *,
    leaving_player_id: str,
) -> BirdMarkState | None:
    if state is None:
        return None
    if not isinstance(state, BirdMarkState):
        raise TypeError("雀标记必须使用 BirdMarkState 或 None 表示")
    return None if state.holder_id == _text(leaving_player_id, "离场角色") else state


_SLASH_NAMES = frozenset({"杀", "火杀", "雷杀"})
_NORMAL_DAMAGE_TRICKS = frozenset({"决斗", "火攻", "南蛮入侵", "万箭齐发"})


def resolve_wufei_damage_context(
    *,
    guo_nuwang_id: str,
    bird_state: BirdMarkState | None,
    bird_holder_alive: bool,
    damage_card_name: str,
    damage_target_id: str,
    card_type: str,
) -> DamageContext:
    """每个独立伤害事件即将造成前重新判断雀是否仍可替换来源。"""

    guo = _text(guo_nuwang_id, "SP郭女王角色标识")
    name = _text(damage_card_name, "伤害牌名")
    target = _text(damage_target_id, "伤害目标")
    kind = _text(card_type, "伤害牌类别")
    alive = _bool(bird_holder_alive, "雀角色是否存活")
    eligible = name in _SLASH_NAMES or (
        name in _NORMAL_DAMAGE_TRICKS and kind == "伤害类普通锦囊"
    )
    replace_source = bird_state is not None and alive and eligible
    source = bird_state.holder_id if replace_source else guo
    return DamageContext(
        card_user_id=guo,
        damage_source_id=source,
        damage_card_name=name,
        damage_target_id=target,
        card_type=kind,
        skill_activator_id=guo,
        equipment_owner_id=guo,
        source_replaced=replace_source,
    )


@dataclass(frozen=True)
class WufeiAfterDamageResult:
    eligible: bool
    activated: bool
    target_id: str | None
    damage_amount: int
    damage_source_id: None = None
    damage_type: str = "无属性"


def resolve_wufei_after_damage(
    *,
    guo_alive_after_rescue: bool,
    guo_hp_after_damage: int,
    bird_state: BirdMarkState | None,
    bird_holder_alive: bool,
    bird_holder_hp: int,
    activate: bool,
) -> WufeiAfterDamageResult:
    alive = _bool(guo_alive_after_rescue, "郭女王救援后是否存活")
    bird_alive = _bool(bird_holder_alive, "雀角色是否存活")
    chosen = _bool(activate, "是否发动诬诽后半段")
    if isinstance(guo_hp_after_damage, bool) or not isinstance(guo_hp_after_damage, int):
        raise TypeError("郭女王受伤后体力必须是整数")
    if isinstance(bird_holder_hp, bool) or not isinstance(bird_holder_hp, int):
        raise TypeError("雀角色体力必须是整数")
    eligible = (
        alive
        and bird_state is not None
        and bird_alive
        and bird_holder_hp > 3
        and bird_holder_hp > guo_hp_after_damage
    )
    return WufeiAfterDamageResult(
        eligible=eligible,
        activated=eligible and chosen,
        target_id=bird_state.holder_id if eligible and chosen and bird_state else None,
        damage_amount=1 if eligible and chosen else 0,
    )


# ---------------------------------------------------------------------------
# 神吕布重制原型：仅实验测试池


@dataclass(frozen=True)
class ShenLubuReworkState:
    rage: int = 2
    wuqian_targets: frozenset[str] = field(default_factory=frozenset)
    wushuang_active: bool = False
    shenfen_used_this_play_phase: bool = False
    face_up: bool = True

    def __post_init__(self) -> None:
        ensure_int_at_least(self.rage, "暴怒", 0)
        object.__setattr__(
            self,
            "wuqian_targets",
            frozenset(_text(item, "无前目标") for item in self.wuqian_targets),
        )
        _bool(self.wushuang_active, "无双状态")
        _bool(self.shenfen_used_this_play_phase, "神愤本阶段使用状态")
        _bool(self.face_up, "武将牌正面朝上状态")

    @property
    def dynamic_x(self) -> int:
        return len(self.wuqian_targets)

    @property
    def bonus_slash_limit(self) -> int:
        return self.dynamic_x


def gain_rage_from_damage(
    state: ShenLubuReworkState,
    *,
    damage_dealt: int = 0,
    damage_received: int = 0,
) -> ShenLubuReworkState:
    if not isinstance(state, ShenLubuReworkState):
        raise TypeError("神吕布状态必须使用 ShenLubuReworkState 表示")
    dealt = ensure_int_at_least(damage_dealt, "实际造成伤害", 0)
    received = ensure_int_at_least(damage_received, "实际受到伤害", 0)
    return replace(state, rage=state.rage + dealt + received)


class WumouAction(str, Enum):
    USE = "使用"
    PLAY = "打出"


@dataclass(frozen=True)
class WumouTrick:
    card_id: str
    card_name: str
    is_normal_trick: bool
    static_damage_card: bool
    target_template: str
    distance_rule: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "card_id", _text(self.card_id, "无谋实体牌编号"))
        object.__setattr__(self, "card_name", _text(self.card_name, "无谋实体锦囊名"))
        _bool(self.is_normal_trick, "是否普通锦囊")
        _bool(self.static_damage_card, "实体牌静态伤害分类")
        object.__setattr__(self, "target_template", _text(self.target_template, "原锦囊目标模板"))
        object.__setattr__(self, "distance_rule", _text(self.distance_rule, "原锦囊距离规则"))


@dataclass(frozen=True)
class WumouConversionResult:
    legal: bool
    reason: str
    physical_card_name: str
    actual_card_name: str
    action: WumouAction
    target_ids: tuple[str, ...]
    target_template: str
    distance_rule: str
    uses_attack_range: bool | None
    can_target_self: bool | None
    consumes_slash_use_limit: bool
    actual_use_is_damage_card: bool
    physical_static_damage_card: bool
    legality_externally_verified: bool = False


def convert_wumou_trick(
    card: WumouTrick,
    *,
    action: WumouAction | str,
    owner_id: str,
    original_legal_target_ids: Sequence[str] = (),
    all_player_ids: Sequence[str] = (),
    response_requires_slash: bool = False,
    borrowed_sword_relation_exists: bool | None = None,
    original_legality_verified: bool = False,
    uses_attack_range: bool | None = None,
    can_target_self: bool | None = None,
) -> WumouConversionResult:
    if not isinstance(card, WumouTrick):
        raise TypeError("无谋转化牌必须使用 WumouTrick 表示")
    if not card.is_normal_trick:
        raise ValueError("【无谋】只能转换普通锦囊牌")
    try:
        resolved_action = action if isinstance(action, WumouAction) else WumouAction(action)
    except (TypeError, ValueError) as exc:
        raise ValueError("无谋动作只能是使用或打出") from exc
    owner = _text(owner_id, "神吕布角色标识")
    targets = tuple(_text(item, "原锦囊合法目标") for item in original_legal_target_ids)
    players = tuple(_text(item, "当前玩家") for item in all_player_ids)
    if len(targets) != len(set(targets)) or len(players) != len(set(players)):
        raise ValueError("无谋目标或当前玩家不能重复")
    response_ok = _bool(response_requires_slash, "当前响应窗口是否需要杀")
    borrowed_ok = (
        None
        if borrowed_sword_relation_exists is None
        else _bool(borrowed_sword_relation_exists, "借刀杀人武器关系是否合法")
    )
    externally_verified = _bool(original_legality_verified, "原锦囊目标与合法性是否已由外部核验")
    attack_range_fact = (
        None
        if uses_attack_range is None
        else _bool(uses_attack_range, "无谋转化杀是否使用攻击范围")
    )
    self_target_fact = (
        None
        if can_target_self is None
        else _bool(can_target_self, "无谋转化杀是否可以指定自己")
    )

    legal = True
    reason = "沿用原普通锦囊的目标模板和距离规则"
    actual_targets = targets
    if resolved_action is WumouAction.PLAY:
        legal = response_ok
        actual_targets = ()
        reason = "当前响应窗口需要打出杀" if legal else "当前没有需要打出杀的合法响应窗口"
    else:
        if externally_verified and not targets:
            legal = False
            actual_targets = ()
            reason = "当前没有外部已核验的原锦囊目标"
        elif players and owner not in players:
            legal = False
            actual_targets = ()
            reason = "神吕布不在调用方提供的当前玩家集合中"
        elif players and any(target not in players for target in targets):
            legal = False
            actual_targets = ()
            reason = "原锦囊目标不在调用方提供的当前玩家集合中"
        elif card.target_template == "borrowed_sword_relation" and borrowed_ok is not True:
            legal = False
            actual_targets = ()
            reason = (
                "当前不存在装备武器牌的合法借刀目标关系"
                if borrowed_ok is False
                else "借刀杀人的目标关系尚未由外部核验"
            )
        elif self_target_fact is False and owner in targets:
            legal = False
            actual_targets = ()
            reason = "调用方明确确认本次无谋转化杀不能指定自己"
        elif not externally_verified:
            legal = False
            actual_targets = ()
            reason = "攻击范围、自身目标和特殊锦囊逐牌合法性待外部核验"
        else:
            legal = True
            actual_targets = targets
            reason = "使用外部已核验的原普通锦囊目标"
    return WumouConversionResult(
        legal=legal,
        reason=reason,
        physical_card_name=card.card_name,
        actual_card_name="杀",
        action=resolved_action,
        target_ids=actual_targets,
        target_template=card.target_template,
        distance_rule=card.distance_rule,
        uses_attack_range=attack_range_fact,
        can_target_self=(
            True if legal and owner in actual_targets else self_target_fact
        ),
        consumes_slash_use_limit=legal and resolved_action is WumouAction.USE,
        actual_use_is_damage_card=legal,
        physical_static_damage_card=card.static_damage_card,
        legality_externally_verified=legal and (
            response_ok if resolved_action is WumouAction.PLAY else externally_verified
        ),
    )


def activate_wuqian(
    state: ShenLubuReworkState,
    *,
    target_id: str,
) -> ShenLubuReworkState:
    if not isinstance(state, ShenLubuReworkState):
        raise TypeError("神吕布状态必须使用 ShenLubuReworkState 表示")
    target = _text(target_id, "无前目标")
    if state.rage < 2:
        raise ValueError("发动【无前】需要移去两个暴怒")
    if target in state.wuqian_targets:
        raise ValueError("同一目标能否重复发动【无前】待核验，当前接口不作合法性推断")
    return replace(
        state,
        rage=state.rage - 2,
        wuqian_targets=state.wuqian_targets | {target},
        wushuang_active=True,
    )


def remove_wuqian_target(
    state: ShenLubuReworkState,
    *,
    target_id: str,
) -> ShenLubuReworkState:
    if not isinstance(state, ShenLubuReworkState):
        raise TypeError("神吕布状态必须使用 ShenLubuReworkState 表示")
    _text(target_id, "离场无前目标")
    raise ValueError("无前目标死亡或离场后的标记处理待核验，当前接口不作推断")


def is_shen_lubu_damage_card(card: V24Card) -> bool:
    """读取现有静态分类，并强制纳入 B 层实测确认的【闪电】。"""

    if not isinstance(card, V24Card):
        raise TypeError("神吕布伤害牌分类必须使用 V24Card 表示")
    return card.static_damage_card or card.card_name == "闪电"


@dataclass(frozen=True)
class WuqianDamageResult:
    state_after: ShenLubuReworkState
    total_actual_damage: int
    cleared_all: bool


def resolve_wuqian_damage_card_completion(
    state: ShenLubuReworkState,
    *,
    is_damage_card_use: bool,
    actual_damage_by_target: Sequence[int],
    damage_card_name: str | None = None,
) -> WuqianDamageResult:
    if not isinstance(state, ShenLubuReworkState):
        raise TypeError("神吕布状态必须使用 ShenLubuReworkState 表示")
    damage_use = _bool(is_damage_card_use, "是否使用伤害牌")
    if damage_card_name is not None:
        name = _text(damage_card_name, "本次使用牌名")
        damage_use = damage_use or name == "闪电"
    damages = tuple(
        ensure_int_at_least(value, "单个目标实际伤害", 0)
        for value in actual_damage_by_target
    )
    if damage_use and not damages:
        raise ValueError("伤害牌结算尚无实际伤害结果，不能判定【无前】是否结束")
    total = sum(damages)
    cleared = bool(state.wuqian_targets) and damage_use and total == 0
    after = (
        replace(state, wuqian_targets=frozenset(), wushuang_active=False)
        if cleared
        else state
    )
    return WuqianDamageResult(after, total, cleared)


class WushuangResponseKind(str, Enum):
    SLASH_JINK = "杀的闪响应"
    DUEL_SLASH = "决斗的杀响应"


@dataclass(frozen=True)
class WushuangVariantResponse:
    kind: WushuangResponseKind | str
    responder_id: str
    required_count: int
    provided_count: int = 0

    def __post_init__(self) -> None:
        try:
            kind = self.kind if isinstance(self.kind, WushuangResponseKind) else WushuangResponseKind(self.kind)
        except (TypeError, ValueError) as exc:
            raise ValueError("无双※响应类型无效") from exc
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "responder_id", _text(self.responder_id, "无双※响应角色"))
        required = ensure_int_at_least(self.required_count, "无双※所需响应牌数", 1)
        provided = ensure_int_at_least(self.provided_count, "无双※已提供响应牌数", 0)
        if required not in (1, 2):
            raise ValueError("无双※所需响应牌数只能是一张或两张")
        if provided > required:
            raise ValueError("无双※已提供响应牌数不能超过所需数量")

    @property
    def required_card_name(self) -> str:
        return "闪" if self.kind is WushuangResponseKind.SLASH_JINK else "杀"

    @property
    def remaining_count(self) -> int:
        return self.required_count - self.provided_count

    @property
    def complete(self) -> bool:
        return self.remaining_count == 0


def start_wushuang_slash_response(
    state: ShenLubuReworkState,
    *,
    shen_lubu_id: str,
    slash_user_id: str,
    target_id: str,
) -> WushuangVariantResponse:
    if not isinstance(state, ShenLubuReworkState):
        raise TypeError("神吕布状态必须使用 ShenLubuReworkState 表示")
    shen = _text(shen_lubu_id, "神吕布角色标识")
    user = _text(slash_user_id, "杀使用者")
    target = _text(target_id, "杀目标")
    if user != shen:
        raise ValueError("无双※的两闪要求只适用于神吕布使用的杀")
    return WushuangVariantResponse(
        WushuangResponseKind.SLASH_JINK,
        target,
        2 if state.wushuang_active else 1,
    )


def start_wushuang_duel_response(
    state: ShenLubuReworkState,
    *,
    shen_lubu_id: str,
    duel_user_id: str,
    duel_target_id: str,
    responder_id: str,
) -> WushuangVariantResponse:
    if not isinstance(state, ShenLubuReworkState):
        raise TypeError("神吕布状态必须使用 ShenLubuReworkState 表示")
    shen = _text(shen_lubu_id, "神吕布角色标识")
    user = _text(duel_user_id, "决斗使用者")
    target = _text(duel_target_id, "决斗目标")
    responder = _text(responder_id, "决斗当前响应者")
    if user == target:
        raise ValueError("决斗使用者与目标不能相同")
    if shen not in (user, target):
        raise ValueError("无双※决斗响应必须包含神吕布")
    if responder not in (user, target):
        raise ValueError("决斗当前响应者必须是决斗双方之一")
    opponent = target if user == shen else user
    return WushuangVariantResponse(
        WushuangResponseKind.DUEL_SLASH,
        responder,
        2 if state.wushuang_active and responder == opponent else 1,
    )


def play_wushuang_response_card(
    response: WushuangVariantResponse,
    *,
    card_name: str,
) -> WushuangVariantResponse:
    if not isinstance(response, WushuangVariantResponse):
        raise TypeError("无双※响应必须使用 WushuangVariantResponse 表示")
    if response.complete:
        raise ValueError("无双※本次响应已经完成")
    card = _text(card_name, "无双※响应牌名")
    legal = (
        card == "闪"
        if response.kind is WushuangResponseKind.SLASH_JINK
        else card in _SLASH_NAMES
    )
    if not legal:
        raise ValueError(f"无双※本次响应需要打出【{response.required_card_name}】")
    return replace(response, provided_count=response.provided_count + 1)


@dataclass(frozen=True)
class WuqianDamageCardAward:
    """来源未知、等待外层随机具现的一张伤害牌奖励。"""

    card_category_key: str = "damage_card"
    count: int = 1
    random_selection: bool = True
    requires_external_materialization: bool = True

    def __post_init__(self) -> None:
        if self.card_category_key != "damage_card":
            raise ValueError("无前结束阶段奖励只能使用抽象伤害牌类别")
        if self.count != 1:
            raise ValueError("无前结束阶段抽象奖励数量只能是一张")
        if not _bool(self.random_selection, "无前结束阶段奖励是否随机"):
            raise ValueError("无前结束阶段抽象奖励必须随机选择")
        if not _bool(
            self.requires_external_materialization,
            "无前结束阶段奖励是否等待外层具现",
        ):
            raise ValueError("来源未知的无前结束阶段奖励必须等待外层具现")


@dataclass(frozen=True)
class WuqianEndPhaseResult:
    state_after: ShenLubuReworkState
    damage_cards_in_hand_before: int
    gained_cards: tuple[V24Card, ...]
    draw_pile_after: tuple[V24Card, ...]
    pending_awards: tuple[WuqianDamageCardAward, ...] = ()


def resolve_wuqian_end_phase(
    state: ShenLubuReworkState,
    *,
    hand_cards: Sequence[V24Card],
    draw_pile: Sequence[V24Card] = (),
    seed: object | None = None,
) -> WuqianEndPhaseResult:
    """生成来源无关的随机伤害牌奖励；旧牌堆参数只作原样兼容回传。"""

    if not isinstance(state, ShenLubuReworkState):
        raise TypeError("神吕布状态必须使用 ShenLubuReworkState 表示")
    hand = tuple(hand_cards)
    legacy_pile = tuple(draw_pile)
    if any(not isinstance(card, V24Card) for card in hand + legacy_pile):
        raise TypeError("无前手牌与牌堆必须使用 V24Card 表示")
    if any(card.zone is not CardZone.HAND for card in hand):
        raise ValueError("无前结束阶段手牌输入必须来自手牌区")
    if any(card.zone is not CardZone.DRAW_PILE for card in legacy_pile):
        raise ValueError("兼容参数 draw_pile 中的牌必须来自牌堆区")
    before = sum(is_shen_lubu_damage_card(card) for card in hand)
    pending_awards = (WuqianDamageCardAward(),) if before == 0 else ()
    # seed 与 draw_pile 保留为公开调用兼容参数；随机候选及来源必须由外层具现。
    _ = seed
    return WuqianEndPhaseResult(
        state,
        before,
        (),
        legacy_pile,
        pending_awards,
    )


@dataclass(frozen=True)
class ShenfenParticipant:
    player_id: str
    hp: int
    equipment_card_ids: tuple[str, ...] = ()
    hand_card_ids: tuple[str, ...] = ()
    alive: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "player_id", _text(self.player_id, "神愤目标"))
        if isinstance(self.hp, bool) or not isinstance(self.hp, int):
            raise TypeError("神愤目标体力必须是整数")
        object.__setattr__(
            self,
            "equipment_card_ids",
            tuple(_text(item, "神愤装备牌编号") for item in self.equipment_card_ids),
        )
        object.__setattr__(
            self,
            "hand_card_ids",
            tuple(_text(item, "神愤手牌编号") for item in self.hand_card_ids),
        )
        _bool(self.alive, "神愤目标存活状态")


@dataclass(frozen=True)
class ShenfenDamageOutcome:
    actual_damage: int
    hp_after: int
    alive_after: bool
    game_over: bool = False

    def __post_init__(self) -> None:
        ensure_int_at_least(self.actual_damage, "神愤实际伤害", 0)
        if isinstance(self.hp_after, bool) or not isinstance(self.hp_after, int):
            raise TypeError("神愤伤害后体力必须是整数")
        _bool(self.alive_after, "神愤伤害后存活状态")
        _bool(self.game_over, "神愤伤害后游戏结束状态")


ShenfenDamageResolver = Callable[[ShenfenParticipant], ShenfenDamageOutcome]


@dataclass(frozen=True)
class ShenfenEvent:
    round_name: str
    player_id: str
    detail: str


@dataclass(frozen=True)
class ShenfenResult:
    state_after: ShenLubuReworkState
    participants_after: tuple[ShenfenParticipant, ...]
    events: tuple[ShenfenEvent, ...]
    game_over: bool
    flipped_at_end: bool


def resolve_shenfen(
    state: ShenLubuReworkState,
    *,
    ordered_other_players: Sequence[ShenfenParticipant],
    damage_resolver: ShenfenDamageResolver | None = None,
) -> ShenfenResult:
    """严格按伤害轮、装备轮、手牌轮逐名完整处理，最后才翻面。"""

    if not isinstance(state, ShenLubuReworkState):
        raise TypeError("神吕布状态必须使用 ShenLubuReworkState 表示")
    if state.shenfen_used_this_play_phase:
        raise ValueError("【神愤】每个出牌阶段限一次")
    if state.rage < 6:
        raise ValueError("发动【神愤】需要移去六个暴怒")
    if isinstance(ordered_other_players, (str, bytes)) or not isinstance(
        ordered_other_players,
        Sequence,
    ):
        raise TypeError("神愤其他角色必须按外部已确定的顺序给出")
    participants = list(ordered_other_players)
    if any(not isinstance(item, ShenfenParticipant) for item in participants):
        raise TypeError("神愤目标必须使用 ShenfenParticipant 表示")
    if len({item.player_id for item in participants}) != len(participants):
        raise ValueError("神愤目标不能重复")
    if damage_resolver is not None and not callable(damage_resolver):
        raise TypeError("神愤伤害处理器必须可调用")
    if any(not item.alive or item.hp <= 0 for item in participants):
        raise ValueError("神愤死亡或离场角色的参与方式待核验，当前接口不作推断")
    if any(len(item.hand_card_ids) < 4 for item in participants):
        raise ValueError("神愤目标手牌不足四张时的处理待核验，当前接口不作推断")

    outcomes: list[ShenfenDamageOutcome] = []
    for player in participants:
        outcome = (
            ShenfenDamageOutcome(1, player.hp - 1, player.hp - 1 >= 1)
            if damage_resolver is None
            else damage_resolver(player)
        )
        if not isinstance(outcome, ShenfenDamageOutcome):
            raise TypeError("神愤伤害处理器必须返回 ShenfenDamageOutcome")
        if outcome.game_over:
            raise ValueError("神愤伤害后的胜负中止时机待核验，当前接口不作推断")
        if not outcome.alive_after or outcome.hp_after <= 0:
            raise ValueError("神愤伤害后的死亡处理待核验，当前接口不作推断")
        if outcome.hp_after != player.hp - outcome.actual_damage:
            raise ValueError("神愤实际伤害与伤害后体力必须是外部核验的一致事实")
        outcomes.append(outcome)

    working = replace(
        state,
        rage=state.rage - 6,
        shenfen_used_this_play_phase=True,
    )
    events: list[ShenfenEvent] = []
    for index, (player, outcome) in enumerate(zip(participants, outcomes, strict=True)):
        participants[index] = replace(
            player,
            hp=outcome.hp_after,
            alive=outcome.alive_after,
        )
        working = gain_rage_from_damage(working, damage_dealt=outcome.actual_damage)
        events.append(ShenfenEvent("伤害轮", player.player_id, f"实际受到{outcome.actual_damage}点伤害"))

    for index, player in enumerate(participants):
        if not player.alive:
            continue
        events.append(ShenfenEvent("装备轮", player.player_id, f"弃置{len(player.equipment_card_ids)}张装备牌"))
        participants[index] = replace(player, equipment_card_ids=())

    for index, player in enumerate(participants):
        if not player.alive:
            continue
        discarded = min(4, len(player.hand_card_ids))
        events.append(ShenfenEvent("手牌轮", player.player_id, f"弃置{discarded}张手牌"))
        participants[index] = replace(player, hand_card_ids=player.hand_card_ids[discarded:])

    working = replace(working, face_up=not working.face_up)
    events.append(ShenfenEvent("最后", "神吕布", "翻面"))
    return ShenfenResult(working, tuple(participants), tuple(events), False, True)


def start_shen_lubu_play_phase(state: ShenLubuReworkState) -> ShenLubuReworkState:
    if not isinstance(state, ShenLubuReworkState):
        raise TypeError("神吕布状态必须使用 ShenLubuReworkState 表示")
    return replace(state, shenfen_used_this_play_phase=False)
