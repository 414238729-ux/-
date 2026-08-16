# -*- coding: utf-8 -*-
"""POST-B C2：多人卡牌语义闭合专项测试。

覆盖：方天画戟多人多目标（合法/非法/伪造/逐目标响应/死亡继续）、
多人群体锦囊、多人无懈链、借刀多人候选、延时锦囊/闪电4p、多人距离/
坐骑/防具逐目标隔离、player_ids/seat replay 往返、custom finish_reason
回放、4-observer visibility、38类覆盖矩阵等。

只走真实生产路径：enumerate_legal_actions → validate_action →
apply_action → response → resolution → strict replay。
"""

from __future__ import annotations

from dataclasses import replace
from itertools import combinations

import pytest

from scripts.sgs_engine.actions import (
    ActionType,
    InvalidActionError,
    LegalAction,
    UnsupportedRuleError,
    validate_action,
)
from scripts.sgs_engine.events import EventType
from scripts.sgs_engine.model import (
    DISCARD_PILE,
    DRAW_PILE,
    ZoneRef,
)
from scripts.sgs_engine.multiplayer import OutcomePolicy, PlayerTopology
from scripts.sgs_engine.production_batch import (
    BatchActionIdController,
    ProductionBatchError,
    ProductionBasicCardBatch,
    ProductionPhase,
    _replace_player,
)
from scripts.sgs_engine.production_cards import (
    WEAPON_SKILL_STATUS,
    equipped_weapon_key,
)

SHA = "sgs_basic_sha"
SHAN = "sgs_basic_shan"
TAO = "sgs_basic_tao"
JIU = "sgs_basic_jiu"
FANGTIAN = "sgs_weapon_fangtianhuaji"

# seed 2 的四人局首回合角色是 p1（与 C1 测试一致）。
_FOUR_PLAYER_SEED = 2


class _LastSurvivorOutcomePolicy(OutcomePolicy):
    """C2 测试脚手架：>1 存活返回 None（对局继续），恰好 1 存活判胜者。

    只作为生产 OutcomePolicy 接口的测试消费者，不是正式模式规则。
    """

    def __init__(self) -> None:
        object.__setattr__(self, "policy_id", "c2_test_last_survivor_scaffold")

    def resolve_winner_after_death(
        self, topology: PlayerTopology, dying_id: str
    ) -> str | None:
        alive = topology.alive_ids
        if len(alive) == 1:
            winner = alive[0]
            if winner == dying_id:
                raise UnsupportedRuleError("已死亡角色不能成为胜者")
            return winner
        return None


# ----------------------------------------------------------------------
# 测试辅助
# ----------------------------------------------------------------------


def _fresh_four(*, hp: int = 4) -> ProductionBasicCardBatch:
    game = ProductionBasicCardBatch(
        seed=_FOUR_PLAYER_SEED,
        player_hp=(hp, hp, hp, hp),
        player_max_hp=(hp, hp, hp, hp),
    )
    assert game.first_player_id == "p1"
    return game


def _proceed(game: ProductionBasicCardBatch, operation: str) -> None:
    action = next(
        a
        for a in game.legal_actions()
        if a.payload.get("operation") == operation
    )
    game.step(BatchActionIdController(action.action_id))


def _step(game: ProductionBasicCardBatch, action: object) -> None:
    assert action is not None and getattr(action, "action_id", None), action
    game.step(BatchActionIdController(action.action_id))  # type: ignore[attr-defined]


def _action(
    game: ProductionBasicCardBatch,
    operation: str,
    *,
    card_key: str | None = None,
    target: str | None = None,
    targets: tuple[str, ...] | None = None,
) -> LegalAction | None:
    for action in game.legal_actions():
        if action.payload.get("operation") != operation:
            continue
        if card_key is not None and action.payload.get("card_key") != card_key:
            continue
        if target is not None and (
            not action.target_ids or action.target_ids[0] != target
        ):
            continue
        if targets is not None and action.target_ids != targets:
            continue
        return action
    return None


def _enter_play(game: ProductionBasicCardBatch) -> None:
    for operation in ("proceed_prepare", "proceed_judgment", "proceed_draw"):
        _proceed(game, operation)
    assert game.phase is ProductionPhase.PLAY


def _equip(game: ProductionBasicCardBatch, player_id: str, card_key: str) -> str:
    records = game.formal_registry.instances_of(card_key)
    instance_id = next(
        (
            record.instance_id
            for record in records
            if game.state.location_of(record.instance_id).kind.value == "draw"
        ),
        records[0].instance_id,
    )
    game._state = game.state.move_card(
        instance_id, ZoneRef.equipment(player_id, "weapon")
    )
    return instance_id


def _empty_hand(game: ProductionBasicCardBatch, player_id: str) -> None:
    for instance_id in list(game.state.card_ids_in(ZoneRef.hand(player_id))):
        game._state = game.state.move_card(instance_id, DISCARD_PILE)


def _put_hand(game: ProductionBasicCardBatch, card_key: str, player_id: str = "p1") -> str:
    records = game.formal_registry.instances_of(card_key)
    instance_id = next(
        (
            record.instance_id
            for record in records
            if game.state.location_of(record.instance_id).kind.value == "draw"
        ),
        records[0].instance_id,
    )
    game._state = game.state.move_card(instance_id, ZoneRef.hand(player_id))
    return instance_id


def _fangtian_four_player_fixture() -> tuple[ProductionBasicCardBatch, str]:
    """p1 装备方天、手牌恰为一张普通杀（4p、全员4血、p1出牌阶段）。"""
    game = _fresh_four()
    _enter_play(game)
    _equip(game, "p1", FANGTIAN)
    _empty_hand(game, "p1")
    slash_id = _put_hand(game, SHA)
    assert equipped_weapon_key(game.state, "p1") == FANGTIAN
    return game, slash_id


def _damage_events_of(
    game: ProductionBasicCardBatch, target_id: str
) -> list[object]:
    return [
        event
        for event in game.events
        if event.event_type is EventType.DAMAGE
        and event.target_ids == (target_id,)
    ]


# ----------------------------------------------------------------------
# A. 方天画戟：合法多人附加目标
# ----------------------------------------------------------------------


