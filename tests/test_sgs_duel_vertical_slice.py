from __future__ import annotations

import pytest

from scripts.sgs_engine.actions import ActionType
from scripts.sgs_engine.duel import (
    STANDARD_PHASES,
    TEST_ONLY_DUEL_MODE,
    DeterministicReferenceController,
    DuelFinishedError,
    DuelPhase,
    DuelSafetyLimitError,
    TestOnlyDuelGame,
)
from scripts.sgs_engine.events import EventType
from scripts.sgs_engine.model import DISCARD_PILE, PROCESSING_ZONE, ZoneRef


def _phase_only_deck() -> tuple[str, ...]:
    # p1依次获得索引0/2/4/6，首次摸索引8/9；其中没有【杀】，可稳定观察六阶段。
    return (
        "闪",
        "杀",
        "闪",
        "杀",
        "桃",
        "杀",
        "桃",
        "杀",
        "闪",
        "桃",
        "杀",
        "杀",
    )


def _dodge_deck() -> tuple[str, ...]:
    # p1起手有杀，p2起手有闪；其余牌只用于满足测试小牌堆边界。
    return (
        "杀",
        "闪",
        "杀",
        "杀",
        "杀",
        "杀",
        "杀",
        "杀",
        "桃",
        "杀",
        "闪",
        "桃",
    )


def _rescue_deck() -> tuple[str, ...]:
    # p2起手有桃而没有闪；p1造成濒死后，p1先放弃，p2在自己的机会使用桃。
    return (
        "杀",
        "桃",
        "杀",
        "杀",
        "杀",
        "杀",
        "杀",
        "杀",
        "闪",
        "杀",
        "桃",
        "闪",
    )


def _lethal_deck() -> tuple[str, ...]:
    # 桃在p1手中；确定性控制器不会用自己的桃救援敌人p2。
    return (
        "杀",
        "杀",
        "桃",
        "杀",
        "杀",
        "杀",
        "杀",
        "杀",
        "闪",
        "杀",
        "桃",
        "闪",
    )


def _advance_to(game: TestOnlyDuelGame, phase: DuelPhase) -> None:
    for _ in range(50):
        if game.phase is phase:
            return
        game.step()
    raise AssertionError(f"未在动作上限内进入阶段{phase.value}")


def test_initial_state_uses_exact_test_mode_two_players_and_four_cards_each() -> None:
    game = TestOnlyDuelGame(seed=1, deck_keys=_phase_only_deck(), shuffle=False)

    assert TEST_ONLY_DUEL_MODE == "test_only_duel_vertical_slice"
    assert tuple(player.player_id for player in game.state.players) == ("p1", "p2")
    assert len(game.state.card_ids_in(ZoneRef.hand("p1"))) == 4
    assert len(game.state.card_ids_in(ZoneRef.hand("p2"))) == 4
    assert game.current_player_id == "p1"
    assert game.first_player_id == "p1"
    assert game.current_actor_id == "p1"
    assert set(game.registry.registered_keys) == {
        (TEST_ONLY_DUEL_MODE, phase.value)
        for phase in (*STANDARD_PHASES, DuelPhase.SLASH_RESPONSE, DuelPhase.DYING_RESCUE)
    }
    game.state.assert_card_conservation()


def test_six_standard_phases_advance_through_real_legal_action_path() -> None:
    game = TestOnlyDuelGame(seed=3, deck_keys=_phase_only_deck(), shuffle=False)
    controller = DeterministicReferenceController()

    for _ in range(20):
        if game.current_player_id == "p2" and game.phase is DuelPhase.PREPARE:
            break
        legal = game.legal_actions()
        chosen = game.step(controller)
        assert chosen in legal
    else:
        raise AssertionError("首回合未在安全步数内结束")

    observed = [
        entry.phase
        for entry in game.phase_history
        if entry.turn_number == 1 and entry.phase in STANDARD_PHASES
    ]
    # 弃牌阶段可因逐张弃牌重复停留，但六阶段的进入顺序必须固定。
    collapsed = [phase for index, phase in enumerate(observed) if index == 0 or phase != observed[index - 1]]
    assert collapsed == list(STANDARD_PHASES)
    assert game.current_player_id == "p2"
    assert game.state.revision > 0
    game.state.assert_card_conservation()


