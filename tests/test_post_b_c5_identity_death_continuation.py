# -*- coding: utf-8 -*-
"""POST-B C5：非终局死亡 parent/root 继续与身份奖惩时序。"""

from __future__ import annotations

from dataclasses import replace
from types import MappingProxyType
from typing import Any

import pytest

from scripts.sgs_engine.actions import InvalidActionError, LegalAction
from scripts.sgs_engine.events import EventType
from scripts.sgs_engine.model import DISCARD_PILE, DRAW_PILE, PROCESSING_ZONE, ZoneRef
from scripts.sgs_engine.mode_identity import (
    FormalIdentityConfiguration,
    FormalIdentitySession,
    StandardIdentityRole,
)
from scripts.sgs_engine.multiplayer import PlayerTopology
from scripts.sgs_engine.production_batch import (
    BatchActionIdController,
    ProductionBasicCardBatch,
    ProductionBatchError,
    ProductionPhase,
    _replace_player,
)

SHA = "sgs_basic_sha"
_SECRET = b"0123456789abcdef0123456789abcdef"


def _session(seed: int) -> FormalIdentitySession:
    return FormalIdentitySession(
        seed=seed,
        configuration=FormalIdentityConfiguration.formal_profile(),
        session_id=f"c5-cont-{seed}",
        session_secret=_SECRET,
    )


def _step(game: ProductionBasicCardBatch, action: LegalAction) -> None:
    game.step(BatchActionIdController(action.action_id))


def _op(game: ProductionBasicCardBatch, operation: str, **filters: Any) -> LegalAction | None:
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


def _require_op(game: ProductionBasicCardBatch, operation: str, **filters: Any) -> LegalAction:
    action = _op(game, operation, **filters)
    assert action is not None, (
        f"缺少 {operation!r}: {[a.payload.get('operation') for a in game.legal_actions()]}"
    )
    return action


def _strip_hand(game: ProductionBasicCardBatch, player_id: str) -> None:
    for instance_id in tuple(game.state.card_ids_in(ZoneRef.hand(player_id))):
        game._state = game.state.move_card(instance_id, DISCARD_PILE)


def _give_card(game: ProductionBasicCardBatch, player_id: str, card_key: str) -> str:
    for instance_id, card in game.state.cards_by_id.items():
        if card.card_key == card_key:
            destination = ZoneRef.hand(player_id)
            if game.state.location_of(instance_id) != destination:
                game._state = game.state.move_card(instance_id, destination)
            return instance_id
    raise AssertionError(card_key)


def _enter_play(game: ProductionBasicCardBatch) -> None:
    for operation in ("proceed_prepare", "proceed_judgment", "proceed_draw"):
        _step(game, _require_op(game, operation))


def _pass_rescues(game: ProductionBasicCardBatch) -> None:
    while game.phase is ProductionPhase.DYING_RESCUE:
        _step(game, _require_op(game, "pass_rescue"))


def _pass_trick(game: ProductionBasicCardBatch) -> None:
    while _op(game, "pass_trick_response") is not None:
        _step(game, _require_op(game, "pass_trick_response"))


def _end_turn(game: ProductionBasicCardBatch) -> None:
    if game.phase is ProductionPhase.PLAY:
        _step(game, _require_op(game, "end_play_phase"))
    while game.phase is ProductionPhase.DISCARD:
        submit = _op(game, "discard_phase_submit")
        if submit is not None:
            _step(game, submit)
        else:
            _step(game, _require_op(game, "select_discard_card"))
    if game.phase is ProductionPhase.END:
        _step(game, _require_op(game, "end_turn"))


def _advance_to(game: FormalIdentitySession, player_id: str) -> None:
    guard = 0
    while game.current_player_id != player_id:
        if game.phase is ProductionPhase.PREPARE:
            _enter_play(game)
        _end_turn(game)
        guard += 1
        assert guard < 20


def _discard_moves(game: ProductionBasicCardBatch, instance_id: str) -> list[object]:
    return [
        event
        for event in game.events
        if event.card_instance_id == instance_id
        and event.event_type is EventType.CARD_MOVED
        and event.payload.get("destination", {}).get("kind") == "discard_pile"
    ]


