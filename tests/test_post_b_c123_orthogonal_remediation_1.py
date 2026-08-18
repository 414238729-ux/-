# -*- coding: utf-8 -*-
"""POST-B C123 第二轮正交敌对审计 F-003～F-006 回归测试。

本文件先于 production 修复提交，用于证明旧基线真实失败，并在修复后
锁定最小路径。finding 状态不得写成 CLOSED / AUDIT_PASSED。

只走真实 Formal2v2Session / ProductionBasicCardBatch 生产路径。
"""

from __future__ import annotations

import dataclasses
from typing import Any

import pytest

from scripts.sgs_engine.actions import (
    LegalAction,
    UnsupportedRuleError,
)
from scripts.sgs_engine.events import EventType
from scripts.sgs_engine.mode_2v2 import (
    Formal2v2Configuration,
    Formal2v2Session,
)
from scripts.sgs_engine.model import DISCARD_PILE, DRAW_PILE, PROCESSING_ZONE, ZoneRef
from scripts.sgs_engine.multiplayer import PlayerTopology
from scripts.sgs_engine.production_batch import (
    BatchActionIdController,
    ProductionBasicCardBatch,
    ProductionBatchError,
    ProductionPhase,
    _PendingSlash,
    _PendingSlashChoice,
    _replace_player,
)


HUOSHA = "sgs_basic_huosha"
TAO = "sgs_basic_tao"
SHAN = "sgs_basic_shan"
JIU = "sgs_basic_jiu"
FANGTIAN = "sgs_weapon_fangtianhuaji"
SHANDIAN = "sgs_delayed_shandian"
SPADE_7_SHA = "sgs-mobile-20260725-140"
RESCUE_OR_DODGE_KEYS = frozenset({TAO, SHAN, JIU})


def _session(*, seed: int = 2) -> Formal2v2Session:
    return Formal2v2Session(
        seed=seed,
        configuration=Formal2v2Configuration.formal_profile(),
        analysis_only=False,
    )


def _op(
    game: ProductionBasicCardBatch, operation: str, **filters: Any
) -> LegalAction | None:
    for action in game.legal_actions():
        if action.payload.get("operation") != operation:
            continue
        ok = True
        for key, value in filters.items():
            if key == "targets" and action.target_ids != value:
                ok = False
            if key == "card_key" and action.payload.get("card_key") != value:
                ok = False
        if ok:
            return action
    return None


def _require_op(
    game: ProductionBasicCardBatch, operation: str, **filters: Any
) -> LegalAction:
    action = _op(game, operation, **filters)
    assert action is not None, (
        f"缺少操作{operation!r}："
        f"{sorted({a.payload.get('operation') for a in game.legal_actions()})}"
    )
    return action


def _step(game: ProductionBasicCardBatch, action: LegalAction) -> None:
    game.step(BatchActionIdController(action.action_id))


def _strip_hand(game: ProductionBasicCardBatch, player_id: str) -> None:
    for instance_id in tuple(game.state.card_ids_in(ZoneRef.hand(player_id))):
        game._state = game.state.move_card(instance_id, DISCARD_PILE)


def _strip_rescue_and_dodge(game: ProductionBasicCardBatch) -> None:
    for player in game.state.players:
        for instance_id in tuple(
            game.state.card_ids_in(ZoneRef.hand(player.player_id))
        ):
            if game.state.cards_by_id[instance_id].card_key in RESCUE_OR_DODGE_KEYS:
                game._state = game.state.move_card(instance_id, DISCARD_PILE)


def _give_card(
    game: ProductionBasicCardBatch,
    player_id: str,
    card_key: str,
) -> str:
    for zone in (DRAW_PILE, DISCARD_PILE):
        for instance_id in game.state.card_ids_in(zone):
            if game.state.cards_by_id[instance_id].card_key == card_key:
                game._state = game.state.move_card(
                    instance_id, ZoneRef.hand(player_id)
                )
                return instance_id
    raise AssertionError(f"找不到{card_key}")


