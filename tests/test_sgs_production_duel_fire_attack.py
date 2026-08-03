# -*- coding: utf-8 -*-
"""【决斗】与【火攻】生产垂直切片测试。

覆盖正式CSV实体绑定、使用时机与目标规则、【无懈可击】响应链复用、
【决斗】交替打出【杀】与伤害来源、死亡角色边界、【火攻】目标展示手牌
与同花色弃置、火焰伤害、隐藏信息隔离、严格回放与篡改失败关闭。
所有动作均经过真实 enumerate -> validate -> apply 路径；公开区域与死亡
边界测试使用不可变 GameState 与权威状态转换助手构造，不代表装备、
延时锦囊或武将技能已实现。
"""
from __future__ import annotations

import copy
from dataclasses import replace
from pathlib import Path

import pytest

from scripts.sgs_engine.actions import (
    ActionContext,
    ActionType,
    InvalidActionError,
    LegalAction,
    UnsupportedRuleError,
    validate_action,
)
from scripts.sgs_engine.events import EventType
from scripts.sgs_engine.model import (
    DISCARD_PILE,
    PROCESSING_ZONE,
    ZoneRef,
)
from scripts.sgs_engine.production_batch import (
    PRODUCTION_BASIC_CARDS_MODE,
    BatchActionIdController,
    ProductionBasicCardBatch,
    ProductionBatchFinishedError,
    ProductionBatchSafetyLimitError,
    ProductionPhase,
    ScriptedBatchController,
    _replace_player,
)
from scripts.sgs_engine.production_cards import (
    PRODUCTION_TRICK_KEYS,
    SLASH_CARD_KEYS,
    HuogongAdapter,
    JuedouAdapter,
)
from scripts.sgs_engine.production_replay import (
    ProductionReplayDivergenceError,
    ProductionReplayFormatError,
    ProductionReexecutionReplay,
    record_reference_production_batch,
    reexecute_production_replay,
)

DUEL = "sgs_trick_juedou"
HUO = "sgs_trick_huogong"
WUXIE = "sgs_trick_wuxiekeji"
WUZHONG = "sgs_trick_wuzhongshengyou"

REPO_ROOT = Path(__file__).resolve().parent.parent

_REVEAL_PAYLOAD_KEYS = {
    "operation",
    "trick_instance_id",
    "root_trick_instance_id",
    "user_id",
    "target_id",
    "window_id",
    "state_hash",
    "handle",
}


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
    target: str | None = None,
    actor: str | None = None,
) -> object:
    for action in game.legal_actions():
        if action.payload.get("operation") != operation:
            continue
        if card_key is not None and action.payload.get("card_key") != card_key:
            continue
        if target is not None and action.target_ids[0] != target:
            continue
        if actor is not None and action.actor_id != actor:
            continue
        return action
    return None


def _step(game: ProductionBasicCardBatch, action: object) -> None:
    assert action is not None and getattr(action, "action_id", None)
    game.step(BatchActionIdController(action.action_id))


def _pass_trick(game: ProductionBasicCardBatch) -> None:
    _step(game, _action(game, "pass_trick_response"))


def _close_trick_window(game: ProductionBasicCardBatch) -> None:
    _pass_trick(game)
    _pass_trick(game)


def _use_trick(
    game: ProductionBasicCardBatch,
    operation: str,
    card_key: str,
    target: str,
) -> str:
    action = _action(game, operation, card_key=card_key, target=target)
    assert action is not None, f"出牌阶段必须能枚举{operation}"
    assert action.target_ids == (target,)
    trick_id = action.card_instance_id
    assert trick_id is not None
    _step(game, action)
    return trick_id


def _fixture_set_state(game: ProductionBasicCardBatch, moves: dict) -> None:
    """测试夹具：用不可变GameState与正式牌区移动接口改变区域归属。"""
    game._state = game.state.move_cards(moves)


def _kill_player(game: ProductionBasicCardBatch, player_id: str) -> None:
    """用引擎自身状态转换助手构造死亡边界；不绕过后续任何事件与校验。"""
    game._state = _replace_player(game.state, player_id, hp=0, alive=False)


def _any_instance_of(game: ProductionBasicCardBatch, card_key: str) -> str:
    for card in game.state.cards:
        if card.card_key == card_key:
            return card.instance_id
    raise AssertionError(f"正式牌堆中必须存在{card_key}实体供夹具使用")


def _duel_open(
    game: ProductionBasicCardBatch, target: str = "p2"
) -> tuple[str, str]:
    """使用【决斗】并关闭无懈链，返回(决斗实体ID, 目标首次打出杀实体)。"""
    trick_id = _use_trick(game, "use_duel", DUEL, target)
    _close_trick_window(game)
    assert game.phase is ProductionPhase.DUEL_RESPONSE
    return trick_id, _action(game, "play_slash_for_duel")


def _fire_reveal_open(
    game: ProductionBasicCardBatch, target: str = "p2"
) -> str:
    trick_id = _use_trick(game, "use_fire_attack", HUO, target)
    _close_trick_window(game)
    assert game.phase is ProductionPhase.FIRE_ATTACK_REVEAL
    return trick_id

# ---------------------------------------------------------------------
# A. 注册表与正式牌堆
# ---------------------------------------------------------------------


def test_duel_entities_bind_to_production_adapter() -> None:
    game = ProductionBasicCardBatch(seed=3)
    registry = game.formal_registry
    assert DUEL in PRODUCTION_TRICK_KEYS
    assert DUEL in registry.implemented_card_keys
    records = registry.instances_of(DUEL)
    assert len(records) == 3
    assert len({record.instance_id for record in records}) == 3
    assert {(record.suit, record.rank) for record in records} == {
        ("♦", "A"),
        ("♣", "A"),
        ("♠", "A"),
    }
    adapter = registry.adapter_for(DUEL)
    assert isinstance(adapter, JuedouAdapter)
    assert adapter.implemented is True and adapter.tested is True
    spec = adapter.rule_spec()
    assert spec["card_key"] == DUEL
    assert spec["use_timing"] == "own_play_phase"
    assert spec["target_filter"] == "one_other_character"
    assert spec["distance_rule"] == "not_applicable"
    assert spec["nullification_eligible"] is True
    for record in records:
        card = game.state.cards_by_id[record.instance_id]
        assert card.card_key == DUEL and card.card_name == "决斗"


def test_huogong_entities_bind_to_production_adapter() -> None:
    game = ProductionBasicCardBatch(seed=3)
    registry = game.formal_registry
    assert HUO in PRODUCTION_TRICK_KEYS
    assert HUO in registry.implemented_card_keys
    records = registry.instances_of(HUO)
    assert len(records) == 3
    assert len({record.instance_id for record in records}) == 3
    assert {(record.suit, record.rank) for record in records} == {
        ("♦", "Q"),
        ("♥", "2"),
        ("♥", "3"),
    }
    adapter = registry.adapter_for(HUO)
    assert isinstance(adapter, HuogongAdapter)
    assert adapter.implemented is True and adapter.tested is True
    spec = adapter.rule_spec()
    assert spec["card_key"] == HUO
    assert spec["use_timing"] == "own_play_phase"
    assert "including_self" in str(spec["target_filter"])
    assert spec["distance_rule"] == "not_applicable"
    assert spec["nullification_eligible"] is True
    for record in records:
        card = game.state.cards_by_id[record.instance_id]
        assert card.card_key == HUO and card.card_name == "火攻"


def test_formal_deck_remains_160_with_unique_ids_and_single_zone() -> None:
    game = ProductionBasicCardBatch(seed=3)
    zone_total = sum(
        len(game.state.card_ids_in(zone)) for zone in game.state.zone_order
    )
    assert zone_total == len(game.state.cards) == 160
    assert len({card.instance_id for card in game.state.cards}) == 160
    for card in game.state.cards:
        locations = [
            zone
            for zone in game.state.zone_order
            if card.instance_id in game.state.card_ids_in(zone)
        ]
        assert len(locations) == 1


def test_implemented_and_remaining_card_counts_updated() -> None:
    game = ProductionBasicCardBatch(seed=3)
    registry = game.formal_registry
    assert DUEL in registry.implemented_card_keys
    assert HUO in registry.implemented_card_keys
    assert len(registry.implemented_card_keys) == 12
    assert len(registry.unimplemented_card_keys) == 26
    assert DUEL not in registry.unimplemented_card_keys
    assert HUO not in registry.unimplemented_card_keys
    assert (
        sum(len(registry.instances_of(key)) for key in registry.implemented_card_keys)
        == 113
    )
    assert {DUEL, HUO} <= set(PRODUCTION_TRICK_KEYS)


