# -*- coding: utf-8 -*-
"""Skill Replay and Verification envelope.

Binds skill profile identities, registry identity, step-by-step state hashes,
usage transitions, materials, and event slices for strict fresh reexecution.
Rejects tampered payloads, altered states, or diverged events.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import math
import re
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from .actions import ActionContext, ActionType, LegalAction, UnsupportedRuleError
from .engine import canonical_state_snapshot
from .events import EventType, GameEvent
from .model import GameState
from .replay import canonical_json, sha256_value
from .skill_registry import AuthoritativeSkillRegistry
from .skill_runtime import AuthoritativeSkillRuntime


SKILL_REPLAY_SCHEMA_V1 = "sgs-authoritative-skill-replay-v1"


class SkillReplayDivergenceError(ValueError):
    """Raised when reexecution diverges from the recorded replay envelope."""


@dataclass(frozen=True, slots=True, kw_only=True)
class SkillActionReplayRecord:
    """Audit record for a single authoritative skill action step."""

    step_index: int
    skill_id: str
    skill_version: str
    actor_id: str
    action_type: str
    payload: Mapping[str, Any] = field(default_factory=dict)
    card_instance_id: str | None = None
    target_ids: tuple[str, ...] = ()
    state_hash_before: str
    state_hash_after: str
    usage_before: Mapping[str, int]
    usage_after: Mapping[str, int]
    events: tuple[Mapping[str, Any], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_type": self.action_type,
            "actor_id": self.actor_id,
            "card_instance_id": self.card_instance_id,
            "events": [dict(e) for e in self.events],
            "payload": dict(self.payload),
            "skill_id": self.skill_id,
            "skill_version": self.skill_version,
            "state_hash_after": self.state_hash_after,
            "state_hash_before": self.state_hash_before,
            "step_index": self.step_index,
            "target_ids": list(self.target_ids),
            "usage_after": dict(self.usage_after),
            "usage_before": dict(self.usage_before),
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class SkillReplayEnvelope:
    """Envelope binding complete skill execution evidence."""

    schema: str = SKILL_REPLAY_SCHEMA_V1
    registry_identity: str
    skill_profile_identities: Mapping[str, str]
    records: tuple[SkillActionReplayRecord, ...]
    initial_state_hash: str
    final_state_hash: str
    execution_identity: str = field(default="")

    def __post_init__(self) -> None:
        if self.schema != SKILL_REPLAY_SCHEMA_V1:
            raise ValueError(f"不受支持的技能回放 schema: {self.schema}")
        if not self.execution_identity:
            canonical_repr = json.dumps(
                {
                    "final_state_hash": self.final_state_hash,
                    "initial_state_hash": self.initial_state_hash,
                    "records": [r.to_dict() for r in self.records],
                    "registry_identity": self.registry_identity,
                    "schema": self.schema,
                    "skill_profile_identities": dict(sorted(self.skill_profile_identities.items())),
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            object.__setattr__(
                self, "execution_identity", hashlib.sha256(canonical_repr.encode("utf-8")).hexdigest()
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "execution_identity": self.execution_identity,
            "final_state_hash": self.final_state_hash,
            "initial_state_hash": self.initial_state_hash,
            "records": [r.to_dict() for r in self.records],
            "registry_identity": self.registry_identity,
            "schema": self.schema,
            "skill_profile_identities": dict(sorted(self.skill_profile_identities.items())),
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class SkillReplayVerificationResult:
    """Result of fresh reexecution verification."""

    verified: bool
    steps_verified: int
    registry_identity_matched: bool
    state_hashes_matched: bool
    details: str


def compute_state_hash(state: GameState) -> str:
    """Compute deterministic SHA-256 hash of canonical GameState representation."""
    snapshot = canonical_state_snapshot(state)
    return sha256_value(snapshot)


def reexecute_component_skill_replay(
    envelope: SkillReplayEnvelope,
    initial_state: GameState,
    initial_runtime: AuthoritativeSkillRuntime,
) -> SkillReplayVerificationResult:
    """COMPONENT-ONLY runtime reexecution. Not production authority."""
    # 1. Verify registry identity
    actual_registry_identity = initial_runtime.registry.registry_identity
    if envelope.registry_identity != actual_registry_identity:
        raise SkillReplayDivergenceError(
            f"注册表身份不匹配：预期 {envelope.registry_identity}，实际 {actual_registry_identity}"
        )

    # 2. Verify initial state hash
    actual_initial_hash = compute_state_hash(initial_state)
    if envelope.initial_state_hash != actual_initial_hash:
        raise SkillReplayDivergenceError(
            f"初始状态哈希不匹配：预期 {envelope.initial_state_hash}，实际 {actual_initial_hash}"
        )

    current_state = initial_state
    current_runtime = initial_runtime
    steps_verified = 0

    for record in envelope.records:
        # Check pre-state hash
        expected_pre_hash = record.state_hash_before
        actual_pre_hash = compute_state_hash(current_state)
        if expected_pre_hash != actual_pre_hash:
            raise SkillReplayDivergenceError(
                f"第 {record.step_index} 步前置状态哈希不匹配：预期 {expected_pre_hash}，实际 {actual_pre_hash}"
            )

        # Check skill ownership and pre-usage
        skill_state = current_runtime.get_skill_state(record.actor_id, record.skill_id)
        if skill_state.uses_this_phase != record.usage_before.get("uses_this_phase", 0):
            raise SkillReplayDivergenceError(f"第 {record.step_index} 步 uses_this_phase 前置计数不匹配")
        if skill_state.uses_this_turn != record.usage_before.get("uses_this_turn", 0):
            raise SkillReplayDivergenceError(f"第 {record.step_index} 步 uses_this_turn 前置计数不匹配")

        # Construct LegalAction
        action = LegalAction(
            action_type=ActionType(record.action_type),
            actor_id=record.actor_id,
            card_instance_id=record.card_instance_id,
            target_ids=record.target_ids,
            skill_id=record.skill_id,
            payload=record.payload,
        )

        context = ActionContext(
            mode="authoritative_skill_mode_v1",
            phase="play",
            actor_id=record.actor_id,
        )

        # Execute
        new_state, new_runtime, events = current_runtime.apply_skill_action(action, context, current_state)

        # Verify post-state hash
        actual_post_hash = compute_state_hash(new_state)
        if record.state_hash_after != actual_post_hash:
            raise SkillReplayDivergenceError(
                f"第 {record.step_index} 步后置状态哈希不匹配：预期 {record.state_hash_after}，实际 {actual_post_hash}"
            )

        # Verify post-usage
        new_skill_state = new_runtime.get_skill_state(record.actor_id, record.skill_id)
        if new_skill_state.uses_this_phase != record.usage_after.get("uses_this_phase", 0):
            raise SkillReplayDivergenceError(f"第 {record.step_index} 步 uses_this_phase 后置计数不匹配")
        if new_skill_state.uses_this_turn != record.usage_after.get("uses_this_turn", 0):
            raise SkillReplayDivergenceError(f"第 {record.step_index} 步 uses_this_turn 后置计数不匹配")

        # Verify event count and event types
        if len(events) != len(record.events):
            raise SkillReplayDivergenceError(
                f"第 {record.step_index} 步生成事件数量不匹配：预期 {len(record.events)}，实际 {len(events)}"
            )

        current_state = new_state
        current_runtime = new_runtime
        steps_verified += 1

    # Verify final state hash
    actual_final_hash = compute_state_hash(current_state)
    if envelope.final_state_hash != actual_final_hash:
        raise SkillReplayDivergenceError(
            f"终态哈希不匹配：预期 {envelope.final_state_hash}，实际 {actual_final_hash}"
        )

    return SkillReplayVerificationResult(
        verified=True,
        steps_verified=steps_verified,
        registry_identity_matched=True,
        state_hashes_matched=True,
        details=f"组件 runtime 重放通过，共验证 {steps_verified} 步",
    )


def reexecute_skill_replay(*args: object, **kwargs: object) -> SkillReplayVerificationResult:
    raise UnsupportedRuleError(
        "SkillRuntime.apply_skill_action 重放不是生产权威证明；"
        "必须使用 reexecute_skill_production_replay"
    )


SKILL_PRODUCTION_REPLAY_SCHEMA_V1 = "sgs-authoritative-skill-production-replay-v1"

_SKILL_PRODUCTION_REPLAY_FIELDS = frozenset(
    {
        "schema",
        "contract_identity",
        "implementation_identity",
        "seed",
        "session_id",
        "session_secret_hex",
        "registry_identity",
        "skill_profile_identities",
        "skill_assignments",
        "skill_id",
        "skill_version",
        "owner_id",
        "trigger_event_sequence",
        "trigger_event_type",
        "action_ids",
        "legal_set_hashes",
        "chosen_action_semantics",
        "usage_before",
        "usage_after",
        "marks_before",
        "marks_after",
        "event_slice",
        "state_hash_before",
        "state_hash_after",
        "rng_hash",
        "records_identity",
        "execution_identity",
    }
)
_ACTION_SEMANTICS_FIELDS = frozenset(
    {
        "action_type",
        "actor_id",
        "skill_id",
        "card_instance_id",
        "target_ids",
        "operation",
        "payload",
    }
)
_EVENT_BASE_FIELDS = frozenset(
    {
        "sequence",
        "event_type",
        "card_instance_id",
        "card_key",
        "material_card_instance_ids",
        "card_user",
        "damage_source",
        "skill_owner",
        "equipment_owner",
        "kill_credit",
        "target_ids",
        "payload",
    }
)
_EVENT_DAMAGE_FIELDS = frozenset({"target_id", "amount", "damage_type"})
_USAGE_FIELDS = frozenset({"uses_this_phase", "uses_this_turn"})
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_ACTION_ID_RE = re.compile(r"act_[0-9a-f]{64}\Z")

_SKILL_PRODUCTION_REPLAY_CONTRACT_DESCRIPTOR_V1: Mapping[str, object] = {
    "authentication_order": [
        "exact_schema",
        "contract_identity",
        "implementation_identity",
        "registry_identity",
        "skill_profile_identities",
        "skill_assignment_and_owner",
        "records_identity",
        "execution_identity",
        "fresh_session",
        "live_legal_actions",
        "step",
    ],
    "envelope_fields": sorted(_SKILL_PRODUCTION_REPLAY_FIELDS),
    "nested_action_fields": sorted(_ACTION_SEMANTICS_FIELDS),
    "nested_event_base_fields": sorted(_EVENT_BASE_FIELDS),
    "nested_event_damage_fields": sorted(_EVENT_DAMAGE_FIELDS),
    "schema": SKILL_PRODUCTION_REPLAY_SCHEMA_V1,
    "serialized_pass_flags_are_input": False,
    "strict_json_types": True,
}


def skill_production_replay_contract_identity() -> str:
    """Return the stable identity of the V1 production-skill replay contract."""

    return sha256_value(_SKILL_PRODUCTION_REPLAY_CONTRACT_DESCRIPTOR_V1)


SKILL_PRODUCTION_REPLAY_CONTRACT_IDENTITY_V1 = (
    skill_production_replay_contract_identity()
)


def _current_implementation_identity() -> str:
    # Local import avoids a package-initialization cycle. The identity helper
    # hashes the explicit production source inventory and does not construct a
    # game/session.
    from .formal_duel import implementation_identity

    return implementation_identity()


def _replay_format_error(path: str, detail: str) -> SkillReplayDivergenceError:
    return SkillReplayDivergenceError(f"生产技能回放字段 {path} {detail}")


def _exact_dict(value: object, path: str) -> dict[str, Any]:
    if type(value) is not dict:
        raise _replay_format_error(path, "必须是 JSON object")
    return value


def _exact_fields(value: dict[str, Any], expected: frozenset[str], path: str) -> None:
    actual = set(value)
    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    if missing or extra:
        raise _replay_format_error(
            path,
            f"字段集合不精确；missing={missing} extra={extra}",
        )


def _exact_string(value: object, path: str, *, allow_none: bool = False) -> str | None:
    if value is None and allow_none:
        return None
    if type(value) is not str or not value or value.strip() != value:
        raise _replay_format_error(path, "必须是无首尾空白的非空字符串")
    return value


def _exact_int(
    value: object,
    path: str,
    *,
    minimum: int | None = None,
    allow_none: bool = False,
) -> int | None:
    if value is None and allow_none:
        return None
    if type(value) is not int:
        raise _replay_format_error(path, "必须是 exact int；bool 不得代替 int")
    if minimum is not None and value < minimum:
        raise _replay_format_error(path, f"必须大于等于 {minimum}")
    return value


def _exact_sha256(value: object, path: str) -> str:
    text = _exact_string(value, path)
    assert isinstance(text, str)
    if _SHA256_RE.fullmatch(text) is None:
        raise _replay_format_error(path, "必须是小写 SHA-256 十六进制字符串")
    return text


def _exact_json_value(value: object, path: str) -> object:
    if value is None or type(value) in (str, bool, int):
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise _replay_format_error(path, "不得包含非有限浮点数")
        return value
    if type(value) is list:
        return [_exact_json_value(item, f"{path}[]") for item in value]
    if type(value) is dict:
        result: dict[str, object] = {}
        for key, item in value.items():
            if type(key) is not str or not key or key.strip() != key:
                raise _replay_format_error(path, "的嵌套 object 键必须是非空字符串")
            result[key] = _exact_json_value(item, f"{path}.{key}")
        return result
    raise _replay_format_error(path, f"包含不受支持的 JSON 类型 {type(value).__name__}")


def _exact_string_list(
    value: object,
    path: str,
    *,
    allow_empty: bool = True,
    unique: bool = True,
) -> tuple[str, ...]:
    if type(value) is not list:
        raise _replay_format_error(path, "必须是 JSON array")
    items = tuple(_exact_string(item, f"{path}[]") for item in value)
    if not allow_empty and not items:
        raise _replay_format_error(path, "不得为空")
    if unique and len(items) != len(set(items)):
        raise _replay_format_error(path, "不得包含重复 ID")
    return tuple(item for item in items if isinstance(item, str))


def _exact_usage(value: object, path: str) -> dict[str, int]:
    data = _exact_dict(value, path)
    _exact_fields(data, _USAGE_FIELDS, path)
    return {
        key: int(_exact_int(data[key], f"{path}.{key}", minimum=0))
        for key in sorted(_USAGE_FIELDS)
    }


def _exact_marks(value: object, path: str) -> dict[str, int]:
    data = _exact_dict(value, path)
    result: dict[str, int] = {}
    for key, item in data.items():
        clean = _exact_string(key, f"{path}.<key>")
        assert isinstance(clean, str)
        result[clean] = int(_exact_int(item, f"{path}.{clean}", minimum=0))
    return result


def _exact_profile_identities(value: object) -> dict[str, str]:
    data = _exact_dict(value, "skill_profile_identities")
    if not data:
        raise _replay_format_error("skill_profile_identities", "不得为空")
    result: dict[str, str] = {}
    for key, item in data.items():
        skill_id = _exact_string(key, "skill_profile_identities.<key>")
        assert isinstance(skill_id, str)
        result[skill_id] = _exact_sha256(
            item, f"skill_profile_identities.{skill_id}"
        )
    return result


def _exact_assignments(value: object) -> dict[str, tuple[str, ...]]:
    data = _exact_dict(value, "skill_assignments")
    if not data:
        raise _replay_format_error("skill_assignments", "不得为空")
    result: dict[str, tuple[str, ...]] = {}
    for key, item in data.items():
        owner_id = _exact_string(key, "skill_assignments.<owner_id>")
        assert isinstance(owner_id, str)
        result[owner_id] = _exact_string_list(
            item,
            f"skill_assignments.{owner_id}",
            allow_empty=False,
            unique=True,
        )
    return result


def _exact_action_semantics(value: object, index: int) -> dict[str, Any]:
    path = f"chosen_action_semantics[{index}]"
    data = _exact_dict(value, path)
    _exact_fields(data, _ACTION_SEMANTICS_FIELDS, path)
    action_type = _exact_string(data["action_type"], f"{path}.action_type")
    if action_type not in {member.value for member in ActionType}:
        raise _replay_format_error(f"{path}.action_type", "不是已知 ActionType")
    actor_id = _exact_string(data["actor_id"], f"{path}.actor_id")
    skill_id = _exact_string(data["skill_id"], f"{path}.skill_id", allow_none=True)
    card_instance_id = _exact_string(
        data["card_instance_id"], f"{path}.card_instance_id", allow_none=True
    )
    target_ids = _exact_string_list(data["target_ids"], f"{path}.target_ids")
    operation = _exact_string(data["operation"], f"{path}.operation", allow_none=True)
    payload = _exact_dict(data["payload"], f"{path}.payload")
    frozen_payload = _exact_json_value(payload, f"{path}.payload")
    assert isinstance(frozen_payload, dict)
    if frozen_payload.get("operation") != operation:
        raise _replay_format_error(path, "的 operation 与 payload.operation 不一致")
    return {
        "action_type": action_type,
        "actor_id": actor_id,
        "skill_id": skill_id,
        "card_instance_id": card_instance_id,
        "target_ids": list(target_ids),
        "operation": operation,
        "payload": frozen_payload,
    }


def _exact_event(value: object, index: int) -> dict[str, Any]:
    path = f"event_slice[{index}]"
    data = _exact_dict(value, path)
    event_type = _exact_string(data.get("event_type"), f"{path}.event_type")
    expected = (
        _EVENT_BASE_FIELDS | _EVENT_DAMAGE_FIELDS
        if event_type == EventType.DAMAGE.value
        else _EVENT_BASE_FIELDS
    )
    _exact_fields(data, expected, path)
    sequence = _exact_int(data["sequence"], f"{path}.sequence", minimum=1)
    if event_type not in {member.value for member in EventType}:
        raise _replay_format_error(f"{path}.event_type", "不是已知 EventType")
    result: dict[str, Any] = {
        "sequence": sequence,
        "event_type": event_type,
    }
    for key in (
        "card_instance_id",
        "card_key",
        "card_user",
        "damage_source",
        "skill_owner",
        "equipment_owner",
        "kill_credit",
    ):
        result[key] = _exact_string(data[key], f"{path}.{key}", allow_none=True)
    result["material_card_instance_ids"] = list(
        _exact_string_list(
            data["material_card_instance_ids"],
            f"{path}.material_card_instance_ids",
        )
    )
    result["target_ids"] = list(
        _exact_string_list(data["target_ids"], f"{path}.target_ids")
    )
    payload = _exact_dict(data["payload"], f"{path}.payload")
    frozen_payload = _exact_json_value(payload, f"{path}.payload")
    assert isinstance(frozen_payload, dict)
    result["payload"] = frozen_payload
    if event_type == EventType.DAMAGE.value:
        target_id = _exact_string(data["target_id"], f"{path}.target_id")
        if result["target_ids"] != [target_id]:
            raise _replay_format_error(path, "的 damage target_id 与 target_ids 不一致")
        result.update(
            {
                "target_id": target_id,
                "amount": _exact_int(data["amount"], f"{path}.amount", minimum=1),
                "damage_type": _exact_string(data["damage_type"], f"{path}.damage_type"),
            }
        )
    return result


def _json_frozen(value: object) -> object:
    return json.loads(canonical_json(value))


@dataclass(frozen=True, slots=True, kw_only=True)
class SkillProductionReplayEnvelope:
    """Production skill replay: cold payload for a skill-enabled ProductionBasicCardBatch."""

    schema: str = SKILL_PRODUCTION_REPLAY_SCHEMA_V1
    seed: int
    session_id: str
    session_secret_hex: str
    registry_identity: str
    skill_profile_identities: Mapping[str, str]
    skill_assignments: Mapping[str, tuple[str, ...]]
    skill_id: str
    skill_version: str
    owner_id: str
    trigger_event_sequence: int | None
    trigger_event_type: str | None
    action_ids: tuple[str, ...]
    legal_set_hashes: tuple[str, ...]
    chosen_action_semantics: tuple[Mapping[str, Any], ...]
    usage_before: Mapping[str, int]
    usage_after: Mapping[str, int]
    marks_before: Mapping[str, int]
    marks_after: Mapping[str, int]
    event_slice: tuple[Mapping[str, Any], ...]
    state_hash_before: str
    state_hash_after: str
    rng_hash: str
    contract_identity: str = SKILL_PRODUCTION_REPLAY_CONTRACT_IDENTITY_V1
    implementation_identity: str = field(default_factory=_current_implementation_identity)
    records_identity: str = ""
    execution_identity: str = ""

    def __post_init__(self) -> None:
        if self.schema != SKILL_PRODUCTION_REPLAY_SCHEMA_V1:
            raise ValueError(f"不受支持的生产技能回放 schema: {self.schema}")
        object.__setattr__(
            self,
            "skill_profile_identities",
            MappingProxyType(dict(self.skill_profile_identities)),
        )
        object.__setattr__(
            self,
            "skill_assignments",
            MappingProxyType({k: tuple(v) for k, v in self.skill_assignments.items()}),
        )
        object.__setattr__(self, "usage_before", MappingProxyType(dict(self.usage_before)))
        object.__setattr__(self, "usage_after", MappingProxyType(dict(self.usage_after)))
        object.__setattr__(self, "marks_before", MappingProxyType(dict(self.marks_before)))
        object.__setattr__(self, "marks_after", MappingProxyType(dict(self.marks_after)))
        if not self.records_identity:
            object.__setattr__(self, "records_identity", self._compute_records_identity())
        if not self.execution_identity:
            object.__setattr__(self, "execution_identity", self._compute_execution_identity())

    def _compute_records_identity(self) -> str:
        return sha256_value(
            {
                "action_ids": list(self.action_ids),
                "chosen_action_semantics": [
                    _json_frozen(item) for item in self.chosen_action_semantics
                ],
                "event_slice": [_json_frozen(item) for item in self.event_slice],
                "legal_set_hashes": list(self.legal_set_hashes),
                "marks_after": dict(self.marks_after),
                "marks_before": dict(self.marks_before),
                "owner_id": self.owner_id,
                "rng_hash": self.rng_hash,
                "skill_id": self.skill_id,
                "skill_version": self.skill_version,
                "state_hash_after": self.state_hash_after,
                "state_hash_before": self.state_hash_before,
                "trigger_event_sequence": self.trigger_event_sequence,
                "trigger_event_type": self.trigger_event_type,
                "usage_after": dict(self.usage_after),
                "usage_before": dict(self.usage_before),
            }
        )

    def _compute_execution_identity(self) -> str:
        payload = self.to_dict()
        payload.pop("execution_identity", None)
        return hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "contract_identity": self.contract_identity,
            "implementation_identity": self.implementation_identity,
            "seed": self.seed,
            "session_id": self.session_id,
            "session_secret_hex": self.session_secret_hex,
            "registry_identity": self.registry_identity,
            "skill_profile_identities": dict(sorted(self.skill_profile_identities.items())),
            "skill_assignments": {k: list(v) for k, v in sorted(self.skill_assignments.items())},
            "skill_id": self.skill_id,
            "skill_version": self.skill_version,
            "owner_id": self.owner_id,
            "trigger_event_sequence": self.trigger_event_sequence,
            "trigger_event_type": self.trigger_event_type,
            "action_ids": list(self.action_ids),
            "legal_set_hashes": list(self.legal_set_hashes),
            "chosen_action_semantics": [_json_frozen(item) for item in self.chosen_action_semantics],
            "usage_before": dict(self.usage_before),
            "usage_after": dict(self.usage_after),
            "marks_before": dict(self.marks_before),
            "marks_after": dict(self.marks_after),
            "event_slice": [_json_frozen(item) for item in self.event_slice],
            "state_hash_before": self.state_hash_before,
            "state_hash_after": self.state_hash_after,
            "rng_hash": self.rng_hash,
            "records_identity": self.records_identity,
            "execution_identity": self.execution_identity,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "SkillProductionReplayEnvelope":
        data = _exact_dict(payload, "<root>")
        _exact_fields(data, _SKILL_PRODUCTION_REPLAY_FIELDS, "<root>")
        schema = _exact_string(data["schema"], "schema")
        if schema != SKILL_PRODUCTION_REPLAY_SCHEMA_V1:
            raise SkillReplayDivergenceError(f"不受支持的生产技能回放 schema: {schema}")
        contract_identity = _exact_sha256(data["contract_identity"], "contract_identity")
        implementation_identity = _exact_sha256(
            data["implementation_identity"], "implementation_identity"
        )
        seed = _exact_int(data["seed"], "seed")
        session_id = _exact_string(data["session_id"], "session_id")
        session_secret_hex = _exact_string(
            data["session_secret_hex"], "session_secret_hex"
        )
        assert isinstance(session_secret_hex, str)
        if len(session_secret_hex) != 64 or _SHA256_RE.fullmatch(session_secret_hex) is None:
            raise _replay_format_error(
                "session_secret_hex", "必须是精确 32 字节的小写十六进制字符串"
            )
        registry_identity = _exact_sha256(data["registry_identity"], "registry_identity")
        profiles = _exact_profile_identities(data["skill_profile_identities"])
        assignments = _exact_assignments(data["skill_assignments"])
        skill_id = _exact_string(data["skill_id"], "skill_id")
        skill_version = _exact_string(data["skill_version"], "skill_version")
        owner_id = _exact_string(data["owner_id"], "owner_id")
        trigger_event_sequence = _exact_int(
            data["trigger_event_sequence"],
            "trigger_event_sequence",
            minimum=1,
            allow_none=True,
        )
        trigger_event_type = _exact_string(
            data["trigger_event_type"], "trigger_event_type", allow_none=True
        )
        if (trigger_event_sequence is None) != (trigger_event_type is None):
            raise _replay_format_error(
                "触发事件 trigger_event_sequence/trigger_event_type",
                "必须同时为空或同时存在",
            )
        if trigger_event_type is not None and trigger_event_type not in {
            member.value for member in EventType
        }:
            raise _replay_format_error("trigger_event_type", "不是已知 EventType")
        action_ids = _exact_string_list(
            data["action_ids"], "action_ids", allow_empty=False, unique=True
        )
        for index, action_id in enumerate(action_ids):
            if _ACTION_ID_RE.fullmatch(action_id) is None:
                raise _replay_format_error(
                    f"action_ids[{index}]",
                    "必须是 act_ 加 256-bit SHA-256 represented as 64 lowercase hexadecimal characters",
                )
        legal_set_hashes = _exact_string_list(
            data["legal_set_hashes"], "legal_set_hashes", allow_empty=False
        )
        for index, item in enumerate(legal_set_hashes):
            _exact_sha256(item, f"legal_set_hashes[{index}]")
        raw_semantics = data["chosen_action_semantics"]
        if type(raw_semantics) is not list:
            raise _replay_format_error("chosen_action_semantics", "必须是 JSON array")
        semantics = tuple(
            _exact_action_semantics(item, index)
            for index, item in enumerate(raw_semantics)
        )
        if not (
            len(action_ids) == len(legal_set_hashes) == len(semantics)
        ):
            raise _replay_format_error(
                "action_ids/legal_set_hashes/chosen_action_semantics",
                "长度必须完全一致",
            )
        raw_events = data["event_slice"]
        if type(raw_events) is not list:
            raise _replay_format_error("event_slice", "必须是 JSON array")
        events = tuple(_exact_event(item, index) for index, item in enumerate(raw_events))
        sequences = tuple(event["sequence"] for event in events)
        if len(sequences) != len(set(sequences)) or sequences != tuple(sorted(sequences)):
            raise _replay_format_error("event_slice.sequence", "必须严格递增且不得重复")
        loaded = cls(
            schema=schema,
            contract_identity=contract_identity,
            implementation_identity=implementation_identity,
            seed=int(seed),
            session_id=session_id,
            session_secret_hex=session_secret_hex,
            registry_identity=registry_identity,
            skill_profile_identities=profiles,
            skill_assignments=assignments,
            skill_id=skill_id,
            skill_version=skill_version,
            owner_id=owner_id,
            trigger_event_sequence=trigger_event_sequence,
            trigger_event_type=trigger_event_type,
            action_ids=action_ids,
            legal_set_hashes=legal_set_hashes,
            chosen_action_semantics=semantics,
            usage_before=_exact_usage(data["usage_before"], "usage_before"),
            usage_after=_exact_usage(data["usage_after"], "usage_after"),
            marks_before=_exact_marks(data["marks_before"], "marks_before"),
            marks_after=_exact_marks(data["marks_after"], "marks_after"),
            event_slice=events,
            state_hash_before=_exact_sha256(data["state_hash_before"], "state_hash_before"),
            state_hash_after=_exact_sha256(data["state_hash_after"], "state_hash_after"),
            rng_hash=_exact_sha256(data["rng_hash"], "rng_hash"),
            records_identity=_exact_sha256(data["records_identity"], "records_identity"),
            execution_identity=_exact_sha256(data["execution_identity"], "execution_identity"),
        )
        loaded._authenticate_static_fields()
        return loaded

    def _authenticate_static_fields(self) -> None:
        if self.schema != SKILL_PRODUCTION_REPLAY_SCHEMA_V1:
            raise SkillReplayDivergenceError("生产技能回放 schema 不匹配")
        if self.contract_identity != SKILL_PRODUCTION_REPLAY_CONTRACT_IDENTITY_V1:
            raise SkillReplayDivergenceError("contract_identity 与当前生产回放合同不匹配")
        current_implementation = _current_implementation_identity()
        if self.implementation_identity != current_implementation:
            raise SkillReplayDivergenceError(
                "implementation_identity 与当前生产实现不匹配"
            )
        if self.records_identity != self._compute_records_identity():
            raise SkillReplayDivergenceError("records_identity 与内层回放记录不一致")
        if self.execution_identity != self._compute_execution_identity():
            raise SkillReplayDivergenceError("execution_identity 与信封内容不一致")


def rng_calls_hash(calls: Sequence[object]) -> str:
    rows = []
    for call in calls:
        rows.append(
            {
                "index": getattr(call, "index", None),
                "method": getattr(call, "method", None),
                "arguments": _json_frozen(dict(getattr(call, "arguments", {}) or {})),
                "result": _json_frozen(getattr(call, "result", None)),
            }
        )
    return sha256_value(rows)


def legal_actions_semantic_hash(actions: Sequence[LegalAction]) -> str:
    rows = [
        {
            "action_type": action.action_type.value,
            "actor_id": action.actor_id,
            "skill_id": action.skill_id,
            "card_instance_id": action.card_instance_id,
            "target_ids": list(action.target_ids),
            "operation": action.payload.get("operation"),
            "payload": _json_frozen(dict(action.payload)),
        }
        for action in actions
    ]
    return sha256_value(rows)


def action_semantics(action: LegalAction) -> dict[str, Any]:
    return {
        "action_type": action.action_type.value,
        "actor_id": action.actor_id,
        "skill_id": action.skill_id,
        "card_instance_id": action.card_instance_id,
        "target_ids": list(action.target_ids),
        "operation": action.payload.get("operation"),
        "payload": _json_frozen(dict(action.payload)),
    }


def _construct_skill_production_replay_session(
    envelope: SkillProductionReplayEnvelope,
    registry: AuthoritativeSkillRegistry,
) -> object:
    """Single constructor wrapper reached only after replay preflight succeeds."""

    from .production_batch import ProductionBasicCardBatch

    return ProductionBasicCardBatch(
        seed=envelope.seed,
        session_id=envelope.session_id,
        session_secret=bytes.fromhex(envelope.session_secret_hex),
        skill_registry=registry,
        skill_assignments=envelope.skill_assignments,
    )


def reexecute_skill_production_replay(
    envelope: SkillProductionReplayEnvelope,
    registry: AuthoritativeSkillRegistry,
) -> SkillReplayVerificationResult:
    if type(envelope) is not SkillProductionReplayEnvelope:
        raise SkillReplayDivergenceError(
            "生产技能回放必须是 exact SkillProductionReplayEnvelope"
        )
    # Re-parse the public JSON representation so direct dataclass construction
    # cannot bypass exact cold-load validation. This performs schema,
    # contract/implementation, inner-record and outer-envelope authentication
    # before any production constructor is imported or called.
    envelope = SkillProductionReplayEnvelope.from_dict(envelope.to_dict())
    if type(registry) is not AuthoritativeSkillRegistry:
        raise SkillReplayDivergenceError(
            "技能注册表必须是 exact AuthoritativeSkillRegistry"
        )
    if not registry.is_frozen:
        raise SkillReplayDivergenceError("技能注册表必须已冻结")
    if registry.registry_identity != envelope.registry_identity:
        raise SkillReplayDivergenceError("注册表身份不匹配")
    if set(envelope.skill_profile_identities) != set(registry.skill_ids):
        raise SkillReplayDivergenceError(
            "技能 profile identity 集合与注册表技能集合不匹配"
        )
    for skill_id, profile in envelope.skill_profile_identities.items():
        try:
            actual = registry.get_skill(skill_id).profile_identity
        except UnsupportedRuleError as exc:
            raise SkillReplayDivergenceError(str(exc)) from exc
        if actual != profile:
            raise SkillReplayDivergenceError(f"技能 {skill_id} profile identity 不匹配")
    known_players = frozenset({"p1", "p2"})
    if not set(envelope.skill_assignments).issubset(known_players):
        raise SkillReplayDivergenceError("技能归属包含生产回放会话之外的 owner_id")
    for owner_id, assigned_skill_ids in envelope.skill_assignments.items():
        if not assigned_skill_ids:
            raise SkillReplayDivergenceError(f"角色 {owner_id} 的技能归属不得为空")
        unknown = set(assigned_skill_ids) - set(envelope.skill_profile_identities)
        if unknown:
            raise SkillReplayDivergenceError(
                f"角色 {owner_id} 的技能归属包含未知 skill_id: {sorted(unknown)}"
            )
    if envelope.skill_id not in envelope.skill_profile_identities:
        raise SkillReplayDivergenceError("信封 skill_id 不在 profile 集合中")
    if envelope.owner_id not in known_players:
        raise SkillReplayDivergenceError("owner_id 不属于生产回放会话")
    if envelope.skill_id not in envelope.skill_assignments.get(envelope.owner_id, ()):
        raise SkillReplayDivergenceError("owner_id 未拥有信封声明的 skill_id")
    try:
        definition = registry.get_skill(envelope.skill_id)
    except UnsupportedRuleError as exc:
        raise SkillReplayDivergenceError(str(exc)) from exc
    if definition.version != envelope.skill_version:
        raise SkillReplayDivergenceError("技能版本不匹配")
    from .production_batch import BatchActionIdController

    game = _construct_skill_production_replay_session(envelope, registry)
    steps_verified = 0
    for index, action_id in enumerate(envelope.action_ids):
        legal = game.legal_actions()
        legal_hash = legal_actions_semantic_hash(legal)
        if legal_hash != envelope.legal_set_hashes[index]:
            raise SkillReplayDivergenceError(f"第 {index} 步合法动作语义集合不匹配")
        chosen = next((item for item in legal if item.action_id == action_id), None)
        if chosen is None:
            raise SkillReplayDivergenceError(f"第 {index} 步 chosen action_id 不在 live legal_actions 中")
        expected_semantics = envelope.chosen_action_semantics[index]
        actual_semantics = action_semantics(chosen)
        if actual_semantics != expected_semantics:
            raise SkillReplayDivergenceError(f"第 {index} 步 chosen action 语义不匹配")
        if chosen.skill_id == envelope.skill_id:
            if compute_state_hash(game.state) != envelope.state_hash_before:
                raise SkillReplayDivergenceError("技能步前置状态哈希不匹配")
            if game.skill_runtime is None:
                raise SkillReplayDivergenceError("技能步缺少 SkillRuntime")
            try:
                skill_state = game.skill_runtime.get_skill_state(
                    envelope.owner_id, envelope.skill_id
                )
            except UnsupportedRuleError as exc:
                raise SkillReplayDivergenceError(str(exc)) from exc
            if skill_state.uses_this_phase != envelope.usage_before.get(
                "uses_this_phase", 0
            ):
                raise SkillReplayDivergenceError("uses_this_phase 前置计数不匹配")
            if dict(skill_state.marks) != dict(envelope.marks_before):
                raise SkillReplayDivergenceError("marks 前置不匹配")
        game.step(BatchActionIdController(action_id))
        steps_verified += 1
    if compute_state_hash(game.state) != envelope.state_hash_after:
        raise SkillReplayDivergenceError("终态哈希不匹配")
    if game.skill_runtime is None:
        raise SkillReplayDivergenceError("重放会话未装载 SkillRuntime")
    try:
        skill_state = game.skill_runtime.get_skill_state(
            envelope.owner_id, envelope.skill_id
        )
    except UnsupportedRuleError as exc:
        raise SkillReplayDivergenceError(str(exc)) from exc
    if skill_state.uses_this_phase != envelope.usage_after.get("uses_this_phase", 0):
        raise SkillReplayDivergenceError("uses_this_phase 后置计数不匹配")
    if dict(skill_state.marks) != dict(envelope.marks_after):
        raise SkillReplayDivergenceError("marks 后置不匹配")
    actual_events = tuple(event.to_replay_dict() for event in game.events)
    if actual_events != envelope.event_slice:
        raise SkillReplayDivergenceError("事件内容或序号切片不匹配")
    if rng_calls_hash(game.rng_calls) != envelope.rng_hash:
        raise SkillReplayDivergenceError("RNG 回放不一致")
    if envelope.trigger_event_sequence is not None or envelope.trigger_event_type is not None:
        if envelope.trigger_event_sequence is None or envelope.trigger_event_type is None:
            raise SkillReplayDivergenceError("触发事件序号与类型必须成对")
        match = next(
            (
                event
                for event in game.events
                if event.sequence == envelope.trigger_event_sequence
            ),
            None,
        )
        if match is None or match.event_type.value != envelope.trigger_event_type:
            raise SkillReplayDivergenceError("触发事件序号或类型不匹配")
    return SkillReplayVerificationResult(
        verified=True,
        steps_verified=steps_verified,
        registry_identity_matched=True,
        state_hashes_matched=True,
        details=f"生产技能回放验证通过，共 {steps_verified} 步",
    )


GENERAL_PRODUCTION_REPLAY_SCHEMA_V1 = "sgs-authoritative-general-production-replay-v1"
GENERAL_PRODUCTION_REPLAY_CONTRACT_VERSION_LEGACY = (
    "general-production-replay.v1.legacy"
)
GENERAL_PRODUCTION_REPLAY_CONTRACT_VERSION_G3_AUTHORITY_V2 = (
    "general-production-replay.v2.g3-authority-required"
)
GENERAL_PRODUCTION_REPLAY_G3_REQUIRED_AUTHORITY_CAPABILITIES = (
    "production_authority_trace_per_step",
    "production_authority_after",
    "dynamic_skill_runtime",
    "pending_skill_decision_queue",
    "card_continuation_semantic_kind",
    "qianchong_phase_permission",
    "turn_loss_ledger",
    "card_movement_authority",
    "end_phase_dispatch_state",
)

_G3_AUTHORITY_SNAPSHOT_REQUIRED_FIELDS = frozenset(
    {
        "runtime",
        "pending_skill_decision",
        "pending_skill_decision_queue",
        "pending_card_continuation",
        "consumed_triggers",
        "consumed_card_continuations",
        "continuation_in_progress_id",
        "pending_private_card_selection",
        "pending_skill_hp_loss",
        "consumed_skill_continuations",
        "qianchong_phase_permission",
        "turn_loss_ledger",
        "card_movement_authority",
        "end_phase_dispatch_state",
        "target_effect_ineffective",
    }
)

_GENERAL_PRODUCTION_REPLAY_LEGACY_FIELDS = frozenset(
    {
        "schema",
        "contract_identity",
        "implementation_identity",
        "seed",
        "session_id",
        "session_secret_hex",
        "initial_hand_count",
        "general_registry_identity",
        "general_profile_identities",
        "general_semantic_payloads",
        "general_assignments",
        "skill_registry_identity",
        "skill_profile_identities",
        "derived_skill_assignments",
        "primary_general_key",
        "owner_id",
        "trigger_event_sequence",
        "trigger_event_type",
        "usage_before",
        "usage_after",
        "marks_before",
        "marks_after",
        "skill_runtime_after",
        "continuation_identity",
        "action_ids",
        "legal_set_hashes",
        "chosen_action_semantics",
        "event_slice",
        "state_hash_before",
        "state_hash_after",
        "rng_hash",
        "production_authority_after",
        "production_authority_trace",
        "records_identity",
        "execution_identity",
    }
)

_GENERAL_PRODUCTION_REPLAY_VERSIONED_FIELDS = (
    _GENERAL_PRODUCTION_REPLAY_LEGACY_FIELDS
    | {
        "replay_contract_version",
        "required_authority_capabilities",
    }
)

_GENERAL_PRODUCTION_REPLAY_G3_V2_FIELDS = (
    _GENERAL_PRODUCTION_REPLAY_VERSIONED_FIELDS
    | {
        "participant_player_ids",
    }
)

_GENERAL_PRODUCTION_REPLAY_CONTRACT_DESCRIPTOR_V1: Mapping[str, object] = {
    "authentication_order": [
        "exact_schema",
        "contract_identity",
        "implementation_identity",
        "general_registry_identity",
        "general_profile_identities",
        "general_semantic_payloads",
        "general_assignments",
        "derived_skill_assignments",
        "skill_registry_identity",
        "skill_profile_identities",
        "trigger_event_binding",
        "usage_and_marks_transition",
        "full_skill_runtime_after",
        "full_production_authority_trace",
        "continuation_identity",
        "records_identity",
        "execution_identity",
        "fresh_session",
        "live_legal_actions",
        "step",
    ],
    "envelope_fields": sorted(_GENERAL_PRODUCTION_REPLAY_LEGACY_FIELDS),
    "nested_action_fields": sorted(_ACTION_SEMANTICS_FIELDS),
    "nested_event_base_fields": sorted(_EVENT_BASE_FIELDS),
    "nested_event_damage_fields": sorted(_EVENT_DAMAGE_FIELDS),
    "schema": GENERAL_PRODUCTION_REPLAY_SCHEMA_V1,
    "strict_json_types": True,
}


def general_production_replay_contract_identity() -> str:
    """Return the stable identity of the V1 production-general replay contract."""
    return sha256_value(_GENERAL_PRODUCTION_REPLAY_CONTRACT_DESCRIPTOR_V1)


GENERAL_PRODUCTION_REPLAY_CONTRACT_IDENTITY_V1 = (
    general_production_replay_contract_identity()
)

_GENERAL_PRODUCTION_REPLAY_CONTRACT_DESCRIPTOR_V2: Mapping[str, object] = {
    "authentication_order": [
        "exact_schema",
        "replay_contract_version",
        "required_authority_capabilities",
        "contract_identity",
        "implementation_identity",
        "general_registry_identity",
        "general_profile_identities",
        "general_semantic_payloads",
        "general_assignments",
        "derived_skill_assignments",
        "skill_registry_identity",
        "skill_profile_identities",
        "trigger_event_binding",
        "usage_and_marks_transition",
        "full_skill_runtime_after",
        "required_full_production_authority_trace",
        "required_production_authority_after",
        "continuation_identity",
        "records_identity",
        "execution_identity",
        "fresh_session",
        "live_legal_actions",
        "step",
    ],
    "envelope_fields": sorted(_GENERAL_PRODUCTION_REPLAY_G3_V2_FIELDS),
    "nested_action_fields": sorted(_ACTION_SEMANTICS_FIELDS),
    "nested_event_base_fields": sorted(_EVENT_BASE_FIELDS),
    "nested_event_damage_fields": sorted(_EVENT_DAMAGE_FIELDS),
    "required_authority_capabilities": list(
        GENERAL_PRODUCTION_REPLAY_G3_REQUIRED_AUTHORITY_CAPABILITIES
    ),
    "required_authority_snapshot_fields": sorted(
        _G3_AUTHORITY_SNAPSHOT_REQUIRED_FIELDS
    ),
    "schema": GENERAL_PRODUCTION_REPLAY_SCHEMA_V1,
    "version": GENERAL_PRODUCTION_REPLAY_CONTRACT_VERSION_G3_AUTHORITY_V2,
    "strict_json_types": True,
}


def general_production_replay_contract_identity_v2() -> str:
    return sha256_value(_GENERAL_PRODUCTION_REPLAY_CONTRACT_DESCRIPTOR_V2)


GENERAL_PRODUCTION_REPLAY_CONTRACT_IDENTITY_V2 = (
    general_production_replay_contract_identity_v2()
)


def _exact_general_assignments(value: object) -> dict[str, str]:
    data = _exact_dict(value, "general_assignments")
    if not data:
        raise _replay_format_error("general_assignments", "不得为空")
    result: dict[str, str] = {}
    for key, item in data.items():
        player_id = _exact_string(key, "general_assignments.<player_id>")
        assert isinstance(player_id, str)
        gen_key = _exact_string(item, f"general_assignments.{player_id}")
        assert isinstance(gen_key, str)
        result[player_id] = gen_key
    return result


def _exact_general_semantic_payloads(
    value: object,
) -> dict[str, Mapping[str, Any]]:
    from .generals import GeneralDefinition

    data = _exact_dict(value, "general_semantic_payloads")
    if not data:
        raise _replay_format_error("general_semantic_payloads", "不得为空")
    result: dict[str, Mapping[str, Any]] = {}
    for raw_key, raw_payload in data.items():
        general_key = _exact_string(
            raw_key, "general_semantic_payloads.<general_key>"
        )
        assert isinstance(general_key, str)
        payload = _exact_dict(
            raw_payload, f"general_semantic_payloads.{general_key}"
        )
        try:
            definition = GeneralDefinition.from_dict(payload)
        except (TypeError, ValueError) as exc:
            raise _replay_format_error(
                f"general_semantic_payloads.{general_key}", str(exc)
            ) from exc
        if definition.general_key != general_key:
            raise _replay_format_error(
                f"general_semantic_payloads.{general_key}",
                "映射键与 payload.general_key 不一致",
            )
        result[general_key] = MappingProxyType(definition.to_dict())
    return result


def _requires_g3_authority_contract(
    *,
    primary_general_key: str,
    general_assignments: Mapping[str, str],
    derived_skill_assignments: Mapping[str, tuple[str, ...]],
) -> bool:
    if primary_general_key == "wangyuanji":
        return True
    if "wangyuanji" in general_assignments.values():
        return True
    g3_skill_ids = {
        "sgs_skill_qianchong",
        "sgs_skill_mingzhe",
        "sgs_skill_shangjian",
    }
    return any(
        g3_skill_ids.intersection(skill_ids)
        for skill_ids in derived_skill_assignments.values()
    )


def _requires_current_general_production_replay_contract(
    *,
    primary_general_key: str,
    general_assignments: Mapping[str, str],
    derived_skill_assignments: Mapping[str, tuple[str, ...]],
    replay_contract_version: str | None = None,
    contract_identity: str | None = None,
    required_authority_capabilities: tuple[str, ...] | list[str] | None = None,
) -> bool:
    explicit_v2_version = (
        replay_contract_version
        == GENERAL_PRODUCTION_REPLAY_CONTRACT_VERSION_G3_AUTHORITY_V2
    )
    explicit_v2_contract_identity = (
        contract_identity
        == GENERAL_PRODUCTION_REPLAY_CONTRACT_IDENTITY_V2
    )
    caps = (
        tuple(required_authority_capabilities)
        if required_authority_capabilities is not None
        else ()
    )
    explicit_g3_required_capabilities = bool(
        caps
        and (
            caps == GENERAL_PRODUCTION_REPLAY_G3_REQUIRED_AUTHORITY_CAPABILITIES
            or any(
                cap in GENERAL_PRODUCTION_REPLAY_G3_REQUIRED_AUTHORITY_CAPABILITIES
                for cap in caps
            )
        )
    )
    content_requires_g3 = _requires_g3_authority_contract(
        primary_general_key=primary_general_key,
        general_assignments=general_assignments,
        derived_skill_assignments=derived_skill_assignments,
    )
    return bool(
        explicit_v2_version
        or explicit_v2_contract_identity
        or explicit_g3_required_capabilities
        or content_requires_g3
    )


def _validate_g3_authority_snapshot(
    snapshot: Mapping[str, Any], label: str
) -> None:
    missing = _G3_AUTHORITY_SNAPSHOT_REQUIRED_FIELDS - set(snapshot)
    if missing:
        raise SkillReplayDivergenceError(
            f"{label}缺少当前 G3 authority 字段: {sorted(missing)}"
        )
    if type(snapshot["runtime"]) is not dict:
        raise SkillReplayDivergenceError(f"{label}.runtime必须是JSON object")
    ledger = snapshot["turn_loss_ledger"]
    if type(ledger) is not dict or not {
        "turn_number",
        "turn_player_id",
        "entries",
    }.issubset(ledger):
        raise SkillReplayDivergenceError(
            f"{label}.turn_loss_ledger缺少 canonical schema"
        )
    if type(ledger["entries"]) is not list:
        raise SkillReplayDivergenceError(
            f"{label}.turn_loss_ledger.entries必须是JSON array"
        )
    if type(snapshot["card_movement_authority"]) is not list:
        raise SkillReplayDivergenceError(
            f"{label}.card_movement_authority必须是JSON array"
        )
    decision_fields = {
        "decision_window_id",
        "skill_id",
        "actor_id",
        "trigger_event_sequence",
        "trigger_index",
        "trigger_event_type",
        "card_instance_id",
        "window_revision",
        "consumption_key",
        "payload",
    }
    pending = snapshot["pending_skill_decision"]
    if pending is not None and (
        type(pending) is not dict or not decision_fields.issubset(pending)
    ):
        raise SkillReplayDivergenceError(
            f"{label}.pending_skill_decision缺少 canonical schema"
        )
    queue = snapshot["pending_skill_decision_queue"]
    if type(queue) is not list or any(
        type(item) is not dict or not decision_fields.issubset(item)
        for item in queue
    ):
        raise SkillReplayDivergenceError(
            f"{label}.pending_skill_decision_queue缺少 canonical schema"
        )
    continuation = snapshot["pending_card_continuation"]
    continuation_fields = {
        "continuation_id",
        "continuation_kind",
        "source_event_sequence",
        "source_event_type",
        "card_action_identity",
        "actor_id",
        "owner_id",
        "card_instance_id",
        "target_ids",
        "expected_phase",
        "expected_pending_dying_id",
        "window_revision",
        "expected_revision",
        "consumed",
    }
    if continuation is not None and (
        type(continuation) is not dict
        or not continuation_fields.issubset(continuation)
    ):
        raise SkillReplayDivergenceError(
            f"{label}.pending_card_continuation缺少 canonical schema"
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class GeneralProductionReplayEnvelope:
    """Production general replay envelope binding general authority and skill derivation."""

    schema: str = GENERAL_PRODUCTION_REPLAY_SCHEMA_V1
    seed: int
    session_id: str
    session_secret_hex: str
    initial_hand_count: int
    general_registry_identity: str
    general_profile_identities: Mapping[str, str]
    general_semantic_payloads: Mapping[str, Mapping[str, Any]]
    general_assignments: Mapping[str, str]
    skill_registry_identity: str
    skill_profile_identities: Mapping[str, str]
    derived_skill_assignments: Mapping[str, tuple[str, ...]]
    primary_general_key: str
    owner_id: str
    trigger_event_sequence: int
    trigger_event_type: str
    usage_before: Mapping[str, int]
    usage_after: Mapping[str, int]
    marks_before: Mapping[str, int]
    marks_after: Mapping[str, int]
    skill_runtime_after: Mapping[str, Any]
    continuation_identity: str
    action_ids: tuple[str, ...]
    legal_set_hashes: tuple[str, ...]
    chosen_action_semantics: tuple[Mapping[str, Any], ...]
    event_slice: tuple[Mapping[str, Any], ...]
    state_hash_before: str
    state_hash_after: str
    rng_hash: str
    replay_contract_version: str = ""
    required_authority_capabilities: tuple[str, ...] | None = None
    participant_player_ids: tuple[str, ...] | None = None
    production_authority_after: Mapping[str, Any] = field(default_factory=dict)
    production_authority_trace: tuple[Mapping[str, Any], ...] = ()
    contract_identity: str = ""
    implementation_identity: str = field(default_factory=_current_implementation_identity)
    records_identity: str = ""
    execution_identity: str = ""
    historical_implicit_legacy: bool = field(
        default=False, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        if self.schema != GENERAL_PRODUCTION_REPLAY_SCHEMA_V1:
            raise ValueError(f"不受支持的生产武将回放 schema: {self.schema}")
        object.__setattr__(
            self,
            "general_profile_identities",
            MappingProxyType(dict(self.general_profile_identities)),
        )
        object.__setattr__(
            self,
            "general_assignments",
            MappingProxyType(dict(self.general_assignments)),
        )
        object.__setattr__(
            self,
            "general_semantic_payloads",
            MappingProxyType(
                {
                    key: MappingProxyType(dict(value))
                    for key, value in self.general_semantic_payloads.items()
                }
            ),
        )
        object.__setattr__(
            self,
            "skill_profile_identities",
            MappingProxyType(dict(self.skill_profile_identities)),
        )
        object.__setattr__(
            self,
            "derived_skill_assignments",
            MappingProxyType({k: tuple(v) for k, v in self.derived_skill_assignments.items()}),
        )
        requires_current_contract = (
            _requires_current_general_production_replay_contract(
                primary_general_key=self.primary_general_key,
                general_assignments=self.general_assignments,
                derived_skill_assignments=self.derived_skill_assignments,
                replay_contract_version=self.replay_contract_version,
                contract_identity=self.contract_identity,
                required_authority_capabilities=self.required_authority_capabilities,
            )
        )
        if requires_current_contract:
            if self.participant_player_ids is None:
                raise SkillReplayDivergenceError(
                    "当前 G3 回放必须显式提供 participant_player_ids"
                )
            participant_player_ids = self.participant_player_ids
            if (
                type(participant_player_ids) is not tuple
                or len(participant_player_ids) < 2
                or any(
                    not isinstance(player_id, str) or not player_id
                    for player_id in participant_player_ids
                )
                or len(set(participant_player_ids)) != len(participant_player_ids)
            ):
                raise SkillReplayDivergenceError(
                    "participant_player_ids必须是至少两项、非空且不重复的字符串元组"
                )
            if not set(self.general_assignments).issubset(participant_player_ids):
                raise SkillReplayDivergenceError(
                    "general_assignments引用了participant_player_ids之外的角色"
                )
            object.__setattr__(
                self, "participant_player_ids", tuple(participant_player_ids)
            )
            if not self.replay_contract_version:
                raise SkillReplayDivergenceError(
                    "当前 G3 回放必须显式提供 replay_contract_version"
                )
            if (
                self.replay_contract_version
                != GENERAL_PRODUCTION_REPLAY_CONTRACT_VERSION_G3_AUTHORITY_V2
            ):
                raise SkillReplayDivergenceError(
                    "当前 G3 武将回放不能降级为 legacy contract"
                )
            object.__setattr__(
                self, "replay_contract_version", self.replay_contract_version
            )
            if self.required_authority_capabilities is None:
                raise SkillReplayDivergenceError(
                    "当前 G3 回放必须显式提供 required_authority_capabilities"
                )
            if (
                tuple(self.required_authority_capabilities)
                != GENERAL_PRODUCTION_REPLAY_G3_REQUIRED_AUTHORITY_CAPABILITIES
            ):
                raise SkillReplayDivergenceError(
                    "当前 G3 回放 required_authority_capabilities 不完整"
                )
            object.__setattr__(
                self,
                "required_authority_capabilities",
                tuple(self.required_authority_capabilities),
            )
            if not self.contract_identity:
                raise SkillReplayDivergenceError(
                    "当前 G3 回放必须显式提供 contract_identity"
                )
            if (
                self.contract_identity
                != GENERAL_PRODUCTION_REPLAY_CONTRACT_IDENTITY_V2
            ):
                raise SkillReplayDivergenceError(
                    "contract_identity 与当前生产回放合同不匹配"
                )
            object.__setattr__(self, "contract_identity", self.contract_identity)
        else:
            participant_player_ids = self.participant_player_ids
            if participant_player_ids is None:
                participant_player_ids = ("p1", "p2")
            if (
                type(participant_player_ids) is not tuple
                or len(participant_player_ids) < 2
                or any(
                    not isinstance(player_id, str) or not player_id
                    for player_id in participant_player_ids
                )
                or len(set(participant_player_ids)) != len(participant_player_ids)
            ):
                raise SkillReplayDivergenceError(
                    "participant_player_ids必须是至少两项、非空且不重复的字符串元组"
                )
            if not set(self.general_assignments).issubset(participant_player_ids):
                raise SkillReplayDivergenceError(
                    "general_assignments引用了participant_player_ids之外的角色"
                )
            object.__setattr__(
                self, "participant_player_ids", tuple(participant_player_ids)
            )
            version = (
                self.replay_contract_version
                or GENERAL_PRODUCTION_REPLAY_CONTRACT_VERSION_LEGACY
            )
            if (
                version
                != GENERAL_PRODUCTION_REPLAY_CONTRACT_VERSION_LEGACY
            ):
                raise SkillReplayDivergenceError(
                    "历史 G1/G2 回放必须显式声明 legacy contract"
                )
            object.__setattr__(self, "replay_contract_version", version)
            capabilities = (
                ()
                if self.required_authority_capabilities is None
                else self.required_authority_capabilities
            )
            if tuple(capabilities):
                raise SkillReplayDivergenceError(
                    "legacy contract 不得声明当前 G3 authority capabilities"
                )
            object.__setattr__(
                self, "required_authority_capabilities", tuple(capabilities)
            )
            contract_identity = (
                self.contract_identity
                or GENERAL_PRODUCTION_REPLAY_CONTRACT_IDENTITY_V1
            )
            object.__setattr__(self, "contract_identity", contract_identity)
        object.__setattr__(self, "usage_before", MappingProxyType(dict(self.usage_before)))
        object.__setattr__(self, "usage_after", MappingProxyType(dict(self.usage_after)))
        object.__setattr__(self, "marks_before", MappingProxyType(dict(self.marks_before)))
        object.__setattr__(self, "marks_after", MappingProxyType(dict(self.marks_after)))
        object.__setattr__(
            self,
            "skill_runtime_after",
            MappingProxyType(dict(_json_frozen(self.skill_runtime_after))),
        )
        authority_after = _json_frozen(self.production_authority_after)
        if type(authority_after) is not dict:
            raise ValueError("production_authority_after必须是JSON object")
        object.__setattr__(
            self,
            "production_authority_after",
            MappingProxyType(dict(authority_after)),
        )
        authority_trace: list[Mapping[str, Any]] = []
        for index, item in enumerate(self.production_authority_trace):
            frozen_item = _json_frozen(item)
            if type(frozen_item) is not dict:
                raise SkillReplayDivergenceError(
                    f"production_authority_trace[{index}]必须是JSON object"
                )
            authority_trace.append(MappingProxyType(dict(frozen_item)))
        object.__setattr__(self, "production_authority_trace", tuple(authority_trace))
        self._validate_authority_contract(requires_current_contract)
        if not self.records_identity:
            object.__setattr__(self, "records_identity", self._compute_records_identity())
        if not self.execution_identity:
            object.__setattr__(self, "execution_identity", self._compute_execution_identity())

    def _validate_authority_contract(self, requires_g3_authority: bool) -> None:
        if requires_g3_authority:
            if (
                self.replay_contract_version
                != GENERAL_PRODUCTION_REPLAY_CONTRACT_VERSION_G3_AUTHORITY_V2
            ):
                raise SkillReplayDivergenceError(
                    "当前 G3 武将回放不能降级为 legacy contract"
                )
            if tuple(self.required_authority_capabilities or ()) != (
                GENERAL_PRODUCTION_REPLAY_G3_REQUIRED_AUTHORITY_CAPABILITIES
            ):
                raise SkillReplayDivergenceError(
                    "当前 G3 回放 required_authority_capabilities 不完整"
                )
            if (
                self.contract_identity
                != GENERAL_PRODUCTION_REPLAY_CONTRACT_IDENTITY_V2
            ):
                raise SkillReplayDivergenceError(
                    "contract_identity 与当前生产回放合同不匹配"
                )
            if not self.production_authority_trace:
                raise SkillReplayDivergenceError(
                    "当前 G3 回放 production_authority_trace 必须存在且非空"
                )
            if len(self.production_authority_trace) != len(self.action_ids):
                raise SkillReplayDivergenceError(
                    "当前 G3 回放 production_authority_trace 必须与 action_ids 一一对应"
                )
            if not self.production_authority_after:
                raise SkillReplayDivergenceError(
                    "当前 G3 回放 production_authority_after 必须存在且非空"
                )
            for index, snapshot in enumerate(self.production_authority_trace):
                _validate_g3_authority_snapshot(
                    snapshot, f"production_authority_trace[{index}]"
                )
            _validate_g3_authority_snapshot(
                self.production_authority_after,
                "production_authority_after",
            )
            if _json_frozen(self.production_authority_after) != _json_frozen(
                self.production_authority_trace[-1]
            ):
                raise SkillReplayDivergenceError(
                    "当前 G3 production_authority_after 必须等于 trace 最终快照"
                )
            return
        if (
            self.replay_contract_version
            != GENERAL_PRODUCTION_REPLAY_CONTRACT_VERSION_LEGACY
        ):
            raise SkillReplayDivergenceError(
                "历史 G1/G2 回放必须显式声明 legacy contract"
            )
        if tuple(self.required_authority_capabilities or ()):
            raise SkillReplayDivergenceError(
                "legacy contract 不得声明当前 G3 authority capabilities"
            )
        if self.production_authority_trace and len(
            self.production_authority_trace
        ) != len(self.action_ids):
            raise SkillReplayDivergenceError(
                "legacy production_authority_trace 必须与 action_ids 一一对应"
            )

    def _compute_records_identity(self) -> str:
        payload: dict[str, Any] = {
            "action_ids": list(self.action_ids),
            "chosen_action_semantics": [
                _json_frozen(item) for item in self.chosen_action_semantics
            ],
            "event_slice": [_json_frozen(item) for item in self.event_slice],
            "legal_set_hashes": list(self.legal_set_hashes),
            "owner_id": self.owner_id,
            "primary_general_key": self.primary_general_key,
            "trigger_event_sequence": self.trigger_event_sequence,
            "trigger_event_type": self.trigger_event_type,
            "usage_before": dict(self.usage_before),
            "usage_after": dict(self.usage_after),
            "marks_before": dict(self.marks_before),
            "marks_after": dict(self.marks_after),
            "skill_runtime_after": _json_frozen(self.skill_runtime_after),
            "continuation_identity": self.continuation_identity,
            "rng_hash": self.rng_hash,
            "state_hash_after": self.state_hash_after,
            "state_hash_before": self.state_hash_before,
        }
        if (
            self.replay_contract_version
            == GENERAL_PRODUCTION_REPLAY_CONTRACT_VERSION_G3_AUTHORITY_V2
        ):
            payload["participant_player_ids"] = list(
                self.participant_player_ids or ()
            )
            payload["replay_contract_version"] = self.replay_contract_version
            payload["required_authority_capabilities"] = list(
                self.required_authority_capabilities or ()
            )
            payload["production_authority_after"] = _json_frozen(
                self.production_authority_after
            )
            payload["production_authority_trace"] = [
                _json_frozen(item) for item in self.production_authority_trace
            ]
        elif self.production_authority_after or self.production_authority_trace:
            # Preserve the exact historical V1 identity shape for genuine
            # G1/G2 envelopes that already carried optional authority data.
            payload["production_authority_after"] = _json_frozen(
                self.production_authority_after
            )
            payload["production_authority_trace"] = [
                _json_frozen(item) for item in self.production_authority_trace
            ]
        return sha256_value(payload)

    def _compute_execution_identity(self) -> str:
        payload = self.to_dict()
        payload.pop("execution_identity", None)
        if self.historical_implicit_legacy:
            # Historical V1 execution identities predate these explicit
            # discriminator fields. Their fixed values are validated directly.
            payload.pop("replay_contract_version", None)
            payload.pop("required_authority_capabilities", None)
        return hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "schema": self.schema,
            "contract_identity": self.contract_identity,
            "implementation_identity": self.implementation_identity,
            "seed": self.seed,
            "session_id": self.session_id,
            "session_secret_hex": self.session_secret_hex,
            "initial_hand_count": self.initial_hand_count,
            "general_registry_identity": self.general_registry_identity,
            "general_profile_identities": dict(sorted(self.general_profile_identities.items())),
            "general_semantic_payloads": {
                key: _json_frozen(value)
                for key, value in sorted(self.general_semantic_payloads.items())
            },
            "general_assignments": dict(sorted(self.general_assignments.items())),
            "skill_registry_identity": self.skill_registry_identity,
            "skill_profile_identities": dict(sorted(self.skill_profile_identities.items())),
            "derived_skill_assignments": {k: list(v) for k, v in sorted(self.derived_skill_assignments.items())},
            "primary_general_key": self.primary_general_key,
            "owner_id": self.owner_id,
            "trigger_event_sequence": self.trigger_event_sequence,
            "trigger_event_type": self.trigger_event_type,
            "usage_before": dict(self.usage_before),
            "usage_after": dict(self.usage_after),
            "marks_before": dict(self.marks_before),
            "marks_after": dict(self.marks_after),
            "skill_runtime_after": _json_frozen(self.skill_runtime_after),
            "continuation_identity": self.continuation_identity,
            "action_ids": list(self.action_ids),
            "legal_set_hashes": list(self.legal_set_hashes),
            "chosen_action_semantics": [_json_frozen(item) for item in self.chosen_action_semantics],
            "event_slice": [_json_frozen(item) for item in self.event_slice],
            "state_hash_before": self.state_hash_before,
            "state_hash_after": self.state_hash_after,
            "rng_hash": self.rng_hash,
            "replay_contract_version": self.replay_contract_version,
            "required_authority_capabilities": list(
                self.required_authority_capabilities or ()
            ),
            "production_authority_after": _json_frozen(
                self.production_authority_after
            ),
            "production_authority_trace": [
                _json_frozen(item) for item in self.production_authority_trace
            ],
            "records_identity": self.records_identity,
            "execution_identity": self.execution_identity,
        }
        if (
            self.replay_contract_version
            == GENERAL_PRODUCTION_REPLAY_CONTRACT_VERSION_G3_AUTHORITY_V2
        ):
            payload["participant_player_ids"] = list(
                self.participant_player_ids or ()
            )
        if self.historical_implicit_legacy:
            payload.pop("replay_contract_version", None)
            payload.pop("required_authority_capabilities", None)
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "GeneralProductionReplayEnvelope":
        data = _exact_dict(payload, "<root>")
        field_names = frozenset(data)
        historical_implicit_legacy = (
            field_names == _GENERAL_PRODUCTION_REPLAY_LEGACY_FIELDS
        )
        if not historical_implicit_legacy:
            if "replay_contract_version" not in data:
                _exact_fields(
                    data, _GENERAL_PRODUCTION_REPLAY_VERSIONED_FIELDS, "<root>"
                )
            raw_version = _exact_string(
                data["replay_contract_version"], "replay_contract_version"
            )
            expected_fields = (
                _GENERAL_PRODUCTION_REPLAY_G3_V2_FIELDS
                if raw_version
                == GENERAL_PRODUCTION_REPLAY_CONTRACT_VERSION_G3_AUTHORITY_V2
                else _GENERAL_PRODUCTION_REPLAY_VERSIONED_FIELDS
            )
            _exact_fields(data, expected_fields, "<root>")
        schema = _exact_string(data["schema"], "schema")
        if schema != GENERAL_PRODUCTION_REPLAY_SCHEMA_V1:
            raise SkillReplayDivergenceError(f"不受支持的生产武将回放 schema: {schema}")
        if historical_implicit_legacy:
            replay_contract_version = (
                GENERAL_PRODUCTION_REPLAY_CONTRACT_VERSION_LEGACY
            )
            required_authority_capabilities: tuple[str, ...] = ()
        else:
            replay_contract_version = _exact_string(
                data["replay_contract_version"], "replay_contract_version"
            )
            assert isinstance(replay_contract_version, str)
            required_authority_capabilities = _exact_string_list(
                data["required_authority_capabilities"],
                "required_authority_capabilities",
                allow_empty=True,
                unique=True,
            )
        participant_player_ids = (
            _exact_string_list(
                data["participant_player_ids"],
                "participant_player_ids",
                allow_empty=False,
                unique=True,
            )
            if replay_contract_version
            == GENERAL_PRODUCTION_REPLAY_CONTRACT_VERSION_G3_AUTHORITY_V2
            else ("p1", "p2")
        )
        if len(participant_player_ids) < 2:
            raise _replay_format_error(
                "participant_player_ids", "必须至少包含两名角色"
            )
        contract_identity = _exact_sha256(data["contract_identity"], "contract_identity")
        implementation_identity = _exact_sha256(
            data["implementation_identity"], "implementation_identity"
        )
        seed = _exact_int(data["seed"], "seed")
        session_id = _exact_string(data["session_id"], "session_id")
        session_secret_hex = _exact_string(
            data["session_secret_hex"], "session_secret_hex"
        )
        assert isinstance(session_secret_hex, str)
        if len(session_secret_hex) != 64 or _SHA256_RE.fullmatch(session_secret_hex) is None:
            raise _replay_format_error(
                "session_secret_hex", "必须是精确 32 字节的小写十六进制字符串"
            )
        initial_hand_count = _exact_int(
            data["initial_hand_count"], "initial_hand_count", minimum=1
        )
        general_registry_identity = _exact_sha256(
            data["general_registry_identity"], "general_registry_identity"
        )
        general_profiles = _exact_profile_identities(data["general_profile_identities"])
        general_semantic_payloads = _exact_general_semantic_payloads(
            data["general_semantic_payloads"]
        )
        general_assignments = _exact_general_assignments(data["general_assignments"])
        skill_registry_identity = _exact_sha256(
            data["skill_registry_identity"], "skill_registry_identity"
        )
        skill_profiles = _exact_profile_identities(data["skill_profile_identities"])
        derived_assignments = _exact_assignments(data["derived_skill_assignments"])
        primary_general_key = _exact_string(data["primary_general_key"], "primary_general_key")
        owner_id = _exact_string(data["owner_id"], "owner_id")
        assert isinstance(primary_general_key, str)
        if historical_implicit_legacy and _requires_current_general_production_replay_contract(
            primary_general_key=primary_general_key,
            general_assignments=general_assignments,
            derived_skill_assignments=derived_assignments,
            replay_contract_version=replay_contract_version,
            contract_identity=contract_identity,
            required_authority_capabilities=required_authority_capabilities,
        ):
            raise SkillReplayDivergenceError(
                "当前 G3 武将回放不能通过删除 contract/authority 字段降级为历史 V1"
            )
        trigger_event_sequence = _exact_int(
            data["trigger_event_sequence"], "trigger_event_sequence", minimum=0
        )
        trigger_event_type = _exact_string(
            data["trigger_event_type"], "trigger_event_type"
        )
        continuation_identity = _exact_sha256(
            data["continuation_identity"], "continuation_identity"
        )
        skill_runtime_after = _exact_json_value(
            data["skill_runtime_after"], "skill_runtime_after"
        )
        if type(skill_runtime_after) is not dict:
            raise _replay_format_error(
                "skill_runtime_after", "必须是 JSON object"
            )
        production_authority_after = _exact_json_value(
            data["production_authority_after"], "production_authority_after"
        )
        if type(production_authority_after) is not dict:
            raise _replay_format_error(
                "production_authority_after", "必须是 JSON object"
            )
        raw_authority_trace = data["production_authority_trace"]
        if type(raw_authority_trace) is not list:
            raise _replay_format_error(
                "production_authority_trace", "必须是 JSON array"
            )
        production_authority_trace: tuple[Mapping[str, Any], ...] = tuple(
            _exact_dict(
                _exact_json_value(item, f"production_authority_trace[{index}]"),
                f"production_authority_trace[{index}]",
            )
            for index, item in enumerate(raw_authority_trace)
        )

        action_ids = _exact_string_list(
            data["action_ids"], "action_ids", allow_empty=False, unique=True
        )
        for index, action_id in enumerate(action_ids):
            if _ACTION_ID_RE.fullmatch(action_id) is None:
                raise _replay_format_error(
                    f"action_ids[{index}]",
                    "必须是 act_ 加 256-bit SHA-256 represented as 64 lowercase hexadecimal characters",
                )
        legal_set_hashes = _exact_string_list(
            data["legal_set_hashes"],
            "legal_set_hashes",
            allow_empty=False,
            unique=False,
        )
        for index, item in enumerate(legal_set_hashes):
            _exact_sha256(item, f"legal_set_hashes[{index}]")
        raw_semantics = data["chosen_action_semantics"]
        if type(raw_semantics) is not list:
            raise _replay_format_error("chosen_action_semantics", "必须是 JSON array")
        semantics = tuple(
            _exact_action_semantics(item, index)
            for index, item in enumerate(raw_semantics)
        )
        if not (
            len(action_ids) == len(legal_set_hashes) == len(semantics)
        ):
            raise _replay_format_error(
                "action_ids/legal_set_hashes/chosen_action_semantics",
                "长度必须完全一致",
            )
        raw_events = data["event_slice"]
        if type(raw_events) is not list:
            raise _replay_format_error("event_slice", "必须是 JSON array")
        events = tuple(_exact_event(item, index) for index, item in enumerate(raw_events))
        sequences = tuple(event["sequence"] for event in events)
        if len(sequences) != len(set(sequences)) or sequences != tuple(sorted(sequences)):
            raise _replay_format_error("event_slice.sequence", "必须严格递增且不得重复")
        loaded = cls(
            schema=schema,
            contract_identity=contract_identity,
            implementation_identity=implementation_identity,
            seed=int(seed),
            session_id=session_id,
            session_secret_hex=session_secret_hex,
            initial_hand_count=int(initial_hand_count),
            general_registry_identity=general_registry_identity,
            general_profile_identities=general_profiles,
            general_semantic_payloads=general_semantic_payloads,
            general_assignments=general_assignments,
            skill_registry_identity=skill_registry_identity,
            skill_profile_identities=skill_profiles,
            derived_skill_assignments=derived_assignments,
            primary_general_key=primary_general_key,
            owner_id=owner_id,
            trigger_event_sequence=int(trigger_event_sequence),
            trigger_event_type=trigger_event_type,
            usage_before=_exact_usage(data["usage_before"], "usage_before"),
            usage_after=_exact_usage(data["usage_after"], "usage_after"),
            marks_before=_exact_marks(data["marks_before"], "marks_before"),
            marks_after=_exact_marks(data["marks_after"], "marks_after"),
            skill_runtime_after=skill_runtime_after,
            continuation_identity=continuation_identity,
            action_ids=action_ids,
            legal_set_hashes=legal_set_hashes,
            chosen_action_semantics=semantics,
            event_slice=events,
            state_hash_before=_exact_sha256(data["state_hash_before"], "state_hash_before"),
            state_hash_after=_exact_sha256(data["state_hash_after"], "state_hash_after"),
            rng_hash=_exact_sha256(data["rng_hash"], "rng_hash"),
            replay_contract_version=replay_contract_version,
            required_authority_capabilities=required_authority_capabilities,
            participant_player_ids=participant_player_ids,
            production_authority_after=production_authority_after,
            production_authority_trace=production_authority_trace,
            records_identity=_exact_sha256(data["records_identity"], "records_identity"),
            execution_identity=_exact_sha256(data["execution_identity"], "execution_identity"),
            historical_implicit_legacy=historical_implicit_legacy,
        )
        loaded._authenticate_static_fields()
        return loaded

    def _authenticate_static_fields(self) -> None:
        if self.schema != GENERAL_PRODUCTION_REPLAY_SCHEMA_V1:
            raise SkillReplayDivergenceError("生产武将回放 schema 不匹配")
        requires_current_contract = (
            _requires_current_general_production_replay_contract(
                primary_general_key=self.primary_general_key,
                general_assignments=self.general_assignments,
                derived_skill_assignments=self.derived_skill_assignments,
                replay_contract_version=self.replay_contract_version,
                contract_identity=self.contract_identity,
                required_authority_capabilities=self.required_authority_capabilities,
            )
        )
        self._validate_authority_contract(requires_current_contract)
        expected_contract_identity = (
            GENERAL_PRODUCTION_REPLAY_CONTRACT_IDENTITY_V2
            if requires_current_contract
            else GENERAL_PRODUCTION_REPLAY_CONTRACT_IDENTITY_V1
        )
        if self.contract_identity != expected_contract_identity:
            raise SkillReplayDivergenceError("contract_identity 与当前生产回放合同不匹配")
        current_implementation = _current_implementation_identity()
        if self.implementation_identity != current_implementation:
            raise SkillReplayDivergenceError(
                "implementation_identity 与当前生产实现不匹配"
            )
        if self.records_identity != self._compute_records_identity():
            raise SkillReplayDivergenceError("records_identity 与内层回放记录不一致")
        if self.execution_identity != self._compute_execution_identity():
            raise SkillReplayDivergenceError("execution_identity 与信封内容不一致")


def _construct_general_production_replay_session(
    envelope: GeneralProductionReplayEnvelope,
    general_registry: object,
    skill_registry: AuthoritativeSkillRegistry,
) -> object:
    from .production_batch import ProductionBasicCardBatch

    participant_player_ids = tuple(envelope.participant_player_ids or ())
    if len(participant_player_ids) < 2:
        raise SkillReplayDivergenceError(
            "生产武将回放 participant_player_ids 至少需要两名角色"
        )
    if any(
        player_id not in participant_player_ids
        for player_id in envelope.general_assignments
    ):
        raise SkillReplayDivergenceError(
            "武将分配引用了 participant_player_ids 之外的角色"
        )
    player_hp: list[int] = []
    player_max_hp: list[int] = []
    for player_id in participant_player_ids:
        general_key = envelope.general_assignments.get(player_id)
        if general_key is None:
            player_hp.append(4)
            player_max_hp.append(4)
            continue
        definition = general_registry.get_general(general_key)
        player_hp.append(definition.starting_hp)
        player_max_hp.append(definition.max_hp)
    first_semantics = envelope.chosen_action_semantics[0]
    first_actor = first_semantics.get("actor_id")
    if not isinstance(first_actor, str) or first_actor not in participant_player_ids:
        raise SkillReplayDivergenceError(
            "生产武将回放首步缺少可绑定的 first_player_id"
        )
    constructor_kwargs: dict[str, object] = {"first_player_id": first_actor}
    return ProductionBasicCardBatch(
        seed=envelope.seed,
        session_id=envelope.session_id,
        session_secret=bytes.fromhex(envelope.session_secret_hex),
        initial_hand_count=envelope.initial_hand_count,
        player_hp=tuple(player_hp),
        player_max_hp=tuple(player_max_hp),
        player_ids=participant_player_ids,
        general_registry=general_registry,
        general_assignments=envelope.general_assignments,
        skill_registry=skill_registry,
        **constructor_kwargs,
    )


def reexecute_general_production_replay(
    envelope: GeneralProductionReplayEnvelope,
    general_registry: object,
    skill_registry: AuthoritativeSkillRegistry,
) -> SkillReplayVerificationResult:
    if type(envelope) is not GeneralProductionReplayEnvelope:
        raise SkillReplayDivergenceError(
            "生产武将回放必须是 exact GeneralProductionReplayEnvelope"
        )
    envelope = GeneralProductionReplayEnvelope.from_dict(envelope.to_dict())

    from .generals import AuthoritativeGeneralRegistry

    if type(general_registry) is not AuthoritativeGeneralRegistry:
        raise SkillReplayDivergenceError(
            "武将注册表必须是 exact AuthoritativeGeneralRegistry"
        )
    if not general_registry.is_frozen:
        raise SkillReplayDivergenceError("武将注册表必须已冻结")
    try:
        general_registry.assert_canonical_integrity()
        live_general_registry_identity = general_registry.canonical_registry_identity()
    except (TypeError, ValueError, UnsupportedRuleError) as exc:
        raise SkillReplayDivergenceError(
            f"武将注册表 live canonical payload 校验失败：{exc}"
        ) from exc
    if live_general_registry_identity != envelope.general_registry_identity:
        raise SkillReplayDivergenceError("武将注册表身份不匹配")

    if type(skill_registry) is not AuthoritativeSkillRegistry:
        raise SkillReplayDivergenceError(
            "技能注册表必须是 exact AuthoritativeSkillRegistry"
        )
    if not skill_registry.is_frozen:
        raise SkillReplayDivergenceError("技能注册表必须已冻结")
    if skill_registry.registry_identity != envelope.skill_registry_identity:
        raise SkillReplayDivergenceError("技能注册表身份不匹配")

    assigned_general_keys = set(envelope.general_assignments.values())
    if set(envelope.general_profile_identities) != assigned_general_keys:
        raise SkillReplayDivergenceError("武将 profile 集合与 live assignment 不精确一致")
    if set(envelope.general_semantic_payloads) != assigned_general_keys:
        raise SkillReplayDivergenceError("武将 semantic payload 集合与 live assignment 不精确一致")
    if set(envelope.derived_skill_assignments) != set(envelope.general_assignments):
        raise SkillReplayDivergenceError("派生技能归属与武将归属角色集合不精确一致")
    if envelope.owner_id not in envelope.general_assignments:
        raise SkillReplayDivergenceError("owner_id 不在武将分配中")
    if envelope.general_assignments[envelope.owner_id] != envelope.primary_general_key:
        raise SkillReplayDivergenceError("primary_general_key 与 owner_id 的 live assignment 不匹配")

    live_generals: dict[str, object] = {}
    for gen_key, expected_profile in envelope.general_profile_identities.items():
        try:
            gen_def = general_registry.get_general(gen_key)
        except (TypeError, ValueError, UnsupportedRuleError) as exc:
            raise SkillReplayDivergenceError(str(exc)) from exc
        live_generals[gen_key] = gen_def
        if gen_def.canonical_profile_identity() != expected_profile:
            raise SkillReplayDivergenceError(f"武将 {gen_key} profile identity 不匹配")
        if gen_def.to_dict() != dict(envelope.general_semantic_payloads[gen_key]):
            raise SkillReplayDivergenceError(f"武将 {gen_key} canonical semantic payload 不匹配")

    for player_id, gen_key in envelope.general_assignments.items():
        gen_def = live_generals[gen_key]
        expected_derived = envelope.derived_skill_assignments.get(player_id)
        if expected_derived != gen_def.skill_ids:
            raise SkillReplayDivergenceError(
                f"角色 {player_id} 从武将 {gen_key} 派生的技能集合不匹配"
            )
        for s_id in gen_def.skill_ids:
            if not skill_registry.has_skill(s_id):
                raise SkillReplayDivergenceError(f"技能注册表缺少派生技能 {s_id!r}")
            s_def = skill_registry.get_skill(s_id)
            if envelope.skill_profile_identities.get(s_id) != s_def.profile_identity:
                raise SkillReplayDivergenceError(f"派生技能 {s_id} profile identity 不匹配")

    all_derived_skills = {
        skill_id
        for skill_ids in envelope.derived_skill_assignments.values()
        for skill_id in skill_ids
    }
    if set(envelope.skill_profile_identities) != all_derived_skills:
        raise SkillReplayDivergenceError("技能 profile 集合与武将派生技能集合不精确一致")
    primary_general = live_generals[envelope.primary_general_key]
    tracked_skill_is_dynamic = False
    multiple_decisions_allowed = False
    if envelope.primary_general_key == "shamoke":
        tracked_skill_id = "sgs_skill_jili"
        tracked_label = "Jili"
        decision_required = True
        continuation_kind = "card"
        expected_trigger_types = {
            EventType.CARD_USED.value,
            EventType.CARD_PLAYED.value,
        }
    elif envelope.primary_general_key == "zhugezhan":
        if envelope.trigger_event_type == EventType.END_PHASE_STARTED.value:
            tracked_skill_id = "sgs_skill_zuilun"
            tracked_label = "Zuilun"
            decision_required = True
            continuation_kind = "skill"
            expected_trigger_types = {EventType.END_PHASE_STARTED.value}
        elif envelope.trigger_event_type == EventType.CARD_USED.value:
            tracked_skill_id = "sgs_skill_fuyin"
            tracked_label = "Fuyin"
            decision_required = False
            continuation_kind = "target_effect"
            expected_trigger_types = {EventType.CARD_USED.value}
        else:
            raise SkillReplayDivergenceError(
                "Zhugezhan 回放 trigger_event_type 不能确定 Zuilun/Fuyin 权威路径"
            )
    elif envelope.primary_general_key == "wangyuanji":
        if envelope.trigger_event_type == EventType.CARD_DISCARDED.value:
            tracked_skill_id = "sgs_skill_mingzhe"
            tracked_label = "Mingzhe"
            decision_required = True
            continuation_kind = "card"
            expected_trigger_types = {EventType.CARD_DISCARDED.value}
            tracked_skill_is_dynamic = True
            multiple_decisions_allowed = True
        elif envelope.trigger_event_type in (
            EventType.END_PHASE_STARTED.value,
            EventType.SKILL_CONDITION_EVALUATED.value,
        ):
            tracked_skill_id = "sgs_skill_shangjian"
            tracked_label = "Shangjian"
            decision_required = False
            continuation_kind = "evaluation"
            expected_trigger_types = {
                EventType.END_PHASE_STARTED.value,
                EventType.SKILL_CONDITION_EVALUATED.value,
            }
        elif envelope.trigger_event_type in (
            "play_phase_start",
            EventType.SKILL_CONDITION_EVALUATED.value,
        ):
            tracked_skill_id = "sgs_skill_qianchong"
            tracked_label = "Qianchong"
            decision_required = True
            continuation_kind = "permission"
            expected_trigger_types = {
                "play_phase_start",
                EventType.SKILL_CONDITION_EVALUATED.value,
            }
        else:
            raise SkillReplayDivergenceError(
                "Wangyuanji 回放 trigger_event_type 不能确定 Qianchong/Shangjian 权威路径"
            )
    else:
        raise SkillReplayDivergenceError(
            f"生产武将回放尚未声明 {envelope.primary_general_key!r} 的语义验证器"
        )
    if envelope.trigger_event_type not in expected_trigger_types:
        raise SkillReplayDivergenceError(
            f"{tracked_label} trigger_event_type 与权威时机不匹配"
        )
    if tracked_skill_is_dynamic:
        if "sgs_skill_qianchong" not in primary_general.skill_ids:
            raise SkillReplayDivergenceError(
                "Mingzhe 回放的 primary general 未派生 Qianchong 来源技能"
            )
        if not skill_registry.has_skill(tracked_skill_id):
            raise SkillReplayDivergenceError("技能注册表缺少动态 Mingzhe")
    else:
        if tracked_skill_id not in primary_general.skill_ids:
            raise SkillReplayDivergenceError(
                f"primary general 未派生 {tracked_label}"
            )
        if tracked_skill_id not in envelope.derived_skill_assignments[envelope.owner_id]:
            raise SkillReplayDivergenceError(
                f"owner_id 未从 primary general 派生 {tracked_label}"
            )

    from .production_batch import BatchActionIdController

    game = _construct_general_production_replay_session(
        envelope, general_registry, skill_registry
    )
    authority_required = (
        envelope.replay_contract_version
        == GENERAL_PRODUCTION_REPLAY_CONTRACT_VERSION_G3_AUTHORITY_V2
    )
    if (authority_required or envelope.production_authority_trace) and len(
        envelope.production_authority_trace
    ) != len(envelope.action_ids):
        raise SkillReplayDivergenceError(
            "production_authority_trace 必须与 action_ids 逐步一一对应"
        )

    steps_verified = 0
    tracked_step_seen = False
    trigger_step_seen = False
    usage_before_verified = False
    for index, action_id in enumerate(envelope.action_ids):
        legal = game.legal_actions()
        legal_hash = legal_actions_semantic_hash(legal)
        if legal_hash != envelope.legal_set_hashes[index]:
            raise SkillReplayDivergenceError(f"第 {index} 步合法动作语义集合不匹配")
        chosen = next((item for item in legal if item.action_id == action_id), None)
        if chosen is None:
            raise SkillReplayDivergenceError(
                f"第 {index} 步 chosen action_id 不在 live legal_actions 中"
            )
        expected_semantics = envelope.chosen_action_semantics[index]
        actual_semantics = action_semantics(chosen)
        if actual_semantics != expected_semantics:
            raise SkillReplayDivergenceError(f"第 {index} 步 chosen action 语义不匹配")
        if index == 0 and envelope.state_hash_before:
            if compute_state_hash(game.state) != envelope.state_hash_before:
                raise SkillReplayDivergenceError("起始状态哈希不匹配")
        if game.skill_runtime is None:
            raise SkillReplayDivergenceError("生产武将回放缺少 SkillRuntime")
        pre_skill_state = None
        if game.skill_runtime.has_skill(envelope.owner_id, tracked_skill_id):
            try:
                pre_skill_state = game.skill_runtime.get_skill_state(
                    envelope.owner_id, tracked_skill_id
                )
            except UnsupportedRuleError as exc:
                raise SkillReplayDivergenceError(str(exc)) from exc
        if (
            chosen.skill_id == tracked_skill_id
            and chosen.payload.get("operation") in ("activate_skill", "pass_skill", "qianchong_choice")
        ):
            if not decision_required:
                raise SkillReplayDivergenceError(
                    f"锁定技 {tracked_label} 不得生成 ACTIVATE/PASS 决策步"
                )
            first_tracked_decision = not tracked_step_seen
            if tracked_step_seen and not multiple_decisions_allowed:
                raise SkillReplayDivergenceError(
                    f"生产武将回放包含重复 {tracked_label} 决策步"
                )
            tracked_step_seen = True
            if chosen.actor_id != envelope.owner_id:
                raise SkillReplayDivergenceError(
                    f"{tracked_label} 决策 actor 与 owner_id 不匹配"
                )
            if first_tracked_decision and (
                chosen.payload.get("trigger_event_sequence")
                != envelope.trigger_event_sequence
            ):
                raise SkillReplayDivergenceError(
                    f"{tracked_label} trigger_event_sequence 不匹配"
                )
            if chosen.payload.get("trigger_event_type") != envelope.trigger_event_type:
                raise SkillReplayDivergenceError(
                    f"{tracked_label} trigger_event_type 不匹配"
                )
            if chosen.payload.get("continuation_identity") != envelope.continuation_identity:
                raise SkillReplayDivergenceError(
                    f"{tracked_label} continuation_identity 不匹配"
                )
            if (
                continuation_kind == "card"
                and game.pending_card_continuation_identity
                != envelope.continuation_identity
            ):
                raise SkillReplayDivergenceError(
                    "live pending card continuation identity 不匹配"
                )
            if first_tracked_decision:
                if pre_skill_state is None:
                    raise SkillReplayDivergenceError(
                        f"{tracked_label} 决策步缺少 live skill state"
                    )
                actual_usage_before = {
                    "uses_this_phase": pre_skill_state.uses_this_phase,
                    "uses_this_turn": pre_skill_state.uses_this_turn,
                }
                if actual_usage_before != dict(envelope.usage_before):
                    raise SkillReplayDivergenceError(
                        f"{tracked_label} usage_before 不匹配"
                    )
                if dict(pre_skill_state.marks) != dict(envelope.marks_before):
                    raise SkillReplayDivergenceError(
                        f"{tracked_label} marks_before 不匹配"
                    )
                usage_before_verified = True
        existing_sequences = {
            event.sequence for event in game.events if event.sequence is not None
        }
        game.step(BatchActionIdController(action_id))
        steps_verified += 1
        if authority_required or envelope.production_authority_trace:
            live_authority = _json_frozen(game._skill_audit_value() or {})
            expected_authority = _json_frozen(
                envelope.production_authority_trace[index]
            )
            if live_authority != expected_authority:
                raise SkillReplayDivergenceError(
                    f"第 {index} 步 production authority 快照不匹配"
                )
        if (
            not trigger_step_seen
            and envelope.trigger_event_sequence not in existing_sequences
            and any(
                event.sequence == envelope.trigger_event_sequence
                for event in game.events
            )
        ):
            trigger_step_seen = True
            if not decision_required:
                if pre_skill_state is None:
                    raise SkillReplayDivergenceError(
                        f"{tracked_label} 触发步缺少 live skill state"
                    )
                actual_usage_before = {
                    "uses_this_phase": pre_skill_state.uses_this_phase,
                    "uses_this_turn": pre_skill_state.uses_this_turn,
                }
                if actual_usage_before != dict(envelope.usage_before):
                    raise SkillReplayDivergenceError(
                        f"{tracked_label} usage_before 不匹配"
                    )
                if dict(pre_skill_state.marks) != dict(envelope.marks_before):
                    raise SkillReplayDivergenceError(
                        f"{tracked_label} marks_before 不匹配"
                    )
                usage_before_verified = True

    if decision_required and not tracked_step_seen:
        raise SkillReplayDivergenceError(
            f"生产武将回放未重现 {tracked_label} 决策"
        )
    if not usage_before_verified:
        raise SkillReplayDivergenceError(
            f"生产武将回放未绑定 {tracked_label} usage_before/marks_before"
        )

    if compute_state_hash(game.state) != envelope.state_hash_after:
        raise SkillReplayDivergenceError("终态哈希不匹配")
    if game.skill_runtime is None:
        raise SkillReplayDivergenceError("重放会话未装载 SkillRuntime")
    if game.general_registry is None:
        raise SkillReplayDivergenceError("重放会话未装载 GeneralRegistry")
    try:
        final_skill_state = game.skill_runtime.get_skill_state(
            envelope.owner_id, tracked_skill_id
        )
    except UnsupportedRuleError as exc:
        raise SkillReplayDivergenceError(str(exc)) from exc
    actual_usage_after = {
        "uses_this_phase": final_skill_state.uses_this_phase,
        "uses_this_turn": final_skill_state.uses_this_turn,
    }
    if actual_usage_after != dict(envelope.usage_after):
        raise SkillReplayDivergenceError(f"{tracked_label} usage_after 不匹配")
    if dict(final_skill_state.marks) != dict(envelope.marks_after):
        raise SkillReplayDivergenceError(f"{tracked_label} marks_after 不匹配")
    live_runtime_after = _json_frozen(game.skill_runtime.audit_fingerprint())
    if live_runtime_after != _json_frozen(envelope.skill_runtime_after):
        raise SkillReplayDivergenceError("完整 SkillRuntime runtime_after 不匹配")
    if authority_required or envelope.production_authority_after:
        live_authority_after = _json_frozen(game._skill_audit_value() or {})
        if live_authority_after != _json_frozen(
            envelope.production_authority_after
        ):
            raise SkillReplayDivergenceError(
                "完整 production authority runtime_after 不匹配"
            )
        if envelope.production_authority_trace and live_authority_after != _json_frozen(
            envelope.production_authority_trace[-1]
        ):
            raise SkillReplayDivergenceError(
                "production authority 最终快照与逐步 trace 不一致"
            )
    if continuation_kind == "card":
        if game.pending_card_continuation_identity is not None:
            raise SkillReplayDivergenceError(
                f"{tracked_label} 决策后 card continuation 未完成消费"
            )
        if envelope.continuation_identity not in game.consumed_card_continuation_identities:
            raise SkillReplayDivergenceError(
                f"{tracked_label} card continuation 未记录为已消费"
            )
    elif continuation_kind == "skill":
        if envelope.continuation_identity not in game.consumed_skill_continuation_identities:
            raise SkillReplayDivergenceError(
                "Zuilun skill continuation 未记录为已消费"
            )
    elif continuation_kind == "permission":
        if not any(
            e.event_type is EventType.SKILL_CONDITION_EVALUATED
            and e.payload.get("continuation_identity") == envelope.continuation_identity
            for e in game.events
        ):
            raise SkillReplayDivergenceError(
                "Qianchong permission continuation 未记录在事件流中"
            )
    elif continuation_kind == "evaluation":
        if not any(
            e.event_type is EventType.SKILL_CONDITION_EVALUATED
            and e.payload.get("evaluation_identity") == envelope.continuation_identity
            for e in game.events
        ):
            raise SkillReplayDivergenceError(
                "Shangjian evaluation identity 未记录在事件流中"
            )

    actual_events = tuple(
        _json_frozen(event.to_replay_dict()) for event in game.events
    )
    if actual_events != envelope.event_slice:
        raise SkillReplayDivergenceError("事件内容或序号切片不匹配")
    if rng_calls_hash(game.rng_calls) != envelope.rng_hash:
        raise SkillReplayDivergenceError("RNG 回放不一致")
    if continuation_kind != "permission":
        trigger_event = next(
            (
                event
                for event in game.events
                if event.sequence == envelope.trigger_event_sequence
            ),
            None,
        )
        if trigger_event is None or trigger_event.event_type.value != envelope.trigger_event_type:
            raise SkillReplayDivergenceError(
                f"{tracked_label} 触发事件序号或类型不匹配"
            )
    else:
        trigger_event = next(
            (
                event
                for event in game.events
                if event.sequence == envelope.trigger_event_sequence
            ),
            None,
        )
        if trigger_event is None:
            raise SkillReplayDivergenceError(
                f"{tracked_label} 触发事件序号不匹配"
            )
    if continuation_kind == "target_effect":
        if envelope.owner_id not in trigger_event.target_ids:
            raise SkillReplayDivergenceError("Fuyin 触发根未以 owner_id 为目标")
        condition_events = tuple(
            event for event in game.events
            if event.event_type is EventType.SKILL_CONDITION_EVALUATED
            and event.skill_owner == envelope.owner_id
            and event.payload.get("skill_id") == "sgs_skill_fuyin"
            and event.payload.get("source_event_sequence")
            == envelope.trigger_event_sequence
        )
        if len(condition_events) != 1:
            raise SkillReplayDivergenceError("Fuyin 机会消费/条件判定事件必须恰好一条")
        condition_event = condition_events[0]
        if condition_event.payload.get("resolution_identity") != envelope.continuation_identity:
            raise SkillReplayDivergenceError("Fuyin resolution_identity 不匹配")
        if (
            condition_event.payload.get("consumed_before") is not False
            or condition_event.payload.get("consumed_after") is not True
        ):
            raise SkillReplayDivergenceError("Fuyin 机会消费事实不匹配")
        ineffective = condition_event.payload.get("target_effect_ineffective")
        if type(ineffective) is not bool:
            raise SkillReplayDivergenceError("Fuyin ineffective 结果必须是 exact bool")
        target_events = tuple(
            event for event in game.events
            if event.event_type is EventType.TARGET_EFFECT_INEFFECTIVE
            and event.skill_owner == envelope.owner_id
            and event.payload.get("source_event_sequence")
            == envelope.trigger_event_sequence
        )
        if len(target_events) != int(ineffective):
            raise SkillReplayDivergenceError(
                "Fuyin TARGET_EFFECT_INEFFECTIVE 与条件结果不一致"
            )
        if target_events and (
            target_events[0].payload.get("resolution_identity")
            != envelope.continuation_identity
        ):
            raise SkillReplayDivergenceError("Fuyin ineffective 事件身份不匹配")

    return SkillReplayVerificationResult(
        verified=True,
        steps_verified=steps_verified,
        registry_identity_matched=True,
        state_hashes_matched=True,
        details=f"生产武将回放验证通过，共 {steps_verified} 步",
    )
