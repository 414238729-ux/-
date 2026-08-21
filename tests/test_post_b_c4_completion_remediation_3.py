# -*- coding: utf-8 -*-
"""POST-B C4 completion remediation 3：C4-COMPLETION-001 / 002 回归。

C4-COMPLETION-001：借刀杀人 forced Fire Slash 命中连环农民后，chain child
非终局死亡不得对借刀根做 jiedaosharen_victory_cleanup；奖励窗口结束后
parent 只能完成一次。

C4-COMPLETION-002：当前回合农民闪电正式命中并非终局死亡时，不得在
DEATH / PEASANT_REWARD_CHOICE 之前 shandian_victory_cleanup；pending_judgment
必须与实体根 zone 一致。
"""

from __future__ import annotations

from dataclasses import replace
from types import MappingProxyType
from typing import Any

import pytest

from scripts.sgs_engine.actions import LegalAction
from scripts.sgs_engine.events import EventType
from scripts.sgs_engine.mode_doudizhu import (
    FormalDoudizhuConfiguration,
    FormalDoudizhuSession,
)
from scripts.sgs_engine.model import (
    DISCARD_PILE,
    DRAW_PILE,
    PROCESSING_ZONE,
    ZoneRef,
)
from scripts.sgs_engine.production_batch import (
    BatchActionIdController,
    ProductionBasicCardBatch,
    ProductionBatchError,
    ProductionPhase,
    _replace_player,
)


JIEDAO = "sgs_trick_jiedaosharen"
HUOSHA = "sgs_basic_huosha"
QINGGANG = "sgs_weapon_qinggangjian"
SHANDIAN = "sgs_delayed_shandian"
TAO = "sgs_basic_tao"
SHAN = "sgs_basic_shan"
JIU = "sgs_basic_jiu"
RESCUE_OR_DODGE_KEYS = frozenset({TAO, SHAN, JIU})
SPADE_SUITS = frozenset({"♠", "spade", "黑桃"})
SPADE_HIT_RANKS = frozenset({"2", "3", "4", "5", "6", "7", "8", "9"})


def _session(seed: int = 201) -> FormalDoudizhuSession:
    return FormalDoudizhuSession(
        seed=seed,
        configuration=FormalDoudizhuConfiguration.formal_profile(),
        session_id=f"test-c4-completion-rem3-{seed}",
    )


def _op(
    game: ProductionBasicCardBatch, operation: str, **filters: Any
) -> LegalAction | None:
    for action in game.legal_actions():
        if action.payload.get("operation") != operation:
            continue
        matched = True
        for key, value in filters.items():
            if key == "targets":
                if tuple(action.target_ids) != tuple(value):
                    matched = False
                    break
            elif action.payload.get(key) != value:
                matched = False
                break
        if matched:
            return action
    return None


def _require_op(
    game: ProductionBasicCardBatch, operation: str, **filters: Any
) -> LegalAction:
    action = _op(game, operation, **filters)
    assert action is not None, (
        f"缺少操作 {operation!r}（当前合法操作："
        f"{[a.payload.get('operation') for a in game.legal_actions()]}）"
    )
    return action


def _step(game: ProductionBasicCardBatch, action: LegalAction) -> None:
    game.step(BatchActionIdController(action.action_id))


def _strip_hand(game: ProductionBasicCardBatch, player_id: str) -> None:
    for instance_id in tuple(game.state.card_ids_in(ZoneRef.hand(player_id))):
        game._state = game.state.move_card(instance_id, DISCARD_PILE)


