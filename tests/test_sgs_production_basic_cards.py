# -*- coding: utf-8 -*-
"""正式160张牌堆六种基本牌生产批次的验收测试。

所有测试都经过真实生产注册表、权威核心、真实实体牌以及
enumerate_legal_actions -> validate_action -> apply_action 路径；
不使用固定概率、固定收益、fallback 或自证式断言。
"""

from __future__ import annotations

import copy
from dataclasses import replace

import pytest

from scripts.sgs_engine.actions import (
    ActionType,
    InvalidActionError,
    LegalAction,
    UnsupportedRuleError,
    apply_action,
    validate_action,
)
from scripts.sgs_engine.events import DamageEvent, EventType
from scripts.sgs_engine.model import DISCARD_PILE, DRAW_PILE, PROCESSING_ZONE, GameState, PlayerState, ZoneRef
from scripts.sgs_engine.production_batch import (
    PRODUCTION_BASIC_CARDS_MODE,
    BatchActionIdController,
    ProductionBatchDeckExhaustedError,
    ProductionBatchError,
    ProductionBatchSafetyLimitError,
    ScriptedBatchController,
    ProductionBasicCardBatch,
    ProductionBatchFinishedError,
    ProductionPhase,
)
from scripts.sgs_engine.production_cards import (
    PRODUCTION_ARMOR_KEYS,
    PRODUCTION_BASIC_CARD_KEYS,
    PRODUCTION_TRICK_KEYS,
    PRODUCTION_DELAYED_TRICK_KEYS,
    PRODUCTION_MOUNT_KEYS,
    PRODUCTION_WEAPON_KEYS,
    BasicCardAdapter,
    FormalCardRegistry,
    attack_range_of,
    is_valid_slash_target,
)
from scripts.sgs_engine.production_replay import (
    ProductionReplayDivergenceError,
    ProductionReplayFormatError,
    ProductionReexecutionReplay,
    _build_event_hash_chain,
    record_reference_production_batch,
    reexecute_production_replay,
)
from scripts.sgs_engine.replay import sha256_value
from scripts.sgs_engine.rng import RNGCall


def _hand_keys(game: ProductionBasicCardBatch, player_id: str) -> tuple[str, ...]:
    return tuple(
        game.state.cards_by_id[instance_id].card_key
        for instance_id in game.state.card_ids_in(ZoneRef.hand(player_id))
    )


def _action(
    game: ProductionBasicCardBatch,
    operation: str,
    *,
    card_key: str | None = None,
) -> object:
    for action in game.legal_actions():
        if action.payload.get("operation") != operation:
            continue
        if card_key is not None and action.payload.get("card_key") != card_key:
            continue
        return action
    return None


def _step(game: ProductionBasicCardBatch, action: object) -> object:
    assert action is not None and getattr(action, "action_id", None)
    return game.step(BatchActionIdController(action.action_id))


def _discard_to_end(game: ProductionBasicCardBatch) -> None:
    """弃牌阶段：选择恰好超限数量的手牌并一次性提交（CP-04O 批量弃置）。"""
    if game.phase is not ProductionPhase.DISCARD:
        # 手牌不超过上限时弃牌阶段已自动完成并进入结束阶段
        return
    while True:
        submit = next(
            (
                action
                for action in game.legal_actions()
                if action.payload.get("operation")
                == "discard_phase_submit"
            ),
            None,
        )
        if submit is not None:
            _step(game, submit)
            return
        select_actions = [
            action
            for action in game.legal_actions()
            if action.payload.get("operation") == "select_discard_card"
        ]
        if not select_actions:
            raise AssertionError(
                "弃牌阶段必须能提交恰好超限数量的弃牌选择"
            )
        _step(
            game,
            min(
                select_actions,
                key=lambda action: action.card_instance_id or "",
            ),
        )


def _fresh(*args: object, **kwargs: object) -> ProductionBasicCardBatch:
    """创建生产批处理会话并推进到出牌阶段（CP-04L 正式阶段流）。"""
    game = ProductionBasicCardBatch(*args, **kwargs)  # type: ignore[arg-type]
    for operation in ("proceed_prepare", "proceed_judgment", "proceed_draw"):
        action = next(
            a
            for a in game.legal_actions()
            if a.payload.get("operation") == operation
        )
        game.step(BatchActionIdController(action.action_id))
    assert game.phase.value == "play"
    return game

def _find_seed(predicate, max_seed: int = 150) -> int:
    for seed in range(1, max_seed + 1):
        game = _fresh(seed=seed)
        if predicate(game):
            return seed
    raise AssertionError("未在种子范围内找到满足条件的初始手牌")


# ---------------------------------------------------------------------
# 1-2 正式牌堆注册表
# ---------------------------------------------------------------------

def test_formal_160_deck_production_card_keys_map_to_production_adapters() -> None:
    game = _fresh(seed=1)
    registry = game.formal_registry

    assert registry.card_count == 160
    assert len(registry.instance_ids) == len(set(registry.instance_ids)) == 160
    assert set(registry.implemented_card_keys) == set(PRODUCTION_BASIC_CARD_KEYS) | set(PRODUCTION_TRICK_KEYS) | set(PRODUCTION_WEAPON_KEYS) | set(PRODUCTION_DELAYED_TRICK_KEYS) | set(PRODUCTION_ARMOR_KEYS) | set(PRODUCTION_MOUNT_KEYS)
    for key in PRODUCTION_BASIC_CARD_KEYS:
        adapter = registry.adapter_for(key)
        assert isinstance(adapter, BasicCardAdapter)
        assert adapter.implemented is True
        assert adapter.tested is True
        assert adapter.production_adapter is True
        spec = adapter.rule_spec()
        assert spec["card_key"] == key
        assert spec["implemented"] is True
        assert spec["production_adapter"] is True

    expected_counts = {
        "sgs_basic_sha": 30,
        "sgs_basic_huosha": 5,
        "sgs_basic_leisha": 9,
        "sgs_basic_shan": 24,
        "sgs_basic_tao": 12,
        "sgs_basic_jiu": 5,
    }
    for key, count in expected_counts.items():
        assert len(registry.instances_of(key)) == count
    assert not registry.unimplemented_card_keys
    assert registry.card_count == len(registry.records)
    game.state.assert_card_conservation()


