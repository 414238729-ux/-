# -*- coding: utf-8 -*-
"""POST-B C7：储君/转忠/择途隐藏信息与 player-visible 脱敏。"""

from __future__ import annotations

from typing import Any, Mapping

from scripts.sgs_engine.events import EventType
from scripts.sgs_engine.mode_identity import StandardIdentityRole
from scripts.sgs_engine.mode_identity_heir import (
    FormalHeirAndSpyChoiceIdentityConfiguration,
    FormalHeirAndSpyChoiceIdentitySession,
)
from scripts.sgs_engine.production_batch import BatchActionIdController, ProductionPhase
from scripts.sgs_engine.production_replay import (
    _project_public_events,
    _redact_identity_header,
    record_reference_formal_heir_and_spy_choice_identity,
)

VALID = ("p1", "p2", "p3", "p4", "p5", "p6", "p7", "p8")
_SECRET = b"c7-visibility-session-secret-0001"


def _session(seed: int = 8) -> FormalHeirAndSpyChoiceIdentitySession:
    return FormalHeirAndSpyChoiceIdentitySession(
        seed=seed,
        configuration=FormalHeirAndSpyChoiceIdentityConfiguration.formal_profile(),
        analysis_only=False,
        session_id=f"c7-visibility-{seed}",
        session_secret=_SECRET,
    )


def _walk_mappings(value: object) -> list[Mapping[str, object]]:
    found: list[Mapping[str, object]] = []
    if isinstance(value, Mapping):
        found.append(value)
        for item in value.values():
            found.extend(_walk_mappings(item))
    elif isinstance(value, (list, tuple)):
        for item in value:
            found.extend(_walk_mappings(item))
    return found


def test_c7_eight_independent_initial_identity_projections() -> None:
    game = _session(3)
    identities = {
        player_id: role.value
        for player_id, role in game.identities_by_player.items()
    }
    lord = game.lord_player_id
    header = {
        "mode_id": game.mode_id,
        "initial_configuration": {
            "identities": identities,
            "lord_player_id": lord,
        },
    }
    public_header = _redact_identity_header(dict(header), None)
    public_identities = public_header["initial_configuration"]["identities"]
    for player_id, role in public_identities.items():
        assert role == ("lord" if player_id == lord else "hidden")
    for viewer_id in VALID:
        seen = _redact_identity_header(dict(header), viewer_id)[
            "initial_configuration"
        ]["identities"]
        assert seen[viewer_id] == identities[viewer_id]
        assert seen[lord] == StandardIdentityRole.LORD.value
        assert all(
            role == "hidden"
            for player_id, role in seen.items()
            if player_id not in {viewer_id, lord}
        )


def test_c7_heir_target_absent_from_public_events_and_other_legal_actions() -> None:
    game = _session(0)
    lord = game.lord_player_id
    other = game.numbered_player_order[1]
    def _step_op(operation: str) -> None:
        for action in game.legal_actions():
            if action.payload.get("operation") == operation:
                game.step(BatchActionIdController(action.action_id))
                return
        raise AssertionError(operation)

    for operation in ("proceed_prepare", "proceed_judgment", "proceed_draw"):
        _step_op(operation)
    _step_op("end_play_phase")
    while game.phase is ProductionPhase.DISCARD:
        operations = [
            action.payload.get("operation") for action in game.legal_actions()
        ]
        _step_op(
            "discard_phase_submit"
            if "discard_phase_submit" in operations
            else "select_discard_card"
        )
    if game.phase is ProductionPhase.END:
        _step_op("end_turn")
    assert game.phase is ProductionPhase.MODE_DECISION
    assert game.current_actor_id == lord
    target = other
    chosen = next(
        action
        for action in game.legal_actions()
        if action.payload.get("operation") == "select_heir"
        and action.payload.get("target_id") == target
    )
    game.step(BatchActionIdController(chosen.action_id))
    events = [event.to_replay_dict() for event in game.events]
    for event in events:
        assert event.get("event_type") != "heir_selected"
        payload = event.get("payload") or {}
        assert "heir_player_id" not in payload
        assert payload.get("reason") != "select_heir"
    for viewer_id in VALID:
        if viewer_id == lord:
            continue
        projected = _project_public_events(events, viewer_id, frozenset())
        blob = repr(projected)
        assert "select_heir" not in blob
        assert "heir_selected" not in blob


def test_c7_converted_loyalist_announcement_hides_subject() -> None:
    game = _session(1)
    spy = next(
        player_id
        for player_id, role in game.role_current.items()
        if role == "spy"
    )
    game._variant.spy_path_choice = "loyalist"
    game._variant.spy_path_pending = True
    game._variant.spy_path_locked = True
    game._variant.spy_path_chooser_id = spy
    state, runtime = game._c7_apply_spy_conversion(
        game.state, game.runtime, spy, "loyalist"
    )
    game._state = state
    game._runtime = runtime
    announced = [
        event
        for event in game.events
        if event.event_type is EventType.IDENTITY_REVEALED
        and event.payload.get("reason") == "spy_converted_loyalist_announced"
    ]
    assert announced
    assert announced[0].target_ids == ()
    assert announced[0].payload["subject_revealed"] is False
    public = _project_public_events(
        [event.to_replay_dict() for event in announced],
        "p1" if spy != "p1" else "p2",
        frozenset(),
    )
    assert spy not in repr(public[0].get("target_ids", ()))


def test_c7_player_visible_payload_does_not_hash_secrets() -> None:
    record = record_reference_formal_heir_and_spy_choice_identity(
        0,
        configuration=FormalHeirAndSpyChoiceIdentityConfiguration.formal_profile(),
        analysis_only=False,
        max_steps=8000,
    )
    visible = record.player_visible_payload(
        "p1", valid_player_ids=VALID
    )
    assert visible["player_visible"] is True
    assert "authoritative_private" not in visible
    assert "session_secret_hex" not in repr(visible)
    for mapping in _walk_mappings(visible):
        assert "heir_player_id" not in mapping
        assert "spy_path_choice" not in mapping
