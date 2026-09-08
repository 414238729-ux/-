# -*- coding: utf-8 -*-
"""C8-F bounded multi-window timed trace over canonical C6 no-skill 8p.

This is not a full-game runner or a production cold-replay contract. It records
eight real production decision windows, verifies public evidence strictly, and
supports a fresh bounded semantic rerun.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import json
from pathlib import Path
import re
from types import MappingProxyType
from typing import Any, Final, Mapping, Sequence

from . import c8_c6_production_adapter_v1 as prod
from . import c8_strict_replay_v1 as replay
from . import c8_timed_session_runtime_v1 as runtime_v1
from . import c8_timeout_controller_integration_v1 as controller_v1
from . import c8_virtual_time_contract_v1 as clock_v1
from .actions import LegalAction
from .authoritative_no_skill_full_game import canonical_no_skill_mode_v1
from .mode_identity import (
    FORMAL_NO_SKILL_IDENTITY_8P_MODE,
    FormalEightPlayerIdentitySession,
)
from .production_batch import ProductionPhase


class C8FTraceError(ValueError):
    """Fail-closed C8-F construction, parsing, or continuity error."""


class C8FDecisionMarkerV1(str, Enum):
    NORMAL_ON_TIME = "NORMAL_ON_TIME"
    TIMEOUT_EXACT_BOUNDARY = "TIMEOUT_EXACT_BOUNDARY"


C8_F_TRACE_ID: Final[str] = "c8-bounded-timed-8p-trace-v1"
C8_F_TRACE_SCHEMA: Final[str] = "sgs-c8-f-bounded-timed-8p-trace-v1"
C8_F_TRACE_VERSION: Final[int] = 1
C8_F_CELL_SCHEMA: Final[str] = "sgs-c8-f-bounded-timed-8p-cell-v1"
C8_F_SCOPE_MARKER: Final[str] = "BOUNDED_REAL_PRODUCTION_TRACE_ONLY"
C8_F_DRIVER_POLICY_ID: Final[str] = "c8-f-public-last-ordinal-interleave-v1"
C8_F_MAX_BOUNDED_PRODUCTION_STEPS: Final[int] = 16
C8_F_MAX_WINDOWS: Final[int] = 8
C8_F_TRACE_A_SEED: Final[int] = 0
C8_F_TRACE_A_TIMEOUT_WINDOWS: Final[tuple[int, ...]] = (1, 4, 6, 8)
C8_F_PRODUCTION_COLD_REPLAY: Final[str] = "NOT_PROVEN"
C8_F_NESTED_STATUS: Final[str] = "NOT_NATURALLY_OBSERVED_IN_BOUNDED_SCOPE"
C8_F_MODE_DECISION_STATUS: Final[str] = "NOT_APPLICABLE_IN_C6_NO_SKILL_8P"
C8_F_FULL_GAME: Final[bool] = False
C8_F_FORMAL_MATRIX: Final[bool] = False

_BASE_COMMIT: Final[str] = "230d5b3a0b483dc794cc43c6691c8ecce237e8e4"
_TAG_OBJECT: Final[str] = "969dcc57a9972647add8fe413d4fad4b32e0c04b"
_TAG_PEEL: Final[str] = _BASE_COMMIT
_BRIDGE_PIN: Final[str] = (
    "ba3838692ad9e1954f8759ea9f51260796fe011e7cc881747f74018e0c42c2e6"
)
_ZERO_IDENTITY: Final[str] = "0" * 64
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_TEXT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")
_RUN_LABEL_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,47}$")

_AUDITED_HASHES: Final[Mapping[str, str]] = MappingProxyType(
    {
        "c8_a_source": "a2f7ee8bf79c50ec10dbf60cc2e70286a4a3eacf972b8294c9fefabd886739c4",
        "c8_a_test": "4a55c7f5ea97938d228c6080a2dfc903359d515af39ffed6bce846b1613a0d1e",
        "c8_b_source": "26e2b34d2f20d814cb5b3c62c915127b79663406d60e69b3a56da5e91e34c54a",
        "c8_b_test": "510cce80454eb9002cf55973a612fbe84fb610f862ee7774d258bc1b0ef83e16",
        "c8_c_source": "cd906a86eefe42ae256af60219e136af31d337bcb50747676dbdaf59c4a8e026",
        "c8_c_test": "e0740f36afa0f775c9156699850dd4eea75abf16feb3e99135586a13c6d8f52a",
        "c8_d_source": "bc6cd0410aff5adfce7e4573872747d02b455ea08e67fb935b05f6bf44adf536",
        "c8_d_test": "92f3833a6ed6a02e1f9a0a8b328d3021b8d806862c95417d65af4a49720ee6ff",
        "c8_e_source": "50147fd7abbbff86459f38fa0ab19e0571599b0e9f66efd007bbec466f64c647",
        "c8_e_test": "fe4514d92ff94707f1639b0b428e821362aa2ede79ba0d06fcae22a2a0e84012",
        "production_batch_source": "ed90625615c01e185ab03948c466b3779867d5f78187bb557660e08b6e5f089b",
        "mode_identity_source": "8ba10885af4d8d84e5433b533c8c0a2448cc3b8b51a3c418aa618f86f0aa555d",
        "bridge_current_pin_source": "8b8331beebc3e71223fae0e5c90042c4e41b7b616ce2b7384c836cd71530edff",
    }
)
_AUDITED_PATHS: Final[Mapping[str, str]] = MappingProxyType(
    {
        "c8_a_source": "scripts/sgs_engine/c8_virtual_time_contract_v1.py",
        "c8_a_test": "tests/test_c8_virtual_time_contract_v1.py",
        "c8_b_source": "scripts/sgs_engine/c8_timed_session_runtime_v1.py",
        "c8_b_test": "tests/test_c8_timed_session_runtime_v1.py",
        "c8_c_source": "scripts/sgs_engine/c8_timeout_controller_integration_v1.py",
        "c8_c_test": "tests/test_c8_timeout_controller_integration_v1.py",
        "c8_d_source": "scripts/sgs_engine/c8_strict_replay_v1.py",
        "c8_d_test": "tests/test_c8_strict_replay_v1.py",
        "c8_e_source": "scripts/sgs_engine/c8_c6_production_adapter_v1.py",
        "c8_e_test": "tests/test_c8_c6_production_adapter_v1.py",
        "production_batch_source": "scripts/sgs_engine/production_batch.py",
        "mode_identity_source": "scripts/sgs_engine/mode_identity.py",
        "bridge_current_pin_source": "scripts/current_implementation_pin.py",
    }
)
_DRIVER_POLICY: Final[Mapping[str, object]] = MappingProxyType(
    {
        "schema": "sgs-c8-f-bounded-driver-policy-v1",
        "contract_version": 1,
        "policy_id": C8_F_DRIVER_POLICY_ID,
        "trace_a_seed": C8_F_TRACE_A_SEED,
        "trace_a_timeout_window_sequences": list(C8_F_TRACE_A_TIMEOUT_WINDOWS),
        "normal_on_time_selection": "FRESH_PRODUCTION_PUBLIC_ORDER_LAST_ORDINAL",
        "timeout_selection": "C8_C_FALLBACK_OVER_C8_E_FRESH_PUBLIC_PROJECTION",
        "production_order_resorted": False,
        "private_payload_read_by_driver": False,
        "wall_clock_in_semantics": False,
    }
)
_CONTRACT_DESCRIPTOR: Final[Mapping[str, object]] = MappingProxyType(
    {
        "schema": "sgs-c8-f-bounded-timed-8p-trace-contract-v1",
        "contract_version": 1,
        "trace_id": C8_F_TRACE_ID,
        "trace_schema": C8_F_TRACE_SCHEMA,
        "scope_marker": C8_F_SCOPE_MARKER,
        "canonical_mode": FORMAL_NO_SKILL_IDENTITY_8P_MODE,
        "canonical_factory": "canonical_no_skill_mode_v1.create_session",
        "production_adapter": prod.C8_E_ADAPTER_ID,
        "max_bounded_production_steps": C8_F_MAX_BOUNDED_PRODUCTION_STEPS,
        "max_windows": C8_F_MAX_WINDOWS,
        "driver_policy": dict(_DRIVER_POLICY),
        "full_game": False,
        "formal_matrix": False,
        "natural_terminal_forbidden": True,
        "production_cold_replay": C8_F_PRODUCTION_COLD_REPLAY,
        "strict_evidence": "REQUIRED_FIELDS_EXACT_KEYS_IDENTITY_AND_CONTINUITY",
        "fresh_verification": "SAME_SEED_SAME_POLICY_BOUNDED_SEMANTIC_RERUN",
        "serialized_passed_authority": False,
    }
)


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _identity(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


C8_F_DRIVER_POLICY_IDENTITY: Final[str] = _identity(dict(_DRIVER_POLICY))
C8_F_CONTRACT_IDENTITY: Final[str] = _identity(dict(_CONTRACT_DESCRIPTOR))


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


def _exact_dict(value: object, label: str) -> dict[str, Any]:
    if type(value) is not dict or any(type(key) is not str for key in value):
        raise C8FTraceError(f"{label}必须是精确JSON object")
    return value


def _exact_list(value: object, label: str) -> list[Any]:
    if type(value) is not list:
        raise C8FTraceError(f"{label}必须是精确JSON array")
    return value


def _exact_keys(value: object, keys: frozenset[str], label: str) -> dict[str, Any]:
    data = _exact_dict(value, label)
    actual = frozenset(data)
    if actual != keys:
        raise C8FTraceError(
            f"{label}字段不匹配 missing={sorted(keys-actual)} extra={sorted(actual-keys)}"
        )
    return data


def _text(value: object, label: str) -> str:
    if type(value) is not str or not value:
        raise C8FTraceError(f"{label}必须是非空精确字符串")
    return value


def _text_id(value: object, label: str) -> str:
    text = _text(value, label)
    if _TEXT_ID_RE.fullmatch(text) is None:
        raise C8FTraceError(f"{label}不是canonical text id")
    return text


def _sha(value: object, label: str, *, allow_zero: bool = False) -> str:
    text = _text(value, label)
    if _SHA_RE.fullmatch(text) is None or (not allow_zero and text == _ZERO_IDENTITY):
        raise C8FTraceError(f"{label}必须是canonical nonzero SHA-256")
    return text


def _integer(value: object, label: str, *, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise C8FTraceError(f"{label}必须是精确int且 >= {minimum}")
    return value


def _contract_version_one(value: object, label: str) -> None:
    if _integer(value, label, minimum=1) != 1:
        raise C8FTraceError(f"{label}必须是exact int 1")


def _same_json_value(left: object, right: object) -> bool:
    """Compare JSON values without Python's bool/int equality aliasing."""

    return _canonical_bytes(left) == _canonical_bytes(right)


def _strict_json(raw: bytes | str) -> dict[str, Any]:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise C8FTraceError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    try:
        value = json.loads(raw, object_pairs_hook=reject_duplicates)
    except C8FTraceError:
        raise
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise C8FTraceError("trace不是strict JSON") from exc
    return _exact_dict(value, "trace JSON root")


def _identity_object(
    value: object, *, keys: frozenset[str], identity_key: str, label: str
) -> dict[str, Any]:
    data = _exact_keys(value, keys, label)
    supplied = _sha(data[identity_key], f"{label}.{identity_key}")
    material = {key: item for key, item in data.items() if key != identity_key}
    if supplied != _identity(material):
        raise C8FTraceError(f"{label}.{identity_key}不匹配")
    return data


def _assert_no_private_keys(value: object, path: str = "trace") -> None:
    forbidden = {
        "payload", "card_instance_id", "virtual_card", "target_ids", "skill_id",
        "handle", "card_key", "card_name", "rng_state", "raw_snapshot",
    }
    if type(value) is dict:
        for key, item in value.items():
            if key in forbidden:
                raise C8FTraceError(f"public trace禁止private字段 {path}.{key}")
            _assert_no_private_keys(item, f"{path}.{key}")
    elif type(value) is list:
        for index, item in enumerate(value):
            _assert_no_private_keys(item, f"{path}[{index}]")


