# -*- coding: utf-8 -*-
"""正式160张牌堆最小普通锦囊垂直切片的生产验收测试。

本文件覆盖【无中生有】与【无懈可击】的正式生产路径：
- 全部动作都经过 enumerate_legal_actions -> validate_action -> apply_action；
- 使用正式160张牌堆CSV建立的 FormalCardRegistry 与权威核心会话；
- 实体牌必须经历真实牌区移动（hand -> processing -> discard）；
- 不使用固定概率、固定收益、fallback 或自证式断言。
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
from scripts.sgs_engine.events import EventType
from scripts.sgs_engine.model import (
    DISCARD_PILE,
    DRAW_PILE,
    PROCESSING_ZONE,
    ZoneRef,
)
from scripts.sgs_engine.production_batch import (
    BatchActionIdController,
    BatchReferenceController,
    ProductionBasicCardBatch,
    ProductionBatchFinishedError,
    ProductionPhase,
    ScriptedBatchController,
)
from scripts.sgs_engine.production_cards import (
    PRODUCTION_BASIC_CARD_KEYS,
    PRODUCTION_TRICK_KEYS,
    FormalCardRegistry,
    WuxiekejiAdapter,
    WuzhongshengyouAdapter,
)
from scripts.sgs_engine.production_replay import (
    ProductionReplayDivergenceError,
    ProductionReplayFormatError,
    ProductionReexecutionReplay,
    record_reference_production_batch,
    reexecute_production_replay,
)
from scripts.sgs_engine.replay import sha256_value

WUZHONG = "sgs_trick_wuzhongshengyou"
WUXIE = "sgs_trick_wuxiekeji"


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


def _use_wuzhong(game: ProductionBasicCardBatch) -> str:
    action = _action(game, "use_wuzhong", card_key=WUZHONG)
    assert action is not None, "出牌阶段必须能枚举【无中生有】动作"
    trick_id = action.card_instance_id
    assert trick_id is not None
    _step(game, action)
    return trick_id


def _close_window_with_passes(game: ProductionBasicCardBatch) -> None:
    for _ in range(2):
        _step(game, _action(game, "pass_trick_response"))


# ---------------------------------------------------------------------
# 1-2 正式CSV实体与生产适配器绑定
# ---------------------------------------------------------------------


def test_wuzhong_entities_bind_to_production_adapter() -> None:
    game = ProductionBasicCardBatch(seed=3)
    registry = game.formal_registry
    assert isinstance(registry, FormalCardRegistry)
    assert WUZHONG in PRODUCTION_TRICK_KEYS
    assert WUZHONG in registry.implemented_card_keys
    records = registry.instances_of(WUZHONG)
    assert len(records) == 4
    assert len({record.instance_id for record in records}) == 4
    assert {record.suit for record in records} == {"♥"}
    adapter = registry.adapter_for(WUZHONG)
    assert isinstance(adapter, WuzhongshengyouAdapter)
    assert adapter.implemented is True
    assert adapter.tested is True
    assert adapter.production_adapter is True
    spec = adapter.rule_spec()
    assert spec["card_key"] == WUZHONG
    assert spec["use_timing"] == "own_play_phase"
    assert spec["target_filter"] == "self"
    assert spec["nullification_eligible"] is True
    assert spec["movement_lifecycle"] == "hand->processing->discard"
    for record in records:
        card = game.state.cards_by_id[record.instance_id]
        assert card.card_key == WUZHONG
        assert card.card_name == "无中生有"
        assert card.card_type == "锦囊牌"
        assert record.rank
        assert record.instance_id in registry.instance_ids


def test_wuxie_entities_bind_to_production_adapter() -> None:
    game = ProductionBasicCardBatch(seed=3)
    registry = game.formal_registry
    assert WUXIE in PRODUCTION_TRICK_KEYS
    assert WUXIE in registry.implemented_card_keys
    records = registry.instances_of(WUXIE)
    assert len(records) == 7
    assert len({record.instance_id for record in records}) == 7
    assert {record.suit for record in records} == {"♦", "♣", "♥", "♠"}
    adapter = registry.adapter_for(WUXIE)
    assert isinstance(adapter, WuxiekejiAdapter)
    assert adapter.implemented is True
    assert adapter.tested is True
    assert adapter.production_adapter is True
    spec = adapter.rule_spec()
    assert spec["card_key"] == WUXIE
    assert spec["use_timing"] == "trick_response_window"
    assert spec["nullification_eligible"] is True
    assert spec["movement_lifecycle"] == "hand->processing->discard"
    for record in records:
        card = game.state.cards_by_id[record.instance_id]
        assert card.card_key == WUXIE
        assert card.card_name == "无懈可击"
        assert card.card_type == "锦囊牌"
        assert record.rank
        assert record.instance_id in registry.instance_ids


# ---------------------------------------------------------------------
# 3-4 【无中生有】响应窗口与放弃响应
# ---------------------------------------------------------------------


def test_wuzhong_use_establishes_nullification_window() -> None:
    game = ProductionBasicCardBatch(seed=3)
    assert game.current_player_id == "p1"
    action = _action(game, "use_wuzhong", card_key=WUZHONG)
    assert action is not None
    assert action.target_ids == ("p1",)
    trick_id = _use_wuzhong(game)
    assert game.phase is ProductionPhase.TRICK_RESPONSE
    runtime = game.runtime
    assert runtime.pending_trick is not None
    assert runtime.pending_trick.user_id == "p1"
    assert runtime.pending_trick.target_id == "p1"
    assert runtime.pending_trick.trick_instance_id == trick_id
    assert runtime.pending_trick.trick_key == WUZHONG
    assert runtime.trick_effect_active is True
    assert runtime.trick_response_order == ("p1", "p2")
    assert runtime.trick_response_index == 0
    assert runtime.response_window_id is not None
    assert runtime.response_window_id.startswith("trick:")
    assert runtime.response_window_order == ("p1",)
    assert game.state.location_of(trick_id) == PROCESSING_ZONE
    used = [
        event
        for event in game.events
        if event.event_type is EventType.CARD_USED
        and event.card_instance_id == trick_id
    ]
    assert len(used) == 1
    assert used[0].payload.get("purpose") == "draw_2"
    assert used[0].card_user == "p1"
    assert used[0].target_ids == ("p1",)


def test_all_passes_close_window_and_wuzhong_draws_two() -> None:
    game = ProductionBasicCardBatch(seed=3)
    trick_id = _use_wuzhong(game)
    hand_after_use = len(game.state.card_ids_in(ZoneRef.hand("p1")))
    _close_window_with_passes(game)
    assert game.phase is ProductionPhase.PLAY
    assert game.runtime.pending_trick is None
    assert len(game.state.card_ids_in(ZoneRef.hand("p1"))) == hand_after_use + 2
    assert game.state.location_of(trick_id) == DISCARD_PILE
    used_sequence = next(
        event.sequence
        for event in game.events
        if event.event_type is EventType.CARD_USED
        and event.card_instance_id == trick_id
    )
    gained_after_use = [
        event
        for event in game.events
        if event.event_type is EventType.CARD_GAINED
        and event.sequence > used_sequence
    ]
    assert len(gained_after_use) == 2
    assert all(event.target_ids == ("p1",) for event in gained_after_use)
    resolved = [
        event
        for event in game.events
        if event.event_type is EventType.CARD_MOVED
        and event.card_instance_id == trick_id
        and event.payload.get("reason") == "wuzhong_effect_resolved"
    ]
    assert len(resolved) == 1
    cancelled = [
        event
        for event in game.events
        if event.event_type is EventType.CARD_EFFECT_CANCELLED
        and event.card_instance_id == trick_id
    ]
    assert cancelled == []


# ---------------------------------------------------------------------
# 5-7 【无懈可击】无效路径与实体生命周期
# ---------------------------------------------------------------------


def test_wuxie_nullifies_wuzhong_and_blocks_draw() -> None:
    game = ProductionBasicCardBatch(seed=3)
    trick_id = _use_wuzhong(game)
    hand_after_use = len(game.state.card_ids_in(ZoneRef.hand("p1")))
    _step(game, _action(game, "pass_trick_response"))
    wuxie = _action(game, "use_wuxie")
    assert wuxie is not None
    assert wuxie.actor_id == "p2"
    _step(game, wuxie)
    _step(game, _action(game, "pass_trick_response"))
    _step(game, _action(game, "pass_trick_response"))
    assert game.phase is ProductionPhase.PLAY
    assert len(game.state.card_ids_in(ZoneRef.hand("p1"))) == hand_after_use
    cancelled = [
        event
        for event in game.events
        if event.event_type is EventType.CARD_EFFECT_CANCELLED
        and event.card_instance_id == trick_id
    ]
    assert len(cancelled) == 1
    assert cancelled[0].card_key == WUZHONG
    assert cancelled[0].payload.get("reason") == "nullified_by_wuxie"
    assert game.state.location_of(trick_id) == DISCARD_PILE


def test_nullified_wuzhong_still_records_card_used() -> None:
    game = ProductionBasicCardBatch(seed=3)
    trick_id = _use_wuzhong(game)
    _step(game, _action(game, "pass_trick_response"))
    _step(game, _action(game, "use_wuxie"))
    _step(game, _action(game, "pass_trick_response"))
    _step(game, _action(game, "pass_trick_response"))
    used = [
        event
        for event in game.events
        if event.event_type is EventType.CARD_USED
        and event.card_instance_id == trick_id
    ]
    assert len(used) == 1
    assert used[0].payload.get("purpose") == "draw_2"
    assert used[0].card_user == "p1"
    assert used[0].card_key == WUZHONG


def test_wuxie_card_completes_zone_lifecycle() -> None:
    game = ProductionBasicCardBatch(seed=3)
    _use_wuzhong(game)
    _step(game, _action(game, "pass_trick_response"))
    wuxie = _action(game, "use_wuxie")
    assert wuxie is not None
    wuxie_id = wuxie.card_instance_id
    assert game.state.location_of(wuxie_id) == ZoneRef.hand("p2")
    _step(game, wuxie)
    moves = [
        event
        for event in game.events
        if event.event_type is EventType.CARD_MOVED
        and event.card_instance_id == wuxie_id
    ]
    assert [event.payload.get("reason") for event in moves] == [
        "wuxie_response:enter_processing",
        "wuxie_response:leave_processing",
    ]
    assert moves[0].payload["source"]["kind"] == "hand"
    assert moves[0].payload["source"]["owner_id"] == "p2"
    assert moves[0].payload["destination"]["kind"] == "processing"
    assert moves[1].payload["source"]["kind"] == "processing"
    assert moves[1].payload["destination"]["kind"] == "discard_pile"
    assert game.state.location_of(wuxie_id) == DISCARD_PILE


# ---------------------------------------------------------------------
# 8-9 连续【无懈可击】响应
# ---------------------------------------------------------------------


def test_three_consecutive_wuxie_chain_targets_and_nullification() -> None:
    game = ProductionBasicCardBatch(seed=292)
    controller = ScriptedBatchController(
        [
            {"operation": "use_slash"},
            {"operation": "pass_slash_response"},
            {"operation": "end_play_phase"},
            {"operation": "end_turn"},
            {"operation": "use_wuzhong"},
            {"operation": "pass_trick_response"},
            {"operation": "use_wuxie"},
            {"operation": "pass_trick_response"},
            {"operation": "use_wuxie"},
            {"operation": "pass_trick_response"},
            {"operation": "use_wuxie"},
        ]
    )
    for _ in range(11):
        game.step(controller)
    trick_id = next(
        event.card_instance_id
        for event in game.events
        if event.event_type is EventType.CARD_USED
        and event.card_key == WUZHONG
    )
    used_wuxie = [
        event
        for event in game.events
        if event.event_type is EventType.CARD_USED and event.card_key == WUXIE
    ]
    assert len(used_wuxie) == 3
    assert used_wuxie[0].payload.get("response_to") == trick_id
    assert used_wuxie[1].payload.get("response_to") == used_wuxie[0].card_instance_id
    assert used_wuxie[2].payload.get("response_to") == used_wuxie[1].card_instance_id
    for event in used_wuxie:
        assert event.payload.get("root_trick_instance_id") == trick_id
        assert event.payload.get("creates_card_played_event") is False
        assert event.payload.get("counts_for_use_or_play_total") is True
    assert game.runtime.trick_effect_active is False
    _close_window_with_passes(game)
    assert game.phase is ProductionPhase.PLAY
    assert [
        event
        for event in game.events
        if event.event_type is EventType.CARD_EFFECT_CANCELLED
        and event.card_instance_id == trick_id
    ]
    assert game.state.location_of(trick_id) == DISCARD_PILE
    for event in used_wuxie:
        assert game.state.location_of(event.card_instance_id) == DISCARD_PILE


def test_two_consecutive_wuxie_keep_effect_with_correct_chain() -> None:
    game = ProductionBasicCardBatch(seed=396)
    trick_id = _use_wuzhong(game)
    _step(game, _action(game, "pass_trick_response"))
    first = _action(game, "use_wuxie")
    assert first is not None and first.actor_id == "p2"
    first_id = first.card_instance_id
    assert first_id is not None
    _step(game, first)
    second = _action(game, "use_wuxie")
    assert second is not None and second.actor_id == "p1"
    _step(game, second)
    assert game.runtime.trick_effect_active is True
    used = [
        event
        for event in game.events
        if event.event_type is EventType.CARD_USED and event.card_key == WUXIE
    ]
    assert len(used) == 2
    assert used[0].payload.get("response_to") == trick_id
    assert used[1].payload.get("response_to") == first_id
    assert used[1].card_instance_id != first_id
    for event in used:
        assert event.payload.get("root_trick_instance_id") == trick_id
    before = len(game.events)
    _close_window_with_passes(game)
    assert game.phase is ProductionPhase.PLAY
    gained = [
        event
        for event in game.events[before:]
        if event.event_type is EventType.CARD_GAINED
        and event.payload.get("reason") == "draw_phase"
    ]
    assert len(gained) == 2
    assert not [
        event
        for event in game.events
        if event.event_type is EventType.CARD_EFFECT_CANCELLED
        and event.card_instance_id == trick_id
    ]


def test_wuxie_can_respond_to_wuxie_chain() -> None:
    game = ProductionBasicCardBatch(seed=396)
    assert WUXIE in _hand_keys(game, "p1")
    assert WUXIE in _hand_keys(game, "p2")
    trick_id = _use_wuzhong(game)
    _step(game, _action(game, "pass_trick_response"))
    first = _action(game, "use_wuxie")
    assert first is not None and first.actor_id == "p2"
    first_id = first.card_instance_id
    assert first_id is not None
    assert first.payload.get("response_to") == trick_id
    assert first.payload.get("root_trick_instance_id") == trick_id
    _step(game, first)
    second = _action(game, "use_wuxie")
    assert second is not None and second.actor_id == "p1"
    assert second.payload.get("response_to") == first_id
    assert second.payload.get("root_trick_instance_id") == trick_id
    _step(game, second)
    used_wuxie = [
        event
        for event in game.events
        if event.event_type is EventType.CARD_USED and event.card_key == WUXIE
    ]
    assert len(used_wuxie) == 2
    for event in used_wuxie:
        assert event.payload.get("creates_card_played_event") is False
        assert event.payload.get("counts_for_use_or_play_total") is True
        assert event.payload.get("root_trick_instance_id") == trick_id
    assert used_wuxie[0].payload.get("response_to") == trick_id
    assert used_wuxie[1].payload.get("response_to") == first_id
    assert used_wuxie[1].card_instance_id != first_id
    _close_window_with_passes(game)
    assert game.phase is ProductionPhase.PLAY
    assert game.state.location_of(trick_id) == DISCARD_PILE


def test_consecutive_response_final_effect_state_correct() -> None:
    # 奇数次【无懈可击】：最终不生效，不摸牌
    odd = ProductionBasicCardBatch(seed=3)
    trick_id = _use_wuzhong(odd)
    _step(odd, _action(odd, "pass_trick_response"))
    _step(odd, _action(odd, "use_wuxie"))
    assert odd.runtime.trick_effect_active is False
    _step(odd, _action(odd, "pass_trick_response"))
    _step(odd, _action(odd, "pass_trick_response"))
    assert odd.phase is ProductionPhase.PLAY
    assert odd.runtime.trick_effect_active is False
    assert [
        event
        for event in odd.events
        if event.event_type is EventType.CARD_EFFECT_CANCELLED
        and event.card_instance_id == trick_id
    ]

    # 偶数次【无懈可击】：最终生效并摸2张
    even = ProductionBasicCardBatch(seed=396)
    trick_id = _use_wuzhong(even)
    _step(even, _action(even, "pass_trick_response"))
    _step(even, _action(even, "use_wuxie"))
    _step(even, _action(even, "use_wuxie"))
    assert even.runtime.trick_effect_active is True
    _step(even, _action(even, "pass_trick_response"))
    _step(even, _action(even, "pass_trick_response"))
    assert even.phase is ProductionPhase.PLAY
    assert not [
        event
        for event in even.events
        if event.event_type is EventType.CARD_EFFECT_CANCELLED
        and event.card_instance_id == trick_id
    ]
    used_sequence = next(
        event.sequence
        for event in even.events
        if event.event_type is EventType.CARD_USED
        and event.card_instance_id == trick_id
    )
    gained_after_use = [
        event
        for event in even.events
        if event.event_type is EventType.CARD_GAINED
        and event.sequence > used_sequence
    ]
    assert len(gained_after_use) == 2


# ---------------------------------------------------------------------
# 10-14 响应合法性、顺序与隐藏信息
# ---------------------------------------------------------------------


def test_illegal_responder_card_and_stale_actions_rejected() -> None:
    game = ProductionBasicCardBatch(seed=396)
    use = _action(game, "use_wuzhong", card_key=WUZHONG)
    assert use is not None
    _step(game, use)
    # 已使用的【无中生有】动作已过期
    with pytest.raises(InvalidActionError):
        validate_action(game.state, game._context(), use, game.registry)
    _step(game, _action(game, "pass_trick_response"))
    assert game.current_actor_id == "p2"
    context = game._context()
    # 非法响应者：p1 手牌中的【无懈可击】不能由 p2 打出
    p1_wuxie = next(
        instance_id
        for instance_id in game.state.card_ids_in(ZoneRef.hand("p1"))
        if game.state.cards_by_id[instance_id].card_key == WUXIE
    )
    forged_owner = LegalAction(
        action_type=ActionType.USE_CARD,
        actor_id="p2",
        card_instance_id=p1_wuxie,
        target_ids=("p1",),
        payload={
            "operation": "use_wuxie",
            "card_key": WUXIE,
            "card_name": "无懈可击",
        },
        action_id="act_forged_owner",
    )
    with pytest.raises(InvalidActionError):
        validate_action(game.state, context, forged_owner, game.registry)
    # 非法响应牌：p2 的【闪】不能冒充【无懈可击】
    shan_id = next(
        instance_id
        for instance_id in game.state.card_ids_in(ZoneRef.hand("p2"))
        if game.state.cards_by_id[instance_id].card_key == "sgs_basic_shan"
    )
    forged_card = LegalAction(
        action_type=ActionType.USE_CARD,
        actor_id="p2",
        card_instance_id=shan_id,
        target_ids=("p1",),
        payload={
            "operation": "use_wuxie",
            "card_key": "sgs_basic_shan",
            "card_name": "闪",
        },
        action_id="act_forged_card",
    )
    with pytest.raises(InvalidActionError):
        validate_action(game.state, context, forged_card, game.registry)
    # 过期动作：窗口关闭后，之前捕获的放弃响应动作不能再执行
    # （p1 已放弃过一次，p2 再次放弃即连续一整轮无人响应，窗口立即关闭）
    stale = _action(game, "pass_trick_response")
    _step(game, stale)
    assert game.phase is ProductionPhase.PLAY
    with pytest.raises(InvalidActionError):
        validate_action(game.state, game._context(), stale, game.registry)


def test_forged_wuxie_response_targets_fail_closed() -> None:
    game = ProductionBasicCardBatch(seed=396)
    trick_id = _use_wuzhong(game)
    _step(game, _action(game, "pass_trick_response"))
    assert game.current_actor_id == "p2"
    first_context = game._context()
    legal_wuxie = _action(game, "use_wuxie")
    assert legal_wuxie is not None
    assert legal_wuxie.payload.get("response_to") == trick_id
    # 错误 target_ids：验证层拒绝
    forged_target = replace(legal_wuxie, target_ids=("p2",))
    with pytest.raises(InvalidActionError):
        validate_action(game.state, first_context, forged_target, game.registry)
    # 错误 response_to：验证层拒绝
    forged_response_to = replace(
        legal_wuxie,
        payload={**legal_wuxie.payload, "response_to": "sgs-forged-object"},
    )
    with pytest.raises(InvalidActionError):
        validate_action(
            game.state, first_context, forged_response_to, game.registry
        )
    # 正确响应对象可以真实执行
    _step(game, legal_wuxie)
    assert game.current_actor_id == "p1"
    second_context = game._context()
    second = _action(game, "use_wuxie")
    assert second is not None
    assert second.payload.get("response_to") == legal_wuxie.card_instance_id
    # 已执行动作过期：直接响应对象已经推进
    with pytest.raises(InvalidActionError):
        validate_action(game.state, first_context, legal_wuxie, game.registry)
    # 伪造 response_to 指回已过期的原锦囊：验证层拒绝
    stale = replace(
        second, payload={**second.payload, "response_to": trick_id}
    )
    with pytest.raises(InvalidActionError):
        validate_action(game.state, second_context, stale, game.registry)
    # 绕过验证层直接把篡改动作交给生产适配器应用时，运行时校验失败关闭
    canonical = validate_action(
        game.state, second_context, second, game.registry
    )
    tampered = replace(
        canonical, payload={**canonical.payload, "response_to": trick_id}
    )
    wuxie_adapter = game.formal_registry.adapter_for(WUXIE)
    with pytest.raises(InvalidActionError):
        wuxie_adapter.apply_action(game.state, second_context, tampered)


def test_responder_without_wuxie_has_no_wuxie_action() -> None:
    game = ProductionBasicCardBatch(seed=3)
    assert WUXIE not in _hand_keys(game, "p1")
    _use_wuzhong(game)
    actions = game.legal_actions()
    assert not any(
        action.payload.get("operation") == "use_wuxie" for action in actions
    )
    assert any(
        action.payload.get("operation") == "pass_trick_response"
        for action in actions
    )


def test_both_players_without_wuxie_only_pass_in_trick_window() -> None:
    game = ProductionBasicCardBatch(seed=18)
    assert WUXIE not in _hand_keys(game, "p1")
    assert WUXIE not in _hand_keys(game, "p2")
    _use_wuzhong(game)
    for expected_actor in ("p1", "p2"):
        assert game.current_actor_id == expected_actor
        operations = {
            action.payload.get("operation")
            for action in game.legal_actions()
        }
        assert operations == {"pass_trick_response"}
        _step(game, _action(game, "pass_trick_response"))
    assert game.phase is ProductionPhase.PLAY
    gained = [
        event
        for event in game.events
        if event.event_type is EventType.CARD_GAINED
        and event.payload.get("reason") == "draw_phase"
        and event.sequence > trick_sequence(game)
    ]
    assert len(gained) == 2
    assert not [
        event
        for event in game.events
        if event.event_type is EventType.CARD_EFFECT_CANCELLED
    ]


def trick_sequence(game: ProductionBasicCardBatch) -> int:
    used = [
        event
        for event in game.events
        if event.event_type is EventType.CARD_USED
        and event.card_key == WUZHONG
    ]
    assert used
    return used[0].sequence or 0


def test_pass_is_real_legal_action_in_trick_window() -> None:
    game = ProductionBasicCardBatch(seed=3)
    _use_wuzhong(game)
    passes = [
        action
        for action in game.legal_actions()
        if action.payload.get("operation") == "pass_trick_response"
    ]
    assert len(passes) == 1
    assert passes[0].action_type is ActionType.PASS
    assert passes[0].actor_id == "p1"
    assert passes[0].card_instance_id is None
    executed = _step(game, passes[0])
    assert executed.action_id == passes[0].action_id
    assert game.runtime.trick_response_index == 1
    assert game.current_actor_id == "p2"


def test_response_order_starts_from_current_turn_player() -> None:
    game = ProductionBasicCardBatch(seed=11)
    assert game.first_player_id == "p2"
    assert game.current_player_id == "p2"
    action = _action(game, "use_wuzhong", card_key=WUZHONG)
    assert action is not None and action.actor_id == "p2"
    _step(game, action)
    assert game.runtime.trick_response_order == ("p2", "p1")
    assert game.runtime.trick_response_index == 0
    assert game.current_actor_id == "p2"
    # 响应从当前回合角色开始按座次递增
    _step(game, _action(game, "pass_trick_response"))
    assert game.current_actor_id == "p1"


def test_hidden_hands_not_exposed_to_unauthorized_decision_input() -> None:
    game = ProductionBasicCardBatch(seed=396)
    _use_wuzhong(game)
    _step(game, _action(game, "pass_trick_response"))
    assert game.current_actor_id == "p2"
    p1_hand = set(game.state.card_ids_in(ZoneRef.hand("p1")))
    p2_hand = set(game.state.card_ids_in(ZoneRef.hand("p2")))
    assert p1_hand.isdisjoint(p2_hand)
    for action in game.legal_actions():
        if action.card_instance_id is None:
            continue
        assert action.card_instance_id in p2_hand
        assert action.card_instance_id not in p1_hand
    context = game._context()
    assert context.actor_id == "p2"
    pending = context.metadata.get("pending_trick")
    assert pending is not None
    assert set(pending) == {
        "user_id",
        "target_id",
        "trick_instance_id",
        "trick_key",
        "root_trick_instance_id",
    }


# ---------------------------------------------------------------------
# 15-16 守恒与失败关闭
# ---------------------------------------------------------------------


def test_card_conservation_holds_through_trick_paths() -> None:
    game = ProductionBasicCardBatch(seed=396)
    trick_id = _use_wuzhong(game)
    _step(game, _action(game, "pass_trick_response"))
    wuxie = _action(game, "use_wuxie")
    assert wuxie is not None
    wuxie_id = wuxie.card_instance_id
    _step(game, wuxie)
    _step(game, _action(game, "use_wuxie"))
    _close_window_with_passes(game)
    assert game.phase is ProductionPhase.PLAY
    assert game.state.location_of(trick_id) == DISCARD_PILE
    assert game.state.location_of(wuxie_id) == DISCARD_PILE
    zone_total = sum(
        len(game.state.card_ids_in(zone)) for zone in game.state.zone_order
    )
    assert zone_total == len(game.state.cards) == 160
    seen: set[str] = set()
    for zone in game.state.zone_order:
        for instance_id in game.state.card_ids_in(zone):
            assert instance_id not in seen
            seen.add(instance_id)
    assert seen == set(game.state.cards_by_id)
    game.state.assert_card_conservation()


def test_wuzhong_draw_reshuffles_when_draw_pile_exhausted() -> None:
    game = ProductionBasicCardBatch(seed=102)
    reached = False
    while not game.is_finished and game.step_count < 400:
        context = game._context()
        legal = game.legal_actions()
        if context.phase == ProductionPhase.PLAY.value:
            wuzhong_actions = [
                action
                for action in legal
                if action.payload.get("operation") == "use_wuzhong"
            ]
            if wuzhong_actions and len(game.state.card_ids_in(DRAW_PILE)) <= 2:
                chosen = min(
                    wuzhong_actions, key=lambda action: action.action_id or ""
                )
            else:
                chosen = BatchReferenceController().choose(legal, context)
        elif context.phase == ProductionPhase.TRICK_RESPONSE.value:
            chosen = next(
                action
                for action in legal
                if action.payload.get("operation") == "pass_trick_response"
            )
        else:
            chosen = BatchReferenceController().choose(legal, context)
        pile_before = len(game.state.card_ids_in(DRAW_PILE))
        before = len(game.events)
        game.step(BatchActionIdController(chosen.action_id))
        new_events = game.events[before:]
        reasons = [event.payload.get("reason") for event in new_events]
        if "reshuffle" in reasons and "wuzhong_effect_resolved" in reasons:
            reached = True
            assert pile_before == 0
            reshuffle_moves = [
                event
                for event in new_events
                if event.payload.get("reason") == "reshuffle"
            ]
            assert reshuffle_moves
            assert all(
                event.payload["source"]["kind"] == "discard_pile"
                for event in reshuffle_moves
            )
            assert all(
                event.payload["destination"]["kind"] == "draw_pile"
                for event in reshuffle_moves
            )
            draws = [
                event
                for event in new_events
                if event.event_type is EventType.CARD_GAINED
                and event.payload.get("reason") == "draw_phase"
            ]
            assert len(draws) == 2
            assert all(event.target_ids == ("p1",) for event in draws)
            assert max(
                event.sequence or 0 for event in reshuffle_moves
            ) < min(event.sequence or 0 for event in draws)
            assert any(
                event.payload.get("reason") == "wuzhong_effect_resolved"
                for event in new_events
            )
            break
    assert reached, "【无中生有】摸两张必须真实触发重洗并完成摸牌"
    assert len(game.state.cards) == 160
    assert sum(
        len(game.state.card_ids_in(zone)) for zone in game.state.zone_order
    ) == 160
    game.state.assert_card_conservation()


def test_other_normal_tricks_stay_fail_closed() -> None:
    game = ProductionBasicCardBatch(seed=3)
    registry = game.formal_registry
    for key in (
        "sgs_trick_guohechaiqiao",
        "sgs_trick_shunshouqianyang",
        "sgs_trick_juedou",
        "sgs_trick_huogong",
        "sgs_trick_nanmanruqin",
        "sgs_trick_wanjianqifa",
    ):
        assert key in registry.unimplemented_card_keys
        with pytest.raises(UnsupportedRuleError):
            registry.adapter_for(key)
    with pytest.raises(UnsupportedRuleError):
        registry.rule_spec_for("sgs_trick_guohechaiqiao")
    with pytest.raises(UnsupportedRuleError):
        registry.assert_no_unimplemented_fallback()
    implemented = set(PRODUCTION_BASIC_CARD_KEYS) | set(PRODUCTION_TRICK_KEYS)
    for action in game.legal_actions():
        if action.card_instance_id is None:
            continue
        assert (
            game.state.cards_by_id[action.card_instance_id].card_key
            in implemented
        )
    guohe_id = next(
        instance_id
        for instance_id in game.state.card_ids_in(ZoneRef.hand("p1"))
        if game.state.cards_by_id[instance_id].card_key
        == "sgs_trick_guohechaiqiao"
    )
    forged = LegalAction(
        action_type=ActionType.USE_CARD,
        actor_id="p1",
        card_instance_id=guohe_id,
        target_ids=("p2",),
        payload={
            "operation": "use_slash",
            "card_key": "sgs_trick_guohechaiqiao",
            "card_name": "过河拆桥",
        },
        action_id="act_guohe_forged",
    )
    with pytest.raises(InvalidActionError):
        validate_action(game.state, game._context(), forged, game.registry)


# ---------------------------------------------------------------------
# 17-19 规则重执行回放
# ---------------------------------------------------------------------


def test_replay_reexecutes_un_nullified_wuzhong_path() -> None:
    record = record_reference_production_batch(
        seed=3,
        controller=ScriptedBatchController(
            [
                {"operation": "use_wuzhong"},
                {"operation": "pass_trick_response"},
                {"operation": "pass_trick_response"},
            ]
        ),
    )
    assert record.header["production_basic_cards_batch"] is True
    used_keys = {
        event.get("card_key")
        for event in record.events
        if event.get("event_type") == "card_used"
    }
    assert WUZHONG in used_keys
    # 本路径的【无中生有】未被无效；后续【闪】抵消【杀】的取消事件不属于锦囊路径
    assert not any(
        event.get("event_type") == "card_effect_cancelled"
        and event.get("card_key") == WUZHONG
        for event in record.events
    )
    result = reexecute_production_replay(record)
    assert result.verified is True
    assert result.winner_id == record.outcome["winner_id"]


def test_replay_reexecutes_wuxie_nullified_path() -> None:
    record = record_reference_production_batch(
        seed=3,
        controller=ScriptedBatchController(
            [
                {"operation": "use_wuzhong"},
                {"operation": "pass_trick_response"},
                {"operation": "use_wuxie"},
                {"operation": "pass_trick_response"},
                {"operation": "pass_trick_response"},
            ]
        ),
    )
    cancelled = [
        event
        for event in record.events
        if event.get("event_type") == "card_effect_cancelled"
    ]
    assert cancelled
    used_keys = {
        event.get("card_key")
        for event in record.events
        if event.get("event_type") == "card_used"
    }
    assert {WUZHONG, WUXIE} <= used_keys
    result = reexecute_production_replay(record)
    assert result.verified is True


def test_tampered_trick_replay_fails_closed() -> None:
    record = record_reference_production_batch(
        seed=3,
        controller=ScriptedBatchController(
            [
                {"operation": "use_wuzhong"},
                {"operation": "pass_trick_response"},
                {"operation": "use_wuxie"},
                {"operation": "pass_trick_response"},
                {"operation": "pass_trick_response"},
            ]
        ),
    )
    assert any(
        event.get("event_type") == "card_effect_cancelled"
        for event in record.events
    )

    # 篡改锦囊响应窗口内的动作
    tampered = copy.deepcopy(record.to_dict())
    wuxie_decision = next(
        decision
        for decision in tampered["decisions"]
        if decision["chosen_action"].get("payload", {}).get("operation")
        == "use_wuxie"
    )
    legal_ids = {
        action["action_id"] for action in wuxie_decision["legal_actions"]
    }
    bogus = "act_" + sha256_value("tampered-wuxie-action")
    assert bogus not in legal_ids
    wuxie_decision["chosen_action_id"] = bogus
    del tampered["record_sha256"]
    rebuilt = ProductionReexecutionReplay.from_dict(tampered)
    with pytest.raises(ProductionReplayDivergenceError):
        reexecute_production_replay(rebuilt)

    # 篡改与响应相关的事件
    tampered = copy.deepcopy(record.to_dict())
    cancelled_event = next(
        event
        for event in tampered["events"]
        if event.get("event_type") == "card_effect_cancelled"
    )
    cancelled_event["card_key"] = "sgs_basic_sha"
    del tampered["record_sha256"]
    with pytest.raises(ProductionReplayFormatError):
        ProductionReexecutionReplay.from_dict(tampered)

    # 篡改最终状态哈希
    tampered = copy.deepcopy(record.to_dict())
    tampered["outcome"]["final_game_state_hash"] = sha256_value(
        "tampered-final-state"
    )
    del tampered["record_sha256"]
    rebuilt = ProductionReexecutionReplay.from_dict(tampered)
    with pytest.raises(ProductionReplayDivergenceError):
        reexecute_production_replay(rebuilt)


# ---------------------------------------------------------------------
# 20 游戏结束后停止响应与摸牌
# ---------------------------------------------------------------------


def test_finished_game_stops_trick_response_and_draw() -> None:
    game = ProductionBasicCardBatch(seed=5)
    result = game.run()
    assert game.is_finished
    assert game.winner_id == result.winner_id
    event_count = len(game.events)
    with pytest.raises(ProductionBatchFinishedError):
        game.legal_actions()
    with pytest.raises(ProductionBatchFinishedError):
        game.step()
    assert len(game.events) == event_count