def _find_card(game: ProductionBasicCardBatch, card_key: str) -> str:
    for player in game.state.players:
        for instance_id in game.state.card_ids_in(
            ZoneRef.hand(player.player_id)
        ):
            if game.state.cards_by_id[instance_id].card_key == card_key:
                return instance_id
        for slot in (
            "weapon",
            "armor",
            "attack_horse",
            "defense_horse",
            "treasure",
        ):
            for instance_id in game.state.card_ids_in(
                ZoneRef.equipment(player.player_id, slot)
            ):
                if game.state.cards_by_id[instance_id].card_key == card_key:
                    return instance_id
        for instance_id in game.state.card_ids_in(
            ZoneRef.judgment(player.player_id)
        ):
            if game.state.cards_by_id[instance_id].card_key == card_key:
                return instance_id
    for zone in (DRAW_PILE, DISCARD_PILE, PROCESSING_ZONE):
        for instance_id in game.state.card_ids_in(zone):
            if game.state.cards_by_id[instance_id].card_key == card_key:
                return instance_id
    raise AssertionError(f"找不到{card_key}")


def _give_card(
    game: ProductionBasicCardBatch, player_id: str, card_key: str
) -> str:
    instance_id = _find_card(game, card_key)
    if game.state.location_of(instance_id) != ZoneRef.hand(player_id):
        game._state = game.state.move_card(
            instance_id, ZoneRef.hand(player_id)
        )
    return instance_id


def _equip_weapon(
    game: ProductionBasicCardBatch, player_id: str, card_key: str
) -> str:
    instance_id = _find_card(game, card_key)
    destination = ZoneRef.equipment(player_id, "weapon")
    if game.state.location_of(instance_id) != destination:
        game._state = game.state.move_card(instance_id, destination)
    return instance_id


def _enter_play(game: ProductionBasicCardBatch) -> None:
    for operation in ("proceed_prepare", "proceed_judgment", "proceed_draw"):
        _step(game, _require_op(game, operation))


def _end_current_turn(game: ProductionBasicCardBatch) -> None:
    assert game.phase is ProductionPhase.PLAY
    _step(game, _require_op(game, "end_play_phase"))
    while game.phase is ProductionPhase.DISCARD:
        submit = _op(game, "discard_phase_submit")
        if submit is not None:
            _step(game, submit)
        else:
            _step(game, _require_op(game, "select_discard_card"))
    _step(game, _require_op(game, "end_turn"))


def _pass_all_rescues(game: ProductionBasicCardBatch) -> None:
    while game.phase is ProductionPhase.DYING_RESCUE:
        _step(game, _require_op(game, "pass_rescue"))


def _pass_trick_window(game: ProductionBasicCardBatch) -> None:
    while game.phase is ProductionPhase.TRICK_RESPONSE:
        _step(game, _require_op(game, "pass_trick_response"))


def _pass_judgment_wuxie(game: ProductionBasicCardBatch) -> None:
    while game.phase in (
        ProductionPhase.JUDGMENT_WUXIE,
        ProductionPhase.TRICK_RESPONSE,
    ):
        op = (
            "pass_judgment_wuxie"
            if _op(game, "pass_judgment_wuxie") is not None
            else "pass_trick_response"
        )
        _step(game, _require_op(game, op))


def _strip_rescue_and_dodge(game: ProductionBasicCardBatch) -> None:
    for player in game.state.players:
        for instance_id in tuple(
            game.state.card_ids_in(ZoneRef.hand(player.player_id))
        ):
            if game.state.cards_by_id[instance_id].card_key in (
                RESCUE_OR_DODGE_KEYS
            ):
                game._state = game.state.move_card(instance_id, DISCARD_PILE)


def _drain_deck_to(game: ProductionBasicCardBatch, count: int) -> None:
    ids = list(game.state.card_ids_in(DRAW_PILE))
    assert len(ids) >= count
    game._state = game.state.move_cards(
        {instance_id: DISCARD_PILE for instance_id in ids[count:]}
    )


def _put_spade_hit_on_draw_top(game: ProductionBasicCardBatch) -> None:
    draw_cards = list(game.state.card_ids_in(DRAW_PILE))
    spade_card = next(
        cid
        for cid in draw_cards
        if game.state.cards_by_id[cid].suit in SPADE_SUITS
        and game.state.cards_by_id[cid].rank in SPADE_HIT_RANKS
    )
    others = [cid for cid in draw_cards if cid != spade_card]
    game._state = game.state.reorder_zone(
        DRAW_PILE, (spade_card, *others)
    )


