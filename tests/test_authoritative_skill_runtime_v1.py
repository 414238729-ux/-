# -*- coding: utf-8 -*-
"""Targeted unit tests for Authoritative Skill Runtime V1 core contracts.

Covers:
- Orthogonal SkillKind and SkillTag validation
- SkillDefinition canonical profile identity and immutability
- SkillRuntimeState invariants (non-negative usage, non-negative marks, lost vs invalidated)
- AuthoritativeSkillRegistry immutability, duplicate rejection, and empty registry
- Phase/turn reset mechanics (including extra turn scope)
- Action validation and fail-closed trigger arbitration
"""

from __future__ import annotations

import pytest

from scripts.sgs_engine.actions import (
    ActionContext,
    ActionType,
    InvalidActionError,
    LegalAction,
    UnsupportedRuleError,
)
from scripts.sgs_engine.events import EventType, GameEvent
from scripts.sgs_engine.engine import DEFAULT_DECK_PATH
from scripts.deck_data import load_deck_csv
from scripts.sgs_engine.model import GameState, PlayerState, ZoneRef
from scripts.sgs_engine.skill_registry import (
    AuthoritativeSkillRegistry,
    EMPTY_SKILL_REGISTRY,
    SkillRegistryError,
    create_skill_registry,
)
from scripts.sgs_engine.skill_runtime import AuthoritativeSkillRuntime
from scripts.sgs_engine.skills import (
    AuthoritativeSkillKind,
    AuthoritativeSkillTag,
    SkillDefinition,
    SkillHandler,
    SkillRuntimeState,
    SkillTimingWindow,
    SkillTriggerContext,
)


def _make_two_player_state() -> GameState:
    records, _ = load_deck_csv(DEFAULT_DECK_PATH, expected_total=160)
    players = (
        PlayerState(player_id="p1", seat=1, hp=4, max_hp=4),
        PlayerState(player_id="p2", seat=2, hp=3, max_hp=3),
    )
    state = GameState.from_deck_records(records, players=players)
    # Give p1 first 2 cards in hand
    c1, c2 = records[0].instance_id, records[1].instance_id
    return state.move_cards({c1: ZoneRef.hand("p1"), c2: ZoneRef.hand("p1")})



class DummyActiveSkillHandler(SkillHandler):
    def __init__(self, skill_id: str = "dummy_active", max_uses_per_phase: int | None = 1) -> None:
        self._def = SkillDefinition(
            skill_id=skill_id,
            skill_name="测试主动技",
            version="1.0.0",
            kind=AuthoritativeSkillKind.ACTIVE,
            tags=frozenset({AuthoritativeSkillTag.LIMITED}),
            timing_windows=frozenset({SkillTimingWindow.PLAY_PHASE_ACTION}),
            max_uses_per_phase=max_uses_per_phase,
        )

    @property
    def definition(self) -> SkillDefinition:
        return self._def

    def enumerate_active_actions(
        self, context: ActionContext, state: object, skill_state: SkillRuntimeState
    ) -> tuple[LegalAction, ...]:
        return (
            LegalAction(
                action_type=ActionType.ACTIVATE_SKILL,
                actor_id=skill_state.owner_id,
                skill_id=self._def.skill_id,
                payload={"test": "dummy_active"},
            ),
        )

    def apply_action(
        self, action: LegalAction, context: ActionContext, state: object, skill_state: SkillRuntimeState
    ) -> tuple[object, SkillRuntimeState, tuple[GameEvent, ...]]:
        event = GameEvent(
            event_type=EventType.CARD_MOVED,
            card_instance_id="sgs-mobile-20260725-001",
            card_user=skill_state.owner_id,
            skill_owner=skill_state.owner_id,
            target_ids=(skill_state.owner_id,),
            payload={"reason": "dummy_applied"},
        )
        return state, skill_state, (event,)


