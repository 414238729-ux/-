# -*- coding: utf-8 -*-
"""C8-D generic timed-session/controller strict replay evidence (provisional).

This module records and reexecutes only a synthetic, public-action C8-A/B/C
trace.  It is not a production C6 eight-player adapter and it is not a full
game replay.  Every authoritative C8-B lease, guard, timeout commitment,
pending issuance capability, and receipt is freshly issued inside an isolated
worker process.  Serialized values are evidence commitments only and never
become live authority.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from types import MappingProxyType
from typing import Any, ClassVar, Final, Mapping, Sequence

from . import c8_timed_session_runtime_v1 as rt
from . import c8_timeout_controller_integration_v1 as ctl
from . import c8_virtual_time_contract_v1 as c8


class C8ReplayError(ValueError):
    """Base class for strict structural, identity, or replay divergence."""


class C8ReplayIdentityError(C8ReplayError):
    """The replay is not bound to the exact current A/B/C/D contract."""


class C8ReplayDivergenceError(C8ReplayError):
    """Fresh cold reexecution did not reproduce recorded evidence."""


C8_D_REPLAY_ID: Final[str] = "c8-strict-replay-v1"
C8_D_REPLAY_SCHEMA: Final[str] = "sgs-c8-strict-replay-v1"
C8_D_REPLAY_VERSION: Final[int] = 1
C8_D_SCOPE_MARKER: Final[str] = "GENERIC_TIMED_SESSION_CONTROLLER_TRACE_ONLY"
C8_D_PRODUCTION_ADAPTER_INTEGRATION: Final[str] = "NOT_PROVEN"
C8_D_FULL_GAME: Final[str] = "NOT_PROVEN"
C8_D_RECORDING_SCOPE: Final[str] = "COMMITTED_CONTROLLER_TRANSACTIONS_ONLY"
C8_D_FAILED_ATTEMPT_POLICY: Final[str] = (
    "NOT_A_COMMITTED_REPLAY_RECORD;RETAIN_B_NONROLLBACK_SECURITY_AUDIT"
)

C8_A_DEVELOPMENT_IDENTITY: Final[str] = (
    "3e4cc397d33d49388d66505a94569080d1130b5a03d0364929f83b817e8d031c"
)
C8_A_SOURCE_SHA256: Final[str] = (
    "a2f7ee8bf79c50ec10dbf60cc2e70286a4a3eacf972b8294c9fefabd886739c4"
)
C8_A_TEST_SHA256: Final[str] = (
    "4a55c7f5ea97938d228c6080a2dfc903359d515af39ffed6bce846b1613a0d1e"
)
C8_B_DEVELOPMENT_IDENTITY: Final[str] = (
    "d5768b198110401c04d3a8e1183eb7120910f2722e539e24af2644b1280deec0"
)
C8_B_SOURCE_SHA256: Final[str] = (
    "26e2b34d2f20d814cb5b3c62c915127b79663406d60e69b3a56da5e91e34c54a"
)
C8_B_TEST_SHA256: Final[str] = (
    "510cce80454eb9002cf55973a612fbe84fb610f862ee7774d258bc1b0ef83e16"
)
C8_C_DEVELOPMENT_IDENTITY: Final[str] = (
    "9ce93811f37276318e266e62bb6c0e8d897e5893a8d73379df1063f726bc3159"
)
C8_C_SOURCE_SHA256: Final[str] = (
    "cd906a86eefe42ae256af60219e136af31d337bcb50747676dbdaf59c4a8e026"
)
C8_C_TEST_SHA256: Final[str] = (
    "e0740f36afa0f775c9156699850dd4eea75abf16feb3e99135586a13c6d8f52a"
)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_TEXT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")
_ZERO_IDENTITY: Final[str] = "0" * 64


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _identity(value: object) -> str:
    return hashlib.sha256(_canonical_json_bytes(value)).hexdigest()


# Implementation migration, shared by every seed. The historical descriptor
# remains an explicit ancestor; a cell or result digest is never a source pin.
C8_B_DEVELOPMENT_IDENTITY = _identity({
    "schema": "sgs-c8-b-source-bound-development-v2",
    "prior_development_identity": C8_B_DEVELOPMENT_IDENTITY,
    "runtime_contract_identity": rt.C8_B_RUNTIME_CONTRACT_IDENTITY_V1,
    "source_sha256": C8_B_SOURCE_SHA256,
    "test_sha256": C8_B_TEST_SHA256,
})


def _plain(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if type(value) is tuple or type(value) is list:
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
        raise C8ReplayError(f"{label}必须是精确JSON object")
    if any(type(key) is not str for key in value):
        raise C8ReplayError(f"{label}字段名必须是精确字符串")
    return value


def _exact_list(value: object, label: str) -> list[Any]:
    if type(value) is not list:
        raise C8ReplayError(f"{label}必须是精确JSON array")
    return value


def _exact_keys(value: object, expected: frozenset[str], label: str) -> dict[str, Any]:
    data = _exact_dict(value, label)
    actual = frozenset(data)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise C8ReplayError(f"{label}字段不匹配 missing={missing} extra={extra}")
    return data


def _text(value: object, label: str, *, allow_empty: bool = False) -> str:
    if type(value) is not str or (not allow_empty and not value):
        raise C8ReplayError(f"{label}必须是精确字符串")
    return value


def _text_id(value: object, label: str) -> str:
    text = _text(value, label)
    if _TEXT_ID_RE.fullmatch(text) is None:
        raise C8ReplayError(f"{label}不是canonical text id")
    return text


def _sha256(value: object, label: str, *, allow_zero: bool = False) -> str:
    text = _text(value, label)
    if _SHA256_RE.fullmatch(text) is None or (not allow_zero and text == _ZERO_IDENTITY):
        raise C8ReplayError(f"{label}必须是canonical nonzero SHA-256")
    return text


def _integer(value: object, label: str, *, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise C8ReplayError(f"{label}必须是精确int且 >= {minimum}")
    return value


def _boolean(value: object, label: str) -> bool:
    if type(value) is not bool:
        raise C8ReplayError(f"{label}必须是精确bool")
    return value


def _optional_text(value: object, label: str) -> str | None:
    if value is None:
        return None
    return _text_id(value, label)


def _optional_integer(value: object, label: str) -> int | None:
    if value is None:
        return None
    return _integer(value, label)


def _strict_json_object(raw: bytes | str) -> dict[str, Any]:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise C8ReplayError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    try:
        parsed = json.loads(raw, object_pairs_hook=reject_duplicates)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        if isinstance(exc, C8ReplayError):
            raise
        raise C8ReplayError("replay不是strict JSON") from exc
    return _exact_dict(parsed, "replay JSON root")


_CONTRACT_DESCRIPTOR: Final[Mapping[str, object]] = MappingProxyType(
    {
        "schema": "sgs-c8-d-strict-replay-contract-v1",
        "contract_version": 1,
        "replay_id": C8_D_REPLAY_ID,
        "replay_schema": C8_D_REPLAY_SCHEMA,
        "scope_marker": C8_D_SCOPE_MARKER,
        "production_adapter_integration": C8_D_PRODUCTION_ADAPTER_INTEGRATION,
        "full_game": C8_D_FULL_GAME,
        "recording_scope": C8_D_RECORDING_SCOPE,
        "cold_authority": "FRESH_ISOLATED_PROCESS_REEXECUTION",
        "live_capability_rule": (
            "SERIALIZED_COMMITMENTS_NEVER_REHYDRATE_LIVE_AUTHORITY"
        ),
        "adapter_oracle": "DETERMINISTIC_PUBLIC_SYNTHETIC_SCRIPT_V1",
        "receipt_evidence": "FRESH_B_RECEIPT_REDERIVED_AND_FIELDWISE_COMPARED",
        "controller_evidence": "FRESH_C_RESULT_AND_EVENT_TRACE_RECOMPUTED",
        "security_evidence": (
            "NONROLLBACK_OPERATION_ATTEMPT_AND_EXTERNAL_AUTH_LINEAGE_RECOMPUTED"
        ),
        "failed_attempt_policy": C8_D_FAILED_ATTEMPT_POLICY,
        "wall_clock_semantics": "FORBIDDEN",
        "rng_semantics": "FORBIDDEN",
    }
)
C8_D_CONTRACT_IDENTITY: Final[str] = _identity(dict(_CONTRACT_DESCRIPTOR))

_DEVELOPMENT_DESCRIPTOR: Final[Mapping[str, object]] = MappingProxyType(
    {
        "schema": "sgs-c8-d-development-identity-v1",
        "contract_version": 1,
        "c8_d_contract_identity": C8_D_CONTRACT_IDENTITY,
        "c8_a_development_identity": C8_A_DEVELOPMENT_IDENTITY,
        "c8_b_development_identity": C8_B_DEVELOPMENT_IDENTITY,
        "c8_c_development_identity": C8_C_DEVELOPMENT_IDENTITY,
        "strict_envelope": "EXACT_ALL_LEVEL_FIELDS_NO_DEFAULTS",
        "cold_worker": "NEW_PROCESS_PER_RECORD_OR_REEXECUTE",
        "semantic_comparison": "CANONICAL_BYTE_EQUAL_EXECUTION_EVIDENCE",
    }
)
C8_D_DEVELOPMENT_IDENTITY: Final[str] = _identity(dict(_DEVELOPMENT_DESCRIPTOR))
C8_D_CURRENT_IMPLEMENTATION_IDENTITY: Final[str] = _identity(
    {
        "schema": "sgs-c8-d-current-implementation-identity-v1",
        "contract_version": 1,
        "c8_d_development_identity": C8_D_DEVELOPMENT_IDENTITY,
        "dependency_development_identities": [
            C8_A_DEVELOPMENT_IDENTITY,
            C8_B_DEVELOPMENT_IDENTITY,
            C8_C_DEVELOPMENT_IDENTITY,
        ],
    }
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(65536), b""):
            digest.update(block)
    return digest.hexdigest()


def _assert_dependency_files_current() -> None:
    root = _repo_root()
    expected = {
        root / "scripts/sgs_engine/c8_virtual_time_contract_v1.py": C8_A_SOURCE_SHA256,
        root / "tests/test_c8_virtual_time_contract_v1.py": C8_A_TEST_SHA256,
        root / "scripts/sgs_engine/c8_timed_session_runtime_v1.py": C8_B_SOURCE_SHA256,
        root / "tests/test_c8_timed_session_runtime_v1.py": C8_B_TEST_SHA256,
        root / "scripts/sgs_engine/c8_timeout_controller_integration_v1.py": C8_C_SOURCE_SHA256,
        root / "tests/test_c8_timeout_controller_integration_v1.py": C8_C_TEST_SHA256,
    }
    from . import c8_timed_replay_version_compatibility_v1 as compatibility
    if compatibility.assert_execution_source_pair_v1(expected):
        # The envelope separately checked actual verifier bytes; these fixed
        # values still bind the original producer, never the new implementation.
        return
    for path, expected_hash in expected.items():
        if not path.is_file() or _file_sha256(path) != expected_hash:
            raise C8ReplayIdentityError(f"dependency source/test hash drift: {path.name}")


def _assert_current_dependencies() -> None:
    if c8.C8_A_CONTRACT_IDENTITY_V1 != ctl.C8_A_REQUIRED_CONTRACT_IDENTITY:
        raise C8ReplayIdentityError("C8-A contract identity drift")
    if rt.C8_B_RUNTIME_CONTRACT_IDENTITY_V1 != (
        ctl.C8_B_REQUIRED_RUNTIME_CONTRACT_IDENTITY
    ):
        raise C8ReplayIdentityError("C8-B runtime contract identity drift")
    if rt.C8_B_CURRENT_CONTRACT_LATCH_V1.latch_identity != (
        ctl.C8_B_REQUIRED_CURRENT_CONTRACT_LATCH_IDENTITY
    ):
        raise C8ReplayIdentityError("C8-B current-contract latch drift")
    if ctl.C8_C_CONTROLLER_ID != "c8-timeout-controller-integration-v1":
        raise C8ReplayIdentityError("C8-C controller id drift")
    if ctl.C8_C_CONTRACT_IDENTITY != (
        "924c9712502cd24ccc4f77e5fce221b04f83b5257d51858f3ee6410e89390336"
    ):
        raise C8ReplayIdentityError("C8-C contract identity drift")
    _assert_dependency_files_current()


@dataclass(frozen=True, slots=True, kw_only=True)
class C8DCurrentContractLatchV1:
    schema: str
    contract_version: int
    replay_id: str
    replay_schema: str
    scope_marker: str
    production_adapter_integration: str
    full_game: str
    c8_a_contract_identity: str
    c8_a_development_identity: str
    c8_a_source_sha256: str
    c8_a_test_sha256: str
    clock_domain_identity: str
    duration_profile_identity: str
    fallback_registry_identity: str
    public_ordering_contract_id: str
    same_tick_chain_contract_identity: str
    same_tick_chain_max_steps: int
    bridge_frozen_identity: str
    c8_b_runtime_contract_identity: str
    c8_b_current_contract_latch_identity: str
    c8_b_development_identity: str
    c8_b_source_sha256: str
    c8_b_test_sha256: str
    c8_c_controller_id: str
    c8_c_contract_identity: str
    c8_c_development_identity: str
    c8_c_source_sha256: str
    c8_c_test_sha256: str
    c8_d_contract_identity: str
    c8_d_development_identity: str
    c8_d_current_implementation_identity: str
    latch_identity: str

    _KEYS: ClassVar[frozenset[str]] = frozenset(
        name for name in __annotations__ if not name.startswith("_")
    )

    def __post_init__(self) -> None:
        _assert_current_dependencies()
        material = self._material()
        expected = {**material, "latch_identity": _identity(material)}
        if self.to_dict() != expected:
            raise C8ReplayIdentityError("C8-D current-contract latch drift")

    @classmethod
    def _material(cls) -> dict[str, object]:
        return {
            "schema": "sgs-c8-d-current-contract-latch-v1",
            "contract_version": 1,
            "replay_id": C8_D_REPLAY_ID,
            "replay_schema": C8_D_REPLAY_SCHEMA,
            "scope_marker": C8_D_SCOPE_MARKER,
            "production_adapter_integration": C8_D_PRODUCTION_ADAPTER_INTEGRATION,
            "full_game": C8_D_FULL_GAME,
            "c8_a_contract_identity": c8.C8_A_CONTRACT_IDENTITY_V1,
            "c8_a_development_identity": C8_A_DEVELOPMENT_IDENTITY,
            "c8_a_source_sha256": C8_A_SOURCE_SHA256,
            "c8_a_test_sha256": C8_A_TEST_SHA256,
            "clock_domain_identity": c8.CLOCK_DOMAIN_V1.clock_domain_identity,
            "duration_profile_identity": c8.ENGINEERING_TEST_PROFILE_V1.profile_identity,
            "fallback_registry_identity": c8.TIMEOUT_FALLBACK_REGISTRY_V1.registry_identity,
            "public_ordering_contract_id": c8.PUBLIC_ORDERING_CONTRACT_ID,
            "same_tick_chain_contract_identity": (
                c8.SAME_TICK_FALLBACK_CHAIN_CONTRACT_V1.contract_identity
            ),
            "same_tick_chain_max_steps": c8.SAME_TICK_FALLBACK_CHAIN_MAX_STEPS,
            "bridge_frozen_identity": c8.BRIDGE_V1_FROZEN_BASELINE_IDENTITY,
            "c8_b_runtime_contract_identity": rt.C8_B_RUNTIME_CONTRACT_IDENTITY_V1,
            "c8_b_current_contract_latch_identity": (
                rt.C8_B_CURRENT_CONTRACT_LATCH_V1.latch_identity
            ),
            "c8_b_development_identity": C8_B_DEVELOPMENT_IDENTITY,
            "c8_b_source_sha256": C8_B_SOURCE_SHA256,
            "c8_b_test_sha256": C8_B_TEST_SHA256,
            "c8_c_controller_id": ctl.C8_C_CONTROLLER_ID,
            "c8_c_contract_identity": ctl.C8_C_CONTRACT_IDENTITY,
            "c8_c_development_identity": C8_C_DEVELOPMENT_IDENTITY,
            "c8_c_source_sha256": C8_C_SOURCE_SHA256,
            "c8_c_test_sha256": C8_C_TEST_SHA256,
            "c8_d_contract_identity": C8_D_CONTRACT_IDENTITY,
            "c8_d_development_identity": C8_D_DEVELOPMENT_IDENTITY,
            "c8_d_current_implementation_identity": (
                C8_D_CURRENT_IMPLEMENTATION_IDENTITY
            ),
        }

    @classmethod
    def canonical(cls) -> "C8DCurrentContractLatchV1":
        material = cls._material()
        return cls(**material, latch_identity=_identity(material))  # type: ignore[arg-type]

    def to_dict(self) -> dict[str, object]:
        return {
            **{name: getattr(self, name) for name in self._material()},
            "latch_identity": self.latch_identity,
        }

    @classmethod
    def from_dict(cls, value: object) -> "C8DCurrentContractLatchV1":
        data = _exact_keys(value, cls._KEYS, "C8DCurrentContractLatchV1")
        for name in cls._material():
            expected = cls._material()[name]
            actual = data[name]
            if type(actual) is not type(expected) or actual != expected:
                raise C8ReplayIdentityError(f"current-contract latch {name} drift")
        _sha256(data["latch_identity"], "latch_identity")
        return cls(**data)


@dataclass(frozen=True, slots=True, kw_only=True)
class C8ReplayInitialMaterialV1:
    schema: str
    contract_version: int
    trace_id: str
    trace_seed_identity: str
    instance_nonce_identity: str
    input_source_id: str
    driver_authority_identity: str
    inner_adapter_identity: str
    inner_session_binding_identity: str
    input_authenticator_identity: str
    controller_instance_identity: str
    synthetic_adapter_contract_identity: str
    material_identity: str

    _KEYS: ClassVar[frozenset[str]] = frozenset(
        name for name in __annotations__ if not name.startswith("_")
    )

    def __post_init__(self) -> None:
        expected = self._derived(self.trace_id)
        if self.to_dict() != expected:
            raise C8ReplayIdentityError("initial replay material不是canonical derivation")

    @classmethod
    def _derived(cls, trace_id: object) -> dict[str, object]:
        trace = _text_id(trace_id, "trace_id")
        seed = _identity(
            {
                "schema": "sgs-c8-d-trace-seed-v1",
                "contract_version": 1,
                "trace_id": trace,
                "c8_d_contract_identity": C8_D_CONTRACT_IDENTITY,
            }
        )
        material: dict[str, object] = {
            "schema": "sgs-c8-d-initial-material-v1",
            "contract_version": 1,
            "trace_id": trace,
            "trace_seed_identity": seed,
            "instance_nonce_identity": _identity(
                {"kind": "isolated-replay-runtime-nonce", "seed": seed}
            ),
            "input_source_id": f"c8-d-replay-driver-{trace}",
            "driver_authority_identity": _identity(
                {"kind": "replay-driver-authority", "seed": seed}
            ),
            "inner_adapter_identity": _identity(
                {"kind": "synthetic-public-inner-adapter", "seed": seed}
            ),
            "inner_session_binding_identity": _identity(
                {"kind": "synthetic-session-binding", "seed": seed}
            ),
            "input_authenticator_identity": _identity(
                {"kind": "synthetic-input-authenticator", "seed": seed}
            ),
            "controller_instance_identity": _identity(
                {"kind": "synthetic-c8-c-controller", "seed": seed}
            ),
            "synthetic_adapter_contract_identity": _identity(
                {
                    "schema": "sgs-c8-d-public-synthetic-adapter-contract-v1",
                    "contract_version": 1,
                    "public_only": True,
                    "deterministic": True,
                    "production_adapter": False,
                }
            ),
        }
        material["material_identity"] = _identity(material)
        return material

    @classmethod
    def build(cls, trace_id: str) -> "C8ReplayInitialMaterialV1":
        return cls(**cls._derived(trace_id))

    def to_dict(self) -> dict[str, object]:
        return {name: getattr(self, name) for name in self._KEYS}

    @classmethod
    def from_dict(cls, value: object) -> "C8ReplayInitialMaterialV1":
        data = _exact_keys(value, cls._KEYS, "C8ReplayInitialMaterialV1")
        return cls(**data)


class C8ReplayCommandKindV1(str, Enum):
    OPEN_WINDOW = "OPEN_WINDOW"
    ADVANCE_TIME = "ADVANCE_TIME"
    RESOLVE_TIMEOUT = "RESOLVE_TIMEOUT"


@dataclass(frozen=True, slots=True, kw_only=True)
class C8ReplayCommandV1:
    schema: str
    contract_version: int
    command_index: int
    command_kind: C8ReplayCommandKindV1
    window_key: str
    actor_id: str
    window_kind: str
    decision_identity: str
    obligation_identity: str
    parent_window_key: str | None
    requested_tick: int | None
    families_by_step: tuple[tuple[str, ...], ...]
    completion_by_step: tuple[bool, ...]
    command_identity: str

    _KEYS: ClassVar[frozenset[str]] = frozenset(
        name for name in __annotations__ if not name.startswith("_")
    )

    def __post_init__(self) -> None:
        if self.schema != "sgs-c8-d-replay-command-v1" or self.contract_version != 1:
            raise C8ReplayError("replay command schema/version不匹配")
        _integer(self.command_index, "command_index")
        if type(self.command_kind) is not C8ReplayCommandKindV1:
            raise C8ReplayError("command_kind必须是exact enum")
        _text_id(self.window_key, "window_key")
        if type(self.families_by_step) is not tuple or any(
            type(step) is not tuple for step in self.families_by_step
        ):
            raise C8ReplayError("families_by_step必须是nested strict tuple")
        if type(self.completion_by_step) is not tuple or any(
            type(item) is not bool for item in self.completion_by_step
        ):
            raise C8ReplayError("completion_by_step必须是strict bool tuple")
        if self.command_kind is C8ReplayCommandKindV1.OPEN_WINDOW:
            _text_id(self.actor_id, "actor_id")
            try:
                c8.TimedWindowKindV1(self.window_kind)
            except (TypeError, ValueError) as exc:
                raise C8ReplayError("unknown window_kind") from exc
            _sha256(self.decision_identity, "decision_identity")
            _sha256(self.obligation_identity, "obligation_identity")
            _optional_text(self.parent_window_key, "parent_window_key")
            if (
                self.requested_tick is not None
                or self.families_by_step
                or self.completion_by_step
            ):
                raise C8ReplayError("OPEN_WINDOW携带了非open字段")
        elif self.command_kind is C8ReplayCommandKindV1.ADVANCE_TIME:
            if (
                self.actor_id
                or self.window_kind
                or self.decision_identity
                or self.obligation_identity
                or self.parent_window_key is not None
                or self.families_by_step
                or self.completion_by_step
            ):
                raise C8ReplayError("ADVANCE_TIME携带了非advance字段")
            _integer(self.requested_tick, "requested_tick")
        else:
            if (
                self.actor_id
                or self.window_kind
                or self.decision_identity
                or self.obligation_identity
                or self.parent_window_key is not None
                or self.requested_tick is not None
            ):
                raise C8ReplayError("RESOLVE_TIMEOUT携带了非resolve字段")
            if not self.families_by_step or (
                len(self.families_by_step) != len(self.completion_by_step)
            ):
                raise C8ReplayError("resolve step families/completion长度不一致")
            if self.completion_by_step[-1] is not True or any(
                self.completion_by_step[:-1]
            ):
                raise C8ReplayError("committed trace必须仅在末step完成")
            for step in self.families_by_step:
                if not step:
                    raise C8ReplayError("每个legal-set step至少一个public candidate")
                for family in step:
                    try:
                        c8.PublicActionFamilyV1(family)
                    except (TypeError, ValueError) as exc:
                        raise C8ReplayError("unknown public action family") from exc
        if self.command_identity != _identity(self._identity_material()):
            raise C8ReplayIdentityError("command_identity mismatch")

    def _identity_material(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "contract_version": self.contract_version,
            "command_index": self.command_index,
            "command_kind": self.command_kind.value,
            "window_key": self.window_key,
            "actor_id": self.actor_id,
            "window_kind": self.window_kind,
            "decision_identity": self.decision_identity,
            "obligation_identity": self.obligation_identity,
            "parent_window_key": self.parent_window_key,
            "requested_tick": self.requested_tick,
            "families_by_step": [list(step) for step in self.families_by_step],
            "completion_by_step": list(self.completion_by_step),
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._identity_material(), "command_identity": self.command_identity}

    @classmethod
    def _build(cls, **values: object) -> "C8ReplayCommandV1":
        material = {
            "schema": "sgs-c8-d-replay-command-v1",
            "contract_version": 1,
            **values,
        }
        material["command_identity"] = _identity(material)
        return cls(**material)  # type: ignore[arg-type]

    @classmethod
    def open_window(
        cls,
        *,
        command_index: int,
        window_key: str,
        actor_id: str,
        window_kind: c8.TimedWindowKindV1 | str,
        decision_identity: str,
        obligation_identity: str,
        parent_window_key: str | None = None,
    ) -> "C8ReplayCommandV1":
        kind = (
            window_kind.value
            if type(window_kind) is c8.TimedWindowKindV1
            else _text(window_kind, "window_kind")
        )
        return cls._build(
            command_index=command_index,
            command_kind=C8ReplayCommandKindV1.OPEN_WINDOW,
            window_key=window_key,
            actor_id=actor_id,
            window_kind=kind,
            decision_identity=decision_identity,
            obligation_identity=obligation_identity,
            parent_window_key=parent_window_key,
            requested_tick=None,
            families_by_step=(),
            completion_by_step=(),
        )

    @classmethod
    def advance_time(
        cls, *, command_index: int, window_key: str, requested_tick: int
    ) -> "C8ReplayCommandV1":
        return cls._build(
            command_index=command_index,
            command_kind=C8ReplayCommandKindV1.ADVANCE_TIME,
            window_key=window_key,
            actor_id="",
            window_kind="",
            decision_identity="",
            obligation_identity="",
            parent_window_key=None,
            requested_tick=requested_tick,
            families_by_step=(),
            completion_by_step=(),
        )

    @classmethod
    def resolve_timeout(
        cls,
        *,
        command_index: int,
        window_key: str,
        families_by_step: Sequence[Sequence[c8.PublicActionFamilyV1 | str]],
        completion_by_step: Sequence[bool],
    ) -> "C8ReplayCommandV1":
        families = tuple(
            tuple(
                item.value if type(item) is c8.PublicActionFamilyV1 else str(item)
                for item in step
            )
            for step in families_by_step
        )
        return cls._build(
            command_index=command_index,
            command_kind=C8ReplayCommandKindV1.RESOLVE_TIMEOUT,
            window_key=window_key,
            actor_id="",
            window_kind="",
            decision_identity="",
            obligation_identity="",
            parent_window_key=None,
            requested_tick=None,
            families_by_step=families,
            completion_by_step=tuple(completion_by_step),
        )

    @classmethod
    def from_dict(cls, value: object) -> "C8ReplayCommandV1":
        data = _exact_keys(value, cls._KEYS, "C8ReplayCommandV1")
        converted = dict(data)
        try:
            converted["command_kind"] = C8ReplayCommandKindV1(
                _text(data["command_kind"], "command_kind")
            )
        except ValueError as exc:
            raise C8ReplayError("unknown command_kind") from exc
        converted["families_by_step"] = tuple(
            tuple(_text(item, "action_family") for item in _exact_list(step, "family step"))
            for step in _exact_list(data["families_by_step"], "families_by_step")
        )
        converted["completion_by_step"] = tuple(
            _boolean(item, "completion_by_step[]")
            for item in _exact_list(data["completion_by_step"], "completion_by_step")
        )
        return cls(**converted)


def _security_audit_dict(value: rt.ControllerCallbackSecurityAuditV1) -> dict[str, object]:
    if type(value) is not rt.ControllerCallbackSecurityAuditV1:
        raise C8ReplayError("security audit type drift")
    return value.to_dict()


def _parse_security_audit(value: object) -> rt.ControllerCallbackSecurityAuditV1:
    keys = frozenset(
        {
            "schema",
            "contract_version",
            "runtime_contract_identity",
            "runtime_instance_identity",
            "operation_attempt_epoch",
            "operation_attempt_chain_tip",
            "guard_active",
            "next_guard_generation",
            "authorizing_capability_exposed",
            "audit_identity",
        }
    )
    data = _exact_keys(value, keys, "controller callback security audit")
    if data["authorizing_capability_exposed"] is not False:
        raise C8ReplayError("serialized security audit禁止暴露authority")
    audit = rt.ControllerCallbackSecurityAuditV1(
        schema=_text(data["schema"], "security_audit.schema"),
        contract_version=_integer(data["contract_version"], "contract_version", minimum=1),
        runtime_contract_identity=_sha256(
            data["runtime_contract_identity"], "runtime_contract_identity"
        ),
        runtime_instance_identity=_sha256(
            data["runtime_instance_identity"], "runtime_instance_identity"
        ),
        operation_attempt_epoch=_integer(
            data["operation_attempt_epoch"], "operation_attempt_epoch"
        ),
        operation_attempt_chain_tip=_sha256(
            data["operation_attempt_chain_tip"], "operation_attempt_chain_tip"
        ),
        guard_active=_boolean(data["guard_active"], "guard_active"),
        next_guard_generation=_integer(
            data["next_guard_generation"], "next_guard_generation"
        ),
        audit_identity=_sha256(data["audit_identity"], "audit_identity"),
    )
    if audit.to_dict() != data:
        raise C8ReplayIdentityError("security audit serialization drift")
    return audit


def _parse_public_projection(
    value: object, outer_state: rt.TimedSessionOuterStateV1
) -> rt.TimedSessionPublicProjectionV1:
    data = _exact_dict(value, "TimedSessionPublicProjectionV1")
    expected = rt.TimedSessionPublicProjectionV1.from_state(outer_state)
    if frozenset(data) != frozenset(expected.to_dict()) or data != expected.to_dict():
        raise C8ReplayIdentityError("public projection与fresh outer-state derivation不一致")
    return expected


def _adapter_snapshot_dict(
    value: ctl.AdapterPublicLegalActionsSnapshotV1,
) -> dict[str, object]:
    return {
        "schema": value.schema,
        "contract_version": value.contract_version,
        "public_legal_set": value.public_legal_set.to_dict(),
        "projection_legal_set_identity": value.projection_legal_set_identity,
        "canonical_public_ordering_identity": (
            value.canonical_public_ordering_identity
        ),
        "runtime_instance_identity": value.runtime_instance_identity,
        "window_authority_ref_identity": value.window_authority_ref_identity,
        "window_id": value.window_id,
        "decision_identity": value.decision_identity,
        "obligation_identity": value.obligation_identity,
        "session_identity": value.session_identity,
        "controller_identity": value.controller_identity,
        "adapter_identity": value.adapter_identity,
        "public_state_identity": value.public_state_identity,
        "authoritative_state_identity": value.authoritative_state_identity,
        "issuance_security_ledger_identity": (
            value.issuance_security_ledger_identity
        ),
        "snapshot_identity": value.snapshot_identity,
    }


_ADAPTER_SNAPSHOT_KEYS = frozenset(
    {
        "schema",
        "contract_version",
        "public_legal_set",
        "projection_legal_set_identity",
        "canonical_public_ordering_identity",
        "runtime_instance_identity",
        "window_authority_ref_identity",
        "window_id",
        "decision_identity",
        "obligation_identity",
        "session_identity",
        "controller_identity",
        "adapter_identity",
        "public_state_identity",
        "authoritative_state_identity",
        "issuance_security_ledger_identity",
        "snapshot_identity",
    }
)


def _parse_adapter_snapshot(
    value: object,
) -> ctl.AdapterPublicLegalActionsSnapshotV1:
    data = _exact_keys(value, _ADAPTER_SNAPSHOT_KEYS, "adapter legal-set snapshot")
    public_set = c8.PublicLegalSetProjectionV1.from_dict(data["public_legal_set"])
    rebuilt = ctl.build_adapter_public_legal_actions_snapshot_v1(
        public_legal_set=public_set,
        runtime_instance_identity=_sha256(
            data["runtime_instance_identity"], "runtime_instance_identity"
        ),
        window_authority_ref_identity=_sha256(
            data["window_authority_ref_identity"], "window_authority_ref_identity"
        ),
        session_identity=_sha256(data["session_identity"], "session_identity"),
        controller_identity=_sha256(
            data["controller_identity"], "controller_identity"
        ),
        adapter_identity=_sha256(data["adapter_identity"], "adapter_identity"),
        public_state_identity=_sha256(
            data["public_state_identity"], "public_state_identity"
        ),
        authoritative_state_identity=_sha256(
            data["authoritative_state_identity"], "authoritative_state_identity"
        ),
        issuance_security_ledger_identity=_sha256(
            data["issuance_security_ledger_identity"],
            "issuance_security_ledger_identity",
        ),
    )
    if _adapter_snapshot_dict(rebuilt) != data:
        raise C8ReplayIdentityError("adapter legal-set snapshot mismatch")
    return rebuilt


def _bound_legal_set_dict(value: ctl.FreshPublicLegalActionsEnvelopeV1) -> dict[str, object]:
    return {
        "schema": value.schema,
        "contract_version": value.contract_version,
        "public_legal_set": value.public_legal_set.to_dict(),
        "projection_legal_set_identity": value.projection_legal_set_identity,
        "adapter_legal_set_snapshot_identity": (
            value.adapter_legal_set_snapshot_identity
        ),
        "legal_set_identity": value.legal_set_identity,
        "canonical_public_ordering_identity": (
            value.canonical_public_ordering_identity
        ),
        "timeout_authentication_bindings_identity": (
            value.timeout_authentication_bindings_identity
        ),
        "timeout_due_commitment_identity": value.timeout_due_commitment_identity,
        "runtime_contract_identity": value.runtime_contract_identity,
        "runtime_instance_identity": value.runtime_instance_identity,
        "window_authority_ref_identity": value.window_authority_ref_identity,
        "window_id": value.window_id,
        "decision_identity": value.decision_identity,
        "obligation_identity": value.obligation_identity,
        "session_identity": value.session_identity,
        "controller_identity": value.controller_identity,
        "adapter_identity": value.adapter_identity,
        "public_state_identity": value.public_state_identity,
        "authoritative_state_identity": value.authoritative_state_identity,
        "issuance_security_ledger_identity": (
            value.issuance_security_ledger_identity
        ),
    }


_BOUND_LEGAL_SET_KEYS = frozenset(
    {
        "schema",
        "contract_version",
        "public_legal_set",
        "projection_legal_set_identity",
        "adapter_legal_set_snapshot_identity",
        "legal_set_identity",
        "canonical_public_ordering_identity",
        "timeout_authentication_bindings_identity",
        "timeout_due_commitment_identity",
        "runtime_contract_identity",
        "runtime_instance_identity",
        "window_authority_ref_identity",
        "window_id",
        "decision_identity",
        "obligation_identity",
        "session_identity",
        "controller_identity",
        "adapter_identity",
        "public_state_identity",
        "authoritative_state_identity",
        "issuance_security_ledger_identity",
    }
)


def _parse_bound_legal_set(value: object) -> ctl.FreshPublicLegalActionsEnvelopeV1:
    data = _exact_keys(value, _BOUND_LEGAL_SET_KEYS, "bound legal-set envelope")
    public_set = c8.PublicLegalSetProjectionV1.from_dict(data["public_legal_set"])
    rebuilt = ctl.build_fresh_public_legal_actions_envelope_v1(
        public_legal_set=public_set,
        adapter_legal_set_snapshot_identity=_sha256(
            data["adapter_legal_set_snapshot_identity"],
            "adapter_legal_set_snapshot_identity",
        ),
        timeout_authentication_bindings_identity=_sha256(
            data["timeout_authentication_bindings_identity"],
            "timeout_authentication_bindings_identity",
        ),
        timeout_due_commitment_identity=_sha256(
            data["timeout_due_commitment_identity"],
            "timeout_due_commitment_identity",
        ),
        runtime_contract_identity=_sha256(
            data["runtime_contract_identity"], "runtime_contract_identity"
        ),
        runtime_instance_identity=_sha256(
            data["runtime_instance_identity"], "runtime_instance_identity"
        ),
        window_authority_ref_identity=_sha256(
            data["window_authority_ref_identity"], "window_authority_ref_identity"
        ),
        session_identity=_sha256(data["session_identity"], "session_identity"),
        controller_identity=_sha256(
            data["controller_identity"], "controller_identity"
        ),
        adapter_identity=_sha256(data["adapter_identity"], "adapter_identity"),
        public_state_identity=_sha256(
            data["public_state_identity"], "public_state_identity"
        ),
        authoritative_state_identity=_sha256(
            data["authoritative_state_identity"], "authoritative_state_identity"
        ),
        issuance_security_ledger_identity=_sha256(
            data["issuance_security_ledger_identity"],
            "issuance_security_ledger_identity",
        ),
    )
    if _bound_legal_set_dict(rebuilt) != data:
        raise C8ReplayIdentityError("bound legal-set envelope mismatch")
    return rebuilt


def _issuance_dict(value: ctl.SignedActionIssuanceEvidenceV1) -> dict[str, object]:
    return {
        **dict(value.identity_payload_v1()),
        "issuance_identity": value.issuance_identity,
        "serialized_live_authority": False,
    }


_ISSUANCE_KEYS = frozenset(
    set(ctl.SignedActionIssuanceEvidenceV1.__dataclass_fields__)
    - {"external_capability"}
    | {"serialized_live_authority"}
)


def _parse_issuance(value: object) -> ctl.SignedActionIssuanceEvidenceV1:
    data = _exact_keys(value, _ISSUANCE_KEYS, "issuance evidence")
    if data["serialized_live_authority"] is not False:
        raise C8ReplayError("serialized issuance禁止携带live authority")
    values = {
        key: item
        for key, item in data.items()
        if key not in {"issuance_identity", "serialized_live_authority"}
    }
    rebuilt = ctl.build_signed_action_issuance_evidence_v1(
        **values, external_capability=object()
    )
    if _issuance_dict(rebuilt) != data:
        raise C8ReplayIdentityError("issuance evidence mismatch")
    return rebuilt


_GUARD_EVIDENCE_KEYS = frozenset(
    {
        "schema",
        "contract_version",
        "callback_kind",
        "resolution_index",
        "step_index",
        "runtime_instance_identity",
        "controller_identity",
        "adapter_identity",
        "window_authority_ref_identity",
        "window_id",
        "timeout_due_commitment_identity",
        "pending_deadline_identity",
        "lease_generation",
        "lease_operation_attempt_epoch",
        "lease_operation_attempt_chain_tip",
        "lease_identity",
        "guard_entry_operation_attempt_epoch",
        "guard_entry_operation_attempt_chain_tip",
        "guard_identity",
        "guard_result_identity",
        "outer_state_identity",
        "callback_completed",
        "serialized_live_authority",
        "evidence_identity",
    }
)


def _validate_guard_evidence(value: object) -> dict[str, Any]:
    data = _exact_keys(value, _GUARD_EVIDENCE_KEYS, "callback guard evidence")
    if data["schema"] != "sgs-c8-d-callback-guard-evidence-v1" or data[
        "contract_version"
    ] != 1:
        raise C8ReplayError("callback guard evidence schema/version不匹配")
    if data["callback_kind"] not in {"LEGAL_SET", "ISSUANCE"}:
        raise C8ReplayError("unknown callback_kind")
    for name in ("resolution_index", "step_index", "lease_generation"):
        _integer(data[name], name)
    for name in (
        "lease_operation_attempt_epoch",
        "guard_entry_operation_attempt_epoch",
    ):
        _integer(data[name], name, minimum=1)
    for name in _GUARD_EVIDENCE_KEYS - {
        "schema",
        "contract_version",
        "callback_kind",
        "resolution_index",
        "step_index",
        "lease_generation",
        "lease_operation_attempt_epoch",
        "guard_entry_operation_attempt_epoch",
        "window_id",
        "callback_completed",
        "serialized_live_authority",
    }:
        _sha256(data[name], name)
    _text(data["window_id"], "window_id")
    if data["callback_completed"] is not True or data[
        "serialized_live_authority"
    ] is not False:
        raise C8ReplayError("callback guard evidence不得恢复authority且必须完成")
    material = {key: item for key, item in data.items() if key != "evidence_identity"}
    if data["evidence_identity"] != _identity(material):
        raise C8ReplayIdentityError("callback guard evidence identity mismatch")
    if data["guard_entry_operation_attempt_epoch"] != (
        data["lease_operation_attempt_epoch"] + 1
    ):
        raise C8ReplayError("callback guard attempt epoch lineage mismatch")
    return data


_CAPABILITY_EVIDENCE_KEYS = frozenset(
    {
        "schema",
        "contract_version",
        "step_index",
        "runtime_instance_identity",
        "controller_identity",
        "adapter_identity",
        "window_authority_ref_identity",
        "window_id",
        "timeout_due_commitment_identity",
        "pending_deadline_identity",
        "signed_action_id_commitment",
        "external_capability_identity",
        "authorization_ledger_identity_at_issue",
        "guard_result_identity",
        "capability_generation",
        "operation_attempt_epoch_at_issue",
        "capability_identity",
        "ownership_status_lineage",
        "committed_receipt_identity",
        "aborted",
        "consumed",
        "serialized_live_authority",
        "evidence_identity",
    }
)


def _validate_capability_evidence(value: object) -> dict[str, Any]:
    data = _exact_keys(value, _CAPABILITY_EVIDENCE_KEYS, "capability evidence")
    if data["schema"] != "sgs-c8-d-capability-lifecycle-evidence-v1" or data[
        "contract_version"
    ] != 1:
        raise C8ReplayError("capability evidence schema/version不匹配")
    _integer(data["step_index"], "step_index", minimum=1)
    _integer(data["capability_generation"], "capability_generation")
    _integer(
        data["operation_attempt_epoch_at_issue"],
        "operation_attempt_epoch_at_issue",
        minimum=1,
    )
    for name in _CAPABILITY_EVIDENCE_KEYS - {
        "schema",
        "contract_version",
        "step_index",
        "window_id",
        "capability_generation",
        "operation_attempt_epoch_at_issue",
        "ownership_status_lineage",
        "aborted",
        "consumed",
        "serialized_live_authority",
    }:
        _sha256(data[name], name)
    _text(data["window_id"], "window_id")
    lineage = _exact_list(data["ownership_status_lineage"], "ownership_status_lineage")
    if lineage != [
        "CONTROLLER_OWNED_PENDING",
        "AUTH_EVIDENCE_CONSUMED",
        "RECEIPT_COMMITTED_CONSUMED",
    ]:
        raise C8ReplayError("capability ownership lineage mismatch")
    if data["aborted"] is not False or data["consumed"] is not True:
        raise C8ReplayError("committed capability必须consumed且不得aborted")
    if data["serialized_live_authority"] is not False:
        raise C8ReplayError("serialized capability禁止成为live authority")
    material = {key: item for key, item in data.items() if key != "evidence_identity"}
    if data["evidence_identity"] != _identity(material):
        raise C8ReplayIdentityError("capability evidence identity mismatch")
    return data


_AUTH_LINEAGE_KEYS = frozenset(
    {
        "schema",
        "contract_version",
        "authority_kind",
        "step_index",
        "authorization_evidence_identity",
        "bound_input_or_action_identity",
        "expected_binding_identity",
        "ledger_before_identity",
        "ledger_after_identity",
        "consumed",
        "lineage_identity",
    }
)


def _validate_auth_lineage(value: object) -> dict[str, Any]:
    data = _exact_keys(value, _AUTH_LINEAGE_KEYS, "auth anti-replay lineage")
    if data["schema"] != "sgs-c8-d-auth-anti-replay-lineage-v1" or data[
        "contract_version"
    ] != 1:
        raise C8ReplayError("auth lineage schema/version不匹配")
    if data["authority_kind"] not in {"ADVANCE", "TIMEOUT_ACTION"}:
        raise C8ReplayError("unknown auth authority_kind")
    _integer(data["step_index"], "step_index")
    for name in _AUTH_LINEAGE_KEYS - {
        "schema",
        "contract_version",
        "authority_kind",
        "step_index",
        "consumed",
    }:
        _sha256(data[name], name)
    if data["consumed"] is not True or (
        data["ledger_before_identity"] == data["ledger_after_identity"]
    ):
        raise C8ReplayError("auth lineage必须证明one-shot ledger推进")
    material = {key: item for key, item in data.items() if key != "lineage_identity"}
    if data["lineage_identity"] != _identity(material):
        raise C8ReplayIdentityError("auth lineage identity mismatch")
    return data


_COMMAND_RECORD_KEYS = frozenset(
    {
        "schema",
        "contract_version",
        "command_index",
        "command_identity",
        "command_kind",
        "pre_outer_state",
        "post_outer_state",
        "pre_public_projection",
        "post_public_projection",
        "pre_security_audit",
        "post_security_audit",
        "window_ref",
        "advance_input",
        "accepted_input",
        "derived_deadline",
        "timeout_due_commitments",
        "legal_snapshots",
        "bound_legal_sets",
        "issuances",
        "callback_guards",
        "capability_transitions",
        "receipts",
        "auth_lineage",
        "controller_result",
        "controller_events",
        "record_identity",
    }
)


def _validate_command_record(value: object) -> dict[str, Any]:
    data = _exact_keys(value, _COMMAND_RECORD_KEYS, "replay command record")
    if data["schema"] != "sgs-c8-d-command-execution-record-v1" or data[
        "contract_version"
    ] != 1:
        raise C8ReplayError("command record schema/version不匹配")
    _integer(data["command_index"], "command_index")
    _sha256(data["command_identity"], "command_identity")
    try:
        kind = C8ReplayCommandKindV1(_text(data["command_kind"], "command_kind"))
    except ValueError as exc:
        raise C8ReplayError("unknown record command_kind") from exc
    pre_state = rt.TimedSessionOuterStateV1.from_dict(data["pre_outer_state"])
    post_state = rt.TimedSessionOuterStateV1.from_dict(data["post_outer_state"])
    _parse_public_projection(data["pre_public_projection"], pre_state)
    _parse_public_projection(data["post_public_projection"], post_state)
    pre_audit = _parse_security_audit(data["pre_security_audit"])
    post_audit = _parse_security_audit(data["post_security_audit"])
    if (
        pre_audit.runtime_instance_identity != pre_state.runtime_instance_identity
        or post_audit.runtime_instance_identity != post_state.runtime_instance_identity
    ):
        raise C8ReplayError("security audit/runtime lineage mismatch")
    ref = (
        None
        if data["window_ref"] is None
        else rt.WindowAuthorityRefV1.from_dict(data["window_ref"])
    )
    advance = (
        None
        if data["advance_input"] is None
        else c8.VirtualTimeAdvanceInputV1.from_dict(data["advance_input"])
    )
    accepted = (
        None
        if data["accepted_input"] is None
        else rt.AcceptedVirtualTimeInputV1.from_dict(data["accepted_input"])
    )
    commitments = tuple(
        rt.TimeoutDueCommitmentV1.from_dict(item)
        for item in _exact_list(
            data["timeout_due_commitments"], "timeout_due_commitments"
        )
    )
    snapshots = tuple(
        _parse_adapter_snapshot(item)
        for item in _exact_list(data["legal_snapshots"], "legal_snapshots")
    )
    envelopes = tuple(
        _parse_bound_legal_set(item)
        for item in _exact_list(data["bound_legal_sets"], "bound_legal_sets")
    )
    issuances = tuple(
        _parse_issuance(item)
        for item in _exact_list(data["issuances"], "issuances")
    )
    guards = tuple(
        _validate_guard_evidence(item)
        for item in _exact_list(data["callback_guards"], "callback_guards")
    )
    capabilities = tuple(
        _validate_capability_evidence(item)
        for item in _exact_list(
            data["capability_transitions"], "capability_transitions"
        )
    )
    receipts = tuple(
        rt.TimeoutActionExecutionReceiptV1.from_dict(item)
        for item in _exact_list(data["receipts"], "receipts")
    )
    auth_lineage = tuple(
        _validate_auth_lineage(item)
        for item in _exact_list(data["auth_lineage"], "auth_lineage")
    )
    result = (
        None
        if data["controller_result"] is None
        else ctl.TimeoutControllerResultV1.from_public_dict_v1(
            data["controller_result"]
        )
    )
    events = tuple(
        ctl.ControllerEventV1.from_public_dict_v1(item)
        for item in _exact_list(data["controller_events"], "controller_events")
    )

    if kind is C8ReplayCommandKindV1.OPEN_WINDOW:
        if ref is None or any(
            item is not None for item in (advance, accepted, result)
        ) or any((commitments, snapshots, envelopes, issuances, guards, capabilities, receipts, auth_lineage, events)):
            raise C8ReplayError("OPEN_WINDOW record evidence shape mismatch")
    elif kind is C8ReplayCommandKindV1.ADVANCE_TIME:
        if ref is None or advance is None or accepted is None or commitments or result is not None:
            raise C8ReplayError("ADVANCE_TIME record evidence shape mismatch")
        if any((snapshots, envelopes, issuances, guards, capabilities, receipts, events)):
            raise C8ReplayError("ADVANCE_TIME携带timeout/controller evidence")
        if len(auth_lineage) != 1 or auth_lineage[0]["authority_kind"] != "ADVANCE":
            raise C8ReplayError("ADVANCE_TIME缺少唯一auth lineage")
        if accepted.input_identity != advance.input_identity:
            raise C8ReplayError("accepted input未绑定advance input")
        if not post_state.input_records or post_state.input_records[-1] != accepted:
            raise C8ReplayError("post state未包含accepted input tail")
        if data["derived_deadline"] is not None:
            derived = c8.DerivedDeadlineReachedV1.from_dict(
                data["derived_deadline"],
                prior_state=pre_state.virtual_time_state,
                current_tick=post_state.virtual_time_state.now_tick,
                caused_by_input=advance,
                previous_event_chain_tip=pre_state.virtual_time_state.event_chain_tip,
            )
            if accepted.derived_deadline_identity != derived.event_identity:
                raise C8ReplayError("accepted input/deadline identity mismatch")
        elif accepted.derived_deadline_identity is not None:
            raise C8ReplayError("accepted input声称deadline但record缺失")
    else:
        if ref is None or not commitments or result is None or advance is not None or accepted is not None or data["derived_deadline"] is not None:
            raise C8ReplayError("RESOLVE_TIMEOUT record evidence shape mismatch")
        if result.result_kind not in {
            ctl.ControllerResultKindV1.RESOLVED_SINGLE.value,
            ctl.ControllerResultKindV1.RESOLVED_CHAIN.value,
        }:
            raise C8ReplayError("C8-D committed scope禁止记录失败/未解决结果")
        count = result.step_count
        if not (
            len(commitments)
            == len(snapshots)
            == len(envelopes)
            == len(issuances)
            == len(capabilities)
            == len(receipts)
            == count
        ):
            raise C8ReplayError("timeout per-step evidence count mismatch")
        if len(guards) != count * 2 or len(auth_lineage) != count:
            raise C8ReplayError("guard/auth evidence count mismatch")
        if tuple(item.legal_set_identity for item in envelopes) != result.legal_set_identities:
            raise C8ReplayError("controller result/legal-set order mismatch")
        if tuple(item.receipt_identity for item in receipts) != result.receipt_identities:
            raise C8ReplayError("controller result/receipt order mismatch")
        if tuple(item.event_identity for item in events) != result.event_identities:
            raise C8ReplayError("controller result/event order mismatch")
        if tuple(item.issuance_identity for item in issuances) != tuple(
            item.issuance_evidence_identity for item in result.selected_actions
        ):
            raise C8ReplayError("controller result/issuance order mismatch")
        for index, (issuance, receipt, capability) in enumerate(
            zip(issuances, receipts, capabilities, strict=True), start=1
        ):
            if (
                issuance.signed_action_id_commitment
                != receipt.signed_action_id_commitment
                or capability["step_index"] != index
                or capability["capability_identity"]
                != receipt.pending_issuance_capability_identity
                or capability["committed_receipt_identity"]
                != receipt.receipt_identity
            ):
                raise C8ReplayError("issuance/capability/receipt lineage mismatch")
    material = {key: item for key, item in data.items() if key != "record_identity"}
    if data["record_identity"] != _identity(material):
        raise C8ReplayIdentityError("command record identity mismatch")
    return data


_EXECUTION_KEYS = frozenset(
    {
        "schema",
        "contract_version",
        "initial_outer_state",
        "initial_public_projection",
        "initial_security_audit",
        "initial_authenticator_ledger_identity",
        "command_records",
        "controller_event_trace",
        "final_outer_state",
        "final_public_projection",
        "final_security_audit",
        "final_authenticator_ledger_identity",
        "semantic_identity",
        "execution_identity",
    }
)


def _execution_semantic_material(data: Mapping[str, object]) -> dict[str, object]:
    records = data["command_records"]
    assert type(records) is list
    return {
        "schema": "sgs-c8-d-execution-semantic-identity-v1",
        "contract_version": 1,
        "initial_state_identity": data["initial_outer_state"]["state_identity"],  # type: ignore[index]
        "command_identities": [item["command_identity"] for item in records],
        "command_record_identities": [item["record_identity"] for item in records],
        "controller_event_identities": [
            item["event_identity"] for item in data["controller_event_trace"]  # type: ignore[index]
        ],
        "final_state_identity": data["final_outer_state"]["state_identity"],  # type: ignore[index]
        "final_public_projection_identity": data["final_public_projection"][  # type: ignore[index]
            "projection_identity"
        ],
        "final_security_audit_identity": data["final_security_audit"][  # type: ignore[index]
            "audit_identity"
        ],
        "final_authenticator_ledger_identity": data[
            "final_authenticator_ledger_identity"
        ],
    }


def _validate_execution(value: object) -> dict[str, Any]:
    data = _exact_keys(value, _EXECUTION_KEYS, "C8 replay execution evidence")
    if data["schema"] != "sgs-c8-d-execution-evidence-v1" or data[
        "contract_version"
    ] != 1:
        raise C8ReplayError("execution evidence schema/version不匹配")
    initial_state = rt.TimedSessionOuterStateV1.from_dict(data["initial_outer_state"])
    final_state = rt.TimedSessionOuterStateV1.from_dict(data["final_outer_state"])
    _parse_public_projection(data["initial_public_projection"], initial_state)
    _parse_public_projection(data["final_public_projection"], final_state)
    initial_audit = _parse_security_audit(data["initial_security_audit"])
    final_audit = _parse_security_audit(data["final_security_audit"])
    if initial_audit.guard_active or final_audit.guard_active:
        raise C8ReplayError("record boundary禁止active controller callback guard")
    _sha256(
        data["initial_authenticator_ledger_identity"],
        "initial_authenticator_ledger_identity",
    )
    _sha256(
        data["final_authenticator_ledger_identity"],
        "final_authenticator_ledger_identity",
    )
    records = _exact_list(data["command_records"], "command_records")
    validated = tuple(_validate_command_record(item) for item in records)
    if validated:
        if validated[0]["pre_outer_state"] != data["initial_outer_state"]:
            raise C8ReplayError("first command pre-state不是initial state")
        for left, right in zip(validated, validated[1:]):
            if left["post_outer_state"] != right["pre_outer_state"]:
                raise C8ReplayError("command state chain出现delete/reorder/splice")
        if validated[-1]["post_outer_state"] != data["final_outer_state"]:
            raise C8ReplayError("last command post-state不是final state")
    elif data["initial_outer_state"] != data["final_outer_state"]:
        raise C8ReplayError("empty command trace改变了state")
    events = tuple(
        ctl.ControllerEventV1.from_public_dict_v1(item)
        for item in _exact_list(data["controller_event_trace"], "controller_event_trace")
    )
    previous = _ZERO_IDENTITY
    for index, event in enumerate(events, start=1):
        if event.event_sequence != index or event.previous_event_identity != previous:
            raise C8ReplayError("controller event trace reorder/delete/duplicate")
        previous = event.event_identity
    record_events = tuple(
        event["event_identity"]
        for record in validated
        for event in record["controller_events"]
    )
    if record_events != tuple(item.event_identity for item in events):
        raise C8ReplayError("per-command/global controller event trace mismatch")
    semantic = _identity(_execution_semantic_material(data))
    if data["semantic_identity"] != semantic:
        raise C8ReplayIdentityError("execution semantic identity mismatch")
    material = {key: item for key, item in data.items() if key != "execution_identity"}
    if data["execution_identity"] != _identity(material):
        raise C8ReplayIdentityError("execution identity mismatch")
    return data


@dataclass(frozen=True, slots=True, kw_only=True)
class C8ReplayExecutionEvidenceV1:
    value: Mapping[str, object]

    def __post_init__(self) -> None:
        plain = _plain(self.value)
        validated = _validate_execution(_exact_dict(plain, "execution evidence"))
        object.__setattr__(self, "value", _freeze(validated))

    @classmethod
    def from_dict(cls, value: object) -> "C8ReplayExecutionEvidenceV1":
        return cls(value=_exact_dict(value, "execution evidence"))

    def to_dict(self) -> dict[str, object]:
        return _exact_dict(_plain(self.value), "execution evidence")


def _public_projection_from_execution(
    commands: Sequence[C8ReplayCommandV1], evidence: C8ReplayExecutionEvidenceV1
) -> dict[str, object]:
    execution = evidence.to_dict()
    records = execution["command_records"]
    assert type(records) is list
    public_records: list[dict[str, object]] = []
    for command, record in zip(commands, records, strict=True):
        advance = record["advance_input"]
        public_advance = (
            None
            if advance is None
            else {
                key: advance[key]
                for key in (
                    "schema",
                    "contract_version",
                    "input_seq",
                    "source_id",
                    "domain_id",
                    "window_id",
                    "requested_tick",
                    "input_identity",
                )
            }
        )
        public_receipts = [
            {
                key: receipt[key]
                for key in (
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
                    "post_inner_public_state_identity",
                    "timeout_due_commitment_identity",
                    "pending_deadline_identity",
                    "derived_deadline_identity",
                    "deadline_at",
                    "executed_at_tick",
                    "outer_transition_identity",
                    "accepted",
                    "executed",
                    "receipt_identity",
                )
            }
            for receipt in record["receipts"]
        ]
        public_records.append(
            {
                "command_index": command.command_index,
                "command_kind": command.command_kind.value,
                "window_key": command.window_key,
                "command_identity": command.command_identity,
                "window_ref": record["window_ref"],
                "advance_input": public_advance,
                "derived_deadline": record["derived_deadline"],
                "public_legal_sets": [
                    item["public_legal_set"] for item in record["bound_legal_sets"]
                ],
                "receipts": public_receipts,
                "controller_result": record["controller_result"],
                "controller_events": record["controller_events"],
                "post_public_projection": record["post_public_projection"],
            }
        )
    material: dict[str, object] = {
        "schema": "sgs-c8-d-replay-public-projection-v1",
        "contract_version": 1,
        "replay_id": C8_D_REPLAY_ID,
        "scope_marker": C8_D_SCOPE_MARKER,
        "production_adapter_integration": C8_D_PRODUCTION_ADAPTER_INTEGRATION,
        "full_game": C8_D_FULL_GAME,
        "public_only": True,
        "initial_public_projection": execution["initial_public_projection"],
        "command_records": public_records,
        "controller_event_trace": execution["controller_event_trace"],
        "final_public_projection": execution["final_public_projection"],
        "execution_semantic_identity": execution["semantic_identity"],
    }
    material["public_projection_identity"] = _identity(material)
    return material


_REPLAY_KEYS = frozenset(
    {
        "schema",
        "replay_version",
        "replay_id",
        "scope_marker",
        "production_adapter_integration",
        "full_game",
        "recording_scope",
        "current_contract_latch",
        "c8_d_contract_identity",
        "c8_d_development_identity",
        "c8_d_current_implementation_identity",
        "initial_material",
        "commands",
        "execution_evidence",
        "public_projection",
        "replay_identity",
    }
)


@dataclass(frozen=True, slots=True, kw_only=True)
class C8StrictReplayV1:
    schema: str
    replay_version: int
    replay_id: str
    scope_marker: str
    production_adapter_integration: str
    full_game: str
    recording_scope: str
    current_contract_latch: C8DCurrentContractLatchV1
    c8_d_contract_identity: str
    c8_d_development_identity: str
    c8_d_current_implementation_identity: str
    initial_material: C8ReplayInitialMaterialV1
    commands: tuple[C8ReplayCommandV1, ...]
    execution_evidence: C8ReplayExecutionEvidenceV1
    public_projection: Mapping[str, object]
    replay_identity: str

    def __post_init__(self) -> None:
        if (
            self.schema != C8_D_REPLAY_SCHEMA
            or self.replay_version != C8_D_REPLAY_VERSION
            or self.replay_id != C8_D_REPLAY_ID
            or self.scope_marker != C8_D_SCOPE_MARKER
            or self.production_adapter_integration
            != C8_D_PRODUCTION_ADAPTER_INTEGRATION
            or self.full_game != C8_D_FULL_GAME
            or self.recording_scope != C8_D_RECORDING_SCOPE
        ):
            raise C8ReplayIdentityError("replay schema/version/scope latch drift")
        if type(self.current_contract_latch) is not C8DCurrentContractLatchV1:
            raise C8ReplayError("current_contract_latch type drift")
        if self.current_contract_latch != C8DCurrentContractLatchV1.canonical():
            raise C8ReplayIdentityError("current contract latch mismatch")
        expected_d = {
            "c8_d_contract_identity": C8_D_CONTRACT_IDENTITY,
            "c8_d_development_identity": C8_D_DEVELOPMENT_IDENTITY,
            "c8_d_current_implementation_identity": (
                C8_D_CURRENT_IMPLEMENTATION_IDENTITY
            ),
        }
        for name, expected in expected_d.items():
            if getattr(self, name) != expected:
                raise C8ReplayIdentityError(f"{name} drift")
        if type(self.initial_material) is not C8ReplayInitialMaterialV1:
            raise C8ReplayError("initial_material type drift")
        if type(self.commands) is not tuple or not self.commands or any(
            type(item) is not C8ReplayCommandV1 for item in self.commands
        ):
            raise C8ReplayError("commands必须是nonempty strict tuple")
        if tuple(item.command_index for item in self.commands) != tuple(
            range(len(self.commands))
        ):
            raise C8ReplayError("commands index必须连续且从0开始")
        if len({item.command_identity for item in self.commands}) != len(self.commands):
            raise C8ReplayError("duplicate command identity")
        if type(self.execution_evidence) is not C8ReplayExecutionEvidenceV1:
            raise C8ReplayError("execution_evidence type drift")
        execution = self.execution_evidence.to_dict()
        records = execution["command_records"]
        assert type(records) is list
        if len(records) != len(self.commands):
            raise C8ReplayError("command/execution count mismatch")
        for command, record in zip(self.commands, records, strict=True):
            if (
                record["command_index"] != command.command_index
                or record["command_identity"] != command.command_identity
                or record["command_kind"] != command.command_kind.value
            ):
                raise C8ReplayError("execution record未绑定exact command")
        expected_public = _public_projection_from_execution(
            self.commands, self.execution_evidence
        )
        plain_public = _exact_dict(_plain(self.public_projection), "public_projection")
        if plain_public != expected_public:
            raise C8ReplayIdentityError("public projection不是execution的strict derivation")
        object.__setattr__(self, "public_projection", _freeze(plain_public))
        expected_replay_identity = _identity(self._identity_material())
        if self.replay_identity != expected_replay_identity:
            raise C8ReplayIdentityError("replay identity mismatch")

    def _identity_material(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "replay_version": self.replay_version,
            "replay_id": self.replay_id,
            "scope_marker": self.scope_marker,
            "production_adapter_integration": self.production_adapter_integration,
            "full_game": self.full_game,
            "recording_scope": self.recording_scope,
            "current_contract_latch": self.current_contract_latch.to_dict(),
            "c8_d_contract_identity": self.c8_d_contract_identity,
            "c8_d_development_identity": self.c8_d_development_identity,
            "c8_d_current_implementation_identity": (
                self.c8_d_current_implementation_identity
            ),
            "initial_material": self.initial_material.to_dict(),
            "commands": [item.to_dict() for item in self.commands],
            "execution_evidence": self.execution_evidence.to_dict(),
            "public_projection": _plain(self.public_projection),
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._identity_material(), "replay_identity": self.replay_identity}

    def to_json_bytes(self) -> bytes:
        return _canonical_json_bytes(self.to_dict())

    def to_public_dict_v1(self) -> dict[str, object]:
        return _exact_dict(_plain(self.public_projection), "public projection")

    @classmethod
    def from_dict(cls, value: object) -> "C8StrictReplayV1":
        data = _exact_keys(value, _REPLAY_KEYS, "C8StrictReplayV1")
        commands_raw = _exact_list(data["commands"], "commands")
        return cls(
            schema=_text(data["schema"], "schema"),
            replay_version=_integer(data["replay_version"], "replay_version", minimum=1),
            replay_id=_text(data["replay_id"], "replay_id"),
            scope_marker=_text(data["scope_marker"], "scope_marker"),
            production_adapter_integration=_text(
                data["production_adapter_integration"],
                "production_adapter_integration",
            ),
            full_game=_text(data["full_game"], "full_game"),
            recording_scope=_text(data["recording_scope"], "recording_scope"),
            current_contract_latch=C8DCurrentContractLatchV1.from_dict(
                data["current_contract_latch"]
            ),
            c8_d_contract_identity=_sha256(
                data["c8_d_contract_identity"], "c8_d_contract_identity"
            ),
            c8_d_development_identity=_sha256(
                data["c8_d_development_identity"], "c8_d_development_identity"
            ),
            c8_d_current_implementation_identity=_sha256(
                data["c8_d_current_implementation_identity"],
                "c8_d_current_implementation_identity",
            ),
            initial_material=C8ReplayInitialMaterialV1.from_dict(
                data["initial_material"]
            ),
            commands=tuple(C8ReplayCommandV1.from_dict(item) for item in commands_raw),
            execution_evidence=C8ReplayExecutionEvidenceV1.from_dict(
                data["execution_evidence"]
            ),
            public_projection=_freeze(
                _exact_dict(data["public_projection"], "public_projection")
            ),
            replay_identity=_sha256(data["replay_identity"], "replay_identity"),
        )

    @classmethod
    def from_json_bytes(cls, raw: bytes | str) -> "C8StrictReplayV1":
        return cls.from_dict(_strict_json_object(raw))


def recompute_c8_replay_outer_identities_v1(value: Mapping[str, object]) -> dict[str, object]:
    """Recompute public non-secret outer hashes for adversarial test construction."""

    plain = _exact_dict(_plain(value), "replay")
    _exact_keys(plain, _REPLAY_KEYS, "replay")
    execution = _exact_dict(plain["execution_evidence"], "execution_evidence")
    records = _exact_list(execution["command_records"], "command_records")
    for record in records:
        record_data = _exact_dict(record, "command_record")
        record_data["record_identity"] = _identity(
            {key: item for key, item in record_data.items() if key != "record_identity"}
        )
    execution["semantic_identity"] = _identity(_execution_semantic_material(execution))
    execution["execution_identity"] = _identity(
        {key: item for key, item in execution.items() if key != "execution_identity"}
    )
    public = _exact_dict(plain["public_projection"], "public_projection")
    public["execution_semantic_identity"] = execution["semantic_identity"]
    public["public_projection_identity"] = _identity(
        {key: item for key, item in public.items() if key != "public_projection_identity"}
    )
    plain["replay_identity"] = _identity(
        {key: item for key, item in plain.items() if key != "replay_identity"}
    )
    return plain


def _auth_lineage_record(
    *,
    authority_kind: str,
    step_index: int,
    authorization_evidence_identity: str,
    bound_input_or_action_identity: str,
    expected_binding_identity: str,
    ledger_before_identity: str,
    ledger_after_identity: str,
) -> dict[str, object]:
    material: dict[str, object] = {
        "schema": "sgs-c8-d-auth-anti-replay-lineage-v1",
        "contract_version": 1,
        "authority_kind": authority_kind,
        "step_index": step_index,
        "authorization_evidence_identity": authorization_evidence_identity,
        "bound_input_or_action_identity": bound_input_or_action_identity,
        "expected_binding_identity": expected_binding_identity,
        "ledger_before_identity": ledger_before_identity,
        "ledger_after_identity": ledger_after_identity,
        "consumed": True,
    }
    material["lineage_identity"] = _identity(material)
    return material


class _ReplayInnerAdapter:
    """Deterministic synthetic inner adapter; no gameplay/private payload exists."""

    def __init__(self, initial: C8ReplayInitialMaterialV1) -> None:
        self._adapter_identity = initial.inner_adapter_identity
        self._session_identity = initial.inner_session_binding_identity
        self._token_marker = f"c8-d-opaque-snapshot:{initial.trace_seed_identity}"
        self.public_counter = 0
        self.authoritative_counter = 0
        self.action_commitments: list[str] = []
        self.runtime: rt.C8TimedSessionRuntimeV1 | None = None
        self.audit_by_epoch: dict[int, dict[str, object]] = {}
        self.apply_observations: list[dict[str, object]] = []

    def bind_runtime(self, runtime: rt.C8TimedSessionRuntimeV1) -> None:
        if self.runtime is not None:
            raise C8ReplayError("inner adapter runtime already bound")
        self.runtime = runtime

    def _probe(self) -> None:
        if self.runtime is None:
            return
        audit = self.runtime.controller_callback_security_audit_v1()
        self.audit_by_epoch.setdefault(
            audit.operation_attempt_epoch,
            {
                "audit": audit.to_dict(),
                "outer_state_identity": self.runtime.state.state_identity,
            },
        )

    def adapter_identity_v1(self) -> str:
        self._probe()
        return self._adapter_identity

    def session_binding_identity_v1(self) -> str:
        self._probe()
        return self._session_identity

    def public_state_identity_v1(self) -> str:
        self._probe()
        return _identity(
            {
                "schema": "sgs-c8-d-synthetic-public-state-v1",
                "public_counter": self.public_counter,
                "action_commitments": self.action_commitments,
            }
        )

    def authoritative_state_identity_v1(self) -> str:
        self._probe()
        return _identity(
            {
                "schema": "sgs-c8-d-synthetic-authoritative-state-v1",
                "public_counter": self.public_counter,
                "authoritative_counter": self.authoritative_counter,
                "action_commitments": self.action_commitments,
            }
        )

    def capture_transaction_snapshot_v1(self) -> object:
        self._probe()
        return (
            self.public_counter,
            self.authoritative_counter,
            tuple(self.action_commitments),
            self._adapter_identity,
            self._session_identity,
            self._token_marker,
        )

    def snapshot_token_identity_v1(self, token: object) -> str:
        self._probe()
        if type(token) is not tuple:
            raise C8ReplayError("synthetic snapshot token type drift")
        return _identity(
            {
                "schema": "sgs-c8-d-synthetic-snapshot-token-commitment-v1",
                "token": list(token),
            }
        )

    def restore_transaction_snapshot_v1(self, token: object) -> None:
        self._probe()
        if type(token) is not tuple or len(token) != 6:
            raise C8ReplayError("synthetic snapshot token shape drift")
        public, authoritative, commitments, adapter, session, marker = token
        if marker != self._token_marker or adapter != self._adapter_identity or session != self._session_identity:
            raise C8ReplayError("synthetic snapshot token owner mismatch")
        if type(public) is not int or type(authoritative) is not int or type(commitments) is not tuple:
            raise C8ReplayError("synthetic snapshot token data drift")
        self.public_counter = public
        self.authoritative_counter = authoritative
        self.action_commitments = list(commitments)

    def apply_signed_action_id_v1(self, signed_action_id: str) -> None:
        self._probe()
        if self.runtime is None:
            raise C8ReplayError("inner adapter runtime missing")
        pre_state = self.runtime.state
        pre_public = self.public_state_identity_v1()
        pre_authoritative = self.authoritative_state_identity_v1()
        commitment = ctl.signed_action_id_commitment_v1(signed_action_id)
        self.public_counter += 1
        self.authoritative_counter += 1
        self.action_commitments.append(commitment)
        self.apply_observations.append(
            {
                "signed_action_id": signed_action_id,
                "signed_action_id_commitment": commitment,
                "pre_outer_state": pre_state,
                "pre_public_state_identity": pre_public,
                "pre_authoritative_state_identity": pre_authoritative,
                "post_public_state_identity": self.public_state_identity_v1(),
                "post_authoritative_state_identity": (
                    self.authoritative_state_identity_v1()
                ),
            }
        )


class _ReplayAuthenticator:
    """Deterministic one-shot authority with a non-rollback consumed ledger."""

    def __init__(self, initial: C8ReplayInitialMaterialV1) -> None:
        self._identity = initial.input_authenticator_identity
        self._next_authorization = 0
        self._authorized: dict[str, tuple[str, str, str]] = {}
        self._consumed: set[str] = set()
        self._revoked: set[str] = set()
        self._consumed_epoch = 0
        self.advance_lineage: list[dict[str, object]] = []
        self.timeout_lineage: list[dict[str, object]] = []

    def authenticator_identity_v1(self) -> str:
        return self._identity

    def anti_replay_state_identity_v1(self) -> str:
        return _identity(
            {
                "schema": "sgs-c8-d-synthetic-auth-ledger-v1",
                "consumed_epoch": self._consumed_epoch,
                "consumed_evidence": sorted(self._consumed),
                "revoked_evidence": sorted(self._revoked),
            }
        )

    def _issue(self, kind: str, subject: str, binding: str) -> str:
        evidence = _identity(
            {
                "schema": "sgs-c8-d-synthetic-authorization-evidence-v1",
                "authenticator_identity": self._identity,
                "authorization_sequence": self._next_authorization,
                "authority_kind": kind,
                "subject": subject,
                "binding": binding,
            }
        )
        self._next_authorization += 1
        self._authorized[evidence] = (kind, subject, binding)
        return evidence

    def authorize_advance(self, expected_binding: str) -> str:
        return self._issue("ADVANCE", expected_binding, expected_binding)

    def authorize_timeout_action(self, signed_action_id: str, binding: str) -> str:
        return self._issue("TIMEOUT_ACTION", signed_action_id, binding)

    def _consume(self, evidence: str) -> tuple[tuple[str, str, str] | None, str, str]:
        before = self.anti_replay_state_identity_v1()
        record = self._authorized.pop(evidence, None)
        if record is not None:
            self._consumed.add(evidence)
            self._consumed_epoch += 1
        after = self.anti_replay_state_identity_v1()
        return record, before, after

    def verify_and_consume_advance_authorization_v1(
        self,
        advance_input: c8.VirtualTimeAdvanceInputV1,
        expected_request_binding_identity: str,
    ) -> bool:
        record, before, after = self._consume(
            advance_input.authentication_evidence_identity
        )
        accepted = record == (
            "ADVANCE",
            expected_request_binding_identity,
            expected_request_binding_identity,
        )
        if accepted:
            self.advance_lineage.append(
                _auth_lineage_record(
                    authority_kind="ADVANCE",
                    step_index=advance_input.input_seq,
                    authorization_evidence_identity=(
                        advance_input.authentication_evidence_identity
                    ),
                    bound_input_or_action_identity=advance_input.input_identity,
                    expected_binding_identity=expected_request_binding_identity,
                    ledger_before_identity=before,
                    ledger_after_identity=after,
                )
            )
        return accepted

    def verify_and_consume_timeout_action_authorization_v1(
        self,
        signed_action_id: str,
        authorization_evidence_identity: str,
        expected_request_binding_identity: str,
    ) -> bool:
        record, before, after = self._consume(authorization_evidence_identity)
        accepted = (
            record is not None
            and record[0] == "TIMEOUT_ACTION"
            and record[1] == signed_action_id
        )
        if accepted:
            self.timeout_lineage.append(
                _auth_lineage_record(
                    authority_kind="TIMEOUT_ACTION",
                    step_index=len(self.timeout_lineage) + 1,
                    authorization_evidence_identity=authorization_evidence_identity,
                    bound_input_or_action_identity=(
                        ctl.signed_action_id_commitment_v1(signed_action_id)
                    ),
                    expected_binding_identity=expected_request_binding_identity,
                    ledger_before_identity=before,
                    ledger_after_identity=after,
                )
            )
        return accepted

    def revoke_unconsumed(self, evidence: str) -> bool:
        if self._authorized.pop(evidence, None) is None:
            return False
        self._revoked.add(evidence)
        return True


class _ReplayPublicAuthorityAdapter:
    """Public-only deterministic oracle used by both record and cold replay."""

    def __init__(
        self,
        runtime: rt.C8TimedSessionRuntimeV1,
        authenticator: _ReplayAuthenticator,
        initial: C8ReplayInitialMaterialV1,
    ) -> None:
        self.runtime = runtime
        self.authenticator = authenticator
        self.initial = initial
        self.ref: rt.WindowAuthorityRefV1 | None = None
        self.resolution_index = -1
        self.families_by_step: tuple[tuple[str, ...], ...] = ()
        self.completion_by_step: tuple[bool, ...] = ()
        self.fetch_index = 0
        self.issue_index = 0
        self.current_snapshot: ctl.AdapterPublicLegalActionsSnapshotV1 | None = None
        self.legal_snapshots: list[ctl.AdapterPublicLegalActionsSnapshotV1] = []
        self.issuances: list[ctl.SignedActionIssuanceEvidenceV1] = []
        self.callback_entries: list[dict[str, object]] = []
        self._confirmed: set[str] = set()
        self._invalidated: set[str] = set()
        self._external_capabilities: dict[int, tuple[object, str]] = {}

    def configure(
        self,
        *,
        ref: rt.WindowAuthorityRefV1,
        resolution_index: int,
        families_by_step: tuple[tuple[str, ...], ...],
        completion_by_step: tuple[bool, ...],
    ) -> None:
        self.ref = ref
        self.resolution_index = resolution_index
        self.families_by_step = families_by_step
        self.completion_by_step = completion_by_step
        self.fetch_index = 0
        self.issue_index = 0
        self.current_snapshot = None

    def _active_ref(self) -> rt.WindowAuthorityRefV1:
        if self.ref is None:
            raise C8ReplayError("adapter resolution ref missing")
        return self.ref

    def _security_ledger_identity(self) -> str:
        return _identity(
            {
                "schema": "sgs-c8-d-synthetic-issuance-ledger-v1",
                "confirmed": sorted(self._confirmed),
                "invalidated": sorted(self._invalidated),
            }
        )

    def _guard_entry(self, kind: str, step_index: int) -> None:
        audit = self.runtime.controller_callback_security_audit_v1()
        if not audit.guard_active:
            raise C8ReplayError("adapter callback未在C8-B trusted guard内")
        state = self.runtime.state
        active = state.virtual_time_state.window_stack.active_window
        pending = state.pending_deadline
        ref = self._active_ref()
        if active is None or pending is None:
            raise C8ReplayError("guarded timeout callback缺少active/pending lineage")
        commitment = rt.TimeoutDueCommitmentV1.build(
            state=state,
            ref=ref,
            active=active,
            pending=pending,
        )
        self.callback_entries.append(
            {
                "callback_kind": kind,
                "resolution_index": self.resolution_index,
                "step_index": step_index,
                "entry_audit": audit.to_dict(),
                "outer_state_identity": state.state_identity,
                "runtime_instance_identity": state.runtime_instance_identity,
                "controller_identity": self.initial.controller_instance_identity,
                "adapter_identity": state.inner_adapter_identity,
                "window_authority_ref_identity": ref.authority_ref_identity,
                "window_id": active.window_id,
                "timeout_due_commitment_identity": commitment.commitment_identity,
                "pending_deadline_identity": pending.pending_identity,
            }
        )

    def current_adapter_identity_v1(self) -> str:
        return self.runtime.state.inner_adapter_identity

    def current_session_identity_v1(self) -> str:
        return self.runtime.state.inner_session_binding_identity

    def current_controller_identity_v1(self) -> str:
        return self.initial.controller_instance_identity

    def current_public_state_identity_v1(self) -> str:
        return self.runtime.state.inner_public_state_identity

    def current_authoritative_state_identity_v1(self) -> str:
        return self.runtime.state.inner_authoritative_state_identity

    def current_issuance_authority_identity_v1(self) -> str:
        return self.runtime.state.input_authenticator_identity

    def current_issuance_security_ledger_identity_v1(self) -> str:
        return self._security_ledger_identity()

    def current_consumed_authorization_ledger_identity_v1(self) -> str:
        return self.authenticator.anti_replay_state_identity_v1()

    def current_public_legal_set_snapshot_identity_v1(self) -> str:
        if self.current_snapshot is None:
            return _identity(
                {
                    "schema": "sgs-c8-d-no-current-legal-snapshot-v1",
                    "resolution_index": self.resolution_index,
                }
            )
        return self.current_snapshot.snapshot_identity

    def current_canonical_public_ordering_identity_v1(self) -> str:
        if self.current_snapshot is None:
            return _identity(
                {
                    "schema": "sgs-c8-d-no-current-ordering-v1",
                    "resolution_index": self.resolution_index,
                }
            )
        return self.current_snapshot.canonical_public_ordering_identity

    def fresh_public_legal_actions_v1(
        self,
    ) -> ctl.AdapterPublicLegalActionsSnapshotV1:
        step = self.fetch_index
        self._guard_entry("LEGAL_SET", step + 1)
        if step >= len(self.families_by_step):
            raise C8ReplayError("adapter script exhausted legal-set steps")
        active = self.runtime.state.virtual_time_state.window_stack.active_window
        if active is None:
            raise C8ReplayError("adapter legal-set requires active window")
        candidates = tuple(
            c8.PublicLegalActionCandidateV1.build(
                window_id=active.window_id,
                actor_id=active.actor_id,
                decision_identity=active.decision_identity,
                obligation_identity=active.obligation_identity,
                public_ordinal=ordinal,
                action_id=(
                    f"c8-d-public-r{self.resolution_index}-s{step + 1}-o{ordinal}"
                ),
                action_family=c8.PublicActionFamilyV1(family),
            )
            for ordinal, family in enumerate(self.families_by_step[step])
        )
        public_set = c8.PublicLegalSetProjectionV1.build(
            window_id=active.window_id,
            actor_id=active.actor_id,
            decision_identity=active.decision_identity,
            obligation_identity=active.obligation_identity,
            actions=candidates,
            ordering_contract_id=c8.PUBLIC_ORDERING_CONTRACT_ID,
        )
        ref = self._active_ref()
        snapshot = ctl.build_adapter_public_legal_actions_snapshot_v1(
            public_legal_set=public_set,
            runtime_instance_identity=self.runtime.state.runtime_instance_identity,
            window_authority_ref_identity=ref.authority_ref_identity,
            session_identity=self.runtime.state.inner_session_binding_identity,
            controller_identity=self.initial.controller_instance_identity,
            adapter_identity=self.runtime.state.inner_adapter_identity,
            public_state_identity=self.runtime.state.inner_public_state_identity,
            authoritative_state_identity=(
                self.runtime.state.inner_authoritative_state_identity
            ),
            issuance_security_ledger_identity=self._security_ledger_identity(),
        )
        self.fetch_index += 1
        self.current_snapshot = snapshot
        self.legal_snapshots.append(snapshot)
        return snapshot

    def confirm_and_issue_signed_action_v1(
        self,
        candidate_reference: str,
        public_ordinal: int,
        legal_set_identity: str,
        timeout_auth_binding: str,
        timeout_due_commitment_identity: str,
    ) -> ctl.SignedActionIssuanceEvidenceV1:
        step = self.issue_index
        self._guard_entry("ISSUANCE", step + 1)
        snapshot = self.current_snapshot
        if snapshot is None:
            raise C8ReplayError("issuance missing current legal snapshot")
        matches = tuple(
            candidate
            for candidate in snapshot.public_legal_set.actions
            if candidate.action_id == candidate_reference
            and candidate.public_ordinal == public_ordinal
        )
        if len(matches) != 1:
            raise C8ReplayError("issuance candidate不是current unique member")
        candidate = matches[0]
        signed_action_id = (
            f"c8-d-signed-r{self.resolution_index}-s{step + 1}-o{public_ordinal}"
        )
        ledger_before = self._security_ledger_identity()
        evidence = self.authenticator.authorize_timeout_action(
            signed_action_id, timeout_auth_binding
        )
        self._confirmed.add(evidence)
        ledger_after = self._security_ledger_identity()
        external_capability = object()
        external_capability_identity = _identity(
            {
                "schema": "sgs-c8-d-external-capability-commitment-v1",
                "resolution_index": self.resolution_index,
                "step_index": step + 1,
                "authorization_evidence_identity": evidence,
            }
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
            issuance_authority_identity=self.runtime.state.input_authenticator_identity,
            authorization_evidence_identity=evidence,
            runtime_instance_identity=self.runtime.state.runtime_instance_identity,
            window_authority_ref_identity=self._active_ref().authority_ref_identity,
            window_id=self._active_ref().window_id,
            session_identity=self.runtime.state.inner_session_binding_identity,
            controller_identity=self.initial.controller_instance_identity,
            adapter_identity=self.runtime.state.inner_adapter_identity,
            public_state_identity=snapshot.public_state_identity,
            authoritative_state_identity=snapshot.authoritative_state_identity,
            issuance_security_ledger_before_identity=ledger_before,
            issuance_security_ledger_after_identity=ledger_after,
            obligation_completed=self.completion_by_step[step],
            external_capability=external_capability,
        )
        self._external_capabilities[id(external_capability)] = (
            external_capability,
            evidence,
        )
        self.issue_index += 1
        self.issuances.append(issuance)
        return issuance

    def abort_pending_issuance_v1(
        self, external_capability: object
    ) -> ctl.UnforwardedIssuanceInvalidationEvidenceV1:
        self._guard_entry("ISSUANCE", self.issue_index + 1)
        record = self._external_capabilities.pop(id(external_capability), None)
        if record is None or record[0] is not external_capability:
            raise C8ReplayError("unknown external capability")
        issuance = next(
            item
            for item in self.issuances
            if item.authorization_evidence_identity == record[1]
        )
        before = self._security_ledger_identity()
        if not self.authenticator.revoke_unconsumed(record[1]):
            raise C8ReplayError("external capability no longer pending")
        self._invalidated.add(record[1])
        after = self._security_ledger_identity()
        return ctl.build_unforwarded_issuance_invalidation_evidence_v1(
            issuance_identity=issuance.issuance_identity,
            authorization_evidence_identity=issuance.authorization_evidence_identity,
            runtime_instance_identity=issuance.runtime_instance_identity,
            window_authority_ref_identity=issuance.window_authority_ref_identity,
            session_identity=issuance.session_identity,
            controller_identity=issuance.controller_identity,
            adapter_identity=issuance.adapter_identity,
            security_ledger_before_identity=before,
            security_ledger_after_identity=after,
            invalidated=True,
        )

    def recover_failed_issuance_attempt_v1(self, **_: object) -> object:
        raise C8ReplayError("committed replay scope does not admit failed issuance")


def _derive_bound_envelope(
    snapshot: ctl.AdapterPublicLegalActionsSnapshotV1,
    commitment: rt.TimeoutDueCommitmentV1,
    ref: rt.WindowAuthorityRefV1,
) -> ctl.FreshPublicLegalActionsEnvelopeV1:
    candidate_bindings = tuple(
        (
            candidate.candidate_identity,
            candidate.action_id,
            ctl.timeout_issuance_request_binding_v1(
                timeout_due_commitment_identity=commitment.commitment_identity,
                runtime_instance_identity=commitment.runtime_instance_identity,
                window_authority_ref_identity=ref.authority_ref_identity,
                session_identity=snapshot.session_identity,
                controller_identity=snapshot.controller_identity,
                adapter_identity=snapshot.adapter_identity,
                projection_legal_set_identity=(
                    snapshot.projection_legal_set_identity
                ),
                adapter_legal_set_snapshot_identity=snapshot.snapshot_identity,
                canonical_public_ordering_identity=(
                    snapshot.canonical_public_ordering_identity
                ),
                candidate=candidate,
            ),
        )
        for candidate in snapshot.public_legal_set.actions
    )
    bindings_identity = ctl.timeout_authentication_bindings_identity_v1(
        snapshot.public_legal_set, candidate_bindings
    )
    return ctl.build_fresh_public_legal_actions_envelope_v1(
        public_legal_set=snapshot.public_legal_set,
        adapter_legal_set_snapshot_identity=snapshot.snapshot_identity,
        timeout_authentication_bindings_identity=bindings_identity,
        timeout_due_commitment_identity=commitment.commitment_identity,
        runtime_contract_identity=commitment.runtime_contract_identity,
        runtime_instance_identity=commitment.runtime_instance_identity,
        window_authority_ref_identity=ref.authority_ref_identity,
        session_identity=snapshot.session_identity,
        controller_identity=snapshot.controller_identity,
        adapter_identity=snapshot.adapter_identity,
        public_state_identity=snapshot.public_state_identity,
        authoritative_state_identity=snapshot.authoritative_state_identity,
        issuance_security_ledger_identity=(
            snapshot.issuance_security_ledger_identity
        ),
    )


def _derive_guard_evidence(
    entry: Mapping[str, object],
    inner: _ReplayInnerAdapter,
) -> dict[str, object]:
    entry_audit = _exact_dict(_plain(entry["entry_audit"]), "entry audit")
    entry_epoch = _integer(
        entry_audit["operation_attempt_epoch"], "guard entry epoch", minimum=1
    )
    lease_epoch = entry_epoch - 1
    lease_probe = inner.audit_by_epoch.get(lease_epoch)
    if lease_probe is None:
        raise C8ReplayError("missing public audit observation for lease issue")
    lease_audit = _exact_dict(
        _plain(lease_probe["audit"]), "lease issue audit"
    )
    generation = _integer(
        lease_audit["next_guard_generation"], "lease generation"
    )
    if entry_audit["next_guard_generation"] != generation + 1:
        raise C8ReplayError("guard generation lineage mismatch")
    runtime_instance = _sha256(
        entry_audit["runtime_instance_identity"], "runtime_instance_identity"
    )
    state_identity = _sha256(
        entry["outer_state_identity"], "outer_state_identity"
    )
    ref_identity = _sha256(
        entry["window_authority_ref_identity"], "window_authority_ref_identity"
    )
    commitment_identity = _sha256(
        entry["timeout_due_commitment_identity"],
        "timeout_due_commitment_identity",
    )
    pending_identity = _sha256(
        entry["pending_deadline_identity"], "pending_deadline_identity"
    )
    controller_identity = _sha256(
        entry["controller_identity"], "controller_identity"
    )
    adapter_identity = _sha256(entry["adapter_identity"], "adapter_identity")
    lease_tip = _sha256(
        lease_audit["operation_attempt_chain_tip"],
        "lease operation attempt chain tip",
    )
    entry_tip = _sha256(
        entry_audit["operation_attempt_chain_tip"],
        "guard entry operation attempt chain tip",
    )
    lease_nonce = _identity(
        {
            "schema": "sgs-c8-b-controller-callback-lease-v1",
            "runtime_contract_identity": rt.C8_B_RUNTIME_CONTRACT_IDENTITY_V1,
            "runtime_instance_identity": runtime_instance,
            "controller_identity": controller_identity,
            "adapter_identity": adapter_identity,
            "window_authority_ref_identity": ref_identity,
            "timeout_due_commitment_identity": commitment_identity,
            "pending_deadline_identity": pending_identity,
            "lease_generation": generation,
            "operation_attempt_epoch_at_issue": lease_epoch,
            "operation_attempt_chain_tip_at_issue": lease_tip,
        }
    )
    lease_material = {
        "schema": "sgs-c8-b-controller-callback-lease-v1",
        "contract_version": 1,
        "runtime_contract_identity": rt.C8_B_RUNTIME_CONTRACT_IDENTITY_V1,
        "runtime_instance_identity": runtime_instance,
        "controller_identity": controller_identity,
        "adapter_identity": adapter_identity,
        "window_authority_ref_identity": ref_identity,
        "window_id": entry["window_id"],
        "timeout_due_commitment_identity": commitment_identity,
        "pending_deadline_identity": pending_identity,
        "outer_state_identity_at_issue": state_identity,
        "lease_generation": generation,
        "operation_attempt_epoch_at_issue": lease_epoch,
        "lease_nonce_identity": lease_nonce,
        "live_owner_guard_bound": True,
        "serializable_authority": False,
    }
    lease_identity = _identity(lease_material)
    guard_nonce = _identity(
        {
            "schema": "sgs-c8-b-controller-callback-guard-v1",
            "runtime_contract_identity": rt.C8_B_RUNTIME_CONTRACT_IDENTITY_V1,
            "runtime_instance_identity": runtime_instance,
            "lease_identity": lease_identity,
            "guard_generation": generation,
            "operation_attempt_epoch_at_entry": entry_epoch,
            "operation_attempt_chain_tip_at_entry": entry_tip,
        }
    )
    guard_material = {
        "schema": "sgs-c8-b-controller-callback-guard-v1",
        "contract_version": 1,
        "runtime_contract_identity": rt.C8_B_RUNTIME_CONTRACT_IDENTITY_V1,
        "runtime_instance_identity": runtime_instance,
        "controller_identity": controller_identity,
        "adapter_identity": adapter_identity,
        "window_authority_ref_identity": ref_identity,
        "window_id": entry["window_id"],
        "timeout_due_commitment_identity": commitment_identity,
        "pending_deadline_identity": pending_identity,
        "lease_identity": lease_identity,
        "guard_generation": generation,
        "guard_nonce_identity": guard_nonce,
        "operation_attempt_epoch_at_entry": entry_epoch,
        "operation_attempt_chain_tip_at_entry": entry_tip,
        "outer_state_identity_at_entry": state_identity,
        "live_owner_guard_bound": True,
        "serializable_authority": False,
    }
    guard_identity = _identity(guard_material)
    result_material = {
        "schema": "sgs-c8-b-controller-callback-guard-result-v1",
        "contract_version": 1,
        "runtime_contract_identity": rt.C8_B_RUNTIME_CONTRACT_IDENTITY_V1,
        "runtime_instance_identity": runtime_instance,
        "controller_identity": controller_identity,
        "adapter_identity": adapter_identity,
        "window_authority_ref_identity": ref_identity,
        "window_id": entry["window_id"],
        "timeout_due_commitment_identity": commitment_identity,
        "pending_deadline_identity": pending_identity,
        "lease_identity": lease_identity,
        "guard_generation": generation,
        "guard_identity": guard_identity,
        "operation_attempt_epoch_at_entry": entry_epoch,
        "operation_attempt_epoch_at_exit": entry_epoch,
        "operation_attempt_chain_tip_at_entry": entry_tip,
        "operation_attempt_chain_tip_at_exit": entry_tip,
        "outer_state_identity_at_entry": state_identity,
        "outer_state_identity_at_exit": state_identity,
        "callback_completed": True,
        "live_owner_guard_bound": True,
        "serializable_authority": False,
    }
    evidence: dict[str, object] = {
        "schema": "sgs-c8-d-callback-guard-evidence-v1",
        "contract_version": 1,
        "callback_kind": entry["callback_kind"],
        "resolution_index": entry["resolution_index"],
        "step_index": entry["step_index"],
        "runtime_instance_identity": runtime_instance,
        "controller_identity": controller_identity,
        "adapter_identity": adapter_identity,
        "window_authority_ref_identity": ref_identity,
        "window_id": entry["window_id"],
        "timeout_due_commitment_identity": commitment_identity,
        "pending_deadline_identity": pending_identity,
        "lease_generation": generation,
        "lease_operation_attempt_epoch": lease_epoch,
        "lease_operation_attempt_chain_tip": lease_tip,
        "lease_identity": lease_identity,
        "guard_entry_operation_attempt_epoch": entry_epoch,
        "guard_entry_operation_attempt_chain_tip": entry_tip,
        "guard_identity": guard_identity,
        "guard_result_identity": _identity(result_material),
        "outer_state_identity": state_identity,
        "callback_completed": True,
        "serialized_live_authority": False,
    }
    evidence["evidence_identity"] = _identity(evidence)
    return evidence


def _derive_capability_identity(
    *,
    capability_generation: int,
    guard_evidence: Mapping[str, object],
    issuance: ctl.SignedActionIssuanceEvidenceV1,
    commitment: rt.TimeoutDueCommitmentV1,
    auth_ledger_at_issue: str,
) -> tuple[str, int]:
    operation_epoch = _integer(
        guard_evidence["guard_entry_operation_attempt_epoch"],
        "guard entry epoch",
        minimum=1,
    ) + 1
    ownership_nonce = _identity(
        {
            "schema": "sgs-c8-b-pending-timeout-issuance-capability-v1",
            "runtime_contract_identity": rt.C8_B_RUNTIME_CONTRACT_IDENTITY_V1,
            "runtime_instance_identity": commitment.runtime_instance_identity,
            "guard_result_identity": guard_evidence["guard_result_identity"],
            "signed_action_id_commitment": issuance.signed_action_id_commitment,
            "external_capability_identity": issuance.external_capability_identity,
            "authorization_ledger_identity_at_issue": auth_ledger_at_issue,
            "capability_generation": capability_generation,
            "operation_attempt_epoch_at_issue": operation_epoch,
        }
    )
    capability_material = {
        "schema": "sgs-c8-b-pending-timeout-issuance-capability-v1",
        "contract_version": 1,
        "runtime_contract_identity": rt.C8_B_RUNTIME_CONTRACT_IDENTITY_V1,
        "runtime_instance_identity": commitment.runtime_instance_identity,
        "controller_identity": issuance.controller_identity,
        "adapter_identity": issuance.adapter_identity,
        "window_authority_ref_identity": commitment.window_authority_ref_identity,
        "window_id": commitment.window_id,
        "timeout_due_commitment_identity": commitment.commitment_identity,
        "pending_deadline_identity": commitment.pending_deadline_identity,
        "signed_action_id_commitment": issuance.signed_action_id_commitment,
        "external_capability_identity": issuance.external_capability_identity,
        "authorization_ledger_identity_at_issue": auth_ledger_at_issue,
        "guard_result_identity": guard_evidence["guard_result_identity"],
        "capability_generation": capability_generation,
        "operation_attempt_epoch_at_issue": operation_epoch,
        "ownership_nonce_identity": ownership_nonce,
        "live_owner_guard_bound": True,
        "serializable_authority": False,
    }
    capability_identity = _identity(capability_material)
    return capability_identity, operation_epoch


def _derive_capability_evidence(
    *,
    step_index: int,
    capability_generation: int,
    guard_evidence: Mapping[str, object],
    issuance: ctl.SignedActionIssuanceEvidenceV1,
    commitment: rt.TimeoutDueCommitmentV1,
    auth_ledger_at_issue: str,
    receipt_identity: str,
) -> tuple[dict[str, object], str]:
    capability_identity, operation_epoch = _derive_capability_identity(
        capability_generation=capability_generation,
        guard_evidence=guard_evidence,
        issuance=issuance,
        commitment=commitment,
        auth_ledger_at_issue=auth_ledger_at_issue,
    )
    evidence: dict[str, object] = {
        "schema": "sgs-c8-d-capability-lifecycle-evidence-v1",
        "contract_version": 1,
        "step_index": step_index,
        "runtime_instance_identity": commitment.runtime_instance_identity,
        "controller_identity": issuance.controller_identity,
        "adapter_identity": issuance.adapter_identity,
        "window_authority_ref_identity": commitment.window_authority_ref_identity,
        "window_id": commitment.window_id,
        "timeout_due_commitment_identity": commitment.commitment_identity,
        "pending_deadline_identity": commitment.pending_deadline_identity,
        "signed_action_id_commitment": issuance.signed_action_id_commitment,
        "external_capability_identity": issuance.external_capability_identity,
        "authorization_ledger_identity_at_issue": auth_ledger_at_issue,
        "guard_result_identity": guard_evidence["guard_result_identity"],
        "capability_generation": capability_generation,
        "operation_attempt_epoch_at_issue": operation_epoch,
        "capability_identity": capability_identity,
        "ownership_status_lineage": [
            "CONTROLLER_OWNED_PENDING",
            "AUTH_EVIDENCE_CONSUMED",
            "RECEIPT_COMMITTED_CONSUMED",
        ],
        "committed_receipt_identity": receipt_identity,
        "aborted": False,
        "consumed": True,
        "serialized_live_authority": False,
    }
    evidence["evidence_identity"] = _identity(evidence)
    return evidence, capability_identity


def _receipt_chain_genesis(runtime_instance_identity: str) -> str:
    return _identity(
        {
            "runtime_contract_identity": rt.C8_B_RUNTIME_CONTRACT_IDENTITY_V1,
            "runtime_instance_identity": runtime_instance_identity,
            "chain": "TIMEOUT_EXECUTION_RECEIPT_GENESIS",
        }
    )


def c8_replay_identity_v1(value: object) -> str:
    """Return the canonical SHA-256 used by the replay evidence contract."""

    return _identity(value)


def _state_dict(runtime: rt.C8TimedSessionRuntimeV1) -> dict[str, object]:
    return runtime.state.to_dict()


def _projection_dict(runtime: rt.C8TimedSessionRuntimeV1) -> dict[str, object]:
    return runtime.public_projection().to_dict()


class _ReplayExecution:
    """One isolated deterministic A/B/C execution; never constructed from evidence."""

    def __init__(self, initial: C8ReplayInitialMaterialV1) -> None:
        self.initial = initial
        self.inner = _ReplayInnerAdapter(initial)
        self.authenticator = _ReplayAuthenticator(initial)
        self.runtime = rt.C8TimedSessionRuntimeV1(
            inner_adapter=self.inner,
            input_authenticator=self.authenticator,
            instance_nonce_identity=initial.instance_nonce_identity,
            input_source_id=initial.input_source_id,
            driver_authority_identity=initial.driver_authority_identity,
        )
        self.inner.bind_runtime(self.runtime)
        self.adapter = _ReplayPublicAuthorityAdapter(
            self.runtime, self.authenticator, initial
        )
        self.controller = ctl.TimeoutResolverControllerIntegrationV1(
            self.runtime,
            self.adapter,
            controller_instance_identity=initial.controller_instance_identity,
        )
        self.refs: dict[str, rt.WindowAuthorityRefV1] = {}
        self.receipt_sequence = 0
        self.previous_receipt_identity = _receipt_chain_genesis(
            self.runtime.state.runtime_instance_identity
        )
        self.capability_generation = 0

    def _active_ref_for(self, window_key: str) -> rt.WindowAuthorityRefV1:
        ref = self.refs.get(window_key)
        if ref is None:
            raise C8ReplayError(f"unknown window_key: {window_key}")
        active = self.runtime.active_window_ref()
        if active != ref:
            raise C8ReplayError(f"window_key不是current active window: {window_key}")
        return ref

    @staticmethod
    def _base_record(
        command: C8ReplayCommandV1,
        *,
        pre_state: Mapping[str, object],
        pre_projection: Mapping[str, object],
        pre_audit: Mapping[str, object],
    ) -> dict[str, object]:
        return {
            "schema": "sgs-c8-d-command-execution-record-v1",
            "contract_version": 1,
            "command_index": command.command_index,
            "command_identity": command.command_identity,
            "command_kind": command.command_kind.value,
            "pre_outer_state": dict(pre_state),
            "post_outer_state": {},
            "pre_public_projection": dict(pre_projection),
            "post_public_projection": {},
            "pre_security_audit": dict(pre_audit),
            "post_security_audit": {},
            "window_ref": None,
            "advance_input": None,
            "accepted_input": None,
            "derived_deadline": None,
            "timeout_due_commitments": [],
            "legal_snapshots": [],
            "bound_legal_sets": [],
            "issuances": [],
            "callback_guards": [],
            "capability_transitions": [],
            "receipts": [],
            "auth_lineage": [],
            "controller_result": None,
            "controller_events": [],
        }

    def _finish_record(self, record: dict[str, object]) -> dict[str, object]:
        record["post_outer_state"] = _state_dict(self.runtime)
        record["post_public_projection"] = _projection_dict(self.runtime)
        record["post_security_audit"] = _security_audit_dict(
            self.runtime.controller_callback_security_audit_v1()
        )
        record["record_identity"] = _identity(record)
        _validate_command_record(record)
        return record

    def _open(
        self, command: C8ReplayCommandV1, record: dict[str, object]
    ) -> dict[str, object]:
        if command.window_key in self.refs:
            raise C8ReplayError(f"window_key重复: {command.window_key}")
        parent_ref = (
            None
            if command.parent_window_key is None
            else self._active_ref_for(command.parent_window_key)
        )
        ref = self.runtime.open_window(
            actor_id=command.actor_id,
            window_kind=c8.TimedWindowKindV1(command.window_kind),
            decision_identity=command.decision_identity,
            obligation_identity=command.obligation_identity,
            expected_parent_ref=parent_ref,
        )
        self.refs[command.window_key] = ref
        record["window_ref"] = ref.to_dict()
        return self._finish_record(record)

    def _advance(
        self, command: C8ReplayCommandV1, record: dict[str, object]
    ) -> dict[str, object]:
        ref = self._active_ref_for(command.window_key)
        requested_tick = _integer(command.requested_tick, "requested_tick")
        state = self.runtime.state
        binding = self.runtime.expected_advance_authentication_binding(
            requested_tick=requested_tick
        )
        evidence = self.authenticator.authorize_advance(binding)
        advance_input = c8.VirtualTimeAdvanceInputV1.issue(
            input_seq=state.virtual_time_state.next_input_seq,
            source_id=state.input_source_id,
            domain_id=c8.CLOCK_DOMAIN_ID,
            window_id=ref.window_id,
            requested_tick=requested_tick,
            authentication_evidence_identity=evidence,
        )
        lineage_start = len(self.authenticator.advance_lineage)
        result = self.runtime.ingest_virtual_time_input(
            advance_input,
            expected_previous_input_chain_tip=state.input_chain_tip,
            duration_profile_identity=c8.ENGINEERING_TEST_PROFILE_V1.profile_identity,
        )
        lineage = self.authenticator.advance_lineage[lineage_start:]
        if len(lineage) != 1:
            raise C8ReplayError("fresh advance未产生唯一external auth lineage")
        accepted = self.runtime.state.input_records[-1]
        record.update(
            {
                "window_ref": ref.to_dict(),
                "advance_input": advance_input.to_dict(),
                "accepted_input": accepted.to_dict(),
                "derived_deadline": (
                    None
                    if result.derived_deadline is None
                    else result.derived_deadline.to_dict()
                ),
                "auth_lineage": lineage,
            }
        )
        return self._finish_record(record)

    def _rebuild_timeout_receipts(
        self,
        *,
        ref: rt.WindowAuthorityRefV1,
        result: ctl.TimeoutControllerResultV1,
        observations: Sequence[Mapping[str, object]],
        snapshots: Sequence[ctl.AdapterPublicLegalActionsSnapshotV1],
        issuances: Sequence[ctl.SignedActionIssuanceEvidenceV1],
        guard_entries: Sequence[Mapping[str, object]],
        auth_lineage: Sequence[Mapping[str, object]],
    ) -> tuple[
        list[rt.TimeoutDueCommitmentV1],
        list[ctl.FreshPublicLegalActionsEnvelopeV1],
        list[dict[str, object]],
        list[dict[str, object]],
        list[rt.TimeoutActionExecutionReceiptV1],
    ]:
        count = result.step_count
        if not (
            len(observations)
            == len(snapshots)
            == len(issuances)
            == len(auth_lineage)
            == count
            and len(guard_entries) == count * 2
        ):
            raise C8ReplayError("fresh controller per-step observation count mismatch")
        commitments: list[rt.TimeoutDueCommitmentV1] = []
        envelopes: list[ctl.FreshPublicLegalActionsEnvelopeV1] = []
        guards: list[dict[str, object]] = []
        capabilities: list[dict[str, object]] = []
        receipts: list[rt.TimeoutActionExecutionReceiptV1] = []
        for index in range(count):
            observation = observations[index]
            pre_state = observation["pre_outer_state"]
            if type(pre_state) is not rt.TimedSessionOuterStateV1:
                raise C8ReplayError("inner observation outer-state type drift")
            active = pre_state.virtual_time_state.window_stack.active_window
            pending = pre_state.pending_deadline
            if active is None or pending is None:
                raise C8ReplayError("timeout observation缺少active/pending state")
            commitment = rt.TimeoutDueCommitmentV1.build(
                state=pre_state,
                ref=ref,
                active=active,
                pending=pending,
            )
            snapshot = snapshots[index]
            issuance = issuances[index]
            envelope = _derive_bound_envelope(snapshot, commitment, ref)
            legal_guard = _derive_guard_evidence(
                guard_entries[index * 2], self.inner
            )
            issuance_guard = _derive_guard_evidence(
                guard_entries[index * 2 + 1], self.inner
            )
            if (
                legal_guard["callback_kind"] != "LEGAL_SET"
                or issuance_guard["callback_kind"] != "ISSUANCE"
            ):
                raise C8ReplayError("callback guard order不是LEGAL_SET then ISSUANCE")
            lineage = auth_lineage[index]
            ledger_before = _sha256(
                lineage["ledger_before_identity"], "timeout auth ledger before"
            )
            ledger_after = _sha256(
                lineage["ledger_after_identity"], "timeout auth ledger after"
            )
            capability_identity, _ = _derive_capability_identity(
                capability_generation=self.capability_generation,
                guard_evidence=issuance_guard,
                issuance=issuance,
                commitment=commitment,
                auth_ledger_at_issue=ledger_before,
            )
            authorization_binding = (
                rt.derive_timeout_action_authorization_binding_v1(
                    timeout_due_commitment=commitment,
                    signed_action_id=issuance.signed_action_id,
                    issuance_authority_identity=(
                        issuance.issuance_authority_identity
                    ),
                    previous_auth_ledger_identity=ledger_before,
                    receipt_sequence=self.receipt_sequence,
                    previous_receipt_identity=self.previous_receipt_identity,
                    pending_issuance_capability_identity=capability_identity,
                )
            )
            if lineage["expected_binding_identity"] != authorization_binding:
                raise C8ReplayError("fresh B authorization binding observation mismatch")
            transition_identity = _identity(
                {
                    "schema": "sgs-c8-b-timeout-inner-transition-commitment-v1",
                    "contract_version": 1,
                    "runtime_contract_identity": rt.C8_B_RUNTIME_CONTRACT_IDENTITY_V1,
                    "runtime_instance_identity": pre_state.runtime_instance_identity,
                    "window_ref_identity": ref.authority_ref_identity,
                    "timeout_due_commitment_identity": commitment.commitment_identity,
                    "pending_deadline_identity": pending.pending_identity,
                    "signed_action_id_commitment": (
                        issuance.signed_action_id_commitment
                    ),
                    "before_inner_public_state_identity": (
                        observation["pre_public_state_identity"]
                    ),
                    "after_inner_public_state_identity": (
                        observation["post_public_state_identity"]
                    ),
                    "before_inner_authoritative_state_identity": (
                        observation["pre_authoritative_state_identity"]
                    ),
                    "after_inner_authoritative_state_identity": (
                        observation["post_authoritative_state_identity"]
                    ),
                    "inner_adapter_identity": pre_state.inner_adapter_identity,
                    "inner_session_binding_identity": (
                        pre_state.inner_session_binding_identity
                    ),
                    "authorization_binding_identity": authorization_binding,
                    "authorization_evidence_identity": (
                        issuance.authorization_evidence_identity
                    ),
                    "authorization_ledger_after_identity": ledger_after,
                    "pending_issuance_capability_identity": capability_identity,
                }
            )
            receipt = rt.TimeoutActionExecutionReceiptV1.build(
                runtime_instance_identity=pre_state.runtime_instance_identity,
                receipt_sequence=self.receipt_sequence,
                previous_receipt_identity=self.previous_receipt_identity,
                ref=ref,
                signed_action_id_commitment=issuance.signed_action_id_commitment,
                pre_inner_public_state_identity=(
                    observation["pre_public_state_identity"]
                ),
                pre_inner_authoritative_state_identity=(
                    observation["pre_authoritative_state_identity"]
                ),
                post_inner_public_state_identity=(
                    observation["post_public_state_identity"]
                ),
                post_inner_authoritative_state_identity=(
                    observation["post_authoritative_state_identity"]
                ),
                inner_adapter_identity=pre_state.inner_adapter_identity,
                inner_session_binding_identity=pre_state.inner_session_binding_identity,
                issuance_authority_identity=issuance.issuance_authority_identity,
                authorization_evidence_identity=(
                    issuance.authorization_evidence_identity
                ),
                authorization_binding_identity=authorization_binding,
                authorization_ledger_before_identity=ledger_before,
                authorization_ledger_after_identity=ledger_after,
                timeout_due_commitment=commitment,
                outer_transition_identity=transition_identity,
                pending_issuance_capability_identity=capability_identity,
            )
            if receipt.receipt_identity != result.receipt_identities[index]:
                raise C8ReplayError("fresh reconstructed B receipt mismatch")
            capability, derived_capability_identity = _derive_capability_evidence(
                step_index=index + 1,
                capability_generation=self.capability_generation,
                guard_evidence=issuance_guard,
                issuance=issuance,
                commitment=commitment,
                auth_ledger_at_issue=ledger_before,
                receipt_identity=receipt.receipt_identity,
            )
            if derived_capability_identity != capability_identity:
                raise C8ReplayError("capability reconstruction drift")
            commitments.append(commitment)
            envelopes.append(envelope)
            guards.extend((legal_guard, issuance_guard))
            capabilities.append(capability)
            receipts.append(receipt)
            self.receipt_sequence += 1
            self.previous_receipt_identity = receipt.receipt_identity
            self.capability_generation += 1
        return commitments, envelopes, guards, capabilities, receipts

    def _resolve(
        self, command: C8ReplayCommandV1, record: dict[str, object]
    ) -> dict[str, object]:
        ref = self._active_ref_for(command.window_key)
        observation_start = len(self.inner.apply_observations)
        snapshot_start = len(self.adapter.legal_snapshots)
        issuance_start = len(self.adapter.issuances)
        guard_start = len(self.adapter.callback_entries)
        auth_start = len(self.authenticator.timeout_lineage)
        event_start = len(self.controller.public_event_trace_v1())
        commitment = self.runtime.current_timeout_due_commitment_v1(ref)
        self.adapter.configure(
            ref=ref,
            resolution_index=command.command_index,
            families_by_step=command.families_by_step,
            completion_by_step=command.completion_by_step,
        )
        result = self.controller.resolve_timeout_v1(
            ref, timeout_due_commitment=commitment
        )
        if result.result_kind not in {
            ctl.ControllerResultKindV1.RESOLVED_SINGLE.value,
            ctl.ControllerResultKindV1.RESOLVED_CHAIN.value,
        }:
            raise C8ReplayError(
                f"record scope only accepts committed resolution: {result.reason}"
            )
        observations = self.inner.apply_observations[observation_start:]
        snapshots = self.adapter.legal_snapshots[snapshot_start:]
        issuances = self.adapter.issuances[issuance_start:]
        guard_entries = self.adapter.callback_entries[guard_start:]
        auth_lineage = self.authenticator.timeout_lineage[auth_start:]
        commitments, envelopes, guards, capabilities, receipts = (
            self._rebuild_timeout_receipts(
                ref=ref,
                result=result,
                observations=observations,
                snapshots=snapshots,
                issuances=issuances,
                guard_entries=guard_entries,
                auth_lineage=auth_lineage,
            )
        )
        if commitments[0] != commitment:
            raise C8ReplayError("first controller commitment不是caller live commitment")
        events = self.controller.public_event_trace_v1()[event_start:]
        record.update(
            {
                "window_ref": ref.to_dict(),
                "timeout_due_commitments": [
                    item.to_dict() for item in commitments
                ],
                "legal_snapshots": [
                    _adapter_snapshot_dict(item) for item in snapshots
                ],
                "bound_legal_sets": [
                    _bound_legal_set_dict(item) for item in envelopes
                ],
                "issuances": [_issuance_dict(item) for item in issuances],
                "callback_guards": guards,
                "capability_transitions": capabilities,
                "receipts": [item.to_dict() for item in receipts],
                "auth_lineage": list(auth_lineage),
                "controller_result": result.to_public_dict_v1(),
                "controller_events": [item.to_public_dict_v1() for item in events],
            }
        )
        return self._finish_record(record)

    def run(
        self, commands: Sequence[C8ReplayCommandV1]
    ) -> C8ReplayExecutionEvidenceV1:
        initial_state = _state_dict(self.runtime)
        initial_projection = _projection_dict(self.runtime)
        initial_audit = _security_audit_dict(
            self.runtime.controller_callback_security_audit_v1()
        )
        initial_ledger = self.authenticator.anti_replay_state_identity_v1()
        records: list[dict[str, object]] = []
        for expected_index, command in enumerate(commands):
            if type(command) is not C8ReplayCommandV1:
                raise C8ReplayError("worker commands必须是strict typed values")
            if command.command_index != expected_index:
                raise C8ReplayError("worker command index drift")
            pre_state = _state_dict(self.runtime)
            pre_projection = _projection_dict(self.runtime)
            pre_audit = _security_audit_dict(
                self.runtime.controller_callback_security_audit_v1()
            )
            record = self._base_record(
                command,
                pre_state=pre_state,
                pre_projection=pre_projection,
                pre_audit=pre_audit,
            )
            if command.command_kind is C8ReplayCommandKindV1.OPEN_WINDOW:
                records.append(self._open(command, record))
            elif command.command_kind is C8ReplayCommandKindV1.ADVANCE_TIME:
                records.append(self._advance(command, record))
            else:
                records.append(self._resolve(command, record))
        event_trace = self.controller.public_event_trace_v1()
        material: dict[str, object] = {
            "schema": "sgs-c8-d-execution-evidence-v1",
            "contract_version": 1,
            "initial_outer_state": initial_state,
            "initial_public_projection": initial_projection,
            "initial_security_audit": initial_audit,
            "initial_authenticator_ledger_identity": initial_ledger,
            "command_records": records,
            "controller_event_trace": [
                item.to_public_dict_v1() for item in event_trace
            ],
            "final_outer_state": _state_dict(self.runtime),
            "final_public_projection": _projection_dict(self.runtime),
            "final_security_audit": _security_audit_dict(
                self.runtime.controller_callback_security_audit_v1()
            ),
            "final_authenticator_ledger_identity": (
                self.authenticator.anti_replay_state_identity_v1()
            ),
        }
        material["semantic_identity"] = _identity(
            _execution_semantic_material(material)
        )
        material["execution_identity"] = _identity(material)
        return C8ReplayExecutionEvidenceV1.from_dict(material)


_WORKER_FLAG: Final[str] = "--c8-d-isolated-worker-v1"
_WORKER_REQUEST_KEYS: Final[frozenset[str]] = frozenset(
    {"schema", "contract_version", "initial_material", "commands"}
)


def _execute_in_isolated_worker(
    initial: C8ReplayInitialMaterialV1,
    commands: Sequence[C8ReplayCommandV1],
) -> C8ReplayExecutionEvidenceV1:
    _assert_current_dependencies()
    request = {
        "schema": "sgs-c8-d-isolated-worker-request-v1",
        "contract_version": 1,
        "initial_material": initial.to_dict(),
        "commands": [item.to_dict() for item in commands],
    }
    from . import c8_timed_replay_version_compatibility_v1 as compatibility
    try:
        compatible_response = compatibility.d_reexecution_request_v1(request)
    except compatibility.C8CompatibilityError as exc:
        raise C8ReplayDivergenceError(str(exc)) from exc
    if compatible_response is not None:
        response = _exact_keys(compatible_response,
            frozenset({"schema", "contract_version", "execution_evidence"}), "compat worker response")
        if response["schema"] != "sgs-c8-d-isolated-worker-response-v1" or type(response["contract_version"]) is not int or response["contract_version"] != 1:
            raise C8ReplayError("compat worker response schema/version mismatch")
        return C8ReplayExecutionEvidenceV1.from_dict(response["execution_evidence"])
    environment = dict(os.environ)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["PYTHONHASHSEED"] = "0"
    completed = subprocess.run(
        [
            sys.executable,
            "-B",
            "-m",
            "scripts.sgs_engine.c8_strict_replay_v1",
            _WORKER_FLAG,
        ],
        input=_canonical_json_bytes(request),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=_repo_root(),
        env=environment,
        timeout=30,
        check=False,
    )
    if completed.returncode != 0:
        message = completed.stderr.decode("utf-8", errors="replace")[-2000:]
        raise C8ReplayDivergenceError(
            f"isolated C8-D worker failed ({completed.returncode}): {message}"
        )
    response = _strict_json_object(completed.stdout)
    response = _exact_keys(
        response,
        frozenset({"schema", "contract_version", "execution_evidence"}),
        "worker response",
    )
    if (
        response["schema"] != "sgs-c8-d-isolated-worker-response-v1"
        or response["contract_version"] != 1
    ):
        raise C8ReplayError("worker response schema/version mismatch")
    return C8ReplayExecutionEvidenceV1.from_dict(response["execution_evidence"])


def _build_replay(
    *,
    initial_material: C8ReplayInitialMaterialV1,
    commands: Sequence[C8ReplayCommandV1],
    evidence: C8ReplayExecutionEvidenceV1,
) -> C8StrictReplayV1:
    latch = C8DCurrentContractLatchV1.canonical()
    command_tuple = tuple(commands)
    public = _public_projection_from_execution(command_tuple, evidence)
    values: dict[str, object] = {
        "schema": C8_D_REPLAY_SCHEMA,
        "replay_version": C8_D_REPLAY_VERSION,
        "replay_id": C8_D_REPLAY_ID,
        "scope_marker": C8_D_SCOPE_MARKER,
        "production_adapter_integration": C8_D_PRODUCTION_ADAPTER_INTEGRATION,
        "full_game": C8_D_FULL_GAME,
        "recording_scope": C8_D_RECORDING_SCOPE,
        "current_contract_latch": latch,
        "c8_d_contract_identity": C8_D_CONTRACT_IDENTITY,
        "c8_d_development_identity": C8_D_DEVELOPMENT_IDENTITY,
        "c8_d_current_implementation_identity": (
            C8_D_CURRENT_IMPLEMENTATION_IDENTITY
        ),
        "initial_material": initial_material,
        "commands": command_tuple,
        "execution_evidence": evidence,
        "public_projection": _freeze(public),
    }
    identity_material = {
        "schema": values["schema"],
        "replay_version": values["replay_version"],
        "replay_id": values["replay_id"],
        "scope_marker": values["scope_marker"],
        "production_adapter_integration": values[
            "production_adapter_integration"
        ],
        "full_game": values["full_game"],
        "recording_scope": values["recording_scope"],
        "current_contract_latch": latch.to_dict(),
        "c8_d_contract_identity": values["c8_d_contract_identity"],
        "c8_d_development_identity": values["c8_d_development_identity"],
        "c8_d_current_implementation_identity": values[
            "c8_d_current_implementation_identity"
        ],
        "initial_material": initial_material.to_dict(),
        "commands": [item.to_dict() for item in command_tuple],
        "execution_evidence": evidence.to_dict(),
        "public_projection": public,
    }
    return C8StrictReplayV1(
        **values, replay_identity=_identity(identity_material)  # type: ignore[arg-type]
    )


def record_c8_timed_session_trace_v1(
    *,
    initial_material: C8ReplayInitialMaterialV1,
    commands: Sequence[C8ReplayCommandV1],
) -> C8StrictReplayV1:
    """Execute typed commands in a fresh process and record only derived evidence."""

    from . import c8_timed_replay_version_compatibility_v1 as compatibility

    if type(initial_material) is not C8ReplayInitialMaterialV1:
        raise C8ReplayError("record API requires typed canonical initial material")
    command_tuple = tuple(commands)
    if not command_tuple or any(type(item) is not C8ReplayCommandV1 for item in command_tuple):
        raise C8ReplayError("record API requires nonempty typed command sequence")
    compatibility.reject_recording_v1()
    evidence = _execute_in_isolated_worker(initial_material, command_tuple)
    return _build_replay(
        initial_material=initial_material,
        commands=command_tuple,
        evidence=evidence,
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class C8ReplayProofV1:
    schema: str
    contract_version: int
    status: str
    replay_identity: str
    recorded_execution_identity: str
    reexecuted_execution_identity: str
    semantic_identity: str
    public_projection_identity: str
    fresh_isolated_process: bool
    live_authority_reissued: bool
    serialized_authority_accepted: bool
    production_adapter_integration: str
    full_game: str
    proof_identity: str

    def __post_init__(self) -> None:
        material = self._material()
        if (
            self.schema != "sgs-c8-d-replay-proof-v1"
            or self.contract_version != 1
            or self.status != "MATCH"
            or self.fresh_isolated_process is not True
            or self.live_authority_reissued is not True
            or self.serialized_authority_accepted is not False
            or self.production_adapter_integration
            != C8_D_PRODUCTION_ADAPTER_INTEGRATION
            or self.full_game != C8_D_FULL_GAME
            or self.recorded_execution_identity
            != self.reexecuted_execution_identity
            or self.proof_identity != _identity(material)
        ):
            raise C8ReplayError("replay proof不是fresh-derived MATCH")
        for name in (
            "replay_identity",
            "recorded_execution_identity",
            "reexecuted_execution_identity",
            "semantic_identity",
            "public_projection_identity",
        ):
            _sha256(getattr(self, name), name)

    def _material(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "contract_version": self.contract_version,
            "status": self.status,
            "replay_identity": self.replay_identity,
            "recorded_execution_identity": self.recorded_execution_identity,
            "reexecuted_execution_identity": self.reexecuted_execution_identity,
            "semantic_identity": self.semantic_identity,
            "public_projection_identity": self.public_projection_identity,
            "fresh_isolated_process": self.fresh_isolated_process,
            "live_authority_reissued": self.live_authority_reissued,
            "serialized_authority_accepted": self.serialized_authority_accepted,
            "production_adapter_integration": self.production_adapter_integration,
            "full_game": self.full_game,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._material(), "proof_identity": self.proof_identity}


def _coerce_strict_replay(value: C8StrictReplayV1 | Mapping[str, object] | bytes | str) -> C8StrictReplayV1:
    if type(value) is C8StrictReplayV1:
        return C8StrictReplayV1.from_json_bytes(value.to_json_bytes())
    if type(value) is bytes or type(value) is str:
        return C8StrictReplayV1.from_json_bytes(value)
    if type(value) is dict:
        return C8StrictReplayV1.from_json_bytes(_canonical_json_bytes(value))
    raise C8ReplayError("strict replay input type drift")


def strict_reexecute_c8_replay_v1(
    value: C8StrictReplayV1 | Mapping[str, object] | bytes | str,
) -> C8ReplayProofV1:
    """Cold-load, fresh-reexecute, and byte-compare all authoritative evidence."""

    replay = _coerce_strict_replay(value)
    fresh = _execute_in_isolated_worker(replay.initial_material, replay.commands)
    recorded = replay.execution_evidence.to_dict()
    reexecuted = fresh.to_dict()
    if _canonical_json_bytes(recorded) != _canonical_json_bytes(reexecuted):
        raise C8ReplayDivergenceError(
            "fresh A/B/C reexecution diverged from recorded semantic evidence"
        )
    fresh_public = _public_projection_from_execution(replay.commands, fresh)
    if fresh_public != replay.to_public_dict_v1():
        raise C8ReplayDivergenceError("fresh public projection diverged")
    values: dict[str, object] = {
        "schema": "sgs-c8-d-replay-proof-v1",
        "contract_version": 1,
        "status": "MATCH",
        "replay_identity": replay.replay_identity,
        "recorded_execution_identity": recorded["execution_identity"],
        "reexecuted_execution_identity": reexecuted["execution_identity"],
        "semantic_identity": reexecuted["semantic_identity"],
        "public_projection_identity": fresh_public["public_projection_identity"],
        "fresh_isolated_process": True,
        "live_authority_reissued": True,
        "serialized_authority_accepted": False,
        "production_adapter_integration": C8_D_PRODUCTION_ADAPTER_INTEGRATION,
        "full_game": C8_D_FULL_GAME,
    }
    return C8ReplayProofV1(
        **values, proof_identity=_identity(values)  # type: ignore[arg-type]
    )


def _worker_main() -> int:
    if len(sys.argv) != 2 or sys.argv[1] != _WORKER_FLAG:
        return 2
    try:
        request = _strict_json_object(sys.stdin.buffer.read())
        data = _exact_keys(request, _WORKER_REQUEST_KEYS, "worker request")
        if (
            data["schema"] != "sgs-c8-d-isolated-worker-request-v1"
            or data["contract_version"] != 1
        ):
            raise C8ReplayError("worker request schema/version mismatch")
        initial = C8ReplayInitialMaterialV1.from_dict(data["initial_material"])
        commands = tuple(
            C8ReplayCommandV1.from_dict(item)
            for item in _exact_list(data["commands"], "worker commands")
        )
        evidence = _ReplayExecution(initial).run(commands)
        response = {
            "schema": "sgs-c8-d-isolated-worker-response-v1",
            "contract_version": 1,
            "execution_evidence": evidence.to_dict(),
        }
        sys.stdout.buffer.write(_canonical_json_bytes(response))
        return 0
    except Exception as exc:
        sys.stderr.write(f"{type(exc).__name__}: {exc}\n")
        return 2


__all__ = [
    "C8DCurrentContractLatchV1",
    "C8ReplayCommandKindV1",
    "C8ReplayCommandV1",
    "C8ReplayDivergenceError",
    "C8ReplayError",
    "C8ReplayExecutionEvidenceV1",
    "C8ReplayIdentityError",
    "C8ReplayInitialMaterialV1",
    "C8ReplayProofV1",
    "C8StrictReplayV1",
    "C8_D_CONTRACT_IDENTITY",
    "C8_D_CURRENT_IMPLEMENTATION_IDENTITY",
    "C8_D_DEVELOPMENT_IDENTITY",
    "C8_D_FULL_GAME",
    "C8_D_FAILED_ATTEMPT_POLICY",
    "C8_D_PRODUCTION_ADAPTER_INTEGRATION",
    "C8_D_REPLAY_ID",
    "C8_D_REPLAY_SCHEMA",
    "C8_D_REPLAY_VERSION",
    "C8_D_SCOPE_MARKER",
    "c8_replay_identity_v1",
    "record_c8_timed_session_trace_v1",
    "recompute_c8_replay_outer_identities_v1",
    "strict_reexecute_c8_replay_v1",
]


if __name__ == "__main__":
    raise SystemExit(_worker_main())