def audited_dependency_snapshot_v1(
    repo_root: Path | str | None = None,
) -> dict[str, object]:
    """Fresh-hash A-E/shared core and derive the audited pre-F identity."""

    root = _repo_root() if repo_root is None else Path(repo_root).resolve()
    observed = {
        label: _file_sha256(root / relative)
        for label, relative in _AUDITED_PATHS.items()
    }
    if observed != dict(_AUDITED_HASHES):
        drift = {
            key: {"expected": _AUDITED_HASHES[key], "observed": observed[key]}
            for key in _AUDITED_HASHES
            if observed[key] != _AUDITED_HASHES[key]
        }
        raise C8FTraceError(f"C8_F_A_E_AUDITED_HASH_DRIFT {drift}")
    live = {
        "c8_a_contract_identity": clock_v1.C8_A_CONTRACT_IDENTITY_V1,
        "c8_b_runtime_contract_identity": runtime_v1.C8_B_RUNTIME_CONTRACT_IDENTITY_V1,
        "c8_b_current_contract_latch_identity": (
            runtime_v1.C8_B_CURRENT_CONTRACT_LATCH_V1.latch_identity
        ),
        "c8_c_contract_identity": controller_v1.C8_C_CONTRACT_IDENTITY,
        "c8_d_contract_identity": replay.C8_D_CONTRACT_IDENTITY,
        "c8_d_current_implementation_identity": replay.C8_D_CURRENT_IMPLEMENTATION_IDENTITY,
        "c8_d_current_contract_latch_identity": (
            replay.C8DCurrentContractLatchV1.canonical().latch_identity
        ),
        "c8_e_contract_identity": prod.C8_E_CONTRACT_IDENTITY,
    }
    live_expected = {
        "c8_a_contract_identity": "64f52c789ffb59d1fbdd0c9a4295109ff73be6bd50f2042666f4946f66f648c2",
        "c8_b_runtime_contract_identity": "ce5a7c622dbecfc71423bf06bf0a94d447741aabe29a59cc23f36c1b1b2d8b55",
        "c8_b_current_contract_latch_identity": "eb2407ae7ce4f76dbf087fc4b351060c8fe60bf747e34635c454ec9f40a6657d",
        "c8_c_contract_identity": "924c9712502cd24ccc4f77e5fce221b04f83b5257d51858f3ee6410e89390336",
        "c8_d_contract_identity": "4c5641760271fb9f612a2f97f2a82b80d76845103c0e45f22477bd8edbdf7471",
        "c8_d_current_implementation_identity": "cc853b1206753867f5329eb14c8ae06348422624c861351a9d3817eccb2d8b64",
        "c8_d_current_contract_latch_identity": "65aff4a27bdc526901f68912bc98dd33dcf5f60beea34c0e496015d9e3083997",
        "c8_e_contract_identity": "17fd08db5270dfa2b7ccbbdc973ce61643d296a3b94158c8fc8a15a7f5138a8c",
    }
    if live != live_expected:
        raise C8FTraceError("C8_F_A_E_LIVE_CONTRACT_IDENTITY_DRIFT")
    e_material = {
        "schema": "sgs-c8-e-c6-production-adapter-development-identity-v1",
        "contract_version": 1,
        "adapter_id": prod.C8_E_ADAPTER_ID,
        "contract_identity": prod.C8_E_CONTRACT_IDENTITY,
        "source_sha256": observed["c8_e_source"],
        "test_sha256": observed["c8_e_test"],
        "shared_production_core_source_sha256": {
            "scripts/sgs_engine/mode_identity.py": observed["mode_identity_source"],
            "scripts/sgs_engine/production_batch.py": observed["production_batch_source"],
        },
        "dependency_development_identities": {
            "c8_a": replay.C8_A_DEVELOPMENT_IDENTITY,
            "c8_b": replay.C8_B_DEVELOPMENT_IDENTITY,
            "c8_c": replay.C8_C_DEVELOPMENT_IDENTITY,
            "c8_d": replay.C8_D_DEVELOPMENT_IDENTITY,
        },
        "c8_d_current_implementation_identity": replay.C8_D_CURRENT_IMPLEMENTATION_IDENTITY,
    }
    c8_e_development_identity = _identity(e_material)
    if c8_e_development_identity != (
        "71e2e6b16d6c12cd1724f08f1a400c78f91a41af8026c944680b8e8fa1dd586e"
    ):
        raise C8FTraceError("C8-E development identity fresh recompute drift")
    prior_material = {
        "schema": "sgs-c8-current-implementation-identity-material-v1",
        "contract_version": 1,
        "base_commit": _BASE_COMMIT,
        "bridge_frozen_anchor": {
            "tag_object": _TAG_OBJECT, "tag_peel": _TAG_PEEL, "current_pin": _BRIDGE_PIN,
        },
        "development_identities": {
            "c8_a": replay.C8_A_DEVELOPMENT_IDENTITY,
            "c8_b": replay.C8_B_DEVELOPMENT_IDENTITY,
            "c8_c": replay.C8_C_DEVELOPMENT_IDENTITY,
            "c8_d": replay.C8_D_DEVELOPMENT_IDENTITY,
            "c8_e": c8_e_development_identity,
        },
        "c8_d_current_implementation_identity": replay.C8_D_CURRENT_IMPLEMENTATION_IDENTITY,
    }
    prior_identity = _identity(prior_material)
    if prior_identity != (
        "4730dcaa20335cdf234000f48594ca765a019702cdf9ae9f0a1c7c423207181e"
    ):
        raise C8FTraceError("pre-F current C8 implementation identity drift")
    bindings = {
        "c8_a_contract_identity": live["c8_a_contract_identity"],
        "c8_a_development_identity": replay.C8_A_DEVELOPMENT_IDENTITY,
        "c8_b_runtime_contract_identity": live["c8_b_runtime_contract_identity"],
        "c8_b_current_contract_latch_identity": live[
            "c8_b_current_contract_latch_identity"
        ],
        "c8_b_development_identity": replay.C8_B_DEVELOPMENT_IDENTITY,
        "c8_c_contract_identity": live["c8_c_contract_identity"],
        "c8_c_development_identity": replay.C8_C_DEVELOPMENT_IDENTITY,
        "c8_d_contract_identity": live["c8_d_contract_identity"],
        "c8_d_development_identity": replay.C8_D_DEVELOPMENT_IDENTITY,
        "c8_d_current_implementation_identity": live[
            "c8_d_current_implementation_identity"
        ],
        "c8_d_current_contract_latch_identity": live[
            "c8_d_current_contract_latch_identity"
        ],
        "c8_e_adapter_id": prod.C8_E_ADAPTER_ID,
        "c8_e_contract_identity": live["c8_e_contract_identity"],
        "c8_e_development_identity": c8_e_development_identity,
        "prior_current_c8_implementation_identity": prior_identity,
    }
    return {
        "schema": "sgs-c8-f-a-e-audited-dependency-snapshot-v1",
        "contract_version": 1,
        "audited_hashes": observed,
        "contract_bindings": bindings,
        "dependency_hash_set_identity": _identity(observed),
        "contract_binding_set_identity": _identity(bindings),
        "prior_current_c8_implementation_identity": prior_identity,
    }


def current_c8_f_development_snapshot_v1(
    repo_root: Path | str | None = None,
) -> dict[str, object]:
    root = _repo_root() if repo_root is None else Path(repo_root).resolve()
    dependencies = audited_dependency_snapshot_v1(root)
    source_hash = _file_sha256(
        root / "scripts/sgs_engine/c8_bounded_timed_8p_trace_v1.py"
    )
    test_hash = _file_sha256(root / "tests/test_c8_bounded_timed_8p_trace_v1.py")
    material = {
        "schema": "sgs-c8-f-development-identity-v1",
        "contract_version": 1,
        "trace_id": C8_F_TRACE_ID,
        "contract_identity": C8_F_CONTRACT_IDENTITY,
        "source_sha256": source_hash,
        "test_sha256": test_hash,
        "dependency_hash_set_identity": dependencies["dependency_hash_set_identity"],
        "contract_binding_set_identity": dependencies["contract_binding_set_identity"],
        "prior_current_c8_implementation_identity": dependencies[
            "prior_current_c8_implementation_identity"
        ],
    }
    development_identity = _identity(material)
    current_material = {
        "schema": "sgs-c8-f-current-implementation-identity-v1",
        "contract_version": 1,
        "base_commit": _BASE_COMMIT,
        "prior_current_c8_implementation_identity": dependencies[
            "prior_current_c8_implementation_identity"
        ],
        "c8_f_contract_identity": C8_F_CONTRACT_IDENTITY,
        "c8_f_development_identity": development_identity,
        "c8_f_source_sha256": source_hash,
        "c8_f_test_sha256": test_hash,
    }
    return {
        **material,
        "development_identity": development_identity,
        "current_c8_implementation_identity": _identity(current_material),
        "dependencies": dependencies,
    }


def _phase_turn(session: FormalEightPlayerIdentitySession) -> int:
    if not session.phase_history:
        raise C8FTraceError("canonical C6 phase history为空")
    return session.phase_history[-1].turn_number


def _controller_tip(
    controller: controller_v1.TimeoutResolverControllerIntegrationV1,
) -> str:
    events = controller.public_event_trace_v1()
    return events[-1].event_identity if events else _ZERO_IDENTITY


def _capture_state(
    session: FormalEightPlayerIdentitySession,
    adapter: prod.C8C6ProductionAdapterV1,
    runtime: runtime_v1.C8TimedSessionRuntimeV1,
    controller: controller_v1.TimeoutResolverControllerIntegrationV1,
) -> dict[str, object]:
    active = runtime.state.virtual_time_state.window_stack.active_window
    material: dict[str, object] = {
        "schema": "sgs-c8-f-production-runtime-state-v1",
        "contract_version": 1,
        "phase": session.phase.value,
        "turn_number": _phase_turn(session),
        "current_actor_id": session.current_actor_id,
        "current_player_id": session.current_player_id,
        "state_revision": session.state.revision,
        "production_step_count": session.step_count,
        "adapter_public_state_identity": adapter.public_state_identity_v1(),
        "adapter_authoritative_state_identity": adapter.authoritative_state_identity_v1(),
        "production_execution_identity": session.execution_hash,
        "runtime_state_identity": runtime.state.state_identity,
        "runtime_event_chain_tip": runtime.state.event_chain_tip,
        "controller_event_chain_tip": _controller_tip(controller),
        "virtual_tick": runtime.state.virtual_time_state.now_tick,
        "active_window_id": None if active is None else active.window_id,
    }
    return {**material, "state_identity": _identity(material)}


def _public_action_ids(
    session: FormalEightPlayerIdentitySession,
) -> tuple[str, ...]:
    actions = session.legal_actions()
    if type(actions) is not tuple or any(type(item) is not LegalAction for item in actions):
        raise C8FTraceError("canonical production legal_actions类型漂移")
    # Deliberately access only the public production-signed ID and tuple order.
    action_ids = tuple(_text(item.action_id, "production signed action_id") for item in actions)
    if not action_ids or len(action_ids) != len(set(action_ids)):
        raise C8FTraceError("canonical production public action order为空或重复")
    return action_ids


def _production_order_identity(session_identity: str, action_ids: Sequence[str]) -> str:
    return _identity(
        {
            "schema": "sgs-c8-e-production-proposal-order-v1",
            "contract_version": 1,
            "session_identity": session_identity,
            "action_ids": list(action_ids),
        }
    )


