# -*- coding: utf-8 -*-
"""【南蛮入侵】【万箭齐发】【桃园结义】群体普通锦囊生产垂直切片测试。

覆盖正式CSV实体绑定、服务器自动目标序列与行动顺序、逐目标独立
【无懈可击】窗口、逐目标推进与完成时进入弃牌堆、南蛮/万箭逐目标
响应（打出【杀】/【闪】）与不响应伤害、桃园逐目标回复、濒死救援
期间队列暂停与恢复、玩家可见回放不泄露未打出手牌、严格重执行与
篡改失败关闭。正向流程与正常动作均经过真实 enumerate -> validate
-> apply 路径；定向伪造负向测试允许直接调用生产适配器入口，用于
验证生产层失败关闭；不使用 mock 或替代结算器。夹具只通过不可变
GameState 与权威状态转换助手构造前置状态，不代表装备、延时锦囊或
武将技能已实现。
"""
from __future__ import annotations

import copy
import json
from dataclasses import replace
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
    PROCESSING_ZONE,
    ZoneRef,
)
from scripts.sgs_engine.production_batch import (
    BatchActionIdController,
    ProductionBasicCardBatch,
    ProductionBatchFinishedError,
    ProductionPhase,
    ScriptedBatchController,
    _replace_player,
)
from scripts.sgs_engine.production_cards import (
    GROUP_TRICK_KEYS,
    PRODUCTION_TRICK_KEYS,
    SLASH_CARD_KEYS,
    NanmanRuqinAdapter,
    TaoyuanJieyiAdapter,
    WanjianQifaAdapter,
)
from scripts.sgs_engine.production_replay import (
    ProductionReplayDivergenceError,
    ProductionReplayFormatError,
    ProductionReexecutionReplay,
    record_reference_production_batch,
    reexecute_production_replay,
)
from scripts.sgs_engine.replay import state_sha256

NANMAN = "sgs_trick_nanmanruqin"
WANJIAN = "sgs_trick_wanjianqifa"
TAOYUAN = "sgs_trick_taoyuanjieyi"
WUXIE = "sgs_trick_wuxiekeji"
SHA = "sgs_basic_sha"
HUOSHA = "sgs_basic_huosha"
LEISHA = "sgs_basic_leisha"
SHAN = "sgs_basic_shan"
TAO = "sgs_basic_tao"

REPO_ROOT = Path(__file__).resolve().parent.parent

_GROUP_RESPONSE_PAYLOAD_KEYS = {
    "operation",
    "response_to",
    "root_trick_instance_id",
    "target_id",
    "target_index",
    "window_id",
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
) -> object | None:
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


def _move_to_hand(game: ProductionBasicCardBatch, instance_id: str, player_id: str) -> None:
    if game.state.location_of(instance_id) != ZoneRef.hand(player_id):
        game._state = game.state.move_card(instance_id, ZoneRef.hand(player_id))


def _set_hp(game: ProductionBasicCardBatch, player_id: str, hp: int) -> None:
    game._state = _replace_player(game.state, player_id, hp=hp)


def _use_group(
    game: ProductionBasicCardBatch, operation: str, card_key: str
) -> str:
    action = _action(game, operation, card_key=card_key)
    assert action is not None, f"出牌阶段必须能枚举{operation}"
    assert action.target_ids == ()
    trick_id = action.card_instance_id
    assert trick_id is not None
    _step(game, action)
    return trick_id


def _group_handle_for(
    game: ProductionBasicCardBatch, instance_id: str
) -> str:
    handles = game.runtime.group_response_handles
    for handle, candidate in handles.items():
        if candidate == instance_id:
            return handle
    raise AssertionError(f"响应窗口中没有{instance_id}的句柄")


def _play_group_response(
    game: ProductionBasicCardBatch, operation: str, instance_id: str
) -> None:
    handle = _group_handle_for(game, instance_id)
    action = next(
        action
        for action in game.legal_actions()
        if action.payload.get("operation") == operation
        and action.payload.get("handle") == handle
    )
    _step(game, action)


def _events_of(game: ProductionBasicCardBatch, event_type: EventType) -> tuple:
    return tuple(
        event for event in game.events if event.event_type is event_type
    )


def _fresh(seed: int = 3) -> ProductionBasicCardBatch:
    game = ProductionBasicCardBatch(seed=seed)
    assert game.first_player_id == "p1"
    for operation in ("proceed_prepare", "proceed_judgment", "proceed_draw"):
        action = next(
            a
            for a in game.legal_actions()
            if a.payload.get("operation") == operation
        )
        game.step(BatchActionIdController(action.action_id))
    assert game.phase.value == "play"
    return game

def _nanman_fixture(
    *, response_key: str | None = None, target_hp: int | None = None
) -> tuple[ProductionBasicCardBatch, str]:
    """p1持【南蛮入侵】，p2可选持响应牌并可选压低体力。"""
    game = _fresh(3)
    trick_id = next(
        record.instance_id
        for record in game.formal_registry.instances_of(NANMAN)
    )
    _move_to_hand(game, trick_id, "p1")
    if response_key is not None:
        response_id = next(
            record.instance_id
            for record in game.formal_registry.instances_of(response_key)
        )
        _move_to_hand(game, response_id, "p2")
    if target_hp is not None:
        _set_hp(game, "p2", target_hp)
    return game, trick_id


def _wanjian_fixture(
    *, response_key: str | None = None, target_hp: int | None = None
) -> tuple[ProductionBasicCardBatch, str]:
    game = _fresh(3)
    trick_id = next(
        record.instance_id
        for record in game.formal_registry.instances_of(WANJIAN)
    )
    _move_to_hand(game, trick_id, "p1")
    if response_key is not None:
        response_id = next(
            record.instance_id
            for record in game.formal_registry.instances_of(response_key)
        )
        _move_to_hand(game, response_id, "p2")
    if target_hp is not None:
        _set_hp(game, "p2", target_hp)
    return game, trick_id


def _taoyuan_fixture(
    *, p1_hp: int = 3, p2_hp: int = 3
) -> tuple[ProductionBasicCardBatch, str]:
    game = _fresh(3)
    trick_id = next(
        record.instance_id
        for record in game.formal_registry.instances_of(TAOYUAN)
    )
    _move_to_hand(game, trick_id, "p1")
    _set_hp(game, "p1", p1_hp)
    _set_hp(game, "p2", p2_hp)
    return game, trick_id


def _open_nanman_response(
    game: ProductionBasicCardBatch,
) -> None:
    """使用【南蛮入侵】并关闭无懈窗口，进入当前目标响应阶段。"""
    _use_group(game, "use_nanman", NANMAN)
    _close_trick_window(game)
    assert game.phase is ProductionPhase.NANMAN_RESPONSE


# ---------------------------------------------------------------------
# A. 注册表与正式牌堆
# ---------------------------------------------------------------------


def test_nanman_entities_bind_to_production_adapter() -> None:
    game = _fresh(3)
    registry = game.formal_registry
    assert NANMAN in PRODUCTION_TRICK_KEYS
    assert NANMAN in GROUP_TRICK_KEYS
    assert NANMAN in registry.implemented_card_keys
    records = registry.instances_of(NANMAN)
    assert len(records) == 3
    assert len({record.instance_id for record in records}) == 3
    assert {(record.suit, record.rank) for record in records} == {
        ("♣", "7"),
        ("♠", "7"),
        ("♠", "K"),
    }
    assert {record.instance_id for record in records} == {
        "sgs-mobile-20260725-061",
        "sgs-mobile-20260725-141",
        "sgs-mobile-20260725-158",
    }
    adapter = registry.adapter_for(NANMAN)
    assert isinstance(adapter, NanmanRuqinAdapter)
    assert adapter.implemented is True and adapter.tested is True
    spec = adapter.rule_spec()
    assert spec["card_key"] == NANMAN
    assert spec["use_timing"] == "own_play_phase"
    assert spec["target_filter"] == "all_other_characters"
    assert spec["distance_rule"] == "not_applicable"
    assert spec["nullification_eligible"] is True
    for record in records:
        card = game.state.cards_by_id[record.instance_id]
        assert card.card_key == NANMAN and card.card_name == "南蛮入侵"


def test_wanjian_entities_bind_to_production_adapter() -> None:
    game = _fresh(3)
    registry = game.formal_registry
    assert WANJIAN in PRODUCTION_TRICK_KEYS
    assert WANJIAN in GROUP_TRICK_KEYS
    assert WANJIAN in registry.implemented_card_keys
    records = registry.instances_of(WANJIAN)
    assert len(records) == 1
    assert {(record.suit, record.rank) for record in records} == {("♥", "A")}
    assert {record.instance_id for record in records} == {
        "sgs-mobile-20260725-082"
    }
    adapter = registry.adapter_for(WANJIAN)
    assert isinstance(adapter, WanjianQifaAdapter)
    assert adapter.implemented is True and adapter.tested is True
    spec = adapter.rule_spec()
    assert spec["card_key"] == WANJIAN
    assert spec["target_filter"] == "all_other_characters"
    assert spec["distance_rule"] == "not_applicable"
    assert spec["nullification_eligible"] is True
    record = records[0]
    card = game.state.cards_by_id[record.instance_id]
    assert card.card_key == WANJIAN and card.card_name == "万箭齐发"


