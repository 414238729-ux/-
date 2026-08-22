# -*- coding: utf-8 -*-
"""POST-B C5：正式无武将技能五人标准军争身份模式核心测试。"""

from __future__ import annotations

from copy import copy, deepcopy
from dataclasses import replace
from types import MappingProxyType
from typing import Any

import pytest

from scripts.sgs_engine.actions import InvalidActionError, LegalAction
from scripts.sgs_engine.events import EventType
from scripts.sgs_engine.model import DISCARD_PILE, DRAW_PILE, PlayerState, ZoneRef
from scripts.sgs_engine.mode_identity import (
    FORMAL_NO_SKILL_IDENTITY_5P_MODE,
    FormalIdentityConfiguration,
    FormalIdentityConfigurationError,
    FormalIdentityReadiness,
    FormalIdentitySession,
    IdentityOutcomePolicy,
    StandardIdentityRole,
    TrustedFormalIdentityConfiguration,
    assert_trusted_formal_identity_configuration,
    inspect_formal_identity_readiness,
)
from scripts.sgs_engine.multiplayer import PlayerTopology
from scripts.sgs_engine.production_batch import (
    BatchActionIdController,
    DeathConfirmationContext,
    ProductionBasicCardBatch,
    ProductionPhase,
    _replace_player,
)
from scripts.sgs_engine.rng import DeterministicRNG

SHA = "sgs_basic_sha"
_SECRET = b"c5-identity-test-secret-32bytes!"


def _profile() -> TrustedFormalIdentityConfiguration:
    return FormalIdentityConfiguration.formal_profile()


def _session(seed: int = 0, *, analysis_only: bool = False) -> FormalIdentitySession:
    return FormalIdentitySession(
        seed=seed,
        configuration=_profile(),
        analysis_only=analysis_only,
        session_id=f"c5-mode-{seed}",
        session_secret=_SECRET,
    )


def _step(game: ProductionBasicCardBatch, action: LegalAction) -> None:
    game.step(BatchActionIdController(action.action_id))


def _op(
    game: ProductionBasicCardBatch, operation: str, **filters: Any
) -> LegalAction | None:
    for action in game.legal_actions():
        if action.payload.get("operation") != operation:
            continue
        matched = True
        for key, value in filters.items():
            if key == "targets":
                if tuple(action.target_ids) != tuple(value):
                    matched = False
                    break
            elif action.payload.get(key) != value:
                matched = False
                break
        if matched:
            return action
    return None


def _require_op(
    game: ProductionBasicCardBatch, operation: str, **filters: Any
) -> LegalAction:
    action = _op(game, operation, **filters)
    assert action is not None, (
        f"缺少操作 {operation!r}（当前："
        f"{[a.payload.get('operation') for a in game.legal_actions()]})"
    )
    return action


def _strip_hand(game: ProductionBasicCardBatch, player_id: str) -> None:
    for instance_id in tuple(game.state.card_ids_in(ZoneRef.hand(player_id))):
        game._state = game.state.move_card(instance_id, DISCARD_PILE)


def _find_card(game: ProductionBasicCardBatch, card_key: str) -> str:
    for instance_id, card in game.state.cards_by_id.items():
        if card.card_key == card_key:
            return instance_id
    raise AssertionError(f"找不到{card_key}")


def _give_card(
    game: ProductionBasicCardBatch, player_id: str, card_key: str
) -> str:
    instance_id = _find_card(game, card_key)
    destination = ZoneRef.hand(player_id)
    if game.state.location_of(instance_id) != destination:
        game._state = game.state.move_card(instance_id, destination)
    return instance_id


def _enter_play(game: ProductionBasicCardBatch) -> None:
    for operation in ("proceed_prepare", "proceed_judgment", "proceed_draw"):
        _step(game, _require_op(game, operation))