def test_fangtian_four_player_enumerates_2_and_3_target_combos() -> None:
    game, slash_id = _fangtian_four_player_fixture()
    multi = [
        action
        for action in game.legal_actions()
        if action.payload.get("operation") == "use_slash"
        and action.payload.get("fangtian_multi_target") is True
    ]
    assert len(multi) == 4  # C(3,2)=3 双目标组合 + C(3,3)=1 三目标组合
    target_sets = {action.target_ids for action in multi}
    assert target_sets == {
        ("p2", "p3"),
        ("p2", "p4"),
        ("p3", "p4"),
        ("p2", "p3", "p4"),
    }
    assert all(action.card_instance_id == slash_id for action in multi)
    # 单目标杀仍与多目标并列存在（"可令"=可选）
    single = [
        action
        for action in game.legal_actions()
        if action.payload.get("operation") == "use_slash"
        and action.payload.get("fangtian_multi_target") is not True
    ]
    assert {action.target_ids for action in single} == {("p2",), ("p3",), ("p4",)}


def test_fangtian_three_player_enumerates_two_target_combo_only() -> None:
    game = ProductionBasicCardBatch(
        seed=_FOUR_PLAYER_SEED,
        player_hp=(4, 4, 4),
        player_max_hp=(4, 4, 4),
    )
    assert game.first_player_id == "p1"
    _enter_play(game)
    _equip(game, "p1", FANGTIAN)
    _empty_hand(game, "p1")
    _put_hand(game, SHA)
    multi = [
        action
        for action in game.legal_actions()
        if action.payload.get("operation") == "use_slash"
        and action.payload.get("fangtian_multi_target") is True
    ]
    assert {action.target_ids for action in multi} == {("p2", "p3")}


def test_fangtian_two_player_no_multi_target() -> None:
    game = ProductionBasicCardBatch(seed=1)
    _enter_play(game)
    _equip(game, "p1", FANGTIAN)
    _empty_hand(game, "p1")
    _put_hand(game, SHA)
    multi = [
        action
        for action in game.legal_actions()
        if action.payload.get("fangtian_multi_target") is True
    ]
    assert multi == []


def test_fangtian_multi_target_resolves_per_target_in_snapshot_order() -> None:
    game, _slash_id = _fangtian_four_player_fixture()
    action = _action(game, "use_slash", targets=("p2", "p4"))
    assert action is not None
    _step(game, action)
    # 使用事件携带完整目标快照
    used = next(
        event
        for event in game.events
        if event.event_type is EventType.CARD_USED
        and event.card_key == SHA
    )
    assert used.target_ids == ("p2", "p4")
    assert game.phase is ProductionPhase.SLASH_RESPONSE
    assert game.runtime.pending_slash is not None
    assert game.runtime.pending_slash.target_sequence == ("p2", "p4")
    assert game.runtime.pending_slash.current_target_index == 0
    # 目标1（p2）放弃响应 → 伤害 p2 → 推进到目标2（p4）
    _step(game, _action(game, "pass_slash_response"))
    assert game.phase is ProductionPhase.SLASH_RESPONSE
    assert game.runtime.pending_slash.target_id == "p4"
    assert game.runtime.pending_slash.current_target_index == 1
    assert _damage_events_of(game, "p2")
    assert game.state.players_by_id["p2"].hp == 3
    # 目标2（p4）放弃响应 → 伤害 p4 → 根完成回到出牌阶段
    _step(game, _action(game, "pass_slash_response"))
    assert game.phase is ProductionPhase.PLAY
    assert game.runtime.pending_slash is None
    assert _damage_events_of(game, "p4")
    assert game.state.players_by_id["p4"].hp == 3
    # 根【杀】已进入弃牌堆，卡牌守恒
    assert len(game.state.cards) == 160
    assert game.state.location_of(_slash_id) == DISCARD_PILE


def test_fangtian_three_target_full_resolution() -> None:
    game, _slash_id = _fangtian_four_player_fixture()
    action = _action(game, "use_slash", targets=("p2", "p3", "p4"))
    assert action is not None
    _step(game, action)
    for expected in ("p2", "p3", "p4"):
        assert game.runtime.pending_slash.target_id == expected
        _step(game, _action(game, "pass_slash_response"))
    assert game.phase is ProductionPhase.PLAY
    assert all(
        game.state.players_by_id[pid].hp == 3 for pid in ("p2", "p3", "p4")
    )


def test_fangtian_target_dodge_does_not_block_next_target() -> None:
    """目标1出【闪】回避后仍继续结算目标2；逐目标独立。"""
    game, _slash_id = _fangtian_four_player_fixture()
    shan_id = _put_hand(game, SHAN, "p2")
    action = _action(game, "use_slash", targets=("p2", "p4"))
    assert action is not None
    _step(game, action)
    dodge = _action(game, "play_dodge")
    assert dodge is not None
    _step(game, dodge)
    assert game.phase is ProductionPhase.SLASH_RESPONSE
    assert game.runtime.pending_slash.target_id == "p4"
    assert not _damage_events_of(game, "p2")
    assert game.state.location_of(dodge.card_instance_id) == DISCARD_PILE
    _step(game, _action(game, "pass_slash_response"))
    assert game.phase is ProductionPhase.PLAY
    assert _damage_events_of(game, "p4")


# ----------------------------------------------------------------------
# B. 方天画戟：非法/伪造目标
# ----------------------------------------------------------------------


def test_fangtian_forged_multi_target_rejected() -> None:
    game, slash_id = _fangtian_four_player_fixture()
    # 伪造：不带方天正式负载的多目标动作
    forged = LegalAction(
        action_type=ActionType.USE_CARD,
        actor_id="p1",
        card_instance_id=slash_id,
        target_ids=("p2", "p3"),
        payload={"operation": "use_slash", "card_key": SHA, "card_name": "杀"},
        action_id="act_forged_fangtian",
    )
    with pytest.raises(InvalidActionError):
        validate_action(game.state, game._context(), forged, game.registry)
    # 伪造：4个目标（超过至多3个；重复目标在 LegalAction 构造层即被拒）
    forged4 = LegalAction(
        action_type=ActionType.USE_CARD,
        actor_id="p1",
        card_instance_id=slash_id,
        target_ids=("p2", "p3", "p4", "p1"),
        payload={
            "operation": "use_slash",
            "card_key": SHA,
            "card_name": "杀",
            "fangtian_multi_target": True,
        },
        action_id="act_forged_fangtian_4",
    )
    with pytest.raises(InvalidActionError):
        validate_action(game.state, game._context(), forged4, game.registry)
    # 伪造：负载夹带额外目标字段
    forged_extra = LegalAction(
        action_type=ActionType.USE_CARD,
        actor_id="p1",
        card_instance_id=slash_id,
        target_ids=("p2", "p3"),
        payload={
            "operation": "use_slash",
            "card_key": SHA,
            "card_name": "杀",
            "fangtian_multi_target": True,
            "extra_targets": ["p4"],
        },
        action_id="act_forged_fangtian_extra",
    )
    with pytest.raises(InvalidActionError):
        validate_action(
            game.state, game._context(), forged_extra, game.registry
        )


