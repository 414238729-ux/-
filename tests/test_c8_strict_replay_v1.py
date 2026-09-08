# -*- coding: utf-8 -*-
"""Cheap, synthetic-only evidence tests for provisional C8-D strict replay."""

from __future__ import annotations

from copy import deepcopy
import inspect
import json
from pathlib import Path
from typing import Any, Callable

import pytest

from scripts.sgs_engine import c8_strict_replay_v1 as replay
from scripts.sgs_engine import c8_timed_session_runtime_v1 as rt
from scripts.sgs_engine import c8_virtual_time_contract_v1 as c8


def _id(label: str) -> str:
    return replay.c8_replay_identity_v1(
        {"schema": "sgs-c8-d-test-label-v1", "label": label}
    )


def _open(
    index: int,
    key: str,
    kind: c8.TimedWindowKindV1,
    *,
    parent: str | None = None,
) -> replay.C8ReplayCommandV1:
    return replay.C8ReplayCommandV1.open_window(
        command_index=index,
        window_key=key,
        actor_id=f"actor-{key}",
        window_kind=kind,
        decision_identity=_id(f"decision:{key}"),
        obligation_identity=_id(f"obligation:{key}"),
        parent_window_key=parent,
    )


def _advance(index: int, key: str, tick: int) -> replay.C8ReplayCommandV1:
    return replay.C8ReplayCommandV1.advance_time(
        command_index=index, window_key=key, requested_tick=tick
    )


def _resolve(
    index: int,
    key: str,
    families: tuple[tuple[c8.PublicActionFamilyV1, ...], ...],
    completion: tuple[bool, ...],
) -> replay.C8ReplayCommandV1:
    return replay.C8ReplayCommandV1.resolve_timeout(
        command_index=index,
        window_key=key,
        families_by_step=families,
        completion_by_step=completion,
    )


def _simple_commands() -> tuple[replay.C8ReplayCommandV1, ...]:
    return (
        _open(0, "play", c8.TimedWindowKindV1.PLAY),
        _advance(1, "play", 100),
        _resolve(
            2,
            "play",
            ((c8.PublicActionFamilyV1.END_PLAY_PHASE,),),
            (True,),
        ),
    )


def _comprehensive_commands() -> tuple[replay.C8ReplayCommandV1, ...]:
    commands: list[replay.C8ReplayCommandV1] = []

    def add_open(
        key: str,
        kind: c8.TimedWindowKindV1,
        *,
        parent: str | None = None,
    ) -> None:
        commands.append(_open(len(commands), key, kind, parent=parent))

    def add_advance(key: str, tick: int) -> None:
        commands.append(_advance(len(commands), key, tick))

    def add_resolve(
        key: str,
        families: tuple[tuple[c8.PublicActionFamilyV1, ...], ...],
        completion: tuple[bool, ...],
    ) -> None:
        commands.append(_resolve(len(commands), key, families, completion))

    add_open("optional", c8.TimedWindowKindV1.OPTIONAL_RESPONSE)
    add_advance("optional", 100)
    add_resolve(
        "optional",
        ((c8.PublicActionFamilyV1.MANDATORY_ACTION, c8.PublicActionFamilyV1.PASS_RESPONSE),),
        (True,),
    )
    add_open("mandatory", c8.TimedWindowKindV1.MANDATORY_SINGLE_ACTION)
    add_advance("mandatory", 200)
    add_resolve(
        "mandatory", ((c8.PublicActionFamilyV1.MANDATORY_ACTION,),), (True,)
    )
    add_open("ordinal", c8.TimedWindowKindV1.MANDATORY_PUBLIC_CHOICE)
    add_advance("ordinal", 300)
    add_resolve(
        "ordinal",
        ((c8.PublicActionFamilyV1.PUBLIC_CHOICE,) * 3,),
        (True,),
    )
    add_open("chain2", c8.TimedWindowKindV1.MULTI_STEP_OBLIGATION)
    add_advance("chain2", 400)
    add_resolve(
        "chain2",
        ((c8.PublicActionFamilyV1.DECLINE_OPTIONAL,),) * 2,
        (False, True),
    )
    add_open("chain3", c8.TimedWindowKindV1.MULTI_STEP_OBLIGATION)
    add_advance("chain3", 500)
    add_resolve(
        "chain3",
        ((c8.PublicActionFamilyV1.DECLINE_OPTIONAL,),) * 3,
        (False, False, True),
    )
    add_open("parent", c8.TimedWindowKindV1.PLAY)
    add_advance("parent", 520)
    add_open(
        "child", c8.TimedWindowKindV1.OPTIONAL_RESPONSE, parent="parent"
    )
    add_advance("child", 620)
    add_resolve(
        "child", ((c8.PublicActionFamilyV1.PASS_RESPONSE,),), (True,)
    )
    add_advance("parent", 700)
    add_resolve(
        "parent", ((c8.PublicActionFamilyV1.END_PLAY_PHASE,),), (True,)
    )
    return tuple(commands)