def test_other_unimplemented_cards_stay_fail_closed() -> None:
    game = ProductionBasicCardBatch(seed=3)
    registry = game.formal_registry
    for key in ("sgs_trick_jiedaosharen", "sgs_trick_nanmanruqin"):
        assert key in registry.unimplemented_card_keys
        with pytest.raises(UnsupportedRuleError):
            registry.adapter_for(key)
        with pytest.raises(UnsupportedRuleError):
            registry.rule_spec_for(key)
    with pytest.raises(UnsupportedRuleError):
        registry.assert_no_unimplemented_fallback()


# ---------------------------------------------------------------------
# B. 使用时机与目标合法性
# ---------------------------------------------------------------------


def test_duel_usable_only_in_own_play_phase() -> None:
    game = ProductionBasicCardBatch(seed=3)
    assert _action(game, "use_duel", card_key=DUEL) is not None
    _use_trick(game, "use_duel", DUEL, "p2")
    assert game.phase is ProductionPhase.TRICK_RESPONSE
    assert _action(game, "use_duel", card_key=DUEL) is None
    assert _action(game, "use_fire_attack", card_key=HUO) is None
    context = game._context()
    stale_hand_card = game.state.card_ids_in(ZoneRef.hand("p1"))[0]
    forged = replace(
        LegalAction(
            action_type=ActionType.USE_CARD,
            actor_id="p1",
            card_instance_id=stale_hand_card,
            target_ids=("p2",),
            payload={"operation": "use_duel", "card_key": DUEL},
        ),
        action_id="act_out_of_phase",
    )
    with pytest.raises(InvalidActionError):
        game.formal_registry.adapter_for(DUEL).apply_action(
            game.state, context, forged
        )


def test_huogong_usable_only_in_own_play_phase() -> None:
    game = ProductionBasicCardBatch(seed=14)
    assert _action(game, "use_fire_attack", card_key=HUO, target="p2") is not None
    _use_trick(game, "use_fire_attack", HUO, "p2")
    assert game.phase is ProductionPhase.TRICK_RESPONSE
    assert _action(game, "use_fire_attack", card_key=HUO) is None
    context = game._context()
    stale_hand_card = game.state.card_ids_in(ZoneRef.hand("p1"))[0]
    forged = replace(
        LegalAction(
            action_type=ActionType.USE_CARD,
            actor_id="p1",
            card_instance_id=stale_hand_card,
            target_ids=("p2",),
            payload={"operation": "use_fire_attack", "card_key": HUO},
        ),
        action_id="act_out_of_phase",
    )
    with pytest.raises(InvalidActionError):
        game.formal_registry.adapter_for(HUO).apply_action(
            game.state, context, forged
        )


def test_duel_cannot_target_self() -> None:
    game = ProductionBasicCardBatch(seed=3)
    action = _action(game, "use_duel", card_key=DUEL)
    assert action is not None and action.target_ids == ("p2",)
    forged = replace(action, target_ids=("p1",))
    with pytest.raises(InvalidActionError):
        validate_action(game.state, game._context(), forged, game.registry)


def test_duel_has_no_zone_or_distance_target_restriction() -> None:
    game = ProductionBasicCardBatch(seed=3)
    hand_ids = tuple(game.state.card_ids_in(ZoneRef.hand("p2")))
    _fixture_set_state(game, {instance_id: DISCARD_PILE for instance_id in hand_ids})
    mount_id = _any_instance_of(game, "sgs_mount_defensive")
    _fixture_set_state(
        game, {mount_id: ZoneRef.equipment("p2", "defense_horse")}
    )
    action = _action(game, "use_duel", card_key=DUEL)
    assert action is not None and action.target_ids == ("p2",)
    spec = game.formal_registry.adapter_for(DUEL).rule_spec()
    assert spec["distance_rule"] == "not_applicable"


def test_huogong_target_must_have_hand_and_may_be_self() -> None:
    game = ProductionBasicCardBatch(seed=14)
    assert _action(game, "use_fire_attack", card_key=HUO, target="p1") is not None
    assert _action(game, "use_fire_attack", card_key=HUO, target="p2") is not None
    hand_ids = tuple(game.state.card_ids_in(ZoneRef.hand("p2")))
    _fixture_set_state(game, {instance_id: DISCARD_PILE for instance_id in hand_ids})
    assert _action(game, "use_fire_attack", card_key=HUO, target="p2") is None
    assert _action(game, "use_fire_attack", card_key=HUO, target="p1") is not None

# ---------------------------------------------------------------------
# C. 【决斗】使用、【无懈可击】与交替打出【杀】
# ---------------------------------------------------------------------


def test_duel_use_establishes_nullification_window_and_card_used() -> None:
    game = ProductionBasicCardBatch(seed=3)
    trick_id = _use_trick(game, "use_duel", DUEL, "p2")
    runtime = game.runtime
    assert runtime.pending_trick is not None
    assert runtime.pending_trick.trick_key == DUEL
    assert runtime.pending_trick.trick_instance_id == trick_id
    assert runtime.pending_trick.user_id == "p1"
    assert runtime.pending_trick.target_id == "p2"
    assert runtime.trick_direct_response_to == trick_id
    assert runtime.trick_response_order == ("p1", "p2")
    assert runtime.response_window_id is not None
    assert runtime.response_window_id.startswith("trick:")
    assert game.state.location_of(trick_id) == PROCESSING_ZONE
    used = [
        event
        for event in game.events
        if event.event_type is EventType.CARD_USED
        and event.card_instance_id == trick_id
    ]
    assert len(used) == 1
    assert used[0].payload.get("purpose") == "duel_alternating_slash"
    assert used[0].card_user == "p1"


def test_one_wuxie_cancels_duel_no_slash_chain() -> None:
    game = ProductionBasicCardBatch(seed=3)
    assert WUXIE in _hand_keys(game, "p2")
    trick_id = _use_trick(game, "use_duel", DUEL, "p2")
    _pass_trick(game)
    _step(game, _action(game, "use_wuxie"))
    _pass_trick(game)
    _pass_trick(game)
    assert game.phase is ProductionPhase.PLAY
    assert game.runtime.pending_duel is None
    assert not [e for e in game.events if e.event_type is EventType.CARD_PLAYED]
    assert not [e for e in game.events if e.event_type is EventType.DAMAGE]
    cancelled = [
        event
        for event in game.events
        if event.event_type is EventType.CARD_EFFECT_CANCELLED
        and event.card_instance_id == trick_id
    ]
    assert len(cancelled) == 1
    assert game.state.location_of(trick_id) == DISCARD_PILE


def test_two_wuxie_restore_duel_opens_slash_chain() -> None:
    game = ProductionBasicCardBatch(seed=6)
    assert WUXIE in _hand_keys(game, "p1")
    assert WUXIE in _hand_keys(game, "p2")
    trick_id = _use_trick(game, "use_duel", DUEL, "p2")
    first = _action(game, "use_wuxie")
    assert first is not None and first.actor_id == "p1"
    _step(game, first)
    second = _action(game, "use_wuxie")
    assert second is not None and second.actor_id == "p2"
    _step(game, second)
    _pass_trick(game)
    _pass_trick(game)
    assert game.phase is ProductionPhase.DUEL_RESPONSE
    assert game.runtime.pending_duel is not None
    assert game.runtime.pending_duel.trick_instance_id == trick_id
    used_wuxie = [
        e
        for e in game.events
        if e.event_type is EventType.CARD_USED and e.card_key == WUXIE
    ]
    assert len(used_wuxie) == 2
    assert used_wuxie[0].payload.get("response_to") == trick_id
    assert used_wuxie[1].payload.get("response_to") == used_wuxie[0].card_instance_id
    for event in used_wuxie:
        assert event.payload.get("root_trick_instance_id") == trick_id


def test_duel_target_is_first_responder() -> None:
    game = ProductionBasicCardBatch(seed=137)
    trick_id = _use_trick(game, "use_duel", DUEL, "p2")
    _close_trick_window(game)
    duel = game.runtime.pending_duel
    assert duel is not None
    assert duel.trick_instance_id == trick_id
    assert duel.responder_id == "p2"
    assert duel.opponent_id == "p1"
    assert duel.user_id == "p1"
    assert duel.target_id == "p2"
    assert duel.round_index == 0
    assert duel.response_index == 0
    assert duel.slash_sequence == ()


