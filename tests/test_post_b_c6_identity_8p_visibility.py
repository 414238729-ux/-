# -*- coding: utf-8 -*-
"""POST-B C6：八观察者独立手牌视图、身份公开与 side-channel 脱敏。"""

from __future__ import annotations

from typing import Any, Mapping

import pytest

from scripts.sgs_engine.events import EventType
from scripts.sgs_engine.mode_identity import (
    FormalEightPlayerIdentityConfiguration,
    FormalEightPlayerIdentitySession,
    StandardIdentityRole,
)
from scripts.sgs_engine.production_replay import (
    ProductionReexecutionReplay,
    ProductionReplayFormatError,
    _project_public_events,
    _redact_identity_header,
    record_reference_formal_eight_player_identity,
    reexecute_production_replay,
)

VALID = ("p1", "p2", "p3", "p4", "p5", "p6", "p7", "p8")
_SECRET = b"c6-visibility-session-secret-0001"


def _session(seed: int = 8) -> FormalEightPlayerIdentitySession:
    return FormalEightPlayerIdentitySession(
        seed=seed,
        configuration=FormalEightPlayerIdentityConfiguration.formal_profile(),
        analysis_only=False,
        session_id=f"c6-visibility-{seed}",
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


def _without_visible_hash(value: dict[str, object]) -> dict[str, object]:
    result = dict(value)
    result.pop("player_visible_sha256", None)
    return result


@pytest.fixture(scope="module")
def same_seed_records() -> tuple[
    ProductionReexecutionReplay, ProductionReexecutionReplay
]:
    first = record_reference_formal_eight_player_identity(
        16,
        configuration=FormalEightPlayerIdentityConfiguration.formal_profile(),
        analysis_only=False,
        max_steps=8000,
    )
    second = record_reference_formal_eight_player_identity(
        16,
        configuration=FormalEightPlayerIdentityConfiguration.formal_profile(),
        analysis_only=False,
        max_steps=8000,
    )
    assert first.authoritative_private != second.authoritative_private
    assert (
        first.outcome["winner_id"]
        == second.outcome["winner_id"]
        == "lord_and_loyalists"
    )
    return first, second


def test_c6_eight_independent_initial_hand_and_identity_projections() -> None:
    game = _session(333)
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
    assert len(public_identities) == 8
    for player_id, role in public_identities.items():
        assert role == ("lord" if player_id == lord else "hidden")

    events = [event.to_replay_dict() for event in game.events]
    initial_gains = [
        event
        for event in events
        if event["event_type"] == EventType.CARD_GAINED.value
        and event["payload"].get("reason") == "initial_hand"
    ]
    assert len(initial_gains) == 32
    for viewer_id in VALID:
        viewer_header = _redact_identity_header(dict(header), viewer_id)
        seen = viewer_header["initial_configuration"]["identities"]
        assert seen[viewer_id] == identities[viewer_id]
        assert seen[lord] == StandardIdentityRole.LORD.value
        assert all(
            role == "hidden"
            for player_id, role in seen.items()
            if player_id not in {viewer_id, lord}
        )
        projected = _project_public_events(events, viewer_id, frozenset())
        projected_initial = [
            event
            for event in projected
            if event.get("event_type") == EventType.CARD_GAINED.value
            and event.get("payload", {}).get("reason") == "initial_hand"
        ]
        assert len(projected_initial) == 32
        for event in projected_initial:
            owner = event["target_ids"][0]
            if owner == viewer_id:
                assert event.get("card_instance_id") is not None
                assert event.get("card_key") is not None
            else:
                assert event.get("card_instance_id") is None
                assert event.get("card_key") is None
                assert event.get("payload", {}).get("redacted") is True


def test_c6_confirmed_dead_nonlord_identity_is_public_event(
    same_seed_records: tuple[
        ProductionReexecutionReplay, ProductionReexecutionReplay
    ],
) -> None:
    record = same_seed_records[0]
    authoritative_events = list(record.events)
    reveals = [
        event
        for event in authoritative_events
        if event["event_type"] == EventType.IDENTITY_REVEALED.value
        and event["payload"].get("reason") == "confirmed_death"
    ]
    assert reveals
    for reveal in reveals:
        victim = reveal["target_ids"][0]
        assert reveal["payload"]["identity"] in {
            "loyalist",
            "rebel",
            "spy",
        }
        reveal_index = authoritative_events.index(reveal)
        dying_indices = [
            index
            for index, event in enumerate(authoritative_events[:reveal_index])
            if event["event_type"] == EventType.DYING.value
            and victim in event["target_ids"]
        ]
        death_indices = [
            index
            for index, event in enumerate(authoritative_events[reveal_index + 1 :], start=reveal_index + 1)
            if event["event_type"] == EventType.DEATH.value
            and victim in event["target_ids"]
        ]
        assert dying_indices
        assert death_indices
        assert dying_indices[-1] < reveal_index < death_indices[0]

    public = record.player_visible_payload(viewer_id=None, valid_player_ids=VALID)
    public_reveals = [
        event
        for event in public["events"]
        if event.get("event_type") == EventType.IDENTITY_REVEALED.value
        and event.get("payload", {}).get("reason") == "confirmed_death"
    ]
    assert [
        (tuple(event["target_ids"]), event["payload"]["identity"])
        for event in public_reveals
    ] == [
        (tuple(event["target_ids"]), event["payload"]["identity"])
        for event in reveals
    ]


def test_c6_player_visible_payload_redacts_all_authority_and_hidden_hashes(
    same_seed_records: tuple[
        ProductionReexecutionReplay, ProductionReexecutionReplay
    ],
) -> None:
    record = same_seed_records[0]
    with pytest.raises(ValueError, match="不是正式会话中的合法角色ID"):
        record.player_visible_payload(viewer_id="p9", valid_player_ids=VALID)

    for viewer_id in (*VALID, None):
        visible = record.player_visible_payload(
            viewer_id=viewer_id, valid_player_ids=VALID
        )
        header = visible["header"]
        assert "seed" not in header
        assert "initial_rng_state" not in header
        assert "initial_rng_state_sha256" not in header
        assert "initial_execution_hash" not in header
        assert "initial_game_state_hash" not in header
        assert header["rng_material_redacted"] is True
        assert visible["random_consumptions"] == []
        assert visible["random_consumption_count"] > 0
        assert "authoritative_private" not in visible
        assert visible["event_hash_chain"] == []
        assert "record_sha256" not in visible
        assert visible["player_visible"] is True
        assert "player_visible_sha256" in visible

        identities = header["initial_configuration"]["identities"]
        lord = header["initial_configuration"]["lord_player_id"]
        for player_id, role in identities.items():
            if player_id == lord:
                assert role == "lord"
            elif player_id == viewer_id:
                assert role in {"loyalist", "rebel", "spy"}
            else:
                assert role == "hidden"

        banned_keys = {
            "state_hash",
            "state_sha256",
            "execution_hash",
            "execution_sha256",
            "event_hash",
            "event_chain_tip",
            "record_sha256",
            "legal_action_set_sha256",
            "chosen_action_id",
            "action_id",
            "session_secret_hex",
        }
        for mapping in _walk_mappings(visible):
            assert banned_keys.isdisjoint(mapping)
            for key in mapping:
                if key.endswith("_sha256"):
                    assert key in {"context_sha256", "player_visible_sha256"}

        with pytest.raises((ProductionReplayFormatError, TypeError, ValueError)):
            reexecute_production_replay(
                ProductionReexecutionReplay.from_dict(visible)
            )


def test_c6_public_projection_is_independent_of_session_secret_and_action_ids(
    same_seed_records: tuple[
        ProductionReexecutionReplay, ProductionReexecutionReplay
    ],
) -> None:
    first, second = same_seed_records
    for viewer_id in (*VALID, None):
        visible_first = first.player_visible_payload(
            viewer_id=viewer_id, valid_player_ids=VALID
        )
        visible_second = second.player_visible_payload(
            viewer_id=viewer_id, valid_player_ids=VALID
        )
        assert _without_visible_hash(visible_first) == _without_visible_hash(
            visible_second
        )