def test_production_adapters_read_real_instance_suit_and_rank() -> None:
    game = _fresh(seed=1)
    registry = game.formal_registry

    for key in PRODUCTION_BASIC_CARD_KEYS:
        records = registry.instances_of(key)
        assert records
        for record in records:
            assert record.instance_id
            assert record.suit in {"♠", "♥", "♣", "♦"}
            assert record.rank
            card = game.state.cards_by_id[record.instance_id]
            assert card.card_key == key
            assert card.card_name == record.card_name
            assert card.suit == record.suit
            assert card.rank == record.rank
            assert card.card_type == "基本牌"

# ---------------------------------------------------------------------
# 3-6 三种【杀】的伤害属性与响应窗口
# ---------------------------------------------------------------------

def _use_slash_and_pass(game: ProductionBasicCardBatch, slash_key: str) -> None:
    action = _action(game, "use_slash", card_key=slash_key)
    assert action is not None, "出牌阶段必须能枚举该【杀】动作"
    _step(game, action)
    _step(game, _action(game, "pass_slash_response"))


def test_plain_slash_generates_no_attribute_damage() -> None:
    game = _fresh(seed=1)
    assert game.first_player_id == "p1"
    _use_slash_and_pass(game, "sgs_basic_sha")

    damages = [e for e in game.events if isinstance(e, DamageEvent)]
    assert len(damages) == 1
    assert damages[0].amount == 1
    assert damages[0].damage_type == "无属性"
    assert damages[0].card_user == "p1"
    assert damages[0].damage_source == "p1"
    assert damages[0].kill_credit == "p1"
    assert damages[0].card_key == "sgs_basic_sha"
    assert game.state.players_by_id["p2"].hp == 3


def test_fire_slash_generates_fire_damage() -> None:
    game = _fresh(seed=1)
    _use_slash_and_pass(game, "sgs_basic_huosha")

    damages = [e for e in game.events if isinstance(e, DamageEvent)]
    assert len(damages) == 1
    assert damages[0].damage_type == "火属性"
    assert damages[0].card_key == "sgs_basic_huosha"
    assert game.state.players_by_id["p2"].hp == 3


def test_thunder_slash_generates_thunder_damage() -> None:
    game = _fresh(seed=28)
    assert game.first_player_id == "p1"
    _use_slash_and_pass(game, "sgs_basic_leisha")

    damages = [e for e in game.events if isinstance(e, DamageEvent)]
    assert len(damages) == 1
    assert damages[0].damage_type == "雷属性"
    assert damages[0].card_key == "sgs_basic_leisha"
    assert game.state.players_by_id["p2"].hp == 3


@pytest.mark.parametrize(
    ("slash_key", "seed"),
    [
        ("sgs_basic_sha", 1),
        ("sgs_basic_huosha", 1),
        ("sgs_basic_leisha", 28),
    ],
)
def test_each_slash_establishes_real_response_window(slash_key: str, seed: int) -> None:
    game = _fresh(seed=seed)
    action = _action(game, "use_slash", card_key=slash_key)
    _step(game, action)

    assert game.phase is ProductionPhase.SLASH_RESPONSE
    assert game.current_actor_id == "p2"
    assert game.runtime.response_window_id == (
        f"slash:{game.runtime.turn_number}:{action.card_instance_id}"
    )
    window = game._build_window(game.runtime)
    assert window.responder_order == ("p2",)
    assert window.allowed_event_types == frozenset((EventType.CARD_USED,))
    assert window.source_event is not None
    assert window.source_event.event_type is EventType.CARD_USED
    assert window.source_event.card_instance_id == action.card_instance_id
    assert game.state.location_of(action.card_instance_id) == PROCESSING_ZONE


# ---------------------------------------------------------------------
# 7-10 【闪】响应【杀】
# ---------------------------------------------------------------------

def test_dodge_response_generates_card_used() -> None:
    game = _fresh(seed=1)
    _step(game, _action(game, "use_slash", card_key="sgs_basic_sha"))
    dodge = _action(game, "play_dodge")
    assert dodge is not None
    assert dodge.card_instance_id is not None
    dodge_id = dodge.card_instance_id
    assert game.state.cards_by_id[dodge_id].card_key == "sgs_basic_shan"

    event_start = len(game.events)
    _step(game, dodge)
    produced = game.events[event_start:]
    used = [e for e in produced if e.event_type is EventType.CARD_USED]
    assert len(used) == 1
    assert used[0].card_instance_id == dodge_id
    assert used[0].card_user == "p2"
    assert used[0].card_key == "sgs_basic_shan"
    assert used[0].payload.get("response_to") is not None


def test_dodge_response_does_not_generate_card_played() -> None:
    game = _fresh(seed=1)
    _step(game, _action(game, "use_slash", card_key="sgs_basic_sha"))
    _step(game, _action(game, "play_dodge"))

    assert EventType.CARD_PLAYED not in {
        e.event_type for e in game.events
    }