def _pass_all_rescues(game: ProductionBasicCardBatch) -> None:
    while game.phase is ProductionPhase.DYING_RESCUE:
        _step(game, _require_op(game, "pass_rescue"))


def _end_turn(game: ProductionBasicCardBatch) -> None:
    if game.phase is ProductionPhase.PLAY:
        _step(game, _require_op(game, "end_play_phase"))
    while game.phase is ProductionPhase.DISCARD:
        submit = _op(game, "discard_phase_submit")
        if submit is not None:
            _step(game, submit)
        else:
            _step(game, _require_op(game, "select_discard_card"))
    if game.phase is ProductionPhase.END:
        _step(game, _require_op(game, "end_turn"))


def _advance_to(game: FormalIdentitySession, player_id: str) -> None:
    guard = 0
    while game.current_player_id != player_id:
        if game.phase is ProductionPhase.PREPARE:
            _enter_play(game)
        _end_turn(game)
        guard += 1
        assert guard < 20


def _players_of_role(
    game: FormalIdentitySession, role: StandardIdentityRole
) -> list[str]:
    return [
        player_id
        for player_id, item in game.identities_by_player.items()
        if item is role
    ]


def _slash_at(
    game: ProductionBasicCardBatch, victim_id: str
) -> LegalAction | None:
    for action in game.legal_actions():
        if (
            action.payload.get("operation") == "use_slash"
            and victim_id in action.target_ids
        ):
            return action
    return None


def _ensure_qinglong(game: ProductionBasicCardBatch, player_id: str) -> None:
    weapon_id = _find_card(game, "sgs_weapon_qinglongyanyuedao")
    slot = ZoneRef.equipment(player_id, "weapon")
    current = game.state.card_ids_in(slot)
    if current and current[0] == weapon_id:
        return
    if current:
        game._state = game.state.move_card(current[0], DISCARD_PILE)
    game._state = game.state.move_card(weapon_id, slot)


def _kill(
    game: FormalIdentitySession,
    killer_id: str,
    victim_id: str,
    *,
    hp: int = 1,
) -> None:
    if not game.state.players_by_id[victim_id].alive:
        return
    for _ in range(16):
        if game.is_finished:
            return
        if game.phase is ProductionPhase.PREPARE:
            _enter_play(game)
        if game.current_player_id != killer_id:
            _advance_to(game, killer_id)
            if game.phase is ProductionPhase.PREPARE:
                _enter_play(game)
        _strip_hand(game, victim_id)
        _give_card(game, killer_id, SHA)
        _ensure_qinglong(game, killer_id)
        game._state = _replace_player(game.state, victim_id, hp=hp)
        action = _slash_at(game, victim_id)
        if action is None:
            _end_turn(game)
            continue
        _step(game, action)
        if _op(game, "pass_slash_response") is not None:
            _step(game, _require_op(game, "pass_slash_response"))
        _pass_all_rescues(game)
        return
    raise AssertionError(f"{killer_id}无法击杀{victim_id}")


def _topology(
    alive: dict[str, bool],
) -> PlayerTopology:
    players = []
    for index, player_id in enumerate(("p1", "p2", "p3", "p4", "p5"), start=1):
        is_alive = alive.get(player_id, True)
        players.append(
            PlayerState(
                player_id=player_id,
                seat=index,
                hp=4 if is_alive else 0,
                max_hp=4,
                alive=is_alive,
            )
        )
    return PlayerTopology(players=tuple(players))


def test_canonical_profile_and_trusted_boundary() -> None:
    config = _profile()
    assert isinstance(config, TrustedFormalIdentityConfiguration)
    assert config.physical_player_ids == ("p1", "p2", "p3", "p4", "p5")
    assert config.identity_cards == ("lord", "loyalist", "rebel", "rebel", "spy")
    assert config.base_hp == 4
    assert config.lord_hp == 5
    assert config.initial_hand_count == 4
    assert config.deck_supply_mode == "reshuffle_draw"
    assert config.hand_qi_ka_allowed is False
    assert_trusted_formal_identity_configuration(config)

    custom = FormalIdentityConfiguration()
    with pytest.raises(FormalIdentityConfigurationError, match="exact type"):
        assert_trusted_formal_identity_configuration(custom)


