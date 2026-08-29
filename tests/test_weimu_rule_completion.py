# -*- coding: utf-8 -*-
"""WEIMU_RULE_COMPLETION production acceptance.

All positive card paths use ProductionBasicCardBatch.legal_actions -> signed
action_id -> step.  Fixture moves only arrange deterministic formal entities;
they do not resolve card effects or bypass the production state machine.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from scripts.sgs_engine.actions import InvalidActionError, LegalAction
from scripts.sgs_engine.events import EventType
from scripts.sgs_engine.model import DISCARD_PILE, DRAW_PILE, ZoneRef
from scripts.sgs_engine.production_batch import (
    BatchActionIdController,
    ProductionBasicCardBatch,
    ProductionBatchError,
    ProductionPhase,
    _replace_player,
)
from scripts.sgs_engine.skill_impl_v1 import WeimuSkillHandler
from scripts.sgs_engine.skill_registry import create_skill_registry


WEIMU = "sgs_skill_weimu"
GUOHE = "sgs_trick_guohechaiqiao"
NANMAN = "sgs_trick_nanmanruqin"
LEBUSI = "sgs_delayed_lebusi"
SHANDIAN = "sgs_delayed_shandian"
SHA = "sgs_basic_sha"


def _fresh(
    *,
    players: int = 3,
    assignments: dict[str, tuple[str, ...]] | None = None,
) -> ProductionBasicCardBatch:
    registry = create_skill_registry((WeimuSkillHandler(),))
    player_ids = tuple(f"p{index}" for index in range(1, players + 1))
    game = ProductionBasicCardBatch(
        seed=37,
        player_hp=(4,) * players,
        player_max_hp=(4,) * players,
        player_ids=player_ids,
        first_player_id="p1",
        skill_registry=registry,
        skill_assignments=assignments or {},
    )
    for operation in ("proceed_prepare", "proceed_judgment", "proceed_draw"):
        _proceed(game, operation)
    assert game.phase is ProductionPhase.PLAY
    return game


def _step(game: ProductionBasicCardBatch, action: LegalAction) -> None:
    assert action.action_id is not None
    game.step(BatchActionIdController(action.action_id))


def _proceed(game: ProductionBasicCardBatch, operation: str) -> None:
    action = next(
        item
        for item in game.legal_actions()
        if item.payload.get("operation") == operation
    )
    _step(game, action)


def _action(
    game: ProductionBasicCardBatch,
    operation: str,
    *,
    card_id: str | None = None,
    target: str | None = None,
) -> LegalAction | None:
    for action in game.legal_actions():
        if action.payload.get("operation") != operation:
            continue
        if card_id is not None and action.card_instance_id != card_id:
            continue
        if target is not None and action.target_ids != (target,):
            continue
        return action
    return None


def _swap_to_hand(
    game: ProductionBasicCardBatch,
    player_id: str,
    card_key: str,
    *,
    color: str,
) -> str:
    card = next(
        item
        for item in game.state.cards
        if item.card_key == card_key and item.color == color
    )
    destination = ZoneRef.hand(player_id)
    source = game.state.location_of(card.instance_id)
    if source == destination:
        return card.instance_id
    moves: dict[str, ZoneRef] = {card.instance_id: destination}
    current = game.state.card_ids_in(destination)
    if current:
        moves[current[0]] = source
    game._state = game.state.move_cards(moves)
    return card.instance_id


def _put_miss_judgment_on_top(game: ProductionBasicCardBatch) -> str:
    card = next(
        item
        for item in game.state.cards
        if item.color == "红" and item.card_key != SHANDIAN
    )
    if game.state.location_of(card.instance_id) != DRAW_PILE:
        game._state = game.state.move_card(card.instance_id, DRAW_PILE)
    pile = list(game.state.card_ids_in(DRAW_PILE))
    pile.remove(card.instance_id)
    pile.insert(0, card.instance_id)
    game._state = game.state.reorder_zone(DRAW_PILE, tuple(pile))
    return card.instance_id


def _discard_to_end(game: ProductionBasicCardBatch) -> None:
    while game.phase is ProductionPhase.DISCARD:
        actions = game.legal_actions()
        submit = next(
            (
                action
                for action in actions
                if action.payload.get("operation") == "discard_phase_submit"
            ),
            None,
        )
        if submit is not None:
            _step(game, submit)
            break
        select = next(
            action
            for action in actions
            if action.payload.get("operation") == "select_discard_card"
        )
        _step(game, select)


def _end_turn(game: ProductionBasicCardBatch) -> None:
    assert game.phase is ProductionPhase.PLAY
    _proceed(game, "end_play_phase")
    _discard_to_end(game)
    assert game.phase is ProductionPhase.END
    _proceed(game, "end_turn")
    assert game.phase is ProductionPhase.PREPARE


def _play_empty_turn(game: ProductionBasicCardBatch) -> None:
    assert game.phase is ProductionPhase.PREPARE
    _proceed(game, "proceed_prepare")
    _proceed(game, "proceed_judgment")
    assert game.phase is ProductionPhase.DRAW
    _proceed(game, "proceed_draw")
    assert game.phase is ProductionPhase.PLAY
    _end_turn(game)


def _advance_to_prepare(
    game: ProductionBasicCardBatch, player_id: str
) -> None:
    while not (
        game.current_player_id == player_id
        and game.phase is ProductionPhase.PREPARE
    ):
        _play_empty_turn(game)


def _open_and_close_judgment(game: ProductionBasicCardBatch) -> None:
    assert game.phase is ProductionPhase.PREPARE
    _proceed(game, "proceed_prepare")
    _proceed(game, "proceed_judgment")
    assert game.phase is ProductionPhase.JUDGMENT_WUXIE
    for _ in range(16):
        if game.phase is not ProductionPhase.JUDGMENT_WUXIE:
            break
        _proceed(game, "pass_judgment_wuxie")
    assert game.phase is ProductionPhase.JUDGMENT


def _use_black_lightning(game: ProductionBasicCardBatch) -> str:
    lightning_id = _swap_to_hand(
        game, "p1", SHANDIAN, color="黑"
    )
    action = _action(
        game, "use_shandian", card_id=lightning_id, target="p1"
    )
    assert action is not None
    _step(game, action)
    assert lightning_id in game.state.card_ids_in(ZoneRef.judgment("p1"))
    return lightning_id


def test_black_single_target_enumeration_and_forged_or_stale_rejection() -> None:
    game = _fresh(assignments={"p3": (WEIMU,)})
    guohe_id = _swap_to_hand(game, "p1", GUOHE, color="黑")

    assert _action(game, "use_guohe", card_id=guohe_id, target="p3") is None
    issued = _action(game, "use_guohe", card_id=guohe_id, target="p2")
    assert issued is not None

    forged = replace(issued, target_ids=("p3",))
    with pytest.raises(InvalidActionError, match="绑定内容不一致|过期或系伪造"):
        game._validate_session_action(game.state, game._context(), forged)

    assert game.skill_runtime is not None
    game._skill_runtime = game.skill_runtime.assign_skill("p2", WEIMU)
    with pytest.raises(ProductionBatchError, match="过期或系伪造"):
        game.step(BatchActionIdController(issued.action_id))


def test_black_group_trick_auto_target_set_excludes_weimu_owner() -> None:
    game = _fresh(
        players=4,
        assignments={"p3": (WEIMU,)},
    )
    nanman_id = _swap_to_hand(game, "p1", NANMAN, color="黑")
    action = _action(game, "use_nanman", card_id=nanman_id)
    assert action is not None and action.target_ids == ()
    _step(game, action)

    used = next(
        event
        for event in reversed(game.events)
        if event.event_type is EventType.CARD_USED
        and event.card_instance_id == nanman_id
    )
    assert used.target_ids == ("p2", "p4")
    assert "p3" not in used.target_ids


def test_delayed_trick_and_current_black_lightning_use_are_illegal() -> None:
    target_game = _fresh(assignments={"p3": (WEIMU,)})
    black_lebusi = _swap_to_hand(
        target_game, "p1", LEBUSI, color="黑"
    )
    assert (
        _action(
            target_game,
            "use_lebusi",
            card_id=black_lebusi,
            target="p3",
        )
        is None
    )
    assert (
        _action(
            target_game,
            "use_lebusi",
            card_id=black_lebusi,
            target="p2",
        )
        is not None
    )

    self_game = _fresh(assignments={"p1": (WEIMU,)})
    black_lightning = _swap_to_hand(
        self_game, "p1", SHANDIAN, color="黑"
    )
    red_lightning = _swap_to_hand(
        self_game, "p1", SHANDIAN, color="红"
    )
    assert (
        _action(
            self_game,
            "use_shandian",
            card_id=black_lightning,
            target="p1",
        )
        is None
    )
    assert (
        _action(
            self_game,
            "use_shandian",
            card_id=red_lightning,
            target="p1",
        )
        is not None
    )


def test_existing_lightning_still_judges_after_owner_gains_weimu() -> None:
    game = _fresh(players=2)
    lightning_id = _use_black_lightning(game)
    assert game.skill_runtime is not None
    game._skill_runtime = game.skill_runtime.assign_skill("p1", WEIMU)

    _end_turn(game)
    _play_empty_turn(game)
    assert game.current_player_id == "p1"
    _put_miss_judgment_on_top(game)
    _open_and_close_judgment(game)

    started = [
        event
        for event in game.events
        if event.event_type is EventType.JUDGMENT_STARTED
        and event.card_instance_id == lightning_id
    ]
    assert len(started) == 1


def test_lightning_transfer_skips_multiple_weimu_owners() -> None:
    game = _fresh(
        players=4,
        assignments={"p2": (WEIMU,), "p3": (WEIMU,)},
    )
    lightning_id = _use_black_lightning(game)
    _end_turn(game)
    _advance_to_prepare(game, "p1")
    _put_miss_judgment_on_top(game)
    _open_and_close_judgment(game)

    assert lightning_id in game.state.card_ids_in(ZoneRef.judgment("p4"))
    transferred = [
        event
        for event in game.events
        if event.event_type is EventType.DELAYED_TRICK_TRANSFERRED
        and event.card_instance_id == lightning_id
    ]
    assert transferred[-1].payload["from_player_id"] == "p1"
    assert transferred[-1].payload["to_player_id"] == "p4"
    assert transferred[-1].payload["reason"] == "shandian_transfer"


def test_lightning_self_restore_when_all_other_targets_have_weimu_and_rejudges() -> None:
    game = _fresh(
        players=4,
        assignments={
            "p2": (WEIMU,),
            "p3": (WEIMU,),
            "p4": (WEIMU,),
        },
    )
    lightning_id = _use_black_lightning(game)
    _end_turn(game)
    _advance_to_prepare(game, "p1")
    _put_miss_judgment_on_top(game)
    _open_and_close_judgment(game)

    assert lightning_id in game.state.card_ids_in(ZoneRef.judgment("p1"))
    assert lightning_id not in game.state.card_ids_in(DISCARD_PILE)
    transfers = [
        event
        for event in game.events
        if event.event_type is EventType.DELAYED_TRICK_TRANSFERRED
        and event.card_instance_id == lightning_id
    ]
    assert transfers[-1].payload["to_player_id"] == "p1"
    assert transfers[-1].payload["reason"] == "shandian_self_restore"

    _proceed(game, "proceed_judgment")
    _proceed(game, "proceed_draw")
    _end_turn(game)
    _advance_to_prepare(game, "p1")
    _put_miss_judgment_on_top(game)
    _open_and_close_judgment(game)

    started = [
        event
        for event in game.events
        if event.event_type is EventType.JUDGMENT_STARTED
        and event.card_instance_id == lightning_id
    ]
    assert len(started) == 2


def test_weimu_lost_invalidated_and_death_lifecycle() -> None:
    game = _fresh(assignments={"p3": (WEIMU,)})
    guohe_id = _swap_to_hand(game, "p1", GUOHE, color="黑")
    assert _action(game, "use_guohe", card_id=guohe_id, target="p3") is None
    assert game.skill_runtime is not None

    game._skill_runtime = game.skill_runtime.invalidate_skill("p3", WEIMU)
    assert _action(game, "use_guohe", card_id=guohe_id, target="p3") is not None
    game._skill_runtime = game.skill_runtime.recover_skill("p3", WEIMU)
    assert _action(game, "use_guohe", card_id=guohe_id, target="p3") is None
    game._skill_runtime = game.skill_runtime.lose_skill("p3", WEIMU)
    assert _action(game, "use_guohe", card_id=guohe_id, target="p3") is not None

    death_game = _fresh(assignments={"p3": (WEIMU,)})
    death_guohe = _swap_to_hand(death_game, "p1", GUOHE, color="黑")
    card = death_game.state.cards_by_id[death_guohe]
    death_game._state = _replace_player(
        death_game.state, "p3", hp=0, alive=False
    )
    assert death_game.filter_targets_for_card(
        "p1", card, card.card_key, ("p3",)
    ) == ("p3",)


def test_red_trick_and_basic_card_are_not_filtered() -> None:
    game = _fresh(assignments={"p3": (WEIMU,)})
    red_guohe = _swap_to_hand(game, "p1", GUOHE, color="红")
    black_sha = _swap_to_hand(game, "p1", SHA, color="黑")
    assert _action(game, "use_guohe", card_id=red_guohe, target="p3") is not None
    assert _action(game, "use_slash", card_id=black_sha, target="p3") is not None
