# -*- coding: utf-8 -*-
"""Dedicated cheap tests for C8-C; no production gameplay adapter is used."""

from __future__ import annotations

import ast
import copy
from dataclasses import replace
import gc
import hashlib
import inspect
import json
from pathlib import Path
from typing import Any, Callable, Sequence

import pytest

from scripts.sgs_engine import c8_timed_session_runtime_v1 as rt
from scripts.sgs_engine import c8_timeout_controller_integration_v1 as ctl
from scripts.sgs_engine import c8_virtual_time_contract_v1 as c8


def _sha(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _canonical_identity(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


NONCE_ID = _sha("c8-c-test-runtime-nonce")
DRIVER_AUTHORITY_ID = _sha("c8-c-test-driver-authority")
PROFILE_ID = c8.ENGINEERING_TEST_PROFILE_V1.profile_identity


class FakeInnerAdapter:
    """Opaque mutable inner state implementing only the frozen C8-B protocol."""

    def __init__(self, *, label: str = "primary") -> None:
        self._adapter_identity = _sha(f"inner-adapter:{label}")
        self._session_binding_identity = _sha(f"inner-session:{label}")
        self.public_counter = 0
        self.secret_counter = 0
        self.inner_events: list[str] = []
        self.calls: list[str] = []
        self.apply_raises = False
        self.restore_raises = False
        self.restore_faults: list[str] = []
        self.apply_reentrant_call: Callable[[], object] | None = None
        self.opaque_token_secret = f"OPAQUE-INNER-TOKEN:{label}:DO-NOT-REPR"

    def adapter_identity_v1(self) -> str:
        self.calls.append("adapter_identity_v1")
        return self._adapter_identity

    def session_binding_identity_v1(self) -> str:
        self.calls.append("session_binding_identity_v1")
        return self._session_binding_identity

    def public_state_identity_v1(self) -> str:
        self.calls.append("public_state_identity_v1")
        return _sha(f"inner-public:{self.public_counter}")

    def authoritative_state_identity_v1(self) -> str:
        self.calls.append("authoritative_state_identity_v1")
        return _sha(
            f"inner-authoritative:{self.public_counter}:{self.secret_counter}"
        )

    def capture_transaction_snapshot_v1(self) -> object:
        self.calls.append("capture_transaction_snapshot_v1")
        return (
            self.public_counter,
            self.secret_counter,
            tuple(self.inner_events),
            self._adapter_identity,
            self._session_binding_identity,
            self.opaque_token_secret,
        )

    def snapshot_token_identity_v1(self, token: object) -> str:
        self.calls.append("snapshot_token_identity_v1")
        return _sha(json.dumps(token, ensure_ascii=False, separators=(",", ":")))

    def restore_transaction_snapshot_v1(self, token: object) -> None:
        self.calls.append("restore_transaction_snapshot_v1")
        if self.restore_raises:
            raise RuntimeError("synthetic inner restore failure")
        (
            public,
            secret,
            events,
            adapter_identity,
            session_identity,
            token_secret,
        ) = token  # type: ignore[misc]
        if token_secret != self.opaque_token_secret:
            raise RuntimeError("synthetic snapshot owner mismatch")
        self.public_counter = public
        self.secret_counter = secret
        self.inner_events = list(events)
        self._adapter_identity = adapter_identity
        self._session_binding_identity = session_identity
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
            else:  # pragma: no cover - fixture misuse
                raise AssertionError(f"unknown restore fault: {fault}")

    def apply_signed_action_id_v1(self, signed_action_id: str) -> None:
        self.calls.append(f"apply_signed_action_id_v1:{signed_action_id}")
        if self.apply_reentrant_call is not None:
            self.apply_reentrant_call()
        if self.apply_raises:
            raise RuntimeError("synthetic inner action failure")
        self.public_counter += 1
        self.secret_counter += 1
        self.inner_events.append(f"signed-action:{signed_action_id}")


class FakeAuthenticator:
    """External one-shot C8-B authority; consumed evidence is non-rollback state."""

    def __init__(self, *, label: str = "primary") -> None:
        self._identity = _sha(f"authenticator:{label}")
        self._next_authorization = 0
        self._authorized: dict[str, str] = {}
        self.consumed_evidence: set[str] = set()
        self.revoked_evidence: set[str] = set()
        self._consumed_epoch = 0
        self.calls: list[str] = []
        self.timeout_verify_raises_before_consume = False
        self.timeout_verify_raises_after_consume = False

    def authenticator_identity_v1(self) -> str:
        self.calls.append("authenticator_identity_v1")
        return self._identity

    def anti_replay_state_identity_v1(self) -> str:
        self.calls.append("anti_replay_state_identity_v1")
        return _sha(
            json.dumps(
                {
                    "consumed_epoch": self._consumed_epoch,
                    "consumed_evidence": sorted(self.consumed_evidence),
                },
                sort_keys=True,
                separators=(",", ":"),
            )
        )

    def authorize(self, request_binding_identity: str) -> str:
        evidence = _sha(
            f"opaque-auth:{self._identity}:{self._next_authorization}:"
            f"{request_binding_identity}"
        )
        self._next_authorization += 1
        self._authorized[evidence] = request_binding_identity
        return evidence

    def authorize_timeout_action(
        self, signed_action_id: str, issuance_request_binding: str
    ) -> str:
        evidence = _sha(
            f"opaque-timeout-auth:{self._identity}:{self._next_authorization}:"
            f"{signed_action_id}:{issuance_request_binding}"
        )
        self._next_authorization += 1
        self._authorized[evidence] = (
            f"timeout-action:{signed_action_id}:{issuance_request_binding}"
        )
        return evidence

    def verify_and_consume_advance_authorization_v1(
        self,
        advance_input: c8.VirtualTimeAdvanceInputV1,
        expected_request_binding_identity: str,
    ) -> bool:
        self.calls.append("verify_and_consume_advance_authorization_v1")
        evidence = advance_input.authentication_evidence_identity
        expected = self._authorized.pop(evidence, None)
        if expected is None:
            return False
        self.consumed_evidence.add(evidence)
        self._consumed_epoch += 1
        return expected == expected_request_binding_identity

    def verify_and_consume_timeout_action_authorization_v1(
        self,
        signed_action_id: str,
        authorization_evidence_identity: str,
        expected_request_binding_identity: str,
    ) -> bool:
        self.calls.append(
            f"verify_and_consume_timeout_action_authorization_v1:{signed_action_id}"
        )
        if self.timeout_verify_raises_before_consume:
            raise RuntimeError("synthetic timeout verifier failed before consume")
        expected = self._authorized.pop(authorization_evidence_identity, None)
        if expected is None:
            return False
        self.consumed_evidence.add(authorization_evidence_identity)
        self._consumed_epoch += 1
        if self.timeout_verify_raises_after_consume:
            raise RuntimeError("synthetic timeout verifier failed after consume")
        return expected == expected_request_binding_identity or expected.startswith(
            f"timeout-action:{signed_action_id}:"
        )

    def revoke_unconsumed(self, evidence: str) -> bool:
        """Revoke adapter capability without advancing C8-B's consumed ledger."""

        if self._authorized.pop(evidence, None) is None:
            return False
        self.revoked_evidence.add(evidence)
        return True


class SyntheticPublicAuthorityAdapter:
    """Conforming public-only C8-C harness with explicit security state."""

    def __init__(
        self,
        runtime: rt.C8TimedSessionRuntimeV1,
        authenticator: FakeAuthenticator,
        ref: rt.WindowAuthorityRefV1,
        *,
        controller_identity: str,
        families_by_step: Sequence[Sequence[c8.PublicActionFamilyV1]],
        completion_by_step: Sequence[bool] = (True,),
        reuse_public_reference_as_signed_action: bool = False,
    ) -> None:
        assert families_by_step
        self.runtime = runtime
        self.authenticator = authenticator
        self.ref = ref
        self.controller_identity = controller_identity
        self.families_by_step = tuple(tuple(items) for items in families_by_step)
        self.completion_by_step = tuple(completion_by_step)
        self.reuse_public_reference_as_signed_action = (
            reuse_public_reference_as_signed_action
        )
        self.fetch_count = 0
        self.issue_count = 0
        self.identity_bundle_count = 0
        self.calls: list[str] = []
        self.guard_observations: list[tuple[str, bool]] = []
        self.current_snapshot: ctl.AdapterPublicLegalActionsSnapshotV1 | None = None
        self.issuances: list[ctl.SignedActionIssuanceEvidenceV1] = []
        self.window_observations: list[tuple[int, int, int, str]] = []
        self.invalidations: list[
            ctl.UnforwardedIssuanceInvalidationEvidenceV1
        ] = []
        self.failed_issuance_recoveries: list[
            ctl.FailedIssuanceRecoveryEvidenceV1
        ] = []
        self._confirmed_evidence: set[str] = set()
        self._invalidated_evidence: set[str] = set()
        self._external_capabilities: dict[
            int, tuple[object, ctl.SignedActionIssuanceEvidenceV1]
        ] = {}
        self.fault: str | None = None
        self.tamper_field: str | None = None
        self.tamper_value: object | None = None
        self.drift_field: str | None = None
        self.drift_on_bundle = 2
        self.reentrant_call: Callable[[], object] | None = None
        self.replay_issuance: ctl.SignedActionIssuanceEvidenceV1 | None = None
        self.replay_previous_issuance_at_issue_count: int | None = None
        self.replay_receipt: rt.TimeoutActionExecutionReceiptV1 | None = None
        self.raised_after_advance_evidence: str | None = None
        self.failed_recovery_raises = False
        self.tamper_failed_recovery = False

    def _record_guard(self, callback_name: str) -> None:
        self.guard_observations.append(
            (
                callback_name,
                self.runtime.controller_callback_security_audit_v1().guard_active,
            )
        )

    def _security_ledger_identity(self) -> str:
        return _sha(
            json.dumps(
                {
                    "confirmed": sorted(self._confirmed_evidence),
                    "invalidated": sorted(self._invalidated_evidence),
                },
                sort_keys=True,
                separators=(",", ":"),
            )
        )

    def _drift(self, field: str, current: str) -> str:
        if (
            self.drift_field == field
            and self.identity_bundle_count >= self.drift_on_bundle
        ):
            return _sha(f"stable-drift:{field}:{current}")
        return current

    def current_adapter_identity_v1(self) -> str:
        self.identity_bundle_count += 1
        self.calls.append("identity:adapter")
        return self._drift("adapter", self.runtime.state.inner_adapter_identity)

    def current_session_identity_v1(self) -> str:
        self.calls.append("identity:session")
        return self._drift("session", self.runtime.state.inner_session_binding_identity)

    def current_controller_identity_v1(self) -> str:
        self.calls.append("identity:controller")
        return self._drift("controller", self.controller_identity)

    def current_public_state_identity_v1(self) -> str:
        self.calls.append("identity:public")
        return self._drift("public", self.runtime.state.inner_public_state_identity)

    def current_authoritative_state_identity_v1(self) -> str:
        self.calls.append("identity:authoritative")
        return self._drift(
            "authoritative", self.runtime.state.inner_authoritative_state_identity
        )

    def current_issuance_authority_identity_v1(self) -> str:
        self.calls.append("identity:issuance-authority")
        return self._drift(
            "issuance_authority", self.runtime.state.input_authenticator_identity
        )

    def current_issuance_security_ledger_identity_v1(self) -> str:
        self.calls.append("identity:issuance-security-ledger")
        return self._drift("issuance_security_ledger", self._security_ledger_identity())

    def current_consumed_authorization_ledger_identity_v1(self) -> str:
        """Expose B authenticator anti-replay state without private payloads."""

        self.calls.append("identity:consumed-authorization-ledger")
        return self._drift(
            "consumed_authorization_ledger",
            self.authenticator.anti_replay_state_identity_v1(),
        )

    def current_public_legal_set_snapshot_identity_v1(self) -> str:
        self.calls.append("identity:legal-set-snapshot")
        current = (
            _sha("no-current-c8-c-legal-set")
            if self.current_snapshot is None
            else self.current_snapshot.snapshot_identity
        )
        return self._drift("legal_set_snapshot", current)

    def current_canonical_public_ordering_identity_v1(self) -> str:
        self.calls.append("identity:ordering")
        current = (
            _sha("no-current-c8-c-ordering")
            if self.current_snapshot is None
            else self.current_snapshot.canonical_public_ordering_identity
        )
        return self._drift("ordering", current)

    def _families_for_fetch(self) -> tuple[c8.PublicActionFamilyV1, ...]:
        index = min(self.fetch_count, len(self.families_by_step) - 1)
        return self.families_by_step[index]

    def fresh_public_legal_actions_v1(
        self,
    ) -> ctl.AdapterPublicLegalActionsSnapshotV1:
        self.calls.append("fresh-public-legal-set")
        self._record_guard("fresh-public-legal-set")
        if self.fault == "legal_fetch":
            raise RuntimeError("synthetic legal-set fetch failure")
        if self.reentrant_call is not None and self.fault == "reenter_from_legal_fetch":
            self.reentrant_call()
        active = _active_window(self.runtime)
        self.window_observations.append(
            (
                self.runtime.state.virtual_time_state.now_tick,
                active.opened_at,
                active.deadline_at,
                active.window_id,
            )
        )
        families = self._families_for_fetch()
        fetch_index = self.fetch_count
        candidates = tuple(
            c8.PublicLegalActionCandidateV1.build(
                window_id=active.window_id,
                actor_id=active.actor_id,
                decision_identity=active.decision_identity,
                obligation_identity=active.obligation_identity,
                public_ordinal=index,
                action_id=f"c8-c-public-ref-{fetch_index}-{index}",
                action_family=family,
            )
            for index, family in enumerate(families)
        )
        public_set = c8.PublicLegalSetProjectionV1.build(
            window_id=active.window_id,
            actor_id=active.actor_id,
            decision_identity=active.decision_identity,
            obligation_identity=active.obligation_identity,
            actions=candidates,
            ordering_contract_id=c8.PUBLIC_ORDERING_CONTRACT_ID,
        )
        snapshot = ctl.build_adapter_public_legal_actions_snapshot_v1(
            public_legal_set=public_set,
            runtime_instance_identity=self.runtime.state.runtime_instance_identity,
            window_authority_ref_identity=self.ref.authority_ref_identity,
            session_identity=self.runtime.state.inner_session_binding_identity,
            controller_identity=self.controller_identity,
            adapter_identity=self.runtime.state.inner_adapter_identity,
            public_state_identity=self.runtime.state.inner_public_state_identity,
            authoritative_state_identity=(
                self.runtime.state.inner_authoritative_state_identity
            ),
            issuance_security_ledger_identity=self._security_ledger_identity(),
        )
        self.fetch_count += 1
        if self.fault == "tamper_envelope" and self.tamper_field is not None:
            snapshot = _unsafe_dataclass_copy(
                snapshot, **{self.tamper_field: self.tamper_value}
            )  # type: ignore[assignment]
        self.current_snapshot = snapshot
        return snapshot

    def confirm_and_issue_signed_action_v1(
        self,
        candidate_reference: str,
        public_ordinal: int,
        legal_set_identity: str,
        timeout_auth_binding: str,
        timeout_due_commitment_identity: str,
    ) -> ctl.SignedActionIssuanceEvidenceV1:
        self.calls.append("confirm-and-issue")
        self._record_guard("confirm-and-issue")
        if self.fault == "issue_error":
            raise RuntimeError("synthetic issuance failure")
        if self.reentrant_call is not None and self.fault == "reenter_from_issue":
            self.reentrant_call()
        snapshot = self.current_snapshot
        if snapshot is None:
            raise RuntimeError("missing current legal-set snapshot")
        matches = tuple(
            candidate
            for candidate in snapshot.public_legal_set.actions
            if candidate.action_id == candidate_reference
            and candidate.public_ordinal == public_ordinal
        )
        if len(matches) != 1:
            raise RuntimeError("candidate is not a unique member of current legal set")
        candidate = matches[0]
        if (
            self.replay_previous_issuance_at_issue_count is not None
            and self.issue_count >= self.replay_previous_issuance_at_issue_count
            and self.issuances
        ):
            replay = self.issuances[0]
            self.issue_count += 1
            self.issuances.append(replay)
            return replay
        if self.replay_issuance is not None:
            self.issue_count += 1
            self.issuances.append(self.replay_issuance)
            return self.replay_issuance
        ledger_before = self._security_ledger_identity()
        signed_action_id = (
            candidate.action_id
            if self.reuse_public_reference_as_signed_action
            else f"c8-c-signed-action-{self.issue_count}-{candidate.public_ordinal}"
        )
        evidence = self.authenticator.authorize_timeout_action(
            signed_action_id, timeout_auth_binding
        )
        self._confirmed_evidence.add(evidence)
        ledger_after = self._security_ledger_identity()
        if self.fault == "issue_after_external_advance_error":
            self.raised_after_advance_evidence = evidence
            raise RuntimeError("synthetic issuance failed after security advance")
        external_capability = object()
        external_capability_identity = _sha(
            f"external-capability:{evidence}:{self.issue_count}"
        )
        completion_index = min(
            self.issue_count, len(self.completion_by_step) - 1
        )
        issuance = ctl.build_signed_action_issuance_evidence_v1(
            signed_action_id=signed_action_id,
            signed_action_id_commitment=ctl.signed_action_id_commitment_v1(
                signed_action_id
            ),
            external_capability_identity=external_capability_identity,
            public_action_reference=candidate.action_id,
            public_ordinal=candidate.public_ordinal,
            candidate_identity=candidate.candidate_identity,
            action_family=candidate.action_family.value,
            legal_set_identity=legal_set_identity,
            canonical_public_ordering_identity=(
                snapshot.canonical_public_ordering_identity
            ),
            timeout_due_commitment_identity=timeout_due_commitment_identity,
            authorization_binding_identity=timeout_auth_binding,
            issuance_authority_identity=(
                self.runtime.state.input_authenticator_identity
            ),
            authorization_evidence_identity=evidence,
            runtime_instance_identity=self.runtime.state.runtime_instance_identity,
            window_authority_ref_identity=self.ref.authority_ref_identity,
            window_id=self.ref.window_id,
            session_identity=self.runtime.state.inner_session_binding_identity,
            controller_identity=self.controller_identity,
            adapter_identity=self.runtime.state.inner_adapter_identity,
            public_state_identity=snapshot.public_state_identity,
            authoritative_state_identity=(
                snapshot.authoritative_state_identity
            ),
            issuance_security_ledger_before_identity=ledger_before,
            issuance_security_ledger_after_identity=ledger_after,
            obligation_completed=self.completion_by_step[completion_index],
            external_capability=external_capability,
        )
        self._external_capabilities[id(external_capability)] = (
            external_capability,
            issuance,
        )
        self.issue_count += 1
        if self.replay_issuance is not None:
            issuance = self.replay_issuance
        elif self.fault == "tamper_issuance" and self.tamper_field is not None:
            issuance = _unsafe_dataclass_copy(
                issuance, **{self.tamper_field: self.tamper_value}
            )  # type: ignore[assignment]
        self.issuances.append(issuance)
        return issuance

    def abort_pending_issuance_v1(
        self,
        external_capability: object,
    ) -> ctl.UnforwardedIssuanceInvalidationEvidenceV1:
        self.calls.append("invalidate-unforwarded-issuance")
        self._record_guard("abort-pending-issuance")
        if self.fault == "invalidation_error":
            raise RuntimeError("synthetic issuance invalidation failure")
        record = self._external_capabilities.get(id(external_capability))
        if record is None or record[0] is not external_capability:
            raise RuntimeError("unknown external issuance capability")
        issuance_evidence = record[1]
        ledger_before = self._security_ledger_identity()
        if not self.authenticator.revoke_unconsumed(
            issuance_evidence.authorization_evidence_identity
        ):
            raise RuntimeError("authorization evidence was not pending")
        self._invalidated_evidence.add(
            issuance_evidence.authorization_evidence_identity
        )
        self._external_capabilities.pop(id(external_capability), None)
        ledger_after = self._security_ledger_identity()
        invalidation = ctl.build_unforwarded_issuance_invalidation_evidence_v1(
            issuance_identity=issuance_evidence.issuance_identity,
            authorization_evidence_identity=(
                issuance_evidence.authorization_evidence_identity
            ),
            runtime_instance_identity=issuance_evidence.runtime_instance_identity,
            window_authority_ref_identity=(
                issuance_evidence.window_authority_ref_identity
            ),
            session_identity=issuance_evidence.session_identity,
            controller_identity=issuance_evidence.controller_identity,
            adapter_identity=issuance_evidence.adapter_identity,
            security_ledger_before_identity=ledger_before,
            security_ledger_after_identity=ledger_after,
            invalidated=True,
        )
        self.invalidations.append(invalidation)
        return invalidation

    def recover_failed_issuance_attempt_v1(
        self,
        *,
        issuance_security_ledger_before_identity: str,
        issuance_security_ledger_observed_after_failure_identity: str,
        transaction_identity: str,
        legal_set_identity: str,
        candidate_reference: str,
        public_ordinal: int,
        timeout_auth_binding: str,
    ) -> ctl.FailedIssuanceRecoveryEvidenceV1:
        """Revoke adapter capabilities created by a confirm call that raised.

        This security recovery deliberately does not advance C8-B's consumed
        authorization ledger.  Only a real B forward may do that.
        """

        self.calls.append("recover-failed-issuance-attempt")
        self._record_guard("recover-failed-issuance-attempt")
        if self.failed_recovery_raises:
            raise RuntimeError("synthetic failed-issuance recovery failure")
        observed = self._security_ledger_identity()
        if observed != issuance_security_ledger_observed_after_failure_identity:
            raise RuntimeError("failed-confirm observed ledger mismatch")
        pending = tuple(
            sorted(
                evidence
                for evidence in self._confirmed_evidence
                if evidence not in self._invalidated_evidence
                and evidence not in self.authenticator.consumed_evidence
                and evidence not in self.authenticator.revoked_evidence
            )
        )
        if not pending:
            raise RuntimeError("failed confirm left no recoverable capability")
        for evidence in pending:
            if not self.authenticator.revoke_unconsumed(evidence):
                raise RuntimeError("failed-confirm capability was not pending")
            self._invalidated_evidence.add(evidence)
        after = self._security_ledger_identity()
        recovery = ctl.build_failed_issuance_recovery_evidence_v1(
            transaction_identity=transaction_identity,
            legal_set_identity=legal_set_identity,
            candidate_reference=candidate_reference,
            public_ordinal=public_ordinal,
            timeout_auth_binding=timeout_auth_binding,
            runtime_instance_identity=self.runtime.state.runtime_instance_identity,
            window_authority_ref_identity=self.ref.authority_ref_identity,
            session_identity=self.runtime.state.inner_session_binding_identity,
            controller_identity=self.controller_identity,
            adapter_identity=self.runtime.state.inner_adapter_identity,
            security_ledger_before_identity=(
                issuance_security_ledger_before_identity
            ),
            security_ledger_observed_after_failure_identity=observed,
            security_ledger_after_recovery_identity=after,
            recovered_evidence_set_identity=_sha(
                json.dumps(pending, separators=(",", ":"))
            ),
            recovered_evidence_count=len(pending),
            recovered=True,
        )
        if self.tamper_failed_recovery:
            recovery = _unsafe_dataclass_copy(
                recovery, recovery_identity=_sha("forged-recovery-self-identity")
            )
        self.failed_issuance_recoveries.append(recovery)
        return recovery


def _runtime(
    *,
    label: str = "primary",
) -> tuple[rt.C8TimedSessionRuntimeV1, FakeInnerAdapter, FakeAuthenticator]:
    inner = FakeInnerAdapter(label=label)
    authenticator = FakeAuthenticator(label=label)
    runtime = rt.C8TimedSessionRuntimeV1(
        inner_adapter=inner,
        input_authenticator=authenticator,
        instance_nonce_identity=_sha(f"{NONCE_ID}:{label}"),
        input_source_id=f"authenticated-c8-c-test-driver-{label}",
        driver_authority_identity=_sha(f"{DRIVER_AUTHORITY_ID}:{label}"),
    )
    return runtime, inner, authenticator


def _open(
    runtime: rt.C8TimedSessionRuntimeV1,
    *,
    label: str = "root",
    kind: c8.TimedWindowKindV1 = c8.TimedWindowKindV1.PLAY,
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
        expected_parent_ref=None,
    )


def _advance_input(
    runtime: rt.C8TimedSessionRuntimeV1,
    authenticator: FakeAuthenticator,
    *,
    requested_tick: int,
) -> c8.VirtualTimeAdvanceInputV1:
    state = runtime.state
    active = state.virtual_time_state.window_stack.active_window
    assert active is not None
    evidence = authenticator.authorize(
        runtime.expected_advance_authentication_binding(
            requested_tick=requested_tick
        )
    )
    return c8.VirtualTimeAdvanceInputV1.issue(
        input_seq=state.virtual_time_state.next_input_seq,
        source_id=state.input_source_id,
        domain_id=c8.CLOCK_DOMAIN_ID,
        window_id=active.window_id,
        requested_tick=requested_tick,
        authentication_evidence_identity=evidence,
    )


def _advance_to(
    runtime: rt.C8TimedSessionRuntimeV1,
    authenticator: FakeAuthenticator,
    requested_tick: int,
) -> rt.TimedRuntimeAdvanceResultV1:
    state = runtime.state
    return runtime.ingest_virtual_time_input(
        _advance_input(runtime, authenticator, requested_tick=requested_tick),
        expected_previous_input_chain_tip=state.input_chain_tip,
        duration_profile_identity=PROFILE_ID,
    )


def _active_window(runtime: rt.C8TimedSessionRuntimeV1) -> c8.TimedDecisionWindowV1:
    active = runtime.state.virtual_time_state.window_stack.active_window
    assert active is not None
    return active


def _open_and_due(
    *,
    label: str = "primary",
    kind: c8.TimedWindowKindV1 = c8.TimedWindowKindV1.PLAY,
) -> tuple[
    rt.C8TimedSessionRuntimeV1,
    FakeInnerAdapter,
    FakeAuthenticator,
    rt.WindowAuthorityRefV1,
    rt.TimeoutDueCommitmentV1,
]:
    runtime, inner, authenticator = _runtime(label=label)
    ref = _open(runtime, label=label, kind=kind)
    deadline = _active_window(runtime).deadline_at
    result = _advance_to(runtime, authenticator, deadline)
    assert result.derived_deadline is not None
    commitment = runtime.current_timeout_due_commitment_v1(ref)
    return runtime, inner, authenticator, ref, commitment


def _json_round_trip(value: object) -> object:
    return json.loads(json.dumps(value, ensure_ascii=False, sort_keys=True))


def _controller_harness(
    *,
    label: str = "primary",
    kind: c8.TimedWindowKindV1 = c8.TimedWindowKindV1.PLAY,
    families_by_step: Sequence[Sequence[c8.PublicActionFamilyV1]] = (
        (c8.PublicActionFamilyV1.END_PLAY_PHASE,),
    ),
    completion_by_step: Sequence[bool] = (True,),
) -> tuple[
    ctl.TimeoutResolverControllerIntegrationV1,
    SyntheticPublicAuthorityAdapter,
    rt.C8TimedSessionRuntimeV1,
    FakeInnerAdapter,
    FakeAuthenticator,
    rt.WindowAuthorityRefV1,
    rt.TimeoutDueCommitmentV1,
]:
    runtime, inner, authenticator, ref, commitment = _open_and_due(
        label=label, kind=kind
    )
    controller_identity = _sha(f"c8-c-controller-instance:{label}")
    adapter = SyntheticPublicAuthorityAdapter(
        runtime,
        authenticator,
        ref,
        controller_identity=controller_identity,
        families_by_step=families_by_step,
        completion_by_step=completion_by_step,
    )
    controller = ctl.TimeoutResolverControllerIntegrationV1(
        runtime,
        adapter,
        controller_instance_identity=controller_identity,
    )
    return (
        controller,
        adapter,
        runtime,
        inner,
        authenticator,
        ref,
        commitment,
    )


def _gameplay_snapshot(
    runtime: rt.C8TimedSessionRuntimeV1,
    inner: FakeInnerAdapter,
) -> tuple[object, int, int, tuple[str, ...]]:
    return (
        runtime.state,
        inner.public_counter,
        inner.secret_counter,
        tuple(inner.inner_events),
    )


def _unsafe_dataclass_copy(value: object, **changes: object) -> object:
    forged = copy.copy(value)
    for field, replacement in changes.items():
        object.__setattr__(forged, field, replacement)
    return forged


def _runtime_window_invariants(
    runtime: rt.C8TimedSessionRuntimeV1,
) -> tuple[int, int, int, str, str]:
    active = _active_window(runtime)
    return (
        runtime.state.virtual_time_state.now_tick,
        active.opened_at,
        active.deadline_at,
        active.window_id,
        active.obligation_identity,
    )


def _assert_public_only(value: object) -> None:
    """Reject key/name/value leakage without banning opaque public hashes."""

    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True).lower()
    for forbidden in (
        "opaque-inner-token",
        "secret_counter",
        "private_payload",
        "hand_cards",
        "card_payload",
    ):
        assert forbidden not in encoded


def test_module_has_no_rng_wall_clock_or_private_accessor_dependency() -> None:
    source_path = Path(inspect.getsourcefile(ctl) or "")
    source = source_path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    forbidden_imports = {"random", "secrets", "time", "datetime", "uuid"}
    imported: set[str] = set()
    called_attributes: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(item.name.split(".", 1)[0] for item in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".", 1)[0])
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
        ):
            called_attributes.add(node.func.attr)
    assert imported.isdisjoint(forbidden_imports)
    assert not any("private" in name.lower() for name in called_attributes)
    assert "apply_signed_action_id_v1" not in called_attributes
    for forbidden_shared_module in (
        "production_batch",
        "production_replay",
        "authoritative_no_skill_full_game",
    ):
        assert forbidden_shared_module not in source