def test_invalid_configurations_rejected() -> None:
    with pytest.raises(FormalIdentityConfigurationError, match="长度为5"):
        FormalIdentityConfiguration(physical_player_ids=("p1", "p2"))  # type: ignore[arg-type]
    with pytest.raises(FormalIdentityConfigurationError, match="不能重复"):
        FormalIdentityConfiguration(
            physical_player_ids=("p1", "p1", "p3", "p4", "p5")
        )
    with pytest.raises(FormalIdentityConfigurationError, match="list/tuple|元组"):
        FormalIdentityConfiguration(
            physical_player_ids=["p1", "p2", "p3", "p4", "p5"]  # type: ignore[arg-type]
        )
    with pytest.raises(FormalIdentityConfigurationError, match="禁止手气卡"):
        FormalIdentityConfiguration(hand_qi_ka_allowed=True)
    with pytest.raises(FormalIdentityConfigurationError, match="reshuffle_draw"):
        FormalIdentityConfiguration(deck_supply_mode="no_reshuffle_draw")
    with pytest.raises(FormalIdentityConfigurationError, match="整数4"):
        FormalIdentityConfiguration(base_hp=True)  # type: ignore[arg-type]
    with pytest.raises(FormalIdentityConfigurationError, match="整数5"):
        FormalIdentityConfiguration(lord_hp=5.0)  # type: ignore[arg-type]


def test_public_trusted_construction_cannot_mint_capability() -> None:
    public = TrustedFormalIdentityConfiguration()
    with pytest.raises(FormalIdentityConfigurationError, match="capability"):
        assert_trusted_formal_identity_configuration(public)
    with pytest.raises(FormalIdentityConfigurationError, match="capability"):
        FormalIdentitySession(
            seed=1,
            configuration=public,
            analysis_only=False,
        )


@pytest.mark.parametrize(
    "reconstructor",
    (
        pytest.param(lambda value: replace(value), id="replace"),
        pytest.param(lambda value: copy(value), id="copy"),
        pytest.param(lambda value: deepcopy(value), id="deepcopy"),
    ),
)
def test_copy_replace_cannot_carry_capability(reconstructor: Any) -> None:
    reconstructed = reconstructor(_profile())
    with pytest.raises(FormalIdentityConfigurationError, match="capability"):
        assert_trusted_formal_identity_configuration(reconstructed)


def test_trusted_subclass_fail_closed() -> None:
    class Forged(TrustedFormalIdentityConfiguration):
        pass

    with pytest.raises(FormalIdentityConfigurationError, match="exact type"):
        assert_trusted_formal_identity_configuration(Forged())


def test_session_subclass_cannot_bypass_authority() -> None:
    class Sub(FormalIdentitySession):
        pass

    with pytest.raises(TypeError, match="子类"):
        Sub(seed=0, configuration=_profile(), analysis_only=True)