def _event_types_since(game: ProductionBasicCardBatch, start: int) -> list[EventType]:
    return [event.event_type for event in game.events[start:]]


def test_group_target_nonterminal_death_resumes_and_rewards_before_continuation() -> None:
    game = _session(201)
    lord = game.lord_player_id
    rebels = [
        pid
        for pid, role in game.identities_by_player.items()
        if role is StandardIdentityRole.REBEL
    ]
    _enter_play(game)
    _strip_hand(game, lord)
    nanman = _give_card(game, lord, "sgs_trick_nanmanruqin")
    victim = rebels[0]
    _strip_hand(game, victim)
    game._state = _replace_player(game.state, victim, hp=1)
    start = len(game.events)
    _step(game, _require_op(game, "use_nanman"))
    _pass_trick(game)
    if _op(game, "pass_nanman_slash") is not None:
        _step(game, _require_op(game, "pass_nanman_slash"))
    _pass_rescues(game)
    assert game.state.players_by_id[victim].alive is False
    assert game.is_finished is False
    types = _event_types_since(game, start)
    assert EventType.IDENTITY_REVEALED in types
    assert types.index(EventType.IDENTITY_REVEALED) < types.index(EventType.DEATH)
    assert EventType.VICTORY not in types
    gained = [
        event
        for event in game.events[start:]
        if event.event_type is EventType.CARD_GAINED
        and event.payload.get("reason") == "identity_kill_rebel_draw"
    ]
    assert len(gained) == 3
    guard = 0
    while (
        not game.is_finished
        and nanman in game.state.card_ids_in(PROCESSING_ZONE)
        and guard < 24
    ):
        if _op(game, "pass_nanman_slash") is not None:
            _step(game, _require_op(game, "pass_nanman_slash"))
        elif _op(game, "pass_trick_response") is not None:
            _step(game, _require_op(game, "pass_trick_response"))
        elif game.phase is ProductionPhase.DYING_RESCUE:
            _pass_rescues(game)
        else:
            break
        guard += 1
    assert nanman not in game.state.card_ids_in(PROCESSING_ZONE)
    assert (
        len(
            [
                event
                for event in game.events
                if event.card_instance_id == nanman
                and event.event_type is EventType.CARD_MOVED
                and event.payload.get("destination", {}).get("kind")
                == "discard_pile"
            ]
        )
        == 1
    )


def test_fangtian_multi_target_nonterminal_death() -> None:
    game = _session(202)
    lord = game.lord_player_id
    others = [pid for pid in game.numbered_player_order if pid != lord]
    _enter_play(game)
    _strip_hand(game, lord)
    fangtian = _give_card(game, lord, "sgs_weapon_fangtianhuaji")
    game._state = game.state.move_card(fangtian, ZoneRef.equipment(lord, "weapon"))
    slash = _give_card(game, lord, SHA)
    victim = others[0]
    second = others[1]
    _strip_hand(game, victim)
    game._state = _replace_player(game.state, victim, hp=1)
    action = None
    for candidate in game.legal_actions():
        if candidate.payload.get("operation") == "use_slash" and set(candidate.target_ids) >= {victim, second}:
            action = candidate
            break
    if action is None:
        action = _require_op(game, "use_slash", targets=(victim,))
    _step(game, action)
    if _op(game, "pass_slash_response") is not None:
        _step(game, _require_op(game, "pass_slash_response"))
    _pass_rescues(game)
    assert game.state.players_by_id[victim].alive is False
    assert game.is_finished is False
    assert slash not in game.state.card_ids_in(PROCESSING_ZONE) or game.runtime.pending_slash is not None


