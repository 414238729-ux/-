# -*- coding: utf-8 -*-
"""BRIDGE-G Wang Yuanji natural full-game composition, strict replay, Qianchong/Shangjian witness.

Scope is exactly WANGYUANJI_BASELINE_SUBMATRIX_6 (G-001..G-006 == B18-013..B18-018).
Every cell is a real natural formal duel driven only by the BRIDGE-C public-only
controller through the frozen Qianchong/Shangjian production runtime to a formal terminal,
then strictly reexecuted from a cold load.  No fixture, premutation, manual event
injection, seed search or sentinel discovery is used or permitted here.
"""

from __future__ import annotations

from copy import deepcopy
import json

import pytest

from scripts.sgs_engine import skill_aware_fixed_assignment_full_game_bridge as bridge
from scripts.sgs_engine.formal_duel import implementation_identity
from scripts.sgs_engine.model import DISCARD_PILE, ZoneRef
from scripts.sgs_engine.production_batch import (
    ProductionBasicCardBatch,
    ProductionBatchError,
    ProductionPhase,
    _EndPhaseDispatchState,
)
from scripts.sgs_engine.skill_aware_fixed_assignment_full_game_bridge import (
    _BRIDGE_STRICT_REPLAY_RECONSTRUCTION_CAPABILITY,
    create_bridge_assignment,
)
from scripts.sgs_engine.skill_aware_fixed_assignment_full_game_bridge_replay import (
    MAX_STEPS,
    SKILL_EVENT_COVERAGE_PROVEN,
    BridgeFullGameCellProofV1,
    BridgeFullGameReplayV1,
    BridgeReplayDivergenceError,
    BridgeReplayIdentityError,
    BridgeTraceScope,
    _canonical_full_game_cell_id,
    _create_skill_aware_fixed_assignment_duel_session_for_strict_replay_v1,
    _record_bridge_replay_core,
    derive_bridge_full_game_cell_proof_v1,
    record_natural_full_game_skill_aware_fixed_assignment_bridge_replay_v1,
    recompute_bridge_replay_identities_v1,
    reexecute_skill_aware_fixed_assignment_bridge_replay_v1,
)


QIANCHONG = "sgs_skill_qianchong"
SHANGJIAN = "sgs_skill_shangjian"
WEIMU = "sgs_skill_weimu"
MINGZHE = "sgs_skill_mingzhe"
ZERO64 = "0" * 64

# Exact BRIDGE-G submatrix in frozen execution order (section 18).
WANGYUANJI_SUBMATRIX = (
    ("G-001", "B18-013", "GENERAL_AS_P1", 0),
    ("G-002", "B18-014", "GENERAL_AS_P1", 1),
    ("G-003", "B18-015", "GENERAL_AS_P1", 49),
    ("G-004", "B18-016", "GENERAL_AS_P2", 0),
    ("G-005", "B18-017", "GENERAL_AS_P2", 1),
    ("G-006", "B18-018", "GENERAL_AS_P2", 49),
)
LABELS = tuple(item[0] for item in WANGYUANJI_SUBMATRIX)
# Representative cell for the deep tamper battery (section 19): a natural game that
# exercises Qianchong category choice, dynamic grants, and multiple Shangjian evaluations.
TAMPER_LABEL = "G-001"


