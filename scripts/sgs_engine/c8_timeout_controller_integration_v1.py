"""C8-C generic timeout resolver/controller integration (provisional).

This module deliberately sits above the frozen C8-A virtual-time contract and
the revised-current C8-B runtime wrapper.  It owns orchestration and public
evidence only.  It does not know an inner gameplay state, a private card
payload, RNG, or a wall clock.

The live C8-B timeout commitment and receipt objects are always passed back to
C8-B as the same objects.  This module reads their public identity fields but
never serializes or reconstructs either authority object.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import hashlib
import json
import threading
import weakref
from typing import (
    Any,
    Callable,
    ClassVar,
    Final,
    Mapping,
    Protocol,
    Sequence,
    runtime_checkable,
)

from . import c8_timed_session_runtime_v1 as rt
from . import c8_virtual_time_contract_v1 as c8


C8_C_CONTROLLER_ID: Final[str] = "c8-timeout-controller-integration-v1"
C8_C_SCHEMA_VERSION: Final[int] = 1

C8_A_REQUIRED_CONTRACT_IDENTITY: Final[str] = (
    "64f52c789ffb59d1fbdd0c9a4295109ff73be6bd50f2042666f4946f66f648c2"
)
C8_B_REQUIRED_RUNTIME_CONTRACT_IDENTITY: Final[str] = (
    "ce5a7c622dbecfc71423bf06bf0a94d447741aabe29a59cc23f36c1b1b2d8b55"
)
C8_B_REQUIRED_CURRENT_CONTRACT_LATCH_IDENTITY: Final[str] = (
    "eb2407ae7ce4f76dbf087fc4b351060c8fe60bf747e34635c454ec9f40a6657d"
)
C8_C_LIVE_COMMITMENT_PROBE_ACTION_REFERENCE: Final[str] = (
    "c8-c-timeout-live-commitment-probe-v1"
)

_ZERO_IDENTITY: Final[str] = "0" * 64
_HEX: Final[frozenset[str]] = frozenset("0123456789abcdef")

_CONTRACT_DESCRIPTOR: Final[Mapping[str, Any]] = {
    "schema": "sgs-c8-c-timeout-controller-contract-v1",
    "contract_version": 1,
    "controller_id": C8_C_CONTROLLER_ID,
    "c8_a_contract_identity": C8_A_REQUIRED_CONTRACT_IDENTITY,
    "c8_b_runtime_contract_identity": C8_B_REQUIRED_RUNTIME_CONTRACT_IDENTITY,
    "c8_b_current_contract_latch_identity": (
        C8_B_REQUIRED_CURRENT_CONTRACT_LATCH_IDENTITY
    ),
    "authority_pipeline": [
        "current-timeout-due-commitment",
        "trusted-guarded-fresh-public-legal-set",
        "frozen-c8-a-resolver",
        "trusted-guarded-fresh-issuance-confirmation",
        "controller-owned-pending-issuance-capability",
        "c8-b-capability-bound-timeout-forward",
        "typed-receipt-verification",
        "receipt-bound-close-or-same-tick-continuation",
    ],
    "same_tick_chain_max_steps": 8,
    "live_commitment_probe_action_reference": (
        C8_C_LIVE_COMMITMENT_PROBE_ACTION_REFERENCE
    ),
    "private_payload_access": False,
    "all_adapter_callbacks_use_b_trusted_controller_guard": True,
    "callback_operation_attempt_epoch_is_non_rollback_security_state": True,
    "pending_capability_owner_before_forward": "CONTROLLER_OWNED_PENDING",
    "pending_capability_abort_requires_adapter_guard_then_b_abort": True,
    "pending_capability_consumed_states_are_non_reviving": True,
    "receipt_completion_is_prebound_by_fresh_issuance": True,
    "production_signed_action_id_may_equal_public_action_reference": True,
    "signed_action_authority": (
        "FRESH_LEGAL_SET_CURRENT_STATE_ORDER_CONTEXT_CONFIRMATION"
    ),
    "single_driver_scope": "process-local-runtime-owner-tombstone-registry",
    "cross_process_single_driver": "OPEN_C8_D_OR_PRODUCTION_LEASE_DEBT",
    "rng": False,
    "wall_clock": False,
}


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _identity(value: Any) -> str:
    return hashlib.sha256(_canonical_json_bytes(value)).hexdigest()


C8_C_CONTRACT_IDENTITY: Final[str] = _identity(_CONTRACT_DESCRIPTOR)


def _require_exact_str(value: Any, name: str, *, nonempty: bool = True) -> str:
    if type(value) is not str:
        raise TypeError(f"{name} must be an exact str")
    if nonempty and not value:
        raise ValueError(f"{name} must be non-empty")
    return value


def _require_exact_int(
    value: Any, name: str, *, minimum: int | None = None
) -> int:
    if type(value) is not int:
        raise TypeError(f"{name} must be an exact int")
    if minimum is not None and value < minimum:
        raise ValueError(f"{name} must be >= {minimum}")
    return value


def _require_exact_bool(value: Any, name: str) -> bool:
    if type(value) is not bool:
        raise TypeError(f"{name} must be an exact bool")
    return value


def _require_identity(value: Any, name: str, *, allow_zero: bool = False) -> str:
    value = _require_exact_str(value, name)
    if len(value) != 64 or any(character not in _HEX for character in value):
        raise ValueError(f"{name} must be a lowercase SHA-256 identity")
    if not allow_zero and value == _ZERO_IDENTITY:
        raise ValueError(f"{name} must not be the zero identity")
    return value


def _enum_text(value: Any, name: str) -> str:
    if isinstance(value, Enum):
        value = value.value
    return _require_exact_str(value, name)


def _require_exact_keys(
    value: Any, expected: frozenset[str], name: str
) -> Mapping[str, Any]:
    if type(value) is not dict:
        raise TypeError(f"{name} must be an exact dict")
    actual = frozenset(value)
    if actual != expected:
        missing = sorted(expected - actual)
        unknown = sorted(actual - expected)
        raise ValueError(f"{name} key mismatch: missing={missing}, unknown={unknown}")
    return value


def _strict_json_object(raw: bytes | str) -> Mapping[str, Any]:
    if type(raw) is bytes:
        text = raw.decode("utf-8", errors="strict")
    elif type(raw) is str:
        text = raw
    else:
        raise TypeError("serialized result must be exact bytes or str")

    def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    decoded = json.loads(
        text,
        object_pairs_hook=reject_duplicate_keys,
        parse_constant=lambda token: (_ for _ in ()).throw(
            ValueError(f"non-finite JSON number: {token}")
        ),
    )
    if type(decoded) is not dict:
        raise TypeError("serialized result root must be an exact object")
    return decoded


def _object_fields_equal(left: Any, right: Any, fields: Sequence[str]) -> bool:
    if type(left) is not type(right):
        return False
    for field_name in fields:
        if not hasattr(left, field_name) or not hasattr(right, field_name):
            return False
        if getattr(left, field_name) != getattr(right, field_name):
            return False
    return True


_TIMEOUT_COMMITMENT_FIELDS: Final[tuple[str, ...]] = (
    "schema",
    "contract_version",
    "runtime_contract_identity",
    "runtime_instance_identity",
    "window_authority_ref_identity",
    "window_id",
    "actor_id",
    "decision_identity",
    "obligation_identity",
    "now_tick",
    "deadline_at",
    "virtual_time_state_identity",
    "pending_deadline_identity",
    "derived_deadline_identity",
    "caused_by_input_identity",
    "input_chain_tip",
    "event_chain_tip",
    "outer_state_identity",
    "commitment_identity",
)

_WINDOW_REF_FIELDS: Final[tuple[str, ...]] = (
    "schema",
    "contract_version",
    "runtime_instance_identity",
    "window_id",
    "parent_window_id",
    "actor_id",
    "window_kind",
    "decision_identity",
    "obligation_identity",
    "window_binding_identity",
    "authority_ref_identity",
)

_RUNTIME_OWNER_REGISTRY_LOCK: Final[threading.RLock] = threading.RLock()
_RUNTIME_OWNER_REGISTRY: Final[
    dict[str, tuple[weakref.ReferenceType[Any], threading.RLock]]
] = {}


def _claim_process_local_runtime_owner_v1(
    runtime_instance_identity: str, owner: Any
) -> threading.RLock:
    runtime_instance_identity = _require_identity(
        runtime_instance_identity, "runtime_instance_identity"
    )
    with _RUNTIME_OWNER_REGISTRY_LOCK:
        existing = _RUNTIME_OWNER_REGISTRY.get(runtime_instance_identity)
        if existing is not None:
            raise C8CContractError(
                "runtime identity already has a process-local C8-C owner/tombstone"
            )
        shared_lock = threading.RLock()
        # Deliberately retain a tombstone after owner GC.  Releasing merely on
        # object lifetime would permit a fresh controller with empty replay
        # ledgers to take over the still-live runtime identity.
        owner_ref = weakref.ref(owner)
        _RUNTIME_OWNER_REGISTRY[runtime_instance_identity] = (
            owner_ref,
            shared_lock,
        )
        return shared_lock


class ControllerResultKindV1(str, Enum):
    RESOLVED_SINGLE = "RESOLVED_SINGLE"
    RESOLVED_CHAIN = "RESOLVED_CHAIN"
    TIMEOUT_UNRESOLVED = "TIMEOUT_UNRESOLVED"
    CHAIN_CAP_EXHAUSTED = "CHAIN_CAP_EXHAUSTED"
    FAILED_ROLLED_BACK = "FAILED_ROLLED_BACK"
    FAILED_POISONED = "FAILED_POISONED"


class ControllerEventKindV1(str, Enum):
    RESOLUTION_STARTED = "RESOLUTION_STARTED"
    LEGAL_SET_BOUND = "LEGAL_SET_BOUND"
    FALLBACK_SELECTED = "FALLBACK_SELECTED"
    ISSUANCE_BOUND = "ISSUANCE_BOUND"
    RECEIPT_BOUND = "RECEIPT_BOUND"
    CHAIN_CONTINUED = "CHAIN_CONTINUED"
    WINDOW_RESOLVED = "WINDOW_RESOLVED"
    ROLLED_BACK = "ROLLED_BACK"


class C8CContractError(RuntimeError):
    """Base class for a fail-closed C8-C contract violation."""


class C8CReentrancyError(C8CContractError):
    """Raised into a nested callback that attempts another resolution."""


class C8CPoisonedError(C8CContractError):
    """Raised when rollback recovery or reentrancy poisoned the controller."""


@dataclass(frozen=True, slots=True)
class _AbortResolution(Exception):
    result_kind: ControllerResultKindV1
    reason: str


def canonical_public_ordering_identity_v1(
    public_legal_set: c8.PublicLegalSetProjectionV1,
) -> str:
    if type(public_legal_set) is not c8.PublicLegalSetProjectionV1:
        raise TypeError("public_legal_set must be exact PublicLegalSetProjectionV1")
    actions_payload: list[Mapping[str, Any]] = []
    seen_ordinals: set[int] = set()
    seen_candidates: set[str] = set()
    seen_references: set[str] = set()
    for index, candidate in enumerate(public_legal_set.actions):
        if type(candidate) is not c8.PublicLegalActionCandidateV1:
            raise TypeError("legal-set actions must be exact public candidates")
        ordinal = _require_exact_int(
            candidate.public_ordinal, "candidate.public_ordinal", minimum=0
        )
        if ordinal != index:
            raise ValueError("public ordinals must be contiguous canonical indices")
        candidate_identity = _require_identity(
            candidate.candidate_identity, "candidate.candidate_identity"
        )
        action_reference = _require_exact_str(
            candidate.action_id, "candidate.action_id"
        )
        if ordinal in seen_ordinals:
            raise ValueError("duplicate public ordinal")
        if candidate_identity in seen_candidates:
            raise ValueError("duplicate candidate identity")
        if action_reference in seen_references:
            raise ValueError("duplicate public action reference")
        seen_ordinals.add(ordinal)
        seen_candidates.add(candidate_identity)
        seen_references.add(action_reference)
        actions_payload.append(
            {
                "public_ordinal": ordinal,
                "candidate_identity": candidate_identity,
                "action_reference": action_reference,
                "action_family": _enum_text(
                    candidate.action_family, "candidate.action_family"
                ),
            }
        )
    return _identity(
        {
            "schema": "sgs-c8-c-canonical-public-ordering-v1",
            "contract_version": 1,
            "ordering_contract_id": _require_exact_str(
                public_legal_set.ordering_contract_id,
                "public_legal_set.ordering_contract_id",
            ),
            "actions": actions_payload,
        }
    )


def timeout_authentication_bindings_identity_v1(
    public_legal_set: c8.PublicLegalSetProjectionV1,
    candidate_bindings: Sequence[tuple[str, str, str]],
) -> str:
    if type(candidate_bindings) not in (tuple, list):
        raise TypeError("candidate_bindings must be a tuple or list")
    if len(candidate_bindings) != len(public_legal_set.actions):
        raise ValueError("candidate binding count must match legal-set actions")
    payload: list[Mapping[str, str]] = []
    for candidate, binding in zip(public_legal_set.actions, candidate_bindings):
        if type(binding) is not tuple or len(binding) != 3:
            raise TypeError("each candidate binding must be an exact three-tuple")
        candidate_identity, action_reference, binding_identity = binding
        if candidate_identity != candidate.candidate_identity:
            raise ValueError("candidate binding identity/order mismatch")
        if action_reference != candidate.action_id:
            raise ValueError("candidate binding action-reference mismatch")
        payload.append(
            {
                "candidate_identity": _require_identity(
                    candidate_identity, "candidate_binding.candidate_identity"
                ),
                "action_reference": _require_exact_str(
                    action_reference, "candidate_binding.action_reference"
                ),
                "authorization_binding_identity": _require_identity(
                    binding_identity,
                    "candidate_binding.authorization_binding_identity",
                ),
            }
        )
    return _identity(
        {
            "schema": "sgs-c8-c-timeout-authentication-bindings-v1",
            "contract_version": 1,
            "projection_legal_set_identity": _require_identity(
                public_legal_set.legal_set_identity,
                "public_legal_set.legal_set_identity",
            ),
            "candidate_bindings": payload,
        }
    )


def signed_action_id_commitment_v1(signed_action_id: str) -> str:
    """Mirror C8-B's public commitment without exposing the signed identifier."""

    return _identity(
        {
            "schema": "sgs-c8-b-timeout-signed-action-id-commitment-v1",
            "contract_version": 1,
            "signed_action_id": _require_exact_str(
                signed_action_id, "signed_action_id"
            ),
        }
    )


def timeout_issuance_request_binding_v1(
    *,
    timeout_due_commitment_identity: str,
    runtime_instance_identity: str,
    window_authority_ref_identity: str,
    session_identity: str,
    controller_identity: str,
    adapter_identity: str,
    projection_legal_set_identity: str,
    adapter_legal_set_snapshot_identity: str,
    canonical_public_ordering_identity: str,
    candidate: c8.PublicLegalActionCandidateV1,
) -> str:
    """Bind a public candidate to the exact fresh controller issuance request.

    This is deliberately distinct from C8-B's final authorization binding.  The
    latter can only be derived after the latest B seam registers the live,
    controller-owned pending issuance capability.
    """

    if type(candidate) is not c8.PublicLegalActionCandidateV1:
        raise TypeError("candidate must be an exact C8-A public candidate")
    candidate.__post_init__()
    return _identity(
        {
            "schema": "sgs-c8-c-timeout-issuance-request-binding-v1",
            "contract_version": 1,
            "timeout_due_commitment_identity": _require_identity(
                timeout_due_commitment_identity,
                "timeout_due_commitment_identity",
            ),
            "runtime_instance_identity": _require_identity(
                runtime_instance_identity, "runtime_instance_identity"
            ),
            "window_authority_ref_identity": _require_identity(
                window_authority_ref_identity,
                "window_authority_ref_identity",
            ),
            "session_identity": _require_identity(
                session_identity, "session_identity"
            ),
            "controller_identity": _require_identity(
                controller_identity, "controller_identity"
            ),
            "adapter_identity": _require_identity(
                adapter_identity, "adapter_identity"
            ),
            "projection_legal_set_identity": _require_identity(
                projection_legal_set_identity,
                "projection_legal_set_identity",
            ),
            "adapter_legal_set_snapshot_identity": _require_identity(
                adapter_legal_set_snapshot_identity,
                "adapter_legal_set_snapshot_identity",
            ),
            "canonical_public_ordering_identity": _require_identity(
                canonical_public_ordering_identity,
                "canonical_public_ordering_identity",
            ),
            "candidate_identity": candidate.candidate_identity,
            "public_action_reference": candidate.action_id,
            "public_ordinal": candidate.public_ordinal,
            "action_family": _enum_text(
                candidate.action_family, "candidate.action_family"
            ),
        }
    )


@dataclass(frozen=True, slots=True)
class AdapterPublicLegalActionsSnapshotV1:
    """Adapter-originated public snapshot before C8-C adds B auth bindings."""

    schema: str
    contract_version: int
    public_legal_set: c8.PublicLegalSetProjectionV1
    projection_legal_set_identity: str
    canonical_public_ordering_identity: str
    runtime_instance_identity: str
    window_authority_ref_identity: str
    window_id: str
    decision_identity: str
    obligation_identity: str
    session_identity: str
    controller_identity: str
    adapter_identity: str
    public_state_identity: str
    authoritative_state_identity: str
    issuance_security_ledger_identity: str
    snapshot_identity: str

    def __post_init__(self) -> None:
        _require_exact_str(self.schema, "schema")
        if self.schema != "sgs-c8-c-adapter-public-legal-actions-snapshot-v1":
            raise ValueError("invalid adapter public legal-set snapshot schema")
        if type(self.contract_version) is not int or self.contract_version != 1:
            raise ValueError("invalid adapter public legal-set snapshot version")
        if type(self.public_legal_set) is not c8.PublicLegalSetProjectionV1:
            raise TypeError("public_legal_set must be exact C8-A public projection")
        if self.projection_legal_set_identity != self.public_legal_set.legal_set_identity:
            raise ValueError("adapter projection legal-set identity mismatch")
        if self.canonical_public_ordering_identity != (
            canonical_public_ordering_identity_v1(self.public_legal_set)
        ):
            raise ValueError("adapter canonical ordering identity mismatch")
        _require_exact_str(self.window_id, "window_id")
        for name in (
            "projection_legal_set_identity",
            "canonical_public_ordering_identity",
            "runtime_instance_identity",
            "window_authority_ref_identity",
            "decision_identity",
            "obligation_identity",
            "session_identity",
            "controller_identity",
            "adapter_identity",
            "public_state_identity",
            "authoritative_state_identity",
            "issuance_security_ledger_identity",
            "snapshot_identity",
        ):
            _require_identity(getattr(self, name), name)
        if self.snapshot_identity != _identity(self.identity_payload_v1()):
            raise ValueError("adapter public legal-set snapshot identity mismatch")

    def identity_payload_v1(self) -> Mapping[str, Any]:
        return {
            "schema": self.schema,
            "contract_version": self.contract_version,
            "projection_legal_set_identity": self.projection_legal_set_identity,
            "canonical_public_ordering_identity": (
                self.canonical_public_ordering_identity
            ),
            "runtime_instance_identity": self.runtime_instance_identity,
            "window_authority_ref_identity": self.window_authority_ref_identity,
            "window_id": self.window_id,
            "decision_identity": self.decision_identity,
            "obligation_identity": self.obligation_identity,
            "session_identity": self.session_identity,
            "controller_identity": self.controller_identity,
            "adapter_identity": self.adapter_identity,
            "public_state_identity": self.public_state_identity,
            "authoritative_state_identity": self.authoritative_state_identity,
            "issuance_security_ledger_identity": (
                self.issuance_security_ledger_identity
            ),
        }


def build_adapter_public_legal_actions_snapshot_v1(
    *,
    public_legal_set: c8.PublicLegalSetProjectionV1,
    runtime_instance_identity: str,
    window_authority_ref_identity: str,
    session_identity: str,
    controller_identity: str,
    adapter_identity: str,
    public_state_identity: str,
    authoritative_state_identity: str,
    issuance_security_ledger_identity: str,
) -> AdapterPublicLegalActionsSnapshotV1:
    values: dict[str, Any] = {
        "schema": "sgs-c8-c-adapter-public-legal-actions-snapshot-v1",
        "contract_version": 1,
        "public_legal_set": public_legal_set,
        "projection_legal_set_identity": public_legal_set.legal_set_identity,
        "canonical_public_ordering_identity": (
            canonical_public_ordering_identity_v1(public_legal_set)
        ),
        "runtime_instance_identity": runtime_instance_identity,
        "window_authority_ref_identity": window_authority_ref_identity,
        "window_id": public_legal_set.window_id,
        "decision_identity": public_legal_set.decision_identity,
        "obligation_identity": public_legal_set.obligation_identity,
        "session_identity": session_identity,
        "controller_identity": controller_identity,
        "adapter_identity": adapter_identity,
        "public_state_identity": public_state_identity,
        "authoritative_state_identity": authoritative_state_identity,
        "issuance_security_ledger_identity": issuance_security_ledger_identity,
    }
    values["snapshot_identity"] = _identity(
        {
            key: value
            for key, value in values.items()
            if key != "public_legal_set"
        }
    )
    return AdapterPublicLegalActionsSnapshotV1(**values)