def test_rescue_success_does_not_reveal_identity() -> None:
    game = _session(203)
    lord = game.lord_player_id
    victim = next(
        pid
        for pid, role in game.identities_by_player.items()
        if role is not StandardIdentityRole.LORD
    )
    _enter_play(game)
    _strip_hand(game, victim)
    _give_card(game, lord, SHA)
    peach = _give_card(game, lord, "sgs_basic_tao")
    game._state = _replace_player(game.state, victim, hp=1)
    _step(game, _require_op(game, "use_slash", targets=(victim,)))
    if _op(game, "pass_slash_response") is not None:
        _step(game, _require_op(game, "pass_slash_response"))
    assert game.phase is ProductionPhase.DYING_RESCUE
    rescue = _op(game, "use_peach") or _op(game, "rescue_peach")
    if rescue is None:
        for action in game.legal_actions():
            if action.card_instance_id == peach:
                rescue = action
                break
    assert rescue is not None
    _step(game, rescue)
    assert game.state.players_by_id[victim].alive is True
    assert game.state.players_by_id[victim].hp >= 1
    assert not any(
        event.event_type is EventType.IDENTITY_REVEALED
        and event.target_ids == (victim,)
        and event.payload.get("reason") == "confirmed_death"
        for event in game.events
    )


def test_current_turn_owner_death_defers_turn_end() -> None:
    """当前回合角色在回合未完成时经真实濒死确认死亡：根先收尾再兑现推迟切回合。"""

    game = _session(204)
    victim = next(
        pid
        for pid, role in game.identities_by_player.items()
        if role is not StandardIdentityRole.LORD
    )
    if game.phase is ProductionPhase.PREPARE:
        _enter_play(game)
    _advance_to(game, victim)
    assert game.current_player_id == victim
    assert game.phase is ProductionPhase.PREPARE
    assert game.state.players_by_id[victim].alive is True

    lightning = _give_card(game, victim, "sgs_delayed_shandian")
    game._state = game.state.move_card(lightning, ZoneRef.judgment(victim))
    game._runtime = replace(
        game.runtime,
        judgment_entry_indices=MappingProxyType({lightning: 1}),
        judgment_entry_counter=max(game.runtime.judgment_entry_counter, 1),
    )
    game._state = _replace_player(game.state, victim, hp=2)
    draw_cards = list(game.state.card_ids_in(DRAW_PILE))
    spade = next(
        cid
        for cid in draw_cards
        if game.state.cards_by_id[cid].suit in ("♠", "spade", "黑桃")
        and str(game.state.cards_by_id[cid].rank) in set("23456789")
    )
    others = [cid for cid in draw_cards if cid != spade]
    game._state = game.state.reorder_zone(DRAW_PILE, (spade, *others))

    turn_before = game.runtime.turn_number
    start = len(game.events)
    _step(game, _require_op(game, "proceed_prepare"))
    _step(game, _require_op(game, "proceed_judgment"))
    while game.phase in (
        ProductionPhase.JUDGMENT_WUXIE,
        ProductionPhase.TRICK_RESPONSE,
    ):
        operation = (
            "pass_judgment_wuxie"
            if _op(game, "pass_judgment_wuxie") is not None
            else "pass_trick_response"
        )
        _step(game, _require_op(game, operation))
    assert game.phase is ProductionPhase.DYING_RESCUE
    assert game.runtime.pending_dying_id == victim
    assert game.current_player_id == victim
    assert game.state.players_by_id[victim].alive is True
    assert game.is_finished is False
    _pass_rescues(game)

    assert game.state.players_by_id[victim].alive is False
    assert game.is_finished is False
    assert game.winner_id is None
    expected_next = PlayerTopology.from_state(game.state).first_alive_after(victim)
    assert game.current_player_id == expected_next
    assert game.current_player_id != victim
    assert game.state.players_by_id[expected_next].alive is True
    assert game.phase is ProductionPhase.PREPARE
    assert game.runtime.turn_number == turn_before + 1
    assert game.runtime.deferred_turn_end_after_owner_death is False
    assert game.runtime.pending_judgment is None
    assert lightning not in game.state.card_ids_in(PROCESSING_ZONE)
    assert len(_discard_moves(game, lightning)) == 1

    types = _event_types_since(game, start)
    assert EventType.DYING in types
    assert EventType.IDENTITY_REVEALED in types
    assert EventType.DEATH in types
    assert types.index(EventType.IDENTITY_REVEALED) < types.index(EventType.DEATH)
    assert EventType.VICTORY not in types
    assert types.count(EventType.DEATH) == 1

    seen_current: list[str] = []
    for _ in range(4):
        assert game.current_player_id != victim
        seen_current.append(game.current_player_id)
        if game.phase is ProductionPhase.PREPARE:
            _enter_play(game)
        assert game.phase is ProductionPhase.PLAY
        assert game.current_player_id != victim
        _end_turn(game)
    assert victim not in seen_current
    assert len(_discard_moves(game, lightning)) == 1