@pytest.fixture(scope="session", autouse=True)
def _explicit_compatibility_regression_scope():
    import os
    incoming = os.environ.get("C8_COMPAT_TEST_CONFIG")
    if not incoming:
        yield
        return
    from scripts.sgs_engine import c8_timed_replay_version_compatibility_v1 as compatibility
    config = json.loads(Path(incoming).read_bytes())
    policy = compatibility.PinnedCompatibilityPolicyV1.load(Path(config["policy"]),
        expected_sha256=config["policy_sha256"], producer_root=Path(config["producer_root"]),
        verifier_root=Path(__file__).resolve().parents[1])
    with compatibility._verification_scope(Path(config["d_envelope"]).read_bytes(),
            Path(config["d_artifact"]).read_bytes(), policy):
        yield


@pytest.fixture(scope="session")
def simple_replay() -> replay.C8StrictReplayV1:
    from scripts.sgs_engine import c8_timed_replay_version_compatibility_v1 as compatibility
    if compatibility.active_v1():
        return replay.C8StrictReplayV1.from_json_bytes(compatibility.d_original_artifacts_v1()["simple"]["raw_utf8"].encode("utf-8"))
    return replay.record_c8_timed_session_trace_v1(
        initial_material=replay.C8ReplayInitialMaterialV1.build("simple-play"),
        commands=_simple_commands(),
    )


@pytest.fixture(scope="session")
def comprehensive_replay() -> replay.C8StrictReplayV1:
    from scripts.sgs_engine import c8_timed_replay_version_compatibility_v1 as compatibility
    if compatibility.active_v1():
        return replay.C8StrictReplayV1.from_json_bytes(compatibility.d_original_artifacts_v1()["comprehensive"]["raw_utf8"].encode("utf-8"))
    return replay.record_c8_timed_session_trace_v1(
        initial_material=replay.C8ReplayInitialMaterialV1.build("all-semantics"),
        commands=_comprehensive_commands(),
    )


def _set_path(root: Any, path: tuple[Any, ...], value: Any) -> None:
    current = root
    for key in path[:-1]:
        current = current[key]
    current[path[-1]] = value


def _mutated(
    value: replay.C8StrictReplayV1,
    path: tuple[Any, ...],
    replacement: Any,
) -> dict[str, object]:
    data = deepcopy(value.to_dict())
    _set_path(data, path, replacement)
    return data


def test_simple_play_record_serialize_cold_load_and_reexecute(
    simple_replay: replay.C8StrictReplayV1,
) -> None:
    raw = simple_replay.to_json_bytes()
    loaded = replay.C8StrictReplayV1.from_json_bytes(raw)
    proof = replay.strict_reexecute_c8_replay_v1(loaded)
    assert proof.status == "MATCH"
    assert proof.fresh_isolated_process is True
    assert proof.live_authority_reissued is True
    assert proof.serialized_authority_accepted is False
    assert proof.production_adapter_integration == "NOT_PROVEN"
    assert proof.full_game == "NOT_PROVEN"


def test_record_api_rejects_caller_supplied_untyped_passed_result() -> None:
    with pytest.raises(replay.C8ReplayError):
        replay.record_c8_timed_session_trace_v1(  # type: ignore[arg-type]
            initial_material={"caller_claim": "PASSED"}, commands=_simple_commands()
        )