def _cold_round_trip(replay: BridgeFullGameReplayV1) -> BridgeFullGameReplayV1:
    encoded = json.dumps(
        replay.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return BridgeFullGameReplayV1.from_dict(json.loads(encoded))


def _rehash(payload: dict[str, object]) -> dict[str, object]:
    return recompute_bridge_replay_identities_v1(payload)


def _must_fail(payload: dict[str, object]) -> None:
    with pytest.raises((BridgeReplayDivergenceError, BridgeReplayIdentityError)):
        loaded = BridgeFullGameReplayV1.from_dict(_rehash(payload))
        reexecute_skill_aware_fixed_assignment_bridge_replay_v1(loaded)


@pytest.fixture(scope="module")
def natural_replays() -> dict[str, BridgeFullGameReplayV1]:
    return {
        label: record_natural_full_game_skill_aware_fixed_assignment_bridge_replay_v1(
            general_key="wangyuanji",
            seat_assignment=seat,
            seed=seed,
            cell_id=b18,
        )
        for label, b18, seat, seed in WANGYUANJI_SUBMATRIX
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


def _general_pid(proof) -> str:
    return "p1" if proof.seat_assignment == "GENERAL_AS_P1" else "p2"


def _replay_to_finished_session(replay: BridgeFullGameReplayV1, seat: str):
    assignment = create_bridge_assignment(general_key="wangyuanji", seat_assignment=seat)
    signing = replay.authoritative_private["signing_authority"]
    session = _create_skill_aware_fixed_assignment_duel_session_for_strict_replay_v1(
        seed=replay.seed,
        assignment=assignment,
        session_id=signing["session_id"],
        session_secret_hex=signing["session_secret_hex"],
        capability=_BRIDGE_STRICT_REPLAY_RECONSTRUCTION_CAPABILITY,
    )
    for decision in replay.decisions:
        session.step(decision["chosen_action_id"])
    return session


def _drive_to_first_completed_end(session) -> None:
    """Use only the public Bridge controller until the first END checkpoint closes."""

    for _ in range(100):
        if session.phase is ProductionPhase.END and session.skill_pending is None:
            assert session._end_phase_dispatch_state is None
            return
        session.step_with_acceptance_controller_v1()
    pytest.fail("Bridge controller未在100步内到达首个已结算END checkpoint")


def _drive_to_first_self_equip_for_player(session, *, owner_id: str):
    """Use only the public controller until owner_id naturally self-equips."""

    for _ in range(100):
        authority_count = len(session.card_movement_authority)
        executed = session.step_with_acceptance_controller_v1()
        new_movements = session.card_movement_authority[authority_count:]
        enter_processing = next(
            (
                entry
                for entry in new_movements
                if entry.source_owner_id == owner_id
                and entry.source_zone == "hand"
                and entry.destination_owner_id is None
                and entry.destination_zone == "processing"
                and entry.semantic_reason.endswith("_equip:enter_processing")
            ),
            None,
        )
        if enter_processing is None:
            continue
        installed = next(
            (
                entry
                for entry in new_movements
                if entry.card_instance_id == enter_processing.card_instance_id
                and entry.root_operation_identity
                == enter_processing.root_operation_identity
                and entry.source_owner_id is None
                and entry.source_zone == "processing"
                and entry.destination_owner_id == owner_id
                and entry.destination_zone.startswith("equipment:")
                and entry.semantic_reason == "equip_installed"
            ),
            None,
        )
        assert installed is not None
        return executed, enter_processing, installed
    pytest.fail("Bridge controller未在100步内观察到指定角色的自然self-equip")


def _shangjian_evaluation_count(session) -> int:
    return sum(
        event.event_type.value == "skill_condition_evaluated"
        and event.payload.get("skill_id") == SHANGJIAN
        for event in session.events
    )


# ---------------------------------------------------------------------------
# Scope, canonical identity and natural-only ingress (sections 1-2, 22)
# ---------------------------------------------------------------------------


def test_submatrix_cell_ids_scope_and_natural_only_markers(
    natural_replays: dict[str, BridgeFullGameReplayV1],
) -> None:
    live_identity = implementation_identity()
    for label, b18, seat, seed in WANGYUANJI_SUBMATRIX:
        replay = natural_replays[label]
        payload = replay.to_dict()
        assert replay.cell_id == b18
        assert replay.seed == seed
        assert replay.trace_scope is BridgeTraceScope.NATURAL_FULL_GAME
        assert payload["outcome"]["trace_scope"] == "NATURAL_FULL_GAME"
        assert replay.implementation_identity == live_identity
        assert replay.implementation_identity != (
            "426540caf93784c36d8f3131fc61850290c5c88c26edcb173982de035ecb4a32"
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
        assert initialization["assignment"]["general_key"] == "wangyuanji"
        assert initialization["assignment"]["seat_assignment"] == seat


def test_natural_recorder_rejects_non_baseline_seed_and_wrong_cap() -> None:
    with pytest.raises(BridgeReplayDivergenceError):
        record_natural_full_game_skill_aware_fixed_assignment_bridge_replay_v1(
            general_key="wangyuanji", seat_assignment="GENERAL_AS_P1", seed=2
        )
    with pytest.raises(BridgeReplayDivergenceError):
        record_natural_full_game_skill_aware_fixed_assignment_bridge_replay_v1(
            general_key="wangyuanji",
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
    assert max(steps.values()) <= 350
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
        "SKILL_EVENT_COVERAGE_PROVEN",
        "SKILL_EVENT_COVERAGE_QIANCHONG_PROVEN",
        "SKILL_EVENT_COVERAGE_SHANGJIAN_PROVEN",
    )
    for label in LABELS:
        proof = cell_proofs[label]
        for name in always_true:
            assert proof.proof_flags[name] is True, f"{label} {name} 必须为true"
        assert proof.skill_event_coverage == SKILL_EVENT_COVERAGE_PROVEN
        assert proof.qianchong_event_coverage == SKILL_EVENT_COVERAGE_PROVEN
        assert proof.shangjian_event_coverage == SKILL_EVENT_COVERAGE_PROVEN


def test_wangyuanji_frozen_semantics_hold_in_full_game(
    natural_replays: dict[str, BridgeFullGameReplayV1],
) -> None:
    for label in LABELS:
        initialization = natural_replays[label].to_dict()["initialization"]
        base = initialization["base_skill_derivation"]
        assert base["general_key"] == "wangyuanji"
        assert set(base["base_skill_ids"]) == {QIANCHONG, SHANGJIAN}
        assert WEIMU not in base["base_skill_ids"]
        assert MINGZHE not in base["base_skill_ids"]
        assert base["no_skill_base_skill_ids"] == []

        general_pid = base["general_player_id"]
        no_skill_pid = base["no_skill_player_id"]
        reconcile = initialization["initial_dynamic_reconcile_result"]
        assert reconcile["player_effective_skills"][general_pid] == sorted([QIANCHONG, SHANGJIAN])
        assert reconcile["player_effective_skills"][no_skill_pid] == []
        assert all(grants == [] for grants in reconcile["dynamic_grants"].values())

        participants = initialization["assignment"]["participants"]
        general_part = next(p for p in participants if p["player_id"] == general_pid)
        assert general_part["hp"] == 3 and general_part["max_hp"] == 3
        assert general_part["gender"] == "female"
        assert set(general_part["skill_ids"]) == {QIANCHONG, SHANGJIAN}


# ---------------------------------------------------------------------------
# EV-G3-QIANCHONG-01: choice witnesses + dynamic grants (sections 5, 9, 10)
# ---------------------------------------------------------------------------


def test_qianchong_category_choice_witnesses(
    cell_proofs: dict[str, BridgeFullGameCellProofV1],
) -> None:
    total_choices = 0
    for label in LABELS:
        proof = cell_proofs[label]
        witnesses = proof.qianchong_choice_witnesses
        assert witnesses, f"{label} 必须自然观察到至少一次谦冲PLAY阶段选牌类别机会"
        for w in witnesses:
            total_choices += 1
            assert w["skill_id"] == QIANCHONG
            assert w["owner"] == _general_pid(proof)
            assert w["phase"] == "play"
            assert w["color_classification"] in {"empty", "mixed"}
            legal_types = [opt["public_choice_value"] for opt in w["legal_signed_options"]]
            assert "basic" in legal_types
            assert w["chosen_option"] == "basic"
            assert w["controller_conformance"] is True
            perm = w["permission_after"]
            assert perm is not None
            assert perm["chosen_card_type"] == "basic"
            assert perm["owner_id"] == _general_pid(proof)
            assert w["permission_lifecycle_identity"] is not None
    assert total_choices >= 20


def test_qianchong_dynamic_grant_transitions(
    cell_proofs: dict[str, BridgeFullGameCellProofV1],
) -> None:
    total_grants = 0
    observed_colors = set()
    for label in LABELS:
        proof = cell_proofs[label]
        for w in proof.qianchong_dynamic_grant_witnesses:
            total_grants += 1
            observed_colors.add(w["color_classification_after"])
            assert w["player_id"] == _general_pid(proof)
            after_grants = set(w["dynamic_grants_after"])
            assert not ({WEIMU, MINGZHE} <= after_grants)
            if w["color_classification_after"] == "all_black":
                assert after_grants == {WEIMU}
            elif w["color_classification_after"] == "all_red":
                assert after_grants == {MINGZHE}
            elif w["color_classification_after"] in {"empty", "mixed"}:
                assert after_grants == set()
    assert total_grants >= 5
    assert "all_black" in observed_colors or "all_red" in observed_colors


def test_aggregate_ev_g3_qianchong_01_observed_and_replay_proven(
    cell_proofs: dict[str, BridgeFullGameCellProofV1],
) -> None:
    obligation = next(
        item for item in bridge.EVENT_OBLIGATIONS if item.event_id == "EV-G3-QIANCHONG-01"
    )
    assert obligation.general_key == "wangyuanji"
    covered = [
        label
        for label in LABELS
        if cell_proofs[label].qianchong_choice_witnesses
        and cell_proofs[label].qianchong_event_coverage == SKILL_EVENT_COVERAGE_PROVEN
    ]
    assert covered == list(LABELS)
    assert ("OBSERVED_AND_REPLAY_PROVEN" if covered else "NOT_YET_COVERED") == (
        "OBSERVED_AND_REPLAY_PROVEN"
    )


# ---------------------------------------------------------------------------
# EV-G3-SHANGJIAN-01: loss ledger and HP condition derivations (sections 6, 9)
# ---------------------------------------------------------------------------


def test_shangjian_condition_witnesses(
    cell_proofs: dict[str, BridgeFullGameCellProofV1],
) -> None:
    total_evals = 0
    zero_loss_count = 0
    positive_loss_count = 0
    condition_false_count = 0
    for label in LABELS:
        proof = cell_proofs[label]
        witnesses = proof.shangjian_condition_witnesses
        assert witnesses, f"{label} 必须自然观察到尚俭条件判定事件"
        for w in witnesses:
            total_evals += 1
            assert w["owner_id"] == _general_pid(proof)
            payload = w["recorded_payload"]
            assert payload["skill_id"] == SHANGJIAN
            assert w["rederived_l"] == payload["l_count"]
            assert w["rederived_h"] == payload["h_hp"]
            assert w["rederived_condition"] == payload["condition_met"]
            assert w["rederived_draw_count"] == payload["draw_count"]
            expected_met = w["rederived_l"] <= w["rederived_h"]
            assert w["rederived_condition"] == expected_met
            expected_draw = w["rederived_l"] if expected_met else 0
            assert w["rederived_draw_count"] == expected_draw
            if w["rederived_l"] == 0:
                zero_loss_count += 1
                assert expected_met is True
                assert expected_draw == 0
            else:
                positive_loss_count += 1
            if not expected_met:
                condition_false_count += 1
    assert total_evals >= 50
    assert zero_loss_count >= 1
    assert positive_loss_count >= 1


@pytest.mark.parametrize(
    ("seed", "expected_first_player_id"),
    ((0, "p2"), (1, "p1")),
)
def test_initial_turn_loss_ledger_matches_rng_selected_first_player(
    seed: int, expected_first_player_id: str
) -> None:
    session = bridge.create_skill_aware_fixed_assignment_duel_session_v1(
        seed=seed,
        general_key="wangyuanji",
        seat_assignment="GENERAL_AS_P1",
    )

    assert tuple(call.method for call in session.rng_calls) == ("choice", "shuffle")
    assert session.rng_calls[0].result == expected_first_player_id
    assert session.first_player_id == expected_first_player_id
    assert session.runtime.turn_number == 1
    assert session.runtime.current_player_id == expected_first_player_id
    assert session.turn_loss_ledger.turn_number == 1
    assert session.turn_loss_ledger.turn_player_id == expected_first_player_id
    assert session.turn_loss_ledger.entries == ()
    assert session.turn_loss_ledger.count_losses_this_turn("p1") == 0
    assert session.turn_loss_ledger.count_losses_this_turn("p2") == 0


def test_explicit_first_player_initializes_matching_empty_turn_loss_ledger() -> None:
    session = ProductionBasicCardBatch(seed=0, first_player_id="p2")

    assert tuple(call.method for call in session.rng_calls) == ("shuffle",)
    assert session.first_player_id == "p2"
    assert session.runtime.turn_number == 1
    assert session.runtime.current_player_id == "p2"
    assert session.turn_loss_ledger.turn_number == 1
    assert session.turn_loss_ledger.turn_player_id == "p2"
    assert session.turn_loss_ledger.entries == ()
    assert session.turn_loss_ledger.count_losses_this_turn("p1") == 0
    assert session.turn_loss_ledger.count_losses_this_turn("p2") == 0


def test_turn_loss_ledger_equipment_movements_non_loss() -> None:
    session = bridge.create_skill_aware_fixed_assignment_duel_session_v1(
        seed=0,
        general_key="wangyuanji",
        seat_assignment="GENERAL_AS_P1",
    )
    general_pid = session.assignment.general_player_id
    no_skill_pid = session.assignment.no_skill_player_id
    assert (general_pid, no_skill_pid) == ("p1", "p2")
    assert session.first_player_id == no_skill_pid
    assert session.skill_runtime is not None
    assert session.skill_runtime.has_skill(general_pid, SHANGJIAN)
    assert not session.skill_runtime.has_skill(no_skill_pid, SHANGJIAN)

    executed, enter_processing, installed = _drive_to_first_self_equip_for_player(
        session, owner_id=general_pid
    )
    first_unscoped_equip = next(
        entry
        for entry in session.card_movement_authority
        if entry.semantic_reason.endswith("_equip:enter_processing")
    )
    assert first_unscoped_equip.source_owner_id == no_skill_pid
    assert first_unscoped_equip.card_instance_id != enter_processing.card_instance_id
    assert executed.actor_id == general_pid
    assert executed.card_instance_id == enter_processing.card_instance_id
    assert session.runtime.current_player_id == general_pid
    assert enter_processing.source_owner_id == general_pid
    assert enter_processing.destination_owner_id is None
    assert enter_processing.action_actor_id == general_pid
    assert enter_processing.card_user_id == general_pid
    assert (enter_processing.source_zone, enter_processing.destination_zone) == (
        "hand",
        "processing",
    )
    assert installed.source_owner_id is None
    assert installed.destination_owner_id == general_pid
    assert installed.action_actor_id == general_pid
    assert installed.card_user_id == general_pid
    assert installed.source_zone == "processing"
    assert installed.destination_zone.startswith("equipment:")
    assert enter_processing.root_operation_identity == installed.root_operation_identity
    assert enter_processing.movement_sequence < installed.movement_sequence
    assert enter_processing.counts_as_shangjian_loss is False
    assert installed.counts_as_shangjian_loss is False

    ledger_entries = [
        entry
        for entry in session.turn_loss_ledger.entries
        if entry.movement_identity == enter_processing.movement_identity
    ]
    assert len(ledger_entries) == 1
    ledger_entry = ledger_entries[0]
    assert ledger_entry.losing_player_id == general_pid
    assert ledger_entry.card_instance_id == enter_processing.card_instance_id
    assert ledger_entry.source_zone == enter_processing.source_zone
    assert ledger_entry.destination_zone == enter_processing.destination_zone
    assert ledger_entry.semantic_reason == enter_processing.semantic_reason
    assert (
        ledger_entry.root_operation_identity
        == enter_processing.root_operation_identity
    )
    assert ledger_entry.action_actor_id == general_pid
    assert ledger_entry.card_user_id == general_pid
    assert ledger_entry.counts_as_loss is False


def test_turn_loss_ledger_resets_exactly_at_signed_true_turn_boundary() -> None:
    session = bridge.create_skill_aware_fixed_assignment_duel_session_v1(
        seed=0,
        general_key="wangyuanji",
        seat_assignment="GENERAL_AS_P1",
    )
    assert session.first_player_id == "p2"
    assert session.runtime.turn_number == 1
    assert session.runtime.current_player_id == "p2"
    assert session.turn_loss_ledger.turn_number == 1
    assert session.turn_loss_ledger.turn_player_id == "p2"
    assert session.turn_loss_ledger.entries == ()
    _drive_to_first_completed_end(session)

    previous_turn = session.runtime.turn_number
    ledger_before = session.turn_loss_ledger
    assert ledger_before.turn_number == previous_turn
    assert ledger_before.turn_player_id == session.runtime.current_player_id == "p2"
    assert ledger_before.entries
    assert [action.payload.get("operation") for action in session.legal_actions()] == [
        "end_turn"
    ]

    executed = session.step_with_acceptance_controller_v1()

    assert executed.payload.get("operation") == "end_turn"
    assert session.runtime.turn_number == previous_turn + 1
    assert session.turn_loss_ledger.turn_number == session.runtime.turn_number
    assert (
        session.turn_loss_ledger.turn_player_id == session.runtime.current_player_id
    )
    assert session.turn_loss_ledger.entries == ()
    assert session.turn_loss_ledger.count_losses_this_turn("p1") == 0
    assert session.turn_loss_ledger.count_losses_this_turn("p2") == 0


def test_post_end_loss_waits_for_boundary_without_retroactive_shangjian() -> None:
    session = bridge.create_skill_aware_fixed_assignment_duel_session_v1(
        seed=0,
        general_key="wangyuanji",
        seat_assignment="GENERAL_AS_P1",
    )
    _drive_to_first_completed_end(session)

    evaluations_before = _shangjian_evaluation_count(session)
    losses_before = session.turn_loss_ledger.count_losses_this_turn("p1")
    entries_before = len(session.turn_loss_ledger.entries)
    card_id = session.state.card_ids_in(ZoneRef.hand("p1"))[0]

    # The canonical movement authority seam supplies the otherwise rare later-END
    # loss fact.  END entry and the following turn edge remain real signed Bridge
    # controller steps; this focused regression is not a natural-event witness.
    session._state = session._commit_authoritative_card_movements(
        session.state,
        {card_id: DISCARD_PILE},
        semantic_reason="bridge_g_post_end_loss_regression",
        movement_kind="discard",
        root_operation_identity="bridge-g-post-end-loss-regression",
        action_actor_id="p1",
        card_user_id="p1",
    )

    assert session.turn_loss_ledger.count_losses_this_turn("p1") == losses_before + 1
    assert len(session.turn_loss_ledger.entries) == entries_before + 1
    assert session.turn_loss_ledger.entries[-1].card_instance_id == card_id
    assert session.turn_loss_ledger.entries[-1].counts_as_loss is True
    assert _shangjian_evaluation_count(session) == evaluations_before
    assert session._end_phase_dispatch_state is None

    previous_turn = session.runtime.turn_number
    executed = session.step_with_acceptance_controller_v1()

    assert executed.payload.get("operation") == "end_turn"
    assert session.runtime.turn_number == previous_turn + 1
    assert _shangjian_evaluation_count(session) == evaluations_before
    assert session.turn_loss_ledger.entries == ()


def test_aggregate_ev_g3_shangjian_01_observed_and_replay_proven(
    cell_proofs: dict[str, BridgeFullGameCellProofV1],
) -> None:
    obligation = next(
        item for item in bridge.EVENT_OBLIGATIONS if item.event_id == "EV-G3-SHANGJIAN-01"
    )
    assert obligation.general_key == "wangyuanji"
    covered = [
        label
        for label in LABELS
        if cell_proofs[label].shangjian_condition_witnesses
        and cell_proofs[label].shangjian_event_coverage == SKILL_EVENT_COVERAGE_PROVEN
    ]
    assert covered == list(LABELS)
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


def _find_qianchong_decision(payload):
    for index, decision in enumerate(payload["decisions"]):
        chosen = decision["chosen_semantic_projection"]["projection"]
        if chosen.get("operation") == "qianchong_choice":
            return index, decision
    raise AssertionError("no qianchong choice decision")


def test_tamper_general_assignment_and_base_skills_fail(tamper_source) -> None:
    general = deepcopy(tamper_source)
    general["initialization"]["assignment"]["general_key"] = "zhugezhan"
    _must_fail(general)

    no_qc = deepcopy(tamper_source)
    base = no_qc["initialization"]["base_skill_derivation"]["base_skill_ids"]
    base.remove(QIANCHONG)
    _must_fail(no_qc)

    no_sj = deepcopy(tamper_source)
    base2 = no_sj["initialization"]["base_skill_derivation"]["base_skill_ids"]
    base2.remove(SHANGJIAN)
    _must_fail(no_sj)

    inject_weimu = deepcopy(tamper_source)
    inject_weimu["initialization"]["base_skill_derivation"]["base_skill_ids"].append(WEIMU)
    _must_fail(inject_weimu)

    inject_mingzhe = deepcopy(tamper_source)
    inject_mingzhe["initialization"]["base_skill_derivation"]["base_skill_ids"].append(MINGZHE)
    _must_fail(inject_mingzhe)

    dual_grant = deepcopy(tamper_source)
    init_grants = dual_grant["initialization"]["initial_dynamic_reconcile_result"]["dynamic_grants"]
    init_grants["p1"] = [
        {"target_skill_id": WEIMU, "source_skill_id": QIANCHONG, "active": True},
        {"target_skill_id": MINGZHE, "source_skill_id": QIANCHONG, "active": True},
    ]
    _must_fail(dual_grant)


def test_tamper_qianchong_choice_and_permission_fail(tamper_source) -> None:
    choice_attack = deepcopy(tamper_source)
    index, decision = _find_qianchong_decision(choice_attack)
    alt = next(
        item
        for item in decision["legal_action_projections"]
        if item["projection"]["public_choice_value"] != "basic"
    )
    decision["chosen_action_id"] = alt["projection"]["action_id"]
    decision["chosen_semantic_projection"] = alt
    _must_fail(choice_attack)

    perm_attack = deepcopy(tamper_source)
    index, _decision = _find_qianchong_decision(perm_attack)
    perm_attack["production_authority_trace"][index]["runtime_identity_after"] = ZERO64
    _must_fail(perm_attack)


def test_tamper_shangjian_condition_l_h_draw_and_events_fail(tamper_source) -> None:
    def find_sj_event(payload):
        return next(
            e for e in payload["events"]
            if e.get("event_type") == "skill_condition_evaluated"
            and (e.get("payload") or {}).get("skill_id") == SHANGJIAN
        )

    l_tamper = deepcopy(tamper_source)
    find_sj_event(l_tamper)["payload"]["l_count"] = 99
    _must_fail(l_tamper)

    h_tamper = deepcopy(tamper_source)
    find_sj_event(h_tamper)["payload"]["h_hp"] = 0
    _must_fail(h_tamper)

    cond_tamper = deepcopy(tamper_source)
    ev = find_sj_event(cond_tamper)
    ev["payload"]["condition_met"] = not ev["payload"]["condition_met"]
    _must_fail(cond_tamper)

    draw_tamper = deepcopy(tamper_source)
    find_sj_event(draw_tamper)["payload"]["draw_count"] = 10
    _must_fail(draw_tamper)

    dup_tamper = deepcopy(tamper_source)
    ev_dup = deepcopy(find_sj_event(dup_tamper))
    dup_tamper["events"].append(ev_dup)
    _must_fail(dup_tamper)

    missing_tamper = deepcopy(tamper_source)
    sj_index = next(
        i for i, e in enumerate(missing_tamper["events"])
        if e.get("event_type") == "skill_condition_evaluated"
        and (e.get("payload") or {}).get("skill_id") == SHANGJIAN
    )
    missing_tamper["events"].pop(sj_index)
    _must_fail(missing_tamper)


def test_tamper_terminal_runtime_state_and_cursor_fail(tamper_source) -> None:
    finished = deepcopy(tamper_source)
    finished["outcome"]["finished"] = False
    _must_fail(finished)

    winner = deepcopy(tamper_source)
    current = winner["outcome"]["winner"]
    winner["outcome"]["winner"] = "p2" if current == "p1" else "p1"
    _must_fail(winner)

    runtime = deepcopy(tamper_source)
    runtime["production_authority_trace"][-1]["runtime_identity_after"] = ZERO64
    _must_fail(runtime)

    state = deepcopy(tamper_source)
    state["decisions"][-1]["state_identity_after"] = ZERO64
    _must_fail(state)


def test_tamper_trace_scope_and_natural_cell_id_fail(
    tamper_source, natural_replays
) -> None:
    scope = deepcopy(tamper_source)
    scope["trace_scope"] = BridgeTraceScope.BOUNDED_PRODUCTION_TRACE.value
    scope["outcome"]["trace_scope"] = BridgeTraceScope.BOUNDED_PRODUCTION_TRACE.value
    _must_fail(scope)

    relabeled = natural_replays[TAMPER_LABEL].to_dict()
    relabeled["cell_id"] = "BRIDGE-G-WANGYUANJI-P1-SEED-0"
    relabeled = _rehash(relabeled)
    with pytest.raises((BridgeReplayDivergenceError, BridgeReplayIdentityError)):
        derive_bridge_full_game_cell_proof_v1(
            BridgeFullGameReplayV1.from_dict(relabeled).to_dict()
        )


# ---------------------------------------------------------------------------
# BRIDGE-F remediation non-regression (section 20)
# ---------------------------------------------------------------------------


def test_f_cleanup_terminal_end_phase_dispatch_state_is_none(
    natural_replays: dict[str, BridgeFullGameReplayV1],
) -> None:
    for label, _b18, seat, _seed in WANGYUANJI_SUBMATRIX:
        replay = natural_replays[label]
        session = _replay_to_finished_session(replay, seat)
        assert session.is_finished is True
        assert session.phase is ProductionPhase.FINISHED
        assert session._end_phase_dispatch_state is None
        session.assert_finished_state_invariants()


def test_f_cleanup_dispatcher_guard_blocks_late_resume(
    natural_replays: dict[str, BridgeFullGameReplayV1],
) -> None:
    replay = natural_replays[TAMPER_LABEL]
    session = _replay_to_finished_session(replay, "GENERAL_AS_P1")
    assert session.is_finished is True
    assert session.phase is ProductionPhase.FINISHED
    assert session._end_phase_dispatch_state is None

    event_count_before = len(session.events)
    revision_before = session.state.revision

    returned_state = session._run_end_phase_dispatcher(session.state)

    assert returned_state.revision == revision_before
    assert len(session.events) == event_count_before
    assert session.skill_pending is None
    assert tuple(session._skill_trigger_queue) == ()
    assert session._end_phase_dispatch_state is None


def test_f_cleanup_assert_finished_state_invariants_fails_closed_on_stale_cursor(
    natural_replays: dict[str, BridgeFullGameReplayV1],
) -> None:
    replay = natural_replays[TAMPER_LABEL]
    session = _replay_to_finished_session(replay, "GENERAL_AS_P1")
    session._end_phase_dispatch_state = _EndPhaseDispatchState(
        end_phase_identity="adversarial_test_identity",
        turn_number=1,
        turn_player_id="p1",
        seat_ring=("p1", "p2"),
        current_seat_index=0,
        completed_triggers=(),
        source_event_sequence=1,
    )
    with pytest.raises(ProductionBatchError, match="_end_phase_dispatch_state 必须为 None"):
        session.assert_finished_state_invariants()
