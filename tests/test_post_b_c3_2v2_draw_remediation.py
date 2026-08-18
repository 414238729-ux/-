# -*- coding: utf-8 -*-
"""C123 remediation：§2.11 正式平局 sibling 路径回归。

只走真实 Formal2v2Session production 路径：
enumerate_legal_actions → step。不得把 helper 成功当成引擎正确。

覆盖：摸牌阶段、五谷不足/恰好耗尽、延时锦囊判定、无中、铁索重铸、
死亡奖励、八卦、run() 公共 API、复杂平局回放往返，以及
FINISHED_TRANSIENT_RUNTIME_FIELDS 全集清场防漂移。
"""

from __future__ import annotations

from dataclasses import replace
from types import MappingProxyType
from typing import Any

import pytest

from scripts.sgs_engine.actions import LegalAction
from scripts.sgs_engine.events import EventType
from scripts.sgs_engine.mode_2v2 import (
    Formal2v2Configuration,
    Formal2v2Session,
)
from scripts.sgs_engine.model import (
    DISCARD_PILE,
    DRAW_PILE,
    PROCESSING_ZONE,
    REVEALED_ZONE,
    ZoneRef,
)
from scripts.sgs_engine.production_batch import (
    FINISHED_TRANSIENT_RUNTIME_FIELDS,
    BatchActionIdController,
    BatchReferenceController,
    ProductionBasicCardBatch,
    ProductionBatchError,
    ProductionPhase,
    _BatchRuntime,
    _replace_player,
    cleanup_finished_transient_runtime,
    finished_transient_cleanup_values,
)
from scripts.sgs_engine.production_replay import (
    record_reference_formal_2v2,
    reexecute_production_replay,
)

SHA = "sgs_basic_sha"
JIU = "sgs_basic_jiu"
WUGU = "sgs_trick_wugufengdeng"
WUZHONG = "sgs_trick_wuzhongshengyou"
TIESUO = "sgs_trick_tiesuolianhuan"
LEBUSI = "sgs_delayed_lebusi"
BAGUA = "sgs_armor_baguazhen"

_DIRTY_TRANSIENT_SAMPLES: dict[str, object] = {
    "pending_trick": "residual",
    "pending_slash": "residual",
    "pending_judgment": "residual",
    "pending_borrowed_sword": "residual",
    "pending_group_trick": "residual",
    "pending_duel": "residual",
    "pending_fire_attack": "residual",
    "pending_wugu": "residual",
    "pending_cixiong_choice": "residual",
    "pending_weapon_choice": "residual",
    "pending_slash_choice": "residual",
    "pending_discard_two": "residual",
    "pending_hanbing_discard": "residual",
    "pending_zone_choice": "residual",
    "pending_chain": "residual",
    "pending_dying_id": "p1",
    "response_window_id": "x",
    "response_window_order": ("p1",),
    "response_window_source_sequence": 1,
    "rescue_order": ("p1",),
    "rescue_index": 1,
    "rescue_decision_count": 1,
    "trick_effect_active": True,
    "trick_consecutive_passes": 1,
    "trick_response_order": ("p1",),
    "trick_response_index": 1,
    "trick_decision_count": 1,
    "trick_direct_response_to": "x",
    "zone_choice_handles": MappingProxyType({"x": "y"}),
    "zone_choice_snapshot_digest": "x",
    "fire_attack_reveal_handles": MappingProxyType({"x": "y"}),
    "group_response_handles": MappingProxyType({"x": "y"}),
    "group_response_snapshot_digest": "x",
    "borrowed_sword_slash_handles": MappingProxyType({"x": "y"}),
    "borrowed_sword_slash_snapshot_digest": "x",
    "pending_damage_card_id": "x",
    "pending_damage_source_id": "p1",
    "pending_damage_kill_credit": "p1",
    "pending_damage_rescue_reason": "x",
    "pending_damage_death_reason": "x",
    "bagua_attempted": True,
    "defer_damage_card_finish": True,
    "damage_card_already_finished": True,
    "wine_buff_owner_id": "p1",
    "wine_buff_used_this_play_phase": True,
    "skipped_phases": MappingProxyType({"p1": "draw"}),
    "phase_skip_reasons": MappingProxyType({"p1": "x"}),
    "discard_phase_window_id": "x",
    "discard_phase_selected_ids": ("x",),
    "discard_phase_handles": MappingProxyType({"x": "y"}),
    "discard_phase_snapshot_digest": "x",
    "processed_judgment_instance_ids": ("x",),
    "feiyang_window_id": "x",
    "feiyang_handles": MappingProxyType({"x": "y"}),
    "feiyang_snapshot_digest": "x",
    "feiyang_selected_ids": ("x",),
    "feiyang_judgment_choice": "x",
}