def test_fangtian_requires_last_hand_card() -> None:
    game, _slash_id = _fangtian_four_player_fixture()
    _put_hand(game, SHAN)  # 手牌不再是唯一杀
    multi = [
        action
        for action in game.legal_actions()
        if action.payload.get("fangtian_multi_target") is True
    ]
    assert multi == []
    # 伪造多目标动作在 apply 层被拒（手牌非最后一张）
    forged = LegalAction(
        action_type=ActionType.USE_CARD,
        actor_id="p1",
        card_instance_id=_slash_id,
        target_ids=("p2", "p3"),
        payload={
            "operation": "use_slash",
            "card_key": SHA,
            "card_name": "杀",
            "fangtian_multi_target": True,
        },
        action_id="act_forged_last_hand",
    )
    with pytest.raises(InvalidActionError):
        validate_action(game.state, game._context(), forged, game.registry)


def test_fangtian_requires_fangtian_weapon() -> None:
    game = _fresh_four()
    _enter_play(game)
    _empty_hand(game, "p1")
    slash_id = _put_hand(game, SHA)
    forged = LegalAction(
        action_type=ActionType.USE_CARD,
        actor_id="p1",
        card_instance_id=slash_id,
        target_ids=("p2", "p3"),
        payload={
            "operation": "use_slash",
            "card_key": SHA,
            "card_name": "杀",
            "fangtian_multi_target": True,
        },
        action_id="act_forged_no_weapon",
    )
    with pytest.raises(InvalidActionError):
        validate_action(game.state, game._context(), forged, game.registry)


def test_fangtian_wine_buff_multi_target_blocked_by_rule_source() -> None:
    game = _fresh_four()
    _enter_play(game)
    _equip(game, "p1", FANGTIAN)
    _empty_hand(game, "p1")
    _put_hand(game, JIU)
    _put_hand(game, SHA)
    # 出牌阶段使用酒（强化下一张杀）
    wine_action = _action(game, "use_wine_buff", card_key=JIU)
    assert wine_action is not None
    _step(game, wine_action)
    assert game.runtime.wine_buff_owner_id == "p1"
    # 手牌只剩杀（最后一张手牌）但酒强化生效：多目标组合不枚举
    multi = [
        action
        for action in game.legal_actions()
        if action.payload.get("fangtian_multi_target") is True
    ]
    assert multi == []
    # 单目标酒杀仍可枚举（酒+方天单目标=普通酒杀语义，规则源覆盖）
    assert _action(game, "use_slash", target="p2") is not None


def test_fangtian_stale_multi_target_action_fails_closed() -> None:
    game, _slash_id = _fangtian_four_player_fixture()
    action = _action(game, "use_slash", targets=("p2", "p3"))
    assert action is not None
    # 枚举后状态变化（杀离开手牌）→ 旧 action_id 失败关闭
    game._state = game.state.move_card(action.card_instance_id, DISCARD_PILE)
    with pytest.raises(ProductionBatchError):
        game.step(BatchActionIdController(action.action_id))  # type: ignore[arg-type]


# ----------------------------------------------------------------------
# C. 方天画戟：死亡继续与模式胜负边界
# ----------------------------------------------------------------------


def test_fangtian_target_death_continues_with_policy() -> None:
    """目标1死亡（政策返回 None）→ 推进到目标2；政策只在最后一人时判胜。"""
    game = ProductionBasicCardBatch(
        seed=_FOUR_PLAYER_SEED,
        player_hp=(4, 4, 4, 4),
        player_max_hp=(4, 4, 4, 4),
        outcome_policy=_LastSurvivorOutcomePolicy(),
    )
    _enter_play(game)
    _equip(game, "p1", FANGTIAN)
    _empty_hand(game, "p1")
    _put_hand(game, SHA)
    # 目标 p2 只剩1血且全员无桃（无法救援）
    game._state = _replace_player(game.state, "p2", hp=1)
    for player_id in game.player_ids:
        for instance_id in list(game.state.card_ids_in(ZoneRef.hand(player_id))):
            if game.state.cards_by_id[instance_id].card_key in (TAO, JIU):
                game._state = game.state.move_card(instance_id, DISCARD_PILE)
    action = _action(game, "use_slash", targets=("p2", "p3"))
    assert action is not None
    _step(game, action)
    _step(game, _action(game, "pass_slash_response"))
    # 进入濒死救援（4名角色依次放弃）
    assert game.phase is ProductionPhase.DYING_RESCUE
    for _ in range(3):
        _step(game, _action(game, "pass_rescue"))
    # 第4名救援者放弃 → p2 死亡 → 政策返回 None → 推进到 p3
    _step(game, _action(game, "pass_rescue"))
    assert game.phase is ProductionPhase.SLASH_RESPONSE
    assert game.runtime.pending_slash is not None
    assert game.runtime.pending_slash.target_id == "p3"
    assert game.state.players_by_id["p2"].alive is False
    assert game.state.players_by_id["p2"].seat == 2  # 座位保留
    assert not game.is_finished
    # 继续结算 p3
    _step(game, _action(game, "pass_slash_response"))
    assert game.phase is ProductionPhase.PLAY
    assert game.state.players_by_id["p3"].hp == 3


def test_fangtian_no_policy_death_fails_closed() -> None:
    """无政策 4p 方天目标死亡 → 非终局死亡继续路径由政策缺失失败关闭。"""
    game, _slash_id = _fangtian_four_player_fixture()
    game._state = _replace_player(game.state, "p2", hp=1)
    action = _action(game, "use_slash", targets=("p2", "p3"))
    assert action is not None
    _step(game, action)
    _step(game, _action(game, "pass_slash_response"))
    assert game.phase is ProductionPhase.DYING_RESCUE
    # 无政策且 N>2：胜负判定失败关闭（不猜测最后一人生存规则）
    for _ in range(3):
        _step(game, _action(game, "pass_rescue"))
    with pytest.raises(UnsupportedRuleError, match="胜负策略"):
        _step(game, _action(game, "pass_rescue"))
    assert game.is_finished is False


# ----------------------------------------------------------------------
# D. 群体普通锦囊 4p 生产语义（南蛮/万箭/桃园）
# ----------------------------------------------------------------------

NANMAN = "sgs_trick_nanmanruqin"
WANJIAN = "sgs_trick_wanjianqifa"
TAOYUAN = "sgs_trick_taoyuanjieyi"
WUGU = "sgs_trick_wugufengdeng"


