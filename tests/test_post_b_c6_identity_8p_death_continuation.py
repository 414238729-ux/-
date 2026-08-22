# -*- coding: utf-8 -*-
"""POST-B C6：8p 死亡、救援与 parent/root continuation 强回归。"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

import pytest

from scripts.sgs_engine.events import EventType
from scripts.sgs_engine.model import PROCESSING_ZONE, ZoneRef
from scripts.sgs_engine.mode_identity import (
    FormalEightPlayerIdentityConfiguration,
    FormalEightPlayerIdentitySession,
    StandardIdentityRole,
)
from scripts.sgs_engine.production_batch import (
    ProductionBatchFinishedError,
    ProductionPhase,
    _replace_player,
)

_SECRET = b"c6-death-continuation-secret-001"


def _session(seed: int) -> FormalEightPlayerIdentitySession:
    game = FormalEightPlayerIdentitySession(
        seed=seed,
        configuration=FormalEightPlayerIdentityConfiguration.formal_profile(),
        analysis_only=False,
        session_id=f"c6-death-continuation-{seed}",
        session_secret=_SECRET,
    )
    assert len(game.player_ids) == 8
    return game


def _scenarios() -> Any:
    path = Path(__file__).with_name(
        "test_post_b_c5_identity_death_continuation.py"
    )
    spec = importlib.util.spec_from_file_location(
        "_c6_reused_c5_death_continuation_scenarios", path
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载C5 parent/root强场景：{path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module._session = _session
    return module


@pytest.fixture(scope="module")
def scenarios() -> Any:
    return _scenarios()


@pytest.mark.parametrize(
    "scenario_name",
    (
        "test_current_turn_owner_death_defers_turn_end",
        "test_borrowed_sword_parent_root_survives_nonterminal_death",
        "test_lightning_pending_judgment_nonterminal",
        "test_chain_damage_nonterminal_child_death_continues",
        "test_stale_action_fails_closed",
    ),
)
def test_c6_eight_player_parent_root_and_death_scenarios(
    scenarios: Any, scenario_name: str
) -> None:
    """原强断言原样执行；路径不可达会直接失败，不 skip/return/fallback。"""

    getattr(scenarios, scenario_name)()


def test_c6_group_target_nonterminal_death_reward_precedes_continuation(
    scenarios: Any,
) -> None:
    game = _session(201)
    lord = game.lord_player_id
    victim = game.numbered_player_order[1]
    assert game.identities_by_player[victim] is StandardIdentityRole.REBEL
    scenarios._enter_play(game)
    scenarios._strip_hand(game, lord)
    nanman = scenarios._give_card(game, lord, "sgs_trick_nanmanruqin")
    scenarios._strip_hand(game, victim)
    game._state = _replace_player(game.state, victim, hp=1)
    start = len(game.events)
    scenarios._step(game, scenarios._require_op(game, "use_nanman"))
    scenarios._pass_trick(game)
    assert game.runtime.pending_group_trick is not None
    assert game.runtime.pending_group_trick.responder_id == victim
    assert len(game.runtime.pending_group_trick.target_sequence) == 7
    scenarios._step(game, scenarios._require_op(game, "pass_nanman_slash"))
    scenarios._pass_rescues(game)
    assert game.state.players_by_id[victim].alive is False
    assert game.is_finished is False
    types = scenarios._event_types_since(game, start)
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
    assert next(
        event.sequence
        for event in game.events[start:]
        if event.event_type is EventType.DEATH
        and event.target_ids == (victim,)
    ) < gained[0].sequence

    guard = 0
    while nanman in game.state.card_ids_in(PROCESSING_ZONE) and guard < 96:
        if scenarios._op(game, "pass_nanman_slash") is not None:
            scenarios._step(
                game, scenarios._require_op(game, "pass_nanman_slash")
            )
        elif scenarios._op(game, "pass_trick_response") is not None:
            scenarios._step(
                game, scenarios._require_op(game, "pass_trick_response")
            )
        elif game.phase is ProductionPhase.DYING_RESCUE:
            scenarios._pass_rescues(game)
        else:
            raise AssertionError(
                f"南蛮root未完成且没有合法continuation：{game.phase}"
            )
        guard += 1
    assert guard < 96
    assert nanman not in game.state.card_ids_in(PROCESSING_ZONE)
    assert len(scenarios._discard_moves(game, nanman)) == 1


def test_c6_fangtian_two_target_nonterminal_death_continues_exactly_once(
    scenarios: Any,
) -> None:
    game = _session(202)
    lord = game.lord_player_id
    rebels = [
        player_id
        for player_id in game.numbered_player_order
        if game.identities_by_player[player_id] is StandardIdentityRole.REBEL
    ]
    assert len(rebels) == 4
    victim, second = rebels[:2]
    scenarios._enter_play(game)
    scenarios._strip_hand(game, lord)
    fangtian = scenarios._give_card(
        game, lord, "sgs_weapon_fangtianhuaji"
    )
    game._state = game.state.move_card(
        fangtian, ZoneRef.equipment(lord, "weapon")
    )
    slash = scenarios._give_card(game, lord, scenarios.SHA)
    scenarios._strip_hand(game, victim)
    scenarios._strip_hand(game, second)
    game._state = _replace_player(game.state, victim, hp=1)
    action = next(
        (
            candidate
            for candidate in game.legal_actions()
            if candidate.payload.get("operation") == "use_slash"
            and candidate.card_instance_id == slash
            and candidate.target_ids == (victim, second)
        ),
        None,
    )
    assert action is not None
    assert action.payload.get("fangtian_multi_target") is True
    assert len(action.target_ids) == 2
    start = len(game.events)
    scenarios._step(game, action)
    assert game.runtime.pending_slash is not None
    assert game.runtime.pending_slash.target_sequence == (victim, second)
    assert game.state.card_ids_in(PROCESSING_ZONE).count(slash) == 1
    scenarios._step(game, scenarios._require_op(game, "pass_slash_response"))
    assert game.phase is ProductionPhase.DYING_RESCUE
    scenarios._pass_rescues(game)
    assert game.state.players_by_id[victim].alive is False
    assert game.is_finished is False
    assert game.phase is ProductionPhase.SLASH_RESPONSE
    assert game.runtime.pending_slash is not None
    assert game.runtime.pending_slash.target_id == second
    assert game.runtime.pending_slash.current_target_index == 1
    rewards = [
        event
        for event in game.events[start:]
        if event.event_type is EventType.CARD_GAINED
        and event.target_ids == (lord,)
        and event.payload.get("reason") == "identity_kill_rebel_draw"
    ]
    assert len(rewards) == 3
    second_hp = game.state.players_by_id[second].hp
    scenarios._step(game, scenarios._require_op(game, "pass_slash_response"))
    assert game.state.players_by_id[second].hp == second_hp - 1
    assert game.state.players_by_id[second].alive is True
    assert game.runtime.pending_slash is None
    assert game.state.card_ids_in(PROCESSING_ZONE).count(slash) == 0
    assert len(scenarios._discard_moves(game, slash)) == 1
    second_damage = next(
        event
        for event in game.events[start:]
        if event.event_type is EventType.DAMAGE
        and event.target_ids == (second,)
    )
    assert rewards[-1].sequence < second_damage.sequence


def test_c6_rescue_success_does_not_reveal_nonlord_identity(
    scenarios: Any,
) -> None:
    game = _session(203)
    lord = game.lord_player_id
    victim = game.numbered_player_order[1]
    assert game.identities_by_player[victim] is not StandardIdentityRole.LORD
    scenarios._enter_play(game)
    scenarios._strip_hand(game, victim)
    scenarios._give_card(game, lord, scenarios.SHA)
    peach = scenarios._give_card(game, lord, "sgs_basic_tao")
    game._state = _replace_player(game.state, victim, hp=1)
    scenarios._step(
        game, scenarios._require_op(game, "use_slash", targets=(victim,))
    )
    scenarios._step(
        game, scenarios._require_op(game, "pass_slash_response")
    )
    assert game.phase is ProductionPhase.DYING_RESCUE
    rescue = None
    passed_rescuers = 0
    while rescue is None:
        rescue = next(
            (
                action
                for action in game.legal_actions()
                if action.card_instance_id == peach
            ),
            None,
        )
        if rescue is None:
            scenarios._step(game, scenarios._require_op(game, "pass_rescue"))
            passed_rescuers += 1
            assert passed_rescuers < 8
    assert rescue is not None
    assert rescue.card_instance_id == peach
    scenarios._step(game, rescue)
    assert game.state.players_by_id[victim].alive is True
    assert game.state.players_by_id[victim].hp >= 1
    assert not any(
        event.event_type is EventType.IDENTITY_REVEALED
        and event.target_ids == (victim,)
        and event.payload.get("reason") == "confirmed_death"
        for event in game.events
    )


def test_c6_lord_loyalist_penalty_precedes_group_future_target(
    scenarios: Any,
) -> None:
    game = _session(201)
    lord = game.lord_player_id
    target_order = [
        player_id for player_id in game.numbered_player_order if player_id != lord
    ]
    assert len(target_order) == 7
    loyalist = target_order[1]
    assert game.identities_by_player[loyalist] is StandardIdentityRole.LOYALIST
    scenarios._enter_play(game)
    scenarios._strip_hand(game, lord)
    equipment = scenarios._give_card(
        game, lord, "sgs_weapon_qinglongyanyuedao"
    )
    game._state = game.state.move_card(
        equipment, ZoneRef.equipment(lord, "weapon")
    )
    judgment = scenarios._give_card(game, lord, "sgs_delayed_lebusi")
    game._state = game.state.move_card(judgment, ZoneRef.judgment(lord))
    nanman = scenarios._give_card(game, lord, "sgs_trick_nanmanruqin")
    penalty_hand = scenarios._give_card(game, lord, "sgs_basic_tao")
    for player_id in target_order:
        scenarios._strip_hand(game, player_id)
    game._state = _replace_player(game.state, loyalist, hp=1)
    start = len(game.events)
    scenarios._step(game, scenarios._require_op(game, "use_nanman"))
    assert game.state.card_ids_in(PROCESSING_ZONE).count(nanman) == 1
    scenarios._pass_trick(game)
    assert game.runtime.pending_group_trick is not None
    assert game.runtime.pending_group_trick.target_sequence == tuple(target_order)
    assert game.runtime.pending_group_trick.responder_id == target_order[0]

    first_target = target_order[0]
    first_hp = game.state.players_by_id[first_target].hp
    scenarios._step(game, scenarios._require_op(game, "pass_nanman_slash"))
    assert game.state.players_by_id[first_target].hp == first_hp - 1
    assert game.state.players_by_id[first_target].alive is True
    scenarios._pass_trick(game)
    assert game.runtime.pending_group_trick is not None
    assert game.runtime.pending_group_trick.responder_id == loyalist
    scenarios._step(game, scenarios._require_op(game, "pass_nanman_slash"))
    assert game.phase is ProductionPhase.DYING_RESCUE
    scenarios._pass_rescues(game)

    assert game.state.players_by_id[loyalist].alive is False
    assert game.is_finished is False
    assert game.state.card_ids_in(ZoneRef.hand(lord)) == ()
    assert game.state.card_ids_in(ZoneRef.equipment(lord, "weapon")) == ()
    assert game.state.card_ids_in(ZoneRef.judgment(lord)) == (judgment,)
    assert game.state.card_ids_in(PROCESSING_ZONE).count(nanman) == 1
    penalty_moves = [
        event
        for event in game.events[start:]
        if event.event_type is EventType.CARD_MOVED
        and event.payload.get("reason")
        == "identity_lord_kill_loyalist_penalty"
    ]
    assert {event.card_instance_id for event in penalty_moves} == {
        penalty_hand,
        equipment,
    }
    assert len(penalty_moves) == 2
    death = next(
        event
        for event in game.events[start:]
        if event.event_type is EventType.DEATH
        and event.target_ids == (loyalist,)
    )
    assert death.sequence < penalty_moves[0].sequence
    assert game.runtime.pending_group_trick is not None
    assert game.runtime.pending_group_trick.current_target_index == 2
    scenarios._pass_trick(game)
    assert game.runtime.pending_group_trick is not None
    future_target = target_order[2]
    assert game.runtime.pending_group_trick.responder_id == future_target
    future_hp = game.state.players_by_id[future_target].hp
    scenarios._step(game, scenarios._require_op(game, "pass_nanman_slash"))
    assert game.state.players_by_id[future_target].hp == future_hp - 1
    future_damage = next(
        event
        for event in game.events[start:]
        if event.event_type is EventType.DAMAGE
        and event.target_ids == (future_target,)
    )
    assert penalty_moves[-1].sequence < future_damage.sequence
    while game.runtime.pending_group_trick is not None:
        scenarios._pass_trick(game)
        scenarios._step(
            game, scenarios._require_op(game, "pass_nanman_slash")
        )
    assert game.phase is ProductionPhase.PLAY
    assert game.state.card_ids_in(PROCESSING_ZONE).count(nanman) == 0
    assert len(scenarios._discard_moves(game, nanman)) == 1


def test_c6_terminal_lord_death_stops_seven_target_group_future_targets(
    scenarios: Any,
) -> None:
    game = _session(202)
    lord = game.lord_player_id
    user = game.numbered_player_order[-1]
    assert game.identities_by_player[user] is StandardIdentityRole.REBEL
    scenarios._advance_to(game, user)
    scenarios._enter_play(game)
    scenarios._strip_hand(game, user)
    nanman = scenarios._give_card(game, user, "sgs_trick_nanmanruqin")
    scenarios._strip_hand(game, lord)
    game._state = _replace_player(game.state, lord, hp=1)
    start = len(game.events)
    scenarios._step(game, scenarios._require_op(game, "use_nanman"))
    assert game.runtime.pending_group_trick is not None
    target_sequence = game.runtime.pending_group_trick.target_sequence
    assert len(target_sequence) == 7
    assert target_sequence[0] == lord
    future_targets = target_sequence[1:]
    assert len(future_targets) == 6
    future_hp = {
        player_id: game.state.players_by_id[player_id].hp
        for player_id in future_targets
    }
    scenarios._pass_trick(game)
    assert game.runtime.pending_group_trick is not None
    assert game.runtime.pending_group_trick.responder_id == lord
    scenarios._step(game, scenarios._require_op(game, "pass_nanman_slash"))
    assert game.phase is ProductionPhase.DYING_RESCUE
    terminal_start = len(game.events)
    scenarios._pass_rescues(game)
    assert game.state.players_by_id[lord].alive is False
    assert game.is_finished is True
    assert game.winner_id == "rebels"
    assert game.phase is ProductionPhase.FINISHED
    assert game.runtime.pending_group_trick is None
    with pytest.raises(ProductionBatchFinishedError):
        game.legal_actions()
    assert game.state.card_ids_in(PROCESSING_ZONE).count(nanman) == 0
    root_moves = scenarios._discard_moves(game, nanman)
    assert len(root_moves) == 1
    victory_events = [
        event
        for event in game.events[terminal_start:]
        if event.event_type is EventType.VICTORY
    ]
    assert len(victory_events) == 1
    assert victory_events[0].target_ids == ("rebels",)
    forbidden_future_types = {
        EventType.CARD_EFFECT_CANCELLED,
        EventType.CARD_INVALIDATED,
        EventType.DAMAGE,
        EventType.DYING,
        EventType.GROUP_TARGET_RESOLVED,
    }
    assert not any(
        event.event_type in forbidden_future_types
        and any(player_id in event.target_ids for player_id in future_targets)
        for event in game.events[start:]
    )
    assert all(
        game.state.players_by_id[player_id].alive is True
        and game.state.players_by_id[player_id].hp == future_hp[player_id]
        for player_id in future_targets
    )
    death = next(
        event
        for event in game.events[terminal_start:]
        if event.event_type is EventType.DEATH and event.target_ids == (lord,)
    )
    assert root_moves[0].sequence < death.sequence < victory_events[0].sequence
