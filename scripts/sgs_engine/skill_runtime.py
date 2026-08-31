# -*- coding: utf-8 -*-
"""Authoritative Skill Runtime orchestrator.

Coordinates skill definitions, player skill states, timing window dispatch,
active action enumeration, static modifier filtering (e.g. 帷幕), trigger discovery (e.g. 明哲),
state transitions, and event emissions.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from types import MappingProxyType
from typing import Any, Callable, Iterable, Mapping, Sequence

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
    DynamicSkillGrant,
    SkillDecisionWindow,
    SkillDefinition,
    SkillHandler,
    SkillRuntimeState,
    SkillTimingWindow,
    SkillTriggerContext,
)


class AuthoritativeSkillRuntime:
    """Authoritative Skill Runtime managing per-player skill lifecycle, dynamic grants, and execution."""

    def __init__(
        self,
        registry: AuthoritativeSkillRegistry,
        player_skills: Mapping[str, Mapping[str, SkillRuntimeState]] | None = None,
        dynamic_grants: Mapping[str, Sequence[DynamicSkillGrant]] | None = None,
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

        if dynamic_grants is None:
            self._dynamic_grants: dict[str, tuple[DynamicSkillGrant, ...]] = {}
        else:
            self._dynamic_grants = {
                pid: tuple(grants) for pid, grants in dynamic_grants.items()
            }

    @property
    def registry(self) -> AuthoritativeSkillRegistry:
        return self._registry

    @property
    def player_skills(self) -> Mapping[str, Mapping[str, SkillRuntimeState]]:
        return MappingProxyType(
            {pid: MappingProxyType(skills) for pid, skills in self._player_skills.items()}
        )

    @property
    def dynamic_grants(self) -> Mapping[str, tuple[DynamicSkillGrant, ...]]:
        return MappingProxyType(dict(self._dynamic_grants))

    def _all_player_ids(self) -> tuple[str, ...]:
        return tuple(sorted(set(self._player_skills.keys()) | set(self._dynamic_grants.keys())))

    def get_effective_skill_map(self, player_id: str) -> dict[str, SkillRuntimeState]:
        """Return a mapping of skill_id to effective SkillRuntimeState for a player."""
        result: dict[str, SkillRuntimeState] = {}
        base_map = self._player_skills.get(player_id, {})
        for sid, state in base_map.items():
            if state.effective:
                result[sid] = state

        # Check dynamic grants
        grants = self._dynamic_grants.get(player_id, ())
        for grant in grants:
            if not grant.active:
                continue
            sid = grant.target_skill_id
            if sid not in result:
                definition = self._registry.get_skill(sid)
                result[sid] = SkillRuntimeState(
                    skill_id=sid,
                    skill_version=definition.version,
                    owner_id=player_id,
                    source=f"dynamic_grant:{grant.source_skill_id}",
                    marks={},
                )
        return result

    def get_player_skill_states(self, player_id: str) -> tuple[SkillRuntimeState, ...]:
        """Return all effective skill states for player_id in deterministic order."""
        eff_map = self.get_effective_skill_map(player_id)
        return tuple(eff_map[sid] for sid in sorted(eff_map))

    def has_skill(self, player_id: str, skill_id: str) -> bool:
        """Check if player_id has an active/effective skill (base or dynamic)."""
        base_map = self._player_skills.get(player_id, {})
        if skill_id in base_map and base_map[skill_id].effective:
            return True
        grants = self._dynamic_grants.get(player_id, ())
        return any(g.active and g.target_skill_id == skill_id for g in grants)

    def get_skill_state(self, player_id: str, skill_id: str) -> SkillRuntimeState:
        """Return SkillRuntimeState for player_id and skill_id, or raise UnsupportedRuleError."""
        base_map = self._player_skills.get(player_id, {})
        if skill_id in base_map:
            return base_map[skill_id]
        grants = self._dynamic_grants.get(player_id, ())
        active_grant = next((g for g in grants if g.active and g.target_skill_id == skill_id), None)
        if active_grant is not None:
            definition = self._registry.get_skill(skill_id)
            return SkillRuntimeState(
                skill_id=skill_id,
                skill_version=definition.version,
                owner_id=player_id,
                source=f"dynamic_grant:{active_grant.source_skill_id}",
                marks={},
            )
        raise UnsupportedRuleError(f"角色 {player_id!r} 未拥有技能 {skill_id!r}")

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
        return AuthoritativeSkillRuntime(self._registry, updated, self._dynamic_grants)

    def grant_dynamic_skill(
        self,
        grant: DynamicSkillGrant,
    ) -> AuthoritativeSkillRuntime:
        """Add a dynamic skill grant and return a new runtime."""
        if not isinstance(grant, DynamicSkillGrant):
            raise TypeError("grant 必须是 DynamicSkillGrant 实例")
        if not self._registry.has_skill(grant.target_skill_id):
            raise UnsupportedRuleError(f"被授予技能 {grant.target_skill_id!r} 未在注册表中注册")
        player_id = grant.owner_id
        grants_list = list(self._dynamic_grants.get(player_id, ()))
        grants_list.append(grant)
        updated_grants = dict(self._dynamic_grants)
        updated_grants[player_id] = tuple(grants_list)
        return AuthoritativeSkillRuntime(self._registry, self._player_skills, updated_grants)

    def revoke_dynamic_grants(
        self,
        predicate: Callable[[DynamicSkillGrant], bool],
        reason: str,
        turn_number: int,
        phase: str,
    ) -> AuthoritativeSkillRuntime:
        """Revoke active dynamic grants matching predicate and return a new runtime."""
        updated_grants: dict[str, tuple[DynamicSkillGrant, ...]] = {}
        for pid, grants in self._dynamic_grants.items():
            new_list: list[DynamicSkillGrant] = []
            for g in grants:
                if g.active and predicate(g):
                    new_list.append(g.revoke(reason, turn_number, phase))
                else:
                    new_list.append(g)
            updated_grants[pid] = tuple(new_list)
        updated_skills = {
            pid: dict(skills) for pid, skills in self._player_skills.items()
        }
        for pid, grants in updated_grants.items():
            active_dynamic_skill_ids = {
                grant.target_skill_id
                for grant in grants
                if grant.active
            }
            for skill_id, skill_state in tuple(
                updated_skills.get(pid, {}).items()
            ):
                if (
                    skill_state.source.startswith("dynamic_grant:")
                    and skill_id not in active_dynamic_skill_ids
                ):
                    updated_skills[pid].pop(skill_id, None)
        return AuthoritativeSkillRuntime(
            self._registry, updated_skills, updated_grants
        )

    def reconcile_qianchong_grants(
        self,
        player_id: str,
        condition: str,
        turn_number: int,
        phase: str,
    ) -> tuple[AuthoritativeSkillRuntime, tuple[DynamicSkillGrant, ...], tuple[DynamicSkillGrant, ...]]:
        """Atomically reconcile Qianchong dynamic grants for player_id.

        Transitions:
        - "all_black" -> active grant: sgs_skill_weimu (revoke mingzhe if active)
        - "all_red" -> active grant: sgs_skill_mingzhe (revoke weimu if active)
        - "none" / "mixed" / "empty" -> revoke any active Qianchong grant

        Guarantees atomic transition without exposing intermediate dual-skill states.
        """
        target_skill: str | None = None
        if condition == "all_black":
            target_skill = "sgs_skill_weimu"
        elif condition == "all_red":
            target_skill = "sgs_skill_mingzhe"

        current_grants = list(self._dynamic_grants.get(player_id, ()))
        active_qianchong = [
            g for g in current_grants if g.active and g.source_skill_id == "sgs_skill_qianchong"
        ]

        if target_skill is None:
            if not active_qianchong:
                return self, (), ()
        else:
            if (
                len(active_qianchong) == 1
                and active_qianchong[0].target_skill_id == target_skill
                and active_qianchong[0].condition_identity == condition
            ):
                return self, (), ()

        revoked: list[DynamicSkillGrant] = []
        granted: list[DynamicSkillGrant] = []
        new_grants_list: list[DynamicSkillGrant] = []

        for g in current_grants:
            if g.active and g.source_skill_id == "sgs_skill_qianchong":
                if target_skill is None or g.target_skill_id != target_skill:
                    revoked_g = g.revoke("qianchong_equipment_condition_changed", turn_number, phase)
                    new_grants_list.append(revoked_g)
                    revoked.append(revoked_g)
                else:
                    new_grants_list.append(g)
            else:
                new_grants_list.append(g)

        if target_skill is not None:
            has_active_target = any(
                g.active and g.source_skill_id == "sgs_skill_qianchong" and g.target_skill_id == target_skill
                for g in new_grants_list
            )
            if not has_active_target:
                new_grant = DynamicSkillGrant(
                    grant_id=f"grant:{player_id}:sgs_skill_qianchong:{target_skill}:{condition}:{turn_number}:{phase}:{len(new_grants_list)}",
                    owner_id=player_id,
                    source_skill_id="sgs_skill_qianchong",
                    target_skill_id=target_skill,
                    lifetime_kind="conditional",
                    condition_identity=condition,
                    created_turn_number=turn_number,
                    created_phase=phase,
                    active=True,
                )
                new_grants_list.append(new_grant)
                granted.append(new_grant)

        updated_grants = dict(self._dynamic_grants)
        updated_grants[player_id] = tuple(new_grants_list)
        updated_skills = {
            pid: dict(skills) for pid, skills in self._player_skills.items()
        }
        active_dynamic_skill_ids = {
            grant.target_skill_id
            for grant in new_grants_list
            if grant.active
            and grant.source_skill_id == "sgs_skill_qianchong"
        }
        for skill_id, skill_state in tuple(
            updated_skills.get(player_id, {}).items()
        ):
            if (
                skill_state.source == "dynamic_grant:sgs_skill_qianchong"
                and skill_id not in active_dynamic_skill_ids
            ):
                updated_skills[player_id].pop(skill_id, None)
        new_runtime = AuthoritativeSkillRuntime(
            self._registry, updated_skills, updated_grants
        )
        return new_runtime, tuple(granted), tuple(revoked)

    def on_phase_change(self, new_phase: str) -> AuthoritativeSkillRuntime:
        """Reset uses_this_phase to 0 for all skills across all players."""
        updated: dict[str, dict[str, SkillRuntimeState]] = {}
        for pid, skills_map in self._player_skills.items():
            updated[pid] = {
                sid: state.with_reset_phase() for sid, state in skills_map.items()
            }
        return AuthoritativeSkillRuntime(self._registry, updated, self._dynamic_grants)

    def on_turn_change(
        self, new_turn_player_id: str, *, is_extra_turn: bool = False
    ) -> AuthoritativeSkillRuntime:
        """Reset uses_this_turn and uses_this_phase to 0 for all skills across all players."""
        updated: dict[str, dict[str, SkillRuntimeState]] = {}
        for pid, skills_map in self._player_skills.items():
            updated[pid] = {
                sid: state.with_reset_turn() for sid, state in skills_map.items()
            }
        return AuthoritativeSkillRuntime(self._registry, updated, self._dynamic_grants)

    def invalidate_skill(
        self, player_id: str, skill_id: str, reason: str = "技能失效"
    ) -> AuthoritativeSkillRuntime:
        state = self.get_skill_state(player_id, skill_id)
        updated = {pid: dict(s) for pid, s in self._player_skills.items()}
        updated[player_id][skill_id] = state.invalidate(reason)
        return AuthoritativeSkillRuntime(self._registry, updated, self._dynamic_grants)

    def recover_skill(
        self, player_id: str, skill_id: str
    ) -> AuthoritativeSkillRuntime:
        state = self.get_skill_state(player_id, skill_id)
        updated = {pid: dict(s) for pid, s in self._player_skills.items()}
        updated[player_id][skill_id] = state.recover_invalidation()
        return AuthoritativeSkillRuntime(self._registry, updated, self._dynamic_grants)

    def lose_skill(
        self, player_id: str, skill_id: str
    ) -> AuthoritativeSkillRuntime:
        state = self.get_skill_state(player_id, skill_id)
        updated = {pid: dict(s) for pid, s in self._player_skills.items()}
        updated[player_id][skill_id] = state.lose()
        return AuthoritativeSkillRuntime(self._registry, updated, self._dynamic_grants)

    def increment_usage(
        self, player_id: str, skill_id: str
    ) -> AuthoritativeSkillRuntime:
        """Return a new runtime with phase/turn/game usage incremented by 1."""
        state = self.get_skill_state(player_id, skill_id)
        updated = {pid: dict(s) for pid, s in self._player_skills.items()}
        updated.setdefault(player_id, {})[skill_id] = state.with_usage_increment()
        return AuthoritativeSkillRuntime(self._registry, updated, self._dynamic_grants)

    def with_skill_state(
        self, player_id: str, skill_id: str, state: SkillRuntimeState
    ) -> AuthoritativeSkillRuntime:
        """Replace exactly one registered runtime state."""
        current = self.get_skill_state(player_id, skill_id)
        if state.owner_id != player_id or state.skill_id != skill_id:
            raise ValueError("替换的技能状态与角色/技能身份不一致")
        if state.skill_version != current.skill_version:
            raise ValueError("替换的技能状态版本不一致")
        updated = {pid: dict(s) for pid, s in self._player_skills.items()}
        updated[player_id][skill_id] = state
        return AuthoritativeSkillRuntime(self._registry, updated, self._dynamic_grants)

    def resolve_target_effect_after_card_used(
        self,
        event: GameEvent,
        state: GameState,
        turn_number: int,
    ) -> tuple[
        AuthoritativeSkillRuntime,
        tuple[tuple[str, str, bool, tuple[GameEvent, ...]], ...],
    ]:
        """Resolve mandatory ON_BECOME_TARGET handlers in stable order."""
        runtime = self
        resolved: list[tuple[str, str, bool, tuple[GameEvent, ...]]] = []
        for player_id in self._all_player_ids():
            eff_map = runtime.get_effective_skill_map(player_id)
            for skill_id in sorted(eff_map):
                skill_state = eff_map[skill_id]
                if not skill_state.effective:
                    continue
                definition = self._registry.get_skill(skill_id)
                if (
                    definition.kind is not AuthoritativeSkillKind.TRIGGERED
                    or not definition.is_mandatory
                    or SkillTimingWindow.ON_BECOME_TARGET not in definition.timing_windows
                ):
                    continue
                handler = self._registry.get_handler(skill_id)
                result = handler.resolve_target_effect_after_card_used(
                    event=event,
                    state=state,
                    skill_state=skill_state,
                    turn_number=turn_number,
                )
                if result is None:
                    continue
                next_skill_state, ineffective, events = result
                runtime = runtime.with_skill_state(
                    player_id, skill_id, next_skill_state
                )
                resolved.append(
                    (player_id, skill_id, ineffective, tuple(events))
                )
        return runtime, tuple(resolved)

    def enumerate_active_skill_actions(
        self,
        actor_id: str,
        context: ActionContext,
        state: GameState,
    ) -> tuple[LegalAction, ...]:
        """Enumerate active skill actions available to actor_id in current context."""
        eff_map = self.get_effective_skill_map(actor_id)
        actions: list[LegalAction] = []

        for skill_id in sorted(eff_map):
            skill_state = eff_map[skill_id]
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
        grants_dict: dict[str, object] = {}
        for pid in sorted(self._dynamic_grants):
            grants_dict[pid] = [
                g.to_dict()
                for g in sorted(self._dynamic_grants[pid], key=lambda x: x.grant_id)
            ]
        return {
            "registry_identity": self._registry.registry_identity,
            "player_skills": players,
            "dynamic_grants": grants_dict,
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
                valid_targets.append(target_id)
                continue
            eff_map = self.get_effective_skill_map(target_id)
            prohibited = False
            for skill_id in sorted(eff_map):
                skill_state = eff_map[skill_id]
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
                continue
            eff_map = self.get_effective_skill_map(target_id)
            for skill_id in sorted(eff_map):
                skill_state = eff_map[skill_id]
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

        try:
            from .multiplayer import PlayerTopology
            player_order = PlayerTopology.from_state(state).alive_ring_from(turn_player_id)
        except Exception:
            player_order = tuple(self._all_player_ids())

        for pid in player_order:
            eff_map = self.get_effective_skill_map(pid)
            for skill_id in sorted(eff_map):
                skill_state = eff_map[skill_id]
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
        new_runtime = AuthoritativeSkillRuntime(self._registry, updated_runtime_skills, self._dynamic_grants)

        return new_state, new_runtime, events