def test_slash_without_dodge_deals_real_damage() -> None:
    game = _fresh(seed=1)
    _use_slash_and_pass(game, "sgs_basic_sha")

    assert any(isinstance(e, DamageEvent) for e in game.events)
    assert EventType.CARD_EFFECT_CANCELLED not in {
        e.event_type for e in game.events
    }
    assert game.state.players_by_id["p2"].hp == 3


def test_slash_cancelled_by_dodge_deals_no_damage() -> None:
    game = _fresh(seed=1)
    _step(game, _action(game, "use_slash", card_key="sgs_basic_sha"))
    slash_id = game.runtime.pending_slash.slash_instance_id
    _step(game, _action(game, "play_dodge"))

    assert not any(isinstance(e, DamageEvent) for e in game.events)
    assert game.state.players_by_id["p2"].hp == 4
    cancelled = [
        e
        for e in game.events
        if e.event_type is EventType.CARD_EFFECT_CANCELLED
    ]
    assert len(cancelled) == 1
    assert cancelled[0].card_instance_id == slash_id
    assert cancelled[0].payload.get("reason") == "dodge"
    assert game.state.location_of(slash_id) == DISCARD_PILE

# ---------------------------------------------------------------------
# 11-12 次数限制与目标/距离合法性
# ---------------------------------------------------------------------

def test_plain_slash_respects_one_per_play_phase() -> None:
    game = _fresh(seed=28)
    assert game.first_player_id == "p1"
    slash_keys = {
        game.state.cards_by_id[a.card_instance_id].card_key
        for a in game.legal_actions()
        if a.payload.get("operation") == "use_slash"
    }
    assert "sgs_basic_sha" in slash_keys and "sgs_basic_leisha" in slash_keys

    _step(game, _action(game, "use_slash", card_key="sgs_basic_sha"))
    _step(game, _action(game, "pass_slash_response"))
    assert game.runtime.slash_used_counts.get("p1", 0) == 1
    assert all(
        a.payload.get("operation") != "use_slash"
        for a in game.legal_actions()
    )

    _step(game, _action(game, "end_play_phase"))
    _discard_to_end(game)
    _step(game, _action(game, "end_turn"))
    # CP-04K：出杀次数按角色记录；回合结束时只重置新回合角色的计数，
    # p1 在本回合的出杀计数保留到其自身下一个出牌阶段开始时才清零。
    assert game.runtime.slash_used_counts.get("p1", 0) == 1
    assert game.runtime.slash_used_counts.get("p2", 0) == 0
    assert game.runtime.current_player_id == "p2"


def test_all_three_slashes_enforce_target_and_distance_checks() -> None:
    for slash_key, seed in (
        ("sgs_basic_sha", 1),
        ("sgs_basic_huosha", 1),
        ("sgs_basic_leisha", 28),
    ):
        game = _fresh(seed=seed)
        for action in game.legal_actions():
            if (
                action.payload.get("operation") != "use_slash"
                or action.payload.get("card_key") != slash_key
            ):
                continue
            assert action.target_ids == ("p2",)
            assert is_valid_slash_target(game.state, "p1", "p2")
            assert is_valid_slash_target(game.state, "p1", "p1") is False
        # 攻击范围外目标不能产生合法动作（四人环中距离2超过范围1）
        records = game.formal_registry.records
        players = (
            PlayerState("p1", 1, 4, 4),
            PlayerState("p2", 2, 4, 4),
            PlayerState("p3", 3, 4, 4),
            PlayerState("p4", 4, 4, 4),
        )
        wide = GameState.from_deck_records(records, players=players)
        assert is_valid_slash_target(wide, "p1", "p3") is False
        assert is_valid_slash_target(wide, "p1", "p4") is True
        assert is_valid_slash_target(wide, "p1", "p1") is False


# ---------------------------------------------------------------------
# 13-17 【桃】
# ---------------------------------------------------------------------

def test_peach_self_heal_in_own_play_phase_when_wounded() -> None:
    game = _fresh(seed=18, player_hp=(3, 4))
    assert game.first_player_id == "p1"
    assert "sgs_basic_tao" in _hand_keys(game, "p1")

    peach = _action(game, "heal_self")
    assert peach is not None
    assert peach.target_ids == ("p1",)
    peach_id = peach.card_instance_id
    _step(game, peach)

    assert game.state.players_by_id["p1"].hp == 4
    assert game.phase is ProductionPhase.PLAY
    used = [
        e
        for e in game.events
        if e.event_type is EventType.CARD_USED
        and e.card_key == "sgs_basic_tao"
    ]
    assert len(used) == 1
    assert used[0].card_instance_id == peach_id
    assert used[0].payload.get("purpose") == "heal_self"
    assert game.state.location_of(peach_id) == DISCARD_PILE


def test_peach_self_heal_unavailable_at_full_hp() -> None:
    game = _fresh(seed=18)
    assert game.first_player_id == "p1"
    assert "sgs_basic_tao" in _hand_keys(game, "p1")
    assert game.state.players_by_id["p1"].hp == game.state.players_by_id["p1"].max_hp

    assert _action(game, "heal_self") is None
    assert all(
        a.payload.get("operation") != "heal_self"
        for a in game.legal_actions()
    )


