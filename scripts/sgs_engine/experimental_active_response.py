"""Experimental active-response modifier mode v1.

This module is deliberately separate from C5/C6/C7 formal no-skill modes.  It
models only an auditable, configuration-static response modifier: it is not a
Shen Lubu implementation and does not claim Wuqian, rage, Wumou, or Shenfen.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import json
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from ..deck_data import DeckRecord, load_deck_csv
from .actions import ActionContext, InvalidActionError, LegalAction, UnsupportedRuleError
from .engine import DEFAULT_DECK_PATH
from .production_batch import (
    ProductionBasicCardBatch,
    ProductionBatchError,
    ProductionPhase,
    RequiredResponseProgress,
    advance_required_response_count,
)
from .replay import canonical_json, sha256_value


EXPERIMENTAL_ACTIVE_RESPONSE_MODE = "experimental-active-response-modifier-v1"
EXPERIMENTAL_ACTIVE_RESPONSE_CONFIGURATION_SCHEMA = (
    "experimental-active-response-modifier-configuration-v1"
)
EXPERIMENTAL_ACTIVE_RESPONSE_EXECUTION_SCHEMA = (
    "experimental-active-response-modifier-execution-v1"
)
EXPERIMENTAL_ACTIVE_RESPONSE_PROFILE_ID = (
    "experimental-minimal-active-response-modifier-profile-v1"
)
EXPERIMENTAL_ACTIVE_RESPONSE_MODIFIER_KEY = "minimal_active_response_modifier"
ACTIVATION_POLICY_CONFIGURATION_STATIC = "configuration_static"


class ExperimentalActiveResponseConfigurationError(ValueError):
    """The independent experimental configuration is malformed or untrusted."""


def _require_exact_fields(
    value: Mapping[str, object], required: set[str], label: str
) -> None:
    missing = sorted(required.difference(value))
    extra = sorted(set(value).difference(required))
    if missing:
        raise ExperimentalActiveResponseConfigurationError(
            f"{label}缺少字段：{'、'.join(missing)}"
        )
    if extra:
        raise ExperimentalActiveResponseConfigurationError(
            f"{label}包含未知字段：{'、'.join(extra)}"
        )


def _require_nonempty_str(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ExperimentalActiveResponseConfigurationError(f"{label}必须是非空字符串")
    return value.strip()


def _require_exact_str(value: object, expected: str, label: str) -> str:
    if type(value) is not str or value != expected:
        raise ExperimentalActiveResponseConfigurationError(
            f"{label}必须是{expected!r}"
        )
    return value


def _require_positive_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ExperimentalActiveResponseConfigurationError(f"{label}必须是正整数")
    return value


def _deck_definition_value(records: Sequence[DeckRecord]) -> dict[str, object]:
    """The configuration binds the complete registered production deck."""

    return {
        "deck_id": records[0].deck_id if records else "",
        "cards": [
            {
                "position": index,
                "instance_id": record.instance_id,
                "deck_id": record.deck_id,
                "card_key": record.card_key,
                "card_name": record.card_name,
                "card_type": record.card_type,
                "suit": record.suit,
                "color": record.color,
                "rank": record.rank,
                "card_variant": record.card_variant,
                "equipment_slot": record.equip_slot or None,
                "distance_modifier": (
                    int(record.distance_modifier)
                    if record.distance_modifier.strip()
                    else None
                ),
            }
            for index, record in enumerate(records)
        ],
    }


def production_deck_identity() -> tuple[str, str]:
    """Return the current registered deck id and a full-deck content hash."""

    records, _audit = load_deck_csv(DEFAULT_DECK_PATH, expected_total=160)
    if not records:
        raise ExperimentalActiveResponseConfigurationError("生产牌堆不能为空")
    definition = _deck_definition_value(records)
    return records[0].deck_id, sha256_value(definition)


@dataclass(frozen=True, slots=True)
class ExperimentalRosterEntry:
    """Configuration-owned identity metadata; it does not alter PlayerState."""

    player_id: str
    character_id: str
    character_gender: str
    hp: int
    max_hp: int
    initial_hand_count: int

    def to_dict(self) -> dict[str, object]:
        return {
            "player_id": self.player_id,
            "character_id": self.character_id,
            "character_gender": self.character_gender,
            "hp": self.hp,
            "max_hp": self.max_hp,
            "initial_hand_count": self.initial_hand_count,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "ExperimentalRosterEntry":
        _require_exact_fields(
            value,
            {
                "player_id",
                "character_id",
                "character_gender",
                "hp",
                "max_hp",
                "initial_hand_count",
            },
            "roster item",
        )
        hp = _require_positive_int(value["hp"], "roster.hp")
        max_hp = _require_positive_int(value["max_hp"], "roster.max_hp")
        if hp > max_hp:
            raise ExperimentalActiveResponseConfigurationError(
                "roster.hp不能高于roster.max_hp"
            )
        return cls(
            player_id=_require_nonempty_str(value["player_id"], "roster.player_id"),
            character_id=_require_nonempty_str(
                value["character_id"], "roster.character_id"
            ),
            character_gender=_require_nonempty_str(
                value["character_gender"], "roster.character_gender"
            ),
            hp=hp,
            max_hp=max_hp,
            initial_hand_count=_require_positive_int(
                value["initial_hand_count"], "roster.initial_hand_count"
            ),
        )


@dataclass(frozen=True, slots=True)
class ExperimentalActiveResponseProfile:
    """The frozen, deliberately minimal experimental profile."""

    profile_id: str
    version: int
    modifier_owner_id: str
    modifier_key: str
    activation_policy: str

    def to_dict(self) -> dict[str, object]:
        return {
            "profile_id": self.profile_id,
            "version": self.version,
            "modifier_owner_id": self.modifier_owner_id,
            "modifier_key": self.modifier_key,
            "activation_policy": self.activation_policy,
        }

    @classmethod
    def from_dict(
        cls, value: Mapping[str, object]
    ) -> "ExperimentalActiveResponseProfile":
        _require_exact_fields(
            value,
            {
                "profile_id",
                "version",
                "modifier_owner_id",
                "modifier_key",
                "activation_policy",
            },
            "skill_profile",
        )
        return cls(
            profile_id=_require_exact_str(
                value["profile_id"],
                EXPERIMENTAL_ACTIVE_RESPONSE_PROFILE_ID,
                "skill_profile.profile_id",
            ),
            version=(
                1
                if value["version"] == 1 and not isinstance(value["version"], bool)
                else (_raise_profile_version())
            ),
            modifier_owner_id=_require_nonempty_str(
                value["modifier_owner_id"], "skill_profile.modifier_owner_id"
            ),
            modifier_key=_require_exact_str(
                value["modifier_key"],
                EXPERIMENTAL_ACTIVE_RESPONSE_MODIFIER_KEY,
                "skill_profile.modifier_key",
            ),
            activation_policy=_require_exact_str(
                value["activation_policy"],
                ACTIVATION_POLICY_CONFIGURATION_STATIC,
                "skill_profile.activation_policy",
            ),
        )


def _raise_profile_version() -> int:
    raise ExperimentalActiveResponseConfigurationError(
        "skill_profile.version必须是整数1"
    )


@dataclass(frozen=True, slots=True)
class ExperimentalActiveResponseConfiguration:
    """Strict, opt-in configuration for the isolated experimental session."""

    schema: str
    mode_id: str
    experimental: bool
    formal_result: bool
    deck_id: str
    deck_hash: str
    roster: tuple[ExperimentalRosterEntry, ExperimentalRosterEntry]
    skill_profile: ExperimentalActiveResponseProfile

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "mode_id": self.mode_id,
            "experimental": self.experimental,
            "formal_result": self.formal_result,
            "deck_id": self.deck_id,
            "deck_hash": self.deck_hash,
            "roster": [entry.to_dict() for entry in self.roster],
            "skill_profile": self.skill_profile.to_dict(),
        }

    @property
    def identity(self) -> str:
        return sha256_value(self.to_dict())

    @classmethod
    def from_dict(
        cls, value: Mapping[str, object]
    ) -> "ExperimentalActiveResponseConfiguration":
        if cls is not ExperimentalActiveResponseConfiguration:
            raise ExperimentalActiveResponseConfigurationError(
                "实验配置解析禁止通过子类改变exact dataclass type"
            )
        _require_exact_fields(
            value,
            {
                "schema",
                "mode_id",
                "experimental",
                "formal_result",
                "deck_id",
                "deck_hash",
                "roster",
                "skill_profile",
            },
            "experimental active-response configuration",
        )
        raw_roster = value["roster"]
        if isinstance(raw_roster, (str, bytes)) or not isinstance(
            raw_roster, Sequence
        ):
            raise ExperimentalActiveResponseConfigurationError("roster必须是两人数组")
        if len(raw_roster) != 2:
            raise ExperimentalActiveResponseConfigurationError("roster必须恰好包含两人")
        entries: list[ExperimentalRosterEntry] = []
        for index, item in enumerate(raw_roster):
            if not isinstance(item, Mapping):
                raise ExperimentalActiveResponseConfigurationError(
                    f"roster[{index}]必须是对象"
                )
            entries.append(ExperimentalRosterEntry.from_dict(item))
        raw_profile = value["skill_profile"]
        if not isinstance(raw_profile, Mapping):
            raise ExperimentalActiveResponseConfigurationError("skill_profile必须是对象")
        configuration = cls(
            schema=_require_exact_str(
                value["schema"],
                EXPERIMENTAL_ACTIVE_RESPONSE_CONFIGURATION_SCHEMA,
                "schema",
            ),
            mode_id=_require_exact_str(
                value["mode_id"],
                EXPERIMENTAL_ACTIVE_RESPONSE_MODE,
                "mode_id",
            ),
            experimental=(
                True
                if value["experimental"] is True
                else (_raise_configuration_flag("experimental", True))
            ),
            formal_result=(
                False
                if value["formal_result"] is False
                else (_raise_configuration_flag("formal_result", False))
            ),
            deck_id=_require_nonempty_str(value["deck_id"], "deck_id"),
            deck_hash=_require_nonempty_str(value["deck_hash"], "deck_hash"),
            roster=(entries[0], entries[1]),
            skill_profile=ExperimentalActiveResponseProfile.from_dict(raw_profile),
        )
        configuration.assert_structural_validity()
        return configuration

    @classmethod
    def default_profile(cls) -> "ExperimentalActiveResponseConfiguration":
        deck_id, deck_hash = production_deck_identity()
        return cls.from_dict(
            {
                "schema": EXPERIMENTAL_ACTIVE_RESPONSE_CONFIGURATION_SCHEMA,
                "mode_id": EXPERIMENTAL_ACTIVE_RESPONSE_MODE,
                "experimental": True,
                "formal_result": False,
                "deck_id": deck_id,
                "deck_hash": deck_hash,
                "roster": [
                    {
                        "player_id": "experimental_modifier_holder",
                        "character_id": "experimental_modifier_holder",
                        "character_gender": "unknown",
                        "hp": 4,
                        "max_hp": 4,
                        "initial_hand_count": 4,
                    },
                    {
                        "player_id": "experimental_opponent",
                        "character_id": "experimental_opponent",
                        "character_gender": "unknown",
                        "hp": 4,
                        "max_hp": 4,
                        "initial_hand_count": 4,
                    },
                ],
                "skill_profile": {
                    "profile_id": EXPERIMENTAL_ACTIVE_RESPONSE_PROFILE_ID,
                    "version": 1,
                    "modifier_owner_id": "experimental_modifier_holder",
                    "modifier_key": EXPERIMENTAL_ACTIVE_RESPONSE_MODIFIER_KEY,
                    "activation_policy": ACTIVATION_POLICY_CONFIGURATION_STATIC,
                },
            }
        )

    def assert_structural_validity(self) -> None:
        if type(self) is not ExperimentalActiveResponseConfiguration:
            raise ExperimentalActiveResponseConfigurationError(
                "实验会话只接受exact ExperimentalActiveResponseConfiguration"
            )
        if self.schema != EXPERIMENTAL_ACTIVE_RESPONSE_CONFIGURATION_SCHEMA:
            raise ExperimentalActiveResponseConfigurationError("实验配置schema不匹配")
        if self.mode_id != EXPERIMENTAL_ACTIVE_RESPONSE_MODE:
            raise ExperimentalActiveResponseConfigurationError("实验配置mode_id不匹配")
        if self.experimental is not True or self.formal_result is not False:
            raise ExperimentalActiveResponseConfigurationError(
                "实验配置必须声明experimental=true且formal_result=false"
            )
        if type(self.roster) is not tuple or len(self.roster) != 2:
            raise ExperimentalActiveResponseConfigurationError("实验配置roster必须是exact两人元组")
        if any(type(entry) is not ExperimentalRosterEntry for entry in self.roster):
            raise ExperimentalActiveResponseConfigurationError("实验配置roster项类型无效")
        for entry in self.roster:
            # Reuse the strict parser for direct dataclass construction too.
            ExperimentalRosterEntry.from_dict(entry.to_dict())
        player_ids = tuple(entry.player_id for entry in self.roster)
        if len(set(player_ids)) != 2:
            raise ExperimentalActiveResponseConfigurationError("实验配置玩家ID必须唯一")
        if type(self.skill_profile) is not ExperimentalActiveResponseProfile:
            raise ExperimentalActiveResponseConfigurationError("实验配置skill_profile类型无效")
        ExperimentalActiveResponseProfile.from_dict(self.skill_profile.to_dict())
        profile = self.skill_profile
        if (
            profile.profile_id != EXPERIMENTAL_ACTIVE_RESPONSE_PROFILE_ID
            or profile.version != 1
            or profile.modifier_key != EXPERIMENTAL_ACTIVE_RESPONSE_MODIFIER_KEY
            or profile.activation_policy != ACTIVATION_POLICY_CONFIGURATION_STATIC
        ):
            raise ExperimentalActiveResponseConfigurationError("实验配置skill_profile不受支持")
        if profile.modifier_owner_id not in player_ids:
            raise ExperimentalActiveResponseConfigurationError(
                "唯一modifier owner必须属于实验roster"
            )

    def assert_deck_matches_registered_production_deck(self) -> None:
        actual_id, actual_hash = production_deck_identity()
        if self.deck_id != actual_id or self.deck_hash != actual_hash:
            raise ExperimentalActiveResponseConfigurationError(
                "实验配置绑定的deck_id或完整deck_hash与当前注册生产牌堆不一致"
            )


def _raise_configuration_flag(label: str, expected: bool) -> bool:
    raise ExperimentalActiveResponseConfigurationError(
        f"{label}必须是{str(expected).lower()}"
    )


@dataclass(frozen=True, slots=True)
class ExperimentalSkillState:
    """Immutable state assembled only by the experimental session factory."""

    schema: str
    profile_id: str
    profile_version: int
    modifier_owner_id: str
    modifier_key: str
    activation_policy: str
    modifier_active: bool
    state_version: int

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "profile_id": self.profile_id,
            "profile_version": self.profile_version,
            "modifier_owner_id": self.modifier_owner_id,
            "modifier_key": self.modifier_key,
            "activation_policy": self.activation_policy,
            "modifier_active": self.modifier_active,
            "state_version": self.state_version,
        }


@dataclass(frozen=True, slots=True)
class PendingResponseObligation:
    """Extension-owned multiple-response state; never stored in formal pending roots."""

    obligation_id: str
    responder_id: str
    required_response_count: int
    provided_response_count: int
    response_card_type: str
    root_card_id: str
    skill_source: str
    duel_response_index: int | None
    root_card_type: str
    response_kind: str

    def to_dict(self) -> dict[str, object]:
        return {
            "obligation_id": self.obligation_id,
            "responder_id": self.responder_id,
            "required_response_count": self.required_response_count,
            "provided_response_count": self.provided_response_count,
            "response_card_type": self.response_card_type,
            "root_card_id": self.root_card_id,
            "skill_source": self.skill_source,
            "duel_response_index": self.duel_response_index,
            "root_card_type": self.root_card_type,
            "response_kind": self.response_kind,
        }


def _build_skill_state(
    configuration: ExperimentalActiveResponseConfiguration,
) -> ExperimentalSkillState:
    """The only construction path for experimental skill state."""

    configuration.assert_structural_validity()
    profile = configuration.skill_profile
    return ExperimentalSkillState(
        schema="experimental-active-response-skill-state-v1",
        profile_id=profile.profile_id,
        profile_version=profile.version,
        modifier_owner_id=profile.modifier_owner_id,
        modifier_key=profile.modifier_key,
        activation_policy=profile.activation_policy,
        # configuration_static means the profile owner has this *minimal*
        # modifier for the entire session.  It is not a Wuqian lifecycle.
        modifier_active=True,
        state_version=1,
    )


class ExperimentalActiveResponseSession(ProductionBasicCardBatch):
    """Independent two-player experimental session with no external state injection."""

    MODE_ID = EXPERIMENTAL_ACTIVE_RESPONSE_MODE

    def __init__(
        self,
        *,
        seed: int,
        configuration: ExperimentalActiveResponseConfiguration,
        session_id: str | None = None,
        session_secret: bytes | None = None,
    ) -> None:
        if type(self) is not ExperimentalActiveResponseSession:
            raise TypeError("实验 active-response 会话不允许通过子类改变边界")
        if type(configuration) is not ExperimentalActiveResponseConfiguration:
            raise TypeError(
                "实验 active-response 会话必须接收exact ExperimentalActiveResponseConfiguration"
            )
        configuration.assert_structural_validity()
        configuration.assert_deck_matches_registered_production_deck()
        self._experimental_configuration = configuration
        self._experimental_skill_state = _build_skill_state(configuration)
        self._pending_response_obligation: PendingResponseObligation | None = None
        super().__init__(
            seed=seed,
            player_hp=tuple(entry.hp for entry in configuration.roster),
            player_max_hp=tuple(entry.max_hp for entry in configuration.roster),
            player_ids=tuple(entry.player_id for entry in configuration.roster),
            initial_hand_counts=tuple(
                entry.initial_hand_count for entry in configuration.roster
            ),
            first_player_id=configuration.roster[0].player_id,
            shuffle=True,
            session_id=session_id,
            session_secret=session_secret,
        )
        if self.state.deck_id != configuration.deck_id:
            raise ExperimentalActiveResponseConfigurationError(
                "实验会话初始化后的牌堆ID与冻结配置不一致"
            )

    @property
    def configuration(self) -> ExperimentalActiveResponseConfiguration:
        return self._experimental_configuration

    @property
    def experimental_skill_state(self) -> ExperimentalSkillState:
        return self._experimental_skill_state

    @property
    def pending_response_obligation(self) -> PendingResponseObligation | None:
        return self._pending_response_obligation

    @property
    def experimental(self) -> bool:
        return True

    @property
    def formal_result_eligible(self) -> bool:
        return False

    def _required_count(
        self,
        *,
        root_card_type: str,
        responder_id: str,
        source_id: str,
    ) -> int:
        state = self._experimental_skill_state
        if not state.modifier_active:
            return 1
        owner = state.modifier_owner_id
        if root_card_type == "slash":
            # Only the static holder's own Slash imposes two real Dodges.
            return 2 if source_id == owner and responder_id != owner else 1
        if root_card_type == "duel":
            # In every duel involving H, H's opponent needs two Slashes while
            # H always needs one, regardless of who started the duel.
            return 2 if source_id == owner and responder_id != owner else 1
        raise ProductionBatchError("实验响应义务根牌类型不受支持")

    def _open_required_response_obligation(
        self,
        *,
        response_kind: str,
        root_card_id: str,
        root_card_type: str,
        responder_id: str,
        response_card_type: str,
        source_id: str,
        duel_response_index: int | None,
    ) -> None:
        if self._pending_response_obligation is not None:
            raise ProductionBatchError("实验响应义务未完成时禁止覆盖建立新义务")
        if response_kind not in ("slash_dodge", "duel_slash"):
            raise ProductionBatchError("实验响应义务类型不受支持")
        if root_card_type not in ("slash", "duel"):
            raise ProductionBatchError("实验根牌类型不受支持")
        if response_card_type not in ("dodge", "slash"):
            raise ProductionBatchError("实验响应牌类型不受支持")
        if (root_card_type == "duel") != (duel_response_index is not None):
            raise ProductionBatchError("实验义务的决斗响应序号与根牌类型不一致")
        required = self._required_count(
            root_card_type=root_card_type,
            responder_id=responder_id,
            source_id=source_id,
        )
        material = {
            "configuration_identity": self.configuration.identity,
            "response_kind": response_kind,
            "root_card_type": root_card_type,
            "root_card_id": root_card_id,
            "responder_id": responder_id,
            "response_card_type": response_card_type,
            "duel_response_index": duel_response_index,
        }
        self._pending_response_obligation = PendingResponseObligation(
            obligation_id="aro_" + sha256_value(material)[:32],
            responder_id=responder_id,
            required_response_count=required,
            provided_response_count=0,
            response_card_type=response_card_type,
            root_card_id=root_card_id,
            skill_source=(
                f"{self._experimental_skill_state.profile_id}:"
                f"{self._experimental_skill_state.modifier_owner_id}"
            ),
            duel_response_index=duel_response_index,
            root_card_type=root_card_type,
            response_kind=response_kind,
        )

    def _advance_required_response_progress(
        self,
        *,
        response_kind: str,
        root_card_id: str,
        responder_id: str,
        response_card_type: str,
        duel_response_index: int | None,
    ) -> RequiredResponseProgress:
        obligation = self._pending_response_obligation
        if obligation is None:
            raise ProductionBatchError("实验响应提交缺少PendingResponseObligation")
        if (
            obligation.response_kind != response_kind
            or obligation.root_card_id != root_card_id
            or obligation.responder_id != responder_id
            or obligation.response_card_type != response_card_type
            or obligation.duel_response_index != duel_response_index
        ):
            raise ProductionBatchError("实验响应提交与当前义务绑定不一致")
        provided, completed = advance_required_response_count(
            obligation.required_response_count,
            obligation.provided_response_count,
        )
        event_obligation = replace(obligation, provided_response_count=provided)
        return RequiredResponseProgress(
            response_kind=response_kind,
            root_card_id=root_card_id,
            responder_id=responder_id,
            required_response_count=obligation.required_response_count,
            provided_response_count=provided,
            completed=completed,
            event_payload=MappingProxyType(
                {"experimental_response_obligation": event_obligation.to_dict()}
            ),
        )

    def _commit_required_response_progress(
        self, progress: RequiredResponseProgress
    ) -> None:
        obligation = self._pending_response_obligation
        if obligation is None:
            raise ProductionBatchError("实验响应进度提交缺少义务")
        if (
            progress.response_kind != obligation.response_kind
            or progress.root_card_id != obligation.root_card_id
            or progress.responder_id != obligation.responder_id
            or progress.required_response_count != obligation.required_response_count
        ):
            raise ProductionBatchError("实验响应进度提交与义务不一致")
        if progress.completed:
            if progress.provided_response_count != obligation.required_response_count:
                raise ProductionBatchError("实验完成义务的计数不一致")
            self._pending_response_obligation = None
            return
        if progress.provided_response_count >= obligation.required_response_count:
            raise ProductionBatchError("实验未完成义务的计数越界")
        self._pending_response_obligation = replace(
            obligation, provided_response_count=progress.provided_response_count
        )

    def _clear_required_response_obligation(
        self,
        *,
        response_kind: str,
        root_card_id: str,
        responder_id: str,
        duel_response_index: int | None,
    ) -> None:
        obligation = self._pending_response_obligation
        if obligation is None:
            raise ProductionBatchError("实验响应放弃时缺少义务")
        if (
            obligation.response_kind != response_kind
            or obligation.root_card_id != root_card_id
            or obligation.responder_id != responder_id
            or obligation.duel_response_index != duel_response_index
        ):
            raise ProductionBatchError("实验响应放弃与当前义务绑定不一致")
        self._pending_response_obligation = None

    @staticmethod
    def _response_binding_value(
        obligation: PendingResponseObligation
    ) -> dict[str, object]:
        return {
            "response_obligation_id": obligation.obligation_id,
            "response_obligation_root_card_id": obligation.root_card_id,
            "response_obligation_root_card_type": obligation.root_card_type,
            "response_obligation_required_count": obligation.required_response_count,
            "response_obligation_provided_count": obligation.provided_response_count,
            "response_obligation_duel_response_index": obligation.duel_response_index,
        }

    def _bind_response_action(
        self, action: LegalAction, obligation: PendingResponseObligation
    ) -> LegalAction:
        if action.action_id is None:
            raise ProductionBatchError("实验响应动作必须先由生产枚举器签发")
        payload = dict(action.payload)
        payload.update(self._response_binding_value(obligation))
        action_id = sha256_value(
            {
                "schema": "experimental-active-response-action-binding-v1",
                "base_action_id": action.action_id,
                "configuration_identity": self.configuration.identity,
                "obligation": obligation.to_dict(),
                "payload": payload,
            }
        )
        return replace(action, action_id=action_id, payload=payload)

    def legal_actions(self) -> tuple[LegalAction, ...]:
        actions = super().legal_actions()
        if self.phase not in (
            ProductionPhase.SLASH_RESPONSE,
            ProductionPhase.DUEL_RESPONSE,
        ):
            return actions
        obligation = self._pending_response_obligation
        if obligation is None:
            raise ProductionBatchError("实验响应阶段缺少PendingResponseObligation")
        bound: list[LegalAction] = []
        for action in actions:
            operation = str(action.payload.get("operation", ""))
            if operation == "activate_bagua":
                # The second response interaction is not backed by a rule
                # source.  Phase 1 permits only physical Dodge/Slash responses.
                continue
            if action.payload.get("zhangba_virtual") is True:
                # The shared core has an audited material lifecycle for this
                # virtual Slash, but phase 1 does not yet have an isolated
                # experimental strict-replay proof for the two-response case.
                # Keep the extension closed until that proof is added.
                continue
            if operation in (
                "play_dodge",
                "pass_slash_response",
                "play_slash_for_duel",
                "pass_duel_slash",
            ):
                bound.append(self._bind_response_action(action, obligation))
            else:
                raise ProductionBatchError("实验响应阶段出现未审计动作类型")
        return tuple(bound)

    def _validate_session_action(
        self,
        state: Any,
        context: ActionContext,
        action: LegalAction,
    ) -> LegalAction:
        if not isinstance(action, LegalAction) or action.action_id is None:
            raise InvalidActionError("实验会话只能提交当前签发的动作")
        legal = self.legal_actions()
        canonical = next(
            (item for item in legal if item.action_id == action.action_id), None
        )
        if canonical is None or action != canonical:
            raise InvalidActionError("实验响应动作已过期、伪造或义务绑定不一致")
        return canonical

    def _apply_session_action(
        self,
        state: Any,
        context: ActionContext,
        action: LegalAction,
    ) -> Any:
        # The canonical action has already been checked against the session's
        # obligation-bound legal set.  Dispatch directly to the exact adapter,
        # avoiding the public stateless enumerator which intentionally knows
        # nothing about this extension-owned state.
        return self.registry.resolve(context.mode, context.phase).apply_action(
            state, context, action
        )

    def apply_bagua_activate(
        self,
        state: Any,
        context: ActionContext,
        action: LegalAction,
        adapter: object,
    ) -> Any:
        del state, context, action, adapter
        raise UnsupportedRuleError(
            "BLOCKED_BY_RULE_SOURCE：experimental phase1不接受八卦阵替代响应"
        )

    @property
    def execution_snapshot(self) -> dict[str, object]:
        snapshot = {
            "schema": EXPERIMENTAL_ACTIVE_RESPONSE_EXECUTION_SCHEMA,
            "experimental": True,
            "formal_result": False,
            "configuration_identity": self.configuration.identity,
            "configuration": self.configuration.to_dict(),
            "skill_state": self.experimental_skill_state.to_dict(),
            "pending_response_obligation": (
                None
                if self.pending_response_obligation is None
                else self.pending_response_obligation.to_dict()
            ),
            "production_execution_snapshot": super().execution_snapshot,
        }
        value = json.loads(canonical_json(snapshot))
        assert isinstance(value, dict)
        return value

    def assert_resolution_invariants(self) -> None:
        super().assert_resolution_invariants()
        obligation = self._pending_response_obligation
        if obligation is None:
            return
        if self.phase is ProductionPhase.SLASH_RESPONSE:
            pending = self.runtime.pending_slash
            valid = (
                obligation.response_kind == "slash_dodge"
                and obligation.root_card_type == "slash"
                and obligation.duel_response_index is None
                and pending is not None
                and obligation.root_card_id == pending.slash_instance_id
                and obligation.responder_id == pending.target_id
                and obligation.response_card_type == "dodge"
            )
        elif self.phase is ProductionPhase.DUEL_RESPONSE:
            pending_duel = self.runtime.pending_duel
            valid = (
                obligation.response_kind == "duel_slash"
                and obligation.root_card_type == "duel"
                and pending_duel is not None
                and obligation.root_card_id == pending_duel.trick_instance_id
                and obligation.responder_id == pending_duel.responder_id
                and obligation.duel_response_index == pending_duel.response_index
                and obligation.response_card_type == "slash"
            )
        else:
            valid = False
        if not valid:
            raise ProductionBatchError("实验PendingResponseObligation与生产运行时分叉")


def create_experimental_active_response_session(
    *,
    seed: int,
    configuration: ExperimentalActiveResponseConfiguration,
    session_id: str | None = None,
    session_secret: bytes | None = None,
) -> ExperimentalActiveResponseSession:
    """The isolated factory; it intentionally accepts no skill/provider/fixture state."""

    return ExperimentalActiveResponseSession(
        seed=seed,
        configuration=configuration,
        session_id=session_id,
        session_secret=session_secret,
    )


__all__ = [
    "ACTIVATION_POLICY_CONFIGURATION_STATIC",
    "EXPERIMENTAL_ACTIVE_RESPONSE_CONFIGURATION_SCHEMA",
    "EXPERIMENTAL_ACTIVE_RESPONSE_EXECUTION_SCHEMA",
    "EXPERIMENTAL_ACTIVE_RESPONSE_MODE",
    "EXPERIMENTAL_ACTIVE_RESPONSE_MODIFIER_KEY",
    "EXPERIMENTAL_ACTIVE_RESPONSE_PROFILE_ID",
    "ExperimentalActiveResponseConfiguration",
    "ExperimentalActiveResponseConfigurationError",
    "ExperimentalActiveResponseProfile",
    "ExperimentalActiveResponseSession",
    "ExperimentalRosterEntry",
    "ExperimentalSkillState",
    "PendingResponseObligation",
    "create_experimental_active_response_session",
    "production_deck_identity",
]