def _equip_weapon(
    game: ProductionBasicCardBatch, player_id: str, card_key: str
) -> str:
    for instance_id in game.state.card_ids_in(DRAW_PILE):
        if game.state.cards_by_id[instance_id].card_key == card_key:
            game._state = game.state.move_card(
                instance_id, ZoneRef.equipment(player_id, "weapon")
            )
            return instance_id
    raise AssertionError(f"牌堆中找不到武器{card_key}")


def _enter_play(game: ProductionBasicCardBatch) -> None:
    for operation in ("proceed_prepare", "proceed_judgment", "proceed_draw"):
        _step(game, _require_op(game, operation))


def _end_turn(game: ProductionBasicCardBatch) -> None:
    _step(game, _require_op(game, "end_play_phase"))
    while game.phase is ProductionPhase.DISCARD:
        if _op(game, "discard_phase_submit") is not None:
            _step(game, _require_op(game, "discard_phase_submit"))
        else:
            _step(game, _require_op(game, "select_discard_card"))
    _step(game, _require_op(game, "end_turn"))


def _pass_all_rescues(game: ProductionBasicCardBatch) -> None:
    while game.phase is ProductionPhase.DYING_RESCUE:
        _step(game, _require_op(game, "pass_rescue"))


def _chain_all(game: ProductionBasicCardBatch) -> None:
    for player_id in game.player_ids:
        game._state = _replace_player(game.state, player_id, chained=True)


def _set_hp(game: ProductionBasicCardBatch, player_id: str, hp: int) -> None:
    game._state = _replace_player(game.state, player_id, hp=hp)


def _put_draw_at(
    game: ProductionBasicCardBatch, instance_id: str, position: int = 0
) -> None:
    if game.state.location_of(instance_id) != DRAW_PILE:
        game._state = game.state.move_card(instance_id, DRAW_PILE)
    pile = list(game.state.card_ids_in(DRAW_PILE))
    pile.remove(instance_id)
    pile.insert(position, instance_id)
    game._state = game.state.reorder_zone(DRAW_PILE, tuple(pile))


def _pass_judgment_wuxie(game: ProductionBasicCardBatch) -> None:
    while _op(game, "pass_judgment_wuxie") is not None:
        _step(game, _require_op(game, "pass_judgment_wuxie"))


def _slash_discard_moves(
    game: ProductionBasicCardBatch, slash_id: str
) -> list[object]:
    return [
        event
        for event in game.events
        if event.event_type is EventType.CARD_MOVED
        and event.card_instance_id == slash_id
        and event.payload.get("destination", {}).get("kind") == "discard_pile"
    ]


def _reasons(game: ProductionBasicCardBatch) -> list[object]:
    return [event.payload.get("reason") for event in game.events]


# ----------------------------------------------------------------------
# F-003：死亡 current-player 不得再当救援锚点
# ----------------------------------------------------------------------


def test_f003_dead_current_player_does_not_anchor_next_dying_rescue() -> None:
    """2v2 全员横置：p1 火杀 p2；hp 1/1/1/4；无闪无桃。

    p2 死亡后传导至 p1；p1 确认死亡后再传导至 p3 进入新 DYING。
    修复后不得抛 UnsupportedRuleError，p3 救援窗口必须打开，
    响应顺序必须是存活角色环。
    """

    game = _session()
    _enter_play(game)
    _strip_rescue_and_dodge(game)
    _strip_hand(game, "p1")
    slash_id = _give_card(game, "p1", HUOSHA)
    _chain_all(game)
    _set_hp(game, "p1", 1)
    _set_hp(game, "p2", 1)
    _set_hp(game, "p3", 1)
    _set_hp(game, "p4", 4)
    _step(game, _require_op(game, "use_slash", card_key=HUOSHA, targets=("p2",)))
    if _op(game, "pass_slash_response") is not None:
        _step(game, _require_op(game, "pass_slash_response"))
    assert game.phase is ProductionPhase.DYING_RESCUE
    assert game.runtime.pending_dying_id == "p2"
    while (
        game.phase is ProductionPhase.DYING_RESCUE
        and game.runtime.pending_dying_id == "p2"
    ):
        _step(game, _require_op(game, "pass_rescue"))
    assert game.state.players_by_id["p2"].alive is False
    assert game.phase is ProductionPhase.DYING_RESCUE
    assert game.runtime.pending_dying_id == "p1"
    while (
        game.phase is ProductionPhase.DYING_RESCUE
        and game.runtime.pending_dying_id == "p1"
    ):
        _step(game, _require_op(game, "pass_rescue"))
    assert game.state.players_by_id["p1"].alive is False
    assert game.is_finished is False
    assert game.phase is ProductionPhase.DYING_RESCUE
    assert game.runtime.pending_dying_id == "p3"
    assert game.state.players_by_id["p3"].hp <= 0
    rescue_order = game.runtime.rescue_order
    assert rescue_order
    assert "p1" not in rescue_order
    assert "p2" not in rescue_order
    topology = PlayerTopology.from_state(game.state)
    expected_anchor = topology.first_alive_after("p1")
    assert expected_anchor == "p3"
    assert rescue_order == topology.alive_ring_from(expected_anchor)
    with pytest.raises(UnsupportedRuleError, match="不能作为存活环顺序锚点"):
        topology.alive_ring_from("p1")
    del slash_id


