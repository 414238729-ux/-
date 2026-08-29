# -*- coding: utf-8 -*-
"""PRODUCTION EventQueue trigger tests for 【明哲】 and 【帷幕】 target filter."""

from __future__ import annotations

import pytest

from scripts.sgs_engine.actions import ActionType, InvalidActionError
from scripts.sgs_engine.events import EventType
from scripts.sgs_engine.model import ZoneRef
from scripts.sgs_engine.production_batch import (
    BatchActionIdController,
    ProductionBasicCardBatch,
    ProductionBatchError,
    ProductionPhase,
)
from scripts.sgs_engine.skill_impl_v1 import MingzheSkillHandler, WeimuSkillHandler
from scripts.sgs_engine.skill_registry import create_skill_registry


def _fresh_play(**kwargs: object) -> ProductionBasicCardBatch:
    game = ProductionBasicCardBatch(**kwargs)  # type: ignore[arg-type]
    for operation in ("proceed_prepare", "proceed_judgment", "proceed_draw"):
        action = next(
            item
            for item in game.legal_actions()
            if item.payload.get("operation") == operation
        )
        game.step(BatchActionIdController(action.action_id))
    assert game.phase is ProductionPhase.PLAY
    return game


def _step_op(game: ProductionBasicCardBatch, operation: str, **payload: object) -> object:
    for action in game.legal_actions():
        if action.payload.get("operation") != operation:
            continue
        if payload and any(action.payload.get(key) != value for key, value in payload.items()):
            continue
        game.step(BatchActionIdController(action.action_id))
        return action
    raise AssertionError(f"missing operation {operation} {payload}")


def test_weimu_excludes_owner_from_black_trick_targets() -> None:
    registry = create_skill_registry((WeimuSkillHandler(),))
    found = None
    for seed in range(1, 80):
        game = _fresh_play(
            seed=seed,
            skill_registry=registry,
            skill_assignments={"p2": ("sgs_skill_weimu",)},
        )
        black_trick_actions = [
            action
            for action in game.legal_actions()
            if action.card_instance_id
            and game.state.cards_by_id[action.card_instance_id].color == "黑"
            and game.state.cards_by_id[action.card_instance_id].card_type == "锦囊牌"
        ]
        if not any(
            action.payload.get("operation") == "use_guohe" for action in game.legal_actions()
        ):
            # Compare against a no-skill clone of the same seed.
            plain = _fresh_play(seed=seed)
            if any(a.payload.get("operation") == "use_guohe" for a in plain.legal_actions()):
                found = (seed, game, plain)
                break
        del black_trick_actions
    assert found is not None, "need a seed where p1 has 过河拆桥"
    seed, game, plain = found
    assert any(a.payload.get("operation") == "use_guohe" for a in plain.legal_actions())
    weimu_guohe = [
        a for a in game.legal_actions() if a.payload.get("operation") == "use_guohe"
    ]
    assert all("p2" not in a.target_ids for a in weimu_guohe)
    # Forged target from the no-skill legal set must be rejected after re-enumerate.
    stolen = next(a for a in plain.legal_actions() if a.payload.get("operation") == "use_guohe")
    with pytest.raises((InvalidActionError, ProductionBatchError)):
        game._validate_session_action(game.state, game._context(), stolen)


def test_weimu_allows_slash_and_red_tricks() -> None:
    registry = create_skill_registry((WeimuSkillHandler(),))
    basic_game = _fresh_play(
        seed=1,
        skill_registry=registry,
        skill_assignments={"p2": ("sgs_skill_weimu",)},
    )
    slash_to_p2 = [
        action
        for action in basic_game.legal_actions()
        if action.payload.get("operation") == "use_slash" and "p2" in action.target_ids
    ]
    assert slash_to_p2, "seed 1 必须确定性提供以 p2 为目标的基本牌【杀】"

    red_game = _fresh_play(
        seed=2,
        skill_registry=registry,
        skill_assignments={"p2": ("sgs_skill_weimu",)},
    )
    red_target = [
        action
        for action in red_game.legal_actions()
        if action.card_instance_id
        and red_game.state.cards_by_id[action.card_instance_id].color == "红"
        and red_game.state.cards_by_id[action.card_instance_id].card_type == "锦囊牌"
        and "p2" in action.target_ids
    ]
    assert red_target, "seed 2 必须确定性提供仍可指定 p2 的红色锦囊"
    assert all(
        red_game.state.cards_by_id[action.card_instance_id].color == "红"
        for action in red_target
    )


