# -*- coding: utf-8 -*-
"""PRODUCTION INTEGRATION tests for the skill opt-in seam (P1).

These tests must go through ProductionBasicCardBatch.legal_actions → signed
action_id → session.step. They are not component tests.
"""

from __future__ import annotations

import pytest

from scripts.sgs_engine.actions import (
    ActionType,
    InvalidActionError,
    LegalAction,
)
from scripts.sgs_engine.events import EventType
from scripts.sgs_engine.formal_duel import (
    FormalDuelConfiguration,
    FormalNoSkillDuelSession,
)
from scripts.sgs_engine.model import ZoneRef
from scripts.sgs_engine.production_batch import (
    BatchActionIdController,
    ProductionBasicCardBatch,
    ProductionBatchError,
    ProductionPhase,
)
from scripts.sgs_engine.production_cards import hand_limit_of
from scripts.sgs_engine.skill_impl_v1 import PojiangSkillHandler
from scripts.sgs_engine.skill_registry import create_skill_registry
from scripts.sgs_engine.skills import (
    AuthoritativeSkillKind,
    SkillDefinition,
    SkillHandler,
    SkillRuntimeState,
    SkillTimingWindow,
)
from scripts.sgs_engine.actions import ActionContext


class _P1ProbeDrawHandler(SkillHandler):
    """Test-only ACTIVE probe. Not a Knowledge general skill."""

    def __init__(self) -> None:
        self._definition = SkillDefinition(
            skill_id="sgs_skill_p1_probe_draw",
            skill_name="P1探测摸牌",
            version="1.0.0",
            kind=AuthoritativeSkillKind.ACTIVE,
            timing_windows=frozenset({SkillTimingWindow.PLAY_PHASE_ACTION}),
            max_uses_per_phase=1,
            description="P1 seam probe: 出牌阶段限一次，经生产摸牌事务摸一张牌。",
        )

    @property
    def definition(self) -> SkillDefinition:
        return self._definition

    def enumerate_active_actions(
        self, context: ActionContext, state: object, skill_state: SkillRuntimeState
    ) -> tuple[LegalAction, ...]:
        return (
            LegalAction(
                action_type=ActionType.ACTIVATE_SKILL,
                actor_id=skill_state.owner_id,
                skill_id=self._definition.skill_id,
                payload={"probe": "draw_one"},
            ),
        )

    def apply_action(
        self, action: LegalAction, context: ActionContext, state: object, skill_state: SkillRuntimeState
    ) -> tuple[object, SkillRuntimeState, tuple]:
        raise AssertionError("production tests must not use component apply_action")

    def apply_in_production(
        self, session: object, action: LegalAction, context: ActionContext, state: object, skill_state: SkillRuntimeState
    ) -> object:
        return session.draw_cards_for_skill(
            state,
            skill_state.owner_id,
            1,
            reason="sgs_skill_p1_probe_draw",
            skill_owner=skill_state.owner_id,
        )


def _fresh_play(*args: object, **kwargs: object) -> ProductionBasicCardBatch:
    game = ProductionBasicCardBatch(*args, **kwargs)  # type: ignore[arg-type]
    for operation in ("proceed_prepare", "proceed_judgment", "proceed_draw"):
        action = next(
            item
            for item in game.legal_actions()
            if item.payload.get("operation") == operation
        )
        game.step(BatchActionIdController(action.action_id))
    assert game.phase is ProductionPhase.PLAY
    return game


def _skill_session() -> ProductionBasicCardBatch:
    registry = create_skill_registry((_P1ProbeDrawHandler(),))
    return _fresh_play(
        seed=1,
        skill_registry=registry,
        skill_assignments={"p1": ("sgs_skill_p1_probe_draw",)},
    )


def _semantic_actions(game: ProductionBasicCardBatch) -> tuple[tuple[object, ...], ...]:
    rows = []
    for action in game.legal_actions():
        rows.append(
            (
                action.action_type.value,
                action.actor_id,
                action.skill_id,
                action.card_instance_id,
                action.target_ids,
                action.payload.get("operation"),
                action.payload.get("card_key"),
            )
        )
    return tuple(rows)


def test_no_skill_session_does_not_construct_skill_runtime() -> None:
    game = _fresh_play(seed=1)
    assert game.skill_runtime is None
    assert all(action.skill_id is None for action in game.legal_actions())
    assert all(
        action.action_type is not ActionType.ACTIVATE_SKILL
        or action.payload.get("operation") != "activate_skill"
        for action in game.legal_actions()
    )


