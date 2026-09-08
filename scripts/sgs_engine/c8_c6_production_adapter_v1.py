# -*- coding: utf-8 -*-
"""C8-E adapter for canonical C6 standard no-skill eight-player production.

The adapter bridges public C8 identities and capabilities to the existing C6
authorities.  It never implements card/gameplay transitions, never constructs
production action IDs, and never exposes a private action payload or raw
authoritative snapshot.
"""

from __future__ import annotations

from types import MappingProxyType

from dataclasses import dataclass
from enum import Enum
import hashlib
import json
import re
import threading
from typing import Any, Final, Mapping, Sequence

from . import c8_timed_session_runtime_v1 as rt
from . import c8_timeout_controller_integration_v1 as ctl
from . import c8_virtual_time_contract_v1 as c8
from .actions import ActionType, LegalAction
from .authoritative_no_skill_full_game import canonical_no_skill_mode_v1
from .mode_identity import (
    FORMAL_NO_SKILL_IDENTITY_8P_MODE,
    FormalEightPlayerIdentitySession,
)
from .production_batch import (
    BatchActionIdController,
    ProductionBasicCardBatch,
    ProductionPhase,
)


class C8C6ProductionAdapterError(RuntimeError):
    """Fail-closed C8-E authority, lineage, or capability error."""


class ProductionContextApplicabilityV1(str, Enum):
    APPLICABLE = "APPLICABLE"
    NOT_APPLICABLE_IN_C6_NO_SKILL_8P = (
        "NOT_APPLICABLE_IN_C6_NO_SKILL_8P"
    )
    PRIVATE_ORDINAL_TIMEOUT_UNRESOLVED = (
        "PRIVATE_ORDINAL_TIMEOUT_UNRESOLVED"
    )


C8_E_ADAPTER_ID: Final[str] = "c8-c6-production-adapter-v1"
C8_E_SCHEMA_VERSION: Final[int] = 1

_CONTRACT_DESCRIPTOR: Final[Mapping[str, object]] = {
    "schema": "sgs-c8-e-c6-production-adapter-contract-v1",
    "contract_version": 1,
    "adapter_id": C8_E_ADAPTER_ID,
    "canonical_mode": FORMAL_NO_SKILL_IDENTITY_8P_MODE,
    "canonical_factory": "canonical_no_skill_mode_v1.create_session",
    "production_legal_authority": "FormalEightPlayerIdentitySession.legal_actions",
    "production_step_authority": "FormalEightPlayerIdentitySession.step",
    "production_action_controller": "BatchActionIdController",
    "production_transaction_seam": {
        "capture": "capture_authoritative_transaction_v1",
        "identity": "authoritative_transaction_token_identity_v1",
        "restore": "restore_authoritative_transaction_v1",
        "commit": "commit_authoritative_transaction_v1",
        "raw_snapshot_exposed": False,
        "one_shot": True,
        "serializable": False,
    },
    "public_candidate_fields": [
        "production_signed_action_id",
        "production_proposal_ordinal",
        "public_action_family",
    ],
    "private_candidate_fields_exposed": [],
    "proposal_order": "EXACT_PRODUCTION_ENUMERATION_ORDER_NO_RESORT",
    "signed_action_confirmation": (
        "FRESH_REENUMERATE_AND_MATCH_STATE_CONTEXT_ORDER_ORDINAL_ACTION_ID"
    ),
    "signed_action_id_may_equal_public_reference": True,
    "decision_identity_inputs": [
        "session_binding",
        "mode",
        "turn_number",
        "phase",
        "current_player",
        "current_actor",
        "state_revision",
        "step_count",
        "proposal_order_identity",
        "parent_context_identity",
    ],
    "identity_forbidden_inputs": [
        "python_object_id",
        "memory_address",
        "wall_clock",
        "unstable_repr",
    ],
    "gameplay_authority_copied": False,
    "rng_authority": "PRODUCTION_SESSION_ONLY",
    "full_game": False,
}


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


C8_E_CONTRACT_IDENTITY: Final[str] = _identity(_CONTRACT_DESCRIPTOR)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ZERO_IDENTITY = "0" * 64


def _sha(value: object, label: str) -> str:
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        raise C8C6ProductionAdapterError(f"{label}必须是lowercase SHA-256")
    if value == _ZERO_IDENTITY:
        raise C8C6ProductionAdapterError(f"{label}不得为zero identity")
    return value


def _text(value: object, label: str) -> str:
    if type(value) is not str or not value:
        raise C8C6ProductionAdapterError(f"{label}必须是非空精确字符串")
    return value