def _place_lightning(
    game: ProductionBasicCardBatch, player_id: str
) -> str:
    lightning_id = _give_card(game, player_id, SHANDIAN)
    game._state = game.state.move_card(
        lightning_id, ZoneRef.judgment(player_id)
    )
    entry_index = game.runtime.judgment_entry_counter + 1
    game._runtime = replace(
        game.runtime,
        judgment_entry_indices=MappingProxyType(
            {
                **game.runtime.judgment_entry_indices,
                lightning_id: entry_index,
            }
        ),
        judgment_entry_counter=max(
            game.runtime.judgment_entry_counter, entry_index
        ),
    )
    return lightning_id


def _processing_to_discard(
    game: ProductionBasicCardBatch, instance_id: str
) -> list[object]:
    return [
        event
        for event in game.events
        if event.event_type is EventType.CARD_MOVED
        and event.card_instance_id == instance_id
        and event.payload.get("source", {}).get("kind") == "processing"
        and event.payload.get("destination", {}).get("kind")
        == "discard_pile"
    ]


def _event_reasons(game: ProductionBasicCardBatch) -> list[object]:
    return [event.payload.get("reason") for event in game.events]


def _event_index(
    game: ProductionBasicCardBatch, predicate: Any
) -> int:
    for index, event in enumerate(game.events):
        if predicate(event):
            return index
    raise AssertionError("找不到满足条件的事件")


def _assert_borrowed_root_ownership(
    game: ProductionBasicCardBatch, root_id: str
) -> None:
    pending = game.runtime.pending_borrowed_sword
    assert pending is not None
    assert pending.trick_instance_id == root_id
    if pending.root_discarded is False:
        assert game.state.location_of(root_id) == PROCESSING_ZONE
        assert "jiedaosharen_victory_cleanup" not in _event_reasons(game)


def _assert_lightning_root_ownership(
    game: ProductionBasicCardBatch, lightning_id: str
) -> None:
    pending = game.runtime.pending_judgment
    assert pending is not None
    assert pending.trick_instance_id == lightning_id
    assert pending.stage == "resolving_effect"
    if pending.cleanup_done is False:
        assert game.state.location_of(lightning_id) == PROCESSING_ZONE
        assert "shandian_victory_cleanup" not in _event_reasons(game)
        assert all(
            event.payload.get("game_over_cleanup") is not True
            for event in game.events
            if event.card_instance_id == lightning_id
        )


def _open_borrowed_fire_slash_chain_child_reward(
    game: ProductionBasicCardBatch,
    *,
    p2_hp: int = 1,
    p3_hp: int = 4,
) -> str:
    """借刀 → p2 强制火杀 p3 → p3 存活 → p2 被传导非终局死亡 → 奖励窗口。"""

    _enter_play(game)
    _strip_rescue_and_dodge(game)
    _strip_hand(game, "p1")
    _strip_hand(game, "p2")
    _strip_hand(game, "p3")
    jiedao_id = _give_card(game, "p1", JIEDAO)
    _equip_weapon(game, "p2", QINGGANG)
    _give_card(game, "p2", HUOSHA)
    game._state = _replace_player(
        game.state, "p1", chained=False, hp=5
    )
    game._state = _replace_player(
        game.state, "p2", chained=True, hp=p2_hp
    )
    game._state = _replace_player(
        game.state, "p3", chained=True, hp=p3_hp
    )
    _step(
        game,
        _require_op(
            game,
            "use_jiedao",
            targets=("p2",),
            second_target_id="p3",
        ),
    )
    _pass_trick_window(game)
    _step(game, _require_op(game, "choose_borrowed_sword_slash"))
    _step(game, _require_op(game, "pass_slash_response"))
    _pass_all_rescues(game)
    assert game.phase is ProductionPhase.PEASANT_REWARD_CHOICE
    assert game.is_finished is False
    _assert_borrowed_root_ownership(game, jiedao_id)
    assert game.runtime.pending_chain is not None
    game.assert_resolution_invariants()
    return jiedao_id


