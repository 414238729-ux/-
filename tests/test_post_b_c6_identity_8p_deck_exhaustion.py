# -*- coding: utf-8 -*-
"""POST-B C6：8p reshuffle_draw、局部取得与真实耗尽终局。"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

import pytest

from scripts.sgs_engine.events import EventType
from scripts.sgs_engine.model import (
    DISCARD_PILE,
    DRAW_PILE,
    PROCESSING_ZONE,
    REVEALED_ZONE,
    ZoneRef,
)
from scripts.sgs_engine.mode_identity import (
    FormalEightPlayerIdentityConfiguration,
    FormalEightPlayerIdentitySession,
    StandardIdentityRole,
)
from scripts.sgs_engine.production_batch import ProductionPhase, _replace_player

_SECRET = b"c6-deck-exhaustion-test-secret-001"


def _session(seed: int = 15) -> FormalEightPlayerIdentitySession:
    game = FormalEightPlayerIdentitySession(
        seed=seed,
        configuration=FormalEightPlayerIdentityConfiguration.formal_profile(),
        analysis_only=False,
        session_id=f"c6-deck-exhaustion-{seed}",
        session_secret=_SECRET,
    )
    assert len(game.state.card_ids_in(DRAW_PILE)) == 128
    return game


def _scenarios() -> Any:
    path = Path(__file__).with_name(
        "test_post_b_c5_identity_deck_exhaustion.py"
    )
    spec = importlib.util.spec_from_file_location(
        "_c6_reused_c5_identity_deck_scenarios", path
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载C5牌堆强场景：{path}")
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
        "test_reshuffle_when_discard_sufficient",
        "test_complete_last_card_is_not_draw",
        "test_need_next_card_with_both_piles_empty_is_identity_draw",
        "test_partial_draw_keeps_already_moved_cards",
        "test_wuzhong_exhaustion_is_formal_draw",
        "test_judgment_exhaustion_is_formal_draw",
        "test_tiesuo_recast_reshuffles_when_draw_empty",
        "test_tiesuo_recast_self_supplies_when_both_piles_empty",
        "test_bagua_judgment_reshuffles_when_draw_empty",
        "test_bagua_judgment_exhaustion_is_formal_draw",
        "test_cixiong_not_applicable_in_no_skill_soldier_profile",
        "test_hand_equipment_judgment_not_reshuffled",
    ),
)
def test_c6_live_draw_acquisition_and_exhaustion_scenarios(
    scenarios: Any, scenario_name: str
) -> None:
    """真实 C6 step 路径；任一 operation 不可达均直接失败。"""

    getattr(scenarios, scenario_name)()


def test_c6_wugu_reveals_eight_and_reshuffles_only_discard(
    scenarios: Any,
) -> None:
    game = _session(20)
    scenarios._enter_play(game)
    actor = game.current_player_id
    holder = next(player_id for player_id in game.player_ids if player_id != actor)
    scenarios._strip_hand(game, actor)
    wugu = scenarios._give_card(game, actor, "sgs_trick_wugufengdeng")
    draw_ids = list(game.state.card_ids_in(DRAW_PILE))
    scenarios._park_away(game, draw_ids[2:], holder)
    extra = list(game.state.card_ids_in(ZoneRef.hand(holder)))[:6]
    assert len(extra) == 6
    game._state = game.state.move_cards(
        {instance_id: DISCARD_PILE for instance_id in extra}
    )
    assert len(game.state.card_ids_in(DRAW_PILE)) == 2
    discard_before = tuple(game.state.card_ids_in(DISCARD_PILE))
    assert len(discard_before) >= 6
    start = len(game.events)
    scenarios._step(game, scenarios._require_op(game, "use_wugu"))
    assert game.is_finished is False
    assert wugu in game.state.card_ids_in(PROCESSING_ZONE)
    revealed = list(game.state.card_ids_in(REVEALED_ZONE))
    assert len(revealed) == 8
    revealed_so_far: list[str] = []
    reshuffles = []
    for event in game.events[start:]:
        if (
            event.event_type is EventType.CARD_REVEALED
            and event.payload.get("reason") == "wugu_reveal"
            and event.card_instance_id is not None
        ):
            revealed_so_far.append(event.card_instance_id)
        if (
            event.event_type is EventType.CARD_MOVED
            and event.payload.get("reason") == "reshuffle"
        ):
            reshuffles.append(event)
            assert event.payload.get("source", {}).get("kind") == "discard_pile"
            assert event.payload.get("destination", {}).get("kind") == "draw_pile"
            assert event.card_instance_id != wugu
            assert event.card_instance_id not in revealed_so_far
    assert len(reshuffles) == len(discard_before)
    assert len(revealed_so_far) == 8


def test_c6_rebel_reward_partial_acquisition_then_true_exhaustion_keeps_death(
    scenarios: Any,
) -> None:
    game = _session(23)
    lord = game.lord_player_id
    rebel = game.numbered_player_order[1]
    assert game.identities_by_player[rebel] is StandardIdentityRole.REBEL
    scenarios._enter_play(game)
    for instance_id in tuple(game.state.card_ids_in(ZoneRef.hand(rebel))):
        game._state = game.state.move_card(instance_id, DISCARD_PILE)
    slash = next(
        instance_id
        for instance_id in game.state.card_ids_in(DRAW_PILE)
        if game.state.cards_by_id[instance_id].card_key == scenarios.SHA
    )
    game._state = game.state.move_card(slash, ZoneRef.hand(lord))
    leftover = list(game.state.card_ids_in(DRAW_PILE))
    keep = leftover[:1]
    other = next(
        player_id for player_id in game.player_ids if player_id not in {lord, rebel}
    )
    game._state = game.state.move_cards(
        {
            instance_id: ZoneRef.hand(other)
            for instance_id in leftover[1:]
        }
    )
    discard = list(game.state.card_ids_in(DISCARD_PILE))
    game._state = game.state.move_cards(
        {instance_id: ZoneRef.hand(other) for instance_id in discard}
    )
    game._state = _replace_player(game.state, rebel, hp=1)
    scenarios._step(
        game,
        scenarios._require_op(game, "use_slash", targets=(rebel,)),
    )
    scenarios._step(
        game, scenarios._require_op(game, "pass_slash_response")
    )
    while game.phase is ProductionPhase.DYING_RESCUE:
        scenarios._step(game, scenarios._require_op(game, "pass_rescue"))
    assert game.state.players_by_id[rebel].alive is False
    assert any(
        event.event_type is EventType.IDENTITY_REVEALED
        and event.target_ids == (rebel,)
        for event in game.events
    )
    assert any(
        event.event_type is EventType.DEATH
        and event.target_ids == (rebel,)
        for event in game.events
    )
    assert game.is_finished is True
    assert game.winner_id is None
    assert game.runtime.game_over_reason == "identity_draw_deck_exhausted"
    assert not any(event.event_type is EventType.VICTORY for event in game.events)
    gained = [
        event
        for event in game.events
        if event.event_type is EventType.CARD_GAINED
        and event.payload.get("reason") == "identity_kill_rebel_draw"
    ]
    assert len(gained) == 2
    assert slash in {event.card_instance_id for event in gained}
    assert keep[0] in game.state.card_ids_in(ZoneRef.hand(lord))


def test_c6_wugu_partial_reveal_true_exhaustion_terminal_cleanup_once(
    scenarios: Any,
) -> None:
    game = _session(23)
    scenarios._enter_play(game)
    actor = game.current_player_id
    holder = next(player_id for player_id in game.player_ids if player_id != actor)
    scenarios._strip_hand(game, actor)
    wugu = scenarios._give_card(game, actor, "sgs_trick_wugufengdeng")
    draw_ids = list(game.state.card_ids_in(DRAW_PILE))
    keep = draw_ids[:2]
    scenarios._park_away(game, draw_ids[2:], holder)
    scenarios._park_away(
        game, list(game.state.card_ids_in(DISCARD_PILE)), holder
    )
    assert len(game.state.card_ids_in(DRAW_PILE)) == 2
    assert game.state.card_ids_in(DISCARD_PILE) == ()
    start = len(game.events)
    scenarios._step(game, scenarios._require_op(game, "use_wugu"))
    assert game.is_finished is True
    assert game.winner_id is None
    assert game.runtime.game_over_reason == "identity_draw_deck_exhausted"
    new_events = game.events[start:]
    revealed_events = [
        event
        for event in new_events
        if event.event_type is EventType.CARD_REVEALED
        and event.payload.get("reason") == "wugu_reveal"
    ]
    assert [event.card_instance_id for event in revealed_events] == keep
    draw_events = [
        event for event in new_events if event.event_type is EventType.DRAW
    ]
    assert len(draw_events) == 1
    assert revealed_events[-1].sequence < draw_events[0].sequence
    cleanups = [
        event
        for event in new_events
        if event.payload.get("reason") == "draw_game_over_cleanup"
    ]
    assert cleanups
    assert all(event.sequence > draw_events[0].sequence for event in cleanups)
    assert game.state.card_ids_in(REVEALED_ZONE) == ()
    assert game.state.card_ids_in(PROCESSING_ZONE) == ()
    for instance_id in keep:
        assert game.state.location_of(instance_id) == DISCARD_PILE
    assert wugu not in game.state.card_ids_in(PROCESSING_ZONE)