def test_weimu_invalidated_allows_black_trick_again() -> None:
    registry = create_skill_registry((WeimuSkillHandler(),))
    seed = 3
    plain = _fresh_play(seed=seed)
    assert any(
        a.payload.get("operation") == "use_guohe" and "p2" in a.target_ids
        for a in plain.legal_actions()
    )
    game = _fresh_play(
        seed=seed,
        skill_registry=registry,
        skill_assignments={"p2": ("sgs_skill_weimu",)},
    )
    assert not any(
        a.payload.get("operation") == "use_guohe" and "p2" in a.target_ids
        for a in game.legal_actions()
    )
    assert game.skill_runtime is not None
    game._skill_runtime = game.skill_runtime.invalidate_skill("p2", "sgs_skill_weimu")
    assert any(
        a.payload.get("operation") == "use_guohe" and "p2" in a.target_ids
        for a in game.legal_actions()
    )


def test_weimu_lost_allows_black_trick_again() -> None:
    registry = create_skill_registry((WeimuSkillHandler(),))
    game = _fresh_play(
        seed=3,
        skill_registry=registry,
        skill_assignments={"p2": ("sgs_skill_weimu",)},
    )
    assert not any(
        action.payload.get("operation") == "use_guohe" and "p2" in action.target_ids
        for action in game.legal_actions()
    )
    assert game.skill_runtime is not None
    game._skill_runtime = game.skill_runtime.lose_skill("p2", "sgs_skill_weimu")
    assert any(
        action.payload.get("operation") == "use_guohe" and "p2" in action.target_ids
        for action in game.legal_actions()
    )


def test_weimu_owner_death_stops_static_modifier_on_real_death_path() -> None:
    registry = create_skill_registry((WeimuSkillHandler(),))
    game = _fresh_play(
        seed=1,
        player_hp=(4, 1),
        player_max_hp=(4, 4),
        skill_registry=registry,
        skill_assignments={"p2": ("sgs_skill_weimu",)},
    )
    black_trick = next(
        card
        for card in game.state.cards
        if card.card_type == "锦囊牌" and card.color == "黑"
    )
    assert game.filter_targets_for_card(
        "p1", black_trick, black_trick.card_key, ("p2",)
    ) == ()
    slash = next(
        action
        for action in game.legal_actions()
        if action.payload.get("operation") == "use_slash" and "p2" in action.target_ids
    )
    game.step(BatchActionIdController(slash.action_id))
    for _ in range(12):
        if not game.state.players_by_id["p2"].alive:
            break
        pass_action = next(
            action
            for action in game.legal_actions()
            if action.action_type is ActionType.PASS
        )
        game.step(BatchActionIdController(pass_action.action_id))
    assert game.state.players_by_id["p2"].alive is False
    assert game.filter_targets_for_card(
        "p1", black_trick, black_trick.card_key, ("p2",)
    ) == ("p2",)


def test_weimu_confirmed_black_group_trick_scope_filters_owner() -> None:
    registry = create_skill_registry((WeimuSkillHandler(),))
    plain = _fresh_play(seed=3)
    assert any(
        action.payload.get("operation") == "use_nanman"
        for action in plain.legal_actions()
    )
    game = _fresh_play(
        seed=3,
        skill_registry=registry,
        skill_assignments={"p2": ("sgs_skill_weimu",)},
    )
    assert not any(
        action.payload.get("operation") == "use_nanman"
        for action in game.legal_actions()
    )


def test_weimu_black_delayed_trick_is_filtered_at_target_legality() -> None:
    registry = create_skill_registry((WeimuSkillHandler(),))
    plain = _fresh_play(seed=4)
    assert any(
        action.payload.get("operation") == "use_bingliang"
        and "p2" in action.target_ids
        for action in plain.legal_actions()
    )
    game = _fresh_play(
        seed=4,
        skill_registry=registry,
        skill_assignments={"p2": ("sgs_skill_weimu",)},
    )
    assert not any(
        action.payload.get("operation") == "use_bingliang"
        and "p2" in action.target_ids
        for action in game.legal_actions()
    )


