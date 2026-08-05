# -*- coding: utf-8 -*-
"""CP-04J：横置角色火／雷属性伤害传导生产基础设施。

全部正向用例走真实生产入口（enumerate→validate→apply），不使用 mock、
monkeypatch、skip 或 xfail。双人正式入口只能证明最多一名其他传导目标；
多人座次只以通用纯函数覆盖，不宣称三人以上生产入口 PROVEN。实际伤害
为0与伤害被防止的边界没有当前正式卡牌可在双人生产路径自然构造，因此
以纯决策函数覆盖该规则分支，不构造旁路夹具。
"""

from __future__ import annotations

import copy
from dataclasses import replace
import json
from pathlib import Path

import pytest

from scripts.sgs_engine.actions import (
    ActionType,
    InvalidActionError,
    LegalAction,
    UnsupportedRuleError,
    validate_action,
)
from scripts.sgs_engine.engine import canonical_state_snapshot
from scripts.sgs_engine.events import EventType
from scripts.sgs_engine.model import (
    DISCARD_PILE,
    DRAW_PILE,
    PROCESSING_ZONE,
    REVEALED_ZONE,
    GameState,
    PlayerState,
    ZoneRef,
)
from scripts.sgs_engine.production_batch import (
    BatchActionIdController,
    ProductionBasicCardBatch,
    ProductionBatchError,
    ProductionPhase,
    ScriptedBatchController,
    _ChainStepOutcome,
    _PendingChainDamage,
    _chain_dynamic_skip_reason,
    _chain_recipient_base,
    _chain_recipient_outcome,
    _chain_trigger_conditions,
    _ordered_chain_candidate_ids,
    _replace_player,
)
from scripts.sgs_engine.production_replay import (
    ProductionReexecutionReplay,
    ProductionReplayDivergenceError,
    ProductionReplayFormatError,
    record_reference_production_batch,
    reexecute_production_replay,
)
from scripts.sgs_engine.replay import sha256_value, state_sha256

WUGU = "sgs_trick_wugufengdeng"
TIESUO = "sgs_trick_tiesuolianhuan"


# ----------------------------------------------------------------------
# 基础夹具与助手（与既有生产测试同一模式）
# ----------------------------------------------------------------------


def _fresh(
    seed: int,
    *,
    player_hp: tuple[int, int] = (4, 4),
    initial_hand_count: int = 4,
) -> ProductionBasicCardBatch:
    game = ProductionBasicCardBatch(
        seed=seed,
        player_hp=player_hp,
        initial_hand_count=initial_hand_count,
    )
    for operation in ("proceed_prepare", "proceed_judgment", "proceed_draw"):
        action = next(
            a
            for a in game.legal_actions()
            if a.payload.get("operation") == operation
        )
        game.step(BatchActionIdController(action.action_id))
    assert game.phase.value == "play"
    return game

def _me(game: ProductionBasicCardBatch) -> str:
    return game._first_player_id


def _other(game: ProductionBasicCardBatch) -> str:
    return "p1" if _me(game) == "p2" else "p2"


def _move_to_hand(
    game: ProductionBasicCardBatch,
    instance_id: str,
    player_id: str,
) -> None:
    if game.state.location_of(instance_id) != ZoneRef.hand(player_id):
        game._state = game.state.move_card(instance_id, ZoneRef.hand(player_id))


def _stock_tricks(
    game: ProductionBasicCardBatch,
) -> tuple[list[str], list[str]]:
    player_id = _me(game)
    opponent_id = _other(game)
    wugu_ids: list[str] = []
    tiesuo_ids: list[str] = []
    wuxie_ids: list[str] = []
    for instance_id in game.state.card_ids_in(DRAW_PILE):
        key = game.state.cards_by_id[instance_id].card_key
        if key == WUGU:
            wugu_ids.append(instance_id)
        elif key == TIESUO:
            tiesuo_ids.append(instance_id)
        elif key == "sgs_trick_wuxiekeji":
            wuxie_ids.append(instance_id)
    for instance_id in wugu_ids + tiesuo_ids:
        _move_to_hand(game, instance_id, player_id)
    for index, instance_id in enumerate(wuxie_ids):
        target = player_id if index % 2 == 0 else opponent_id
        _move_to_hand(game, instance_id, target)
    return wugu_ids, tiesuo_ids


def _stock_card_key_to_hand(
    game: ProductionBasicCardBatch, card_key: str, player_id: str
) -> str:
    for instance_id in game.state.card_ids_in(DRAW_PILE):
        if game.state.cards_by_id[instance_id].card_key == card_key:
            _move_to_hand(game, instance_id, player_id)
            return instance_id
    raise AssertionError(f"牌堆中找不到{card_key}实体用于测试布置")


def _action(
    game: ProductionBasicCardBatch,
    operation: str,
    *,
    card_key: str | None = None,
    targets: tuple[str, ...] | None = None,
    actor: str | None = None,
) -> LegalAction | None:
    for action in game.legal_actions():
        payload = action.payload
        if payload.get("operation") != operation:
            continue
        if card_key is not None and payload.get("card_key") != card_key:
            continue
        if targets is not None and action.target_ids != targets:
            continue
        if actor is not None and action.actor_id != actor:
            continue
        return action
    return None