def test_slash_response_with_dodge_emits_used_not_damage() -> None:
    game = TestOnlyDuelGame(seed=1, deck_keys=_dodge_deck(), shuffle=False)
    _advance_to(game, DuelPhase.PLAY)

    slash = game.step()
    assert slash.action_type is ActionType.USE_CARD
    assert slash.payload["card_key"] == "杀"
    assert game.phase is DuelPhase.SLASH_RESPONSE
    assert game.state.location_of(slash.card_instance_id) == PROCESSING_ZONE

    dodge = game.step()
    assert dodge.action_type is ActionType.USE_CARD
    assert dodge.payload["card_key"] == "闪"
    assert game.phase is DuelPhase.PLAY
    assert game.state.players_by_id["p2"].hp == 4
    assert game.state.location_of(slash.card_instance_id) == DISCARD_PILE

    types = [event.event_type for event in game.events]
    assert EventType.CARD_USED in types
    assert EventType.CARD_PLAYED not in types
    assert EventType.CARD_EFFECT_CANCELLED in types
    assert EventType.DAMAGE not in types
    game.state.assert_card_conservation()


def test_damage_dying_and_self_peach_rescue_follow_current_turn_order() -> None:
    game = TestOnlyDuelGame(
        seed=1,
        deck_keys=_rescue_deck(),
        shuffle=False,
        player_hp=(4, 1),
    )
    _advance_to(game, DuelPhase.PLAY)
    slash = game.step()  # p1使用杀
    game.step()  # p2不出闪，受到伤害并进入濒死

    assert game.phase is DuelPhase.DYING_RESCUE
    assert game.state.location_of(slash.card_instance_id) == PROCESSING_ZONE
    assert game.current_actor_id == "p1"  # 救援从当前回合角色开始
    assert game.state.players_by_id["p2"].hp == 0
    game.step()  # p1不会用桃救敌人
    assert game.current_actor_id == "p2"
    rescue = game.step()

    assert rescue.payload["operation"] == "rescue_with_peach"
    assert game.state.players_by_id["p2"].hp == 1
    assert game.state.players_by_id["p2"].alive
    assert game.phase is DuelPhase.PLAY
    assert game.state.location_of(slash.card_instance_id) == DISCARD_PILE
    assert [event.event_type for event in game.events].count(EventType.DYING) == 1
    assert EventType.DEATH not in [event.event_type for event in game.events]
    game.state.assert_card_conservation()


def test_unrescued_dying_confirms_death_victory_and_hard_stops() -> None:
    game = TestOnlyDuelGame(
        seed=1,
        deck_keys=_lethal_deck(),
        shuffle=False,
        player_hp=(4, 1),
    )
    _advance_to(game, DuelPhase.PLAY)
    slash = game.step()  # 杀
    game.step()  # 伤害、濒死
    game.step()  # p1放弃救敌人
    game.step()  # p2无桃，确认死亡并判胜

    assert game.is_finished
    assert game.winner_id == "p1"
    assert game.state.location_of(slash.card_instance_id) == DISCARD_PILE
    assert not game.state.players_by_id["p2"].alive
    assert game.state.players_by_id["p2"].hp == 0
    assert [event.event_type for event in game.events][-2:] == [
        EventType.DEATH,
        EventType.VICTORY,
    ]
    before = (game.state, game.events, game.step_count)
    with pytest.raises(DuelFinishedError, match="胜利已经成立"):
        game.step()
    assert (game.state, game.events, game.step_count) == before