def test_failed_controller_transaction_is_not_promoted_to_committed_replay() -> None:
    commands = (
        _open(0, "failed", c8.TimedWindowKindV1.OPTIONAL_RESPONSE),
        _advance(1, "failed", 100),
        _resolve(
            2,
            "failed",
            ((c8.PublicActionFamilyV1.MANDATORY_ACTION,),),
            (True,),
        ),
    )
    from scripts.sgs_engine import c8_timed_replay_version_compatibility_v1 as compatibility
    if compatibility.active_v1():
        with pytest.raises(ValueError):
            replay._ReplayExecution(replay.C8ReplayInitialMaterialV1.build("failed-transaction")).run(commands)
        with pytest.raises(compatibility.C8CompatibilityError, match="只允许验证"):
            replay.record_c8_timed_session_trace_v1(
                initial_material=replay.C8ReplayInitialMaterialV1.build("failed-transaction"), commands=commands)
        assert replay.C8_D_FAILED_ATTEMPT_POLICY.startswith("NOT_A_COMMITTED")
        return
    with pytest.raises(replay.C8ReplayDivergenceError):
        replay.record_c8_timed_session_trace_v1(
            initial_material=replay.C8ReplayInitialMaterialV1.build(
                "failed-transaction"
            ),
            commands=commands,
        )
    assert replay.C8_D_FAILED_ATTEMPT_POLICY.startswith("NOT_A_COMMITTED")


def test_optional_mandatory_and_public_ordinal_semantics(
    comprehensive_replay: replay.C8StrictReplayV1,
) -> None:
    records = comprehensive_replay.execution_evidence.to_dict()["command_records"]
    results = {
        record["window_ref"]["window_id"]: record["controller_result"]
        for record in records
        if record["controller_result"] is not None
    }
    optional = records[2]["controller_result"]
    mandatory = records[5]["controller_result"]
    ordinal = records[8]["controller_result"]
    assert optional["selected_actions"][0]["action_family"] == "pass_response"
    assert optional["selected_actions"][0]["public_ordinal"] == 1
    assert mandatory["selected_actions"][0]["action_family"] == "mandatory_action"
    assert mandatory["selected_actions"][0]["public_ordinal"] == 0
    assert ordinal["selected_actions"][0]["action_family"] == "public_choice"
    assert ordinal["selected_actions"][0]["public_ordinal"] == 0
    assert len(results) == 7


def test_two_and_three_step_same_tick_chains_are_fresh_and_stable(
    comprehensive_replay: replay.C8StrictReplayV1,
) -> None:
    records = comprehensive_replay.execution_evidence.to_dict()["command_records"]
    for record, count in ((records[11], 2), (records[14], 3)):
        result = record["controller_result"]
        assert result["result_kind"] == "RESOLVED_CHAIN"
        assert result["step_count"] == count
        assert len(set(result["legal_set_identities"])) == count
        assert len(set(result["receipt_identities"])) == count
        assert {item["executed_at_tick"] for item in record["receipts"]} == {
            result["resolution_tick"]
        }
        assert [item["step_index"] for item in result["selected_actions"]] == list(
            range(1, count + 1)
        )


def test_exact_deadline_and_nested_pause_resume_lifecycle(
    comprehensive_replay: replay.C8StrictReplayV1,
) -> None:
    records = comprehensive_replay.execution_evidence.to_dict()["command_records"]
    child_open = records[17]
    child_resolve = records[19]
    parent_resume = records[20]
    assert child_open["post_public_projection"]["window_depth"] == 2
    assert child_open["post_outer_state"]["virtual_time_state"]["window_stack"][
        "windows"
    ][0]["status"] == "SUSPENDED_BY_CHILD"
    assert child_resolve["post_public_projection"]["active_window_id"] == (
        records[15]["window_ref"]["window_id"]
    )
    assert parent_resume["post_public_projection"]["now_tick"] == 700
    assert parent_resume["derived_deadline"]["deadline_at"] == 700
    for record in records:
        if record["derived_deadline"] is not None:
            assert record["derived_deadline"]["deadline_at"] == record[
                "post_public_projection"
            ]["now_tick"]