def _step(game: ProductionBasicCardBatch, action: LegalAction | None) -> None:
    assert action is not None and getattr(action, "action_id", None)
    game.step(BatchActionIdController(action.action_id))


def _close_trick_window(game: ProductionBasicCardBatch) -> None:
    _step(game, _action(game, "pass_trick_response"))
    _step(game, _action(game, "pass_trick_response"))


def _events_of(
    game: ProductionBasicCardBatch, event_type: EventType
) -> list[object]:
    return [
        event
        for event in game.events
        if event.event_type is event_type
    ]


def _events_with_type(
    events: list[dict[str, object]], event_type: str
) -> list[dict[str, object]]:
    return [
        event for event in events if event.get("event_type") == event_type
    ]


def _chain_both(game: ProductionBasicCardBatch) -> None:
    _step(
        game,
        _action(
            game, "use_tiesuo", card_key=TIESUO, targets=(_other(game),)
        ),
    )
    _close_trick_window(game)
    _step(
        game,
        _action(game, "use_tiesuo", card_key=TIESUO, targets=(_me(game),)),
    )
    _close_trick_window(game)
    assert game.state.players_by_id[_other(game)].chained is True
    assert game.state.players_by_id[_me(game)].chained is True


def _fire_slash_other(game: ProductionBasicCardBatch) -> None:
    slash = _action(game, "use_slash", card_key="sgs_basic_huosha")
    assert slash is not None
    _step(game, slash)
    pass_action = _action(game, "pass_slash_response")
    assert pass_action is not None
    _step(game, pass_action)


def _lightning_slash_other(game: ProductionBasicCardBatch) -> None:
    slash = _action(game, "use_slash", card_key="sgs_basic_leisha")
    assert slash is not None
    _step(game, slash)
    pass_action = _action(game, "pass_slash_response")
    assert pass_action is not None
    _step(game, pass_action)


def _fire_attack_other(game: ProductionBasicCardBatch) -> None:
    fire = _action(
        game,
        "use_fire_attack",
        card_key="sgs_trick_huogong",
        targets=(_other(game),),
    )
    assert fire is not None
    _step(game, fire)
    _close_trick_window(game)
    reveal = _action(game, "reveal_card_for_fire_attack")
    assert reveal is not None
    _step(game, reveal)
    pending = game.runtime.pending_fire_attack
    assert pending is not None and pending.revealed_suit is not None
    same_suit = next(
        (
            instance_id
            for instance_id in game.state.card_ids_in(DRAW_PILE)
            if game.state.cards_by_id[instance_id].suit
            == pending.revealed_suit
        ),
        None,
    )
    if same_suit is not None:
        _move_to_hand(game, same_suit, _me(game))
    discard = _action(game, "discard_same_suit_for_fire_attack")
    assert discard is not None
    _step(game, discard)


def _load_tampered(record: ProductionReexecutionReplay) -> dict[str, object]:
    tampered = copy.deepcopy(record.to_dict())
    del tampered["record_sha256"]
    return tampered


# ----------------------------------------------------------------------
# 纯函数：触发条件、顺序、动态跳过、结果与基数
# ----------------------------------------------------------------------


def test_chain_trigger_conditions_only_attribute_chained_positive() -> None:
    assert _chain_trigger_conditions("火属性", True, 1) is True
    assert _chain_trigger_conditions("雷属性", True, 1) is True
    assert _chain_trigger_conditions("无属性", True, 1) is False
    assert _chain_trigger_conditions("火属性", False, 1) is False
    assert _chain_trigger_conditions("雷属性", True, 0) is False


def test_chain_zero_damage_does_not_trigger_or_unchain() -> None:
    assert _chain_trigger_conditions("火属性", True, 0) is False
    unchain, result = _chain_recipient_outcome(0)
    assert unchain is False
    assert result == "prevented_zero"


def test_ordered_chain_candidates_anchor_and_exclude_original() -> None:
    players = (
        PlayerState("p1", 1, 4, 4, chained=True),
        PlayerState("p2", 2, 4, 4, chained=True),
        PlayerState("p3", 3, 4, 4, chained=True),
        PlayerState("p4", 4, 4, 4, chained=True),
    )
    order = _ordered_chain_candidate_ids(players, "p2", "p2")
    assert order == ("p3", "p4", "p1")
    assert "p2" not in order
    order2 = _ordered_chain_candidate_ids(players, "p3", "p2")
    assert order2 == ("p3", "p4", "p1")


def test_chain_dynamic_skip_reason_dead_and_unchained() -> None:
    assert _chain_dynamic_skip_reason(alive=False, chained=True) == "skipped_dead"
    assert (
        _chain_dynamic_skip_reason(alive=True, chained=False)
        == "skipped_unchained"
    )
    assert _chain_dynamic_skip_reason(alive=True, chained=True) is None


def test_chain_recipient_outcome_damaged_unchains() -> None:
    unchain, result = _chain_recipient_outcome(2)
    assert unchain is True
    assert result == "damaged"


def test_chain_recipient_base_ignores_previous_actual_damage() -> None:
    assert _chain_recipient_base(2, None) == 2
    assert _chain_recipient_base(2, 5) == 2
    assert _chain_recipient_base(3, 1) == 3


