# -*- coding: utf-8 -*-
"""C8-A deterministic virtual-time contract and pure timeout resolver.

Independent from production gameplay: no wall clock, RNG, private state, or
production ``step`` call is permitted here.
"""

from __future__ import annotations

from dataclasses import InitVar, dataclass
from enum import Enum
import hashlib
import json
import re
from types import MappingProxyType
from typing import Any, Mapping, Sequence


class C8VirtualTimeContractError(ValueError):
    """C8-A authority or schema input failed closed."""


C8_A_MILESTONE = "C8-A_VIRTUAL_TIME_CONTRACT_FREEZE_V1"
C8_VIRTUAL_TIME_CONTRACT_ID = "c8-timed-8p-deterministic-virtual-time-v1"
C8_VIRTUAL_TIME_CONTRACT_VERSION = 1
C8_SELECTED_MODE_ID = "C8_TIMED_8P_DETERMINISTIC_VIRTUAL_TIME_V1"
C8_BASE_MODE_ID = "CANONICAL_C6_STANDARD_NO_SKILL_8P"

CLOCK_DOMAIN_SCHEMA = "sgs-c8-clock-domain-v1"
DURATION_PROFILE_SCHEMA = "sgs-c8-duration-profile-v1"
WINDOW_SCHEMA = "sgs-c8-timed-decision-window-v1"
WINDOW_STACK_SCHEMA = "sgs-c8-timed-window-stack-v1"
VIRTUAL_TIME_STATE_SCHEMA = "sgs-c8-virtual-time-state-v1"
ADVANCE_INPUT_SCHEMA = "sgs-c8-virtual-time-advance-input-v1"
CONTROL_INPUT_SCHEMA = "sgs-c8-virtual-time-control-input-v1"
DERIVED_DEADLINE_SCHEMA = "sgs-c8-derived-deadline-reached-v1"
PUBLIC_ACTION_SCHEMA = "sgs-c8-public-legal-action-candidate-v1"
PUBLIC_LEGAL_SET_SCHEMA = "sgs-c8-public-legal-set-projection-v1"
FALLBACK_POLICY_SCHEMA = "sgs-c8-timeout-fallback-policy-v1"
FALLBACK_REGISTRY_SCHEMA = "sgs-c8-timeout-fallback-registry-v1"
TIMEOUT_RESOLUTION_SCHEMA = "sgs-c8-timeout-resolution-v1"
SAME_TICK_CHAIN_CONTRACT_SCHEMA = "sgs-c8-same-tick-chain-contract-v1"
SAME_TICK_CHAIN_STEP_SCHEMA = "sgs-c8-same-tick-chain-step-v1"
SAME_TICK_CHAIN_SCHEMA = "sgs-c8-same-tick-chain-v1"
TRANSACTION_SNAPSHOT_SCHEMA = "sgs-c8-virtual-time-transaction-snapshot-v1"
PUBLIC_PROJECTION_SCHEMA = "sgs-c8-timed-public-projection-v1"
PRIVATE_PROJECTION_SCHEMA = "sgs-c8-timed-authoritative-private-projection-v1"

CLOCK_DOMAIN_ID = "c8-authoritative-virtual-clock-domain-v1"
ENGINEERING_TEST_PROFILE_ID = "c8-engineering-test-duration-profile-v1"
ENGINEERING_PROFILE_DESIGNATION = "NON_OFFICIAL_ENGINEERING_PROFILE"
FALLBACK_REGISTRY_ID = "c8-timeout-fallback-registry-v1"
PUBLIC_ORDERING_CONTRACT_ID = "caller-verified-public-ordinal-v1"
SAME_TICK_CHAIN_CONTRACT_ID = "c8-bounded-same-tick-fallback-chain-v1"
PARENT_RESUME_RULE_ID = "REBASE_DEADLINE_ON_RESUME_PRESERVE_REMAINING_V1"
MULTI_STEP_TIMEOUT_RULE_ID = (
    "NO_DEADLINE_REFRESH_BOUNDED_SAME_TICK_FRESH_LEGAL_ACTION_V1"
)
TIMEOUT_UNRESOLVED_RULE_ID = (
    "FAIL_CLOSED_FUTURE_OUTER_TRANSACTION_ROLLBACK_REQUIRED_V1"
)

TICK_MIN = 0
TICK_MAX = (1 << 63) - 1
SAME_TICK_FALLBACK_CHAIN_MAX_STEPS = 8
BRIDGE_V1_FROZEN_BASELINE_IDENTITY = (
    "ba3838692ad9e1954f8759ea9f51260796fe011e7cc881747f74018e0c42c2e6"
)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_WINDOW_ID_RE = re.compile(r"^c8w-[0-9a-f]{32}$")
_CHAIN_ID_RE = re.compile(r"^c8chain-[0-9a-f]{32}$")
_DERIVATION_GUARD = object()
_PUBLIC_FORBIDDEN_FIELDS = frozenset(
    {
        "card_id", "card_identity", "credential", "credentials", "hand",
        "hand_cards", "private_card", "private_choice", "private_payload",
        "session_secret", "signing_material", "signing_secret",
    }
)


def _exact_dict(value: object, label: str) -> dict[str, Any]:
    if type(value) is not dict:
        raise C8VirtualTimeContractError(f"{label}必须是精确JSON object")
    if any(type(key) is not str for key in value):
        raise C8VirtualTimeContractError(f"{label}字段名必须是精确字符串")
    return value


def _exact_fields(
    value: Mapping[str, object], expected: frozenset[str], label: str
) -> None:
    actual = frozenset(value)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise C8VirtualTimeContractError(
            f"{label}字段必须精确匹配schema；missing={missing}, extra={extra}"
        )


def _exact_list(value: object, label: str) -> list[object]:
    if type(value) is not list:
        raise C8VirtualTimeContractError(f"{label}必须是精确JSON array")
    return value


def _exact_text(value: object, label: str) -> str:
    if type(value) is not str or not value or value.strip() != value:
        raise C8VirtualTimeContractError(f"{label}必须是无首尾空白的精确非空字符串")
    return value


def _exact_optional_text(value: object, label: str) -> str | None:
    if value is None:
        return None
    return _exact_text(value, label)


def _exact_int(
    value: object, label: str, *, minimum: int = TICK_MIN, maximum: int = TICK_MAX
) -> int:
    if type(value) is not int or value < minimum or value > maximum:
        raise C8VirtualTimeContractError(
            f"{label}必须是[{minimum}, {maximum}]内的精确整数"
        )
    return value


def _exact_bool(value: object, label: str) -> bool:
    if type(value) is not bool:
        raise C8VirtualTimeContractError(f"{label}必须是精确布尔值")
    return value


def _exact_sha256(value: object, label: str) -> str:
    text = _exact_text(value, label)
    if _SHA256_RE.fullmatch(text) is None:
        raise C8VirtualTimeContractError(f"{label}必须是64位小写SHA-256")
    return text


def _exact_enum(value: object, enum_type: type[Enum], label: str) -> Enum:
    text = _exact_text(value, label)
    try:
        return enum_type(text)
    except ValueError as exc:
        raise C8VirtualTimeContractError(f"{label}不是受支持的枚举值：{text!r}") from exc


def _canonical_json(value: object) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _strict_json_equal(left: object, right: object) -> bool:
    if type(left) is not type(right):
        return False
    if type(left) is dict:
        assert type(right) is dict
        return left.keys() == right.keys() and all(
            _strict_json_equal(left[key], right[key]) for key in left
        )
    if type(left) is list:
        assert type(right) is list
        return len(left) == len(right) and all(
            _strict_json_equal(a, b) for a, b in zip(left, right)
        )
    return left == right


def _assert_identity(actual: object, material: object, label: str) -> str:
    value = _exact_sha256(actual, label)
    expected = _canonical_sha256(material)
    if value != expected:
        raise C8VirtualTimeContractError(
            f"{label}与canonical material不一致；expected={expected}, actual={value}"
        )
    return value


def _safe_add_ticks(left: int, right: int, label: str) -> int:
    value = left + right
    if value > TICK_MAX:
        raise C8VirtualTimeContractError(f"{label}超出signed-int64 tick范围")
    return value


def _reject_public_leakage(value: object, label: str = "public projection") -> None:
    if type(value) is dict:
        for key, item in value.items():
            if type(key) is not str:
                raise C8VirtualTimeContractError(f"{label}字段名必须是精确字符串")
            if key.lower() in _PUBLIC_FORBIDDEN_FIELDS:
                raise C8VirtualTimeContractError(
                    f"{label}禁止private/card/credential字段：{key}"
                )
            _reject_public_leakage(item, f"{label}.{key}")
    elif type(value) is list:
        for index, item in enumerate(value):
            _reject_public_leakage(item, f"{label}[{index}]")


class ClockUnitV1(str, Enum):
    VIRTUAL_MILLISECOND = "VIRTUAL_MILLISECOND"


class DeadlineTieRuleV1(str, Enum):
    DEADLINE_WINS_AT_EQUAL_TICK = "DEADLINE_WINS_AT_EQUAL_TICK"


class TickConsumptionRuleV1(str, Enum):
    ACTIVE_TOP_WINDOW_ONLY = "ACTIVE_TOP_WINDOW_ONLY"


class WallClockSemanticsV1(str, Enum):
    FORBIDDEN = "FORBIDDEN"


class TimedWindowKindV1(str, Enum):
    PLAY = "PLAY"
    OPTIONAL_RESPONSE = "OPTIONAL_RESPONSE"
    RESCUE_RESPONSE = "RESCUE_RESPONSE"
    OPTIONAL_SKILL_DECISION = "OPTIONAL_SKILL_DECISION"
    MODE_DECISION = "MODE_DECISION"
    MANDATORY_SINGLE_ACTION = "MANDATORY_SINGLE_ACTION"
    MANDATORY_PUBLIC_CHOICE = "MANDATORY_PUBLIC_CHOICE"
    MULTI_STEP_OBLIGATION = "MULTI_STEP_OBLIGATION"