def _advance_to_peasant_prepare(game: ProductionBasicCardBatch) -> None:
    _enter_play(game)
    _end_current_turn(game)
    assert game.current_player_id == "p2"
    assert game.phase is ProductionPhase.PREPARE


def _open_lightning_current_peasant_reward(
    game: ProductionBasicCardBatch,
    *,
    hp: int = 2,
    p3_hp: int | None = None,
) -> str:
    """当前回合农民判定闪电命中自己，救援失败，非终局死亡并打开奖励。"""

    _advance_to_peasant_prepare(game)
    _strip_rescue_and_dodge(game)
    _strip_hand(game, "p2")
    lightning_id = _place_lightning(game, "p2")
    game._state = _replace_player(game.state, "p2", hp=hp)
    if p3_hp is not None:
        game._state = _replace_player(game.state, "p3", hp=p3_hp)
    _step(game, _require_op(game, "proceed_prepare"))
    assert game.phase is ProductionPhase.JUDGMENT
    _put_spade_hit_on_draw_top(game)
    _step(game, _require_op(game, "proceed_judgment"))
    _pass_judgment_wuxie(game)
    assert game.phase is ProductionPhase.DYING_RESCUE
    _assert_lightning_root_ownership(game, lightning_id)
    _pass_all_rescues(game)
    assert game.phase is ProductionPhase.PEASANT_REWARD_CHOICE
    assert game.current_actor_id == "p3"
    assert game.state.players_by_id["p2"].alive is False
    assert game.state.players_by_id["p3"].alive is True
    assert any(event.event_type is EventType.DEATH for event in game.events)
    _assert_lightning_root_ownership(game, lightning_id)
    assert game.runtime.deferred_turn_end_after_owner_death is True
    game.assert_resolution_invariants()
    return lightning_id


# ----------------------------------------------------------------------
# C4-COMPLETION-001
# ----------------------------------------------------------------------


def test_borrowed_fire_slash_chain_child_death_reward_decline_resumes_parent() -> None:
    game = _session(seed=201)
    jiedao_id = _open_borrowed_fire_slash_chain_child_reward(game)
    assert game.current_actor_id == "p3"
    assert game.state.players_by_id["p2"].alive is False
    assert game.state.players_by_id["p3"].alive is True
    decline = _require_op(game, "peasant_reward_decline")
    _step(game, decline)
    assert game.runtime.pending_peasant_reward is None
    assert game.runtime.pending_chain is None
    assert game.runtime.pending_borrowed_sword is None
    assert game.state.location_of(jiedao_id) == DISCARD_PILE
    assert len(_processing_to_discard(game, jiedao_id)) == 1
    assert _event_reasons(game).count("jiedaosharen_fulfilled") == 1
    assert "jiedaosharen_victory_cleanup" not in _event_reasons(game)
    finished = [
        event
        for event in game.events
        if event.event_type is EventType.CHAIN_DAMAGE_FINISHED
    ]
    assert len(finished) == 1
    assert game.phase is ProductionPhase.PLAY
    assert game.current_player_id == "p1"
    assert not game.state.card_ids_in(PROCESSING_ZONE)
    game.assert_resolution_invariants()
    event_count = len(game.events)
    execution_hash = game.execution_hash
    finished_count = len(finished)
    root_moves = len(_processing_to_discard(game, jiedao_id))
    with pytest.raises(ProductionBatchError):
        _step(game, decline)
    assert len(game.events) == event_count
    assert game.execution_hash == execution_hash
    assert (
        len(
            [
                event
                for event in game.events
                if event.event_type is EventType.CHAIN_DAMAGE_FINISHED
            ]
        )
        == finished_count
    )
    assert len(_processing_to_discard(game, jiedao_id)) == root_moves


