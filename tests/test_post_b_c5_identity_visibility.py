# -*- coding: utf-8 -*-
"""POST-B C5：五观察者手牌隐私与身份可见性。"""

from __future__ import annotations

import json
from typing import Any, Mapping, Sequence

import pytest

from scripts.sgs_engine.actions import LegalAction
from scripts.sgs_engine.events import EventType
from scripts.sgs_engine.model import DISCARD_PILE, DRAW_PILE, ZoneRef
from scripts.sgs_engine.mode_identity import (
    FormalIdentityConfiguration,
    FormalIdentitySession,
    StandardIdentityRole,
)
from scripts.sgs_engine.production_batch import (
    BatchActionIdController,
    ProductionBasicCardBatch,
    ProductionPhase,
    _replace_player,
)
from scripts.sgs_engine.production_replay import (
    _project_public_events,
    _redact_identity_header,
    record_reference_formal_identity,
    record_reference_production_batch,
)

_SECRET_A = b"0123456789abcdef0123456789abcdef"
_SECRET_B = b"fedcba9876543210fedcba9876543210"
VALID = ("p1", "p2", "p3", "p4", "p5")
SHA = "sgs_basic_sha"


class _PacifistController:
    strategy_version = "c5-vis-pacifist.v1"

    def choose(
        self, legal_actions: Sequence[LegalAction], context: Any
    ) -> LegalAction:
        operations = [
            str(action.payload.get("operation", "")) for action in legal_actions
        ]
        for wanted in (
            "proceed_prepare",
            "proceed_judgment",
            "proceed_draw",
            "end_play_phase",
            "discard_phase_submit",
            "select_discard_card",
            "end_turn",
            "pass_trick_response",
            "pass_slash_response",
            "pass_rescue",
            "pass_judgment_wuxie",
            "heal_self",
        ):
            if wanted in operations:
                return next(
                    action
                    for action in legal_actions
                    if action.payload.get("operation") == wanted
                )
        raise AssertionError(operations)


def _session(seed: int = 8) -> FormalIdentitySession:
    return FormalIdentitySession(
        seed=seed,
        configuration=FormalIdentityConfiguration.formal_profile(),
        session_id=f"c5-vis-{seed}",
        session_secret=_SECRET_A,
    )


def _step(game: ProductionBasicCardBatch, action: LegalAction) -> None:
    game.step(BatchActionIdController(action.action_id))


def _op(game: ProductionBasicCardBatch, operation: str, **filters: Any) -> LegalAction | None:
    for action in game.legal_actions():
        if action.payload.get("operation") != operation:
            continue
        if "targets" in filters and tuple(action.target_ids) != tuple(filters["targets"]):
            continue
        return action
    return None


def _require_op(game: ProductionBasicCardBatch, operation: str, **filters: Any) -> LegalAction:
    action = _op(game, operation, **filters)
    assert action is not None
    return action


def _enter_play(game: ProductionBasicCardBatch) -> None:
    for operation in ("proceed_prepare", "proceed_judgment", "proceed_draw"):
        _step(game, _require_op(game, operation))


def test_five_independent_hand_projections_and_identity_privacy() -> None:
    game = _session(333)
    identities = {pid: role.value for pid, role in game.identities_by_player.items()}
    lord = game.lord_player_id
    header = {
        "mode_id": game.mode_id,
        "initial_configuration": {
            "identities": dict(identities),
            "lord_player_id": lord,
        },
    }
    public_header = _redact_identity_header(dict(header), None)
    public_ids = public_header["initial_configuration"]["identities"]
    for player_id, role in public_ids.items():
        if player_id == lord:
            assert role == "lord"
        else:
            assert role == "hidden"
    events = [event.to_replay_dict() for event in game.events]
    for viewer_id in VALID:
        viewer_header = _redact_identity_header(dict(header), viewer_id)
        seen = viewer_header["initial_configuration"]["identities"]
        assert seen[viewer_id] == identities[viewer_id]
        assert seen[lord] == "lord"
        for player_id, role in seen.items():
            if player_id not in {viewer_id, lord}:
                assert role == "hidden"
        projected = _project_public_events(events, viewer_id, frozenset())
        for event in projected:
            payload = event.get("payload")
            if not isinstance(payload, dict):
                continue
            destination = payload.get("destination")
            if isinstance(destination, dict) and destination.get("kind") == "hand":
                owner = destination.get("owner_id")
                if owner == viewer_id:
                    assert event.get("card_instance_id") is not None
                elif owner:
                    assert event.get("card_instance_id") is None
                    assert payload.get("redacted") is True
            if event.get("event_type") == "card_gained":
                targets = event.get("target_ids") or ()
                if targets and targets[0] != viewer_id:
                    assert event.get("card_instance_id") is None