# ----------------------------------------------------------------------
# 基础：三种属性伤害入口触发传导
# ----------------------------------------------------------------------


def test_fire_slash_chained_other_triggers_chain() -> None:
    game = _fresh(3)
    _stock_tricks(game)
    _stock_card_key_to_hand(game, "sgs_basic_huosha", _me(game))
    _chain_both(game)
    _fire_slash_other(game)
    assert game.phase is ProductionPhase.PLAY
    damage = _events_of(game, EventType.DAMAGE)
    assert len(damage) == 2
    assert damage[0].damage_type == "火属性"
    assert damage[1].payload["is_chain_transmitted"] is True
    assert damage[1].amount == 1
    assert game.state.players_by_id[_other(game)].chained is False
    assert game.state.players_by_id[_me(game)].chained is False
    started = _events_of(game, EventType.CHAIN_DAMAGE_STARTED)
    assert len(started) == 1
    finished = _events_of(game, EventType.CHAIN_DAMAGE_FINISHED)
    assert finished[0].payload["stop_reason"] == "completed"


def test_lightning_slash_chained_other_triggers_chain() -> None:
    game = _fresh(7)
    _stock_tricks(game)
    _stock_card_key_to_hand(game, "sgs_basic_leisha", _me(game))
    _chain_both(game)
    _lightning_slash_other(game)
    damage = _events_of(game, EventType.DAMAGE)
    assert len(damage) == 2
    assert damage[1].damage_type == "雷属性"
    assert game.state.players_by_id[_me(game)].chained is False


def test_fire_attack_chained_other_triggers_chain() -> None:
    game = _fresh(11)
    _stock_tricks(game)
    _stock_card_key_to_hand(game, "sgs_trick_huogong", _me(game))
    _chain_both(game)
    _fire_attack_other(game)
    damage = _events_of(game, EventType.DAMAGE)
    assert len(damage) == 2
    assert damage[1].damage_type == "火属性"
    assert damage[1].payload["is_chain_transmitted"] is True
    assert game.state.players_by_id[_me(game)].chained is False


def test_unchained_other_fire_slash_does_not_chain() -> None:
    game = _fresh(13)
    _stock_tricks(game)
    _stock_card_key_to_hand(game, "sgs_basic_huosha", _me(game))
    _fire_slash_other(game)
    damage = _events_of(game, EventType.DAMAGE)
    assert len(damage) == 1
    assert _events_of(game, EventType.CHAIN_DAMAGE_STARTED) == []
    assert game.state.players_by_id[_other(game)].chained is False


def test_chained_other_no_attribute_slash_does_not_chain() -> None:
    game = _fresh(17)
    _stock_tricks(game)
    _stock_card_key_to_hand(game, "sgs_basic_sha", _me(game))
    _step(
        game,
        _action(
            game, "use_tiesuo", card_key=TIESUO, targets=(_other(game),)
        ),
    )
    _close_trick_window(game)
    slash = _action(game, "use_slash", card_key="sgs_basic_sha")
    assert slash is not None
    _step(game, slash)
    pass_action = _action(game, "pass_slash_response")
    assert pass_action is not None
    _step(game, pass_action)
    damage = _events_of(game, EventType.DAMAGE)
    assert len(damage) == 1
    assert damage[0].damage_type == "无属性"
    assert _events_of(game, EventType.CHAIN_DAMAGE_STARTED) == []
    assert game.state.players_by_id[_other(game)].chained is True


def test_original_unchains_after_actual_damage() -> None:
    game = _fresh(19)
    _stock_tricks(game)
    _stock_card_key_to_hand(game, "sgs_basic_huosha", _me(game))
    _chain_both(game)
    _fire_slash_other(game)
    chained_events = _events_of(game, EventType.CHAINED_STATE)
    original_unchain = next(
        event
        for event in chained_events
        if event.target_ids == (_other(game),)
        and event.payload["reason"] == "chain_damage_original_unchained"
    )
    assert original_unchain.payload["old_value"] is True
    assert original_unchain.payload["new_value"] is False


def test_chain_target_unchains_after_actual_damage() -> None:
    game = _fresh(23)
    _stock_tricks(game)
    _stock_card_key_to_hand(game, "sgs_basic_huosha", _me(game))
    _chain_both(game)
    _fire_slash_other(game)
    chained_events = _events_of(game, EventType.CHAINED_STATE)
    target_unchain = next(
        event
        for event in chained_events
        if event.target_ids == (_me(game),)
        and event.payload["reason"] == "chain_damage_target_unchained"
    )
    assert target_unchain.payload["old_value"] is True
    assert target_unchain.payload["new_value"] is False


# ----------------------------------------------------------------------
# 来源、实体牌与基数继承
# ----------------------------------------------------------------------


def test_chain_inherits_source_and_root_card() -> None:
    game = _fresh(29)
    _stock_tricks(game)
    slash_id = _stock_card_key_to_hand(game, "sgs_basic_huosha", _me(game))
    _chain_both(game)
    _fire_slash_other(game)
    damage = _events_of(game, EventType.DAMAGE)
    assert damage[1].damage_source == _me(game)
    assert damage[1].card_instance_id == slash_id
    assert damage[1].card_key == "sgs_basic_huosha"
    assert damage[1].card_user == _me(game)