def test_fresh_reexecute_twice_has_identical_semantic_proof(
    comprehensive_replay: replay.C8StrictReplayV1,
) -> None:
    first = replay.strict_reexecute_c8_replay_v1(comprehensive_replay)
    second = replay.strict_reexecute_c8_replay_v1(
        comprehensive_replay.to_json_bytes()
    )
    assert first.to_dict() == second.to_dict()


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("schema", "sgs-c8-strict-replay-legacy"),
        ("replay_version", 2),
        ("replay_id", "unknown-replay"),
        ("scope_marker", "TIMED_8P_FULL_GAME"),
        ("production_adapter_integration", "PROVEN"),
        ("full_game", "PROVEN"),
        ("recording_scope", "FAILED_RESULTS_TRUSTED"),
        ("c8_d_contract_identity", "f" * 64),
        ("c8_d_development_identity", "e" * 64),
        ("c8_d_current_implementation_identity", "d" * 64),
    ],
)
def test_top_level_schema_scope_and_d_latches_fail_closed(
    simple_replay: replay.C8StrictReplayV1,
    field: str,
    replacement: object,
) -> None:
    with pytest.raises(replay.C8ReplayError):
        replay.C8StrictReplayV1.from_dict(
            _mutated(simple_replay, (field,), replacement)
        )


@pytest.mark.parametrize(
    "field",
    [
        "c8_a_contract_identity",
        "c8_a_development_identity",
        "c8_a_source_sha256",
        "c8_a_test_sha256",
        "clock_domain_identity",
        "duration_profile_identity",
        "fallback_registry_identity",
        "public_ordering_contract_id",
        "same_tick_chain_contract_identity",
        "same_tick_chain_max_steps",
        "bridge_frozen_identity",
        "c8_b_runtime_contract_identity",
        "c8_b_current_contract_latch_identity",
        "c8_b_development_identity",
        "c8_b_source_sha256",
        "c8_b_test_sha256",
        "c8_c_controller_id",
        "c8_c_contract_identity",
        "c8_c_development_identity",
        "c8_c_source_sha256",
        "c8_c_test_sha256",
    ],
)
def test_every_a_b_c_profile_policy_ordering_cap_latch_is_exact(
    simple_replay: replay.C8StrictReplayV1, field: str
) -> None:
    current = simple_replay.to_dict()["current_contract_latch"][field]
    replacement: object = current + 1 if type(current) is int else "f" * 64
    if field in {"public_ordering_contract_id", "c8_c_controller_id"}:
        replacement = "unknown-current-contract"
    with pytest.raises(replay.C8ReplayError):
        replay.C8StrictReplayV1.from_dict(
            _mutated(simple_replay, ("current_contract_latch", field), replacement)
        )


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        (lambda data: data.pop("full_game"), replay.C8ReplayError),
        (lambda data: data.__setitem__("unknown", True), replay.C8ReplayError),
        (lambda data: data.__setitem__("replay_version", True), replay.C8ReplayError),
        (
            lambda data: data["commands"][0].__setitem__("authority", "forged"),
            replay.C8ReplayError,
        ),
        (
            lambda data: data["execution_evidence"]["command_records"][2][
                "callback_guards"
            ][0].__setitem__("live_token", "forged"),
            replay.C8ReplayError,
        ),
    ],
)
def test_missing_extra_type_drift_and_deep_unknown_fields_fail_closed(
    simple_replay: replay.C8StrictReplayV1,
    mutation: Callable[[dict[str, Any]], object],
    expected: type[Exception],
) -> None:
    data = deepcopy(simple_replay.to_dict())
    mutation(data)
    with pytest.raises(expected):
        replay.C8StrictReplayV1.from_dict(data)