def _build_proposal_evidence(
    *,
    session_identity: str,
    context: prod.ProductionDecisionContextV1,
    action_ids: tuple[str, ...],
    selected_ordinal: int,
    marker: C8FDecisionMarkerV1,
    c8_c_legal_set_identity: str | None,
    e_snapshot_identity: str | None,
) -> dict[str, object]:
    selected = action_ids[selected_ordinal]
    e_order = _production_order_identity(session_identity, action_ids)
    if e_order != context.proposal_order_identity:
        raise C8FTraceError("fresh production order与C8-E context不匹配")
    commitments = [_identity({"production_signed_action_id": item}) for item in action_ids]
    f_legal = _identity(
        {
            "schema": "sgs-c8-f-production-public-legal-set-v1",
            "contract_version": 1,
            "session_identity": session_identity,
            "context_identity": context.context_identity,
            "action_ids_in_production_order": list(action_ids),
        }
    )
    material: dict[str, object] = {
        "schema": "sgs-c8-f-production-proposal-evidence-v1",
        "contract_version": 1,
        "source": "FormalEightPlayerIdentitySession.legal_actions",
        "context_identity": context.context_identity,
        "action_ids_in_production_order": list(action_ids),
        "action_id_commitments_in_production_order": commitments,
        "proposal_count": len(action_ids),
        "e_proposal_order_identity": e_order,
        "f_legal_set_identity": f_legal,
        "selected_public_ordinal": selected_ordinal,
        "selected_signed_action_id": selected,
        "selected_action_id_commitment": commitments[selected_ordinal],
        "driver_rule": (
            "C8_C_FALLBACK_OVER_C8_E_FRESH_PUBLIC_PROJECTION"
            if marker is C8FDecisionMarkerV1.TIMEOUT_EXACT_BOUNDARY
            else "FRESH_PRODUCTION_PUBLIC_ORDER_LAST_ORDINAL"
        ),
        "private_payload_read_by_driver": False,
        "production_order_resorted": False,
        "c8_c_legal_set_identity": c8_c_legal_set_identity,
        "e_public_legal_set_snapshot_identity": e_snapshot_identity,
    }
    return {**material, "proposal_evidence_identity": _identity(material)}


def _build_refresh_evidence(
    *,
    before_context: prod.ProductionDecisionContextV1,
    after_context: prod.ProductionDecisionContextV1,
    before_ref: runtime_v1.WindowAuthorityRefV1,
    after_ref: runtime_v1.WindowAuthorityRefV1,
    opened: bool,
    deadline_before: int,
    deadline_after: int,
    runtime_state_before: str,
    runtime_state_after: str,
) -> dict[str, object]:
    material: dict[str, object] = {
        "schema": "sgs-c8-f-same-context-refresh-evidence-v1",
        "contract_version": 1,
        "context_before_identity": before_context.context_identity,
        "context_after_identity": after_context.context_identity,
        "window_ref_before_identity": before_ref.authority_ref_identity,
        "window_ref_after_identity": after_ref.authority_ref_identity,
        "refresh_opened_new_window": opened,
        "deadline_before": deadline_before,
        "deadline_after": deadline_after,
        "deadline_refreshed": deadline_before != deadline_after,
        "runtime_state_before_identity": runtime_state_before,
        "runtime_state_after_identity": runtime_state_after,
    }
    if (
        before_context != after_context
        or before_ref != after_ref
        or opened
        or deadline_before != deadline_after
        or runtime_state_before != runtime_state_after
    ):
        raise C8FTraceError("same logical decision refresh改变了window/deadline/state")
    return {**material, "refresh_evidence_identity": _identity(material)}


def _build_on_time_receipt(
    *,
    ref: runtime_v1.WindowAuthorityRefV1,
    signed_action_id: str,
    transition_identity: str,
    pre_state: Mapping[str, object],
    post_state: Mapping[str, object],
) -> dict[str, object]:
    material: dict[str, object] = {
        "schema": "sgs-c8-f-on-time-production-action-receipt-v1",
        "contract_version": 1,
        "window_authority_ref_identity": ref.authority_ref_identity,
        "signed_action_id": signed_action_id,
        "inner_transition_identity": transition_identity,
        "pre_public_state_identity": pre_state["adapter_public_state_identity"],
        "pre_authoritative_state_identity": pre_state[
            "adapter_authoritative_state_identity"
        ],
        "pre_execution_identity": pre_state["production_execution_identity"],
        "post_public_state_identity": post_state["adapter_public_state_identity"],
        "post_authoritative_state_identity": post_state[
            "adapter_authoritative_state_identity"
        ],
        "post_execution_identity": post_state["production_execution_identity"],
        "accepted": True,
        "executed": True,
        "timeout_authority_used": False,
    }
    return {**material, "receipt_identity": _identity(material)}


def _build_rejection(
    *,
    kind: str,
    stale_cell_sequence: int,
    stale_legal_set_identity: str,
    stale_context_identity: str,
    stale_window_ref_identity: str,
    current_context_identity: str,
    current_turn_number: int,
    current_actor_id: str,
    outcome: str,
    result_identity: str,
    runtime_before: str,
    runtime_after: str,
) -> dict[str, object]:
    material: dict[str, object] = {
        "schema": "sgs-c8-f-stale-evidence-rejection-v1",
        "contract_version": 1,
        "rejection_kind": kind,
        "stale_cell_sequence": stale_cell_sequence,
        "stale_legal_set_identity": stale_legal_set_identity,
        "stale_context_identity": stale_context_identity,
        "stale_window_ref_identity": stale_window_ref_identity,
        "current_context_identity": current_context_identity,
        "current_turn_number": current_turn_number,
        "current_actor_id": current_actor_id,
        "outcome": outcome,
        "result_identity": result_identity,
        "runtime_state_before_identity": runtime_before,
        "runtime_state_after_identity": runtime_after,
        "rejected": True,
    }
    if runtime_before != runtime_after:
        raise C8FTraceError("stale evidence rejection改变了runtime state")
    return {**material, "rejection_evidence_identity": _identity(material)}


def _cell_semantic_material(cell: Mapping[str, object]) -> dict[str, object]:
    pre = _exact_dict(cell["pre_state"], "cell.pre_state")
    post = _exact_dict(cell["post_state"], "cell.post_state")
    context = _exact_dict(cell["decision_context"], "cell.decision_context")
    proposal = _exact_dict(cell["proposal_evidence"], "cell.proposal_evidence")
    execution = _exact_dict(cell["execution_evidence"], "cell.execution_evidence")
    window = _exact_dict(cell["window_evidence"], "cell.window_evidence")
    open_window = _exact_dict(window["open_window"], "cell.open_window")
    # Runtime/controller authority is intentionally live-instance bound.  In
    # particular, a timeout transaction contributes its live binding to the
    # production execution hash, and later production-signed action IDs bind
    # that hash.  Those exact values remain mandatory in each strict trace,
    # but cannot be compared for equality across two fresh runtime instances.
    # The rerun comparison therefore freezes the public ordered ordinal shape
    # and selected ordinal together with stable production phase/turn/step
    # semantics; each run independently verifies its raw IDs and commitments.
    state_fields = (
        "phase", "turn_number", "current_actor_id", "current_player_id",
        "state_revision", "production_step_count", "virtual_tick",
    )
    action_ids = _exact_list(
        proposal["action_ids_in_production_order"], "cell.proposal_action_ids"
    )
    return {
        "cell_sequence": cell["cell_sequence"],
        "decision_marker": cell["decision_marker"],
        "pre": {key: pre[key] for key in state_fields},
        "post": {key: post[key] for key in state_fields},
        "context": {
            key: context[key]
            for key in (
                "phase", "turn_number", "current_actor_id", "current_player_id",
                "window_kind", "applicability", "proposal_count",
            )
        },
        "ordered_public_commitment_shape": [
            {
                "public_ordinal": ordinal,
                "authority_kind": "PRODUCTION_SIGNED_ACTION_ID",
            }
            for ordinal in range(len(action_ids))
        ],
        "selected_public_ordinal": proposal["selected_public_ordinal"],
        "opened_at": open_window["opened_at"],
        "deadline_at": open_window["deadline_at"],
        "decision_tick": execution["decision_tick"],
        "close_status": window["close_status"],
        "production_steps_committed": execution["production_steps_committed"],
    }


def _semantic_trace_material(document: Mapping[str, object]) -> dict[str, object]:
    return {
        "schema": "sgs-c8-f-bounded-semantic-trace-v1",
        "contract_version": 1,
        "contract_identity": document["contract_identity"],
        "driver_policy_identity": document["driver_policy_identity"],
        "seed": document["seed"],
        "mode_id": document["mode_id"],
        "mode_contract_id": document["mode_contract_id"],
        "profile_identity": document["profile_identity"],
        "max_bounded_production_steps": document["max_bounded_production_steps"],
        "max_windows": document["max_windows"],
        "fresh_session_execution_identity": document["fresh_session_execution_identity"],
        "prelude_signed_action_ids": document["prelude_signed_action_ids"],
        "cells": [
            _cell_semantic_material(_exact_dict(item, "cell"))
            for item in _exact_list(document["cells"], "cells")
        ],
        "stale_rejection_kinds": [
            _exact_dict(item, "rejection")["rejection_kind"]
            for item in _exact_list(
                document["stale_rejection_evidence"], "stale_rejection_evidence"
            )
        ],
        "bounded_limit_reached": document["bounded_limit_reached"],
        "stop_reason": document["stop_reason"],
        "production_session_finished": document["production_session_finished"],
    }


_STATE_KEYS = frozenset(
    {
        "schema", "contract_version", "phase", "turn_number", "current_actor_id",
        "current_player_id", "state_revision", "production_step_count",
        "adapter_public_state_identity", "adapter_authoritative_state_identity",
        "production_execution_identity", "runtime_state_identity",
        "runtime_event_chain_tip", "controller_event_chain_tip", "virtual_tick",
        "active_window_id", "state_identity",
    }
)


def _validate_state(value: object, label: str) -> dict[str, Any]:
    data = _identity_object(
        value, keys=_STATE_KEYS, identity_key="state_identity", label=label
    )
    _contract_version_one(data["contract_version"], f"{label}.contract_version")
    if data["schema"] != "sgs-c8-f-production-runtime-state-v1":
        raise C8FTraceError(f"{label} schema/version不匹配")
    if data["phase"] not in {item.value for item in ProductionPhase}:
        raise C8FTraceError(f"{label}.phase未知")
    _text_id(data["current_actor_id"], f"{label}.current_actor_id")
    _text_id(data["current_player_id"], f"{label}.current_player_id")
    for name, minimum in (
        ("turn_number", 1), ("state_revision", 0),
        ("production_step_count", 0), ("virtual_tick", 0),
    ):
        _integer(data[name], f"{label}.{name}", minimum=minimum)
    for name in (
        "adapter_public_state_identity", "adapter_authoritative_state_identity",
        "production_execution_identity", "runtime_state_identity",
        "runtime_event_chain_tip",
    ):
        _sha(data[name], f"{label}.{name}")
    _sha(
        data["controller_event_chain_tip"],
        f"{label}.controller_event_chain_tip",
        allow_zero=True,
    )
    if data["active_window_id"] is not None:
        _text(data["active_window_id"], f"{label}.active_window_id")
    return data


_CONTEXT_KEYS = frozenset(
    {
        "schema", "contract_version", "mode_id", "phase", "current_actor_id",
        "current_player_id", "turn_number", "state_revision", "step_count",
        "window_kind", "applicability", "parent_context_identity",
        "proposal_count", "proposal_order_identity", "private_payload_present",
        "public_ordinal_safe", "decision_identity", "obligation_identity",
        "context_identity",
    }
)


def _validate_context(value: object, label: str) -> dict[str, Any]:
    data = _exact_keys(value, _CONTEXT_KEYS, label)
    _contract_version_one(data["contract_version"], f"{label}.contract_version")
    if data["schema"] != "sgs-c8-e-production-decision-context-v1":
        raise C8FTraceError(f"{label} schema/version不匹配")
    if data["mode_id"] != FORMAL_NO_SKILL_IDENTITY_8P_MODE:
        raise C8FTraceError(f"{label} mode不匹配")
    if data["phase"] not in {item.value for item in ProductionPhase}:
        raise C8FTraceError(f"{label} phase未知")
    _text_id(data["current_actor_id"], f"{label}.current_actor_id")
    _text_id(data["current_player_id"], f"{label}.current_player_id")
    for name, minimum in (
        ("turn_number", 1), ("state_revision", 0),
        ("step_count", 0), ("proposal_count", 1),
    ):
        _integer(data[name], f"{label}.{name}", minimum=minimum)
    _text(data["window_kind"], f"{label}.window_kind")
    _text(data["applicability"], f"{label}.applicability")
    if data["parent_context_identity"] is not None:
        _sha(data["parent_context_identity"], f"{label}.parent_context_identity")
    if type(data["private_payload_present"]) is not bool:
        raise C8FTraceError(f"{label}.private_payload_present必须是bool")
    if type(data["public_ordinal_safe"]) is not bool:
        raise C8FTraceError(f"{label}.public_ordinal_safe必须是bool")
    for name in (
        "proposal_order_identity", "decision_identity",
        "obligation_identity", "context_identity",
    ):
        _sha(data[name], f"{label}.{name}")
    material = {key: item for key, item in data.items() if key != "context_identity"}
    if data["context_identity"] != _identity(material):
        raise C8FTraceError(f"{label}.context_identity不匹配")
    return data


