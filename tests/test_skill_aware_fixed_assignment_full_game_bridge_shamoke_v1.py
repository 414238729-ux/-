# -*- coding: utf-8 -*-
"""BRIDGE-E Shamoke natural full-game composition, strict replay and Jili witness.

Scope is exactly SHAMOKE_BASELINE_SUBMATRIX_6 (E-001..E-006 == B18-001..B18-006).
Every cell is a real natural formal duel driven only by the BRIDGE-C public
controller through the frozen Jili production runtime to a formal terminal, then
strictly reexecuted from a cold load.  No fixture, premutation, manual event
injection, seed search or sentinel discovery is used or permitted here.
"""

from __future__ import annotations

from copy import deepcopy
import json

import pytest

from scripts.sgs_engine import skill_aware_fixed_assignment_full_game_bridge as bridge
from scripts.sgs_engine.formal_duel import implementation_identity
from scripts.sgs_engine.skill_aware_fixed_assignment_full_game_bridge_replay import (
    SKILL_EVENT_COVERAGE_PROVEN,
    BridgeFullGameCellProofV1,
    BridgeFullGameReplayV1,
    BridgeReplayDivergenceError,
    BridgeReplayIdentityError,
    BridgeTraceScope,
    derive_bridge_full_game_cell_proof_v1,
    record_natural_full_game_skill_aware_fixed_assignment_bridge_replay_v1,
    recompute_bridge_replay_identities_v1,
    reexecute_skill_aware_fixed_assignment_bridge_replay_v1,
)


JILI = "sgs_skill_jili"
ZERO64 = "0" * 64

# Exact BRIDGE-E submatrix in frozen execution order (section 15).  The E labels
# map one-to-one onto the first six BASELINE_18 cells (section 1).
SHAMOKE_SUBMATRIX = (
    ("E-001", "B18-001", "GENERAL_AS_P1", 0),
    ("E-002", "B18-002", "GENERAL_AS_P1", 1),
    ("E-003", "B18-003", "GENERAL_AS_P1", 49),
    ("E-004", "B18-004", "GENERAL_AS_P2", 0),
    ("E-005", "B18-005", "GENERAL_AS_P2", 1),
    ("E-006", "B18-006", "GENERAL_AS_P2", 49),
)
LABELS = tuple(item[0] for item in SHAMOKE_SUBMATRIX)
# Representative cell for the deep full-game tamper battery (section 16): the
# shortest natural game keeps the adversarial reexecutions cheap.
TAMPER_LABEL = "E-005"


