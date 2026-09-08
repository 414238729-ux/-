# -*- coding: utf-8 -*-
"""Authoritative no-skill full-game V1 aggregate acceptance.

This module deliberately does not make :class:`AuthoritativeCoreSession` a
full-game runner.  It composes the six already-trusted formal no-skill mode
facades through their public production action path, and records a new V2
acceptance replay envelope around the compatible production-replay V1 record.

The aggregate controller is an acceptance policy, not an AI.  It can observe
only the already-issued legal actions and a deliberately public projection of
the current action context.  It never receives a session, ``GameState``, RNG,
deck, or private hand access.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from .actions import ActionContext, ActionType, LegalAction, VirtualCardReference
from .formal_duel import (
    FormalDuelConfiguration,
    FormalNoSkillDuelSession,
    deck_identity,
    implementation_identity,
    rules_profile_identity,
)
from .mode_2v2 import (
    FORMAL_NO_SKILL_2V2_MODE,
    Formal2v2Configuration,
    Formal2v2Session,
)
from .mode_doudizhu import (
    FORMAL_NO_SKILL_DOUDIZHU_MODE,
    FormalDoudizhuConfiguration,
    FormalDoudizhuSession,
)
from .mode_identity import (
    FORMAL_NO_SKILL_IDENTITY_5P_MODE,
    FORMAL_NO_SKILL_IDENTITY_8P_MODE,
    FormalEightPlayerIdentityConfiguration,
    FormalEightPlayerIdentitySession,
    FormalIdentityConfiguration,
    FormalIdentitySession,
)
from .mode_identity_heir import (
    FORMAL_NO_SKILL_IDENTITY_8P_HEIR_MODE,
    FormalHeirAndSpyChoiceIdentityConfiguration,
    FormalHeirAndSpyChoiceIdentitySession,
)
from .production_batch import (
    FORMAL_NO_SKILL_DUEL_MODE,
    BatchReferenceController,
    ProductionBasicCardBatch,
    ProductionBatchError,
)
from .production_cards import PRODUCTION_DELAYED_TRICK_KEYS
from .production_replay import (
    ProductionReexecutionReplay,
    ProductionReplayDivergenceError,
    ProductionReplayFormatError,
    ProductionReplayVerificationResult,
    record_reference_production_batch,
    reexecute_production_replay,
)
from .replay import canonical_json, sha256_value


AUTHORITATIVE_NO_SKILL_FULL_GAME_V1_CONTRACT_ID = (
    "authoritative-no-skill-full-game-v1"
)
AUTHORITATIVE_NO_SKILL_REPLAY_V2_SCHEMA = (
    "sgs-authoritative-no-skill-full-game-replay-v2"
)
AUTHORITATIVE_NO_SKILL_CELL_REPORT_SCHEMA_V1 = (
    "sgs-authoritative-no-skill-full-game-cell-report-v1"
)
NO_SKILL_ACCEPTANCE_CONTROLLER_V1_ID = "no-skill-acceptance-controller-v1"
NO_SKILL_ACCEPTANCE_CONTROLLER_V1_VERSION = "1"

# The V1 completion grid is intentionally frozen here.  Stage 1/2 only runs a
# small smoke subset; it must not be represented as a completed aggregate.
AUTHORITATIVE_NO_SKILL_ACCEPTANCE_SEEDS_V1: tuple[int, ...] = (*range(20), 49)


class AuthoritativeNoSkillFullGameError(ValueError):
    """The V1 aggregate contract, artifact, or factory boundary was violated."""


class AuthoritativeNoSkillReplayV2IdentityError(ProductionReplayDivergenceError):
    """V2 identity differs before the V1 reexecutor may construct a session."""

    def __init__(self, label: str, expected: str, actual: str) -> None:
        super().__init__(
            "identity",
            None,
            f"replay-v2 {label}不匹配；拒绝在身份漂移下重建会话",
            expected=expected,
            actual=actual,
        )
        self.label = label


def _plain(value: object) -> Any:
    return json.loads(canonical_json(value))


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, tuple):
        return tuple(_freeze(item) for item in value)
    return value


def _require_mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise AuthoritativeNoSkillFullGameError(f"{label}必须是JSON对象")
    return value


def _require_exact_fields(
    value: Mapping[str, object], required: frozenset[str], label: str
) -> None:
    missing = sorted(required.difference(value))
    extra = sorted(set(value).difference(required))
    if missing:
        raise AuthoritativeNoSkillFullGameError(
            f"{label}缺少字段：{', '.join(missing)}"
        )
    if extra:
        raise AuthoritativeNoSkillFullGameError(
            f"{label}包含未知字段：{', '.join(extra)}"
        )


def _require_sha256(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise AuthoritativeNoSkillFullGameError(f"{label}必须是小写64位SHA-256")
    return value


def _require_seed(value: object, label: str = "seed") -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise AuthoritativeNoSkillFullGameError(f"{label}必须是非负整数")
    return value


@dataclass(frozen=True, slots=True)
class PublicActionContextV1:
    """Acceptance policy may receive only this public context projection."""

    mode_id: str
    phase: str
    actor_id: str
    turn_player_id: str | None
    response_window_id: str | None
    expected_revision: int | None

    @classmethod
    def from_action_context(cls, context: ActionContext) -> "PublicActionContextV1":
        if not isinstance(context, ActionContext):
            raise TypeError("acceptance controller必须接收ActionContext")
        # Intentionally do not copy context.metadata: it is not intrinsically
        # public and may contain private selection handles.
        return cls(
            mode_id=context.mode,
            phase=context.phase,
            actor_id=context.actor_id,
            turn_player_id=context.turn_player_id,
            response_window_id=context.response_window_id,
            expected_revision=context.expected_revision,
        )

    def as_action_context(self) -> ActionContext:
        return ActionContext(
            mode=self.mode_id,
            phase=self.phase,
            actor_id=self.actor_id,
            turn_player_id=self.turn_player_id,
            response_window_id=self.response_window_id,
            expected_revision=self.expected_revision,
            metadata={},
        )


class NoSkillAcceptanceControllerV1:
    """Deterministic acceptance policy; explicitly not an AI.

    The only selection input is ``legal_actions`` plus the public projection
    above.  ``BatchReferenceController`` already implements the project-wide
    deterministic action ranking and itself has no session access.  Reusing it
    avoids creating a second priority algorithm while this façade prevents
    private ``ActionContext.metadata`` from reaching it.
    """

    controller_id = NO_SKILL_ACCEPTANCE_CONTROLLER_V1_ID
    controller_version = NO_SKILL_ACCEPTANCE_CONTROLLER_V1_VERSION
    strategy_version = (
        f"{NO_SKILL_ACCEPTANCE_CONTROLLER_V1_ID}."
        f"{NO_SKILL_ACCEPTANCE_CONTROLLER_V1_VERSION}"
    )

    def __init__(self) -> None:
        self._reference = BatchReferenceController()

    def choose_action_id(
        self,
        legal_actions: Sequence[LegalAction],
        public_context: PublicActionContextV1,
    ) -> str:
        if not isinstance(public_context, PublicActionContextV1):
            raise TypeError("acceptance policy只能读取PublicActionContextV1")
        chosen = self._reference.choose(
            legal_actions, public_context.as_action_context()
        )
        if chosen.action_id is None:
            raise ProductionBatchError("acceptance policy收到未签发ID的合法动作")
        return chosen.action_id

    def choose(
        self, legal_actions: Sequence[LegalAction], context: ActionContext
    ) -> LegalAction:
        public_context = PublicActionContextV1.from_action_context(context)
        action_id = self.choose_action_id(legal_actions, public_context)
        for action in legal_actions:
            if action.action_id == action_id:
                return action
        raise ProductionBatchError("acceptance policy返回的ID不在当前合法动作集合中")


@dataclass(frozen=True, slots=True)
class CanonicalNoSkillModeV1:
    """Sealed trusted canonical mode factory; it accepts no caller factory."""

    mode_id: str
    label: str
    multiplayer: bool
    configuration_type: type[object]
    session_type: type[ProductionBasicCardBatch]
    max_steps: int

    @property
    def mode_contract_id(self) -> str:
        """The sealed per-mode contract bound into every replay-v2 header."""

        return f"{AUTHORITATIVE_NO_SKILL_FULL_GAME_V1_CONTRACT_ID}:{self.mode_id}"

    def create_session(self, seed: int, *, session_id: str | None = None) -> ProductionBasicCardBatch:
        seed = _require_seed(seed)
        configuration_factory = getattr(self.configuration_type, "formal_profile", None)
        if not callable(configuration_factory):  # defensive registry integrity check
            raise AuthoritativeNoSkillFullGameError(
                f"{self.mode_id}缺少trusted canonical formal_profile工厂"
            )
        configuration = configuration_factory()
        # Optional public run identity; signing secret remains freshly generated
        # by the canonical session constructor and is never supplied by a driver.
        identity_args = {} if session_id is None else {"session_id": session_id}
        session = self.session_type(
            seed=seed,
            configuration=configuration,
            analysis_only=False,
            **identity_args,
        )
        if type(session) is not self.session_type or session.mode_id != self.mode_id:
            raise AuthoritativeNoSkillFullGameError(
                f"{self.mode_id} canonical factory返回了非预期session façade"
            )
        if getattr(session, "analysis_only", None) is not False:
            raise AuthoritativeNoSkillFullGameError(
                f"{self.mode_id} aggregate acceptance禁止analysis_only"
            )
        return session

    def profile_identity(self) -> str:
        configuration_factory = getattr(self.configuration_type, "formal_profile", None)
        if not callable(configuration_factory):
            raise AuthoritativeNoSkillFullGameError(
                f"{self.mode_id}缺少trusted canonical formal_profile工厂"
            )
        if self.mode_id == FORMAL_NO_SKILL_DUEL_MODE:
            # Preserve the existing formal-duel identity calculation exactly.
            return rules_profile_identity()
        configuration = configuration_factory()
        to_dict = getattr(configuration, "to_dict", None)
        if not callable(to_dict):
            raise AuthoritativeNoSkillFullGameError(
                f"{self.mode_id} canonical profile不可序列化"
            )
        return sha256_value(to_dict())


# The registry is a literal six-mode contract.  No discovery or automatic
# inclusion is permitted, so C8/skill/timed/other identity variants cannot
# enter an aggregate artifact accidentally.
AUTHORITATIVE_NO_SKILL_MODE_REGISTRY_V1: tuple[CanonicalNoSkillModeV1, ...] = (
    CanonicalNoSkillModeV1(
        FORMAL_NO_SKILL_DUEL_MODE,
        "formal duel",
        False,
        FormalDuelConfiguration,
        FormalNoSkillDuelSession,
        2000,
    ),
    CanonicalNoSkillModeV1(
        FORMAL_NO_SKILL_2V2_MODE,
        "C3 2v2",
        True,
        Formal2v2Configuration,
        Formal2v2Session,
        2000,
    ),
    CanonicalNoSkillModeV1(
        FORMAL_NO_SKILL_DOUDIZHU_MODE,
        "C4 斗地主",
        True,
        FormalDoudizhuConfiguration,
        FormalDoudizhuSession,
        2000,
    ),
    CanonicalNoSkillModeV1(
        FORMAL_NO_SKILL_IDENTITY_5P_MODE,
        "C5 5p identity",
        True,
        FormalIdentityConfiguration,
        FormalIdentitySession,
        2000,
    ),
    CanonicalNoSkillModeV1(
        FORMAL_NO_SKILL_IDENTITY_8P_MODE,
        "C6 8p identity",
        True,
        FormalEightPlayerIdentityConfiguration,
        FormalEightPlayerIdentitySession,
        4000,
    ),
    CanonicalNoSkillModeV1(
        FORMAL_NO_SKILL_IDENTITY_8P_HEIR_MODE,
        "C7 heir/spy identity",
        True,
        FormalHeirAndSpyChoiceIdentityConfiguration,
        FormalHeirAndSpyChoiceIdentitySession,
        4000,
    ),
)
_MODE_BY_ID = MappingProxyType(
    {spec.mode_id: spec for spec in AUTHORITATIVE_NO_SKILL_MODE_REGISTRY_V1}
)
if len(_MODE_BY_ID) != 6:  # pragma: no cover - source-level contract guard
    raise RuntimeError("V1 aggregate mode registry必须恰好包含六种不同模式")


def canonical_no_skill_mode_v1(mode_id: str) -> CanonicalNoSkillModeV1:
    if not isinstance(mode_id, str) or not mode_id.strip():
        raise AuthoritativeNoSkillFullGameError("mode_id必须是非空字符串")
    try:
        return _MODE_BY_ID[mode_id]
    except KeyError as exc:
        raise AuthoritativeNoSkillFullGameError(
            f"mode_id={mode_id!r}不在authoritative no-skill V1 sealed registry"
        ) from exc


def _legal_action_from_replay_value(
    value: Mapping[str, object], label: str
) -> LegalAction:
    """Rebuild one already-issued legal action for controller conformance only."""

    try:
        raw_virtual = value.get("virtual_card")
        virtual = (
            None
            if raw_virtual is None
            else VirtualCardReference(
                card_key=str(_require_mapping(raw_virtual, f"{label}.virtual_card")["card_key"]),
                conversion_rule_id=str(
                    _require_mapping(raw_virtual, f"{label}.virtual_card")[
                        "conversion_rule_id"
                    ]
                ),
                material_card_instance_ids=tuple(
                    _require_mapping(raw_virtual, f"{label}.virtual_card").get(
                        "material_card_instance_ids", ()
                    )
                ),
            )
        )
        target_values = value.get("target_ids", ())
        if isinstance(target_values, (str, bytes)) or not isinstance(
            target_values, Sequence
        ):
            raise AuthoritativeNoSkillFullGameError(
                f"{label}.target_ids必须是JSON数组"
            )
        payload = _require_mapping(value.get("payload"), f"{label}.payload")
        return LegalAction(
            action_type=ActionType(str(value["action_type"])),
            actor_id=str(value["actor_id"]),
            card_instance_id=(
                None
                if value.get("card_instance_id") is None
                else str(value["card_instance_id"])
            ),
            virtual_card=virtual,
            target_ids=tuple(str(item) for item in target_values),
            skill_id=(
                None if value.get("skill_id") is None else str(value["skill_id"])
            ),
            payload=payload,
            action_id=(None if value.get("action_id") is None else str(value["action_id"])),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise AuthoritativeNoSkillFullGameError(
            f"{label}不是可验证的已签发合法动作"
        ) from exc


def _assert_v1_decisions_match_acceptance_policy(
    record: ProductionReexecutionReplay,
) -> None:
    """A V2 header may not merely *claim* its sealed controller identity."""

    controller = NoSkillAcceptanceControllerV1()
    for index, decision in enumerate(record.decisions):
        context = _require_mapping(decision.get("context"), f"decisions[{index}].context")
        try:
            public_context = PublicActionContextV1(
                mode_id=str(context["mode"]),
                phase=str(context["phase"]),
                actor_id=str(context["actor_id"]),
                turn_player_id=(
                    None
                    if context.get("turn_player_id") is None
                    else str(context["turn_player_id"])
                ),
                response_window_id=(
                    None
                    if context.get("response_window_id") is None
                    else str(context["response_window_id"])
                ),
                expected_revision=(
                    None
                    if context.get("expected_revision") is None
                    else int(context["expected_revision"])
                ),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise AuthoritativeNoSkillFullGameError(
                f"decisions[{index}].context不是可验证的公开行动上下文"
            ) from exc
        legal_values = decision.get("legal_actions")
        if isinstance(legal_values, (str, bytes)) or not isinstance(
            legal_values, Sequence
        ):
            raise AuthoritativeNoSkillFullGameError(
                f"decisions[{index}].legal_actions必须是JSON数组"
            )
        legal = tuple(
            _legal_action_from_replay_value(
                _require_mapping(value, f"decisions[{index}].legal_actions[{action_index}]"),
                f"decisions[{index}].legal_actions[{action_index}]",
            )
            for action_index, value in enumerate(legal_values)
        )
        selected = controller.choose_action_id(legal, public_context)
        if selected != decision.get("chosen_action_id"):
            raise AuthoritativeNoSkillFullGameError(
                f"decisions[{index}]不符合sealed acceptance controller选择策略"
            )


_V2_HEADER_FIELDS = frozenset(
    {
        "schema_version",
        "contract_id",
        "mode_id",
        "mode_contract_id",
        "seed",
        "controller_id",
        "controller_version",
        "implementation_identity",
        "ruleset_identity",
        "rules_profile_identity",
        "deck_identity",
        "production_replay_v1_sha256",
    }
)
_V2_ROOT_FIELDS = frozenset({"header", "production_replay_v1", "replay_v2_sha256"})

_CELL_REPORT_FIELDS = frozenset(
    {
        "cell_schema_version",
        "mode_id",
        "seed",
        "controller_id",
        "controller_version",
        "terminal_reason",
        "winner",
        "turn_count",
        "action_count",
        "event_count",
        "rng_count",
        "reached_card_keys",
        "reached_card_classes",
        "lifecycle_evidence",
        "proof_flags",
        "implementation_identity",
        "ruleset_identity",
        "rules_profile_identity",
        "deck_identity",
        "replay_v2_sha256",
        "replay_v2",
    }
)


@dataclass(frozen=True, slots=True)
class AuthoritativeNoSkillReplayV2:
    """V2 acceptance envelope around a compatible production replay V1 record."""

    header: Mapping[str, object]
    production_replay_v1: ProductionReexecutionReplay
    replay_v2_sha256: str = ""

    def __post_init__(self) -> None:
        header = _plain(_require_mapping(self.header, "replay-v2 header"))
        _require_exact_fields(header, _V2_HEADER_FIELDS, "replay-v2 header")
        if header["schema_version"] != AUTHORITATIVE_NO_SKILL_REPLAY_V2_SCHEMA:
            raise AuthoritativeNoSkillFullGameError("不支持的authoritative replay-v2 schema")
        if header["contract_id"] != AUTHORITATIVE_NO_SKILL_FULL_GAME_V1_CONTRACT_ID:
            raise AuthoritativeNoSkillFullGameError("replay-v2 contract_id不属于V1")
        spec = canonical_no_skill_mode_v1(str(header["mode_id"]))
        if header["mode_contract_id"] != spec.mode_contract_id:
            raise AuthoritativeNoSkillFullGameError(
                "replay-v2 mode_contract_id与sealed V1 mode不一致"
            )
        _require_seed(header["seed"])
        for key in ("controller_id", "controller_version"):
            if not isinstance(header[key], str) or not header[key].strip():
                raise AuthoritativeNoSkillFullGameError(
                    f"replay-v2 {key}必须是非空字符串"
                )
        if header["controller_id"] != NO_SKILL_ACCEPTANCE_CONTROLLER_V1_ID:
            raise AuthoritativeNoSkillFullGameError("replay-v2只接受V1 sealed acceptance controller")
        if header["controller_version"] != NO_SKILL_ACCEPTANCE_CONTROLLER_V1_VERSION:
            raise AuthoritativeNoSkillFullGameError("replay-v2 acceptance controller版本不匹配")
        for key in (
            "implementation_identity",
            "ruleset_identity",
            "rules_profile_identity",
            "deck_identity",
            "production_replay_v1_sha256",
        ):
            _require_sha256(header[key], f"replay-v2 {key}")
        if not isinstance(self.production_replay_v1, ProductionReexecutionReplay):
            raise TypeError("replay-v2必须封装ProductionReexecutionReplay v1")
        v1_header = self.production_replay_v1.header
        if v1_header["mode_id"] != header["mode_id"]:
            raise AuthoritativeNoSkillFullGameError("replay-v2 mode与内嵌v1记录不一致")
        if v1_header["seed"] != header["seed"]:
            raise AuthoritativeNoSkillFullGameError("replay-v2 seed与内嵌v1记录不一致")
        if v1_header["fixture_applied"] is not False:
            raise AuthoritativeNoSkillFullGameError("aggregate replay-v2拒绝fixture记录")
        if v1_header["formal_result"] is not True:
            raise AuthoritativeNoSkillFullGameError("aggregate replay-v2必须是formal_result")
        config = _require_mapping(v1_header["initial_configuration"], "v1 initial_configuration")
        if config.get("analysis_only") is not False:
            raise AuthoritativeNoSkillFullGameError("aggregate replay-v2拒绝analysis_only记录")
        if header["production_replay_v1_sha256"] != self.production_replay_v1.record_sha256:
            raise AuthoritativeNoSkillFullGameError("replay-v2未绑定内嵌v1记录哈希")
        if header["ruleset_identity"] != v1_header["ruleset_hash"]:
            raise AuthoritativeNoSkillFullGameError("replay-v2 ruleset_identity与内嵌v1记录不一致")
        _assert_v1_decisions_match_acceptance_policy(self.production_replay_v1)
        object.__setattr__(self, "header", _freeze(header))
        material = self._material_dict()
        digest = sha256_value(material)
        if self.replay_v2_sha256:
            supplied = _require_sha256(self.replay_v2_sha256, "replay_v2_sha256")
            if supplied != digest:
                raise AuthoritativeNoSkillFullGameError("replay-v2总哈希不匹配")
        object.__setattr__(self, "replay_v2_sha256", digest)

    def _material_dict(self) -> dict[str, object]:
        return {
            "header": _plain(self.header),
            "production_replay_v1": self.production_replay_v1.to_dict(),
        }

    def verify_integrity(self) -> bool:
        self.production_replay_v1.verify_integrity()
        if sha256_value(self._material_dict()) != self.replay_v2_sha256:
            raise AuthoritativeNoSkillFullGameError("replay-v2总哈希不匹配")
        return True

    def to_dict(self) -> dict[str, object]:
        value = self._material_dict()
        value["replay_v2_sha256"] = self.replay_v2_sha256
        return value

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "AuthoritativeNoSkillReplayV2":
        mapping = _require_mapping(value, "replay-v2记录")
        _require_exact_fields(mapping, _V2_ROOT_FIELDS, "replay-v2记录")
        return cls(
            header=_require_mapping(mapping["header"], "replay-v2 header"),
            production_replay_v1=ProductionReexecutionReplay.from_dict(
                _require_mapping(mapping["production_replay_v1"], "production_replay_v1")
            ),
            replay_v2_sha256=str(mapping["replay_v2_sha256"]),
        )

    @classmethod
    def from_v1_record(
        cls,
        record: ProductionReexecutionReplay,
        *,
        controller: NoSkillAcceptanceControllerV1,
    ) -> "AuthoritativeNoSkillReplayV2":
        if not isinstance(record, ProductionReexecutionReplay):
            raise TypeError("replay-v2必须从ProductionReexecutionReplay v1建立")
        if not isinstance(controller, NoSkillAcceptanceControllerV1):
            raise TypeError("aggregate replay-v2必须使用NoSkillAcceptanceControllerV1")
        mode_id = str(record.header["mode_id"])
        spec = canonical_no_skill_mode_v1(mode_id)
        return cls(
            header={
                "schema_version": AUTHORITATIVE_NO_SKILL_REPLAY_V2_SCHEMA,
                "contract_id": AUTHORITATIVE_NO_SKILL_FULL_GAME_V1_CONTRACT_ID,
                "mode_id": mode_id,
                "mode_contract_id": spec.mode_contract_id,
                "seed": record.header["seed"],
                "controller_id": controller.controller_id,
                "controller_version": controller.controller_version,
                "implementation_identity": implementation_identity(),
                "ruleset_identity": record.header["ruleset_hash"],
                "rules_profile_identity": spec.profile_identity(),
                "deck_identity": deck_identity(),
                "production_replay_v1_sha256": record.record_sha256,
            },
            production_replay_v1=record,
        )


def reexecute_authoritative_no_skill_replay_v2(
    replay: AuthoritativeNoSkillReplayV2,
) -> ProductionReplayVerificationResult:
    """Fail closed on V2 identities before V1 is allowed to rebuild a session."""

    if not isinstance(replay, AuthoritativeNoSkillReplayV2):
        raise TypeError("严格重执行必须接收AuthoritativeNoSkillReplayV2")
    replay.verify_integrity()
    header = replay.header
    spec = canonical_no_skill_mode_v1(str(header["mode_id"]))
    current_identities = (
        ("implementation_identity", str(header["implementation_identity"]), implementation_identity()),
        ("rules_profile_identity", str(header["rules_profile_identity"]), spec.profile_identity()),
        ("deck_identity", str(header["deck_identity"]), deck_identity()),
    )
    for label, expected, actual in current_identities:
        if expected != actual:
            # This must precede reexecute_production_replay(), the function
            # which performs the actual canonical-session reconstruction.
            raise AuthoritativeNoSkillReplayV2IdentityError(label, expected, actual)
    return reexecute_production_replay(replay.production_replay_v1)


def _reached_card_evidence(record: ProductionReexecutionReplay) -> tuple[tuple[str, ...], tuple[str, ...]]:
    deck_definition = _require_mapping(record.header["deck_definition"], "deck_definition")
    cards = deck_definition.get("cards")
    key_to_class: dict[str, str] = {}
    instance_to_key: dict[str, str] = {}
    if isinstance(cards, (list, tuple)):
        for card in cards:
            if not isinstance(card, Mapping):
                continue
            key = card.get("card_key")
            card_type = card.get("card_type")
            if isinstance(key, str) and key and isinstance(card_type, str) and card_type:
                key_to_class[key] = card_type
                instance_id = card.get("instance_id")
                if isinstance(instance_id, str) and instance_id:
                    instance_to_key[instance_id] = key
    # A card merely dealt to a hand is not "reached" in the acceptance sense.
    # Count only a chosen action's issued material/virtual card and public card
    # use/equipment events, never initial draw/card-moved evidence.
    keys: set[str] = set()
    for decision in record.decisions:
        chosen = decision.get("chosen_action")
        if not isinstance(chosen, Mapping):
            continue
        instance_id = chosen.get("card_instance_id")
        if isinstance(instance_id, str) and instance_id in instance_to_key:
            keys.add(instance_to_key[instance_id])
        virtual = chosen.get("virtual_card")
        if isinstance(virtual, Mapping):
            value = virtual.get("card_key")
            if isinstance(value, str) and value:
                keys.add(value)
        payload = chosen.get("payload")
        if isinstance(payload, Mapping):
            value = payload.get("card_key")
            if isinstance(value, str) and value:
                keys.add(value)
    for event in record.events:
        if event.get("event_type") not in {
            "card_used",
            "card_played",
            "equipment_equipped",
        }:
            continue
        value = event.get("card_key")
        if isinstance(value, str) and value:
            keys.add(value)
    return tuple(sorted(keys)), tuple(sorted({key_to_class[key] for key in keys if key in key_to_class}))


def _verification_matches_record(
    record: ProductionReexecutionReplay,
    verification: ProductionReplayVerificationResult,
) -> bool:
    outcome = record.outcome
    return (
        verification.verified is True
        and verification.winner_id == outcome["winner_id"]
        and verification.decision_count == outcome["decision_count"]
        and verification.random_consumption_count
        == outcome["random_consumption_count"]
        and verification.event_count == outcome["event_count"]
        and verification.final_execution_hash == outcome["final_execution_hash"]
        and verification.final_game_state_hash == outcome["final_game_state_hash"]
    )


def _finished_state_invariants_proven(
    record: ProductionReexecutionReplay,
    verification: ProductionReplayVerificationResult,
) -> bool:
    """Return explicit terminal evidence, not an aggregate-completeness claim.

    The production recorder and V1 reexecutor both force
    ``assert_finished_state_invariants()`` on the finishing step.  Persisting
    this derived report column alongside the strict result makes that evidence
    auditable without changing the formal replay-v1/v2 schemas.
    """

    outcome = record.outcome
    finish_reason = outcome.get("finish_reason")
    has_terminal_winner_or_reason = (
        outcome.get("winner_id") is not None
        or (isinstance(finish_reason, str) and bool(finish_reason))
    )
    return _verification_matches_record(record, verification) and has_terminal_winner_or_reason


def _cell_proof_flags(
    record: ProductionReexecutionReplay,
    verification: ProductionReplayVerificationResult,
) -> Mapping[str, bool]:
    config = _require_mapping(record.header["initial_configuration"], "initial_configuration")
    strict_replay_proven = _verification_matches_record(record, verification)
    finished_invariants_proven = _finished_state_invariants_proven(
        record, verification
    )
    production_reachable = bool(record.decisions)
    naturally_reached = (
        record.header["fixture_applied"] is False
        and record.header["formal_result"] is True
        and config.get("analysis_only") is False
    )
    return MappingProxyType(
        {
            "PRODUCTION_REACHABLE": production_reachable,
            "NATURALLY_REACHED_IN_ACCEPTANCE": naturally_reached,
            "FINISHED_STATE_INVARIANTS_PROVEN": finished_invariants_proven,
            "STRICT_REPLAY_PROVEN": strict_replay_proven,
            "FULL_GAME_COMPOSITION_PROVEN": (
                production_reachable
                and naturally_reached
                and finished_invariants_proven
                and strict_replay_proven
            ),
        }
    )


def _lifecycle_evidence(record: ProductionReexecutionReplay) -> Mapping[str, bool]:
    events = tuple(record.events)
    decisions = tuple(record.decisions)
    event_types = {
        str(event.get("event_type", ""))
        for event in events
        if isinstance(event, Mapping)
    }
    operations = {
        str(action.get("payload", {}).get("operation", ""))
        for decision in decisions
        for action in (decision.get("chosen_action"),)
        if isinstance(action, Mapping) and isinstance(action.get("payload"), Mapping)
    }
    contexts = {
        str(decision.get("context", {}).get("phase", ""))
        for decision in decisions
        if isinstance(decision.get("context"), Mapping)
    }
    keys, _classes = _reached_card_evidence(record)
    equipment_prefixes = ("sgs_weapon_", "sgs_armor_", "sgs_mount_")
    reshuffle = any(
        isinstance(event.get("payload"), Mapping)
        and event["payload"].get("reason") == "reshuffle"
        for event in events
    )
    terminal_reason = str(record.outcome.get("finish_reason", ""))
    return MappingProxyType(
        {
            "response": bool({"slash_response", "trick_response", "dying_rescue"} & contexts),
            "delayed": any(key in PRODUCTION_DELAYED_TRICK_KEYS for key in keys),
            "equipment": any(key.startswith(equipment_prefixes) for key in keys),
            "damage": "damage" in event_types,
            "dying": "dying" in event_types,
            "rescue": any(operation.startswith("rescue_") for operation in operations),
            "death": "death" in event_types,
            "victory": record.outcome.get("winner_id") is not None,
            "reshuffle": reshuffle,
            "deck_exhaustion": "deck_exhausted" in terminal_reason,
        }
    )


@dataclass(frozen=True, slots=True)
class AuthoritativeNoSkillAcceptanceCellV1:
    """One natural canonical V1 acceptance execution and its V2 strict proof."""

    replay_v2: AuthoritativeNoSkillReplayV2
    verification: ProductionReplayVerificationResult

    def __post_init__(self) -> None:
        if not isinstance(self.replay_v2, AuthoritativeNoSkillReplayV2):
            raise TypeError("acceptance cell必须包含AuthoritativeNoSkillReplayV2")
        if not isinstance(self.verification, ProductionReplayVerificationResult):
            raise TypeError("acceptance cell必须包含严格重执行结果")
        if self.verification.verified is not True:
            raise AuthoritativeNoSkillFullGameError("acceptance cell必须有strict replay证明")
        if not _verification_matches_record(
            self.replay_v2.production_replay_v1, self.verification
        ):
            raise AuthoritativeNoSkillFullGameError(
                "acceptance cell严格重执行结果与记录终局证据不一致"
            )

    @property
    def mode_id(self) -> str:
        return str(self.replay_v2.header["mode_id"])

    @property
    def seed(self) -> int:
        return int(self.replay_v2.header["seed"])

    def proof_flags(self) -> Mapping[str, bool]:
        return _cell_proof_flags(
            self.replay_v2.production_replay_v1, self.verification
        )

    def to_dict(self) -> dict[str, object]:
        record = self.replay_v2.production_replay_v1
        reached_keys, reached_classes = _reached_card_evidence(record)
        return {
            "cell_schema_version": AUTHORITATIVE_NO_SKILL_CELL_REPORT_SCHEMA_V1,
            "mode_id": self.mode_id,
            "seed": self.seed,
            "controller_id": self.replay_v2.header["controller_id"],
            "controller_version": self.replay_v2.header["controller_version"],
            "terminal_reason": record.outcome["finish_reason"],
            "winner": record.outcome["winner_id"],
            "turn_count": record.outcome["turn_count"],
            "action_count": record.outcome["step_count"],
            "event_count": record.outcome["event_count"],
            "rng_count": record.outcome["random_consumption_count"],
            "reached_card_keys": list(reached_keys),
            "reached_card_classes": list(reached_classes),
            "lifecycle_evidence": dict(_lifecycle_evidence(record)),
            "proof_flags": dict(self.proof_flags()),
            "implementation_identity": self.replay_v2.header["implementation_identity"],
            "ruleset_identity": self.replay_v2.header["ruleset_identity"],
            "rules_profile_identity": self.replay_v2.header["rules_profile_identity"],
            "deck_identity": self.replay_v2.header["deck_identity"],
            "replay_v2_sha256": self.replay_v2.replay_v2_sha256,
            "replay_v2": self.replay_v2.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class AuthoritativeNoSkillDerivedGatesV1:
    authoritative_no_skill_full_game_v1_ready: bool
    authoritative_no_skill_multiplayer_v1_proven: bool
    missing_cells: tuple[tuple[str, int], ...]


@dataclass(frozen=True, slots=True)
class AuthoritativeNoSkillAcceptanceMatrixV1:
    """Serializable V1 acceptance matrix whose gates are only derived."""

    cells: tuple[AuthoritativeNoSkillAcceptanceCellV1, ...]

    def __post_init__(self) -> None:
        cells = tuple(self.cells)
        if any(not isinstance(cell, AuthoritativeNoSkillAcceptanceCellV1) for cell in cells):
            raise TypeError("acceptance matrix只能包含V1 acceptance cells")
        pairs = tuple((cell.mode_id, cell.seed) for cell in cells)
        if len(pairs) != len(set(pairs)):
            raise AuthoritativeNoSkillFullGameError("acceptance matrix不能包含重复mode/seed")
        if any(mode_id not in _MODE_BY_ID for mode_id, _seed in pairs):
            raise AuthoritativeNoSkillFullGameError("acceptance matrix包含sealed registry外的mode")
        object.__setattr__(self, "cells", tuple(sorted(cells, key=lambda cell: (cell.mode_id, cell.seed))))

    @staticmethod
    def required_pairs() -> frozenset[tuple[str, int]]:
        return frozenset(
            (spec.mode_id, seed)
            for spec in AUTHORITATIVE_NO_SKILL_MODE_REGISTRY_V1
            for seed in AUTHORITATIVE_NO_SKILL_ACCEPTANCE_SEEDS_V1
        )

    def derived_gates(self) -> AuthoritativeNoSkillDerivedGatesV1:
        by_pair = {(cell.mode_id, cell.seed): cell for cell in self.cells}
        required = self.required_pairs()
        missing = tuple(sorted(required.difference(by_pair)))
        unexpected = tuple(sorted(set(by_pair).difference(required)))
        if missing or unexpected:
            return AuthoritativeNoSkillDerivedGatesV1(False, False, missing)
        # Do not trust a cached boolean in a serialized artifact.  Every V2
        # record is identity-checked and strictly reexecuted before an aggregate
        # gate can become true.
        for pair in sorted(required):
            cell = by_pair[pair]
            verification = reexecute_authoritative_no_skill_replay_v2(cell.replay_v2)
            if verification.verified is not True:
                return AuthoritativeNoSkillDerivedGatesV1(False, False, ())
            flags = _cell_proof_flags(
                cell.replay_v2.production_replay_v1, verification
            )
            if flags["FULL_GAME_COMPOSITION_PROVEN"] is not True:
                return AuthoritativeNoSkillDerivedGatesV1(False, False, ())
        multiplayer_pairs = frozenset(
            (spec.mode_id, seed)
            for spec in AUTHORITATIVE_NO_SKILL_MODE_REGISTRY_V1
            if spec.multiplayer
            for seed in AUTHORITATIVE_NO_SKILL_ACCEPTANCE_SEEDS_V1
        )
        multiplayer = multiplayer_pairs.issubset(by_pair)
        return AuthoritativeNoSkillDerivedGatesV1(True, multiplayer, ())

    def to_dict(self) -> dict[str, object]:
        gates = self.derived_gates()
        return {
            "contract_id": AUTHORITATIVE_NO_SKILL_FULL_GAME_V1_CONTRACT_ID,
            "mode_ids": [spec.mode_id for spec in AUTHORITATIVE_NO_SKILL_MODE_REGISTRY_V1],
            "required_seeds": list(AUTHORITATIVE_NO_SKILL_ACCEPTANCE_SEEDS_V1),
            "derived_gates": {
                "authoritative_no_skill_full_game_v1_ready": gates.authoritative_no_skill_full_game_v1_ready,
                "authoritative_no_skill_multiplayer_v1_proven": gates.authoritative_no_skill_multiplayer_v1_proven,
                "missing_cells": [list(pair) for pair in gates.missing_cells],
            },
            "cells": [
                cell.to_dict()
                for cell in self.cells
            ],
        }

    @classmethod
    def from_dict(
        cls, value: Mapping[str, object]
    ) -> "AuthoritativeNoSkillAcceptanceMatrixV1":
        """Load only current V1 artifacts and recompute every derived gate."""

        mapping = _require_mapping(value, "acceptance matrix")
        required = frozenset(
            {"contract_id", "mode_ids", "required_seeds", "derived_gates", "cells"}
        )
        _require_exact_fields(mapping, required, "acceptance matrix")
        if mapping["contract_id"] != AUTHORITATIVE_NO_SKILL_FULL_GAME_V1_CONTRACT_ID:
            raise AuthoritativeNoSkillFullGameError("acceptance matrix contract_id不属于V1")
        expected_mode_ids = [spec.mode_id for spec in AUTHORITATIVE_NO_SKILL_MODE_REGISTRY_V1]
        if mapping["mode_ids"] != expected_mode_ids:
            raise AuthoritativeNoSkillFullGameError("acceptance matrix mode registry与sealed V1不一致")
        if mapping["required_seeds"] != list(AUTHORITATIVE_NO_SKILL_ACCEPTANCE_SEEDS_V1):
            raise AuthoritativeNoSkillFullGameError("acceptance matrix required_seeds与V1冻结集合不一致")
        raw_cells = mapping["cells"]
        if isinstance(raw_cells, (str, bytes)) or not isinstance(raw_cells, Sequence):
            raise AuthoritativeNoSkillFullGameError("acceptance matrix cells必须是JSON数组")
        cells: list[AuthoritativeNoSkillAcceptanceCellV1] = []
        for index, raw_cell in enumerate(raw_cells):
            cell_value = _require_mapping(raw_cell, f"cells[{index}]")
            _require_exact_fields(cell_value, _CELL_REPORT_FIELDS, f"cells[{index}]")
            raw_replay = _require_mapping(cell_value.get("replay_v2"), f"cells[{index}].replay_v2")
            replay = AuthoritativeNoSkillReplayV2.from_dict(raw_replay)
            verification = reexecute_authoritative_no_skill_replay_v2(replay)
            cell = AuthoritativeNoSkillAcceptanceCellV1(replay, verification)
            # The duplicated report columns are an audit convenience only;
            # never accept values that disagree with the replay-derived cell.
            expected = cell.to_dict()
            for key, expected_value in expected.items():
                if cell_value.get(key) != expected_value:
                    raise AuthoritativeNoSkillFullGameError(
                        f"cells[{index}].{key}与replay-v2派生值不一致"
                    )
            cells.append(cell)
        matrix = cls(tuple(cells))
        actual_gates = matrix.derived_gates()
        expected_gates = {
            "authoritative_no_skill_full_game_v1_ready": actual_gates.authoritative_no_skill_full_game_v1_ready,
            "authoritative_no_skill_multiplayer_v1_proven": actual_gates.authoritative_no_skill_multiplayer_v1_proven,
            "missing_cells": [list(pair) for pair in actual_gates.missing_cells],
        }
        if mapping["derived_gates"] != expected_gates:
            raise AuthoritativeNoSkillFullGameError("acceptance matrix derived_gates不可由当前证据重算")
        return matrix


class AuthoritativeNoSkillFullGameOrchestrator:
    """Sealed aggregate runner for the six formal no-skill V1 modes only."""

    contract_id = AUTHORITATIVE_NO_SKILL_FULL_GAME_V1_CONTRACT_ID

    def __init__(self) -> None:
        self._controller = NoSkillAcceptanceControllerV1()

    @property
    def controller(self) -> NoSkillAcceptanceControllerV1:
        return self._controller

    @property
    def mode_registry(self) -> tuple[CanonicalNoSkillModeV1, ...]:
        return AUTHORITATIVE_NO_SKILL_MODE_REGISTRY_V1

    def run_cell(
        self,
        mode_id: str,
        seed: int,
        *,
        fixture: object | None = None,
        premutated_session: object | None = None,
    ) -> AuthoritativeNoSkillAcceptanceCellV1:
        """Run exactly canonical factory -> legal actions -> action IDs -> step.

        The two forbidden parameters exist solely as explicit fail-closed
        boundaries.  The method has no caller factory, deck, analysis-only, or
        mutable session ingress.
        """

        if fixture is not None:
            raise AuthoritativeNoSkillFullGameError(
                "aggregate orchestration拒绝fixture；必须canonical natural start"
            )
        if premutated_session is not None:
            raise AuthoritativeNoSkillFullGameError(
                "aggregate orchestration拒绝预突变session；必须trusted factory"
            )
        spec = canonical_no_skill_mode_v1(mode_id)
        game = spec.create_session(seed)
        record = record_reference_production_batch(
            seed,
            controller=self._controller,
            max_steps=spec.max_steps,
            _game=game,
        )
        replay_v2 = AuthoritativeNoSkillReplayV2.from_v1_record(
            record, controller=self._controller
        )
        verification = reexecute_authoritative_no_skill_replay_v2(replay_v2)
        return AuthoritativeNoSkillAcceptanceCellV1(replay_v2, verification)

    def run_smoke_matrix(
        self, *, seed: int = 0
    ) -> AuthoritativeNoSkillAcceptanceMatrixV1:
        """One seed per sealed mode for wiring smoke only, never final proof."""

        seed = _require_seed(seed)
        return AuthoritativeNoSkillAcceptanceMatrixV1(
            tuple(self.run_cell(spec.mode_id, seed) for spec in self.mode_registry)
        )


__all__ = [
    "AUTHORITATIVE_NO_SKILL_ACCEPTANCE_SEEDS_V1",
    "AUTHORITATIVE_NO_SKILL_FULL_GAME_V1_CONTRACT_ID",
    "AUTHORITATIVE_NO_SKILL_MODE_REGISTRY_V1",
    "AUTHORITATIVE_NO_SKILL_REPLAY_V2_SCHEMA",
    "AUTHORITATIVE_NO_SKILL_CELL_REPORT_SCHEMA_V1",
    "AuthoritativeNoSkillAcceptanceCellV1",
    "AuthoritativeNoSkillAcceptanceMatrixV1",
    "AuthoritativeNoSkillDerivedGatesV1",
    "AuthoritativeNoSkillFullGameError",
    "AuthoritativeNoSkillFullGameOrchestrator",
    "AuthoritativeNoSkillReplayV2",
    "AuthoritativeNoSkillReplayV2IdentityError",
    "CanonicalNoSkillModeV1",
    "NO_SKILL_ACCEPTANCE_CONTROLLER_V1_ID",
    "NO_SKILL_ACCEPTANCE_CONTROLLER_V1_VERSION",
    "NoSkillAcceptanceControllerV1",
    "PublicActionContextV1",
    "canonical_no_skill_mode_v1",
    "reexecute_authoritative_no_skill_replay_v2",
]
