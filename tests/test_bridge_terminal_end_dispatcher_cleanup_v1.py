# -*- coding: utf-8 -*-
"""BRIDGE-F — Terminal End-Dispatcher Production Cleanup Remediation V1 (B2_PRODUCTION_CLEANUP).

Verifies:
1. Frozen production terminal cleanup: every natural formal terminal has
   `session._end_phase_dispatch_state is None`.
2. F-001..F-006 natural terminal verification (seeds 0, 1, 49, mirrored seats).
3. Production invariant fail-closed: `assert_finished_state_invariants()` requires
   `_end_phase_dispatch_state is None`.
4. Defense-in-depth against internal resume attack: invoking
   `_run_end_phase_dispatcher(state)` on a natural finished session is inert.
5. Representative tamper battery against terminal cleanup, trace authorities, and outcomes
   with attacker-recomputed outer identities.
"""

from __future__ import annotations

from copy import deepcopy
import json

import pytest

from scripts.sgs_engine.model import DRAW_PILE
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
    BridgeFullGameCellProofV1,
    BridgeFullGameReplayV1,
    BridgeReplayDivergenceError,
    BridgeReplayIdentityError,
    _create_skill_aware_fixed_assignment_duel_session_for_strict_replay_v1,
    derive_bridge_full_game_cell_proof_v1,
    recompute_bridge_replay_identities_v1,
    record_natural_full_game_skill_aware_fixed_assignment_bridge_replay_v1,
    reexecute_skill_aware_fixed_assignment_bridge_replay_v1,
)


ZHUGEZHAN_SUBMATRIX = (
    ("F-001", "B18-007", "GENERAL_AS_P1", 0),
    ("F-002", "B18-008", "GENERAL_AS_P1", 1),
    ("F-003", "B18-009", "GENERAL_AS_P1", 49),
    ("F-004", "B18-010", "GENERAL_AS_P2", 0),
    ("F-005", "B18-011", "GENERAL_AS_P2", 1),
    ("F-006", "B18-012", "GENERAL_AS_P2", 49),
)
LABELS = tuple(item[0] for item in ZHUGEZHAN_SUBMATRIX)
FORMAL_TERMINAL_HP_LOSS_LABELS = ("F-001", "F-005", "F-006")


