# -*- coding: utf-8 -*-
"""BRIDGE-F Zhugezhan natural full-game composition, strict replay, Zuilun/Fuyin witness.

Scope is exactly ZHUGEZHAN_BASELINE_SUBMATRIX_6 (F-001..F-006 == B18-007..B18-012).
Every cell is a real natural formal duel driven only by the BRIDGE-C public-only
controller through the frozen Zuilun/Fuyin production runtime to a formal terminal,
then strictly reexecuted from a cold load.  No fixture, premutation, manual event
injection, seed search or sentinel discovery is used or permitted here.
"""

from __future__ import annotations

from copy import deepcopy
import json

import pytest

from scripts.sgs_engine import skill_aware_fixed_assignment_full_game_bridge as bridge
from scripts.sgs_engine.formal_duel import implementation_identity
from scripts.sgs_engine.skill_aware_fixed_assignment_full_game_bridge_replay import (
    MAX_STEPS,
    SKILL_EVENT_COVERAGE_PROVEN,
    BridgeFullGameCellProofV1,
    BridgeFullGameReplayV1,
    BridgeReplayDivergenceError,
    BridgeReplayIdentityError,
    BridgeTraceScope,
    _canonical_full_game_cell_id,
    _record_bridge_replay_core,
    derive_bridge_full_game_cell_proof_v1,
    record_natural_full_game_skill_aware_fixed_assignment_bridge_replay_v1,
    recompute_bridge_replay_identities_v1,
    reexecute_skill_aware_fixed_assignment_bridge_replay_v1,
)


ZUILUN = "sgs_skill_zuilun"
FUYIN = "sgs_skill_fuyin"
SLASH_DUEL_KEYS = frozenset(
    {"sgs_basic_sha", "sgs_basic_huosha", "sgs_basic_leisha", "sgs_trick_juedou"}
)
ZERO64 = "0" * 64

# Exact BRIDGE-F submatrix in frozen execution order (section 18).
ZHUGEZHAN_SUBMATRIX = (
    ("F-001", "B18-007", "GENERAL_AS_P1", 0),
    ("F-002", "B18-008", "GENERAL_AS_P1", 1),
    ("F-003", "B18-009", "GENERAL_AS_P1", 49),
    ("F-004", "B18-010", "GENERAL_AS_P2", 0),
    ("F-005", "B18-011", "GENERAL_AS_P2", 1),
    ("F-006", "B18-012", "GENERAL_AS_P2", 49),
)
LABELS = tuple(item[0] for item in ZHUGEZHAN_SUBMATRIX)
# Representative cell for the deep tamper battery (section 19): a natural game that
# exercises Zuilun ACTIVATE, private selection, the n=0 HP-loss path and Fuyin.
TAMPER_LABEL = "F-002"