def test_borrowed_sword_parent_root_survives_nonterminal_death() -> None:
    game = _session(205)
    lord = game.lord_player_id
    others = [pid for pid in game.numbered_player_order if pid != lord]
    _enter_play(game)
    _strip_hand(game, lord)
    jiedao = _give_card(game, lord, "sgs_trick_jiedaosharen")
    weapon_holder = others[0]
    victim = others[1]
    _strip_hand(game, weapon_holder)
    qinglong = _give_card(game, weapon_holder, "sgs_weapon_qinglongyanyuedao")
    game._state = game.state.move_card(
        qinglong, ZoneRef.equipment(weapon_holder, "weapon")
    )
    _give_card(game, weapon_holder, SHA)
    _strip_hand(game, victim)
    game._state = _replace_player(game.state, victim, hp=1)
    used = None
    for action in game.legal_actions():
        if action.payload.get("operation") == "use_jiedao" or (
            action.card_instance_id == jiedao
        ):
            used = action
            break
    if used is None:
        return
    _step(game, used)
    _pass_trick(game)
    if _op(game, "jiedao_use_slash") is not None:
        _step(game, _require_op(game, "jiedao_use_slash"))
    if _op(game, "pass_slash_response") is not None:
        _step(game, _require_op(game, "pass_slash_response"))
    _pass_rescues(game)
    if not game.state.players_by_id[victim].alive:
        assert game.is_finished is False
        moves = [
            event
            for event in game.events
            if event.card_instance_id == jiedao
            and event.event_type is EventType.CARD_MOVED
            and event.payload.get("destination", {}).get("kind") == "discard_pile"
        ]
        assert len(moves) <= 1


def test_lightning_pending_judgment_nonterminal() -> None:
    game = _session(206)
    lord = game.lord_player_id
    _enter_play(game)
    lightning = _give_card(game, lord, "sgs_delayed_shandian")
    game._state = game.state.move_card(lightning, ZoneRef.judgment(lord))
    game._runtime = replace(
        game.runtime,
        judgment_entry_indices=MappingProxyType({lightning: 1}),
        judgment_entry_counter=1,
    )
    game._state = _replace_player(game.state, lord, hp=5)
    _step(game, _require_op(game, "end_play_phase"))
    while game.phase is ProductionPhase.DISCARD:
        submit = _op(game, "discard_phase_submit")
        if submit is not None:
            _step(game, submit)
        else:
            _step(game, _require_op(game, "select_discard_card"))
    _step(game, _require_op(game, "end_turn"))
    while game.current_player_id != lord:
        _enter_play(game)
        _step(game, _require_op(game, "end_play_phase"))
        while game.phase is ProductionPhase.DISCARD:
            submit = _op(game, "discard_phase_submit")
            if submit is not None:
                _step(game, submit)
            else:
                _step(game, _require_op(game, "select_discard_card"))
        _step(game, _require_op(game, "end_turn"))
    draw_cards = list(game.state.card_ids_in(DRAW_PILE))
    spade = next(
        (
            cid
            for cid in draw_cards
            if game.state.cards_by_id[cid].suit in ("♠", "spade", "黑桃")
            and str(game.state.cards_by_id[cid].rank) in set("23456789")
        ),
        None,
    )
    if spade is None:
        return
    others = [c for c in draw_cards if c != spade]
    game._state = game.state.reorder_zone(DRAW_PILE, (spade, *others))
    _step(game, _require_op(game, "proceed_prepare"))
    _step(game, _require_op(game, "proceed_judgment"))
    while game.phase in (ProductionPhase.JUDGMENT_WUXIE, ProductionPhase.TRICK_RESPONSE):
        op = "pass_judgment_wuxie" if _op(game, "pass_judgment_wuxie") else "pass_trick_response"
        _step(game, _require_op(game, op))
    _pass_rescues(game)
    moves = [
        event
        for event in game.events
        if event.card_instance_id == lightning
        and event.event_type is EventType.CARD_MOVED
        and event.payload.get("destination", {}).get("kind") == "discard_pile"
    ]
    assert len(moves) <= 1


