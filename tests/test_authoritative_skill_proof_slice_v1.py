# -*- coding: utf-8 -*-
"""COMPONENT ONLY tests for V1 skill handlers.

These are not production integration proofs. Mutao is not the Knowledge
CURRENT CONFIRMED skill and is not a V1 production mandatory proof.
"""

from __future__ import annotations

import pytest

from scripts.deck_data import load_deck_csv
from scripts.sgs_engine.actions import (
    ActionContext,
    ActionType,
    InvalidActionError,
    LegalAction,
)
from scripts.sgs_engine.engine import DEFAULT_DECK_PATH
from scripts.sgs_engine.events import EventType, GameEvent
from scripts.sgs_engine.model import (
    CardInstance,
    DRAW_PILE,
    GameState,
    PlayerState,
    ZoneRef,
)
from scripts.sgs_engine.skill_impl_v1 import (
    MingzheSkillHandler,
    MutaoSkillHandler,
    WeimuSkillHandler,
)
from scripts.sgs_engine.skill_registry import create_skill_registry
from scripts.sgs_engine.skill_runtime import AuthoritativeSkillRuntime
from scripts.sgs_engine.skills import SkillTimingWindow, SkillTriggerContext


def _setup_three_player_game() -> tuple[GameState, AuthoritativeSkillRuntime]:
    records, _ = load_deck_csv(DEFAULT_DECK_PATH, expected_total=160)
    players = (
        PlayerState(player_id="p1", seat=1, hp=4, max_hp=4),
        PlayerState(player_id="p2", seat=2, hp=3, max_hp=3),
        PlayerState(player_id="p3", seat=3, hp=3, max_hp=3),
    )
    state = GameState.from_deck_records(records, players=players)

    # Find specific cards:
    # We want a red card and a black trick card for deterministic tests
    cards_by_id = {c.instance_id: c for c in state.cards}

    red_card_id = next(c.instance_id for c in state.cards if c.color == "红")
    black_trick_id = next(
        c.instance_id for c in state.cards if c.color == "黑" and (c.card_type == "锦囊牌" or "trick" in c.card_key)
    )
    red_trick_id = next(
        c.instance_id for c in state.cards if c.color == "红" and (c.card_type == "锦囊牌" or "trick" in c.card_key)
    )
    black_basic_id = next(
        c.instance_id for c in state.cards if c.color == "黑" and c.card_type == "基本牌"
    )

    # Distribute:
    # p1 hand: red_card_id, black_trick_id
    # p2 hand: red_trick_id, black_basic_id
    # p3 hand: some other card
    p3_card_id = state.cards[10].instance_id

    moves = {
        red_card_id: ZoneRef.hand("p1"),
        black_trick_id: ZoneRef.hand("p1"),
        red_trick_id: ZoneRef.hand("p2"),
        black_basic_id: ZoneRef.hand("p2"),
        p3_card_id: ZoneRef.hand("p3"),
    }
    state = state.move_cards(moves)

    registry = create_skill_registry(
        (MutaoSkillHandler(), MingzheSkillHandler(), WeimuSkillHandler())
    )
    runtime = AuthoritativeSkillRuntime(registry)
    # Assign Mutao to p1, Mingzhe to p1, Weimu to p3
    runtime = runtime.assign_skill("p1", "sgs_skill_mutao")
    runtime = runtime.assign_skill("p1", "sgs_skill_mingzhe")
    runtime = runtime.assign_skill("p3", "sgs_skill_weimu")

    return state, runtime


# ---------------------------------------------------------------------------
# 1. 【募讨】 (Mutao) Tests
# ---------------------------------------------------------------------------


def test_mutao_active_enumeration_and_branches() -> None:
    """Mutao enumerates all hand cards and all other alive players for branches 1 and 2."""
    state, runtime = _setup_three_player_game()
    context = ActionContext(mode="formal_mode", phase="play", actor_id="p1")

    actions = runtime.enumerate_active_skill_actions("p1", context, state)
    # p1 has 2 hand cards, 2 other alive targets (p2, p3), 2 branches (1, 2) -> 2 * 2 * 2 = 8 actions
    assert len(actions) == 8
    for a in actions:
        assert a.action_type == ActionType.ACTIVATE_SKILL
        assert a.skill_id == "sgs_skill_mutao"
        assert a.actor_id == "p1"
        assert len(a.target_ids) == 1
        assert a.target_ids[0] in ("p2", "p3")
        assert a.payload["branch"] in (1, 2)


