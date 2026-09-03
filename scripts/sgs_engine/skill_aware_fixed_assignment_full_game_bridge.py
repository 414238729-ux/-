# -*- coding: utf-8 -*-
"""Bridge V1 contract, session and public-only acceptance controller.

BRIDGE-A/B provide the frozen contract and opt-in production session. BRIDGE-C
adds a stateless controller that can consume only sanitized signed actions plus
an immutable public context. Full-game replay and acceptance remain out of
scope.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
import re
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from .actions import ActionContext, ActionType, LegalAction
from .formal_duel import (
    FormalDuelConfiguration,
    assert_trusted_formal_configuration,
    deck_identity,
    rules_profile_identity,
)
from .generals import create_authoritative_general_batch_v1_registry
from .engine import canonical_state_snapshot
from .multiplayer import DuelOutcomePolicy
from .production_batch import (
    BatchActionIdController,
    ProductionBasicCardBatch,
    ProductionBatchError,
    ProductionPhase,
)
from .replay import canonical_json, sha256_value, state_sha256
from .skill_impl_v1 import (
    FuyinSkillHandler,
    JiliSkillHandler,
    MingzheSkillHandler,
    QianchongSkillHandler,
    ShangjianSkillHandler,
    WeimuSkillHandler,
    ZuilunSkillHandler,
)
from .skill_registry import AuthoritativeSkillRegistry, create_skill_registry


class BridgeContractError(ValueError):
    """Bridge V1 contract or authority input failed closed."""


class BridgeIdentityError(BridgeContractError):
    """A canonical frozen input does not have the authorized identity."""


BRIDGE_NAME = (
    "POST_AUTHORITATIVE_GENERAL_BATCH_V1_SKILL_AWARE_FIXED_ASSIGNMENT_"
    "FULL_GAME_BRIDGE_V1"
)
CONTRACT_ID = (
    "post-authoritative-general-batch-v1-skill-aware-fixed-assignment-"
    "full-game-bridge-v1"
)
CONTRACT_VERSION = 1
MODE_ID = "skill-aware-fixed-assignment-formal-duel-v1"
REPLAY_SCHEMA = "sgs-skill-aware-fixed-assignment-full-game-bridge-replay-v1"
REPLAY_VERSION = 1
CONTROLLER_ID = "skill-aware-fixed-assignment-acceptance-controller-v1"
CONTROLLER_VERSION = 1

BASELINE_18_SCHEMA = "skill-aware-fixed-assignment-bridge-baseline-matrix-v1"
FORMAL_DUEL_PROFILE_IDENTITY = (
    "9a7b0e9f45c05292a207c500e5b024a77d97b4a6c9446230d81d357c7b514283"
)
DECK_IDENTITY = (
    "e490631698e6b7695c6a9b3ad0c355e421ccfafab696e5b3a97418c9ec80f38b"
)
GENERAL_REGISTRY_IDENTITY = (
    "409ad3daa5169e9c60c5e926ec309ee6b6b0ea2f8830f16ce5928a86d10a9a09"
)
EXPECTED_BRIDGE_SKILL_REGISTRY_IDENTITY = (
    "26d17f5893ee721d5e4209519f35fd38324b41e577485143b41368dadbd4034f"
)
EXPECTED_BASELINE_18_REGISTRY_IDENTITY = (
    "76e5444cd758851059f25a21a884e9af68b8c9ee48d652455561dd91717c56af"
)

GENERAL_ALLOWLIST = ("shamoke", "zhugezhan", "wangyuanji")
BRIDGE_SKILL_ALLOWLIST = (
    "sgs_skill_fuyin",
    "sgs_skill_jili",
    "sgs_skill_mingzhe",
    "sgs_skill_qianchong",
    "sgs_skill_shangjian",
    "sgs_skill_weimu",
    "sgs_skill_zuilun",
)
PARTICIPANT_IDS = ("p1", "p2")
BASELINE_SEEDS = (0, 1, 49)
MAX_STEPS = 2000

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _require_exact_dict(value: object, label: str) -> dict[str, Any]:
    if type(value) is not dict:
        raise BridgeContractError(f"{label}必须是精确JSON object")
    if any(type(key) is not str for key in value):
        raise BridgeContractError(f"{label}字段名必须是精确字符串")
    return value


def _require_exact_fields(
    value: Mapping[str, object], expected: frozenset[str], label: str
) -> None:
    actual = frozenset(value)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise BridgeContractError(
            f"{label}字段必须精确匹配schema；missing={missing}, extra={extra}"
        )


def _require_text(value: object, label: str) -> str:
    if type(value) is not str or not value.strip():
        raise BridgeContractError(f"{label}必须是精确非空字符串")
    return value


def _require_int(value: object, label: str, *, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise BridgeContractError(f"{label}必须是大于等于{minimum}的精确整数")
    return value


def _require_bool(value: object, label: str) -> bool:
    if type(value) is not bool:
        raise BridgeContractError(f"{label}必须是精确布尔值")
    return value


def _require_sha256(value: object, label: str) -> str:
    text = _require_text(value, label)
    if _SHA256_RE.fullmatch(text) is None:
        raise BridgeContractError(f"{label}必须是64位小写SHA-256")
    return text


def _deep_freeze(value: object) -> object:
    if type(value) is dict:
        return MappingProxyType({key: _deep_freeze(item) for key, item in value.items()})
    if type(value) is list:
        return tuple(_deep_freeze(item) for item in value)
    if type(value) is tuple:
        return tuple(_deep_freeze(item) for item in value)
    return value


def _deep_plain(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _deep_plain(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_deep_plain(item) for item in value]
    return value


def _validate_frozen_input_identities() -> None:
    live = (
        ("formal duel profile", rules_profile_identity(), FORMAL_DUEL_PROFILE_IDENTITY),
        ("deck", deck_identity(), DECK_IDENTITY),
    )
    for label, actual, expected in live:
        if actual != expected:
            raise BridgeIdentityError(
                f"{label} identity不一致；expected={expected}, actual={actual}"
            )


def _authoritative_general_registry():
    registry = create_authoritative_general_batch_v1_registry()
    actual = registry.registry_identity
    if actual != GENERAL_REGISTRY_IDENTITY:
        raise BridgeIdentityError(
            "General registry identity不一致；"
            f"expected={GENERAL_REGISTRY_IDENTITY}, actual={actual}"
        )
    actual_keys = tuple(key for key in GENERAL_ALLOWLIST if registry.has_general(key))
    if actual_keys != GENERAL_ALLOWLIST:
        raise BridgeIdentityError("General registry未覆盖Bridge exact General allowlist")
    return registry


@dataclass(frozen=True, slots=True)
class BridgeGeneralDescriptor:
    """Semantic payload derived from, and checked against, the frozen registry."""

    general_key: str
    profile_identity: str
    gender: str
    starting_hp: int
    max_hp: int
    base_skill_ids: tuple[str, ...]
    canonical_source_payload: object

    def to_dict(self) -> dict[str, object]:
        return {
            "general_key": self.general_key,
            "profile_identity": self.profile_identity,
            "gender": self.gender,
            "starting_hp": self.starting_hp,
            "max_hp": self.max_hp,
            "base_skill_ids": list(self.base_skill_ids),
            "canonical_source_payload": _deep_plain(self.canonical_source_payload),
        }


def _derive_general_descriptors() -> tuple[BridgeGeneralDescriptor, ...]:
    registry = _authoritative_general_registry()
    descriptors: list[BridgeGeneralDescriptor] = []
    for general_key in GENERAL_ALLOWLIST:
        general = registry.get_general(general_key)
        descriptors.append(
            BridgeGeneralDescriptor(
                general_key=general.general_key,
                profile_identity=general.profile_identity,
                gender=general.gender.value,
                starting_hp=general.starting_hp,
                max_hp=general.max_hp,
                base_skill_ids=general.skill_ids,
                canonical_source_payload=_deep_freeze(general.to_dict()),
            )
        )
    return tuple(descriptors)


GENERAL_ALLOWLIST_DESCRIPTORS = _derive_general_descriptors()
_GENERAL_BY_KEY = MappingProxyType(
    {item.general_key: item for item in GENERAL_ALLOWLIST_DESCRIPTORS}
)


def general_descriptor(general_key: object) -> BridgeGeneralDescriptor:
    key = _require_text(general_key, "General key")
    try:
        return _GENERAL_BY_KEY[key]
    except KeyError as exc:
        raise BridgeContractError(f"Bridge V1拒绝未知General：{key!r}") from exc


def create_bridge_skill_registry() -> AuthoritativeSkillRegistry:
    """Build the dedicated seven-skill registry without reusing proof registry."""

    registry = create_skill_registry(
        (
            FuyinSkillHandler(),
            JiliSkillHandler(),
            MingzheSkillHandler(),
            QianchongSkillHandler(),
            ShangjianSkillHandler(),
            WeimuSkillHandler(),
            ZuilunSkillHandler(),
        )
    )
    if registry.skill_ids != BRIDGE_SKILL_ALLOWLIST:
        raise BridgeIdentityError(
            "Bridge dedicated Skill Registry与exact allowlist不一致"
        )
    if registry.registry_identity != EXPECTED_BRIDGE_SKILL_REGISTRY_IDENTITY:
        raise BridgeIdentityError(
            "Bridge Skill Registry identity推导不一致；"
            f"expected={EXPECTED_BRIDGE_SKILL_REGISTRY_IDENTITY}, "
            f"actual={registry.registry_identity}"
        )
    return registry


def validate_bridge_skill_id(skill_id: object) -> str:
    value = _require_text(skill_id, "skill_id")
    if value not in BRIDGE_SKILL_ALLOWLIST:
        raise BridgeContractError(f"Bridge V1拒绝非allowlisted skill：{value!r}")
    return value


BRIDGE_SKILL_REGISTRY_IDENTITY = create_bridge_skill_registry().registry_identity


class ParticipantId(str, Enum):
    P1 = "p1"
    P2 = "p2"


class FixedAssignment(str, Enum):
    GENERAL_AS_P1 = "GENERAL_AS_P1"
    GENERAL_AS_P2 = "GENERAL_AS_P2"


class ParticipantKind(str, Enum):
    GENERAL = "GENERAL"
    NO_SKILL_SOLDIER = "NO_SKILL_SOLDIER"


class ModeModifier(str, Enum):
    NONE = "NONE"


class EquipmentColorState(str, Enum):
    EMPTY = "empty"
    MIXED = "mixed"
    ALL_BLACK = "all_black"
    ALL_RED = "all_red"


class WitnessStatus(str, Enum):
    NOT_REQUIRED = "NOT_REQUIRED"
    REQUIRED = "REQUIRED"
    PROVEN = "PROVEN"


class SentinelDiscoveryStatus(str, Enum):
    UNDISCOVERED = "UNDISCOVERED"


class UnknownAuthorityFieldPolicy(str, Enum):
    REJECT = "REJECT"


@dataclass(frozen=True, slots=True)
class BaseSkillBinding:
    general_key: str
    base_skill_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "general_key": self.general_key,
            "base_skill_ids": list(self.base_skill_ids),
        }


@dataclass(frozen=True, slots=True)
class BaseSkillAuthorityDescriptor:
    source_registry_identity: str
    bindings: tuple[BaseSkillBinding, ...]

    def skills_for(self, general_key: object | None) -> tuple[str, ...]:
        if general_key is None:
            return ()
        descriptor = general_descriptor(general_key)
        for binding in self.bindings:
            if binding.general_key == descriptor.general_key:
                return binding.base_skill_ids
        raise BridgeContractError("BASE_SKILL_AUTHORITY缺少allowlisted General")

    def to_dict(self) -> dict[str, object]:
        return {
            "source_registry_identity": self.source_registry_identity,
            "bindings": [binding.to_dict() for binding in self.bindings],
            "caller_supplied_base_skills": "REJECT",
        }


BASE_SKILL_AUTHORITY = BaseSkillAuthorityDescriptor(
    source_registry_identity=GENERAL_REGISTRY_IDENTITY,
    bindings=tuple(
        BaseSkillBinding(item.general_key, item.base_skill_ids)
        for item in GENERAL_ALLOWLIST_DESCRIPTORS
    ),
)


@dataclass(frozen=True, slots=True)
class DynamicDerivationRule:
    source_skill_id: str
    equipment_state: EquipmentColorState
    granted_skill_id: str

    def to_dict(self) -> dict[str, str]:
        return {
            "source_skill_id": self.source_skill_id,
            "equipment_state": self.equipment_state.value,
            "granted_skill_id": self.granted_skill_id,
        }


@dataclass(frozen=True, slots=True)
class DynamicDerivationAuthorityDescriptor:
    rules: tuple[DynamicDerivationRule, ...]
    no_grant_states: tuple[EquipmentColorState, ...]

    def derive(
        self, general_key: object | None, equipment_state: EquipmentColorState
    ) -> tuple[str, ...]:
        if not isinstance(equipment_state, EquipmentColorState):
            raise BridgeContractError("equipment_state必须是EquipmentColorState")
        base = BASE_SKILL_AUTHORITY.skills_for(general_key)
        if "sgs_skill_qianchong" not in base:
            return ()
        for rule in self.rules:
            if rule.equipment_state is equipment_state:
                return (rule.granted_skill_id,)
        if equipment_state in self.no_grant_states:
            return ()
        raise BridgeContractError("未定义的Qianchong dynamic derivation state")

    def validate_claim(
        self,
        *,
        general_key: object | None,
        equipment_state: EquipmentColorState,
        source_skill_id: object | None,
        granted_skill_ids: tuple[str, ...],
    ) -> tuple[str, ...]:
        if type(granted_skill_ids) is not tuple or any(
            type(item) is not str for item in granted_skill_ids
        ):
            raise BridgeContractError("dynamic granted_skill_ids必须是精确字符串tuple")
        if len(granted_skill_ids) != len(set(granted_skill_ids)):
            raise BridgeContractError("dynamic grant不得重复")
        if len(granted_skill_ids) > 1:
            raise BridgeContractError("Bridge V1禁止双dynamic grant")
        expected = self.derive(general_key, equipment_state)
        expected_source = "sgs_skill_qianchong" if expected else None
        if source_skill_id != expected_source or granted_skill_ids != expected:
            raise BridgeContractError(
                "caller supplied dynamic skill/source与唯一合法派生不一致"
            )
        return expected

    def to_dict(self) -> dict[str, object]:
        return {
            "rules": [rule.to_dict() for rule in self.rules],
            "no_grant_states": [state.value for state in self.no_grant_states],
            "no_qianchong": "none",
            "caller_supplied_grants": "REJECT",
            "dual_grant": "REJECT",
        }


DYNAMIC_DERIVATION_AUTHORITY = DynamicDerivationAuthorityDescriptor(
    rules=(
        DynamicDerivationRule(
            "sgs_skill_qianchong",
            EquipmentColorState.ALL_BLACK,
            "sgs_skill_weimu",
        ),
        DynamicDerivationRule(
            "sgs_skill_qianchong",
            EquipmentColorState.ALL_RED,
            "sgs_skill_mingzhe",
        ),
    ),
    no_grant_states=(EquipmentColorState.EMPTY, EquipmentColorState.MIXED),
)


@dataclass(frozen=True, slots=True)
class RuntimeEffectiveAuthorityDescriptor:
    invariant: str = "effective = base + currently-valid dynamic-derived skills"

    def expected(
        self, general_key: object | None, equipment_state: EquipmentColorState
    ) -> tuple[str, ...]:
        return BASE_SKILL_AUTHORITY.skills_for(general_key) + (
            DYNAMIC_DERIVATION_AUTHORITY.derive(general_key, equipment_state)
        )

    def validate(
        self,
        *,
        general_key: object | None,
        equipment_state: EquipmentColorState,
        effective_skill_ids: tuple[str, ...],
    ) -> tuple[str, ...]:
        if type(effective_skill_ids) is not tuple or any(
            type(item) is not str for item in effective_skill_ids
        ):
            raise BridgeContractError("effective_skill_ids必须是精确字符串tuple")
        expected = self.expected(general_key, equipment_state)
        if effective_skill_ids != expected:
            raise BridgeContractError("runtime effective skills与Bridge invariant不一致")
        return expected

    def to_dict(self) -> dict[str, object]:
        return {"invariant": self.invariant, "live_reconcile": "BRIDGE-B"}


RUNTIME_EFFECTIVE_AUTHORITY = RuntimeEffectiveAuthorityDescriptor()


@dataclass(frozen=True, slots=True)
class ParticipantDescriptor:
    player_id: str
    participant_kind: ParticipantKind
    character_key: str
    gender: str
    hp: int
    max_hp: int
    skill_ids: tuple[str, ...]
    general_key: str | None
    profile_identity: str | None

    def __post_init__(self) -> None:
        if self.player_id not in PARTICIPANT_IDS:
            raise BridgeContractError(f"未知participant：{self.player_id!r}")
        if not isinstance(self.participant_kind, ParticipantKind):
            raise BridgeContractError("participant_kind必须是ParticipantKind")
        _require_text(self.character_key, "character_key")
        _require_text(self.gender, "gender")
        _require_int(self.hp, "hp", minimum=1)
        _require_int(self.max_hp, "max_hp", minimum=1)
        if self.hp > self.max_hp:
            raise BridgeContractError("participant hp不能高于max_hp")
        if type(self.skill_ids) is not tuple or any(
            type(item) is not str for item in self.skill_ids
        ):
            raise BridgeContractError("participant skill_ids必须是精确字符串tuple")
        if self.participant_kind is ParticipantKind.GENERAL:
            authoritative = general_descriptor(self.general_key)
            actual = (
                self.character_key,
                self.gender,
                self.hp,
                self.max_hp,
                self.skill_ids,
                self.profile_identity,
            )
            expected = (
                authoritative.general_key,
                authoritative.gender,
                authoritative.starting_hp,
                authoritative.max_hp,
                authoritative.base_skill_ids,
                authoritative.profile_identity,
            )
            if actual != expected:
                raise BridgeContractError(
                    "General participant必须由frozen General registry精确派生"
                )
        else:
            profile = FormalDuelConfiguration.formal_profile()
            soldier = profile.participants[0]
            if soldier is None:
                raise BridgeIdentityError("formal duel canonical soldier metadata缺失")
            expected_soldier = (
                soldier.character_key,
                soldier.effective_gender.value,
                profile.player_hp[0],
                profile.player_max_hp[0],
                (),
                None,
                None,
            )
            actual_soldier = (
                self.character_key,
                self.gender,
                self.hp,
                self.max_hp,
                self.skill_ids,
                self.general_key,
                self.profile_identity,
            )
            if actual_soldier != expected_soldier:
                raise BridgeContractError(
                    "no-skill participant必须由formal duel soldier authority精确派生"
                )

    def to_dict(self) -> dict[str, object]:
        return {
            "player_id": self.player_id,
            "participant_kind": self.participant_kind.value,
            "character_key": self.character_key,
            "gender": self.gender,
            "hp": self.hp,
            "max_hp": self.max_hp,
            "skill_ids": list(self.skill_ids),
            "general_key": self.general_key,
            "profile_identity": self.profile_identity,
        }

    @classmethod
    def from_dict(cls, value: object) -> "ParticipantDescriptor":
        data = _require_exact_dict(value, "participant")
        fields = frozenset(
            {
                "player_id",
                "participant_kind",
                "character_key",
                "gender",
                "hp",
                "max_hp",
                "skill_ids",
                "general_key",
                "profile_identity",
            }
        )
        _require_exact_fields(data, fields, "participant")
        raw_skills = data["skill_ids"]
        if type(raw_skills) is not list or any(type(item) is not str for item in raw_skills):
            raise BridgeContractError("participant skill_ids必须是精确JSON array")
        try:
            kind = ParticipantKind(_require_text(data["participant_kind"], "participant_kind"))
        except ValueError as exc:
            raise BridgeContractError("未知participant_kind") from exc
        for optional in ("general_key", "profile_identity"):
            if data[optional] is not None and type(data[optional]) is not str:
                raise BridgeContractError(f"participant {optional}必须是字符串或null")
        return cls(
            player_id=_require_text(data["player_id"], "player_id"),
            participant_kind=kind,
            character_key=_require_text(data["character_key"], "character_key"),
            gender=_require_text(data["gender"], "gender"),
            hp=_require_int(data["hp"], "hp", minimum=1),
            max_hp=_require_int(data["max_hp"], "max_hp", minimum=1),
            skill_ids=tuple(raw_skills),
            general_key=data["general_key"],
            profile_identity=data["profile_identity"],
        )


def _assignment_enum(value: object) -> FixedAssignment:
    text = _require_text(value, "seat_assignment")
    try:
        return FixedAssignment(text)
    except ValueError as exc:
        raise BridgeContractError(f"未知或非固定assignment：{text!r}") from exc


def _authoritative_assignment_participants(
    general_key: str, seat_assignment: FixedAssignment
) -> tuple[ParticipantDescriptor, ParticipantDescriptor]:
    general = general_descriptor(general_key)
    profile = FormalDuelConfiguration.formal_profile()
    if rules_profile_identity() != FORMAL_DUEL_PROFILE_IDENTITY:
        raise BridgeIdentityError("formal duel profile identity在assignment构造时漂移")
    soldier_metadata = profile.participants[0]
    if soldier_metadata is None:
        raise BridgeIdentityError("formal duel canonical soldier metadata缺失")
    if seat_assignment is FixedAssignment.GENERAL_AS_P1:
        general_player, soldier_player = "p1", "p2"
    elif seat_assignment is FixedAssignment.GENERAL_AS_P2:
        general_player, soldier_player = "p2", "p1"
    else:  # pragma: no cover - enum exhaustiveness guard
        raise BridgeContractError("Bridge V1只允许两种fixed assignment")
    general_participant = ParticipantDescriptor(
        player_id=general_player,
        participant_kind=ParticipantKind.GENERAL,
        character_key=general.general_key,
        gender=general.gender,
        hp=general.starting_hp,
        max_hp=general.max_hp,
        skill_ids=general.base_skill_ids,
        general_key=general.general_key,
        profile_identity=general.profile_identity,
    )
    soldier_participant = ParticipantDescriptor(
        player_id=soldier_player,
        participant_kind=ParticipantKind.NO_SKILL_SOLDIER,
        character_key=soldier_metadata.character_key,
        gender=soldier_metadata.effective_gender.value,
        hp=profile.player_hp[0],
        max_hp=profile.player_max_hp[0],
        skill_ids=(),
        general_key=None,
        profile_identity=None,
    )
    return tuple(
        sorted((general_participant, soldier_participant), key=lambda item: item.player_id)
    )  # type: ignore[return-value]


@dataclass(frozen=True, slots=True)
class BridgeAssignmentDescriptor:
    general_key: str
    seat_assignment: FixedAssignment
    participants: tuple[ParticipantDescriptor, ParticipantDescriptor]

    def __post_init__(self) -> None:
        general_descriptor(self.general_key)
        if not isinstance(self.seat_assignment, FixedAssignment):
            raise BridgeContractError("seat_assignment必须是FixedAssignment")
        if type(self.participants) is not tuple or len(self.participants) != 2:
            raise BridgeContractError("assignment必须恰好包含p1/p2两名participant")
        expected = _authoritative_assignment_participants(
            self.general_key, self.seat_assignment
        )
        if self.participants != expected:
            raise BridgeContractError(
                "assignment participant/stats/skills必须由frozen authority精确派生"
            )

    @property
    def general_player_id(self) -> str:
        return "p1" if self.seat_assignment is FixedAssignment.GENERAL_AS_P1 else "p2"

    @property
    def no_skill_player_id(self) -> str:
        return "p2" if self.general_player_id == "p1" else "p1"

    def to_dict(self) -> dict[str, object]:
        return {
            "general_key": self.general_key,
            "seat_assignment": self.seat_assignment.value,
            "general_player_id": self.general_player_id,
            "no_skill_player_id": self.no_skill_player_id,
            "participants": [item.to_dict() for item in self.participants],
        }

    @classmethod
    def from_dict(cls, value: object) -> "BridgeAssignmentDescriptor":
        data = _require_exact_dict(value, "Bridge assignment")
        fields = frozenset(
            {
                "general_key",
                "seat_assignment",
                "general_player_id",
                "no_skill_player_id",
                "participants",
            }
        )
        _require_exact_fields(data, fields, "Bridge assignment")
        raw_participants = data["participants"]
        if type(raw_participants) is not list:
            raise BridgeContractError("Bridge assignment participants必须是JSON array")
        descriptor = cls(
            general_key=_require_text(data["general_key"], "general_key"),
            seat_assignment=_assignment_enum(data["seat_assignment"]),
            participants=tuple(
                ParticipantDescriptor.from_dict(item) for item in raw_participants
            ),  # type: ignore[arg-type]
        )
        if data["general_player_id"] != descriptor.general_player_id:
            raise BridgeContractError("general_player_id与fixed assignment不一致")
        if data["no_skill_player_id"] != descriptor.no_skill_player_id:
            raise BridgeContractError("no_skill_player_id与fixed assignment不一致")
        return descriptor


def create_bridge_assignment(
    general_key: object, seat_assignment: FixedAssignment | str
) -> BridgeAssignmentDescriptor:
    key = general_descriptor(general_key).general_key
    assignment = (
        seat_assignment
        if isinstance(seat_assignment, FixedAssignment)
        else _assignment_enum(seat_assignment)
    )
    return BridgeAssignmentDescriptor(
        key,
        assignment,
        _authoritative_assignment_participants(key, assignment),
    )


def create_bridge_assignment_from_request(value: object) -> BridgeAssignmentDescriptor:
    data = _require_exact_dict(value, "Bridge assignment request")
    _require_exact_fields(
        data, frozenset({"general_key", "seat_assignment"}), "Bridge assignment request"
    )
    return create_bridge_assignment(data["general_key"], data["seat_assignment"])


@dataclass(frozen=True, slots=True)
class BaselineCellDescriptor:
    cell_id: str
    general_key: str
    seat_assignment: FixedAssignment
    general_player_id: str
    no_skill_player_id: str
    seed: int
    analysis_only: bool = False
    fixture: bool = False
    premutation: bool = False
    manual_event_injection: bool = False
    max_steps: int = MAX_STEPS
    mode_modifier: ModeModifier = ModeModifier.NONE

    def __post_init__(self) -> None:
        _require_text(self.cell_id, "cell_id")
        if re.fullmatch(r"B18-[0-9]{3}", self.cell_id) is None:
            raise BridgeContractError("BASELINE_18 cell_id必须匹配B18-NNN")
        if not isinstance(self.seat_assignment, FixedAssignment):
            raise BridgeContractError("baseline seat_assignment必须是FixedAssignment")
        assignment = create_bridge_assignment(self.general_key, self.seat_assignment)
        if self.general_player_id != assignment.general_player_id:
            raise BridgeContractError("baseline general_player_id与assignment不一致")
        if self.no_skill_player_id != assignment.no_skill_player_id:
            raise BridgeContractError("baseline no_skill_player_id与assignment不一致")
        _require_int(self.seed, "seed")
        if self.seed not in BASELINE_SEEDS:
            raise BridgeContractError("BASELINE_18 seed必须是0/1/49")
        for field_name in (
            "analysis_only",
            "fixture",
            "premutation",
            "manual_event_injection",
        ):
            if _require_bool(getattr(self, field_name), field_name) is not False:
                raise BridgeContractError(f"BASELINE_18禁止{field_name}=true")
        if type(self.max_steps) is not int or self.max_steps != MAX_STEPS:
            raise BridgeContractError("BASELINE_18 max_steps必须精确为2000")
        if self.mode_modifier is not ModeModifier.NONE:
            raise BridgeContractError("Bridge V1 mode modifier必须为NONE")

    def to_registry_descriptor(self) -> dict[str, object]:
        """Authorized canonical payload used by the frozen B18 registry hash."""

        return {
            "cell_id": self.cell_id,
            "general_key": self.general_key,
            "seat_assignment": self.seat_assignment.value,
            "general_player_id": self.general_player_id,
            "no_skill_player_id": self.no_skill_player_id,
            "seed": self.seed,
        }

    def to_contract_dict(self) -> dict[str, object]:
        value = self.to_registry_descriptor()
        value.update(
            {
                "analysis_only": self.analysis_only,
                "fixture": self.fixture,
                "premutation": self.premutation,
                "manual_event_injection": self.manual_event_injection,
                "max_steps": self.max_steps,
                "mode_modifier": self.mode_modifier.value,
            }
        )
        return value


def _create_baseline_18() -> tuple[BaselineCellDescriptor, ...]:
    cells: list[BaselineCellDescriptor] = []
    index = 1
    for general_key in GENERAL_ALLOWLIST:
        for assignment in (
            FixedAssignment.GENERAL_AS_P1,
            FixedAssignment.GENERAL_AS_P2,
        ):
            resolved = create_bridge_assignment(general_key, assignment)
            for seed in BASELINE_SEEDS:
                cells.append(
                    BaselineCellDescriptor(
                        cell_id=f"B18-{index:03d}",
                        general_key=general_key,
                        seat_assignment=assignment,
                        general_player_id=resolved.general_player_id,
                        no_skill_player_id=resolved.no_skill_player_id,
                        seed=seed,
                    )
                )
                index += 1
    return tuple(cells)


BASELINE_18 = _create_baseline_18()


def baseline_18_canonical_descriptor() -> dict[str, object]:
    return {
        "schema": BASELINE_18_SCHEMA,
        "contract_id": CONTRACT_ID,
        "cells": [cell.to_registry_descriptor() for cell in BASELINE_18],
    }


def compute_baseline_18_registry_identity() -> str:
    return sha256_value(baseline_18_canonical_descriptor())


BASELINE_18_REGISTRY_IDENTITY = compute_baseline_18_registry_identity()
if BASELINE_18_REGISTRY_IDENTITY != EXPECTED_BASELINE_18_REGISTRY_IDENTITY:
    raise BridgeIdentityError(
        "BASELINE_18 identity derivation discrepancy；"
        f"expected={EXPECTED_BASELINE_18_REGISTRY_IDENTITY}, "
        f"actual={BASELINE_18_REGISTRY_IDENTITY}"
    )


class InitializationStep(str, Enum):
    VALIDATE_FORMAL_PROFILE = "validate_formal_profile"
    VALIDATE_ASSIGNMENT = "validate_assignment"
    DERIVE_GENERAL_STATS = "derive_general_stats"
    APPLY_MODE_MODIFIER_NONE = "apply_mode_modifier_none"
    FIRST_PLAYER_RNG = "first_player_rng"
    SHUFFLE_AND_DEAL = "shuffle_and_deal"
    DERIVE_BASE_SKILLS = "derive_base_skills"
    INITIAL_QIANCHONG_RECONCILE = "initial_qianchong_reconcile"
    SIGN_INITIAL_STATE = "sign_initial_state"
    ENUMERATE_FIRST_LEGAL_SET = "enumerate_first_legal_set"


INITIALIZATION_SEQUENCE = tuple(InitializationStep)
INITIALIZATION_PROHIBITIONS = (
    "initial_deal_not_in_turn_loss_ledger",
    "initialization_does_not_call_gameplay_skill_dispatcher",
    "initialization_does_not_trigger_jili",
    "initialization_does_not_trigger_zuilun",
    "initialization_does_not_trigger_fuyin",
    "initialization_does_not_trigger_mingzhe",
    "initialization_does_not_trigger_shangjian",
    "qianchong_initial_reconcile_is_eventless",
)


@dataclass(frozen=True, slots=True)
class InitializationAuthorityDescriptor:
    sequence: tuple[InitializationStep, ...]
    prohibitions: tuple[str, ...]
    mode_modifier: ModeModifier
    live_execution_stage: str

    def to_dict(self) -> dict[str, object]:
        return {
            "sequence": [step.value for step in self.sequence],
            "prohibitions": list(self.prohibitions),
            "mode_modifier": self.mode_modifier.value,
            "live_execution_stage": self.live_execution_stage,
        }


INITIALIZATION_CONTRACT = InitializationAuthorityDescriptor(
    INITIALIZATION_SEQUENCE,
    INITIALIZATION_PROHIBITIONS,
    ModeModifier.NONE,
    "BRIDGE-B",
)
INITIALIZATION_SEQUENCE_IDENTITY = sha256_value(INITIALIZATION_CONTRACT.to_dict())


@dataclass(frozen=True, slots=True)
class EventObligationDescriptor:
    event_id: str
    general_key: str
    requirement_scope: str
    witness_obligation: str
    initial_status: WitnessStatus = WitnessStatus.REQUIRED

    def __post_init__(self) -> None:
        _require_text(self.event_id, "event_id")
        general_descriptor(self.general_key)
        _require_text(self.requirement_scope, "requirement_scope")
        _require_text(self.witness_obligation, "witness_obligation")
        if self.initial_status is WitnessStatus.PROVEN:
            raise BridgeContractError("BRIDGE-A不得把event obligation标为PROVEN")

    def to_dict(self) -> dict[str, str]:
        return {
            "event_id": self.event_id,
            "general_key": self.general_key,
            "requirement_scope": self.requirement_scope,
            "witness_obligation": self.witness_obligation,
            "initial_status": self.initial_status.value,
        }


EVENT_OBLIGATIONS = (
    EventObligationDescriptor(
        "EV-G1-JILI-01",
        "shamoke",
        "aggregate_general_natural_full_game",
        "natural checkpoint with signed Jili ACTIVATE/PASS before continuation",
    ),
    EventObligationDescriptor(
        "EV-G2-ZUILUN-01",
        "zhugezhan",
        "aggregate_general_natural_full_game",
        "real END_PHASE_STARTED with signed Zuilun ACTIVATE/PASS opportunity",
    ),
    EventObligationDescriptor(
        "EV-G2-FUYIN-01",
        "zhugezhan",
        "aggregate_general_natural_full_game",
        "first natural Slash/Duel target consumption in an independent turn",
    ),
    EventObligationDescriptor(
        "EV-G3-QIANCHONG-01",
        "wangyuanji",
        "aggregate_general_natural_full_game",
        "authenticated initial reconcile plus category choice or real dynamic transition",
    ),
    EventObligationDescriptor(
        "EV-G3-SHANGJIAN-01",
        "wangyuanji",
        "aggregate_general_natural_full_game",
        "real END_PHASE_STARTED evaluation derived from TurnLossLedger and live HP",
    ),
)
EVENT_OBLIGATION_IDS = tuple(item.event_id for item in EVENT_OBLIGATIONS)
BASELINE_18_WITNESS_OBLIGATIONS_STATUS = WitnessStatus.REQUIRED


@dataclass(frozen=True, slots=True)
class SentinelPolicyDescriptor:
    seed_min: int
    seed_max: int
    excluded_seeds: tuple[int, ...]
    general_order: tuple[str, ...]
    seat_order: tuple[FixedAssignment, ...]
    seed_order: str
    selection_rule: str
    inclusion_minimal: bool
    discovery_is_formal_evidence: bool
    frozen_failure_may_replace_seed: bool

    def validate_candidate(
        self,
        *,
        general_key: object,
        seat_assignment: FixedAssignment | str,
        seed: object,
        closes_event_ids: tuple[str, ...],
    ) -> None:
        general_descriptor(general_key)
        assignment = (
            seat_assignment
            if isinstance(seat_assignment, FixedAssignment)
            else _assignment_enum(seat_assignment)
        )
        if assignment not in self.seat_order:
            raise BridgeContractError("sentinel seat不在frozen order")
        actual_seed = _require_int(seed, "sentinel seed")
        if not self.seed_min <= actual_seed <= self.seed_max:
            raise BridgeContractError("sentinel seed必须在0..99")
        if actual_seed in self.excluded_seeds:
            raise BridgeContractError("sentinel seed不得复用BASELINE_18 seed")
        if type(closes_event_ids) is not tuple or not closes_event_ids:
            raise BridgeContractError("sentinel必须关闭至少一个uncovered REQUIRED event")
        if any(event_id not in EVENT_OBLIGATION_IDS for event_id in closes_event_ids):
            raise BridgeContractError("sentinel closes_event_ids包含未知event")

    def to_dict(self) -> dict[str, object]:
        return {
            "seed_range": [self.seed_min, self.seed_max],
            "excluded_seeds": list(self.excluded_seeds),
            "general_order": list(self.general_order),
            "seat_order": [item.value for item in self.seat_order],
            "seed_order": self.seed_order,
            "selection_rule": self.selection_rule,
            "inclusion_minimal": self.inclusion_minimal,
            "discovery_is_formal_evidence": self.discovery_is_formal_evidence,
            "frozen_failure_may_replace_seed": self.frozen_failure_may_replace_seed,
        }


SENTINEL_POLICY = SentinelPolicyDescriptor(
    seed_min=0,
    seed_max=99,
    excluded_seeds=BASELINE_SEEDS,
    general_order=GENERAL_ALLOWLIST,
    seat_order=(FixedAssignment.GENERAL_AS_P1, FixedAssignment.GENERAL_AS_P2),
    seed_order="ascending",
    selection_rule="selected only if closes uncovered REQUIRED event",
    inclusion_minimal=True,
    discovery_is_formal_evidence=False,
    frozen_failure_may_replace_seed=False,
)
MINIMAL_REQUIRED_SENTINELS = SentinelDiscoveryStatus.UNDISCOVERED
FINAL_ACCEPTANCE_MATRIX = "BASELINE_18 + UNDISCOVERED_SENTINELS"


PRIVATE_SELECTION_ALLOWED_FIELDS = frozenset(
    {"choice_token", "ordinal", "action_id", "publicly_allowed_action_type"}
)
PRIVATE_SELECTION_FORBIDDEN_FIELDS = frozenset(
    {
        "card_id",
        "card_identity",
        "card_name",
        "suit",
        "rank",
        "card_value",
        "private_payload",
        "private_semantic_value",
        "future_cards",
        "deck_contents",
        "draw_pile",
    }
)


@dataclass(frozen=True, slots=True)
class PublicOpaqueChoiceProjection:
    choice_token: str
    ordinal: int
    action_id: str
    publicly_allowed_action_type: str

    def __post_init__(self) -> None:
        _require_text(self.choice_token, "choice_token")
        _require_int(self.ordinal, "ordinal")
        _require_text(self.action_id, "action_id")
        _require_text(
            self.publicly_allowed_action_type, "publicly_allowed_action_type"
        )

    @classmethod
    def from_dict(cls, value: object) -> "PublicOpaqueChoiceProjection":
        data = _require_exact_dict(value, "public opaque choice projection")
        if frozenset(data) & PRIVATE_SELECTION_FORBIDDEN_FIELDS:
            raise BridgeContractError("public controller projection包含private card payload")
        _require_exact_fields(
            data,
            PRIVATE_SELECTION_ALLOWED_FIELDS,
            "public opaque choice projection",
        )
        return cls(
            choice_token=_require_text(data["choice_token"], "choice_token"),
            ordinal=_require_int(data["ordinal"], "ordinal"),
            action_id=_require_text(data["action_id"], "action_id"),
            publicly_allowed_action_type=_require_text(
                data["publicly_allowed_action_type"], "publicly_allowed_action_type"
            ),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "choice_token": self.choice_token,
            "ordinal": self.ordinal,
            "action_id": self.action_id,
            "publicly_allowed_action_type": self.publicly_allowed_action_type,
        }


CONTROLLER_PRIVATE_FIELD_DENYLIST = frozenset(
    {
        "card_instance_id",
        "card_id",
        "card_identity",
        "card_name",
        "card_type",
        "card_category",
        "suit",
        "rank",
        "color",
        "semantic_value",
        "card_value",
        "deck_index",
        "future_draw_consequence",
        "observed_card_ids",
        "selected_card_ids",
        "remaining_top_order",
        "private_payload",
        "private_semantic_value",
        "raw_selected_card",
        "virtual_card",
        "material_card_instance_ids",
        "handle",
        "continuation_identity",
        "metadata",
        "private_hand",
        "deck_contents",
        "draw_pile",
        "rng",
        "seed",
        "general_name",
        "general_key",
        "winner",
        "expected_winner",
        "future_cards",
    }
)

_PUBLIC_CONTEXT_FIELDS = frozenset(
    {
        "mode_id",
        "phase",
        "actor_id",
        "turn_player_id",
        "response_window_id",
        "expected_revision",
        "seat_order",
        "action_window_kind",
    }
)

_RESPONSE_PHASES = frozenset(
    {
        ProductionPhase.JUDGMENT_WUXIE.value,
        ProductionPhase.SLASH_RESPONSE.value,
        ProductionPhase.TRICK_RESPONSE.value,
        ProductionPhase.DUEL_RESPONSE.value,
        ProductionPhase.FIRE_ATTACK_REVEAL.value,
        ProductionPhase.FIRE_ATTACK_DISCARD.value,
        ProductionPhase.BORROWED_SWORD_CHOICE.value,
        ProductionPhase.NANMAN_RESPONSE.value,
        ProductionPhase.WANJIAN_RESPONSE.value,
    }
)


def _public_action_window_kind(phase: str) -> str:
    if phase == ProductionPhase.DYING_RESCUE.value:
        return "rescue"
    if phase in _RESPONSE_PHASES:
        return "response"
    if phase in {
        ProductionPhase.ZONE_CHOICE.value,
        ProductionPhase.WUGU_PICK.value,
        ProductionPhase.CIXIONG_TARGET_CHOICE.value,
        ProductionPhase.SUCCESSION_CARD_CHOICE.value,
    }:
        return "public_choice"
    if phase in {
        ProductionPhase.DISCARD.value,
        ProductionPhase.WEAPON_DISCARD_TWO.value,
        ProductionPhase.HANBING_DISCARD.value,
    }:
        return "discard"
    return "phase"


@dataclass(frozen=True, slots=True)
class PublicActionContextV1:
    """Exact public-only projection of one live production action context."""

    mode_id: str
    phase: str
    actor_id: str
    turn_player_id: str | None
    response_window_id: str | None
    expected_revision: int
    seat_order: tuple[str, ...]
    action_window_kind: str

    def __post_init__(self) -> None:
        if _require_text(self.mode_id, "mode_id") != MODE_ID:
            raise BridgeContractError("public context mode_id不是Bridge V1")
        phase = _require_text(self.phase, "phase")
        if phase not in {item.value for item in ProductionPhase if item is not ProductionPhase.FINISHED}:
            raise BridgeContractError(f"public context包含未知phase：{phase!r}")
        actor = _require_text(self.actor_id, "actor_id")
        if type(self.seat_order) is not tuple or self.seat_order != PARTICIPANT_IDS:
            raise BridgeContractError("public context seat_order必须精确为Bridge公开座次")
        if actor not in self.seat_order:
            raise BridgeContractError("public context actor_id不在公开座次中")
        if self.turn_player_id is not None:
            if _require_text(self.turn_player_id, "turn_player_id") not in self.seat_order:
                raise BridgeContractError("public context turn_player_id不在公开座次中")
        if self.response_window_id is not None:
            _require_text(self.response_window_id, "response_window_id")
        _require_int(self.expected_revision, "expected_revision")
        expected_kind = _public_action_window_kind(phase)
        if self.action_window_kind != expected_kind:
            raise BridgeContractError(
                "public context action_window_kind与公开phase不一致"
            )

    @classmethod
    def from_action_context(cls, context: ActionContext) -> "PublicActionContextV1":
        if type(context) is not ActionContext:
            raise TypeError("public context投影只接受精确ActionContext")
        if context.expected_revision is None:
            raise BridgeContractError("Bridge production ActionContext缺少revision")
        # metadata is intentionally not inspected or copied.  Bridge V1 has a
        # fixed public two-seat topology, so no private state is needed here.
        return cls(
            mode_id=context.mode,
            phase=context.phase,
            actor_id=context.actor_id,
            turn_player_id=context.turn_player_id,
            response_window_id=context.response_window_id,
            expected_revision=context.expected_revision,
            seat_order=PARTICIPANT_IDS,
            action_window_kind=_public_action_window_kind(context.phase),
        )

    @classmethod
    def from_dict(cls, value: object) -> "PublicActionContextV1":
        data = _require_exact_dict(value, "public action context")
        if frozenset(data) & CONTROLLER_PRIVATE_FIELD_DENYLIST:
            raise BridgeContractError("public action context包含private authority字段")
        _require_exact_fields(data, _PUBLIC_CONTEXT_FIELDS, "public action context")
        raw_seats = data["seat_order"]
        if type(raw_seats) is not list or any(type(item) is not str for item in raw_seats):
            raise BridgeContractError("public action context seat_order必须是字符串array")
        for optional in ("turn_player_id", "response_window_id"):
            if data[optional] is not None and type(data[optional]) is not str:
                raise BridgeContractError(f"public action context {optional}必须是字符串或null")
        return cls(
            mode_id=_require_text(data["mode_id"], "mode_id"),
            phase=_require_text(data["phase"], "phase"),
            actor_id=_require_text(data["actor_id"], "actor_id"),
            turn_player_id=data["turn_player_id"],
            response_window_id=data["response_window_id"],
            expected_revision=_require_int(data["expected_revision"], "expected_revision"),
            seat_order=tuple(raw_seats),
            action_window_kind=_require_text(
                data["action_window_kind"], "action_window_kind"
            ),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "mode_id": self.mode_id,
            "phase": self.phase,
            "actor_id": self.actor_id,
            "turn_player_id": self.turn_player_id,
            "response_window_id": self.response_window_id,
            "expected_revision": self.expected_revision,
            "seat_order": list(self.seat_order),
            "action_window_kind": self.action_window_kind,
        }

    def as_action_context(self) -> ActionContext:
        """Reconstruct only the public shell; metadata is always empty."""

        return ActionContext(
            mode=self.mode_id,
            phase=self.phase,
            actor_id=self.actor_id,
            turn_player_id=self.turn_player_id,
            response_window_id=self.response_window_id,
            expected_revision=self.expected_revision,
            metadata={},
        )


_ACTION_FAMILY_OPERATIONS: Mapping[str, tuple[str, ...]] = MappingProxyType(
    {
        "phase_advance": (
            "proceed_prepare",
            "proceed_judgment",
            "proceed_draw",
            "end_play_phase",
            "end_turn",
        ),
        "card_use": (
            "heal_self",
            "use_wine_buff",
            "use_slash",
            "use_wuzhong",
            "use_guohe",
            "use_shunshou",
            "use_duel",
            "use_fire_attack",
            "use_nanman",
            "use_wanjian",
            "use_taoyuan",
            "use_tiesuo",
            "recast_tiesuo",
            "use_wugu",
            "use_jiedao",
            "use_lebusi",
            "use_bingliang",
            "use_shandian",
        ),
        "equipment_use": ("use_weapon", "use_armor", "use_mount"),
        "response": (
            "use_wuxie",
            "pass_judgment_wuxie",
            "play_dodge",
            "activate_bagua",
            "pass_slash_response",
            "pass_trick_response",
            "play_slash_for_duel",
            "pass_duel_slash",
            "reveal_card_for_fire_attack",
            "discard_same_suit_for_fire_attack",
            "pass_fire_attack_discard",
            "choose_borrowed_sword_slash",
            "refuse_borrowed_sword_slash",
            "play_slash_for_nanman",
            "pass_nanman_slash",
            "play_jink_for_wanjian",
            "pass_wanjian_jink",
        ),
        "rescue": (
            "rescue_with_peach",
            "rescue_with_wine",
            "pass_rescue",
        ),
        "public_target_choice": (
            "choose_target_zone_card",
            "pick_wugu_card",
            "skill_lose_hp_target_choice",
            "succession_obtain_card",
        ),
        "discard": (
            "select_discard_card",
            "unselect_discard_card",
            "discard_phase_submit",
            "cixiong_discard_card",
            "weapon_discard_mount",
            "select_discard_two",
            "unselect_discard_two",
            "discard_two_submit",
            "hanbing_discard_card",
        ),
        "skill_decision": (
            "activate_skill",
            "pass_skill",
            "qianchong_choice",
        ),
        "equipment_decision": (
            "activate_cixiong",
            "pass_cixiong",
            "cixiong_allow_draw",
            "weapon_force_hit",
            "weapon_prevent_damage",
            "qinglong_use_slash",
            "pass_weapon_choice",
        ),
        "mode_decision": (
            "feiyang_activate",
            "feiyang_decline",
            "peasant_reward_recover_hp",
            "peasant_reward_draw_two",
            "peasant_reward_decline",
            "select_heir",
            "choose_spy_path",
            "pass_mode_decision",
            "succession_obtain_none",
            "ambitionist_mark_draw_two",
            "ambitionist_reward_draw_three",
            "ambitionist_reward_decline",
        ),
        "private_player_choice": ("private_card_selection_submit",),
    }
)


def _operation_family_map() -> Mapping[str, str]:
    result: dict[str, str] = {}
    for family, operations in _ACTION_FAMILY_OPERATIONS.items():
        for operation in operations:
            if operation in result:
                raise BridgeIdentityError(
                    f"controller operation重复归类：{operation!r}"
                )
            result[operation] = family
    return MappingProxyType(result)


SUPPORTED_OPERATION_FAMILIES = _operation_family_map()
SUPPORTED_ACTION_FAMILIES = tuple(sorted(set(SUPPORTED_OPERATION_FAMILIES.values())))

_PUBLIC_LEGAL_ACTION_FIELDS = frozenset(
    {
        "action_id",
        "action_type",
        "operation",
        "actor_id",
        "target_ids",
        "virtual",
        "public_source_zone",
        "choice_ordinal",
        "public_choice_token",
        "public_choice_value",
        "public_skill_id",
        "response_window_kind",
        "revision",
    }
)

_PUBLIC_SOURCE_ZONES = frozenset(
    {
        "judgment",
        "revealed",
        "processing",
        "equipment:weapon",
        "equipment:armor",
        "equipment:attack_horse",
        "equipment:defense_horse",
        "equipment:treasure",
    }
)


def _optional_text(value: object, label: str) -> str | None:
    if value is None:
        return None
    return _require_text(value, label)


@dataclass(frozen=True, slots=True)
class PublicLegalActionProjectionV1:
    """Sanitized signed public gameplay action; no card identity is present."""

    action_id: str
    action_type: str
    operation: str
    actor_id: str
    target_ids: tuple[str, ...]
    virtual: bool
    public_source_zone: str | None
    choice_ordinal: int
    public_choice_token: str | None
    public_choice_value: str | None
    public_skill_id: str | None
    response_window_kind: str
    revision: int

    def __post_init__(self) -> None:
        _require_text(self.action_id, "action_id")
        action_type = _require_text(self.action_type, "action_type")
        if action_type not in {item.value for item in ActionType}:
            raise BridgeContractError(f"unknown action_type：{action_type!r}")
        operation = _require_text(self.operation, "operation")
        if operation not in SUPPORTED_OPERATION_FAMILIES:
            raise BridgeContractError(f"unknown action family/operation：{operation!r}")
        _require_text(self.actor_id, "actor_id")
        if type(self.target_ids) is not tuple or any(
            type(item) is not str or not item for item in self.target_ids
        ):
            raise BridgeContractError("target_ids必须是精确非空字符串tuple")
        if len(self.target_ids) != len(set(self.target_ids)):
            raise BridgeContractError("target_ids不得重复")
        _require_bool(self.virtual, "virtual")
        if self.public_source_zone is not None:
            zone = _require_text(self.public_source_zone, "public_source_zone")
            if zone not in _PUBLIC_SOURCE_ZONES:
                raise BridgeContractError("public_source_zone不得暴露private zone")
        _require_int(self.choice_ordinal, "choice_ordinal")
        _optional_text(self.public_choice_token, "public_choice_token")
        choice = _optional_text(self.public_choice_value, "public_choice_value")
        if operation == "qianchong_choice":
            if choice not in {"basic", "trick", "equipment"}:
                raise BridgeContractError("Qianchong public category不合法")
        elif choice is not None:
            raise BridgeContractError("非Qianchong action不得携带public_choice_value")
        _optional_text(self.public_skill_id, "public_skill_id")
        if self.response_window_kind not in {
            "phase",
            "response",
            "rescue",
            "public_choice",
            "discard",
        }:
            raise BridgeContractError("response_window_kind不合法")
        _require_int(self.revision, "revision")

    @property
    def action_family(self) -> str:
        return SUPPORTED_OPERATION_FAMILIES[self.operation]

    @classmethod
    def from_dict(cls, value: object) -> "PublicLegalActionProjectionV1":
        data = _require_exact_dict(value, "public legal action projection")
        if frozenset(data) & CONTROLLER_PRIVATE_FIELD_DENYLIST:
            raise BridgeContractError("public legal action projection包含private字段")
        _require_exact_fields(
            data, _PUBLIC_LEGAL_ACTION_FIELDS, "public legal action projection"
        )
        raw_targets = data["target_ids"]
        if type(raw_targets) is not list or any(type(item) is not str for item in raw_targets):
            raise BridgeContractError("target_ids必须是字符串array")
        return cls(
            action_id=_require_text(data["action_id"], "action_id"),
            action_type=_require_text(data["action_type"], "action_type"),
            operation=_require_text(data["operation"], "operation"),
            actor_id=_require_text(data["actor_id"], "actor_id"),
            target_ids=tuple(raw_targets),
            virtual=_require_bool(data["virtual"], "virtual"),
            public_source_zone=_optional_text(
                data["public_source_zone"], "public_source_zone"
            ),
            choice_ordinal=_require_int(data["choice_ordinal"], "choice_ordinal"),
            public_choice_token=_optional_text(
                data["public_choice_token"], "public_choice_token"
            ),
            public_choice_value=_optional_text(
                data["public_choice_value"], "public_choice_value"
            ),
            public_skill_id=_optional_text(data["public_skill_id"], "public_skill_id"),
            response_window_kind=_require_text(
                data["response_window_kind"], "response_window_kind"
            ),
            revision=_require_int(data["revision"], "revision"),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "action_id": self.action_id,
            "action_type": self.action_type,
            "operation": self.operation,
            "actor_id": self.actor_id,
            "target_ids": list(self.target_ids),
            "virtual": self.virtual,
            "public_source_zone": self.public_source_zone,
            "choice_ordinal": self.choice_ordinal,
            "public_choice_token": self.public_choice_token,
            "public_choice_value": self.public_choice_value,
            "public_skill_id": self.public_skill_id,
            "response_window_kind": self.response_window_kind,
            "revision": self.revision,
        }


ControllerActionProjectionV1 = PublicLegalActionProjectionV1 | PublicOpaqueChoiceProjection


def _public_source_zone(payload: Mapping[str, object]) -> str | None:
    zone = payload.get("zone")
    if type(zone) is str and zone in _PUBLIC_SOURCE_ZONES:
        return zone
    return None


def project_signed_legal_actions_v1(
    legal_actions: tuple[LegalAction, ...],
    public_context: PublicActionContextV1,
) -> tuple[ControllerActionProjectionV1, ...]:
    """Project one real signed legal set without copying private card data."""

    if type(legal_actions) is not tuple:
        raise TypeError("legal action投影只接受production legal_actions tuple")
    if type(public_context) is not PublicActionContextV1:
        raise TypeError("legal action投影只接受PublicActionContextV1")
    projected: list[ControllerActionProjectionV1] = []
    seen_ids: set[str] = set()
    for ordinal, action in enumerate(legal_actions):
        if type(action) is not LegalAction:
            raise TypeError("legal action投影只接受精确LegalAction")
        if action.action_id is None:
            raise BridgeContractError("controller拒绝unsigned legal action")
        if action.action_id in seen_ids:
            raise BridgeContractError("controller拒绝duplicate/conflicting action_id")
        seen_ids.add(action.action_id)
        if action.actor_id != public_context.actor_id:
            raise BridgeContractError("legal action actor与public context不一致")
        if any(target not in public_context.seat_order for target in action.target_ids):
            raise BridgeContractError("legal action target不在公开座次中")
        operation = action.payload.get("operation")
        if type(operation) is not str or operation not in SUPPORTED_OPERATION_FAMILIES:
            raise BridgeContractError(f"unknown action family/operation：{operation!r}")
        payload_revision = action.payload.get("expected_revision")
        if payload_revision is not None and payload_revision != public_context.expected_revision:
            raise BridgeContractError("legal action payload revision已过期")
        if operation == "private_card_selection_submit":
            if (
                action.action_type is not ActionType.CHOOSE_OPTION
                or action.skill_id != "sgs_skill_zuilun"
            ):
                raise BridgeContractError("private choice不是frozen Zuilun signed action")
            projected.append(
                PublicOpaqueChoiceProjection(
                    choice_token=f"opaque:{ordinal}",
                    ordinal=ordinal,
                    action_id=action.action_id,
                    publicly_allowed_action_type=action.action_type.value,
                )
            )
            continue
        public_choice_value = None
        if operation == "qianchong_choice":
            raw_choice = action.payload.get("chosen_card_type")
            if type(raw_choice) is not str:
                raise BridgeContractError("Qianchong signed action缺少public category")
            public_choice_value = raw_choice
        projected.append(
            PublicLegalActionProjectionV1(
                action_id=action.action_id,
                action_type=action.action_type.value,
                operation=operation,
                actor_id=action.actor_id,
                target_ids=action.target_ids,
                virtual=(
                    action.payload.get("virtual") is True
                    or action.virtual_card is not None
                    or action.payload.get("zhangba_virtual") is True
                ),
                public_source_zone=_public_source_zone(action.payload),
                choice_ordinal=ordinal,
                public_choice_token=None,
                public_choice_value=public_choice_value,
                public_skill_id=action.skill_id,
                response_window_kind=public_context.action_window_kind,
                revision=public_context.expected_revision,
            )
        )
    return tuple(projected)


def project_public_action_surface_v1(
    legal_actions: tuple[LegalAction, ...],
    context: ActionContext,
) -> tuple[PublicActionContextV1, tuple[ControllerActionProjectionV1, ...]]:
    """One-way public façade from the real production surface."""

    public_context = PublicActionContextV1.from_action_context(context)
    return public_context, project_signed_legal_actions_v1(
        legal_actions, public_context
    )


_PLAY_OPERATION_PRIORITY = MappingProxyType(
    {
        "heal_self": 0,
        "use_wine_buff": 1,
        "use_slash": 2,
        "use_wuzhong": 3,
        "use_guohe": 4,
        "use_shunshou": 5,
        "use_duel": 6,
        "use_fire_attack": 7,
        "use_nanman": 8,
        "use_wanjian": 9,
        "use_taoyuan": 10,
        "use_tiesuo": 11,
        "recast_tiesuo": 12,
        "use_wugu": 13,
        "use_jiedao": 14,
        "use_lebusi": 15,
        "use_bingliang": 16,
        "use_shandian": 17,
        "use_weapon": 18,
        "use_armor": 19,
        "use_mount": 20,
        "activate_skill": 30,
        "end_play_phase": 99,
    }
)

_RESPONSE_OPERATION_PRIORITY: Mapping[str, Mapping[str, int]] = MappingProxyType(
    {
        ProductionPhase.JUDGMENT_WUXIE.value: MappingProxyType(
            {"use_wuxie": 0, "pass_judgment_wuxie": 9}
        ),
        ProductionPhase.SLASH_RESPONSE.value: MappingProxyType(
            {"play_dodge": 0, "activate_bagua": 1, "pass_slash_response": 9}
        ),
        ProductionPhase.TRICK_RESPONSE.value: MappingProxyType(
            {"use_wuxie": 0, "pass_trick_response": 9}
        ),
        ProductionPhase.DUEL_RESPONSE.value: MappingProxyType(
            {"play_slash_for_duel": 0, "pass_duel_slash": 9}
        ),
        ProductionPhase.FIRE_ATTACK_REVEAL.value: MappingProxyType(
            {"reveal_card_for_fire_attack": 0}
        ),
        ProductionPhase.FIRE_ATTACK_DISCARD.value: MappingProxyType(
            {
                "discard_same_suit_for_fire_attack": 0,
                "pass_fire_attack_discard": 9,
            }
        ),
        ProductionPhase.BORROWED_SWORD_CHOICE.value: MappingProxyType(
            {"choose_borrowed_sword_slash": 0, "refuse_borrowed_sword_slash": 9}
        ),
        ProductionPhase.NANMAN_RESPONSE.value: MappingProxyType(
            {"play_slash_for_nanman": 0, "pass_nanman_slash": 9}
        ),
        ProductionPhase.WANJIAN_RESPONSE.value: MappingProxyType(
            {
                "play_jink_for_wanjian": 0,
                "activate_bagua": 1,
                "pass_wanjian_jink": 9,
            }
        ),
    }
)


class SkillAwareFixedAssignmentAcceptanceControllerV1:
    """Stateless deterministic public-only Bridge acceptance policy."""

    __slots__ = ()
    controller_id = CONTROLLER_ID
    controller_version = CONTROLLER_VERSION
    strategy_version = f"{CONTROLLER_ID}.{CONTROLLER_VERSION}"

    @staticmethod
    def _target_key(
        action: PublicLegalActionProjectionV1,
        context: PublicActionContextV1,
    ) -> tuple[int, ...]:
        index = {player_id: ordinal for ordinal, player_id in enumerate(context.seat_order)}
        try:
            return tuple(index[target] for target in action.target_ids)
        except KeyError as exc:
            raise BridgeContractError("action target不在public seat order中") from exc

    def _rank(
        self,
        action: PublicLegalActionProjectionV1,
        context: PublicActionContextV1,
    ) -> tuple[object, ...]:
        operation = action.operation
        target_key = self._target_key(action, context)
        if operation == "qianchong_choice":
            category_rank = {"basic": 0, "trick": 1, "equipment": 2}
            return (0, category_rank[action.public_choice_value], target_key, action.choice_ordinal)
        if operation == "skill_lose_hp_target_choice":
            return (0, target_key, action.choice_ordinal)
        if context.phase == ProductionPhase.DYING_RESCUE.value:
            if operation == "rescue_with_peach" and action.target_ids == (
                action.actor_id,
            ):
                rank = 0
            elif operation == "rescue_with_wine" and action.target_ids == (
                action.actor_id,
            ):
                rank = 1
            elif operation == "rescue_with_peach":
                rank = 2
            elif operation == "rescue_with_wine":
                rank = 3
            else:
                rank = 9
            if action.virtual:
                rank += 4
            return (rank, target_key, action.choice_ordinal)
        response_ranks = _RESPONSE_OPERATION_PRIORITY.get(context.phase)
        if response_ranks is not None:
            return (
                response_ranks.get(operation, 8),
                operation,
                target_key,
                action.choice_ordinal,
            )
        if context.phase == ProductionPhase.PLAY.value:
            return (
                _PLAY_OPERATION_PRIORITY.get(operation, 50),
                operation,
                target_key,
                action.public_skill_id or "",
                action.choice_ordinal,
            )
        if context.phase == ProductionPhase.DISCARD.value:
            rank = {
                "discard_phase_submit": 0,
                "select_discard_card": 1,
                "unselect_discard_card": 2,
            }.get(operation, 9)
            return (rank, target_key, action.choice_ordinal)
        if context.phase == ProductionPhase.WEAPON_DISCARD_TWO.value:
            rank = {
                "discard_two_submit": 0,
                "select_discard_two": 1,
                "unselect_discard_two": 2,
            }.get(operation, 9)
            return (rank, target_key, action.choice_ordinal)
        pass_rank = 1 if action.action_type == ActionType.PASS.value else 0
        return (
            pass_rank,
            action.action_family,
            operation,
            target_key,
            action.public_choice_value or "",
            action.public_skill_id or "",
            action.choice_ordinal,
        )

    def choose(
        self,
        legal_actions: tuple[ControllerActionProjectionV1, ...],
        public_context: PublicActionContextV1,
    ) -> str:
        if type(public_context) is not PublicActionContextV1:
            raise TypeError("controller只能接收PublicActionContextV1")
        if type(legal_actions) is not tuple:
            raise TypeError("controller只能接收sanitized projection tuple")
        if not legal_actions:
            raise BridgeContractError("controller拒绝empty legal action set")
        if any(
            type(action) not in {PublicLegalActionProjectionV1, PublicOpaqueChoiceProjection}
            for action in legal_actions
        ):
            raise TypeError("controller拒绝raw session/state/runtime/LegalAction")
        action_ids = tuple(action.action_id for action in legal_actions)
        if len(action_ids) != len(set(action_ids)):
            raise BridgeContractError("controller拒绝duplicate/conflicting action_id")
        opaque = tuple(
            action for action in legal_actions if type(action) is PublicOpaqueChoiceProjection
        )
        if opaque:
            if len(opaque) != len(legal_actions):
                raise BridgeContractError("private choice window不得混入public gameplay action")
            ordinals = tuple(action.ordinal for action in opaque)
            if len(ordinals) != len(set(ordinals)):
                raise BridgeContractError("private choice ordinal不得重复")
            tokens = tuple(action.choice_token for action in opaque)
            if len(tokens) != len(set(tokens)):
                raise BridgeContractError("private choice token不得重复")
            if any(
                action.publicly_allowed_action_type != ActionType.CHOOSE_OPTION.value
                for action in opaque
            ):
                raise BridgeContractError("private choice action type不合法")
            return min(opaque, key=lambda action: action.ordinal).action_id
        public_actions = tuple(
            action
            for action in legal_actions
            if type(action) is PublicLegalActionProjectionV1
        )
        for action in public_actions:
            if action.actor_id != public_context.actor_id:
                raise BridgeContractError("projection actor与public context不一致")
            if action.revision != public_context.expected_revision:
                raise BridgeContractError("projection revision与public context不一致")
            if action.response_window_kind != public_context.action_window_kind:
                raise BridgeContractError("projection window kind与public context不一致")
        ordinals = tuple(action.choice_ordinal for action in public_actions)
        if len(ordinals) != len(set(ordinals)):
            raise BridgeContractError("public action choice_ordinal不得重复")
        operations = {action.operation for action in public_actions}
        if "pass_skill" in operations:
            if not operations <= {"activate_skill", "pass_skill"}:
                raise BridgeContractError("optional skill window混入非技能决策动作")
            activations = tuple(
                action for action in public_actions if action.operation == "activate_skill"
            )
            if activations:
                return min(
                    activations,
                    key=lambda action: (
                        action.public_skill_id or "",
                        self._target_key(action, public_context),
                        action.choice_ordinal,
                    ),
                ).action_id
            return min(
                public_actions, key=lambda action: action.choice_ordinal
            ).action_id
        return min(
            public_actions,
            key=lambda action: self._rank(action, public_context),
        ).action_id


_PROJECTION_WRAPPER_FIELDS = frozenset({"projection_kind", "projection"})


def _projection_to_record_value(
    action: ControllerActionProjectionV1,
) -> dict[str, object]:
    if type(action) is PublicLegalActionProjectionV1:
        kind = "public_gameplay_action"
    elif type(action) is PublicOpaqueChoiceProjection:
        kind = "private_player_choice"
    else:  # pragma: no cover - guarded at every public ingress
        raise TypeError("unknown controller projection type")
    return {"projection_kind": kind, "projection": action.to_dict()}


def _projection_from_record_value(value: object) -> ControllerActionProjectionV1:
    data = _require_exact_dict(value, "controller projection wrapper")
    _require_exact_fields(data, _PROJECTION_WRAPPER_FIELDS, "controller projection wrapper")
    kind = _require_text(data["projection_kind"], "projection_kind")
    if kind == "public_gameplay_action":
        return PublicLegalActionProjectionV1.from_dict(data["projection"])
    if kind == "private_player_choice":
        return PublicOpaqueChoiceProjection.from_dict(data["projection"])
    raise BridgeContractError(f"unknown projection_kind：{kind!r}")


_CONTROLLER_DECISION_FIELDS = frozenset(
    {
        "controller_id",
        "controller_version",
        "public_context",
        "public_context_identity",
        "legal_action_projections",
        "legal_action_set_identity",
        "chosen_action_id",
    }
)


@dataclass(frozen=True, slots=True)
class ControllerDecisionRecordV1:
    controller_id: str
    controller_version: int
    public_context: PublicActionContextV1
    public_context_identity: str
    legal_action_projections: tuple[ControllerActionProjectionV1, ...]
    legal_action_set_identity: str
    chosen_action_id: str

    def __post_init__(self) -> None:
        if self.controller_id != CONTROLLER_ID:
            raise BridgeContractError("wrong controller ID")
        if type(self.controller_version) is not int or self.controller_version != CONTROLLER_VERSION:
            raise BridgeContractError("wrong controller version")
        if type(self.public_context) is not PublicActionContextV1:
            raise TypeError("controller decision必须包含PublicActionContextV1")
        if type(self.legal_action_projections) is not tuple:
            raise TypeError("controller decision legal actions必须是tuple")
        expected_context_identity = sha256_value(self.public_context.to_dict())
        if self.public_context_identity != expected_context_identity:
            raise BridgeContractError("altered public context identity")
        action_values = [
            _projection_to_record_value(action)
            for action in self.legal_action_projections
        ]
        expected_action_identity = sha256_value(action_values)
        if self.legal_action_set_identity != expected_action_identity:
            raise BridgeContractError("altered/missing legal action projection")
        action_ids = tuple(action.action_id for action in self.legal_action_projections)
        if not action_ids:
            raise BridgeContractError("controller decision缺少legal action")
        if len(action_ids) != len(set(action_ids)):
            raise BridgeContractError("controller decision包含duplicate/conflicting action_id")
        if self.chosen_action_id not in action_ids:
            raise BridgeContractError("chosen action不在legal action set")

    @classmethod
    def from_dict(cls, value: object) -> "ControllerDecisionRecordV1":
        data = _require_exact_dict(value, "controller decision")
        if frozenset(data) & CONTROLLER_PRIVATE_FIELD_DENYLIST:
            raise BridgeContractError("controller decision包含private authority字段")
        _require_exact_fields(data, _CONTROLLER_DECISION_FIELDS, "controller decision")
        raw_actions = data["legal_action_projections"]
        if type(raw_actions) is not list:
            raise BridgeContractError("legal_action_projections必须是array")
        return cls(
            controller_id=_require_text(data["controller_id"], "controller_id"),
            controller_version=_require_int(
                data["controller_version"], "controller_version"
            ),
            public_context=PublicActionContextV1.from_dict(data["public_context"]),
            public_context_identity=_require_sha256(
                data["public_context_identity"], "public_context_identity"
            ),
            legal_action_projections=tuple(
                _projection_from_record_value(item) for item in raw_actions
            ),
            legal_action_set_identity=_require_sha256(
                data["legal_action_set_identity"], "legal_action_set_identity"
            ),
            chosen_action_id=_require_text(data["chosen_action_id"], "chosen_action_id"),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "controller_id": self.controller_id,
            "controller_version": self.controller_version,
            "public_context": self.public_context.to_dict(),
            "public_context_identity": self.public_context_identity,
            "legal_action_projections": [
                _projection_to_record_value(action)
                for action in self.legal_action_projections
            ],
            "legal_action_set_identity": self.legal_action_set_identity,
            "chosen_action_id": self.chosen_action_id,
        }


def create_controller_decision_record_v1(
    public_context: PublicActionContextV1,
    legal_action_projections: tuple[ControllerActionProjectionV1, ...],
) -> ControllerDecisionRecordV1:
    controller = SkillAwareFixedAssignmentAcceptanceControllerV1()
    chosen = controller.choose(legal_action_projections, public_context)
    action_values = [
        _projection_to_record_value(action) for action in legal_action_projections
    ]
    return ControllerDecisionRecordV1(
        controller_id=CONTROLLER_ID,
        controller_version=CONTROLLER_VERSION,
        public_context=public_context,
        public_context_identity=sha256_value(public_context.to_dict()),
        legal_action_projections=legal_action_projections,
        legal_action_set_identity=sha256_value(action_values),
        chosen_action_id=chosen,
    )


def assert_controller_conformance_v1(record: ControllerDecisionRecordV1) -> str:
    """Reexecute one recorded decision without implementing full replay."""

    if type(record) is not ControllerDecisionRecordV1:
        raise TypeError("controller conformance只接受ControllerDecisionRecordV1")
    chosen = SkillAwareFixedAssignmentAcceptanceControllerV1().choose(
        record.legal_action_projections, record.public_context
    )
    if chosen != record.chosen_action_id:
        raise BridgeContractError("recorded decision不符合controller deterministic policy")
    return chosen


BRIDGE_REPLAY_REQUIRED_FIELDS = frozenset(
    {
        "schema",
        "replay_version",
        "contract_id",
        "contract_identity",
        "implementation_identity",
        "ruleset_identity",
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
UNKNOWN_REPLAY_AUTHORITY_FIELD_POLICY = UnknownAuthorityFieldPolicy.REJECT
_REPLAY_IDENTITY_FIELDS = (
    "contract_identity",
    "implementation_identity",
    "ruleset_identity",
    "bridge_mode_profile_identity",
    "formal_duel_profile_identity",
    "deck_identity",
    "general_registry_identity",
    "bridge_skill_registry_identity",
    "bridge_authority_profile_identity",
    "records_identity",
    "execution_identity",
    "replay_identity",
)
_REPLAY_LIST_FIELDS = (
    "decisions",
    "random_consumptions",
    "events",
    "production_authority_trace",
    "skill_decision_authority_trace",
)
_REPLAY_OBJECT_FIELDS = ("initialization", "outcome", "authoritative_private")


def validate_bridge_replay_schema_marker(value: object) -> str:
    schema = _require_text(value, "replay schema")
    if schema != REPLAY_SCHEMA:
        raise BridgeContractError(
            "Bridge parser只接受exact Bridge schema；no-skill/legacy marker不得误识别"
        )
    return schema


_REPLAY_DESCRIPTOR_CAPABILITY = object()


@dataclass(frozen=True, slots=True)
class BridgeReplayDescriptorSkeleton:
    """Strict top-level schema holder only; no replay execution exists in A."""

    fields: object
    _capability: object = None

    def __post_init__(self) -> None:
        if self._capability is not _REPLAY_DESCRIPTOR_CAPABILITY:
            raise BridgeContractError(
                "Bridge replay descriptor只能由strict from_dict parser构造"
            )

    @classmethod
    def from_dict(cls, value: object) -> "BridgeReplayDescriptorSkeleton":
        data = _require_exact_dict(value, "Bridge replay descriptor")
        _require_exact_fields(data, BRIDGE_REPLAY_REQUIRED_FIELDS, "Bridge replay descriptor")
        validate_bridge_replay_schema_marker(data["schema"])
        if _require_int(data["replay_version"], "replay_version", minimum=1) != REPLAY_VERSION:
            raise BridgeContractError("Bridge replay_version不匹配")
        if _require_text(data["contract_id"], "contract_id") != CONTRACT_ID:
            raise BridgeContractError("Bridge replay contract_id不匹配")
        if _require_text(data["controller_id"], "controller_id") != CONTROLLER_ID:
            raise BridgeContractError("Bridge replay controller_id不匹配")
        if _require_int(data["controller_version"], "controller_version", minimum=1) != CONTROLLER_VERSION:
            raise BridgeContractError("Bridge replay controller_version不匹配")
        _require_text(data["cell_id"], "cell_id")
        _require_int(data["seed"], "seed")
        for field_name in _REPLAY_IDENTITY_FIELDS:
            _require_sha256(data[field_name], field_name)
        for field_name in _REPLAY_LIST_FIELDS:
            if type(data[field_name]) is not list:
                raise BridgeContractError(f"Bridge replay {field_name}必须是精确JSON array")
        for field_name in _REPLAY_OBJECT_FIELDS:
            _require_exact_dict(data[field_name], f"Bridge replay {field_name}")
        return cls(_deep_freeze(dict(data)), _REPLAY_DESCRIPTOR_CAPABILITY)

    def to_dict(self) -> dict[str, object]:
        plain = _deep_plain(self.fields)
        if type(plain) is not dict:  # pragma: no cover - constructor invariant
            raise BridgeContractError("Bridge replay skeleton内部字段不是object")
        return plain


FROZEN_OUT_OF_SCOPE_MARKERS = (
    "production_session_integration",
    "gameplay_execution",
    "controller_implementation",
    "replay_execution",
    "seed_discovery",
    "sentinel_execution",
    "natural_full_games",
    "frozen_skill_semantic_modifications",
    "stage3_changes",
    "c7_changes",
    "c8",
)


def bridge_authority_profile_descriptor() -> dict[str, object]:
    return {
        "general_registry_identity": GENERAL_REGISTRY_IDENTITY,
        "general_payloads": [item.to_dict() for item in GENERAL_ALLOWLIST_DESCRIPTORS],
        "bridge_skill_registry_identity": BRIDGE_SKILL_REGISTRY_IDENTITY,
        "base_skill_authority": BASE_SKILL_AUTHORITY.to_dict(),
        "dynamic_derivation_authority": DYNAMIC_DERIVATION_AUTHORITY.to_dict(),
        "runtime_effective_authority": RUNTIME_EFFECTIVE_AUTHORITY.to_dict(),
        "assignment_policy": {
            "participant_ids": list(PARTICIPANT_IDS),
            "assignments": [item.value for item in FixedAssignment],
            "general_count": 1,
            "no_skill_soldier_count": 1,
            "caller_supplied_stats": "REJECT",
            "caller_supplied_skills": "REJECT",
            "mixed_or_random_assignment": "REJECT",
        },
    }


BRIDGE_AUTHORITY_PROFILE_IDENTITY = sha256_value(bridge_authority_profile_descriptor())
BRIDGE_MODE_PROFILE_IDENTITY = sha256_value(
    {
        "mode_id": MODE_ID,
        "formal_duel_profile_identity": FORMAL_DUEL_PROFILE_IDENTITY,
        "mode_modifier": ModeModifier.NONE.value,
        "max_steps": MAX_STEPS,
        "assignment_authority_identity": BRIDGE_AUTHORITY_PROFILE_IDENTITY,
    }
)


def bridge_contract_descriptor() -> dict[str, object]:
    """Deterministic canonical Bridge V1 descriptor for BRIDGE-A."""

    return {
        "bridge_name": BRIDGE_NAME,
        "contract_id": CONTRACT_ID,
        "contract_version": CONTRACT_VERSION,
        "mode_id": MODE_ID,
        "replay_schema": REPLAY_SCHEMA,
        "replay_version": REPLAY_VERSION,
        "controller_id": CONTROLLER_ID,
        "controller_version": CONTROLLER_VERSION,
        "formal_duel_profile_identity": FORMAL_DUEL_PROFILE_IDENTITY,
        "deck_identity": DECK_IDENTITY,
        "general_registry_identity": GENERAL_REGISTRY_IDENTITY,
        "bridge_skill_registry_identity": BRIDGE_SKILL_REGISTRY_IDENTITY,
        "bridge_authority_profile_identity": BRIDGE_AUTHORITY_PROFILE_IDENTITY,
        "bridge_mode_profile_identity": BRIDGE_MODE_PROFILE_IDENTITY,
        "general_allowlist": list(GENERAL_ALLOWLIST),
        "general_source_payloads": [
            item.to_dict() for item in GENERAL_ALLOWLIST_DESCRIPTORS
        ],
        "skill_allowlist": list(BRIDGE_SKILL_ALLOWLIST),
        "dynamic_derivation_policy": DYNAMIC_DERIVATION_AUTHORITY.to_dict(),
        "assignment_policy": bridge_authority_profile_descriptor()["assignment_policy"],
        "initialization_policy": INITIALIZATION_CONTRACT.to_dict(),
        "baseline_18_registry_identity": BASELINE_18_REGISTRY_IDENTITY,
        "event_obligation_ids": list(EVENT_OBLIGATION_IDS),
        "sentinel_discovery_policy": SENTINEL_POLICY.to_dict(),
        "minimal_required_sentinels": MINIMAL_REQUIRED_SENTINELS.value,
        "final_acceptance_matrix": FINAL_ACCEPTANCE_MATRIX,
        "mode_modifier": ModeModifier.NONE.value,
        "max_steps": MAX_STEPS,
        "frozen_out_of_scope": [
            {"marker": marker, "status": "OUT_OF_SCOPE"}
            for marker in FROZEN_OUT_OF_SCOPE_MARKERS
        ],
        "unknown_authority_field_policy": UNKNOWN_REPLAY_AUTHORITY_FIELD_POLICY.value,
        "private_selection_boundary": {
            "allowed_fields": sorted(PRIVATE_SELECTION_ALLOWED_FIELDS),
            "forbidden_fields": sorted(PRIVATE_SELECTION_FORBIDDEN_FIELDS),
            "zuilun_selection": "signed opaque ordinal only",
        },
    }


def compute_bridge_contract_identity() -> str:
    return sha256_value(bridge_contract_descriptor())


PROPOSED_BRIDGE_CONTRACT_IDENTITY = compute_bridge_contract_identity()


_validate_frozen_input_identities()


@dataclass(frozen=True, slots=True)
class _BridgeMutationSnapshotV1:
    """Bridge identity wrapper around the existing production rollback snapshot."""

    production_snapshot: object
    assignment_identity: str
    bridge_skill_registry_identity: str
    bridge_contract_identity: str


_BRIDGE_STRICT_REPLAY_RECONSTRUCTION_CAPABILITY = object()


class SkillAwareFixedAssignmentDuelSessionV1(ProductionBasicCardBatch):
    """Explicit opt-in production duel joining fixed Generals to Skill Runtime.

    This façade deliberately accepts only a validated Bridge assignment.  Deck,
    formal profile, General registry, skill registry, outcome policy and runtime
    are all constructed from their canonical authorities inside this boundary.
    """

    MODE_ID = MODE_ID

    def __init__(
        self,
        *,
        seed: int,
        assignment: BridgeAssignmentDescriptor,
        bridge_contract_identity: str,
        _strict_replay_capability: object | None = None,
        _strict_replay_session_id: str | None = None,
        _strict_replay_session_secret: bytes | None = None,
    ) -> None:
        if type(self) is not _CANONICAL_BRIDGE_SESSION_TYPE:
            raise TypeError("Bridge canonical会话不允许通过子类覆写authority边界")
        if type(assignment) is not BridgeAssignmentDescriptor:
            raise BridgeContractError(
                "Bridge session assignment必须是canonical BridgeAssignmentDescriptor"
            )
        if bridge_contract_identity != PROPOSED_BRIDGE_CONTRACT_IDENTITY:
            raise BridgeIdentityError(
                "Bridge contract identity不一致；"
                f"expected={PROPOSED_BRIDGE_CONTRACT_IDENTITY}, "
                f"actual={bridge_contract_identity!r}"
            )
        replay_authority_supplied = (
            _strict_replay_session_id is not None
            or _strict_replay_session_secret is not None
        )
        if replay_authority_supplied and (
            _strict_replay_capability
            is not _BRIDGE_STRICT_REPLAY_RECONSTRUCTION_CAPABILITY
        ):
            raise BridgeContractError(
                "Bridge signing authority只能由canonical strict replay恢复"
            )
        if not replay_authority_supplied and _strict_replay_capability is not None:
            raise BridgeContractError("Bridge strict replay capability不得空载使用")
        if replay_authority_supplied and (
            type(_strict_replay_session_id) is not str
            or not _strict_replay_session_id
            or type(_strict_replay_session_secret) is not bytes
            or len(_strict_replay_session_secret) < 32
        ):
            raise BridgeContractError("Bridge strict replay signing authority不合法")

        # 1 validate_formal_profile
        _validate_frozen_input_identities()
        formal_configuration = FormalDuelConfiguration.formal_profile()
        assert_trusted_formal_configuration(formal_configuration)

        # 2 validate_assignment
        canonical_assignment = BridgeAssignmentDescriptor.from_dict(
            assignment.to_dict()
        )
        if canonical_assignment != assignment:
            raise BridgeContractError("Bridge assignment canonical round-trip不一致")

        # 3 derive_general_stats
        participants = canonical_assignment.participants
        hp = tuple(item.hp for item in participants)
        max_hp = tuple(item.max_hp for item in participants)
        general_assignments = {
            canonical_assignment.general_player_id: canonical_assignment.general_key
        }
        general_registry = _authoritative_general_registry()

        # 4 apply_mode_modifier_none: no mode_policy or caller modifier is installed.
        skill_registry = create_bridge_skill_registry()
        self._bridge_assignment = canonical_assignment
        self._bridge_assignment_identity = sha256_value(
            canonical_assignment.to_dict()
        )
        self._formal_configuration = formal_configuration
        self._mode_modifier = ModeModifier.NONE

        # ProductionBasicCardBatch preserves the frozen order internally:
        # 5 first_player_rng -> 6 shuffle_and_deal -> 7 derive_base_skills.
        super().__init__(
            seed=seed,
            player_hp=hp,
            player_max_hp=max_hp,
            player_ids=PARTICIPANT_IDS,
            outcome_policy=DuelOutcomePolicy(),
            initial_hand_count=formal_configuration.initial_hand_count,
            shuffle=True,
            skill_registry=skill_registry,
            general_registry=general_registry,
            general_assignments=general_assignments,
            session_id=_strict_replay_session_id,
            session_secret=_strict_replay_session_secret,
        )

        # The no-skill seat uses the same canonical soldier metadata as the
        # frozen formal duel.  General metadata was installed by the registry.
        soldier = next(
            item
            for item in participants
            if item.player_id == canonical_assignment.no_skill_player_id
        )
        soldier_metadata = formal_configuration.participants[0]
        if soldier_metadata is None:
            raise BridgeIdentityError("formal duel canonical soldier metadata缺失")
        players = tuple(
            replace(player, character=soldier_metadata)
            if player.player_id == soldier.player_id
            else player
            for player in self.state.players
        )
        self._state = replace(self.state, players=players)

        runtime = self.skill_runtime
        if runtime is None:
            raise BridgeIdentityError("Bridge production session未构造Skill Runtime")
        if runtime.registry.registry_identity != BRIDGE_SKILL_REGISTRY_IDENTITY:
            raise BridgeIdentityError("Bridge live Skill Runtime registry identity漂移")
        expected_base = BASE_SKILL_AUTHORITY.skills_for(
            canonical_assignment.general_key
        )
        actual_base = tuple(
            runtime.player_skills.get(
                canonical_assignment.general_player_id, {}
            ).keys()
        )
        if actual_base != expected_base:
            raise BridgeIdentityError(
                "Bridge live base skill set与General registry派生不一致"
            )
        if runtime.get_effective_skill_map(
            canonical_assignment.no_skill_player_id
        ):
            raise BridgeIdentityError("Bridge no-skill participant不得拥有技能")

        # 8 initial_qianchong_reconcile.  The existing production reconcile is
        # intentionally used directly; initialization deal events are never
        # dispatched as gameplay movement triggers.
        state_before = self.state
        events_before = self.events
        rng_before = self._rng.current_state_sha256
        ledger_before = self.turn_loss_ledger
        pending_before = (
            self._skill_pending,
            tuple(self._skill_trigger_queue),
            self._pending_private_card_selection,
            self._pending_skill_hp_loss,
            self._pending_card_continuation,
            self._end_phase_dispatch_state,
        )
        self._reconcile_qianchong_for_all(self.state)
        if (
            self.state != state_before
            or self.events != events_before
            or self._rng.current_state_sha256 != rng_before
            or self.turn_loss_ledger != ledger_before
            or pending_before
            != (
                self._skill_pending,
                tuple(self._skill_trigger_queue),
                self._pending_private_card_selection,
                self._pending_skill_hp_loss,
                self._pending_card_continuation,
                self._end_phase_dispatch_state,
            )
        ):
            raise BridgeIdentityError(
                "initial Qianchong reconcile不得改变gameplay state/event/RNG/pending"
            )

        # 9 sign_initial_state -> 10 enumerate_first_legal_set.
        self._initial_state_identity = state_sha256(
            canonical_state_snapshot(self.state)
        )
        self._initial_execution_identity = self.execution_hash
        first_legal = self.legal_actions()
        if not first_legal or any(item.action_id is None for item in first_legal):
            raise BridgeIdentityError("Bridge initial legal set必须包含production signed action")
        self._initial_legal_actions = first_legal
        self._initialization_trace = INITIALIZATION_SEQUENCE

    @property
    def assignment(self) -> BridgeAssignmentDescriptor:
        return self._bridge_assignment

    @property
    def assignment_identity(self) -> str:
        return self._bridge_assignment_identity

    @property
    def formal_configuration(self) -> FormalDuelConfiguration:
        return self._formal_configuration

    @property
    def mode_modifier(self) -> ModeModifier:
        return self._mode_modifier

    @property
    def initialization_trace(self) -> tuple[InitializationStep, ...]:
        return self._initialization_trace

    @property
    def initial_state_identity(self) -> str:
        return self._initial_state_identity

    @property
    def initial_execution_identity(self) -> str:
        return self._initial_execution_identity

    @property
    def initial_legal_actions(self) -> tuple[object, ...]:
        return self._initial_legal_actions

    @property
    def formal_result_eligible(self) -> bool:
        return self._formal_configuration.source_confirmed

    @property
    def execution_snapshot(self) -> dict[str, object]:
        snapshot = super().execution_snapshot
        snapshot["bridge_authority"] = {
            "contract_identity": PROPOSED_BRIDGE_CONTRACT_IDENTITY,
            "mode_id": MODE_ID,
            "formal_duel_profile_identity": FORMAL_DUEL_PROFILE_IDENTITY,
            "deck_identity": DECK_IDENTITY,
            "general_registry_identity": GENERAL_REGISTRY_IDENTITY,
            "bridge_skill_registry_identity": BRIDGE_SKILL_REGISTRY_IDENTITY,
            "bridge_authority_profile_identity": BRIDGE_AUTHORITY_PROFILE_IDENTITY,
            "bridge_mode_profile_identity": BRIDGE_MODE_PROFILE_IDENTITY,
            "assignment_identity": self._bridge_assignment_identity,
            "assignment": self._bridge_assignment.to_dict(),
            "mode_modifier": self._mode_modifier.value,
            "initialization_sequence_identity": INITIALIZATION_SEQUENCE_IDENTITY,
            "initialization_sequence": [
                item.value for item in INITIALIZATION_SEQUENCE
            ],
        }
        return snapshot

    def _snapshot_authoritative_mutation_state(self) -> _BridgeMutationSnapshotV1:
        return _BridgeMutationSnapshotV1(
            production_snapshot=super()._snapshot_authoritative_mutation_state(),
            assignment_identity=self._bridge_assignment_identity,
            bridge_skill_registry_identity=BRIDGE_SKILL_REGISTRY_IDENTITY,
            bridge_contract_identity=PROPOSED_BRIDGE_CONTRACT_IDENTITY,
        )

    def _restore_authoritative_mutation_state(
        self, snapshot: _BridgeMutationSnapshotV1
    ) -> None:
        if type(snapshot) is not _BridgeMutationSnapshotV1:
            raise BridgeIdentityError("Bridge transaction snapshot类型不合法")
        expected = (
            self._bridge_assignment_identity,
            BRIDGE_SKILL_REGISTRY_IDENTITY,
            PROPOSED_BRIDGE_CONTRACT_IDENTITY,
        )
        actual = (
            snapshot.assignment_identity,
            snapshot.bridge_skill_registry_identity,
            snapshot.bridge_contract_identity,
        )
        if actual != expected:
            raise BridgeIdentityError("Bridge transaction authority identity不一致")
        super()._restore_authoritative_mutation_state(snapshot.production_snapshot)
        runtime = self.skill_runtime
        if (
            runtime is None
            or runtime.registry.registry_identity != BRIDGE_SKILL_REGISTRY_IDENTITY
        ):
            raise BridgeIdentityError("Bridge transaction restore丢失Skill Runtime authority")

    def public_action_surface_v1(
        self,
    ) -> tuple[PublicActionContextV1, tuple[ControllerActionProjectionV1, ...]]:
        """Expose one sanitized view of the current real signed legal set."""

        context = self._context()
        legal_actions = self.legal_actions()
        return project_public_action_surface_v1(legal_actions, context)

    def acceptance_decision_record_v1(self) -> ControllerDecisionRecordV1:
        """Choose from the public façade and return a conformance-ready record."""

        public_context, projections = self.public_action_surface_v1()
        return create_controller_decision_record_v1(public_context, projections)

    def step_with_acceptance_controller_v1(self):
        """Drive exactly one production step through the BRIDGE-C façade."""

        decision = self.acceptance_decision_record_v1()
        assert_controller_conformance_v1(decision)
        return self.step(decision.chosen_action_id)

    def step(self, action_id: str):
        """Forward one signed live action through the production dispatcher."""

        if type(action_id) is not str or not action_id:
            raise BridgeContractError("Bridge step必须接收非空production action_id")
        return super().step(BatchActionIdController(action_id))


_CANONICAL_BRIDGE_SESSION_TYPE = SkillAwareFixedAssignmentDuelSessionV1


def create_skill_aware_fixed_assignment_duel_session_v1(
    *,
    seed: int,
    general_key: object,
    seat_assignment: FixedAssignment | str,
    bridge_contract_identity: str = PROPOSED_BRIDGE_CONTRACT_IDENTITY,
) -> SkillAwareFixedAssignmentDuelSessionV1:
    """Canonical Bridge-B factory; all production authority is internal."""

    assignment = create_bridge_assignment(general_key, seat_assignment)
    return SkillAwareFixedAssignmentDuelSessionV1(
        seed=seed,
        assignment=assignment,
        bridge_contract_identity=bridge_contract_identity,
    )


def _create_skill_aware_fixed_assignment_duel_session_for_strict_replay_v1(
    *,
    seed: int,
    assignment: BridgeAssignmentDescriptor,
    session_id: str,
    session_secret_hex: str,
    capability: object,
) -> SkillAwareFixedAssignmentDuelSessionV1:
    """Private reconstruction seam; never accepts a caller session/factory."""

    if capability is not _BRIDGE_STRICT_REPLAY_RECONSTRUCTION_CAPABILITY:
        raise BridgeContractError("Bridge strict replay reconstruction capability不匹配")
    if type(assignment) is not BridgeAssignmentDescriptor:
        raise BridgeContractError("Bridge strict replay assignment必须是canonical descriptor")
    if type(session_secret_hex) is not str or re.fullmatch(
        r"[0-9a-f]{64,}", session_secret_hex
    ) is None:
        raise BridgeContractError("Bridge strict replay session secret格式不合法")
    return SkillAwareFixedAssignmentDuelSessionV1(
        seed=seed,
        assignment=assignment,
        bridge_contract_identity=PROPOSED_BRIDGE_CONTRACT_IDENTITY,
        _strict_replay_capability=capability,
        _strict_replay_session_id=session_id,
        _strict_replay_session_secret=bytes.fromhex(session_secret_hex),
    )


__all__ = [
    "BASELINE_18",
    "BASELINE_18_REGISTRY_IDENTITY",
    "BASELINE_18_SCHEMA",
    "BASELINE_18_WITNESS_OBLIGATIONS_STATUS",
    "BASE_SKILL_AUTHORITY",
    "BRIDGE_AUTHORITY_PROFILE_IDENTITY",
    "BRIDGE_MODE_PROFILE_IDENTITY",
    "BRIDGE_NAME",
    "BRIDGE_REPLAY_REQUIRED_FIELDS",
    "BRIDGE_SKILL_ALLOWLIST",
    "BRIDGE_SKILL_REGISTRY_IDENTITY",
    "BridgeAssignmentDescriptor",
    "BridgeContractError",
    "BridgeIdentityError",
    "BridgeReplayDescriptorSkeleton",
    "CONTRACT_ID",
    "CONTRACT_VERSION",
    "CONTROLLER_ID",
    "CONTROLLER_PRIVATE_FIELD_DENYLIST",
    "CONTROLLER_VERSION",
    "ControllerActionProjectionV1",
    "ControllerDecisionRecordV1",
    "DECK_IDENTITY",
    "DYNAMIC_DERIVATION_AUTHORITY",
    "EVENT_OBLIGATIONS",
    "EVENT_OBLIGATION_IDS",
    "EquipmentColorState",
    "FINAL_ACCEPTANCE_MATRIX",
    "FORMAL_DUEL_PROFILE_IDENTITY",
    "FixedAssignment",
    "GENERAL_ALLOWLIST",
    "GENERAL_ALLOWLIST_DESCRIPTORS",
    "GENERAL_REGISTRY_IDENTITY",
    "INITIALIZATION_CONTRACT",
    "INITIALIZATION_PROHIBITIONS",
    "INITIALIZATION_SEQUENCE",
    "INITIALIZATION_SEQUENCE_IDENTITY",
    "InitializationStep",
    "MAX_STEPS",
    "MINIMAL_REQUIRED_SENTINELS",
    "MODE_ID",
    "ModeModifier",
    "PARTICIPANT_IDS",
    "PRIVATE_SELECTION_ALLOWED_FIELDS",
    "PRIVATE_SELECTION_FORBIDDEN_FIELDS",
    "PROPOSED_BRIDGE_CONTRACT_IDENTITY",
    "PublicActionContextV1",
    "PublicLegalActionProjectionV1",
    "PublicOpaqueChoiceProjection",
    "REPLAY_SCHEMA",
    "REPLAY_VERSION",
    "RUNTIME_EFFECTIVE_AUTHORITY",
    "SENTINEL_POLICY",
    "SentinelDiscoveryStatus",
    "SkillAwareFixedAssignmentAcceptanceControllerV1",
    "SkillAwareFixedAssignmentDuelSessionV1",
    "SUPPORTED_ACTION_FAMILIES",
    "SUPPORTED_OPERATION_FAMILIES",
    "UNKNOWN_REPLAY_AUTHORITY_FIELD_POLICY",
    "WitnessStatus",
    "baseline_18_canonical_descriptor",
    "assert_controller_conformance_v1",
    "bridge_contract_descriptor",
    "canonical_json",
    "compute_baseline_18_registry_identity",
    "compute_bridge_contract_identity",
    "create_bridge_assignment",
    "create_bridge_assignment_from_request",
    "create_bridge_skill_registry",
    "create_controller_decision_record_v1",
    "create_skill_aware_fixed_assignment_duel_session_v1",
    "general_descriptor",
    "project_public_action_surface_v1",
    "project_signed_legal_actions_v1",
    "validate_bridge_replay_schema_marker",
    "validate_bridge_skill_id",
]
