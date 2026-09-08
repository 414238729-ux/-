# -*- coding: utf-8 -*-
"""C8-G1 timed 8p natural-full-game contracts (provisional).

This module is deliberately pure.  It defines the frozen G contract, driver
policy, registries, proof/result types, sentinel selection, and promotion
rules.  It does not create a production session and it cannot turn serialized
``ready``/``passed`` booleans into authority.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import hashlib
import json
import re
from types import MappingProxyType
from typing import Any, ClassVar, Final, Iterable, Mapping, Sequence


class C8G1ContractError(ValueError):
    """Fail-closed C8-G1 contract, registry, or promotion error."""


C8_G1_CONTRACT_ID: Final[str] = "c8-timed-8p-natural-full-game-acceptance-v4"
C8_G1_CONTRACT_VERSION: Final[int] = 4
C8_G1_DRIVER_MATERIAL_VERSION: Final[int] = 3
C8_G1_SCOPE_MARKER: Final[str] = (
    "C8_TIMED_8P_NATURAL_FULL_GAME_ACCEPTANCE_ONLY"
)
C8_G1_SELECTED_MODE_ID: Final[str] = "C8_TIMED_8P_DETERMINISTIC_VIRTUAL_TIME_V1"
C8_G1_BASE_MODE_ID: Final[str] = "formal_no_skill_identity_8p"
C8_G1_BASE_FULL_GAME_CONTRACT_ID: Final[str] = (
    "authoritative-no-skill-full-game-v1"
)
C8_G1_TIMER_PROFILE_ID: Final[str] = (
    "c8-engineering-test-duration-profile-v1"
)
C8_G1_TIMER_PROFILE_STATUS: Final[str] = "NON_OFFICIAL_ENGINEERING_PROFILE"
C8_G1_DRIVER_POLICY_ID: Final[str] = (
    "c8-g-public-context-ordinal-periodic-timeout-v3"
)
C8_G1_REPLAY_SCHEMA: Final[str] = "sgs-c8-timed-8p-full-game-replay-v4"
C8_G1_RUNNER_SCHEMA: Final[str] = "sgs-c8-timed-8p-full-game-runner-v4"
C8_G1_CELL_SCHEMA: Final[str] = "sgs-c8-timed-8p-full-game-cell-proof-v4"
C8_G1_MATRIX_SCHEMA: Final[str] = "sgs-c8-timed-8p-full-game-matrix-v4"
C8_G1_REGISTRY_SCHEMA: Final[str] = "sgs-c8-timed-8p-full-game-registry-v4"
C8_G1_PROGRESS_SCHEMA: Final[str] = "sgs-c8-timed-8p-full-game-progress-v4"
C8_G1_PROMOTION_SCHEMA: Final[str] = "sgs-c8-g1-promotion-decision-v4"
C8_G1_BASELINE_SEEDS: Final[tuple[int, ...]] = (0, 1, 49)
C8_G1_SENTINEL_SEED_MIN: Final[int] = 0
C8_G1_SENTINEL_SEED_MAX: Final[int] = 99
C8_G1_MAX_PRODUCTION_STEPS_GUARD: Final[int] = 4000
C8_G1_MAX_TIMER_WINDOWS_GUARD: Final[int] = 8192
C8_G1_MAX_SAME_TICK_CHAIN: Final[int] = 8
C8_G1_WINDOW_DURATION_TICKS: Final[int] = 100
C8_G1_FULL_GAME_REPLAY_EXECUTION: Final[str] = "NOT_PROVEN"
C8_G1_E_ADAPTER_ID: Final[str] = "c8-c6-production-adapter-v1"
C8_G1_E_CONTRACT_IDENTITY: Final[str] = (
    "17fd08db5270dfa2b7ccbbdc973ce61643d296a3b94158c8fc8a15a7f5138a8c"
)
C8_G1_C_CONTROLLER_CONTRACT_IDENTITY: Final[str] = (
    "924c9712502cd24ccc4f77e5fce221b04f83b5257d51858f3ee6410e89390336"
)
C8_G1_V2_PRIOR_IDENTITIES: Final[Mapping[str, str]] = MappingProxyType({
    "contract": "223ac11dbc3b41981a1d7f83578a53fc86ebe06831d3801eaaa69cfe1113d299",
    "replay_contract": "ddf20a6949db2e95c1d4b0a46e37da19432e38ad2c9e011cd424cd9e4bbdacc1",
    "development": "f457c5a465659b3da7617fc7b643ddf51376ae3595bc81e0668a36c41e02dfd9",
    "current": "f0d6a623e485426f06e2d33d055c7d329202cef825519218fdc48c8fabc51c30",
})
C8_G1_PRIOR_STATUS: Final[str] = "IMPLEMENTED_PROVISIONAL"
C8_G1_SUPERSESSION_STATUS: Final[str] = (
    "SUPERSEDED_FOR_CURRENT_G3_SCHEMA"
)
C8_G1_PRIOR_DRIVER_POLICY_IDENTITY: Final[str] = (
    "fabdb6bf6cca2448ea6fe3a3d0c09dd94320146ab6a3d6f08511a0c39e2cc923"
)
C8_G2_STATUS: Final[str] = "PARTIAL_DRAFT_NOT_DELIVERED"
C8_G2_PRIOR_BOUNDED_SMOKE_STATUS: Final[str] = (
    "FAILED_AT_WINDOW_4_NO_ARTIFACT"
)
C8_FULL_GAME_STATUS: Final[str] = "NOT_PROVEN"
C8_FULL_GAME_MATRIX_STATUS: Final[str] = "NOT_STARTED"

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_TEXT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")
_ZERO_SHA256: Final[str] = "0" * 64


def canonical_json_bytes_v1(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def identity_v1(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes_v1(value)).hexdigest()


def _plain(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if type(value) in (tuple, list):
        return [_plain(item) for item in value]
    if isinstance(value, Enum):
        return value.value
    return value


def _freeze(value: object) -> object:
    if type(value) is dict:
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if type(value) is list:
        return tuple(_freeze(item) for item in value)
    return value


def _exact_dict(value: object, label: str) -> dict[str, Any]:
    if type(value) is not dict:
        raise C8G1ContractError(f"{label}必须是精确JSON object")
    if any(type(key) is not str for key in value):
        raise C8G1ContractError(f"{label}字段名必须是精确字符串")
    return value


def _exact_list(value: object, label: str) -> list[Any]:
    if type(value) is not list:
        raise C8G1ContractError(f"{label}必须是精确JSON array")
    return value


def _exact_keys(value: object, expected: frozenset[str], label: str) -> dict[str, Any]:
    data = _exact_dict(value, label)
    actual = frozenset(data)
    if actual != expected:
        raise C8G1ContractError(
            f"{label}字段不匹配 missing={sorted(expected - actual)} "
            f"extra={sorted(actual - expected)}"
        )
    return data


def _text(value: object, label: str, *, allow_empty: bool = False) -> str:
    if type(value) is not str or (not allow_empty and not value):
        raise C8G1ContractError(f"{label}必须是精确字符串")
    return value


def _text_id(value: object, label: str) -> str:
    result = _text(value, label)
    if _TEXT_ID_RE.fullmatch(result) is None:
        raise C8G1ContractError(f"{label}不是canonical text id")
    return result


def _sha256(value: object, label: str, *, allow_zero: bool = False) -> str:
    result = _text(value, label)
    if _SHA256_RE.fullmatch(result) is None:
        raise C8G1ContractError(f"{label}必须是canonical SHA-256")
    if not allow_zero and result == _ZERO_SHA256:
        raise C8G1ContractError(f"{label}不得是全零SHA-256")
    return result


def _integer(value: object, label: str, *, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise C8G1ContractError(f"{label}必须是精确int且 >= {minimum}")
    return value


def _boolean(value: object, label: str) -> bool:
    if type(value) is not bool:
        raise C8G1ContractError(f"{label}必须是精确bool")
    return value


def _optional_text_id(value: object, label: str) -> str | None:
    if value is None:
        return None
    return _text_id(value, label)


def _optional_sha256(value: object, label: str) -> str | None:
    if value is None:
        return None
    return _sha256(value, label)


def _optional_integer(
    value: object, label: str, *, minimum: int = 0
) -> int | None:
    if value is None:
        return None
    return _integer(value, label, minimum=minimum)


def _enum_value(enum_type: type[Enum], value: object, label: str) -> Any:
    raw = _text(value, label)
    try:
        return enum_type(raw)
    except ValueError as exc:
        raise C8G1ContractError(f"{label}不是允许值：{raw}") from exc


_FROZEN_EXTERNAL_DESCRIPTOR: Final[Mapping[str, object]] = MappingProxyType(
    {
        "base_full_game_contract_id": C8_G1_BASE_FULL_GAME_CONTRACT_ID,
        "base_mode_id": C8_G1_BASE_MODE_ID,
        "baseline_seeds": list(C8_G1_BASELINE_SEEDS),
        "cell_schema": C8_G1_CELL_SCHEMA,
        "contract_id": C8_G1_CONTRACT_ID,
        "contract_version": C8_G1_CONTRACT_VERSION,
        "supersedes_contract_identity": (
            "64240606ca5a09ef3601e4b681203a513cb67966c93f1e691f33233c0e63d153"
        ),
        "supersession_status": C8_G1_SUPERSESSION_STATUS,
        "driver_policy_id": C8_G1_DRIVER_POLICY_ID,
        "dying_rescue_requirement": "MATRIX_UNION_REQUIRED_IF_APPLICABLE",
        "full_game_scope_marker": C8_G1_SCOPE_MARKER,
        "max_production_steps_guard": C8_G1_MAX_PRODUCTION_STEPS_GUARD,
        "max_timer_windows_guard": C8_G1_MAX_TIMER_WINDOWS_GUARD,
        "natural_terminal_required": True,
        "nested_response_requirement": "MATRIX_UNION_REQUIRED_IF_APPLICABLE",
        "parent_child_relation_model": {
            "intra_decision_nested_child": (
                "ACTIVE_PARENT_SUSPEND_CHILD_CLOSE_RESUME_REMAINING_BUDGET"
            ),
            "intra_decision_selected_c6_applicability": (
                "NOT_APPLICABLE_IN_C6_NO_SKILL_8P_BY_STRUCTURAL_AUTHORITY"
            ),
            "post_commit_causal_child": (
                "PARENT_COMMITTED_CLOSED_THEN_FRESH_CHILD_WITH_CAUSAL_LINEAGE"
            ),
            "post_commit_causal_successor": (
                "PARENT_COMMITTED_CLOSED_THEN_FRESH_SUCCESSOR_WITH_CAUSAL_LINEAGE"
            ),
            "post_commit_active_parent_ref": None,
            "post_commit_parent_deadline_reuse": "FORBIDDEN",
            "post_commit_suspend_resume": "FORBIDDEN",
        },
        "replay_schema": C8_G1_REPLAY_SCHEMA,
        "typed_production_evidence": "ON_TIME_CONTINUED_OR_CLOSED_TIMEOUT_RECEIPT_CLOSED",
        "window_step_domain": "ONE_OPEN_MANY_ORDERED_ACCEPTED_STEPS_SAME_REF_DEADLINE_TICK",
        "liveness_policy": "PUBLIC_ORDER_SHAPE_CERTIFIED_MONOTONIC_POLICY_V1",
        "execution_order_profile": "PYTHONHASHSEED_0_BEFORE_START_EXACT_BUILD_EXECUTABLE_SLOT_ORDER",
        "accepted_step_invariant": "INNER_INDEX_I_G_STEP_I_PLUS_1_PRODUCTION_STEP_COUNT_PLUS_1",
        "state_revision_invariant": "ACTUAL_NONDECREASING_AND_EXACT_BOTH_FRESH_PATHS",
        "inner_replay_schema": "sgs-production-basic-batch-reexecution-v1",
        "driver_material_version": C8_G1_DRIVER_MATERIAL_VERSION,
        "runner_schema": C8_G1_RUNNER_SCHEMA,
        "selected_mode_id": C8_G1_SELECTED_MODE_ID,
        "sentinel_seed_range": [C8_G1_SENTINEL_SEED_MIN, C8_G1_SENTINEL_SEED_MAX],
        "timeout_schedule": {
            "global_window_index_base": 1,
            "timeout_modulo": 4,
            "timeout_remainder": 0,
            "unresolved_context_policy": "FORCE_ON_TIME_AND_RECORD",
        },
        "timer_profile_id": C8_G1_TIMER_PROFILE_ID,
        "timer_profile_status": C8_G1_TIMER_PROFILE_STATUS,
    }
)
C8_G1_PRIOR_CONTRACT_IDENTITY: Final[str] = (
    "901bcfd02449786ee2a527b54eeaa435b293c588f5910fc17965c0f08a089472"
)
C8_G1_CONTRACT_IDENTITY: Final[str] = identity_v1(dict(_FROZEN_EXTERNAL_DESCRIPTOR))
C8_G1_CONTRACT_MATERIAL_IDENTITY: Final[str] = C8_G1_CONTRACT_IDENTITY


def contract_descriptor_v1() -> dict[str, object]:
    return _plain(_FROZEN_EXTERNAL_DESCRIPTOR)  # type: ignore[return-value]


class ObligationLevelV1(str, Enum):
    PER_CELL_REQUIRED = "PER_CELL_REQUIRED"
    MATRIX_UNION_REQUIRED = "MATRIX_UNION_REQUIRED"
    CONDITIONAL_MATRIX_UNION_REQUIRED = "CONDITIONAL_MATRIX_UNION_REQUIRED"
    AUDITED_PREREQUISITE = "AUDITED_PREREQUISITE"
    NOT_APPLICABLE_IN_C6_NO_SKILL_8P = "NOT_APPLICABLE_IN_C6_NO_SKILL_8P"


class ObligationApplicabilityV1(str, Enum):
    APPLICABLE = "APPLICABLE"
    APPLICABLE_IF_NATURALLY_OBSERVED = "APPLICABLE_IF_NATURALLY_OBSERVED"
    AUDITED_PREREQUISITE = "AUDITED_PREREQUISITE"
    NOT_APPLICABLE_IN_C6_NO_SKILL_8P = "NOT_APPLICABLE_IN_C6_NO_SKILL_8P"


class WitnessStatusV1(str, Enum):
    OBSERVED = "OBSERVED"
    MISSING = "MISSING"
    NOT_NATURALLY_OBSERVED = "NOT_NATURALLY_OBSERVED"
    NOT_APPLICABLE_IN_C6_NO_SKILL_8P = "NOT_APPLICABLE_IN_C6_NO_SKILL_8P"
    AUDITED_PREREQUISITE_PASSED = "AUDITED_PREREQUISITE_PASSED"


class CandidateScopeV1(str, Enum):
    FORMAL_QUALITY_CANDIDATE = "FORMAL_QUALITY_CANDIDATE"
    ORDINARY_DISCOVERY = "ORDINARY_DISCOVERY"
    BOUNDED_TRACE = "BOUNDED_TRACE"
    SYNTHETIC_REPLAY = "SYNTHETIC_REPLAY"
    REPORT_ONLY = "REPORT_ONLY"


class CellRunStatusV1(str, Enum):
    COMPLETE = "COMPLETE"
    FAILED = "FAILED"
    INCOMPLETE = "INCOMPLETE"
    FAILED_INCOMPLETE_SAFETY_CAP = "FAILED_INCOMPLETE_SAFETY_CAP"


class SentinelSelectionStatusV1(str, Enum):
    COMPLETE = "COMPLETE"
    DISCOVERY_IN_PROGRESS = "DISCOVERY_IN_PROGRESS"
    SENTINEL_DISCOVERY_BLOCKED = "SENTINEL_DISCOVERY_BLOCKED"


class PromotionStatusV1(str, Enum):
    PROMOTABLE_TO_FORMAL = "PROMOTABLE_TO_FORMAL"
    NOT_PROMOTABLE = "NOT_PROMOTABLE"


class MatrixStatusV1(str, Enum):
    PASSED_PROVISIONAL_PENDING_EXTERNAL_AUDIT = (
        "PASSED_PROVISIONAL_PENDING_EXTERNAL_AUDIT"
    )
    FAILED = "FAILED"
    INCOMPLETE = "INCOMPLETE"


class PublicWindowKindV1(str, Enum):
    PLAY = "PLAY"
    OPTIONAL_RESPONSE = "OPTIONAL_RESPONSE"
    RESCUE_RESPONSE = "RESCUE_RESPONSE"
    OPTIONAL_SKILL_DECISION = "OPTIONAL_SKILL_DECISION"
    PRIVATE_ORDINAL_TIMEOUT_UNRESOLVED = "PRIVATE_ORDINAL_TIMEOUT_UNRESOLVED"
    MULTI_STEP_OBLIGATION = "MULTI_STEP_OBLIGATION"
    OTHER_PUBLIC = "OTHER_PUBLIC"


class TimeoutApplicabilityV1(str, Enum):
    APPLICABLE = "APPLICABLE"
    PRIVATE_ORDINAL_TIMEOUT_UNRESOLVED = "PRIVATE_ORDINAL_TIMEOUT_UNRESOLVED"
    NOT_APPLICABLE_IN_C6_NO_SKILL_8P = "NOT_APPLICABLE_IN_C6_NO_SKILL_8P"


class DriverDecisionMarkerV1(str, Enum):
    ON_TIME = "ON_TIME"
    TIMEOUT = "TIMEOUT"
    TIMEOUT_INTENT_SKIPPED_UNRESOLVED = "TIMEOUT_INTENT_SKIPPED_UNRESOLVED"


class CausalRelationKindV2(str, Enum):
    INDEPENDENT_DECISION = "INDEPENDENT_DECISION"
    INTRA_DECISION_NESTED_CHILD = "INTRA_DECISION_NESTED_CHILD"
    POST_COMMIT_CAUSAL_CHILD = "POST_COMMIT_CAUSAL_CHILD"
    POST_COMMIT_CAUSAL_SUCCESSOR = "POST_COMMIT_CAUSAL_SUCCESSOR"


@dataclass(frozen=True, slots=True)
class DecisionCompletionEvidenceV1:
    """G completion commitment; never a B timeout receipt or live authority."""

    decision_kind: str
    decision_evidence_identity: str
    action_binding_identity: str
    disposition: str
    disposition_event_identity: str
    post_step_observation_identity: str
    completion_identity: str = ""

    def __post_init__(self) -> None:
        expected = {"ON_TIME_PRODUCTION_DECISION": {"CLOSED_BY_ACTION", "CONTINUED"},
                    "TIMEOUT_PRODUCTION_DECISION": {"CLOSED_BY_TIMEOUT"}}
        if self.decision_kind not in expected or self.disposition not in expected[self.decision_kind]:
            raise C8G1ContractError("completion分支与当前E的actual disposition不一致")
        for key in ("decision_evidence_identity", "action_binding_identity",
                    "disposition_event_identity", "post_step_observation_identity"):
            _sha256(getattr(self, key), key)
        material = self.to_dict()
        material.pop("completion_identity")
        digest = identity_v1(material)
        if self.completion_identity and self.completion_identity != digest:
            raise C8G1ContractError("completion identity mismatch")
        object.__setattr__(self, "completion_identity", digest)

    def to_dict(self) -> dict[str, object]:
        return {"schema": "sgs-c8-g-decision-completion-evidence-v1",
                **{key: getattr(self, key) for key in self.__dataclass_fields__}}

    @classmethod
    def from_dict(cls, value: object) -> "DecisionCompletionEvidenceV1":
        data = _exact_keys(value, frozenset(cls.__dataclass_fields__) | {"schema"}, "completion")
        if data["schema"] != "sgs-c8-g-decision-completion-evidence-v1":
            raise C8G1ContractError("completion schema mismatch")
        _sha256(data["completion_identity"], "completion_identity")
        return cls(**{key: data[key] for key in cls.__dataclass_fields__})


def parent_close_evidence_identity_v3(**values: object) -> str:
    expected = frozenset({
        "causal_parent_window_identity", "originating_step_identity",
        "originating_decision_kind", "originating_decision_evidence_identity",
        "originating_completion_identity", "parent_window_close_status",
    })
    _exact_keys(values, expected, "typed parent close")
    for key in expected - {"originating_decision_kind", "parent_window_close_status"}:
        _sha256(values[key], key)
    kinds = {"ON_TIME_PRODUCTION_DECISION": "CLOSED_BY_ACTION",
             "TIMEOUT_PRODUCTION_DECISION": "CLOSED_BY_TIMEOUT"}
    if values["originating_decision_kind"] not in kinds or (
        kinds[values["originating_decision_kind"]] != values["parent_window_close_status"]
    ):
        raise C8G1ContractError("typed parent分支与实际close不匹配")
    return identity_v1({"schema": "sgs-c8-g1-parent-close-evidence-v3", **values})


def post_step_observe_identity_v2(
    *,
    originating_step_identity: str,
    originating_post_production_revision: int,
    originating_post_public_state_identity: str,
    causal_parent_context_identity: str,
    post_step_context_identity: str,
) -> str:
    return identity_v1(
        {
            "schema": "sgs-c8-g1-post-step-observe-evidence-v3",
            "contract_version": C8_G1_CONTRACT_VERSION,
            "originating_step_identity": _sha256(
                originating_step_identity, "originating_step_identity"
            ),
            "originating_post_production_revision": _integer(
                originating_post_production_revision,
                "originating_post_production_revision",
            ),
            "originating_post_public_state_identity": _sha256(
                originating_post_public_state_identity,
                "originating_post_public_state_identity",
            ),
            "causal_parent_context_identity": _sha256(
                causal_parent_context_identity, "causal_parent_context_identity"
            ),
            "post_step_context_identity": _sha256(
                post_step_context_identity, "post_step_context_identity"
            ),
        }
    )


@dataclass(frozen=True, slots=True)
class WindowRelationEvidenceV3:
    causal_relation_kind: CausalRelationKindV2
    active_parent_window_id: str | None = None
    active_parent_window_identity: str | None = None
    causal_parent_window_identity: str | None = None
    causal_parent_context_identity: str | None = None
    expected_active_parent_ref: str | None = None
    parent_decision_committed: bool = False
    originating_step_index: int | None = None
    originating_step_identity: str | None = None
    originating_post_production_revision: int | None = None
    originating_post_public_state_identity: str | None = None
    originating_decision_kind: str | None = None
    originating_decision_evidence_identity: str | None = None
    originating_completion_identity: str | None = None
    parent_window_close_status: str | None = None
    parent_window_close_evidence_identity: str | None = None
    post_step_observe_identity: str | None = None
    post_step_context_identity: str | None = None
    parent_closed_before_child_open: bool = False

    def __post_init__(self) -> None:
        if type(self.causal_relation_kind) is not CausalRelationKindV2:
            raise C8G1ContractError("causal relation必须使用versioned enum")
        for key in self.__dataclass_fields__:
            value = getattr(self, key)
            if key.endswith("identity") or key == "expected_active_parent_ref":
                _optional_sha256(value, key)
        _optional_text_id(self.active_parent_window_id, "active_parent_window_id")
        _optional_integer(self.originating_step_index, "originating_step_index", minimum=1)
        _optional_integer(self.originating_post_production_revision, "post_revision")
        _boolean(self.parent_decision_committed, "parent_decision_committed")
        _boolean(self.parent_closed_before_child_open, "parent_closed_before_child_open")
        active = (self.active_parent_window_id, self.active_parent_window_identity,
                  self.expected_active_parent_ref)
        causal = tuple(getattr(self, key) for key in self.__dataclass_fields__
                       if key.startswith("originating_") or key in {
                           "causal_parent_window_identity", "causal_parent_context_identity",
                           "parent_window_close_status", "parent_window_close_evidence_identity",
                           "post_step_observe_identity", "post_step_context_identity"})
        kind = self.causal_relation_kind
        if kind in {CausalRelationKindV2.INDEPENDENT_DECISION,
                    CausalRelationKindV2.INTRA_DECISION_NESTED_CHILD}:
            if any(v is not None for v in causal) or self.parent_decision_committed or self.parent_closed_before_child_open:
                raise C8G1ContractError("非post-commit relation不得携带closed-parent证据")
            if kind is CausalRelationKindV2.INDEPENDENT_DECISION:
                if any(v is not None for v in active):
                    raise C8G1ContractError("independent decision不得伪造parent")
            elif any(v is None for v in active) or self.expected_active_parent_ref != self.active_parent_window_identity:
                raise C8G1ContractError("intra child缺少active parent authority")
            return
        if any(v is not None for v in active):
            raise C8G1ContractError("已关闭parent不得恢复active authority")
        if any(v is None for v in causal) or not self.parent_decision_committed or not self.parent_closed_before_child_open:
            raise C8G1ContractError("post-commit relation缺少typed completion lineage")
        close = parent_close_evidence_identity_v3(**{
            key: getattr(self, key) for key in (
                "causal_parent_window_identity", "originating_step_identity",
                "originating_decision_kind", "originating_decision_evidence_identity",
                "originating_completion_identity", "parent_window_close_status")})
        if close != self.parent_window_close_evidence_identity:
            raise C8G1ContractError("parent close evidence identity mismatch")
        observe = post_step_observe_identity_v2(
            originating_step_identity=self.originating_step_identity,
            originating_post_production_revision=self.originating_post_production_revision,
            originating_post_public_state_identity=self.originating_post_public_state_identity,
            causal_parent_context_identity=self.causal_parent_context_identity,
            post_step_context_identity=self.post_step_context_identity)
        if observe != self.post_step_observe_identity:
            raise C8G1ContractError("post-step observe identity mismatch")

    @classmethod
    def independent_decision_v3(cls) -> "WindowRelationEvidenceV3":
        return cls(CausalRelationKindV2.INDEPENDENT_DECISION)

    @classmethod
    def intra_decision_nested_child_v3(cls, *, active_parent_window_id: str,
                                     active_parent_window_identity: str) -> "WindowRelationEvidenceV3":
        return cls(CausalRelationKindV2.INTRA_DECISION_NESTED_CHILD,
                   active_parent_window_id=active_parent_window_id,
                   active_parent_window_identity=active_parent_window_identity,
                   expected_active_parent_ref=active_parent_window_identity)

    @classmethod
    def post_commit_v3(cls, **values: object) -> "WindowRelationEvidenceV3":
        if values.get("causal_relation_kind") not in {
            CausalRelationKindV2.POST_COMMIT_CAUSAL_CHILD,
            CausalRelationKindV2.POST_COMMIT_CAUSAL_SUCCESSOR,
        }:
            raise C8G1ContractError("post_commit仅允许causal child/successor")
        close = parent_close_evidence_identity_v3(**{key: values[key] for key in (
            "causal_parent_window_identity", "originating_step_identity",
            "originating_decision_kind", "originating_decision_evidence_identity",
            "originating_completion_identity", "parent_window_close_status")})
        observe = post_step_observe_identity_v2(**{key: values[key] for key in (
            "originating_step_identity", "originating_post_production_revision",
            "originating_post_public_state_identity", "causal_parent_context_identity",
            "post_step_context_identity")})
        return cls(**values, parent_decision_committed=True,
                   parent_closed_before_child_open=True,
                   parent_window_close_evidence_identity=close, post_step_observe_identity=observe)

    def to_dict(self) -> dict[str, object]:
        return {"schema": "sgs-c8-g1-window-relation-evidence-v3", "contract_version": 3,
                **{key: (getattr(self, key).value if key == "causal_relation_kind" else getattr(self, key))
                   for key in self.__dataclass_fields__}}

    @classmethod
    def from_dict(cls, value: object) -> "WindowRelationEvidenceV3":
        data = _exact_keys(value, frozenset(cls.__dataclass_fields__) | {"schema", "contract_version"}, "typed relation")
        if data["schema"] != "sgs-c8-g1-window-relation-evidence-v3" or _integer(data["contract_version"], "version") != 3:
            raise C8G1ContractError("旧relation schema禁止恢复current证据")
        values = {key: data[key] for key in cls.__dataclass_fields__}
        values["causal_relation_kind"] = _enum_value(CausalRelationKindV2, values["causal_relation_kind"], "relation kind")
        return cls(**values)


def classify_post_commit_relation_v2(
    *,
    window_kind: PublicWindowKindV1,
    causal_parent_context_identity: str | None,
) -> CausalRelationKindV2:
    if not isinstance(window_kind, PublicWindowKindV1):
        raise C8G1ContractError("classification window_kind非法")
    if causal_parent_context_identity is None:
        return CausalRelationKindV2.INDEPENDENT_DECISION
    _sha256(causal_parent_context_identity, "causal_parent_context_identity")
    if window_kind in {
        PublicWindowKindV1.OPTIONAL_RESPONSE,
        PublicWindowKindV1.RESCUE_RESPONSE,
    }:
        return CausalRelationKindV2.POST_COMMIT_CAUSAL_CHILD
    return CausalRelationKindV2.POST_COMMIT_CAUSAL_SUCCESSOR


def validate_relation_window_kind_v2(
    relation: WindowRelationEvidenceV3,
    window_kind: PublicWindowKindV1,
) -> None:
    if not isinstance(relation, WindowRelationEvidenceV3):
        raise C8G1ContractError("relation必须是WindowRelationEvidenceV3")
    if not isinstance(window_kind, PublicWindowKindV1):
        raise C8G1ContractError("window_kind必须是PublicWindowKindV1")
    if relation.causal_relation_kind is CausalRelationKindV2.POST_COMMIT_CAUSAL_CHILD:
        if window_kind not in {
            PublicWindowKindV1.OPTIONAL_RESPONSE,
            PublicWindowKindV1.RESCUE_RESPONSE,
        }:
            raise C8G1ContractError(
                "POST_COMMIT_CAUSAL_CHILD必须是真实optional-response或dying/rescue"
            )
    elif relation.causal_relation_kind is (
        CausalRelationKindV2.POST_COMMIT_CAUSAL_SUCCESSOR
    ) and window_kind in {
        PublicWindowKindV1.OPTIONAL_RESPONSE,
        PublicWindowKindV1.RESCUE_RESPONSE,
    }:
        raise C8G1ContractError("response/dying context不得降级为causal successor")


@dataclass(frozen=True, slots=True)
class RequiredEventObligationV1:
    obligation_id: str
    semantic_name: str
    level: ObligationLevelV1
    applicability: ObligationApplicabilityV1
    production_evidence_required: bool

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "obligation_id",
            "semantic_name",
            "level",
            "applicability",
            "production_evidence_required",
        }
    )

    def __post_init__(self) -> None:
        if not self.obligation_id.startswith("FG-TIMER-"):
            raise C8G1ContractError("obligation_id必须是FG-TIMER-* canonical id")
        _text_id(self.semantic_name, "semantic_name")
        if not isinstance(self.level, ObligationLevelV1):
            raise C8G1ContractError("level必须是ObligationLevelV1")
        if not isinstance(self.applicability, ObligationApplicabilityV1):
            raise C8G1ContractError("applicability必须是ObligationApplicabilityV1")
        _boolean(self.production_evidence_required, "production_evidence_required")

    def to_dict(self) -> dict[str, object]:
        return {
            "obligation_id": self.obligation_id,
            "semantic_name": self.semantic_name,
            "level": self.level.value,
            "applicability": self.applicability.value,
            "production_evidence_required": self.production_evidence_required,
        }

    @classmethod
    def from_dict(cls, value: object) -> "RequiredEventObligationV1":
        data = _exact_keys(value, cls._FIELDS, "required-event obligation")
        return cls(
            obligation_id=_text_id(data["obligation_id"], "obligation_id"),
            semantic_name=_text_id(data["semantic_name"], "semantic_name"),
            level=_enum_value(ObligationLevelV1, data["level"], "level"),
            applicability=_enum_value(
                ObligationApplicabilityV1,
                data["applicability"],
                "applicability",
            ),
            production_evidence_required=_boolean(
                data["production_evidence_required"],
                "production_evidence_required",
            ),
        )


_OBLIGATION_ROWS: Final[
    tuple[
        tuple[
            str,
            str,
            ObligationLevelV1,
            ObligationApplicabilityV1,
            bool,
        ],
        ...,
    ]
] = (
    ("FG-TIMER-01", "ON_TIME_ACTION_BEFORE_DEADLINE", ObligationLevelV1.PER_CELL_REQUIRED, ObligationApplicabilityV1.APPLICABLE, True),
    ("FG-TIMER-02", "EXACT_DEADLINE_TIMEOUT_FALLBACK", ObligationLevelV1.PER_CELL_REQUIRED, ObligationApplicabilityV1.APPLICABLE, True),
    ("FG-TIMER-03", "CONSECUTIVE_WINDOWS_SAME_CONTEXT_NO_REFRESH", ObligationLevelV1.PER_CELL_REQUIRED, ObligationApplicabilityV1.APPLICABLE, True),
    ("FG-TIMER-04", "PHASE_TRANSITION_POST_COMMIT_SUCCESSOR_CLEANUP", ObligationLevelV1.PER_CELL_REQUIRED, ObligationApplicabilityV1.APPLICABLE, True),
    ("FG-TIMER-05", "TURN_ACTOR_BOUNDARY_CLEANUP", ObligationLevelV1.PER_CELL_REQUIRED, ObligationApplicabilityV1.APPLICABLE, True),
    ("FG-TIMER-06", "STALE_EVIDENCE_REJECTION", ObligationLevelV1.PER_CELL_REQUIRED, ObligationApplicabilityV1.APPLICABLE, True),
    ("FG-TIMER-07", "POST_COMMIT_OPTIONAL_RESPONSE_CAUSAL_CHILD_TIMER", ObligationLevelV1.MATRIX_UNION_REQUIRED, ObligationApplicabilityV1.APPLICABLE, True),
    ("FG-TIMER-08", "POST_COMMIT_DYING_RESCUE_CAUSAL_CHILD_TIMER", ObligationLevelV1.MATRIX_UNION_REQUIRED, ObligationApplicabilityV1.APPLICABLE, True),
    ("FG-TIMER-09", "UNRESOLVED_PRIVATE_MANDATORY_CHOICE_FAIL_CLOSED", ObligationLevelV1.CONDITIONAL_MATRIX_UNION_REQUIRED, ObligationApplicabilityV1.APPLICABLE_IF_NATURALLY_OBSERVED, True),
    ("FG-TIMER-10", "NATURAL_TERMINAL_TIMER_CLEANUP", ObligationLevelV1.PER_CELL_REQUIRED, ObligationApplicabilityV1.APPLICABLE, True),
    ("FG-TIMER-11", "PRODUCTION_TRANSACTION_ROLLBACK_PREREQUISITE", ObligationLevelV1.AUDITED_PREREQUISITE, ObligationApplicabilityV1.AUDITED_PREREQUISITE, False),
    ("FG-TIMER-12", "FULL_GAME_COLD_REPLAY", ObligationLevelV1.PER_CELL_REQUIRED, ObligationApplicabilityV1.APPLICABLE, True),
    ("FG-TIMER-13", "INTRA_DECISION_NESTED_CHILD_PAUSE_RESUME_AUTHORITY", ObligationLevelV1.AUDITED_PREREQUISITE, ObligationApplicabilityV1.NOT_APPLICABLE_IN_C6_NO_SKILL_8P, False),
)
REQUIRED_EVENT_OBLIGATIONS_V1: Final[tuple[RequiredEventObligationV1, ...]] = tuple(
    RequiredEventObligationV1(*row) for row in _OBLIGATION_ROWS
)
REQUIRED_EVENT_OBLIGATION_IDS_V1: Final[tuple[str, ...]] = tuple(
    item.obligation_id for item in REQUIRED_EVENT_OBLIGATIONS_V1
)
REQUIRED_EVENT_REGISTRY_IDENTITY_V1: Final[str] = identity_v1(
    [item.to_dict() for item in REQUIRED_EVENT_OBLIGATIONS_V1]
)


@dataclass(frozen=True, slots=True)
class RequiredEventWitnessV1:
    obligation_id: str
    level: ObligationLevelV1
    applicability: ObligationApplicabilityV1
    status: WitnessStatusV1
    witness_identities: tuple[str, ...]
    source_scope: str

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "obligation_id",
            "level",
            "applicability",
            "status",
            "witness_identities",
            "source_scope",
        }
    )

    def __post_init__(self) -> None:
        if self.obligation_id not in REQUIRED_EVENT_OBLIGATION_IDS_V1:
            raise C8G1ContractError("required-event witness obligation_id未知")
        expected = REQUIRED_EVENT_OBLIGATIONS_V1[
            REQUIRED_EVENT_OBLIGATION_IDS_V1.index(self.obligation_id)
        ]
        if self.level is not expected.level or self.applicability is not expected.applicability:
            raise C8G1ContractError("required-event witness level/applicability drift")
        if not isinstance(self.status, WitnessStatusV1):
            raise C8G1ContractError("required-event witness status非法")
        identities = tuple(self.witness_identities)
        if identities != tuple(sorted(set(identities))):
            raise C8G1ContractError("witness identities必须唯一且canonical排序")
        for index, item in enumerate(identities):
            _sha256(item, f"witness_identities[{index}]")
        _text_id(self.source_scope, "source_scope")
        if self.status is WitnessStatusV1.OBSERVED:
            if not identities:
                raise C8G1ContractError("OBSERVED witness必须包含identity")
            if expected.production_evidence_required and self.source_scope != (
                "FULL_GAME_REAL_PRODUCTION_TRACE"
            ):
                raise C8G1ContractError(
                    "production required-event不能由synthetic/bounded evidence满足"
                )
        elif identities:
            raise C8G1ContractError("非OBSERVED witness不得携带witness identities")
        if self.status is WitnessStatusV1.NOT_APPLICABLE_IN_C6_NO_SKILL_8P:
            if expected.applicability is not ObligationApplicabilityV1.NOT_APPLICABLE_IN_C6_NO_SKILL_8P:
                raise C8G1ContractError("当前冻结applicable obligation不得标记N/A")
        if self.status is WitnessStatusV1.AUDITED_PREREQUISITE_PASSED:
            if expected.level is not ObligationLevelV1.AUDITED_PREREQUISITE:
                raise C8G1ContractError("只有AUDITED_PREREQUISITE可引用审计")
            if self.source_scope != "C8_E_INDEPENDENT_TARGETED_AUDIT_PASSED":
                raise C8G1ContractError("FG-TIMER-11必须绑定C8-E独立审计")

    def to_dict(self) -> dict[str, object]:
        return {
            "obligation_id": self.obligation_id,
            "level": self.level.value,
            "applicability": self.applicability.value,
            "status": self.status.value,
            "witness_identities": list(self.witness_identities),
            "source_scope": self.source_scope,
        }

    @classmethod
    def from_dict(cls, value: object) -> "RequiredEventWitnessV1":
        data = _exact_keys(value, cls._FIELDS, "required-event witness")
        raw_ids = _exact_list(data["witness_identities"], "witness_identities")
        return cls(
            obligation_id=_text_id(data["obligation_id"], "obligation_id"),
            level=_enum_value(ObligationLevelV1, data["level"], "level"),
            applicability=_enum_value(
                ObligationApplicabilityV1,
                data["applicability"],
                "applicability",
            ),
            status=_enum_value(WitnessStatusV1, data["status"], "status"),
            witness_identities=tuple(
                _sha256(item, f"witness_identities[{index}]")
                for index, item in enumerate(raw_ids)
            ),
            source_scope=_text_id(data["source_scope"], "source_scope"),
        )


def canonical_missing_witnesses_v1() -> tuple[RequiredEventWitnessV1, ...]:
    result: list[RequiredEventWitnessV1] = []
    for obligation in REQUIRED_EVENT_OBLIGATIONS_V1:
        if obligation.applicability is (
            ObligationApplicabilityV1.NOT_APPLICABLE_IN_C6_NO_SKILL_8P
        ):
            status = WitnessStatusV1.NOT_APPLICABLE_IN_C6_NO_SKILL_8P
            scope = "C6_NO_SKILL_STRUCTURAL_AUTHORITY_DECISION"
        elif obligation.level is ObligationLevelV1.AUDITED_PREREQUISITE:
            status = WitnessStatusV1.AUDITED_PREREQUISITE_PASSED
            scope = "C8_E_INDEPENDENT_TARGETED_AUDIT_PASSED"
        elif obligation.obligation_id == "FG-TIMER-09":
            status = WitnessStatusV1.NOT_NATURALLY_OBSERVED
            scope = "FULL_GAME_REAL_PRODUCTION_TRACE"
        else:
            status = WitnessStatusV1.MISSING
            scope = "FULL_GAME_REAL_PRODUCTION_TRACE"
        result.append(
            RequiredEventWitnessV1(
                obligation.obligation_id,
                obligation.level,
                obligation.applicability,
                status,
                (),
                scope,
            )
        )
    return tuple(result)


def obligation_status_is_gap_v1(
    level: ObligationLevelV1,
    status: WitnessStatusV1,
) -> bool:
    """Pure applicability rule; an independently proven N/A is never a gap."""

    if not isinstance(level, ObligationLevelV1) or not isinstance(
        status, WitnessStatusV1
    ):
        raise C8G1ContractError("gap derivation必须使用versioned enum")
    if status is WitnessStatusV1.NOT_APPLICABLE_IN_C6_NO_SKILL_8P:
        return False
    if level is ObligationLevelV1.AUDITED_PREREQUISITE:
        return status is not WitnessStatusV1.AUDITED_PREREQUISITE_PASSED
    return status is not WitnessStatusV1.OBSERVED


@dataclass(frozen=True, slots=True)
class FullGameCellRefV1:
    cell_id: str
    mode_id: str
    seed: int

    _FIELDS: ClassVar[frozenset[str]] = frozenset({"cell_id", "mode_id", "seed"})

    def __post_init__(self) -> None:
        _text_id(self.cell_id, "cell_id")
        if self.mode_id != C8_G1_BASE_MODE_ID:
            raise C8G1ContractError("full-game cell mode必须是canonical C6 8p")
        _integer(self.seed, "seed")
        if self.seed > C8_G1_SENTINEL_SEED_MAX:
            raise C8G1ContractError("full-game cell seed超出0..99冻结范围")
        if self.cell_id != canonical_cell_id_v1(self.seed):
            raise C8G1ContractError("cell_id必须由seed canonical派生")

    def to_dict(self) -> dict[str, object]:
        return {"cell_id": self.cell_id, "mode_id": self.mode_id, "seed": self.seed}

    @classmethod
    def from_dict(cls, value: object) -> "FullGameCellRefV1":
        data = _exact_keys(value, cls._FIELDS, "full-game cell ref")
        return cls(
            cell_id=_text_id(data["cell_id"], "cell_id"),
            mode_id=_text_id(data["mode_id"], "mode_id"),
            seed=_integer(data["seed"], "seed"),
        )


def canonical_cell_id_v1(seed: int) -> str:
    seed = _integer(seed, "seed")
    if seed > C8_G1_SENTINEL_SEED_MAX:
        raise C8G1ContractError("seed超出0..99冻结范围")
    return f"C8G-FG-{seed:03d}"


CANONICAL_BASELINE_CELLS_V1: Final[tuple[FullGameCellRefV1, ...]] = tuple(
    FullGameCellRefV1(canonical_cell_id_v1(seed), C8_G1_BASE_MODE_ID, seed)
    for seed in C8_G1_BASELINE_SEEDS
)
C8_G1_BASELINE_REGISTRY_IDENTITY: Final[str] = identity_v1(
    [cell.to_dict() for cell in CANONICAL_BASELINE_CELLS_V1]
)


@dataclass(frozen=True, slots=True)
class FullGameRegistryV1:
    baseline_cells: tuple[FullGameCellRefV1, ...]
    sentinel_cells: tuple[FullGameCellRefV1, ...] = ()

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "contract_version",
            "baseline_registry_identity",
            "baseline_cells",
            "sentinel_cells",
            "selected_cells",
            "registry_identity",
        }
    )

    def __post_init__(self) -> None:
        baseline = tuple(self.baseline_cells)
        sentinels = tuple(self.sentinel_cells)
        if baseline != CANONICAL_BASELINE_CELLS_V1:
            raise C8G1ContractError(
                "baseline registry必须精确为C8G-FG-000/001/049且顺序固定"
            )
        if any(not isinstance(item, FullGameCellRefV1) for item in sentinels):
            raise C8G1ContractError("sentinel registry只能包含FullGameCellRefV1")
        sentinel_seeds = tuple(item.seed for item in sentinels)
        if sentinel_seeds != tuple(sorted(set(sentinel_seeds))):
            raise C8G1ContractError("sentinel registry必须seed升序、唯一")
        if set(sentinel_seeds) & set(C8_G1_BASELINE_SEEDS):
            raise C8G1ContractError("sentinel registry不得包含baseline seed")
        selected = baseline + sentinels
        if len({item.cell_id for item in selected}) != len(selected):
            raise C8G1ContractError("registry cell_id不得重复")
        object.__setattr__(self, "baseline_cells", baseline)
        object.__setattr__(self, "sentinel_cells", sentinels)

    @classmethod
    def canonical(cls, sentinel_seeds: Sequence[int] = ()) -> "FullGameRegistryV1":
        seeds = tuple(sentinel_seeds)
        return cls(
            CANONICAL_BASELINE_CELLS_V1,
            tuple(
                FullGameCellRefV1(
                    canonical_cell_id_v1(seed), C8_G1_BASE_MODE_ID, seed
                )
                for seed in seeds
            ),
        )

    @property
    def selected_cells(self) -> tuple[FullGameCellRefV1, ...]:
        return self.baseline_cells + self.sentinel_cells

    @property
    def registry_identity(self) -> str:
        return identity_v1(
            {
                "schema": C8_G1_REGISTRY_SCHEMA,
                "contract_version": C8_G1_CONTRACT_VERSION,
                "baseline_registry_identity": C8_G1_BASELINE_REGISTRY_IDENTITY,
                "baseline_cells": [item.to_dict() for item in self.baseline_cells],
                "sentinel_cells": [item.to_dict() for item in self.sentinel_cells],
                "selected_cells": [item.to_dict() for item in self.selected_cells],
            }
        )

    def to_dict(self) -> dict[str, object]:
        value = {
            "schema": C8_G1_REGISTRY_SCHEMA,
            "contract_version": C8_G1_CONTRACT_VERSION,
            "baseline_registry_identity": C8_G1_BASELINE_REGISTRY_IDENTITY,
            "baseline_cells": [item.to_dict() for item in self.baseline_cells],
            "sentinel_cells": [item.to_dict() for item in self.sentinel_cells],
            "selected_cells": [item.to_dict() for item in self.selected_cells],
        }
        value["registry_identity"] = self.registry_identity
        return value

    @classmethod
    def from_dict(cls, value: object) -> "FullGameRegistryV1":
        data = _exact_keys(value, cls._FIELDS, "full-game registry")
        if data["schema"] != C8_G1_REGISTRY_SCHEMA:
            raise C8G1ContractError("full-game registry schema不匹配")
        if _integer(data["contract_version"], "contract_version", minimum=1) != (
            C8_G1_CONTRACT_VERSION
        ):
            raise C8G1ContractError("full-game registry version不匹配")
        if _sha256(
            data["baseline_registry_identity"], "baseline_registry_identity"
        ) != C8_G1_BASELINE_REGISTRY_IDENTITY:
            raise C8G1ContractError("baseline registry identity drift")
        baseline = tuple(
            FullGameCellRefV1.from_dict(item)
            for item in _exact_list(data["baseline_cells"], "baseline_cells")
        )
        sentinels = tuple(
            FullGameCellRefV1.from_dict(item)
            for item in _exact_list(data["sentinel_cells"], "sentinel_cells")
        )
        registry = cls(baseline, sentinels)
        selected = [item.to_dict() for item in registry.selected_cells]
        if data["selected_cells"] != selected:
            raise C8G1ContractError("selected_cells必须从baseline+sentinel重新派生")
        if _sha256(data["registry_identity"], "registry_identity") != (
            registry.registry_identity
        ):
            raise C8G1ContractError("registry identity mismatch")
        return registry


@dataclass(frozen=True, slots=True)
class SentinelCandidateV1:
    seed: int
    closed_gap_ids: tuple[str, ...]
    artifact_scope: CandidateScopeV1

    def __post_init__(self) -> None:
        _integer(self.seed, "sentinel seed")
        if self.seed > C8_G1_SENTINEL_SEED_MAX:
            raise C8G1ContractError("sentinel seed超出0..99")
        if self.seed in C8_G1_BASELINE_SEEDS:
            raise C8G1ContractError("sentinel candidate不得使用baseline seed")
        gaps = tuple(self.closed_gap_ids)
        if gaps != tuple(sorted(set(gaps))):
            raise C8G1ContractError("closed_gap_ids必须唯一且排序")
        allowed = set(REQUIRED_EVENT_OBLIGATION_IDS_V1)
        if not gaps or not set(gaps).issubset(allowed):
            raise C8G1ContractError("sentinel candidate必须关闭至少一个已知gap")
        if not isinstance(self.artifact_scope, CandidateScopeV1):
            raise C8G1ContractError("sentinel artifact_scope非法")


@dataclass(frozen=True, slots=True)
class SentinelSelectionResultV1:
    status: SentinelSelectionStatusV1
    selected_seeds: tuple[int, ...]
    remaining_gap_ids: tuple[str, ...]

    @property
    def selection_identity(self) -> str:
        return identity_v1(
            {
                "schema": "sgs-c8-g1-sentinel-selection-v1",
                "contract_version": C8_G1_CONTRACT_VERSION,
                "status": self.status.value,
                "selected_seeds": list(self.selected_seeds),
                "remaining_gap_ids": list(self.remaining_gap_ids),
            }
        )


_BASELINE_GAP_STATE_AUTHORITY_TOKEN: Final[object] = object()


@dataclass(frozen=True, slots=True)
class BaselineGapStateV1:
    baseline_cell_ids: tuple[str, ...]
    baseline_registry_identity: str
    required_gap_ids: tuple[str, ...]
    _authority_token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._authority_token is not _BASELINE_GAP_STATE_AUTHORITY_TOKEN:
            raise C8G1ContractError(
                "sentinel gap state只能从完整baseline fresh derivation取得"
            )
        expected_ids = tuple(item.cell_id for item in CANONICAL_BASELINE_CELLS_V1)
        if self.baseline_cell_ids != expected_ids:
            raise C8G1ContractError("baseline gap state cell registry drift")
        _sha256(self.baseline_registry_identity, "baseline_registry_identity")
        allowed = {
            item.obligation_id
            for item in REQUIRED_EVENT_OBLIGATIONS_V1
            if item.level
            in {
                ObligationLevelV1.MATRIX_UNION_REQUIRED,
                ObligationLevelV1.CONDITIONAL_MATRIX_UNION_REQUIRED,
            }
        }
        if self.required_gap_ids != tuple(sorted(set(self.required_gap_ids))):
            raise C8G1ContractError("baseline required gaps必须唯一且排序")
        if not set(self.required_gap_ids).issubset(allowed):
            raise C8G1ContractError("baseline gap state包含非matrix-union obligation")


def _baseline_gap_state_for_policy_test_v1(
    required_gap_ids: Iterable[str],
) -> BaselineGapStateV1:
    """Internal pure-policy fixture; never serialized or promoted."""

    registry = FullGameRegistryV1.canonical()
    return BaselineGapStateV1(
        tuple(item.cell_id for item in registry.baseline_cells),
        registry.registry_identity,
        tuple(sorted(set(required_gap_ids))),
        _authority_token=_BASELINE_GAP_STATE_AUTHORITY_TOKEN,
    )


def select_sentinels_v1(
    baseline_gap_state: BaselineGapStateV1,
    candidates: Sequence[SentinelCandidateV1],
    *,
    examined_seeds: Sequence[int] = (),
) -> SentinelSelectionResultV1:
    if not isinstance(baseline_gap_state, BaselineGapStateV1) or (
        baseline_gap_state._authority_token is not _BASELINE_GAP_STATE_AUTHORITY_TOKEN
    ):
        raise C8G1ContractError("sentinel discovery必须在完整baseline derivation之后")
    gaps = baseline_gap_state.required_gap_ids
    allowed_union = {
        item.obligation_id
        for item in REQUIRED_EVENT_OBLIGATIONS_V1
        if item.level
        in {
            ObligationLevelV1.MATRIX_UNION_REQUIRED,
            ObligationLevelV1.CONDITIONAL_MATRIX_UNION_REQUIRED,
        }
    }
    if not set(gaps).issubset(allowed_union):
        raise C8G1ContractError("sentinel只能关闭matrix-union required gaps")
    ordered = tuple(candidates)
    if any(not isinstance(item, SentinelCandidateV1) for item in ordered):
        raise C8G1ContractError("candidates类型非法")
    seeds = tuple(item.seed for item in ordered)
    if seeds != tuple(sorted(set(seeds))):
        raise C8G1ContractError("sentinel candidates必须按seed canonical升序且唯一")
    allowed_seed_order = tuple(
        seed
        for seed in range(C8_G1_SENTINEL_SEED_MIN, C8_G1_SENTINEL_SEED_MAX + 1)
        if seed not in C8_G1_BASELINE_SEEDS
    )
    examined = tuple(examined_seeds)
    for seed in examined:
        _integer(seed, "examined sentinel seed")
    if examined != allowed_seed_order[: len(examined)]:
        raise C8G1ContractError(
            "examined sentinel seeds必须是0..99排除baseline后的continuous ascending prefix"
        )
    if not set(seeds).issubset(examined):
        raise C8G1ContractError("sentinel candidate必须来自已检查seed prefix")
    if not gaps:
        return SentinelSelectionResultV1(
            SentinelSelectionStatusV1.COMPLETE, (), ()
        )
    remaining = set(gaps)
    selected: list[SentinelCandidateV1] = []
    for candidate in ordered:
        if remaining.intersection(candidate.closed_gap_ids):
            selected.append(candidate)
            remaining.difference_update(candidate.closed_gap_ids)
        if not remaining:
            break
    # Remove higher-seed candidates first; equal coverage therefore keeps the
    # smaller seed and leaves an inclusion-minimal ordered registry.
    for candidate in tuple(reversed(selected)):
        others = [item for item in selected if item is not candidate]
        coverage = set().union(*(set(item.closed_gap_ids) for item in others))
        if set(gaps).issubset(coverage):
            selected.remove(candidate)
    remaining = set(gaps)
    for candidate in selected:
        remaining.difference_update(candidate.closed_gap_ids)
    if not remaining:
        status = SentinelSelectionStatusV1.COMPLETE
    elif examined == allowed_seed_order:
        status = SentinelSelectionStatusV1.SENTINEL_DISCOVERY_BLOCKED
    else:
        status = SentinelSelectionStatusV1.DISCOVERY_IN_PROGRESS
    return SentinelSelectionResultV1(
        status,
        tuple(item.seed for item in selected),
        tuple(sorted(remaining)),
    )


@dataclass(frozen=True, slots=True)
class PublicActionOptionV1:
    public_ordinal: int
    public_action_family: str

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {"public_ordinal", "public_action_family"}
    )

    def __post_init__(self) -> None:
        _integer(self.public_ordinal, "public_ordinal")
        _text_id(self.public_action_family, "public_action_family")

    def to_dict(self) -> dict[str, object]:
        return {
            "public_ordinal": self.public_ordinal,
            "public_action_family": self.public_action_family,
        }

    @classmethod
    def from_dict(cls, value: object) -> "PublicActionOptionV1":
        data = _exact_keys(value, cls._FIELDS, "public action option")
        return cls(
            _integer(data["public_ordinal"], "public_ordinal"),
            _text_id(data["public_action_family"], "public_action_family"),
        )


PRIVATE_ORDINAL_POLICY_V1: Final[str] = "PUBLIC_ORDER_SHAPE_CERTIFIED_MONOTONIC_POLICY_V1"
PRIVATE_ORDINAL_SOURCE_HASHES_V1: Final[Mapping[str, str]] = MappingProxyType({
    "scripts/sgs_engine/production_batch.py": "ed90625615c01e185ab03948c466b3779867d5f78187bb557660e08b6e5f089b",
    "scripts/sgs_engine/model.py": "986d6a7f028cb27309d6a657d5c5fb8fa24cf508865bb98a30948b238e405480",
    "scripts/sgs_engine/actions.py": "7157cd4cae3e48d8c5109e821b37c1becc48d191d2fb5efa04e8541867cd1ff2",
    "scripts/sgs_engine/c8_c6_production_adapter_v1.py": "50147fd7abbbff86459f38fa0ab19e0571599b0e9f66efd007bbec466f64c647",
})
PRIVATE_ORDINAL_ORDER_CERTIFICATE_V1: Final[Mapping[str, object]] = MappingProxyType({
    "schema": "sgs-c8-g-public-order-certificate-v1",
    "policy": PRIVATE_ORDINAL_POLICY_V1,
    "sources": dict(PRIVATE_ORDINAL_SOURCE_HASHES_V1),
    "selection_phases": ["discard", "weapon_discard_two"],
    "grammar": "UNSELECTED_FORWARD_THEN_SELECTED_REVERSAL_THEN_UNIQUE_OPTIONAL_COMMIT",
    "empty_entry": "CANONICAL_STEP0_SOLE_DRIVER_AND_PRIOR_ACCEPTED_PHASE_TRANSITION",
    "hanbing": "IMMEDIATE_DISCARD_POOL_MINUS_ONE_AT_MOST_TWO",
    "source_scope": "CURRENT_EXACT_C6_NO_SKILL_8P_ONLY",
})
PRIVATE_ORDINAL_CERTIFICATE_IDENTITY_V1: Final[str] = identity_v1(dict(PRIVATE_ORDINAL_ORDER_CERTIFICATE_V1))
PUBLIC_EQUIPMENT_SLOT_ORDER_V1: Final[tuple[str, ...]] = (
    "defense_horse", "armor", "weapon", "attack_horse", "treasure",
)
PRIVATE_SELECTION_PHASES_V1: Final[frozenset[str]] = frozenset({"discard", "weapon_discard_two"})
PRIVATE_SINGLE_PHASES_V1: Final[frozenset[str]] = frozenset({
    "cixiong_target_choice", "zone_choice", "fire_attack_reveal", "borrowed_sword_choice", "wugu_pick",
})
PRIVATE_CERTIFIED_PHASES_V1: Final[frozenset[str]] = (
    PRIVATE_SELECTION_PHASES_V1 | PRIVATE_SINGLE_PHASES_V1 | {"hanbing_discard"}
)


@dataclass(frozen=True, slots=True)
class PublicOrdinalProgressV1:
    """Public-history certificate data, never restored live authority or E observed q."""

    run_binding_identity: str
    execution_order_profile_identity: str
    source_certificate_identity: str
    logical_obligation_identity: str
    opening_ref_identity: str
    opening_context_identity: str
    entry_step_index: int
    accepted_step_index: int
    global_window_index: int
    deadline_at: int
    phase: str
    turn_number: int
    turn_player_id: str
    actor_id: str
    candidate_count: int
    certified_selected_progress_count: int
    stage: str
    shape_count: int
    certified_required_count: int | None
    entry_pre_context_identity: str
    entry_pre_phase: str
    entry_pre_actor_id: str

    def __post_init__(self) -> None:
        for key in ("run_binding_identity", "execution_order_profile_identity", "source_certificate_identity",
                    "logical_obligation_identity", "opening_ref_identity", "opening_context_identity", "entry_pre_context_identity"):
            _sha256(getattr(self, key), key)
        for key in ("entry_step_index", "accepted_step_index", "certified_selected_progress_count", "shape_count"):
            _integer(getattr(self, key), key)
        for key in ("global_window_index", "deadline_at", "turn_number", "candidate_count"):
            _integer(getattr(self, key), key, minimum=1)
        for key in ("phase", "turn_player_id", "actor_id", "entry_pre_phase", "entry_pre_actor_id"):
            _text_id(getattr(self, key), key)
        _optional_integer(self.certified_required_count, "certified_required_count", minimum=1)
        if self.source_certificate_identity != PRIVATE_ORDINAL_CERTIFICATE_IDENTITY_V1 or self.phase not in PRIVATE_CERTIFIED_PHASES_V1:
            raise C8G1ContractError("DRIVER_LIVENESS_UNRESOLVED: source/phase没有证书")
        if self.entry_step_index < 1 or self.accepted_step_index < self.entry_step_index:
            raise C8G1ContractError("DRIVER_LIVENESS_UNRESOLVED: 不能接管未知入口")
        receiver_successor = self.phase == "wugu_pick" and self.entry_pre_actor_id != self.actor_id
        if self.entry_pre_phase == self.phase and not receiver_successor:
            raise C8G1ContractError("DRIVER_LIVENESS_UNRESOLVED: 没有可证明空选/新receiver入口")
        q = self.certified_selected_progress_count
        if self.phase in PRIVATE_SELECTION_PHASES_V1:
            if q > self.candidate_count or self.stage not in {"SELECTING", "DONE"}:
                raise C8G1ContractError("DRIVER_LIVENESS_UNRESOLVED: q/N/stage非法")
            if self.stage == "SELECTING" and self.shape_count not in {self.candidate_count, self.candidate_count + 1}:
                raise C8G1ContractError("DRIVER_LIVENESS_UNRESOLVED: 未知selection shape")
            if self.certified_required_count is not None and self.certified_required_count != q:
                raise C8G1ContractError("DRIVER_LIVENESS_UNRESOLVED: required只能由commit shape证明")
            if self.stage == "SELECTING" and (self.shape_count == self.candidate_count + 1) != (self.certified_required_count is not None):
                raise C8G1ContractError("DRIVER_LIVENESS_UNRESOLVED: commit shape/required不匹配")
            if self.stage == "DONE" and (q == 0 or self.certified_required_count is None):
                raise C8G1ContractError("DRIVER_LIVENESS_UNRESOLVED: 未经commit不能标完成")
            used = q + int(self.stage == "DONE")
        else:
            limit = 2 if self.phase == "hanbing_discard" else 1
            if q > limit or self.stage not in {"FORWARD", "DONE"} or self.certified_required_count is not None:
                raise C8G1ContractError("DRIVER_LIVENESS_UNRESOLVED: 单次/寒冰证书非法")
            if self.stage == "FORWARD" and (q >= limit or self.shape_count < 1):
                raise C8G1ContractError("DRIVER_LIVENESS_UNRESOLVED: 专用有限义务已耗尽")
            if self.phase == "hanbing_discard" and self.stage == "FORWARD" and self.shape_count != self.candidate_count - q:
                raise C8G1ContractError("DRIVER_LIVENESS_UNRESOLVED: 寒冰候选池未逐张减少")
            used = q
            if self.stage == "DONE" and q == 0:
                raise C8G1ContractError("DRIVER_LIVENESS_UNRESOLVED: 单次义务没有accepted进展")
        if self.accepted_step_index != self.entry_step_index + used:
            raise C8G1ContractError("DRIVER_LIVENESS_BLOCKED: public history计数倒退/重用")
        if self.logical_obligation_identity != identity_v1(self.obligation_material()):
            raise C8G1ContractError("DRIVER_LIVENESS_UNRESOLVED: 稳定义务入口绑定不匹配")

    def obligation_material(self) -> dict[str, object]:
        return {"schema": "sgs-c8-g-stable-public-obligation-v1", **{key: getattr(self, key) for key in (
            "run_binding_identity", "source_certificate_identity", "phase", "turn_number", "turn_player_id",
            "actor_id", "entry_step_index", "entry_pre_context_identity")}}

    @property
    def variant(self) -> int:
        if self.stage == "DONE":
            return 0
        if self.phase in PRIVATE_SELECTION_PHASES_V1:
            return self.candidate_count - self.certified_selected_progress_count + 1
        return (2 if self.phase == "hanbing_discard" else 1) - self.certified_selected_progress_count

    def to_dict(self) -> dict[str, object]:
        return {key: getattr(self, key) for key in self.__dataclass_fields__}

    @classmethod
    def from_dict(cls, value: object) -> "PublicOrdinalProgressV1":
        return cls(**_exact_keys(value, frozenset(cls.__dataclass_fields__), "public history certificate"))


def open_public_ordinal_progress_v1(*, run_binding_identity: str, execution_order_profile_identity: str,
        opening_ref_identity: str, opening_context_identity: str, entry_step_index: int,
        global_window_index: int, deadline_at: int, phase: str, turn_number: int, turn_player_id: str,
        actor_id: str, proposal_count: int, entry_pre_context_identity: str, entry_pre_phase: str,
        entry_pre_actor_id: str) -> PublicOrdinalProgressV1:
    """Caller must freshly derive the predecessor from its own canonical step0 history."""
    values = {"run_binding_identity": run_binding_identity, "execution_order_profile_identity": execution_order_profile_identity,
        "source_certificate_identity": PRIVATE_ORDINAL_CERTIFICATE_IDENTITY_V1,
        "opening_ref_identity": opening_ref_identity, "opening_context_identity": opening_context_identity,
        "entry_step_index": entry_step_index, "accepted_step_index": entry_step_index,
        "global_window_index": global_window_index, "deadline_at": deadline_at,
        "phase": phase, "turn_number": turn_number, "turn_player_id": turn_player_id, "actor_id": actor_id,
        "candidate_count": proposal_count, "certified_selected_progress_count": 0,
        "stage": "SELECTING" if phase in PRIVATE_SELECTION_PHASES_V1 else "FORWARD",
        "shape_count": proposal_count, "certified_required_count": None,
        "entry_pre_context_identity": entry_pre_context_identity, "entry_pre_phase": entry_pre_phase,
        "entry_pre_actor_id": entry_pre_actor_id}
    material = {"schema": "sgs-c8-g-stable-public-obligation-v1", **{key: values[key] for key in (
        "run_binding_identity", "source_certificate_identity", "phase", "turn_number", "turn_player_id",
        "actor_id", "entry_step_index", "entry_pre_context_identity")}}
    return PublicOrdinalProgressV1(**values, logical_obligation_identity=identity_v1(material))


def certified_ordinal_choice_v1(progress: PublicOrdinalProgressV1, proposal_count: int) -> tuple[int, str]:
    if type(progress) is not PublicOrdinalProgressV1:
        raise C8G1ContractError("DRIVER_LIVENESS_UNRESOLVED: 缺少typed公共历史")
    m = _integer(proposal_count, "fresh proposal count", minimum=1)
    if progress.stage == "DONE" or progress.shape_count != m:
        raise C8G1ContractError("DRIVER_LIVENESS_BLOCKED: 已完成义务或fresh shape漂移")
    n, q = progress.candidate_count, progress.certified_selected_progress_count
    if progress.phase in PRIVATE_SELECTION_PHASES_V1:
        if m == n + 1 and 1 <= q <= n:
            return n, "COMMIT"
        if m == n and q < n:
            return 0, "PROGRESS"
        raise C8G1ContractError("DRIVER_LIVENESS_UNRESOLVED: 无可证明forward/commit，禁止试探")
    # These phases retain their exact legacy single-eligible last-ordinal choice.
    return m - 1, "PROGRESS"


def advance_public_ordinal_progress_v1(progress: PublicOrdinalProgressV1, *, chosen_ordinal: int,
        post_step_count: int, next_phase: str | None, next_actor_id: str | None,
        next_turn_number: int | None, next_turn_player_id: str | None, next_proposal_count: int) -> PublicOrdinalProgressV1:
    """Check an already accepted boundary; failure never authorizes rollback or retry."""
    ordinal, action_class = certified_ordinal_choice_v1(progress, progress.shape_count)
    if _integer(chosen_ordinal, "chosen ordinal") != ordinal or _integer(post_step_count, "post step") != progress.accepted_step_index + 1:
        raise C8G1ContractError("DRIVER_LIVENESS_BLOCKED: ordinal或accepted边界不匹配")
    count = _integer(next_proposal_count, "next proposal count")
    if next_phase is None:
        if any(v is not None for v in (next_actor_id, next_turn_number, next_turn_player_id)) or count != 0:
            raise C8G1ContractError("DRIVER_LIVENESS_UNRESOLVED: terminal公开边界不完整")
    else:
        _text_id(next_phase, "next phase")
        _text_id(next_actor_id, "next actor")
        _text_id(next_turn_player_id, "next turn player")
        _integer(next_turn_number, "next turn", minimum=1)
        if count < 1:
            raise C8G1ContractError("DRIVER_LIVENESS_UNRESOLVED: 非终局缺少公开候选")
    same = (next_phase, next_actor_id, next_turn_number, next_turn_player_id) == (
        progress.phase, progress.actor_id, progress.turn_number, progress.turn_player_id)
    values = progress.to_dict()
    values.update(accepted_step_index=post_step_count, shape_count=count)
    q, n = progress.certified_selected_progress_count, progress.candidate_count
    if progress.phase in PRIVATE_SELECTION_PHASES_V1:
        if action_class == "COMMIT":
            if same:
                raise C8G1ContractError("DRIVER_LIVENESS_UNRESOLVED: 已提交但未离开义务")
            values.update(stage="DONE", certified_required_count=q)
        else:
            if not same or count not in {n, n + 1}:
                raise C8G1ContractError("DRIVER_LIVENESS_UNRESOLVED: 已选择后的公开后继不符")
            values.update(certified_selected_progress_count=q + 1,
                          certified_required_count=q + 1 if count == n + 1 else None)
    elif progress.phase == "hanbing_discard":
        if same and (q >= 1 or count != progress.shape_count - 1):
            raise C8G1ContractError("DRIVER_LIVENESS_UNRESOLVED: 寒冰真实弃置未减少候选或超过两步")
        values.update(certified_selected_progress_count=q + 1, stage="FORWARD" if same else "DONE")
    else:
        if same:
            raise C8G1ContractError("DRIVER_LIVENESS_UNRESOLVED: 单次private义务出现未知第二步")
        values.update(certified_selected_progress_count=1, stage="DONE")
    result = PublicOrdinalProgressV1(**values)
    if result.variant >= progress.variant:
        raise C8G1ContractError("DRIVER_LIVENESS_BLOCKED: variant未严格下降")
    return result


@dataclass(frozen=True, slots=True)
class FormalDriverInputV1:
    formal_seed: int
    global_window_index: int
    turn_number: int
    turn_player_id: str
    actor_id: str
    phase: str
    window_kind: PublicWindowKindV1
    deadline_at: int
    timeout_applicability: TimeoutApplicabilityV1
    proposal_order_identity: str
    public_actions: tuple[PublicActionOptionV1, ...]
    public_ordinal_progress: PublicOrdinalProgressV1 | None = None

    def __post_init__(self) -> None:
        _integer(self.formal_seed, "formal_seed")
        _integer(self.global_window_index, "global_window_index", minimum=1)
        _integer(self.turn_number, "turn_number", minimum=1)
        _text_id(self.turn_player_id, "turn_player_id")
        _text_id(self.actor_id, "actor_id")
        _text_id(self.phase, "phase")
        if not isinstance(self.window_kind, PublicWindowKindV1):
            raise C8G1ContractError("window_kind非法")
        _integer(self.deadline_at, "deadline_at", minimum=1)
        if not isinstance(self.timeout_applicability, TimeoutApplicabilityV1):
            raise C8G1ContractError("timeout_applicability非法")
        if (
            self.window_kind is PublicWindowKindV1.PRIVATE_ORDINAL_TIMEOUT_UNRESOLVED
        ) != (
            self.timeout_applicability
            is TimeoutApplicabilityV1.PRIVATE_ORDINAL_TIMEOUT_UNRESOLVED
        ):
            raise C8G1ContractError(
                "private-ordinal window kind/applicability必须成对绑定"
            )
        _sha256(self.proposal_order_identity, "proposal_order_identity")
        actions = tuple(self.public_actions)
        if not actions or any(not isinstance(item, PublicActionOptionV1) for item in actions):
            raise C8G1ContractError("public_actions必须是非空public option tuple")
        if tuple(item.public_ordinal for item in actions) != tuple(range(len(actions))):
            raise C8G1ContractError("public action ordinal必须从0连续且保持production顺序")
        expected_order = identity_v1([item.to_dict() for item in actions])
        if self.proposal_order_identity != expected_order:
            raise C8G1ContractError("proposal_order_identity与public action顺序不一致")
        object.__setattr__(self, "public_actions", actions)
        progress = self.public_ordinal_progress
        if progress is not None:
            if type(progress) is not PublicOrdinalProgressV1:
                raise C8G1ContractError("public ordinal progress必须是typed record")
            if self.window_kind is not PublicWindowKindV1.PRIVATE_ORDINAL_TIMEOUT_UNRESOLVED:
                raise C8G1ContractError("DRIVER_LIVENESS_UNRESOLVED: private证书不能混入普通分支")
            for key in ("phase", "turn_number", "turn_player_id", "actor_id", "global_window_index", "deadline_at"):
                if getattr(progress, key) != getattr(self, key):
                    raise C8G1ContractError("DRIVER_LIVENESS_UNRESOLVED: public history/input绑定漂移")
            if progress.shape_count != len(actions) or any(a.public_action_family != "PRIVATE_ORDINAL" for a in actions):
                raise C8G1ContractError("DRIVER_LIVENESS_UNRESOLVED: private family/shape漂移")

    def identity_material(self) -> dict[str, object]:
        return {
            "formal_seed": self.formal_seed,
            "global_window_index": self.global_window_index,
            "turn_number": self.turn_number,
            "turn_player_id": self.turn_player_id,
            "actor_id": self.actor_id,
            "phase": self.phase,
            "window_kind": self.window_kind.value,
            "deadline_at": self.deadline_at,
            "timeout_applicability": self.timeout_applicability.value,
            "proposal_order_identity": self.proposal_order_identity,
            "public_actions": [item.to_dict() for item in self.public_actions],
            "public_ordinal_progress": None if self.public_ordinal_progress is None else self.public_ordinal_progress.to_dict(),
        }

    def selection_material(self) -> dict[str, object]:
        """Exact public-only material allowed to influence ordinal choice."""

        return {
            "formal_seed": self.formal_seed,
            "global_window_index": self.global_window_index,
            "turn_number": self.turn_number,
            "turn_player_id": self.turn_player_id,
            "actor_id": self.actor_id,
            "phase": self.phase,
            "window_kind": self.window_kind.value,
            "proposal_count": len(self.public_actions),
            "public_actions": [item.to_dict() for item in self.public_actions],
        }


@dataclass(frozen=True, slots=True)
class FormalDriverDecisionV1:
    policy_id: str
    policy_identity: str
    driver_input_identity: str
    timeout_intent: bool
    actual_timeout: bool
    marker: DriverDecisionMarkerV1
    decision_tick: int
    chosen_public_ordinal: int | None
    chosen_public_action_family: str | None
    choice_digest: str | None
    skip_reason: str | None

    def __post_init__(self) -> None:
        if self.policy_id != C8_G1_DRIVER_POLICY_ID:
            raise C8G1ContractError("formal driver policy id drift")
        if _sha256(self.policy_identity, "policy_identity") != (
            C8_G1_DRIVER_POLICY_IDENTITY
        ):
            raise C8G1ContractError("formal driver policy identity drift")
        _sha256(self.driver_input_identity, "driver_input_identity")
        _boolean(self.timeout_intent, "timeout_intent")
        _boolean(self.actual_timeout, "actual_timeout")
        if not isinstance(self.marker, DriverDecisionMarkerV1):
            raise C8G1ContractError("formal driver marker非法")
        _integer(self.decision_tick, "decision_tick")
        _optional_integer(self.chosen_public_ordinal, "chosen_public_ordinal")
        _optional_text_id(
            self.chosen_public_action_family, "chosen_public_action_family"
        )
        _optional_sha256(self.choice_digest, "choice_digest")
        _optional_text_id(self.skip_reason, "skip_reason")
        if self.actual_timeout:
            if self.marker is not DriverDecisionMarkerV1.TIMEOUT:
                raise C8G1ContractError("actual timeout marker drift")
            if any(
                item is not None
                for item in (
                    self.chosen_public_ordinal,
                    self.chosen_public_action_family,
                    self.choice_digest,
                    self.skip_reason,
                )
            ):
                raise C8G1ContractError(
                    "timeout ordinal/family只能来自C resolver result/B receipt/E evidence"
                )
        else:
            if any(
                item is None
                for item in (
                    self.chosen_public_ordinal,
                    self.chosen_public_action_family,
                    self.choice_digest,
                )
            ):
                raise C8G1ContractError("on-time driver必须产生public ordinal/family")


_DRIVER_POLICY_DESCRIPTOR: Final[Mapping[str, object]] = MappingProxyType(
    {
        "schema": "sgs-c8-g-formal-driver-policy-v3",
        "contract_version": C8_G1_DRIVER_MATERIAL_VERSION,
        "policy_id": C8_G1_DRIVER_POLICY_ID,
        "global_window_index_base": 1,
        "timeout_modulo": 4,
        "timeout_remainder": 0,
        "on_time_tick": "deadline_at-1",
        "timeout_tick": "deadline_at",
        "inputs": [
            "formal_seed",
            "global_window_index",
            "turn_number",
            "public_actor_and_turn_player",
            "phase",
            "window_kind",
            "proposal_count",
            "ordered_public_ordinal_action_family",
        ],
        "forbidden_inputs": [
            "private_payload",
            "card_identity",
            "hidden_choice",
            "rng",
            "wall_clock",
        ],
        "unresolved_timeout": "FORCE_ON_TIME_AND_RECORD",
        "driver_choice_scope": "ON_TIME_ONLY",
        "timeout_selection_authority": (
            "C_RESOLVER_RESULT_B_RECEIPT_E_EVIDENCE_ONLY"
        ),
        "same_tick_chain_cap": C8_G1_MAX_SAME_TICK_CHAIN,
        "legacy_ordinary_selection_material_version": 2,
        "global_window_index_domain": "B_OPEN_ONLY_CONTINUATION_DOES_NOT_INCREMENT",
        "private_subpolicy": dict(PRIVATE_ORDINAL_ORDER_CERTIFICATE_V1),
        "private_progress_input": "G_CERTIFIED_PUBLIC_HISTORY_NOT_E_OBSERVED_SELECTED_COUNT",
        "ownership": "OPENING_REF_PLUS_FRESH_EXECUTION_CONTEXT_DISTINCT_DOMAINS",
        "execution_order": {"hash_randomization": 0, "slots": list(PUBLIC_EQUIPMENT_SLOT_ORDER_V1)},
    }
)
C8_G1_DRIVER_POLICY_IDENTITY: Final[str] = identity_v1(
    dict(_DRIVER_POLICY_DESCRIPTOR)
)


def formal_driver_policy_descriptor_v1() -> dict[str, object]:
    return _plain(_DRIVER_POLICY_DESCRIPTOR)  # type: ignore[return-value]


def _eligible_ordinals(input_value: FormalDriverInputV1) -> tuple[int, ...]:
    actions = input_value.public_actions
    if input_value.window_kind in {PublicWindowKindV1.PRIVATE_ORDINAL_TIMEOUT_UNRESOLVED,
                                   PublicWindowKindV1.MULTI_STEP_OBLIGATION}:
        if input_value.public_ordinal_progress is None:
            raise C8G1ContractError("DRIVER_LIVENESS_UNRESOLVED: private入口没有source/public history证书")
        return (certified_ordinal_choice_v1(input_value.public_ordinal_progress, len(actions))[0],)
    if len(actions) == 1:
        return (0,)
    if input_value.window_kind is PublicWindowKindV1.PLAY:
        progress = tuple(
            item.public_ordinal
            for item in actions
            if item.public_action_family != "END_PLAY_PHASE"
        )
        if progress:
            return progress
        end = tuple(
            item.public_ordinal
            for item in actions
            if item.public_action_family == "END_PLAY_PHASE"
        )
        if len(end) != 1:
            raise C8G1ContractError("PLAY无progress action时必须有唯一END_PLAY_PHASE")
        return end
    if input_value.window_kind in {
        PublicWindowKindV1.OPTIONAL_RESPONSE,
        PublicWindowKindV1.RESCUE_RESPONSE,
        PublicWindowKindV1.OPTIONAL_SKILL_DECISION,
    }:
        non_decline = tuple(
            item.public_ordinal
            for item in actions
            if item.public_action_family not in {"PASS", "DECLINE"}
        )
        if non_decline:
            return non_decline
        decline = tuple(
            item.public_ordinal
            for item in actions
            if item.public_action_family in {"PASS", "DECLINE"}
        )
        if not decline:
            raise C8G1ContractError("optional window没有可用public action")
        return decline
    return tuple(item.public_ordinal for item in actions)


def choose_formal_driver_action_v1(
    input_value: FormalDriverInputV1,
) -> FormalDriverDecisionV1:
    if not isinstance(input_value, FormalDriverInputV1):
        raise C8G1ContractError("formal driver只接受FormalDriverInputV1")
    timeout_intent = input_value.global_window_index % 4 == 0
    if input_value.timeout_applicability is (
        TimeoutApplicabilityV1.NOT_APPLICABLE_IN_C6_NO_SKILL_8P
    ):
        raise C8G1ContractError(
            "NOT_APPLICABLE context自然出现：C8-G contract/source drift"
        )
    skipped = (
        timeout_intent
        and input_value.timeout_applicability
        is TimeoutApplicabilityV1.PRIVATE_ORDINAL_TIMEOUT_UNRESOLVED
    )
    actual_timeout = timeout_intent and not skipped
    if actual_timeout:
        marker = DriverDecisionMarkerV1.TIMEOUT
        tick = input_value.deadline_at
        skip_reason = None
    elif skipped:
        marker = DriverDecisionMarkerV1.TIMEOUT_INTENT_SKIPPED_UNRESOLVED
        tick = input_value.deadline_at - 1
        skip_reason = "PRIVATE_ORDINAL_TIMEOUT_UNRESOLVED"
    else:
        marker = DriverDecisionMarkerV1.ON_TIME
        tick = input_value.deadline_at - 1
        skip_reason = None
    if actual_timeout:
        return FormalDriverDecisionV1(
            C8_G1_DRIVER_POLICY_ID,
            C8_G1_DRIVER_POLICY_IDENTITY,
            identity_v1(input_value.identity_material()),
            timeout_intent,
            True,
            marker,
            tick,
            None,
            None,
            None,
            None,
        )
    eligible = _eligible_ordinals(input_value)
    digest_material = {
        "schema": "sgs-c8-g-driver-choice-material-v2",
        "contract_version": 2,
        **input_value.selection_material(),
        "eligible_ordinals": list(eligible),
    }
    if input_value.public_ordinal_progress is not None:
        digest_material.update(schema="sgs-c8-g-driver-choice-material-v3", contract_version=3,
            public_ordinal_progress=input_value.public_ordinal_progress.to_dict())
    digest = identity_v1(digest_material)
    if len(eligible) == 1:
        chosen = eligible[0]
    elif input_value.window_kind in {
        PublicWindowKindV1.PLAY,
        PublicWindowKindV1.OPTIONAL_RESPONSE,
        PublicWindowKindV1.RESCUE_RESPONSE,
        PublicWindowKindV1.OPTIONAL_SKILL_DECISION,
    }:
        chosen = eligible[int(digest, 16) % len(eligible)]
    else:
        chosen = eligible[int(digest, 16) % len(eligible)]
    action = input_value.public_actions[chosen]
    return FormalDriverDecisionV1(
        C8_G1_DRIVER_POLICY_ID,
        C8_G1_DRIVER_POLICY_IDENTITY,
        identity_v1(input_value.identity_material()),
        timeout_intent,
        actual_timeout,
        marker,
        tick,
        chosen,
        action.public_action_family,
        digest,
        skip_reason,
    )


@dataclass(frozen=True, slots=True)
class NaturalTerminalEvidenceV1:
    winner_id: str | None
    outcome_identity: str
    finish_reason: str
    turn_count: int
    production_step_count: int
    timed_window_count: int
    event_count: int
    rng_count: int
    final_public_state_identity: str
    final_authoritative_state_identity: str
    final_inner_replay_identity: str
    natural_terminal: bool
    analysis_only: bool
    skill_runtime: None
    synthetic_terminal: bool
    safety_cap_hit: bool
    all_timed_windows_clean: bool
    pending_authorities_clean: bool

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "winner_id",
            "outcome_identity",
            "finish_reason",
            "turn_count",
            "production_step_count",
            "timed_window_count",
            "event_count",
            "rng_count",
            "final_public_state_identity",
            "final_authoritative_state_identity",
            "final_inner_replay_identity",
            "natural_terminal",
            "analysis_only",
            "skill_runtime",
            "synthetic_terminal",
            "safety_cap_hit",
            "all_timed_windows_clean",
            "pending_authorities_clean",
        }
    )

    def __post_init__(self) -> None:
        if self.winner_id is not None:
            _text_id(self.winner_id, "winner_id")
        _sha256(self.outcome_identity, "outcome_identity")
        _text_id(self.finish_reason, "finish_reason")
        for name in (
            "turn_count",
            "production_step_count",
            "timed_window_count",
            "event_count",
            "rng_count",
        ):
            _integer(getattr(self, name), name)
        for name in (
            "final_public_state_identity",
            "final_authoritative_state_identity",
            "final_inner_replay_identity",
        ):
            _sha256(getattr(self, name), name)
        expected_outcome = natural_terminal_outcome_identity_v1(
            winner_id=self.winner_id,
            finish_reason=self.finish_reason,
            turn_count=self.turn_count,
            production_step_count=self.production_step_count,
            event_count=self.event_count,
            rng_count=self.rng_count,
        )
        if self.outcome_identity != expected_outcome:
            raise C8G1ContractError(
                "outcome_identity必须从authoritative terminal fields重新派生"
            )
        for name in (
            "natural_terminal",
            "analysis_only",
            "synthetic_terminal",
            "safety_cap_hit",
            "all_timed_windows_clean",
            "pending_authorities_clean",
        ):
            _boolean(getattr(self, name), name)
        if self.skill_runtime is not None:
            raise C8G1ContractError("canonical C6 full game必须skill_runtime=None")
        if self.natural_terminal and (
            self.analysis_only
            or self.synthetic_terminal
            or self.safety_cap_hit
            or not self.all_timed_windows_clean
            or not self.pending_authorities_clean
            or not self.finish_reason
        ):
            raise C8G1ContractError("natural terminal evidence与冻结终局条件矛盾")

    def to_dict(self) -> dict[str, object]:
        return {name: _plain(getattr(self, name)) for name in self._FIELDS}

    @classmethod
    def from_dict(cls, value: object) -> "NaturalTerminalEvidenceV1":
        data = _exact_keys(value, cls._FIELDS, "natural terminal evidence")
        winner = data["winner_id"]
        if winner is not None:
            winner = _text_id(winner, "winner_id")
        return cls(
            winner_id=winner,
            outcome_identity=_sha256(data["outcome_identity"], "outcome_identity"),
            finish_reason=_text_id(data["finish_reason"], "finish_reason"),
            turn_count=_integer(data["turn_count"], "turn_count"),
            production_step_count=_integer(
                data["production_step_count"], "production_step_count"
            ),
            timed_window_count=_integer(data["timed_window_count"], "timed_window_count"),
            event_count=_integer(data["event_count"], "event_count"),
            rng_count=_integer(data["rng_count"], "rng_count"),
            final_public_state_identity=_sha256(
                data["final_public_state_identity"], "final_public_state_identity"
            ),
            final_authoritative_state_identity=_sha256(
                data["final_authoritative_state_identity"],
                "final_authoritative_state_identity",
            ),
            final_inner_replay_identity=_sha256(
                data["final_inner_replay_identity"], "final_inner_replay_identity"
            ),
            natural_terminal=_boolean(data["natural_terminal"], "natural_terminal"),
            analysis_only=_boolean(data["analysis_only"], "analysis_only"),
            skill_runtime=data["skill_runtime"],
            synthetic_terminal=_boolean(
                data["synthetic_terminal"], "synthetic_terminal"
            ),
            safety_cap_hit=_boolean(data["safety_cap_hit"], "safety_cap_hit"),
            all_timed_windows_clean=_boolean(
                data["all_timed_windows_clean"], "all_timed_windows_clean"
            ),
            pending_authorities_clean=_boolean(
                data["pending_authorities_clean"], "pending_authorities_clean"
            ),
        )


def natural_terminal_outcome_identity_v1(
    *,
    winner_id: str | None,
    finish_reason: str,
    turn_count: int,
    production_step_count: int,
    event_count: int,
    rng_count: int,
) -> str:
    if winner_id is not None:
        _text_id(winner_id, "winner_id")
    _text_id(finish_reason, "finish_reason")
    return identity_v1(
        {
            "schema": "sgs-c8-g1-authoritative-terminal-outcome-v1",
            "contract_version": C8_G1_CONTRACT_VERSION,
            "winner_id": winner_id,
            "finish_reason": finish_reason,
            "turn_count": _integer(turn_count, "turn_count"),
            "production_step_count": _integer(
                production_step_count, "production_step_count"
            ),
            "event_count": _integer(event_count, "event_count"),
            "rng_count": _integer(rng_count, "rng_count"),
        }
    )


CELL_ATOMIC_PROOF_FACTS_V1: Final[frozenset[str]] = frozenset(
    {
        "PRODUCTION_REACHABLE",
        "NATURAL_FULL_GAME",
        "CANONICAL_C6_MODE_PROVEN",
        "FORMAL_DRIVER_POLICY_PROVEN",
        "TIMER_AUTHORITY_PROVEN",
        "PUBLIC_ADAPTER_AUTHORITY_PROVEN",
        "CONTROLLER_AUTHORITY_PROVEN",
        "ON_TIME_TRACE_PROVEN",
        "TIMEOUT_TRACE_PROVEN",
        "MULTIWINDOW_CONTINUITY_PROVEN",
        "SAME_CONTEXT_NO_REFRESH_PROVEN",
        "PHASE_CLEANUP_PROVEN",
        "TURN_ACTOR_CLEANUP_PROVEN",
        "STALE_EVIDENCE_REJECTION_PROVEN",
        "NATURAL_TERMINAL_PROVEN",
        "TERMINAL_WINDOWS_CLEAN_PROVEN",
        "INNER_PRODUCTION_REPLAY_PROVEN",
        "OUTER_TIMER_REPLAY_PROVEN",
        "FULL_GAME_REPLAY_STRICT_VERIFIED",
        "IDENTITY_PROFILE_DRIVER_BINDING_PROVEN",
        "UNRESOLVED_CONTEXT_POLICY_PROVEN",
    }
)
_FRESH_RESULT_AUTHORITY_TOKEN: Final[object] = object()
_PROMOTION_DECISION_AUTHORITY_TOKEN: Final[object] = object()


@dataclass(frozen=True, slots=True)
class FullGameResultV1:
    """Runtime-only result issued by a future fresh G3 verifier.

    There is intentionally no authoritative ``from_dict``.  Serialized report
    booleans can be inspected, but promotion accepts only a live instance that
    was freshly derived by the verifier integration.
    """

    cell_id: str
    seed: int
    mode_id: str
    registry_identity: str
    current_implementation_identity: str
    contract_identity: str
    timer_profile_id: str
    driver_policy_identity: str
    replay_schema: str
    replay_scope: str
    production_adapter_id: str
    production_adapter_contract_identity: str
    controller_contract_identity: str
    artifact_scope: CandidateScopeV1
    run_status: CellRunStatusV1
    artifact_complete: bool
    full_game: bool
    formal_matrix_cell: bool
    natural_terminal: bool
    safety_cap_hit: bool
    strict_replay_verified: bool
    replay_identity: str
    artifact_identity: str
    verified_fact_ids: frozenset[str]
    required_event_witnesses: tuple[RequiredEventWitnessV1, ...]
    successful_rescue_evidence_identities: tuple[str, ...] = ()
    _authority_token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._authority_token is not _FRESH_RESULT_AUTHORITY_TOKEN:
            raise C8G1ContractError(
                "FullGameResult只能由fresh verifier integration签发"
            )
        if self.cell_id != canonical_cell_id_v1(self.seed):
            raise C8G1ContractError("FullGameResult cell_id/seed不一致")
        _text_id(self.mode_id, "mode_id")
        for name in (
            "registry_identity",
            "current_implementation_identity",
            "contract_identity",
            "driver_policy_identity",
            "replay_identity",
            "artifact_identity",
        ):
            _sha256(getattr(self, name), name)
        _text_id(self.timer_profile_id, "timer_profile_id")
        _text_id(self.replay_schema, "replay_schema")
        _text_id(self.replay_scope, "replay_scope")
        _text_id(self.production_adapter_id, "production_adapter_id")
        _sha256(
            self.production_adapter_contract_identity,
            "production_adapter_contract_identity",
        )
        _sha256(self.controller_contract_identity, "controller_contract_identity")
        if not isinstance(self.artifact_scope, CandidateScopeV1):
            raise C8G1ContractError("FullGameResult artifact scope非法")
        if not isinstance(self.run_status, CellRunStatusV1):
            raise C8G1ContractError("FullGameResult run status非法")
        for name in (
            "artifact_complete",
            "full_game",
            "formal_matrix_cell",
            "natural_terminal",
            "safety_cap_hit",
            "strict_replay_verified",
        ):
            _boolean(getattr(self, name), name)
        facts = frozenset(self.verified_fact_ids)
        if not facts.issubset(CELL_ATOMIC_PROOF_FACTS_V1):
            raise C8G1ContractError("FullGameResult包含未知proof fact")
        witnesses = tuple(self.required_event_witnesses)
        if tuple(item.obligation_id for item in witnesses) != (
            REQUIRED_EVENT_OBLIGATION_IDS_V1
        ):
            raise C8G1ContractError("required-event witnesses必须完整且canonical有序")
        object.__setattr__(self, "verified_fact_ids", facts)
        object.__setattr__(self, "required_event_witnesses", witnesses)
        rescues = tuple(self.successful_rescue_evidence_identities)
        for identity in rescues:
            _sha256(identity, "successful rescue evidence identity")
        object.__setattr__(self, "successful_rescue_evidence_identities", rescues)

    @classmethod
    def from_dict(cls, _value: object) -> "FullGameResultV1":
        raise C8G1ContractError(
            "serialized FullGameResult/replay_verified不得恢复fresh authority"
        )

    def proof_flags(self) -> Mapping[str, bool]:
        facts = self.verified_fact_ids
        atomic = {
            f"CELL_{name}": name in facts
            for name in sorted(CELL_ATOMIC_PROOF_FACTS_V1)
        }
        atomic["CELL_SAFETY_CAP_NOT_HIT"] = self.safety_cap_hit is False
        atomic["CELL_PUBLIC_CONTROLLER_ADAPTER_PROVEN"] = (
            atomic["CELL_PUBLIC_ADAPTER_AUTHORITY_PROVEN"]
            and atomic["CELL_CONTROLLER_AUTHORITY_PROVEN"]
        )
        atomic["CELL_ALL_WINDOWS_CLEAN_AT_TERMINAL"] = atomic[
            "CELL_TERMINAL_WINDOWS_CLEAN_PROVEN"
        ]
        atomic["CELL_COLD_STRICT_REEXECUTION_PROVEN"] = (
            self.strict_replay_verified
            and atomic["CELL_FULL_GAME_REPLAY_STRICT_VERIFIED"]
        )
        composition_inputs = (
            self.run_status is CellRunStatusV1.COMPLETE,
            self.artifact_complete,
            self.full_game,
            self.formal_matrix_cell,
            self.natural_terminal,
            not self.safety_cap_hit,
            self.strict_replay_verified,
            *(value for key, value in atomic.items() if key not in {
                "CELL_UNRESOLVED_CONTEXT_POLICY_PROVEN",
            }),
        )
        atomic["CELL_FULL_GAME_COMPOSITION_PROVEN"] = all(composition_inputs)
        atomic["CELL_PROOF"] = atomic["CELL_FULL_GAME_COMPOSITION_PROVEN"]
        return MappingProxyType(dict(sorted(atomic.items())))

    def to_report_dict(self) -> dict[str, object]:
        return {
            "schema": C8_G1_CELL_SCHEMA,
            "contract_version": C8_G1_CONTRACT_VERSION,
            "authority": "REPORT_ONLY_NOT_REHYDRATABLE",
            "cell_id": self.cell_id,
            "seed": self.seed,
            "mode_id": self.mode_id,
            "registry_identity": self.registry_identity,
            "current_implementation_identity": self.current_implementation_identity,
            "contract_identity": self.contract_identity,
            "timer_profile_id": self.timer_profile_id,
            "driver_policy_identity": self.driver_policy_identity,
            "replay_schema": self.replay_schema,
            "replay_scope": self.replay_scope,
            "production_adapter_id": self.production_adapter_id,
            "production_adapter_contract_identity": (
                self.production_adapter_contract_identity
            ),
            "controller_contract_identity": self.controller_contract_identity,
            "artifact_scope": self.artifact_scope.value,
            "run_status": self.run_status.value,
            "artifact_complete": self.artifact_complete,
            "full_game": self.full_game,
            "formal_matrix_cell": self.formal_matrix_cell,
            "natural_terminal": self.natural_terminal,
            "safety_cap_hit": self.safety_cap_hit,
            "strict_replay_verified": self.strict_replay_verified,
            "replay_identity": self.replay_identity,
            "artifact_identity": self.artifact_identity,
            "proof_flags": dict(self.proof_flags()),
            "successful_rescue_evidence_identities": list(self.successful_rescue_evidence_identities),
            "required_event_witnesses": [
                item.to_dict() for item in self.required_event_witnesses
            ],
        }


def _fresh_full_game_result_v1(**values: object) -> FullGameResultV1:
    """Internal seam reserved for the future G3 fresh verifier and policy tests."""

    return FullGameResultV1(
        **values, _authority_token=_FRESH_RESULT_AUTHORITY_TOKEN
    )  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True)
class PromotionDecisionV1:
    status: PromotionStatusV1
    selected_cell_ids: tuple[str, ...]
    promoted_candidate_artifacts: tuple[tuple[str, str], ...]
    reason_codes: tuple[str, ...]
    required_event_gaps: tuple[str, ...]
    _authority_token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._authority_token is not _PROMOTION_DECISION_AUTHORITY_TOKEN:
            raise C8G1ContractError(
                "PromotionDecision只能由fresh promotion gate派生"
            )

    @property
    def promotable_to_formal(self) -> bool:
        return self.status is PromotionStatusV1.PROMOTABLE_TO_FORMAL

    @property
    def decision_identity(self) -> str:
        return identity_v1(self.to_dict(include_identity=False))

    def to_dict(self, *, include_identity: bool = True) -> dict[str, object]:
        value: dict[str, object] = {
            "schema": C8_G1_PROMOTION_SCHEMA,
            "contract_version": C8_G1_CONTRACT_VERSION,
            "status": self.status.value,
            "selected_cell_ids": list(self.selected_cell_ids),
            "promoted_candidate_artifacts": [
                {"final_cell_id": cell_id, "candidate_artifact_identity": artifact}
                for cell_id, artifact in self.promoted_candidate_artifacts
            ],
            "reason_codes": list(self.reason_codes),
            "required_event_gaps": list(self.required_event_gaps),
        }
        if include_identity:
            value["decision_identity"] = self.decision_identity
        return value

    @classmethod
    def from_dict(cls, _value: object) -> "PromotionDecisionV1":
        raise C8G1ContractError(
            "serialized promotion/ready/pass flag没有promotion authority"
        )


def _required_event_gaps_v1(
    results: Sequence[FullGameResultV1],
) -> tuple[str, ...]:
    gaps: list[str] = []
    for obligation in REQUIRED_EVENT_OBLIGATIONS_V1:
        statuses = [
            result.required_event_witnesses[
                REQUIRED_EVENT_OBLIGATION_IDS_V1.index(obligation.obligation_id)
            ].status
            for result in results
        ]
        if all(
            status is WitnessStatusV1.NOT_APPLICABLE_IN_C6_NO_SKILL_8P
            for status in statuses
        ):
            if obligation.applicability is not (
                ObligationApplicabilityV1.NOT_APPLICABLE_IN_C6_NO_SKILL_8P
            ):
                gaps.append(obligation.obligation_id)
            continue
        if obligation.level is ObligationLevelV1.PER_CELL_REQUIRED:
            if any(status is not WitnessStatusV1.OBSERVED for status in statuses):
                gaps.append(obligation.obligation_id)
        elif obligation.level is ObligationLevelV1.MATRIX_UNION_REQUIRED:
            if WitnessStatusV1.OBSERVED not in statuses:
                gaps.append(obligation.obligation_id)
        elif obligation.level is ObligationLevelV1.CONDITIONAL_MATRIX_UNION_REQUIRED:
            observed = WitnessStatusV1.OBSERVED in statuses
            not_observed = all(
                status is WitnessStatusV1.NOT_NATURALLY_OBSERVED
                for status in statuses
            )
            policy = all(
                "UNRESOLVED_CONTEXT_POLICY_PROVEN" in result.verified_fact_ids
                for result in results
            )
            if not (observed or (not_observed and policy)):
                gaps.append(obligation.obligation_id)
        elif obligation.level is ObligationLevelV1.AUDITED_PREREQUISITE:
            if any(
                status is not WitnessStatusV1.AUDITED_PREREQUISITE_PASSED
                for status in statuses
            ):
                gaps.append(obligation.obligation_id)
        elif any(
            status is not WitnessStatusV1.NOT_APPLICABLE_IN_C6_NO_SKILL_8P
            for status in statuses
        ):
            gaps.append(obligation.obligation_id)
    return tuple(gaps)


def derive_baseline_gap_state_v1(
    results: Sequence[FullGameResultV1],
    *,
    expected_current_implementation_identity: str,
) -> BaselineGapStateV1:
    """Derive the only authority accepted by sentinel discovery."""

    cells = tuple(results)
    expected_registry = FullGameRegistryV1.canonical()
    expected_identity = _sha256(
        expected_current_implementation_identity,
        "expected_current_implementation_identity",
    )
    expected_ids = tuple(item.cell_id for item in expected_registry.baseline_cells)
    if any(not isinstance(item, FullGameResultV1) for item in cells):
        raise C8G1ContractError("baseline derivation只接受fresh FullGameResultV1")
    if tuple(item.cell_id for item in cells) != expected_ids:
        raise C8G1ContractError("baseline derivation必须先完成exact ordered 0/1/49")
    for item in cells:
        if item.registry_identity != expected_registry.registry_identity:
            raise C8G1ContractError("baseline result registry identity mismatch")
        if (
            item.current_implementation_identity != expected_identity
            or item.contract_identity != C8_G1_CONTRACT_IDENTITY
            or item.timer_profile_id != C8_G1_TIMER_PROFILE_ID
            or item.driver_policy_identity != C8_G1_DRIVER_POLICY_IDENTITY
        ):
            raise C8G1ContractError("baseline result source/contract/profile/driver drift")
        if item.artifact_scope is not CandidateScopeV1.FORMAL_QUALITY_CANDIDATE:
            raise C8G1ContractError("baseline discovery输入必须是formal-quality candidate")
        if item.run_status is not CellRunStatusV1.COMPLETE or (
            item.proof_flags()["CELL_PROOF"] is not True
        ):
            raise C8G1ContractError("baseline未完成fresh full-game/cold proof")
    union_ids = {
        item.obligation_id
        for item in REQUIRED_EVENT_OBLIGATIONS_V1
        if item.level
        in {
            ObligationLevelV1.MATRIX_UNION_REQUIRED,
            ObligationLevelV1.CONDITIONAL_MATRIX_UNION_REQUIRED,
        }
    }
    gaps = tuple(
        item for item in _required_event_gaps_v1(cells) if item in union_ids
    )
    return BaselineGapStateV1(
        expected_ids,
        expected_registry.registry_identity,
        gaps,
        _authority_token=_BASELINE_GAP_STATE_AUTHORITY_TOKEN,
    )


def evaluate_promotion_v1(
    registry: FullGameRegistryV1,
    results: Sequence[FullGameResultV1],
    *,
    expected_current_implementation_identity: str,
) -> PromotionDecisionV1:
    if not isinstance(registry, FullGameRegistryV1):
        raise C8G1ContractError("promotion必须使用FullGameRegistryV1")
    expected_identity = _sha256(
        expected_current_implementation_identity,
        "expected_current_implementation_identity",
    )
    cells = tuple(results)
    reasons: set[str] = set()
    if any(not isinstance(item, FullGameResultV1) for item in cells):
        raise C8G1ContractError("promotion results必须是fresh FullGameResultV1")
    expected_ids = tuple(item.cell_id for item in registry.selected_cells)
    actual_ids = tuple(item.cell_id for item in cells)
    if actual_ids != expected_ids or len(actual_ids) != len(set(actual_ids)):
        reasons.add("ORDERED_REGISTRY_MISMATCH")
    for result in cells:
        # Candidate artifacts are immutable: baseline cells bind the exact
        # baseline registry, while a sentinel binds baseline + itself.  The
        # final selected registry is derived here and the promotion record maps
        # each original artifact identity to its final cell id; no replay bytes
        # are rewritten merely to add later-discovered sentinels.
        candidate_registry = (
            FullGameRegistryV1.canonical()
            if result.seed in C8_G1_BASELINE_SEEDS
            else FullGameRegistryV1.canonical((result.seed,))
        )
        if result.registry_identity != candidate_registry.registry_identity:
            reasons.add("CANDIDATE_REGISTRY_IDENTITY_MISMATCH")
        if result.current_implementation_identity != expected_identity:
            reasons.add("IMPLEMENTATION_IDENTITY_MISMATCH")
        if result.contract_identity != C8_G1_CONTRACT_IDENTITY:
            reasons.add("CONTRACT_IDENTITY_MISMATCH")
        if result.mode_id != C8_G1_BASE_MODE_ID:
            reasons.add("CANONICAL_C6_MODE_MISMATCH")
        if result.timer_profile_id != C8_G1_TIMER_PROFILE_ID:
            reasons.add("PROFILE_IDENTITY_MISMATCH")
        if result.driver_policy_identity != C8_G1_DRIVER_POLICY_IDENTITY:
            reasons.add("DRIVER_IDENTITY_MISMATCH")
        if result.replay_schema != C8_G1_REPLAY_SCHEMA:
            reasons.add("REPLAY_SCHEMA_MISMATCH")
        if result.production_adapter_id != C8_G1_E_ADAPTER_ID or (
            result.production_adapter_contract_identity
            != C8_G1_E_CONTRACT_IDENTITY
        ):
            reasons.add("E_ADAPTER_IDENTITY_MISMATCH")
        if result.controller_contract_identity != (
            C8_G1_C_CONTROLLER_CONTRACT_IDENTITY
        ):
            reasons.add("CONTROLLER_IDENTITY_MISMATCH")
        if result.artifact_scope is not CandidateScopeV1.FORMAL_QUALITY_CANDIDATE:
            reasons.add("NOT_FORMAL_QUALITY_CANDIDATE")
        if result.replay_scope != "FULL_GAME_REAL_PRODUCTION_TRACE":
            reasons.add("WRONG_REPLAY_SCOPE")
        if result.run_status is not CellRunStatusV1.COMPLETE:
            reasons.add("CELL_FAILED_OR_INCOMPLETE")
        if result.safety_cap_hit:
            reasons.add("SAFETY_CAP_HIT")
        if not result.artifact_complete:
            reasons.add("ARTIFACT_INCOMPLETE")
        if not result.natural_terminal:
            reasons.add("NON_NATURAL_TERMINAL")
        if not result.strict_replay_verified:
            reasons.add("STRICT_REPLAY_NOT_VERIFIED")
        if not result.full_game or not result.formal_matrix_cell:
            reasons.add("FULL_GAME_FORMAL_CELL_SCOPE_MISMATCH")
        if result.proof_flags()["CELL_PROOF"] is not True:
            reasons.add("CELL_PROOF_INCOMPLETE")
    gaps = _required_event_gaps_v1(cells) if cells else tuple(
        item.obligation_id for item in REQUIRED_EVENT_OBLIGATIONS_V1
    )
    if gaps:
        reasons.add("REQUIRED_EVENT_GAP")
    status = (
        PromotionStatusV1.PROMOTABLE_TO_FORMAL
        if not reasons
        else PromotionStatusV1.NOT_PROMOTABLE
    )
    return PromotionDecisionV1(
        status,
        expected_ids,
        tuple((item.cell_id, item.artifact_identity) for item in cells),
        tuple(sorted(reasons)),
        tuple(gaps),
        _authority_token=_PROMOTION_DECISION_AUTHORITY_TOKEN,
    )


@dataclass(frozen=True, slots=True)
class FullGameMatrixAggregateV1:
    registry: FullGameRegistryV1
    selected_cell_ids: tuple[str, ...]
    failed_cell_ids: tuple[str, ...]
    per_cell_proof_flags: Mapping[str, Mapping[str, bool]]
    per_cell_required_events: Mapping[str, tuple[RequiredEventWitnessV1, ...]]
    matrix_union_events: tuple[str, ...]
    required_event_gaps: tuple[str, ...]
    replay_status: str
    terminal_status: str
    promotion_decision: PromotionDecisionV1
    matrix_status: MatrixStatusV1

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": C8_G1_MATRIX_SCHEMA,
            "contract_version": C8_G1_CONTRACT_VERSION,
            "authority": "FRESH_DERIVATION_ONLY",
            "registry": self.registry.to_dict(),
            "selected_cell_ids": list(self.selected_cell_ids),
            "failed_cell_ids": list(self.failed_cell_ids),
            "per_cell_proof_flags": {
                key: dict(value) for key, value in self.per_cell_proof_flags.items()
            },
            "per_cell_required_events": {
                key: [item.to_dict() for item in value]
                for key, value in self.per_cell_required_events.items()
            },
            "matrix_union_events": list(self.matrix_union_events),
            "required_event_gaps": list(self.required_event_gaps),
            "replay_status": self.replay_status,
            "terminal_status": self.terminal_status,
            "promotion_status": self.promotion_decision.status.value,
            "promotion_decision_identity": self.promotion_decision.decision_identity,
            "matrix_status": self.matrix_status.value,
        }

    @classmethod
    def from_dict(cls, _value: object) -> "FullGameMatrixAggregateV1":
        raise C8G1ContractError(
            "serialized matrix ready/passed/coverage不能恢复aggregate authority"
        )


def derive_matrix_aggregate_v1(
    registry: FullGameRegistryV1,
    results: Sequence[FullGameResultV1],
    *,
    expected_current_implementation_identity: str,
) -> FullGameMatrixAggregateV1:
    cells = tuple(results)
    promotion = evaluate_promotion_v1(
        registry,
        cells,
        expected_current_implementation_identity=expected_current_implementation_identity,
    )
    flags = MappingProxyType(
        {item.cell_id: item.proof_flags() for item in cells}
    )
    per_cell_events = MappingProxyType(
        {item.cell_id: item.required_event_witnesses for item in cells}
    )
    failed = tuple(
        item.cell_id
        for item in cells
        if item.run_status is not CellRunStatusV1.COMPLETE
        or item.proof_flags()["CELL_PROOF"] is not True
    )
    union = tuple(
        obligation_id
        for obligation_id in REQUIRED_EVENT_OBLIGATION_IDS_V1
        if any(
            item.required_event_witnesses[
                REQUIRED_EVENT_OBLIGATION_IDS_V1.index(obligation_id)
            ].status
            in {
                WitnessStatusV1.OBSERVED,
                WitnessStatusV1.AUDITED_PREREQUISITE_PASSED,
                WitnessStatusV1.NOT_APPLICABLE_IN_C6_NO_SKILL_8P,
            }
            for item in cells
        )
    )
    gaps = promotion.required_event_gaps
    if promotion.promotable_to_formal:
        matrix_status = MatrixStatusV1.PASSED_PROVISIONAL_PENDING_EXTERNAL_AUDIT
    elif len(cells) != len(registry.selected_cells):
        matrix_status = MatrixStatusV1.INCOMPLETE
    else:
        matrix_status = MatrixStatusV1.FAILED
    replay_status = (
        "ALL_CELLS_COLD_REPLAY_MATCH"
        if cells and all(item.strict_replay_verified for item in cells)
        else "NOT_PROVEN_OR_MISMATCH"
    )
    terminal_status = (
        "ALL_CELLS_NATURAL_TERMINAL"
        if cells and all(item.natural_terminal for item in cells)
        else "NOT_PROVEN_OR_INCOMPLETE"
    )
    return FullGameMatrixAggregateV1(
        registry,
        tuple(item.cell_id for item in cells),
        failed,
        flags,
        per_cell_events,
        union,
        gaps,
        replay_status,
        terminal_status,
        promotion,
        matrix_status,
    )


@dataclass(frozen=True, slots=True)
class FullGameCellArtifactRefV1:
    cell_id: str
    replay_identity: str
    artifact_identity: str
    artifact_sha256: str

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {"cell_id", "replay_identity", "artifact_identity", "artifact_sha256"}
    )

    def __post_init__(self) -> None:
        _text_id(self.cell_id, "cell_id")
        for name in ("replay_identity", "artifact_identity", "artifact_sha256"):
            _sha256(getattr(self, name), name)

    def to_dict(self) -> dict[str, object]:
        return {
            "cell_id": self.cell_id,
            "replay_identity": self.replay_identity,
            "artifact_identity": self.artifact_identity,
            "artifact_sha256": self.artifact_sha256,
        }

    @classmethod
    def from_dict(cls, value: object) -> "FullGameCellArtifactRefV1":
        data = _exact_keys(value, cls._FIELDS, "completed cell artifact ref")
        return cls(
            cell_id=_text_id(data["cell_id"], "cell_id"),
            replay_identity=_sha256(data["replay_identity"], "replay_identity"),
            artifact_identity=_sha256(data["artifact_identity"], "artifact_identity"),
            artifact_sha256=_sha256(data["artifact_sha256"], "artifact_sha256"),
        )


@dataclass(frozen=True, slots=True)
class FullGameProgressV1:
    current_implementation_identity: str
    registry: FullGameRegistryV1
    completed_cells: tuple[FullGameCellArtifactRefV1, ...]
    failed_cell_ids: tuple[str, ...]
    replay_execution_status: str
    promotion_status: PromotionStatusV1

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "contract_version",
            "contract_identity",
            "timer_profile_id",
            "driver_policy_identity",
            "current_implementation_identity",
            "registry",
            "completed_cells",
            "failed_cell_ids",
            "replay_execution_status",
            "promotion_status",
        }
    )

    def __post_init__(self) -> None:
        _sha256(self.current_implementation_identity, "current_implementation_identity")
        if not isinstance(self.registry, FullGameRegistryV1):
            raise C8G1ContractError("progress registry非法")
        completed = tuple(self.completed_cells)
        if len(completed) > len(self.registry.selected_cells):
            raise C8G1ContractError("completed artifacts不是registry continuous prefix")
        if any(not isinstance(item, FullGameCellArtifactRefV1) for item in completed):
            raise C8G1ContractError("completed_cells类型非法")
        selected_ids = tuple(item.cell_id for item in self.registry.selected_cells)
        if tuple(item.cell_id for item in completed) != selected_ids[: len(completed)]:
            raise C8G1ContractError("completed cells必须是ordered registry continuous prefix")
        failed = tuple(self.failed_cell_ids)
        if len(set(failed)) != len(failed) or any(item not in selected_ids for item in failed):
            raise C8G1ContractError("progress failed_cell_ids非法")
        if failed and (
            len(failed) != 1
            or len(completed) >= len(selected_ids)
            or failed[0] != selected_ids[len(completed)]
        ):
            raise C8G1ContractError("failed cell只能是continuous prefix的下一cell")
        if self.replay_execution_status not in {"NOT_PROVEN", "PARTIAL", "VERIFIED"}:
            raise C8G1ContractError("progress replay_execution_status非法")
        if not isinstance(self.promotion_status, PromotionStatusV1):
            raise C8G1ContractError("progress promotion_status非法")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": C8_G1_PROGRESS_SCHEMA,
            "contract_version": C8_G1_CONTRACT_VERSION,
            "contract_identity": C8_G1_CONTRACT_IDENTITY,
            "timer_profile_id": C8_G1_TIMER_PROFILE_ID,
            "driver_policy_identity": C8_G1_DRIVER_POLICY_IDENTITY,
            "current_implementation_identity": self.current_implementation_identity,
            "registry": self.registry.to_dict(),
            "completed_cells": [item.to_dict() for item in self.completed_cells],
            "failed_cell_ids": list(self.failed_cell_ids),
            "replay_execution_status": self.replay_execution_status,
            "promotion_status": self.promotion_status.value,
        }

    @classmethod
    def from_dict(cls, value: object) -> "FullGameProgressV1":
        data = _exact_keys(value, cls._FIELDS, "full-game progress")
        if data["schema"] != C8_G1_PROGRESS_SCHEMA:
            raise C8G1ContractError("progress schema mismatch")
        if _integer(data["contract_version"], "contract_version", minimum=1) != (
            C8_G1_CONTRACT_VERSION
        ):
            raise C8G1ContractError("progress version mismatch")
        if _sha256(data["contract_identity"], "contract_identity") != C8_G1_CONTRACT_IDENTITY:
            raise C8G1ContractError("progress contract identity mismatch")
        if data["timer_profile_id"] != C8_G1_TIMER_PROFILE_ID:
            raise C8G1ContractError("progress timer profile mismatch")
        if _sha256(data["driver_policy_identity"], "driver_policy_identity") != C8_G1_DRIVER_POLICY_IDENTITY:
            raise C8G1ContractError("progress driver identity mismatch")
        return cls(
            current_implementation_identity=_sha256(
                data["current_implementation_identity"],
                "current_implementation_identity",
            ),
            registry=FullGameRegistryV1.from_dict(data["registry"]),
            completed_cells=tuple(
                FullGameCellArtifactRefV1.from_dict(item)
                for item in _exact_list(data["completed_cells"], "completed_cells")
            ),
            failed_cell_ids=tuple(
                _text_id(item, f"failed_cell_ids[{index}]")
                for index, item in enumerate(
                    _exact_list(data["failed_cell_ids"], "failed_cell_ids")
                )
            ),
            replay_execution_status=_text_id(
                data["replay_execution_status"], "replay_execution_status"
            ),
            promotion_status=_enum_value(
                PromotionStatusV1, data["promotion_status"], "promotion_status"
            ),
        )


__all__ = [
    "C8G1ContractError",
    "C8_G1_CONTRACT_ID",
    "C8_G1_CONTRACT_IDENTITY",
    "C8_G1_CONTRACT_MATERIAL_IDENTITY",
    "C8_G1_CONTRACT_VERSION",
    "C8_G1_PRIOR_CONTRACT_IDENTITY",
    "C8_G1_PRIOR_DRIVER_POLICY_IDENTITY",
    "C8_G1_PRIOR_STATUS",
    "C8_G1_SUPERSESSION_STATUS",
    "C8_G1_SCOPE_MARKER",
    "C8_G1_SELECTED_MODE_ID",
    "C8_G1_BASE_MODE_ID",
    "C8_G1_TIMER_PROFILE_ID",
    "C8_G1_TIMER_PROFILE_STATUS",
    "C8_G1_DRIVER_POLICY_ID",
    "C8_G1_DRIVER_POLICY_IDENTITY",
    "C8_G1_E_ADAPTER_ID",
    "C8_G1_E_CONTRACT_IDENTITY",
    "C8_G1_C_CONTROLLER_CONTRACT_IDENTITY",
    "C8_G1_REPLAY_SCHEMA",
    "C8_G1_BASELINE_REGISTRY_IDENTITY",
    "C8_G1_FULL_GAME_REPLAY_EXECUTION",
    "C8_G2_PRIOR_BOUNDED_SMOKE_STATUS",
    "BaselineGapStateV1",
    "REQUIRED_EVENT_OBLIGATIONS_V1",
    "REQUIRED_EVENT_OBLIGATION_IDS_V1",
    "REQUIRED_EVENT_REGISTRY_IDENTITY_V1",
    "CandidateScopeV1",
    "CausalRelationKindV2",
    "CellRunStatusV1",
    "DriverDecisionMarkerV1",
    "FormalDriverDecisionV1",
    "FormalDriverInputV1",
    "FullGameCellRefV1",
    "FullGameCellArtifactRefV1",
    "FullGameMatrixAggregateV1",
    "FullGameProgressV1",
    "FullGameRegistryV1",
    "FullGameResultV1",
    "MatrixStatusV1",
    "NaturalTerminalEvidenceV1",
    "ObligationApplicabilityV1",
    "ObligationLevelV1",
    "PromotionDecisionV1",
    "PromotionStatusV1",
    "PublicActionOptionV1",
    "PublicWindowKindV1",
    "RequiredEventObligationV1",
    "RequiredEventWitnessV1",
    "SentinelCandidateV1",
    "SentinelSelectionResultV1",
    "SentinelSelectionStatusV1",
    "TimeoutApplicabilityV1",
    "WitnessStatusV1",
    "WindowRelationEvidenceV3",
    "canonical_cell_id_v1",
    "canonical_json_bytes_v1",
    "canonical_missing_witnesses_v1",
    "choose_formal_driver_action_v1",
    "classify_post_commit_relation_v2",
    "contract_descriptor_v1",
    "derive_matrix_aggregate_v1",
    "derive_baseline_gap_state_v1",
    "evaluate_promotion_v1",
    "formal_driver_policy_descriptor_v1",
    "identity_v1",
    "natural_terminal_outcome_identity_v1",
    "obligation_status_is_gap_v1",
    "parent_close_evidence_identity_v3",
    "post_step_observe_identity_v2",
    "select_sentinels_v1",
    "validate_relation_window_kind_v2",
]
