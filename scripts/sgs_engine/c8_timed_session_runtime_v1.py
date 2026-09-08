# -*- coding: utf-8 -*-
"""C8-B generic deterministic timed-session runtime wrapper.

This module composes the immutable C8-A contract.  It owns only outer virtual
time, timed-window lifecycle, input/event chains, and transaction metadata.
It deliberately does not choose timeout actions, call ``legal_actions`` or
``step`` directly, read wall time, use RNG, or modify frozen shared core.
On-time signed action IDs may be forwarded transparently to the bound adapter;
the inner session remains the sole gameplay mutation authority.  At the C8-B
boundary, C8-A candidate.action_id is only a fresh public legal-set action
reference, not proof that a post-resolver signature was created.  A future C8-C
issuer must freshly confirm that public candidate and authorize the exact
timeout forwarding binding before this wrapper will call the inner adapter.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import hashlib
import json
import re
from types import MappingProxyType
from typing import Any, Callable, Protocol, Sequence

from .c8_virtual_time_contract_v1 import (
    BRIDGE_V1_FROZEN_BASELINE_IDENTITY,
    C8_A_CONTRACT_IDENTITY_V1,
    CLOCK_DOMAIN_ID,
    CLOCK_DOMAIN_V1,
    ENGINEERING_TEST_PROFILE_V1,
    SAME_TICK_FALLBACK_CHAIN_CONTRACT_V1,
    TIMEOUT_FALLBACK_REGISTRY_V1,
    C8VirtualTimeContractError,
    DeadlinePrecedenceV1,
    DerivedDeadlineReachedV1,
    TimedDecisionWindowV1,
    TimedWindowKindV1,
    TimedWindowStatusV1,
    VirtualTimeAdvanceInputV1,
    VirtualTimeStateV1,
    VirtualTimeTransactionSnapshotV1,
    advance_virtual_time_v1,
    close_decision_window_v1,
    deadline_precedence_v1,
    open_decision_window_v1,
)


class C8TimedSessionRuntimeError(ValueError):
    """C8-B runtime authority, transition, or schema validation failed closed."""


C8_B_MILESTONE = "C8-B_TIMED_SESSION_RUNTIME_WRAPPER_V1"
C8_B_RUNTIME_ID = "c8-timed-session-runtime-wrapper-v1"
C8_B_RUNTIME_VERSION = 1
C8_B_PAUSE_AUTHORITY = "CHILD_WINDOW_ONLY"
C8_B_CANCEL_RULE = "ROLLBACK_TO_PRE_OPEN_OUTER_TRANSACTION_SNAPSHOT_ONLY"
C8_B_TIMEOUT_INTEGRATION = (
    "TIMEOUT_DUE_AUTHENTICATED_SIGNED_ACTION_RECEIPT_AND_SAME_TICK_PROGRESS"
)

CONTRACT_LATCH_SCHEMA = "sgs-c8-b-current-contract-latch-v1"
WINDOW_AUTHORITY_REF_SCHEMA = "sgs-c8-b-window-authority-ref-v1"
INPUT_RECORD_SCHEMA = "sgs-c8-b-accepted-time-input-v1"
LOGICAL_PROGRESS_SCHEMA = "sgs-c8-b-logical-obligation-progress-v1"
PENDING_DEADLINE_SCHEMA = "sgs-c8-b-pending-derived-deadline-v1"
RUNTIME_EVENT_SCHEMA = "sgs-c8-b-runtime-event-v1"
OUTER_STATE_SCHEMA = "sgs-c8-b-timed-session-outer-state-v1"
PUBLIC_PROJECTION_SCHEMA = "sgs-c8-b-timed-session-public-projection-v1"
TRANSACTION_SNAPSHOT_SCHEMA = "sgs-c8-b-outer-transaction-snapshot-v1"
CANCELLATION_RECEIPT_SCHEMA = "sgs-c8-b-rollback-cancellation-receipt-v1"
INPUT_AUTH_BINDING_SCHEMA = "sgs-c8-b-input-authentication-binding-v1"
INPUT_CHAIN_LINK_SCHEMA = "sgs-c8-b-input-chain-link-v1"
TIMEOUT_DUE_COMMITMENT_SCHEMA = "sgs-c8-b-timeout-due-commitment-v1"
TIMEOUT_ACTION_AUTH_BINDING_SCHEMA = (
    "sgs-c8-b-timeout-signed-action-authorization-binding-v1"
)
TIMEOUT_ACTION_ID_COMMITMENT_SCHEMA = (
    "sgs-c8-b-timeout-signed-action-id-commitment-v1"
)
TIMEOUT_EXECUTION_RECEIPT_SCHEMA = (
    "sgs-c8-b-timeout-signed-action-execution-receipt-v1"
)
CONTROLLER_CALLBACK_LEASE_SCHEMA = (
    "sgs-c8-b-controller-callback-lease-v1"
)
CONTROLLER_CALLBACK_GUARD_SCHEMA = (
    "sgs-c8-b-controller-callback-guard-v1"
)
CONTROLLER_CALLBACK_GUARD_RESULT_SCHEMA = (
    "sgs-c8-b-controller-callback-guard-result-v1"
)
CONTROLLER_CALLBACK_SECURITY_AUDIT_SCHEMA = (
    "sgs-c8-b-controller-callback-security-audit-v1"
)
PENDING_ISSUANCE_CAPABILITY_SCHEMA = (
    "sgs-c8-b-pending-timeout-issuance-capability-v1"
)
PENDING_ISSUANCE_OWNERSHIP_SCHEMA = (
    "sgs-c8-b-pending-timeout-issuance-ownership-v1"
)
OPERATION_ATTEMPT_CHAIN_SCHEMA = (
    "sgs-c8-b-nonrollback-operation-attempt-chain-v1"
)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_TEXT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")
_TICK_MAX = (1 << 63) - 1


def _exact_dict(value: object, label: str) -> dict[str, Any]:
    if type(value) is not dict:
        raise C8TimedSessionRuntimeError(f"{label}必须是精确JSON object")
    if any(type(key) is not str for key in value):
        raise C8TimedSessionRuntimeError(f"{label}字段名必须是精确字符串")
    return value


def _exact_fields(value: dict[str, Any], expected: frozenset[str], label: str) -> None:
    actual = frozenset(value)
    if actual != expected:
        raise C8TimedSessionRuntimeError(
            f"{label}字段必须精确匹配schema；"
            f"missing={sorted(expected - actual)}, extra={sorted(actual - expected)}"
        )


def _exact_list(value: object, label: str) -> list[object]:
    if type(value) is not list:
        raise C8TimedSessionRuntimeError(f"{label}必须是精确JSON array")
    return value


def _exact_text(value: object, label: str) -> str:
    if type(value) is not str or not value or value.strip() != value:
        raise C8TimedSessionRuntimeError(f"{label}必须是无首尾空白的精确非空字符串")
    return value


def _exact_text_id(value: object, label: str) -> str:
    text = _exact_text(value, label)
    if _TEXT_ID_RE.fullmatch(text) is None:
        raise C8TimedSessionRuntimeError(f"{label}格式不正确")
    return text


def _exact_optional_text(value: object, label: str) -> str | None:
    return None if value is None else _exact_text(value, label)


def _exact_int(
    value: object,
    label: str,
    *,
    minimum: int = 0,
    maximum: int = _TICK_MAX,
) -> int:
    if type(value) is not int or value < minimum or value > maximum:
        raise C8TimedSessionRuntimeError(
            f"{label}必须是[{minimum}, {maximum}]内的精确整数"
        )
    return value


def _exact_optional_int(value: object, label: str) -> int | None:
    return None if value is None else _exact_int(value, label)


def _exact_bool(value: object, label: str) -> bool:
    if type(value) is not bool:
        raise C8TimedSessionRuntimeError(f"{label}必须是精确boolean")
    return value


def _exact_sha256(value: object, label: str) -> str:
    text = _exact_text(value, label)
    if _SHA256_RE.fullmatch(text) is None:
        raise C8TimedSessionRuntimeError(f"{label}必须是64位小写SHA-256")
    return text


def _exact_optional_sha256(value: object, label: str) -> str | None:
    return None if value is None else _exact_sha256(value, label)


def _exact_enum(value: object, enum_type: type[Enum], label: str) -> Enum:
    text = _exact_text(value, label)
    try:
        return enum_type(text)
    except ValueError as exc:
        raise C8TimedSessionRuntimeError(f"{label}不是受支持的枚举值：{text!r}") from exc


def _canonical_json(value: object) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _assert_identity(actual: object, material: object, label: str) -> str:
    identity = _exact_sha256(actual, label)
    expected = _canonical_sha256(material)
    if identity != expected:
        raise C8TimedSessionRuntimeError(
            f"{label}与canonical material不一致；expected={expected}, actual={identity}"
        )
    return identity


def _is_prefix(prefix: tuple[object, ...], value: tuple[object, ...]) -> bool:
    return len(prefix) <= len(value) and value[: len(prefix)] == prefix


def _signed_action_id_commitment_v1(signed_action_id: object) -> str:
    action_id = _exact_text(signed_action_id, "signed_action_id")
    return _canonical_sha256(
        {
            "schema": TIMEOUT_ACTION_ID_COMMITMENT_SCHEMA,
            "contract_version": 1,
            "signed_action_id": action_id,
        }
    )


C8_B_RUNTIME_DESCRIPTOR_V1 = MappingProxyType(
    {
        "milestone": C8_B_MILESTONE,
        "runtime_id": C8_B_RUNTIME_ID,
        "runtime_version": C8_B_RUNTIME_VERSION,
        "c8_a_contract_identity": C8_A_CONTRACT_IDENTITY_V1,
        "clock_domain_identity": CLOCK_DOMAIN_V1.clock_domain_identity,
        "duration_profile_identity": ENGINEERING_TEST_PROFILE_V1.profile_identity,
        "fallback_registry_identity": TIMEOUT_FALLBACK_REGISTRY_V1.registry_identity,
        "same_tick_chain_identity": SAME_TICK_FALLBACK_CHAIN_CONTRACT_V1.contract_identity,
        "bridge_historical_identity": BRIDGE_V1_FROZEN_BASELINE_IDENTITY,
        "clock_authority": "WRAPPER_OWNS_ONLY_LIVE_VIRTUAL_TIME_STATE",
        "inner_authority": "FROZEN_INNER_SESSION_RETAINS_GAMEPLAY_AUTHORITY",
        "normal_action_passthrough": (
            "ON_TIME_SIGNED_ACTION_ID_TO_BOUND_INNER_ADAPTER_NO_ACTION_SELECTION"
        ),
        "inner_passthrough_lineage": (
            "SEPARATE_OUTER_INNER_SIGNED_ACTION_FORWARDED_COMMITMENT_EVENT"
        ),
        "adapter_callback_contract": (
            "DETERMINISTIC_SIDE_EFFECT_SCOPED_NON_REENTRANT_SERIAL_DRIVER_ONLY"
        ),
        "trusted_controller_callback_guard": (
            "RUNTIME_ISSUED_LIVE_ONE_SHOT_LEASE_BOUND_TO_TIMEOUT_LINEAGE"
        ),
        "controller_callback_operation_attempt_evidence": (
            "MONOTONIC_HASH_CHAIN_OUTSIDE_GAMEPLAY_ROLLBACK_DOMAIN"
        ),
        "controller_callback_read_only_surface": (
            "CACHED_STATE_WINDOW_REF_ELIGIBILITY_PUBLIC_AND_SECURITY_AUDIT_PROJECTIONS"
        ),
        "logical_input_authentication": (
            "EXTERNAL_ONE_SHOT_TIME_AND_TIMEOUT_ACTION_AUTHORITY_SURVIVES_OUTER_ROLLBACK"
        ),
        "authenticator_rollback_guard": (
            "ANTI_REPLAY_LEDGER_IDENTITY_MUST_NOT_CHANGE_DURING_INNER_RESTORE"
        ),
        "transactional_outer_snapshot": (
            "CLOCK_INPUT_CHAIN_WINDOW_STACK_PAUSE_DEADLINE_EVENT_AND_INNER_TOKEN"
        ),
        "nonrollback_control_plane": (
            "EXTERNAL_AUTH_LEDGER_AND_LIVE_SNAPSHOT_TIMEOUT_COMMITMENT_RECEIPT_REGISTRIES"
        ),
        "pause_authority": C8_B_PAUSE_AUTHORITY,
        "nested_open_event_order": "PARENT_SUSPENDED_BY_CHILD_THEN_WINDOW_OPENED",
        "nested_close_event_order": "WINDOW_CLOSED_THEN_PARENT_RESUMED_AFTER_CHILD",
        "cancel_rule": C8_B_CANCEL_RULE,
        "timeout_integration": C8_B_TIMEOUT_INTEGRATION,
        "timeout_action_passthrough": (
            "TIMEOUT_DUE_FRESHLY_AUTHORIZED_SIGNED_ACTION_ID_NO_SELECTION_OR_RESOLVER"
        ),
        "timeout_receipt": (
            "STRICT_PRE_POST_IDENTITY_RECEIPT_BOUND_TO_OUTER_EVENT_AND_ONE_SHOT_CONSUMPTION"
        ),
        "pending_issuance_capability_ownership": (
            "CONTROLLER_OWNED_UNTIL_AUTH_CONSUMED_OR_TYPED_RECEIPT_COMMITTED_"
            "WITH_EXPLICIT_ONE_SHOT_ABORT"
        ),
        "timeout_same_tick_progress": (
            "RECEIPT_BOUND_NO_TIME_OR_DEADLINE_REFRESH_ONE_RECEIPT_PER_LOGICAL_STEP"
        ),
        "exact_boundary": "CURRENT_TIME_LT_DEADLINE_ONLY",
        "outer_events": "SEPARATE_FROM_INNER_GAMEPLAY_EVENT_LOG",
        "wall_clock": "FORBIDDEN",
        "rng": "FORBIDDEN",
        "timeout_policy_controller": "NOT_INCLUDED_IN_C8_B",
        "replay_schema": "NOT_INCLUDED_IN_C8_B",
        "outer_state_rehydrate_scope": "STRUCTURAL_SNAPSHOT_ONLY_NOT_REPLAY_AUTHORITY",
    }
)
C8_B_RUNTIME_CONTRACT_IDENTITY_V1 = _canonical_sha256(
    dict(C8_B_RUNTIME_DESCRIPTOR_V1)
)


def _timeout_receipt_chain_genesis(runtime_instance_identity: str) -> str:
    return _canonical_sha256(
        {
            "runtime_contract_identity": C8_B_RUNTIME_CONTRACT_IDENTITY_V1,
            "runtime_instance_identity": _exact_sha256(
                runtime_instance_identity, "runtime_instance_identity"
            ),
            "chain": "TIMEOUT_EXECUTION_RECEIPT_GENESIS",
        }
    )


def _operation_attempt_chain_genesis(runtime_instance_identity: str) -> str:
    return _canonical_sha256(
        {
            "schema": OPERATION_ATTEMPT_CHAIN_SCHEMA,
            "contract_version": 1,
            "runtime_contract_identity": C8_B_RUNTIME_CONTRACT_IDENTITY_V1,
            "runtime_instance_identity": _exact_sha256(
                runtime_instance_identity, "runtime_instance_identity"
            ),
            "epoch": 0,
        }
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class C8BCurrentContractLatchV1:
    schema: str
    contract_version: int
    runtime_contract_identity: str
    c8_a_contract_identity: str
    clock_domain_identity: str
    duration_profile_identity: str
    fallback_registry_identity: str
    same_tick_chain_identity: str
    bridge_historical_identity: str
    latch_identity: str

    def __post_init__(self) -> None:
        if self.schema != CONTRACT_LATCH_SCHEMA or self.contract_version != 1:
            raise C8TimedSessionRuntimeError("C8-B current-contract latch schema/version不匹配")
        expected = {
            "runtime_contract_identity": C8_B_RUNTIME_CONTRACT_IDENTITY_V1,
            "c8_a_contract_identity": C8_A_CONTRACT_IDENTITY_V1,
            "clock_domain_identity": CLOCK_DOMAIN_V1.clock_domain_identity,
            "duration_profile_identity": ENGINEERING_TEST_PROFILE_V1.profile_identity,
            "fallback_registry_identity": TIMEOUT_FALLBACK_REGISTRY_V1.registry_identity,
            "same_tick_chain_identity": SAME_TICK_FALLBACK_CHAIN_CONTRACT_V1.contract_identity,
            "bridge_historical_identity": BRIDGE_V1_FROZEN_BASELINE_IDENTITY,
        }
        for label, expected_value in expected.items():
            _exact_sha256(getattr(self, label), label)
            if getattr(self, label) != expected_value:
                raise C8TimedSessionRuntimeError(f"current-contract latch {label} drift")
        _assert_identity(self.latch_identity, self._identity_material(), "latch_identity")

    def _identity_material(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "contract_version": self.contract_version,
            "runtime_contract_identity": self.runtime_contract_identity,
            "c8_a_contract_identity": self.c8_a_contract_identity,
            "clock_domain_identity": self.clock_domain_identity,
            "duration_profile_identity": self.duration_profile_identity,
            "fallback_registry_identity": self.fallback_registry_identity,
            "same_tick_chain_identity": self.same_tick_chain_identity,
            "bridge_historical_identity": self.bridge_historical_identity,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._identity_material(), "latch_identity": self.latch_identity}

    @classmethod
    def canonical(cls) -> "C8BCurrentContractLatchV1":
        material = {
            "schema": CONTRACT_LATCH_SCHEMA,
            "contract_version": 1,
            "runtime_contract_identity": C8_B_RUNTIME_CONTRACT_IDENTITY_V1,
            "c8_a_contract_identity": C8_A_CONTRACT_IDENTITY_V1,
            "clock_domain_identity": CLOCK_DOMAIN_V1.clock_domain_identity,
            "duration_profile_identity": ENGINEERING_TEST_PROFILE_V1.profile_identity,
            "fallback_registry_identity": TIMEOUT_FALLBACK_REGISTRY_V1.registry_identity,
            "same_tick_chain_identity": SAME_TICK_FALLBACK_CHAIN_CONTRACT_V1.contract_identity,
            "bridge_historical_identity": BRIDGE_V1_FROZEN_BASELINE_IDENTITY,
        }
        return cls(**material, latch_identity=_canonical_sha256(material))

    @classmethod
    def from_dict(cls, value: object) -> "C8BCurrentContractLatchV1":
        data = _exact_dict(value, "C8BCurrentContractLatchV1")
        fields = frozenset(
            {
                "schema",
                "contract_version",
                "runtime_contract_identity",
                "c8_a_contract_identity",
                "clock_domain_identity",
                "duration_profile_identity",
                "fallback_registry_identity",
                "same_tick_chain_identity",
                "bridge_historical_identity",
                "latch_identity",
            }
        )
        _exact_fields(data, fields, "C8BCurrentContractLatchV1")
        return cls(
            schema=_exact_text(data["schema"], "latch.schema"),
            contract_version=_exact_int(data["contract_version"], "contract_version"),
            runtime_contract_identity=_exact_sha256(
                data["runtime_contract_identity"], "runtime_contract_identity"
            ),
            c8_a_contract_identity=_exact_sha256(
                data["c8_a_contract_identity"], "c8_a_contract_identity"
            ),
            clock_domain_identity=_exact_sha256(
                data["clock_domain_identity"], "clock_domain_identity"
            ),
            duration_profile_identity=_exact_sha256(
                data["duration_profile_identity"], "duration_profile_identity"
            ),
            fallback_registry_identity=_exact_sha256(
                data["fallback_registry_identity"], "fallback_registry_identity"
            ),
            same_tick_chain_identity=_exact_sha256(
                data["same_tick_chain_identity"], "same_tick_chain_identity"
            ),
            bridge_historical_identity=_exact_sha256(
                data["bridge_historical_identity"], "bridge_historical_identity"
            ),
            latch_identity=_exact_sha256(data["latch_identity"], "latch_identity"),
        )


C8_B_CURRENT_CONTRACT_LATCH_V1 = C8BCurrentContractLatchV1.canonical()


class RuntimeEventKindV1(str, Enum):
    WINDOW_OPENED = "WINDOW_OPENED"
    PARENT_SUSPENDED_BY_CHILD = "PARENT_SUSPENDED_BY_CHILD"
    TIME_INPUT_ACCEPTED = "TIME_INPUT_ACCEPTED"
    DEADLINE_DERIVED = "DEADLINE_DERIVED"
    MULTI_STEP_CONTINUED = "MULTI_STEP_CONTINUED"
    INNER_SIGNED_ACTION_FORWARDED = "INNER_SIGNED_ACTION_FORWARDED"
    TIMEOUT_SIGNED_ACTION_FORWARDED = "TIMEOUT_SIGNED_ACTION_FORWARDED"
    TIMEOUT_MULTI_STEP_CONTINUED = "TIMEOUT_MULTI_STEP_CONTINUED"
    WINDOW_CLOSED_BY_ACTION = "WINDOW_CLOSED_BY_ACTION"
    WINDOW_CLOSED_BY_TIMEOUT = "WINDOW_CLOSED_BY_TIMEOUT"
    PARENT_RESUMED_AFTER_CHILD = "PARENT_RESUMED_AFTER_CHILD"


@dataclass(frozen=True, slots=True, kw_only=True)
class WindowAuthorityRefV1:
    schema: str
    contract_version: int
    runtime_instance_identity: str
    window_id: str
    parent_window_id: str | None
    actor_id: str
    window_kind: TimedWindowKindV1
    decision_identity: str
    obligation_identity: str
    window_binding_identity: str
    authority_ref_identity: str

    def __post_init__(self) -> None:
        if self.schema != WINDOW_AUTHORITY_REF_SCHEMA or self.contract_version != 1:
            raise C8TimedSessionRuntimeError("window authority ref schema/version不匹配")
        _exact_sha256(self.runtime_instance_identity, "runtime_instance_identity")
        _exact_text(self.window_id, "window_id")
        _exact_optional_text(self.parent_window_id, "parent_window_id")
        _exact_text_id(self.actor_id, "actor_id")
        if type(self.window_kind) is not TimedWindowKindV1:
            raise C8TimedSessionRuntimeError("window_kind类型不正确")
        _exact_sha256(self.decision_identity, "decision_identity")
        _exact_sha256(self.obligation_identity, "obligation_identity")
        _exact_sha256(self.window_binding_identity, "window_binding_identity")
        _assert_identity(
            self.authority_ref_identity,
            self._identity_material(),
            "authority_ref_identity",
        )

    def _identity_material(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "contract_version": self.contract_version,
            "runtime_instance_identity": self.runtime_instance_identity,
            "window_id": self.window_id,
            "parent_window_id": self.parent_window_id,
            "actor_id": self.actor_id,
            "window_kind": self.window_kind.value,
            "decision_identity": self.decision_identity,
            "obligation_identity": self.obligation_identity,
            "window_binding_identity": self.window_binding_identity,
        }

    def to_dict(self) -> dict[str, object]:
        return {
            **self._identity_material(),
            "authority_ref_identity": self.authority_ref_identity,
        }

    @classmethod
    def issue(
        cls,
        *,
        runtime_instance_identity: str,
        window_id: str,
        parent_window_id: str | None,
        actor_id: str,
        window_kind: TimedWindowKindV1,
        decision_identity: str,
        obligation_identity: str,
        window_binding_identity: str,
    ) -> "WindowAuthorityRefV1":
        if type(window_kind) is not TimedWindowKindV1:
            raise C8TimedSessionRuntimeError("window_kind类型不正确")
        material = {
            "schema": WINDOW_AUTHORITY_REF_SCHEMA,
            "contract_version": 1,
            "runtime_instance_identity": runtime_instance_identity,
            "window_id": window_id,
            "parent_window_id": parent_window_id,
            "actor_id": actor_id,
            "window_kind": window_kind.value,
            "decision_identity": decision_identity,
            "obligation_identity": obligation_identity,
            "window_binding_identity": window_binding_identity,
        }
        return cls(
            schema=WINDOW_AUTHORITY_REF_SCHEMA,
            contract_version=1,
            runtime_instance_identity=runtime_instance_identity,
            window_id=window_id,
            parent_window_id=parent_window_id,
            actor_id=actor_id,
            window_kind=window_kind,
            decision_identity=decision_identity,
            obligation_identity=obligation_identity,
            window_binding_identity=window_binding_identity,
            authority_ref_identity=_canonical_sha256(material),
        )

    @classmethod
    def from_window(
        cls, runtime_instance_identity: str, window: TimedDecisionWindowV1
    ) -> "WindowAuthorityRefV1":
        if type(window) is not TimedDecisionWindowV1:
            raise C8TimedSessionRuntimeError("window authority ref需要C8-A window")
        return cls.issue(
            runtime_instance_identity=runtime_instance_identity,
            window_id=window.window_id,
            parent_window_id=window.parent_window_id,
            actor_id=window.actor_id,
            window_kind=window.window_kind,
            decision_identity=window.decision_identity,
            obligation_identity=window.obligation_identity,
            window_binding_identity=window.window_binding_identity,
        )

    @classmethod
    def from_dict(cls, value: object) -> "WindowAuthorityRefV1":
        data = _exact_dict(value, "WindowAuthorityRefV1")
        fields = frozenset(
            {
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
            }
        )
        _exact_fields(data, fields, "WindowAuthorityRefV1")
        return cls(
            schema=_exact_text(data["schema"], "ref.schema"),
            contract_version=_exact_int(data["contract_version"], "contract_version"),
            runtime_instance_identity=_exact_sha256(
                data["runtime_instance_identity"], "runtime_instance_identity"
            ),
            window_id=_exact_text(data["window_id"], "window_id"),
            parent_window_id=_exact_optional_text(
                data["parent_window_id"], "parent_window_id"
            ),
            actor_id=_exact_text_id(data["actor_id"], "actor_id"),
            window_kind=_exact_enum(
                data["window_kind"], TimedWindowKindV1, "window_kind"
            ),
            decision_identity=_exact_sha256(
                data["decision_identity"], "decision_identity"
            ),
            obligation_identity=_exact_sha256(
                data["obligation_identity"], "obligation_identity"
            ),
            window_binding_identity=_exact_sha256(
                data["window_binding_identity"], "window_binding_identity"
            ),
            authority_ref_identity=_exact_sha256(
                data["authority_ref_identity"], "authority_ref_identity"
            ),
        )


def _input_chain_genesis(
    *,
    runtime_instance_identity: str,
    duration_profile_identity: str,
    input_source_id: str,
    driver_authority_identity: str,
) -> str:
    return _canonical_sha256(
        {
            "runtime_contract_identity": C8_B_RUNTIME_CONTRACT_IDENTITY_V1,
            "runtime_instance_identity": runtime_instance_identity,
            "duration_profile_identity": duration_profile_identity,
            "input_source_id": input_source_id,
            "driver_authority_identity": driver_authority_identity,
            "chain": "INPUT_GENESIS",
        }
    )


def derive_advance_request_binding_identity_v1(
    *,
    runtime_instance_identity: str,
    driver_authority_identity: str,
    duration_profile_identity: str,
    previous_input_chain_tip: str,
    input_seq: int,
    source_id: str,
    domain_id: str,
    window_id: str,
    requested_tick: int,
) -> str:
    """Derive the request binding an external one-shot authenticator must sign."""

    material = {
        "schema": INPUT_AUTH_BINDING_SCHEMA,
        "contract_version": 1,
        "runtime_contract_identity": C8_B_RUNTIME_CONTRACT_IDENTITY_V1,
        "runtime_instance_identity": _exact_sha256(
            runtime_instance_identity, "runtime_instance_identity"
        ),
        "driver_authority_identity": _exact_sha256(
            driver_authority_identity, "driver_authority_identity"
        ),
        "duration_profile_identity": _exact_sha256(
            duration_profile_identity, "duration_profile_identity"
        ),
        "previous_input_chain_tip": _exact_sha256(
            previous_input_chain_tip, "previous_input_chain_tip"
        ),
        "input_seq": _exact_int(input_seq, "input_seq"),
        "source_id": _exact_text_id(source_id, "source_id"),
        "domain_id": _exact_text_id(domain_id, "domain_id"),
        "window_id": _exact_text(window_id, "window_id"),
        "requested_tick": _exact_int(requested_tick, "requested_tick"),
    }
    return _canonical_sha256(material)


@dataclass(frozen=True, slots=True, kw_only=True)
class AcceptedVirtualTimeInputV1:
    schema: str
    contract_version: int
    input_seq: int
    input_identity: str
    previous_input_chain_tip: str
    before_virtual_state_identity: str
    after_virtual_state_identity: str
    requested_tick: int
    applied_tick: int
    unconsumed_ticks: int
    derived_deadline_identity: str | None
    input_chain_link_identity: str

    def __post_init__(self) -> None:
        if self.schema != INPUT_RECORD_SCHEMA or self.contract_version != 1:
            raise C8TimedSessionRuntimeError("accepted input record schema/version不匹配")
        _exact_int(self.input_seq, "record.input_seq")
        for label in (
            "input_identity",
            "previous_input_chain_tip",
            "before_virtual_state_identity",
            "after_virtual_state_identity",
        ):
            _exact_sha256(getattr(self, label), f"record.{label}")
        _exact_int(self.requested_tick, "record.requested_tick")
        _exact_int(self.applied_tick, "record.applied_tick")
        _exact_int(self.unconsumed_ticks, "record.unconsumed_ticks")
        if self.requested_tick != self.applied_tick + self.unconsumed_ticks:
            raise C8TimedSessionRuntimeError("accepted input surplus accounting不一致")
        _exact_optional_sha256(
            self.derived_deadline_identity, "record.derived_deadline_identity"
        )
        _assert_identity(
            self.input_chain_link_identity,
            self._identity_material(),
            "input_chain_link_identity",
        )

    def _identity_material(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "contract_version": self.contract_version,
            "input_seq": self.input_seq,
            "input_identity": self.input_identity,
            "previous_input_chain_tip": self.previous_input_chain_tip,
            "before_virtual_state_identity": self.before_virtual_state_identity,
            "after_virtual_state_identity": self.after_virtual_state_identity,
            "requested_tick": self.requested_tick,
            "applied_tick": self.applied_tick,
            "unconsumed_ticks": self.unconsumed_ticks,
            "derived_deadline_identity": self.derived_deadline_identity,
        }

    def to_dict(self) -> dict[str, object]:
        return {
            **self._identity_material(),
            "input_chain_link_identity": self.input_chain_link_identity,
        }

    @classmethod
    def build(
        cls,
        *,
        input_seq: int,
        input_identity: str,
        previous_input_chain_tip: str,
        before_virtual_state_identity: str,
        after_virtual_state_identity: str,
        requested_tick: int,
        applied_tick: int,
        unconsumed_ticks: int,
        derived_deadline_identity: str | None,
    ) -> "AcceptedVirtualTimeInputV1":
        material = {
            "schema": INPUT_RECORD_SCHEMA,
            "contract_version": 1,
            "input_seq": input_seq,
            "input_identity": input_identity,
            "previous_input_chain_tip": previous_input_chain_tip,
            "before_virtual_state_identity": before_virtual_state_identity,
            "after_virtual_state_identity": after_virtual_state_identity,
            "requested_tick": requested_tick,
            "applied_tick": applied_tick,
            "unconsumed_ticks": unconsumed_ticks,
            "derived_deadline_identity": derived_deadline_identity,
        }
        return cls(**material, input_chain_link_identity=_canonical_sha256(material))

    @classmethod
    def from_dict(cls, value: object) -> "AcceptedVirtualTimeInputV1":
        data = _exact_dict(value, "AcceptedVirtualTimeInputV1")
        fields = frozenset(
            {
                "schema",
                "contract_version",
                "input_seq",
                "input_identity",
                "previous_input_chain_tip",
                "before_virtual_state_identity",
                "after_virtual_state_identity",
                "requested_tick",
                "applied_tick",
                "unconsumed_ticks",
                "derived_deadline_identity",
                "input_chain_link_identity",
            }
        )
        _exact_fields(data, fields, "AcceptedVirtualTimeInputV1")
        return cls(
            schema=_exact_text(data["schema"], "record.schema"),
            contract_version=_exact_int(data["contract_version"], "contract_version"),
            input_seq=_exact_int(data["input_seq"], "input_seq"),
            input_identity=_exact_sha256(data["input_identity"], "input_identity"),
            previous_input_chain_tip=_exact_sha256(
                data["previous_input_chain_tip"], "previous_input_chain_tip"
            ),
            before_virtual_state_identity=_exact_sha256(
                data["before_virtual_state_identity"], "before_virtual_state_identity"
            ),
            after_virtual_state_identity=_exact_sha256(
                data["after_virtual_state_identity"], "after_virtual_state_identity"
            ),
            requested_tick=_exact_int(data["requested_tick"], "requested_tick"),
            applied_tick=_exact_int(data["applied_tick"], "applied_tick"),
            unconsumed_ticks=_exact_int(
                data["unconsumed_ticks"], "unconsumed_ticks"
            ),
            derived_deadline_identity=_exact_optional_sha256(
                data["derived_deadline_identity"], "derived_deadline_identity"
            ),
            input_chain_link_identity=_exact_sha256(
                data["input_chain_link_identity"], "input_chain_link_identity"
            ),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class LogicalObligationProgressV1:
    schema: str
    contract_version: int
    window_id: str
    window_binding_identity: str
    obligation_identity: str
    next_step_index: int
    step_identities: tuple[str, ...]
    progress_identity: str

    def __post_init__(self) -> None:
        if self.schema != LOGICAL_PROGRESS_SCHEMA or self.contract_version != 1:
            raise C8TimedSessionRuntimeError("logical progress schema/version不匹配")
        _exact_text(self.window_id, "logical.window_id")
        _exact_sha256(self.window_binding_identity, "logical.window_binding_identity")
        _exact_sha256(self.obligation_identity, "logical.obligation_identity")
        _exact_int(self.next_step_index, "logical.next_step_index")
        if type(self.step_identities) is not tuple:
            raise C8TimedSessionRuntimeError("logical step identities必须是strict tuple")
        for identity in self.step_identities:
            _exact_sha256(identity, "logical.step_identity")
        if len(self.step_identities) != len(set(self.step_identities)):
            raise C8TimedSessionRuntimeError("logical step identity禁止重复")
        if self.next_step_index != len(self.step_identities):
            raise C8TimedSessionRuntimeError("next_step_index与step identity chain不一致")
        _assert_identity(self.progress_identity, self._identity_material(), "progress_identity")

    def _identity_material(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "contract_version": self.contract_version,
            "window_id": self.window_id,
            "window_binding_identity": self.window_binding_identity,
            "obligation_identity": self.obligation_identity,
            "next_step_index": self.next_step_index,
            "step_identities": list(self.step_identities),
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._identity_material(), "progress_identity": self.progress_identity}

    @classmethod
    def build(
        cls,
        *,
        window_id: str,
        window_binding_identity: str,
        obligation_identity: str,
        next_step_index: int,
        step_identities: Sequence[str],
    ) -> "LogicalObligationProgressV1":
        material = {
            "schema": LOGICAL_PROGRESS_SCHEMA,
            "contract_version": 1,
            "window_id": window_id,
            "window_binding_identity": window_binding_identity,
            "obligation_identity": obligation_identity,
            "next_step_index": next_step_index,
            "step_identities": list(step_identities),
        }
        return cls(
            schema=LOGICAL_PROGRESS_SCHEMA,
            contract_version=1,
            window_id=window_id,
            window_binding_identity=window_binding_identity,
            obligation_identity=obligation_identity,
            next_step_index=next_step_index,
            step_identities=tuple(step_identities),
            progress_identity=_canonical_sha256(material),
        )

    @classmethod
    def from_dict(cls, value: object) -> "LogicalObligationProgressV1":
        data = _exact_dict(value, "LogicalObligationProgressV1")
        fields = frozenset(
            {
                "schema",
                "contract_version",
                "window_id",
                "window_binding_identity",
                "obligation_identity",
                "next_step_index",
                "step_identities",
                "progress_identity",
            }
        )
        _exact_fields(data, fields, "LogicalObligationProgressV1")
        return cls(
            schema=_exact_text(data["schema"], "logical.schema"),
            contract_version=_exact_int(data["contract_version"], "contract_version"),
            window_id=_exact_text(data["window_id"], "window_id"),
            window_binding_identity=_exact_sha256(
                data["window_binding_identity"], "window_binding_identity"
            ),
            obligation_identity=_exact_sha256(
                data["obligation_identity"], "obligation_identity"
            ),
            next_step_index=_exact_int(data["next_step_index"], "next_step_index"),
            step_identities=tuple(
                _exact_sha256(item, "step_identities[]")
                for item in _exact_list(data["step_identities"], "step_identities")
            ),
            progress_identity=_exact_sha256(
                data["progress_identity"], "progress_identity"
            ),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class PendingDerivedDeadlineV1:
    schema: str
    contract_version: int
    window_id: str
    window_state_identity: str
    input_identity: str
    derived_deadline_identity: str
    deadline_at: int
    pending_identity: str

    def __post_init__(self) -> None:
        if self.schema != PENDING_DEADLINE_SCHEMA or self.contract_version != 1:
            raise C8TimedSessionRuntimeError("pending deadline schema/version不匹配")
        _exact_text(self.window_id, "pending.window_id")
        _exact_sha256(self.window_state_identity, "pending.window_state_identity")
        _exact_sha256(self.input_identity, "pending.input_identity")
        _exact_sha256(self.derived_deadline_identity, "pending.derived_deadline_identity")
        _exact_int(self.deadline_at, "pending.deadline_at")
        _assert_identity(self.pending_identity, self._identity_material(), "pending_identity")

    def _identity_material(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "contract_version": self.contract_version,
            "window_id": self.window_id,
            "window_state_identity": self.window_state_identity,
            "input_identity": self.input_identity,
            "derived_deadline_identity": self.derived_deadline_identity,
            "deadline_at": self.deadline_at,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._identity_material(), "pending_identity": self.pending_identity}

    @classmethod
    def from_derived(
        cls, derived: DerivedDeadlineReachedV1, window: TimedDecisionWindowV1
    ) -> "PendingDerivedDeadlineV1":
        if type(derived) is not DerivedDeadlineReachedV1:
            raise C8TimedSessionRuntimeError("pending deadline必须来自C8-A derived event")
        if type(window) is not TimedDecisionWindowV1:
            raise C8TimedSessionRuntimeError("pending deadline必须绑定C8-A window")
        material = {
            "schema": PENDING_DEADLINE_SCHEMA,
            "contract_version": 1,
            "window_id": derived.window_id,
            "window_state_identity": window.window_state_identity,
            "input_identity": derived.caused_by_input_identity,
            "derived_deadline_identity": derived.event_identity,
            "deadline_at": derived.deadline_at,
        }
        return cls(**material, pending_identity=_canonical_sha256(material))

    @classmethod
    def from_dict(cls, value: object) -> "PendingDerivedDeadlineV1":
        data = _exact_dict(value, "PendingDerivedDeadlineV1")
        fields = frozenset(
            {
                "schema",
                "contract_version",
                "window_id",
                "window_state_identity",
                "input_identity",
                "derived_deadline_identity",
                "deadline_at",
                "pending_identity",
            }
        )
        _exact_fields(data, fields, "PendingDerivedDeadlineV1")
        return cls(
            schema=_exact_text(data["schema"], "pending.schema"),
            contract_version=_exact_int(data["contract_version"], "contract_version"),
            window_id=_exact_text(data["window_id"], "window_id"),
            window_state_identity=_exact_sha256(
                data["window_state_identity"], "window_state_identity"
            ),
            input_identity=_exact_sha256(data["input_identity"], "input_identity"),
            derived_deadline_identity=_exact_sha256(
                data["derived_deadline_identity"], "derived_deadline_identity"
            ),
            deadline_at=_exact_int(data["deadline_at"], "deadline_at"),
            pending_identity=_exact_sha256(data["pending_identity"], "pending_identity"),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class TimeoutDueCommitmentV1:
    """Wrapper-issued proof of the current pending deadline and exact lineage."""

    schema: str
    contract_version: int
    runtime_contract_identity: str
    runtime_instance_identity: str
    window_authority_ref_identity: str
    window_id: str
    actor_id: str
    decision_identity: str
    obligation_identity: str
    now_tick: int
    deadline_at: int
    virtual_time_state_identity: str
    pending_deadline_identity: str
    derived_deadline_identity: str
    caused_by_input_identity: str
    input_chain_tip: str
    event_chain_tip: str
    outer_state_identity: str
    commitment_identity: str

    def __post_init__(self) -> None:
        if self.schema != TIMEOUT_DUE_COMMITMENT_SCHEMA or self.contract_version != 1:
            raise C8TimedSessionRuntimeError(
                "timeout due commitment schema/version不匹配"
            )
        if self.runtime_contract_identity != C8_B_RUNTIME_CONTRACT_IDENTITY_V1:
            raise C8TimedSessionRuntimeError("timeout due commitment runtime contract drift")
        for label in (
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
        ):
            _exact_sha256(getattr(self, label), f"timeout_due.{label}")
        _exact_text(self.window_id, "timeout_due.window_id")
        _exact_text_id(self.actor_id, "timeout_due.actor_id")
        _exact_int(self.now_tick, "timeout_due.now_tick")
        _exact_int(self.deadline_at, "timeout_due.deadline_at")
        if self.now_tick < self.deadline_at:
            raise C8TimedSessionRuntimeError(
                "timeout due commitment禁止绑定before-deadline状态"
            )
        _assert_identity(
            self.commitment_identity,
            self._identity_material(),
            "timeout due commitment_identity",
        )

    def _identity_material(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "contract_version": self.contract_version,
            "runtime_contract_identity": self.runtime_contract_identity,
            "runtime_instance_identity": self.runtime_instance_identity,
            "window_authority_ref_identity": self.window_authority_ref_identity,
            "window_id": self.window_id,
            "actor_id": self.actor_id,
            "decision_identity": self.decision_identity,
            "obligation_identity": self.obligation_identity,
            "now_tick": self.now_tick,
            "deadline_at": self.deadline_at,
            "virtual_time_state_identity": self.virtual_time_state_identity,
            "pending_deadline_identity": self.pending_deadline_identity,
            "derived_deadline_identity": self.derived_deadline_identity,
            "caused_by_input_identity": self.caused_by_input_identity,
            "input_chain_tip": self.input_chain_tip,
            "event_chain_tip": self.event_chain_tip,
            "outer_state_identity": self.outer_state_identity,
        }

    def to_dict(self) -> dict[str, object]:
        return {
            **self._identity_material(),
            "commitment_identity": self.commitment_identity,
        }

    @classmethod
    def build(
        cls,
        *,
        state: "TimedSessionOuterStateV1",
        ref: WindowAuthorityRefV1,
        active: TimedDecisionWindowV1,
        pending: PendingDerivedDeadlineV1,
    ) -> "TimeoutDueCommitmentV1":
        if type(ref) is not WindowAuthorityRefV1:
            raise C8TimedSessionRuntimeError("timeout due commitment需要window ref")
        if type(active) is not TimedDecisionWindowV1:
            raise C8TimedSessionRuntimeError("timeout due commitment需要active window")
        if type(pending) is not PendingDerivedDeadlineV1:
            raise C8TimedSessionRuntimeError("timeout due commitment需要pending deadline")
        material = {
            "schema": TIMEOUT_DUE_COMMITMENT_SCHEMA,
            "contract_version": 1,
            "runtime_contract_identity": C8_B_RUNTIME_CONTRACT_IDENTITY_V1,
            "runtime_instance_identity": state.runtime_instance_identity,
            "window_authority_ref_identity": ref.authority_ref_identity,
            "window_id": active.window_id,
            "actor_id": active.actor_id,
            "decision_identity": active.decision_identity,
            "obligation_identity": active.obligation_identity,
            "now_tick": state.virtual_time_state.now_tick,
            "deadline_at": active.deadline_at,
            "virtual_time_state_identity": state.virtual_time_state.state_identity,
            "pending_deadline_identity": pending.pending_identity,
            "derived_deadline_identity": pending.derived_deadline_identity,
            "caused_by_input_identity": pending.input_identity,
            "input_chain_tip": state.input_chain_tip,
            "event_chain_tip": state.event_chain_tip,
            "outer_state_identity": state.state_identity,
        }
        return cls(**material, commitment_identity=_canonical_sha256(material))

    @classmethod
    def from_dict(cls, value: object) -> "TimeoutDueCommitmentV1":
        data = _exact_dict(value, "TimeoutDueCommitmentV1")
        fields = frozenset(
            {
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
            }
        )
        _exact_fields(data, fields, "TimeoutDueCommitmentV1")
        return cls(
            schema=_exact_text(data["schema"], "timeout_due.schema"),
            contract_version=_exact_int(data["contract_version"], "contract_version"),
            runtime_contract_identity=_exact_sha256(
                data["runtime_contract_identity"], "runtime_contract_identity"
            ),
            runtime_instance_identity=_exact_sha256(
                data["runtime_instance_identity"], "runtime_instance_identity"
            ),
            window_authority_ref_identity=_exact_sha256(
                data["window_authority_ref_identity"],
                "window_authority_ref_identity",
            ),
            window_id=_exact_text(data["window_id"], "window_id"),
            actor_id=_exact_text_id(data["actor_id"], "actor_id"),
            decision_identity=_exact_sha256(
                data["decision_identity"], "decision_identity"
            ),
            obligation_identity=_exact_sha256(
                data["obligation_identity"], "obligation_identity"
            ),
            now_tick=_exact_int(data["now_tick"], "now_tick"),
            deadline_at=_exact_int(data["deadline_at"], "deadline_at"),
            virtual_time_state_identity=_exact_sha256(
                data["virtual_time_state_identity"], "virtual_time_state_identity"
            ),
            pending_deadline_identity=_exact_sha256(
                data["pending_deadline_identity"], "pending_deadline_identity"
            ),
            derived_deadline_identity=_exact_sha256(
                data["derived_deadline_identity"], "derived_deadline_identity"
            ),
            caused_by_input_identity=_exact_sha256(
                data["caused_by_input_identity"], "caused_by_input_identity"
            ),
            input_chain_tip=_exact_sha256(data["input_chain_tip"], "input_chain_tip"),
            event_chain_tip=_exact_sha256(data["event_chain_tip"], "event_chain_tip"),
            outer_state_identity=_exact_sha256(
                data["outer_state_identity"], "outer_state_identity"
            ),
            commitment_identity=_exact_sha256(
                data["commitment_identity"], "commitment_identity"
            ),
        )


def derive_timeout_action_authorization_binding_v1(
    *,
    timeout_due_commitment: TimeoutDueCommitmentV1,
    signed_action_id: str,
    issuance_authority_identity: str,
    previous_auth_ledger_identity: str,
    receipt_sequence: int,
    previous_receipt_identity: str,
    pending_issuance_capability_identity: str | None = None,
) -> str:
    """Bind future C8-C fresh issuance to one exact timeout transition."""

    if type(timeout_due_commitment) is not TimeoutDueCommitmentV1:
        raise C8TimedSessionRuntimeError(
            "timeout action authorization需要strict due commitment"
        )
    material = {
        "schema": TIMEOUT_ACTION_AUTH_BINDING_SCHEMA,
        "contract_version": 1,
        "runtime_contract_identity": C8_B_RUNTIME_CONTRACT_IDENTITY_V1,
        "runtime_instance_identity": timeout_due_commitment.runtime_instance_identity,
        "issuance_authority_identity": _exact_sha256(
            issuance_authority_identity, "issuance_authority_identity"
        ),
        "previous_auth_ledger_identity": _exact_sha256(
            previous_auth_ledger_identity, "previous_auth_ledger_identity"
        ),
        "timeout_due_commitment_identity": timeout_due_commitment.commitment_identity,
        "window_authority_ref_identity": (
            timeout_due_commitment.window_authority_ref_identity
        ),
        "signed_action_id_commitment": _signed_action_id_commitment_v1(
            signed_action_id
        ),
        "receipt_sequence": _exact_int(receipt_sequence, "receipt_sequence"),
        "previous_receipt_identity": _exact_sha256(
            previous_receipt_identity, "previous_receipt_identity"
        ),
        "pending_issuance_capability_identity": _exact_optional_sha256(
            pending_issuance_capability_identity,
            "pending_issuance_capability_identity",
        ),
    }
    return _canonical_sha256(material)


@dataclass(frozen=True, slots=True, kw_only=True)
class TimeoutActionExecutionReceiptV1:
    """Strict public-ID/identity receipt; it never serializes private payload."""

    schema: str
    contract_version: int
    runtime_contract_identity: str
    runtime_instance_identity: str
    receipt_sequence: int
    previous_receipt_identity: str
    window_authority_ref_identity: str
    window_id: str
    actor_id: str
    decision_identity: str
    obligation_identity: str
    signed_action_id_commitment: str
    pre_inner_public_state_identity: str
    pre_inner_authoritative_state_identity: str
    post_inner_public_state_identity: str
    post_inner_authoritative_state_identity: str
    inner_adapter_identity: str
    inner_session_binding_identity: str
    issuance_authority_identity: str
    authorization_evidence_identity: str
    authorization_binding_identity: str
    authorization_ledger_before_identity: str
    authorization_ledger_after_identity: str
    pending_issuance_capability_identity: str | None
    timeout_due_commitment_identity: str
    pending_deadline_identity: str
    derived_deadline_identity: str
    deadline_at: int
    executed_at_tick: int
    outer_transition_identity: str
    accepted: bool
    executed: bool
    receipt_identity: str

    def __post_init__(self) -> None:
        if (
            self.schema != TIMEOUT_EXECUTION_RECEIPT_SCHEMA
            or self.contract_version != 1
        ):
            raise C8TimedSessionRuntimeError(
                "timeout execution receipt schema/version不匹配"
            )
        if self.runtime_contract_identity != C8_B_RUNTIME_CONTRACT_IDENTITY_V1:
            raise C8TimedSessionRuntimeError(
                "timeout execution receipt runtime contract drift"
            )
        _exact_int(self.receipt_sequence, "receipt_sequence")
        for label in (
            "runtime_contract_identity",
            "runtime_instance_identity",
            "previous_receipt_identity",
            "window_authority_ref_identity",
            "decision_identity",
            "obligation_identity",
            "signed_action_id_commitment",
            "pre_inner_public_state_identity",
            "pre_inner_authoritative_state_identity",
            "post_inner_public_state_identity",
            "post_inner_authoritative_state_identity",
            "inner_adapter_identity",
            "inner_session_binding_identity",
            "issuance_authority_identity",
            "authorization_evidence_identity",
            "authorization_binding_identity",
            "authorization_ledger_before_identity",
            "authorization_ledger_after_identity",
            "timeout_due_commitment_identity",
            "pending_deadline_identity",
            "derived_deadline_identity",
            "outer_transition_identity",
        ):
            _exact_sha256(getattr(self, label), f"timeout_receipt.{label}")
        _exact_optional_sha256(
            self.pending_issuance_capability_identity,
            "timeout_receipt.pending_issuance_capability_identity",
        )
        _exact_text(self.window_id, "timeout_receipt.window_id")
        _exact_text_id(self.actor_id, "timeout_receipt.actor_id")
        _exact_int(self.deadline_at, "timeout_receipt.deadline_at")
        _exact_int(self.executed_at_tick, "timeout_receipt.executed_at_tick")
        if self.executed_at_tick < self.deadline_at:
            raise C8TimedSessionRuntimeError(
                "timeout execution receipt禁止before-deadline execution"
            )
        if not _exact_bool(self.accepted, "timeout_receipt.accepted"):
            raise C8TimedSessionRuntimeError("timeout execution receipt必须accepted=true")
        if not _exact_bool(self.executed, "timeout_receipt.executed"):
            raise C8TimedSessionRuntimeError("timeout execution receipt必须executed=true")
        if (
            self.authorization_ledger_before_identity
            == self.authorization_ledger_after_identity
        ):
            raise C8TimedSessionRuntimeError(
                "timeout execution receipt必须证明external auth ledger推进"
            )
        if (
            self.pre_inner_authoritative_state_identity
            == self.post_inner_authoritative_state_identity
        ):
            raise C8TimedSessionRuntimeError(
                "timeout execution receipt必须证明authoritative state transition"
            )
        _assert_identity(
            self.receipt_identity,
            self._identity_material(),
            "timeout execution receipt_identity",
        )

    def _identity_material(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "contract_version": self.contract_version,
            "runtime_contract_identity": self.runtime_contract_identity,
            "runtime_instance_identity": self.runtime_instance_identity,
            "receipt_sequence": self.receipt_sequence,
            "previous_receipt_identity": self.previous_receipt_identity,
            "window_authority_ref_identity": self.window_authority_ref_identity,
            "window_id": self.window_id,
            "actor_id": self.actor_id,
            "decision_identity": self.decision_identity,
            "obligation_identity": self.obligation_identity,
            "signed_action_id_commitment": self.signed_action_id_commitment,
            "pre_inner_public_state_identity": self.pre_inner_public_state_identity,
            "pre_inner_authoritative_state_identity": (
                self.pre_inner_authoritative_state_identity
            ),
            "post_inner_public_state_identity": self.post_inner_public_state_identity,
            "post_inner_authoritative_state_identity": (
                self.post_inner_authoritative_state_identity
            ),
            "inner_adapter_identity": self.inner_adapter_identity,
            "inner_session_binding_identity": self.inner_session_binding_identity,
            "issuance_authority_identity": self.issuance_authority_identity,
            "authorization_evidence_identity": self.authorization_evidence_identity,
            "authorization_binding_identity": self.authorization_binding_identity,
            "authorization_ledger_before_identity": (
                self.authorization_ledger_before_identity
            ),
            "authorization_ledger_after_identity": (
                self.authorization_ledger_after_identity
            ),
            "pending_issuance_capability_identity": (
                self.pending_issuance_capability_identity
            ),
            "timeout_due_commitment_identity": self.timeout_due_commitment_identity,
            "pending_deadline_identity": self.pending_deadline_identity,
            "derived_deadline_identity": self.derived_deadline_identity,
            "deadline_at": self.deadline_at,
            "executed_at_tick": self.executed_at_tick,
            "outer_transition_identity": self.outer_transition_identity,
            "accepted": self.accepted,
            "executed": self.executed,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._identity_material(), "receipt_identity": self.receipt_identity}

    @classmethod
    def build(
        cls,
        *,
        runtime_instance_identity: str,
        receipt_sequence: int,
        previous_receipt_identity: str,
        ref: WindowAuthorityRefV1,
        signed_action_id_commitment: str,
        pre_inner_public_state_identity: str,
        pre_inner_authoritative_state_identity: str,
        post_inner_public_state_identity: str,
        post_inner_authoritative_state_identity: str,
        inner_adapter_identity: str,
        inner_session_binding_identity: str,
        issuance_authority_identity: str,
        authorization_evidence_identity: str,
        authorization_binding_identity: str,
        authorization_ledger_before_identity: str,
        authorization_ledger_after_identity: str,
        timeout_due_commitment: TimeoutDueCommitmentV1,
        outer_transition_identity: str,
        pending_issuance_capability_identity: str | None = None,
    ) -> "TimeoutActionExecutionReceiptV1":
        if type(ref) is not WindowAuthorityRefV1:
            raise C8TimedSessionRuntimeError("timeout receipt需要strict window ref")
        if type(timeout_due_commitment) is not TimeoutDueCommitmentV1:
            raise C8TimedSessionRuntimeError(
                "timeout receipt需要strict due commitment"
            )
        material = {
            "schema": TIMEOUT_EXECUTION_RECEIPT_SCHEMA,
            "contract_version": 1,
            "runtime_contract_identity": C8_B_RUNTIME_CONTRACT_IDENTITY_V1,
            "runtime_instance_identity": runtime_instance_identity,
            "receipt_sequence": receipt_sequence,
            "previous_receipt_identity": previous_receipt_identity,
            "window_authority_ref_identity": ref.authority_ref_identity,
            "window_id": ref.window_id,
            "actor_id": ref.actor_id,
            "decision_identity": ref.decision_identity,
            "obligation_identity": ref.obligation_identity,
            "signed_action_id_commitment": signed_action_id_commitment,
            "pre_inner_public_state_identity": pre_inner_public_state_identity,
            "pre_inner_authoritative_state_identity": (
                pre_inner_authoritative_state_identity
            ),
            "post_inner_public_state_identity": post_inner_public_state_identity,
            "post_inner_authoritative_state_identity": (
                post_inner_authoritative_state_identity
            ),
            "inner_adapter_identity": inner_adapter_identity,
            "inner_session_binding_identity": inner_session_binding_identity,
            "issuance_authority_identity": issuance_authority_identity,
            "authorization_evidence_identity": authorization_evidence_identity,
            "authorization_binding_identity": authorization_binding_identity,
            "authorization_ledger_before_identity": (
                authorization_ledger_before_identity
            ),
            "authorization_ledger_after_identity": (
                authorization_ledger_after_identity
            ),
            "pending_issuance_capability_identity": (
                pending_issuance_capability_identity
            ),
            "timeout_due_commitment_identity": (
                timeout_due_commitment.commitment_identity
            ),
            "pending_deadline_identity": (
                timeout_due_commitment.pending_deadline_identity
            ),
            "derived_deadline_identity": (
                timeout_due_commitment.derived_deadline_identity
            ),
            "deadline_at": timeout_due_commitment.deadline_at,
            "executed_at_tick": timeout_due_commitment.now_tick,
            "outer_transition_identity": outer_transition_identity,
            "accepted": True,
            "executed": True,
        }
        return cls(**material, receipt_identity=_canonical_sha256(material))

    @classmethod
    def from_dict(cls, value: object) -> "TimeoutActionExecutionReceiptV1":
        data = _exact_dict(value, "TimeoutActionExecutionReceiptV1")
        fields = frozenset(
            {
                "schema",
                "contract_version",
                "runtime_contract_identity",
                "runtime_instance_identity",
                "receipt_sequence",
                "previous_receipt_identity",
                "window_authority_ref_identity",
                "window_id",
                "actor_id",
                "decision_identity",
                "obligation_identity",
                "signed_action_id_commitment",
                "pre_inner_public_state_identity",
                "pre_inner_authoritative_state_identity",
                "post_inner_public_state_identity",
                "post_inner_authoritative_state_identity",
                "inner_adapter_identity",
                "inner_session_binding_identity",
                "issuance_authority_identity",
                "authorization_evidence_identity",
                "authorization_binding_identity",
                "authorization_ledger_before_identity",
                "authorization_ledger_after_identity",
                "pending_issuance_capability_identity",
                "timeout_due_commitment_identity",
                "pending_deadline_identity",
                "derived_deadline_identity",
                "deadline_at",
                "executed_at_tick",
                "outer_transition_identity",
                "accepted",
                "executed",
                "receipt_identity",
            }
        )
        _exact_fields(data, fields, "TimeoutActionExecutionReceiptV1")
        sha_fields = {
            label: _exact_sha256(data[label], label)
            for label in (
                "runtime_contract_identity",
                "runtime_instance_identity",
                "previous_receipt_identity",
                "window_authority_ref_identity",
                "decision_identity",
                "obligation_identity",
                "signed_action_id_commitment",
                "pre_inner_public_state_identity",
                "pre_inner_authoritative_state_identity",
                "post_inner_public_state_identity",
                "post_inner_authoritative_state_identity",
                "inner_adapter_identity",
                "inner_session_binding_identity",
                "issuance_authority_identity",
                "authorization_evidence_identity",
                "authorization_binding_identity",
                "authorization_ledger_before_identity",
                "authorization_ledger_after_identity",
                "timeout_due_commitment_identity",
                "pending_deadline_identity",
                "derived_deadline_identity",
                "outer_transition_identity",
                "receipt_identity",
            )
        }
        return cls(
            schema=_exact_text(data["schema"], "timeout_receipt.schema"),
            contract_version=_exact_int(data["contract_version"], "contract_version"),
            receipt_sequence=_exact_int(data["receipt_sequence"], "receipt_sequence"),
            window_id=_exact_text(data["window_id"], "window_id"),
            actor_id=_exact_text_id(data["actor_id"], "actor_id"),
            deadline_at=_exact_int(data["deadline_at"], "deadline_at"),
            executed_at_tick=_exact_int(data["executed_at_tick"], "executed_at_tick"),
            accepted=_exact_bool(data["accepted"], "accepted"),
            executed=_exact_bool(data["executed"], "executed"),
            pending_issuance_capability_identity=_exact_optional_sha256(
                data["pending_issuance_capability_identity"],
                "pending_issuance_capability_identity",
            ),
            **sha_fields,
        )


class PendingIssuanceCapabilityStatusV1(str, Enum):
    CONTROLLER_OWNED_PENDING = "CONTROLLER_OWNED_PENDING"
    AUTH_EVIDENCE_CONSUMED = "AUTH_EVIDENCE_CONSUMED"
    RECEIPT_COMMITTED_CONSUMED = "RECEIPT_COMMITTED_CONSUMED"
    CONTROLLER_ABORTED = "CONTROLLER_ABORTED"


@dataclass(frozen=True, slots=True, kw_only=True)
class ControllerCallbackLeaseV1:
    """One-shot live capability; intentionally has no serialization API."""

    schema: str
    contract_version: int
    runtime_contract_identity: str
    runtime_instance_identity: str
    controller_identity: str
    adapter_identity: str
    window_authority_ref_identity: str
    window_id: str
    timeout_due_commitment_identity: str
    pending_deadline_identity: str
    outer_state_identity_at_issue: str
    lease_generation: int
    operation_attempt_epoch_at_issue: int
    lease_nonce_identity: str
    lease_identity: str
    _owner_guard: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self.schema != CONTROLLER_CALLBACK_LEASE_SCHEMA or self.contract_version != 1:
            raise C8TimedSessionRuntimeError(
                "controller callback lease schema/version不匹配"
            )
        if self.runtime_contract_identity != C8_B_RUNTIME_CONTRACT_IDENTITY_V1:
            raise C8TimedSessionRuntimeError(
                "controller callback lease runtime contract drift"
            )
        for label in (
            "runtime_contract_identity",
            "runtime_instance_identity",
            "controller_identity",
            "adapter_identity",
            "window_authority_ref_identity",
            "timeout_due_commitment_identity",
            "pending_deadline_identity",
            "outer_state_identity_at_issue",
            "lease_nonce_identity",
        ):
            _exact_sha256(getattr(self, label), f"controller_lease.{label}")
        _exact_text(self.window_id, "controller_lease.window_id")
        _exact_int(self.lease_generation, "controller_lease.lease_generation")
        _exact_int(
            self.operation_attempt_epoch_at_issue,
            "controller_lease.operation_attempt_epoch_at_issue",
        )
        _assert_identity(
            self.lease_identity,
            self._identity_material(),
            "controller callback lease_identity",
        )

    def _identity_material(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "contract_version": self.contract_version,
            "runtime_contract_identity": self.runtime_contract_identity,
            "runtime_instance_identity": self.runtime_instance_identity,
            "controller_identity": self.controller_identity,
            "adapter_identity": self.adapter_identity,
            "window_authority_ref_identity": self.window_authority_ref_identity,
            "window_id": self.window_id,
            "timeout_due_commitment_identity": self.timeout_due_commitment_identity,
            "pending_deadline_identity": self.pending_deadline_identity,
            "outer_state_identity_at_issue": self.outer_state_identity_at_issue,
            "lease_generation": self.lease_generation,
            "operation_attempt_epoch_at_issue": self.operation_attempt_epoch_at_issue,
            "lease_nonce_identity": self.lease_nonce_identity,
            "live_owner_guard_bound": True,
            "serializable_authority": False,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class ControllerCallbackGuardTokenV1:
    """Active guard token; only the exact issuing wrapper may release it."""

    schema: str
    contract_version: int
    runtime_contract_identity: str
    runtime_instance_identity: str
    controller_identity: str
    adapter_identity: str
    window_authority_ref_identity: str
    window_id: str
    timeout_due_commitment_identity: str
    pending_deadline_identity: str
    lease_identity: str
    guard_generation: int
    guard_nonce_identity: str
    operation_attempt_epoch_at_entry: int
    operation_attempt_chain_tip_at_entry: str
    outer_state_identity_at_entry: str
    guard_identity: str
    _owner_guard: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self.schema != CONTROLLER_CALLBACK_GUARD_SCHEMA or self.contract_version != 1:
            raise C8TimedSessionRuntimeError(
                "controller callback guard schema/version不匹配"
            )
        if self.runtime_contract_identity != C8_B_RUNTIME_CONTRACT_IDENTITY_V1:
            raise C8TimedSessionRuntimeError(
                "controller callback guard runtime contract drift"
            )
        for label in (
            "runtime_contract_identity",
            "runtime_instance_identity",
            "controller_identity",
            "adapter_identity",
            "window_authority_ref_identity",
            "timeout_due_commitment_identity",
            "pending_deadline_identity",
            "lease_identity",
            "guard_nonce_identity",
            "operation_attempt_chain_tip_at_entry",
            "outer_state_identity_at_entry",
        ):
            _exact_sha256(getattr(self, label), f"controller_guard.{label}")
        _exact_text(self.window_id, "controller_guard.window_id")
        _exact_int(self.guard_generation, "controller_guard.guard_generation")
        _exact_int(
            self.operation_attempt_epoch_at_entry,
            "controller_guard.operation_attempt_epoch_at_entry",
        )
        _assert_identity(
            self.guard_identity,
            self._identity_material(),
            "controller callback guard_identity",
        )

    def _identity_material(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "contract_version": self.contract_version,
            "runtime_contract_identity": self.runtime_contract_identity,
            "runtime_instance_identity": self.runtime_instance_identity,
            "controller_identity": self.controller_identity,
            "adapter_identity": self.adapter_identity,
            "window_authority_ref_identity": self.window_authority_ref_identity,
            "window_id": self.window_id,
            "timeout_due_commitment_identity": self.timeout_due_commitment_identity,
            "pending_deadline_identity": self.pending_deadline_identity,
            "lease_identity": self.lease_identity,
            "guard_generation": self.guard_generation,
            "guard_nonce_identity": self.guard_nonce_identity,
            "operation_attempt_epoch_at_entry": self.operation_attempt_epoch_at_entry,
            "operation_attempt_chain_tip_at_entry": (
                self.operation_attempt_chain_tip_at_entry
            ),
            "outer_state_identity_at_entry": self.outer_state_identity_at_entry,
            "live_owner_guard_bound": True,
            "serializable_authority": False,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class ControllerCallbackGuardResultV1:
    """Successful release evidence; also a one-shot live registration authority."""

    schema: str
    contract_version: int
    runtime_contract_identity: str
    runtime_instance_identity: str
    controller_identity: str
    adapter_identity: str
    window_authority_ref_identity: str
    window_id: str
    timeout_due_commitment_identity: str
    pending_deadline_identity: str
    lease_identity: str
    guard_generation: int
    guard_identity: str
    operation_attempt_epoch_at_entry: int
    operation_attempt_epoch_at_exit: int
    operation_attempt_chain_tip_at_entry: str
    operation_attempt_chain_tip_at_exit: str
    outer_state_identity_at_entry: str
    outer_state_identity_at_exit: str
    callback_completed: bool
    result_identity: str
    _owner_guard: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if (
            self.schema != CONTROLLER_CALLBACK_GUARD_RESULT_SCHEMA
            or self.contract_version != 1
        ):
            raise C8TimedSessionRuntimeError(
                "controller callback guard result schema/version不匹配"
            )
        if self.runtime_contract_identity != C8_B_RUNTIME_CONTRACT_IDENTITY_V1:
            raise C8TimedSessionRuntimeError(
                "controller callback guard result runtime contract drift"
            )
        for label in (
            "runtime_contract_identity",
            "runtime_instance_identity",
            "controller_identity",
            "adapter_identity",
            "window_authority_ref_identity",
            "timeout_due_commitment_identity",
            "pending_deadline_identity",
            "lease_identity",
            "guard_identity",
            "operation_attempt_chain_tip_at_entry",
            "operation_attempt_chain_tip_at_exit",
            "outer_state_identity_at_entry",
            "outer_state_identity_at_exit",
        ):
            _exact_sha256(getattr(self, label), f"controller_result.{label}")
        _exact_text(self.window_id, "controller_result.window_id")
        _exact_int(self.guard_generation, "controller_result.guard_generation")
        _exact_int(
            self.operation_attempt_epoch_at_entry,
            "controller_result.operation_attempt_epoch_at_entry",
        )
        _exact_int(
            self.operation_attempt_epoch_at_exit,
            "controller_result.operation_attempt_epoch_at_exit",
        )
        if (
            self.operation_attempt_epoch_at_entry
            != self.operation_attempt_epoch_at_exit
            or self.operation_attempt_chain_tip_at_entry
            != self.operation_attempt_chain_tip_at_exit
            or self.outer_state_identity_at_entry
            != self.outer_state_identity_at_exit
        ):
            raise C8TimedSessionRuntimeError(
                "controller callback guard result禁止operation/state drift"
            )
        if not _exact_bool(self.callback_completed, "callback_completed"):
            raise C8TimedSessionRuntimeError(
                "controller callback guard result必须证明callback completed"
            )
        _assert_identity(
            self.result_identity,
            self._identity_material(),
            "controller callback guard result_identity",
        )

    def _identity_material(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "contract_version": self.contract_version,
            "runtime_contract_identity": self.runtime_contract_identity,
            "runtime_instance_identity": self.runtime_instance_identity,
            "controller_identity": self.controller_identity,
            "adapter_identity": self.adapter_identity,
            "window_authority_ref_identity": self.window_authority_ref_identity,
            "window_id": self.window_id,
            "timeout_due_commitment_identity": self.timeout_due_commitment_identity,
            "pending_deadline_identity": self.pending_deadline_identity,
            "lease_identity": self.lease_identity,
            "guard_generation": self.guard_generation,
            "guard_identity": self.guard_identity,
            "operation_attempt_epoch_at_entry": self.operation_attempt_epoch_at_entry,
            "operation_attempt_epoch_at_exit": self.operation_attempt_epoch_at_exit,
            "operation_attempt_chain_tip_at_entry": (
                self.operation_attempt_chain_tip_at_entry
            ),
            "operation_attempt_chain_tip_at_exit": (
                self.operation_attempt_chain_tip_at_exit
            ),
            "outer_state_identity_at_entry": self.outer_state_identity_at_entry,
            "outer_state_identity_at_exit": self.outer_state_identity_at_exit,
            "callback_completed": self.callback_completed,
            "live_owner_guard_bound": True,
            "serializable_authority": False,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class ControllerCallbackInvocationResultV1:
    guard_result: ControllerCallbackGuardResultV1
    callback_result: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if type(self.guard_result) is not ControllerCallbackGuardResultV1:
            raise C8TimedSessionRuntimeError(
                "controller callback invocation需要strict guard result"
            )


@dataclass(frozen=True, slots=True, kw_only=True)
class ControllerCallbackSecurityAuditV1:
    """Non-authorizing audit projection of the non-rollback security plane."""

    schema: str
    contract_version: int
    runtime_contract_identity: str
    runtime_instance_identity: str
    operation_attempt_epoch: int
    operation_attempt_chain_tip: str
    guard_active: bool
    next_guard_generation: int
    audit_identity: str

    def __post_init__(self) -> None:
        if (
            self.schema != CONTROLLER_CALLBACK_SECURITY_AUDIT_SCHEMA
            or self.contract_version != 1
        ):
            raise C8TimedSessionRuntimeError(
                "controller callback security audit schema/version不匹配"
            )
        if self.runtime_contract_identity != C8_B_RUNTIME_CONTRACT_IDENTITY_V1:
            raise C8TimedSessionRuntimeError(
                "controller callback security audit runtime contract drift"
            )
        _exact_sha256(self.runtime_instance_identity, "security_audit.runtime_instance")
        _exact_int(self.operation_attempt_epoch, "security_audit.operation_attempt_epoch")
        _exact_sha256(
            self.operation_attempt_chain_tip,
            "security_audit.operation_attempt_chain_tip",
        )
        _exact_bool(self.guard_active, "security_audit.guard_active")
        _exact_int(self.next_guard_generation, "security_audit.next_guard_generation")
        _assert_identity(
            self.audit_identity,
            self._identity_material(),
            "controller callback security audit_identity",
        )

    def _identity_material(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "contract_version": self.contract_version,
            "runtime_contract_identity": self.runtime_contract_identity,
            "runtime_instance_identity": self.runtime_instance_identity,
            "operation_attempt_epoch": self.operation_attempt_epoch,
            "operation_attempt_chain_tip": self.operation_attempt_chain_tip,
            "guard_active": self.guard_active,
            "next_guard_generation": self.next_guard_generation,
            "authorizing_capability_exposed": False,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._identity_material(), "audit_identity": self.audit_identity}


@dataclass(frozen=True, slots=True, kw_only=True)
class PendingTimeoutIssuanceCapabilityV1:
    """Controller-owned pending capability lease; never serialized or restored."""

    schema: str
    contract_version: int
    runtime_contract_identity: str
    runtime_instance_identity: str
    controller_identity: str
    adapter_identity: str
    window_authority_ref_identity: str
    window_id: str
    timeout_due_commitment_identity: str
    pending_deadline_identity: str
    signed_action_id_commitment: str
    external_capability_identity: str
    authorization_ledger_identity_at_issue: str
    guard_result_identity: str
    capability_generation: int
    operation_attempt_epoch_at_issue: int
    ownership_nonce_identity: str
    capability_identity: str
    _owner_guard: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if (
            self.schema != PENDING_ISSUANCE_CAPABILITY_SCHEMA
            or self.contract_version != 1
        ):
            raise C8TimedSessionRuntimeError(
                "pending issuance capability schema/version不匹配"
            )
        if self.runtime_contract_identity != C8_B_RUNTIME_CONTRACT_IDENTITY_V1:
            raise C8TimedSessionRuntimeError(
                "pending issuance capability runtime contract drift"
            )
        for label in (
            "runtime_contract_identity",
            "runtime_instance_identity",
            "controller_identity",
            "adapter_identity",
            "window_authority_ref_identity",
            "timeout_due_commitment_identity",
            "pending_deadline_identity",
            "signed_action_id_commitment",
            "external_capability_identity",
            "authorization_ledger_identity_at_issue",
            "guard_result_identity",
            "ownership_nonce_identity",
        ):
            _exact_sha256(getattr(self, label), f"pending_capability.{label}")
        _exact_text(self.window_id, "pending_capability.window_id")
        _exact_int(
            self.capability_generation,
            "pending_capability.capability_generation",
        )
        _exact_int(
            self.operation_attempt_epoch_at_issue,
            "pending_capability.operation_attempt_epoch_at_issue",
        )
        _assert_identity(
            self.capability_identity,
            self._identity_material(),
            "pending issuance capability_identity",
        )

    def _identity_material(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "contract_version": self.contract_version,
            "runtime_contract_identity": self.runtime_contract_identity,
            "runtime_instance_identity": self.runtime_instance_identity,
            "controller_identity": self.controller_identity,
            "adapter_identity": self.adapter_identity,
            "window_authority_ref_identity": self.window_authority_ref_identity,
            "window_id": self.window_id,
            "timeout_due_commitment_identity": self.timeout_due_commitment_identity,
            "pending_deadline_identity": self.pending_deadline_identity,
            "signed_action_id_commitment": self.signed_action_id_commitment,
            "external_capability_identity": self.external_capability_identity,
            "authorization_ledger_identity_at_issue": (
                self.authorization_ledger_identity_at_issue
            ),
            "guard_result_identity": self.guard_result_identity,
            "capability_generation": self.capability_generation,
            "operation_attempt_epoch_at_issue": (
                self.operation_attempt_epoch_at_issue
            ),
            "ownership_nonce_identity": self.ownership_nonce_identity,
            "live_owner_guard_bound": True,
            "serializable_authority": False,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class PendingIssuanceCapabilityOwnershipV1:
    """Audit-only lifecycle view; runtime APIs never accept it as authority."""

    schema: str
    contract_version: int
    runtime_contract_identity: str
    runtime_instance_identity: str
    capability_identity: str
    controller_identity: str
    adapter_identity: str
    window_authority_ref_identity: str
    timeout_due_commitment_identity: str
    external_capability_identity: str
    status: PendingIssuanceCapabilityStatusV1
    committed_receipt_identity: str | None
    ownership_identity: str

    def __post_init__(self) -> None:
        if (
            self.schema != PENDING_ISSUANCE_OWNERSHIP_SCHEMA
            or self.contract_version != 1
        ):
            raise C8TimedSessionRuntimeError(
                "pending issuance ownership schema/version不匹配"
            )
        if self.runtime_contract_identity != C8_B_RUNTIME_CONTRACT_IDENTITY_V1:
            raise C8TimedSessionRuntimeError(
                "pending issuance ownership runtime contract drift"
            )
        for label in (
            "runtime_instance_identity",
            "capability_identity",
            "controller_identity",
            "adapter_identity",
            "window_authority_ref_identity",
            "timeout_due_commitment_identity",
            "external_capability_identity",
        ):
            _exact_sha256(getattr(self, label), f"pending_ownership.{label}")
        if type(self.status) is not PendingIssuanceCapabilityStatusV1:
            raise C8TimedSessionRuntimeError(
                "pending issuance ownership status类型不正确"
            )
        _exact_optional_sha256(
            self.committed_receipt_identity,
            "pending_ownership.committed_receipt_identity",
        )
        if (
            self.status is PendingIssuanceCapabilityStatusV1.RECEIPT_COMMITTED_CONSUMED
        ) != (self.committed_receipt_identity is not None):
            raise C8TimedSessionRuntimeError(
                "pending issuance ownership receipt/status不一致"
            )
        _assert_identity(
            self.ownership_identity,
            self._identity_material(),
            "pending issuance ownership_identity",
        )

    def _identity_material(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "contract_version": self.contract_version,
            "runtime_contract_identity": self.runtime_contract_identity,
            "runtime_instance_identity": self.runtime_instance_identity,
            "capability_identity": self.capability_identity,
            "controller_identity": self.controller_identity,
            "adapter_identity": self.adapter_identity,
            "window_authority_ref_identity": self.window_authority_ref_identity,
            "timeout_due_commitment_identity": self.timeout_due_commitment_identity,
            "external_capability_identity": self.external_capability_identity,
            "status": self.status.value,
            "committed_receipt_identity": self.committed_receipt_identity,
            "authorizing_capability_exposed": False,
        }

    def to_dict(self) -> dict[str, object]:
        return {
            **self._identity_material(),
            "ownership_identity": self.ownership_identity,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class RuntimeEventV1:
    schema: str
    contract_version: int
    event_sequence: int
    event_kind: RuntimeEventKindV1
    runtime_instance_identity: str
    tick: int
    window_id: str
    related_window_id: str | None
    actor_id: str
    decision_identity: str
    obligation_identity: str
    window_state_identity: str
    before_virtual_state_identity: str
    after_virtual_state_identity: str
    input_identity: str | None
    derived_deadline_identity: str | None
    logical_step_identity: str | None
    inner_transition_identity: str | None
    execution_receipt_identity: str | None
    requested_tick: int | None
    applied_tick: int | None
    remaining_ticks: int
    previous_event_identity: str
    event_identity: str

    def __post_init__(self) -> None:
        if self.schema != RUNTIME_EVENT_SCHEMA or self.contract_version != 1:
            raise C8TimedSessionRuntimeError("runtime event schema/version不匹配")
        _exact_int(self.event_sequence, "event_sequence")
        if type(self.event_kind) is not RuntimeEventKindV1:
            raise C8TimedSessionRuntimeError("event_kind类型不正确")
        _exact_sha256(self.runtime_instance_identity, "runtime_instance_identity")
        _exact_int(self.tick, "event.tick")
        _exact_text(self.window_id, "event.window_id")
        _exact_optional_text(self.related_window_id, "event.related_window_id")
        _exact_text_id(self.actor_id, "event.actor_id")
        for label in (
            "decision_identity",
            "obligation_identity",
            "window_state_identity",
            "before_virtual_state_identity",
            "after_virtual_state_identity",
            "previous_event_identity",
        ):
            _exact_sha256(getattr(self, label), f"event.{label}")
        _exact_optional_sha256(self.input_identity, "event.input_identity")
        _exact_optional_sha256(
            self.derived_deadline_identity, "event.derived_deadline_identity"
        )
        _exact_optional_sha256(self.logical_step_identity, "event.logical_step_identity")
        _exact_optional_sha256(
            self.inner_transition_identity, "event.inner_transition_identity"
        )
        _exact_optional_sha256(
            self.execution_receipt_identity, "event.execution_receipt_identity"
        )
        _exact_optional_int(self.requested_tick, "event.requested_tick")
        _exact_optional_int(self.applied_tick, "event.applied_tick")
        _exact_int(self.remaining_ticks, "event.remaining_ticks")
        if (self.requested_tick is None) != (self.applied_tick is None):
            raise C8TimedSessionRuntimeError("runtime event requested/applied tick必须同时存在")
        if self.event_kind in {
            RuntimeEventKindV1.TIME_INPUT_ACCEPTED,
            RuntimeEventKindV1.DEADLINE_DERIVED,
        }:
            if self.input_identity is None or self.requested_tick is None:
                raise C8TimedSessionRuntimeError("time/deadline event缺少input/tick binding")
        elif self.requested_tick is not None:
            raise C8TimedSessionRuntimeError("非time event禁止携带requested/applied tick")
        if (
            self.event_kind
            not in {
                RuntimeEventKindV1.TIME_INPUT_ACCEPTED,
                RuntimeEventKindV1.DEADLINE_DERIVED,
            }
            and self.input_identity is not None
        ):
            raise C8TimedSessionRuntimeError("非time/deadline event禁止input identity")
        if self.event_kind is RuntimeEventKindV1.DEADLINE_DERIVED:
            if self.derived_deadline_identity is None:
                raise C8TimedSessionRuntimeError("DEADLINE_DERIVED缺少derived identity")
        elif self.event_kind is RuntimeEventKindV1.WINDOW_CLOSED_BY_TIMEOUT:
            if self.derived_deadline_identity is None or self.input_identity is not None:
                raise C8TimedSessionRuntimeError("timeout close必须只绑定derived deadline")
        elif self.derived_deadline_identity is not None:
            raise C8TimedSessionRuntimeError("该event kind禁止derived deadline identity")
        if self.event_kind in {
            RuntimeEventKindV1.MULTI_STEP_CONTINUED,
            RuntimeEventKindV1.TIMEOUT_MULTI_STEP_CONTINUED,
        }:
            if self.logical_step_identity is None:
                raise C8TimedSessionRuntimeError("multi-step event缺少logical step identity")
        elif self.logical_step_identity is not None:
            raise C8TimedSessionRuntimeError("非multi-step event禁止logical step identity")
        if self.event_kind in {
            RuntimeEventKindV1.INNER_SIGNED_ACTION_FORWARDED,
            RuntimeEventKindV1.TIMEOUT_SIGNED_ACTION_FORWARDED,
        }:
            if self.inner_transition_identity is None:
                raise C8TimedSessionRuntimeError(
                    "inner action event缺少transition identity"
                )
        elif self.inner_transition_identity is not None:
            raise C8TimedSessionRuntimeError(
                "非inner action event禁止inner transition identity"
            )
        receipt_event_kinds = {
            RuntimeEventKindV1.TIMEOUT_SIGNED_ACTION_FORWARDED,
            RuntimeEventKindV1.TIMEOUT_MULTI_STEP_CONTINUED,
            RuntimeEventKindV1.WINDOW_CLOSED_BY_TIMEOUT,
        }
        if self.event_kind in receipt_event_kinds:
            if self.execution_receipt_identity is None:
                raise C8TimedSessionRuntimeError(
                    "timeout receipt-bound event缺少execution receipt identity"
                )
        elif self.execution_receipt_identity is not None:
            raise C8TimedSessionRuntimeError(
                "非timeout receipt-bound event禁止execution receipt identity"
            )
        _assert_identity(self.event_identity, self._identity_material(), "event_identity")

    def _identity_material(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "contract_version": self.contract_version,
            "event_sequence": self.event_sequence,
            "event_kind": self.event_kind.value,
            "runtime_instance_identity": self.runtime_instance_identity,
            "tick": self.tick,
            "window_id": self.window_id,
            "related_window_id": self.related_window_id,
            "actor_id": self.actor_id,
            "decision_identity": self.decision_identity,
            "obligation_identity": self.obligation_identity,
            "window_state_identity": self.window_state_identity,
            "before_virtual_state_identity": self.before_virtual_state_identity,
            "after_virtual_state_identity": self.after_virtual_state_identity,
            "input_identity": self.input_identity,
            "derived_deadline_identity": self.derived_deadline_identity,
            "logical_step_identity": self.logical_step_identity,
            "inner_transition_identity": self.inner_transition_identity,
            "execution_receipt_identity": self.execution_receipt_identity,
            "requested_tick": self.requested_tick,
            "applied_tick": self.applied_tick,
            "remaining_ticks": self.remaining_ticks,
            "previous_event_identity": self.previous_event_identity,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._identity_material(), "event_identity": self.event_identity}

    @classmethod
    def build(
        cls,
        *,
        event_sequence: int,
        event_kind: RuntimeEventKindV1,
        runtime_instance_identity: str,
        tick: int,
        window: TimedDecisionWindowV1,
        related_window_id: str | None,
        before_virtual_state_identity: str,
        after_virtual_state_identity: str,
        input_identity: str | None,
        derived_deadline_identity: str | None,
        logical_step_identity: str | None,
        inner_transition_identity: str | None,
        execution_receipt_identity: str | None = None,
        requested_tick: int | None,
        applied_tick: int | None,
        previous_event_identity: str,
    ) -> "RuntimeEventV1":
        if type(event_kind) is not RuntimeEventKindV1:
            raise C8TimedSessionRuntimeError("runtime event kind类型不正确")
        if type(window) is not TimedDecisionWindowV1:
            raise C8TimedSessionRuntimeError("runtime event必须绑定C8-A window")
        material = {
            "schema": RUNTIME_EVENT_SCHEMA,
            "contract_version": 1,
            "event_sequence": event_sequence,
            "event_kind": event_kind.value,
            "runtime_instance_identity": runtime_instance_identity,
            "tick": tick,
            "window_id": window.window_id,
            "related_window_id": related_window_id,
            "actor_id": window.actor_id,
            "decision_identity": window.decision_identity,
            "obligation_identity": window.obligation_identity,
            "window_state_identity": window.window_state_identity,
            "before_virtual_state_identity": before_virtual_state_identity,
            "after_virtual_state_identity": after_virtual_state_identity,
            "input_identity": input_identity,
            "derived_deadline_identity": derived_deadline_identity,
            "logical_step_identity": logical_step_identity,
            "inner_transition_identity": inner_transition_identity,
            "execution_receipt_identity": execution_receipt_identity,
            "requested_tick": requested_tick,
            "applied_tick": applied_tick,
            "remaining_ticks": window.remaining_ticks,
            "previous_event_identity": previous_event_identity,
        }
        return cls(
            schema=RUNTIME_EVENT_SCHEMA,
            contract_version=1,
            event_sequence=event_sequence,
            event_kind=event_kind,
            runtime_instance_identity=runtime_instance_identity,
            tick=tick,
            window_id=window.window_id,
            related_window_id=related_window_id,
            actor_id=window.actor_id,
            decision_identity=window.decision_identity,
            obligation_identity=window.obligation_identity,
            window_state_identity=window.window_state_identity,
            before_virtual_state_identity=before_virtual_state_identity,
            after_virtual_state_identity=after_virtual_state_identity,
            input_identity=input_identity,
            derived_deadline_identity=derived_deadline_identity,
            logical_step_identity=logical_step_identity,
            inner_transition_identity=inner_transition_identity,
            execution_receipt_identity=execution_receipt_identity,
            requested_tick=requested_tick,
            applied_tick=applied_tick,
            remaining_ticks=window.remaining_ticks,
            previous_event_identity=previous_event_identity,
            event_identity=_canonical_sha256(material),
        )

    @classmethod
    def from_dict(cls, value: object) -> "RuntimeEventV1":
        data = _exact_dict(value, "RuntimeEventV1")
        fields = frozenset(
            {
                "schema",
                "contract_version",
                "event_sequence",
                "event_kind",
                "runtime_instance_identity",
                "tick",
                "window_id",
                "related_window_id",
                "actor_id",
                "decision_identity",
                "obligation_identity",
                "window_state_identity",
                "before_virtual_state_identity",
                "after_virtual_state_identity",
                "input_identity",
                "derived_deadline_identity",
                "logical_step_identity",
                "inner_transition_identity",
                "execution_receipt_identity",
                "requested_tick",
                "applied_tick",
                "remaining_ticks",
                "previous_event_identity",
                "event_identity",
            }
        )
        _exact_fields(data, fields, "RuntimeEventV1")
        return cls(
            schema=_exact_text(data["schema"], "event.schema"),
            contract_version=_exact_int(data["contract_version"], "contract_version"),
            event_sequence=_exact_int(data["event_sequence"], "event_sequence"),
            event_kind=_exact_enum(data["event_kind"], RuntimeEventKindV1, "event_kind"),
            runtime_instance_identity=_exact_sha256(
                data["runtime_instance_identity"], "runtime_instance_identity"
            ),
            tick=_exact_int(data["tick"], "tick"),
            window_id=_exact_text(data["window_id"], "window_id"),
            related_window_id=_exact_optional_text(
                data["related_window_id"], "related_window_id"
            ),
            actor_id=_exact_text_id(data["actor_id"], "actor_id"),
            decision_identity=_exact_sha256(
                data["decision_identity"], "decision_identity"
            ),
            obligation_identity=_exact_sha256(
                data["obligation_identity"], "obligation_identity"
            ),
            window_state_identity=_exact_sha256(
                data["window_state_identity"], "window_state_identity"
            ),
            before_virtual_state_identity=_exact_sha256(
                data["before_virtual_state_identity"], "before_virtual_state_identity"
            ),
            after_virtual_state_identity=_exact_sha256(
                data["after_virtual_state_identity"], "after_virtual_state_identity"
            ),
            input_identity=_exact_optional_sha256(
                data["input_identity"], "input_identity"
            ),
            derived_deadline_identity=_exact_optional_sha256(
                data["derived_deadline_identity"], "derived_deadline_identity"
            ),
            logical_step_identity=_exact_optional_sha256(
                data["logical_step_identity"], "logical_step_identity"
            ),
            inner_transition_identity=_exact_optional_sha256(
                data["inner_transition_identity"], "inner_transition_identity"
            ),
            execution_receipt_identity=_exact_optional_sha256(
                data["execution_receipt_identity"], "execution_receipt_identity"
            ),
            requested_tick=_exact_optional_int(data["requested_tick"], "requested_tick"),
            applied_tick=_exact_optional_int(data["applied_tick"], "applied_tick"),
            remaining_ticks=_exact_int(data["remaining_ticks"], "remaining_ticks"),
            previous_event_identity=_exact_sha256(
                data["previous_event_identity"], "previous_event_identity"
            ),
            event_identity=_exact_sha256(data["event_identity"], "event_identity"),
        )


def _event_chain_genesis(runtime_instance_identity: str) -> str:
    return _canonical_sha256(
        {
            "runtime_contract_identity": C8_B_RUNTIME_CONTRACT_IDENTITY_V1,
            "runtime_instance_identity": runtime_instance_identity,
            "chain": "OUTER_EVENT_GENESIS",
        }
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class TimedSessionOuterStateV1:
    schema: str
    contract_version: int
    runtime_id: str
    runtime_instance_identity: str
    instance_nonce_identity: str
    contract_latch: C8BCurrentContractLatchV1
    input_source_id: str
    driver_authority_identity: str
    input_authenticator_identity: str
    inner_adapter_identity: str
    inner_session_binding_identity: str
    inner_public_state_identity: str
    inner_authoritative_state_identity: str
    virtual_time_state: VirtualTimeStateV1
    input_records: tuple[AcceptedVirtualTimeInputV1, ...]
    input_chain_tip: str
    window_open_state_origins: tuple[str, ...]
    logical_obligations: tuple[LogicalObligationProgressV1, ...]
    seen_logical_obligation_identities: tuple[str, ...]
    pending_deadline: PendingDerivedDeadlineV1 | None
    runtime_events: tuple[RuntimeEventV1, ...]
    event_chain_tip: str
    state_revision: int
    state_identity: str

    def __post_init__(self) -> None:
        if self.schema != OUTER_STATE_SCHEMA or self.contract_version != 1:
            raise C8TimedSessionRuntimeError("outer state schema/version不匹配")
        if self.runtime_id != C8_B_RUNTIME_ID:
            raise C8TimedSessionRuntimeError("runtime_id不匹配")
        for label in (
            "runtime_instance_identity",
            "instance_nonce_identity",
            "driver_authority_identity",
            "input_authenticator_identity",
            "inner_adapter_identity",
            "inner_session_binding_identity",
            "inner_public_state_identity",
            "inner_authoritative_state_identity",
        ):
            _exact_sha256(getattr(self, label), label)
        _exact_text_id(self.input_source_id, "input_source_id")
        expected_instance_identity = _canonical_sha256(
            {
                "runtime_contract_identity": C8_B_RUNTIME_CONTRACT_IDENTITY_V1,
                "instance_nonce_identity": self.instance_nonce_identity,
                "input_source_id": self.input_source_id,
                "driver_authority_identity": self.driver_authority_identity,
                "input_authenticator_identity": self.input_authenticator_identity,
                "inner_adapter_identity": self.inner_adapter_identity,
                "inner_session_binding_identity": self.inner_session_binding_identity,
            }
        )
        if self.runtime_instance_identity != expected_instance_identity:
            raise C8TimedSessionRuntimeError("runtime_instance_identity与authority material不一致")
        if type(self.contract_latch) is not C8BCurrentContractLatchV1:
            raise C8TimedSessionRuntimeError("contract_latch类型不正确")
        if self.contract_latch != C8_B_CURRENT_CONTRACT_LATCH_V1:
            raise C8TimedSessionRuntimeError("current-contract latch drift")
        if type(self.virtual_time_state) is not VirtualTimeStateV1:
            raise C8TimedSessionRuntimeError("virtual_time_state类型不正确")
        if (
            self.virtual_time_state.clock_domain_identity
            != self.contract_latch.clock_domain_identity
        ):
            raise C8TimedSessionRuntimeError("virtual state clock domain drift")
        if self.virtual_time_state.globally_paused:
            raise C8TimedSessionRuntimeError(
                "C8-B child-only pause contract禁止注入manual/global clock pause"
            )
        if type(self.input_records) is not tuple or any(
            type(item) is not AcceptedVirtualTimeInputV1 for item in self.input_records
        ):
            raise C8TimedSessionRuntimeError("input_records必须是strict tuple")
        expected_input_tip = _input_chain_genesis(
            runtime_instance_identity=self.runtime_instance_identity,
            duration_profile_identity=self.contract_latch.duration_profile_identity,
            input_source_id=self.input_source_id,
            driver_authority_identity=self.driver_authority_identity,
        )
        derived_identities: list[str] = []
        for index, record in enumerate(self.input_records):
            if record.input_seq != index:
                raise C8TimedSessionRuntimeError("input record sequence必须从0连续递增")
            if record.previous_input_chain_tip != expected_input_tip:
                raise C8TimedSessionRuntimeError("input record chain发生splice/reorder")
            expected_input_tip = record.input_chain_link_identity
            if record.derived_deadline_identity is not None:
                derived_identities.append(record.derived_deadline_identity)
        if self.input_chain_tip != expected_input_tip:
            raise C8TimedSessionRuntimeError("input_chain_tip与records不一致")
        if self.virtual_time_state.next_input_seq != len(self.input_records):
            raise C8TimedSessionRuntimeError("C8-A next_input_seq与B input chain不一致")
        if tuple(derived_identities) != self.virtual_time_state.event_chain:
            raise C8TimedSessionRuntimeError("C8-A derived event chain与B input records不一致")
        if type(self.window_open_state_origins) is not tuple:
            raise C8TimedSessionRuntimeError("window_open_state_origins必须是strict tuple")
        for identity in self.window_open_state_origins:
            _exact_sha256(identity, "window pre-open state identity")
        if len(self.window_open_state_origins) != len(
            self.virtual_time_state.window_stack.windows
        ):
            raise C8TimedSessionRuntimeError("pre-open origins必须精确覆盖current window stack")
        if type(self.logical_obligations) is not tuple or any(
            type(item) is not LogicalObligationProgressV1
            for item in self.logical_obligations
        ):
            raise C8TimedSessionRuntimeError("logical_obligations必须是strict tuple")
        progress_by_window = {item.window_id: item for item in self.logical_obligations}
        if len(progress_by_window) != len(self.logical_obligations):
            raise C8TimedSessionRuntimeError("logical obligation progress禁止重复window")
        if len({item.obligation_identity for item in self.logical_obligations}) != len(
            self.logical_obligations
        ):
            raise C8TimedSessionRuntimeError("live logical multi-step obligation identity禁止重复")
        if type(self.seen_logical_obligation_identities) is not tuple:
            raise C8TimedSessionRuntimeError(
                "seen_logical_obligation_identities必须是strict tuple"
            )
        for identity in self.seen_logical_obligation_identities:
            _exact_sha256(identity, "seen logical obligation identity")
        if len(self.seen_logical_obligation_identities) != len(
            set(self.seen_logical_obligation_identities)
        ):
            raise C8TimedSessionRuntimeError("seen logical obligation identity禁止复用")
        if not set(item.obligation_identity for item in self.logical_obligations).issubset(
            self.seen_logical_obligation_identities
        ):
            raise C8TimedSessionRuntimeError("live logical obligation缺少seen registry binding")
        multi_windows = tuple(
            item
            for item in self.virtual_time_state.window_stack.windows
            if item.window_kind is TimedWindowKindV1.MULTI_STEP_OBLIGATION
        )
        if tuple(item.window_id for item in multi_windows) != tuple(
            item.window_id for item in self.logical_obligations
        ):
            raise C8TimedSessionRuntimeError("logical progress必须精确覆盖stack内multi-step windows")
        for window in multi_windows:
            progress = progress_by_window[window.window_id]
            if (
                progress.window_binding_identity != window.window_binding_identity
                or progress.obligation_identity != window.obligation_identity
            ):
                raise C8TimedSessionRuntimeError("logical progress与window binding不一致")
        active = self.virtual_time_state.window_stack.active_window
        deadline_is_due = (
            active is not None
            and active.status is TimedWindowStatusV1.ACTIVE
            and self.virtual_time_state.now_tick == active.deadline_at
        )
        if deadline_is_due != (self.pending_deadline is not None):
            raise C8TimedSessionRuntimeError(
                "exact-deadline ACTIVE window与pending deadline必须同时存在"
            )
        if self.pending_deadline is not None:
            if type(self.pending_deadline) is not PendingDerivedDeadlineV1:
                raise C8TimedSessionRuntimeError("pending_deadline类型不正确")
            if (
                active is None
                or self.virtual_time_state.now_tick != active.deadline_at
                or self.pending_deadline.window_id != active.window_id
                or self.pending_deadline.window_state_identity != active.window_state_identity
                or self.pending_deadline.deadline_at != active.deadline_at
                or not derived_identities
                or self.pending_deadline.derived_deadline_identity != derived_identities[-1]
                or self.pending_deadline.input_identity
                != self.input_records[-1].input_identity
            ):
                raise C8TimedSessionRuntimeError("pending deadline未绑定current exact-deadline window")
        if type(self.runtime_events) is not tuple or any(
            type(item) is not RuntimeEventV1 for item in self.runtime_events
        ):
            raise C8TimedSessionRuntimeError("runtime_events必须是strict tuple")
        expected_event_tip = _event_chain_genesis(self.runtime_instance_identity)
        previous_tick = 0
        input_events: list[RuntimeEventV1] = []
        deadline_events: list[RuntimeEventV1] = []
        previous_transition_after: str | None = None
        previous_transition_before: str | None = None
        for index, event in enumerate(self.runtime_events):
            if event.event_sequence != index:
                raise C8TimedSessionRuntimeError("runtime event sequence必须从0连续递增")
            if event.runtime_instance_identity != self.runtime_instance_identity:
                raise C8TimedSessionRuntimeError("runtime event绑定了其它runtime instance")
            if event.previous_event_identity != expected_event_tip:
                raise C8TimedSessionRuntimeError("runtime event chain发生splice/reorder")
            if (
                index == 0
                and event.before_virtual_state_identity
                != VirtualTimeStateV1.initial(CLOCK_DOMAIN_V1).state_identity
            ):
                raise C8TimedSessionRuntimeError(
                    "runtime event chain不是从initial virtual state开始"
                )
            if event.tick < previous_tick:
                raise C8TimedSessionRuntimeError("runtime event tick禁止倒退")
            previous_tick = event.tick
            expected_event_tip = event.event_identity
            if (
                previous_transition_before is not None
                and event.before_virtual_state_identity
                == previous_transition_before
                and event.after_virtual_state_identity == previous_transition_after
            ):
                pass
            else:
                if (
                    previous_transition_after is not None
                    and event.before_virtual_state_identity != previous_transition_after
                ):
                    raise C8TimedSessionRuntimeError(
                        "runtime event virtual-state transition chain不连续"
                    )
                previous_transition_before = event.before_virtual_state_identity
                previous_transition_after = event.after_virtual_state_identity
            if event.event_kind is RuntimeEventKindV1.TIME_INPUT_ACCEPTED:
                input_events.append(event)
            if event.event_kind is RuntimeEventKindV1.DEADLINE_DERIVED:
                deadline_events.append(event)
        if self.event_chain_tip != expected_event_tip:
            raise C8TimedSessionRuntimeError("event_chain_tip与runtime events不一致")
        if len(input_events) != len(self.input_records):
            raise C8TimedSessionRuntimeError("accepted input events与input records不一致")
        for event, record in zip(input_events, self.input_records, strict=True):
            if (
                event.input_identity != record.input_identity
                or event.requested_tick != record.requested_tick
                or event.applied_tick != record.applied_tick
                or event.before_virtual_state_identity
                != record.before_virtual_state_identity
                or event.after_virtual_state_identity != record.after_virtual_state_identity
            ):
                raise C8TimedSessionRuntimeError(
                    "accepted input event未精确绑定input record transition"
                )
        derived_records = tuple(
            item for item in self.input_records if item.derived_deadline_identity is not None
        )
        if len(deadline_events) != len(derived_records):
            raise C8TimedSessionRuntimeError("deadline events与derived input records不一致")
        for event, record in zip(deadline_events, derived_records, strict=True):
            if (
                event.input_identity != record.input_identity
                or event.derived_deadline_identity != record.derived_deadline_identity
                or event.requested_tick != record.requested_tick
                or event.applied_tick != record.applied_tick
                or event.before_virtual_state_identity
                != record.before_virtual_state_identity
                or event.after_virtual_state_identity != record.after_virtual_state_identity
            ):
                raise C8TimedSessionRuntimeError(
                    "deadline event未精确绑定derived input record transition"
                )
        if self.runtime_events:
            if previous_transition_after != self.virtual_time_state.state_identity:
                raise C8TimedSessionRuntimeError(
                    "runtime event chain tail未绑定current virtual state"
                )
        elif (
            self.virtual_time_state
            != VirtualTimeStateV1.initial(CLOCK_DOMAIN_V1)
        ):
            raise C8TimedSessionRuntimeError(
                "empty runtime event chain只能对应initial virtual state"
            )
        _exact_int(self.state_revision, "state_revision")
        if self.state_revision != len(self.runtime_events):
            raise C8TimedSessionRuntimeError("state_revision必须等于committed outer event count")
        _assert_identity(self.state_identity, self._identity_material(), "state_identity")

    def _identity_material(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "contract_version": self.contract_version,
            "runtime_id": self.runtime_id,
            "runtime_instance_identity": self.runtime_instance_identity,
            "instance_nonce_identity": self.instance_nonce_identity,
            "contract_latch": self.contract_latch.to_dict(),
            "input_source_id": self.input_source_id,
            "driver_authority_identity": self.driver_authority_identity,
            "input_authenticator_identity": self.input_authenticator_identity,
            "inner_adapter_identity": self.inner_adapter_identity,
            "inner_session_binding_identity": self.inner_session_binding_identity,
            "inner_public_state_identity": self.inner_public_state_identity,
            "inner_authoritative_state_identity": self.inner_authoritative_state_identity,
            "virtual_time_state": self.virtual_time_state.to_dict(),
            "input_records": [item.to_dict() for item in self.input_records],
            "input_chain_tip": self.input_chain_tip,
            "window_open_state_origins": list(self.window_open_state_origins),
            "logical_obligations": [item.to_dict() for item in self.logical_obligations],
            "seen_logical_obligation_identities": list(
                self.seen_logical_obligation_identities
            ),
            "pending_deadline": (
                None if self.pending_deadline is None else self.pending_deadline.to_dict()
            ),
            "runtime_events": [item.to_dict() for item in self.runtime_events],
            "event_chain_tip": self.event_chain_tip,
            "state_revision": self.state_revision,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._identity_material(), "state_identity": self.state_identity}

    @classmethod
    def build(
        cls,
        *,
        runtime_instance_identity: str,
        instance_nonce_identity: str,
        contract_latch: C8BCurrentContractLatchV1,
        input_source_id: str,
        driver_authority_identity: str,
        input_authenticator_identity: str,
        inner_adapter_identity: str,
        inner_session_binding_identity: str,
        inner_public_state_identity: str,
        inner_authoritative_state_identity: str,
        virtual_time_state: VirtualTimeStateV1,
        input_records: Sequence[AcceptedVirtualTimeInputV1],
        window_open_state_origins: Sequence[str],
        logical_obligations: Sequence[LogicalObligationProgressV1],
        seen_logical_obligation_identities: Sequence[str],
        pending_deadline: PendingDerivedDeadlineV1 | None,
        runtime_events: Sequence[RuntimeEventV1],
    ) -> "TimedSessionOuterStateV1":
        records = tuple(input_records)
        events = tuple(runtime_events)
        logical = tuple(logical_obligations)
        seen_logical = tuple(seen_logical_obligation_identities)
        origins = tuple(window_open_state_origins)
        input_tip = (
            records[-1].input_chain_link_identity
            if records
            else _input_chain_genesis(
                runtime_instance_identity=runtime_instance_identity,
                duration_profile_identity=contract_latch.duration_profile_identity,
                input_source_id=input_source_id,
                driver_authority_identity=driver_authority_identity,
            )
        )
        event_tip = (
            events[-1].event_identity
            if events
            else _event_chain_genesis(runtime_instance_identity)
        )
        material = {
            "schema": OUTER_STATE_SCHEMA,
            "contract_version": 1,
            "runtime_id": C8_B_RUNTIME_ID,
            "runtime_instance_identity": runtime_instance_identity,
            "instance_nonce_identity": instance_nonce_identity,
            "contract_latch": contract_latch.to_dict(),
            "input_source_id": input_source_id,
            "driver_authority_identity": driver_authority_identity,
            "input_authenticator_identity": input_authenticator_identity,
            "inner_adapter_identity": inner_adapter_identity,
            "inner_session_binding_identity": inner_session_binding_identity,
            "inner_public_state_identity": inner_public_state_identity,
            "inner_authoritative_state_identity": inner_authoritative_state_identity,
            "virtual_time_state": virtual_time_state.to_dict(),
            "input_records": [item.to_dict() for item in records],
            "input_chain_tip": input_tip,
            "window_open_state_origins": list(origins),
            "logical_obligations": [item.to_dict() for item in logical],
            "seen_logical_obligation_identities": list(seen_logical),
            "pending_deadline": (
                None if pending_deadline is None else pending_deadline.to_dict()
            ),
            "runtime_events": [item.to_dict() for item in events],
            "event_chain_tip": event_tip,
            "state_revision": len(events),
        }
        return cls(
            schema=OUTER_STATE_SCHEMA,
            contract_version=1,
            runtime_id=C8_B_RUNTIME_ID,
            runtime_instance_identity=runtime_instance_identity,
            instance_nonce_identity=instance_nonce_identity,
            contract_latch=contract_latch,
            input_source_id=input_source_id,
            driver_authority_identity=driver_authority_identity,
            input_authenticator_identity=input_authenticator_identity,
            inner_adapter_identity=inner_adapter_identity,
            inner_session_binding_identity=inner_session_binding_identity,
            inner_public_state_identity=inner_public_state_identity,
            inner_authoritative_state_identity=inner_authoritative_state_identity,
            virtual_time_state=virtual_time_state,
            input_records=records,
            input_chain_tip=input_tip,
            window_open_state_origins=origins,
            logical_obligations=logical,
            seen_logical_obligation_identities=seen_logical,
            pending_deadline=pending_deadline,
            runtime_events=events,
            event_chain_tip=event_tip,
            state_revision=len(events),
            state_identity=_canonical_sha256(material),
        )

    @classmethod
    def from_dict(cls, value: object) -> "TimedSessionOuterStateV1":
        data = _exact_dict(value, "TimedSessionOuterStateV1")
        fields = frozenset(
            {
                "schema",
                "contract_version",
                "runtime_id",
                "runtime_instance_identity",
                "instance_nonce_identity",
                "contract_latch",
                "input_source_id",
                "driver_authority_identity",
                "input_authenticator_identity",
                "inner_adapter_identity",
                "inner_session_binding_identity",
                "inner_public_state_identity",
                "inner_authoritative_state_identity",
                "virtual_time_state",
                "input_records",
                "input_chain_tip",
                "window_open_state_origins",
                "logical_obligations",
                "seen_logical_obligation_identities",
                "pending_deadline",
                "runtime_events",
                "event_chain_tip",
                "state_revision",
                "state_identity",
            }
        )
        _exact_fields(data, fields, "TimedSessionOuterStateV1")
        pending_raw = data["pending_deadline"]
        return cls(
            schema=_exact_text(data["schema"], "state.schema"),
            contract_version=_exact_int(data["contract_version"], "contract_version"),
            runtime_id=_exact_text(data["runtime_id"], "runtime_id"),
            runtime_instance_identity=_exact_sha256(
                data["runtime_instance_identity"], "runtime_instance_identity"
            ),
            instance_nonce_identity=_exact_sha256(
                data["instance_nonce_identity"], "instance_nonce_identity"
            ),
            contract_latch=C8BCurrentContractLatchV1.from_dict(data["contract_latch"]),
            input_source_id=_exact_text_id(data["input_source_id"], "input_source_id"),
            driver_authority_identity=_exact_sha256(
                data["driver_authority_identity"], "driver_authority_identity"
            ),
            input_authenticator_identity=_exact_sha256(
                data["input_authenticator_identity"], "input_authenticator_identity"
            ),
            inner_adapter_identity=_exact_sha256(
                data["inner_adapter_identity"], "inner_adapter_identity"
            ),
            inner_session_binding_identity=_exact_sha256(
                data["inner_session_binding_identity"], "inner_session_binding_identity"
            ),
            inner_public_state_identity=_exact_sha256(
                data["inner_public_state_identity"], "inner_public_state_identity"
            ),
            inner_authoritative_state_identity=_exact_sha256(
                data["inner_authoritative_state_identity"],
                "inner_authoritative_state_identity",
            ),
            virtual_time_state=VirtualTimeStateV1.from_dict(data["virtual_time_state"]),
            input_records=tuple(
                AcceptedVirtualTimeInputV1.from_dict(item)
                for item in _exact_list(data["input_records"], "input_records")
            ),
            input_chain_tip=_exact_sha256(data["input_chain_tip"], "input_chain_tip"),
            window_open_state_origins=tuple(
                _exact_sha256(item, "window_open_state_origins[]")
                for item in _exact_list(
                    data["window_open_state_origins"], "window_open_state_origins"
                )
            ),
            logical_obligations=tuple(
                LogicalObligationProgressV1.from_dict(item)
                for item in _exact_list(
                    data["logical_obligations"], "logical_obligations"
                )
            ),
            seen_logical_obligation_identities=tuple(
                _exact_sha256(item, "seen_logical_obligation_identities[]")
                for item in _exact_list(
                    data["seen_logical_obligation_identities"],
                    "seen_logical_obligation_identities",
                )
            ),
            pending_deadline=(
                None
                if pending_raw is None
                else PendingDerivedDeadlineV1.from_dict(pending_raw)
            ),
            runtime_events=tuple(
                RuntimeEventV1.from_dict(item)
                for item in _exact_list(data["runtime_events"], "runtime_events")
            ),
            event_chain_tip=_exact_sha256(data["event_chain_tip"], "event_chain_tip"),
            state_revision=_exact_int(data["state_revision"], "state_revision"),
            state_identity=_exact_sha256(data["state_identity"], "state_identity"),
        )


class TimedSessionInnerAdapterV1(Protocol):
    """Minimal inner authority seam; no legal-action or private projection API."""

    def adapter_identity_v1(self) -> str: ...

    def session_binding_identity_v1(self) -> str: ...

    def public_state_identity_v1(self) -> str: ...

    def authoritative_state_identity_v1(self) -> str: ...

    def capture_transaction_snapshot_v1(self) -> object: ...

    def snapshot_token_identity_v1(self, token: object) -> str: ...

    def restore_transaction_snapshot_v1(self, token: object) -> None: ...

    def apply_signed_action_id_v1(self, signed_action_id: str) -> None: ...


class VirtualTimeInputAuthenticatorV1(Protocol):
    """External one-shot time/timeout authority, independent from outer rollback."""

    def authenticator_identity_v1(self) -> str: ...

    def anti_replay_state_identity_v1(self) -> str: ...

    def verify_and_consume_advance_authorization_v1(
        self,
        advance_input: VirtualTimeAdvanceInputV1,
        expected_request_binding_identity: str,
    ) -> bool: ...

    def verify_and_consume_timeout_action_authorization_v1(
        self,
        signed_action_id: str,
        authorization_evidence_identity: str,
        expected_request_binding_identity: str,
    ) -> bool: ...


@dataclass(frozen=True, slots=True, kw_only=True)
class TimedSessionTransactionSnapshotV1:
    schema: str
    contract_version: int
    runtime_instance_identity: str
    outer_state: TimedSessionOuterStateV1
    virtual_time_snapshot: VirtualTimeTransactionSnapshotV1
    inner_adapter_identity: str
    inner_session_binding_identity: str
    inner_snapshot_token: object = field(repr=False, compare=False)
    inner_snapshot_identity: str
    owner_guard: object = field(repr=False, compare=False)
    snapshot_identity: str

    def __post_init__(self) -> None:
        if self.schema != TRANSACTION_SNAPSHOT_SCHEMA or self.contract_version != 1:
            raise C8TimedSessionRuntimeError("transaction snapshot schema/version不匹配")
        _exact_sha256(self.runtime_instance_identity, "snapshot.runtime_instance_identity")
        if type(self.outer_state) is not TimedSessionOuterStateV1:
            raise C8TimedSessionRuntimeError("snapshot outer_state类型不正确")
        if type(self.virtual_time_snapshot) is not VirtualTimeTransactionSnapshotV1:
            raise C8TimedSessionRuntimeError("snapshot virtual_time_snapshot类型不正确")
        if self.runtime_instance_identity != self.outer_state.runtime_instance_identity:
            raise C8TimedSessionRuntimeError("snapshot runtime binding不一致")
        if (
            self.virtual_time_snapshot.virtual_time_state
            != self.outer_state.virtual_time_state
            or self.virtual_time_snapshot.active_fallback_chain is not None
        ):
            raise C8TimedSessionRuntimeError("snapshot C8-A state不一致或提前携带C8-C chain")
        _exact_sha256(self.inner_adapter_identity, "snapshot.inner_adapter_identity")
        _exact_sha256(
            self.inner_session_binding_identity,
            "snapshot.inner_session_binding_identity",
        )
        if (
            self.inner_adapter_identity != self.outer_state.inner_adapter_identity
            or self.inner_session_binding_identity
            != self.outer_state.inner_session_binding_identity
        ):
            raise C8TimedSessionRuntimeError("snapshot inner binding与outer state不一致")
        _exact_sha256(self.inner_snapshot_identity, "inner_snapshot_identity")
        _assert_identity(self.snapshot_identity, self._identity_material(), "snapshot_identity")

    def _identity_material(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "contract_version": self.contract_version,
            "runtime_instance_identity": self.runtime_instance_identity,
            "outer_state": self.outer_state.to_dict(),
            "virtual_time_snapshot": self.virtual_time_snapshot.to_dict(),
            "inner_adapter_identity": self.inner_adapter_identity,
            "inner_session_binding_identity": self.inner_session_binding_identity,
            "inner_snapshot_identity": self.inner_snapshot_identity,
            "opaque_inner_token_serialized": False,
            "live_owner_guard_bound": True,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class TimedRuntimeAdvanceResultV1:
    state: TimedSessionOuterStateV1
    derived_deadline: DerivedDeadlineReachedV1 | None
    requested_tick: int
    applied_tick: int
    consumed_ticks: int
    unconsumed_ticks: int


@dataclass(frozen=True, slots=True, kw_only=True)
class RollbackCancellationReceiptV1:
    schema: str
    contract_version: int
    runtime_instance_identity: str
    cancelled_window_ref_identity: str
    before_state_identity: str
    restored_state_identity: str
    committed_cancel_event: bool
    receipt_identity: str

    def __post_init__(self) -> None:
        if self.schema != CANCELLATION_RECEIPT_SCHEMA or self.contract_version != 1:
            raise C8TimedSessionRuntimeError("cancellation receipt schema/version不匹配")
        for label in (
            "runtime_instance_identity",
            "cancelled_window_ref_identity",
            "before_state_identity",
            "restored_state_identity",
        ):
            _exact_sha256(getattr(self, label), label)
        if type(self.committed_cancel_event) is not bool or self.committed_cancel_event:
            raise C8TimedSessionRuntimeError("rollback cancel禁止伪造committed CANCEL event")
        _assert_identity(self.receipt_identity, self._identity_material(), "receipt_identity")

    def _identity_material(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "contract_version": self.contract_version,
            "runtime_instance_identity": self.runtime_instance_identity,
            "cancelled_window_ref_identity": self.cancelled_window_ref_identity,
            "before_state_identity": self.before_state_identity,
            "restored_state_identity": self.restored_state_identity,
            "committed_cancel_event": self.committed_cancel_event,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class TimedSessionPublicProjectionV1:
    schema: str
    contract_version: int
    runtime_id: str
    runtime_contract_identity: str
    runtime_instance_identity: str
    inner_public_state_identity: str
    now_tick: int
    window_depth: int
    active_window_id: str | None
    active_actor_id: str | None
    active_window_kind: str | None
    active_deadline_at: int | None
    active_remaining_ticks: int | None
    active_decision_identity: str | None
    active_obligation_identity: str | None
    action_eligibility: str | None
    input_chain_tip: str
    event_chain_tip: str
    projection_identity: str

    def __post_init__(self) -> None:
        if self.schema != PUBLIC_PROJECTION_SCHEMA or self.contract_version != 1:
            raise C8TimedSessionRuntimeError("public projection schema/version不匹配")
        if self.runtime_id != C8_B_RUNTIME_ID:
            raise C8TimedSessionRuntimeError("public projection runtime_id不匹配")
        for label in (
            "runtime_contract_identity",
            "runtime_instance_identity",
            "inner_public_state_identity",
            "input_chain_tip",
            "event_chain_tip",
        ):
            _exact_sha256(getattr(self, label), label)
        _exact_int(self.now_tick, "now_tick")
        _exact_int(self.window_depth, "window_depth")
        optional_values = (
            self.active_window_id,
            self.active_actor_id,
            self.active_window_kind,
            self.active_decision_identity,
            self.active_obligation_identity,
            self.action_eligibility,
        )
        for index, value in enumerate(optional_values):
            _exact_optional_text(value, f"active_optional[{index}]")
        _exact_optional_int(self.active_deadline_at, "active_deadline_at")
        _exact_optional_int(self.active_remaining_ticks, "active_remaining_ticks")
        if self.window_depth == 0 and any(value is not None for value in optional_values):
            raise C8TimedSessionRuntimeError("empty projection禁止active window字段")
        if self.window_depth == 0 and (
            self.active_deadline_at is not None or self.active_remaining_ticks is not None
        ):
            raise C8TimedSessionRuntimeError("empty projection禁止active tick字段")
        _assert_identity(
            self.projection_identity,
            self._identity_material(),
            "projection_identity",
        )

    def _identity_material(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "contract_version": self.contract_version,
            "runtime_id": self.runtime_id,
            "runtime_contract_identity": self.runtime_contract_identity,
            "runtime_instance_identity": self.runtime_instance_identity,
            "inner_public_state_identity": self.inner_public_state_identity,
            "now_tick": self.now_tick,
            "window_depth": self.window_depth,
            "active_window_id": self.active_window_id,
            "active_actor_id": self.active_actor_id,
            "active_window_kind": self.active_window_kind,
            "active_deadline_at": self.active_deadline_at,
            "active_remaining_ticks": self.active_remaining_ticks,
            "active_decision_identity": self.active_decision_identity,
            "active_obligation_identity": self.active_obligation_identity,
            "action_eligibility": self.action_eligibility,
            "input_chain_tip": self.input_chain_tip,
            "event_chain_tip": self.event_chain_tip,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._identity_material(), "projection_identity": self.projection_identity}

    @classmethod
    def from_state(cls, state: TimedSessionOuterStateV1) -> "TimedSessionPublicProjectionV1":
        active = state.virtual_time_state.window_stack.active_window
        eligibility = (
            None
            if active is None
            else deadline_precedence_v1(active, state.virtual_time_state.now_tick).value
        )
        material = {
            "schema": PUBLIC_PROJECTION_SCHEMA,
            "contract_version": 1,
            "runtime_id": C8_B_RUNTIME_ID,
            "runtime_contract_identity": C8_B_RUNTIME_CONTRACT_IDENTITY_V1,
            "runtime_instance_identity": state.runtime_instance_identity,
            "inner_public_state_identity": state.inner_public_state_identity,
            "now_tick": state.virtual_time_state.now_tick,
            "window_depth": len(state.virtual_time_state.window_stack.windows),
            "active_window_id": None if active is None else active.window_id,
            "active_actor_id": None if active is None else active.actor_id,
            "active_window_kind": None if active is None else active.window_kind.value,
            "active_deadline_at": None if active is None else active.deadline_at,
            "active_remaining_ticks": None if active is None else active.remaining_ticks,
            "active_decision_identity": None if active is None else active.decision_identity,
            "active_obligation_identity": None if active is None else active.obligation_identity,
            "action_eligibility": eligibility,
            "input_chain_tip": state.input_chain_tip,
            "event_chain_tip": state.event_chain_tip,
        }
        return cls(**material, projection_identity=_canonical_sha256(material))


class C8TimedSessionRuntimeV1:
    """Single live owner of one C8-B outer state and one bound inner adapter."""

    __slots__ = (
        "__state",
        "__adapter",
        "__input_authenticator",
        "__owner_guard",
        "__callback_busy",
        "__active_controller_callback_guard",
        "__poisoned",
        "__auth_ledger_identity",
        "__operation_attempt_epoch",
        "__operation_attempt_chain_tip",
        "__operation_attempt_records",
        "__operation_attempt_validation_cache",
        "__next_controller_callback_generation",
        "__issued_controller_callback_leases",
        "__issued_controller_callback_guards",
        "__released_controller_callback_guard_identities",
        "__issued_controller_callback_guard_results",
        "__next_pending_issuance_capability_generation",
        "__issued_pending_issuance_capabilities",
        "__issued_snapshots",
        "__issued_timeout_commitments",
        "__issued_timeout_receipts",
        "__consumed_timeout_receipt_identities",
        "__pending_timeout_receipt_identity",
        "__timeout_receipt_chain_tip",
        "__next_timeout_receipt_sequence",
    )

    def __init__(
        self,
        *,
        inner_adapter: TimedSessionInnerAdapterV1,
        input_authenticator: VirtualTimeInputAuthenticatorV1,
        instance_nonce_identity: str,
        input_source_id: str,
        driver_authority_identity: str,
    ) -> None:
        nonce = _exact_sha256(instance_nonce_identity, "instance_nonce_identity")
        source = _exact_text_id(input_source_id, "input_source_id")
        authority = _exact_sha256(
            driver_authority_identity, "driver_authority_identity"
        )
        self.__adapter = inner_adapter
        self.__input_authenticator = input_authenticator
        self.__owner_guard = object()
        self.__callback_busy = False
        self.__active_controller_callback_guard: (
            ControllerCallbackGuardTokenV1 | None
        ) = None
        self.__poisoned = False
        self.__operation_attempt_epoch = 0
        self.__operation_attempt_chain_tip = ""
        self.__operation_attempt_records: list[
            tuple[int, str, str | None, str]
        ] = []
        # Non-authorizing, runtime-local memo of successfully verified immutable
        # records. It is neither exported nor restored by gameplay rollback.
        self.__operation_attempt_validation_cache: list[
            tuple[object, tuple[str, str, str, object], str, str] | None
        ] = []
        self.__next_controller_callback_generation = 0
        self.__issued_controller_callback_leases: dict[
            int, tuple[ControllerCallbackLeaseV1, str, str, bool]
        ] = {}
        self.__issued_controller_callback_guards: dict[
            int, tuple[ControllerCallbackGuardTokenV1, str]
        ] = {}
        self.__released_controller_callback_guard_identities: set[str] = set()
        self.__issued_controller_callback_guard_results: dict[
            int, tuple[ControllerCallbackGuardResultV1, str, bool]
        ] = {}
        self.__next_pending_issuance_capability_generation = 0
        self.__issued_pending_issuance_capabilities: dict[
            int,
            tuple[
                PendingTimeoutIssuanceCapabilityV1,
                str,
                PendingIssuanceCapabilityStatusV1,
                str | None,
            ],
        ] = {}
        self.__issued_snapshots: dict[
            int, tuple[TimedSessionTransactionSnapshotV1, str]
        ] = {}
        self.__issued_timeout_commitments: dict[
            int, tuple[TimeoutDueCommitmentV1, str, str]
        ] = {}
        self.__issued_timeout_receipts: dict[
            int, tuple[TimeoutActionExecutionReceiptV1, str]
        ] = {}
        self.__consumed_timeout_receipt_identities: set[str] = set()
        self.__pending_timeout_receipt_identity: str | None = None
        adapter_identity = self._adapter_sha("adapter_identity_v1")
        authenticator_identity = self._authenticator_sha("authenticator_identity_v1")
        self.__auth_ledger_identity = self._authenticator_sha(
            "anti_replay_state_identity_v1"
        )
        session_binding = self._adapter_sha("session_binding_identity_v1")
        public_identity = self._adapter_sha("public_state_identity_v1")
        authoritative_identity = self._adapter_sha("authoritative_state_identity_v1")
        instance_identity = _canonical_sha256(
            {
                "runtime_contract_identity": C8_B_RUNTIME_CONTRACT_IDENTITY_V1,
                "instance_nonce_identity": nonce,
                "input_source_id": source,
                "driver_authority_identity": authority,
                "input_authenticator_identity": authenticator_identity,
                "inner_adapter_identity": adapter_identity,
                "inner_session_binding_identity": session_binding,
            }
        )
        self.__timeout_receipt_chain_tip = _timeout_receipt_chain_genesis(
            instance_identity
        )
        self.__operation_attempt_chain_tip = _operation_attempt_chain_genesis(
            instance_identity
        )
        self.__next_timeout_receipt_sequence = 0
        self.__state = TimedSessionOuterStateV1.build(
            runtime_instance_identity=instance_identity,
            instance_nonce_identity=nonce,
            contract_latch=C8_B_CURRENT_CONTRACT_LATCH_V1,
            input_source_id=source,
            driver_authority_identity=authority,
            input_authenticator_identity=authenticator_identity,
            inner_adapter_identity=adapter_identity,
            inner_session_binding_identity=session_binding,
            inner_public_state_identity=public_identity,
            inner_authoritative_state_identity=authoritative_identity,
            virtual_time_state=VirtualTimeStateV1.initial(CLOCK_DOMAIN_V1),
            input_records=(),
            window_open_state_origins=(),
            logical_obligations=(),
            seen_logical_obligation_identities=(),
            pending_deadline=None,
            runtime_events=(),
        )

    @property
    def state(self) -> TimedSessionOuterStateV1:
        """Return trusted server-side state; this is not a public projection."""

        return self.__state

    def _validate_operation_attempt_evidence(self) -> None:
        if self.__operation_attempt_epoch != len(self.__operation_attempt_records):
            raise C8TimedSessionRuntimeError(
                "non-rollback operation-attempt epoch/history drift"
            )
        tip = _operation_attempt_chain_genesis(
            self.__state.runtime_instance_identity
        )
        cache = self.__operation_attempt_validation_cache
        domain = (
            OPERATION_ATTEMPT_CHAIN_SCHEMA,
            C8_B_RUNTIME_CONTRACT_IDENTITY_V1,
            self.__state.runtime_instance_identity,
            self.__owner_guard,
        )
        for expected_epoch, record in enumerate(
            self.__operation_attempt_records, start=1
        ):
            epoch, operation_name, active_guard_identity, record_identity = record
            if epoch != expected_epoch:
                raise C8TimedSessionRuntimeError(
                    "non-rollback operation-attempt epoch sequence drift"
                )
            operation = _exact_text_id(
                operation_name, "operation_attempt.operation_name"
            )
            guard_identity = _exact_optional_sha256(
                active_guard_identity,
                "operation_attempt.active_guard_identity",
            )
            # Keep the full prefix walk, field checks and chain comparison.
            # Object identity is safe only for exact tuples of immutable scalars;
            # legacy/malformed containers always take the original hash path.
            cacheable = (
                type(record) is tuple
                and type(epoch) is int
                and type(operation_name) is str
                and (active_guard_identity is None or type(active_guard_identity) is str)
                and type(record_identity) is str
            )
            index = expected_epoch - 1
            cached = cache[index] if index < len(cache) else None
            cache_hit = (cacheable and cached is not None and cached[0] is record
                         and cached[1] == domain and cached[2] == tip)
            if cache_hit:
                expected_identity = cached[3]
            else:
                expected_identity = _canonical_sha256({
                    "schema": OPERATION_ATTEMPT_CHAIN_SCHEMA,
                    "contract_version": 1,
                    "runtime_contract_identity": (
                        C8_B_RUNTIME_CONTRACT_IDENTITY_V1
                    ),
                    "runtime_instance_identity": (
                        self.__state.runtime_instance_identity
                    ),
                    "epoch": epoch,
                    "operation_name": operation,
                    "active_guard_identity": guard_identity,
                    "previous_attempt_identity": tip,
                })
            if record_identity != expected_identity:
                raise C8TimedSessionRuntimeError(
                    "non-rollback operation-attempt chain drift"
                )
            if not cache_hit:
                entry = (record, domain, tip, expected_identity) if cacheable else None
                if index < len(cache):
                    cache[index] = entry
                else:
                    cache.append(entry)
            tip = record_identity
        if self.__operation_attempt_chain_tip != tip:
            raise C8TimedSessionRuntimeError(
                "non-rollback operation-attempt chain tip drift"
            )

    def _record_public_operation_attempt(self, operation_name: str) -> None:
        """Record before validation; gameplay rollback never restores this chain."""

        self._validate_operation_attempt_evidence()
        operation = _exact_text_id(operation_name, "operation_name")
        active_guard_identity = (
            None
            if self.__active_controller_callback_guard is None
            else self.__active_controller_callback_guard.guard_identity
        )
        epoch = self.__operation_attempt_epoch + 1
        record_identity = _canonical_sha256(
            {
                "schema": OPERATION_ATTEMPT_CHAIN_SCHEMA,
                "contract_version": 1,
                "runtime_contract_identity": C8_B_RUNTIME_CONTRACT_IDENTITY_V1,
                "runtime_instance_identity": self.__state.runtime_instance_identity,
                "epoch": epoch,
                "operation_name": operation,
                "active_guard_identity": active_guard_identity,
                "previous_attempt_identity": self.__operation_attempt_chain_tip,
            }
        )
        self.__operation_attempt_records.append(
            (epoch, operation, active_guard_identity, record_identity)
        )
        self.__operation_attempt_epoch = epoch
        self.__operation_attempt_chain_tip = record_identity
        if self.__active_controller_callback_guard is not None:
            raise C8TimedSessionRuntimeError(
                "trusted controller callback期间检测到runtime mutating operation attempt"
            )

    def operation_attempt_epoch_v1(self) -> int:
        """Read the monotonic security epoch; it is not gameplay state."""

        self._validate_operation_attempt_evidence()
        return self.__operation_attempt_epoch

    def controller_callback_security_audit_v1(
        self,
    ) -> ControllerCallbackSecurityAuditV1:
        """Return a non-authorizing audit projection without any live token."""

        self._validate_operation_attempt_evidence()
        material = {
            "schema": CONTROLLER_CALLBACK_SECURITY_AUDIT_SCHEMA,
            "contract_version": 1,
            "runtime_contract_identity": C8_B_RUNTIME_CONTRACT_IDENTITY_V1,
            "runtime_instance_identity": self.__state.runtime_instance_identity,
            "operation_attempt_epoch": self.__operation_attempt_epoch,
            "operation_attempt_chain_tip": self.__operation_attempt_chain_tip,
            "guard_active": self.__active_controller_callback_guard is not None,
            "next_guard_generation": self.__next_controller_callback_generation,
            "authorizing_capability_exposed": False,
        }
        return ControllerCallbackSecurityAuditV1(
            schema=CONTROLLER_CALLBACK_SECURITY_AUDIT_SCHEMA,
            contract_version=1,
            runtime_contract_identity=C8_B_RUNTIME_CONTRACT_IDENTITY_V1,
            runtime_instance_identity=self.__state.runtime_instance_identity,
            operation_attempt_epoch=self.__operation_attempt_epoch,
            operation_attempt_chain_tip=self.__operation_attempt_chain_tip,
            guard_active=self.__active_controller_callback_guard is not None,
            next_guard_generation=self.__next_controller_callback_generation,
            audit_identity=_canonical_sha256(material),
        )

    def issue_controller_callback_lease_v1(
        self,
        ref: WindowAuthorityRefV1,
        *,
        timeout_due_commitment: TimeoutDueCommitmentV1,
        controller_identity: str,
        adapter_identity: str,
    ) -> ControllerCallbackLeaseV1:
        """Issue one live lease for one exact current timeout callback."""

        self._record_public_operation_attempt(
            "issue_controller_callback_lease_v1"
        )
        self._ensure_live_binding()
        active, pending = self._validate_timeout_due_commitment(
            ref, timeout_due_commitment
        )
        controller = _exact_sha256(controller_identity, "controller_identity")
        adapter = _exact_sha256(adapter_identity, "adapter_identity")
        generation = self.__next_controller_callback_generation
        lease_nonce_identity = _canonical_sha256(
            {
                "schema": CONTROLLER_CALLBACK_LEASE_SCHEMA,
                "runtime_contract_identity": C8_B_RUNTIME_CONTRACT_IDENTITY_V1,
                "runtime_instance_identity": self.__state.runtime_instance_identity,
                "controller_identity": controller,
                "adapter_identity": adapter,
                "window_authority_ref_identity": ref.authority_ref_identity,
                "timeout_due_commitment_identity": (
                    timeout_due_commitment.commitment_identity
                ),
                "pending_deadline_identity": pending.pending_identity,
                "lease_generation": generation,
                "operation_attempt_epoch_at_issue": (
                    self.__operation_attempt_epoch
                ),
                "operation_attempt_chain_tip_at_issue": (
                    self.__operation_attempt_chain_tip
                ),
            }
        )
        material = {
            "schema": CONTROLLER_CALLBACK_LEASE_SCHEMA,
            "contract_version": 1,
            "runtime_contract_identity": C8_B_RUNTIME_CONTRACT_IDENTITY_V1,
            "runtime_instance_identity": self.__state.runtime_instance_identity,
            "controller_identity": controller,
            "adapter_identity": adapter,
            "window_authority_ref_identity": ref.authority_ref_identity,
            "window_id": active.window_id,
            "timeout_due_commitment_identity": (
                timeout_due_commitment.commitment_identity
            ),
            "pending_deadline_identity": pending.pending_identity,
            "outer_state_identity_at_issue": self.__state.state_identity,
            "lease_generation": generation,
            "operation_attempt_epoch_at_issue": self.__operation_attempt_epoch,
            "lease_nonce_identity": lease_nonce_identity,
            "live_owner_guard_bound": True,
            "serializable_authority": False,
        }
        lease = ControllerCallbackLeaseV1(
            schema=CONTROLLER_CALLBACK_LEASE_SCHEMA,
            contract_version=1,
            runtime_contract_identity=C8_B_RUNTIME_CONTRACT_IDENTITY_V1,
            runtime_instance_identity=self.__state.runtime_instance_identity,
            controller_identity=controller,
            adapter_identity=adapter,
            window_authority_ref_identity=ref.authority_ref_identity,
            window_id=active.window_id,
            timeout_due_commitment_identity=(
                timeout_due_commitment.commitment_identity
            ),
            pending_deadline_identity=pending.pending_identity,
            outer_state_identity_at_issue=self.__state.state_identity,
            lease_generation=generation,
            operation_attempt_epoch_at_issue=self.__operation_attempt_epoch,
            lease_nonce_identity=lease_nonce_identity,
            lease_identity=_canonical_sha256(material),
            _owner_guard=self.__owner_guard,
        )
        self.__issued_controller_callback_leases[id(lease)] = (
            lease,
            lease.lease_identity,
            self.__state.state_identity,
            False,
        )
        self.__next_controller_callback_generation += 1
        return lease

    def _validate_controller_callback_lease(
        self, lease: ControllerCallbackLeaseV1
    ) -> tuple[ControllerCallbackLeaseV1, str, str, bool]:
        if type(lease) is not ControllerCallbackLeaseV1:
            raise C8TimedSessionRuntimeError(
                "controller callback begin需要strict runtime-issued lease"
            )
        issued = self.__issued_controller_callback_leases.get(id(lease))
        if (
            issued is None
            or issued[0] is not lease
            or issued[1] != lease.lease_identity
            or lease._owner_guard is not self.__owner_guard
        ):
            raise C8TimedSessionRuntimeError(
                "controller callback lease不是current wrapper实际签发的live object"
            )
        _assert_identity(
            lease.lease_identity,
            lease._identity_material(),
            "controller callback lease_identity",
        )
        if issued[3]:
            raise C8TimedSessionRuntimeError(
                "controller callback lease已经消费，禁止duplicate/replay"
            )
        if (
            issued[2] != self.__state.state_identity
            or lease.outer_state_identity_at_issue != self.__state.state_identity
            or lease.runtime_instance_identity
            != self.__state.runtime_instance_identity
            or lease.operation_attempt_epoch_at_issue + 1
            != self.__operation_attempt_epoch
        ):
            raise C8TimedSessionRuntimeError(
                "controller callback lease已stale或跨runtime/window lineage"
            )
        return issued

    def begin_controller_callback_guard_v1(
        self, lease: ControllerCallbackLeaseV1
    ) -> ControllerCallbackGuardTokenV1:
        """Consume a live lease and enter the shared non-reentrant callback guard."""

        self._record_public_operation_attempt(
            "begin_controller_callback_guard_v1"
        )
        self._ensure_live_binding()
        issued = self._validate_controller_callback_lease(lease)
        active = self.__state.virtual_time_state.window_stack.active_window
        pending = self.__state.pending_deadline
        if active is None or pending is None:
            raise C8TimedSessionRuntimeError(
                "controller callback guard需要current timeout window lineage"
            )
        ref = WindowAuthorityRefV1.from_window(
            self.__state.runtime_instance_identity, active
        )
        if (
            lease.window_authority_ref_identity != ref.authority_ref_identity
            or lease.window_id != active.window_id
            or lease.pending_deadline_identity != pending.pending_identity
        ):
            raise C8TimedSessionRuntimeError(
                "controller callback lease与current timeout lineage不一致"
            )
        guard_nonce_identity = _canonical_sha256(
            {
                "schema": CONTROLLER_CALLBACK_GUARD_SCHEMA,
                "runtime_contract_identity": C8_B_RUNTIME_CONTRACT_IDENTITY_V1,
                "runtime_instance_identity": self.__state.runtime_instance_identity,
                "lease_identity": lease.lease_identity,
                "guard_generation": lease.lease_generation,
                "operation_attempt_epoch_at_entry": (
                    self.__operation_attempt_epoch
                ),
                "operation_attempt_chain_tip_at_entry": (
                    self.__operation_attempt_chain_tip
                ),
            }
        )
        material = {
            "schema": CONTROLLER_CALLBACK_GUARD_SCHEMA,
            "contract_version": 1,
            "runtime_contract_identity": C8_B_RUNTIME_CONTRACT_IDENTITY_V1,
            "runtime_instance_identity": self.__state.runtime_instance_identity,
            "controller_identity": lease.controller_identity,
            "adapter_identity": lease.adapter_identity,
            "window_authority_ref_identity": lease.window_authority_ref_identity,
            "window_id": lease.window_id,
            "timeout_due_commitment_identity": (
                lease.timeout_due_commitment_identity
            ),
            "pending_deadline_identity": lease.pending_deadline_identity,
            "lease_identity": lease.lease_identity,
            "guard_generation": lease.lease_generation,
            "guard_nonce_identity": guard_nonce_identity,
            "operation_attempt_epoch_at_entry": self.__operation_attempt_epoch,
            "operation_attempt_chain_tip_at_entry": (
                self.__operation_attempt_chain_tip
            ),
            "outer_state_identity_at_entry": self.__state.state_identity,
            "live_owner_guard_bound": True,
            "serializable_authority": False,
        }
        token = ControllerCallbackGuardTokenV1(
            schema=CONTROLLER_CALLBACK_GUARD_SCHEMA,
            contract_version=1,
            runtime_contract_identity=C8_B_RUNTIME_CONTRACT_IDENTITY_V1,
            runtime_instance_identity=self.__state.runtime_instance_identity,
            controller_identity=lease.controller_identity,
            adapter_identity=lease.adapter_identity,
            window_authority_ref_identity=lease.window_authority_ref_identity,
            window_id=lease.window_id,
            timeout_due_commitment_identity=(
                lease.timeout_due_commitment_identity
            ),
            pending_deadline_identity=lease.pending_deadline_identity,
            lease_identity=lease.lease_identity,
            guard_generation=lease.lease_generation,
            guard_nonce_identity=guard_nonce_identity,
            operation_attempt_epoch_at_entry=self.__operation_attempt_epoch,
            operation_attempt_chain_tip_at_entry=(
                self.__operation_attempt_chain_tip
            ),
            outer_state_identity_at_entry=self.__state.state_identity,
            guard_identity=_canonical_sha256(material),
            _owner_guard=self.__owner_guard,
        )
        self.__issued_controller_callback_leases[id(lease)] = (
            issued[0], issued[1], issued[2], True
        )
        self.__issued_controller_callback_guards[id(token)] = (
            token,
            token.guard_identity,
        )
        self.__active_controller_callback_guard = token
        self.__callback_busy = True
        return token

    def _validate_controller_callback_guard_token(
        self, token: ControllerCallbackGuardTokenV1
    ) -> None:
        if type(token) is not ControllerCallbackGuardTokenV1:
            raise C8TimedSessionRuntimeError(
                "controller callback release需要strict guard token"
            )
        issued = self.__issued_controller_callback_guards.get(id(token))
        if (
            issued is None
            or issued[0] is not token
            or issued[1] != token.guard_identity
            or token._owner_guard is not self.__owner_guard
        ):
            raise C8TimedSessionRuntimeError(
                "controller callback guard token不是current wrapper实际签发"
            )
        _assert_identity(
            token.guard_identity,
            token._identity_material(),
            "controller callback guard_identity",
        )
        if token.guard_identity in self.__released_controller_callback_guard_identities:
            raise C8TimedSessionRuntimeError(
                "controller callback guard已经release，禁止duplicate/replay"
            )
        if self.__active_controller_callback_guard is not token:
            raise C8TimedSessionRuntimeError(
                "controller callback guard不是current active guard"
            )

    def _release_controller_callback_guard(
        self,
        token: ControllerCallbackGuardTokenV1,
        *,
        callback_completed: bool,
    ) -> ControllerCallbackGuardResultV1 | None:
        try:
            self._validate_controller_callback_guard_token(token)
        except Exception:
            self._record_public_operation_attempt(
                "invalid_controller_callback_guard_release_v1"
            )
            raise
        self._validate_operation_attempt_evidence()
        exit_epoch = self.__operation_attempt_epoch
        exit_tip = self.__operation_attempt_chain_tip
        self.__released_controller_callback_guard_identities.add(
            token.guard_identity
        )
        self.__active_controller_callback_guard = None
        self.__callback_busy = False
        if (
            exit_epoch != token.operation_attempt_epoch_at_entry
            or exit_tip != token.operation_attempt_chain_tip_at_entry
        ):
            raise C8TimedSessionRuntimeError(
                "controller callback guard检测到不可回退runtime operation attempt"
            )
        self._ensure_live_binding()
        if self.__state.state_identity != token.outer_state_identity_at_entry:
            raise C8TimedSessionRuntimeError(
                "controller callback期间outer state发生未授权变化"
            )
        active = self.__state.virtual_time_state.window_stack.active_window
        pending = self.__state.pending_deadline
        if (
            active is None
            or pending is None
            or token.window_id != active.window_id
            or token.window_authority_ref_identity
            != WindowAuthorityRefV1.from_window(
                self.__state.runtime_instance_identity, active
            ).authority_ref_identity
            or token.pending_deadline_identity != pending.pending_identity
        ):
            raise C8TimedSessionRuntimeError(
                "controller callback guard release timeout lineage drift"
            )
        if not callback_completed:
            return None
        material = {
            "schema": CONTROLLER_CALLBACK_GUARD_RESULT_SCHEMA,
            "contract_version": 1,
            "runtime_contract_identity": C8_B_RUNTIME_CONTRACT_IDENTITY_V1,
            "runtime_instance_identity": self.__state.runtime_instance_identity,
            "controller_identity": token.controller_identity,
            "adapter_identity": token.adapter_identity,
            "window_authority_ref_identity": token.window_authority_ref_identity,
            "window_id": token.window_id,
            "timeout_due_commitment_identity": (
                token.timeout_due_commitment_identity
            ),
            "pending_deadline_identity": token.pending_deadline_identity,
            "lease_identity": token.lease_identity,
            "guard_generation": token.guard_generation,
            "guard_identity": token.guard_identity,
            "operation_attempt_epoch_at_entry": (
                token.operation_attempt_epoch_at_entry
            ),
            "operation_attempt_epoch_at_exit": exit_epoch,
            "operation_attempt_chain_tip_at_entry": (
                token.operation_attempt_chain_tip_at_entry
            ),
            "operation_attempt_chain_tip_at_exit": exit_tip,
            "outer_state_identity_at_entry": token.outer_state_identity_at_entry,
            "outer_state_identity_at_exit": self.__state.state_identity,
            "callback_completed": True,
            "live_owner_guard_bound": True,
            "serializable_authority": False,
        }
        result = ControllerCallbackGuardResultV1(
            schema=CONTROLLER_CALLBACK_GUARD_RESULT_SCHEMA,
            contract_version=1,
            runtime_contract_identity=C8_B_RUNTIME_CONTRACT_IDENTITY_V1,
            runtime_instance_identity=self.__state.runtime_instance_identity,
            controller_identity=token.controller_identity,
            adapter_identity=token.adapter_identity,
            window_authority_ref_identity=token.window_authority_ref_identity,
            window_id=token.window_id,
            timeout_due_commitment_identity=(
                token.timeout_due_commitment_identity
            ),
            pending_deadline_identity=token.pending_deadline_identity,
            lease_identity=token.lease_identity,
            guard_generation=token.guard_generation,
            guard_identity=token.guard_identity,
            operation_attempt_epoch_at_entry=(
                token.operation_attempt_epoch_at_entry
            ),
            operation_attempt_epoch_at_exit=exit_epoch,
            operation_attempt_chain_tip_at_entry=(
                token.operation_attempt_chain_tip_at_entry
            ),
            operation_attempt_chain_tip_at_exit=exit_tip,
            outer_state_identity_at_entry=token.outer_state_identity_at_entry,
            outer_state_identity_at_exit=self.__state.state_identity,
            callback_completed=True,
            result_identity=_canonical_sha256(material),
            _owner_guard=self.__owner_guard,
        )
        self.__issued_controller_callback_guard_results[id(result)] = (
            result,
            result.result_identity,
            False,
        )
        return result

    def release_controller_callback_guard_v1(
        self, token: ControllerCallbackGuardTokenV1
    ) -> ControllerCallbackGuardResultV1:
        """Release exactly once and reject even identity-preserving attempts."""

        result = self._release_controller_callback_guard(
            token, callback_completed=True
        )
        assert result is not None
        return result

    def invoke_controller_callback_guarded_v1(
        self,
        lease: ControllerCallbackLeaseV1,
        callback: Callable[[], object],
    ) -> ControllerCallbackInvocationResultV1:
        """Preferred exception-safe public seam for a trusted controller callback."""

        if not callable(callback):
            raise C8TimedSessionRuntimeError(
                "trusted controller callback必须callable"
            )
        token = self.begin_controller_callback_guard_v1(lease)
        try:
            callback_result = callback()
        except BaseException as callback_exc:
            try:
                self._release_controller_callback_guard(
                    token, callback_completed=False
                )
            except BaseException as release_exc:
                raise release_exc from callback_exc
            self._record_public_operation_attempt(
                "controller_callback_exception_v1"
            )
            raise C8TimedSessionRuntimeError(
                "trusted controller callback异常；guard已安全退出"
            ) from callback_exc
        guard_result = self.release_controller_callback_guard_v1(token)
        return ControllerCallbackInvocationResultV1(
            guard_result=guard_result,
            callback_result=callback_result,
        )

    def _validate_controller_callback_guard_result(
        self, result: ControllerCallbackGuardResultV1
    ) -> tuple[ControllerCallbackGuardResultV1, str, bool]:
        if type(result) is not ControllerCallbackGuardResultV1:
            raise C8TimedSessionRuntimeError(
                "pending issuance registration需要strict live guard result"
            )
        issued = self.__issued_controller_callback_guard_results.get(id(result))
        if (
            issued is None
            or issued[0] is not result
            or issued[1] != result.result_identity
            or result._owner_guard is not self.__owner_guard
        ):
            raise C8TimedSessionRuntimeError(
                "controller callback guard result不是current wrapper实际签发"
            )
        _assert_identity(
            result.result_identity,
            result._identity_material(),
            "controller callback guard result_identity",
        )
        if issued[2]:
            raise C8TimedSessionRuntimeError(
                "controller callback guard result已经用于issuance registration"
            )
        if (
            result.runtime_instance_identity
            != self.__state.runtime_instance_identity
            or result.outer_state_identity_at_exit != self.__state.state_identity
            or result.operation_attempt_epoch_at_exit + 1
            != self.__operation_attempt_epoch
        ):
            raise C8TimedSessionRuntimeError(
                "controller callback guard result已stale或跨runtime lineage"
            )
        return issued

    def register_pending_timeout_issuance_capability_v1(
        self,
        ref: WindowAuthorityRefV1,
        *,
        timeout_due_commitment: TimeoutDueCommitmentV1,
        guard_result: ControllerCallbackGuardResultV1,
        signed_action_id: str,
        external_capability_identity: str,
    ) -> PendingTimeoutIssuanceCapabilityV1:
        """Register controller ownership without implementing a C8-C issuer."""

        self._record_public_operation_attempt(
            "register_pending_timeout_issuance_capability_v1"
        )
        self._ensure_live_binding()
        issued_result = self._validate_controller_callback_guard_result(
            guard_result
        )
        active, pending = self._validate_timeout_due_commitment(
            ref, timeout_due_commitment
        )
        if (
            guard_result.window_authority_ref_identity
            != ref.authority_ref_identity
            or guard_result.window_id != active.window_id
            or guard_result.timeout_due_commitment_identity
            != timeout_due_commitment.commitment_identity
            or guard_result.pending_deadline_identity != pending.pending_identity
        ):
            raise C8TimedSessionRuntimeError(
                "guard result与pending issuance timeout lineage不一致"
            )
        action_commitment = _signed_action_id_commitment_v1(signed_action_id)
        external_identity = _exact_sha256(
            external_capability_identity,
            "external_capability_identity",
        )
        generation = self.__next_pending_issuance_capability_generation
        ownership_nonce_identity = _canonical_sha256(
            {
                "schema": PENDING_ISSUANCE_CAPABILITY_SCHEMA,
                "runtime_contract_identity": C8_B_RUNTIME_CONTRACT_IDENTITY_V1,
                "runtime_instance_identity": self.__state.runtime_instance_identity,
                "guard_result_identity": guard_result.result_identity,
                "signed_action_id_commitment": action_commitment,
                "external_capability_identity": external_identity,
                "authorization_ledger_identity_at_issue": (
                    self.__auth_ledger_identity
                ),
                "capability_generation": generation,
                "operation_attempt_epoch_at_issue": (
                    self.__operation_attempt_epoch
                ),
            }
        )
        material = {
            "schema": PENDING_ISSUANCE_CAPABILITY_SCHEMA,
            "contract_version": 1,
            "runtime_contract_identity": C8_B_RUNTIME_CONTRACT_IDENTITY_V1,
            "runtime_instance_identity": self.__state.runtime_instance_identity,
            "controller_identity": guard_result.controller_identity,
            "adapter_identity": guard_result.adapter_identity,
            "window_authority_ref_identity": ref.authority_ref_identity,
            "window_id": active.window_id,
            "timeout_due_commitment_identity": (
                timeout_due_commitment.commitment_identity
            ),
            "pending_deadline_identity": pending.pending_identity,
            "signed_action_id_commitment": action_commitment,
            "external_capability_identity": external_identity,
            "authorization_ledger_identity_at_issue": (
                self.__auth_ledger_identity
            ),
            "guard_result_identity": guard_result.result_identity,
            "capability_generation": generation,
            "operation_attempt_epoch_at_issue": self.__operation_attempt_epoch,
            "ownership_nonce_identity": ownership_nonce_identity,
            "live_owner_guard_bound": True,
            "serializable_authority": False,
        }
        capability = PendingTimeoutIssuanceCapabilityV1(
            schema=PENDING_ISSUANCE_CAPABILITY_SCHEMA,
            contract_version=1,
            runtime_contract_identity=C8_B_RUNTIME_CONTRACT_IDENTITY_V1,
            runtime_instance_identity=self.__state.runtime_instance_identity,
            controller_identity=guard_result.controller_identity,
            adapter_identity=guard_result.adapter_identity,
            window_authority_ref_identity=ref.authority_ref_identity,
            window_id=active.window_id,
            timeout_due_commitment_identity=(
                timeout_due_commitment.commitment_identity
            ),
            pending_deadline_identity=pending.pending_identity,
            signed_action_id_commitment=action_commitment,
            external_capability_identity=external_identity,
            authorization_ledger_identity_at_issue=(
                self.__auth_ledger_identity
            ),
            guard_result_identity=guard_result.result_identity,
            capability_generation=generation,
            operation_attempt_epoch_at_issue=self.__operation_attempt_epoch,
            ownership_nonce_identity=ownership_nonce_identity,
            capability_identity=_canonical_sha256(material),
            _owner_guard=self.__owner_guard,
        )
        self.__issued_pending_issuance_capabilities[id(capability)] = (
            capability,
            capability.capability_identity,
            PendingIssuanceCapabilityStatusV1.CONTROLLER_OWNED_PENDING,
            None,
        )
        self.__issued_controller_callback_guard_results[id(guard_result)] = (
            issued_result[0],
            issued_result[1],
            True,
        )
        self.__next_pending_issuance_capability_generation += 1
        return capability

    def _pending_issuance_capability_record(
        self, capability: PendingTimeoutIssuanceCapabilityV1
    ) -> tuple[
        PendingTimeoutIssuanceCapabilityV1,
        str,
        PendingIssuanceCapabilityStatusV1,
        str | None,
    ]:
        if type(capability) is not PendingTimeoutIssuanceCapabilityV1:
            raise C8TimedSessionRuntimeError(
                "pending issuance capability必须是strict live token"
            )
        issued = self.__issued_pending_issuance_capabilities.get(id(capability))
        if (
            issued is None
            or issued[0] is not capability
            or issued[1] != capability.capability_identity
            or capability._owner_guard is not self.__owner_guard
        ):
            raise C8TimedSessionRuntimeError(
                "pending issuance capability不是current wrapper实际签发"
            )
        _assert_identity(
            capability.capability_identity,
            capability._identity_material(),
            "pending issuance capability_identity",
        )
        return issued

    def _validate_pending_issuance_for_forward(
        self,
        capability: PendingTimeoutIssuanceCapabilityV1,
        *,
        ref: WindowAuthorityRefV1,
        timeout_due_commitment: TimeoutDueCommitmentV1,
        signed_action_id: str,
        operation_attempt_offset: int = 1,
    ) -> PendingTimeoutIssuanceCapabilityV1:
        expected_offset = _exact_int(
            operation_attempt_offset, "operation_attempt_offset"
        )
        issued = self._pending_issuance_capability_record(capability)
        if (
            issued[2]
            is not PendingIssuanceCapabilityStatusV1.CONTROLLER_OWNED_PENDING
        ):
            raise C8TimedSessionRuntimeError(
                "pending issuance capability已经abort/consume，禁止duplicate/replay"
            )
        pending = self.__state.pending_deadline
        if (
            pending is None
            or capability.runtime_instance_identity
            != self.__state.runtime_instance_identity
            or capability.window_authority_ref_identity
            != ref.authority_ref_identity
            or capability.window_id != ref.window_id
            or capability.timeout_due_commitment_identity
            != timeout_due_commitment.commitment_identity
            or capability.pending_deadline_identity != pending.pending_identity
            or capability.signed_action_id_commitment
            != _signed_action_id_commitment_v1(signed_action_id)
            or capability.authorization_ledger_identity_at_issue
            != self.__auth_ledger_identity
            or capability.operation_attempt_epoch_at_issue + expected_offset
            != self.__operation_attempt_epoch
        ):
            raise C8TimedSessionRuntimeError(
                "pending issuance capability与current runtime/window/action/auth lineage不一致"
            )
        return capability

    def _set_pending_issuance_capability_status(
        self,
        capability: PendingTimeoutIssuanceCapabilityV1,
        status: PendingIssuanceCapabilityStatusV1,
        *,
        committed_receipt_identity: str | None,
    ) -> None:
        issued = self._pending_issuance_capability_record(capability)
        self.__issued_pending_issuance_capabilities[id(capability)] = (
            issued[0],
            issued[1],
            status,
            committed_receipt_identity,
        )

    def _mark_pending_issuance_auth_consumed(
        self, capability: PendingTimeoutIssuanceCapabilityV1 | None
    ) -> None:
        if capability is None:
            return
        issued = self._pending_issuance_capability_record(capability)
        if (
            issued[2]
            is PendingIssuanceCapabilityStatusV1.CONTROLLER_OWNED_PENDING
        ):
            self._set_pending_issuance_capability_status(
                capability,
                PendingIssuanceCapabilityStatusV1.AUTH_EVIDENCE_CONSUMED,
                committed_receipt_identity=None,
            )

    def _mark_pending_issuance_receipt_committed(
        self,
        capability: PendingTimeoutIssuanceCapabilityV1 | None,
        receipt: TimeoutActionExecutionReceiptV1,
    ) -> None:
        if capability is None:
            return
        issued = self._pending_issuance_capability_record(capability)
        if (
            issued[2]
            is not PendingIssuanceCapabilityStatusV1.AUTH_EVIDENCE_CONSUMED
        ):
            raise C8TimedSessionRuntimeError(
                "pending issuance capability未先证明auth evidence consumed"
            )
        self._set_pending_issuance_capability_status(
            capability,
            PendingIssuanceCapabilityStatusV1.RECEIPT_COMMITTED_CONSUMED,
            committed_receipt_identity=receipt.receipt_identity,
        )

    def _pending_issuance_ownership_projection(
        self, capability: PendingTimeoutIssuanceCapabilityV1
    ) -> PendingIssuanceCapabilityOwnershipV1:
        issued = self._pending_issuance_capability_record(capability)
        material = {
            "schema": PENDING_ISSUANCE_OWNERSHIP_SCHEMA,
            "contract_version": 1,
            "runtime_contract_identity": C8_B_RUNTIME_CONTRACT_IDENTITY_V1,
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
            "external_capability_identity": (
                capability.external_capability_identity
            ),
            "status": issued[2].value,
            "committed_receipt_identity": issued[3],
            "authorizing_capability_exposed": False,
        }
        return PendingIssuanceCapabilityOwnershipV1(
            schema=PENDING_ISSUANCE_OWNERSHIP_SCHEMA,
            contract_version=1,
            runtime_contract_identity=C8_B_RUNTIME_CONTRACT_IDENTITY_V1,
            runtime_instance_identity=capability.runtime_instance_identity,
            capability_identity=capability.capability_identity,
            controller_identity=capability.controller_identity,
            adapter_identity=capability.adapter_identity,
            window_authority_ref_identity=(
                capability.window_authority_ref_identity
            ),
            timeout_due_commitment_identity=(
                capability.timeout_due_commitment_identity
            ),
            external_capability_identity=capability.external_capability_identity,
            status=issued[2],
            committed_receipt_identity=issued[3],
            ownership_identity=_canonical_sha256(material),
        )

    def current_pending_issuance_capability_ownership_v1(
        self, capability: PendingTimeoutIssuanceCapabilityV1
    ) -> PendingIssuanceCapabilityOwnershipV1:
        """Read an audit-only lifecycle view; it is never authorization input."""

        if self.__active_controller_callback_guard is not None:
            self._record_public_operation_attempt(
                "current_pending_issuance_capability_ownership_v1"
            )
        self._ensure_live_binding()
        return self._pending_issuance_ownership_projection(capability)

    def abort_pending_timeout_issuance_capability_v1(
        self, capability: PendingTimeoutIssuanceCapabilityV1
    ) -> PendingIssuanceCapabilityOwnershipV1:
        """Invalidate a still controller-owned capability exactly once."""

        self._record_public_operation_attempt(
            "abort_pending_timeout_issuance_capability_v1"
        )
        self._ensure_live_binding()
        issued = self._pending_issuance_capability_record(capability)
        if (
            issued[2]
            is not PendingIssuanceCapabilityStatusV1.CONTROLLER_OWNED_PENDING
        ):
            raise C8TimedSessionRuntimeError(
                "pending issuance capability已经abort/consume，禁止duplicate abort"
            )
        self._set_pending_issuance_capability_status(
            capability,
            PendingIssuanceCapabilityStatusV1.CONTROLLER_ABORTED,
            committed_receipt_identity=None,
        )
        return self._pending_issuance_ownership_projection(capability)

    def _call_external(
        self,
        owner: object,
        owner_label: str,
        method_name: str,
        *args: object,
    ) -> object:
        if self.__callback_busy:
            raise C8TimedSessionRuntimeError(
                "external adapter/authenticator callback禁止重入C8-B runtime"
            )
        method = getattr(owner, method_name, None)
        if not callable(method):
            raise C8TimedSessionRuntimeError(f"{owner_label}缺少{method_name}")
        self.__callback_busy = True
        try:
            return method(*args)
        finally:
            self.__callback_busy = False

    def _adapter_sha(self, method_name: str, *args: object) -> str:
        return _exact_sha256(
            self._call_external(
                self.__adapter, "inner adapter", method_name, *args
            ),
            f"inner adapter {method_name}",
        )

    def _authenticator_sha(self, method_name: str, *args: object) -> str:
        return _exact_sha256(
            self._call_external(
                self.__input_authenticator,
                "input authenticator",
                method_name,
                *args,
            ),
            f"input authenticator {method_name}",
        )

    def _ensure_live_binding(self) -> None:
        self._validate_operation_attempt_evidence()
        if self.__poisoned:
            raise C8TimedSessionRuntimeError(
                "C8-B runtime已因inner rollback recovery失败进入fail-closed状态"
            )
        if self.__callback_busy:
            raise C8TimedSessionRuntimeError(
                "external adapter/authenticator callback禁止重入C8-B runtime"
            )
        state = self.__state
        if state.contract_latch != C8_B_CURRENT_CONTRACT_LATCH_V1:
            raise C8TimedSessionRuntimeError("runtime current-contract latch drift")
        if (
            self._authenticator_sha("authenticator_identity_v1")
            != state.input_authenticator_identity
        ):
            raise C8TimedSessionRuntimeError("input authenticator identity drift")
        if (
            self._authenticator_sha("anti_replay_state_identity_v1")
            != self.__auth_ledger_identity
        ):
            raise C8TimedSessionRuntimeError(
                "input authenticator anti-replay ledger发生runtime外漂移"
            )
        if self._adapter_sha("adapter_identity_v1") != state.inner_adapter_identity:
            raise C8TimedSessionRuntimeError("inner adapter identity drift")
        if (
            self._adapter_sha("session_binding_identity_v1")
            != state.inner_session_binding_identity
        ):
            raise C8TimedSessionRuntimeError("inner session binding drift")
        if self._adapter_sha("public_state_identity_v1") != state.inner_public_state_identity:
            raise C8TimedSessionRuntimeError("inner public state发生wrapper外漂移")
        if (
            self._adapter_sha("authoritative_state_identity_v1")
            != state.inner_authoritative_state_identity
        ):
            raise C8TimedSessionRuntimeError("inner authoritative state发生wrapper外漂移")

    def _active_for_ref(self, ref: WindowAuthorityRefV1) -> TimedDecisionWindowV1:
        if type(ref) is not WindowAuthorityRefV1:
            raise C8TimedSessionRuntimeError("window authority ref类型不正确")
        state = self.__state
        active = state.virtual_time_state.window_stack.active_window
        if active is None:
            raise C8TimedSessionRuntimeError("当前没有active timed window")
        if ref.runtime_instance_identity != state.runtime_instance_identity:
            raise C8TimedSessionRuntimeError("window ref绑定了其它runtime")
        expected = WindowAuthorityRefV1.from_window(state.runtime_instance_identity, active)
        if ref != expected:
            raise C8TimedSessionRuntimeError(
                "window/parent/actor/kind/decision/obligation authority不匹配current top"
            )
        return active

    def active_window_ref(self) -> WindowAuthorityRefV1 | None:
        active = self.__state.virtual_time_state.window_stack.active_window
        return (
            None
            if active is None
            else WindowAuthorityRefV1.from_window(
                self.__state.runtime_instance_identity, active
            )
        )

    def _validate_timeout_due_commitment(
        self,
        ref: WindowAuthorityRefV1,
        timeout_due_commitment: TimeoutDueCommitmentV1,
    ) -> tuple[TimedDecisionWindowV1, PendingDerivedDeadlineV1]:
        if type(timeout_due_commitment) is not TimeoutDueCommitmentV1:
            raise C8TimedSessionRuntimeError(
                "timeout forwarding需要wrapper签发的strict due commitment"
            )
        issued = self.__issued_timeout_commitments.get(id(timeout_due_commitment))
        if (
            issued is None
            or issued[0] is not timeout_due_commitment
            or issued[1] != timeout_due_commitment.commitment_identity
        ):
            raise C8TimedSessionRuntimeError(
                "timeout due commitment不是current wrapper实际签发的live object"
            )
        try:
            material = timeout_due_commitment._identity_material()
        except Exception as exc:
            raise C8TimedSessionRuntimeError(
                "timeout due commitment material已被深层篡改"
            ) from exc
        _assert_identity(
            timeout_due_commitment.commitment_identity,
            material,
            "timeout due commitment_identity",
        )
        state = self.__state
        active = self._active_for_ref(ref)
        pending = state.pending_deadline
        if (
            active.status is not TimedWindowStatusV1.ACTIVE
            or state.virtual_time_state.now_tick < active.deadline_at
            or pending is None
        ):
            raise C8TimedSessionRuntimeError(
                "timeout due commitment只允许current timeout-priority ACTIVE window"
            )
        if issued[2] != state.state_identity:
            raise C8TimedSessionRuntimeError("timeout due commitment已stale或跨sibling lineage")
        expected = TimeoutDueCommitmentV1.build(
            state=state,
            ref=ref,
            active=active,
            pending=pending,
        )
        if timeout_due_commitment != expected:
            raise C8TimedSessionRuntimeError(
                "timeout due commitment未绑定current time/deadline/input/event chain"
            )
        return active, pending

    def current_timeout_due_commitment_v1(
        self, ref: WindowAuthorityRefV1
    ) -> TimeoutDueCommitmentV1:
        """Issue a live proof derived only from the runtime's pending deadline."""

        self._record_public_operation_attempt(
            "current_timeout_due_commitment_v1"
        )
        self._ensure_live_binding()
        if self.__pending_timeout_receipt_identity is not None:
            raise C8TimedSessionRuntimeError(
                "current timeout action receipt尚未close/continue消费"
            )
        active = self._active_for_ref(ref)
        state = self.__state
        pending = state.pending_deadline
        if (
            active.status is not TimedWindowStatusV1.ACTIVE
            or state.virtual_time_state.now_tick < active.deadline_at
            or pending is None
        ):
            raise C8TimedSessionRuntimeError(
                "before-deadline或缺少runtime-derived pending deadline"
            )
        commitment = TimeoutDueCommitmentV1.build(
            state=state,
            ref=ref,
            active=active,
            pending=pending,
        )
        self.__issued_timeout_commitments[id(commitment)] = (
            commitment,
            commitment.commitment_identity,
            state.state_identity,
        )
        return commitment

    def expected_timeout_action_authentication_binding_v1(
        self,
        ref: WindowAuthorityRefV1,
        *,
        timeout_due_commitment: TimeoutDueCommitmentV1,
        signed_action_id: str,
        pending_issuance_capability: (
            PendingTimeoutIssuanceCapabilityV1 | None
        ) = None,
    ) -> str:
        """Return the exact binding a future C8-C fresh issuer must authorize."""

        if self.__active_controller_callback_guard is not None:
            self._record_public_operation_attempt(
                "expected_timeout_action_authentication_binding_v1"
            )
        self._ensure_live_binding()
        self._validate_timeout_due_commitment(ref, timeout_due_commitment)
        if self.__pending_timeout_receipt_identity is not None:
            raise C8TimedSessionRuntimeError(
                "current timeout action receipt尚未close/continue消费"
            )
        action_id = _exact_text(signed_action_id, "signed_action_id")
        capability = (
            None
            if pending_issuance_capability is None
            else self._validate_pending_issuance_for_forward(
                pending_issuance_capability,
                ref=ref,
                timeout_due_commitment=timeout_due_commitment,
                signed_action_id=action_id,
                operation_attempt_offset=0,
            )
        )
        state = self.__state
        return derive_timeout_action_authorization_binding_v1(
            timeout_due_commitment=timeout_due_commitment,
            signed_action_id=action_id,
            issuance_authority_identity=state.input_authenticator_identity,
            previous_auth_ledger_identity=self.__auth_ledger_identity,
            receipt_sequence=self.__next_timeout_receipt_sequence,
            previous_receipt_identity=self.__timeout_receipt_chain_tip,
            pending_issuance_capability_identity=(
                None if capability is None else capability.capability_identity
            ),
        )

    def _build_timeout_execution_receipt(
        self, **kwargs: object
    ) -> TimeoutActionExecutionReceiptV1:
        return TimeoutActionExecutionReceiptV1.build(**kwargs)  # type: ignore[arg-type]

    def _restore_failed_timeout_forward(
        self,
        snapshot: TimedSessionTransactionSnapshotV1,
        *,
        preserved_auth_ledger_identity: str,
    ) -> None:
        """Restore a wrapper-issued snapshot without rolling back auth evidence."""

        try:
            issued = self.__issued_snapshots.get(id(snapshot))
            if (
                issued is None
                or issued[0] is not snapshot
                or issued[1] != snapshot.snapshot_identity
                or snapshot.owner_guard is not self.__owner_guard
            ):
                raise C8TimedSessionRuntimeError(
                    "timeout recovery snapshot不是current wrapper签发"
                )
            _assert_identity(
                snapshot.snapshot_identity,
                snapshot._identity_material(),
                "timeout recovery snapshot_identity",
            )
            if (
                self._adapter_sha(
                    "snapshot_token_identity_v1", snapshot.inner_snapshot_token
                )
                != snapshot.inner_snapshot_identity
            ):
                raise C8TimedSessionRuntimeError(
                    "timeout recovery inner snapshot token漂移"
                )
            self._call_external(
                self.__adapter,
                "inner adapter",
                "restore_transaction_snapshot_v1",
                snapshot.inner_snapshot_token,
            )
            restored = snapshot.outer_state
            if (
                self._adapter_sha("adapter_identity_v1")
                != restored.inner_adapter_identity
                or self._adapter_sha("session_binding_identity_v1")
                != restored.inner_session_binding_identity
                or self._adapter_sha("public_state_identity_v1")
                != restored.inner_public_state_identity
                or self._adapter_sha("authoritative_state_identity_v1")
                != restored.inner_authoritative_state_identity
                or self._authenticator_sha("authenticator_identity_v1")
                != restored.input_authenticator_identity
                or self._authenticator_sha("anti_replay_state_identity_v1")
                != preserved_auth_ledger_identity
            ):
                raise C8TimedSessionRuntimeError(
                    "timeout recovery未恢复inner identities或非法回退auth ledger"
                )
            self.__state = restored
        except Exception as recovery_exc:
            self.__poisoned = True
            raise C8TimedSessionRuntimeError(
                "timeout forwarding recovery失败；runtime已poisoned fail closed"
            ) from recovery_exc

    def _validate_timeout_execution_receipt(
        self,
        ref: WindowAuthorityRefV1,
        execution_receipt: TimeoutActionExecutionReceiptV1 | None,
    ) -> TimeoutActionExecutionReceiptV1:
        if type(execution_receipt) is not TimeoutActionExecutionReceiptV1:
            raise C8TimedSessionRuntimeError(
                "timeout close/continue需要strict execution receipt"
            )
        receipt = execution_receipt
        issued = self.__issued_timeout_receipts.get(id(receipt))
        if (
            issued is None
            or issued[0] is not receipt
            or issued[1] != receipt.receipt_identity
        ):
            raise C8TimedSessionRuntimeError(
                "timeout execution receipt不是current wrapper实际签发的live object"
            )
        try:
            material = receipt._identity_material()
        except Exception as exc:
            raise C8TimedSessionRuntimeError(
                "timeout execution receipt material已被深层篡改"
            ) from exc
        _assert_identity(
            receipt.receipt_identity,
            material,
            "timeout execution receipt_identity",
        )
        if receipt.receipt_identity in self.__consumed_timeout_receipt_identities:
            raise C8TimedSessionRuntimeError("timeout execution receipt已经消费或撤销")
        if self.__pending_timeout_receipt_identity != receipt.receipt_identity:
            raise C8TimedSessionRuntimeError(
                "timeout execution receipt不是current pending receipt lineage"
            )
        if self.__timeout_receipt_chain_tip != receipt.receipt_identity:
            raise C8TimedSessionRuntimeError(
                "timeout execution receipt已被更新lineage取代"
            )
        state = self.__state
        active = self._active_for_ref(ref)
        pending = state.pending_deadline
        if pending is None or state.virtual_time_state.now_tick < active.deadline_at:
            raise C8TimedSessionRuntimeError(
                "timeout execution receipt缺少current pending deadline"
            )
        if (
            receipt.runtime_contract_identity
            != C8_B_RUNTIME_CONTRACT_IDENTITY_V1
            or receipt.runtime_instance_identity != state.runtime_instance_identity
            or receipt.window_authority_ref_identity != ref.authority_ref_identity
            or receipt.window_id != active.window_id
            or receipt.actor_id != active.actor_id
            or receipt.decision_identity != active.decision_identity
            or receipt.obligation_identity != active.obligation_identity
            or receipt.deadline_at != active.deadline_at
            or receipt.executed_at_tick != state.virtual_time_state.now_tick
            or receipt.pending_deadline_identity != pending.pending_identity
            or receipt.derived_deadline_identity
            != pending.derived_deadline_identity
            or receipt.inner_adapter_identity != state.inner_adapter_identity
            or receipt.inner_session_binding_identity
            != state.inner_session_binding_identity
            or receipt.issuance_authority_identity
            != state.input_authenticator_identity
            or receipt.post_inner_public_state_identity
            != state.inner_public_state_identity
            or receipt.post_inner_authoritative_state_identity
            != state.inner_authoritative_state_identity
            or receipt.authorization_ledger_after_identity
            != self.__auth_ledger_identity
        ):
            raise C8TimedSessionRuntimeError(
                "timeout execution receipt与current window/runtime/post-state/deadline不一致"
            )
        if receipt.pending_issuance_capability_identity is not None:
            capability_records = tuple(
                item
                for item in self.__issued_pending_issuance_capabilities.values()
                if item[1] == receipt.pending_issuance_capability_identity
            )
            if (
                len(capability_records) != 1
                or capability_records[0][2]
                is not PendingIssuanceCapabilityStatusV1.RECEIPT_COMMITTED_CONSUMED
                or capability_records[0][3] != receipt.receipt_identity
            ):
                raise C8TimedSessionRuntimeError(
                    "timeout receipt未绑定已正式commit/consume的issuance capability"
                )
        if not state.runtime_events:
            raise C8TimedSessionRuntimeError(
                "timeout execution receipt缺少outer forwarding event"
            )
        event = state.runtime_events[-1]
        if (
            event.event_kind is not RuntimeEventKindV1.TIMEOUT_SIGNED_ACTION_FORWARDED
            or event.window_id != active.window_id
            or event.execution_receipt_identity != receipt.receipt_identity
            or event.inner_transition_identity != receipt.outer_transition_identity
            or state.event_chain_tip != event.event_identity
        ):
            raise C8TimedSessionRuntimeError(
                "timeout execution receipt未绑定current outer transition/event chain"
            )
        return receipt

    def _consume_timeout_execution_receipt(
        self, receipt: TimeoutActionExecutionReceiptV1
    ) -> None:
        self.__consumed_timeout_receipt_identities.add(receipt.receipt_identity)
        self.__pending_timeout_receipt_identity = None

    def _invalidate_pending_timeout_execution_receipt(self) -> None:
        pending = self.__pending_timeout_receipt_identity
        if pending is not None:
            self.__consumed_timeout_receipt_identities.add(pending)
            self.__pending_timeout_receipt_identity = None

    def _commit(
        self,
        *,
        virtual_time_state: VirtualTimeStateV1,
        input_records: Sequence[AcceptedVirtualTimeInputV1] | None = None,
        window_open_state_origins: Sequence[str] | None = None,
        logical_obligations: Sequence[LogicalObligationProgressV1] | None = None,
        seen_logical_obligation_identities: Sequence[str] | None = None,
        pending_deadline: PendingDerivedDeadlineV1 | None,
        event_specs: Sequence[dict[str, object]],
        inner_public_state_identity: str | None = None,
        inner_authoritative_state_identity: str | None = None,
    ) -> TimedSessionOuterStateV1:
        prior = self.__state
        events = list(prior.runtime_events)
        previous_tip = prior.event_chain_tip
        for spec in event_specs:
            window = spec["window"]
            if type(window) is not TimedDecisionWindowV1:
                raise C8TimedSessionRuntimeError("internal event spec window类型不正确")
            event = RuntimeEventV1.build(
                event_sequence=len(events),
                event_kind=spec["event_kind"],
                runtime_instance_identity=prior.runtime_instance_identity,
                tick=virtual_time_state.now_tick,
                window=window,
                related_window_id=spec.get("related_window_id"),
                before_virtual_state_identity=prior.virtual_time_state.state_identity,
                after_virtual_state_identity=virtual_time_state.state_identity,
                input_identity=spec.get("input_identity"),
                derived_deadline_identity=spec.get("derived_deadline_identity"),
                logical_step_identity=spec.get("logical_step_identity"),
                inner_transition_identity=spec.get("inner_transition_identity"),
                execution_receipt_identity=spec.get("execution_receipt_identity"),
                requested_tick=spec.get("requested_tick"),
                applied_tick=spec.get("applied_tick"),
                previous_event_identity=previous_tip,
            )
            events.append(event)
            previous_tip = event.event_identity
        candidate = TimedSessionOuterStateV1.build(
            runtime_instance_identity=prior.runtime_instance_identity,
            instance_nonce_identity=prior.instance_nonce_identity,
            contract_latch=prior.contract_latch,
            input_source_id=prior.input_source_id,
            driver_authority_identity=prior.driver_authority_identity,
            input_authenticator_identity=prior.input_authenticator_identity,
            inner_adapter_identity=prior.inner_adapter_identity,
            inner_session_binding_identity=prior.inner_session_binding_identity,
            inner_public_state_identity=(
                prior.inner_public_state_identity
                if inner_public_state_identity is None
                else inner_public_state_identity
            ),
            inner_authoritative_state_identity=(
                prior.inner_authoritative_state_identity
                if inner_authoritative_state_identity is None
                else inner_authoritative_state_identity
            ),
            virtual_time_state=virtual_time_state,
            input_records=prior.input_records if input_records is None else input_records,
            window_open_state_origins=(
                prior.window_open_state_origins
                if window_open_state_origins is None
                else window_open_state_origins
            ),
            logical_obligations=(
                prior.logical_obligations
                if logical_obligations is None
                else logical_obligations
            ),
            seen_logical_obligation_identities=(
                prior.seen_logical_obligation_identities
                if seen_logical_obligation_identities is None
                else seen_logical_obligation_identities
            ),
            pending_deadline=pending_deadline,
            runtime_events=events,
        )
        self.__state = candidate
        return candidate

    def open_window(
        self,
        *,
        actor_id: str,
        window_kind: TimedWindowKindV1,
        decision_identity: str,
        obligation_identity: str,
        expected_parent_ref: WindowAuthorityRefV1 | None,
    ) -> WindowAuthorityRefV1:
        self._record_public_operation_attempt("open_window")
        self._ensure_live_binding()
        actor = _exact_text_id(actor_id, "actor_id")
        if type(window_kind) is not TimedWindowKindV1:
            raise C8TimedSessionRuntimeError("window_kind类型不正确")
        decision = _exact_sha256(decision_identity, "decision_identity")
        obligation = _exact_sha256(obligation_identity, "obligation_identity")
        prior = self.__state
        parent = prior.virtual_time_state.window_stack.active_window
        if any(
            item.window_kind is TimedWindowKindV1.MULTI_STEP_OBLIGATION
            and item.obligation_identity == obligation
            for item in prior.virtual_time_state.window_stack.windows
        ):
            raise C8TimedSessionRuntimeError(
                "同一logical multi-step obligation必须continue，不得经nested window刷新deadline"
            )
        if (
            window_kind is TimedWindowKindV1.MULTI_STEP_OBLIGATION
            and obligation in prior.seen_logical_obligation_identities
        ):
            raise C8TimedSessionRuntimeError(
                "logical multi-step obligation identity已经使用，禁止重开deadline"
            )
        if parent is None:
            if expected_parent_ref is not None:
                raise C8TimedSessionRuntimeError("root window不得提供parent ref")
        else:
            if (
                deadline_precedence_v1(
                    parent, prior.virtual_time_state.now_tick
                )
                is not DeadlinePrecedenceV1.ACTION_ELIGIBLE_BEFORE_DEADLINE
            ):
                raise C8TimedSessionRuntimeError(
                    "parent deadline已经到达，禁止打开nested child"
                )
            if expected_parent_ref is None:
                raise C8TimedSessionRuntimeError("nested window必须显式绑定current parent ref")
            self._active_for_ref(expected_parent_ref)
        try:
            virtual = open_decision_window_v1(
                prior.virtual_time_state,
                actor_id=actor,
                window_kind=window_kind,
                decision_identity=decision,
                obligation_identity=obligation,
                duration_profile=ENGINEERING_TEST_PROFILE_V1,
                fallback_policy=TIMEOUT_FALLBACK_REGISTRY_V1.policy_for(window_kind),
            )
        except C8VirtualTimeContractError as exc:
            raise C8TimedSessionRuntimeError(f"C8-A window open拒绝：{exc}") from exc
        opened = virtual.window_stack.active_window
        assert opened is not None
        logical = list(prior.logical_obligations)
        if window_kind is TimedWindowKindV1.MULTI_STEP_OBLIGATION:
            logical.append(
                LogicalObligationProgressV1.build(
                    window_id=opened.window_id,
                    window_binding_identity=opened.window_binding_identity,
                    obligation_identity=opened.obligation_identity,
                    next_step_index=0,
                    step_identities=(),
                )
            )
        specs: list[dict[str, object]] = []
        if parent is not None:
            suspended = virtual.window_stack.windows[-2]
            specs.append(
                {
                    "event_kind": RuntimeEventKindV1.PARENT_SUSPENDED_BY_CHILD,
                    "window": suspended,
                    "related_window_id": opened.window_id,
                }
            )
        specs.append(
            {
                "event_kind": RuntimeEventKindV1.WINDOW_OPENED,
                "window": opened,
                "related_window_id": opened.parent_window_id,
            }
        )
        self._commit(
            virtual_time_state=virtual,
            window_open_state_origins=(
                prior.window_open_state_origins + (prior.state_identity,)
            ),
            logical_obligations=logical,
            seen_logical_obligation_identities=(
                prior.seen_logical_obligation_identities + (obligation,)
                if window_kind is TimedWindowKindV1.MULTI_STEP_OBLIGATION
                else prior.seen_logical_obligation_identities
            ),
            pending_deadline=None,
            event_specs=specs,
        )
        return WindowAuthorityRefV1.from_window(
            self.__state.runtime_instance_identity, opened
        )

    def action_eligibility(self, ref: WindowAuthorityRefV1) -> DeadlinePrecedenceV1:
        if self.__active_controller_callback_guard is None:
            self._ensure_live_binding()
        else:
            self._validate_operation_attempt_evidence()
        active = self._active_for_ref(ref)
        if active.status is not TimedWindowStatusV1.ACTIVE:
            raise C8TimedSessionRuntimeError("action eligibility只允许ACTIVE top")
        return deadline_precedence_v1(active, self.__state.virtual_time_state.now_tick)

    def continue_multi_step_obligation(
        self,
        ref: WindowAuthorityRefV1,
        *,
        expected_step_index: int,
        logical_step_identity: str,
    ) -> DeadlinePrecedenceV1:
        self._record_public_operation_attempt(
            "continue_multi_step_obligation"
        )
        self._ensure_live_binding()
        active = self._active_for_ref(ref)
        step_index = _exact_int(expected_step_index, "expected_step_index")
        step_identity = _exact_sha256(logical_step_identity, "logical_step_identity")
        if active.window_kind is not TimedWindowKindV1.MULTI_STEP_OBLIGATION:
            raise C8TimedSessionRuntimeError("continue只允许MULTI_STEP_OBLIGATION window")
        eligibility = deadline_precedence_v1(active, self.__state.virtual_time_state.now_tick)
        if eligibility is not DeadlinePrecedenceV1.ACTION_ELIGIBLE_BEFORE_DEADLINE:
            raise C8TimedSessionRuntimeError("deadline已到达，禁止继续logical step")
        logical = list(self.__state.logical_obligations)
        progress = logical[-1]
        if progress.window_id != active.window_id:
            raise C8TimedSessionRuntimeError("active multi-step progress不一致")
        if step_index != progress.next_step_index:
            raise C8TimedSessionRuntimeError("multi-step index重复、跳号或重排")
        if step_identity in progress.step_identities:
            raise C8TimedSessionRuntimeError("multi-step logical step identity重复")
        logical[-1] = LogicalObligationProgressV1.build(
            window_id=progress.window_id,
            window_binding_identity=progress.window_binding_identity,
            obligation_identity=progress.obligation_identity,
            next_step_index=progress.next_step_index + 1,
            step_identities=progress.step_identities + (step_identity,),
        )
        self._commit(
            virtual_time_state=self.__state.virtual_time_state,
            logical_obligations=logical,
            pending_deadline=self.__state.pending_deadline,
            event_specs=(
                {
                    "event_kind": RuntimeEventKindV1.MULTI_STEP_CONTINUED,
                    "window": active,
                    "logical_step_identity": step_identity,
                },
            ),
        )
        return eligibility

    def forward_on_time_signed_action_id(
        self,
        ref: WindowAuthorityRefV1,
        *,
        signed_action_id: str,
    ) -> str:
        """Transparently forward an on-time action; the inner adapter remains authority."""

        self._record_public_operation_attempt(
            "forward_on_time_signed_action_id"
        )
        self._ensure_live_binding()
        active = self._active_for_ref(ref)
        if (
            deadline_precedence_v1(active, self.__state.virtual_time_state.now_tick)
            is not DeadlinePrecedenceV1.ACTION_ELIGIBLE_BEFORE_DEADLINE
        ):
            raise C8TimedSessionRuntimeError(
                "exact deadline处timeout优先，禁止forward normal action"
            )
        action_id = _exact_text(signed_action_id, "signed_action_id")
        prior = self.__state
        auth_ledger_before = self.__auth_ledger_identity
        backup_token = self._call_external(
            self.__adapter,
            "inner adapter",
            "capture_transaction_snapshot_v1",
        )
        backup_identity = self._adapter_sha("snapshot_token_identity_v1", backup_token)
        try:
            result = self._call_external(
                self.__adapter,
                "inner adapter",
                "apply_signed_action_id_v1",
                action_id,
            )
            if result is not None:
                raise C8TimedSessionRuntimeError(
                    "inner signed-action passthrough必须返回None"
                )
            if self._adapter_sha("adapter_identity_v1") != prior.inner_adapter_identity:
                raise C8TimedSessionRuntimeError("normal action后inner adapter identity drift")
            if (
                self._adapter_sha("session_binding_identity_v1")
                != prior.inner_session_binding_identity
            ):
                raise C8TimedSessionRuntimeError("normal action后inner session binding drift")
            public_identity = self._adapter_sha("public_state_identity_v1")
            authoritative_identity = self._adapter_sha(
                "authoritative_state_identity_v1"
            )
            if (
                self._authenticator_sha("anti_replay_state_identity_v1")
                != auth_ledger_before
            ):
                raise C8TimedSessionRuntimeError(
                    "inner normal action非法改变external auth ledger"
                )
            if authoritative_identity == prior.inner_authoritative_state_identity:
                raise C8TimedSessionRuntimeError(
                    "inner adapter接受action后authoritative identity未变化"
                )
            transition_identity = _canonical_sha256(
                {
                    "schema": "sgs-c8-b-inner-transition-commitment-v1",
                    "runtime_instance_identity": prior.runtime_instance_identity,
                    "window_ref_identity": ref.authority_ref_identity,
                    "signed_action_id_identity": _canonical_sha256(
                        {"signed_action_id": action_id}
                    ),
                    "before_inner_public_state_identity": (
                        prior.inner_public_state_identity
                    ),
                    "after_inner_public_state_identity": public_identity,
                    "before_inner_authoritative_state_identity": (
                        prior.inner_authoritative_state_identity
                    ),
                    "after_inner_authoritative_state_identity": (
                        authoritative_identity
                    ),
                }
            )
            candidate = self._commit(
                virtual_time_state=prior.virtual_time_state,
                pending_deadline=prior.pending_deadline,
                event_specs=(
                    {
                        "event_kind": (
                            RuntimeEventKindV1.INNER_SIGNED_ACTION_FORWARDED
                        ),
                        "window": active,
                        "inner_transition_identity": transition_identity,
                    },
                ),
                inner_public_state_identity=public_identity,
                inner_authoritative_state_identity=authoritative_identity,
            )
        except Exception as exc:
            try:
                if (
                    self._adapter_sha("snapshot_token_identity_v1", backup_token)
                    != backup_identity
                ):
                    raise C8TimedSessionRuntimeError(
                        "normal action backup token漂移"
                    )
                self._call_external(
                    self.__adapter,
                    "inner adapter",
                    "restore_transaction_snapshot_v1",
                    backup_token,
                )
                if (
                    self._adapter_sha("adapter_identity_v1")
                    != prior.inner_adapter_identity
                    or self._adapter_sha("session_binding_identity_v1")
                    != prior.inner_session_binding_identity
                    or self._adapter_sha("public_state_identity_v1")
                    != prior.inner_public_state_identity
                    or self._adapter_sha("authoritative_state_identity_v1")
                    != prior.inner_authoritative_state_identity
                    or self._authenticator_sha("anti_replay_state_identity_v1")
                    != auth_ledger_before
                ):
                    raise C8TimedSessionRuntimeError(
                        "normal action backup restore identity不一致"
                    )
            except Exception as recovery_exc:
                self.__poisoned = True
                raise C8TimedSessionRuntimeError(
                    "inner normal action失败且backup restore失败；runtime已fail closed"
                ) from recovery_exc
            if isinstance(exc, C8TimedSessionRuntimeError):
                raise
            raise C8TimedSessionRuntimeError(
                "inner normal action失败；outer state未替换"
            ) from exc
        return candidate.inner_public_state_identity

    def forward_timeout_due_signed_action_id_v1(
        self,
        ref: WindowAuthorityRefV1,
        *,
        timeout_due_commitment: TimeoutDueCommitmentV1,
        signed_action_id: str,
        authorization_evidence_identity: str,
        pending_issuance_capability: (
            PendingTimeoutIssuanceCapabilityV1 | None
        ) = None,
    ) -> TimeoutActionExecutionReceiptV1:
        """Forward one freshly authorized timeout action and return a typed receipt."""

        self._record_public_operation_attempt(
            "forward_timeout_due_signed_action_id_v1"
        )
        self._ensure_live_binding()
        active, pending = self._validate_timeout_due_commitment(
            ref, timeout_due_commitment
        )
        if self.__pending_timeout_receipt_identity is not None:
            raise C8TimedSessionRuntimeError(
                "current timeout action receipt尚未close/continue消费"
            )
        action_id = _exact_text(signed_action_id, "signed_action_id")
        evidence_identity = _exact_sha256(
            authorization_evidence_identity,
            "authorization_evidence_identity",
        )
        prior = self.__state
        action_commitment = _signed_action_id_commitment_v1(action_id)
        capability = (
            None
            if pending_issuance_capability is None
            else self._validate_pending_issuance_for_forward(
                pending_issuance_capability,
                ref=ref,
                timeout_due_commitment=timeout_due_commitment,
                signed_action_id=action_id,
                operation_attempt_offset=1,
            )
        )
        authorization_binding = derive_timeout_action_authorization_binding_v1(
            timeout_due_commitment=timeout_due_commitment,
            signed_action_id=action_id,
            issuance_authority_identity=prior.input_authenticator_identity,
            previous_auth_ledger_identity=self.__auth_ledger_identity,
            receipt_sequence=self.__next_timeout_receipt_sequence,
            previous_receipt_identity=self.__timeout_receipt_chain_tip,
            pending_issuance_capability_identity=(
                None if capability is None else capability.capability_identity
            ),
        )
        snapshot = self.capture_transaction()
        auth_ledger_before = self.__auth_ledger_identity
        try:
            authorized = self._call_external(
                self.__input_authenticator,
                "input authenticator",
                "verify_and_consume_timeout_action_authorization_v1",
                action_id,
                evidence_identity,
                authorization_binding,
            )
        except Exception as exc:
            auth_ledger_after_failure = self._authenticator_sha(
                "anti_replay_state_identity_v1"
            )
            self.__auth_ledger_identity = auth_ledger_after_failure
            if auth_ledger_after_failure != auth_ledger_before:
                self._mark_pending_issuance_auth_consumed(capability)
            if isinstance(exc, C8TimedSessionRuntimeError):
                raise
            raise C8TimedSessionRuntimeError(
                "external timeout action authenticator调用失败"
            ) from exc
        auth_ledger_after = self._authenticator_sha(
            "anti_replay_state_identity_v1"
        )
        self.__auth_ledger_identity = auth_ledger_after
        if auth_ledger_after != auth_ledger_before:
            self._mark_pending_issuance_auth_consumed(capability)
        if type(authorized) is not bool or not authorized:
            raise C8TimedSessionRuntimeError(
                "external timeout action authority未授权该signed action"
            )
        if auth_ledger_after == auth_ledger_before:
            raise C8TimedSessionRuntimeError(
                "authorized timeout action未推进external anti-replay ledger"
            )
        try:
            if (
                self._adapter_sha("adapter_identity_v1")
                != prior.inner_adapter_identity
                or self._adapter_sha("session_binding_identity_v1")
                != prior.inner_session_binding_identity
                or self._adapter_sha("public_state_identity_v1")
                != prior.inner_public_state_identity
                or self._adapter_sha("authoritative_state_identity_v1")
                != prior.inner_authoritative_state_identity
            ):
                raise C8TimedSessionRuntimeError(
                    "timeout apply前inner adapter/session/public/authoritative binding drift"
                )
            result = self._call_external(
                self.__adapter,
                "inner adapter",
                "apply_signed_action_id_v1",
                action_id,
            )
            if result is not None:
                raise C8TimedSessionRuntimeError(
                    "inner signed-action passthrough必须返回None"
                )
            adapter_identity = self._adapter_sha("adapter_identity_v1")
            session_identity = self._adapter_sha("session_binding_identity_v1")
            public_identity = self._adapter_sha("public_state_identity_v1")
            authoritative_identity = self._adapter_sha(
                "authoritative_state_identity_v1"
            )
            if adapter_identity != prior.inner_adapter_identity:
                raise C8TimedSessionRuntimeError(
                    "timeout action后inner adapter identity drift"
                )
            if session_identity != prior.inner_session_binding_identity:
                raise C8TimedSessionRuntimeError(
                    "timeout action后inner session binding drift"
                )
            if (
                self._authenticator_sha("authenticator_identity_v1")
                != prior.input_authenticator_identity
                or self._authenticator_sha("anti_replay_state_identity_v1")
                != auth_ledger_after
            ):
                raise C8TimedSessionRuntimeError(
                    "timeout action后external issuance authority drift"
                )
            if authoritative_identity == prior.inner_authoritative_state_identity:
                raise C8TimedSessionRuntimeError(
                    "inner adapter接受timeout action后authoritative identity未变化"
                )
            transition_identity = _canonical_sha256(
                {
                    "schema": "sgs-c8-b-timeout-inner-transition-commitment-v1",
                    "contract_version": 1,
                    "runtime_contract_identity": C8_B_RUNTIME_CONTRACT_IDENTITY_V1,
                    "runtime_instance_identity": prior.runtime_instance_identity,
                    "window_ref_identity": ref.authority_ref_identity,
                    "timeout_due_commitment_identity": (
                        timeout_due_commitment.commitment_identity
                    ),
                    "pending_deadline_identity": pending.pending_identity,
                    "signed_action_id_commitment": action_commitment,
                    "before_inner_public_state_identity": (
                        prior.inner_public_state_identity
                    ),
                    "after_inner_public_state_identity": public_identity,
                    "before_inner_authoritative_state_identity": (
                        prior.inner_authoritative_state_identity
                    ),
                    "after_inner_authoritative_state_identity": (
                        authoritative_identity
                    ),
                    "inner_adapter_identity": adapter_identity,
                    "inner_session_binding_identity": session_identity,
                    "authorization_binding_identity": authorization_binding,
                    "authorization_evidence_identity": evidence_identity,
                    "authorization_ledger_after_identity": auth_ledger_after,
                    "pending_issuance_capability_identity": (
                        None
                        if capability is None
                        else capability.capability_identity
                    ),
                }
            )
            receipt = self._build_timeout_execution_receipt(
                runtime_instance_identity=prior.runtime_instance_identity,
                receipt_sequence=self.__next_timeout_receipt_sequence,
                previous_receipt_identity=self.__timeout_receipt_chain_tip,
                ref=ref,
                signed_action_id_commitment=action_commitment,
                pre_inner_public_state_identity=prior.inner_public_state_identity,
                pre_inner_authoritative_state_identity=(
                    prior.inner_authoritative_state_identity
                ),
                post_inner_public_state_identity=public_identity,
                post_inner_authoritative_state_identity=authoritative_identity,
                inner_adapter_identity=adapter_identity,
                inner_session_binding_identity=session_identity,
                issuance_authority_identity=prior.input_authenticator_identity,
                authorization_evidence_identity=evidence_identity,
                authorization_binding_identity=authorization_binding,
                authorization_ledger_before_identity=auth_ledger_before,
                authorization_ledger_after_identity=auth_ledger_after,
                timeout_due_commitment=timeout_due_commitment,
                outer_transition_identity=transition_identity,
                pending_issuance_capability_identity=(
                    None
                    if capability is None
                    else capability.capability_identity
                ),
            )
            candidate = self._commit(
                virtual_time_state=prior.virtual_time_state,
                pending_deadline=prior.pending_deadline,
                event_specs=(
                    {
                        "event_kind": (
                            RuntimeEventKindV1.TIMEOUT_SIGNED_ACTION_FORWARDED
                        ),
                        "window": active,
                        "inner_transition_identity": transition_identity,
                        "execution_receipt_identity": receipt.receipt_identity,
                    },
                ),
                inner_public_state_identity=public_identity,
                inner_authoritative_state_identity=authoritative_identity,
            )
            committed_event = candidate.runtime_events[-1]
            if (
                committed_event.event_kind
                is not RuntimeEventKindV1.TIMEOUT_SIGNED_ACTION_FORWARDED
                or committed_event.inner_transition_identity
                != receipt.outer_transition_identity
                or committed_event.execution_receipt_identity
                != receipt.receipt_identity
            ):
                raise C8TimedSessionRuntimeError(
                    "timeout receipt未绑定committed outer event"
                )
        except Exception as exc:
            self._restore_failed_timeout_forward(
                snapshot,
                preserved_auth_ledger_identity=auth_ledger_after,
            )
            if isinstance(exc, C8TimedSessionRuntimeError):
                raise
            raise C8TimedSessionRuntimeError(
                "inner timeout action失败；inner/outer已回滚且auth evidence保持消耗"
            ) from exc
        self.__issued_timeout_receipts[id(receipt)] = (
            receipt,
            receipt.receipt_identity,
        )
        self.__pending_timeout_receipt_identity = receipt.receipt_identity
        self.__timeout_receipt_chain_tip = receipt.receipt_identity
        self.__next_timeout_receipt_sequence += 1
        self._mark_pending_issuance_receipt_committed(capability, receipt)
        return receipt

    def continue_timeout_multi_step_obligation_v1(
        self,
        ref: WindowAuthorityRefV1,
        *,
        execution_receipt: TimeoutActionExecutionReceiptV1 | None,
        expected_step_index: int,
        logical_step_identity: str,
    ) -> DeadlinePrecedenceV1:
        """Consume one timeout receipt for one same-tick logical step only."""

        self._record_public_operation_attempt(
            "continue_timeout_multi_step_obligation_v1"
        )
        self._ensure_live_binding()
        active = self._active_for_ref(ref)
        if active.window_kind is not TimedWindowKindV1.MULTI_STEP_OBLIGATION:
            raise C8TimedSessionRuntimeError(
                "timeout continue只允许MULTI_STEP_OBLIGATION window"
            )
        eligibility = deadline_precedence_v1(
            active, self.__state.virtual_time_state.now_tick
        )
        if eligibility is not DeadlinePrecedenceV1.TIMEOUT_PRIORITY_AT_OR_AFTER_DEADLINE:
            raise C8TimedSessionRuntimeError(
                "timeout same-tick progress禁止before-deadline普通路径误用"
            )
        receipt = self._validate_timeout_execution_receipt(
            ref, execution_receipt
        )
        step_index = _exact_int(expected_step_index, "expected_step_index")
        step_identity = _exact_sha256(
            logical_step_identity, "logical_step_identity"
        )
        state = self.__state
        logical = list(state.logical_obligations)
        if not logical:
            raise C8TimedSessionRuntimeError(
                "timeout multi-step progress缺少logical obligation"
            )
        progress = logical[-1]
        if (
            progress.window_id != active.window_id
            or progress.window_binding_identity != active.window_binding_identity
            or progress.obligation_identity != active.obligation_identity
            or receipt.obligation_identity != progress.obligation_identity
        ):
            raise C8TimedSessionRuntimeError(
                "timeout receipt/logical obligation/current window binding不一致"
            )
        if step_index != progress.next_step_index:
            raise C8TimedSessionRuntimeError(
                "timeout multi-step index必须严格递增且不得跳号或重排"
            )
        if step_identity in progress.step_identities:
            raise C8TimedSessionRuntimeError(
                "timeout multi-step logical step identity重复"
            )
        logical[-1] = LogicalObligationProgressV1.build(
            window_id=progress.window_id,
            window_binding_identity=progress.window_binding_identity,
            obligation_identity=progress.obligation_identity,
            next_step_index=progress.next_step_index + 1,
            step_identities=progress.step_identities + (step_identity,),
        )
        before_virtual = state.virtual_time_state
        self._commit(
            virtual_time_state=before_virtual,
            logical_obligations=logical,
            pending_deadline=state.pending_deadline,
            event_specs=(
                {
                    "event_kind": (
                        RuntimeEventKindV1.TIMEOUT_MULTI_STEP_CONTINUED
                    ),
                    "window": active,
                    "logical_step_identity": step_identity,
                    "execution_receipt_identity": receipt.receipt_identity,
                },
            ),
        )
        self._consume_timeout_execution_receipt(receipt)
        return eligibility

    def expected_advance_authentication_binding(self, *, requested_tick: int) -> str:
        """Return the exact binding an external authenticator must authorize."""

        if self.__active_controller_callback_guard is not None:
            self._record_public_operation_attempt(
                "expected_advance_authentication_binding"
            )
        self._ensure_live_binding()
        tick = _exact_int(requested_tick, "requested_tick")
        state = self.__state
        active = state.virtual_time_state.window_stack.active_window
        if active is None or active.status is not TimedWindowStatusV1.ACTIVE:
            raise C8TimedSessionRuntimeError("TIME_ADVANCE需要ACTIVE top window")
        if tick < state.virtual_time_state.now_tick:
            raise C8TimedSessionRuntimeError("virtual time禁止负增量/倒退")
        return derive_advance_request_binding_identity_v1(
            runtime_instance_identity=state.runtime_instance_identity,
            driver_authority_identity=state.driver_authority_identity,
            duration_profile_identity=state.contract_latch.duration_profile_identity,
            previous_input_chain_tip=state.input_chain_tip,
            input_seq=state.virtual_time_state.next_input_seq,
            source_id=state.input_source_id,
            domain_id=CLOCK_DOMAIN_ID,
            window_id=active.window_id,
            requested_tick=tick,
        )
    def ingest_virtual_time_input(
        self,
        advance_input: VirtualTimeAdvanceInputV1,
        *,
        expected_previous_input_chain_tip: str,
        duration_profile_identity: str,
    ) -> TimedRuntimeAdvanceResultV1:
        self._record_public_operation_attempt("ingest_virtual_time_input")
        self._ensure_live_binding()
        if type(advance_input) is not VirtualTimeAdvanceInputV1:
            raise C8TimedSessionRuntimeError(
                "caller只能提交strict VirtualTimeAdvanceInputV1；禁止提交derived deadline"
            )
        state = self.__state
        chain_tip = _exact_sha256(
            expected_previous_input_chain_tip,
            "expected_previous_input_chain_tip",
        )
        profile_identity = _exact_sha256(
            duration_profile_identity, "duration_profile_identity"
        )
        if chain_tip != state.input_chain_tip:
            raise C8TimedSessionRuntimeError("virtual-time input跨链、stale或splice")
        if profile_identity != state.contract_latch.duration_profile_identity:
            raise C8TimedSessionRuntimeError("virtual-time input duration profile drift")
        active = state.virtual_time_state.window_stack.active_window
        if active is None:
            raise C8TimedSessionRuntimeError("TIME_ADVANCE需要ACTIVE top window")
        if advance_input.source_id != state.input_source_id:
            raise C8TimedSessionRuntimeError("virtual-time input source authority drift")
        if advance_input.domain_id != CLOCK_DOMAIN_ID:
            raise C8TimedSessionRuntimeError("virtual-time input clock domain drift")
        if advance_input.input_seq != state.virtual_time_state.next_input_seq:
            raise C8TimedSessionRuntimeError("virtual-time input sequence重复、跳号或重排")
        if advance_input.window_id != active.window_id:
            raise C8TimedSessionRuntimeError("virtual-time input绑定stale/非active window")
        if advance_input.requested_tick < state.virtual_time_state.now_tick:
            raise C8TimedSessionRuntimeError("virtual time禁止负增量/倒退")
        if state.virtual_time_state.now_tick >= active.deadline_at:
            raise C8TimedSessionRuntimeError("deadline已经到达，必须先处理timeout")
        expected_binding = derive_advance_request_binding_identity_v1(
            runtime_instance_identity=state.runtime_instance_identity,
            driver_authority_identity=state.driver_authority_identity,
            duration_profile_identity=profile_identity,
            previous_input_chain_tip=chain_tip,
            input_seq=advance_input.input_seq,
            source_id=advance_input.source_id,
            domain_id=advance_input.domain_id,
            window_id=advance_input.window_id,
            requested_tick=advance_input.requested_tick,
        )
        ledger_before = self.__auth_ledger_identity
        try:
            authorized = self._call_external(
                self.__input_authenticator,
                "input authenticator",
                "verify_and_consume_advance_authorization_v1",
                advance_input,
                expected_binding,
            )
        except Exception:
            self.__auth_ledger_identity = self._authenticator_sha(
                "anti_replay_state_identity_v1"
            )
            raise
        ledger_after = self._authenticator_sha("anti_replay_state_identity_v1")
        if type(authorized) is not bool or not authorized:
            self.__auth_ledger_identity = ledger_after
            raise C8TimedSessionRuntimeError(
                "external input authenticator未授权该virtual-time input"
            )
        if ledger_after == ledger_before:
            raise C8TimedSessionRuntimeError(
                "authorized input未推进external anti-replay ledger"
            )
        self.__auth_ledger_identity = ledger_after
        before = state.virtual_time_state
        try:
            result = advance_virtual_time_v1(before, advance_input, CLOCK_DOMAIN_V1)
        except C8VirtualTimeContractError as exc:
            raise C8TimedSessionRuntimeError(f"C8-A TIME_ADVANCE拒绝：{exc}") from exc
        after_active = result.state.window_stack.active_window
        assert after_active is not None
        derived_identity = (
            None
            if result.derived_deadline is None
            else result.derived_deadline.event_identity
        )
        record = AcceptedVirtualTimeInputV1.build(
            input_seq=advance_input.input_seq,
            input_identity=advance_input.input_identity,
            previous_input_chain_tip=state.input_chain_tip,
            before_virtual_state_identity=before.state_identity,
            after_virtual_state_identity=result.state.state_identity,
            requested_tick=result.requested_tick,
            applied_tick=result.applied_tick,
            unconsumed_ticks=result.unconsumed_ticks,
            derived_deadline_identity=derived_identity,
        )
        pending = (
            None
            if result.derived_deadline is None
            else PendingDerivedDeadlineV1.from_derived(
                result.derived_deadline, after_active
            )
        )
        specs: list[dict[str, object]] = [
            {
                "event_kind": RuntimeEventKindV1.TIME_INPUT_ACCEPTED,
                "window": after_active,
                "input_identity": advance_input.input_identity,
                "requested_tick": result.requested_tick,
                "applied_tick": result.applied_tick,
            }
        ]
        if result.derived_deadline is not None:
            specs.append(
                {
                    "event_kind": RuntimeEventKindV1.DEADLINE_DERIVED,
                    "window": after_active,
                    "input_identity": advance_input.input_identity,
                    "derived_deadline_identity": result.derived_deadline.event_identity,
                    "requested_tick": result.requested_tick,
                    "applied_tick": result.applied_tick,
                }
            )
        next_state = self._commit(
            virtual_time_state=result.state,
            input_records=state.input_records + (record,),
            pending_deadline=pending,
            event_specs=specs,
        )
        return TimedRuntimeAdvanceResultV1(
            state=next_state,
            derived_deadline=result.derived_deadline,
            requested_tick=result.requested_tick,
            applied_tick=result.applied_tick,
            consumed_ticks=result.consumed_ticks,
            unconsumed_ticks=result.unconsumed_ticks,
        )

    def _close(
        self,
        ref: WindowAuthorityRefV1,
        *,
        close_status: TimedWindowStatusV1,
        execution_receipt: TimeoutActionExecutionReceiptV1 | None,
    ) -> TimedDecisionWindowV1:
        self._ensure_live_binding()
        active = self._active_for_ref(ref)
        state = self.__state
        if close_status is TimedWindowStatusV1.CLOSED_BY_ACTION:
            if execution_receipt is not None:
                raise C8TimedSessionRuntimeError("action close禁止timeout execution receipt")
            derived_deadline_identity = None
            if (
                deadline_precedence_v1(active, state.virtual_time_state.now_tick)
                is not DeadlinePrecedenceV1.ACTION_ELIGIBLE_BEFORE_DEADLINE
            ):
                raise C8TimedSessionRuntimeError("exact deadline处timeout优先，禁止action close")
        elif close_status is TimedWindowStatusV1.CLOSED_BY_TIMEOUT:
            receipt = self._validate_timeout_execution_receipt(
                ref, execution_receipt
            )
            derived_deadline_identity = receipt.derived_deadline_identity
        else:
            raise C8TimedSessionRuntimeError("C8-B只允许action/timeout committed close")
        try:
            transition = close_decision_window_v1(
                state.virtual_time_state,
                window_id=active.window_id,
                close_status=close_status,
            )
        except C8VirtualTimeContractError as exc:
            raise C8TimedSessionRuntimeError(f"C8-A window close拒绝：{exc}") from exc
        logical = tuple(
            item for item in state.logical_obligations if item.window_id != active.window_id
        )
        event_kind = (
            RuntimeEventKindV1.WINDOW_CLOSED_BY_ACTION
            if close_status is TimedWindowStatusV1.CLOSED_BY_ACTION
            else RuntimeEventKindV1.WINDOW_CLOSED_BY_TIMEOUT
        )
        specs: list[dict[str, object]] = [
            {
                "event_kind": event_kind,
                "window": transition.closed_window,
                "related_window_id": active.parent_window_id,
                "derived_deadline_identity": derived_deadline_identity,
                "execution_receipt_identity": (
                    None
                    if close_status is TimedWindowStatusV1.CLOSED_BY_ACTION
                    else receipt.receipt_identity
                ),
            }
        ]
        resumed = transition.state.window_stack.active_window
        if resumed is not None:
            specs.append(
                {
                    "event_kind": RuntimeEventKindV1.PARENT_RESUMED_AFTER_CHILD,
                    "window": resumed,
                    "related_window_id": active.window_id,
                }
            )
        self._commit(
            virtual_time_state=transition.state,
            window_open_state_origins=state.window_open_state_origins[:-1],
            logical_obligations=logical,
            pending_deadline=None,
            event_specs=specs,
        )
        if close_status is TimedWindowStatusV1.CLOSED_BY_TIMEOUT:
            self._consume_timeout_execution_receipt(receipt)
        return transition.closed_window

    def close_window_by_action(
        self, ref: WindowAuthorityRefV1
    ) -> TimedDecisionWindowV1:
        self._record_public_operation_attempt("close_window_by_action")
        return self._close(
            ref,
            close_status=TimedWindowStatusV1.CLOSED_BY_ACTION,
            execution_receipt=None,
        )

    def close_window_by_timeout(
        self,
        ref: WindowAuthorityRefV1,
        *,
        execution_receipt: TimeoutActionExecutionReceiptV1 | None = None,
    ) -> TimedDecisionWindowV1:
        self._record_public_operation_attempt("close_window_by_timeout")
        return self._close(
            ref,
            close_status=TimedWindowStatusV1.CLOSED_BY_TIMEOUT,
            execution_receipt=execution_receipt,
        )

    def close_window_by_timeout_receipt_v1(
        self,
        ref: WindowAuthorityRefV1,
        *,
        execution_receipt: TimeoutActionExecutionReceiptV1 | None = None,
    ) -> TimedDecisionWindowV1:
        return self.close_window_by_timeout(
            ref,
            execution_receipt=execution_receipt,
        )

    def capture_transaction(self) -> TimedSessionTransactionSnapshotV1:
        self._record_public_operation_attempt("capture_transaction")
        self._ensure_live_binding()
        token = self._call_external(
            self.__adapter,
            "inner adapter",
            "capture_transaction_snapshot_v1",
        )
        token_identity = self._adapter_sha("snapshot_token_identity_v1", token)
        outer = self.__state
        virtual_snapshot = VirtualTimeTransactionSnapshotV1.capture(
            virtual_time_state=outer.virtual_time_state,
            active_fallback_chain=None,
        )
        material = {
            "schema": TRANSACTION_SNAPSHOT_SCHEMA,
            "contract_version": 1,
            "runtime_instance_identity": outer.runtime_instance_identity,
            "outer_state": outer.to_dict(),
            "virtual_time_snapshot": virtual_snapshot.to_dict(),
            "inner_adapter_identity": outer.inner_adapter_identity,
            "inner_session_binding_identity": outer.inner_session_binding_identity,
            "inner_snapshot_identity": token_identity,
            "opaque_inner_token_serialized": False,
            "live_owner_guard_bound": True,
        }
        snapshot = TimedSessionTransactionSnapshotV1(
            schema=TRANSACTION_SNAPSHOT_SCHEMA,
            contract_version=1,
            runtime_instance_identity=outer.runtime_instance_identity,
            outer_state=outer,
            virtual_time_snapshot=virtual_snapshot,
            inner_adapter_identity=outer.inner_adapter_identity,
            inner_session_binding_identity=outer.inner_session_binding_identity,
            inner_snapshot_token=token,
            inner_snapshot_identity=token_identity,
            owner_guard=self.__owner_guard,
            snapshot_identity=_canonical_sha256(material),
        )
        self.__issued_snapshots[id(snapshot)] = (
            snapshot,
            snapshot.snapshot_identity,
        )
        return snapshot

    def rollback(self, snapshot: TimedSessionTransactionSnapshotV1) -> None:
        self._record_public_operation_attempt("rollback")
        if self.__poisoned:
            raise C8TimedSessionRuntimeError(
                "C8-B runtime已因inner rollback recovery失败进入fail-closed状态"
            )
        if self.__callback_busy:
            raise C8TimedSessionRuntimeError(
                "external adapter/authenticator callback禁止重入C8-B runtime"
            )
        if type(snapshot) is not TimedSessionTransactionSnapshotV1:
            raise C8TimedSessionRuntimeError("rollback snapshot类型不正确")
        issued = self.__issued_snapshots.get(id(snapshot))
        if (
            issued is None
            or issued[0] is not snapshot
            or issued[1] != snapshot.snapshot_identity
        ):
            raise C8TimedSessionRuntimeError(
                "rollback snapshot不是current wrapper实际签发的live object"
            )
        try:
            snapshot_material = snapshot._identity_material()
        except Exception as exc:
            raise C8TimedSessionRuntimeError(
                "rollback snapshot material已被深层篡改"
            ) from exc
        _assert_identity(
            snapshot.snapshot_identity,
            snapshot_material,
            "rollback snapshot_identity",
        )
        self._ensure_live_binding()
        current = self.__state
        auth_ledger_before = self.__auth_ledger_identity
        if snapshot.owner_guard is not self.__owner_guard:
            raise C8TimedSessionRuntimeError("rollback snapshot不属于current live wrapper owner")
        if (
            snapshot.runtime_instance_identity != current.runtime_instance_identity
            or snapshot.inner_adapter_identity != current.inner_adapter_identity
            or snapshot.inner_session_binding_identity
            != current.inner_session_binding_identity
        ):
            raise C8TimedSessionRuntimeError("rollback snapshot不属于current runtime/adapter")
        if not _is_prefix(snapshot.outer_state.input_records, current.input_records):
            raise C8TimedSessionRuntimeError("rollback snapshot input chain不是current ancestor")
        if not _is_prefix(snapshot.outer_state.runtime_events, current.runtime_events):
            raise C8TimedSessionRuntimeError("rollback snapshot event chain不是current ancestor")
        if self._adapter_sha("adapter_identity_v1") != current.inner_adapter_identity:
            raise C8TimedSessionRuntimeError("rollback前inner adapter identity drift")
        if (
            self._adapter_sha("session_binding_identity_v1")
            != current.inner_session_binding_identity
        ):
            raise C8TimedSessionRuntimeError("rollback前inner session binding drift")
        if (
            self._adapter_sha(
                "snapshot_token_identity_v1", snapshot.inner_snapshot_token
            )
            != snapshot.inner_snapshot_identity
        ):
            raise C8TimedSessionRuntimeError("opaque inner snapshot token被篡改")
        backup_token = self._call_external(
            self.__adapter,
            "inner adapter",
            "capture_transaction_snapshot_v1",
        )
        backup_identity = self._adapter_sha("snapshot_token_identity_v1", backup_token)
        try:
            self._call_external(
                self.__adapter,
                "inner adapter",
                "restore_transaction_snapshot_v1",
                snapshot.inner_snapshot_token,
            )
            restored_adapter = self._adapter_sha("adapter_identity_v1")
            restored_session = self._adapter_sha("session_binding_identity_v1")
            restored_public = self._adapter_sha("public_state_identity_v1")
            restored_authoritative = self._adapter_sha("authoritative_state_identity_v1")
            restored_auth_ledger = self._authenticator_sha(
                "anti_replay_state_identity_v1"
            )
            if (
                restored_adapter != snapshot.outer_state.inner_adapter_identity
                or restored_session != snapshot.outer_state.inner_session_binding_identity
                or restored_public != snapshot.outer_state.inner_public_state_identity
                or restored_authoritative
                != snapshot.outer_state.inner_authoritative_state_identity
                or restored_auth_ledger != auth_ledger_before
            ):
                raise C8TimedSessionRuntimeError(
                    "inner restore结果与snapshot identities或external auth ledger不一致"
                )
        except Exception as exc:
            try:
                if self._adapter_sha("snapshot_token_identity_v1", backup_token) != backup_identity:
                    raise C8TimedSessionRuntimeError("rollback backup token漂移")
                self._call_external(
                    self.__adapter,
                    "inner adapter",
                    "restore_transaction_snapshot_v1",
                    backup_token,
                )
                if (
                    self._adapter_sha("adapter_identity_v1")
                    != current.inner_adapter_identity
                    or self._adapter_sha("session_binding_identity_v1")
                    != current.inner_session_binding_identity
                    or self._adapter_sha("public_state_identity_v1")
                    != current.inner_public_state_identity
                    or self._adapter_sha("authoritative_state_identity_v1")
                    != current.inner_authoritative_state_identity
                    or self._authenticator_sha("anti_replay_state_identity_v1")
                    != auth_ledger_before
                ):
                    raise C8TimedSessionRuntimeError("rollback backup restore identity不一致")
            except Exception as recovery_exc:
                self.__poisoned = True
                raise C8TimedSessionRuntimeError(
                    "inner rollback失败且backup restore失败；outer state未替换"
                ) from recovery_exc
            if isinstance(exc, C8TimedSessionRuntimeError):
                raise
            raise C8TimedSessionRuntimeError("inner rollback原子恢复失败；outer state未替换") from exc
        self.__state = snapshot.outer_state
        self._invalidate_pending_timeout_execution_receipt()

    def cancel_window_to_pre_open_snapshot(
        self,
        ref: WindowAuthorityRefV1,
        *,
        pre_open_snapshot: TimedSessionTransactionSnapshotV1,
    ) -> RollbackCancellationReceiptV1:
        self._record_public_operation_attempt(
            "cancel_window_to_pre_open_snapshot"
        )
        self._ensure_live_binding()
        active = self._active_for_ref(ref)
        current = self.__state
        target = pre_open_snapshot.outer_state
        current_windows = current.virtual_time_state.window_stack.windows
        target_windows = target.virtual_time_state.window_stack.windows
        if len(target_windows) != len(current_windows) - 1:
            raise C8TimedSessionRuntimeError("cancel snapshot必须恰为window open前一层stack")
        if active.window_id in {item.window_id for item in target_windows}:
            raise C8TimedSessionRuntimeError("cancel snapshot仍包含被取消window")
        if target.virtual_time_state.next_window_seq != active.window_sequence:
            raise C8TimedSessionRuntimeError("cancel snapshot不是该window的pre-open state")
        if target.state_identity != current.window_open_state_origins[-1]:
            raise C8TimedSessionRuntimeError("cancel snapshot不是精确紧邻的pre-open outer state")
        if not _is_prefix(target.input_records, current.input_records):
            raise C8TimedSessionRuntimeError("cancel snapshot input chain不是current prefix")
        if not _is_prefix(target.runtime_events, current.runtime_events):
            raise C8TimedSessionRuntimeError("cancel snapshot event chain不是current prefix")
        before_identity = current.state_identity
        self.rollback(pre_open_snapshot)
        material = {
            "schema": CANCELLATION_RECEIPT_SCHEMA,
            "contract_version": 1,
            "runtime_instance_identity": current.runtime_instance_identity,
            "cancelled_window_ref_identity": ref.authority_ref_identity,
            "before_state_identity": before_identity,
            "restored_state_identity": self.__state.state_identity,
            "committed_cancel_event": False,
        }
        return RollbackCancellationReceiptV1(
            **material,
            receipt_identity=_canonical_sha256(material),
        )

    def public_projection(self) -> TimedSessionPublicProjectionV1:
        if self.__active_controller_callback_guard is None:
            self._ensure_live_binding()
        else:
            self._validate_operation_attempt_evidence()
        return TimedSessionPublicProjectionV1.from_state(self.__state)