def test_public_adapter_protocol_has_no_private_payload_accessor() -> None:
    public_methods = {
        name
        for name, member in inspect.getmembers(
            ctl.PublicLegalActionsIssuanceAdapterV1
        )
        if callable(member) and not name.startswith("__")
    }
    assert public_methods
    assert not any("private" in name.lower() for name in public_methods)
    assert {
        "fresh_public_legal_actions_v1",
        "confirm_and_issue_signed_action_v1",
        "abort_pending_issuance_v1",
        "recover_failed_issuance_attempt_v1",
        "current_adapter_identity_v1",
        "current_session_identity_v1",
        "current_controller_identity_v1",
        "current_public_state_identity_v1",
        "current_authoritative_state_identity_v1",
        "current_issuance_authority_identity_v1",
        "current_issuance_security_ledger_identity_v1",
        "current_consumed_authorization_ledger_identity_v1",
        "current_public_legal_set_snapshot_identity_v1",
        "current_canonical_public_ordering_identity_v1",
    } <= public_methods
    assert "verify_execution_receipt_lineage_v1" not in public_methods


def test_legacy_on_time_forward_remains_rejected_at_exact_deadline() -> None:
    runtime, inner, _, ref, _ = _open_and_due(label="on-time-exact-deadline")
    pre = _gameplay_snapshot(runtime, inner)
    with pytest.raises(rt.C8TimedSessionRuntimeError):
        runtime.forward_on_time_signed_action_id(
            ref,
            signed_action_id="must-not-bypass-timeout-path",
        )
    assert _gameplay_snapshot(runtime, inner) == pre