def test_peach_enters_real_dying_rescue_flow() -> None:
    game = _fresh(seed=49, player_hp=(1, 1))
    assert game.first_player_id == "p1"
    _step(game, _action(game, "use_slash"))
    _step(game, _action(game, "pass_slash_response"))

    assert game.phase is ProductionPhase.DYING_RESCUE
    assert game.runtime.pending_dying_id == "p2"
    assert game.state.players_by_id["p2"].hp == 0
    assert any(e.event_type is EventType.DYING for e in game.events)
    assert game.current_actor_id == "p1"

    _step(game, _action(game, "pass_rescue"))
    assert game.current_actor_id == "p2"
    peach = _action(game, "rescue_with_peach")
    assert peach is not None
    assert peach.target_ids == ("p2",)
    assert peach.card_instance_id is not None
    peach_id = peach.card_instance_id
    assert game.state.cards_by_id[peach_id].card_key == "sgs_basic_tao"
    _step(game, peach)

    assert game.state.players_by_id["p2"].hp == 1
    assert game.phase is ProductionPhase.PLAY
    assert game.runtime.pending_dying_id is None


def test_rescue_success_stops_unnecessary_rescue_and_returns_to_play() -> None:
    game = _fresh(seed=49, player_hp=(1, 1))
    _step(game, _action(game, "use_slash"))
    _step(game, _action(game, "pass_slash_response"))
    _step(game, _action(game, "pass_rescue"))
    peach = _action(game, "rescue_with_peach")
    _step(game, peach)

    assert game.state.players_by_id["p2"].hp == 1
    assert game.phase is ProductionPhase.PLAY
    assert game.runtime.rescue_order == ()
    assert game.runtime.response_window_id is None
    used = [
        e
        for e in game.events
        if e.event_type is EventType.CARD_USED
        and e.card_key == "sgs_basic_tao"
    ]
    assert used[0].payload.get("purpose") == "dying_rescue"
    assert used[0].payload.get("response_window_id", "").startswith("dying:")
    assert game.state.location_of(used[0].card_instance_id) == DISCARD_PILE


def test_rescue_failure_confirms_death_and_victory() -> None:
    game = _fresh(
        seed=2, player_hp=(1, 1), player_max_hp=(1, 1)
    )
    game.run(
        ScriptedBatchController(
            [
                {"operation": "use_slash"},
                {"operation": "pass_slash_response"},
                {"operation": "pass_rescue"},
                {"operation": "pass_rescue"},
            ]
        ),
        max_steps=50,
    )

    assert game.is_finished
    assert game.winner_id == "p1"
    assert game.state.players_by_id["p2"].alive is False
    assert game.state.players_by_id["p2"].hp < 1
    types = [e.event_type for e in game.events]
    assert EventType.DEATH in types
    assert EventType.VICTORY in types

# 18-23 【酒】两种用途
# ---------------------------------------------------------------------

def _wine_buff_then_slash(game: ProductionBasicCardBatch) -> object:
    """使用出牌阶段【酒】强化后使用普通【杀】，返回【杀】动作。"""
    wine = _action(game, "use_wine_buff")
    assert wine is not None, "p1手牌有【酒】时必须能枚举强化用途"
    _step(game, wine)
    slash = _action(game, "use_slash", card_key="sgs_basic_sha")
    assert slash is not None
    _step(game, slash)
    return slash


def test_wine_buff_boosts_next_slash_damage() -> None:
    game = _fresh(seed=49)
    assert game.first_player_id == "p1"
    assert "sgs_basic_jiu" in _hand_keys(game, "p1")

    wine = _action(game, "use_wine_buff")
    assert wine.target_ids == ("p1",)
    wine_id = wine.card_instance_id
    hp_before = game.state.players_by_id["p1"].hp
    _step(game, wine)

    assert game.runtime.wine_buff_owner_id == "p1"
    assert game.runtime.wine_buff_used_this_play_phase is True
    assert game.state.players_by_id["p1"].hp == hp_before, "强化用途【酒】不得立即回复体力"
    buff_events = [
        e
        for e in game.events
        if e.event_type is EventType.CARD_USED and e.card_key == "sgs_basic_jiu"
    ]
    assert buff_events[-1].payload.get("purpose") == "play_phase_slash_buff"
    assert game.state.location_of(wine_id) == DISCARD_PILE

    slash = _action(game, "use_slash", card_key="sgs_basic_sha")
    _step(game, slash)
    assert game.runtime.pending_slash is not None
    assert game.runtime.pending_slash.boosted is True
    assert game.runtime.wine_buff_owner_id is None, "强化状态应被下一张【杀】消费"
    slash_used = [
        e
        for e in game.events
        if e.event_type is EventType.CARD_USED
        and e.card_instance_id == slash.card_instance_id
    ]
    assert slash_used[-1].payload.get("boosted") is True

    _step(game, _action(game, "pass_slash_response"))
    damages = [e for e in game.events if isinstance(e, DamageEvent)]
    assert len(damages) == 1
    assert damages[0].amount == 2
    assert damages[0].damage_type == "无属性"
    assert game.state.players_by_id["p2"].hp == 2


def test_wine_buff_respects_once_per_play_phase() -> None:
    game = _fresh(seed=49)
    wine = _action(game, "use_wine_buff")
    _step(game, wine)

    assert _action(game, "use_wine_buff") is None
    assert all(
        a.payload.get("operation") != "use_wine_buff"
        for a in game.legal_actions()
    )
    assert game.runtime.wine_buff_used_this_play_phase is True

    # 已执行动作不能在本阶段再次提交（动作已随状态指纹过期）
    with pytest.raises(ProductionBatchError):
        _step(game, wine)


