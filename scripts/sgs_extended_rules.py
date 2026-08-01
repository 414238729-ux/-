"""三国杀已确认规则的轻量状态模型。

本模块只实现适合独立验证的边界：牌堆取得与重洗、判定区放置约束、
存活角色环，以及军争身份模式的身份与胜负判断。它不是完整游戏引擎，
也不会补全 Knowledge 中没有给出的客户端细节。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Callable, Generic, Iterable, Mapping, Sequence, TypeVar

from ._validation import ensure_int_at_least, make_rng
from .sgs_card_rules import DelayedTrick

T = TypeVar("T")
S = TypeVar("S")


def _as_tuple(values: Iterable[T], name: str) -> tuple[T, ...]:
    if values is None:
        raise TypeError(f"{name}不能是 None")
    try:
        return tuple(values)
    except TypeError as exc:
        raise TypeError(f"{name}必须是可迭代对象") from exc


class DeckOperation(Enum):
    """会因牌堆顶牌不足而触发重洗的操作。"""

    DRAW = "摸牌"
    VIEW_TOP = "观看牌堆顶"
    REVEAL_TOP = "亮出牌堆顶"
    JUDGMENT = "判定"


class RuleStatus(Enum):
    """本项目允许用于轻量规则结果的资料状态。"""

    CURRENT_CONFIRMED = "当前确认"
    ANALYSIS_CONVENTION = "分析约定"


@dataclass(frozen=True)
class DeckExhaustionPolicy:
    """牌堆彻底不足时采用的规则及其证据层级。"""

    code: str
    status: RuleStatus
    outcome: str = "游戏平局"


DRAW_EXHAUSTION_RULE = DeckExhaustionPolicy(
    code="draw_exhaustion_rule",
    status=RuleStatus.CURRENT_CONFIRMED,
)
NON_DRAW_DECK_EXHAUSTION_ASSUMPTION = DeckExhaustionPolicy(
    code="non_draw_deck_exhaustion_assumption",
    status=RuleStatus.ANALYSIS_CONVENTION,
)


@dataclass(frozen=True)
class TableCardState(Generic[T]):
    """当前牌堆与各个不会自动参与重洗的区域。

    只有 ``discard_pile`` 会在牌堆不足时参与重洗。其他字段明确保留，
    用于避免把正在结算的牌或其他区域里的牌误并入弃牌堆。
    """

    draw_pile: tuple[T, ...]
    discard_pile: tuple[T, ...]
    resolving_cards: tuple[T, ...] = ()
    hand_cards: tuple[T, ...] = ()
    equipment_cards: tuple[T, ...] = ()
    judgment_cards: tuple[T, ...] = ()
    power_cards: tuple[T, ...] = ()
    special_zone_cards: tuple[T, ...] = ()
    removed_from_game_cards: tuple[T, ...] = ()
    retained_cards: tuple[T, ...] = ()

    def __post_init__(self) -> None:
        for field_name, chinese_name in (
            ("draw_pile", "牌堆"),
            ("discard_pile", "弃牌堆"),
            ("resolving_cards", "正在结算的牌"),
            ("hand_cards", "手牌"),
            ("equipment_cards", "装备区牌"),
            ("judgment_cards", "判定区牌"),
            ("power_cards", "权"),
            ("special_zone_cards", "特殊区域牌"),
            ("removed_from_game_cards", "已移出游戏的牌"),
            ("retained_cards", "被特殊效果保留的牌"),
        ):
            object.__setattr__(
                self,
                field_name,
                _as_tuple(getattr(self, field_name), chinese_name),
            )


@dataclass(frozen=True)
class DeckTakeResult(Generic[T]):
    """一次牌堆顶取得操作的结果。"""

    operation: DeckOperation
    requested_count: int
    cards: tuple[T, ...]
    remaining_state: TableCardState[T]
    reshuffled: bool
    game_tied: bool
    exhaustion_policy: DeckExhaustionPolicy | None

    @property
    def completed(self) -> bool:
        return len(self.cards) == self.requested_count

    @property
    def exhaustion_status(self) -> RuleStatus | None:
        """返回本次平局结论的资料状态；未耗尽时为 ``None``。"""

        if self.exhaustion_policy is None:
            return None
        return self.exhaustion_policy.status

    @property
    def exhaustion_disclosure(self) -> str | None:
        """供模拟报告直接披露规则来源，避免两类耗尽静默合并。"""

        if self.exhaustion_policy is None:
            return None
        return (
            f"{self.exhaustion_policy.code}："
            f"{self.exhaustion_policy.status.value}，结果为{self.exhaustion_policy.outcome}"
        )


def _coerce_deck_operation(value: DeckOperation | str) -> DeckOperation:
    if isinstance(value, DeckOperation):
        return value
    try:
        return DeckOperation(value)
    except (TypeError, ValueError) as exc:
        choices = "、".join(item.value for item in DeckOperation)
        raise ValueError(f"牌堆操作必须是以下之一：{choices}") from exc


def take_top_cards(
    state: TableCardState[T],
    count: int,
    *,
    operation: DeckOperation | str = DeckOperation.DRAW,
    seed: object | None = None,
) -> DeckTakeResult[T]:
    """逐张取得牌堆顶牌，必要时只重洗当前弃牌堆。

    若重洗后仍无法取得下一张所需牌，则返回 ``game_tied=True``。
    恰好取得最后一张且操作已经完成不会判平局。摸牌不足采用
    ``draw_exhaustion_rule``（当前确认）；观看、亮牌和判定不足采用
    ``non_draw_deck_exhaustion_assumption``（分析约定）。调用者必须在
    报告中披露结果携带的策略状态，不能把两者合成“无牌即平局”。
    """

    if not isinstance(state, TableCardState):
        raise TypeError("牌区状态必须是 TableCardState")
    requested = ensure_int_at_least(count, "取得数量", 0)
    resolved_operation = _coerce_deck_operation(operation)
    rng = make_rng(seed)
    draw_pile = list(state.draw_pile)
    discard_pile = list(state.discard_pile)
    cards: list[T] = []
    reshuffled = False

    while len(cards) < requested:
        if not draw_pile:
            if discard_pile:
                rng.shuffle(discard_pile)
                draw_pile = discard_pile
                discard_pile = []
                reshuffled = True
            else:
                break
        cards.append(draw_pile.pop(0))

    remaining = TableCardState(
        draw_pile=tuple(draw_pile),
        discard_pile=tuple(discard_pile),
        resolving_cards=state.resolving_cards,
        hand_cards=state.hand_cards,
        equipment_cards=state.equipment_cards,
        judgment_cards=state.judgment_cards,
        power_cards=state.power_cards,
        special_zone_cards=state.special_zone_cards,
        removed_from_game_cards=state.removed_from_game_cards,
        retained_cards=state.retained_cards,
    )
    game_tied = len(cards) < requested
    exhaustion_policy: DeckExhaustionPolicy | None = None
    if game_tied:
        exhaustion_policy = (
            DRAW_EXHAUSTION_RULE
            if resolved_operation is DeckOperation.DRAW
            else NON_DRAW_DECK_EXHAUSTION_ASSUMPTION
        )
    return DeckTakeResult(
        operation=resolved_operation,
        requested_count=requested,
        cards=tuple(cards),
        remaining_state=remaining,
        reshuffled=reshuffled,
        game_tied=game_tied,
        exhaustion_policy=exhaustion_policy,
    )


def take_bottom_cards(
    state: TableCardState[T],
    count: int,
    *,
    operation: DeckOperation | str = DeckOperation.DRAW,
    seed: object | None = None,
) -> DeckTakeResult[T]:
    """逐张从牌堆底取得牌；用于【寸目】等明确改写摸牌方向的效果。

    多张牌按实际逐张取得顺序返回。牌堆不足时仍只重洗当前弃牌堆，
    重洗完成后继续从新牌堆底取得；彻底不足时沿用同一耗尽规则。
    """

    if not isinstance(state, TableCardState):
        raise TypeError("牌区状态必须是 TableCardState")
    requested = ensure_int_at_least(count, "取得数量", 0)
    resolved_operation = _coerce_deck_operation(operation)
    rng = make_rng(seed)
    draw_pile = list(state.draw_pile)
    discard_pile = list(state.discard_pile)
    cards: list[T] = []
    reshuffled = False

    while len(cards) < requested:
        if not draw_pile:
            if discard_pile:
                rng.shuffle(discard_pile)
                draw_pile = discard_pile
                discard_pile = []
                reshuffled = True
            else:
                break
        cards.append(draw_pile.pop())

    remaining = TableCardState(
        draw_pile=tuple(draw_pile),
        discard_pile=tuple(discard_pile),
        resolving_cards=state.resolving_cards,
        hand_cards=state.hand_cards,
        equipment_cards=state.equipment_cards,
        judgment_cards=state.judgment_cards,
        power_cards=state.power_cards,
        special_zone_cards=state.special_zone_cards,
        removed_from_game_cards=state.removed_from_game_cards,
        retained_cards=state.retained_cards,
    )
    game_tied = len(cards) < requested
    exhaustion_policy: DeckExhaustionPolicy | None = None
    if game_tied:
        exhaustion_policy = (
            DRAW_EXHAUSTION_RULE
            if resolved_operation is DeckOperation.DRAW
            else NON_DRAW_DECK_EXHAUSTION_ASSUMPTION
        )
    return DeckTakeResult(
        operation=resolved_operation,
        requested_count=requested,
        cards=tuple(cards),
        remaining_state=remaining,
        reshuffled=reshuffled,
        game_tied=game_tied,
        exhaustion_policy=exhaustion_policy,
    )


@dataclass(frozen=True)
class DeckSearchResult(Generic[T]):
    """只检索当前牌堆、且不触发弃牌堆重洗的结果。"""

    found: bool
    card: T | None
    remaining_state: TableCardState[T]
    reshuffled: bool = False


def search_current_draw_pile(
    state: TableCardState[T],
    predicate: Callable[[T], bool],
) -> DeckSearchResult[T]:
    """从当前牌堆取得第一张匹配牌；失败时不重洗弃牌堆。"""

    if not isinstance(state, TableCardState):
        raise TypeError("牌区状态必须是 TableCardState")
    if not callable(predicate):
        raise TypeError("检索条件必须是可调用对象")
    draw_pile = list(state.draw_pile)
    found_index: int | None = None
    for index, card in enumerate(draw_pile):
        if predicate(card):
            found_index = index
            break

    card: T | None = None
    if found_index is not None:
        card = draw_pile.pop(found_index)
    remaining = TableCardState(
        draw_pile=tuple(draw_pile),
        discard_pile=state.discard_pile,
        resolving_cards=state.resolving_cards,
        hand_cards=state.hand_cards,
        equipment_cards=state.equipment_cards,
        judgment_cards=state.judgment_cards,
        power_cards=state.power_cards,
        special_zone_cards=state.special_zone_cards,
        removed_from_game_cards=state.removed_from_game_cards,
        retained_cards=state.retained_cards,
    )
    return DeckSearchResult(
        found=found_index is not None,
        card=card,
        remaining_state=remaining,
    )


def _coerce_delayed_trick(value: DelayedTrick | str) -> DelayedTrick:
    if isinstance(value, DelayedTrick):
        return value
    try:
        return DelayedTrick(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("延时锦囊必须是乐不思蜀、兵粮寸断或闪电") from exc


def can_place_delayed_trick(
    card: DelayedTrick | str,
    target_judgment_zone: Iterable[DelayedTrick | str],
) -> bool:
    """检查目标判定区是否已有同名延时锦囊。

    普通使用和技能直接置入均应在落入判定区前调用同一检查。
    """

    resolved = _coerce_delayed_trick(card)
    existing = tuple(
        _coerce_delayed_trick(item)
        for item in _as_tuple(target_judgment_zone, "目标判定区")
    )
    return resolved not in existing


@dataclass(frozen=True)
class SkippedJudgmentPhaseResult:
    """跳过整个判定阶段时延时锦囊的留存结果。"""

    retained_cards: tuple[DelayedTrick, ...]
    nullification_window_entered: bool = False
    judgment_performed: bool = False
    effect_applied: bool = False


def skip_entire_judgment_phase(
    judgment_zone: Iterable[DelayedTrick | str],
) -> SkippedJudgmentPhaseResult:
    """跳过判定阶段：不进无懈时机、不判定，全部原地留存。"""

    retained = tuple(
        _coerce_delayed_trick(item)
        for item in _as_tuple(judgment_zone, "判定区")
    )
    return SkippedJudgmentPhaseResult(retained_cards=retained)


@dataclass(frozen=True)
class DelayedTrickEntry:
    """一张延时锦囊及其进入当前判定区时取得的稳定索引。"""

    card: DelayedTrick
    entry_index: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "card", _coerce_delayed_trick(self.card))
        object.__setattr__(
            self,
            "entry_index",
            ensure_int_at_least(self.entry_index, "延时锦囊进入索引", 1),
        )


@dataclass(frozen=True)
class DelayedTrickZone:
    """保存延时锦囊进入先后的轻量判定区。

    ``entries`` 始终按进入索引递增保存；实际结算时反向读取，实现
    后发先至。``next_entry_index`` 不会因牌被结算或位置交换而回退。
    """

    entries: tuple[DelayedTrickEntry, ...] = ()
    next_entry_index: int = 1

    def __post_init__(self) -> None:
        entries = _as_tuple(self.entries, "延时锦囊判定区记录")
        if any(not isinstance(entry, DelayedTrickEntry) for entry in entries):
            raise TypeError("延时锦囊判定区记录必须由 DelayedTrickEntry 组成")
        indices = tuple(entry.entry_index for entry in entries)
        if indices != tuple(sorted(indices)) or len(set(indices)) != len(indices):
            raise ValueError("延时锦囊进入索引必须唯一并按严格递增顺序保存")
        cards = tuple(entry.card for entry in entries)
        if len(set(cards)) != len(cards):
            raise ValueError("同一角色的判定区内不能存在同名延时锦囊")
        next_index = ensure_int_at_least(
            self.next_entry_index,
            "下一个延时锦囊进入索引",
            1,
        )
        if indices and next_index <= indices[-1]:
            raise ValueError("下一个延时锦囊进入索引必须大于所有既有索引")
        object.__setattr__(self, "entries", entries)
        object.__setattr__(self, "next_entry_index", next_index)

    @property
    def resolution_order(self) -> tuple[DelayedTrickEntry, ...]:
        """按进入索引降序返回后发先至的结算顺序。"""

        return tuple(reversed(self.entries))

    def place(self, card: DelayedTrick | str) -> "DelayedTrickZone":
        """放入一张不同名延时锦囊，并分配不可回退的进入索引。"""

        resolved = _coerce_delayed_trick(card)
        if any(entry.card is resolved for entry in self.entries):
            raise ValueError(f"判定区内已有【{resolved.value}】，不能放入同名延时锦囊")
        entry = DelayedTrickEntry(resolved, self.next_entry_index)
        return DelayedTrickZone(
            entries=self.entries + (entry,),
            next_entry_index=self.next_entry_index + 1,
        )


@dataclass(frozen=True)
class DelayedTrickZoneResolution(Generic[S]):
    """一次判定阶段对多张延时锦囊的顺序处理结果。"""

    processed_entries: tuple[DelayedTrickEntry, ...]
    state_after_each_entry: tuple[S, ...]
    final_state: S
    remaining_zone: DelayedTrickZone
    skipped_judgment_phase: bool
    stopped_by_game_over: bool


def resolve_delayed_trick_zone(
    zone: DelayedTrickZone,
    initial_state: S,
    resolve_one_entry: Callable[[S, DelayedTrickEntry], S],
    is_game_over: Callable[[S], bool],
    *,
    judgment_phase_skipped: bool = False,
) -> DelayedTrickZoneResolution[S]:
    """按 LIFO 逐张调用完整的单牌结算回调。

    ``resolve_one_entry`` 必须在返回前完成当前牌的无懈、判定、去向，
    以及由它引发的伤害、技能、濒死、死亡和胜负状态更新。闪电转移
    也由该回调写入调用方状态；回调返回后，本函数可以继续下一张。
    本函数只维护当前角色判定区的进入顺序，不实现具体卡牌效果。
    """

    if not isinstance(zone, DelayedTrickZone):
        raise TypeError("判定区必须是 DelayedTrickZone")
    if not callable(resolve_one_entry):
        raise TypeError("单张延时锦囊结算器必须是可调用对象")
    if not callable(is_game_over):
        raise TypeError("游戏结束判断器必须是可调用对象")
    if not isinstance(judgment_phase_skipped, bool):
        raise TypeError("是否跳过判定阶段必须是布尔值")

    state = initial_state
    stopped = bool(is_game_over(state))
    if judgment_phase_skipped:
        return DelayedTrickZoneResolution(
            processed_entries=(),
            state_after_each_entry=(),
            final_state=state,
            remaining_zone=zone,
            skipped_judgment_phase=True,
            stopped_by_game_over=stopped,
        )

    processed: list[DelayedTrickEntry] = []
    states: list[S] = []
    if not stopped:
        for entry in zone.resolution_order:
            state = resolve_one_entry(state, entry)
            processed.append(entry)
            states.append(state)
            if is_game_over(state):
                stopped = True
                break

    processed_indices = {entry.entry_index for entry in processed}
    remaining_entries = tuple(
        entry
        for entry in zone.entries
        if entry.entry_index not in processed_indices
    )
    remaining_zone = DelayedTrickZone(
        entries=remaining_entries,
        next_entry_index=zone.next_entry_index,
    )
    return DelayedTrickZoneResolution(
        processed_entries=tuple(processed),
        state_after_each_entry=tuple(states),
        final_state=state,
        remaining_zone=remaining_zone,
        skipped_judgment_phase=False,
        stopped_by_game_over=stopped,
    )


@dataclass(frozen=True)
class LivingSeatRing:
    """由当前座位及存活玩家组成的任意人数环。

    ``occupants_by_current_seat`` 的下标表示当前座位，元素是稳定的玩家
    标识（通常用开局座次）。死亡后玩家标识不改号，只从距离与顺序环
    中过滤；交换位置只交换当前座位上的玩家。
    """

    occupants_by_current_seat: tuple[int, ...]
    alive_players: frozenset[int]

    def __post_init__(self) -> None:
        occupants = _as_tuple(self.occupants_by_current_seat, "当前座次")
        if not occupants:
            raise ValueError("当前座次不能为空")
        for player in occupants:
            ensure_int_at_least(player, "玩家标识", 1)
        if len(set(occupants)) != len(occupants):
            raise ValueError("当前座次中的玩家标识不能重复")
        try:
            alive = frozenset(self.alive_players)
        except TypeError as exc:
            raise TypeError("存活玩家必须是可迭代对象") from exc
        unknown = alive.difference(occupants)
        if unknown:
            names = "、".join(str(player) for player in sorted(unknown))
            raise ValueError(f"存活玩家中存在不在当前座次里的标识：{names}")
        object.__setattr__(self, "occupants_by_current_seat", occupants)
        object.__setattr__(self, "alive_players", alive)

    @classmethod
    def all_alive(cls, player_count: int) -> "LivingSeatRing":
        count = ensure_int_at_least(player_count, "玩家人数", 1)
        occupants = tuple(range(1, count + 1))
        return cls(occupants, frozenset(occupants))

    @property
    def living_order(self) -> tuple[int, ...]:
        """按当前座次数递增方向返回存活玩家，跳过死亡玩家。"""

        return tuple(
            player
            for player in self.occupants_by_current_seat
            if player in self.alive_players
        )

    def current_seat_of(self, player: int) -> int:
        ensure_int_at_least(player, "玩家标识", 1)
        try:
            return self.occupants_by_current_seat.index(player) + 1
        except ValueError as exc:
            raise ValueError(f"玩家 {player} 不在当前座次中") from exc

    def base_distance(self, first_player: int, second_player: int) -> int:
        """在存活角色环上取座次递增、递减两个方向的较小步数。"""

        for player in (first_player, second_player):
            if player not in self.alive_players:
                raise ValueError(f"玩家 {player} 已死亡或不在游戏中，不能计算距离")
        living = self.living_order
        first_index = living.index(first_player)
        second_index = living.index(second_player)
        increasing = (second_index - first_index) % len(living)
        decreasing = (first_index - second_index) % len(living)
        return min(increasing, decreasing)

    def turn_order_from(self, start_player: int) -> tuple[int, ...]:
        """从指定存活玩家开始返回一整轮顺序，自动跳过死亡玩家。"""

        if start_player not in self.alive_players:
            raise ValueError("回合起点必须是当前存活玩家")
        living = self.living_order
        index = living.index(start_player)
        return living[index:] + living[:index]

    def with_player_dead(self, player: int) -> "LivingSeatRing":
        """保留原玩家标识和座位，仅将其移出存活角色环。"""

        self.current_seat_of(player)
        return LivingSeatRing(
            self.occupants_by_current_seat,
            self.alive_players.difference({player}),
        )

    def swap_current_seats(
        self,
        first_seat: int,
        second_seat: int,
    ) -> "LivingSeatRing":
        """交换两个当前位置；玩家标识及存活状态不变。"""

        seat_count = len(self.occupants_by_current_seat)
        for seat in (first_seat, second_seat):
            ensure_int_at_least(seat, "当前座位", 1)
            if seat > seat_count:
                raise ValueError(f"当前座位不能超过 {seat_count}")
        occupants = list(self.occupants_by_current_seat)
        first_index = first_seat - 1
        second_index = second_seat - 1
        occupants[first_index], occupants[second_index] = (
            occupants[second_index],
            occupants[first_index],
        )
        return LivingSeatRing(tuple(occupants), self.alive_players)


class Identity(Enum):
    LORD = "主公"
    LOYALIST = "忠臣"
    REBEL = "反贼"
    SPY = "内奸"


class IdentityVictory(Enum):
    ONGOING = "游戏继续"
    LORD_AND_LOYALISTS = "主公与忠臣获胜"
    REBELS = "反贼获胜"
    SPY = "内奸获胜"


_IDENTITY_COUNTS: Mapping[int, Mapping[Identity, int]] = MappingProxyType(
    {
        5: MappingProxyType(
            {
                Identity.LORD: 1,
                Identity.LOYALIST: 1,
                Identity.REBEL: 2,
                Identity.SPY: 1,
            }
        ),
        8: MappingProxyType(
            {
                Identity.LORD: 1,
                Identity.LOYALIST: 2,
                Identity.REBEL: 4,
                Identity.SPY: 1,
            }
        ),
    }
)


def standard_identity_counts(player_count: int) -> Mapping[Identity, int]:
    """返回本项目明确记录的五人或八人标准身份数量。"""

    ensure_int_at_least(player_count, "玩家人数", 1)
    if player_count not in _IDENTITY_COUNTS:
        raise ValueError("当前资料只展开了五人局和八人局的标准身份数量")
    return _IDENTITY_COUNTS[player_count]


def _coerce_identity(value: Identity | str) -> Identity:
    if isinstance(value, Identity):
        return value
    try:
        return Identity(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("身份必须是主公、忠臣、反贼或内奸") from exc


@dataclass(frozen=True)
class IdentityTable:
    """军争身份分配以及以主公为 1 号位的编号视图。"""

    physical_order: tuple[int, ...]
    identities: Mapping[int, Identity]

    def __post_init__(self) -> None:
        physical = _as_tuple(self.physical_order, "物理环形位置")
        if len(set(physical)) != len(physical) or not physical:
            raise ValueError("物理环形位置必须包含不重复的玩家")
        prepared: dict[int, Identity] = {}
        for player, identity in self.identities.items():
            prepared[player] = _coerce_identity(identity)
        if set(prepared) != set(physical):
            raise ValueError("身份分配必须恰好覆盖全部玩家")
        if sum(role is Identity.LORD for role in prepared.values()) != 1:
            raise ValueError("标准身份分配必须恰好有一名主公")
        object.__setattr__(self, "physical_order", physical)
        object.__setattr__(self, "identities", MappingProxyType(prepared))

    @property
    def lord_player(self) -> int:
        return next(
            player
            for player, identity in self.identities.items()
            if identity is Identity.LORD
        )

    @property
    def numbered_player_order(self) -> tuple[int, ...]:
        """不移动玩家，只把主公处作为 1 号并沿递增方向编号。"""

        index = self.physical_order.index(self.lord_player)
        return self.physical_order[index:] + self.physical_order[:index]

    def seat_number_of(self, player: int) -> int:
        try:
            return self.numbered_player_order.index(player) + 1
        except ValueError as exc:
            raise ValueError(f"玩家 {player} 不在身份桌中") from exc

    def turn_order(self, alive_players: Iterable[int] | None = None) -> tuple[int, ...]:
        """主公先行动，并在后续循环中跳过死亡玩家。"""

        if alive_players is None:
            alive = set(self.physical_order)
        else:
            alive = set(_as_tuple(alive_players, "存活玩家"))
            unknown = alive.difference(self.physical_order)
            if unknown:
                raise ValueError("存活玩家中包含不在身份桌中的玩家")
        return tuple(
            player for player in self.numbered_player_order if player in alive
        )

    def visible_identity(
        self,
        viewer: int,
        target: int,
        *,
        confirmed_dead: Iterable[int] = (),
    ) -> Identity | None:
        """自己、主公及已确认死亡角色身份可见，其余身份隐藏。"""

        if viewer not in self.identities or target not in self.identities:
            raise ValueError("查看者和目标都必须是身份桌中的玩家")
        dead = set(_as_tuple(confirmed_dead, "确认死亡玩家"))
        if target == viewer or target == self.lord_player or target in dead:
            return self.identities[target]
        return None


def deal_standard_identities(
    physical_order: Sequence[int],
    *,
    seed: object | None = None,
) -> IdentityTable:
    """按五人或八人固定构成等概率洗混身份牌。"""

    players = _as_tuple(physical_order, "玩家物理位置")
    counts = standard_identity_counts(len(players))
    cards = [
        identity
        for identity, count in counts.items()
        for _ in range(count)
    ]
    make_rng(seed).shuffle(cards)
    return IdentityTable(players, dict(zip(players, cards, strict=True)))


@dataclass(frozen=True)
class LordHealth:
    maximum_hp: int
    initial_hp: int


def apply_lord_health_bonus(
    base_maximum_hp: int,
    base_initial_hp: int,
) -> LordHealth:
    """把主公初始体力上限和初始体力值同时加 1。"""

    maximum = ensure_int_at_least(base_maximum_hp, "基础体力上限", 1)
    initial = ensure_int_at_least(base_initial_hp, "基础初始体力", 1)
    if initial > maximum:
        raise ValueError("基础初始体力不能超过基础体力上限")
    return LordHealth(maximum + 1, initial + 1)


@dataclass(frozen=True)
class IdentityKillConsequence(Generic[T]):
    draw_count: int
    discarded_hand: tuple[T, ...]
    discarded_equipment: tuple[T, ...]
    retained_judgment: tuple[T, ...]


def resolve_identity_kill_consequence(
    killer_identity: Identity | str,
    victim_identity: Identity | str,
    *,
    killer_hand: Iterable[T] = (),
    killer_equipment: Iterable[T] = (),
    killer_judgment: Iterable[T] = (),
) -> IdentityKillConsequence[T]:
    """计算确认游戏尚未结束后的身份击杀奖惩。

    本函数只计算奖惩本身。完整死亡流程应调用
    :func:`resolve_standard_identity_death`，先检查胜利，再决定是否执行
    本函数。
    """

    killer = _coerce_identity(killer_identity)
    victim = _coerce_identity(victim_identity)
    hand = _as_tuple(killer_hand, "击杀者手牌")
    equipment = _as_tuple(killer_equipment, "击杀者装备")
    judgment = _as_tuple(killer_judgment, "击杀者判定区")
    punish_lord = killer is Identity.LORD and victim is Identity.LOYALIST
    return IdentityKillConsequence(
        draw_count=3 if victim is Identity.REBEL else 0,
        discarded_hand=hand if punish_lord else (),
        discarded_equipment=equipment if punish_lord else (),
        retained_judgment=judgment,
    )


def determine_identity_victory(
    identities: Mapping[int, Identity | str],
    alive_players: Iterable[int],
) -> IdentityVictory:
    """按用户确认的标准身份模式条件判断胜利方或继续游戏。"""

    if not isinstance(identities, Mapping) or not identities:
        raise ValueError("身份映射不能为空")
    prepared = {
        player: _coerce_identity(identity)
        for player, identity in identities.items()
    }
    lords = [
        player for player, identity in prepared.items() if identity is Identity.LORD
    ]
    if len(lords) != 1:
        raise ValueError("身份映射必须恰好包含一名主公")
    alive = set(_as_tuple(alive_players, "存活玩家"))
    if not alive.issubset(prepared):
        raise ValueError("存活玩家中包含未分配身份的玩家")
    lord_alive = lords[0] in alive
    alive_identities = [prepared[player] for player in alive]

    if lord_alive:
        if not any(
            identity in {Identity.REBEL, Identity.SPY}
            for identity in alive_identities
        ):
            return IdentityVictory.LORD_AND_LOYALISTS
        return IdentityVictory.ONGOING

    if len(alive) == 1 and alive_identities[0] is Identity.SPY:
        return IdentityVictory.SPY
    return IdentityVictory.REBELS


def meets_normal_death_condition(
    current_hp: int,
    *,
    rescue_completed: bool,
) -> bool:
    """只判断通常死亡条件，不产生正式死亡或清空区域等副作用。"""

    if isinstance(current_hp, bool) or not isinstance(current_hp, int):
        raise TypeError("当前体力必须是整数")
    if not isinstance(rescue_completed, bool):
        raise TypeError("濒死救援完成标识必须是布尔值")
    return rescue_completed and current_hp < 1


@dataclass(frozen=True)
class DeathStateMachineResult(Generic[S]):
    """通用死亡流程结果，显式保留正式死亡前的模式覆盖窗口。"""

    final_state: S
    current_hp: int
    rescue_completed: bool
    normal_death_condition_met: bool
    before_formal_death_override_count: int
    formal_death_confirmed: bool
    after_formal_death_events_completed: bool
    victory_checked: bool
    game_over: bool
    event_order: tuple[str, ...]


def resolve_death_state_machine(
    initial_state: S,
    *,
    current_hp: int,
    rescue_completed: bool,
    before_formal_death_overrides: Iterable[Callable[[S], S]] = (),
    confirm_formal_death: Callable[[S], S],
    after_formal_death_events: Callable[[S], S] | None = None,
    check_victory: Callable[[S], bool],
) -> DeathStateMachineResult[S]:
    """依次处理通常死亡条件、死亡前覆盖、正式死亡和胜负检查。

    ``before_formal_death_overrides`` 是模式覆盖钩子。八人特殊玩法可在
    这里完成合法储君取牌与继位；此时调用方的原主公区域不得先被清空。
    ``confirm_formal_death`` 才能执行身份公开、区域牌后续去向和退出游戏
    等正式死亡副作用。本函数故意不提供不可插入覆盖规则的单体 ``die``。
    """

    condition_met = meets_normal_death_condition(
        current_hp,
        rescue_completed=rescue_completed,
    )
    if not callable(confirm_formal_death):
        raise TypeError("正式死亡确认器必须是可调用对象")
    if after_formal_death_events is not None and not callable(
        after_formal_death_events
    ):
        raise TypeError("正式死亡后事件处理器必须是可调用对象或 None")
    if not callable(check_victory):
        raise TypeError("胜负检查器必须是可调用对象")
    try:
        overrides = tuple(before_formal_death_overrides)
    except TypeError as exc:
        raise TypeError("正式死亡前模式覆盖必须是可迭代对象") from exc
    if any(not callable(callback) for callback in overrides):
        raise TypeError("每个正式死亡前模式覆盖都必须是可调用对象")

    state = initial_state
    events: list[str] = []
    if not rescue_completed:
        if current_hp < 1:
            events.extend(("进入濒死状态", "濒死救援尚未完成"))
        return DeathStateMachineResult(
            final_state=state,
            current_hp=current_hp,
            rescue_completed=False,
            normal_death_condition_met=False,
            before_formal_death_override_count=0,
            formal_death_confirmed=False,
            after_formal_death_events_completed=False,
            victory_checked=False,
            game_over=False,
            event_order=tuple(events),
        )

    events.append("完成濒死救援")
    if not condition_met:
        events.append("脱离濒死状态")
        return DeathStateMachineResult(
            final_state=state,
            current_hp=current_hp,
            rescue_completed=True,
            normal_death_condition_met=False,
            before_formal_death_override_count=0,
            formal_death_confirmed=False,
            after_formal_death_events_completed=False,
            victory_checked=False,
            game_over=False,
            event_order=tuple(events),
        )

    events.append("满足通常死亡条件")
    for index, callback in enumerate(overrides, start=1):
        state = callback(state)
        events.append(f"完成正式死亡前模式覆盖:{index}")

    state = confirm_formal_death(state)
    events.append("确认正式死亡")
    after_completed = after_formal_death_events is not None
    if after_formal_death_events is not None:
        state = after_formal_death_events(state)
        events.append("完成正式死亡后事件")

    game_over = bool(check_victory(state))
    events.append("检查胜利条件")
    return DeathStateMachineResult(
        final_state=state,
        current_hp=current_hp,
        rescue_completed=True,
        normal_death_condition_met=True,
        before_formal_death_override_count=len(overrides),
        formal_death_confirmed=True,
        after_formal_death_events_completed=after_completed,
        victory_checked=True,
        game_over=game_over,
        event_order=tuple(events),
    )


@dataclass(frozen=True)
class StandardIdentityDeathResolution(Generic[T]):
    """标准身份模式一次确认死亡后的胜利与身份奖惩结果。"""

    victim_player_id: int
    victory: IdentityVictory
    game_over: bool
    identity_consequence_processed: bool
    identity_consequence: IdentityKillConsequence[T] | None


def resolve_standard_identity_death(
    identities: Mapping[int, Identity | str],
    alive_players_after_death: Iterable[int],
    *,
    killer_player_id: int,
    victim_player_id: int,
    killer_hand: Iterable[T] = (),
    killer_equipment: Iterable[T] = (),
    killer_judgment: Iterable[T] = (),
) -> StandardIdentityDeathResolution[T]:
    """先检查胜利，只有游戏继续时才处理身份击杀奖惩。

    调用前应已完成濒死救援、正式死亡确认、当前真实身份确认，以及
    其他直接决定胜利条件的必要状态更新。本函数不统一改写具体武将
    死亡技能的独立时序。
    """

    if not isinstance(identities, Mapping) or not identities:
        raise ValueError("身份映射不能为空")
    killer = ensure_int_at_least(killer_player_id, "击杀者玩家标识", 1)
    victim = ensure_int_at_least(victim_player_id, "死亡玩家标识", 1)
    if killer not in identities:
        raise ValueError("击杀者必须存在于身份映射中")
    if victim not in identities:
        raise ValueError("死亡玩家必须存在于身份映射中")
    alive = frozenset(_as_tuple(alive_players_after_death, "死亡后的存活玩家"))
    if victim in alive:
        raise ValueError("已正式死亡的玩家不能仍在存活玩家集合中")

    victory = determine_identity_victory(identities, alive)
    if victory is not IdentityVictory.ONGOING:
        return StandardIdentityDeathResolution(
            victim_player_id=victim,
            victory=victory,
            game_over=True,
            identity_consequence_processed=False,
            identity_consequence=None,
        )

    consequence = resolve_identity_kill_consequence(
        identities[killer],
        identities[victim],
        killer_hand=killer_hand,
        killer_equipment=killer_equipment,
        killer_judgment=killer_judgment,
    )
    return StandardIdentityDeathResolution(
        victim_player_id=victim,
        victory=victory,
        game_over=False,
        identity_consequence_processed=True,
        identity_consequence=consequence,
    )


@dataclass(frozen=True)
class SequentialResolutionResult(Generic[T, S]):
    """连续效果逐目标完整结算并在游戏结束时停止的结果。"""

    processed_targets: tuple[T, ...]
    state_after_each_target: tuple[S, ...]
    final_state: S
    stopped_by_game_over: bool


def resolve_sequential_effect(
    targets: Iterable[T],
    initial_state: S,
    resolve_one_target: Callable[[S, T], S],
    is_game_over: Callable[[S], bool],
) -> SequentialResolutionResult[T, S]:
    """先完整处理一个目标，再决定是否继续下一个目标。

    ``resolve_one_target`` 应包含该目标伤害、濒死、死亡，以及胜利检查
    所需的身份、继位等状态更新；胜利成立时不得再执行身份击杀奖惩，
    只有游戏继续时才处理相应奖惩。具体武将死亡技能仍按其自身时序
    处理。函数不会把多名角色的死亡合并结算。
    """

    prepared_targets = _as_tuple(targets, "连续结算目标")
    if not callable(resolve_one_target) or not callable(is_game_over):
        raise TypeError("单目标结算器和游戏结束判断器必须是可调用对象")
    state = initial_state
    processed: list[T] = []
    states: list[S] = []
    stopped = bool(is_game_over(state))
    if not stopped:
        for target in prepared_targets:
            state = resolve_one_target(state, target)
            processed.append(target)
            states.append(state)
            if is_game_over(state):
                stopped = True
                break
    return SequentialResolutionResult(
        processed_targets=tuple(processed),
        state_after_each_target=tuple(states),
        final_state=state,
        stopped_by_game_over=stopped,
    )


__all__ = [
    "DRAW_EXHAUSTION_RULE",
    "NON_DRAW_DECK_EXHAUSTION_ASSUMPTION",
    "DeathStateMachineResult",
    "DeckOperation",
    "DeckExhaustionPolicy",
    "DeckSearchResult",
    "DeckTakeResult",
    "DelayedTrickEntry",
    "DelayedTrickZone",
    "DelayedTrickZoneResolution",
    "Identity",
    "IdentityKillConsequence",
    "StandardIdentityDeathResolution",
    "IdentityTable",
    "IdentityVictory",
    "LivingSeatRing",
    "LordHealth",
    "RuleStatus",
    "SequentialResolutionResult",
    "SkippedJudgmentPhaseResult",
    "TableCardState",
    "apply_lord_health_bonus",
    "can_place_delayed_trick",
    "deal_standard_identities",
    "determine_identity_victory",
    "meets_normal_death_condition",
    "resolve_identity_kill_consequence",
    "resolve_death_state_machine",
    "resolve_standard_identity_death",
    "resolve_delayed_trick_zone",
    "resolve_sequential_effect",
    "search_current_draw_pile",
    "skip_entire_judgment_phase",
    "standard_identity_counts",
    "take_bottom_cards",
    "take_top_cards",
]
