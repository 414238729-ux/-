"""专项武将与主公特殊裁定的轻量结算器。

本模块只实现徐荣、王经、魏/吴文鸯、鲍信、谋皇甫嵩，以及少量已
明确的主公特殊裁定。它不保存技能全文、不建立第二套完整武将数据库，
也不推断附件未提供的交互。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import math
import random
from types import MappingProxyType
from typing import Iterable, Mapping, Sequence

from ._validation import ensure_int_at_least
from .sgs_incremental_mechanics import (
    ExplicitDamageSourceResult,
    PhysicalCardIdentity,
    actual_distance_within_limit,
    count_current_hand_slashes,
    counts_as_current_hand_slash,
    resolve_explicit_damage_source,
    resolve_generated_card_after_source_death,
)


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label}必须是非空字符串")
    return value.strip()


def _bool(value: object, label: str) -> bool:
    if not isinstance(value, bool):
        raise TypeError(f"{label}必须是布尔值")
    return value


def _enum(value: object, enum_type: type[Enum], label: str) -> Enum:
    if isinstance(value, enum_type):
        return value
    try:
        return enum_type(value)
    except (TypeError, ValueError) as exc:
        choices = "、".join(str(item.value) for item in enum_type)
        raise ValueError(f"{label}只能是：{choices}") from exc


def _ids(values: Iterable[str], label: str) -> tuple[str, ...]:
    if values is None:
        raise TypeError(f"{label}不能是 None")
    try:
        result = tuple(_text(value, label) for value in values)
    except TypeError as exc:
        raise TypeError(f"{label}必须是可迭代对象") from exc
    if len(result) != len(set(result)):
        raise ValueError(f"{label}不能包含重复值")
    return result


# ---------------------------------------------------------------------------
# 徐荣


class XionghuoPunishment(str, Enum):
    FIRE_DAMAGE = "火焰伤害并禁杀"
    LOSE_HP = "失去体力并减手牌上限"
    TAKE_CARDS = "随机获得手牌与装备"


@dataclass(frozen=True)
class XionghuoState:
    available_brutality: int = 3
    marked_other_ids: frozenset[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        ensure_int_at_least(self.available_brutality, "徐荣可分配暴戾数", 0)
        object.__setattr__(
            self,
            "marked_other_ids",
            frozenset(_text(value, "暴戾角色编号") for value in self.marked_other_ids),
        )


def assign_xionghuo_brutality(
    state: XionghuoState,
    *,
    xurong_id: str,
    target_id: str,
) -> XionghuoState:
    if not isinstance(state, XionghuoState):
        raise TypeError("凶镬状态必须是 XionghuoState")
    xurong = _text(xurong_id, "徐荣角色编号")
    target = _text(target_id, "暴戾目标编号")
    if xurong == target:
        raise ValueError("凶镬只能将暴戾分配给其他角色")
    if state.available_brutality <= 0:
        raise ValueError("徐荣当前没有可分配的暴戾")
    if target in state.marked_other_ids:
        raise ValueError("不能给已经有暴戾的角色再次分配暴戾")
    return XionghuoState(
        state.available_brutality - 1,
        state.marked_other_ids | {target},
    )


def xionghuo_modified_damage(base_damage: int, *, target_has_brutality: bool) -> int:
    """每名受伤角色分别读取自己的暴戾；0点不凭空变成伤害。"""

    damage = ensure_int_at_least(base_damage, "凶镬修正前伤害", 0)
    _bool(target_has_brutality, "目标是否有暴戾")
    return damage + 1 if damage > 0 and target_has_brutality else damage


def xionghuo_chain_damages(
    base_damages: Iterable[tuple[str, int, bool]],
) -> Mapping[str, int]:
    """对铁索中的每名角色独立应用暴戾加伤。"""

    result: dict[str, int] = {}
    for target_id, damage, has_token in base_damages:
        target = _text(target_id, "凶镬伤害目标")
        if target in result:
            raise ValueError("凶镬连环目标不能重复")
        result[target] = xionghuo_modified_damage(
            damage,
            target_has_brutality=has_token,
        )
    return MappingProxyType(result)


@dataclass(frozen=True)
class XionghuoPunishmentResult:
    punishment: XionghuoPunishment
    token_removed: bool
    fire_damage: int = 0
    hp_loss: int = 0
    cannot_slash_xurong_this_turn: bool = False
    hand_limit_modifier: int = 0
    obtained_hand_card_id: str | None = None
    obtained_equipment_card_id: str | None = None


def resolve_xionghuo_play_phase_start(
    *,
    punishment: XionghuoPunishment | str | None = None,
    hand_card_ids: Iterable[str] = (),
    equipment_card_ids: Iterable[str] = (),
    seed: int | None = None,
) -> XionghuoPunishmentResult:
    """移去暴戾后执行一项；第三项对两个区域分别随机取一张。"""

    rng = random.Random(seed)
    branch = (
        rng.choice(tuple(XionghuoPunishment))
        if punishment is None
        else _enum(punishment, XionghuoPunishment, "凶镬随机项")
    )
    hand = _ids(hand_card_ids, "凶镬目标手牌")
    equipment = _ids(equipment_card_ids, "凶镬目标装备")
    if branch is XionghuoPunishment.FIRE_DAMAGE:
        return XionghuoPunishmentResult(branch, True, 1, 0, True)
    if branch is XionghuoPunishment.LOSE_HP:
        return XionghuoPunishmentResult(branch, True, 0, 1, False, -1)
    return XionghuoPunishmentResult(
        branch,
        True,
        obtained_hand_card_id=rng.choice(hand) if hand else None,
        obtained_equipment_card_id=rng.choice(equipment) if equipment else None,
    )


@dataclass(frozen=True)
class ShajueResult:
    triggered: bool
    brutality_gained: int
    obtained_damage_card_id: str | None


def resolve_shajue(
    *,
    target_is_other: bool,
    hp_after_damage: int,
    damage_card_id: str | None,
    damage_card_obtainable: bool,
) -> ShajueResult:
    """仅其他角色因伤害进入体力小于0的深度濒死时触发。"""

    _bool(target_is_other, "是否为其他角色")
    if isinstance(hp_after_damage, bool) or not isinstance(hp_after_damage, int):
        raise TypeError("伤害后体力必须是整数")
    _bool(damage_card_obtainable, "伤害牌是否仍可取得")
    triggered = target_is_other and hp_after_damage < 0
    obtained = None
    if triggered and damage_card_obtainable and damage_card_id is not None:
        obtained = _text(damage_card_id, "伤害牌编号")
    return ShajueResult(triggered, int(triggered), obtained)


def should_xurong_spy_attack(expected_net_value: float) -> bool:
    """内奸策略允许放弃净收益不为正的攻击。"""

    if isinstance(expected_net_value, bool) or not isinstance(expected_net_value, (int, float)):
        raise TypeError("攻击期望净收益必须是数值")
    if not math.isfinite(float(expected_net_value)):
        raise ValueError("攻击期望净收益必须是有限数值")
    return float(expected_net_value) > 0


# ---------------------------------------------------------------------------
# 王经


class ZujinConvertedName(str, Enum):
    SLASH = "杀"
    DODGE = "闪"
    NULLIFICATION = "无懈可击"


@dataclass(frozen=True)
class ZujinGlobalTurnState:
    global_turn_id: str
    used_converted_names: frozenset[ZujinConvertedName] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        object.__setattr__(self, "global_turn_id", _text(self.global_turn_id, "全局回合编号"))
        object.__setattr__(
            self,
            "used_converted_names",
            frozenset(
                _enum(name, ZujinConvertedName, "阻进转化牌名")
                for name in self.used_converted_names
            ),
        )


def start_zujin_global_turn(global_turn_id: str) -> ZujinGlobalTurnState:
    return ZujinGlobalTurnState(global_turn_id)


@dataclass(frozen=True)
class ZujinConversionResult:
    state_after: ZujinGlobalTurnState
    legal: bool
    converted_name: ZujinConvertedName
    reason: str


def resolve_zujin_conversion(
    state: ZujinGlobalTurnState,
    *,
    converted_name: ZujinConvertedName | str,
    current_hp: int,
    maximum_hp: int,
    all_alive_hp: Sequence[int],
    material_is_basic_card: bool = True,
) -> ZujinConversionResult:
    """【杀】【闪】【无懈可击】在每个全局回合分别限一次。"""

    if not isinstance(state, ZujinGlobalTurnState):
        raise TypeError("阻进状态必须是 ZujinGlobalTurnState")
    name = _enum(converted_name, ZujinConvertedName, "阻进转化牌名")
    hp = ensure_int_at_least(current_hp, "王经当前体力", 0)
    max_hp = ensure_int_at_least(maximum_hp, "王经体力上限", 1)
    if hp > max_hp:
        raise ValueError("王经当前体力不能高于体力上限")
    alive_hp = tuple(
        ensure_int_at_least(value, "存活角色体力", 0) for value in all_alive_hp
    )
    if not alive_hp or hp not in alive_hp:
        raise ValueError("存活角色体力列表必须包含王经当前体力")
    _bool(material_is_basic_card, "阻进材料是否为基本牌")
    if not material_is_basic_card:
        return ZujinConversionResult(state, False, name, "材料不是基本牌")
    if name in state.used_converted_names:
        return ZujinConversionResult(state, False, name, "本全局回合该转化牌名已经使用")
    wounded = hp < max_hp
    is_full_hp = hp == max_hp
    is_not_global_minimum = hp > min(alive_hp)
    condition = (
        wounded
        if name is not ZujinConvertedName.SLASH
        else (is_full_hp or is_not_global_minimum)
    )
    if not condition:
        reason = "闪和无懈可击转化要求王经已受伤" if name is not ZujinConvertedName.SLASH else "受伤且处于全场最低体力时不能转化杀（并列最低也不满足）"
        return ZujinConversionResult(state, False, name, reason)
    after = ZujinGlobalTurnState(
        state.global_turn_id,
        state.used_converted_names | {name},
    )
    return ZujinConversionResult(after, True, name, "当前转化合法并独立占用该牌名次数")


@dataclass(frozen=True)
class JiejianMarkState:
    wangjing_id: str
    marked_id: str
    hp_snapshot: int
    given_card_ids: tuple[str, ...]
    triggered_global_turn_ids: frozenset[str] = field(default_factory=frozenset)


def create_jiejian_mark(
    *,
    wangjing_id: str,
    marked_id: str,
    marked_current_hp: int,
    given_card_ids: Iterable[str],
) -> JiejianMarkState:
    wid = _text(wangjing_id, "王经角色编号")
    mid = _text(marked_id, "节谏目标编号")
    if wid == mid:
        raise ValueError("节谏只能选择一名其他角色")
    cards = _ids(given_card_ids, "节谏交给目标的牌")
    if not cards:
        raise ValueError("发动节谏必须交给目标至少一张牌")
    return JiejianMarkState(
        wid,
        mid,
        ensure_int_at_least(marked_current_hp, "节谏记录体力", 0),
        cards,
    )


@dataclass(frozen=True)
class JiejianTriggerResult:
    state_after: JiejianMarkState
    triggered: bool
    target_redirected_to: str | None
    draw_count: int
    delayed_trick_stays_on_original_target: bool
    reason: str


def resolve_jiejian_target_event(
    state: JiejianMarkState,
    *,
    global_turn_id: str,
    target_ids: Sequence[str],
    delayed_trick: bool,
    activate: bool = True,
) -> JiejianTriggerResult:
    if not isinstance(state, JiejianMarkState):
        raise TypeError("节谏标记必须是 JiejianMarkState")
    turn = _text(global_turn_id, "当前全局回合编号")
    targets = tuple(_text(target, "牌目标") for target in target_ids)
    _bool(delayed_trick, "是否为延时锦囊")
    _bool(activate, "是否发动节谏")
    if not activate:
        return JiejianTriggerResult(state, False, None, 0, False, "王经选择不发动")
    if targets != (state.marked_id,):
        return JiejianTriggerResult(state, False, None, 0, False, "必须是只指定标记角色的牌")
    if turn in state.triggered_global_turn_ids:
        return JiejianTriggerResult(state, False, None, 0, False, "本角色回合已经发动过节谏")
    after = JiejianMarkState(
        state.wangjing_id,
        state.marked_id,
        state.hp_snapshot,
        state.given_card_ids,
        state.triggered_global_turn_ids | {turn},
    )
    return JiejianTriggerResult(
        after,
        True,
        None if delayed_trick else state.wangjing_id,
        1,
        delayed_trick,
        "延时锦囊只摸牌不改目标" if delayed_trick else "普通单目标牌改为王经并摸一张",
    )


@dataclass(frozen=True)
class JiejianEndResult:
    mark_removed: bool
    wangjing_draw_count: int
    state_after: JiejianMarkState | None


def resolve_jiejian_marked_turn_end(
    state: JiejianMarkState,
    *,
    marked_current_hp: int,
    entire_turn_skipped: bool = False,
) -> JiejianEndResult:
    if not isinstance(state, JiejianMarkState):
        raise TypeError("节谏标记必须是 JiejianMarkState")
    current = ensure_int_at_least(marked_current_hp, "标记角色当前体力", 0)
    _bool(entire_turn_skipped, "是否跳过整个回合")
    if entire_turn_skipped:
        return JiejianEndResult(False, 0, state)
    return JiejianEndResult(True, 2 if current >= state.hp_snapshot else 0, None)


# ---------------------------------------------------------------------------
# 文鸯


class WenyangRoute(str, Enum):
    WEI = "魏"
    WU = "吴"


WENYANG_ROUTE_TAUNT = MappingProxyType(
    {WenyangRoute.WEI: "常态高嘲讽", WenyangRoute.WU: "装备依赖、动态上升"}
)


class QuediChoice(str, Enum):
    OBTAIN_HAND = "获得目标一张手牌"
    DISCARD_BASIC = "弃基本牌令伤害加一"
    BACKWATER = "背水"


@dataclass(frozen=True)
class QuediTurnState:
    used_count: int = 0
    extra_uses_from_kills: int = 0

    @property
    def use_limit(self) -> int:
        return 1 + self.extra_uses_from_kills


@dataclass(frozen=True)
class QuediResult:
    state_after: QuediTurnState
    obtained_card_id: str | None
    discarded_basic_card_id: str | None
    damage_bonus: int
    maximum_hp_loss: int
    event_order: tuple[str, ...]


def resolve_quedi(
    state: QuediTurnState,
    *,
    choice: QuediChoice | str,
    target_hand_card_ids: Iterable[str] = (),
    selected_obtained_card_id: str | None = None,
    selected_obtained_card_is_basic: bool = False,
    basic_card_ids_before: Iterable[str] = (),
    selected_discard_card_id: str | None = None,
) -> QuediResult:
    if not isinstance(state, QuediTurnState):
        raise TypeError("却敌状态必须是 QuediTurnState")
    if state.used_count >= state.use_limit:
        raise ValueError("本回合却敌可用次数已经用完")
    branch = _enum(choice, QuediChoice, "却敌选项")
    target_hand = _ids(target_hand_card_ids, "却敌目标手牌")
    _bool(selected_obtained_card_is_basic, "却敌第一项获得牌是否为基本牌")
    basics = set(_ids(basic_card_ids_before, "却敌发动前基本牌"))
    obtained: str | None = None
    discarded: str | None = None
    order: list[str] = []
    if branch in {QuediChoice.OBTAIN_HAND, QuediChoice.BACKWATER}:
        if not target_hand:
            raise ValueError("目标没有手牌，不能执行却敌第一项")
        obtained = _text(selected_obtained_card_id, "却敌获得牌编号")
        if obtained not in target_hand:
            raise ValueError("却敌获得牌必须来自目标当前手牌")
        order.append("获得目标一张手牌")
    if branch in {QuediChoice.DISCARD_BASIC, QuediChoice.BACKWATER}:
        if selected_discard_card_id is None:
            raise ValueError("却敌第二项必须指定一张基本牌作为材料")
        discarded = _text(selected_discard_card_id, "却敌弃置基本牌编号")
        legal_basics = basics | (
            {obtained}
            if obtained is not None and selected_obtained_card_is_basic
            else set()
        )
        if discarded not in legal_basics:
            raise ValueError("却敌只能弃置原有基本牌，或第一项刚获得的基本牌")
        order.append("弃置一张基本牌并令伤害加一")
    max_loss = int(branch is QuediChoice.BACKWATER)
    if max_loss:
        order.append("最后减少一点体力上限")
    return QuediResult(
        QuediTurnState(state.used_count + 1, state.extra_uses_from_kills),
        obtained,
        discarded,
        int(branch in {QuediChoice.DISCARD_BASIC, QuediChoice.BACKWATER}),
        max_loss,
        tuple(order),
    )


@dataclass(frozen=True)
class ChoujueResult:
    quedi_state_after: QuediTurnState
    maximum_hp_gain: int
    draw_count: int


def resolve_choujue_kill(state: QuediTurnState) -> ChoujueResult:
    if not isinstance(state, QuediTurnState):
        raise TypeError("却敌状态必须是 QuediTurnState")
    return ChoujueResult(
        QuediTurnState(state.used_count, state.extra_uses_from_kills + 1),
        1,
        2,
    )


@dataclass(frozen=True)
class ChoujueHealthResult:
    """【仇决】增加体力上限后的生命状态，不附带回复体力。"""

    hp_after: int
    maximum_hp_after: int
    recovered_hp: int = 0


def apply_choujue_maximum_hp_gain(
    current_hp: int,
    current_maximum_hp: int,
) -> ChoujueHealthResult:
    """令体力上限加一，但保持当前体力不变。"""

    hp = ensure_int_at_least(current_hp, "吴文鸯当前体力", 0)
    maximum = ensure_int_at_least(current_maximum_hp, "吴文鸯当前体力上限", 1)
    if hp > maximum:
        raise ValueError("吴文鸯当前体力不能高于当前体力上限")
    return ChoujueHealthResult(hp, maximum + 1, 0)


@dataclass(frozen=True)
class ZhuifengResult:
    hp_after_loss: int
    entered_dying: bool
    source_died: bool
    generated_duel_started: bool
    target_played_slash: bool
    source_can_play_next_slash: bool
    duel_ended: bool
    event_order: tuple[str, ...]


def resolve_zhuifeng_generated_duel(
    *,
    current_hp: int,
    uses_this_play_phase: int,
    target_plays_slash: bool,
    rescued_after_hp_loss: bool = False,
    game_ended_after_hp_loss: bool = False,
) -> ZhuifengResult:
    hp = ensure_int_at_least(current_hp, "椎锋发动前体力", 1)
    uses = ensure_int_at_least(uses_this_play_phase, "椎锋本阶段已用次数", 0)
    if uses >= 2:
        raise ValueError("椎锋每个出牌阶段最多发动两次")
    _bool(target_plays_slash, "目标是否打出杀")
    _bool(rescued_after_hp_loss, "流失体力进入濒死后是否获救")
    _bool(game_ended_after_hp_loss, "流失体力后游戏是否结束")
    hp_after = hp - 1
    entered_dying = hp_after <= 0
    if rescued_after_hp_loss and not entered_dying:
        raise ValueError("只有流失体力后进入濒死，才能标记为获救")
    if rescued_after_hp_loss and game_ended_after_hp_loss:
        raise ValueError("已经获救时不能同时标记为游戏结束")
    died = entered_dying and not rescued_after_hp_loss
    continuation = resolve_generated_card_after_source_death(
        generated_legally=True,
        source_alive=not died,
        game_ended=game_ended_after_hp_loss,
        next_step_requires_source_action=died and target_plays_slash,
    )
    order = ["流失一点体力", "生成并开始结算决斗"]
    if entered_dying:
        order.append("完成濒死救援并确认文鸯是否死亡")
    if game_ended_after_hp_loss:
        order.append("游戏结束，停止结算")
    elif target_plays_slash:
        order.append("目标打出一张杀")
        order.append("文鸯存活则继续响应，否则决斗结束")
    else:
        order.append("目标未打出杀，结算决斗伤害")
    return ZhuifengResult(
        hp_after,
        entered_dying,
        died,
        continuation.generated_card_started,
        target_plays_slash and not game_ended_after_hp_loss,
        not died and target_plays_slash and not game_ended_after_hp_loss,
        game_ended_after_hp_loss or not target_plays_slash or died,
        tuple(order),
    )


@dataclass(frozen=True)
class ChongjianRecipientResult:
    target_id: str
    actual_damage: int
    target_alive_after_damage: bool
    obtained_equipment_card_ids: tuple[str, ...]


def resolve_chongjian_recipients(
    recipients: Iterable[tuple[str, int, bool, Sequence[str]]],
    *,
    selected_equipment_by_target: Mapping[str, Sequence[str]] | None = None,
) -> tuple[ChongjianRecipientResult, ...]:
    """每名实际受伤且仍存活的角色分别选择取得至多伤害值张装备。"""

    results: list[ChongjianRecipientResult] = []
    seen: set[str] = set()
    if selected_equipment_by_target is not None and not isinstance(
        selected_equipment_by_target, Mapping
    ):
        raise TypeError("冲坚装备选择必须是角色到装备牌序列的映射")
    selected_mapping = selected_equipment_by_target or {}
    for target_id, actual_damage, alive, equipment_ids in recipients:
        target = _text(target_id, "冲坚受伤角色")
        if target in seen:
            raise ValueError("冲坚受伤角色不能重复")
        seen.add(target)
        damage = ensure_int_at_least(actual_damage, "冲坚实际伤害", 0)
        _bool(alive, "受伤角色是否仍存活")
        equipment = _ids(equipment_ids, "受伤角色装备牌")
        if target in selected_mapping:
            selected = _ids(selected_mapping[target], "冲坚选择取得的装备牌")
            if len(selected) > damage:
                raise ValueError("冲坚取得装备数量不能超过该角色受到的伤害值")
            if any(card_id not in equipment for card_id in selected):
                raise ValueError("冲坚只能取得该受伤角色装备区内的牌")
            if selected and (damage <= 0 or not alive):
                raise ValueError("未实际受伤或已经死亡的角色不能提供冲坚装备")
            gains = selected
        else:
            gains = equipment[:damage] if damage > 0 and alive else ()
        results.append(ChongjianRecipientResult(target, damage, alive, gains))
    unknown_targets = set(selected_mapping) - seen
    if unknown_targets:
        raise ValueError(
            "冲坚装备选择包含未结算角色：" + "、".join(sorted(unknown_targets))
        )
    return tuple(results)


# ---------------------------------------------------------------------------
# 主公特殊裁定


def yanzhu_option_one_available(target_equipment_count: int) -> bool:
    return ensure_int_at_least(target_equipment_count, "宴诛目标装备数", 0) > 0


def ruoyu_can_awaken(liushan_hp: int, all_alive_hp: Sequence[int]) -> bool:
    hp = ensure_int_at_least(liushan_hp, "刘禅当前体力", 0)
    values = tuple(ensure_int_at_least(value, "存活角色体力", 0) for value in all_alive_hp)
    if not values or hp not in values:
        raise ValueError("存活角色体力列表必须包含刘禅当前体力")
    return hp == min(values)


def mou_yuanshao_has_guaranteed_other_qun(
    *,
    lord_player_id: str,
    factions_by_player: Mapping[str, str],
) -> bool:
    lord = _text(lord_player_id, "谋袁绍角色编号")
    if lord not in factions_by_player:
        raise ValueError("势力映射必须包含谋袁绍")
    return any(
        player_id != lord and faction == "群"
        for player_id, faction in factions_by_player.items()
    )


@dataclass(frozen=True)
class XueyiTurnState:
    drawn_this_turn: int = 0

    def __post_init__(self) -> None:
        drawn = ensure_int_at_least(self.drawn_this_turn, "血裔本回合已摸牌数", 0)
        if drawn > 2:
            raise ValueError("血裔本回合摸牌数不能超过2")


@dataclass(frozen=True)
class XueyiTargetResult:
    trigger_count: int
    draw_count: int
    state_after: XueyiTurnState


def resolve_xueyi_targets(
    target_factions: Iterable[str],
    *,
    turn_state: XueyiTurnState | None = None,
) -> XueyiTargetResult:
    factions = tuple(_text(value, "血裔目标势力") for value in target_factions)
    state = XueyiTurnState() if turn_state is None else turn_state
    if not isinstance(state, XueyiTurnState):
        raise TypeError("血裔回合状态必须是 XueyiTurnState")
    triggers = sum(faction == "群" for faction in factions)
    draw_count = min(triggers, 2 - state.drawn_this_turn)
    return XueyiTargetResult(
        triggers,
        draw_count,
        XueyiTurnState(state.drawn_this_turn + draw_count),
    )


# ---------------------------------------------------------------------------
# 鲍信


@dataclass(frozen=True)
class MutaoDistribution:
    card_id: str
    recipient_id: str


@dataclass(frozen=True)
class MutaoResult:
    activated: bool
    distributed: tuple[MutaoDistribution, ...]
    last_recipient_id: str | None
    damage_amount: int
    damage_source: ExplicitDamageSourceResult | None
    damage_is_attributeless: bool
    damage_is_from_slash: bool
    can_respond_with_dodge: bool
    hands_after: Mapping[str, tuple[PhysicalCardIdentity, ...]]


def resolve_mutao(
    *,
    baoxin_id: str,
    original_target_id: str,
    living_ring: Sequence[str],
    hands_by_player: Mapping[str, Sequence[PhysicalCardIdentity]],
    seed: int | None = None,
) -> MutaoResult:
    """循环分发原目标全部当前卡名【杀】，最后由原目标造成至多2点伤害。"""

    baoxin = _text(baoxin_id, "鲍信角色编号")
    original = _text(original_target_id, "募讨原目标")
    ring = tuple(_text(player, "存活角色环") for player in living_ring)
    if len(ring) != len(set(ring)) or not ring:
        raise ValueError("存活角色环不能为空且不能包含重复角色")
    if original not in ring:
        raise ValueError("募讨原目标必须位于存活角色环中")
    if not isinstance(hands_by_player, Mapping):
        raise TypeError("募讨手牌必须是玩家到实体牌序列的映射")
    hands: dict[str, list[PhysicalCardIdentity]] = {}
    all_ids: list[str] = []
    for player in ring:
        if player not in hands_by_player:
            raise ValueError(f"募讨缺少{player}的手牌信息")
        cards = list(hands_by_player[player])
        if not all(isinstance(card, PhysicalCardIdentity) for card in cards):
            raise TypeError("募讨手牌必须由 PhysicalCardIdentity 组成")
        hands[player] = cards
        all_ids.extend(card.card_id for card in cards)
    if len(all_ids) != len(set(all_ids)):
        raise ValueError("同一实体牌不能同时出现在多名角色手牌中")

    slash_cards = [card for card in hands[original] if counts_as_current_hand_slash(card)]
    hands[original] = [card for card in hands[original] if card not in slash_cards]
    if not slash_cards:
        return MutaoResult(
            True,
            (),
            None,
            0,
            None,
            False,
            False,
            False,
            MappingProxyType({key: tuple(value) for key, value in hands.items()}),
        )
    random.Random(seed).shuffle(slash_cards)
    start = ring.index(original)
    distributed: list[MutaoDistribution] = []
    for offset, card in enumerate(slash_cards, 1):
        recipient = ring[(start + offset) % len(ring)]
        hands[recipient].append(card)
        distributed.append(MutaoDistribution(card.card_id, recipient))
    last = distributed[-1].recipient_id
    damage = min(count_current_hand_slashes(hands[last]), 2)
    source = resolve_explicit_damage_source(
        actor_id=original,
        skill_owner_id=baoxin,
        target_id=last,
    )
    return MutaoResult(
        True,
        tuple(distributed),
        last,
        damage,
        source,
        True,
        False,
        False,
        MappingProxyType({key: tuple(value) for key, value in hands.items()}),
    )


def yimou_trigger_count(*, actual_damage: int, actual_distance_to_baoxin: int) -> int:
    damage = ensure_int_at_least(actual_damage, "毅谋对应实际伤害", 0)
    distance = ensure_int_at_least(actual_distance_to_baoxin, "受伤角色与鲍信实际距离", 0)
    return int(damage > 0 and actual_distance_within_limit(distance, 1))


@dataclass(frozen=True)
class YimouGainSlashResult:
    obtained_card_id: str | None
    deck_after: tuple[PhysicalCardIdentity, ...]


def resolve_yimou_gain_random_slash(
    deck: Sequence[PhysicalCardIdentity],
    *,
    seed: int | None = None,
) -> YimouGainSlashResult:
    if not all(isinstance(card, PhysicalCardIdentity) for card in deck):
        raise TypeError("毅谋牌堆必须由 PhysicalCardIdentity 组成")
    candidates = [card for card in deck if card.current_card_name in {"杀", "火杀", "雷杀"}]
    if not candidates:
        return YimouGainSlashResult(None, tuple(deck))
    selected = random.Random(seed).choice(candidates)
    return YimouGainSlashResult(
        selected.card_id,
        tuple(card for card in deck if card.card_id != selected.card_id),
    )


@dataclass(frozen=True)
class YimouTransferResult:
    given_card_id: str
    recipient_id: str
    draw_count: int = 1


def resolve_yimou_transfer(
    *,
    injured_hand_card_ids: Iterable[str],
    selected_card_id: str,
    injured_player_id: str,
    recipient_id: str,
) -> YimouTransferResult:
    hand = _ids(injured_hand_card_ids, "毅谋受伤角色手牌")
    if not hand:
        raise ValueError("受伤角色没有手牌，不能选择毅谋第二项")
    selected = _text(selected_card_id, "毅谋交出牌编号")
    if selected not in hand:
        raise ValueError("毅谋只能交出受伤角色当前手牌")
    injured = _text(injured_player_id, "受伤角色编号")
    recipient = _text(recipient_id, "毅谋收牌角色")
    if injured == recipient:
        raise ValueError("毅谋第二项必须交给另一名角色")
    return YimouTransferResult(selected, recipient)


# ---------------------------------------------------------------------------
# 谋皇甫嵩


@dataclass(frozen=True)
class ColoredHandCard:
    card_id: str
    color: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "card_id", _text(self.card_id, "手牌编号"))
        if self.color not in {"红", "黑", "无色"}:
            raise ValueError("手牌颜色只能是红、黑或无色")


@dataclass(frozen=True)
class ShijiVictimInput:
    target_id: str
    hand_cards: tuple[ColoredHandCard, ...]


@dataclass(frozen=True)
class ShijiEventResult:
    target_id: str
    triggered: bool
    discarded_red_card_ids: tuple[str, ...]
    draw_count: int
    huangfusong_hand_count_after: int


def resolve_shiji_chain(
    *,
    huangfusong_id: str,
    huangfusong_hand_count: int,
    other_hand_counts: Mapping[str, int],
    victims_in_order: Sequence[ShijiVictimInput],
) -> tuple[ShijiEventResult, ...]:
    """每名属性伤害受伤者按最新手牌状态分别检查【势击】。"""

    hid = _text(huangfusong_id, "谋皇甫嵩角色编号")
    current_hf = ensure_int_at_least(huangfusong_hand_count, "谋皇甫嵩手牌数", 0)
    counts = {
        _text(player, "角色编号"): ensure_int_at_least(count, "角色手牌数", 0)
        for player, count in other_hand_counts.items()
    }
    if hid in counts:
        raise ValueError("其他角色手牌数映射不能重复包含谋皇甫嵩")
    results: list[ShijiEventResult] = []
    for victim in victims_in_order:
        if not isinstance(victim, ShijiVictimInput):
            raise TypeError("势击受伤者必须使用 ShijiVictimInput")
        target = _text(victim.target_id, "势击受伤角色")
        if target == hid:
            raise ValueError("势击只处理谋皇甫嵩造成给其他角色的属性伤害")
        counts[target] = len(victim.hand_cards)
        unique_maximum = all(current_hf > count for count in counts.values())
        if unique_maximum:
            results.append(ShijiEventResult(target, False, (), 0, current_hf))
            continue
        red = tuple(card.card_id for card in victim.hand_cards if card.color == "红")
        counts[target] -= len(red)
        current_hf += len(red)
        results.append(ShijiEventResult(target, True, red, len(red), current_hf))
    return tuple(results)


class TaoluanChoice(str, Enum):
    TAKE_JUDGMENT_CARD = "获得判定牌"
    FIRE_SLASH = "视为使用火杀"


@dataclass(frozen=True)
class TaoluanTurnState:
    used_count: int = 0

    def __post_init__(self) -> None:
        used = ensure_int_at_least(self.used_count, "讨乱本回合已发动次数", 0)
        if used > 1:
            raise ValueError("讨乱每回合限一次")


@dataclass(frozen=True)
class TaoluanResult:
    triggered: bool
    judgment_terminated: bool
    delayed_trick_remains_in_original_zone: bool
    delayed_trick_processed_again_this_turn: bool
    judgment_card_destination: str
    virtual_fire_slash_generated: bool
    ignores_distance: bool
    ignores_normal_slash_quota: bool
    turn_state_after: TaoluanTurnState


def resolve_taoluan(
    *,
    judgment_suit: str,
    judgment_card_id: str,
    judged_character_is_self: bool,
    choice: TaoluanChoice | str | None = None,
    judgment_from_delayed_trick: bool = False,
    turn_state: TaoluanTurnState | None = None,
) -> TaoluanResult:
    suit = _text(judgment_suit, "讨乱判定花色")
    _text(judgment_card_id, "讨乱判定牌编号")
    _bool(judged_character_is_self, "判定角色是否为谋皇甫嵩")
    _bool(judgment_from_delayed_trick, "是否来自延时锦囊判定")
    state = TaoluanTurnState() if turn_state is None else turn_state
    if not isinstance(state, TaoluanTurnState):
        raise TypeError("讨乱回合状态必须是 TaoluanTurnState")
    if suit != "黑桃":
        return TaoluanResult(
            False,
            False,
            False,
            False,
            "按原判定流程处理",
            False,
            False,
            False,
            state,
        )
    if state.used_count >= 1:
        raise ValueError("讨乱本回合已经发动过")
    if choice is None:
        raise ValueError("黑桃判定触发讨乱时必须选择一项")
    branch = _enum(choice, TaoluanChoice, "讨乱选项")
    if branch is TaoluanChoice.FIRE_SLASH and judged_character_is_self:
        raise ValueError("判定角色是谋皇甫嵩本人时不能选择讨乱火杀项")
    fire_slash = branch is TaoluanChoice.FIRE_SLASH
    return TaoluanResult(
        True,
        True,
        judgment_from_delayed_trick,
        False,
        "弃牌堆" if fire_slash else "谋皇甫嵩手牌",
        fire_slash,
        fire_slash,
        fire_slash,
        TaoluanTurnState(1),
    )


@dataclass(frozen=True)
class TaoluanFireSlashResult:
    responded_by_dodge: bool
    actual_damage: int
    can_trigger_shiji: bool


def resolve_taoluan_fire_slash(
    *,
    target_plays_dodge: bool,
    damage_prevented: bool = False,
) -> TaoluanFireSlashResult:
    _bool(target_plays_dodge, "目标是否打出闪")
    _bool(damage_prevented, "火杀伤害是否被防止")
    damage = 0 if target_plays_dodge or damage_prevented else 1
    return TaoluanFireSlashResult(target_plays_dodge, damage, damage > 0)


class RectificationTask(str, Enum):
    LEIJIN = "擂进"
    BIANZHEN = "变阵"
    MINGZHI = "鸣止"


@dataclass(frozen=True)
class RectificationCardRecord:
    card_id: str
    rank: int | None
    suit: str | None
    effect_invalidated: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "card_id", _text(self.card_id, "整肃牌编号"))
        if self.rank is not None:
            ensure_int_at_least(self.rank, "整肃牌点数", 1)
        if self.suit is not None:
            object.__setattr__(self, "suit", _text(self.suit, "整肃牌花色"))
        _bool(self.effect_invalidated, "牌效果是否无效")


@dataclass(frozen=True)
class RectificationResult:
    task: RectificationTask
    success: bool
    recorded_card_ids: tuple[str, ...]
    reason: str


def evaluate_rectification(
    task: RectificationTask | str,
    records: Sequence[RectificationCardRecord],
) -> RectificationResult:
    """记录全部相关牌；效果无效仍计入，缺点数/花色绝不自动通过。"""

    resolved = _enum(task, RectificationTask, "整肃任务")
    if not all(isinstance(record, RectificationCardRecord) for record in records):
        raise TypeError("整肃记录必须由 RectificationCardRecord 组成")
    ids = tuple(record.card_id for record in records)
    if len(ids) != len(set(ids)):
        raise ValueError("整肃记录实体牌编号不能重复")
    if resolved is RectificationTask.LEIJIN:
        if len(records) < 3:
            return RectificationResult(resolved, False, ids, "擂进至少需要使用三张牌")
        if any(record.rank is None for record in records):
            return RectificationResult(resolved, False, ids, "存在无点数牌，不能自动视为严格递增")
        ranks = tuple(record.rank for record in records)
        success = all(left < right for left, right in zip(ranks, ranks[1:]))
        return RectificationResult(resolved, success, ids, "全部点数严格递增" if success else "存在不递增的使用牌")
    if resolved is RectificationTask.BIANZHEN:
        if len(records) < 2:
            return RectificationResult(resolved, False, ids, "变阵至少需要使用两张牌")
        if any(record.suit is None for record in records):
            return RectificationResult(resolved, False, ids, "存在无花色牌，不能自动视为同花色")
        success = len({record.suit for record in records}) == 1
        return RectificationResult(resolved, success, ids, "全部牌花色相同" if success else "存在不同花色的使用牌")
    if len(records) < 2:
        return RectificationResult(resolved, False, ids, "鸣止至少需要弃置两张牌")
    if any(record.suit is None for record in records):
        return RectificationResult(resolved, False, ids, "存在无花色牌，不能自动视为花色各异")
    success = len({record.suit for record in records}) == len(records)
    return RectificationResult(resolved, success, ids, "全部弃牌花色各异" if success else "弃牌花色存在重复")


class RectificationReward(str, Enum):
    DRAW_TWO = "摸两张牌"
    RECOVER_ONE = "回复一点体力"


@dataclass(frozen=True)
class ZhengjunRewardResult:
    self_choice: RectificationReward
    self_draw_count: int
    self_recover_hp: int
    other_choice: RectificationReward | None
    other_draw_count: int
    other_recover_hp: int
    event_order: tuple[str, ...]


def resolve_zhengjun_rewards(
    *,
    self_choice: RectificationReward | str,
    other_choice: RectificationReward | str | None = None,
) -> ZhengjunRewardResult:
    own = _enum(self_choice, RectificationReward, "谋皇甫嵩整肃奖励")
    other = (
        None
        if other_choice is None
        else _enum(other_choice, RectificationReward, "另一角色整肃奖励")
    )
    event_order = ["谋皇甫嵩选择并结算奖励"]
    if other is not None:
        event_order.extend(("选择另一名角色", "另一角色独立选择并结算奖励"))
    return ZhengjunRewardResult(
        own,
        2 if own is RectificationReward.DRAW_TWO else 0,
        1 if own is RectificationReward.RECOVER_ONE else 0,
        other,
        2 if other is RectificationReward.DRAW_TWO else 0,
        1 if other is RectificationReward.RECOVER_ONE else 0,
        tuple(event_order),
    )
