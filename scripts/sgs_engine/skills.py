# -*- coding: utf-8 -*-
"""Authoritative skill definitions, lifecycle states, and handler interfaces.

This module provides the core types for the authoritative skill runtime:
- AuthoritativeSkillKind: orthogonal execution kinds (ACTIVE, TRIGGERED, STATIC_MODIFIER, VIEW_AS)
- AuthoritativeSkillTag: orthogonal text type tags (LOCKED, LIMITED, AWAKENING, MISSION, PERSEVERING, CONVERSION, CHARGE)
- SkillTimingWindow: discrete timing windows
- SkillDefinition: immutable, validated skill schema with canonical profile identity
- SkillRuntimeState: immutable per-player skill state tracking ownership, invalidation, lost status, usage, marks, and conversion
- SkillHandler: abstract base class for authoritative skill execution
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field, replace
from enum import Enum
import hashlib
import json
import math
from types import MappingProxyType
from typing import Any, Iterable, Mapping, Sequence

from .actions import (
    ActionContext,
    ActionType,
    InvalidActionError,
    LegalAction,
    UnsupportedRuleError,
    VirtualCardReference,
)

SKILL_SCHEMA_V1 = "authoritative-skill-v1"
from .events import EventType, GameEvent
from .model import CardInstance, GameState, ZoneKind, ZoneRef


class AuthoritativeSkillKind(str, Enum):
    """Orthogonal execution kinds of skills."""

    ACTIVE = "active"
    TRIGGERED = "triggered"
    STATIC_MODIFIER = "static_modifier"
    VIEW_AS = "view_as"


class AuthoritativeSkillTag(str, Enum):
    """Orthogonal text type tags of skills."""

    LOCKED = "锁定技"
    LIMITED = "限定技"
    AWAKENING = "觉醒技"
    MISSION = "使命技"
    PERSEVERING = "持恒技"
    CONVERSION = "转换技"
    CHARGE = "蓄力技"


class SkillTimingWindow(str, Enum):
    """Discrete timing and execution windows for skills."""

    PLAY_PHASE_ACTION = "play_phase_action"
    ON_CARD_USED = "on_card_used"
    ON_CARD_PLAYED = "on_card_played"
    ON_CARD_LOST = "on_card_lost"
    ON_CARD_DISCARDED = "on_card_discarded"
    ON_CARD_GAINED = "on_card_gained"
    ON_DAMAGE_TAKEN = "on_damage_taken"
    ON_DAMAGE_INFLICTED = "on_damage_inflicted"
    ON_BECOME_TARGET = "on_become_target"
    TARGET_FILTER = "target_filter"
    DISTANCE_MODIFIER = "distance_modifier"
    RESPONSE_WINDOW = "response_window"
    PHASE_CHANGE = "phase_change"
    TURN_CHANGE = "turn_change"
    END_PHASE_START = "end_phase_start"


_ACTIVE_ONLY_WINDOWS = frozenset(
    {SkillTimingWindow.PLAY_PHASE_ACTION, SkillTimingWindow.RESPONSE_WINDOW}
)
_STATIC_WINDOWS = frozenset(
    {SkillTimingWindow.TARGET_FILTER, SkillTimingWindow.DISTANCE_MODIFIER}
)
_TRIGGER_WINDOWS = frozenset(
    {
        SkillTimingWindow.ON_CARD_USED,
        SkillTimingWindow.ON_CARD_PLAYED,
        SkillTimingWindow.ON_CARD_LOST,
        SkillTimingWindow.ON_CARD_DISCARDED,
        SkillTimingWindow.ON_CARD_GAINED,
        SkillTimingWindow.ON_DAMAGE_TAKEN,
        SkillTimingWindow.ON_DAMAGE_INFLICTED,
        SkillTimingWindow.ON_BECOME_TARGET,
        SkillTimingWindow.PHASE_CHANGE,
        SkillTimingWindow.TURN_CHANGE,
        SkillTimingWindow.END_PHASE_START,
        SkillTimingWindow.RESPONSE_WINDOW,
    }
)


def _require_nonempty_str(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label}必须是非空字符串")
    return value.strip()


def _require_non_negative_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{label}必须是非负整数")
    return value


def _freeze_dict(mapping: Mapping[str, Any], label: str) -> MappingProxyType[str, Any]:
    if not isinstance(mapping, Mapping):
        raise TypeError(f"{label}必须是映射")
    frozen: dict[str, Any] = {}
    for k, v in mapping.items():
        if not isinstance(k, str) or not k.strip():
            raise ValueError(f"{label}的键必须是非空字符串")
        frozen[k.strip()] = v
    return MappingProxyType(frozen)


@dataclass(frozen=True, slots=True, kw_only=True)
class SkillDefinition:
    """Immutable authoritative skill definition."""

    skill_id: str
    skill_name: str
    version: str
    kind: AuthoritativeSkillKind
    tags: frozenset[AuthoritativeSkillTag] = field(default_factory=frozenset)
    timing_windows: frozenset[SkillTimingWindow] = field(default_factory=frozenset)
    is_mandatory: bool = False
    max_uses_per_phase: int | None = None
    max_uses_per_turn: int | None = None
    max_uses_per_game: int | None = None
    description: str = ""
    schema_version: str = SKILL_SCHEMA_V1
    profile_identity: str = field(default="")

    def __post_init__(self) -> None:
        object.__setattr__(self, "skill_id", _require_nonempty_str(self.skill_id, "技能ID"))
        object.__setattr__(self, "skill_name", _require_nonempty_str(self.skill_name, "技能名称"))
        object.__setattr__(self, "version", _require_nonempty_str(self.version, "技能版本"))
        if not isinstance(self.kind, AuthoritativeSkillKind):
            raise TypeError("技能kind必须是AuthoritativeSkillKind枚举")
        if not isinstance(self.tags, frozenset):
            try:
                tags = frozenset(self.tags)
            except TypeError as exc:
                raise TypeError("技能tags必须是可迭代集合") from exc
            if any(not isinstance(t, AuthoritativeSkillTag) for t in tags):
                raise TypeError("技能tags中的元素必须是AuthoritativeSkillTag枚举")
            object.__setattr__(self, "tags", tags)
        if not isinstance(self.timing_windows, frozenset):
            try:
                windows = frozenset(self.timing_windows)
            except TypeError as exc:
                raise TypeError("技能timing_windows必须是可迭代集合") from exc
            if any(not isinstance(w, SkillTimingWindow) for w in windows):
                raise TypeError("技能timing_windows中的元素必须是SkillTimingWindow枚举")
            object.__setattr__(self, "timing_windows", windows)
        if not isinstance(self.is_mandatory, bool):
            raise TypeError("is_mandatory必须是布尔值")
        for field_name, label in (
            ("max_uses_per_phase", "阶段发动上限"),
            ("max_uses_per_turn", "回合发动上限"),
            ("max_uses_per_game", "整局发动上限"),
        ):
            val = getattr(self, field_name)
            if val is not None:
                if isinstance(val, bool) or not isinstance(val, int) or val < 1:
                    raise ValueError(f"{label}必须是正整数或None")
        if not isinstance(self.description, str):
            raise TypeError("技能描述必须是字符串")
        object.__setattr__(
            self, "schema_version", _require_nonempty_str(self.schema_version, "技能schema版本")
        )
        self._validate_v1_capability()

        canonical_dict = self.to_canonical_dict(include_identity=False)
        encoded = json.dumps(canonical_dict, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        computed_id = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        if self.profile_identity and self.profile_identity != computed_id:
            raise ValueError(f"提供的profile_identity与计算值不一致：{self.profile_identity} != {computed_id}")
        object.__setattr__(self, "profile_identity", computed_id)

    def _validate_v1_capability(self) -> None:
        """Restrict currently supported combinations; V2 may widen this set."""

        if self.schema_version != SKILL_SCHEMA_V1:
            raise UnsupportedRuleError(
                f"不受支持的技能schema版本：{self.schema_version}"
            )
        if self.kind is AuthoritativeSkillKind.VIEW_AS:
            raise UnsupportedRuleError(
                "V1不支持视为技；登记或调用 VIEW_AS 必须失败关闭，"
                "不得静默返回空动作集"
            )
        if self.kind is AuthoritativeSkillKind.ACTIVE:
            if self.is_mandatory or AuthoritativeSkillTag.LOCKED in self.tags:
                raise UnsupportedRuleError(
                    "V1 不允许 ACTIVE 与强制锁定技语义并存"
                )
            if SkillTimingWindow.PLAY_PHASE_ACTION not in self.timing_windows:
                raise UnsupportedRuleError(
                    "V1 主动技必须声明 PLAY_PHASE_ACTION 时机"
                )
        if self.kind is AuthoritativeSkillKind.STATIC_MODIFIER:
            if not (self.timing_windows & _STATIC_WINDOWS):
                raise UnsupportedRuleError(
                    "V1 静态修正技必须声明 TARGET_FILTER 或 DISTANCE_MODIFIER"
                )
            if self.timing_windows & _ACTIVE_ONLY_WINDOWS:
                raise UnsupportedRuleError(
                    "V1 静态修正技不得声明主动技专用时机"
                )
        if self.kind is AuthoritativeSkillKind.TRIGGERED:
            if not (self.timing_windows & _TRIGGER_WINDOWS):
                raise UnsupportedRuleError(
                    "V1 触发技必须声明已支持的触发时机"
                )

    def to_canonical_dict(self, *, include_identity: bool = True) -> dict[str, Any]:
        result: dict[str, Any] = {
            "description": self.description,
            "is_mandatory": self.is_mandatory,
            "kind": self.kind.value,
            "max_uses_per_game": self.max_uses_per_game,
            "max_uses_per_phase": self.max_uses_per_phase,
            "max_uses_per_turn": self.max_uses_per_turn,
            "schema_version": self.schema_version,
            "skill_id": self.skill_id,
            "skill_name": self.skill_name,
            "tags": sorted(t.value for t in self.tags),
            "timing_windows": sorted(w.value for w in self.timing_windows),
            "version": self.version,
        }
        if include_identity:
            result["profile_identity"] = self.profile_identity
        return result


@dataclass(frozen=True, slots=True, kw_only=True)
class SkillRuntimeState:
    """Immutable authoritative runtime state for one skill instance owned by a player."""

    skill_id: str
    skill_version: str
    owner_id: str
    source: str = "武将牌"
    owned: bool = True
    invalidated: bool = False
    invalidation_reason: str | None = None
    lost: bool = False
    uses_this_phase: int = 0
    uses_this_turn: int = 0
    uses_this_game: int = 0
    awakened: bool = False
    conversion_state: str | None = None
    marks: Mapping[str, int] = field(default_factory=dict)
    charge: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "skill_id", _require_nonempty_str(self.skill_id, "技能ID"))
        object.__setattr__(self, "skill_version", _require_nonempty_str(self.skill_version, "技能版本"))
        object.__setattr__(self, "owner_id", _require_nonempty_str(self.owner_id, "所有者ID"))
        object.__setattr__(self, "source", _require_nonempty_str(self.source, "技能来源"))
        if not isinstance(self.owned, bool):
            raise TypeError("owned必须是布尔值")
        if not isinstance(self.invalidated, bool):
            raise TypeError("invalidated必须是布尔值")
        if not isinstance(self.lost, bool):
            raise TypeError("lost必须是布尔值")
        if self.lost and self.invalidated:
            raise ValueError("已经失去的技能不能同时保持失效状态")
        object.__setattr__(self, "uses_this_phase", _require_non_negative_int(self.uses_this_phase, "uses_this_phase"))
        object.__setattr__(self, "uses_this_turn", _require_non_negative_int(self.uses_this_turn, "uses_this_turn"))
        object.__setattr__(self, "uses_this_game", _require_non_negative_int(self.uses_this_game, "uses_this_game"))
        if not isinstance(self.awakened, bool):
            raise TypeError("awakened必须是布尔值")
        if self.conversion_state is not None:
            object.__setattr__(self, "conversion_state", _require_nonempty_str(self.conversion_state, "conversion_state"))
        if not isinstance(self.marks, MappingProxyType):
            if not isinstance(self.marks, Mapping):
                raise TypeError("marks必须是映射")
            frozen_marks: dict[str, int] = {}
            for k, v in self.marks.items():
                k_clean = _require_nonempty_str(k, "mark名称")
                v_clean = _require_non_negative_int(v, f"mark[{k}]")
                frozen_marks[k_clean] = v_clean
            object.__setattr__(self, "marks", MappingProxyType(frozen_marks))
        if self.charge is not None:
            object.__setattr__(self, "charge", _require_non_negative_int(self.charge, "charge"))

    @property
    def effective(self) -> bool:
        """A skill is effective if owned, not lost, and not invalidated."""
        return self.owned and not self.lost and not self.invalidated

    def with_usage_increment(self) -> SkillRuntimeState:
        """Increment phase, turn, and game usage counts by 1."""
        return replace(
            self,
            uses_this_phase=self.uses_this_phase + 1,
            uses_this_turn=self.uses_this_turn + 1,
            uses_this_game=self.uses_this_game + 1,
        )

    def with_reset_phase(self) -> SkillRuntimeState:
        """Reset phase usage to 0."""
        if self.uses_this_phase == 0:
            return self
        return replace(self, uses_this_phase=0)

    def with_reset_turn(self) -> SkillRuntimeState:
        """Reset both turn and phase usage to 0."""
        if self.uses_this_phase == 0 and self.uses_this_turn == 0:
            return self
        return replace(self, uses_this_phase=0, uses_this_turn=0)

    def with_marks(self, marks: Mapping[str, int]) -> SkillRuntimeState:
        """Return state with updated marks mapping."""
        return replace(self, marks=marks)

    def invalidate(self, reason: str = "技能失效") -> SkillRuntimeState:
        """Invalidate the skill."""
        if self.lost:
            return self
        return replace(self, invalidated=True, invalidation_reason=_require_nonempty_str(reason, "失效原因"))

    def recover_invalidation(self) -> SkillRuntimeState:
        """Recover from invalidation if not permanently lost."""
        if self.lost or not self.invalidated:
            return self
        return replace(self, invalidated=False, invalidation_reason=None)

    def lose(self) -> SkillRuntimeState:
        """Permanently lose the skill."""
        return replace(self, lost=True, owned=False, invalidated=False, invalidation_reason=None)

    def to_dict(self) -> dict[str, Any]:
        return {
            "awakened": self.awakened,
            "charge": self.charge,
            "conversion_state": self.conversion_state,
            "invalidated": self.invalidated,
            "invalidation_reason": self.invalidation_reason,
            "lost": self.lost,
            "marks": dict(self.marks),
            "owned": self.owned,
            "owner_id": self.owner_id,
            "skill_id": self.skill_id,
            "skill_version": self.skill_version,
            "source": self.source,
            "uses_this_game": self.uses_this_game,
            "uses_this_phase": self.uses_this_phase,
            "uses_this_turn": self.uses_this_turn,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class SkillTriggerContext:
    """Context passed when evaluating and executing a trigger window."""

    timing_window: SkillTimingWindow
    actor_id: str
    turn_player_id: str
    phase: str
    event: GameEvent | None = None
    payload: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.timing_window, SkillTimingWindow):
            raise TypeError("timing_window必须是SkillTimingWindow")
        object.__setattr__(self, "actor_id", _require_nonempty_str(self.actor_id, "actor_id"))
        object.__setattr__(self, "turn_player_id", _require_nonempty_str(self.turn_player_id, "turn_player_id"))
        object.__setattr__(self, "phase", _require_nonempty_str(self.phase, "phase"))
        if self.event is not None and not isinstance(self.event, GameEvent):
            raise TypeError("event必须是GameEvent或None")
        if not isinstance(self.payload, MappingProxyType):
            object.__setattr__(self, "payload", _freeze_dict(self.payload, "payload"))


@dataclass(frozen=True, slots=True, kw_only=True)
class SkillDecisionWindow:
    """An authoritative decision window presented to a player when a skill triggers or is active."""

    decision_window_id: str
    skill_id: str
    actor_id: str
    timing_window: SkillTimingWindow
    trigger_event_sequence: int | None = None
    legal_actions: tuple[LegalAction, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "decision_window_id", _require_nonempty_str(self.decision_window_id, "decision_window_id"))
        object.__setattr__(self, "skill_id", _require_nonempty_str(self.skill_id, "skill_id"))
        object.__setattr__(self, "actor_id", _require_nonempty_str(self.actor_id, "actor_id"))
        if not isinstance(self.timing_window, SkillTimingWindow):
            raise TypeError("timing_window必须是SkillTimingWindow")
        if self.trigger_event_sequence is not None:
            if isinstance(self.trigger_event_sequence, bool) or not isinstance(self.trigger_event_sequence, int) or self.trigger_event_sequence < 1:
                raise ValueError("trigger_event_sequence必须是正整数或None")
        if any(not isinstance(a, LegalAction) for a in self.legal_actions):
            raise TypeError("legal_actions中的元素必须是LegalAction")


class SkillHandler(ABC):
    """Abstract base class for all authoritative skill handlers."""

    @property
    @abstractmethod
    def definition(self) -> SkillDefinition:
        """The immutable skill definition."""
        raise NotImplementedError

    def enumerate_active_actions(
        self,
        context: ActionContext,
        state: GameState,
        skill_state: SkillRuntimeState,
    ) -> tuple[LegalAction, ...]:
        """Enumerate active skill actions during active decision phases (e.g. PLAY)."""
        return ()

    def evaluate_trigger(
        self,
        context: SkillTriggerContext,
        state: GameState,
        skill_state: SkillRuntimeState,
    ) -> bool:
        """Return True if this skill's trigger conditions are met by the event/context."""
        return False

    def resolve_target_effect_after_card_used(
        self,
        *,
        event: GameEvent,
        state: GameState,
        skill_state: SkillRuntimeState,
        turn_number: int,
    ) -> tuple[SkillRuntimeState, bool, tuple[GameEvent, ...]] | None:
        """Resolve a registered mandatory target-effect modifier.

        ``None`` means this handler does not apply to the card/target relation.
        The boolean is target-scoped ineffectiveness, never whole-card
        invalidation or target cancellation.
        """

        del event, state, skill_state, turn_number
        return None

    def enumerate_trigger_actions(
        self,
        context: SkillTriggerContext,
        state: GameState,
        skill_state: SkillRuntimeState,
    ) -> tuple[LegalAction, ...]:
        """Enumerate legal actions for an optional trigger window."""
        return ()

    def apply_action(
        self,
        action: LegalAction,
        context: ActionContext,
        state: GameState,
        skill_state: SkillRuntimeState,
    ) -> tuple[GameState, SkillRuntimeState, tuple[GameEvent, ...]]:
        """COMPONENT-ONLY apply. Not a production authority entry.

        Production execution must go through ProductionBasicCardBatch.step
        after signed legal-action enumeration. Unit tests may call this.
        """
        raise NotImplementedError

    def apply_in_production(
        self,
        session: object,
        action: LegalAction,
        context: ActionContext,
        state: GameState,
        skill_state: SkillRuntimeState,
    ) -> GameState:
        """Production effect entry invoked only by the production session.

        Implementations must use session production transactions
        (draw / discard / move with EventQueue). Direct GameState.move_card
        without the session transaction is not a production apply.
        """
        raise UnsupportedRuleError(
            f"技能{self.definition.skill_id}没有生产结算入口"
        )

    def filter_target_legality(
        self,
        target_id: str,
        card_instance: CardInstance | None,
        card_key: str,
        user_id: str,
        state: GameState,
        skill_state: SkillRuntimeState,
    ) -> bool:
        """Return False if this static modifier skill prohibits target_id from being targeted.

        Default is True (no prohibition).
        """
        return True

    def modify_distance(
        self,
        from_player_id: str,
        to_player_id: str,
        raw_distance: int,
        state: GameState,
        skill_state: SkillRuntimeState,
    ) -> int:
        """Apply distance modifications. Default is unchanged."""
        return raw_distance