def test_duel_slash_recorded_as_played_not_used() -> None:
    game = ProductionBasicCardBatch(seed=10)
    trick_id = _use_trick(game, "use_duel", DUEL, "p2")
    _close_trick_window(game)
    slash = _action(game, "play_slash_for_duel", card_key="sgs_basic_sha")
    assert slash is not None and slash.actor_id == "p2"
    assert slash.action_type is ActionType.PLAY_CARD
    slash_id = slash.card_instance_id
    assert slash_id is not None
    _step(game, slash)
    played = [
        event
        for event in game.events
        if event.event_type is EventType.CARD_PLAYED
        and event.card_instance_id == slash_id
    ]
    assert len(played) == 1
    payload = played[0].payload
    assert payload.get("response_to") == trick_id
    assert payload.get("root_trick_instance_id") == trick_id
    assert payload.get("response_action") == "play"
    assert payload.get("purpose") == "duel_slash_response"
    assert payload.get("creates_card_used_event") is False
    assert payload.get("creates_card_played_event") is True
    assert payload.get("counts_for_use_or_play_total") is True
    assert payload.get("physical_or_virtual") == "physical"
    assert payload.get("response_provider") == "p2"
    assert payload.get("next_responder") == "p1"
    assert played[0].card_user == "p2"
    assert not [
        event
        for event in game.events
        if event.event_type is EventType.CARD_USED
        and event.card_instance_id == slash_id
    ]


def test_huosha_and_leisha_respond_by_current_card_name() -> None:
    for seed, first_slash, second_slash in (
        (10, "sgs_basic_sha", "sgs_basic_huosha"),
        (377, "sgs_basic_leisha", "sgs_basic_sha"),
    ):
        game = ProductionBasicCardBatch(seed=seed)
        _use_trick(game, "use_duel", DUEL, "p2")
        _close_trick_window(game)
        first = _action(game, "play_slash_for_duel", card_key=first_slash)
        assert first is not None
        _step(game, first)
        second = _action(game, "play_slash_for_duel", card_key=second_slash)
        assert second is not None
        _step(game, second)
        _step(game, _action(game, "pass_duel_slash"))
        assert game.phase is ProductionPhase.PLAY
        played_keys = {
            event.card_key
            for event in game.events
            if event.event_type is EventType.CARD_PLAYED
        }
        assert {first_slash, second_slash} <= played_keys


def test_non_slash_card_not_enumerated_for_duel_response() -> None:
    game = ProductionBasicCardBatch(seed=3)
    _use_trick(game, "use_duel", DUEL, "p2")
    _close_trick_window(game)
    assert WUXIE in _hand_keys(game, "p2")
    slash_actions = [
        action
        for action in game.legal_actions()
        if action.payload.get("operation") == "play_slash_for_duel"
    ]
    assert slash_actions
    for action in slash_actions:
        assert action.card_instance_id is not None
        assert (
            game.state.cards_by_id[action.card_instance_id].card_key
            in SLASH_CARD_KEYS
        )


def test_duel_slash_completes_hand_processing_discard_lifecycle() -> None:
    game = ProductionBasicCardBatch(seed=10)
    _use_trick(game, "use_duel", DUEL, "p2")
    _close_trick_window(game)
    slash = _action(game, "play_slash_for_duel", card_key="sgs_basic_sha")
    slash_id = slash.card_instance_id
    assert slash_id is not None
    _step(game, slash)
    assert game.state.location_of(slash_id) == DISCARD_PILE
    moves = [
        event
        for event in game.events
        if event.event_type is EventType.CARD_MOVED
        and event.card_instance_id == slash_id
    ]
    reasons = [event.payload.get("reason") for event in moves]
    assert "duel_slash_response:enter_processing" in reasons
    assert "duel_slash_response:leave_processing" in reasons
    enter = next(
        event
        for event in moves
        if event.payload.get("reason") == "duel_slash_response:enter_processing"
    )
    assert enter.payload["source"]["kind"] == "hand"
    assert enter.payload["source"]["owner_id"] == "p2"
    assert enter.payload["destination"]["kind"] == "processing"
    leave = next(
        event
        for event in moves
        if event.payload.get("reason") == "duel_slash_response:leave_processing"
    )
    assert leave.payload["destination"]["kind"] == "discard_pile"


def test_duel_responder_with_slash_may_pass() -> None:
    game = ProductionBasicCardBatch(seed=10)
    _use_trick(game, "use_duel", DUEL, "p2")
    _close_trick_window(game)
    assert _action(game, "play_slash_for_duel", card_key="sgs_basic_sha") is not None
    assert _action(game, "pass_duel_slash") is not None
    _step(game, _action(game, "pass_duel_slash"))
    assert game.phase is ProductionPhase.PLAY
    damage = [
        event for event in game.events if event.event_type is EventType.DAMAGE
    ]
    assert len(damage) == 1
    assert damage[0].target_id == "p2"
    assert damage[0].damage_source == "p1"

def _set_player_stats(
    game: ProductionBasicCardBatch,
    player_id: str,
    *,
    hp: int | None = None,
    max_hp: int | None = None,
) -> None:
    """测试夹具：用不可变GameState事务调整体力，不绕过后续事件与校验。"""
    players = []
    for player in game.state.players:
        if player.player_id != player_id:
            players.append(player)
            continue
        players.append(
            replace(
                player,
                hp=player.hp if hp is None else hp,
                max_hp=player.max_hp if max_hp is None else max_hp,
            )
        )
    game._state = replace(
        game.state, players=tuple(players), revision=game.state.revision + 1
    )


def _consume_duel(
    game: ProductionBasicCardBatch,
    plays: tuple[str, ...],
    passer: str,
) -> list[str]:
    """按给定卡牌键顺序打出【杀】，最后由 passer 放弃响应；返回打出序列。"""
    played_ids: list[str] = []
    for card_key in plays:
        action = _action(game, "play_slash_for_duel", card_key=card_key)
        assert action is not None, f"当前响应者必须能打出{card_key}"
        assert action.card_instance_id is not None
        played_ids.append(action.card_instance_id)
        _step(game, action)
    pass_action = _action(game, "pass_duel_slash")
    assert pass_action is not None and pass_action.actor_id == passer
    _step(game, pass_action)
    return played_ids


# ---------------------------------------------------------------------
# D. 【决斗】效果：打出生命周期、伤害来源、救援与死亡边界
# ---------------------------------------------------------------------


def test_duel_slash_physical_lifecycle_hand_processing_discard() -> None:
    game = ProductionBasicCardBatch(seed=10)
    _use_trick(game, "use_duel", DUEL, "p2")
    _close_trick_window(game)
    slash = _action(game, "play_slash_for_duel", card_key="sgs_basic_sha")
    assert slash is not None and slash.card_instance_id is not None
    slash_id = slash.card_instance_id
    assert game.state.location_of(slash_id) == ZoneRef.hand("p2")
    _step(game, slash)
    assert game.state.location_of(slash_id) == DISCARD_PILE
    moved = [
        event
        for event in game.events
        if event.event_type is EventType.CARD_MOVED
        and event.card_instance_id == slash_id
    ]
    assert [event.payload.get("reason") for event in moved] == [
        "duel_slash_response:enter_processing",
        "duel_slash_response:leave_processing",
    ]
    assert moved[0].payload["source"]["kind"] == "hand"
    assert moved[1].payload["destination"]["kind"] == "discard_pile"


def test_duel_pass_allowed_even_with_slash_in_hand() -> None:
    game = ProductionBasicCardBatch(seed=10)
    _use_trick(game, "use_duel", DUEL, "p2")
    _close_trick_window(game)
    assert _action(game, "play_slash_for_duel", card_key="sgs_basic_sha") is not None
    pass_action = _action(game, "pass_duel_slash")
    assert pass_action is not None
    _step(game, pass_action)
    damage = [event for event in game.events if event.event_type is EventType.DAMAGE]
    assert len(damage) == 1
    assert damage[0].target_id == "p2" and damage[0].damage_source == "p1"
    assert game.phase is ProductionPhase.PLAY