def _four_player_p2_play_with_trick(trick_key: str):
    """p2 出牌阶段、手牌加入指定群体锦囊（4p、全员8血免弃牌）。"""
    game = _fresh_four(hp=8)
    _enter_play(game)
    _proceed(game, "end_play_phase")
    _proceed(game, "end_turn")
    assert game.current_player_id == "p2"
    _enter_play(game)
    _put_hand(game, trick_key, "p2")
    return game


def _close_four_player_wuxie_window(game: ProductionBasicCardBatch) -> None:
    """关闭当前无懈窗口：按实际存活 responder 数依次放弃（死亡后可能少于4名）。"""
    while True:
        action = _action(game, "pass_trick_response")
        if action is None:
            return
        _step(game, action)


def _put_draw_at(game: ProductionBasicCardBatch, instance_id: str, position: int) -> None:
    """把实体牌放到牌堆指定位置（0-based），其余相对顺序保持不变。"""
    if game.state.location_of(instance_id) != DRAW_PILE:
        game._state = game.state.move_card(instance_id, DRAW_PILE)
    pile = list(game.state.card_ids_in(DRAW_PILE))
    pile.remove(instance_id)
    pile.insert(position, instance_id)
    game._state = game.state.reorder_zone(DRAW_PILE, tuple(pile))


def test_nanman_four_player_full_resolution() -> None:
    game = _four_player_p2_play_with_trick(NANMAN)
    trick_id = next(
        instance_id
        for instance_id in game.state.card_ids_in(ZoneRef.hand("p2"))
        if game.state.cards_by_id[instance_id].card_key == NANMAN
    )
    action = _action(game, "use_nanman", card_key=NANMAN)
    assert action is not None and action.target_ids == ()
    _step(game, action)
    group = game.runtime.pending_group_trick
    assert group is not None
    assert group.target_sequence == ("p3", "p4", "p1")
    # 每个目标独立无懈窗口（4名角色依次放弃）→ 逐目标南蛮响应 → 各受1点伤害
    assert game.phase is ProductionPhase.TRICK_RESPONSE
    for expected in ("p3", "p4", "p1"):
        _close_four_player_wuxie_window(game)
        assert game.phase is ProductionPhase.NANMAN_RESPONSE
        _step(game, _action(game, "pass_nanman_slash"))
    assert game.phase is ProductionPhase.PLAY
    assert all(
        game.state.players_by_id[pid].hp == 7 for pid in ("p3", "p4", "p1")
    )
    assert game.state.players_by_id["p2"].hp == 8  # 使用者不受影响
    # 原锦囊直到全部目标完成才 finalize
    assert game.state.location_of(trick_id) == DISCARD_PILE
    assert len(game.state.cards) == 160


def test_wanjian_four_player_full_resolution() -> None:
    game = _four_player_p2_play_with_trick(WANJIAN)
    action = _action(game, "use_wanjian", card_key=WANJIAN)
    assert action is not None
    _step(game, action)
    assert game.runtime.pending_group_trick.target_sequence == (
        "p3",
        "p4",
        "p1",
    )
    for expected in ("p3", "p4", "p1"):
        _close_four_player_wuxie_window(game)
        assert game.phase is ProductionPhase.WANJIAN_RESPONSE
        _step(game, _action(game, "pass_wanjian_jink"))
    assert game.phase is ProductionPhase.PLAY
    assert all(
        game.state.players_by_id[pid].hp == 7 for pid in ("p3", "p4", "p1")
    )


def test_taoyuan_four_player_wounded_order_and_recovery() -> None:
    game = _four_player_p2_play_with_trick(TAOYUAN)
    # 受伤：使用者 p2（3/8）、p3（2/8）；p4、p1 满血不是目标
    game._state = _replace_player(game.state, "p2", hp=3)
    game._state = _replace_player(game.state, "p3", hp=2)
    action = _action(game, "use_taoyuan", card_key=TAOYUAN)
    assert action is not None
    _step(game, action)
    # 目标快照：从使用者 p2 的座次环（p2,p3,p4,p1）过滤受伤（含使用者）
    group = game.runtime.pending_group_trick
    assert group is not None
    assert group.target_sequence == ("p2", "p3")
    _close_four_player_wuxie_window(game)
    _close_four_player_wuxie_window(game)
    assert game.phase is ProductionPhase.PLAY
    assert game.state.players_by_id["p2"].hp == 4
    assert game.state.players_by_id["p3"].hp == 3
    assert game.state.players_by_id["p1"].hp == 8
    assert game.state.players_by_id["p4"].hp == 8


def test_wugu_four_player_full_resolution() -> None:
    """4p 五谷丰登：展示数量=存活目标数、含使用者、逐目标独立无懈+选牌。"""
    from scripts.sgs_engine.model import REVEALED_ZONE

    game = _four_player_p2_play_with_trick(WUGU)
    action = _action(game, "use_wugu", card_key=WUGU)
    assert action is not None
    _step(game, action)
    group = game.runtime.pending_group_trick
    assert group is not None
    assert group.target_sequence == ("p2", "p3", "p4", "p1")  # 含使用者
    # 展示池 = 目标数 4 张（公开）
    assert len(game.state.card_ids_in(REVEALED_ZONE)) == 4
    hands_before = {
        pid: len(game.state.card_ids_in(ZoneRef.hand(pid)))
        for pid in game.player_ids
    }
    for expected in ("p2", "p3", "p4", "p1"):
        _close_four_player_wuxie_window(game)
        assert game.phase is ProductionPhase.WUGU_PICK
        assert game.current_actor_id == expected
        picks = [
            a
            for a in game.legal_actions()
            if a.payload.get("operation") == "pick_wugu_card"
        ]
        assert picks
        _step(game, picks[0])
    assert game.phase is ProductionPhase.PLAY
    assert not game.state.card_ids_in(REVEALED_ZONE)  # 展示池清空
    for pid in game.player_ids:
        assert (
            len(game.state.card_ids_in(ZoneRef.hand(pid)))
            == hands_before[pid] + 1
        )


