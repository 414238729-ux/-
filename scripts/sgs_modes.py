"""三国杀模式规则的轻量计算模型。

本模块只表达项目 Knowledge 中已经记录、且适合独立测试的规则约束。
它不是完整游戏引擎，也不负责推断未提供的客户端实现细节。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Callable, Generic, Iterable, Mapping, Sequence, TypeVar

from ._validation import ensure_int_at_least, make_rng

T = TypeVar("T")
S = TypeVar("S")

SGS_PRIMARY_PLATFORM = "三国杀移动版"
LANDLORD_MULLIGAN_LIMIT = 8
STANDARD_EIGHT_PLAYER_MULLIGAN_LIMIT = 8
STANDARD_EIGHT_PLAYER_IDENTITIES: Mapping[str, int] = MappingProxyType(
    {"主公": 1, "忠臣": 2, "反贼": 4, "内奸": 1}
)
_TWO_V_TWO_PLAYERS = frozenset({1, 2, 3, 4})
_TWO_V_TWO_TEAMMATES = {1: 4, 2: 3, 3: 2, 4: 1}
_TWO_V_TWO_HAND_SIZES = {1: 3, 2: 4, 3: 4, 4: 5}

OMNISCIENT_UPPER_BOUND_MARKER = (
    "理论上限假设，不代表实际游戏信息条件"
)
GENERAL_CANDIDATE_EQUAL_ASSUMPTION_DISCLOSURE = (
    "本次武将候选概率采用等概率计算假设，不代表客户端真实出现权重。"
)
STANDARD_TURN_PHASES = (
    "准备阶段",
    "判定阶段",
    "摸牌阶段",
    "出牌阶段",
    "弃牌阶段",
    "结束阶段",
)
DEFAULT_DRAW_COUNT = 2


@dataclass(frozen=True)
class StandardEightPlayerSetup:
    """普通八人军争的显式默认配置。

    限时“主公立储与内奸择途”只在调用方明确选择对应变体时加载；本
    配置刻意不携带继位、择途或野心家状态机。
    """

    identity_counts: Mapping[str, int] = field(
        default_factory=lambda: STANDARD_EIGHT_PLAYER_IDENTITIES
    )
    mulligan_limit: int = STANDARD_EIGHT_PLAYER_MULLIGAN_LIMIT
    limited_variant_enabled: bool = False

    def __post_init__(self) -> None:
        if dict(self.identity_counts) != dict(STANDARD_EIGHT_PLAYER_IDENTITIES):
            raise ValueError("普通八人军争身份构成必须为主公1、忠臣2、反贼4、内奸1")
        ensure_int_at_least(self.mulligan_limit, "普通八人手气卡次数", 0)
        if self.mulligan_limit != STANDARD_EIGHT_PLAYER_MULLIGAN_LIMIT:
            raise ValueError("当前普通八人军争手气卡上限必须为8次")
        if not isinstance(self.limited_variant_enabled, bool):
            raise TypeError("限时变体开关必须是布尔值")
        if self.limited_variant_enabled:
            raise ValueError("普通八人军争默认配置不能静默启用限时变体")


def standard_eight_player_setup() -> StandardEightPlayerSetup:
    """返回普通八人军争默认规则与最多8次整手重摸口径。"""

    return StandardEightPlayerSetup()


def standard_eight_player_mulligan_limit() -> int:
    return STANDARD_EIGHT_PLAYER_MULLIGAN_LIMIT


class HandVisibility(Enum):
    """一名玩家对另一名玩家具体手牌内容的实际可见性。"""

    VISIBLE = "可见"
    HIDDEN = "隐藏"


@dataclass(frozen=True)
class HandInformationResult:
    """实际信息条件与分析时采用的信息条件。"""

    viewer: int
    target: int
    actual_visibility: HandVisibility
    analysis_visibility: HandVisibility
    omniscient_upper_bound: bool
    assumption_marker: str | None


def _hand_information_result(
    viewer: int,
    target: int,
    actual_visibility: HandVisibility,
    assume_omniscient: bool,
) -> HandInformationResult:
    if not isinstance(assume_omniscient, bool):
        raise TypeError("全知假设开关必须是布尔值")
    uses_hidden_information = (
        assume_omniscient and actual_visibility is HandVisibility.HIDDEN
    )
    return HandInformationResult(
        viewer=viewer,
        target=target,
        actual_visibility=actual_visibility,
        analysis_visibility=(
            HandVisibility.VISIBLE
            if assume_omniscient
            else actual_visibility
        ),
        omniscient_upper_bound=uses_hidden_information,
        assumption_marker=(
            OMNISCIENT_UPPER_BOUND_MARKER
            if uses_hidden_information
            else None
        ),
    )


def two_v_two_hand_information(
    viewer: int,
    target: int,
    *,
    assume_omniscient: bool = False,
) -> HandInformationResult:
    """返回 2v2 手牌信息条件。

    玩家可见自己与固定队友的具体手牌；敌对玩家手牌默认隐藏。交换
    当前座次不改变这里按初始身份确定的固定队友关系。
    """

    _validate_initial_position(viewer)
    _validate_initial_position(target)
    visible = viewer == target or two_v_two_teammate(viewer) == target
    return _hand_information_result(
        viewer,
        target,
        HandVisibility.VISIBLE if visible else HandVisibility.HIDDEN,
        assume_omniscient,
    )


def landlord_hand_information(
    viewer: int,
    target: int,
    *,
    assume_omniscient: bool = False,
) -> HandInformationResult:
    """返回三人斗地主的手牌信息条件。

    1 号位是地主，2、3 号位是农民。除自己的手牌外，任何两名不同
    玩家之间默认隐藏；两名农民也不共享具体手牌。
    """

    _validate_mode_seat(viewer, 3, "查看者座位")
    _validate_mode_seat(target, 3, "目标座位")
    actual = (
        HandVisibility.VISIBLE
        if viewer == target
        else HandVisibility.HIDDEN
    )
    return _hand_information_result(
        viewer,
        target,
        actual,
        assume_omniscient,
    )


@dataclass(frozen=True)
class LandlordHealth:
    """地主身份加成后的体力上限与初始体力。"""

    maximum_hp: int
    initial_hp: int
    applied_before_game_start: bool = True
    counts_as_recovery: bool = False
    emits_in_game_hp_change_event: bool = False
    emits_in_game_maximum_hp_change_event: bool = False


def apply_landlord_health_bonus(
    base_maximum_hp: int,
    base_initial_hp: int,
) -> LandlordHealth:
    """将地主的体力上限和初始体力同时加 1。"""

    ensure_int_at_least(base_maximum_hp, "基础体力上限", 1)
    ensure_int_at_least(base_initial_hp, "基础初始体力", 1)
    if base_initial_hp > base_maximum_hp:
        raise ValueError("基础初始体力不能超过基础体力上限")
    return LandlordHealth(
        maximum_hp=base_maximum_hp + 1,
        initial_hp=base_initial_hp + 1,
    )


def landlord_mulligan_limit() -> int:
    """返回当前三国杀移动版斗地主采用的手气卡次数。"""

    return LANDLORD_MULLIGAN_LIMIT


@dataclass(frozen=True)
class RoundTracker:
    """只追踪正常回合循环的轮次状态。

    ``normal_turn_cycle`` 表示当前轮已经开始的正常回合数量；额外回合
    不修改该值，也不增加 ``round_number``。完成一整轮正常回合后，
    直到下一次正常回合实际开始时才进入下一轮。
    """

    player_count: int
    round_number: int = 1
    normal_turn_cycle: int = 0

    def __post_init__(self) -> None:
        ensure_int_at_least(self.player_count, "玩家人数", 2)
        ensure_int_at_least(self.round_number, "轮次编号", 1)
        ensure_int_at_least(self.normal_turn_cycle, "当前轮正常回合计数", 0)
        if self.normal_turn_cycle > self.player_count:
            raise ValueError("当前轮正常回合计数不能超过玩家人数")


@dataclass(frozen=True)
class TurnOccurrence:
    """一次正常或额外回合开始时的轮次视图。"""

    round_number: int
    normal_turn_cycle: int
    is_extra_turn: bool
    tracker_after_start: RoundTracker


def begin_turn(
    tracker: RoundTracker,
    *,
    is_extra_turn: bool,
) -> TurnOccurrence:
    """开始一个回合；额外回合保持当前轮次与正常循环计数。"""

    if not isinstance(tracker, RoundTracker):
        raise TypeError("轮次状态必须是 RoundTracker")
    if not isinstance(is_extra_turn, bool):
        raise TypeError("额外回合标识必须是布尔值")

    current = tracker
    if is_extra_turn:
        return TurnOccurrence(
            round_number=current.round_number,
            normal_turn_cycle=current.normal_turn_cycle,
            is_extra_turn=True,
            tracker_after_start=current,
        )

    if current.normal_turn_cycle == current.player_count:
        current = RoundTracker(
            player_count=current.player_count,
            round_number=current.round_number + 1,
            normal_turn_cycle=0,
        )
    after = RoundTracker(
        player_count=current.player_count,
        round_number=current.round_number,
        normal_turn_cycle=current.normal_turn_cycle + 1,
    )
    return TurnOccurrence(
        round_number=current.round_number,
        normal_turn_cycle=after.normal_turn_cycle,
        is_extra_turn=False,
        tracker_after_start=after,
    )


def two_v_two_first_round_flying_allowance(
    initial_position: int,
    turn: TurnOccurrence,
) -> int:
    """返回2v2四号位在本回合的首轮专属“飞扬”额度。"""

    _validate_initial_position(initial_position)
    if not isinstance(turn, TurnOccurrence):
        raise TypeError("回合信息必须是 TurnOccurrence")
    return 1 if initial_position == 4 and turn.round_number == 1 else 0


def _validate_player_count(player_count: int) -> int:
    ensure_int_at_least(player_count, "玩家人数", 3)
    if player_count not in (3, 4):
        raise ValueError(
            f"当前轻量座次模型只支持 3 人或 4 人，当前为 {player_count} 人"
        )
    return player_count


def _validate_mode_seat(
    seat: int,
    player_count: int,
    name: str = "座位",
) -> int:
    _validate_player_count(player_count)
    ensure_int_at_least(seat, name, 1)
    if seat > player_count:
        raise ValueError(
            f"{player_count} 人模式的{name}只能为 1 至 {player_count}，"
            f"当前为 {seat}"
        )
    return seat


def increasing_circular_seat_order(
    player_count: int,
    start_seat: int,
) -> tuple[int, ...]:
    """返回从指定座位开始、按数字递增并环绕的一整轮座次。"""

    _validate_player_count(player_count)
    _validate_mode_seat(start_seat, player_count, "起始座位")
    return tuple(
        ((start_seat - 1 + offset) % player_count) + 1
        for offset in range(player_count)
    )


def two_v_two_base_distance(
    first_seat: int,
    second_seat: int,
) -> int:
    """计算 2v2 四座环形座次上的双向最短基础距离。"""

    _validate_mode_seat(first_seat, 4, "第一座位")
    _validate_mode_seat(second_seat, 4, "第二座位")
    clockwise = (second_seat - first_seat) % 4
    counterclockwise = (first_seat - second_seat) % 4
    return min(clockwise, counterclockwise)


def default_hand_limit(current_hp: int) -> int:
    """返回未被技能或其他规则修改时的默认手牌上限。"""

    ensure_int_at_least(current_hp, "当前体力", 0)
    return current_hp


@dataclass(frozen=True)
class StandardTurnDefaults:
    """标准回合阶段、默认摸牌数和默认手牌上限。"""

    phases: tuple[str, ...]
    draw_count: int
    hand_limit: int


def standard_turn_defaults(current_hp: int) -> StandardTurnDefaults:
    """汇总未被其他规则修改时的标准回合默认值。"""

    return StandardTurnDefaults(
        phases=STANDARD_TURN_PHASES,
        draw_count=DEFAULT_DRAW_COUNT,
        hand_limit=default_hand_limit(current_hp),
    )


@dataclass(frozen=True)
class LandlordBidResult:
    """一次合法叫地主过程的结果。

    ``landlord_call_position`` 是随机叫地主顺序中的第几名玩家，从 1
    开始计数，并不是叫地主结束后的座次。
    """

    landlord_call_position: int
    winning_multiplier: int
    bids: tuple[int | None, ...]


def resolve_landlord_bidding(
    bids: Sequence[int | None],
) -> LandlordBidResult:
    """校验斗地主叫价并返回地主。

    ``None`` 表示“不叫”。第一名玩家必须叫 1 倍；后续非空叫价必须
    严格高于当前最高价，且最高为 3 倍。叫到 3 倍后过程立即结束；
    为便于使用固定三元素数组，尾部 ``None`` 占位也被接受。
    """

    if bids is None:
        raise TypeError("叫价序列不能是 None")
    try:
        prepared = tuple(bids)
    except TypeError as exc:
        raise TypeError("叫价必须是可迭代序列") from exc

    if not prepared:
        raise ValueError("叫价序列不能为空，第一名玩家必须叫 1 倍")
    if len(prepared) > 3:
        raise ValueError("斗地主只有三名玩家，叫价记录不能超过 3 项")
    if (
        isinstance(prepared[0], bool)
        or not isinstance(prepared[0], int)
        or prepared[0] != 1
    ):
        raise ValueError("第一名玩家必须叫 1 倍，不能不叫或叫其他倍数")

    highest = 1
    landlord = 1
    ended = False

    for call_position, bid in enumerate(prepared[1:], start=2):
        if ended:
            if bid is not None:
                raise ValueError("已经叫到 3 倍，后续不能继续叫价")
            continue
        if bid is None:
            continue
        if isinstance(bid, bool) or not isinstance(bid, int):
            raise TypeError("叫价必须是整数 1、2、3，或用 None 表示不叫")
        if bid < 1 or bid > 3:
            raise ValueError(f"叫价只能为 1 至 3 倍，当前为 {bid} 倍")
        if bid <= highest:
            raise ValueError(
                f"后续叫价必须严格高于当前最高 {highest} 倍，或选择不叫"
            )
        highest = bid
        landlord = call_position
        ended = bid == 3

    if highest < 3 and len(prepared) < 3:
        raise ValueError("无人叫到 3 倍时，必须提供三名玩家的完整叫价")

    return LandlordBidResult(
        landlord_call_position=landlord,
        winning_multiplier=highest,
        bids=prepared,
    )


def _prepare_landlord_physical_seat_order(
    players: Sequence[T],
) -> tuple[T, T, T]:
    """校验并保留斗地主三名玩家的逆时针物理环形顺序。"""

    if players is None:
        raise TypeError("物理座位顺序不能是 None")
    try:
        prepared = tuple(players)
    except TypeError as exc:
        raise TypeError("物理座位顺序必须是可迭代序列") from exc
    if len(prepared) != 3:
        raise ValueError("斗地主物理座位顺序必须恰好包含三名玩家")
    for player in prepared:
        if player is None or (isinstance(player, str) and not player.strip()):
            raise ValueError("物理座位顺序中的玩家标识不能为空")
        try:
            hash(player)
        except TypeError as exc:
            raise TypeError("物理座位顺序中的玩家标识必须可作为映射键") from exc
    if len(set(prepared)) != 3:
        raise ValueError("物理座位顺序中的三名玩家不能重复")
    return prepared  # type: ignore[return-value]


def choose_landlord_bidding_start(
    physical_seat_order: Sequence[T],
    *,
    seed: object | None = None,
) -> T:
    """从固定物理座位中的三名玩家随机选择首名叫地主者。"""

    order = _prepare_landlord_physical_seat_order(physical_seat_order)
    return make_rng(seed).choice(order)


def build_landlord_bidding_order(
    physical_seat_order: Sequence[T],
    bidding_start_player: T,
) -> tuple[T, T, T]:
    """从首名玩家起，沿固定物理环的逆时针方向建立叫地主顺序。"""

    order = _prepare_landlord_physical_seat_order(physical_seat_order)
    if bidding_start_player not in order:
        raise ValueError("首名叫地主者必须在固定物理座位顺序中")
    start = order.index(bidding_start_player)
    return (
        order[start],
        order[(start + 1) % 3],
        order[(start + 2) % 3],
    )


@dataclass(frozen=True)
class LandlordSeatAssignment(Generic[T]):
    """以地主为1号位重新标记后的确定性座次，不移动物理位置。"""

    physical_seat_order: tuple[T, T, T]
    landlord_player_id: T
    players_by_current_seat: tuple[T, T, T]
    current_seat_number: Mapping[T, int]
    physical_positions_changed: bool = False


def assign_landlord_current_seats(
    physical_seat_order: Sequence[T],
    landlord_player_id: T,
) -> LandlordSeatAssignment[T]:
    """按物理环确定斗地主1、2、3号位，绝不再次随机分配农民。"""

    order = _prepare_landlord_physical_seat_order(physical_seat_order)
    if landlord_player_id not in order:
        raise ValueError("地主必须在固定物理座位顺序中")
    landlord_index = order.index(landlord_player_id)
    seats = (
        order[landlord_index],
        order[(landlord_index + 1) % 3],
        order[(landlord_index + 2) % 3],
    )
    return LandlordSeatAssignment(
        physical_seat_order=order,
        landlord_player_id=landlord_player_id,
        players_by_current_seat=seats,
        current_seat_number=MappingProxyType(
            {player: seat for seat, player in enumerate(seats, start=1)}
        ),
    )


@dataclass(frozen=True)
class LandlordBiddingSeatResult(Generic[T]):
    """一次叫地主过程及其确定性座次映射。"""

    physical_seat_order: tuple[T, T, T]
    bidding_start_player: T
    bidding_order: tuple[T, T, T]
    bid_result: LandlordBidResult
    seat_assignment: LandlordSeatAssignment[T]

    @property
    def landlord_player_id(self) -> T:
        return self.seat_assignment.landlord_player_id


def resolve_landlord_bidding_with_seats(
    physical_seat_order: Sequence[T],
    bidding_start_player: T,
    bids: Sequence[int | None],
) -> LandlordBiddingSeatResult[T]:
    """先按物理环叫价，再由最终地主唯一确定当前座次。"""

    order = _prepare_landlord_physical_seat_order(physical_seat_order)
    bidding_order = build_landlord_bidding_order(order, bidding_start_player)
    bid_result = resolve_landlord_bidding(bids)
    landlord = bidding_order[bid_result.landlord_call_position - 1]
    return LandlordBiddingSeatResult(
        physical_seat_order=order,
        bidding_start_player=bidding_start_player,
        bidding_order=bidding_order,
        bid_result=bid_result,
        seat_assignment=assign_landlord_current_seats(order, landlord),
    )


@dataclass(frozen=True)
class FarmerSeatMarginalAssumption:
    """未建完整过程时，一个指定农民落在2、3号位的边际近似。"""

    seat_2_probability: float = 0.5
    seat_3_probability: float = 0.5
    report_label: str = "计算假设"
    description: str = "未显式模拟叫地主过程时的边际对称近似"
    represents_actual_post_landlord_randomization: bool = False


def symmetric_farmer_seat_marginal_assumption(
    *,
    physical_seat_order_known: bool,
    bidding_start_and_strategy_modeled: bool,
    players_fully_symmetric: bool,
) -> FarmerSeatMarginalAssumption:
    """仅在物理位置与叫地主过程均未建模且玩家对称时返回50%近似。"""

    for value, name in (
        (physical_seat_order_known, "物理座位已知标识"),
        (bidding_start_and_strategy_modeled, "叫地主过程建模标识"),
        (players_fully_symmetric, "玩家完全对称标识"),
    ):
        if not isinstance(value, bool):
            raise TypeError(f"{name}必须是布尔值")
    if physical_seat_order_known or bidding_start_and_strategy_modeled:
        raise ValueError("已有物理座位或叫地主过程时，必须使用确定座次，不能再采用50%简化")
    if not players_fully_symmetric:
        raise ValueError("玩家不完全对称时，不能采用农民2、3号位各50%的边际近似")
    return FarmerSeatMarginalAssumption()


def _prepare_cards(cards: Sequence[T], name: str) -> tuple[T, ...]:
    if cards is None:
        raise TypeError(f"{name}不能是 None")
    try:
        return tuple(cards)
    except TypeError as exc:
        raise TypeError(f"{name}必须是可迭代序列") from exc


def reroll_starting_hand(
    remaining_deck: Sequence[T],
    current_hand: Sequence[T],
    *,
    seed: object | None = None,
) -> list[T]:
    """把当前起始手牌放回剩余牌堆，再等量重抽。

    ``remaining_deck`` 应只包含当前仍在牌堆内的牌；其他玩家已经取得
    且未放回的牌不得传入。返回值不修改任何输入序列。
    """

    prepared_deck = _prepare_cards(remaining_deck, "剩余牌堆")
    prepared_hand = _prepare_cards(current_hand, "当前起始手牌")
    pool = prepared_deck + prepared_hand
    return make_rng(seed).sample(pool, len(prepared_hand))


def two_v_two_starting_hand_size(initial_position: int) -> int:
    """返回 2v2 特殊允许手气卡时，各初始位置的重抽数量。"""

    _validate_initial_position(initial_position)
    return _TWO_V_TWO_HAND_SIZES[initial_position]


def reroll_two_v_two_starting_hand(
    remaining_deck: Sequence[T],
    current_hand: Sequence[T],
    initial_position: int,
    *,
    seed: object | None = None,
) -> list[T]:
    """按初始位置校验数量后执行 2v2 起始手牌重抽。"""

    expected = two_v_two_starting_hand_size(initial_position)
    prepared_hand = _prepare_cards(current_hand, "当前起始手牌")
    if len(prepared_hand) != expected:
        raise ValueError(
            f"2v2 初始 {initial_position} 号位每次应重抽 {expected} 张，"
            f"当前为 {len(prepared_hand)} 张"
        )
    return reroll_starting_hand(
        remaining_deck,
        prepared_hand,
        seed=seed,
    )


def reroll_landlord_starting_hand(
    remaining_deck: Sequence[T],
    current_hand: Sequence[T],
    *,
    seed: object | None = None,
) -> list[T]:
    """校验四张数量后执行斗地主起始手牌重抽。"""

    prepared_hand = _prepare_cards(current_hand, "当前起始手牌")
    if len(prepared_hand) != 4:
        raise ValueError(
            f"斗地主每次应重抽 4 张起始手牌，当前为 {len(prepared_hand)} 张"
        )
    return reroll_starting_hand(
        remaining_deck,
        prepared_hand,
        seed=seed,
    )


def _validate_initial_position(position: int) -> int:
    ensure_int_at_least(position, "初始位置", 1)
    if position not in _TWO_V_TWO_PLAYERS:
        raise ValueError(f"2v2 初始位置只能为 1、2、3、4，当前为 {position}")
    return position


def two_v_two_teammate(initial_player: int) -> int:
    """按开局身份返回固定队友，不受后续座次交换影响。"""

    _validate_initial_position(initial_player)
    return _TWO_V_TWO_TEAMMATES[initial_player]


@dataclass(frozen=True)
class TwoVsTwoTable:
    """2v2 当前座次。

    元组下标代表当前 1 至 4 号座位，元素代表由初始位置标识的玩家。
    因此交换元组元素只改变行动顺序，不改变玩家的固定队友。
    """

    occupants_by_seat: tuple[int, int, int, int] = (1, 2, 3, 4)

    def __post_init__(self) -> None:
        if len(self.occupants_by_seat) != 4:
            raise ValueError(
                "当前座次必须恰好包含初始玩家 1、2、3、4，且不得重复"
            )
        for player in self.occupants_by_seat:
            _validate_initial_position(player)
        if len(set(self.occupants_by_seat)) != 4:
            raise ValueError(
                "当前座次必须恰好包含初始玩家 1、2、3、4，且不得重复"
            )

    @property
    def action_order(self) -> tuple[int, int, int, int]:
        """返回按当前座次 1→2→3→4 的玩家行动顺序。"""

        return self.occupants_by_seat

    def swap_seats(
        self,
        first_seat: int,
        second_seat: int,
    ) -> "TwoVsTwoTable":
        """交换两个当前座位，并返回新的不可变桌面状态。"""

        _validate_current_seat(first_seat)
        _validate_current_seat(second_seat)
        occupants = list(self.occupants_by_seat)
        first_index = first_seat - 1
        second_index = second_seat - 1
        occupants[first_index], occupants[second_index] = (
            occupants[second_index],
            occupants[first_index],
        )
        return TwoVsTwoTable(tuple(occupants))

    def are_teammates(self, first_player: int, second_player: int) -> bool:
        """按两名玩家的初始身份判断固定队友关系。"""

        _validate_initial_position(first_player)
        _validate_initial_position(second_player)
        return two_v_two_teammate(first_player) == second_player

    def seat_of(self, initial_player: int) -> int:
        """返回一名初始身份玩家当前所在的座位。"""

        _validate_initial_position(initial_player)
        return self.occupants_by_seat.index(initial_player) + 1

    def base_distance(
        self,
        first_player: int,
        second_player: int,
    ) -> int:
        """按两名玩家当前座次计算 2v2 环形基础距离。"""

        return two_v_two_base_distance(
            self.seat_of(first_player),
            self.seat_of(second_player),
        )


def _validated_player_modifier_mapping(
    values: Mapping[int, int],
    name: str,
) -> Mapping[int, int]:
    if not isinstance(values, Mapping):
        raise TypeError(f"{name}必须是映射")
    prepared: dict[int, int] = {}
    for player, modifier in values.items():
        _validate_initial_position(player)
        if isinstance(modifier, bool) or not isinstance(modifier, int):
            raise TypeError(f"{name}必须使用整数修正值")
        prepared[player] = modifier
    return MappingProxyType(prepared)


def _validated_pair_modifier_mapping(
    values: Mapping[tuple[int, int], int],
) -> Mapping[tuple[int, int], int]:
    if not isinstance(values, Mapping):
        raise TypeError("定向实际距离修正必须是映射")
    prepared: dict[tuple[int, int], int] = {}
    for pair, modifier in values.items():
        if (
            not isinstance(pair, tuple)
            or len(pair) != 2
        ):
            raise TypeError("定向实际距离修正的键必须是（来源玩家，目标玩家）")
        source, target = pair
        _validate_initial_position(source)
        _validate_initial_position(target)
        if isinstance(modifier, bool) or not isinstance(modifier, int):
            raise TypeError("定向实际距离修正必须使用整数修正值")
        prepared[(source, target)] = modifier
    return MappingProxyType(prepared)


@dataclass(frozen=True)
class TwoVsTwoDistanceState:
    """2v2 当前座次下的实际距离与攻击范围轻量状态。

    ``outgoing_actual_distance_modifiers`` 表示来源计算到其他角色的
    单向修正，例如攻击坐骑为 ``-1``；``incoming_actual_distance_modifiers``
    表示其他角色计算到目标时的单向修正，例如防御坐骑为 ``+1``。
    武器或其他攻击范围效果只写入 ``attack_ranges``，不会混入实际距离。

    本模型只复用已经确认的 2v2 四座基础距离，不推导其他人数模式的
    环形距离公式，也不擅自给距离修正结果设置未提供的下限。
    """

    table: TwoVsTwoTable = field(default_factory=TwoVsTwoTable)
    outgoing_actual_distance_modifiers: Mapping[int, int] = field(
        default_factory=dict
    )
    incoming_actual_distance_modifiers: Mapping[int, int] = field(
        default_factory=dict
    )
    directional_actual_distance_modifiers: Mapping[tuple[int, int], int] = field(
        default_factory=dict
    )
    attack_ranges: Mapping[int, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.table, TwoVsTwoTable):
            raise TypeError("2v2 距离状态必须使用 TwoVsTwoTable 当前座次")
        object.__setattr__(
            self,
            "outgoing_actual_distance_modifiers",
            _validated_player_modifier_mapping(
                self.outgoing_actual_distance_modifiers,
                "来源方向实际距离修正",
            ),
        )
        object.__setattr__(
            self,
            "incoming_actual_distance_modifiers",
            _validated_player_modifier_mapping(
                self.incoming_actual_distance_modifiers,
                "目标方向实际距离修正",
            ),
        )
        object.__setattr__(
            self,
            "directional_actual_distance_modifiers",
            _validated_pair_modifier_mapping(
                self.directional_actual_distance_modifiers
            ),
        )
        ranges = _validated_player_modifier_mapping(
            self.attack_ranges,
            "攻击范围",
        )
        for player, attack_range in ranges.items():
            if attack_range < 1:
                raise ValueError(
                    f"{player} 号玩家的攻击范围必须大于或等于 1"
                )
        object.__setattr__(self, "attack_ranges", ranges)


def get_actual_distance(
    source_player: int,
    target_player: int,
    state: TwoVsTwoDistanceState,
) -> int:
    """按事件发生时的当前座次与实际距离修正计算定向距离。"""

    if not isinstance(state, TwoVsTwoDistanceState):
        raise TypeError("实际距离计算必须使用 TwoVsTwoDistanceState")
    _validate_initial_position(source_player)
    _validate_initial_position(target_player)
    base_distance = state.table.base_distance(source_player, target_player)
    actual_distance = (
        base_distance
        + state.outgoing_actual_distance_modifiers.get(source_player, 0)
        + state.incoming_actual_distance_modifiers.get(target_player, 0)
        + state.directional_actual_distance_modifiers.get(
            (source_player, target_player),
            0,
        )
    )
    if actual_distance < 0:
        raise ValueError("实际距离修正结果不能小于 0，请检查距离修正输入")
    return actual_distance


def is_in_attack_range(
    source_player: int,
    target_player: int,
    state: TwoVsTwoDistanceState,
) -> bool:
    """判断目标是否处于来源的攻击范围内。

    攻击范围只决定允许覆盖的最大实际距离；武器不会回写或降低
    ``get_actual_distance`` 返回的实际距离。
    """

    actual_distance = get_actual_distance(source_player, target_player, state)
    attack_range = state.attack_ranges.get(source_player, 1)
    return actual_distance <= attack_range


def _validate_current_seat(seat: int) -> int:
    ensure_int_at_least(seat, "当前座位", 1)
    if seat > 4:
        raise ValueError(f"2v2 当前座位只能为 1、2、3、4，当前为 {seat}")
    return seat


@dataclass(frozen=True)
class DyingRescueStep:
    """一名座位在濒死救援序列中的处理结果。"""

    seat: int
    hp_before: int
    recovery_amount: int
    hp_after: int


@dataclass(frozen=True)
class DyingRescueResult:
    """一轮濒死救援的轻量结算结果。"""

    dying_seat: int
    initial_hp: int
    final_hp: int
    rescue_order: tuple[int, ...]
    steps: tuple[DyingRescueStep, ...]
    rescued: bool
    death_confirmed: bool
    stopped_at_seat: int | None


def resolve_dying_rescue(
    current_hp: int,
    recoveries_by_seat: Mapping[int, int],
    *,
    player_count: int,
    current_turn_seat: int,
    dying_seat: int,
    living_seats: Iterable[int] | None = None,
) -> DyingRescueResult:
    """从当前回合座次开始，按递增环序处理一整轮救援。

    ``recoveries_by_seat`` 表示各座位在自己此次处理机会中提供的总
    恢复量。``dying_seat`` 只记录濒死角色当前座位，不决定询问起点；
    询问始终从 ``current_turn_seat`` 开始。体力恢复到至少 1 时立即
    停止；完整一轮后仍低于 1 才确认死亡。提供 ``living_seats`` 时，
    已确认死亡的座位会从询问环中移除，其他角色不会因此重新编号。
    """

    if isinstance(current_hp, bool) or not isinstance(current_hp, int):
        raise TypeError("濒死角色当前体力必须是整数")
    if current_hp >= 1:
        raise ValueError("只有当前体力小于 1 的角色才能进入濒死救援")
    if not isinstance(recoveries_by_seat, Mapping):
        raise TypeError("各座位恢复量必须是映射")
    _validate_mode_seat(dying_seat, player_count, "濒死角色座位")

    full_order = increasing_circular_seat_order(
        player_count,
        current_turn_seat,
    )
    if living_seats is None:
        living = frozenset(full_order)
    else:
        prepared_living = _prepare_cards(living_seats, "存活座位")
        if len(prepared_living) != len(set(prepared_living)):
            raise ValueError("存活座位不能重复")
        for seat in prepared_living:
            _validate_mode_seat(seat, player_count, "存活座位")
        living = frozenset(prepared_living)
        if current_turn_seat not in living:
            raise ValueError("当前回合座位必须属于存活座位")
        if dying_seat not in living:
            raise ValueError("尚在濒死救援中的角色必须属于存活座位")
    order = tuple(seat for seat in full_order if seat in living)
    recoveries: dict[int, int] = {}
    for seat, amount in recoveries_by_seat.items():
        _validate_mode_seat(seat, player_count, "救援座位")
        if seat not in living:
            raise ValueError(f"已确认死亡的 {seat} 号位不能参与濒死救援")
        ensure_int_at_least(amount, f"{seat} 号位恢复量", 0)
        recoveries[seat] = amount

    hp = current_hp
    steps: list[DyingRescueStep] = []
    for seat in order:
        amount = recoveries.get(seat, 0)
        before = hp
        hp += amount
        steps.append(
            DyingRescueStep(
                seat=seat,
                hp_before=before,
                recovery_amount=amount,
                hp_after=hp,
            )
        )
        if hp >= 1:
            return DyingRescueResult(
                dying_seat=dying_seat,
                initial_hp=current_hp,
                final_hp=hp,
                rescue_order=order,
                steps=tuple(steps),
                rescued=True,
                death_confirmed=False,
                stopped_at_seat=seat,
            )

    return DyingRescueResult(
        dying_seat=dying_seat,
        initial_hp=current_hp,
        final_hp=hp,
        rescue_order=order,
        steps=tuple(steps),
        rescued=False,
        death_confirmed=True,
        stopped_at_seat=None,
    )


@dataclass(frozen=True)
class MandatoryDrawReward:
    """2v2 队友死亡后的强制摸牌奖励。"""

    recipient: int
    draw_count: int = 1
    may_decline: bool = False


def two_v_two_death_reward(
    dead_player: int,
    living_players: Iterable[int],
    *,
    death_confirmed: bool = True,
) -> MandatoryDrawReward | None:
    """在确认死亡后，按固定队友身份计算 2v2 奖励。

    若死者的固定队友也已不存活，则没有可领取奖励的角色，返回
    ``None``。该函数不接受“放弃奖励”选项。
    """

    _validate_initial_position(dead_player)
    if not isinstance(death_confirmed, bool):
        raise TypeError("死亡确认状态必须是布尔值")
    if not death_confirmed:
        return None
    if living_players is None:
        raise TypeError("存活玩家集合不能是 None")
    try:
        living = tuple(living_players)
    except TypeError as exc:
        raise TypeError("存活玩家必须是可迭代对象") from exc
    for player in living:
        _validate_initial_position(player)
    if len(living) != len(set(living)):
        raise ValueError("存活玩家集合中不能出现重复玩家")
    if dead_player in living:
        raise ValueError("已确认死亡的玩家不能同时出现在存活玩家集合中")

    teammate = two_v_two_teammate(dead_player)
    if teammate not in living:
        return None
    return MandatoryDrawReward(recipient=teammate)


class FarmerRewardChoice(Enum):
    """斗地主农民队友死亡后的三种合法选择。"""

    RECOVER_ONE = "回复1点体力"
    DRAW_TWO = "摸2张牌"
    DECLINE_BOTH = "两项都不要"


@dataclass(frozen=True)
class FarmerDeathReward:
    """一次合法的农民死亡奖励结算结果。"""

    choice: FarmerRewardChoice
    recover_amount: int
    draw_count: int


def resolve_farmer_death_reward(
    choice: FarmerRewardChoice | str,
    *,
    death_confirmed: bool = True,
) -> FarmerDeathReward | None:
    """把农民的三选一选择转换为轻量数值结果。"""

    if not isinstance(death_confirmed, bool):
        raise TypeError("死亡确认状态必须是布尔值")
    if not death_confirmed:
        return None
    if not isinstance(choice, FarmerRewardChoice):
        try:
            choice = FarmerRewardChoice(choice)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "农民死亡奖励只能选择“回复1点体力”“摸2张牌”"
                "或“两项都不要”，不能同时回血和摸牌"
            ) from exc

    if choice is FarmerRewardChoice.RECOVER_ONE:
        return FarmerDeathReward(choice, recover_amount=1, draw_count=0)
    if choice is FarmerRewardChoice.DRAW_TWO:
        return FarmerDeathReward(choice, recover_amount=0, draw_count=2)
    return FarmerDeathReward(choice, recover_amount=0, draw_count=0)


@dataclass(frozen=True)
class OrderedStateStep(Generic[S]):
    """一名座位处理前后承接的状态。"""

    seat: int
    state_before: S
    state_after: S
    handled: bool


@dataclass(frozen=True)
class OrderedStateResult(Generic[S]):
    """多人按座次依次处理并传递状态的结果。"""

    initial_state: S
    final_state: S
    processing_order: tuple[int, ...]
    steps: tuple[OrderedStateStep[S], ...]


def resolve_ordered_responses(
    initial_state: S,
    handlers_by_seat: Mapping[int, Callable[[S], S]],
    *,
    player_count: int,
    current_turn_seat: int,
    living_seats: Iterable[int] | None = None,
) -> OrderedStateResult[S]:
    """按当前回合座次起的递增环序传递多人响应状态。

    每名存在处理函数的玩家都会读取前一名玩家更新后的状态。没有
    处理函数的座位视为不响应，状态原样传给下一座位。提供
    ``living_seats`` 时，已确认死亡的座位不参与处理；存活角色仍使用
    原有座位编号。
    """

    if not isinstance(handlers_by_seat, Mapping):
        raise TypeError("各座位处理函数必须是映射")
    full_order = increasing_circular_seat_order(
        player_count,
        current_turn_seat,
    )
    if living_seats is None:
        living = frozenset(full_order)
    else:
        prepared_living = _prepare_cards(living_seats, "存活座位")
        if len(prepared_living) != len(set(prepared_living)):
            raise ValueError("存活座位不能重复")
        for seat in prepared_living:
            _validate_mode_seat(seat, player_count, "存活座位")
        living = frozenset(prepared_living)
        if current_turn_seat not in living:
            raise ValueError("当前回合座位必须属于存活座位")
    order = tuple(seat for seat in full_order if seat in living)
    handlers: dict[int, Callable[[S], S]] = {}
    for seat, handler in handlers_by_seat.items():
        _validate_mode_seat(seat, player_count, "响应座位")
        if seat not in living:
            raise ValueError(f"已确认死亡的 {seat} 号位不能参与多人响应")
        if not callable(handler):
            raise TypeError(f"{seat} 号位的处理函数必须可调用")
        handlers[seat] = handler

    state = initial_state
    steps: list[OrderedStateStep[S]] = []
    for seat in order:
        before = state
        handler = handlers.get(seat)
        state = before if handler is None else handler(before)
        steps.append(
            OrderedStateStep(
                seat=seat,
                state_before=before,
                state_after=state,
                handled=handler is not None,
            )
        )

    return OrderedStateResult(
        initial_state=initial_state,
        final_state=state,
        processing_order=order,
        steps=tuple(steps),
    )


def resolve_judgment_retrials(
    initial_judgment: S,
    retrials_by_seat: Mapping[int, Callable[[S], S]],
    *,
    player_count: int,
    current_turn_seat: int,
    living_seats: Iterable[int] | None = None,
) -> OrderedStateResult[S]:
    """依序处理存活角色的改判；每次均读取此前最新判定结果。"""

    return resolve_ordered_responses(
        initial_judgment,
        retrials_by_seat,
        player_count=player_count,
        current_turn_seat=current_turn_seat,
        living_seats=living_seats,
    )


def _prepare_generals(
    generals: Sequence[str],
    name: str,
) -> tuple[str, ...]:
    if generals is None:
        raise TypeError(f"{name}不能是 None")
    try:
        prepared = tuple(generals)
    except TypeError as exc:
        raise TypeError(f"{name}必须是可迭代序列") from exc
    if not prepared:
        raise ValueError(f"{name}不能为空")
    if any(
        not isinstance(general, str) or not general.strip()
        for general in prepared
    ):
        raise ValueError(f"{name}中的武将名必须是非空字符串")
    if len(prepared) != len(set(prepared)):
        raise ValueError(f"{name}中不能出现重复武将")
    return prepared


@dataclass(frozen=True)
class AutomaticGeneralSelection:
    """断线自动确认时采用的候选武将。"""

    selected_general: str
    used_clicked_candidate: bool
    used_first_candidate_fallback: bool


def resolve_disconnected_general_selection(
    current_candidates: Sequence[str],
    *,
    clicked_general: str | None = None,
) -> AutomaticGeneralSelection:
    """断线时优先采用已点击候选，否则采用候选列表第一名。"""

    candidates = _prepare_generals(current_candidates, "当前候选框")
    if clicked_general is None:
        return AutomaticGeneralSelection(
            selected_general=candidates[0],
            used_clicked_candidate=False,
            used_first_candidate_fallback=True,
        )
    if not isinstance(clicked_general, str) or not clicked_general.strip():
        raise ValueError("已点击候选武将必须是非空字符串或 None")
    if clicked_general not in candidates:
        raise ValueError("已点击武将必须仍在当前候选列表中")
    return AutomaticGeneralSelection(
        selected_general=clicked_general,
        used_clicked_candidate=True,
        used_first_candidate_fallback=False,
    )


@dataclass(frozen=True)
class CandidateSelectionSimulationScope:
    """固定阵容与候选、断线流程的模拟开关。"""

    fixed_lineup: bool
    random_candidate_generation_loaded: bool
    disconnect_auto_selection_loaded: bool


def candidate_selection_simulation_scope(
    *,
    fixed_lineup: bool,
    include_random_candidate_generation: bool = False,
    include_disconnect_auto_selection: bool = False,
) -> CandidateSelectionSimulationScope:
    """固定阵容时强制排除随机候选和断线自动选择流程。"""

    for value, name in (
        (fixed_lineup, "固定阵容标识"),
        (include_random_candidate_generation, "随机候选开关"),
        (include_disconnect_auto_selection, "断线自动选择开关"),
    ):
        if not isinstance(value, bool):
            raise TypeError(f"{name}必须是布尔值")
    return CandidateSelectionSimulationScope(
        fixed_lineup=fixed_lineup,
        random_candidate_generation_loaded=(
            False if fixed_lineup else include_random_candidate_generation
        ),
        disconnect_auto_selection_loaded=(
            False if fixed_lineup else include_disconnect_auto_selection
        ),
    )


@dataclass(frozen=True)
class GeneralCandidateProbabilityContext:
    """客户端真实分布与本次模拟口径的分层记录。"""

    actual_distribution: str
    actual_weights_known: bool
    fixed_lineup: bool
    simulate_appearance_probability: bool
    simulation_distribution: str | None
    disclosure: str


def general_candidate_probability_context(
    *,
    fixed_lineup: bool,
) -> GeneralCandidateProbabilityContext:
    """返回武将候选概率的当前证据与模拟口径。

    用户已确认客户端真实出现概率不是等概率，但完整权重未知。只有
    确实需要随机生成合法候选时才采用等概率模拟假设；固定阵容不计算
    武将被刷出的概率。
    """

    if not isinstance(fixed_lineup, bool):
        raise TypeError("固定阵容标识必须是布尔值")
    if fixed_lineup:
        return GeneralCandidateProbabilityContext(
            actual_distribution="非等概率",
            actual_weights_known=False,
            fixed_lineup=True,
            simulate_appearance_probability=False,
            simulation_distribution=None,
            disclosure="参战武将已固定，本次不计算武将刷出概率。",
        )
    return GeneralCandidateProbabilityContext(
        actual_distribution="非等概率",
        actual_weights_known=False,
        fixed_lineup=False,
        simulate_appearance_probability=True,
        simulation_distribution="合法候选等概率",
        disclosure=GENERAL_CANDIDATE_EQUAL_ASSUMPTION_DISCLOSURE,
    )


def eligible_replacement_generals(
    unlocked_generals: Sequence[str],
    current_candidates: Sequence[str],
    slot_index: int,
) -> tuple[str, ...]:
    """返回某候选框换将时的等概率候选集合。

    ``slot_index`` 使用从 0 开始的 Python 下标。本次替换先排除当前
    所有候选框仍显示的武将；目标框原武将在后续替换中只要不再显示，
    就可以再次进入候选集合。这里的等概率只是调用者选择采用的模拟
    假设。
    """

    unlocked = _prepare_generals(unlocked_generals, "已开启武将池")
    current = _prepare_generals(current_candidates, "当前候选框")
    ensure_int_at_least(slot_index, "候选框下标", 0)
    if slot_index >= len(current):
        raise ValueError(
            f"候选框下标越界，当前为 {slot_index}，"
            f"候选框数量为 {len(current)}"
        )
    missing = [general for general in current if general not in unlocked]
    if missing:
        raise ValueError(
            "当前候选框包含未在已开启武将池中的武将："
            + "、".join(missing)
        )

    currently_displayed = set(current)
    eligible = tuple(
        general
        for general in unlocked
        if general not in currently_displayed
    )
    if not eligible:
        raise ValueError("排除当前候选框后，没有可用于换将的武将")
    return eligible


@dataclass(frozen=True)
class GeneralReplacementResult:
    """一次候选武将框替换的结果。"""

    slot_index: int
    previous_general: str
    new_general: str
    candidates: tuple[str, ...]
    probability_assumption: str = "合法候选等概率"
    assumption_disclosure: str = (
        GENERAL_CANDIDATE_EQUAL_ASSUMPTION_DISCLOSURE
    )
    represents_actual_client_weights: bool = False


def replace_general_candidate(
    unlocked_generals: Sequence[str],
    current_candidates: Sequence[str],
    slot_index: int,
    *,
    seed: object | None = None,
) -> GeneralReplacementResult:
    """按等概率模拟假设替换一个候选框，使用独立随机数生成器。"""

    current = _prepare_generals(current_candidates, "当前候选框")
    eligible = eligible_replacement_generals(
        unlocked_generals,
        current,
        slot_index,
    )
    selected = make_rng(seed).choice(eligible)
    updated = list(current)
    previous = updated[slot_index]
    updated[slot_index] = selected
    return GeneralReplacementResult(
        slot_index=slot_index,
        previous_general=previous,
        new_general=selected,
        candidates=tuple(updated),
    )
