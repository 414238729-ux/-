# -*- coding: utf-8 -*-
"""C8-G1 independent timed 8p full-game replay schema skeleton.

The parser and semantic preflight are implemented here.  Full production
reexecution is intentionally absent until G3.  Parsing an envelope therefore
never proves replay execution, even when every stored claim is internally
consistent.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import json
import math
from pathlib import Path
from types import MappingProxyType
from typing import Any, ClassVar, Final, Mapping, Protocol, Sequence

from . import c8_bounded_timed_8p_trace_v1 as c8f
from . import c8_c6_production_adapter_v1 as c8e
from . import c8_strict_replay_v1 as c8d
from . import c8_timed_session_runtime_v1 as c8b
from . import c8_timeout_controller_integration_v1 as c8c
from . import c8_virtual_time_contract_v1 as c8a
from . import c8_timed_8p_full_game_contract_v1 as contract
from .authoritative_no_skill_full_game import (
    AUTHORITATIVE_NO_SKILL_FULL_GAME_V1_CONTRACT_ID,
    canonical_no_skill_mode_v1,
)
from .formal_duel import deck_identity


class C8G1ReplayError(ValueError):
    """Base error for structural or semantic replay rejection."""


class C8G1ReplayIdentityError(C8G1ReplayError):
    """The artifact is not bound to current A--G1 identities."""


class C8G1ReplaySemanticError(C8G1ReplayError):
    """Structurally valid evidence contradicts the frozen semantics."""


class C8G1ReplayExecutionNotProven(C8G1ReplayError):
    """G1 has no full-game fresh reexecution implementation."""


C8_G1_REPLAY_ID: Final[str] = "c8-timed-8p-full-game-replay-v4"
C8_G1_REPLAY_SCHEMA: Final[str] = contract.C8_G1_REPLAY_SCHEMA
C8_G1_REPLAY_VERSION: Final[int] = 4
C8_G1_REPLAY_TRACE_SCOPE: Final[str] = "FULL_GAME_REAL_PRODUCTION_TRACE"
C8_G1_REPLAY_EXECUTION: Final[str] = "NOT_PROVEN"
C8_G1_FORMAL_MATRIX_CELL: Final[bool] = True
C8_G1_FULL_GAME: Final[bool] = True
C8_G1_INNER_BINDING_SCHEMA: Final[str] = "sgs-c8-g1-inner-c6-replay-binding-v4"
C8_G1_PRIVATE_SCHEMA: Final[str] = "sgs-c8-g1-authoritative-private-v4"
C8_G1_INITIAL_SCHEMA: Final[str] = "sgs-c8-g1-initial-production-material-v4"
C8_G1_STEP_SCHEMA: Final[str] = "sgs-c8-g1-production-step-evidence-v4"
C8_G1_WINDOW_SCHEMA: Final[str] = "sgs-c8-g1-timed-window-evidence-v4"
C8_G1_PUBLIC_PROJECTION_SCHEMA: Final[str] = (
    "sgs-c8-g1-full-game-public-projection-v4"
)
C8_G1_DEVELOPMENT_IDENTITY_SCHEMA: Final[str] = (
    "sgs-c8-g1-development-identity-v4"
)
C8_G1_CURRENT_IMPLEMENTATION_IDENTITY_SCHEMA: Final[str] = (
    "sgs-c8-g1-current-implementation-identity-v4"
)
C8_G1_PRIOR_REPLAY_CONTRACT_IDENTITY: Final[str] = (
    "99e153084cf6c48610e8e8d0e01dd97b5b4f58d6588c2ee9d0f75c89c95f29fb"
)
C8_G1_PRIOR_DEVELOPMENT_IDENTITY: Final[str] = (
    "f375f8f2d27a04181af96bee797d5123901d0f98cb8c77844663897d46992634"
)
C8_G1_PRIOR_CURRENT_IMPLEMENTATION_IDENTITY: Final[str] = (
    "cff46b0fff4382b8a5c1114594ae3d4926ccc77be9ed16779410c2c40b375a6e"
)
C8_G1_COLD_REPLAY_PIPELINE_V1: Final[tuple[str, ...]] = (
    "STRICT_DUPLICATE_AND_REQUIRED_KEY_PARSE",
    "FRESH_CANONICAL_C6_SESSION",
    "FRESH_A_B_C_E_RUNTIME_CONTROLLER_ADAPTER",
    "FRESH_PRODUCTION_AND_VIRTUAL_TIME_INPUT_REPLAY",
    "FRESH_LEGAL_SET_AND_SIGNED_ACTION_REGENERATION",
    "FRESH_C_RESULT_B_RECEIPT_E_ISSUANCE_REGENERATION",
    "FRESH_STATE_TERMINAL_REQUIRED_EVENT_REDERIVATION",
    "FIELDWISE_AND_IDENTITY_COMPARISON",
)
C8_G1_LIVE_CAPABILITIES_RECONSTRUCT_FRESH_V1: Final[tuple[str, ...]] = (
    "lease",
    "guard_token",
    "pending_capability",
    "transaction_token",
    "receipt_ownership",
    "callback_guard",
)

_SHA256_RE = contract._SHA256_RE
_ZERO_SHA256: Final[str] = "0" * 64
_TEXT_ID_RE = contract._TEXT_ID_RE

_SERIALIZED_LIVE_KEYS: Final[frozenset[str]] = frozenset(
    {
        "lease",
        "lease_token",
        "guard_token",
        "pending_capability",
        "transaction_token",
        "transaction_capability",
        "receipt_ownership",
        "callback_token",
        "callback_guard",
        "reservation",
        "runtime_object",
        "private_runtime_object",
    }
)
_PUBLIC_FORBIDDEN_KEYS: Final[frozenset[str]] = frozenset(
    {
        "card_instance_id",
        "virtual_materials",
        "private_choice_payload",
        "authorization_evidence",
        "raw_snapshot",
        "transaction_capability",
        "lease",
        "lease_token",
        "guard_token",
        "pending_capability",
        "transaction_token",
        "receipt_ownership",
        "private_runtime_object",
        "inner_replay_payload",
    }
)


def _canonical_bytes(value: object) -> bytes:
    return contract.canonical_json_bytes_v1(value)


def _identity(value: object) -> str:
    return contract.identity_v1(value)


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
        raise C8G1ReplayError(f"{label}必须是精确JSON object")
    if any(type(key) is not str for key in value):
        raise C8G1ReplayError(f"{label}字段名必须是精确字符串")
    return value


def _exact_list(value: object, label: str) -> list[Any]:
    if type(value) is not list:
        raise C8G1ReplayError(f"{label}必须是精确JSON array")
    return value


def _exact_keys(value: object, expected: frozenset[str], label: str) -> dict[str, Any]:
    data = _exact_dict(value, label)
    actual = frozenset(data)
    if actual != expected:
        raise C8G1ReplayError(
            f"{label}字段不匹配 missing={sorted(expected - actual)} "
            f"extra={sorted(actual - expected)}"
        )
    return data


def _text(value: object, label: str, *, allow_empty: bool = False) -> str:
    if type(value) is not str or (not allow_empty and not value):
        raise C8G1ReplayError(f"{label}必须是精确字符串")
    return value


def _text_id(value: object, label: str) -> str:
    result = _text(value, label)
    if _TEXT_ID_RE.fullmatch(result) is None:
        raise C8G1ReplayError(f"{label}不是canonical text id")
    return result


def _sha256(value: object, label: str, *, allow_zero: bool = False) -> str:
    result = _text(value, label)
    if _SHA256_RE.fullmatch(result) is None:
        raise C8G1ReplayError(f"{label}必须是canonical SHA-256")
    if not allow_zero and result == _ZERO_SHA256:
        raise C8G1ReplayError(f"{label}不得为全零SHA-256")
    return result


def _integer(value: object, label: str, *, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise C8G1ReplayError(f"{label}必须是精确int且 >= {minimum}")
    return value


def _boolean(value: object, label: str) -> bool:
    if type(value) is not bool:
        raise C8G1ReplayError(f"{label}必须是精确bool")
    return value


def _optional_text_id(value: object, label: str) -> str | None:
    if value is None:
        return None
    return _text_id(value, label)


def _optional_integer(value: object, label: str, *, minimum: int = 0) -> int | None:
    if value is None:
        return None
    return _integer(value, label, minimum=minimum)


def _optional_sha256(value: object, label: str) -> str | None:
    if value is None:
        return None
    return _sha256(value, label)


def _strict_json(raw: bytes | str) -> dict[str, Any]:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise C8G1ReplayError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    try:
        parsed = json.loads(raw, object_pairs_hook=reject_duplicates)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        if isinstance(exc, C8G1ReplayError):
            raise
        raise C8G1ReplayError("full-game replay不是strict JSON") from exc
    _validate_json_tree(parsed, "strict JSON")
    return _exact_dict(parsed, "full-game replay root")


def _validate_json_tree(value: object, label: str) -> None:
    if value is None or type(value) in (str, bool, int):
        return
    if type(value) is float:
        if not math.isfinite(value):
            raise C8G1ReplayError(f"{label}不得包含NaN/Infinity")
        return
    if type(value) is list:
        for index, item in enumerate(value):
            _validate_json_tree(item, f"{label}[{index}]")
        return
    if type(value) is dict:
        if any(type(key) is not str for key in value):
            raise C8G1ReplayError(f"{label}字段名必须是字符串")
        for key, item in value.items():
            _validate_json_tree(item, f"{label}.{key}")
        return
    raise C8G1ReplayError(f"{label}包含非JSON类型")


def _reject_forbidden_keys(value: object, forbidden: frozenset[str], label: str) -> None:
    if type(value) is dict:
        intersection = forbidden.intersection(key.lower() for key in value)
        if intersection:
            raise C8G1ReplayError(
                f"{label}包含禁止字段：{sorted(intersection)}"
            )
        for key, item in value.items():
            _reject_forbidden_keys(item, forbidden, f"{label}.{key}")
    elif type(value) is list:
        for index, item in enumerate(value):
            _reject_forbidden_keys(item, forbidden, f"{label}[{index}]")


_REPLAY_CONTRACT_DESCRIPTOR: Final[Mapping[str, object]] = MappingProxyType(
    {
        "schema": "sgs-c8-g1-full-game-replay-contract-v4",
        "contract_version": C8_G1_REPLAY_VERSION,
        "replay_id": C8_G1_REPLAY_ID,
        "replay_schema": C8_G1_REPLAY_SCHEMA,
        "inner_replay_schema": "sgs-production-basic-batch-reexecution-v1",
        "selection_evidence": "STRICT_ON_TIME_CONTINUED_OR_CLOSED_AND_TIMEOUT_RECEIPT_CLOSED",
        "state_revision_equals_step_count": False,
        "supersedes_v3_current_identity": "f1972a255be140ee2677638f5f1c3f21dc1e030d0149d5a7b5b960e95c4c5558",
        "composition": "FRESH_GROUPED_WINDOWS_FLAT_ACCEPTED_C6_ACTIONS_PUBLIC_INDUCTION_STATE_EVENT_RNG",
        "scope_marker": contract.C8_G1_SCOPE_MARKER,
        "trace_scope": C8_G1_REPLAY_TRACE_SCOPE,
        "full_game": True,
        "formal_matrix_cell": True,
        "base_full_game_contract_id": contract.C8_G1_BASE_FULL_GAME_CONTRACT_ID,
        "base_mode_id": contract.C8_G1_BASE_MODE_ID,
        "cold_replay_order": list(C8_G1_COLD_REPLAY_PIPELINE_V1),
        "live_capability_rule": (
            "LEASE_GUARD_PENDING_TRANSACTION_RECEIPT_AUTHORITY_FRESH_ONLY"
        ),
        "public_projection": "PUBLIC_MATERIAL_ONLY",
        "g1_execution_status": C8_G1_REPLAY_EXECUTION,
        "bounded_promotion": "FORBIDDEN",
        "serialized_replay_verified": "NO_AUTHORITY",
        "window_relation_schema": "sgs-c8-g1-window-relation-evidence-v3",
        "post_commit_order": (
            "STEP_COMMITTED_PARENT_CLOSED_POST_STEP_OBSERVED_FRESH_WINDOW_OPENED"
        ),
        "post_commit_active_parent_ref": None,
        "post_commit_parent_deadline_reuse": "FORBIDDEN",
        "timeout_ordinal_authority": (
            "C_RESOLVER_RESULT_B_RECEIPT_E_EVIDENCE_ONLY"
        ),
        "supersedes_replay_contract_identity": (
            C8_G1_PRIOR_REPLAY_CONTRACT_IDENTITY
        ),
    }
)
C8_G1_REPLAY_CONTRACT_IDENTITY: Final[str] = _identity(
    dict(_REPLAY_CONTRACT_DESCRIPTOR)
)


def replay_contract_descriptor_v1() -> dict[str, object]:
    return _plain(_REPLAY_CONTRACT_DESCRIPTOR)  # type: ignore[return-value]


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _file_sha256(path: Path) -> str:
    from . import c8_timed_replay_version_compatibility_v1 as compatibility
    producer_digest = compatibility.execution_source_digest_v1(path)
    if producer_digest is not None:
        return producer_digest
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(65536), b""):
            digest.update(block)
    return digest.hexdigest()


_G1_PATHS: Final[Mapping[str, str]] = MappingProxyType(
    {
        "contract_source": "scripts/sgs_engine/c8_timed_8p_full_game_contract_v1.py",
        "replay_source": "scripts/sgs_engine/c8_timed_8p_full_game_replay_v1.py",
        "contract_test": "tests/test_c8_timed_8p_full_game_contract_v1.py",
        "replay_test": "tests/test_c8_timed_8p_full_game_replay_v1.py",
    }
)


def current_c8_g1_development_snapshot_v1(
    repo_root: Path | str | None = None,
) -> dict[str, object]:
    root = _repo_root() if repo_root is None else Path(repo_root).resolve()
    prior = c8f.current_c8_f_development_snapshot_v1(root)
    hashes = {
        label: _file_sha256(root / relative)
        for label, relative in _G1_PATHS.items()
    }
    material = {
        "schema": C8_G1_DEVELOPMENT_IDENTITY_SCHEMA,
        "contract_version": C8_G1_REPLAY_VERSION,
        "contract_identity": contract.C8_G1_CONTRACT_IDENTITY,
        "replay_contract_identity": C8_G1_REPLAY_CONTRACT_IDENTITY,
        "source_test_sha256": hashes,
        "superseded_v2_identities": dict(contract.C8_G1_V2_PRIOR_IDENTITIES),
        "prior_current_c8_implementation_identity": prior[
            "current_c8_implementation_identity"
        ],
    }
    development_identity = _identity(material)
    current_material = {
        "schema": C8_G1_CURRENT_IMPLEMENTATION_IDENTITY_SCHEMA,
        "contract_version": C8_G1_REPLAY_VERSION,
        "prior_current_c8_implementation_identity": prior[
            "current_c8_implementation_identity"
        ],
        "c8_g1_contract_identity": contract.C8_G1_CONTRACT_IDENTITY,
        "c8_g1_replay_contract_identity": C8_G1_REPLAY_CONTRACT_IDENTITY,
        "c8_g1_development_identity": development_identity,
    }
    return {
        **material,
        "development_identity": development_identity,
        "current_c8_implementation_identity": _identity(current_material),
        "prior": prior,
    }


_BINDING_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "schema",
        "contract_version",
        "c8_a_contract_identity",
        "c8_a_development_identity",
        "c8_b_runtime_contract_identity",
        "c8_b_current_contract_latch_identity",
        "c8_b_development_identity",
        "c8_c_contract_identity",
        "c8_c_development_identity",
        "c8_d_contract_identity",
        "c8_d_current_implementation_identity",
        "c8_d_development_identity",
        "c8_e_adapter_id",
        "c8_e_contract_identity",
        "c8_e_development_identity",
        "c8_f_contract_identity",
        "c8_f_driver_policy_identity",
        "c8_f_development_identity",
        "prior_current_c8_implementation_identity",
        "c8_g1_contract_id",
        "c8_g1_contract_identity",
        "c8_g1_replay_id",
        "c8_g1_replay_contract_identity",
        "c8_g1_development_identity",
        "current_c8_implementation_identity",
        "base_full_game_contract_id",
        "base_mode_id",
        "mode_contract_id",
        "rules_profile_identity",
        "deck_identity",
        "timer_profile_id",
        "timer_profile_status",
        "driver_policy_id",
        "driver_policy_identity",
        "baseline_registry_identity",
        "registry_identity",
        "required_event_registry_identity",
    }
)


def current_binding_snapshot_v1(
    registry: contract.FullGameRegistryV1,
    repo_root: Path | str | None = None,
) -> dict[str, object]:
    if not isinstance(registry, contract.FullGameRegistryV1):
        raise C8G1ReplayError("binding snapshot必须使用FullGameRegistryV1")
    development = current_c8_g1_development_snapshot_v1(repo_root)
    prior = development["prior"]
    dependencies = prior["dependencies"]
    bindings = dependencies["contract_bindings"]
    mode = canonical_no_skill_mode_v1(contract.C8_G1_BASE_MODE_ID)
    return {
        "schema": "sgs-c8-g1-current-binding-snapshot-v3",
        "contract_version": C8_G1_REPLAY_VERSION,
        "c8_a_contract_identity": c8a.C8_A_CONTRACT_IDENTITY_V1,
        "c8_a_development_identity": c8d.C8_A_DEVELOPMENT_IDENTITY,
        "c8_b_runtime_contract_identity": c8b.C8_B_RUNTIME_CONTRACT_IDENTITY_V1,
        "c8_b_current_contract_latch_identity": (
            c8b.C8_B_CURRENT_CONTRACT_LATCH_V1.latch_identity
        ),
        "c8_b_development_identity": c8d.C8_B_DEVELOPMENT_IDENTITY,
        "c8_c_contract_identity": c8c.C8_C_CONTRACT_IDENTITY,
        "c8_c_development_identity": c8d.C8_C_DEVELOPMENT_IDENTITY,
        "c8_d_contract_identity": c8d.C8_D_CONTRACT_IDENTITY,
        "c8_d_current_implementation_identity": (
            c8d.C8_D_CURRENT_IMPLEMENTATION_IDENTITY
        ),
        "c8_d_development_identity": c8d.C8_D_DEVELOPMENT_IDENTITY,
        "c8_e_adapter_id": c8e.C8_E_ADAPTER_ID,
        "c8_e_contract_identity": c8e.C8_E_CONTRACT_IDENTITY,
        "c8_e_development_identity": bindings["c8_e_development_identity"],
        "c8_f_contract_identity": c8f.C8_F_CONTRACT_IDENTITY,
        "c8_f_driver_policy_identity": c8f.C8_F_DRIVER_POLICY_IDENTITY,
        "c8_f_development_identity": prior["development_identity"],
        "prior_current_c8_implementation_identity": prior[
            "current_c8_implementation_identity"
        ],
        "c8_g1_contract_id": contract.C8_G1_CONTRACT_ID,
        "c8_g1_contract_identity": contract.C8_G1_CONTRACT_IDENTITY,
        "c8_g1_replay_id": C8_G1_REPLAY_ID,
        "c8_g1_replay_contract_identity": C8_G1_REPLAY_CONTRACT_IDENTITY,
        "c8_g1_development_identity": development["development_identity"],
        "current_c8_implementation_identity": development[
            "current_c8_implementation_identity"
        ],
        "base_full_game_contract_id": AUTHORITATIVE_NO_SKILL_FULL_GAME_V1_CONTRACT_ID,
        "base_mode_id": contract.C8_G1_BASE_MODE_ID,
        "mode_contract_id": mode.mode_contract_id,
        "rules_profile_identity": mode.profile_identity(),
        "deck_identity": deck_identity(),
        "timer_profile_id": contract.C8_G1_TIMER_PROFILE_ID,
        "timer_profile_status": contract.C8_G1_TIMER_PROFILE_STATUS,
        "driver_policy_id": contract.C8_G1_DRIVER_POLICY_ID,
        "driver_policy_identity": contract.C8_G1_DRIVER_POLICY_IDENTITY,
        "baseline_registry_identity": contract.C8_G1_BASELINE_REGISTRY_IDENTITY,
        "registry_identity": registry.registry_identity,
        "required_event_registry_identity": (
            contract.REQUIRED_EVENT_REGISTRY_IDENTITY_V1
        ),
    }


def exact_equal_v3(recorded: object, fresh: object, label: str) -> None:
    """Compare canonical bytes, including exact bool/int domains; never normalize."""
    if _canonical_bytes(_plain(recorded)) != _canonical_bytes(_plain(fresh)):
        raise C8G1ReplaySemanticError(f"C8_G3_COMPOSITION_MISMATCH: {label}")


def _object(value: object, fields: str, label: str) -> dict[str, Any]:
    return _exact_keys(value, frozenset(fields.split()), label)


def _range(value: object, label: str) -> None:
    d = _object(value, "start end", label)
    if _integer(d["end"], label) < _integer(d["start"], label):
        raise C8G1ReplaySemanticError(f"{label}索引倒退")


ACTION_REF_FIELDS = "inner_decision_index signed_action_id_commitment ordered_legal_action_commitment executed_public_ordinal executed_public_action_family"
BINDING_FIELDS = """cell_execution_identity inner_decision_index step_index global_window_index
window_id window_authority_ref_identity production_context_identity turn_number turn_player_id
actor_id phase production_window_kind driver_window_kind pre_revision post_revision pre_step_count
post_step_count production_action_ref pre_public_state_identity post_public_state_identity
pre_execution_identity post_execution_identity pre_state_identity post_state_identity event_start
event_end rng_start rng_end inner_decision_identity opened_at deadline_at decision_tick
virtual_input_ref runtime_event_range controller_event_range window_disposition_ref relation_ref
window_step_index opening_production_context_identity"""


@dataclass(frozen=True, slots=True, repr=False)
class ProductionActionBindingV1:
    """Internal comparison data with an explicit public allowlist; no selection authority."""

    value: Mapping[str, object]

    def __post_init__(self) -> None:
        d = _object(_plain(self.value), BINDING_FIELDS, "production action binding")
        for key in ("inner_decision_index", "step_index", "global_window_index", "turn_number",
                    "pre_revision", "post_revision", "pre_step_count", "post_step_count",
                    "event_start", "event_end", "rng_start", "rng_end", "opened_at",
                    "deadline_at", "decision_tick", "window_step_index"):
            _integer(d[key], key)
        for key in ("cell_execution_identity", "window_authority_ref_identity", "production_context_identity",
                    "pre_public_state_identity", "post_public_state_identity", "pre_execution_identity",
                    "post_execution_identity", "pre_state_identity", "post_state_identity",
                    "inner_decision_identity", "virtual_input_ref", "window_disposition_ref", "relation_ref",
                    "opening_production_context_identity"):
            _sha256(d[key], key)
        for key in ("window_id", "turn_player_id", "actor_id", "phase", "production_window_kind", "driver_window_kind"):
            _text_id(d[key], key)
        i = d["inner_decision_index"]
        if (d["step_index"], d["pre_step_count"], d["post_step_count"]) != (i + 1, i, i + 1):
            raise C8G1ReplaySemanticError("inner index0/G step1换算或accepted step +1不成立")
        if d["global_window_index"] < 1 or d["turn_number"] < 1:
            raise C8G1ReplaySemanticError("window/turn必须从1开始")
        if d["post_revision"] < d["pre_revision"]:
            raise C8G1ReplaySemanticError("committed production revision不得倒退")
        if d["pre_execution_identity"] == d["post_execution_identity"]:
            raise C8G1ReplaySemanticError("accepted step缺少actual execution transition")
        for prefix in ("event", "rng"):
            if d[prefix+"_end"] < d[prefix+"_start"]:
                raise C8G1ReplaySemanticError("event/RNG索引倒退")
        if d["deadline_at"] - d["opened_at"] != contract.C8_G1_WINDOW_DURATION_TICKS:
            raise C8G1ReplaySemanticError("新窗口必须使用冻结duration，不复用closed parent时间")
        a = _object(d["production_action_ref"], ACTION_REF_FIELDS, "production action ref")
        for key in ("inner_decision_index", "executed_public_ordinal"):
            _integer(a[key], key)
        exact_equal_v3(a["inner_decision_index"], i, "action ref index")
        _text_id(a["executed_public_action_family"], "action family")
        _sha256(a["signed_action_id_commitment"], "signed action commitment")
        _sha256(a["ordered_legal_action_commitment"], "ordered legal commitment")
        _range(d["runtime_event_range"], "runtime event range")
        _range(d["controller_event_range"], "controller event range")
        object.__setattr__(self, "value", _freeze(d))

    @property
    def binding_identity(self) -> str:
        return _identity({"schema": "sgs-c8-g-production-action-binding-v1", **self.to_dict()})

    def to_dict(self) -> dict[str, object]:
        return _plain(self.value)

    @classmethod
    def from_dict(cls, value: object) -> "ProductionActionBindingV1":
        return cls(_exact_dict(value, "binding"))

    def public_projection(self) -> dict[str, object]:
        allowed = """cell_execution_identity inner_decision_index step_index global_window_index
        window_id window_authority_ref_identity production_context_identity turn_number turn_player_id
        actor_id phase production_window_kind driver_window_kind pre_revision post_revision
        pre_step_count post_step_count production_action_ref pre_public_state_identity post_public_state_identity
        opened_at deadline_at decision_tick virtual_input_ref runtime_event_range controller_event_range
        window_disposition_ref relation_ref window_step_index opening_production_context_identity""".split()
        d = self.to_dict()
        return {key: d[key] for key in allowed}


def driver_input_from_dict_v3(value: object) -> contract.FormalDriverInputV1:
    d = _object(value, "formal_seed global_window_index turn_number turn_player_id actor_id phase window_kind deadline_at timeout_applicability proposal_order_identity public_actions public_ordinal_progress", "driver input")
    return contract.FormalDriverInputV1(
        **{key: d[key] for key in ("formal_seed", "global_window_index", "turn_number", "turn_player_id", "actor_id", "phase", "deadline_at", "proposal_order_identity")},
        window_kind=contract.PublicWindowKindV1(d["window_kind"]),
        timeout_applicability=contract.TimeoutApplicabilityV1(d["timeout_applicability"]),
        public_actions=tuple(contract.PublicActionOptionV1.from_dict(a) for a in _exact_list(d["public_actions"], "public_actions")),
        public_ordinal_progress=None if d["public_ordinal_progress"] is None else contract.PublicOrdinalProgressV1.from_dict(d["public_ordinal_progress"]))


def driver_decision_dict_v3(value: contract.FormalDriverInputV1) -> dict[str, object]:
    decision = contract.choose_formal_driver_action_v1(value)
    return {key: (getattr(decision, key).value if key == "marker" else getattr(decision, key))
            for key in decision.__dataclass_fields__}


def validate_public_legal_v3(value: object, input_value: contract.FormalDriverInputV1,
                             binding: Mapping[str, object]) -> None:
    d = _object(value, "actions proposal_order_identity legal_set_commitment", "fresh public legal set")
    actions = _exact_list(d["actions"], "actions")
    if len(actions) != len(input_value.public_actions):
        raise C8G1ReplaySemanticError("fresh legal tuple与public ordinals不是一一对应")
    for i, action in enumerate(actions):
        a = _object(action, "public_ordinal public_action_family signed_action_id_commitment", "public action")
        _integer(a["public_ordinal"], "ordinal")
        exact_equal_v3({key: a[key] for key in ("public_ordinal", "public_action_family")},
                       input_value.public_actions[i].to_dict(), "fresh canonical ordinal")
        _sha256(a["signed_action_id_commitment"], "signed action commitment")
    exact_equal_v3(d["proposal_order_identity"], input_value.proposal_order_identity, "public ordering")
    exact_equal_v3(d["legal_set_commitment"], _identity(actions), "public legal commitment")
    ref = binding["production_action_ref"]
    ordinal = ref["executed_public_ordinal"]
    if ordinal >= len(actions):
        raise C8G1ReplaySemanticError("executed ordinal越界")
    exact_equal_v3(actions[ordinal]["signed_action_id_commitment"], ref["signed_action_id_commitment"], "selected action commitment")
    exact_equal_v3(actions[ordinal]["public_action_family"], ref["executed_public_action_family"], "selected family")


ON_TIME_SCHEMA = "sgs-c8-g-on-time-production-decision-evidence-v2"
TIMEOUT_SCHEMA = "sgs-c8-g-timeout-production-decision-evidence-v2"
ON_TIME_KIND = "ON_TIME_PRODUCTION_DECISION"
TIMEOUT_KIND = "TIMEOUT_PRODUCTION_DECISION"
ON_TIME_FIELDS = "schema kind binding fresh_public_legal_set driver_input driver_decision normal_forward completion liveness evidence_identity"
TIMEOUT_FIELDS = "schema kind binding timeout_schedule_decision timeout_due_commitment fresh_public_legal_set_and_canonical_order c_resolver_result_and_selected_action_ref e_fresh_confirmation_and_issuance_evidence b_timeout_receipt_link completion security_operation_evidence evidence_identity"


def logical_continuation_identity_v1(binding: Mapping[str, object], progress: contract.PublicOrdinalProgressV1) -> str:
    """Acyclic actual accepted-step binding, computed before the B CONTINUE event."""
    return _identity({"schema": "sgs-c8-g-on-time-logical-step-v1",
        "logical_obligation_identity": progress.logical_obligation_identity,
        **{key: binding[key] for key in ("window_authority_ref_identity", "step_index", "window_step_index",
            "production_context_identity", "inner_decision_identity", "production_action_ref",
            "pre_step_count", "post_step_count", "deadline_at", "decision_tick")}})


def validate_liveness_step_v1(value: object, inp: contract.FormalDriverInputV1,
                              binding: Mapping[str, object]) -> contract.PublicOrdinalProgressV1 | None:
    if inp.public_ordinal_progress is None:
        if value is not None:
            raise C8G1ReplaySemanticError("普通输入不能夹入private certificate")
        return None
    d = _object(value, "before after post_public_boundary", "liveness step")
    before = contract.PublicOrdinalProgressV1.from_dict(d["before"])
    exact_equal_v3(before.to_dict(), inp.public_ordinal_progress.to_dict(), "liveness driver before")
    for key, expected in (("opening_ref_identity", binding["window_authority_ref_identity"]),
                          ("opening_context_identity", binding["opening_production_context_identity"]),
                          ("accepted_step_index", binding["pre_step_count"])):
        exact_equal_v3(getattr(before, key), expected, "liveness opening/step "+key)
    exact_equal_v3(binding["window_step_index"], before.accepted_step_index-before.entry_step_index, "liveness local step")
    post = _object(d["post_public_boundary"], "next_phase next_actor_id next_turn_number next_turn_player_id next_proposal_count", "liveness post public boundary")
    for key in ("next_phase", "next_actor_id", "next_turn_player_id"):
        _optional_text_id(post[key], key)
    _optional_integer(post["next_turn_number"], "next turn", minimum=1)
    _integer(post["next_proposal_count"], "next count")
    after = contract.advance_public_ordinal_progress_v1(before,
        chosen_ordinal=binding["production_action_ref"]["executed_public_ordinal"],
        post_step_count=binding["post_step_count"], **post)
    exact_equal_v3(d["after"], after.to_dict(), "fresh public induction transition")
    return after


def _validate_decision(value: object, *, timeout: bool) -> dict[str, object]:
    d = _object(value, TIMEOUT_FIELDS if timeout else ON_TIME_FIELDS, "typed decision")
    if (d["schema"], d["kind"]) != ((TIMEOUT_SCHEMA, TIMEOUT_KIND) if timeout else (ON_TIME_SCHEMA, ON_TIME_KIND)):
        raise C8G1ReplaySemanticError("typed decision tag/schema不匹配")
    b = ProductionActionBindingV1.from_dict(d["binding"]).to_dict()
    schedule = (_object(d["timeout_schedule_decision"], "driver_input driver_decision", "timeout schedule")
                if timeout else d)
    inp = driver_input_from_dict_v3(schedule["driver_input"])
    decision = driver_decision_dict_v3(inp)
    exact_equal_v3(schedule["driver_decision"], decision, "frozen driver v3 recomputation")
    exact_equal_v3(decision["actual_timeout"], timeout, "LT/EQ branch")
    for key in ("global_window_index", "turn_number", "turn_player_id", "actor_id", "phase", "deadline_at"):
        exact_equal_v3(schedule["driver_input"][key], b[key], "driver/binding "+key)
    exact_equal_v3(inp.window_kind.value, b["driver_window_kind"], "raw E / driver kind")
    exact_equal_v3(decision["decision_tick"], b["decision_tick"], "decision tick")
    a = b["production_action_ref"]
    if not timeout:
        validate_public_legal_v3(d["fresh_public_legal_set"], inp, b)
        if b["decision_tick"] != b["deadline_at"] - 1:
            raise C8G1ReplaySemanticError("on-time必须deadline-1")
        exact_equal_v3(decision["chosen_public_ordinal"], a["executed_public_ordinal"], "on-time chosen ordinal")
        exact_equal_v3(decision["chosen_public_action_family"], a["executed_public_action_family"], "on-time chosen family")
        f = _object(d["normal_forward"], "returned_public_state_identity inner_transition_identity runtime_forward_event_identity", "normal forward")
        for key in f:
            _sha256(f[key], key)
        exact_equal_v3(f["returned_public_state_identity"], b["post_public_state_identity"], "normal return")
        progress = validate_liveness_step_v1(d["liveness"], inp, b)
        continued = progress is not None and progress.stage != "DONE"
        if continued:
            c = _object(d["completion"], "kind logical_step_identity continue_event_identity progress_identity post_step_observation_identity", "on-time continuation")
            if c["kind"] != "ON_TIME_OBLIGATION_CONTINUED" or b["production_window_kind"] != "MULTI_STEP_OBLIGATION":
                raise C8G1ReplaySemanticError("continuation必须保持实际multi-step window")
            exact_equal_v3(c["logical_step_identity"], logical_continuation_identity_v1(b, inp.public_ordinal_progress), "accepted continuation identity")
            exact_equal_v3(c["continue_event_identity"], b["window_disposition_ref"], "B continuation event")
        else:
            c = _object(d["completion"], "kind close_event_identity closed_window_identity completed_context_identity post_step_observation_identity", "on-time completion")
            if c["kind"] != "ON_TIME_CONTEXT_CLOSED":
                raise C8G1ReplaySemanticError("on-time completion kind mismatch")
            exact_equal_v3(c["completed_context_identity"], b["opening_production_context_identity"], "completed opening ownership")
            exact_equal_v3(c["close_event_identity"], b["window_disposition_ref"], "action close")
    else:
        exact_equal_v3(b["window_step_index"], 0, "timeout window cannot inherit on-time continuation")
        exact_equal_v3(b["opening_production_context_identity"], b["production_context_identity"], "timeout opening context")
        if b["decision_tick"] != b["deadline_at"]:
            raise C8G1ReplaySemanticError("冻结timeout调度必须exact deadline")
        due = _object(d["timeout_due_commitment"], "commitment_identity deadline_at decision_tick window_authority_ref_identity", "timeout due")
        _sha256(due["commitment_identity"], "due identity")
        for key in ("deadline_at", "decision_tick", "window_authority_ref_identity"):
            exact_equal_v3(due[key], b[key], "due/binding "+key)
        legal = _object(d["fresh_public_legal_set_and_canonical_order"], "public_legal_set legal_set_identity canonical_order_identity snapshot_identity", "timeout legal")
        validate_public_legal_v3(legal["public_legal_set"], inp, b)
        for key in ("legal_set_identity", "canonical_order_identity", "snapshot_identity"):
            _sha256(legal[key], key)
        result = _object(d["c_resolver_result_and_selected_action_ref"], "result_identity result_kind selected_action_identity production_action_ref receipt_identity selection_identity", "C result")
        if result["result_kind"] != "RESOLVED_SINGLE":
            raise C8G1ReplaySemanticError("current E不支持continued/multi-step callback")
        exact_equal_v3(result["production_action_ref"], a, "C selected action ref")
        for key in ("result_identity", "selected_action_identity", "receipt_identity", "selection_identity"):
            _sha256(result[key], key)
        e = _object(d["e_fresh_confirmation_and_issuance_evidence"], "issuance_identity candidate_identity public_ordinal signed_action_id_commitment legal_set_identity canonical_order_identity timeout_due_identity context_identity ledger_before_identity ledger_after_identity", "E evidence")
        for key in e:
            if key != "public_ordinal":
                _sha256(e[key], key)
        _integer(e["public_ordinal"], "E ordinal")
        for key, fresh in (("public_ordinal", a["executed_public_ordinal"]),
                           ("signed_action_id_commitment", a["signed_action_id_commitment"]),
                           ("legal_set_identity", legal["legal_set_identity"]),
                           ("canonical_order_identity", legal["canonical_order_identity"]),
                           ("timeout_due_identity", due["commitment_identity"]),
                           ("context_identity", b["production_context_identity"])):
            exact_equal_v3(e[key], fresh, "E cross-link "+key)
        link = _object(d["b_timeout_receipt_link"], "receipt_identity c_result_identity c_selected_action_identity runtime_forward_event_identity runtime_disposition_event_identity timeout_due_identity signed_action_id_commitment", "B receipt link")
        for key in link:
            _sha256(link[key], key)
        for key, fresh in (("receipt_identity", result["receipt_identity"]),
                           ("c_result_identity", result["result_identity"]),
                           ("c_selected_action_identity", result["selected_action_identity"]),
                           ("timeout_due_identity", due["commitment_identity"]),
                           ("signed_action_id_commitment", a["signed_action_id_commitment"]),
                           ("runtime_disposition_event_identity", b["window_disposition_ref"])):
            exact_equal_v3(link[key], fresh, "B cross-link "+key)
        c = _object(d["completion"], "kind receipt_identity runtime_disposition_event_identity obligation_progress_ref post_step_observation_identity", "timeout completion")
        # The union reserves continuation for a future E profile; the current exact E always closes.
        if c["kind"] != "TIMEOUT_CONTEXT_CLOSED" or c["obligation_progress_ref"] is not None:
            raise C8G1ReplaySemanticError("current E completion必须receipt-bound close")
        exact_equal_v3(c["receipt_identity"], link["receipt_identity"], "completion receipt")
        exact_equal_v3(c["runtime_disposition_event_identity"], b["window_disposition_ref"], "timeout close")
        security = _object(d["security_operation_evidence"], "before_identity after_identity before_epoch after_epoch", "security operations")
        _sha256(security["before_identity"], "security before")
        _sha256(security["after_identity"], "security after")
        if _integer(security["after_epoch"], "after epoch") <= _integer(security["before_epoch"], "before epoch"):
            raise C8G1ReplaySemanticError("timeout security操作没有进展")
    for key in c:
        if key not in {"kind", "obligation_progress_ref"}:
            _sha256(c[key], key)
    exact_equal_v3(d["evidence_identity"], _identity({key: item for key, item in d.items() if key != "evidence_identity"}), "typed evidence identity")
    return d


@dataclass(frozen=True, slots=True, repr=False)
class OnTimeProductionDecisionEvidenceV1:
    value: Mapping[str, object]

    def __post_init__(self) -> None:
        object.__setattr__(self, "value", _freeze(_validate_decision(_plain(self.value), timeout=False)))

    def to_dict(self) -> dict[str, object]:
        return _plain(self.value)

    @classmethod
    def from_dict(cls, value: object) -> "OnTimeProductionDecisionEvidenceV1":
        return cls(_exact_dict(value, "on-time evidence"))


@dataclass(frozen=True, slots=True, repr=False)
class TimeoutProductionDecisionEvidenceV1:
    value: Mapping[str, object]

    def __post_init__(self) -> None:
        object.__setattr__(self, "value", _freeze(_validate_decision(_plain(self.value), timeout=True)))

    def to_dict(self) -> dict[str, object]:
        return _plain(self.value)

    @classmethod
    def from_dict(cls, value: object) -> "TimeoutProductionDecisionEvidenceV1":
        return cls(_exact_dict(value, "timeout evidence"))


def production_decision_from_dict_v1(value: object) -> OnTimeProductionDecisionEvidenceV1 | TimeoutProductionDecisionEvidenceV1:
    d = _exact_dict(value, "typed decision")
    if d.get("kind") == ON_TIME_KIND:
        return OnTimeProductionDecisionEvidenceV1.from_dict(d)
    if d.get("kind") == TIMEOUT_KIND:
        return TimeoutProductionDecisionEvidenceV1.from_dict(d)
    raise C8G1ReplaySemanticError("unknown production decision branch")


def completion_from_decision_v1(value: object) -> contract.DecisionCompletionEvidenceV1:
    d = production_decision_from_dict_v1(value).to_dict()
    b = ProductionActionBindingV1.from_dict(d["binding"])
    return contract.DecisionCompletionEvidenceV1(
        d["kind"], d["evidence_identity"], b.binding_identity,
        ("CONTINUED" if d["completion"]["kind"] == "ON_TIME_OBLIGATION_CONTINUED" else
         "CLOSED_BY_ACTION" if d["kind"] == ON_TIME_KIND else "CLOSED_BY_TIMEOUT"),
        d["binding"]["window_disposition_ref"], d["completion"]["post_step_observation_identity"])


def ordered_production_sequence_v1(decisions: list[object]) -> list[dict[str, object]]:
    result = []
    previous = None
    previous_decision = None
    cell = None
    for i, raw in enumerate(decisions):
        d = production_decision_from_dict_v1(raw).to_dict()
        b = d["binding"]
        exact_equal_v3(b["inner_decision_index"], i, "ordered inner index")
        if cell is None:
            cell = b["cell_execution_identity"]
        exact_equal_v3(b["cell_execution_identity"], cell, "cross-cell action splice")
        if previous is not None:
            continued = previous_decision["completion"]["kind"] == "ON_TIME_OBLIGATION_CONTINUED"
            if continued:
                for key in ("global_window_index", "window_id", "window_authority_ref_identity", "opening_production_context_identity",
                            "actor_id", "turn_number", "turn_player_id", "phase", "deadline_at", "opened_at", "decision_tick", "virtual_input_ref"):
                    exact_equal_v3(b[key], previous[key], "same-window continuation "+key)
                exact_equal_v3(b["window_step_index"], previous["window_step_index"]+1, "consecutive window step")
                if d["kind"] != ON_TIME_KIND:
                    raise C8G1ReplaySemanticError("on-time continuation不能偷换timeout receipt")
                exact_equal_v3(d["liveness"]["before"], previous_decision["liveness"]["after"], "induction history continuation")
            else:
                exact_equal_v3(b["global_window_index"], previous["global_window_index"]+1, "B OPEN index")
                exact_equal_v3(b["window_step_index"], 0, "new-window first step")
                if b["window_authority_ref_identity"] == previous["window_authority_ref_identity"]:
                    raise C8G1ReplaySemanticError("closed window不能复活")
            for before, after in (("pre_revision", "post_revision"), ("pre_step_count", "post_step_count"),
                                  ("pre_execution_identity", "post_execution_identity"), ("pre_state_identity", "post_state_identity"),
                                  ("event_start", "event_end"), ("rng_start", "rng_end")):
                exact_equal_v3(b[before], previous[after], "ordered continuity "+before)
        elif b["global_window_index"] != 1 or b["window_step_index"] != 0:
            raise C8G1ReplaySemanticError("flat sequence必须从首个OPEN/accepted step开始")
        result.append({key: b[key] for key in ("cell_execution_identity", "inner_decision_index", "step_index",
                       "pre_revision", "post_revision", "pre_step_count", "post_step_count", "production_action_ref",
                       "pre_execution_identity", "post_execution_identity", "pre_state_identity", "post_state_identity",
                       "event_start", "event_end", "rng_start", "rng_end", "inner_decision_identity")})
        previous = b
        previous_decision = d
    if previous_decision is not None and previous_decision["completion"]["kind"] == "ON_TIME_OBLIGATION_CONTINUED":
        raise C8G1ReplaySemanticError("成功artifact不能截断未完成义务")
    return result


def ordered_production_sequence_identity_v1(sequence: object) -> str:
    return _identity({"schema": "sgs-c8-g-ordered-production-sequence-v1", "sequence": sequence})


def public_decision_projection_v1(value: object) -> dict[str, object]:
    d = production_decision_from_dict_v1(value).to_dict()
    return {**{key: item for key, item in d.items() if key != "binding"},
            "binding": ProductionActionBindingV1.from_dict(d["binding"]).public_projection()}


@dataclass(frozen=True, slots=True, repr=False)
class TimedEightPlayerFullGameReplayV1:
    """Current v3 parsed data. Parsing never issues a fresh result or restores ownership."""

    document: Mapping[str, object]

    def to_dict(self) -> dict[str, object]:
        return _plain(self.document)

    def to_json_bytes(self) -> bytes:
        return _canonical_bytes(self.to_dict())

    @classmethod
    def from_dict(cls, value: object, *, repo_root: Path | str | None = None) -> "TimedEightPlayerFullGameReplayV1":
        from . import c8_timed_8p_full_game_production_replay_v1 as production
        d = production.preflight_composition_v1(value, full_game=True, repo_root=repo_root)
        return cls(_freeze(d))

    @classmethod
    def from_json_bytes(cls, raw: bytes | str, *, repo_root: Path | str | None = None) -> "TimedEightPlayerFullGameReplayV1":
        return cls.from_dict(_strict_json(raw), repo_root=repo_root)


def strict_reexecute_full_game_replay_v1(value: TimedEightPlayerFullGameReplayV1) -> contract.FullGameResultV1:
    if type(value) is not TimedEightPlayerFullGameReplayV1:
        raise C8G1ReplayError("固定G3入口只接受current full-game envelope")
    from .c8_timed_8p_full_game_production_replay_v1 import verify_full_game_composition_v1
    return verify_full_game_composition_v1(value.to_dict())