def test_group_trick_target_death_continues_in_four_player() -> None:
    """4p 南蛮目标死亡（政策返回 None）→ 继续后续目标队列。"""
    game = ProductionBasicCardBatch(
        seed=_FOUR_PLAYER_SEED,
        player_hp=(8, 8, 8, 8),
        player_max_hp=(8, 8, 8, 8),
        outcome_policy=_LastSurvivorOutcomePolicy(),
    )
    _enter_play(game)
    _proceed(game, "end_play_phase")
    _proceed(game, "end_turn")
    _enter_play(game)
    _put_hand(game, NANMAN, "p2")
    game._state = _replace_player(game.state, "p3", hp=1)
    # 全员无桃
    for player_id in game.player_ids:
        for instance_id in list(game.state.card_ids_in(ZoneRef.hand(player_id))):
            if game.state.cards_by_id[instance_id].card_key in (TAO, JIU):
                game._state = game.state.move_card(instance_id, DISCARD_PILE)
    action = _action(game, "use_nanman", card_key=NANMAN)
    assert action is not None
    _step(game, action)
    _close_four_player_wuxie_window(game)
    # p3 放弃出杀 → 伤害 → 濒死 → 4名救援者放弃 → 死亡 → 继续 p4
    _step(game, _action(game, "pass_nanman_slash"))
    assert game.phase is ProductionPhase.DYING_RESCUE
    for _ in range(3):
        _step(game, _action(game, "pass_rescue"))
    _step(game, _action(game, "pass_rescue"))
    assert game.state.players_by_id["p3"].alive is False
    assert game.state.players_by_id["p3"].seat == 3
    assert not game.is_finished
    # 死亡继续：进入 p4 的独立无懈窗口
    assert game.phase is ProductionPhase.TRICK_RESPONSE
    _close_four_player_wuxie_window(game)
    assert game.phase is ProductionPhase.NANMAN_RESPONSE
    _step(game, _action(game, "pass_nanman_slash"))  # p4 受伤
    _close_four_player_wuxie_window(game)  # p1 的独立无懈窗口
    assert game.phase is ProductionPhase.NANMAN_RESPONSE
    _step(game, _action(game, "pass_nanman_slash"))  # p1 受伤
    assert game.phase is ProductionPhase.PLAY
    assert game.state.players_by_id["p4"].hp == 7
    assert game.state.players_by_id["p1"].hp == 7


# ----------------------------------------------------------------------
# E. 多人无懈可击链（三名以上 responder）
# ----------------------------------------------------------------------

WUXIE = "sgs_trick_wuxiekeji"


def test_four_player_wuxie_chain_three_responders() -> None:
    """3 名不同 responder 的连续无懈链：A无懈→B反无懈→C再反无懈。"""
    game = _four_player_p2_play_with_trick(NANMAN)
    # 把前3张无懈实体分别放入 p4/p1/p2 手牌（确定性fixture，ID互不重复）
    wuxie_ids = [
        record.instance_id
        for record in game.formal_registry.instances_of(WUXIE)
    ]
    assert len(wuxie_ids) >= 3
    for instance_id, player_id in zip(wuxie_ids[:3], ("p4", "p1", "p2")):
        game._state = game.state.move_card(instance_id, ZoneRef.hand(player_id))
    action = _action(game, "use_nanman", card_key=NANMAN)
    assert action is not None
    _step(game, action)
    # 目标 p3 的无懈窗口（顺序 p2,p3,p4,p1）：
    # p2 放弃、p3 放弃、p4 使用无懈（A，抵消 p3 的效果）
    _step(game, _action(game, "pass_trick_response"))
    _step(game, _action(game, "pass_trick_response"))
    assert game.runtime.pending_trick is not None
    _step(game, _action(game, "use_wuxie"))
    # 反无懈窗口从 A 的下一位（p1）继续：p1 使用无懈（B）
    _step(game, _action(game, "use_wuxie"))
    # 反无懈窗口继续（p2）：p2 使用无懈（C）
    _step(game, _action(game, "use_wuxie"))
    # 反无懈窗口在 C 之后需要整圈（p3、p4、p1、p2）全部放弃才闭合
    # → C 生效 → B 被抵消 → A 重新生效 → 南蛮对 p3 的效果被抵消
    for _ in range(4):
        _step(game, _action(game, "pass_trick_response"))
    # p3 效果被抵消：不进入 p3 的南蛮响应，直接进入 p4 的无懈窗口
    assert game.phase is ProductionPhase.TRICK_RESPONSE
    cancelled = [
        event
        for event in game.events
        if event.event_type is EventType.CARD_EFFECT_CANCELLED
    ]
    assert cancelled
    _close_four_player_wuxie_window(game)  # p4 的独立无懈窗口
    assert game.phase is ProductionPhase.NANMAN_RESPONSE
    group = game.runtime.pending_group_trick
    assert group is not None
    assert group.target_sequence[group.current_target_index] == "p4"
    # 后续目标正常结算（p4 → p1 各自独立窗口）
    _step(game, _action(game, "pass_nanman_slash"))
    _close_four_player_wuxie_window(game)
    _step(game, _action(game, "pass_nanman_slash"))
    assert game.phase is ProductionPhase.PLAY
    assert game.state.players_by_id["p3"].hp == 8  # 效果被抵消，未受伤
    assert game.state.players_by_id["p4"].hp == 7
    assert game.state.players_by_id["p1"].hp == 7


# ----------------------------------------------------------------------
# F. 借刀杀人多人候选
# ----------------------------------------------------------------------

JIEDAO = "sgs_trick_jiedaosharen"


def test_borrowed_sword_four_player_multiple_first_target_candidates() -> None:
    game = _fresh_four()
    _enter_play(game)
    _put_hand(game, JIEDAO)
    # p3、p4 各装备一把武器（成为合法第一目标候选）
    _equip(game, "p3", "sgs_weapon_qinggangjian")
    _equip(game, "p4", "sgs_weapon_zhugeliannu")
    actions = [
        action
        for action in game.legal_actions()
        if action.payload.get("operation") == "use_jiedao"
    ]
    first_targets = {action.target_ids[0] for action in actions}
    assert first_targets == {"p3", "p4"}
    # p2 没有武器 → 不是第一目标候选
    assert all(action.target_ids[0] != "p2" for action in actions)
    # 每个第一目标对应多个潜在第二目标（在攻击范围内的其他角色）
    second_targets = {
        (action.target_ids[0], action.payload.get("second_target_id"))
        for action in actions
    }
    # 第二目标由权威枚举确定：不含第一目标自身
    for first_target, second_target in second_targets:
        assert second_target != first_target
        assert second_target is not None
    assert len(second_targets) >= 4  # 两个第一目标 × 多个第二目标


