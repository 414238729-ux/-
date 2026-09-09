"""本轮早期短测：配置、模式初始状态和真实签名开局链。"""
import pytest

from scripts.sgs_engine.playable_config import GameConfig, MODE_SEATS
from scripts.sgs_engine.playable_game import PlayableGame
from scripts.sgs_engine.model import ZoneRef
from scripts.sgs_engine.actions import InvalidActionError


@pytest.mark.parametrize("mode", MODE_SEATS)
def test_each_mode_initializes_complete_generals(mode):
    cfg = GameConfig(mode=mode, control="AI_VS_AI", mulligan=False,
                     landlord_seat=2 if mode == "doudizhu" else None)
    game = PlayableGame(cfg)
    assert game.stage == "playing"
    assert len(game.state.players) == MODE_SEATS[mode]
    assert game.core.skill_runtime is not None
    registry = game.core.general_registry
    for player in game.state.players:
        general = registry.get_general(game.selected[player.player_id])
        bonus = int(game.roles.get(player.player_id) in ("lord", "landlord"))
        assert player.hp == general.starting_hp + bonus
        assert player.max_hp == general.max_hp + bonus
        assert tuple(game.core.skill_runtime.player_skills[player.player_id]) == general.skill_ids
    assert game.legal_actions()
    if mode == "2v2":
        assert [len(game.state.card_ids_in(ZoneRef.hand(pid))) for pid in cfg.player_ids] == [3, 4, 4, 5]
    if mode == "doudizhu":
        assert game.core.player_ids == ("p2", "p3", "p1")
        assert game.core.first_player_id == "p2"


def choose(game, operation, **values):
    return next(a for a in game.legal_actions() if a.payload["operation"] == operation
                and all(a.payload.get(k) == v for k, v in values.items()))


def test_bidding_selection_and_mulligan_signed_pipeline():
    game = PlayableGame(GameConfig(mode="doudizhu", selection="candidates", control="ALL_HUMAN"))
    first = game.actor
    legal = game.legal_actions()
    assert [a.payload["bid"] for a in legal] == [1]
    old = legal[0].action_id
    game.step(old)
    with pytest.raises(InvalidActionError):
        game.step(old)
    second = game.actor
    game.step(choose(game, "opening_bid", bid=3).action_id)
    assert game.roles[second] == "landlord" and game.roles[first] == "peasants"
    for _ in range(3):
        game.step(game.legal_actions()[0].action_id)
    assert game.stage == "mulligan"
    actor = game.actor
    untouched = {pid: game.state.card_ids_in(ZoneRef.hand(pid)) for pid in game.config.player_ids if pid != actor}
    for _ in range(8):
        game.step(choose(game, "opening_reroll_hand").action_id)
        game.state.assert_card_conservation()
    assert [a.payload["operation"] for a in game.legal_actions()] == ["opening_keep_hand"]
    assert untouched == {pid: game.state.card_ids_in(ZoneRef.hand(pid)) for pid in untouched}
    while game.stage == "mulligan":
        game.step(choose(game, "opening_keep_hand").action_id)
    assert game.core.first_player_id == second
    assert game.core.turn_loss_ledger.entries == ()


@pytest.mark.parametrize("values", [
    {"enabled_generals": ["xuyou"]}, {"mode": "unknown"}, {"seed": True},
    {"identities": ["lord"]}, {"human_seats": [1, 1]},
    {"ai_parameters": {"secret": 1}}, {"omniscient_debug": True},
    {"selection": "candidates", "candidate_count": 4},
])
def test_bad_config_rejected(values):
    with pytest.raises((ValueError, TypeError)):
        GameConfig(**values)