def test_f003_lightning_original_death_then_next_chain_target_dying() -> None:
    """闪电原角色确认死亡后，下一传导目标进入 DYING 时也不得用死者锚点。"""

    game = _session()
    _enter_play(game)
    _strip_rescue_and_dodge(game)
    _strip_hand(game, "p1")
    _give_card(game, "p1", SHANDIAN)
    _chain_all(game)
    _set_hp(game, "p1", 1)
    _set_hp(game, "p2", 1)
    _set_hp(game, "p3", 4)
    _set_hp(game, "p4", 4)
    _step(game, _require_op(game, "use_shandian", card_key=SHANDIAN))
    _end_turn(game)
    for _ in range(3):
        _enter_play(game)
        _end_turn(game)
    assert game.current_player_id == "p1"
    _step(game, _require_op(game, "proceed_prepare"))
    _step(game, _require_op(game, "proceed_judgment"))
    _put_draw_at(game, SPADE_7_SHA, 0)
    _pass_judgment_wuxie(game)
    assert game.phase is ProductionPhase.DYING_RESCUE
    assert game.runtime.pending_dying_id == "p1"
    while (
        game.phase is ProductionPhase.DYING_RESCUE
        and game.runtime.pending_dying_id == "p1"
    ):
        _step(game, _require_op(game, "pass_rescue"))
    assert game.state.players_by_id["p1"].alive is False
    assert game.is_finished is False
    assert game.phase is ProductionPhase.DYING_RESCUE
    assert game.runtime.pending_dying_id == "p2"
    topology = PlayerTopology.from_state(game.state)
    assert game.runtime.rescue_order == topology.alive_ring_from(
        topology.first_alive_after("p1")
    )
    with pytest.raises(UnsupportedRuleError, match="不能作为存活环顺序锚点"):
        topology.alive_ring_from("p1")


def test_alive_ring_from_still_rejects_dead_anchor() -> None:
    game = _session()
    game._state = _replace_player(game.state, "p1", hp=0, alive=False)
    topology = PlayerTopology.from_state(game.state)
    with pytest.raises(UnsupportedRuleError, match="不能作为存活环顺序锚点"):
        topology.alive_ring_from("p1")
    with pytest.raises(UnsupportedRuleError, match="不能作为存活环继任锚点"):
        topology.next_alive("p1")
    assert topology.first_alive_after("p1") == "p2"
    assert topology.alive_ring_from("p2") == ("p2", "p3", "p4")
    game._state = _replace_player(game.state, "p4", hp=0, alive=False)
    wrap_topo = PlayerTopology.from_state(game.state)
    assert wrap_topo.first_alive_after("p4") == "p2"


# ----------------------------------------------------------------------
# F-004：方天未完成时 current-player 死亡不得清根杀
# ----------------------------------------------------------------------