def test_taoyuan_entities_bind_to_production_adapter() -> None:
    game = _fresh(3)
    registry = game.formal_registry
    assert TAOYUAN in PRODUCTION_TRICK_KEYS
    assert TAOYUAN in GROUP_TRICK_KEYS
    assert TAOYUAN in registry.implemented_card_keys
    records = registry.instances_of(TAOYUAN)
    assert len(records) == 1
    assert {(record.suit, record.rank) for record in records} == {("♥", "A")}
    assert {record.instance_id for record in records} == {
        "sgs-mobile-20260725-081"
    }
    adapter = registry.adapter_for(TAOYUAN)
    assert isinstance(adapter, TaoyuanJieyiAdapter)
    assert adapter.implemented is True and adapter.tested is True
    spec = adapter.rule_spec()
    assert spec["card_key"] == TAOYUAN
    assert "wounded_characters_including_self" in str(spec["target_filter"])
    assert spec["distance_rule"] == "not_applicable"
    assert spec["nullification_eligible"] is True
    record = records[0]
    card = game.state.cards_by_id[record.instance_id]
    assert card.card_key == TAOYUAN and card.card_name == "桃园结义"


def test_formal_deck_remains_160_with_unique_ids_and_single_zone() -> None:
    game = _fresh(3)
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
    game = _fresh(3)
    registry = game.formal_registry
    assert {NANMAN, WANJIAN, TAOYUAN} <= set(registry.implemented_card_keys)
    assert len(registry.implemented_card_keys) == 38
    assert len(registry.unimplemented_card_keys) == 0
    assert {NANMAN, WANJIAN, TAOYUAN} <= set(PRODUCTION_TRICK_KEYS)
    assert set(GROUP_TRICK_KEYS) == {NANMAN, WANJIAN, TAOYUAN}
    assert (
        sum(
            len(registry.instances_of(key))
            for key in registry.implemented_card_keys
        )
        == 160
    )


def test_other_unimplemented_cards_stay_fail_closed() -> None:
    game = _fresh(3)
    registry = game.formal_registry
    assert not registry.unimplemented_card_keys
    registry.assert_no_unimplemented_fallback()
    # 群体锦囊不再属于未实现卡牌
    assert NANMAN not in registry.unimplemented_card_keys
    assert WANJIAN not in registry.unimplemented_card_keys
    assert TAOYUAN not in registry.unimplemented_card_keys


# ---------------------------------------------------------------------
# B. 通用目标队列
# ---------------------------------------------------------------------


def test_target_sequence_is_server_generated_and_unmodifiable() -> None:
    game, trick_id = _taoyuan_fixture()
    assert game.runtime.pending_group_trick is None
    _use_group(game, "use_taoyuan", TAOYUAN)
    group = game.runtime.pending_group_trick
    assert group is not None
    assert group.target_sequence == ("p1", "p2")
    assert group.trick_instance_id == trick_id
    assert group.user_id == "p1"
    # 玩家伪造带目标列表的使用动作：验证与执行都必须失败关闭
    forged = LegalAction(
        action_type=ActionType.USE_CARD,
        actor_id="p1",
        card_instance_id=trick_id,
        target_ids=("p2",),
        payload={
            "operation": "use_taoyuan",
            "card_key": TAOYUAN,
            "card_name": "桃园结义",
        },
        action_id="act_forged_targets",
    )
    context = game._context()
    with pytest.raises(InvalidActionError):
        validate_action(game.state, context, forged, game.registry)
    adapter = game.formal_registry.adapter_for(TAOYUAN)
    with pytest.raises(InvalidActionError):
        adapter.apply_action(game.state, context, forged)


def test_target_order_follows_action_order() -> None:
    game, _ = _taoyuan_fixture()
    _use_group(game, "use_taoyuan", TAOYUAN)
    assert game.runtime.pending_group_trick.target_sequence == ("p1", "p2")
    game2, _ = _nanman_fixture()
    _use_group(game2, "use_nanman", NANMAN)
    assert game2.runtime.pending_group_trick.target_sequence == ("p2",)
    game3, _ = _wanjian_fixture()
    _use_group(game3, "use_wanjian", WANJIAN)
    assert game3.runtime.pending_group_trick.target_sequence == ("p2",)


def test_current_target_index_advances_step_by_step() -> None:
    game, _ = _taoyuan_fixture()
    _use_group(game, "use_taoyuan", TAOYUAN)
    assert game.runtime.pending_group_trick.current_target_index == 0
    _close_trick_window(game)
    assert game.runtime.pending_group_trick.current_target_index == 1
    _close_trick_window(game)
    assert game.runtime.pending_group_trick is None
    resolved = _events_of(game, EventType.GROUP_TARGET_RESOLVED)
    assert [event.payload["target_index"] for event in resolved] == [0, 1]
    assert [event.target_ids[0] for event in resolved] == ["p1", "p2"]


def test_each_target_has_independent_effect_state() -> None:
    game, _ = _taoyuan_fixture()
    _use_group(game, "use_taoyuan", TAOYUAN)
    _close_trick_window(game)
    _close_trick_window(game)
    resolved = _events_of(game, EventType.GROUP_TARGET_RESOLVED)
    assert len(resolved) == 2
    assert [event.target_ids for event in resolved] == [("p1",), ("p2",)]
    assert [event.payload["result"] for event in resolved] == [
        "recovered",
        "recovered",
    ]
    assert resolved[0].payload["next_target_id"] == "p2"
    assert resolved[0].payload["next_target_index"] == 1
    assert resolved[1].payload["next_target_id"] is None
    assert resolved[1].payload["next_target_index"] is None


def test_original_trick_stays_in_processing_until_last_target() -> None:
    game, trick_id = _taoyuan_fixture()
    assert game.state.location_of(trick_id) == ZoneRef.hand("p1")
    _use_group(game, "use_taoyuan", TAOYUAN)
    assert game.state.location_of(trick_id) == PROCESSING_ZONE
    _close_trick_window(game)
    # 第一目标结算完成后、第二目标开始前：原锦囊仍在处理区
    assert game.state.location_of(trick_id) == PROCESSING_ZONE
    assert game.runtime.pending_group_trick.current_target_index == 1
    _close_trick_window(game)
    assert game.state.location_of(trick_id) == DISCARD_PILE
    game.state.assert_card_conservation()


def test_trick_enters_discard_only_after_all_targets() -> None:
    game, trick_id = _taoyuan_fixture()
    _use_group(game, "use_taoyuan", TAOYUAN)
    _close_trick_window(game)
    assert game.state.location_of(trick_id) == PROCESSING_ZONE
    assert game.phase is ProductionPhase.TRICK_RESPONSE
    _close_trick_window(game)
    assert game.state.location_of(trick_id) == DISCARD_PILE
    assert game.phase is ProductionPhase.PLAY


def test_stale_previous_target_action_fails_in_next_window() -> None:
    game, _ = _taoyuan_fixture()
    wuxie_id = next(
        record.instance_id
        for record in game.formal_registry.instances_of(WUXIE)
    )
    _move_to_hand(game, wuxie_id, "p2")
    _use_group(game, "use_taoyuan", TAOYUAN)
    # 第一目标窗口（当前目标p1）：p1先响应
    _pass_trick(game)
    stale_wuxie = _action(game, "use_wuxie", card_key=WUXIE)
    assert stale_wuxie is not None
    assert stale_wuxie.target_ids == ("p1",)
    _pass_trick(game)
    # 窗口关闭并进入第二目标窗口（当前目标p2）
    assert game.runtime.pending_group_trick.current_target_index == 1
    context = game._context()
    with pytest.raises(InvalidActionError):
        validate_action(game.state, context, stale_wuxie, game.registry)
    adapter = game.formal_registry.adapter_for(WUXIE)
    with pytest.raises(InvalidActionError):
        adapter.apply_action(game.state, context, stale_wuxie)


def test_death_ends_game_and_stops_queue() -> None:
    game, trick_id = _nanman_fixture(target_hp=1)
    _open_nanman_response(game)
    _step(game, _action(game, "pass_nanman_slash"))
    assert game.phase is ProductionPhase.DYING_RESCUE
    assert game.state.players_by_id["p2"].hp == 0
    # 濒死期间原锦囊仍在处理区
    assert game.state.location_of(trick_id) == PROCESSING_ZONE
    _step(game, _action(game, "pass_rescue"))
    _step(game, _action(game, "pass_rescue"))
    assert game.is_finished
    assert game.winner_id == "p1"
    assert _events_of(game, EventType.DEATH)
    assert _events_of(game, EventType.VICTORY)
    with pytest.raises(ProductionBatchFinishedError):
        game.step(BatchActionIdController("act_after_game_over"))


