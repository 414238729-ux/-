"""当前普通候选相关武将/版本记录的轻量结算模型与候选池。

技能全文与完整结算说明以 Knowledge 中唯一的武将规则补充文件为准；
这里的十四条记录只服务现有十三个普通候选名额，不是全部正式武将
条目的索引，也不凭模型记忆补全其他武将。曹纯的两个版本是两个规则
记录，但在候选池中始终只占一个实际名额。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Iterable, Mapping, Sequence

from ._validation import ensure_int_at_least, make_rng


def _nonempty(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label}必须是非空字符串")
    return value.strip()


def _tuple(values: Iterable[str], label: str) -> tuple[str, ...]:
    if values is None:
        raise TypeError(f"{label}不能是 None")
    try:
        result = tuple(values)
    except TypeError as exc:
        raise TypeError(f"{label}必须是可迭代对象") from exc
    for value in result:
        _nonempty(value, label)
    return result


class CardEventKind(str, Enum):
    USE = "使用"
    RESPOND = "打出"
    VIEW_AS_USE = "视为使用"
    CONVERTED_USE = "转化后使用或打出"
    DISCARD = "弃置"
    LOSE = "失去"
    RECAST = "重铸"
    REVEAL = "展示"
    PLACE_ON_GENERAL = "置于武将牌上"
    SKILL_ONLY = "仅发动技能"


_JILI_COUNTED_EVENTS = frozenset(
    {
        CardEventKind.USE,
        CardEventKind.RESPOND,
        CardEventKind.VIEW_AS_USE,
        CardEventKind.CONVERTED_USE,
    }
)


@dataclass(frozen=True)
class GeneralRuleRecord:
    general_key: str
    general_name: str
    version: str
    base_hp: int
    base_max_hp: int
    skill_names: tuple[str, ...]
    taunt_baseline: str
    source: str = "用户本轮明确提供并确认"
    confidence: str = "当前确认"

    def __post_init__(self) -> None:
        object.__setattr__(self, "general_key", _nonempty(self.general_key, "武将键"))
        object.__setattr__(self, "general_name", _nonempty(self.general_name, "武将名"))
        object.__setattr__(self, "version", _nonempty(self.version, "版本"))
        object.__setattr__(self, "base_hp", ensure_int_at_least(self.base_hp, "体力", 1))
        object.__setattr__(
            self,
            "base_max_hp",
            ensure_int_at_least(self.base_max_hp, "体力上限", 1),
        )
        if self.base_hp > self.base_max_hp:
            raise ValueError("基础体力不能高于基础体力上限")
        object.__setattr__(self, "skill_names", _tuple(self.skill_names, "技能名"))


GENERAL_RULE_RECORDS: Mapping[str, GeneralRuleRecord] = MappingProxyType(
    {
        record.general_key: record
        for record in (
            GeneralRuleRecord("shamoke", "沙摩柯", "当前条目", 4, 4, ("蒺藜",), "A"),
            GeneralRuleRecord("zhugezhan", "诸葛瞻", "当前条目", 3, 3, ("罪论", "父荫"), "A-～A"),
            GeneralRuleRecord("jie_zhonghui", "界钟会", "界", 4, 4, ("权计", "自立", "排异"), "B+～A-"),
            GeneralRuleRecord("caochun_old", "曹纯", "旧版", 4, 4, ("缮甲",), "A+"),
            GeneralRuleRecord("caochun_new", "曹纯", "新版", 4, 4, ("缮甲",), "A+～S-"),
            GeneralRuleRecord("wangyuanji", "王元姬", "当前条目", 3, 3, ("谦冲", "尚俭", "帷幕", "明哲"), "A"),
            GeneralRuleRecord("caoying", "曹婴", "当前条目", 4, 4, ("凌人", "伏间", "奸雄", "行殇"), "A+"),
            GeneralRuleRecord("zhangqiying", "张琪瑛", "当前条目", 3, 3, ("法箓", "真仪", "点化"), "A"),
            GeneralRuleRecord("star_ganning", "星·甘宁", "星", 4, 4, ("锦帆", "射却"), "A-～A"),
            GeneralRuleRecord("xuyou", "许攸", "当前条目", 3, 3, ("成略", "恃才", "寸目"), "动态计算"),
            GeneralRuleRecord("qinghe_princess", "清河公主", "当前条目", 3, 3, ("谮构", "诽离"), "动态计算"),
            GeneralRuleRecord("fuqian", "傅佥", "当前条目", 4, 4, ("破降", "绝勇"), "动态计算"),
            GeneralRuleRecord("strategist_gongsunzan", "谋·公孙瓒", "谋", 4, 4, ("义从", "趫猛"), "动态计算"),
            GeneralRuleRecord("baoxin", "鲍信", "当前条目", 4, 4, ("募讨", "毅谋"), "B+～A-"),
        )
    }
)


TAUNT_LEVEL_ORDER = ("B+", "A-", "A", "A+", "S-", "S", "S+")


# ---------------------------------------------------------------------------
# 沙摩柯：蒺藜


@dataclass(frozen=True)
class JiliTurnState:
    cards_used_or_responded_this_turn: int = 0

    def __post_init__(self) -> None:
        ensure_int_at_least(
            self.cards_used_or_responded_this_turn,
            "本回合使用或打出牌数",
            0,
        )


@dataclass(frozen=True)
class JiliResult:
    state_after: JiliTurnState
    counted: bool
    attack_range_checked: int
    triggered: bool
    draw_count: int


def start_jili_independent_turn() -> JiliTurnState:
    """每个正常或额外独立回合重新开始计数。"""

    return JiliTurnState()


def resolve_jili_card_event(
    state: JiliTurnState,
    *,
    event_kind: CardEventKind | str,
    attack_range_before_card_effect: int,
    legal_card_event: bool = True,
) -> JiliResult:
    """在牌效果结算前按当时攻击范围检查【蒺藜】。"""

    if not isinstance(state, JiliTurnState):
        raise TypeError("蒺藜状态必须是 JiliTurnState")
    attack_range = ensure_int_at_least(
        attack_range_before_card_effect,
        "牌效果结算前攻击范围",
        1,
    )
    try:
        kind = event_kind if isinstance(event_kind, CardEventKind) else CardEventKind(event_kind)
    except (TypeError, ValueError) as exc:
        raise ValueError("未知的牌事件类型") from exc
    if not isinstance(legal_card_event, bool):
        raise TypeError("牌事件是否合法必须是布尔值")

    counted = legal_card_event and kind in _JILI_COUNTED_EVENTS
    count = state.cards_used_or_responded_this_turn + (1 if counted else 0)
    triggered = counted and count == attack_range
    return JiliResult(
        state_after=JiliTurnState(count),
        counted=counted,
        attack_range_checked=attack_range,
        triggered=triggered,
        draw_count=attack_range if triggered else 0,
    )


def simulate_jili_pre_effect_ranges(ranges: Sequence[int]) -> tuple[int, ...]:
    """按顺序返回每张牌触发【蒺藜】时的摸牌数。"""

    state = JiliTurnState()
    draws: list[int] = []
    for value in ranges:
        result = resolve_jili_card_event(
            state,
            event_kind=CardEventKind.USE,
            attack_range_before_card_effect=value,
        )
        state = result.state_after
        if result.triggered:
            draws.append(result.draw_count)
    return tuple(draws)


# ---------------------------------------------------------------------------
# 诸葛瞻：罪论、父荫


@dataclass(frozen=True)
class ZuilunResult:
    activated: bool
    satisfied_conditions: int
    cards_kept: int
    self_hp_loss: int
    other_hp_loss: int
    event_order: tuple[str, ...]


def resolve_zuilun(
    *,
    activate: bool,
    caused_damage_this_turn: bool,
    discarded_card_this_turn: bool,
    hand_count: int,
    all_alive_hand_counts: Sequence[int],
    game_ended_after_self_loss: bool = False,
) -> ZuilunResult:
    """计算【罪论】满足项数与零条件时的体力流失顺序。"""

    if not isinstance(activate, bool) or not isinstance(game_ended_after_self_loss, bool):
        raise TypeError("罪论发动与游戏结束标记必须是布尔值")
    hand = ensure_int_at_least(hand_count, "诸葛瞻手牌数", 0)
    counts = tuple(
        ensure_int_at_least(value, "存活角色手牌数", 0)
        for value in all_alive_hand_counts
    )
    if not counts:
        raise ValueError("至少需要一名存活角色的手牌数")
    if hand not in counts:
        raise ValueError("全场手牌数必须包含诸葛瞻当前手牌数")
    if not activate:
        return ZuilunResult(False, 0, 0, 0, 0, ())
    satisfied = sum(
        (
            bool(caused_damage_this_turn),
            not bool(discarded_card_this_turn),
            hand == min(counts),
        )
    )
    if satisfied:
        return ZuilunResult(True, satisfied, satisfied, 0, 0, ("取得牌", "其余牌放回牌堆顶"))
    order = ["诸葛瞻失去1点体力", "处理诸葛瞻濒死、死亡与胜负"]
    other_loss = 0
    if not game_ended_after_self_loss:
        order.append("另一名角色失去1点体力")
        other_loss = 1
    return ZuilunResult(True, 0, 0, 1, other_loss, tuple(order))


@dataclass(frozen=True)
class FuyinTurnState:
    fuyin_checked_this_turn: bool = False
    caused_damage_this_turn: bool = False
    discarded_card_this_turn: bool = False

    def __post_init__(self) -> None:
        for value, label in (
            (self.fuyin_checked_this_turn, "父荫是否已检查"),
            (self.caused_damage_this_turn, "本回合是否造成伤害"),
            (self.discarded_card_this_turn, "本回合是否弃置过牌"),
        ):
            if not isinstance(value, bool):
                raise TypeError(f"{label}必须是布尔值")


@dataclass(frozen=True)
class FuyinResult:
    state_after: FuyinTurnState
    opportunity_consumed: bool
    card_invalidated: bool


def resolve_fuyin_target(
    state: FuyinTurnState,
    *,
    card_name: str,
    defender_hand_count: int,
    user_hand_count_after_use: int,
) -> FuyinResult:
    """仅首张以诸葛瞻为目标的【杀】或【决斗】检查【父荫】。"""

    if not isinstance(state, FuyinTurnState):
        raise TypeError("父荫状态必须是 FuyinTurnState")
    name = _nonempty(card_name, "牌名")
    defender = ensure_int_at_least(defender_hand_count, "诸葛瞻手牌数", 0)
    user = ensure_int_at_least(user_hand_count_after_use, "使用者用牌后手牌数", 0)
    if name not in {"杀", "决斗"} or state.fuyin_checked_this_turn:
        return FuyinResult(state, False, False)
    invalidated = defender <= user
    return FuyinResult(
        FuyinTurnState(
            True,
            state.caused_damage_this_turn,
            state.discarded_card_this_turn,
        ),
        True,
        invalidated,
    )


# ---------------------------------------------------------------------------
# 界钟会：权计、自立、排异


def quanji_damage_opportunities(damage_points: int, *, rescued_if_dying: bool) -> int:
    points = ensure_int_at_least(damage_points, "伤害点数", 0)
    if not isinstance(rescued_if_dying, bool):
        raise TypeError("濒死后是否救回必须是布尔值")
    return points if rescued_if_dying else 0


@dataclass(frozen=True)
class ZhonghuiState:
    quan_cards: tuple[str, ...] = ()
    zili_awakened: bool = False
    paiyi_used_this_play_phase: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "quan_cards", _tuple(self.quan_cards, "权"))


@dataclass(frozen=True)
class ZiliResult:
    state_after: ZhonghuiState
    awakened: bool
    draw_count: int
    recover_hp: int
    max_hp_loss: int


def resolve_zili(state: ZhonghuiState, *, choice: str) -> ZiliResult:
    if not isinstance(state, ZhonghuiState):
        raise TypeError("界钟会状态必须是 ZhonghuiState")
    if state.zili_awakened or len(state.quan_cards) < 3:
        return ZiliResult(state, False, 0, 0, 0)
    selected = _nonempty(choice, "自立选项")
    if selected not in {"回复1点体力", "摸2张牌"}:
        raise ValueError("自立只能选择回复1点体力或摸2张牌")
    return ZiliResult(
        ZhonghuiState(state.quan_cards, True, state.paiyi_used_this_play_phase),
        True,
        2 if selected == "摸2张牌" else 0,
        1 if selected == "回复1点体力" else 0,
        1,
    )


@dataclass(frozen=True)
class PaiyiResult:
    state_after: ZhonghuiState
    target_draw_count: int
    target_hand_after_draw: int
    damage_to_target: int


def resolve_paiyi(
    state: ZhonghuiState,
    *,
    power_card_id: str,
    target_hand_before_draw: int,
    zhonghui_hand_after_target_draw: int,
    target_is_self: bool,
) -> PaiyiResult:
    if not isinstance(state, ZhonghuiState):
        raise TypeError("界钟会状态必须是 ZhonghuiState")
    if state.paiyi_used_this_play_phase:
        raise ValueError("本出牌阶段已经使用过排异")
    power = _nonempty(power_card_id, "要移去的权")
    if power not in state.quan_cards:
        raise ValueError("指定的权不存在")
    target_before = ensure_int_at_least(target_hand_before_draw, "目标摸牌前手牌数", 0)
    self_after = ensure_int_at_least(
        zhonghui_hand_after_target_draw,
        "目标摸牌后钟会手牌数",
        0,
    )
    target_after = target_before + 2
    damage = 0 if target_is_self else int(target_after > self_after)
    remaining = list(state.quan_cards)
    remaining.remove(power)
    return PaiyiResult(
        ZhonghuiState(tuple(remaining), state.zili_awakened, True),
        2,
        target_after,
        damage,
    )


# ---------------------------------------------------------------------------
# 曹纯：新旧缮甲与八人测试池


class CaochunVersion(str, Enum):
    OLD = "旧版"
    NEW = "新版"


@dataclass(frozen=True)
class CaochunState:
    equipment_zone_cards_lost_total: int = 0
    shanjia_used_this_play_phase: bool = False

    def __post_init__(self) -> None:
        ensure_int_at_least(
            self.equipment_zone_cards_lost_total,
            "累计失去装备区牌数",
            0,
        )


def record_caochun_card_loss(
    state: CaochunState,
    *,
    from_zone: str,
    count: int = 1,
) -> CaochunState:
    if not isinstance(state, CaochunState):
        raise TypeError("曹纯状态必须是 CaochunState")
    amount = ensure_int_at_least(count, "失去牌数", 0)
    zone = _nonempty(from_zone, "来源区域")
    increment = amount if zone == "装备区" else 0
    return CaochunState(
        state.equipment_zone_cards_lost_total + increment,
        state.shanjia_used_this_play_phase,
    )


@dataclass(frozen=True)
class ShanjiaResult:
    state_after: CaochunState
    draw_count: int
    locked_discard_count: int
    virtual_slash_available: bool
    play_phase_no_distance: bool
    virtual_slash_uses_normal_quota: bool = False


def resolve_shanjia(
    state: CaochunState,
    *,
    version: CaochunVersion | str,
    timing: str,
    discarded_card_types: Sequence[str],
    equipment_lost_during_resolution: int = 0,
) -> ShanjiaResult:
    if not isinstance(state, CaochunState):
        raise TypeError("曹纯状态必须是 CaochunState")
    try:
        selected_version = version if isinstance(version, CaochunVersion) else CaochunVersion(version)
    except (TypeError, ValueError) as exc:
        raise ValueError("曹纯版本只能是旧版或新版") from exc
    actual_timing = _nonempty(timing, "缮甲发动时机")
    if selected_version is CaochunVersion.OLD and actual_timing != "出牌阶段开始时":
        raise ValueError("旧版缮甲只能在出牌阶段开始时发动")
    if selected_version is CaochunVersion.NEW and actual_timing != "出牌阶段内":
        raise ValueError("新版缮甲应在出牌阶段内自行选择时机")
    if state.shanjia_used_this_play_phase:
        raise ValueError("本出牌阶段已经发动过缮甲")
    types = _tuple(discarded_card_types, "弃置牌类型")
    required = max(0, 3 - state.equipment_zone_cards_lost_total)
    if len(types) != required:
        raise ValueError(f"本次缮甲必须弃置恰好 {required} 张牌")
    for card_type in types:
        if card_type not in {"基本牌", "锦囊牌", "装备牌"}:
            raise ValueError("弃置牌类型只能是基本牌、锦囊牌或装备牌")
    newly_lost = ensure_int_at_least(
        equipment_lost_during_resolution,
        "本次结算失去装备区牌数",
        0,
    )
    after = CaochunState(
        state.equipment_zone_cards_lost_total + newly_lost,
        True,
    )
    no_basic = "基本牌" not in types
    no_trick = "锦囊牌" not in types
    if selected_version is CaochunVersion.OLD:
        virtual_slash = no_basic and no_trick
        no_distance = False
    else:
        virtual_slash = no_basic
        no_distance = no_trick
    return ShanjiaResult(after, 3, required, virtual_slash, no_distance)


def caochun_version_probabilities() -> Mapping[CaochunVersion, float]:
    return MappingProxyType({CaochunVersion.OLD: 0.5, CaochunVersion.NEW: 0.5})


def choose_caochun_version(seed: object | None = None) -> CaochunVersion:
    return make_rng(seed).choice((CaochunVersion.OLD, CaochunVersion.NEW))


ORIGINAL_EIGHT_GENERAL_SLOTS = (
    "沙摩柯",
    "诸葛瞻",
    "界钟会",
    "曹纯",
    "王元姬",
    "曹婴",
    "张琪瑛",
    "星·甘宁",
)


GENERAL_CANDIDATE_SLOTS = ORIGINAL_EIGHT_GENERAL_SLOTS + (
    "许攸",
    "清河公主",
    "傅佥",
    "谋·公孙瓒",
    "鲍信",
)

# 保留旧公开名称供既有调用方兼容；它现在表示八人模式所用的十三名候选
# 槽，而不是每局固定全选的八人名单。
EIGHT_PLAYER_GENERAL_SLOTS = GENERAL_CANDIDATE_SLOTS

# 谋皇甫嵩当前仅作为中上候选／精品强将专项测试，不进入普通十三人池。
EVALUATION_ONLY_GENERAL_NAMES = frozenset({"谋皇甫嵩"})

# V2.4 已正式收录规则、但尚未被静默并入现有十三名随机抽样池的武将。
# 基础数值已经由用户确认，可供固定阵容画像直接读取；是否扩充随机池仍
# 必须另行显式决定。
V24_FORMAL_RULE_CANDIDATES = frozenset({"势·孙綝", "势·辛宪英", "SP郭女王"})

# 未上线原型与所有正式规则/胜率池隔离。
EXPERIMENTAL_GENERAL_NAMES = frozenset({"神吕布重制原型"})

# 值的顺序统一为（基础初始体力，基础体力上限）。神吕布仍是实验原型；
# 收录基础值不改变它的池隔离状态。
V24_GENERAL_BASE_STATS: Mapping[str, tuple[int, int]] = MappingProxyType(
    {
        "势·孙綝": (4, 4),
        "势·辛宪英": (3, 3),
        "SP郭女王": (3, 3),
        "神吕布重制原型": (5, 5),
    }
)


def v24_general_base_stats(general_name: str) -> tuple[int, int]:
    """返回用户确认的（基础初始体力，基础体力上限）。"""

    name = _nonempty(general_name, "武将名")
    try:
        return V24_GENERAL_BASE_STATS[name]
    except KeyError as exc:
        raise ValueError("该武将没有已登记的V2.4基础体力数据") from exc

CORE_LORD_POOL = (
    "曹叡",
    "界曹丕",
    "刘禅",
    "界孙休",
    "界孙权",
    "谋袁绍",
    "界董卓",
)

SPECIALIZED_LORD_POOL = (
    "孙亮",
    "界孙策",
    "谋孙权",
    "谋孙策",
    "谋张角",
    "标曹丕",
)

LORD_BASE_STATS: Mapping[str, tuple[int, int]] = MappingProxyType(
    {
        "曹叡": (3, 3),
        "界曹丕": (3, 3),
        "刘禅": (3, 3),
        "界孙休": (3, 3),
        "界孙权": (4, 4),
        "谋袁绍": (4, 4),
        "界董卓": (8, 8),
        "孙亮": (3, 3),
        "界孙策": (4, 4),
        "谋孙权": (4, 4),
        "谋孙策": (4, 4),
        "谋张角": (3, 3),
        "标曹丕": (3, 3),
    }
)


def lord_eight_player_initial_stats(lord_name: str) -> tuple[int, int]:
    """返回登记主公在普通八人军争中的（初始体力，体力上限）。"""

    name = _nonempty(lord_name, "主公武将名")
    if name not in LORD_BASE_STATS:
        raise ValueError("该武将不在当前核心或专项主公池基础数据中")
    base_hp, base_max_hp = LORD_BASE_STATS[name]
    return base_hp + 1, base_max_hp + 1


@dataclass(frozen=True)
class LordEvaluationPlan:
    """固定被测主公及运行前登记的相性、克制专项主公集合。"""

    tested_lord: str
    core_lords: tuple[str, ...]
    specialized_lords: tuple[str, ...]
    synergy_lords: tuple[str, ...] = ()
    counter_lords: tuple[str, ...] = ()


def build_lord_evaluation_plan(
    tested_lord: str,
    *,
    synergy_lords: Iterable[str] = (),
    counter_lords: Iterable[str] = (),
) -> LordEvaluationPlan:
    """强制指定主公，并在模拟前登记相性与克制专项池。"""

    tested = _nonempty(tested_lord, "被测主公")
    synergy = _tuple(synergy_lords, "相性主公")
    counters = _tuple(counter_lords, "克制主公")
    if len(synergy) != len(set(synergy)) or len(counters) != len(set(counters)):
        raise ValueError("相性主公和克制主公各自不能重复")
    known = set(CORE_LORD_POOL) | set(SPECIALIZED_LORD_POOL) | {tested}
    unknown = (set(synergy) | set(counters)) - known
    if unknown:
        raise ValueError(f"专项主公不在已登记主公池：{'、'.join(sorted(unknown))}")
    return LordEvaluationPlan(
        tested_lord=tested,
        core_lords=CORE_LORD_POOL,
        specialized_lords=SPECIALIZED_LORD_POOL,
        synergy_lords=synergy,
        counter_lords=counters,
    )

MODE_GENERAL_SAMPLE_SIZES: Mapping[str, int] = MappingProxyType(
    {
        "2v2": 4,
        "斗地主": 3,
        "八人军争身份": 8,
    }
)

EXCLUDED_GENERAL_NAMES = frozenset(
    {
        "谋·曹仁",
        "界徐盛",
        "神太史慈",
        "骧·张辽",
        "司马懿",
    }
)


def sample_general_lineup(
    mode: str,
    seed: object | None = None,
) -> tuple[str, ...]:
    """从十三个唯一名额中按模式无放回抽取；曹纯入选后再等概率选版本。"""

    selected_mode = _nonempty(mode, "模式")
    aliases = {
        "八人身份": "八人军争身份",
        "军争身份": "八人军争身份",
        "标准八人军争": "八人军争身份",
    }
    selected_mode = aliases.get(selected_mode, selected_mode)
    if selected_mode not in MODE_GENERAL_SAMPLE_SIZES:
        allowed = "、".join(MODE_GENERAL_SAMPLE_SIZES)
        raise ValueError(f"模式只能是：{allowed}")
    rng = make_rng(seed)
    slots = rng.sample(
        GENERAL_CANDIDATE_SLOTS,
        MODE_GENERAL_SAMPLE_SIZES[selected_mode],
    )
    result: list[str] = []
    for name in slots:
        if name == "曹纯":
            version = rng.choice((CaochunVersion.OLD, CaochunVersion.NEW))
            result.append(f"{version.value}曹纯")
        else:
            result.append(name)
    return tuple(result)


def materialize_eight_player_test_pool(seed: object | None = None) -> tuple[str, ...]:
    """兼容旧接口：从当前十三名候选池为标准八人军争抽取八名。"""

    return sample_general_lineup("八人军争身份", seed)


# ---------------------------------------------------------------------------
# 王元姬：谦冲、明哲、尚俭


@dataclass(frozen=True)
class QianchongState:
    has_weimu: bool
    has_mingzhe: bool
    can_choose_temporary_card_type: bool


@dataclass(frozen=True)
class WangYuanjiState:
    """王元姬在一个回合内需要持久保存的专属状态。"""

    cards_lost_this_turn: int = 0
    temporary_qianchong_card_type: str | None = None
    has_weimu: bool = False
    has_mingzhe: bool = False

    def __post_init__(self) -> None:
        ensure_int_at_least(self.cards_lost_this_turn, "本回合失去牌数", 0)
        if self.temporary_qianchong_card_type is not None:
            card_type = _nonempty(
                self.temporary_qianchong_card_type,
                "谦冲临时牌类型",
            )
            if card_type not in {"基本牌", "锦囊牌", "装备牌"}:
                raise ValueError("谦冲临时牌类型只能是基本牌、锦囊牌或装备牌")
        if not isinstance(self.has_weimu, bool) or not isinstance(
            self.has_mingzhe,
            bool,
        ):
            raise TypeError("帷幕与明哲状态必须是布尔值")


def build_wangyuanji_state(
    *,
    equipment_colors: Sequence[str],
    cards_lost_this_turn: int = 0,
    temporary_qianchong_card_type: str | None = None,
) -> WangYuanjiState:
    """从当前装备颜色和本回合事件汇总生成王元姬状态。"""

    qianchong = evaluate_qianchong_equipment(equipment_colors)
    if temporary_qianchong_card_type is not None and not (
        qianchong.can_choose_temporary_card_type
    ):
        raise ValueError("当前装备颜色不满足选择谦冲临时牌类型的条件")
    return WangYuanjiState(
        cards_lost_this_turn=cards_lost_this_turn,
        temporary_qianchong_card_type=temporary_qianchong_card_type,
        has_weimu=qianchong.has_weimu,
        has_mingzhe=qianchong.has_mingzhe,
    )


def evaluate_qianchong_equipment(colors: Sequence[str]) -> QianchongState:
    values = _tuple(colors, "装备颜色")
    if any(value not in {"红", "黑"} for value in values):
        raise ValueError("装备颜色只能是红或黑")
    if not values:
        return QianchongState(False, False, True)
    all_black = all(value == "黑" for value in values)
    all_red = all(value == "红" for value in values)
    return QianchongState(all_black, all_red, not (all_black or all_red))


@dataclass(frozen=True)
class CardLossEvent:
    card_id: str
    from_zone: str
    to_zone: str
    reason: str
    color: str | None = None
    outside_owner_turn: bool = False

    def __post_init__(self) -> None:
        _nonempty(self.card_id, "实体牌标识")
        _nonempty(self.from_zone, "来源区域")
        _nonempty(self.to_zone, "目标区域")
        _nonempty(self.reason, "移动原因")
        if self.color not in {None, "红", "黑"}:
            raise ValueError("颜色只能是红、黑或未知")


def mingzhe_draw_opportunities(events: Sequence[CardLossEvent]) -> int:
    allowed_reasons = {"使用", "打出", "弃置"}
    return sum(
        event.outside_owner_turn
        and event.color == "红"
        and event.reason in allowed_reasons
        for event in events
    )


def count_wangyuanji_lost_cards(events: Sequence[CardLossEvent]) -> int:
    count = 0
    for event in events:
        if event.from_zone not in {"手牌区", "装备区"}:
            continue
        if (
            event.from_zone == "手牌区"
            and event.to_zone == "自己的装备区"
            and event.reason == "使用装备"
        ):
            continue
        count += 1
    return count


def resolve_shangjian(cards_lost_this_turn: int, current_hp: int) -> int:
    lost = ensure_int_at_least(cards_lost_this_turn, "本回合失去牌数", 0)
    hp = ensure_int_at_least(current_hp, "结束阶段当前体力", 0)
    return lost if lost <= hp else 0


# ---------------------------------------------------------------------------
# 曹婴：凌人、奸雄、行殇、伏间


@dataclass(frozen=True)
class LingrenPlayPhaseState:
    lingren_used_this_play_phase: bool = False


@dataclass(frozen=True)
class CaoyingState:
    """曹婴的回合内次数、临时技能与依法已知手牌信息。"""

    lingren_used_this_play_phase: bool = False
    temporary_jianxiong: bool = False
    temporary_xingshang: bool = False
    temporary_skill_expiry: str | None = None
    known_hand_information: Mapping[str, tuple[str, ...]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for value, label in (
            (self.lingren_used_this_play_phase, "凌人是否已使用"),
            (self.temporary_jianxiong, "是否临时拥有奸雄"),
            (self.temporary_xingshang, "是否临时拥有行殇"),
        ):
            if not isinstance(value, bool):
                raise TypeError(f"{label}必须是布尔值")
        if self.temporary_skill_expiry is not None:
            _nonempty(self.temporary_skill_expiry, "临时技能失效时点")
        normalized = {
            _nonempty(player_id, "已知手牌角色标识"): _tuple(cards, "依法已知手牌")
            for player_id, cards in self.known_hand_information.items()
        }
        object.__setattr__(
            self,
            "known_hand_information",
            MappingProxyType(normalized),
        )


def apply_lingren_result_to_caoying_state(
    state: CaoyingState,
    result: "LingrenResult",
) -> CaoyingState:
    if not isinstance(state, CaoyingState):
        raise TypeError("曹婴状态必须是 CaoyingState")
    if not isinstance(result, LingrenResult):
        raise TypeError("凌人结果必须是 LingrenResult")
    return CaoyingState(
        lingren_used_this_play_phase=result.state_after.lingren_used_this_play_phase,
        temporary_jianxiong=state.temporary_jianxiong or result.grants_jianxiong,
        temporary_xingshang=state.temporary_xingshang or result.grants_xingshang,
        temporary_skill_expiry=(
            result.temporary_skill_expiry or state.temporary_skill_expiry
        ),
        known_hand_information=state.known_hand_information,
    )


@dataclass(frozen=True)
class LingrenResult:
    state_after: LingrenPlayPhaseState
    correct_guesses: int
    damage_bonus: int
    draw_count: int
    grants_jianxiong: bool
    grants_xingshang: bool
    temporary_skill_expiry: str | None


def resolve_lingren(
    state: LingrenPlayPhaseState,
    *,
    guesses_has_type: Mapping[str, bool],
    actual_hand_types: Iterable[str],
) -> LingrenResult:
    if not isinstance(state, LingrenPlayPhaseState):
        raise TypeError("凌人状态必须是 LingrenPlayPhaseState")
    if state.lingren_used_this_play_phase:
        raise ValueError("本出牌阶段已经发动过凌人")
    categories = ("基本牌", "锦囊牌", "装备牌")
    if set(guesses_has_type) != set(categories):
        raise ValueError("凌人必须分别猜测基本牌、锦囊牌和装备牌")
    if any(not isinstance(value, bool) for value in guesses_has_type.values()):
        raise TypeError("凌人猜测结果必须是布尔值")
    actual = set(_tuple(actual_hand_types, "目标手牌类别"))
    if not actual <= set(categories):
        raise ValueError("目标手牌类别包含未知类型")
    correct = sum(guesses_has_type[name] == (name in actual) for name in categories)
    return LingrenResult(
        LingrenPlayPhaseState(True),
        correct,
        1 if correct >= 1 else 0,
        2 if correct >= 2 else 0,
        correct == 3,
        correct == 3,
        "下回合开始" if correct == 3 else None,
    )


def expire_caoying_temporary_skills_at_turn_start(
    *,
    has_temporary_jianxiong: bool,
    has_temporary_xingshang: bool,
) -> tuple[bool, bool]:
    """任何下一回合（包括额外回合）开始时均失去临时技能。"""

    if not isinstance(has_temporary_jianxiong, bool) or not isinstance(
        has_temporary_xingshang, bool
    ):
        raise TypeError("临时技能状态必须是布尔值")
    return False, False


def resolve_temporary_jianxiong(entity_card_ids: Sequence[str] | None) -> tuple[str, ...]:
    """虚拟伤害没有实体牌时返回空，不凭空生成牌。"""

    if entity_card_ids is None:
        return ()
    return _tuple(entity_card_ids, "伤害实体牌")


def resolve_temporary_xingshang(
    *,
    dead_hand_cards: Sequence[str],
    dead_equipment_cards: Sequence[str],
    dead_judgment_cards: Sequence[str] = (),
) -> tuple[str, ...]:
    _tuple(dead_judgment_cards, "死亡角色判定区牌")
    return _tuple(dead_hand_cards, "死亡角色手牌") + _tuple(
        dead_equipment_cards,
        "死亡角色装备区牌",
    )


@dataclass(frozen=True)
class FujianResult:
    triggered: bool
    target_player_id: str | None
    viewed_card_ids: tuple[str, ...]
    minimum_hand_count: int


def resolve_fujian(
    *,
    caoying_player_id: str,
    alive_hands: Mapping[str, Sequence[str]],
    seed: object | None = None,
) -> FujianResult:
    actor = _nonempty(caoying_player_id, "曹婴标识")
    if actor not in alive_hands:
        raise ValueError("存活角色手牌中缺少曹婴")
    normalized = {
        _nonempty(player, "玩家标识"): _tuple(cards, "手牌")
        for player, cards in alive_hands.items()
    }
    minimum = min(len(cards) for cards in normalized.values())
    if minimum == 0:
        return FujianResult(False, None, (), 0)
    candidates = tuple(player for player in normalized if player != actor)
    if not candidates:
        return FujianResult(False, None, (), minimum)
    rng = make_rng(seed)
    target = rng.choice(candidates)
    viewed = tuple(rng.sample(normalized[target], minimum))
    return FujianResult(True, target, viewed, minimum)


# ---------------------------------------------------------------------------
# 张琪瑛：法箓、真仪、点化


class FaluMark(str, Enum):
    ZIWEI = "紫薇"
    HOUTU = "后土"
    YUQING = "玉清"
    GOUCHEN = "勾陈"


_SUIT_TO_MARK = MappingProxyType(
    {"♠": FaluMark.ZIWEI, "♣": FaluMark.HOUTU, "♥": FaluMark.YUQING, "♦": FaluMark.GOUCHEN}
)


@dataclass(frozen=True)
class ZhangQiyingState:
    marks: frozenset[FaluMark] = field(default_factory=lambda: frozenset(FaluMark))

    def __post_init__(self) -> None:
        normalized: set[FaluMark] = set()
        for value in self.marks:
            try:
                normalized.add(value if isinstance(value, FaluMark) else FaluMark(value))
            except (TypeError, ValueError) as exc:
                raise ValueError("存在未知法箓标记") from exc
        object.__setattr__(self, "marks", frozenset(normalized))

    @property
    def ziwei_mark(self) -> bool:
        return FaluMark.ZIWEI in self.marks

    @property
    def houtu_mark(self) -> bool:
        return FaluMark.HOUTU in self.marks

    @property
    def yuqing_mark(self) -> bool:
        return FaluMark.YUQING in self.marks

    @property
    def gouchen_mark(self) -> bool:
        return FaluMark.GOUCHEN in self.marks


def restore_falu_marks(
    state: ZhangQiyingState,
    *,
    suits: Sequence[str],
    move_reason: str,
) -> ZhangQiyingState:
    if not isinstance(state, ZhangQiyingState):
        raise TypeError("张琪瑛状态必须是 ZhangQiyingState")
    if _nonempty(move_reason, "移动原因") != "弃置进入弃牌堆":
        return state
    marks = set(state.marks)
    for suit in _tuple(suits, "弃置牌花色"):
        if suit not in _SUIT_TO_MARK:
            raise ValueError("花色只能是♠、♣、♥或♦")
        marks.add(_SUIT_TO_MARK[suit])
    return ZhangQiyingState(frozenset(marks))


def _consume_falu_mark(state: ZhangQiyingState, mark: FaluMark) -> ZhangQiyingState:
    if mark not in state.marks:
        raise ValueError(f"当前没有可消耗的{mark.value}标记")
    marks = set(state.marks)
    marks.remove(mark)
    return ZhangQiyingState(frozenset(marks))


@dataclass(frozen=True)
class ZiweiResult:
    state_after: ZhangQiyingState
    judgment_suit: str
    judgment_rank: str = "5"
    locks_final_judgment: bool = False


def resolve_ziwei(state: ZhangQiyingState, *, choose_suit: str) -> ZiweiResult:
    suit = _nonempty(choose_suit, "紫薇改判花色")
    if suit not in {"♠", "♥"}:
        raise ValueError("紫薇只能改为黑桃5或红桃5")
    return ZiweiResult(_consume_falu_mark(state, FaluMark.ZIWEI), suit)


def resolve_houtu(
    state: ZhangQiyingState,
    *,
    is_dying: bool,
    hand_count: int,
) -> ZhangQiyingState:
    if not is_dying:
        raise ValueError("只有处于濒死状态时才能发动后土")
    if ensure_int_at_least(hand_count, "手牌数", 0) < 1:
        raise ValueError("发动后土必须仍有至少一张手牌")
    return _consume_falu_mark(state, FaluMark.HOUTU)


@dataclass(frozen=True)
class YuqingResult:
    state_after: ZhangQiyingState
    final_damage: int


def resolve_yuqing(
    state: ZhangQiyingState,
    *,
    base_damage: int,
    judgment_color: str,
) -> YuqingResult:
    damage = ensure_int_at_least(base_damage, "原伤害", 0)
    color = _nonempty(judgment_color, "玉清判定颜色")
    if color not in {"红", "黑"}:
        raise ValueError("判定颜色只能是红或黑")
    return YuqingResult(
        _consume_falu_mark(state, FaluMark.YUQING),
        damage + (1 if color == "黑" else 0),
    )


@dataclass(frozen=True)
class CategoryCard:
    card_id: str
    category: str
    source_zone: str

    def __post_init__(self) -> None:
        _nonempty(self.card_id, "实体牌标识")
        if self.category not in {"基本牌", "锦囊牌", "装备牌"}:
            raise ValueError("牌类别只能是基本牌、锦囊牌或装备牌")
        if self.source_zone not in {"牌堆", "弃牌堆"}:
            raise ValueError("勾陈候选牌只能来自牌堆或弃牌堆")


@dataclass(frozen=True)
class GouchenResult:
    state_after: ZhangQiyingState
    obtained_cards: tuple[CategoryCard, ...]


def resolve_gouchen(
    state: ZhangQiyingState,
    *,
    elemental_damage_received: bool,
    rescued_if_dying: bool,
    candidates: Sequence[CategoryCard],
    seed: object | None = None,
) -> GouchenResult:
    if not elemental_damage_received:
        raise ValueError("只有实际受到属性伤害后才能发动勾陈")
    if not rescued_if_dying:
        raise ValueError("濒死未救回时不能结算勾陈")
    rng = make_rng(seed)
    chosen: list[CategoryCard] = []
    for category in ("基本牌", "锦囊牌", "装备牌"):
        pool = [card for card in candidates if card.category == category]
        if pool:
            chosen.append(rng.choice(pool))
    return GouchenResult(
        _consume_falu_mark(state, FaluMark.GOUCHEN),
        tuple(chosen),
    )


@dataclass(frozen=True)
class DianhuaTurnState:
    preparation_used: bool = False
    ending_used: bool = False


@dataclass(frozen=True)
class DianhuaResult:
    state_after: DianhuaTurnState
    viewed_count: int
    reordered_top_cards: tuple[str, ...]


def resolve_dianhua(
    state: DianhuaTurnState,
    *,
    phase: str,
    mark_count: int,
    current_top_cards: Sequence[str],
    reordered_top_cards: Sequence[str],
) -> DianhuaResult:
    if not isinstance(state, DianhuaTurnState):
        raise TypeError("点化状态必须是 DianhuaTurnState")
    selected_phase = _nonempty(phase, "点化发动阶段")
    if selected_phase not in {"准备阶段", "结束阶段"}:
        raise ValueError("点化只能在准备阶段或结束阶段发动")
    if selected_phase == "准备阶段" and state.preparation_used:
        raise ValueError("本回合准备阶段已经发动过点化")
    if selected_phase == "结束阶段" and state.ending_used:
        raise ValueError("本回合结束阶段已经发动过点化")
    count = ensure_int_at_least(mark_count, "当前标记数", 0)
    if count > 4:
        raise ValueError("点化标记数不能超过4")
    current = _tuple(current_top_cards, "当前牌堆顶牌")[:count]
    reordered = _tuple(reordered_top_cards, "重新排列后的牌")
    if len(current) != count:
        raise ValueError("提供的牌堆顶牌不足点化观看数量")
    if sorted(current) != sorted(reordered):
        raise ValueError("点化只能重新排列所观看的牌")
    after = DianhuaTurnState(
        preparation_used=state.preparation_used or selected_phase == "准备阶段",
        ending_used=state.ending_used or selected_phase == "结束阶段",
    )
    return DianhuaResult(after, count, reordered)


def delayed_tricks_last_in_first_out(entry_order: Sequence[str]) -> tuple[str, ...]:
    return tuple(reversed(_tuple(entry_order, "延时锦囊进入顺序")))


def zhangqiying_elemental_target_modifier(*, lethal: bool) -> float:
    """非致死属性伤害大幅降权；致死属性伤害不享受该降权。"""

    if not isinstance(lethal, bool):
        raise TypeError("是否致死必须是布尔值")
    return 0.0 if lethal else -3.0


# ---------------------------------------------------------------------------
# 星·甘宁：铃与射却


class Suit(str, Enum):
    SPADE = "♠"
    CLUB = "♣"
    HEART = "♥"
    DIAMOND = "♦"


@dataclass(frozen=True)
class BellCard:
    card_id: str
    card_name: str
    suit: Suit | str
    category: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "card_id", _nonempty(self.card_id, "铃实体牌标识"))
        object.__setattr__(self, "card_name", _nonempty(self.card_name, "铃牌名"))
        try:
            suit = self.suit if isinstance(self.suit, Suit) else Suit(self.suit)
        except (TypeError, ValueError) as exc:
            raise ValueError("铃花色只能是♠、♣、♥或♦") from exc
        object.__setattr__(self, "suit", suit)
        _nonempty(self.category, "铃牌类别")


@dataclass(frozen=True)
class XingGanningState:
    bell_cards_by_suit: Mapping[Suit, BellCard] = field(default_factory=dict)

    def __post_init__(self) -> None:
        normalized: dict[Suit, BellCard] = {}
        for raw_suit, card in self.bell_cards_by_suit.items():
            try:
                suit = raw_suit if isinstance(raw_suit, Suit) else Suit(raw_suit)
            except (TypeError, ValueError) as exc:
                raise ValueError("存在未知铃花色栏位") from exc
            if not isinstance(card, BellCard):
                raise TypeError("铃栏位必须保存 BellCard")
            if card.suit is not suit:
                raise ValueError("铃的花色与栏位不一致")
            if suit in normalized:
                raise ValueError("每种花色最多一张铃")
            normalized[suit] = card
        object.__setattr__(self, "bell_cards_by_suit", MappingProxyType(normalized))


def store_bells(state: XingGanningState, cards: Sequence[BellCard]) -> XingGanningState:
    if not isinstance(state, XingGanningState):
        raise TypeError("星·甘宁状态必须是 XingGanningState")
    values = dict(state.bell_cards_by_suit)
    for card in cards:
        if not isinstance(card, BellCard):
            raise TypeError("要置为铃的牌必须是 BellCard")
        if card.suit in values:
            raise ValueError("同花色铃已经存在，不能再次置入")
        values[card.suit] = card
    return XingGanningState(values)


def bell_counts_as_hand_card() -> bool:
    return False


def bell_can_pay_hand_only_cost() -> bool:
    return False


def bell_can_be_used_when_hand_cards_forbidden() -> bool:
    return True


def bell_can_be_zhangba_material() -> bool:
    return True


@dataclass(frozen=True)
class BellLeaveResult:
    state_after: XingGanningState
    obtained_cards: tuple[BellCard, ...]
    draw_pile_after: tuple[BellCard, ...]


def leave_bells_and_search_same_suit(
    state: XingGanningState,
    *,
    leaving_suits: Sequence[Suit | str],
    draw_pile: Sequence[BellCard],
    owner_alive: bool,
    seed: object | None = None,
) -> BellLeaveResult:
    if not isinstance(state, XingGanningState):
        raise TypeError("星·甘宁状态必须是 XingGanningState")
    if not isinstance(owner_alive, bool):
        raise TypeError("角色是否存活必须是布尔值")
    suits: list[Suit] = []
    for value in leaving_suits:
        try:
            suit = value if isinstance(value, Suit) else Suit(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("离开的铃花色无效") from exc
        if suit in suits:
            raise ValueError("同一张铃不能在一次事件中离开两次")
        if suit not in state.bell_cards_by_suit:
            raise ValueError("指定花色栏当前没有铃")
        suits.append(suit)
    pile = list(draw_pile)
    if any(not isinstance(card, BellCard) for card in pile):
        raise TypeError("牌堆记录必须是 BellCard")
    remaining_bells = dict(state.bell_cards_by_suit)
    for suit in suits:
        del remaining_bells[suit]
    obtained: list[BellCard] = []
    if owner_alive:
        rng = make_rng(seed)
        for suit in suits:
            indices = [index for index, card in enumerate(pile) if card.suit is suit]
            if not indices:
                continue
            selected_index = rng.choice(indices)
            obtained.append(pile.pop(selected_index))
    return BellLeaveResult(XingGanningState(remaining_bells), tuple(obtained), tuple(pile))


@dataclass(frozen=True)
class ShequeResult:
    can_use: bool
    slash_kind: str | None
    ignores_distance: bool
    ignores_armor: bool
    consumes_play_phase_slash_quota: bool
    changes_attack_range: bool = False


def resolve_sheque(
    *,
    target_is_other: bool,
    target_has_equipment: bool,
    slash_kind: str | None,
) -> ShequeResult:
    if not isinstance(target_is_other, bool) or not isinstance(target_has_equipment, bool):
        raise TypeError("射却目标条件必须是布尔值")
    if not target_is_other or not target_has_equipment or slash_kind is None:
        return ShequeResult(False, None, False, False, False)
    kind = _nonempty(slash_kind, "射却提供的杀")
    if kind not in {"杀", "火杀", "雷杀"}:
        raise ValueError("射却只能提供普通杀、火杀或雷杀")
    return ShequeResult(True, kind, True, True, False)