__all__ = [
    "AcceptedVirtualTimeInputV1",
    "C8BCurrentContractLatchV1",
    "C8TimedSessionRuntimeError",
    "C8TimedSessionRuntimeV1",
    "ControllerCallbackGuardResultV1",
    "ControllerCallbackGuardTokenV1",
    "ControllerCallbackInvocationResultV1",
    "ControllerCallbackLeaseV1",
    "ControllerCallbackSecurityAuditV1",
    "C8_B_CANCEL_RULE",
    "C8_B_CURRENT_CONTRACT_LATCH_V1",
    "C8_B_MILESTONE",
    "C8_B_PAUSE_AUTHORITY",
    "C8_B_RUNTIME_CONTRACT_IDENTITY_V1",
    "C8_B_RUNTIME_DESCRIPTOR_V1",
    "C8_B_RUNTIME_ID",
    "C8_B_TIMEOUT_INTEGRATION",
    "LogicalObligationProgressV1",
    "PendingDerivedDeadlineV1",
    "PendingIssuanceCapabilityOwnershipV1",
    "PendingIssuanceCapabilityStatusV1",
    "PendingTimeoutIssuanceCapabilityV1",
    "RollbackCancellationReceiptV1",
    "RuntimeEventKindV1",
    "RuntimeEventV1",
    "TimedRuntimeAdvanceResultV1",
    "TimeoutActionExecutionReceiptV1",
    "TimeoutDueCommitmentV1",
    "TimedSessionInnerAdapterV1",
    "TimedSessionOuterStateV1",
    "TimedSessionPublicProjectionV1",
    "TimedSessionTransactionSnapshotV1",
    "VirtualTimeInputAuthenticatorV1",
    "WindowAuthorityRefV1",
    "derive_advance_request_binding_identity_v1",
    "derive_timeout_action_authorization_binding_v1",
]