def test_chain_inherits_damage_type() -> None:
    game = _fresh(31)
    _stock_tricks(game)
    _stock_card_key_to_hand(game, "sgs_basic_leisha", _me(game))
    _chain_both(game)
    _lightning_slash_other(game)
    damage = _events_of(game, EventType.DAMAGE)
    assert damage[0].damage_type == "雷属性"
    assert damage[1].damage_type == "雷属性"


def test_chain_base_equals_original_actual_damage() -> None:
    game = _fresh(37)
    _stock_tricks(game)
    _stock_card_key_to_hand(game, "sgs_basic_jiu", _me(game))
    _stock_card_key_to_hand(game, "sgs_basic_huosha", _me(game))
    _chain_both(game)
    _step(game, _action(game, "use_wine_buff", card_key="sgs_basic_jiu"))
    _fire_slash_other(game)
    damage = _events_of(game, EventType.DAMAGE)
    assert damage[0].amount == 2
    assert damage[1].amount == 2
    assert damage[1].payload["chain_base_damage"] == 2
    started = _events_of(game, EventType.CHAIN_DAMAGE_STARTED)
    assert started[0].payload["chain_base_damage"] == 2


def test_chain_transmitted_damage_does_not_start_new_root() -> None:
    game = _fresh(41)
    _stock_tricks(game)
    _stock_card_key_to_hand(game, "sgs_basic_huosha", _me(game))
    _chain_both(game)
    _fire_slash_other(game)
    started = _events_of(game, EventType.CHAIN_DAMAGE_STARTED)
    assert len(started) == 1
    damage = _events_of(game, EventType.DAMAGE)
    assert damage[1].payload["is_chain_transmitted"] is True
    assert damage[1].payload["root_damage_event_id"] == (
        started[0].payload["root_damage_event_id"]
    )


def test_each_candidate_uses_base_not_previous_actual() -> None:
    assert _chain_recipient_base(2, 1) == 2
    game = _fresh(43)
    _stock_tricks(game)
    _stock_card_key_to_hand(game, "sgs_basic_huosha", _me(game))
    _chain_both(game)
    _fire_slash_other(game)
    damage = _events_of(game, EventType.DAMAGE)
    assert damage[1].amount == damage[0].amount
    assert damage[1].payload["chain_base_damage"] == damage[0].amount


# ----------------------------------------------------------------------
# 顺序、濒死暂停／恢复、胜利终止与跳过
# ----------------------------------------------------------------------


def test_dual_candidate_order_is_opponent() -> None:
    game = _fresh(47)
    _stock_tricks(game)
    _stock_card_key_to_hand(game, "sgs_basic_huosha", _me(game))
    _chain_both(game)
    _fire_slash_other(game)
    started = _events_of(game, EventType.CHAIN_DAMAGE_STARTED)
    assert tuple(started[0].payload["candidate_order"]) == (_me(game),)
    order = _ordered_chain_candidate_ids(
        game.state.players, _me(game), _other(game)
    )
    assert order == (_me(game),)


def test_original_dying_rescue_completes_before_chain() -> None:
    game = _fresh(53, player_hp=(1, 1))
    _stock_tricks(game)
    _stock_card_key_to_hand(game, "sgs_basic_huosha", _me(game))
    _stock_card_key_to_hand(game, "sgs_basic_tao", _me(game))
    _stock_card_key_to_hand(game, "sgs_basic_jiu", _me(game))
    _chain_both(game)
    slash = _action(game, "use_slash", card_key="sgs_basic_huosha")
    assert slash is not None
    _step(game, slash)
    pass_action = _action(game, "pass_slash_response")
    assert pass_action is not None
    _step(game, pass_action)
    assert game.phase is ProductionPhase.DYING_RESCUE
    assert game.runtime.pending_chain is not None
    damage_before_rescue = _events_of(game, EventType.DAMAGE)
    assert len(damage_before_rescue) == 1
    _step(
        game,
        _action(
            game,
            "rescue_with_peach",
            card_key="sgs_basic_tao",
            targets=(_other(game),),
        ),
    )
    # 原始对手救援完成后，传导继续命中当前角色并使其濒死。
    assert game.phase is ProductionPhase.DYING_RESCUE
    assert game.runtime.pending_dying_id == _me(game)
    _step(
        game,
        _action(
            game,
            "rescue_with_wine",
            card_key="sgs_basic_jiu",
            targets=(_me(game),),
        ),
    )
    assert game.phase is ProductionPhase.PLAY
    damage_after = _events_of(game, EventType.DAMAGE)
    assert len(damage_after) == 2
    assert damage_after[1].payload["is_chain_transmitted"] is True
    rescue_events = [
        event
        for event in game.events
        if event.event_type is EventType.CARD_USED
        and event.payload.get("purpose") == "dying_rescue"
    ]
    assert damage_after[1].sequence > rescue_events[-1].sequence