@pytest.mark.parametrize(
    ("path", "replacement"),
    [
        (("execution_evidence", "initial_outer_state", "virtual_time_state", "now_tick"), 1),
        (("execution_evidence", "command_records", 0, "window_ref", "window_id"), "forged-window"),
        (("execution_evidence", "command_records", 1, "advance_input", "input_seq"), 9),
        (("execution_evidence", "command_records", 1, "advance_input", "source_id"), "forged-source"),
        (("execution_evidence", "command_records", 1, "advance_input", "domain_id"), "forged-domain"),
        (("execution_evidence", "command_records", 1, "pre_outer_state", "input_chain_tip"), "3" * 64),
        (("execution_evidence", "command_records", 1, "derived_deadline", "deadline_at"), 99),
        (("execution_evidence", "command_records", 2, "timeout_due_commitments", 0, "now_tick"), 99),
        (("execution_evidence", "command_records", 2, "bound_legal_sets", 0, "legal_set_identity"), "f" * 64),
        (("execution_evidence", "command_records", 2, "legal_snapshots", 0, "canonical_public_ordering_identity"), "e" * 64),
        (("execution_evidence", "command_records", 2, "legal_snapshots", 0, "public_legal_set", "actions", 0, "public_ordinal"), 7),
        (("execution_evidence", "command_records", 2, "issuances", 0, "signed_action_id"), "forged-signed-action"),
        (("execution_evidence", "command_records", 2, "issuances", 0, "external_capability_identity"), "d" * 64),
        (("execution_evidence", "command_records", 2, "issuances", 0, "session_identity"), "2" * 64),
        (("execution_evidence", "command_records", 2, "capability_transitions", 0, "ownership_status_lineage"), ["CONTROLLER_ABORTED"]),
        (("execution_evidence", "command_records", 2, "receipts", 0, "window_id"), "cross-window"),
        (("execution_evidence", "command_records", 2, "receipts", 0, "runtime_instance_identity"), "c" * 64),
        (("execution_evidence", "command_records", 2, "receipts", 0, "timeout_due_commitment_identity"), "b" * 64),
        (("execution_evidence", "command_records", 2, "receipts", 0, "pre_inner_public_state_identity"), "a" * 64),
        (("execution_evidence", "command_records", 2, "receipts", 0, "authorization_ledger_after_identity"), "9" * 64),
        (("execution_evidence", "command_records", 2, "receipts", 0, "previous_receipt_identity"), "8" * 64),
        (("execution_evidence", "command_records", 2, "controller_result", "result_kind"), "TIMEOUT_UNRESOLVED"),
        (("execution_evidence", "command_records", 2, "controller_events", 0, "outcome"), "FORGED"),
        (("execution_evidence", "command_records", 2, "post_security_audit", "operation_attempt_epoch"), 0),
        (("execution_evidence", "command_records", 2, "post_security_audit", "operation_attempt_chain_tip"), "7" * 64),
        (("execution_evidence", "command_records", 2, "callback_guards", 0, "callback_completed"), False),
        (("execution_evidence", "command_records", 2, "callback_guards", 1, "guard_result_identity"), "6" * 64),
        (("execution_evidence", "final_outer_state", "inner_public_state_identity"), "5" * 64),
        (("public_projection", "final_public_projection", "projection_identity"), "4" * 64),
    ],
)
def test_representative_authority_tamper_families_fail_closed(
    simple_replay: replay.C8StrictReplayV1,
    path: tuple[Any, ...],
    replacement: object,
) -> None:
    with pytest.raises((replay.C8ReplayError, ValueError, TypeError)):
        replay.C8StrictReplayV1.from_dict(
            _mutated(simple_replay, path, replacement)
        )


@pytest.mark.parametrize("operation", ["reverse", "duplicate", "delete"])
def test_controller_event_reorder_duplicate_delete_rejected(
    simple_replay: replay.C8StrictReplayV1, operation: str
) -> None:
    data = deepcopy(simple_replay.to_dict())
    events = data["execution_evidence"]["command_records"][2]["controller_events"]
    if operation == "reverse":
        events.reverse()
    elif operation == "duplicate":
        events.append(deepcopy(events[-1]))
    else:
        events.pop(0)
    with pytest.raises((replay.C8ReplayError, ValueError, TypeError)):
        replay.C8StrictReplayV1.from_dict(data)


@pytest.mark.parametrize("operation", ["reverse", "duplicate", "delete"])
def test_command_record_reorder_duplicate_delete_rejected(
    simple_replay: replay.C8StrictReplayV1, operation: str
) -> None:
    data = deepcopy(simple_replay.to_dict())
    records = data["execution_evidence"]["command_records"]
    if operation == "reverse":
        records.reverse()
    elif operation == "duplicate":
        records.append(deepcopy(records[-1]))
    else:
        records.pop(1)
    with pytest.raises((replay.C8ReplayError, ValueError, TypeError)):
        replay.C8StrictReplayV1.from_dict(data)