def test_complete_reference_game_is_deterministic_and_conserves_every_card() -> None:
    first = TestOnlyDuelGame(seed=20260801)
    second = TestOnlyDuelGame(seed=20260801)

    first_result = first.run(max_steps=300)
    second_result = second.run(max_steps=300)

    assert first_result.winner_id == second_result.winner_id
    assert first_result.step_count == second_result.step_count
    assert first_result.final_state == second_result.final_state
    assert [event.to_replay_dict() for event in first_result.events] == [
        event.to_replay_dict() for event in second_result.events
    ]
    assert first_result.rng_calls == second_result.rng_calls
    assert [event.sequence for event in first_result.events] == list(
        range(1, len(first_result.events) + 1)
    )
    first_result.final_state.assert_card_conservation()
    assert len(first_result.final_state.cards) == 24


def test_reference_controller_finishes_fixed_50_seed_matrix_without_cap() -> None:
    completed: list[tuple[int, int, str]] = []

    for seed in range(50):
        game = TestOnlyDuelGame(seed=seed)
        result = game.run(max_steps=500)
        result.final_state.assert_card_conservation()
        assert result.winner_id in {"p1", "p2"}
        assert result.step_count < 500
        assert game.state.card_ids_in(PROCESSING_ZONE) == ()
        completed.append((seed, result.step_count, result.winner_id))

    assert len(completed) == 50
    assert max(steps for _, steps, _ in completed) == 187


def test_first_player_uses_same_audited_rng_and_runtime_snapshot_is_hashable() -> None:
    first = TestOnlyDuelGame(seed=1, deck_keys=_phase_only_deck(), shuffle=False)
    second = TestOnlyDuelGame(seed=0, deck_keys=_phase_only_deck(), shuffle=False)

    assert first.first_player_id == "p1"
    assert second.first_player_id == "p2"
    assert first.rng_calls[0].method == "choice"
    assert second.rng_calls[0].method == "choice"
    assert first.execution_snapshot["runtime"]["phase"] == "prepare"
    assert len(first.execution_hash) == 64

    before = first.execution_hash
    first.step()
    assert first.execution_hash != before
    assert first.execution_snapshot["runtime"]["phase"] == "judgment"

    shuffled = TestOnlyDuelGame(seed=1, deck_keys=_phase_only_deck(), shuffle=True)
    assert [call.method for call in shuffled.rng_calls[:2]] == ["choice", "shuffle"]


def test_safety_limit_fails_closed_without_fabricated_winner() -> None:
    game = TestOnlyDuelGame(seed=9)

    with pytest.raises(DuelSafetyLimitError, match="禁止静默判胜或近似收尾"):
        game.run(max_steps=1)

    assert not game.is_finished
    assert game.winner_id is None
    assert EventType.VICTORY not in [event.event_type for event in game.events]
    game.state.assert_card_conservation()


@pytest.mark.parametrize(
    "hp, max_hp, error_type, message",
    [
        ((0, 4), (4, 4), ValueError, "至少1点体力"),
        ((4, 4), (0, 4), ValueError, "至少1点体力"),
        ((5, 4), (4, 4), ValueError, "不能高于体力上限"),
        ((True, 4), (4, 4), TypeError, "必须是整数"),
    ],
)
def test_initial_players_must_start_alive_with_valid_hp(
    hp: tuple[int, int],
    max_hp: tuple[int, int],
    error_type: type[Exception],
    message: str,
) -> None:
    with pytest.raises(error_type, match=message):
        TestOnlyDuelGame(
            seed=1,
            deck_keys=_phase_only_deck(),
            player_hp=hp,
            player_max_hp=max_hp,
            shuffle=False,
        )


@pytest.mark.parametrize(
    "keys, message",
    [
        (("杀", "闪", "桃"), "至少需要12张"),
        (("杀",) * 10 + ("闪", "酒"), "只支持"),
        (("杀",) * 11 + ("闪",), "必须同时包含"),
    ],
)
def test_test_deck_scope_is_explicit_and_fails_closed(
    keys: tuple[str, ...], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        TestOnlyDuelGame(seed=1, deck_keys=keys, shuffle=False)
