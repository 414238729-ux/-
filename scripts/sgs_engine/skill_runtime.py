# -*- coding: utf-8 -*-
"""Authoritative Skill Runtime orchestrator.

Coordinates skill definitions, player skill states, timing window dispatch,
active action enumeration, static modifier filtering (e.g. 帷幕), trigger discovery (e.g. 明哲),
state transitions, and event emissions.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from types import MappingProxyType
from typing import Any, Iterable, Mapping, Sequence

from .actions import (
    ActionContext,
    ActionType,
    InvalidActionError,
    LegalAction,
    UnsupportedRuleError,
)
from .events import EventType, GameEvent
from .model import CardInstance, GameState, PlayerState, ZoneRef
from .skill_registry import AuthoritativeSkillRegistry, EMPTY_SKILL_REGISTRY
from .skills import (
    AuthoritativeSkillKind,
    AuthoritativeSkillTag,
    SkillDecisionWindow,
    SkillDefinition,
    SkillHandler,
    SkillRuntimeState,
    SkillTimingWindow,
    SkillTriggerContext,
)


class AuthoritativeSkillRuntime:
    """Authoritative Skill Runtime managing per-player skill lifecycle and execution."""

    def __init__(
        self,
        registry: AuthoritativeSkillRegistry,
        player_skills: Mapping[str, Mapping[str, SkillRuntimeState]] | None = None,
    ) -> None:
        if not isinstance(registry, AuthoritativeSkillRegistry):
            raise TypeError("registry 必须是 AuthoritativeSkillRegistry")
        if not registry.is_frozen:
            raise ValueError("传入的技能注册表必须已冻结")

        self._registry = registry
        if player_skills is None:
            self._player_skills: dict[str, dict[str, SkillRuntimeState]] = {}
        else:
            self._player_skills = {
                pid: dict(skills_map) for pid, skills_map in player_skills.items()
            }

    @property
    def registry(self) -> AuthoritativeSkillRegistry:
        return self._registry

    @property
    def player_skills(self) -> Mapping[str, Mapping[str, SkillRuntimeState]]:
        return MappingProxyType(
            {pid: MappingProxyType(skills) for pid, skills in self._player_skills.items()}
        )

    def get_player_skill_states(self, player_id: str) -> tuple[SkillRuntimeState, ...]:
        skills = self._player_skills.get(player_id, {})
        return tuple(skills.values())

    def has_skill(self, player_id: str, skill_id: str) -> bool:
        return skill_id in self._player_skills.get(player_id, {})

    def get_skill_state(self, player_id: str, skill_id: str) -> SkillRuntimeState:
        player_map = self._player_skills.get(player_id)
        if player_map is None or skill_id not in player_map:
            raise UnsupportedRuleError(f"角色 {player_id!r} 未拥有技能 {skill_id!r}")
        return player_map[skill_id]

    def assign_skill(
        self,
        player_id: str,
        skill_id: str,
        *,
        source: str = "武将牌",
        initial_marks: Mapping[str, int] | None = None,
    ) -> AuthoritativeSkillRuntime:
        """Assign a registered skill to a player and return a new runtime."""
        definition = self._registry.get_skill(skill_id)
        new_state = SkillRuntimeState(
            skill_id=definition.skill_id,
            skill_version=definition.version,
            owner_id=player_id,
            source=source,
            marks=initial_marks or {},
        )
        updated = {pid: dict(s) for pid, s in self._player_skills.items()}
        updated.setdefault(player_id, {})[skill_id] = new_state
        return AuthoritativeSkillRuntime(self._registry, updated)

    def on_phase_change(self, new_phase: str) -> AuthoritativeSkillRuntime:
        """Reset uses_this_phase to 0 for all skills across all players."""
        updated: dict[str, dict[str, SkillRuntimeState]] = {}
        for pid, skills_map in self._player_skills.items():
            updated[pid] = {
                sid: state.with_reset_phase() for sid, state in skills_map.items()
            }
        return AuthoritativeSkillRuntime(self._registry, updated)

    def on_turn_change(
        self, new_turn_player_id: str, *, is_extra_turn: bool = False
    ) -> AuthoritativeSkillRuntime:
        """Reset uses_this_turn and uses_this_phase to 0 for all skills across all players."""
        updated: dict[str, dict[str, SkillRuntimeState]] = {}
        for pid, skills_map in self._player_skills.items():
            updated[pid] = {
                sid: state.with_reset_turn() for sid, state in skills_map.items()
            }
        return AuthoritativeSkillRuntime(self._registry, updated)

    def invalidate_skill(
        self, player_id: str, skill_id: str, reason: str = "技能失效"
    ) -> AuthoritativeSkillRuntime:
        state = self.get_skill_state(player_id, skill_id)
        updated = {pid: dict(s) for pid, s in self._player_skills.items()}
        updated[player_id][skill_id] = state.invalidate(reason)
        return AuthoritativeSkillRuntime(self._registry, updated)

    def recover_skill(
        self, player_id: str, skill_id: str
    ) -> AuthoritativeSkillRuntime:
        state = self.get_skill_state(player_id, skill_id)
        updated = {pid: dict(s) for pid, s in self._player_skills.items()}
        updated[player_id][skill_id] = state.recover_invalidation()
        return AuthoritativeSkillRuntime(self._registry, updated)

    def lose_skill(
        self, player_id: str, skill_id: str
    ) -> AuthoritativeSkillRuntime:
        state = self.get_skill_state(player_id, skill_id)
        updated = {pid: dict(s) for pid, s in self._player_skills.items()}
        updated[player_id][skill_id] = state.lose()
        return AuthoritativeSkillRuntime(self._registry, updated)

    def increment_usage(
        self, player_id: str, skill_id: str
    ) -> AuthoritativeSkillRuntime:
        """Return a new runtime with phase/turn/game usage incremented by 1."""
        state = self.get_skill_state(player_id, skill_id)
        updated = {pid: dict(s) for pid, s in self._player_skills.items()}
        updated[player_id][skill_id] = state.with_usage_increment()
        return AuthoritativeSkillRuntime(self._registry, updated)

    def enumerate_active_skill_actions(
        self,
        actor_id: str,
        context: ActionContext,
        state: GameState,
    ) -> tuple[LegalAction, ...]:
        """Enumerate active skill actions available to actor_id in current context."""
        player_map = self._player_skills.get(actor_id, {})
        actions: list[LegalAction] = []

        for skill_id, skill_state in sorted(player_map.items()):
            if not skill_state.effective:
                continue
            definition = self._registry.get_skill(skill_id)
            if definition.kind is AuthoritativeSkillKind.VIEW_AS:
                raise UnsupportedRuleError(
                    "V1不支持视为技；不得静默返回空动作集"
                )
            if definition.kind != AuthoritativeSkillKind.ACTIVE:
                continue
            if SkillTimingWindow.PLAY_PHASE_ACTION not in definition.timing_windows:
                continue
            # Check usage limits
            if (
                definition.max_uses_per_phase is not None
                and skill_state.uses_this_phase >= definition.max_uses_per_phase
            ):
                continue
            if (
                definition.max_uses_per_turn is not None
                and skill_state.uses_this_turn >= definition.max_uses_per_turn
            ):
                continue
            if (
                definition.max_uses_per_game is not None
                and skill_state.uses_this_game >= definition.max_uses_per_game
            ):
                continue

            handler = self._registry.get_handler(skill_id)
            enumerated = handler.enumerate_active_actions(context, state, skill_state)
            actions.extend(enumerated)

        return tuple(actions)

    def audit_fingerprint(self) -> dict[str, object]:
        """JSON-stable fingerprint for production adapter audit_state."""

        players: dict[str, object] = {}
        for pid in sorted(self._player_skills):
            skills = self._player_skills[pid]
            players[pid] = {
                sid: {
                    "effective": state.effective,
                    "lost": state.lost,
                    "invalidated": state.invalidated,
                    "uses_this_phase": state.uses_this_phase,
                    "uses_this_turn": state.uses_this_turn,
                    "uses_this_game": state.uses_this_game,
                    "skill_version": state.skill_version,
                    "marks": dict(state.marks),
                }
                for sid, state in sorted(skills.items())
            }
        return {
            "registry_identity": self._registry.registry_identity,
            "player_skills": players,
        }

    def filter_legal_targets(
        self,
        user_id: str,
        card_instance: CardInstance | None,
        card_key: str,
        candidate_targets: Sequence[str],
        state: GameState,
    ) -> tuple[str, ...]:
        """Filter candidate_targets through all registered static modifier skills (e.g. 帷幕)."""
        valid_targets: list[str] = []
        for target_id in candidate_targets:
            target_player = state.players_by_id.get(target_id)
            if target_player is None or not target_player.alive:
                # This method applies only skill modifiers; base card legality
                # remains responsible for rejecting dead/unknown targets.
                valid_targets.append(target_id)
                continue
            target_skills = self._player_skills.get(target_id, {})
            prohibited = False
            for skill_id, skill_state in target_skills.items():
                if not skill_state.effective:
                    continue
                definition = self._registry.get_skill(skill_id)
                if definition.kind != AuthoritativeSkillKind.STATIC_MODIFIER:
                    continue
                if SkillTimingWindow.TARGET_FILTER not in definition.timing_windows:
                    continue

                handler = self._registry.get_handler(skill_id)
                if not handler.filter_target_legality(
                    target_id=target_id,
                    card_instance=card_instance,
                    card_key=card_key,
                    user_id=user_id,
                    state=state,
                    skill_state=skill_state,
                ):
                    prohibited = True
                    break
            if not prohibited:
                valid_targets.append(target_id)
        return tuple(valid_targets)

    def validate_target_legality(
        self,
        user_id: str,
        target_ids: Sequence[str],
        card_instance: CardInstance | None,
        card_key: str,
        state: GameState,
    ) -> None:
        """Validate that all target_ids are permissible under static modifier skills."""
        for target_id in target_ids:
            target_player = state.players_by_id.get(target_id)
            if target_player is None or not target_player.alive:
                # Dead owners no longer project static modifiers. The card
                # adapter's ordinary target validator still rejects dead IDs.
                continue
            target_skills = self._player_skills.get(target_id, {})
            for skill_id, skill_state in target_skills.items():
                if not skill_state.effective:
                    continue
                definition = self._registry.get_skill(skill_id)
                if definition.kind != AuthoritativeSkillKind.STATIC_MODIFIER:
                    continue
                if SkillTimingWindow.TARGET_FILTER not in definition.timing_windows:
                    continue

                handler = self._registry.get_handler(skill_id)
                if not handler.filter_target_legality(
                    target_id=target_id,
                    card_instance=card_instance,
                    card_key=card_key,
                    user_id=user_id,
                    state=state,
                    skill_state=skill_state,
                ):
                    raise InvalidActionError(
                        f"目标角色 {target_id} 拥有技能【{definition.skill_name}】，不能成为【{card_key}】的目标"
                    )

    def evaluate_triggers_for_event(
        self,
        event: GameEvent,
        state: GameState,
        turn_player_id: str,
        current_phase: str,
        timing_window: SkillTimingWindow,
        context_payload: Mapping[str, Any] | None = None,
    ) -> tuple[tuple[str, str, SkillHandler, SkillTriggerContext], ...]:
        """Discover and evaluate all matching skill triggers for a given GameEvent."""
        candidates: list[tuple[str, str, SkillHandler, SkillTriggerContext]] = []

        for pid, skills_map in sorted(self._player_skills.items()):
            for skill_id, skill_state in sorted(skills_map.items()):
                if not skill_state.effective:
                    continue
                definition = self._registry.get_skill(skill_id)
                if definition.kind is AuthoritativeSkillKind.VIEW_AS:
                    raise UnsupportedRuleError(
                        "V1不支持视为技；不得静默返回空触发集"
                    )
                if definition.kind != AuthoritativeSkillKind.TRIGGERED:
                    continue
                if timing_window not in definition.timing_windows:
                    continue

                # Check usage limits
                if (
                    definition.max_uses_per_phase is not None
                    and skill_state.uses_this_phase >= definition.max_uses_per_phase
                ):
                    continue
                if (
                    definition.max_uses_per_turn is not None
                    and skill_state.uses_this_turn >= definition.max_uses_per_turn
                ):
                    continue
                if (
                    definition.max_uses_per_game is not None
                    and skill_state.uses_this_game >= definition.max_uses_per_game
                ):
                    continue

                ctx = SkillTriggerContext(
                    timing_window=timing_window,
                    actor_id=pid,
                    turn_player_id=turn_player_id,
                    phase=current_phase,
                    event=event,
                    payload=context_payload or {},
                )
                handler = self._registry.get_handler(skill_id)
                if handler.evaluate_trigger(ctx, state, skill_state):
                    candidates.append((pid, skill_id, handler, ctx))

        if len(candidates) > 1:
            # Check for multiple simultaneous triggers: fail-closed if no formal ordering rule exists
            raise UnsupportedRuleError(
                f"发现多个技能同时触发（{[f'{c[0]}:{c[1]}' for c in candidates]}），"
                f"当前 Knowledge 未确认该组合排序规则，失败关闭"
            )

        return tuple(candidates)

    def apply_skill_action(
        self,
        action: LegalAction,
        context: ActionContext,
        state: GameState,
    ) -> tuple[GameState, AuthoritativeSkillRuntime, tuple[GameEvent, ...]]:
        """COMPONENT-ONLY helper. Not a production authority entry.

        Production consumers and production skill replay must go through
        ``ProductionBasicCardBatch.legal_actions`` → signed ``action_id`` →
        ``session.step``. This method does not bind action_id, EventQueue,
        or the production phase machine.
        """
        if action.action_type != ActionType.ACTIVATE_SKILL:
            raise InvalidActionError(f"apply_skill_action 只能处理 ACTIVATE_SKILL 动作，当前为 {action.action_type.value}")
        if not action.skill_id:
            raise InvalidActionError("ACTIVATE_SKILL 动作缺少 skill_id")

        actor_id = action.actor_id
        skill_id = action.skill_id
        skill_state = self.get_skill_state(actor_id, skill_id)
        if not skill_state.effective:
            raise InvalidActionError(f"角色 {actor_id} 的技能 {skill_id} 已失效或失去，无法发动")

        definition = self._registry.get_skill(skill_id)
        # Verify usage limits
        if (
            definition.max_uses_per_phase is not None
            and skill_state.uses_this_phase >= definition.max_uses_per_phase
        ):
            raise InvalidActionError(f"技能 {skill_id} 已达阶段发动上限 {definition.max_uses_per_phase}")
        if (
            definition.max_uses_per_turn is not None
            and skill_state.uses_this_turn >= definition.max_uses_per_turn
        ):
            raise InvalidActionError(f"技能 {skill_id} 已达回合发动上限 {definition.max_uses_per_turn}")
        if (
            definition.max_uses_per_game is not None
            and skill_state.uses_this_game >= definition.max_uses_per_game
        ):
            raise InvalidActionError(f"技能 {skill_id} 已达整局发动上限 {definition.max_uses_per_game}")

        handler = self._registry.get_handler(skill_id)
        new_state, updated_skill_state, events = handler.apply_action(action, context, state, skill_state)

        # Increment usage counter
        final_skill_state = updated_skill_state.with_usage_increment()
        updated_runtime_skills = {pid: dict(s) for pid, s in self._player_skills.items()}
        updated_runtime_skills[actor_id][skill_id] = final_skill_state
        new_runtime = AuthoritativeSkillRuntime(self._registry, updated_runtime_skills)

        return new_state, new_runtime, events