def test_f004_fangtian_continues_after_current_player_chain_death() -> None:
    """方天火杀至少两目标；第一目标传导打死当前回合角色；剩余目标不濒死。

    必须：死亡提交成功、剩余目标真实进入 SLASH_RESPONSE 并完成结算、
    根杀 exactly-once finalize、PROCESSING 无孤儿、pending_slash 最终清空、
    最后才进入下一存活角色 PREPARE。
    """

    game = _session()
    _enter_play(game)
    _strip_rescue_and_dodge(game)
    _equip_weapon(game, "p1", FANGTIAN)
    _strip_hand(game, "p1")
    slash_id = _give_card(game, "p1", HUOSHA)
    _chain_all(game)
    _set_hp(game, "p1", 1)
    _set_hp(game, "p2", 4)
    _set_hp(game, "p3", 4)
    _set_hp(game, "p4", 4)
    action = _require_op(game, "use_slash", card_key=HUOSHA, targets=("p2", "p3"))
    _step(game, action)
    assert game.runtime.pending_slash is not None
    assert game.runtime.pending_slash.target_sequence == ("p2", "p3")
    assert game.runtime.pending_slash.current_target_index == 0
    _step(game, _require_op(game, "pass_slash_response"))
    assert game.phase is ProductionPhase.DYING_RESCUE
    assert game.runtime.pending_dying_id == "p1"
    _pass_all_rescues(game)
    assert game.state.players_by_id["p1"].alive is False
    assert game.is_finished is False
    assert game.state.players_by_id["p3"].hp > 0
    assert game.state.players_by_id["p4"].hp > 0
    assert game.phase is ProductionPhase.SLASH_RESPONSE
    assert game.runtime.pending_slash is not None
    assert game.runtime.pending_slash.target_id == "p3"
    assert game.runtime.pending_slash.current_target_index == 1
    assert game.state.location_of(slash_id) == PROCESSING_ZONE
    game.assert_resolution_invariants()
    _step(game, _require_op(game, "pass_slash_response"))
    assert game.state.players_by_id["p3"].hp == 2
    assert game.runtime.pending_slash is None
    assert game.state.location_of(slash_id) == DISCARD_PILE
    assert not game.state.card_ids_in(PROCESSING_ZONE)
    discard_moves = _slash_discard_moves(game, slash_id)
    assert len(discard_moves) == 1
    game.assert_resolution_invariants()
    assert game.phase is ProductionPhase.PREPARE
    assert game.current_player_id == "p2"
    assert game.is_finished is False


# ----------------------------------------------------------------------
# F-005：闪电 chain 子目标非终局死亡不得清判定根
# ----------------------------------------------------------------------