def test_same_tick_step_and_chain_cap_tamper_rejected(
    comprehensive_replay: replay.C8StrictReplayV1,
) -> None:
    data = _mutated(
        comprehensive_replay,
        (
            "execution_evidence",
            "command_records",
            14,
            "controller_result",
            "selected_actions",
            1,
            "step_index",
        ),
        8,
    )
    with pytest.raises((replay.C8ReplayError, ValueError, TypeError)):
        replay.C8StrictReplayV1.from_dict(data)


def test_nested_parent_pause_resume_lineage_tamper_rejected(
    comprehensive_replay: replay.C8StrictReplayV1,
) -> None:
    data = _mutated(
        comprehensive_replay,
        (
            "execution_evidence",
            "command_records",
            17,
            "post_outer_state",
            "virtual_time_state",
            "window_stack",
            "windows",
            0,
            "remaining_ticks",
        ),
        79,
    )
    with pytest.raises((replay.C8ReplayError, ValueError, TypeError)):
        replay.C8StrictReplayV1.from_dict(data)

    parent_data = _mutated(
        comprehensive_replay,
        (
            "execution_evidence",
            "command_records",
            17,
            "post_outer_state",
            "virtual_time_state",
            "window_stack",
            "windows",
            1,
            "parent_window_id",
        ),
        "forged-parent",
    )
    with pytest.raises((replay.C8ReplayError, ValueError, TypeError)):
        replay.C8StrictReplayV1.from_dict(parent_data)


def test_runtime_event_chain_reorder_is_rejected(
    simple_replay: replay.C8StrictReplayV1,
) -> None:
    data = deepcopy(simple_replay.to_dict())
    events = data["execution_evidence"]["final_outer_state"]["runtime_events"]
    events[-2:] = reversed(events[-2:])
    with pytest.raises((replay.C8ReplayError, ValueError, TypeError)):
        replay.C8StrictReplayV1.from_dict(data)


def test_sibling_replay_record_splice_rejected(
    simple_replay: replay.C8StrictReplayV1,
) -> None:
    from scripts.sgs_engine import c8_timed_replay_version_compatibility_v1 as compatibility
    if compatibility.active_v1():
        sibling = replay.C8StrictReplayV1.from_json_bytes(compatibility.d_original_artifacts_v1()["sibling"]["raw_utf8"].encode("utf-8"))
    else:
        sibling = replay.record_c8_timed_session_trace_v1(
            initial_material=replay.C8ReplayInitialMaterialV1.build("sibling"),
            commands=_simple_commands(),
        )
    data = deepcopy(simple_replay.to_dict())
    data["execution_evidence"]["command_records"][1] = deepcopy(
        sibling.to_dict()["execution_evidence"]["command_records"][1]
    )
    with pytest.raises((replay.C8ReplayError, ValueError, TypeError)):
        replay.C8StrictReplayV1.from_dict(data)


def test_deep_initial_material_tamper_with_outer_rehash_semantically_rejected(
    simple_replay: replay.C8StrictReplayV1,
) -> None:
    data = deepcopy(simple_replay.to_dict())
    data["initial_material"] = replay.C8ReplayInitialMaterialV1.build(
        "different-fresh-runtime"
    ).to_dict()
    rehashed = replay.recompute_c8_replay_outer_identities_v1(data)
    parsed = replay.C8StrictReplayV1.from_dict(rehashed)
    with pytest.raises(replay.C8ReplayDivergenceError):
        replay.strict_reexecute_c8_replay_v1(parsed)


def test_deep_command_tamper_with_outer_rehash_semantically_rejected(
    simple_replay: replay.C8StrictReplayV1,
) -> None:
    data = deepcopy(simple_replay.to_dict())
    command = data["commands"][1]
    command["requested_tick"] = 99
    command["command_identity"] = replay.c8_replay_identity_v1(
        {key: value for key, value in command.items() if key != "command_identity"}
    )
    data["execution_evidence"]["command_records"][1]["command_identity"] = (
        command["command_identity"]
    )
    data["public_projection"]["command_records"][1]["command_identity"] = (
        command["command_identity"]
    )
    rehashed = replay.recompute_c8_replay_outer_identities_v1(data)
    parsed = replay.C8StrictReplayV1.from_dict(rehashed)
    with pytest.raises(replay.C8ReplayDivergenceError):
        replay.strict_reexecute_c8_replay_v1(parsed)