def test_duel_target_passes_damage_source_is_user() -> None:
    game = ProductionBasicCardBatch(seed=137)
    trick_id = _use_trick(game, "use_duel", DUEL, "p2")
    _close_trick_window(game)
    _step(game, _action(game, "pass_duel_slash"))
    damage = [event for event in game.events if event.event_type is EventType.DAMAGE]
    assert len(damage) == 1
    event = damage[0]
    assert event.target_id == "p2"
    assert event.damage_source == "p1"
    assert event.amount == 1
    assert event.damage_type == "无属性"
    assert event.card_instance_id == trick_id
    assert event.card_key == DUEL
    assert game.state.location_of(trick_id) == DISCARD_PILE


def test_duel_user_passes_second_round_damage_source_is_target() -> None:
    game = ProductionBasicCardBatch(seed=107)
    trick_id = _use_trick(game, "use_duel", DUEL, "p2")
    _close_trick_window(game)
    _step(game, _action(game, "play_slash_for_duel"))
    _step(game, _action(game, "pass_duel_slash"))
    damage = [event for event in game.events if event.event_type is EventType.DAMAGE]
    assert len(damage) == 1
    event = damage[0]
    assert event.target_id == "p1"
    assert event.damage_source == "p2"
    assert event.amount == 1
    assert event.damage_type == "无属性"
    assert event.card_instance_id == trick_id


def test_duel_three_slash_alternation_exact_order() -> None:
    game = ProductionBasicCardBatch(seed=399)
    _use_trick(game, "use_duel", DUEL, "p2")
    _close_trick_window(game)
    responders: list[str] = []
    played_ids: list[str] = []
    for _ in range(3):
        duel = game.runtime.pending_duel
        assert duel is not None
        responders.append(duel.responder_id)
        action = _action(game, "play_slash_for_duel")
        assert action is not None and action.card_instance_id is not None
        played_ids.append(action.card_instance_id)
        _step(game, action)
    assert responders == ["p2", "p1", "p2"]
    duel = game.runtime.pending_duel
    assert duel is not None
    assert duel.slash_sequence == tuple(played_ids)
    assert duel.response_index == 3 and duel.round_index == 1
    _step(game, _action(game, "pass_duel_slash"))
    played_events = [
        event
        for event in game.events
        if event.event_type is EventType.CARD_PLAYED
    ]
    assert [event.card_instance_id for event in played_events] == played_ids
    damage = [event for event in game.events if event.event_type is EventType.DAMAGE]
    assert len(damage) == 1
    assert damage[0].target_id == "p1" and damage[0].damage_source == "p2"


def test_duel_dead_responder_ends_immediately_without_damage() -> None:
    game = ProductionBasicCardBatch(seed=323)
    _use_trick(game, "use_duel", DUEL, "p2")
    _close_trick_window(game)
    assert game.runtime.pending_duel.responder_id == "p2"
    _step(game, _action(game, "play_slash_for_duel"))
    assert game.runtime.pending_duel.responder_id == "p1"
    _kill_player(game, "p2")
    _step(game, _action(game, "play_slash_for_duel"))
    assert game.phase is ProductionPhase.PLAY
    assert not [event for event in game.events if event.event_type is EventType.DAMAGE]
    finish = [
        event
        for event in game.events
        if event.event_type is EventType.CARD_MOVED
        and event.payload.get("reason") == "duel_resolved_responder_dead"
    ]
    assert len(finish) == 1
    assert finish[0].payload.get("dead_responder") == "p2"


def test_duel_damage_enters_peach_rescue() -> None:
    game = ProductionBasicCardBatch(seed=137)
    _set_player_stats(game, "p2", hp=1, max_hp=1)
    trick_id = _use_trick(game, "use_duel", DUEL, "p2")
    _close_trick_window(game)
    _step(game, _action(game, "pass_duel_slash"))
    assert game.phase is ProductionPhase.DYING_RESCUE
    assert game.runtime.pending_dying_id == "p2"
    _step(game, _action(game, "pass_rescue"))
    peach = _action(game, "rescue_with_peach")
    assert peach is not None and peach.actor_id == "p2"
    _step(game, peach)
    assert game.phase is ProductionPhase.PLAY
    assert game.state.players_by_id["p2"].hp == 1
    assert game.state.players_by_id["p2"].alive is True
    assert game.state.location_of(trick_id) == DISCARD_PILE


def test_duel_damage_enters_wine_self_rescue() -> None:
    game = ProductionBasicCardBatch(seed=377)
    _set_player_stats(game, "p2", hp=1, max_hp=1)
    _use_trick(game, "use_duel", DUEL, "p2")
    _close_trick_window(game)
    _consume_duel(game, ("sgs_basic_leisha", "sgs_basic_sha"), passer="p2")
    assert game.phase is ProductionPhase.DYING_RESCUE
    _step(game, _action(game, "pass_rescue"))
    wine = _action(game, "rescue_with_wine")
    assert wine is not None and wine.actor_id == "p2"
    _step(game, wine)
    assert game.phase is ProductionPhase.PLAY
    assert game.state.players_by_id["p2"].hp == 1


def test_duel_rescue_failure_confirms_death_and_victory() -> None:
    game = ProductionBasicCardBatch(seed=3)
    _set_player_stats(game, "p2", hp=1, max_hp=1)
    trick_id = _use_trick(game, "use_duel", DUEL, "p2")
    _pass_trick(game)
    _pass_trick(game)
    assert game.phase is ProductionPhase.DUEL_RESPONSE
    _step(game, _action(game, "pass_duel_slash"))
    assert game.phase is ProductionPhase.DYING_RESCUE
    _step(game, _action(game, "pass_rescue"))
    _step(game, _action(game, "pass_rescue"))
    assert game.is_finished
    assert game.winner_id == "p1"
    assert not game.state.players_by_id["p2"].alive
    deaths = [event for event in game.events if event.event_type is EventType.DEATH]
    assert len(deaths) == 1 and deaths[0].target_ids == ("p2",)
    victories = [
        event for event in game.events if event.event_type is EventType.VICTORY
    ]
    assert len(victories) == 1 and victories[0].target_ids == ("p1",)
    assert game.state.location_of(trick_id) == DISCARD_PILE

# ---------------------------------------------------------------------
# E. 【火攻】无懈、展示、同花色弃置与火焰伤害
# ---------------------------------------------------------------------


def test_fire_attack_one_wuxie_cancels_no_reveal_window() -> None:
    game = ProductionBasicCardBatch(seed=14)
    assert WUXIE in _hand_keys(game, "p2")
    trick_id = _use_trick(game, "use_fire_attack", HUO, "p2")
    _pass_trick(game)
    _step(game, _action(game, "use_wuxie"))
    _pass_trick(game)
    _pass_trick(game)
    assert game.phase is ProductionPhase.PLAY
    assert game.runtime.pending_fire_attack is None
    assert not [event for event in game.events if event.event_type is EventType.CARD_REVEALED]
    assert not [event for event in game.events if event.event_type is EventType.DAMAGE]
    cancelled = [
        event
        for event in game.events
        if event.event_type is EventType.CARD_EFFECT_CANCELLED
        and event.card_instance_id == trick_id
    ]
    assert len(cancelled) == 1
    assert game.state.location_of(trick_id) == DISCARD_PILE


def test_fire_attack_two_wuxie_restore_enters_reveal() -> None:
    game = ProductionBasicCardBatch(seed=968)
    assert _hand_keys(game, "p2").count(WUXIE) == 2
    trick_id = _use_trick(game, "use_fire_attack", HUO, "p2")
    _pass_trick(game)
    first = _action(game, "use_wuxie")
    assert first is not None and first.actor_id == "p2"
    _step(game, first)
    _pass_trick(game)
    second = _action(game, "use_wuxie")
    assert second is not None and second.actor_id == "p2"
    _step(game, second)
    _pass_trick(game)
    _pass_trick(game)
    assert game.phase is ProductionPhase.FIRE_ATTACK_REVEAL
    fire = game.runtime.pending_fire_attack
    assert fire is not None and fire.trick_instance_id == trick_id
    assert fire.user_id == "p1" and fire.target_id == "p2"
    used_wuxie = [
        event
        for event in game.events
        if event.event_type is EventType.CARD_USED and event.card_key == WUXIE
    ]
    assert len(used_wuxie) == 2
    assert used_wuxie[0].payload.get("response_to") == trick_id
    assert used_wuxie[1].payload.get("response_to") == used_wuxie[0].card_instance_id