_REFRESH_KEYS = frozenset(
    {
        "schema", "contract_version", "context_before_identity",
        "context_after_identity", "window_ref_before_identity",
        "window_ref_after_identity", "refresh_opened_new_window",
        "deadline_before", "deadline_after", "deadline_refreshed",
        "runtime_state_before_identity", "runtime_state_after_identity",
        "refresh_evidence_identity",
    }
)


def _validate_refresh(value: object, label: str) -> dict[str, Any]:
    data = _identity_object(
        value,
        keys=_REFRESH_KEYS,
        identity_key="refresh_evidence_identity",
        label=label,
    )
    _contract_version_one(data["contract_version"], f"{label}.contract_version")
    if data["schema"] != "sgs-c8-f-same-context-refresh-evidence-v1":
        raise C8FTraceError(f"{label} schema/version不匹配")
    for name in (
        "context_before_identity", "context_after_identity",
        "window_ref_before_identity", "window_ref_after_identity",
        "runtime_state_before_identity", "runtime_state_after_identity",
    ):
        _sha(data[name], f"{label}.{name}")
    _integer(data["deadline_before"], f"{label}.deadline_before")
    _integer(data["deadline_after"], f"{label}.deadline_after")
    if data["refresh_opened_new_window"] is not False or data[
        "deadline_refreshed"
    ] is not False:
        raise C8FTraceError("same-context refresh不得开新window或刷新deadline")
    if (
        data["context_before_identity"] != data["context_after_identity"]
        or data["window_ref_before_identity"] != data["window_ref_after_identity"]
        or data["deadline_before"] != data["deadline_after"]
        or data["runtime_state_before_identity"]
        != data["runtime_state_after_identity"]
    ):
        raise C8FTraceError("same-context refresh continuity不匹配")
    return data


_PROPOSAL_KEYS = frozenset(
    {
        "schema", "contract_version", "source", "context_identity",
        "action_ids_in_production_order",
        "action_id_commitments_in_production_order", "proposal_count",
        "e_proposal_order_identity", "f_legal_set_identity",
        "selected_public_ordinal", "selected_signed_action_id",
        "selected_action_id_commitment", "driver_rule",
        "private_payload_read_by_driver", "production_order_resorted",
        "c8_c_legal_set_identity", "e_public_legal_set_snapshot_identity",
        "proposal_evidence_identity",
    }
)


def _validate_proposal(
    value: object,
    *,
    label: str,
    session_identity: str,
    context: Mapping[str, object],
    marker: str,
) -> dict[str, Any]:
    data = _identity_object(
        value,
        keys=_PROPOSAL_KEYS,
        identity_key="proposal_evidence_identity",
        label=label,
    )
    _contract_version_one(data["contract_version"], f"{label}.contract_version")
    if data["schema"] != "sgs-c8-f-production-proposal-evidence-v1":
        raise C8FTraceError(f"{label} schema/version不匹配")
    if data["source"] != "FormalEightPlayerIdentitySession.legal_actions":
        raise C8FTraceError(f"{label} production legal authority不匹配")
    if data["context_identity"] != context["context_identity"]:
        raise C8FTraceError(f"{label} context binding不匹配")
    action_ids = _exact_list(
        data["action_ids_in_production_order"], f"{label}.action_ids"
    )
    commitments = _exact_list(
        data["action_id_commitments_in_production_order"],
        f"{label}.action_commitments",
    )
    if not action_ids or len(action_ids) != len(set(action_ids)):
        raise C8FTraceError(f"{label} action IDs为空或重复")
    for item in action_ids:
        _text(item, f"{label}.action_id")
    expected_commitments = [
        _identity({"production_signed_action_id": item}) for item in action_ids
    ]
    if commitments != expected_commitments:
        raise C8FTraceError(f"{label} proposal commitment order被篡改")
    proposal_count = _integer(
        data["proposal_count"], f"{label}.proposal_count", minimum=1
    )
    if proposal_count != len(action_ids) or proposal_count != context[
        "proposal_count"
    ]:
        raise C8FTraceError(f"{label} proposal count不匹配")
    expected_order = _production_order_identity(session_identity, action_ids)
    if data["e_proposal_order_identity"] != expected_order or expected_order != context[
        "proposal_order_identity"
    ]:
        raise C8FTraceError(f"{label} production proposal order不匹配")
    expected_legal = _identity(
        {
            "schema": "sgs-c8-f-production-public-legal-set-v1",
            "contract_version": 1,
            "session_identity": session_identity,
            "context_identity": context["context_identity"],
            "action_ids_in_production_order": action_ids,
        }
    )
    if data["f_legal_set_identity"] != expected_legal:
        raise C8FTraceError(f"{label} F legal-set identity不匹配")
    ordinal = _integer(data["selected_public_ordinal"], f"{label}.ordinal")
    if ordinal >= len(action_ids):
        raise C8FTraceError(f"{label} selected ordinal越界")
    if (
        data["selected_signed_action_id"] != action_ids[ordinal]
        or data["selected_action_id_commitment"] != commitments[ordinal]
    ):
        raise C8FTraceError(f"{label} signed action/ordinal binding不匹配")
    if data["private_payload_read_by_driver"] is not False or data[
        "production_order_resorted"
    ] is not False:
        raise C8FTraceError(f"{label} driver禁止private selection/resort")
    if marker == C8FDecisionMarkerV1.NORMAL_ON_TIME.value:
        if ordinal != len(action_ids) - 1:
            raise C8FTraceError("NORMAL_ON_TIME必须选择fresh production最后ordinal")
        if data["driver_rule"] != "FRESH_PRODUCTION_PUBLIC_ORDER_LAST_ORDINAL":
            raise C8FTraceError("NORMAL_ON_TIME driver rule不匹配")
        if data["c8_c_legal_set_identity"] is not None or data[
            "e_public_legal_set_snapshot_identity"
        ] is not None:
            raise C8FTraceError("NORMAL_ON_TIME禁止伪装C8-C timeout evidence")
    else:
        if data["driver_rule"] != (
            "C8_C_FALLBACK_OVER_C8_E_FRESH_PUBLIC_PROJECTION"
        ):
            raise C8FTraceError("TIMEOUT driver rule不匹配")
        _sha(data["c8_c_legal_set_identity"], f"{label}.c8_c_legal_set_identity")
        _sha(
            data["e_public_legal_set_snapshot_identity"],
            f"{label}.e_snapshot_identity",
        )
    return data


_ON_TIME_RECEIPT_KEYS = frozenset(
    {
        "schema", "contract_version", "window_authority_ref_identity",
        "signed_action_id", "inner_transition_identity",
        "pre_public_state_identity", "pre_authoritative_state_identity",
        "pre_execution_identity", "post_public_state_identity",
        "post_authoritative_state_identity", "post_execution_identity",
        "accepted", "executed", "timeout_authority_used", "receipt_identity",
    }
)


def _validate_on_time_receipt(
    value: object,
    *,
    label: str,
    ref_identity: str,
    selected_action_id: str,
    pre: Mapping[str, object],
    post: Mapping[str, object],
) -> dict[str, Any]:
    data = _identity_object(
        value,
        keys=_ON_TIME_RECEIPT_KEYS,
        identity_key="receipt_identity",
        label=label,
    )
    _contract_version_one(data["contract_version"], f"{label}.contract_version")
    if data["schema"] != "sgs-c8-f-on-time-production-action-receipt-v1":
        raise C8FTraceError(f"{label} schema/version不匹配")
    expected = {
        "window_authority_ref_identity": ref_identity,
        "signed_action_id": selected_action_id,
        "pre_public_state_identity": pre["adapter_public_state_identity"],
        "pre_authoritative_state_identity": pre[
            "adapter_authoritative_state_identity"
        ],
        "pre_execution_identity": pre["production_execution_identity"],
        "post_public_state_identity": post["adapter_public_state_identity"],
        "post_authoritative_state_identity": post[
            "adapter_authoritative_state_identity"
        ],
        "post_execution_identity": post["production_execution_identity"],
    }
    for name, item in expected.items():
        if data[name] != item:
            raise C8FTraceError(f"{label}.{name} continuity不匹配")
    _sha(data["inner_transition_identity"], f"{label}.inner_transition_identity")
    if data["accepted"] is not True or data["executed"] is not True:
        raise C8FTraceError(f"{label}必须accepted/executed")
    if data["timeout_authority_used"] is not False:
        raise C8FTraceError(f"{label}不得使用timeout authority")
    return data


_EXECUTION_KEYS = frozenset(
    {
        "schema", "contract_version", "decision_marker", "decision_tick",
        "deadline_at", "deadline_relation", "transaction_identity",
        "timeout_due_commitment", "b_timeout_receipt_identity",
        "c_controller_result", "on_time_receipt",
        "production_steps_committed", "runtime_event_identities",
        "runtime_event_kinds", "controller_event_identities",
        "inner_transition_identity", "execution_evidence_identity",
    }
)


def _validate_execution(
    value: object,
    *,
    label: str,
    marker: str,
    ref_identity: str,
    selected_action_id: str,
    selected_ordinal: int,
    legal_set_identity: str | None,
    pre: Mapping[str, object],
    post: Mapping[str, object],
) -> dict[str, Any]:
    data = _identity_object(
        value,
        keys=_EXECUTION_KEYS,
        identity_key="execution_evidence_identity",
        label=label,
    )
    _contract_version_one(data["contract_version"], f"{label}.contract_version")
    if data["schema"] != "sgs-c8-f-production-execution-evidence-v1":
        raise C8FTraceError(f"{label} schema/version不匹配")
    if data["decision_marker"] != marker:
        raise C8FTraceError(f"{label} decision marker不匹配")
    tick = _integer(data["decision_tick"], f"{label}.decision_tick")
    deadline = _integer(data["deadline_at"], f"{label}.deadline_at")
    _sha(data["transaction_identity"], f"{label}.transaction_identity")
    _sha(data["inner_transition_identity"], f"{label}.inner_transition_identity")
    steps = _integer(
        data["production_steps_committed"],
        f"{label}.production_steps_committed",
        minimum=1,
    )
    if post["production_step_count"] - pre["production_step_count"] != steps:
        raise C8FTraceError(f"{label} production step delta不匹配")
    event_ids = _exact_list(
        data["runtime_event_identities"], f"{label}.runtime_events"
    )
    event_kinds = _exact_list(
        data["runtime_event_kinds"], f"{label}.runtime_kinds"
    )
    if len(event_ids) != len(event_kinds) or not event_ids:
        raise C8FTraceError(f"{label} runtime event evidence为空/不齐")
    for item in event_ids:
        _sha(item, f"{label}.runtime_event_identity")
    for item in event_kinds:
        _text(item, f"{label}.runtime_event_kind")
    controller_ids = _exact_list(
        data["controller_event_identities"], f"{label}.controller_events"
    )
    for item in controller_ids:
        _sha(item, f"{label}.controller_event_identity")

    if marker == C8FDecisionMarkerV1.NORMAL_ON_TIME.value:
        if tick >= deadline or data["deadline_relation"] != "LT":
            raise C8FTraceError("on-time action必须严格早于deadline")
        if data["timeout_due_commitment"] is not None:
            raise C8FTraceError("on-time action禁止timeout due commitment")
        if data["b_timeout_receipt_identity"] is not None:
            raise C8FTraceError("on-time action禁止B timeout receipt")
        if data["c_controller_result"] is not None or controller_ids:
            raise C8FTraceError("on-time action禁止C timeout result/events")
        receipt = _validate_on_time_receipt(
            data["on_time_receipt"],
            label=f"{label}.on_time_receipt",
            ref_identity=ref_identity,
            selected_action_id=selected_action_id,
            pre=pre,
            post=post,
        )
        if data["transaction_identity"] != receipt["inner_transition_identity"]:
            raise C8FTraceError("on-time transaction/transition identity不匹配")
        if (
            "INNER_SIGNED_ACTION_FORWARDED" not in event_kinds
            or "WINDOW_CLOSED_BY_ACTION" not in event_kinds
        ):
            raise C8FTraceError("on-time runtime event chain不完整")
    else:
        if tick != deadline or data["deadline_relation"] != "EQ":
            raise C8FTraceError("timeout必须发生在exact deadline boundary")
        if data["on_time_receipt"] is not None:
            raise C8FTraceError("timeout禁止伪装on-time receipt")
        due = runtime_v1.TimeoutDueCommitmentV1.from_dict(
            data["timeout_due_commitment"]
        )
        if due.now_tick != deadline or due.deadline_at != deadline:
            raise C8FTraceError("timeout due tick/deadline不匹配")
        result = controller_v1.TimeoutControllerResultV1.from_public_dict_v1(
            data["c_controller_result"]
        )
        if result.result_kind not in {
            controller_v1.ControllerResultKindV1.RESOLVED_SINGLE.value,
            controller_v1.ControllerResultKindV1.RESOLVED_CHAIN.value,
        }:
            raise C8FTraceError("timeout controller未committed resolution")
        if (
            result.transaction_identity != data["transaction_identity"]
            or result.window_authority_ref_identity != ref_identity
        ):
            raise C8FTraceError("timeout transaction/window ref identity不匹配")
        if tuple(result.event_identities) != tuple(controller_ids):
            raise C8FTraceError("timeout controller event chain不匹配")
        if len(result.selected_actions) != 1:
            raise C8FTraceError("bounded trace只允许single-step timeout cell")
        selected = result.selected_actions[0]
        if (
            selected.signed_action_id != selected_action_id
            or selected.public_ordinal != selected_ordinal
            or selected.legal_set_identity != legal_set_identity
        ):
            raise C8FTraceError("timeout selected action/legal set不匹配")
        receipt_identity = _sha(
            data["b_timeout_receipt_identity"],
            f"{label}.b_timeout_receipt_identity",
        )
        if tuple(result.receipt_identities) != (receipt_identity,):
            raise C8FTraceError("timeout B receipt/result mismatch")
        required = {
            "TIME_INPUT_ACCEPTED", "DEADLINE_DERIVED",
            "TIMEOUT_SIGNED_ACTION_FORWARDED", "WINDOW_CLOSED_BY_TIMEOUT",
        }
        if not required.issubset(set(event_kinds)):
            raise C8FTraceError("timeout runtime event chain不完整")
    return data