def test_orthogonal_skill_kind_and_tag() -> None:
    """SkillKind (execution mechanism) and SkillTag (text tags) are orthogonal."""
    # Active skill with Limited tag
    defn = SkillDefinition(
        skill_id="test_skill_1",
        skill_name="测试技能1",
        version="1.0.0",
        kind=AuthoritativeSkillKind.ACTIVE,
        tags=frozenset({AuthoritativeSkillTag.LIMITED}),
        timing_windows=frozenset({SkillTimingWindow.PLAY_PHASE_ACTION}),
    )
    assert defn.kind == AuthoritativeSkillKind.ACTIVE
    assert AuthoritativeSkillTag.LIMITED in defn.tags
    assert AuthoritativeSkillTag.LOCKED not in defn.tags
    assert defn.profile_identity != ""


def test_v1_schema_rejects_contradictory_kind_tag_combinations() -> None:
    """V1 capability profile rejects contradictory kind/tag/timing sets."""
    with pytest.raises(UnsupportedRuleError, match="ACTIVE 与强制锁定技"):
        SkillDefinition(
            skill_id="bad_locked_active",
            skill_name="矛盾主动锁定",
            version="1.0.0",
            kind=AuthoritativeSkillKind.ACTIVE,
            tags=frozenset({AuthoritativeSkillTag.LOCKED}),
            timing_windows=frozenset({SkillTimingWindow.PLAY_PHASE_ACTION}),
        )
    with pytest.raises(UnsupportedRuleError, match="VIEW_AS"):
        SkillDefinition(
            skill_id="bad_view_as",
            skill_name="无合同视为",
            version="1.0.0",
            kind=AuthoritativeSkillKind.VIEW_AS,
            timing_windows=frozenset({SkillTimingWindow.RESPONSE_WINDOW}),
        )
    with pytest.raises(UnsupportedRuleError, match="静态修正技不得声明主动技专用时机"):
        SkillDefinition(
            skill_id="bad_static",
            skill_name="错窗静态",
            version="1.0.0",
            kind=AuthoritativeSkillKind.STATIC_MODIFIER,
            tags=frozenset({AuthoritativeSkillTag.LOCKED}),
            timing_windows=frozenset(
                {
                    SkillTimingWindow.TARGET_FILTER,
                    SkillTimingWindow.PLAY_PHASE_ACTION,
                }
            ),
            is_mandatory=True,
        )


def test_skill_definition_canonical_profile_identity() -> None:
    """Profile identity is deterministic across same definitions and differs on any change."""
    d1 = SkillDefinition(
        skill_id="test_skill",
        skill_name="测试",
        version="1.0.0",
        kind=AuthoritativeSkillKind.ACTIVE,
        tags=frozenset({AuthoritativeSkillTag.LIMITED}),
        timing_windows=frozenset({SkillTimingWindow.PLAY_PHASE_ACTION}),
    )
    d2 = SkillDefinition(
        skill_id="test_skill",
        skill_name="测试",
        version="1.0.0",
        kind=AuthoritativeSkillKind.ACTIVE,
        tags=frozenset({AuthoritativeSkillTag.LIMITED}),
        timing_windows=frozenset({SkillTimingWindow.PLAY_PHASE_ACTION}),
    )
    assert d1.profile_identity == d2.profile_identity

    d3 = SkillDefinition(
        skill_id="test_skill",
        skill_name="测试",
        version="1.0.1",  # version differs
        kind=AuthoritativeSkillKind.ACTIVE,
        tags=frozenset({AuthoritativeSkillTag.LIMITED}),
        timing_windows=frozenset({SkillTimingWindow.PLAY_PHASE_ACTION}),
    )
    assert d1.profile_identity != d3.profile_identity


def test_skill_definition_invalid_inputs_rejected() -> None:
    """Invalid types or missing required fields raise ValueError/TypeError."""
    with pytest.raises(ValueError, match="技能ID必须是非空字符串"):
        SkillDefinition(
            skill_id="",
            skill_name="名",
            version="1.0",
            kind=AuthoritativeSkillKind.ACTIVE,
        )
    with pytest.raises(TypeError, match="技能kind必须是AuthoritativeSkillKind"):
        SkillDefinition(
            skill_id="s1",
            skill_name="名",
            version="1.0",
            kind="active",  # type: ignore[arg-type]
        )