@dataclass(frozen=True, slots=True)
class FreshPublicLegalActionsEnvelopeV1:
    """Strict public adapter envelope; ``public_legal_set`` is C8-A's type."""

    schema: str
    contract_version: int
    public_legal_set: c8.PublicLegalSetProjectionV1
    projection_legal_set_identity: str
    adapter_legal_set_snapshot_identity: str
    legal_set_identity: str
    canonical_public_ordering_identity: str
    timeout_authentication_bindings_identity: str
    timeout_due_commitment_identity: str
    runtime_contract_identity: str
    runtime_instance_identity: str
    window_authority_ref_identity: str
    window_id: str
    decision_identity: str
    obligation_identity: str
    session_identity: str
    controller_identity: str
    adapter_identity: str
    public_state_identity: str
    authoritative_state_identity: str
    issuance_security_ledger_identity: str

    def __post_init__(self) -> None:
        _require_exact_str(self.schema, "schema")
        if self.schema != "sgs-c8-c-fresh-public-legal-actions-envelope-v1":
            raise ValueError("invalid fresh legal-set envelope schema")
        if type(self.contract_version) is not int or self.contract_version != 1:
            raise ValueError("invalid fresh legal-set envelope version")
        if type(self.public_legal_set) is not c8.PublicLegalSetProjectionV1:
            raise TypeError("public_legal_set must be exact C8-A public projection")
        if self.projection_legal_set_identity != self.public_legal_set.legal_set_identity:
            raise ValueError("projection legal-set identity mismatch")
        if self.canonical_public_ordering_identity != (
            canonical_public_ordering_identity_v1(self.public_legal_set)
        ):
            raise ValueError("canonical public ordering identity mismatch")
        for name in (
            "projection_legal_set_identity",
            "adapter_legal_set_snapshot_identity",
            "legal_set_identity",
            "canonical_public_ordering_identity",
            "timeout_authentication_bindings_identity",
            "timeout_due_commitment_identity",
            "runtime_contract_identity",
            "runtime_instance_identity",
            "window_authority_ref_identity",
            "decision_identity",
            "obligation_identity",
            "session_identity",
            "controller_identity",
            "adapter_identity",
            "public_state_identity",
            "authoritative_state_identity",
            "issuance_security_ledger_identity",
        ):
            _require_identity(getattr(self, name), name)
        _require_exact_str(self.window_id, "window_id")
        expected_identity = _fresh_legal_set_identity_payload_v1(self)
        if self.legal_set_identity != _identity(expected_identity):
            raise ValueError("enriched legal-set identity mismatch")


def _fresh_legal_set_identity_payload_v1(
    envelope: FreshPublicLegalActionsEnvelopeV1,
) -> Mapping[str, Any]:
    return {
        "schema": "sgs-c8-c-bound-public-legal-set-identity-v1",
        "contract_version": 1,
        "projection_legal_set_identity": envelope.projection_legal_set_identity,
        "adapter_legal_set_snapshot_identity": (
            envelope.adapter_legal_set_snapshot_identity
        ),
        "canonical_public_ordering_identity": (
            envelope.canonical_public_ordering_identity
        ),
        "timeout_authentication_bindings_identity": (
            envelope.timeout_authentication_bindings_identity
        ),
        "timeout_due_commitment_identity": envelope.timeout_due_commitment_identity,
        "runtime_contract_identity": envelope.runtime_contract_identity,
        "runtime_instance_identity": envelope.runtime_instance_identity,
        "window_authority_ref_identity": envelope.window_authority_ref_identity,
        "window_id": envelope.window_id,
        "decision_identity": envelope.decision_identity,
        "obligation_identity": envelope.obligation_identity,
        "session_identity": envelope.session_identity,
        "controller_identity": envelope.controller_identity,
        "adapter_identity": envelope.adapter_identity,
        "public_state_identity": envelope.public_state_identity,
        "authoritative_state_identity": envelope.authoritative_state_identity,
        "issuance_security_ledger_identity": (
            envelope.issuance_security_ledger_identity
        ),
    }


def build_fresh_public_legal_actions_envelope_v1(
    *,
    public_legal_set: c8.PublicLegalSetProjectionV1,
    adapter_legal_set_snapshot_identity: str,
    timeout_authentication_bindings_identity: str,
    timeout_due_commitment_identity: str,
    runtime_contract_identity: str,
    runtime_instance_identity: str,
    window_authority_ref_identity: str,
    session_identity: str,
    controller_identity: str,
    adapter_identity: str,
    public_state_identity: str,
    authoritative_state_identity: str,
    issuance_security_ledger_identity: str,
) -> FreshPublicLegalActionsEnvelopeV1:
    ordering_identity = canonical_public_ordering_identity_v1(public_legal_set)
    provisional = FreshPublicLegalActionsEnvelopeV1.__new__(
        FreshPublicLegalActionsEnvelopeV1
    )
    values = {
        "schema": "sgs-c8-c-fresh-public-legal-actions-envelope-v1",
        "contract_version": 1,
        "public_legal_set": public_legal_set,
        "projection_legal_set_identity": public_legal_set.legal_set_identity,
        "adapter_legal_set_snapshot_identity": (
            adapter_legal_set_snapshot_identity
        ),
        "legal_set_identity": _ZERO_IDENTITY,
        "canonical_public_ordering_identity": ordering_identity,
        "timeout_authentication_bindings_identity": (
            timeout_authentication_bindings_identity
        ),
        "timeout_due_commitment_identity": timeout_due_commitment_identity,
        "runtime_contract_identity": runtime_contract_identity,
        "runtime_instance_identity": runtime_instance_identity,
        "window_authority_ref_identity": window_authority_ref_identity,
        "window_id": public_legal_set.window_id,
        "decision_identity": public_legal_set.decision_identity,
        "obligation_identity": public_legal_set.obligation_identity,
        "session_identity": session_identity,
        "controller_identity": controller_identity,
        "adapter_identity": adapter_identity,
        "public_state_identity": public_state_identity,
        "authoritative_state_identity": authoritative_state_identity,
        "issuance_security_ledger_identity": issuance_security_ledger_identity,
    }
    for field_name, field_value in values.items():
        object.__setattr__(provisional, field_name, field_value)
    values["legal_set_identity"] = _identity(
        _fresh_legal_set_identity_payload_v1(provisional)
    )
    return FreshPublicLegalActionsEnvelopeV1(**values)


@dataclass(frozen=True, slots=True)
class SignedActionIssuanceEvidenceV1:
    schema: str
    contract_version: int
    signed_action_id: str
    signed_action_id_commitment: str
    external_capability_identity: str
    public_action_reference: str
    public_ordinal: int
    candidate_identity: str
    action_family: str
    legal_set_identity: str
    canonical_public_ordering_identity: str
    timeout_due_commitment_identity: str
    authorization_binding_identity: str
    issuance_authority_identity: str
    authorization_evidence_identity: str
    runtime_instance_identity: str
    window_authority_ref_identity: str
    window_id: str
    session_identity: str
    controller_identity: str
    adapter_identity: str
    public_state_identity: str
    authoritative_state_identity: str
    issuance_security_ledger_before_identity: str
    issuance_security_ledger_after_identity: str
    obligation_completed: bool
    issuance_identity: str
    external_capability: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        _require_exact_str(self.schema, "schema")
        if self.schema != "sgs-c8-c-signed-action-issuance-evidence-v1":
            raise ValueError("invalid issuance evidence schema")
        if type(self.contract_version) is not int or self.contract_version != 1:
            raise ValueError("invalid issuance evidence version")
        _require_exact_str(self.signed_action_id, "signed_action_id")
        _require_exact_str(self.public_action_reference, "public_action_reference")
        if self.signed_action_id_commitment != signed_action_id_commitment_v1(
            self.signed_action_id
        ):
            raise ValueError("signed action commitment mismatch")
        if self.external_capability is None:
            raise ValueError("external capability handle must be live and non-null")
        _require_exact_int(self.public_ordinal, "public_ordinal", minimum=0)
        _require_exact_bool(self.obligation_completed, "obligation_completed")
        _require_exact_str(self.action_family, "action_family")
        if self.action_family not in {
            _enum_text(item, "public_action_family")
            for item in c8.PublicActionFamilyV1
        }:
            raise ValueError("unknown public action family")
        _require_exact_str(self.window_id, "window_id")
        for name in (
            "candidate_identity",
            "signed_action_id_commitment",
            "external_capability_identity",
            "legal_set_identity",
            "canonical_public_ordering_identity",
            "timeout_due_commitment_identity",
            "authorization_binding_identity",
            "issuance_authority_identity",
            "authorization_evidence_identity",
            "runtime_instance_identity",
            "window_authority_ref_identity",
            "session_identity",
            "controller_identity",
            "adapter_identity",
            "public_state_identity",
            "authoritative_state_identity",
            "issuance_security_ledger_before_identity",
            "issuance_security_ledger_after_identity",
            "issuance_identity",
        ):
            _require_identity(getattr(self, name), name)
        if self.issuance_identity != _identity(self.identity_payload_v1()):
            raise ValueError("issuance evidence identity mismatch")
        if (
            self.issuance_security_ledger_before_identity
            == self.issuance_security_ledger_after_identity
        ):
            raise ValueError("issuance security ledger must advance on confirmation")

    def identity_payload_v1(self) -> Mapping[str, Any]:
        return {
            "schema": self.schema,
            "contract_version": self.contract_version,
            "signed_action_id": self.signed_action_id,
            "signed_action_id_commitment": self.signed_action_id_commitment,
            "external_capability_identity": self.external_capability_identity,
            "public_action_reference": self.public_action_reference,
            "public_ordinal": self.public_ordinal,
            "candidate_identity": self.candidate_identity,
            "action_family": self.action_family,
            "legal_set_identity": self.legal_set_identity,
            "canonical_public_ordering_identity": (
                self.canonical_public_ordering_identity
            ),
            "timeout_due_commitment_identity": self.timeout_due_commitment_identity,
            "authorization_binding_identity": self.authorization_binding_identity,
            "issuance_authority_identity": self.issuance_authority_identity,
            "authorization_evidence_identity": self.authorization_evidence_identity,
            "runtime_instance_identity": self.runtime_instance_identity,
            "window_authority_ref_identity": self.window_authority_ref_identity,
            "window_id": self.window_id,
            "session_identity": self.session_identity,
            "controller_identity": self.controller_identity,
            "adapter_identity": self.adapter_identity,
            "public_state_identity": self.public_state_identity,
            "authoritative_state_identity": self.authoritative_state_identity,
            "issuance_security_ledger_before_identity": (
                self.issuance_security_ledger_before_identity
            ),
            "issuance_security_ledger_after_identity": (
                self.issuance_security_ledger_after_identity
            ),
            "obligation_completed": self.obligation_completed,
        }


def build_signed_action_issuance_evidence_v1(**values: Any) -> SignedActionIssuanceEvidenceV1:
    if "external_capability" not in values:
        raise TypeError("external_capability is required")
    external_capability = values.pop("external_capability")
    payload = {
        "schema": "sgs-c8-c-signed-action-issuance-evidence-v1",
        "contract_version": 1,
        **values,
    }
    payload["issuance_identity"] = _identity(payload)
    return SignedActionIssuanceEvidenceV1(
        **payload,
        external_capability=external_capability,
    )


@dataclass(frozen=True, slots=True)
class ReceiptLineageCompletionEvidenceV1:
    schema: str
    contract_version: int
    receipt_identity: str
    issuance_identity: str
    legal_set_identity: str
    runtime_instance_identity: str
    window_authority_ref_identity: str
    window_id: str
    decision_identity: str
    obligation_identity: str
    session_identity: str
    controller_identity: str
    adapter_identity: str
    post_public_state_identity: str
    post_authoritative_state_identity: str
    obligation_completed: bool
    completion_evidence_identity: str

    def __post_init__(self) -> None:
        _require_exact_str(self.schema, "schema")
        if self.schema != "sgs-c8-c-receipt-lineage-completion-evidence-v1":
            raise ValueError("invalid completion evidence schema")
        if type(self.contract_version) is not int or self.contract_version != 1:
            raise ValueError("invalid completion evidence version")
        _require_exact_str(self.window_id, "window_id")
        _require_exact_bool(self.obligation_completed, "obligation_completed")
        for name in (
            "receipt_identity",
            "issuance_identity",
            "legal_set_identity",
            "runtime_instance_identity",
            "window_authority_ref_identity",
            "decision_identity",
            "obligation_identity",
            "session_identity",
            "controller_identity",
            "adapter_identity",
            "post_public_state_identity",
            "post_authoritative_state_identity",
            "completion_evidence_identity",
        ):
            _require_identity(getattr(self, name), name)
        if self.completion_evidence_identity != _identity(self.identity_payload_v1()):
            raise ValueError("completion evidence identity mismatch")

    def identity_payload_v1(self) -> Mapping[str, Any]:
        return {
            "schema": self.schema,
            "contract_version": self.contract_version,
            "receipt_identity": self.receipt_identity,
            "issuance_identity": self.issuance_identity,
            "legal_set_identity": self.legal_set_identity,
            "runtime_instance_identity": self.runtime_instance_identity,
            "window_authority_ref_identity": self.window_authority_ref_identity,
            "window_id": self.window_id,
            "decision_identity": self.decision_identity,
            "obligation_identity": self.obligation_identity,
            "session_identity": self.session_identity,
            "controller_identity": self.controller_identity,
            "adapter_identity": self.adapter_identity,
            "post_public_state_identity": self.post_public_state_identity,
            "post_authoritative_state_identity": (
                self.post_authoritative_state_identity
            ),
            "obligation_completed": self.obligation_completed,
        }


def build_receipt_lineage_completion_evidence_v1(
    **values: Any,
) -> ReceiptLineageCompletionEvidenceV1:
    payload = {
        "schema": "sgs-c8-c-receipt-lineage-completion-evidence-v1",
        "contract_version": 1,
        **values,
    }
    payload["completion_evidence_identity"] = _identity(payload)
    return ReceiptLineageCompletionEvidenceV1(**payload)


@dataclass(frozen=True, slots=True)
class UnforwardedIssuanceInvalidationEvidenceV1:
    """Proof that an adapter-side pending capability was revoked.

    The ledger fields belong only to the issuance adapter.  This hook must not
    advance C8-B's consumed-authorization anti-replay ledger out of band.
    """

    schema: str
    contract_version: int
    issuance_identity: str
    authorization_evidence_identity: str
    runtime_instance_identity: str
    window_authority_ref_identity: str
    session_identity: str
    controller_identity: str
    adapter_identity: str
    security_ledger_before_identity: str
    security_ledger_after_identity: str
    invalidated: bool
    invalidation_identity: str

    def __post_init__(self) -> None:
        _require_exact_str(self.schema, "schema")
        if self.schema != "sgs-c8-c-unforwarded-issuance-invalidation-v1":
            raise ValueError("invalid issuance invalidation schema")
        if type(self.contract_version) is not int or self.contract_version != 1:
            raise ValueError("invalid issuance invalidation version")
        _require_exact_bool(self.invalidated, "invalidated")
        if self.invalidated is not True:
            raise ValueError("unforwarded issuance must be invalidated")
        for name in (
            "issuance_identity",
            "authorization_evidence_identity",
            "runtime_instance_identity",
            "window_authority_ref_identity",
            "session_identity",
            "controller_identity",
            "adapter_identity",
            "security_ledger_before_identity",
            "security_ledger_after_identity",
            "invalidation_identity",
        ):
            _require_identity(getattr(self, name), name)
        if self.security_ledger_before_identity == self.security_ledger_after_identity:
            raise ValueError("invalidation security ledger must advance")
        if self.invalidation_identity != _identity(self.identity_payload_v1()):
            raise ValueError("issuance invalidation identity mismatch")

    def identity_payload_v1(self) -> Mapping[str, Any]:
        return {
            "schema": self.schema,
            "contract_version": self.contract_version,
            "issuance_identity": self.issuance_identity,
            "authorization_evidence_identity": self.authorization_evidence_identity,
            "runtime_instance_identity": self.runtime_instance_identity,
            "window_authority_ref_identity": self.window_authority_ref_identity,
            "session_identity": self.session_identity,
            "controller_identity": self.controller_identity,
            "adapter_identity": self.adapter_identity,
            "security_ledger_before_identity": self.security_ledger_before_identity,
            "security_ledger_after_identity": self.security_ledger_after_identity,
            "invalidated": self.invalidated,
        }


def build_unforwarded_issuance_invalidation_evidence_v1(
    **values: Any,
) -> UnforwardedIssuanceInvalidationEvidenceV1:
    payload = {
        "schema": "sgs-c8-c-unforwarded-issuance-invalidation-v1",
        "contract_version": 1,
        **values,
    }
    payload["invalidation_identity"] = _identity(payload)
    return UnforwardedIssuanceInvalidationEvidenceV1(**payload)


@dataclass(frozen=True, slots=True)
class FailedIssuanceRecoveryEvidenceV1:
    """Proof that all adapter-side capabilities created by a failed confirm died.

    Recovery revokes pending capabilities in the adapter's separate monotonic
    security ledger.  It never records a B-consumed authorization; only B's
    forward seam may advance B's consumed-authorization anti-replay ledger.
    """

    schema: str
    contract_version: int
    transaction_identity: str
    legal_set_identity: str
    candidate_reference: str
    public_ordinal: int
    timeout_auth_binding: str
    runtime_instance_identity: str
    window_authority_ref_identity: str
    session_identity: str
    controller_identity: str
    adapter_identity: str
    security_ledger_before_identity: str
    security_ledger_observed_after_failure_identity: str
    security_ledger_after_recovery_identity: str
    recovered_evidence_set_identity: str
    recovered_evidence_count: int
    recovered: bool
    recovery_identity: str

    def __post_init__(self) -> None:
        _require_exact_str(self.schema, "schema")
        if self.schema != "sgs-c8-c-failed-issuance-recovery-evidence-v1":
            raise ValueError("invalid failed issuance recovery schema")
        if type(self.contract_version) is not int or self.contract_version != 1:
            raise ValueError("invalid failed issuance recovery version")
        _require_exact_str(self.candidate_reference, "candidate_reference")
        _require_exact_int(self.public_ordinal, "public_ordinal", minimum=0)
        _require_exact_bool(self.recovered, "recovered")
        if self.recovered is not True:
            raise ValueError("failed issuance recovery must prove recovered=True")
        _require_exact_int(
            self.recovered_evidence_count,
            "recovered_evidence_count",
            minimum=1,
        )
        for name in (
            "transaction_identity",
            "legal_set_identity",
            "timeout_auth_binding",
            "runtime_instance_identity",
            "window_authority_ref_identity",
            "session_identity",
            "controller_identity",
            "adapter_identity",
            "security_ledger_before_identity",
            "security_ledger_observed_after_failure_identity",
            "security_ledger_after_recovery_identity",
            "recovered_evidence_set_identity",
            "recovery_identity",
        ):
            _require_identity(getattr(self, name), name)
        if (
            self.security_ledger_before_identity
            == self.security_ledger_observed_after_failure_identity
        ):
            raise ValueError("recovery proof requires a failed-confirm ledger advance")
        if (
            self.security_ledger_observed_after_failure_identity
            == self.security_ledger_after_recovery_identity
        ):
            raise ValueError("adapter recovery ledger must advance")
        if self.recovery_identity != _identity(self.identity_payload_v1()):
            raise ValueError("failed issuance recovery identity mismatch")

    def identity_payload_v1(self) -> Mapping[str, Any]:
        return {
            "schema": self.schema,
            "contract_version": self.contract_version,
            "transaction_identity": self.transaction_identity,
            "legal_set_identity": self.legal_set_identity,
            "candidate_reference": self.candidate_reference,
            "public_ordinal": self.public_ordinal,
            "timeout_auth_binding": self.timeout_auth_binding,
            "runtime_instance_identity": self.runtime_instance_identity,
            "window_authority_ref_identity": self.window_authority_ref_identity,
            "session_identity": self.session_identity,
            "controller_identity": self.controller_identity,
            "adapter_identity": self.adapter_identity,
            "security_ledger_before_identity": self.security_ledger_before_identity,
            "security_ledger_observed_after_failure_identity": (
                self.security_ledger_observed_after_failure_identity
            ),
            "security_ledger_after_recovery_identity": (
                self.security_ledger_after_recovery_identity
            ),
            "recovered_evidence_set_identity": self.recovered_evidence_set_identity,
            "recovered_evidence_count": self.recovered_evidence_count,
            "recovered": self.recovered,
        }


def build_failed_issuance_recovery_evidence_v1(
    **values: Any,
) -> FailedIssuanceRecoveryEvidenceV1:
    payload = {
        "schema": "sgs-c8-c-failed-issuance-recovery-evidence-v1",
        "contract_version": 1,
        **values,
    }
    payload["recovery_identity"] = _identity(payload)
    return FailedIssuanceRecoveryEvidenceV1(**payload)