_WINDOW_KEYS = frozenset(
    {
        "schema", "contract_version", "runtime_state_before_open_identity",
        "runtime_event_chain_before_open_identity", "open_window",
        "window_authority_ref", "runtime_state_after_open_identity",
        "runtime_event_chain_after_open_identity", "closed_window_state_identity",
        "close_status", "runtime_state_after_close_identity",
        "runtime_event_chain_after_close_identity", "active_window_after_close",
        "window_evidence_identity",
    }
)


def _validate_window(value: object, label: str) -> dict[str, Any]:
    data = _identity_object(
        value,
        keys=_WINDOW_KEYS,
        identity_key="window_evidence_identity",
        label=label,
    )
    _contract_version_one(data["contract_version"], f"{label}.contract_version")
    if data["schema"] != "sgs-c8-f-window-lifecycle-evidence-v1":
        raise C8FTraceError(f"{label} schema/version不匹配")
    open_window = clock_v1.TimedDecisionWindowV1.from_dict(data["open_window"])
    ref = runtime_v1.WindowAuthorityRefV1.from_dict(data["window_authority_ref"])
    if (
        open_window.window_id != ref.window_id
        or open_window.window_binding_identity != ref.window_binding_identity
    ):
        raise C8FTraceError(f"{label} window/ref binding不匹配")
    for name in (
        "runtime_state_before_open_identity", "runtime_event_chain_before_open_identity",
        "runtime_state_after_open_identity", "runtime_event_chain_after_open_identity",
        "closed_window_state_identity", "runtime_state_after_close_identity",
        "runtime_event_chain_after_close_identity",
    ):
        _sha(data[name], f"{label}.{name}")
    if data["close_status"] not in {"CLOSED_BY_ACTION", "CLOSED_BY_TIMEOUT"}:
        raise C8FTraceError(f"{label} close status不匹配")
    if data["active_window_after_close"] is not None:
        raise C8FTraceError(f"{label} window close后仍active")
    return data


_CELL_KEYS = frozenset(
    {
        "schema", "contract_version", "trace_id", "scope_marker",
        "cell_sequence", "seed", "current_c8_implementation_identity",
        "contract_bindings", "decision_marker", "decision_context",
        "window_evidence", "refresh_evidence", "proposal_evidence",
        "execution_evidence", "pre_state", "post_state",
        "previous_cell_identity", "cell_identity",
    }
)


def _validate_cell(
    value: object,
    *,
    expected_sequence: int,
    expected_previous: str,
    seed: int,
    session_identity: str,
    current_identity: str,
    bindings: Mapping[str, object],
) -> dict[str, Any]:
    label = f"cells[{expected_sequence-1}]"
    data = _identity_object(
        value, keys=_CELL_KEYS, identity_key="cell_identity", label=label
    )
    _contract_version_one(data["contract_version"], f"{label}.contract_version")
    _integer(data["cell_sequence"], f"{label}.cell_sequence", minimum=1)
    _integer(data["seed"], f"{label}.seed")
    if (
        data["schema"] != C8_F_CELL_SCHEMA
        or data["trace_id"] != C8_F_TRACE_ID
        or data["scope_marker"] != C8_F_SCOPE_MARKER
        or data["cell_sequence"] != expected_sequence
        or data["seed"] != seed
        or data["current_c8_implementation_identity"] != current_identity
        or data["contract_bindings"] != bindings
        or data["previous_cell_identity"] != expected_previous
    ):
        raise C8FTraceError(f"{label} header/chain binding不匹配")
    marker = _text(data["decision_marker"], f"{label}.decision_marker")
    expected_marker = (
        C8FDecisionMarkerV1.TIMEOUT_EXACT_BOUNDARY.value
        if expected_sequence in C8_F_TRACE_A_TIMEOUT_WINDOWS
        else C8FDecisionMarkerV1.NORMAL_ON_TIME.value
    )
    if marker != expected_marker:
        raise C8FTraceError(f"{label}不符合frozen interleave schedule")
    context = _validate_context(data["decision_context"], f"{label}.context")
    window = _validate_window(data["window_evidence"], f"{label}.window")
    refresh = _validate_refresh(data["refresh_evidence"], f"{label}.refresh")
    pre = _validate_state(data["pre_state"], f"{label}.pre_state")
    post = _validate_state(data["post_state"], f"{label}.post_state")
    open_window = _exact_dict(window["open_window"], f"{label}.open_window")
    ref = _exact_dict(window["window_authority_ref"], f"{label}.ref")
    for state_name, context_name in (
        ("phase", "phase"), ("turn_number", "turn_number"),
        ("current_actor_id", "current_actor_id"),
        ("current_player_id", "current_player_id"),
        ("state_revision", "state_revision"),
        ("production_step_count", "step_count"),
    ):
        if pre[state_name] != context[context_name]:
            raise C8FTraceError(f"{label} pre/context {state_name}不匹配")
    if (
        pre["active_window_id"] != ref["window_id"]
        or post["active_window_id"] is not None
        or ref["decision_identity"] != context["decision_identity"]
        or ref["obligation_identity"] != context["obligation_identity"]
        or ref["actor_id"] != context["current_actor_id"]
        or ref["window_kind"] != context["window_kind"]
        or refresh["context_before_identity"] != context["context_identity"]
        or refresh["window_ref_before_identity"] != ref["authority_ref_identity"]
        or refresh["deadline_before"] != open_window["deadline_at"]
    ):
        raise C8FTraceError(f"{label} context/window/refresh continuity不匹配")
    proposal = _validate_proposal(
        data["proposal_evidence"],
        label=f"{label}.proposal",
        session_identity=session_identity,
        context=context,
        marker=marker,
    )
    execution = _validate_execution(
        data["execution_evidence"],
        label=f"{label}.execution",
        marker=marker,
        ref_identity=ref["authority_ref_identity"],
        selected_action_id=proposal["selected_signed_action_id"],
        selected_ordinal=proposal["selected_public_ordinal"],
        legal_set_identity=proposal["c8_c_legal_set_identity"],
        pre=pre,
        post=post,
    )
    if (
        execution["deadline_at"] != open_window["deadline_at"]
        or window["runtime_state_after_open_identity"] != pre["runtime_state_identity"]
        or window["runtime_state_after_close_identity"] != post["runtime_state_identity"]
        or window["runtime_event_chain_after_close_identity"]
        != post["runtime_event_chain_tip"]
    ):
        raise C8FTraceError(f"{label} execution/window state continuity不匹配")
    expected_close = (
        "CLOSED_BY_TIMEOUT"
        if marker == C8FDecisionMarkerV1.TIMEOUT_EXACT_BOUNDARY.value
        else "CLOSED_BY_ACTION"
    )
    if window["close_status"] != expected_close:
        raise C8FTraceError(f"{label} close status/decision marker不匹配")
    if (
        pre["production_execution_identity"] == post["production_execution_identity"]
        or pre["adapter_public_state_identity"] == post["adapter_public_state_identity"]
        or pre["adapter_authoritative_state_identity"]
        == post["adapter_authoritative_state_identity"]
    ):
        raise C8FTraceError(f"{label} production step未改变bound identities")
    return data


_REJECTION_KEYS = frozenset(
    {
        "schema", "contract_version", "rejection_kind", "stale_cell_sequence",
        "stale_legal_set_identity", "stale_context_identity",
        "stale_window_ref_identity", "current_context_identity",
        "current_turn_number", "current_actor_id", "outcome", "result_identity",
        "runtime_state_before_identity", "runtime_state_after_identity",
        "rejected", "rejection_evidence_identity",
    }
)


def _validate_rejection(value: object, label: str) -> dict[str, Any]:
    data = _identity_object(
        value,
        keys=_REJECTION_KEYS,
        identity_key="rejection_evidence_identity",
        label=label,
    )
    _contract_version_one(data["contract_version"], f"{label}.contract_version")
    if data["schema"] != "sgs-c8-f-stale-evidence-rejection-v1":
        raise C8FTraceError(f"{label} schema/version不匹配")
    _text(data["rejection_kind"], f"{label}.kind")
    _integer(data["stale_cell_sequence"], f"{label}.stale_cell", minimum=1)
    for name in (
        "stale_legal_set_identity", "stale_context_identity",
        "stale_window_ref_identity", "current_context_identity",
        "result_identity", "runtime_state_before_identity",
        "runtime_state_after_identity",
    ):
        _sha(data[name], f"{label}.{name}")
    _integer(data["current_turn_number"], f"{label}.turn", minimum=1)
    _text_id(data["current_actor_id"], f"{label}.actor")
    _text(data["outcome"], f"{label}.outcome")
    if data["rejected"] is not True or data[
        "runtime_state_before_identity"
    ] != data["runtime_state_after_identity"]:
        raise C8FTraceError(f"{label} rejection不是fail-closed/no-mutation")
    return data


_TRACE_KEYS = frozenset(
    {
        "schema", "contract_version", "trace_id", "scope_marker",
        "contract_identity", "development_identity", "source_sha256",
        "test_sha256", "prior_current_c8_implementation_identity",
        "current_c8_implementation_identity", "audited_dependency_hashes",
        "contract_bindings", "dependency_hash_set_identity",
        "contract_binding_set_identity", "driver_policy",
        "driver_policy_identity", "seed", "mode_id", "mode_contract_id",
        "profile_identity", "session_binding_identity",
        "runtime_instance_identity", "controller_instance_identity",
        "fresh_session_execution_identity", "prelude_signed_action_ids",
        "initial_trace_state", "max_bounded_production_steps", "max_windows",
        "cells", "stale_rejection_evidence", "final_bounded_state",
        "windows_executed", "trace_production_steps_executed",
        "total_session_steps", "bounded_limit_reached", "stop_reason",
        "multiwindow_timed_proof", "turn_boundary_proof",
        "on_time_timeout_interleave", "nested_response_dying_status",
        "private_mandatory_choice_status", "mode_decision_status",
        "skill_multi_step_status", "production_session_finished",
        "terminal_claimed", "full_game", "formal_matrix",
        "production_cold_replay", "evidence_chain_tip",
        "semantic_trace_identity", "trace_identity",
    }
)