def test_chain_target_dying_pauses_and_resumes() -> None:
    game = _fresh(59, player_hp=(1, 1))
    _stock_tricks(game)
    _stock_card_key_to_hand(game, "sgs_basic_huosha", _me(game))
    _stock_card_key_to_hand(game, "sgs_basic_tao", _me(game))
    _stock_card_key_to_hand(game, "sgs_basic_jiu", _me(game))
    _chain_both(game)
    slash = _action(game, "use_slash", card_key="sgs_basic_huosha")
    assert slash is not None
    _step(game, slash)
    pass_action = _action(game, "pass_slash_response")
    assert pass_action is not None
    _step(game, pass_action)
    # 原始对手濒死：先救援对手。
    _step(
        game,
        _action(
            game,
            "rescue_with_peach",
            card_key="sgs_basic_tao",
            targets=(_other(game),),
        ),
    )
    # 随后传导到当前角色并进入濒死：传导队列挂起。
    assert game.phase is ProductionPhase.DYING_RESCUE
    assert game.runtime.pending_dying_id == _me(game)
    chain = game.runtime.pending_chain
    assert chain is not None
    assert chain.current_target_id == _me(game)
    assert chain.pause_reason == "recipient_dying"
    damage_before = _events_of(game, EventType.DAMAGE)
    assert len(damage_before) == 2
    _step(
        game,
        _action(
            game,
            "rescue_with_wine",
            card_key="sgs_basic_jiu",
            targets=(_me(game),),
        ),
    )
    assert game.phase is ProductionPhase.PLAY
    finished = _events_of(game, EventType.CHAIN_DAMAGE_FINISHED)
    assert finished[0].payload["stop_reason"] == "completed"
    assert game.state.players_by_id[_me(game)].hp == 1


def test_victory_stops_unstarted_chain() -> None:
    game = _fresh(61, player_hp=(1, 1))
    _stock_tricks(game)
    _stock_card_key_to_hand(game, "sgs_basic_huosha", _me(game))
    _chain_both(game)
    slash = _action(game, "use_slash", card_key="sgs_basic_huosha")
    assert slash is not None
    _step(game, slash)
    pass_action = _action(game, "pass_slash_response")
    assert pass_action is not None
    _step(game, pass_action)
    assert game.phase is ProductionPhase.DYING_RESCUE
    _step(game, _action(game, "pass_rescue"))
    _step(game, _action(game, "pass_rescue"))
    assert game.is_finished
    damage = _events_of(game, EventType.DAMAGE)
    assert len(damage) == 1
    finished = _events_of(game, EventType.CHAIN_DAMAGE_FINISHED)
    assert finished[0].payload["stop_reason"] == "winner"
    assert _me(game) in finished[0].payload["skipped_targets"]
    assert game.runtime.pending_chain is None
    # N1：winner 终止不产生 stopped_winner 目标结算事件
    resolved = _events_of(game, EventType.CHAIN_TARGET_RESOLVED)
    assert not any(
        event.payload.get("result") == "stopped_winner"
        for event in resolved
    )


def test_unchained_target_is_skipped_deterministically() -> None:
    game = _fresh(67)
    _stock_tricks(game)
    _stock_card_key_to_hand(game, "sgs_basic_huosha", _me(game))
    # 只横置对手：候选当前角色未横置，应确定性跳过。
    _step(
        game,
        _action(
            game, "use_tiesuo", card_key=TIESUO, targets=(_other(game),)
        ),
    )
    _close_trick_window(game)
    _fire_slash_other(game)
    damage = _events_of(game, EventType.DAMAGE)
    assert len(damage) == 1
    resolved = _events_of(game, EventType.CHAIN_TARGET_RESOLVED)
    assert resolved[0].payload["result"] == "skipped_unchained"
    assert resolved[0].payload["actual_damage"] == 0
    finished = _events_of(game, EventType.CHAIN_DAMAGE_FINISHED)
    assert finished[0].payload["stop_reason"] == "completed"


def test_dead_target_skip_is_deterministic() -> None:
    assert _chain_dynamic_skip_reason(alive=False, chained=True) == "skipped_dead"


def test_original_target_is_not_reprocessed() -> None:
    game = _fresh(71)
    _stock_tricks(game)
    _stock_card_key_to_hand(game, "sgs_basic_huosha", _me(game))
    _chain_both(game)
    _fire_slash_other(game)
    damage = _events_of(game, EventType.DAMAGE)
    assert len(damage) == 2
    assert [event.target_id for event in damage] == [_other(game), _me(game)]


def test_prevented_zero_step_returns_finished_outcome() -> None:
    game = _fresh(73)
    _stock_tricks(game)
    me, other = _me(game), _other(game)
    game._state = _replace_player(game.state, me, chained=True)
    game._state = _replace_player(game.state, other, chained=True)
    root_card = next(iter(game.state.card_ids_in(ZoneRef.hand(me))))
    chain = _PendingChainDamage(
        root_damage_event_id="1",
        root_damage_source_id=me,
        root_card_instance_id=root_card,
        root_card_key=TIESUO,
        root_card_user=me,
        damage_type="火属性",
        chain_base_damage=1,
        original_target_id=other,
        candidate_order=(me, other),
        session_id=game.session_id,
    )
    runtime = replace(game._runtime, pending_chain=chain)
    hp_before = game.state.players_by_id[me].hp
    finished_before = len(_events_of(game, EventType.CHAIN_DAMAGE_FINISHED))
    next_state, next_runtime, outcome = (
        game._apply_chain_damage_to_target(
            game.state, runtime, chain, me, amount=0
        )
    )
    assert outcome is _ChainStepOutcome.FINISHED
    assert next_runtime.pending_chain is None
    finished = _events_of(game, EventType.CHAIN_DAMAGE_FINISHED)
    assert len(finished) == finished_before + 1
    assert finished[-1].payload["stop_reason"] == "prevented_zero"
    assert next_state.players_by_id[me].hp == hp_before
    assert next_state.players_by_id[me].chained is True


