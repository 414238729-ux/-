# -*- coding: utf-8 -*-
"""Targeted bounded/adversarial tests for provisional C8-F evidence."""

from __future__ import annotations

from copy import deepcopy
import hashlib
from pathlib import Path
from typing import Any

import pytest

from scripts.sgs_engine import c8_bounded_timed_8p_trace_v1 as f
from scripts.sgs_engine import c8_c6_production_adapter_v1 as prod
from scripts.sgs_engine import c8_timed_session_runtime_v1 as rt
from scripts.sgs_engine import c8_timeout_controller_integration_v1 as ctl
from scripts.sgs_engine import c8_virtual_time_contract_v1 as clock


REPO_ROOT = Path(__file__).resolve().parents[1]


def _id(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


@pytest.fixture(scope="module")
def primary_trace() -> f.C8FBoundedTraceV1:
    return f.run_trace_a_v1(repo_root=REPO_ROOT, run_label="pytest-primary")


@pytest.fixture(scope="module")
def sibling_trace() -> f.C8FBoundedTraceV1:
    return f.run_trace_a_v1(repo_root=REPO_ROOT, run_label="pytest-sibling")


def _document(trace: f.C8FBoundedTraceV1) -> dict[str, Any]:
    return deepcopy(trace.to_dict())


def _rehash_identity(value: dict[str, Any], identity_key: str) -> None:
    material = {key: item for key, item in value.items() if key != identity_key}
    value[identity_key] = f._identity(material)


def _rehash_cell(cell: dict[str, Any]) -> None:
    _rehash_identity(cell, "cell_identity")


def _rehash_outer(document: dict[str, Any]) -> None:
    document["semantic_trace_identity"] = f._identity(
        f._semantic_trace_material(document)
    )
    _rehash_identity(document, "trace_identity")


def _reject(document: object) -> None:
    with pytest.raises((f.C8FTraceError, TypeError, ValueError)):
        f.C8FBoundedTraceV1.from_dict(document, repo_root=REPO_ROOT)


def _live_stack(label: str, *, seed: int = 0) -> dict[str, Any]:
    session = prod.create_canonical_c6_no_skill_session_v1(seed)
    assert len(prod.advance_canonical_c6_to_first_play_v1(session)) == 3
    adapter = prod.C8C6ProductionAdapterV1(session)
    runtime = rt.C8TimedSessionRuntimeV1(
        inner_adapter=adapter,
        input_authenticator=adapter,
        instance_nonce_identity=_id(f"c8-f-hostile-runtime:{label}"),
        input_source_id=f"c8-f-hostile-{label}",
        driver_authority_identity=_id(f"c8-f-hostile-driver:{label}"),
    )
    controller_identity = _id(f"c8-f-hostile-controller:{label}")
    adapter.bind_runtime_v1(runtime, controller_identity=controller_identity)
    orchestrator = prod.C8C6ProductionWindowOrchestratorV1(adapter, runtime)
    context, ref, opened = orchestrator.observe_and_open_or_refresh_v1()
    assert opened is True
    controller = ctl.TimeoutResolverControllerIntegrationV1(
        runtime,
        adapter,
        controller_instance_identity=controller_identity,
    )
    return {
        "session": session,
        "adapter": adapter,
        "runtime": runtime,
        "orchestrator": orchestrator,
        "context": context,
        "ref": ref,
        "controller": controller,
    }


def test_frozen_scope_and_fresh_a_e_dependency_identity() -> None:
    snapshot = f.current_c8_f_development_snapshot_v1(REPO_ROOT)
    dependencies = snapshot["dependencies"]

    assert f.C8_F_SCOPE_MARKER == "BOUNDED_REAL_PRODUCTION_TRACE_ONLY"
    assert f.C8_F_MAX_BOUNDED_PRODUCTION_STEPS == 16
    assert f.C8_F_MAX_WINDOWS == 8
    assert f.C8_F_FULL_GAME is False
    assert f.C8_F_PRODUCTION_COLD_REPLAY == "NOT_PROVEN"
    assert snapshot["source_sha256"]
    assert snapshot["test_sha256"]
    assert snapshot["development_identity"]
    assert snapshot["current_c8_implementation_identity"]
    assert dependencies["prior_current_c8_implementation_identity"] == (
        "4730dcaa20335cdf234000f48594ca765a019702cdf9ae9f0a1c7c423207181e"
    )
    assert set(dependencies["audited_hashes"]) == set(f._AUDITED_HASHES)


def test_trace_a_is_real_bounded_multiwindow_interleaved_turn_trace(
    primary_trace: f.C8FBoundedTraceV1,
) -> None:
    document = primary_trace.to_dict()
    cells = document["cells"]

    assert document["windows_executed"] == 8
    assert document["trace_production_steps_executed"] == 8
    assert document["total_session_steps"] == 11
    assert document["total_session_steps"] <= 16
    assert document["bounded_limit_reached"] is False
    assert document["production_session_finished"] is False
    assert document["terminal_claimed"] is False
    assert document["full_game"] is False
    assert document["formal_matrix"] is False
    assert document["production_cold_replay"] == "NOT_PROVEN"
    assert [cell["decision_marker"] for cell in cells] == [
        "TIMEOUT_EXACT_BOUNDARY",
        "NORMAL_ON_TIME",
        "NORMAL_ON_TIME",
        "TIMEOUT_EXACT_BOUNDARY",
        "NORMAL_ON_TIME",
        "TIMEOUT_EXACT_BOUNDARY",
        "NORMAL_ON_TIME",
        "TIMEOUT_EXACT_BOUNDARY",
    ]
    assert [cell["pre_state"]["phase"] for cell in cells] == [
        "play", "discard", "discard", "end",
        "prepare", "judgment", "draw", "play",
    ]
    assert [cell["post_state"]["phase"] for cell in cells] == [
        "discard", "discard", "end", "prepare",
        "judgment", "draw", "play", "discard",
    ]
    assert [cell["pre_state"]["turn_number"] for cell in cells] == [
        1, 1, 1, 1, 2, 2, 2, 2,
    ]
    assert cells[0]["pre_state"]["current_actor_id"] != (
        cells[4]["pre_state"]["current_actor_id"]
    )
    assert all(
        cell["post_state"]["production_step_count"]
        == cell["pre_state"]["production_step_count"] + 1
        for cell in cells
    )
    assert document["final_bounded_state"] == cells[-1]["post_state"]


def test_window_refresh_close_and_event_chain_are_continuous(
    primary_trace: f.C8FBoundedTraceV1,
) -> None:
    cells = primary_trace.to_dict()["cells"]
    seen_windows: set[str] = set()
    seen_contexts: set[str] = set()

    for index, cell in enumerate(cells):
        refresh = cell["refresh_evidence"]
        window = cell["window_evidence"]
        opened = window["open_window"]
        context = cell["decision_context"]
        execution = cell["execution_evidence"]

        assert refresh["refresh_opened_new_window"] is False
        assert refresh["deadline_refreshed"] is False
        assert refresh["deadline_before"] == refresh["deadline_after"]
        assert refresh["runtime_state_before_identity"] == (
            refresh["runtime_state_after_identity"]
        )
        assert opened["window_id"] not in seen_windows
        seen_windows.add(opened["window_id"])
        assert opened["parent_window_id"] is None
        assert (
            context["parent_context_identity"] is None
            or context["parent_context_identity"] in seen_contexts
        )
        seen_contexts.add(context["context_identity"])
        assert window["active_window_after_close"] is None
        assert cell["post_state"]["active_window_id"] is None
        assert execution["production_steps_committed"] == 1
        if cell["decision_marker"] == "TIMEOUT_EXACT_BOUNDARY":
            assert execution["decision_tick"] == execution["deadline_at"]
            assert execution["deadline_relation"] == "EQ"
            assert execution["b_timeout_receipt_identity"]
            assert execution["c_controller_result"]["result_kind"] == (
                "RESOLVED_SINGLE"
            )
            assert window["close_status"] == "CLOSED_BY_TIMEOUT"
        else:
            assert execution["decision_tick"] < execution["deadline_at"]
            assert execution["deadline_relation"] == "LT"
            assert execution["on_time_receipt"]["timeout_authority_used"] is False
            assert window["close_status"] == "CLOSED_BY_ACTION"
        if index:
            assert cells[index - 1]["post_state"]["production_execution_identity"] == (
                cell["pre_state"]["production_execution_identity"]
            )
            assert window["runtime_state_before_open_identity"] == (
                cells[index - 1]["post_state"]["runtime_state_identity"]
            )


def test_stale_prior_window_context_and_action_evidence_are_rejected_cross_turn(
    primary_trace: f.C8FBoundedTraceV1,
) -> None:
    document = primary_trace.to_dict()
    rejection = document["stale_rejection_evidence"]
    assert [item["rejection_kind"] for item in rejection] == [
        "STALE_CONTEXT_WINDOW_BIND",
        "STALE_TIMEOUT_DUE_AND_WINDOW_REF",
        "STALE_SIGNED_ACTION_FROM_PRIOR_LEGAL_SET",
    ]
    assert all(item["rejected"] is True for item in rejection)
    assert all(
        item["runtime_state_before_identity"]
        == item["runtime_state_after_identity"]
        for item in rejection
    )
    assert all(item["current_turn_number"] == 2 for item in rejection)


def test_public_trace_has_no_private_payload_keys(
    primary_trace: f.C8FBoundedTraceV1,
) -> None:
    forbidden = {
        "payload", "card_instance_id", "virtual_card", "target_ids", "skill_id",
        "handle", "card_key", "card_name", "rng_state", "raw_snapshot",
    }

    def visit(value: object) -> None:
        if type(value) is dict:
            assert forbidden.isdisjoint(value)
            for child in value.values():
                visit(child)
        elif type(value) is list:
            for child in value:
                visit(child)

    visit(primary_trace.to_dict())
    assert all(
        type(cell["decision_context"]["private_payload_present"]) is bool
        for cell in primary_trace.to_dict()["cells"]
    )


def test_strict_json_round_trip_and_fresh_rerun_match(
    primary_trace: f.C8FBoundedTraceV1,
) -> None:
    cold = f.C8FBoundedTraceV1.from_json_bytes_v1(
        primary_trace.to_json_bytes_v1(), repo_root=REPO_ROOT
    )
    assert cold.trace_identity == primary_trace.trace_identity
    assert f.verify_with_fresh_reexecution_v1(
        cold, repo_root=REPO_ROOT, run_label="pytest-fresh-verifier"
    ) == primary_trace.semantic_trace_identity


def test_duplicate_json_key_is_rejected(
    primary_trace: f.C8FBoundedTraceV1,
) -> None:
    raw = primary_trace.to_json_bytes_v1().replace(
        b'{"audited_dependency_hashes":',
        b'{"schema":"duplicate","audited_dependency_hashes":',
        1,
    )
    with pytest.raises(f.C8FTraceError):
        f.C8FBoundedTraceV1.from_json_bytes_v1(raw, repo_root=REPO_ROOT)


@pytest.mark.parametrize(
    ("mutation",),
    [
        (lambda doc: doc.pop("contract_binding_set_identity"),),
        (lambda doc: doc.__setitem__("windows_executed", "8"),),
        (lambda doc: doc.__setitem__("contract_version", True),),
        (lambda doc: doc.__setitem__("seed", False),),
        (lambda doc: doc.__setitem__("full_game", 0),),
        (lambda doc: doc.__setitem__("unknown_authority", "x"),),
        (lambda doc: doc.__setitem__("passed", True),),
    ],
    ids=[
        "missing-required", "type-drift", "bool-version-drift",
        "bool-seed-drift", "int-full-game-drift", "unknown-field",
        "serialized-passed",
    ],
)
def test_required_unknown_and_type_drift_fail_closed(
    primary_trace: f.C8FBoundedTraceV1,
    mutation: Any,
) -> None:
    document = _document(primary_trace)
    mutation(document)
    _reject(document)


@pytest.mark.parametrize("case", ["reorder", "duplicate", "delete"])
def test_stored_trace_reorder_duplicate_delete_fail_closed(
    primary_trace: f.C8FBoundedTraceV1,
    case: str,
) -> None:
    document = _document(primary_trace)
    if case == "reorder":
        document["cells"][1], document["cells"][2] = (
            document["cells"][2], document["cells"][1]
        )
    elif case == "duplicate":
        document["cells"][2] = deepcopy(document["cells"][1])
    else:
        del document["cells"][2]
    _rehash_outer(document)
    _reject(document)


def test_sibling_trace_splice_fails_closed_after_outer_rehash(
    primary_trace: f.C8FBoundedTraceV1,
    sibling_trace: f.C8FBoundedTraceV1,
) -> None:
    document = _document(primary_trace)
    sibling = sibling_trace.to_dict()
    assert document["trace_identity"] != sibling["trace_identity"]
    document["cells"][3] = deepcopy(sibling["cells"][3])
    _rehash_outer(document)
    _reject(document)


@pytest.mark.parametrize(
    ("path", "replacement"),
    [
        (("seed",), 1),
        (("session_binding_identity",), "a" * 64),
        (("mode_id",), "wrong-mode"),
        (("current_c8_implementation_identity",), "b" * 64),
        (("contract_bindings", "c8_e_adapter_id"), "wrong-adapter"),
    ],
    ids=["seed", "session", "mode", "current-implementation", "e-adapter"],
)
def test_wrong_seed_session_mode_current_or_e_identity_fails_closed(
    primary_trace: f.C8FBoundedTraceV1,
    path: tuple[str, ...],
    replacement: object,
) -> None:
    document = _document(primary_trace)
    target = document
    for part in path[:-1]:
        target = target[part]
    target[path[-1]] = replacement
    _rehash_outer(document)
    _reject(document)


def test_stale_context_carried_into_later_turn_fails_closed(
    primary_trace: f.C8FBoundedTraceV1,
) -> None:
    document = _document(primary_trace)
    document["cells"][4]["decision_context"] = deepcopy(
        document["cells"][0]["decision_context"]
    )
    _rehash_cell(document["cells"][4])
    _rehash_outer(document)
    _reject(document)


def test_on_time_evidence_at_exact_deadline_fails_closed(
    primary_trace: f.C8FBoundedTraceV1,
) -> None:
    document = _document(primary_trace)
    cell = next(
        item for item in document["cells"]
        if item["decision_marker"] == "NORMAL_ON_TIME"
    )
    execution = cell["execution_evidence"]
    execution["decision_tick"] = execution["deadline_at"]
    execution["deadline_relation"] = "EQ"
    _rehash_identity(execution, "execution_evidence_identity")
    _rehash_cell(cell)
    _rehash_outer(document)
    _reject(document)


def test_timeout_evidence_before_deadline_fails_closed(
    primary_trace: f.C8FBoundedTraceV1,
) -> None:
    document = _document(primary_trace)
    cell = next(
        item for item in document["cells"]
        if item["decision_marker"] == "TIMEOUT_EXACT_BOUNDARY"
    )
    execution = cell["execution_evidence"]
    execution["decision_tick"] = execution["deadline_at"] - 1
    execution["deadline_relation"] = "LT"
    _rehash_identity(execution, "execution_evidence_identity")
    _rehash_cell(cell)
    _rehash_outer(document)
    _reject(document)


def test_same_context_deadline_refresh_tamper_fails_closed(
    primary_trace: f.C8FBoundedTraceV1,
) -> None:
    document = _document(primary_trace)
    cell = document["cells"][2]
    refresh = cell["refresh_evidence"]
    refresh["deadline_after"] += 1
    refresh["deadline_refreshed"] = True
    _rehash_identity(refresh, "refresh_evidence_identity")
    _rehash_cell(cell)
    _rehash_outer(document)
    _reject(document)


def test_nested_driver_policy_bool_int_alias_fails_closed(
    primary_trace: f.C8FBoundedTraceV1,
) -> None:
    document = _document(primary_trace)
    document["driver_policy"]["production_order_resorted"] = 0
    _rehash_outer(document)
    _reject(document)


def test_nested_proposal_count_bool_int_alias_fails_closed(
    primary_trace: f.C8FBoundedTraceV1,
) -> None:
    document = _document(primary_trace)
    cell = next(
        item for item in document["cells"]
        if item["proposal_evidence"]["proposal_count"] == 1
    )
    proposal = cell["proposal_evidence"]
    proposal["proposal_count"] = True
    _rehash_identity(proposal, "proposal_evidence_identity")
    _rehash_cell(cell)
    _rehash_outer(document)
    _reject(document)


def test_public_proposal_order_tamper_fails_closed(
    primary_trace: f.C8FBoundedTraceV1,
) -> None:
    document = _document(primary_trace)
    cell = document["cells"][0]
    proposal = cell["proposal_evidence"]
    proposal["action_ids_in_production_order"].reverse()
    _rehash_identity(proposal, "proposal_evidence_identity")
    _rehash_cell(cell)
    _rehash_outer(document)
    _reject(document)


def test_timeout_receipt_controller_result_mismatch_fails_closed(
    primary_trace: f.C8FBoundedTraceV1,
) -> None:
    document = _document(primary_trace)
    cell = document["cells"][0]
    execution = cell["execution_evidence"]
    execution["b_timeout_receipt_identity"] = "c" * 64
    _rehash_identity(execution, "execution_evidence_identity")
    _rehash_cell(cell)
    _rehash_outer(document)
    _reject(document)


@pytest.mark.parametrize(
    ("field", "value"),
    [("phase", "draw"), ("turn_number", 99), ("current_actor_id", "p1")],
    ids=["phase", "turn", "actor"],
)
def test_wrong_actor_turn_phase_binding_fails_closed_after_rehash(
    primary_trace: f.C8FBoundedTraceV1,
    field: str,
    value: object,
) -> None:
    document = _document(primary_trace)
    cell = document["cells"][4]
    cell["pre_state"][field] = value
    _rehash_identity(cell["pre_state"], "state_identity")
    _rehash_cell(cell)
    _rehash_outer(document)
    _reject(document)


def test_private_payload_injection_fails_before_outer_hash_authority(
    primary_trace: f.C8FBoundedTraceV1,
) -> None:
    document = _document(primary_trace)
    document["cells"][0]["proposal_evidence"]["payload"] = {"card": "secret"}
    _rehash_identity(
        document["cells"][0]["proposal_evidence"],
        "proposal_evidence_identity",
    )
    _rehash_cell(document["cells"][0])
    _rehash_outer(document)
    _reject(document)


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("max_bounded_production_steps", 4000),
        ("max_windows", 800),
        ("bounded_limit_reached", True),
        ("full_game", True),
        ("formal_matrix", True),
        ("terminal_claimed", True),
        ("production_session_finished", True),
    ],
)
def test_bounded_limits_or_full_game_terminal_claim_tamper_fails_closed(
    primary_trace: f.C8FBoundedTraceV1,
    name: str,
    value: object,
) -> None:
    document = _document(primary_trace)
    document[name] = value
    _rehash_outer(document)
    _reject(document)