def _integer(value: object, label: str, *, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise C8C6ProductionAdapterError(
            f"{label}必须是大于等于{minimum}的精确整数"
        )
    return value


def _production_actions(session: ProductionBasicCardBatch) -> tuple[LegalAction, ...]:
    actions = session.legal_actions()
    if type(actions) is not tuple or any(type(item) is not LegalAction for item in actions):
        raise C8C6ProductionAdapterError("production legal_actions返回了非strict集合")
    if not actions:
        raise C8C6ProductionAdapterError("production current decision没有合法动作")
    action_ids = tuple(item.action_id for item in actions)
    if any(type(item) is not str or not item for item in action_ids):
        raise C8C6ProductionAdapterError("production legal action缺少signed action_id")
    if len(action_ids) != len(set(action_ids)):
        raise C8C6ProductionAdapterError("production legal action_id重复")
    return actions


_OPTIONAL_RESPONSE_PHASES: Final[frozenset[ProductionPhase]] = frozenset(
    {
        ProductionPhase.JUDGMENT_WUXIE,
        ProductionPhase.SLASH_RESPONSE,
        ProductionPhase.TRICK_RESPONSE,
        ProductionPhase.DUEL_RESPONSE,
        ProductionPhase.FIRE_ATTACK_DISCARD,
        ProductionPhase.NANMAN_RESPONSE,
        ProductionPhase.WANJIAN_RESPONSE,
    }
)
_OPTIONAL_DECISION_PHASES: Final[frozenset[ProductionPhase]] = frozenset(
    {
        ProductionPhase.CIXIONG_ACTIVATE,
        ProductionPhase.WEAPON_AFTER_DAMAGE,
        ProductionPhase.WEAPON_SLASH_CHOICE,
    }
)
_MANDATORY_PRIVATE_CHOICE_PHASES: Final[frozenset[ProductionPhase]] = frozenset(
    {
        ProductionPhase.CIXIONG_TARGET_CHOICE,
        ProductionPhase.ZONE_CHOICE,
        ProductionPhase.FIRE_ATTACK_REVEAL,
        ProductionPhase.BORROWED_SWORD_CHOICE,
        ProductionPhase.WUGU_PICK,
    }
)
_MULTI_STEP_PHASES: Final[frozenset[ProductionPhase]] = frozenset(
    {
        ProductionPhase.DISCARD,
        ProductionPhase.WEAPON_DISCARD_TWO,
        ProductionPhase.HANBING_DISCARD,
    }
)
_AUTOMATIC_PHASES: Final[frozenset[ProductionPhase]] = frozenset(
    {
        ProductionPhase.PREPARE,
        ProductionPhase.JUDGMENT,
        ProductionPhase.DRAW,
        ProductionPhase.END,
    }
)
_NON_C6_PHASES: Final[frozenset[ProductionPhase]] = frozenset(
    {
        ProductionPhase.FEIYANG_ACTIVATE,
        ProductionPhase.PEASANT_REWARD_CHOICE,
        ProductionPhase.MODE_DECISION,
        ProductionPhase.SUCCESSION_CARD_CHOICE,
        ProductionPhase.IDENTITY_REWARD_CHOICE,
    }
)


def _window_mapping(
    phase: ProductionPhase,
) -> tuple[c8.TimedWindowKindV1, ProductionContextApplicabilityV1]:
    if phase is ProductionPhase.PLAY:
        return c8.TimedWindowKindV1.PLAY, ProductionContextApplicabilityV1.APPLICABLE
    if phase in _OPTIONAL_RESPONSE_PHASES:
        return (
            c8.TimedWindowKindV1.OPTIONAL_RESPONSE,
            ProductionContextApplicabilityV1.APPLICABLE,
        )
    if phase is ProductionPhase.DYING_RESCUE:
        return (
            c8.TimedWindowKindV1.RESCUE_RESPONSE,
            ProductionContextApplicabilityV1.APPLICABLE,
        )
    if phase in _OPTIONAL_DECISION_PHASES:
        return (
            c8.TimedWindowKindV1.OPTIONAL_SKILL_DECISION,
            ProductionContextApplicabilityV1.APPLICABLE,
        )
    if phase in _MANDATORY_PRIVATE_CHOICE_PHASES:
        return (
            c8.TimedWindowKindV1.MANDATORY_PUBLIC_CHOICE,
            ProductionContextApplicabilityV1.PRIVATE_ORDINAL_TIMEOUT_UNRESOLVED,
        )
    if phase in _MULTI_STEP_PHASES:
        return (
            c8.TimedWindowKindV1.MULTI_STEP_OBLIGATION,
            ProductionContextApplicabilityV1.PRIVATE_ORDINAL_TIMEOUT_UNRESOLVED,
        )
    if phase in _AUTOMATIC_PHASES:
        return (
            c8.TimedWindowKindV1.MANDATORY_SINGLE_ACTION,
            ProductionContextApplicabilityV1.APPLICABLE,
        )
    if phase in _NON_C6_PHASES:
        mapped = (
            c8.TimedWindowKindV1.MODE_DECISION
            if phase is ProductionPhase.MODE_DECISION
            else c8.TimedWindowKindV1.MANDATORY_SINGLE_ACTION
        )
        return (
            mapped,
            ProductionContextApplicabilityV1.NOT_APPLICABLE_IN_C6_NO_SKILL_8P,
        )
    raise C8C6ProductionAdapterError(
        f"production phase {phase.value!r}没有C8-E decision mapping"
    )


def production_window_context_mapping_v1() -> dict[str, dict[str, str]]:
    """Return the explicit C6 phase mapping without claiming runtime coverage."""

    result: dict[str, dict[str, str]] = {}
    for phase in ProductionPhase:
        if phase is ProductionPhase.FINISHED:
            result[phase.value] = {
                "window_kind": "NONE",
                "applicability": "NO_DECISION_AFTER_FINISH",
            }
            continue
        window_kind, applicability = _window_mapping(phase)
        result[phase.value] = {
            "window_kind": window_kind.value,
            "applicability": applicability.value,
        }
    result["character_skill_multi_step"] = {
        "window_kind": c8.TimedWindowKindV1.MULTI_STEP_OBLIGATION.value,
        "applicability": (
            ProductionContextApplicabilityV1.NOT_APPLICABLE_IN_C6_NO_SKILL_8P.value
        ),
    }
    return result


def _payload_operation(action: LegalAction) -> str:
    operation = action.payload.get("operation")
    return operation if type(operation) is str else ""


def _private_payload_present(actions: Sequence[LegalAction]) -> bool:
    return any(
        action.card_instance_id is not None
        or action.virtual_card is not None
        or action.skill_id is not None
        or bool(action.payload)
        for action in actions
    )


def _public_ordinal_safe(
    phase: ProductionPhase, actions: Sequence[LegalAction]
) -> bool:
    if phase in _MANDATORY_PRIVATE_CHOICE_PHASES or phase in _MULTI_STEP_PHASES:
        return False
    if phase is ProductionPhase.MODE_DECISION:
        return all(
            action.card_instance_id is None
            and action.virtual_card is None
            and action.skill_id is None
            for action in actions
        )
    return True


def _family_for_action(
    action: LegalAction,
    context: "ProductionDecisionContextV1",
) -> c8.PublicActionFamilyV1:
    operation = _payload_operation(action)
    if context.phase is ProductionPhase.PLAY and (
        action.action_type is ActionType.PASS and operation == "end_play_phase"
    ):
        return c8.PublicActionFamilyV1.END_PLAY_PHASE
    if context.window_kind in (c8.TimedWindowKindV1.OPTIONAL_RESPONSE,
                               c8.TimedWindowKindV1.RESCUE_RESPONSE):
        return response_public_action_family_v1(action, context)
    if context.phase in _OPTIONAL_DECISION_PHASES:
        return optional_public_action_family_v1(action, context)
    if context.phase is ProductionPhase.MODE_DECISION and action.action_type is ActionType.PASS:
        return c8.PublicActionFamilyV1.PASS_MODE_DECISION
    if (
        context.window_kind is c8.TimedWindowKindV1.MANDATORY_PUBLIC_CHOICE
        and context.public_ordinal_safe
    ):
        return c8.PublicActionFamilyV1.PUBLIC_CHOICE
    return c8.PublicActionFamilyV1.MANDATORY_ACTION


_RESPONSE_OPERATIONS_V1 = MappingProxyType({
    ProductionPhase.SLASH_RESPONSE: frozenset({"play_dodge", "activate_bagua", "pass_slash_response"}),
    ProductionPhase.WANJIAN_RESPONSE: frozenset({"play_jink_for_wanjian", "activate_bagua", "pass_wanjian_jink"}),
    ProductionPhase.NANMAN_RESPONSE: frozenset({"play_slash_for_nanman", "pass_nanman_slash"}),
    ProductionPhase.DUEL_RESPONSE: frozenset({"play_slash_for_duel", "pass_duel_slash"}),
    ProductionPhase.TRICK_RESPONSE: frozenset({"use_wuxie", "pass_trick_response"}),
    ProductionPhase.JUDGMENT_WUXIE: frozenset({"use_wuxie", "pass_judgment_wuxie"}),
    ProductionPhase.FIRE_ATTACK_DISCARD: frozenset({"discard_same_suit_for_fire_attack", "pass_fire_attack_discard"}),
    ProductionPhase.DYING_RESCUE: frozenset({"rescue_with_peach", "rescue_with_wine", "pass_rescue"}),
})
_RESPONSE_SEMANTICS_V1 = MappingProxyType({
    "play_dodge": (ActionType.USE_CARD, c8.PublicActionFamilyV1.MANDATORY_ACTION),
    "play_jink_for_wanjian": (ActionType.PLAY_CARD, c8.PublicActionFamilyV1.MANDATORY_ACTION),
    "play_slash_for_nanman": (ActionType.PLAY_CARD, c8.PublicActionFamilyV1.MANDATORY_ACTION),
    "play_slash_for_duel": (ActionType.PLAY_CARD, c8.PublicActionFamilyV1.MANDATORY_ACTION),
    "use_wuxie": (ActionType.USE_CARD, c8.PublicActionFamilyV1.MANDATORY_ACTION),
    "discard_same_suit_for_fire_attack": (ActionType.MOVE_CARD, c8.PublicActionFamilyV1.MANDATORY_ACTION),
    "rescue_with_peach": (ActionType.USE_CARD, c8.PublicActionFamilyV1.MANDATORY_ACTION),
    "rescue_with_wine": (ActionType.USE_CARD, c8.PublicActionFamilyV1.MANDATORY_ACTION),
    "activate_bagua": (ActionType.PASS, c8.PublicActionFamilyV1.PUBLIC_CHOICE),
    **{operation: (ActionType.PASS, c8.PublicActionFamilyV1.PASS_RESPONSE) for operation in (
        "pass_slash_response", "pass_wanjian_jink", "pass_nanman_slash", "pass_duel_slash",
        "pass_trick_response", "pass_judgment_wuxie", "pass_fire_attack_discard")},
    "pass_rescue": (ActionType.PASS, c8.PublicActionFamilyV1.PASS_RESCUE),
})


def response_public_action_family_v1(
    action: LegalAction, context: "ProductionDecisionContextV1",
) -> c8.PublicActionFamilyV1:
    """E 私有语义登记：PASS 类型不推导放弃；未知阶段/操作失败关闭。

    PUBLIC_CHOICE 是响应窗口内可选发动的既有精确等价 family。
    它不承诺八卦成功；最终虚拟闪的使用/打出语义仍由 C6 所在窗口决定。
    阶段白名单取自生产 legal-action construction；新窗口必须显式登记。
    """
    operation = _payload_operation(action)
    expected = _RESPONSE_SEMANTICS_V1.get(operation)
    expected_kind = (c8.TimedWindowKindV1.RESCUE_RESPONSE
                     if context.phase is ProductionPhase.DYING_RESCUE
                     else c8.TimedWindowKindV1.OPTIONAL_RESPONSE)
    if (
        operation not in _RESPONSE_OPERATIONS_V1.get(context.phase, ())
        or context.window_kind is not expected_kind
        or expected is None
        or action.action_type is not expected[0]
    ):
        raise C8C6ProductionAdapterError(
            "RESPONSE_SEMANTICS_UNRESOLVED: 未知或不匹配的响应动作语义"
        )
    return expected[1]


def verify_response_public_action_family_v1(
    action: LegalAction, context: "ProductionDecisionContextV1",
    family: c8.PublicActionFamilyV1,
) -> None:
    """Verify supplied E/G2 projection using E's canonical classification."""
    if (
        type(family) is not c8.PublicActionFamilyV1
        or family is not response_public_action_family_v1(action, context)
    ):
        raise C8C6ProductionAdapterError(
            "RESPONSE_FAMILY_SEMANTIC_REJECT: E/G2响应分类不一致"
        )


def slash_response_public_action_family_v1(action, context):
    """保留既有杀响应入口；分类唯一来源为通用 E 登记。"""
    if context.phase is not ProductionPhase.SLASH_RESPONSE:
        raise C8C6ProductionAdapterError("RESPONSE_SEMANTICS_UNRESOLVED: 不是杀响应")
    return response_public_action_family_v1(action, context)


def verify_slash_response_public_action_family_v1(action, context, family):
    slash_response_public_action_family_v1(action, context)
    verify_response_public_action_family_v1(action, context, family)


def optional_public_action_family_v1(
    action: LegalAction, context: "ProductionDecisionContextV1",
) -> c8.PublicActionFamilyV1:
    """E owns optional semantics; private operations never enter G1 material.

    PUBLIC_CHOICE denotes activation in an OPTIONAL_SKILL_DECISION window;
    only DECLINE_OPTIONAL is the existing A explicit timeout fallback.
    This corrects classification without changing A's public contract.
    """
    semantics = {
        ProductionPhase.CIXIONG_ACTIVATE: {
            "activate_cixiong": (ActionType.ACTIVATE_SKILL, c8.PublicActionFamilyV1.PUBLIC_CHOICE),
            "pass_cixiong": (ActionType.PASS, c8.PublicActionFamilyV1.DECLINE_OPTIONAL),
        },
        ProductionPhase.WEAPON_AFTER_DAMAGE: {
            "weapon_discard_mount": (ActionType.MOVE_CARD, c8.PublicActionFamilyV1.PUBLIC_CHOICE),
            "pass_weapon_choice": (ActionType.PASS, c8.PublicActionFamilyV1.DECLINE_OPTIONAL),
        },
        ProductionPhase.WEAPON_SLASH_CHOICE: {
            "weapon_force_hit": (ActionType.PASS, c8.PublicActionFamilyV1.PUBLIC_CHOICE),
            "weapon_prevent_damage": (ActionType.PASS, c8.PublicActionFamilyV1.PUBLIC_CHOICE),
            "qinglong_use_slash": (ActionType.RESPOND, c8.PublicActionFamilyV1.PUBLIC_CHOICE),
            "pass_weapon_choice": (ActionType.PASS, c8.PublicActionFamilyV1.DECLINE_OPTIONAL),
        },
    }
    expected = semantics.get(context.phase, {}).get(_payload_operation(action))
    if expected is None or action.action_type is not expected[0]:
        raise C8C6ProductionAdapterError(
            "OPTIONAL_ACTION_SEMANTICS_UNRESOLVED: 未知或不匹配的optional动作语义"
        )
    return expected[1]


def verify_optional_public_action_family_v1(
    action: LegalAction, context: "ProductionDecisionContextV1",
    family: c8.PublicActionFamilyV1,
) -> None:
    """Reject supplied E/G2 families against E's sole semantic classifier."""
    if type(family) is not c8.PublicActionFamilyV1 or family is not optional_public_action_family_v1(action, context):
        raise C8C6ProductionAdapterError("OPTIONAL_ACTION_FAMILY_SEMANTIC_REJECT: E/G2分类不一致")


@dataclass(frozen=True, slots=True, kw_only=True)
class ProductionDecisionContextV1:
    schema: str
    contract_version: int
    mode_id: str
    phase: ProductionPhase
    current_actor_id: str
    current_player_id: str
    turn_number: int
    state_revision: int
    step_count: int
    window_kind: c8.TimedWindowKindV1
    applicability: ProductionContextApplicabilityV1
    parent_context_identity: str | None
    proposal_count: int
    proposal_order_identity: str
    private_payload_present: bool
    public_ordinal_safe: bool
    decision_identity: str
    obligation_identity: str
    context_identity: str

    def __post_init__(self) -> None:
        if self.schema != "sgs-c8-e-production-decision-context-v1":
            raise C8C6ProductionAdapterError("decision context schema不匹配")
        if self.contract_version != 1:
            raise C8C6ProductionAdapterError("decision context version不匹配")
        if self.mode_id != FORMAL_NO_SKILL_IDENTITY_8P_MODE:
            raise C8C6ProductionAdapterError("decision context不是canonical C6")
        if type(self.phase) is not ProductionPhase:
            raise C8C6ProductionAdapterError("decision context phase类型不匹配")
        if type(self.window_kind) is not c8.TimedWindowKindV1:
            raise C8C6ProductionAdapterError("decision context window kind类型不匹配")
        if type(self.applicability) is not ProductionContextApplicabilityV1:
            raise C8C6ProductionAdapterError("decision applicability类型不匹配")
        _text(self.current_actor_id, "current_actor_id")
        _text(self.current_player_id, "current_player_id")
        _integer(self.turn_number, "turn_number", minimum=1)
        _integer(self.state_revision, "state_revision")
        _integer(self.step_count, "step_count")
        _integer(self.proposal_count, "proposal_count", minimum=1)
        _sha(self.proposal_order_identity, "proposal_order_identity")
        if self.parent_context_identity is not None:
            _sha(self.parent_context_identity, "parent_context_identity")
        if type(self.private_payload_present) is not bool:
            raise C8C6ProductionAdapterError("private_payload_present必须是bool")
        if type(self.public_ordinal_safe) is not bool:
            raise C8C6ProductionAdapterError("public_ordinal_safe必须是bool")
        _sha(self.decision_identity, "decision_identity")
        _sha(self.obligation_identity, "obligation_identity")
        if self.context_identity != _identity(self.identity_material_v1()):
            raise C8C6ProductionAdapterError("decision context identity不匹配")

    def identity_material_v1(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "contract_version": self.contract_version,
            "mode_id": self.mode_id,
            "phase": self.phase.value,
            "current_actor_id": self.current_actor_id,
            "current_player_id": self.current_player_id,
            "turn_number": self.turn_number,
            "state_revision": self.state_revision,
            "step_count": self.step_count,
            "window_kind": self.window_kind.value,
            "applicability": self.applicability.value,
            "parent_context_identity": self.parent_context_identity,
            "proposal_count": self.proposal_count,
            "proposal_order_identity": self.proposal_order_identity,
            "private_payload_present": self.private_payload_present,
            "public_ordinal_safe": self.public_ordinal_safe,
            "decision_identity": self.decision_identity,
            "obligation_identity": self.obligation_identity,
        }

    def to_public_dict_v1(self) -> dict[str, object]:
        return {**self.identity_material_v1(), "context_identity": self.context_identity}

    @classmethod
    def build(
        cls,
        *,
        session_identity: str,
        phase: ProductionPhase,
        current_actor_id: str,
        current_player_id: str,
        turn_number: int,
        state_revision: int,
        step_count: int,
        actions: Sequence[LegalAction],
        parent_context_identity: str | None,
    ) -> "ProductionDecisionContextV1":
        window_kind, applicability = _window_mapping(phase)
        order_identity = _identity(
            {
                "schema": "sgs-c8-e-production-proposal-order-v1",
                "contract_version": 1,
                "session_identity": session_identity,
                "action_ids": [action.action_id for action in actions],
            }
        )
        decision_material = {
            "schema": "sgs-c8-e-production-logical-decision-v1",
            "contract_version": 1,
            "session_identity": session_identity,
            "mode_id": FORMAL_NO_SKILL_IDENTITY_8P_MODE,
            "phase": phase.value,
            "current_actor_id": current_actor_id,
            "current_player_id": current_player_id,
            "turn_number": turn_number,
            "state_revision": state_revision,
            "step_count": step_count,
            "proposal_order_identity": order_identity,
            "parent_context_identity": parent_context_identity,
        }
        decision_identity = _identity(decision_material)
        obligation_identity = _identity(
            {
                "schema": "sgs-c8-e-production-obligation-v1",
                "contract_version": 1,
                "decision_identity": decision_identity,
                "window_kind": window_kind.value,
                "parent_context_identity": parent_context_identity,
            }
        )
        values: dict[str, object] = {
            "schema": "sgs-c8-e-production-decision-context-v1",
            "contract_version": 1,
            "mode_id": FORMAL_NO_SKILL_IDENTITY_8P_MODE,
            "phase": phase,
            "current_actor_id": current_actor_id,
            "current_player_id": current_player_id,
            "turn_number": turn_number,
            "state_revision": state_revision,
            "step_count": step_count,
            "window_kind": window_kind,
            "applicability": applicability,
            "parent_context_identity": parent_context_identity,
            "proposal_count": len(actions),
            "proposal_order_identity": order_identity,
            "private_payload_present": _private_payload_present(actions),
            "public_ordinal_safe": _public_ordinal_safe(phase, actions),
            "decision_identity": decision_identity,
            "obligation_identity": obligation_identity,
        }
        provisional = cls.__new__(cls)
        for name, value in values.items():
            object.__setattr__(provisional, name, value)
        material = provisional.identity_material_v1()
        return cls(**values, context_identity=_identity(material))  # type: ignore[arg-type]


class _OpaqueIssuanceReservationV1:
    __slots__ = ()

    def __repr__(self) -> str:
        return "<opaque-c8-e-issuance-reservation-v1>"

    def __copy__(self) -> object:
        raise TypeError("C8-E issuance reservation禁止复制")

    def __deepcopy__(self, memo: object) -> object:
        raise TypeError("C8-E issuance reservation禁止深复制")

    def __reduce__(self) -> object:
        raise TypeError("C8-E issuance reservation禁止序列化")

    def __reduce_ex__(self, protocol: int) -> object:
        raise TypeError("C8-E issuance reservation禁止序列化")


@dataclass(slots=True)
class _ReservationRecordV1:
    capability: _OpaqueIssuanceReservationV1
    capability_identity: str
    evidence_identity: str
    signed_action_id: str
    candidate_reference: str
    public_ordinal: int
    legal_set_identity: str
    proposal_order_identity: str
    timeout_auth_binding: str
    timeout_due_commitment_identity: str
    context_identity: str
    ledger_before_identity: str
    guard_operation_epoch: int
    issuing_thread_identity: int
    status: str = "PENDING"
    final_b_authorization_binding: str | None = None
    issuance: ctl.SignedActionIssuanceEvidenceV1 | None = None


@dataclass(frozen=True, slots=True)
class _AdapterTransactionSidecarV1:
    token: object
    token_identity: str
    parent_context_identity: str | None


class C8C6ProductionAdapterV1:
    """Bridge one exact canonical C6 session to C8-B and C8-C."""

    def __init__(self, session: FormalEightPlayerIdentitySession) -> None:
        if type(session) is not FormalEightPlayerIdentitySession:
            raise TypeError("C8-E只接受canonical exact C6 session")
        if session.mode_id != FORMAL_NO_SKILL_IDENTITY_8P_MODE:
            raise C8C6ProductionAdapterError("C8-E session mode不匹配")
        if session.analysis_only is not False:
            raise C8C6ProductionAdapterError("C8-E禁止analysis_only session")
        if session.skill_runtime is not None:
            raise C8C6ProductionAdapterError("C8-E仅允许C6 no-skill session")
        self._session = session
        spec = canonical_no_skill_mode_v1(FORMAL_NO_SKILL_IDENTITY_8P_MODE)
        self._session_identity = _identity(
            {
                "schema": "sgs-c8-e-c6-session-binding-v1",
                "contract_version": 1,
                "mode_contract_id": spec.mode_contract_id,
                "profile_identity": spec.profile_identity(),
                "session_id_commitment": _identity(
                    {
                        "schema": "production-session-id-commitment-v1",
                        "session_id": session.session_id,
                    }
                ),
            }
        )
        self._issuance_authority_identity = _identity(
            {
                "schema": "sgs-c8-e-issuance-authority-v1",
                "contract_version": 1,
                "adapter_contract_identity": C8_E_CONTRACT_IDENTITY,
                "session_identity": self._session_identity,
            }
        )
        self._runtime: rt.C8TimedSessionRuntimeV1 | None = None
        self._controller_identity: str | None = None
        self._bound_ref: rt.WindowAuthorityRefV1 | None = None
        self._bound_context: ProductionDecisionContextV1 | None = None
        self._current_snapshot: ctl.AdapterPublicLegalActionsSnapshotV1 | None = None
        self._current_production_order: tuple[str, ...] | None = None
        self._public_legal_set_history: list[
            ctl.AdapterPublicLegalActionsSnapshotV1
        ] = []
        self._public_issuance_history: list[dict[str, object]] = []
        self._pending_parent_context_identity: str | None = None
        self._transaction_sidecars: dict[int, _AdapterTransactionSidecarV1] = {}
        self._next_reservation_sequence = 0
        self._reservations_by_token: dict[int, _ReservationRecordV1] = {}
        self._reservations_by_evidence: dict[str, _ReservationRecordV1] = {}
        self._revoked_evidence: set[str] = set()
        self._consumed_evidence: set[str] = set()
        self._consumed_authorization_epoch = 0
        self._next_advance_authorization_sequence = 0
        self._advance_authorizations: dict[str, tuple[str, str]] = {}

    def adapter_identity_v1(self) -> str:
        return C8_E_CONTRACT_IDENTITY

    def production_session_finished_v1(self) -> bool:
        """Expose only terminal status, never the production session object."""

        return self._session.is_finished

    def session_binding_identity_v1(self) -> str:
        return self._session_identity

    def public_state_identity_v1(self) -> str:
        actions: tuple[LegalAction, ...] = ()
        actor: str | None = None
        if not self._session.is_finished:
            actor = self._session.current_actor_id
            actions = _production_actions(self._session)
        phase_history = self._session.phase_history
        turn_number = phase_history[-1].turn_number
        return _identity(
            {
                "schema": "sgs-c8-e-c6-public-state-identity-v1",
                "contract_version": 1,
                "session_identity": self._session_identity,
                "mode_id": self._session.mode_id,
                "phase": self._session.phase.value,
                "current_actor_id": actor,
                "current_player_id": (
                    None if self._session.is_finished else self._session.current_player_id
                ),
                "turn_number": turn_number,
                "state_revision": self._session.state.revision,
                "step_count": self._session.step_count,
                "production_action_id_commitments_in_proposal_order": [
                    _identity({"production_signed_action_id": item.action_id})
                    for item in actions
                ],
                "private_payload_exposed": False,
            }
        )

    def authoritative_state_identity_v1(self) -> str:
        return _identity(
            {
                "schema": "sgs-c8-e-c6-authoritative-state-identity-v1",
                "contract_version": 1,
                "session_identity": self._session_identity,
                "production_execution_hash": self._session.execution_hash,
            }
        )

    def authenticator_identity_v1(self) -> str:
        return self._issuance_authority_identity

    def anti_replay_state_identity_v1(self) -> str:
        return _identity(
            {
                "schema": "sgs-c8-e-consumed-authorization-ledger-v1",
                "contract_version": 1,
                "session_identity": self._session_identity,
                "consumed_epoch": self._consumed_authorization_epoch,
                "consumed_evidence": sorted(self._consumed_evidence),
            }
        )

    def bind_runtime_v1(
        self,
        runtime: rt.C8TimedSessionRuntimeV1,
        *,
        controller_identity: str,
    ) -> None:
        if type(runtime) is not rt.C8TimedSessionRuntimeV1:
            raise TypeError("C8-E runtime必须是exact C8-B")
        controller = _sha(controller_identity, "controller_identity")
        if self._runtime is not None and self._runtime is not runtime:
            raise C8C6ProductionAdapterError("C8-E adapter禁止cross-runtime rebind")
        if self._controller_identity is not None and self._controller_identity != controller:
            raise C8C6ProductionAdapterError("C8-E controller identity禁止rebind")
        state = runtime.state
        expected = {
            "inner_adapter_identity": self.adapter_identity_v1(),
            "inner_session_binding_identity": self.session_binding_identity_v1(),
            "inner_public_state_identity": self.public_state_identity_v1(),
            "inner_authoritative_state_identity": self.authoritative_state_identity_v1(),
            "input_authenticator_identity": self.authenticator_identity_v1(),
        }
        for name, value in expected.items():
            if getattr(state, name) != value:
                raise C8C6ProductionAdapterError(f"runtime {name}绑定不匹配")
        self._runtime = runtime
        self._controller_identity = controller

    def _bound_runtime_v1(self) -> rt.C8TimedSessionRuntimeV1:
        if self._runtime is None:
            raise C8C6ProductionAdapterError("C8-E尚未绑定C8-B runtime")
        return self._runtime

    def _bound_controller_identity_v1(self) -> str:
        if self._controller_identity is None:
            raise C8C6ProductionAdapterError("C8-E尚未绑定C8-C controller")
        return self._controller_identity

    def _require_controller_guard_v1(self) -> rt.ControllerCallbackSecurityAuditV1:
        audit = self._bound_runtime_v1().controller_callback_security_audit_v1()
        if audit.guard_active is not True:
            raise C8C6ProductionAdapterError("C8-E issuance callback缺少B trusted guard")
        return audit

    def observe_production_decision_context_v1(
        self,
    ) -> ProductionDecisionContextV1:
        if self._session.is_finished:
            raise C8C6ProductionAdapterError("finished C6 session没有decision context")
        actions = _production_actions(self._session)
        history = self._session.phase_history
        if not history:
            raise C8C6ProductionAdapterError("production phase history为空")
        return ProductionDecisionContextV1.build(
            session_identity=self._session_identity,
            phase=self._session.phase,
            current_actor_id=self._session.current_actor_id,
            current_player_id=self._session.current_player_id,
            turn_number=history[-1].turn_number,
            state_revision=self._session.state.revision,
            step_count=self._session.step_count,
            actions=actions,
            parent_context_identity=self._pending_parent_context_identity,
        )

    def bind_window_authority_v1(
        self,
        ref: rt.WindowAuthorityRefV1,
        context: ProductionDecisionContextV1,
    ) -> None:
        runtime = self._bound_runtime_v1()
        if type(ref) is not rt.WindowAuthorityRefV1:
            raise TypeError("window ref必须是exact C8-B authority")
        if type(context) is not ProductionDecisionContextV1:
            raise TypeError("production context类型不匹配")
        current = self.observe_production_decision_context_v1()
        if current != context:
            raise C8C6ProductionAdapterError("decision context已stale")
        active = runtime.active_window_ref()
        if active is None or active != ref:
            raise C8C6ProductionAdapterError("window ref不是current active C8-B authority")
        expected = {
            "runtime_instance_identity": runtime.state.runtime_instance_identity,
            "actor_id": context.current_actor_id,
            "decision_identity": context.decision_identity,
            "obligation_identity": context.obligation_identity,
        }
        for name, value in expected.items():
            if getattr(ref, name) != value:
                raise C8C6ProductionAdapterError(f"window ref {name}绑定不匹配")
        active_window = runtime.state.virtual_time_state.window_stack.active_window
        if active_window is None or active_window.window_kind is not context.window_kind:
            raise C8C6ProductionAdapterError("window kind与production context不匹配")
        self._bound_ref = ref
        self._bound_context = context
        self._current_snapshot = None
        self._current_production_order = None

    def release_window_authority_v1(self, ref: rt.WindowAuthorityRefV1) -> None:
        if self._bound_ref is None or self._bound_ref != ref:
            raise C8C6ProductionAdapterError("释放的window ref不是adapter current binding")
        self._bound_ref = None
        self._bound_context = None
        self._current_snapshot = None
        self._current_production_order = None

    def _require_current_window_context_v1(self) -> ProductionDecisionContextV1:
        if self._bound_ref is None or self._bound_context is None:
            raise C8C6ProductionAdapterError("C8-E尚未绑定production decision window")
        current = self.observe_production_decision_context_v1()
        if current != self._bound_context:
            raise C8C6ProductionAdapterError("production decision context已变化")
        active = self._bound_runtime_v1().active_window_ref()
        if active != self._bound_ref:
            raise C8C6ProductionAdapterError("C8-B active window与adapter binding漂移")
        return current

    def current_adapter_identity_v1(self) -> str:
        return self.adapter_identity_v1()

    def current_session_identity_v1(self) -> str:
        return self.session_binding_identity_v1()

    def current_controller_identity_v1(self) -> str:
        return self._bound_controller_identity_v1()

    def current_public_state_identity_v1(self) -> str:
        return self.public_state_identity_v1()

    def current_authoritative_state_identity_v1(self) -> str:
        return self.authoritative_state_identity_v1()

    def current_issuance_authority_identity_v1(self) -> str:
        return self.authenticator_identity_v1()

    def _issuance_security_ledger_identity_v1(self) -> str:
        return _identity(
            {
                "schema": "sgs-c8-e-issuance-security-ledger-v1",
                "contract_version": 1,
                "session_identity": self._session_identity,
                "next_reservation_sequence": self._next_reservation_sequence,
                "reservations": sorted(
                    (record.evidence_identity, record.status)
                    for record in self._reservations_by_evidence.values()
                ),
                "revoked_evidence": sorted(self._revoked_evidence),
                "consumed_evidence": sorted(self._consumed_evidence),
            }
        )

    def current_issuance_security_ledger_identity_v1(self) -> str:
        return self._issuance_security_ledger_identity_v1()

    def current_consumed_authorization_ledger_identity_v1(self) -> str:
        return self.anti_replay_state_identity_v1()

    def current_public_legal_set_snapshot_identity_v1(self) -> str:
        if self._current_snapshot is None:
            return _identity(
                {
                    "schema": "sgs-c8-e-no-current-public-legal-set-v1",
                    "session_identity": self._session_identity,
                }
            )
        return self._current_snapshot.snapshot_identity

    def current_canonical_public_ordering_identity_v1(self) -> str:
        if self._current_snapshot is None:
            return _identity(
                {
                    "schema": "sgs-c8-e-no-current-ordering-v1",
                    "session_identity": self._session_identity,
                }
            )
        return self._current_snapshot.canonical_public_ordering_identity

    def public_legal_set_evidence_v1(
        self,
    ) -> tuple[ctl.AdapterPublicLegalActionsSnapshotV1, ...]:
        """Return immutable public-only snapshots suitable for replay recording."""

        return tuple(self._public_legal_set_history)

    def public_issuance_evidence_v1(self) -> tuple[dict[str, object], ...]:
        """Return issuance commitments without any live reservation object."""

        return tuple(dict(item) for item in self._public_issuance_history)

    def _project_actions_v1(
        self,
        actions: Sequence[LegalAction],
        context: ProductionDecisionContextV1,
    ) -> c8.PublicLegalSetProjectionV1:
        if self._bound_ref is None:
            raise C8C6ProductionAdapterError("public projection缺少bound window")
        candidates = tuple(
            c8.PublicLegalActionCandidateV1.build(
                window_id=self._bound_ref.window_id,
                actor_id=context.current_actor_id,
                decision_identity=context.decision_identity,
                obligation_identity=context.obligation_identity,
                public_ordinal=index,
                action_id=_text(action.action_id, "production signed action_id"),
                action_family=_family_for_action(action, context),
            )
            for index, action in enumerate(actions)
        )
        return c8.PublicLegalSetProjectionV1.build(
            window_id=self._bound_ref.window_id,
            actor_id=context.current_actor_id,
            decision_identity=context.decision_identity,
            obligation_identity=context.obligation_identity,
            actions=candidates,
            ordering_contract_id=c8.PUBLIC_ORDERING_CONTRACT_ID,
        )

    def fresh_public_legal_actions_v1(
        self,
    ) -> ctl.AdapterPublicLegalActionsSnapshotV1:
        self._require_controller_guard_v1()
        context = self._require_current_window_context_v1()
        actions = _production_actions(self._session)
        actual_order = tuple(_text(item.action_id, "action_id") for item in actions)
        if context.proposal_order_identity != _identity(
            {
                "schema": "sgs-c8-e-production-proposal-order-v1",
                "contract_version": 1,
                "session_identity": self._session_identity,
                "action_ids": list(actual_order),
            }
        ):
            raise C8C6ProductionAdapterError("production proposal order identity漂移")
        public_set = self._project_actions_v1(actions, context)
        runtime = self._bound_runtime_v1()
        assert self._bound_ref is not None
        snapshot = ctl.build_adapter_public_legal_actions_snapshot_v1(
            public_legal_set=public_set,
            runtime_instance_identity=runtime.state.runtime_instance_identity,
            window_authority_ref_identity=self._bound_ref.authority_ref_identity,
            session_identity=self._session_identity,
            controller_identity=self._bound_controller_identity_v1(),
            adapter_identity=C8_E_CONTRACT_IDENTITY,
            public_state_identity=self.public_state_identity_v1(),
            authoritative_state_identity=self.authoritative_state_identity_v1(),
            issuance_security_ledger_identity=(
                self._issuance_security_ledger_identity_v1()
            ),
        )
        self._current_snapshot = snapshot
        self._current_production_order = actual_order
        self._public_legal_set_history.append(snapshot)
        return snapshot

    def _fresh_confirmed_snapshot_v1(
        self,
    ) -> tuple[
        ctl.AdapterPublicLegalActionsSnapshotV1,
        tuple[LegalAction, ...],
        ProductionDecisionContextV1,
    ]:
        context = self._require_current_window_context_v1()
        original = self._current_snapshot
        original_order = self._current_production_order
        if original is None or original_order is None:
            raise C8C6ProductionAdapterError("confirmation缺少fresh public legal set")
        actions = _production_actions(self._session)
        current_order = tuple(_text(item.action_id, "action_id") for item in actions)
        if current_order != original_order:
            raise C8C6ProductionAdapterError("production proposal order已变化")
        public_set = self._project_actions_v1(actions, context)
        runtime = self._bound_runtime_v1()
        assert self._bound_ref is not None
        confirmed = ctl.build_adapter_public_legal_actions_snapshot_v1(
            public_legal_set=public_set,
            runtime_instance_identity=runtime.state.runtime_instance_identity,
            window_authority_ref_identity=self._bound_ref.authority_ref_identity,
            session_identity=self._session_identity,
            controller_identity=self._bound_controller_identity_v1(),
            adapter_identity=C8_E_CONTRACT_IDENTITY,
            public_state_identity=self.public_state_identity_v1(),
            authoritative_state_identity=self.authoritative_state_identity_v1(),
            # Confirmation compares the original gameplay/legal snapshot.
            # Adapter-owned reservation issuance intentionally advances a
            # separate non-rollback ledger after that snapshot was taken.
            issuance_security_ledger_identity=(
                original.issuance_security_ledger_identity
            ),
        )
        if confirmed != original:
            raise C8C6ProductionAdapterError(
                "fresh confirmation与resolver public legal set不一致"
            )
        return confirmed, actions, context

    def confirm_and_issue_signed_action_v1(
        self,
        candidate_reference: str,
        public_ordinal: int,
        legal_set_identity: str,
        timeout_auth_binding: str,
        timeout_due_commitment_identity: str,
    ) -> ctl.SignedActionIssuanceEvidenceV1:
        guard = self._require_controller_guard_v1()
        reference = _text(candidate_reference, "candidate_reference")
        ordinal = _integer(public_ordinal, "public_ordinal")
        _sha(legal_set_identity, "legal_set_identity")
        _sha(timeout_auth_binding, "timeout_auth_binding")
        _sha(timeout_due_commitment_identity, "timeout_due_commitment_identity")
        snapshot, actions, context = self._fresh_confirmed_snapshot_v1()
        if ordinal >= len(actions):
            raise C8C6ProductionAdapterError("public ordinal超出fresh production集合")
        production_action = actions[ordinal]
        candidate = snapshot.public_legal_set.actions[ordinal]
        if production_action.action_id != reference or candidate.action_id != reference:
            raise C8C6ProductionAdapterError("candidate/action_id不属于fresh current ordinal")
        assert self._bound_ref is not None
        runtime = self._bound_runtime_v1()
        expected_bindings = tuple(
            (
                item.candidate_identity,
                item.action_id,
                ctl.timeout_issuance_request_binding_v1(
                    timeout_due_commitment_identity=timeout_due_commitment_identity,
                    runtime_instance_identity=runtime.state.runtime_instance_identity,
                    window_authority_ref_identity=self._bound_ref.authority_ref_identity,
                    session_identity=self._session_identity,
                    controller_identity=self._bound_controller_identity_v1(),
                    adapter_identity=C8_E_CONTRACT_IDENTITY,
                    projection_legal_set_identity=snapshot.projection_legal_set_identity,
                    adapter_legal_set_snapshot_identity=snapshot.snapshot_identity,
                    canonical_public_ordering_identity=(
                        snapshot.canonical_public_ordering_identity
                    ),
                    candidate=item,
                ),
            )
            for item in snapshot.public_legal_set.actions
        )
        binding_by_candidate = {item[0]: item[2] for item in expected_bindings}
        if binding_by_candidate[candidate.candidate_identity] != timeout_auth_binding:
            raise C8C6ProductionAdapterError("candidate timeout binding不匹配")
        binding_set_identity = ctl.timeout_authentication_bindings_identity_v1(
            snapshot.public_legal_set, expected_bindings
        )
        expected_envelope = ctl.build_fresh_public_legal_actions_envelope_v1(
            public_legal_set=snapshot.public_legal_set,
            adapter_legal_set_snapshot_identity=snapshot.snapshot_identity,
            timeout_authentication_bindings_identity=binding_set_identity,
            timeout_due_commitment_identity=timeout_due_commitment_identity,
            runtime_contract_identity=runtime.state.contract_latch.runtime_contract_identity,
            runtime_instance_identity=runtime.state.runtime_instance_identity,
            window_authority_ref_identity=self._bound_ref.authority_ref_identity,
            session_identity=self._session_identity,
            controller_identity=self._bound_controller_identity_v1(),
            adapter_identity=C8_E_CONTRACT_IDENTITY,
            public_state_identity=snapshot.public_state_identity,
            authoritative_state_identity=snapshot.authoritative_state_identity,
            issuance_security_ledger_identity=(
                snapshot.issuance_security_ledger_identity
            ),
        )
        if expected_envelope.legal_set_identity != legal_set_identity:
            raise C8C6ProductionAdapterError("enriched legal set identity不匹配")

        ledger_before = self._issuance_security_ledger_identity_v1()
        sequence = self._next_reservation_sequence
        evidence_identity = _identity(
            {
                "schema": "sgs-c8-e-production-action-authorization-evidence-v1",
                "contract_version": 1,
                "session_identity": self._session_identity,
                "controller_identity": self._bound_controller_identity_v1(),
                "reservation_sequence": sequence,
                "candidate_identity": candidate.candidate_identity,
                "production_signed_action_id": reference,
                "public_ordinal": ordinal,
                "legal_set_identity": legal_set_identity,
                "timeout_auth_binding": timeout_auth_binding,
                "timeout_due_commitment_identity": timeout_due_commitment_identity,
                "context_identity": context.context_identity,
            }
        )
        capability_identity = _identity(
            {
                "schema": "sgs-c8-e-issuance-reservation-capability-v1",
                "contract_version": 1,
                "authorization_evidence_identity": evidence_identity,
                "reservation_sequence": sequence,
                "session_identity": self._session_identity,
                "live_object_required": True,
                "serializable": False,
            }
        )
        capability = _OpaqueIssuanceReservationV1()
        record = _ReservationRecordV1(
            capability=capability,
            capability_identity=capability_identity,
            evidence_identity=evidence_identity,
            signed_action_id=reference,
            candidate_reference=reference,
            public_ordinal=ordinal,
            legal_set_identity=legal_set_identity,
            proposal_order_identity=snapshot.canonical_public_ordering_identity,
            timeout_auth_binding=timeout_auth_binding,
            timeout_due_commitment_identity=timeout_due_commitment_identity,
            context_identity=context.context_identity,
            ledger_before_identity=ledger_before,
            guard_operation_epoch=guard.operation_attempt_epoch,
            issuing_thread_identity=threading.get_ident(),
        )
        self._reservations_by_token[id(capability)] = record
        self._reservations_by_evidence[evidence_identity] = record
        self._next_reservation_sequence += 1
        ledger_after = self._issuance_security_ledger_identity_v1()
        issuance = ctl.build_signed_action_issuance_evidence_v1(
            signed_action_id=reference,
            signed_action_id_commitment=ctl.signed_action_id_commitment_v1(reference),
            external_capability_identity=capability_identity,
            public_action_reference=reference,
            public_ordinal=ordinal,
            candidate_identity=candidate.candidate_identity,
            action_family=candidate.action_family.value,
            legal_set_identity=legal_set_identity,
            canonical_public_ordering_identity=(
                snapshot.canonical_public_ordering_identity
            ),
            timeout_due_commitment_identity=timeout_due_commitment_identity,
            authorization_binding_identity=timeout_auth_binding,
            issuance_authority_identity=self._issuance_authority_identity,
            authorization_evidence_identity=evidence_identity,
            runtime_instance_identity=runtime.state.runtime_instance_identity,
            window_authority_ref_identity=self._bound_ref.authority_ref_identity,
            window_id=self._bound_ref.window_id,
            session_identity=self._session_identity,
            controller_identity=self._bound_controller_identity_v1(),
            adapter_identity=C8_E_CONTRACT_IDENTITY,
            public_state_identity=snapshot.public_state_identity,
            authoritative_state_identity=snapshot.authoritative_state_identity,
            issuance_security_ledger_before_identity=ledger_before,
            issuance_security_ledger_after_identity=ledger_after,
            obligation_completed=True,
            external_capability=capability,
        )
        record.issuance = issuance
        self._public_issuance_history.append(
            {
                **dict(issuance.identity_payload_v1()),
                "issuance_identity": issuance.issuance_identity,
                "serialized_live_authority": False,
            }
        )
        return issuance

    def _reservation_for_token_v1(
        self, capability: object
    ) -> _ReservationRecordV1:
        if type(capability) is not _OpaqueIssuanceReservationV1:
            raise C8C6ProductionAdapterError("issuance reservation必须是strict opaque token")
        record = self._reservations_by_token.get(id(capability))
        if record is None or record.capability is not capability:
            raise C8C6ProductionAdapterError("issuance reservation不是本adapter签发")
        return record

    def abort_pending_issuance_v1(
        self, external_capability: object
    ) -> ctl.UnforwardedIssuanceInvalidationEvidenceV1:
        self._require_controller_guard_v1()
        record = self._reservation_for_token_v1(external_capability)
        if record.status != "PENDING" or record.issuance is None:
            raise C8C6ProductionAdapterError("issuance reservation已消费/撤销，禁止abort")
        before = self._issuance_security_ledger_identity_v1()
        record.status = "REVOKED"
        self._revoked_evidence.add(record.evidence_identity)
        after = self._issuance_security_ledger_identity_v1()
        issuance = record.issuance
        return ctl.build_unforwarded_issuance_invalidation_evidence_v1(
            issuance_identity=issuance.issuance_identity,
            authorization_evidence_identity=record.evidence_identity,
            runtime_instance_identity=issuance.runtime_instance_identity,
            window_authority_ref_identity=issuance.window_authority_ref_identity,
            session_identity=self._session_identity,
            controller_identity=self._bound_controller_identity_v1(),
            adapter_identity=C8_E_CONTRACT_IDENTITY,
            security_ledger_before_identity=before,
            security_ledger_after_identity=after,
            invalidated=True,
        )

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
    ) -> ctl.FailedIssuanceRecoveryEvidenceV1:
        self._require_controller_guard_v1()
        before = _sha(
            issuance_security_ledger_before_identity,
            "issuance_security_ledger_before_identity",
        )
        observed = _sha(
            issuance_security_ledger_observed_after_failure_identity,
            "issuance_security_ledger_observed_after_failure_identity",
        )
        if observed != self._issuance_security_ledger_identity_v1():
            raise C8C6ProductionAdapterError("failed issuance observed ledger不匹配")
        pending = tuple(
            record
            for record in self._reservations_by_evidence.values()
            if record.status == "PENDING"
            and record.ledger_before_identity == before
            and record.legal_set_identity == legal_set_identity
            and record.candidate_reference == candidate_reference
            and record.public_ordinal == public_ordinal
            and record.timeout_auth_binding == timeout_auth_binding
        )
        if not pending:
            raise C8C6ProductionAdapterError("没有可恢复的failed issuance reservation")
        for record in pending:
            record.status = "REVOKED"
            self._revoked_evidence.add(record.evidence_identity)
        after = self._issuance_security_ledger_identity_v1()
        runtime = self._bound_runtime_v1()
        assert self._bound_ref is not None
        recovered_ids = tuple(sorted(record.evidence_identity for record in pending))
        return ctl.build_failed_issuance_recovery_evidence_v1(
            transaction_identity=_sha(transaction_identity, "transaction_identity"),
            legal_set_identity=_sha(legal_set_identity, "legal_set_identity"),
            candidate_reference=_text(candidate_reference, "candidate_reference"),
            public_ordinal=_integer(public_ordinal, "public_ordinal"),
            timeout_auth_binding=_sha(timeout_auth_binding, "timeout_auth_binding"),
            runtime_instance_identity=runtime.state.runtime_instance_identity,
            window_authority_ref_identity=self._bound_ref.authority_ref_identity,
            session_identity=self._session_identity,
            controller_identity=self._bound_controller_identity_v1(),
            adapter_identity=C8_E_CONTRACT_IDENTITY,
            security_ledger_before_identity=before,
            security_ledger_observed_after_failure_identity=observed,
            security_ledger_after_recovery_identity=after,
            recovered_evidence_set_identity=_identity(recovered_ids),
            recovered_evidence_count=len(recovered_ids),
            recovered=True,
        )

    def verify_and_consume_timeout_action_authorization_v1(
        self,
        signed_action_id: str,
        authorization_evidence_identity: str,
        expected_request_binding_identity: str,
    ) -> bool:
        action_id = _text(signed_action_id, "signed_action_id")
        evidence = _sha(
            authorization_evidence_identity, "authorization_evidence_identity"
        )
        binding = _sha(
            expected_request_binding_identity, "expected_request_binding_identity"
        )
        record = self._reservations_by_evidence.get(evidence)
        if record is None or record.status != "PENDING":
            return False
        runtime = self._bound_runtime_v1()
        audit = runtime.controller_callback_security_audit_v1()
        if (
            audit.guard_active
            # B burns one attempt for guard-exit bookkeeping, one for pending
            # capability registration, and one for the forward itself before
            # entering this authenticator callback.
            or audit.operation_attempt_epoch != record.guard_operation_epoch + 3
            or threading.get_ident() != record.issuing_thread_identity
            or action_id != record.signed_action_id
        ):
            return False
        try:
            _, actions, context = self._fresh_confirmed_snapshot_v1()
        except Exception:
            return False
        if (
            context.context_identity != record.context_identity
            or record.public_ordinal >= len(actions)
            or actions[record.public_ordinal].action_id != action_id
        ):
            return False
        record.status = "CONSUMED"
        record.final_b_authorization_binding = binding
        self._consumed_evidence.add(evidence)
        self._consumed_authorization_epoch += 1
        return True

    def issue_virtual_time_advance_v1(
        self, *, requested_tick: int
    ) -> c8.VirtualTimeAdvanceInputV1:
        runtime = self._bound_runtime_v1()
        tick = _integer(requested_tick, "requested_tick")
        state = runtime.state
        active = state.virtual_time_state.window_stack.active_window
        if active is None:
            raise C8C6ProductionAdapterError("virtual time advance缺少active window")
        expected = runtime.expected_advance_authentication_binding(
            requested_tick=tick
        )
        sequence = self._next_advance_authorization_sequence
        evidence = _identity(
            {
                "schema": "sgs-c8-e-virtual-time-advance-authorization-v1",
                "contract_version": 1,
                "session_identity": self._session_identity,
                "runtime_instance_identity": state.runtime_instance_identity,
                "authorization_sequence": sequence,
                "expected_request_binding_identity": expected,
            }
        )
        self._next_advance_authorization_sequence += 1
        self._advance_authorizations[evidence] = (expected, active.window_id)
        return c8.VirtualTimeAdvanceInputV1.issue(
            input_seq=state.virtual_time_state.next_input_seq,
            source_id=state.input_source_id,
            domain_id=c8.CLOCK_DOMAIN_ID,
            window_id=active.window_id,
            requested_tick=tick,
            authentication_evidence_identity=evidence,
        )

    def verify_and_consume_advance_authorization_v1(
        self,
        advance_input: c8.VirtualTimeAdvanceInputV1,
        expected_request_binding_identity: str,
    ) -> bool:
        if type(advance_input) is not c8.VirtualTimeAdvanceInputV1:
            return False
        evidence = advance_input.authentication_evidence_identity
        record = self._advance_authorizations.pop(evidence, None)
        if record is None:
            return False
        self._consumed_evidence.add(evidence)
        self._consumed_authorization_epoch += 1
        return (
            record[0] == expected_request_binding_identity
            and record[1] == advance_input.window_id
        )

    def capture_transaction_snapshot_v1(self) -> object:
        token = self._session.capture_authoritative_transaction_v1()
        production_identity = self._session.authoritative_transaction_token_identity_v1(
            token
        )
        token_identity = _identity(
            {
                "schema": "sgs-c8-e-inner-transaction-token-v1",
                "contract_version": 1,
                "adapter_identity": C8_E_CONTRACT_IDENTITY,
                "session_identity": self._session_identity,
                "production_capability_identity": production_identity,
            }
        )
        self._transaction_sidecars[id(token)] = _AdapterTransactionSidecarV1(
            token=token,
            token_identity=token_identity,
            parent_context_identity=self._pending_parent_context_identity,
        )
        return token

    def _transaction_sidecar_v1(self, token: object) -> _AdapterTransactionSidecarV1:
        sidecar = self._transaction_sidecars.get(id(token))
        if sidecar is None or sidecar.token is not token:
            raise C8C6ProductionAdapterError("inner transaction token不是本adapter签发或已消费")
        return sidecar

    def snapshot_token_identity_v1(self, token: object) -> str:
        sidecar = self._transaction_sidecar_v1(token)
        production_identity = self._session.authoritative_transaction_token_identity_v1(
            token
        )
        expected = _identity(
            {
                "schema": "sgs-c8-e-inner-transaction-token-v1",
                "contract_version": 1,
                "adapter_identity": C8_E_CONTRACT_IDENTITY,
                "session_identity": self._session_identity,
                "production_capability_identity": production_identity,
            }
        )
        if sidecar.token_identity != expected:
            raise C8C6ProductionAdapterError("inner transaction token identity漂移")
        return expected

    def restore_transaction_snapshot_v1(self, token: object) -> None:
        sidecar = self._transaction_sidecar_v1(token)
        del self._transaction_sidecars[id(token)]
        self._session.restore_authoritative_transaction_v1(token)
        self._pending_parent_context_identity = sidecar.parent_context_identity
        self._current_snapshot = None
        self._current_production_order = None

    def commit_transaction_snapshot_v1(self, token: object) -> None:
        self._transaction_sidecar_v1(token)
        del self._transaction_sidecars[id(token)]
        self._session.commit_authoritative_transaction_v1(token)

    def apply_signed_action_id_v1(self, signed_action_id: str) -> None:
        action_id = _text(signed_action_id, "signed_action_id")
        before = self.observe_production_decision_context_v1()
        actions = _production_actions(self._session)
        matches = tuple(item for item in actions if item.action_id == action_id)
        if len(matches) != 1:
            raise C8C6ProductionAdapterError(
                "signed action不在fresh real production legal set"
            )
        # The production step re-enumerates and validates the same signed ID.
        self._session.step(BatchActionIdController(action_id))
        self._current_snapshot = None
        self._current_production_order = None
        if self._session.is_finished:
            self._pending_parent_context_identity = None
            return
        after_phase = self._session.phase
        if (
            after_phase in _OPTIONAL_RESPONSE_PHASES
            or after_phase is ProductionPhase.DYING_RESCUE
            or after_phase in _OPTIONAL_DECISION_PHASES
            or after_phase in _MANDATORY_PRIVATE_CHOICE_PHASES
            or after_phase in _MULTI_STEP_PHASES
        ):
            self._pending_parent_context_identity = before.context_identity
        else:
            self._pending_parent_context_identity = None