def test_wine_dying_self_rescue_recovers_one_hp() -> None:
    game = _fresh(seed=49, player_hp=(1, 1))
    assert game.first_player_id == "p1"
    _step(game, _action(game, "use_slash"))
    _step(game, _action(game, "pass_slash_response"))
    assert game.phase is ProductionPhase.DYING_RESCUE
    assert game.runtime.pending_dying_id == "p2"

    _step(game, _action(game, "pass_rescue"))
    assert game.current_actor_id == "p2"
    wine = _action(game, "rescue_with_wine")
    assert wine is not None
    assert wine.target_ids == ("p2",)
    wine_id = wine.card_instance_id
    assert game.state.cards_by_id[wine_id].card_key == "sgs_basic_jiu"
    _step(game, wine)

    assert game.state.players_by_id["p2"].hp == 1
    assert game.phase is ProductionPhase.PLAY
    assert game.runtime.pending_dying_id is None
    used = [
        e
        for e in game.events
        if e.event_type is EventType.CARD_USED and e.card_key == "sgs_basic_jiu"
    ]
    assert used[-1].payload.get("purpose") == "dying_self_rescue"
    assert game.state.location_of(wine_id) == DISCARD_PILE
    # 全程仅记录【杀】造成的1点伤害；救援本身不产生额外伤害
    damages = [e for e in game.events if isinstance(e, DamageEvent)]
    assert len(damages) == 1
    assert damages[0].amount == 1


def test_wine_play_phase_and_dying_rescue_purposes_are_not_merged() -> None:
    game = _fresh(seed=49, player_hp=(1, 1))
    _step(game, _action(game, "use_slash"))
    _step(game, _action(game, "pass_slash_response"))
    _step(game, _action(game, "pass_rescue"))
    _step(game, _action(game, "rescue_with_wine"))

    # 濒死自救不建立加伤状态，也不消耗出牌阶段强化额度
    assert game.runtime.wine_buff_owner_id is None
    assert game.runtime.wine_buff_used_this_play_phase is False
    purposes = [
        e.payload.get("purpose")
        for e in game.events
        if e.event_type is EventType.CARD_USED and e.card_key == "sgs_basic_jiu"
    ]
    assert purposes == ["dying_self_rescue"]

    # 同出牌阶段内仍可使用强化用途，证明两种用途额度分离
    buff = _action(game, "use_wine_buff")
    assert buff is not None
    _step(game, buff)
    assert game.runtime.wine_buff_used_this_play_phase is True


def test_wine_boosted_slash_cancelled_by_dodge_deals_no_damage() -> None:
    game = _fresh(seed=49)
    slash = _wine_buff_then_slash(game)
    dodge = _action(game, "play_dodge")
    assert dodge is not None
    _step(game, dodge)

    assert not any(isinstance(e, DamageEvent) for e in game.events)
    assert game.state.players_by_id["p2"].hp == 4
    cancelled = [
        e
        for e in game.events
        if e.event_type is EventType.CARD_EFFECT_CANCELLED
    ]
    assert len(cancelled) == 1
    assert cancelled[0].card_instance_id == slash.card_instance_id
    assert game.state.location_of(slash.card_instance_id) == DISCARD_PILE
    assert game.runtime.wine_buff_owner_id is None


def test_wine_buff_cleared_at_turn_end_not_earlier() -> None:
    game = _fresh(seed=49)
    _step(game, _action(game, "use_wine_buff"))
    assert game.runtime.wine_buff_owner_id == "p1"

    _step(game, _action(game, "end_play_phase"))
    _discard_to_end(game)
    assert game.phase is ProductionPhase.END
    assert game.runtime.wine_buff_owner_id == "p1", "强化状态应持续到回合结束清除时点"

    _step(game, _action(game, "end_turn"))
    assert game.runtime.current_player_id == "p2"
    assert game.runtime.wine_buff_owner_id is None
    assert game.runtime.wine_buff_used_this_play_phase is False
    assert not any(isinstance(e, DamageEvent) for e in game.events)


# ---------------------------------------------------------------------
# 24-26 生命周期、守恒与唯一牌区
# ---------------------------------------------------------------------

def test_all_six_basic_cards_complete_real_zone_lifecycle() -> None:
    game = _fresh(seed=5)
    result = game.run()
    assert result.winner_id in ("p1", "p2")

    used_by_key: dict[str, list[object]] = {}
    for event in game.events:
        if (
            event.event_type is EventType.CARD_USED
            and event.card_key in PRODUCTION_BASIC_CARD_KEYS
        ):
            used_by_key.setdefault(event.card_key, []).append(event)
    assert set(used_by_key) == set(PRODUCTION_BASIC_CARD_KEYS)

    moves_by_instance: dict[str, list[object]] = {}
    for event in game.events:
        if event.event_type is EventType.CARD_MOVED:
            moves_by_instance.setdefault(event.card_instance_id, []).append(event)

    for key in PRODUCTION_BASIC_CARD_KEYS:
        used = used_by_key[key][0]
        instance_id = used.card_instance_id
        moves = moves_by_instance.get(instance_id, [])
        entered = [
            move
            for move in moves
            if move.payload.get("destination", {}).get("kind") == "processing"
            and move.payload.get("source", {}).get("kind") == "hand"
            and move.payload.get("source", {}).get("owner_id") == used.card_user
        ]
        left = [
            move
            for move in moves
            if move.payload.get("destination", {}).get("kind") == "discard_pile"
        ]
        assert entered, f"{key}缺少手牌区->处理区的真实移动事件"
        assert left, f"{key}缺少处理区->弃牌堆的真实移动事件"
        assert game.state.location_of(instance_id) == DISCARD_PILE