def test_every_major_branch_preserves_card_conservation() -> None:
    # 南蛮响应
    game, _ = _nanman_fixture(response_key=SHA)
    _open_nanman_response(game)
    response_id = next(
        record.instance_id
        for record in game.formal_registry.instances_of(SHA)
    )
    _play_group_response(game, "play_slash_for_nanman", response_id)
    game.state.assert_card_conservation()
    # 南蛮不响应（伤害）
    game2, _ = _nanman_fixture(target_hp=2)
    _open_nanman_response(game2)
    _step(game2, _action(game2, "pass_nanman_slash"))
    game2.state.assert_card_conservation()
    # 万箭响应
    game3, _ = _wanjian_fixture(response_key=SHAN)
    _use_group(game3, "use_wanjian", WANJIAN)
    _close_trick_window(game3)
    jink_id = next(
        record.instance_id
        for record in game3.formal_registry.instances_of(SHAN)
    )
    _play_group_response(game3, "play_jink_for_wanjian", jink_id)
    game3.state.assert_card_conservation()
    # 桃园逐目标回复
    game4, _ = _taoyuan_fixture()
    _use_group(game4, "use_taoyuan", TAOYUAN)
    _close_trick_window(game4)
    _close_trick_window(game4)
    game4.state.assert_card_conservation()
    # 桃园第一目标被无懈
    game5, _ = _taoyuan_fixture()
    wuxie_id = next(
        record.instance_id
        for record in game5.formal_registry.instances_of(WUXIE)
    )
    _move_to_hand(game5, wuxie_id, "p2")
    _use_group(game5, "use_taoyuan", TAOYUAN)
    _pass_trick(game5)
    _step(game5, _action(game5, "use_wuxie", card_key=WUXIE))
    _pass_trick(game5)
    _pass_trick(game5)
    _close_trick_window(game5)
    game5.state.assert_card_conservation()
# ---------------------------------------------------------------------
# C. 逐目标【无懈可击】
# ---------------------------------------------------------------------


def test_single_wuxie_cancels_current_target() -> None:
    game, _ = _nanman_fixture()
    wuxie_id = next(
        record.instance_id
        for record in game.formal_registry.instances_of(WUXIE)
    )
    _move_to_hand(game, wuxie_id, "p2")
    _use_group(game, "use_nanman", NANMAN)
    # 无懈窗口顺序：p1（使用者）先，p2后
    _pass_trick(game)
    _step(game, _action(game, "use_wuxie", card_key=WUXIE))
    _pass_trick(game)
    _pass_trick(game)
    assert game.phase is ProductionPhase.PLAY
    assert game.state.players_by_id["p2"].hp == 4
    assert not _events_of(game, EventType.DAMAGE)
    cancelled = _events_of(game, EventType.CARD_EFFECT_CANCELLED)
    assert len(cancelled) == 1
    assert cancelled[0].target_ids == ("p2",)
    assert cancelled[0].payload["reason"] == "nullified_by_wuxie"
    resolved = _events_of(game, EventType.GROUP_TARGET_RESOLVED)
    assert len(resolved) == 1
    assert resolved[0].payload["result"] == "cancelled"


def test_wuxie_only_affects_current_target() -> None:
    game, _ = _taoyuan_fixture()
    wuxie_id = next(
        record.instance_id
        for record in game.formal_registry.instances_of(WUXIE)
    )
    _move_to_hand(game, wuxie_id, "p2")
    _use_group(game, "use_taoyuan", TAOYUAN)
    _pass_trick(game)
    _step(game, _action(game, "use_wuxie", card_key=WUXIE))
    _pass_trick(game)
    _pass_trick(game)
    # 第一目标p1被取消：体力不变
    assert game.state.players_by_id["p1"].hp == 3
    # 第二目标p2正常结算：恢复1点
    assert game.runtime.pending_group_trick.current_target_index == 1
    _close_trick_window(game)
    assert game.state.players_by_id["p2"].hp == 4
    recovers = _events_of(game, EventType.HP_RECOVER)
    assert len(recovers) == 1
    assert recovers[0].target_ids == ("p2",)


def test_next_target_still_resolves_after_cancel() -> None:
    game, _ = _taoyuan_fixture()
    wuxie_id = next(
        record.instance_id
        for record in game.formal_registry.instances_of(WUXIE)
    )
    _move_to_hand(game, wuxie_id, "p2")
    _use_group(game, "use_taoyuan", TAOYUAN)
    _pass_trick(game)
    _step(game, _action(game, "use_wuxie", card_key=WUXIE))
    _pass_trick(game)
    _pass_trick(game)
    _close_trick_window(game)
    resolved = _events_of(game, EventType.GROUP_TARGET_RESOLVED)
    assert [event.payload["result"] for event in resolved] == [
        "cancelled",
        "recovered",
    ]


def test_double_wuxie_restores_current_target_effect() -> None:
    game, _ = _taoyuan_fixture()
    wuxie_ids = [
        record.instance_id
        for record in game.formal_registry.instances_of(WUXIE)
    ]
    assert len(wuxie_ids) >= 2
    _move_to_hand(game, wuxie_ids[0], "p1")
    _move_to_hand(game, wuxie_ids[1], "p2")
    _use_group(game, "use_taoyuan", TAOYUAN)
    _step(game, _action(game, "use_wuxie", card_key=WUXIE))
    _step(game, _action(game, "use_wuxie", card_key=WUXIE))
    _pass_trick(game)
    _pass_trick(game)
    assert game.runtime.pending_group_trick.current_target_index == 1
    assert game.state.players_by_id["p1"].hp == 4
    recovers = _events_of(game, EventType.HP_RECOVER)
    assert len(recovers) == 1
    assert recovers[0].target_ids == ("p1",)


def test_wuxie_response_to_chain_is_accurate() -> None:
    game, trick_id = _taoyuan_fixture()
    wuxie_ids = [
        record.instance_id
        for record in game.formal_registry.instances_of(WUXIE)
    ]
    _move_to_hand(game, wuxie_ids[0], "p1")
    _move_to_hand(game, wuxie_ids[1], "p2")
    _use_group(game, "use_taoyuan", TAOYUAN)
    _step(game, _action(game, "use_wuxie", card_key=WUXIE))
    _step(game, _action(game, "use_wuxie", card_key=WUXIE))
    used_wuxie = [
        event
        for event in _events_of(game, EventType.CARD_USED)
        if event.card_key == WUXIE
    ]
    assert len(used_wuxie) == 2
    assert used_wuxie[0].payload["response_to"] == trick_id
    assert used_wuxie[0].payload["root_trick_instance_id"] == trick_id
    assert used_wuxie[1].payload["response_to"] == wuxie_ids[0]
    assert used_wuxie[1].payload["root_trick_instance_id"] == trick_id
    _pass_trick(game)
    _pass_trick(game)


def test_wuxie_state_resets_between_targets() -> None:
    game, _ = _taoyuan_fixture()
    _use_group(game, "use_taoyuan", TAOYUAN)
    _close_trick_window(game)
    runtime = game.runtime
    group = runtime.pending_group_trick
    assert group is not None
    assert group.current_target_index == 1
    assert group.responder_id is None
    assert runtime.trick_effect_active is True
    assert runtime.trick_consecutive_passes == 0
    assert runtime.trick_response_index == 0
    assert runtime.trick_response_order == ("p1", "p2")
    assert runtime.group_response_handles == {}
    assert runtime.group_response_snapshot_digest is None
    assert runtime.pending_trick.target_id == "p2"
    assert runtime.pending_trick.trick_instance_id == (
        game.runtime.pending_group_trick.trick_instance_id
    )


def test_cancelled_target_opens_no_response_or_recovery_step() -> None:
    # 南蛮：被无懈后不要求打出【杀】
    game, _ = _nanman_fixture(response_key=SHA)
    wuxie_id = next(
        record.instance_id
        for record in game.formal_registry.instances_of(WUXIE)
    )
    _move_to_hand(game, wuxie_id, "p2")
    _use_group(game, "use_nanman", NANMAN)
    _pass_trick(game)
    _step(game, _action(game, "use_wuxie", card_key=WUXIE))
    _pass_trick(game)
    _pass_trick(game)
    assert game.phase is ProductionPhase.PLAY
    assert not _events_of(game, EventType.DAMAGE)
    # 桃园：被无懈的目标不产生恢复事件
    game2, _ = _taoyuan_fixture()
    wuxie_id2 = next(
        record.instance_id
        for record in game2.formal_registry.instances_of(WUXIE)
    )
    _move_to_hand(game2, wuxie_id2, "p2")
    _use_group(game2, "use_taoyuan", TAOYUAN)
    _pass_trick(game2)
    _step(game2, _action(game2, "use_wuxie", card_key=WUXIE))
    _pass_trick(game2)
    _pass_trick(game2)
    _close_trick_window(game2)
    recovers = _events_of(game2, EventType.HP_RECOVER)
    assert len(recovers) == 1
    assert recovers[0].target_ids == ("p2",)


# ---------------------------------------------------------------------
# D. 【南蛮入侵】
# ---------------------------------------------------------------------


def test_nanman_auto_targets_exclude_user() -> None:
    game, _ = _nanman_fixture()
    _use_group(game, "use_nanman", NANMAN)
    group = game.runtime.pending_group_trick
    assert group.target_sequence == ("p2",)
    assert "p1" not in group.target_sequence


def test_nanman_respond_with_normal_sha() -> None:
    game, trick_id = _nanman_fixture(response_key=SHA)
    sha_id = next(
        record.instance_id
        for record in game.formal_registry.instances_of(SHA)
    )
    _open_nanman_response(game)
    _play_group_response(game, "play_slash_for_nanman", sha_id)
    assert game.phase is ProductionPhase.PLAY
    assert game.state.players_by_id["p2"].hp == 4
    played = _events_of(game, EventType.CARD_PLAYED)
    assert len(played) == 1
    assert played[0].card_instance_id == sha_id
    assert played[0].card_key == SHA
    assert played[0].payload["response_to"] == trick_id
    assert played[0].payload["root_trick_instance_id"] == trick_id
    resolved = _events_of(game, EventType.GROUP_TARGET_RESOLVED)
    assert resolved[0].payload["result"] == "responded"