def test_deep_tamper_with_recomputed_nonsecret_hashes_still_fails_semantics(
    primary_trace: f.C8FBoundedTraceV1,
) -> None:
    document = _document(primary_trace)
    cell = document["cells"][1]
    cell["pre_state"]["phase"] = "DRAW"
    _rehash_identity(cell["pre_state"], "state_identity")
    _rehash_cell(cell)
    _rehash_outer(document)
    _reject(document)


def test_live_exact_deadline_rejects_normal_action_without_production_step() -> None:
    stack = _live_stack("exact-deadline")
    session = stack["session"]
    adapter = stack["adapter"]
    runtime = stack["runtime"]
    ref = stack["ref"]
    active = runtime.state.virtual_time_state.window_stack.active_window
    assert active is not None
    advance = adapter.issue_virtual_time_advance_v1(
        requested_tick=active.deadline_at
    )
    result = runtime.ingest_virtual_time_input(
        advance,
        expected_previous_input_chain_tip=runtime.state.input_chain_tip,
        duration_profile_identity=clock.ENGINEERING_TEST_PROFILE_V1.profile_identity,
    )
    assert result.derived_deadline is not None
    selected = session.legal_actions()[-1].action_id
    before_execution = session.execution_hash
    before_steps = session.step_count
    before_outer = runtime.state

    with pytest.raises(rt.C8TimedSessionRuntimeError):
        runtime.forward_on_time_signed_action_id(ref, signed_action_id=selected)

    assert session.execution_hash == before_execution
    assert session.step_count == before_steps
    assert runtime.state == before_outer