@runtime_checkable
class PublicLegalActionsIssuanceAdapterV1(Protocol):
    """Public-only adapter.  No private-state or private-payload accessor exists."""

    def current_adapter_identity_v1(self) -> str: ...

    def current_session_identity_v1(self) -> str: ...

    def current_controller_identity_v1(self) -> str: ...

    def current_public_state_identity_v1(self) -> str: ...

    def current_authoritative_state_identity_v1(self) -> str: ...

    def current_issuance_authority_identity_v1(self) -> str: ...

    def current_issuance_security_ledger_identity_v1(self) -> str: ...

    def current_consumed_authorization_ledger_identity_v1(self) -> str: ...

    def current_public_legal_set_snapshot_identity_v1(self) -> str: ...

    def current_canonical_public_ordering_identity_v1(self) -> str: ...

    def fresh_public_legal_actions_v1(self) -> AdapterPublicLegalActionsSnapshotV1: ...

    def confirm_and_issue_signed_action_v1(
        self,
        candidate_reference: str,
        public_ordinal: int,
        legal_set_identity: str,
        timeout_auth_binding: str,
        timeout_due_commitment_identity: str,
    ) -> SignedActionIssuanceEvidenceV1: ...

    def abort_pending_issuance_v1(
        self,
        external_capability: object,
    ) -> UnforwardedIssuanceInvalidationEvidenceV1: ...

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
    ) -> FailedIssuanceRecoveryEvidenceV1: ...


@runtime_checkable
class TimedSessionRuntimeV1(Protocol):
    @property
    def state(self) -> Any: ...

    def public_projection(self) -> Any: ...

    def capture_transaction(self) -> rt.TimedSessionTransactionSnapshotV1: ...

    def rollback(self, snapshot: rt.TimedSessionTransactionSnapshotV1) -> None: ...

    def current_timeout_due_commitment_v1(self, window_authority_ref: Any) -> Any: ...

    def expected_timeout_action_authentication_binding_v1(
        self,
        window_authority_ref: Any,
        *,
        timeout_due_commitment: Any,
        signed_action_id: str,
        pending_issuance_capability: rt.PendingTimeoutIssuanceCapabilityV1 | None = None,
    ) -> str: ...

    def issue_controller_callback_lease_v1(
        self,
        window_authority_ref: Any,
        *,
        timeout_due_commitment: Any,
        controller_identity: str,
        adapter_identity: str,
    ) -> rt.ControllerCallbackLeaseV1: ...

    def begin_controller_callback_guard_v1(
        self, lease: rt.ControllerCallbackLeaseV1
    ) -> rt.ControllerCallbackGuardTokenV1: ...

    def release_controller_callback_guard_v1(
        self, token: rt.ControllerCallbackGuardTokenV1
    ) -> rt.ControllerCallbackGuardResultV1: ...

    def invoke_controller_callback_guarded_v1(
        self,
        lease: rt.ControllerCallbackLeaseV1,
        callback: Callable[[], object],
    ) -> rt.ControllerCallbackInvocationResultV1: ...

    def register_pending_timeout_issuance_capability_v1(
        self,
        window_authority_ref: Any,
        *,
        timeout_due_commitment: Any,
        guard_result: rt.ControllerCallbackGuardResultV1,
        signed_action_id: str,
        external_capability_identity: str,
    ) -> rt.PendingTimeoutIssuanceCapabilityV1: ...

    def current_pending_issuance_capability_ownership_v1(
        self, capability: rt.PendingTimeoutIssuanceCapabilityV1
    ) -> rt.PendingIssuanceCapabilityOwnershipV1: ...

    def abort_pending_timeout_issuance_capability_v1(
        self, capability: rt.PendingTimeoutIssuanceCapabilityV1
    ) -> rt.PendingIssuanceCapabilityOwnershipV1: ...

    def forward_timeout_due_signed_action_id_v1(
        self,
        window_authority_ref: Any,
        *,
        timeout_due_commitment: Any,
        signed_action_id: str,
        authorization_evidence_identity: str,
        pending_issuance_capability: rt.PendingTimeoutIssuanceCapabilityV1 | None = None,
    ) -> rt.TimeoutActionExecutionReceiptV1: ...

    def close_window_by_timeout_receipt_v1(
        self,
        window_authority_ref: Any,
        *,
        execution_receipt: rt.TimeoutActionExecutionReceiptV1,
    ) -> c8.TimedDecisionWindowV1: ...

    def continue_timeout_multi_step_obligation_v1(
        self,
        window_authority_ref: Any,
        *,
        execution_receipt: rt.TimeoutActionExecutionReceiptV1,
        expected_step_index: int,
        logical_step_identity: str,
    ) -> c8.DeadlinePrecedenceV1: ...


@dataclass(frozen=True, slots=True)
class PublicSelectedActionV1:
    schema: str
    contract_version: int
    step_index: int
    legal_set_identity: str
    canonical_public_ordering_identity: str
    public_ordinal: int
    public_action_reference: str
    signed_action_id: str
    candidate_identity: str
    action_family: str
    issuance_evidence_identity: str
    receipt_identity: str
    selection_identity: str

    _KEYS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "contract_version",
            "step_index",
            "legal_set_identity",
            "canonical_public_ordering_identity",
            "public_ordinal",
            "public_action_reference",
            "signed_action_id",
            "candidate_identity",
            "action_family",
            "issuance_evidence_identity",
            "receipt_identity",
            "selection_identity",
        }
    )

    def __post_init__(self) -> None:
        _require_exact_str(self.schema, "schema")
        if self.schema != "sgs-c8-c-public-selected-action-v1":
            raise ValueError("invalid selected-action schema")
        if type(self.contract_version) is not int or self.contract_version != 1:
            raise ValueError("invalid selected-action version")
        _require_exact_int(self.step_index, "step_index", minimum=1)
        _require_exact_int(self.public_ordinal, "public_ordinal", minimum=0)
        _require_exact_str(self.public_action_reference, "public_action_reference")
        _require_exact_str(self.signed_action_id, "signed_action_id", nonempty=False)
        _require_exact_str(self.action_family, "action_family")
        for name in (
            "legal_set_identity",
            "canonical_public_ordering_identity",
            "candidate_identity",
            "selection_identity",
        ):
            _require_identity(getattr(self, name), name)
        for name in ("issuance_evidence_identity", "receipt_identity"):
            value = _require_exact_str(getattr(self, name), name, nonempty=False)
            if value:
                _require_identity(value, name)
        if self.receipt_identity and not self.issuance_evidence_identity:
            raise ValueError("receipt identity requires issuance evidence")
        if self.selection_identity != _identity(self.identity_payload_v1()):
            raise ValueError("selected-action identity mismatch")

    def identity_payload_v1(self) -> Mapping[str, Any]:
        value = self.to_public_dict_v1()
        return {key: item for key, item in value.items() if key != "selection_identity"}

    def to_public_dict_v1(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "contract_version": self.contract_version,
            "step_index": self.step_index,
            "legal_set_identity": self.legal_set_identity,
            "canonical_public_ordering_identity": (
                self.canonical_public_ordering_identity
            ),
            "public_ordinal": self.public_ordinal,
            "public_action_reference": self.public_action_reference,
            "signed_action_id": self.signed_action_id,
            "candidate_identity": self.candidate_identity,
            "action_family": self.action_family,
            "issuance_evidence_identity": self.issuance_evidence_identity,
            "receipt_identity": self.receipt_identity,
            "selection_identity": self.selection_identity,
        }

    @classmethod
    def from_public_dict_v1(cls, value: Any) -> "PublicSelectedActionV1":
        value = _require_exact_keys(value, cls._KEYS, "selected_action")
        return cls(**value)


def _build_public_selected_action_v1(
    *,
    step_index: int,
    envelope: FreshPublicLegalActionsEnvelopeV1,
    candidate: c8.PublicLegalActionCandidateV1,
    issuance: SignedActionIssuanceEvidenceV1 | None = None,
    receipt: rt.TimeoutActionExecutionReceiptV1 | None = None,
) -> PublicSelectedActionV1:
    values = {
        "schema": "sgs-c8-c-public-selected-action-v1",
        "contract_version": 1,
        "step_index": step_index,
        "legal_set_identity": envelope.legal_set_identity,
        "canonical_public_ordering_identity": (
            envelope.canonical_public_ordering_identity
        ),
        "public_ordinal": candidate.public_ordinal,
        "public_action_reference": candidate.action_id,
        "signed_action_id": issuance.signed_action_id if issuance is not None else "",
        "candidate_identity": candidate.candidate_identity,
        "action_family": _enum_text(candidate.action_family, "candidate.action_family"),
        "issuance_evidence_identity": (
            issuance.issuance_identity if issuance is not None else ""
        ),
        "receipt_identity": receipt.receipt_identity if receipt is not None else "",
    }
    values["selection_identity"] = _identity(values)
    return PublicSelectedActionV1(**values)


@dataclass(frozen=True, slots=True)
class ControllerEventV1:
    schema: str
    contract_version: int
    controller_id: str
    controller_contract_identity: str
    controller_instance_identity: str
    event_sequence: int
    event_kind: str
    previous_event_identity: str
    transaction_identity: str
    runtime_instance_identity: str
    window_authority_ref_identity: str
    window_id: str
    step_index: int
    legal_set_identity: str
    candidate_identity: str
    public_ordinal: int
    action_family: str
    issuance_evidence_identity: str
    receipt_identity: str
    outcome: str
    reason: str
    details_identity: str
    event_identity: str

    _KEYS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "contract_version",
            "controller_id",
            "controller_contract_identity",
            "controller_instance_identity",
            "event_sequence",
            "event_kind",
            "previous_event_identity",
            "transaction_identity",
            "runtime_instance_identity",
            "window_authority_ref_identity",
            "window_id",
            "step_index",
            "legal_set_identity",
            "candidate_identity",
            "public_ordinal",
            "action_family",
            "issuance_evidence_identity",
            "receipt_identity",
            "outcome",
            "reason",
            "details_identity",
            "event_identity",
        }
    )

    def __post_init__(self) -> None:
        _require_exact_str(self.schema, "schema")
        if self.schema != "sgs-c8-c-controller-event-v1":
            raise ValueError("invalid controller event schema")
        if type(self.contract_version) is not int or self.contract_version != 1:
            raise ValueError("invalid controller event version")
        if self.controller_id != C8_C_CONTROLLER_ID:
            raise ValueError("controller id mismatch")
        if self.controller_contract_identity != C8_C_CONTRACT_IDENTITY:
            raise ValueError("controller contract identity mismatch")
        _require_exact_int(self.event_sequence, "event_sequence", minimum=1)
        _require_exact_int(self.step_index, "step_index", minimum=0)
        if self.public_ordinal < -1 or type(self.public_ordinal) is not int:
            raise ValueError("public_ordinal must be exact int >= -1")
        _require_exact_str(self.controller_id, "controller_id")
        _require_exact_str(self.event_kind, "event_kind")
        if self.event_kind not in {item.value for item in ControllerEventKindV1}:
            raise ValueError("unknown controller event kind")
        for name in (
            "controller_instance_identity",
            "previous_event_identity",
            "transaction_identity",
            "runtime_instance_identity",
            "window_authority_ref_identity",
            "details_identity",
            "event_identity",
        ):
            _require_identity(getattr(self, name), name, allow_zero=(
                name == "previous_event_identity"
            ))
        for optional_identity in (
            self.legal_set_identity,
            self.candidate_identity,
            self.issuance_evidence_identity,
            self.receipt_identity,
        ):
            _require_exact_str(
                optional_identity, "optional event identity", nonempty=False
            )
            if optional_identity:
                _require_identity(optional_identity, "optional event identity")
        for name in ("window_id", "action_family", "outcome", "reason"):
            _require_exact_str(getattr(self, name), name, nonempty=False)
        if self.event_identity != _identity(self.identity_payload_v1()):
            raise ValueError("controller event identity mismatch")

    def identity_payload_v1(self) -> Mapping[str, Any]:
        value = self.to_public_dict_v1()
        return {key: item for key, item in value.items() if key != "event_identity"}

    def to_public_dict_v1(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "contract_version": self.contract_version,
            "controller_id": self.controller_id,
            "controller_contract_identity": self.controller_contract_identity,
            "controller_instance_identity": self.controller_instance_identity,
            "event_sequence": self.event_sequence,
            "event_kind": self.event_kind,
            "previous_event_identity": self.previous_event_identity,
            "transaction_identity": self.transaction_identity,
            "runtime_instance_identity": self.runtime_instance_identity,
            "window_authority_ref_identity": self.window_authority_ref_identity,
            "window_id": self.window_id,
            "step_index": self.step_index,
            "legal_set_identity": self.legal_set_identity,
            "candidate_identity": self.candidate_identity,
            "public_ordinal": self.public_ordinal,
            "action_family": self.action_family,
            "issuance_evidence_identity": self.issuance_evidence_identity,
            "receipt_identity": self.receipt_identity,
            "outcome": self.outcome,
            "reason": self.reason,
            "details_identity": self.details_identity,
            "event_identity": self.event_identity,
        }

    @classmethod
    def from_public_dict_v1(cls, value: Any) -> "ControllerEventV1":
        value = _require_exact_keys(value, cls._KEYS, "controller_event")
        return cls(**value)


@dataclass(frozen=True, slots=True)
class TimeoutControllerResultV1:
    schema: str
    contract_version: int
    controller_id: str
    controller_contract_identity: str
    controller_instance_identity: str
    result_kind: str
    reason: str
    transaction_identity: str
    runtime_contract_identity: str
    runtime_instance_identity: str
    window_authority_ref_identity: str
    window_id: str
    resolution_tick: int | None
    deadline_at: int | None
    step_count: int
    selected_actions: tuple[PublicSelectedActionV1, ...]
    legal_set_identities: tuple[str, ...]
    receipt_identities: tuple[str, ...]
    event_identities: tuple[str, ...]
    event_chain_before_identity: str
    event_chain_after_identity: str
    event_chain_summary_identity: str
    result_identity: str

    _KEYS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "contract_version",
            "controller_id",
            "controller_contract_identity",
            "controller_instance_identity",
            "result_kind",
            "reason",
            "transaction_identity",
            "runtime_contract_identity",
            "runtime_instance_identity",
            "window_authority_ref_identity",
            "window_id",
            "resolution_tick",
            "deadline_at",
            "step_count",
            "selected_actions",
            "legal_set_identities",
            "receipt_identities",
            "event_identities",
            "event_chain_before_identity",
            "event_chain_after_identity",
            "event_chain_summary_identity",
            "result_identity",
        }
    )

    def __post_init__(self) -> None:
        _require_exact_str(self.schema, "schema")
        if self.schema != "sgs-c8-c-timeout-controller-result-v1":
            raise ValueError("invalid controller result schema")
        if type(self.contract_version) is not int or self.contract_version != 1:
            raise ValueError("invalid controller result version")
        if self.controller_id != C8_C_CONTROLLER_ID:
            raise ValueError("controller id mismatch")
        if self.controller_contract_identity != C8_C_CONTRACT_IDENTITY:
            raise ValueError("controller contract identity mismatch")
        _require_exact_str(self.controller_id, "controller_id")
        _require_exact_str(self.result_kind, "result_kind")
        if self.result_kind not in {item.value for item in ControllerResultKindV1}:
            raise ValueError("unknown controller result kind")
        _require_exact_str(self.reason, "reason")
        _require_exact_str(self.window_id, "window_id")
        _require_exact_int(self.step_count, "step_count", minimum=0)
        for value, name in (
            (self.resolution_tick, "resolution_tick"),
            (self.deadline_at, "deadline_at"),
        ):
            if value is not None:
                _require_exact_int(value, name, minimum=0)
        if type(self.selected_actions) is not tuple:
            raise TypeError("selected_actions must be an exact tuple")
        if type(self.legal_set_identities) is not tuple:
            raise TypeError("legal_set_identities must be an exact tuple")
        if type(self.receipt_identities) is not tuple:
            raise TypeError("receipt_identities must be an exact tuple")
        if type(self.event_identities) is not tuple:
            raise TypeError("event_identities must be an exact tuple")
        for selected in self.selected_actions:
            if type(selected) is not PublicSelectedActionV1:
                raise TypeError("selected_actions contains an unknown type")
        for sequence, name in (
            (self.legal_set_identities, "legal_set_identities"),
            (self.receipt_identities, "receipt_identities"),
            (self.event_identities, "event_identities"),
        ):
            for item in sequence:
                _require_identity(item, name)
        # Controller events form a committed hash chain and can never repeat.
        # Legal-set and receipt sequences, however, are *attempted evidence* in
        # rollback results: retaining a duplicate is how a replay attempt is
        # represented rather than silently erased.  Successful results still
        # require unique step evidence below.
        if len(self.event_identities) != len(set(self.event_identities)):
            raise ValueError("event_identities must not contain duplicates")
        for name in (
            "controller_instance_identity",
            "transaction_identity",
            "runtime_contract_identity",
            "runtime_instance_identity",
            "window_authority_ref_identity",
            "event_chain_before_identity",
            "event_chain_after_identity",
            "event_chain_summary_identity",
            "result_identity",
        ):
            _require_identity(
                getattr(self, name),
                name,
                allow_zero=name in {
                    "event_chain_before_identity",
                    "event_chain_after_identity",
                },
            )
        if self.step_count > 8:
            raise ValueError("step count exceeds the frozen same-tick cap")
        if len(self.selected_actions) > self.step_count:
            raise ValueError("selected action count exceeds attempted step count")
        if len(self.legal_set_identities) != self.step_count:
            raise ValueError("legal-set count must match attempted step count")
        if len(self.receipt_identities) > self.step_count:
            raise ValueError("receipt count exceeds attempted step count")
        for selected in self.selected_actions:
            if selected.step_index > self.step_count:
                raise ValueError("selected action step exceeds attempted step count")
            if selected.legal_set_identity not in self.legal_set_identities:
                raise ValueError("selected action legal set is not in audit evidence")
            if (
                selected.receipt_identity
                and selected.receipt_identity not in self.receipt_identities
            ):
                raise ValueError("selected action receipt is not in audit evidence")
        expected_selected_steps = tuple(range(1, len(self.selected_actions) + 1))
        if tuple(item.step_index for item in self.selected_actions) != (
            expected_selected_steps
        ):
            raise ValueError("selected action steps must be ordered and contiguous")
        for selected in self.selected_actions:
            if (
                self.legal_set_identities[selected.step_index - 1]
                != selected.legal_set_identity
            ):
                raise ValueError("selected action/legal-set step linkage mismatch")
        selected_receipt_identities = tuple(
            selected.receipt_identity
            for selected in self.selected_actions
            if selected.receipt_identity
        )
        if self.receipt_identities[: len(selected_receipt_identities)] != (
            selected_receipt_identities
        ):
            raise ValueError("receipt audit order does not match selected actions")
        if self.result_kind in {
            ControllerResultKindV1.RESOLVED_SINGLE.value,
            ControllerResultKindV1.RESOLVED_CHAIN.value,
        }:
            if len(self.legal_set_identities) != len(
                set(self.legal_set_identities)
            ):
                raise ValueError(
                    "resolved legal_set_identities must not contain duplicates"
                )
            if len(self.receipt_identities) != len(set(self.receipt_identities)):
                raise ValueError(
                    "resolved receipt_identities must not contain duplicates"
                )
            if self.step_count < 1 or len(self.selected_actions) != self.step_count:
                raise ValueError("resolved result must select every attempted step")
            if len(self.receipt_identities) != self.step_count:
                raise ValueError("resolved result must bind every step receipt")
            if any(
                not selected.issuance_evidence_identity
                or not selected.receipt_identity
                for selected in self.selected_actions
            ):
                raise ValueError("resolved selected actions must be fully issued")
        summary = _identity(
            {
                "schema": "sgs-c8-c-event-chain-summary-v1",
                "contract_version": 1,
                "event_identities": list(self.event_identities),
            }
        )
        if self.event_chain_summary_identity != summary:
            raise ValueError("event chain summary identity mismatch")
        if self.event_identities:
            if self.event_chain_after_identity != self.event_identities[-1]:
                raise ValueError("event chain after identity must be final event")
        elif self.event_chain_after_identity != self.event_chain_before_identity:
            raise ValueError("empty event result must preserve event-chain tip")
        if self.result_identity != _identity(self.identity_payload_v1()):
            raise ValueError("controller result identity mismatch")

    def identity_payload_v1(self) -> Mapping[str, Any]:
        value = self.to_public_dict_v1()
        return {key: item for key, item in value.items() if key != "result_identity"}

    def to_public_dict_v1(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "contract_version": self.contract_version,
            "controller_id": self.controller_id,
            "controller_contract_identity": self.controller_contract_identity,
            "controller_instance_identity": self.controller_instance_identity,
            "result_kind": self.result_kind,
            "reason": self.reason,
            "transaction_identity": self.transaction_identity,
            "runtime_contract_identity": self.runtime_contract_identity,
            "runtime_instance_identity": self.runtime_instance_identity,
            "window_authority_ref_identity": self.window_authority_ref_identity,
            "window_id": self.window_id,
            "resolution_tick": self.resolution_tick,
            "deadline_at": self.deadline_at,
            "step_count": self.step_count,
            "selected_actions": [
                selected.to_public_dict_v1() for selected in self.selected_actions
            ],
            "legal_set_identities": list(self.legal_set_identities),
            "receipt_identities": list(self.receipt_identities),
            "event_identities": list(self.event_identities),
            "event_chain_before_identity": self.event_chain_before_identity,
            "event_chain_after_identity": self.event_chain_after_identity,
            "event_chain_summary_identity": self.event_chain_summary_identity,
            "result_identity": self.result_identity,
        }

    def to_json_bytes_v1(self) -> bytes:
        return _canonical_json_bytes(self.to_public_dict_v1())

    @classmethod
    def from_public_dict_v1(cls, value: Any) -> "TimeoutControllerResultV1":
        value = _require_exact_keys(value, cls._KEYS, "controller_result")
        selected_raw = value["selected_actions"]
        if type(selected_raw) is not list:
            raise TypeError("selected_actions must serialize as an exact list")
        converted = dict(value)
        converted["selected_actions"] = tuple(
            PublicSelectedActionV1.from_public_dict_v1(item) for item in selected_raw
        )
        for name in (
            "legal_set_identities",
            "receipt_identities",
            "event_identities",
        ):
            raw_sequence = value[name]
            if type(raw_sequence) is not list:
                raise TypeError(f"{name} must serialize as an exact list")
            converted[name] = tuple(raw_sequence)
        return cls(**converted)

    @classmethod
    def from_json_bytes_v1(cls, raw: bytes | str) -> "TimeoutControllerResultV1":
        return cls.from_public_dict_v1(_strict_json_object(raw))