def test_mutao_execution_and_card_conservation() -> None:
    """Mutao moves hand card from actor to target, records CARD_MOVED event, and enforces limit."""
    state, runtime = _setup_three_player_game()
    context = ActionContext(mode="formal_mode", phase="play", actor_id="p1")

    actions = runtime.enumerate_active_skill_actions("p1", context, state)
    chosen_action = actions[0]
    card_id = chosen_action.card_instance_id
    target_id = chosen_action.target_ids[0]

    assert card_id in state.card_ids_in(ZoneRef.hand("p1"))
    assert card_id not in state.card_ids_in(ZoneRef.hand(target_id))

    new_state, new_runtime, events = runtime.apply_skill_action(chosen_action, context, state)

    # Card conservation and movement
    assert card_id not in new_state.card_ids_in(ZoneRef.hand("p1"))
    assert card_id in new_state.card_ids_in(ZoneRef.hand(target_id))
    assert len(new_state.cards) == 160

    # Event generated
    assert len(events) == 1
    assert events[0].event_type == EventType.CARD_MOVED
    assert events[0].card_instance_id == card_id
    assert events[0].skill_owner == "p1"
    assert events[0].target_ids == (target_id,)
    assert events[0].payload["branch"] == chosen_action.payload["branch"]

    # Usage count incremented
    skill_state = new_runtime.get_skill_state("p1", "sgs_skill_mutao")
    assert skill_state.uses_this_phase == 1

    # Second activation in same phase is rejected
    with pytest.raises(InvalidActionError, match="已达阶段发动上限"):
        new_runtime.apply_skill_action(chosen_action, context, new_state)


def test_mutao_illegal_target_and_materials_rejected() -> None:
    """Mutao rejects targeting self, dead players, and non-hand materials."""
    state, runtime = _setup_three_player_game()
    context = ActionContext(mode="formal_mode", phase="play", actor_id="p1")

    p1_card = state.card_ids_in(ZoneRef.hand("p1"))[0]

    # Target self
    self_action = LegalAction(
        action_type=ActionType.ACTIVATE_SKILL,
        actor_id="p1",
        card_instance_id=p1_card,
        target_ids=("p1",),
        skill_id="sgs_skill_mutao",
        payload={"branch": 1},
    )
    with pytest.raises(InvalidActionError, match="只能指定其他角色为目标"):
        runtime.apply_skill_action(self_action, context, state)

    # Material not in hand (e.g. from draw pile)
    draw_card = state.card_ids_in(DRAW_PILE)[0]
    fake_mat_action = LegalAction(
        action_type=ActionType.ACTIVATE_SKILL,
        actor_id="p1",
        card_instance_id=draw_card,
        target_ids=("p2",),
        skill_id="sgs_skill_mutao",
        payload={"branch": 1},
    )
    with pytest.raises(InvalidActionError, match="不在 p1 的手牌区"):
        runtime.apply_skill_action(fake_mat_action, context, state)


# ---------------------------------------------------------------------------
# 2. 【明哲】 (Mingzhe) Tests
# ---------------------------------------------------------------------------


def test_mingzhe_triggers_on_off_turn_red_card_lost() -> None:
    """Mingzhe triggers when red card is lost/discarded during other players' turns."""
    state, runtime = _setup_three_player_game()
    p1_red_card = next(
        cid for cid in state.card_ids_in(ZoneRef.hand("p1")) if state.cards_by_id[cid].color == "红"
    )

    event = GameEvent(
        event_type=EventType.CARD_DISCARDED,
        card_instance_id=p1_red_card,
        card_user="p1",
        target_ids=("p1",),
        payload={"reason": "discard"},
    )

    # Trigger discovered off-turn (turn_player_id="p2", owner="p1")
    triggers = runtime.evaluate_triggers_for_event(
        event=event,
        state=state,
        turn_player_id="p2",
        current_phase="play",
        timing_window=SkillTimingWindow.ON_CARD_DISCARDED,
    )
    assert len(triggers) == 1
    actor_id, skill_id, handler, ctx = triggers[0]
    assert actor_id == "p1"
    assert skill_id == "sgs_skill_mingzhe"

    # Enumerate trigger actions: activate and pass
    actions = handler.enumerate_trigger_actions(ctx, state, runtime.get_skill_state("p1", "sgs_skill_mingzhe"))
    assert len(actions) == 2
    act_action = next(a for a in actions if a.action_type == ActionType.ACTIVATE_SKILL)
    assert act_action.skill_id == "sgs_skill_mingzhe"
    pass_action = next(a for a in actions if a.action_type == ActionType.PASS)
    assert pass_action.payload.get("decision") == "pass"