def _production_continuity_equal(
    first: Mapping[str, object], second: Mapping[str, object]
) -> bool:
    fields = (
        "phase", "turn_number", "current_actor_id", "current_player_id",
        "state_revision", "production_step_count", "adapter_public_state_identity",
        "adapter_authoritative_state_identity", "production_execution_identity",
        "virtual_tick",
    )
    return all(first[name] == second[name] for name in fields)


def _validate_trace_document(
    value: object,
    *,
    repo_root: Path | str | None = None,
) -> dict[str, Any]:
    data = _exact_keys(value, _TRACE_KEYS, "trace")
    _assert_no_private_keys(data)
    _contract_version_one(data["contract_version"], "trace.contract_version")
    if (
        data["schema"] != C8_F_TRACE_SCHEMA
        or data["trace_id"] != C8_F_TRACE_ID
        or data["scope_marker"] != C8_F_SCOPE_MARKER
        or data["contract_identity"] != C8_F_CONTRACT_IDENTITY
    ):
        raise C8FTraceError("trace schema/contract/scope不匹配")
    current = current_c8_f_development_snapshot_v1(repo_root)
    dependencies = _exact_dict(current["dependencies"], "current.dependencies")
    expected = {
        "development_identity": current["development_identity"],
        "source_sha256": current["source_sha256"],
        "test_sha256": current["test_sha256"],
        "prior_current_c8_implementation_identity": dependencies[
            "prior_current_c8_implementation_identity"
        ],
        "current_c8_implementation_identity": current[
            "current_c8_implementation_identity"
        ],
        "audited_dependency_hashes": dependencies["audited_hashes"],
        "contract_bindings": dependencies["contract_bindings"],
        "dependency_hash_set_identity": dependencies[
            "dependency_hash_set_identity"
        ],
        "contract_binding_set_identity": dependencies[
            "contract_binding_set_identity"
        ],
        "driver_policy": dict(_DRIVER_POLICY),
        "driver_policy_identity": C8_F_DRIVER_POLICY_IDENTITY,
    }
    for name, expected_value in expected.items():
        if not _same_json_value(data[name], expected_value):
            raise C8FTraceError(f"trace {name} drift")
    if _integer(data["seed"], "trace.seed") != C8_F_TRACE_A_SEED:
        raise C8FTraceError("TRACE-A seed必须为0")
    if data["mode_id"] != FORMAL_NO_SKILL_IDENTITY_8P_MODE:
        raise C8FTraceError("trace mode不是canonical C6 8p")
    _text(data["mode_contract_id"], "trace.mode_contract_id")
    for name in (
        "profile_identity", "session_binding_identity", "runtime_instance_identity",
        "controller_instance_identity", "fresh_session_execution_identity",
    ):
        _sha(data[name], f"trace.{name}")
    prelude = _exact_list(data["prelude_signed_action_ids"], "trace.prelude")
    if len(prelude) != 3 or any(type(item) is not str or not item for item in prelude):
        raise C8FTraceError("TRACE-A prelude必须恰为3个production signed steps")
    initial = _validate_state(data["initial_trace_state"], "trace.initial_state")
    if (
        initial["phase"] != ProductionPhase.PLAY.value
        or initial["turn_number"] != 1
        or initial["production_step_count"] != 3
        or initial["active_window_id"] is not None
    ):
        raise C8FTraceError("TRACE-A initial state不是first PLAY pre-window")
    max_steps = _integer(
        data["max_bounded_production_steps"],
        "trace.max_bounded_production_steps",
        minimum=1,
    )
    max_windows = _integer(data["max_windows"], "trace.max_windows", minimum=1)
    if (
        max_steps
        != C8_F_MAX_BOUNDED_PRODUCTION_STEPS
        or max_windows != C8_F_MAX_WINDOWS
    ):
        raise C8FTraceError("bounded limits drift")

    bindings = _exact_dict(data["contract_bindings"], "trace.contract_bindings")
    cells = _exact_list(data["cells"], "trace.cells")
    if len(cells) != C8_F_MAX_WINDOWS:
        raise C8FTraceError("TRACE-A必须恰为8个bounded windows")
    genesis = _identity(
        {
            "schema": "sgs-c8-f-cell-chain-genesis-v1",
            "contract_identity": C8_F_CONTRACT_IDENTITY,
            "development_identity": data["development_identity"],
            "current_c8_implementation_identity": data[
                "current_c8_implementation_identity"
            ],
            "seed": data["seed"],
            "session_binding_identity": data["session_binding_identity"],
        }
    )
    previous_identity = genesis
    previous_post = initial
    seen_contexts: set[str] = set()
    validated_cells: list[dict[str, Any]] = []
    for sequence, raw_cell in enumerate(cells, start=1):
        cell = _validate_cell(
            raw_cell,
            expected_sequence=sequence,
            expected_previous=previous_identity,
            seed=data["seed"],
            session_identity=data["session_binding_identity"],
            current_identity=data["current_c8_implementation_identity"],
            bindings=bindings,
        )
        window = _exact_dict(cell["window_evidence"], "cell.window")
        pre = _exact_dict(cell["pre_state"], "cell.pre")
        post = _exact_dict(cell["post_state"], "cell.post")
        context = _exact_dict(cell["decision_context"], "cell.context")
        if window["runtime_state_before_open_identity"] != previous_post[
            "runtime_state_identity"
        ]:
            raise C8FTraceError("window open不是从前一bounded state连续开始")
        if not _production_continuity_equal(previous_post, pre):
            raise C8FTraceError("相邻windows production continuity断裂")
        parent_context = context["parent_context_identity"]
        if parent_context is not None and parent_context not in seen_contexts:
            raise C8FTraceError("production context parent lineage未知")
        seen_contexts.add(context["context_identity"])
        previous_identity = cell["cell_identity"]
        previous_post = post
        validated_cells.append(cell)

    rejections = _exact_list(
        data["stale_rejection_evidence"], "trace.stale_rejections"
    )
    expected_kinds = (
        "STALE_CONTEXT_WINDOW_BIND",
        "STALE_TIMEOUT_DUE_AND_WINDOW_REF",
        "STALE_SIGNED_ACTION_FROM_PRIOR_LEGAL_SET",
    )
    if len(rejections) != len(expected_kinds):
        raise C8FTraceError("stale evidence rejection coverage不完整")
    first = validated_cells[0]
    fifth = validated_cells[4]
    first_context = _exact_dict(first["decision_context"], "first.context")
    first_window = _exact_dict(first["window_evidence"], "first.window")
    first_ref = _exact_dict(first_window["window_authority_ref"], "first.ref")
    first_proposal = _exact_dict(first["proposal_evidence"], "first.proposal")
    fifth_context = _exact_dict(fifth["decision_context"], "fifth.context")
    for index, expected_kind in enumerate(expected_kinds):
        rejection = _validate_rejection(rejections[index], f"rejections[{index}]")
        if (
            rejection["rejection_kind"] != expected_kind
            or rejection["stale_cell_sequence"] != 1
            or rejection["stale_legal_set_identity"]
            != first_proposal["f_legal_set_identity"]
            or rejection["stale_context_identity"]
            != first_context["context_identity"]
            or rejection["stale_window_ref_identity"]
            != first_ref["authority_ref_identity"]
            or rejection["current_context_identity"]
            != fifth_context["context_identity"]
            or rejection["current_turn_number"] != 2
        ):
            raise C8FTraceError("stale rejection没有绑定跨turn旧证据")

    final = _validate_state(data["final_bounded_state"], "trace.final_state")
    if final != previous_post:
        raise C8FTraceError("final bounded state与最后cell不一致")
    windows_executed = _integer(
        data["windows_executed"], "trace.windows_executed", minimum=1
    )
    trace_steps = _integer(
        data["trace_production_steps_executed"],
        "trace.trace_production_steps_executed",
        minimum=1,
    )
    total_steps = _integer(
        data["total_session_steps"], "trace.total_session_steps", minimum=1
    )
    if (
        windows_executed != len(cells)
        or trace_steps != 8
        or total_steps != final["production_step_count"]
        or total_steps != 11
        or total_steps > max_steps
    ):
        raise C8FTraceError("bounded step/window counts不匹配")
    markers = [cell["decision_marker"] for cell in validated_cells]
    transitions = sum(
        1 for before, after in zip(markers, markers[1:]) if before != after
    )
    if transitions < 3:
        raise C8FTraceError("timeout/on-time未形成交错")
    actors = [
        _exact_dict(cell["pre_state"], "cell.pre")["current_actor_id"]
        for cell in validated_cells
    ]
    turns = [
        _exact_dict(cell["pre_state"], "cell.pre")["turn_number"]
        for cell in validated_cells
    ]
    if len(set(actors)) < 2 or max(turns) <= min(turns):
        raise C8FTraceError("TRACE-A未跨actor/turn boundary")
    required_claims = {
        "bounded_limit_reached": False,
        "stop_reason": "TRACE_A_TARGET_REACHED_BEFORE_LIMIT",
        "multiwindow_timed_proof": "PROVEN_PROVISIONAL_PENDING_AUDIT",
        "turn_boundary_proof": "PROVEN_PROVISIONAL_PENDING_AUDIT",
        "on_time_timeout_interleave": "PROVEN_PROVISIONAL_PENDING_AUDIT",
        "nested_response_dying_status": C8_F_NESTED_STATUS,
        "private_mandatory_choice_status": "NOT_CLAIMED_AS_TIMEOUT_PROOF",
        "mode_decision_status": C8_F_MODE_DECISION_STATUS,
        "skill_multi_step_status": C8_F_MODE_DECISION_STATUS,
        "production_session_finished": False,
        "terminal_claimed": False,
        "full_game": False,
        "formal_matrix": False,
        "production_cold_replay": C8_F_PRODUCTION_COLD_REPLAY,
        "evidence_chain_tip": previous_identity,
    }
    for name, expected_value in required_claims.items():
        if not _same_json_value(data[name], expected_value):
            raise C8FTraceError(f"claim boundary drift: {name}")
    if (
        final["phase"] != ProductionPhase.DISCARD.value
        or final["turn_number"] != 2
    ):
        raise C8FTraceError("TRACE-A final bounded state不匹配")
    semantic = _identity(_semantic_trace_material(data))
    if data["semantic_trace_identity"] != semantic:
        raise C8FTraceError("semantic trace identity不匹配")
    supplied_trace_identity = _sha(data["trace_identity"], "trace.trace_identity")
    material = {key: item for key, item in data.items() if key != "trace_identity"}
    if supplied_trace_identity != _identity(material):
        raise C8FTraceError("trace identity不匹配")
    return data


@dataclass(frozen=True, slots=True)
class C8FBoundedTraceV1:
    """Immutable canonical JSON wrapper; deserialization is never authority."""

    _encoded: bytes

    @classmethod
    def from_dict(
        cls,
        value: object,
        *,
        repo_root: Path | str | None = None,
    ) -> "C8FBoundedTraceV1":
        validated = _validate_trace_document(value, repo_root=repo_root)
        return cls(_canonical_bytes(validated))

    @classmethod
    def from_json_bytes_v1(
        cls,
        raw: bytes | str,
        *,
        repo_root: Path | str | None = None,
    ) -> "C8FBoundedTraceV1":
        return cls.from_dict(_strict_json(raw), repo_root=repo_root)

    def to_dict(self) -> dict[str, Any]:
        return _strict_json(self._encoded)

    def to_json_bytes_v1(self) -> bytes:
        return self._encoded

    @property
    def trace_identity(self) -> str:
        return _text(self.to_dict()["trace_identity"], "trace_identity")

    @property
    def semantic_trace_identity(self) -> str:
        return _text(
            self.to_dict()["semantic_trace_identity"], "semantic_trace_identity"
        )

    @property
    def current_c8_implementation_identity(self) -> str:
        return _text(
            self.to_dict()["current_c8_implementation_identity"],
            "current_c8_implementation_identity",
        )