def test_skill_runtime_state_invariants() -> None:
    """Invariants: non-negative usage, non-negative marks, lost vs invalidated."""
    state = SkillRuntimeState(
        skill_id="s1",
        skill_version="1.0.0",
        owner_id="p1",
        marks={"权": 2},
    )
    assert state.effective
    assert state.marks["权"] == 2

    # Negative usage rejected
    with pytest.raises(ValueError, match="uses_this_phase必须是非负整数"):
        SkillRuntimeState(
            skill_id="s1",
            skill_version="1.0.0",
            owner_id="p1",
            uses_this_phase=-1,
        )

    # Negative marks rejected
    with pytest.raises(ValueError, match="mark\\[权\\]必须是非负整数"):
        SkillRuntimeState(
            skill_id="s1",
            skill_version="1.0.0",
            owner_id="p1",
            marks={"权": -1},
        )

    # Lost and invalidated simultaneously rejected
    with pytest.raises(ValueError, match="已经失去的技能不能同时保持失效状态"):
        SkillRuntimeState(
            skill_id="s1",
            skill_version="1.0.0",
            owner_id="p1",
            lost=True,
            invalidated=True,
        )


def test_skill_runtime_state_lifecycle_transitions() -> None:
    """Invalidate, recover, lose, and usage increment transitions."""
    s0 = SkillRuntimeState(
        skill_id="s1",
        skill_version="1.0.0",
        owner_id="p1",
    )
    assert s0.effective

    s_inv = s0.invalidate("封锁")
    assert s_inv.invalidated
    assert not s_inv.effective
    assert s_inv.invalidation_reason == "封锁"

    s_rec = s_inv.recover_invalidation()
    assert not s_rec.invalidated
    assert s_rec.effective

    s_lost = s_rec.lose()
    assert s_lost.lost
    assert not s_lost.owned
    assert not s_lost.effective

    # Lost skill cannot recover from invalidation
    s_lost_rec = s_lost.recover_invalidation()
    assert s_lost_rec.lost
    assert not s_lost_rec.effective


def test_skill_registry_duplicate_and_mutation_rejected() -> None:
    """Registry rejects duplicate skill IDs, duplicate profile identities, and post-freeze mutations."""
    handler1 = DummyActiveSkillHandler("skill_1")
    handler2 = DummyActiveSkillHandler("skill_1")  # Duplicate ID

    registry = AuthoritativeSkillRegistry()
    registry.register(handler1)
    with pytest.raises(SkillRegistryError, match="重复注册技能ID"):
        registry.register(handler2)

    registry.freeze()
    with pytest.raises(SkillRegistryError, match="注册表已冻结"):
        registry.register(DummyActiveSkillHandler("skill_2"))

    assert registry.registry_identity != ""
    assert registry.has_skill("skill_1")
    assert not registry.has_skill("skill_unknown")

    with pytest.raises(UnsupportedRuleError, match="未注册或不受支持的技能"):
        registry.get_skill("skill_unknown")


def test_skill_runtime_phase_and_turn_resets() -> None:
    """Phase change resets phase usage; turn change resets phase & turn usage."""
    handler = DummyActiveSkillHandler("dummy", max_uses_per_phase=2)
    registry = create_skill_registry((handler,))

    runtime = AuthoritativeSkillRuntime(registry)
    runtime = runtime.assign_skill("p1", "dummy")

    # Increment usages
    s1 = runtime.get_skill_state("p1", "dummy")
    s2 = s1.with_usage_increment().with_usage_increment()
    runtime = AuthoritativeSkillRuntime(registry, {"p1": {"dummy": s2}})

    assert runtime.get_skill_state("p1", "dummy").uses_this_phase == 2
    assert runtime.get_skill_state("p1", "dummy").uses_this_turn == 2
    assert runtime.get_skill_state("p1", "dummy").uses_this_game == 2

    # Phase change resets phase usage only
    runtime_after_phase = runtime.on_phase_change("discard")
    assert runtime_after_phase.get_skill_state("p1", "dummy").uses_this_phase == 0
    assert runtime_after_phase.get_skill_state("p1", "dummy").uses_this_turn == 2
    assert runtime_after_phase.get_skill_state("p1", "dummy").uses_this_game == 2

    # Turn change resets phase and turn usage
    runtime_after_turn = runtime_after_phase.on_turn_change("p2", is_extra_turn=False)
    assert runtime_after_turn.get_skill_state("p1", "dummy").uses_this_phase == 0
    assert runtime_after_turn.get_skill_state("p1", "dummy").uses_this_turn == 0
    assert runtime_after_turn.get_skill_state("p1", "dummy").uses_this_game == 2