def test_borrowed_sword_four_player_forged_second_target_rejected() -> None:
    game = _fresh_four()
    _enter_play(game)
    trick_id = _put_hand(game, JIEDAO)
    # 第一目标 p3 装备诸葛连弩（攻击范围1）：p2/p4 距离1 是合法第二目标，
    # p1 距离2 不在范围内 → 伪造第二目标 p1 必须被拒。
    _equip(game, "p3", "sgs_weapon_zhugeliannu")
    real = next(
        action
        for action in game.legal_actions()
        if action.payload.get("operation") == "use_jiedao"
        and action.target_ids[0] == "p3"
    )
    assert real.payload.get("second_target_id") in {"p2", "p4"}
    forged = LegalAction(
        action_type=ActionType.USE_CARD,
        actor_id="p1",
        card_instance_id=trick_id,
        target_ids=("p3",),
        payload={
            "operation": "use_jiedao",
            "card_key": JIEDAO,
            "card_name": "借刀杀人",
            "first_target_id": "p3",
            "second_target_id": "p1",
        },
        action_id="act_forged_jiedao_second",
    )
    with pytest.raises(InvalidActionError):
        validate_action(game.state, game._context(), forged, game.registry)


def test_borrowed_sword_four_player_refusal_transfers_weapon() -> None:
    game = _fresh_four()
    _enter_play(game)
    _put_hand(game, JIEDAO)
    weapon_id = _equip(game, "p3", "sgs_weapon_qinggangjian")
    action = _action(game, "use_jiedao", card_key=JIEDAO)
    assert action is not None
    _step(game, action)
    _close_four_player_wuxie_window(game)
    _step(game, _action(game, "refuse_borrowed_sword_slash"))
    # 拒绝后武器被使用者获得（进入 p1 手牌区，规则源：借刀杀人"获得其武器牌"）
    assert game.state.location_of(weapon_id) == ZoneRef.hand("p1")
    assert game.phase is ProductionPhase.PLAY


# ----------------------------------------------------------------------
# G. 延时锦囊 / 闪电 4p
# ----------------------------------------------------------------------

LEBUSI = "sgs_delayed_lebusi"
BINGLIANG = "sgs_delayed_bingliang"
SHANDIAN = "sgs_delayed_shandian"
HEART_TAO = "sgs-mobile-20260725-098"  # ♥6 桃（判定牌：红桃→乐/兵粮不命中、闪电必转移）
SPADE_7_SHA = "sgs-mobile-20260725-140"  # ♠7 杀（黑桃2-9 → 闪电命中）


def _use_delayed_4p(
    game: ProductionBasicCardBatch, operation: str, key: str, target: str
) -> None:
    action = _action(game, operation, card_key=key, target=target)
    assert action is not None, f"出牌阶段必须能枚举{operation}"
    _step(game, action)


def _complete_turn_8(game: ProductionBasicCardBatch) -> None:
    """8血免弃牌：完整走完当前角色回合。"""
    if game.phase is ProductionPhase.PREPARE:
        _enter_play(game)
    _proceed(game, "end_play_phase")
    _proceed(game, "end_turn")


def test_shandian_four_player_transfers_to_next_alive_on_miss() -> None:
    game = _fresh_four(hp=8)
    _enter_play(game)
    _put_hand(game, SHANDIAN)
    _use_delayed_4p(game, "use_shandian", SHANDIAN, "p1")
    assert game.state.card_ids_in(ZoneRef.judgment("p1"))
    for _ in range(4):
        _complete_turn_8(game)
    assert game.current_player_id == "p1"
    _proceed(game, "proceed_prepare")
    _proceed(game, "proceed_judgment")
    assert game.phase is ProductionPhase.JUDGMENT_WUXIE
    for _ in range(4):
        _step(game, _action(game, "pass_judgment_wuxie"))
    # 判定牌：♥6 桃（非黑桃2-9）→ 未命中 → 闪电转移到下家 p2
    _put_draw_at(game, HEART_TAO, 0)
    _proceed(game, "proceed_judgment")
    assert game.state.card_ids_in(ZoneRef.judgment("p2"))
    assert not game.state.card_ids_in(ZoneRef.judgment("p1"))


def test_shandian_four_player_transfer_skips_dead_and_wraps() -> None:
    game = _fresh_four(hp=8)
    _enter_play(game)
    _put_hand(game, SHANDIAN)
    _use_delayed_4p(game, "use_shandian", SHANDIAN, "p1")
    assert game.state.card_ids_in(ZoneRef.judgment("p1"))
    # p4 已死亡：转移跳过 p4（座次4保留），环回到 p2
    game._state = _replace_player(game.state, "p4", hp=0, alive=False)
    for _ in range(3):
        _complete_turn_8(game)  # p1→p2→p3→p1（回合继任跳过死亡 p4）
    assert game.current_player_id == "p1"
    _proceed(game, "proceed_prepare")
    _proceed(game, "proceed_judgment")
    assert game.phase is ProductionPhase.JUDGMENT_WUXIE
    while _action(game, "pass_judgment_wuxie") is not None:
        _step(game, _action(game, "pass_judgment_wuxie"))
    _put_draw_at(game, HEART_TAO, 0)
    _proceed(game, "proceed_judgment")
    assert game.state.card_ids_in(ZoneRef.judgment("p2"))
    assert not game.state.card_ids_in(ZoneRef.judgment("p1"))


def test_lebusi_and_bingliang_four_player_independent_judgment_zones() -> None:
    game = _fresh_four(hp=8)
    _enter_play(game)
    _put_hand(game, LEBUSI)
    _put_hand(game, BINGLIANG)
    _use_delayed_4p(game, "use_lebusi", LEBUSI, "p3")
    _use_delayed_4p(game, "use_bingliang", BINGLIANG, "p4")
    assert game.state.card_ids_in(ZoneRef.judgment("p3"))
    assert game.state.card_ids_in(ZoneRef.judgment("p4"))
    _complete_turn_8(game)  # p2 回合
    _complete_turn_8(game)  # p3 回合：判定 p3 的乐不思蜀
    _proceed(game, "proceed_prepare")
    _proceed(game, "proceed_judgment")
    assert game.phase is ProductionPhase.JUDGMENT_WUXIE
    for _ in range(4):
        _step(game, _action(game, "pass_judgment_wuxie"))
    _put_draw_at(game, HEART_TAO, 0)  # 红桃：乐不命中
    _proceed(game, "proceed_judgment")
    assert not game.state.card_ids_in(ZoneRef.judgment("p3"))
    assert game.state.card_ids_in(ZoneRef.judgment("p4"))  # p4 判定区独立保留


# ----------------------------------------------------------------------
# H. 多人距离/坐骑/防具逐目标隔离
# ----------------------------------------------------------------------