@dataclass(frozen=True, slots=True)
class _AdapterIdentities:
    adapter_identity: str
    session_identity: str
    controller_identity: str
    public_state_identity: str
    authoritative_state_identity: str
    issuance_authority_identity: str
    issuance_security_ledger_identity: str
    legal_set_snapshot_identity: str
    ordering_identity: str


@dataclass(frozen=True, slots=True)
class _GuardedAdapterCallbackBundle:
    before: _AdapterIdentities
    callback_result: object
    after: _AdapterIdentities


@dataclass(frozen=True, slots=True)
class _GameplayRollbackFingerprint:
    outer_state: Any
    public_projection: Any
    virtual_time_state: Any
    pending_deadline: Any
    inner_adapter_identity: Any
    inner_session_binding_identity: Any
    inner_public_state_identity: Any
    inner_authoritative_state_identity: Any
    event_chain_tip: Any
    logical_obligations: Any


@dataclass(frozen=True, slots=True)
class _FailedIssuanceRecoveryContext:
    window_authority_ref: Any
    envelope: FreshPublicLegalActionsEnvelopeV1
    candidate: c8.PublicLegalActionCandidateV1
    transaction_identity: str
    legal_set_identity: str
    candidate_reference: str
    public_ordinal: int
    timeout_auth_binding: str
    security_ledger_before_identity: str
    security_ledger_observed_after_failure_identity: str


def _read_required_attr(value: Any, name: str) -> Any:
    if not hasattr(value, name):
        raise C8CContractError(f"required field missing: {name}")
    return getattr(value, name)