def test_prevented_zero_finishes_chain_without_loop_or_double_event() -> None:
    game = _fresh(79)
    _stock_tricks(game)
    me, other = _me(game), _other(game)
    game._state = _replace_player(game.state, me, chained=True)
    game._state = _replace_player(game.state, other, chained=True)
    root_card = next(iter(game.state.card_ids_in(ZoneRef.hand(me))))
    chain = _PendingChainDamage(
        root_damage_event_id="1",
        root_damage_source_id=me,
        root_card_instance_id=root_card,
        root_card_key=TIESUO,
        root_card_user=me,
        damage_type="雷属性",
        chain_base_damage=1,
        original_target_id=other,
        candidate_order=(me, other),
        session_id=game.session_id,
    )
    runtime = replace(game._runtime, pending_chain=chain)
    hp_before = {
        player_id: game.state.players_by_id[player_id].hp
        for player_id in (me, other)
    }
    finished_before = len(_events_of(game, EventType.CHAIN_DAMAGE_FINISHED))
    resolved_before = len(_events_of(game, EventType.CHAIN_TARGET_RESOLVED))
    # 第一个候选归零后必须立即结束：不得再次进入循环、不得访问已清理的
    # pending_chain、不得处理后续尚未开始目标、不得抛 ProductionBatchError。
    next_state, next_runtime = game._advance_chain(
        game.state, runtime, amount_override=0
    )
    assert next_runtime.pending_chain is None
    assert next_runtime.phase is ProductionPhase.PLAY
    finished = _events_of(game, EventType.CHAIN_DAMAGE_FINISHED)
    assert len(finished) == finished_before + 1
    assert finished[-1].payload["stop_reason"] == "prevented_zero"
    assert finished[-1].payload["processed_targets"] == ()
    resolved = _events_of(game, EventType.CHAIN_TARGET_RESOLVED)
    assert len(resolved) == resolved_before + 1
    assert resolved[-1].payload["result"] == "prevented_zero"
    assert resolved[-1].payload["target_index"] == 0
    assert resolved[-1].payload["actual_damage"] == 0
    assert resolved[-1].payload["chained_old"] is True
    assert resolved[-1].payload["chained_new"] is True
    # 后续尚未开始目标未被处理：体力与横置均不变。
    for player_id in (me, other):
        assert next_state.players_by_id[player_id].hp == hp_before[player_id]
        assert next_state.players_by_id[player_id].chained is True
    assert len(_events_of(game, EventType.DAMAGE)) == 0


def test_chain_step_amount_injection_rejects_negative() -> None:
    game = _fresh(83)
    _stock_tricks(game)
    me, other = _me(game), _other(game)
    game._state = _replace_player(game.state, me, chained=True)
    game._state = _replace_player(game.state, other, chained=True)
    root_card = next(iter(game.state.card_ids_in(ZoneRef.hand(me))))
    chain = _PendingChainDamage(
        root_damage_event_id="1",
        root_damage_source_id=me,
        root_card_instance_id=root_card,
        root_card_key=TIESUO,
        root_card_user=me,
        damage_type="火属性",
        chain_base_damage=1,
        original_target_id=other,
        candidate_order=(me,),
        session_id=game.session_id,
    )
    runtime = replace(game._runtime, pending_chain=chain)
    with pytest.raises(ValueError, match="不能为负数"):
        game._apply_chain_damage_to_target(
            game.state, runtime, chain, me, amount=-1
        )
    with pytest.raises(TypeError, match="必须是整数"):
        game._apply_chain_damage_to_target(
            game.state, runtime, chain, me, amount=True  # type: ignore[arg-type]
        )


# ----------------------------------------------------------------------
# 严格回放与篡改失败关闭
# ----------------------------------------------------------------------


class _ChainReplayController(ScriptedBatchController):
    """录制控制器：铁索单目标使用精确匹配，避免误选多目标组合。"""

    @staticmethod
    def _matches(action: LegalAction, spec: dict[str, object]) -> bool:
        for key, value in spec.items():
            if key == "operation":
                if action.payload.get("operation") != value:
                    return False
            elif key == "card_key":
                if action.payload.get("card_key") != value:
                    return False
            elif key == "target":
                if action.target_ids != (value,):
                    return False
            elif key == "target_count":
                if len(action.target_ids) != value:
                    return False
            elif key == "include_self":
                if value and not any(
                    target == action.actor_id for target in action.target_ids
                ):
                    return False
            else:
                return False
        return True