def _runtime_event_evidence(
    events: Sequence[runtime_v1.RuntimeEventV1],
) -> tuple[list[str], list[str], str]:
    identities = [item.event_identity for item in events]
    kinds = [item.event_kind.value for item in events]
    transition = tuple(
        item.inner_transition_identity
        for item in events
        if item.inner_transition_identity is not None
    )
    if len(transition) != 1:
        raise C8FTraceError("每个bounded cell必须恰有一个inner transition")
    return identities, kinds, transition[0]


def _make_timeout_due(
    *,
    adapter: prod.C8C6ProductionAdapterV1,
    runtime: runtime_v1.C8TimedSessionRuntimeV1,
    ref: runtime_v1.WindowAuthorityRefV1,
    deadline_at: int,
) -> runtime_v1.TimeoutDueCommitmentV1:
    advance = adapter.issue_virtual_time_advance_v1(requested_tick=deadline_at)
    result = runtime.ingest_virtual_time_input(
        advance,
        expected_previous_input_chain_tip=runtime.state.input_chain_tip,
        duration_profile_identity=clock_v1.ENGINEERING_TEST_PROFILE_V1.profile_identity,
    )
    if result.derived_deadline is None:
        raise C8FTraceError("exact deadline advance未导出timeout evidence")
    commitment = runtime.current_timeout_due_commitment_v1(ref)
    if type(commitment) is not runtime_v1.TimeoutDueCommitmentV1:
        raise C8FTraceError("runtime未签发current timeout due commitment")
    return commitment


def _exception_rejection_identity(kind: str, exc: BaseException) -> str:
    return _identity(
        {
            "schema": "sgs-c8-f-exception-rejection-result-v1",
            "contract_version": 1,
            "rejection_kind": kind,
            "exception_type": type(exc).__name__,
            "rejected": True,
        }
    )


def run_trace_a_v1(
    *,
    repo_root: Path | str | None = None,
    run_label: str = "primary",
) -> C8FBoundedTraceV1:
    """Run the frozen seed-0 eight-window bounded production trace."""

    if type(run_label) is not str or _RUN_LABEL_RE.fullmatch(run_label) is None:
        raise C8FTraceError("run_label必须是短小lowercase deterministic label")
    root = _repo_root() if repo_root is None else Path(repo_root).resolve()
    development = current_c8_f_development_snapshot_v1(root)
    dependencies = _exact_dict(development["dependencies"], "dependencies")
    bindings = _exact_dict(dependencies["contract_bindings"], "contract_bindings")

    spec = canonical_no_skill_mode_v1(FORMAL_NO_SKILL_IDENTITY_8P_MODE)
    session = prod.create_canonical_c6_no_skill_session_v1(C8_F_TRACE_A_SEED)
    fresh_execution_identity = session.execution_hash
    prelude = prod.advance_canonical_c6_to_first_play_v1(session)
    adapter = prod.C8C6ProductionAdapterV1(session)
    instance_nonce_identity = _identity(
        {"scope": "C8_F_TRACE_A", "run_label": run_label, "kind": "runtime"}
    )
    driver_authority_identity = _identity(
        {"scope": "C8_F_TRACE_A", "run_label": run_label, "kind": "driver"}
    )
    controller_identity = _identity(
        {"scope": "C8_F_TRACE_A", "run_label": run_label, "kind": "controller"}
    )
    runtime = runtime_v1.C8TimedSessionRuntimeV1(
        inner_adapter=adapter,
        input_authenticator=adapter,
        instance_nonce_identity=instance_nonce_identity,
        input_source_id=f"c8-f-trace-a-{run_label}",
        driver_authority_identity=driver_authority_identity,
    )
    adapter.bind_runtime_v1(runtime, controller_identity=controller_identity)
    orchestrator = prod.C8C6ProductionWindowOrchestratorV1(adapter, runtime)
    controller = controller_v1.TimeoutResolverControllerIntegrationV1(
        runtime,
        adapter,
        controller_instance_identity=controller_identity,
    )
    initial_state = _capture_state(session, adapter, runtime, controller)
    genesis = _identity(
        {
            "schema": "sgs-c8-f-cell-chain-genesis-v1",
            "contract_identity": C8_F_CONTRACT_IDENTITY,
            "development_identity": development["development_identity"],
            "current_c8_implementation_identity": development[
                "current_c8_implementation_identity"
            ],
            "seed": C8_F_TRACE_A_SEED,
            "session_binding_identity": adapter.session_binding_identity_v1(),
        }
    )
    previous_cell_identity = genesis
    cells: list[dict[str, object]] = []
    stale_rejections: list[dict[str, object]] = []
    first_timeout_context: prod.ProductionDecisionContextV1 | None = None
    first_timeout_ref: runtime_v1.WindowAuthorityRefV1 | None = None
    first_timeout_due: runtime_v1.TimeoutDueCommitmentV1 | None = None
    first_timeout_f_legal_set_identity: str | None = None
    first_timeout_action_id: str | None = None

    for sequence in range(1, C8_F_MAX_WINDOWS + 1):
        if session.step_count >= C8_F_MAX_BOUNDED_PRODUCTION_STEPS:
            raise C8FTraceError("BOUNDED_LIMIT_REACHED before TRACE-A target")
        runtime_state_before_open = runtime.state.state_identity
        event_chain_before_open = runtime.state.event_chain_tip
        runtime_event_start = len(runtime.state.runtime_events)
        controller_event_start = len(controller.public_event_trace_v1())
        context, ref, opened = orchestrator.observe_and_open_or_refresh_v1()
        if opened is not True:
            raise C8FTraceError("new production context没有open新window")
        active = runtime.state.virtual_time_state.window_stack.active_window
        if active is None:
            raise C8FTraceError("opened production context没有active window")
        open_window_dict = active.to_dict()
        runtime_state_after_open = runtime.state.state_identity
        event_chain_after_open = runtime.state.event_chain_tip

        refresh_state_before = runtime.state.state_identity
        refreshed_context, refreshed_ref, refresh_opened = (
            orchestrator.observe_and_open_or_refresh_v1()
        )
        refreshed_active = runtime.state.virtual_time_state.window_stack.active_window
        if refreshed_active is None:
            raise C8FTraceError("same-context refresh丢失active window")
        refresh = _build_refresh_evidence(
            before_context=context,
            after_context=refreshed_context,
            before_ref=ref,
            after_ref=refreshed_ref,
            opened=refresh_opened,
            deadline_before=active.deadline_at,
            deadline_after=refreshed_active.deadline_at,
            runtime_state_before=refresh_state_before,
            runtime_state_after=runtime.state.state_identity,
        )
        pre_state = _capture_state(session, adapter, runtime, controller)
        action_ids = _public_action_ids(session)
        marker = (
            C8FDecisionMarkerV1.TIMEOUT_EXACT_BOUNDARY
            if sequence in C8_F_TRACE_A_TIMEOUT_WINDOWS
            else C8FDecisionMarkerV1.NORMAL_ON_TIME
        )

        # At turn two, prove first-turn evidence is stale and state-neutral.
        if sequence == 5:
            if (
                first_timeout_context is None
                or first_timeout_ref is None
                or first_timeout_due is None
                or first_timeout_f_legal_set_identity is None
                or first_timeout_action_id is None
            ):
                raise C8FTraceError("cross-turn stale probes缺少first-window evidence")
            stale_before = runtime.state.state_identity
            try:
                adapter.bind_window_authority_v1(
                    first_timeout_ref, first_timeout_context
                )
            except prod.C8C6ProductionAdapterError as exc:
                stale_rejections.append(
                    _build_rejection(
                        kind="STALE_CONTEXT_WINDOW_BIND",
                        stale_cell_sequence=1,
                        stale_legal_set_identity=first_timeout_f_legal_set_identity,
                        stale_context_identity=first_timeout_context.context_identity,
                        stale_window_ref_identity=first_timeout_ref.authority_ref_identity,
                        current_context_identity=context.context_identity,
                        current_turn_number=context.turn_number,
                        current_actor_id=context.current_actor_id,
                        outcome="C8C6ProductionAdapterError",
                        result_identity=_exception_rejection_identity(
                            "STALE_CONTEXT_WINDOW_BIND", exc
                        ),
                        runtime_before=stale_before,
                        runtime_after=runtime.state.state_identity,
                    )
                )
            else:
                raise C8FTraceError("stale context/window被错误接受")

            stale_before = runtime.state.state_identity
            stale_result = controller.resolve_timeout_v1(
                first_timeout_ref,
                timeout_due_commitment=first_timeout_due,
            )
            if (
                stale_result.result_kind
                != controller_v1.ControllerResultKindV1.FAILED_ROLLED_BACK.value
                or stale_result.reason != "TIMEOUT_DUE_PRECONDITION_REJECTED"
            ):
                raise C8FTraceError("stale timeout due/window ref未fail closed")
            stale_rejections.append(
                _build_rejection(
                    kind="STALE_TIMEOUT_DUE_AND_WINDOW_REF",
                    stale_cell_sequence=1,
                    stale_legal_set_identity=first_timeout_f_legal_set_identity,
                    stale_context_identity=first_timeout_context.context_identity,
                    stale_window_ref_identity=first_timeout_ref.authority_ref_identity,
                    current_context_identity=context.context_identity,
                    current_turn_number=context.turn_number,
                    current_actor_id=context.current_actor_id,
                    outcome=stale_result.reason,
                    result_identity=stale_result.result_identity,
                    runtime_before=stale_before,
                    runtime_after=runtime.state.state_identity,
                )
            )

            stale_before = runtime.state.state_identity
            try:
                runtime.forward_on_time_signed_action_id(
                    ref, signed_action_id=first_timeout_action_id
                )
            except runtime_v1.C8TimedSessionRuntimeError as exc:
                stale_rejections.append(
                    _build_rejection(
                        kind="STALE_SIGNED_ACTION_FROM_PRIOR_LEGAL_SET",
                        stale_cell_sequence=1,
                        stale_legal_set_identity=first_timeout_f_legal_set_identity,
                        stale_context_identity=first_timeout_context.context_identity,
                        stale_window_ref_identity=first_timeout_ref.authority_ref_identity,
                        current_context_identity=context.context_identity,
                        current_turn_number=context.turn_number,
                        current_actor_id=context.current_actor_id,
                        outcome="C8TimedSessionRuntimeError",
                        result_identity=_exception_rejection_identity(
                            "STALE_SIGNED_ACTION_FROM_PRIOR_LEGAL_SET", exc
                        ),
                        runtime_before=stale_before,
                        runtime_after=runtime.state.state_identity,
                    )
                )
            else:
                raise C8FTraceError("stale signed action被错误接受")

        c8_c_legal_set_identity: str | None = None
        e_snapshot_identity: str | None = None
        timeout_due_dict: dict[str, object] | None = None
        controller_result_dict: dict[str, object] | None = None
        b_receipt_identity: str | None = None
        on_time_receipt: dict[str, object] | None = None

        if marker is C8FDecisionMarkerV1.TIMEOUT_EXACT_BOUNDARY:
            before_snapshots = len(adapter.public_legal_set_evidence_v1())
            due = _make_timeout_due(
                adapter=adapter,
                runtime=runtime,
                ref=ref,
                deadline_at=active.deadline_at,
            )
            result = controller.resolve_timeout_v1(ref, timeout_due_commitment=due)
            if result.result_kind != (
                controller_v1.ControllerResultKindV1.RESOLVED_SINGLE.value
            ):
                raise C8FTraceError(
                    f"bounded timeout未single-step commit: {result.result_kind}"
                )
            orchestrator.confirm_timeout_context_closed_v1(ref, context)
            snapshots = adapter.public_legal_set_evidence_v1()
            if len(snapshots) != before_snapshots + 1:
                raise C8FTraceError("timeout没有恰好一个fresh E legal-set snapshot")
            snapshot = snapshots[-1]
            public_order = tuple(
                item.action_id for item in snapshot.public_legal_set.actions
            )
            if public_order != action_ids:
                raise C8FTraceError("C8-E public proposal order与production不一致")
            selected = result.selected_actions[0]
            selected_ordinal = selected.public_ordinal
            if selected.signed_action_id != action_ids[selected_ordinal]:
                raise C8FTraceError("C8-C selected signed action/ordinal漂移")
            c8_c_legal_set_identity = selected.legal_set_identity
            e_snapshot_identity = snapshot.snapshot_identity
            timeout_due_dict = due.to_dict()
            controller_result_dict = result.to_public_dict_v1()
            b_receipt_identity = selected.receipt_identity
            decision_tick = due.now_tick
            transaction_identity = result.transaction_identity
            if sequence == 1:
                first_timeout_context = context
                first_timeout_ref = ref
                first_timeout_due = due
                first_timeout_action_id = selected.signed_action_id
        else:
            selected_ordinal = len(action_ids) - 1
            selected_action_id = action_ids[selected_ordinal]
            eligibility = runtime.action_eligibility(ref)
            if eligibility is not (
                clock_v1.DeadlinePrecedenceV1.ACTION_ELIGIBLE_BEFORE_DEADLINE
            ):
                raise C8FTraceError("NORMAL_ON_TIME action不在deadline前")
            runtime.forward_on_time_signed_action_id(
                ref, signed_action_id=selected_action_id
            )
            closed = orchestrator.close_completed_on_time_context_v1(ref, context)
            if closed.status is not clock_v1.TimedWindowStatusV1.CLOSED_BY_ACTION:
                raise C8FTraceError("on-time window未按action关闭")
            decision_tick = pre_state["virtual_tick"]
            transaction_identity = ""

        post_state = _capture_state(session, adapter, runtime, controller)
        new_runtime_events = runtime.state.runtime_events[runtime_event_start:]
        event_ids, event_kinds, inner_transition_identity = _runtime_event_evidence(
            new_runtime_events
        )
        new_controller_events = controller.public_event_trace_v1()[
            controller_event_start:
        ]
        controller_event_ids = [
            item.event_identity for item in new_controller_events
        ]
        if marker is C8FDecisionMarkerV1.NORMAL_ON_TIME:
            transaction_identity = inner_transition_identity
            on_time_receipt = _build_on_time_receipt(
                ref=ref,
                signed_action_id=action_ids[selected_ordinal],
                transition_identity=inner_transition_identity,
                pre_state=pre_state,
                post_state=post_state,
            )
        execution_material: dict[str, object] = {
            "schema": "sgs-c8-f-production-execution-evidence-v1",
            "contract_version": 1,
            "decision_marker": marker.value,
            "decision_tick": decision_tick,
            "deadline_at": active.deadline_at,
            "deadline_relation": (
                "EQ"
                if marker is C8FDecisionMarkerV1.TIMEOUT_EXACT_BOUNDARY
                else "LT"
            ),
            "transaction_identity": transaction_identity,
            "timeout_due_commitment": timeout_due_dict,
            "b_timeout_receipt_identity": b_receipt_identity,
            "c_controller_result": controller_result_dict,
            "on_time_receipt": on_time_receipt,
            "production_steps_committed": (
                post_state["production_step_count"]
                - pre_state["production_step_count"]
            ),
            "runtime_event_identities": event_ids,
            "runtime_event_kinds": event_kinds,
            "controller_event_identities": controller_event_ids,
            "inner_transition_identity": inner_transition_identity,
        }
        execution = {
            **execution_material,
            "execution_evidence_identity": _identity(execution_material),
        }
        proposal = _build_proposal_evidence(
            session_identity=adapter.session_binding_identity_v1(),
            context=context,
            action_ids=action_ids,
            selected_ordinal=selected_ordinal,
            marker=marker,
            c8_c_legal_set_identity=c8_c_legal_set_identity,
            e_snapshot_identity=e_snapshot_identity,
        )
        if sequence == 1:
            first_timeout_f_legal_set_identity = _text(
                proposal["f_legal_set_identity"], "first F legal set"
            )
        close_event_kind = (
            runtime_v1.RuntimeEventKindV1.WINDOW_CLOSED_BY_TIMEOUT
            if marker is C8FDecisionMarkerV1.TIMEOUT_EXACT_BOUNDARY
            else runtime_v1.RuntimeEventKindV1.WINDOW_CLOSED_BY_ACTION
        )
        close_events = tuple(
            item for item in new_runtime_events if item.event_kind is close_event_kind
        )
        if len(close_events) != 1:
            raise C8FTraceError("bounded cell缺少唯一window close event")
        close_event = close_events[0]
        window_material: dict[str, object] = {
            "schema": "sgs-c8-f-window-lifecycle-evidence-v1",
            "contract_version": 1,
            "runtime_state_before_open_identity": runtime_state_before_open,
            "runtime_event_chain_before_open_identity": event_chain_before_open,
            "open_window": open_window_dict,
            "window_authority_ref": ref.to_dict(),
            "runtime_state_after_open_identity": runtime_state_after_open,
            "runtime_event_chain_after_open_identity": event_chain_after_open,
            "closed_window_state_identity": close_event.window_state_identity,
            "close_status": (
                "CLOSED_BY_TIMEOUT"
                if marker is C8FDecisionMarkerV1.TIMEOUT_EXACT_BOUNDARY
                else "CLOSED_BY_ACTION"
            ),
            "runtime_state_after_close_identity": runtime.state.state_identity,
            "runtime_event_chain_after_close_identity": runtime.state.event_chain_tip,
            "active_window_after_close": None,
        }
        window = {
            **window_material,
            "window_evidence_identity": _identity(window_material),
        }
        cell_material: dict[str, object] = {
            "schema": C8_F_CELL_SCHEMA,
            "contract_version": 1,
            "trace_id": C8_F_TRACE_ID,
            "scope_marker": C8_F_SCOPE_MARKER,
            "cell_sequence": sequence,
            "seed": C8_F_TRACE_A_SEED,
            "current_c8_implementation_identity": development[
                "current_c8_implementation_identity"
            ],
            "contract_bindings": bindings,
            "decision_marker": marker.value,
            "decision_context": context.to_public_dict_v1(),
            "window_evidence": window,
            "refresh_evidence": refresh,
            "proposal_evidence": proposal,
            "execution_evidence": execution,
            "pre_state": pre_state,
            "post_state": post_state,
            "previous_cell_identity": previous_cell_identity,
        }
        cell = {**cell_material, "cell_identity": _identity(cell_material)}
        cells.append(cell)
        previous_cell_identity = _text(cell["cell_identity"], "cell_identity")

    final_state = _capture_state(session, adapter, runtime, controller)
    if session.is_finished:
        raise C8FTraceError("TRACE-A bounded run禁止自然进入terminal")
    document: dict[str, object] = {
        "schema": C8_F_TRACE_SCHEMA,
        "contract_version": C8_F_TRACE_VERSION,
        "trace_id": C8_F_TRACE_ID,
        "scope_marker": C8_F_SCOPE_MARKER,
        "contract_identity": C8_F_CONTRACT_IDENTITY,
        "development_identity": development["development_identity"],
        "source_sha256": development["source_sha256"],
        "test_sha256": development["test_sha256"],
        "prior_current_c8_implementation_identity": dependencies[
            "prior_current_c8_implementation_identity"
        ],
        "current_c8_implementation_identity": development[
            "current_c8_implementation_identity"
        ],
        "audited_dependency_hashes": dependencies["audited_hashes"],
        "contract_bindings": bindings,
        "dependency_hash_set_identity": dependencies[
            "dependency_hash_set_identity"
        ],
        "contract_binding_set_identity": dependencies[
            "contract_binding_set_identity"
        ],
        "driver_policy": dict(_DRIVER_POLICY),
        "driver_policy_identity": C8_F_DRIVER_POLICY_IDENTITY,
        "seed": C8_F_TRACE_A_SEED,
        "mode_id": FORMAL_NO_SKILL_IDENTITY_8P_MODE,
        "mode_contract_id": spec.mode_contract_id,
        "profile_identity": spec.profile_identity(),
        "session_binding_identity": adapter.session_binding_identity_v1(),
        "runtime_instance_identity": runtime.state.runtime_instance_identity,
        "controller_instance_identity": controller_identity,
        "fresh_session_execution_identity": fresh_execution_identity,
        "prelude_signed_action_ids": list(prelude),
        "initial_trace_state": initial_state,
        "max_bounded_production_steps": C8_F_MAX_BOUNDED_PRODUCTION_STEPS,
        "max_windows": C8_F_MAX_WINDOWS,
        "cells": cells,
        "stale_rejection_evidence": stale_rejections,
        "final_bounded_state": final_state,
        "windows_executed": len(cells),
        "trace_production_steps_executed": (
            final_state["production_step_count"]
            - initial_state["production_step_count"]
        ),
        "total_session_steps": final_state["production_step_count"],
        "bounded_limit_reached": False,
        "stop_reason": "TRACE_A_TARGET_REACHED_BEFORE_LIMIT",
        "multiwindow_timed_proof": "PROVEN_PROVISIONAL_PENDING_AUDIT",
        "turn_boundary_proof": "PROVEN_PROVISIONAL_PENDING_AUDIT",
        "on_time_timeout_interleave": "PROVEN_PROVISIONAL_PENDING_AUDIT",
        "nested_response_dying_status": C8_F_NESTED_STATUS,
        "private_mandatory_choice_status": "NOT_CLAIMED_AS_TIMEOUT_PROOF",
        "mode_decision_status": C8_F_MODE_DECISION_STATUS,
        "skill_multi_step_status": C8_F_MODE_DECISION_STATUS,
        "production_session_finished": False,
        "terminal_claimed": False,
        "full_game": False,
        "formal_matrix": False,
        "production_cold_replay": C8_F_PRODUCTION_COLD_REPLAY,
        "evidence_chain_tip": previous_cell_identity,
    }
    document["semantic_trace_identity"] = _identity(
        _semantic_trace_material(document)
    )
    document["trace_identity"] = _identity(document)
    return C8FBoundedTraceV1.from_dict(document, repo_root=root)