def test_no_skill_duel_constructor_does_not_accept_skill_fields() -> None:
    config = FormalDuelConfiguration.formal_profile()
    assert not hasattr(config, "skill_registry")
    session = FormalNoSkillDuelSession(configuration=config, seed=1)
    assert session.skill_runtime is None


def test_signed_active_skill_draw_uses_production_path() -> None:
    game = _skill_session()
    before_hand = len(game.state.card_ids_in(ZoneRef.hand("p1")))
    before_events = len(game.events)
    skill_actions = [
        action
        for action in game.legal_actions()
        if action.skill_id == "sgs_skill_p1_probe_draw"
        and action.action_type is ActionType.ACTIVATE_SKILL
    ]
    assert len(skill_actions) == 1
    chosen = skill_actions[0]
    assert chosen.action_id and chosen.action_id.startswith("act_")
    assert chosen.payload["operation"] == "activate_skill"
    assert chosen.payload["owner_id"] == "p1"
    game.step(BatchActionIdController(chosen.action_id))
    assert len(game.state.card_ids_in(ZoneRef.hand("p1"))) == before_hand + 1
    gained = [event for event in game.events[before_events:] if event.event_type is EventType.CARD_GAINED]
    moved = [event for event in game.events[before_events:] if event.event_type is EventType.CARD_MOVED]
    assert gained and gained[-1].skill_owner == "p1"
    assert gained[-1].sequence is not None
    assert moved and moved[-1].sequence is not None
    assert game.skill_runtime is not None
    assert game.skill_runtime.get_skill_state("p1", "sgs_skill_p1_probe_draw").uses_this_phase == 1
    assert not any(
        action.skill_id == "sgs_skill_p1_probe_draw" for action in game.legal_actions()
    )


def test_forged_and_stale_skill_actions_are_rejected() -> None:
    game = _skill_session()
    chosen = next(
        action
        for action in game.legal_actions()
        if action.skill_id == "sgs_skill_p1_probe_draw"
    )
    assert chosen.action_id is not None
    with pytest.raises((InvalidActionError, ProductionBatchError), match="过期或系伪造"):
        game.step(BatchActionIdController("act_" + "0" * 64))

    forged_payload = dict(chosen.payload)
    forged_payload["probe"] = "tampered"
    with pytest.raises(InvalidActionError):
        game._validate_session_action(
            game.state,
            game._context(),
            LegalAction(
                action_type=chosen.action_type,
                actor_id=chosen.actor_id,
                skill_id=chosen.skill_id,
                payload=forged_payload,
                action_id=chosen.action_id,
            ),
        )

    end_play = next(
        action
        for action in game.legal_actions()
        if action.payload.get("operation") == "end_play_phase"
    )
    game.step(BatchActionIdController(end_play.action_id))
    with pytest.raises((InvalidActionError, ProductionBatchError), match="过期或系伪造|不在当前最新合法"):
        game.step(BatchActionIdController(chosen.action_id))


def test_second_activation_same_play_phase_rejected() -> None:
    game = _skill_session()
    chosen = next(
        action
        for action in game.legal_actions()
        if action.skill_id == "sgs_skill_p1_probe_draw"
    )
    game.step(BatchActionIdController(chosen.action_id))
    assert not any(action.skill_id == "sgs_skill_p1_probe_draw" for action in game.legal_actions())
    with pytest.raises((InvalidActionError, ProductionBatchError), match="过期或系伪造|不在当前最新合法"):
        game.step(BatchActionIdController(chosen.action_id))


def test_play_phase_end_resets_skill_phase_usage() -> None:
    game = _skill_session()
    chosen = next(
        action
        for action in game.legal_actions()
        if action.skill_id == "sgs_skill_p1_probe_draw"
    )
    game.step(BatchActionIdController(chosen.action_id))
    assert game.skill_runtime is not None
    assert game.skill_runtime.get_skill_state("p1", "sgs_skill_p1_probe_draw").uses_this_phase == 1
    end_play = next(
        action
        for action in game.legal_actions()
        if action.payload.get("operation") == "end_play_phase"
    )
    game.step(BatchActionIdController(end_play.action_id))
    assert game.skill_runtime.get_skill_state("p1", "sgs_skill_p1_probe_draw").uses_this_phase == 0