class TimeoutResolverControllerIntegrationV1:
    """Single-serial-driver C8-C controller.

    The controller's legal-set, issuance-evidence and receipt replay ledgers are
    security state.  They are intentionally not restored on gameplay rollback.
    Staged C8-C gameplay events are discarded on rollback; one deterministic
    ``ROLLED_BACK`` audit event is committed after recovery.
    """

    MAX_CHAIN_STEPS: Final[int] = 8

    def __init__(
        self,
        runtime: TimedSessionRuntimeV1,
        adapter: PublicLegalActionsIssuanceAdapterV1,
        *,
        controller_instance_identity: str,
    ) -> None:
        if type(runtime) is not rt.C8TimedSessionRuntimeV1:
            raise C8CContractError("C8-C requires the exact revised C8-B runtime")
        self._runtime = runtime
        self._adapter = adapter
        self._controller_instance_identity = _require_identity(
            controller_instance_identity, "controller_instance_identity"
        )
        self._verify_frozen_contract_latches()
        runtime_instance_identity = _read_required_attr(
            self._runtime.state, "runtime_instance_identity"
        )
        self._lock = _claim_process_local_runtime_owner_v1(
            runtime_instance_identity, self
        )
        self._resolving = False
        self._poisoned = False
        self._resolution_sequence = 0
        self._event_chain: list[ControllerEventV1] = []
        self._event_chain_tip = _ZERO_IDENTITY
        self._consumed_legal_set_identities: set[str] = set()
        self._consumed_issuance_identities: set[str] = set()
        self._consumed_authorization_evidence_identities: set[str] = set()
        self._consumed_receipt_identities: set[str] = set()
        self._invalidation_evidence_identities: set[str] = set()
        self._failed_issuance_recovery_identities: set[str] = set()
        self._unforwarded_issuances: dict[
            str, SignedActionIssuanceEvidenceV1
        ] = {}
        self._unforwarded_issuance_contexts: dict[
            str, _FailedIssuanceRecoveryContext
        ] = {}
        self._pending_b_capabilities: dict[
            str, rt.PendingTimeoutIssuanceCapabilityV1
        ] = {}

    @property
    def poisoned(self) -> bool:
        return self._poisoned

    def public_event_trace_v1(self) -> tuple[ControllerEventV1, ...]:
        with self._lock:
            return tuple(self._event_chain)

    def resolve_timeout_v1(
        self,
        window_authority_ref: Any,
        *,
        timeout_due_commitment: Any,
    ) -> TimeoutControllerResultV1:
        with self._lock:
            if self._resolving:
                self._poisoned = True
                raise C8CReentrancyError(
                    "nested resolve rejected; outer controller transaction poisoned"
                )
            if self._poisoned:
                raise C8CPoisonedError("controller is poisoned")
            self._resolving = True
            self._resolution_sequence += 1
            try:
                return self._resolve_locked_v1(
                    window_authority_ref,
                    supplied_timeout_due_commitment=timeout_due_commitment,
                )
            finally:
                self._resolving = False

    def _resolve_locked_v1(
        self,
        window_authority_ref: Any,
        *,
        supplied_timeout_due_commitment: Any,
    ) -> TimeoutControllerResultV1:
        self._validate_window_ref_shape(window_authority_ref)
        event_chain_before = self._event_chain_tip
        transaction_identity = self._transaction_identity_v1(
            window_authority_ref, supplied_timeout_due_commitment
        )
        current_commitment = self._current_matching_commitment_v1(
            window_authority_ref, supplied_timeout_due_commitment
        )
        if current_commitment is None:
            return self._build_result_v1(
                kind=ControllerResultKindV1.FAILED_ROLLED_BACK,
                reason="TIMEOUT_DUE_PRECONDITION_REJECTED",
                transaction_identity=transaction_identity,
                window_authority_ref=window_authority_ref,
                commitment=supplied_timeout_due_commitment,
                selected_actions=(),
                attempted_legal_set_identities=(),
                attempted_receipt_identities=(),
                transaction_events=(),
                event_chain_before=event_chain_before,
            )

        snapshot = self._runtime.capture_transaction()
        if type(snapshot) is not rt.TimedSessionTransactionSnapshotV1:
            raise C8CContractError("runtime returned unknown transaction snapshot type")
        snapshot.__post_init__()
        rollback_fingerprint = self._gameplay_rollback_fingerprint_v1()
        if snapshot.outer_state != rollback_fingerprint.outer_state:
            raise C8CContractError("transaction snapshot outer state mismatch")
        staged_events: list[ControllerEventV1] = []
        selected_actions: list[PublicSelectedActionV1] = []
        attempted_legal_set_identities: list[str] = []
        attempted_receipt_identities: list[str] = []
        initial_tick = current_commitment.now_tick
        initial_deadline = current_commitment.deadline_at
        initial_window = self._active_window_v1()
        initial_opened_at = initial_window.opened_at
        initial_parent_window_id = initial_window.parent_window_id
        ever_required_chain = False

        self._stage_event_v1(
            staged_events,
            kind=ControllerEventKindV1.RESOLUTION_STARTED,
            transaction_identity=transaction_identity,
            window_authority_ref=window_authority_ref,
            step_index=0,
            details={
                "timeout_due_commitment_identity": (
                    current_commitment.commitment_identity
                ),
                "resolution_tick": initial_tick,
                "deadline_at": initial_deadline,
            },
        )

        try:
            for step_index in range(1, self.MAX_CHAIN_STEPS + 1):
                if self._poisoned:
                    raise _AbortResolution(
                        ControllerResultKindV1.FAILED_POISONED,
                        "REENTRANCY_OR_CALLBACK_POISON",
                    )
                live_commitment = (
                    current_commitment
                    if step_index == 1
                    else self._runtime.current_timeout_due_commitment_v1(
                        window_authority_ref
                    )
                )
                if live_commitment is None:
                    raise _AbortResolution(
                        ControllerResultKindV1.FAILED_ROLLED_BACK,
                        "TIMEOUT_COMMITMENT_LOST_DURING_CHAIN",
                    )
                self._verify_commitment_and_window_v1(
                    live_commitment, window_authority_ref
                )
                if live_commitment.now_tick != initial_tick:
                    raise _AbortResolution(
                        ControllerResultKindV1.FAILED_ROLLED_BACK,
                        "SAME_TICK_CHAIN_TIME_CHANGED",
                    )
                if live_commitment.deadline_at != initial_deadline:
                    raise _AbortResolution(
                        ControllerResultKindV1.FAILED_ROLLED_BACK,
                        "SAME_TICK_CHAIN_DEADLINE_CHANGED",
                    )
                active_window = self._active_window_v1()
                if active_window.opened_at != initial_opened_at:
                    raise _AbortResolution(
                        ControllerResultKindV1.FAILED_ROLLED_BACK,
                        "SAME_TICK_CHAIN_OPENED_AT_CHANGED",
                    )
                if active_window.parent_window_id != initial_parent_window_id:
                    raise _AbortResolution(
                        ControllerResultKindV1.FAILED_ROLLED_BACK,
                        "SAME_TICK_CHAIN_PARENT_CHANGED",
                    )

                envelope, expected_bindings = self._fresh_bound_legal_set_v1(
                    window_authority_ref,
                    live_commitment,
                )
                attempted_legal_set_identities.append(envelope.legal_set_identity)
                if envelope.legal_set_identity in self._consumed_legal_set_identities:
                    raise _AbortResolution(
                        ControllerResultKindV1.FAILED_ROLLED_BACK,
                        "LEGAL_SET_REPLAY_OR_NOT_FRESH",
                    )
                self._consumed_legal_set_identities.add(envelope.legal_set_identity)
                self._stage_event_v1(
                    staged_events,
                    kind=ControllerEventKindV1.LEGAL_SET_BOUND,
                    transaction_identity=transaction_identity,
                    window_authority_ref=window_authority_ref,
                    step_index=step_index,
                    legal_set_identity=envelope.legal_set_identity,
                    details={
                        "projection_legal_set_identity": (
                            envelope.projection_legal_set_identity
                        ),
                        "canonical_public_ordering_identity": (
                            envelope.canonical_public_ordering_identity
                        ),
                        "timeout_authentication_bindings_identity": (
                            envelope.timeout_authentication_bindings_identity
                        ),
                    },
                )

                policy = self._policy_for_window_v1(active_window)
                runtime_before_resolver = self._runtime.state
                public_before_resolver = self._runtime.public_projection()
                resolution = c8.resolve_timeout_v1(
                    window=active_window,
                    current_tick=live_commitment.now_tick,
                    public_legal_set=envelope.public_legal_set,
                    fallback_policy=policy,
                )
                self._ensure_runtime_unchanged_v1(
                    runtime_before_resolver,
                    public_before_resolver,
                    "C8_A_RESOLVER_MUTATED_RUNTIME",
                )
                candidate = self._validate_resolution_and_select_candidate_v1(
                    resolution,
                    active_window,
                    live_commitment,
                    envelope,
                    policy,
                )
                ever_required_chain = (
                    ever_required_chain or resolution.same_tick_chain_required
                )
                selected_actions.append(
                    _build_public_selected_action_v1(
                        step_index=step_index,
                        envelope=envelope,
                        candidate=candidate,
                    )
                )
                self._stage_event_v1(
                    staged_events,
                    kind=ControllerEventKindV1.FALLBACK_SELECTED,
                    transaction_identity=transaction_identity,
                    window_authority_ref=window_authority_ref,
                    step_index=step_index,
                    legal_set_identity=envelope.legal_set_identity,
                    candidate=candidate,
                    details={
                        "resolution_identity": resolution.resolution_identity,
                        "policy_identity": policy.policy_identity,
                    },
                )

                self._reconfirm_current_lineage_before_issuance_v1(
                    window_authority_ref,
                    live_commitment,
                    envelope,
                )
                binding_by_candidate = {
                    candidate_identity: binding_identity
                    for candidate_identity, _, binding_identity in expected_bindings
                }
                selected_binding = binding_by_candidate[candidate.candidate_identity]
                issuance_security_ledger_before = (
                    envelope.issuance_security_ledger_identity
                )
                runtime_before_issuance = self._runtime.state
                public_before_issuance = self._runtime.public_projection()
                (
                    issuance,
                    pending_issuance_key,
                    pending_b_capability,
                    b_authorization_binding,
                ) = (
                    self._confirm_issuance_with_recovery_v1(
                        window_authority_ref=window_authority_ref,
                        commitment=live_commitment,
                        candidate=candidate,
                        envelope=envelope,
                        selected_binding=selected_binding,
                        issuance_security_ledger_before=(
                            issuance_security_ledger_before
                        ),
                        transaction_identity=transaction_identity,
                        runtime_before_issuance=runtime_before_issuance,
                        public_before_issuance=public_before_issuance,
                    )
                )
                if issuance.issuance_identity in self._consumed_issuance_identities:
                    raise _AbortResolution(
                        ControllerResultKindV1.FAILED_ROLLED_BACK,
                        "ISSUANCE_EVIDENCE_REPLAY",
                    )
                if (
                    issuance.authorization_evidence_identity
                    in self._consumed_authorization_evidence_identities
                ):
                    raise _AbortResolution(
                        ControllerResultKindV1.FAILED_ROLLED_BACK,
                        "EXTERNAL_AUTHORIZATION_EVIDENCE_REPLAY",
                    )
                self._consumed_issuance_identities.add(issuance.issuance_identity)
                self._consumed_authorization_evidence_identities.add(
                    issuance.authorization_evidence_identity
                )
                selected_actions[-1] = _build_public_selected_action_v1(
                    step_index=step_index,
                    envelope=envelope,
                    candidate=candidate,
                    issuance=issuance,
                )
                self._stage_event_v1(
                    staged_events,
                    kind=ControllerEventKindV1.ISSUANCE_BOUND,
                    transaction_identity=transaction_identity,
                    window_authority_ref=window_authority_ref,
                    step_index=step_index,
                    legal_set_identity=envelope.legal_set_identity,
                    candidate=candidate,
                    issuance_evidence_identity=issuance.issuance_identity,
                    details={
                        "issuance_request_binding_identity": selected_binding,
                        "b_authorization_binding_identity": (
                            b_authorization_binding
                        ),
                        "authorization_evidence_identity": (
                            issuance.authorization_evidence_identity
                        ),
                        "pending_issuance_capability_identity": (
                            pending_b_capability.capability_identity
                        ),
                    },
                )

                pre_forward_state = self._runtime.state
                ownership_before = self._pending_capability_ownership_v1(
                    pending_b_capability
                )
                if self._ownership_status_v1(ownership_before) != (
                    "CONTROLLER_OWNED_PENDING"
                ):
                    raise _AbortResolution(
                        ControllerResultKindV1.FAILED_POISONED,
                        "PENDING_CAPABILITY_NOT_CONTROLLER_OWNED_BEFORE_FORWARD",
                    )
                try:
                    receipt = self._runtime.forward_timeout_due_signed_action_id_v1(
                        window_authority_ref,
                        timeout_due_commitment=live_commitment,
                        signed_action_id=issuance.signed_action_id,
                        authorization_evidence_identity=(
                            issuance.authorization_evidence_identity
                        ),
                        pending_issuance_capability=pending_b_capability,
                    )
                except Exception as exc:
                    try:
                        failed_ownership = self._pending_capability_ownership_v1(
                            pending_b_capability
                        )
                        failed_status = self._ownership_status_v1(failed_ownership)
                        if failed_status == "CONTROLLER_OWNED_PENDING":
                            forward_failure_secured = (
                                self._abort_registered_pending_issuance_v1(
                                    window_authority_ref,
                                    live_commitment,
                                    pending_issuance_key,
                                    issuance,
                                    pending_b_capability,
                                )
                            )
                            forward_failure_reason = (
                                "B_FORWARD_FAILED_PRE_CONSUME_CAPABILITY_ABORTED"
                            )
                        elif failed_status in {
                            "AUTH_EVIDENCE_CONSUMED",
                            "RECEIPT_COMMITTED_CONSUMED",
                        }:
                            self._drop_consumed_pending_issuance_v1(
                                pending_issuance_key
                            )
                            forward_failure_secured = True
                            forward_failure_reason = (
                                "B_FORWARD_FAILED_AFTER_CONSUME_CAPABILITY_BURNED"
                            )
                            committed = failed_ownership.committed_receipt_identity
                            if committed is not None:
                                attempted_receipt_identities.append(committed)
                        else:
                            forward_failure_secured = False
                            forward_failure_reason = (
                                "B_FORWARD_FAILURE_INVALID_CAPABILITY_OWNERSHIP"
                            )
                    except Exception:
                        forward_failure_secured = False
                        forward_failure_reason = "B_FORWARD_FAILURE_OWNERSHIP_UNPROVEN"
                    if not forward_failure_secured:
                        self._poisoned = True
                    raise _AbortResolution(
                        (
                            ControllerResultKindV1.FAILED_POISONED
                            if self._poisoned
                            else ControllerResultKindV1.FAILED_ROLLED_BACK
                        ),
                        (
                            "B_FORWARD_FAILURE_SECURITY_RECOVERY_UNPROVEN"
                            if self._poisoned
                            else forward_failure_reason
                        ),
                    ) from exc
                self._ensure_not_poisoned_v1()
                ownership_after = self._pending_capability_ownership_v1(
                    pending_b_capability
                )
                if type(receipt) is rt.TimeoutActionExecutionReceiptV1:
                    receipt_identity = getattr(receipt, "receipt_identity", None)
                    if (
                        type(receipt_identity) is str
                        and len(receipt_identity) == 64
                        and all(character in _HEX for character in receipt_identity)
                        and receipt_identity != _ZERO_IDENTITY
                    ):
                        attempted_receipt_identities.append(receipt_identity)
                self._verify_receipt_v1(
                    receipt,
                    window_authority_ref,
                    live_commitment,
                    envelope,
                    issuance,
                    b_authorization_binding,
                    pre_forward_state,
                    pending_b_capability,
                    ownership_after,
                )
                if receipt.receipt_identity in self._consumed_receipt_identities:
                    raise _AbortResolution(
                        ControllerResultKindV1.FAILED_ROLLED_BACK,
                        "RECEIPT_REPLAY_OR_CROSS_STEP_REUSE",
                    )
                self._consumed_receipt_identities.add(receipt.receipt_identity)
                self._drop_consumed_pending_issuance_v1(pending_issuance_key)
                selected_actions[-1] = _build_public_selected_action_v1(
                    step_index=step_index,
                    envelope=envelope,
                    candidate=candidate,
                    issuance=issuance,
                    receipt=receipt,
                )

                completion = build_receipt_lineage_completion_evidence_v1(
                    receipt_identity=receipt.receipt_identity,
                    issuance_identity=issuance.issuance_identity,
                    legal_set_identity=envelope.legal_set_identity,
                    runtime_instance_identity=live_commitment.runtime_instance_identity,
                    window_authority_ref_identity=(
                        window_authority_ref.authority_ref_identity
                    ),
                    window_id=live_commitment.window_id,
                    decision_identity=live_commitment.decision_identity,
                    obligation_identity=live_commitment.obligation_identity,
                    session_identity=envelope.session_identity,
                    controller_identity=envelope.controller_identity,
                    adapter_identity=envelope.adapter_identity,
                    post_public_state_identity=(
                        receipt.post_inner_public_state_identity
                    ),
                    post_authoritative_state_identity=(
                        receipt.post_inner_authoritative_state_identity
                    ),
                    obligation_completed=issuance.obligation_completed,
                )
                self._validate_completion_evidence_v1(
                    completion,
                    receipt,
                    issuance,
                    envelope,
                    live_commitment,
                )
                self._stage_event_v1(
                    staged_events,
                    kind=ControllerEventKindV1.RECEIPT_BOUND,
                    transaction_identity=transaction_identity,
                    window_authority_ref=window_authority_ref,
                    step_index=step_index,
                    legal_set_identity=envelope.legal_set_identity,
                    candidate=candidate,
                    issuance_evidence_identity=issuance.issuance_identity,
                    receipt_identity=receipt.receipt_identity,
                    details={
                        "completion_evidence_identity": (
                            completion.completion_evidence_identity
                        ),
                        "obligation_completed": completion.obligation_completed,
                    },
                )
                if completion.obligation_completed:
                    pre_close_state = self._runtime.state
                    pre_close_public = self._runtime.public_projection()
                    closed_window = self._runtime.close_window_by_timeout_receipt_v1(
                        window_authority_ref,
                        execution_receipt=receipt,
                    )
                    self._verify_closed_window_v1(
                        closed_window,
                        active_window,
                        window_authority_ref=window_authority_ref,
                        execution_receipt=receipt,
                        pre_close_state=pre_close_state,
                        pre_close_public_projection=pre_close_public,
                        initial_tick=initial_tick,
                        initial_deadline=initial_deadline,
                        initial_opened_at=initial_opened_at,
                    )
                    self._stage_event_v1(
                        staged_events,
                        kind=ControllerEventKindV1.WINDOW_RESOLVED,
                        transaction_identity=transaction_identity,
                        window_authority_ref=window_authority_ref,
                        step_index=step_index,
                        legal_set_identity=envelope.legal_set_identity,
                        candidate=candidate,
                        issuance_evidence_identity=issuance.issuance_identity,
                        receipt_identity=receipt.receipt_identity,
                        outcome=(
                            ControllerResultKindV1.RESOLVED_CHAIN.value
                            if ever_required_chain or step_index > 1
                            else ControllerResultKindV1.RESOLVED_SINGLE.value
                        ),
                        details={
                            "closed_window_state_identity": (
                                closed_window.window_state_identity
                            ),
                            "step_count": step_index,
                        },
                    )
                    result_kind = (
                        ControllerResultKindV1.RESOLVED_CHAIN
                        if ever_required_chain or step_index > 1
                        else ControllerResultKindV1.RESOLVED_SINGLE
                    )
                    result = self._build_result_v1(
                        kind=result_kind,
                        reason="TIMEOUT_RESOLUTION_COMMITTED",
                        transaction_identity=transaction_identity,
                        window_authority_ref=window_authority_ref,
                        commitment=current_commitment,
                        selected_actions=tuple(selected_actions),
                        attempted_legal_set_identities=tuple(
                            attempted_legal_set_identities
                        ),
                        attempted_receipt_identities=tuple(
                            attempted_receipt_identities
                        ),
                        transaction_events=tuple(staged_events),
                        event_chain_before=event_chain_before,
                        event_chain_after_identity=staged_events[-1].event_identity,
                    )
                    self._commit_staged_events_v1(staged_events)
                    return result

                if not resolution.same_tick_chain_required:
                    raise _AbortResolution(
                        ControllerResultKindV1.FAILED_ROLLED_BACK,
                        "INCOMPLETE_OBLIGATION_WITHOUT_SAME_TICK_CHAIN_AUTHORITY",
                    )

                logical_step_identity = _identity(
                    {
                        "schema": "sgs-c8-c-logical-timeout-step-v1",
                        "contract_version": 1,
                        "transaction_identity": transaction_identity,
                        "step_index": step_index,
                        "receipt_identity": receipt.receipt_identity,
                        "completion_evidence_identity": (
                            completion.completion_evidence_identity
                        ),
                        "obligation_identity": live_commitment.obligation_identity,
                    }
                )
                pre_continue_state = self._runtime.state
                pre_continue_public = self._runtime.public_projection()
                precedence = (
                    self._runtime.continue_timeout_multi_step_obligation_v1(
                        window_authority_ref,
                        execution_receipt=receipt,
                        expected_step_index=step_index - 1,
                        logical_step_identity=logical_step_identity,
                    )
                )
                self._verify_continuation_v1(
                    precedence,
                    window_authority_ref,
                    initial_tick=initial_tick,
                    initial_deadline=initial_deadline,
                    initial_opened_at=initial_opened_at,
                    initial_parent_window_id=initial_parent_window_id,
                    execution_receipt=receipt,
                    logical_step_identity=logical_step_identity,
                    expected_step_index=step_index - 1,
                    pre_continue_state=pre_continue_state,
                    pre_continue_public_projection=pre_continue_public,
                )
                self._stage_event_v1(
                    staged_events,
                    kind=ControllerEventKindV1.CHAIN_CONTINUED,
                    transaction_identity=transaction_identity,
                    window_authority_ref=window_authority_ref,
                    step_index=step_index,
                    legal_set_identity=envelope.legal_set_identity,
                    candidate=candidate,
                    issuance_evidence_identity=issuance.issuance_identity,
                    receipt_identity=receipt.receipt_identity,
                    details={
                        "logical_step_identity": logical_step_identity,
                        "deadline_precedence": _enum_text(
                            precedence, "deadline_precedence"
                        ),
                    },
                )
                if step_index == self.MAX_CHAIN_STEPS:
                    raise _AbortResolution(
                        ControllerResultKindV1.CHAIN_CAP_EXHAUSTED,
                        "NINTH_SAME_TICK_STEP_REQUIRED",
                    )

            raise AssertionError("bounded chain loop exited unexpectedly")
        except _AbortResolution as abort:
            return self._rollback_and_result_v1(
                snapshot=snapshot,
                rollback_fingerprint=rollback_fingerprint,
                kind=abort.result_kind,
                reason=abort.reason,
                transaction_identity=transaction_identity,
                window_authority_ref=window_authority_ref,
                commitment=current_commitment,
                selected_actions=tuple(selected_actions),
                attempted_legal_set_identities=tuple(
                    attempted_legal_set_identities
                ),
                attempted_receipt_identities=tuple(
                    attempted_receipt_identities
                ),
                staged_events=tuple(staged_events),
                event_chain_before=event_chain_before,
            )
        except Exception as exc:
            return self._rollback_and_result_v1(
                snapshot=snapshot,
                rollback_fingerprint=rollback_fingerprint,
                kind=(
                    ControllerResultKindV1.FAILED_POISONED
                    if self._poisoned
                    else ControllerResultKindV1.FAILED_ROLLED_BACK
                ),
                reason=f"FAIL_CLOSED_{type(exc).__name__}",
                transaction_identity=transaction_identity,
                window_authority_ref=window_authority_ref,
                commitment=current_commitment,
                selected_actions=tuple(selected_actions),
                attempted_legal_set_identities=tuple(
                    attempted_legal_set_identities
                ),
                attempted_receipt_identities=tuple(
                    attempted_receipt_identities
                ),
                staged_events=tuple(staged_events),
                event_chain_before=event_chain_before,
            )

    def _verify_frozen_contract_latches(self) -> None:
        if c8.C8_A_CONTRACT_IDENTITY_V1 != C8_A_REQUIRED_CONTRACT_IDENTITY:
            raise C8CContractError("C8-A frozen contract identity drift")
        if (
            rt.C8_B_RUNTIME_CONTRACT_IDENTITY_V1
            != C8_B_REQUIRED_RUNTIME_CONTRACT_IDENTITY
        ):
            raise C8CContractError("C8-B revised runtime contract identity drift")
        if (
            rt.C8_B_CURRENT_CONTRACT_LATCH_V1.latch_identity
            != C8_B_REQUIRED_CURRENT_CONTRACT_LATCH_IDENTITY
        ):
            raise C8CContractError("C8-B current contract latch identity drift")
        if c8.SAME_TICK_FALLBACK_CHAIN_MAX_STEPS != self.MAX_CHAIN_STEPS:
            raise C8CContractError("C8-A same-tick chain cap drift")

    def _validate_window_ref_shape(self, ref: Any) -> None:
        if type(ref) is not rt.WindowAuthorityRefV1:
            raise C8CContractError("window authority ref must be exact C8-B type")
        ref.__post_init__()
        for field_name in _WINDOW_REF_FIELDS:
            _read_required_attr(ref, field_name)
        if type(ref.contract_version) is not int or ref.contract_version != 1:
            raise C8CContractError("window authority ref version mismatch")
        for name in (
            "runtime_instance_identity",
            "decision_identity",
            "obligation_identity",
            "window_binding_identity",
            "authority_ref_identity",
        ):
            _require_identity(getattr(ref, name), f"window_ref.{name}")

    def _current_matching_commitment_v1(
        self, ref: Any, supplied_commitment: Any
    ) -> Any | None:
        try:
            current = self._runtime.current_timeout_due_commitment_v1(ref)
        except Exception:
            return None
        if current is None or supplied_commitment is None:
            return None
        if not _object_fields_equal(
            current, supplied_commitment, _TIMEOUT_COMMITMENT_FIELDS
        ):
            return None
        # The deterministic probe asks C8-B's live-object registry to validate
        # the supplied object without consuming authorization evidence.  This
        # rejects a field-identical forged clone even when the legal set is empty.
        try:
            probe_binding = (
                self._runtime.expected_timeout_action_authentication_binding_v1(
                    ref,
                    timeout_due_commitment=supplied_commitment,
                    signed_action_id=C8_C_LIVE_COMMITMENT_PROBE_ACTION_REFERENCE,
                )
            )
            _require_identity(probe_binding, "live commitment probe binding")
        except Exception:
            return None
        try:
            self._verify_commitment_and_window_v1(current, ref)
        except Exception:
            return None
        return supplied_commitment

    def _verify_commitment_and_window_v1(self, commitment: Any, ref: Any) -> None:
        for field_name in _TIMEOUT_COMMITMENT_FIELDS:
            _read_required_attr(commitment, field_name)
        if (
            type(commitment.contract_version) is not int
            or commitment.contract_version != 1
        ):
            raise C8CContractError("timeout commitment version mismatch")
        if (
            commitment.runtime_contract_identity
            != C8_B_REQUIRED_RUNTIME_CONTRACT_IDENTITY
        ):
            raise C8CContractError("timeout commitment runtime contract mismatch")
        if commitment.runtime_instance_identity != ref.runtime_instance_identity:
            raise C8CContractError("timeout commitment runtime mismatch")
        if commitment.window_authority_ref_identity != ref.authority_ref_identity:
            raise C8CContractError("timeout commitment authority ref mismatch")
        for name in ("window_id", "actor_id", "decision_identity", "obligation_identity"):
            if getattr(commitment, name) != getattr(ref, name):
                raise C8CContractError(f"timeout commitment {name} mismatch")
        _require_exact_int(commitment.now_tick, "commitment.now_tick", minimum=0)
        _require_exact_int(commitment.deadline_at, "commitment.deadline_at", minimum=0)
        if commitment.now_tick < commitment.deadline_at:
            raise C8CContractError("timeout commitment is before deadline")
        for name in (
            "runtime_contract_identity",
            "runtime_instance_identity",
            "window_authority_ref_identity",
            "decision_identity",
            "obligation_identity",
            "virtual_time_state_identity",
            "pending_deadline_identity",
            "derived_deadline_identity",
            "caused_by_input_identity",
            "input_chain_tip",
            "event_chain_tip",
            "outer_state_identity",
            "commitment_identity",
        ):
            _require_identity(getattr(commitment, name), f"commitment.{name}")
        active = self._active_window_v1()
        for name in (
            "window_id",
            "actor_id",
            "decision_identity",
            "obligation_identity",
            "window_binding_identity",
        ):
            if getattr(active, name) != getattr(ref, name):
                raise C8CContractError(f"active window {name} mismatch")
        if active.deadline_at != commitment.deadline_at:
            raise C8CContractError("active window deadline mismatch")
        if _enum_text(active.status, "active.status") != "ACTIVE":
            raise C8CContractError("timeout window is not open")

    def _active_window_v1(self) -> c8.TimedDecisionWindowV1:
        state = self._runtime.state
        virtual_time_state = _read_required_attr(state, "virtual_time_state")
        window_stack = _read_required_attr(virtual_time_state, "window_stack")
        active = _read_required_attr(window_stack, "active_window")
        if type(active) is not c8.TimedDecisionWindowV1:
            raise C8CContractError("active window has an unknown type")
        return active

    def _adapter_identities_inside_guard_v1(self) -> _AdapterIdentities:
        """Read adapter identity hooks only from inside C8-B's trusted guard."""

        values = _AdapterIdentities(
            adapter_identity=self._adapter.current_adapter_identity_v1(),
            session_identity=self._adapter.current_session_identity_v1(),
            controller_identity=self._adapter.current_controller_identity_v1(),
            public_state_identity=self._adapter.current_public_state_identity_v1(),
            authoritative_state_identity=(
                self._adapter.current_authoritative_state_identity_v1()
            ),
            issuance_authority_identity=(
                self._adapter.current_issuance_authority_identity_v1()
            ),
            issuance_security_ledger_identity=(
                self._adapter.current_issuance_security_ledger_identity_v1()
            ),
            legal_set_snapshot_identity=(
                self._adapter.current_public_legal_set_snapshot_identity_v1()
            ),
            ordering_identity=(
                self._adapter.current_canonical_public_ordering_identity_v1()
            ),
        )
        for field_name in values.__dataclass_fields__:
            _require_identity(getattr(values, field_name), f"adapter.{field_name}")
        if values.controller_identity != self._controller_instance_identity:
            raise C8CContractError("adapter controller identity mismatch")
        return values

    def _invoke_adapter_callback_guarded_v1(
        self,
        ref: Any,
        commitment: Any,
        callback: Callable[[], object],
        *,
        precondition: Callable[[_AdapterIdentities], None] | None = None,
    ) -> tuple[_GuardedAdapterCallbackBundle, rt.ControllerCallbackGuardResultV1]:
        """Invoke one adapter callback and return B's live successful guard result."""

        state = self._runtime.state
        expected_adapter_identity = _require_identity(
            _read_required_attr(state, "inner_adapter_identity"),
            "runtime.inner_adapter_identity",
        )
        lease = self._runtime.issue_controller_callback_lease_v1(
            ref,
            timeout_due_commitment=commitment,
            controller_identity=self._controller_instance_identity,
            adapter_identity=expected_adapter_identity,
        )
        if type(lease) is not rt.ControllerCallbackLeaseV1:
            raise C8CContractError("B returned unknown controller callback lease")
        lease.__post_init__()

        def guarded_callback() -> _GuardedAdapterCallbackBundle:
            before = self._adapter_identities_inside_guard_v1()
            self._runtime_adapter_linkage_v1(before, self._runtime.state)
            if precondition is not None:
                precondition(before)
            callback_result = callback()
            after = self._adapter_identities_inside_guard_v1()
            self._runtime_adapter_linkage_v1(after, self._runtime.state)
            return _GuardedAdapterCallbackBundle(
                before=before,
                callback_result=callback_result,
                after=after,
            )

        invocation = self._runtime.invoke_controller_callback_guarded_v1(
            lease, guarded_callback
        )
        if type(invocation) is not rt.ControllerCallbackInvocationResultV1:
            raise C8CContractError("B returned unknown guarded callback result")
        invocation.__post_init__()
        guard_result = invocation.guard_result
        if type(guard_result) is not rt.ControllerCallbackGuardResultV1:
            raise C8CContractError("B returned unknown callback guard evidence")
        guard_result.__post_init__()
        bundle = invocation.callback_result
        if type(bundle) is not _GuardedAdapterCallbackBundle:
            raise C8CContractError("guarded callback returned unknown bundle")
        expected_guard = {
            "runtime_contract_identity": C8_B_REQUIRED_RUNTIME_CONTRACT_IDENTITY,
            "runtime_instance_identity": ref.runtime_instance_identity,
            "controller_identity": self._controller_instance_identity,
            "adapter_identity": expected_adapter_identity,
            "window_authority_ref_identity": ref.authority_ref_identity,
            "window_id": ref.window_id,
            "timeout_due_commitment_identity": commitment.commitment_identity,
        }
        for field_name, expected_value in expected_guard.items():
            if getattr(guard_result, field_name) != expected_value:
                raise C8CContractError(
                    f"callback guard result {field_name} mismatch"
                )
        self._ensure_not_poisoned_v1()
        return bundle, guard_result

    @staticmethod
    def _require_adapter_lineage_stable_v1(
        before: _AdapterIdentities,
        after: _AdapterIdentities,
        *,
        allow_legal_projection_change: bool,
        allow_issuance_ledger_change: bool,
    ) -> None:
        stable_fields = [
            "adapter_identity",
            "session_identity",
            "controller_identity",
            "public_state_identity",
            "authoritative_state_identity",
            "issuance_authority_identity",
        ]
        if not allow_legal_projection_change:
            stable_fields.extend(("legal_set_snapshot_identity", "ordering_identity"))
        if not allow_issuance_ledger_change:
            stable_fields.append("issuance_security_ledger_identity")
        for field_name in stable_fields:
            if getattr(before, field_name) != getattr(after, field_name):
                raise C8CContractError(
                    f"adapter callback changed {field_name}"
                )

    @staticmethod
    def _require_issuance_precondition_v1(
        identities: _AdapterIdentities,
        envelope: FreshPublicLegalActionsEnvelopeV1,
    ) -> None:
        expected = {
            "adapter_identity": envelope.adapter_identity,
            "session_identity": envelope.session_identity,
            "controller_identity": envelope.controller_identity,
            "public_state_identity": envelope.public_state_identity,
            "authoritative_state_identity": envelope.authoritative_state_identity,
            "issuance_security_ledger_identity": (
                envelope.issuance_security_ledger_identity
            ),
            "legal_set_snapshot_identity": (
                envelope.adapter_legal_set_snapshot_identity
            ),
            "ordering_identity": envelope.canonical_public_ordering_identity,
        }
        for field_name, expected_value in expected.items():
            if getattr(identities, field_name) != expected_value:
                raise C8CContractError(
                    f"issuance precondition {field_name} changed"
                )

    def _runtime_adapter_linkage_v1(
        self, adapter_ids: _AdapterIdentities, state: Any
    ) -> None:
        checks = (
            ("inner_adapter_identity", adapter_ids.adapter_identity),
            ("inner_session_binding_identity", adapter_ids.session_identity),
            ("inner_public_state_identity", adapter_ids.public_state_identity),
            (
                "inner_authoritative_state_identity",
                adapter_ids.authoritative_state_identity,
            ),
            (
                "input_authenticator_identity",
                adapter_ids.issuance_authority_identity,
            ),
        )
        for field_name, expected in checks:
            actual = _read_required_attr(state, field_name)
            if actual != expected:
                raise C8CContractError(f"adapter/runtime {field_name} mismatch")

    def _fresh_bound_legal_set_v1(
        self, ref: Any, commitment: Any
    ) -> tuple[
        FreshPublicLegalActionsEnvelopeV1, tuple[tuple[str, str, str], ...]
    ]:
        bundle, _ = self._invoke_adapter_callback_guarded_v1(
            ref,
            commitment,
            self._adapter.fresh_public_legal_actions_v1,
        )
        self._require_adapter_lineage_stable_v1(
            bundle.before,
            bundle.after,
            allow_legal_projection_change=True,
            allow_issuance_ledger_change=False,
        )
        adapter_snapshot = bundle.callback_result
        if type(adapter_snapshot) is not AdapterPublicLegalActionsSnapshotV1:
            raise C8CContractError("fresh public legal-set snapshot has unknown type")
        # Adapter objects may have been copied/tampered after construction; do
        # not rely on their original dataclass __post_init__ having run.
        for public_candidate in adapter_snapshot.public_legal_set.actions:
            if type(public_candidate) is not c8.PublicLegalActionCandidateV1:
                raise C8CContractError("fresh legal set candidate has unknown type")
            public_candidate.__post_init__()
        adapter_snapshot.public_legal_set.__post_init__()
        adapter_snapshot.__post_init__()
        adapter_ids = bundle.after
        self._runtime_adapter_linkage_v1(adapter_ids, self._runtime.state)
        snapshot_expected = {
            "runtime_instance_identity": commitment.runtime_instance_identity,
            "window_authority_ref_identity": ref.authority_ref_identity,
            "window_id": commitment.window_id,
            "decision_identity": commitment.decision_identity,
            "obligation_identity": commitment.obligation_identity,
            "session_identity": adapter_ids.session_identity,
            "controller_identity": adapter_ids.controller_identity,
            "adapter_identity": adapter_ids.adapter_identity,
            "public_state_identity": adapter_ids.public_state_identity,
            "authoritative_state_identity": adapter_ids.authoritative_state_identity,
            "issuance_security_ledger_identity": (
                adapter_ids.issuance_security_ledger_identity
            ),
            "snapshot_identity": adapter_ids.legal_set_snapshot_identity,
            "canonical_public_ordering_identity": adapter_ids.ordering_identity,
        }
        for field_name, expected in snapshot_expected.items():
            if getattr(adapter_snapshot, field_name) != expected:
                raise C8CContractError(
                    f"adapter public legal-set snapshot {field_name} mismatch"
                )
        expected_bindings: list[tuple[str, str, str]] = []
        for candidate in adapter_snapshot.public_legal_set.actions:
            binding = timeout_issuance_request_binding_v1(
                timeout_due_commitment_identity=commitment.commitment_identity,
                runtime_instance_identity=commitment.runtime_instance_identity,
                window_authority_ref_identity=ref.authority_ref_identity,
                session_identity=adapter_ids.session_identity,
                controller_identity=adapter_ids.controller_identity,
                adapter_identity=adapter_ids.adapter_identity,
                projection_legal_set_identity=(
                    adapter_snapshot.projection_legal_set_identity
                ),
                adapter_legal_set_snapshot_identity=adapter_snapshot.snapshot_identity,
                canonical_public_ordering_identity=(
                    adapter_snapshot.canonical_public_ordering_identity
                ),
                candidate=candidate,
            )
            _require_identity(binding, "expected timeout authentication binding")
            expected_bindings.append(
                (candidate.candidate_identity, candidate.action_id, binding)
            )
        binding_set_identity = timeout_authentication_bindings_identity_v1(
            adapter_snapshot.public_legal_set, tuple(expected_bindings)
        )
        envelope = build_fresh_public_legal_actions_envelope_v1(
            public_legal_set=adapter_snapshot.public_legal_set,
            adapter_legal_set_snapshot_identity=adapter_snapshot.snapshot_identity,
            timeout_authentication_bindings_identity=binding_set_identity,
            timeout_due_commitment_identity=commitment.commitment_identity,
            runtime_contract_identity=commitment.runtime_contract_identity,
            runtime_instance_identity=commitment.runtime_instance_identity,
            window_authority_ref_identity=ref.authority_ref_identity,
            session_identity=adapter_ids.session_identity,
            controller_identity=adapter_ids.controller_identity,
            adapter_identity=adapter_ids.adapter_identity,
            public_state_identity=adapter_ids.public_state_identity,
            authoritative_state_identity=adapter_ids.authoritative_state_identity,
            issuance_security_ledger_identity=(
                adapter_ids.issuance_security_ledger_identity
            ),
        )
        legal = adapter_snapshot.public_legal_set
        for field_name in (
            "window_id",
            "actor_id",
            "decision_identity",
            "obligation_identity",
        ):
            if getattr(legal, field_name) != getattr(commitment, field_name):
                raise C8CContractError(f"public legal set {field_name} mismatch")
        return envelope, tuple(expected_bindings)

    def _policy_for_window_v1(self, active_window: c8.TimedDecisionWindowV1) -> Any:
        try:
            policy = c8.TIMEOUT_FALLBACK_POLICY_BY_KIND_V1[active_window.window_kind]
        except (KeyError, TypeError) as exc:
            raise _AbortResolution(
                ControllerResultKindV1.TIMEOUT_UNRESOLVED,
                "NO_FROZEN_FALLBACK_POLICY",
            ) from exc
        if policy.window_kind != active_window.window_kind:
            raise C8CContractError("fallback policy window-kind mismatch")
        if policy.policy_identity != active_window.fallback_policy_identity:
            raise C8CContractError("active window fallback policy identity mismatch")
        return policy

    def _validate_resolution_and_select_candidate_v1(
        self,
        resolution: Any,
        active_window: c8.TimedDecisionWindowV1,
        commitment: Any,
        envelope: FreshPublicLegalActionsEnvelopeV1,
        policy: Any,
    ) -> c8.PublicLegalActionCandidateV1:
        if type(resolution) is not c8.TimeoutResolutionV1:
            raise C8CContractError("C8-A resolver returned an unknown result type")
        resolution.__post_init__()
        cold_resolution = c8.TimeoutResolutionV1.from_dict(
            resolution.to_dict(),
            window=active_window,
            current_tick=commitment.now_tick,
            public_legal_set=envelope.public_legal_set,
            fallback_policy=policy,
        )
        if cold_resolution != resolution or (
            cold_resolution.resolution_identity != resolution.resolution_identity
        ):
            raise C8CContractError("C8-A resolution cold validation mismatch")
        required_fields = (
            "schema",
            "contract_version",
            "resolution_kind",
            "reason",
            "resolution_tick",
            "deadline_at",
            "window_id",
            "window_state_identity",
            "obligation_identity",
            "legal_set_identity",
            "policy_identity",
            "resolved_public_ordinal",
            "resolved_candidate_identity",
            "resolved_action_family",
            "same_tick_chain_required",
            "resolution_identity",
        )
        for field_name in required_fields:
            _read_required_attr(resolution, field_name)
        resolution_kind = _enum_text(
            resolution.resolution_kind, "resolution.resolution_kind"
        )
        if resolution_kind in {"TIMEOUT_NOT_DUE", "TIMEOUT_UNRESOLVED"}:
            raise _AbortResolution(
                ControllerResultKindV1.TIMEOUT_UNRESOLVED,
                resolution_kind,
            )
        if resolution_kind != "RESOLVE_TO_PUBLIC_ACTION_ORDINAL":
            raise C8CContractError("unknown C8-A timeout resolution kind")
        expected_pairs = {
            "resolution_tick": commitment.now_tick,
            "deadline_at": commitment.deadline_at,
            "window_id": active_window.window_id,
            "window_state_identity": active_window.window_state_identity,
            "obligation_identity": active_window.obligation_identity,
            "legal_set_identity": envelope.public_legal_set.legal_set_identity,
            "policy_identity": policy.policy_identity,
            "same_tick_chain_required": policy.same_tick_chain_required,
        }
        for field_name, expected in expected_pairs.items():
            if getattr(resolution, field_name) != expected:
                raise C8CContractError(f"resolver {field_name} mismatch")
        ordinal = _require_exact_int(
            resolution.resolved_public_ordinal,
            "resolution.resolved_public_ordinal",
            minimum=0,
        )
        matches = [
            item
            for item in envelope.public_legal_set.actions
            if item.public_ordinal == ordinal
        ]
        if len(matches) != 1:
            raise _AbortResolution(
                ControllerResultKindV1.TIMEOUT_UNRESOLVED,
                "RESOLVED_ORDINAL_NOT_UNIQUE_IN_FRESH_SET",
            )
        candidate = matches[0]
        if candidate.candidate_identity != resolution.resolved_candidate_identity:
            raise C8CContractError("resolved candidate identity mismatch")
        if candidate.action_family != resolution.resolved_action_family:
            raise C8CContractError("resolved action family mismatch")
        self._validate_policy_membership_v1(
            active_window, policy, envelope.public_legal_set, candidate
        )
        return candidate

    def _validate_policy_membership_v1(
        self,
        window: c8.TimedDecisionWindowV1,
        policy: Any,
        legal_set: c8.PublicLegalSetProjectionV1,
        candidate: c8.PublicLegalActionCandidateV1,
    ) -> None:
        window_kind = _enum_text(window.window_kind, "window.window_kind")
        selector = _enum_text(policy.selector, "policy.selector")
        if type(policy.allowed_action_families) is not tuple:
            raise C8CContractError("allowed action families must be an exact tuple")
        allowed = tuple(
            _enum_text(item, "policy.allowed_action_family")
            for item in policy.allowed_action_families
        )
        candidate_family = _enum_text(
            candidate.action_family, "candidate.action_family"
        )
        if window_kind == "MANDATORY_SINGLE_ACTION":
            if selector != "UNIQUE_LEGAL_ACTION" or len(legal_set.actions) != 1:
                raise _AbortResolution(
                    ControllerResultKindV1.TIMEOUT_UNRESOLVED,
                    "MANDATORY_SINGLE_NOT_EXACTLY_ONE",
                )
            if legal_set.actions[0].candidate_identity != candidate.candidate_identity:
                raise C8CContractError("mandatory-single candidate mismatch")
            return
        if window_kind == "MANDATORY_PUBLIC_CHOICE":
            if selector != "CANONICAL_PUBLIC_ORDINAL":
                raise C8CContractError("mandatory public choice selector mismatch")
            if policy.ordering_contract_id != legal_set.ordering_contract_id:
                raise _AbortResolution(
                    ControllerResultKindV1.TIMEOUT_UNRESOLVED,
                    "PUBLIC_ORDERING_CONTRACT_MISMATCH",
                )
            if not legal_set.actions:
                raise _AbortResolution(
                    ControllerResultKindV1.TIMEOUT_UNRESOLVED,
                    "MANDATORY_PUBLIC_CHOICE_HAS_NO_CANDIDATE",
                )
            if any(
                _enum_text(item.action_family, "candidate.action_family")
                != "public_choice"
                for item in legal_set.actions
            ):
                raise _AbortResolution(
                    ControllerResultKindV1.TIMEOUT_UNRESOLVED,
                    "MANDATORY_PUBLIC_CHOICE_HAS_NON_PUBLIC_CHOICE_CANDIDATE",
                )
            if candidate.public_ordinal != 0:
                raise _AbortResolution(
                    ControllerResultKindV1.TIMEOUT_UNRESOLVED,
                    "MANDATORY_PUBLIC_CHOICE_NOT_CANONICAL_ORDINAL_ZERO",
                )
            if legal_set.actions[0].candidate_identity != candidate.candidate_identity:
                raise C8CContractError("canonical public ordinal linkage mismatch")
            return
        if candidate_family not in allowed:
            raise _AbortResolution(
                ControllerResultKindV1.TIMEOUT_UNRESOLVED,
                "SELECTED_ACTION_NOT_POLICY_ELIGIBLE",
            )
        family_by_kind = {
            "PLAY": ("EXPLICIT_ACTION_FAMILY", "end_play_phase"),
            "OPTIONAL_RESPONSE": ("EXPLICIT_ACTION_FAMILY", "pass_response"),
            "RESCUE_RESPONSE": ("EXPLICIT_ACTION_FAMILY", "pass_rescue"),
            "OPTIONAL_SKILL_DECISION": (
                "EXPLICIT_ACTION_FAMILY",
                "decline_optional",
            ),
            "MODE_DECISION": (
                "EXPLICIT_ACTION_FAMILY",
                "pass_mode_decision",
            ),
        }
        if window_kind in family_by_kind:
            expected_selector, expected_family = family_by_kind[window_kind]
            if selector != expected_selector or candidate_family != expected_family:
                raise _AbortResolution(
                    ControllerResultKindV1.TIMEOUT_UNRESOLVED,
                    "EXPLICIT_PUBLIC_FALLBACK_MISSING",
                )
            return
        if window_kind == "MULTI_STEP_OBLIGATION":
            if selector != "MULTI_STEP_SAFE_PUBLIC_FALLBACK":
                raise C8CContractError("multi-step selector mismatch")
            if policy.same_tick_chain_required is not True:
                raise C8CContractError("multi-step policy lacks same-tick chain")
            return
        raise C8CContractError("unknown frozen C8-A window kind")

    def _reconfirm_current_lineage_before_issuance_v1(
        self,
        ref: Any,
        commitment: Any,
        envelope: FreshPublicLegalActionsEnvelopeV1,
    ) -> None:
        current = self._runtime.current_timeout_due_commitment_v1(ref)
        if current is None or not _object_fields_equal(
            current, commitment, _TIMEOUT_COMMITMENT_FIELDS
        ):
            raise _AbortResolution(
                ControllerResultKindV1.FAILED_ROLLED_BACK,
                "COMMITMENT_CHANGED_BEFORE_ISSUANCE",
            )
        try:
            probe_binding = (
                self._runtime.expected_timeout_action_authentication_binding_v1(
                    ref,
                    timeout_due_commitment=commitment,
                    signed_action_id=C8_C_LIVE_COMMITMENT_PROBE_ACTION_REFERENCE,
                )
            )
            _require_identity(probe_binding, "reconfirmed live commitment probe")
        except Exception as exc:
            raise _AbortResolution(
                ControllerResultKindV1.FAILED_ROLLED_BACK,
                "COMMITMENT_OBJECT_NOT_LIVE_BEFORE_ISSUANCE",
            ) from exc
        # Adapter legal-set and ordering lineage are re-read inside the guarded
        # issuance callback.  No adapter hook may run outside that B guard.

    def _confirm_issuance_with_recovery_v1(
        self,
        *,
        window_authority_ref: Any,
        commitment: Any,
        candidate: c8.PublicLegalActionCandidateV1,
        envelope: FreshPublicLegalActionsEnvelopeV1,
        selected_binding: str,
        issuance_security_ledger_before: str,
        transaction_identity: str,
        runtime_before_issuance: Any,
        public_before_issuance: Any,
    ) -> tuple[
        SignedActionIssuanceEvidenceV1,
        str,
        rt.PendingTimeoutIssuanceCapabilityV1,
        str,
    ]:
        try:
            bundle, guard_result = self._invoke_adapter_callback_guarded_v1(
                window_authority_ref,
                commitment,
                lambda: self._adapter.confirm_and_issue_signed_action_v1(
                    candidate.action_id,
                    candidate.public_ordinal,
                    envelope.legal_set_identity,
                    selected_binding,
                    commitment.commitment_identity,
                ),
                precondition=lambda identities: (
                    self._require_issuance_precondition_v1(
                        identities, envelope
                    )
                ),
            )
        except Exception as exc:
            recovered = self._recover_failed_issuance_attempt_v1(
                window_authority_ref=window_authority_ref,
                commitment=commitment,
                transaction_identity=transaction_identity,
                envelope=envelope,
                candidate=candidate,
                selected_binding=selected_binding,
                security_ledger_before=issuance_security_ledger_before,
            )
            if self._runtime.state != runtime_before_issuance or (
                self._runtime.public_projection() != public_before_issuance
            ):
                self._poisoned = True
            if not recovered:
                self._poisoned = True
            raise _AbortResolution(
                (
                    ControllerResultKindV1.FAILED_POISONED
                    if self._poisoned
                    else ControllerResultKindV1.FAILED_ROLLED_BACK
                ),
                (
                    "FAILED_ISSUANCE_RECOVERY_UNPROVEN"
                    if self._poisoned
                    else "ISSUANCE_CALLBACK_FAILED_CAPABILITIES_RECOVERED"
                ),
            ) from exc

        returned = bundle.callback_result
        observed = bundle.after.issuance_security_ledger_identity

        # Every exact typed return is pending before any self-hash or context
        # validation.  That ordering ensures later rejection cannot strand its
        # external authorization capability.
        pending_key = _identity(
            {
                "schema": "sgs-c8-c-pending-issuance-key-v1",
                "contract_version": 1,
                "transaction_identity": transaction_identity,
                "legal_set_identity": envelope.legal_set_identity,
                "candidate_identity": candidate.candidate_identity,
                "public_ordinal": candidate.public_ordinal,
            }
        )
        if type(returned) is SignedActionIssuanceEvidenceV1:
            self._unforwarded_issuances[pending_key] = returned

        context = _FailedIssuanceRecoveryContext(
            window_authority_ref=window_authority_ref,
            envelope=envelope,
            candidate=candidate,
            transaction_identity=transaction_identity,
            legal_set_identity=envelope.legal_set_identity,
            candidate_reference=candidate.action_id,
            public_ordinal=candidate.public_ordinal,
            timeout_auth_binding=selected_binding,
            security_ledger_before_identity=issuance_security_ledger_before,
            security_ledger_observed_after_failure_identity=observed,
        )
        if type(returned) is SignedActionIssuanceEvidenceV1:
            self._unforwarded_issuance_contexts[pending_key] = context
        else:
            recovered = self._recover_failed_issuance_attempt_v1(
                window_authority_ref=window_authority_ref,
                commitment=commitment,
                transaction_identity=transaction_identity,
                envelope=envelope,
                candidate=candidate,
                selected_binding=selected_binding,
                security_ledger_before=issuance_security_ledger_before,
            )
            if self._runtime.state != runtime_before_issuance or (
                self._runtime.public_projection() != public_before_issuance
            ):
                self._poisoned = True
            if not recovered:
                self._poisoned = True
            raise _AbortResolution(
                (
                    ControllerResultKindV1.FAILED_POISONED
                    if self._poisoned
                    else ControllerResultKindV1.FAILED_ROLLED_BACK
                ),
                (
                    "FAILED_ISSUANCE_RECOVERY_UNPROVEN"
                    if self._poisoned
                    else "UNKNOWN_ISSUANCE_TYPE_RECOVERED"
                ),
            )

        try:
            self._require_adapter_lineage_stable_v1(
                bundle.before,
                bundle.after,
                allow_legal_projection_change=False,
                allow_issuance_ledger_change=True,
            )
            expected_before = {
                "adapter_identity": envelope.adapter_identity,
                "session_identity": envelope.session_identity,
                "controller_identity": envelope.controller_identity,
                "public_state_identity": envelope.public_state_identity,
                "authoritative_state_identity": envelope.authoritative_state_identity,
                "issuance_security_ledger_identity": (
                    issuance_security_ledger_before
                ),
                "legal_set_snapshot_identity": (
                    envelope.adapter_legal_set_snapshot_identity
                ),
                "ordering_identity": envelope.canonical_public_ordering_identity,
            }
            for field_name, expected_value in expected_before.items():
                if getattr(bundle.before, field_name) != expected_value:
                    raise C8CContractError(
                        f"issuance callback pre-{field_name} mismatch"
                    )
            # Re-run exact dataclass integrity because a frozen object can still
            # be altered after its original construction.
            returned.__post_init__()
            if (
                returned.issuance_security_ledger_before_identity
                != issuance_security_ledger_before
            ):
                raise C8CContractError(
                    "issuance pre-confirm security ledger mismatch"
                )
            if returned.issuance_security_ledger_after_identity != observed:
                raise C8CContractError(
                    "issuance post-confirm security ledger mismatch"
                )
            self._ensure_runtime_unchanged_v1(
                runtime_before_issuance,
                public_before_issuance,
                "ISSUANCE_CALLBACK_MUTATED_RUNTIME",
            )
            self._ensure_not_poisoned_v1()
            self._validate_issuance_v1(
                returned,
                candidate,
                envelope,
                commitment,
                selected_binding,
                issuance_security_ledger_before,
                bundle.before,
                bundle.after,
            )
        except Exception as exc:
            # The returned object is untrusted until every check above passes.
            # Recover by before->current adapter ledger delta, never by a token
            # or identity read from that object.
            try:
                recovered = self._recover_failed_issuance_attempt_v1(
                    window_authority_ref=window_authority_ref,
                    commitment=commitment,
                    transaction_identity=transaction_identity,
                    envelope=envelope,
                    candidate=candidate,
                    selected_binding=selected_binding,
                    security_ledger_before=issuance_security_ledger_before,
                )
            except Exception:
                recovered = False
            self._unforwarded_issuances.pop(pending_key, None)
            self._unforwarded_issuance_contexts.pop(pending_key, None)
            if not recovered:
                self._poisoned = True
            raise _AbortResolution(
                (
                    ControllerResultKindV1.FAILED_POISONED
                    if self._poisoned
                    else ControllerResultKindV1.FAILED_ROLLED_BACK
                ),
                (
                    "FAILED_ISSUANCE_RECOVERY_UNPROVEN"
                    if self._poisoned
                    else "ISSUANCE_VALIDATION_FAILED_CAPABILITIES_RECOVERED"
                ),
            ) from exc

        try:
            pending_b_capability = (
                self._runtime.register_pending_timeout_issuance_capability_v1(
                    window_authority_ref,
                    timeout_due_commitment=commitment,
                    guard_result=guard_result,
                    signed_action_id=returned.signed_action_id,
                    external_capability_identity=(
                        returned.external_capability_identity
                    ),
                )
            )
            if type(pending_b_capability) is not rt.PendingTimeoutIssuanceCapabilityV1:
                raise C8CContractError(
                    "B returned unknown pending issuance capability"
                )
            pending_b_capability.__post_init__()
            self._pending_b_capabilities[pending_key] = pending_b_capability
            ownership = self._pending_capability_ownership_v1(
                pending_b_capability
            )
            if self._ownership_status_v1(ownership) != "CONTROLLER_OWNED_PENDING":
                raise C8CContractError(
                    "new B pending issuance capability is not controller-owned"
                )
            final_binding = (
                self._runtime.expected_timeout_action_authentication_binding_v1(
                    window_authority_ref,
                    timeout_due_commitment=commitment,
                    signed_action_id=returned.signed_action_id,
                    pending_issuance_capability=pending_b_capability,
                )
            )
            _require_identity(final_binding, "B capability-bound authorization binding")
        except Exception as exc:
            pending = self._pending_b_capabilities.get(pending_key)
            if pending is not None:
                secured = self._abort_registered_pending_issuance_v1(
                    window_authority_ref,
                    commitment,
                    pending_key,
                    returned,
                    pending,
                )
            else:
                secured = self._recover_failed_issuance_attempt_v1(
                    window_authority_ref=window_authority_ref,
                    commitment=commitment,
                    transaction_identity=transaction_identity,
                    envelope=envelope,
                    candidate=candidate,
                    selected_binding=selected_binding,
                    security_ledger_before=issuance_security_ledger_before,
                )
                self._unforwarded_issuances.pop(pending_key, None)
                self._unforwarded_issuance_contexts.pop(pending_key, None)
            if not secured:
                self._poisoned = True
            raise _AbortResolution(
                (
                    ControllerResultKindV1.FAILED_POISONED
                    if self._poisoned
                    else ControllerResultKindV1.FAILED_ROLLED_BACK
                ),
                (
                    "PENDING_CAPABILITY_REGISTRATION_RECOVERY_UNPROVEN"
                    if self._poisoned
                    else "PENDING_CAPABILITY_REGISTRATION_FAILED_ABORTED"
                ),
            ) from exc
        return returned, pending_key, pending_b_capability, final_binding

    def _recover_failed_issuance_attempt_v1(
        self,
        *,
        window_authority_ref: Any,
        commitment: Any,
        transaction_identity: str,
        envelope: FreshPublicLegalActionsEnvelopeV1,
        candidate: c8.PublicLegalActionCandidateV1,
        selected_binding: str,
        security_ledger_before: str,
    ) -> bool:
        try:
            probe_bundle, _ = self._invoke_adapter_callback_guarded_v1(
                window_authority_ref,
                commitment,
                lambda: None,
            )
            self._require_adapter_lineage_stable_v1(
                probe_bundle.before,
                probe_bundle.after,
                allow_legal_projection_change=False,
                allow_issuance_ledger_change=False,
            )
            observed = probe_bundle.after.issuance_security_ledger_identity
            if observed == security_ledger_before:
                return True
            recovery_bundle, _ = self._invoke_adapter_callback_guarded_v1(
                window_authority_ref,
                commitment,
                lambda: self._adapter.recover_failed_issuance_attempt_v1(
                    issuance_security_ledger_before_identity=(
                        security_ledger_before
                    ),
                    issuance_security_ledger_observed_after_failure_identity=(
                        observed
                    ),
                    transaction_identity=transaction_identity,
                    legal_set_identity=envelope.legal_set_identity,
                    candidate_reference=candidate.action_id,
                    public_ordinal=candidate.public_ordinal,
                    timeout_auth_binding=selected_binding,
                ),
            )
            self._require_adapter_lineage_stable_v1(
                recovery_bundle.before,
                recovery_bundle.after,
                allow_legal_projection_change=False,
                allow_issuance_ledger_change=True,
            )
            evidence = recovery_bundle.callback_result
            if type(evidence) is not FailedIssuanceRecoveryEvidenceV1:
                return False
            evidence.__post_init__()
            expected = {
                "transaction_identity": transaction_identity,
                "legal_set_identity": envelope.legal_set_identity,
                "candidate_reference": candidate.action_id,
                "public_ordinal": candidate.public_ordinal,
                "timeout_auth_binding": selected_binding,
                "runtime_instance_identity": envelope.runtime_instance_identity,
                "window_authority_ref_identity": (
                    envelope.window_authority_ref_identity
                ),
                "session_identity": envelope.session_identity,
                "controller_identity": envelope.controller_identity,
                "adapter_identity": envelope.adapter_identity,
                "security_ledger_before_identity": security_ledger_before,
                "security_ledger_observed_after_failure_identity": (
                    observed
                ),
                "recovered": True,
            }
            for field_name, expected_value in expected.items():
                if getattr(evidence, field_name) != expected_value:
                    return False
            current_after = recovery_bundle.after.issuance_security_ledger_identity
            if evidence.security_ledger_after_recovery_identity != current_after:
                return False
            _require_identity(current_after, "recovered issuance security ledger")
            if evidence.recovery_identity in self._failed_issuance_recovery_identities:
                return False
            if not self._verify_timeout_due_coherence_after_security_change_v1(
                window_authority_ref
            ):
                return False
            self._failed_issuance_recovery_identities.add(
                evidence.recovery_identity
            )
            return True
        except Exception:
            return False

    def _verify_timeout_due_coherence_after_security_change_v1(
        self, window_authority_ref: Any
    ) -> bool:
        """Ensure adapter-only revocation did not desynchronize C8-B's ledger."""
        try:
            live = self._runtime.current_timeout_due_commitment_v1(
                window_authority_ref
            )
            if live is None:
                return False
            self._verify_commitment_and_window_v1(live, window_authority_ref)
            probe = self._runtime.expected_timeout_action_authentication_binding_v1(
                window_authority_ref,
                timeout_due_commitment=live,
                signed_action_id=C8_C_LIVE_COMMITMENT_PROBE_ACTION_REFERENCE,
            )
            _require_identity(probe, "post-security-change B coherence probe")
            return True
        except Exception:
            return False

    def _validate_issuance_v1(
        self,
        issuance: Any,
        candidate: c8.PublicLegalActionCandidateV1,
        envelope: FreshPublicLegalActionsEnvelopeV1,
        commitment: Any,
        expected_binding: str,
        issuance_security_ledger_before: str,
        adapter_before: _AdapterIdentities,
        adapter_after: _AdapterIdentities,
    ) -> None:
        if type(issuance) is not SignedActionIssuanceEvidenceV1:
            raise C8CContractError("issuance evidence has unknown type")
        expected = {
            "public_action_reference": candidate.action_id,
            "public_ordinal": candidate.public_ordinal,
            "candidate_identity": candidate.candidate_identity,
            "action_family": _enum_text(
                candidate.action_family, "candidate.action_family"
            ),
            "legal_set_identity": envelope.legal_set_identity,
            "canonical_public_ordering_identity": (
                envelope.canonical_public_ordering_identity
            ),
            "timeout_due_commitment_identity": commitment.commitment_identity,
            "authorization_binding_identity": expected_binding,
            "issuance_authority_identity": adapter_after.issuance_authority_identity,
            "runtime_instance_identity": commitment.runtime_instance_identity,
            "window_authority_ref_identity": envelope.window_authority_ref_identity,
            "window_id": envelope.window_id,
            "session_identity": envelope.session_identity,
            "controller_identity": envelope.controller_identity,
            "adapter_identity": envelope.adapter_identity,
            "public_state_identity": envelope.public_state_identity,
            "authoritative_state_identity": envelope.authoritative_state_identity,
            "issuance_security_ledger_before_identity": (
                issuance_security_ledger_before
            ),
            "issuance_security_ledger_after_identity": (
                adapter_after.issuance_security_ledger_identity
            ),
        }
        for field_name, expected_value in expected.items():
            if getattr(issuance, field_name) != expected_value:
                raise _AbortResolution(
                    ControllerResultKindV1.FAILED_ROLLED_BACK,
                    f"ISSUANCE_{field_name.upper()}_MISMATCH",
                )
        if issuance.signed_action_id_commitment != signed_action_id_commitment_v1(
            issuance.signed_action_id
        ):
            raise _AbortResolution(
                ControllerResultKindV1.FAILED_ROLLED_BACK,
                "ISSUANCE_SIGNED_ACTION_COMMITMENT_MISMATCH",
            )
        if (
            adapter_before.legal_set_snapshot_identity
            != envelope.adapter_legal_set_snapshot_identity
            or adapter_after.legal_set_snapshot_identity
            != envelope.adapter_legal_set_snapshot_identity
        ):
            raise _AbortResolution(
                ControllerResultKindV1.FAILED_ROLLED_BACK,
                "LEGAL_SET_CHANGED_DURING_ISSUANCE",
            )
        if (
            adapter_before.ordering_identity
            != envelope.canonical_public_ordering_identity
            or adapter_after.ordering_identity
            != envelope.canonical_public_ordering_identity
        ):
            raise _AbortResolution(
                ControllerResultKindV1.FAILED_ROLLED_BACK,
                "ORDERING_CHANGED_DURING_ISSUANCE",
            )

    def _verify_receipt_v1(
        self,
        receipt: Any,
        ref: Any,
        commitment: Any,
        envelope: FreshPublicLegalActionsEnvelopeV1,
        issuance: SignedActionIssuanceEvidenceV1,
        expected_binding: str,
        pre_forward_state: Any,
        pending_capability: rt.PendingTimeoutIssuanceCapabilityV1,
        ownership: rt.PendingIssuanceCapabilityOwnershipV1,
    ) -> None:
        if type(receipt) is not rt.TimeoutActionExecutionReceiptV1:
            raise C8CContractError("execution receipt has unknown type")
        receipt.__post_init__()
        cold_receipt = rt.TimeoutActionExecutionReceiptV1.from_dict(
            receipt.to_dict()
        )
        if cold_receipt != receipt:
            raise C8CContractError("execution receipt cold validation mismatch")
        if receipt.schema != "sgs-c8-b-timeout-signed-action-execution-receipt-v1":
            raise C8CContractError("execution receipt schema mismatch")
        if type(receipt.contract_version) is not int or receipt.contract_version != 1:
            raise C8CContractError("execution receipt version mismatch")
        expected_action_commitment = signed_action_id_commitment_v1(
            issuance.signed_action_id
        )
        expected = {
            "runtime_contract_identity": commitment.runtime_contract_identity,
            "runtime_instance_identity": commitment.runtime_instance_identity,
            "window_authority_ref_identity": ref.authority_ref_identity,
            "window_id": commitment.window_id,
            "actor_id": commitment.actor_id,
            "decision_identity": commitment.decision_identity,
            "obligation_identity": commitment.obligation_identity,
            "signed_action_id_commitment": expected_action_commitment,
            "pre_inner_public_state_identity": envelope.public_state_identity,
            "pre_inner_authoritative_state_identity": (
                envelope.authoritative_state_identity
            ),
            "inner_adapter_identity": envelope.adapter_identity,
            "inner_session_binding_identity": envelope.session_identity,
            "issuance_authority_identity": issuance.issuance_authority_identity,
            "authorization_evidence_identity": (
                issuance.authorization_evidence_identity
            ),
            "authorization_binding_identity": expected_binding,
            "authorization_ledger_before_identity": (
                pending_capability.authorization_ledger_identity_at_issue
            ),
            "timeout_due_commitment_identity": commitment.commitment_identity,
            "pending_deadline_identity": commitment.pending_deadline_identity,
            "derived_deadline_identity": commitment.derived_deadline_identity,
            "deadline_at": commitment.deadline_at,
            "executed_at_tick": commitment.now_tick,
            "accepted": True,
            "executed": True,
            "pending_issuance_capability_identity": (
                pending_capability.capability_identity
            ),
        }
        for field_name, expected_value in expected.items():
            if getattr(receipt, field_name) != expected_value:
                raise _AbortResolution(
                    ControllerResultKindV1.FAILED_ROLLED_BACK,
                    f"RECEIPT_{field_name.upper()}_MISMATCH",
                )
        pre_checks = {
            "inner_public_state_identity": envelope.public_state_identity,
            "inner_authoritative_state_identity": (
                envelope.authoritative_state_identity
            ),
            "inner_adapter_identity": envelope.adapter_identity,
            "inner_session_binding_identity": envelope.session_identity,
            "input_authenticator_identity": issuance.issuance_authority_identity,
        }
        for field_name, expected_value in pre_checks.items():
            if _read_required_attr(pre_forward_state, field_name) != expected_value:
                raise C8CContractError(f"pre-forward {field_name} drift")
        post_state = self._runtime.state
        if receipt.post_inner_public_state_identity != _read_required_attr(
            post_state, "inner_public_state_identity"
        ):
            raise _AbortResolution(
                ControllerResultKindV1.FAILED_ROLLED_BACK,
                "RECEIPT_POST_PUBLIC_STATE_MISMATCH",
            )
        if receipt.post_inner_authoritative_state_identity != _read_required_attr(
            post_state, "inner_authoritative_state_identity"
        ):
            raise _AbortResolution(
                ControllerResultKindV1.FAILED_ROLLED_BACK,
                "RECEIPT_POST_AUTHORITATIVE_STATE_MISMATCH",
            )
        if self._ownership_status_v1(ownership) != "RECEIPT_COMMITTED_CONSUMED":
            raise _AbortResolution(
                ControllerResultKindV1.FAILED_ROLLED_BACK,
                "RECEIPT_CAPABILITY_OWNERSHIP_NOT_COMMITTED",
            )
        if ownership.committed_receipt_identity != receipt.receipt_identity:
            raise _AbortResolution(
                ControllerResultKindV1.FAILED_ROLLED_BACK,
                "RECEIPT_CAPABILITY_COMMITTED_RECEIPT_MISMATCH",
            )
        for identity_field in (
            "previous_receipt_identity",
            "authorization_ledger_before_identity",
            "authorization_ledger_after_identity",
            "outer_transition_identity",
            "receipt_identity",
        ):
            _require_identity(
                getattr(receipt, identity_field),
                f"receipt.{identity_field}",
                allow_zero=identity_field == "previous_receipt_identity",
            )
        _require_exact_int(receipt.receipt_sequence, "receipt.receipt_sequence", minimum=0)
        if (
            receipt.authorization_ledger_before_identity
            == receipt.authorization_ledger_after_identity
        ):
            raise C8CContractError("authorization ledger did not advance")

    def _validate_completion_evidence_v1(
        self,
        completion: Any,
        receipt: rt.TimeoutActionExecutionReceiptV1,
        issuance: SignedActionIssuanceEvidenceV1,
        envelope: FreshPublicLegalActionsEnvelopeV1,
        commitment: Any,
    ) -> None:
        if type(completion) is not ReceiptLineageCompletionEvidenceV1:
            raise C8CContractError("completion evidence has unknown type")
        completion.__post_init__()
        expected = {
            "receipt_identity": receipt.receipt_identity,
            "issuance_identity": issuance.issuance_identity,
            "legal_set_identity": envelope.legal_set_identity,
            "runtime_instance_identity": commitment.runtime_instance_identity,
            "window_authority_ref_identity": envelope.window_authority_ref_identity,
            "window_id": commitment.window_id,
            "decision_identity": commitment.decision_identity,
            "obligation_identity": commitment.obligation_identity,
            "session_identity": envelope.session_identity,
            "controller_identity": envelope.controller_identity,
            "adapter_identity": envelope.adapter_identity,
            "post_public_state_identity": receipt.post_inner_public_state_identity,
            "post_authoritative_state_identity": (
                receipt.post_inner_authoritative_state_identity
            ),
        }
        for field_name, expected_value in expected.items():
            if getattr(completion, field_name) != expected_value:
                raise _AbortResolution(
                    ControllerResultKindV1.FAILED_ROLLED_BACK,
                    f"COMPLETION_{field_name.upper()}_MISMATCH",
                )
        current_state = self._runtime.state
        if (
            current_state.inner_public_state_identity
            != completion.post_public_state_identity
        ):
            raise C8CContractError("completion current public identity mismatch")
        if (
            current_state.inner_authoritative_state_identity
            != completion.post_authoritative_state_identity
        ):
            raise C8CContractError("completion current authoritative identity mismatch")

    def _verify_continuation_v1(
        self,
        precedence: Any,
        ref: Any,
        *,
        initial_tick: int,
        initial_deadline: int,
        initial_opened_at: int,
        initial_parent_window_id: str | None,
        execution_receipt: rt.TimeoutActionExecutionReceiptV1,
        logical_step_identity: str,
        expected_step_index: int,
        pre_continue_state: Any,
        pre_continue_public_projection: Any,
    ) -> None:
        if type(precedence) is not c8.DeadlinePrecedenceV1:
            raise C8CContractError("continuation returned unknown precedence type")
        if _enum_text(precedence, "deadline_precedence") != (
            "TIMEOUT_PRIORITY_AT_OR_AFTER_DEADLINE"
        ):
            raise C8CContractError("continuation lost timeout deadline priority")
        active = self._active_window_v1()
        if active.window_id != ref.window_id:
            raise C8CContractError("continuation changed window id")
        if active.opened_at != initial_opened_at:
            raise C8CContractError("continuation refreshed opened_at")
        if active.deadline_at != initial_deadline:
            raise C8CContractError("continuation refreshed deadline")
        if active.parent_window_id != initial_parent_window_id:
            raise C8CContractError("continuation changed parent window")
        current = self._runtime.current_timeout_due_commitment_v1(ref)
        if current is None:
            raise C8CContractError("continuation did not preserve timeout due status")
        if current.now_tick != initial_tick:
            raise C8CContractError("continuation changed virtual time")
        if current.deadline_at != initial_deadline:
            raise C8CContractError("continuation changed derived deadline")
        state = self._runtime.state
        if state.state_identity == pre_continue_state.state_identity:
            raise C8CContractError("continuation did not advance outer state")
        if state.event_chain_tip == pre_continue_state.event_chain_tip:
            raise C8CContractError("continuation did not advance B event chain")
        pre_events = pre_continue_state.runtime_events
        post_events = state.runtime_events
        if type(pre_events) is not tuple or type(post_events) is not tuple:
            raise C8CContractError("runtime events must be exact tuples")
        if len(post_events) != len(pre_events) + 1 or post_events[:-1] != pre_events:
            raise C8CContractError("continuation must append exactly one B event")
        continuation_event = post_events[-1]
        if type(continuation_event) is not rt.RuntimeEventV1:
            raise C8CContractError("continuation appended unknown B event type")
        continuation_event.__post_init__()
        if _enum_text(
            continuation_event.event_kind, "continuation_event.event_kind"
        ) != "TIMEOUT_MULTI_STEP_CONTINUED":
            raise C8CContractError("continuation appended wrong B event kind")
        if continuation_event.window_id != ref.window_id:
            raise C8CContractError("continuation event window mismatch")
        if continuation_event.logical_step_identity != logical_step_identity:
            raise C8CContractError("continuation event logical-step mismatch")
        if (
            continuation_event.execution_receipt_identity
            != execution_receipt.receipt_identity
        ):
            raise C8CContractError("continuation event receipt mismatch")
        if continuation_event.previous_event_identity != pre_continue_state.event_chain_tip:
            raise C8CContractError("continuation event previous identity mismatch")
        if continuation_event.event_identity != state.event_chain_tip:
            raise C8CContractError("continuation event is not B event-chain tip")
        pre_progress = self._logical_progress_for_window_v1(
            pre_continue_state, ref.window_id
        )
        post_progress = self._logical_progress_for_window_v1(state, ref.window_id)
        if pre_progress.next_step_index != expected_step_index:
            raise C8CContractError("pre-continuation logical step index mismatch")
        if post_progress.next_step_index != pre_progress.next_step_index + 1:
            raise C8CContractError("logical progress did not advance exactly once")
        if post_progress.step_identities != (
            pre_progress.step_identities + (logical_step_identity,)
        ):
            raise C8CContractError("logical progress step chain mismatch")
        for field_name in (
            "window_id",
            "window_binding_identity",
            "obligation_identity",
        ):
            if getattr(post_progress, field_name) != getattr(pre_progress, field_name):
                raise C8CContractError(f"logical progress {field_name} changed")
        if post_progress.progress_identity == pre_progress.progress_identity:
            raise C8CContractError("logical progress identity did not advance")
        post_public = self._runtime.public_projection()
        if post_public.active_window_id != ref.window_id:
            raise C8CContractError("continuation changed public active window")
        if post_public.window_depth != pre_continue_public_projection.window_depth:
            raise C8CContractError("continuation changed public window depth")
        if post_public.event_chain_tip != state.event_chain_tip:
            raise C8CContractError("continuation public event tip mismatch")
        if post_public.projection_identity == pre_continue_public_projection.projection_identity:
            raise C8CContractError("continuation did not advance public projection")
        for field_name, expected_value in (
            ("inner_adapter_identity", execution_receipt.inner_adapter_identity),
            (
                "inner_session_binding_identity",
                execution_receipt.inner_session_binding_identity,
            ),
            (
                "input_authenticator_identity",
                execution_receipt.issuance_authority_identity,
            ),
        ):
            if getattr(self._runtime.state, field_name) != expected_value:
                raise C8CContractError(
                    f"continuation runtime {field_name} lineage mismatch"
                )

    def _logical_progress_for_window_v1(self, state: Any, window_id: str) -> Any:
        obligations = _read_required_attr(state, "logical_obligations")
        if type(obligations) is not tuple:
            raise C8CContractError("logical obligations must be an exact tuple")
        matches = [item for item in obligations if item.window_id == window_id]
        if len(matches) != 1:
            raise C8CContractError("logical obligation progress is not unique")
        progress = matches[0]
        if type(progress) is not rt.LogicalObligationProgressV1:
            raise C8CContractError("logical obligation progress has unknown type")
        progress.__post_init__()
        return progress

    def _verify_closed_window_v1(
        self,
        closed: Any,
        prior_active: c8.TimedDecisionWindowV1,
        *,
        window_authority_ref: Any,
        execution_receipt: rt.TimeoutActionExecutionReceiptV1,
        pre_close_state: Any,
        pre_close_public_projection: Any,
        initial_tick: int,
        initial_deadline: int,
        initial_opened_at: int,
    ) -> None:
        if type(closed) is not c8.TimedDecisionWindowV1:
            raise C8CContractError("close returned unknown window type")
        closed.__post_init__()
        if closed.window_id != prior_active.window_id:
            raise C8CContractError("close returned a different window")
        if closed.opened_at != initial_opened_at:
            raise C8CContractError("close changed opened_at")
        if closed.deadline_at != initial_deadline:
            raise C8CContractError("close changed deadline")
        if _enum_text(closed.status, "closed.status") != "CLOSED_BY_TIMEOUT":
            raise C8CContractError("close did not return CLOSED_BY_TIMEOUT")
        state = self._runtime.state
        virtual_time_state = _read_required_attr(state, "virtual_time_state")
        current_tick = _read_required_attr(virtual_time_state, "now_tick")
        if current_tick != initial_tick:
            raise C8CContractError("close changed virtual time")
        if _read_required_attr(state, "pending_deadline") is not None:
            raise C8CContractError("close left a pending deadline")
        if _read_required_attr(state, "state_identity") == _read_required_attr(
            pre_close_state, "state_identity"
        ):
            raise C8CContractError("close did not advance outer state identity")
        if _read_required_attr(state, "event_chain_tip") == _read_required_attr(
            pre_close_state, "event_chain_tip"
        ):
            raise C8CContractError("close did not advance B event chain")
        runtime_events = _read_required_attr(state, "runtime_events")
        pre_events = _read_required_attr(pre_close_state, "runtime_events")
        if type(runtime_events) is not tuple or type(pre_events) is not tuple:
            raise C8CContractError("runtime events must be exact tuples")
        expected_parent_id = prior_active.parent_window_id
        expected_event_count = len(pre_events) + (
            2 if expected_parent_id is not None else 1
        )
        if len(runtime_events) != expected_event_count:
            raise C8CContractError("close appended an unexpected B event suffix")
        if runtime_events[: len(pre_events)] != pre_events:
            raise C8CContractError("close rewrote prior B runtime events")
        close_event = runtime_events[len(pre_events)]
        if type(close_event) is not rt.RuntimeEventV1:
            raise C8CContractError("close appended an unknown B event type")
        close_event.__post_init__()
        if _enum_text(close_event.event_kind, "close_event.event_kind") != (
            "WINDOW_CLOSED_BY_TIMEOUT"
        ):
            raise C8CContractError("close did not append timeout-close event")
        if close_event.window_id != window_authority_ref.window_id:
            raise C8CContractError("close event window mismatch")
        if close_event.execution_receipt_identity != execution_receipt.receipt_identity:
            raise C8CContractError("close event receipt mismatch")
        if close_event.previous_event_identity != pre_close_state.event_chain_tip:
            raise C8CContractError("close event previous identity mismatch")
        if expected_parent_id is None:
            if close_event.event_identity != state.event_chain_tip:
                raise C8CContractError("close event is not current B event-chain tip")
        else:
            resume_event = runtime_events[-1]
            if type(resume_event) is not rt.RuntimeEventV1:
                raise C8CContractError("parent resume appended unknown B event type")
            resume_event.__post_init__()
            if _enum_text(
                resume_event.event_kind, "resume_event.event_kind"
            ) != "PARENT_RESUMED_AFTER_CHILD":
                raise C8CContractError("close did not append parent-resume event")
            if resume_event.window_id != expected_parent_id:
                raise C8CContractError("parent-resume event window mismatch")
            if (
                _read_required_attr(resume_event, "related_window_id")
                != prior_active.window_id
            ):
                raise C8CContractError("parent-resume event child linkage mismatch")
            if resume_event.previous_event_identity != close_event.event_identity:
                raise C8CContractError("parent-resume event previous identity mismatch")
            if resume_event.event_identity != state.event_chain_tip:
                raise C8CContractError("parent-resume event is not B event-chain tip")
        window_stack = _read_required_attr(virtual_time_state, "window_stack")
        actual_active = _read_required_attr(window_stack, "active_window")
        if expected_parent_id is None:
            if actual_active is not None:
                raise C8CContractError("top-level timeout close left active window")
        elif actual_active is None or actual_active.window_id != expected_parent_id:
            raise C8CContractError("timeout close did not restore parent window")
        post_public = self._runtime.public_projection()
        if post_public.active_window_id != expected_parent_id:
            raise C8CContractError("public projection retained closed window")
        if post_public.event_chain_tip != state.event_chain_tip:
            raise C8CContractError("public projection B event tip mismatch")
        if post_public.projection_identity == pre_close_public_projection.projection_identity:
            raise C8CContractError("close did not advance public projection identity")
        if post_public.window_depth != pre_close_public_projection.window_depth - 1:
            raise C8CContractError("close did not decrement public window depth")

    def _gameplay_rollback_fingerprint_v1(self) -> _GameplayRollbackFingerprint:
        state = self._runtime.state
        virtual_time_state = _read_required_attr(state, "virtual_time_state")
        pending_deadline = (
            getattr(state, "pending_deadline")
            if hasattr(state, "pending_deadline")
            else _read_required_attr(virtual_time_state, "pending_deadline")
        )
        return _GameplayRollbackFingerprint(
            outer_state=state,
            public_projection=self._runtime.public_projection(),
            virtual_time_state=virtual_time_state,
            pending_deadline=pending_deadline,
            inner_adapter_identity=_read_required_attr(
                state, "inner_adapter_identity"
            ),
            inner_session_binding_identity=_read_required_attr(
                state, "inner_session_binding_identity"
            ),
            inner_public_state_identity=_read_required_attr(
                state, "inner_public_state_identity"
            ),
            inner_authoritative_state_identity=_read_required_attr(
                state, "inner_authoritative_state_identity"
            ),
            event_chain_tip=_read_required_attr(state, "event_chain_tip"),
            logical_obligations=_read_required_attr(state, "logical_obligations"),
        )

    def _ensure_runtime_unchanged_v1(
        self, before_state: Any, before_public_projection: Any, reason: str
    ) -> None:
        if self._runtime.state != before_state:
            self._poisoned = True
            raise _AbortResolution(ControllerResultKindV1.FAILED_POISONED, reason)
        if self._runtime.public_projection() != before_public_projection:
            self._poisoned = True
            raise _AbortResolution(ControllerResultKindV1.FAILED_POISONED, reason)

    def _ensure_not_poisoned_v1(self) -> None:
        if self._poisoned:
            raise _AbortResolution(
                ControllerResultKindV1.FAILED_POISONED,
                "CONTROLLER_POISONED_DURING_CALLBACK",
            )

    def _transaction_identity_v1(self, ref: Any, supplied_commitment: Any) -> str:
        supplied_identity = getattr(
            supplied_commitment, "commitment_identity", _ZERO_IDENTITY
        )
        if type(supplied_identity) is not str:
            supplied_identity = _ZERO_IDENTITY
        return _identity(
            {
                "schema": "sgs-c8-c-controller-transaction-v1",
                "contract_version": 1,
                "controller_contract_identity": C8_C_CONTRACT_IDENTITY,
                "controller_instance_identity": self._controller_instance_identity,
                "resolution_sequence": self._resolution_sequence,
                "previous_event_identity": self._event_chain_tip,
                "runtime_instance_identity": ref.runtime_instance_identity,
                "window_authority_ref_identity": ref.authority_ref_identity,
                "window_id": ref.window_id,
                "supplied_timeout_due_commitment_identity": supplied_identity,
            }
        )

    def _stage_event_v1(
        self,
        staged: list[ControllerEventV1],
        *,
        kind: ControllerEventKindV1,
        transaction_identity: str,
        window_authority_ref: Any,
        step_index: int,
        legal_set_identity: str = "",
        candidate: c8.PublicLegalActionCandidateV1 | None = None,
        issuance_evidence_identity: str = "",
        receipt_identity: str = "",
        outcome: str = "",
        reason: str = "",
        details: Mapping[str, Any],
    ) -> ControllerEventV1:
        previous = staged[-1].event_identity if staged else self._event_chain_tip
        values = {
            "schema": "sgs-c8-c-controller-event-v1",
            "contract_version": 1,
            "controller_id": C8_C_CONTROLLER_ID,
            "controller_contract_identity": C8_C_CONTRACT_IDENTITY,
            "controller_instance_identity": self._controller_instance_identity,
            "event_sequence": len(self._event_chain) + len(staged) + 1,
            "event_kind": kind.value,
            "previous_event_identity": previous,
            "transaction_identity": transaction_identity,
            "runtime_instance_identity": window_authority_ref.runtime_instance_identity,
            "window_authority_ref_identity": (
                window_authority_ref.authority_ref_identity
            ),
            "window_id": window_authority_ref.window_id,
            "step_index": step_index,
            "legal_set_identity": legal_set_identity,
            "candidate_identity": (
                candidate.candidate_identity if candidate is not None else ""
            ),
            "public_ordinal": (
                candidate.public_ordinal if candidate is not None else -1
            ),
            "action_family": (
                _enum_text(candidate.action_family, "candidate.action_family")
                if candidate is not None
                else ""
            ),
            "issuance_evidence_identity": issuance_evidence_identity,
            "receipt_identity": receipt_identity,
            "outcome": outcome,
            "reason": reason,
            "details_identity": _identity(
                {
                    "schema": "sgs-c8-c-controller-event-details-v1",
                    "contract_version": 1,
                    "event_kind": kind.value,
                    "details": details,
                }
            ),
        }
        values["event_identity"] = _identity(values)
        event = ControllerEventV1(**values)
        staged.append(event)
        return event

    def _commit_staged_events_v1(self, staged: Sequence[ControllerEventV1]) -> None:
        expected_sequence = len(self._event_chain) + 1
        expected_previous = self._event_chain_tip
        for event in staged:
            if event.event_sequence != expected_sequence:
                raise C8CContractError("staged event sequence mismatch")
            if event.previous_event_identity != expected_previous:
                raise C8CContractError("staged event chain mismatch")
            expected_sequence += 1
            expected_previous = event.event_identity
        self._event_chain.extend(staged)
        if staged:
            self._event_chain_tip = staged[-1].event_identity

    def _rollback_and_result_v1(
        self,
        *,
        snapshot: rt.TimedSessionTransactionSnapshotV1,
        rollback_fingerprint: _GameplayRollbackFingerprint,
        kind: ControllerResultKindV1,
        reason: str,
        transaction_identity: str,
        window_authority_ref: Any,
        commitment: Any,
        selected_actions: tuple[PublicSelectedActionV1, ...],
        attempted_legal_set_identities: tuple[str, ...],
        attempted_receipt_identities: tuple[str, ...],
        staged_events: tuple[ControllerEventV1, ...],
        event_chain_before: str,
    ) -> TimeoutControllerResultV1:
        rollback_reason = reason
        invalidation_ok = self._invalidate_unforwarded_issuances_v1(
            window_authority_ref
        )
        if not invalidation_ok:
            self._poisoned = True
            kind = ControllerResultKindV1.FAILED_POISONED
            rollback_reason = "UNFORWARDED_ISSUANCE_INVALIDATION_FAILED"
        try:
            self._runtime.rollback(snapshot)
            if snapshot.outer_state != rollback_fingerprint.outer_state:
                self._poisoned = True
                kind = ControllerResultKindV1.FAILED_POISONED
                rollback_reason = "ROLLBACK_SNAPSHOT_OUTER_STATE_DRIFT"
            elif self._runtime.state != rollback_fingerprint.outer_state:
                self._poisoned = True
                kind = ControllerResultKindV1.FAILED_POISONED
                rollback_reason = "ROLLBACK_COMPLETE_OUTER_STATE_MISMATCH"
            elif self._gameplay_rollback_fingerprint_v1() != rollback_fingerprint:
                self._poisoned = True
                kind = ControllerResultKindV1.FAILED_POISONED
                rollback_reason = "ROLLBACK_GAMEPLAY_FINGERPRINT_MISMATCH"
        except Exception:
            self._poisoned = True
            kind = ControllerResultKindV1.FAILED_POISONED
            rollback_reason = "ROLLBACK_RECOVERY_FAILED"

        discarded_summary = _identity(
            {
                "schema": "sgs-c8-c-discarded-staged-events-v1",
                "contract_version": 1,
                "event_identities": [event.event_identity for event in staged_events],
            }
        )
        rollback_events: list[ControllerEventV1] = []
        self._stage_event_v1(
            rollback_events,
            kind=ControllerEventKindV1.ROLLED_BACK,
            transaction_identity=transaction_identity,
            window_authority_ref=window_authority_ref,
            step_index=len(selected_actions),
            outcome=kind.value,
            reason=rollback_reason,
            details={
                "discarded_staged_event_summary_identity": discarded_summary,
                "legal_set_security_ledger_identity": _identity(
                    sorted(self._consumed_legal_set_identities)
                ),
                "issuance_security_ledger_identity": _identity(
                    sorted(self._consumed_issuance_identities)
                ),
                "authorization_security_ledger_identity": _identity(
                    sorted(self._consumed_authorization_evidence_identities)
                ),
                "receipt_security_ledger_identity": _identity(
                    sorted(self._consumed_receipt_identities)
                ),
                "invalidation_security_ledger_identity": _identity(
                    sorted(self._invalidation_evidence_identities)
                ),
                "controller_poisoned": self._poisoned,
            },
        )
        self._commit_staged_events_v1(rollback_events)
        # Rolled-back actions are not reported as committed selected actions.
        return self._build_result_v1(
            kind=kind,
            reason=rollback_reason,
            transaction_identity=transaction_identity,
            window_authority_ref=window_authority_ref,
            commitment=commitment,
            selected_actions=selected_actions,
            attempted_legal_set_identities=attempted_legal_set_identities,
            attempted_receipt_identities=attempted_receipt_identities,
            transaction_events=tuple(rollback_events),
            event_chain_before=event_chain_before,
        )

    @staticmethod
    def _ownership_status_v1(
        ownership: rt.PendingIssuanceCapabilityOwnershipV1,
    ) -> str:
        status = ownership.status
        if type(status) is not rt.PendingIssuanceCapabilityStatusV1:
            raise C8CContractError("unknown pending issuance ownership status")
        return status.value

    def _pending_capability_ownership_v1(
        self, capability: rt.PendingTimeoutIssuanceCapabilityV1
    ) -> rt.PendingIssuanceCapabilityOwnershipV1:
        ownership = self._runtime.current_pending_issuance_capability_ownership_v1(
            capability
        )
        if type(ownership) is not rt.PendingIssuanceCapabilityOwnershipV1:
            raise C8CContractError("B returned unknown pending capability ownership")
        ownership.__post_init__()
        expected = {
            "runtime_contract_identity": C8_B_REQUIRED_RUNTIME_CONTRACT_IDENTITY,
            "runtime_instance_identity": capability.runtime_instance_identity,
            "capability_identity": capability.capability_identity,
            "controller_identity": capability.controller_identity,
            "adapter_identity": capability.adapter_identity,
            "window_authority_ref_identity": (
                capability.window_authority_ref_identity
            ),
            "timeout_due_commitment_identity": (
                capability.timeout_due_commitment_identity
            ),
            "external_capability_identity": capability.external_capability_identity,
        }
        for field_name, expected_value in expected.items():
            if getattr(ownership, field_name) != expected_value:
                raise C8CContractError(
                    f"pending capability ownership {field_name} mismatch"
                )
        return ownership

    def _drop_consumed_pending_issuance_v1(self, pending_key: str) -> None:
        self._unforwarded_issuances.pop(pending_key, None)
        self._unforwarded_issuance_contexts.pop(pending_key, None)
        self._pending_b_capabilities.pop(pending_key, None)

    def _abort_registered_pending_issuance_v1(
        self,
        window_authority_ref: Any,
        commitment: Any,
        pending_key: str,
        issuance: SignedActionIssuanceEvidenceV1,
        capability: rt.PendingTimeoutIssuanceCapabilityV1,
    ) -> bool:
        """Guarded external abort followed by B's one-way capability abort."""

        try:
            ownership_before = self._pending_capability_ownership_v1(capability)
            if self._ownership_status_v1(ownership_before) != (
                "CONTROLLER_OWNED_PENDING"
            ):
                return False
            bundle, _ = self._invoke_adapter_callback_guarded_v1(
                window_authority_ref,
                commitment,
                lambda: self._adapter.abort_pending_issuance_v1(
                    issuance.external_capability
                ),
            )
            self._require_adapter_lineage_stable_v1(
                bundle.before,
                bundle.after,
                allow_legal_projection_change=False,
                allow_issuance_ledger_change=True,
            )
            evidence = bundle.callback_result
            if type(evidence) is not UnforwardedIssuanceInvalidationEvidenceV1:
                return False
            evidence.__post_init__()
            expected = {
                "issuance_identity": issuance.issuance_identity,
                "authorization_evidence_identity": (
                    issuance.authorization_evidence_identity
                ),
                "runtime_instance_identity": issuance.runtime_instance_identity,
                "window_authority_ref_identity": (
                    issuance.window_authority_ref_identity
                ),
                "session_identity": issuance.session_identity,
                "controller_identity": issuance.controller_identity,
                "adapter_identity": issuance.adapter_identity,
                "security_ledger_before_identity": (
                    bundle.before.issuance_security_ledger_identity
                ),
                "security_ledger_after_identity": (
                    bundle.after.issuance_security_ledger_identity
                ),
                "invalidated": True,
            }
            for field_name, expected_value in expected.items():
                if getattr(evidence, field_name) != expected_value:
                    return False
            if evidence.invalidation_identity in self._invalidation_evidence_identities:
                return False
            aborted = self._runtime.abort_pending_timeout_issuance_capability_v1(
                capability
            )
            if type(aborted) is not rt.PendingIssuanceCapabilityOwnershipV1:
                return False
            aborted.__post_init__()
            if self._ownership_status_v1(aborted) != "CONTROLLER_ABORTED":
                return False
            if aborted.capability_identity != capability.capability_identity:
                return False
            if aborted.committed_receipt_identity is not None:
                return False
            self._invalidation_evidence_identities.add(
                evidence.invalidation_identity
            )
            self._drop_consumed_pending_issuance_v1(pending_key)
            return True
        except Exception:
            return False

    def _invalidate_unforwarded_issuances_v1(
        self, window_authority_ref: Any
    ) -> bool:
        """Resolve every external/B capability according to B's ownership view."""

        for pending_key, issuance in tuple(self._unforwarded_issuances.items()):
            try:
                capability = self._pending_b_capabilities.get(pending_key)
                if capability is None:
                    context = self._unforwarded_issuance_contexts[pending_key]
                    commitment = self._runtime.current_timeout_due_commitment_v1(
                        window_authority_ref
                    )
                    if not self._recover_failed_issuance_attempt_v1(
                        window_authority_ref=window_authority_ref,
                        commitment=commitment,
                        transaction_identity=context.transaction_identity,
                        envelope=context.envelope,
                        candidate=context.candidate,
                        selected_binding=context.timeout_auth_binding,
                        security_ledger_before=(
                            context.security_ledger_before_identity
                        ),
                    ):
                        return False
                    self._drop_consumed_pending_issuance_v1(pending_key)
                    continue
                ownership = self._pending_capability_ownership_v1(capability)
                status = self._ownership_status_v1(ownership)
                if status == "CONTROLLER_OWNED_PENDING":
                    commitment = self._runtime.current_timeout_due_commitment_v1(
                        window_authority_ref
                    )
                    if not self._abort_registered_pending_issuance_v1(
                        window_authority_ref,
                        commitment,
                        pending_key,
                        issuance,
                        capability,
                    ):
                        return False
                elif status in {
                    "AUTH_EVIDENCE_CONSUMED",
                    "RECEIPT_COMMITTED_CONSUMED",
                    "CONTROLLER_ABORTED",
                }:
                    self._drop_consumed_pending_issuance_v1(pending_key)
                else:
                    return False
            except Exception:
                return False
        return (
            not self._unforwarded_issuances
            and not self._pending_b_capabilities
        )

    def _build_result_v1(
        self,
        *,
        kind: ControllerResultKindV1,
        reason: str,
        transaction_identity: str,
        window_authority_ref: Any,
        commitment: Any,
        selected_actions: tuple[PublicSelectedActionV1, ...],
        attempted_legal_set_identities: tuple[str, ...],
        attempted_receipt_identities: tuple[str, ...],
        transaction_events: tuple[ControllerEventV1, ...],
        event_chain_before: str,
        event_chain_after_identity: str | None = None,
    ) -> TimeoutControllerResultV1:
        legal_set_identities = attempted_legal_set_identities
        receipt_identities = attempted_receipt_identities
        event_identities = tuple(event.event_identity for event in transaction_events)
        runtime_contract_identity = getattr(
            commitment,
            "runtime_contract_identity",
            C8_B_REQUIRED_RUNTIME_CONTRACT_IDENTITY,
        )
        if (
            type(runtime_contract_identity) is not str
            or len(runtime_contract_identity) != 64
            or any(character not in _HEX for character in runtime_contract_identity)
        ):
            runtime_contract_identity = C8_B_REQUIRED_RUNTIME_CONTRACT_IDENTITY
        resolution_tick = getattr(commitment, "now_tick", None)
        if type(resolution_tick) is not int or resolution_tick < 0:
            resolution_tick = None
        deadline_at = getattr(commitment, "deadline_at", None)
        if type(deadline_at) is not int or deadline_at < 0:
            deadline_at = None
        values: dict[str, Any] = {
            "schema": "sgs-c8-c-timeout-controller-result-v1",
            "contract_version": 1,
            "controller_id": C8_C_CONTROLLER_ID,
            "controller_contract_identity": C8_C_CONTRACT_IDENTITY,
            "controller_instance_identity": self._controller_instance_identity,
            "result_kind": kind.value,
            "reason": _require_exact_str(reason, "reason"),
            "transaction_identity": transaction_identity,
            "runtime_contract_identity": runtime_contract_identity,
            "runtime_instance_identity": window_authority_ref.runtime_instance_identity,
            "window_authority_ref_identity": (
                window_authority_ref.authority_ref_identity
            ),
            "window_id": window_authority_ref.window_id,
            "resolution_tick": resolution_tick,
            "deadline_at": deadline_at,
            "step_count": len(legal_set_identities),
            "selected_actions": selected_actions,
            "legal_set_identities": legal_set_identities,
            "receipt_identities": receipt_identities,
            "event_identities": event_identities,
            "event_chain_before_identity": event_chain_before,
            "event_chain_after_identity": (
                self._event_chain_tip
                if event_chain_after_identity is None
                else event_chain_after_identity
            ),
            "event_chain_summary_identity": _identity(
                {
                    "schema": "sgs-c8-c-event-chain-summary-v1",
                    "contract_version": 1,
                    "event_identities": list(event_identities),
                }
            ),
        }
        values["result_identity"] = _identity(
            {
                **values,
                "selected_actions": [
                    selected.to_public_dict_v1() for selected in selected_actions
                ],
                "legal_set_identities": list(legal_set_identities),
                "receipt_identities": list(receipt_identities),
                "event_identities": list(event_identities),
            }
        )
        return TimeoutControllerResultV1(**values)