def test_fire_attack_target_not_user_chooses_reveal() -> None:
    game = ProductionBasicCardBatch(seed=283)
    trick_id = _use_trick(game, "use_fire_attack", HUO, "p2")
    _close_trick_window(game)
    assert game.phase is ProductionPhase.FIRE_ATTACK_REVEAL
    assert game.current_actor_id == "p2"
    reveals = [
        action
        for action in game.legal_actions()
        if action.payload.get("operation") == "reveal_card_for_fire_attack"
    ]
    assert reveals
    assert all(action.actor_id == "p2" for action in reveals)
    adapter = game.formal_registry.adapter_for(HUO)
    context = replace(game._context(), actor_id="p1")
    assert adapter.enumerate_legal_actions(game.state, context) == ()
    _step(game, reveals[0])
    assert game.phase is ProductionPhase.FIRE_ATTACK_DISCARD
    assert game.runtime.pending_fire_attack.trick_instance_id == trick_id


def test_fire_attack_revealed_card_stays_in_target_hand() -> None:
    game = ProductionBasicCardBatch(seed=283)
    _use_trick(game, "use_fire_attack", HUO, "p2")
    _close_trick_window(game)
    reveal = _action(game, "reveal_card_for_fire_attack")
    assert reveal is not None
    handle = reveal.payload["handle"]
    instance_id = game.runtime.fire_attack_reveal_handles[handle]
    assert game.state.location_of(instance_id) == ZoneRef.hand("p2")
    _step(game, reveal)
    assert game.state.location_of(instance_id) == ZoneRef.hand("p2")
    assert game.runtime.pending_fire_attack.revealed_instance_id == instance_id


def test_fire_attack_reveal_event_publicizes_card() -> None:
    game = ProductionBasicCardBatch(seed=283)
    trick_id = _use_trick(game, "use_fire_attack", HUO, "p2")
    _close_trick_window(game)
    reveal = _action(game, "reveal_card_for_fire_attack")
    assert reveal is not None
    handle = reveal.payload["handle"]
    instance_id = game.runtime.fire_attack_reveal_handles[handle]
    card = game.state.cards_by_id[instance_id]
    _step(game, reveal)
    revealed_events = [
        event
        for event in game.events
        if event.event_type is EventType.CARD_REVEALED
    ]
    assert len(revealed_events) == 1
    event = revealed_events[0]
    assert event.card_instance_id == instance_id
    assert event.card_key == card.card_key
    assert event.payload["card_name"] == card.card_name
    assert event.payload["suit"] == card.suit
    assert event.payload["rank"] == card.rank
    assert event.payload["reason"] == "fire_attack_reveal"
    assert event.payload["revealed_by"] == "p2"
    assert event.payload["trick_instance_id"] == trick_id


def test_fire_attack_unrevealed_hand_never_leaks_to_decision_input() -> None:
    game = ProductionBasicCardBatch(seed=283)
    _use_trick(game, "use_fire_attack", HUO, "p2")
    _close_trick_window(game)
    target_hand_ids = set(game.state.card_ids_in(ZoneRef.hand("p2")))
    target_hand_cards = {
        instance_id: game.state.cards_by_id[instance_id]
        for instance_id in target_hand_ids
    }
    reveals = [
        action
        for action in game.legal_actions()
        if action.payload.get("operation") == "reveal_card_for_fire_attack"
    ]
    assert len(reveals) == len(target_hand_ids) >= 2
    payload_sets = {frozenset(action.payload.keys()) for action in reveals}
    assert payload_sets == {frozenset(_REVEAL_PAYLOAD_KEYS)}
    for action in reveals:
        assert action.card_instance_id is None
        assert "card_key" not in action.payload
        blob = str(dict(action.payload))
        for instance_id, card in target_hand_cards.items():
            # 实体ID、卡牌键与中文牌名都是多字符标识，可以直接断言不出现；
            # 花色与点数由上面的键集合等价断言保证不进入任何负载字段。
            assert instance_id not in blob
            assert card.card_key not in blob
            assert card.card_name not in blob
        assert "state_hash" in action.payload and "window_id" in action.payload


def test_fire_attack_user_only_discards_same_suit_real_hand_cards() -> None:
    game = ProductionBasicCardBatch(seed=283)
    _use_trick(game, "use_fire_attack", HUO, "p2")
    _close_trick_window(game)
    reveal = _action(game, "reveal_card_for_fire_attack")
    assert reveal is not None
    _step(game, reveal)
    revealed_suit = game.runtime.pending_fire_attack.revealed_suit
    discards = [
        action
        for action in game.legal_actions()
        if action.payload.get("operation") == "discard_same_suit_for_fire_attack"
    ]
    assert discards
    for action in discards:
        assert action.actor_id == "p1"
        card = game.state.cards_by_id[action.card_instance_id]
        assert card.suit == revealed_suit
        assert game.state.location_of(action.card_instance_id) == ZoneRef.hand("p1")
        assert action.payload["revealed_suit"] == revealed_suit
        assert action.payload["card_key"] == card.card_key


def test_fire_attack_pass_discard_allowed_even_with_same_suit() -> None:
    game = ProductionBasicCardBatch(seed=283)
    trick_id = _use_trick(game, "use_fire_attack", HUO, "p2")
    _close_trick_window(game)
    _step(game, _action(game, "reveal_card_for_fire_attack"))
    assert _action(game, "discard_same_suit_for_fire_attack") is not None
    pass_action = _action(game, "pass_fire_attack_discard")
    assert pass_action is not None and pass_action.actor_id == "p1"
    _step(game, pass_action)
    assert game.phase is ProductionPhase.PLAY
    assert not [event for event in game.events if event.event_type is EventType.DAMAGE]
    finish = [
        event
        for event in game.events
        if event.event_type is EventType.CARD_MOVED
        and event.payload.get("reason") == "fire_attack_effect_resolved_no_discard"
    ]
    assert len(finish) == 1
    assert finish[0].card_instance_id == trick_id
    assert game.state.location_of(trick_id) == DISCARD_PILE


def test_fire_attack_no_same_suit_cannot_forge_discard() -> None:
    game = ProductionBasicCardBatch(seed=283)
    _use_trick(game, "use_fire_attack", HUO, "p2")
    _close_trick_window(game)
    reveal = _action(game, "reveal_card_for_fire_attack")
    assert reveal is not None
    _step(game, reveal)
    revealed_suit = game.runtime.pending_fire_attack.revealed_suit
    matching = [
        instance_id
        for instance_id in game.state.card_ids_in(ZoneRef.hand("p1"))
        if game.state.cards_by_id[instance_id].suit == revealed_suit
    ]
    _fixture_set_state(
        game, {instance_id: DISCARD_PILE for instance_id in matching}
    )
    assert not [
        action
        for action in game.legal_actions()
        if action.payload.get("operation") == "discard_same_suit_for_fire_attack"
    ]
    context = game._context()
    adapter = game.formal_registry.adapter_for(HUO)
    other_suit_card = next(
        instance_id
        for instance_id in game.state.card_ids_in(ZoneRef.hand("p1"))
        if game.state.cards_by_id[instance_id].suit != revealed_suit
    )
    fire = game.runtime.pending_fire_attack
    forged = replace(
        LegalAction(
            action_type=ActionType.MOVE_CARD,
            actor_id="p1",
            card_instance_id=other_suit_card,
            target_ids=("p2",),
            payload={
                "operation": "discard_same_suit_for_fire_attack",
                "card_key": game.state.cards_by_id[other_suit_card].card_key,
                "trick_instance_id": fire.trick_instance_id,
                "root_trick_instance_id": fire.trick_instance_id,
                "user_id": "p1",
                "target_id": "p2",
                "revealed_instance_id": fire.revealed_instance_id,
                "revealed_suit": fire.revealed_suit,
            },
        ),
        action_id="act_forged_discard",
    )
    with pytest.raises(InvalidActionError):
        adapter.apply_action(game.state, context, forged)
    not_in_hand = next(
        instance_id
        for instance_id in game.state.cards_by_id
        if game.state.location_of(instance_id) != ZoneRef.hand("p1")
        and game.state.cards_by_id[instance_id].suit == revealed_suit
    )
    forged_off_zone = replace(forged, card_instance_id=not_in_hand)
    with pytest.raises(InvalidActionError):
        adapter.apply_action(game.state, context, forged_off_zone)
    forged_trick = replace(forged, card_instance_id=fire.trick_instance_id)
    with pytest.raises(InvalidActionError):
        adapter.apply_action(game.state, context, forged_trick)