class TimedWindowStatusV1(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED_BY_CHILD = "SUSPENDED_BY_CHILD"
    FROZEN_BY_CLOCK_PAUSE = "FROZEN_BY_CLOCK_PAUSE"
    CLOSED_BY_ACTION = "CLOSED_BY_ACTION"
    CLOSED_BY_TIMEOUT = "CLOSED_BY_TIMEOUT"
    ROLLED_BACK = "ROLLED_BACK"


class VirtualTimeAdvanceInputKindV1(str, Enum):
    TIME_ADVANCE = "TIME_ADVANCE"


class VirtualTimeControlInputKindV1(str, Enum):
    PAUSE = "PAUSE"
    RESUME = "RESUME"


class DeadlinePrecedenceV1(str, Enum):
    ACTION_ELIGIBLE_BEFORE_DEADLINE = "ACTION_ELIGIBLE_BEFORE_DEADLINE"
    TIMEOUT_PRIORITY_AT_OR_AFTER_DEADLINE = "TIMEOUT_PRIORITY_AT_OR_AFTER_DEADLINE"


class PublicActionFamilyV1(str, Enum):
    END_PLAY_PHASE = "end_play_phase"
    PASS_RESPONSE = "pass_response"
    PASS_RESCUE = "pass_rescue"
    DECLINE_OPTIONAL = "decline_optional"
    PASS_MODE_DECISION = "pass_mode_decision"
    MANDATORY_ACTION = "mandatory_action"
    PUBLIC_CHOICE = "public_choice"


class TimeoutFallbackSelectorV1(str, Enum):
    EXPLICIT_ACTION_FAMILY = "EXPLICIT_ACTION_FAMILY"
    UNIQUE_LEGAL_ACTION = "UNIQUE_LEGAL_ACTION"
    CANONICAL_PUBLIC_ORDINAL = "CANONICAL_PUBLIC_ORDINAL"
    MULTI_STEP_SAFE_PUBLIC_FALLBACK = "MULTI_STEP_SAFE_PUBLIC_FALLBACK"


class TimeoutResolutionKindV1(str, Enum):
    TIMEOUT_NOT_DUE = "TIMEOUT_NOT_DUE"
    RESOLVE_TO_PUBLIC_ACTION_ORDINAL = "RESOLVE_TO_PUBLIC_ACTION_ORDINAL"
    TIMEOUT_UNRESOLVED = "TIMEOUT_UNRESOLVED"


class TimeoutResolutionReasonV1(str, Enum):
    BEFORE_DEADLINE = "BEFORE_DEADLINE"
    EXPLICIT_FALLBACK = "EXPLICIT_FALLBACK"
    UNIQUE_MANDATORY_ACTION = "UNIQUE_MANDATORY_ACTION"
    CANONICAL_PUBLIC_ORDINAL = "CANONICAL_PUBLIC_ORDINAL"
    NO_SAFE_DETERMINISTIC_FALLBACK = "NO_SAFE_DETERMINISTIC_FALLBACK"


class SameTickFallbackChainStatusV1(str, Enum):
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"


class SameTickFallbackTerminationV1(str, Enum):
    OBLIGATION_CLOSED = "OBLIGATION_CLOSED"
    WINDOW_TRANSITIONED = "WINDOW_TRANSITIONED"
    TIMEOUT_UNRESOLVED = "TIMEOUT_UNRESOLVED"


@dataclass(frozen=True, slots=True, kw_only=True)
class ClockDomainV1:
    schema: str
    contract_version: int
    domain_id: str
    unit: ClockUnitV1
    tick_min: int
    tick_max: int
    tie_rule: DeadlineTieRuleV1
    consumption_rule: TickConsumptionRuleV1
    wall_clock_semantics: WallClockSemanticsV1
    clock_domain_identity: str

    def __post_init__(self) -> None:
        if self.schema != CLOCK_DOMAIN_SCHEMA:
            raise C8VirtualTimeContractError("ClockDomainV1 schema不匹配")
        if type(self.contract_version) is not int or self.contract_version != 1:
            raise C8VirtualTimeContractError("ClockDomainV1 contract_version必须精确为1")
        if self.domain_id != CLOCK_DOMAIN_ID:
            raise C8VirtualTimeContractError("ClockDomainV1 domain_id不匹配")
        if type(self.unit) is not ClockUnitV1:
            raise C8VirtualTimeContractError("ClockDomainV1 unit类型不正确")
        if type(self.tie_rule) is not DeadlineTieRuleV1:
            raise C8VirtualTimeContractError("ClockDomainV1 tie_rule类型不正确")
        if type(self.consumption_rule) is not TickConsumptionRuleV1:
            raise C8VirtualTimeContractError("ClockDomainV1 consumption_rule类型不正确")
        if type(self.wall_clock_semantics) is not WallClockSemanticsV1:
            raise C8VirtualTimeContractError("ClockDomainV1 wall_clock_semantics类型不正确")
        if self.unit is not ClockUnitV1.VIRTUAL_MILLISECOND:
            raise C8VirtualTimeContractError("ClockDomainV1只允许virtual millisecond")
        if self.tick_min != TICK_MIN or self.tick_max != TICK_MAX:
            raise C8VirtualTimeContractError("ClockDomainV1 tick range不匹配")
        if self.tie_rule is not DeadlineTieRuleV1.DEADLINE_WINS_AT_EQUAL_TICK:
            raise C8VirtualTimeContractError("ClockDomainV1 exact-boundary tie rule不匹配")
        if self.consumption_rule is not TickConsumptionRuleV1.ACTIVE_TOP_WINDOW_ONLY:
            raise C8VirtualTimeContractError("ClockDomainV1 tick consumption rule不匹配")
        if self.wall_clock_semantics is not WallClockSemanticsV1.FORBIDDEN:
            raise C8VirtualTimeContractError("ClockDomainV1禁止wall clock authority")
        _exact_int(self.tick_min, "ClockDomainV1.tick_min")
        _exact_int(self.tick_max, "ClockDomainV1.tick_max")
        _assert_identity(
            self.clock_domain_identity, self._identity_material(), "clock_domain_identity"
        )

    def _identity_material(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "contract_version": self.contract_version,
            "domain_id": self.domain_id,
            "unit": self.unit.value,
            "tick_min": self.tick_min,
            "tick_max": self.tick_max,
            "tie_rule": self.tie_rule.value,
            "consumption_rule": self.consumption_rule.value,
            "wall_clock_semantics": self.wall_clock_semantics.value,
        }

    def to_dict(self) -> dict[str, object]:
        return {
            **self._identity_material(),
            "clock_domain_identity": self.clock_domain_identity,
        }

    @classmethod
    def canonical(cls) -> "ClockDomainV1":
        material = {
            "schema": CLOCK_DOMAIN_SCHEMA,
            "contract_version": 1,
            "domain_id": CLOCK_DOMAIN_ID,
            "unit": ClockUnitV1.VIRTUAL_MILLISECOND.value,
            "tick_min": TICK_MIN,
            "tick_max": TICK_MAX,
            "tie_rule": DeadlineTieRuleV1.DEADLINE_WINS_AT_EQUAL_TICK.value,
            "consumption_rule": TickConsumptionRuleV1.ACTIVE_TOP_WINDOW_ONLY.value,
            "wall_clock_semantics": WallClockSemanticsV1.FORBIDDEN.value,
        }
        return cls(
            schema=CLOCK_DOMAIN_SCHEMA,
            contract_version=1,
            domain_id=CLOCK_DOMAIN_ID,
            unit=ClockUnitV1.VIRTUAL_MILLISECOND,
            tick_min=TICK_MIN,
            tick_max=TICK_MAX,
            tie_rule=DeadlineTieRuleV1.DEADLINE_WINS_AT_EQUAL_TICK,
            consumption_rule=TickConsumptionRuleV1.ACTIVE_TOP_WINDOW_ONLY,
            wall_clock_semantics=WallClockSemanticsV1.FORBIDDEN,
            clock_domain_identity=_canonical_sha256(material),
        )

    @classmethod
    def from_dict(cls, value: object) -> "ClockDomainV1":
        data = _exact_dict(value, "ClockDomainV1")
        _exact_fields(data, frozenset(cls.canonical().to_dict()), "ClockDomainV1")
        return cls(
            schema=_exact_text(data["schema"], "ClockDomainV1.schema"),
            contract_version=_exact_int(
                data["contract_version"], "ClockDomainV1.contract_version"
            ),
            domain_id=_exact_text(data["domain_id"], "ClockDomainV1.domain_id"),
            unit=_exact_enum(data["unit"], ClockUnitV1, "ClockDomainV1.unit"),
            tick_min=_exact_int(data["tick_min"], "ClockDomainV1.tick_min"),
            tick_max=_exact_int(data["tick_max"], "ClockDomainV1.tick_max"),
            tie_rule=_exact_enum(
                data["tie_rule"], DeadlineTieRuleV1, "ClockDomainV1.tie_rule"
            ),
            consumption_rule=_exact_enum(
                data["consumption_rule"],
                TickConsumptionRuleV1,
                "ClockDomainV1.consumption_rule",
            ),
            wall_clock_semantics=_exact_enum(
                data["wall_clock_semantics"],
                WallClockSemanticsV1,
                "ClockDomainV1.wall_clock_semantics",
            ),
            clock_domain_identity=_exact_sha256(
                data["clock_domain_identity"], "ClockDomainV1.clock_domain_identity"
            ),
        )


CLOCK_DOMAIN_V1 = ClockDomainV1.canonical()


@dataclass(frozen=True, slots=True, kw_only=True)
class WindowDurationV1:
    window_kind: TimedWindowKindV1
    duration_ticks: int

    def __post_init__(self) -> None:
        if type(self.window_kind) is not TimedWindowKindV1:
            raise C8VirtualTimeContractError("WindowDurationV1.window_kind类型不正确")
        _exact_int(self.duration_ticks, "WindowDurationV1.duration_ticks", minimum=1)

    def to_dict(self) -> dict[str, object]:
        return {
            "window_kind": self.window_kind.value,
            "duration_ticks": self.duration_ticks,
        }

    @classmethod
    def from_dict(cls, value: object) -> "WindowDurationV1":
        data = _exact_dict(value, "WindowDurationV1")
        _exact_fields(
            data, frozenset({"window_kind", "duration_ticks"}), "WindowDurationV1"
        )
        return cls(
            window_kind=_exact_enum(
                data["window_kind"], TimedWindowKindV1, "WindowDurationV1.window_kind"
            ),
            duration_ticks=_exact_int(
                data["duration_ticks"], "WindowDurationV1.duration_ticks", minimum=1
            ),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class DurationProfileV1:
    schema: str
    contract_version: int
    profile_id: str
    designation: str
    official_client_parity: bool
    unit: ClockUnitV1
    durations: tuple[WindowDurationV1, ...]
    profile_identity: str

    def __post_init__(self) -> None:
        if self.schema != DURATION_PROFILE_SCHEMA:
            raise C8VirtualTimeContractError("DurationProfileV1 schema不匹配")
        if type(self.contract_version) is not int or self.contract_version != 1:
            raise C8VirtualTimeContractError("DurationProfileV1 contract_version必须精确为1")
        _exact_text(self.profile_id, "DurationProfileV1.profile_id")
        if self.designation != ENGINEERING_PROFILE_DESIGNATION:
            raise C8VirtualTimeContractError(
                "DurationProfileV1必须标记non-official engineering profile"
            )
        if type(self.official_client_parity) is not bool or self.official_client_parity:
            raise C8VirtualTimeContractError(
                "DurationProfileV1不得声称official client parity"
            )
        if type(self.unit) is not ClockUnitV1 or self.unit is not CLOCK_DOMAIN_V1.unit:
            raise C8VirtualTimeContractError("DurationProfileV1 unit与clock domain不一致")
        if type(self.durations) is not tuple or any(
            type(item) is not WindowDurationV1 for item in self.durations
        ):
            raise C8VirtualTimeContractError("DurationProfileV1.durations必须是严格tuple")
        expected = tuple(TimedWindowKindV1)
        actual = tuple(item.window_kind for item in self.durations)
        if actual != expected:
            raise C8VirtualTimeContractError(
                "DurationProfileV1必须按canonical顺序完整覆盖window kinds"
            )
        _assert_identity(self.profile_identity, self._identity_material(), "profile_identity")

    def _identity_material(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "contract_version": self.contract_version,
            "profile_id": self.profile_id,
            "designation": self.designation,
            "official_client_parity": self.official_client_parity,
            "unit": self.unit.value,
            "durations": [item.to_dict() for item in self.durations],
        }

    def duration_for(self, window_kind: TimedWindowKindV1) -> int:
        if type(window_kind) is not TimedWindowKindV1:
            raise C8VirtualTimeContractError("duration_for window_kind类型不正确")
        for item in self.durations:
            if item.window_kind is window_kind:
                return item.duration_ticks
        raise C8VirtualTimeContractError("duration profile未覆盖window kind")

    def to_dict(self) -> dict[str, object]:
        return {**self._identity_material(), "profile_identity": self.profile_identity}

    @classmethod
    def build(
        cls, *, profile_id: str, durations: Sequence[WindowDurationV1]
    ) -> "DurationProfileV1":
        _exact_text(profile_id, "DurationProfileV1.profile_id")
        if type(durations) not in (tuple, list):
            raise C8VirtualTimeContractError("durations必须是明确序列")
        items = tuple(durations)
        material = {
            "schema": DURATION_PROFILE_SCHEMA,
            "contract_version": 1,
            "profile_id": profile_id,
            "designation": ENGINEERING_PROFILE_DESIGNATION,
            "official_client_parity": False,
            "unit": ClockUnitV1.VIRTUAL_MILLISECOND.value,
            "durations": [item.to_dict() for item in items],
        }
        return cls(
            schema=DURATION_PROFILE_SCHEMA,
            contract_version=1,
            profile_id=profile_id,
            designation=ENGINEERING_PROFILE_DESIGNATION,
            official_client_parity=False,
            unit=ClockUnitV1.VIRTUAL_MILLISECOND,
            durations=items,
            profile_identity=_canonical_sha256(material),
        )

    @classmethod
    def from_dict(cls, value: object) -> "DurationProfileV1":
        data = _exact_dict(value, "DurationProfileV1")
        fields = frozenset(
            {
                "schema", "contract_version", "profile_id", "designation",
                "official_client_parity", "unit", "durations", "profile_identity",
            }
        )
        _exact_fields(data, fields, "DurationProfileV1")
        return cls(
            schema=_exact_text(data["schema"], "DurationProfileV1.schema"),
            contract_version=_exact_int(
                data["contract_version"], "DurationProfileV1.contract_version"
            ),
            profile_id=_exact_text(data["profile_id"], "DurationProfileV1.profile_id"),
            designation=_exact_text(data["designation"], "DurationProfileV1.designation"),
            official_client_parity=_exact_bool(
                data["official_client_parity"], "DurationProfileV1.official_client_parity"
            ),
            unit=_exact_enum(data["unit"], ClockUnitV1, "DurationProfileV1.unit"),
            durations=tuple(
                WindowDurationV1.from_dict(item)
                for item in _exact_list(data["durations"], "DurationProfileV1.durations")
            ),
            profile_identity=_exact_sha256(
                data["profile_identity"], "DurationProfileV1.profile_identity"
            ),
        )


ENGINEERING_TEST_PROFILE_V1 = DurationProfileV1.build(
    profile_id=ENGINEERING_TEST_PROFILE_ID,
    durations=tuple(
        WindowDurationV1(window_kind=kind, duration_ticks=100)
        for kind in TimedWindowKindV1
    ),
)


@dataclass(frozen=True, slots=True, kw_only=True)
class TimeoutFallbackPolicyV1:
    schema: str
    contract_version: int
    policy_id: str
    window_kind: TimedWindowKindV1
    selector: TimeoutFallbackSelectorV1
    allowed_action_families: tuple[PublicActionFamilyV1, ...]
    ordering_contract_id: str | None
    same_tick_chain_required: bool
    policy_identity: str

    def __post_init__(self) -> None:
        if self.schema != FALLBACK_POLICY_SCHEMA:
            raise C8VirtualTimeContractError("TimeoutFallbackPolicyV1 schema不匹配")
        if type(self.contract_version) is not int or self.contract_version != 1:
            raise C8VirtualTimeContractError("fallback policy contract_version必须精确为1")
        _exact_text(self.policy_id, "fallback policy_id")
        if type(self.window_kind) is not TimedWindowKindV1:
            raise C8VirtualTimeContractError("fallback policy window_kind类型不正确")
        if type(self.selector) is not TimeoutFallbackSelectorV1:
            raise C8VirtualTimeContractError("fallback policy selector类型不正确")
        if type(self.allowed_action_families) is not tuple or any(
            type(item) is not PublicActionFamilyV1 for item in self.allowed_action_families
        ):
            raise C8VirtualTimeContractError("allowed_action_families必须是strict tuple")
        _exact_optional_text(self.ordering_contract_id, "ordering_contract_id")
        _exact_bool(self.same_tick_chain_required, "same_tick_chain_required")
        if self.selector is TimeoutFallbackSelectorV1.EXPLICIT_ACTION_FAMILY:
            if len(self.allowed_action_families) != 1 or self.ordering_contract_id is not None:
                raise C8VirtualTimeContractError("explicit fallback必须冻结唯一action family")
        elif self.selector is TimeoutFallbackSelectorV1.UNIQUE_LEGAL_ACTION:
            if self.allowed_action_families or self.ordering_contract_id is not None:
                raise C8VirtualTimeContractError("unique fallback不得附带family/order policy")
        elif self.selector is TimeoutFallbackSelectorV1.CANONICAL_PUBLIC_ORDINAL:
            if self.allowed_action_families:
                raise C8VirtualTimeContractError("ordinal fallback不得附带action family")
            if self.ordering_contract_id != PUBLIC_ORDERING_CONTRACT_ID:
                raise C8VirtualTimeContractError("ordinal fallback必须绑定public ordering contract")
        else:
            expected_families = (
                PublicActionFamilyV1.END_PLAY_PHASE,
                PublicActionFamilyV1.PASS_RESPONSE,
                PublicActionFamilyV1.PASS_RESCUE,
                PublicActionFamilyV1.DECLINE_OPTIONAL,
                PublicActionFamilyV1.PASS_MODE_DECISION,
            )
            if self.window_kind is not TimedWindowKindV1.MULTI_STEP_OBLIGATION:
                raise C8VirtualTimeContractError("multi-step selector只允许multi-step window")
            if self.allowed_action_families != expected_families:
                raise C8VirtualTimeContractError(
                    "multi-step selector必须冻结完整safe explicit family顺序"
                )
            if self.ordering_contract_id != PUBLIC_ORDERING_CONTRACT_ID:
                raise C8VirtualTimeContractError(
                    "multi-step selector必须绑定public ordering contract"
                )
        if self.same_tick_chain_required != (
            self.window_kind is TimedWindowKindV1.MULTI_STEP_OBLIGATION
        ):
            raise C8VirtualTimeContractError("same-tick chain只能且必须用于multi-step obligation")
        _assert_identity(self.policy_identity, self._identity_material(), "policy_identity")

    def _identity_material(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "contract_version": self.contract_version,
            "policy_id": self.policy_id,
            "window_kind": self.window_kind.value,
            "selector": self.selector.value,
            "allowed_action_families": [item.value for item in self.allowed_action_families],
            "ordering_contract_id": self.ordering_contract_id,
            "same_tick_chain_required": self.same_tick_chain_required,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._identity_material(), "policy_identity": self.policy_identity}

    @classmethod
    def build(
        cls,
        *,
        policy_id: str,
        window_kind: TimedWindowKindV1,
        selector: TimeoutFallbackSelectorV1,
        allowed_action_families: tuple[PublicActionFamilyV1, ...] = (),
        ordering_contract_id: str | None = None,
        same_tick_chain_required: bool = False,
    ) -> "TimeoutFallbackPolicyV1":
        material = {
            "schema": FALLBACK_POLICY_SCHEMA,
            "contract_version": 1,
            "policy_id": policy_id,
            "window_kind": window_kind.value,
            "selector": selector.value,
            "allowed_action_families": [item.value for item in allowed_action_families],
            "ordering_contract_id": ordering_contract_id,
            "same_tick_chain_required": same_tick_chain_required,
        }
        return cls(
            schema=FALLBACK_POLICY_SCHEMA,
            contract_version=1,
            policy_id=policy_id,
            window_kind=window_kind,
            selector=selector,
            allowed_action_families=allowed_action_families,
            ordering_contract_id=ordering_contract_id,
            same_tick_chain_required=same_tick_chain_required,
            policy_identity=_canonical_sha256(material),
        )

    @classmethod
    def from_dict(cls, value: object) -> "TimeoutFallbackPolicyV1":
        data = _exact_dict(value, "TimeoutFallbackPolicyV1")
        _exact_fields(
            data,
            frozenset(
                {
                    "schema", "contract_version", "policy_id", "window_kind",
                    "selector", "allowed_action_families", "ordering_contract_id",
                    "same_tick_chain_required", "policy_identity",
                }
            ),
            "TimeoutFallbackPolicyV1",
        )
        families = tuple(
            _exact_enum(item, PublicActionFamilyV1, "allowed_action_families[]")
            for item in _exact_list(
                data["allowed_action_families"], "allowed_action_families"
            )
        )
        return cls(
            schema=_exact_text(data["schema"], "fallback policy schema"),
            contract_version=_exact_int(data["contract_version"], "contract_version"),
            policy_id=_exact_text(data["policy_id"], "policy_id"),
            window_kind=_exact_enum(data["window_kind"], TimedWindowKindV1, "window_kind"),
            selector=_exact_enum(data["selector"], TimeoutFallbackSelectorV1, "selector"),
            allowed_action_families=families,
            ordering_contract_id=_exact_optional_text(
                data["ordering_contract_id"], "ordering_contract_id"
            ),
            same_tick_chain_required=_exact_bool(
                data["same_tick_chain_required"], "same_tick_chain_required"
            ),
            policy_identity=_exact_sha256(data["policy_identity"], "policy_identity"),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class TimeoutFallbackRegistryV1:
    schema: str
    contract_version: int
    registry_id: str
    policies: tuple[TimeoutFallbackPolicyV1, ...]
    registry_identity: str

    def __post_init__(self) -> None:
        if self.schema != FALLBACK_REGISTRY_SCHEMA or self.registry_id != FALLBACK_REGISTRY_ID:
            raise C8VirtualTimeContractError("fallback registry schema/id不匹配")
        if type(self.contract_version) is not int or self.contract_version != 1:
            raise C8VirtualTimeContractError("fallback registry contract_version必须精确为1")
        if type(self.policies) is not tuple or any(
            type(item) is not TimeoutFallbackPolicyV1 for item in self.policies
        ):
            raise C8VirtualTimeContractError("fallback registry policies必须是strict tuple")
        if tuple(item.window_kind for item in self.policies) != tuple(TimedWindowKindV1):
            raise C8VirtualTimeContractError("fallback registry必须canonical完整覆盖window kinds")
        _assert_identity(self.registry_identity, self._identity_material(), "registry_identity")

    def _identity_material(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "contract_version": self.contract_version,
            "registry_id": self.registry_id,
            "policies": [item.to_dict() for item in self.policies],
        }

    def policy_for(self, window_kind: TimedWindowKindV1) -> TimeoutFallbackPolicyV1:
        if type(window_kind) is not TimedWindowKindV1:
            raise C8VirtualTimeContractError("policy_for window_kind类型不正确")
        return self.policies[tuple(TimedWindowKindV1).index(window_kind)]

    def to_dict(self) -> dict[str, object]:
        return {**self._identity_material(), "registry_identity": self.registry_identity}

    @classmethod
    def build(
        cls, policies: Sequence[TimeoutFallbackPolicyV1]
    ) -> "TimeoutFallbackRegistryV1":
        if type(policies) not in (tuple, list):
            raise C8VirtualTimeContractError("fallback policies必须是明确序列")
        items = tuple(policies)
        material = {
            "schema": FALLBACK_REGISTRY_SCHEMA,
            "contract_version": 1,
            "registry_id": FALLBACK_REGISTRY_ID,
            "policies": [item.to_dict() for item in items],
        }
        return cls(
            schema=FALLBACK_REGISTRY_SCHEMA,
            contract_version=1,
            registry_id=FALLBACK_REGISTRY_ID,
            policies=items,
            registry_identity=_canonical_sha256(material),
        )

    @classmethod
    def from_dict(cls, value: object) -> "TimeoutFallbackRegistryV1":
        data = _exact_dict(value, "TimeoutFallbackRegistryV1")
        _exact_fields(
            data,
            frozenset(
                {"schema", "contract_version", "registry_id", "policies", "registry_identity"}
            ),
            "TimeoutFallbackRegistryV1",
        )
        return cls(
            schema=_exact_text(data["schema"], "registry schema"),
            contract_version=_exact_int(data["contract_version"], "contract_version"),
            registry_id=_exact_text(data["registry_id"], "registry_id"),
            policies=tuple(
                TimeoutFallbackPolicyV1.from_dict(item)
                for item in _exact_list(data["policies"], "policies")
            ),
            registry_identity=_exact_sha256(data["registry_identity"], "registry_identity"),
        )


TIMEOUT_FALLBACK_REGISTRY_V1 = TimeoutFallbackRegistryV1.build(
    (
        TimeoutFallbackPolicyV1.build(
            policy_id="play-explicit-end-play-phase-v1",
            window_kind=TimedWindowKindV1.PLAY,
            selector=TimeoutFallbackSelectorV1.EXPLICIT_ACTION_FAMILY,
            allowed_action_families=(PublicActionFamilyV1.END_PLAY_PHASE,),
        ),
        TimeoutFallbackPolicyV1.build(
            policy_id="optional-response-explicit-pass-v1",
            window_kind=TimedWindowKindV1.OPTIONAL_RESPONSE,
            selector=TimeoutFallbackSelectorV1.EXPLICIT_ACTION_FAMILY,
            allowed_action_families=(PublicActionFamilyV1.PASS_RESPONSE,),
        ),
        TimeoutFallbackPolicyV1.build(
            policy_id="rescue-response-explicit-pass-v1",
            window_kind=TimedWindowKindV1.RESCUE_RESPONSE,
            selector=TimeoutFallbackSelectorV1.EXPLICIT_ACTION_FAMILY,
            allowed_action_families=(PublicActionFamilyV1.PASS_RESCUE,),
        ),
        TimeoutFallbackPolicyV1.build(
            policy_id="optional-skill-explicit-decline-v1",
            window_kind=TimedWindowKindV1.OPTIONAL_SKILL_DECISION,
            selector=TimeoutFallbackSelectorV1.EXPLICIT_ACTION_FAMILY,
            allowed_action_families=(PublicActionFamilyV1.DECLINE_OPTIONAL,),
        ),
        TimeoutFallbackPolicyV1.build(
            policy_id="mode-decision-explicit-pass-v1",
            window_kind=TimedWindowKindV1.MODE_DECISION,
            selector=TimeoutFallbackSelectorV1.EXPLICIT_ACTION_FAMILY,
            allowed_action_families=(PublicActionFamilyV1.PASS_MODE_DECISION,),
        ),
        TimeoutFallbackPolicyV1.build(
            policy_id="mandatory-single-unique-action-v1",
            window_kind=TimedWindowKindV1.MANDATORY_SINGLE_ACTION,
            selector=TimeoutFallbackSelectorV1.UNIQUE_LEGAL_ACTION,
        ),
        TimeoutFallbackPolicyV1.build(
            policy_id="mandatory-public-choice-canonical-ordinal-v1",
            window_kind=TimedWindowKindV1.MANDATORY_PUBLIC_CHOICE,
            selector=TimeoutFallbackSelectorV1.CANONICAL_PUBLIC_ORDINAL,
            ordering_contract_id=PUBLIC_ORDERING_CONTRACT_ID,
        ),
        TimeoutFallbackPolicyV1.build(
            policy_id="multi-step-safe-public-fallback-same-tick-v1",
            window_kind=TimedWindowKindV1.MULTI_STEP_OBLIGATION,
            selector=TimeoutFallbackSelectorV1.MULTI_STEP_SAFE_PUBLIC_FALLBACK,
            allowed_action_families=(
                PublicActionFamilyV1.END_PLAY_PHASE,
                PublicActionFamilyV1.PASS_RESPONSE,
                PublicActionFamilyV1.PASS_RESCUE,
                PublicActionFamilyV1.DECLINE_OPTIONAL,
                PublicActionFamilyV1.PASS_MODE_DECISION,
            ),
            ordering_contract_id=PUBLIC_ORDERING_CONTRACT_ID,
            same_tick_chain_required=True,
        ),
    )
)
TIMEOUT_FALLBACK_POLICY_BY_KIND_V1 = MappingProxyType(
    {item.window_kind: item for item in TIMEOUT_FALLBACK_REGISTRY_V1.policies}
)


@dataclass(frozen=True, slots=True, kw_only=True)
class TimedDecisionWindowV1:
    schema: str
    contract_version: int
    window_sequence: int
    window_id: str
    actor_id: str
    window_kind: TimedWindowKindV1
    opened_at: int
    deadline_at: int
    budget_ticks: int
    remaining_ticks: int
    parent_window_id: str | None
    status: TimedWindowStatusV1
    decision_identity: str
    obligation_identity: str
    duration_profile_identity: str
    fallback_policy_identity: str
    window_binding_identity: str
    window_state_identity: str

    def __post_init__(self) -> None:
        if self.schema != WINDOW_SCHEMA:
            raise C8VirtualTimeContractError("TimedDecisionWindowV1 schema不匹配")
        if type(self.contract_version) is not int or self.contract_version != 1:
            raise C8VirtualTimeContractError("window contract_version必须精确为1")
        _exact_int(self.window_sequence, "window_sequence")
        _exact_text(self.actor_id, "actor_id")
        if type(self.window_kind) is not TimedWindowKindV1:
            raise C8VirtualTimeContractError("window_kind类型不正确")
        _exact_int(self.opened_at, "opened_at")
        _exact_int(self.deadline_at, "deadline_at")
        _exact_int(self.budget_ticks, "budget_ticks", minimum=1)
        _exact_int(self.remaining_ticks, "remaining_ticks")
        if self.remaining_ticks > self.budget_ticks:
            raise C8VirtualTimeContractError("remaining_ticks不得超过initial budget")
        if self.deadline_at < self.opened_at:
            raise C8VirtualTimeContractError("deadline_at不得早于opened_at")
        _exact_optional_text(self.parent_window_id, "parent_window_id")
        if type(self.status) is not TimedWindowStatusV1:
            raise C8VirtualTimeContractError("window status类型不正确")
        _exact_sha256(self.decision_identity, "decision_identity")
        _exact_sha256(self.obligation_identity, "obligation_identity")
        _exact_sha256(self.duration_profile_identity, "duration_profile_identity")
        _exact_sha256(self.fallback_policy_identity, "fallback_policy_identity")
        if self.duration_profile_identity != ENGINEERING_TEST_PROFILE_V1.profile_identity:
            raise C8VirtualTimeContractError(
                "current C8-A window必须绑定frozen engineering duration profile"
            )
        expected_budget = ENGINEERING_TEST_PROFILE_V1.duration_for(self.window_kind)
        if self.budget_ticks != expected_budget:
            raise C8VirtualTimeContractError(
                "window budget_ticks必须等于frozen engineering duration"
            )
        expected_policy = TIMEOUT_FALLBACK_POLICY_BY_KIND_V1[self.window_kind]
        if self.fallback_policy_identity != expected_policy.policy_identity:
            raise C8VirtualTimeContractError(
                "current C8-A window必须绑定frozen fallback registry policy"
            )
        _assert_identity(
            self.window_binding_identity,
            self._binding_material(),
            "window_binding_identity",
        )
        expected_id = f"c8w-{self.window_binding_identity[:32]}"
        if _WINDOW_ID_RE.fullmatch(self.window_id) is None or self.window_id != expected_id:
            raise C8VirtualTimeContractError("window_id与immutable binding不一致")
        _assert_identity(
            self.window_state_identity, self._state_material(), "window_state_identity"
        )

    def _binding_material(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "contract_version": self.contract_version,
            "window_sequence": self.window_sequence,
            "actor_id": self.actor_id,
            "window_kind": self.window_kind.value,
            "opened_at": self.opened_at,
            "budget_ticks": self.budget_ticks,
            "parent_window_id": self.parent_window_id,
            "decision_identity": self.decision_identity,
            "obligation_identity": self.obligation_identity,
            "duration_profile_identity": self.duration_profile_identity,
            "fallback_policy_identity": self.fallback_policy_identity,
        }

    def _state_material(self) -> dict[str, object]:
        return {
            **self._binding_material(),
            "window_id": self.window_id,
            "deadline_at": self.deadline_at,
            "remaining_ticks": self.remaining_ticks,
            "status": self.status.value,
            "window_binding_identity": self.window_binding_identity,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._state_material(), "window_state_identity": self.window_state_identity}

    @classmethod
    def _build(
        cls,
        *,
        window_sequence: int,
        actor_id: str,
        window_kind: TimedWindowKindV1,
        opened_at: int,
        deadline_at: int,
        budget_ticks: int,
        remaining_ticks: int,
        parent_window_id: str | None,
        status: TimedWindowStatusV1,
        decision_identity: str,
        obligation_identity: str,
        duration_profile_identity: str,
        fallback_policy_identity: str,
    ) -> "TimedDecisionWindowV1":
        binding = {
            "schema": WINDOW_SCHEMA,
            "contract_version": 1,
            "window_sequence": window_sequence,
            "actor_id": actor_id,
            "window_kind": window_kind.value,
            "opened_at": opened_at,
            "budget_ticks": budget_ticks,
            "parent_window_id": parent_window_id,
            "decision_identity": decision_identity,
            "obligation_identity": obligation_identity,
            "duration_profile_identity": duration_profile_identity,
            "fallback_policy_identity": fallback_policy_identity,
        }
        binding_identity = _canonical_sha256(binding)
        window_id = f"c8w-{binding_identity[:32]}"
        state_material = {
            **binding,
            "window_id": window_id,
            "deadline_at": deadline_at,
            "remaining_ticks": remaining_ticks,
            "status": status.value,
            "window_binding_identity": binding_identity,
        }
        return cls(
            schema=WINDOW_SCHEMA,
            contract_version=1,
            window_sequence=window_sequence,
            window_id=window_id,
            actor_id=actor_id,
            window_kind=window_kind,
            opened_at=opened_at,
            deadline_at=deadline_at,
            budget_ticks=budget_ticks,
            remaining_ticks=remaining_ticks,
            parent_window_id=parent_window_id,
            status=status,
            decision_identity=decision_identity,
            obligation_identity=obligation_identity,
            duration_profile_identity=duration_profile_identity,
            fallback_policy_identity=fallback_policy_identity,
            window_binding_identity=binding_identity,
            window_state_identity=_canonical_sha256(state_material),
        )

    @classmethod
    def open(
        cls,
        *,
        window_sequence: int,
        actor_id: str,
        window_kind: TimedWindowKindV1,
        opened_at: int,
        parent_window_id: str | None,
        decision_identity: str,
        obligation_identity: str,
        duration_profile: DurationProfileV1,
        fallback_policy: TimeoutFallbackPolicyV1,
    ) -> "TimedDecisionWindowV1":
        if type(duration_profile) is not DurationProfileV1:
            raise C8VirtualTimeContractError("duration_profile类型不正确")
        if type(fallback_policy) is not TimeoutFallbackPolicyV1:
            raise C8VirtualTimeContractError("fallback_policy类型不正确")
        if fallback_policy.window_kind is not window_kind:
            raise C8VirtualTimeContractError("fallback policy与window kind不一致")
        if duration_profile != ENGINEERING_TEST_PROFILE_V1:
            raise C8VirtualTimeContractError("current C8-A只允许frozen engineering profile")
        if fallback_policy != TIMEOUT_FALLBACK_POLICY_BY_KIND_V1[window_kind]:
            raise C8VirtualTimeContractError("current C8-A只允许frozen fallback policy")
        budget = duration_profile.duration_for(window_kind)
        deadline = _safe_add_ticks(opened_at, budget, "window deadline")
        return cls._build(
            window_sequence=window_sequence,
            actor_id=actor_id,
            window_kind=window_kind,
            opened_at=opened_at,
            deadline_at=deadline,
            budget_ticks=budget,
            remaining_ticks=budget,
            parent_window_id=parent_window_id,
            status=TimedWindowStatusV1.ACTIVE,
            decision_identity=decision_identity,
            obligation_identity=obligation_identity,
            duration_profile_identity=duration_profile.profile_identity,
            fallback_policy_identity=fallback_policy.policy_identity,
        )

    def with_runtime_state(
        self,
        *,
        deadline_at: int,
        remaining_ticks: int,
        status: TimedWindowStatusV1,
    ) -> "TimedDecisionWindowV1":
        return self._build(
            window_sequence=self.window_sequence,
            actor_id=self.actor_id,
            window_kind=self.window_kind,
            opened_at=self.opened_at,
            deadline_at=deadline_at,
            budget_ticks=self.budget_ticks,
            remaining_ticks=remaining_ticks,
            parent_window_id=self.parent_window_id,
            status=status,
            decision_identity=self.decision_identity,
            obligation_identity=self.obligation_identity,
            duration_profile_identity=self.duration_profile_identity,
            fallback_policy_identity=self.fallback_policy_identity,
        )

    @classmethod
    def from_dict(cls, value: object) -> "TimedDecisionWindowV1":
        data = _exact_dict(value, "TimedDecisionWindowV1")
        fields = frozenset(
            {
                "schema", "contract_version", "window_sequence", "window_id",
                "actor_id", "window_kind", "opened_at", "deadline_at",
                "budget_ticks", "remaining_ticks", "parent_window_id", "status",
                "decision_identity", "obligation_identity",
                "duration_profile_identity", "fallback_policy_identity",
                "window_binding_identity", "window_state_identity",
            }
        )
        _exact_fields(data, fields, "TimedDecisionWindowV1")
        return cls(
            schema=_exact_text(data["schema"], "window.schema"),
            contract_version=_exact_int(data["contract_version"], "contract_version"),
            window_sequence=_exact_int(data["window_sequence"], "window_sequence"),
            window_id=_exact_text(data["window_id"], "window_id"),
            actor_id=_exact_text(data["actor_id"], "actor_id"),
            window_kind=_exact_enum(data["window_kind"], TimedWindowKindV1, "window_kind"),
            opened_at=_exact_int(data["opened_at"], "opened_at"),
            deadline_at=_exact_int(data["deadline_at"], "deadline_at"),
            budget_ticks=_exact_int(data["budget_ticks"], "budget_ticks", minimum=1),
            remaining_ticks=_exact_int(data["remaining_ticks"], "remaining_ticks"),
            parent_window_id=_exact_optional_text(
                data["parent_window_id"], "parent_window_id"
            ),
            status=_exact_enum(data["status"], TimedWindowStatusV1, "status"),
            decision_identity=_exact_sha256(data["decision_identity"], "decision_identity"),
            obligation_identity=_exact_sha256(
                data["obligation_identity"], "obligation_identity"
            ),
            duration_profile_identity=_exact_sha256(
                data["duration_profile_identity"], "duration_profile_identity"
            ),
            fallback_policy_identity=_exact_sha256(
                data["fallback_policy_identity"], "fallback_policy_identity"
            ),
            window_binding_identity=_exact_sha256(
                data["window_binding_identity"], "window_binding_identity"
            ),
            window_state_identity=_exact_sha256(
                data["window_state_identity"], "window_state_identity"
            ),
        )


def deadline_precedence_v1(
    window: TimedDecisionWindowV1, effective_tick: int
) -> DeadlinePrecedenceV1:
    if type(window) is not TimedDecisionWindowV1:
        raise C8VirtualTimeContractError("deadline precedence window类型不正确")
    tick = _exact_int(effective_tick, "effective_tick")
    if tick < window.deadline_at:
        return DeadlinePrecedenceV1.ACTION_ELIGIBLE_BEFORE_DEADLINE
    return DeadlinePrecedenceV1.TIMEOUT_PRIORITY_AT_OR_AFTER_DEADLINE


@dataclass(frozen=True, slots=True, kw_only=True)
class TimedWindowStackV1:
    schema: str
    contract_version: int
    windows: tuple[TimedDecisionWindowV1, ...]
    stack_identity: str

    def __post_init__(self) -> None:
        if self.schema != WINDOW_STACK_SCHEMA:
            raise C8VirtualTimeContractError("TimedWindowStackV1 schema不匹配")
        if type(self.contract_version) is not int or self.contract_version != 1:
            raise C8VirtualTimeContractError("window stack contract_version必须精确为1")
        if type(self.windows) is not tuple or any(
            type(item) is not TimedDecisionWindowV1 for item in self.windows
        ):
            raise C8VirtualTimeContractError("window stack必须是strict tuple")
        ids = tuple(item.window_id for item in self.windows)
        if len(ids) != len(set(ids)):
            raise C8VirtualTimeContractError("window stack禁止重复window_id")
        sequences = tuple(item.window_sequence for item in self.windows)
        if any(child <= parent for parent, child in zip(sequences, sequences[1:])):
            raise C8VirtualTimeContractError("window stack sequence必须随parent-child严格递增")
        for index, window in enumerate(self.windows):
            expected_parent = None if index == 0 else self.windows[index - 1].window_id
            if window.parent_window_id != expected_parent:
                raise C8VirtualTimeContractError("window stack parent关系不连续")
            expected_statuses = (
                {TimedWindowStatusV1.ACTIVE, TimedWindowStatusV1.FROZEN_BY_CLOCK_PAUSE}
                if index == len(self.windows) - 1
                else {TimedWindowStatusV1.SUSPENDED_BY_CHILD}
            )
            if window.status not in expected_statuses:
                raise C8VirtualTimeContractError("window stack状态违反strict LIFO/top规则")
        _assert_identity(self.stack_identity, self._identity_material(), "stack_identity")

    def _identity_material(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "contract_version": self.contract_version,
            "windows": [item.to_dict() for item in self.windows],
        }

    @property
    def active_window(self) -> TimedDecisionWindowV1 | None:
        return None if not self.windows else self.windows[-1]

    def to_dict(self) -> dict[str, object]:
        return {**self._identity_material(), "stack_identity": self.stack_identity}

    @classmethod
    def build(
        cls, windows: Sequence[TimedDecisionWindowV1]
    ) -> "TimedWindowStackV1":
        if type(windows) not in (tuple, list):
            raise C8VirtualTimeContractError("windows必须是明确序列")
        items = tuple(windows)
        material = {
            "schema": WINDOW_STACK_SCHEMA,
            "contract_version": 1,
            "windows": [item.to_dict() for item in items],
        }
        return cls(
            schema=WINDOW_STACK_SCHEMA,
            contract_version=1,
            windows=items,
            stack_identity=_canonical_sha256(material),
        )

    @classmethod
    def empty(cls) -> "TimedWindowStackV1":
        return cls.build(())

    @classmethod
    def from_dict(cls, value: object) -> "TimedWindowStackV1":
        data = _exact_dict(value, "TimedWindowStackV1")
        _exact_fields(
            data,
            frozenset({"schema", "contract_version", "windows", "stack_identity"}),
            "TimedWindowStackV1",
        )
        return cls(
            schema=_exact_text(data["schema"], "stack.schema"),
            contract_version=_exact_int(data["contract_version"], "contract_version"),
            windows=tuple(
                TimedDecisionWindowV1.from_dict(item)
                for item in _exact_list(data["windows"], "windows")
            ),
            stack_identity=_exact_sha256(data["stack_identity"], "stack_identity"),
        )

    def open_window(
        self, window: TimedDecisionWindowV1, current_tick: int
    ) -> "TimedWindowStackV1":
        if type(window) is not TimedDecisionWindowV1:
            raise C8VirtualTimeContractError("open_window window类型不正确")
        tick = _exact_int(current_tick, "current_tick")
        if window.opened_at != tick or window.status is not TimedWindowStatusV1.ACTIVE:
            raise C8VirtualTimeContractError("新window必须在current tick以ACTIVE打开")
        if not self.windows:
            if window.parent_window_id is not None:
                raise C8VirtualTimeContractError("root window不得声明parent")
            return self.build((window,))
        parent = self.windows[-1]
        if parent.status is not TimedWindowStatusV1.ACTIVE:
            raise C8VirtualTimeContractError("只有ACTIVE top可以打开child")
        if tick >= parent.deadline_at:
            raise C8VirtualTimeContractError("parent抵达deadline后timeout优先，禁止打开child")
        if window.parent_window_id != parent.window_id:
            raise C8VirtualTimeContractError("child parent_window_id不匹配active top")
        remaining = parent.deadline_at - tick
        suspended = parent.with_runtime_state(
            deadline_at=parent.deadline_at,
            remaining_ticks=remaining,
            status=TimedWindowStatusV1.SUSPENDED_BY_CHILD,
        )
        return self.build(self.windows[:-1] + (suspended, window))

    def close_active(
        self,
        *,
        window_id: str,
        current_tick: int,
        close_status: TimedWindowStatusV1,
    ) -> tuple["TimedWindowStackV1", TimedDecisionWindowV1]:
        _exact_text(window_id, "window_id")
        tick = _exact_int(current_tick, "current_tick")
        if close_status is TimedWindowStatusV1.ROLLED_BACK:
            raise C8VirtualTimeContractError(
                "ROLLED_BACK只能由VirtualTimeTransactionSnapshotV1.restore产生"
            )
        if close_status not in {
            TimedWindowStatusV1.CLOSED_BY_ACTION,
            TimedWindowStatusV1.CLOSED_BY_TIMEOUT,
        }:
            raise C8VirtualTimeContractError("close_status不是终止状态")
        if not self.windows or self.windows[-1].window_id != window_id:
            raise C8VirtualTimeContractError("只能按LIFO关闭active top window")
        active = self.windows[-1]
        if active.status is not TimedWindowStatusV1.ACTIVE:
            raise C8VirtualTimeContractError("frozen/suspended window不得直接关闭")
        if tick < active.opened_at:
            raise C8VirtualTimeContractError("关闭tick不得早于window opened_at")
        if (
            close_status is TimedWindowStatusV1.CLOSED_BY_ACTION
            and tick >= active.deadline_at
        ):
            raise C8VirtualTimeContractError("action只能在[opened_at, deadline_at)关闭window")
        if (
            close_status is TimedWindowStatusV1.CLOSED_BY_TIMEOUT
            and tick != active.deadline_at
        ):
            raise C8VirtualTimeContractError("timeout只能在exact deadline关闭window")
        remaining = max(active.deadline_at - tick, 0)
        closed = active.with_runtime_state(
            deadline_at=active.deadline_at,
            remaining_ticks=remaining,
            status=close_status,
        )
        survivors = self.windows[:-1]
        if not survivors:
            return self.empty(), closed
        parent = survivors[-1]
        if parent.status is not TimedWindowStatusV1.SUSPENDED_BY_CHILD:
            raise C8VirtualTimeContractError("child关闭时parent必须处于suspended状态")
        resumed_deadline = _safe_add_ticks(tick, parent.remaining_ticks, "resumed deadline")
        resumed = parent.with_runtime_state(
            deadline_at=resumed_deadline,
            remaining_ticks=parent.remaining_ticks,
            status=TimedWindowStatusV1.ACTIVE,
        )
        return self.build(survivors[:-1] + (resumed,)), closed

GENESIS_EVENT_CHAIN_TIP = _canonical_sha256(
    {"contract_id": C8_VIRTUAL_TIME_CONTRACT_ID, "event_chain": "GENESIS"}
)


@dataclass(frozen=True, slots=True, kw_only=True)
class VirtualTimeStateV1:
    schema: str
    contract_version: int
    clock_domain_identity: str
    now_tick: int
    next_input_seq: int
    next_window_seq: int
    clock_revision: int
    globally_paused: bool
    window_stack: TimedWindowStackV1
    event_chain: tuple[str, ...]
    event_chain_tip: str
    state_identity: str

    def __post_init__(self) -> None:
        if self.schema != VIRTUAL_TIME_STATE_SCHEMA:
            raise C8VirtualTimeContractError("VirtualTimeStateV1 schema不匹配")
        if type(self.contract_version) is not int or self.contract_version != 1:
            raise C8VirtualTimeContractError("virtual time contract_version必须精确为1")
        _exact_sha256(self.clock_domain_identity, "clock_domain_identity")
        if self.clock_domain_identity != CLOCK_DOMAIN_V1.clock_domain_identity:
            raise C8VirtualTimeContractError(
                "VirtualTimeStateV1必须绑定frozen C8-A clock domain"
            )
        _exact_int(self.now_tick, "now_tick")
        _exact_int(self.next_input_seq, "next_input_seq")
        _exact_int(self.next_window_seq, "next_window_seq")
        _exact_int(self.clock_revision, "clock_revision")
        _exact_bool(self.globally_paused, "globally_paused")
        if type(self.window_stack) is not TimedWindowStackV1:
            raise C8VirtualTimeContractError("window_stack类型不正确")
        if type(self.event_chain) is not tuple:
            raise C8VirtualTimeContractError("event_chain必须是strict tuple")
        for index, identity in enumerate(self.event_chain):
            _exact_sha256(identity, f"event_chain[{index}]")
        expected_tip = self.event_chain[-1] if self.event_chain else GENESIS_EVENT_CHAIN_TIP
        if self.event_chain_tip != expected_tip:
            raise C8VirtualTimeContractError("event_chain_tip与event_chain不一致")
        active = self.window_stack.active_window
        if active is not None:
            expected_status = (
                TimedWindowStatusV1.FROZEN_BY_CLOCK_PAUSE
                if self.globally_paused
                else TimedWindowStatusV1.ACTIVE
            )
            if active.status is not expected_status:
                raise C8VirtualTimeContractError("global pause与top window status不一致")
            if self.now_tick > active.deadline_at:
                raise C8VirtualTimeContractError("authoritative now不得越过active deadline")
            if active.remaining_ticks != active.deadline_at - self.now_tick:
                raise C8VirtualTimeContractError(
                    "active/frozen remaining_ticks必须精确等于deadline_at-now_tick"
                )
        windows = self.window_stack.windows
        if windows:
            if self.next_window_seq <= max(item.window_sequence for item in windows):
                raise C8VirtualTimeContractError("next_window_seq未越过已分配window sequence")
        elif self.next_window_seq < 0:
            raise C8VirtualTimeContractError("next_window_seq无效")
        for index, window in enumerate(windows):
            if window.opened_at > self.now_tick:
                raise C8VirtualTimeContractError("window opened_at不得晚于authoritative now")
            if index < len(windows) - 1:
                child = windows[index + 1]
                if child.opened_at < window.opened_at:
                    raise C8VirtualTimeContractError("child opened_at不得早于parent")
                expected_remaining = window.deadline_at - child.opened_at
                if expected_remaining <= 0 or window.remaining_ticks != expected_remaining:
                    raise C8VirtualTimeContractError(
                        "suspended parent remaining budget与child opening tick不一致"
                    )
        _assert_identity(self.state_identity, self._identity_material(), "state_identity")

    def _identity_material(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "contract_version": self.contract_version,
            "clock_domain_identity": self.clock_domain_identity,
            "now_tick": self.now_tick,
            "next_input_seq": self.next_input_seq,
            "next_window_seq": self.next_window_seq,
            "clock_revision": self.clock_revision,
            "globally_paused": self.globally_paused,
            "window_stack": self.window_stack.to_dict(),
            "event_chain": list(self.event_chain),
            "event_chain_tip": self.event_chain_tip,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._identity_material(), "state_identity": self.state_identity}

    @classmethod
    def build(
        cls,
        *,
        clock_domain_identity: str,
        now_tick: int,
        next_input_seq: int,
        next_window_seq: int,
        clock_revision: int,
        globally_paused: bool,
        window_stack: TimedWindowStackV1,
        event_chain: Sequence[str],
    ) -> "VirtualTimeStateV1":
        chain = tuple(event_chain)
        tip = chain[-1] if chain else GENESIS_EVENT_CHAIN_TIP
        material = {
            "schema": VIRTUAL_TIME_STATE_SCHEMA,
            "contract_version": 1,
            "clock_domain_identity": clock_domain_identity,
            "now_tick": now_tick,
            "next_input_seq": next_input_seq,
            "next_window_seq": next_window_seq,
            "clock_revision": clock_revision,
            "globally_paused": globally_paused,
            "window_stack": window_stack.to_dict(),
            "event_chain": list(chain),
            "event_chain_tip": tip,
        }
        return cls(
            schema=VIRTUAL_TIME_STATE_SCHEMA,
            contract_version=1,
            clock_domain_identity=clock_domain_identity,
            now_tick=now_tick,
            next_input_seq=next_input_seq,
            next_window_seq=next_window_seq,
            clock_revision=clock_revision,
            globally_paused=globally_paused,
            window_stack=window_stack,
            event_chain=chain,
            event_chain_tip=tip,
            state_identity=_canonical_sha256(material),
        )

    @classmethod
    def initial(cls, clock_domain: ClockDomainV1) -> "VirtualTimeStateV1":
        if type(clock_domain) is not ClockDomainV1:
            raise C8VirtualTimeContractError("clock_domain类型不正确")
        return cls.build(
            clock_domain_identity=clock_domain.clock_domain_identity,
            now_tick=0,
            next_input_seq=0,
            next_window_seq=0,
            clock_revision=0,
            globally_paused=False,
            window_stack=TimedWindowStackV1.empty(),
            event_chain=(),
        )

    @classmethod
    def from_dict(cls, value: object) -> "VirtualTimeStateV1":
        data = _exact_dict(value, "VirtualTimeStateV1")
        _exact_fields(
            data,
            frozenset(
                {
                    "schema", "contract_version", "clock_domain_identity", "now_tick",
                    "next_input_seq", "next_window_seq", "clock_revision",
                    "globally_paused", "window_stack", "event_chain",
                    "event_chain_tip", "state_identity",
                }
            ),
            "VirtualTimeStateV1",
        )
        return cls(
            schema=_exact_text(data["schema"], "state.schema"),
            contract_version=_exact_int(data["contract_version"], "contract_version"),
            clock_domain_identity=_exact_sha256(
                data["clock_domain_identity"], "clock_domain_identity"
            ),
            now_tick=_exact_int(data["now_tick"], "now_tick"),
            next_input_seq=_exact_int(data["next_input_seq"], "next_input_seq"),
            next_window_seq=_exact_int(data["next_window_seq"], "next_window_seq"),
            clock_revision=_exact_int(data["clock_revision"], "clock_revision"),
            globally_paused=_exact_bool(data["globally_paused"], "globally_paused"),
            window_stack=TimedWindowStackV1.from_dict(data["window_stack"]),
            event_chain=tuple(
                _exact_sha256(item, "event_chain[]")
                for item in _exact_list(data["event_chain"], "event_chain")
            ),
            event_chain_tip=_exact_sha256(data["event_chain_tip"], "event_chain_tip"),
            state_identity=_exact_sha256(data["state_identity"], "state_identity"),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class WindowCloseTransitionV1:
    state: VirtualTimeStateV1
    closed_window: TimedDecisionWindowV1

    def __post_init__(self) -> None:
        if type(self.state) is not VirtualTimeStateV1:
            raise C8VirtualTimeContractError("close transition state类型不正确")
        if type(self.closed_window) is not TimedDecisionWindowV1:
            raise C8VirtualTimeContractError("closed_window类型不正确")


def open_decision_window_v1(
    state: VirtualTimeStateV1,
    *,
    actor_id: str,
    window_kind: TimedWindowKindV1,
    decision_identity: str,
    obligation_identity: str,
    duration_profile: DurationProfileV1,
    fallback_policy: TimeoutFallbackPolicyV1,
) -> VirtualTimeStateV1:
    if type(state) is not VirtualTimeStateV1:
        raise C8VirtualTimeContractError("open state类型不正确")
    if state.globally_paused:
        raise C8VirtualTimeContractError("global pause期间禁止打开decision window")
    parent = state.window_stack.active_window
    parent_id = None if parent is None else parent.window_id
    window = TimedDecisionWindowV1.open(
        window_sequence=state.next_window_seq,
        actor_id=actor_id,
        window_kind=window_kind,
        opened_at=state.now_tick,
        parent_window_id=parent_id,
        decision_identity=decision_identity,
        obligation_identity=obligation_identity,
        duration_profile=duration_profile,
        fallback_policy=fallback_policy,
    )
    stack = state.window_stack.open_window(window, state.now_tick)
    return VirtualTimeStateV1.build(
        clock_domain_identity=state.clock_domain_identity,
        now_tick=state.now_tick,
        next_input_seq=state.next_input_seq,
        next_window_seq=state.next_window_seq + 1,
        clock_revision=state.clock_revision + 1,
        globally_paused=False,
        window_stack=stack,
        event_chain=state.event_chain,
    )


def close_decision_window_v1(
    state: VirtualTimeStateV1,
    *,
    window_id: str,
    close_status: TimedWindowStatusV1,
) -> WindowCloseTransitionV1:
    if type(state) is not VirtualTimeStateV1:
        raise C8VirtualTimeContractError("close state类型不正确")
    if state.globally_paused:
        raise C8VirtualTimeContractError("global pause期间禁止关闭decision window")
    stack, closed = state.window_stack.close_active(
        window_id=window_id,
        current_tick=state.now_tick,
        close_status=close_status,
    )
    next_state = VirtualTimeStateV1.build(
        clock_domain_identity=state.clock_domain_identity,
        now_tick=state.now_tick,
        next_input_seq=state.next_input_seq,
        next_window_seq=state.next_window_seq,
        clock_revision=state.clock_revision + 1,
        globally_paused=False,
        window_stack=stack,
        event_chain=state.event_chain,
    )
    return WindowCloseTransitionV1(state=next_state, closed_window=closed)


@dataclass(frozen=True, slots=True, kw_only=True)
class VirtualTimeControlInputV1:
    schema: str
    contract_version: int
    input_kind: VirtualTimeControlInputKindV1
    input_seq: int
    source_id: str
    source_kind: str
    domain_id: str
    window_id: str
    authentication_evidence_identity: str
    input_identity: str

    def __post_init__(self) -> None:
        if self.schema != CONTROL_INPUT_SCHEMA:
            raise C8VirtualTimeContractError("VirtualTimeControlInputV1 schema不匹配")
        if type(self.contract_version) is not int or self.contract_version != 1:
            raise C8VirtualTimeContractError("control input contract_version必须精确为1")
        if type(self.input_kind) is not VirtualTimeControlInputKindV1:
            raise C8VirtualTimeContractError("control input_kind类型不正确")
        _exact_int(self.input_seq, "control.input_seq")
        _exact_text(self.source_id, "control.source_id")
        if self.source_kind != "AUTHENTICATED_LOGICAL_DRIVER":
            raise C8VirtualTimeContractError(
                "control source_kind必须是authenticated logical driver"
            )
        if self.domain_id != CLOCK_DOMAIN_ID:
            raise C8VirtualTimeContractError("control input domain_id不匹配")
        _exact_text(self.window_id, "control.window_id")
        _exact_sha256(
            self.authentication_evidence_identity,
            "control.authentication_evidence_identity",
        )
        _assert_identity(self.input_identity, self._identity_material(), "control.input_identity")

    def _identity_material(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "contract_version": self.contract_version,
            "input_kind": self.input_kind.value,
            "input_seq": self.input_seq,
            "source_id": self.source_id,
            "source_kind": self.source_kind,
            "domain_id": self.domain_id,
            "window_id": self.window_id,
            "authentication_evidence_identity": self.authentication_evidence_identity,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._identity_material(), "input_identity": self.input_identity}

    @classmethod
    def issue(
        cls,
        *,
        input_kind: VirtualTimeControlInputKindV1,
        input_seq: int,
        source_id: str,
        domain_id: str,
        window_id: str,
        authentication_evidence_identity: str,
    ) -> "VirtualTimeControlInputV1":
        if type(input_kind) is not VirtualTimeControlInputKindV1:
            raise C8VirtualTimeContractError("control input_kind类型不正确")
        material = {
            "schema": CONTROL_INPUT_SCHEMA,
            "contract_version": 1,
            "input_kind": input_kind.value,
            "input_seq": input_seq,
            "source_id": source_id,
            "source_kind": "AUTHENTICATED_LOGICAL_DRIVER",
            "domain_id": domain_id,
            "window_id": window_id,
            "authentication_evidence_identity": authentication_evidence_identity,
        }
        return cls(
            schema=CONTROL_INPUT_SCHEMA,
            contract_version=1,
            input_kind=input_kind,
            input_seq=input_seq,
            source_id=source_id,
            source_kind="AUTHENTICATED_LOGICAL_DRIVER",
            domain_id=domain_id,
            window_id=window_id,
            authentication_evidence_identity=authentication_evidence_identity,
            input_identity=_canonical_sha256(material),
        )

    @classmethod
    def from_dict(cls, value: object) -> "VirtualTimeControlInputV1":
        data = _exact_dict(value, "VirtualTimeControlInputV1")
        _exact_fields(
            data,
            frozenset(
                {
                    "schema", "contract_version", "input_kind", "input_seq",
                    "source_id", "source_kind", "domain_id", "window_id",
                    "authentication_evidence_identity", "input_identity",
                }
            ),
            "VirtualTimeControlInputV1",
        )
        return cls(
            schema=_exact_text(data["schema"], "control.schema"),
            contract_version=_exact_int(data["contract_version"], "contract_version"),
            input_kind=_exact_enum(
                data["input_kind"], VirtualTimeControlInputKindV1, "control.input_kind"
            ),
            input_seq=_exact_int(data["input_seq"], "control.input_seq"),
            source_id=_exact_text(data["source_id"], "control.source_id"),
            source_kind=_exact_text(data["source_kind"], "control.source_kind"),
            domain_id=_exact_text(data["domain_id"], "control.domain_id"),
            window_id=_exact_text(data["window_id"], "control.window_id"),
            authentication_evidence_identity=_exact_sha256(
                data["authentication_evidence_identity"],
                "control.authentication_evidence_identity",
            ),
            input_identity=_exact_sha256(data["input_identity"], "control.input_identity"),
        )


def _validate_control_input_v1(
    state: VirtualTimeStateV1,
    control_input: VirtualTimeControlInputV1,
    clock_domain: ClockDomainV1,
    expected_kind: VirtualTimeControlInputKindV1,
) -> TimedDecisionWindowV1:
    if type(state) is not VirtualTimeStateV1:
        raise C8VirtualTimeContractError("control state类型不正确")
    if type(control_input) is not VirtualTimeControlInputV1:
        raise C8VirtualTimeContractError("control_input类型不正确")
    if type(clock_domain) is not ClockDomainV1:
        raise C8VirtualTimeContractError("clock_domain类型不正确")
    if state.clock_domain_identity != clock_domain.clock_domain_identity:
        raise C8VirtualTimeContractError("state clock domain identity不匹配")
    if control_input.domain_id != clock_domain.domain_id:
        raise C8VirtualTimeContractError("control input clock domain不匹配")
    if control_input.input_kind is not expected_kind:
        raise C8VirtualTimeContractError("control input kind不匹配")
    if control_input.input_seq != state.next_input_seq:
        raise C8VirtualTimeContractError("control input sequence重复、跳号或重排")
    active = state.window_stack.active_window
    if active is None or control_input.window_id != active.window_id:
        raise C8VirtualTimeContractError("control input绑定了stale/非active window")
    return active


def pause_virtual_time_v1(
    state: VirtualTimeStateV1,
    control_input: VirtualTimeControlInputV1,
    clock_domain: ClockDomainV1,
) -> VirtualTimeStateV1:
    active = _validate_control_input_v1(
        state, control_input, clock_domain, VirtualTimeControlInputKindV1.PAUSE
    )
    if state.globally_paused:
        raise C8VirtualTimeContractError("只能暂停未暂停的virtual time state")
    if active.status is not TimedWindowStatusV1.ACTIVE:
        raise C8VirtualTimeContractError("PAUSE只允许ACTIVE top window")
    active = state.window_stack.active_window
    stack = state.window_stack
    assert active is not None
    if state.now_tick >= active.deadline_at:
        raise C8VirtualTimeContractError("deadline已到达时必须先处理timeout")
    remaining = active.deadline_at - state.now_tick
    frozen = active.with_runtime_state(
        deadline_at=active.deadline_at,
        remaining_ticks=remaining,
        status=TimedWindowStatusV1.FROZEN_BY_CLOCK_PAUSE,
    )
    stack = TimedWindowStackV1.build(stack.windows[:-1] + (frozen,))
    return VirtualTimeStateV1.build(
        clock_domain_identity=state.clock_domain_identity,
        now_tick=state.now_tick,
        next_input_seq=state.next_input_seq + 1,
        next_window_seq=state.next_window_seq,
        clock_revision=state.clock_revision + 1,
        globally_paused=True,
        window_stack=stack,
        event_chain=state.event_chain,
    )


def resume_virtual_time_v1(
    state: VirtualTimeStateV1,
    control_input: VirtualTimeControlInputV1,
    clock_domain: ClockDomainV1,
) -> VirtualTimeStateV1:
    active = _validate_control_input_v1(
        state, control_input, clock_domain, VirtualTimeControlInputKindV1.RESUME
    )
    if not state.globally_paused:
        raise C8VirtualTimeContractError("只能恢复已暂停的virtual time state")
    if active.status is not TimedWindowStatusV1.FROZEN_BY_CLOCK_PAUSE:
        raise C8VirtualTimeContractError("RESUME只允许FROZEN top window")
    stack = state.window_stack
    deadline = _safe_add_ticks(state.now_tick, active.remaining_ticks, "resume deadline")
    resumed = active.with_runtime_state(
        deadline_at=deadline,
        remaining_ticks=active.remaining_ticks,
        status=TimedWindowStatusV1.ACTIVE,
    )
    stack = TimedWindowStackV1.build(stack.windows[:-1] + (resumed,))
    return VirtualTimeStateV1.build(
        clock_domain_identity=state.clock_domain_identity,
        now_tick=state.now_tick,
        next_input_seq=state.next_input_seq + 1,
        next_window_seq=state.next_window_seq,
        clock_revision=state.clock_revision + 1,
        globally_paused=False,
        window_stack=stack,
        event_chain=state.event_chain,
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class VirtualTimeAdvanceInputV1:
    schema: str
    contract_version: int
    input_kind: VirtualTimeAdvanceInputKindV1
    input_seq: int
    source_id: str
    source_kind: str
    domain_id: str
    window_id: str
    requested_tick: int
    authentication_evidence_identity: str
    input_identity: str

    def __post_init__(self) -> None:
        if self.schema != ADVANCE_INPUT_SCHEMA:
            raise C8VirtualTimeContractError("VirtualTimeAdvanceInputV1 schema不匹配")
        if type(self.contract_version) is not int or self.contract_version != 1:
            raise C8VirtualTimeContractError("advance input contract_version必须精确为1")
        if type(self.input_kind) is not VirtualTimeAdvanceInputKindV1:
            raise C8VirtualTimeContractError("input_kind类型不正确")
        if self.input_kind is not VirtualTimeAdvanceInputKindV1.TIME_ADVANCE:
            raise C8VirtualTimeContractError("caller只能请求TIME_ADVANCE")
        _exact_int(self.input_seq, "input_seq")
        _exact_text(self.source_id, "source_id")
        if self.source_kind != "AUTHENTICATED_LOGICAL_DRIVER":
            raise C8VirtualTimeContractError("source_kind必须是authenticated logical driver")
        if self.domain_id != CLOCK_DOMAIN_ID:
            raise C8VirtualTimeContractError("advance input domain_id不匹配")
        _exact_text(self.window_id, "window_id")
        _exact_int(self.requested_tick, "requested_tick")
        _exact_sha256(
            self.authentication_evidence_identity,
            "authentication_evidence_identity",
        )
        _assert_identity(self.input_identity, self._identity_material(), "input_identity")

    def _identity_material(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "contract_version": self.contract_version,
            "input_kind": self.input_kind.value,
            "input_seq": self.input_seq,
            "source_id": self.source_id,
            "source_kind": self.source_kind,
            "domain_id": self.domain_id,
            "window_id": self.window_id,
            "requested_tick": self.requested_tick,
            "authentication_evidence_identity": self.authentication_evidence_identity,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._identity_material(), "input_identity": self.input_identity}

    @classmethod
    def issue(
        cls,
        *,
        input_seq: int,
        source_id: str,
        domain_id: str,
        window_id: str,
        requested_tick: int,
        authentication_evidence_identity: str,
    ) -> "VirtualTimeAdvanceInputV1":
        material = {
            "schema": ADVANCE_INPUT_SCHEMA,
            "contract_version": 1,
            "input_kind": VirtualTimeAdvanceInputKindV1.TIME_ADVANCE.value,
            "input_seq": input_seq,
            "source_id": source_id,
            "source_kind": "AUTHENTICATED_LOGICAL_DRIVER",
            "domain_id": domain_id,
            "window_id": window_id,
            "requested_tick": requested_tick,
            "authentication_evidence_identity": authentication_evidence_identity,
        }
        return cls(
            schema=ADVANCE_INPUT_SCHEMA,
            contract_version=1,
            input_kind=VirtualTimeAdvanceInputKindV1.TIME_ADVANCE,
            input_seq=input_seq,
            source_id=source_id,
            source_kind="AUTHENTICATED_LOGICAL_DRIVER",
            domain_id=domain_id,
            window_id=window_id,
            requested_tick=requested_tick,
            authentication_evidence_identity=authentication_evidence_identity,
            input_identity=_canonical_sha256(material),
        )

    @classmethod
    def from_dict(cls, value: object) -> "VirtualTimeAdvanceInputV1":
        data = _exact_dict(value, "VirtualTimeAdvanceInputV1")
        _exact_fields(
            data,
            frozenset(
                {
                    "schema", "contract_version", "input_kind", "input_seq", "source_id",
                    "source_kind", "domain_id", "window_id", "requested_tick",
                    "authentication_evidence_identity", "input_identity",
                }
            ),
            "VirtualTimeAdvanceInputV1",
        )
        return cls(
            schema=_exact_text(data["schema"], "advance.schema"),
            contract_version=_exact_int(data["contract_version"], "contract_version"),
            input_kind=_exact_enum(
                data["input_kind"], VirtualTimeAdvanceInputKindV1, "input_kind"
            ),
            input_seq=_exact_int(data["input_seq"], "input_seq"),
            source_id=_exact_text(data["source_id"], "source_id"),
            source_kind=_exact_text(data["source_kind"], "source_kind"),
            domain_id=_exact_text(data["domain_id"], "domain_id"),
            window_id=_exact_text(data["window_id"], "window_id"),
            requested_tick=_exact_int(data["requested_tick"], "requested_tick"),
            authentication_evidence_identity=_exact_sha256(
                data["authentication_evidence_identity"],
                "authentication_evidence_identity",
            ),
            input_identity=_exact_sha256(data["input_identity"], "input_identity"),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class DerivedDeadlineReachedV1:
    schema: str
    contract_version: int
    event_kind: str
    event_id: str
    caused_by_input_seq: int
    caused_by_input_identity: str
    window_id: str
    actor_id: str
    window_kind: TimedWindowKindV1
    opened_at: int
    deadline_at: int
    reached_at: int
    elapsed_ticks: int
    budget_ticks: int
    elapsed_semantics: str
    duration_profile_identity: str
    fallback_policy_identity: str
    previous_event_chain_tip: str
    event_identity: str
    derivation_guard: InitVar[object]

    def __post_init__(self, derivation_guard: object) -> None:
        if derivation_guard is not _DERIVATION_GUARD:
            raise C8VirtualTimeContractError(
                "DerivedDeadlineReachedV1只能由authoritative virtual time推导"
            )
        if self.schema != DERIVED_DEADLINE_SCHEMA or self.event_kind != "DEADLINE_REACHED":
            raise C8VirtualTimeContractError("derived deadline schema/event kind不匹配")
        if type(self.contract_version) is not int or self.contract_version != 1:
            raise C8VirtualTimeContractError("derived deadline contract_version必须精确为1")
        _exact_text(self.event_id, "event_id")
        _exact_int(self.caused_by_input_seq, "caused_by_input_seq")
        _exact_sha256(self.caused_by_input_identity, "caused_by_input_identity")
        _exact_text(self.window_id, "window_id")
        _exact_text(self.actor_id, "actor_id")
        if type(self.window_kind) is not TimedWindowKindV1:
            raise C8VirtualTimeContractError("derived window_kind类型不正确")
        _exact_int(self.opened_at, "opened_at")
        _exact_int(self.deadline_at, "deadline_at")
        _exact_int(self.reached_at, "reached_at")
        _exact_int(self.elapsed_ticks, "elapsed_ticks")
        if self.reached_at != self.deadline_at:
            raise C8VirtualTimeContractError("DEADLINE_REACHED必须在exact deadline推导")
        _exact_int(self.budget_ticks, "budget_ticks", minimum=1)
        if self.elapsed_semantics != "ACTIVE_BUDGET_TICKS_ONLY":
            raise C8VirtualTimeContractError("elapsed_semantics必须排除child suspended time")
        if self.elapsed_ticks != self.budget_ticks:
            raise C8VirtualTimeContractError("deadline event必须耗尽exact active budget")
        _exact_sha256(self.duration_profile_identity, "duration_profile_identity")
        _exact_sha256(self.fallback_policy_identity, "fallback_policy_identity")
        _exact_sha256(self.previous_event_chain_tip, "previous_event_chain_tip")
        expected_id = f"c8-deadline-{_canonical_sha256(self._event_id_material())[:32]}"
        if self.event_id != expected_id:
            raise C8VirtualTimeContractError("derived deadline event_id不匹配")
        _assert_identity(self.event_identity, self._identity_material(), "event_identity")

    def _event_id_material(self) -> dict[str, object]:
        return {
            "event_kind": self.event_kind,
            "caused_by_input_seq": self.caused_by_input_seq,
            "caused_by_input_identity": self.caused_by_input_identity,
            "window_id": self.window_id,
            "deadline_at": self.deadline_at,
        }

    def _identity_material(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "contract_version": self.contract_version,
            "event_kind": self.event_kind,
            "event_id": self.event_id,
            "caused_by_input_seq": self.caused_by_input_seq,
            "caused_by_input_identity": self.caused_by_input_identity,
            "window_id": self.window_id,
            "actor_id": self.actor_id,
            "window_kind": self.window_kind.value,
            "opened_at": self.opened_at,
            "deadline_at": self.deadline_at,
            "reached_at": self.reached_at,
            "elapsed_ticks": self.elapsed_ticks,
            "budget_ticks": self.budget_ticks,
            "elapsed_semantics": self.elapsed_semantics,
            "duration_profile_identity": self.duration_profile_identity,
            "fallback_policy_identity": self.fallback_policy_identity,
            "previous_event_chain_tip": self.previous_event_chain_tip,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._identity_material(), "event_identity": self.event_identity}

    @classmethod
    def derive(
        cls,
        *,
        prior_state: VirtualTimeStateV1,
        current_tick: int,
        caused_by_input: VirtualTimeAdvanceInputV1,
        previous_event_chain_tip: str,
    ) -> "DerivedDeadlineReachedV1":
        if type(prior_state) is not VirtualTimeStateV1:
            raise C8VirtualTimeContractError("deadline derivation prior_state类型不正确")
        if type(caused_by_input) is not VirtualTimeAdvanceInputV1:
            raise C8VirtualTimeContractError("deadline derivation input类型不正确")
        window = prior_state.window_stack.active_window
        if (
            prior_state.globally_paused
            or window is None
            or window.status is not TimedWindowStatusV1.ACTIVE
        ):
            raise C8VirtualTimeContractError("deadline derivation需要未暂停的ACTIVE top window")
        if previous_event_chain_tip != prior_state.event_chain_tip:
            raise C8VirtualTimeContractError("deadline derivation event chain tip不匹配")
        if caused_by_input.input_seq != prior_state.next_input_seq:
            raise C8VirtualTimeContractError("deadline derivation input sequence不匹配")
        if caused_by_input.window_id != window.window_id:
            raise C8VirtualTimeContractError("deadline derivation input window不匹配")
        if caused_by_input.requested_tick < window.deadline_at:
            raise C8VirtualTimeContractError("deadline derivation input未请求到达deadline")
        if prior_state.now_tick >= window.deadline_at:
            raise C8VirtualTimeContractError("deadline必须由before-deadline state首次跨越推导")
        tick = _exact_int(current_tick, "current_tick")
        if tick != window.deadline_at:
            raise C8VirtualTimeContractError("deadline event只能由current time == deadline推导")
        base = {
            "event_kind": "DEADLINE_REACHED",
            "caused_by_input_seq": caused_by_input.input_seq,
            "caused_by_input_identity": caused_by_input.input_identity,
            "window_id": window.window_id,
            "deadline_at": window.deadline_at,
        }
        event_id = f"c8-deadline-{_canonical_sha256(base)[:32]}"
        material = {
            "schema": DERIVED_DEADLINE_SCHEMA,
            "contract_version": 1,
            "event_kind": "DEADLINE_REACHED",
            "event_id": event_id,
            "caused_by_input_seq": caused_by_input.input_seq,
            "caused_by_input_identity": caused_by_input.input_identity,
            "window_id": window.window_id,
            "actor_id": window.actor_id,
            "window_kind": window.window_kind.value,
            "opened_at": window.opened_at,
            "deadline_at": window.deadline_at,
            "reached_at": tick,
            "elapsed_ticks": window.budget_ticks,
            "budget_ticks": window.budget_ticks,
            "elapsed_semantics": "ACTIVE_BUDGET_TICKS_ONLY",
            "duration_profile_identity": window.duration_profile_identity,
            "fallback_policy_identity": window.fallback_policy_identity,
            "previous_event_chain_tip": previous_event_chain_tip,
        }
        return cls(
            schema=DERIVED_DEADLINE_SCHEMA,
            contract_version=1,
            event_kind="DEADLINE_REACHED",
            event_id=event_id,
            caused_by_input_seq=caused_by_input.input_seq,
            caused_by_input_identity=caused_by_input.input_identity,
            window_id=window.window_id,
            actor_id=window.actor_id,
            window_kind=window.window_kind,
            opened_at=window.opened_at,
            deadline_at=window.deadline_at,
            reached_at=tick,
            elapsed_ticks=window.budget_ticks,
            budget_ticks=window.budget_ticks,
            elapsed_semantics="ACTIVE_BUDGET_TICKS_ONLY",
            duration_profile_identity=window.duration_profile_identity,
            fallback_policy_identity=window.fallback_policy_identity,
            previous_event_chain_tip=previous_event_chain_tip,
            event_identity=_canonical_sha256(material),
            derivation_guard=_DERIVATION_GUARD,
        )

    @classmethod
    def from_dict(
        cls,
        value: object,
        *,
        prior_state: VirtualTimeStateV1,
        current_tick: int,
        caused_by_input: VirtualTimeAdvanceInputV1,
        previous_event_chain_tip: str,
    ) -> "DerivedDeadlineReachedV1":
        data = _exact_dict(value, "DerivedDeadlineReachedV1")
        expected = cls.derive(
            prior_state=prior_state,
            current_tick=current_tick,
            caused_by_input=caused_by_input,
            previous_event_chain_tip=previous_event_chain_tip,
        )
        _exact_fields(data, frozenset(expected.to_dict()), "DerivedDeadlineReachedV1")
        if not _strict_json_equal(data, expected.to_dict()):
            raise C8VirtualTimeContractError(
                "serialized DEADLINE_REACHED与fresh derivation不一致"
            )
        return expected


@dataclass(frozen=True, slots=True, kw_only=True)
class VirtualTimeAdvanceResultV1:
    state: VirtualTimeStateV1
    derived_deadline: DerivedDeadlineReachedV1 | None
    requested_tick: int
    applied_tick: int
    consumed_ticks: int
    unconsumed_ticks: int

    def __post_init__(self) -> None:
        if type(self.state) is not VirtualTimeStateV1:
            raise C8VirtualTimeContractError("advance result state类型不正确")
        if self.derived_deadline is not None and type(
            self.derived_deadline
        ) is not DerivedDeadlineReachedV1:
            raise C8VirtualTimeContractError("derived_deadline类型不正确")
        _exact_int(self.requested_tick, "requested_tick")
        _exact_int(self.applied_tick, "applied_tick")
        _exact_int(self.consumed_ticks, "consumed_ticks")
        _exact_int(self.unconsumed_ticks, "unconsumed_ticks")
        if self.requested_tick != self.applied_tick + self.unconsumed_ticks:
            raise C8VirtualTimeContractError("advance result surplus accounting不一致")


def advance_virtual_time_v1(
    state: VirtualTimeStateV1,
    advance_input: VirtualTimeAdvanceInputV1,
    clock_domain: ClockDomainV1,
) -> VirtualTimeAdvanceResultV1:
    if type(state) is not VirtualTimeStateV1:
        raise C8VirtualTimeContractError("advance state类型不正确")
    if type(advance_input) is not VirtualTimeAdvanceInputV1:
        raise C8VirtualTimeContractError("advance_input类型不正确")
    if type(clock_domain) is not ClockDomainV1:
        raise C8VirtualTimeContractError("clock_domain类型不正确")
    if state.clock_domain_identity != clock_domain.clock_domain_identity:
        raise C8VirtualTimeContractError("state clock domain identity不匹配")
    if advance_input.domain_id != clock_domain.domain_id:
        raise C8VirtualTimeContractError("advance input clock domain不匹配")
    if advance_input.input_seq != state.next_input_seq:
        raise C8VirtualTimeContractError("advance input sequence重复、跳号或重排")
    if state.globally_paused:
        raise C8VirtualTimeContractError("global pause期间拒绝TIME_ADVANCE")
    active = state.window_stack.active_window
    if active is None or active.status is not TimedWindowStatusV1.ACTIVE:
        raise C8VirtualTimeContractError("TIME_ADVANCE需要ACTIVE top window")
    if advance_input.window_id != active.window_id:
        raise C8VirtualTimeContractError("TIME_ADVANCE绑定了stale/非active window")
    if advance_input.requested_tick < state.now_tick:
        raise C8VirtualTimeContractError("virtual time禁止倒退")
    if state.now_tick >= active.deadline_at:
        raise C8VirtualTimeContractError("deadline已经到达，必须先resolve timeout")
    applied_tick = min(advance_input.requested_tick, active.deadline_at)
    consumed_ticks = applied_tick - state.now_tick
    unconsumed_ticks = advance_input.requested_tick - applied_tick
    updated_active = active.with_runtime_state(
        deadline_at=active.deadline_at,
        remaining_ticks=active.deadline_at - applied_tick,
        status=TimedWindowStatusV1.ACTIVE,
    )
    stack = TimedWindowStackV1.build(
        state.window_stack.windows[:-1] + (updated_active,)
    )
    derived: DerivedDeadlineReachedV1 | None = None
    event_chain = state.event_chain
    if applied_tick == active.deadline_at:
        derived = DerivedDeadlineReachedV1.derive(
            prior_state=state,
            current_tick=applied_tick,
            caused_by_input=advance_input,
            previous_event_chain_tip=state.event_chain_tip,
        )
        event_chain = event_chain + (derived.event_identity,)
    next_state = VirtualTimeStateV1.build(
        clock_domain_identity=state.clock_domain_identity,
        now_tick=applied_tick,
        next_input_seq=state.next_input_seq + 1,
        next_window_seq=state.next_window_seq,
        clock_revision=state.clock_revision + 1,
        globally_paused=False,
        window_stack=stack,
        event_chain=event_chain,
    )
    return VirtualTimeAdvanceResultV1(
        state=next_state,
        derived_deadline=derived,
        requested_tick=advance_input.requested_tick,
        applied_tick=applied_tick,
        consumed_ticks=consumed_ticks,
        unconsumed_ticks=unconsumed_ticks,
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class PublicLegalActionCandidateV1:
    schema: str
    contract_version: int
    window_id: str
    actor_id: str
    decision_identity: str
    obligation_identity: str
    public_ordinal: int
    action_id: str
    action_family: PublicActionFamilyV1
    candidate_identity: str

    def __post_init__(self) -> None:
        if self.schema != PUBLIC_ACTION_SCHEMA:
            raise C8VirtualTimeContractError("public candidate schema不匹配")
        if type(self.contract_version) is not int or self.contract_version != 1:
            raise C8VirtualTimeContractError("public candidate contract_version必须精确为1")
        _exact_text(self.window_id, "candidate.window_id")
        _exact_text(self.actor_id, "candidate.actor_id")
        _exact_sha256(self.decision_identity, "candidate.decision_identity")
        _exact_sha256(self.obligation_identity, "candidate.obligation_identity")
        _exact_int(self.public_ordinal, "candidate.public_ordinal")
        _exact_text(self.action_id, "candidate.action_id")
        if type(self.action_family) is not PublicActionFamilyV1:
            raise C8VirtualTimeContractError("candidate.action_family类型不正确")
        _assert_identity(
            self.candidate_identity, self._identity_material(), "candidate_identity"
        )

    def _identity_material(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "contract_version": self.contract_version,
            "window_id": self.window_id,
            "actor_id": self.actor_id,
            "decision_identity": self.decision_identity,
            "obligation_identity": self.obligation_identity,
            "public_ordinal": self.public_ordinal,
            "action_id": self.action_id,
            "action_family": self.action_family.value,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._identity_material(), "candidate_identity": self.candidate_identity}

    @classmethod
    def build(
        cls,
        *,
        window_id: str,
        actor_id: str,
        decision_identity: str,
        obligation_identity: str,
        public_ordinal: int,
        action_id: str,
        action_family: PublicActionFamilyV1,
    ) -> "PublicLegalActionCandidateV1":
        material = {
            "schema": PUBLIC_ACTION_SCHEMA,
            "contract_version": 1,
            "window_id": window_id,
            "actor_id": actor_id,
            "decision_identity": decision_identity,
            "obligation_identity": obligation_identity,
            "public_ordinal": public_ordinal,
            "action_id": action_id,
            "action_family": action_family.value,
        }
        return cls(
            schema=PUBLIC_ACTION_SCHEMA,
            contract_version=1,
            window_id=window_id,
            actor_id=actor_id,
            decision_identity=decision_identity,
            obligation_identity=obligation_identity,
            public_ordinal=public_ordinal,
            action_id=action_id,
            action_family=action_family,
            candidate_identity=_canonical_sha256(material),
        )

    @classmethod
    def from_dict(cls, value: object) -> "PublicLegalActionCandidateV1":
        _reject_public_leakage(value, "PublicLegalActionCandidateV1")
        data = _exact_dict(value, "PublicLegalActionCandidateV1")
        _exact_fields(
            data,
            frozenset(
                {
                    "schema", "contract_version", "window_id", "actor_id",
                    "decision_identity", "obligation_identity", "public_ordinal",
                    "action_id", "action_family", "candidate_identity",
                }
            ),
            "PublicLegalActionCandidateV1",
        )
        return cls(
            schema=_exact_text(data["schema"], "candidate.schema"),
            contract_version=_exact_int(data["contract_version"], "contract_version"),
            window_id=_exact_text(data["window_id"], "window_id"),
            actor_id=_exact_text(data["actor_id"], "actor_id"),
            decision_identity=_exact_sha256(data["decision_identity"], "decision_identity"),
            obligation_identity=_exact_sha256(
                data["obligation_identity"], "obligation_identity"
            ),
            public_ordinal=_exact_int(data["public_ordinal"], "public_ordinal"),
            action_id=_exact_text(data["action_id"], "action_id"),
            action_family=_exact_enum(
                data["action_family"], PublicActionFamilyV1, "action_family"
            ),
            candidate_identity=_exact_sha256(
                data["candidate_identity"], "candidate_identity"
            ),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class PublicLegalSetProjectionV1:
    schema: str
    contract_version: int
    window_id: str
    actor_id: str
    decision_identity: str
    obligation_identity: str
    ordering_contract_id: str
    actions: tuple[PublicLegalActionCandidateV1, ...]
    legal_set_identity: str

    def __post_init__(self) -> None:
        if self.schema != PUBLIC_LEGAL_SET_SCHEMA:
            raise C8VirtualTimeContractError("public legal set schema不匹配")
        if type(self.contract_version) is not int or self.contract_version != 1:
            raise C8VirtualTimeContractError("public legal set contract_version必须精确为1")
        _exact_text(self.window_id, "legal_set.window_id")
        _exact_text(self.actor_id, "legal_set.actor_id")
        _exact_sha256(self.decision_identity, "legal_set.decision_identity")
        _exact_sha256(self.obligation_identity, "legal_set.obligation_identity")
        if self.ordering_contract_id != PUBLIC_ORDERING_CONTRACT_ID:
            raise C8VirtualTimeContractError("public legal set ordering contract不匹配")
        if type(self.actions) is not tuple or any(
            type(item) is not PublicLegalActionCandidateV1 for item in self.actions
        ):
            raise C8VirtualTimeContractError("public legal set actions必须是strict tuple")
        expected_ordinals = tuple(range(len(self.actions)))
        if tuple(item.public_ordinal for item in self.actions) != expected_ordinals:
            raise C8VirtualTimeContractError(
                "caller必须提供已验证、连续且按序的canonical public ordinals"
            )
        action_ids = tuple(item.action_id for item in self.actions)
        candidate_ids = tuple(item.candidate_identity for item in self.actions)
        if len(action_ids) != len(set(action_ids)) or len(candidate_ids) != len(
            set(candidate_ids)
        ):
            raise C8VirtualTimeContractError("public legal set禁止重复action/candidate identity")
        for item in self.actions:
            if (
                item.window_id != self.window_id
                or item.actor_id != self.actor_id
                or item.decision_identity != self.decision_identity
                or item.obligation_identity != self.obligation_identity
            ):
                raise C8VirtualTimeContractError("public candidate未绑定legal set authority")
        _assert_identity(
            self.legal_set_identity, self._identity_material(), "legal_set_identity"
        )

    def _identity_material(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "contract_version": self.contract_version,
            "window_id": self.window_id,
            "actor_id": self.actor_id,
            "decision_identity": self.decision_identity,
            "obligation_identity": self.obligation_identity,
            "ordering_contract_id": self.ordering_contract_id,
            "actions": [item.to_dict() for item in self.actions],
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._identity_material(), "legal_set_identity": self.legal_set_identity}

    @classmethod
    def build(
        cls,
        *,
        window_id: str,
        actor_id: str,
        decision_identity: str,
        obligation_identity: str,
        actions: Sequence[PublicLegalActionCandidateV1],
        ordering_contract_id: str,
    ) -> "PublicLegalSetProjectionV1":
        if type(actions) not in (tuple, list):
            raise C8VirtualTimeContractError("actions必须是明确序列")
        items = tuple(actions)
        material = {
            "schema": PUBLIC_LEGAL_SET_SCHEMA,
            "contract_version": 1,
            "window_id": window_id,
            "actor_id": actor_id,
            "decision_identity": decision_identity,
            "obligation_identity": obligation_identity,
            "ordering_contract_id": ordering_contract_id,
            "actions": [item.to_dict() for item in items],
        }
        return cls(
            schema=PUBLIC_LEGAL_SET_SCHEMA,
            contract_version=1,
            window_id=window_id,
            actor_id=actor_id,
            decision_identity=decision_identity,
            obligation_identity=obligation_identity,
            ordering_contract_id=ordering_contract_id,
            actions=items,
            legal_set_identity=_canonical_sha256(material),
        )

    @classmethod
    def from_dict(cls, value: object) -> "PublicLegalSetProjectionV1":
        _reject_public_leakage(value, "PublicLegalSetProjectionV1")
        data = _exact_dict(value, "PublicLegalSetProjectionV1")
        _exact_fields(
            data,
            frozenset(
                {
                    "schema", "contract_version", "window_id", "actor_id",
                    "decision_identity", "obligation_identity", "ordering_contract_id",
                    "actions", "legal_set_identity",
                }
            ),
            "PublicLegalSetProjectionV1",
        )
        return cls(
            schema=_exact_text(data["schema"], "legal_set.schema"),
            contract_version=_exact_int(data["contract_version"], "contract_version"),
            window_id=_exact_text(data["window_id"], "window_id"),
            actor_id=_exact_text(data["actor_id"], "actor_id"),
            decision_identity=_exact_sha256(data["decision_identity"], "decision_identity"),
            obligation_identity=_exact_sha256(
                data["obligation_identity"], "obligation_identity"
            ),
            ordering_contract_id=_exact_text(
                data["ordering_contract_id"], "ordering_contract_id"
            ),
            actions=tuple(
                PublicLegalActionCandidateV1.from_dict(item)
                for item in _exact_list(data["actions"], "actions")
            ),
            legal_set_identity=_exact_sha256(
                data["legal_set_identity"], "legal_set_identity"
            ),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class TimeoutResolutionV1:
    schema: str
    contract_version: int
    resolution_kind: TimeoutResolutionKindV1
    reason: TimeoutResolutionReasonV1
    resolution_tick: int
    deadline_at: int
    window_id: str
    window_state_identity: str
    obligation_identity: str
    legal_set_identity: str
    policy_identity: str
    resolved_public_ordinal: int | None
    resolved_candidate_identity: str | None
    resolved_action_family: PublicActionFamilyV1 | None
    same_tick_chain_required: bool
    resolution_identity: str

    def __post_init__(self) -> None:
        if self.schema != TIMEOUT_RESOLUTION_SCHEMA:
            raise C8VirtualTimeContractError("TimeoutResolutionV1 schema不匹配")
        if type(self.contract_version) is not int or self.contract_version != 1:
            raise C8VirtualTimeContractError("timeout resolution contract_version必须精确为1")
        if type(self.resolution_kind) is not TimeoutResolutionKindV1:
            raise C8VirtualTimeContractError("resolution_kind类型不正确")
        if type(self.reason) is not TimeoutResolutionReasonV1:
            raise C8VirtualTimeContractError("resolution reason类型不正确")
        _exact_int(self.resolution_tick, "resolution_tick")
        _exact_int(self.deadline_at, "resolution.deadline_at")
        if self.resolution_kind is TimeoutResolutionKindV1.TIMEOUT_NOT_DUE:
            if self.resolution_tick >= self.deadline_at:
                raise C8VirtualTimeContractError("TIMEOUT_NOT_DUE必须严格早于deadline")
        elif self.resolution_tick != self.deadline_at:
            raise C8VirtualTimeContractError("timeout resolution只能在exact deadline产生")
        _exact_text(self.window_id, "resolution.window_id")
        _exact_sha256(self.window_state_identity, "window_state_identity")
        _exact_sha256(self.obligation_identity, "obligation_identity")
        _exact_sha256(self.legal_set_identity, "legal_set_identity")
        _exact_sha256(self.policy_identity, "policy_identity")
        if self.resolved_public_ordinal is not None:
            _exact_int(self.resolved_public_ordinal, "resolved_public_ordinal")
        if self.resolved_candidate_identity is not None:
            _exact_sha256(self.resolved_candidate_identity, "resolved_candidate_identity")
        if self.resolved_action_family is not None and type(
            self.resolved_action_family
        ) is not PublicActionFamilyV1:
            raise C8VirtualTimeContractError("resolved_action_family类型不正确")
        _exact_bool(self.same_tick_chain_required, "same_tick_chain_required")
        selected = (
            self.resolved_public_ordinal is not None
            and self.resolved_candidate_identity is not None
            and self.resolved_action_family is not None
        )
        if self.resolution_kind is TimeoutResolutionKindV1.RESOLVE_TO_PUBLIC_ACTION_ORDINAL:
            if not selected:
                raise C8VirtualTimeContractError("resolved outcome必须完整绑定public candidate")
            if self.reason not in {
                TimeoutResolutionReasonV1.EXPLICIT_FALLBACK,
                TimeoutResolutionReasonV1.UNIQUE_MANDATORY_ACTION,
                TimeoutResolutionReasonV1.CANONICAL_PUBLIC_ORDINAL,
            }:
                raise C8VirtualTimeContractError("resolved outcome reason不匹配")
        else:
            if selected or any(
                item is not None
                for item in (
                    self.resolved_public_ordinal,
                    self.resolved_candidate_identity,
                    self.resolved_action_family,
                )
            ):
                raise C8VirtualTimeContractError("non-resolved outcome不得携带candidate")
            expected_reason = (
                TimeoutResolutionReasonV1.BEFORE_DEADLINE
                if self.resolution_kind is TimeoutResolutionKindV1.TIMEOUT_NOT_DUE
                else TimeoutResolutionReasonV1.NO_SAFE_DETERMINISTIC_FALLBACK
            )
            if self.reason is not expected_reason or self.same_tick_chain_required:
                raise C8VirtualTimeContractError("non-resolved outcome semantics不匹配")
        _assert_identity(
            self.resolution_identity, self._identity_material(), "resolution_identity"
        )

    def _identity_material(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "contract_version": self.contract_version,
            "resolution_kind": self.resolution_kind.value,
            "reason": self.reason.value,
            "resolution_tick": self.resolution_tick,
            "deadline_at": self.deadline_at,
            "window_id": self.window_id,
            "window_state_identity": self.window_state_identity,
            "obligation_identity": self.obligation_identity,
            "legal_set_identity": self.legal_set_identity,
            "policy_identity": self.policy_identity,
            "resolved_public_ordinal": self.resolved_public_ordinal,
            "resolved_candidate_identity": self.resolved_candidate_identity,
            "resolved_action_family": (
                None if self.resolved_action_family is None else self.resolved_action_family.value
            ),
            "same_tick_chain_required": self.same_tick_chain_required,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._identity_material(), "resolution_identity": self.resolution_identity}

    @classmethod
    def _build(
        cls,
        *,
        resolution_kind: TimeoutResolutionKindV1,
        reason: TimeoutResolutionReasonV1,
        current_tick: int,
        window: TimedDecisionWindowV1,
        legal_set: PublicLegalSetProjectionV1,
        policy: TimeoutFallbackPolicyV1,
        candidate: PublicLegalActionCandidateV1 | None,
        same_tick_chain_required: bool,
    ) -> "TimeoutResolutionV1":
        if type(window) is not TimedDecisionWindowV1:
            raise C8VirtualTimeContractError("resolution window类型不正确")
        if type(legal_set) is not PublicLegalSetProjectionV1:
            raise C8VirtualTimeContractError("resolution legal_set类型不正确")
        if type(policy) is not TimeoutFallbackPolicyV1:
            raise C8VirtualTimeContractError("resolution policy类型不正确")
        if type(resolution_kind) is not TimeoutResolutionKindV1:
            raise C8VirtualTimeContractError("resolution_kind类型不正确")
        if type(reason) is not TimeoutResolutionReasonV1:
            raise C8VirtualTimeContractError("resolution reason类型不正确")
        tick = _exact_int(current_tick, "resolution current_tick")
        if resolution_kind is TimeoutResolutionKindV1.TIMEOUT_NOT_DUE:
            if tick >= window.deadline_at:
                raise C8VirtualTimeContractError("TIMEOUT_NOT_DUE必须严格早于deadline")
        elif tick != window.deadline_at:
            raise C8VirtualTimeContractError("timeout resolution只能在exact deadline产生")
        if (
            legal_set.window_id != window.window_id
            or legal_set.actor_id != window.actor_id
            or legal_set.decision_identity != window.decision_identity
            or legal_set.obligation_identity != window.obligation_identity
        ):
            raise C8VirtualTimeContractError("resolution legal set与window binding不一致")
        if (
            policy.window_kind is not window.window_kind
            or policy.policy_identity != window.fallback_policy_identity
        ):
            raise C8VirtualTimeContractError("resolution policy与window binding不一致")
        if candidate is not None:
            if type(candidate) is not PublicLegalActionCandidateV1:
                raise C8VirtualTimeContractError("resolution candidate类型不正确")
            ordinal = candidate.public_ordinal
            if ordinal >= len(legal_set.actions) or legal_set.actions[ordinal] != candidate:
                raise C8VirtualTimeContractError(
                    "resolution candidate不是legal set中该public ordinal的成员"
                )
        material = {
            "schema": TIMEOUT_RESOLUTION_SCHEMA,
            "contract_version": 1,
            "resolution_kind": resolution_kind.value,
            "reason": reason.value,
            "resolution_tick": tick,
            "deadline_at": window.deadline_at,
            "window_id": window.window_id,
            "window_state_identity": window.window_state_identity,
            "obligation_identity": window.obligation_identity,
            "legal_set_identity": legal_set.legal_set_identity,
            "policy_identity": policy.policy_identity,
            "resolved_public_ordinal": None if candidate is None else candidate.public_ordinal,
            "resolved_candidate_identity": (
                None if candidate is None else candidate.candidate_identity
            ),
            "resolved_action_family": None if candidate is None else candidate.action_family.value,
            "same_tick_chain_required": same_tick_chain_required,
        }
        return cls(
            schema=TIMEOUT_RESOLUTION_SCHEMA,
            contract_version=1,
            resolution_kind=resolution_kind,
            reason=reason,
            resolution_tick=tick,
            deadline_at=window.deadline_at,
            window_id=window.window_id,
            window_state_identity=window.window_state_identity,
            obligation_identity=window.obligation_identity,
            legal_set_identity=legal_set.legal_set_identity,
            policy_identity=policy.policy_identity,
            resolved_public_ordinal=None if candidate is None else candidate.public_ordinal,
            resolved_candidate_identity=None if candidate is None else candidate.candidate_identity,
            resolved_action_family=None if candidate is None else candidate.action_family,
            same_tick_chain_required=same_tick_chain_required,
            resolution_identity=_canonical_sha256(material),
        )

    @classmethod
    def from_dict(
        cls,
        value: object,
        *,
        window: TimedDecisionWindowV1,
        current_tick: int,
        public_legal_set: PublicLegalSetProjectionV1,
        fallback_policy: TimeoutFallbackPolicyV1,
    ) -> "TimeoutResolutionV1":
        data = _exact_dict(value, "TimeoutResolutionV1")
        expected = resolve_timeout_v1(
            window,
            current_tick,
            public_legal_set,
            fallback_policy,
        )
        _exact_fields(
            data,
            frozenset(expected.to_dict()),
            "TimeoutResolutionV1",
        )
        if not _strict_json_equal(data, expected.to_dict()):
            raise C8VirtualTimeContractError(
                "serialized TimeoutResolutionV1与fresh resolver结果不一致"
            )
        return expected


def resolve_timeout_v1(
    window: TimedDecisionWindowV1,
    current_tick: int,
    public_legal_set: PublicLegalSetProjectionV1,
    fallback_policy: TimeoutFallbackPolicyV1,
) -> TimeoutResolutionV1:
    """Return a pure public decision; never inspect or mutate inner game state."""

    if type(window) is not TimedDecisionWindowV1:
        raise C8VirtualTimeContractError("resolver window类型不正确")
    tick = _exact_int(current_tick, "current_tick")
    if type(public_legal_set) is not PublicLegalSetProjectionV1:
        raise C8VirtualTimeContractError("resolver public_legal_set类型不正确")
    if type(fallback_policy) is not TimeoutFallbackPolicyV1:
        raise C8VirtualTimeContractError("resolver fallback_policy类型不正确")
    if window.status is not TimedWindowStatusV1.ACTIVE:
        raise C8VirtualTimeContractError("resolver只能处理ACTIVE window")
    if (
        public_legal_set.window_id != window.window_id
        or public_legal_set.actor_id != window.actor_id
        or public_legal_set.decision_identity != window.decision_identity
        or public_legal_set.obligation_identity != window.obligation_identity
    ):
        raise C8VirtualTimeContractError("public legal set与window authority binding不一致")
    if fallback_policy.window_kind is not window.window_kind:
        raise C8VirtualTimeContractError("fallback policy与window kind不一致")
    if fallback_policy.policy_identity != window.fallback_policy_identity:
        raise C8VirtualTimeContractError("fallback policy identity与window binding不一致")
    if window.remaining_ticks != max(window.deadline_at - tick, 0):
        raise C8VirtualTimeContractError(
            "resolver current window remaining_ticks与current_tick不一致"
        )
    if tick > window.deadline_at:
        raise C8VirtualTimeContractError("authoritative resolver tick不得越过deadline")
    if tick < window.deadline_at:
        return TimeoutResolutionV1._build(
            resolution_kind=TimeoutResolutionKindV1.TIMEOUT_NOT_DUE,
            reason=TimeoutResolutionReasonV1.BEFORE_DEADLINE,
            current_tick=tick,
            window=window,
            legal_set=public_legal_set,
            policy=fallback_policy,
            candidate=None,
            same_tick_chain_required=False,
        )

    candidate: PublicLegalActionCandidateV1 | None = None
    reason = TimeoutResolutionReasonV1.NO_SAFE_DETERMINISTIC_FALLBACK
    if fallback_policy.selector is TimeoutFallbackSelectorV1.EXPLICIT_ACTION_FAMILY:
        family = fallback_policy.allowed_action_families[0]
        matches = tuple(
            item for item in public_legal_set.actions if item.action_family is family
        )
        if len(matches) == 1:
            candidate = matches[0]
            reason = TimeoutResolutionReasonV1.EXPLICIT_FALLBACK
    elif fallback_policy.selector is TimeoutFallbackSelectorV1.UNIQUE_LEGAL_ACTION:
        if len(public_legal_set.actions) == 1:
            candidate = public_legal_set.actions[0]
            reason = TimeoutResolutionReasonV1.UNIQUE_MANDATORY_ACTION
    elif fallback_policy.selector is TimeoutFallbackSelectorV1.CANONICAL_PUBLIC_ORDINAL:
        if (
            public_legal_set.ordering_contract_id == fallback_policy.ordering_contract_id
            and public_legal_set.actions
            and all(
                item.action_family is PublicActionFamilyV1.PUBLIC_CHOICE
                for item in public_legal_set.actions
            )
        ):
            candidate = public_legal_set.actions[0]
            reason = TimeoutResolutionReasonV1.CANONICAL_PUBLIC_ORDINAL
    else:
        explicit_matches = tuple(
            item
            for item in public_legal_set.actions
            if item.action_family in fallback_policy.allowed_action_families
        )
        if len(explicit_matches) == 1:
            candidate = explicit_matches[0]
            reason = TimeoutResolutionReasonV1.EXPLICIT_FALLBACK
        elif not explicit_matches and len(public_legal_set.actions) == 1:
            candidate = public_legal_set.actions[0]
            reason = TimeoutResolutionReasonV1.UNIQUE_MANDATORY_ACTION
        elif (
            not explicit_matches
            and public_legal_set.ordering_contract_id
            == fallback_policy.ordering_contract_id
            and public_legal_set.actions
            and all(
                item.action_family is PublicActionFamilyV1.PUBLIC_CHOICE
                for item in public_legal_set.actions
            )
        ):
            candidate = public_legal_set.actions[0]
            reason = TimeoutResolutionReasonV1.CANONICAL_PUBLIC_ORDINAL

    if candidate is None:
        return TimeoutResolutionV1._build(
            resolution_kind=TimeoutResolutionKindV1.TIMEOUT_UNRESOLVED,
            reason=TimeoutResolutionReasonV1.NO_SAFE_DETERMINISTIC_FALLBACK,
            current_tick=tick,
            window=window,
            legal_set=public_legal_set,
            policy=fallback_policy,
            candidate=None,
            same_tick_chain_required=False,
        )
    return TimeoutResolutionV1._build(
        resolution_kind=TimeoutResolutionKindV1.RESOLVE_TO_PUBLIC_ACTION_ORDINAL,
        reason=reason,
        current_tick=tick,
        window=window,
        legal_set=public_legal_set,
        policy=fallback_policy,
        candidate=candidate,
        same_tick_chain_required=fallback_policy.same_tick_chain_required,
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class SameTickFallbackChainContractV1:
    schema: str
    contract_version: int
    contract_id: str
    max_steps: int
    same_tick_required: bool
    fresh_legal_set_required: bool
    normal_step_required: bool
    deadline_refresh_forbidden: bool
    contract_identity: str

    def __post_init__(self) -> None:
        if self.schema != SAME_TICK_CHAIN_CONTRACT_SCHEMA:
            raise C8VirtualTimeContractError("same-tick chain contract schema不匹配")
        if type(self.contract_version) is not int or self.contract_version != 1:
            raise C8VirtualTimeContractError("same-tick contract_version必须精确为1")
        if self.contract_id != SAME_TICK_CHAIN_CONTRACT_ID:
            raise C8VirtualTimeContractError("same-tick chain contract_id不匹配")
        _exact_int(self.max_steps, "same-tick chain max_steps", minimum=1)
        if self.max_steps != SAME_TICK_FALLBACK_CHAIN_MAX_STEPS:
            raise C8VirtualTimeContractError("same-tick chain max_steps不匹配")
        for label, flag in (
            ("same_tick_required", self.same_tick_required),
            ("fresh_legal_set_required", self.fresh_legal_set_required),
            ("normal_step_required", self.normal_step_required),
            ("deadline_refresh_forbidden", self.deadline_refresh_forbidden),
        ):
            if type(flag) is not bool or not flag:
                raise C8VirtualTimeContractError(f"{label}必须精确为true")
        _assert_identity(
            self.contract_identity, self._identity_material(), "chain contract_identity"
        )

    def _identity_material(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "contract_version": self.contract_version,
            "contract_id": self.contract_id,
            "max_steps": self.max_steps,
            "same_tick_required": self.same_tick_required,
            "fresh_legal_set_required": self.fresh_legal_set_required,
            "normal_step_required": self.normal_step_required,
            "deadline_refresh_forbidden": self.deadline_refresh_forbidden,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._identity_material(), "contract_identity": self.contract_identity}

    @classmethod
    def canonical(cls) -> "SameTickFallbackChainContractV1":
        material = {
            "schema": SAME_TICK_CHAIN_CONTRACT_SCHEMA,
            "contract_version": 1,
            "contract_id": SAME_TICK_CHAIN_CONTRACT_ID,
            "max_steps": SAME_TICK_FALLBACK_CHAIN_MAX_STEPS,
            "same_tick_required": True,
            "fresh_legal_set_required": True,
            "normal_step_required": True,
            "deadline_refresh_forbidden": True,
        }
        return cls(
            schema=SAME_TICK_CHAIN_CONTRACT_SCHEMA,
            contract_version=1,
            contract_id=SAME_TICK_CHAIN_CONTRACT_ID,
            max_steps=SAME_TICK_FALLBACK_CHAIN_MAX_STEPS,
            same_tick_required=True,
            fresh_legal_set_required=True,
            normal_step_required=True,
            deadline_refresh_forbidden=True,
            contract_identity=_canonical_sha256(material),
        )

    @classmethod
    def from_dict(cls, value: object) -> "SameTickFallbackChainContractV1":
        data = _exact_dict(value, "SameTickFallbackChainContractV1")
        expected = cls.canonical()
        _exact_fields(data, frozenset(expected.to_dict()), "SameTickFallbackChainContractV1")
        if not _strict_json_equal(data, expected.to_dict()):
            raise C8VirtualTimeContractError("same-tick chain contract与canonical contract不一致")
        return expected


SAME_TICK_FALLBACK_CHAIN_CONTRACT_V1 = SameTickFallbackChainContractV1.canonical()


@dataclass(frozen=True, slots=True, kw_only=True)
class SameTickFallbackChainStepV1:
    schema: str
    contract_version: int
    step_index: int
    tick: int
    window_id: str
    obligation_identity: str
    legal_set_identity: str
    resolution_identity: str
    resolved_public_ordinal: int
    step_identity: str

    def __post_init__(self) -> None:
        if self.schema != SAME_TICK_CHAIN_STEP_SCHEMA:
            raise C8VirtualTimeContractError("same-tick chain step schema不匹配")
        if type(self.contract_version) is not int or self.contract_version != 1:
            raise C8VirtualTimeContractError("chain step contract_version必须精确为1")
        _exact_int(self.step_index, "step_index")
        _exact_int(self.tick, "step.tick")
        _exact_text(self.window_id, "step.window_id")
        _exact_sha256(self.obligation_identity, "step.obligation_identity")
        _exact_sha256(self.legal_set_identity, "step.legal_set_identity")
        _exact_sha256(self.resolution_identity, "step.resolution_identity")
        _exact_int(self.resolved_public_ordinal, "step.resolved_public_ordinal")
        _assert_identity(self.step_identity, self._identity_material(), "step_identity")

    def _identity_material(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "contract_version": self.contract_version,
            "step_index": self.step_index,
            "tick": self.tick,
            "window_id": self.window_id,
            "obligation_identity": self.obligation_identity,
            "legal_set_identity": self.legal_set_identity,
            "resolution_identity": self.resolution_identity,
            "resolved_public_ordinal": self.resolved_public_ordinal,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._identity_material(), "step_identity": self.step_identity}

    @classmethod
    def build(
        cls,
        *,
        step_index: int,
        tick: int,
        window_id: str,
        obligation_identity: str,
        legal_set_identity: str,
        resolution_identity: str,
        resolved_public_ordinal: int,
    ) -> "SameTickFallbackChainStepV1":
        material = {
            "schema": SAME_TICK_CHAIN_STEP_SCHEMA,
            "contract_version": 1,
            "step_index": step_index,
            "tick": tick,
            "window_id": window_id,
            "obligation_identity": obligation_identity,
            "legal_set_identity": legal_set_identity,
            "resolution_identity": resolution_identity,
            "resolved_public_ordinal": resolved_public_ordinal,
        }
        return cls(
            schema=SAME_TICK_CHAIN_STEP_SCHEMA,
            contract_version=1,
            step_index=step_index,
            tick=tick,
            window_id=window_id,
            obligation_identity=obligation_identity,
            legal_set_identity=legal_set_identity,
            resolution_identity=resolution_identity,
            resolved_public_ordinal=resolved_public_ordinal,
            step_identity=_canonical_sha256(material),
        )

    @classmethod
    def from_dict(cls, value: object) -> "SameTickFallbackChainStepV1":
        data = _exact_dict(value, "SameTickFallbackChainStepV1")
        _exact_fields(
            data,
            frozenset(
                {
                    "schema", "contract_version", "step_index", "tick", "window_id",
                    "obligation_identity", "legal_set_identity", "resolution_identity",
                    "resolved_public_ordinal", "step_identity",
                }
            ),
            "SameTickFallbackChainStepV1",
        )
        return cls(
            schema=_exact_text(data["schema"], "step.schema"),
            contract_version=_exact_int(data["contract_version"], "contract_version"),
            step_index=_exact_int(data["step_index"], "step_index"),
            tick=_exact_int(data["tick"], "tick"),
            window_id=_exact_text(data["window_id"], "window_id"),
            obligation_identity=_exact_sha256(
                data["obligation_identity"], "obligation_identity"
            ),
            legal_set_identity=_exact_sha256(
                data["legal_set_identity"], "legal_set_identity"
            ),
            resolution_identity=_exact_sha256(
                data["resolution_identity"], "resolution_identity"
            ),
            resolved_public_ordinal=_exact_int(
                data["resolved_public_ordinal"], "resolved_public_ordinal"
            ),
            step_identity=_exact_sha256(data["step_identity"], "step_identity"),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class BoundedSameTickFallbackChainV1:
    schema: str
    contract_version: int
    chain_id: str
    chain_contract_identity: str
    window_id: str
    actor_id: str
    decision_identity: str
    obligation_identity: str
    window_state_identity: str
    fallback_policy_identity: str
    deadline_event_identity: str
    timeout_tick: int
    next_step_index: int
    status: SameTickFallbackChainStatusV1
    termination_reason: SameTickFallbackTerminationV1 | None
    seen_legal_set_identities: tuple[str, ...]
    steps: tuple[SameTickFallbackChainStepV1, ...]
    chain_identity: str

    def __post_init__(self) -> None:
        if self.schema != SAME_TICK_CHAIN_SCHEMA:
            raise C8VirtualTimeContractError("same-tick chain schema不匹配")
        if type(self.contract_version) is not int or self.contract_version != 1:
            raise C8VirtualTimeContractError("same-tick chain contract_version必须精确为1")
        if _CHAIN_ID_RE.fullmatch(self.chain_id) is None:
            raise C8VirtualTimeContractError("chain_id格式不正确")
        _exact_sha256(self.chain_contract_identity, "chain_contract_identity")
        if (
            self.chain_contract_identity
            != SAME_TICK_FALLBACK_CHAIN_CONTRACT_V1.contract_identity
        ):
            raise C8VirtualTimeContractError("chain必须绑定frozen C8-A chain contract")
        _exact_text(self.window_id, "chain.window_id")
        _exact_text(self.actor_id, "chain.actor_id")
        _exact_sha256(self.decision_identity, "chain.decision_identity")
        _exact_sha256(self.obligation_identity, "chain.obligation_identity")
        _exact_sha256(self.window_state_identity, "chain.window_state_identity")
        _exact_sha256(
            self.fallback_policy_identity, "chain.fallback_policy_identity"
        )
        _exact_sha256(self.deadline_event_identity, "chain.deadline_event_identity")
        _exact_int(self.timeout_tick, "timeout_tick")
        _exact_int(self.next_step_index, "next_step_index")
        if type(self.status) is not SameTickFallbackChainStatusV1:
            raise C8VirtualTimeContractError("chain status类型不正确")
        if self.termination_reason is not None and type(
            self.termination_reason
        ) is not SameTickFallbackTerminationV1:
            raise C8VirtualTimeContractError("termination_reason类型不正确")
        if (self.status is SameTickFallbackChainStatusV1.ACTIVE) != (
            self.termination_reason is None
        ):
            raise C8VirtualTimeContractError("chain status与termination_reason不一致")
        if type(self.seen_legal_set_identities) is not tuple:
            raise C8VirtualTimeContractError("seen legal-set identities必须是strict tuple")
        for value in self.seen_legal_set_identities:
            _exact_sha256(value, "seen legal-set identity")
        if len(self.seen_legal_set_identities) != len(
            set(self.seen_legal_set_identities)
        ):
            raise C8VirtualTimeContractError("same-tick chain禁止复用legal-set identity")
        if type(self.steps) is not tuple or any(
            type(item) is not SameTickFallbackChainStepV1 for item in self.steps
        ):
            raise C8VirtualTimeContractError("chain steps必须是strict tuple")
        if self.next_step_index != len(self.steps):
            raise C8VirtualTimeContractError("next_step_index与steps长度不一致")
        if len(self.steps) > SAME_TICK_FALLBACK_CHAIN_MAX_STEPS:
            raise C8VirtualTimeContractError("same-tick chain超过hard cap")
        if self.seen_legal_set_identities != tuple(
            item.legal_set_identity for item in self.steps
        ):
            raise C8VirtualTimeContractError("seen legal-set identities与steps不一致")
        for index, step in enumerate(self.steps):
            if (
                step.step_index != index
                or step.tick != self.timeout_tick
                or step.window_id != self.window_id
                or step.obligation_identity != self.obligation_identity
            ):
                raise C8VirtualTimeContractError("same-tick chain step authority binding不一致")
        expected_id = f"c8chain-{_canonical_sha256(self._chain_id_material())[:32]}"
        if self.chain_id != expected_id:
            raise C8VirtualTimeContractError("chain_id与binding不一致")
        _assert_identity(self.chain_identity, self._identity_material(), "chain_identity")

    def _chain_id_material(self) -> dict[str, object]:
        return {
            "chain_contract_identity": self.chain_contract_identity,
            "window_id": self.window_id,
            "actor_id": self.actor_id,
            "decision_identity": self.decision_identity,
            "obligation_identity": self.obligation_identity,
            "window_state_identity": self.window_state_identity,
            "fallback_policy_identity": self.fallback_policy_identity,
            "deadline_event_identity": self.deadline_event_identity,
            "timeout_tick": self.timeout_tick,
        }

    def _identity_material(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "contract_version": self.contract_version,
            "chain_id": self.chain_id,
            "chain_contract_identity": self.chain_contract_identity,
            "window_id": self.window_id,
            "actor_id": self.actor_id,
            "decision_identity": self.decision_identity,
            "obligation_identity": self.obligation_identity,
            "window_state_identity": self.window_state_identity,
            "fallback_policy_identity": self.fallback_policy_identity,
            "deadline_event_identity": self.deadline_event_identity,
            "timeout_tick": self.timeout_tick,
            "next_step_index": self.next_step_index,
            "status": self.status.value,
            "termination_reason": (
                None if self.termination_reason is None else self.termination_reason.value
            ),
            "seen_legal_set_identities": list(self.seen_legal_set_identities),
            "steps": [item.to_dict() for item in self.steps],
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._identity_material(), "chain_identity": self.chain_identity}

    def validate_deadline_state(
        self, deadline_state: VirtualTimeStateV1
    ) -> None:
        if type(deadline_state) is not VirtualTimeStateV1:
            raise C8VirtualTimeContractError("chain deadline_state类型不正确")
        active = deadline_state.window_stack.active_window
        if (
            deadline_state.globally_paused
            or active is None
            or active.status is not TimedWindowStatusV1.ACTIVE
            or active.window_kind is not TimedWindowKindV1.MULTI_STEP_OBLIGATION
            or active.remaining_ticks != 0
            or deadline_state.now_tick != active.deadline_at
            or self.timeout_tick != deadline_state.now_tick
            or self.window_id != active.window_id
            or self.actor_id != active.actor_id
            or self.decision_identity != active.decision_identity
            or self.obligation_identity != active.obligation_identity
            or self.window_state_identity != active.window_state_identity
            or self.fallback_policy_identity != active.fallback_policy_identity
            or self.deadline_event_identity != deadline_state.event_chain_tip
            or not deadline_state.event_chain
        ):
            raise C8VirtualTimeContractError(
                "fallback chain未绑定current authoritative deadline state"
            )

    @classmethod
    def _build(
        cls,
        *,
        chain_contract_identity: str,
        window_id: str,
        actor_id: str,
        decision_identity: str,
        obligation_identity: str,
        window_state_identity: str,
        fallback_policy_identity: str,
        deadline_event_identity: str,
        timeout_tick: int,
        status: SameTickFallbackChainStatusV1,
        termination_reason: SameTickFallbackTerminationV1 | None,
        steps: tuple[SameTickFallbackChainStepV1, ...],
    ) -> "BoundedSameTickFallbackChainV1":
        base = {
            "chain_contract_identity": chain_contract_identity,
            "window_id": window_id,
            "actor_id": actor_id,
            "decision_identity": decision_identity,
            "obligation_identity": obligation_identity,
            "window_state_identity": window_state_identity,
            "fallback_policy_identity": fallback_policy_identity,
            "deadline_event_identity": deadline_event_identity,
            "timeout_tick": timeout_tick,
        }
        chain_id = f"c8chain-{_canonical_sha256(base)[:32]}"
        material = {
            "schema": SAME_TICK_CHAIN_SCHEMA,
            "contract_version": 1,
            "chain_id": chain_id,
            **base,
            "next_step_index": len(steps),
            "status": status.value,
            "termination_reason": (
                None if termination_reason is None else termination_reason.value
            ),
            "seen_legal_set_identities": [item.legal_set_identity for item in steps],
            "steps": [item.to_dict() for item in steps],
        }
        return cls(
            schema=SAME_TICK_CHAIN_SCHEMA,
            contract_version=1,
            chain_id=chain_id,
            chain_contract_identity=chain_contract_identity,
            window_id=window_id,
            actor_id=actor_id,
            decision_identity=decision_identity,
            obligation_identity=obligation_identity,
            window_state_identity=window_state_identity,
            fallback_policy_identity=fallback_policy_identity,
            deadline_event_identity=deadline_event_identity,
            timeout_tick=timeout_tick,
            next_step_index=len(steps),
            status=status,
            termination_reason=termination_reason,
            seen_legal_set_identities=tuple(item.legal_set_identity for item in steps),
            steps=steps,
            chain_identity=_canonical_sha256(material),
        )

    @classmethod
    def start(
        cls,
        *,
        deadline_state: VirtualTimeStateV1,
        derived_deadline: DerivedDeadlineReachedV1,
        chain_contract: SameTickFallbackChainContractV1,
    ) -> "BoundedSameTickFallbackChainV1":
        if type(deadline_state) is not VirtualTimeStateV1:
            raise C8VirtualTimeContractError("chain start deadline_state类型不正确")
        if type(derived_deadline) is not DerivedDeadlineReachedV1:
            raise C8VirtualTimeContractError("chain start derived_deadline类型不正确")
        window = deadline_state.window_stack.active_window
        if (
            deadline_state.globally_paused
            or window is None
            or window.status is not TimedWindowStatusV1.ACTIVE
        ):
            raise C8VirtualTimeContractError("chain start需要未暂停的ACTIVE top window")
        if window.window_kind is not TimedWindowKindV1.MULTI_STEP_OBLIGATION:
            raise C8VirtualTimeContractError("same-tick chain只允许multi-step obligation")
        tick = deadline_state.now_tick
        if tick != window.deadline_at or window.remaining_ticks != 0:
            raise C8VirtualTimeContractError(
                "fallback chain只能在预算耗尽的exact deadline启动"
            )
        if (
            not deadline_state.event_chain
            or deadline_state.event_chain_tip != derived_deadline.event_identity
            or derived_deadline.window_id != window.window_id
            or derived_deadline.actor_id != window.actor_id
            or derived_deadline.window_kind is not window.window_kind
            or derived_deadline.deadline_at != window.deadline_at
            or derived_deadline.reached_at != tick
            or derived_deadline.duration_profile_identity
            != window.duration_profile_identity
            or derived_deadline.fallback_policy_identity
            != window.fallback_policy_identity
        ):
            raise C8VirtualTimeContractError(
                "fallback chain未绑定current derived deadline event"
            )
        if chain_contract != SAME_TICK_FALLBACK_CHAIN_CONTRACT_V1:
            raise C8VirtualTimeContractError("chain contract不是frozen C8-A contract")
        return cls._build(
            chain_contract_identity=chain_contract.contract_identity,
            window_id=window.window_id,
            actor_id=window.actor_id,
            decision_identity=window.decision_identity,
            obligation_identity=window.obligation_identity,
            window_state_identity=window.window_state_identity,
            fallback_policy_identity=window.fallback_policy_identity,
            deadline_event_identity=derived_deadline.event_identity,
            timeout_tick=tick,
            status=SameTickFallbackChainStatusV1.ACTIVE,
            termination_reason=None,
            steps=(),
        )

    def append_resolution(
        self,
        *,
        resolution: TimeoutResolutionV1,
        public_legal_set: PublicLegalSetProjectionV1,
        deadline_state: VirtualTimeStateV1,
        current_tick: int,
        chain_contract: SameTickFallbackChainContractV1,
    ) -> "BoundedSameTickFallbackChainV1":
        if self.status is not SameTickFallbackChainStatusV1.ACTIVE:
            raise C8VirtualTimeContractError("terminated fallback chain不得继续")
        if type(chain_contract) is not SameTickFallbackChainContractV1:
            raise C8VirtualTimeContractError("fallback chain contract类型不正确")
        if (
            chain_contract != SAME_TICK_FALLBACK_CHAIN_CONTRACT_V1
            or chain_contract.contract_identity != self.chain_contract_identity
        ):
            raise C8VirtualTimeContractError("fallback chain contract identity drift")
        if self.next_step_index >= chain_contract.max_steps:
            raise C8VirtualTimeContractError("fallback chain达到hard cap")
        self.validate_deadline_state(deadline_state)
        if type(resolution) is not TimeoutResolutionV1 or type(
            public_legal_set
        ) is not PublicLegalSetProjectionV1:
            raise C8VirtualTimeContractError("chain resolution/legal set类型不正确")
        tick = _exact_int(current_tick, "fallback chain current_tick")
        if tick != self.timeout_tick:
            raise C8VirtualTimeContractError("fallback chain所有步骤必须保持same tick")
        if (
            resolution.resolution_kind
            is not TimeoutResolutionKindV1.RESOLVE_TO_PUBLIC_ACTION_ORDINAL
            or not resolution.same_tick_chain_required
            or resolution.window_id != self.window_id
            or resolution.window_state_identity != self.window_state_identity
            or resolution.obligation_identity != self.obligation_identity
            or resolution.policy_identity != self.fallback_policy_identity
            or resolution.resolution_tick != self.timeout_tick
            or resolution.legal_set_identity != public_legal_set.legal_set_identity
        ):
            raise C8VirtualTimeContractError("resolution未绑定当前same-tick chain")
        if (
            public_legal_set.window_id != self.window_id
            or public_legal_set.actor_id != self.actor_id
            or public_legal_set.decision_identity != self.decision_identity
            or public_legal_set.obligation_identity != self.obligation_identity
        ):
            raise C8VirtualTimeContractError(
                "public legal set未绑定当前same-tick chain"
            )
        active = deadline_state.window_stack.active_window
        assert active is not None
        expected_resolution = resolve_timeout_v1(
            active,
            tick,
            public_legal_set,
            TIMEOUT_FALLBACK_POLICY_BY_KIND_V1[active.window_kind],
        )
        if not _strict_json_equal(
            resolution.to_dict(), expected_resolution.to_dict()
        ):
            raise C8VirtualTimeContractError(
                "resolution不是current public legal set的fresh resolver结果"
            )
        if public_legal_set.legal_set_identity in self.seen_legal_set_identities:
            raise C8VirtualTimeContractError("每个fallback step必须fresh legal_actions projection")
        assert resolution.resolved_public_ordinal is not None
        ordinal = resolution.resolved_public_ordinal
        if ordinal >= len(public_legal_set.actions):
            raise C8VirtualTimeContractError("resolution public ordinal超出legal set")
        selected = public_legal_set.actions[ordinal]
        if (
            resolution.resolved_candidate_identity != selected.candidate_identity
            or resolution.resolved_action_family is not selected.action_family
        ):
            raise C8VirtualTimeContractError("resolution candidate未绑定legal set成员")
        step = SameTickFallbackChainStepV1.build(
            step_index=self.next_step_index,
            tick=current_tick,
            window_id=self.window_id,
            obligation_identity=self.obligation_identity,
            legal_set_identity=public_legal_set.legal_set_identity,
            resolution_identity=resolution.resolution_identity,
            resolved_public_ordinal=resolution.resolved_public_ordinal,
        )
        return self._build(
            chain_contract_identity=self.chain_contract_identity,
            window_id=self.window_id,
            actor_id=self.actor_id,
            decision_identity=self.decision_identity,
            obligation_identity=self.obligation_identity,
            window_state_identity=self.window_state_identity,
            fallback_policy_identity=self.fallback_policy_identity,
            deadline_event_identity=self.deadline_event_identity,
            timeout_tick=self.timeout_tick,
            status=self.status,
            termination_reason=None,
            steps=self.steps + (step,),
        )

    def terminate(
        self, reason: SameTickFallbackTerminationV1
    ) -> "BoundedSameTickFallbackChainV1":
        if self.status is not SameTickFallbackChainStatusV1.ACTIVE:
            raise C8VirtualTimeContractError("fallback chain已经终止")
        if type(reason) is not SameTickFallbackTerminationV1:
            raise C8VirtualTimeContractError("termination reason类型不正确")
        return self._build(
            chain_contract_identity=self.chain_contract_identity,
            window_id=self.window_id,
            actor_id=self.actor_id,
            decision_identity=self.decision_identity,
            obligation_identity=self.obligation_identity,
            window_state_identity=self.window_state_identity,
            fallback_policy_identity=self.fallback_policy_identity,
            deadline_event_identity=self.deadline_event_identity,
            timeout_tick=self.timeout_tick,
            status=SameTickFallbackChainStatusV1.TERMINATED,
            termination_reason=reason,
            steps=self.steps,
        )

    @classmethod
    def from_dict(
        cls,
        value: object,
        *,
        deadline_state: VirtualTimeStateV1,
    ) -> "BoundedSameTickFallbackChainV1":
        data = _exact_dict(value, "BoundedSameTickFallbackChainV1")
        _exact_fields(
            data,
            frozenset(
                {
                    "schema", "contract_version", "chain_id", "chain_contract_identity",
                    "window_id", "actor_id", "decision_identity",
                    "obligation_identity", "window_state_identity",
                    "fallback_policy_identity", "deadline_event_identity",
                    "timeout_tick", "next_step_index", "status",
                    "termination_reason", "seen_legal_set_identities",
                    "steps", "chain_identity",
                }
            ),
            "BoundedSameTickFallbackChainV1",
        )
        termination_raw = data["termination_reason"]
        parsed = cls(
            schema=_exact_text(data["schema"], "chain.schema"),
            contract_version=_exact_int(data["contract_version"], "contract_version"),
            chain_id=_exact_text(data["chain_id"], "chain_id"),
            chain_contract_identity=_exact_sha256(
                data["chain_contract_identity"], "chain_contract_identity"
            ),
            window_id=_exact_text(data["window_id"], "window_id"),
            actor_id=_exact_text(data["actor_id"], "actor_id"),
            decision_identity=_exact_sha256(
                data["decision_identity"], "decision_identity"
            ),
            obligation_identity=_exact_sha256(
                data["obligation_identity"], "obligation_identity"
            ),
            window_state_identity=_exact_sha256(
                data["window_state_identity"], "window_state_identity"
            ),
            fallback_policy_identity=_exact_sha256(
                data["fallback_policy_identity"], "fallback_policy_identity"
            ),
            deadline_event_identity=_exact_sha256(
                data["deadline_event_identity"], "deadline_event_identity"
            ),
            timeout_tick=_exact_int(data["timeout_tick"], "timeout_tick"),
            next_step_index=_exact_int(data["next_step_index"], "next_step_index"),
            status=_exact_enum(
                data["status"], SameTickFallbackChainStatusV1, "chain.status"
            ),
            termination_reason=(
                None
                if termination_raw is None
                else _exact_enum(
                    termination_raw,
                    SameTickFallbackTerminationV1,
                    "termination_reason",
                )
            ),
            seen_legal_set_identities=tuple(
                _exact_sha256(item, "seen_legal_set_identities[]")
                for item in _exact_list(
                    data["seen_legal_set_identities"], "seen_legal_set_identities"
                )
            ),
            steps=tuple(
                SameTickFallbackChainStepV1.from_dict(item)
                for item in _exact_list(data["steps"], "steps")
            ),
            chain_identity=_exact_sha256(data["chain_identity"], "chain_identity"),
        )
        parsed.validate_deadline_state(deadline_state)
        return parsed


@dataclass(frozen=True, slots=True, kw_only=True)
class VirtualTimeTransactionSnapshotV1:
    schema: str
    contract_version: int
    virtual_time_state: VirtualTimeStateV1
    clock_event_chain: tuple[str, ...]
    active_fallback_chain: BoundedSameTickFallbackChainV1 | None
    snapshot_identity: str

    def __post_init__(self) -> None:
        if self.schema != TRANSACTION_SNAPSHOT_SCHEMA:
            raise C8VirtualTimeContractError("transaction snapshot schema不匹配")
        if type(self.contract_version) is not int or self.contract_version != 1:
            raise C8VirtualTimeContractError("snapshot contract_version必须精确为1")
        if type(self.virtual_time_state) is not VirtualTimeStateV1:
            raise C8VirtualTimeContractError("snapshot virtual_time_state类型不正确")
        if type(self.clock_event_chain) is not tuple:
            raise C8VirtualTimeContractError("snapshot event chain必须是strict tuple")
        for identity in self.clock_event_chain:
            _exact_sha256(identity, "snapshot clock event identity")
        if self.clock_event_chain != self.virtual_time_state.event_chain:
            raise C8VirtualTimeContractError("snapshot event chain与clock state不一致")
        if self.active_fallback_chain is not None and type(
            self.active_fallback_chain
        ) is not BoundedSameTickFallbackChainV1:
            raise C8VirtualTimeContractError("snapshot fallback chain类型不正确")
        if (
            self.active_fallback_chain is not None
            and self.active_fallback_chain.status
            is not SameTickFallbackChainStatusV1.ACTIVE
        ):
            raise C8VirtualTimeContractError("snapshot只能携带active fallback chain")
        if self.active_fallback_chain is not None:
            try:
                self.active_fallback_chain.validate_deadline_state(
                    self.virtual_time_state
                )
            except C8VirtualTimeContractError as exc:
                raise C8VirtualTimeContractError(
                    "snapshot active fallback chain未绑定current timed-out window"
                ) from exc
        _assert_identity(
            self.snapshot_identity, self._identity_material(), "snapshot_identity"
        )

    def _identity_material(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "contract_version": self.contract_version,
            "virtual_time_state": self.virtual_time_state.to_dict(),
            "clock_event_chain": list(self.clock_event_chain),
            "active_fallback_chain": (
                None
                if self.active_fallback_chain is None
                else self.active_fallback_chain.to_dict()
            ),
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._identity_material(), "snapshot_identity": self.snapshot_identity}

    @classmethod
    def capture(
        cls,
        *,
        virtual_time_state: VirtualTimeStateV1,
        active_fallback_chain: BoundedSameTickFallbackChainV1 | None,
    ) -> "VirtualTimeTransactionSnapshotV1":
        if type(virtual_time_state) is not VirtualTimeStateV1:
            raise C8VirtualTimeContractError("snapshot virtual_time_state类型不正确")
        if active_fallback_chain is not None and type(
            active_fallback_chain
        ) is not BoundedSameTickFallbackChainV1:
            raise C8VirtualTimeContractError("snapshot fallback chain类型不正确")
        chain = virtual_time_state.event_chain
        material = {
            "schema": TRANSACTION_SNAPSHOT_SCHEMA,
            "contract_version": 1,
            "virtual_time_state": virtual_time_state.to_dict(),
            "clock_event_chain": list(chain),
            "active_fallback_chain": (
                None if active_fallback_chain is None else active_fallback_chain.to_dict()
            ),
        }
        return cls(
            schema=TRANSACTION_SNAPSHOT_SCHEMA,
            contract_version=1,
            virtual_time_state=virtual_time_state,
            clock_event_chain=chain,
            active_fallback_chain=active_fallback_chain,
            snapshot_identity=_canonical_sha256(material),
        )

    def restore(
        self,
    ) -> tuple[VirtualTimeStateV1, BoundedSameTickFallbackChainV1 | None]:
        return self.virtual_time_state, self.active_fallback_chain

    @classmethod
    def from_dict(cls, value: object) -> "VirtualTimeTransactionSnapshotV1":
        data = _exact_dict(value, "VirtualTimeTransactionSnapshotV1")
        _exact_fields(
            data,
            frozenset(
                {
                    "schema", "contract_version", "virtual_time_state",
                    "clock_event_chain", "active_fallback_chain", "snapshot_identity",
                }
            ),
            "VirtualTimeTransactionSnapshotV1",
        )
        fallback_raw = data["active_fallback_chain"]
        state = VirtualTimeStateV1.from_dict(data["virtual_time_state"])
        fallback = (
            None
            if fallback_raw is None
            else BoundedSameTickFallbackChainV1.from_dict(
                fallback_raw,
                deadline_state=state,
            )
        )
        return cls(
            schema=_exact_text(data["schema"], "snapshot.schema"),
            contract_version=_exact_int(data["contract_version"], "contract_version"),
            virtual_time_state=state,
            clock_event_chain=tuple(
                _exact_sha256(item, "clock_event_chain[]")
                for item in _exact_list(data["clock_event_chain"], "clock_event_chain")
            ),
            active_fallback_chain=fallback,
            snapshot_identity=_exact_sha256(
                data["snapshot_identity"], "snapshot_identity"
            ),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class TimedPublicProjectionV1:
    schema: str
    contract_version: int
    window_id: str
    actor_id: str
    window_kind: TimedWindowKindV1
    now_tick: int
    opened_at: int
    deadline_at: int
    remaining_ticks: int
    decision_identity: str
    obligation_identity: str
    duration_profile_identity: str
    fallback_policy_identity: str
    legal_set_identity: str
    projection_identity: str

    def __post_init__(self) -> None:
        if self.schema != PUBLIC_PROJECTION_SCHEMA:
            raise C8VirtualTimeContractError("TimedPublicProjectionV1 schema不匹配")
        if type(self.contract_version) is not int or self.contract_version != 1:
            raise C8VirtualTimeContractError("public projection contract_version必须精确为1")
        _exact_text(self.window_id, "public.window_id")
        _exact_text(self.actor_id, "public.actor_id")
        if type(self.window_kind) is not TimedWindowKindV1:
            raise C8VirtualTimeContractError("public.window_kind类型不正确")
        _exact_int(self.now_tick, "public.now_tick")
        _exact_int(self.opened_at, "public.opened_at")
        _exact_int(self.deadline_at, "public.deadline_at")
        _exact_int(self.remaining_ticks, "public.remaining_ticks")
        for label, value in (
            ("decision_identity", self.decision_identity),
            ("obligation_identity", self.obligation_identity),
            ("duration_profile_identity", self.duration_profile_identity),
            ("fallback_policy_identity", self.fallback_policy_identity),
            ("legal_set_identity", self.legal_set_identity),
        ):
            _exact_sha256(value, label)
        if self.remaining_ticks != max(self.deadline_at - self.now_tick, 0):
            raise C8VirtualTimeContractError("public remaining_ticks不是deadline-now的推导值")
        _assert_identity(
            self.projection_identity, self._identity_material(), "public projection_identity"
        )

    def _identity_material(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "contract_version": self.contract_version,
            "window_id": self.window_id,
            "actor_id": self.actor_id,
            "window_kind": self.window_kind.value,
            "now_tick": self.now_tick,
            "opened_at": self.opened_at,
            "deadline_at": self.deadline_at,
            "remaining_ticks": self.remaining_ticks,
            "decision_identity": self.decision_identity,
            "obligation_identity": self.obligation_identity,
            "duration_profile_identity": self.duration_profile_identity,
            "fallback_policy_identity": self.fallback_policy_identity,
            "legal_set_identity": self.legal_set_identity,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._identity_material(), "projection_identity": self.projection_identity}

    @classmethod
    def build(
        cls,
        *,
        state: VirtualTimeStateV1,
        window: TimedDecisionWindowV1,
        legal_set: PublicLegalSetProjectionV1,
    ) -> "TimedPublicProjectionV1":
        if state.window_stack.active_window != window:
            raise C8VirtualTimeContractError("public projection只允许current active window")
        if (
            legal_set.window_id != window.window_id
            or legal_set.actor_id != window.actor_id
            or legal_set.decision_identity != window.decision_identity
            or legal_set.obligation_identity != window.obligation_identity
        ):
            raise C8VirtualTimeContractError(
                "public projection legal set authority binding不匹配"
            )
        material = {
            "schema": PUBLIC_PROJECTION_SCHEMA,
            "contract_version": 1,
            "window_id": window.window_id,
            "actor_id": window.actor_id,
            "window_kind": window.window_kind.value,
            "now_tick": state.now_tick,
            "opened_at": window.opened_at,
            "deadline_at": window.deadline_at,
            "remaining_ticks": max(window.deadline_at - state.now_tick, 0),
            "decision_identity": window.decision_identity,
            "obligation_identity": window.obligation_identity,
            "duration_profile_identity": window.duration_profile_identity,
            "fallback_policy_identity": window.fallback_policy_identity,
            "legal_set_identity": legal_set.legal_set_identity,
        }
        return cls(
            schema=PUBLIC_PROJECTION_SCHEMA,
            contract_version=1,
            window_id=window.window_id,
            actor_id=window.actor_id,
            window_kind=window.window_kind,
            now_tick=state.now_tick,
            opened_at=window.opened_at,
            deadline_at=window.deadline_at,
            remaining_ticks=max(window.deadline_at - state.now_tick, 0),
            decision_identity=window.decision_identity,
            obligation_identity=window.obligation_identity,
            duration_profile_identity=window.duration_profile_identity,
            fallback_policy_identity=window.fallback_policy_identity,
            legal_set_identity=legal_set.legal_set_identity,
            projection_identity=_canonical_sha256(material),
        )

    @classmethod
    def from_dict(cls, value: object) -> "TimedPublicProjectionV1":
        _reject_public_leakage(value, "TimedPublicProjectionV1")
        data = _exact_dict(value, "TimedPublicProjectionV1")
        fields = frozenset(
            {
                "schema", "contract_version", "window_id", "actor_id", "window_kind",
                "now_tick", "opened_at", "deadline_at", "remaining_ticks",
                "decision_identity", "obligation_identity", "duration_profile_identity",
                "fallback_policy_identity", "legal_set_identity", "projection_identity",
            }
        )
        _exact_fields(data, fields, "TimedPublicProjectionV1")
        return cls(
            schema=_exact_text(data["schema"], "public.schema"),
            contract_version=_exact_int(data["contract_version"], "contract_version"),
            window_id=_exact_text(data["window_id"], "window_id"),
            actor_id=_exact_text(data["actor_id"], "actor_id"),
            window_kind=_exact_enum(data["window_kind"], TimedWindowKindV1, "window_kind"),
            now_tick=_exact_int(data["now_tick"], "now_tick"),
            opened_at=_exact_int(data["opened_at"], "opened_at"),
            deadline_at=_exact_int(data["deadline_at"], "deadline_at"),
            remaining_ticks=_exact_int(data["remaining_ticks"], "remaining_ticks"),
            decision_identity=_exact_sha256(data["decision_identity"], "decision_identity"),
            obligation_identity=_exact_sha256(
                data["obligation_identity"], "obligation_identity"
            ),
            duration_profile_identity=_exact_sha256(
                data["duration_profile_identity"], "duration_profile_identity"
            ),
            fallback_policy_identity=_exact_sha256(
                data["fallback_policy_identity"], "fallback_policy_identity"
            ),
            legal_set_identity=_exact_sha256(
                data["legal_set_identity"], "legal_set_identity"
            ),
            projection_identity=_exact_sha256(
                data["projection_identity"], "projection_identity"
            ),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class TimedAuthoritativePrivateProjectionV1:
    schema: str
    contract_version: int
    public_projection_identity: str
    window_state_identity: str
    authority_binding_identity: str
    private_payload_commitment: str
    projection_identity: str

    def __post_init__(self) -> None:
        if self.schema != PRIVATE_PROJECTION_SCHEMA:
            raise C8VirtualTimeContractError("private projection schema不匹配")
        if type(self.contract_version) is not int or self.contract_version != 1:
            raise C8VirtualTimeContractError("private projection contract_version必须精确为1")
        for label, value in (
            ("public_projection_identity", self.public_projection_identity),
            ("window_state_identity", self.window_state_identity),
            ("authority_binding_identity", self.authority_binding_identity),
            ("private_payload_commitment", self.private_payload_commitment),
        ):
            _exact_sha256(value, label)
        _assert_identity(
            self.projection_identity,
            self._identity_material(),
            "private projection_identity",
        )

    def _identity_material(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "contract_version": self.contract_version,
            "public_projection_identity": self.public_projection_identity,
            "window_state_identity": self.window_state_identity,
            "authority_binding_identity": self.authority_binding_identity,
            "private_payload_commitment": self.private_payload_commitment,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._identity_material(), "projection_identity": self.projection_identity}

    @classmethod
    def build(
        cls,
        *,
        public_projection_identity: str,
        window_state_identity: str,
        authority_binding_identity: str,
        private_payload_commitment: str,
    ) -> "TimedAuthoritativePrivateProjectionV1":
        material = {
            "schema": PRIVATE_PROJECTION_SCHEMA,
            "contract_version": 1,
            "public_projection_identity": public_projection_identity,
            "window_state_identity": window_state_identity,
            "authority_binding_identity": authority_binding_identity,
            "private_payload_commitment": private_payload_commitment,
        }
        return cls(
            schema=PRIVATE_PROJECTION_SCHEMA,
            contract_version=1,
            public_projection_identity=public_projection_identity,
            window_state_identity=window_state_identity,
            authority_binding_identity=authority_binding_identity,
            private_payload_commitment=private_payload_commitment,
            projection_identity=_canonical_sha256(material),
        )

    @classmethod
    def from_dict(cls, value: object) -> "TimedAuthoritativePrivateProjectionV1":
        data = _exact_dict(value, "TimedAuthoritativePrivateProjectionV1")
        _exact_fields(
            data,
            frozenset(
                {
                    "schema", "contract_version", "public_projection_identity",
                    "window_state_identity", "authority_binding_identity",
                    "private_payload_commitment", "projection_identity",
                }
            ),
            "TimedAuthoritativePrivateProjectionV1",
        )
        return cls(
            schema=_exact_text(data["schema"], "private.schema"),
            contract_version=_exact_int(data["contract_version"], "contract_version"),
            public_projection_identity=_exact_sha256(
                data["public_projection_identity"], "public_projection_identity"
            ),
            window_state_identity=_exact_sha256(
                data["window_state_identity"], "window_state_identity"
            ),
            authority_binding_identity=_exact_sha256(
                data["authority_binding_identity"], "authority_binding_identity"
            ),
            private_payload_commitment=_exact_sha256(
                data["private_payload_commitment"], "private_payload_commitment"
            ),
            projection_identity=_exact_sha256(
                data["projection_identity"], "projection_identity"
            ),
        )


C8_A_CONTRACT_DESCRIPTOR_V1 = MappingProxyType(
    {
        "milestone": C8_A_MILESTONE,
        "contract_id": C8_VIRTUAL_TIME_CONTRACT_ID,
        "contract_version": C8_VIRTUAL_TIME_CONTRACT_VERSION,
        "selected_mode_id": C8_SELECTED_MODE_ID,
        "base_mode_id": C8_BASE_MODE_ID,
        "clock_domain_identity": CLOCK_DOMAIN_V1.clock_domain_identity,
        "duration_profile_identity": ENGINEERING_TEST_PROFILE_V1.profile_identity,
        "fallback_registry_identity": TIMEOUT_FALLBACK_REGISTRY_V1.registry_identity,
        "public_ordering_contract_id": PUBLIC_ORDERING_CONTRACT_ID,
        "same_tick_chain_contract_identity": (
            SAME_TICK_FALLBACK_CHAIN_CONTRACT_V1.contract_identity
        ),
        "parent_resume_rule_id": PARENT_RESUME_RULE_ID,
        "multi_step_timeout_rule_id": MULTI_STEP_TIMEOUT_RULE_ID,
        "timeout_unresolved_rule_id": TIMEOUT_UNRESOLVED_RULE_ID,
        "exact_boundary_interval": "[opened_at,deadline_at)",
        "timeout_at_equal_tick": True,
        "deadline_derivation": "CURRENT_VIRTUAL_TIME_AND_ACTIVE_DEADLINE_ONLY",
        "logical_input_authority": "AUTHENTICATED_STRICTLY_SEQUENCED",
        "child_window_budget": "PAUSE_PARENT_AND_PRESERVE_REMAINING",
        "multi_step_deadline_refresh": "FORBIDDEN",
        "multi_step_fallback": "BOUNDED_SAME_TICK_FRESH_NORMAL_ACTION_CHAIN",
        "timeout_unresolved": "FAIL_CLOSED_AND_FUTURE_OUTER_TRANSACTION_ROLLBACK",
        "fallback_visibility": "FRESH_PUBLIC_LEGAL_SET_ONLY",
        "wall_clock_authority": "FORBIDDEN",
        "random_fallback": "FORBIDDEN",
        "direct_state_mutation": "FORBIDDEN",
        "production_runtime_integration": "NOT_INCLUDED_IN_C8_A",
        "official_client_parity": False,
        "bridge_v1_parent_baseline_identity": BRIDGE_V1_FROZEN_BASELINE_IDENTITY,
    }
)
C8_A_CONTRACT_IDENTITY_V1 = _canonical_sha256(dict(C8_A_CONTRACT_DESCRIPTOR_V1))
C8_A_CONTRACT_IDS_V1 = MappingProxyType(
    {
        "contract": C8_VIRTUAL_TIME_CONTRACT_ID,
        "contract_identity": C8_A_CONTRACT_IDENTITY_V1,
        "clock_domain": CLOCK_DOMAIN_ID,
        "clock_domain_identity": CLOCK_DOMAIN_V1.clock_domain_identity,
        "duration_profile": ENGINEERING_TEST_PROFILE_ID,
        "duration_profile_identity": ENGINEERING_TEST_PROFILE_V1.profile_identity,
        "fallback_registry": FALLBACK_REGISTRY_ID,
        "fallback_registry_identity": TIMEOUT_FALLBACK_REGISTRY_V1.registry_identity,
        "public_ordering": PUBLIC_ORDERING_CONTRACT_ID,
        "same_tick_chain": SAME_TICK_CHAIN_CONTRACT_ID,
        "same_tick_chain_identity": SAME_TICK_FALLBACK_CHAIN_CONTRACT_V1.contract_identity,
        "parent_resume_rule": PARENT_RESUME_RULE_ID,
        "multi_step_timeout_rule": MULTI_STEP_TIMEOUT_RULE_ID,
        "timeout_unresolved_rule": TIMEOUT_UNRESOLVED_RULE_ID,
    }
)


__all__ = [
    "ADVANCE_INPUT_SCHEMA",
    "BRIDGE_V1_FROZEN_BASELINE_IDENTITY",
    "BoundedSameTickFallbackChainV1",
    "C8_A_CONTRACT_DESCRIPTOR_V1",
    "C8_A_CONTRACT_IDENTITY_V1",
    "C8_A_CONTRACT_IDS_V1",
    "C8_A_MILESTONE",
    "C8_BASE_MODE_ID",
    "C8_SELECTED_MODE_ID",
    "C8_VIRTUAL_TIME_CONTRACT_ID",
    "C8_VIRTUAL_TIME_CONTRACT_VERSION",
    "C8VirtualTimeContractError",
    "CLOCK_DOMAIN_ID",
    "CLOCK_DOMAIN_V1",
    "ClockDomainV1",
    "ClockUnitV1",
    "DeadlinePrecedenceV1",
    "DeadlineTieRuleV1",
    "DerivedDeadlineReachedV1",
    "DurationProfileV1",
    "ENGINEERING_PROFILE_DESIGNATION",
    "ENGINEERING_TEST_PROFILE_ID",
    "ENGINEERING_TEST_PROFILE_V1",
    "FALLBACK_REGISTRY_ID",
    "GENESIS_EVENT_CHAIN_TIP",
    "MULTI_STEP_TIMEOUT_RULE_ID",
    "PARENT_RESUME_RULE_ID",
    "PUBLIC_ORDERING_CONTRACT_ID",
    "PublicActionFamilyV1",
    "PublicLegalActionCandidateV1",
    "PublicLegalSetProjectionV1",
    "SAME_TICK_CHAIN_CONTRACT_ID",
    "SAME_TICK_FALLBACK_CHAIN_CONTRACT_V1",
    "SAME_TICK_FALLBACK_CHAIN_MAX_STEPS",
    "SameTickFallbackChainContractV1",
    "SameTickFallbackChainStatusV1",
    "SameTickFallbackChainStepV1",
    "SameTickFallbackTerminationV1",
    "TICK_MAX",
    "TICK_MIN",
    "TIMEOUT_FALLBACK_POLICY_BY_KIND_V1",
    "TIMEOUT_FALLBACK_REGISTRY_V1",
    "TIMEOUT_UNRESOLVED_RULE_ID",
    "TickConsumptionRuleV1",
    "TimedAuthoritativePrivateProjectionV1",
    "TimedDecisionWindowV1",
    "TimedPublicProjectionV1",
    "TimedWindowKindV1",
    "TimedWindowStackV1",
    "TimedWindowStatusV1",
    "TimeoutFallbackPolicyV1",
    "TimeoutFallbackRegistryV1",
    "TimeoutFallbackSelectorV1",
    "TimeoutResolutionKindV1",
    "TimeoutResolutionReasonV1",
    "TimeoutResolutionV1",
    "VirtualTimeAdvanceInputKindV1",
    "VirtualTimeAdvanceInputV1",
    "VirtualTimeAdvanceResultV1",
    "VirtualTimeControlInputKindV1",
    "VirtualTimeControlInputV1",
    "VirtualTimeStateV1",
    "VirtualTimeTransactionSnapshotV1",
    "WallClockSemanticsV1",
    "WindowCloseTransitionV1",
    "WindowDurationV1",
    "advance_virtual_time_v1",
    "close_decision_window_v1",
    "deadline_precedence_v1",
    "open_decision_window_v1",
    "pause_virtual_time_v1",
    "resolve_timeout_v1",
    "resume_virtual_time_v1",
]