@pytest.fixture(scope="module")
def chain_replay_record() -> ProductionReexecutionReplay:
    specs = [
        {"operation": "use_tiesuo", "card_key": TIESUO, "target": "p2"},
        {"operation": "pass_trick_response"},
        {"operation": "pass_trick_response"},
        {"operation": "use_tiesuo", "card_key": TIESUO, "target": "p1"},
        {"operation": "pass_trick_response"},
        {"operation": "pass_trick_response"},
        {"operation": "use_slash", "card_key": "sgs_basic_huosha"},
        {"operation": "pass_slash_response"},
        {"operation": "use_slash", "card_key": "sgs_basic_sha"},
        {"operation": "pass_slash_response"},
        {"operation": "pass_rescue"},
        {"operation": "pass_rescue"},
    ]
    return record_reference_production_batch(
        seed=273,
        player_hp=(2, 2),
        player_max_hp=(2, 2),
        initial_hand_count=8,
        controller=_ChainReplayController(specs),
    )


def test_chain_replay_reexecutes(
    chain_replay_record: ProductionReexecutionReplay,
) -> None:
    result = reexecute_production_replay(chain_replay_record)
    assert result.verified is True
    started = _events_with_type(chain_replay_record.events, "chain_damage_started")
    assert len(started) == 1
    resolved = _events_with_type(
        chain_replay_record.events, "chain_target_resolved"
    )
    assert any(
        event["payload"]["result"] == "damaged" for event in resolved
    )
    finished = _events_with_type(
        chain_replay_record.events, "chain_damage_finished"
    )
    assert finished[0]["payload"]["stop_reason"] == "completed"
    assert chain_replay_record.outcome["winner_id"] in ("p1", "p2")


def test_chain_replay_tamper_root_event_id_fails(
    chain_replay_record: ProductionReexecutionReplay,
) -> None:
    tampered = _load_tampered(chain_replay_record)
    event = next(
        event
        for event in tampered["events"]
        if event.get("event_type") == "chain_damage_started"
    )
    event["payload"]["root_damage_event_id"] = "forged-root"
    with pytest.raises(ProductionReplayFormatError):
        ProductionReexecutionReplay.from_dict(tampered)


def test_chain_replay_tamper_base_damage_fails(
    chain_replay_record: ProductionReexecutionReplay,
) -> None:
    tampered = _load_tampered(chain_replay_record)
    event = next(
        event
        for event in tampered["events"]
        if event.get("event_type") == "chain_damage_started"
    )
    event["payload"]["chain_base_damage"] = 5
    with pytest.raises(ProductionReplayFormatError):
        ProductionReexecutionReplay.from_dict(tampered)


def test_chain_replay_tamper_source_fails(
    chain_replay_record: ProductionReexecutionReplay,
) -> None:
    tampered = _load_tampered(chain_replay_record)
    event = next(
        event
        for event in tampered["events"]
        if event.get("event_type") == "damage"
        and event.get("payload", {}).get("is_chain_transmitted") is True
    )
    event["damage_source"] = "forged-source"
    with pytest.raises(ProductionReplayFormatError):
        ProductionReexecutionReplay.from_dict(tampered)


def test_chain_replay_tamper_root_card_fails(
    chain_replay_record: ProductionReexecutionReplay,
) -> None:
    tampered = _load_tampered(chain_replay_record)
    event = next(
        event
        for event in tampered["events"]
        if event.get("event_type") == "chain_damage_started"
    )
    event["card_instance_id"] = "forged-card"
    with pytest.raises(ProductionReplayFormatError):
        ProductionReexecutionReplay.from_dict(tampered)


def test_chain_replay_tamper_target_fails(
    chain_replay_record: ProductionReexecutionReplay,
) -> None:
    tampered = _load_tampered(chain_replay_record)
    event = next(
        event
        for event in tampered["events"]
        if event.get("event_type") == "chain_target_resolved"
    )
    event["target_ids"] = ["forged-target"]
    event["payload"]["target_id"] = "forged-target"
    with pytest.raises(ProductionReplayFormatError):
        ProductionReexecutionReplay.from_dict(tampered)


def test_chain_replay_tamper_index_fails(
    chain_replay_record: ProductionReexecutionReplay,
) -> None:
    tampered = _load_tampered(chain_replay_record)
    event = next(
        event
        for event in tampered["events"]
        if event.get("event_type") == "chain_target_resolved"
    )
    event["payload"]["target_index"] = 9
    with pytest.raises(ProductionReplayFormatError):
        ProductionReexecutionReplay.from_dict(tampered)


def test_chain_replay_tamper_chained_state_fails(
    chain_replay_record: ProductionReexecutionReplay,
) -> None:
    tampered = _load_tampered(chain_replay_record)
    event = next(
        event
        for event in tampered["events"]
        if event.get("event_type") == "chained_state"
        and event.get("payload", {}).get("reason")
        == "chain_damage_original_unchained"
    )
    event["payload"]["old_value"] = False
    event["payload"]["new_value"] = True
    with pytest.raises(ProductionReplayFormatError):
        ProductionReexecutionReplay.from_dict(tampered)


def test_chain_replay_delete_started_event_fails(
    chain_replay_record: ProductionReexecutionReplay,
) -> None:
    tampered = _load_tampered(chain_replay_record)
    tampered["events"] = [
        event
        for event in tampered["events"]
        if event.get("event_type") != "chain_damage_started"
    ]
    with pytest.raises(ProductionReplayFormatError):
        ProductionReexecutionReplay.from_dict(tampered)