# ---------------------------------------------------------------------
# F. 【火攻】伤害、隐藏信息、回放与失败关闭
# ---------------------------------------------------------------------

def _reveal_action_for_suit(
    game: ProductionBasicCardBatch, exclude: tuple[str, ...] = ()
) -> object | None:
    """按展示句柄映射到具体实体后，显式选择非排除花色的展示动作。

    展示句柄随会话密钥随机化，合法动作排序不跨会话稳定；测试必须通过
    权威句柄快照按实体选定动作，而不是依赖“第一个动作”。
    """
    for action in game.legal_actions():
        if action.payload.get("operation") != "reveal_card_for_fire_attack":
            continue
        handle = action.payload.get("handle")
        instance_id = game.runtime.fire_attack_reveal_handles.get(handle)
        if instance_id is None:
            continue
        if game.state.cards_by_id[instance_id].suit in exclude:
            continue
        return action
    return None




def test_fire_attack_discard_emits_moved_lost_discarded() -> None:
    game = ProductionBasicCardBatch(seed=283)
    trick_id = _use_trick(game, "use_fire_attack", HUO, "p2")
    _close_trick_window(game)
    reveal = _action(game, "reveal_card_for_fire_attack")
    assert reveal is not None
    _step(game, reveal)
    discard = _action(game, "discard_same_suit_for_fire_attack")
    assert discard is not None and discard.card_instance_id is not None
    discarded_id = discard.card_instance_id
    revealed_suit = game.runtime.pending_fire_attack.revealed_suit
    assert revealed_suit is not None
    _step(game, discard)
    assert game.state.location_of(discarded_id) == DISCARD_PILE
    moved = [
        event
        for event in game.events
        if event.event_type is EventType.CARD_MOVED
        and event.card_instance_id == discarded_id
        and event.payload.get("reason") == "fire_attack_discard_same_suit"
    ]
    assert len(moved) == 1
    assert moved[0].payload["source"]["kind"] == "hand"
    assert moved[0].payload["destination"]["kind"] == "discard_pile"
    lost = [
        event
        for event in game.events
        if event.event_type is EventType.CARD_LOST
        and event.card_instance_id == discarded_id
    ]
    assert len(lost) == 1
    assert lost[0].payload["reason"] == "fire_attack_discard_same_suit"
    discarded_events = [
        event
        for event in game.events
        if event.event_type is EventType.CARD_DISCARDED
        and event.card_instance_id == discarded_id
    ]
    assert len(discarded_events) == 1
    assert discarded_events[0].card_user == "p1"
    assert discarded_events[0].payload["trick_instance_id"] == trick_id
    assert discarded_events[0].payload["revealed_suit"] == revealed_suit
    assert game.state.location_of(trick_id) == DISCARD_PILE


def test_fire_attack_discard_not_used_or_played() -> None:
    game = ProductionBasicCardBatch(seed=283)
    _use_trick(game, "use_fire_attack", HUO, "p2")
    _close_trick_window(game)
    _step(game, _action(game, "reveal_card_for_fire_attack"))
    discard = _action(game, "discard_same_suit_for_fire_attack")
    assert discard is not None and discard.card_instance_id is not None
    discarded_id = discard.card_instance_id
    _step(game, discard)
    assert not [
        event
        for event in game.events
        if event.event_type is EventType.CARD_USED
        and event.card_instance_id == discarded_id
    ]
    assert not [
        event
        for event in game.events
        if event.event_type is EventType.CARD_PLAYED
        and event.card_instance_id == discarded_id
    ]


def test_fire_attack_successful_discard_deals_one_fire_damage() -> None:
    game = ProductionBasicCardBatch(seed=283)
    trick_id = _use_trick(game, "use_fire_attack", HUO, "p2")
    _close_trick_window(game)
    _step(game, _action(game, "reveal_card_for_fire_attack"))
    _step(game, _action(game, "discard_same_suit_for_fire_attack"))
    damage = [event for event in game.events if event.event_type is EventType.DAMAGE]
    assert len(damage) == 1
    event = damage[0]
    assert event.target_id == "p2"
    assert event.damage_source == "p1"
    assert event.amount == 1
    assert event.damage_type == "火属性"
    assert event.card_instance_id == trick_id
    assert event.card_key == HUO
    assert event.kill_credit == "p1"
    assert game.phase is ProductionPhase.PLAY
    assert game.state.location_of(trick_id) == DISCARD_PILE


def test_fire_attack_target_hand_emptied_resolution_no_effect() -> None:
    game = ProductionBasicCardBatch(seed=14)
    trick_id = _use_trick(game, "use_fire_attack", HUO, "p2")
    _pass_trick(game)
    hand_ids = tuple(game.state.card_ids_in(ZoneRef.hand("p2")))
    _fixture_set_state(game, {instance_id: DISCARD_PILE for instance_id in hand_ids})
    _pass_trick(game)
    assert game.phase is ProductionPhase.PLAY
    assert game.runtime.pending_fire_attack is None
    assert not [event for event in game.events if event.event_type is EventType.DAMAGE]
    finish = [
        event
        for event in game.events
        if event.event_type is EventType.CARD_MOVED
        and event.payload.get("reason")
        == "fire_attack_effect_resolved_no_legal_reveal_card"
    ]
    assert len(finish) == 1
    assert finish[0].card_instance_id == trick_id


def test_fire_attack_self_target_reveal_and_discard() -> None:
    game = ProductionBasicCardBatch(seed=14)
    trick_id = _use_trick(game, "use_fire_attack", HUO, "p1")
    _close_trick_window(game)
    assert game.phase is ProductionPhase.FIRE_ATTACK_REVEAL
    assert game.current_actor_id == "p1"
    reveal = _action(game, "reveal_card_for_fire_attack")
    assert reveal is not None and reveal.actor_id == "p1"
    handle = reveal.payload["handle"]
    revealed_id = game.runtime.fire_attack_reveal_handles[handle]
    _step(game, reveal)
    assert game.state.location_of(revealed_id) == ZoneRef.hand("p1")
    assert game.phase is ProductionPhase.FIRE_ATTACK_DISCARD
    discards = [
        action
        for action in game.legal_actions()
        if action.payload.get("operation") == "discard_same_suit_for_fire_attack"
    ]
    # 卡牌效果.md【火攻】：展示牌不移动区域，使用者“弃置一张与展示牌
    # 花色相同的手牌”；自我火攻时被展示牌仍在自己手牌中，按当前手牌
    # 枚举同花色实体时自然包含它（模拟规范5.12的“不同实体牌”要求
    # 属于分析约定，不是卡牌效果）。
    assert any(
        action.card_instance_id == revealed_id for action in discards
    )
    _step(game, discards[0])
    damage = [event for event in game.events if event.event_type is EventType.DAMAGE]
    assert len(damage) == 1
    assert damage[0].target_id == "p1"
    assert damage[0].damage_source == "p1"
    assert damage[0].damage_type == "火属性"
    assert damage[0].card_instance_id == trick_id
    assert game.phase is ProductionPhase.PLAY


def test_fire_attack_damage_enters_dying_peach_rescue() -> None:
    game = ProductionBasicCardBatch(seed=382)
    _set_player_stats(game, "p2", hp=1, max_hp=1)
    _use_trick(game, "use_fire_attack", HUO, "p2")
    _close_trick_window(game)
    reveal = _reveal_action_for_suit(game, exclude=("♦",))
    assert reveal is not None
    _step(game, reveal)
    discard = _action(game, "discard_same_suit_for_fire_attack")
    assert discard is not None
    _step(game, discard)
    assert game.phase is ProductionPhase.DYING_RESCUE
    assert game.runtime.pending_dying_id == "p2"
    _step(game, _action(game, "pass_rescue"))
    peach = _action(game, "rescue_with_peach")
    assert peach is not None and peach.actor_id == "p2"
    _step(game, peach)
    assert game.phase is ProductionPhase.PLAY
    assert game.state.players_by_id["p2"].hp == 1
    assert game.state.players_by_id["p2"].alive is True