def test_card_conservation_holds_through_every_step_and_game_end() -> None:
    game = _fresh(seed=5)
    game.state.assert_card_conservation()
    for _ in range(10):
        game.step()
        game.state.assert_card_conservation()
    game.run(max_steps=500)
    game.state.assert_card_conservation()
    zone_total = sum(
        len(game.state.card_ids_in(zone)) for zone in game.state.zone_order
    )
    assert zone_total == 160
    assert len(game.state.cards) == 160


def test_every_entity_card_occupies_exactly_one_zone() -> None:
    game = _fresh(seed=5)
    for state in (game.state, game.run().final_state):
        seen: list[str] = []
        for zone in state.zone_order:
            ids = state.card_ids_in(zone)
            overlap = set(seen).intersection(ids)
            assert not overlap, f"实体牌同时位于多个区域：{sorted(overlap)}"
            seen.extend(ids)
        assert len(seen) == len(set(seen)) == 160
        for instance_id in seen:
            assert instance_id in state.card_locations


# ---------------------------------------------------------------------
# 27-30 动作管线、未实现卡牌失败关闭与注册表隔离
# ---------------------------------------------------------------------

def test_actions_must_pass_enumerate_validate_apply_pipeline() -> None:
    game = _fresh(seed=1)
    slash = _action(game, "use_slash", card_key="sgs_basic_sha")
    assert slash is not None
    assert slash.action_id is not None
    revision_before = game.state.revision
    executed = _step(game, slash)
    assert executed.action_id == slash.action_id
    assert game.state.revision > revision_before

    # 伪造内容但保留原action_id：必须被拒绝
    forged = replace(
        slash,
        payload={
            "operation": "use_slash",
            "card_key": "sgs_basic_huosha",
            "card_name": "火杀",
        },
    )
    with pytest.raises(InvalidActionError):
        validate_action(game.state, game._context(), forged, game.registry)

    # 凭空构造的action_id：必须被拒绝
    fabricated = LegalAction(
        action_type=ActionType.USE_CARD,
        actor_id="p1",
        card_instance_id=slash.card_instance_id,
        target_ids=("p2",),
        payload={"operation": "use_slash", "card_key": "sgs_basic_sha"},
        action_id="act_forged",
    )
    with pytest.raises(InvalidActionError):
        validate_action(game.state, game._context(), fabricated, game.registry)

    # 直接修改状态必须失败（不可变状态）
    with pytest.raises(Exception):
        game.state.players_by_id["p1"].hp = 99


def test_unimplemented_trick_cards_fail_closed_without_fallback() -> None:
    game = _fresh(seed=49)
    registry = game.formal_registry
    assert not registry.unimplemented_card_keys
    registry.assert_no_unimplemented_fallback()

    # 合法动作集合只引用已注册生产适配器的卡牌实体
    for action in game.legal_actions():
        if action.card_instance_id is None:
            continue
        card_key = game.state.cards_by_id[action.card_instance_id].card_key
        assert card_key in registry.implemented_card_keys

    # 伪造卡牌动作（把坐骑实体伪装成杀动作）不能通过验证
    trick_record = next(
        record
        for record in registry.records
        if record.card_key in PRODUCTION_MOUNT_KEYS
    )
    forged = LegalAction(
        action_type=ActionType.USE_CARD,
        actor_id="p1",
        card_instance_id=trick_record.instance_id,
        target_ids=("p2",),
        payload={
            "operation": "use_slash",
            "card_key": trick_record.card_key,
            "card_name": trick_record.card_name,
        },
        action_id="act_trick_forged",
    )
    with pytest.raises(InvalidActionError):
        validate_action(game.state, game._context(), forged, game.registry)


def test_unimplemented_equipment_fails_closed_including_range() -> None:
    game = _fresh(seed=49)
    registry = game.formal_registry
    # CP-04K：11种武器牌本体已接入生产注册表；CP-04N：两种坐骑已接入。
    assert "sgs_weapon_qinggangjian" in registry.implemented_card_keys
    assert "sgs_mount_defensive" in registry.implemented_card_keys
    assert "sgs_mount_offensive" in registry.implemented_card_keys

    # 装备武器后攻击范围按正式结构化CSV动态计算（青釭剑=2），不再返回近似值
    weapon = next(
        record
        for record in registry.records
        if record.card_key == "sgs_weapon_qinggangjian"
    )
    equipped = game.state.move_card(
        weapon.instance_id, ZoneRef.equipment("p1", "weapon")
    )
    assert attack_range_of(equipped, "p1") == 2
    assert is_valid_slash_target(equipped, "p1", "p2") is True
    # 无武器时默认攻击范围1
    assert attack_range_of(game.state, "p1") == 1

    # 伪造坐骑装备动作（把装备动作伪装成杀动作）不能通过验证
    mount_id = next(
        instance_id
        for instance_id in game.state.card_ids_in(ZoneRef.hand("p1"))
        if game.state.cards_by_id[instance_id].card_key == "sgs_mount_defensive"
    )
    forged = LegalAction(
        action_type=ActionType.USE_CARD,
        actor_id="p1",
        card_instance_id=mount_id,
        target_ids=("p1",),
        payload={
            "operation": "use_slash",
            "card_key": "sgs_mount_defensive",
            "card_name": "的卢",
        },
        action_id="act_mount_forged",
    )
    with pytest.raises(InvalidActionError):
        validate_action(game.state, game._context(), forged, game.registry)