def test_lord_kills_loyalist_then_resumes_parent_group() -> None:
    game = _session(207)
    lord = game.lord_player_id
    loyalist = next(
        pid
        for pid, role in game.identities_by_player.items()
        if role is StandardIdentityRole.LOYALIST
    )
    _enter_play(game)
    _strip_hand(game, lord)
    nanman = _give_card(game, lord, "sgs_trick_nanmanruqin")
    _strip_hand(game, loyalist)
    game._state = _replace_player(game.state, loyalist, hp=1)
    lord_hand_before = list(game.state.card_ids_in(ZoneRef.hand(lord)))
    _step(game, _require_op(game, "use_nanman"))
    _pass_trick(game)
    if _op(game, "pass_nanman_slash") is not None:
        _step(game, _require_op(game, "pass_nanman_slash"))
    _pass_rescues(game)
    if game.state.players_by_id[loyalist].alive:
        return
    assert game.is_finished is False
    assert game.state.card_ids_in(ZoneRef.hand(lord)) == ()
    assert any(
        event.payload.get("reason") == "identity_lord_kill_loyalist_penalty"
        for event in game.events
        if event.payload
    )
    del lord_hand_before
    if game.phase is not ProductionPhase.PLAY:
        if _op(game, "pass_nanman_slash") is not None:
            _step(game, _require_op(game, "pass_nanman_slash"))
        _pass_trick(game)
    assert nanman not in game.state.card_ids_in(PROCESSING_ZONE)


def test_terminal_victory_stops_remaining_targets() -> None:
    game = _session(208)
    lord = game.lord_player_id
    enemies = [
        pid
        for pid, role in game.identities_by_player.items()
        if role in {StandardIdentityRole.REBEL, StandardIdentityRole.SPY}
    ]
    _enter_play(game)
    for enemy in enemies[:-1]:
        _strip_hand(game, enemy)
        _give_card(game, lord, SHA)
        game._state = _replace_player(game.state, enemy, hp=1)
        if game.current_player_id != lord:
            return
        slash = None
        for action in game.legal_actions():
            if (
                action.payload.get("operation") == "use_slash"
                and enemy in action.target_ids
            ):
                slash = action
                break
        if slash is None:
            return
        _step(game, slash)
        if _op(game, "pass_slash_response") is not None:
            _step(game, _require_op(game, "pass_slash_response"))
        _pass_rescues(game)
        if game.is_finished:
            break
        _strip_hand(game, lord)
    if game.is_finished:
        assert game.winner_id in {"lord_and_loyalists", "rebels", "spy"}
        assert not any(
            event.event_type is EventType.DRAW
            and event.payload.get("reason") == "identity_draw_deck_exhausted"
            for event in game.events
        )


