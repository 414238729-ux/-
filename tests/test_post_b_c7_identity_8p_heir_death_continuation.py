# -*- coding: utf-8 -*-
"""POST-B C7：继位、储君死亡失去体力、择途与 parent/root 时序。"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

from scripts.sgs_engine.events import EventType
from scripts.sgs_engine.model import DISCARD_PILE, ZoneRef
from scripts.sgs_engine.mode_identity import StandardIdentityRole
from scripts.sgs_engine.mode_identity_heir import (
    FormalHeirAndSpyChoiceIdentityConfiguration,
    FormalHeirAndSpyChoiceIdentitySession,
    HeirAndSpyChoiceRole,
)
from scripts.sgs_engine.production_batch import (
    BatchActionIdController,
    ProductionBasicCardBatch,
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


def _pass_rescues(game: ProductionBasicCardBatch) -> None:
    while game.phase is ProductionPhase.DYING_RESCUE:
        _step(game, "pass_rescue")


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

    def enter(game: ProductionBasicCardBatch) -> None:
        _pass_mode(game)
        original_enter(game)

    def end(game: ProductionBasicCardBatch) -> None:
        _pass_mode(game)
        original_end(game)

    def advance(game: ProductionBasicCardBatch, player_id: str) -> None:
        _pass_mode(game)
        original_advance(game, player_id)
        _pass_mode(game)

    module._session = _session
    module._enter_play = enter
    module._end_turn = end
    module._advance_to = advance
    return module


_HELPERS = _c5_mode_helpers()


def _kill(
    game: FormalHeirAndSpyChoiceIdentitySession, killer: str, victim: str
) -> None:
    _HELPERS._kill(game, killer, victim)


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
    original_enter = module._enter_play
    original_end = module._end_turn
    original_advance = module._advance_to

    def enter(game: ProductionBasicCardBatch) -> None:
        _pass_mode(game)
        original_enter(game)

    def end(game: ProductionBasicCardBatch) -> None:
        _pass_mode(game)
        original_end(game)

    def advance(game: ProductionBasicCardBatch, player_id: str) -> None:
        _pass_mode(game)
        original_advance(game, player_id)
        _pass_mode(game)

    module._enter_play = enter
    module._end_turn = end
    module._advance_to = advance
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