def test_chain_replay_delete_resolved_event_fails(
    chain_replay_record: ProductionReexecutionReplay,
) -> None:
    tampered = _load_tampered(chain_replay_record)
    tampered["events"] = [
        event
        for event in tampered["events"]
        if event.get("event_type") != "chain_target_resolved"
    ]
    with pytest.raises(ProductionReplayFormatError):
        ProductionReexecutionReplay.from_dict(tampered)


def test_chain_replay_tamper_stop_reason_fails(
    chain_replay_record: ProductionReexecutionReplay,
) -> None:
    tampered = _load_tampered(chain_replay_record)
    event = next(
        event
        for event in tampered["events"]
        if event.get("event_type") == "chain_damage_finished"
    )
    event["payload"]["stop_reason"] = "forged"
    with pytest.raises(ProductionReplayFormatError):
        ProductionReexecutionReplay.from_dict(tampered)


def test_chain_replay_forge_derived_damage_as_new_root_fails(
    chain_replay_record: ProductionReexecutionReplay,
) -> None:
    tampered = _load_tampered(chain_replay_record)
    derived = next(
        event
        for event in tampered["events"]
        if event.get("event_type") == "damage"
        and event.get("payload", {}).get("is_chain_transmitted") is True
    )
    derived["payload"]["is_chain_transmitted"] = False
    tampered["events"].append(
        {
            "sequence": 999999,
            "event_type": "chain_damage_started",
            "card_instance_id": derived["card_instance_id"],
            "card_key": derived["card_key"],
            "card_user": derived["card_user"],
            "damage_source": derived["damage_source"],
            "target_ids": derived["target_ids"],
            "payload": {
                "root_damage_event_id": "forged-new-root",
                "damage_type": derived["damage_type"],
                "chain_base_damage": derived["amount"],
                "candidate_order": ["p1"],
            },
        }
    )
    with pytest.raises(ProductionReplayFormatError):
        ProductionReexecutionReplay.from_dict(tampered)


def test_chain_replay_tamper_decision_diverges(
    chain_replay_record: ProductionReexecutionReplay,
) -> None:
    tampered = _load_tampered(chain_replay_record)
    slash_decision = next(
        decision
        for decision in tampered["decisions"]
        if decision["chosen_action"].get("payload", {}).get("operation")
        == "use_slash"
        and decision["chosen_action"].get("payload", {}).get("card_key")
        == "sgs_basic_huosha"
    )
    slash_decision["chosen_action"]["payload"]["card_key"] = "sgs_basic_leisha"
    rebuilt = ProductionReexecutionReplay.from_dict(tampered)
    with pytest.raises(ProductionReplayDivergenceError):
        reexecute_production_replay(rebuilt)


# ----------------------------------------------------------------------
# 回归：门禁已被正式管线替代、计数边界保持
# ----------------------------------------------------------------------


def test_cp04i_gate_replaced_by_formal_pipeline() -> None:
    import scripts.sgs_engine.production_batch as production_batch_mod

    assert not hasattr(production_batch_mod, "_assert_chain_damage_gate")
    game = _fresh(83)
    registry = game.formal_registry
    spec = registry.rule_spec_for(TIESUO)
    assert spec["chain_damage_implemented"] is True
    assert spec["full_semantics_complete"] is True
    manifest_path = (
        Path(__file__).resolve().parents[1]
        / "docs"
        / "CHECKPOINT_MANIFEST.json"
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    batch = manifest["final_verification"][
        "production_remaining_ordinary_trick_batch"
    ]
    assert batch["tiesuo_chain_damage_implemented"] is True
    assert batch["tiesuo_full_semantics_complete"] is True
    assert batch["approximation_count"] == 0


def test_no_attribute_damage_keeps_chained_and_no_chain() -> None:
    game = _fresh(89)
    _stock_tricks(game)
    _stock_card_key_to_hand(game, "sgs_basic_sha", _me(game))
    _step(
        game,
        _action(
            game, "use_tiesuo", card_key=TIESUO, targets=(_other(game),)
        ),
    )
    _close_trick_window(game)
    slash = _action(game, "use_slash", card_key="sgs_basic_sha")
    assert slash is not None
    _step(game, slash)
    pass_action = _action(game, "pass_slash_response")
    assert pass_action is not None
    _step(game, pass_action)
    assert game.state.players_by_id[_other(game)].chained is True
    assert _events_of(game, EventType.CHAIN_DAMAGE_STARTED) == []


def test_docs_do_not_declare_stopped_winner_as_legal_result() -> None:
    """N1：文档不得把 stopped_winner 列为合法 result 枚举。"""

    root = Path(__file__).resolve().parents[1]
    for doc_path in (
        root / "docs" / "ENGINE_STATUS.md",
        root / "docs" / "IMPLEMENTATION_MATRIX.md",
        root / "docs" / "MASTER_IMPLEMENTATION_PLAN.md",
        root / "docs" / "CHECKPOINT_MANIFEST.json",
    ):
        text = doc_path.read_text(encoding="utf-8")
        # 只禁止“合法枚举列表”形式的声明（damaged|...|stopped_winner）；
        # “不产生 stopped_winner／不是生产实现值”等否定表述允许保留。
        assert "|stopped_winner" not in text, (
            f"{doc_path.name} 中不得把 stopped_winner 声明为合法枚举"
        )
        assert "stopped_winner|" not in text, (
            f"{doc_path.name} 中不得把 stopped_winner 声明为合法枚举"
        )