def test_fire_attack_reveal_handle_forged_or_stale_fails_closed() -> None:
    game = ProductionBasicCardBatch(seed=283)
    _use_trick(game, "use_fire_attack", HUO, "p2")
    _close_trick_window(game)
    reveal = _action(game, "reveal_card_for_fire_attack")
    assert reveal is not None
    context = game._context()
    adapter = game.formal_registry.adapter_for(HUO)
    forged = replace(
        reveal,
        action_id="act_forged_reveal",
        payload={**reveal.payload, "handle": "h_" + "0" * 32},
    )
    with pytest.raises(InvalidActionError):
        validate_action(game.state, context, forged, game.registry)
    with pytest.raises(InvalidActionError):
        adapter.apply_action(game.state, context, forged)
    handle = reveal.payload["handle"]
    instance_id = game.runtime.fire_attack_reveal_handles[handle]
    _fixture_set_state(game, {instance_id: DISCARD_PILE})
    with pytest.raises(InvalidActionError):
        adapter.apply_action(game.state, context, reveal)
    assert not [event for event in game.events if event.event_type is EventType.CARD_REVEALED]

# ---------------------------------------------------------------------
# G. 回放、玩家可见视图与通用失败关闭
# ---------------------------------------------------------------------


def test_duel_replay_reexecutes_and_tampering_fails_closed() -> None:
    record = record_reference_production_batch(
        seed=10,
        controller=ScriptedBatchController(
            [
                {"operation": "use_duel", "card_key": DUEL},
                {"operation": "pass_trick_response"},
                {"operation": "pass_trick_response"},
                {"operation": "play_slash_for_duel", "card_key": "sgs_basic_sha"},
                {"operation": "play_slash_for_duel", "card_key": "sgs_basic_huosha"},
                {"operation": "pass_duel_slash"},
            ]
        ),
    )
    result = reexecute_production_replay(record)
    assert result.verified is True
    played = [
        event
        for event in record.events
        if event.get("event_type") == "card_played"
        and event.get("payload", {}).get("purpose") == "duel_slash_response"
    ]
    assert len(played) == 2
    damages = [
        event for event in record.events if event.get("event_type") == "damage"
    ]
    assert damages, "决斗伤害必须出现在回放事件流中"
    first = damages[0]
    assert first["damage_type"] == "无属性"
    assert first["target_id"] == "p2"
    assert first["damage_source"] == "p1"
    assert first["card_key"] == DUEL
    assert not any(
        event.get("event_type") == "card_effect_cancelled"
        for event in record.events[: first["sequence"] - 1]
    )

    # 篡改伤害来源
    tampered = copy.deepcopy(record.to_dict())
    damage_event = next(
        event
        for event in tampered["events"]
        if event.get("event_type") == "damage"
    )
    damage_event["damage_source"] = "p2"
    del tampered["record_sha256"]
    with pytest.raises(ProductionReplayFormatError):
        ProductionReexecutionReplay.from_dict(tampered)

    # 篡改伤害属性
    tampered = copy.deepcopy(record.to_dict())
    damage_event = next(
        event
        for event in tampered["events"]
        if event.get("event_type") == "damage"
    )
    damage_event["damage_type"] = "火属性"
    del tampered["record_sha256"]
    with pytest.raises(ProductionReplayFormatError):
        ProductionReexecutionReplay.from_dict(tampered)

    # 删除一条打出【杀】事件
    tampered = copy.deepcopy(record.to_dict())
    tampered["events"] = [
        event
        for event in tampered["events"]
        if not (
            event.get("event_type") == "card_played"
            and event.get("payload", {}).get("purpose") == "duel_slash_response"
        )
    ]
    del tampered["record_sha256"]
    with pytest.raises(ProductionReplayFormatError):
        ProductionReexecutionReplay.from_dict(tampered)

    # 篡改响应轮次
    tampered = copy.deepcopy(record.to_dict())
    slash_decision = next(
        decision
        for decision in tampered["decisions"]
        if decision["chosen_action"].get("payload", {}).get("operation")
        == "play_slash_for_duel"
    )
    slash_decision["chosen_action"]["payload"]["duel_round"] = 99
    del tampered["record_sha256"]
    rebuilt = ProductionReexecutionReplay.from_dict(tampered)
    with pytest.raises(ProductionReplayDivergenceError):
        reexecute_production_replay(rebuilt)

    # 篡改当前响应者（打出【杀】的实体改为对方手牌实体）
    tampered = copy.deepcopy(record.to_dict())
    slash_decision = next(
        decision
        for decision in tampered["decisions"]
        if decision["chosen_action"].get("payload", {}).get("operation")
        == "play_slash_for_duel"
    )
    slash_decision["chosen_action"]["payload"]["duel_response_index"] = 7
    del tampered["record_sha256"]
    rebuilt = ProductionReexecutionReplay.from_dict(tampered)
    with pytest.raises(ProductionReplayDivergenceError):
        reexecute_production_replay(rebuilt)

def test_fire_attack_replay_reexecutes_and_tampering_fails_closed() -> None:
    record = record_reference_production_batch(
        seed=283,
        controller=ScriptedBatchController(
            [
                {"operation": "use_fire_attack", "card_key": HUO, "target": "p2"},
                {"operation": "pass_trick_response"},
                {"operation": "pass_trick_response"},
                {"operation": "reveal_card_for_fire_attack"},
                {"operation": "discard_same_suit_for_fire_attack"},
            ]
        ),
    )
    result = reexecute_production_replay(record)
    assert result.verified is True
    damages = [
        event for event in record.events if event.get("event_type") == "damage"
    ]
    assert damages, "【火攻】伤害必须出现在回放事件流中"
    first = damages[0]
    assert first["damage_type"] == "火属性"
    assert first["target_id"] == "p2"
    assert first["damage_source"] == "p1"
    assert first["card_key"] == HUO

    # 篡改展示牌（实体与花色）
    tampered = copy.deepcopy(record.to_dict())
    reveal_event = next(
        event
        for event in tampered["events"]
        if event.get("event_type") == "card_revealed"
    )
    reveal_event["card_instance_id"] = "sgs-mobile-forged"
    del tampered["record_sha256"]
    with pytest.raises(ProductionReplayFormatError):
        ProductionReexecutionReplay.from_dict(tampered)

    tampered = copy.deepcopy(record.to_dict())
    reveal_event = next(
        event
        for event in tampered["events"]
        if event.get("event_type") == "card_revealed"
    )
    reveal_event["payload"]["suit"] = "♠"
    del tampered["record_sha256"]
    with pytest.raises(ProductionReplayFormatError):
        ProductionReexecutionReplay.from_dict(tampered)

    # 篡改展示者
    tampered = copy.deepcopy(record.to_dict())
    reveal_event = next(
        event
        for event in tampered["events"]
        if event.get("event_type") == "card_revealed"
    )
    reveal_event["payload"]["revealed_by"] = "p1"
    del tampered["record_sha256"]
    with pytest.raises(ProductionReplayFormatError):
        ProductionReexecutionReplay.from_dict(tampered)

    # 伪造展示句柄
    tampered = copy.deepcopy(record.to_dict())
    reveal_decision = next(
        decision
        for decision in tampered["decisions"]
        if decision["chosen_action"].get("payload", {}).get("operation")
        == "reveal_card_for_fire_attack"
    )
    reveal_decision["chosen_action"]["payload"]["handle"] = "h_" + "0" * 32
    del tampered["record_sha256"]
    rebuilt = ProductionReexecutionReplay.from_dict(tampered)
    with pytest.raises(ProductionReplayDivergenceError):
        reexecute_production_replay(rebuilt)

    # 篡改弃置决策的展示花色，把不匹配花色伪造成合法弃置
    tampered = copy.deepcopy(record.to_dict())
    discard_decision = next(
        decision
        for decision in tampered["decisions"]
        if decision["chosen_action"].get("payload", {}).get("operation")
        == "discard_same_suit_for_fire_attack"
    )
    discard_decision["chosen_action"]["payload"]["revealed_suit"] = "♠"
    del tampered["record_sha256"]
    rebuilt = ProductionReexecutionReplay.from_dict(tampered)
    with pytest.raises(ProductionReplayDivergenceError):
        reexecute_production_replay(rebuilt)

    # 篡改弃置实体
    tampered = copy.deepcopy(record.to_dict())
    discard_decision = next(
        decision
        for decision in tampered["decisions"]
        if decision["chosen_action"].get("payload", {}).get("operation")
        == "discard_same_suit_for_fire_attack"
    )
    discard_decision["chosen_action"]["card_instance_id"] = "sgs-mobile-forged"
    del tampered["record_sha256"]
    rebuilt = ProductionReexecutionReplay.from_dict(tampered)
    with pytest.raises(ProductionReplayDivergenceError):
        reexecute_production_replay(rebuilt)

    # 删除或增加伤害事件
    tampered = copy.deepcopy(record.to_dict())
    tampered["events"] = [
        event
        for event in tampered["events"]
        if event.get("event_type") != "damage"
    ]
    del tampered["record_sha256"]
    with pytest.raises(ProductionReplayFormatError):
        ProductionReexecutionReplay.from_dict(tampered)

    tampered = copy.deepcopy(record.to_dict())
    damage_event = next(
        event
        for event in tampered["events"]
        if event.get("event_type") == "damage"
    )
    tampered["events"].append(copy.deepcopy(damage_event))
    del tampered["record_sha256"]
    with pytest.raises(ProductionReplayFormatError):
        ProductionReexecutionReplay.from_dict(tampered)


