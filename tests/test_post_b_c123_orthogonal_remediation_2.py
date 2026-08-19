# -*- coding: utf-8 -*-
"""POST-B C123 正交 remediation 2：C123-R1-NEW-001 回归测试。

独立 re-audit 确认 F-003～F-006 CLOSED，但发现新 BLOCKER：
TURN_OWNER_DEATH_CHAIN_CONTINUATION_LOST。

本文件先于 production 修复提交，用于证明基线 614ebbd3 真实失败，
并在修复后锁定最小路径。本轮状态只能写成
IMPLEMENTED_PENDING_INDEPENDENT_REAUDIT，不得写成
REMEDIATION_REAUDIT_PASSED / CLOSED。

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
    ProductionPhase,
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


def _pass_rescues_for(game: ProductionBasicCardBatch, dying_id: str) -> None:
    while (
        game.phase is ProductionPhase.DYING_RESCUE
        and game.runtime.pending_dying_id == dying_id
    ):
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


def _reasons(game: ProductionBasicCardBatch) -> list[object]:
    return [event.payload.get("reason") for event in game.events]


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


def _drain_deck_to(game: ProductionBasicCardBatch, count: int) -> None:
    ids = list(game.state.card_ids_in(DRAW_PILE))
    assert len(ids) >= count
    game._state = game.state.move_cards(
        {instance_id: DISCARD_PILE for instance_id in ids[count:]}
    )


def _place_shandian_and_return_to_p1(game: ProductionBasicCardBatch) -> str:
    _enter_play(game)
    _strip_rescue_and_dodge(game)
    _strip_hand(game, "p1")
    shandian_id = _give_card(game, "p1", SHANDIAN)
    _step(game, _require_op(game, "use_shandian", card_key=SHANDIAN))
    _end_turn(game)
    for _ in range(3):
        _enter_play(game)
        _end_turn(game)
    assert game.current_player_id == "p1"
    return shandian_id


def _hit_p1_lightning(game: ProductionBasicCardBatch) -> None:
    _step(game, _require_op(game, "proceed_prepare"))
    _step(game, _require_op(game, "proceed_judgment"))
    _put_draw_at(game, SPADE_7_SHA, 0)
    _pass_judgment_wuxie(game)


def _lightning_cleanup_reasons(game: ProductionBasicCardBatch) -> list[object]:
    return [
        reason
        for reason in _reasons(game)
        if reason in ("shandian_resolved", "shandian_victory_cleanup")
    ]


def _assert_root_cleared(game: ProductionBasicCardBatch) -> None:
    assert game.runtime.pending_chain is None
    assert game.runtime.pending_judgment is None
    assert not game.state.card_ids_in(PROCESSING_ZONE)
    game.assert_resolution_invariants()


# ----------------------------------------------------------------------
# A. C123-R1-NEW-001 主 reproduction：p1 先死，p2 后死
# ----------------------------------------------------------------------


def test_c123_r1_new_001_lightning_chain_owner_then_child_death_ends_turn() -> None:
    """4 人 2v2 全员横置：p1/p2 均会被闪电 3 点伤害致死。

    p1 判定区【闪电】命中 → p1 DYING → 无救援 → p1 DEATH（游戏继续）
    → 传导 p2 DYING → 无救援 → p2 DEATH。

    根结算全部完成后不得返回已死 p1 的 PLAY；必须进入下一存活角色 PREPARE。
    """

    game = _session()
    shandian_id = _place_shandian_and_return_to_p1(game)
    _chain_all(game)
    _set_hp(game, "p1", 1)
    _set_hp(game, "p2", 1)
    _set_hp(game, "p3", 4)
    _set_hp(game, "p4", 4)
    _hit_p1_lightning(game)
    assert game.phase is ProductionPhase.DYING_RESCUE
    assert game.runtime.pending_dying_id == "p1"
    _pass_rescues_for(game, "p1")
    assert game.state.players_by_id["p1"].alive is False
    assert game.is_finished is False
    assert game.phase is ProductionPhase.DYING_RESCUE
    assert game.runtime.pending_dying_id == "p2"
    _pass_rescues_for(game, "p2")
    assert game.state.players_by_id["p2"].alive is False
    assert game.state.players_by_id["p1"].alive is False
    assert game.state.players_by_id["p3"].alive is True
    assert game.state.players_by_id["p4"].alive is True
    assert game.is_finished is False
    deaths = [
        event.target_ids
        for event in game.events
        if event.event_type is EventType.DEATH
    ]
    assert ("p1",) in deaths
    assert ("p2",) in deaths
    assert deaths.index(("p1",)) < deaths.index(("p2",))
    assert len(_lightning_cleanup_reasons(game)) == 1
    assert game.state.location_of(shandian_id) == DISCARD_PILE
    _assert_root_cleared(game)
    assert game.phase is not ProductionPhase.PLAY
    assert game.current_player_id != "p1"
    assert game.phase is ProductionPhase.PREPARE
    assert game.current_player_id == "p3"
    assert game.state.players_by_id[game.current_player_id].alive is True


# ----------------------------------------------------------------------
# B. p1 先死，p2 后续濒死被桃救回
# ----------------------------------------------------------------------


def test_c123_r1_new_001_owner_death_then_child_rescued_still_ends_turn() -> None:
    """p1 先确认死亡，p2 进入 DYING 后被桃救回。chain 完成后仍须结束 p1 回合。"""

    game = _session()
    shandian_id = _place_shandian_and_return_to_p1(game)
    _chain_all(game)
    _set_hp(game, "p1", 1)
    _set_hp(game, "p2", 3)
    _set_hp(game, "p3", 4)
    _set_hp(game, "p4", 4)
    _hit_p1_lightning(game)
    assert game.phase is ProductionPhase.DYING_RESCUE
    assert game.runtime.pending_dying_id == "p1"
    _pass_rescues_for(game, "p1")
    assert game.state.players_by_id["p1"].alive is False
    assert game.is_finished is False
    assert game.phase is ProductionPhase.DYING_RESCUE
    assert game.runtime.pending_dying_id == "p2"
    rescuer = game.runtime.rescue_order[game.runtime.rescue_index]
    _give_card(game, rescuer, TAO)
    _step(game, _require_op(game, "rescue_with_peach", card_key=TAO))
    assert game.state.players_by_id["p2"].alive is True
    assert game.state.players_by_id["p2"].hp >= 1
    assert game.state.players_by_id["p1"].alive is False
    assert game.is_finished is False
    assert len(_lightning_cleanup_reasons(game)) == 1
    assert game.state.location_of(shandian_id) == DISCARD_PILE
    _assert_root_cleared(game)
    assert game.phase is ProductionPhase.PREPARE
    assert game.current_player_id == "p2"
    assert game.state.players_by_id["p2"].alive is True


# ----------------------------------------------------------------------
# C. p1 先死，后续 chain target 只受伤不进入 DYING
# ----------------------------------------------------------------------


def test_c123_r1_new_001_owner_death_child_damaged_only_ends_turn() -> None:
    """Remediation 1 已有正确路径：p1 死亡后 p2 仅受伤，仍须进入下一存活 PREPARE。"""

    game = _session()
    shandian_id = _place_shandian_and_return_to_p1(game)
    _chain_all(game)
    _set_hp(game, "p1", 1)
    _set_hp(game, "p2", 4)
    _set_hp(game, "p3", 4)
    _set_hp(game, "p4", 4)
    _hit_p1_lightning(game)
    assert game.phase is ProductionPhase.DYING_RESCUE
    assert game.runtime.pending_dying_id == "p1"
    _pass_all_rescues(game)
    assert game.state.players_by_id["p1"].alive is False
    assert game.state.players_by_id["p2"].alive is True
    assert game.state.players_by_id["p2"].hp == 1
    assert game.is_finished is False
    assert len(_lightning_cleanup_reasons(game)) == 1
    assert game.state.location_of(shandian_id) == DISCARD_PILE
    _assert_root_cleared(game)
    assert game.phase is ProductionPhase.PREPARE
    assert game.current_player_id == "p2"


# ----------------------------------------------------------------------
# D. F-003 原路径：其他角色先死 → turn owner 后死 → 下一目标再 DYING
# ----------------------------------------------------------------------


def test_c123_r1_new_001_f003_dead_anchor_does_not_regress() -> None:
    game = _session()
    _enter_play(game)
    _strip_rescue_and_dodge(game)
    _strip_hand(game, "p1")
    _give_card(game, "p1", HUOSHA)
    _chain_all(game)
    _set_hp(game, "p1", 1)
    _set_hp(game, "p2", 1)
    _set_hp(game, "p3", 1)
    _set_hp(game, "p4", 4)
    _step(game, _require_op(game, "use_slash", card_key=HUOSHA, targets=("p2",)))
    if _op(game, "pass_slash_response") is not None:
        _step(game, _require_op(game, "pass_slash_response"))
    assert game.runtime.pending_dying_id == "p2"
    _pass_rescues_for(game, "p2")
    assert game.state.players_by_id["p2"].alive is False
    assert game.runtime.pending_dying_id == "p1"
    _pass_rescues_for(game, "p1")
    assert game.state.players_by_id["p1"].alive is False
    assert game.is_finished is False
    assert game.phase is ProductionPhase.DYING_RESCUE
    assert game.runtime.pending_dying_id == "p3"
    rescue_order = game.runtime.rescue_order
    assert "p1" not in rescue_order
    assert "p2" not in rescue_order
    topology = PlayerTopology.from_state(game.state)
    expected_anchor = topology.first_alive_after("p1")
    assert expected_anchor == "p3"
    assert rescue_order == topology.alive_ring_from(expected_anchor)
    with pytest.raises(UnsupportedRuleError, match="不能作为存活环顺序锚点"):
        topology.alive_ring_from("p1")


# ----------------------------------------------------------------------
# E. F-004 原路径：方天剩余目标必须继续，root exactly once 后才切回合
# ----------------------------------------------------------------------


def test_c123_r1_new_001_f004_fangtian_remaining_targets_continue() -> None:
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
    _step(game, _require_op(game, "use_slash", card_key=HUOSHA, targets=("p2", "p3")))
    assert game.runtime.pending_slash is not None
    assert game.runtime.pending_slash.target_sequence == ("p2", "p3")
    _step(game, _require_op(game, "pass_slash_response"))
    assert game.runtime.pending_dying_id == "p1"
    _pass_all_rescues(game)
    assert game.state.players_by_id["p1"].alive is False
    assert game.is_finished is False
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
    assert len(_slash_discard_moves(game, slash_id)) == 1
    game.assert_resolution_invariants()
    assert game.phase is ProductionPhase.PREPARE
    assert game.current_player_id == "p2"


# ----------------------------------------------------------------------
# F. F-005：闪电原角色存活，chain child 非终局死亡，正常 JUDGMENT→DRAW→PLAY
# ----------------------------------------------------------------------


def test_c123_r1_new_001_f005_alive_owner_child_death_keeps_judgment() -> None:
    game = _session()
    shandian_id = _place_shandian_and_return_to_p1(game)
    _chain_all(game)
    _set_hp(game, "p1", 4)
    _set_hp(game, "p2", 1)
    _set_hp(game, "p3", 4)
    _set_hp(game, "p4", 4)
    _hit_p1_lightning(game)
    assert game.state.players_by_id["p1"].hp == 1
    assert game.state.players_by_id["p1"].alive is True
    if game.phase is ProductionPhase.DYING_RESCUE:
        assert game.runtime.pending_dying_id == "p2"
        pending_before_death = game.runtime.pending_judgment
        assert pending_before_death is not None
        assert pending_before_death.trick_instance_id == shandian_id
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
    _step(game, _require_op(game, "proceed_judgment"))
    assert game.phase is ProductionPhase.DRAW
    _step(game, _require_op(game, "proceed_draw"))
    assert game.phase is ProductionPhase.PLAY
    assert len(game.state.card_ids_in(ZoneRef.hand("p1"))) == hand_before + 2


# ----------------------------------------------------------------------
# H. chain 过程中直接 team victory：终局优先，不得额外切 PREPARE
# ----------------------------------------------------------------------


def test_c123_r1_new_001_chain_team_victory_does_not_enter_prepare() -> None:
    """p3 已死：p1 先死游戏继续，p2 后死使 team_b 全灭。必须 FINISHED，不得 PREPARE。"""

    game = _session()
    shandian_id = _place_shandian_and_return_to_p1(game)
    _chain_all(game)
    game._state = _replace_player(game.state, "p3", hp=0, alive=False)
    _set_hp(game, "p1", 1)
    _set_hp(game, "p2", 1)
    _set_hp(game, "p4", 4)
    _hit_p1_lightning(game)
    assert game.runtime.pending_dying_id == "p1"
    _pass_rescues_for(game, "p1")
    assert game.state.players_by_id["p1"].alive is False
    assert game.is_finished is False
    assert game.phase is ProductionPhase.DYING_RESCUE
    assert game.runtime.pending_dying_id == "p2"
    _pass_rescues_for(game, "p2")
    assert game.state.players_by_id["p2"].alive is False
    assert game.is_finished is True
    assert game.winner_id == "team_a"
    assert game.phase is ProductionPhase.FINISHED
    assert game.phase is not ProductionPhase.PREPARE
    assert game.state.location_of(shandian_id) == DISCARD_PILE
    assert not game.state.card_ids_in(PROCESSING_ZONE)
    game.assert_finished_state_invariants()


# ----------------------------------------------------------------------
# I. chain 中死亡奖励耗尽牌堆：正式平局优先，不得继续 turn transition
# ----------------------------------------------------------------------


def test_c123_r1_new_001_chain_death_reward_draw_does_not_enter_prepare() -> None:
    """p1 已死且 chain 未完；p2 死亡奖励耗尽牌堆。必须正式平局，不得 PREPARE。"""

    game = _session()
    _place_shandian_and_return_to_p1(game)
    _chain_all(game)
    _set_hp(game, "p1", 1)
    _set_hp(game, "p2", 1)
    _set_hp(game, "p3", 4)
    _set_hp(game, "p4", 4)
    _hit_p1_lightning(game)
    _pass_rescues_for(game, "p1")
    assert game.state.players_by_id["p1"].alive is False
    assert game.is_finished is False
    assert game.phase is ProductionPhase.DYING_RESCUE
    assert game.runtime.pending_dying_id == "p2"
    _drain_deck_to(game, 0)
    _pass_rescues_for(game, "p2")
    assert game.state.players_by_id["p2"].alive is False
    assert game.is_finished is True
    assert game.winner_id is None
    assert game.runtime.game_over_reason == "2v2_draw_deck_exhausted"
    assert game.phase is ProductionPhase.FINISHED
    assert game.phase is not ProductionPhase.PREPARE
    game.assert_finished_state_invariants()


# ----------------------------------------------------------------------
# 推迟标记必须进入 execution hash（A 类行为字段）
# ----------------------------------------------------------------------


def test_c123_r1_new_001_deferred_turn_end_flag_changes_execution_hash() -> None:
    game = _session()
    runtime = game.runtime
    assert runtime.deferred_turn_end_after_owner_death is False
    hash_off = game.execution_hash
    game._runtime = dataclasses.replace(
        runtime, deferred_turn_end_after_owner_death=True
    )
    hash_on = game.execution_hash
    assert hash_off != hash_on
    audit = game.runtime.audit_value()
    assert audit["deferred_turn_end_after_owner_death"] is True