def test_canonical_initialization_and_single_rng() -> None:
    seed = 7
    game = _session(seed)
    assert game.mode_id == FORMAL_NO_SKILL_IDENTITY_5P_MODE
    assert game.physical_player_ids == ("p1", "p2", "p3", "p4", "p5")
    roles = list(game.identities_by_player.values())
    assert roles.count(StandardIdentityRole.LORD) == 1
    assert roles.count(StandardIdentityRole.LOYALIST) == 1
    assert roles.count(StandardIdentityRole.REBEL) == 2
    assert roles.count(StandardIdentityRole.SPY) == 1
    lord = game.lord_player_id
    assert game.identities_by_player[lord] is StandardIdentityRole.LORD
    assert game.numbered_player_order[0] == lord
    assert game.seat_by_player[lord] == 1
    assert game.first_player_id == lord
    assert game.current_player_id == lord
    physical = game.physical_player_ids
    lord_index = physical.index(lord)
    assert game.numbered_player_order == physical[lord_index:] + physical[:lord_index]
    assert game.state.players_by_id[lord].hp == 5
    assert game.state.players_by_id[lord].max_hp == 5
    for player_id in physical:
        if player_id != lord:
            player = game.state.players_by_id[player_id]
            assert player.hp == 4
            assert player.max_hp == 4
        assert len(game.state.card_ids_in(ZoneRef.hand(player_id))) == 4
        assert player_id in {item.player_id for item in game.state.players}
    assert len(game.state.card_ids_in(DRAW_PILE)) == 140
    assert all(
        event.event_type
        not in {EventType.HP_RECOVER, EventType.ARMOR_RECOVERED}
        for event in game.events
    )
    assert any(
        event.event_type is EventType.IDENTITY_REVEALED
        and event.payload.get("reason") == "initial_lord_reveal"
        and event.target_ids == (lord,)
        for event in game.events
    )
    operations = {action.payload.get("operation") for action in game.legal_actions()}
    assert "redraw" not in operations
    assert "replace_hand" not in operations
    assert "hand_qi_ka" not in operations
    assert game.deck_supply_mode == "reshuffle_draw"

    expected_cards = ["lord", "loyalist", "rebel", "rebel", "spy"]
    rng = DeterministicRNG(seed)
    rng.shuffle(expected_cards)
    assert game.rng_calls[0].method == "shuffle"
    assert list(game.rng_calls[0].arguments["before"]) == [
        "lord",
        "loyalist",
        "rebel",
        "rebel",
        "spy",
    ]
    assert list(game.rng_calls[0].result["after"]) == expected_cards
    assigned = [
        game.identities_by_player[player_id].value
        for player_id in game.physical_player_ids
    ]
    assert assigned == expected_cards
    assert game.rng_calls[1].method == "shuffle"
    same = _session(seed)
    other = _session(seed + 1)
    assert dict(same.identities_by_player) == dict(game.identities_by_player)
    assert dict(other.identities_by_player) != dict(game.identities_by_player)


def test_inspect_formal_identity_readiness() -> None:
    readiness = inspect_formal_identity_readiness()
    assert isinstance(readiness, FormalIdentityReadiness)
    assert readiness.mode_id == FORMAL_NO_SKILL_IDENTITY_5P_MODE
    assert readiness.deck_count == 160
    assert readiness.global_card_semantics_complete is True
    assert readiness.mode_runtime_reachable is True
    assert readiness.unsupported_rules == 0
    assert readiness.approximation_count == 0
    assert readiness.formal_identity_no_skill_ready is True
    assert readiness.identity_ready is True
    assert readiness.multi_player_production_proven is False
    assert readiness.authoritative_full_game_core is False
    assert readiness.blockers == ()


def test_analysis_only_does_not_produce_formal_result() -> None:
    game = _session(3, analysis_only=True)
    assert game.analysis_only is True
    assert game.formal_result_eligible is False