def test_borrowed_fire_slash_chain_child_death_reward_recover() -> None:
    game = _session(seed=202)
    jiedao_id = _open_borrowed_fire_slash_chain_child_reward(
        game, p3_hp=3
    )
    assert game.state.players_by_id["p3"].hp == 2
    _step(game, _require_op(game, "peasant_reward_recover_hp"))
    assert game.state.players_by_id["p3"].hp == 3
    assert game.runtime.pending_borrowed_sword is None
    assert len(_processing_to_discard(game, jiedao_id)) == 1
    assert _event_reasons(game).count("jiedaosharen_fulfilled") == 1
    assert game.phase is ProductionPhase.PLAY
    assert game.current_player_id == "p1"
    assert any(
        event.event_type is EventType.HP_RECOVER
        and event.payload.get("reason") == "peasant_death_reward"
        for event in game.events
    )


def test_borrowed_fire_slash_chain_child_death_reward_draw_two() -> None:
    game = _session(seed=203)
    jiedao_id = _open_borrowed_fire_slash_chain_child_reward(game)
    hand_before = len(game.state.card_ids_in(ZoneRef.hand("p3")))
    _step(game, _require_op(game, "peasant_reward_draw_two"))
    assert len(game.state.card_ids_in(ZoneRef.hand("p3"))) == hand_before + 2
    assert game.is_finished is False
    assert game.runtime.pending_borrowed_sword is None
    assert len(_processing_to_discard(game, jiedao_id)) == 1
    assert game.phase is ProductionPhase.PLAY
    assert game.current_player_id == "p1"


def test_borrowed_fire_slash_chain_child_death_reward_draw_exhaustion() -> None:
    game = _session(seed=204)
    jiedao_id = _open_borrowed_fire_slash_chain_child_reward(game)
    death_index = _event_index(
        game, lambda event: event.event_type is EventType.DEATH
    )
    _drain_deck_to(game, 2)
    _step(game, _require_op(game, "peasant_reward_draw_two"))
    assert game.is_finished is True
    assert game.winner_id is None
    assert game.runtime.game_over_reason == "doudizhu_draw_deck_exhausted"
    assert game.runtime.pending_borrowed_sword is None
    assert game.runtime.pending_chain is None
    assert not game.state.card_ids_in(PROCESSING_ZONE)
    assert not any(
        event.event_type is EventType.VICTORY for event in game.events
    )
    reward_index = _event_index(
        game,
        lambda event: event.event_type is EventType.CARD_GAINED
        and event.payload.get("reason") == "death_reward_peasant_draw",
    )
    cleanup_index = _event_index(
        game,
        lambda event: event.event_type is EventType.CARD_MOVED
        and event.card_instance_id == jiedao_id
        and event.payload.get("source", {}).get("kind") == "processing"
        and event.payload.get("destination", {}).get("kind")
        == "discard_pile",
    )
    assert death_index < reward_index < cleanup_index
    assert any(event.event_type is EventType.DRAW for event in game.events)
    assert game.phase is ProductionPhase.FINISHED
    assert len(_processing_to_discard(game, jiedao_id)) == 1
    game.assert_finished_state_invariants()


def test_borrowed_fire_slash_second_peasant_death_landlord_victory() -> None:
    game = _session(seed=205)
    jiedao_id = _open_borrowed_fire_slash_chain_child_reward(
        game, p2_hp=1, p3_hp=1
    )
    # p3 是火杀原目标且体力为 1 时，先非终局死亡；奖励给 p2。
    assert game.state.players_by_id["p3"].alive is False
    assert game.runtime.pending_peasant_reward.dead_peasant_id == "p3"
    assert game.current_actor_id == "p2"
    _assert_borrowed_root_ownership(game, jiedao_id)
    _step(game, _require_op(game, "peasant_reward_decline"))
    if game.phase is ProductionPhase.DYING_RESCUE:
        _pass_all_rescues(game)
    assert game.is_finished is True
    assert game.winner_id == "landlord"
    assert game.runtime.pending_borrowed_sword is None
    assert game.runtime.pending_chain is None
    assert not game.state.card_ids_in(PROCESSING_ZONE)
    assert len(_processing_to_discard(game, jiedao_id)) == 1
    assert any(event.event_type is EventType.VICTORY for event in game.events)
    game.assert_finished_state_invariants()