def _cold_round_trip(replay: BridgeFullGameReplayV1) -> BridgeFullGameReplayV1:
    encoded = json.dumps(
        replay.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return BridgeFullGameReplayV1.from_dict(json.loads(encoded))


@pytest.fixture(scope="module")
def natural_replays() -> dict[str, BridgeFullGameReplayV1]:
    return {
        label: record_natural_full_game_skill_aware_fixed_assignment_bridge_replay_v1(
            general_key="shamoke",
            seat_assignment=seat,
            seed=seed,
            cell_id=b18,
        )
        for label, b18, seat, seed in SHAMOKE_SUBMATRIX
    }


@pytest.fixture(scope="module")
def cell_proofs(
    natural_replays: dict[str, BridgeFullGameReplayV1],
) -> dict[str, BridgeFullGameCellProofV1]:
    return {
        label: derive_bridge_full_game_cell_proof_v1(
            _cold_round_trip(natural_replays[label]).to_dict()
        )
        for label in LABELS
    }


def _jili_witnesses(proof: BridgeFullGameCellProofV1) -> tuple[object, ...]:
    return tuple(w for w in proof.witnesses if w["skill_id"] == JILI)


def _legal_ops(witness) -> tuple[str, ...]:
    return tuple(item["operation"] for item in witness["signed_legal_set"])


def _legal_skills(witness) -> tuple[str, ...]:
    return tuple(item["public_skill_id"] for item in witness["signed_legal_set"])


def _condition(witness) -> dict[str, object]:
    return dict(witness["condition_facts"])


# ---------------------------------------------------------------------------
# Scope, canonical identity and natural-only ingress (sections 1-4)
# ---------------------------------------------------------------------------


def test_submatrix_cell_ids_scope_and_natural_only_markers(
    natural_replays: dict[str, BridgeFullGameReplayV1],
) -> None:
    live_identity = implementation_identity()
    for label, b18, seat, seed in SHAMOKE_SUBMATRIX:
        replay = natural_replays[label]
        payload = replay.to_dict()
        assert replay.cell_id == b18
        assert replay.seed == seed
        assert replay.trace_scope is BridgeTraceScope.NATURAL_FULL_GAME
        assert payload["trace_scope"] == "NATURAL_FULL_GAME"
        assert payload["outcome"]["trace_scope"] == "NATURAL_FULL_GAME"
        # The replay binds to the live post-BRIDGE-E development identity, never
        # to the BRIDGE-D identity or the global frozen pin (section 4).
        assert replay.implementation_identity == live_identity
        assert replay.implementation_identity != (
            "6e5c76f2d2962cb81c2c56056b14fc1d53d19788e71d65858f0899c87907f0b0"
        )
        assert replay.implementation_identity != (
            "da73a75e195153f61a89012adf9f84b309194e2a71889ef2059fb847dbfa22d1"
        )
        initialization = payload["initialization"]
        for marker in (
            "analysis_only",
            "fixture_applied",
            "premutation_applied",
            "manual_event_injection",
        ):
            assert initialization[marker] is False
        assert initialization["assignment"]["general_key"] == "shamoke"
        assert initialization["assignment"]["seat_assignment"] == seat


def test_natural_recorder_rejects_non_baseline_seed_and_wrong_cap() -> None:
    # Section 11: no sentinel/seed search. A non-baseline seed fails closed.
    with pytest.raises(BridgeReplayDivergenceError):
        record_natural_full_game_skill_aware_fixed_assignment_bridge_replay_v1(
            general_key="shamoke", seat_assignment="GENERAL_AS_P1", seed=2
        )
    # Section 2: the hard cap is exactly the frozen 2000 steps.
    with pytest.raises(BridgeReplayDivergenceError):
        record_natural_full_game_skill_aware_fixed_assignment_bridge_replay_v1(
            general_key="shamoke",
            seat_assignment="GENERAL_AS_P1",
            seed=0,
            max_steps=25,
        )


def test_wrong_implementation_identity_fails_preflight(
    natural_replays: dict[str, BridgeFullGameReplayV1],
) -> None:
    attacked = natural_replays[TAMPER_LABEL].to_dict()
    attacked["implementation_identity"] = ZERO64
    attacked = recompute_bridge_replay_identities_v1(attacked)
    with pytest.raises(BridgeReplayIdentityError, match="implementation_identity"):
        reexecute_skill_aware_fixed_assignment_bridge_replay_v1(
            BridgeFullGameReplayV1.from_dict(attacked)
        )


# ---------------------------------------------------------------------------
# Natural formal terminal and controller termination (sections 2, 8, 12)
# ---------------------------------------------------------------------------


def test_six_cells_reach_natural_formal_terminal_within_cap(
    cell_proofs: dict[str, BridgeFullGameCellProofV1],
) -> None:
    for label in LABELS:
        proof = cell_proofs[label]
        assert proof.trace_scope == "NATURAL_FULL_GAME"
        assert proof.steps > 0
        # Natural terminal, never the 2000-step cap and never a synthetic draw.
        assert proof.steps < bridge.MAX_STEPS
        assert proof.winner in bridge.PARTICIPANT_IDS
        assert proof.finish_reason == "opponent_confirmed_dead"
        flags = proof.strict_replay_proof_flags
        assert flags["NATURAL_FULL_GAME"] is True
        assert flags["FORMAL_TERMINAL_PROVEN"] is True
        assert flags["FULL_GAME_COMPOSITION_PROVEN"] is True


def test_controller_terminates_without_loop_or_blowup(
    cell_proofs: dict[str, BridgeFullGameCellProofV1],
) -> None:
    # Section 12: the BRIDGE-C controller drives the whole duel to a formal
    # terminal in every cell. Reaching a real terminal far below the cap proves
    # there is no select/unselect, equipment, phase-pass, skill ACTIVATE/PASS,
    # target-oscillation or response deadlock and no max_steps blowup.
    steps = {label: cell_proofs[label].steps for label in LABELS}
    assert all(count < bridge.MAX_STEPS for count in steps.values())
    assert max(steps.values()) <= 500
    assert all(cell_proofs[label].winner is not None for label in LABELS)


def test_terminal_cleanup_invariants_six_of_six(
    cell_proofs: dict[str, BridgeFullGameCellProofV1],
) -> None:
    required_true = (
        "finished",
        "engine_finished_invariants_passed",
        "skill_pending_none",
        "skill_trigger_queue_empty",
        "pending_private_card_selection_none",
        "pending_skill_hp_loss_none",
        "pending_card_continuation_none",
        "end_phase_dispatch_state_none",
        "continuation_in_progress_none",
        "response_window_none",
        "pending_dying_none",
        "processing_empty",
        "revealed_empty",
        "post_finish_step_blocked",
        "post_finish_action_surface_blocked",
    )
    for label in LABELS:
        terminal = cell_proofs[label].terminal_invariants
        assert terminal["phase"] == "finished"
        assert terminal["winner"] == cell_proofs[label].winner
        assert terminal["finish_reason"] == cell_proofs[label].finish_reason
        for name in required_true:
            assert terminal[name] is True, f"{label} terminal invariant {name} 必须为true"


# ---------------------------------------------------------------------------
# Strict replay and full-game cell proof flags (sections 9, 10)
# ---------------------------------------------------------------------------


def test_strict_replay_six_of_six(
    cell_proofs: dict[str, BridgeFullGameCellProofV1],
) -> None:
    for label in LABELS:
        proof = cell_proofs[label]
        flags = proof.strict_replay_proof_flags
        assert flags["STRICT_REPLAY_PROVEN"] is True
        assert flags["PRODUCTION_REACHABLE"] is True
        assert flags["ACTION_AUTHORITY_TRACE_PROVEN"] is True
        assert flags["SKILL_DECISION_AUTHORITY_TRACE_PROVEN"] is True
        assert proof.decision_count == proof.steps
        assert proof.records_identity and proof.execution_identity and proof.replay_identity


def test_explicit_cold_load_strict_reexecute_round_trip(
    natural_replays: dict[str, BridgeFullGameReplayV1],
) -> None:
    replay = natural_replays[TAMPER_LABEL]
    cold = _cold_round_trip(replay)
    assert cold.to_dict() == replay.to_dict()
    verification = reexecute_skill_aware_fixed_assignment_bridge_replay_v1(cold.to_dict())
    assert verification.step_count == len(replay.decisions)
    assert verification.finished is True
    assert verification.proof_flags["STRICT_REPLAY_PROVEN"] is True
    assert verification.proof_flags["FORMAL_TERMINAL_PROVEN"] is True


def test_full_game_cell_proof_section_ten_flags(
    cell_proofs: dict[str, BridgeFullGameCellProofV1],
) -> None:
    always_true = (
        "PRODUCTION_REACHABLE",
        "NATURAL_FULL_GAME",
        "GENERAL_ASSIGNMENT_PROVEN",
        "GENERAL_BASE_STATS_PROVEN",
        "GENERAL_SKILL_DERIVATION_PROVEN",
        "DYNAMIC_SKILL_AUTHORITY_PROVEN",
        "PUBLIC_CONTROLLER_PROVEN",
        "ACTION_AUTHORITY_TRACE_PROVEN",
        "SKILL_DECISION_AUTHORITY_TRACE_PROVEN",
        "FORMAL_TERMINAL_PROVEN",
        "STRICT_REPLAY_PROVEN",
        "FULL_GAME_COMPOSITION_PROVEN",
    )
    for label in LABELS:
        proof = cell_proofs[label]
        for name in always_true:
            assert proof.proof_flags[name] is True, f"{label} {name} 必须为true"
        # Shamoke naturally triggers Jili in every frozen baseline cell, so the
        # derived coverage is PROVEN (never a hard-coded NOT_REQUIRED written true).
        assert proof.skill_event_coverage == SKILL_EVENT_COVERAGE_PROVEN
        assert proof.proof_flags["SKILL_EVENT_COVERAGE_PROVEN"] is True


def test_shamoke_frozen_semantics_hold_in_full_game(
    natural_replays: dict[str, BridgeFullGameReplayV1],
) -> None:
    for label in LABELS:
        initialization = natural_replays[label].to_dict()["initialization"]
        base = initialization["base_skill_derivation"]
        assert base["general_key"] == "shamoke"
        assert base["base_skill_ids"] == [JILI]
        assert base["no_skill_base_skill_ids"] == []
        reconcile = initialization["initial_dynamic_reconcile_result"]
        general_pid = base["general_player_id"]
        no_skill_pid = base["no_skill_player_id"]
        assert reconcile["player_effective_skills"][general_pid] == [JILI]
        assert reconcile["player_effective_skills"][no_skill_pid] == []
        # Shamoke has no lawful dynamic grant; every grant map stays empty.
        assert all(grants == [] for grants in reconcile["dynamic_grants"].values())


# ---------------------------------------------------------------------------
# EV-G1-JILI-01 witness re-derived from strict replay (sections 6, 7)
# ---------------------------------------------------------------------------


def test_jili_witness_re_derived_per_cell(
    cell_proofs: dict[str, BridgeFullGameCellProofV1],
) -> None:
    for label in LABELS:
        proof = cell_proofs[label]
        witnesses = _jili_witnesses(proof)
        assert witnesses, f"{label} 必须自然观察到至少一个 Jili witness"
        for witness in witnesses:
            assert witness["cell_id"] == proof.cell_id
            assert witness["skill_id"] == JILI
            assert witness["owner_id"] in bridge.PARTICIPANT_IDS
            facts = _condition(witness)
            # Frozen Jili trigger: turn_card_count == pre_attack_range == X, X >= 1.
            assert facts["turn_card_count"] == facts["pre_attack_range"]
            assert facts["pre_attack_range"] >= 1
            assert witness["trigger_event_type"] in ("card_used", "card_played")
            assert witness["window_kind"] == witness["window_phase"]
            # Signed optional decision set is exactly ACTIVATE + PASS for Jili.
            assert set(_legal_ops(witness)) == {"activate_skill", "pass_skill"}
            assert set(_legal_skills(witness)) == {JILI}
            # BRIDGE-C policy ACTIVATE > PASS.
            assert witness["chosen_signed_action"]["operation"] == "activate_skill"
            assert witness["controller_conformant"] is True
            # Parent card continuation resumes exactly once after the decision.
            assert witness["parent_card_continuation_resumes_exactly_once"] is True
            assert witness["continuation_identity_before"] != (
                witness["continuation_identity_after"]
            )
            for field in (
                "root_identity",
                "skill_continuation_identity",
                "continuation_identity_before",
                "continuation_identity_after",
            ):
                assert len(witness[field]) == 64


def test_jili_witness_bound_to_recorded_skill_authority_trace(
    natural_replays: dict[str, BridgeFullGameReplayV1],
    cell_proofs: dict[str, BridgeFullGameCellProofV1],
) -> None:
    for label in LABELS:
        payload = natural_replays[label].to_dict()
        trace_by_step = {
            item["step_index"]: item
            for item in payload["skill_decision_authority_trace"]
        }
        for witness in _jili_witnesses(cell_proofs[label]):
            recorded = trace_by_step[witness["step_index"]]
            assert recorded["skill_id"] == JILI
            assert witness["root_identity"] == recorded["root_identity"]
            assert witness["skill_continuation_identity"] == recorded["continuation_identity"]
            assert (
                witness["chosen_signed_action"]["action_id"]
                == recorded["chosen_signed_action"]["action_id"]
            )


def test_aggregate_ev_g1_jili_01_observed_and_replay_proven(
    cell_proofs: dict[str, BridgeFullGameCellProofV1],
) -> None:
    obligation = next(
        item for item in bridge.EVENT_OBLIGATIONS if item.event_id == "EV-G1-JILI-01"
    )
    assert obligation.general_key == "shamoke"
    assert obligation.requirement_scope == "aggregate_general_natural_full_game"
    observed_cells = [
        label for label in LABELS if _jili_witnesses(cell_proofs[label])
    ]
    # Section 6/19: at least one natural, strictly-replayed witness across the
    # frozen submatrix closes the aggregate obligation.
    assert observed_cells == list(LABELS)
    status = (
        "OBSERVED_AND_REPLAY_PROVEN"
        if observed_cells
        else "NOT_YET_COVERED"
    )
    assert status == "OBSERVED_AND_REPLAY_PROVEN"


# ---------------------------------------------------------------------------
# Representative NATURAL_FULL_GAME tamper battery (section 16)
# ---------------------------------------------------------------------------


def _rehash(payload: dict[str, object]) -> dict[str, object]:
    return recompute_bridge_replay_identities_v1(payload)


def _must_fail(payload: dict[str, object]) -> None:
    with pytest.raises((BridgeReplayDivergenceError, BridgeReplayIdentityError)):
        loaded = BridgeFullGameReplayV1.from_dict(_rehash(payload))
        reexecute_skill_aware_fixed_assignment_bridge_replay_v1(loaded)


@pytest.fixture(scope="module")
def tamper_source(
    natural_replays: dict[str, BridgeFullGameReplayV1],
) -> dict[str, object]:
    return natural_replays[TAMPER_LABEL].to_dict()


def _first_jili_step(payload: dict[str, object]) -> int:
    return next(
        item["step_index"]
        for item in payload["skill_decision_authority_trace"]
        if item["skill_id"] == JILI
    )


def test_tamper_finished_winner_and_finish_reason_fail(tamper_source) -> None:
    finished = deepcopy(tamper_source)
    finished["outcome"]["finished"] = False
    _must_fail(finished)

    winner = deepcopy(tamper_source)
    current = winner["outcome"]["winner"]
    winner["outcome"]["winner"] = "p1" if current == "p2" else "p2"
    _must_fail(winner)

    reason = deepcopy(tamper_source)
    reason["outcome"]["finish_reason"] = "forged_terminal"
    _must_fail(reason)


def test_tamper_last_decision_removal_fails(tamper_source) -> None:
    attacked = deepcopy(tamper_source)
    attacked["decisions"].pop()
    attacked["production_authority_trace"].pop()
    _must_fail(attacked)


def test_tamper_jili_decision_removal_fails(tamper_source) -> None:
    attacked = deepcopy(tamper_source)
    index = _first_jili_step(attacked)
    attacked["decisions"].pop(index)
    attacked["production_authority_trace"].pop(index)
    attacked["skill_decision_authority_trace"] = [
        item
        for item in attacked["skill_decision_authority_trace"]
        if item["step_index"] != index
    ]
    _must_fail(attacked)


def test_tamper_jili_continuation_authority_fails(tamper_source) -> None:
    attacked = deepcopy(tamper_source)
    index = _first_jili_step(attacked)
    attacked["production_authority_trace"][index]["continuation_identity_after"] = ZERO64
    _must_fail(attacked)


def test_tamper_general_assignment_and_base_skill_fail(tamper_source) -> None:
    general = deepcopy(tamper_source)
    general["initialization"]["assignment"]["general_key"] = "zhugezhan"
    _must_fail(general)

    base_skill = deepcopy(tamper_source)
    base_skill["initialization"]["base_skill_derivation"]["base_skill_ids"] = []
    _must_fail(base_skill)


def test_tamper_inject_dynamic_skill_fails(tamper_source) -> None:
    attacked = deepcopy(tamper_source)
    general_pid = attacked["initialization"]["base_skill_derivation"]["general_player_id"]
    attacked["initialization"]["initial_dynamic_reconcile_result"]["dynamic_grants"][
        general_pid
    ] = [{"target_skill_id": "sgs_skill_weimu", "active": True}]
    _must_fail(attacked)


def test_tamper_controller_decision_fails(tamper_source) -> None:
    attacked = deepcopy(tamper_source)
    decision = next(
        item for item in attacked["decisions"] if len(item["legal_action_projections"]) > 1
    )
    alternative = next(
        item
        for item in decision["legal_action_projections"]
        if item["projection"]["action_id"] != decision["chosen_action_id"]
    )
    decision["chosen_action_id"] = alternative["projection"]["action_id"]
    decision["chosen_semantic_projection"] = alternative
    _must_fail(attacked)


def test_tamper_final_runtime_and_state_identity_fail(tamper_source) -> None:
    runtime = deepcopy(tamper_source)
    runtime["production_authority_trace"][-1]["runtime_identity_after"] = ZERO64
    _must_fail(runtime)

    state = deepcopy(tamper_source)
    state["decisions"][-1]["state_identity_after"] = ZERO64
    _must_fail(state)


def test_tamper_trace_scope_natural_to_bounded_fails(tamper_source) -> None:
    attacked = deepcopy(tamper_source)
    attacked["trace_scope"] = BridgeTraceScope.BOUNDED_PRODUCTION_TRACE.value
    attacked["outcome"]["trace_scope"] = BridgeTraceScope.BOUNDED_PRODUCTION_TRACE.value
    # Even with outer hashes recomputed, the bounded canonical cell-id derivation
    # rejects a B18 natural cell, so the downgrade cannot survive reexecution.
    _must_fail(attacked)


def test_natural_cell_id_is_canonically_bound(
    natural_replays: dict[str, BridgeFullGameReplayV1],
) -> None:
    attacked = natural_replays[TAMPER_LABEL].to_dict()
    attacked["cell_id"] = "BRIDGE-D-SHAMOKE-P2-SEED-1"
    attacked = _rehash(attacked)
    loaded = BridgeFullGameReplayV1.from_dict(attacked)
    with pytest.raises((BridgeReplayDivergenceError, BridgeReplayIdentityError)):
        derive_bridge_full_game_cell_proof_v1(loaded.to_dict())


# ---------------------------------------------------------------------------
# BRIDGE-E-AUDIT-001 remediation: symmetric NATURAL canonical cell binding in
# the generic strict reexecutor.  Formal cell-proof (above) always bound
# cell_id; these tests prove the generic strict replay authority now derives
# the canonical cell independently from fresh General/seat/seed and refuses a
# serialized cell_id that disagrees -- even when every outer identity is
# attacker-recomputed.
# ---------------------------------------------------------------------------


def _generic_strict_reexecute_from_payload(
    payload: dict[str, object],
) -> object:
    rehashed = recompute_bridge_replay_identities_v1(deepcopy(payload))
    loaded = BridgeFullGameReplayV1.from_dict(rehashed)
    return reexecute_skill_aware_fixed_assignment_bridge_replay_v1(loaded)


@pytest.mark.parametrize("label,b18,seat,seed", SHAMOKE_SUBMATRIX)
def test_audit001_remediation_six_legit_cells_pass_generic_strict_reexecute(
    natural_replays: dict[str, BridgeFullGameReplayV1],
    label: str,
    b18: str,
    seat: str,
    seed: int,
) -> None:
    # Required attack battery item 1: E-001..E-006 still pass the generic
    # strict reexecutor after the symmetric binding is added.
    replay = natural_replays[label]
    assert replay.cell_id == b18
    verification = _generic_strict_reexecute_from_payload(replay.to_dict())
    assert verification.step_count == len(replay.decisions)
    assert verification.finished is True
    assert verification.proof_flags["STRICT_REPLAY_PROVEN"] is True
    assert verification.proof_flags["NATURAL_FULL_GAME"] is True
    assert verification.proof_flags["FORMAL_TERMINAL_PROVEN"] is True


@pytest.mark.parametrize("forged_cell_id", ("B18-004", "FORGED-CELL"))
def test_audit001_remediation_e005_forged_cell_id_fails_generic_strict_reexecute(
    natural_replays: dict[str, BridgeFullGameReplayV1], forged_cell_id: str
) -> None:
    # E-005 == shamoke / GENERAL_AS_P2 / seed 1 / B18-005.  A different frozen
    # cell label or an arbitrary forged string must fail at the symmetric
    # canonical derivation, not later in formal cell-proof.
    attacked = natural_replays["E-005"].to_dict()
    attacked["cell_id"] = forged_cell_id
    with pytest.raises(BridgeReplayDivergenceError, match="canonical派生不匹配"):
        _generic_strict_reexecute_from_payload(attacked)


def test_audit001_remediation_e005_seed_mismatch_fails_generic_strict_reexecute(
    natural_replays: dict[str, BridgeFullGameReplayV1],
) -> None:
    # P2/seed0 canonical cell is B18-004; the recorded B18-005 cannot survive.
    attacked = natural_replays["E-005"].to_dict()
    attacked["seed"] = 0
    with pytest.raises(BridgeReplayDivergenceError, match="canonical派生不匹配"):
        _generic_strict_reexecute_from_payload(attacked)


def test_audit001_remediation_e005_seat_mismatch_fails_generic_strict_reexecute(
    natural_replays: dict[str, BridgeFullGameReplayV1],
) -> None:
    # Replace the assignment with a self-consistent P1 descriptor so the
    # rejection point is the cell binding rather than assignment parsing.
    attacked = natural_replays["E-005"].to_dict()
    attacked["initialization"]["assignment"] = bridge.create_bridge_assignment(
        "shamoke", "GENERAL_AS_P1"
    ).to_dict()
    with pytest.raises(BridgeReplayDivergenceError, match="canonical派生不匹配"):
        _generic_strict_reexecute_from_payload(attacked)


def test_audit001_remediation_e005_general_mismatch_fails_generic_strict_reexecute(
    natural_replays: dict[str, BridgeFullGameReplayV1],
) -> None:
    # zhugezhan / P2 / seed 1 canonical cell is B18-011, never B18-005.
    attacked = natural_replays["E-005"].to_dict()
    attacked["initialization"]["assignment"] = bridge.create_bridge_assignment(
        "zhugezhan", "GENERAL_AS_P2"
    ).to_dict()
    with pytest.raises(BridgeReplayDivergenceError, match="canonical派生不匹配"):
        _generic_strict_reexecute_from_payload(attacked)


def test_audit001_remediation_non_baseline_seed_fails_closed_without_discovery(
    natural_replays: dict[str, BridgeFullGameReplayV1],
) -> None:
    # Sentinel stays UNDISCOVERED: the generic strict reexecutor must not
    # support seed 2..99 ahead of BASELINE_18 completion.
    attacked = natural_replays["E-005"].to_dict()
    attacked["seed"] = 2
    with pytest.raises(BridgeReplayDivergenceError, match="BASELINE_18"):
        _generic_strict_reexecute_from_payload(attacked)