def test_test_only_adapters_never_enter_production_registry() -> None:
    game = _fresh(seed=1)
    registry = game.formal_registry
    assert set(registry.adapters) == set(PRODUCTION_BASIC_CARD_KEYS) | set(PRODUCTION_TRICK_KEYS) | set(PRODUCTION_WEAPON_KEYS) | set(PRODUCTION_DELAYED_TRICK_KEYS) | set(PRODUCTION_ARMOR_KEYS) | set(PRODUCTION_MOUNT_KEYS)
    for key, adapter in registry.adapters.items():
        assert isinstance(adapter, BasicCardAdapter)
        assert not str(type(adapter).__module__).endswith(".duel")
        assert adapter.production_adapter is True

    assert game.state.deck_id != "test_only_duel_three_card_deck"
    registered = set(game.registry.registered_keys)
    for key in registered:
        assert key[0] == PRODUCTION_BASIC_CARDS_MODE
    # 生产注册表允许正式【决斗】响应阶段；只拒绝测试专用切片阶段。
    assert not any("test_only_duel" in phase for _, phase in registered)
    assert ("test_only_duel_vertical_slice", "play") not in registered


# ---------------------------------------------------------------------
# 31-34 严格规则重执行回放与篡改失败关闭
# ---------------------------------------------------------------------

def test_production_path_with_slash_dodge_peach_wine_reexecutes() -> None:
    record = record_reference_production_batch(seed=5)
    assert record.header["test_only"] is False
    assert record.header["formal_result"] is False
    assert record.header["production_basic_cards_batch"] is True
    assert record.decisions
    used_keys = {
        event.get("card_key")
        for event in record.events
        if event.get("event_type") == "card_used"
    }
    assert {"sgs_basic_sha", "sgs_basic_shan", "sgs_basic_tao", "sgs_basic_jiu"} <= used_keys

    result = reexecute_production_replay(record)
    assert result.verified is True
    assert result.winner_id == record.outcome["winner_id"]

    # 保存/加载往返后仍可严格重执行
    roundtrip = ProductionReexecutionReplay.from_dict(record.to_dict())
    roundtrip.verify_integrity()
    again = reexecute_production_replay(roundtrip)
    assert again.verified is True
    assert again.final_execution_hash == result.final_execution_hash


def test_tampered_replay_action_fails_closed() -> None:
    record = record_reference_production_batch(seed=5)
    tampered = copy.deepcopy(record.to_dict())
    decision = tampered["decisions"][0]
    legal_ids = [action["action_id"] for action in decision["legal_actions"]]
    bogus = "act_" + sha256_value("tampered-action-for-test")
    assert bogus not in legal_ids
    decision["chosen_action_id"] = bogus
    # 即使攻击者重新计算记录哈希，动作偏差也会被真实重执行拦截
    tampered["record_sha256"] = ""
    rebuilt = ProductionReexecutionReplay.from_dict(tampered)
    with pytest.raises(ProductionReplayDivergenceError):
        reexecute_production_replay(rebuilt)


def test_tampered_replay_event_fails_closed() -> None:
    record = record_reference_production_batch(seed=5)
    tampered = copy.deepcopy(record.to_dict())
    assert tampered["events"]
    tampered["events"][0]["card_key"] = "sgs_basic_sha"
    tampered["record_sha256"] = ""
    with pytest.raises(ProductionReplayFormatError):
        ProductionReexecutionReplay.from_dict(tampered)


def test_tampered_random_consumption_fails_closed() -> None:
    record = record_reference_production_batch(seed=5)
    tampered = copy.deepcopy(record.to_dict())
    first = tampered["random_consumptions"][0]
    old_result = first["result"]
    first["result"] = "p2" if old_result == "p1" else "p1"
    # 即使攻击者重新计算记录哈希，随机消费偏差也会被真实重执行拦截
    tampered["record_sha256"] = ""
    rebuilt = ProductionReexecutionReplay.from_dict(tampered)
    with pytest.raises(ProductionReplayDivergenceError):
        reexecute_production_replay(rebuilt)


# ---------------------------------------------------------------------
# 35 游戏结束后停止处理
# ---------------------------------------------------------------------

def test_finished_game_rejects_further_actions() -> None:
    game = _fresh(seed=5)
    result = game.run()
    assert game.is_finished
    assert game.winner_id == result.winner_id
    assert EventType.VICTORY in {e.event_type for e in game.events}
    event_count = len(game.events)
    revision = game.state.revision

    with pytest.raises(ProductionBatchFinishedError):
        game.legal_actions()
    with pytest.raises(ProductionBatchFinishedError):
        game.step()
    game.run()
    assert len(game.events) == event_count
    assert game.state.revision == revision
    assert game.winner_id == result.winner_id

# ---------------------------------------------------------------------
# 36 批次失败分支：非法上限、安全上限、牌堆耗尽与重洗
# ---------------------------------------------------------------------

def test_run_rejects_invalid_max_steps_parameters() -> None:
    game = _fresh(seed=1)
    for bad_value in (0, -1, True, 1.5, "500"):
        with pytest.raises(ValueError, match="安全动作上限"):
            game.run(max_steps=bad_value)
    # CP-04L：_fresh 已推进 PREPARE→JUDGMENT→DRAW 三个阶段动作
    assert game.step_count == 3