def test_invalid_viewer_id_rejected() -> None:
    replay = record_reference_formal_identity(
        seed=2,
        configuration=FormalIdentityConfiguration.formal_profile(),
        analysis_only=True,
        max_steps=8000,
    )
    with pytest.raises(ValueError, match="不是正式会话中的合法角色ID"):
        replay.player_visible_payload(viewer_id="p9", valid_player_ids=VALID)
    public = replay.player_visible_payload(viewer_id=None, valid_player_ids=VALID)
    assert "seed" not in public["header"]
    assert public["random_consumptions"] == []
    assert "authoritative_private" not in public
    lord = replay.header["initial_configuration"]["lord_player_id"]
    public_ids = public["header"]["initial_configuration"]["identities"]
    for player_id, role in public_ids.items():
        if player_id == lord:
            assert role == "lord"
        else:
            assert role == "hidden"


def test_dying_does_not_reveal_identity_until_confirmed_death() -> None:
    game = _session(9)
    lord = game.lord_player_id
    victim = next(
        player_id
        for player_id, role in game.identities_by_player.items()
        if role is not StandardIdentityRole.LORD
    )
    _enter_play(game)
    for instance_id in tuple(game.state.card_ids_in(ZoneRef.hand(victim))):
        game._state = game.state.move_card(instance_id, DISCARD_PILE)
    weapon = None
    for instance_id, card in game.state.cards_by_id.items():
        if card.card_key == "sgs_weapon_qinglongyanyuedao":
            weapon = instance_id
            break
    assert weapon is not None
    game._state = game.state.move_card(
        weapon, ZoneRef.equipment(lord, "weapon")
    )
    for instance_id, card in game.state.cards_by_id.items():
        if card.card_key == SHA:
            game._state = game.state.move_card(instance_id, ZoneRef.hand(lord))
            break
    game._state = _replace_player(game.state, victim, hp=1)
    slash = None
    for action in game.legal_actions():
        if (
            action.payload.get("operation") == "use_slash"
            and victim in action.target_ids
        ):
            slash = action
            break
    assert slash is not None
    _step(game, slash)
    if _op(game, "pass_slash_response") is not None:
        _step(game, _require_op(game, "pass_slash_response"))
    assert game.phase is ProductionPhase.DYING_RESCUE
    assert not any(
        event.event_type is EventType.IDENTITY_REVEALED
        and event.target_ids == (victim,)
        and event.payload.get("reason") == "confirmed_death"
        for event in game.events
    )
    while game.phase is ProductionPhase.DYING_RESCUE:
        _step(game, _require_op(game, "pass_rescue"))
    assert any(
        event.event_type is EventType.IDENTITY_REVEALED
        and event.target_ids == (victim,)
        and event.payload.get("reason") == "confirmed_death"
        and event.payload.get("identity")
        == game.identities_by_player[victim].value
        for event in game.events
    )


_IDENTITY_TOKENS = frozenset({"lord", "loyalist", "rebel", "spy"})
_FORBIDDEN_AUTHORITATIVE_HASH_KEYS = frozenset(
    {
        "initial_execution_hash",
        "initial_game_state_hash",
        "final_execution_hash",
        "final_game_state_hash",
        "legal_action_set_sha256",
        "state_before_sha256",
        "state_after_sha256",
        "execution_before_sha256",
        "execution_after_sha256",
        "event_chain_tip",
        "chosen_action_id",
        "session_secret",
        "session_secret_hex",
        "authoritative_private",
    }
)


def _walk(value: object) -> list[tuple[str, object]]:
    found: list[tuple[str, object]] = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            found.append((str(key), item))
            found.extend(_walk(item))
    elif isinstance(value, (list, tuple)):
        for item in value:
            found.extend(_walk(item))
    return found


def _identity_mappings(value: object) -> list[dict[str, object]]:
    found: list[dict[str, object]] = []
    if isinstance(value, Mapping):
        raw = value.get("identities")
        if isinstance(raw, Mapping):
            found.append(dict(raw))
        for item in value.values():
            found.extend(_identity_mappings(item))
    elif isinstance(value, (list, tuple)):
        for item in value:
            found.extend(_identity_mappings(item))
    return found


def _action_public_fields(action: LegalAction) -> dict[str, object]:
    return {
        "actor_id": action.actor_id,
        "card_instance_id": action.card_instance_id,
        "target_ids": list(action.target_ids),
        "payload": dict(action.payload),
        "skill_id": action.skill_id,
    }


