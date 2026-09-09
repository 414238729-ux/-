"""三国杀团队协作、救援与【无懈可击】信息的轻量策略模型。

本模块只保存可解释、可复现的策略状态，不把策略阈值描述成游戏规则。
它不读取隐藏手牌，也不尝试建立完整游戏引擎。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Hashable, Iterable, Mapping, Sequence

from ._validation import ensure_finite_real, ensure_int_at_least


PlayerId = Hashable


def _require_player_id(value: PlayerId, name: str = "玩家标识") -> PlayerId:
    if value is None or (isinstance(value, str) and not value.strip()):
        raise ValueError(f"{name}不能为空")
    try:
        hash(value)
    except TypeError as exc:
        raise TypeError(f"{name}必须可作为映射键") from exc
    return value


def _unique_player_ids(
    values: Iterable[PlayerId],
    name: str,
) -> tuple[PlayerId, ...]:
    if values is None:
        raise TypeError(f"{name}不能为 None")
    try:
        prepared = tuple(values)
    except TypeError as exc:
        raise TypeError(f"{name}必须是可迭代对象") from exc
    seen: set[PlayerId] = set()
    for value in prepared:
        _require_player_id(value, name)
        if value in seen:
            raise ValueError(f"{name}不能包含重复玩家：{value}")
        seen.add(value)
    return prepared


def _ensure_bool(value: object, name: str) -> bool:
    if not isinstance(value, bool):
        raise TypeError(f"{name}必须是布尔值")
    return value


class FarmerPeachSignal(str, Enum):
    """历史分析数据兼容枚举，不是当前运行层自动共享桃的权限。"""

    HAS_PEACH = "has_peach"
    NO_PEACH = "no_peach"
    UNKNOWN = "unknown"


def _coerce_farmer_signal(
    signal: FarmerPeachSignal | str,
) -> FarmerPeachSignal:
    if isinstance(signal, FarmerPeachSignal):
        return signal
    try:
        return FarmerPeachSignal(signal)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "农民桃信号只能是 has_peach、no_peach 或 unknown"
        ) from exc


@dataclass(frozen=True)
class FarmerPeachKnowledge:
    """历史独立分析对象；production改用绑定语境的公开YES/NO问答。

    ``has_peach`` 只证明至少一张，不公开精确数量或其他手牌。
    """

    player_id: PlayerId
    signal: FarmerPeachSignal | str
    knowledge_source: str = "送花或砸蛋"

    def __post_init__(self) -> None:
        _require_player_id(self.player_id)
        object.__setattr__(self, "signal", _coerce_farmer_signal(self.signal))
        if not isinstance(self.knowledge_source, str) or not self.knowledge_source.strip():
            raise ValueError("桃信号来源不能为空")

    @property
    def minimum_known_peaches(self) -> int:
        return 1 if self.signal is FarmerPeachSignal.HAS_PEACH else 0

    @property
    def exact_quantity_known(self) -> bool:
        return self.signal is FarmerPeachSignal.NO_PEACH

    @property
    def discloses_other_cards(self) -> bool:
        return False

    def after_observed_peach_use(self) -> "FarmerPeachKnowledge":
        """实际使用一张后将剩余数量恢复为未知，而非武断记为零。"""

        if self.signal is not FarmerPeachSignal.HAS_PEACH:
            raise ValueError("只有已表达有桃的玩家才能据此记录一次桃的使用")
        return FarmerPeachKnowledge(
            self.player_id,
            FarmerPeachSignal.UNKNOWN,
            "已观察使用一张桃，剩余数量未知",
        )


@dataclass(frozen=True)
class FarmerSlashCountKnowledge:
    """历史分析的精确数量容器，保留以兼容旧计算资料和测试。

    当前规则禁止通用农民杀数查询/共享；不能把本类型存在视为权限。
    鲍信只允许具体公开方案命题，详见 knowledge/三国杀AI信息规则.md。
    """

    player_id: PlayerId
    current_slash_count: int | None
    knowledge_source: str = "送花或砸蛋"

    def __post_init__(self) -> None:
        _require_player_id(self.player_id)
        if self.current_slash_count is not None:
            ensure_int_at_least(self.current_slash_count, "农民当前杀数量", 0)
        if not isinstance(self.knowledge_source, str) or not self.knowledge_source.strip():
            raise ValueError("杀数量信号来源不能为空")

    @property
    def exact_quantity_known(self) -> bool:
        return self.current_slash_count is not None

    def after_hand_change(self) -> "FarmerSlashCountKnowledge":
        """手牌变化后旧的精确数量失效，等待下一次客户端信号刷新。"""

        return FarmerSlashCountKnowledge(
            self.player_id,
            None,
            "手牌已变化，旧杀数量信号失效",
        )

    @property
    def discloses_other_card_names(self) -> bool:
        return False

    @property
    def discloses_suits_or_ranks(self) -> bool:
        return False


@dataclass(frozen=True)
class FarmerCoordinationKnowledge:
    """历史分析容器；当前production不导入此自动资源合并模型。"""

    peach: FarmerPeachKnowledge
    slash: FarmerSlashCountKnowledge

    def __post_init__(self) -> None:
        if not isinstance(self.peach, FarmerPeachKnowledge):
            raise TypeError("桃信息必须使用 FarmerPeachKnowledge")
        if not isinstance(self.slash, FarmerSlashCountKnowledge):
            raise TypeError("杀信息必须使用 FarmerSlashCountKnowledge")
        if self.peach.player_id != self.slash.player_id:
            raise ValueError("桃信号和杀数量信号必须属于同一名农民")

    @property
    def reveals_full_hand(self) -> bool:
        return False


class RescueResourceKind(str, Enum):
    """能够进入团队救援计算的资源类型。"""

    PEACH = "peach"
    SELF_WINE = "self_wine"
    SKILL = "skill"


def _coerce_rescue_kind(
    value: RescueResourceKind | str,
) -> RescueResourceKind:
    if isinstance(value, RescueResourceKind):
        return value
    try:
        return RescueResourceKind(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("救援资源类型只能是 peach、self_wine 或 skill") from exc


@dataclass(frozen=True)
class RescueResource:
    """当前通过合法信息确认可用的一组同类救援资源。"""

    resource_id: str
    owner_id: PlayerId
    kind: RescueResourceKind | str
    available_uses: int = 1
    healing_per_use: int = 1
    preservation_cost: float = 1.0
    legal_target_ids: frozenset[PlayerId] | None = None
    known_available: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.resource_id, str) or not self.resource_id.strip():
            raise ValueError("救援资源标识不能为空")
        _require_player_id(self.owner_id, "救援资源持有者")
        object.__setattr__(self, "kind", _coerce_rescue_kind(self.kind))
        ensure_int_at_least(self.available_uses, "救援资源可用次数", 1)
        ensure_int_at_least(self.healing_per_use, "每次救援回复量", 1)
        object.__setattr__(
            self,
            "preservation_cost",
            ensure_finite_real(self.preservation_cost, "救援资源保留成本"),
        )
        if self.preservation_cost < 0:
            raise ValueError("救援资源保留成本不能小于 0")
        _ensure_bool(self.known_available, "救援资源已确认标识")
        if self.legal_target_ids is not None:
            targets = frozenset(
                _unique_player_ids(self.legal_target_ids, "救援合法目标")
            )
            object.__setattr__(self, "legal_target_ids", targets)


def rescue_resource_from_farmer_signal(
    knowledge: FarmerPeachKnowledge,
    *,
    resource_id: str | None = None,
) -> RescueResource | None:
    """把“有桃”信号转换成恰好一份最低保证量，不猜测更多张数。"""

    if not isinstance(knowledge, FarmerPeachKnowledge):
        raise TypeError("农民桃信息必须使用 FarmerPeachKnowledge 表示")
    if knowledge.signal is not FarmerPeachSignal.HAS_PEACH:
        return None
    return RescueResource(
        resource_id or f"{knowledge.player_id}:peach-signal",
        knowledge.player_id,
        RescueResourceKind.PEACH,
        available_uses=1,
        preservation_cost=1.0,
    )


@dataclass(frozen=True)
class RescueUse:
    resource_id: str
    owner_id: PlayerId
    kind: RescueResourceKind
    uses: int
    total_healing: int
    total_preservation_cost: float


@dataclass(frozen=True)
class TeamRescuePlan:
    """基于合法已知资源产生的最小资源救援计划。"""

    required_recovery: int
    known_legal_healing: int
    can_guarantee_rescue: bool
    must_rescue: bool
    selected_uses: tuple[RescueUse, ...]
    excluded_resource_ids: tuple[str, ...]
    expected_hp_after: int
    explanation: str


@dataclass(frozen=True)
class _ResourceUnit:
    resource_index: int
    use_index: int
    resource: RescueResource


def _legal_rescue_resources(
    dying_player_id: PlayerId,
    team_ids: frozenset[PlayerId],
    resources: Sequence[RescueResource],
) -> tuple[tuple[RescueResource, ...], tuple[str, ...]]:
    legal: list[RescueResource] = []
    excluded: list[str] = []
    seen_ids: set[str] = set()
    for resource in resources:
        if not isinstance(resource, RescueResource):
            raise TypeError("救援资源必须使用 RescueResource 表示")
        if resource.resource_id in seen_ids:
            raise ValueError(f"救援资源标识不能重复：{resource.resource_id}")
        seen_ids.add(resource.resource_id)
        allowed = resource.known_available and resource.owner_id in team_ids
        if resource.kind is RescueResourceKind.SELF_WINE:
            allowed = allowed and resource.owner_id == dying_player_id
        if resource.legal_target_ids is not None:
            allowed = allowed and dying_player_id in resource.legal_target_ids
        if allowed:
            legal.append(resource)
        else:
            excluded.append(resource.resource_id)
    return tuple(legal), tuple(excluded)


def _plan_minimum_rescue_units(
    required_recovery: int,
    legal_resources: Sequence[RescueResource],
) -> tuple[_ResourceUnit, ...] | None:
    units = tuple(
        _ResourceUnit(resource_index, use_index, resource)
        for resource_index, resource in enumerate(legal_resources)
        for use_index in range(resource.available_uses)
    )
    # 每个已达回复量只保留“使用次数最少、保留成本最低、顺序稳定”的方案。
    states: dict[int, tuple[_ResourceUnit, ...]] = {0: ()}

    def key(candidate: tuple[_ResourceUnit, ...]) -> tuple[object, ...]:
        return (
            len(candidate),
            sum(unit.resource.preservation_cost for unit in candidate),
            tuple((unit.resource_index, unit.use_index) for unit in candidate),
        )

    for unit in units:
        next_states = dict(states)
        for healed, chosen in states.items():
            new_healed = min(
                required_recovery,
                healed + unit.resource.healing_per_use,
            )
            candidate = chosen + (unit,)
            incumbent = next_states.get(new_healed)
            if incumbent is None or key(candidate) < key(incumbent):
                next_states[new_healed] = candidate
        states = next_states
    return states.get(required_recovery)


def plan_team_rescue(
    current_hp: int,
    dying_player_id: PlayerId,
    teammate_ids: Iterable[PlayerId],
    resources: Sequence[RescueResource],
    *,
    game_ended: bool = False,
    rescue_forbidden: bool = False,
) -> TeamRescuePlan:
    """以合法已知资源判断是否确定可救，并给出最少资源计划。

    队友的【酒】会被明确排除；只有濒死者本人持有的【酒】能作为自救资源。
    当已知资源足够、游戏未结束且救援未被禁止时，``must_rescue`` 必为真。
    """

    if isinstance(current_hp, bool) or not isinstance(current_hp, int):
        raise TypeError("濒死角色当前体力必须是整数")
    if current_hp > 0:
        raise ValueError("团队救援计划只适用于体力不大于 0 的濒死角色")
    _require_player_id(dying_player_id, "濒死角色标识")
    teammates = _unique_player_ids(teammate_ids, "队友标识")
    if dying_player_id in teammates:
        raise ValueError("队友列表不应重复包含濒死角色本人")
    if resources is None:
        raise TypeError("救援资源不能为 None")
    try:
        prepared_resources = tuple(resources)
    except TypeError as exc:
        raise TypeError("救援资源必须是可迭代对象") from exc
    _ensure_bool(game_ended, "游戏已结束标识")
    _ensure_bool(rescue_forbidden, "救援被禁止标识")

    required = 1 - current_hp
    team_ids = frozenset((dying_player_id, *teammates))
    legal, excluded = _legal_rescue_resources(
        dying_player_id,
        team_ids,
        prepared_resources,
    )
    known_healing = sum(
        resource.available_uses * resource.healing_per_use
        for resource in legal
    )

    if game_ended:
        return TeamRescuePlan(
            required,
            known_healing,
            known_healing >= required,
            False,
            (),
            excluded,
            current_hp,
            "游戏已经结束，不再开始救援",
        )
    if rescue_forbidden:
        return TeamRescuePlan(
            required,
            known_healing,
            known_healing >= required,
            False,
            (),
            excluded,
            current_hp,
            "规则或技能明确禁止本次救援",
        )

    chosen = _plan_minimum_rescue_units(required, legal)
    if chosen is None:
        return TeamRescuePlan(
            required,
            known_healing,
            False,
            False,
            (),
            excluded,
            current_hp,
            "合法已知救援资源不足，不能保证将队友恢复至至少 1 点体力",
        )

    grouped: dict[str, list[_ResourceUnit]] = {}
    for unit in chosen:
        grouped.setdefault(unit.resource.resource_id, []).append(unit)
    uses = tuple(
        RescueUse(
            resource_id=members[0].resource.resource_id,
            owner_id=members[0].resource.owner_id,
            kind=members[0].resource.kind,
            uses=len(members),
            total_healing=(
                len(members) * members[0].resource.healing_per_use
            ),
            total_preservation_cost=(
                len(members) * members[0].resource.preservation_cost
            ),
        )
        for members in grouped.values()
    )
    total_healing = sum(item.total_healing for item in uses)
    return TeamRescuePlan(
        required,
        known_healing,
        True,
        True,
        uses,
        excluded,
        current_hp + total_healing,
        "合法已知资源足够救活明确队友，必须按最少资源方案完成救援",
    )


class NullificationAvailability(str, Enum):
    """某个响应窗口中对一名角色可用【无懈可击】的知识。"""

    UNKNOWN = "unknown"
    KNOWN_USABLE = "known_usable"
    KNOWN_NONE = "known_none"


@dataclass(frozen=True)
class NullificationPlayerKnowledge:
    player_id: PlayerId
    availability: NullificationAvailability
    knowledge_source: str
    knowledge_time: str
    window_id: str | None
    exact_quantity: None = None
    discloses_other_cards: bool = False


class NullificationKnowledgeState:
    """按玩家保存、并在每个响应窗口重新刷新的无懈知识。"""

    def __init__(self, player_ids: Iterable[PlayerId]) -> None:
        players = _unique_player_ids(player_ids, "无懈知识玩家")
        if not players:
            raise ValueError("无懈知识至少需要一名玩家")
        self._players = players
        self._knowledge: dict[PlayerId, NullificationPlayerKnowledge] = {
            player: NullificationPlayerKnowledge(
                player,
                NullificationAvailability.UNKNOWN,
                "尚未观察到响应读条",
                "初始化",
                None,
            )
            for player in players
        }

    @property
    def player_ids(self) -> tuple[PlayerId, ...]:
        return self._players

    def snapshot(self) -> Mapping[PlayerId, NullificationPlayerKnowledge]:
        return MappingProxyType(dict(self._knowledge))

    def knowledge_for(self, player_id: PlayerId) -> NullificationPlayerKnowledge:
        if player_id not in self._knowledge:
            raise ValueError(f"无懈知识中不存在玩家：{player_id}")
        return self._knowledge[player_id]

    def refresh_response_window(
        self,
        usable_player_ids: Iterable[PlayerId],
        *,
        window_id: str,
        knowledge_time: str,
    ) -> None:
        """使用本次读条覆盖旧集合；集合只表示至少一份可用资格。"""

        if not isinstance(window_id, str) or not window_id.strip():
            raise ValueError("无懈响应窗口标识不能为空")
        if not isinstance(knowledge_time, str) or not knowledge_time.strip():
            raise ValueError("无懈知识时间不能为空")
        usable = frozenset(
            _unique_player_ids(usable_player_ids, "可用无懈玩家")
        )
        unknown_players = usable.difference(self._knowledge)
        if unknown_players:
            raise ValueError(
                f"可用无懈玩家不在当前对局中：{next(iter(unknown_players))}"
            )
        for player in self._players:
            self._knowledge[player] = NullificationPlayerKnowledge(
                player,
                (
                    NullificationAvailability.KNOWN_USABLE
                    if player in usable
                    else NullificationAvailability.KNOWN_NONE
                ),
                "无懈响应读条",
                knowledge_time,
                window_id,
            )

    def record_nullification_used(
        self,
        player_id: PlayerId,
        *,
        knowledge_time: str,
    ) -> None:
        """观察到使用一张后只把剩余量降为未知，绝不推断已经用尽。"""

        current = self.knowledge_for(player_id)
        if not isinstance(knowledge_time, str) or not knowledge_time.strip():
            raise ValueError("无懈知识时间不能为空")
        self._knowledge[player_id] = NullificationPlayerKnowledge(
            player_id,
            NullificationAvailability.UNKNOWN,
            "已使用一张无懈，剩余数量未知",
            knowledge_time,
            current.window_id,
        )

    def record_unknown_hand_change(
        self,
        player_id: PlayerId,
        *,
        knowledge_time: str,
    ) -> None:
        """摸取或失去未知牌后，旧的有/无结论都失效。"""

        current = self.knowledge_for(player_id)
        if not isinstance(knowledge_time, str) or not knowledge_time.strip():
            raise ValueError("无懈知识时间不能为空")
        self._knowledge[player_id] = NullificationPlayerKnowledge(
            player_id,
            NullificationAvailability.UNKNOWN,
            "发生未知手牌变化，旧无懈信息失效",
            knowledge_time,
            current.window_id,
        )

    def record_player_removed(
        self,
        player_id: PlayerId,
        *,
        knowledge_time: str,
    ) -> None:
        """角色退出游戏后记录当前无可用资格，不推导其手牌内容。"""

        current = self.knowledge_for(player_id)
        if not isinstance(knowledge_time, str) or not knowledge_time.strip():
            raise ValueError("无懈知识时间不能为空")
        self._knowledge[player_id] = NullificationPlayerKnowledge(
            player_id,
            NullificationAvailability.KNOWN_NONE,
            "角色已退出游戏",
            knowledge_time,
            current.window_id,
        )


    def record_public_nullification_gained(self, player_id: PlayerId, *, knowledge_time: str) -> None:
        """只接受可信调用者确认的公开区域取牌事实，不探测未知摸牌牌面。"""
        current = self.knowledge_for(player_id)
        if not isinstance(knowledge_time, str) or not knowledge_time.strip():
            raise ValueError("无懈知识时间不能为空")
        self._knowledge[player_id] = NullificationPlayerKnowledge(
            player_id, NullificationAvailability.KNOWN_USABLE,
            "公开获得无懈，精确总量未知", knowledge_time, current.window_id)


@dataclass(frozen=True)
class NullificationDecision:
    use_nullification: bool
    immediate_protection_value: float
    preservation_value: float
    decision_score: float
    explanation: str


def evaluate_nullification_decision(
    current_negative_value: float,
    *,
    future_preservation_value: float = 0.0,
    would_cause_death: bool = False,
    key_control_or_resolution: bool = False,
    opponent_hand_count: int = 4,
    known_enemy_nullification_holders: int = 0,
    allied_counter_available: bool = False,
) -> NullificationDecision:
    """比较当前保护收益和保留价值，返回可解释的无懈决策。

    系数是策略层的透明初值，不是卡牌规则或官方 AI 权重。
    """

    loss = ensure_finite_real(current_negative_value, "当前锦囊负收益")
    future = ensure_finite_real(future_preservation_value, "后续保留价值")
    if loss < 0 or future < 0:
        raise ValueError("当前锦囊负收益和后续保留价值不能小于 0")
    _ensure_bool(would_cause_death, "导致死亡标识")
    _ensure_bool(key_control_or_resolution, "关键控制标识")
    _ensure_bool(allied_counter_available, "己方反无懈可用标识")
    ensure_int_at_least(opponent_hand_count, "对方手牌数", 0)
    ensure_int_at_least(
        known_enemy_nullification_holders,
        "已知敌方无懈持有者数",
        0,
    )

    protection = loss
    reasons: list[str] = []
    if would_cause_death:
        protection += 4.0
        reasons.append("不响应可能导致关键角色死亡")
    if key_control_or_resolution:
        protection += 2.0
        reasons.append("当前属于关键控制或高价值结算")
    if opponent_hand_count <= 2:
        protection += 0.4
        reasons.append("对方手牌较少，反制风险相对较低")
    elif opponent_hand_count >= 6:
        protection -= 0.2
        reasons.append("对方手牌较多，保留与反制风险需要计入")

    counter_risk = known_enemy_nullification_holders * 0.35
    if allied_counter_available and counter_risk:
        counter_risk *= 0.5
        reasons.append("己方存在反无懈资源，部分降低敌方反制风险")
    score = protection - future - counter_risk
    use = score > 0
    if use:
        reasons.insert(0, "当前保护收益高于保留价值")
    else:
        reasons.insert(0, "当前收益不足以覆盖后续保留价值与反制风险")
    return NullificationDecision(
        use,
        protection,
        future,
        score,
        "；".join(reasons),
    )


@dataclass(frozen=True)
class NullificationBaitDecision:
    use_bait: bool
    expected_benefit: float
    expected_cost: float
    decision_score: float
    explanation: str


def evaluate_nullification_bait(
    bait_cost: float,
    followup_trick_value: float,
    *,
    information_value: float = 0.0,
    adverse_side_effect_cost: float = 0.0,
    known_enemy_has_usable: bool | None = None,
    expected_consumption_probability: float | None = None,
) -> NullificationBaitDecision:
    """判断低价值锦囊是否值得试探或诱骗【无懈可击】。"""

    cost = ensure_finite_real(bait_cost, "诱饵锦囊成本")
    followup = ensure_finite_real(followup_trick_value, "后续锦囊价值")
    info = ensure_finite_real(information_value, "试探信息价值")
    adverse = ensure_finite_real(adverse_side_effect_cost, "诱饵反效果成本")
    if min(cost, followup, info, adverse) < 0:
        raise ValueError("诱骗策略的价值与成本不能小于 0")
    if known_enemy_has_usable is not None:
        _ensure_bool(known_enemy_has_usable, "敌方已知有可用无懈标识")
    if expected_consumption_probability is None:
        probability = 0.65 if known_enemy_has_usable else 0.35
    else:
        probability = ensure_finite_real(
            expected_consumption_probability,
            "无懈消耗概率",
        )
        if probability < 0 or probability > 1:
            raise ValueError("无懈消耗概率必须在 0 到 1 之间")

    if known_enemy_has_usable is False:
        return NullificationBaitDecision(
            False,
            0.0,
            cost + adverse,
            -(cost + adverse),
            "敌方在当前响应窗口已知没有可用无懈，无需用低价值锦囊诱骗",
        )
    benefit = followup * probability + info
    total_cost = cost + adverse
    score = benefit - total_cost
    use = followup > 0 and score > 0
    if use:
        explanation = "诱骗或探明无懈的预期收益高于诱饵成本"
    elif followup <= 0:
        explanation = "没有后续高价值锦囊，不值得消耗诱饵"
    else:
        explanation = "诱骗的预期收益不足以覆盖诱饵与反效果成本"
    return NullificationBaitDecision(
        use,
        benefit,
        total_cost,
        score,
        explanation,
    )