def test_four_player_seat_distance_and_offensive_horse_slash_legality() -> None:
    game = _fresh_four()
    _enter_play(game)
    assert PlayerTopology.from_state(game.state).base_seat_distance("p1", "p3") == 2
    # 无武器攻击范围1：p3（距离2）不是合法杀目标
    _put_hand(game, SHA)
    assert _action(game, "use_slash", target="p2") is not None
    assert _action(game, "use_slash", target="p3") is None
    # 装备进攻坐骑（距离-1）：p3 距离1 → 合法
    game._state = game.state.move_card(
        next(
            record.instance_id
            for record in game.formal_registry.instances_of("sgs_mount_offensive")
        ),
        ZoneRef.equipment("p1", "attack_horse"),
    )
    assert _action(game, "use_slash", target="p3") is not None


def test_fangtian_armor_isolation_per_target() -> None:
    """p2 藤甲使普通杀无效、p3 无防具正常受伤——逐目标独立、不泄漏。"""
    game, _slash_id = _fangtian_four_player_fixture()
    game._state = game.state.move_card(
        next(
            record.instance_id
            for record in game.formal_registry.instances_of("sgs_armor_tengjia")
        ),
        ZoneRef.equipment("p2", "armor"),
    )
    action = _action(game, "use_slash", targets=("p2", "p3"))
    assert action is not None
    _step(game, action)
    # p2 被藤甲无效：不开闪响应窗口，直接进入 p3 的响应
    assert game.phase is ProductionPhase.SLASH_RESPONSE
    assert game.runtime.pending_slash.target_id == "p3"
    cancelled = [
        event
        for event in game.events
        if event.event_type is EventType.CARD_EFFECT_CANCELLED
        and event.target_ids == ("p2",)
    ]
    assert cancelled and cancelled[0].payload.get("invalidated_by_armor") is True
    _step(game, _action(game, "pass_slash_response"))
    assert game.phase is ProductionPhase.PLAY
    assert game.state.players_by_id["p2"].hp == 4  # 无效：未受伤
    assert game.state.players_by_id["p3"].hp == 3  # 正常受伤
    assert not _damage_events_of(game, "p2")


# ----------------------------------------------------------------------
# I. replay：player_ids / seat / finish_reason 一等输入
# ----------------------------------------------------------------------


class _FirstBloodCustomFinishPolicy(OutcomePolicy):
    """首杀即终局、自定义终局原因的策略脚手架（测试 replay 终局泛化）。"""

    def __init__(self) -> None:
        object.__setattr__(self, "policy_id", "c2_test_first_blood_custom")

    def resolve_winner_after_death(
        self, topology: PlayerTopology, dying_id: str
    ) -> str:
        alive = topology.alive_ids
        for candidate in alive:
            if candidate != dying_id:
                return candidate
        raise UnsupportedRuleError("first blood 脚手架找不到非死亡存活角色")

    @property
    def finish_reason(self) -> str:
        return "c2_scaffold_first_blood_eliminated"


def _first_blood_fixture_4p(game: ProductionBasicCardBatch) -> None:
    """首杀夹具（ID 无关）：首名玩家持杀，第二玩家无闪，全员无桃酒。"""
    user = game.player_ids[0]
    victim = game.player_ids[1]
    for player_id in game.player_ids:
        for instance_id in list(game.state.card_ids_in(ZoneRef.hand(player_id))):
            key = game.state.cards_by_id[instance_id].card_key
            if key in (TAO, JIU) or (player_id == victim and key == SHAN):
                game._state = game.state.move_card(instance_id, DISCARD_PILE)
    slash_id = next(
        record.instance_id
        for record in game.formal_registry.instances_of(SHA)
        if game.state.location_of(record.instance_id).kind.value != "hand"
    )
    game._state = game.state.move_card(slash_id, ZoneRef.hand(user))


def test_replay_player_ids_roundtrip_with_custom_ids() -> None:
    from scripts.sgs_engine.production_replay import (
        ProductionReplayFormatError,
        record_reference_production_batch,
        reexecute_production_replay,
    )

    game = ProductionBasicCardBatch(
        seed=_FOUR_PLAYER_SEED,
        player_hp=(4, 1, 4, 4),
        player_max_hp=(4, 1, 4, 4),
        player_ids=("alpha", "beta", "gamma", "delta"),
        outcome_policy=_FirstBloodCustomFinishPolicy(),
    )
    record = record_reference_production_batch(
        seed=_FOUR_PLAYER_SEED,
        player_hp=(4, 1, 4, 4),
        player_max_hp=(4, 1, 4, 4),
        _game=game,
        fixture=_first_blood_fixture_4p,
    )
    config = record.header["initial_configuration"]
    assert tuple(config["player_ids"]) == ("alpha", "beta", "gamma", "delta")
    assert record.outcome["finish_reason"] == "c2_scaffold_first_blood_eliminated"
    assert record.outcome["winner_id"] == "alpha"
    result = reexecute_production_replay(
        record,
        fixture=_first_blood_fixture_4p,
        outcome_policy=_FirstBloodCustomFinishPolicy(),
    )
    assert result.verified is True
    assert result.winner_id == "alpha"
    # 篡改 player_ids → 重建身份不同 → 严格重执行失败关闭
    import copy

    tampered = copy.deepcopy(record.to_dict())
    tampered["header"]["initial_configuration"]["player_ids"] = [
        "alpha",
        "beta",
        "gamma",
        "forged",
    ]
    tampered["record_sha256"] = ""
    from scripts.sgs_engine.production_replay import (
        ProductionReexecutionReplay,
    )

    with pytest.raises(
        (ProductionReplayFormatError, Exception)
    ):
        reexecute_production_replay(
            ProductionReexecutionReplay.from_dict(tampered),
            fixture=_first_blood_fixture_4p,
            outcome_policy=_FirstBloodCustomFinishPolicy(),
        )


