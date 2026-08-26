# -*- coding: utf-8 -*-
"""Stage 1/2 contract tests for authoritative no-skill full-game V1.

These are deliberately not a 21 x 6 acceptance run.  They prove the V2
boundary and one canonical cell, while the aggregate gate remains false until
the frozen 126-cell contract is actually supplied and reexecuted.
"""

from __future__ import annotations

import pytest

import scripts.sgs_engine.authoritative_no_skill_full_game as aggregate
from scripts.sgs_engine.actions import ActionContext, ActionType, LegalAction
from scripts.sgs_engine.mode_identity import (
    inspect_formal_eight_player_identity_readiness,
    inspect_formal_identity_readiness,
)
from scripts.sgs_engine.mode_identity_heir import (
    inspect_formal_heir_and_spy_choice_identity_readiness,
)
from scripts.sgs_engine.production_batch import FORMAL_NO_SKILL_DUEL_MODE
from scripts.sgs_engine.production_replay import reexecute_production_replay


@pytest.fixture(scope="module")
def duel_cell() -> aggregate.AuthoritativeNoSkillAcceptanceCellV1:
    return aggregate.AuthoritativeNoSkillFullGameOrchestrator().run_cell(
        FORMAL_NO_SKILL_DUEL_MODE, 0
    )


def test_replay_v1_remains_compatible_and_v2_wraps_it(
    duel_cell: aggregate.AuthoritativeNoSkillAcceptanceCellV1,
) -> None:
    legacy = reexecute_production_replay(duel_cell.replay_v2.production_replay_v1)
    assert legacy.verified is True
    assert duel_cell.replay_v2.header["schema_version"] == (
        aggregate.AUTHORITATIVE_NO_SKILL_REPLAY_V2_SCHEMA
    )
    assert duel_cell.replay_v2.header["mode_contract_id"] == (
        f"{aggregate.AUTHORITATIVE_NO_SKILL_FULL_GAME_V1_CONTRACT_ID}:"
        f"{FORMAL_NO_SKILL_DUEL_MODE}"
    )
    assert duel_cell.replay_v2.header["production_replay_v1_sha256"] == (
        duel_cell.replay_v2.production_replay_v1.record_sha256
    )
    assert duel_cell.replay_v2.header["ruleset_identity"] == (
        duel_cell.replay_v2.production_replay_v1.header["ruleset_hash"]
    )
    loaded = aggregate.AuthoritativeNoSkillReplayV2.from_dict(
        duel_cell.replay_v2.to_dict()
    )
    assert loaded.replay_v2_sha256 == duel_cell.replay_v2.replay_v2_sha256


