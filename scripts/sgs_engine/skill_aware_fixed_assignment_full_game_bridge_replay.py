# -*- coding: utf-8 -*-
"""BRIDGE-D independent replay authority and canonical strict reexecution.

This module intentionally does not wrap any legacy production, no-skill, or
General replay envelope.  A Bridge replay is rebuilt only through the
canonical fixed-assignment Bridge factory and the BRIDGE-C public controller.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import json
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from .engine import canonical_state_snapshot
from .formal_duel import implementation_identity, rules_profile_identity
from .replay import canonical_json, sha256_value, state_sha256
from .model import PROCESSING_ZONE, REVEALED_ZONE
from .production_batch import ProductionBatchFinishedError, ProductionPhase
from .skill_aware_fixed_assignment_full_game_bridge import (
    BASELINE_18,
    BRIDGE_AUTHORITY_PROFILE_IDENTITY,
    BRIDGE_MODE_PROFILE_IDENTITY,
    BRIDGE_SKILL_REGISTRY_IDENTITY,
    CONTRACT_ID,
    CONTROLLER_ID,
    CONTROLLER_VERSION,
    DECK_IDENTITY,
    DYNAMIC_DERIVATION_AUTHORITY,
    FORMAL_DUEL_PROFILE_IDENTITY,
    GENERAL_REGISTRY_IDENTITY,
    INITIALIZATION_SEQUENCE,
    INITIALIZATION_SEQUENCE_IDENTITY,
    MAX_STEPS,
    MODE_ID,
    PARTICIPANT_IDS,
    PRIVATE_SELECTION_ALLOWED_FIELDS,
    PRIVATE_SELECTION_FORBIDDEN_FIELDS,
    PROPOSED_BRIDGE_CONTRACT_IDENTITY,
    REPLAY_SCHEMA,
    REPLAY_VERSION,
    BridgeAssignmentDescriptor,
    BridgeContractError,
    BridgeIdentityError,
    ControllerActionProjectionV1,
    FixedAssignment,
    PublicLegalActionProjectionV1,
    PublicOpaqueChoiceProjection,
    SkillAwareFixedAssignmentAcceptanceControllerV1,
    SkillAwareFixedAssignmentDuelSessionV1,
    _BRIDGE_STRICT_REPLAY_RECONSTRUCTION_CAPABILITY,
    _create_skill_aware_fixed_assignment_duel_session_for_strict_replay_v1,
    create_bridge_assignment,
    create_controller_decision_record_v1,
    create_skill_aware_fixed_assignment_duel_session_v1,
    general_descriptor,
)


BRIDGE_REPLAY_CAPABILITY_V1 = "BRIDGE_FULL_GAME_REPLAY_V1"
AUTHORITATIVE_PRIVATE_SCHEMA_V1 = "bridge-authoritative-private-v1"
AUTHORITATIVE_PRIVATE_VERSION_V1 = 1


class BridgeReplayDivergenceError(BridgeContractError):
    """Cold parsing or live strict reexecution diverged from the record."""


class BridgeReplayIdentityError(BridgeIdentityError):
    """A current implementation or frozen authority identity drifted."""


class BridgeTraceScope(str, Enum):
    BOUNDED_PRODUCTION_TRACE = "BOUNDED_PRODUCTION_TRACE"
    NATURAL_FULL_GAME = "NATURAL_FULL_GAME"


BRIDGE_FULL_GAME_REPLAY_REQUIRED_FIELDS_V1 = frozenset(
    {
        "schema",
        "replay_version",
        "trace_scope",
        "authority_capability",
        "contract_id",
        "contract_identity",
        "implementation_identity",
        "ruleset_identity",
        "mode_id",
        "bridge_mode_profile_identity",
        "formal_duel_profile_identity",
        "deck_identity",
        "general_registry_identity",
        "bridge_skill_registry_identity",
        "bridge_authority_profile_identity",
        "controller_id",
        "controller_version",
        "cell_id",
        "seed",
        "initialization",
        "decisions",
        "random_consumptions",
        "events",
        "production_authority_trace",
        "skill_decision_authority_trace",
        "outcome",
        "authoritative_private",
        "records_identity",
        "execution_identity",
        "replay_identity",
    }
)

_INITIALIZATION_FIELDS = frozenset(
    {
        "initialization_sequence_identity",
        "initialization_sequence",
        "participant_ids",
        "assignment",
        "assignment_identity",
        "general_semantic_payload",
        "mode_modifier_identity",
        "base_skill_derivation",
        "dynamic_derivation_policy",
        "initial_dynamic_reconcile_result",
        "initial_skill_runtime_identity",
        "first_player_id",
        "initial_hand_counts",
        "initial_public_state_commitment",
        "initial_authoritative_state_hash",
        "initial_execution_identity",
        "initial_rng_authority",
        "analysis_only",
        "fixture_applied",
        "premutation_applied",
        "manual_event_injection",
    }
)
_INITIAL_RNG_FIELDS = frozenset(
    {
        "seed_state",
        "seed_state_identity",
        "post_initialization_state",
        "post_initialization_state_identity",
        "post_initialization_call_count",
    }
)
_BASE_SKILL_FIELDS = frozenset(
    {
        "general_player_id",
        "general_key",
        "base_skill_ids",
        "no_skill_player_id",
        "no_skill_base_skill_ids",
    }
)
_DYNAMIC_RECONCILE_FIELDS = frozenset(
    {"player_effective_skills", "dynamic_grants", "runtime_identity"}
)
_DECISION_FIELDS = frozenset(
    {
        "step_index",
        "state_revision_before",
        "execution_revision_before",
        "public_context",
        "public_context_identity",
        "legal_action_projections",
        "legal_set_identity",
        "chosen_action_id",
        "chosen_semantic_projection",
        "controller_id",
        "controller_version",
        "state_identity_before",
        "state_identity_after",
        "execution_identity_before",
        "execution_identity_after",
        "rng_start_index",
        "rng_end_index",
        "event_start_index",
        "event_end_index",
        "authority_identity_before",
        "authority_identity_after",
    }
)
_RANDOM_FIELDS = frozenset(
    {
        "index",
        "operation",
        "domain",
        "result",
        "before_call_index",
        "after_call_index",
    }
)
_PRODUCTION_TRACE_FIELDS = frozenset(
    {
        "step_index",
        "state_identity_before",
        "state_identity_after",
        "execution_identity_before",
        "execution_identity_after",
        "state_revision_before",
        "state_revision_after",
        "execution_revision_before",
        "execution_revision_after",
        "legal_set_identity",
        "rng_authority_before",
        "rng_authority_after",
        "event_range",
        "runtime_identity_before",
        "runtime_identity_after",
        "continuation_identity_before",
        "continuation_identity_after",
        "mode_outcome_identity_before",
        "mode_outcome_identity_after",
        "movement_ledger_end_identity_before",
        "movement_ledger_end_identity_after",
        "authority_identity_before",
        "authority_identity_after",
    }
)
_SKILL_TRACE_FIELDS = frozenset(
    {
        "step_index",
        "skill_id",
        "owner_id",
        "window_kind",
        "root_identity",
        "continuation_identity",
        "queue_ordinal",
        "public_projection",
        "chosen_signed_action",
        "runtime_identity_before",
        "runtime_identity_after",
    }
)
_OUTCOME_FIELDS = frozenset(
    {"finished", "winner", "finish_reason", "trace_scope", "step_count", "turn_count"}
)
_PRIVATE_FIELDS = frozenset(
    {
        "schema",
        "version",
        "participant_ids",
        "signing_authority",
        "initial_private_state",
        "final_private_state",
        "private_skill_selections",
    }
)
_SIGNING_AUTHORITY_FIELDS = frozenset(
    {"session_id", "session_secret_hex", "signing_authority_identity"}
)
_PRIVATE_STATE_FIELDS = frozenset(
    {"participant_hands", "draw_pile_order", "private_state_identity"}
)
_PRIVATE_HAND_FIELDS = frozenset({"participant_id", "card_instance_ids"})
_PRIVATE_SELECTION_FIELDS = frozenset(
    {
        "step_index",
        "participant_id",
        "action_id",
        "observed_card_ids",
        "selected_card_ids",
        "remaining_top_order",
        "choose_count",
        "condition_facts",
    }
)
_PROJECTION_WRAPPER_FIELDS = frozenset({"projection_kind", "projection"})
_EVENT_REQUIRED_FIELDS = frozenset(
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


def _exact_dict(value: object, label: str) -> dict[str, Any]:
    if type(value) is not dict:
        raise BridgeReplayDivergenceError(f"{label}必须是精确JSON object")
    if any(type(key) is not str for key in value):
        raise BridgeReplayDivergenceError(f"{label}字段名必须是字符串")
    return value


def _exact_fields(data: Mapping[str, object], fields: frozenset[str], label: str) -> None:
    actual = frozenset(data)
    if actual != fields:
        missing = sorted(fields - actual)
        extra = sorted(actual - fields)
        raise BridgeReplayDivergenceError(
            f"{label}字段必须精确匹配；missing={missing}, extra={extra}"
        )


def _text(value: object, label: str) -> str:
    if type(value) is not str or not value:
        raise BridgeReplayDivergenceError(f"{label}必须是非空字符串")
    return value


def _integer(value: object, label: str, *, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise BridgeReplayDivergenceError(f"{label}必须是不小于{minimum}的整数")
    return value


def _boolean(value: object, label: str) -> bool:
    if type(value) is not bool:
        raise BridgeReplayDivergenceError(f"{label}必须是boolean")
    return value


def _sha256(value: object, label: str) -> str:
    text = _text(value, label)
    if len(text) != 64 or any(char not in "0123456789abcdef" for char in text):
        raise BridgeReplayDivergenceError(f"{label}必须是小写SHA-256")
    return text


def _json_plain(value: object) -> object:
    try:
        return json.loads(canonical_json(value))
    except (TypeError, ValueError) as exc:
        raise BridgeReplayDivergenceError("replay包含非canonical JSON值") from exc


def _freeze(value: object) -> object:
    if type(value) is dict:
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if type(value) is list:
        return tuple(_freeze(item) for item in value)
    return value


def _plain(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_plain(item) for item in value]
    return value


def _json_object(value: object, label: str) -> dict[str, Any]:
    plain = _json_plain(value)
    return _exact_dict(plain, label)


def _json_array(value: object, label: str) -> list[object]:
    plain = _json_plain(value)
    if type(plain) is not list:
        raise BridgeReplayDivergenceError(f"{label}必须是精确JSON array")
    return plain


def _projection_to_value(action: ControllerActionProjectionV1) -> dict[str, object]:
    if type(action) is PublicLegalActionProjectionV1:
        kind = "public_gameplay_action"
    elif type(action) is PublicOpaqueChoiceProjection:
        kind = "private_player_choice"
    else:
        raise BridgeReplayDivergenceError("未知controller projection类型")
    return {"projection_kind": kind, "projection": action.to_dict()}


def _projection_from_value(value: object) -> ControllerActionProjectionV1:
    data = _exact_dict(value, "controller projection")
    _exact_fields(data, _PROJECTION_WRAPPER_FIELDS, "controller projection")
    kind = _text(data["projection_kind"], "projection_kind")
    if kind == "public_gameplay_action":
        return PublicLegalActionProjectionV1.from_dict(data["projection"])
    if kind == "private_player_choice":
        return PublicOpaqueChoiceProjection.from_dict(data["projection"])
    raise BridgeReplayDivergenceError("未知projection_kind")


def bridge_current_contract_latch_v1(value: object) -> bool:
    """Latch current Bridge material before any legacy parser can be considered."""

    if type(value) is not dict:
        return False
    data = value
    direct_markers = (
        data.get("schema") == REPLAY_SCHEMA,
        data.get("contract_id") == CONTRACT_ID,
        data.get("mode_id") == MODE_ID,
        data.get("controller_id") == CONTROLLER_ID,
        data.get("authority_capability") == BRIDGE_REPLAY_CAPABILITY_V1,
        data.get("trace_scope") in {item.value for item in BridgeTraceScope},
        "bridge_mode_profile_identity" in data,
        "bridge_skill_registry_identity" in data,
        "bridge_authority_profile_identity" in data,
    )
    initialization = data.get("initialization")
    assignment_marker = (
        type(initialization) is dict and "assignment" in initialization
    )
    version_marker = data.get("replay_version") == REPLAY_VERSION
    return any(direct_markers) or assignment_marker or version_marker


def _validate_projection_wrapper(value: object, label: str) -> None:
    try:
        _projection_from_value(value)
    except (BridgeContractError, TypeError, ValueError) as exc:
        raise BridgeReplayDivergenceError(f"{label}不是合法public projection") from exc


def _validate_initialization(value: object) -> None:
    data = _exact_dict(value, "initialization")
    _exact_fields(data, _INITIALIZATION_FIELDS, "initialization")
    _sha256(data["initialization_sequence_identity"], "initialization_sequence_identity")
    if type(data["initialization_sequence"]) is not list:
        raise BridgeReplayDivergenceError("initialization_sequence必须是array")
    if type(data["participant_ids"]) is not list:
        raise BridgeReplayDivergenceError("participant_ids必须是array")
    try:
        BridgeAssignmentDescriptor.from_dict(data["assignment"])
    except (BridgeContractError, TypeError, ValueError) as exc:
        raise BridgeReplayDivergenceError(
            "initialization assignment不是canonical Bridge authority"
        ) from exc
    _sha256(data["assignment_identity"], "assignment_identity")
    _exact_dict(data["general_semantic_payload"], "general_semantic_payload")
    _text(data["mode_modifier_identity"], "mode_modifier_identity")
    base = _exact_dict(data["base_skill_derivation"], "base_skill_derivation")
    _exact_fields(base, _BASE_SKILL_FIELDS, "base_skill_derivation")
    dynamic = _exact_dict(data["initial_dynamic_reconcile_result"], "initial_dynamic_reconcile_result")
    _exact_fields(dynamic, _DYNAMIC_RECONCILE_FIELDS, "initial_dynamic_reconcile_result")
    _exact_dict(data["dynamic_derivation_policy"], "dynamic_derivation_policy")
    _sha256(data["initial_skill_runtime_identity"], "initial_skill_runtime_identity")
    _text(data["first_player_id"], "first_player_id")
    _exact_dict(data["initial_hand_counts"], "initial_hand_counts")
    for field in (
        "initial_public_state_commitment",
        "initial_authoritative_state_hash",
        "initial_execution_identity",
    ):
        _sha256(data[field], field)
    rng = _exact_dict(data["initial_rng_authority"], "initial_rng_authority")
    _exact_fields(rng, _INITIAL_RNG_FIELDS, "initial_rng_authority")
    _exact_dict(rng["seed_state"], "seed_state")
    _sha256(rng["seed_state_identity"], "seed_state_identity")
    _exact_dict(rng["post_initialization_state"], "post_initialization_state")
    _sha256(rng["post_initialization_state_identity"], "post_initialization_state_identity")
    _integer(rng["post_initialization_call_count"], "post_initialization_call_count")
    for field in (
        "analysis_only",
        "fixture_applied",
        "premutation_applied",
        "manual_event_injection",
    ):
        if _boolean(data[field], field):
            raise BridgeReplayDivergenceError(f"Bridge replay拒绝{field}=true")


def _validate_decision(value: object, index: int) -> None:
    data = _exact_dict(value, f"decisions[{index}]")
    _exact_fields(data, _DECISION_FIELDS, f"decisions[{index}]")
    if _integer(data["step_index"], "step_index") != index:
        raise BridgeReplayDivergenceError("decision step_index必须连续")
    for field in (
        "state_revision_before",
        "execution_revision_before",
        "rng_start_index",
        "rng_end_index",
        "event_start_index",
        "event_end_index",
    ):
        _integer(data[field], field)
    from .skill_aware_fixed_assignment_full_game_bridge import PublicActionContextV1

    PublicActionContextV1.from_dict(data["public_context"])
    for field in (
        "public_context_identity",
        "legal_set_identity",
        "state_identity_before",
        "state_identity_after",
        "execution_identity_before",
        "execution_identity_after",
        "authority_identity_before",
        "authority_identity_after",
    ):
        _sha256(data[field], field)
    projections = data["legal_action_projections"]
    if type(projections) is not list or not projections:
        raise BridgeReplayDivergenceError("legal_action_projections必须是非空array")
    for projection in projections:
        _validate_projection_wrapper(projection, "legal_action_projection")
    _validate_projection_wrapper(data["chosen_semantic_projection"], "chosen_semantic_projection")
    _text(data["chosen_action_id"], "chosen_action_id")
    if data["controller_id"] != CONTROLLER_ID or data["controller_version"] != CONTROLLER_VERSION:
        raise BridgeReplayDivergenceError("decision controller identity不匹配")


def _validate_random(value: object, index: int) -> None:
    data = _exact_dict(value, f"random_consumptions[{index}]")
    _exact_fields(data, _RANDOM_FIELDS, f"random_consumptions[{index}]")
    if _integer(data["index"], "random index") != index:
        raise BridgeReplayDivergenceError("random consumption index不连续")
    _text(data["operation"], "random operation")
    _exact_dict(data["domain"], "random domain")
    if _integer(data["before_call_index"], "before_call_index") != index:
        raise BridgeReplayDivergenceError("random before_call_index不匹配")
    if _integer(data["after_call_index"], "after_call_index") != index + 1:
        raise BridgeReplayDivergenceError("random after_call_index不匹配")
    _json_plain(data["result"])


def _validate_event(value: object, index: int) -> None:
    data = _exact_dict(value, f"events[{index}]")
    if not _EVENT_REQUIRED_FIELDS <= frozenset(data):
        raise BridgeReplayDivergenceError("event缺少canonical authority字段")
    sequence = _integer(data["sequence"], "event sequence", minimum=1)
    if sequence != index + 1:
        raise BridgeReplayDivergenceError("event sequence必须从1连续递增")
    _text(data["event_type"], "event_type")
    _exact_dict(data["payload"], "event payload")


def _validate_production_trace(value: object, index: int) -> None:
    data = _exact_dict(value, f"production_authority_trace[{index}]")
    _exact_fields(data, _PRODUCTION_TRACE_FIELDS, f"production_authority_trace[{index}]")
    if _integer(data["step_index"], "trace step_index") != index:
        raise BridgeReplayDivergenceError("production trace step_index必须连续")
    for field in _PRODUCTION_TRACE_FIELDS - {
        "step_index",
        "state_revision_before",
        "state_revision_after",
        "execution_revision_before",
        "execution_revision_after",
        "rng_authority_before",
        "rng_authority_after",
        "event_range",
    }:
        _sha256(data[field], field)
    for field in (
        "state_revision_before",
        "state_revision_after",
        "execution_revision_before",
        "execution_revision_after",
    ):
        _integer(data[field], field)
    for field in ("rng_authority_before", "rng_authority_after", "event_range"):
        _exact_dict(data[field], field)


def _validate_skill_trace(value: object, index: int) -> None:
    data = _exact_dict(value, f"skill_decision_authority_trace[{index}]")
    _exact_fields(data, _SKILL_TRACE_FIELDS, f"skill_decision_authority_trace[{index}]")
    _integer(data["step_index"], "skill trace step_index")
    _text(data["skill_id"], "skill_id")
    _text(data["owner_id"], "owner_id")
    _text(data["window_kind"], "window_kind")
    for field in (
        "root_identity",
        "continuation_identity",
        "runtime_identity_before",
        "runtime_identity_after",
    ):
        _sha256(data[field], field)
    _integer(data["queue_ordinal"], "queue_ordinal")
    _validate_projection_wrapper(data["public_projection"], "skill public_projection")
    chosen = _exact_dict(data["chosen_signed_action"], "chosen_signed_action")
    _exact_fields(chosen, frozenset({"action_id", "operation", "action_type"}), "chosen_signed_action")


def _validate_outcome(value: object, scope: BridgeTraceScope) -> None:
    data = _exact_dict(value, "outcome")
    _exact_fields(data, _OUTCOME_FIELDS, "outcome")
    finished = _boolean(data["finished"], "outcome.finished")
    if data["winner"] is not None:
        _text(data["winner"], "outcome.winner")
    if data["finish_reason"] is not None:
        _text(data["finish_reason"], "outcome.finish_reason")
    if data["trace_scope"] != scope.value:
        raise BridgeReplayDivergenceError("outcome trace_scope与top-level不一致")
    _integer(data["step_count"], "outcome.step_count")
    _integer(data["turn_count"], "outcome.turn_count")
    if scope is BridgeTraceScope.NATURAL_FULL_GAME:
        if not finished or data["finish_reason"] is None:
            raise BridgeReplayDivergenceError("NATURAL_FULL_GAME必须是真实formal terminal")
    elif not finished and (data["winner"] is not None or data["finish_reason"] is not None):
        raise BridgeReplayDivergenceError("未结束bounded trace不得伪造winner/finish_reason")


def _validate_private_state(value: object, label: str) -> None:
    data = _exact_dict(value, label)
    _exact_fields(data, _PRIVATE_STATE_FIELDS, label)
    hands = data["participant_hands"]
    if type(hands) is not list or len(hands) != len(PARTICIPANT_IDS):
        raise BridgeReplayDivergenceError(f"{label}.participant_hands不合法")
    for hand in hands:
        hand_data = _exact_dict(hand, "participant hand")
        _exact_fields(hand_data, _PRIVATE_HAND_FIELDS, "participant hand")
        _text(hand_data["participant_id"], "participant_id")
        if type(hand_data["card_instance_ids"]) is not list:
            raise BridgeReplayDivergenceError("card_instance_ids必须是array")
    if type(data["draw_pile_order"]) is not list:
        raise BridgeReplayDivergenceError("draw_pile_order必须是array")
    _sha256(data["private_state_identity"], "private_state_identity")
    material = dict(data)
    supplied = material.pop("private_state_identity")
    if supplied != sha256_value(material):
        raise BridgeReplayDivergenceError("private_state_identity不匹配")


def _validate_authoritative_private(value: object) -> None:
    data = _exact_dict(value, "authoritative_private")
    _exact_fields(data, _PRIVATE_FIELDS, "authoritative_private")
    if data["schema"] != AUTHORITATIVE_PRIVATE_SCHEMA_V1:
        raise BridgeReplayDivergenceError("authoritative_private schema不匹配")
    if data["version"] != AUTHORITATIVE_PRIVATE_VERSION_V1:
        raise BridgeReplayDivergenceError("authoritative_private version不匹配")
    if data["participant_ids"] != list(PARTICIPANT_IDS):
        raise BridgeReplayDivergenceError("authoritative_private participant scope不匹配")
    signing = _exact_dict(data["signing_authority"], "signing_authority")
    _exact_fields(signing, _SIGNING_AUTHORITY_FIELDS, "signing_authority")
    _text(signing["session_id"], "session_id")
    secret = _text(signing["session_secret_hex"], "session_secret_hex")
    if len(secret) < 64 or len(secret) % 2 or any(
        char not in "0123456789abcdef" for char in secret
    ):
        raise BridgeReplayDivergenceError("session_secret_hex必须是至少256位小写十六进制")
    supplied_signing_identity = _sha256(
        signing["signing_authority_identity"], "signing_authority_identity"
    )
    if supplied_signing_identity != sha256_value(
        {"session_id": signing["session_id"], "session_secret_hex": secret}
    ):
        raise BridgeReplayDivergenceError("signing_authority_identity不匹配")
    _validate_private_state(data["initial_private_state"], "initial_private_state")
    _validate_private_state(data["final_private_state"], "final_private_state")
    selections = data["private_skill_selections"]
    if type(selections) is not list:
        raise BridgeReplayDivergenceError("private_skill_selections必须是array")
    for item in selections:
        selection = _exact_dict(item, "private skill selection")
        _exact_fields(selection, _PRIVATE_SELECTION_FIELDS, "private skill selection")
        _integer(selection["step_index"], "private selection step_index")
        _text(selection["participant_id"], "private selection participant_id")
        _text(selection["action_id"], "private selection action_id")
        for field in ("observed_card_ids", "selected_card_ids", "remaining_top_order"):
            if type(selection[field]) is not list:
                raise BridgeReplayDivergenceError(f"{field}必须是array")
        _integer(selection["choose_count"], "choose_count")
        _exact_dict(selection["condition_facts"], "condition_facts")


def _records_material(data: Mapping[str, object]) -> dict[str, object]:
    return {
        "initialization": data["initialization"],
        "decisions": data["decisions"],
        "random_consumptions": data["random_consumptions"],
        "events": data["events"],
        "production_authority_trace": data["production_authority_trace"],
        "skill_decision_authority_trace": data["skill_decision_authority_trace"],
        "authoritative_private": data["authoritative_private"],
    }


def _execution_material(data: Mapping[str, object], records_identity: str) -> dict[str, object]:
    return {
        "schema": data["schema"],
        "replay_version": data["replay_version"],
        "trace_scope": data["trace_scope"],
        "authority_capability": data["authority_capability"],
        "contract_id": data["contract_id"],
        "contract_identity": data["contract_identity"],
        "implementation_identity": data["implementation_identity"],
        "ruleset_identity": data["ruleset_identity"],
        "mode_id": data["mode_id"],
        "bridge_mode_profile_identity": data["bridge_mode_profile_identity"],
        "formal_duel_profile_identity": data["formal_duel_profile_identity"],
        "deck_identity": data["deck_identity"],
        "general_registry_identity": data["general_registry_identity"],
        "bridge_skill_registry_identity": data["bridge_skill_registry_identity"],
        "bridge_authority_profile_identity": data["bridge_authority_profile_identity"],
        "controller_id": data["controller_id"],
        "controller_version": data["controller_version"],
        "cell_id": data["cell_id"],
        "seed": data["seed"],
        "records_identity": records_identity,
        "outcome": data["outcome"],
    }


def recompute_bridge_replay_identities_v1(value: Mapping[str, object]) -> dict[str, object]:
    """Recompute all non-keyed identity layers for adversarial test construction."""

    plain = _json_object(value, "Bridge replay")
    _exact_fields(plain, BRIDGE_FULL_GAME_REPLAY_REQUIRED_FIELDS_V1, "Bridge replay")
    records_identity = sha256_value(_records_material(plain))
    plain["records_identity"] = records_identity
    execution_identity = sha256_value(_execution_material(plain, records_identity))
    plain["execution_identity"] = execution_identity
    replay_material = dict(plain)
    replay_material.pop("replay_identity")
    plain["replay_identity"] = sha256_value(replay_material)
    return plain


@dataclass(frozen=True, slots=True)
class BridgeFullGameReplayV1:
    schema: str
    replay_version: int
    trace_scope: BridgeTraceScope
    authority_capability: str
    contract_id: str
    contract_identity: str
    implementation_identity: str
    ruleset_identity: str
    mode_id: str
    bridge_mode_profile_identity: str
    formal_duel_profile_identity: str
    deck_identity: str
    general_registry_identity: str
    bridge_skill_registry_identity: str
    bridge_authority_profile_identity: str
    controller_id: str
    controller_version: int
    cell_id: str
    seed: int
    initialization: Mapping[str, object]
    decisions: tuple[Mapping[str, object], ...]
    random_consumptions: tuple[Mapping[str, object], ...]
    events: tuple[Mapping[str, object], ...]
    production_authority_trace: tuple[Mapping[str, object], ...]
    skill_decision_authority_trace: tuple[Mapping[str, object], ...]
    outcome: Mapping[str, object]
    authoritative_private: Mapping[str, object]
    records_identity: str
    execution_identity: str
    replay_identity: str

    def __post_init__(self) -> None:
        if self.schema != REPLAY_SCHEMA:
            raise BridgeReplayDivergenceError("Bridge replay schema不匹配")
        if type(self.replay_version) is not int or self.replay_version != REPLAY_VERSION:
            raise BridgeReplayDivergenceError("Bridge replay_version不匹配")
        if type(self.trace_scope) is not BridgeTraceScope:
            raise BridgeReplayDivergenceError("trace_scope必须是exact BridgeTraceScope")
        expected_static = {
            "authority_capability": BRIDGE_REPLAY_CAPABILITY_V1,
            "contract_id": CONTRACT_ID,
            "contract_identity": PROPOSED_BRIDGE_CONTRACT_IDENTITY,
            "mode_id": MODE_ID,
            "bridge_mode_profile_identity": BRIDGE_MODE_PROFILE_IDENTITY,
            "formal_duel_profile_identity": FORMAL_DUEL_PROFILE_IDENTITY,
            "deck_identity": DECK_IDENTITY,
            "general_registry_identity": GENERAL_REGISTRY_IDENTITY,
            "bridge_skill_registry_identity": BRIDGE_SKILL_REGISTRY_IDENTITY,
            "bridge_authority_profile_identity": BRIDGE_AUTHORITY_PROFILE_IDENTITY,
            "controller_id": CONTROLLER_ID,
        }
        for field, expected in expected_static.items():
            if getattr(self, field) != expected:
                raise BridgeReplayIdentityError(f"{field}与current Bridge authority不匹配")
        if type(self.controller_version) is not int or self.controller_version != CONTROLLER_VERSION:
            raise BridgeReplayIdentityError("controller_version不匹配")
        _text(self.cell_id, "cell_id")
        _integer(self.seed, "seed")
        for field in (
            "implementation_identity",
            "ruleset_identity",
            "records_identity",
            "execution_identity",
            "replay_identity",
        ):
            _sha256(getattr(self, field), field)
        for field in (
            "initialization",
            "outcome",
            "authoritative_private",
        ):
            if not isinstance(getattr(self, field), Mapping):
                raise BridgeReplayDivergenceError(f"{field}必须是immutable mapping")
        for field in (
            "decisions",
            "random_consumptions",
            "events",
            "production_authority_trace",
            "skill_decision_authority_trace",
        ):
            if type(getattr(self, field)) is not tuple:
                raise BridgeReplayDivergenceError(f"{field}必须是tuple")
        plain = self.to_dict()
        _validate_initialization(plain["initialization"])
        for index, item in enumerate(plain["decisions"]):
            _validate_decision(item, index)
        for index, item in enumerate(plain["random_consumptions"]):
            _validate_random(item, index)
        for index, item in enumerate(plain["events"]):
            _validate_event(item, index)
        for index, item in enumerate(plain["production_authority_trace"]):
            _validate_production_trace(item, index)
        for index, item in enumerate(plain["skill_decision_authority_trace"]):
            _validate_skill_trace(item, index)
        _validate_outcome(plain["outcome"], self.trace_scope)
        _validate_authoritative_private(plain["authoritative_private"])
        if len(self.decisions) != len(self.production_authority_trace):
            raise BridgeReplayDivergenceError("decision与production authority trace长度不一致")
        recomputed = recompute_bridge_replay_identities_v1(plain)
        for field in ("records_identity", "execution_identity", "replay_identity"):
            if plain[field] != recomputed[field]:
                raise BridgeReplayIdentityError(f"{field}不匹配")

    @classmethod
    def from_dict(cls, value: object) -> "BridgeFullGameReplayV1":
        data = _exact_dict(value, "Bridge replay")
        if not bridge_current_contract_latch_v1(data):
            raise BridgeReplayDivergenceError("payload不是current Bridge replay")
        _exact_fields(data, BRIDGE_FULL_GAME_REPLAY_REQUIRED_FIELDS_V1, "Bridge replay")
        try:
            scope = BridgeTraceScope(_text(data["trace_scope"], "trace_scope"))
        except ValueError as exc:
            raise BridgeReplayDivergenceError("未知trace_scope") from exc
        list_fields = (
            "decisions",
            "random_consumptions",
            "events",
            "production_authority_trace",
            "skill_decision_authority_trace",
        )
        for field in list_fields:
            if type(data[field]) is not list:
                raise BridgeReplayDivergenceError(f"{field}必须是精确JSON array")
        object_fields = ("initialization", "outcome", "authoritative_private")
        for field in object_fields:
            _exact_dict(data[field], field)
        return cls(
            schema=_text(data["schema"], "schema"),
            replay_version=_integer(data["replay_version"], "replay_version", minimum=1),
            trace_scope=scope,
            authority_capability=_text(data["authority_capability"], "authority_capability"),
            contract_id=_text(data["contract_id"], "contract_id"),
            contract_identity=_sha256(data["contract_identity"], "contract_identity"),
            implementation_identity=_sha256(data["implementation_identity"], "implementation_identity"),
            ruleset_identity=_sha256(data["ruleset_identity"], "ruleset_identity"),
            mode_id=_text(data["mode_id"], "mode_id"),
            bridge_mode_profile_identity=_sha256(data["bridge_mode_profile_identity"], "bridge_mode_profile_identity"),
            formal_duel_profile_identity=_sha256(data["formal_duel_profile_identity"], "formal_duel_profile_identity"),
            deck_identity=_sha256(data["deck_identity"], "deck_identity"),
            general_registry_identity=_sha256(data["general_registry_identity"], "general_registry_identity"),
            bridge_skill_registry_identity=_sha256(data["bridge_skill_registry_identity"], "bridge_skill_registry_identity"),
            bridge_authority_profile_identity=_sha256(data["bridge_authority_profile_identity"], "bridge_authority_profile_identity"),
            controller_id=_text(data["controller_id"], "controller_id"),
            controller_version=_integer(data["controller_version"], "controller_version", minimum=1),
            cell_id=_text(data["cell_id"], "cell_id"),
            seed=_integer(data["seed"], "seed"),
            initialization=_freeze(_json_object(data["initialization"], "initialization")),  # type: ignore[arg-type]
            decisions=tuple(_freeze(_json_object(item, "decision")) for item in data["decisions"]),  # type: ignore[arg-type]
            random_consumptions=tuple(_freeze(_json_object(item, "random consumption")) for item in data["random_consumptions"]),  # type: ignore[arg-type]
            events=tuple(_freeze(_json_object(item, "event")) for item in data["events"]),  # type: ignore[arg-type]
            production_authority_trace=tuple(_freeze(_json_object(item, "production trace")) for item in data["production_authority_trace"]),  # type: ignore[arg-type]
            skill_decision_authority_trace=tuple(_freeze(_json_object(item, "skill trace")) for item in data["skill_decision_authority_trace"]),  # type: ignore[arg-type]
            outcome=_freeze(_json_object(data["outcome"], "outcome")),  # type: ignore[arg-type]
            authoritative_private=_freeze(_json_object(data["authoritative_private"], "authoritative_private")),  # type: ignore[arg-type]
            records_identity=_sha256(data["records_identity"], "records_identity"),
            execution_identity=_sha256(data["execution_identity"], "execution_identity"),
            replay_identity=_sha256(data["replay_identity"], "replay_identity"),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "replay_version": self.replay_version,
            "trace_scope": self.trace_scope.value,
            "authority_capability": self.authority_capability,
            "contract_id": self.contract_id,
            "contract_identity": self.contract_identity,
            "implementation_identity": self.implementation_identity,
            "ruleset_identity": self.ruleset_identity,
            "mode_id": self.mode_id,
            "bridge_mode_profile_identity": self.bridge_mode_profile_identity,
            "formal_duel_profile_identity": self.formal_duel_profile_identity,
            "deck_identity": self.deck_identity,
            "general_registry_identity": self.general_registry_identity,
            "bridge_skill_registry_identity": self.bridge_skill_registry_identity,
            "bridge_authority_profile_identity": self.bridge_authority_profile_identity,
            "controller_id": self.controller_id,
            "controller_version": self.controller_version,
            "cell_id": self.cell_id,
            "seed": self.seed,
            "initialization": _plain(self.initialization),
            "decisions": [_plain(item) for item in self.decisions],
            "random_consumptions": [_plain(item) for item in self.random_consumptions],
            "events": [_plain(item) for item in self.events],
            "production_authority_trace": [_plain(item) for item in self.production_authority_trace],
            "skill_decision_authority_trace": [_plain(item) for item in self.skill_decision_authority_trace],
            "outcome": _plain(self.outcome),
            "authoritative_private": _plain(self.authoritative_private),
            "records_identity": self.records_identity,
            "execution_identity": self.execution_identity,
            "replay_identity": self.replay_identity,
        }


def _ruleset_identity(session: object) -> str:
    binding = session.registry.binding_value(session.mode_id, session.phase.value)
    value = {
        "mode_id": session.mode_id,
        "adapter_type": str(binding["adapter_type"]),
        "ruleset_version": str(binding["adapter_version"]),
        "registry_fingerprint": str(binding["registry_fingerprint"]),
    }
    return sha256_value(value)


def _state_identity(session: object) -> str:
    return state_sha256(canonical_state_snapshot(session.state))


def _public_state_commitment(session: object) -> str:
    snapshot = canonical_state_snapshot(session.state)
    public = {
        "schema": "bridge-public-state-commitment-v1",
        "deck_id": snapshot["deck_id"],
        "revision": snapshot["revision"],
        "players": snapshot["players"],
        "zone_counts": [
            {"zone": item["zone"], "count": len(item["instance_ids"])}
            for item in snapshot["zones"]
        ],
        "first_player_id": session.first_player_id,
    }
    return sha256_value(public)


def _private_state(session: object) -> dict[str, object]:
    snapshot = canonical_state_snapshot(session.state)
    hands: list[dict[str, object]] = []
    draw_pile: list[str] | None = None
    for zone_entry in snapshot["zones"]:
        zone = zone_entry["zone"]
        if zone["kind"] == "hand":
            hands.append(
                {
                    "participant_id": zone["owner_id"],
                    "card_instance_ids": list(zone_entry["instance_ids"]),
                }
            )
        elif zone["kind"] == "draw_pile":
            draw_pile = list(zone_entry["instance_ids"])
    hands.sort(key=lambda item: str(item["participant_id"]))
    if tuple(item["participant_id"] for item in hands) != PARTICIPANT_IDS or draw_pile is None:
        raise BridgeReplayDivergenceError("canonical state缺少participant hand或draw pile")
    material = {"participant_hands": hands, "draw_pile_order": draw_pile}
    return {**material, "private_state_identity": sha256_value(material)}


def _runtime_identity(snapshot: Mapping[str, object]) -> str:
    skill = snapshot.get("skill_authority")
    if type(skill) is not dict or type(skill.get("runtime")) is not dict:
        raise BridgeReplayDivergenceError("Bridge execution snapshot缺少Skill Runtime authority")
    return sha256_value(skill["runtime"])


def _continuation_identity(snapshot: Mapping[str, object]) -> str:
    skill = snapshot.get("skill_authority")
    if type(skill) is not dict:
        raise BridgeReplayDivergenceError("Bridge execution snapshot缺少skill authority")
    return sha256_value(
        {
            "pending_skill_decision": skill.get("pending_skill_decision"),
            "pending_skill_decision_queue": skill.get("pending_skill_decision_queue"),
            "pending_card_continuation": skill.get("pending_card_continuation"),
            "pending_private_card_selection": skill.get("pending_private_card_selection"),
            "pending_skill_hp_loss": skill.get("pending_skill_hp_loss"),
            "consumed_skill_continuations": skill.get("consumed_skill_continuations"),
            "consumed_card_continuations": skill.get("consumed_card_continuations"),
            "continuation_in_progress_id": skill.get("continuation_in_progress_id"),
        }
    )


def _movement_ledger_end_identity(snapshot: Mapping[str, object]) -> str:
    skill = snapshot.get("skill_authority")
    if type(skill) is not dict:
        raise BridgeReplayDivergenceError("Bridge execution snapshot缺少movement authority")
    return sha256_value(
        {
            "turn_loss_ledger": skill.get("turn_loss_ledger"),
            "card_movement_authority": skill.get("card_movement_authority"),
            "end_phase_dispatch_state": skill.get("end_phase_dispatch_state"),
        }
    )


def _mode_outcome_identity(snapshot: Mapping[str, object]) -> str:
    runtime = snapshot.get("runtime")
    if type(runtime) is not dict:
        raise BridgeReplayDivergenceError("execution snapshot缺少runtime")
    return sha256_value(
        {
            "mode": snapshot.get("mode"),
            "outcome_policy_identity": snapshot.get("outcome_policy_identity"),
            "runtime": runtime,
            "current_actor_id": snapshot.get("current_actor_id"),
        }
    )


def _rng_authority(session: object) -> dict[str, object]:
    return {
        "call_count": session._rng.call_count,
        "state_identity": session._rng.current_state_sha256,
    }


def _initialization_value(session: object) -> dict[str, object]:
    assignment = session.assignment
    runtime = session.skill_runtime
    if runtime is None:
        raise BridgeReplayDivergenceError("Bridge session缺少Skill Runtime")
    runtime_value = runtime.audit_fingerprint()
    effective = {
        player_id: sorted(runtime.get_effective_skill_map(player_id))
        for player_id in PARTICIPANT_IDS
    }
    dynamic_grants = {
        player_id: [grant.to_dict() for grant in runtime.dynamic_grants.get(player_id, ())]
        for player_id in PARTICIPANT_IDS
    }
    private = _private_state(session)
    initial_hand_counts = {
        item["participant_id"]: len(item["card_instance_ids"])
        for item in private["participant_hands"]
    }
    seed_state = session._rng.export_initial_state()
    post_state = session._rng.export_current_state()
    general = general_descriptor(assignment.general_key)
    return {
        "initialization_sequence_identity": INITIALIZATION_SEQUENCE_IDENTITY,
        "initialization_sequence": [item.value for item in INITIALIZATION_SEQUENCE],
        "participant_ids": list(PARTICIPANT_IDS),
        "assignment": assignment.to_dict(),
        "assignment_identity": session.assignment_identity,
        "general_semantic_payload": general.to_dict(),
        "mode_modifier_identity": session.mode_modifier.value,
        "base_skill_derivation": {
            "general_player_id": assignment.general_player_id,
            "general_key": assignment.general_key,
            "base_skill_ids": list(general.base_skill_ids),
            "no_skill_player_id": assignment.no_skill_player_id,
            "no_skill_base_skill_ids": [],
        },
        "dynamic_derivation_policy": DYNAMIC_DERIVATION_AUTHORITY.to_dict(),
        "initial_dynamic_reconcile_result": {
            "player_effective_skills": effective,
            "dynamic_grants": dynamic_grants,
            "runtime_identity": sha256_value(runtime_value),
        },
        "initial_skill_runtime_identity": sha256_value(runtime_value),
        "first_player_id": session.first_player_id,
        "initial_hand_counts": initial_hand_counts,
        "initial_public_state_commitment": _public_state_commitment(session),
        "initial_authoritative_state_hash": _state_identity(session),
        "initial_execution_identity": session.execution_hash,
        "initial_rng_authority": {
            "seed_state": seed_state,
            "seed_state_identity": session._rng.initial_state_sha256,
            "post_initialization_state": post_state,
            "post_initialization_state_identity": session._rng.current_state_sha256,
            "post_initialization_call_count": session._rng.call_count,
        },
        "analysis_only": False,
        "fixture_applied": False,
        "premutation_applied": False,
        "manual_event_injection": False,
    }


def _production_trace_value(
    *,
    step_index: int,
    before_snapshot: Mapping[str, object],
    after_snapshot: Mapping[str, object],
    before_state_identity: str,
    after_state_identity: str,
    legal_set_identity: str,
    rng_before: Mapping[str, object],
    rng_after: Mapping[str, object],
    event_start: int,
    event_end: int,
) -> dict[str, object]:
    return {
        "step_index": step_index,
        "state_identity_before": before_state_identity,
        "state_identity_after": after_state_identity,
        "execution_identity_before": sha256_value(before_snapshot),
        "execution_identity_after": sha256_value(after_snapshot),
        "state_revision_before": before_snapshot["game_state"]["revision"],
        "state_revision_after": after_snapshot["game_state"]["revision"],
        "execution_revision_before": before_snapshot["step_count"],
        "execution_revision_after": after_snapshot["step_count"],
        "legal_set_identity": legal_set_identity,
        "rng_authority_before": dict(rng_before),
        "rng_authority_after": dict(rng_after),
        "event_range": {"start": event_start, "end": event_end},
        "runtime_identity_before": _runtime_identity(before_snapshot),
        "runtime_identity_after": _runtime_identity(after_snapshot),
        "continuation_identity_before": _continuation_identity(before_snapshot),
        "continuation_identity_after": _continuation_identity(after_snapshot),
        "mode_outcome_identity_before": _mode_outcome_identity(before_snapshot),
        "mode_outcome_identity_after": _mode_outcome_identity(after_snapshot),
        "movement_ledger_end_identity_before": _movement_ledger_end_identity(before_snapshot),
        "movement_ledger_end_identity_after": _movement_ledger_end_identity(after_snapshot),
        "authority_identity_before": sha256_value(before_snapshot),
        "authority_identity_after": sha256_value(after_snapshot),
    }


def _private_selection_value(step_index: int, action: object) -> dict[str, object] | None:
    if action.payload.get("operation") != "private_card_selection_submit":
        return None
    payload = action.payload
    return {
        "step_index": step_index,
        "participant_id": action.actor_id,
        "action_id": action.action_id,
        "observed_card_ids": list(payload.get("observed_card_ids") or ()),
        "selected_card_ids": list(payload.get("selected_card_ids") or ()),
        "remaining_top_order": list(payload.get("remaining_top_order") or ()),
        "choose_count": payload.get("choose_count"),
        "condition_facts": dict(payload.get("condition_facts") or {}),
    }


def _skill_trace_value(
    *,
    step_index: int,
    action: object,
    projection: Mapping[str, object],
    context: object,
    before_snapshot: Mapping[str, object],
    after_snapshot: Mapping[str, object],
) -> dict[str, object] | None:
    skill = before_snapshot["skill_authority"]
    pending = skill.get("pending_skill_decision")
    private = skill.get("pending_private_card_selection")
    hp_loss = skill.get("pending_skill_hp_loss")
    skill_id = action.skill_id
    owner_id = action.actor_id
    authority: Mapping[str, object] | None = None
    if type(pending) is dict:
        authority = pending
        skill_id = skill_id or pending.get("skill_id")
        owner_id = pending.get("actor_id") or owner_id
    elif type(private) is dict:
        authority = private
        skill_id = skill_id or private.get("skill_id")
        owner_id = private.get("actor_id") or owner_id
    elif type(hp_loss) is dict:
        authority = hp_loss
        skill_id = skill_id or hp_loss.get("skill_id")
        owner_id = hp_loss.get("owner_id") or owner_id
    if type(skill_id) is not str or not skill_id:
        return None
    continuation = None if authority is None else authority.get("continuation_id")
    root = None
    if authority is not None:
        root = authority.get("decision_window_id") or authority.get("window_id") or continuation
    root_value = {
        "skill_id": skill_id,
        "owner_id": owner_id,
        "root": root,
        "response_window_id": context.response_window_id,
    }
    continuation_value = {
        "skill_id": skill_id,
        "continuation": continuation,
        "root": root,
    }
    queue = skill.get("pending_skill_decision_queue") or []
    queue_ordinal = 0
    if type(queue) is list and authority in queue:
        queue_ordinal = queue.index(authority)
    return {
        "step_index": step_index,
        "skill_id": skill_id,
        "owner_id": owner_id,
        "window_kind": context.phase,
        "root_identity": sha256_value(root_value),
        "continuation_identity": sha256_value(continuation_value),
        "queue_ordinal": queue_ordinal,
        "public_projection": dict(projection),
        "chosen_signed_action": {
            "action_id": action.action_id,
            "operation": action.payload.get("operation"),
            "action_type": action.action_type.value,
        },
        "runtime_identity_before": _runtime_identity(before_snapshot),
        "runtime_identity_after": _runtime_identity(after_snapshot),
    }


def _random_values(session: object) -> list[dict[str, object]]:
    return [
        {
            "index": call.index,
            "operation": call.method,
            "domain": call.to_dict()["arguments"],
            "result": call.to_dict()["result"],
            "before_call_index": call.index,
            "after_call_index": call.index + 1,
        }
        for call in session.rng_calls
    ]


def _outcome_value(session: object, scope: BridgeTraceScope) -> dict[str, object]:
    finished = session.is_finished
    reason = session._resolve_public_finish_reason() if finished else None
    return {
        "finished": finished,
        "winner": session.winner_id if finished else None,
        "finish_reason": reason,
        "trace_scope": scope.value,
        "step_count": session.step_count,
        "turn_count": session.runtime.turn_number,
    }


def _canonical_bounded_cell_id(
    assignment: BridgeAssignmentDescriptor, seed: int
) -> str:
    seat = "P1" if assignment.seat_assignment is FixedAssignment.GENERAL_AS_P1 else "P2"
    return f"BRIDGE-D-{assignment.general_key.upper()}-{seat}-SEED-{seed}"


def _assert_natural_full_game_pristine_recording_authority(
    session: object,
    *,
    seed: int,
    cell_id: str,
    max_steps: int,
    require_terminal: bool,
) -> None:
    """BRIDGE-E-AUDIT-002 remediation：NATURAL recording construction fail-closed。

    一个带 NATURAL_FULL_GAME 标签的 artifact 只能同时满足：

    1. ``require_terminal`` 精确为 True（必须跑到真实 formal terminal）；
    2. ``max_steps`` 精确为 frozen ``MAX_STEPS``（2000，拒绝 bool 伪装）；
    3. session 是 canonical Bridge session 类型（拒绝 duck-typed 替身）；
    4. session 仍处于 pristine canonical initialization state——这里复用
       session 构造结束时签署的 initialization/state/execution authority 做
       比对，而不是只看 ``step_count == 0``：任何推进、事件、RNG 消耗、
       phase/runtime/skill mutation 都会改变 execution authority；
    5. caller seed 必须是整数且与 canonical session 自身 RNG seed 一致，
       cell_id 必须能由 session 当前的 General/seat/seed 经 frozen
       BASELINE_18 authority 独立复现，不信任 caller 传入的 serialized
       cell_id。

    任一条件不满足都在 construction layer 直接拒绝，不产生 artifact。
    """

    if type(require_terminal) is not bool or require_terminal is not True:
        raise BridgeReplayDivergenceError(
            "NATURAL_FULL_GAME recording必须要求真实formal terminal"
            "（require_terminal必须精确为True）"
        )
    if type(max_steps) is not int or isinstance(max_steps, bool) or (
        max_steps != MAX_STEPS
    ):
        raise BridgeReplayDivergenceError(
            f"NATURAL_FULL_GAME recording的max_steps必须精确为{MAX_STEPS}"
        )
    if type(session) is not SkillAwareFixedAssignmentDuelSessionV1:
        raise BridgeReplayDivergenceError(
            "NATURAL_FULL_GAME recording必须使用canonical Bridge session"
        )
    if session.initialization_trace != INITIALIZATION_SEQUENCE:
        raise BridgeReplayDivergenceError(
            "NATURAL_FULL_GAME recording要求canonical initialization sequence完整"
        )
    if session.step_count != 0:
        raise BridgeReplayDivergenceError(
            "NATURAL_FULL_GAME recording要求session从未被推进（step_count必须为0）"
        )
    if _state_identity(session) != session.initial_state_identity:
        raise BridgeReplayDivergenceError(
            "NATURAL_FULL_GAME recording要求session仍处于pristine canonical "
            "initialization state：current state identity与签署的initial "
            "state identity不一致"
        )
    if session.execution_hash != session.initial_execution_identity:
        raise BridgeReplayDivergenceError(
            "NATURAL_FULL_GAME recording要求session仍处于pristine canonical "
            "initialization state：execution authority已偏离签署的initial "
            "execution identity"
        )
    if session.is_finished:
        raise BridgeReplayDivergenceError(
            "NATURAL_FULL_GAME recording不接受已finished的session"
        )
    if type(seed) is not int or isinstance(seed, bool) or session._rng.seed != seed:
        raise BridgeReplayDivergenceError(
            "NATURAL_FULL_GAME recording的seed必须与canonical session RNG seed一致"
        )
    canonical_cell_id = _canonical_full_game_cell_id(session.assignment, seed)
    if type(cell_id) is not str or cell_id != canonical_cell_id:
        raise BridgeReplayDivergenceError(
            "NATURAL_FULL_GAME recording的cell_id必须由当前General/seat/seed经"
            f"frozen BASELINE_18 authority canonical派生（期望{canonical_cell_id}）"
        )


def _record_bridge_replay_core(
    session: object,
    *,
    seed: int,
    scope: BridgeTraceScope,
    cell_id: str,
    max_steps: int,
    require_terminal: bool,
) -> BridgeFullGameReplayV1:
    """Drive one real Bridge trace through the BRIDGE-C public controller.

    Shared by bounded and natural full-game recording; only the trace scope,
    the canonical cell id and the formal-terminal requirement differ.  The loop
    never fabricates a terminal: a natural full game must reach a real formal
    terminal within ``max_steps`` or the cell fails closed.
    """

    if scope is BridgeTraceScope.NATURAL_FULL_GAME:
        # BRIDGE-E-AUDIT-002 remediation：construction layer fail-closed，
        # 禁止内部误用把已推进/非 pristine session 录成带 NATURAL 标签的中局
        # artifact。BOUNDED recording workflow 不经过本守卫，行为保持不变。
        _assert_natural_full_game_pristine_recording_authority(
            session,
            seed=seed,
            cell_id=cell_id,
            max_steps=max_steps,
            require_terminal=require_terminal,
        )
    initialization = _initialization_value(session)
    ruleset_identity = _ruleset_identity(session)
    initial_private_state = _private_state(session)
    decisions: list[dict[str, object]] = []
    production_trace: list[dict[str, object]] = []
    skill_trace: list[dict[str, object]] = []
    private_selections: list[dict[str, object]] = []
    while not session.is_finished and len(decisions) < max_steps:
        step_index = len(decisions)
        context = session._context()
        legal = session.legal_actions()
        public_context, projections = session.public_action_surface_v1()
        decision_record = create_controller_decision_record_v1(public_context, projections)
        chosen_index = next(
            index
            for index, action in enumerate(legal)
            if action.action_id == decision_record.chosen_action_id
        )
        chosen = legal[chosen_index]
        chosen_projection = _projection_to_value(projections[chosen_index])
        before_snapshot = session.execution_snapshot
        before_state = _state_identity(session)
        rng_before = _rng_authority(session)
        event_start = len(session.events)
        executed = session.step(decision_record.chosen_action_id)
        if executed.action_id != decision_record.chosen_action_id:
            raise BridgeReplayDivergenceError("production step未执行controller signed action")
        after_snapshot = session.execution_snapshot
        after_state = _state_identity(session)
        rng_after = _rng_authority(session)
        event_end = len(session.events)
        projections_value = [_projection_to_value(item) for item in projections]
        authority = _production_trace_value(
            step_index=step_index,
            before_snapshot=before_snapshot,
            after_snapshot=after_snapshot,
            before_state_identity=before_state,
            after_state_identity=after_state,
            legal_set_identity=decision_record.legal_action_set_identity,
            rng_before=rng_before,
            rng_after=rng_after,
            event_start=event_start,
            event_end=event_end,
        )
        decisions.append(
            {
                "step_index": step_index,
                "state_revision_before": before_snapshot["game_state"]["revision"],
                "execution_revision_before": before_snapshot["step_count"],
                "public_context": public_context.to_dict(),
                "public_context_identity": decision_record.public_context_identity,
                "legal_action_projections": projections_value,
                "legal_set_identity": decision_record.legal_action_set_identity,
                "chosen_action_id": decision_record.chosen_action_id,
                "chosen_semantic_projection": chosen_projection,
                "controller_id": CONTROLLER_ID,
                "controller_version": CONTROLLER_VERSION,
                "state_identity_before": before_state,
                "state_identity_after": after_state,
                "execution_identity_before": sha256_value(before_snapshot),
                "execution_identity_after": sha256_value(after_snapshot),
                "rng_start_index": rng_before["call_count"],
                "rng_end_index": rng_after["call_count"],
                "event_start_index": event_start,
                "event_end_index": event_end,
                "authority_identity_before": sha256_value(before_snapshot),
                "authority_identity_after": sha256_value(after_snapshot),
            }
        )
        production_trace.append(authority)
        private_selection = _private_selection_value(step_index, chosen)
        if private_selection is not None:
            private_selections.append(private_selection)
        skill = _skill_trace_value(
            step_index=step_index,
            action=chosen,
            projection=chosen_projection,
            context=context,
            before_snapshot=before_snapshot,
            after_snapshot=after_snapshot,
        )
        if skill is not None:
            skill_trace.append(skill)
    authoritative_private = {
        "schema": AUTHORITATIVE_PRIVATE_SCHEMA_V1,
        "version": AUTHORITATIVE_PRIVATE_VERSION_V1,
        "participant_ids": list(PARTICIPANT_IDS),
        "signing_authority": {
            "session_id": session.session_id,
            "session_secret_hex": session.session_secret_hex,
            "signing_authority_identity": sha256_value(
                {
                    "session_id": session.session_id,
                    "session_secret_hex": session.session_secret_hex,
                }
            ),
        },
        "initial_private_state": initial_private_state,
        "final_private_state": _private_state(session),
        "private_skill_selections": private_selections,
    }
    if require_terminal and not session.is_finished:
        raise BridgeReplayDivergenceError(
            "NATURAL_FULL_GAME必须在max_steps内到达真实formal terminal；"
            "CELL FAILED，不得换seed、不得人工收尾、不得伪造terminal"
        )
    material: dict[str, object] = {
        "schema": REPLAY_SCHEMA,
        "replay_version": REPLAY_VERSION,
        "trace_scope": scope.value,
        "authority_capability": BRIDGE_REPLAY_CAPABILITY_V1,
        "contract_id": CONTRACT_ID,
        "contract_identity": PROPOSED_BRIDGE_CONTRACT_IDENTITY,
        "implementation_identity": implementation_identity(),
        "ruleset_identity": ruleset_identity,
        "mode_id": MODE_ID,
        "bridge_mode_profile_identity": BRIDGE_MODE_PROFILE_IDENTITY,
        "formal_duel_profile_identity": FORMAL_DUEL_PROFILE_IDENTITY,
        "deck_identity": DECK_IDENTITY,
        "general_registry_identity": GENERAL_REGISTRY_IDENTITY,
        "bridge_skill_registry_identity": BRIDGE_SKILL_REGISTRY_IDENTITY,
        "bridge_authority_profile_identity": BRIDGE_AUTHORITY_PROFILE_IDENTITY,
        "controller_id": CONTROLLER_ID,
        "controller_version": CONTROLLER_VERSION,
        "cell_id": cell_id,
        "seed": seed,
        "initialization": initialization,
        "decisions": decisions,
        "random_consumptions": _random_values(session),
        "events": [event.to_replay_dict() for event in session.events],
        "production_authority_trace": production_trace,
        "skill_decision_authority_trace": skill_trace,
        "outcome": _outcome_value(session, scope),
        "authoritative_private": authoritative_private,
        "records_identity": "0" * 64,
        "execution_identity": "0" * 64,
        "replay_identity": "0" * 64,
    }
    return BridgeFullGameReplayV1.from_dict(
        recompute_bridge_replay_identities_v1(material)
    )


def _canonical_full_game_cell_id(
    assignment: BridgeAssignmentDescriptor, seed: int
) -> str:
    """Derive the natural full-game cell id from the frozen BASELINE_18 registry.

    Only baseline cells may be recorded as natural full games in BRIDGE-E; a
    non-baseline seed fails closed so no sentinel/seed search can be smuggled in.
    """

    for cell in BASELINE_18:
        if (
            cell.general_key == assignment.general_key
            and cell.seat_assignment is assignment.seat_assignment
            and cell.seed == seed
        ):
            return cell.cell_id
    raise BridgeReplayDivergenceError(
        "natural full-game cell必须由BASELINE_18 canonical派生；"
        f"general={assignment.general_key}, "
        f"seat={assignment.seat_assignment.value}, seed={seed} 不是baseline cell"
    )


def record_bounded_skill_aware_fixed_assignment_bridge_replay_v1(
    *,
    general_key: str,
    seat_assignment: FixedAssignment | str,
    seed: int,
    max_steps: int = 25,
    cell_id: str,
) -> BridgeFullGameReplayV1:
    """Record a real bounded Bridge trace; never promote it to full-game proof."""

    if type(max_steps) is not int or max_steps < 1:
        raise BridgeReplayDivergenceError("bounded max_steps必须是正整数")
    session = create_skill_aware_fixed_assignment_duel_session_v1(
        seed=seed,
        general_key=general_key,
        seat_assignment=seat_assignment,
    )
    canonical_cell_id = _canonical_bounded_cell_id(session.assignment, seed)
    if cell_id != canonical_cell_id:
        raise BridgeReplayDivergenceError(
            f"bounded cell_id必须由assignment/seed canonical派生：{canonical_cell_id}"
        )
    return _record_bridge_replay_core(
        session,
        seed=seed,
        scope=BridgeTraceScope.BOUNDED_PRODUCTION_TRACE,
        cell_id=canonical_cell_id,
        max_steps=max_steps,
        require_terminal=False,
    )


def record_natural_full_game_skill_aware_fixed_assignment_bridge_replay_v1(
    *,
    general_key: str,
    seat_assignment: FixedAssignment | str,
    seed: int,
    cell_id: str | None = None,
    max_steps: int = MAX_STEPS,
) -> BridgeFullGameReplayV1:
    """Record a real natural full game that must reach a formal terminal.

    The trace scope is NATURAL_FULL_GAME only because the recorder observed a
    real formal terminal; the scope is never written directly.  ``max_steps`` is
    fixed to the frozen 2000 hard cap and the cell fails closed if the duel does
    not terminate naturally within it.
    """

    if type(max_steps) is not int or max_steps != MAX_STEPS:
        raise BridgeReplayDivergenceError(
            f"natural full-game max_steps必须精确为{MAX_STEPS}"
        )
    session = create_skill_aware_fixed_assignment_duel_session_v1(
        seed=seed,
        general_key=general_key,
        seat_assignment=seat_assignment,
    )
    canonical_cell_id = _canonical_full_game_cell_id(session.assignment, seed)
    if cell_id is not None and cell_id != canonical_cell_id:
        raise BridgeReplayDivergenceError(
            f"natural full-game cell_id必须由BASELINE_18 canonical派生：{canonical_cell_id}"
        )
    return _record_bridge_replay_core(
        session,
        seed=seed,
        scope=BridgeTraceScope.NATURAL_FULL_GAME,
        cell_id=canonical_cell_id,
        max_steps=max_steps,
        require_terminal=True,
    )


@dataclass(frozen=True, slots=True)
class BridgeReplayVerificationResultV1:
    replay_identity: str
    step_count: int
    finished: bool
    proof_flags: Mapping[str, bool]

    def to_dict(self) -> dict[str, object]:
        return {
            "replay_identity": self.replay_identity,
            "step_count": self.step_count,
            "finished": self.finished,
            "proof_flags": dict(self.proof_flags),
        }


def _cold_parse(value: object) -> BridgeFullGameReplayV1:
    raw = value.to_dict() if type(value) is BridgeFullGameReplayV1 else value
    plain = _json_plain(raw)
    return BridgeFullGameReplayV1.from_dict(plain)


def _assert_equal(label: str, recorded: object, live: object) -> None:
    if _json_plain(recorded) != _json_plain(live):
        raise BridgeReplayDivergenceError(f"strict reexecution {label}不匹配")


def _reexecute_bridge_replay_core(
    value: object,
    *,
    collect_full_game_evidence: bool = False,
) -> tuple[BridgeReplayVerificationResultV1, "dict[str, object] | None"]:
    """Cold-load and strictly reexecute a Bridge replay with no override ingress.

    Returns the verification result plus, when ``collect_full_game_evidence`` is
    set, the live full-game evidence (skill decision windows, parent card
    continuation resume tracking and formal-terminal cleanup invariants) used to
    derive BRIDGE-E witnesses without trusting any serialized proof flag.
    """

    evidence_skill_windows: list[dict[str, object]] = []
    evidence_continuation_pending: dict[str, list[int]] = {}
    evidence_private_windows: list[dict[str, object]] = []
    evidence_hp_loss_windows: list[dict[str, object]] = []
    evidence_end_dispatch: list[dict[str, object]] = []
    evidence_qianchong_choices: list[dict[str, object]] = []
    evidence_dynamic_grants: list[dict[str, object]] = []
    evidence_shangjian_evaluations: list[dict[str, object]] = []
    replay = _cold_parse(value)
    if replay.implementation_identity != implementation_identity():
        raise BridgeReplayIdentityError("implementation_identity与live production source不匹配")
    if replay.formal_duel_profile_identity != rules_profile_identity():
        raise BridgeReplayIdentityError("formal duel profile identity漂移")
    initialization = replay.to_dict()["initialization"]
    assignment = BridgeAssignmentDescriptor.from_dict(initialization["assignment"])
    canonical_assignment = create_bridge_assignment(
        assignment.general_key, assignment.seat_assignment
    )
    _assert_equal("canonical assignment", assignment.to_dict(), canonical_assignment.to_dict())
    if replay.trace_scope is BridgeTraceScope.BOUNDED_PRODUCTION_TRACE:
        expected_cell_id = _canonical_bounded_cell_id(canonical_assignment, replay.seed)
        if replay.cell_id != expected_cell_id:
            raise BridgeReplayDivergenceError(
                "cell_id与fresh assignment/seed derivation不匹配"
            )
    elif replay.trace_scope is BridgeTraceScope.NATURAL_FULL_GAME:
        # BRIDGE-E-AUDIT-001 remediation：与 BOUNDED 对称的 canonical cell
        # identity 绑定。独立地由 fresh canonical assignment（General/seat）
        # 与 seed 复用 frozen BASELINE_18 authority 派生 canonical cell_id，
        # 不信任 serialized cell_id，也不复制第二份 mapping；非 frozen
        # BASELINE_18（含 seed 2..99、未发现 sentinel）在此直接 fail closed。
        expected_cell_id = _canonical_full_game_cell_id(
            canonical_assignment, replay.seed
        )
        if replay.cell_id != expected_cell_id:
            raise BridgeReplayDivergenceError(
                "natural full-game cell_id与fresh General/seat/seed "
                "canonical派生不匹配"
            )
    signing = replay.to_dict()["authoritative_private"]["signing_authority"]
    session = _create_skill_aware_fixed_assignment_duel_session_for_strict_replay_v1(
        seed=replay.seed,
        assignment=canonical_assignment,
        session_id=signing["session_id"],
        session_secret_hex=signing["session_secret_hex"],
        capability=_BRIDGE_STRICT_REPLAY_RECONSTRUCTION_CAPABILITY,
    )
    if replay.ruleset_identity != _ruleset_identity(session):
        raise BridgeReplayIdentityError("ruleset_identity与fresh Bridge session不匹配")
    _assert_equal("initialization authority", initialization, _initialization_value(session))
    private = replay.to_dict()["authoritative_private"]
    _assert_equal("initial private authority", private["initial_private_state"], _private_state(session))
    rebuilt_decisions: list[dict[str, object]] = []
    rebuilt_production: list[dict[str, object]] = []
    rebuilt_skill: list[dict[str, object]] = []
    rebuilt_private_selections: list[dict[str, object]] = []
    for index, recorded in enumerate(replay.to_dict()["decisions"]):
        if session.is_finished:
            raise BridgeReplayDivergenceError("recorded decision出现在fresh terminal之后")
        context = session._context()
        legal = session.legal_actions()
        public_context, projections = session.public_action_surface_v1()
        conformance = create_controller_decision_record_v1(public_context, projections)
        projections_value = [_projection_to_value(item) for item in projections]
        chosen_index = next(
            (i for i, action in enumerate(legal) if action.action_id == conformance.chosen_action_id),
            None,
        )
        if chosen_index is None:
            raise BridgeReplayDivergenceError("fresh controller choice不在live signed legal set")
        chosen = legal[chosen_index]
        chosen_projection = _projection_to_value(projections[chosen_index])
        before_snapshot = session.execution_snapshot
        before_state = _state_identity(session)
        rng_before = _rng_authority(session)
        event_start = len(session.events)
        prefix = {
            "step_index": index,
            "state_revision_before": before_snapshot["game_state"]["revision"],
            "execution_revision_before": before_snapshot["step_count"],
            "public_context": public_context.to_dict(),
            "public_context_identity": conformance.public_context_identity,
            "legal_action_projections": projections_value,
            "legal_set_identity": conformance.legal_action_set_identity,
            "chosen_action_id": conformance.chosen_action_id,
            "chosen_semantic_projection": chosen_projection,
            "controller_id": CONTROLLER_ID,
            "controller_version": CONTROLLER_VERSION,
            "state_identity_before": before_state,
            "execution_identity_before": sha256_value(before_snapshot),
            "rng_start_index": rng_before["call_count"],
            "event_start_index": event_start,
            "authority_identity_before": sha256_value(before_snapshot),
        }
        for field, live_value in prefix.items():
            _assert_equal(f"decisions[{index}].{field}", recorded[field], live_value)
        if recorded["chosen_action_id"] != conformance.chosen_action_id:
            raise BridgeReplayDivergenceError("recorded choice不符合fresh controller")
        executed = session.step(recorded["chosen_action_id"])
        if executed.action_id != recorded["chosen_action_id"]:
            raise BridgeReplayDivergenceError("fresh production step未执行recorded signed action")
        after_snapshot = session.execution_snapshot
        after_state = _state_identity(session)
        rng_after = _rng_authority(session)
        event_end = len(session.events)
        suffix = {
            "state_identity_after": after_state,
            "execution_identity_after": sha256_value(after_snapshot),
            "rng_end_index": rng_after["call_count"],
            "event_end_index": event_end,
            "authority_identity_after": sha256_value(after_snapshot),
        }
        for field, live_value in suffix.items():
            _assert_equal(f"decisions[{index}].{field}", recorded[field], live_value)
        rebuilt = {**prefix, **suffix}
        rebuilt_decisions.append(rebuilt)
        _assert_equal(f"decisions[{index}]", recorded, rebuilt)
        production = _production_trace_value(
            step_index=index,
            before_snapshot=before_snapshot,
            after_snapshot=after_snapshot,
            before_state_identity=before_state,
            after_state_identity=after_state,
            legal_set_identity=conformance.legal_action_set_identity,
            rng_before=rng_before,
            rng_after=rng_after,
            event_start=event_start,
            event_end=event_end,
        )
        rebuilt_production.append(production)
        if collect_full_game_evidence:
            _collect_full_game_step_evidence(
                evidence_skill_windows,
                evidence_continuation_pending,
                evidence_private_windows,
                evidence_hp_loss_windows,
                evidence_end_dispatch,
                evidence_qianchong_choices,
                evidence_dynamic_grants,
                evidence_shangjian_evaluations,
                index=index,
                context=context,
                projections=projections,
                conformance=conformance,
                chosen=chosen,
                before_snapshot=before_snapshot,
                after_snapshot=after_snapshot,
                session_events=session.events,
                event_start=event_start,
                event_end=event_end,
            )
        private_selection = _private_selection_value(index, chosen)
        if private_selection is not None:
            rebuilt_private_selections.append(private_selection)
        skill = _skill_trace_value(
            step_index=index,
            action=chosen,
            projection=chosen_projection,
            context=context,
            before_snapshot=before_snapshot,
            after_snapshot=after_snapshot,
        )
        if skill is not None:
            rebuilt_skill.append(skill)
    _assert_equal("decision records", replay.to_dict()["decisions"], rebuilt_decisions)
    _assert_equal("production authority trace", replay.to_dict()["production_authority_trace"], rebuilt_production)
    _assert_equal("skill decision authority trace", replay.to_dict()["skill_decision_authority_trace"], rebuilt_skill)
    _assert_equal("random authority", replay.to_dict()["random_consumptions"], _random_values(session))
    _assert_equal("event authority", replay.to_dict()["events"], [event.to_replay_dict() for event in session.events])
    _assert_equal("private skill selection authority", private["private_skill_selections"], rebuilt_private_selections)
    _assert_equal("final private authority", private["final_private_state"], _private_state(session))
    live_outcome = _outcome_value(session, replay.trace_scope)
    _assert_equal("outcome", replay.to_dict()["outcome"], live_outcome)
    if replay.trace_scope is BridgeTraceScope.NATURAL_FULL_GAME and not session.is_finished:
        raise BridgeReplayDivergenceError("NATURAL_FULL_GAME未到达fresh formal terminal")
    if replay.trace_scope is BridgeTraceScope.BOUNDED_PRODUCTION_TRACE:
        formal_terminal = False
        composition = False
    else:
        formal_terminal = session.is_finished
        composition = session.is_finished
    evidence: dict[str, object] | None = None
    if collect_full_game_evidence:
        evidence = {
            "skill_windows": evidence_skill_windows,
            "continuation_pending_steps": evidence_continuation_pending,
            "private_windows": evidence_private_windows,
            "hp_loss_windows": evidence_hp_loss_windows,
            "end_dispatch_steps": evidence_end_dispatch,
            "qianchong_choices": evidence_qianchong_choices,
            "dynamic_grants": evidence_dynamic_grants,
            "shangjian_evaluations": evidence_shangjian_evaluations,
            "terminal": _terminal_invariants_value(session),
        }
    proof_flags = MappingProxyType(
        {
            "PRODUCTION_REACHABLE": True,
            "NATURAL_FULL_GAME": replay.trace_scope is BridgeTraceScope.NATURAL_FULL_GAME,
            "GENERAL_ASSIGNMENT_PROVEN": True,
            "GENERAL_BASE_STATS_PROVEN": True,
            "GENERAL_SKILL_DERIVATION_PROVEN": True,
            "DYNAMIC_SKILL_AUTHORITY_PROVEN": True,
            "PUBLIC_CONTROLLER_PROVEN": True,
            "ACTION_AUTHORITY_TRACE_PROVEN": True,
            "SKILL_DECISION_AUTHORITY_TRACE_PROVEN": True,
            "FORMAL_TERMINAL_PROVEN": formal_terminal,
            "STRICT_REPLAY_PROVEN": True,
            "SKILL_EVENT_COVERAGE_PROVEN": False,
            "FULL_GAME_COMPOSITION_PROVEN": composition,
        }
    )
    result = BridgeReplayVerificationResultV1(
        replay_identity=replay.replay_identity,
        step_count=len(replay.decisions),
        finished=session.is_finished,
        proof_flags=proof_flags,
    )
    return result, evidence


def reexecute_skill_aware_fixed_assignment_bridge_replay_v1(
    value: object,
) -> BridgeReplayVerificationResultV1:
    """Cold-load and strictly reexecute a Bridge replay with no override ingress."""

    result, _evidence = _reexecute_bridge_replay_core(value)
    return result


def _extract_player_equipment(
    game_state: Mapping[str, object], player_id: str
) -> list[dict[str, object]]:
    cards_list = game_state.get("cards") or ()
    if isinstance(cards_list, dict):
        cards_by_id = cards_list
    else:
        cards_by_id = {
            c.get("instance_id"): c for c in cards_list if isinstance(c, dict)
        }
    zones = game_state.get("zones") or ()
    result: list[dict[str, object]] = []
    for z in zones:
        zone_info = z.get("zone") or {}
        if (
            zone_info.get("kind") == "equipment"
            and zone_info.get("owner_id") == player_id
        ):
            slot = zone_info.get("equipment_slot")
            for cid in z.get("instance_ids") or ():
                card_data = cards_by_id.get(cid) or {}
                result.append(
                    {
                        "card_instance_id": cid,
                        "slot": slot,
                        "card_key": card_data.get("card_key"),
                        "suit": card_data.get("suit"),
                        "color": card_data.get("color"),
                    }
                )
    return result


def _classify_equipment_color(equipment: Sequence[Mapping[str, object]]) -> str:
    if not equipment:
        return "empty"
    colors = {item.get("color") for item in equipment}
    if colors == {"黑"}:
        return "all_black"
    if colors == {"红"}:
        return "all_red"
    return "mixed"


def _collect_full_game_step_evidence(
    skill_windows: list[dict[str, object]],
    continuation_pending: dict[str, list[int]],
    private_windows: list[dict[str, object]],
    hp_loss_windows: list[dict[str, object]],
    end_dispatch_steps: list[dict[str, object]],
    qianchong_choices: list[dict[str, object]],
    dynamic_grants: list[dict[str, object]],
    shangjian_evaluations: list[dict[str, object]],
    *,
    index: int,
    context: object,
    projections: Sequence[ControllerActionProjectionV1],
    conformance: object,
    chosen: object,
    before_snapshot: Mapping[str, object],
    after_snapshot: Mapping[str, object],
    session_events: Sequence[object] = (),
    event_start: int = 0,
    event_end: int = 0,
) -> None:
    """Capture generic live skill-authority window facts for one step.

    Nothing here is General- or skill-specific.  Card-selection windows are
    captured through their opaque public projections only; private observed or
    selected card identities are never copied into this evidence (they remain in
    ``authoritative_private``).  The END-phase dispatcher cursor is captured by a
    public-safe identity so pause/resume can be re-derived without leaking state.
    """

    skill_before = before_snapshot["skill_authority"]
    skill_after = after_snapshot["skill_authority"]

    def _cursor(value: object) -> "dict[str, object] | None":
        if type(value) is not dict:
            return None
        return {
            "end_phase_identity": value.get("end_phase_identity"),
            "turn_number": value.get("turn_number"),
            "current_seat_index": value.get("current_seat_index"),
            "completed_triggers": tuple(
                tuple(item) for item in (value.get("completed_triggers") or ())
            ),
        }

    cursor_before = _cursor(skill_before.get("end_phase_dispatch_state"))
    cursor_after = _cursor(skill_after.get("end_phase_dispatch_state"))
    end_dispatch_steps.append(
        {"step_index": index, "before": cursor_before, "after": cursor_after}
    )

    continuation_before = skill_before.get("pending_card_continuation")
    if (
        type(continuation_before) is dict
        and continuation_before.get("consumed") is False
    ):
        continuation_id = continuation_before.get("continuation_id")
        if type(continuation_id) is str and continuation_id:
            continuation_pending.setdefault(continuation_id, []).append(index)

    pending = skill_before.get("pending_skill_decision")
    if type(pending) is dict:
        legal_set = [
            {
                "action_id": item.action_id,
                "operation": item.operation,
                "action_type": item.action_type,
                "public_skill_id": item.public_skill_id,
            }
            for item in projections
            if type(item) is PublicLegalActionProjectionV1
        ]
        continuation_after = skill_after.get("pending_card_continuation")
        skill_windows.append(
            {
                "step_index": index,
                "skill_id": pending.get("skill_id"),
                "owner_id": pending.get("actor_id"),
                "decision_window_id": pending.get("decision_window_id"),
                "trigger_event_sequence": pending.get("trigger_event_sequence"),
                "trigger_event_type": pending.get("trigger_event_type"),
                "card_instance_id": pending.get("card_instance_id"),
                "condition_facts": dict(pending.get("payload") or {}),
                "window_phase": context.phase,
                "response_window_id": context.response_window_id,
                "signed_legal_set": legal_set,
                "chosen_action_id": conformance.chosen_action_id,
                "chosen_operation": chosen.payload.get("operation"),
                "chosen_action_type": chosen.action_type.value,
                "parent_card_continuation_id_before": (
                    continuation_before.get("continuation_id")
                    if type(continuation_before) is dict
                    else None
                ),
                "parent_card_continuation_consumed_before": (
                    continuation_before.get("consumed")
                    if type(continuation_before) is dict
                    else None
                ),
                "parent_card_continuation_id_after": (
                    continuation_after.get("continuation_id")
                    if type(continuation_after) is dict
                    else None
                ),
                "consumed_card_continuations_after": list(
                    skill_after.get("consumed_card_continuations") or ()
                ),
            }
        )

    private = skill_before.get("pending_private_card_selection")
    if type(private) is dict:
        opaque_options = [
            item.to_dict()
            for item in projections
            if type(item) is PublicOpaqueChoiceProjection
        ]
        chosen_ordinal = None
        for item in projections:
            if (
                type(item) is PublicOpaqueChoiceProjection
                and item.action_id == conformance.chosen_action_id
            ):
                chosen_ordinal = item.ordinal
        private_windows.append(
            {
                "step_index": index,
                "skill_id": private.get("skill_id"),
                "owner_id": private.get("actor_id"),
                "window_id": private.get("window_id"),
                "continuation_id": private.get("continuation_id"),
                "choose_count": private.get("choose_count"),
                "turn_number": private.get("turn_number"),
                "window_phase": context.phase,
                "opaque_options": opaque_options,
                "chosen_action_id": conformance.chosen_action_id,
                "chosen_ordinal": chosen_ordinal,
                "end_cursor_before": cursor_before,
                "end_cursor_after": cursor_after,
            }
        )

    hp_loss = skill_before.get("pending_skill_hp_loss")
    if type(hp_loss) is dict:
        hp_legal_set = [
            {
                "action_id": item.action_id,
                "operation": item.operation,
                "action_type": item.action_type,
                "public_skill_id": item.public_skill_id,
                "target_ids": item.target_ids,
            }
            for item in projections
            if type(item) is PublicLegalActionProjectionV1
        ]
        hp_loss_windows.append(
            {
                "step_index": index,
                "skill_id": hp_loss.get("skill_id"),
                "owner_id": hp_loss.get("owner_id"),
                "stage": hp_loss.get("stage"),
                "resume_phase": hp_loss.get("resume_phase"),
                "target_id": hp_loss.get("target_id"),
                "window_id": hp_loss.get("window_id"),
                "continuation_id": hp_loss.get("continuation_id"),
                "window_phase": context.phase,
                "signed_legal_set": hp_legal_set,
                "chosen_action_id": conformance.chosen_action_id,
                "chosen_operation": chosen.payload.get("operation"),
                "end_cursor_before": cursor_before,
                "end_cursor_after": cursor_after,
            }
        )

    if type(pending) is dict and pending.get("skill_id") == "sgs_skill_qianchong":
        actor_id = pending.get("actor_id")
        eq_before = _extract_player_equipment(
            before_snapshot.get("game_state") or {}, actor_id
        )
        color_class = _classify_equipment_color(eq_before)
        perm_before = skill_before.get("qianchong_phase_permission")
        perm_after = skill_after.get("qianchong_phase_permission")
        legal_opts = [
            {
                "action_id": item.action_id,
                "operation": item.operation,
                "public_choice_value": item.public_choice_value,
            }
            for item in projections
            if type(item) is PublicLegalActionProjectionV1
            and item.operation == "qianchong_choice"
        ]
        chosen_cat = chosen.payload.get("chosen_card_type")
        qianchong_choices.append(
            {
                "step_index": index,
                "turn_number": (
                    context.turn_number
                    if hasattr(context, "turn_number")
                    else before_snapshot.get("runtime", {}).get("turn_number")
                ),
                "owner_id": actor_id,
                "equipment_state": eq_before,
                "color_classification": color_class,
                "signed_legal_options": legal_opts,
                "chosen_action_id": conformance.chosen_action_id,
                "chosen_option": chosen_cat,
                "controller_conformance": True,
                "permission_before": perm_before,
                "permission_after": perm_after,
                "permission_lifecycle_identity": (
                    sha256_value(perm_after) if perm_after is not None else None
                ),
                "runtime_identity_before": sha256_value(
                    skill_before.get("runtime") or {}
                ),
                "runtime_identity_after": sha256_value(
                    skill_after.get("runtime") or {}
                ),
                "continuation_identity": pending.get("payload", {}).get(
                    "continuation_identity"
                ),
            }
        )

    rt_before = skill_before.get("runtime") or {}
    rt_after = skill_after.get("runtime") or {}
    grants_before = rt_before.get("dynamic_grants") or {}
    grants_after = rt_after.get("dynamic_grants") or {}
    for pid in PARTICIPANT_IDS:
        before_active = tuple(
            sorted(
                g["target_skill_id"]
                for g in grants_before.get(pid, ())
                if g.get("active")
            )
        )
        after_active = tuple(
            sorted(
                g["target_skill_id"]
                for g in grants_after.get(pid, ())
                if g.get("active")
            )
        )
        if before_active != after_active:
            eq_before = _extract_player_equipment(
                before_snapshot.get("game_state") or {}, pid
            )
            eq_after = _extract_player_equipment(
                after_snapshot.get("game_state") or {}, pid
            )
            color_before = _classify_equipment_color(eq_before)
            color_after = _classify_equipment_color(eq_after)
            player_skills_after = (rt_after.get("player_skills") or {}).get(pid) or {}
            base_skills = tuple(
                sorted(
                    sid
                    for sid, sdata in player_skills_after.items()
                    if not (sdata.get("source") or "").startswith("dynamic_grant:")
                )
            )
            player_skills_before = (
                (rt_before.get("player_skills") or {}).get(pid) or {}
            )
            eff_before = tuple(
                sorted(
                    sid
                    for sid, sdata in player_skills_before.items()
                    if sdata.get("effective")
                )
            )
            eff_after = tuple(
                sorted(
                    sid
                    for sid, sdata in player_skills_after.items()
                    if sdata.get("effective")
                )
            )
            dynamic_grants.append(
                {
                    "step_index": index,
                    "turn_number": (
                        context.turn_number
                        if hasattr(context, "turn_number")
                        else before_snapshot.get("runtime", {}).get("turn_number")
                    ),
                    "player_id": pid,
                    "movement_root_identity": (
                        chosen.action_id
                        if hasattr(chosen, "action_id") and chosen.action_id
                        else sha256_value({"step": index})
                    ),
                    "equipment_before": eq_before,
                    "equipment_after": eq_after,
                    "color_classification_before": color_before,
                    "color_classification_after": color_after,
                    "base_skills": base_skills,
                    "dynamic_grants_before": before_active,
                    "dynamic_grants_after": after_active,
                    "effective_skill_set_before": eff_before,
                    "effective_skill_set_after": eff_after,
                    "runtime_identity_before": sha256_value(rt_before),
                    "runtime_identity_after": sha256_value(rt_after),
                }
            )

    step_events = session_events[event_start:event_end]
    for ev in step_events:
        ev_dict = ev.to_replay_dict() if hasattr(ev, "to_replay_dict") else ev
        if (
            ev_dict.get("event_type") == "skill_condition_evaluated"
            and ev_dict.get("payload", {}).get("skill_id") == "sgs_skill_shangjian"
        ):
            payload = ev_dict["payload"]
            owner_id = ev_dict.get("skill_owner")
            ledger = (
                after_snapshot.get("skill_authority", {}).get("turn_loss_ledger") or {}
            )
            ledger_entries = ledger.get("entries") or ()
            rederived_l = sum(
                1
                for e in ledger_entries
                if e.get("losing_player_id") == owner_id and e.get("counts_as_loss")
            )
            players = after_snapshot.get("game_state", {}).get("players") or ()
            owner_player = next(
                (p for p in players if p.get("player_id") == owner_id), None
            )
            rederived_h = owner_player.get("hp") if owner_player else None
            cond_met = (
                (rederived_l <= rederived_h) if rederived_h is not None else False
            )
            draw_n = rederived_l if cond_met else 0
            shangjian_evaluations.append(
                {
                    "step_index": index,
                    "turn_number": payload.get("turn_number"),
                    "owner_id": owner_id,
                    "event_sequence": ev_dict.get("sequence"),
                    "rederived_l": rederived_l,
                    "rederived_h": rederived_h,
                    "rederived_condition": cond_met,
                    "rederived_draw_count": draw_n,
                    "recorded_payload": dict(payload),
                    "evaluation_identity": payload.get("evaluation_identity"),
                }
            )


def _terminal_invariants_value(session: object) -> dict[str, object]:
    """Derive formal-terminal cleanup invariants from the live finished session.

    Uses the engine's own finished-state contract plus the Bridge skill/continuation
    surface; never invents a terminal and never trusts a serialized proof flag.
    """

    if not session.is_finished:
        raise BridgeReplayDivergenceError(
            "terminal cleanup invariants只能在真实formal terminal后派生"
        )
    session.assert_finished_state_invariants()
    if session.phase is not ProductionPhase.FINISHED:
        raise BridgeReplayDivergenceError("terminal phase必须是FINISHED")
    winner = session.winner_id
    if winner not in PARTICIPANT_IDS:
        raise BridgeReplayDivergenceError(f"terminal winner不合法：{winner!r}")
    finish_reason = session._resolve_public_finish_reason()
    if type(finish_reason) is not str or not finish_reason:
        raise BridgeReplayDivergenceError("terminal finish_reason不合法")
    runtime = session.runtime
    step_blocked = False
    try:
        session.step("act_bridge_e_terminal_probe")
    except ProductionBatchFinishedError:
        step_blocked = True
    surface_blocked = False
    try:
        session.public_action_surface_v1()
    except ProductionBatchFinishedError:
        surface_blocked = True
    facts = {
        "engine_finished_invariants_passed": True,
        "skill_pending_none": session.skill_pending is None,
        "skill_trigger_queue_empty": tuple(session._skill_trigger_queue) == (),
        "pending_private_card_selection_none": session._pending_private_card_selection is None,
        "pending_skill_hp_loss_none": session._pending_skill_hp_loss is None,
        "pending_card_continuation_none": session._pending_card_continuation is None,
        "end_phase_dispatch_state_none": session._end_phase_dispatch_state is None,
        "continuation_in_progress_none": session._continuation_in_progress_id is None,
        "response_window_none": runtime.response_window_id is None,
        "pending_dying_none": runtime.pending_dying_id is None,
        "processing_empty": tuple(session.state.card_ids_in(PROCESSING_ZONE)) == (),
        "revealed_empty": tuple(session.state.card_ids_in(REVEALED_ZONE)) == (),
        "post_finish_step_blocked": step_blocked,
        "post_finish_action_surface_blocked": surface_blocked,
    }
    # Under the restored Bridge V1 terminal contract (remediation decision
    # B2_PRODUCTION_CLEANUP), the production engine cleans the END dispatcher cursor
    # on any formal terminal transition. Therefore end_phase_dispatch_state_none is
    # hard-required to be literally True. We also retain end_dispatcher_cannot_resume
    # as defense-in-depth telemetry.
    facts["end_dispatcher_cannot_resume"] = (
        step_blocked
        and facts["skill_pending_none"]
        and facts["skill_trigger_queue_empty"]
        and facts["pending_private_card_selection_none"]
        and facts["pending_skill_hp_loss_none"]
        and facts["pending_card_continuation_none"]
        and facts["continuation_in_progress_none"]
    )
    hard_required = tuple(facts.keys())
    failed = sorted(name for name in hard_required if facts[name] is not True)
    if failed:
        raise BridgeReplayDivergenceError(
            "terminal cleanup invariants失败：" + "、".join(failed)
        )
    return {
        "finished": True,
        "phase": session.phase.value,
        "winner": winner,
        "finish_reason": finish_reason,
        **facts,
    }


def derive_skill_event_witnesses_v1(
    evidence: Mapping[str, object],
    replay_payload: Mapping[str, object],
) -> tuple[dict[str, object], ...]:
    """Re-derive skill-event witnesses from live evidence bound to the record.

    Each witness is cross-checked against the recorded skill decision authority
    trace (already proven equal to the live rebuild by strict reexecution) and the
    recorded production authority trace, so no serialized ``event_witness`` boolean
    is ever trusted.  The derivation is General-agnostic: it reports whatever skill
    decision windows naturally occurred, with their opaque live condition facts and
    a proof that any paused parent card continuation resumed exactly once.
    """

    skill_windows = evidence["skill_windows"]
    continuation_pending = evidence["continuation_pending_steps"]
    trace_by_step = {
        item["step_index"]: item
        for item in replay_payload["skill_decision_authority_trace"]
    }
    production_by_step = {
        item["step_index"]: item
        for item in replay_payload["production_authority_trace"]
    }
    witnesses: list[dict[str, object]] = []
    for window in skill_windows:
        index = window["step_index"]
        recorded = trace_by_step.get(index)
        if recorded is None:
            raise BridgeReplayDivergenceError(
                f"skill window step_index={index}在recorded skill authority trace中缺失"
            )
        if recorded["skill_id"] != window["skill_id"]:
            raise BridgeReplayDivergenceError("witness skill_id与recorded trace不匹配")
        if recorded["owner_id"] != window["owner_id"]:
            raise BridgeReplayDivergenceError("witness owner_id与recorded trace不匹配")
        if recorded["window_kind"] != window["window_phase"]:
            raise BridgeReplayDivergenceError("witness window kind与recorded trace不匹配")
        chosen_signed = recorded["chosen_signed_action"]
        if chosen_signed["action_id"] != window["chosen_action_id"]:
            raise BridgeReplayDivergenceError("witness chosen action与recorded trace不匹配")
        if chosen_signed["operation"] != window["chosen_operation"]:
            raise BridgeReplayDivergenceError("witness chosen operation与recorded trace不匹配")
        production = production_by_step.get(index)
        if production is None:
            raise BridgeReplayDivergenceError(
                f"skill window step_index={index}在recorded production trace中缺失"
            )
        continuation_id = window["parent_card_continuation_id_before"]
        resumes_exactly_once: bool | None
        if (
            type(continuation_id) is str
            and continuation_id
            and window["parent_card_continuation_consumed_before"] is False
        ):
            pending_steps = continuation_pending.get(continuation_id, [])
            consumed_after = continuation_id in window["consumed_card_continuations_after"]
            resumes_exactly_once = (
                pending_steps == [index]
                and consumed_after
                and window["parent_card_continuation_id_after"] != continuation_id
            )
        else:
            resumes_exactly_once = None
        witnesses.append(
            {
                "cell_id": replay_payload["cell_id"],
                "step_index": index,
                "skill_id": window["skill_id"],
                "owner_id": window["owner_id"],
                "root_identity": recorded["root_identity"],
                "skill_continuation_identity": recorded["continuation_identity"],
                "decision_window_id": window["decision_window_id"],
                "trigger_event_sequence": window["trigger_event_sequence"],
                "trigger_event_type": window["trigger_event_type"],
                "card_instance_id": window["card_instance_id"],
                "window_kind": recorded["window_kind"],
                "window_phase": window["window_phase"],
                "response_window_id": window["response_window_id"],
                "condition_facts": window["condition_facts"],
                "signed_legal_set": window["signed_legal_set"],
                "chosen_signed_action": {
                    "action_id": window["chosen_action_id"],
                    "operation": window["chosen_operation"],
                    "action_type": window["chosen_action_type"],
                },
                "controller_conformant": True,
                "parent_card_continuation_id": continuation_id,
                "parent_card_continuation_resumes_exactly_once": resumes_exactly_once,
                "continuation_identity_before": production["continuation_identity_before"],
                "continuation_identity_after": production["continuation_identity_after"],
            }
        )
    return tuple(witnesses)


def derive_private_selection_witnesses_v1(
    evidence: Mapping[str, object],
    replay_payload: Mapping[str, object],
) -> tuple[dict[str, object], ...]:
    """Re-derive opaque private card-selection witnesses from live evidence.

    Bound to the recorded skill decision authority trace, the recorded production
    authority trace and the separately stored ``authoritative_private`` selection.
    The witness only ever exposes opaque ordinals and window identity; private
    observed/selected card identities stay in ``authoritative_private`` and are
    never copied into this witness or any controller-facing surface.
    """

    private_windows = evidence["private_windows"]
    trace_by_step = {
        item["step_index"]: item
        for item in replay_payload["skill_decision_authority_trace"]
    }
    production_by_step = {
        item["step_index"]: item
        for item in replay_payload["production_authority_trace"]
    }
    private_by_step = {
        item["step_index"]: item
        for item in replay_payload["authoritative_private"]["private_skill_selections"]
    }
    witnesses: list[dict[str, object]] = []
    for window in private_windows:
        index = window["step_index"]
        recorded = trace_by_step.get(index)
        if recorded is None:
            raise BridgeReplayDivergenceError(
                f"private selection step_index={index}在recorded skill authority trace中缺失"
            )
        if recorded["skill_id"] != window["skill_id"]:
            raise BridgeReplayDivergenceError("private selection witness skill_id与recorded trace不匹配")
        if recorded["owner_id"] != window["owner_id"]:
            raise BridgeReplayDivergenceError("private selection witness owner_id与recorded trace不匹配")
        if recorded["chosen_signed_action"]["action_id"] != window["chosen_action_id"]:
            raise BridgeReplayDivergenceError("private selection witness chosen action与recorded trace不匹配")
        production = production_by_step.get(index)
        if production is None:
            raise BridgeReplayDivergenceError(
                f"private selection step_index={index}在recorded production trace中缺失"
            )
        for option in window["opaque_options"]:
            if frozenset(option) != PRIVATE_SELECTION_ALLOWED_FIELDS:
                raise BridgeReplayDivergenceError("private selection public option不是精确opaque字段集")
            if frozenset(option) & PRIVATE_SELECTION_FORBIDDEN_FIELDS:
                raise BridgeReplayDivergenceError("private selection public option泄露禁止字段")
        available = sorted(option["ordinal"] for option in window["opaque_options"])
        chosen_ordinal = window["chosen_ordinal"]
        controller_conformant = bool(available) and chosen_ordinal == min(available)
        secret = private_by_step.get(index)
        if secret is None:
            raise BridgeReplayDivergenceError(
                f"private selection step_index={index}在authoritative_private中缺失"
            )
        if secret["choose_count"] != window["choose_count"]:
            raise BridgeReplayDivergenceError("private selection choose_count与authoritative_private不匹配")
        if secret["action_id"] != window["chosen_action_id"]:
            raise BridgeReplayDivergenceError("private selection action_id与authoritative_private不匹配")
        cursor_before = window["end_cursor_before"]
        witnesses.append(
            {
                "cell_id": replay_payload["cell_id"],
                "step_index": index,
                "skill_id": window["skill_id"],
                "owner_id": window["owner_id"],
                "root_identity": recorded["root_identity"],
                "skill_continuation_identity": recorded["continuation_identity"],
                "window_id": window["window_id"],
                "continuation_id": window["continuation_id"],
                "choose_count": window["choose_count"],
                "turn_number": window["turn_number"],
                "window_phase": window["window_phase"],
                "available_opaque_ordinals": available,
                "chosen_ordinal": chosen_ordinal,
                "chosen_signed_action": {"action_id": window["chosen_action_id"]},
                "controller_conformant": controller_conformant,
                "private_public_separation": True,
                "secret_recorded_separately": True,
                "end_phase_identity": None if cursor_before is None else cursor_before["end_phase_identity"],
                "end_cursor_identity_before": None if cursor_before is None else sha256_value(cursor_before),
                "end_cursor_identity_after": (
                    None
                    if window["end_cursor_after"] is None
                    else sha256_value(window["end_cursor_after"])
                ),
                "continuation_identity_before": production["continuation_identity_before"],
                "continuation_identity_after": production["continuation_identity_after"],
            }
        )
    return tuple(witnesses)


def derive_skill_hp_loss_witnesses_v1(
    evidence: Mapping[str, object],
    replay_payload: Mapping[str, object],
) -> tuple[dict[str, object], ...]:
    """Re-derive skill HP-loss / dying continuation witnesses from live evidence.

    Bound to the recorded skill decision authority trace and production trace.  The
    frozen production path enforces exactly-once nested continuation and terminal
    cancel cleanup; this exposes the live stage progression and target choice.
    """

    hp_windows = evidence["hp_loss_windows"]
    trace_by_step = {
        item["step_index"]: item
        for item in replay_payload["skill_decision_authority_trace"]
    }
    production_by_step = {
        item["step_index"]: item
        for item in replay_payload["production_authority_trace"]
    }
    witnesses: list[dict[str, object]] = []
    for window in hp_windows:
        index = window["step_index"]
        recorded = trace_by_step.get(index)
        if recorded is None:
            raise BridgeReplayDivergenceError(
                f"hp-loss step_index={index}在recorded skill authority trace中缺失"
            )
        if recorded["skill_id"] != window["skill_id"]:
            raise BridgeReplayDivergenceError("hp-loss witness skill_id与recorded trace不匹配")
        if recorded["owner_id"] != window["owner_id"]:
            raise BridgeReplayDivergenceError("hp-loss witness owner_id与recorded trace不匹配")
        production = production_by_step.get(index)
        if production is None:
            raise BridgeReplayDivergenceError(
                f"hp-loss step_index={index}在recorded production trace中缺失"
            )
        cursor_before = window["end_cursor_before"]
        witnesses.append(
            {
                "cell_id": replay_payload["cell_id"],
                "step_index": index,
                "skill_id": window["skill_id"],
                "owner_id": window["owner_id"],
                "stage": window["stage"],
                "resume_phase": window["resume_phase"],
                "target_id": window["target_id"],
                "window_id": window["window_id"],
                "continuation_id": window["continuation_id"],
                "window_phase": window["window_phase"],
                "root_identity": recorded["root_identity"],
                "skill_continuation_identity": recorded["continuation_identity"],
                "signed_legal_set": window["signed_legal_set"],
                "chosen_signed_action": {
                    "action_id": window["chosen_action_id"],
                    "operation": window["chosen_operation"],
                },
                "end_phase_identity": None if cursor_before is None else cursor_before["end_phase_identity"],
                "end_cursor_identity_before": None if cursor_before is None else sha256_value(cursor_before),
                "continuation_identity_before": production["continuation_identity_before"],
                "continuation_identity_after": production["continuation_identity_after"],
            }
        )
    return tuple(witnesses)


def derive_end_dispatcher_resume_v1(
    evidence: Mapping[str, object],
) -> dict[str, object]:
    """Re-derive the END-phase dispatcher pause/resume proof from live cursor steps.

    Verifies that within one END phase identity the completed-trigger set only grows
    (no re-discovery, no skip, no double resume) and that the dispatcher is fully
    cleared at the formal terminal.  Strict reexecution already proved every cursor
    transition equals the live rebuild; this exposes the resume invariant and the
    per-skill completion counts without hardcoding any General or skill identity.
    """

    steps = evidence["end_dispatch_steps"]
    terminal = evidence["terminal"]
    last_by_identity: dict[object, tuple] = {}
    observed_identities: list[object] = []
    anomalies: list[dict[str, object]] = []
    for step in steps:
        for phase in ("before", "after"):
            cursor = step[phase]
            if cursor is None:
                continue
            identity = cursor["end_phase_identity"]
            if identity not in observed_identities:
                observed_identities.append(identity)
            completed = tuple(sorted(tuple(item) for item in cursor["completed_triggers"]))
            previous = last_by_identity.get(identity)
            if previous is not None:
                if not set(previous).issubset(set(completed)):
                    anomalies.append(
                        {
                            "kind": "non_monotonic_or_skipped",
                            "end_phase_identity": identity,
                            "step_index": step["step_index"],
                        }
                    )
                if len(completed) != len(set(completed)):
                    anomalies.append(
                        {
                            "kind": "duplicate_trigger",
                            "end_phase_identity": identity,
                            "step_index": step["step_index"],
                        }
                    )
            last_by_identity[identity] = completed
    completions_by_skill: dict[object, int] = {}
    for completed in last_by_identity.values():
        for trigger in completed:
            if len(trigger) == 2:
                completions_by_skill[trigger[1]] = completions_by_skill.get(trigger[1], 0) + 1
    terminal_none = terminal["end_phase_dispatch_state_none"] is True
    terminal_cannot_resume = terminal["end_dispatcher_cannot_resume"] is True
    return {
        "end_phase_identities_observed": tuple(observed_identities),
        "completed_triggers_final": {
            str(identity): [list(item) for item in sorted(completed)]
            for identity, completed in last_by_identity.items()
        },
        "completed_triggers_by_skill": completions_by_skill,
        "monotonic_no_duplicate_no_skip": not anomalies,
        "anomalies": tuple(anomalies),
        "terminal_dispatcher_none": terminal_none,
        "terminal_dispatcher_cannot_resume": terminal_cannot_resume,
        "resume_proven": (not anomalies) and terminal_cannot_resume and terminal_none,
    }


def derive_target_effect_first_chance_witnesses_v1(
    replay_payload: Mapping[str, object],
) -> tuple[dict[str, object], ...]:
    """Re-derive locked target-effect first-chance witnesses from recorded events.

    Generic over any skill emitting a SKILL_CONDITION_EVALUATED first-chance
    consumption carrying ``consumed_before``/``consumed_after``.  The recorded events
    are already proven equal to the live rebuild by strict reexecution, so this is
    live-derived authority, never a serialized boolean, and it never infers the mark
    from final damage.  No General name, skill id or card key is hardcoded.
    """

    events = replay_payload["events"]
    ineffective_sources: set[tuple] = set()
    for event in events:
        if event["event_type"] != "target_effect_ineffective":
            continue
        payload = event.get("payload") or {}
        source = payload.get("source_event_sequence")
        if source is not None:
            ineffective_sources.add((event.get("skill_owner"), source))
    witnesses: list[dict[str, object]] = []
    for event in events:
        if event["event_type"] != "skill_condition_evaluated":
            continue
        payload = event.get("payload") or {}
        if "consumed_before" not in payload or "consumed_after" not in payload:
            continue
        user_hand = payload.get("user_hand_count_after_use")
        owner_hand = payload.get("owner_hand_count")
        ineffective = payload.get("target_effect_ineffective")
        if (
            type(user_hand) is not int
            or type(owner_hand) is not int
            or type(ineffective) is not bool
        ):
            raise BridgeReplayDivergenceError("target-effect first-chance event缺少hand比较事实")
        comparison = user_hand <= owner_hand
        if comparison != ineffective:
            raise BridgeReplayDivergenceError("target-effect first-chance比较结果与ineffective标志不一致")
        if payload.get("consumed_before") is not False or payload.get("consumed_after") is not True:
            raise BridgeReplayDivergenceError("target-effect first-chance必须consumed_before=false/consumed_after=true")
        owner = event.get("skill_owner")
        source = payload.get("source_event_sequence")
        target_ids = list(event.get("target_ids") or ())
        witnesses.append(
            {
                "cell_id": replay_payload["cell_id"],
                "event_sequence": event["sequence"],
                "skill_id": payload.get("skill_id"),
                "owner_id": owner,
                "target_ids": target_ids,
                "card_user": event.get("card_user"),
                "card_key": event.get("card_key"),
                "card_instance_id": event.get("card_instance_id"),
                "turn_number": payload.get("turn_number"),
                "source_event_sequence": source,
                "consumed_before": payload.get("consumed_before"),
                "consumed_after": payload.get("consumed_after"),
                "user_hand_count_after_use": user_hand,
                "owner_hand_count": owner_hand,
                "comparison_user_le_owner": comparison,
                "target_effect_ineffective": ineffective,
                "resolution_identity": payload.get("resolution_identity"),
                "per_target_only": target_ids == [owner],
                "ineffective_event_present": (
                    ((owner, source) in ineffective_sources) if ineffective else True
                ),
            }
        )
    return tuple(witnesses)


def derive_qianchong_choice_witnesses_v1(
    evidence: Mapping[str, object],
    replay_payload: Mapping[str, object],
) -> tuple[dict[str, object], ...]:
    """Re-derive Qianchong PLAY-start category choice witnesses from live evidence."""
    choices = evidence.get("qianchong_choices", ())
    trace_by_step = {
        item["step_index"]: item
        for item in replay_payload.get("skill_decision_authority_trace", ())
    }
    witnesses: list[dict[str, object]] = []
    for w in choices:
        index = w["step_index"]
        recorded = trace_by_step.get(index)
        if recorded is None:
            raise BridgeReplayDivergenceError(
                f"qianchong choice step_index={index}在recorded skill authority trace中缺失"
            )
        if recorded["skill_id"] != "sgs_skill_qianchong":
            raise BridgeReplayDivergenceError("qianchong choice witness skill_id不匹配")
        if recorded["owner_id"] != w["owner_id"]:
            raise BridgeReplayDivergenceError("qianchong choice witness owner_id不匹配")
        if w["color_classification"] not in {"empty", "mixed"}:
            raise BridgeReplayDivergenceError("qianchong choice只能在装备empty/mixed时发生")
        legal_opts = [opt["public_choice_value"] for opt in w["signed_legal_options"]]
        if "basic" in legal_opts and w["chosen_option"] != "basic":
            raise BridgeReplayDivergenceError("qianchong choice违反basic > trick > equipment策略")
        witnesses.append(
            {
                "cell_id": replay_payload["cell_id"],
                "step_index": index,
                "turn_identity": w["turn_number"],
                "owner": w["owner_id"],
                "skill_id": "sgs_skill_qianchong",
                "phase": "play",
                "equipment_state": w["equipment_state"],
                "color_classification": w["color_classification"],
                "legal_signed_options": w["signed_legal_options"],
                "chosen_option": w["chosen_option"],
                "controller_conformance": True,
                "permission_before": w["permission_before"],
                "permission_after": w["permission_after"],
                "permission_lifecycle_identity": w["permission_lifecycle_identity"],
                "runtime_identity_before": w["runtime_identity_before"],
                "runtime_identity_after": w["runtime_identity_after"],
                "continuation_identity": recorded["continuation_identity"],
            }
        )
    return tuple(witnesses)


def derive_qianchong_dynamic_grant_witnesses_v1(
    evidence: Mapping[str, object],
    replay_payload: Mapping[str, object],
) -> tuple[dict[str, object], ...]:
    """Re-derive Qianchong dynamic grant transition witnesses from live evidence."""
    grants = evidence.get("dynamic_grants", ())
    witnesses: list[dict[str, object]] = []
    for g in grants:
        color_after = g["color_classification_after"]
        active_after = set(g["dynamic_grants_after"])
        if color_after == "all_black":
            if active_after != {"sgs_skill_weimu"}:
                raise BridgeReplayDivergenceError("全黑装备必须且只能授予帷幕")
        elif color_after == "all_red":
            if active_after != {"sgs_skill_mingzhe"}:
                raise BridgeReplayDivergenceError("全红装备必须且只能授予明哲")
        elif color_after in {"empty", "mixed"}:
            if active_after:
                raise BridgeReplayDivergenceError("空或混色装备不得拥有动态技能")
        if {"sgs_skill_weimu", "sgs_skill_mingzhe"} <= active_after:
            raise BridgeReplayDivergenceError("严禁同时授予帷幕和明哲")
        witnesses.append(
            {
                "cell_id": replay_payload["cell_id"],
                "step_index": g["step_index"],
                "turn_number": g["turn_number"],
                "player_id": g["player_id"],
                "movement_root_identity": g["movement_root_identity"],
                "equipment_before": g["equipment_before"],
                "equipment_after": g["equipment_after"],
                "color_classification_before": g["color_classification_before"],
                "color_classification_after": color_after,
                "base_skills": g["base_skills"],
                "dynamic_grants_before": g["dynamic_grants_before"],
                "dynamic_grants_after": g["dynamic_grants_after"],
                "effective_skill_set_before": g["effective_skill_set_before"],
                "effective_skill_set_after": g["effective_skill_set_after"],
                "runtime_identity_before": g["runtime_identity_before"],
                "runtime_identity_after": g["runtime_identity_after"],
            }
        )
    return tuple(witnesses)


def derive_shangjian_condition_witnesses_v1(
    evidence: Mapping[str, object],
    replay_payload: Mapping[str, object],
) -> tuple[dict[str, object], ...]:
    """Re-derive Shangjian condition evaluation witnesses from live evidence."""
    evaluations = evidence.get("shangjian_evaluations", ())
    events_by_seq = {
        e.get("sequence"): e
        for e in replay_payload.get("events", ())
        if e.get("event_type") == "skill_condition_evaluated"
        and e.get("payload", {}).get("skill_id") == "sgs_skill_shangjian"
    }
    witnesses: list[dict[str, object]] = []
    for ev in evaluations:
        seq = ev["event_sequence"]
        recorded_event = events_by_seq.get(seq)
        if recorded_event is None:
            raise BridgeReplayDivergenceError(
                f"Shangjian event sequence={seq}在recorded events中缺失"
            )
        rec_payload = recorded_event.get("payload") or {}
        if ev["rederived_l"] != rec_payload.get("l_count"):
            raise BridgeReplayDivergenceError(
                "Shangjian live derived L与recorded l_count不一致"
            )
        if ev["rederived_h"] != rec_payload.get("h_hp"):
            raise BridgeReplayDivergenceError(
                "Shangjian live derived H与recorded h_hp不一致"
            )
        if ev["rederived_condition"] != rec_payload.get("condition_met"):
            raise BridgeReplayDivergenceError(
                "Shangjian live derived condition与recorded condition_met不一致"
            )
        if ev["rederived_draw_count"] != rec_payload.get("draw_count"):
            raise BridgeReplayDivergenceError(
                "Shangjian live derived draw_count与recorded draw_count不一致"
            )
        witnesses.append(
            {
                "cell_id": replay_payload["cell_id"],
                "step_index": ev["step_index"],
                "turn_number": ev["turn_number"],
                "owner_id": ev["owner_id"],
                "event_sequence": seq,
                "rederived_l": ev["rederived_l"],
                "rederived_h": ev["rederived_h"],
                "rederived_condition": ev["rederived_condition"],
                "rederived_draw_count": ev["rederived_draw_count"],
                "recorded_payload": dict(rec_payload),
                "evaluation_identity": ev["evaluation_identity"],
            }
        )
    return tuple(witnesses)


SKILL_EVENT_COVERAGE_PROVEN = "PROVEN"
SKILL_EVENT_COVERAGE_NOT_OBSERVED = "NOT_OBSERVED"


@dataclass(frozen=True, slots=True)
class BridgeFullGameCellProofV1:
    """Minimal BRIDGE-E full-game cell proof derived from one strict reexecution."""

    cell_id: str
    general_key: str
    seat_assignment: str
    seed: int
    trace_scope: str
    steps: int
    turns: int
    winner: "str | None"
    finish_reason: "str | None"
    decision_count: int
    event_count: int
    random_count: int
    skill_trace_count: int
    skill_window_count: int
    witnesses: "tuple[Mapping[str, object], ...]"
    private_selection_witnesses: "tuple[Mapping[str, object], ...]"
    hp_loss_witnesses: "tuple[Mapping[str, object], ...]"
    target_effect_first_chance_witnesses: "tuple[Mapping[str, object], ...]"
    end_dispatcher_resume: "Mapping[str, object]"
    terminal_invariants: "Mapping[str, object]"
    strict_replay_proof_flags: "Mapping[str, bool]"
    skill_event_coverage: str
    proof_flags: "Mapping[str, bool]"
    records_identity: str
    execution_identity: str
    replay_identity: str
    qianchong_choice_witnesses: "tuple[Mapping[str, object], ...]" = ()
    qianchong_dynamic_grant_witnesses: "tuple[Mapping[str, object], ...]" = ()
    shangjian_condition_witnesses: "tuple[Mapping[str, object], ...]" = ()
    qianchong_event_coverage: str = SKILL_EVENT_COVERAGE_NOT_OBSERVED
    shangjian_event_coverage: str = SKILL_EVENT_COVERAGE_NOT_OBSERVED

    def to_dict(self) -> dict[str, object]:
        return {
            "cell_id": self.cell_id,
            "general_key": self.general_key,
            "seat_assignment": self.seat_assignment,
            "seed": self.seed,
            "trace_scope": self.trace_scope,
            "steps": self.steps,
            "turns": self.turns,
            "winner": self.winner,
            "finish_reason": self.finish_reason,
            "decision_count": self.decision_count,
            "event_count": self.event_count,
            "random_count": self.random_count,
            "skill_trace_count": self.skill_trace_count,
            "skill_window_count": self.skill_window_count,
            "witness_count": len(self.witnesses),
            "private_selection_witness_count": len(self.private_selection_witnesses),
            "hp_loss_witness_count": len(self.hp_loss_witnesses),
            "target_effect_first_chance_witness_count": len(
                self.target_effect_first_chance_witnesses
            ),
            "end_dispatcher_resume_proven": self.end_dispatcher_resume["resume_proven"],
            "skill_event_coverage": self.skill_event_coverage,
            "proof_flags": dict(self.proof_flags),
            "terminal_invariants": _plain(self.terminal_invariants),
            "records_identity": self.records_identity,
            "execution_identity": self.execution_identity,
            "replay_identity": self.replay_identity,
            "qianchong_choice_witness_count": len(self.qianchong_choice_witnesses),
            "qianchong_dynamic_grant_witness_count": len(
                self.qianchong_dynamic_grant_witnesses
            ),
            "shangjian_condition_witness_count": len(
                self.shangjian_condition_witnesses
            ),
            "qianchong_event_coverage": self.qianchong_event_coverage,
            "shangjian_event_coverage": self.shangjian_event_coverage,
        }


def derive_bridge_full_game_cell_proof_v1(
    value: object,
) -> BridgeFullGameCellProofV1:
    """Derive a full-game cell proof through one fresh strict reexecution.

    The proof never trusts serialized terminal/coverage flags: the formal terminal,
    cleanup invariants, skill-event witnesses and every section flag are re-derived
    from the live canonical reconstruction and the recorded authority traces.
    """

    replay = _cold_parse(value)
    if replay.trace_scope is not BridgeTraceScope.NATURAL_FULL_GAME:
        raise BridgeReplayDivergenceError(
            "full-game cell proof只接受NATURAL_FULL_GAME replay"
        )
    payload = replay.to_dict()
    assignment = BridgeAssignmentDescriptor.from_dict(
        payload["initialization"]["assignment"]
    )
    expected_cell_id = _canonical_full_game_cell_id(assignment, replay.seed)
    if replay.cell_id != expected_cell_id:
        raise BridgeReplayDivergenceError(
            "natural full-game cell_id必须由BASELINE_18 canonical派生："
            f"{expected_cell_id}"
        )
    result, evidence = _reexecute_bridge_replay_core(
        value, collect_full_game_evidence=True
    )
    if evidence is None:
        raise BridgeReplayDivergenceError("full-game cell proof缺少live evidence")
    witnesses = derive_skill_event_witnesses_v1(evidence, payload)
    private_selection_witnesses = derive_private_selection_witnesses_v1(evidence, payload)
    hp_loss_witnesses = derive_skill_hp_loss_witnesses_v1(evidence, payload)
    target_effect_witnesses = derive_target_effect_first_chance_witnesses_v1(payload)
    end_dispatcher_resume = derive_end_dispatcher_resume_v1(evidence)
    qianchong_choice_witnesses = derive_qianchong_choice_witnesses_v1(evidence, payload)
    qianchong_grant_witnesses = derive_qianchong_dynamic_grant_witnesses_v1(evidence, payload)
    shangjian_witnesses = derive_shangjian_condition_witnesses_v1(evidence, payload)
    qianchong_coverage = (
        SKILL_EVENT_COVERAGE_PROVEN
        if (qianchong_choice_witnesses or qianchong_grant_witnesses)
        else SKILL_EVENT_COVERAGE_NOT_OBSERVED
    )
    shangjian_coverage = (
        SKILL_EVENT_COVERAGE_PROVEN
        if shangjian_witnesses
        else SKILL_EVENT_COVERAGE_NOT_OBSERVED
    )
    coverage = (
        SKILL_EVENT_COVERAGE_PROVEN
        if (witnesses or shangjian_witnesses or qianchong_grant_witnesses)
        else SKILL_EVENT_COVERAGE_NOT_OBSERVED
    )
    proof_flags = dict(result.proof_flags)
    proof_flags["SKILL_EVENT_COVERAGE_PROVEN"] = (coverage == SKILL_EVENT_COVERAGE_PROVEN)
    proof_flags["SKILL_EVENT_COVERAGE_QIANCHONG_PROVEN"] = (
        qianchong_coverage == SKILL_EVENT_COVERAGE_PROVEN
    )
    proof_flags["SKILL_EVENT_COVERAGE_SHANGJIAN_PROVEN"] = (
        shangjian_coverage == SKILL_EVENT_COVERAGE_PROVEN
    )
    terminal = evidence["terminal"]
    return BridgeFullGameCellProofV1(
        cell_id=replay.cell_id,
        general_key=assignment.general_key,
        seat_assignment=assignment.seat_assignment.value,
        seed=replay.seed,
        trace_scope=replay.trace_scope.value,
        steps=result.step_count,
        turns=payload["outcome"]["turn_count"],
        winner=payload["outcome"]["winner"],
        finish_reason=payload["outcome"]["finish_reason"],
        decision_count=len(payload["decisions"]),
        event_count=len(payload["events"]),
        random_count=len(payload["random_consumptions"]),
        skill_trace_count=len(payload["skill_decision_authority_trace"]),
        skill_window_count=len(evidence["skill_windows"]),
        witnesses=tuple(_freeze(item) for item in witnesses),
        private_selection_witnesses=tuple(
            _freeze(item) for item in private_selection_witnesses
        ),
        hp_loss_witnesses=tuple(_freeze(item) for item in hp_loss_witnesses),
        target_effect_first_chance_witnesses=tuple(
            _freeze(item) for item in target_effect_witnesses
        ),
        end_dispatcher_resume=_freeze(end_dispatcher_resume),
        terminal_invariants=_freeze(terminal),
        strict_replay_proof_flags=result.proof_flags,
        skill_event_coverage=coverage,
        proof_flags=MappingProxyType(proof_flags),
        records_identity=replay.records_identity,
        execution_identity=replay.execution_identity,
        replay_identity=replay.replay_identity,
        qianchong_choice_witnesses=tuple(_freeze(item) for item in qianchong_choice_witnesses),
        qianchong_dynamic_grant_witnesses=tuple(_freeze(item) for item in qianchong_grant_witnesses),
        shangjian_condition_witnesses=tuple(_freeze(item) for item in shangjian_witnesses),
        qianchong_event_coverage=qianchong_coverage,
        shangjian_event_coverage=shangjian_coverage,
    )


__all__ = [
    "AUTHORITATIVE_PRIVATE_SCHEMA_V1",
    "AUTHORITATIVE_PRIVATE_VERSION_V1",
    "BRIDGE_FULL_GAME_REPLAY_REQUIRED_FIELDS_V1",
    "BRIDGE_REPLAY_CAPABILITY_V1",
    "BridgeFullGameCellProofV1",
    "BridgeFullGameReplayV1",
    "BridgeReplayDivergenceError",
    "BridgeReplayIdentityError",
    "BridgeReplayVerificationResultV1",
    "BridgeTraceScope",
    "SKILL_EVENT_COVERAGE_NOT_OBSERVED",
    "SKILL_EVENT_COVERAGE_PROVEN",
    "bridge_current_contract_latch_v1",
    "derive_bridge_full_game_cell_proof_v1",
    "derive_end_dispatcher_resume_v1",
    "derive_private_selection_witnesses_v1",
    "derive_qianchong_choice_witnesses_v1",
    "derive_qianchong_dynamic_grant_witnesses_v1",
    "derive_shangjian_condition_witnesses_v1",
    "derive_skill_event_witnesses_v1",
    "derive_skill_hp_loss_witnesses_v1",
    "derive_target_effect_first_chance_witnesses_v1",
    "record_bounded_skill_aware_fixed_assignment_bridge_replay_v1",
    "record_natural_full_game_skill_aware_fixed_assignment_bridge_replay_v1",
    "recompute_bridge_replay_identities_v1",
    "reexecute_skill_aware_fixed_assignment_bridge_replay_v1",
]