def _session(*, seed: int = 2, **kwargs: Any) -> Formal2v2Session:
    return Formal2v2Session(
        seed=seed,
        configuration=Formal2v2Configuration.formal_profile(),
        analysis_only=False,
        **kwargs,
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
    for instance_id in game.state.card_ids_in(ZoneRef.hand(player_id)):
        if game.state.cards_by_id[instance_id].card_key == card_key:
            return instance_id
    raise AssertionError(f"找不到{card_key}")


def _equip_armor(
    game: ProductionBasicCardBatch, player_id: str, card_key: str
) -> str:
    for instance_id in game.state.card_ids_in(DRAW_PILE):
        if game.state.cards_by_id[instance_id].card_key == card_key:
            game._state = game.state.move_card(
                instance_id, ZoneRef.equipment(player_id, "armor")
            )
            return instance_id
    raise AssertionError(f"牌堆中找不到防具{card_key}")


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


def _pass_wuxie(game: ProductionBasicCardBatch) -> None:
    while not game.is_finished:
        action = _op(game, "pass_judgment_wuxie") or _op(
            game, "pass_trick_response"
        )
        if action is None:
            return
        _step(game, action)


def _pass_all_rescues(game: ProductionBasicCardBatch) -> None:
    while game.phase is ProductionPhase.DYING_RESCUE:
        _step(game, _require_op(game, "pass_rescue"))


def _drain_deck_to(game: ProductionBasicCardBatch, count: int) -> None:
    ids = list(game.state.card_ids_in(DRAW_PILE))
    assert len(ids) >= count
    game._state = game.state.move_cards(
        {instance_id: DISCARD_PILE for instance_id in ids[count:]}
    )


def _assert_formal_draw(game: ProductionBasicCardBatch) -> None:
    assert game.is_finished is True
    assert game.winner_id is None
    assert game.runtime.game_over_reason == "2v2_draw_deck_exhausted"
    assert game.phase is ProductionPhase.FINISHED
    assert not game.state.card_ids_in(PROCESSING_ZONE)
    assert not game.state.card_ids_in(REVEALED_ZONE)
    draw_events = [event for event in game.events if event.event_type is EventType.DRAW]
    assert draw_events
    assert draw_events[-1].payload["reason"] == "2v2_draw_deck_exhausted"
    game.assert_finished_state_invariants()


def _dirty_runtime(runtime: _BatchRuntime) -> _BatchRuntime:
    injected = {
        field: _DIRTY_TRANSIENT_SAMPLES.get(field, "residual")
        for field in FINISHED_TRANSIENT_RUNTIME_FIELDS
    }
    return replace(runtime, **injected)


# ----------------------------------------------------------------------
# 1. 摸牌阶段：不足 2 / 恰好耗尽（与 C3 既有口径对齐）
# ----------------------------------------------------------------------


def test_draw_phase_insufficient_is_formal_draw() -> None:
    game = _session(seed=2)
    _drain_deck_to(game, 1)
    hand_before = len(game.state.card_ids_in(ZoneRef.hand("p1")))
    events_before = len(game.events)
    _step(game, _require_op(game, "proceed_prepare"))
    _step(game, _require_op(game, "proceed_judgment"))
    _step(game, _require_op(game, "proceed_draw"))
    _assert_formal_draw(game)
    assert len(game.state.card_ids_in(ZoneRef.hand("p1"))) == hand_before
    assert len(game.state.card_ids_in(DRAW_PILE)) == 1
    new_events = game.events[events_before:]
    assert [event.event_type for event in new_events if event.event_type is EventType.DRAW]


def test_draw_phase_exact_exhaust_is_formal_draw() -> None:
    game = _session(seed=2)
    _drain_deck_to(game, 2)
    hand_before = len(game.state.card_ids_in(ZoneRef.hand("p1")))
    _step(game, _require_op(game, "proceed_prepare"))
    _step(game, _require_op(game, "proceed_judgment"))
    _step(game, _require_op(game, "proceed_draw"))
    _assert_formal_draw(game)
    assert len(game.state.card_ids_in(ZoneRef.hand("p1"))) == hand_before + 2
    assert not game.state.card_ids_in(DRAW_PILE)


# ----------------------------------------------------------------------
# 2–3. 五谷：不足 / 展示后恰好耗尽
# ----------------------------------------------------------------------


def test_wugu_insufficient_is_formal_draw_without_partial_events() -> None:
    game = _session(seed=2)
    _enter_play(game)
    wugu_id = _give_card(game, "p1", WUGU)
    events_before = len(game.events)
    _drain_deck_to(game, 3)
    _step(game, _require_op(game, "use_wugu", card_key=WUGU))
    _assert_formal_draw(game)
    assert game.state.location_of(wugu_id) == ZoneRef.hand("p1")
    new_events = game.events[events_before:]
    assert all(event.event_type is EventType.DRAW for event in new_events)
    assert not any(
        event.payload.get("reason") == "wugu_reveal" for event in new_events
    )


def test_wugu_exact_exhaust_after_reveal_is_formal_draw() -> None:
    game = _session(seed=2)
    _enter_play(game)
    wugu_id = _give_card(game, "p1", WUGU)
    events_before = len(game.events)
    _drain_deck_to(game, 4)
    _step(game, _require_op(game, "use_wugu", card_key=WUGU))
    _assert_formal_draw(game)
    assert game.state.location_of(wugu_id) == DISCARD_PILE
    new_events = game.events[events_before:]
    assert any(event.event_type is EventType.CARD_USED for event in new_events)
    assert any(
        event.payload.get("reason") == "wugu_reveal" for event in new_events
    )
    assert any(event.event_type is EventType.DRAW for event in new_events)
    cleanup = [
        event
        for event in new_events
        if event.payload.get("reason") == "draw_game_over_cleanup"
    ]
    assert cleanup
    revealed_cleanup = [
        event
        for event in cleanup
        if event.payload.get("source", {}).get("kind") == "revealed"
    ]
    assert revealed_cleanup
    assert all(
        event.payload.get("destination", {}).get("kind") == "discard_pile"
        for event in revealed_cleanup
    )


# ----------------------------------------------------------------------
# 4. 延时锦囊判定：开始时 0 / 取走最后 1 张
# ----------------------------------------------------------------------


def _start_p2_lebusi_judgment(game: ProductionBasicCardBatch) -> None:
    _enter_play(game)
    _give_card(game, "p1", LEBUSI)
    _step(game, _require_op(game, "use_lebusi", targets=("p2",)))
    _end_turn(game)
    _step(game, _require_op(game, "proceed_prepare"))
    _step(game, _require_op(game, "proceed_judgment"))
    assert game.runtime.pending_judgment is not None


def test_delayed_judgment_empty_deck_is_formal_draw() -> None:
    game = _session(seed=2)
    _start_p2_lebusi_judgment(game)
    _drain_deck_to(game, 0)
    _pass_wuxie(game)
    _assert_formal_draw(game)
    assert game.runtime.pending_judgment is None
    assert game.runtime.processed_judgment_instance_ids == ()


def test_delayed_judgment_takes_last_card_is_formal_draw() -> None:
    game = _session(seed=2)
    _start_p2_lebusi_judgment(game)
    _drain_deck_to(game, 1)
    _pass_wuxie(game)
    _assert_formal_draw(game)
    assert game.runtime.pending_judgment is None
    assert game.runtime.processed_judgment_instance_ids == ()


# ----------------------------------------------------------------------
# 5. 无中：无酒不足/取尽；本回合用酒后取尽
# ----------------------------------------------------------------------


def test_wuzhong_insufficient_is_formal_draw() -> None:
    game = _session(seed=2)
    _enter_play(game)
    _give_card(game, "p1", WUZHONG)
    _drain_deck_to(game, 1)
    _step(game, _require_op(game, "use_wuzhong", card_key=WUZHONG))
    _pass_wuxie(game)
    _assert_formal_draw(game)


def test_wuzhong_exact_exhaust_is_formal_draw() -> None:
    game = _session(seed=2)
    _enter_play(game)
    _give_card(game, "p1", WUZHONG)
    _drain_deck_to(game, 2)
    _step(game, _require_op(game, "use_wuzhong", card_key=WUZHONG))
    _pass_wuxie(game)
    _assert_formal_draw(game)


def test_wuzhong_after_wine_clears_wine_buff() -> None:
    game = _session(seed=2)
    _enter_play(game)
    _give_card(game, "p1", JIU)
    _give_card(game, "p1", WUZHONG)
    _step(game, _require_op(game, "use_wine_buff", card_key=JIU))
    assert game.runtime.wine_buff_owner_id == "p1"
    assert game.runtime.wine_buff_used_this_play_phase is True
    _drain_deck_to(game, 2)
    _step(game, _require_op(game, "use_wuzhong", card_key=WUZHONG))
    _pass_wuxie(game)
    _assert_formal_draw(game)
    assert game.runtime.wine_buff_owner_id is None
    assert game.runtime.wine_buff_used_this_play_phase is False


# ----------------------------------------------------------------------
# 6. 铁索重铸：无酒不足/取尽；有酒取尽
# ----------------------------------------------------------------------


def test_tiesuo_recast_insufficient_is_formal_draw() -> None:
    game = _session(seed=2)
    _enter_play(game)
    tiesuo_id = _give_card(game, "p1", TIESUO)
    _drain_deck_to(game, 0)
    _step(game, _require_op(game, "recast_tiesuo"))
    _assert_formal_draw(game)
    assert game.state.location_of(tiesuo_id) == ZoneRef.hand("p1")


def test_tiesuo_recast_exact_exhaust_is_formal_draw() -> None:
    game = _session(seed=2)
    _enter_play(game)
    tiesuo_id = _give_card(game, "p1", TIESUO)
    _drain_deck_to(game, 1)
    _step(game, _require_op(game, "recast_tiesuo"))
    _assert_formal_draw(game)
    assert game.state.location_of(tiesuo_id) == DISCARD_PILE


def test_tiesuo_recast_after_wine_clears_wine_buff() -> None:
    game = _session(seed=2)
    _enter_play(game)
    _give_card(game, "p1", JIU)
    _give_card(game, "p1", TIESUO)
    _step(game, _require_op(game, "use_wine_buff", card_key=JIU))
    assert game.runtime.wine_buff_used_this_play_phase is True
    _drain_deck_to(game, 1)
    _step(game, _require_op(game, "recast_tiesuo"))
    _assert_formal_draw(game)
    assert game.runtime.wine_buff_owner_id is None
    assert game.runtime.wine_buff_used_this_play_phase is False


# ----------------------------------------------------------------------
# 7. 死亡奖励：无酒不足/取尽；酒后击杀再奖励取尽
# ----------------------------------------------------------------------


def test_death_reward_insufficient_is_formal_draw() -> None:
    game = _session(seed=2)
    _enter_play(game)
    _strip_hand(game, "p2")
    game._state = _replace_player(game.state, "p2", hp=1)
    _give_card(game, "p1", SHA)
    _drain_deck_to(game, 0)
    _step(game, _require_op(game, "use_slash", targets=("p2",)))
    _step(game, _require_op(game, "pass_slash_response"))
    _pass_all_rescues(game)
    _assert_formal_draw(game)
    assert game.state.players_by_id["p2"].alive is False


def test_death_reward_exact_exhaust_is_formal_draw() -> None:
    game = _session(seed=2)
    _enter_play(game)
    _strip_hand(game, "p2")
    game._state = _replace_player(game.state, "p2", hp=1)
    _give_card(game, "p1", SHA)
    _drain_deck_to(game, 1)
    p3_before = len(game.state.card_ids_in(ZoneRef.hand("p3")))
    _step(game, _require_op(game, "use_slash", targets=("p2",)))
    _step(game, _require_op(game, "pass_slash_response"))
    _pass_all_rescues(game)
    _assert_formal_draw(game)
    assert game.state.players_by_id["p2"].alive is False
    assert len(game.state.card_ids_in(ZoneRef.hand("p3"))) == p3_before + 1


def test_death_reward_after_wine_kill_clears_wine_fields() -> None:
    game = _session(seed=2)
    _enter_play(game)
    _strip_hand(game, "p2")
    game._state = _replace_player(game.state, "p2", hp=1)
    _give_card(game, "p1", JIU)
    _give_card(game, "p1", SHA)
    _step(game, _require_op(game, "use_wine_buff", card_key=JIU))
    assert game.runtime.wine_buff_used_this_play_phase is True
    _drain_deck_to(game, 1)
    _step(game, _require_op(game, "use_slash", targets=("p2",)))
    _step(game, _require_op(game, "pass_slash_response"))
    _pass_all_rescues(game)
    _assert_formal_draw(game)
    assert game.runtime.wine_buff_owner_id is None
    assert game.runtime.wine_buff_used_this_play_phase is False


# ----------------------------------------------------------------------
# 8. 八卦：不足 1 / 取最后 1 张
# ----------------------------------------------------------------------


def _start_p2_bagua_response(game: ProductionBasicCardBatch) -> None:
    _enter_play(game)
    _equip_armor(game, "p2", BAGUA)
    _strip_hand(game, "p2")
    _give_card(game, "p1", SHA)
    _step(game, _require_op(game, "use_slash", targets=("p2",)))
    assert _op(game, "activate_bagua") is not None


def test_bagua_insufficient_is_formal_draw() -> None:
    game = _session(seed=2)
    _start_p2_bagua_response(game)
    _drain_deck_to(game, 0)
    _step(game, _require_op(game, "activate_bagua"))
    _assert_formal_draw(game)


def test_bagua_takes_last_card_is_formal_draw() -> None:
    game = _session(seed=2)
    _start_p2_bagua_response(game)
    _drain_deck_to(game, 1)
    _step(game, _require_op(game, "activate_bagua"))
    _assert_formal_draw(game)


# ----------------------------------------------------------------------
# 9. run() 公共 API 必须能返回正式平局
# ----------------------------------------------------------------------


def test_run_returns_formal_draw_result() -> None:
    game = _session(seed=2)
    _drain_deck_to(game, 2)
    result = game.run(BatchReferenceController(), max_steps=20)
    assert result.winner_id is None
    assert result.finish_reason == "2v2_draw_deck_exhausted"
    assert game.runtime.game_over_reason == "2v2_draw_deck_exhausted"
    game.assert_finished_state_invariants()


def test_two_player_run_still_requires_winner() -> None:
    game = ProductionBasicCardBatch(
        seed=1, player_hp=(4, 4), player_max_hp=(4, 4)
    )
    game._runtime = replace(
        game.runtime, phase=ProductionPhase.FINISHED, winner_id=None
    )
    with pytest.raises(ProductionBatchError, match="必须有胜者"):
        game.run(max_steps=1)


# ----------------------------------------------------------------------
# 10. 复杂平局场景：record → reexecute 严格往返
# ----------------------------------------------------------------------


class _ComplexDrawController:
    """优先打出非伤害耗牌动作，把对局推到牌堆耗尽平局。"""

    strategy_version = "c123-complex-draw-controller.v1"

    def choose(self, legal_actions: Any, context: Any) -> LegalAction:
        operations = [
            str(action.payload.get("operation", "")) for action in legal_actions
        ]
        priority_order = (
            "feiyang_decline",
            "proceed_prepare",
            "proceed_judgment",
            "proceed_draw",
            "pick_wugu_card",
            "use_wugu",
            "use_wuzhong",
            "recast_tiesuo",
            "use_lebusi",
            "use_bingliang",
            "heal_self",
            "end_play_phase",
            "discard_phase_submit",
            "select_discard_card",
            "end_turn",
            "pass_judgment_wuxie",
            "pass_trick_response",
            "pass_nanman_slash",
            "pass_wanjian_jink",
            "pass_slash_response",
            "pass_rescue",
        )
        for wanted in priority_order:
            if wanted in operations:
                return next(
                    action
                    for action in legal_actions
                    if action.payload.get("operation") == wanted
                )
        raise AssertionError(
            f"阶段{getattr(context, 'phase', '')!r}没有可脚本化操作：{operations}"
        )


def test_complex_draw_replay_roundtrip() -> None:
    record = record_reference_formal_2v2(
        11,
        configuration=Formal2v2Configuration.formal_profile(),
        analysis_only=False,
        controller=_ComplexDrawController(),
        max_steps=6000,
    )
    assert record.outcome["winner_id"] is None
    assert record.outcome["finish_reason"] == "2v2_draw_deck_exhausted"
    result = reexecute_production_replay(record)
    assert result.verified is True
    assert result.winner_id is None
    assert result.decision_count == record.outcome["decision_count"]


# ----------------------------------------------------------------------
# 11. FINISHED_TRANSIENT_RUNTIME_FIELDS 防漂移
# ----------------------------------------------------------------------


def test_finished_transient_cleanup_values_match_inventory() -> None:
    assert set(finished_transient_cleanup_values()) == set(
        FINISHED_TRANSIENT_RUNTIME_FIELDS
    )


def test_draw_finish_clears_entire_injected_inventory() -> None:
    """修复不能只清当前已观察字段；inventory 新增字段必须被同一 primitive 清掉。

    对象型 pending_* 不能经 ``_context()`` 注入后再 enumerate，因此先用
    真实 enumerate/step 走到摸牌不足这一 sibling 路径，再把脏 inventory
    交给 step() 在 ``_DeckExhaustedDraw`` 时调用的同一
    ``_finish_game_as_draw``。
    """

    game = _session(seed=2)
    _drain_deck_to(game, 1)
    _step(game, _require_op(game, "proceed_prepare"))
    _step(game, _require_op(game, "proceed_judgment"))
    action = _require_op(game, "proceed_draw")
    assert action.payload.get("operation") == "proceed_draw"
    dirty = _dirty_runtime(game.runtime)
    leftover_before = [
        field
        for field in sorted(FINISHED_TRANSIENT_RUNTIME_FIELDS)
        if getattr(dirty, field) not in (None, (), {}, 0, False)
        and not (isinstance(getattr(dirty, field), str) and getattr(dirty, field) == "")
    ]
    assert leftover_before == sorted(FINISHED_TRANSIENT_RUNTIME_FIELDS)
    next_state, next_runtime = game._finish_game_as_draw(game.state, dirty)
    game._state = next_state
    game._commit_runtime(game.runtime, next_runtime)
    _assert_formal_draw(game)


def test_cleanup_primitive_clears_each_inventory_field() -> None:
    game = _session(seed=2)
    cleaned = cleanup_finished_transient_runtime(_dirty_runtime(game.runtime))
    leftover = []
    for field in sorted(FINISHED_TRANSIENT_RUNTIME_FIELDS):
        value = getattr(cleaned, field)
        if value in (None, (), {}, 0, False) or (
            isinstance(value, str) and value == ""
        ):
            continue
        leftover.append(field)
    assert leftover == []
    assert cleaned.phase is game.runtime.phase
    assert cleaned.current_player_id == game.runtime.current_player_id