def test_v2_identity_mismatch_fails_before_v1_reexecution(
    duel_cell: aggregate.AuthoritativeNoSkillAcceptanceCellV1,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden_v1_reexecution(object_: object) -> object:
        raise AssertionError("identity mismatch must fail before v1 rebuild")

    monkeypatch.setattr(aggregate, "implementation_identity", lambda: "0" * 64)
    monkeypatch.setattr(
        aggregate, "reexecute_production_replay", forbidden_v1_reexecution
    )
    with pytest.raises(aggregate.AuthoritativeNoSkillReplayV2IdentityError):
        aggregate.reexecute_authoritative_no_skill_replay_v2(duel_cell.replay_v2)


def test_current_aggregate_reexecutor_refuses_bare_v1_artifacts(
    duel_cell: aggregate.AuthoritativeNoSkillAcceptanceCellV1,
) -> None:
    with pytest.raises(TypeError):
        aggregate.reexecute_authoritative_no_skill_replay_v2(
            duel_cell.replay_v2.production_replay_v1  # type: ignore[arg-type]
        )


def test_sealed_six_mode_registry_rejects_any_extra_mode() -> None:
    mode_ids = tuple(
        spec.mode_id for spec in aggregate.AUTHORITATIVE_NO_SKILL_MODE_REGISTRY_V1
    )
    assert mode_ids == (
        FORMAL_NO_SKILL_DUEL_MODE,
        "formal_no_skill_2v2",
        "formal_no_skill_doudizhu",
        "formal_no_skill_identity_5p",
        "formal_no_skill_identity_8p",
        "formal_no_skill_identity_8p_heir_and_spy_choice",
    )
    with pytest.raises(aggregate.AuthoritativeNoSkillFullGameError):
        aggregate.canonical_no_skill_mode_v1("C8")


def test_frozen_acceptance_seed_contract_and_matrix_cardinality() -> None:
    assert aggregate.AUTHORITATIVE_NO_SKILL_ACCEPTANCE_SEEDS_V1 == (
        *range(20),
        49,
    )
    assert len(aggregate.AUTHORITATIVE_NO_SKILL_ACCEPTANCE_SEEDS_V1) == 21
    assert len(aggregate.AuthoritativeNoSkillAcceptanceMatrixV1.required_pairs()) == 126


def test_controller_receives_no_private_metadata_and_returns_issued_action_id() -> None:
    controller = aggregate.NoSkillAcceptanceControllerV1()
    context = ActionContext(
        mode=FORMAL_NO_SKILL_DUEL_MODE,
        phase="play",
        actor_id="p1",
        metadata={"private_hand_or_deck_material": "must-not-reach-controller"},
    )
    public = aggregate.PublicActionContextV1.from_action_context(context)
    assert not hasattr(public, "metadata")
    legal = (
        LegalAction(action_type=ActionType.PASS, actor_id="p1", action_id="issued-id"),
    )
    assert controller.choose_action_id(legal, public) == "issued-id"
    assert controller.choose(legal, context).action_id == "issued-id"


def test_orchestrator_rejects_fixture_and_premutated_session_ingress() -> None:
    orchestrator = aggregate.AuthoritativeNoSkillFullGameOrchestrator()
    with pytest.raises(aggregate.AuthoritativeNoSkillFullGameError, match="fixture"):
        orchestrator.run_cell(FORMAL_NO_SKILL_DUEL_MODE, 0, fixture=object())
    with pytest.raises(aggregate.AuthoritativeNoSkillFullGameError, match="预突变"):
        orchestrator.run_cell(
            FORMAL_NO_SKILL_DUEL_MODE, 0, premutated_session=object()
        )


def test_single_cell_strict_reexecute_and_serialized_schema(
    duel_cell: aggregate.AuthoritativeNoSkillAcceptanceCellV1,
) -> None:
    payload = duel_cell.to_dict()
    assert payload["cell_schema_version"] == (
        aggregate.AUTHORITATIVE_NO_SKILL_CELL_REPORT_SCHEMA_V1
    )
    assert payload["mode_id"] == FORMAL_NO_SKILL_DUEL_MODE
    assert payload["controller_id"] == aggregate.NO_SKILL_ACCEPTANCE_CONTROLLER_V1_ID
    assert payload["terminal_reason"]
    assert payload["action_count"] > 0
    assert payload["event_count"] > 0
    assert payload["rng_count"] > 0
    assert set(payload["lifecycle_evidence"]) == {
        "response",
        "delayed",
        "equipment",
        "damage",
        "dying",
        "rescue",
        "death",
        "victory",
        "reshuffle",
        "deck_exhaustion",
    }
    assert payload["proof_flags"] == {
        "PRODUCTION_REACHABLE": True,
        "NATURALLY_REACHED_IN_ACCEPTANCE": True,
        "FINISHED_STATE_INVARIANTS_PROVEN": True,
        "STRICT_REPLAY_PROVEN": True,
        "FULL_GAME_COMPOSITION_PROVEN": True,
    }


def test_derived_gates_stay_false_for_smoke_and_have_machine_true_condition(
    duel_cell: aggregate.AuthoritativeNoSkillAcceptanceCellV1,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    matrix = aggregate.AuthoritativeNoSkillAcceptanceMatrixV1((duel_cell,))
    false_gates = matrix.derived_gates()
    assert false_gates.authoritative_no_skill_full_game_v1_ready is False
    assert false_gates.authoritative_no_skill_multiplayer_v1_proven is False
    assert len(false_gates.missing_cells) == 125
    assert matrix.to_dict()["cells"][0]["proof_flags"][
        "FULL_GAME_COMPOSITION_PROVEN"
    ] is True

    # Isolate the predicate in this unit test.  The production classmethod is
    # sealed to 21 x 6; its unmodified result above remains false for smoke.
    monkeypatch.setattr(
        aggregate.AuthoritativeNoSkillAcceptanceMatrixV1,
        "required_pairs",
        staticmethod(lambda: frozenset({(duel_cell.mode_id, duel_cell.seed)})),
    )
    true_gates = matrix.derived_gates()
    assert true_gates.authoritative_no_skill_full_game_v1_ready is True
    assert true_gates.authoritative_no_skill_multiplayer_v1_proven is False


def test_matrix_roundtrip_preserves_per_cell_full_flag_but_not_partial_aggregate(
    duel_cell: aggregate.AuthoritativeNoSkillAcceptanceCellV1,
) -> None:
    matrix = aggregate.AuthoritativeNoSkillAcceptanceMatrixV1((duel_cell,))
    payload = matrix.to_dict()
    loaded = aggregate.AuthoritativeNoSkillAcceptanceMatrixV1.from_dict(payload)
    assert loaded.cells[0].proof_flags()["FULL_GAME_COMPOSITION_PROVEN"] is True
    assert payload["derived_gates"]["authoritative_no_skill_full_game_v1_ready"] is False


def test_matrix_rejects_tampered_per_cell_full_flag(
    duel_cell: aggregate.AuthoritativeNoSkillAcceptanceCellV1,
) -> None:
    matrix = aggregate.AuthoritativeNoSkillAcceptanceMatrixV1((duel_cell,))
    payload = matrix.to_dict()
    payload["cells"][0]["proof_flags"]["FULL_GAME_COMPOSITION_PROVEN"] = False
    with pytest.raises(aggregate.AuthoritativeNoSkillFullGameError):
        aggregate.AuthoritativeNoSkillAcceptanceMatrixV1.from_dict(payload)


def test_c5_c6_c7_keep_old_broad_flags_false() -> None:
    for readiness in (
        inspect_formal_identity_readiness(),
        inspect_formal_eight_player_identity_readiness(),
        inspect_formal_heir_and_spy_choice_identity_readiness(),
    ):
        assert readiness.multi_player_production_proven is False
        assert readiness.authoritative_full_game_core is False