def _current_hands_from_events(
    events: Sequence[Mapping[str, object]],
) -> dict[str, set[str]]:
    hands: dict[str, set[str]] = {player_id: set() for player_id in VALID}
    for event in events:
        payload = event.get("payload")
        if not isinstance(payload, Mapping):
            continue
        destination = payload.get("destination")
        instance_id = event.get("card_instance_id")
        if not isinstance(instance_id, str) or not isinstance(destination, Mapping):
            continue
        for owner_id in list(hands):
            hands[owner_id].discard(instance_id)
        if destination.get("kind") == "hand":
            owner = destination.get("owner_id")
            if isinstance(owner, str):
                hands.setdefault(owner, set()).add(instance_id)
    return hands


def _alive_hidden_roles(
    identities: Mapping[str, str],
    lord: str,
    viewer_id: str,
    revealed: set[str],
) -> set[str]:
    hidden: set[str] = set()
    for player_id, role in identities.items():
        if player_id in {viewer_id, lord} or player_id in revealed:
            continue
        if role in {"loyalist", "rebel", "spy"}:
            hidden.add(role)
    return hidden


@pytest.fixture(scope="module")
def identity_visible_replay() -> object:
    return record_reference_formal_identity(
        seed=2,
        configuration=FormalIdentityConfiguration.formal_profile(),
        analysis_only=True,
        max_steps=8000,
    )


def test_player_visible_legal_actions_hide_others_identity_and_hands(
    identity_visible_replay: object,
) -> None:
    record = identity_visible_replay
    identities = dict(record.header["initial_configuration"]["identities"])
    lord = str(record.header["initial_configuration"]["lord_player_id"])
    revealed_dead = {
        str(event["target_ids"][0])
        for event in record.events
        if event.get("event_type") == "identity_revealed"
        and isinstance(event.get("target_ids"), (list, tuple))
        and event["target_ids"]
        and isinstance(event.get("payload"), Mapping)
        and event["payload"].get("reason") == "confirmed_death"
    }
    game = _session(8)
    _enter_play(game)
    live_context = game._context()
    assert "identities" not in live_context.metadata
    live_text = json.dumps(
        {
            "context": {
                "mode": live_context.mode,
                "phase": live_context.phase,
                "actor_id": live_context.actor_id,
                "metadata": live_context.metadata,
            },
            "legal": [
                _action_public_fields(action) for action in game.legal_actions()
            ],
        },
        ensure_ascii=False,
        default=str,
    )
    for player_id, role in game.identities_by_player.items():
        if player_id in {game.current_actor_id, game.lord_player_id}:
            continue
        assert role.value not in live_text
    for player_id in game.player_ids:
        if player_id == game.current_actor_id:
            continue
        for instance_id in game.state.card_ids_in(ZoneRef.hand(player_id)):
            assert instance_id not in live_text

    for viewer_id in VALID:
        visible = record.player_visible_payload(
            viewer_id=viewer_id, valid_player_ids=VALID
        )
        hidden_roles = _alive_hidden_roles(
            identities, lord, viewer_id, revealed_dead
        )
        for decision in visible["decisions"]:
            event_start = int(decision.get("event_start") or 0)
            hands = _current_hands_from_events(record.events[:event_start])
            other_hands = set()
            for player_id, cards in hands.items():
                if player_id != viewer_id:
                    other_hands.update(cards)
            side = {
                "payload": decision.get("chosen_action"),
                "legal_actions": decision.get("legal_actions"),
                "context": decision.get("context"),
            }
            for mapping in _identity_mappings(side):
                values = set(mapping.values())
                assert values.isdisjoint({"loyalist", "rebel", "spy"} & hidden_roles)
                if values & _IDENTITY_TOKENS:
                    assert "hidden" in values or values <= {
                        "lord",
                        "hidden",
                        identities[viewer_id],
                    }
            blob = json.dumps(side, ensure_ascii=False, default=str)
            for role in hidden_roles:
                assert role not in blob
            for instance_id in other_hands:
                assert instance_id not in blob