def test_fire_attack_player_visible_replay_only_publicizes_revealed() -> None:
    import json as _json

    record = record_reference_production_batch(
        seed=283,
        controller=ScriptedBatchController(
            [
                {"operation": "use_fire_attack", "card_key": HUO, "target": "p2"},
                {"operation": "pass_trick_response"},
                {"operation": "pass_trick_response"},
                {"operation": "reveal_card_for_fire_attack"},
                {"operation": "pass_fire_attack_discard"},
            ]
        ),
    )
    data = record.to_dict()
    decisions = data["decisions"]
    events = data["events"]
    reveal_index = next(
        index
        for index, decision in enumerate(decisions)
        if decision["chosen_action"].get("payload", {}).get("operation")
        == "reveal_card_for_fire_attack"
    )
    reveal_decision = decisions[reveal_index]
    reveal_legal = [
        legal
        for legal in reveal_decision["legal_actions"]
        if legal.get("payload", {}).get("operation")
        == "reveal_card_for_fire_attack"
    ]
    assert reveal_legal
    for legal in reveal_legal:
        assert set(legal.get("payload", {})) == _REVEAL_PAYLOAD_KEYS
        assert legal.get("card_instance_id") is None
        assert "card_key" not in legal.get("payload", {})
        assert "suit" not in legal.get("payload", {})
        assert "rank" not in legal.get("payload", {})
    reveal_events = [
        event
        for event in events
        if event.get("event_type") == "card_revealed"
    ]
    assert len(reveal_events) == 1
    revealed_id = reveal_events[0]["card_instance_id"]
    assert reveal_events[0]["payload"]["suit"] in ("♣", "♦")
    game = ProductionBasicCardBatch(seed=283)
    target_hand_ids = set(game.state.card_ids_in(ZoneRef.hand("p2")))
    assert revealed_id in target_hand_ids
    reveal_event_index = events.index(reveal_events[0])
    use_event_index = next(
        index
        for index, event in enumerate(events)
        if event.get("event_type") == "card_used"
        and event.get("card_key") == HUO
    )
    window_events = events[use_event_index + 1 : reveal_event_index]
    for instance_id in target_hand_ids:
        if instance_id == revealed_id:
            continue
        # 未展示手牌实体不得出现在展示决策输入中
        assert instance_id not in _json.dumps(
            decisions[: reveal_index + 1], ensure_ascii=False
        ), f"未展示手牌实体{instance_id}在展示决策输入中被泄露"
        # 未展示手牌实体不得出现在【火攻】使用到展示之间的任何事件中
        assert instance_id not in _json.dumps(
            window_events, ensure_ascii=False
        ), f"未展示手牌实体{instance_id}在展示前事件中被泄露"
        # 展示事件本身只能公开被展示实体
        assert instance_id not in _json.dumps(
            reveal_events[0], ensure_ascii=False
        )
    reveal_blob = _json.dumps(reveal_events[0], ensure_ascii=False)
    assert revealed_id in reveal_blob
    visible = record.player_visible_payload()
    visible_blob = _json.dumps(visible, ensure_ascii=False)
    assert "session_secret_hex" not in visible_blob
    assert "authoritative_private" not in visible_blob
    assert "fire_attack_reveal_handles" not in visible_blob
    assert visible["player_visible"] is True
    # 未展示手牌实体在整份玩家可见导出中只允许出现在公共发牌记录里，
    # 不得因【火攻】展示机制而进入任何其他事件或决策材料。
    for instance_id in target_hand_ids:
        if instance_id == revealed_id or instance_id not in visible_blob:
            continue
        initial_deal_occurrences = [
            event
            for event in events
            if event.get("card_instance_id") == instance_id
            and event.get("payload", {}).get("reason") == "initial_hand"
        ]
        assert initial_deal_occurrences, (
            f"未展示手牌实体{instance_id}在玩家可见导出中除公共发牌记录外被泄露"
        )

def test_duel_and_fire_actions_pass_enumerate_validate_apply() -> None:
    for seed, operation, card_key, target in (
        (10, "use_duel", DUEL, "p2"),
        (283, "use_fire_attack", HUO, "p2"),
    ):
        game = ProductionBasicCardBatch(seed=seed)
        action = _action(game, operation, card_key=card_key, target=target)
        assert action is not None
        context = game._context()
        validated = validate_action(game.state, context, action, game.registry)
        assert validated.action_id == action.action_id
        returned = game.step(BatchActionIdController(action.action_id))
        assert returned.action_id == action.action_id
        forged = replace(action, action_id="act_forged_use")
        with pytest.raises(InvalidActionError):
            validate_action(game.state, context, forged, game.registry)


def test_conservation_and_single_zone_after_each_new_branch() -> None:
    def check(game: ProductionBasicCardBatch) -> None:
        zone_total = sum(
            len(game.state.card_ids_in(zone)) for zone in game.state.zone_order
        )
        assert zone_total == len(game.state.cards) == 160
        game.state.assert_card_conservation()
        for card in game.state.cards:
            locations = [
                zone
                for zone in game.state.zone_order
                if card.instance_id in game.state.card_ids_in(zone)
            ]
            assert len(locations) == 1

    game = ProductionBasicCardBatch(seed=10)
    _use_trick(game, "use_duel", DUEL, "p2")
    _close_trick_window(game)
    _step(game, _action(game, "play_slash_for_duel"))
    _step(game, _action(game, "pass_duel_slash"))
    check(game)

    game = ProductionBasicCardBatch(seed=3)
    _use_trick(game, "use_duel", DUEL, "p2")
    _pass_trick(game)
    _step(game, _action(game, "use_wuxie"))
    _pass_trick(game)
    _pass_trick(game)
    check(game)

    game = ProductionBasicCardBatch(seed=283)
    _use_trick(game, "use_fire_attack", HUO, "p2")
    _close_trick_window(game)
    _step(game, _action(game, "reveal_card_for_fire_attack"))
    _step(game, _action(game, "discard_same_suit_for_fire_attack"))
    check(game)

    game = ProductionBasicCardBatch(seed=14)
    _use_trick(game, "use_fire_attack", HUO, "p2")
    _pass_trick(game)
    _step(game, _action(game, "use_wuxie"))
    _pass_trick(game)
    _pass_trick(game)
    check(game)


def test_finished_game_blocks_further_duel_and_fire_actions() -> None:
    game = ProductionBasicCardBatch(seed=3)
    _set_player_stats(game, "p2", hp=1, max_hp=1)
    _use_trick(game, "use_duel", DUEL, "p2")
    _pass_trick(game)
    _pass_trick(game)
    _step(game, _action(game, "pass_duel_slash"))
    _step(game, _action(game, "pass_rescue"))
    _step(game, _action(game, "pass_rescue"))
    assert game.is_finished
    assert game.winner_id == "p1"
    event_count = len(game.events)
    with pytest.raises(ProductionBatchFinishedError):
        game.legal_actions()
    with pytest.raises(ProductionBatchFinishedError):
        game.step()
    assert len(game.events) == event_count


def test_full_repo_source_audit_has_zero_defects() -> None:
    from scripts.sgs_source_integrity_audit import scan_python_sources

    report = scan_python_sources(REPO_ROOT)
    assert report.defect_count == 0
    assert report.scanned_files
    new_test = "tests/test_sgs_production_duel_fire_attack.py"
    assert new_test in report.scanned_files