def test_live_leases_guards_and_capabilities_have_no_from_dict_authority() -> None:
    assert not hasattr(rt.ControllerCallbackLeaseV1, "from_dict")
    assert not hasattr(rt.ControllerCallbackGuardTokenV1, "from_dict")
    assert not hasattr(rt.PendingTimeoutIssuanceCapabilityV1, "from_dict")


def test_serialized_receipt_is_evidence_not_fresh_runtime_authority(
    simple_replay: replay.C8StrictReplayV1,
) -> None:
    receipt_dict = simple_replay.execution_evidence.to_dict()["command_records"][2][
        "receipts"
    ][0]
    receipt = rt.TimeoutActionExecutionReceiptV1.from_dict(receipt_dict)
    initial = replay.C8ReplayInitialMaterialV1.build("receipt-authority-probe")
    execution = replay._ReplayExecution(initial)
    execution.run(_simple_commands()[:2])
    ref = execution.refs["play"]
    with pytest.raises(rt.C8TimedSessionRuntimeError):
        execution.runtime.close_window_by_timeout_receipt_v1(
            ref, execution_receipt=receipt
        )


def test_serialized_issuance_cannot_smuggle_external_live_capability(
    simple_replay: replay.C8StrictReplayV1,
) -> None:
    data = deepcopy(simple_replay.to_dict())
    data["execution_evidence"]["command_records"][2]["issuances"][0][
        "external_capability"
    ] = "serialized-live-token"
    with pytest.raises(replay.C8ReplayError):
        replay.C8StrictReplayV1.from_dict(data)


def test_public_projection_has_no_private_or_authority_leakage(
    comprehensive_replay: replay.C8StrictReplayV1,
) -> None:
    public_blob = json.dumps(
        comprehensive_replay.to_public_dict_v1(), sort_keys=True
    ).lower()
    for forbidden in (
        "authoritative_state",
        "authorization_evidence",
        "external_capability",
        "capability_identity",
        "opaque_inner",
        "private_card",
        "private_choice",
        "secret_counter",
    ):
        assert forbidden not in public_blob
    assert "public_legal_sets" in public_blob
    assert "receipt_identity" in public_blob


def test_module_has_no_wall_clock_or_rng_semantic_dependency() -> None:
    source = inspect.getsource(replay)
    forbidden = ("import random", "import secrets", "import time", "uuid4(", "time.time(")
    assert not any(item in source for item in forbidden)
    assert "DETERMINISTIC_PUBLIC_SYNTHETIC_SCRIPT_V1" in source


def test_scope_markers_cannot_be_misread_as_timed_8p_or_full_game(
    comprehensive_replay: replay.C8StrictReplayV1,
) -> None:
    public = comprehensive_replay.to_public_dict_v1()
    assert public["scope_marker"] == "GENERIC_TIMED_SESSION_CONTROLLER_TRACE_ONLY"
    assert public["production_adapter_integration"] == "NOT_PROVEN"
    assert public["full_game"] == "NOT_PROVEN"
    assert "eight_player" not in json.dumps(public).lower()


def test_a_b_c_dependency_hashes_are_current_and_bound() -> None:
    latch = replay.C8DCurrentContractLatchV1.canonical()
    assert latch.c8_a_source_sha256 == replay.C8_A_SOURCE_SHA256
    assert latch.c8_a_test_sha256 == replay.C8_A_TEST_SHA256
    assert latch.c8_b_source_sha256 == replay.C8_B_SOURCE_SHA256
    assert latch.c8_b_test_sha256 == replay.C8_B_TEST_SHA256
    assert latch.c8_c_source_sha256 == replay.C8_C_SOURCE_SHA256
    assert latch.c8_c_test_sha256 == replay.C8_C_TEST_SHA256


def test_only_dedicated_c8_d_files_are_expected_new_artifacts() -> None:
    path = Path(replay.__file__).resolve()
    assert path.name == "c8_strict_replay_v1.py"
    assert Path(__file__).name == "test_c8_strict_replay_v1.py"