class C8C6ProductionWindowOrchestratorV1:
    """Minimal observed-context to C8-B window lifecycle seam."""

    def __init__(
        self,
        adapter: C8C6ProductionAdapterV1,
        runtime: rt.C8TimedSessionRuntimeV1,
    ) -> None:
        if type(adapter) is not C8C6ProductionAdapterV1:
            raise TypeError("window orchestrator需要exact C8-E adapter")
        if type(runtime) is not rt.C8TimedSessionRuntimeV1:
            raise TypeError("window orchestrator需要exact C8-B runtime")
        if adapter._bound_runtime_v1() is not runtime:
            raise C8C6ProductionAdapterError("window orchestrator runtime绑定不一致")
        self._adapter = adapter
        self._runtime = runtime
        self._contexts_by_ref_identity: dict[str, ProductionDecisionContextV1] = {}

    def observe_and_open_or_refresh_v1(
        self,
        *,
        expected_parent_ref: rt.WindowAuthorityRefV1 | None = None,
    ) -> tuple[ProductionDecisionContextV1, rt.WindowAuthorityRefV1, bool]:
        context = self._adapter.observe_production_decision_context_v1()
        active = self._runtime.active_window_ref()
        if active is not None:
            existing = self._contexts_by_ref_identity.get(active.authority_ref_identity)
            if existing == context:
                self._adapter.bind_window_authority_v1(active, context)
                return context, active, False
        if expected_parent_ref is None:
            if active is not None:
                raise C8C6ProductionAdapterError(
                    "top-level production context出现时已有active C8 window"
                )
        else:
            parent = self._contexts_by_ref_identity.get(
                expected_parent_ref.authority_ref_identity
            )
            if parent is None:
                raise C8C6ProductionAdapterError("nested context缺少known parent authority")
            if active != expected_parent_ref:
                raise C8C6ProductionAdapterError("nested context parent不是active top")
            if context.parent_context_identity != parent.context_identity:
                raise C8C6ProductionAdapterError("production child/parent relation不匹配")
        ref = self._runtime.open_window(
            actor_id=context.current_actor_id,
            window_kind=context.window_kind,
            decision_identity=context.decision_identity,
            obligation_identity=context.obligation_identity,
            expected_parent_ref=expected_parent_ref,
        )
        self._contexts_by_ref_identity[ref.authority_ref_identity] = context
        self._adapter.bind_window_authority_v1(ref, context)
        return context, ref, True

    def close_completed_on_time_context_v1(
        self,
        ref: rt.WindowAuthorityRefV1,
        completed_context: ProductionDecisionContextV1,
    ) -> c8.TimedDecisionWindowV1:
        recorded = self._contexts_by_ref_identity.get(ref.authority_ref_identity)
        if recorded != completed_context:
            raise C8C6ProductionAdapterError("completed context/ref binding不匹配")
        if not self._adapter.production_session_finished_v1():
            current = self._adapter.observe_production_decision_context_v1()
            if current.context_identity == completed_context.context_identity:
                raise C8C6ProductionAdapterError("production context尚未完成")
        closed = self._runtime.close_window_by_action(ref)
        self._contexts_by_ref_identity.pop(ref.authority_ref_identity, None)
        self._adapter.release_window_authority_v1(ref)
        return closed

    def confirm_timeout_context_closed_v1(
        self,
        ref: rt.WindowAuthorityRefV1,
        completed_context: ProductionDecisionContextV1,
    ) -> None:
        recorded = self._contexts_by_ref_identity.get(ref.authority_ref_identity)
        if recorded != completed_context:
            raise C8C6ProductionAdapterError("timeout context/ref binding不匹配")
        active_ids = {
            item.window_id
            for item in self._runtime.state.virtual_time_state.window_stack.windows
        }
        if ref.window_id in active_ids:
            raise C8C6ProductionAdapterError("timeout result未关闭production window")
        self._contexts_by_ref_identity.pop(ref.authority_ref_identity, None)
        self._adapter.release_window_authority_v1(ref)