# ----------------------------------------------------------------------
# C4-COMPLETION-002
# ----------------------------------------------------------------------


def test_lightning_current_peasant_death_reward_decline_root_cleanup_order() -> None:
    game = _session(seed=211)
    lightning_id = _open_lightning_current_peasant_reward(game)
    death_index = _event_index(
        game, lambda event: event.event_type is EventType.DEATH
    )
    _step(game, _require_op(game, "peasant_reward_decline"))
    assert "shandian_victory_cleanup" not in _event_reasons(game)
    assert _event_reasons(game).count("shandian_resolved") == 1
    assert len(_processing_to_discard(game, lightning_id)) == 1
    assert game.runtime.pending_judgment is None
    assert game.state.location_of(lightning_id) == DISCARD_PILE
    cleanup_index = _event_index(
        game,
        lambda event: event.event_type is EventType.CARD_MOVED
        and event.card_instance_id == lightning_id
        and event.payload.get("reason") == "shandian_resolved",
    )
    assert death_index < cleanup_index
    assert game.current_player_id == "p3"
    assert game.phase is ProductionPhase.PREPARE
    assert game.runtime.deferred_turn_end_after_owner_death is False
    game.assert_resolution_invariants()


def test_lightning_current_peasant_death_reward_recover() -> None:
    game = _session(seed=212)
    lightning_id = _open_lightning_current_peasant_reward(game, p3_hp=2)
    death_index = _event_index(
        game, lambda event: event.event_type is EventType.DEATH
    )
    _step(game, _require_op(game, "peasant_reward_recover_hp"))
    recover_index = _event_index(
        game,
        lambda event: event.event_type is EventType.HP_RECOVER
        and event.payload.get("reason") == "peasant_death_reward",
    )
    cleanup_index = _event_index(
        game,
        lambda event: event.event_type is EventType.CARD_MOVED
        and event.card_instance_id == lightning_id
        and event.payload.get("reason") == "shandian_resolved",
    )
    assert death_index < recover_index < cleanup_index
    assert game.state.players_by_id["p3"].hp == 3
    assert game.runtime.pending_judgment is None
    assert len(_processing_to_discard(game, lightning_id)) == 1
    assert game.current_player_id == "p3"
    assert game.phase is ProductionPhase.PREPARE


def test_lightning_current_peasant_death_reward_draw_exhaustion() -> None:
    game = _session(seed=213)
    lightning_id = _open_lightning_current_peasant_reward(game)
    death_index = _event_index(
        game, lambda event: event.event_type is EventType.DEATH
    )
    _drain_deck_to(game, 2)
    _step(game, _require_op(game, "peasant_reward_draw_two"))
    assert game.is_finished is True
    assert game.winner_id is None
    assert game.runtime.game_over_reason == "doudizhu_draw_deck_exhausted"
    assert game.runtime.pending_judgment is None
    assert not game.state.card_ids_in(PROCESSING_ZONE)
    assert "shandian_victory_cleanup" not in _event_reasons(game)
    assert not any(
        event.event_type is EventType.VICTORY for event in game.events
    )
    reward_index = _event_index(
        game,
        lambda event: event.event_type is EventType.CARD_GAINED
        and event.payload.get("reason") == "death_reward_peasant_draw",
    )
    cleanup_index = _event_index(
        game,
        lambda event: event.event_type is EventType.CARD_MOVED
        and event.card_instance_id == lightning_id
        and event.payload.get("source", {}).get("kind") == "processing"
        and event.payload.get("destination", {}).get("kind")
        == "discard_pile",
    )
    assert death_index < reward_index < cleanup_index
    assert any(event.event_type is EventType.DRAW for event in game.events)
    assert game.phase is ProductionPhase.FINISHED
    assert len(_processing_to_discard(game, lightning_id)) == 1
    game.assert_finished_state_invariants()