def test_nanman_respond_with_fire_and_thunder_slash() -> None:
    for response_key in (HUOSHA, LEISHA):
        game, _ = _nanman_fixture(response_key=response_key)
        response_id = next(
            record.instance_id
            for record in game.formal_registry.instances_of(response_key)
        )
        _open_nanman_response(game)
        _play_group_response(game, "play_slash_for_nanman", response_id)
        assert game.phase is ProductionPhase.PLAY
        played = _events_of(game, EventType.CARD_PLAYED)
        assert len(played) == 1
        assert played[0].card_key == response_key


def test_nanman_rejects_non_slash_response() -> None:
    game, _ = _nanman_fixture(response_key=SHAN)
    _open_nanman_response(game)
    # 合法集合中只有打出杀与放弃；闪没有句柄
    operations = {
        action.payload.get("operation") for action in game.legal_actions()
    }
    assert operations == {"play_slash_for_nanman", "pass_nanman_slash"}
    forged = LegalAction(
        action_type=ActionType.PLAY_CARD,
        actor_id="p2",
        target_ids=("p2",),
        payload={
            "operation": "play_slash_for_nanman",
            "response_to": game.runtime.pending_group_trick.trick_instance_id,
            "root_trick_instance_id": (
                game.runtime.pending_group_trick.trick_instance_id
            ),
            "target_id": "p2",
            "target_index": 0,
            "window_id": "nanman_forged_window",
            "state_hash": "0" * 64,
            "handle": "gr_" + "0" * 32,
        },
        action_id="act_forged_slash",
    )
    context = game._context()
    with pytest.raises(InvalidActionError):
        validate_action(game.state, context, forged, game.registry)
    adapter = game.formal_registry.adapter_for(NANMAN)
    with pytest.raises(InvalidActionError):
        adapter.apply_action(game.state, context, forged)


def test_nanman_pass_allowed_even_with_slash_in_hand() -> None:
    game, _ = _nanman_fixture(response_key=SHA, target_hp=4)
    _open_nanman_response(game)
    assert SHA in _hand_keys(game, "p2")
    _step(game, _action(game, "pass_nanman_slash"))
    assert game.phase is ProductionPhase.PLAY
    assert game.state.players_by_id["p2"].hp == 3
    assert not _events_of(game, EventType.CARD_PLAYED)


def test_nanman_slash_is_played_not_used() -> None:
    game, _ = _nanman_fixture(response_key=SHA)
    sha_id = next(
        record.instance_id
        for record in game.formal_registry.instances_of(SHA)
    )
    _open_nanman_response(game)
    _play_group_response(game, "play_slash_for_nanman", sha_id)
    played = _events_of(game, EventType.CARD_PLAYED)
    used = _events_of(game, EventType.CARD_USED)
    assert len(played) == 1
    assert played[0].payload["creates_card_used_event"] is False
    assert played[0].payload["creates_card_played_event"] is True
    assert played[0].payload["counts_for_use_or_play_total"] is True
    assert played[0].payload["response_action"] == "play"
    assert not any(event.card_instance_id == sha_id for event in used)
    assert not game.runtime.slash_used_counts


def test_nanman_slash_full_zone_lifecycle() -> None:
    game, _ = _nanman_fixture(response_key=SHA)
    sha_id = next(
        record.instance_id
        for record in game.formal_registry.instances_of(SHA)
    )
    _open_nanman_response(game)
    _play_group_response(game, "play_slash_for_nanman", sha_id)
    assert game.state.location_of(sha_id) == DISCARD_PILE
    moved = [
        event
        for event in _events_of(game, EventType.CARD_MOVED)
        if event.card_instance_id == sha_id
    ]
    reasons = [event.payload["reason"] for event in moved]
    assert reasons == [
        "sgs_trick_nanmanruqin_response:enter_processing",
        "sgs_trick_nanmanruqin_response:leave_processing",
    ]


def test_nanman_no_response_deals_one_damage() -> None:
    game, trick_id = _nanman_fixture(target_hp=4)
    _open_nanman_response(game)
    _step(game, _action(game, "pass_nanman_slash"))
    assert game.state.players_by_id["p2"].hp == 3
    damages = _events_of(game, EventType.DAMAGE)
    assert len(damages) == 1
    assert damages[0].amount == 1
    assert damages[0].card_instance_id == trick_id


def test_nanman_damage_source_type_and_root() -> None:
    game, trick_id = _nanman_fixture(target_hp=4)
    _open_nanman_response(game)
    _step(game, _action(game, "pass_nanman_slash"))
    damage = _events_of(game, EventType.DAMAGE)[0]
    assert damage.damage_source == "p1"
    assert damage.damage_type == "无属性"
    assert damage.card_user == "p1"
    assert damage.kill_credit == "p1"
    assert damage.payload["root_trick_instance_id"] == trick_id
    assert damage.payload["target_index"] == 0
    assert damage.payload["target_count"] == 1
    resolved = _events_of(game, EventType.GROUP_TARGET_RESOLVED)[0]
    assert resolved.payload["result"] == "damaged"
    assert resolved.payload["damage_amount"] == 1
    assert resolved.payload["damage_source_id"] == "p1"
    assert resolved.payload["damage_type"] == "无属性"


def test_nanman_damage_enters_dying_and_rescue() -> None:
    game, trick_id = _nanman_fixture(target_hp=1)
    tao_id = next(
        record.instance_id for record in game.formal_registry.instances_of(TAO)
    )
    _move_to_hand(game, tao_id, "p1")
    _open_nanman_response(game)
    _step(game, _action(game, "pass_nanman_slash"))
    assert game.phase is ProductionPhase.DYING_RESCUE
    assert _events_of(game, EventType.DYING)
    # 濒死期间原锦囊留在处理区，目标队列状态保留
    assert game.state.location_of(trick_id) == PROCESSING_ZONE
    group = game.runtime.pending_group_trick
    assert group is not None
    assert group.current_target_index == 0
    assert group.trick_instance_id == trick_id


def test_nanman_rescue_then_queue_completes() -> None:
    game, trick_id = _nanman_fixture(target_hp=1)
    tao_id = next(
        record.instance_id for record in game.formal_registry.instances_of(TAO)
    )
    _move_to_hand(game, tao_id, "p1")
    _open_nanman_response(game)
    _step(game, _action(game, "pass_nanman_slash"))
    _step(game, _action(game, "rescue_with_peach", card_key=TAO))
    assert game.phase is ProductionPhase.PLAY
    assert game.state.players_by_id["p2"].hp == 1
    assert game.state.location_of(trick_id) == DISCARD_PILE
    resolved = _events_of(game, EventType.GROUP_TARGET_RESOLVED)[0]
    assert resolved.payload["result"] == "damaged"
    assert resolved.payload["rescued"] is True
    assert resolved.payload["damage_source_id"] == "p1"


def test_nanman_forged_responder_index_window_and_hash_fail() -> None:
    game, trick_id = _nanman_fixture(response_key=SHA)
    sha_id = next(
        record.instance_id
        for record in game.formal_registry.instances_of(SHA)
    )
    _open_nanman_response(game)
    handle = _group_handle_for(game, sha_id)
    context = game._context()
    adapter = game.formal_registry.adapter_for(NANMAN)
    group = game.runtime.pending_group_trick
    window_id = (
        f"{group.trick_key}:{game.runtime.turn_number}:"
        f"{group.trick_instance_id}:gt{group.current_target_index}"
    )
    legal_state_hash = state_sha256(canonical_state_snapshot(game.state))
    real_action = next(
        action
        for action in game.legal_actions()
        if action.payload.get("operation") == "play_slash_for_nanman"
        and action.payload.get("handle") == handle
    )

    def forge(**overrides: object) -> LegalAction:
        payload: dict[str, object] = {
            "operation": "play_slash_for_nanman",
            "response_to": trick_id,
            "root_trick_instance_id": trick_id,
            "target_id": "p2",
            "target_index": 0,
            "window_id": window_id,
            "state_hash": legal_state_hash,
            "handle": handle,
        }
        payload.update(overrides)
        return LegalAction(
            action_type=ActionType.PLAY_CARD,
            actor_id="p2",
            target_ids=("p2",),
            payload=payload,
            action_id="act_forged_nanman",
        )

    # 正向对照：forge() 基线负载与真实枚举负载逐字段一致
    assert forge().payload == real_action.payload
    # 非响应者提交（enumerate -> validate 入口）
    other = forge()
    with pytest.raises(
        InvalidActionError, match="动作角色与当前行动上下文不一致"
    ):
        validate_action(
            game.state,
            context,
            LegalAction(
                action_type=ActionType.PLAY_CARD,
                actor_id="p1",
                target_ids=("p2",),
                payload=dict(other.payload),
                action_id="act_wrong_actor",
            ),
            game.registry,
        )
    # 仅伪造 target_id：命中目标绑定校验
    with pytest.raises(
        InvalidActionError, match="绑定的目标不是当前目标"
    ):
        adapter.apply_action(game.state, context, forge(target_id="p1"))
    # 仅伪造 operation：命中动作负载校验
    with pytest.raises(
        InvalidActionError, match="响应动作负载无效"
    ):
        adapter.apply_action(
            game.state, context, forge(operation="play_jink_for_wanjian")
        )
    # 仅伪造目标索引：命中索引校验
    with pytest.raises(InvalidActionError, match="目标索引已过期"):
        adapter.apply_action(game.state, context, forge(target_index=7))
    # 仅伪造窗口：命中窗口校验
    with pytest.raises(InvalidActionError, match="响应窗口已过期"):
        adapter.apply_action(
            game.state, context, forge(window_id="stale_window")
        )
    # 仅伪造状态哈希：命中状态哈希校验
    with pytest.raises(
        InvalidActionError, match="状态哈希与当前状态不一致"
    ):
        adapter.apply_action(
            game.state, context, forge(state_hash="0" * 64)
        )
    # 仅伪造根锦囊：命中根锦囊校验
    with pytest.raises(
        InvalidActionError, match="根锦囊与当前结算不一致"
    ):
        adapter.apply_action(
            game.state, context, forge(root_trick_instance_id="forged_root")
        )
    # 仅伪造句柄：命中句柄校验（其他字段与真实枚举负载完全一致）
    forged_handle = "gr_" + "f" * 32
    only_handle = forge(handle=forged_handle)
    assert only_handle.payload == {**real_action.payload, "handle": forged_handle}
    with pytest.raises(
        InvalidActionError, match="句柄无效、伪造或已过期"
    ):
        adapter.apply_action(game.state, context, only_handle)


