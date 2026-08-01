from __future__ import annotations

from dataclasses import replace

import pytest

from scripts.sgs_engine.actions import (
    ActionContext,
    ActionType,
    InvalidActionError,
    LegalAction,
    RuleAdapter,
    RuleRegistrationError,
    RuleRegistry,
    UnsupportedRuleError,
    apply_action,
    enumerate_legal_actions,
    validate_action,
)
from scripts.sgs_engine.model import (
    DISCARD_PILE,
    CardInstance,
    GameState,
    PlayerState,
    ZoneRef,
)


def _state() -> GameState:
    card = CardInstance(
        instance_id="c1",
        deck_id="test-deck",
        card_key="slash",
        card_name="杀",
        card_type="基本牌",
        suit="黑桃",
        color="黑色",
        rank="7",
    )
    hand = ZoneRef.hand("p1")
    return GameState(
        cards=(card,),
        players=(
            PlayerState(player_id="p1", seat=1, hp=4, max_hp=4),
            PlayerState(player_id="p2", seat=2, hp=4, max_hp=4),
        ),
        card_locations={"c1": hand},
        zone_order={hand: ("c1",)},
    )


class DiscardAdapter(RuleAdapter):
    @property
    def adapter_version(self):
        return "tests.discard.v1"

    def audit_state(self):
        return {}

    def enumerate_legal_actions(self, state, context):
        if state.location_of("c1") == ZoneRef.hand(context.actor_id):
            return (
                LegalAction(
                    action_type=ActionType.MOVE_CARD,
                    actor_id=context.actor_id,
                    card_instance_id="c1",
                    payload={"destination": "discard_pile"},
                ),
            )
        return ()

    def apply_action(self, state, context, action):
        return state.move_card(action.card_instance_id, DISCARD_PILE)


class WrongActorAdapter(DiscardAdapter):
    def enumerate_legal_actions(self, state, context):
        return (LegalAction(action_type=ActionType.PASS, actor_id="p2"),)


class VersionedDiscardAdapter(DiscardAdapter):
    def __init__(self, version="tests.versioned.v1", *, option="default"):
        self.version = version
        self.option = option

    @property
    def adapter_version(self):
        return self.version

    def audit_state(self):
        return {"option": self.option}


class AuditStateMutatingAdapter(DiscardAdapter):
    def __init__(self):
        self.counter = 0

    @property
    def adapter_version(self):
        return "tests.audit-mutation.v1"

    def audit_state(self):
        return {"counter": self.counter}

    def enumerate_legal_actions(self, state, context):
        self.counter += 1
        return super().enumerate_legal_actions(state, context)


class GameStateMutatingAdapter(DiscardAdapter):
    @property
    def adapter_version(self):
        return "tests.state-mutation.v1"

    def enumerate_legal_actions(self, state, context):
        object.__setattr__(state, "revision", state.revision + 1)
        return super().enumerate_legal_actions(state, context)


class InvalidAuditStateAdapter(DiscardAdapter):
    @property
    def adapter_version(self):
        return "tests.invalid-audit.v1"

    def audit_state(self):
        return ["not", "a", "mapping"]


def _registry(adapter=None):
    registry = RuleRegistry()
    registry.register("duel", "play", adapter or DiscardAdapter())
    return registry


def _context(**changes):
    values = {"mode": "duel", "phase": "play", "actor_id": "p1"}
    values.update(changes)
    return ActionContext(**values)


def test_real_game_state_action_moves_card_and_is_stable():
    state = _state()
    registry = _registry()
    first = enumerate_legal_actions(state, _context(), registry)
    second = enumerate_legal_actions(state, _context(), registry)

    assert first == second
    assert len(first) == 1
    assert first[0].action_id.startswith("act_")

    updated = apply_action(state, _context(), first[0], registry)
    assert state.location_of("c1") == ZoneRef.hand("p1")
    assert updated.location_of("c1") == DISCARD_PILE
    assert updated.revision == state.revision + 1
    updated.assert_card_conservation()

    with pytest.raises(InvalidActionError, match="最新合法动作集合"):
        apply_action(updated, _context(), first[0], registry)


def test_validate_action_is_explicit_and_has_no_side_effects():
    state = _state()
    registry = _registry()
    issued = enumerate_legal_actions(state, _context(), registry)[0]

    canonical = validate_action(state, _context(), issued, registry)

    assert canonical == issued
    assert state.location_of("c1") == ZoneRef.hand("p1")
    assert state.revision == 0
    forged = replace(issued, payload={"destination": "hand"})
    with pytest.raises(InvalidActionError, match="伪造动作"):
        validate_action(state, _context(), forged, registry)