def test_outcome_matrix_policy() -> None:
    identities = {
        "p1": StandardIdentityRole.LORD,
        "p2": StandardIdentityRole.LOYALIST,
        "p3": StandardIdentityRole.REBEL,
        "p4": StandardIdentityRole.REBEL,
        "p5": StandardIdentityRole.SPY,
    }
    policy = IdentityOutcomePolicy(identities)
    assert policy.finish_reason == "identity_victory"
    assert policy.draw_finish_reason == "identity_draw_deck_exhausted"

    alive = {"p1": True, "p2": True, "p3": False, "p4": False, "p5": False}
    assert policy.resolve_winner_after_death(_topology(alive), "p5") == (
        "lord_and_loyalists"
    )

    alive = {"p1": True, "p2": False, "p3": False, "p4": False, "p5": True}
    assert policy.resolve_winner_after_death(_topology(alive), "p4") is None

    alive = {"p1": False, "p2": False, "p3": False, "p4": False, "p5": True}
    assert policy.resolve_winner_after_death(_topology(alive), "p1") == "spy"

    alive = {"p1": False, "p2": True, "p3": False, "p4": False, "p5": False}
    assert policy.resolve_winner_after_death(_topology(alive), "p1") == "rebels"

    alive = {"p1": False, "p2": False, "p3": True, "p4": False, "p5": False}
    assert policy.resolve_winner_after_death(_topology(alive), "p1") == "rebels"

    alive = {"p1": False, "p2": False, "p3": False, "p4": False, "p5": False}
    assert policy.resolve_winner_after_death(_topology(alive), "p1") == "rebels"


def test_real_session_lord_and_loyalists_and_skip_reward() -> None:
    game = _session(11)
    lord = game.lord_player_id
    rebels = _players_of_role(game, StandardIdentityRole.REBEL)
    spy = _players_of_role(game, StandardIdentityRole.SPY)[0]
    _kill(game, lord, rebels[0])
    assert game.is_finished is False
    _kill(game, lord, rebels[1])
    assert game.is_finished is False
    before_events = len(game.events)
    _kill(game, lord, spy)
    assert game.is_finished is True
    assert game.winner_id == "lord_and_loyalists"
    assert (
        game.outcome_policy is not None
        and game.outcome_policy.finish_reason == "identity_victory"
    )
    draw_rewards = [
        event
        for event in game.events[before_events:]
        if event.event_type is EventType.CARD_GAINED
        and event.payload.get("reason") == "identity_kill_rebel_draw"
    ]
    assert draw_rewards == []
    assert not any(
        event.event_type is EventType.DRAW for event in game.events[before_events:]
    )


def test_real_session_spy_victory_requires_unique_alive_spy() -> None:
    game = _session(21)
    lord = game.lord_player_id
    loyalist = _players_of_role(game, StandardIdentityRole.LOYALIST)[0]
    rebels = _players_of_role(game, StandardIdentityRole.REBEL)
    spy = _players_of_role(game, StandardIdentityRole.SPY)[0]
    _kill(game, lord, rebels[0])
    _kill(game, lord, rebels[1])
    _kill(game, spy, loyalist)
    assert game.is_finished is False
    _kill(game, spy, lord)
    assert game.is_finished is True
    assert game.winner_id == "spy"


def test_real_session_rebels_win_when_lord_dies_with_others() -> None:
    game = _session(31)
    lord = game.lord_player_id
    rebel = _players_of_role(game, StandardIdentityRole.REBEL)[0]
    _kill(game, rebel, lord)
    assert game.is_finished is True
    assert game.winner_id == "rebels"


def test_spy_death_blocks_later_spy_victory() -> None:
    game = _session(41)
    lord = game.lord_player_id
    spy = _players_of_role(game, StandardIdentityRole.SPY)[0]
    rebel = _players_of_role(game, StandardIdentityRole.REBEL)[0]
    _kill(game, lord, spy)
    assert game.is_finished is False
    _kill(game, rebel, lord)
    assert game.is_finished is True
    assert game.winner_id == "rebels"


def test_each_confirmed_death_checks_outcome_immediately() -> None:
    game = _session(51)
    lord = game.lord_player_id
    rebels = _players_of_role(game, StandardIdentityRole.REBEL)
    spy = _players_of_role(game, StandardIdentityRole.SPY)[0]
    winners_after: list[str | None] = []
    _kill(game, lord, rebels[0])
    winners_after.append(game.winner_id)
    _kill(game, lord, rebels[1])
    winners_after.append(game.winner_id)
    _kill(game, lord, spy)
    winners_after.append(game.winner_id)
    assert winners_after[:2] == [None, None]
    assert winners_after[2] == "lord_and_loyalists"