def test_player_visible_context_excludes_full_identity_and_private_hands(
    identity_visible_replay: object,
) -> None:
    record = identity_visible_replay
    identities = dict(record.header["initial_configuration"]["identities"])
    lord = str(record.header["initial_configuration"]["lord_player_id"])
    assert not hasattr(FormalIdentitySession, "player_visible_context")
    game = _session(8)
    assert not hasattr(game, "player_visible_context")
    live = game._context()
    assert "identities" not in live.metadata
    for mapping in _identity_mappings(
        {"mode": live.mode, "metadata": live.metadata}
    ):
        raise AssertionError(f"live context leaked identities mapping: {mapping}")

    for viewer_id in (*VALID, None):
        visible = record.player_visible_payload(
            viewer_id=viewer_id, valid_player_ids=VALID
        )
        header_ids = visible["header"]["initial_configuration"]["identities"]
        for player_id, role in header_ids.items():
            if player_id == lord or player_id == viewer_id:
                assert role == identities[player_id]
            else:
                assert role == "hidden"
        assert dict(header_ids) != dict(identities)
        for decision in visible["decisions"]:
            context = decision.get("context")
            assert isinstance(context, Mapping)
            mappings = _identity_mappings(context)
            assert mappings == []
            event_start = int(decision.get("event_start") or 0)
            hands = _current_hands_from_events(record.events[:event_start])
            other_hands = set()
            for player_id, cards in hands.items():
                if viewer_id is not None and player_id == viewer_id:
                    continue
                other_hands.update(cards)
            blob = json.dumps(context, ensure_ascii=False, default=str)
            for instance_id in other_hands:
                assert instance_id not in blob


def test_player_visible_hash_fields_do_not_encode_secrets(
    identity_visible_replay: object,
) -> None:
    record = identity_visible_replay
    assert not hasattr(FormalIdentitySession, "player_visible_hash")
    first = FormalIdentitySession(
        seed=12,
        configuration=FormalIdentityConfiguration.formal_profile(),
        analysis_only=True,
        session_id="c5-hash-a",
        session_secret=_SECRET_A,
    )
    second = FormalIdentitySession(
        seed=12,
        configuration=FormalIdentityConfiguration.formal_profile(),
        analysis_only=True,
        session_id="c5-hash-b",
        session_secret=_SECRET_B,
    )
    record_a = record_reference_production_batch(12, max_steps=8000, _game=first)
    record_b = record_reference_production_batch(12, max_steps=8000, _game=second)
    allowed_sha256 = {"context_sha256", "player_visible_sha256"}
    for replay in (record, record_a, record_b):
        for viewer_id in (*VALID, None):
            visible = replay.player_visible_payload(
                viewer_id=viewer_id, valid_player_ids=VALID
            )
            assert visible.get("player_visible") is True
            keys = {key for key, _ in _walk(visible)}
            assert keys.isdisjoint(_FORBIDDEN_AUTHORITATIVE_HASH_KEYS)
            assert visible.get("event_hash_chain") == []
            assert "seed" not in visible["header"]
            assert "authoritative_private" not in visible
            assert "player_visible_sha256" in visible
            for key, _item in _walk(visible):
                lowered = key.lower()
                if lowered.endswith("_sha256"):
                    assert lowered in allowed_sha256 or key in {
                        "deck_hash",
                        "ruleset_hash",
                    }
    public_a = record_a.player_visible_payload(
        viewer_id=None, valid_player_ids=VALID
    )
    public_b = record_b.player_visible_payload(
        viewer_id=None, valid_player_ids=VALID
    )
    public_a.pop("player_visible_sha256", None)
    public_b.pop("player_visible_sha256", None)
    assert public_a == public_b


def test_cross_session_secret_public_projection_stable() -> None:
    config = FormalIdentityConfiguration.formal_profile()
    first = FormalIdentitySession(
        seed=12,
        configuration=config,
        analysis_only=True,
        session_id="c5-vis-a",
        session_secret=_SECRET_A,
    )
    second = FormalIdentitySession(
        seed=12,
        configuration=config,
        analysis_only=True,
        session_id="c5-vis-b",
        session_secret=_SECRET_B,
    )
    header_a = {
        "mode_id": first.mode_id,
        "initial_configuration": {
            "identities": {
                pid: role.value for pid, role in first.identities_by_player.items()
            },
            "lord_player_id": first.lord_player_id,
        },
    }
    header_b = {
        "mode_id": second.mode_id,
        "initial_configuration": {
            "identities": {
                pid: role.value for pid, role in second.identities_by_player.items()
            },
            "lord_player_id": second.lord_player_id,
        },
    }
    public_a = _redact_identity_header(header_a, None)
    public_b = _redact_identity_header(header_b, None)
    assert (
        public_a["initial_configuration"]["identities"]
        == public_b["initial_configuration"]["identities"]
    )
    assert first.lord_player_id == second.lord_player_id
    assert dict(first.identities_by_player) == dict(second.identities_by_player)