def test_live_timeout_before_deadline_rejects_without_production_step() -> None:
    stack = _live_stack("timeout-too-early")
    session = stack["session"]
    runtime = stack["runtime"]
    before_execution = session.execution_hash
    before_steps = session.step_count
    before_outer = runtime.state

    result = stack["controller"].resolve_timeout_v1(
        stack["ref"], timeout_due_commitment=None
    )

    assert result.result_kind == ctl.ControllerResultKindV1.FAILED_ROLLED_BACK.value
    assert result.reason == "TIMEOUT_DUE_PRECONDITION_REJECTED"
    assert session.execution_hash == before_execution
    assert session.step_count == before_steps
    assert runtime.state == before_outer


def test_live_cross_session_signed_action_substitution_fails_closed() -> None:
    first = _live_stack("cross-session-first", seed=0)
    second = _live_stack("cross-session-second", seed=1)
    foreign = first["session"].legal_actions()[0].action_id
    assert foreign not in {
        item.action_id for item in second["session"].legal_actions()
    }
    before_execution = second["session"].execution_hash
    before_outer = second["runtime"].state

    with pytest.raises(rt.C8TimedSessionRuntimeError):
        second["runtime"].forward_on_time_signed_action_id(
            second["ref"], signed_action_id=foreign
        )

    assert second["session"].execution_hash == before_execution
    assert second["runtime"].state == before_outer


@pytest.mark.parametrize("key,old_hash", [
    ("c8_e_source", "1b56952e34941d96c13b8f0d70e1cafc9f4b7db3c13d9461a3f8e122b63737ad"),
    ("c8_e_test", "266a012990f47168306c8f7a5095711261a060686733aeea872abd73f7868f8a"),
])
def test_step1362_old_e_audited_binding_strictly_rejected(key, old_hash, monkeypatch):
    old_audited = dict(f._AUDITED_HASHES)
    old_audited[key] = old_hash
    monkeypatch.setattr(f, "_AUDITED_HASHES", old_audited)
    with pytest.raises(f.C8FTraceError, match="C8_F_A_E_AUDITED_HASH_DRIFT"):
        f.audited_dependency_snapshot_v1(REPO_ROOT)