def test_any_identity_killing_rebel_draws_three() -> None:
    for seed, killer_role in (
        (61, StandardIdentityRole.LORD),
        (62, StandardIdentityRole.LOYALIST),
        (63, StandardIdentityRole.REBEL),
        (64, StandardIdentityRole.SPY),
    ):
        game = _session(seed)
        killer = _players_of_role(game, killer_role)[0]
        rebels = [
            player_id
            for player_id in _players_of_role(game, StandardIdentityRole.REBEL)
            if player_id != killer
        ]
        victim = rebels[0]
        if game.phase is ProductionPhase.PREPARE:
            _enter_play(game)
        _advance_to(game, killer)
        if game.phase is ProductionPhase.PREPARE:
            _enter_play(game)
        before = len(game.state.card_ids_in(ZoneRef.hand(killer)))
        _kill(game, killer, victim)
        assert game.is_finished is False
        after = len(game.state.card_ids_in(ZoneRef.hand(killer)))
        gained = [
            event
            for event in game.events
            if event.event_type is EventType.CARD_GAINED
            and event.payload.get("reason") == "identity_kill_rebel_draw"
            and event.target_ids == (killer,)
        ]
        assert len(gained) == 3
        assert after == before + 3


def test_lord_kills_loyalist_discards_hand_and_equipment() -> None:
    game = _session(71)
    lord = game.lord_player_id
    loyalist = _players_of_role(game, StandardIdentityRole.LOYALIST)[0]
    if game.phase is ProductionPhase.PREPARE:
        _enter_play(game)
    _advance_to(game, lord)
    if game.phase is ProductionPhase.PREPARE:
        _enter_play(game)
    delayed = _give_card(game, lord, "sgs_delayed_lebusi")
    game._state = game.state.move_card(delayed, ZoneRef.judgment(lord))
    weapon = _give_card(game, lord, "sgs_weapon_qinglongyanyuedao")
    game._state = game.state.move_card(
        weapon, ZoneRef.equipment(lord, "weapon")
    )
    assert delayed in game.state.card_ids_in(ZoneRef.judgment(lord))
    _kill(game, lord, loyalist)
    assert game.is_finished is False
    assert game.state.card_ids_in(ZoneRef.hand(lord)) == ()
    assert game.state.card_ids_in(ZoneRef.equipment(lord, "weapon")) == ()
    assert delayed in game.state.card_ids_in(ZoneRef.judgment(lord))
    assert game.state.location_of(weapon) == DISCARD_PILE


def test_non_lord_killing_loyalist_has_no_lord_penalty() -> None:
    game = _session(81)
    lord = game.lord_player_id
    loyalist = _players_of_role(game, StandardIdentityRole.LOYALIST)[0]
    spy = _players_of_role(game, StandardIdentityRole.SPY)[0]
    if game.phase is ProductionPhase.PREPARE:
        _enter_play(game)
    _kill(game, spy, loyalist)
    assert game.is_finished is False
    assert not any(
        event.payload.get("reason") == "identity_lord_kill_loyalist_penalty"
        for event in game.events
        if event.payload
    )


def test_no_damage_source_creates_no_identity_consequence() -> None:
    context = DeathConfirmationContext(
        dying_id="p3",
        final_damage_source=None,
        kill_credit=None,
        winner=None,
    )
    game = _session(91)
    policy = game.mode_policy
    state, runtime = policy.death_confirmed_hook(
        game, game.state, game.runtime, "p3", death_context=context
    )
    assert state is game.state
    assert runtime is game.runtime


def test_death_context_is_required_and_not_guessed() -> None:
    game = _session(92)
    policy = game.mode_policy
    with pytest.raises(FormalIdentityConfigurationError, match="DeathConfirmationContext"):
        policy.death_confirmed_hook(game, game.state, game.runtime, "p2")
