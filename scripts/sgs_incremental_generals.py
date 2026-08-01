"""四名增量武将的轻量结算模型。

本模块只实现用户已确认、且适合单元测试的状态边界：许攸的【成略】【恃才】
【寸目】，清河公主的【谮构】【诽离】，傅佥的【破降】【绝勇】，以及
谋·公孙瓒的【义从】【趫猛】。它不是完整游戏引擎，也不会补全未提供的
武将、技能或客户端行为。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import random
from typing import Iterable, Mapping, Sequence


def _nonempty(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label}必须是非空字符串")
    return value.strip()


def _int_at_least(value: object, label: str, minimum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{label}必须是整数")
    if value < minimum:
        raise ValueError(f"{label}不能小于{minimum}")
    return value


def _unique_nonempty(values: Iterable[str], label: str) -> tuple[str, ...]:
    try:
        result = tuple(_nonempty(value, label) for value in values)
    except TypeError as exc:
        raise TypeError(f"{label}必须是可迭代对象") from exc
    if len(result) != len(set(result)):
        raise ValueError(f"{label}不能包含重复值")
    return result


def _coerce_enum(value: object, enum_type: type[Enum], label: str) -> Enum:
    if isinstance(value, enum_type):
        return value
    try:
        return enum_type(value)
    except (TypeError, ValueError) as exc:
        choices = "、".join(str(member.value) for member in enum_type)
        raise ValueError(f"{label}只能是：{choices}") from exc


@dataclass(frozen=True)
class CardEntity:
    """技能结算所需的最小实体牌信息。"""

    card_id: str
    card_name: str
    suit: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "card_id", _nonempty(self.card_id, "实体牌编号"))
        object.__setattr__(self, "card_name", _nonempty(self.card_name, "牌名"))
        if self.suit is not None:
            object.__setattr__(self, "suit", _nonempty(self.suit, "花色"))


# ---------------------------------------------------------------------------
# 许攸：基础数据、成略、恃才、寸目


class XuYouRole(str, Enum):
    NORMAL = "普通身份"
    LORD = "主公"
    LANDLORD = "地主"


@dataclass(frozen=True)
class GeneralInitialStats:
    base_hp: int
    base_max_hp: int
    initial_hp: int
    initial_max_hp: int


def xu_you_initial_stats(role: XuYouRole | str = XuYouRole.NORMAL) -> GeneralInitialStats:
    """返回许攸正式基础 3/3，以及主公或地主加成后的 4/4。"""

    resolved = _coerce_enum(role, XuYouRole, "许攸身份")
    bonus = 0 if resolved is XuYouRole.NORMAL else 1
    return GeneralInitialStats(3, 3, 3 + bonus, 3 + bonus)


def base_hp_vulnerability_adjustment(
    stats: GeneralInitialStats,
    *,
    reference_base_hp: int = 4,
    per_missing_base_hp: float = 0.45,
) -> float:
    """给策略层提供透明的基础体力修正；模式加成不会抹掉三体力底盘。"""

    if not isinstance(stats, GeneralInitialStats):
        raise TypeError("武将初始数据必须是 GeneralInitialStats")
    _int_at_least(reference_base_hp, "参考基础体力", 1)
    if isinstance(per_missing_base_hp, bool) or not isinstance(
        per_missing_base_hp, (int, float)
    ):
        raise TypeError("每点基础体力差修正必须是数值")
    if per_missing_base_hp < 0:
        raise ValueError("每点基础体力差修正不能为负数")
    return max(reference_base_hp - stats.base_hp, 0) * float(per_missing_base_hp)


class ChenglueMode(str, Enum):
    YANG = "阳"
    YIN = "阴"


@dataclass(frozen=True)
class ChenglueState:
    mode: ChenglueMode = ChenglueMode.YANG
    used_this_play_phase: bool = False
    unrestricted_suits: frozenset[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        object.__setattr__(self, "mode", _coerce_enum(self.mode, ChenglueMode, "成略阴阳状态"))
        if not isinstance(self.used_this_play_phase, bool):
            raise TypeError("成略本阶段是否已发动必须是布尔值")
        try:
            suits = frozenset(_nonempty(suit, "成略开放花色") for suit in self.unrestricted_suits)
        except TypeError as exc:
            raise TypeError("成略开放花色必须是可迭代对象") from exc
        object.__setattr__(self, "unrestricted_suits", suits)


@dataclass(frozen=True)
class ChenglueResult:
    state_after: ChenglueState
    hand_after: tuple[CardEntity, ...]
    drawn_card_ids: tuple[str, ...]
    discarded_card_ids: tuple[str, ...]
    granted_suits: frozenset[str]


def start_xu_you_play_phase(state: ChenglueState | None = None) -> ChenglueState:
    """进入新的独立出牌阶段；保留阴阳，清除阶段次数与花色权限。"""

    if state is None:
        return ChenglueState()
    if not isinstance(state, ChenglueState):
        raise TypeError("成略状态必须是 ChenglueState")
    return ChenglueState(mode=state.mode)


def resolve_chenglue(
    state: ChenglueState,
    *,
    hand_before: Sequence[CardEntity],
    drawn_cards: Sequence[CardEntity],
    discard_card_ids: Iterable[str],
) -> ChenglueResult:
    """按“先摸、再按实际可弃数量弃置”处理一次【成略】。"""

    if not isinstance(state, ChenglueState):
        raise TypeError("成略状态必须是 ChenglueState")
    if state.used_this_play_phase:
        raise ValueError("当前出牌阶段已经发动过成略")
    if not all(isinstance(card, CardEntity) for card in (*hand_before, *drawn_cards)):
        raise TypeError("手牌和摸到的牌都必须是 CardEntity")

    draw_count = 1 if state.mode is ChenglueMode.YANG else 2
    discard_count = 2 if state.mode is ChenglueMode.YANG else 1
    if len(drawn_cards) != draw_count:
        raise ValueError(f"成略{state.mode.value}状态必须先摸{draw_count}张牌")
    combined = tuple(hand_before) + tuple(drawn_cards)
    ids = [card.card_id for card in combined]
    if len(ids) != len(set(ids)):
        raise ValueError("成略结算中的实体牌编号不能重复")
    selected = _unique_nonempty(discard_card_ids, "成略弃牌编号")
    required = min(discard_count, len(combined))
    if len(selected) != required:
        raise ValueError(f"成略本次必须实际弃置{required}张手牌")
    if not set(selected).issubset(ids):
        raise ValueError("成略只能弃置摸牌后实际持有的手牌")

    selected_set = set(selected)
    discarded = tuple(card for card in combined if card.card_id in selected_set)
    granted = frozenset(card.suit for card in discarded if card.suit is not None)
    next_mode = ChenglueMode.YIN if state.mode is ChenglueMode.YANG else ChenglueMode.YANG
    return ChenglueResult(
        state_after=ChenglueState(
            mode=next_mode,
            used_this_play_phase=True,
            unrestricted_suits=granted,
        ),
        hand_after=tuple(card for card in combined if card.card_id not in selected_set),
        drawn_card_ids=tuple(card.card_id for card in drawn_cards),
        discarded_card_ids=selected,
        granted_suits=granted,
    )


@dataclass(frozen=True)
class ChengluePermission:
    ignore_distance: bool
    ignore_frequency: bool
    other_legality_still_required: bool = True


def chenglue_permission(
    state: ChenglueState,
    *,
    card_suit: str | None,
    is_converted: bool,
) -> ChengluePermission:
    if not isinstance(state, ChenglueState):
        raise TypeError("成略状态必须是 ChenglueState")
    if not isinstance(is_converted, bool):
        raise TypeError("是否为转化牌必须是布尔值")
    enabled = (
        not is_converted
        and card_suit is not None
        and card_suit in state.unrestricted_suits
    )
    return ChengluePermission(enabled, enabled)


class ShicaiCardType(str, Enum):
    BASIC = "基本牌"
    TRICK = "锦囊牌"
    EQUIPMENT = "装备牌"


@dataclass(frozen=True)
class ShicaiTurnState:
    completed_types: frozenset[ShicaiCardType] = field(default_factory=frozenset)


@dataclass(frozen=True)
class ShicaiResult:
    state_after: ShicaiTurnState
    type_recorded: bool
    can_trigger: bool
    topdeck_card_ids: tuple[str, ...]
    draw_count: int
    reason: str


def resolve_shicai(
    state: ShicaiTurnState,
    *,
    card_type: ShicaiCardType | str,
    physical_card_ids: Iterable[str],
    card_use_completed: bool,
    delayed_trick: bool = False,
    entities_movable: bool = True,
    effect_cancelled_by_nullification: bool = False,
    card_or_effect_invalidated: bool = False,
    topdeck_order: Iterable[str] | None = None,
) -> ShicaiResult:
    """记录牌类型，并区分无懈抵消与真正无效的【恃才】结果。"""

    if not isinstance(state, ShicaiTurnState):
        raise TypeError("恃才状态必须是 ShicaiTurnState")
    resolved_type = _coerce_enum(card_type, ShicaiCardType, "恃才牌类型")
    ids = _unique_nonempty(physical_card_ids, "恃才实体牌编号")
    if not ids:
        raise ValueError("恃才需要至少一张可追踪实体牌")
    for value, label in (
        (card_use_completed, "使用流程是否完成"),
        (delayed_trick, "是否延时锦囊"),
        (entities_movable, "实体牌是否可移动"),
        (effect_cancelled_by_nullification, "是否被无懈抵消"),
        (card_or_effect_invalidated, "是否真正无效"),
    ):
        if not isinstance(value, bool):
            raise TypeError(f"{label}必须是布尔值")
    if delayed_trick and resolved_type is not ShicaiCardType.TRICK:
        raise ValueError("只有锦囊牌可以标记为延时锦囊")
    if card_or_effect_invalidated and card_use_completed:
        raise ValueError("真正无效的牌不能同时标记为已完成恃才所需的结算节点")

    first_type = resolved_type not in state.completed_types
    type_recorded = card_use_completed
    new_types = state.completed_types | ({resolved_type} if type_recorded else set())
    can_trigger = (
        first_type
        and card_use_completed
        and not delayed_trick
        and entities_movable
        and not card_or_effect_invalidated
    )
    if can_trigger:
        ordered = ids if topdeck_order is None else _unique_nonempty(
            topdeck_order, "恃才置顶顺序"
        )
        if set(ordered) != set(ids) or len(ordered) != len(ids):
            raise ValueError("恃才置顶顺序必须恰好包含本次使用的全部实体牌")
        reason = "被无懈抵消但使用流程完成，仍可发动" if effect_cancelled_by_nullification else "首次完成该类型牌的使用结算"
        draw_count = 1
    else:
        ordered = ()
        draw_count = 0
        if not card_use_completed or card_or_effect_invalidated:
            reason = "未完成恃才要求的使用结算节点"
        elif not first_type:
            reason = "本回合该牌类型已经完成结算"
        elif delayed_trick:
            reason = "延时锦囊占用锦囊类型但自身不能置顶"
        else:
            reason = "实体牌已经移动，无法完成置顶摸牌"
    return ShicaiResult(
        ShicaiTurnState(frozenset(new_types)),
        type_recorded,
        can_trigger,
        tuple(ordered),
        draw_count,
        reason,
    )


class BottomDrawExhausted(RuntimeError):
    """仍需继续摸牌、但牌堆与可重洗弃牌堆均无牌。"""

    def __init__(self, drawn_card_ids: Sequence[str]) -> None:
        super().__init__("仍需继续摸牌，但牌堆和可重洗弃牌堆均已无牌，游戏应判平局")
        self.drawn_card_ids = tuple(drawn_card_ids)


@dataclass(frozen=True)
class BottomDrawResult:
    drawn_card_ids: tuple[str, ...]
    deck_after: tuple[str, ...]
    discard_after: tuple[str, ...]
    reshuffle_count: int


def draw_from_bottom(
    deck: Sequence[str],
    count: int,
    *,
    discard_pile: Sequence[str] = (),
    seed: int | None = None,
) -> BottomDrawResult:
    """按【寸目】逐张从牌堆底摸牌；不足时洗入弃牌堆后继续从底部摸。"""

    draw_count = _int_at_least(count, "寸目摸牌数", 0)
    current = list(_unique_nonempty(deck, "牌堆实体牌编号"))
    discard = list(_unique_nonempty(discard_pile, "弃牌堆实体牌编号"))
    if set(current) & set(discard):
        raise ValueError("同一实体牌不能同时位于牌堆和弃牌堆")
    rng = random.Random(seed)
    drawn: list[str] = []
    reshuffles = 0
    while len(drawn) < draw_count:
        if not current:
            if not discard:
                raise BottomDrawExhausted(drawn)
            current = discard
            discard = []
            rng.shuffle(current)
            reshuffles += 1
        drawn.append(current.pop())
    return BottomDrawResult(tuple(drawn), tuple(current), tuple(discard), reshuffles)


# ---------------------------------------------------------------------------
# 清河公主：谮构、诬、诽离


_NORMAL_BASIC_NAMES = frozenset({"杀", "闪", "桃", "酒"})


def _normal_basic_name(name: str) -> str:
    normalized = _nonempty(name, "基本牌名")
    if normalized in {"火杀", "雷杀"}:
        normalized = "杀"
    if normalized not in _NORMAL_BASIC_NAMES:
        raise ValueError("谮构第一项只能使用普通基本牌名：杀、闪、桃、酒")
    return normalized


def zengou_option_one_available(
    legal_second_names_by_first: Mapping[str, Iterable[str]],
) -> bool:
    """选择第一项前检查是否存在完整的两张不同牌名合法序列。"""

    if not isinstance(legal_second_names_by_first, Mapping):
        raise TypeError("谮构合法序列必须是映射")
    for first, seconds in legal_second_names_by_first.items():
        first_name = _normal_basic_name(first)
        if any(_normal_basic_name(second) != first_name for second in seconds):
            return True
    return False


@dataclass(frozen=True)
class ZengouSequence:
    first_card_name: str
    second_card_name: str
    ignores_normal_frequency: bool = True
    requires_other_legality: bool = True


def validate_zengou_sequence(
    *,
    selected_first: str,
    selected_second: str,
    legal_first_names: Iterable[str],
    legal_second_names_after_first: Iterable[str],
) -> ZengouSequence:
    first = _normal_basic_name(selected_first)
    second = _normal_basic_name(selected_second)
    legal_first = {_normal_basic_name(name) for name in legal_first_names}
    legal_second = {_normal_basic_name(name) for name in legal_second_names_after_first}
    if first not in legal_first:
        raise ValueError("谮构选择的第一张基本牌在当前状态下不合法")
    if second not in legal_second:
        raise ValueError("谮构选择的第二张基本牌在第一张结算后的最新状态下不合法")
    if first == second:
        raise ValueError("谮构第一项必须依次使用两张不同牌名的基本牌")
    return ZengouSequence(first, second)


@dataclass(frozen=True)
class ZengouReplacementResult:
    shared_name_snapshot: frozenset[str]
    qinghe_replaced_card_ids: tuple[str, ...]
    target_replaced_card_ids: tuple[str, ...]
    qinghe_slash_card_ids: tuple[str, ...]
    target_slash_card_ids: tuple[str, ...]
    deck_after: tuple[CardEntity, ...]
    hand_limit_exemption_owner: Mapping[str, str]


def resolve_zengou_shared_name_replacement(
    *,
    qinghe_id: str,
    target_id: str,
    qinghe_hand: Sequence[CardEntity],
    target_hand: Sequence[CardEntity],
    deck: Sequence[CardEntity],
    seed: int | None = None,
) -> ZengouReplacementResult:
    """先锁定共有牌名，再按清河公主、目标顺序取得牌堆中的【杀】。"""

    qid = _nonempty(qinghe_id, "清河公主角色编号")
    tid = _nonempty(target_id, "谮构目标编号")
    if qid == tid:
        raise ValueError("谮构第二项的双方角色编号不能相同")
    cards = tuple(qinghe_hand) + tuple(target_hand) + tuple(deck)
    if not all(isinstance(card, CardEntity) for card in cards):
        raise TypeError("谮构手牌和牌堆都必须由 CardEntity 组成")
    ids = [card.card_id for card in cards]
    if len(ids) != len(set(ids)):
        raise ValueError("谮构结算中的实体牌编号不能重复")
    shared = frozenset(card.card_name for card in qinghe_hand) & frozenset(
        card.card_name for card in target_hand
    )
    q_originals = tuple(card for card in qinghe_hand if card.card_name in shared)
    t_originals = tuple(card for card in target_hand if card.card_name in shared)
    working = list(deck) + list(q_originals) + list(t_originals)
    rng = random.Random(seed)
    rng.shuffle(working)

    def take_slashes(amount: int) -> tuple[CardEntity, ...]:
        selected: list[CardEntity] = []
        for card in tuple(working):
            if len(selected) == amount:
                break
            if card.card_name == "杀":
                selected.append(card)
                working.remove(card)
        return tuple(selected)

    q_slashes = take_slashes(len(q_originals))
    t_slashes = take_slashes(len(t_originals))
    exemptions = {card.card_id: qid for card in q_slashes}
    exemptions.update({card.card_id: tid for card in t_slashes})
    return ZengouReplacementResult(
        shared,
        tuple(card.card_id for card in q_originals),
        tuple(card.card_id for card in t_originals),
        tuple(card.card_id for card in q_slashes),
        tuple(card.card_id for card in t_slashes),
        tuple(working),
        exemptions,
    )


def zengou_slash_exemption_active(
    result: ZengouReplacementResult,
    *,
    card_id: str,
    current_owner_id: str,
    still_in_owner_hand: bool,
    owner_next_end_phase_reached: bool,
    ever_left_original_owner_hand: bool = False,
) -> bool:
    """免计上限绑定原取得者与实体牌，离手或到下个结束阶段即永久失效。"""

    owner = result.hand_limit_exemption_owner.get(_nonempty(card_id, "杀实体牌编号"))
    return (
        owner is not None
        and current_owner_id == owner
        and still_in_owner_hand
        and not ever_left_original_owner_hand
        and not owner_next_end_phase_reached
    )


@dataclass(frozen=True)
class WuMarkState:
    mark_names: frozenset[str] = field(default_factory=frozenset)
    first_use_checked_this_turn: bool = False


def add_wu_mark(state: WuMarkState, card_name: str) -> WuMarkState:
    if not isinstance(state, WuMarkState):
        raise TypeError("诬标记状态必须是 WuMarkState")
    return WuMarkState(state.mark_names | {_normal_basic_name(card_name)}, state.first_use_checked_this_turn)


def start_wu_independent_turn(state: WuMarkState) -> WuMarkState:
    if not isinstance(state, WuMarkState):
        raise TypeError("诬标记状态必须是 WuMarkState")
    return WuMarkState(state.mark_names, False)


@dataclass(frozen=True)
class WuMarkResult:
    state_after: WuMarkState
    occupied_first_use: bool
    matched_mark: bool
    hp_loss: int
    checked_card_name: str | None


def resolve_wu_card_event(
    state: WuMarkState,
    *,
    event_is_use: bool,
    original_entity_name: str,
    explicitly_rewritten_name: str | None = None,
    use_process_finished: bool = True,
) -> WuMarkResult:
    """普通打出不占首张；转化默认看实体原牌名，明确改名时才看新名。"""

    if not isinstance(state, WuMarkState):
        raise TypeError("诬标记状态必须是 WuMarkState")
    if not isinstance(event_is_use, bool) or not isinstance(use_process_finished, bool):
        raise TypeError("牌事件标记必须是布尔值")
    # 首张“使用”的任意牌都会占用检查；只有诬标记本身限定为基本牌名。
    # 因而普通锦囊或装备不能在此处被错误拒绝，只会自然地不匹配标记。
    original = _nonempty(original_entity_name, "首张使用牌实体原名")
    checked = (
        _nonempty(explicitly_rewritten_name, "明确改写后的牌名")
        if explicitly_rewritten_name
        else original
    )
    if not event_is_use:
        return WuMarkResult(state, False, False, 0, None)
    if state.first_use_checked_this_turn:
        return WuMarkResult(state, False, False, 0, None)
    if not use_process_finished:
        raise ValueError("诬标记必须等第一张使用牌的使用流程处理完后再检查")
    matched = checked in state.mark_names
    marks = state.mark_names - ({checked} if matched else set())
    return WuMarkResult(WuMarkState(frozenset(marks), True), True, matched, int(matched), checked)


class FeiliBranch(str, Enum):
    DO_NOT_PREVENT = "不发动"
    DISCARD_TWO = "弃置两张牌"
    REMOVE_SOURCE_WU = "移除来源全部诬"


@dataclass(frozen=True)
class FeiliResult:
    damage_after: int
    prevented_entire_event: bool
    discarded_count: int
    removed_wu_names: frozenset[str]
    draw_count: int
    newly_blocked_zengou_source: str | None


def resolve_feili(
    *,
    incoming_damage: int,
    branch: FeiliBranch | str,
    qinghe_has_zengou: bool,
    discardable_card_count: int,
    source_id: str | None = None,
    source_wu_names: Iterable[str] = (),
) -> FeiliResult:
    damage = _int_at_least(incoming_damage, "诽离处理前伤害", 0)
    resolved = _coerce_enum(branch, FeiliBranch, "诽离分支")
    discardable = _int_at_least(discardable_card_count, "可弃置牌数", 0)
    marks = frozenset(_normal_basic_name(name) for name in source_wu_names)
    if resolved is FeiliBranch.DO_NOT_PREVENT or damage == 0:
        return FeiliResult(damage, False, 0, frozenset(), 0, None)
    if not qinghe_has_zengou:
        raise ValueError("失去谮构后不能发动诽离")
    if resolved is FeiliBranch.DISCARD_TWO:
        if discardable < 2:
            raise ValueError("诽离普通分支需要弃置手牌区或装备区共两张牌")
        return FeiliResult(0, True, 2, frozenset(), 0, None)
    sid = _nonempty(source_id, "伤害来源")
    if not marks:
        raise ValueError("伤害来源没有诬标记，不能选择诽离替代分支")
    return FeiliResult(0, True, 0, marks, 2, sid)


# ---------------------------------------------------------------------------
# 傅佥：破降、绝勇


@dataclass(frozen=True)
class JueCard:
    card_id: str
    card_name: str
    original_user_id: str
    is_virtual: bool = False
    is_converted: bool = False
    used_by_jueyong: bool = False
    delayed_trick: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "card_id", _nonempty(self.card_id, "绝实体牌编号"))
        object.__setattr__(self, "card_name", _nonempty(self.card_name, "绝牌名"))
        object.__setattr__(self, "original_user_id", _nonempty(self.original_user_id, "绝原使用者"))


@dataclass(frozen=True)
class JueyongState:
    jue_cards: tuple[JueCard, ...] = ()

    def __post_init__(self) -> None:
        if not all(isinstance(card, JueCard) for card in self.jue_cards):
            raise TypeError("绝区只能包含 JueCard")
        ids = [card.card_id for card in self.jue_cards]
        if len(ids) != len(set(ids)):
            raise ValueError("绝区实体牌编号不能重复")


@dataclass(frozen=True)
class JueyongCaptureResult:
    state_after: JueyongState
    captured: bool
    target_cancelled: bool
    derived_target_effects_invalid: bool
    card_still_counted_as_used: bool


def resolve_jueyong_capture(
    state: JueyongState,
    *,
    fu_qian_id: str,
    current_hp: int,
    card: JueCard,
    target_ids: Sequence[str],
) -> JueyongCaptureResult:
    if not isinstance(state, JueyongState) or not isinstance(card, JueCard):
        raise TypeError("绝勇状态和牌必须分别是 JueyongState、JueCard")
    fid = _nonempty(fu_qian_id, "傅佥角色编号")
    hp = _int_at_least(current_hp, "傅佥当前体力", 0)
    targets = tuple(_nonempty(target, "牌目标") for target in target_ids)
    eligible = (
        not card.is_virtual
        and not card.is_converted
        and not card.used_by_jueyong
        and card.card_name not in {"桃", "酒"}
        and targets == (fid,)
        and len(state.jue_cards) < hp
    )
    if not eligible:
        return JueyongCaptureResult(state, False, False, False, True)
    return JueyongCaptureResult(
        JueyongState(state.jue_cards + (card,)),
        True,
        True,
        True,
        True,
    )


@dataclass(frozen=True)
class PojiangResult:
    current_hp_after: int
    discarded_jue_card_ids: tuple[str, ...]
    drawn_card_ids: tuple[str, ...]
    hand_limit_exempt_card_ids: frozenset[str]
    lost_hp: int
    loss_is_damage: bool
    enters_dying: bool


def resolve_pojiang(
    *,
    current_hp: int,
    self_id: str,
    recipient_id: str,
    give_card_id: str,
    hand_card_ids: Iterable[str],
    equipment_card_ids: Iterable[str],
    drawn_card_ids: Iterable[str],
    jue_state: JueyongState,
) -> PojiangResult:
    hp = _int_at_least(current_hp, "傅佥当前体力", 0)
    sid = _nonempty(self_id, "傅佥角色编号")
    rid = _nonempty(recipient_id, "破降收牌角色")
    if sid == rid:
        raise ValueError("破降必须将牌交给一名其他角色")
    give = _nonempty(give_card_id, "破降交出牌编号")
    available = set(_unique_nonempty(hand_card_ids, "手牌编号")) | set(
        _unique_nonempty(equipment_card_ids, "装备牌编号")
    )
    if give not in available:
        raise ValueError("破降只能交出手牌区或装备区的一张牌")
    drawn = _unique_nonempty(drawn_card_ids, "破降摸牌编号")
    if len(drawn) != 3:
        raise ValueError("破降必须摸三张牌；牌堆彻底不足应交由通用平局规则处理")
    if not isinstance(jue_state, JueyongState):
        raise TypeError("破降的绝状态必须是 JueyongState")
    hp_after = hp - 1
    return PojiangResult(
        hp_after,
        tuple(card.card_id for card in jue_state.jue_cards),
        drawn,
        frozenset(drawn),
        1,
        False,
        hp_after <= 0,
    )


class JueyongEndAction(str, Enum):
    REUSE = "原使用者再次使用"
    DISCARD = "置入弃牌堆"


@dataclass(frozen=True)
class JueyongEndEvent:
    card_id: str
    action: JueyongEndAction
    reason: str
    ignores_timing: bool = True
    ignores_frequency: bool = True
    ignores_distance: bool = False


@dataclass(frozen=True)
class JueyongEndResult:
    events: tuple[JueyongEndEvent, ...]
    judgment_delayed_trick_names_after: frozenset[str]
    state_after: JueyongState = JueyongState()


def resolve_jueyong_end_phase(
    state: JueyongState,
    *,
    living_user_ids: Iterable[str],
    currently_legal_reuse_card_ids: Iterable[str],
    judgment_delayed_trick_names: Iterable[str] = (),
) -> JueyongEndResult:
    """按 FIFO 处理绝；合法集合须已包含距离、目标和禁止条件检查。"""

    if not isinstance(state, JueyongState):
        raise TypeError("绝勇状态必须是 JueyongState")
    living = set(_unique_nonempty(living_user_ids, "存活角色编号"))
    legal = set(_unique_nonempty(currently_legal_reuse_card_ids, "当前合法绝编号"))
    delayed = set(_unique_nonempty(judgment_delayed_trick_names, "判定区延时锦囊名"))
    events: list[JueyongEndEvent] = []
    for card in state.jue_cards:
        if card.original_user_id not in living:
            events.append(JueyongEndEvent(card.card_id, JueyongEndAction.DISCARD, "原使用者已不在场"))
            continue
        if card.card_id not in legal:
            events.append(
                JueyongEndEvent(
                    card.card_id,
                    JueyongEndAction.DISCARD,
                    "距离、目标或禁止条件不合法",
                )
            )
            continue
        if card.delayed_trick and card.card_name in delayed:
            events.append(JueyongEndEvent(card.card_id, JueyongEndAction.DISCARD, "判定区已有同名延时锦囊"))
            continue
        events.append(JueyongEndEvent(card.card_id, JueyongEndAction.REUSE, "当前合法，按绝的置入顺序再次使用"))
        if card.delayed_trick:
            delayed.add(card.card_name)
    return JueyongEndResult(tuple(events), frozenset(delayed))


# ---------------------------------------------------------------------------
# 谋·公孙瓒：义从、扈、趫猛


class YicongBranch(str, Enum):
    ATTACK = "进攻"
    DEFENSE = "防守"


@dataclass(frozen=True)
class YicongState:
    charge: int = 2
    hu_cards: tuple[CardEntity, ...] = ()
    outgoing_actual_distance_modifier: int = 0
    incoming_actual_distance_modifier: int = 0
    owns_yicong: bool = True

    def __post_init__(self) -> None:
        _int_at_least(self.charge, "义从蓄力", 0)
        if self.charge > 4:
            raise ValueError("义从蓄力不能超过4")
        if len(self.hu_cards) > 4:
            raise ValueError("扈最多四张")
        if not all(isinstance(card, CardEntity) for card in self.hu_cards):
            raise TypeError("扈必须由 CardEntity 组成")


def start_yicong_round(state: YicongState) -> YicongState:
    """上一轮距离修正结束；未使用的扈与蓄力继续保留。"""

    if not isinstance(state, YicongState):
        raise TypeError("义从状态必须是 YicongState")
    return YicongState(state.charge, state.hu_cards, 0, 0, state.owns_yicong)


@dataclass(frozen=True)
class YicongActivationResult:
    state_after: YicongState
    spent_charge: int
    acquired_hu_card_ids: tuple[str, ...]
    deck_after: tuple[CardEntity, ...]


def activate_yicong(
    state: YicongState,
    *,
    spend_charge: int,
    branch: YicongBranch | str,
    deck: Sequence[CardEntity],
    seed: int | None = None,
) -> YicongActivationResult:
    if not isinstance(state, YicongState):
        raise TypeError("义从状态必须是 YicongState")
    if not state.owns_yicong:
        raise ValueError("失去义从后不能发动义从")
    spend = _int_at_least(spend_charge, "义从消耗蓄力", 1)
    if spend > state.charge:
        raise ValueError("义从消耗蓄力不能超过当前蓄力")
    resolved = _coerce_enum(branch, YicongBranch, "义从分支")
    if not all(isinstance(card, CardEntity) for card in deck):
        raise TypeError("义从牌堆必须由 CardEntity 组成")
    wanted = "杀" if resolved is YicongBranch.ATTACK else "闪"
    candidates = [card for card in deck if card.card_name == wanted]
    acquire_count = min(spend, 4 - len(state.hu_cards), len(candidates))
    selected = random.Random(seed).sample(candidates, acquire_count)
    selected_ids = {card.card_id for card in selected}
    outgoing = -1 if resolved is YicongBranch.ATTACK else 0
    incoming = 1 if resolved is YicongBranch.DEFENSE else 0
    after = YicongState(
        charge=state.charge - spend,
        hu_cards=state.hu_cards + tuple(selected),
        outgoing_actual_distance_modifier=outgoing,
        incoming_actual_distance_modifier=incoming,
        owns_yicong=True,
    )
    return YicongActivationResult(
        after,
        spend,
        tuple(card.card_id for card in selected),
        tuple(card for card in deck if card.card_id not in selected_ids),
    )


class HuAction(str, Enum):
    USE = "使用"
    RESPOND = "打出"
    ZHANGBA_MATERIAL = "丈八蛇矛材料"
    DISCARD_HAND_COST = "普通弃置手牌成本"
    GIVE_HAND_COST = "交给手牌成本"
    SHOW_HAND_COST = "展示手牌成本"
    EXCHANGE_HAND_COST = "交换手牌成本"
    COUNT_AS_HAND = "计入手牌数"


def hu_action_allowed(
    action: HuAction | str,
    *,
    hand_card_use_prohibited: bool = False,
    all_card_use_or_response_prohibited: bool = False,
    specific_card_name_prohibited: bool = False,
) -> bool:
    resolved = _coerce_enum(action, HuAction, "扈操作")
    if all_card_use_or_response_prohibited or specific_card_name_prohibited:
        return False
    if resolved in {HuAction.USE, HuAction.RESPOND, HuAction.ZHANGBA_MATERIAL}:
        return True
    # 扈不是普通手牌；仅禁止手牌中的牌不会阻止上述三种合法用途。
    _ = hand_card_use_prohibited
    return False


class QiaomengOption(str, Enum):
    DISCARD_AND_DRAW = "弃置区域牌并摸一张"
    GAIN_CHARGE = "获得三点蓄力"


@dataclass(frozen=True)
class QiaomengResult:
    triggered: bool
    discarded_count: int
    draw_count: int
    charge_after: int
    trigger_count_for_event: int


def resolve_qiaomeng(
    *,
    actual_damage: int,
    damage_is_from_slash: bool,
    owns_yicong: bool,
    option: QiaomengOption | str,
    current_charge: int,
    target_has_area_card: bool,
) -> QiaomengResult:
    damage = _int_at_least(actual_damage, "趫猛对应实际伤害", 0)
    charge = _int_at_least(current_charge, "当前蓄力", 0)
    if charge > 4:
        raise ValueError("当前蓄力不能超过4")
    resolved = _coerce_enum(option, QiaomengOption, "趫猛选项")
    if not isinstance(damage_is_from_slash, bool) or not isinstance(owns_yicong, bool):
        raise TypeError("趫猛伤害来源和义从状态必须是布尔值")
    if not isinstance(target_has_area_card, bool):
        raise TypeError("目标区域内是否有牌必须是布尔值")
    if damage == 0 or not damage_is_from_slash or not owns_yicong:
        return QiaomengResult(False, 0, 0, charge, 0)
    if resolved is QiaomengOption.DISCARD_AND_DRAW:
        return QiaomengResult(True, int(target_has_area_card), 1, charge, 1)
    return QiaomengResult(True, 0, 0, min(4, charge + 3), 1)