def test_replay_custom_finish_reason_verified_and_forged_rejected() -> None:
    from scripts.sgs_engine.production_replay import (
        ProductionReplayDivergenceError,
        ProductionReplayFormatError,
        record_reference_production_batch,
        reexecute_production_replay,
    )

    game = ProductionBasicCardBatch(
        seed=_FOUR_PLAYER_SEED,
        player_hp=(4, 1, 4, 4),
        player_max_hp=(4, 1, 4, 4),
        outcome_policy=_FirstBloodCustomFinishPolicy(),
    )
    record = record_reference_production_batch(
        seed=_FOUR_PLAYER_SEED,
        player_hp=(4, 1, 4, 4),
        player_max_hp=(4, 1, 4, 4),
        _game=game,
        fixture=_first_blood_fixture_4p,
    )
    # 合法 custom finish_reason 不再被 duel-only 常量拒绝
    assert record.outcome["finish_reason"] == "c2_scaffold_first_blood_eliminated"
    result = reexecute_production_replay(
        record,
        fixture=_first_blood_fixture_4p,
        outcome_policy=_FirstBloodCustomFinishPolicy(),
    )
    assert result.verified is True
    # 伪造 finish_reason：与策略产出值不一致 → 失败关闭
    import copy

    tampered = copy.deepcopy(record.to_dict())
    tampered["outcome"]["finish_reason"] = "forged_reason"
    tampered["record_sha256"] = ""
    from scripts.sgs_engine.production_replay import (
        ProductionReexecutionReplay,
    )

    with pytest.raises(
        (ProductionReplayFormatError, ProductionReplayDivergenceError)
    ):
        reexecute_production_replay(
            ProductionReexecutionReplay.from_dict(tampered),
            fixture=_first_blood_fixture_4p,
            outcome_policy=_FirstBloodCustomFinishPolicy(),
        )
    # 伪造/不匹配 policy identity：失败关闭（不提供策略或提供身份不同策略）
    with pytest.raises(ProductionReplayFormatError):
        reexecute_production_replay(
            record,
            fixture=_first_blood_fixture_4p,
            outcome_policy=_LastSurvivorOutcomePolicy(),
        )
    with pytest.raises(ProductionReplayFormatError):
        reexecute_production_replay(record, fixture=_first_blood_fixture_4p)


def test_replay_seat_order_roundtrip_with_custom_ids() -> None:
    from scripts.sgs_engine.production_replay import (
        record_reference_production_batch,
        reexecute_production_replay,
    )

    game = ProductionBasicCardBatch(
        seed=_FOUR_PLAYER_SEED,
        player_hp=(4, 1, 4, 4),
        player_max_hp=(4, 1, 4, 4),
        player_ids=("zeta", "alpha", "beta", "gamma"),
        outcome_policy=_FirstBloodCustomFinishPolicy(),
    )
    record = record_reference_production_batch(
        seed=_FOUR_PLAYER_SEED,
        player_hp=(4, 1, 4, 4),
        player_max_hp=(4, 1, 4, 4),
        _game=game,
        fixture=_first_blood_fixture_4p,
    )
    # 座次顺序按 player_ids 顺序（seat 1..N）权威重建
    assert tuple(record.header["initial_configuration"]["player_ids"]) == (
        "zeta",
        "alpha",
        "beta",
        "gamma",
    )
    result = reexecute_production_replay(
        record,
        fixture=_first_blood_fixture_4p,
        outcome_policy=_FirstBloodCustomFinishPolicy(),
    )
    assert result.verified is True
    assert result.winner_id == "zeta"


# ----------------------------------------------------------------------
# J. 4-observer visibility 审计（无新增泄漏）
# ----------------------------------------------------------------------


def test_four_observer_visibility_no_new_leaks() -> None:
    from scripts.sgs_engine.production_replay import (
        record_reference_production_batch,
    )

    game = ProductionBasicCardBatch(
        seed=_FOUR_PLAYER_SEED,
        player_hp=(4, 1, 4, 4),
        player_max_hp=(4, 1, 4, 4),
        outcome_policy=_FirstBloodCustomFinishPolicy(),
    )
    record = record_reference_production_batch(
        seed=_FOUR_PLAYER_SEED,
        player_hp=(4, 1, 4, 4),
        player_max_hp=(4, 1, 4, 4),
        _game=game,
        fixture=_first_blood_fixture_4p,
    )
    import json as json_module

    for viewer_id in (None, "p1", "p2", "p3", "p4"):
        view = record.player_visible_payload(
            viewer_id=viewer_id if viewer_id is None else viewer_id,
            valid_player_ids=("p1", "p2", "p3", "p4"),
        )
        encoded = json_module.dumps(view, ensure_ascii=False)
        # 任何视角不得泄漏会话秘密/权威私有材料/句柄HMAC
        assert "session_secret" not in encoded
        assert "authoritative_private" not in encoded
        assert "record_sha256" not in encoded
        assert "hmac" not in encoded.lower()
        assert "handle" not in encoded.lower()
    observer = record.player_visible_payload()
    assert observer["player_visible"] is True
    assert all(
        "chosen_action" not in decision for decision in observer["decisions"]
    )


# ----------------------------------------------------------------------
# K. 38 类卡牌 coverage matrix（机器可检查）
# ----------------------------------------------------------------------


def _all_38_card_keys() -> tuple[str, ...]:
    from scripts.sgs_engine.production_cards import (
        PRODUCTION_ARMOR_KEYS,
        PRODUCTION_BASIC_CARD_KEYS,
        PRODUCTION_DELAYED_TRICK_KEYS,
        PRODUCTION_MOUNT_KEYS,
        PRODUCTION_TRICK_KEYS,
        PRODUCTION_WEAPON_KEYS,
    )

    return (
        *PRODUCTION_BASIC_CARD_KEYS,
        *PRODUCTION_TRICK_KEYS,
        *PRODUCTION_DELAYED_TRICK_KEYS,
        *PRODUCTION_WEAPON_KEYS,
        *PRODUCTION_ARMOR_KEYS,
        *PRODUCTION_MOUNT_KEYS,
    )


def test_38_card_coverage_matrix_all_global_complete() -> None:
    """38 类正式卡牌：实现 + 规则源 + 状态逐项机器核验。"""
    from scripts.sgs_engine.production_cards import WEAPON_SKILL_STATUS

    keys = _all_38_card_keys()
    assert len(keys) == 38
    assert len(set(keys)) == 38
    game = ProductionBasicCardBatch(seed=1)
    registry = game.formal_registry
    knowledge_text = (
        (game._deck_path.parent / "三国杀卡牌效果.md").read_text(
            encoding="utf-8"
        )
        + (
            game._deck_path.parent / "三国杀基础术语与通用机制.md"
        ).read_text(encoding="utf-8")
    )
    for key in keys:
        # 1) production implementation：适配器已注册且 tested
        adapter = registry.adapter_for(key)
        assert adapter is not None, key
        assert adapter.implemented is True, key
        assert adapter.tested is True, key
        # 2) 规则源：Knowledge 卡牌效果/基础术语必须提及该卡牌名
        assert adapter.card_name in knowledge_text, key
        # 3) 状态：武器走 WEAPON_SKILL_STATUS（全部 COMPLETE），其余已实现
        if key in WEAPON_SKILL_STATUS:
            assert WEAPON_SKILL_STATUS[key] == "COMPLETE", key
    assert {
        key for key, status in WEAPON_SKILL_STATUS.items() if status == "PARTIAL"
    } == set()
    assert len(registry.implemented_card_keys) == 38
    assert not registry.unimplemented_card_keys