# ---------------------------------------------------------------------
# E. 【万箭齐发】
# ---------------------------------------------------------------------


def test_wanjian_auto_targets_exclude_user() -> None:
    game, _ = _wanjian_fixture()
    _use_group(game, "use_wanjian", WANJIAN)
    group = game.runtime.pending_group_trick
    assert group.target_sequence == ("p2",)
    assert "p1" not in group.target_sequence


def test_wanjian_respond_with_jink() -> None:
    game, trick_id = _wanjian_fixture(response_key=SHAN)
    jink_id = next(
        record.instance_id
        for record in game.formal_registry.instances_of(SHAN)
    )
    _use_group(game, "use_wanjian", WANJIAN)
    _close_trick_window(game)
    assert game.phase is ProductionPhase.WANJIAN_RESPONSE
    _play_group_response(game, "play_jink_for_wanjian", jink_id)
    assert game.phase is ProductionPhase.PLAY
    assert game.state.players_by_id["p2"].hp == 4
    played = _events_of(game, EventType.CARD_PLAYED)
    assert len(played) == 1
    assert played[0].card_instance_id == jink_id
    assert played[0].payload["response_to"] == trick_id
    assert played[0].payload["root_trick_instance_id"] == trick_id
    resolved = _events_of(game, EventType.GROUP_TARGET_RESOLVED)
    assert resolved[0].payload["result"] == "responded"


def test_wanjian_rejects_non_jink_response() -> None:
    game, _ = _wanjian_fixture(response_key=SHA)
    _use_group(game, "use_wanjian", WANJIAN)
    _close_trick_window(game)
    assert game.phase is ProductionPhase.WANJIAN_RESPONSE
    operations = {
        action.payload.get("operation") for action in game.legal_actions()
    }
    assert operations == {"play_jink_for_wanjian", "pass_wanjian_jink"}
    forged = LegalAction(
        action_type=ActionType.PLAY_CARD,
        actor_id="p2",
        target_ids=("p2",),
        payload={
            "operation": "play_jink_for_wanjian",
            "response_to": game.runtime.pending_group_trick.trick_instance_id,
            "root_trick_instance_id": (
                game.runtime.pending_group_trick.trick_instance_id
            ),
            "target_id": "p2",
            "target_index": 0,
            "window_id": "wanjian_forged_window",
            "state_hash": "0" * 64,
            "handle": "gr_" + "0" * 32,
        },
        action_id="act_forged_jink",
    )
    context = game._context()
    with pytest.raises(InvalidActionError):
        validate_action(game.state, context, forged, game.registry)
    adapter = game.formal_registry.adapter_for(WANJIAN)
    with pytest.raises(InvalidActionError):
        adapter.apply_action(game.state, context, forged)


def test_wanjian_pass_allowed_even_with_jink_in_hand() -> None:
    game, _ = _wanjian_fixture(response_key=SHAN)
    _use_group(game, "use_wanjian", WANJIAN)
    _close_trick_window(game)
    assert SHAN in _hand_keys(game, "p2")
    _step(game, _action(game, "pass_wanjian_jink"))
    assert game.phase is ProductionPhase.PLAY
    assert game.state.players_by_id["p2"].hp == 3
    assert not _events_of(game, EventType.CARD_PLAYED)


def test_wanjian_jink_is_played_not_used() -> None:
    game, _ = _wanjian_fixture(response_key=SHAN)
    jink_id = next(
        record.instance_id
        for record in game.formal_registry.instances_of(SHAN)
    )
    _use_group(game, "use_wanjian", WANJIAN)
    _close_trick_window(game)
    _play_group_response(game, "play_jink_for_wanjian", jink_id)
    played = _events_of(game, EventType.CARD_PLAYED)
    used = _events_of(game, EventType.CARD_USED)
    assert len(played) == 1
    assert played[0].payload["creates_card_used_event"] is False
    assert played[0].payload["creates_card_played_event"] is True
    assert played[0].payload["counts_for_use_or_play_total"] is True
    assert played[0].payload["response_action"] == "play"
    assert not any(event.card_instance_id == jink_id for event in used)
    assert not game.runtime.slash_used_counts


def test_wanjian_jink_full_zone_lifecycle() -> None:
    game, _ = _wanjian_fixture(response_key=SHAN)
    jink_id = next(
        record.instance_id
        for record in game.formal_registry.instances_of(SHAN)
    )
    _use_group(game, "use_wanjian", WANJIAN)
    _close_trick_window(game)
    _play_group_response(game, "play_jink_for_wanjian", jink_id)
    assert game.state.location_of(jink_id) == DISCARD_PILE
    moved = [
        event
        for event in _events_of(game, EventType.CARD_MOVED)
        if event.card_instance_id == jink_id
    ]
    assert [event.payload["reason"] for event in moved] == [
        "sgs_trick_wanjianqifa_response:enter_processing",
        "sgs_trick_wanjianqifa_response:leave_processing",
    ]


def test_wanjian_no_response_deals_one_damage() -> None:
    game, trick_id = _wanjian_fixture(target_hp=4)
    _use_group(game, "use_wanjian", WANJIAN)
    _close_trick_window(game)
    _step(game, _action(game, "pass_wanjian_jink"))
    assert game.state.players_by_id["p2"].hp == 3
    damages = _events_of(game, EventType.DAMAGE)
    assert len(damages) == 1
    assert damages[0].amount == 1
    assert damages[0].card_instance_id == trick_id


def test_wanjian_damage_source_type_and_root() -> None:
    game, trick_id = _wanjian_fixture(target_hp=4)
    _use_group(game, "use_wanjian", WANJIAN)
    _close_trick_window(game)
    _step(game, _action(game, "pass_wanjian_jink"))
    damage = _events_of(game, EventType.DAMAGE)[0]
    assert damage.damage_source == "p1"
    assert damage.damage_type == "无属性"
    assert damage.card_user == "p1"
    assert damage.payload["root_trick_instance_id"] == trick_id
    assert damage.payload["target_index"] == 0
    resolved = _events_of(game, EventType.GROUP_TARGET_RESOLVED)[0]
    assert resolved.payload["result"] == "damaged"
    assert resolved.payload["damage_amount"] == 1
    assert resolved.payload["damage_source_id"] == "p1"


def test_wanjian_respond_clears_window_and_affects_no_other_target() -> None:
    game, _ = _wanjian_fixture(response_key=SHAN)
    jink_id = next(
        record.instance_id
        for record in game.formal_registry.instances_of(SHAN)
    )
    _use_group(game, "use_wanjian", WANJIAN)
    _close_trick_window(game)
    _play_group_response(game, "play_jink_for_wanjian", jink_id)
    # 响应后：原锦囊进入弃牌堆、目标窗口与响应句柄全部清除
    assert game.phase is ProductionPhase.PLAY
    assert game.runtime.pending_group_trick is None
    assert game.runtime.group_response_handles == {}
    assert game.runtime.group_response_snapshot_digest is None
    assert game.state.players_by_id["p1"].hp == 4
    assert not _events_of(game, EventType.DAMAGE)