@pytest.mark.parametrize("case", ["before-deadline", "missing", "forged-copy", "stale"])
def test_timeout_due_precondition_fails_closed_without_adapter_calls(case: str) -> None:
    runtime, inner, authenticator = _runtime(label=f"precondition-{case}")
    kind = (
        c8.TimedWindowKindV1.MULTI_STEP_OBLIGATION
        if case == "stale"
        else c8.TimedWindowKindV1.PLAY
    )
    ref = _open(runtime, label=f"precondition-{case}", kind=kind)
    controller_identity = _sha(f"c8-c-controller:precondition:{case}")
    adapter = SyntheticPublicAuthorityAdapter(
        runtime,
        authenticator,
        ref,
        controller_identity=controller_identity,
        families_by_step=((c8.PublicActionFamilyV1.END_PLAY_PHASE,),),
    )
    controller = ctl.TimeoutResolverControllerIntegrationV1(
        runtime,
        adapter,
        controller_instance_identity=controller_identity,
    )
    supplied: object = None
    if case in {"missing", "forged-copy", "stale"}:
        deadline = _active_window(runtime).deadline_at
        _advance_to(runtime, authenticator, deadline)
        if case != "missing":
            live = runtime.current_timeout_due_commitment_v1(ref)
            if case == "forged-copy":
                supplied = rt.TimeoutDueCommitmentV1.from_dict(live.to_dict())
            else:
                supplied = live
                signed_action_id = "stale-commitment-progress-action"
                binding = runtime.expected_timeout_action_authentication_binding_v1(
                    ref,
                    timeout_due_commitment=live,
                    signed_action_id=signed_action_id,
                )
                receipt = runtime.forward_timeout_due_signed_action_id_v1(
                    ref,
                    timeout_due_commitment=live,
                    signed_action_id=signed_action_id,
                    authorization_evidence_identity=authenticator.authorize(binding),
                )
                runtime.continue_timeout_multi_step_obligation_v1(
                    ref,
                    execution_receipt=receipt,
                    expected_step_index=0,
                    logical_step_identity=_sha("make-supplied-commitment-stale"),
                )
    pre = _gameplay_snapshot(runtime, inner)
    result = controller.resolve_timeout_v1(
        ref, timeout_due_commitment=supplied
    )
    assert result.result_kind == ctl.ControllerResultKindV1.FAILED_ROLLED_BACK.value
    assert result.step_count == 0
    assert adapter.calls == []
    assert _gameplay_snapshot(runtime, inner) == pre


def test_play_end_phase_happy_path_uses_full_authority_pipeline() -> None:
    controller, adapter, runtime, inner, _, ref, commitment = _controller_harness()
    result = controller.resolve_timeout_v1(
        ref, timeout_due_commitment=commitment
    )
    assert result.result_kind == ctl.ControllerResultKindV1.RESOLVED_SINGLE.value
    assert result.reason == "TIMEOUT_RESOLUTION_COMMITTED"
    assert result.step_count == 1
    assert result.resolution_tick == result.deadline_at == 100
    assert runtime.active_window_ref() is None
    assert inner.public_counter == inner.secret_counter == 1
    assert len(adapter.issuances) == 1
    assert tuple(event.event_kind for event in controller.public_event_trace_v1()) == (
        ctl.ControllerEventKindV1.RESOLUTION_STARTED.value,
        ctl.ControllerEventKindV1.LEGAL_SET_BOUND.value,
        ctl.ControllerEventKindV1.FALLBACK_SELECTED.value,
        ctl.ControllerEventKindV1.ISSUANCE_BOUND.value,
        ctl.ControllerEventKindV1.RECEIPT_BOUND.value,
        ctl.ControllerEventKindV1.WINDOW_RESOLVED.value,
    )
    assert adapter.calls.index("fresh-public-legal-set") < adapter.calls.index(
        "confirm-and-issue"
    )
    assert "verify-receipt-lineage" not in adapter.calls
    assert adapter.guard_observations == [
        ("fresh-public-legal-set", True),
        ("confirm-and-issue", True),
    ]
    assert len(result.receipt_identities) == 1
    assert (
        result.selected_actions[0].signed_action_id
        != result.selected_actions[0].public_action_reference
    )
    _assert_public_only(result.to_public_dict_v1())