def test_run_safety_limit_fails_closed_without_forced_win() -> None:
    game = _fresh(seed=1)
    with pytest.raises(ProductionBatchSafetyLimitError):
        game.run(max_steps=1)
    # CP-04L：_fresh 推进3个阶段动作后，run(max_steps=1)再执行1步
    assert game.step_count == 4
    assert game.winner_id is None
    assert not game.is_finished
    assert not any(
        event.event_type is EventType.VICTORY for event in game.events
    )
    game.state.assert_card_conservation()


def test_deck_exhaustion_fails_closed_through_public_turn_flow() -> None:
    """牌堆彻底不足时原子失败关闭（CP-04O 正式弃牌阶段下重构）。

    弃牌阶段会把超限手牌逐张置入弃牌堆，因此双人正式流程中摸牌阶段
    的“牌堆＋可重洗弃牌堆均不足”状态在自然推进下不可达；本测试按
    判定耗竭测试的既有方式，在公开流程推进到 p2 摸牌阶段前通过权威
    牌区移动接口构造耗竭状态，再验证 proceed_draw 原子失败关闭。"""

    game = _fresh(seed=1, initial_hand_count=79)
    script = ScriptedBatchController(
        [
            {"operation": "end_play_phase"},
            {"operation": "end_turn"},
            {"operation": "proceed_prepare"},
            {"operation": "proceed_judgment"},
            {"operation": "proceed_draw"},
        ]
    )
    # CP-04O：p1弃牌阶段由参考控制器逐张弃置，直到p2进入摸牌阶段
    for _ in range(200):
        game.step(script)
        if (
            game.phase is ProductionPhase.DRAW
            and game.current_player_id == "p2"
        ):
            break
    else:
        raise AssertionError("未能在预期步数内推进到p2摸牌阶段")
    # 把牌堆与可重洗弃牌堆全部移入p2手牌，构造正式规则下可达的耗竭状态
    draw_ids = list(game.state.card_ids_in(DRAW_PILE))
    discard_ids = list(game.state.card_ids_in(DISCARD_PILE))
    moves = {
        instance_id: ZoneRef.hand("p2")
        for instance_id in draw_ids + discard_ids
    }
    game._state = game.state.move_cards(moves)
    events_before = len(game.events)
    rng_before = len(game.rng_calls)
    snapshot_before = game.execution_snapshot
    with pytest.raises(ProductionBatchDeckExhaustedError):
        game.step(script)
    assert len(game.events) == events_before
    assert len(game.rng_calls) == rng_before
    assert game.execution_snapshot == snapshot_before
    assert not game.is_finished
    assert game.winner_id is None
    assert not game.state.card_ids_in(DRAW_PILE)
    assert not game.state.card_ids_in(DISCARD_PILE)
    zone_total = sum(
        len(game.state.card_ids_in(zone)) for zone in game.state.zone_order
    )
    assert zone_total == len(game.state.cards) == 160
    game.state.assert_card_conservation()


def test_draw_reshuffle_continues_current_draw_with_auditable_events() -> None:
    game = _fresh(seed=1, initial_hand_count=79)
    script = ScriptedBatchController(
        [
            {"operation": "use_wine_buff"},
            {"operation": "use_slash"},
            {"operation": "pass_slash_response"},
            {"operation": "end_play_phase"},
            {"operation": "end_turn"},
        ]
    )
    # CP-04O：p1弃牌阶段由参考控制器逐张弃置（75张），直到p2摸牌阶段
    # 触发重洗并完成摸牌
    for _ in range(200):
        game.step(script)
        if any(
            event.payload.get("reason") == "reshuffle"
            for event in game.events
        ):
            break
    else:
        raise AssertionError("未能在预期步数内触发弃牌堆重洗")

    reshuffles = [
        event
        for event in game.events
        if event.payload.get("reason") == "reshuffle"
    ]
    assert len(reshuffles) == 77
    assert all(event.event_type is EventType.CARD_MOVED for event in reshuffles)
    assert all(
        event.payload["source"]["kind"] == "discard_pile"
        and event.payload["destination"]["kind"] == "draw_pile"
        for event in reshuffles
    )
    reshuffled_ids = {event.card_instance_id for event in reshuffles}
    assert len(reshuffled_ids) == 77
    reshuffle_sequence = max(
        event.sequence or 0 for event in reshuffles
    )

    draws_after_reshuffle = [
        event
        for event in game.events
        if event.event_type is EventType.CARD_MOVED
        and event.payload.get("reason") == "draw_phase"
        and event.card_instance_id in reshuffled_ids
        and (event.sequence or 0) > reshuffle_sequence
    ]
    assert len(draws_after_reshuffle) == 2
    assert all(
        event.payload["destination"]["kind"] == "hand"
        and event.payload["destination"]["owner_id"] == "p2"
        for event in draws_after_reshuffle
    )
    for draw in draws_after_reshuffle:
        reshuffle = next(
            event
            for event in reshuffles
            if event.card_instance_id == draw.card_instance_id
        )
        assert reshuffle.sequence < draw.sequence

    p2_hand = set(game.state.card_ids_in(ZoneRef.hand("p2")))
    drawn_ids = {event.card_instance_id for event in draws_after_reshuffle}
    assert drawn_ids.issubset(reshuffled_ids)
    assert drawn_ids.issubset(p2_hand)
    assert len(game.state.card_ids_in(DRAW_PILE)) == 75
    assert len(game.state.card_ids_in(DISCARD_PILE)) == 0
    assert any(call.method == "shuffle" for call in game.rng_calls)
    zone_total = sum(
        len(game.state.card_ids_in(zone)) for zone in game.state.zone_order
    )
    assert zone_total == len(game.state.cards) == 160
    game.state.assert_card_conservation()