__all__ = [
    "AdapterPublicLegalActionsSnapshotV1",
    "C8_A_REQUIRED_CONTRACT_IDENTITY",
    "C8_B_REQUIRED_CURRENT_CONTRACT_LATCH_IDENTITY",
    "C8_B_REQUIRED_RUNTIME_CONTRACT_IDENTITY",
    "C8_C_CONTRACT_IDENTITY",
    "C8_C_CONTROLLER_ID",
    "C8_C_LIVE_COMMITMENT_PROBE_ACTION_REFERENCE",
    "C8CContractError",
    "C8CPoisonedError",
    "C8CReentrancyError",
    "ControllerEventKindV1",
    "ControllerEventV1",
    "ControllerResultKindV1",
    "FreshPublicLegalActionsEnvelopeV1",
    "FailedIssuanceRecoveryEvidenceV1",
    "PublicLegalActionsIssuanceAdapterV1",
    "PublicSelectedActionV1",
    "ReceiptLineageCompletionEvidenceV1",
    "SignedActionIssuanceEvidenceV1",
    "TimeoutControllerResultV1",
    "TimeoutResolverControllerIntegrationV1",
    "UnforwardedIssuanceInvalidationEvidenceV1",
    "build_adapter_public_legal_actions_snapshot_v1",
    "build_fresh_public_legal_actions_envelope_v1",
    "build_failed_issuance_recovery_evidence_v1",
    "build_receipt_lineage_completion_evidence_v1",
    "build_signed_action_issuance_evidence_v1",
    "build_unforwarded_issuance_invalidation_evidence_v1",
    "canonical_public_ordering_identity_v1",
    "signed_action_id_commitment_v1",
    "timeout_authentication_bindings_identity_v1",
    "timeout_issuance_request_binding_v1",
]