def test_missing_exact_mode_or_phase_fails_closed():
    state = _state()
    registry = _registry()
    with pytest.raises(UnsupportedRuleError, match="禁止空默认或近似"):
        enumerate_legal_actions(state, _context(mode="2v2"), registry)
    with pytest.raises(UnsupportedRuleError, match="禁止空默认或近似"):
        enumerate_legal_actions(state, _context(phase="response"), registry)


def test_duplicate_registration_cannot_silently_override():
    registry = _registry()
    with pytest.raises(RuleRegistrationError, match="禁止静默覆盖"):
        registry.register("duel", "play", DiscardAdapter())


def test_forged_action_and_wrong_actor_are_rejected():
    state = _state()
    registry = _registry()
    legal = enumerate_legal_actions(state, _context(), registry)[0]
    forged = replace(legal, payload={"destination": "hand"})
    with pytest.raises(InvalidActionError, match="伪造动作"):
        apply_action(state, _context(), forged, registry)

    wrong_actor_action = replace(legal, actor_id="p2")
    with pytest.raises(InvalidActionError, match="动作角色"):
        apply_action(state, _context(), wrong_actor_action, registry)

    with pytest.raises(InvalidActionError, match="不属于当前行动角色"):
        enumerate_legal_actions(state, _context(), _registry(WrongActorAdapter()))


def test_unknown_actor_and_stale_context_are_rejected():
    state = _state()
    registry = _registry()
    with pytest.raises(InvalidActionError, match="不存在"):
        enumerate_legal_actions(state, _context(actor_id="missing"), registry)
    with pytest.raises(InvalidActionError, match="状态版本"):
        enumerate_legal_actions(
            state,
            _context(expected_revision=state.revision + 1),
            registry,
        )


def test_action_id_binds_adapter_version_and_rejects_cross_version_action():
    state = _state()
    registry_v1 = _registry(VersionedDiscardAdapter("rules.v1"))
    registry_v2 = _registry(VersionedDiscardAdapter("rules.v2"))

    action_v1 = enumerate_legal_actions(state, _context(), registry_v1)[0]
    action_v2 = enumerate_legal_actions(state, _context(), registry_v2)[0]

    assert action_v1.action_id != action_v2.action_id
    with pytest.raises(InvalidActionError, match="最新合法动作集合"):
        apply_action(state, _context(), action_v1, registry_v2)


def test_action_id_binds_complete_registry_fingerprint():
    state = _state()
    registry = _registry()
    issued = enumerate_legal_actions(state, _context(), registry)[0]

    registry.register("duel", "response", VersionedDiscardAdapter("response.v1"))
    current = enumerate_legal_actions(state, _context(), registry)[0]

    assert issued.action_id != current.action_id
    with pytest.raises(InvalidActionError, match="最新合法动作集合"):
        apply_action(state, _context(), issued, registry)


def test_registered_adapter_version_cannot_change_silently():
    state = _state()
    adapter = VersionedDiscardAdapter("rules.v1")
    registry = _registry(adapter)
    enumerate_legal_actions(state, _context(), registry)

    adapter.version = "rules.v2"
    with pytest.raises(RuleRegistrationError, match="版本在注册后"):
        enumerate_legal_actions(state, _context(), registry)


def test_adapter_must_declare_nonempty_stable_version():
    registry = RuleRegistry()
    with pytest.raises(RuleRegistrationError, match="稳定的非空版本"):
        registry.register("duel", "play", VersionedDiscardAdapter("   "))


def test_adapter_audit_state_change_makes_an_issued_action_stale():
    state = _state()
    adapter = VersionedDiscardAdapter(option="normal")
    registry = _registry(adapter)
    issued = enumerate_legal_actions(state, _context(), registry)[0]

    adapter.option = "changed"
    current = enumerate_legal_actions(state, _context(), registry)[0]

    assert issued.action_id != current.action_id
    with pytest.raises(InvalidActionError, match="最新合法动作集合"):
        apply_action(state, _context(), issued, registry)


def test_enumeration_rejects_observable_adapter_side_effects():
    state = _state()
    with pytest.raises(InvalidActionError, match="可观察审计状态"):
        enumerate_legal_actions(
            state,
            _context(),
            _registry(AuditStateMutatingAdapter()),
        )


def test_enumeration_rejects_game_state_side_effects():
    state = _state()
    with pytest.raises(InvalidActionError, match="修改了传入GameState"):
        enumerate_legal_actions(
            state,
            _context(),
            _registry(GameStateMutatingAdapter()),
        )


def test_adapter_must_expose_json_mapping_audit_state():
    registry = RuleRegistry()
    with pytest.raises(TypeError, match="audit_state必须返回映射"):
        registry.register("duel", "play", InvalidAuditStateAdapter())
