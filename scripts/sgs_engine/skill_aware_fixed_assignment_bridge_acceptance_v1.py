# -*- coding: utf-8 -*-
"""Bridge-H provisional acceptance contracts and pure authority plumbing.

This module is deliberately separate from the frozen no-skill Stage3 contract.
It consumes only the generic Bridge V1 authority exported by
``skill_aware_fixed_assignment_full_game_bridge``.  Formal matrix execution is
not performed here, and every serialized H artifact is explicitly provisional
until the external batch audit closes the recorded audit debt.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from .formal_duel import implementation_identity
from .replay import sha256_value
from .skill_aware_fixed_assignment_full_game_bridge import (
    BASELINE_18,
    BASELINE_18_REGISTRY_IDENTITY,
    BASELINE_18_SCHEMA,
    BRIDGE_AUTHORITY_PROFILE_IDENTITY,
    BRIDGE_MODE_PROFILE_IDENTITY,
    BRIDGE_SKILL_REGISTRY_IDENTITY,
    CONTRACT_ID as BRIDGE_CONTRACT_ID,
    CONTROLLER_ID,
    CONTROLLER_VERSION,
    DECK_IDENTITY,
    EVENT_OBLIGATION_IDS,
    EVENT_OBLIGATIONS,
    FORMAL_DUEL_PROFILE_IDENTITY,
    GENERAL_ALLOWLIST,
    GENERAL_REGISTRY_IDENTITY,
    MODE_ID,
    PROPOSED_BRIDGE_CONTRACT_IDENTITY,
    SENTINEL_POLICY,
    FixedAssignment,
)


class BridgeAcceptanceContractError(ValueError):
    """A Bridge-H schema, type, or derived authority failed closed."""


class BridgeAcceptanceIdentityError(BridgeAcceptanceContractError):
    """A Bridge-H or frozen Bridge identity failed closed."""


BRIDGE_H_CONTRACT_ID = "skill-aware-fixed-assignment-bridge-acceptance-v1"
BRIDGE_H_CONTRACT_VERSION = 1
PROVISIONAL_PENDING_AUDIT = "YES"

BRIDGE_ACCEPTANCE_AUTHORITY_SCHEMA_V1 = "sgs-bridge-acceptance-authority-v1"
BRIDGE_ACCEPTANCE_CELL_PROOF_SCHEMA_V1 = "sgs-bridge-acceptance-cell-proof-v1"
BRIDGE_ACCEPTANCE_REGISTRY_CELL_SCHEMA_V1 = (
    "sgs-bridge-acceptance-registry-cell-v1"
)
BRIDGE_ACCEPTANCE_REGISTRY_SCHEMA_V1 = "sgs-bridge-acceptance-registry-v1"
BRIDGE_REQUIRED_EVENT_WITNESS_SCHEMA_V1 = "sgs-bridge-required-event-witness-v1"
BRIDGE_REQUIRED_EVENT_COVERAGE_SCHEMA_V1 = "sgs-bridge-required-event-coverage-v1"
BRIDGE_ACCEPTANCE_CELL_SCHEMA_V1 = "sgs-bridge-acceptance-cell-v1"
BRIDGE_SENTINEL_OBSERVATION_SCHEMA_V1 = "sgs-bridge-sentinel-observation-v1"
BRIDGE_SENTINEL_CANDIDATE_SCHEMA_V1 = "sgs-bridge-sentinel-candidate-v1"
BRIDGE_SENTINEL_REGISTRY_SCHEMA_V1 = "sgs-bridge-sentinel-registry-v1"
BRIDGE_ACCEPTANCE_MATRIX_SCHEMA_V1 = "sgs-bridge-acceptance-matrix-v1"
BRIDGE_ACCEPTANCE_ARTIFACT_SCHEMA_V1 = "sgs-bridge-acceptance-artifact-v1"
BRIDGE_ACCEPTANCE_PROGRESS_SCHEMA_V1 = "sgs-bridge-acceptance-progress-v1"
BRIDGE_ACCEPTANCE_RESULT_SCHEMA_V1 = "sgs-bridge-acceptance-result-v1"

BRIDGE_REQUIRED_EVENT_IDS_V1 = (
    "EV-G1-JILI-01",
    "EV-G2-ZUILUN-01",
    "EV-G2-FUYIN-01",
    "EV-G3-QIANCHONG-01",
    "EV-G3-SHANGJIAN-01",
)
if EVENT_OBLIGATION_IDS != BRIDGE_REQUIRED_EVENT_IDS_V1:
    raise BridgeAcceptanceIdentityError(
        "Bridge-H required event IDs与frozen Bridge obligation authority不一致"
    )

_EVENT_GENERAL_BY_ID = MappingProxyType(
    {item.event_id: item.general_key for item in EVENT_OBLIGATIONS}
)

BRIDGE_ACCEPTANCE_PROOF_FLAG_NAMES_V1 = (
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

_TERMINAL_BOOL_FIELDS_V1 = frozenset(
    {
        "engine_finished_invariants_passed",
        "skill_pending_none",
        "skill_trigger_queue_empty",
        "pending_private_card_selection_none",
        "pending_skill_hp_loss_none",
        "pending_card_continuation_none",
        "end_phase_dispatch_state_none",
        "continuation_in_progress_none",
        "response_window_none",
        "pending_dying_none",
        "processing_empty",
        "revealed_empty",
        "post_finish_step_blocked",
        "post_finish_action_surface_blocked",
        "end_dispatcher_cannot_resume",
    }
)
_TERMINAL_FIELDS_V1 = _TERMINAL_BOOL_FIELDS_V1 | frozenset(
    {"finished", "phase", "winner", "finish_reason"}
)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_BASELINE_CELL_RE = re.compile(r"^B18-[0-9]{3}$")
_SENTINEL_CELL_RE = re.compile(
    r"^SENTINEL-(SHAMOKE|ZHUGEZHAN|WANGYUANJI)-(P1|P2)-SEED-([0-9]{1,2})$"
)


def _exact_dict(value: object, label: str) -> dict[str, Any]:
    if type(value) is not dict:
        raise BridgeAcceptanceContractError(f"{label}必须是精确JSON object")
    if any(type(key) is not str for key in value):
        raise BridgeAcceptanceContractError(f"{label}字段名必须是精确字符串")
    return value


def _exact_fields(
    value: Mapping[str, object], expected: frozenset[str], label: str
) -> None:
    actual = frozenset(value)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise BridgeAcceptanceContractError(
            f"{label}字段必须精确匹配schema；missing={missing}, extra={extra}"
        )


def _text(value: object, label: str) -> str:
    if type(value) is not str or not value.strip():
        raise BridgeAcceptanceContractError(f"{label}必须是精确非空字符串")
    return value


def _integer(value: object, label: str, *, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise BridgeAcceptanceContractError(
            f"{label}必须是大于等于{minimum}的精确整数"
        )
    return value


def _boolean(value: object, label: str) -> bool:
    if type(value) is not bool:
        raise BridgeAcceptanceContractError(f"{label}必须是精确布尔值")
    return value


def _sha256(value: object, label: str) -> str:
    result = _text(value, label)
    if _SHA256_RE.fullmatch(result) is None:
        raise BridgeAcceptanceContractError(f"{label}必须是64位小写SHA-256")
    return result


def _json_list(value: object, label: str) -> list[object]:
    if type(value) is not list:
        raise BridgeAcceptanceContractError(f"{label}必须是精确JSON array")
    return value


def _text_tuple(
    value: object,
    label: str,
    *,
    allow_empty: bool = True,
    unique: bool = True,
) -> tuple[str, ...]:
    if type(value) is not tuple or any(type(item) is not str for item in value):
        raise BridgeAcceptanceContractError(f"{label}必须是精确字符串tuple")
    result = value
    if not allow_empty and not result:
        raise BridgeAcceptanceContractError(f"{label}不得为空")
    if unique and len(result) != len(set(result)):
        raise BridgeAcceptanceContractError(f"{label}不得重复")
    return result


def _text_tuple_from_json(
    value: object,
    label: str,
    *,
    allow_empty: bool = True,
    unique: bool = True,
) -> tuple[str, ...]:
    items = _json_list(value, label)
    if any(type(item) is not str for item in items):
        raise BridgeAcceptanceContractError(f"{label}必须只含精确字符串")
    return _text_tuple(
        tuple(items), label, allow_empty=allow_empty, unique=unique
    )


def _freeze(value: object) -> object:
    if type(value) is dict:
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if type(value) is list:
        return tuple(_freeze(item) for item in value)
    if type(value) is tuple:
        return tuple(_freeze(item) for item in value)
    return value


def _plain(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_plain(item) for item in value]
    return value


def _identity(value: object) -> str:
    return sha256_value(_plain(value))


def _provisional(value: object) -> str:
    if value != PROVISIONAL_PENDING_AUDIT:
        raise BridgeAcceptanceContractError(
            "Bridge-H artifact必须显式PROVISIONAL_PENDING_AUDIT=YES"
        )
    return PROVISIONAL_PENDING_AUDIT


def _schema_version(
    schema: object, version: object, expected_schema: str, label: str
) -> None:
    if schema != expected_schema:
        raise BridgeAcceptanceContractError(f"{label} schema不匹配")
    if type(version) is not int or version != BRIDGE_H_CONTRACT_VERSION:
        raise BridgeAcceptanceContractError(f"{label} version不匹配")


_AUTHORITY_FIELDS = frozenset(
    {
        "schema",
        "version",
        "bridge_h_contract_id",
        "bridge_h_contract_identity",
        "bridge_contract_id",
        "bridge_contract_identity",
        "mode_id",
        "bridge_mode_profile_identity",
        "formal_duel_profile_identity",
        "deck_identity",
        "general_registry_identity",
        "bridge_skill_registry_identity",
        "bridge_authority_profile_identity",
        "baseline_18_registry_identity",
        "controller_id",
        "controller_version",
        "implementation_identity",
        "provisional_pending_audit",
    }
)
_CELL_PROOF_FIELDS = frozenset(
    {
        "schema",
        "version",
        "trace_scope",
        "finished",
        "source_proof_flags",
        "terminal_invariants",
        "source_cell_proof_identity",
        "provisional_pending_audit",
    }
)
_REGISTRY_CELL_FIELDS = frozenset(
    {
        "schema",
        "version",
        "cell_id",
        "general_key",
        "seat_assignment",
        "general_player_id",
        "no_skill_player_id",
        "seed",
        "source_registry_identity",
        "registry_cell_identity",
        "provisional_pending_audit",
    }
)
_REGISTRY_FIELDS = frozenset(
    {
        "schema",
        "version",
        "authority",
        "source_registry_schema",
        "source_registry_identity",
        "cells",
        "registry_identity",
        "provisional_pending_audit",
    }
)
_EVENT_WITNESS_FIELDS = frozenset(
    {
        "schema",
        "version",
        "event_id",
        "general_key",
        "cell_id",
        "source_kind",
        "source_index",
        "source_witness_identity",
        "source_replay_identity",
        "witness_binding_identity",
        "provisional_pending_audit",
    }
)
_EVENT_COVERAGE_FIELDS = frozenset(
    {
        "schema",
        "version",
        "event_id",
        "general_key",
        "witness_cell_ids",
        "witness_binding_identities",
        "coverage_identity",
        "provisional_pending_audit",
    }
)
_CELL_FIELDS = frozenset(
    {
        "schema",
        "version",
        "authority",
        "cell_kind",
        "cell_id",
        "general_key",
        "seat_assignment",
        "general_player_id",
        "no_skill_player_id",
        "seed",
        "registry_cell_identity",
        "replay_artifact_path",
        "replay_artifact_sha256",
        "records_identity",
        "execution_identity",
        "replay_identity",
        "proof",
        "required_event_witnesses",
        "cell_identity",
        "provisional_pending_audit",
    }
)
_SENTINEL_CANDIDATE_FIELDS = frozenset(
    {
        "schema",
        "version",
        "candidate_id",
        "general_key",
        "seat_assignment",
        "seed",
        "closes_event_ids",
        "discovery_artifact_sha256",
        "discovery_witness_identities",
        "discovery_is_formal_evidence",
        "candidate_identity",
        "provisional_pending_audit",
    }
)
_SENTINEL_OBSERVATION_FIELDS = frozenset(
    {
        "schema",
        "version",
        "general_key",
        "seat_assignment",
        "seed",
        "observed_event_ids",
        "discovery_artifact_sha256",
        "discovery_witness_identities",
        "discovery_is_formal_evidence",
        "observation_identity",
        "provisional_pending_audit",
    }
)
_SENTINEL_REGISTRY_FIELDS = frozenset(
    {
        "schema",
        "version",
        "authority",
        "baseline_event_ids",
        "selected_candidates",
        "remaining_event_ids",
        "discovery_status",
        "discovery_is_formal_evidence",
        "registry_identity",
        "provisional_pending_audit",
    }
)
_MATRIX_FIELDS = frozenset(
    {
        "schema",
        "version",
        "authority",
        "ordered_registry_identity",
        "ordered_cell_ids",
        "cells",
        "sentinel_registry",
        "matrix_identity",
        "provisional_pending_audit",
    }
)
_ARTIFACT_FIELDS = frozenset(
    {
        "schema",
        "version",
        "cell_id",
        "artifact_path",
        "artifact_sha256",
        "replay_identity",
        "cell_identity",
        "artifact_identity",
        "provisional_pending_audit",
    }
)
_PROGRESS_FIELDS = frozenset(
    {
        "schema",
        "version",
        "authority",
        "mode",
        "ordered_registry_identity",
        "sentinel_registry_identity",
        "ordered_expected_cell_ids",
        "completed_cell_ids",
        "failed_cell_ids",
        "artifacts",
        "final_artifact_exists",
        "progress_identity",
        "provisional_pending_audit",
    }
)
_RESULT_FIELDS = frozenset(
    {
        "schema",
        "version",
        "authority",
        "matrix_identity",
        "aggregate_proof_flags",
        "required_event_coverage",
        "missing_required_event_ids",
        "result_identity",
        "provisional_pending_audit",
    }
)


def bridge_h_contract_descriptor_v1() -> dict[str, object]:
    """Return the deterministic Bridge-H schema/authority descriptor."""

    return {
        "contract_id": BRIDGE_H_CONTRACT_ID,
        "contract_version": BRIDGE_H_CONTRACT_VERSION,
        "bridge_contract_id": BRIDGE_CONTRACT_ID,
        "bridge_contract_identity": PROPOSED_BRIDGE_CONTRACT_IDENTITY,
        "required_event_ids": list(BRIDGE_REQUIRED_EVENT_IDS_V1),
        "aggregate_proof_flag_names": list(
            BRIDGE_ACCEPTANCE_PROOF_FLAG_NAMES_V1
        ),
        "type_fields": {
            "authority": sorted(_AUTHORITY_FIELDS),
            "cell_proof": sorted(_CELL_PROOF_FIELDS),
            "registry_cell": sorted(_REGISTRY_CELL_FIELDS),
            "registry": sorted(_REGISTRY_FIELDS),
            "event_witness": sorted(_EVENT_WITNESS_FIELDS),
            "event_coverage": sorted(_EVENT_COVERAGE_FIELDS),
            "cell": sorted(_CELL_FIELDS),
            "sentinel_observation": sorted(_SENTINEL_OBSERVATION_FIELDS),
            "sentinel_candidate": sorted(_SENTINEL_CANDIDATE_FIELDS),
            "sentinel_registry": sorted(_SENTINEL_REGISTRY_FIELDS),
            "matrix": sorted(_MATRIX_FIELDS),
            "artifact": sorted(_ARTIFACT_FIELDS),
            "progress": sorted(_PROGRESS_FIELDS),
            "result": sorted(_RESULT_FIELDS),
        },
        "cached_authority_fields_not_accepted": [
            "ready",
            "event_union_complete",
            "sentinel_not_required",
        ],
        "unknown_authority_field_policy": "REJECT",
        "audit_state": "PROVISIONAL_PENDING_AUDIT",
    }


BRIDGE_H_CONTRACT_IDENTITY_V1 = _identity(bridge_h_contract_descriptor_v1())


@dataclass(frozen=True, slots=True)
class BridgeAcceptanceAuthorityV1:
    schema: str
    version: int
    bridge_h_contract_id: str
    bridge_h_contract_identity: str
    bridge_contract_id: str
    bridge_contract_identity: str
    mode_id: str
    bridge_mode_profile_identity: str
    formal_duel_profile_identity: str
    deck_identity: str
    general_registry_identity: str
    bridge_skill_registry_identity: str
    bridge_authority_profile_identity: str
    baseline_18_registry_identity: str
    controller_id: str
    controller_version: int
    implementation_identity: str
    provisional_pending_audit: str

    def __post_init__(self) -> None:
        _schema_version(
            self.schema,
            self.version,
            BRIDGE_ACCEPTANCE_AUTHORITY_SCHEMA_V1,
            "Bridge-H authority",
        )
        expected = {
            "bridge_h_contract_id": BRIDGE_H_CONTRACT_ID,
            "bridge_h_contract_identity": BRIDGE_H_CONTRACT_IDENTITY_V1,
            "bridge_contract_id": BRIDGE_CONTRACT_ID,
            "bridge_contract_identity": PROPOSED_BRIDGE_CONTRACT_IDENTITY,
            "mode_id": MODE_ID,
            "bridge_mode_profile_identity": BRIDGE_MODE_PROFILE_IDENTITY,
            "formal_duel_profile_identity": FORMAL_DUEL_PROFILE_IDENTITY,
            "deck_identity": DECK_IDENTITY,
            "general_registry_identity": GENERAL_REGISTRY_IDENTITY,
            "bridge_skill_registry_identity": BRIDGE_SKILL_REGISTRY_IDENTITY,
            "bridge_authority_profile_identity": BRIDGE_AUTHORITY_PROFILE_IDENTITY,
            "baseline_18_registry_identity": BASELINE_18_REGISTRY_IDENTITY,
            "controller_id": CONTROLLER_ID,
            "controller_version": CONTROLLER_VERSION,
        }
        for field, value in expected.items():
            if getattr(self, field) != value:
                raise BridgeAcceptanceIdentityError(
                    f"Bridge-H authority {field}与current frozen Bridge不匹配"
                )
        _sha256(self.implementation_identity, "implementation_identity")
        if self.implementation_identity != implementation_identity():
            raise BridgeAcceptanceIdentityError(
                "Bridge-H authority implementation_identity与live source不匹配"
            )
        _provisional(self.provisional_pending_audit)

    @classmethod
    def current(cls) -> "BridgeAcceptanceAuthorityV1":
        return cls(
            schema=BRIDGE_ACCEPTANCE_AUTHORITY_SCHEMA_V1,
            version=BRIDGE_H_CONTRACT_VERSION,
            bridge_h_contract_id=BRIDGE_H_CONTRACT_ID,
            bridge_h_contract_identity=BRIDGE_H_CONTRACT_IDENTITY_V1,
            bridge_contract_id=BRIDGE_CONTRACT_ID,
            bridge_contract_identity=PROPOSED_BRIDGE_CONTRACT_IDENTITY,
            mode_id=MODE_ID,
            bridge_mode_profile_identity=BRIDGE_MODE_PROFILE_IDENTITY,
            formal_duel_profile_identity=FORMAL_DUEL_PROFILE_IDENTITY,
            deck_identity=DECK_IDENTITY,
            general_registry_identity=GENERAL_REGISTRY_IDENTITY,
            bridge_skill_registry_identity=BRIDGE_SKILL_REGISTRY_IDENTITY,
            bridge_authority_profile_identity=BRIDGE_AUTHORITY_PROFILE_IDENTITY,
            baseline_18_registry_identity=BASELINE_18_REGISTRY_IDENTITY,
            controller_id=CONTROLLER_ID,
            controller_version=CONTROLLER_VERSION,
            implementation_identity=implementation_identity(),
            provisional_pending_audit=PROVISIONAL_PENDING_AUDIT,
        )

    @classmethod
    def from_dict(cls, value: object) -> "BridgeAcceptanceAuthorityV1":
        data = _exact_dict(value, "Bridge-H authority")
        _exact_fields(data, _AUTHORITY_FIELDS, "Bridge-H authority")
        return cls(
            schema=_text(data["schema"], "authority schema"),
            version=_integer(data["version"], "authority version", minimum=1),
            bridge_h_contract_id=_text(
                data["bridge_h_contract_id"], "bridge_h_contract_id"
            ),
            bridge_h_contract_identity=_sha256(
                data["bridge_h_contract_identity"], "bridge_h_contract_identity"
            ),
            bridge_contract_id=_text(
                data["bridge_contract_id"], "bridge_contract_id"
            ),
            bridge_contract_identity=_sha256(
                data["bridge_contract_identity"], "bridge_contract_identity"
            ),
            mode_id=_text(data["mode_id"], "mode_id"),
            bridge_mode_profile_identity=_sha256(
                data["bridge_mode_profile_identity"],
                "bridge_mode_profile_identity",
            ),
            formal_duel_profile_identity=_sha256(
                data["formal_duel_profile_identity"],
                "formal_duel_profile_identity",
            ),
            deck_identity=_sha256(data["deck_identity"], "deck_identity"),
            general_registry_identity=_sha256(
                data["general_registry_identity"], "general_registry_identity"
            ),
            bridge_skill_registry_identity=_sha256(
                data["bridge_skill_registry_identity"],
                "bridge_skill_registry_identity",
            ),
            bridge_authority_profile_identity=_sha256(
                data["bridge_authority_profile_identity"],
                "bridge_authority_profile_identity",
            ),
            baseline_18_registry_identity=_sha256(
                data["baseline_18_registry_identity"],
                "baseline_18_registry_identity",
            ),
            controller_id=_text(data["controller_id"], "controller_id"),
            controller_version=_integer(
                data["controller_version"], "controller_version", minimum=1
            ),
            implementation_identity=_sha256(
                data["implementation_identity"], "implementation_identity"
            ),
            provisional_pending_audit=_text(
                data["provisional_pending_audit"], "provisional_pending_audit"
            ),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "version": self.version,
            "bridge_h_contract_id": self.bridge_h_contract_id,
            "bridge_h_contract_identity": self.bridge_h_contract_identity,
            "bridge_contract_id": self.bridge_contract_id,
            "bridge_contract_identity": self.bridge_contract_identity,
            "mode_id": self.mode_id,
            "bridge_mode_profile_identity": self.bridge_mode_profile_identity,
            "formal_duel_profile_identity": self.formal_duel_profile_identity,
            "deck_identity": self.deck_identity,
            "general_registry_identity": self.general_registry_identity,
            "bridge_skill_registry_identity": self.bridge_skill_registry_identity,
            "bridge_authority_profile_identity": self.bridge_authority_profile_identity,
            "baseline_18_registry_identity": self.baseline_18_registry_identity,
            "controller_id": self.controller_id,
            "controller_version": self.controller_version,
            "implementation_identity": self.implementation_identity,
            "provisional_pending_audit": self.provisional_pending_audit,
        }

    @property
    def authority_identity(self) -> str:
        return _identity(self.to_dict())


@dataclass(frozen=True, slots=True)
class BridgeAcceptanceRegistryCellV1:
    """One exact H registry row derived from the frozen canonical BASELINE_18."""

    schema: str
    version: int
    cell_id: str
    general_key: str
    seat_assignment: FixedAssignment
    general_player_id: str
    no_skill_player_id: str
    seed: int
    source_registry_identity: str
    registry_cell_identity: str
    provisional_pending_audit: str

    def __post_init__(self) -> None:
        _schema_version(
            self.schema,
            self.version,
            BRIDGE_ACCEPTANCE_REGISTRY_CELL_SCHEMA_V1,
            "Bridge-H registry cell",
        )
        if _BASELINE_CELL_RE.fullmatch(self.cell_id) is None:
            raise BridgeAcceptanceContractError("registry cell_id必须匹配B18-NNN")
        if self.general_key not in GENERAL_ALLOWLIST:
            raise BridgeAcceptanceContractError("registry General不在Bridge allowlist")
        if type(self.seat_assignment) is not FixedAssignment:
            raise BridgeAcceptanceContractError("registry seat类型不匹配")
        _text(self.general_player_id, "registry general_player_id")
        _text(self.no_skill_player_id, "registry no_skill_player_id")
        _integer(self.seed, "registry seed")
        if self.source_registry_identity != BASELINE_18_REGISTRY_IDENTITY:
            raise BridgeAcceptanceIdentityError(
                "registry source identity与frozen BASELINE_18不匹配"
            )
        matches = tuple(item for item in BASELINE_18 if item.cell_id == self.cell_id)
        if len(matches) != 1:
            raise BridgeAcceptanceContractError(
                "registry cell_id无法唯一映射到canonical BASELINE_18"
            )
        canonical = matches[0]
        actual = {
            "cell_id": self.cell_id,
            "general_key": self.general_key,
            "seat_assignment": self.seat_assignment.value,
            "general_player_id": self.general_player_id,
            "no_skill_player_id": self.no_skill_player_id,
            "seed": self.seed,
        }
        expected = canonical.to_registry_descriptor()
        if actual != expected:
            raise BridgeAcceptanceContractError(
                "Bridge-H registry row与canonical BASELINE_18事实不一致"
            )
        _sha256(self.registry_cell_identity, "registry_cell_identity")
        if self.registry_cell_identity != _identity(expected):
            raise BridgeAcceptanceIdentityError("registry_cell_identity不匹配")
        _provisional(self.provisional_pending_audit)

    @classmethod
    def from_baseline_descriptor(
        cls, value: object
    ) -> "BridgeAcceptanceRegistryCellV1":
        if value not in BASELINE_18:
            raise BridgeAcceptanceContractError(
                "H registry cell必须直接来自canonical BASELINE_18 descriptor"
            )
        descriptor = value.to_registry_descriptor()
        return cls(
            schema=BRIDGE_ACCEPTANCE_REGISTRY_CELL_SCHEMA_V1,
            version=BRIDGE_H_CONTRACT_VERSION,
            cell_id=descriptor["cell_id"],
            general_key=descriptor["general_key"],
            seat_assignment=FixedAssignment(descriptor["seat_assignment"]),
            general_player_id=descriptor["general_player_id"],
            no_skill_player_id=descriptor["no_skill_player_id"],
            seed=descriptor["seed"],
            source_registry_identity=BASELINE_18_REGISTRY_IDENTITY,
            registry_cell_identity=_identity(descriptor),
            provisional_pending_audit=PROVISIONAL_PENDING_AUDIT,
        )

    @classmethod
    def from_dict(cls, value: object) -> "BridgeAcceptanceRegistryCellV1":
        data = _exact_dict(value, "Bridge-H registry cell")
        _exact_fields(data, _REGISTRY_CELL_FIELDS, "Bridge-H registry cell")
        try:
            seat = FixedAssignment(
                _text(data["seat_assignment"], "seat_assignment")
            )
        except ValueError as exc:
            raise BridgeAcceptanceContractError("未知registry seat") from exc
        return cls(
            schema=_text(data["schema"], "registry cell schema"),
            version=_integer(
                data["version"], "registry cell version", minimum=1
            ),
            cell_id=_text(data["cell_id"], "cell_id"),
            general_key=_text(data["general_key"], "general_key"),
            seat_assignment=seat,
            general_player_id=_text(
                data["general_player_id"], "general_player_id"
            ),
            no_skill_player_id=_text(
                data["no_skill_player_id"], "no_skill_player_id"
            ),
            seed=_integer(data["seed"], "seed"),
            source_registry_identity=_sha256(
                data["source_registry_identity"], "source_registry_identity"
            ),
            registry_cell_identity=_sha256(
                data["registry_cell_identity"], "registry_cell_identity"
            ),
            provisional_pending_audit=_text(
                data["provisional_pending_audit"], "provisional_pending_audit"
            ),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "version": self.version,
            "cell_id": self.cell_id,
            "general_key": self.general_key,
            "seat_assignment": self.seat_assignment.value,
            "general_player_id": self.general_player_id,
            "no_skill_player_id": self.no_skill_player_id,
            "seed": self.seed,
            "source_registry_identity": self.source_registry_identity,
            "registry_cell_identity": self.registry_cell_identity,
            "provisional_pending_audit": self.provisional_pending_audit,
        }


@dataclass(frozen=True, slots=True)
class BridgeAcceptanceRegistryV1:
    """Exact ordered H view of BASELINE_18; never a second facts source."""

    schema: str
    version: int
    authority: BridgeAcceptanceAuthorityV1
    source_registry_schema: str
    source_registry_identity: str
    cells: tuple[BridgeAcceptanceRegistryCellV1, ...]
    registry_identity: str
    provisional_pending_audit: str

    def __post_init__(self) -> None:
        _schema_version(
            self.schema,
            self.version,
            BRIDGE_ACCEPTANCE_REGISTRY_SCHEMA_V1,
            "Bridge-H acceptance registry",
        )
        if type(self.authority) is not BridgeAcceptanceAuthorityV1:
            raise BridgeAcceptanceContractError("registry authority类型不匹配")
        if self.source_registry_schema != BASELINE_18_SCHEMA:
            raise BridgeAcceptanceIdentityError("BASELINE_18 source schema不匹配")
        if self.source_registry_identity != BASELINE_18_REGISTRY_IDENTITY:
            raise BridgeAcceptanceIdentityError("BASELINE_18 source identity不匹配")
        if type(self.cells) is not tuple or any(
            type(item) is not BridgeAcceptanceRegistryCellV1
            for item in self.cells
        ):
            raise BridgeAcceptanceContractError("registry cells类型不匹配")
        expected = tuple(
            BridgeAcceptanceRegistryCellV1.from_baseline_descriptor(item)
            for item in BASELINE_18
        )
        if self.cells != expected:
            raise BridgeAcceptanceContractError(
                "Bridge-H registry必须精确复用canonical BASELINE_18顺序与事实"
            )
        _sha256(self.registry_identity, "acceptance registry_identity")
        if self.registry_identity != self.compute_identity():
            raise BridgeAcceptanceIdentityError("acceptance registry_identity不匹配")
        _provisional(self.provisional_pending_audit)

    @property
    def ordered_cell_ids(self) -> tuple[str, ...]:
        return tuple(item.cell_id for item in self.cells)

    def identity_material(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "version": self.version,
            "authority": self.authority.to_dict(),
            "source_registry_schema": self.source_registry_schema,
            "source_registry_identity": self.source_registry_identity,
            "cells": [item.to_dict() for item in self.cells],
            "provisional_pending_audit": self.provisional_pending_audit,
        }

    def compute_identity(self) -> str:
        return _identity(self.identity_material())

    @classmethod
    def current(cls) -> "BridgeAcceptanceRegistryV1":
        authority = BridgeAcceptanceAuthorityV1.current()
        cells = tuple(
            BridgeAcceptanceRegistryCellV1.from_baseline_descriptor(item)
            for item in BASELINE_18
        )
        material = {
            "schema": BRIDGE_ACCEPTANCE_REGISTRY_SCHEMA_V1,
            "version": BRIDGE_H_CONTRACT_VERSION,
            "authority": authority.to_dict(),
            "source_registry_schema": BASELINE_18_SCHEMA,
            "source_registry_identity": BASELINE_18_REGISTRY_IDENTITY,
            "cells": [item.to_dict() for item in cells],
            "provisional_pending_audit": PROVISIONAL_PENDING_AUDIT,
        }
        return cls(
            schema=BRIDGE_ACCEPTANCE_REGISTRY_SCHEMA_V1,
            version=BRIDGE_H_CONTRACT_VERSION,
            authority=authority,
            source_registry_schema=BASELINE_18_SCHEMA,
            source_registry_identity=BASELINE_18_REGISTRY_IDENTITY,
            cells=cells,
            registry_identity=_identity(material),
            provisional_pending_audit=PROVISIONAL_PENDING_AUDIT,
        )

    @classmethod
    def from_dict(cls, value: object) -> "BridgeAcceptanceRegistryV1":
        data = _exact_dict(value, "Bridge-H acceptance registry")
        _exact_fields(data, _REGISTRY_FIELDS, "Bridge-H acceptance registry")
        raw_cells = _json_list(data["cells"], "registry cells")
        return cls(
            schema=_text(data["schema"], "registry schema"),
            version=_integer(data["version"], "registry version", minimum=1),
            authority=BridgeAcceptanceAuthorityV1.from_dict(data["authority"]),
            source_registry_schema=_text(
                data["source_registry_schema"], "source_registry_schema"
            ),
            source_registry_identity=_sha256(
                data["source_registry_identity"], "source_registry_identity"
            ),
            cells=tuple(
                BridgeAcceptanceRegistryCellV1.from_dict(item)
                for item in raw_cells
            ),
            registry_identity=_sha256(
                data["registry_identity"], "registry_identity"
            ),
            provisional_pending_audit=_text(
                data["provisional_pending_audit"], "provisional_pending_audit"
            ),
        )

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_material(), "registry_identity": self.registry_identity}


def bridge_acceptance_baseline_registry_v1() -> BridgeAcceptanceRegistryV1:
    return BridgeAcceptanceRegistryV1.current()


@dataclass(frozen=True, slots=True)
class BridgeAcceptanceCellProofV1:
    schema: str
    version: int
    trace_scope: str
    finished: bool
    source_proof_flags: Mapping[str, bool]
    terminal_invariants: Mapping[str, object]
    source_cell_proof_identity: str
    provisional_pending_audit: str

    def __post_init__(self) -> None:
        _schema_version(
            self.schema,
            self.version,
            BRIDGE_ACCEPTANCE_CELL_PROOF_SCHEMA_V1,
            "Bridge-H cell proof",
        )
        if self.trace_scope != "NATURAL_FULL_GAME":
            raise BridgeAcceptanceContractError(
                "Bridge-H cell proof只接受NATURAL_FULL_GAME"
            )
        if _boolean(self.finished, "cell proof finished") is not True:
            raise BridgeAcceptanceContractError(
                "Bridge-H cell proof必须来自fresh formal terminal"
            )
        if not isinstance(self.source_proof_flags, Mapping):
            raise BridgeAcceptanceContractError(
                "source_proof_flags必须是immutable mapping"
            )
        _exact_fields(
            self.source_proof_flags,
            frozenset(BRIDGE_ACCEPTANCE_PROOF_FLAG_NAMES_V1),
            "source_proof_flags",
        )
        for name in BRIDGE_ACCEPTANCE_PROOF_FLAG_NAMES_V1:
            if _boolean(self.source_proof_flags[name], name) is not True:
                raise BridgeAcceptanceContractError(
                    f"Bridge-H completed cell缺少required proof：{name}"
                )
        if not isinstance(self.terminal_invariants, Mapping):
            raise BridgeAcceptanceContractError(
                "terminal_invariants必须是immutable mapping"
            )
        _exact_fields(
            self.terminal_invariants,
            _TERMINAL_FIELDS_V1,
            "terminal_invariants",
        )
        if self.terminal_invariants["finished"] is not True:
            raise BridgeAcceptanceContractError("terminal finished必须为true")
        if self.terminal_invariants["phase"] != "finished":
            raise BridgeAcceptanceContractError("terminal phase必须为finished")
        if self.terminal_invariants["winner"] not in ("p1", "p2"):
            raise BridgeAcceptanceContractError("terminal winner必须为p1或p2")
        _text(self.terminal_invariants["finish_reason"], "finish_reason")
        for name in _TERMINAL_BOOL_FIELDS_V1:
            if self.terminal_invariants[name] is not True:
                raise BridgeAcceptanceContractError(
                    f"terminal invariant未证明：{name}"
                )
        _sha256(self.source_cell_proof_identity, "source_cell_proof_identity")
        _provisional(self.provisional_pending_audit)

    @classmethod
    def from_dict(cls, value: object) -> "BridgeAcceptanceCellProofV1":
        data = _exact_dict(value, "Bridge-H cell proof")
        _exact_fields(data, _CELL_PROOF_FIELDS, "Bridge-H cell proof")
        raw_flags = _exact_dict(data["source_proof_flags"], "source_proof_flags")
        _exact_fields(
            raw_flags,
            frozenset(BRIDGE_ACCEPTANCE_PROOF_FLAG_NAMES_V1),
            "source_proof_flags",
        )
        flags = {
            name: _boolean(raw_flags[name], f"source_proof_flags.{name}")
            for name in BRIDGE_ACCEPTANCE_PROOF_FLAG_NAMES_V1
        }
        terminal = _exact_dict(data["terminal_invariants"], "terminal_invariants")
        _exact_fields(terminal, _TERMINAL_FIELDS_V1, "terminal_invariants")
        return cls(
            schema=_text(data["schema"], "cell proof schema"),
            version=_integer(data["version"], "cell proof version", minimum=1),
            trace_scope=_text(data["trace_scope"], "trace_scope"),
            finished=_boolean(data["finished"], "finished"),
            source_proof_flags=MappingProxyType(flags),
            terminal_invariants=_freeze(terminal),  # type: ignore[arg-type]
            source_cell_proof_identity=_sha256(
                data["source_cell_proof_identity"], "source_cell_proof_identity"
            ),
            provisional_pending_audit=_text(
                data["provisional_pending_audit"], "provisional_pending_audit"
            ),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "version": self.version,
            "trace_scope": self.trace_scope,
            "finished": self.finished,
            "source_proof_flags": dict(self.source_proof_flags),
            "terminal_invariants": _plain(self.terminal_invariants),
            "source_cell_proof_identity": self.source_cell_proof_identity,
            "provisional_pending_audit": self.provisional_pending_audit,
        }


class BridgeCellKindV1(str, Enum):
    BASELINE = "BASELINE"
    SENTINEL = "SENTINEL"


_EVENT_WITNESS_KIND_BY_ID = MappingProxyType(
    {
        "EV-G1-JILI-01": frozenset({"SKILL_OPTIONAL_WINDOW"}),
        "EV-G2-ZUILUN-01": frozenset({"SKILL_OPTIONAL_WINDOW_END_RESUME"}),
        "EV-G2-FUYIN-01": frozenset({"TARGET_EFFECT_FIRST_CHANCE"}),
        "EV-G3-QIANCHONG-01": frozenset(
            {"QIANCHONG_CHOICE", "QIANCHONG_DYNAMIC_GRANT"}
        ),
        "EV-G3-SHANGJIAN-01": frozenset({"SHANGJIAN_LIVE_CONDITION"}),
    }
)


@dataclass(frozen=True, slots=True)
class BridgeRequiredEventWitnessV1:
    schema: str
    version: int
    event_id: str
    general_key: str
    cell_id: str
    source_kind: str
    source_index: int
    source_witness_identity: str
    source_replay_identity: str
    witness_binding_identity: str
    provisional_pending_audit: str

    def __post_init__(self) -> None:
        _schema_version(
            self.schema,
            self.version,
            BRIDGE_REQUIRED_EVENT_WITNESS_SCHEMA_V1,
            "Bridge-H event witness",
        )
        if self.event_id not in BRIDGE_REQUIRED_EVENT_IDS_V1:
            raise BridgeAcceptanceContractError("Bridge-H witness包含未知required event")
        if self.general_key != _EVENT_GENERAL_BY_ID[self.event_id]:
            raise BridgeAcceptanceContractError(
                "Bridge-H witness event与General归属不一致"
            )
        if self.general_key not in GENERAL_ALLOWLIST:
            raise BridgeAcceptanceContractError("Bridge-H witness General不在allowlist")
        _text(self.cell_id, "witness cell_id")
        if self.source_kind not in _EVENT_WITNESS_KIND_BY_ID[self.event_id]:
            raise BridgeAcceptanceContractError(
                "Bridge-H witness source_kind不能证明该required event"
            )
        _integer(self.source_index, "witness source_index")
        _sha256(self.source_witness_identity, "source_witness_identity")
        _sha256(self.source_replay_identity, "source_replay_identity")
        _sha256(self.witness_binding_identity, "witness_binding_identity")
        if self.witness_binding_identity != self.compute_identity():
            raise BridgeAcceptanceIdentityError("witness_binding_identity不匹配")
        _provisional(self.provisional_pending_audit)

    def identity_material(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "version": self.version,
            "event_id": self.event_id,
            "general_key": self.general_key,
            "cell_id": self.cell_id,
            "source_kind": self.source_kind,
            "source_index": self.source_index,
            "source_witness_identity": self.source_witness_identity,
            "source_replay_identity": self.source_replay_identity,
            "provisional_pending_audit": self.provisional_pending_audit,
        }

    def compute_identity(self) -> str:
        return _identity(self.identity_material())

    @classmethod
    def from_dict(cls, value: object) -> "BridgeRequiredEventWitnessV1":
        data = _exact_dict(value, "Bridge-H event witness")
        _exact_fields(data, _EVENT_WITNESS_FIELDS, "Bridge-H event witness")
        return cls(
            schema=_text(data["schema"], "event witness schema"),
            version=_integer(data["version"], "event witness version", minimum=1),
            event_id=_text(data["event_id"], "event_id"),
            general_key=_text(data["general_key"], "general_key"),
            cell_id=_text(data["cell_id"], "cell_id"),
            source_kind=_text(data["source_kind"], "source_kind"),
            source_index=_integer(data["source_index"], "source_index"),
            source_witness_identity=_sha256(
                data["source_witness_identity"], "source_witness_identity"
            ),
            source_replay_identity=_sha256(
                data["source_replay_identity"], "source_replay_identity"
            ),
            witness_binding_identity=_sha256(
                data["witness_binding_identity"], "witness_binding_identity"
            ),
            provisional_pending_audit=_text(
                data["provisional_pending_audit"], "provisional_pending_audit"
            ),
        )

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_material(), "witness_binding_identity": self.witness_binding_identity}


@dataclass(frozen=True, slots=True)
class BridgeRequiredEventCoverageV1:
    schema: str
    version: int
    event_id: str
    general_key: str
    witness_cell_ids: tuple[str, ...]
    witness_binding_identities: tuple[str, ...]
    coverage_identity: str
    provisional_pending_audit: str

    def __post_init__(self) -> None:
        _schema_version(
            self.schema,
            self.version,
            BRIDGE_REQUIRED_EVENT_COVERAGE_SCHEMA_V1,
            "Bridge-H event coverage",
        )
        if self.event_id not in BRIDGE_REQUIRED_EVENT_IDS_V1:
            raise BridgeAcceptanceContractError("coverage包含未知required event")
        if self.general_key != _EVENT_GENERAL_BY_ID[self.event_id]:
            raise BridgeAcceptanceContractError("coverage event与General归属不一致")
        _text_tuple(self.witness_cell_ids, "witness_cell_ids")
        _text_tuple(
            self.witness_binding_identities, "witness_binding_identities"
        )
        if len(self.witness_cell_ids) != len(self.witness_binding_identities):
            raise BridgeAcceptanceContractError(
                "coverage witness cell与binding数量不一致"
            )
        for item in self.witness_binding_identities:
            _sha256(item, "witness_binding_identity")
        _sha256(self.coverage_identity, "coverage_identity")
        if self.coverage_identity != self.compute_identity():
            raise BridgeAcceptanceIdentityError("coverage_identity不匹配")
        _provisional(self.provisional_pending_audit)

    @property
    def covered(self) -> bool:
        return bool(self.witness_cell_ids)

    def identity_material(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "version": self.version,
            "event_id": self.event_id,
            "general_key": self.general_key,
            "witness_cell_ids": list(self.witness_cell_ids),
            "witness_binding_identities": list(
                self.witness_binding_identities
            ),
            "provisional_pending_audit": self.provisional_pending_audit,
        }

    def compute_identity(self) -> str:
        return _identity(self.identity_material())

    @classmethod
    def from_dict(cls, value: object) -> "BridgeRequiredEventCoverageV1":
        data = _exact_dict(value, "Bridge-H event coverage")
        _exact_fields(data, _EVENT_COVERAGE_FIELDS, "Bridge-H event coverage")
        return cls(
            schema=_text(data["schema"], "coverage schema"),
            version=_integer(data["version"], "coverage version", minimum=1),
            event_id=_text(data["event_id"], "event_id"),
            general_key=_text(data["general_key"], "general_key"),
            witness_cell_ids=_text_tuple_from_json(
                data["witness_cell_ids"], "witness_cell_ids"
            ),
            witness_binding_identities=_text_tuple_from_json(
                data["witness_binding_identities"],
                "witness_binding_identities",
            ),
            coverage_identity=_sha256(
                data["coverage_identity"], "coverage_identity"
            ),
            provisional_pending_audit=_text(
                data["provisional_pending_audit"], "provisional_pending_audit"
            ),
        )

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_material(), "coverage_identity": self.coverage_identity}


@dataclass(frozen=True, slots=True)
class BridgeAcceptanceCellV1:
    schema: str
    version: int
    authority: BridgeAcceptanceAuthorityV1
    cell_kind: BridgeCellKindV1
    cell_id: str
    general_key: str
    seat_assignment: FixedAssignment
    general_player_id: str
    no_skill_player_id: str
    seed: int
    registry_cell_identity: str
    replay_artifact_path: str
    replay_artifact_sha256: str
    records_identity: str
    execution_identity: str
    replay_identity: str
    proof: BridgeAcceptanceCellProofV1
    required_event_witnesses: tuple[BridgeRequiredEventWitnessV1, ...]
    cell_identity: str
    provisional_pending_audit: str

    def __post_init__(self) -> None:
        _schema_version(
            self.schema,
            self.version,
            BRIDGE_ACCEPTANCE_CELL_SCHEMA_V1,
            "Bridge-H cell",
        )
        if type(self.authority) is not BridgeAcceptanceAuthorityV1:
            raise BridgeAcceptanceContractError("cell authority类型不匹配")
        if type(self.cell_kind) is not BridgeCellKindV1:
            raise BridgeAcceptanceContractError("cell_kind类型不匹配")
        _text(self.cell_id, "cell_id")
        if self.cell_kind is BridgeCellKindV1.BASELINE:
            if _BASELINE_CELL_RE.fullmatch(self.cell_id) is None:
                raise BridgeAcceptanceContractError("baseline cell_id必须匹配B18-NNN")
        elif _SENTINEL_CELL_RE.fullmatch(self.cell_id) is None:
            raise BridgeAcceptanceContractError("sentinel cell_id格式不匹配")
        if self.general_key not in GENERAL_ALLOWLIST:
            raise BridgeAcceptanceContractError("cell General不在Bridge allowlist")
        if type(self.seat_assignment) is not FixedAssignment:
            raise BridgeAcceptanceContractError("seat_assignment类型不匹配")
        expected_general = (
            "p1"
            if self.seat_assignment is FixedAssignment.GENERAL_AS_P1
            else "p2"
        )
        if self.general_player_id != expected_general:
            raise BridgeAcceptanceContractError("general_player_id与seat不一致")
        expected_no_skill = "p2" if expected_general == "p1" else "p1"
        if self.no_skill_player_id != expected_no_skill:
            raise BridgeAcceptanceContractError("no_skill_player_id与seat不一致")
        _integer(self.seed, "seed")
        _sha256(self.registry_cell_identity, "registry_cell_identity")
        _text(self.replay_artifact_path, "replay_artifact_path")
        for field in (
            "replay_artifact_sha256",
            "records_identity",
            "execution_identity",
            "replay_identity",
            "cell_identity",
        ):
            _sha256(getattr(self, field), field)
        if type(self.proof) is not BridgeAcceptanceCellProofV1:
            raise BridgeAcceptanceContractError("cell proof类型不匹配")
        if type(self.required_event_witnesses) is not tuple:
            raise BridgeAcceptanceContractError(
                "required_event_witnesses必须是tuple"
            )
        witness_ids: list[str] = []
        for witness in self.required_event_witnesses:
            if type(witness) is not BridgeRequiredEventWitnessV1:
                raise BridgeAcceptanceContractError("event witness类型不匹配")
            if witness.cell_id != self.cell_id:
                raise BridgeAcceptanceContractError("event witness绑定到错误cell")
            if witness.general_key != self.general_key:
                raise BridgeAcceptanceContractError("event witness绑定到错误General")
            if witness.source_replay_identity != self.replay_identity:
                raise BridgeAcceptanceContractError("event witness绑定到错误replay")
            witness_ids.append(witness.witness_binding_identity)
        if len(witness_ids) != len(set(witness_ids)):
            raise BridgeAcceptanceContractError("cell event witness不得重复")
        if self.cell_identity != self.compute_identity():
            raise BridgeAcceptanceIdentityError("cell_identity不匹配")
        _provisional(self.provisional_pending_audit)

    @property
    def proof_flags(self) -> Mapping[str, bool]:
        """Derived view; no serialized cell ``proof_flags`` field is accepted."""

        return self.proof.source_proof_flags

    @property
    def observed_required_event_ids(self) -> tuple[str, ...]:
        observed = {item.event_id for item in self.required_event_witnesses}
        return tuple(
            event_id
            for event_id in BRIDGE_REQUIRED_EVENT_IDS_V1
            if event_id in observed
        )

    def identity_material(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "version": self.version,
            "authority": self.authority.to_dict(),
            "cell_kind": self.cell_kind.value,
            "cell_id": self.cell_id,
            "general_key": self.general_key,
            "seat_assignment": self.seat_assignment.value,
            "general_player_id": self.general_player_id,
            "no_skill_player_id": self.no_skill_player_id,
            "seed": self.seed,
            "registry_cell_identity": self.registry_cell_identity,
            "replay_artifact_path": self.replay_artifact_path,
            "replay_artifact_sha256": self.replay_artifact_sha256,
            "records_identity": self.records_identity,
            "execution_identity": self.execution_identity,
            "replay_identity": self.replay_identity,
            "proof": self.proof.to_dict(),
            "required_event_witnesses": [
                item.to_dict() for item in self.required_event_witnesses
            ],
            "provisional_pending_audit": self.provisional_pending_audit,
        }

    def compute_identity(self) -> str:
        return _identity(self.identity_material())

    @classmethod
    def from_dict(cls, value: object) -> "BridgeAcceptanceCellV1":
        data = _exact_dict(value, "Bridge-H cell")
        _exact_fields(data, _CELL_FIELDS, "Bridge-H cell")
        try:
            kind = BridgeCellKindV1(_text(data["cell_kind"], "cell_kind"))
        except ValueError as exc:
            raise BridgeAcceptanceContractError("未知cell_kind") from exc
        try:
            seat = FixedAssignment(
                _text(data["seat_assignment"], "seat_assignment")
            )
        except ValueError as exc:
            raise BridgeAcceptanceContractError("未知seat_assignment") from exc
        witness_values = _json_list(
            data["required_event_witnesses"], "required_event_witnesses"
        )
        return cls(
            schema=_text(data["schema"], "cell schema"),
            version=_integer(data["version"], "cell version", minimum=1),
            authority=BridgeAcceptanceAuthorityV1.from_dict(data["authority"]),
            cell_kind=kind,
            cell_id=_text(data["cell_id"], "cell_id"),
            general_key=_text(data["general_key"], "general_key"),
            seat_assignment=seat,
            general_player_id=_text(
                data["general_player_id"], "general_player_id"
            ),
            no_skill_player_id=_text(
                data["no_skill_player_id"], "no_skill_player_id"
            ),
            seed=_integer(data["seed"], "seed"),
            registry_cell_identity=_sha256(
                data["registry_cell_identity"], "registry_cell_identity"
            ),
            replay_artifact_path=_text(
                data["replay_artifact_path"], "replay_artifact_path"
            ),
            replay_artifact_sha256=_sha256(
                data["replay_artifact_sha256"], "replay_artifact_sha256"
            ),
            records_identity=_sha256(
                data["records_identity"], "records_identity"
            ),
            execution_identity=_sha256(
                data["execution_identity"], "execution_identity"
            ),
            replay_identity=_sha256(data["replay_identity"], "replay_identity"),
            proof=BridgeAcceptanceCellProofV1.from_dict(data["proof"]),
            required_event_witnesses=tuple(
                BridgeRequiredEventWitnessV1.from_dict(item)
                for item in witness_values
            ),
            cell_identity=_sha256(data["cell_identity"], "cell_identity"),
            provisional_pending_audit=_text(
                data["provisional_pending_audit"], "provisional_pending_audit"
            ),
        )

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_material(), "cell_identity": self.cell_identity}


class BridgeSentinelDiscoveryStatusV1(str, Enum):
    NOT_RUN = "NOT_RUN"
    NOT_REQUIRED = "NOT_REQUIRED"
    SELECTED = "SELECTED"
    SENTINEL_DISCOVERY_BLOCKED = "SENTINEL_DISCOVERY_BLOCKED"


@dataclass(frozen=True, slots=True)
class BridgeSentinelObservationV1:
    """One non-formal discovery observation supplied to the pure selector."""

    schema: str
    version: int
    general_key: str
    seat_assignment: FixedAssignment
    seed: int
    observed_event_ids: tuple[str, ...]
    discovery_artifact_sha256: str
    discovery_witness_identities: tuple[str, ...]
    discovery_is_formal_evidence: bool
    observation_identity: str
    provisional_pending_audit: str

    def __post_init__(self) -> None:
        _schema_version(
            self.schema,
            self.version,
            BRIDGE_SENTINEL_OBSERVATION_SCHEMA_V1,
            "Bridge-H sentinel observation",
        )
        if self.general_key not in GENERAL_ALLOWLIST:
            raise BridgeAcceptanceContractError("observation General不在allowlist")
        if type(self.seat_assignment) is not FixedAssignment:
            raise BridgeAcceptanceContractError("observation seat类型不匹配")
        _integer(self.seed, "observation seed")
        if not SENTINEL_POLICY.seed_min <= self.seed <= SENTINEL_POLICY.seed_max:
            raise BridgeAcceptanceContractError("observation seed必须在0..99")
        if self.seed in SENTINEL_POLICY.excluded_seeds:
            raise BridgeAcceptanceContractError("observation不得复用baseline seed")
        _text_tuple(self.observed_event_ids, "observed_event_ids")
        if self.observed_event_ids != _ordered_event_ids(set(self.observed_event_ids)):
            raise BridgeAcceptanceContractError("observed_event_ids顺序必须canonical")
        if any(
            _EVENT_GENERAL_BY_ID[event_id] != self.general_key
            for event_id in self.observed_event_ids
        ):
            raise BridgeAcceptanceContractError(
                "sentinel observation不得声称其他General的required event"
            )
        _sha256(self.discovery_artifact_sha256, "discovery_artifact_sha256")
        _text_tuple(
            self.discovery_witness_identities,
            "discovery_witness_identities",
        )
        if len(self.discovery_witness_identities) != len(self.observed_event_ids):
            raise BridgeAcceptanceContractError(
                "observation event与witness数量不一致"
            )
        for value in self.discovery_witness_identities:
            _sha256(value, "discovery_witness_identity")
        if _boolean(
            self.discovery_is_formal_evidence,
            "discovery_is_formal_evidence",
        ) is not False:
            raise BridgeAcceptanceContractError("discovery observation不是formal evidence")
        _sha256(self.observation_identity, "observation_identity")
        if self.observation_identity != self.compute_identity():
            raise BridgeAcceptanceIdentityError("observation_identity不匹配")
        _provisional(self.provisional_pending_audit)

    @property
    def search_key(self) -> tuple[str, FixedAssignment, int]:
        return (self.general_key, self.seat_assignment, self.seed)

    def identity_material(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "version": self.version,
            "general_key": self.general_key,
            "seat_assignment": self.seat_assignment.value,
            "seed": self.seed,
            "observed_event_ids": list(self.observed_event_ids),
            "discovery_artifact_sha256": self.discovery_artifact_sha256,
            "discovery_witness_identities": list(
                self.discovery_witness_identities
            ),
            "discovery_is_formal_evidence": self.discovery_is_formal_evidence,
            "provisional_pending_audit": self.provisional_pending_audit,
        }

    def compute_identity(self) -> str:
        return _identity(self.identity_material())

    @classmethod
    def from_dict(cls, value: object) -> "BridgeSentinelObservationV1":
        data = _exact_dict(value, "Bridge-H sentinel observation")
        _exact_fields(
            data, _SENTINEL_OBSERVATION_FIELDS, "Bridge-H sentinel observation"
        )
        try:
            seat = FixedAssignment(
                _text(data["seat_assignment"], "seat_assignment")
            )
        except ValueError as exc:
            raise BridgeAcceptanceContractError("未知observation seat") from exc
        return cls(
            schema=_text(data["schema"], "observation schema"),
            version=_integer(
                data["version"], "observation version", minimum=1
            ),
            general_key=_text(data["general_key"], "general_key"),
            seat_assignment=seat,
            seed=_integer(data["seed"], "seed"),
            observed_event_ids=_text_tuple_from_json(
                data["observed_event_ids"], "observed_event_ids"
            ),
            discovery_artifact_sha256=_sha256(
                data["discovery_artifact_sha256"],
                "discovery_artifact_sha256",
            ),
            discovery_witness_identities=_text_tuple_from_json(
                data["discovery_witness_identities"],
                "discovery_witness_identities",
            ),
            discovery_is_formal_evidence=_boolean(
                data["discovery_is_formal_evidence"],
                "discovery_is_formal_evidence",
            ),
            observation_identity=_sha256(
                data["observation_identity"], "observation_identity"
            ),
            provisional_pending_audit=_text(
                data["provisional_pending_audit"], "provisional_pending_audit"
            ),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            **self.identity_material(),
            "observation_identity": self.observation_identity,
        }


@dataclass(frozen=True, slots=True)
class BridgeSentinelCandidateV1:
    schema: str
    version: int
    candidate_id: str
    general_key: str
    seat_assignment: FixedAssignment
    seed: int
    closes_event_ids: tuple[str, ...]
    discovery_artifact_sha256: str
    discovery_witness_identities: tuple[str, ...]
    discovery_is_formal_evidence: bool
    candidate_identity: str
    provisional_pending_audit: str

    def __post_init__(self) -> None:
        _schema_version(
            self.schema,
            self.version,
            BRIDGE_SENTINEL_CANDIDATE_SCHEMA_V1,
            "Bridge-H sentinel candidate",
        )
        if self.general_key not in GENERAL_ALLOWLIST:
            raise BridgeAcceptanceContractError("sentinel General不在allowlist")
        if type(self.seat_assignment) is not FixedAssignment:
            raise BridgeAcceptanceContractError("sentinel seat类型不匹配")
        _integer(self.seed, "sentinel seed")
        _text_tuple(
            self.closes_event_ids,
            "closes_event_ids",
            allow_empty=False,
        )
        SENTINEL_POLICY.validate_candidate(
            general_key=self.general_key,
            seat_assignment=self.seat_assignment,
            seed=self.seed,
            closes_event_ids=self.closes_event_ids,
        )
        if any(
            _EVENT_GENERAL_BY_ID[event_id] != self.general_key
            for event_id in self.closes_event_ids
        ):
            raise BridgeAcceptanceContractError(
                "sentinel candidate不得关闭其他General的required event"
            )
        expected_id = canonical_sentinel_candidate_id_v1(
            self.general_key, self.seat_assignment, self.seed
        )
        if self.candidate_id != expected_id:
            raise BridgeAcceptanceContractError("sentinel candidate_id不匹配")
        _sha256(self.discovery_artifact_sha256, "discovery_artifact_sha256")
        _text_tuple(
            self.discovery_witness_identities,
            "discovery_witness_identities",
            allow_empty=False,
        )
        for value in self.discovery_witness_identities:
            _sha256(value, "discovery_witness_identity")
        if len(self.closes_event_ids) != len(self.discovery_witness_identities):
            raise BridgeAcceptanceContractError(
                "sentinel关闭event与discovery witness数量不一致"
            )
        if _boolean(
            self.discovery_is_formal_evidence,
            "discovery_is_formal_evidence",
        ) is not False:
            raise BridgeAcceptanceContractError("sentinel discovery不是formal evidence")
        _sha256(self.candidate_identity, "candidate_identity")
        if self.candidate_identity != self.compute_identity():
            raise BridgeAcceptanceIdentityError("candidate_identity不匹配")
        _provisional(self.provisional_pending_audit)

    def identity_material(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "version": self.version,
            "candidate_id": self.candidate_id,
            "general_key": self.general_key,
            "seat_assignment": self.seat_assignment.value,
            "seed": self.seed,
            "closes_event_ids": list(self.closes_event_ids),
            "discovery_artifact_sha256": self.discovery_artifact_sha256,
            "discovery_witness_identities": list(
                self.discovery_witness_identities
            ),
            "discovery_is_formal_evidence": self.discovery_is_formal_evidence,
            "provisional_pending_audit": self.provisional_pending_audit,
        }

    def compute_identity(self) -> str:
        return _identity(self.identity_material())

    @classmethod
    def from_dict(cls, value: object) -> "BridgeSentinelCandidateV1":
        data = _exact_dict(value, "Bridge-H sentinel candidate")
        _exact_fields(
            data, _SENTINEL_CANDIDATE_FIELDS, "Bridge-H sentinel candidate"
        )
        try:
            seat = FixedAssignment(
                _text(data["seat_assignment"], "seat_assignment")
            )
        except ValueError as exc:
            raise BridgeAcceptanceContractError("未知sentinel seat") from exc
        return cls(
            schema=_text(data["schema"], "sentinel candidate schema"),
            version=_integer(
                data["version"], "sentinel candidate version", minimum=1
            ),
            candidate_id=_text(data["candidate_id"], "candidate_id"),
            general_key=_text(data["general_key"], "general_key"),
            seat_assignment=seat,
            seed=_integer(data["seed"], "seed"),
            closes_event_ids=_text_tuple_from_json(
                data["closes_event_ids"],
                "closes_event_ids",
                allow_empty=False,
            ),
            discovery_artifact_sha256=_sha256(
                data["discovery_artifact_sha256"],
                "discovery_artifact_sha256",
            ),
            discovery_witness_identities=_text_tuple_from_json(
                data["discovery_witness_identities"],
                "discovery_witness_identities",
                allow_empty=False,
            ),
            discovery_is_formal_evidence=_boolean(
                data["discovery_is_formal_evidence"],
                "discovery_is_formal_evidence",
            ),
            candidate_identity=_sha256(
                data["candidate_identity"], "candidate_identity"
            ),
            provisional_pending_audit=_text(
                data["provisional_pending_audit"], "provisional_pending_audit"
            ),
        )

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_material(), "candidate_identity": self.candidate_identity}


def canonical_sentinel_candidate_id_v1(
    general_key: str, seat_assignment: FixedAssignment, seed: int
) -> str:
    seat = "P1" if seat_assignment is FixedAssignment.GENERAL_AS_P1 else "P2"
    return f"SENTINEL-{general_key.upper()}-{seat}-SEED-{seed}"


@dataclass(frozen=True, slots=True)
class BridgeSentinelRegistryV1:
    schema: str
    version: int
    authority: BridgeAcceptanceAuthorityV1
    baseline_event_ids: tuple[str, ...]
    selected_candidates: tuple[BridgeSentinelCandidateV1, ...]
    remaining_event_ids: tuple[str, ...]
    discovery_status: BridgeSentinelDiscoveryStatusV1
    discovery_is_formal_evidence: bool
    registry_identity: str
    provisional_pending_audit: str

    def __post_init__(self) -> None:
        _schema_version(
            self.schema,
            self.version,
            BRIDGE_SENTINEL_REGISTRY_SCHEMA_V1,
            "Bridge-H sentinel registry",
        )
        if type(self.authority) is not BridgeAcceptanceAuthorityV1:
            raise BridgeAcceptanceContractError("sentinel registry authority类型不匹配")
        _text_tuple(self.baseline_event_ids, "baseline_event_ids")
        if any(item not in BRIDGE_REQUIRED_EVENT_IDS_V1 for item in self.baseline_event_ids):
            raise BridgeAcceptanceContractError("baseline_event_ids包含未知event")
        if type(self.selected_candidates) is not tuple or any(
            type(item) is not BridgeSentinelCandidateV1
            for item in self.selected_candidates
        ):
            raise BridgeAcceptanceContractError("selected_candidates类型不匹配")
        candidate_ids = tuple(item.candidate_id for item in self.selected_candidates)
        if len(candidate_ids) != len(set(candidate_ids)):
            raise BridgeAcceptanceContractError("selected sentinel不得重复")
        _text_tuple(self.remaining_event_ids, "remaining_event_ids")
        if any(item not in BRIDGE_REQUIRED_EVENT_IDS_V1 for item in self.remaining_event_ids):
            raise BridgeAcceptanceContractError("remaining_event_ids包含未知event")
        if type(self.discovery_status) is not BridgeSentinelDiscoveryStatusV1:
            raise BridgeAcceptanceContractError("discovery_status类型不匹配")
        if _boolean(
            self.discovery_is_formal_evidence,
            "discovery_is_formal_evidence",
        ) is not False:
            raise BridgeAcceptanceContractError("sentinel discovery不是formal evidence")
        _sha256(self.registry_identity, "sentinel registry_identity")
        if self.registry_identity != self.compute_identity():
            raise BridgeAcceptanceIdentityError("sentinel registry_identity不匹配")
        _provisional(self.provisional_pending_audit)

    def identity_material(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "version": self.version,
            "authority": self.authority.to_dict(),
            "baseline_event_ids": list(self.baseline_event_ids),
            "selected_candidates": [
                item.to_dict() for item in self.selected_candidates
            ],
            "remaining_event_ids": list(self.remaining_event_ids),
            "discovery_status": self.discovery_status.value,
            "discovery_is_formal_evidence": self.discovery_is_formal_evidence,
            "provisional_pending_audit": self.provisional_pending_audit,
        }

    def compute_identity(self) -> str:
        return _identity(self.identity_material())

    @classmethod
    def from_dict(cls, value: object) -> "BridgeSentinelRegistryV1":
        data = _exact_dict(value, "Bridge-H sentinel registry")
        _exact_fields(
            data, _SENTINEL_REGISTRY_FIELDS, "Bridge-H sentinel registry"
        )
        try:
            status = BridgeSentinelDiscoveryStatusV1(
                _text(data["discovery_status"], "discovery_status")
            )
        except ValueError as exc:
            raise BridgeAcceptanceContractError("未知discovery_status") from exc
        candidates = _json_list(data["selected_candidates"], "selected_candidates")
        return cls(
            schema=_text(data["schema"], "sentinel registry schema"),
            version=_integer(
                data["version"], "sentinel registry version", minimum=1
            ),
            authority=BridgeAcceptanceAuthorityV1.from_dict(data["authority"]),
            baseline_event_ids=_text_tuple_from_json(
                data["baseline_event_ids"], "baseline_event_ids"
            ),
            selected_candidates=tuple(
                BridgeSentinelCandidateV1.from_dict(item) for item in candidates
            ),
            remaining_event_ids=_text_tuple_from_json(
                data["remaining_event_ids"], "remaining_event_ids"
            ),
            discovery_status=status,
            discovery_is_formal_evidence=_boolean(
                data["discovery_is_formal_evidence"],
                "discovery_is_formal_evidence",
            ),
            registry_identity=_sha256(
                data["registry_identity"], "registry_identity"
            ),
            provisional_pending_audit=_text(
                data["provisional_pending_audit"], "provisional_pending_audit"
            ),
        )

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_material(), "registry_identity": self.registry_identity}


@dataclass(frozen=True, slots=True)
class BridgeAcceptanceMatrixV1:
    schema: str
    version: int
    authority: BridgeAcceptanceAuthorityV1
    ordered_registry_identity: str
    ordered_cell_ids: tuple[str, ...]
    cells: tuple[BridgeAcceptanceCellV1, ...]
    sentinel_registry: BridgeSentinelRegistryV1
    matrix_identity: str
    provisional_pending_audit: str

    def __post_init__(self) -> None:
        _schema_version(
            self.schema,
            self.version,
            BRIDGE_ACCEPTANCE_MATRIX_SCHEMA_V1,
            "Bridge-H matrix",
        )
        if type(self.authority) is not BridgeAcceptanceAuthorityV1:
            raise BridgeAcceptanceContractError("matrix authority类型不匹配")
        _sha256(self.ordered_registry_identity, "ordered_registry_identity")
        _text_tuple(self.ordered_cell_ids, "ordered_cell_ids")
        if type(self.cells) is not tuple or any(
            type(item) is not BridgeAcceptanceCellV1 for item in self.cells
        ):
            raise BridgeAcceptanceContractError("matrix cells类型不匹配")
        if type(self.sentinel_registry) is not BridgeSentinelRegistryV1:
            raise BridgeAcceptanceContractError("sentinel_registry类型不匹配")
        if self.authority != self.sentinel_registry.authority:
            raise BridgeAcceptanceIdentityError("matrix与sentinel authority不一致")
        if any(item.authority != self.authority for item in self.cells):
            raise BridgeAcceptanceIdentityError("matrix cell authority不一致")
        _sha256(self.matrix_identity, "matrix_identity")
        if self.matrix_identity != self.compute_identity():
            raise BridgeAcceptanceIdentityError("matrix_identity不匹配")
        _provisional(self.provisional_pending_audit)

    def identity_material(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "version": self.version,
            "authority": self.authority.to_dict(),
            "ordered_registry_identity": self.ordered_registry_identity,
            "ordered_cell_ids": list(self.ordered_cell_ids),
            "cells": [item.to_dict() for item in self.cells],
            "sentinel_registry": self.sentinel_registry.to_dict(),
            "provisional_pending_audit": self.provisional_pending_audit,
        }

    def compute_identity(self) -> str:
        return _identity(self.identity_material())

    @classmethod
    def from_dict(cls, value: object) -> "BridgeAcceptanceMatrixV1":
        data = _exact_dict(value, "Bridge-H matrix")
        _exact_fields(data, _MATRIX_FIELDS, "Bridge-H matrix")
        cells = _json_list(data["cells"], "matrix cells")
        return cls(
            schema=_text(data["schema"], "matrix schema"),
            version=_integer(data["version"], "matrix version", minimum=1),
            authority=BridgeAcceptanceAuthorityV1.from_dict(data["authority"]),
            ordered_registry_identity=_sha256(
                data["ordered_registry_identity"], "ordered_registry_identity"
            ),
            ordered_cell_ids=_text_tuple_from_json(
                data["ordered_cell_ids"], "ordered_cell_ids"
            ),
            cells=tuple(BridgeAcceptanceCellV1.from_dict(item) for item in cells),
            sentinel_registry=BridgeSentinelRegistryV1.from_dict(
                data["sentinel_registry"]
            ),
            matrix_identity=_sha256(data["matrix_identity"], "matrix_identity"),
            provisional_pending_audit=_text(
                data["provisional_pending_audit"], "provisional_pending_audit"
            ),
        )

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_material(), "matrix_identity": self.matrix_identity}


@dataclass(frozen=True, slots=True)
class BridgeAcceptanceArtifactV1:
    schema: str
    version: int
    cell_id: str
    artifact_path: str
    artifact_sha256: str
    replay_identity: str
    cell_identity: str
    artifact_identity: str
    provisional_pending_audit: str

    def __post_init__(self) -> None:
        _schema_version(
            self.schema,
            self.version,
            BRIDGE_ACCEPTANCE_ARTIFACT_SCHEMA_V1,
            "Bridge-H artifact",
        )
        _text(self.cell_id, "artifact cell_id")
        _text(self.artifact_path, "artifact_path")
        for field in (
            "artifact_sha256",
            "replay_identity",
            "cell_identity",
            "artifact_identity",
        ):
            _sha256(getattr(self, field), field)
        if self.artifact_identity != self.compute_identity():
            raise BridgeAcceptanceIdentityError("artifact_identity不匹配")
        _provisional(self.provisional_pending_audit)

    def identity_material(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "version": self.version,
            "cell_id": self.cell_id,
            "artifact_path": self.artifact_path,
            "artifact_sha256": self.artifact_sha256,
            "replay_identity": self.replay_identity,
            "cell_identity": self.cell_identity,
            "provisional_pending_audit": self.provisional_pending_audit,
        }

    def compute_identity(self) -> str:
        return _identity(self.identity_material())

    @classmethod
    def from_dict(cls, value: object) -> "BridgeAcceptanceArtifactV1":
        data = _exact_dict(value, "Bridge-H artifact")
        _exact_fields(data, _ARTIFACT_FIELDS, "Bridge-H artifact")
        return cls(
            schema=_text(data["schema"], "artifact schema"),
            version=_integer(data["version"], "artifact version", minimum=1),
            cell_id=_text(data["cell_id"], "cell_id"),
            artifact_path=_text(data["artifact_path"], "artifact_path"),
            artifact_sha256=_sha256(data["artifact_sha256"], "artifact_sha256"),
            replay_identity=_sha256(data["replay_identity"], "replay_identity"),
            cell_identity=_sha256(data["cell_identity"], "cell_identity"),
            artifact_identity=_sha256(
                data["artifact_identity"], "artifact_identity"
            ),
            provisional_pending_audit=_text(
                data["provisional_pending_audit"], "provisional_pending_audit"
            ),
        )

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_material(), "artifact_identity": self.artifact_identity}


class BridgeAcceptanceRunModeV1(str, Enum):
    DISCOVERY = "discovery"
    FORMAL = "formal"


@dataclass(frozen=True, slots=True)
class BridgeAcceptanceProgressV1:
    schema: str
    version: int
    authority: BridgeAcceptanceAuthorityV1
    mode: BridgeAcceptanceRunModeV1
    ordered_registry_identity: str
    sentinel_registry_identity: str
    ordered_expected_cell_ids: tuple[str, ...]
    completed_cell_ids: tuple[str, ...]
    failed_cell_ids: tuple[str, ...]
    artifacts: tuple[BridgeAcceptanceArtifactV1, ...]
    final_artifact_exists: bool
    progress_identity: str
    provisional_pending_audit: str

    def __post_init__(self) -> None:
        _schema_version(
            self.schema,
            self.version,
            BRIDGE_ACCEPTANCE_PROGRESS_SCHEMA_V1,
            "Bridge-H progress",
        )
        if type(self.authority) is not BridgeAcceptanceAuthorityV1:
            raise BridgeAcceptanceContractError("progress authority类型不匹配")
        if type(self.mode) is not BridgeAcceptanceRunModeV1:
            raise BridgeAcceptanceContractError("progress mode类型不匹配")
        _sha256(self.ordered_registry_identity, "ordered_registry_identity")
        _sha256(self.sentinel_registry_identity, "sentinel_registry_identity")
        _text_tuple(self.ordered_expected_cell_ids, "ordered_expected_cell_ids")
        _text_tuple(self.completed_cell_ids, "completed_cell_ids")
        _text_tuple(self.failed_cell_ids, "failed_cell_ids")
        if type(self.artifacts) is not tuple or any(
            type(item) is not BridgeAcceptanceArtifactV1 for item in self.artifacts
        ):
            raise BridgeAcceptanceContractError("progress artifacts类型不匹配")
        if len(self.completed_cell_ids) != len(self.artifacts):
            raise BridgeAcceptanceContractError("completed cells与artifacts数量不一致")
        if tuple(item.cell_id for item in self.artifacts) != self.completed_cell_ids:
            raise BridgeAcceptanceContractError("artifact顺序与completed prefix不一致")
        if set(self.completed_cell_ids) & set(self.failed_cell_ids):
            raise BridgeAcceptanceContractError("cell不得同时completed和failed")
        _boolean(self.final_artifact_exists, "final_artifact_exists")
        _sha256(self.progress_identity, "progress_identity")
        if self.progress_identity != self.compute_identity():
            raise BridgeAcceptanceIdentityError("progress_identity不匹配")
        _provisional(self.provisional_pending_audit)

    def identity_material(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "version": self.version,
            "authority": self.authority.to_dict(),
            "mode": self.mode.value,
            "ordered_registry_identity": self.ordered_registry_identity,
            "sentinel_registry_identity": self.sentinel_registry_identity,
            "ordered_expected_cell_ids": list(self.ordered_expected_cell_ids),
            "completed_cell_ids": list(self.completed_cell_ids),
            "failed_cell_ids": list(self.failed_cell_ids),
            "artifacts": [item.to_dict() for item in self.artifacts],
            "final_artifact_exists": self.final_artifact_exists,
            "provisional_pending_audit": self.provisional_pending_audit,
        }

    def compute_identity(self) -> str:
        return _identity(self.identity_material())

    @classmethod
    def from_dict(cls, value: object) -> "BridgeAcceptanceProgressV1":
        data = _exact_dict(value, "Bridge-H progress")
        _exact_fields(data, _PROGRESS_FIELDS, "Bridge-H progress")
        try:
            mode = BridgeAcceptanceRunModeV1(_text(data["mode"], "mode"))
        except ValueError as exc:
            raise BridgeAcceptanceContractError("未知Bridge-H runner mode") from exc
        artifacts = _json_list(data["artifacts"], "artifacts")
        return cls(
            schema=_text(data["schema"], "progress schema"),
            version=_integer(data["version"], "progress version", minimum=1),
            authority=BridgeAcceptanceAuthorityV1.from_dict(data["authority"]),
            mode=mode,
            ordered_registry_identity=_sha256(
                data["ordered_registry_identity"], "ordered_registry_identity"
            ),
            sentinel_registry_identity=_sha256(
                data["sentinel_registry_identity"],
                "sentinel_registry_identity",
            ),
            ordered_expected_cell_ids=_text_tuple_from_json(
                data["ordered_expected_cell_ids"],
                "ordered_expected_cell_ids",
            ),
            completed_cell_ids=_text_tuple_from_json(
                data["completed_cell_ids"], "completed_cell_ids"
            ),
            failed_cell_ids=_text_tuple_from_json(
                data["failed_cell_ids"], "failed_cell_ids"
            ),
            artifacts=tuple(
                BridgeAcceptanceArtifactV1.from_dict(item) for item in artifacts
            ),
            final_artifact_exists=_boolean(
                data["final_artifact_exists"], "final_artifact_exists"
            ),
            progress_identity=_sha256(
                data["progress_identity"], "progress_identity"
            ),
            provisional_pending_audit=_text(
                data["provisional_pending_audit"], "provisional_pending_audit"
            ),
        )

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_material(), "progress_identity": self.progress_identity}


@dataclass(frozen=True, slots=True)
class BridgeAcceptanceResultV1:
    schema: str
    version: int
    authority: BridgeAcceptanceAuthorityV1
    matrix_identity: str
    aggregate_proof_flags: Mapping[str, bool]
    required_event_coverage: tuple[BridgeRequiredEventCoverageV1, ...]
    missing_required_event_ids: tuple[str, ...]
    result_identity: str
    provisional_pending_audit: str

    def __post_init__(self) -> None:
        _schema_version(
            self.schema,
            self.version,
            BRIDGE_ACCEPTANCE_RESULT_SCHEMA_V1,
            "Bridge-H result",
        )
        if type(self.authority) is not BridgeAcceptanceAuthorityV1:
            raise BridgeAcceptanceContractError("result authority类型不匹配")
        _sha256(self.matrix_identity, "matrix_identity")
        if not isinstance(self.aggregate_proof_flags, Mapping):
            raise BridgeAcceptanceContractError("aggregate_proof_flags类型不匹配")
        _exact_fields(
            self.aggregate_proof_flags,
            frozenset(BRIDGE_ACCEPTANCE_PROOF_FLAG_NAMES_V1),
            "aggregate_proof_flags",
        )
        for name in BRIDGE_ACCEPTANCE_PROOF_FLAG_NAMES_V1:
            _boolean(self.aggregate_proof_flags[name], name)
        if type(self.required_event_coverage) is not tuple or any(
            type(item) is not BridgeRequiredEventCoverageV1
            for item in self.required_event_coverage
        ):
            raise BridgeAcceptanceContractError("required_event_coverage类型不匹配")
        if tuple(item.event_id for item in self.required_event_coverage) != (
            BRIDGE_REQUIRED_EVENT_IDS_V1
        ):
            raise BridgeAcceptanceContractError("required event coverage顺序/全集不匹配")
        _text_tuple(self.missing_required_event_ids, "missing_required_event_ids")
        expected_missing = tuple(
            item.event_id for item in self.required_event_coverage if not item.covered
        )
        if self.missing_required_event_ids != expected_missing:
            raise BridgeAcceptanceContractError(
                "missing_required_event_ids必须由coverage重新派生"
            )
        _sha256(self.result_identity, "result_identity")
        if self.result_identity != self.compute_identity():
            raise BridgeAcceptanceIdentityError("result_identity不匹配")
        _provisional(self.provisional_pending_audit)

    @property
    def all_required_events_covered(self) -> bool:
        return not self.missing_required_event_ids

    @property
    def all_cell_proofs_proven(self) -> bool:
        return all(self.aggregate_proof_flags.values())

    def identity_material(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "version": self.version,
            "authority": self.authority.to_dict(),
            "matrix_identity": self.matrix_identity,
            "aggregate_proof_flags": dict(self.aggregate_proof_flags),
            "required_event_coverage": [
                item.to_dict() for item in self.required_event_coverage
            ],
            "missing_required_event_ids": list(self.missing_required_event_ids),
            "provisional_pending_audit": self.provisional_pending_audit,
        }

    def compute_identity(self) -> str:
        return _identity(self.identity_material())

    @classmethod
    def from_dict(cls, value: object) -> "BridgeAcceptanceResultV1":
        data = _exact_dict(value, "Bridge-H result")
        _exact_fields(data, _RESULT_FIELDS, "Bridge-H result")
        flags = _exact_dict(
            data["aggregate_proof_flags"], "aggregate_proof_flags"
        )
        _exact_fields(
            flags,
            frozenset(BRIDGE_ACCEPTANCE_PROOF_FLAG_NAMES_V1),
            "aggregate_proof_flags",
        )
        coverage = _json_list(
            data["required_event_coverage"], "required_event_coverage"
        )
        return cls(
            schema=_text(data["schema"], "result schema"),
            version=_integer(data["version"], "result version", minimum=1),
            authority=BridgeAcceptanceAuthorityV1.from_dict(data["authority"]),
            matrix_identity=_sha256(data["matrix_identity"], "matrix_identity"),
            aggregate_proof_flags=MappingProxyType(
                {
                    name: _boolean(flags[name], f"aggregate.{name}")
                    for name in BRIDGE_ACCEPTANCE_PROOF_FLAG_NAMES_V1
                }
            ),
            required_event_coverage=tuple(
                BridgeRequiredEventCoverageV1.from_dict(item) for item in coverage
            ),
            missing_required_event_ids=_text_tuple_from_json(
                data["missing_required_event_ids"],
                "missing_required_event_ids",
            ),
            result_identity=_sha256(data["result_identity"], "result_identity"),
            provisional_pending_audit=_text(
                data["provisional_pending_audit"], "provisional_pending_audit"
            ),
        )

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_material(), "result_identity": self.result_identity}


def create_bridge_required_event_witness_v1(
    *,
    event_id: str,
    cell_id: str,
    source_kind: str,
    source_index: int,
    source_witness_identity: str,
    source_replay_identity: str,
) -> BridgeRequiredEventWitnessV1:
    """Create a normalized witness binding from already-derived replay evidence."""

    if event_id not in BRIDGE_REQUIRED_EVENT_IDS_V1:
        raise BridgeAcceptanceContractError("未知required event")
    material = {
        "schema": BRIDGE_REQUIRED_EVENT_WITNESS_SCHEMA_V1,
        "version": BRIDGE_H_CONTRACT_VERSION,
        "event_id": event_id,
        "general_key": _EVENT_GENERAL_BY_ID[event_id],
        "cell_id": cell_id,
        "source_kind": source_kind,
        "source_index": source_index,
        "source_witness_identity": source_witness_identity,
        "source_replay_identity": source_replay_identity,
        "provisional_pending_audit": PROVISIONAL_PENDING_AUDIT,
    }
    return BridgeRequiredEventWitnessV1(
        schema=BRIDGE_REQUIRED_EVENT_WITNESS_SCHEMA_V1,
        version=BRIDGE_H_CONTRACT_VERSION,
        event_id=event_id,
        general_key=_EVENT_GENERAL_BY_ID[event_id],
        cell_id=cell_id,
        source_kind=source_kind,
        source_index=source_index,
        source_witness_identity=source_witness_identity,
        source_replay_identity=source_replay_identity,
        witness_binding_identity=_identity(material),
        provisional_pending_audit=PROVISIONAL_PENDING_AUDIT,
    )


def create_bridge_baseline_acceptance_cell_v1(
    *,
    registry_cell: BridgeAcceptanceRegistryCellV1,
    replay_artifact_path: str,
    replay_artifact_sha256: str,
    records_identity: str,
    execution_identity: str,
    replay_identity: str,
    proof: BridgeAcceptanceCellProofV1,
    required_event_witnesses: tuple[BridgeRequiredEventWitnessV1, ...],
) -> BridgeAcceptanceCellV1:
    """Build one baseline cell without accepting caller-supplied registry facts."""

    if type(registry_cell) is not BridgeAcceptanceRegistryCellV1:
        raise BridgeAcceptanceContractError("registry_cell类型不匹配")
    authority = BridgeAcceptanceAuthorityV1.current()
    material = {
        "schema": BRIDGE_ACCEPTANCE_CELL_SCHEMA_V1,
        "version": BRIDGE_H_CONTRACT_VERSION,
        "authority": authority.to_dict(),
        "cell_kind": BridgeCellKindV1.BASELINE.value,
        "cell_id": registry_cell.cell_id,
        "general_key": registry_cell.general_key,
        "seat_assignment": registry_cell.seat_assignment.value,
        "general_player_id": registry_cell.general_player_id,
        "no_skill_player_id": registry_cell.no_skill_player_id,
        "seed": registry_cell.seed,
        "registry_cell_identity": registry_cell.registry_cell_identity,
        "replay_artifact_path": replay_artifact_path,
        "replay_artifact_sha256": replay_artifact_sha256,
        "records_identity": records_identity,
        "execution_identity": execution_identity,
        "replay_identity": replay_identity,
        "proof": proof.to_dict(),
        "required_event_witnesses": [
            item.to_dict() for item in required_event_witnesses
        ],
        "provisional_pending_audit": PROVISIONAL_PENDING_AUDIT,
    }
    return BridgeAcceptanceCellV1(
        schema=BRIDGE_ACCEPTANCE_CELL_SCHEMA_V1,
        version=BRIDGE_H_CONTRACT_VERSION,
        authority=authority,
        cell_kind=BridgeCellKindV1.BASELINE,
        cell_id=registry_cell.cell_id,
        general_key=registry_cell.general_key,
        seat_assignment=registry_cell.seat_assignment,
        general_player_id=registry_cell.general_player_id,
        no_skill_player_id=registry_cell.no_skill_player_id,
        seed=registry_cell.seed,
        registry_cell_identity=registry_cell.registry_cell_identity,
        replay_artifact_path=replay_artifact_path,
        replay_artifact_sha256=replay_artifact_sha256,
        records_identity=records_identity,
        execution_identity=execution_identity,
        replay_identity=replay_identity,
        proof=proof,
        required_event_witnesses=required_event_witnesses,
        cell_identity=_identity(material),
        provisional_pending_audit=PROVISIONAL_PENDING_AUDIT,
    )


def create_bridge_sentinel_acceptance_cell_v1(
    *,
    candidate: BridgeSentinelCandidateV1,
    replay_artifact_path: str,
    replay_artifact_sha256: str,
    records_identity: str,
    execution_identity: str,
    replay_identity: str,
    proof: BridgeAcceptanceCellProofV1,
    required_event_witnesses: tuple[BridgeRequiredEventWitnessV1, ...],
) -> BridgeAcceptanceCellV1:
    """Build one formal sentinel cell from the frozen H4 candidate authority.

    Discovery evidence is intentionally not reused as formal proof.  The caller
    must supply a fresh natural-full-game proof and fresh normalized witnesses.
    """

    if type(candidate) is not BridgeSentinelCandidateV1:
        raise BridgeAcceptanceContractError("sentinel candidate类型不匹配")
    authority = BridgeAcceptanceAuthorityV1.current()
    general_player_id = (
        "p1"
        if candidate.seat_assignment is FixedAssignment.GENERAL_AS_P1
        else "p2"
    )
    no_skill_player_id = "p2" if general_player_id == "p1" else "p1"
    material = {
        "schema": BRIDGE_ACCEPTANCE_CELL_SCHEMA_V1,
        "version": BRIDGE_H_CONTRACT_VERSION,
        "authority": authority.to_dict(),
        "cell_kind": BridgeCellKindV1.SENTINEL.value,
        "cell_id": candidate.candidate_id,
        "general_key": candidate.general_key,
        "seat_assignment": candidate.seat_assignment.value,
        "general_player_id": general_player_id,
        "no_skill_player_id": no_skill_player_id,
        "seed": candidate.seed,
        "registry_cell_identity": candidate.candidate_identity,
        "replay_artifact_path": replay_artifact_path,
        "replay_artifact_sha256": replay_artifact_sha256,
        "records_identity": records_identity,
        "execution_identity": execution_identity,
        "replay_identity": replay_identity,
        "proof": proof.to_dict(),
        "required_event_witnesses": [
            item.to_dict() for item in required_event_witnesses
        ],
        "provisional_pending_audit": PROVISIONAL_PENDING_AUDIT,
    }
    return BridgeAcceptanceCellV1(
        schema=BRIDGE_ACCEPTANCE_CELL_SCHEMA_V1,
        version=BRIDGE_H_CONTRACT_VERSION,
        authority=authority,
        cell_kind=BridgeCellKindV1.SENTINEL,
        cell_id=candidate.candidate_id,
        general_key=candidate.general_key,
        seat_assignment=candidate.seat_assignment,
        general_player_id=general_player_id,
        no_skill_player_id=no_skill_player_id,
        seed=candidate.seed,
        registry_cell_identity=candidate.candidate_identity,
        replay_artifact_path=replay_artifact_path,
        replay_artifact_sha256=replay_artifact_sha256,
        records_identity=records_identity,
        execution_identity=execution_identity,
        replay_identity=replay_identity,
        proof=proof,
        required_event_witnesses=required_event_witnesses,
        cell_identity=_identity(material),
        provisional_pending_audit=PROVISIONAL_PENDING_AUDIT,
    )


def create_bridge_sentinel_registry_record_v1(
    *,
    authority: BridgeAcceptanceAuthorityV1,
    baseline_event_ids: tuple[str, ...],
    selected_candidates: tuple[BridgeSentinelCandidateV1, ...],
    remaining_event_ids: tuple[str, ...],
    discovery_status: BridgeSentinelDiscoveryStatusV1,
) -> BridgeSentinelRegistryV1:
    """Create a hashed registry record; H4 supplies the selection authority."""

    material = {
        "schema": BRIDGE_SENTINEL_REGISTRY_SCHEMA_V1,
        "version": BRIDGE_H_CONTRACT_VERSION,
        "authority": authority.to_dict(),
        "baseline_event_ids": list(baseline_event_ids),
        "selected_candidates": [item.to_dict() for item in selected_candidates],
        "remaining_event_ids": list(remaining_event_ids),
        "discovery_status": discovery_status.value,
        "discovery_is_formal_evidence": False,
        "provisional_pending_audit": PROVISIONAL_PENDING_AUDIT,
    }
    return BridgeSentinelRegistryV1(
        schema=BRIDGE_SENTINEL_REGISTRY_SCHEMA_V1,
        version=BRIDGE_H_CONTRACT_VERSION,
        authority=authority,
        baseline_event_ids=baseline_event_ids,
        selected_candidates=selected_candidates,
        remaining_event_ids=remaining_event_ids,
        discovery_status=discovery_status,
        discovery_is_formal_evidence=False,
        registry_identity=_identity(material),
        provisional_pending_audit=PROVISIONAL_PENDING_AUDIT,
    )


def canonical_bridge_sentinel_search_keys_v1(
) -> tuple[tuple[str, FixedAssignment, int], ...]:
    """Return the exact General -> seat -> ascending seed search order."""

    if SENTINEL_POLICY.general_order != GENERAL_ALLOWLIST:
        raise BridgeAcceptanceIdentityError("sentinel General order authority漂移")
    expected_seats = (
        FixedAssignment.GENERAL_AS_P1,
        FixedAssignment.GENERAL_AS_P2,
    )
    if SENTINEL_POLICY.seat_order != expected_seats:
        raise BridgeAcceptanceIdentityError("sentinel seat order authority漂移")
    if (
        SENTINEL_POLICY.seed_min,
        SENTINEL_POLICY.seed_max,
        SENTINEL_POLICY.excluded_seeds,
        SENTINEL_POLICY.seed_order,
    ) != (0, 99, (0, 1, 49), "ascending"):
        raise BridgeAcceptanceIdentityError("sentinel seed search authority漂移")
    return tuple(
        (general_key, seat, seed)
        for general_key in SENTINEL_POLICY.general_order
        for seat in SENTINEL_POLICY.seat_order
        for seed in range(
            SENTINEL_POLICY.seed_min, SENTINEL_POLICY.seed_max + 1
        )
        if seed not in SENTINEL_POLICY.excluded_seeds
    )


def create_bridge_sentinel_observation_v1(
    *,
    general_key: str,
    seat_assignment: FixedAssignment,
    seed: int,
    observed_event_ids: tuple[str, ...],
    discovery_artifact_sha256: str,
    discovery_witness_identities: tuple[str, ...],
) -> BridgeSentinelObservationV1:
    material = {
        "schema": BRIDGE_SENTINEL_OBSERVATION_SCHEMA_V1,
        "version": BRIDGE_H_CONTRACT_VERSION,
        "general_key": general_key,
        "seat_assignment": seat_assignment.value,
        "seed": seed,
        "observed_event_ids": list(observed_event_ids),
        "discovery_artifact_sha256": discovery_artifact_sha256,
        "discovery_witness_identities": list(discovery_witness_identities),
        "discovery_is_formal_evidence": False,
        "provisional_pending_audit": PROVISIONAL_PENDING_AUDIT,
    }
    return BridgeSentinelObservationV1(
        schema=BRIDGE_SENTINEL_OBSERVATION_SCHEMA_V1,
        version=BRIDGE_H_CONTRACT_VERSION,
        general_key=general_key,
        seat_assignment=seat_assignment,
        seed=seed,
        observed_event_ids=observed_event_ids,
        discovery_artifact_sha256=discovery_artifact_sha256,
        discovery_witness_identities=discovery_witness_identities,
        discovery_is_formal_evidence=False,
        observation_identity=_identity(material),
        provisional_pending_audit=PROVISIONAL_PENDING_AUDIT,
    )


def _create_sentinel_candidate_from_observation_v1(
    observation: BridgeSentinelObservationV1,
    closes_event_ids: tuple[str, ...],
) -> BridgeSentinelCandidateV1:
    witness_by_event = dict(
        zip(
            observation.observed_event_ids,
            observation.discovery_witness_identities,
            strict=True,
        )
    )
    witness_identities = tuple(witness_by_event[item] for item in closes_event_ids)
    candidate_id = canonical_sentinel_candidate_id_v1(
        observation.general_key, observation.seat_assignment, observation.seed
    )
    material = {
        "schema": BRIDGE_SENTINEL_CANDIDATE_SCHEMA_V1,
        "version": BRIDGE_H_CONTRACT_VERSION,
        "candidate_id": candidate_id,
        "general_key": observation.general_key,
        "seat_assignment": observation.seat_assignment.value,
        "seed": observation.seed,
        "closes_event_ids": list(closes_event_ids),
        "discovery_artifact_sha256": observation.discovery_artifact_sha256,
        "discovery_witness_identities": list(witness_identities),
        "discovery_is_formal_evidence": False,
        "provisional_pending_audit": PROVISIONAL_PENDING_AUDIT,
    }
    return BridgeSentinelCandidateV1(
        schema=BRIDGE_SENTINEL_CANDIDATE_SCHEMA_V1,
        version=BRIDGE_H_CONTRACT_VERSION,
        candidate_id=candidate_id,
        general_key=observation.general_key,
        seat_assignment=observation.seat_assignment,
        seed=observation.seed,
        closes_event_ids=closes_event_ids,
        discovery_artifact_sha256=observation.discovery_artifact_sha256,
        discovery_witness_identities=witness_identities,
        discovery_is_formal_evidence=False,
        candidate_identity=_identity(material),
        provisional_pending_audit=PROVISIONAL_PENDING_AUDIT,
    )


def _inclusion_minimal_observations_v1(
    selected: Sequence[BridgeSentinelObservationV1],
    baseline_event_ids: tuple[str, ...],
) -> tuple[BridgeSentinelObservationV1, ...]:
    retained = list(selected)
    baseline = set(baseline_event_ids)
    observed_goal: set[str] = set()
    for item in retained:
        observed_goal.update(item.observed_event_ids)
    observed_goal -= baseline
    changed = True
    while changed:
        changed = False
        for index in range(len(retained)):
            without = set(baseline)
            for other_index, item in enumerate(retained):
                if other_index != index:
                    without.update(item.observed_event_ids)
            if observed_goal <= without:
                retained.pop(index)
                changed = True
                break
    return tuple(retained)


def select_bridge_sentinel_registry_v1(
    *,
    baseline_event_ids: tuple[str, ...],
    observations: tuple[BridgeSentinelObservationV1, ...],
) -> BridgeSentinelRegistryV1:
    """Pure deterministic selection; this function never executes discovery."""

    _text_tuple(baseline_event_ids, "baseline_event_ids")
    if baseline_event_ids != _ordered_event_ids(set(baseline_event_ids)):
        raise BridgeAcceptanceContractError("baseline event union顺序必须canonical")
    if type(observations) is not tuple or any(
        type(item) is not BridgeSentinelObservationV1 for item in observations
    ):
        raise BridgeAcceptanceContractError("observations必须是exact observation tuple")
    authority = BridgeAcceptanceAuthorityV1.current()
    uncovered = set(BRIDGE_REQUIRED_EVENT_IDS_V1) - set(baseline_event_ids)
    if not uncovered:
        if observations:
            raise BridgeAcceptanceContractError(
                "baseline union complete时不得执行或提供sentinel discovery"
            )
        return create_bridge_sentinel_registry_record_v1(
            authority=authority,
            baseline_event_ids=baseline_event_ids,
            selected_candidates=(),
            remaining_event_ids=(),
            discovery_status=BridgeSentinelDiscoveryStatusV1.NOT_REQUIRED,
        )

    search_keys = canonical_bridge_sentinel_search_keys_v1()
    if len(observations) > len(search_keys):
        raise BridgeAcceptanceContractError("sentinel observations超过0..99搜索空间")
    selected_observations: list[BridgeSentinelObservationV1] = []
    closed_at: int | None = None
    for index, observation in enumerate(observations):
        if observation.search_key != search_keys[index]:
            raise BridgeAcceptanceContractError(
                "sentinel observation不是strict continuous canonical search prefix"
            )
        closes = set(observation.observed_event_ids) & uncovered
        if closes:
            selected_observations.append(observation)
            uncovered -= closes
        if not uncovered:
            closed_at = index
            break

    if closed_at is not None:
        if closed_at != len(observations) - 1:
            raise BridgeAcceptanceContractError(
                "required event全部关闭后必须立即停止，禁止trailing discovery"
            )
        status = BridgeSentinelDiscoveryStatusV1.SELECTED
    elif len(observations) != len(search_keys):
        raise BridgeAcceptanceContractError(
            "sentinel observation prefix未关闭全部event且尚未耗尽0..99"
        )
    else:
        status = BridgeSentinelDiscoveryStatusV1.SENTINEL_DISCOVERY_BLOCKED

    minimal = _inclusion_minimal_observations_v1(
        selected_observations, baseline_event_ids
    )
    rebuilt_uncovered = set(BRIDGE_REQUIRED_EVENT_IDS_V1) - set(
        baseline_event_ids
    )
    candidates: list[BridgeSentinelCandidateV1] = []
    for observation in minimal:
        closes = _ordered_event_ids(
            set(observation.observed_event_ids) & rebuilt_uncovered
        )
        if not closes:
            raise BridgeAcceptanceContractError(
                "inclusion-minimal sentinel必须关闭至少一个当前uncovered event"
            )
        candidates.append(
            _create_sentinel_candidate_from_observation_v1(observation, closes)
        )
        rebuilt_uncovered -= set(closes)
    if status is BridgeSentinelDiscoveryStatusV1.SELECTED and rebuilt_uncovered:
        raise BridgeAcceptanceContractError("sentinel minimalization错误地重新打开event gap")
    remaining = _ordered_event_ids(rebuilt_uncovered)
    return create_bridge_sentinel_registry_record_v1(
        authority=authority,
        baseline_event_ids=baseline_event_ids,
        selected_candidates=tuple(candidates),
        remaining_event_ids=remaining,
        discovery_status=status,
    )


def validate_bridge_sentinel_selection_v1(
    registry_value: object,
    *,
    observations: tuple[BridgeSentinelObservationV1, ...],
) -> BridgeSentinelRegistryV1:
    registry = (
        registry_value
        if type(registry_value) is BridgeSentinelRegistryV1
        else BridgeSentinelRegistryV1.from_dict(registry_value)
    )
    expected = select_bridge_sentinel_registry_v1(
        baseline_event_ids=registry.baseline_event_ids,
        observations=observations,
    )
    if registry != expected:
        raise BridgeAcceptanceContractError(
            "sentinel registry与deterministic inclusion-minimal selection不一致"
        )
    return registry


def bridge_acceptance_ordered_registry_identity_v1(
    registry: BridgeAcceptanceRegistryV1,
    sentinel_registry: BridgeSentinelRegistryV1,
) -> str:
    if type(registry) is not BridgeAcceptanceRegistryV1:
        raise BridgeAcceptanceContractError("acceptance registry类型不匹配")
    if type(sentinel_registry) is not BridgeSentinelRegistryV1:
        raise BridgeAcceptanceContractError("sentinel registry类型不匹配")
    ordered_ids = registry.ordered_cell_ids + tuple(
        item.candidate_id for item in sentinel_registry.selected_candidates
    )
    return _identity(
        {
            "baseline_acceptance_registry_identity": registry.registry_identity,
            "sentinel_registry_identity": sentinel_registry.registry_identity,
            "ordered_cell_ids": list(ordered_ids),
        }
    )


def _ordered_event_ids(values: set[str]) -> tuple[str, ...]:
    return tuple(
        event_id for event_id in BRIDGE_REQUIRED_EVENT_IDS_V1 if event_id in values
    )


def _validate_sentinel_registry_against_cells_v1(
    sentinel_registry: BridgeSentinelRegistryV1,
    baseline_cells: tuple[BridgeAcceptanceCellV1, ...],
    sentinel_cells: tuple[BridgeAcceptanceCellV1, ...],
) -> None:
    baseline_union: set[str] = set()
    for cell in baseline_cells:
        baseline_union.update(cell.observed_required_event_ids)
    if sentinel_registry.baseline_event_ids != _ordered_event_ids(baseline_union):
        raise BridgeAcceptanceContractError(
            "sentinel registry baseline event union必须由baseline cells重新派生"
        )

    if len(sentinel_registry.selected_candidates) != len(sentinel_cells):
        raise BridgeAcceptanceContractError(
            "selected sentinel candidates与formal sentinel cells数量不一致"
        )
    covered = set(baseline_union)
    for candidate, cell in zip(
        sentinel_registry.selected_candidates, sentinel_cells, strict=True
    ):
        if cell.cell_kind is not BridgeCellKindV1.SENTINEL:
            raise BridgeAcceptanceContractError("sentinel registry指向非sentinel cell")
        expected = (
            candidate.candidate_id,
            candidate.general_key,
            candidate.seat_assignment,
            candidate.seed,
            candidate.candidate_identity,
        )
        actual = (
            cell.cell_id,
            cell.general_key,
            cell.seat_assignment,
            cell.seed,
            cell.registry_cell_identity,
        )
        if actual != expected:
            raise BridgeAcceptanceContractError(
                "sentinel cell与selected candidate authority不一致"
            )
        newly_observed = set(cell.observed_required_event_ids) - covered
        claimed = set(candidate.closes_event_ids)
        if not newly_observed or claimed != newly_observed:
            raise BridgeAcceptanceContractError(
                "sentinel candidate closes_event_ids必须精确由当前uncovered witness派生"
            )
        covered.update(newly_observed)

    sentinel_observed_goal: set[str] = set()
    for cell in sentinel_cells:
        sentinel_observed_goal.update(cell.observed_required_event_ids)
    sentinel_observed_goal -= baseline_union
    for index in range(len(sentinel_cells)):
        without = set(baseline_union)
        for other_index, cell in enumerate(sentinel_cells):
            if other_index != index:
                without.update(cell.observed_required_event_ids)
        if sentinel_observed_goal <= without:
            raise BridgeAcceptanceContractError(
                "formal sentinel set不是inclusion-minimal"
            )

    remaining = set(BRIDGE_REQUIRED_EVENT_IDS_V1) - covered
    if sentinel_registry.remaining_event_ids != _ordered_event_ids(remaining):
        raise BridgeAcceptanceContractError(
            "sentinel remaining_event_ids必须由cell witness union重新派生"
        )
    if not sentinel_registry.selected_candidates and not remaining:
        expected_status = BridgeSentinelDiscoveryStatusV1.NOT_REQUIRED
    elif not sentinel_registry.selected_candidates:
        expected_status = (
            BridgeSentinelDiscoveryStatusV1.SENTINEL_DISCOVERY_BLOCKED
            if sentinel_registry.discovery_status
            is BridgeSentinelDiscoveryStatusV1.SENTINEL_DISCOVERY_BLOCKED
            else BridgeSentinelDiscoveryStatusV1.NOT_RUN
        )
    elif remaining:
        expected_status = BridgeSentinelDiscoveryStatusV1.SENTINEL_DISCOVERY_BLOCKED
    else:
        expected_status = BridgeSentinelDiscoveryStatusV1.SELECTED
    if sentinel_registry.discovery_status is not expected_status:
        raise BridgeAcceptanceContractError(
            "sentinel discovery_status不能替代rederived event union"
        )


def validate_bridge_acceptance_matrix_v1(
    value: object,
) -> BridgeAcceptanceMatrixV1:
    """Purely validate registry, cell, sentinel, and witness composition."""

    matrix = (
        value
        if type(value) is BridgeAcceptanceMatrixV1
        else BridgeAcceptanceMatrixV1.from_dict(value)
    )
    registry = bridge_acceptance_baseline_registry_v1()
    if matrix.authority != registry.authority:
        raise BridgeAcceptanceIdentityError(
            "matrix authority与current acceptance registry不一致"
        )
    baseline_count = len(registry.cells)
    expected_ids = registry.ordered_cell_ids + tuple(
        item.candidate_id for item in matrix.sentinel_registry.selected_candidates
    )
    if matrix.ordered_cell_ids != expected_ids:
        raise BridgeAcceptanceContractError(
            "matrix ordered_cell_ids必须精确等于BASELINE_18+selected sentinels"
        )
    if tuple(item.cell_id for item in matrix.cells) != expected_ids:
        raise BridgeAcceptanceContractError("matrix cell顺序/缺失/重复不合法")
    baseline_cells = matrix.cells[:baseline_count]
    sentinel_cells = matrix.cells[baseline_count:]
    for expected, cell in zip(registry.cells, baseline_cells, strict=True):
        if cell.cell_kind is not BridgeCellKindV1.BASELINE:
            raise BridgeAcceptanceContractError("BASELINE_18 row被标为非baseline")
        actual = (
            cell.cell_id,
            cell.general_key,
            cell.seat_assignment,
            cell.general_player_id,
            cell.no_skill_player_id,
            cell.seed,
            cell.registry_cell_identity,
        )
        canonical = (
            expected.cell_id,
            expected.general_key,
            expected.seat_assignment,
            expected.general_player_id,
            expected.no_skill_player_id,
            expected.seed,
            expected.registry_cell_identity,
        )
        if actual != canonical:
            raise BridgeAcceptanceContractError(
                "matrix baseline cell与canonical registry不一致"
            )
    _validate_sentinel_registry_against_cells_v1(
        matrix.sentinel_registry, baseline_cells, sentinel_cells
    )
    expected_registry_identity = bridge_acceptance_ordered_registry_identity_v1(
        registry, matrix.sentinel_registry
    )
    if matrix.ordered_registry_identity != expected_registry_identity:
        raise BridgeAcceptanceIdentityError("matrix ordered registry identity不匹配")
    return matrix


def create_bridge_acceptance_matrix_v1(
    *,
    cells: tuple[BridgeAcceptanceCellV1, ...],
    sentinel_registry: BridgeSentinelRegistryV1,
) -> BridgeAcceptanceMatrixV1:
    registry = bridge_acceptance_baseline_registry_v1()
    ordered_ids = registry.ordered_cell_ids + tuple(
        item.candidate_id for item in sentinel_registry.selected_candidates
    )
    ordered_registry_identity = bridge_acceptance_ordered_registry_identity_v1(
        registry, sentinel_registry
    )
    material = {
        "schema": BRIDGE_ACCEPTANCE_MATRIX_SCHEMA_V1,
        "version": BRIDGE_H_CONTRACT_VERSION,
        "authority": registry.authority.to_dict(),
        "ordered_registry_identity": ordered_registry_identity,
        "ordered_cell_ids": list(ordered_ids),
        "cells": [item.to_dict() for item in cells],
        "sentinel_registry": sentinel_registry.to_dict(),
        "provisional_pending_audit": PROVISIONAL_PENDING_AUDIT,
    }
    matrix = BridgeAcceptanceMatrixV1(
        schema=BRIDGE_ACCEPTANCE_MATRIX_SCHEMA_V1,
        version=BRIDGE_H_CONTRACT_VERSION,
        authority=registry.authority,
        ordered_registry_identity=ordered_registry_identity,
        ordered_cell_ids=ordered_ids,
        cells=cells,
        sentinel_registry=sentinel_registry,
        matrix_identity=_identity(material),
        provisional_pending_audit=PROVISIONAL_PENDING_AUDIT,
    )
    return validate_bridge_acceptance_matrix_v1(matrix)


def _derive_required_event_coverage_v1(
    cells: Sequence[BridgeAcceptanceCellV1],
) -> tuple[BridgeRequiredEventCoverageV1, ...]:
    coverage: list[BridgeRequiredEventCoverageV1] = []
    for event_id in BRIDGE_REQUIRED_EVENT_IDS_V1:
        witness_cells: list[str] = []
        witness_bindings: list[str] = []
        for cell in cells:
            witnesses = tuple(
                item
                for item in cell.required_event_witnesses
                if item.event_id == event_id
            )
            if not witnesses:
                continue
            witness_cells.append(cell.cell_id)
            witness_bindings.append(witnesses[0].witness_binding_identity)
        material = {
            "schema": BRIDGE_REQUIRED_EVENT_COVERAGE_SCHEMA_V1,
            "version": BRIDGE_H_CONTRACT_VERSION,
            "event_id": event_id,
            "general_key": _EVENT_GENERAL_BY_ID[event_id],
            "witness_cell_ids": witness_cells,
            "witness_binding_identities": witness_bindings,
            "provisional_pending_audit": PROVISIONAL_PENDING_AUDIT,
        }
        coverage.append(
            BridgeRequiredEventCoverageV1(
                schema=BRIDGE_REQUIRED_EVENT_COVERAGE_SCHEMA_V1,
                version=BRIDGE_H_CONTRACT_VERSION,
                event_id=event_id,
                general_key=_EVENT_GENERAL_BY_ID[event_id],
                witness_cell_ids=tuple(witness_cells),
                witness_binding_identities=tuple(witness_bindings),
                coverage_identity=_identity(material),
                provisional_pending_audit=PROVISIONAL_PENDING_AUDIT,
            )
        )
    return tuple(coverage)


def derive_bridge_acceptance_result_v1(value: object) -> BridgeAcceptanceResultV1:
    """Re-derive every aggregate bit and event union from validated cells."""

    matrix = validate_bridge_acceptance_matrix_v1(value)
    aggregate = MappingProxyType(
        {
            name: bool(matrix.cells)
            and all(cell.proof_flags[name] is True for cell in matrix.cells)
            for name in BRIDGE_ACCEPTANCE_PROOF_FLAG_NAMES_V1
        }
    )
    coverage = _derive_required_event_coverage_v1(matrix.cells)
    missing = tuple(item.event_id for item in coverage if not item.covered)
    material = {
        "schema": BRIDGE_ACCEPTANCE_RESULT_SCHEMA_V1,
        "version": BRIDGE_H_CONTRACT_VERSION,
        "authority": matrix.authority.to_dict(),
        "matrix_identity": matrix.matrix_identity,
        "aggregate_proof_flags": dict(aggregate),
        "required_event_coverage": [item.to_dict() for item in coverage],
        "missing_required_event_ids": list(missing),
        "provisional_pending_audit": PROVISIONAL_PENDING_AUDIT,
    }
    return BridgeAcceptanceResultV1(
        schema=BRIDGE_ACCEPTANCE_RESULT_SCHEMA_V1,
        version=BRIDGE_H_CONTRACT_VERSION,
        authority=matrix.authority,
        matrix_identity=matrix.matrix_identity,
        aggregate_proof_flags=aggregate,
        required_event_coverage=coverage,
        missing_required_event_ids=missing,
        result_identity=_identity(material),
        provisional_pending_audit=PROVISIONAL_PENDING_AUDIT,
    )


def validate_bridge_acceptance_result_v1(
    matrix_value: object, result_value: object
) -> BridgeAcceptanceResultV1:
    """Reject cached aggregate or event-union forgery against the source matrix."""

    expected = derive_bridge_acceptance_result_v1(matrix_value)
    actual = (
        result_value
        if type(result_value) is BridgeAcceptanceResultV1
        else BridgeAcceptanceResultV1.from_dict(result_value)
    )
    if actual != expected:
        raise BridgeAcceptanceContractError(
            "Bridge-H result必须从cell proofs与witness union重新派生"
        )
    return actual


def assert_bridge_acceptance_aggregate_complete_v1(result_value: object) -> None:
    """Fail closed on any missing cell proof or event; this does not close audit debt."""

    result = (
        result_value
        if type(result_value) is BridgeAcceptanceResultV1
        else BridgeAcceptanceResultV1.from_dict(result_value)
    )
    missing_flags = tuple(
        name
        for name in BRIDGE_ACCEPTANCE_PROOF_FLAG_NAMES_V1
        if result.aggregate_proof_flags[name] is not True
    )
    if missing_flags or result.missing_required_event_ids:
        raise BridgeAcceptanceContractError(
            "Bridge-H aggregate criteria未满足；"
            f"missing_flags={missing_flags}, "
            f"missing_events={result.missing_required_event_ids}"
        )


__all__ = [
    "BRIDGE_ACCEPTANCE_ARTIFACT_SCHEMA_V1",
    "BRIDGE_ACCEPTANCE_AUTHORITY_SCHEMA_V1",
    "BRIDGE_ACCEPTANCE_CELL_PROOF_SCHEMA_V1",
    "BRIDGE_ACCEPTANCE_CELL_SCHEMA_V1",
    "BRIDGE_ACCEPTANCE_MATRIX_SCHEMA_V1",
    "BRIDGE_ACCEPTANCE_PROGRESS_SCHEMA_V1",
    "BRIDGE_ACCEPTANCE_PROOF_FLAG_NAMES_V1",
    "BRIDGE_ACCEPTANCE_REGISTRY_CELL_SCHEMA_V1",
    "BRIDGE_ACCEPTANCE_REGISTRY_SCHEMA_V1",
    "BRIDGE_ACCEPTANCE_RESULT_SCHEMA_V1",
    "BRIDGE_H_CONTRACT_ID",
    "BRIDGE_H_CONTRACT_IDENTITY_V1",
    "BRIDGE_H_CONTRACT_VERSION",
    "BRIDGE_REQUIRED_EVENT_COVERAGE_SCHEMA_V1",
    "BRIDGE_REQUIRED_EVENT_IDS_V1",
    "BRIDGE_REQUIRED_EVENT_WITNESS_SCHEMA_V1",
    "BRIDGE_SENTINEL_CANDIDATE_SCHEMA_V1",
    "BRIDGE_SENTINEL_OBSERVATION_SCHEMA_V1",
    "BRIDGE_SENTINEL_REGISTRY_SCHEMA_V1",
    "PROVISIONAL_PENDING_AUDIT",
    "BridgeAcceptanceArtifactV1",
    "BridgeAcceptanceAuthorityV1",
    "BridgeAcceptanceCellProofV1",
    "BridgeAcceptanceCellV1",
    "BridgeAcceptanceContractError",
    "BridgeAcceptanceIdentityError",
    "BridgeAcceptanceMatrixV1",
    "BridgeAcceptanceProgressV1",
    "BridgeAcceptanceRegistryCellV1",
    "BridgeAcceptanceRegistryV1",
    "BridgeAcceptanceResultV1",
    "BridgeAcceptanceRunModeV1",
    "BridgeCellKindV1",
    "BridgeRequiredEventCoverageV1",
    "BridgeRequiredEventWitnessV1",
    "BridgeSentinelCandidateV1",
    "BridgeSentinelDiscoveryStatusV1",
    "BridgeSentinelObservationV1",
    "BridgeSentinelRegistryV1",
    "bridge_h_contract_descriptor_v1",
    "bridge_acceptance_baseline_registry_v1",
    "bridge_acceptance_ordered_registry_identity_v1",
    "canonical_sentinel_candidate_id_v1",
    "canonical_bridge_sentinel_search_keys_v1",
    "create_bridge_acceptance_matrix_v1",
    "create_bridge_baseline_acceptance_cell_v1",
    "create_bridge_sentinel_acceptance_cell_v1",
    "create_bridge_required_event_witness_v1",
    "create_bridge_sentinel_registry_record_v1",
    "create_bridge_sentinel_observation_v1",
    "derive_bridge_acceptance_result_v1",
    "validate_bridge_acceptance_matrix_v1",
    "validate_bridge_acceptance_result_v1",
    "select_bridge_sentinel_registry_v1",
    "validate_bridge_sentinel_selection_v1",
    "assert_bridge_acceptance_aggregate_complete_v1",
]