def test_f005_shandian_child_death_keeps_judgment_root_and_draws() -> None:
    """p1 闪电命中 4→1 仍存活；全员横置；p2=1 被传导 3 雷非终局死亡。

    不得走 shandian_victory_cleanup；chain 结束后走正常闪电 root
    completion：JUDGMENT → DRAW（真实摸 2 张）→ PLAY。
    """

    game = _session()
    _enter_play(game)
    _strip_rescue_and_dodge(game)
    _strip_hand(game, "p1")
    shandian_id = _give_card(game, "p1", SHANDIAN)
    _chain_all(game)
    _set_hp(game, "p1", 4)
    _set_hp(game, "p2", 1)
    _set_hp(game, "p3", 4)
    _set_hp(game, "p4", 4)
    _step(game, _require_op(game, "use_shandian", card_key=SHANDIAN))
    _end_turn(game)
    for _ in range(3):
        _enter_play(game)
        _end_turn(game)
    assert game.current_player_id == "p1"
    _step(game, _require_op(game, "proceed_prepare"))
    _step(game, _require_op(game, "proceed_judgment"))
    _put_draw_at(game, SPADE_7_SHA, 0)
    _pass_judgment_wuxie(game)
    assert game.state.players_by_id["p1"].hp == 1
    assert game.state.players_by_id["p1"].alive is True
    if game.phase is ProductionPhase.DYING_RESCUE:
        assert game.runtime.pending_dying_id == "p2"
        pending_before_death = game.runtime.pending_judgment
        assert pending_before_death is not None
        assert pending_before_death.trick_instance_id == shandian_id
        assert pending_before_death.stage == "resolving_effect"
        _pass_all_rescues(game)
    assert game.state.players_by_id["p2"].alive is False
    assert game.is_finished is False
    assert "shandian_victory_cleanup" not in _reasons(game)
    assert _reasons(game).count("shandian_resolved") == 1
    assert game.runtime.pending_judgment is None
    assert game.phase is ProductionPhase.JUDGMENT
    assert game.current_player_id == "p1"
    assert game.state.location_of(shandian_id) == DISCARD_PILE
    hand_before = len(game.state.card_ids_in(ZoneRef.hand("p1")))
    gained_before = [
        event
        for event in game.events
        if event.event_type is EventType.CARD_GAINED
        and event.payload.get("reason") == "draw_phase"
    ]
    _step(game, _require_op(game, "proceed_judgment"))
    assert game.phase is ProductionPhase.DRAW
    _step(game, _require_op(game, "proceed_draw"))
    assert game.phase is ProductionPhase.PLAY
    hand_after = len(game.state.card_ids_in(ZoneRef.hand("p1")))
    assert hand_after == hand_before + 2
    gained_after = [
        event
        for event in game.events
        if event.event_type is EventType.CARD_GAINED
        and event.payload.get("reason") == "draw_phase"
    ]
    assert len(gained_after) == len(gained_before) + 2


def test_f005_pending_judgment_survives_child_dying_pause() -> None:
    """p3 也被传导打入濒死时，p2 死亡提交后判定根必须仍挂起。"""

    game = _session()
    _enter_play(game)
    _strip_rescue_and_dodge(game)
    _strip_hand(game, "p1")
    shandian_id = _give_card(game, "p1", SHANDIAN)
    _chain_all(game)
    _set_hp(game, "p1", 4)
    _set_hp(game, "p2", 1)
    _set_hp(game, "p3", 3)
    _set_hp(game, "p4", 4)
    _step(game, _require_op(game, "use_shandian", card_key=SHANDIAN))
    _end_turn(game)
    for _ in range(3):
        _enter_play(game)
        _end_turn(game)
    _step(game, _require_op(game, "proceed_prepare"))
    _step(game, _require_op(game, "proceed_judgment"))
    _put_draw_at(game, SPADE_7_SHA, 0)
    _pass_judgment_wuxie(game)
    assert game.phase is ProductionPhase.DYING_RESCUE
    assert game.runtime.pending_dying_id == "p2"
    while (
        game.phase is ProductionPhase.DYING_RESCUE
        and game.runtime.pending_dying_id == "p2"
    ):
        _step(game, _require_op(game, "pass_rescue"))
    assert game.state.players_by_id["p2"].alive is False
    assert game.is_finished is False
    assert game.phase is ProductionPhase.DYING_RESCUE
    assert game.runtime.pending_dying_id == "p3"
    pending = game.runtime.pending_judgment
    assert pending is not None
    assert pending.trick_instance_id == shandian_id
    assert pending.stage == "resolving_effect"
    assert pending.cleanup_done is False
    assert "shandian_victory_cleanup" not in _reasons(game)
    rescuer = game.runtime.rescue_order[game.runtime.rescue_index]
    peach_id = _give_card(game, rescuer, TAO)
    _step(game, _require_op(game, "rescue_with_peach", card_key=TAO))
    del peach_id
    assert game.state.players_by_id["p3"].alive is True
    assert game.state.players_by_id["p3"].hp >= 1
    assert game.phase is ProductionPhase.JUDGMENT
    assert game.current_player_id == "p1"
    assert _reasons(game).count("shandian_resolved") == 1
    hand_before = len(game.state.card_ids_in(ZoneRef.hand("p1")))
    _step(game, _require_op(game, "proceed_judgment"))
    _step(game, _require_op(game, "proceed_draw"))
    assert game.phase is ProductionPhase.PLAY
    assert len(game.state.card_ids_in(ZoneRef.hand("p1"))) == hand_before + 2