def test_wanjian_forged_responder_index_window_and_hash_fail() -> None:
    game, trick_id = _wanjian_fixture(response_key=SHAN)
    jink_id = next(
        record.instance_id
        for record in game.formal_registry.instances_of(SHAN)
    )
    _use_group(game, "use_wanjian", WANJIAN)
    _close_trick_window(game)
    handle = _group_handle_for(game, jink_id)
    context = game._context()
    adapter = game.formal_registry.adapter_for(WANJIAN)
    group = game.runtime.pending_group_trick
    window_id = (
        f"{group.trick_key}:{game.runtime.turn_number}:"
        f"{group.trick_instance_id}:gt{group.current_target_index}"
    )
    legal_state_hash = state_sha256(canonical_state_snapshot(game.state))
    real_action = next(
        action
        for action in game.legal_actions()
        if action.payload.get("operation") == "play_jink_for_wanjian"
        and action.payload.get("handle") == handle
    )

    def forge(**overrides: object) -> LegalAction:
        payload: dict[str, object] = {
            "operation": "play_jink_for_wanjian",
            "response_to": trick_id,
            "root_trick_instance_id": trick_id,
            "target_id": "p2",
            "target_index": 0,
            "window_id": window_id,
            "state_hash": legal_state_hash,
            "handle": handle,
        }
        payload.update(overrides)
        return LegalAction(
            action_type=ActionType.PLAY_CARD,
            actor_id="p2",
            target_ids=("p2",),
            payload=payload,
            action_id="act_forged_wanjian",
        )

    # 正向对照：forge() 基线负载与真实枚举负载逐字段一致
    assert forge().payload == real_action.payload
    # 独立用例一：其他字段合法，仅 target_id 错误
    with pytest.raises(
        InvalidActionError, match="绑定的目标不是当前目标"
    ):
        adapter.apply_action(game.state, context, forge(target_id="p1"))
    # 独立用例二：其他字段合法，仅 operation 错误
    with pytest.raises(
        InvalidActionError, match="响应动作负载无效"
    ):
        adapter.apply_action(
            game.state,
            context,
            forge(operation="play_slash_for_nanman"),
        )
    # 独立用例三：其他字段合法，仅 handle 错误
    forged_handle = "gr_" + "a" * 32
    only_handle = forge(handle=forged_handle)
    assert only_handle.payload == {**real_action.payload, "handle": forged_handle}
    with pytest.raises(
        InvalidActionError, match="句柄无效、伪造或已过期"
    ):
        adapter.apply_action(game.state, context, only_handle)
    # 独立用例四：非当前响应者提交（负载全部合法，仅 context.actor_id
    # 改为非当前响应者 p1）。经生产适配器入口（wanjian_response 阶段
    # 分派到 apply_group_response_play），该校验顺序中响应者检查先于
    # operation/target/window/state_hash/handle 等负载校验，故命中
    # “只有当前响应目标可以打出响应牌”这一层。
    non_responder_context = replace(context, actor_id="p1")
    with pytest.raises(
        InvalidActionError, match="只有当前响应目标可以打出响应牌"
    ):
        adapter.apply_action(game.state, non_responder_context, forge())
    # 仅伪造目标索引：命中索引校验
    with pytest.raises(InvalidActionError, match="目标索引已过期"):
        adapter.apply_action(game.state, context, forge(target_index=3))
    # 仅伪造窗口：命中窗口校验
    with pytest.raises(InvalidActionError, match="响应窗口已过期"):
        adapter.apply_action(
            game.state, context, forge(window_id="old_window")
        )
    # 仅伪造状态哈希：命中状态哈希校验
    with pytest.raises(
        InvalidActionError, match="状态哈希与当前状态不一致"
    ):
        adapter.apply_action(
            game.state, context, forge(state_hash="0" * 64)
        )
    # 仅伪造根锦囊：命中根锦囊校验
    with pytest.raises(
        InvalidActionError, match="根锦囊与当前结算不一致"
    ):
        adapter.apply_action(
            game.state, context, forge(root_trick_instance_id="forged")
        )
# ---------------------------------------------------------------------
# F. 【桃园结义】
# ---------------------------------------------------------------------


def test_taoyuan_auto_targets_are_wounded_characters() -> None:
    # 双方受伤：包含使用者自身，顺序为行动顺序（p1先、p2后）
    game, _ = _taoyuan_fixture(p1_hp=3, p2_hp=3)
    _use_group(game, "use_taoyuan", TAOYUAN)
    assert game.runtime.pending_group_trick.target_sequence == ("p1", "p2")
    # 只有使用者受伤：p2（满体力）不属于目标
    game2, _ = _taoyuan_fixture(p1_hp=3, p2_hp=4)
    _use_group(game2, "use_taoyuan", TAOYUAN)
    assert game2.runtime.pending_group_trick.target_sequence == ("p1",)


def test_taoyuan_includes_user_according_to_knowledge() -> None:
    game, _ = _taoyuan_fixture(p1_hp=2, p2_hp=4)
    _use_group(game, "use_taoyuan", TAOYUAN)
    sequence = game.runtime.pending_group_trick.target_sequence
    assert sequence == ("p1",)
    assert "p1" in sequence


def test_taoyuan_full_hp_character_is_not_a_target() -> None:
    game, _ = _taoyuan_fixture(p1_hp=3, p2_hp=4)
    _use_group(game, "use_taoyuan", TAOYUAN)
    _close_trick_window(game)
    recovers = _events_of(game, EventType.HP_RECOVER)
    assert len(recovers) == 1
    assert recovers[0].target_ids == ("p1",)
    assert game.state.players_by_id["p2"].hp == 4
    resolved = _events_of(game, EventType.GROUP_TARGET_RESOLVED)
    assert [event.target_ids for event in resolved] == [("p1",)]


def test_taoyuan_cannot_be_used_without_any_wounded_target() -> None:
    game = _fresh(3)
    trick_id = next(
        record.instance_id
        for record in game.formal_registry.instances_of(TAOYUAN)
    )
    _move_to_hand(game, trick_id, "p1")
    action = _action(game, "use_taoyuan", card_key=TAOYUAN)
    assert action is None
    context = game._context()
    adapter = game.formal_registry.adapter_for(TAOYUAN)
    assert adapter.enumerate_legal_actions(game.state, context) == ()


def test_taoyuan_each_wounded_target_recovers_one() -> None:
    game, _ = _taoyuan_fixture(p1_hp=2, p2_hp=2)
    _use_group(game, "use_taoyuan", TAOYUAN)
    _close_trick_window(game)
    assert game.state.players_by_id["p1"].hp == 3
    _close_trick_window(game)
    assert game.state.players_by_id["p2"].hp == 3
    recovers = _events_of(game, EventType.HP_RECOVER)
    assert [event.target_ids[0] for event in recovers] == ["p1", "p2"]
    assert [event.payload["amount"] for event in recovers] == [1, 1]
    assert [event.payload["actual_amount"] for event in recovers] == [1, 1]


def test_taoyuan_recovery_never_exceeds_max_hp() -> None:
    game, _ = _taoyuan_fixture(p1_hp=3, p2_hp=3)
    _use_group(game, "use_taoyuan", TAOYUAN)
    _close_trick_window(game)
    _close_trick_window(game)
    assert game.state.players_by_id["p1"].hp == 4
    assert game.state.players_by_id["p2"].hp == 4
    assert game.state.players_by_id["p1"].hp <= game.state.players_by_id["p1"].max_hp
    assert game.state.players_by_id["p2"].hp <= game.state.players_by_id["p2"].max_hp


def test_taoyuan_full_hp_target_produces_no_fake_recovery() -> None:
    game, _ = _taoyuan_fixture(p1_hp=3, p2_hp=4)
    _use_group(game, "use_taoyuan", TAOYUAN)
    _close_trick_window(game)
    assert game.phase is ProductionPhase.PLAY
    assert not any(
        event.target_ids == ("p2",)
        for event in _events_of(game, EventType.HP_RECOVER)
    )
    assert game.state.players_by_id["p2"].hp == 4


def test_taoyuan_cancelled_target_does_not_recover() -> None:
    game, _ = _taoyuan_fixture(p1_hp=3, p2_hp=3)
    wuxie_id = next(
        record.instance_id
        for record in game.formal_registry.instances_of(WUXIE)
    )
    _move_to_hand(game, wuxie_id, "p2")
    _use_group(game, "use_taoyuan", TAOYUAN)
    _pass_trick(game)
    _step(game, _action(game, "use_wuxie", card_key=WUXIE))
    _pass_trick(game)
    _pass_trick(game)
    assert not any(
        event.target_ids == ("p1",)
        for event in _events_of(game, EventType.HP_RECOVER)
    )
    assert game.state.players_by_id["p1"].hp == 3


def test_taoyuan_cancel_does_not_affect_next_target() -> None:
    game, _ = _taoyuan_fixture(p1_hp=3, p2_hp=2)
    wuxie_id = next(
        record.instance_id
        for record in game.formal_registry.instances_of(WUXIE)
    )
    _move_to_hand(game, wuxie_id, "p2")
    _use_group(game, "use_taoyuan", TAOYUAN)
    _pass_trick(game)
    _step(game, _action(game, "use_wuxie", card_key=WUXIE))
    _pass_trick(game)
    _pass_trick(game)
    _close_trick_window(game)
    assert game.state.players_by_id["p1"].hp == 3
    assert game.state.players_by_id["p2"].hp == 3
    resolved = _events_of(game, EventType.GROUP_TARGET_RESOLVED)
    assert [event.payload["result"] for event in resolved] == [
        "cancelled",
        "recovered",
    ]


