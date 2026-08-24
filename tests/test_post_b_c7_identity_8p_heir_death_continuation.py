# -*- coding: utf-8 -*-
"""POST-B C7：继位、储君死亡失去体力、择途与 parent/root 时序。"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

import pytest

from scripts.sgs_engine.events import EventType
from scripts.sgs_engine.model import DISCARD_PILE, PROCESSING_ZONE, ZoneRef
from scripts.sgs_engine.mode_identity import StandardIdentityRole
from scripts.sgs_engine.mode_identity_heir import (
    FormalHeirAndSpyChoiceIdentityConfiguration,
    FormalHeirAndSpyChoiceIdentitySession,
    HeirAndSpyChoiceRole,
)
from scripts.sgs_engine.production_batch import (
    BatchActionIdController,
    ProductionBasicCardBatch,
    ProductionBatchFinishedError,
    ProductionPhase,
    _replace_player,
)

_SECRET = b"c7-death-continuation-secret-001"


def _session(seed: int) -> FormalHeirAndSpyChoiceIdentitySession:
    return FormalHeirAndSpyChoiceIdentitySession(
        seed=seed,
        configuration=FormalHeirAndSpyChoiceIdentityConfiguration.formal_profile(),
        analysis_only=False,
        session_id=f"c7-death-{seed}",
        session_secret=_SECRET,
    )


def _step(game: ProductionBasicCardBatch, operation: str, **filters: Any) -> None:
    for action in game.legal_actions():
        if action.payload.get("operation") != operation:
            continue
        matched = True
        for key, value in filters.items():
            if key == "target":
                if not action.target_ids or action.target_ids[0] != value:
                    matched = False
                    break
            elif action.payload.get(key) != value:
                matched = False
                break
        if matched:
            game.step(BatchActionIdController(action.action_id))
            return
    raise AssertionError(
        f"缺少 {operation!r} {filters}: "
        f"{[item.payload.get('operation') for item in game.legal_actions()]} "
        f"phase={game.phase}"
    )


def _pass_mode(game: ProductionBasicCardBatch) -> None:
    while game.phase is ProductionPhase.MODE_DECISION:
        _step(game, "pass_mode_decision")


def _enter_play(game: ProductionBasicCardBatch) -> None:
    _pass_mode(game)
    for operation in ("proceed_prepare", "proceed_judgment", "proceed_draw"):
        _step(game, operation)
        _pass_mode(game)


def _pass_rescues(game: ProductionBasicCardBatch) -> None:
    while game.phase is ProductionPhase.DYING_RESCUE:
        _step(game, "pass_rescue")


_MODE_DECISION_OPERATIONS = {
    "pass_mode_decision",
    "select_heir",
    "choose_spy_path",
}


def _install_c7_mode_passthrough(
    module: Any,
    original_enter: Any,
    original_end: Any,
    original_advance: Any,
) -> None:
    original_step = module._step
    original_op = module._op
    original_require = module._require_op

    def pass_mode(game: ProductionBasicCardBatch) -> None:
        while game.phase is ProductionPhase.MODE_DECISION:
            original_step(game, original_require(game, "pass_mode_decision"))

    def op(game: ProductionBasicCardBatch, operation: str, **filters: Any) -> Any:
        if operation not in _MODE_DECISION_OPERATIONS:
            pass_mode(game)
        return original_op(game, operation, **filters)

    def require_op(
        game: ProductionBasicCardBatch, operation: str, **filters: Any
    ) -> Any:
        if operation not in _MODE_DECISION_OPERATIONS:
            pass_mode(game)
        return original_require(game, operation, **filters)

    def step(game: ProductionBasicCardBatch, action: Any) -> None:
        operation = (
            action.payload.get("operation") if hasattr(action, "payload") else None
        )
        if operation not in _MODE_DECISION_OPERATIONS:
            pass_mode(game)
        original_step(game, action)

    def enter(game: ProductionBasicCardBatch) -> None:
        pass_mode(game)
        for operation in ("proceed_prepare", "proceed_judgment", "proceed_draw"):
            original_step(game, original_require(game, operation))
            pass_mode(game)

    def end(game: ProductionBasicCardBatch) -> None:
        pass_mode(game)
        original_end(game)

    def advance(game: ProductionBasicCardBatch, player_id: str) -> None:
        pass_mode(game)
        original_advance(game, player_id)
        pass_mode(game)

    def pass_rescues(game: ProductionBasicCardBatch) -> None:
        while game.phase is ProductionPhase.DYING_RESCUE:
            original_step(game, original_require(game, "pass_rescue"))
        pass_mode(game)

    module._pass_mode = pass_mode
    module._op = op
    module._require_op = require_op
    module._step = step
    module._enter_play = enter
    module._end_turn = end
    module._advance_to = advance
    if hasattr(module, "_pass_rescues"):
        module._pass_rescues = pass_rescues
    if hasattr(module, "_pass_all_rescues"):
        module._pass_all_rescues = pass_rescues
    del original_enter


def _c5_mode_helpers() -> Any:
    path = Path(__file__).with_name("test_post_b_c5_identity_mode.py")
    spec = importlib.util.spec_from_file_location(
        "_c7_reused_c5_identity_mode_helpers", path
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载C5击杀助手：{path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    original_enter = module._enter_play
    original_end = module._end_turn
    original_advance = module._advance_to

    _install_c7_mode_passthrough(module, original_enter, original_end, original_advance)
    module._session = _session
    return module


_HELPERS = _c5_mode_helpers()


def _kill(
    game: FormalHeirAndSpyChoiceIdentitySession, killer: str, victim: str
) -> None:
    _pass_mode(game)
    _HELPERS._kill(game, killer, victim)
    _pass_mode(game)


def _players_of_role(
    game: FormalHeirAndSpyChoiceIdentitySession, role: StandardIdentityRole
) -> list[str]:
    return [
        player_id
        for player_id, current in game.identities_by_player.items()
        if current is role
    ]


def test_c7_heir_death_loses_current_lord_hp_not_damage() -> None:
    game = _session(0)
    lord = game.lord_player_id
    heir = next(
        player_id
        for player_id in game.numbered_player_order
        if player_id != lord
        and game.identities_by_player[player_id] is StandardIdentityRole.REBEL
    )
    game._variant.heir_player_id = heir
    game._variant.heir_selection_used = True
    before_hp = game.state.players_by_id[lord].hp
    start = len(game.events)
    killer = next(
        player_id
        for player_id in game.numbered_player_order
        if player_id not in {lord, heir}
    )
    _kill(game, killer, heir)
    assert game.state.players_by_id[heir].alive is False
    assert game._variant.heir_player_id is None
    types = [event.event_type for event in game.events[start:]]
    assert EventType.DEATH in types
    assert EventType.LOSE_HP in types
    assert not any(
        event.event_type is EventType.DAMAGE and lord in event.target_ids
        for event in game.events[start:]
    )
    lose = next(
        event
        for event in game.events[start:]
        if event.event_type is EventType.LOSE_HP
    )
    assert lose.target_ids == (lord,)
    assert lose.payload["amount"] == 1
    assert lose.damage_source is None
    if game.state.players_by_id[lord].alive:
        assert game.state.players_by_id[lord].hp == before_hp - 1


def test_c7_last_rebel_heir_cannot_skip_lord_hp_loss() -> None:
    game = _session(2)
    lord = game.lord_player_id
    rebels = _players_of_role(game, StandardIdentityRole.REBEL)
    spy = _players_of_role(game, StandardIdentityRole.SPY)[0]
    loyalists = _players_of_role(game, StandardIdentityRole.LOYALIST)
    heir = rebels[-1]
    game._variant.heir_player_id = heir
    game._variant.heir_selection_used = True
    _kill(game, lord, spy)
    for loyalist in loyalists:
        _kill(game, lord, loyalist)
    for rebel in rebels[:-1]:
        _kill(game, lord, rebel)
    assert game.is_finished is False
    start = len(game.events)
    _kill(game, lord, heir)
    assert any(
        event.event_type is EventType.LOSE_HP
        for event in game.events[start:]
    )


def test_c7_succession_updates_current_lord_without_reseating() -> None:
    game = _session(3)
    lord = game.lord_player_id
    loyalist = _players_of_role(game, StandardIdentityRole.LOYALIST)[0]
    heir_seat = game.seat_by_player[loyalist]
    numbered = game.numbered_player_order
    game._variant.heir_player_id = loyalist
    game._variant.heir_selection_used = True
    old_hp = game.state.players_by_id[loyalist].hp
    old_max = game.state.players_by_id[loyalist].max_hp
    _kill(game, loyalist, lord)
    if game.phase is ProductionPhase.SUCCESSION_CARD_CHOICE:
        _step(game, "succession_obtain_none")
    assert game.current_lord_player_id == loyalist
    assert game.original_lord_player_id == lord
    assert game.seat_by_player[loyalist] == heir_seat
    assert game.numbered_player_order == numbered
    assert game.role_current[loyalist] == HeirAndSpyChoiceRole.LORD.value
    successor = game.state.players_by_id[loyalist]
    assert successor.max_hp == old_max + 1
    assert successor.hp == min(old_max + 1, old_hp + 1)
    assert game.state.players_by_id[lord].alive is False
    if not game.is_finished:
        assert game.winner_id is None


def test_c7_converted_loyalist_can_succeed() -> None:
    game = _session(4)
    lord = game.lord_player_id
    spy = _players_of_role(game, StandardIdentityRole.SPY)[0]
    game._variant.heir_player_id = spy
    game._variant.heir_selection_used = True
    game._variant.role_current[spy] = HeirAndSpyChoiceRole.LOYALIST.value
    game._variant.converted_loyalist_ids = (spy,)
    game._sync_outcome_policy()
    _kill(game, spy, lord)
    if game.phase is ProductionPhase.SUCCESSION_CARD_CHOICE:
        _step(game, "succession_obtain_none")
    assert game.current_lord_player_id == spy
    assert game.role_original[spy] == "spy"
    assert game.role_current[spy] == "lord"


def test_c7_ambitionist_heir_cannot_succeed_but_still_loses_lord_hp() -> None:
    game = _session(5)
    lord = game.lord_player_id
    spy = _players_of_role(game, StandardIdentityRole.SPY)[0]
    game._variant.heir_player_id = spy
    game._variant.heir_selection_used = True
    game._variant.role_current[spy] = HeirAndSpyChoiceRole.AMBITIONIST.value
    game._sync_outcome_policy()
    before = game.state.players_by_id[lord].hp
    _kill(game, lord, spy)
    assert game.current_lord_player_id == lord
    assert game.role_current[spy] == "ambitionist"
    if game.state.players_by_id[lord].alive:
        assert game.state.players_by_id[lord].hp == before - 1


def _patch_c5_helpers(module: Any) -> None:
    _install_c7_mode_passthrough(
        module, module._enter_play, module._end_turn, module._advance_to
    )
    module._session = _session


def _scenarios() -> Any:
    path = Path(__file__).with_name("test_post_b_c5_identity_death_continuation.py")
    spec = importlib.util.spec_from_file_location(
        "_c7_reused_c5_death_continuation_scenarios", path
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载C5 parent/root强场景：{path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    _patch_c5_helpers(module)
    return module


def test_c7_parent_root_group_and_chain_high_risk() -> None:
    scenarios = _scenarios()
    scenarios.test_stale_action_fails_closed()
    scenarios.test_borrowed_sword_parent_root_survives_nonterminal_death()
    scenarios.test_chain_damage_nonterminal_child_death_continues()

    game = _session(201)
    lord = game.lord_player_id
    victim = game.numbered_player_order[1]
    scenarios._enter_play(game)
    scenarios._strip_hand(game, lord)
    scenarios._give_card(game, lord, "sgs_trick_nanmanruqin")
    scenarios._strip_hand(game, victim)
    game._state = _replace_player(game.state, victim, hp=1)
    scenarios._step(game, scenarios._require_op(game, "use_nanman"))
    scenarios._pass_trick(game)
    assert game.runtime.pending_group_trick is not None
    scenarios._step(game, scenarios._require_op(game, "pass_nanman_slash"))
    scenarios._pass_rescues(game)
    assert game.state.players_by_id[victim].alive is False
    assert game.is_finished is False
    assert game.runtime.pending_group_trick is not None


def _operations(game: ProductionBasicCardBatch) -> list[object]:
    return [action.payload.get("operation") for action in game.legal_actions()]


def _alive_count(game: ProductionBasicCardBatch) -> int:
    return sum(1 for player in game.state.players if player.alive)


def _strip_hand(game: ProductionBasicCardBatch, player_id: str) -> None:
    for instance_id in tuple(game.state.card_ids_in(ZoneRef.hand(player_id))):
        game._state = game.state.move_card(instance_id, DISCARD_PILE)


def _give_card(game: ProductionBasicCardBatch, player_id: str, card_key: str) -> str:
    for instance_id, card in game.state.cards_by_id.items():
        if card.card_key == card_key:
            destination = ZoneRef.hand(player_id)
            if game.state.location_of(instance_id) != destination:
                game._state = game.state.move_card(instance_id, destination)
            return instance_id
    raise AssertionError(card_key)


def _end_turn(game: ProductionBasicCardBatch) -> None:
    _pass_mode(game)
    if game.phase is ProductionPhase.PLAY:
        _step(game, "end_play_phase")
        _pass_mode(game)
    while game.phase is ProductionPhase.DISCARD:
        operations = _operations(game)
        if "discard_phase_submit" in operations:
            _step(game, "discard_phase_submit")
        else:
            _step(game, "select_discard_card")
        _pass_mode(game)
    if game.phase is ProductionPhase.END:
        _step(game, "end_turn")


def _drive_group_until_mode(game: ProductionBasicCardBatch) -> None:
    guard = 0
    while guard < 48:
        if game.phase is ProductionPhase.MODE_DECISION:
            return
        if game.runtime.pending_group_trick is None:
            return
        operations = _operations(game)
        if "pass_trick_response" in operations:
            _step(game, "pass_trick_response")
        elif "pass_nanman_slash" in operations:
            _step(game, "pass_nanman_slash")
        elif "pass_rescue" in operations:
            _step(game, "pass_rescue")
        else:
            return
        guard += 1
    raise AssertionError("群体锦囊推进超时")


def _await_spy_choice_window(
    game: FormalHeirAndSpyChoiceIdentitySession, spy: str
) -> None:
    guard = 0
    while game.phase is ProductionPhase.MODE_DECISION:
        if (
            "choose_spy_path" in _operations(game)
            and game.current_actor_id == spy
        ):
            return
        if "pass_mode_decision" in _operations(game):
            _step(game, "pass_mode_decision")
        else:
            break
        guard += 1
        assert guard < 8
    raise AssertionError(
        "内奸未取得 choose_spy_path 窗口: "
        f"phase={game.phase} actor={getattr(game, 'current_actor_id', None)} "
        f"ops={_operations(game)}"
    )


def _continue_nanman_until_alive(
    game: FormalHeirAndSpyChoiceIdentitySession, until_alive: int
) -> None:
    guard = 0
    while _alive_count(game) > until_alive and guard < 48:
        if game.phase is ProductionPhase.MODE_DECISION:
            _pass_mode(game)
            continue
        if game.runtime.pending_group_trick is None:
            break
        _drive_group_until_mode(game)
        guard += 1


def _nanman_discard_count(game: ProductionBasicCardBatch, nanman_id: str) -> int:
    return sum(
        1
        for event in game.events
        if event.card_instance_id == nanman_id
        and event.event_type is EventType.CARD_MOVED
        and event.payload.get("destination", {}).get("kind") == "discard_pile"
    )


def _setup_seed1_lord_nanman() -> tuple[
    FormalHeirAndSpyChoiceIdentitySession, str, str, str, str
]:
    game = _session(1)
    lord = game.lord_player_id
    spy = next(
        player_id
        for player_id, role in game.role_current.items()
        if role == "spy"
    )
    loyalist = "p8"
    assert lord == "p6"
    assert spy == "p5"
    assert game.role_current[loyalist] == "loyalist"
    _enter_play(game)
    assert game.current_player_id == lord
    assert game.phase is ProductionPhase.PLAY
    _strip_hand(game, lord)
    nanman_id = _give_card(game, lord, "sgs_trick_nanmanruqin")
    for victim in ("p8", "p1", "p2", "p4"):
        _strip_hand(game, victim)
        game._state = _replace_player(game.state, victim, hp=1)
    _step(game, "use_nanman")
    return game, lord, spy, loyalist, nanman_id


def _drive_to_nested_lord_dying(
    game: FormalHeirAndSpyChoiceIdentitySession,
    lord: str,
) -> None:
    for _ in range(96):
        runtime = game.runtime
        if (
            game.phase is ProductionPhase.DYING_RESCUE
            and runtime.pending_dying_id == lord
            and runtime.pending_lose_hp_dying
        ):
            return
        operations = _operations(game)
        if game.phase is ProductionPhase.MODE_DECISION:
            _pass_mode(game)
        elif game.phase is ProductionPhase.DYING_RESCUE:
            _step(game, "pass_rescue")
        elif "pass_trick_response" in operations:
            _step(game, "pass_trick_response")
        elif "pass_nanman_slash" in operations:
            _step(game, "pass_nanman_slash")
        else:
            raise AssertionError(
                "无法推进到储君死亡触发的主公嵌套濒死："
                f"phase={game.phase} operations={operations}"
            )
    raise AssertionError("推进主公嵌套濒死超过硬上限")


def _finish_pending_group(game: FormalHeirAndSpyChoiceIdentitySession) -> None:
    for _ in range(96):
        if game.runtime.pending_group_trick is None:
            return
        before = (
            game.phase,
            game.runtime.pending_group_trick.current_target_index,
            len(game.events),
        )
        if game.phase is ProductionPhase.MODE_DECISION:
            _pass_mode(game)
        else:
            _drive_group_until_mode(game)
        group = game.runtime.pending_group_trick
        after = (
            game.phase,
            None if group is None else group.current_target_index,
            len(game.events),
        )
        assert after != before, "南蛮 parent/root 继续未取得进展"
    raise AssertionError("南蛮 parent/root 完成超过硬上限")


def test_c7_a1_nested_lord_death_finishes_once_and_cleans_nanman_root() -> None:
    game, lord, _spy, heir, nanman_id = _setup_seed1_lord_nanman()
    game._variant.heir_player_id = heir
    game._variant.heir_selection_used = True
    game._state = _replace_player(game.state, lord, hp=1)
    death_cleanup_marker = _give_card(game, lord, "sgs_basic_sha")
    start = len(game.events)

    _drive_to_nested_lord_dying(game, lord)
    group = game.runtime.pending_group_trick
    assert group is not None
    assert group.target_sequence[group.current_target_index] == heir
    future_targets = group.target_sequence[group.current_target_index + 1 :]
    future_state = {
        player_id: (
            game.state.players_by_id[player_id].hp,
            game.state.players_by_id[player_id].alive,
        )
        for player_id in future_targets
    }
    assert game.runtime.pending_outer_death is not None
    assert game.runtime.pending_outer_death.dying_id == heir
    rescue_order = game.runtime.rescue_order
    assert rescue_order
    for _ in rescue_order:
        _step(game, "pass_rescue")

    assert game.state.players_by_id[lord].alive is False
    assert game.is_finished is True
    assert game.phase is ProductionPhase.FINISHED
    assert game.winner_id == "rebels"
    assert game.runtime.pending_dying_id is None
    assert game.runtime.pending_lose_hp_dying is False
    assert game.runtime.pending_outer_death is None
    assert game.runtime.pending_group_trick is None
    with pytest.raises(ProductionBatchFinishedError):
        game.legal_actions()

    events = game.events[start:]
    heir_deaths = [
        event
        for event in events
        if event.event_type is EventType.DEATH
        and event.target_ids == (heir,)
    ]
    lord_lose_hp = [
        event
        for event in events
        if event.event_type is EventType.LOSE_HP
        and event.target_ids == (lord,)
    ]
    lord_dying = [
        event
        for event in events
        if event.event_type is EventType.DYING
        and event.target_ids == (lord,)
    ]
    lord_deaths = [
        event
        for event in events
        if event.event_type is EventType.DEATH
        and event.target_ids == (lord,)
    ]
    victories = [
        event for event in events if event.event_type is EventType.VICTORY
    ]
    assert len(heir_deaths) == 1
    assert len(lord_lose_hp) == 1
    assert len(lord_dying) == 1
    assert len(lord_deaths) == 1
    assert len(victories) == 1
    assert victories[0].target_ids == ("rebels",)
    for event in (*lord_lose_hp, *lord_dying, *lord_deaths):
        assert event.damage_source is None
        assert event.kill_credit is None

    root_moves = [
        event
        for event in events
        if event.card_instance_id == nanman_id
        and event.event_type is EventType.CARD_MOVED
        and event.payload.get("destination", {}).get("kind") == "discard_pile"
    ]
    assert len(root_moves) == 1
    assert nanman_id not in game.state.card_ids_in(PROCESSING_ZONE)
    assert (
        heir_deaths[0].sequence
        < lord_lose_hp[0].sequence
        < lord_dying[0].sequence
        < root_moves[0].sequence
        < lord_deaths[0].sequence
        < victories[0].sequence
    )
    assert game.state.location_of(death_cleanup_marker) == DISCARD_PILE
    assert not any(
        event.card_instance_id == death_cleanup_marker
        and event.payload.get("reason")
        == "identity_lord_kill_loyalist_penalty"
        for event in events
    )
    forbidden_future_types = {
        EventType.CARD_EFFECT_CANCELLED,
        EventType.CARD_INVALIDATED,
        EventType.DAMAGE,
        EventType.DYING,
        EventType.DEATH,
        EventType.GROUP_TARGET_RESOLVED,
    }
    assert not any(
        event.event_type in forbidden_future_types
        and any(player_id in event.target_ids for player_id in future_targets)
        for event in events
    )
    assert all(
        (
            game.state.players_by_id[player_id].hp,
            game.state.players_by_id[player_id].alive,
        )
        == future_state[player_id]
        for player_id in future_targets
    )


def test_c7_a1_rescued_lord_resumes_outer_death_then_nanman_once() -> None:
    game, lord, _spy, heir, nanman_id = _setup_seed1_lord_nanman()
    game._variant.heir_player_id = heir
    game._variant.heir_selection_used = True
    game._state = _replace_player(game.state, lord, hp=1)
    peach_id = _give_card(game, lord, "sgs_basic_tao")
    penalty_marker = _give_card(game, lord, "sgs_basic_sha")
    start = len(game.events)

    _drive_to_nested_lord_dying(game, lord)
    group_before = game.runtime.pending_group_trick
    assert group_before is not None
    assert group_before.target_sequence[group_before.current_target_index] == heir
    target_sequence = group_before.target_sequence
    _step(game, "rescue_with_peach")

    assert game.state.players_by_id[lord].alive is True
    assert game.state.players_by_id[lord].hp == 1
    assert game.state.players_by_id[heir].alive is False
    assert game.runtime.pending_lose_hp_dying is False
    assert game.runtime.pending_outer_death is None
    group_after = game.runtime.pending_group_trick
    assert group_after is not None
    assert group_after.current_target_index == group_before.current_target_index + 1
    assert group_after.completed_target_ids == (
        *group_before.completed_target_ids,
        heir,
    )
    assert (
        group_after.target_sequence[group_after.current_target_index]
        != heir
    )
    assert nanman_id in game.state.card_ids_in(PROCESSING_ZONE)
    assert _nanman_discard_count(game, nanman_id) == 0

    events_after_rescue = game.events[start:]
    heir_death = next(
        event
        for event in events_after_rescue
        if event.event_type is EventType.DEATH
        and event.target_ids == (heir,)
    )
    lord_lose_hp = next(
        event
        for event in events_after_rescue
        if event.event_type is EventType.LOSE_HP
        and event.target_ids == (lord,)
    )
    lord_dying = next(
        event
        for event in events_after_rescue
        if event.event_type is EventType.DYING
        and event.target_ids == (lord,)
    )
    peach_move = next(
        event
        for event in events_after_rescue
        if event.card_instance_id == peach_id
        and event.event_type is EventType.CARD_MOVED
        and event.payload.get("destination", {}).get("kind") == "discard_pile"
    )
    penalty_move = next(
        event
        for event in events_after_rescue
        if event.card_instance_id == penalty_marker
        and event.event_type is EventType.CARD_MOVED
        and event.payload.get("reason")
        == "identity_lord_kill_loyalist_penalty"
    )
    heir_group_resolved = [
        event
        for event in events_after_rescue
        if event.card_instance_id == nanman_id
        and event.event_type is EventType.GROUP_TARGET_RESOLVED
        and event.target_ids == (heir,)
    ]
    assert len(heir_group_resolved) == 1
    assert (
        heir_death.sequence
        < lord_lose_hp.sequence
        < lord_dying.sequence
        < peach_move.sequence
        < penalty_move.sequence
        < heir_group_resolved[0].sequence
    )
    for event in (lord_lose_hp, lord_dying):
        assert event.damage_source is None
        assert event.kill_credit is None
    assert not any(
        event.event_type is EventType.DAMAGE and lord in event.target_ids
        for event in events_after_rescue
    )
    assert not any(
        event.event_type is EventType.DEATH and event.target_ids == (lord,)
        for event in events_after_rescue
    )

    _finish_pending_group(game)
    assert game.is_finished is False
    assert game.runtime.pending_group_trick is None
    assert nanman_id not in game.state.card_ids_in(PROCESSING_ZONE)
    assert _nanman_discard_count(game, nanman_id) == 1
    resolved_targets = [
        event.target_ids[0]
        for event in game.events[start:]
        if event.card_instance_id == nanman_id
        and event.event_type is EventType.GROUP_TARGET_RESOLVED
    ]
    assert resolved_targets == list(target_sequence)
    assert len(resolved_targets) == len(set(resolved_targets))


def test_c7_spy_path_window_opens_during_live_nanman_group_root() -> None:
    game, lord, spy, loyalist, nanman_id = _setup_seed1_lord_nanman()
    policy = game.mode_policy
    _drive_group_until_mode(game)
    assert game.state.players_by_id[loyalist].alive is False
    assert _alive_count(game) == 7
    assert policy.spy_path_chooser_id(game.state) == spy
    assert game.phase is ProductionPhase.MODE_DECISION
    group_before = game.runtime.pending_group_trick
    assert group_before is not None
    assert group_before.trick_key == "sgs_trick_nanmanruqin"
    index_before = group_before.current_target_index
    completed_before = group_before.completed_target_ids
    assert loyalist in completed_before
    assert group_before.target_sequence[index_before] != loyalist
    assert nanman_id in game.state.card_ids_in(PROCESSING_ZONE)
    _await_spy_choice_window(game, spy)
    assert "choose_spy_path" in _operations(game)
    assert game.current_actor_id == spy
    assert game.current_player_id == lord
    pending = game.runtime.pending_mode_decision
    assert pending is not None
    assert pending.resume_phase is not ProductionPhase.PREPARE
    _step(game, "choose_spy_path", path="ambitionist")
    assert game._variant.spy_path_locked is True
    assert game._variant.spy_path_pending is True
    assert game.role_current[spy] == "spy"
    group_after = game.runtime.pending_group_trick
    assert group_after is not None
    assert group_after.trick_instance_id == group_before.trick_instance_id
    assert group_after.current_target_index == index_before
    assert group_after.completed_target_ids == completed_before
    assert game.phase is pending.resume_phase
    _continue_nanman_until_alive(game, 4)
    assert _alive_count(game) == 4
    assert game._variant.spy_path_locked is True
    assert game._variant.spy_path_pending is True
    assert game.role_current[spy] == "spy"
    assert policy.spy_path_chooser_id(game.state) is None
    while game.runtime.pending_group_trick is not None:
        if game.phase is ProductionPhase.MODE_DECISION:
            _pass_mode(game)
            continue
        before_index = game.runtime.pending_group_trick.current_target_index
        _drive_group_until_mode(game)
        if (
            game.runtime.pending_group_trick is not None
            and game.runtime.pending_group_trick.current_target_index
            == before_index
            and game.phase is not ProductionPhase.MODE_DECISION
        ):
            break
    assert game.runtime.pending_group_trick is None
    assert _nanman_discard_count(game, nanman_id) == 1
    assert nanman_id not in game.state.card_ids_in(PROCESSING_ZONE)
    _end_turn(game)
    assert game.role_current[spy] == "ambitionist"
    assert game._variant.spy_path_pending is False
    assert game._variant.spy_path_locked is True


def test_c7_spy_path_defer_keeps_later_checkpoint_until_alive_at_most_four() -> None:
    game, lord, spy, loyalist, nanman_id = _setup_seed1_lord_nanman()
    del lord, nanman_id
    policy = game.mode_policy
    _drive_group_until_mode(game)
    assert _alive_count(game) == 7
    assert game.state.players_by_id[loyalist].alive is False
    assert policy.spy_path_chooser_id(game.state) == spy
    _pass_mode(game)
    assert game._variant.spy_path_locked is False
    assert game._variant.spy_path_pending is False
    assert game.role_current[spy] == "spy"
    assert game.runtime.pending_group_trick is not None
    _drive_group_until_mode(game)
    assert _alive_count(game) == 6
    assert policy.spy_path_chooser_id(game.state) == spy
    assert game.phase is ProductionPhase.MODE_DECISION
    _await_spy_choice_window(game, spy)
    assert "choose_spy_path" in _operations(game)
    _pass_mode(game)
    _continue_nanman_until_alive(game, 4)
    assert _alive_count(game) <= 4
    assert game._variant.spy_path_locked is False
    assert game._variant.spy_path_pending is False
    assert policy.spy_path_chooser_id(game.state) is None
    if game.phase is ProductionPhase.MODE_DECISION:
        assert "choose_spy_path" not in _operations(game)
    while game.runtime.pending_group_trick is not None:
        if game.phase is ProductionPhase.MODE_DECISION:
            assert "choose_spy_path" not in _operations(game)
            _pass_mode(game)
            continue
        _drive_group_until_mode(game)


def test_c7_mode_decision_preserves_nanman_parent_root_queue() -> None:
    game, lord, spy, loyalist, nanman_id = _setup_seed1_lord_nanman()
    del lord
    _drive_group_until_mode(game)
    group = game.runtime.pending_group_trick
    assert group is not None
    processed = set(group.completed_target_ids)
    assert loyalist in processed
    remaining = group.target_sequence[group.current_target_index :]
    assert loyalist not in remaining
    index_at_window = group.current_target_index
    _await_spy_choice_window(game, spy)
    _step(game, "choose_spy_path", path="loyalist")
    group = game.runtime.pending_group_trick
    assert group is not None
    assert group.current_target_index == index_at_window
    assert set(group.completed_target_ids) == processed
    seen = list(processed)
    guard = 0
    while game.runtime.pending_group_trick is not None and guard < 48:
        group = game.runtime.pending_group_trick
        current = group.target_sequence[group.current_target_index]
        assert current not in seen
        if game.phase is ProductionPhase.MODE_DECISION:
            _pass_mode(game)
            guard += 1
            continue
        _drive_group_until_mode(game)
        if game.runtime.pending_group_trick is None:
            break
        new_completed = game.runtime.pending_group_trick.completed_target_ids
        for player_id in new_completed:
            if player_id not in seen:
                seen.append(player_id)
        guard += 1
    assert game.runtime.pending_group_trick is None
    assert len(seen) == len(set(seen))
    assert _nanman_discard_count(game, nanman_id) == 1