def test_lightning_current_peasant_successful_rescue_completes_root() -> None:
    game = _session(seed=214)
    _advance_to_peasant_prepare(game)
    _strip_rescue_and_dodge(game)
    _strip_hand(game, "p2")
    lightning_id = _place_lightning(game, "p2")
    game._state = _replace_player(game.state, "p2", hp=3)
    _step(game, _require_op(game, "proceed_prepare"))
    _put_spade_hit_on_draw_top(game)
    _step(game, _require_op(game, "proceed_judgment"))
    _pass_judgment_wuxie(game)
    assert game.phase is ProductionPhase.DYING_RESCUE
    _assert_lightning_root_ownership(game, lightning_id)
    rescuer = game.runtime.rescue_order[game.runtime.rescue_index]
    _give_card(game, rescuer, TAO)
    _step(game, _require_op(game, "rescue_with_peach"))
    assert game.state.players_by_id["p2"].alive is True
    assert game.state.players_by_id["p2"].hp >= 1
    assert game.phase is not ProductionPhase.PEASANT_REWARD_CHOICE
    assert game.runtime.pending_peasant_reward is None
    assert "shandian_victory_cleanup" not in _event_reasons(game)
    assert _event_reasons(game).count("shandian_resolved") == 1
    assert len(_processing_to_discard(game, lightning_id)) == 1
    assert game.runtime.pending_judgment is None
    assert game.current_player_id == "p2"
    assert game.phase in (ProductionPhase.JUDGMENT, ProductionPhase.DRAW)
    if game.phase is ProductionPhase.JUDGMENT:
        _step(game, _require_op(game, "proceed_judgment"))
    assert game.phase is ProductionPhase.DRAW
    _step(game, _require_op(game, "proceed_draw"))
    assert game.phase is ProductionPhase.PLAY


def test_lightning_chain_child_death_keeps_pending_judgment_f005_adjacent() -> None:
    game = _session(seed=215)
    assert game.current_player_id == "p1"
    lightning_id = _place_lightning(game, "p1")
    game._state = _replace_player(game.state, "p1", chained=True, hp=5)
    game._state = _replace_player(game.state, "p2", chained=True, hp=1)
    game._state = _replace_player(game.state, "p3", chained=True, hp=4)
    _strip_rescue_and_dodge(game)
    _step(game, _require_op(game, "proceed_prepare"))
    if game.phase is ProductionPhase.FEIYANG_ACTIVATE:
        _step(game, _require_op(game, "feiyang_decline"))
    _put_spade_hit_on_draw_top(game)
    _step(game, _require_op(game, "proceed_judgment"))
    _pass_judgment_wuxie(game)
    _pass_all_rescues(game)
    assert game.phase is ProductionPhase.PEASANT_REWARD_CHOICE
    assert game.state.players_by_id["p1"].alive is True
    assert game.state.players_by_id["p2"].alive is False
    _assert_lightning_root_ownership(game, lightning_id)
    assert game.runtime.pending_chain is not None
    _step(game, _require_op(game, "peasant_reward_decline"))
    assert "shandian_victory_cleanup" not in _event_reasons(game)
    assert _event_reasons(game).count("shandian_resolved") == 1
    assert game.runtime.pending_judgment is None
    assert game.current_player_id == "p1"
    assert game.phase is ProductionPhase.JUDGMENT
    _step(game, _require_op(game, "proceed_judgment"))
    assert game.phase is ProductionPhase.DRAW
    _step(game, _require_op(game, "proceed_draw"))
    assert game.phase is ProductionPhase.PLAY


def test_lightning_reward_window_pending_cannot_point_at_discarded_root() -> None:
    game = _session(seed=216)
    lightning_id = _open_lightning_current_peasant_reward(game)
    pending = game.runtime.pending_judgment
    assert pending is not None
    assert pending.cleanup_done is False
    assert pending.stage == "resolving_effect"
    assert game.state.location_of(lightning_id) != DISCARD_PILE
    assert game.state.location_of(lightning_id) == PROCESSING_ZONE