def test_taoyuan_double_wuxie_restores_recovery() -> None:
    game, _ = _taoyuan_fixture(p1_hp=3, p2_hp=3)
    wuxie_ids = [
        record.instance_id
        for record in game.formal_registry.instances_of(WUXIE)
    ]
    _move_to_hand(game, wuxie_ids[0], "p1")
    _move_to_hand(game, wuxie_ids[1], "p2")
    _use_group(game, "use_taoyuan", TAOYUAN)
    _step(game, _action(game, "use_wuxie", card_key=WUXIE))
    _step(game, _action(game, "use_wuxie", card_key=WUXIE))
    _pass_trick(game)
    _pass_trick(game)
    assert game.state.players_by_id["p1"].hp == 4
    _close_trick_window(game)
    assert game.state.players_by_id["p2"].hp == 4
    recovers = _events_of(game, EventType.HP_RECOVER)
    assert [event.target_ids[0] for event in recovers] == ["p1", "p2"]


def test_taoyuan_two_targets_resolve_sequentially() -> None:
    game, trick_id = _taoyuan_fixture(p1_hp=2, p2_hp=3)
    _use_group(game, "use_taoyuan", TAOYUAN)
    _close_trick_window(game)
    assert game.state.players_by_id["p1"].hp == 3
    assert game.phase is ProductionPhase.TRICK_RESPONSE
    _close_trick_window(game)
    assert game.state.players_by_id["p2"].hp == 4
    recovers = _events_of(game, EventType.HP_RECOVER)
    assert [event.payload["target_index"] for event in recovers] == [0, 1]
    for event in recovers:
        assert event.card_instance_id == trick_id
        assert event.payload["root_trick_instance_id"] == trick_id
        assert event.payload["reason"] == "taoyuan_jieyi_effect"
        assert event.payload["user_id"] == "p1"


def test_taoyuan_self_and_other_share_one_target_queue() -> None:
    game, trick_id = _taoyuan_fixture(p1_hp=3, p2_hp=3)
    _use_group(game, "use_taoyuan", TAOYUAN)
    group = game.runtime.pending_group_trick
    assert group.target_sequence == ("p1", "p2")
    assert group.trick_instance_id == trick_id
    _close_trick_window(game)
    # 第二目标仍由同一根锦囊状态推进，不另起一套自身回复流程
    group2 = game.runtime.pending_group_trick
    assert group2 is not None
    assert group2.trick_instance_id == trick_id
    assert group2.current_target_index == 1
    _close_trick_window(game)
    resolved = _events_of(game, EventType.GROUP_TARGET_RESOLVED)
    assert all(
        event.payload["root_trick_instance_id"] == trick_id
        for event in resolved
    )
    assert [event.payload["target_index"] for event in resolved] == [0, 1]
    assert len(_events_of(game, EventType.CARD_USED)) == 1


def test_taoyuan_forged_recovery_values_and_targets_fail() -> None:
    game, trick_id = _taoyuan_fixture(p1_hp=3, p2_hp=3)
    context = game._context()
    adapter = game.formal_registry.adapter_for(TAOYUAN)
    # 玩家不能提交目标列表
    forged_targets = LegalAction(
        action_type=ActionType.USE_CARD,
        actor_id="p1",
        card_instance_id=trick_id,
        target_ids=("p2",),
        payload={
            "operation": "use_taoyuan",
            "card_key": TAOYUAN,
            "card_name": "桃园结义",
        },
        action_id="act_taoyuan_targets",
    )
    with pytest.raises(InvalidActionError):
        validate_action(game.state, context, forged_targets, game.registry)
    with pytest.raises(InvalidActionError):
        adapter.apply_action(game.state, context, forged_targets)
    # 玩家不能携带自选回复值
    forged_amount = LegalAction(
        action_type=ActionType.USE_CARD,
        actor_id="p1",
        card_instance_id=trick_id,
        target_ids=(),
        payload={
            "operation": "use_taoyuan",
            "card_key": TAOYUAN,
            "card_name": "桃园结义",
            "recover_amount": 2,
        },
        action_id="act_taoyuan_amount",
    )
    with pytest.raises(InvalidActionError):
        validate_action(game.state, context, forged_amount, game.registry)
    # 使用后原动作过期：实体牌已离开手牌，不能重复使用
    _use_group(game, "use_taoyuan", TAOYUAN)
    stale = _action(game, "use_taoyuan", card_key=TAOYUAN)
    assert stale is None or stale.card_instance_id != trick_id


# ---------------------------------------------------------------------
# G. 严格回放与隐藏信息
# ---------------------------------------------------------------------

_NANMAN_REPLAY_SPECS = [
    {"operation": "use_nanman", "card_key": NANMAN},
    {"operation": "pass_trick_response"},
    {"operation": "pass_trick_response"},
    {"operation": "play_slash_for_nanman"},
]

_WANJIAN_REPLAY_SPECS = [
    {"operation": "use_wanjian", "card_key": WANJIAN},
    {"operation": "pass_trick_response"},
    {"operation": "pass_trick_response"},
    {"operation": "pass_wanjian_jink"},
]

_TAOYUAN_REPLAY_SPECS = [
    {"operation": "use_taoyuan", "card_key": TAOYUAN},
    {"operation": "pass_trick_response"},
    {"operation": "pass_trick_response"},
    {"operation": "pass_trick_response"},
    {"operation": "pass_trick_response"},
]


@pytest.fixture(scope="module")
def nanman_replay_record() -> ProductionReexecutionReplay:
    return record_reference_production_batch(
        seed=15,
        controller=ScriptedBatchController(_NANMAN_REPLAY_SPECS),
    )


@pytest.fixture(scope="module")
def wanjian_replay_record() -> ProductionReexecutionReplay:
    return record_reference_production_batch(
        seed=8,
        controller=ScriptedBatchController(_WANJIAN_REPLAY_SPECS),
    )


@pytest.fixture(scope="module")
def taoyuan_replay_record() -> ProductionReexecutionReplay:
    return record_reference_production_batch(
        seed=21,
        player_hp=(3, 3),
        controller=ScriptedBatchController(_TAOYUAN_REPLAY_SPECS),
    )


def test_nanman_replay_reexecutes(nanman_replay_record: ProductionReexecutionReplay) -> None:
    record = nanman_replay_record
    result = reexecute_production_replay(record)
    assert result.verified is True
    played = [
        event
        for event in record.events
        if event.get("event_type") == "card_played"
        and event.get("payload", {}).get("purpose")
        == "sgs_trick_nanmanruqin_response"
    ]
    assert len(played) == 1
    assert played[0]["payload"]["response_action"] == "play"
    resolved = [
        event
        for event in record.events
        if event.get("event_type") == "group_target_resolved"
    ]
    assert len(resolved) == 1
    assert resolved[0]["payload"]["result"] == "responded"


def test_wanjian_replay_reexecutes(wanjian_replay_record: ProductionReexecutionReplay) -> None:
    record = wanjian_replay_record
    result = reexecute_production_replay(record)
    assert result.verified is True
    damages = [
        event
        for event in record.events
        if event.get("event_type") == "damage"
        and event.get("card_key") == WANJIAN
    ]
    assert len(damages) == 1
    assert damages[0]["damage_type"] == "无属性"
    assert damages[0]["damage_source"] == "p1"
    assert damages[0]["card_key"] == WANJIAN
    resolved = [
        event
        for event in record.events
        if event.get("event_type") == "group_target_resolved"
        and event.get("card_key") == WANJIAN
    ]
    assert resolved[0]["payload"]["result"] == "damaged"


def test_taoyuan_replay_reexecutes(taoyuan_replay_record: ProductionReexecutionReplay) -> None:
    record = taoyuan_replay_record
    result = reexecute_production_replay(record)
    assert result.verified is True
    recovers = [
        event
        for event in record.events
        if event.get("event_type") == "hp_recover"
        and event.get("payload", {}).get("reason") == "taoyuan_jieyi_effect"
    ]
    assert len(recovers) == 2
    assert [event["target_ids"][0] for event in recovers] == ["p1", "p2"]
    assert [event["payload"]["amount"] for event in recovers] == [1, 1]


def _load_tampered(record: ProductionReexecutionReplay) -> dict[str, object]:
    tampered = copy.deepcopy(record.to_dict())
    tampered["record_sha256"] = ""
    return tampered


def test_replay_tamper_target_order_fails(
    taoyuan_replay_record: ProductionReexecutionReplay,
) -> None:
    record = taoyuan_replay_record
    tampered = _load_tampered(record)
    for decision in tampered["decisions"]:
        metadata = decision.get("context", {}).get("metadata", {})
        group = metadata.get("pending_group_trick")
        if group and group.get("target_sequence") == ["p1", "p2"]:
            group["target_sequence"] = ["p2", "p1"]
            break
    else:
        raise AssertionError("回放决策中必须存在桃园目标序列上下文")
    rebuilt = ProductionReexecutionReplay.from_dict(tampered)
    with pytest.raises(ProductionReplayDivergenceError):
        reexecute_production_replay(rebuilt)


def test_replay_tamper_current_target_index_fails(
    nanman_replay_record: ProductionReexecutionReplay,
) -> None:
    record = nanman_replay_record
    tampered = _load_tampered(record)
    slash_decision = next(
        decision
        for decision in tampered["decisions"]
        if decision["chosen_action"].get("payload", {}).get("operation")
        == "play_slash_for_nanman"
    )
    slash_decision["chosen_action"]["payload"]["target_index"] = 99
    rebuilt = ProductionReexecutionReplay.from_dict(tampered)
    with pytest.raises(ProductionReplayDivergenceError):
        reexecute_production_replay(rebuilt)