# ----------------------------------------------------------------------
# F-006：方天 progression 必须进入 execution hash
# ----------------------------------------------------------------------


def _pending_slash_for_hash(
    *,
    target_id: str = "p2",
    target_sequence: tuple[str, ...] = ("p2", "p3"),
    current_target_index: int = 0,
) -> _PendingSlash:
    return _PendingSlash(
        attacker_id="p1",
        target_id=target_id,
        slash_instance_id="slash-f006",
        boosted=False,
        target_sequence=target_sequence,
        current_target_index=current_target_index,
    )


def test_f006_target_sequence_changes_execution_hash() -> None:
    """只改 target_sequence；target_id / index / 其余 runtime 完全相同。"""

    game = _session()
    slash_a = _pending_slash_for_hash(target_sequence=("p2", "p3"))
    slash_b = _pending_slash_for_hash(target_sequence=("p2", "p4"))
    assert slash_a.target_id == slash_b.target_id
    assert slash_a.current_target_index == slash_b.current_target_index
    game._runtime = dataclasses.replace(game.runtime, pending_slash=slash_a)
    hash_a = game.execution_hash
    game._runtime = dataclasses.replace(game.runtime, pending_slash=slash_b)
    hash_b = game.execution_hash
    assert hash_a != hash_b


def test_f006_current_target_index_changes_execution_hash() -> None:
    """只改 current_target_index；target_id / sequence / 其余完全相同。"""

    game = _session()
    slash_zero = _pending_slash_for_hash(current_target_index=0)
    slash_one = _pending_slash_for_hash(current_target_index=1)
    assert slash_zero.target_id == slash_one.target_id
    assert slash_zero.target_sequence == slash_one.target_sequence
    game._runtime = dataclasses.replace(game.runtime, pending_slash=slash_zero)
    hash_zero = game.execution_hash
    game._runtime = dataclasses.replace(game.runtime, pending_slash=slash_one)
    hash_one = game.execution_hash
    assert hash_zero != hash_one


def test_f006_audit_value_exposes_fangtian_progression() -> None:
    game = _session()
    slash = _pending_slash_for_hash(
        target_sequence=("p2", "p4"),
        current_target_index=1,
    )
    game._runtime = dataclasses.replace(game.runtime, pending_slash=slash)
    pending_value = game.runtime.audit_value()["pending_slash"]
    assert pending_value is not None
    assert pending_value["target_sequence"] == ["p2", "p4"]
    assert pending_value["current_target_index"] == 1


def test_f006_pending_slash_inventory_covers_dataclass_fields() -> None:
    from scripts.sgs_engine.production_batch import (
        PENDING_SLASH_EXECUTION_FIELD_INVENTORY,
    )

    assert PENDING_SLASH_EXECUTION_FIELD_INVENTORY == {
        item.name for item in dataclasses.fields(_PendingSlash)
    }
    game = _session()
    slash = _pending_slash_for_hash()
    serialized = game.runtime._pending_slash_value(slash)
    assert serialized is not None
    assert set(serialized) == PENDING_SLASH_EXECUTION_FIELD_INVENTORY


def test_f006_nested_pending_slash_sequence_divergence_fails_closed() -> None:
    """现有 pending_slash_choice 一致性 invariant：只改嵌套副本的
    target_sequence 必须失败关闭，不得静默接受。"""

    game = _session()
    slash = _pending_slash_for_hash(target_sequence=("p2", "p3"))
    diverged = dataclasses.replace(slash, target_sequence=("p3", "p2"))
    choice = _PendingSlashChoice(
        weapon_key="sgs_weapon_guanshifu",
        kind="guanshifu_force_hit",
        attacker_id="p1",
        target_id="p2",
        window_id="window-f006",
        pending_slash=diverged,
    )
    game._runtime = dataclasses.replace(
        game.runtime,
        pending_slash=slash,
        pending_slash_choice=choice,
    )
    with pytest.raises(ProductionBatchError, match="不一致"):
        _ = game.execution_snapshot
