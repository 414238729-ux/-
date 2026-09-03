# -*- coding: utf-8 -*-
"""BRIDGE-D exact schema, bounded recording and strict reexecution tests."""

from __future__ import annotations

from copy import deepcopy
import inspect
import json

import pytest

from scripts.sgs_engine import skill_aware_fixed_assignment_full_game_bridge as bridge
from scripts.sgs_engine.authoritative_no_skill_full_game import (
    AuthoritativeNoSkillReplayV2,
)
from scripts.sgs_engine.skill_replay import GeneralProductionReplayEnvelope
from scripts.sgs_engine.skill_aware_fixed_assignment_full_game_bridge_replay import (
    _record_bridge_replay_core,
    AUTHORITATIVE_PRIVATE_SCHEMA_V1,
    BRIDGE_FULL_GAME_REPLAY_REQUIRED_FIELDS_V1,
    BRIDGE_REPLAY_CAPABILITY_V1,
    BridgeFullGameReplayV1,
    BridgeReplayDivergenceError,
    BridgeReplayIdentityError,
    BridgeTraceScope,
    bridge_current_contract_latch_v1,
    record_bounded_skill_aware_fixed_assignment_bridge_replay_v1,
    record_natural_full_game_skill_aware_fixed_assignment_bridge_replay_v1,
    recompute_bridge_replay_identities_v1,
    reexecute_skill_aware_fixed_assignment_bridge_replay_v1,
)


CASES = (
    ("shamoke", "GENERAL_AS_P1"),
    ("shamoke", "GENERAL_AS_P2"),
    ("zhugezhan", "GENERAL_AS_P1"),
    ("zhugezhan", "GENERAL_AS_P2"),
    ("wangyuanji", "GENERAL_AS_P1"),
    ("wangyuanji", "GENERAL_AS_P2"),
)


@pytest.fixture(scope="module")
def bounded_replays() -> dict[tuple[str, str], BridgeFullGameReplayV1]:
    return {
        case: record_bounded_skill_aware_fixed_assignment_bridge_replay_v1(
            general_key=case[0],
            seat_assignment=case[1],
            seed=0,
            max_steps=25,
            cell_id=(
                f"BRIDGE-D-{case[0].upper()}-"
                f"{'P1' if case[1] == 'GENERAL_AS_P1' else 'P2'}-SEED-0"
            ),
        )
        for case in CASES
    }


def test_exact_top_level_schema_and_independent_authority_marker(
    bounded_replays: dict[tuple[str, str], BridgeFullGameReplayV1],
) -> None:
    payload = bounded_replays[CASES[0]].to_dict()
    assert frozenset(payload) == BRIDGE_FULL_GAME_REPLAY_REQUIRED_FIELDS_V1
    assert payload["schema"] == bridge.REPLAY_SCHEMA
    assert payload["replay_version"] == 1
    assert payload["authority_capability"] == BRIDGE_REPLAY_CAPABILITY_V1
    assert payload["trace_scope"] == "BOUNDED_PRODUCTION_TRACE"
    assert payload["mode_id"] == bridge.MODE_ID
    assert "production_replay_v1" not in payload
    assert "event_slice" not in payload


def test_every_required_field_omission_and_unknown_field_fail_closed(
    bounded_replays: dict[tuple[str, str], BridgeFullGameReplayV1],
) -> None:
    source = bounded_replays[CASES[0]].to_dict()
    for field in BRIDGE_FULL_GAME_REPLAY_REQUIRED_FIELDS_V1:
        attacked = deepcopy(source)
        attacked.pop(field)
        with pytest.raises(BridgeReplayDivergenceError):
            BridgeFullGameReplayV1.from_dict(attacked)
    attacked = deepcopy(source)
    attacked["caller_authority"] = True
    with pytest.raises(BridgeReplayDivergenceError, match="字段必须精确匹配"):
        BridgeFullGameReplayV1.from_dict(attacked)