def test_pojiang_production_give_draw_and_lose_hp() -> None:
    registry = create_skill_registry((PojiangSkillHandler(),))
    game = _fresh_play(
        seed=1,
        skill_registry=registry,
        skill_assignments={"p1": ("sgs_skill_pojiang",)},
    )
    chosen = next(
        action
        for action in game.legal_actions()
        if action.skill_id == "sgs_skill_pojiang"
    )
    material = chosen.card_instance_id
    target = chosen.target_ids[0]
    assert material
    p1_hand_before = len(game.state.card_ids_in(ZoneRef.hand("p1")))
    p2_hand_before = len(game.state.card_ids_in(ZoneRef.hand(target)))
    p1_hp_before = game.state.players_by_id["p1"].hp
    game.step(BatchActionIdController(chosen.action_id))
    assert material in game.state.card_ids_in(ZoneRef.hand(target))
    assert len(game.state.card_ids_in(ZoneRef.hand(target))) == p2_hand_before + 1
    assert len(game.state.card_ids_in(ZoneRef.hand("p1"))) == p1_hand_before - 1 + 3
    assert game.state.players_by_id["p1"].hp == p1_hp_before - 1
    assert any(event.event_type is EventType.CARD_LOST for event in game.events)
    assert any(
        event.event_type is EventType.LOSE_HP and event.payload.get("reason") == "sgs_skill_pojiang"
        for event in game.events
    )
    assert not any(action.skill_id == "sgs_skill_pojiang" for action in game.legal_actions())


def test_pojiang_drawn_cards_do_not_count_toward_discard_excess() -> None:
    registry = create_skill_registry((PojiangSkillHandler(),))
    game = _fresh_play(
        seed=1,
        skill_registry=registry,
        skill_assignments={"p1": ("sgs_skill_pojiang",)},
    )
    chosen = next(
        action
        for action in game.legal_actions()
        if action.skill_id == "sgs_skill_pojiang"
    )
    event_start = len(game.events)
    game.step(BatchActionIdController(chosen.action_id))
    drawn_ids = tuple(
        event.card_instance_id
        for event in game.events[event_start:]
        if event.event_type is EventType.CARD_GAINED
        and event.payload.get("reason") == "sgs_skill_pojiang"
        and event.target_ids == ("p1",)
        and event.card_instance_id is not None
    )
    assert len(drawn_ids) == 3
    assert frozenset(drawn_ids) == game._skill_hand_limit_exempt_ids
    hand_ids = tuple(game.state.card_ids_in(ZoneRef.hand("p1")))
    normal_limit = hand_limit_of(game.state, "p1")
    assert len(hand_ids) > normal_limit
    expected_excess = len(hand_ids) - normal_limit - len(drawn_ids)
    assert expected_excess > 0

    end_play = next(
        action
        for action in game.legal_actions()
        if action.payload.get("operation") == "end_play_phase"
    )
    game.step(BatchActionIdController(end_play.action_id))
    assert game.phase is ProductionPhase.DISCARD
    discard_actions = game.legal_actions()
    assert {
        action.payload["excess_count"]
        for action in discard_actions
        if action.payload.get("operation") == "select_discard_card"
    } == {expected_excess}

    non_exempt = [instance_id for instance_id in hand_ids if instance_id not in drawn_ids]
    selected: list[str] = []
    for instance_id in non_exempt[:expected_excess]:
        select = next(
            action
            for action in game.legal_actions()
            if action.payload.get("operation") == "select_discard_card"
            and action.card_instance_id == instance_id
        )
        selected.append(instance_id)
        game.step(BatchActionIdController(select.action_id))
    submit = next(
        action
        for action in game.legal_actions()
        if action.payload.get("operation") == "discard_phase_submit"
    )
    assert submit.payload["selected_count"] == expected_excess
    game.step(BatchActionIdController(submit.action_id))
    assert game.phase is ProductionPhase.END
    assert set(drawn_ids).issubset(game.state.card_ids_in(ZoneRef.hand("p1")))
    assert all(
        instance_id not in game.state.card_ids_in(ZoneRef.hand("p1"))
        for instance_id in selected
    )

    end_turn = next(
        action
        for action in game.legal_actions()
        if action.payload.get("operation") == "end_turn"
    )
    game.step(BatchActionIdController(end_turn.action_id))
    assert game.current_player_id == "p2"
    assert game._skill_hand_limit_exempt_ids == frozenset()
    # Extra-turn semantics are not implemented by the formal V1 session and
    # remain explicitly NOT_PROVEN; this test proves only the normal turn edge.


def test_no_skill_play_semantic_snapshot_unchanged() -> None:
    game = _fresh_play(seed=1)
    semantic = _semantic_actions(game)
    assert all(row[2] is None for row in semantic)
    assert any(row[5] == "end_play_phase" for row in semantic)
    clone = _fresh_play(seed=1)
    assert _semantic_actions(clone) == semantic