def _mingzhe_red_dodge_seed() -> int:
    registry = create_skill_registry((MingzheSkillHandler(),))
    for seed in range(1, 150):
        game = _fresh_play(
            seed=seed,
            skill_registry=registry,
            skill_assignments={"p2": ("sgs_skill_mingzhe",)},
        )
        slash = next(
            (
                action
                for action in game.legal_actions()
                if action.payload.get("operation") == "use_slash"
                and "p2" in action.target_ids
            ),
            None,
        )
        if slash is None:
            continue
        game.step(BatchActionIdController(slash.action_id))
        dodge = next(
            (
                action
                for action in game.legal_actions()
                if action.payload.get("operation") == "play_dodge"
            ),
            None,
        )
        if dodge is None or dodge.card_instance_id is None:
            continue
        if game.state.cards_by_id[dodge.card_instance_id].color == "红":
            return seed
    raise AssertionError("no seed with p1 slash and p2 red dodge")


def _p2_respond_red_dodge(game: ProductionBasicCardBatch) -> None:
    slash = next(
        action
        for action in game.legal_actions()
        if action.payload.get("operation") == "use_slash" and "p2" in action.target_ids
    )
    game.step(BatchActionIdController(slash.action_id))
    dodge = next(
        action
        for action in game.legal_actions()
        if action.payload.get("operation") == "play_dodge"
    )
    game.step(BatchActionIdController(dodge.action_id))


def test_mingzhe_triggers_on_off_turn_use_and_draw() -> None:
    seed = _mingzhe_red_dodge_seed()
    registry = create_skill_registry((MingzheSkillHandler(),))
    game = _fresh_play(
        seed=seed,
        skill_registry=registry,
        skill_assignments={"p2": ("sgs_skill_mingzhe",)},
    )
    hand_before = len(game.state.card_ids_in(ZoneRef.hand("p2")))
    _p2_respond_red_dodge(game)
    assert game._skill_pending is not None
    assert game._skill_pending.skill_id == "sgs_skill_mingzhe"
    assert game._skill_pending.actor_id == "p2"
    assert game._skill_pending.trigger_event_type == "card_used"
    activate = next(
        action
        for action in game.legal_actions()
        if action.action_type is ActionType.ACTIVATE_SKILL
        and action.skill_id == "sgs_skill_mingzhe"
    )
    game.step(BatchActionIdController(activate.action_id))
    assert game._skill_pending is None
    assert len(game.state.card_ids_in(ZoneRef.hand("p2"))) == hand_before
    assert any(
        event.event_type is EventType.CARD_GAINED and event.skill_owner == "p2"
        for event in game.events
    )


def test_mingzhe_pass_does_not_draw() -> None:
    seed = _mingzhe_red_dodge_seed()
    registry = create_skill_registry((MingzheSkillHandler(),))
    game = _fresh_play(
        seed=seed,
        skill_registry=registry,
        skill_assignments={"p2": ("sgs_skill_mingzhe",)},
    )
    hand_before = len(game.state.card_ids_in(ZoneRef.hand("p2")))
    _p2_respond_red_dodge(game)
    decline = next(
        action
        for action in game.legal_actions()
        if action.payload.get("operation") == "pass_skill"
    )
    game.step(BatchActionIdController(decline.action_id))
    assert game._skill_pending is None
    assert len(game.state.card_ids_in(ZoneRef.hand("p2"))) == hand_before - 1
    assert not any(
        event.event_type is EventType.CARD_GAINED and event.skill_owner == "p2"
        for event in game.events
    )


def test_mingzhe_does_not_retrigger_consumed_event() -> None:
    seed = _mingzhe_red_dodge_seed()
    registry = create_skill_registry((MingzheSkillHandler(),))
    game = _fresh_play(
        seed=seed,
        skill_registry=registry,
        skill_assignments={"p2": ("sgs_skill_mingzhe",)},
    )
    _p2_respond_red_dodge(game)
    assert game._skill_pending is not None
    key = game._skill_pending.consumption_key
    decline = next(
        action
        for action in game.legal_actions()
        if action.payload.get("operation") == "pass_skill"
    )
    game.step(BatchActionIdController(decline.action_id))
    assert key in game._skill_consumed_triggers
    assert game._skill_pending is None