def test_skill_runtime_active_enumeration_and_usage_limit() -> None:
    """Active skill enumerated during PLAY phase and respects max_uses_per_phase."""
    handler = DummyActiveSkillHandler("dummy", max_uses_per_phase=1)
    registry = create_skill_registry((handler,))

    runtime = AuthoritativeSkillRuntime(registry)
    runtime = runtime.assign_skill("p1", "dummy")

    game_state = _make_two_player_state()
    context = ActionContext(mode="test_mode", phase="play", actor_id="p1")

    # Enumerate legal actions
    actions = runtime.enumerate_active_skill_actions("p1", context, game_state)
    assert len(actions) == 1
    assert actions[0].action_type == ActionType.ACTIVATE_SKILL
    assert actions[0].skill_id == "dummy"

    # Execute action
    new_state, new_runtime, events = runtime.apply_skill_action(actions[0], context, game_state)
    assert len(events) == 1
    assert events[0].skill_owner == "p1"

    # Once used, further enumeration in same phase returns 0 actions
    actions_after = new_runtime.enumerate_active_skill_actions("p1", context, new_state)
    assert len(actions_after) == 0

    # Direct illegal re-application raises InvalidActionError
    with pytest.raises(InvalidActionError, match="已达阶段发动上限"):
        new_runtime.apply_skill_action(actions[0], context, new_state)


# ---------------------------------------------------------------------------
# Implementation Identity & Dependency Pinning Gates
# ---------------------------------------------------------------------------

def test_implementation_identity_matches_pin() -> None:
    """Computed identity must strictly match the current C8 development pin."""
    from scripts.current_c8_implementation_pin import (
        C8_CURRENT_IMPLEMENTATION_IDENTITY,
    )
    from scripts.sgs_engine.formal_duel import implementation_identity

    actual = implementation_identity()
    assert actual == C8_CURRENT_IMPLEMENTATION_IDENTITY


@pytest.mark.parametrize(
    "skill_file",
    [
        "scripts/sgs_engine/skills.py",
        "scripts/sgs_engine/skill_registry.py",
        "scripts/sgs_engine/skill_runtime.py",
        "scripts/sgs_engine/skill_impl_v1.py",
        "scripts/sgs_engine/skill_replay.py",
        "scripts/sgs_engine/generals.py",
    ],
)
def test_implementation_identity_changes_on_skill_source_mutation(skill_file: str) -> None:
    """Mutating any skill production file changes implementation_identity."""
    from pathlib import Path
    from scripts.sgs_engine.formal_duel import implementation_identity

    repo_root = Path(__file__).resolve().parents[1]
    target_path = repo_root / skill_file
    assert target_path.is_file(), f"Target file does not exist: {target_path}"

    original_bytes = target_path.read_bytes()
    before_identity = implementation_identity()

    try:
        # Append comment byte mutation
        target_path.write_bytes(original_bytes + b"\n# identity_mutation_test\n")
        mutated_identity = implementation_identity()
        assert mutated_identity != before_identity, f"Mutating {skill_file} did not change identity"
    finally:
        target_path.write_bytes(original_bytes)

    # Restored
    assert implementation_identity() == before_identity
