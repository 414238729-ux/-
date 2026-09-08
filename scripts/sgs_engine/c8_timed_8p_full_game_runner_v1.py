# -*- coding: utf-8 -*-
"""C8-G2 provisional full-game runner/session integration.

This module composes exact C6 with the audited A/B/C/E path. The v4 writer records
typed evidence and a private incremental C6 transcript. A parsed artifact is
data only; the fixed G3 entry performs fresh process verification. Natural full
game execution remains a separately authorized operation.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import argparse
import datetime
import hashlib
import json
import os
import platform
import struct
import sys
import time
from pathlib import Path
import re
from typing import Any, Callable, ClassVar, Final, Mapping, Protocol, Sequence

from . import c8_c6_production_adapter_v1 as prod
from . import c8_timed_8p_full_game_contract_v1 as contract
from . import c8_timed_8p_full_game_replay_v1 as replay
from . import c8_timed_session_runtime_v1 as runtime_v1
from . import c8_timeout_controller_integration_v1 as controller_v1
from . import c8_virtual_time_contract_v1 as clock_v1
from .actions import ActionType, LegalAction
from .mode_identity import FormalEightPlayerIdentitySession
from .model import EQUIPMENT_SLOTS


class C8G2RunnerError(ValueError):
    """Fail-closed G2 runner, artifact, or resume error."""


class C8G2NotReady(C8G2RunnerError):
    """A formal/candidate operation requires the future G3 verifier."""


class C8G2CommittedStepIncomplete(C8G2RunnerError):
    """A production step committed, but its post-step evidence could not close."""

    def __init__(self, failure_artifact: Mapping[str, object]) -> None:
        super().__init__("FAILED_INCOMPLETE_AFTER_COMMITTED_STEP")
        self.failure_artifact = dict(failure_artifact)


class RunnerModeV1(str, Enum):
    BOUNDED_SMOKE = "BOUNDED_SMOKE"
    CANDIDATE = "CANDIDATE"
    FORMAL = "FORMAL"


class RunnerArtifactScopeV1(str, Enum):
    BOUNDED_SMOKE = "BOUNDED_INTEGRATION_SMOKE"
    FORMAL_QUALITY_CANDIDATE = "FORMAL_QUALITY_CANDIDATE"
    PROMOTED_FORMAL = "PROMOTED_FORMAL"


class RunnerStatusV1(str, Enum):
    BOUNDED_STOP = "BOUNDED_STOP"
    NOT_READY = "NOT_READY"
    FAILED_INCOMPLETE = "FAILED_INCOMPLETE"
    FAILED_INCOMPLETE_AFTER_COMMITTED_STEP = (
        "FAILED_INCOMPLETE_AFTER_COMMITTED_STEP"
    )


C8_G2_RUNNER_ID: Final[str] = "c8-timed-8p-full-game-runner-v4"
C8_G2_RUNNER_SCHEMA: Final[str] = contract.C8_G1_RUNNER_SCHEMA
C8_G2_RUNNER_VERSION: Final[int] = 4
C8_G2_PROGRESS_SCHEMA: Final[str] = "sgs-c8-g2-full-game-progress-v4"
C8_G2_SMOKE_SCHEMA: Final[str] = "sgs-c8-g2-bounded-integration-smoke-v4"
C8_G2_WINDOW_SCHEMA: Final[str] = "sgs-c8-g2-public-window-record-v4"
C8_G2_OBSERVATION_SCHEMA: Final[str] = "sgs-c8-g2-required-event-observation-v3"
C8_G2_FAILURE_SCHEMA: Final[str] = (
    "sgs-c8-g2-committed-step-incomplete-v5"
)
C8_G2_FAILURE_VERSION: Final[int] = 5
C8_G2_DEVELOPMENT_SCHEMA: Final[str] = "sgs-c8-g2-development-identity-v4"
C8_G2_CURRENT_IMPLEMENTATION_SCHEMA: Final[str] = (
    "sgs-c8-g2-current-c8-implementation-identity-v4"
)
C8_G2_PRIOR_RUNNER_ID: Final[str] = "c8-timed-8p-full-game-runner-v1"
C8_G2_PRIOR_RUNNER_CONTRACT_IDENTITY: Final[str] = (
    "f4fc5ef43473c02555bed3f3dbdecb3e3e28f2293a482282c451e05c22896d7d"
)
C8_G2_PRIOR_DEVELOPMENT_IDENTITY: Final[str] = (
    "d1af752b8817cc7827fd0fed35f2a22ba0fdee860fac28228017ba32a83bfaf9"
)
C8_G2_PRIOR_CURRENT_IMPLEMENTATION_IDENTITY: Final[str] = (
    "4901387c5f0b77526ef61f73267be02f7aa4f107ec4b2d11afade3fab28fc6a3"
)
C8_G2_PRIOR_STATUS: Final[str] = "PARTIAL_DRAFT_NOT_DELIVERED"
C8_G2_PRIOR_BOUNDED_SMOKE_STATUS: Final[str] = (
    "FAILED_AT_WINDOW_4_NO_ARTIFACT"
)
C8_G2_CURRENT_STATUS: Final[str] = "IMPLEMENTED_PROVISIONAL"
C8_G2_SCOPE_MARKER: Final[str] = "BOUNDED_INTEGRATION_SMOKE"
C8_G2_REPLAY_STATUS: Final[str] = "TYPED_V4_FIXED_G3_COMPOSITION_IMPLEMENTED_PROVISIONAL"
C8_G2_G3_STATUS: Final[str] = "IMPLEMENTED_PROVISIONAL_NOT_EXECUTED_ON_FULL_GAME"
C8_G2_FULL_GAME_STATUS: Final[str] = "NOT_PROVEN"
C8_G2_MATRIX_STATUS: Final[str] = "NOT_STARTED"
C8_G2_DEFAULT_INFRASTRUCTURE_MAX_STEPS: Final[int] = (
    contract.C8_G1_MAX_PRODUCTION_STEPS_GUARD
)
C8_G2_DEFAULT_INFRASTRUCTURE_MAX_WINDOWS: Final[int] = (
    contract.C8_G1_MAX_TIMER_WINDOWS_GUARD
)
C8_G2_MAX_BOUNDED_SMOKE_STEPS: Final[int] = 12
C8_G2_MAX_BOUNDED_SMOKE_WINDOWS: Final[int] = 8
C8_G2_SMOKE_PLAN_CELL_ID: Final[str] = "C8G2-SMOKE-000"

_ZERO_SHA256: Final[str] = "0" * 64
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_TEXT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")
_RUN_LABEL_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,47}$")
_G2_PATHS: Final[Mapping[str, str]] = {
    "runner_source": "scripts/sgs_engine/c8_timed_8p_full_game_runner_v1.py",
    "runner_test": "tests/test_c8_timed_8p_full_game_runner_v1.py",
}
_FORBIDDEN_PUBLIC_KEYS: Final[frozenset[str]] = frozenset(
    {
        "payload",
        "private_payload",
        "card_instance_id",
        "card_identity",
        "hidden_choice",
        "hands",
        "draw_pile",
        "rng_state",
        "wall_clock",
    }
)


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _identity(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _file_sha256(path: Path) -> str:
    from . import c8_timed_replay_version_compatibility_v1 as compatibility
    producer_digest = compatibility.execution_source_digest_v1(path)
    if producer_digest is not None:
        return producer_digest
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _exact_dict(value: object, label: str) -> dict[str, Any]:
    if type(value) is not dict or any(type(key) is not str for key in value):
        raise C8G2RunnerError(f"{label}必须是精确JSON object")
    return value


def _exact_list(value: object, label: str) -> list[Any]:
    if type(value) is not list:
        raise C8G2RunnerError(f"{label}必须是精确JSON array")
    return value


def _exact_keys(value: object, fields: frozenset[str], label: str) -> dict[str, Any]:
    data = _exact_dict(value, label)
    actual = frozenset(data)
    if actual != fields:
        raise C8G2RunnerError(
            f"{label}字段不匹配 missing={sorted(fields - actual)} "
            f"extra={sorted(actual - fields)}"
        )
    return data


def _text(value: object, label: str, *, allow_empty: bool = False) -> str:
    if type(value) is not str or (not allow_empty and not value):
        raise C8G2RunnerError(f"{label}必须是精确字符串")
    return value


def _text_id(value: object, label: str) -> str:
    result = _text(value, label)
    if _TEXT_RE.fullmatch(result) is None:
        raise C8G2RunnerError(f"{label}不是canonical text id")
    return result


def _sha(value: object, label: str, *, allow_zero: bool = False) -> str:
    result = _text(value, label)
    if _SHA_RE.fullmatch(result) is None or (not allow_zero and result == _ZERO_SHA256):
        raise C8G2RunnerError(f"{label}必须是canonical SHA-256")
    return result


def _integer(value: object, label: str, *, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise C8G2RunnerError(f"{label}必须是精确int且 >= {minimum}")
    return value


def _boolean(value: object, label: str) -> bool:
    if type(value) is not bool:
        raise C8G2RunnerError(f"{label}必须是精确bool")
    return value


def _enum(enum_type: type[Enum], value: object, label: str) -> Any:
    raw = _text(value, label)
    try:
        return enum_type(raw)
    except ValueError as exc:
        raise C8G2RunnerError(f"{label}不是允许值：{raw}") from exc


def _public_key_audit(value: object, path: str = "artifact") -> None:
    if type(value) is dict:
        for key, item in value.items():
            if key in _FORBIDDEN_PUBLIC_KEYS:
                raise C8G2RunnerError(f"public artifact包含private key: {path}.{key}")
            _public_key_audit(item, f"{path}.{key}")
    elif type(value) is list:
        for index, item in enumerate(value):
            _public_key_audit(item, f"{path}[{index}]")


_RUNNER_DESCRIPTOR: Final[Mapping[str, object]] = {
    "schema": "sgs-c8-g2-runner-contract-v4",
    "contract_version": C8_G2_RUNNER_VERSION,
    "runner_id": C8_G2_RUNNER_ID,
    "runner_schema": C8_G2_RUNNER_SCHEMA,
    "executable_modes_in_g2": [RunnerModeV1.BOUNDED_SMOKE.value],
    "formal_modes_require_g3_verifier": True,
    "canonical_factory": "create_canonical_c6_no_skill_session_v1",
    "production_adapter": contract.C8_G1_E_ADAPTER_ID,
    "driver_policy_identity": contract.C8_G1_DRIVER_POLICY_IDENTITY,
    "baseline_seeds": list(contract.C8_G1_BASELINE_SEEDS),
    "default_max_steps": C8_G2_DEFAULT_INFRASTRUCTURE_MAX_STEPS,
    "default_max_windows": C8_G2_DEFAULT_INFRASTRUCTURE_MAX_WINDOWS,
    "bounded_smoke_max_steps": C8_G2_MAX_BOUNDED_SMOKE_STEPS,
    "bounded_smoke_max_windows": C8_G2_MAX_BOUNDED_SMOKE_WINDOWS,
    "atomic_write": "tmp-flush-fsync-close-replace",
    "resume": "READ_ONLY_EXISTING_COMPLETE_ARTIFACT_NO_LIVE_REHYDRATE",
    "natural_terminal_required_for_candidate": True,
    "strict_cold_reexecution_required_for_formal": True,
    "window_lifecycle": (
        "ONE_OPEN_FRESH_SIGNED_STEPS_CONTINUE_SAME_REF_DEADLINE_UNTIL_COMMIT_CLOSE"
    ),
    "post_commit_expected_active_parent_ref": None,
    "post_commit_parent_resume": "FORBIDDEN",
    "same_context_refresh_scope": "BEFORE_ACCEPTED_PRODUCTION_STEP_ONLY",
    "timeout_selection_authority": (
        "ACTUAL_C_RESOLVER_RESULT+B_RECEIPT+E_ISSUANCE"
    ),
    "committed_step_failure_status": (
        RunnerStatusV1.FAILED_INCOMPLETE_AFTER_COMMITTED_STEP.value
    ),
    "committed_step_failure_schema": C8_G2_FAILURE_SCHEMA,
    "next_window_failure_checkpoint": "PUBLIC_DIAGNOSTIC_NOT_LIVE_AUTHORITY",
    "diagnostic": "REPORT_ONLY_50_ACCEPTED_ATOMIC_SEGMENTS_ONE_SAME_BYTE_IO_RETRY_NO_RESUME",
    "execution_order_profile": "PRE_SESSION_HASH_SEED_0_INTERPRETER_BUILD_EXECUTABLE_PUBLIC_SLOT_ORDER",
    "supersedes_v3_current_identity": "e2a48170a9d613fe4262a57306693eff9b18a5faf7fc8128137bf532e0dd8ab9",
    "supersedes": {
        "runner_id": C8_G2_PRIOR_RUNNER_ID,
        "runner_contract_identity": C8_G2_PRIOR_RUNNER_CONTRACT_IDENTITY,
        "status": C8_G2_PRIOR_STATUS,
        "bounded_smoke": C8_G2_PRIOR_BOUNDED_SMOKE_STATUS,
    },
}
C8_G2_RUNNER_CONTRACT_IDENTITY: Final[str] = _identity(_RUNNER_DESCRIPTOR)


def runner_contract_descriptor_v1() -> dict[str, object]:
    return dict(_RUNNER_DESCRIPTOR)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def current_c8_g2_development_snapshot_v1(
    repo_root: Path | str | None = None,
) -> dict[str, object]:
    root = _repo_root() if repo_root is None else Path(repo_root).resolve()
    prior = replay.current_c8_g1_development_snapshot_v1(root)
    hashes = {
        label: _file_sha256(root / relative) for label, relative in _G2_PATHS.items()
    }
    material = {
        "schema": C8_G2_DEVELOPMENT_SCHEMA,
        "contract_version": C8_G2_RUNNER_VERSION,
        "runner_contract_identity": C8_G2_RUNNER_CONTRACT_IDENTITY,
    "source_test_sha256": hashes,
        "superseded_v2_identities": {
            "runner_contract": "699e0553bacd8be8b7a3dbdc8920e603f913da1038387388673503e73c5113a9",
            "development": "a4d5075f7d8cc20ff528e09c0628aaaf5fe6772db5fbe3fb78853b02bd2cf496",
            "current": "a8246d2aeddd842e2f619da1ff1ed2ca3bf4ec4ca2d80c52d9fb92d25937a6b0",
        },
        "prior_current_c8_implementation_identity": prior[
            "current_c8_implementation_identity"
        ],
    }
    development_identity = _identity(material)
    current_material = {
        "schema": C8_G2_CURRENT_IMPLEMENTATION_SCHEMA,
        "contract_version": C8_G2_RUNNER_VERSION,
        "prior_current_c8_implementation_identity": prior[
            "current_c8_implementation_identity"
        ],
        "c8_g1_contract_identity": contract.C8_G1_CONTRACT_IDENTITY,
        "c8_g1_replay_contract_identity": replay.C8_G1_REPLAY_CONTRACT_IDENTITY,
        "c8_g2_runner_contract_identity": C8_G2_RUNNER_CONTRACT_IDENTITY,
        "c8_g2_development_identity": development_identity,
    }
    return {
        **material,
        "development_identity": development_identity,
        "current_c8_implementation_identity": _identity(current_material),
        "prior": prior,
    }


def current_binding_snapshot_v1(
    registry: contract.FullGameRegistryV1,
    repo_root: Path | str | None = None,
) -> dict[str, object]:
    if not isinstance(registry, contract.FullGameRegistryV1):
        raise C8G2RunnerError("G2 binding必须使用G1 FullGameRegistryV1")
    root = _repo_root() if repo_root is None else Path(repo_root).resolve()
    development = current_c8_g2_development_snapshot_v1(root)
    g1 = replay.current_binding_snapshot_v1(registry, root)
    return {
        "schema": "sgs-c8-g2-current-binding-snapshot-v4",
        "contract_version": C8_G2_RUNNER_VERSION,
        "g1_binding_snapshot": g1,
        "g1_binding_snapshot_identity": _identity(g1),
        "g1_current_c8_implementation_identity": development["prior"][
            "current_c8_implementation_identity"
        ],
        "g2_runner_id": C8_G2_RUNNER_ID,
        "g2_runner_schema": C8_G2_RUNNER_SCHEMA,
        "g2_runner_contract_identity": C8_G2_RUNNER_CONTRACT_IDENTITY,
        "g2_development_identity": development["development_identity"],
        "current_c8_implementation_identity": development[
            "current_c8_implementation_identity"
        ],
        "registry_identity": registry.registry_identity,
        "selected_cell_ids": [item.cell_id for item in registry.selected_cells],
        "selected_sentinel_seeds": [item.seed for item in registry.sentinel_cells],
        "full_game_replay_execution": contract.C8_G1_FULL_GAME_REPLAY_EXECUTION,
        "g3_status": C8_G2_G3_STATUS,
    }


def _relation_window_kind_from_raw_v2(
    raw: str, applicability: str
) -> contract.PublicWindowKindV1:
    mapping = {
        "PLAY": contract.PublicWindowKindV1.PLAY,
        "OPTIONAL_RESPONSE": contract.PublicWindowKindV1.OPTIONAL_RESPONSE,
        "RESCUE_RESPONSE": contract.PublicWindowKindV1.RESCUE_RESPONSE,
        "OPTIONAL_SKILL_DECISION": contract.PublicWindowKindV1.OPTIONAL_SKILL_DECISION,
        "MULTI_STEP_OBLIGATION": contract.PublicWindowKindV1.MULTI_STEP_OBLIGATION,
    }
    if raw in mapping:
        return mapping[raw]
    if applicability == "PRIVATE_ORDINAL_TIMEOUT_UNRESOLVED":
        return contract.PublicWindowKindV1.PRIVATE_ORDINAL_TIMEOUT_UNRESOLVED
    return contract.PublicWindowKindV1.OTHER_PUBLIC


def _driver_window_kind_from_raw_v2(
    raw: str, applicability: str
) -> contract.PublicWindowKindV1:
    if applicability == "PRIVATE_ORDINAL_TIMEOUT_UNRESOLVED":
        return contract.PublicWindowKindV1.PRIVATE_ORDINAL_TIMEOUT_UNRESOLVED
    return _relation_window_kind_from_raw_v2(raw, applicability)


def _window_kind(context_value: prod.ProductionDecisionContextV1) -> contract.PublicWindowKindV1:
    return _driver_window_kind_from_raw_v2(
        context_value.window_kind.value, context_value.applicability.value
    )


def _timeout_applicability(
    context_value: prod.ProductionDecisionContextV1,
) -> contract.TimeoutApplicabilityV1:
    raw = context_value.applicability.value
    if raw == "PRIVATE_ORDINAL_TIMEOUT_UNRESOLVED":
        return contract.TimeoutApplicabilityV1.PRIVATE_ORDINAL_TIMEOUT_UNRESOLVED
    if raw == "NOT_APPLICABLE_IN_C6_NO_SKILL_8P":
        return contract.TimeoutApplicabilityV1.NOT_APPLICABLE_IN_C6_NO_SKILL_8P
    return contract.TimeoutApplicabilityV1.APPLICABLE


def _family_for_public_action(
    action: LegalAction,
    context_value: prod.ProductionDecisionContextV1,
) -> str:
    kind = _window_kind(context_value)
    if kind is contract.PublicWindowKindV1.PLAY:
        return "END_PLAY_PHASE" if action.action_type is ActionType.PASS else "PROGRESS_ACTION"
    if kind is contract.PublicWindowKindV1.OPTIONAL_RESPONSE:
        family = prod._family_for_action(action, context_value)
        prod.verify_response_public_action_family_v1(action, context_value, family)
        return {
            prod.c8.PublicActionFamilyV1.MANDATORY_ACTION: "RESPOND",
            prod.c8.PublicActionFamilyV1.PUBLIC_CHOICE: "ACTIVATE",
            prod.c8.PublicActionFamilyV1.PASS_RESPONSE: "PASS",
        }[family]
    if kind is contract.PublicWindowKindV1.RESCUE_RESPONSE:
        family = prod._family_for_action(action, context_value)
        prod.verify_response_public_action_family_v1(action, context_value, family)
        return {prod.c8.PublicActionFamilyV1.PASS_RESCUE: "PASS",
                prod.c8.PublicActionFamilyV1.MANDATORY_ACTION: "RESCUE"}[family]
    if kind is contract.PublicWindowKindV1.OPTIONAL_SKILL_DECISION:
        family = prod._family_for_action(action, context_value)
        prod.verify_optional_public_action_family_v1(action, context_value, family)
        return "DECLINE" if family is prod.c8.PublicActionFamilyV1.DECLINE_OPTIONAL else "ACTIVATE"
    if kind is contract.PublicWindowKindV1.PRIVATE_ORDINAL_TIMEOUT_UNRESOLVED:
        return "PRIVATE_ORDINAL"
    if kind is contract.PublicWindowKindV1.MULTI_STEP_OBLIGATION:
        return "MULTI_STEP_PROGRESS"
    return "MANDATORY_ACTION" if context_value.proposal_count == 1 else "PUBLIC_CHOICE"


def _public_actions_raw(
    context_value: prod.ProductionDecisionContextV1,
    session: FormalEightPlayerIdentitySession,
) -> tuple[LegalAction, ...]:
    actions = session.legal_actions()
    if type(actions) is not tuple or any(type(item) is not LegalAction for item in actions):
        raise C8G2RunnerError("canonical session legal_actions类型漂移")
    if not actions or len(actions) != context_value.proposal_count:
        raise C8G2RunnerError("public proposal count与C8-E context不匹配")
    if len({item.action_id for item in actions}) != len(actions):
        raise C8G2RunnerError("production signed action_id重复")
    return actions


def public_driver_input_v1(
    *,
    session: FormalEightPlayerIdentitySession,
    context_value: prod.ProductionDecisionContextV1,
    formal_seed: int,
    global_window_index: int,
    deadline_at: int,
    public_ordinal_progress: contract.PublicOrdinalProgressV1 | None = None,
) -> tuple[contract.FormalDriverInputV1, tuple[str, ...]]:
    """Build the frozen G1 driver input using public IDs/families/order only."""

    actions = _public_actions_raw(context_value, session)
    action_ids = tuple(_text(item.action_id, "production signed action_id") for item in actions)
    options = tuple(
        contract.PublicActionOptionV1(index, _family_for_public_action(item, context_value))
        for index, item in enumerate(actions)
    )
    value = contract.FormalDriverInputV1(
        formal_seed=formal_seed,
        global_window_index=global_window_index,
        turn_number=context_value.turn_number,
        turn_player_id=context_value.current_player_id,
        actor_id=context_value.current_actor_id,
        phase=context_value.phase.value,
        window_kind=_window_kind(context_value),
        deadline_at=deadline_at,
        timeout_applicability=_timeout_applicability(context_value),
        proposal_order_identity=contract.identity_v1([item.to_dict() for item in options]),
        public_actions=options,
        public_ordinal_progress=public_ordinal_progress,
    )
    return value, action_ids


def driver_decision_dict_v1(
    input_value: contract.FormalDriverInputV1,
) -> dict[str, object]:
    decision = contract.choose_formal_driver_action_v1(input_value)
    return {
        "policy_id": decision.policy_id,
        "policy_identity": decision.policy_identity,
        "driver_input_identity": decision.driver_input_identity,
        "timeout_intent": decision.timeout_intent,
        "actual_timeout": decision.actual_timeout,
        "marker": decision.marker.value,
        "decision_tick": decision.decision_tick,
        "chosen_public_ordinal": decision.chosen_public_ordinal,
        "chosen_public_action_family": decision.chosen_public_action_family,
        "choice_digest": decision.choice_digest,
        "skip_reason": decision.skip_reason,
    }


def _driver_input_dict(value: contract.FormalDriverInputV1) -> dict[str, object]:
    return value.identity_material()


def _driver_input_from_dict(value: object) -> contract.FormalDriverInputV1:
    return replay.driver_input_from_dict_v3(value)




@dataclass(frozen=True, slots=True)
class CanonicalSessionBundleV1:
    session: FormalEightPlayerIdentitySession
    adapter: prod.C8C6ProductionAdapterV1
    runtime: runtime_v1.C8TimedSessionRuntimeV1
    orchestrator: prod.C8C6ProductionWindowOrchestratorV1
    controller: controller_v1.TimeoutResolverControllerIntegrationV1
    session_binding_identity: str
    runtime_instance_identity: str
    controller_instance_identity: str


def create_canonical_session_bundle_v1(
    *, seed: int, run_label: str = "bounded-smoke", baseline_cell_id: str | None = None
) -> CanonicalSessionBundleV1:
    """Wire one exact audited production stack; never construct alternate gameplay."""

    seed = _integer(seed, "seed")
    if seed > contract.C8_G1_SENTINEL_SEED_MAX:
        raise C8G2RunnerError("seed超出冻结0..99范围")
    if type(run_label) is not str or _RUN_LABEL_RE.fullmatch(run_label) is None:
        raise C8G2RunnerError("run_label必须是deterministic lowercase id")
    validate_execution_order_profile_v1()
    session_id = None
    if baseline_cell_id is not None:
        cell = contract.FullGameCellRefV1(baseline_cell_id, contract.C8_G1_BASE_MODE_ID, seed)
        if cell not in contract.CANONICAL_BASELINE_CELLS_V1:
            raise C8G2RunnerError("baseline session只接受正式baseline registry")
        session_id = baseline_public_session_id_v1(cell_id=baseline_cell_id, seed=seed, run_label=run_label)
    if session_id is None:
        session = prod.create_canonical_c6_no_skill_session_v1(seed)
    else:
        session = prod.canonical_no_skill_mode_v1(contract.C8_G1_BASE_MODE_ID).create_session(
            seed, session_id=session_id)
    return _assemble_bundle_v3(session, seed=seed, run_label=run_label)


def baseline_public_session_id_v1(*, cell_id: str, seed: int, run_label: str) -> str:
    cell = contract.FullGameCellRefV1(cell_id, contract.C8_G1_BASE_MODE_ID, seed)
    if cell not in contract.CANONICAL_BASELINE_CELLS_V1:
        raise C8G2RunnerError("baseline session只接受正式baseline registry")
    if type(run_label) is not str or _RUN_LABEL_RE.fullmatch(run_label) is None:
        raise C8G2RunnerError("run_label必须是deterministic lowercase id")
    return _identity({"schema": "sgs-c8-baseline-public-session-id-v1",
        "cell": cell.to_dict(), "run_label": run_label})


def construct_baseline_session_identity_v1(*, cell_id: str, seed: int, run_label: str) -> dict[str, str]:
    """只构造step-0绑定；不签发C owner，也不消费process-local tombstone。"""
    session_id = baseline_public_session_id_v1(cell_id=cell_id, seed=seed, run_label=run_label)
    validate_execution_order_profile_v1()
    session = prod.canonical_no_skill_mode_v1(contract.C8_G1_BASE_MODE_ID).create_session(seed, session_id=session_id)
    adapter, runtime, controller_identity = _assemble_runtime_v3(session, seed=seed, run_label=run_label)
    return {"session_binding_identity": adapter.session_binding_identity_v1(),
            "runtime_instance_identity": runtime.state.runtime_instance_identity,
            "controller_instance_identity": controller_identity}


def validate_execution_order_profile_v1(expected: object = None, *, repo_root: Path | str | None = None) -> dict[str, object]:
    """Mandatory pre-session check; changing os.environ after startup is insufficient."""
    if sys.flags.hash_randomization != 0 or os.environ.get("PYTHONHASHSEED") != "0":
        raise C8G2RunnerError("EXECUTION_ORDER_PROFILE_MISMATCH: 必须在解释器启动前固定PYTHONHASHSEED=0")
    slots = tuple(EQUIPMENT_SLOTS)
    if slots != contract.PUBLIC_EQUIPMENT_SLOT_ORDER_V1:
        raise C8G2RunnerError("EXECUTION_ORDER_PROFILE_MISMATCH: 公开装备槽实际顺序漂移")
    root = _repo_root() if repo_root is None else Path(repo_root).resolve()
    for relative, digest in contract.PRIVATE_ORDINAL_SOURCE_HASHES_V1.items():
        if _file_sha256(root / relative) != digest:
            raise C8G2RunnerError("DRIVER_LIVENESS_UNRESOLVED: source/order certificate漂移: " + relative)
    profile = {"schema": "sgs-c8-g-execution-order-profile-v1", "version": 1,
        "python_version": sys.version, "python_build": list(platform.python_build()),
        "architecture_bits": struct.calcsize("P") * 8, "machine": platform.machine(),
        "executable_sha256": _file_sha256(Path(sys.executable)), "hash_randomization": 0,
        "python_hash_seed": "0", "public_equipment_slot_order": list(slots),
        "source_certificate_identity": contract.PRIVATE_ORDINAL_CERTIFICATE_IDENTITY_V1}
    profile["profile_identity"] = _identity(profile)
    if expected is not None:
        replay.exact_equal_v3(expected, profile, "execution-order exact interpreter/profile")
    return profile


def _assemble_runtime_v3(session: FormalEightPlayerIdentitySession, *, seed: int, run_label: str):
    adapter = prod.C8C6ProductionAdapterV1(session)
    runtime_nonce = _identity(
        {"scope": C8_G2_SCOPE_MARKER, "seed": seed, "run_label": run_label, "kind": "runtime"}
    )
    driver_authority = _identity(
        {"scope": C8_G2_SCOPE_MARKER, "seed": seed, "run_label": run_label, "kind": "driver"}
    )
    controller_identity = _identity(
        {"scope": C8_G2_SCOPE_MARKER, "seed": seed, "run_label": run_label, "kind": "controller"}
    )
    runtime = runtime_v1.C8TimedSessionRuntimeV1(
        inner_adapter=adapter,
        input_authenticator=adapter,
        instance_nonce_identity=runtime_nonce,
        input_source_id=f"c8-g2-{run_label}",
        driver_authority_identity=driver_authority,
    )
    return adapter, runtime, controller_identity


def _assemble_bundle_v3(session: FormalEightPlayerIdentitySession, *, seed: int, run_label: str) -> CanonicalSessionBundleV1:
    adapter, runtime, controller_identity = _assemble_runtime_v3(session, seed=seed, run_label=run_label)
    adapter.bind_runtime_v1(runtime, controller_identity=controller_identity)
    orchestrator = prod.C8C6ProductionWindowOrchestratorV1(adapter, runtime)
    controller = controller_v1.TimeoutResolverControllerIntegrationV1(
        runtime,
        adapter,
        controller_instance_identity=controller_identity,
    )
    return CanonicalSessionBundleV1(
        session,
        adapter,
        runtime,
        orchestrator,
        controller,
        adapter.session_binding_identity_v1(),
        runtime.state.runtime_instance_identity,
        controller_identity,
    )


def _controller_tip(controller: controller_v1.TimeoutResolverControllerIntegrationV1) -> str:
    events = controller.public_event_trace_v1()
    return events[-1].event_identity if events else _ZERO_SHA256


def _capture_public_state(bundle: CanonicalSessionBundleV1) -> dict[str, object]:
    session = bundle.session
    active = bundle.runtime.state.virtual_time_state.window_stack.active_window
    if session.is_finished:
        phase = session.phase.value
        actor = None
        player = None
        turn = session.phase_history[-1].turn_number
    else:
        phase = session.phase.value
        actor = session.current_actor_id
        player = session.current_player_id
        turn = session.phase_history[-1].turn_number
    material: dict[str, object] = {
        "schema": "sgs-c8-g2-public-runtime-state-v4",
        "contract_version": C8_G2_RUNNER_VERSION,
        "phase": phase,
        "turn_number": turn,
        "current_actor_id": actor,
        "current_player_id": player,
        "state_revision": session.state.revision,
        "production_step_count": session.step_count,
        "production_finished": session.is_finished,
        "adapter_public_state_identity": bundle.adapter.public_state_identity_v1(),
        "adapter_authoritative_state_commitment": bundle.adapter.authoritative_state_identity_v1(),
        "production_execution_commitment": session.execution_hash,
        "runtime_state_identity": bundle.runtime.state.state_identity,
        "runtime_event_chain_tip": bundle.runtime.state.event_chain_tip,
        "controller_event_chain_tip": _controller_tip(bundle.controller),
        "virtual_tick": bundle.runtime.state.virtual_time_state.now_tick,
        "window_depth": len(bundle.runtime.state.virtual_time_state.window_stack.windows),
        "active_window_id": None if active is None else active.window_id,
    }
    return {**material, "state_identity": _identity(material)}


def _advance_virtual_time(
    bundle: CanonicalSessionBundleV1, requested_tick: int
) -> runtime_v1.TimedRuntimeAdvanceResultV1:
    advance = bundle.adapter.issue_virtual_time_advance_v1(requested_tick=requested_tick)
    return bundle.runtime.ingest_virtual_time_input(
        advance,
        expected_previous_input_chain_tip=bundle.runtime.state.input_chain_tip,
        duration_profile_identity=clock_v1.ENGINEERING_TEST_PROFILE_V1.profile_identity,
    )


def _action_commitment(action_id: str) -> str:
    return _identity({"production_signed_action_id": action_id})


def _window_record_identity(record: Mapping[str, object]) -> str:
    return _identity({key: value for key, value in record.items() if key != "record_identity"})


def _public_cursor(bundle: CanonicalSessionBundleV1) -> dict[str, object]:
    s = bundle.session
    active = bundle.runtime.state.virtual_time_state.window_stack.active_window
    return {"production_step_count": s.step_count, "state_revision": s.state.revision,
            "phase": s.phase.value, "window_depth": len(bundle.runtime.state.virtual_time_state.window_stack.windows),
            "active_window_id": None if active is None else active.window_id,
            "runtime_state_identity": bundle.runtime.state.state_identity}


def committed_step_failure_from_dict_v2(value: object) -> dict[str, object]:
    d = replay._object(value, "schema contract_version run_status reason sequence committed_step_count last_accepted_step last_fully_evidenced_step last_durable_diagnostic_step last_authoritative_replay_step resume_capability error_class current_public_cursor last_completed_window typed_decision completion authority production_step_rollback_claimed closed_parent_reopened promotion full_game failure_identity", "committed-step incomplete")
    if d["schema"] != C8_G2_FAILURE_SCHEMA or _integer(d["contract_version"], "failure version") != C8_G2_FAILURE_VERSION:
        raise C8G2RunnerError("旧failure schema禁止恢复current typed lineage")
    for key, expected in (("run_status", "FAILED_INCOMPLETE_AFTER_COMMITTED_STEP"),
                          ("authority", "DIAGNOSTIC_ONLY_NO_RESUME_CAPABILITY"),
                          ("production_step_rollback_claimed", False), ("closed_parent_reopened", False),
                          ("promotion", False), ("full_game", False)):
        replay.exact_equal_v3(d[key], expected, "failure "+key)
    _integer(d["sequence"], "sequence", minimum=1)
    _integer(d["committed_step_count"], "committed steps", minimum=1)
    replay.exact_equal_v3(d["last_accepted_step"], d["committed_step_count"], "failure accepted cursor")
    replay.exact_equal_v3(d["last_authoritative_replay_step"], None, "failure has no rehydrate proof")
    replay.exact_equal_v3(d["resume_capability"], "NONE", "failure no resume")
    _text_id(d["reason"], "controlled stop reason")
    _text_id(d["error_class"], "controlled error class")
    for key in ("last_fully_evidenced_step", "last_durable_diagnostic_step"):
        if d[key] is not None and _integer(d[key], key) > d["committed_step_count"]:
            raise C8G2RunnerError("failure evidence cursor超过实际accepted边界")
    cursor = replay._object(d["current_public_cursor"], "production_step_count state_revision phase window_depth active_window_id runtime_state_identity", "failure cursor")
    replay.exact_equal_v3(cursor["production_step_count"], d["committed_step_count"], "failure actual cursor")
    if d["typed_decision"] is not None:
        decision = replay.production_decision_from_dict_v1(d["typed_decision"]).to_dict()
        replay.exact_equal_v3(replay.completion_from_decision_v1(decision).to_dict(), d["completion"], "failure completion")
        replay.exact_equal_v3(decision["binding"]["post_step_count"], d["committed_step_count"], "failure committed step")
    elif d["completion"] is not None:
        raise C8G2RunnerError("不完整typed evidence不得凭空补completion")
    if d["last_completed_window"] is not None:
        w = _window_record_from_dict(d["last_completed_window"], expected_sequence=d["last_completed_window"]["sequence"])
        if w["steps"][-1]["decision"]["binding"]["post_step_count"] > d["committed_step_count"]:
            raise C8G2RunnerError("failure cursor落后于已提交步")
    replay.exact_equal_v3(d["failure_identity"], _identity({k:v for k,v in d.items() if k != "failure_identity"}), "failure hash")
    return d


def _committed_failure(bundle: CanonicalSessionBundleV1, records: list[dict[str, object]],
                       sequence: int, decision: dict[str, object] | None, *, reason: str = "POST_COMMIT_EVIDENCE_INCOMPLETE",
                       error_class: str = "C8G2RunnerError", last_evidenced: int = 0,
                       last_durable: int | None = None) -> C8G2CommittedStepIncomplete:
    material = {"schema": C8_G2_FAILURE_SCHEMA, "contract_version": C8_G2_FAILURE_VERSION,
                "run_status": "FAILED_INCOMPLETE_AFTER_COMMITTED_STEP", "reason": reason, "error_class": error_class,
                "sequence": sequence, "committed_step_count": bundle.session.step_count,
                "last_accepted_step": bundle.session.step_count, "last_fully_evidenced_step": last_evidenced,
                "last_durable_diagnostic_step": last_durable, "last_authoritative_replay_step": None,
                "resume_capability": "NONE",
                "current_public_cursor": _public_cursor(bundle), "last_completed_window": records[-1] if records else None,
                "typed_decision": decision,
                "completion": None if decision is None else replay.completion_from_decision_v1(decision).to_dict(),
                "authority": "DIAGNOSTIC_ONLY_NO_RESUME_CAPABILITY", "production_step_rollback_claimed": False,
                "closed_parent_reopened": False, "promotion": False, "full_game": False}
    return C8G2CommittedStepIncomplete({**material, "failure_identity": _identity(material)})


def _stale_context_rejected_v1(bundle: CanonicalSessionBundleV1, ref: runtime_v1.WindowAuthorityRefV1,
                              old_context: prod.ProductionDecisionContextV1) -> bool:
    before = _public_cursor(bundle)
    production_before = (bundle.session.execution_hash, len(bundle.session.events), len(bundle.session.rng_calls))
    try:
        bundle.adapter.bind_window_authority_v1(ref, old_context)
    except prod.C8C6ProductionAdapterError:
        replay.exact_equal_v3(before, _public_cursor(bundle), "stale rejection production unchanged")
        replay.exact_equal_v3(production_before, (bundle.session.execution_hash, len(bundle.session.events), len(bundle.session.rng_calls)), "stale rejection execution/event/RNG unchanged")
        return True
    raise C8G2RunnerError("production transition后stale context/ref被接受")


def _post_public_boundary_v1(context: prod.ProductionDecisionContextV1 | None) -> dict[str, object]:
    return {"next_phase": None if context is None else context.phase.value,
            "next_actor_id": None if context is None else context.current_actor_id,
            "next_turn_number": None if context is None else context.turn_number,
            "next_turn_player_id": None if context is None else context.current_player_id,
            "next_proposal_count": 0 if context is None else context.proposal_count}


class DiagnosticIOFailureV1(C8G2RunnerError):
    """Pure IO failed after at most one retry of identical immutable bytes."""


def diagnostic_step_projection_v1(step: Mapping[str, object], *, relation_kind: str = "NOT_PROVIDED") -> bytes:
    decision = step["decision"]
    b = decision["binding"]
    driver = decision["driver_decision"] if decision["kind"] == replay.ON_TIME_KIND else decision["timeout_schedule_decision"]["driver_decision"]
    live = decision.get("liveness")
    progress = None if live is None else live["after"]
    action_class = "ORDINARY" if live is None else contract.certified_ordinal_choice_v1(
        contract.PublicOrdinalProgressV1.from_dict(live["before"]), live["before"]["shape_count"])[1]
    row = {"step_index": b["post_step_count"], "turn_number": b["turn_number"], "turn_player_id": b["turn_player_id"],
        "actor_id": b["actor_id"], "phase": b["phase"], "window_index": b["global_window_index"],
        "window_step_index": b["window_step_index"], "marker": driver["marker"],
        "family": b["production_action_ref"]["executed_public_action_family"], "progress_class": action_class,
        "timeout_intent": driver["timeout_intent"], "actual_timeout": driver["actual_timeout"],
        "continued": decision["completion"]["kind"] == "ON_TIME_OBLIGATION_CONTINUED",
        "logical_obligation_identity": None if progress is None else progress["logical_obligation_identity"],
        "certified_selected_progress_count": None if progress is None else progress["certified_selected_progress_count"],
        "candidate_count": None if progress is None else progress["candidate_count"],
        "certified_required_count": None if progress is None else progress["certified_required_count"],
        "stage": None if progress is None else progress["stage"], "q_authority": "G_CERTIFIED_PUBLIC_HISTORY",
        "e_observed_selected_count": None, "e_observed_required_count": None, "e_count_availability": "NOT_EXPOSED",
        "opening_ref_commitment": b["window_authority_ref_identity"],
        "fresh_context_commitment": b["production_context_identity"], "deadline_at": b["deadline_at"],
        "virtual_tick": b["decision_tick"], "active_depth": step["post_state"]["window_depth"],
        "relation_kind": relation_kind, "current_position": diagnostic_public_position_v1(step["post_state"])}
    return _canonical_bytes(row)


def diagnostic_public_position_v1(state: Mapping[str, object]) -> dict[str, object]:
    return {"turn_number": state["turn_number"], "turn_player_id": state["current_player_id"],
        "actor_id": state["current_actor_id"], "phase": state["phase"], "availability": "PUBLIC_BOUNDARY",
        "reason": "NATURAL_TERMINAL" if state["production_finished"] else None}


DIAGNOSTIC_EFFECT_FIELDS_V1 = frozenset("damage_events damage_amount dying_events death_events hp_recover_events hp_recover_amount successful_rescues".split())
DIAGNOSTIC_BOUNDARY_FIELDS_V1 = frozenset("accepted_step_count state_revision event_count rng_count alive_count alive_hp_sum alive_hp_min alive_hp_max dying_count effects_delta".split())


def _diagnostic_boundary_from_bytes_v1(raw: bytes) -> dict[str, object]:
    if type(raw) is not bytes:
        raise C8G2RunnerError("diagnostic sink只接收immutable bytes")
    d = replay._object(replay._strict_json(raw), "public private", "diagnostic detached boundary")
    public = replay._exact_keys(d["public"], DIAGNOSTIC_BOUNDARY_FIELDS_V1, "diagnostic public boundary")
    for key in DIAGNOSTIC_BOUNDARY_FIELDS_V1 - {"effects_delta", "alive_hp_min", "alive_hp_max", "alive_hp_sum"}:
        _integer(public[key], key)
    for key in ("alive_hp_min", "alive_hp_max", "alive_hp_sum"):
        if public[key] is not None and type(public[key]) is not int:
            raise C8G2RunnerError("diagnostic HP必须是exact int/null")
    effects = replay._exact_keys(public["effects_delta"], DIAGNOSTIC_EFFECT_FIELDS_V1, "diagnostic effects")
    for key in effects:
        _integer(effects[key], key)
    replay._exact_dict(d["private"], "private-only diagnostics")
    return d


def diagnostic_snapshot_from_dict_v1(value: object) -> dict[str, object]:
    """Strict reporting data parser; no live, replay, or promotion capability."""
    d = replay._object(value, "schema version scope resume_capable gameplay_authority promotion_authority resume_capability generation previous_snapshot_ref status metadata last_accepted_step last_fully_evidenced_step last_durable_diagnostic_step last_authoritative_replay_step completed_window_count metrics_observed_at_step boundary current_position metrics_availability sanitized_public_progress_digest position_and_obligation effects schedule histograms delta_step_rows rolling_indicators ops io checksum", "diagnostic snapshot")
    for key, expected in (("schema", "sgs-c8-g-natural-diagnostic-snapshot-v1"), ("version", 1),
            ("scope", "REPORT_ONLY"), ("resume_capable", False), ("gameplay_authority", False),
            ("promotion_authority", False), ("resume_capability", "NONE"), ("last_authoritative_replay_step", None)):
        replay.exact_equal_v3(d[key], expected, "diagnostic "+key)
    for key in ("generation", "last_accepted_step", "last_fully_evidenced_step", "completed_window_count", "metrics_observed_at_step"):
        _integer(d[key], key)
    if d["last_durable_diagnostic_step"] is not None:
        _integer(d["last_durable_diagnostic_step"], "last durable")
    if d["last_fully_evidenced_step"] > d["last_accepted_step"] or d["metrics_observed_at_step"] > d["last_accepted_step"]:
        raise C8G2RunnerError("diagnostic cursor不能超过actual accepted")
    _diagnostic_boundary_from_bytes_v1(_canonical_bytes({"public": d["boundary"], "private": {}}))
    metadata = replay._object(d["metadata"], "cell_execution_identity attempt_ref g1_identity g2_identity g3_identity source_identity driver_identity execution_order_profile", "diagnostic metadata")
    for key in metadata.keys()-{"attempt_ref", "execution_order_profile"}:
        _sha(metadata[key], key)
    _text_id(metadata["attempt_ref"], "attempt ref")
    replay._object(d["current_position"], "turn_number turn_player_id actor_id phase availability reason", "diagnostic public position")
    schedule = replay._object(d["schedule"], "opened_windows timeout_intent_count actual_timeout_window_count on_time_window_count skipped_unresolved_intent_count accepted_on_time_steps accepted_timeout_steps continuation_steps", "diagnostic schedule")
    for key, count in schedule.items():
        _integer(count, key)
    for key, count in replay._exact_keys(d["effects"], DIAGNOSTIC_EFFECT_FIELDS_V1, "diagnostic effects").items():
        _integer(count, key)
    rows = replay._exact_list(d["delta_step_rows"], "diagnostic segment")
    if len(rows) > 50:
        raise C8G2RunnerError("diagnostic分段最多50行")
    for row in rows:
        replay._object(row, "step_index turn_number turn_player_id actor_id phase window_index window_step_index marker family progress_class timeout_intent actual_timeout continued logical_obligation_identity certified_selected_progress_count candidate_count certified_required_count stage q_authority e_observed_selected_count e_observed_required_count e_count_availability opening_ref_commitment fresh_context_commitment deadline_at virtual_tick active_depth relation_kind current_position aggregate effects_delta wall_elapsed_seconds", "diagnostic row")
        _integer(row["step_index"], "diagnostic row step")
    if rows and rows[-1]["step_index"] > d["last_accepted_step"]:
        raise C8G2RunnerError("diagnostic row超过accepted")
    replay.exact_equal_v3(d["checksum"], _identity({k:v for k,v in d.items() if k != "checksum"}), "diagnostic checksum not proof")
    return d


class ReportOnlyDiagnosticSinkV1:
    """An output sink with detached data only; no session, driver, recorder or resume methods."""

    def __init__(self, output_dir: Path | str) -> None:
        self.root = Path(output_dir).resolve()
        if self.root == _repo_root() or _repo_root() in self.root.parents:
            raise C8G2RunnerError("diagnostic输出必须在repo外")
        if (self.root/"latest.json").exists():
            raise C8G2RunnerError("diagnostic禁止resume或覆盖已有attempt")
        self.generation = 0
        self.previous = None
        self.last_durable = None
        self.rows = []
        self.boundary = None
        self.metadata = None
        self.last_step = None
        self.effects = {k: 0 for k in DIAGNOSTIC_EFFECT_FIELDS_V1}
        self.histograms = {k: {} for k in ("phase", "family", "progress_class")}
        self.schedule = {k: 0 for k in ("opened_windows", "timeout_intent_count", "actual_timeout_window_count",
            "on_time_window_count", "skipped_unresolved_intent_count", "accepted_on_time_steps", "accepted_timeout_steps", "continuation_steps")}
        self.started = time.monotonic()
        self.last_damage_turn = None
        self.last_death_turn = None
        self.steps_in_turn = 0
        self.io_failed = False
        self.last_write_at = None
        self.last_progress_at = None
        self.last_progress_step = None
        self.last_quotient = None
        self.repeated_quotient = 0
        self.initial_position = None

    def _write_bytes(self, path: Path, raw: bytes, *, immutable: bool) -> None:
        # No retry ever calls gameplay, a driver, an observer, or re-encodes a snapshot.
        for attempt in range(2):
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                if immutable and path.exists():
                    if path.read_bytes() != raw:
                        raise DiagnosticIOFailureV1("DIAGNOSTIC_IMMUTABLE_GENERATION_CONFLICT")
                    return
                temporary = path.with_suffix(path.suffix+".tmp")
                with temporary.open("wb") as handle:
                    handle.write(raw)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, path)
                if path.read_bytes() != raw:
                    raise OSError("diagnostic readback mismatch")
                return
            except OSError as exc:
                if attempt:
                    self.io_failed = True
                    raise DiagnosticIOFailureV1("IO_FAILURE: 同一不可变字节纯IO重试一次后仍失败") from exc

    def start(self, boundary: bytes, *, construction: Mapping[str, object], cell_execution_identity: str,
              binding: Mapping[str, object], position_bytes: bytes) -> None:
        from .c8_timed_8p_full_game_production_replay_v1 import current_c8_g3_development_snapshot_v1
        self.boundary = _diagnostic_boundary_from_bytes_v1(boundary)
        if self.boundary["public"]["accepted_step_count"] != 0 or self.metadata is not None:
            raise C8G2RunnerError("diagnostic必须从step0且仅start一次")
        g3 = current_c8_g3_development_snapshot_v1()
        self.initial_position = replay._object(replay._strict_json(position_bytes),
            "turn_number turn_player_id actor_id phase availability reason", "public initial position")
        self.metadata = {"cell_execution_identity": _sha(cell_execution_identity, "cell identity"),
            "attempt_ref": construction["run_label"],
            "g1_identity": binding["g1_current_c8_implementation_identity"],
            "g2_identity": binding["current_c8_implementation_identity"],
            "g3_identity": g3["current_c8_implementation_identity"], "source_identity": g3["global_source_identity"],
            "driver_identity": contract.C8_G1_DRIVER_POLICY_IDENTITY,
            "execution_order_profile": json.loads(_canonical_bytes(construction["execution_order_profile"]))}
        self._publish("STARTED", 0, 0, 0)

    def note_open(self, raw: bytes) -> None:
        d = replay._object(replay._strict_json(raw), "window_index timeout_intent actual_timeout skipped_unresolved", "opened schedule")
        if _integer(d["window_index"], "window index") != self.schedule["opened_windows"]+1:
            raise C8G2RunnerError("diagnostic OPEN序号不连续")
        for key in ("timeout_intent", "actual_timeout", "skipped_unresolved"):
            _boolean(d[key], key)
        self.schedule["opened_windows"] += 1
        self.schedule["timeout_intent_count"] += d["timeout_intent"]
        # Intent belongs to OPEN. Actual window/step counters wait for a committed step.
        self.schedule["skipped_unresolved_intent_count"] += d["skipped_unresolved"]

    def accept(self, boundary: bytes, *, step_bytes: bytes, completed_window_count: int) -> None:
        data = _diagnostic_boundary_from_bytes_v1(boundary)
        row = replay._strict_json(step_bytes)
        # The sender uses the fixed allowlist projection, never a raw typed step.
        fields = "step_index turn_number turn_player_id actor_id phase window_index window_step_index marker family progress_class timeout_intent actual_timeout continued logical_obligation_identity certified_selected_progress_count candidate_count certified_required_count stage q_authority e_observed_selected_count e_observed_required_count e_count_availability opening_ref_commitment fresh_context_commitment deadline_at virtual_tick active_depth relation_kind current_position"
        replay._object(row, fields, "allowlisted diagnostic row")
        accepted = data["public"]["accepted_step_count"]
        if accepted != self.boundary["public"]["accepted_step_count"]+1 or row["step_index"] != accepted:
            raise C8G2RunnerError("diagnostic accepted边界必须精确+1")
        for key in ("actual_timeout", "timeout_intent", "continued"):
            _boolean(row[key], key)
        for key in ("step_index", "turn_number", "window_index", "window_step_index", "deadline_at", "virtual_tick", "active_depth"):
            _integer(row[key], key)
        for key in ("certified_selected_progress_count", "candidate_count", "certified_required_count"):
            if row[key] is not None:
                _integer(row[key], key)
        for key in ("e_observed_selected_count", "e_observed_required_count"):
            if row[key] is not None:
                raise C8G2RunnerError("diagnostic禁止伪造E observed count")
        replay.exact_equal_v3(row["q_authority"], "G_CERTIFIED_PUBLIC_HISTORY", "diagnostic q authority")
        replay.exact_equal_v3(row["e_count_availability"], "NOT_EXPOSED", "diagnostic unavailable counts")
        _integer(completed_window_count, "completed windows")
        replay._object(row["current_position"], "turn_number turn_player_id actor_id phase availability reason", "current public position")
        _integer(row["current_position"]["turn_number"], "current turn")
        _text_id(row["current_position"]["phase"], "current phase")
        for key in ("opening_ref_commitment", "fresh_context_commitment"):
            _sha(row[key], key)
        quotient = tuple(row[k] for k in ("logical_obligation_identity", "certified_selected_progress_count", "candidate_count", "stage"))
        self.repeated_quotient = self.repeated_quotient+1 if quotient[0] is not None and quotient == self.last_quotient else 0
        if quotient[0] is not None and quotient != self.last_quotient:
            self.last_progress_step = accepted
            self.last_progress_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
        self.last_quotient = quotient
        self.steps_in_turn = self.steps_in_turn+1 if self.last_step and self.last_step["turn_number"] == row["turn_number"] else 1
        self.boundary = data
        self.last_step = row
        for key, count in data["public"]["effects_delta"].items():
            self.effects[key] += count
        if data["public"]["effects_delta"]["damage_events"]:
            self.last_damage_turn = row["turn_number"]
        if data["public"]["effects_delta"]["death_events"]:
            self.last_death_turn = row["turn_number"]
        for key in self.histograms:
            value = row[key]
            self.histograms[key][value] = self.histograms[key].get(value, 0)+1
        self.schedule["accepted_timeout_steps" if row["actual_timeout"] else "accepted_on_time_steps"] += 1
        if row["window_step_index"] == 0:
            self.schedule["actual_timeout_window_count" if row["actual_timeout"] else "on_time_window_count"] += 1
        self.schedule["continuation_steps"] += row["continued"]
        row = {**row, "aggregate": {k: v for k, v in data["public"].items() if k != "effects_delta"},
               "effects_delta": dict(data["public"]["effects_delta"]), "wall_elapsed_seconds": time.monotonic()-self.started}
        self.rows.append(row)
        if len(self.rows) > 50:
            raise C8G2RunnerError("diagnostic delta segment超过50条")
        if accepted % 50 == 0:
            self._publish("RUNNING", accepted, accepted, completed_window_count)

    def _publish(self, status: str, accepted: int, evidenced: int, completed: int) -> None:
        for key, value in (("accepted", accepted), ("evidenced", evidenced), ("completed", completed)):
            _integer(value, key)
        if evidenced > accepted:
            raise C8G2RunnerError("diagnostic evidenced超过accepted")
        generation = self.generation
        self.generation += 1
        name = f"generation-{generation:06d}-step-{accepted:08d}.json"
        observed = self.boundary["public"]
        turn = None if self.last_step is None else self.last_step["turn_number"]
        snapshot = {"schema": "sgs-c8-g-natural-diagnostic-snapshot-v1", "version": 1, "scope": "REPORT_ONLY",
            "resume_capable": False, "gameplay_authority": False, "promotion_authority": False,
            "resume_capability": "NONE", "generation": generation, "previous_snapshot_ref": self.previous,
            "status": status, "metadata": self.metadata, "last_accepted_step": accepted,
            "last_fully_evidenced_step": evidenced, "last_durable_diagnostic_step": self.last_durable,
            "last_authoritative_replay_step": None, "completed_window_count": completed,
            "metrics_observed_at_step": observed["accepted_step_count"], "boundary": observed,
            "current_position": self.initial_position if self.last_step is None else self.last_step["current_position"],
            "metrics_availability": "COMPLETE_ACCEPTED_BOUNDARY" if observed["accepted_step_count"] == accepted else "LAST_OBSERVED_BOUNDARY_TAIL_MISSING",
            "sanitized_public_progress_digest": _identity({"boundary": observed, "position": self.last_step}),
            "position_and_obligation": self.last_step, "effects": dict(self.effects), "schedule": dict(self.schedule),
            "histograms": self.histograms, "delta_step_rows": self.rows,
            "rolling_indicators": {"turns_since_damage": None if self.last_damage_turn is None or turn is None else turn-self.last_damage_turn,
                "turns_since_death": None if self.last_death_turn is None or turn is None else turn-self.last_death_turn,
                "steps_in_current_turn": self.steps_in_turn, "long_turn_review_indicator": self.steps_in_turn >= 256,
                "damage_never_seen": self.last_damage_turn is None, "death_never_seen": self.last_death_turn is None,
                "repeated_certified_obligation_state_count": self.repeated_quotient,
                "last_obligation_progress_step": self.last_progress_step,
                "review_indicator_authority": "REPORT_ONLY"},
            "ops": {"observed_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    "wall_elapsed_seconds": time.monotonic()-self.started, "last_snapshot_write_at": self.last_write_at,
                    "last_obligation_progress_at": self.last_progress_at},
            "io": {"policy": "FAIL_CLOSED_AFTER_CURRENT_COMMITTED_STEP", "same_byte_retry_limit": 1,
                "io_failure_seen": self.io_failed, "io_error_class": "OSError" if self.io_failed else None,
                "last_attempted_generation": generation, "stop_reason": status,
                "accepted_but_not_evidenced": accepted > evidenced}}
        snapshot["checksum"] = _identity(snapshot)
        diagnostic_snapshot_from_dict_v1(snapshot)
        private = {"schema": "sgs-c8-g-private-diagnostic-generation-v1", "generation": generation,
                   "public_checksum": snapshot["checksum"], "data": self.boundary["private"]}
        self._write_bytes(self.root/"private"/name, _canonical_bytes(private)+b"\n", immutable=True)
        self._write_bytes(self.root/"progress"/name, _canonical_bytes(snapshot)+b"\n", immutable=True)
        pointer = {"schema": "sgs-c8-g-report-only-latest-v1", "generation": generation,
            "path": "progress/"+name, "checksum": snapshot["checksum"], "last_accepted_step": accepted,
            "last_durable_diagnostic_step": accepted, "last_authoritative_replay_step": None, "resume_capability": "NONE"}
        self._write_bytes(self.root/"latest.json", _canonical_bytes(pointer)+b"\n", immutable=False)
        self.previous = {"path": pointer["path"], "checksum": snapshot["checksum"]}
        self.last_durable = accepted
        self.last_write_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
        self.rows = []

    def finish(self, *, status: str, last_accepted_step: int, last_fully_evidenced_step: int,
               completed_window_count: int) -> None:
        if self.boundary is None or self.metadata is None:
            return
        try:
            self._publish(status, last_accepted_step, last_fully_evidenced_step, completed_window_count)
        except (OSError, DiagnosticIOFailureV1) as exc:
            receipt = {"status": "IO_FAILURE", "last_accepted_step": last_accepted_step,
                       "last_durable_diagnostic_step": self.last_durable, "last_authoritative_replay_step": None,
                       "resume_capability": "NONE", "last_fully_evidenced_step": last_fully_evidenced_step}
            print(json.dumps(receipt), file=sys.stderr)
            try:
                self._write_bytes(self.root/f"failure-receipt-{self.generation:06d}.json",
                                  _canonical_bytes(receipt)+b"\n", immutable=True)
            except (OSError, DiagnosticIOFailureV1):
                pass
            raise DiagnosticIOFailureV1("IO_FAILURE: 最终diagnostic尾态未保证落盘") from exc


def flat_step_records_v4(artifact: Mapping[str, object]) -> list[dict[str, object]]:
    return [step for window in artifact["window_records"] for step in window["steps"]]


def construct_timed_execution_identity_v1(*, repo_root: Path,
        session_binding_identity: str, seed: int, run_label: str,
        max_steps: int, max_windows: int) -> dict[str, object]:
    """正式 step-0 身份材料；dry-run 与 natural 使用同一构造式，不执行 gameplay。"""
    seed = _integer(seed, "seed")
    contract.canonical_cell_id_v1(seed)
    if type(run_label) is not str or _RUN_LABEL_RE.fullmatch(run_label) is None:
        raise C8G2RunnerError("run_label必须是deterministic lowercase id")
    _integer(max_steps, "max_steps", minimum=1)
    _integer(max_windows, "max_windows", minimum=1)
    _sha(session_binding_identity, "session_binding_identity")
    profile = validate_execution_order_profile_v1(repo_root=repo_root)
    binding = current_binding_snapshot_v1(contract.FullGameRegistryV1.canonical(), repo_root)
    construction = {"schema": "sgs-c8-g-timed-construction-v2", "seed": seed, "run_label": run_label,
                    "scope": C8_G2_SCOPE_MARKER, "max_steps": max_steps, "max_windows": max_windows,
                    "execution_order_profile": profile}
    cell_execution = _identity({"schema": "sgs-c8-g-cell-execution-v1", "construction": construction,
                               "session_binding_identity": session_binding_identity,
                               "g2_binding_identity": _identity(binding)})
    return {"construction": construction, "binding": binding,
            "cell_execution_identity": cell_execution}


def _execute_timed_v3(*, repo_root: Path, bundle: CanonicalSessionBundleV1, seed: int,
                      max_steps: int, max_windows: int, run_label: str,
                      full_game: bool = False, test_only: bool = False,
                      test_only_factory: object | None = None,
                      expected_initial_record: Mapping[str, object] | None = None,
                      diagnostic_sink: ReportOnlyDiagnosticSinkV1 | None = None) -> dict[str, object]:
    from .c8_timed_8p_full_game_production_replay_v1 import PrivateIncrementalC6RecorderV1
    if test_only:
        from .c8_timed_8p_full_game_production_replay_v1 import (
            ExplicitTestOnlyFixtureFactoryV1,
            finalize_test_only_timed_artifact_v1,
        )
        if type(test_only_factory) is not ExplicitTestOnlyFixtureFactoryV1:
            raise C8G2RunnerError(
                "test-only runner dispatch必须使用ExplicitTestOnlyFixtureFactoryV1"
            )
    elif test_only_factory is not None:
        raise C8G2RunnerError("formal runner不得携带test-only factory")
    profile = validate_execution_order_profile_v1(repo_root=repo_root)
    recorder = PrivateIncrementalC6RecorderV1(
        bundle.session, seed=seed, max_steps=max_steps, test_only=test_only
    )
    if expected_initial_record is not None:
        recorder.compare_initial(expected_initial_record)
    registry = contract.FullGameRegistryV1.canonical()
    execution = construct_timed_execution_identity_v1(repo_root=repo_root, session_binding_identity=bundle.session_binding_identity,
        seed=seed, run_label=run_label, max_steps=max_steps, max_windows=max_windows)
    binding = execution["binding"]
    initial = _capture_public_state(bundle)
    construction = execution["construction"]
    cell_execution = execution["cell_execution_identity"]
    relation = contract.WindowRelationEvidenceV3.independent_decision_v3()
    records: list[dict[str, object]] = []
    private_timed: list[dict[str, object]] = []
    previous_context = None
    last_decision = None
    last_evidenced = 0
    status = "FAILED"
    pending_failure = None
    sequence = 1
    try:
        if diagnostic_sink is not None:
            diagnostic_sink.start(recorder.diagnostic_boundary_v1(), construction=construction,
                                  cell_execution_identity=cell_execution, binding=binding,
                                  position_bytes=_canonical_bytes(diagnostic_public_position_v1(initial)))
        while not bundle.session.is_finished and len(records) < max_windows and bundle.session.step_count < max_steps:
            sequence = len(records)+1
            operations: list[dict[str, object]] = []

            def operation(name: str, call: Callable[[], object], projection: Callable[[object], object] = lambda v: v) -> object:
                before = bundle.runtime.controller_callback_security_audit_v1()
                result = call()
                after = bundle.runtime.controller_callback_security_audit_v1()
                operations.append({"index": len(operations), "name": name,
                    "before_epoch": before.operation_attempt_epoch, "after_epoch": after.operation_attempt_epoch,
                    "result_identity": _identity(projection(result))})
                return result

            runtime_start = len(bundle.runtime.state.runtime_events)
            controller_start = len(bundle.controller.public_event_trace_v1())
            observe = bundle.orchestrator.observe_and_open_or_refresh_v1
            observation_projection = lambda v: {"context": v[0].to_public_dict_v1(), "ref": v[1].to_dict(), "opened": v[2]}
            opening_context, ref, opened = operation("OPEN", observe, observation_projection)
            context = opening_context
            if opened is not True:
                raise C8G2RunnerError("fresh production context必须打开新window")
            if diagnostic_sink is not None:
                intent = sequence % 4 == 0
                skipped = intent and context.applicability is prod.ProductionContextApplicabilityV1.PRIVATE_ORDINAL_TIMEOUT_UNRESOLVED
                diagnostic_sink.note_open(_canonical_bytes({"window_index": sequence,
                    "timeout_intent": intent, "actual_timeout": intent and not skipped, "skipped_unresolved": skipped}))
            active = bundle.runtime.state.virtual_time_state.window_stack.active_window
            if active is None or active.parent_window_id is not None:
                raise C8G2RunnerError("selected C6不得reopen/resume已关闭parent")
            contract.validate_relation_window_kind_v2(relation, _relation_window_kind_from_raw_v2(context.window_kind.value, context.applicability.value))
            if relation.post_step_context_identity is not None:
                replay.exact_equal_v3(relation.post_step_context_identity, context.context_identity, "fresh successor context")
            refreshes = []
            for _ in range(2):
                before_refresh = _capture_public_state(bundle)
                again = operation("REFRESH", observe, observation_projection)
                replay.exact_equal_v3(observation_projection(again), {"context": context.to_public_dict_v1(), "ref": ref.to_dict(), "opened": False}, "same context refresh")
                replay.exact_equal_v3(_capture_public_state(bundle), before_refresh, "refresh不刷新deadline/state")
                refreshes.append({"deadline_at": active.deadline_at, "opened_at": active.opened_at,
                                  "state_identity": before_refresh["state_identity"]})
            progress = None
            if context.applicability is prod.ProductionContextApplicabilityV1.PRIVATE_ORDINAL_TIMEOUT_UNRESOLVED:
                if previous_context is None:
                    raise C8G2RunnerError("DRIVER_LIVENESS_UNRESOLVED: 缺少canonical prior accepted入口")
                progress = contract.open_public_ordinal_progress_v1(
                    run_binding_identity=cell_execution, execution_order_profile_identity=profile["profile_identity"],
                    opening_ref_identity=ref.authority_ref_identity, opening_context_identity=context.context_identity,
                    entry_step_index=bundle.session.step_count, global_window_index=sequence,
                    deadline_at=active.deadline_at, phase=context.phase.value, turn_number=context.turn_number,
                    turn_player_id=context.current_player_id, actor_id=context.current_actor_id,
                    proposal_count=context.proposal_count, entry_pre_context_identity=previous_context.context_identity,
                    entry_pre_phase=previous_context.phase.value, entry_pre_actor_id=previous_context.current_actor_id)
            window_steps = []
            input_ref = None
            while True:
                if bundle.session.step_count >= max_steps:
                    raise C8G2RunnerError("accepted guard到达且义务未完成；保留同窗尾态，禁止扩预算")
                local_index = len(window_steps)
                # Fresh execution context is never rebound to the opening ownership.
                fresh = operation("FRESH_EXECUTION_CONTEXT", bundle.adapter.observe_production_decision_context_v1,
                                  lambda v: v.to_public_dict_v1())
                replay.exact_equal_v3(fresh.to_public_dict_v1(), context.to_public_dict_v1(), "fresh execution boundary")
                replay.exact_equal_v3(bundle.runtime.active_window_ref().to_dict(), ref.to_dict(), "same active B ref")
                driver_input, action_ids = public_driver_input_v1(session=bundle.session, context_value=context,
                    formal_seed=seed, global_window_index=sequence, deadline_at=active.deadline_at,
                    public_ordinal_progress=progress)
                driver = contract.choose_formal_driver_action_v1(driver_input)
                driver_dict = replay.driver_decision_dict_v3(driver_input)
                actions = [{**option.to_dict(), "signed_action_id_commitment": _action_commitment(action_ids[option.public_ordinal])}
                           for option in driver_input.public_actions]
                public_legal = {"actions": actions, "proposal_order_identity": driver_input.proposal_order_identity,
                                "legal_set_commitment": _identity(actions)}
                pre = _capture_public_state(bundle)
                recorder.before()
                if local_index == 0:
                    operation("ADVANCE", lambda: _advance_virtual_time(bundle, driver.decision_tick),
                              lambda v: {"state_identity": bundle.runtime.state.state_identity})
                    input_ref = bundle.runtime.state.input_chain_tip
                replay.exact_equal_v3(bundle.runtime.state.virtual_time_state.now_tick, driver.decision_tick, "same deadline/tick")
                security_before = bundle.runtime.controller_callback_security_audit_v1()
                due = result = selected = returned = None
                if driver.actual_timeout:
                    due = operation("DUE", lambda: bundle.runtime.current_timeout_due_commitment_v1(ref), lambda v: v.to_dict())
                    result = operation("RESOLVE", lambda: bundle.controller.resolve_timeout_v1(ref, timeout_due_commitment=due), lambda v: v.to_public_dict_v1())
                    if result.result_kind != "RESOLVED_SINGLE" or len(result.selected_actions) != 1:
                        raise C8G2RunnerError("current E只能一提交步后close")
                    selected = result.selected_actions[0]
                    ordinal = selected.public_ordinal
                    replay.exact_equal_v3(selected.signed_action_id, action_ids[ordinal], "C fresh selected action")
                    inner, counters = recorder.after(selected.signed_action_id)
                else:
                    ordinal = driver.chosen_public_ordinal
                    returned = operation("FORWARD_ON_TIME", lambda: bundle.runtime.forward_on_time_signed_action_id(ref, signed_action_id=action_ids[ordinal]))
                    inner, counters = recorder.after(action_ids[ordinal])
                replay.exact_equal_v3(counters["post_step_count"], counters["pre_step_count"]+1, "one accepted forward")
                next_context = None if bundle.session.is_finished else operation("POST_OBSERVE",
                    bundle.adapter.observe_production_decision_context_v1, lambda v: v.to_public_dict_v1())
                next_public = None if next_context is None else next_context.to_public_dict_v1()
                liveness = None
                after_progress = None
                if progress is not None:
                    boundary = _post_public_boundary_v1(next_context)
                    after_progress = contract.advance_public_ordinal_progress_v1(progress, chosen_ordinal=ordinal,
                        post_step_count=bundle.session.step_count, **boundary)
                    liveness = {"before": progress.to_dict(), "after": after_progress.to_dict(), "post_public_boundary": boundary}
                continued = after_progress is not None and after_progress.stage != "DONE"
                action_ref = {"inner_decision_index": inner["index"], "signed_action_id_commitment": _action_commitment(action_ids[ordinal]),
                    "ordered_legal_action_commitment": inner["legal_action_set_sha256"], "executed_public_ordinal": ordinal,
                    "executed_public_action_family": driver_input.public_actions[ordinal].public_action_family}
                continuation_material = {"window_authority_ref_identity": ref.authority_ref_identity,
                    "step_index": inner["index"]+1, "window_step_index": local_index,
                    "production_context_identity": context.context_identity, "inner_decision_identity": _identity(inner),
                    "production_action_ref": action_ref, "pre_step_count": counters["pre_step_count"],
                    "post_step_count": counters["post_step_count"], "deadline_at": active.deadline_at,
                    "decision_tick": driver.decision_tick}
                logical_step = None
                if continued:
                    logical_step = replay.logical_continuation_identity_v1(continuation_material, progress)
                    operation("CONTINUE_ON_TIME", lambda: bundle.runtime.continue_multi_step_obligation(ref,
                        expected_step_index=local_index, logical_step_identity=logical_step), lambda v: v.value)
                    replay.exact_equal_v3(bundle.runtime.active_window_ref().to_dict(), ref.to_dict(), "continued active owner")
                    replay.exact_equal_v3(bundle.runtime.state.virtual_time_state.now_tick, driver.decision_tick, "continued tick")
                    actual_progress = bundle.runtime.state.logical_obligations[-1]
                    replay.exact_equal_v3(actual_progress.next_step_index, local_index+1, "B progress +1")
                elif driver.actual_timeout:
                    operation("CONFIRM_TIMEOUT_CLOSED", lambda: bundle.orchestrator.confirm_timeout_context_closed_v1(ref, opening_context))
                else:
                    operation("CLOSE_ON_TIME", lambda: bundle.orchestrator.close_completed_on_time_context_v1(ref, opening_context), lambda v: v.to_dict())
                if not continued and bundle.runtime.active_window_ref() is not None:
                    raise C8G2RunnerError("completed义务仍有active timer")
                post = _capture_public_state(bundle)
                post_observation_identity = _identity({"schema": "sgs-c8-g-post-step-observation-v4",
                    "inner_decision_identity": _identity(inner), "next_context": next_public,
                    "post_state_identity": post["state_identity"]})
                if not continued:
                    operation("STALE_REJECT", lambda: _stale_context_rejected_v1(bundle, ref, opening_context))
                security_after = bundle.runtime.controller_callback_security_audit_v1()
                runtime_events = [v.to_dict() for v in bundle.runtime.state.runtime_events[runtime_start:]]
                controller_events = [v.to_public_dict_v1() for v in bundle.controller.public_event_trace_v1()[controller_start:]]
                forwards = [v for v in runtime_events if v["inner_transition_identity"] is not None]
                disposition = "MULTI_STEP_CONTINUED" if continued else "WINDOW_CLOSED_BY_TIMEOUT" if driver.actual_timeout else "WINDOW_CLOSED_BY_ACTION"
                dispositions = [v for v in runtime_events if v["event_kind"] == disposition]
                if len(forwards) != 1 or len(dispositions) != 1:
                    raise C8G2RunnerError("每步必须唯一B forward与对应CONTINUE/CLOSE")
                forward, disposition_event = forwards[0], dispositions[0]
                production_binding = {"cell_execution_identity": cell_execution, "inner_decision_index": inner["index"],
                    **continuation_material, "global_window_index": sequence, "window_id": ref.window_id,
                    "opening_production_context_identity": opening_context.context_identity,
                    "turn_number": context.turn_number, "turn_player_id": context.current_player_id, "actor_id": context.current_actor_id,
                    "phase": context.phase.value, "production_window_kind": context.window_kind.value,
                    "driver_window_kind": driver_input.window_kind.value, **counters,
                    "pre_public_state_identity": pre["adapter_public_state_identity"], "post_public_state_identity": post["adapter_public_state_identity"],
                    "pre_execution_identity": inner["execution_before_sha256"], "post_execution_identity": inner["execution_after_sha256"],
                    "pre_state_identity": inner["state_before_sha256"], "post_state_identity": inner["state_after_sha256"],
                    **{key: inner[key] for key in ("event_start", "event_end", "rng_start", "rng_end")},
                    "opened_at": active.opened_at, "virtual_input_ref": input_ref,
                    "runtime_event_range": {"start": runtime_start, "end": runtime_start+len(runtime_events)},
                    "controller_event_range": {"start": controller_start, "end": controller_start+len(controller_events)},
                    "window_disposition_ref": disposition_event["event_identity"],
                    "relation_ref": _identity(relation.to_dict()) if local_index == 0 else _identity({"opening_window_ref": ref.authority_ref_identity})}
                timed_private = {"runtime_events": runtime_events, "controller_events": controller_events,
                    "security_before": security_before.to_dict(), "security_after": security_after.to_dict(),
                    "controller_result": None, "e_legal_snapshot": None, "e_issuance": None, "due": None}
                if not driver.actual_timeout:
                    decision = {"schema": replay.ON_TIME_SCHEMA, "kind": replay.ON_TIME_KIND, "binding": production_binding,
                        "fresh_public_legal_set": public_legal, "driver_input": driver_input.identity_material(), "driver_decision": driver_dict,
                        "liveness": liveness,
                        "normal_forward": {"returned_public_state_identity": returned, "inner_transition_identity": forward["inner_transition_identity"],
                                           "runtime_forward_event_identity": forward["event_identity"]},
                        "completion": {"kind": "ON_TIME_CONTEXT_CLOSED", "close_event_identity": disposition_event["event_identity"],
                                       "closed_window_identity": disposition_event["window_state_identity"], "completed_context_identity": opening_context.context_identity,
                                       "post_step_observation_identity": post_observation_identity}}
                else:
                    issuance = bundle.adapter.public_issuance_evidence_v1()[-1]
                    snapshot = bundle.adapter.public_legal_set_evidence_v1()[-1]
                    c_selected = selected.to_public_dict_v1()
                    timed_private.update(controller_result=result.to_public_dict_v1(), e_legal_snapshot={**dict(snapshot.identity_payload_v1()),
                                         "public_legal_set": snapshot.public_legal_set.to_dict(), "snapshot_identity": snapshot.snapshot_identity},
                                         e_issuance=issuance, due=due.to_dict())
                    selected_identity = _identity(c_selected)
                    receipt_link = {"receipt_identity": selected.receipt_identity, "c_result_identity": result.result_identity,
                        "c_selected_action_identity": selected_identity, "runtime_forward_event_identity": forward["event_identity"],
                        "runtime_disposition_event_identity": disposition_event["event_identity"], "timeout_due_identity": due.commitment_identity,
                        "signed_action_id_commitment": action_ref["signed_action_id_commitment"]}
                    decision = {"schema": replay.TIMEOUT_SCHEMA, "kind": replay.TIMEOUT_KIND, "binding": production_binding,
                        "timeout_schedule_decision": {"driver_input": driver_input.identity_material(), "driver_decision": driver_dict},
                        "timeout_due_commitment": {"commitment_identity": due.commitment_identity, "deadline_at": active.deadline_at,
                                                   "decision_tick": driver.decision_tick, "window_authority_ref_identity": ref.authority_ref_identity},
                        "fresh_public_legal_set_and_canonical_order": {"public_legal_set": public_legal, "legal_set_identity": selected.legal_set_identity,
                             "canonical_order_identity": snapshot.canonical_public_ordering_identity, "snapshot_identity": snapshot.snapshot_identity},
                        "c_resolver_result_and_selected_action_ref": {"result_identity": result.result_identity, "result_kind": result.result_kind,
                             "selected_action_identity": selected_identity, "production_action_ref": action_ref, "receipt_identity": selected.receipt_identity,
                             "selection_identity": selected.selection_identity},
                        "e_fresh_confirmation_and_issuance_evidence": {"issuance_identity": issuance["issuance_identity"],
                             "candidate_identity": issuance["candidate_identity"], "public_ordinal": ordinal,
                             "signed_action_id_commitment": action_ref["signed_action_id_commitment"], "legal_set_identity": selected.legal_set_identity,
                             "canonical_order_identity": snapshot.canonical_public_ordering_identity, "timeout_due_identity": due.commitment_identity,
                             "context_identity": context.context_identity, "ledger_before_identity": issuance["issuance_security_ledger_before_identity"],
                             "ledger_after_identity": issuance["issuance_security_ledger_after_identity"]},
                        "b_timeout_receipt_link": receipt_link,
                        "completion": {"kind": "TIMEOUT_CONTEXT_CLOSED", "receipt_identity": selected.receipt_identity,
                             "runtime_disposition_event_identity": disposition_event["event_identity"], "obligation_progress_ref": None,
                             "post_step_observation_identity": post_observation_identity},
                        "security_operation_evidence": {"before_identity": _identity(security_before.to_dict()), "after_identity": _identity(security_after.to_dict()),
                             "before_epoch": security_before.operation_attempt_epoch, "after_epoch": security_after.operation_attempt_epoch}}
                if continued:
                    decision["completion"] = {"kind": "ON_TIME_OBLIGATION_CONTINUED",
                        "logical_step_identity": logical_step, "continue_event_identity": disposition_event["event_identity"],
                        "progress_identity": actual_progress.progress_identity,
                        "post_step_observation_identity": post_observation_identity}
                decision["evidence_identity"] = _identity(decision)
                decision = replay.production_decision_from_dict_v1(decision).to_dict()
                completion = replay.completion_from_decision_v1(decision)
                step = {"schema": "sgs-c8-g-accepted-step-record-v1", "window_step_index": local_index,
                    "context": context.to_public_dict_v1(), "pre_state": pre, "post_state": post,
                    "decision": decision, "completion": completion.to_dict(),
                    "post_step_observation": {"next_context": next_public, "observation_identity": post_observation_identity},
                    "operations": operations}
                step["record_identity"] = _window_record_identity(step)
                window_steps.append(step)
                private_timed.append(timed_private)
                last_decision, last_evidenced, previous_context = decision, bundle.session.step_count, context
                if diagnostic_sink is not None:
                    diagnostic_sink.accept(recorder.diagnostic_boundary_v1(), step_bytes=diagnostic_step_projection_v1(step,
                        relation_kind=relation.causal_relation_kind.value if local_index == 0 else "ON_TIME_OBLIGATION_CONTINUED"),
                        completed_window_count=len(records)+int(not continued))
                if not continued:
                    break
                context, progress = next_context, after_progress
                operations = []
                runtime_start = len(bundle.runtime.state.runtime_events)
                controller_start = len(bundle.controller.public_event_trace_v1())
            record = {"schema": C8_G2_WINDOW_SCHEMA, "contract_version": C8_G2_RUNNER_VERSION, "sequence": sequence,
                "context": opening_context.to_public_dict_v1(), "window_ref": ref.to_dict(),
                "opened_window": active.to_dict(), "refreshes": refreshes,
                "relation": relation.to_dict(), "steps": window_steps}
            record["record_identity"] = _window_record_identity(record)
            records.append(record)
            if next_context is None or next_context.parent_context_identity is None:
                relation = contract.WindowRelationEvidenceV3.independent_decision_v3()
            else:
                replay.exact_equal_v3(next_context.parent_context_identity, context.context_identity, "last accepted step causal lineage")
                kind = contract.classify_post_commit_relation_v2(window_kind=_relation_window_kind_from_raw_v2(next_context.window_kind.value, next_context.applicability.value),
                    causal_parent_context_identity=next_context.parent_context_identity)
                relation = contract.WindowRelationEvidenceV3.post_commit_v3(causal_relation_kind=kind,
                    causal_parent_window_identity=record["record_identity"], causal_parent_context_identity=context.context_identity,
                    originating_step_index=inner["index"]+1, originating_step_identity=_identity(inner),
                    originating_post_production_revision=counters["post_revision"], originating_post_public_state_identity=post["state_identity"],
                    originating_decision_kind=decision["kind"], originating_decision_evidence_identity=decision["evidence_identity"],
                    originating_completion_identity=completion.completion_identity, parent_window_close_status=completion.disposition,
                    post_step_context_identity=next_context.context_identity)
        if bundle.session.is_finished is not full_game:
            raise C8G2RunnerError("terminal与请求scope不一致；禁止截断或synthetic终局")
        if bundle.runtime.state.pending_deadline is not None or bundle.runtime.state.virtual_time_state.window_stack.windows:
            raise C8G2RunnerError("停止时仍存在active/suspended window或pending deadline")
        final = _capture_public_state(bundle)
        artifact = {"schema": C8_G2_RUNNER_SCHEMA if full_game else C8_G2_SMOKE_SCHEMA, "contract_version": C8_G2_RUNNER_VERSION,
            "runner_id": C8_G2_RUNNER_ID, "runner_contract_identity": C8_G2_RUNNER_CONTRACT_IDENTITY,
            "scope": "FULL_GAME_REAL_PRODUCTION_TRACE" if full_game else C8_G2_SCOPE_MARKER,
            "full_game": full_game, "promotion": False, "test_only": test_only, "seed": seed,
            "construction": construction, "current_binding": binding, "registry": registry.to_dict(),
            "session_binding_identity": bundle.session_binding_identity, "runtime_instance_identity": bundle.runtime_instance_identity,
            "controller_instance_identity": bundle.controller_instance_identity, "cell_execution_identity": cell_execution,
            "initial_state": initial, "final_state": final, "window_records": records,
            "completed_windows": len(records), "completed_production_steps": bundle.session.step_count,
            "private_production_record": recorder.finish(), "private_timed_transcript": private_timed,
            "final_security_audit": bundle.runtime.controller_callback_security_audit_v1().to_dict()}
        artifact["public_projection"] = public_projection_v3(artifact)
        artifact["artifact_identity"] = _identity(artifact)
        if test_only:
            finalize_test_only_timed_artifact_v1(
                artifact, fixture_factory=test_only_factory, repo_root=repo_root
            )
        else:
            # The default path is deliberately the unchanged formal parser.
            timed_artifact_from_dict_v3(artifact, full_game=full_game, repo_root=repo_root)
        status = "COMPLETED" if full_game else "BOUNDED_STOP"
        return artifact
    except BaseException as exc:
        status = "IO_FAILURE" if isinstance(exc, DiagnosticIOFailureV1) else "INTERRUPTED" if isinstance(exc, KeyboardInterrupt) else "FAILED"
        for controlled in ("DRIVER_LIVENESS_UNRESOLVED", "DRIVER_LIVENESS_BLOCKED", "TIMEOUT_UNRESOLVED"):
            if str(exc).startswith(controlled):
                status = controlled
        if bundle.session.step_count:
            valid = last_decision if last_evidenced == bundle.session.step_count else None
            pending_failure = _committed_failure(bundle, records, sequence, valid, reason=status,
                error_class=type(exc).__name__, last_evidenced=last_evidenced,
                last_durable=None if diagnostic_sink is None else diagnostic_sink.last_durable)
            raise pending_failure from exc
        raise
    finally:
        if diagnostic_sink is not None:
            try:
                diagnostic_sink.finish(status=status, last_accepted_step=bundle.session.step_count,
                    last_fully_evidenced_step=last_evidenced, completed_window_count=len(records))
            except DiagnosticIOFailureV1 as io_error:
                if bundle.session.step_count:
                    pending_failure = _committed_failure(bundle, records, sequence,
                        last_decision if last_evidenced == bundle.session.step_count else None, reason="IO_FAILURE",
                        error_class=type(io_error).__name__, last_evidenced=last_evidenced, last_durable=diagnostic_sink.last_durable)
                    raise pending_failure from io_error
                raise
            finally:
                if pending_failure is not None:
                    f = pending_failure.failure_artifact
                    f["last_durable_diagnostic_step"] = diagnostic_sink.last_durable
                    f["failure_identity"] = _identity({k:v for k,v in f.items() if k != "failure_identity"})


def execute_bounded_smoke_v1(*, repo_root: Path | str, seed: int = 0, max_steps: int = 8,
                            max_windows: int = 8, run_label: str = "bounded-smoke",
                            bundle_factory: Callable[..., CanonicalSessionBundleV1] | None = None,
                            test_only: bool = False,
                            diagnostic_sink: ReportOnlyDiagnosticSinkV1 | None = None) -> dict[str, object]:
    if _integer(seed, "seed") != 0 or _integer(max_steps, "max_steps", minimum=1) > 12 or _integer(max_windows, "max_windows", minimum=1) > 8:
        raise C8G2RunnerError("bounded限定seed0、最多8windows/12accepted steps")
    _boolean(test_only, "test_only")
    test_only_factory = None
    if test_only:
        from .c8_timed_8p_full_game_production_replay_v1 import ExplicitTestOnlyFixtureFactoryV1
        if type(bundle_factory) is not ExplicitTestOnlyFixtureFactoryV1:
            raise C8G2RunnerError(
                "test-only dispatch必须显式提供受信ExplicitTestOnlyFixtureFactoryV1"
            )
        test_only_factory = bundle_factory
    elif bundle_factory is not None:
        raise C8G2RunnerError("注入factory必须显式TEST_ONLY，禁止production proof")
    validate_execution_order_profile_v1(repo_root=repo_root)
    if test_only_factory is None:
        bundle = create_canonical_session_bundle_v1(seed=seed, run_label=run_label)
    else:
        bundle = test_only_factory.create_bundle(seed=seed, run_label=run_label)
    if type(bundle) is not CanonicalSessionBundleV1:
        raise C8G2RunnerError("bundle必须是exact canonical type")
    return _execute_timed_v3(repo_root=Path(repo_root).resolve(), bundle=bundle, seed=seed,
                            max_steps=max_steps, max_windows=max_windows, run_label=run_label, test_only=test_only,
                            test_only_factory=test_only_factory,
                            diagnostic_sink=diagnostic_sink)


def public_projection_v3(artifact: Mapping[str, object]) -> dict[str, object]:
    """Explicit allowlist. Entire writer artifacts include strictly private replay data."""
    return {"schema": "sgs-c8-g2-public-projection-v4", "full_game": artifact["full_game"], "promotion": False,
            "seed": artifact["seed"], "completed_windows": artifact["completed_windows"],
            "completed_production_steps": artifact["completed_production_steps"],
            "decisions": [replay.public_decision_projection_v1(s["decision"]) for s in flat_step_records_v4(artifact)],
            "relations": [w["relation"] for w in artifact["window_records"]]}


def _public_context_from_dict_v3(value: object) -> dict[str, object]:
    d = replay._object(value, "applicability context_identity contract_version current_actor_id current_player_id decision_identity mode_id obligation_identity parent_context_identity phase private_payload_present proposal_count proposal_order_identity public_ordinal_safe schema state_revision step_count turn_number window_kind", "production public context")
    replay.exact_equal_v3(d["contract_version"], 1, "E public context version")
    prod.ProductionDecisionContextV1(**{**d, "phase": prod.ProductionPhase(d["phase"]),
        "window_kind": clock_v1.TimedWindowKindV1(d["window_kind"]),
        "applicability": prod.ProductionContextApplicabilityV1(d["applicability"])})
    return d


def _public_state_from_dict_v3(value: object) -> dict[str, object]:
    d = replay._object(value, "schema contract_version phase turn_number current_actor_id current_player_id state_revision production_step_count production_finished adapter_public_state_identity adapter_authoritative_state_commitment production_execution_commitment runtime_state_identity runtime_event_chain_tip controller_event_chain_tip virtual_tick window_depth active_window_id state_identity", "public runtime state")
    replay.exact_equal_v3(d["schema"], "sgs-c8-g2-public-runtime-state-v4", "state schema")
    replay.exact_equal_v3(d["contract_version"], C8_G2_RUNNER_VERSION, "state version")
    for key in ("turn_number", "state_revision", "production_step_count", "virtual_tick", "window_depth"):
        _integer(d[key], key)
    _boolean(d["production_finished"], "production_finished")
    replay.exact_equal_v3(d["state_identity"], _identity({k:v for k,v in d.items() if k != "state_identity"}), "state hash")
    return d


def _window_record_from_dict(value: object, *, expected_sequence: int) -> dict[str, object]:
    d = replay._object(value, "schema contract_version sequence context window_ref opened_window refreshes relation steps record_identity", "timed window")
    replay.exact_equal_v3(d["schema"], C8_G2_WINDOW_SCHEMA, "window schema")
    replay.exact_equal_v3(d["contract_version"], C8_G2_RUNNER_VERSION, "window version")
    replay.exact_equal_v3(d["sequence"], expected_sequence, "window ordered index")
    context = _public_context_from_dict_v3(d["context"])
    ref = runtime_v1.WindowAuthorityRefV1.from_dict(d["window_ref"])
    opened = clock_v1.TimedDecisionWindowV1.from_dict(d["opened_window"])
    replay.exact_equal_v3(runtime_v1.WindowAuthorityRefV1.from_window(ref.runtime_instance_identity, opened).to_dict(), ref.to_dict(), "opening window/ref")
    for key, expected in (("actor_id", context["current_actor_id"]), ("decision_identity", context["decision_identity"]),
                          ("obligation_identity", context["obligation_identity"])):
        replay.exact_equal_v3(getattr(ref, key), expected, "opening ownership "+key)
    if opened.parent_window_id is not None or ref.parent_window_id is not None:
        raise C8G2RunnerError("selected C6的fresh successor不得打开active parent")
    relation = contract.WindowRelationEvidenceV3.from_dict(d["relation"])
    contract.validate_relation_window_kind_v2(relation, _relation_window_kind_from_raw_v2(context["window_kind"], context["applicability"]))
    refreshes = replay._exact_list(d["refreshes"], "same-context refreshes")
    if len(refreshes) != 2:
        raise C8G2RunnerError("必须保存两次same-context refresh")
    for refresh in refreshes:
        r = replay._object(refresh, "opened_at deadline_at state_identity", "refresh")
        replay.exact_equal_v3(r["opened_at"], opened.opened_at, "refresh opened_at")
        replay.exact_equal_v3(r["deadline_at"], opened.deadline_at, "refresh deadline")
        _sha(r["state_identity"], "refresh state")
    replay.exact_equal_v3(refreshes[0], refreshes[1], "refresh unchanged")
    steps = replay._exact_list(d["steps"], "accepted steps")
    if not steps:
        raise C8G2RunnerError("window缺少accepted step")
    previous = None
    for local, raw in enumerate(steps):
        step = replay._object(raw, "schema window_step_index context pre_state post_state decision completion post_step_observation operations record_identity", "accepted step record")
        replay.exact_equal_v3(step["schema"], "sgs-c8-g-accepted-step-record-v1", "step record schema")
        replay.exact_equal_v3(step["window_step_index"], local, "step local ordinal")
        fresh_context = _public_context_from_dict_v3(step["context"])
        if local == 0:
            replay.exact_equal_v3(fresh_context, context, "opening first execution")
        else:
            replay.exact_equal_v3(previous["post_step_observation"]["next_context"], fresh_context, "continuation fresh context")
        decision = replay.production_decision_from_dict_v1(step["decision"]).to_dict()
        b = decision["binding"]
        for key, expected in (("global_window_index", expected_sequence), ("window_step_index", local),
                              ("window_id", ref.window_id), ("window_authority_ref_identity", ref.authority_ref_identity),
                              ("opened_at", opened.opened_at), ("deadline_at", opened.deadline_at),
                              ("opening_production_context_identity", context["context_identity"]),
                              ("production_context_identity", fresh_context["context_identity"])):
            replay.exact_equal_v3(b[key], expected, "window execution binding "+key)
        for key, ck in (("actor_id", "current_actor_id"), ("turn_player_id", "current_player_id"),
                        ("turn_number", "turn_number"), ("phase", "phase"), ("pre_step_count", "step_count"),
                        ("pre_revision", "state_revision"), ("production_window_kind", "window_kind")):
            replay.exact_equal_v3(b[key], fresh_context[ck], "fresh public position "+key)
        expected_relation = _identity(d["relation"]) if local == 0 else _identity({"opening_window_ref": ref.authority_ref_identity})
        replay.exact_equal_v3(b["relation_ref"], expected_relation, "relation belongs to opening only")
        completion = replay.completion_from_decision_v1(decision)
        replay.exact_equal_v3(step["completion"], completion.to_dict(), "typed completion")
        continued = completion.disposition == "CONTINUED"
        if continued != (local < len(steps)-1):
            raise C8G2RunnerError("只有中间步CONTINUED且只最终步CLOSED")
        for label in ("pre_state", "post_state"):
            state = _public_state_from_dict_v3(step[label])
            prefix = "pre" if label == "pre_state" else "post"
            for key, sk in (("revision", "state_revision"), ("step_count", "production_step_count"),
                            ("public_state_identity", "adapter_public_state_identity")):
                replay.exact_equal_v3(state[sk], b[prefix+"_"+key], "actual step boundary "+key)
        replay.exact_equal_v3(step["post_state"]["window_depth"], int(continued), "actual active window depth")
        replay.exact_equal_v3(step["post_state"]["virtual_tick"], b["decision_tick"], "same decision tick")
        observation = replay._object(step["post_step_observation"], "next_context observation_identity", "post observation")
        nxt = observation["next_context"]
        if nxt is not None:
            _public_context_from_dict_v3(nxt)
        observed = _identity({"schema": "sgs-c8-g-post-step-observation-v4", "inner_decision_identity": b["inner_decision_identity"],
                             "next_context": nxt, "post_state_identity": step["post_state"]["state_identity"]})
        replay.exact_equal_v3(observation["observation_identity"], observed, "post observation commitment")
        replay.exact_equal_v3(observed, decision["completion"]["post_step_observation_identity"], "completion observation")
        if decision["kind"] == replay.ON_TIME_KIND and decision["liveness"] is not None:
            post = {"next_phase": None if nxt is None else nxt["phase"],
                    "next_actor_id": None if nxt is None else nxt["current_actor_id"],
                    "next_turn_number": None if nxt is None else nxt["turn_number"],
                    "next_turn_player_id": None if nxt is None else nxt["current_player_id"],
                    "next_proposal_count": 0 if nxt is None else nxt["proposal_count"]}
            replay.exact_equal_v3(decision["liveness"]["post_public_boundary"], post, "public liveness actual post context")
        expected = (["OPEN", "REFRESH", "REFRESH"] if local == 0 else []) + ["FRESH_EXECUTION_CONTEXT"]
        expected += ["ADVANCE"] if local == 0 else []
        expected += ["DUE", "RESOLVE"] if decision["kind"] == replay.TIMEOUT_KIND else ["FORWARD_ON_TIME"]
        expected += ["POST_OBSERVE"] if nxt is not None else []
        expected += ["CONTINUE_ON_TIME"] if continued else ["CONFIRM_TIMEOUT_CLOSED"] if decision["kind"] == replay.TIMEOUT_KIND else ["CLOSE_ON_TIME"]
        expected += [] if continued else ["STALE_REJECT"]
        ops = replay._exact_list(step["operations"], "operations")
        replay.exact_equal_v3([v["name"] for v in ops], expected, "完整有序操作transcript")
        for i, op in enumerate(ops):
            replay._object(op, "index name before_epoch after_epoch result_identity", "operation")
            replay.exact_equal_v3(op["index"], i, "operation index")
            if _integer(op["after_epoch"], "after epoch") < _integer(op["before_epoch"], "before epoch"):
                raise C8G2RunnerError("operation epoch倒退")
            _sha(op["result_identity"], "operation result")
            if i:
                replay.exact_equal_v3(ops[i-1]["after_epoch"], op["before_epoch"], "operation epoch continuity")
        replay.exact_equal_v3(step["record_identity"], _window_record_identity(step), "step record hash")
        previous = step
    replay.exact_equal_v3(d["record_identity"], _window_record_identity(d), "window hash")
    return d


def _validate_parent_origin_v4(relation: contract.WindowRelationEvidenceV3, previous: Mapping[str, object] | None) -> None:
    """Actual typed semantic origin gate, shared by parser and cheap detached-data negatives."""
    if relation.causal_parent_window_identity is not None:
        if previous is None:
            raise C8G2RunnerError("missing originating window")
        previous_last = previous["steps"][-1]
        prev = previous_last["decision"]
        for key, expected in (("causal_parent_window_identity", previous["record_identity"]),
                   ("causal_parent_context_identity", prev["binding"]["production_context_identity"]),
                   ("originating_step_index", prev["binding"]["step_index"]),
                   ("originating_step_identity", prev["binding"]["inner_decision_identity"]),
                   ("originating_decision_kind", prev["kind"]), ("originating_decision_evidence_identity", prev["evidence_identity"]),
                   ("originating_completion_identity", previous_last["completion"]["completion_identity"]),
                   ("originating_post_production_revision", prev["binding"]["post_revision"]),
                   ("originating_post_public_state_identity", previous_last["post_state"]["state_identity"])):
            replay.exact_equal_v3(getattr(relation, key), expected, "typed parent origin "+key)



def _timed_artifact_from_dict_common(value: object, *, full_game: bool,
                                     expected_test_only: bool,
                                     repo_root: Path | str | None = None) -> dict[str, object]:
    from .c8_timed_8p_full_game_production_replay_v1 import (
        _security_audit_from_dict,
        _validate_private_record,
        _validate_test_only_private_record,
    )
    d = replay._object(value, "schema contract_version runner_id runner_contract_identity scope full_game promotion test_only seed construction current_binding registry session_binding_identity runtime_instance_identity controller_instance_identity cell_execution_identity initial_state final_state window_records completed_windows completed_production_steps private_production_record private_timed_transcript final_security_audit public_projection artifact_identity", "G2 typed artifact")
    for key, expected in (("schema", C8_G2_RUNNER_SCHEMA if full_game else C8_G2_SMOKE_SCHEMA), ("contract_version", C8_G2_RUNNER_VERSION),
                          ("runner_id", C8_G2_RUNNER_ID), ("runner_contract_identity", C8_G2_RUNNER_CONTRACT_IDENTITY),
                          ("scope", "FULL_GAME_REAL_PRODUCTION_TRACE" if full_game else C8_G2_SCOPE_MARKER),
                          ("full_game", full_game), ("promotion", False)):
        replay.exact_equal_v3(d[key], expected, "G2 "+key)
    replay.exact_equal_v3(d["test_only"], expected_test_only, "G2 explicit test-only lane")
    _public_state_from_dict_v3(d["initial_state"])
    _public_state_from_dict_v3(d["final_state"])
    _security_audit_from_dict(d["final_security_audit"])
    construction = replay._object(d["construction"], "schema seed run_label scope max_steps max_windows execution_order_profile", "construction descriptor")
    replay.exact_equal_v3(construction["schema"], "sgs-c8-g-timed-construction-v2", "construction schema")
    validate_execution_order_profile_v1(construction["execution_order_profile"], repo_root=repo_root)
    replay.exact_equal_v3(construction["seed"], d["seed"], "construction seed")
    _integer(d["seed"], "seed")
    if _RUN_LABEL_RE.fullmatch(_text(construction["run_label"], "run_label")) is None:
        raise C8G2RunnerError("construction run_label非法")
    steps_limit = _integer(construction["max_steps"], "max_steps", minimum=1)
    windows_limit = _integer(construction["max_windows"], "max_windows", minimum=1)
    if not full_game and (d["seed"] != 0 or steps_limit > 12 or windows_limit > 8):
        raise C8G2RunnerError("bounded scope/limits不一致")
    if steps_limit > contract.C8_G1_MAX_PRODUCTION_STEPS_GUARD or windows_limit > contract.C8_G1_MAX_TIMER_WINDOWS_GUARD:
        raise C8G2RunnerError("full-game infrastructure limits越界")
    registry = contract.FullGameRegistryV1.from_dict(d["registry"])
    replay.exact_equal_v3(d["current_binding"], current_binding_snapshot_v1(registry, repo_root), "G2 current source identity")
    replay.exact_equal_v3(d["cell_execution_identity"], _identity({"schema": "sgs-c8-g-cell-execution-v1", "construction": construction,
                        "session_binding_identity": d["session_binding_identity"], "g2_binding_identity": _identity(d["current_binding"])}), "cell identity")
    records = replay._exact_list(d["window_records"], "window records")
    if not records or len(records) > windows_limit or len(records) > steps_limit:
        raise C8G2RunnerError("window count/limit不一致")
    replay.exact_equal_v3(d["completed_windows"], len(records), "completed windows")
    steps = flat_step_records_v4(d)
    if len(steps) > steps_limit:
        raise C8G2RunnerError("accepted steps超过冻结guard")
    replay.exact_equal_v3(d["completed_production_steps"], len(steps), "flat accepted step count")
    previous = None
    for i, raw in enumerate(records):
        w = _window_record_from_dict(raw, expected_sequence=i+1)
        first_step, last_step = w["steps"][0], w["steps"][-1]
        b = first_step["decision"]["binding"]
        replay.exact_equal_v3(b["cell_execution_identity"], d["cell_execution_identity"], "cross-cell timed splice")
        relation = contract.WindowRelationEvidenceV3.from_dict(w["relation"])
        replay.exact_equal_v3(relation.causal_parent_context_identity, w["context"]["parent_context_identity"], "public causal relation cannot be omitted")
        _validate_parent_origin_v4(relation, previous)
        if previous is not None:
            replay.exact_equal_v3(previous["steps"][-1]["post_step_observation"]["next_context"], w["context"], "fresh post/open context")
        first_decision = first_step["decision"]
        if first_decision["kind"] == replay.ON_TIME_KIND and first_decision["liveness"] is not None:
            if previous is None:
                raise C8G2RunnerError("private义务缺少canonical accepted入口")
            prior_context = previous["steps"][-1]["context"]
            context = w["context"]
            progress = contract.open_public_ordinal_progress_v1(run_binding_identity=d["cell_execution_identity"],
                execution_order_profile_identity=construction["execution_order_profile"]["profile_identity"],
                opening_ref_identity=b["window_authority_ref_identity"], opening_context_identity=context["context_identity"],
                entry_step_index=context["step_count"], global_window_index=i+1, deadline_at=b["deadline_at"],
                phase=context["phase"], turn_number=context["turn_number"], turn_player_id=context["current_player_id"],
                actor_id=context["current_actor_id"], proposal_count=context["proposal_count"],
                entry_pre_context_identity=prior_context["context_identity"], entry_pre_phase=prior_context["phase"],
                entry_pre_actor_id=prior_context["current_actor_id"])
            for item in w["steps"]:
                live = item["decision"]["liveness"]
                replay.exact_equal_v3(live["before"], progress.to_dict(), "rederived window entry/public history")
                progress = contract.advance_public_ordinal_progress_v1(progress,
                    chosen_ordinal=item["decision"]["binding"]["production_action_ref"]["executed_public_ordinal"],
                    post_step_count=item["decision"]["binding"]["post_step_count"], **live["post_public_boundary"])
                replay.exact_equal_v3(live["after"], progress.to_dict(), "rederived induction after")
        previous = w
    replay.ordered_production_sequence_v1([s["decision"] for s in steps])
    private_validator = _validate_test_only_private_record if expected_test_only else _validate_private_record
    private = private_validator(d["private_production_record"], full_game=full_game,
                                seed=d["seed"], max_steps=steps_limit)
    replay.exact_equal_v3(len(private["decisions"]), len(steps), "inner outer action count")
    for i, inner in enumerate(private["decisions"]):
        b = steps[i]["decision"]["binding"]
        for key in ("pre_revision", "post_revision", "pre_step_count", "post_step_count"):
            replay.exact_equal_v3(b[key], private["counters"][i][key], "inner outer actual counter")
        for key, inner_key in (("pre_execution_identity", "execution_before_sha256"), ("post_execution_identity", "execution_after_sha256"),
                               ("pre_state_identity", "state_before_sha256"), ("post_state_identity", "state_after_sha256"),
                               ("event_start", "event_start"), ("event_end", "event_end"), ("rng_start", "rng_start"), ("rng_end", "rng_end")):
            replay.exact_equal_v3(b[key], inner[inner_key], "inner outer exact material "+key)
        replay.exact_equal_v3(b["inner_decision_identity"], _identity(inner), "inner decision commitment")
        a = b["production_action_ref"]
        replay.exact_equal_v3(a["signed_action_id_commitment"], _action_commitment(inner["chosen_action_id"]), "inner outer signed action")
        replay.exact_equal_v3(a["ordered_legal_action_commitment"], inner["legal_action_set_sha256"], "inner outer full ordered legal tuple")
        ordinal = a["executed_public_ordinal"]
        if ordinal >= len(inner["legal_actions"]):
            raise C8G2RunnerError("inner executed ordinal越界")
        replay.exact_equal_v3(inner["legal_actions"][ordinal], inner["chosen_action"], "inner ordinal/action equality")
    if len(replay._exact_list(d["private_timed_transcript"], "private timed transcript")) != len(steps):
        raise C8G2RunnerError("private timed transcript count mismatch")
    replay.exact_equal_v3(d["initial_state"]["production_step_count"], 0, "canonical origin step0")
    replay.exact_equal_v3(d["final_state"]["production_step_count"], len(steps), "final step count")
    replay.exact_equal_v3(d["final_state"]["production_finished"], full_game, "natural terminal scope")
    if d["final_state"]["window_depth"] != 0 or d["final_security_audit"]["guard_active"] is not False:
        raise C8G2RunnerError("terminal/bounded stop存在pending window/guard")
    replay.exact_equal_v3(d["public_projection"], public_projection_v3(d), "public explicit allowlist")
    replay.exact_equal_v3(d["artifact_identity"], _identity({k:v for k,v in d.items() if k != "artifact_identity"}), "G2 artifact hash")
    return d


def timed_artifact_from_dict_v3(value: object, *, full_game: bool,
                                repo_root: Path | str | None = None) -> dict[str, object]:
    """Formal-only parser; test-only artifacts are rejected before worker use."""
    return _timed_artifact_from_dict_common(
        value, full_game=full_game, expected_test_only=False, repo_root=repo_root
    )


def test_only_timed_artifact_from_dict_v1(value: object, *, repo_root: Path | str | None = None) -> dict[str, object]:
    """Explicit detached parser for the isolated R2 test-only timed lane."""
    return _timed_artifact_from_dict_common(
        value, full_game=False, expected_test_only=True, repo_root=repo_root
    )


def bounded_smoke_from_dict_v1(value: object, *, repo_root: Path | str | None = None) -> dict[str, object]:
    return timed_artifact_from_dict_v3(value, full_game=False, repo_root=repo_root)


def _atomic_json(path: Path, value: object) -> None:
    data = _canonical_bytes(value)+b"\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix+".tmp")
    with temporary.open("wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    for attempt in range(2):
        try:
            os.replace(temporary, path)
            break
        except PermissionError:
            if attempt == 1:
                raise
    if path.read_bytes() != data:
        raise C8G2RunnerError("checkpoint atomic write回读不一致")


def run_bounded_runner_v1(*, repo_root: Path | str, output_dir: Path | str, resume: bool = False,
                          max_steps: int = 8, max_windows: int = 8, run_label: str = "bounded-smoke",
                          bundle_factory: Callable[..., CanonicalSessionBundleV1] | None = None,
                          test_only: bool = False) -> dict[str, object]:
    root, output = Path(repo_root).resolve(), Path(output_dir).resolve()
    if output == root or root in output.parents:
        raise C8G2RunnerError("所有artifact/temp/cache必须在repo外")
    state_path = output/"state.json"
    if resume:
        state = replay._strict_json(state_path.read_bytes())
        replay.exact_equal_v3(state.get("schema"), C8_G2_PROGRESS_SCHEMA, "resume current schema")
        if state.get("status") == "FAILED_INCOMPLETE_AFTER_COMMITTED_STEP":
            committed_step_failure_from_dict_v2(replay._strict_json((output/"failure.json").read_bytes()))
            raise C8G2RunnerError("committed-step incomplete仅diagnostic，禁止resume重执行已提交步")
        replay._object(state, "schema status artifact_sha256 artifact_identity last_accepted_step last_durable_diagnostic_step last_authoritative_replay_step resume_capability", "bounded state")
        replay.exact_equal_v3(state["status"], "BOUNDED_STOP", "resume status")
        raw = (output/"bounded_smoke.json").read_bytes()
        replay.exact_equal_v3(_file_sha256(output/"bounded_smoke.json"), state["artifact_sha256"], "resume artifact bytes")
        value = bounded_smoke_from_dict_v1(replay._strict_json(raw), repo_root=root)
        replay.exact_equal_v3(value["artifact_identity"], state["artifact_identity"], "resume artifact identity")
        replay.exact_equal_v3(state["last_accepted_step"], value["completed_production_steps"], "saved accepted step")
        replay.exact_equal_v3(state["last_authoritative_replay_step"], None, "no authoritative resume package")
        replay.exact_equal_v3(state["resume_capability"], "NONE", "no live resume")
        return {"status": "REUSED_EXISTING_ARTIFACT_NO_GAMEPLAY", "artifact": value}
    if state_path.exists() or (output/"bounded_smoke.json").exists():
        raise C8G2RunnerError("已有checkpoint必须显式resume，禁止覆盖/re-execute")
    sink = ReportOnlyDiagnosticSinkV1(output/"diagnostics")
    try:
        value = execute_bounded_smoke_v1(repo_root=root, max_steps=max_steps, max_windows=max_windows,
                                       run_label=run_label, bundle_factory=bundle_factory, test_only=test_only,
                                       diagnostic_sink=sink)
    except C8G2CommittedStepIncomplete as exc:
        _atomic_json(output/"failure.json", exc.failure_artifact)
        _atomic_json(state_path, {"schema": C8_G2_PROGRESS_SCHEMA, "status": "FAILED_INCOMPLETE_AFTER_COMMITTED_STEP",
            **{k:exc.failure_artifact[k] for k in ("last_accepted_step", "last_durable_diagnostic_step", "last_authoritative_replay_step", "resume_capability")}})
        raise
    try:
        _atomic_json(output/"bounded_smoke.json", value)
        _atomic_json(state_path, {"schema": C8_G2_PROGRESS_SCHEMA, "status": "BOUNDED_STOP",
                     "artifact_sha256": _file_sha256(output/"bounded_smoke.json"), "artifact_identity": value["artifact_identity"],
                     "last_accepted_step": value["completed_production_steps"], "last_durable_diagnostic_step": sink.last_durable,
                     "last_authoritative_replay_step": None, "resume_capability": "NONE"})
    except BaseException:
        sink.finish(status="ARTIFACT_IO_FAILURE", last_accepted_step=value["completed_production_steps"],
                    last_fully_evidenced_step=value["completed_production_steps"], completed_window_count=value["completed_windows"])
        raise
    return {"status": "BOUNDED_STOP", "artifact": value}


def run_candidate_or_formal_v1(*, artifact: object, mode: RunnerModeV1 = RunnerModeV1.CANDIDATE) -> contract.FullGameResultV1:
    """Fixed production verifier only; caller-supplied factories/verifiers are not authority."""
    if type(mode) is not RunnerModeV1 or mode is RunnerModeV1.BOUNDED_SMOKE:
        raise C8G2NotReady("formal entry必须使用candidate/formal mode")
    from .c8_timed_8p_full_game_production_replay_v1 import verify_full_game_composition_v1
    return verify_full_game_composition_v1(artifact)