def test_fresh_confirmed_production_style_signed_id_may_equal_public_reference() -> None:
    runtime, inner, authenticator, ref, commitment = _open_and_due(
        label="production-signed-id-is-public-reference"
    )
    controller_identity = _sha("c8-c-controller:production-signed-reference")
    adapter = SyntheticPublicAuthorityAdapter(
        runtime,
        authenticator,
        ref,
        controller_identity=controller_identity,
        families_by_step=((c8.PublicActionFamilyV1.END_PLAY_PHASE,),),
        reuse_public_reference_as_signed_action=True,
    )
    controller = ctl.TimeoutResolverControllerIntegrationV1(
        runtime,
        adapter,
        controller_instance_identity=controller_identity,
    )

    result = controller.resolve_timeout_v1(
        ref, timeout_due_commitment=commitment
    )

    assert result.result_kind == ctl.ControllerResultKindV1.RESOLVED_SINGLE.value
    selected = result.selected_actions[0]
    assert selected.signed_action_id == selected.public_action_reference
    assert inner.public_counter == inner.secret_counter == 1
    _assert_public_only(result.to_public_dict_v1())


def test_pending_issuance_ownership_transitions_only_at_b_forward(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller, _, runtime, _, _, ref, commitment = _controller_harness(
        label="ownership-transition"
    )
    original = rt.C8TimedSessionRuntimeV1.forward_timeout_due_signed_action_id_v1
    observations: list[
        tuple[
            rt.PendingIssuanceCapabilityOwnershipV1,
            rt.PendingIssuanceCapabilityOwnershipV1,
        ]
    ] = []

    def observe_ownership(
        runtime_self: rt.C8TimedSessionRuntimeV1,
        *args: object,
        **kwargs: object,
    ) -> rt.TimeoutActionExecutionReceiptV1:
        capability = kwargs["pending_issuance_capability"]
        before = runtime_self.current_pending_issuance_capability_ownership_v1(
            capability
        )
        receipt = original(runtime_self, *args, **kwargs)  # type: ignore[arg-type]
        after = runtime_self.current_pending_issuance_capability_ownership_v1(
            capability
        )
        observations.append((before, after))
        return receipt

    monkeypatch.setattr(
        rt.C8TimedSessionRuntimeV1,
        "forward_timeout_due_signed_action_id_v1",
        observe_ownership,
    )
    result = controller.resolve_timeout_v1(ref, timeout_due_commitment=commitment)
    assert result.result_kind == ctl.ControllerResultKindV1.RESOLVED_SINGLE.value
    before, after = observations[0]
    assert before.status is rt.PendingIssuanceCapabilityStatusV1.CONTROLLER_OWNED_PENDING
    assert after.status is rt.PendingIssuanceCapabilityStatusV1.RECEIPT_COMMITTED_CONSUMED
    assert after.committed_receipt_identity == result.receipt_identities[0]


def test_nested_timeout_close_commits_then_resumes_parent_window() -> None:
    runtime, inner, authenticator = _runtime(label="nested-timeout-close")
    parent_ref = _open(
        runtime,
        label="nested-parent",
        kind=c8.TimedWindowKindV1.PLAY,
        actor="p1",
    )
    parent_before_child = _active_window(runtime)
    child_ref = runtime.open_window(
        actor_id="p2",
        window_kind=c8.TimedWindowKindV1.OPTIONAL_RESPONSE,
        decision_identity=_sha("nested-child-decision"),
        obligation_identity=_sha("nested-child-obligation"),
        expected_parent_ref=parent_ref,
    )
    child = _active_window(runtime)
    _advance_to(runtime, authenticator, child.deadline_at)
    commitment = runtime.current_timeout_due_commitment_v1(child_ref)
    controller_identity = _sha("nested-timeout-controller")
    adapter = SyntheticPublicAuthorityAdapter(
        runtime,
        authenticator,
        child_ref,
        controller_identity=controller_identity,
        families_by_step=((c8.PublicActionFamilyV1.PASS_RESPONSE,),),
    )
    controller = ctl.TimeoutResolverControllerIntegrationV1(
        runtime,
        adapter,
        controller_instance_identity=controller_identity,
    )
    events_before = len(runtime.state.runtime_events)
    result = controller.resolve_timeout_v1(
        child_ref,
        timeout_due_commitment=commitment,
    )
    assert result.result_kind == ctl.ControllerResultKindV1.RESOLVED_SINGLE.value
    assert runtime.active_window_ref() == parent_ref
    resumed = _active_window(runtime)
    assert resumed.window_id == parent_before_child.window_id
    assert resumed.status is c8.TimedWindowStatusV1.ACTIVE
    assert resumed.opened_at == parent_before_child.opened_at
    appended = runtime.state.runtime_events[events_before:]
    assert tuple(item.event_kind for item in appended[-2:]) == (
        rt.RuntimeEventKindV1.WINDOW_CLOSED_BY_TIMEOUT,
        rt.RuntimeEventKindV1.PARENT_RESUMED_AFTER_CHILD,
    )
    assert inner.public_counter == inner.secret_counter == 1


@pytest.mark.parametrize(
    ("kind", "fallback"),
    [
        (c8.TimedWindowKindV1.PLAY, c8.PublicActionFamilyV1.END_PLAY_PHASE),
        (
            c8.TimedWindowKindV1.OPTIONAL_RESPONSE,
            c8.PublicActionFamilyV1.PASS_RESPONSE,
        ),
        (
            c8.TimedWindowKindV1.RESCUE_RESPONSE,
            c8.PublicActionFamilyV1.PASS_RESCUE,
        ),
        (
            c8.TimedWindowKindV1.OPTIONAL_SKILL_DECISION,
            c8.PublicActionFamilyV1.DECLINE_OPTIONAL,
        ),
        (
            c8.TimedWindowKindV1.MODE_DECISION,
            c8.PublicActionFamilyV1.PASS_MODE_DECISION,
        ),
    ],
)
def test_explicit_policy_fallback_happy_and_missing(
    kind: c8.TimedWindowKindV1,
    fallback: c8.PublicActionFamilyV1,
) -> None:
    success = _controller_harness(
        label=f"explicit-success-{kind.value}",
        kind=kind,
        families_by_step=((c8.PublicActionFamilyV1.MANDATORY_ACTION, fallback),),
    )
    controller, adapter, runtime, _, _, ref, commitment = success
    result = controller.resolve_timeout_v1(ref, timeout_due_commitment=commitment)
    assert result.result_kind == ctl.ControllerResultKindV1.RESOLVED_SINGLE.value
    assert result.selected_actions[0].action_family == fallback.value
    assert result.selected_actions[0].public_ordinal == 1
    assert runtime.active_window_ref() is None
    assert adapter.issue_count == 1

    missing = _controller_harness(
        label=f"explicit-missing-{kind.value}",
        kind=kind,
        families_by_step=((c8.PublicActionFamilyV1.MANDATORY_ACTION,),),
    )
    controller, adapter, runtime, inner, _, ref, commitment = missing
    pre = _gameplay_snapshot(runtime, inner)
    result = controller.resolve_timeout_v1(ref, timeout_due_commitment=commitment)
    assert result.result_kind == ctl.ControllerResultKindV1.TIMEOUT_UNRESOLVED.value
    assert result.reason == c8.TimeoutResolutionKindV1.TIMEOUT_UNRESOLVED.value
    assert result.step_count == 1
    assert len(result.legal_set_identities) == 1
    assert result.receipt_identities == ()
    assert result.selected_actions == ()
    assert adapter.issue_count == 0
    assert _gameplay_snapshot(runtime, inner) == pre


@pytest.mark.parametrize("candidate_count", [0, 1, 2])
def test_mandatory_single_requires_exactly_one_candidate(
    candidate_count: int,
) -> None:
    families = tuple(
        c8.PublicActionFamilyV1.MANDATORY_ACTION for _ in range(candidate_count)
    )
    controller, adapter, runtime, inner, _, ref, commitment = _controller_harness(
        label=f"mandatory-single-{candidate_count}",
        kind=c8.TimedWindowKindV1.MANDATORY_SINGLE_ACTION,
        families_by_step=(families,),
    )
    pre = _gameplay_snapshot(runtime, inner)
    result = controller.resolve_timeout_v1(ref, timeout_due_commitment=commitment)
    expected = (
        ctl.ControllerResultKindV1.RESOLVED_SINGLE.value
        if candidate_count == 1
        else ctl.ControllerResultKindV1.TIMEOUT_UNRESOLVED.value
    )
    assert result.result_kind == expected
    assert adapter.issue_count == (1 if candidate_count == 1 else 0)
    if candidate_count == 1:
        assert result.selected_actions[0].public_ordinal == 0
        assert runtime.active_window_ref() is None
    else:
        assert _gameplay_snapshot(runtime, inner) == pre


def test_mandatory_public_choice_uses_canonical_public_ordinal_zero() -> None:
    controller, adapter, runtime, _, _, ref, commitment = _controller_harness(
        label="mandatory-public-choice",
        kind=c8.TimedWindowKindV1.MANDATORY_PUBLIC_CHOICE,
        families_by_step=(
            (
                c8.PublicActionFamilyV1.PUBLIC_CHOICE,
                c8.PublicActionFamilyV1.PUBLIC_CHOICE,
            ),
        ),
    )
    result = controller.resolve_timeout_v1(ref, timeout_due_commitment=commitment)
    assert result.result_kind == ctl.ControllerResultKindV1.RESOLVED_SINGLE.value
    assert result.selected_actions[0].public_ordinal == 0
    assert result.selected_actions[0].public_action_reference.endswith("-0")
    assert runtime.active_window_ref() is None
    assert adapter.fetch_count == adapter.issue_count == 1


@pytest.mark.parametrize("steps", [2, 3, 8])
def test_same_tick_chain_refreshes_legal_authority_and_completes_at_cap(
    steps: int,
) -> None:
    controller, adapter, runtime, inner, _, ref, commitment = _controller_harness(
        label=f"same-tick-chain-{steps}",
        kind=c8.TimedWindowKindV1.MULTI_STEP_OBLIGATION,
        families_by_step=(
            (c8.PublicActionFamilyV1.DECLINE_OPTIONAL,),
        ) * steps,
        completion_by_step=(False,) * (steps - 1) + (True,),
    )
    result = controller.resolve_timeout_v1(ref, timeout_due_commitment=commitment)
    assert result.result_kind == ctl.ControllerResultKindV1.RESOLVED_CHAIN.value
    assert result.step_count == steps
    assert len(set(result.legal_set_identities)) == steps
    assert len(set(result.receipt_identities)) == steps
    assert len({item.issuance_evidence_identity for item in result.selected_actions}) == steps
    assert [item.step_index for item in result.selected_actions] == list(
        range(1, steps + 1)
    )
    assert len(set(adapter.window_observations)) == 1
    assert adapter.fetch_count == adapter.issue_count == steps
    assert inner.public_counter == inner.secret_counter == steps
    assert runtime.active_window_ref() is None
    kinds = [event.event_kind for event in controller.public_event_trace_v1()]
    assert kinds.count(ctl.ControllerEventKindV1.CHAIN_CONTINUED.value) == steps - 1


def test_same_tick_continuation_uses_zero_based_b_progress_indices(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller, _, runtime, _, _, ref, commitment = _controller_harness(
        label="zero-based-b-progress",
        kind=c8.TimedWindowKindV1.MULTI_STEP_OBLIGATION,
        families_by_step=((c8.PublicActionFamilyV1.DECLINE_OPTIONAL,),) * 3,
        completion_by_step=(False, False, True),
    )
    original = rt.C8TimedSessionRuntimeV1.continue_timeout_multi_step_obligation_v1
    indices: list[int] = []

    def record_continue(
        runtime_self: rt.C8TimedSessionRuntimeV1,
        *args: object,
        **kwargs: object,
    ) -> c8.DeadlinePrecedenceV1:
        indices.append(kwargs["expected_step_index"])  # type: ignore[arg-type]
        return original(runtime_self, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(
        rt.C8TimedSessionRuntimeV1,
        "continue_timeout_multi_step_obligation_v1",
        record_continue,
    )
    result = controller.resolve_timeout_v1(ref, timeout_due_commitment=commitment)
    assert result.result_kind == ctl.ControllerResultKindV1.RESOLVED_CHAIN.value
    assert indices == [0, 1]


def test_repeated_public_legal_set_in_same_tick_chain_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller, adapter, runtime, inner, _, ref, commitment = _controller_harness(
        label="repeated-public-legal-set",
        kind=c8.TimedWindowKindV1.MULTI_STEP_OBLIGATION,
        families_by_step=((c8.PublicActionFamilyV1.DECLINE_OPTIONAL,),) * 2,
        completion_by_step=(False, True),
    )
    original = adapter.fresh_public_legal_actions_v1
    first: list[ctl.AdapterPublicLegalActionsSnapshotV1] = []

    def replay_snapshot() -> ctl.AdapterPublicLegalActionsSnapshotV1:
        if first:
            adapter.current_snapshot = first[0]
            return first[0]
        snapshot = original()
        first.append(snapshot)
        return snapshot

    monkeypatch.setattr(adapter, "fresh_public_legal_actions_v1", replay_snapshot)
    pre = _gameplay_snapshot(runtime, inner)
    result = controller.resolve_timeout_v1(ref, timeout_due_commitment=commitment)
    assert result.result_kind == ctl.ControllerResultKindV1.FAILED_ROLLED_BACK.value
    assert result.reason in {
        "LEGAL_SET_REPLAY_OR_NOT_FRESH",
        "FAIL_CLOSED_C8CContractError",
    }
    assert result.step_count == 1
    assert len(result.legal_set_identities) == 1
    assert _gameplay_snapshot(runtime, inner) == pre


def test_candidate_and_issuance_cannot_replay_across_fresh_legal_sets() -> None:
    controller, adapter, runtime, inner, _, ref, commitment = _controller_harness(
        label="cross-legal-set-issuance-replay",
        kind=c8.TimedWindowKindV1.MULTI_STEP_OBLIGATION,
        families_by_step=((c8.PublicActionFamilyV1.DECLINE_OPTIONAL,),) * 2,
        completion_by_step=(False, True),
    )
    adapter.replay_previous_issuance_at_issue_count = 1
    pre = _gameplay_snapshot(runtime, inner)
    result = controller.resolve_timeout_v1(ref, timeout_due_commitment=commitment)
    assert result.result_kind == ctl.ControllerResultKindV1.FAILED_ROLLED_BACK.value
    assert result.step_count == 2
    assert len(result.legal_set_identities) == 2
    assert adapter.issuances[0] is adapter.issuances[1]
    assert _gameplay_snapshot(runtime, inner) == pre


def test_candidate_and_issuance_cannot_replay_across_window_and_session() -> None:
    first, first_adapter, _, _, _, first_ref, first_commitment = (
        _controller_harness(label="cross-context-replay-source")
    )
    first_result = first.resolve_timeout_v1(
        first_ref, timeout_due_commitment=first_commitment
    )
    assert first_result.result_kind == ctl.ControllerResultKindV1.RESOLVED_SINGLE.value
    replay = first_adapter.issuances[0]

    second, second_adapter, runtime, inner, _, ref, commitment = (
        _controller_harness(label="cross-context-replay-target")
    )
    second_adapter.replay_issuance = replay
    pre = _gameplay_snapshot(runtime, inner)
    result = second.resolve_timeout_v1(ref, timeout_due_commitment=commitment)
    assert result.result_kind == ctl.ControllerResultKindV1.FAILED_ROLLED_BACK.value
    assert replay.window_authority_ref_identity != ref.authority_ref_identity
    assert replay.session_identity != runtime.state.inner_session_binding_identity
    assert _gameplay_snapshot(runtime, inner) == pre


def test_chain_requiring_ninth_step_exhausts_and_rolls_back_atomically() -> None:
    controller, adapter, runtime, inner, authenticator, ref, commitment = (
        _controller_harness(
            label="chain-cap-exhaustion",
            kind=c8.TimedWindowKindV1.MULTI_STEP_OBLIGATION,
            families_by_step=(
                (c8.PublicActionFamilyV1.DECLINE_OPTIONAL,),
            ) * 8,
            completion_by_step=(False,) * 8,
        )
    )
    pre = _gameplay_snapshot(runtime, inner)
    result = controller.resolve_timeout_v1(ref, timeout_due_commitment=commitment)
    assert result.result_kind == ctl.ControllerResultKindV1.CHAIN_CAP_EXHAUSTED.value
    assert result.reason == "NINTH_SAME_TICK_STEP_REQUIRED"
    assert result.step_count == 8
    assert len(result.legal_set_identities) == len(result.receipt_identities) == 8
    assert len(result.selected_actions) == 8
    assert adapter.fetch_count == adapter.issue_count == 8
    assert _gameplay_snapshot(runtime, inner) == pre
    assert len(authenticator.consumed_evidence) >= 9  # one clock input + eight actions
    assert controller.public_event_trace_v1()[-1].event_kind == (
        ctl.ControllerEventKindV1.ROLLED_BACK.value
    )


@pytest.mark.parametrize("unresolved_step", [2, 3])
def test_chain_midstep_unresolved_rolls_back_prior_executions(
    unresolved_step: int,
) -> None:
    families = [
        (c8.PublicActionFamilyV1.DECLINE_OPTIONAL,)
        for _ in range(unresolved_step - 1)
    ]
    families.append(
        (
            c8.PublicActionFamilyV1.MANDATORY_ACTION,
            c8.PublicActionFamilyV1.PUBLIC_CHOICE,
        )
    )
    controller, adapter, runtime, inner, _, ref, commitment = _controller_harness(
        label=f"chain-unresolved-{unresolved_step}",
        kind=c8.TimedWindowKindV1.MULTI_STEP_OBLIGATION,
        families_by_step=tuple(families),
        completion_by_step=(False,) * unresolved_step,
    )
    pre = _gameplay_snapshot(runtime, inner)
    result = controller.resolve_timeout_v1(ref, timeout_due_commitment=commitment)
    assert result.result_kind == ctl.ControllerResultKindV1.TIMEOUT_UNRESOLVED.value
    assert result.step_count == unresolved_step
    assert len(result.legal_set_identities) == unresolved_step
    assert len(result.receipt_identities) == unresolved_step - 1
    assert len(result.selected_actions) == unresolved_step - 1
    assert adapter.issue_count == unresolved_step - 1
    assert _gameplay_snapshot(runtime, inner) == pre


@pytest.mark.parametrize(
    "field",
    [
        "runtime_instance_identity",
        "window_authority_ref_identity",
        "session_identity",
        "controller_identity",
        "adapter_identity",
        "public_state_identity",
        "authoritative_state_identity",
        "issuance_security_ledger_identity",
        "canonical_public_ordering_identity",
        "snapshot_identity",
    ],
)
def test_adapter_snapshot_identity_context_and_deep_tamper_fail_closed(
    field: str,
) -> None:
    controller, adapter, runtime, inner, _, ref, commitment = _controller_harness(
        label=f"snapshot-tamper-{field}"
    )
    adapter.fault = "tamper_envelope"
    adapter.tamper_field = field
    adapter.tamper_value = _sha(f"tampered-snapshot:{field}")
    pre = _gameplay_snapshot(runtime, inner)
    result = controller.resolve_timeout_v1(ref, timeout_due_commitment=commitment)
    assert result.result_kind in {
        ctl.ControllerResultKindV1.FAILED_ROLLED_BACK.value,
        ctl.ControllerResultKindV1.FAILED_POISONED.value,
    }
    assert adapter.issue_count == 0
    assert _gameplay_snapshot(runtime, inner) == pre


@pytest.mark.parametrize(
    "field",
    [
        "legal_set_snapshot",
        "ordering",
        "adapter",
        "session",
        "controller",
        "public",
        "authoritative",
    ],
)
def test_current_lineage_change_between_resolver_and_issuance_rolls_back(
    field: str,
) -> None:
    controller, adapter, runtime, inner, _, ref, commitment = _controller_harness(
        label=f"pre-issuance-drift-{field}"
    )
    adapter.drift_field = field
    adapter.drift_on_bundle = 3
    pre = _gameplay_snapshot(runtime, inner)
    result = controller.resolve_timeout_v1(ref, timeout_due_commitment=commitment)
    assert result.result_kind in {
        ctl.ControllerResultKindV1.FAILED_ROLLED_BACK.value,
        ctl.ControllerResultKindV1.FAILED_POISONED.value,
    }
    assert adapter.issue_count == 0
    assert result.step_count == 1
    assert len(result.legal_set_identities) == 1
    assert result.receipt_identities == ()
    assert _gameplay_snapshot(runtime, inner) == pre


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("signed_action_id", "forged-signed-action"),
        ("signed_action_id_commitment", _sha("wrong-signed-action-commitment")),
        ("external_capability_identity", _sha("wrong-external-capability")),
        ("public_ordinal", 7),
        ("candidate_identity", _sha("wrong-candidate")),
        ("action_family", c8.PublicActionFamilyV1.PASS_RESPONSE.value),
        ("legal_set_identity", _sha("wrong-legal-set")),
        ("canonical_public_ordering_identity", _sha("wrong-ordering")),
        ("timeout_due_commitment_identity", _sha("wrong-timeout")),
        ("authorization_binding_identity", _sha("wrong-auth-binding")),
        ("issuance_authority_identity", _sha("wrong-issuer")),
        ("authorization_evidence_identity", _sha("forged-auth-evidence")),
        ("runtime_instance_identity", _sha("wrong-runtime")),
        ("window_authority_ref_identity", _sha("wrong-window-ref")),
        ("session_identity", _sha("wrong-session")),
        ("controller_identity", _sha("wrong-controller")),
        ("adapter_identity", _sha("wrong-adapter")),
        ("public_state_identity", _sha("wrong-public-state")),
        ("authoritative_state_identity", _sha("wrong-authoritative-state")),
        ("issuance_security_ledger_before_identity", _sha("wrong-ledger-before")),
        ("issuance_security_ledger_after_identity", _sha("wrong-ledger-after")),
        ("obligation_completed", "true"),
        ("issuance_identity", _sha("forged-issuance-identity")),
    ],
)
def test_issuance_evidence_mismatch_or_deep_tamper_fails_closed(
    field: str,
    replacement: object,
) -> None:
    controller, adapter, runtime, inner, _, ref, commitment = _controller_harness(
        label=f"issuance-tamper-{field}"
    )
    adapter.fault = "tamper_issuance"
    adapter.tamper_field = field
    adapter.tamper_value = replacement
    pre = _gameplay_snapshot(runtime, inner)
    result = controller.resolve_timeout_v1(ref, timeout_due_commitment=commitment)
    assert result.result_kind in {
        ctl.ControllerResultKindV1.FAILED_ROLLED_BACK.value,
        ctl.ControllerResultKindV1.FAILED_POISONED.value,
    }
    assert runtime.active_window_ref() == ref
    assert _gameplay_snapshot(runtime, inner) == pre


@pytest.mark.parametrize("fault", ["legal_fetch", "issue_error"])
def test_failure_stages_restore_full_inner_and_outer_state(fault: str) -> None:
    controller, adapter, runtime, inner, _, ref, commitment = _controller_harness(
        label=f"fault-stage-{fault}"
    )
    adapter.fault = fault
    pre = _gameplay_snapshot(runtime, inner)
    result = controller.resolve_timeout_v1(ref, timeout_due_commitment=commitment)
    assert result.result_kind in {
        ctl.ControllerResultKindV1.FAILED_ROLLED_BACK.value,
        ctl.ControllerResultKindV1.FAILED_POISONED.value,
    }
    assert _gameplay_snapshot(runtime, inner) == pre
    assert runtime.active_window_ref() == ref


def test_b_forward_failure_after_auth_consumption_is_not_misclassified_unforwarded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller, adapter, runtime, inner, authenticator, ref, commitment = (
        _controller_harness(label="b-forward-fails-after-consume")
    )
    inner.apply_raises = True
    original = rt.C8TimedSessionRuntimeV1.forward_timeout_due_signed_action_id_v1
    observed_capabilities: list[rt.PendingTimeoutIssuanceCapabilityV1] = []

    def capture_capability_then_forward(
        runtime_self: rt.C8TimedSessionRuntimeV1,
        *args: object,
        **kwargs: object,
    ) -> rt.TimeoutActionExecutionReceiptV1:
        observed_capabilities.append(kwargs["pending_issuance_capability"])  # type: ignore[arg-type]
        return original(runtime_self, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(
        rt.C8TimedSessionRuntimeV1,
        "forward_timeout_due_signed_action_id_v1",
        capture_capability_then_forward,
    )
    pre = _gameplay_snapshot(runtime, inner)
    consumed_before = set(authenticator.consumed_evidence)
    result = controller.resolve_timeout_v1(ref, timeout_due_commitment=commitment)
    newly_consumed = authenticator.consumed_evidence - consumed_before
    assert result.result_kind == ctl.ControllerResultKindV1.FAILED_ROLLED_BACK.value
    assert result.reason == "B_FORWARD_FAILED_AFTER_CONSUME_CAPABILITY_BURNED"
    assert controller.poisoned is False
    assert len(newly_consumed) == 1
    assert adapter.issuances[0].authorization_evidence_identity in newly_consumed
    assert adapter.invalidations == []
    assert adapter.failed_issuance_recoveries == []
    assert authenticator.revoked_evidence.isdisjoint(newly_consumed)
    capability = observed_capabilities[0]
    ownership = runtime.current_pending_issuance_capability_ownership_v1(
        capability
    )
    assert ownership.status is rt.PendingIssuanceCapabilityStatusV1.AUTH_EVIDENCE_CONSUMED
    with pytest.raises(rt.C8TimedSessionRuntimeError):
        runtime.abort_pending_timeout_issuance_capability_v1(capability)
    assert _gameplay_snapshot(runtime, inner) == pre
    assert runtime.current_timeout_due_commitment_v1(ref) is not None


def test_b_authenticator_raise_before_consume_recovers_adapter_capability() -> None:
    controller, adapter, runtime, inner, authenticator, ref, commitment = (
        _controller_harness(label="b-auth-raises-before-consume")
    )
    authenticator.timeout_verify_raises_before_consume = True
    pre = _gameplay_snapshot(runtime, inner)
    consumed_before = set(authenticator.consumed_evidence)
    result = controller.resolve_timeout_v1(ref, timeout_due_commitment=commitment)
    evidence = adapter.issuances[0].authorization_evidence_identity
    assert result.result_kind == ctl.ControllerResultKindV1.FAILED_ROLLED_BACK.value
    assert controller.poisoned is False
    assert authenticator.consumed_evidence == consumed_before
    assert evidence in authenticator.revoked_evidence
    assert evidence not in authenticator._authorized
    assert len(adapter.invalidations) == 1
    assert adapter.failed_issuance_recoveries == []
    assert _gameplay_snapshot(runtime, inner) == pre
    assert runtime.current_timeout_due_commitment_v1(ref) is not None


@pytest.mark.parametrize("unknown_return", [None, object()])
def test_unknown_preconsume_b_return_keeps_ownership_then_guarded_aborts(
    monkeypatch: pytest.MonkeyPatch,
    unknown_return: object,
) -> None:
    controller, adapter, runtime, inner, authenticator, ref, commitment = (
        _controller_harness(label=f"unknown-preconsume-{type(unknown_return).__name__}")
    )
    original = rt.C8TimedSessionRuntimeV1.forward_timeout_due_signed_action_id_v1
    observed_capabilities: list[rt.PendingTimeoutIssuanceCapabilityV1] = []

    def return_without_consuming(
        runtime_self: rt.C8TimedSessionRuntimeV1,
        *args: object,
        **kwargs: object,
    ) -> object:
        assert runtime_self is runtime
        observed_capabilities.append(kwargs["pending_issuance_capability"])  # type: ignore[arg-type]
        return unknown_return

    monkeypatch.setattr(
        rt.C8TimedSessionRuntimeV1,
        "forward_timeout_due_signed_action_id_v1",
        return_without_consuming,
    )
    pre = _gameplay_snapshot(runtime, inner)
    result = controller.resolve_timeout_v1(ref, timeout_due_commitment=commitment)
    assert result.result_kind == ctl.ControllerResultKindV1.FAILED_ROLLED_BACK.value
    assert controller.poisoned is False
    assert len(observed_capabilities) == 1
    capability = observed_capabilities[0]
    ownership = runtime.current_pending_issuance_capability_ownership_v1(
        capability
    )
    assert ownership.status is rt.PendingIssuanceCapabilityStatusV1.CONTROLLER_ABORTED
    assert ownership.committed_receipt_identity is None
    issuance = adapter.issuances[0]
    assert issuance.authorization_evidence_identity in authenticator.revoked_evidence
    assert issuance.authorization_evidence_identity not in authenticator.consumed_evidence
    assert len(adapter.invalidations) == 1
    assert ("abort-pending-issuance", True) in adapter.guard_observations
    with pytest.raises(rt.C8TimedSessionRuntimeError):
        runtime.abort_pending_timeout_issuance_capability_v1(capability)
    monkeypatch.setattr(
        rt.C8TimedSessionRuntimeV1,
        "forward_timeout_due_signed_action_id_v1",
        original,
    )
    current = runtime.current_timeout_due_commitment_v1(ref)
    with pytest.raises(rt.C8TimedSessionRuntimeError):
        runtime.forward_timeout_due_signed_action_id_v1(
            ref,
            timeout_due_commitment=current,
            signed_action_id=issuance.signed_action_id,
            authorization_evidence_identity=issuance.authorization_evidence_identity,
            pending_issuance_capability=capability,
        )
    assert _gameplay_snapshot(runtime, inner) == pre


def test_post_issuance_validation_failure_recovers_unforwarded_external_evidence() -> None:
    controller, adapter, runtime, inner, authenticator, ref, commitment = (
        _controller_harness(label="unforwarded-invalidation")
    )
    adapter.fault = "tamper_issuance"
    adapter.tamper_field = "issuance_identity"
    adapter.tamper_value = _sha("post-issuance-invalid-self-identity")
    pre = _gameplay_snapshot(runtime, inner)
    result = controller.resolve_timeout_v1(ref, timeout_due_commitment=commitment)
    assert result.result_kind == ctl.ControllerResultKindV1.FAILED_ROLLED_BACK.value
    assert adapter.issue_count == 1
    assert adapter.invalidations == []
    assert len(adapter.failed_issuance_recoveries) == 1
    evidence = adapter.issuances[0].authorization_evidence_identity
    assert evidence in authenticator.revoked_evidence
    assert evidence not in authenticator.consumed_evidence
    assert evidence not in authenticator._authorized
    assert len(authenticator.consumed_evidence) == 1  # virtual-time advance only
    assert controller.poisoned is False
    assert _gameplay_snapshot(runtime, inner) == pre
    assert runtime.current_timeout_due_commitment_v1(ref) is not None


def test_issue_callback_raise_after_external_advance_cannot_leave_reusable_auth() -> None:
    controller, adapter, runtime, inner, authenticator, ref, commitment = (
        _controller_harness(label="issue-raise-after-security-advance")
    )
    adapter.fault = "issue_after_external_advance_error"
    pre = _gameplay_snapshot(runtime, inner)
    result = controller.resolve_timeout_v1(ref, timeout_due_commitment=commitment)
    evidence = adapter.raised_after_advance_evidence
    assert evidence is not None
    assert result.result_kind == ctl.ControllerResultKindV1.FAILED_ROLLED_BACK.value
    assert result.reason == "ISSUANCE_CALLBACK_FAILED_CAPABILITIES_RECOVERED"
    assert controller.poisoned is False
    assert len(adapter.failed_issuance_recoveries) == 1
    assert evidence not in authenticator._authorized
    assert evidence in authenticator.revoked_evidence
    assert evidence not in authenticator.consumed_evidence
    assert len(authenticator.consumed_evidence) == 1  # virtual-time advance only
    assert _gameplay_snapshot(runtime, inner) == pre
    assert runtime.current_timeout_due_commitment_v1(ref) is not None


@pytest.mark.parametrize("tampered_proof", [False, True])
def test_failed_issuance_recovery_failure_or_tamper_poisons_controller(
    tampered_proof: bool,
) -> None:
    controller, adapter, runtime, inner, authenticator, ref, commitment = (
        _controller_harness(label=f"failed-recovery-{tampered_proof}")
    )
    adapter.fault = "issue_after_external_advance_error"
    adapter.failed_recovery_raises = not tampered_proof
    adapter.tamper_failed_recovery = tampered_proof
    pre = _gameplay_snapshot(runtime, inner)
    result = controller.resolve_timeout_v1(ref, timeout_due_commitment=commitment)
    evidence = adapter.raised_after_advance_evidence
    assert evidence is not None
    assert result.result_kind == ctl.ControllerResultKindV1.FAILED_POISONED.value
    assert controller.poisoned is True
    if tampered_proof:
        assert evidence in authenticator.revoked_evidence
        assert evidence not in authenticator._authorized
    else:
        assert evidence in authenticator._authorized
    assert evidence not in authenticator.consumed_evidence
    assert _gameplay_snapshot(runtime, inner) == pre
    with pytest.raises(ctl.C8CPoisonedError):
        controller.resolve_timeout_v1(ref, timeout_due_commitment=commitment)


def test_consumed_external_auth_evidence_cannot_replay_after_controller_rollback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller, adapter, runtime, inner, authenticator, ref, commitment = (
        _controller_harness(label="consumed-auth-replay")
    )
    original = rt.C8TimedSessionRuntimeV1.forward_timeout_due_signed_action_id_v1

    def return_malformed_receipt(
        runtime_self: rt.C8TimedSessionRuntimeV1,
        *args: object,
        **kwargs: object,
    ) -> rt.TimeoutActionExecutionReceiptV1:
        receipt = original(runtime_self, *args, **kwargs)  # type: ignore[arg-type]
        return _unsafe_dataclass_copy(
            receipt,
            receipt_identity=_sha("malformed-consumed-receipt"),
        )  # type: ignore[return-value]

    monkeypatch.setattr(
        rt.C8TimedSessionRuntimeV1,
        "forward_timeout_due_signed_action_id_v1",
        return_malformed_receipt,
    )
    pre = _gameplay_snapshot(runtime, inner)
    failed = controller.resolve_timeout_v1(ref, timeout_due_commitment=commitment)
    assert failed.result_kind == ctl.ControllerResultKindV1.FAILED_ROLLED_BACK.value
    issuance = adapter.issuances[0]
    assert issuance.authorization_evidence_identity in authenticator.consumed_evidence
    assert issuance.authorization_evidence_identity not in authenticator._authorized
    assert _gameplay_snapshot(runtime, inner) == pre

    current = runtime.current_timeout_due_commitment_v1(ref)
    replay_pre = _gameplay_snapshot(runtime, inner)
    with pytest.raises(rt.C8TimedSessionRuntimeError):
        runtime.forward_timeout_due_signed_action_id_v1(
            ref,
            timeout_due_commitment=current,
            signed_action_id=issuance.signed_action_id,
            authorization_evidence_identity=(
                issuance.authorization_evidence_identity
            ),
        )
    assert _gameplay_snapshot(runtime, inner) == replay_pre


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("signed_action_id_commitment", _sha("receipt-wrong-action")),
        ("window_id", "c8w-wrong-window"),
        ("runtime_instance_identity", _sha("receipt-wrong-runtime")),
        ("timeout_due_commitment_identity", _sha("receipt-wrong-timeout")),
        ("authorization_evidence_identity", _sha("receipt-wrong-issuance")),
        (
            "pending_issuance_capability_identity",
            _sha("receipt-wrong-pending-capability"),
        ),
        ("pre_inner_public_state_identity", _sha("receipt-wrong-pre-public")),
        (
            "pre_inner_authoritative_state_identity",
            _sha("receipt-wrong-pre-authoritative"),
        ),
        ("post_inner_public_state_identity", _sha("receipt-wrong-post-public")),
        (
            "post_inner_authoritative_state_identity",
            _sha("receipt-wrong-post-authoritative"),
        ),
        ("pending_deadline_identity", _sha("receipt-wrong-deadline")),
        ("receipt_sequence", 99),
        ("receipt_identity", _sha("receipt-forged-self-identity")),
    ],
)
def test_execution_receipt_binding_and_deep_tamper_rolls_back(
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    replacement: object,
) -> None:
    controller, adapter, runtime, inner, authenticator, ref, commitment = (
        _controller_harness(label=f"receipt-tamper-{field}")
    )
    original = rt.C8TimedSessionRuntimeV1.forward_timeout_due_signed_action_id_v1

    def tampered_forward(
        runtime_self: rt.C8TimedSessionRuntimeV1,
        *args: object,
        **kwargs: object,
    ) -> rt.TimeoutActionExecutionReceiptV1:
        receipt = original(runtime_self, *args, **kwargs)  # type: ignore[arg-type]
        return _unsafe_dataclass_copy(
            receipt, **{field: replacement}
        )  # type: ignore[return-value]

    monkeypatch.setattr(
        rt.C8TimedSessionRuntimeV1,
        "forward_timeout_due_signed_action_id_v1",
        tampered_forward,
    )
    pre = _gameplay_snapshot(runtime, inner)
    result = controller.resolve_timeout_v1(ref, timeout_due_commitment=commitment)
    assert result.result_kind in {
        ctl.ControllerResultKindV1.FAILED_ROLLED_BACK.value,
        ctl.ControllerResultKindV1.FAILED_POISONED.value,
    }
    assert result.step_count == 1
    assert len(result.legal_set_identities) == 1
    assert len(result.receipt_identities) == 1
    assert _gameplay_snapshot(runtime, inner) == pre
    assert len(authenticator.consumed_evidence) >= 2
    assert runtime.active_window_ref() == ref