def test_constructor_and_from_dict_have_no_required_defaults() -> None:
    signature = inspect.signature(BridgeFullGameReplayV1)
    assert signature.parameters
    assert all(
        parameter.default is inspect.Parameter.empty
        for parameter in signature.parameters.values()
    )
    with pytest.raises(TypeError):
        BridgeFullGameReplayV1()  # type: ignore[call-arg]


@pytest.mark.parametrize("general_key,seat_assignment", CASES)
def test_six_bounded_canonical_traces_cold_load_and_strict_reexecute(
    bounded_replays: dict[tuple[str, str], BridgeFullGameReplayV1],
    general_key: str,
    seat_assignment: str,
) -> None:
    replay = bounded_replays[(general_key, seat_assignment)]
    encoded = json.dumps(
        replay.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    cold = json.loads(encoded)
    loaded = BridgeFullGameReplayV1.from_dict(cold)
    verification = reexecute_skill_aware_fixed_assignment_bridge_replay_v1(
        loaded.to_dict()
    )
    assert len(loaded.decisions) == 25
    assert verification.step_count == 25
    assert verification.proof_flags["STRICT_REPLAY_PROVEN"] is True
    assert verification.proof_flags["FORMAL_TERMINAL_PROVEN"] is False
    assert verification.proof_flags["FULL_GAME_COMPOSITION_PROVEN"] is False
    assert loaded.to_dict() == BridgeFullGameReplayV1.from_dict(
        json.loads(json.dumps(loaded.to_dict(), ensure_ascii=False))
    ).to_dict()


def test_identity_derivation_and_serialization_are_deterministic(
    bounded_replays: dict[tuple[str, str], BridgeFullGameReplayV1],
) -> None:
    payload = bounded_replays[CASES[0]].to_dict()
    reversed_payload = dict(reversed(tuple(payload.items())))
    assert recompute_bridge_replay_identities_v1(payload) == payload
    assert recompute_bridge_replay_identities_v1(reversed_payload) == payload
    assert bridge.canonical_json(payload) == bridge.canonical_json(reversed_payload)


def test_zuilun_private_public_boundary_and_controller_visibility(
    bounded_replays: dict[tuple[str, str], BridgeFullGameReplayV1],
) -> None:
    payload = bounded_replays[("zhugezhan", "GENERAL_AS_P1")].to_dict()
    selections = payload["authoritative_private"]["private_skill_selections"]
    assert len(selections) >= 1
    opaque_decision = next(
        decision
        for decision in payload["decisions"]
        if decision["chosen_semantic_projection"]["projection_kind"]
        == "private_player_choice"
    )
    opaque = opaque_decision["chosen_semantic_projection"]["projection"]
    assert frozenset(opaque) == bridge.PRIVATE_SELECTION_ALLOWED_FIELDS
    serialized_public = bridge.canonical_json(
        {
            "public_context": opaque_decision["public_context"],
            "legal": opaque_decision["legal_action_projections"],
            "chosen": opaque_decision["chosen_semantic_projection"],
        }
    )
    for forbidden in bridge.PRIVATE_SELECTION_FORBIDDEN_FIELDS:
        assert f'"{forbidden}"' not in serialized_public
    assert "selected_card_ids" not in serialized_public
    assert "observed_card_ids" not in serialized_public
    projections = tuple(
        PublicOpaqueChoiceProjection.from_dict(item["projection"])
        for item in opaque_decision["legal_action_projections"]
    )
    context = bridge.PublicActionContextV1.from_dict(opaque_decision["public_context"])
    private_state_a = {"selected": selections[0]["selected_card_ids"]}
    private_state_b = {"selected": list(reversed(selections[0]["observed_card_ids"]))}
    assert private_state_a != private_state_b
    controller = bridge.SkillAwareFixedAssignmentAcceptanceControllerV1()
    assert controller.choose(projections, context) == controller.choose(projections, context)


def test_authoritative_private_is_typed_versioned_and_participant_scoped(
    bounded_replays: dict[tuple[str, str], BridgeFullGameReplayV1],
) -> None:
    private = bounded_replays[CASES[0]].to_dict()["authoritative_private"]
    assert private["schema"] == AUTHORITATIVE_PRIVATE_SCHEMA_V1
    assert private["version"] == 1
    assert private["participant_ids"] == ["p1", "p2"]
    assert frozenset(private) == {
        "schema",
        "version",
        "participant_ids",
        "signing_authority",
        "initial_private_state",
        "final_private_state",
        "private_skill_selections",
    }
    text = bridge.canonical_json(private)
    for forbidden in ("pickle", "callable", "factory", "session_object", "repr"):
        assert forbidden not in text


def test_random_event_skill_and_production_authority_are_live_bound(
    bounded_replays: dict[tuple[str, str], BridgeFullGameReplayV1],
) -> None:
    payload = bounded_replays[("zhugezhan", "GENERAL_AS_P1")].to_dict()
    assert payload["random_consumptions"]
    assert payload["events"]
    assert payload["production_authority_trace"]
    assert payload["skill_decision_authority_trace"]
    assert len(payload["production_authority_trace"]) == len(payload["decisions"])
    assert [item["index"] for item in payload["random_consumptions"]] == list(
        range(len(payload["random_consumptions"]))
    )
    assert [item["sequence"] for item in payload["events"]] == list(
        range(1, len(payload["events"]) + 1)
    )


def test_bounded_cannot_be_promoted_to_natural_even_with_outer_rehash(
    bounded_replays: dict[tuple[str, str], BridgeFullGameReplayV1],
) -> None:
    attacked = bounded_replays[CASES[0]].to_dict()
    attacked["trace_scope"] = BridgeTraceScope.NATURAL_FULL_GAME.value
    attacked["outcome"].update(
        {
            "trace_scope": BridgeTraceScope.NATURAL_FULL_GAME.value,
            "finished": True,
            "winner": "p1",
            "finish_reason": "forged_terminal",
        }
    )
    attacked = recompute_bridge_replay_identities_v1(attacked)
    loaded = BridgeFullGameReplayV1.from_dict(attacked)
    # BRIDGE-E-AUDIT-001 remediation 后，generic strict reexecutor 在更早的
    # symmetric canonical cell 绑定处就拒绝 bounded->natural 提升（bounded
    # cell_id 不是该 General/seat/seed 的 BASELINE_18 canonical cell）；旧路径
    # 的 outcome 不匹配仍是后续防线，两者都证明提升不可能成功。
    with pytest.raises(
        BridgeReplayDivergenceError,
        match="outcome不匹配|canonical派生不匹配|BASELINE_18",
    ):
        reexecute_skill_aware_fixed_assignment_bridge_replay_v1(loaded)


@pytest.mark.parametrize(
    "remaining_marker",
    (
        "contract_id",
        "replay_version",
        "mode_id",
        "controller_id",
        "authority_capability",
        "trace_scope",
        "bridge_skill_registry_identity",
        "bridge_authority_profile_identity",
        "assignment",
    ),
)
def test_current_contract_latch_survives_marker_stripping(
    bounded_replays: dict[tuple[str, str], BridgeFullGameReplayV1],
    remaining_marker: str,
) -> None:
    source = bounded_replays[CASES[0]].to_dict()
    marker_value = (
        source["initialization"]["assignment"]
        if remaining_marker == "assignment"
        else source[remaining_marker]
    )
    stripped: dict[str, object]
    if remaining_marker == "assignment":
        stripped = {"initialization": {"assignment": marker_value}}
    else:
        stripped = {remaining_marker: marker_value}
    assert bridge_current_contract_latch_v1(stripped) is True
    with pytest.raises(BridgeReplayDivergenceError):
        BridgeFullGameReplayV1.from_dict(stripped)


def test_cross_parser_isolation_and_downgrade_rejection(
    bounded_replays: dict[tuple[str, str], BridgeFullGameReplayV1],
) -> None:
    payload = bounded_replays[CASES[0]].to_dict()
    with pytest.raises(Exception):
        AuthoritativeNoSkillReplayV2.from_dict(payload)
    with pytest.raises(Exception):
        GeneralProductionReplayEnvelope.from_dict(payload)
    no_skill_marker = {
        "header": {
            "schema_version": "sgs-authoritative-no-skill-full-game-replay-v2"
        }
    }
    general_marker = {"schema": "sgs-general-production-replay-v1"}
    assert bridge_current_contract_latch_v1(no_skill_marker) is False
    assert bridge_current_contract_latch_v1(general_marker) is False
    with pytest.raises(BridgeReplayDivergenceError):
        BridgeFullGameReplayV1.from_dict(no_skill_marker)
    with pytest.raises(BridgeReplayDivergenceError):
        BridgeFullGameReplayV1.from_dict(general_marker)
    attacked = deepcopy(payload)
    attacked["schema"] = "sgs-authoritative-no-skill-full-game-replay-v2"
    attacked = recompute_bridge_replay_identities_v1(attacked)
    assert bridge_current_contract_latch_v1(attacked) is True
    with pytest.raises(BridgeReplayDivergenceError):
        BridgeFullGameReplayV1.from_dict(attacked)
    attacked = deepcopy(payload)
    attacked.pop("schema")
    assert bridge_current_contract_latch_v1(attacked) is True
    with pytest.raises(BridgeReplayDivergenceError):
        BridgeFullGameReplayV1.from_dict(attacked)


def test_wrong_current_implementation_identity_fails_preflight(
    bounded_replays: dict[tuple[str, str], BridgeFullGameReplayV1],
) -> None:
    attacked = bounded_replays[CASES[0]].to_dict()
    attacked["implementation_identity"] = "0" * 64
    attacked = recompute_bridge_replay_identities_v1(attacked)
    loaded = BridgeFullGameReplayV1.from_dict(attacked)
    with pytest.raises(BridgeReplayIdentityError, match="implementation_identity"):
        reexecute_skill_aware_fixed_assignment_bridge_replay_v1(loaded)


# Imported here to keep the public/private test's controller inputs explicit.
from scripts.sgs_engine.skill_aware_fixed_assignment_full_game_bridge import (  # noqa: E402
    PublicOpaqueChoiceProjection,
)


# ---------------------------------------------------------------------------
# BRIDGE-E-AUDIT-002 remediation: NATURAL_FULL_GAME construction-layer
# fail-closed guard.  The private recording core must never mint a NATURAL
# artifact from a non-terminal, non-pristine or cell-inconsistent session,
# while the bounded workflow stays untouched.
# ---------------------------------------------------------------------------


def _fresh_shamoke_p2_session(seed: int = 1):
    return bridge.create_skill_aware_fixed_assignment_duel_session_v1(
        seed=seed, general_key="shamoke", seat_assignment="GENERAL_AS_P2"
    )


def _controller_advance(session, steps: int):
    """Drive a session exactly like the BRIDGE-C public controller loop."""
    for _ in range(steps):
        record = session.acceptance_decision_record_v1()
        session.step(record.chosen_action_id)
    return session


def _private_natural_core(session, **overrides):
    kwargs = {
        "seed": 1,
        "scope": BridgeTraceScope.NATURAL_FULL_GAME,
        "cell_id": "B18-005",
        "max_steps": bridge.MAX_STEPS,
        "require_terminal": True,
    }
    kwargs.update(overrides)
    return _record_bridge_replay_core(session, **kwargs)


def test_audit002_fresh_session_require_terminal_false_fails() -> None:
    # Attack 1: fresh session, NATURAL, require_terminal=False -> fail closed.
    with pytest.raises(BridgeReplayDivergenceError, match="formal terminal"):
        _private_natural_core(_fresh_shamoke_p2_session(), require_terminal=False)


def test_audit002_advanced_one_step_fails_before_recording() -> None:
    # Attack 2: one controller step then NATURAL+terminal must be rejected
    # before the recording loop drives the session any further.
    session = _controller_advance(_fresh_shamoke_p2_session(), 1)
    with pytest.raises(BridgeReplayDivergenceError, match="step_count"):
        _private_natural_core(session)
    assert session.step_count == 1
    assert session.is_finished is False


def test_audit002_advanced_five_steps_require_terminal_false_fails() -> None:
    # Attack 3: five steps in, require_terminal=False -> fail closed.
    session = _controller_advance(_fresh_shamoke_p2_session(), 5)
    with pytest.raises(BridgeReplayDivergenceError):
        _private_natural_core(session, require_terminal=False)
    assert session.step_count == 5


def test_audit002_wrong_cap_fails() -> None:
    # Attack 4: NATURAL max_steps != 2000 (and bool cannot masquerade).
    with pytest.raises(BridgeReplayDivergenceError, match="max_steps"):
        _private_natural_core(_fresh_shamoke_p2_session(), max_steps=1999)
    with pytest.raises(BridgeReplayDivergenceError, match="max_steps"):
        _private_natural_core(_fresh_shamoke_p2_session(), max_steps=True)


def test_audit002_forged_cell_id_fails() -> None:
    # Attack 5: forged cell_id is caught against frozen BASELINE_18 authority.
    with pytest.raises(BridgeReplayDivergenceError, match="BASELINE_18"):
        _private_natural_core(
            _fresh_shamoke_p2_session(), cell_id="FORGED-CELL"
        )


def test_audit002_seed_and_non_canonical_session_fail() -> None:
    # Caller seed must agree with the canonical session RNG seed.
    with pytest.raises(BridgeReplayDivergenceError, match="RNG seed"):
        _private_natural_core(_fresh_shamoke_p2_session(seed=1), seed=0)

    class _NotACanonicalSession:
        pass

    # A duck-typed stand-in is rejected regardless of supplied fields.
    with pytest.raises(BridgeReplayDivergenceError, match="canonical Bridge session"):
        _private_natural_core(_NotACanonicalSession())


def test_audit002_mutation_without_step_count_is_still_rejected() -> None:
    # The guard must not rely on step_count alone: corrupting the signed
    # initial execution authority while leaving step_count at 0 still fails.
    session = _fresh_shamoke_p2_session()
    assert session.step_count == 0
    session._initial_execution_identity = "0" * 64
    with pytest.raises(BridgeReplayDivergenceError, match="execution authority"):
        _private_natural_core(session)


def test_audit002_legit_public_natural_recorder_passes() -> None:
    # Attack battery item 6: the legitimate public natural recorder (E-005,
    # the shortest Shamoke cell) still records a real formal terminal.
    replay = record_natural_full_game_skill_aware_fixed_assignment_bridge_replay_v1(
        general_key="shamoke",
        seat_assignment="GENERAL_AS_P2",
        seed=1,
        cell_id="B18-005",
    )
    assert replay.trace_scope is BridgeTraceScope.NATURAL_FULL_GAME
    assert replay.cell_id == "B18-005"
    assert replay.outcome["finished"] is True
    assert replay.outcome["winner"] in bridge.PARTICIPANT_IDS
    assert replay.outcome["step_count"] < bridge.MAX_STEPS


def test_audit002_legit_bounded_recorder_workflow_unaffected() -> None:
    # Attack battery item 7: bounded recording never enters the NATURAL guard.
    replay = record_bounded_skill_aware_fixed_assignment_bridge_replay_v1(
        general_key="shamoke",
        seat_assignment="GENERAL_AS_P2",
        seed=0,
        max_steps=25,
        cell_id="BRIDGE-D-SHAMOKE-P2-SEED-0",
    )
    assert replay.trace_scope is BridgeTraceScope.BOUNDED_PRODUCTION_TRACE
    assert len(replay.decisions) == 25
    assert replay.outcome["finished"] is False