def verify_with_fresh_reexecution_v1(
    trace: C8FBoundedTraceV1 | bytes | str | Mapping[str, object],
    *,
    repo_root: Path | str | None = None,
    run_label: str = "fresh-verifier",
) -> str:
    """Strictly load evidence, then compare with one fresh bounded rerun."""

    root = _repo_root() if repo_root is None else Path(repo_root).resolve()
    if type(trace) is C8FBoundedTraceV1:
        candidate = C8FBoundedTraceV1.from_json_bytes_v1(
            trace.to_json_bytes_v1(), repo_root=root
        )
    elif type(trace) in {bytes, str}:
        candidate = C8FBoundedTraceV1.from_json_bytes_v1(trace, repo_root=root)
    elif isinstance(trace, Mapping):
        candidate = C8FBoundedTraceV1.from_dict(dict(trace), repo_root=root)
    else:
        raise TypeError("fresh verifier只接受C8-F trace/dict/JSON")
    fresh = run_trace_a_v1(repo_root=root, run_label=run_label)
    if candidate.semantic_trace_identity != fresh.semantic_trace_identity:
        raise C8FTraceError("fresh bounded production semantic trace mismatch")
    return fresh.semantic_trace_identity


def write_trace_artifact_v1(
    path: Path | str,
    trace: C8FBoundedTraceV1,
) -> None:
    if type(trace) is not C8FBoundedTraceV1:
        raise TypeError("artifact writer需要exact C8FBoundedTraceV1")
    target = Path(path)
    if not target.parent.is_dir():
        raise C8FTraceError("trace artifact parent directory不存在")
    target.write_bytes(trace.to_json_bytes_v1() + b"\n")


__all__ = [
    "C8FBoundedTraceV1",
    "C8FDecisionMarkerV1",
    "C8FTraceError",
    "C8_F_CONTRACT_IDENTITY",
    "C8_F_DRIVER_POLICY_ID",
    "C8_F_DRIVER_POLICY_IDENTITY",
    "C8_F_FULL_GAME",
    "C8_F_MAX_BOUNDED_PRODUCTION_STEPS",
    "C8_F_MAX_WINDOWS",
    "C8_F_PRODUCTION_COLD_REPLAY",
    "C8_F_SCOPE_MARKER",
    "C8_F_TRACE_ID",
    "C8_F_TRACE_SCHEMA",
    "C8_F_TRACE_VERSION",
    "audited_dependency_snapshot_v1",
    "current_c8_f_development_snapshot_v1",
    "run_trace_a_v1",
    "verify_with_fresh_reexecution_v1",
    "write_trace_artifact_v1",
]