def test_replay_tamper_response_card_handle_fails(
    nanman_replay_record: ProductionReexecutionReplay,
) -> None:
    record = nanman_replay_record
    tampered = _load_tampered(record)
    slash_decision = next(
        decision
        for decision in tampered["decisions"]
        if decision["chosen_action"].get("payload", {}).get("operation")
        == "play_slash_for_nanman"
    )
    slash_decision["chosen_action"]["payload"]["handle"] = "gr_" + "0" * 32
    rebuilt = ProductionReexecutionReplay.from_dict(tampered)
    with pytest.raises(ProductionReplayDivergenceError):
        reexecute_production_replay(rebuilt)


def test_replay_tamper_damage_source_or_type_fails(
    wanjian_replay_record: ProductionReexecutionReplay,
) -> None:
    record = wanjian_replay_record
    tampered = _load_tampered(record)
    damage_event = next(
        event
        for event in tampered["events"]
        if event.get("event_type") == "damage"
        and event.get("card_key") == WANJIAN
    )
    damage_event["damage_source"] = "p2"
    with pytest.raises(ProductionReplayFormatError):
        ProductionReexecutionReplay.from_dict(tampered)

    tampered = _load_tampered(record)
    damage_event = next(
        event
        for event in tampered["events"]
        if event.get("event_type") == "damage"
        and event.get("card_key") == WANJIAN
    )
    damage_event["damage_type"] = "火属性"
    with pytest.raises(ProductionReplayFormatError):
        ProductionReexecutionReplay.from_dict(tampered)


def test_replay_tamper_taoyuan_recovery_value_fails(
    taoyuan_replay_record: ProductionReexecutionReplay,
) -> None:
    record = taoyuan_replay_record
    tampered = _load_tampered(record)
    recover_event = next(
        event
        for event in tampered["events"]
        if event.get("event_type") == "hp_recover"
    )
    recover_event["payload"]["amount"] = 2
    recover_event["payload"]["actual_amount"] = 2
    with pytest.raises(ProductionReplayFormatError):
        ProductionReexecutionReplay.from_dict(tampered)


def test_replay_delete_target_event_fails(
    taoyuan_replay_record: ProductionReexecutionReplay,
) -> None:
    record = taoyuan_replay_record
    tampered = _load_tampered(record)
    tampered["events"] = [
        event
        for event in tampered["events"]
        if not (
            event.get("event_type") == "group_target_resolved"
            and event.get("payload", {}).get("target_index") == 1
        )
    ]
    with pytest.raises(ProductionReplayFormatError):
        ProductionReexecutionReplay.from_dict(tampered)


def test_replay_duplicate_target_event_fails(
    taoyuan_replay_record: ProductionReexecutionReplay,
) -> None:
    record = taoyuan_replay_record
    tampered = _load_tampered(record)
    target_event = next(
        event
        for event in tampered["events"]
        if event.get("event_type") == "group_target_resolved"
    )
    position = tampered["events"].index(target_event)
    tampered["events"].insert(position, copy.deepcopy(target_event))
    with pytest.raises(ProductionReplayFormatError):
        ProductionReexecutionReplay.from_dict(tampered)


def test_player_visible_replay_leaks_no_unplayed_hand_cards(
    nanman_replay_record: ProductionReexecutionReplay,
) -> None:
    record = nanman_replay_record
    view = record.player_visible_payload()
    assert view["player_visible"] is True
    assert "authoritative_private" not in view
    blob = json.dumps(view, ensure_ascii=False)
    secret = record.authoritative_private["session_secret_hex"]
    assert secret not in blob
    # 同种子重建牌局得到相同初始手牌；从未公开化的目标手牌实体不得因群体
    # 响应机制泄露：事件中只允许公共发牌记录，决策材料中不得出现（与既有
    # 火攻批次玩家可见导出约定一致）。
    publicized_ids = {
        event["card_instance_id"]
        for event in record.events
        if event.get("event_type")
        in ("card_played", "card_used", "card_revealed", "card_recast")
    }
    # CP-04O：弃牌阶段公开置入弃牌堆的实体属于合法公开信息
    publicized_ids.update(
        event["card_instance_id"]
        for event in record.events
        if event.get("event_type")
        in ("card_moved", "card_lost", "card_discarded")
        and event.get("payload", {}).get("reason") == "discard_phase"
    )
    # CP-04O：弃牌阶段使p2初始手牌全部合法公开（本记录p2使用3张并弃置
    # 1张）；改用记录决策重执行后的最终手牌（从未使用/弃置/展示的实体）
    # 验证隐私边界，避免断言退化为空集自证。
    private = record.authoritative_private
    replay_game = ProductionBasicCardBatch(
        seed=15,
        session_id=private["session_id"],
        session_secret=bytes.fromhex(private["session_secret_hex"]),
    )
    for decision in record.decisions:
        replay_game.step(
            BatchActionIdController(decision["chosen_action_id"])
        )
    final_p2_hand = set(
        replay_game.state.card_ids_in(ZoneRef.hand("p2"))
    )
    never_publicized = final_p2_hand - publicized_ids
    assert never_publicized, "p2必须存在从未公开化的手牌"
    for instance_id in never_publicized:
        occurrences = [
            event
            for event in view["events"]
            if event.get("card_instance_id") == instance_id
        ]
        public_deal = [
            event
            for event in occurrences
            if event.get("event_type") == "card_gained"
            and event.get("payload", {}).get("reason") == "initial_hand"
        ]
        # CP-04L：初始发牌属于非公开获得，公共/旁观者视图不暴露实体ID
        assert not occurrences, f"实体{instance_id}在公共视图中被泄露"
        # 隐私边界：未公开化的手牌不得出现在其所有者之外的材料中。
        # 所有者自己在出牌阶段的合法动作会枚举自己的手牌（与【杀】
        # 【闪】【桃】【酒】及全部已接入锦囊的既有生产口径一致），
        # 属于自信息，不构成跨玩家泄露；响应类窗口继续以不透明句柄
        # 保护，不允许任何未公开化实体进入他人决策材料。
        leaked_outside_owner = [
            decision
            for decision in view["decisions"]
            if decision.get("context", {}).get("actor_id") != "p2"
            and "chosen_action" in decision
            and instance_id
            in json.dumps(
                [
                    decision["chosen_action"],
                    *decision.get("legal_actions", []),
                ],
                ensure_ascii=False,
            )
        ]
        assert not leaked_outside_owner, (
            f"实体{instance_id}在非所有者决策材料中被泄露"
        )
    # B1-b：公共视图下所有非行动者决策均已省略私有动作
    for decision in view["decisions"]:
        assert "chosen_action" not in decision
        assert "legal_actions" not in decision
    # 双视角：所有者p2视图中保留自己的初始发牌实例记录
    owner_view = record.player_visible_payload(viewer_id="p2")
    for instance_id in never_publicized:
        assert any(
            event.get("event_type") == "card_gained"
            and event.get("card_instance_id") == instance_id
            for event in owner_view["events"]
        ), f"实体{instance_id}在所有者视图缺少获得记录"
    # 对手p1视图不得包含p2未公开化的手牌
    opponent_view = record.player_visible_payload(viewer_id="p1")
    for instance_id in never_publicized:
        assert not any(
            event.get("card_instance_id") == instance_id
            for event in opponent_view["events"]
        ), f"实体{instance_id}在对手视图中被泄露"
    # 公共视图已省略全部私有动作（B1-b）
    for decision in view["decisions"]:
        assert "chosen_action" not in decision
        assert "legal_actions" not in decision
    # 行动者本人视图的群体响应动作负载只含固定键集，不携带牌面或实体ID
    for viewer_id in ("p1", "p2"):
        actor_view = record.player_visible_payload(viewer_id=viewer_id)
        for decision in actor_view["decisions"]:
            if decision.get("context", {}).get("actor_id") != viewer_id:
                continue
            for action in [decision.get("chosen_action")]:
                operation = action.get("payload", {}).get("operation")
                if operation in (
                    "play_slash_for_nanman",
                    "play_jink_for_wanjian",
                ):
                    assert set(action["payload"]) == (
                        _GROUP_RESPONSE_PAYLOAD_KEYS
                    )
                    assert action.get("card_instance_id") is None
                    assert action.get("skill_id") is None
            for action in decision.get("legal_actions", []):
                operation = action.get("payload", {}).get("operation")
                if operation in (
                    "play_slash_for_nanman",
                    "play_jink_for_wanjian",
                ):
                    assert set(action["payload"]) == (
                        _GROUP_RESPONSE_PAYLOAD_KEYS
                    )
                    assert action.get("card_instance_id") is None


def test_authoritative_replay_reexecutes_rather_than_restores(
    wanjian_replay_record: ProductionReexecutionReplay,
) -> None:
    record = wanjian_replay_record
    assert record.header["test_only"] is False
    assert record.header["formal_result"] is False
    assert len(record.decisions) > 0
    result = reexecute_production_replay(record)
    assert result.verified is True
    assert result.decision_count == len(record.decisions)
    assert result.event_count == len(record.events)
    assert result.final_execution_hash == record.outcome["final_execution_hash"]
    assert result.final_game_state_hash == (
        record.outcome["final_game_state_hash"]
    )