def create_canonical_c6_no_skill_session_v1(
    seed: int,
) -> FormalEightPlayerIdentitySession:
    """Use only the sealed C6 production factory."""

    session = canonical_no_skill_mode_v1(
        FORMAL_NO_SKILL_IDENTITY_8P_MODE
    ).create_session(seed)
    if type(session) is not FormalEightPlayerIdentitySession:
        raise C8C6ProductionAdapterError("canonical C6 factory type漂移")
    return session


def advance_canonical_c6_to_first_play_v1(
    session: FormalEightPlayerIdentitySession,
) -> tuple[str, ...]:
    """Bounded PREPARE/JUDGMENT/DRAW progression through signed normal steps."""

    if type(session) is not FormalEightPlayerIdentitySession:
        raise TypeError("advance helper只接受exact canonical C6 session")
    if session.step_count != 0 or session.phase is not ProductionPhase.PREPARE:
        raise C8C6ProductionAdapterError("advance helper只接受fresh C6 session")
    executed: list[str] = []
    expected = (
        ProductionPhase.PREPARE,
        ProductionPhase.JUDGMENT,
        ProductionPhase.DRAW,
    )
    for phase in expected:
        if session.phase is not phase:
            raise C8C6ProductionAdapterError("bounded automatic phase progression漂移")
        legal = _production_actions(session)
        if len(legal) != 1:
            raise C8C6ProductionAdapterError("automatic phase不是唯一production action")
        action_id = _text(legal[0].action_id, "automatic signed action_id")
        session.step(BatchActionIdController(action_id))
        executed.append(action_id)
    if session.phase is not ProductionPhase.PLAY or session.step_count != 3:
        raise C8C6ProductionAdapterError("bounded progression未到达first PLAY")
    return tuple(executed)


__all__ = [
    "C8C6ProductionAdapterError",
    "C8C6ProductionAdapterV1",
    "C8C6ProductionWindowOrchestratorV1",
    "C8_E_ADAPTER_ID",
    "C8_E_CONTRACT_IDENTITY",
    "C8_E_SCHEMA_VERSION",
    "ProductionContextApplicabilityV1",
    "ProductionDecisionContextV1",
    "advance_canonical_c6_to_first_play_v1",
    "create_canonical_c6_no_skill_session_v1",
    "production_window_context_mapping_v1",
]
