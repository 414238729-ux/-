# -*- coding: utf-8 -*-
"""Dedicated cheap tests for C8-B; no gameplay or timeout controller runs."""

from __future__ import annotations

import ast
import copy
import hashlib
import inspect
import json
from dataclasses import replace
from typing import Any

import pytest

from scripts.sgs_engine import c8_timed_session_runtime_v1 as rt
from scripts.sgs_engine import c8_virtual_time_contract_v1 as c8


def _sha(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


NONCE_ID = _sha("c8-b-test-runtime-nonce")
DRIVER_AUTHORITY_ID = _sha("c8-b-test-driver-authority")
CONTROLLER_ID = _sha("c8-c-test-controller")
CONTROLLER_ADAPTER_ID = _sha("c8-c-test-adapter")
PROFILE_ID = c8.ENGINEERING_TEST_PROFILE_V1.profile_identity


class FakeInnerAdapter:
    """Small opaque-state adapter; intentionally exposes no gameplay operations."""

    def __init__(self, *, label: str = "primary") -> None:
        self._adapter_identity = _sha(f"adapter:{label}")
        self._session_binding_identity = _sha(f"session:{label}")
        self.public_counter = 0
        self.secret_counter = 0
        self.inner_events: list[str] = []
        self.calls: list[str] = []
        self.corrupt_next_restore = False
        self.restore_faults: list[str] = []
        self.private_payload_calls = 0
        self.reentrant_call: Any = None
        self.apply_reentrant_call: Any = None
        self.apply_result: object = None
        self.apply_raises = False
        self.apply_post_fault: str | None = None
        self.restore_raises = False
        self.shared_authenticator: Any = None
        self.opaque_token_secret = f"OPAQUE-INNER-TOKEN:{label}:DO-NOT-REPR"

    def adapter_identity_v1(self) -> str:
        self.calls.append("adapter_identity_v1")
        return self._adapter_identity

    def session_binding_identity_v1(self) -> str:
        self.calls.append("session_binding_identity_v1")
        return self._session_binding_identity

    def public_state_identity_v1(self) -> str:
        self.calls.append("public_state_identity_v1")
        return _sha(f"public:{self.public_counter}")

    def authoritative_state_identity_v1(self) -> str:
        self.calls.append("authoritative_state_identity_v1")
        return _sha(f"authoritative:{self.public_counter}:{self.secret_counter}")

    def capture_transaction_snapshot_v1(self) -> object:
        self.calls.append("capture_transaction_snapshot_v1")
        if self.reentrant_call is not None:
            self.reentrant_call()
        shared_ledger = (
            None
            if self.shared_authenticator is None
            else self.shared_authenticator.shared_anti_replay_snapshot()
        )
        return (
            self.public_counter,
            self.secret_counter,
            tuple(self.inner_events),
            self._adapter_identity,
            self._session_binding_identity,
            self.opaque_token_secret,
            shared_ledger,
        )

    def snapshot_token_identity_v1(self, token: object) -> str:
        self.calls.append("snapshot_token_identity_v1")
        return _sha(json.dumps(token, ensure_ascii=False, separators=(",", ":")))

    def restore_transaction_snapshot_v1(self, token: object) -> None:
        self.calls.append("restore_transaction_snapshot_v1")
        if self.restore_raises:
            raise RuntimeError("fake inner restore failure")
        (
            public,
            secret,
            events,
            adapter_identity,
            session_identity,
            opaque_token_secret,
            shared_ledger,
        ) = token  # type: ignore[misc]
        self.public_counter = public
        self.secret_counter = secret
        self.inner_events = list(events)
        self._adapter_identity = adapter_identity
        self._session_binding_identity = session_identity
        if opaque_token_secret != self.opaque_token_secret:
            raise RuntimeError("opaque inner token owner mismatch")
        if self.shared_authenticator is not None and shared_ledger is not None:
            self.shared_authenticator.restore_shared_anti_replay_snapshot(shared_ledger)
        if self.corrupt_next_restore:
            self.corrupt_next_restore = False
            self.public_counter += 1
        if self.restore_faults:
            fault = self.restore_faults.pop(0)
            if fault == "adapter":
                self._adapter_identity = _sha("restore-fault:adapter")
            elif fault == "session":
                self._session_binding_identity = _sha("restore-fault:session")
            elif fault == "public":
                self.public_counter += 1
            elif fault == "authoritative":
                self.secret_counter += 1
            else:  # pragma: no cover - test helper misuse
                raise AssertionError(f"unknown restore fault: {fault}")

    def apply_signed_action_id_v1(self, signed_action_id: str) -> None:
        self.calls.append(f"apply_signed_action_id_v1:{signed_action_id}")
        if self.apply_reentrant_call is not None:
            self.apply_reentrant_call()
        if self.apply_raises:
            raise RuntimeError("fake inner action failure")
        self.public_counter += 1
        self.secret_counter += 1
        self.inner_events.append(f"signed-action:{signed_action_id}")
        if self.apply_post_fault == "adapter":
            self._adapter_identity = _sha("post-apply-fault:adapter")
        elif self.apply_post_fault == "session":
            self._session_binding_identity = _sha("post-apply-fault:session")
        elif self.apply_post_fault == "public":
            self.public_counter += 1
        elif self.apply_post_fault == "authoritative":
            self.secret_counter -= 1
        return self.apply_result  # type: ignore[return-value]

    def private_payload_v1(self) -> dict[str, int]:
        """A forbidden surface which the timed wrapper must never discover/call."""

        self.private_payload_calls += 1
        return {"secret_counter": self.secret_counter}

    def mutate_outside_wrapper(self, *, public_delta: int, secret_delta: int) -> None:
        self.public_counter += public_delta
        self.secret_counter += secret_delta
        self.inner_events.append("inner-mutation")


class FakeAuthenticator:
    """External one-shot authority; authorization state is never wrapper-rolled back."""

    def __init__(self, *, label: str = "primary") -> None:
        self._identity = _sha(f"authenticator:{label}")
        self._next_authorization = 0
        self._authorized: dict[str, str] = {}
        self.consumed_evidence: set[str] = set()
        self._consumed_epoch = 0
        self.calls: list[str] = []
        self.reentrant_call: Any = None

    def authenticator_identity_v1(self) -> str:
        self.calls.append("authenticator_identity_v1")
        return self._identity

    def anti_replay_state_identity_v1(self) -> str:
        self.calls.append("anti_replay_state_identity_v1")
        material = json.dumps(
            {
                "consumed_epoch": self._consumed_epoch,
                "consumed_evidence": sorted(self.consumed_evidence),
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return _sha(material)

    def authorize(self, request_binding_identity: str) -> str:
        evidence = _sha(
            f"opaque-auth:{self._identity}:{self._next_authorization}:"
            f"{request_binding_identity}"
        )
        self._next_authorization += 1
        self._authorized[evidence] = request_binding_identity
        return evidence

    def verify_and_consume_advance_authorization_v1(
        self,
        advance_input: c8.VirtualTimeAdvanceInputV1,
        expected_request_binding_identity: str,
    ) -> bool:
        self.calls.append("verify_and_consume_advance_authorization_v1")
        if self.reentrant_call is not None:
            self.reentrant_call()
        evidence = advance_input.authentication_evidence_identity
        authorized_binding = self._authorized.pop(evidence, None)
        if authorized_binding is None:
            return False
        self.consumed_evidence.add(evidence)
        self._consumed_epoch += 1
        return authorized_binding == expected_request_binding_identity

    def verify_and_consume_timeout_action_authorization_v1(
        self,
        signed_action_id: str,
        authorization_evidence_identity: str,
        expected_request_binding_identity: str,
    ) -> bool:
        self.calls.append(
            f"verify_and_consume_timeout_action_authorization_v1:{signed_action_id}"
        )
        if self.reentrant_call is not None:
            self.reentrant_call()
        authorized_binding = self._authorized.pop(
            authorization_evidence_identity, None
        )
        if authorized_binding is None:
            return False
        self.consumed_evidence.add(authorization_evidence_identity)
        self._consumed_epoch += 1
        return authorized_binding == expected_request_binding_identity

    def shared_anti_replay_snapshot(self) -> tuple[int, tuple[str, ...]]:
        return self._consumed_epoch, tuple(sorted(self.consumed_evidence))

    def restore_shared_anti_replay_snapshot(
        self, snapshot: tuple[int, tuple[str, ...]]
    ) -> None:
        epoch, consumed = snapshot
        self._consumed_epoch = epoch
        self.consumed_evidence = set(consumed)


_AUTHENTICATORS: dict[rt.C8TimedSessionRuntimeV1, FakeAuthenticator] = {}


def _runtime(
    adapter: FakeInnerAdapter | None = None,
    *,
    nonce_identity: str = NONCE_ID,
    authenticator: FakeAuthenticator | None = None,
    share_auth_ledger_with_adapter_snapshot: bool = False,
) -> tuple[rt.C8TimedSessionRuntimeV1, FakeInnerAdapter]:
    bound = FakeInnerAdapter() if adapter is None else adapter
    input_authenticator = (
        FakeAuthenticator() if authenticator is None else authenticator
    )
    if share_auth_ledger_with_adapter_snapshot:
        bound.shared_authenticator = input_authenticator
    runtime = rt.C8TimedSessionRuntimeV1(
        inner_adapter=bound,
        input_authenticator=input_authenticator,
        instance_nonce_identity=nonce_identity,
        input_source_id="authenticated-test-driver",
        driver_authority_identity=DRIVER_AUTHORITY_ID,
    )
    _AUTHENTICATORS[runtime] = input_authenticator
    return runtime, bound


def _open(
    runtime: rt.C8TimedSessionRuntimeV1,
    *,
    label: str = "root",
    kind: c8.TimedWindowKindV1 = c8.TimedWindowKindV1.PLAY,
    parent: rt.WindowAuthorityRefV1 | None = None,
    actor: str = "p1",
    obligation_identity: str | None = None,
) -> rt.WindowAuthorityRefV1:
    return runtime.open_window(
        actor_id=actor,
        window_kind=kind,
        decision_identity=_sha(f"decision:{label}"),
        obligation_identity=(
            _sha(f"obligation:{label}")
            if obligation_identity is None
            else obligation_identity
        ),
        expected_parent_ref=parent,
    )


def _advance(
    runtime: rt.C8TimedSessionRuntimeV1, requested_tick: int
) -> rt.TimedRuntimeAdvanceResultV1:
    prior_tip = runtime.state.input_chain_tip
    advance_input = _authorized_input(runtime, requested_tick=requested_tick)
    return runtime.ingest_virtual_time_input(
        advance_input,
        expected_previous_input_chain_tip=prior_tip,
        duration_profile_identity=PROFILE_ID,
    )


def _authorized_input(
    runtime: rt.C8TimedSessionRuntimeV1,
    *,
    requested_tick: int,
    input_seq: int | None = None,
    source_id: str | None = None,
    window_id: str | None = None,
) -> c8.VirtualTimeAdvanceInputV1:
    state = runtime.state
    active = state.virtual_time_state.window_stack.active_window
    assert active is not None
    seq = state.virtual_time_state.next_input_seq if input_seq is None else input_seq
    source = state.input_source_id if source_id is None else source_id
    window = active.window_id if window_id is None else window_id
    if (
        seq == state.virtual_time_state.next_input_seq
        and source == state.input_source_id
        and window == active.window_id
        and requested_tick >= state.virtual_time_state.now_tick
    ):
        binding = runtime.expected_advance_authentication_binding(
            requested_tick=requested_tick
        )
        evidence = _AUTHENTICATORS[runtime].authorize(binding)
    else:
        # These malformed cases must fail before invoking the authenticator.
        evidence = _sha(
            f"untrusted:{seq}:{source}:{window}:{requested_tick}:"
            f"{state.input_chain_tip}"
        )
    return c8.VirtualTimeAdvanceInputV1.issue(
        input_seq=seq,
        source_id=source,
        domain_id=c8.CLOCK_DOMAIN_ID,
        window_id=window,
        requested_tick=requested_tick,
        authentication_evidence_identity=evidence,
    )


def _ingest(
    runtime: rt.C8TimedSessionRuntimeV1,
    value: object,
    *,
    chain_tip: str | None = None,
    profile_identity: str = PROFILE_ID,
) -> rt.TimedRuntimeAdvanceResultV1:
    return runtime.ingest_virtual_time_input(  # type: ignore[arg-type]
        value,
        expected_previous_input_chain_tip=(
            runtime.state.input_chain_tip if chain_tip is None else chain_tip
        ),
        duration_profile_identity=profile_identity,
    )


def _timeout_authorization_evidence(
    runtime: rt.C8TimedSessionRuntimeV1,
    ref: rt.WindowAuthorityRefV1,
    timeout_due_commitment: rt.TimeoutDueCommitmentV1,
    *,
    signed_action_id: str,
) -> str:
    binding = runtime.expected_timeout_action_authentication_binding_v1(
        ref,
        timeout_due_commitment=timeout_due_commitment,
        signed_action_id=signed_action_id,
    )
    return _AUTHENTICATORS[runtime].authorize(binding)


def _forward_timeout(
    runtime: rt.C8TimedSessionRuntimeV1,
    ref: rt.WindowAuthorityRefV1,
    *,
    signed_action_id: str = "timeout-signed-action-001",
    timeout_due_commitment: rt.TimeoutDueCommitmentV1 | None = None,
) -> rt.TimeoutActionExecutionReceiptV1:
    commitment = (
        runtime.current_timeout_due_commitment_v1(ref)
        if timeout_due_commitment is None
        else timeout_due_commitment
    )
    evidence = _timeout_authorization_evidence(
        runtime,
        ref,
        commitment,
        signed_action_id=signed_action_id,
    )
    return runtime.forward_timeout_due_signed_action_id_v1(
        ref,
        timeout_due_commitment=commitment,
        signed_action_id=signed_action_id,
        authorization_evidence_identity=evidence,
    )


def _controller_callback_lease(
    runtime: rt.C8TimedSessionRuntimeV1,
    ref: rt.WindowAuthorityRefV1,
    commitment: rt.TimeoutDueCommitmentV1,
) -> rt.ControllerCallbackLeaseV1:
    return runtime.issue_controller_callback_lease_v1(
        ref,
        timeout_due_commitment=commitment,
        controller_identity=CONTROLLER_ID,
        adapter_identity=CONTROLLER_ADAPTER_ID,
    )


def _due_runtime(
    *,
    kind: c8.TimedWindowKindV1 = c8.TimedWindowKindV1.PLAY,
) -> tuple[
    rt.C8TimedSessionRuntimeV1,
    FakeInnerAdapter,
    rt.WindowAuthorityRefV1,
    rt.TimeoutDueCommitmentV1,
]:
    runtime, adapter = _runtime()
    ref = _open(runtime, kind=kind)
    _advance(runtime, 100)
    commitment = runtime.current_timeout_due_commitment_v1(ref)
    return runtime, adapter, ref, commitment


def _successful_controller_guard_result(
    runtime: rt.C8TimedSessionRuntimeV1,
    ref: rt.WindowAuthorityRefV1,
    commitment: rt.TimeoutDueCommitmentV1,
) -> rt.ControllerCallbackGuardResultV1:
    lease = _controller_callback_lease(runtime, ref, commitment)
    invocation = runtime.invoke_controller_callback_guarded_v1(
        lease,
        lambda: {"public_legal_set_identity": _sha("legal-set")},
    )
    assert type(invocation) is rt.ControllerCallbackInvocationResultV1
    return invocation.guard_result


def _pending_issuance_capability(
    runtime: rt.C8TimedSessionRuntimeV1,
    ref: rt.WindowAuthorityRefV1,
    commitment: rt.TimeoutDueCommitmentV1,
    *,
    signed_action_id: str,
) -> rt.PendingTimeoutIssuanceCapabilityV1:
    guard_result = _successful_controller_guard_result(
        runtime, ref, commitment
    )
    return runtime.register_pending_timeout_issuance_capability_v1(
        ref,
        timeout_due_commitment=commitment,
        guard_result=guard_result,
        signed_action_id=signed_action_id,
        external_capability_identity=_sha(
            f"external-issuance-capability:{signed_action_id}"
        ),
    )


def _unsafe_ref_with(
    ref: rt.WindowAuthorityRefV1, **changes: object
) -> rt.WindowAuthorityRefV1:
    material: dict[str, Any] = {
        "runtime_instance_identity": ref.runtime_instance_identity,
        "window_id": ref.window_id,
        "parent_window_id": ref.parent_window_id,
        "actor_id": ref.actor_id,
        "window_kind": ref.window_kind,
        "decision_identity": ref.decision_identity,
        "obligation_identity": ref.obligation_identity,
        "window_binding_identity": ref.window_binding_identity,
    }
    material.update(changes)
    return rt.WindowAuthorityRefV1.issue(**material)


def test_initial_state_has_single_authority_empty_clock_and_public_projection() -> None:
    runtime, adapter = _runtime()
    state = runtime.state

    assert state.runtime_id == rt.C8_B_RUNTIME_ID
    assert state.contract_latch == rt.C8_B_CURRENT_CONTRACT_LATCH_V1
    assert state.virtual_time_state.now_tick == 0
    assert state.virtual_time_state.next_input_seq == 0
    assert state.virtual_time_state.next_window_seq == 0
    assert state.virtual_time_state.window_stack.windows == ()
    assert state.input_records == ()
    assert state.logical_obligations == ()
    assert state.pending_deadline is None
    assert state.runtime_events == ()
    assert runtime.active_window_ref() is None

    projection = runtime.public_projection()
    assert projection.now_tick == 0
    assert projection.window_depth == 0
    assert projection.active_window_id is None
    assert projection.action_eligibility is None
    assert projection.inner_public_state_identity == adapter.public_state_identity_v1()


def test_open_window_creates_deterministic_deadline_and_separate_outer_event() -> None:
    runtime, adapter = _runtime()
    ref = _open(runtime)
    active = runtime.state.virtual_time_state.window_stack.active_window
    assert active is not None

    assert active.opened_at == 0
    assert active.deadline_at == 100
    assert active.budget_ticks == 100
    assert active.remaining_ticks == 100
    assert active.status is c8.TimedWindowStatusV1.ACTIVE
    assert ref == runtime.active_window_ref()
    assert [event.event_kind for event in runtime.state.runtime_events] == [
        rt.RuntimeEventKindV1.WINDOW_OPENED
    ]
    assert adapter.inner_events == []

    other, _ = _runtime(FakeInnerAdapter(), nonce_identity=NONCE_ID)
    other_ref = _open(other)
    other_active = other.state.virtual_time_state.window_stack.active_window
    assert other_active is not None
    assert other_active.to_dict() == active.to_dict()
    assert other_ref.authority_ref_identity == ref.authority_ref_identity


def test_monotonic_strictly_sequenced_inputs_are_accepted_and_chained() -> None:
    runtime, _ = _runtime()
    _open(runtime)

    first = _advance(runtime, 10)
    first_tip = runtime.state.input_chain_tip
    second = _advance(runtime, 25)

    assert (first.applied_tick, first.consumed_ticks) == (10, 10)
    assert (second.applied_tick, second.consumed_ticks) == (25, 15)
    assert runtime.state.virtual_time_state.next_input_seq == 2
    assert [record.input_seq for record in runtime.state.input_records] == [0, 1]
    assert runtime.state.input_records[1].previous_input_chain_tip == first_tip
    assert runtime.state.input_chain_tip == runtime.state.input_records[-1].input_chain_link_identity


def test_duplicate_reordered_and_backward_inputs_fail_closed() -> None:
    runtime, _ = _runtime()
    _open(runtime)
    stale_tip = runtime.state.input_chain_tip
    first_input = _authorized_input(runtime, requested_tick=10)
    _ingest(runtime, first_input, chain_tip=stale_tip)

    before = runtime.state
    with pytest.raises(rt.C8TimedSessionRuntimeError):
        _ingest(runtime, first_input, chain_tip=stale_tip)
    assert runtime.state == before

    reordered = _authorized_input(runtime, requested_tick=20, input_seq=2)
    with pytest.raises(rt.C8TimedSessionRuntimeError):
        _ingest(runtime, reordered)
    assert runtime.state == before

    backward = _authorized_input(runtime, requested_tick=9)
    with pytest.raises(rt.C8TimedSessionRuntimeError):
        _ingest(runtime, backward)
    assert runtime.state == before

    with pytest.raises(rt.C8TimedSessionRuntimeError):
        runtime.expected_advance_authentication_binding(requested_tick=-1)
    assert runtime.state == before


def test_cross_chain_profile_source_and_runtime_inputs_fail_closed() -> None:
    runtime, _ = _runtime()
    _open(runtime)
    valid = _authorized_input(runtime, requested_tick=5)
    before = runtime.state

    with pytest.raises(rt.C8TimedSessionRuntimeError):
        _ingest(runtime, valid, chain_tip="f" * 64)
    with pytest.raises(rt.C8TimedSessionRuntimeError):
        _ingest(runtime, valid, profile_identity="e" * 64)
    wrong_source = _authorized_input(
        runtime, requested_tick=5, source_id="another-authenticated-driver"
    )
    with pytest.raises(rt.C8TimedSessionRuntimeError):
        _ingest(runtime, wrong_source)

    other, _ = _runtime(FakeInnerAdapter(label="other"), nonce_identity=_sha("other-nonce"))
    _open(other)
    other_input = _authorized_input(other, requested_tick=5)
    with pytest.raises(rt.C8TimedSessionRuntimeError):
        _ingest(runtime, other_input)
    assert runtime.state == before


def test_wrong_domain_is_rejected_at_strict_input_boundary() -> None:
    runtime, _ = _runtime()
    _open(runtime)
    valid = _authorized_input(runtime, requested_tick=5)
    raw = valid.to_dict()
    raw["domain_id"] = "foreign-clock-domain"

    with pytest.raises(c8.C8VirtualTimeContractError):
        c8.VirtualTimeAdvanceInputV1.from_dict(raw)
    with pytest.raises(rt.C8TimedSessionRuntimeError):
        _ingest(runtime, raw)


def test_tick_binding_alone_cannot_mint_authenticated_advance_input() -> None:
    runtime, _ = _runtime()
    _open(runtime)
    state = runtime.state
    binding = runtime.expected_advance_authentication_binding(requested_tick=5)
    assert len(binding) == 64
    assert not hasattr(runtime, "build_advance_input_for_authenticated_driver")
    active = state.virtual_time_state.window_stack.active_window
    assert active is not None
    unauthenticated = c8.VirtualTimeAdvanceInputV1.issue(
        input_seq=state.virtual_time_state.next_input_seq,
        source_id=state.input_source_id,
        domain_id=c8.CLOCK_DOMAIN_ID,
        window_id=active.window_id,
        requested_tick=5,
        authentication_evidence_identity=_sha("caller-self-minted-evidence"),
    )
    before = runtime.state

    with pytest.raises(rt.C8TimedSessionRuntimeError):
        _ingest(runtime, unauthenticated)
    assert runtime.state == before
    assert _AUTHENTICATORS[runtime].consumed_evidence == set()


def test_consumed_authorization_cannot_replay_after_outer_rollback() -> None:
    runtime, _ = _runtime()
    _open(runtime)
    snapshot = runtime.capture_transaction()
    authenticator = _AUTHENTICATORS[runtime]
    ledger_before_issue = authenticator.anti_replay_state_identity_v1()
    advance_input = _authorized_input(runtime, requested_tick=10)
    assert authenticator.anti_replay_state_identity_v1() == ledger_before_issue
    evidence = advance_input.authentication_evidence_identity
    _ingest(runtime, advance_input)
    ledger_after_consume = authenticator.anti_replay_state_identity_v1()
    assert ledger_after_consume != ledger_before_issue
    assert evidence in authenticator.consumed_evidence

    runtime.rollback(snapshot)
    before_replay = runtime.state
    with pytest.raises(rt.C8TimedSessionRuntimeError):
        _ingest(runtime, advance_input)
    assert runtime.state == before_replay
    assert evidence in authenticator.consumed_evidence
    assert authenticator.anti_replay_state_identity_v1() == ledger_after_consume


def test_found_authorization_is_burned_even_when_request_binding_is_wrong() -> None:
    runtime, _ = _runtime()
    _open(runtime)
    authenticator = _AUTHENTICATORS[runtime]
    state = runtime.state
    active = state.virtual_time_state.window_stack.active_window
    assert active is not None
    authorized_binding = runtime.expected_advance_authentication_binding(
        requested_tick=5
    )
    evidence = authenticator.authorize(authorized_binding)
    ledger_before = authenticator.anti_replay_state_identity_v1()
    mismatched = c8.VirtualTimeAdvanceInputV1.issue(
        input_seq=state.virtual_time_state.next_input_seq,
        source_id=state.input_source_id,
        domain_id=c8.CLOCK_DOMAIN_ID,
        window_id=active.window_id,
        requested_tick=6,
        authentication_evidence_identity=evidence,
    )
    before_outer = runtime.state

    with pytest.raises(rt.C8TimedSessionRuntimeError):
        _ingest(runtime, mismatched)

    assert runtime.state == before_outer
    assert evidence in authenticator.consumed_evidence
    assert authenticator.anti_replay_state_identity_v1() != ledger_before
    # The wrapper latched the burned ledger even though the outer transition failed.
    assert runtime.public_projection().now_tick == 0


def test_sibling_branch_snapshot_cannot_fast_forward_over_current_lineage() -> None:
    runtime, adapter = _runtime()
    ref = _open(runtime)
    base_snapshot = runtime.capture_transaction()

    runtime.forward_on_time_signed_action_id(ref, signed_action_id="branch-a-action")
    branch_a_snapshot = runtime.capture_transaction()
    branch_a_identity = branch_a_snapshot.outer_state.state_identity
    assert (
        branch_a_snapshot.outer_state.runtime_events[-1].event_kind
        is rt.RuntimeEventKindV1.INNER_SIGNED_ACTION_FORWARDED
    )

    runtime.rollback(base_snapshot)
    runtime.forward_on_time_signed_action_id(ref, signed_action_id="branch-b-action")
    branch_b_state = runtime.state
    branch_b_inner = adapter.capture_transaction_snapshot_v1()
    assert branch_b_state.state_identity != branch_a_identity
    assert (
        branch_b_state.runtime_events[-1].event_kind
        is rt.RuntimeEventKindV1.INNER_SIGNED_ACTION_FORWARDED
    )
    assert (
        branch_b_state.runtime_events[-1].inner_transition_identity
        != branch_a_snapshot.outer_state.runtime_events[-1].inner_transition_identity
    )

    with pytest.raises(rt.C8TimedSessionRuntimeError):
        runtime.rollback(branch_a_snapshot)

    assert runtime.state == branch_b_state
    assert adapter.capture_transaction_snapshot_v1() == branch_b_inner


def test_authenticator_callback_cannot_reenter_runtime() -> None:
    runtime, _ = _runtime()
    _open(runtime)
    authenticator = _AUTHENTICATORS[runtime]
    advance_input = _authorized_input(runtime, requested_tick=10)
    before = runtime.state
    authenticator.reentrant_call = runtime.public_projection

    with pytest.raises(rt.C8TimedSessionRuntimeError):
        _ingest(runtime, advance_input)
    assert runtime.state == before

    authenticator.reentrant_call = None
    result = _ingest(runtime, advance_input)
    assert result.applied_tick == 10


def test_timeout_action_authenticator_callback_cannot_reenter_runtime() -> None:
    runtime, adapter = _runtime()
    ref = _open(runtime)
    _advance(runtime, 100)
    commitment = runtime.current_timeout_due_commitment_v1(ref)
    action_id = "timeout-auth-reentrant"
    evidence = _timeout_authorization_evidence(
        runtime,
        ref,
        commitment,
        signed_action_id=action_id,
    )
    authenticator = _AUTHENTICATORS[runtime]
    authenticator.reentrant_call = runtime.public_projection
    before_outer = runtime.state
    before_inner = adapter.capture_transaction_snapshot_v1()

    with pytest.raises(rt.C8TimedSessionRuntimeError):
        runtime.forward_timeout_due_signed_action_id_v1(
            ref,
            timeout_due_commitment=commitment,
            signed_action_id=action_id,
            authorization_evidence_identity=evidence,
        )

    assert runtime.state == before_outer
    assert adapter.capture_transaction_snapshot_v1() == before_inner
    authenticator.reentrant_call = None


def test_inner_capture_callback_cannot_reenter_runtime() -> None:
    runtime, adapter = _runtime()
    _open(runtime)
    before = runtime.state
    adapter.reentrant_call = runtime.public_projection

    with pytest.raises(rt.C8TimedSessionRuntimeError):
        runtime.capture_transaction()
    assert runtime.state == before

    adapter.reentrant_call = None
    assert runtime.capture_transaction().outer_state == before


def test_exact_boundary_is_timeout_due_and_action_close_is_atomic_rejection() -> None:
    runtime, _ = _runtime()
    ref = _open(runtime)
    before_deadline = _advance(runtime, 99)
    assert before_deadline.derived_deadline is None
    assert runtime.action_eligibility(ref) is (
        c8.DeadlinePrecedenceV1.ACTION_ELIGIBLE_BEFORE_DEADLINE
    )

    at_deadline = _advance(runtime, 100)
    assert at_deadline.derived_deadline is not None
    assert runtime.state.virtual_time_state.now_tick == 100
    assert runtime.action_eligibility(ref) is (
        c8.DeadlinePrecedenceV1.TIMEOUT_PRIORITY_AT_OR_AFTER_DEADLINE
    )
    before_rejection = runtime.state
    with pytest.raises(rt.C8TimedSessionRuntimeError):
        runtime.close_window_by_action(ref)
    assert runtime.state == before_rejection

    with pytest.raises(rt.C8TimedSessionRuntimeError):
        runtime.close_window_by_timeout(ref)

    receipt = _forward_timeout(runtime, ref)
    closed = runtime.close_window_by_timeout(
        ref,
        execution_receipt=receipt,
    )
    assert closed.status is c8.TimedWindowStatusV1.CLOSED_BY_TIMEOUT
    assert runtime.active_window_ref() is None
    assert runtime.state.pending_deadline is None


def test_before_deadline_action_close_succeeds_without_timeout_policy_choice() -> None:
    runtime, _ = _runtime()
    ref = _open(runtime)
    _advance(runtime, 99)
    closed = runtime.close_window_by_action(ref)

    assert closed.status is c8.TimedWindowStatusV1.CLOSED_BY_ACTION
    assert runtime.active_window_ref() is None
    assert all(
        event.event_kind is not rt.RuntimeEventKindV1.DEADLINE_DERIVED
        for event in runtime.state.runtime_events
    )


def test_on_time_signed_action_passthrough_updates_only_inner_commitments() -> None:
    runtime, adapter = _runtime()
    ref = _open(runtime)
    _advance(runtime, 10)
    before = runtime.state

    returned_public_identity = runtime.forward_on_time_signed_action_id(
        ref, signed_action_id="signed-action-001"
    )
    after = runtime.state

    assert returned_public_identity == after.inner_public_state_identity
    assert after.inner_public_state_identity != before.inner_public_state_identity
    assert (
        after.inner_authoritative_state_identity
        != before.inner_authoritative_state_identity
    )
    assert after.virtual_time_state == before.virtual_time_state
    assert after.input_records == before.input_records
    assert after.input_chain_tip == before.input_chain_tip
    assert after.runtime_events[:-1] == before.runtime_events
    forwarded = after.runtime_events[-1]
    assert forwarded.event_kind is rt.RuntimeEventKindV1.INNER_SIGNED_ACTION_FORWARDED
    assert forwarded.inner_transition_identity is not None
    assert forwarded.before_virtual_state_identity == before.virtual_time_state.state_identity
    assert forwarded.after_virtual_state_identity == before.virtual_time_state.state_identity
    assert after.event_chain_tip == forwarded.event_identity
    assert after.event_chain_tip != before.event_chain_tip
    assert after.state_revision == before.state_revision + 1
    assert adapter.inner_events == ["signed-action:signed-action-001"]


def test_exact_deadline_rejects_signed_action_before_inner_adapter_call() -> None:
    runtime, adapter = _runtime()
    ref = _open(runtime)
    _advance(runtime, 100)
    before = runtime.state
    apply_calls_before = tuple(
        call for call in adapter.calls if call.startswith("apply_signed_action_id_v1:")
    )

    with pytest.raises(rt.C8TimedSessionRuntimeError):
        runtime.forward_on_time_signed_action_id(ref, signed_action_id="too-late")

    apply_calls_after = tuple(
        call for call in adapter.calls if call.startswith("apply_signed_action_id_v1:")
    )
    assert runtime.state == before
    assert apply_calls_after == apply_calls_before
    assert adapter.inner_events == []


@pytest.mark.parametrize("failure_mode", ["raises", "non_none", "reentrant"])
def test_failed_or_reentrant_signed_action_passthrough_restores_inner_and_outer_atomically(
    failure_mode: str,
) -> None:
    runtime, adapter = _runtime()
    ref = _open(runtime)
    before_outer = runtime.state
    before_inner = adapter.capture_transaction_snapshot_v1()
    if failure_mode == "raises":
        adapter.apply_raises = True
    elif failure_mode == "non_none":
        adapter.apply_result = "forbidden-return-value"
    else:
        adapter.apply_reentrant_call = runtime.public_projection

    with pytest.raises(rt.C8TimedSessionRuntimeError):
        runtime.forward_on_time_signed_action_id(ref, signed_action_id="rejected-action")

    assert runtime.state == before_outer
    assert adapter.capture_transaction_snapshot_v1() == before_inner
    assert runtime.public_projection().now_tick == 0


def test_timeout_forward_rejects_before_deadline_and_missing_or_forged_commitment() -> None:
    runtime, adapter = _runtime()
    ref = _open(runtime)
    before = runtime.state

    with pytest.raises(rt.C8TimedSessionRuntimeError):
        runtime.current_timeout_due_commitment_v1(ref)
    with pytest.raises(rt.C8TimedSessionRuntimeError):
        runtime.forward_timeout_due_signed_action_id_v1(
            ref,
            timeout_due_commitment=None,  # type: ignore[arg-type]
            signed_action_id="too-early",
            authorization_evidence_identity=_sha("unused-evidence"),
        )
    assert runtime.state == before
    assert adapter.inner_events == []

    _advance(runtime, 100)
    commitment = runtime.current_timeout_due_commitment_v1(ref)
    serialized_copy = rt.TimeoutDueCommitmentV1.from_dict(commitment.to_dict())
    assert serialized_copy == commitment
    assert serialized_copy is not commitment
    with pytest.raises(rt.C8TimedSessionRuntimeError):
        runtime.expected_timeout_action_authentication_binding_v1(
            ref,
            timeout_due_commitment=serialized_copy,
            signed_action_id="forged-copy-action",
        )


def test_timeout_forward_at_deadline_returns_strict_pre_post_receipt() -> None:
    runtime, adapter = _runtime()
    ref = _open(runtime)
    deadline_result = _advance(runtime, 100)
    assert deadline_result.derived_deadline is not None
    before = runtime.state
    commitment = runtime.current_timeout_due_commitment_v1(ref)
    receipt = _forward_timeout(
        runtime,
        ref,
        signed_action_id="public-signed-timeout-action",
        timeout_due_commitment=commitment,
    )
    after = runtime.state

    assert type(receipt) is rt.TimeoutActionExecutionReceiptV1
    assert receipt.accepted is True
    assert receipt.executed is True
    assert receipt.runtime_contract_identity == rt.C8_B_RUNTIME_CONTRACT_IDENTITY_V1
    assert receipt.runtime_instance_identity == before.runtime_instance_identity
    assert receipt.window_id == ref.window_id
    assert receipt.actor_id == ref.actor_id
    assert receipt.decision_identity == ref.decision_identity
    assert receipt.obligation_identity == ref.obligation_identity
    assert receipt.pre_inner_public_state_identity == before.inner_public_state_identity
    assert (
        receipt.pre_inner_authoritative_state_identity
        == before.inner_authoritative_state_identity
    )
    assert receipt.post_inner_public_state_identity == after.inner_public_state_identity
    assert (
        receipt.post_inner_authoritative_state_identity
        == after.inner_authoritative_state_identity
    )
    assert receipt.inner_adapter_identity == after.inner_adapter_identity
    assert receipt.inner_session_binding_identity == after.inner_session_binding_identity
    assert receipt.timeout_due_commitment_identity == commitment.commitment_identity
    assert receipt.pending_deadline_identity == before.pending_deadline.pending_identity
    assert (
        receipt.derived_deadline_identity
        == deadline_result.derived_deadline.event_identity
    )
    assert receipt.deadline_at == receipt.executed_at_tick == 100
    assert (
        receipt.authorization_ledger_before_identity
        != receipt.authorization_ledger_after_identity
    )
    assert after.virtual_time_state == before.virtual_time_state
    assert after.pending_deadline == before.pending_deadline
    event = after.runtime_events[-1]
    assert event.event_kind is rt.RuntimeEventKindV1.TIMEOUT_SIGNED_ACTION_FORWARDED
    assert event.execution_receipt_identity == receipt.receipt_identity
    assert event.inner_transition_identity == receipt.outer_transition_identity
    assert rt.TimeoutActionExecutionReceiptV1.from_dict(receipt.to_dict()) == receipt
    assert adapter.inner_events == ["signed-action:public-signed-timeout-action"]


def test_timeout_receipt_strict_serialization_rejects_schema_type_and_tamper() -> None:
    runtime, _ = _runtime()
    ref = _open(runtime)
    _advance(runtime, 100)
    receipt = _forward_timeout(runtime, ref)
    raw = json.loads(json.dumps(receipt.to_dict(), sort_keys=True))

    mutations: list[dict[str, Any]] = []
    missing = copy.deepcopy(raw)
    missing.pop("receipt_identity")
    mutations.append(missing)
    extra = copy.deepcopy(raw)
    extra["private_payload"] = "forbidden"
    mutations.append(extra)
    type_drift = copy.deepcopy(raw)
    type_drift["accepted"] = 1
    mutations.append(type_drift)
    for field, replacement in (
        ("runtime_instance_identity", "f" * 64),
        ("window_id", "c8w-wrong"),
        ("signed_action_id_commitment", "e" * 64),
        ("post_inner_public_state_identity", "d" * 64),
        ("post_inner_authoritative_state_identity", "c" * 64),
        ("pending_deadline_identity", "b" * 64),
        ("timeout_due_commitment_identity", "a" * 64),
    ):
        tampered = copy.deepcopy(raw)
        tampered[field] = replacement
        mutations.append(tampered)

    for mutated in mutations:
        with pytest.raises(rt.C8TimedSessionRuntimeError):
            rt.TimeoutActionExecutionReceiptV1.from_dict(mutated)


def test_timeout_receipt_is_live_one_shot_and_close_is_receipt_bound() -> None:
    runtime, _ = _runtime()
    ref = _open(runtime)
    _advance(runtime, 100)
    receipt = _forward_timeout(runtime, ref)

    with pytest.raises(rt.C8TimedSessionRuntimeError):
        runtime.close_window_by_timeout(ref)
    copied = replace(receipt)
    with pytest.raises(rt.C8TimedSessionRuntimeError):
        runtime.close_window_by_timeout(ref, execution_receipt=copied)

    closed = runtime.close_window_by_timeout_receipt_v1(
        ref, execution_receipt=receipt
    )
    assert closed.status is c8.TimedWindowStatusV1.CLOSED_BY_TIMEOUT
    assert runtime.active_window_ref() is None
    with pytest.raises(rt.C8TimedSessionRuntimeError):
        runtime.close_window_by_timeout_receipt_v1(
            ref, execution_receipt=receipt
        )


def test_timeout_receipt_wrong_runtime_action_or_current_post_state_fails_closed() -> None:
    runtime, adapter = _runtime()
    ref = _open(runtime)
    _advance(runtime, 100)
    receipt = _forward_timeout(runtime, ref)
    other, _ = _runtime(
        FakeInnerAdapter(label="other-receipt"),
        nonce_identity=_sha("other-receipt-nonce"),
    )
    other_ref = _open(other)
    _advance(other, 100)

    with pytest.raises(rt.C8TimedSessionRuntimeError):
        other.close_window_by_timeout_receipt_v1(
            other_ref, execution_receipt=receipt
        )

    original_action_commitment = receipt.signed_action_id_commitment
    object.__setattr__(receipt, "signed_action_id_commitment", "f" * 64)
    try:
        with pytest.raises(rt.C8TimedSessionRuntimeError):
            runtime.close_window_by_timeout_receipt_v1(
                ref, execution_receipt=receipt
            )
    finally:
        object.__setattr__(
            receipt, "signed_action_id_commitment", original_action_commitment
        )

    before_outer = runtime.state
    adapter.mutate_outside_wrapper(public_delta=1, secret_delta=1)
    with pytest.raises(rt.C8TimedSessionRuntimeError):
        runtime.close_window_by_timeout_receipt_v1(
            ref, execution_receipt=receipt
        )
    assert runtime.state == before_outer


@pytest.mark.parametrize(
    "failure_mode",
    ["post-binding", "receipt-construction", "outer-commit"],
)
def test_timeout_forward_post_apply_failures_restore_inner_and_outer_but_burn_auth(
    failure_mode: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, adapter = _runtime()
    ref = _open(runtime)
    _advance(runtime, 100)
    commitment = runtime.current_timeout_due_commitment_v1(ref)
    action_id = f"timeout-failure-{failure_mode}"
    evidence = _timeout_authorization_evidence(
        runtime,
        ref,
        commitment,
        signed_action_id=action_id,
    )
    authenticator = _AUTHENTICATORS[runtime]
    before_outer = runtime.state
    before_inner = adapter.capture_transaction_snapshot_v1()
    ledger_before = authenticator.anti_replay_state_identity_v1()

    if failure_mode == "post-binding":
        adapter.apply_post_fault = "session"
    elif failure_mode == "receipt-construction":
        def fail_receipt(
            self: rt.C8TimedSessionRuntimeV1, **kwargs: object
        ) -> rt.TimeoutActionExecutionReceiptV1:
            raise RuntimeError("forced receipt construction failure")

        monkeypatch.setattr(
            rt.C8TimedSessionRuntimeV1,
            "_build_timeout_execution_receipt",
            fail_receipt,
        )
    else:
        def fail_commit(
            self: rt.C8TimedSessionRuntimeV1, **kwargs: object
        ) -> rt.TimedSessionOuterStateV1:
            raise RuntimeError("forced outer commit failure")

        monkeypatch.setattr(rt.C8TimedSessionRuntimeV1, "_commit", fail_commit)

    with pytest.raises(rt.C8TimedSessionRuntimeError):
        runtime.forward_timeout_due_signed_action_id_v1(
            ref,
            timeout_due_commitment=commitment,
            signed_action_id=action_id,
            authorization_evidence_identity=evidence,
        )

    assert runtime.state == before_outer
    assert adapter.capture_transaction_snapshot_v1() == before_inner
    assert authenticator.anti_replay_state_identity_v1() != ledger_before


def test_timeout_forward_rollback_does_not_make_consumed_auth_reusable() -> None:
    runtime, adapter = _runtime()
    ref = _open(runtime)
    _advance(runtime, 100)
    commitment = runtime.current_timeout_due_commitment_v1(ref)
    action_id = "burn-on-rollback"
    evidence = _timeout_authorization_evidence(
        runtime,
        ref,
        commitment,
        signed_action_id=action_id,
    )
    adapter.apply_raises = True
    before = runtime.state
    with pytest.raises(rt.C8TimedSessionRuntimeError):
        runtime.forward_timeout_due_signed_action_id_v1(
            ref,
            timeout_due_commitment=commitment,
            signed_action_id=action_id,
            authorization_evidence_identity=evidence,
        )
    assert runtime.state == before
    adapter.apply_raises = False
    apply_calls_before_replay = sum(
        call.startswith("apply_signed_action_id_v1:") for call in adapter.calls
    )
    with pytest.raises(rt.C8TimedSessionRuntimeError):
        runtime.forward_timeout_due_signed_action_id_v1(
            ref,
            timeout_due_commitment=commitment,
            signed_action_id=action_id,
            authorization_evidence_identity=evidence,
        )
    assert (
        sum(call.startswith("apply_signed_action_id_v1:") for call in adapter.calls)
        == apply_calls_before_replay
    )


def test_timeout_forward_recovery_failure_poisons_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, adapter = _runtime()
    ref = _open(runtime)
    _advance(runtime, 100)
    commitment = runtime.current_timeout_due_commitment_v1(ref)
    evidence = _timeout_authorization_evidence(
        runtime,
        ref,
        commitment,
        signed_action_id="poisoned-timeout",
    )

    def fail_receipt(
        self: rt.C8TimedSessionRuntimeV1, **kwargs: object
    ) -> rt.TimeoutActionExecutionReceiptV1:
        raise RuntimeError("forced receipt construction failure")

    monkeypatch.setattr(
        rt.C8TimedSessionRuntimeV1,
        "_build_timeout_execution_receipt",
        fail_receipt,
    )
    adapter.restore_raises = True
    with pytest.raises(rt.C8TimedSessionRuntimeError, match="poisoned"):
        runtime.forward_timeout_due_signed_action_id_v1(
            ref,
            timeout_due_commitment=commitment,
            signed_action_id="poisoned-timeout",
            authorization_evidence_identity=evidence,
        )
    adapter.restore_raises = False
    with pytest.raises(rt.C8TimedSessionRuntimeError, match="fail-closed"):
        runtime.public_projection()


@pytest.mark.parametrize("nested_operation", ["forward", "advance", "open", "rollback"])
def test_timeout_apply_callback_cannot_reenter_runtime_operations(
    nested_operation: str,
) -> None:
    runtime, adapter = _runtime()
    ref = _open(runtime)
    _advance(runtime, 100)
    commitment = runtime.current_timeout_due_commitment_v1(ref)
    action_id = f"reentrant-{nested_operation}"
    evidence = _timeout_authorization_evidence(
        runtime,
        ref,
        commitment,
        signed_action_id=action_id,
    )
    rollback_snapshot = runtime.capture_transaction()
    before_outer = runtime.state
    before_inner = adapter.capture_transaction_snapshot_v1()

    if nested_operation == "forward":
        adapter.apply_reentrant_call = lambda: (
            runtime.forward_timeout_due_signed_action_id_v1(
                ref,
                timeout_due_commitment=commitment,
                signed_action_id=action_id,
                authorization_evidence_identity=evidence,
            )
        )
    elif nested_operation == "advance":
        adapter.apply_reentrant_call = lambda: runtime.ingest_virtual_time_input(
            object(),  # type: ignore[arg-type]
            expected_previous_input_chain_tip=runtime.state.input_chain_tip,
            duration_profile_identity=PROFILE_ID,
        )
    elif nested_operation == "open":
        adapter.apply_reentrant_call = lambda: runtime.open_window(
            actor_id="p2",
            window_kind=c8.TimedWindowKindV1.OPTIONAL_RESPONSE,
            decision_identity=_sha("reentrant-decision"),
            obligation_identity=_sha("reentrant-obligation"),
            expected_parent_ref=ref,
        )
    else:
        adapter.apply_reentrant_call = lambda: runtime.rollback(rollback_snapshot)

    with pytest.raises(rt.C8TimedSessionRuntimeError):
        runtime.forward_timeout_due_signed_action_id_v1(
            ref,
            timeout_due_commitment=commitment,
            signed_action_id=action_id,
            authorization_evidence_identity=evidence,
        )
    assert runtime.state == before_outer
    assert adapter.capture_transaction_snapshot_v1() == before_inner


def test_nested_child_freezes_parent_budget_and_resume_rebuilds_exact_deadline() -> None:
    runtime, _ = _runtime()
    parent_ref = _open(runtime, label="parent")
    _advance(runtime, 30)
    child_ref = _open(
        runtime,
        label="child",
        kind=c8.TimedWindowKindV1.OPTIONAL_RESPONSE,
        parent=parent_ref,
        actor="p2",
    )
    parent_suspended, child = runtime.state.virtual_time_state.window_stack.windows
    assert parent_suspended.status is c8.TimedWindowStatusV1.SUSPENDED_BY_CHILD
    assert parent_suspended.remaining_ticks == 70
    assert child.opened_at == 30
    assert child.deadline_at == 130

    _advance(runtime, 80)
    parent_suspended, child = runtime.state.virtual_time_state.window_stack.windows
    assert parent_suspended.remaining_ticks == 70
    assert child.remaining_ticks == 50
    runtime.close_window_by_action(child_ref)

    resumed = runtime.state.virtual_time_state.window_stack.active_window
    assert resumed is not None
    assert resumed.window_id == parent_ref.window_id
    assert resumed.status is c8.TimedWindowStatusV1.ACTIVE
    assert resumed.remaining_ticks == 70
    assert resumed.deadline_at == 150
    assert resumed.deadline_at == runtime.state.virtual_time_state.now_tick + 70


def test_lifo_and_stale_refs_prevent_double_pause_or_double_resume() -> None:
    runtime, _ = _runtime()
    parent_ref = _open(runtime, label="parent")
    _advance(runtime, 20)
    child_ref = _open(runtime, label="child", parent=parent_ref, actor="p2")
    child_state = runtime.state

    with pytest.raises(rt.C8TimedSessionRuntimeError):
        runtime.close_window_by_action(parent_ref)
    with pytest.raises(rt.C8TimedSessionRuntimeError):
        _open(runtime, label="illegal-grandchild", parent=parent_ref, actor="p3")
    assert runtime.state == child_state

    runtime.close_window_by_action(child_ref)
    resumed = runtime.state.virtual_time_state.window_stack.active_window
    assert resumed is not None
    assert resumed.remaining_ticks == 80
    assert resumed.deadline_at == 100
    after_resume = runtime.state
    with pytest.raises(rt.C8TimedSessionRuntimeError):
        runtime.close_window_by_action(child_ref)
    with pytest.raises(rt.C8TimedSessionRuntimeError):
        _open(runtime, label="stale-child-parent", parent=child_ref, actor="p3")
    assert runtime.state == after_resume


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("window_id", "c8w-forged"),
        ("parent_window_id", "c8w-forged-parent"),
        ("actor_id", "p-forged"),
        ("decision_identity", _sha("forged-decision")),
        ("obligation_identity", _sha("forged-obligation")),
        ("window_binding_identity", _sha("forged-window-binding")),
    ],
)
def test_wrong_window_parent_actor_decision_or_obligation_ref_fails_closed(
    field: str, replacement: object
) -> None:
    runtime, _ = _runtime()
    ref = _open(runtime)
    forged = _unsafe_ref_with(ref, **{field: replacement})
    before = runtime.state

    with pytest.raises(rt.C8TimedSessionRuntimeError):
        runtime.action_eligibility(forged)
    assert runtime.state == before


def test_multi_step_continuation_preserves_logical_deadline_and_binding() -> None:
    runtime, _ = _runtime()
    obligation = _sha("one-logical-obligation")
    ref = _open(
        runtime,
        label="multi",
        kind=c8.TimedWindowKindV1.MULTI_STEP_OBLIGATION,
        obligation_identity=obligation,
    )
    _advance(runtime, 15)
    active_before = runtime.state.virtual_time_state.window_stack.active_window
    assert active_before is not None

    eligibility = runtime.continue_multi_step_obligation(
        ref, expected_step_index=0, logical_step_identity=_sha("logical-step-0")
    )
    active_after = runtime.state.virtual_time_state.window_stack.active_window
    assert active_after is not None
    assert eligibility is c8.DeadlinePrecedenceV1.ACTION_ELIGIBLE_BEFORE_DEADLINE
    assert active_after.window_id == active_before.window_id
    assert active_after.window_binding_identity == active_before.window_binding_identity
    assert active_after.obligation_identity == obligation
    assert active_after.opened_at == active_before.opened_at
    assert active_after.deadline_at == active_before.deadline_at == 100
    assert active_after.remaining_ticks == active_before.remaining_ticks == 85
    assert runtime.state.logical_obligations[0].next_step_index == 1

    before_illegal_reopen = runtime.state
    with pytest.raises(rt.C8TimedSessionRuntimeError):
        _open(
            runtime,
            label="same-obligation-child",
            kind=c8.TimedWindowKindV1.MULTI_STEP_OBLIGATION,
            parent=ref,
            obligation_identity=obligation,
        )
    assert runtime.state == before_illegal_reopen


def test_multi_step_obligation_cannot_refresh_through_intervening_child() -> None:
    runtime, _ = _runtime()
    obligation = _sha("stack-wide-logical-obligation")
    root_ref = _open(
        runtime,
        label="multi-root",
        kind=c8.TimedWindowKindV1.MULTI_STEP_OBLIGATION,
        obligation_identity=obligation,
    )
    child_ref = _open(
        runtime,
        label="intervening-child",
        kind=c8.TimedWindowKindV1.OPTIONAL_RESPONSE,
        parent=root_ref,
        actor="p2",
    )
    before = runtime.state

    with pytest.raises(rt.C8TimedSessionRuntimeError):
        _open(
            runtime,
            label="illegal-refreshed-multi",
            kind=c8.TimedWindowKindV1.MULTI_STEP_OBLIGATION,
            parent=child_ref,
            actor="p3",
            obligation_identity=obligation,
        )
    assert runtime.state == before


def test_duplicate_logical_step_identity_is_replay_rejected() -> None:
    runtime, _ = _runtime()
    ref = _open(
        runtime,
        label="multi-replay",
        kind=c8.TimedWindowKindV1.MULTI_STEP_OBLIGATION,
    )
    step_identity = _sha("same-logical-step")
    runtime.continue_multi_step_obligation(
        ref, expected_step_index=0, logical_step_identity=step_identity
    )
    before = runtime.state

    with pytest.raises(rt.C8TimedSessionRuntimeError):
        runtime.continue_multi_step_obligation(
            ref, expected_step_index=1, logical_step_identity=step_identity
        )
    assert runtime.state == before


def test_timeout_same_tick_progress_consumes_one_receipt_per_strict_step() -> None:
    runtime, _ = _runtime()
    obligation = _sha("timeout-multi-obligation")
    ref = _open(
        runtime,
        label="timeout-multi",
        kind=c8.TimedWindowKindV1.MULTI_STEP_OBLIGATION,
        obligation_identity=obligation,
    )
    _advance(runtime, 100)
    active_before = runtime.state.virtual_time_state.window_stack.active_window
    assert active_before is not None
    pending_before = runtime.state.pending_deadline
    first_receipt = _forward_timeout(
        runtime,
        ref,
        signed_action_id="timeout-multi-step-action-0",
    )
    eligibility = runtime.continue_timeout_multi_step_obligation_v1(
        ref,
        execution_receipt=first_receipt,
        expected_step_index=0,
        logical_step_identity=_sha("timeout-logical-step-0"),
    )
    active_after = runtime.state.virtual_time_state.window_stack.active_window
    assert active_after is not None
    assert eligibility is c8.DeadlinePrecedenceV1.TIMEOUT_PRIORITY_AT_OR_AFTER_DEADLINE
    assert runtime.state.virtual_time_state.now_tick == 100
    assert runtime.state.pending_deadline == pending_before
    assert active_after.window_id == active_before.window_id
    assert active_after.window_binding_identity == active_before.window_binding_identity
    assert active_after.obligation_identity == obligation
    assert active_after.opened_at == active_before.opened_at
    assert active_after.deadline_at == active_before.deadline_at == 100
    assert active_after.remaining_ticks == active_before.remaining_ticks == 0
    assert runtime.state.logical_obligations[-1].next_step_index == 1
    assert (
        runtime.state.runtime_events[-1].event_kind
        is rt.RuntimeEventKindV1.TIMEOUT_MULTI_STEP_CONTINUED
    )
    assert (
        runtime.state.runtime_events[-1].execution_receipt_identity
        == first_receipt.receipt_identity
    )

    with pytest.raises(rt.C8TimedSessionRuntimeError):
        runtime.continue_timeout_multi_step_obligation_v1(
            ref,
            execution_receipt=first_receipt,
            expected_step_index=1,
            logical_step_identity=_sha("timeout-logical-step-replay"),
        )

    second_receipt = _forward_timeout(
        runtime,
        ref,
        signed_action_id="timeout-multi-step-action-1",
    )
    assert second_receipt.receipt_sequence == first_receipt.receipt_sequence + 1
    assert second_receipt.previous_receipt_identity == first_receipt.receipt_identity
    assert second_receipt.receipt_identity != first_receipt.receipt_identity
    runtime.continue_timeout_multi_step_obligation_v1(
        ref,
        execution_receipt=second_receipt,
        expected_step_index=1,
        logical_step_identity=_sha("timeout-logical-step-1"),
    )
    assert runtime.state.logical_obligations[-1].next_step_index == 2
    assert runtime.state.virtual_time_state.now_tick == 100
    assert (
        runtime.state.virtual_time_state.window_stack.active_window.deadline_at
        == 100
    )


def test_timeout_progress_rejects_before_deadline_wrong_step_and_wrong_obligation() -> None:
    runtime, _ = _runtime()
    ref = _open(
        runtime,
        label="timeout-progress-guard",
        kind=c8.TimedWindowKindV1.MULTI_STEP_OBLIGATION,
    )
    with pytest.raises(rt.C8TimedSessionRuntimeError):
        runtime.continue_timeout_multi_step_obligation_v1(
            ref,
            execution_receipt=None,
            expected_step_index=0,
            logical_step_identity=_sha("early-timeout-step"),
        )

    _advance(runtime, 100)
    receipt = _forward_timeout(runtime, ref)
    wrong_ref = _unsafe_ref_with(
        ref, obligation_identity=_sha("wrong-timeout-obligation")
    )
    before = runtime.state
    with pytest.raises(rt.C8TimedSessionRuntimeError):
        runtime.continue_timeout_multi_step_obligation_v1(
            wrong_ref,
            execution_receipt=receipt,
            expected_step_index=0,
            logical_step_identity=_sha("wrong-obligation-step"),
        )
    with pytest.raises(rt.C8TimedSessionRuntimeError):
        runtime.continue_timeout_multi_step_obligation_v1(
            ref,
            execution_receipt=receipt,
            expected_step_index=1,
            logical_step_identity=_sha("skipped-timeout-step"),
        )
    assert runtime.state == before

    step_identity = _sha("timeout-step-once")
    runtime.continue_timeout_multi_step_obligation_v1(
        ref,
        execution_receipt=receipt,
        expected_step_index=0,
        logical_step_identity=step_identity,
    )
    next_receipt = _forward_timeout(
        runtime,
        ref,
        signed_action_id="timeout-step-duplicate-identity",
    )
    before_duplicate = runtime.state
    with pytest.raises(rt.C8TimedSessionRuntimeError):
        runtime.continue_timeout_multi_step_obligation_v1(
            ref,
            execution_receipt=next_receipt,
            expected_step_index=1,
            logical_step_identity=step_identity,
        )
    assert runtime.state == before_duplicate


def test_timeout_receipt_from_rolled_back_sibling_lineage_cannot_replay() -> None:
    runtime, _ = _runtime()
    ref = _open(
        runtime,
        label="timeout-sibling",
        kind=c8.TimedWindowKindV1.MULTI_STEP_OBLIGATION,
    )
    _advance(runtime, 100)
    branch_point = runtime.capture_transaction()
    first_receipt = _forward_timeout(
        runtime,
        ref,
        signed_action_id="sibling-timeout-a",
    )
    runtime.rollback(branch_point)
    assert runtime.state == branch_point.outer_state

    second_receipt = _forward_timeout(
        runtime,
        ref,
        signed_action_id="sibling-timeout-b",
    )
    assert second_receipt.previous_receipt_identity == first_receipt.receipt_identity
    with pytest.raises(rt.C8TimedSessionRuntimeError):
        runtime.continue_timeout_multi_step_obligation_v1(
            ref,
            execution_receipt=first_receipt,
            expected_step_index=0,
            logical_step_identity=_sha("sibling-stale-step"),
        )
    runtime.continue_timeout_multi_step_obligation_v1(
        ref,
        execution_receipt=second_receipt,
        expected_step_index=0,
        logical_step_identity=_sha("sibling-current-step"),
    )


def test_timeout_commitment_becomes_stale_after_same_tick_outer_progress() -> None:
    runtime, _ = _runtime()
    ref = _open(
        runtime,
        label="stale-timeout-commitment",
        kind=c8.TimedWindowKindV1.MULTI_STEP_OBLIGATION,
    )
    _advance(runtime, 100)
    stale_commitment = runtime.current_timeout_due_commitment_v1(ref)
    receipt = _forward_timeout(
        runtime,
        ref,
        signed_action_id="stale-commitment-first-action",
        timeout_due_commitment=stale_commitment,
    )
    runtime.continue_timeout_multi_step_obligation_v1(
        ref,
        execution_receipt=receipt,
        expected_step_index=0,
        logical_step_identity=_sha("stale-commitment-step"),
    )
    with pytest.raises(rt.C8TimedSessionRuntimeError):
        runtime.expected_timeout_action_authentication_binding_v1(
            ref,
            timeout_due_commitment=stale_commitment,
            signed_action_id="must-use-fresh-commitment",
        )


def test_snapshot_rollback_restores_all_outer_chains_window_state_and_inner_token() -> None:
    runtime, adapter = _runtime()
    parent_ref = _open(runtime, label="parent")
    _advance(runtime, 20)
    snapshot = runtime.capture_transaction()
    expected_outer = snapshot.outer_state.to_dict()
    expected_inner = adapter.capture_transaction_snapshot_v1()

    child_ref = _open(runtime, label="child", parent=parent_ref, actor="p2")
    child = runtime.state.virtual_time_state.window_stack.active_window
    assert child is not None
    runtime.forward_on_time_signed_action_id(
        child_ref, signed_action_id="inner-mutation-before-rollback"
    )
    result = _advance(runtime, child.deadline_at)
    assert result.derived_deadline is not None
    assert runtime.state.pending_deadline is not None

    runtime.rollback(snapshot)

    assert runtime.state.to_dict() == expected_outer
    assert runtime.state.virtual_time_state.now_tick == 20
    assert runtime.active_window_ref() == parent_ref
    assert runtime.state.pending_deadline is None
    assert adapter.capture_transaction_snapshot_v1() == expected_inner
    assert child_ref.window_id not in {
        window.window_id for window in runtime.state.virtual_time_state.window_stack.windows
    }


def test_failed_inner_restore_recovers_backup_and_keeps_outer_state_atomic() -> None:
    runtime, adapter = _runtime()
    _open(runtime)
    snapshot = runtime.capture_transaction()
    _advance(runtime, 10)
    before_outer = runtime.state
    before_public = runtime.public_projection()
    before_inner = adapter.capture_transaction_snapshot_v1()
    adapter.corrupt_next_restore = True

    with pytest.raises(rt.C8TimedSessionRuntimeError):
        runtime.rollback(snapshot)

    assert runtime.state == before_outer
    assert adapter.capture_transaction_snapshot_v1() == before_inner
    assert runtime.public_projection() == before_public


def test_shared_adapter_snapshot_cannot_rollback_external_auth_ledger() -> None:
    authenticator = FakeAuthenticator(label="shared-ledger")
    runtime, adapter = _runtime(
        authenticator=authenticator,
        share_auth_ledger_with_adapter_snapshot=True,
    )
    _open(runtime)
    snapshot_before_auth = runtime.capture_transaction()
    _advance(runtime, 10)
    outer_after_auth = runtime.state
    inner_after_auth = adapter.capture_transaction_snapshot_v1()
    ledger_after_auth = authenticator.anti_replay_state_identity_v1()

    with pytest.raises(rt.C8TimedSessionRuntimeError):
        runtime.rollback(snapshot_before_auth)

    assert runtime.state == outer_after_auth
    assert adapter.capture_transaction_snapshot_v1() == inner_after_auth
    assert authenticator.anti_replay_state_identity_v1() == ledger_after_auth
    assert runtime.public_projection().now_tick == 10


@pytest.mark.parametrize("target_fault", ["adapter", "session", "public", "authoritative"])
def test_target_restore_revalidates_all_four_inner_identities_and_recovers(
    target_fault: str,
) -> None:
    runtime, adapter = _runtime()
    _open(runtime)
    snapshot = runtime.capture_transaction()
    _advance(runtime, 10)
    before_outer = runtime.state
    before_inner = adapter.capture_transaction_snapshot_v1()
    adapter.restore_faults = [target_fault]

    with pytest.raises(rt.C8TimedSessionRuntimeError):
        runtime.rollback(snapshot)

    assert runtime.state == before_outer
    assert adapter.capture_transaction_snapshot_v1() == before_inner
    assert adapter.adapter_identity_v1() == before_outer.inner_adapter_identity
    assert adapter.session_binding_identity_v1() == before_outer.inner_session_binding_identity
    assert adapter.public_state_identity_v1() == before_outer.inner_public_state_identity
    assert (
        adapter.authoritative_state_identity_v1()
        == before_outer.inner_authoritative_state_identity
    )


def test_backup_recovery_revalidates_all_four_identities() -> None:
    runtime, adapter = _runtime()
    _open(runtime)
    snapshot = runtime.capture_transaction()
    _advance(runtime, 10)
    before_outer = runtime.state
    adapter.restore_faults = ["public", "adapter"]

    with pytest.raises(rt.C8TimedSessionRuntimeError):
        runtime.rollback(snapshot)

    assert runtime.state == before_outer


def test_rejected_transition_does_not_change_outer_or_inner_state() -> None:
    runtime, adapter = _runtime()
    _open(runtime)
    invalid = _authorized_input(runtime, requested_tick=10)
    before_outer = runtime.state.to_dict()
    before_inner = adapter.capture_transaction_snapshot_v1()

    with pytest.raises(rt.C8TimedSessionRuntimeError):
        _ingest(runtime, invalid, profile_identity=_sha("wrong-profile"))

    assert runtime.state.to_dict() == before_outer
    assert adapter.capture_transaction_snapshot_v1() == before_inner


def test_caller_cannot_ingest_forged_or_even_genuine_derived_deadline_object() -> None:
    runtime, _ = _runtime()
    _open(runtime)
    result = _advance(runtime, 100)
    assert result.derived_deadline is not None
    before = runtime.state

    with pytest.raises(rt.C8TimedSessionRuntimeError):
        _ingest(runtime, result.derived_deadline)
    with pytest.raises(rt.C8TimedSessionRuntimeError):
        _ingest(runtime, {"event_kind": "DEADLINE_REACHED"})
    assert runtime.state == before


def test_module_has_no_wall_clock_rng_or_nondeterministic_identity_source() -> None:
    source = inspect.getsource(rt)
    tree = ast.parse(source)
    banned_roots = {"time", "datetime", "random", "secrets", "uuid"}
    imported_roots: set[str] = set()
    referenced_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_roots.add(node.module.split(".", 1)[0])
        elif isinstance(node, ast.Name):
            referenced_names.add(node.id)

    assert not (banned_roots & imported_roots)
    assert not (banned_roots & referenced_names)
    assert rt.C8_B_RUNTIME_DESCRIPTOR_V1["wall_clock"] == "FORBIDDEN"
    assert rt.C8_B_RUNTIME_DESCRIPTOR_V1["rng"] == "FORBIDDEN"


def test_inner_adapter_and_public_projection_expose_no_timeout_or_private_gameplay_api() -> None:
    protocol_members = set(rt.TimedSessionInnerAdapterV1.__dict__)
    assert {
        "adapter_identity_v1",
        "session_binding_identity_v1",
        "public_state_identity_v1",
        "authoritative_state_identity_v1",
        "capture_transaction_snapshot_v1",
        "snapshot_token_identity_v1",
        "restore_transaction_snapshot_v1",
        "apply_signed_action_id_v1",
    }.issubset(protocol_members)
    assert not {
        "legal_actions",
        "step",
        "resolve_timeout",
        "choose_timeout_action",
        "private_state",
    } & protocol_members
    authenticator_members = set(rt.VirtualTimeInputAuthenticatorV1.__dict__)
    assert {
        "authenticator_identity_v1",
        "anti_replay_state_identity_v1",
        "verify_and_consume_advance_authorization_v1",
        "verify_and_consume_timeout_action_authorization_v1",
    }.issubset(authenticator_members)

    runtime, adapter = _runtime()
    _open(runtime)
    _advance(runtime, 10)
    public = runtime.public_projection().to_dict()
    assert not any(
        fragment in key
        for key in public
        for fragment in ("authoritative", "private", "driver_authority", "snapshot_token")
    )
    assert adapter.private_payload_calls == 0
    assert adapter.inner_events == []


def test_timeout_receipt_and_public_projection_do_not_leak_private_payload() -> None:
    runtime, adapter = _runtime()
    ref = _open(runtime)
    _advance(runtime, 100)
    signed_action_id = "public-timeout-action-reference"
    receipt = _forward_timeout(
        runtime,
        ref,
        signed_action_id=signed_action_id,
    )
    receipt_json = json.dumps(receipt.to_dict(), sort_keys=True)
    public_json = json.dumps(runtime.public_projection().to_dict(), sort_keys=True)

    assert signed_action_id not in receipt_json
    assert adapter.opaque_token_secret not in receipt_json
    assert "secret_counter" not in receipt_json
    assert receipt.receipt_identity not in adapter.inner_events
    assert "execution_receipt" not in public_json
    assert "authorization_evidence" not in public_json
    assert "authoritative" not in public_json
    assert adapter.private_payload_calls == 0


def test_public_projection_does_not_expose_authoritative_derived_state_identity() -> None:
    runtime, _ = _runtime()
    _open(runtime)
    public = runtime.public_projection().to_dict()

    assert "state_identity" not in public
    assert not any("authoritative" in key or "private" in key for key in public)


def test_outer_state_strict_round_trip_and_root_tamper_rejection() -> None:
    runtime, _ = _runtime()
    _open(runtime)
    _advance(runtime, 10)
    _advance(runtime, 20)
    raw = json.loads(json.dumps(runtime.state.to_dict(), sort_keys=True))
    assert rt.TimedSessionOuterStateV1.from_dict(raw) == runtime.state

    mutations = []
    extra = copy.deepcopy(raw)
    extra["unexpected"] = "field"
    mutations.append(extra)
    missing = copy.deepcopy(raw)
    missing.pop("event_chain_tip")
    mutations.append(missing)
    numeric_bool = copy.deepcopy(raw)
    numeric_bool["state_revision"] = True
    mutations.append(numeric_bool)
    identity = copy.deepcopy(raw)
    identity["inner_authoritative_state_identity"] = "f" * 64
    mutations.append(identity)

    for mutated in mutations:
        with pytest.raises((rt.C8TimedSessionRuntimeError, c8.C8VirtualTimeContractError)):
            rt.TimedSessionOuterStateV1.from_dict(mutated)


def test_outer_state_deep_tamper_reorder_and_contract_latch_splice_rejected() -> None:
    runtime, _ = _runtime()
    _open(runtime)
    _advance(runtime, 10)
    _advance(runtime, 20)
    raw = json.loads(json.dumps(runtime.state.to_dict(), sort_keys=True))

    deep_tick = copy.deepcopy(raw)
    deep_tick["virtual_time_state"]["now_tick"] = 11
    reordered_events = copy.deepcopy(raw)
    reordered_events["runtime_events"][0], reordered_events["runtime_events"][1] = (
        reordered_events["runtime_events"][1],
        reordered_events["runtime_events"][0],
    )
    reordered_inputs = copy.deepcopy(raw)
    reordered_inputs["input_records"].reverse()
    latch_splice = copy.deepcopy(raw)
    latch_splice["contract_latch"]["c8_a_contract_identity"] = "f" * 64

    for mutated in (deep_tick, reordered_events, reordered_inputs, latch_splice):
        with pytest.raises((rt.C8TimedSessionRuntimeError, c8.C8VirtualTimeContractError)):
            rt.TimedSessionOuterStateV1.from_dict(mutated)


def test_child_only_runtime_rejects_coherent_global_pause_or_frozen_injection() -> None:
    runtime, _ = _runtime()
    _open(runtime)
    prior = runtime.state
    active = prior.virtual_time_state.window_stack.active_window
    assert active is not None
    control = c8.VirtualTimeControlInputV1.issue(
        input_kind=c8.VirtualTimeControlInputKindV1.PAUSE,
        input_seq=prior.virtual_time_state.next_input_seq,
        source_id=prior.input_source_id,
        domain_id=c8.CLOCK_DOMAIN_ID,
        window_id=active.window_id,
        authentication_evidence_identity=_sha("coherent-forged-pause-auth"),
    )
    paused = c8.pause_virtual_time_v1(
        prior.virtual_time_state, control, c8.CLOCK_DOMAIN_V1
    )
    paused_active = paused.window_stack.active_window
    assert paused_active is not None
    record = rt.AcceptedVirtualTimeInputV1.build(
        input_seq=control.input_seq,
        input_identity=control.input_identity,
        previous_input_chain_tip=prior.input_chain_tip,
        before_virtual_state_identity=prior.virtual_time_state.state_identity,
        after_virtual_state_identity=paused.state_identity,
        requested_tick=paused.now_tick,
        applied_tick=paused.now_tick,
        unconsumed_ticks=0,
        derived_deadline_identity=None,
    )
    event = rt.RuntimeEventV1.build(
        event_sequence=len(prior.runtime_events),
        event_kind=rt.RuntimeEventKindV1.TIME_INPUT_ACCEPTED,
        runtime_instance_identity=prior.runtime_instance_identity,
        tick=paused.now_tick,
        window=paused_active,
        related_window_id=None,
        before_virtual_state_identity=prior.virtual_time_state.state_identity,
        after_virtual_state_identity=paused.state_identity,
        input_identity=control.input_identity,
        derived_deadline_identity=None,
        logical_step_identity=None,
        inner_transition_identity=None,
        requested_tick=paused.now_tick,
        applied_tick=paused.now_tick,
        previous_event_identity=prior.event_chain_tip,
    )

    with pytest.raises(rt.C8TimedSessionRuntimeError):
        rt.TimedSessionOuterStateV1.build(
            runtime_instance_identity=prior.runtime_instance_identity,
            instance_nonce_identity=prior.instance_nonce_identity,
            contract_latch=prior.contract_latch,
            input_source_id=prior.input_source_id,
            driver_authority_identity=prior.driver_authority_identity,
            input_authenticator_identity=prior.input_authenticator_identity,
            inner_adapter_identity=prior.inner_adapter_identity,
            inner_session_binding_identity=prior.inner_session_binding_identity,
            inner_public_state_identity=prior.inner_public_state_identity,
            inner_authoritative_state_identity=prior.inner_authoritative_state_identity,
            virtual_time_state=paused,
            input_records=prior.input_records + (record,),
            window_open_state_origins=prior.window_open_state_origins,
            logical_obligations=prior.logical_obligations,
            seen_logical_obligation_identities=(
                prior.seen_logical_obligation_identities
            ),
            pending_deadline=None,
            runtime_events=prior.runtime_events + (event,),
        )


def test_cancel_is_rollback_only_with_no_committed_cancel_event() -> None:
    runtime, adapter = _runtime()
    pre_open = runtime.capture_transaction()
    ref = _open(runtime)
    _advance(runtime, 20)
    before_cancel_identity = runtime.state.state_identity

    receipt = runtime.cancel_window_to_pre_open_snapshot(
        ref, pre_open_snapshot=pre_open
    )

    assert receipt.before_state_identity == before_cancel_identity
    assert receipt.restored_state_identity == pre_open.outer_state.state_identity
    assert receipt.committed_cancel_event is False
    assert runtime.state == pre_open.outer_state
    assert runtime.state.runtime_events == ()
    assert runtime.active_window_ref() is None
    assert "WINDOW_CANCELLED" not in rt.RuntimeEventKindV1.__members__
    assert adapter.inner_events == []


def test_cancel_rejects_non_pre_open_snapshot_and_is_atomic() -> None:
    runtime, _ = _runtime()
    initial = runtime.capture_transaction()
    parent_ref = _open(runtime, label="parent")
    parent_open = runtime.capture_transaction()
    child_ref = _open(runtime, label="child", parent=parent_ref, actor="p2")
    before = runtime.state

    with pytest.raises(rt.C8TimedSessionRuntimeError):
        runtime.cancel_window_to_pre_open_snapshot(
            child_ref, pre_open_snapshot=initial
        )
    assert runtime.state == before

    receipt = runtime.cancel_window_to_pre_open_snapshot(
        child_ref, pre_open_snapshot=parent_open
    )
    assert receipt.committed_cancel_event is False
    assert runtime.state == parent_open.outer_state


def test_stale_parent_snapshot_cannot_masquerade_as_child_immediate_pre_open() -> None:
    runtime, _ = _runtime()
    parent_ref = _open(runtime, label="parent")
    stale_parent_snapshot = runtime.capture_transaction()
    _advance(runtime, 10)
    child_ref = _open(runtime, label="child", parent=parent_ref, actor="p2")
    before = runtime.state

    with pytest.raises(rt.C8TimedSessionRuntimeError):
        runtime.cancel_window_to_pre_open_snapshot(
            child_ref, pre_open_snapshot=stale_parent_snapshot
        )
    assert runtime.state == before


def test_snapshot_live_owner_guard_rejects_other_wrapper_even_with_same_identity_material() -> None:
    first, _ = _runtime(FakeInnerAdapter(label="shared"))
    second, _ = _runtime(FakeInnerAdapter(label="shared"))
    _open(first)
    _open(second)
    first_snapshot = first.capture_transaction()
    second_before = second.state

    # Runtime nonce uniqueness is an external constructor precondition; the live
    # snapshot owner guard is still object-local even if that precondition is broken.
    assert first.state.runtime_instance_identity == second.state.runtime_instance_identity
    with pytest.raises(rt.C8TimedSessionRuntimeError):
        second.rollback(first_snapshot)
    assert second.state == second_before


def test_forged_copied_snapshot_is_rejected_by_issued_object_registry() -> None:
    runtime, _ = _runtime()
    _open(runtime)
    issued = runtime.capture_transaction()
    forged_copy = replace(issued)
    assert forged_copy is not issued
    assert forged_copy == issued
    _advance(runtime, 10)
    before = runtime.state

    with pytest.raises(rt.C8TimedSessionRuntimeError):
        runtime.rollback(forged_copy)
    assert runtime.state == before


def test_actual_issued_snapshot_identity_and_deep_outer_tamper_fail_closed() -> None:
    runtime, adapter = _runtime()
    _open(runtime)
    issued = runtime.capture_transaction()
    _advance(runtime, 10)
    before = runtime.state

    original_snapshot_identity = issued.snapshot_identity
    calls_before_identity_tamper = tuple(adapter.calls)
    object.__setattr__(issued, "snapshot_identity", "f" * 64)
    try:
        with pytest.raises(rt.C8TimedSessionRuntimeError):
            runtime.rollback(issued)
    finally:
        object.__setattr__(issued, "snapshot_identity", original_snapshot_identity)
    assert runtime.state == before
    assert tuple(adapter.calls) == calls_before_identity_tamper

    deep_virtual = issued.outer_state.virtual_time_state
    original_deep_identity = deep_virtual.state_identity
    calls_before_deep_tamper = tuple(adapter.calls)
    object.__setattr__(deep_virtual, "state_identity", "e" * 64)
    try:
        with pytest.raises(rt.C8TimedSessionRuntimeError):
            runtime.rollback(issued)
    finally:
        object.__setattr__(deep_virtual, "state_identity", original_deep_identity)
    assert runtime.state == before
    assert tuple(adapter.calls) == calls_before_deep_tamper

    # Restoring both fields returns the actual issued object to its valid form.
    runtime.rollback(issued)
    assert runtime.state == issued.outer_state


def test_snapshot_repr_hides_opaque_inner_token_and_live_owner_guard() -> None:
    runtime, adapter = _runtime()
    snapshot = runtime.capture_transaction()
    rendered = repr(snapshot)

    assert adapter.opaque_token_secret not in rendered
    assert "inner_snapshot_token=" not in rendered
    assert "owner_guard=" not in rendered


def test_controller_callback_guard_valid_enter_exit_and_read_only_access() -> None:
    runtime, _, ref, commitment = _due_runtime()
    lease = _controller_callback_lease(runtime, ref, commitment)
    token = runtime.begin_controller_callback_guard_v1(lease)
    entry_epoch = token.operation_attempt_epoch_at_entry
    entry_tip = token.operation_attempt_chain_tip_at_entry

    assert runtime.state.state_identity == token.outer_state_identity_at_entry
    assert runtime.active_window_ref() == ref
    assert runtime.public_projection().active_window_id == ref.window_id
    assert (
        runtime.action_eligibility(ref)
        is c8.DeadlinePrecedenceV1.TIMEOUT_PRIORITY_AT_OR_AFTER_DEADLINE
    )
    assert runtime.operation_attempt_epoch_v1() == entry_epoch
    active_audit = runtime.controller_callback_security_audit_v1()
    assert active_audit.guard_active is True
    assert active_audit.operation_attempt_epoch == entry_epoch
    assert active_audit.operation_attempt_chain_tip == entry_tip

    result = runtime.release_controller_callback_guard_v1(token)
    assert type(result) is rt.ControllerCallbackGuardResultV1
    assert result.operation_attempt_epoch_at_entry == entry_epoch
    assert result.operation_attempt_epoch_at_exit == entry_epoch
    assert result.operation_attempt_chain_tip_at_exit == entry_tip
    assert result.outer_state_identity_at_exit == token.outer_state_identity_at_entry
    assert runtime.controller_callback_security_audit_v1().guard_active is False


def test_guard_detects_identity_preserving_current_snapshot_rollback_attempt() -> None:
    runtime, adapter, ref, commitment = _due_runtime()
    current_live_snapshot = runtime.capture_transaction()
    lease = _controller_callback_lease(runtime, ref, commitment)
    before = (
        runtime.state.state_identity,
        runtime.public_projection().projection_identity,
        runtime.state.event_chain_tip,
        adapter.public_state_identity_v1(),
        adapter.authoritative_state_identity_v1(),
    )
    caught: list[Exception] = []

    def callback() -> str:
        try:
            runtime.rollback(current_live_snapshot)
        except rt.C8TimedSessionRuntimeError as exc:
            caught.append(exc)
        return "callback-caught-runtime-rejection"

    epoch_before_invoke = runtime.operation_attempt_epoch_v1()
    with pytest.raises(rt.C8TimedSessionRuntimeError, match="operation attempt"):
        runtime.invoke_controller_callback_guarded_v1(lease, callback)

    after = (
        runtime.state.state_identity,
        runtime.public_projection().projection_identity,
        runtime.state.event_chain_tip,
        adapter.public_state_identity_v1(),
        adapter.authoritative_state_identity_v1(),
    )
    assert caught
    assert after == before
    assert runtime.operation_attempt_epoch_v1() >= epoch_before_invoke + 2
    assert runtime.controller_callback_security_audit_v1().guard_active is False


@pytest.mark.parametrize(
    "operation_name",
    [
        "advance",
        "open",
        "close",
        "forward-on-time",
        "forward-timeout",
        "continue",
        "continue-timeout",
        "rollback",
        "capture",
        "issue-timeout-commitment",
        "expected-timeout-binding",
        "expected-advance-binding",
    ],
)
def test_guard_rejects_and_records_each_major_runtime_mutator_attempt(
    operation_name: str,
) -> None:
    runtime, _, ref, commitment = _due_runtime(
        kind=c8.TimedWindowKindV1.MULTI_STEP_OBLIGATION
    )
    snapshot = runtime.capture_transaction()
    operations = {
        "advance": lambda: runtime.ingest_virtual_time_input(
            object(),  # type: ignore[arg-type]
            expected_previous_input_chain_tip=runtime.state.input_chain_tip,
            duration_profile_identity=PROFILE_ID,
        ),
        "open": lambda: runtime.open_window(
            actor_id="p2",
            window_kind=c8.TimedWindowKindV1.OPTIONAL_RESPONSE,
            decision_identity=_sha("guard-nested-open"),
            obligation_identity=_sha("guard-nested-obligation"),
            expected_parent_ref=ref,
        ),
        "close": lambda: runtime.close_window_by_action(ref),
        "forward-on-time": lambda: runtime.forward_on_time_signed_action_id(
            ref, signed_action_id="guard-on-time"
        ),
        "forward-timeout": lambda: (
            runtime.forward_timeout_due_signed_action_id_v1(
                ref,
                timeout_due_commitment=commitment,
                signed_action_id="guard-timeout",
                authorization_evidence_identity=_sha("guard-timeout-evidence"),
            )
        ),
        "continue": lambda: runtime.continue_multi_step_obligation(
            ref,
            expected_step_index=0,
            logical_step_identity=_sha("guard-step"),
        ),
        "continue-timeout": lambda: (
            runtime.continue_timeout_multi_step_obligation_v1(
                ref,
                execution_receipt=None,
                expected_step_index=0,
                logical_step_identity=_sha("guard-timeout-step"),
            )
        ),
        "rollback": lambda: runtime.rollback(snapshot),
        "capture": runtime.capture_transaction,
        "issue-timeout-commitment": lambda: (
            runtime.current_timeout_due_commitment_v1(ref)
        ),
        "expected-timeout-binding": lambda: (
            runtime.expected_timeout_action_authentication_binding_v1(
                ref,
                timeout_due_commitment=commitment,
                signed_action_id="guard-expected-timeout",
            )
        ),
        "expected-advance-binding": lambda: (
            runtime.expected_advance_authentication_binding(requested_tick=100)
        ),
    }
    lease = _controller_callback_lease(runtime, ref, commitment)
    state_before = runtime.state
    epoch_before = runtime.operation_attempt_epoch_v1()

    def callback() -> None:
        with pytest.raises(rt.C8TimedSessionRuntimeError):
            operations[operation_name]()

    with pytest.raises(rt.C8TimedSessionRuntimeError, match="operation attempt"):
        runtime.invoke_controller_callback_guarded_v1(lease, callback)

    assert runtime.state == state_before
    assert runtime.operation_attempt_epoch_v1() >= epoch_before + 2
    assert runtime.controller_callback_security_audit_v1().guard_active is False


def test_nested_begin_and_duplicate_release_are_one_shot_fail_closed() -> None:
    runtime, _, ref, commitment = _due_runtime()
    lease = _controller_callback_lease(runtime, ref, commitment)
    token = runtime.begin_controller_callback_guard_v1(lease)

    with pytest.raises(rt.C8TimedSessionRuntimeError, match="operation attempt"):
        runtime.begin_controller_callback_guard_v1(lease)
    with pytest.raises(rt.C8TimedSessionRuntimeError, match="operation attempt"):
        runtime.release_controller_callback_guard_v1(token)
    assert runtime.controller_callback_security_audit_v1().guard_active is False

    second_lease = _controller_callback_lease(runtime, ref, commitment)
    second_token = runtime.begin_controller_callback_guard_v1(second_lease)
    runtime.release_controller_callback_guard_v1(second_token)
    with pytest.raises(rt.C8TimedSessionRuntimeError, match="duplicate/replay"):
        runtime.release_controller_callback_guard_v1(second_token)


def test_wrong_copied_and_cross_wrapper_guard_tokens_are_rejected() -> None:
    first, _, ref, commitment = _due_runtime()
    second, _, second_ref, second_commitment = _due_runtime()
    lease = _controller_callback_lease(first, ref, commitment)
    token = first.begin_controller_callback_guard_v1(lease)

    copied = replace(token)
    with pytest.raises(rt.C8TimedSessionRuntimeError):
        first.release_controller_callback_guard_v1(copied)
    with pytest.raises(rt.C8TimedSessionRuntimeError, match="operation attempt"):
        first.release_controller_callback_guard_v1(token)
    assert first.controller_callback_security_audit_v1().guard_active is False

    foreign_lease = _controller_callback_lease(first, ref, commitment)
    with pytest.raises(rt.C8TimedSessionRuntimeError):
        second.begin_controller_callback_guard_v1(foreign_lease)
    local_lease = _controller_callback_lease(
        second, second_ref, second_commitment
    )
    local_token = second.begin_controller_callback_guard_v1(local_lease)
    with pytest.raises(rt.C8TimedSessionRuntimeError):
        first.release_controller_callback_guard_v1(local_token)
    second.release_controller_callback_guard_v1(local_token)


def test_guard_lease_rejects_stale_window_and_timeout_lineage() -> None:
    runtime, _ = _runtime()
    ref = _open(runtime)
    before_due = runtime.capture_transaction()
    _advance(runtime, 100)
    commitment = runtime.current_timeout_due_commitment_v1(ref)
    lease = _controller_callback_lease(runtime, ref, commitment)

    runtime.rollback(before_due)
    with pytest.raises(rt.C8TimedSessionRuntimeError, match="stale|lineage"):
        runtime.begin_controller_callback_guard_v1(lease)


def test_controller_callback_exception_releases_busy_state_and_records_security_event() -> None:
    runtime, _, ref, commitment = _due_runtime()
    lease = _controller_callback_lease(runtime, ref, commitment)
    before = runtime.operation_attempt_epoch_v1()

    def exploding_callback() -> None:
        raise RuntimeError("adapter callback failure")

    with pytest.raises(rt.C8TimedSessionRuntimeError, match="guard已安全退出"):
        runtime.invoke_controller_callback_guarded_v1(
            lease, exploding_callback
        )

    audit = runtime.controller_callback_security_audit_v1()
    assert audit.guard_active is False
    assert audit.operation_attempt_epoch >= before + 2
    assert runtime.public_projection().active_window_id == ref.window_id
    assert runtime.current_timeout_due_commitment_v1(ref).window_id == ref.window_id


def test_operation_attempt_epoch_is_not_restored_by_gameplay_rollback() -> None:
    runtime, _ = _runtime()
    ref = _open(runtime)
    snapshot = runtime.capture_transaction()
    state_at_snapshot = snapshot.outer_state
    epoch_at_snapshot = runtime.operation_attempt_epoch_v1()
    tip_at_snapshot = runtime.controller_callback_security_audit_v1().operation_attempt_chain_tip

    _advance(runtime, 10)
    epoch_after_mutation = runtime.operation_attempt_epoch_v1()
    runtime.rollback(snapshot)

    audit = runtime.controller_callback_security_audit_v1()
    assert runtime.state == state_at_snapshot
    assert runtime.active_window_ref() == ref
    assert epoch_after_mutation > epoch_at_snapshot
    assert audit.operation_attempt_epoch > epoch_after_mutation
    assert audit.operation_attempt_chain_tip != tip_at_snapshot


def test_guard_token_tamper_and_serialized_audit_cannot_authorize() -> None:
    runtime, _, ref, commitment = _due_runtime()
    lease = _controller_callback_lease(runtime, ref, commitment)
    assert not hasattr(lease, "to_dict")
    assert not hasattr(lease, "from_dict")
    with pytest.raises(rt.C8TimedSessionRuntimeError):
        runtime.begin_controller_callback_guard_v1(replace(lease))

    fresh_lease = _controller_callback_lease(runtime, ref, commitment)
    token = runtime.begin_controller_callback_guard_v1(fresh_lease)
    assert not hasattr(token, "to_dict")
    assert not hasattr(token, "from_dict")
    original_epoch = token.operation_attempt_epoch_at_entry
    object.__setattr__(
        token, "operation_attempt_epoch_at_entry", original_epoch + 1
    )
    try:
        with pytest.raises(rt.C8TimedSessionRuntimeError):
            runtime.release_controller_callback_guard_v1(token)
    finally:
        object.__setattr__(
            token, "operation_attempt_epoch_at_entry", original_epoch
        )
    with pytest.raises(rt.C8TimedSessionRuntimeError, match="operation attempt"):
        runtime.release_controller_callback_guard_v1(token)
    audit_dict = runtime.controller_callback_security_audit_v1().to_dict()
    assert "guard_identity" not in audit_dict
    assert "lease_identity" not in audit_dict
    with pytest.raises(rt.C8TimedSessionRuntimeError):
        runtime.begin_controller_callback_guard_v1(audit_dict)  # type: ignore[arg-type]


def test_security_epoch_private_tamper_fails_closed_without_restore_path() -> None:
    runtime, _ = _runtime()
    _open(runtime)
    original = runtime.operation_attempt_epoch_v1()
    object.__setattr__(
        runtime,
        "_C8TimedSessionRuntimeV1__operation_attempt_epoch",
        original + 1,
    )
    with pytest.raises(rt.C8TimedSessionRuntimeError, match="epoch/history drift"):
        runtime.operation_attempt_epoch_v1()


def _attempt_records(runtime):
    return runtime._C8TimedSessionRuntimeV1__operation_attempt_records


def test_attempt_memo_reuses_hashes_but_visits_every_record(monkeypatch):
    runtime, _ = _runtime()
    _open(runtime)
    runtime.operation_attempt_epoch_v1()  # Populate the verified memo.
    before = runtime.controller_callback_security_audit_v1().to_dict()
    calls = {"hash": 0, "fields": 0}
    original_hash, original_text = rt._canonical_sha256, rt._exact_text_id

    def counted_hash(value):
        if value.get("schema") == rt.OPERATION_ATTEMPT_CHAIN_SCHEMA and value.get("epoch", 0) > 0:
            calls["hash"] += 1
        return original_hash(value)

    def counted_text(value, label):
        if label == "operation_attempt.operation_name":
            calls["fields"] += 1
        return original_text(value, label)

    monkeypatch.setattr(rt, "_canonical_sha256", counted_hash)
    monkeypatch.setattr(rt, "_exact_text_id", counted_text)
    assert runtime.controller_callback_security_audit_v1().to_dict() == before
    assert calls == {"hash": 0, "fields": len(_attempt_records(runtime))}
    records = _attempt_records(runtime)
    records[0] = tuple(list(records[0]))  # Equal value, different object.
    assert runtime.controller_callback_security_audit_v1().to_dict() == before
    assert calls["hash"] == 1


@pytest.mark.parametrize("mutation", ["epoch", "bool", "float", "operation", "guard", "digest", "append", "reverse", "tip", "instance"])
def test_attempt_memo_rejects_warmed_history_tamper(mutation):
    runtime, _ = _runtime()
    _open(runtime)
    _advance(runtime, 1)
    runtime.operation_attempt_epoch_v1()
    records = _attempt_records(runtime)
    row = list(records[0])
    if mutation == "epoch": row[0] = 2
    elif mutation == "bool": row[0] = True
    elif mutation == "float": row[0] = 1.0
    elif mutation == "operation": row[1] = "tampered"
    elif mutation == "guard": row[2] = _sha("wrong-guard")
    elif mutation == "digest": row[3] = _sha("wrong-digest")
    elif mutation == "append": records.append(records[-1])
    elif mutation == "reverse": records.reverse()
    elif mutation == "tip": runtime._C8TimedSessionRuntimeV1__operation_attempt_chain_tip = _sha("wrong-tip")
    elif mutation == "instance":
        object.__setattr__(runtime.state, "runtime_instance_identity", _sha("wrong-instance"))
    if mutation in {"epoch", "bool", "float", "operation", "guard", "digest"}:
        records[0] = tuple(row)
    with pytest.raises(rt.C8TimedSessionRuntimeError):
        runtime.operation_attempt_epoch_v1()


def test_attempt_memo_mutable_record_and_cross_runtime_are_not_trusted(monkeypatch):
    runtime, _ = _runtime()
    _open(runtime)
    runtime.operation_attempt_epoch_v1()
    records = _attempt_records(runtime)
    records[0] = list(records[0])
    runtime.operation_attempt_epoch_v1()  # Original accepted container remains accepted.
    records[0][1] = "tampered-after-read"
    with pytest.raises(rt.C8TimedSessionRuntimeError, match="chain drift"):
        runtime.operation_attempt_epoch_v1()
    second, _ = _runtime(nonce_identity=_sha("another-runtime"))
    _open(second)
    second._C8TimedSessionRuntimeV1__operation_attempt_records[0] = tuple(records[0])
    with pytest.raises(rt.C8TimedSessionRuntimeError, match="chain drift"):
        second.operation_attempt_epoch_v1()


def test_attempt_memo_failure_recovery_and_rollback_keep_security_chain():
    runtime, _ = _runtime()
    _open(runtime)
    snapshot = runtime.capture_transaction()
    records = _attempt_records(runtime)
    runtime.operation_attempt_epoch_v1()
    original = records[0]
    records[0] = (original[0], "changed", original[2], original[3])
    with pytest.raises(rt.C8TimedSessionRuntimeError):
        runtime.operation_attempt_epoch_v1()
    records[0] = original
    epoch = runtime.operation_attempt_epoch_v1()
    _advance(runtime, 1)
    runtime.rollback(snapshot)
    assert runtime.state == snapshot.outer_state
    assert runtime.operation_attempt_epoch_v1() > epoch
    audit = runtime.controller_callback_security_audit_v1().to_dict()
    assert "cache" not in json.dumps(audit)


def test_attempt_memo_binds_previous_tip_and_runtime_owner(monkeypatch):
    runtime, _ = _runtime()
    _open(runtime)
    _advance(runtime, 1)
    runtime.operation_attempt_epoch_v1()
    records = _attempt_records(runtime)
    epoch, _, guard, _ = records[0]
    changed = rt._canonical_sha256({
        "schema": rt.OPERATION_ATTEMPT_CHAIN_SCHEMA, "contract_version": 1,
        "runtime_contract_identity": rt.C8_B_RUNTIME_CONTRACT_IDENTITY_V1,
        "runtime_instance_identity": runtime.state.runtime_instance_identity,
        "epoch": epoch, "operation_name": "changed", "active_guard_identity": guard,
        "previous_attempt_identity": rt._operation_attempt_chain_genesis(runtime.state.runtime_instance_identity),
    })
    records[0] = (epoch, "changed", guard, changed)
    # The first record is validly rehashed; the unchanged second record is stale.
    with pytest.raises(rt.C8TimedSessionRuntimeError, match="chain drift"):
        runtime.operation_attempt_epoch_v1()

    first, _ = _runtime()
    second, _ = _runtime()  # Same public identity, distinct live owner.
    _open(first)
    _open(second)
    first.operation_attempt_epoch_v1()
    second._C8TimedSessionRuntimeV1__operation_attempt_records[:] = _attempt_records(first)
    second._C8TimedSessionRuntimeV1__operation_attempt_validation_cache[:] = first._C8TimedSessionRuntimeV1__operation_attempt_validation_cache
    calls = []
    original = rt._canonical_sha256

    def counted(value):
        if value.get("schema") == rt.OPERATION_ATTEMPT_CHAIN_SCHEMA and value.get("epoch", 0) > 0:
            calls.append(value["epoch"])
        return original(value)

    monkeypatch.setattr(rt, "_canonical_sha256", counted)
    assert second.operation_attempt_epoch_v1() == first.operation_attempt_epoch_v1()
    assert calls == list(range(1, len(_attempt_records(second)) + 1))


def test_public_projection_and_audit_do_not_leak_live_guard_capability() -> None:
    runtime, _, ref, commitment = _due_runtime()
    lease = _controller_callback_lease(runtime, ref, commitment)
    token = runtime.begin_controller_callback_guard_v1(lease)
    public_json = json.dumps(runtime.public_projection().to_dict(), sort_keys=True)
    audit_json = json.dumps(
        runtime.controller_callback_security_audit_v1().to_dict(),
        sort_keys=True,
    )

    for secret_identity in (
        lease.lease_identity,
        lease.lease_nonce_identity,
        token.guard_identity,
        token.guard_nonce_identity,
        CONTROLLER_ID,
        CONTROLLER_ADAPTER_ID,
    ):
        assert secret_identity not in public_json
        assert secret_identity not in audit_json
    assert "_owner_guard" not in repr(lease)
    assert "_owner_guard" not in repr(token)
    runtime.release_controller_callback_guard_v1(token)


def test_malformed_preconsume_forward_return_keeps_capability_abortable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, _, ref, commitment = _due_runtime()
    action_id = "malformed-preconsume-return"
    capability = _pending_issuance_capability(
        runtime, ref, commitment, signed_action_id=action_id
    )
    assert not hasattr(capability, "to_dict")
    assert not hasattr(capability, "from_dict")
    ledger_before = _AUTHENTICATORS[runtime].anti_replay_state_identity_v1()

    def malformed_forward(
        self: rt.C8TimedSessionRuntimeV1,
        ref: rt.WindowAuthorityRefV1,
        **kwargs: object,
    ) -> object:
        return {"unknown_receipt": True}

    monkeypatch.setattr(
        rt.C8TimedSessionRuntimeV1,
        "forward_timeout_due_signed_action_id_v1",
        malformed_forward,
    )
    observed = runtime.forward_timeout_due_signed_action_id_v1(
        ref,
        timeout_due_commitment=commitment,
        signed_action_id=action_id,
        authorization_evidence_identity=_sha("unused-preconsume-evidence"),
        pending_issuance_capability=capability,
    )
    assert type(observed) is not rt.TimeoutActionExecutionReceiptV1
    ownership = runtime.current_pending_issuance_capability_ownership_v1(
        capability
    )
    assert (
        ownership.status
        is rt.PendingIssuanceCapabilityStatusV1.CONTROLLER_OWNED_PENDING
    )
    assert _AUTHENTICATORS[runtime].anti_replay_state_identity_v1() == ledger_before
    aborted = runtime.abort_pending_timeout_issuance_capability_v1(capability)
    assert aborted.status is rt.PendingIssuanceCapabilityStatusV1.CONTROLLER_ABORTED
    with pytest.raises(rt.C8TimedSessionRuntimeError, match="duplicate abort"):
        runtime.abort_pending_timeout_issuance_capability_v1(capability)


def test_malformed_authenticator_return_without_consume_preserves_abort_ownership(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, _, ref, commitment = _due_runtime()
    action_id = "malformed-auth-return"
    capability = _pending_issuance_capability(
        runtime, ref, commitment, signed_action_id=action_id
    )
    authenticator = _AUTHENTICATORS[runtime]
    binding = runtime.expected_timeout_action_authentication_binding_v1(
        ref,
        timeout_due_commitment=commitment,
        signed_action_id=action_id,
        pending_issuance_capability=capability,
    )
    evidence = authenticator.authorize(binding)
    ledger_before = authenticator.anti_replay_state_identity_v1()

    monkeypatch.setattr(
        authenticator,
        "verify_and_consume_timeout_action_authorization_v1",
        lambda signed_action_id, evidence_identity, expected_binding: {
            "malformed": True
        },
    )
    with pytest.raises(rt.C8TimedSessionRuntimeError, match="未授权"):
        runtime.forward_timeout_due_signed_action_id_v1(
            ref,
            timeout_due_commitment=commitment,
            signed_action_id=action_id,
            authorization_evidence_identity=evidence,
            pending_issuance_capability=capability,
        )
    assert authenticator.anti_replay_state_identity_v1() == ledger_before
    assert (
        runtime.current_pending_issuance_capability_ownership_v1(
            capability
        ).status
        is rt.PendingIssuanceCapabilityStatusV1.CONTROLLER_OWNED_PENDING
    )
    assert (
        runtime.abort_pending_timeout_issuance_capability_v1(
            capability
        ).status
        is rt.PendingIssuanceCapabilityStatusV1.CONTROLLER_ABORTED
    )


def test_auth_consumed_capability_survives_rollback_and_cannot_abort_or_replay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, _, ref, commitment = _due_runtime()
    gameplay_snapshot = runtime.capture_transaction()
    action_id = "auth-consumed-capability"
    capability = _pending_issuance_capability(
        runtime, ref, commitment, signed_action_id=action_id
    )
    binding = runtime.expected_timeout_action_authentication_binding_v1(
        ref,
        timeout_due_commitment=commitment,
        signed_action_id=action_id,
        pending_issuance_capability=capability,
    )
    evidence = _AUTHENTICATORS[runtime].authorize(binding)

    def fail_receipt(
        self: rt.C8TimedSessionRuntimeV1, **kwargs: object
    ) -> rt.TimeoutActionExecutionReceiptV1:
        raise RuntimeError("forced receipt construction failure")

    monkeypatch.setattr(
        rt.C8TimedSessionRuntimeV1,
        "_build_timeout_execution_receipt",
        fail_receipt,
    )
    with pytest.raises(rt.C8TimedSessionRuntimeError):
        runtime.forward_timeout_due_signed_action_id_v1(
            ref,
            timeout_due_commitment=commitment,
            signed_action_id=action_id,
            authorization_evidence_identity=evidence,
            pending_issuance_capability=capability,
        )
    assert (
        runtime.current_pending_issuance_capability_ownership_v1(
            capability
        ).status
        is rt.PendingIssuanceCapabilityStatusV1.AUTH_EVIDENCE_CONSUMED
    )

    runtime.rollback(gameplay_snapshot)
    assert (
        runtime.current_pending_issuance_capability_ownership_v1(
            capability
        ).status
        is rt.PendingIssuanceCapabilityStatusV1.AUTH_EVIDENCE_CONSUMED
    )
    with pytest.raises(rt.C8TimedSessionRuntimeError, match="abort/consume"):
        runtime.abort_pending_timeout_issuance_capability_v1(capability)
    with pytest.raises(rt.C8TimedSessionRuntimeError, match="duplicate/replay"):
        runtime.forward_timeout_due_signed_action_id_v1(
            ref,
            timeout_due_commitment=commitment,
            signed_action_id=action_id,
            authorization_evidence_identity=evidence,
            pending_issuance_capability=capability,
        )


def test_successful_capability_forward_binds_receipt_and_consumes_one_shot() -> None:
    runtime, _, ref, commitment = _due_runtime()
    action_id = "capability-bound-timeout-action"
    capability = _pending_issuance_capability(
        runtime, ref, commitment, signed_action_id=action_id
    )
    binding = runtime.expected_timeout_action_authentication_binding_v1(
        ref,
        timeout_due_commitment=commitment,
        signed_action_id=action_id,
        pending_issuance_capability=capability,
    )
    evidence = _AUTHENTICATORS[runtime].authorize(binding)
    receipt = runtime.forward_timeout_due_signed_action_id_v1(
        ref,
        timeout_due_commitment=commitment,
        signed_action_id=action_id,
        authorization_evidence_identity=evidence,
        pending_issuance_capability=capability,
    )

    assert receipt.pending_issuance_capability_identity == capability.capability_identity
    ownership = runtime.current_pending_issuance_capability_ownership_v1(
        capability
    )
    assert (
        ownership.status
        is rt.PendingIssuanceCapabilityStatusV1.RECEIPT_COMMITTED_CONSUMED
    )
    assert ownership.committed_receipt_identity == receipt.receipt_identity
    runtime.close_window_by_timeout_receipt_v1(
        ref, execution_receipt=receipt
    )
    with pytest.raises(rt.C8TimedSessionRuntimeError, match="abort/consume"):
        runtime.abort_pending_timeout_issuance_capability_v1(capability)


def test_public_mutator_attempt_coverage_is_explicit_and_no_pause_clear_seam_exists() -> None:
    protected = {
        "issue_controller_callback_lease_v1",
        "begin_controller_callback_guard_v1",
        "register_pending_timeout_issuance_capability_v1",
        "abort_pending_timeout_issuance_capability_v1",
        "current_timeout_due_commitment_v1",
        "open_window",
        "continue_multi_step_obligation",
        "forward_on_time_signed_action_id",
        "forward_timeout_due_signed_action_id_v1",
        "continue_timeout_multi_step_obligation_v1",
        "ingest_virtual_time_input",
        "close_window_by_action",
        "close_window_by_timeout",
        "capture_transaction",
        "rollback",
        "cancel_window_to_pre_open_snapshot",
    }
    for name in protected:
        source = inspect.getsource(getattr(rt.C8TimedSessionRuntimeV1, name))
        assert "_record_public_operation_attempt" in source, name

    receipt_alias = inspect.getsource(
        rt.C8TimedSessionRuntimeV1.close_window_by_timeout_receipt_v1
    )
    assert "close_window_by_timeout" in receipt_alias
    public_names = {
        name
        for name in rt.C8TimedSessionRuntimeV1.__dict__
        if not name.startswith("_")
    }
    assert not {
        "pause",
        "resume",
        "clear_poison",
        "restore_snapshot",
    } & public_names