def test_obligation_completion_is_prebound_by_guarded_issuance() -> None:
    controller, adapter, runtime, _, _, ref, commitment = _controller_harness(
        label="prebound-completion"
    )
    result = controller.resolve_timeout_v1(ref, timeout_due_commitment=commitment)
    assert result.result_kind == ctl.ControllerResultKindV1.RESOLVED_SINGLE.value
    assert adapter.issuances[0].obligation_completed is True
    assert "verify-receipt-lineage" not in adapter.calls
    assert not hasattr(
        ctl.PublicLegalActionsIssuanceAdapterV1,
        "verify_execution_receipt_lineage_v1",
    )
    assert runtime.active_window_ref() is None


def test_duplicate_receipt_across_chain_steps_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller, adapter, runtime, inner, _, ref, commitment = _controller_harness(
        label="duplicate-chain-receipt",
        kind=c8.TimedWindowKindV1.MULTI_STEP_OBLIGATION,
        families_by_step=(
            (c8.PublicActionFamilyV1.DECLINE_OPTIONAL,),
            (c8.PublicActionFamilyV1.DECLINE_OPTIONAL,),
        ),
        completion_by_step=(False, True),
    )
    original = rt.C8TimedSessionRuntimeV1.forward_timeout_due_signed_action_id_v1
    first_receipt: list[rt.TimeoutActionExecutionReceiptV1] = []

    def replaying_forward(
        runtime_self: rt.C8TimedSessionRuntimeV1,
        *args: object,
        **kwargs: object,
    ) -> rt.TimeoutActionExecutionReceiptV1:
        if first_receipt:
            return first_receipt[0]
        receipt = original(runtime_self, *args, **kwargs)  # type: ignore[arg-type]
        first_receipt.append(receipt)
        return receipt

    monkeypatch.setattr(
        rt.C8TimedSessionRuntimeV1,
        "forward_timeout_due_signed_action_id_v1",
        replaying_forward,
    )
    pre = _gameplay_snapshot(runtime, inner)
    result = controller.resolve_timeout_v1(ref, timeout_due_commitment=commitment)
    assert result.result_kind in {
        ctl.ControllerResultKindV1.FAILED_ROLLED_BACK.value,
        ctl.ControllerResultKindV1.FAILED_POISONED.value,
    }
    assert result.step_count == 2
    assert len(result.receipt_identities) == 2
    assert result.receipt_identities[0] == result.receipt_identities[1]
    assert _gameplay_snapshot(runtime, inner) == pre