def test_chain_damage_nonterminal_child_death_continues() -> None:
    """属性伤害根经铁索传导：chain child 非终局死亡奖惩先完成，再继续剩余目标。"""

    game = _session(201)
    lord = game.lord_player_id
    order = list(game.numbered_player_order)
    original = order[-1]
    dying = next(
        pid
        for pid in order
        if pid != original
        and game.identities_by_player[pid] is StandardIdentityRole.REBEL
    )
    remaining = next(
        pid for pid in order if pid not in {lord, original, dying}
    )
    _enter_play(game)
    _strip_hand(game, lord)
    slash_id = _give_card(game, lord, "sgs_basic_huosha")
    qinglong = _give_card(game, lord, "sgs_weapon_qinglongyanyuedao")
    game._state = game.state.move_card(
        qinglong, ZoneRef.equipment(lord, "weapon")
    )
    _strip_hand(game, original)
    _strip_hand(game, dying)
    game._state = _replace_player(game.state, original, chained=True, hp=4)
    game._state = _replace_player(game.state, dying, chained=True, hp=1)
    game._state = _replace_player(game.state, remaining, chained=True, hp=4)

    slash = None
    for action in game.legal_actions():
        if (
            action.payload.get("operation") == "use_slash"
            and action.payload.get("card_key") == "sgs_basic_huosha"
            and original in action.target_ids
        ):
            slash = action
            break
    assert slash is not None
    start = len(game.events)
    _step(game, slash)
    if _op(game, "pass_slash_response") is not None:
        _step(game, _require_op(game, "pass_slash_response"))
    assert game.phase is ProductionPhase.DYING_RESCUE
    assert game.runtime.pending_dying_id == dying
    assert game.runtime.pending_chain is not None
    assert game.is_finished is False
    _pass_rescues(game)

    assert game.state.players_by_id[dying].alive is False
    assert game.is_finished is False
    assert game.winner_id is None
    assert game.current_player_id == lord
    assert game.phase is ProductionPhase.PLAY
    assert game.runtime.pending_chain is None
    assert slash_id not in game.state.card_ids_in(PROCESSING_ZONE)
    assert game.state.players_by_id[remaining].alive is True
    assert game.state.players_by_id[remaining].chained is False
    assert game.state.players_by_id[original].chained is False

    events = game.events[start:]
    types = [event.event_type for event in events]
    assert types.count(EventType.CHAIN_DAMAGE_STARTED) == 1
    assert types.count(EventType.CHAIN_DAMAGE_FINISHED) == 1
    assert types.count(EventType.DEATH) == 1
    assert EventType.VICTORY not in types

    original_damage = next(
        event
        for event in events
        if event.event_type is EventType.DAMAGE
        and event.target_ids == (original,)
    )
    child_damage = next(
        event
        for event in events
        if event.event_type is EventType.DAMAGE
        and event.target_ids == (dying,)
        and event.payload.get("is_chain_transmitted") is True
    )
    remaining_damage = next(
        event
        for event in events
        if event.event_type is EventType.DAMAGE
        and event.target_ids == (remaining,)
        and event.payload.get("is_chain_transmitted") is True
    )
    started = next(
        event
        for event in events
        if event.event_type is EventType.CHAIN_DAMAGE_STARTED
    )
    revealed = next(
        event
        for event in events
        if event.event_type is EventType.IDENTITY_REVEALED
        and event.target_ids == (dying,)
        and event.payload.get("reason") == "confirmed_death"
        and event.payload.get("identity") == StandardIdentityRole.REBEL.value
    )
    death = next(
        event
        for event in events
        if event.event_type is EventType.DEATH and event.target_ids == (dying,)
    )
    rewards = [
        event
        for event in events
        if event.event_type is EventType.CARD_GAINED
        and event.payload.get("reason") == "identity_kill_rebel_draw"
        and event.target_ids == (lord,)
    ]
    finished = next(
        event
        for event in events
        if event.event_type is EventType.CHAIN_DAMAGE_FINISHED
    )
    assert original_damage.sequence < started.sequence
    assert started.sequence < child_damage.sequence
    assert revealed.sequence < death.sequence
    assert death.sequence < rewards[0].sequence
    assert len(rewards) == 3
    assert rewards[-1].sequence < remaining_damage.sequence
    assert remaining_damage.sequence < finished.sequence
    processed = [
        event.target_ids[0]
        for event in events
        if event.event_type is EventType.CHAIN_TARGET_RESOLVED and event.target_ids
    ]
    assert dying in processed
    assert remaining in processed
    assert processed.count(dying) == 1
    assert processed.count(remaining) == 1
    assert len(_discard_moves(game, slash_id)) == 1


def test_stale_action_fails_closed() -> None:
    game = _session(209)
    _enter_play(game)
    legal = game.legal_actions()
    stale = legal[0]
    _step(game, _require_op(game, "end_play_phase"))
    event_count = len(game.events)
    execution = game.execution_snapshot
    state_rev = game.state.revision
    with pytest.raises((InvalidActionError, ProductionBatchError)):
        game.step(BatchActionIdController(stale.action_id))
    assert len(game.events) == event_count
    assert game.state.revision == state_rev
    assert game.execution_snapshot["step_count"] == execution["step_count"]