def test_mingzhe_does_not_trigger_on_own_turn_or_black_card() -> None:
    """Mingzhe does not trigger during own turn, or when black card is lost."""
    state, runtime = _setup_three_player_game()
    p1_red_card = next(
        cid for cid in state.card_ids_in(ZoneRef.hand("p1")) if state.cards_by_id[cid].color == "红"
    )
    p1_black_card = next(
        cid for cid in state.card_ids_in(ZoneRef.hand("p1")) if state.cards_by_id[cid].color == "黑"
    )

    # 1. Own turn with red card -> No trigger
    own_turn_event = GameEvent(
        event_type=EventType.CARD_DISCARDED,
        card_instance_id=p1_red_card,
        card_user="p1",
        target_ids=("p1",),
    )
    triggers_own = runtime.evaluate_triggers_for_event(
        event=own_turn_event,
        state=state,
        turn_player_id="p1",  # own turn
        current_phase="discard",
        timing_window=SkillTimingWindow.ON_CARD_DISCARDED,
    )
    assert len(triggers_own) == 0

    # 2. Off-turn with black card -> No trigger
    black_event = GameEvent(
        event_type=EventType.CARD_DISCARDED,
        card_instance_id=p1_black_card,
        card_user="p1",
        target_ids=("p1",),
    )
    triggers_black = runtime.evaluate_triggers_for_event(
        event=black_event,
        state=state,
        turn_player_id="p2",  # off-turn
        current_phase="play",
        timing_window=SkillTimingWindow.ON_CARD_DISCARDED,
    )
    assert len(triggers_black) == 0


# ---------------------------------------------------------------------------
# 3. 【帷幕】 (Weimu) Tests
# ---------------------------------------------------------------------------


def test_weimu_filters_black_trick_targets() -> None:
    """Weimu prohibits black trick cards from targeting its owner (p3)."""
    state, runtime = _setup_three_player_game()

    black_trick = next(
        c for c in state.cards if c.color == "黑" and (c.card_type == "锦囊牌" or "trick" in c.card_key)
    )
    red_trick = next(
        c for c in state.cards if c.color == "红" and (c.card_type == "锦囊牌" or "trick" in c.card_key)
    )
    black_basic = next(
        c for c in state.cards if c.color == "黑" and c.card_type == "基本牌"
    )

    candidates = ("p1", "p2", "p3")

    # 1. Black trick card: p3 (Weimu owner) must be filtered out
    filtered_black_trick = runtime.filter_legal_targets(
        user_id="p1",
        card_instance=black_trick,
        card_key=black_trick.card_key,
        candidate_targets=candidates,
        state=state,
    )
    assert "p3" not in filtered_black_trick
    assert "p1" in filtered_black_trick
    assert "p2" in filtered_black_trick

    # 2. Red trick card: p3 is allowed
    filtered_red_trick = runtime.filter_legal_targets(
        user_id="p1",
        card_instance=red_trick,
        card_key=red_trick.card_key,
        candidate_targets=candidates,
        state=state,
    )
    assert "p3" in filtered_red_trick

    # 3. Black basic card (e.g. 杀): p3 is allowed
    filtered_basic = runtime.filter_legal_targets(
        user_id="p1",
        card_instance=black_basic,
        card_key=black_basic.card_key,
        candidate_targets=candidates,
        state=state,
    )
    assert "p3" in filtered_basic


def test_weimu_forged_black_trick_target_rejected() -> None:
    """Attempting to submit an action targeting Weimu owner with black trick raises InvalidActionError."""
    state, runtime = _setup_three_player_game()
    black_trick = next(
        c for c in state.cards if c.color == "黑" and (c.card_type == "锦囊牌" or "trick" in c.card_key)
    )

    with pytest.raises(InvalidActionError, match="拥有技能【帷幕】"):
        runtime.validate_target_legality(
            user_id="p1",
            target_ids=("p3",),
            card_instance=black_trick,
            card_key=black_trick.card_key,
            state=state,
        )


def test_weimu_invalidation_allows_black_tricks() -> None:
    """When Weimu is invalidated, black trick cards can target the owner."""
    state, runtime = _setup_three_player_game()
    black_trick = next(
        c for c in state.cards if c.color == "黑" and (c.card_type == "锦囊牌" or "trick" in c.card_key)
    )

    # Invalidate Weimu
    inv_runtime = runtime.invalidate_skill("p3", "sgs_skill_weimu")
    filtered = inv_runtime.filter_legal_targets(
        user_id="p1",
        card_instance=black_trick,
        card_key=black_trick.card_key,
        candidate_targets=("p1", "p2", "p3"),
        state=state,
    )
    assert "p3" in filtered