def _cold_round_trip(replay: BridgeFullGameReplayV1) -> BridgeFullGameReplayV1:
    encoded = json.dumps(
        replay.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return BridgeFullGameReplayV1.from_dict(json.loads(encoded))


@pytest.fixture(scope="module")
def natural_replays() -> dict[str, BridgeFullGameReplayV1]:
    return {
        label: record_natural_full_game_skill_aware_fixed_assignment_bridge_replay_v1(
            general_key="zhugezhan",
            seat_assignment=seat,
            seed=seed,
            cell_id=b18,
        )
        for label, b18, seat, seed in ZHUGEZHAN_SUBMATRIX
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


def _zuilun_opportunities(proof) -> tuple[object, ...]:
    return tuple(w for w in proof.witnesses if w["skill_id"] == ZUILUN)


def _ops(witness) -> tuple[str, ...]:
    return tuple(item["operation"] for item in witness["signed_legal_set"])


def _fuyin(proof) -> tuple[object, ...]:
    return tuple(
        w for w in proof.target_effect_first_chance_witnesses if w["skill_id"] == FUYIN
    )


def _general_pid(proof) -> str:
    return "p1" if proof.seat_assignment == "GENERAL_AS_P1" else "p2"


# ---------------------------------------------------------------------------
# Scope, canonical identity and natural-only ingress (sections 1-2, 22)
# ---------------------------------------------------------------------------


def test_submatrix_cell_ids_scope_and_natural_only_markers(
    natural_replays: dict[str, BridgeFullGameReplayV1],
) -> None:
    live_identity = implementation_identity()
    for label, b18, seat, seed in ZHUGEZHAN_SUBMATRIX:
        replay = natural_replays[label]
        payload = replay.to_dict()
        assert replay.cell_id == b18
        assert replay.seed == seed
        assert replay.trace_scope is BridgeTraceScope.NATURAL_FULL_GAME
        assert payload["outcome"]["trace_scope"] == "NATURAL_FULL_GAME"
        # Bound to the live post-BRIDGE-F development identity, never the BRIDGE-E
        # identity, the BEFORE identity, or the global frozen pin (section 22).
        assert replay.implementation_identity == live_identity
        assert replay.implementation_identity != (
            "9f397d5b45a14c7e68e6211e3b6cdf124e67ef3d1f8fd433d724b5455aecc2f5"
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
        assert initialization["assignment"]["general_key"] == "zhugezhan"
        assert initialization["assignment"]["seat_assignment"] == seat


def test_natural_recorder_rejects_non_baseline_seed_and_wrong_cap() -> None:
    with pytest.raises(BridgeReplayDivergenceError):
        record_natural_full_game_skill_aware_fixed_assignment_bridge_replay_v1(
            general_key="zhugezhan", seat_assignment="GENERAL_AS_P1", seed=2
        )
    with pytest.raises(BridgeReplayDivergenceError):
        record_natural_full_game_skill_aware_fixed_assignment_bridge_replay_v1(
            general_key="zhugezhan",
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
# Natural formal terminal, controller termination, terminal cleanup (8,10,13)
# ---------------------------------------------------------------------------


def test_six_cells_reach_natural_formal_terminal_within_cap(
    cell_proofs: dict[str, BridgeFullGameCellProofV1],
) -> None:
    for label in LABELS:
        proof = cell_proofs[label]
        assert proof.trace_scope == "NATURAL_FULL_GAME"
        assert 0 < proof.steps < MAX_STEPS
        assert proof.winner in bridge.PARTICIPANT_IDS
        assert proof.finish_reason == "opponent_confirmed_dead"
        flags = proof.strict_replay_proof_flags
        assert flags["NATURAL_FULL_GAME"] is True
        assert flags["FORMAL_TERMINAL_PROVEN"] is True
        assert flags["FULL_GAME_COMPOSITION_PROVEN"] is True


def test_controller_terminates_without_loop_or_blowup(
    cell_proofs: dict[str, BridgeFullGameCellProofV1],
) -> None:
    steps = {label: cell_proofs[label].steps for label in LABELS}
    assert all(count < MAX_STEPS for count in steps.values())
    assert max(steps.values()) <= 260
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
        "end_dispatcher_cannot_resume",
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
        for name in required_true:
            assert terminal[name] is True, f"{label} terminal invariant {name} 必须为true"
        # No unresolved Zuilun private selection / HP-loss continuation at terminal.
        assert terminal["pending_private_card_selection_none"] is True
        assert terminal["pending_skill_hp_loss_none"] is True
        # Zuilun n=0 terminal cleanup restores the Bridge V1 frozen contract:
        # END dispatcher cursor is strictly None at formal terminal (B2_PRODUCTION_CLEANUP).
        assert terminal["end_phase_dispatch_state_none"] is True
        assert terminal["end_dispatcher_cannot_resume"] is True


# ---------------------------------------------------------------------------
# Strict replay and section-12 proof gates (12, 14)
# ---------------------------------------------------------------------------


def test_strict_replay_six_of_six(
    cell_proofs: dict[str, BridgeFullGameCellProofV1],
) -> None:
    for label in LABELS:
        proof = cell_proofs[label]
        flags = proof.strict_replay_proof_flags
        assert flags["STRICT_REPLAY_PROVEN"] is True
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


def test_full_game_cell_proof_section_twelve_flags(
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
        # Zhugezhan naturally triggers Zuilun in every baseline cell.
        assert proof.skill_event_coverage == SKILL_EVENT_COVERAGE_PROVEN


def test_zhugezhan_frozen_semantics_hold_in_full_game(
    natural_replays: dict[str, BridgeFullGameReplayV1],
) -> None:
    for label in LABELS:
        initialization = natural_replays[label].to_dict()["initialization"]
        base = initialization["base_skill_derivation"]
        assert base["general_key"] == "zhugezhan"
        assert set(base["base_skill_ids"]) == {ZUILUN, FUYIN}
        assert base["no_skill_base_skill_ids"] == []
        reconcile = initialization["initial_dynamic_reconcile_result"]
        general_pid = base["general_player_id"]
        no_skill_pid = base["no_skill_player_id"]
        assert reconcile["player_effective_skills"][general_pid] == sorted([ZUILUN, FUYIN])
        assert reconcile["player_effective_skills"][no_skill_pid] == []
        assert all(grants == [] for grants in reconcile["dynamic_grants"].values())
        participants = initialization["assignment"]["participants"]
        general_part = next(p for p in participants if p["player_id"] == general_pid)
        assert general_part["hp"] == 3 and general_part["max_hp"] == 3
        assert set(general_part["skill_ids"]) == {ZUILUN, FUYIN}


# ---------------------------------------------------------------------------
# EV-G2-ZUILUN-01: opportunity + END dispatcher pause/resume (sections 5, 10)
# ---------------------------------------------------------------------------


def test_zuilun_opportunity_witness_ev_g2_zuilun_01(
    cell_proofs: dict[str, BridgeFullGameCellProofV1],
) -> None:
    for label in LABELS:
        proof = cell_proofs[label]
        opportunities = _zuilun_opportunities(proof)
        assert opportunities, f"{label} 必须自然观察到 Zuilun END_PHASE_STARTED 机会"
        for w in opportunities:
            assert w["skill_id"] == ZUILUN
            assert w["owner_id"] == _general_pid(proof)
            # Real END_PHASE_STARTED checkpoint in the owner's own END phase.
            assert w["trigger_event_type"] == "end_phase_started"
            assert w["window_phase"] == "end"
            assert w["window_kind"] == "end"
            # Signed optional set is exactly ACTIVATE + PASS; policy ACTIVATE > PASS.
            assert set(_ops(w)) == {"activate_skill", "pass_skill"}
            assert w["chosen_signed_action"]["operation"] == "activate_skill"
            assert w["controller_conformant"] is True


def test_zuilun_end_dispatcher_pause_resume(
    cell_proofs: dict[str, BridgeFullGameCellProofV1],
) -> None:
    for label in LABELS:
        resume = cell_proofs[label].end_dispatcher_resume
        assert resume["resume_proven"] is True
        assert resume["monotonic_no_duplicate_no_skip"] is True
        assert resume["terminal_dispatcher_cannot_resume"] is True
        assert tuple(resume["anomalies"]) == ()
        # Zuilun was actually discovered and completed by the END dispatcher.
        assert resume["completed_triggers_by_skill"][ZUILUN] >= 1
        assert len(resume["end_phase_identities_observed"]) >= 1


def test_aggregate_ev_g2_zuilun_01_observed_and_replay_proven(
    cell_proofs: dict[str, BridgeFullGameCellProofV1],
) -> None:
    obligation = next(
        item for item in bridge.EVENT_OBLIGATIONS if item.event_id == "EV-G2-ZUILUN-01"
    )
    assert obligation.general_key == "zhugezhan"
    covered = [
        label
        for label in LABELS
        if _zuilun_opportunities(cell_proofs[label])
        and cell_proofs[label].end_dispatcher_resume["resume_proven"] is True
    ]
    assert covered == list(LABELS)
    assert ("OBSERVED_AND_REPLAY_PROVEN" if covered else "NOT_YET_COVERED") == (
        "OBSERVED_AND_REPLAY_PROVEN"
    )


# ---------------------------------------------------------------------------
# Zuilun private selection authority + controller privacy (sections 6, 7, 16)
# ---------------------------------------------------------------------------


def test_zuilun_private_selection_opaque_authority(
    cell_proofs: dict[str, BridgeFullGameCellProofV1],
) -> None:
    seen = 0
    for label in LABELS:
        for w in cell_proofs[label].private_selection_witnesses:
            seen += 1
            assert w["skill_id"] == ZUILUN
            assert w["owner_id"] == _general_pid(cell_proofs[label])
            assert w["choose_count"] >= 1
            # Opaque ordinal-ascending policy; controller never sees card identity.
            assert w["available_opaque_ordinals"] == tuple(
                sorted(w["available_opaque_ordinals"])
            )
            assert w["chosen_ordinal"] == min(w["available_opaque_ordinals"])
            assert w["controller_conformant"] is True
            assert w["private_public_separation"] is True
            assert w["secret_recorded_separately"] is True
            # END cursor identity is present and stable across the paused window.
            assert w["end_phase_identity"]
            assert w["continuation_identity_before"] != w["continuation_identity_after"]
            for field in ("root_identity", "skill_continuation_identity"):
                assert len(w[field]) == 64
    # The frozen submatrix naturally exercises Zuilun private selection.
    assert seen >= 1


def test_controller_privacy_no_private_card_leak(
    natural_replays: dict[str, BridgeFullGameReplayV1],
) -> None:
    allowed = bridge.PRIVATE_SELECTION_ALLOWED_FIELDS
    forbidden = bridge.PRIVATE_SELECTION_FORBIDDEN_FIELDS
    for label in LABELS:
        payload = natural_replays[label].to_dict()
        private_choice_steps = 0
        for decision in payload["decisions"]:
            chosen = decision["chosen_semantic_projection"]
            if chosen["projection_kind"] != "private_player_choice":
                continue
            private_choice_steps += 1
            for item in decision["legal_action_projections"]:
                assert item["projection_kind"] == "private_player_choice"
                assert frozenset(item["projection"]) == allowed
                assert not (frozenset(item["projection"]) & forbidden)
            serialized_public = bridge.canonical_json(
                {
                    "public_context": decision["public_context"],
                    "legal": decision["legal_action_projections"],
                    "chosen": chosen,
                }
            )
            for leak in forbidden:
                assert f'"{leak}"' not in serialized_public
            assert "observed_card_ids" not in serialized_public
            assert "selected_card_ids" not in serialized_public
        # authoritative_private keeps the secret, separate from the public trace.
        selections = payload["authoritative_private"]["private_skill_selections"]
        assert len(selections) == private_choice_steps


# ---------------------------------------------------------------------------
# Zuilun n=0 HP-loss / dying path (section 11)
# ---------------------------------------------------------------------------


def test_zuilun_hp_loss_path_resolves_cleanly(
    cell_proofs: dict[str, BridgeFullGameCellProofV1],
) -> None:
    seen = 0
    for label in LABELS:
        proof = cell_proofs[label]
        for w in proof.hp_loss_witnesses:
            seen += 1
            assert w["skill_id"] == ZUILUN
            assert w["owner_id"] == _general_pid(proof)
            assert w["resume_phase"] == "end"
            assert w["continuation_id"]
            assert w["chosen_signed_action"]["action_id"]
        # No HP-loss continuation left pending at terminal.
        assert proof.terminal_invariants["pending_skill_hp_loss_none"] is True
    # The frozen submatrix naturally exercises the n=0 HP-loss branch.
    assert seen >= 1


# ---------------------------------------------------------------------------
# EV-G2-FUYIN-01: first Slash/Duel target chance consumption (sections 8, 9)
# ---------------------------------------------------------------------------


def test_fuyin_first_chance_witness_ev_g2_fuyin_01(
    cell_proofs: dict[str, BridgeFullGameCellProofV1],
) -> None:
    seen = 0
    for label in LABELS:
        for w in _fuyin(cell_proofs[label]):
            seen += 1
            assert w["skill_id"] == FUYIN
            assert w["owner_id"] == _general_pid(cell_proofs[label])
            assert w["card_key"] in SLASH_DUEL_KEYS
            assert w["card_user"] in bridge.PARTICIPANT_IDS
            assert w["card_user"] != w["owner_id"]
            # First-chance mark consumed at the correct checkpoint.
            assert w["consumed_before"] is False
            assert w["consumed_after"] is True
            # Comparison drives the ineffective flag; never inferred from damage.
            assert w["comparison_user_le_owner"] == (
                w["user_hand_count_after_use"] <= w["owner_hand_count"]
            )
            assert w["target_effect_ineffective"] == w["comparison_user_le_owner"]
            # Fuyin only affects Zhugezhan as the single target.
            assert w["per_target_only"] is True
            assert tuple(w["target_ids"]) == (w["owner_id"],)
            assert w["turn_number"] >= 1
            assert w["source_event_sequence"] >= 1
            assert len(w["resolution_identity"]) == 64
            if w["target_effect_ineffective"]:
                assert w["ineffective_event_present"] is True
    assert seen >= 1


def test_aggregate_ev_g2_fuyin_01_observed_and_replay_proven(
    cell_proofs: dict[str, BridgeFullGameCellProofV1],
) -> None:
    obligation = next(
        item for item in bridge.EVENT_OBLIGATIONS if item.event_id == "EV-G2-FUYIN-01"
    )
    assert obligation.general_key == "zhugezhan"
    covered = [label for label in LABELS if _fuyin(cell_proofs[label])]
    assert covered  # at least one natural strictly-replayed Fuyin first-chance
    assert ("OBSERVED_AND_REPLAY_PROVEN" if covered else "NOT_YET_COVERED") == (
        "OBSERVED_AND_REPLAY_PROVEN"
    )


# ---------------------------------------------------------------------------
# Representative NATURAL_FULL_GAME tamper battery (section 19)
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


def _find_zuilun_activate_decision(payload):
    for index, decision in enumerate(payload["decisions"]):
        chosen = decision["chosen_semantic_projection"]["projection"]
        if (
            chosen.get("public_skill_id") == ZUILUN
            and chosen.get("operation") == "activate_skill"
        ):
            return index, decision
    raise AssertionError("no zuilun activate decision")


def _find_private_choice_decision(payload):
    for index, decision in enumerate(payload["decisions"]):
        if (
            decision["chosen_semantic_projection"]["projection_kind"]
            == "private_player_choice"
        ):
            return index, decision
    raise AssertionError("no private choice decision")


def test_tamper_general_assignment_and_base_skill_removal_fail(tamper_source) -> None:
    general = deepcopy(tamper_source)
    general["initialization"]["assignment"]["general_key"] = "shamoke"
    _must_fail(general)

    no_zuilun = deepcopy(tamper_source)
    base = no_zuilun["initialization"]["base_skill_derivation"]["base_skill_ids"]
    base.remove(ZUILUN)
    _must_fail(no_zuilun)

    no_fuyin = deepcopy(tamper_source)
    base2 = no_fuyin["initialization"]["base_skill_derivation"]["base_skill_ids"]
    base2.remove(FUYIN)
    _must_fail(no_fuyin)


def test_tamper_zuilun_activate_to_pass_fails(tamper_source) -> None:
    attacked = deepcopy(tamper_source)
    _index, decision = _find_zuilun_activate_decision(attacked)
    alternative = next(
        item
        for item in decision["legal_action_projections"]
        if item["projection"]["action_id"] != decision["chosen_action_id"]
    )
    decision["chosen_action_id"] = alternative["projection"]["action_id"]
    decision["chosen_semantic_projection"] = alternative
    _must_fail(attacked)


def test_tamper_private_selection_ordinal_and_secret_and_leak_fail(tamper_source) -> None:
    ordinal = deepcopy(tamper_source)
    _index, decision = _find_private_choice_decision(ordinal)
    projection = decision["chosen_semantic_projection"]["projection"]
    projection["ordinal"] = projection["ordinal"] + 1
    _must_fail(ordinal)

    secret = deepcopy(tamper_source)
    selection = secret["authoritative_private"]["private_skill_selections"][0]
    selection["selected_card_ids"][0] = selection["remaining_top_order"][0]
    _must_fail(secret)

    leak = deepcopy(tamper_source)
    _lindex, ldecision = _find_private_choice_decision(leak)
    ldecision["legal_action_projections"][0]["projection"]["card_id"] = "private-leak"
    _must_fail(leak)


def test_tamper_end_cursor_identity_fails(tamper_source) -> None:
    attacked = deepcopy(tamper_source)
    index, _decision = _find_zuilun_activate_decision(attacked)
    attacked["production_authority_trace"][index][
        "movement_ledger_end_identity_after"
    ] = ZERO64
    _must_fail(attacked)


def test_tamper_fuyin_consumption_comparison_and_flag_fail(tamper_source) -> None:
    def fuyin_event(payload):
        return next(
            event
            for event in payload["events"]
            if event["event_type"] == "skill_condition_evaluated"
            and (event.get("payload") or {}).get("skill_id") == FUYIN
        )

    consumed = deepcopy(tamper_source)
    fuyin_event(consumed)["payload"]["consumed_before"] = True
    _must_fail(consumed)

    comparison = deepcopy(tamper_source)
    fuyin_event(comparison)["payload"]["user_hand_count_after_use"] = 99
    _must_fail(comparison)

    flag = deepcopy(tamper_source)
    event = fuyin_event(flag)
    event["payload"]["target_effect_ineffective"] = not event["payload"][
        "target_effect_ineffective"
    ]
    _must_fail(flag)


def test_tamper_terminal_runtime_state_and_private_selection_fail(tamper_source) -> None:
    finished = deepcopy(tamper_source)
    finished["outcome"]["finished"] = False
    _must_fail(finished)

    winner = deepcopy(tamper_source)
    current = winner["outcome"]["winner"]
    winner["outcome"]["winner"] = "p1" if current == "p2" else "p2"
    _must_fail(winner)

    runtime = deepcopy(tamper_source)
    runtime["production_authority_trace"][-1]["runtime_identity_after"] = ZERO64
    _must_fail(runtime)

    state = deepcopy(tamper_source)
    state["decisions"][-1]["state_identity_after"] = ZERO64
    _must_fail(state)

    private_removed = deepcopy(tamper_source)
    private_removed["authoritative_private"]["private_skill_selections"].pop()
    _must_fail(private_removed)


def test_tamper_trace_scope_and_natural_cell_id_fail(
    tamper_source, natural_replays
) -> None:
    scope = deepcopy(tamper_source)
    scope["trace_scope"] = BridgeTraceScope.BOUNDED_PRODUCTION_TRACE.value
    scope["outcome"]["trace_scope"] = BridgeTraceScope.BOUNDED_PRODUCTION_TRACE.value
    _must_fail(scope)

    relabeled = natural_replays[TAMPER_LABEL].to_dict()
    relabeled["cell_id"] = "BRIDGE-D-ZHUGEZHAN-P1-SEED-1"
    relabeled = _rehash(relabeled)
    with pytest.raises((BridgeReplayDivergenceError, BridgeReplayIdentityError)):
        derive_bridge_full_game_cell_proof_v1(
            BridgeFullGameReplayV1.from_dict(relabeled).to_dict()
        )


# ---------------------------------------------------------------------------
# BRIDGE-E remediation non-regression (section 20)
# ---------------------------------------------------------------------------


def test_e_remediation_finding_001_wrong_natural_cell_id_fails_closed(
    natural_replays: dict[str, BridgeFullGameReplayV1],
) -> None:
    attacked = natural_replays[TAMPER_LABEL].to_dict()
    attacked["cell_id"] = "B18-999"
    attacked = _rehash(attacked)
    loaded = BridgeFullGameReplayV1.from_dict(attacked)
    with pytest.raises((BridgeReplayDivergenceError, BridgeReplayIdentityError)):
        derive_bridge_full_game_cell_proof_v1(loaded.to_dict())


def test_e_remediation_finding_002_preadvanced_natural_recording_fails_closed() -> None:
    session = bridge.create_skill_aware_fixed_assignment_duel_session_v1(
        seed=1, general_key="zhugezhan", seat_assignment="GENERAL_AS_P1"
    )
    # Advance the session one real step so it is no longer pristine.
    session.step_with_acceptance_controller_v1()
    assert session.step_count == 1
    canonical = _canonical_full_game_cell_id(session.assignment, 1)
    with pytest.raises(BridgeReplayDivergenceError):
        _record_bridge_replay_core(
            session,
            seed=1,
            scope=BridgeTraceScope.NATURAL_FULL_GAME,
            cell_id=canonical,
            max_steps=MAX_STEPS,
            require_terminal=True,
        )