def _cold_round_trip(replay: BridgeFullGameReplayV1) -> BridgeFullGameReplayV1:
    encoded = json.dumps(
        replay.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return BridgeFullGameReplayV1.from_dict(json.loads(encoded))


def _rehash(payload: dict[str, object]) -> dict[str, object]:
    return recompute_bridge_replay_identities_v1(payload)


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


def _replay_to_finished_session(replay: BridgeFullGameReplayV1, seat: str):
    assignment = create_bridge_assignment(general_key="zhugezhan", seat_assignment=seat)
    signing = replay.authoritative_private["signing_authority"]
    session = _create_skill_aware_fixed_assignment_duel_session_for_strict_replay_v1(
        seed=replay.seed,
        assignment=assignment,
        session_id=signing["session_id"],
        session_secret_hex=signing["session_secret_hex"],
        capability=_BRIDGE_STRICT_REPLAY_RECONSTRUCTION_CAPABILITY,
    )
    for dec in replay.decisions:
        session.step(dec["chosen_action_id"])
    return session


# ---------------------------------------------------------------------------
# 1. Natural terminal cursor verification for all six cells (Sections 6 & 7)
# ---------------------------------------------------------------------------


def test_remediated_terminal_cursor_is_none_six_of_six(
    cell_proofs: dict[str, BridgeFullGameCellProofV1],
) -> None:
    """Every formal terminal must report end_phase_dispatch_state_none == True."""
    for label in LABELS:
        terminal = cell_proofs[label].terminal_invariants
        assert terminal["phase"] == "finished"
        assert terminal["finished"] is True
        assert terminal["engine_finished_invariants_passed"] is True
        assert (
            terminal["end_phase_dispatch_state_none"] is True
        ), f"{label} terminal cursor 必须为 None"
        assert terminal["end_dispatcher_cannot_resume"] is True


def test_f001_f005_f006_specific_remediation(
    cell_proofs: dict[str, BridgeFullGameCellProofV1],
) -> None:
    """The 3 cells previously failing end_phase_dispatch_state_none now strictly pass."""
    for label in FORMAL_TERMINAL_HP_LOSS_LABELS:
        terminal = cell_proofs[label].terminal_invariants
        assert terminal["end_phase_dispatch_state_none"] is True
        assert terminal["pending_skill_hp_loss_none"] is True
        assert terminal["pending_private_card_selection_none"] is True


def test_f002_f003_f004_non_regression(
    cell_proofs: dict[str, BridgeFullGameCellProofV1],
) -> None:
    """The 3 cells that were already None remain None."""
    for label in ("F-002", "F-003", "F-004"):
        terminal = cell_proofs[label].terminal_invariants
        assert terminal["end_phase_dispatch_state_none"] is True


# ---------------------------------------------------------------------------
# 2. Adversarial internal resume attack reproduction (Section 8)
# ---------------------------------------------------------------------------


def test_adversarial_internal_resume_on_natural_terminal_session(
    natural_replays: dict[str, BridgeFullGameReplayV1],
) -> None:
    """Invoking _run_end_phase_dispatcher on real finished sessions is strictly inert.

    Attacks F-001, F-005, F-006 natural terminal sessions: verifies no new events,
    no state mutation, no reopened decision, and cursor remains None.
    """
    for label, _b18, seat, _seed in ZHUGEZHAN_SUBMATRIX:
        if label not in FORMAL_TERMINAL_HP_LOSS_LABELS:
            continue
        replay = natural_replays[label]
        live_session = _replay_to_finished_session(replay, seat)

        assert live_session.is_finished is True
        assert live_session.phase is ProductionPhase.FINISHED
        assert live_session._end_phase_dispatch_state is None

        event_count_before = len(live_session.events)
        revision_before = live_session.state.revision
        cards_before = tuple(live_session.state.card_ids_in(DRAW_PILE))

        # ADVERSARIAL INVOCATION ON REAL FINISHED SESSION
        returned_state = live_session._run_end_phase_dispatcher(live_session.state)

        assert returned_state.revision == revision_before
        assert len(live_session.events) == event_count_before
        assert live_session.skill_pending is None
        assert tuple(live_session._skill_trigger_queue) == ()
        assert live_session._end_phase_dispatch_state is None
        assert tuple(live_session.state.card_ids_in(DRAW_PILE)) == cards_before


# ---------------------------------------------------------------------------
# 3. Production finished invariant fail-closed verification (Section 3)
# ---------------------------------------------------------------------------


def test_production_finished_invariant_fail_closed_on_uncleared_cursor(
    natural_replays: dict[str, BridgeFullGameReplayV1],
) -> None:
    """If _end_phase_dispatch_state is non-None at FINISHED, assert_finished_state_invariants fails."""
    replay = natural_replays["F-001"]
    session = _replay_to_finished_session(replay, "GENERAL_AS_P1")

    assert session.is_finished is True
    assert session._end_phase_dispatch_state is None
    # Production invariant passes cleanly when cursor is None
    session.assert_finished_state_invariants()

    # Artificially inject an uncleared cursor
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


# ---------------------------------------------------------------------------
# 4. Deep tamper battery (Section 11) - Attacker recomputes outer identities
# ---------------------------------------------------------------------------


def test_tamper_a_production_trace_dispatch_state_non_none(
    natural_replays: dict[str, BridgeFullGameReplayV1],
) -> None:
    """Tampering recorded production authority trace to falsify movement_ledger_end_identity fails."""
    tamper_label = "F-001"
    raw = deepcopy(natural_replays[tamper_label].to_dict())
    last_step = raw["production_authority_trace"][-1]
    # Inject forged identity into movement_ledger_end_identity_after
    last_step["movement_ledger_end_identity_after"] = "0" * 64
    tampered_replay = BridgeFullGameReplayV1.from_dict(_rehash(raw))
    with pytest.raises(BridgeReplayDivergenceError, match="production authority trace不匹配"):
        reexecute_skill_aware_fixed_assignment_bridge_replay_v1(tampered_replay)


def test_tamper_b_terminal_invariant_payload_dispatch_state_none_false() -> None:
    """Tampering terminal invariants to set end_phase_dispatch_state_none=False fails derivation."""
    from scripts.sgs_engine.skill_aware_fixed_assignment_full_game_bridge_replay import (
        _terminal_invariants_value,
    )
    class MockFinishedSession:
        is_finished = True
        phase = ProductionPhase.FINISHED
        winner_id = "p2"
        runtime = type("MockRuntime", (), {"response_window_id": None, "pending_dying_id": None})()
        state = type("MockState", (), {"card_ids_in": lambda self, zone: ()})()
        skill_pending = None
        _skill_trigger_queue = ()
        _pending_private_card_selection = None
        _pending_skill_hp_loss = None
        _pending_card_continuation = None
        _end_phase_dispatch_state = object()  # non-None cursor!
        _continuation_in_progress_id = None
        def assert_finished_state_invariants(self): pass
        def _resolve_public_finish_reason(self): return "normal_death"
        def step(self, action_id):
            from scripts.sgs_engine.production_batch import ProductionBatchFinishedError
            raise ProductionBatchFinishedError("finished")
        def public_action_surface_v1(self):
            from scripts.sgs_engine.production_batch import ProductionBatchFinishedError
            raise ProductionBatchFinishedError("finished")

    with pytest.raises(BridgeReplayDivergenceError, match="terminal cleanup invariants失败.*end_phase_dispatch_state_none"):
        _terminal_invariants_value(MockFinishedSession())


def test_tamper_c_remove_cleanup_related_authority(
    natural_replays: dict[str, BridgeFullGameReplayV1],
) -> None:
    """Removing production authority trace entries fails length validation."""
    tamper_label = "F-001"
    raw = deepcopy(natural_replays[tamper_label].to_dict())
    raw["production_authority_trace"] = raw["production_authority_trace"][:-1]
    with pytest.raises(BridgeReplayDivergenceError, match="production authority trace长度不一致"):
        BridgeFullGameReplayV1.from_dict(_rehash(raw))


def test_tamper_d_tamper_terminal_outcome(
    natural_replays: dict[str, BridgeFullGameReplayV1],
) -> None:
    """Tampering terminal winner in outcome fails strict replay."""
    tamper_label = "F-001"
    raw = deepcopy(natural_replays[tamper_label].to_dict())
    current_winner = raw["outcome"]["winner"]
    falsified_winner = "p1" if current_winner == "p2" else "p2"
    raw["outcome"]["winner"] = falsified_winner
    tampered_replay = BridgeFullGameReplayV1.from_dict(_rehash(raw))
    with pytest.raises(BridgeReplayDivergenceError, match="outcome不匹配"):
        reexecute_skill_aware_fixed_assignment_bridge_replay_v1(tampered_replay)


def test_tamper_e_tamper_end_cursor_identity(
    natural_replays: dict[str, BridgeFullGameReplayV1],
) -> None:
    """Tampering end dispatch step identity fails strict replay."""
    tamper_label = "F-001"
    raw = deepcopy(natural_replays[tamper_label].to_dict())
    first_step = raw["production_authority_trace"][0]
    first_step["movement_ledger_end_identity_before"] = "f" * 64
    tampered_replay = BridgeFullGameReplayV1.from_dict(_rehash(raw))
    with pytest.raises(BridgeReplayDivergenceError, match="production authority trace不匹配"):
        reexecute_skill_aware_fixed_assignment_bridge_replay_v1(tampered_replay)