@pytest.mark.parametrize("operation", ["close", "continue"])
def test_post_execute_close_or_continue_failure_restores_transaction(
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    is_continue = operation == "continue"
    controller, adapter, runtime, inner, authenticator, ref, commitment = (
        _controller_harness(
            label=f"post-execute-{operation}",
            kind=(
                c8.TimedWindowKindV1.MULTI_STEP_OBLIGATION
                if is_continue
                else c8.TimedWindowKindV1.PLAY
            ),
            families_by_step=(
                (
                    c8.PublicActionFamilyV1.DECLINE_OPTIONAL
                    if is_continue
                    else c8.PublicActionFamilyV1.END_PLAY_PHASE,
                ),
            ),
            completion_by_step=((False,) if is_continue else (True,)),
        )
    )
    method_name = (
        "continue_timeout_multi_step_obligation_v1"
        if is_continue
        else "close_window_by_timeout_receipt_v1"
    )

    def fail_after_execute(*args: object, **kwargs: object) -> object:
        raise RuntimeError(f"synthetic {operation} failure")

    monkeypatch.setattr(rt.C8TimedSessionRuntimeV1, method_name, fail_after_execute)
    pre = _gameplay_snapshot(runtime, inner)
    result = controller.resolve_timeout_v1(ref, timeout_due_commitment=commitment)
    assert result.result_kind == ctl.ControllerResultKindV1.FAILED_ROLLED_BACK.value
    assert result.step_count == 1
    assert len(result.receipt_identities) == 1
    assert _gameplay_snapshot(runtime, inner) == pre
    assert len(authenticator.consumed_evidence) >= 2


def test_no_op_close_returning_real_closed_shape_cannot_fake_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller, _, runtime, inner, authenticator, ref, commitment = (
        _controller_harness(label="no-op-close")
    )
    pre = _gameplay_snapshot(runtime, inner)
    rewind = runtime.capture_transaction()
    original = rt.C8TimedSessionRuntimeV1.close_window_by_timeout_receipt_v1

    def close_then_rewind(
        runtime_self: rt.C8TimedSessionRuntimeV1,
        *args: object,
        **kwargs: object,
    ) -> c8.TimedDecisionWindowV1:
        closed = original(runtime_self, *args, **kwargs)  # type: ignore[arg-type]
        runtime_self.rollback(rewind)
        return closed

    monkeypatch.setattr(
        rt.C8TimedSessionRuntimeV1,
        "close_window_by_timeout_receipt_v1",
        close_then_rewind,
    )
    result = controller.resolve_timeout_v1(ref, timeout_due_commitment=commitment)
    assert result.result_kind in {
        ctl.ControllerResultKindV1.FAILED_ROLLED_BACK.value,
        ctl.ControllerResultKindV1.FAILED_POISONED.value,
    }
    assert runtime.active_window_ref() == ref
    assert _gameplay_snapshot(runtime, inner) == pre
    assert len(authenticator.consumed_evidence) == 2


def test_no_op_continuation_returning_valid_precedence_cannot_fake_progress(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller, _, runtime, inner, authenticator, ref, commitment = (
        _controller_harness(
            label="no-op-continuation",
            kind=c8.TimedWindowKindV1.MULTI_STEP_OBLIGATION,
            families_by_step=((c8.PublicActionFamilyV1.DECLINE_OPTIONAL,),) * 2,
            completion_by_step=(False, True),
        )
    )
    pre = _gameplay_snapshot(runtime, inner)
    rewind = runtime.capture_transaction()
    original = rt.C8TimedSessionRuntimeV1.continue_timeout_multi_step_obligation_v1

    def continue_then_rewind(
        runtime_self: rt.C8TimedSessionRuntimeV1,
        *args: object,
        **kwargs: object,
    ) -> c8.DeadlinePrecedenceV1:
        precedence = original(runtime_self, *args, **kwargs)  # type: ignore[arg-type]
        runtime_self.rollback(rewind)
        return precedence

    monkeypatch.setattr(
        rt.C8TimedSessionRuntimeV1,
        "continue_timeout_multi_step_obligation_v1",
        continue_then_rewind,
    )
    result = controller.resolve_timeout_v1(ref, timeout_due_commitment=commitment)
    assert result.result_kind in {
        ctl.ControllerResultKindV1.FAILED_ROLLED_BACK.value,
        ctl.ControllerResultKindV1.FAILED_POISONED.value,
    }
    assert runtime.active_window_ref() == ref
    assert _gameplay_snapshot(runtime, inner) == pre
    assert len(authenticator.consumed_evidence) >= 2


@pytest.mark.parametrize(
    "callback_stage",
    ["reenter_from_legal_fetch", "reenter_from_issue"],
)
def test_nested_resolve_from_adapter_callback_is_rejected_and_poisons(
    callback_stage: str,
) -> None:
    controller, adapter, runtime, inner, _, ref, commitment = _controller_harness(
        label=f"nested-resolve-{callback_stage}"
    )
    adapter.fault = callback_stage
    adapter.reentrant_call = lambda: controller.resolve_timeout_v1(
        ref, timeout_due_commitment=commitment
    )
    pre = _gameplay_snapshot(runtime, inner)
    result = controller.resolve_timeout_v1(ref, timeout_due_commitment=commitment)
    assert result.result_kind == ctl.ControllerResultKindV1.FAILED_POISONED.value
    assert controller.poisoned is True
    assert _gameplay_snapshot(runtime, inner) == pre
    with pytest.raises(ctl.C8CPoisonedError):
        controller.resolve_timeout_v1(ref, timeout_due_commitment=commitment)


def test_nested_resolve_from_inner_execute_callback_is_rejected_and_poisons() -> None:
    controller, _, runtime, inner, authenticator, ref, commitment = (
        _controller_harness(label="nested-resolve-inner-execute")
    )
    inner.apply_reentrant_call = lambda: controller.resolve_timeout_v1(
        ref, timeout_due_commitment=commitment
    )
    pre = _gameplay_snapshot(runtime, inner)
    result = controller.resolve_timeout_v1(ref, timeout_due_commitment=commitment)
    assert result.result_kind == ctl.ControllerResultKindV1.FAILED_POISONED.value
    assert controller.poisoned is True
    assert _gameplay_snapshot(runtime, inner) == pre
    assert len(authenticator.consumed_evidence) == 2


@pytest.mark.parametrize(
    "operation",
    ["advance", "open", "close", "forward", "continue", "rollback"],
)
def test_runtime_operation_from_adapter_callback_cannot_nest_controller_transaction(
    operation: str,
) -> None:
    controller, adapter, runtime, inner, authenticator, ref, commitment = (
        _controller_harness(label=f"callback-runtime-operation-{operation}")
    )
    callback_snapshot = runtime.capture_transaction()

    def attempt_runtime_operation() -> object:
        try:
            if operation == "advance":
                return _advance_to(
                    runtime,
                    authenticator,
                    runtime.state.virtual_time_state.now_tick + 1,
                )
            if operation == "open":
                return _open(runtime, label="illegal-nested-open")
            if operation == "close":
                return runtime.close_window_by_timeout_receipt_v1(
                    ref,
                    execution_receipt=None,  # type: ignore[arg-type]
                )
            if operation == "forward":
                return runtime.forward_timeout_due_signed_action_id_v1(
                    ref,
                    timeout_due_commitment=commitment,
                    signed_action_id="illegal-guarded-forward",
                    authorization_evidence_identity=_sha("illegal-guarded-forward"),
                )
            if operation == "continue":
                return runtime.continue_timeout_multi_step_obligation_v1(
                    ref,
                    execution_receipt=None,
                    expected_step_index=0,
                    logical_step_identity=_sha("illegal-guarded-continue"),
                )
            return runtime.rollback(callback_snapshot)
        except Exception:
            # The callback deliberately catches the runtime rejection.  B's
            # non-rollback operation-attempt epoch must still make guard release
            # fail closed.
            return "caught-runtime-operation-attempt"

    adapter.fault = "reenter_from_legal_fetch"
    adapter.reentrant_call = attempt_runtime_operation
    pre = _gameplay_snapshot(runtime, inner)
    result = controller.resolve_timeout_v1(ref, timeout_due_commitment=commitment)
    assert result.result_kind in {
        ctl.ControllerResultKindV1.FAILED_ROLLED_BACK.value,
        ctl.ControllerResultKindV1.FAILED_POISONED.value,
    }
    assert _gameplay_snapshot(runtime, inner) == pre
    assert runtime.active_window_ref() == ref


@pytest.mark.parametrize("same_controller_identity", [True, False])
def test_second_controller_for_same_live_runtime_is_rejected(
    same_controller_identity: bool,
) -> None:
    first, first_adapter, runtime, _, authenticator, ref, _ = _controller_harness(
        label=f"single-live-driver-{same_controller_identity}"
    )
    second_identity = (
        first_adapter.controller_identity
        if same_controller_identity
        else _sha(f"different-controller:{same_controller_identity}")
    )
    second_adapter = SyntheticPublicAuthorityAdapter(
        runtime,
        authenticator,
        ref,
        controller_identity=second_identity,
        families_by_step=((c8.PublicActionFamilyV1.END_PLAY_PHASE,),),
    )
    assert first.poisoned is False
    with pytest.raises((ctl.C8CContractError, ctl.C8CReentrancyError)):
        ctl.TimeoutResolverControllerIntegrationV1(
            runtime,
            second_adapter,
            controller_instance_identity=second_identity,
        )


def test_runtime_owner_tombstone_survives_controller_deletion_and_gc() -> None:
    controller, adapter, runtime, _, authenticator, ref, _ = _controller_harness(
        label="single-driver-tombstone"
    )
    controller_identity = adapter.controller_identity
    del controller
    del adapter
    gc.collect()
    replacement_adapter = SyntheticPublicAuthorityAdapter(
        runtime,
        authenticator,
        ref,
        controller_identity=controller_identity,
        families_by_step=((c8.PublicActionFamilyV1.END_PLAY_PHASE,),),
    )
    with pytest.raises(ctl.C8CContractError):
        ctl.TimeoutResolverControllerIntegrationV1(
            runtime,
            replacement_adapter,
            controller_instance_identity=controller_identity,
        )


def test_runtime_subclass_is_rejected_as_non_exact_b_authority() -> None:
    class RuntimeSubclass(rt.C8TimedSessionRuntimeV1):
        pass

    inner = FakeInnerAdapter(label="runtime-subclass")
    authenticator = FakeAuthenticator(label="runtime-subclass")
    runtime = RuntimeSubclass(
        inner_adapter=inner,
        input_authenticator=authenticator,
        instance_nonce_identity=_sha("runtime-subclass-nonce"),
        input_source_id="authenticated-runtime-subclass-driver",
        driver_authority_identity=_sha("runtime-subclass-driver-authority"),
    )
    ref = _open(runtime, label="runtime-subclass")
    _advance_to(runtime, authenticator, _active_window(runtime).deadline_at)
    controller_identity = _sha("runtime-subclass-controller")
    adapter = SyntheticPublicAuthorityAdapter(
        runtime,
        authenticator,
        ref,
        controller_identity=controller_identity,
        families_by_step=((c8.PublicActionFamilyV1.END_PLAY_PHASE,),),
    )
    with pytest.raises(ctl.C8CContractError):
        ctl.TimeoutResolverControllerIntegrationV1(
            runtime,
            adapter,
            controller_instance_identity=controller_identity,
        )


def test_success_requires_exact_closed_by_timeout_status_and_tick(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller, _, runtime, _, _, ref, commitment = _controller_harness(
        label="exact-close-status"
    )
    original = rt.C8TimedSessionRuntimeV1.close_window_by_timeout_receipt_v1
    observed: list[c8.TimedDecisionWindowV1] = []

    def recording_close(
        runtime_self: rt.C8TimedSessionRuntimeV1,
        *args: object,
        **kwargs: object,
    ) -> c8.TimedDecisionWindowV1:
        closed = original(runtime_self, *args, **kwargs)  # type: ignore[arg-type]
        observed.append(closed)
        return closed

    monkeypatch.setattr(
        rt.C8TimedSessionRuntimeV1,
        "close_window_by_timeout_receipt_v1",
        recording_close,
    )
    result = controller.resolve_timeout_v1(ref, timeout_due_commitment=commitment)
    assert result.result_kind == ctl.ControllerResultKindV1.RESOLVED_SINGLE.value
    assert len(observed) == 1
    assert observed[0].status is c8.TimedWindowStatusV1.CLOSED_BY_TIMEOUT
    assert result.resolution_tick == result.deadline_at
    assert runtime.state.virtual_time_state.now_tick == result.deadline_at


def test_failure_result_and_rollback_event_preserve_attempted_public_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller, adapter, runtime, inner, _, ref, commitment = _controller_harness(
        label="rollback-public-evidence"
    )
    original = rt.C8TimedSessionRuntimeV1.forward_timeout_due_signed_action_id_v1

    def return_malformed_receipt(
        runtime_self: rt.C8TimedSessionRuntimeV1,
        *args: object,
        **kwargs: object,
    ) -> rt.TimeoutActionExecutionReceiptV1:
        receipt = original(runtime_self, *args, **kwargs)  # type: ignore[arg-type]
        return _unsafe_dataclass_copy(
            receipt,
            receipt_identity=_sha("rollback-public-evidence-malformed-receipt"),
        )  # type: ignore[return-value]

    monkeypatch.setattr(
        rt.C8TimedSessionRuntimeV1,
        "forward_timeout_due_signed_action_id_v1",
        return_malformed_receipt,
    )
    pre = _gameplay_snapshot(runtime, inner)
    result = controller.resolve_timeout_v1(ref, timeout_due_commitment=commitment)
    assert result.result_kind == ctl.ControllerResultKindV1.FAILED_ROLLED_BACK.value
    assert result.step_count == 1
    assert len(result.selected_actions) == 1
    assert len(result.legal_set_identities) == 1
    assert len(result.receipt_identities) == 1
    selected = result.selected_actions[0]
    assert selected.legal_set_identity == result.legal_set_identities[0]
    assert selected.receipt_identity == ""
    assert selected.issuance_evidence_identity == adapter.issuances[0].issuance_identity
    trace = controller.public_event_trace_v1()
    assert len(trace) == 1
    assert trace[0].event_kind == ctl.ControllerEventKindV1.ROLLED_BACK.value
    assert result.event_identities == (trace[0].event_identity,)
    assert result.event_chain_after_identity == trace[0].event_identity
    assert _gameplay_snapshot(runtime, inner) == pre
    _assert_public_only(result.to_public_dict_v1())
    _assert_public_only([event.to_public_dict_v1() for event in trace])


def test_public_result_and_trace_never_expose_inner_secret_payload() -> None:
    controller, _, _, inner, _, ref, commitment = _controller_harness(
        label="public-no-secret-leak"
    )
    inner.opaque_token_secret = "ULTRA-PRIVATE-C8-C-PAYLOAD-MARKER"
    result = controller.resolve_timeout_v1(ref, timeout_due_commitment=commitment)
    public_artifact = {
        "result": result.to_public_dict_v1(),
        "events": [
            event.to_public_dict_v1()
            for event in controller.public_event_trace_v1()
        ],
    }
    encoded = json.dumps(public_artifact, ensure_ascii=False, sort_keys=True)
    assert "ULTRA-PRIVATE-C8-C-PAYLOAD-MARKER" not in encoded
    assert "secret_counter" not in encoded
    assert "inner_snapshot_token" not in encoded


def test_controller_result_and_event_serialization_round_trip_is_canonical() -> None:
    controller, _, _, _, _, ref, commitment = _controller_harness(
        label="strict-result-round-trip"
    )
    result = controller.resolve_timeout_v1(ref, timeout_due_commitment=commitment)
    decoded = ctl.TimeoutControllerResultV1.from_json_bytes_v1(
        result.to_json_bytes_v1()
    )
    assert decoded == result
    assert decoded.to_json_bytes_v1() == result.to_json_bytes_v1()
    for event in controller.public_event_trace_v1():
        assert ctl.ControllerEventV1.from_public_dict_v1(
            _json_round_trip(event.to_public_dict_v1())
        ) == event
    with pytest.raises((AttributeError, TypeError)):
        result.reason = "mutation-must-fail"  # type: ignore[misc]


def test_controller_result_strict_serialization_rejects_unknown_missing_type_and_tamper() -> None:
    controller, _, _, _, _, ref, commitment = _controller_harness(
        label="strict-result-tamper"
    )
    result = controller.resolve_timeout_v1(ref, timeout_due_commitment=commitment)
    original = result.to_public_dict_v1()

    mutations: list[Callable[[dict[str, Any]], None]] = [
        lambda value: value.__setitem__("unknown_field", "forbidden"),
        lambda value: value.pop("reason"),
        lambda value: value.__setitem__("schema", "unknown-result-schema"),
        lambda value: value.__setitem__("contract_version", True),
        lambda value: value.__setitem__("result_kind", "UNKNOWN_RESULT"),
        lambda value: value.__setitem__("step_count", "1"),
        lambda value: value.__setitem__("selected_actions", tuple()),
        lambda value: value.__setitem__("legal_set_identities", tuple()),
        lambda value: value.__setitem__("result_identity", _sha("forged-result")),
        lambda value: value.__setitem__("reason", "deep-tamper"),
        lambda value: value["selected_actions"][0].__setitem__(
            "selection_identity", _sha("forged-selection")
        ),
        lambda value: value["selected_actions"][0].__setitem__(
            "unknown_nested", "forbidden"
        ),
    ]
    for mutate in mutations:
        payload = copy.deepcopy(original)
        mutate(payload)
        with pytest.raises((TypeError, ValueError, KeyError)):
            ctl.TimeoutControllerResultV1.from_public_dict_v1(payload)

    malformed_json = (
        b'{"schema":"sgs-c8-c-timeout-controller-result-v1",'
        b'"schema":"duplicate"}'
    )
    with pytest.raises((TypeError, ValueError, json.JSONDecodeError)):
        ctl.TimeoutControllerResultV1.from_json_bytes_v1(malformed_json)
    with pytest.raises((TypeError, ValueError)):
        ctl.TimeoutControllerResultV1.from_json_bytes_v1(b"[]")


def test_controller_event_strict_serialization_rejects_deep_tamper() -> None:
    controller, _, _, _, _, ref, commitment = _controller_harness(
        label="strict-event-tamper"
    )
    controller.resolve_timeout_v1(ref, timeout_due_commitment=commitment)
    event = controller.public_event_trace_v1()[0]
    original = event.to_public_dict_v1()
    for field, replacement in (
        ("event_kind", "UNKNOWN_EVENT"),
        ("event_sequence", True),
        ("previous_event_identity", _sha("wrong-previous")),
        ("details_identity", _sha("tampered-details")),
        ("event_identity", _sha("tampered-event")),
    ):
        payload = copy.deepcopy(original)
        payload[field] = replacement
        with pytest.raises((TypeError, ValueError)):
            ctl.ControllerEventV1.from_public_dict_v1(payload)
    for structural in ("unknown", "missing"):
        payload = copy.deepcopy(original)
        if structural == "unknown":
            payload["unknown_field"] = "forbidden"
        else:
            payload.pop("event_identity")
        with pytest.raises((TypeError, ValueError, KeyError)):
            ctl.ControllerEventV1.from_public_dict_v1(payload)


def test_controller_result_and_event_identities_are_deterministic() -> None:
    controller, _, _, _, _, ref, commitment = _controller_harness(
        label="deterministic-identities"
    )
    result = controller.resolve_timeout_v1(ref, timeout_due_commitment=commitment)
    first_bytes = result.to_json_bytes_v1()
    assert first_bytes == result.to_json_bytes_v1()
    result_payload = json.loads(first_bytes)
    identity_material = {
        key: value
        for key, value in result_payload.items()
        if key != "result_identity"
    }
    assert result_payload["result_identity"] == _canonical_identity(
        identity_material
    )
    trace = controller.public_event_trace_v1()
    assert result.event_identities == tuple(event.event_identity for event in trace)
    for index, event in enumerate(trace):
        assert event.event_identity == _canonical_identity(
            event.identity_payload_v1()
        )
        assert event.event_sequence == index + 1
        assert event.previous_event_identity == (
            "0" * 64 if index == 0 else trace[index - 1].event_identity
        )
