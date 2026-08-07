# -*- coding: utf-8 -*-
"""【过河拆桥】与【顺手牵羊】目标区域选牌生产批次测试。

覆盖正式CSV实体绑定、目标区域选牌动作、隐藏手牌选择句柄、公开区域
实体候选、弃置／获得实体牌事件、连续【无懈可击】响应、无合法区域牌
结算、严格回放与失败关闭。所有动作都经过真实枚举→校验→应用路径；
公开区域夹具只使用不可变GameState与正式牌区移动接口，不代表装备或
延时锦囊效果已经实现。
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
    ProductionBatchSafetyLimitError,
    ProductionPhase,
    ScriptedBatchController,
)
from scripts.sgs_engine.production_cards import (
    GuoheChaiqiaoAdapter,
    PRODUCTION_TRICK_KEYS,
    ShunshouQianyangAdapter,
    is_valid_shunshou_target,
)
from scripts.sgs_engine.production_replay import (
    ProductionReplayDivergenceError,
    ProductionReplayFormatError,
    ProductionReexecutionReplay,
    record_reference_production_batch,
    reexecute_production_replay,
)

GUOHE = "sgs_trick_guohechaiqiao"
SHUNSHOU = "sgs_trick_shunshouqianyang"
WUXIE = "sgs_trick_wuxiekeji"
_HAND_CHOICE_PAYLOAD_KEYS = {
    "operation",
    "trick_instance_id",
    "root_trick_instance_id",
    "user_id",
    "target_id",
    "zone",
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
    game: ProductionBasicCardBatch, operation: str, *, card_key: str | None = None
) -> object:
    for action in game.legal_actions():
        if action.payload.get("operation") != operation:
            continue
        if card_key is not None and action.payload.get("card_key") != card_key:
            continue
        return action
    return None


def _step(game: ProductionBasicCardBatch, action: object) -> None:
    assert action is not None and getattr(action, "action_id", None)
    game.step(BatchActionIdController(action.action_id))


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

def _pass(game: ProductionBasicCardBatch) -> None:
    _step(game, _action(game, "pass_trick_response"))


def _use_trick(game: ProductionBasicCardBatch, operation: str, card_key: str) -> str:
    action = _action(game, operation, card_key=card_key)
    assert action is not None, f"出牌阶段必须能枚举{operation}"
    assert len(action.target_ids) == 1, "双人切片中恰好一名目标"
    assert action.target_ids[0] != action.actor_id, "不能以自己为目标"
    trick_id = action.card_instance_id
    assert trick_id is not None
    _step(game, action)
    return trick_id


def _choose_zone(game: ProductionBasicCardBatch, zone_id: str) -> object:
    actions = [
        action
        for action in game.legal_actions()
        if action.payload.get("operation") == "choose_target_zone_card"
        and action.payload.get("zone") == zone_id
    ]
    assert actions, f"选牌窗口必须包含区域{zone_id}"
    action = actions[0]
    _step(game, action)
    return action


def _fixture_set_state(game: ProductionBasicCardBatch, moves: dict) -> None:
    """测试夹具：用不可变GameState与正式牌区移动接口改变区域归属。

    只赋值会话当前状态，不直接修改任何区域列表；仅用于把正式实体牌
    放入装备区／判定区或清空目标区域，不代表装备／延时锦囊效果已实现。
    """
    game._state = game.state.move_cards(moves)


def _empty_p2_zones(game: ProductionBasicCardBatch) -> tuple[str, ...]:
    hand_ids = tuple(game.state.card_ids_in(ZoneRef.hand("p2")))
    if hand_ids:
        _fixture_set_state(game, {instance_id: DISCARD_PILE for instance_id in hand_ids})
    return hand_ids


def _any_equipment_instance(game: ProductionBasicCardBatch) -> str:
    for card in game.state.cards:
        if card.card_type == "装备牌" and card.equipment_slot:
            return card.instance_id
    raise AssertionError("正式牌堆中必须存在装备实体牌供测试夹具使用")


def _any_instance_of(game: ProductionBasicCardBatch, card_key: str) -> str:
    for card in game.state.cards:
        if card.card_key == card_key:
            return card.instance_id
    raise AssertionError(f"正式牌堆中必须存在{card_key}实体牌供测试夹具使用")

# ---------------------------------------------------------------------
# A. 注册表与正式牌堆
# ---------------------------------------------------------------------


def test_guohe_entities_bind_to_production_adapter() -> None:
    game = _fresh(seed=3)
    registry = game.formal_registry
    assert GUOHE in PRODUCTION_TRICK_KEYS
    assert GUOHE in registry.implemented_card_keys
    records = registry.instances_of(GUOHE)
    assert len(records) == 6
    assert len({record.instance_id for record in records}) == 6
    assert {record.suit for record in records} == {"♣", "♥", "♠"}
    adapter = registry.adapter_for(GUOHE)
    assert isinstance(adapter, GuoheChaiqiaoAdapter)
    assert adapter.implemented is True and adapter.tested is True
    spec = adapter.rule_spec()
    assert spec["card_key"] == GUOHE
    assert spec["use_timing"] == "own_play_phase"
    assert spec["distance_rule"] == "not_applicable"
    assert spec["nullification_eligible"] is True
    for record in records:
        card = game.state.cards_by_id[record.instance_id]
        assert card.card_key == GUOHE and card.card_name == "过河拆桥"


def test_shunshou_entities_bind_to_production_adapter() -> None:
    game = _fresh(seed=3)
    registry = game.formal_registry
    assert SHUNSHOU in PRODUCTION_TRICK_KEYS
    assert SHUNSHOU in registry.implemented_card_keys
    records = registry.instances_of(SHUNSHOU)
    assert len(records) == 5
    assert len({record.instance_id for record in records}) == 5
    assert {record.suit for record in records} == {"♦", "♠"}
    adapter = registry.adapter_for(SHUNSHOU)
    assert isinstance(adapter, ShunshouQianyangAdapter)
    assert adapter.implemented is True and adapter.tested is True
    spec = adapter.rule_spec()
    assert spec["card_key"] == SHUNSHOU
    assert "actual_distance(user,target)==1" in str(spec["distance_rule"])
    for record in records:
        card = game.state.cards_by_id[record.instance_id]
        assert card.card_key == SHUNSHOU and card.card_name == "顺手牵羊"


def test_formal_deck_remains_160_with_unique_ids() -> None:
    game = _fresh(seed=3)
    zone_total = sum(
        len(game.state.card_ids_in(zone)) for zone in game.state.zone_order
    )
    assert zone_total == len(game.state.cards) == 160
    assert len({card.instance_id for card in game.state.cards}) == 160


def test_implemented_and_remaining_card_counts_updated() -> None:
    game = _fresh(seed=3)
    registry = game.formal_registry
    assert GUOHE in registry.implemented_card_keys
    assert SHUNSHOU in registry.implemented_card_keys
    assert len(registry.unimplemented_card_keys) == 0
    assert GUOHE not in registry.unimplemented_card_keys
    assert SHUNSHOU not in registry.unimplemented_card_keys
    assert sum(len(registry.instances_of(key)) for key in registry.implemented_card_keys) == 160
    assert {GUOHE, SHUNSHOU} <= set(PRODUCTION_TRICK_KEYS)


def test_other_unimplemented_tricks_stay_fail_closed() -> None:
    game = _fresh(seed=3)
    registry = game.formal_registry
    assert not registry.unimplemented_card_keys
    registry.assert_no_unimplemented_fallback()


# ---------------------------------------------------------------------
# B. 使用合法性
# ---------------------------------------------------------------------


def test_tricks_usable_only_in_own_play_phase() -> None:
    game = _fresh(seed=3)
    assert _action(game, "use_guohe", card_key=GUOHE) is not None
    _use_trick(game, "use_guohe", GUOHE)
    assert game.phase is ProductionPhase.TRICK_RESPONSE
    assert _action(game, "use_guohe", card_key=GUOHE) is None
    assert _action(game, "use_shunshou", card_key=SHUNSHOU) is None
    adapter = game.formal_registry.adapter_for(GUOHE)
    stale = _action(game, "pass_trick_response")
    _step(game, stale)
    context = game._context()
    any_hand_card = game.state.card_ids_in(ZoneRef.hand("p1"))[0]
    play_action = replace(
        LegalAction(
            action_type=ActionType.USE_CARD,
            actor_id="p1",
            card_instance_id=any_hand_card,
            target_ids=("p2",),
            payload={"operation": "use_guohe", "card_key": GUOHE},
        ),
        action_id="act_out_of_phase",
    )
    with pytest.raises(InvalidActionError):
        adapter.apply_action(game.state, context, play_action)


def test_cannot_target_self() -> None:
    game = _fresh(seed=3)
    action = _action(game, "use_guohe", card_key=GUOHE)
    assert action is not None and action.target_ids == ("p2",)
    forged = replace(action, target_ids=("p1",))
    with pytest.raises(InvalidActionError):
        validate_action(game.state, game._context(), forged, game.registry)
    shunshou_game = _fresh(seed=2)
    shun_action = _action(shunshou_game, "use_shunshou", card_key=SHUNSHOU)
    assert shun_action is not None and shun_action.target_ids == ("p2",)
    forged = replace(shun_action, target_ids=("p1",))
    with pytest.raises(InvalidActionError):
        validate_action(shunshou_game.state, shunshou_game._context(), forged, shunshou_game.registry)

def test_all_zones_empty_target_not_legal() -> None:
    game = _fresh(seed=66)
    _empty_p2_zones(game)
    assert _action(game, "use_guohe", card_key=GUOHE) is None
    assert _action(game, "use_shunshou", card_key=SHUNSHOU) is None


def test_hand_only_target_legal() -> None:
    game = _fresh(seed=66)
    assert game.state.card_ids_in(ZoneRef.hand("p2"))
    assert not game.state.card_ids_in(ZoneRef.judgment("p2"))
    assert _action(game, "use_guohe", card_key=GUOHE) is not None
    assert _action(game, "use_shunshou", card_key=SHUNSHOU) is not None


def test_equipment_only_target_legal() -> None:
    game = _fresh(seed=66)
    _empty_p2_zones(game)
    equipment_id = _any_equipment_instance(game)
    slot = game.state.cards_by_id[equipment_id].equipment_slot
    assert slot is not None
    _fixture_set_state(game, {equipment_id: ZoneRef.equipment("p2", slot)})
    assert not game.state.card_ids_in(ZoneRef.hand("p2"))
    assert game.state.card_ids_in(ZoneRef.equipment("p2", slot))
    assert _action(game, "use_guohe", card_key=GUOHE) is not None
    assert _action(game, "use_shunshou", card_key=SHUNSHOU) is not None


def test_judgment_only_target_legal() -> None:
    game = _fresh(seed=66)
    _empty_p2_zones(game)
    judgment_id = _any_instance_of(game, "sgs_delayed_shandian")
    _fixture_set_state(game, {judgment_id: ZoneRef.judgment("p2")})
    assert not game.state.card_ids_in(ZoneRef.hand("p2"))
    assert game.state.card_ids_in(ZoneRef.judgment("p2"))
    assert _action(game, "use_guohe", card_key=GUOHE) is not None
    assert _action(game, "use_shunshou", card_key=SHUNSHOU) is not None


def test_shunshou_distance_with_defensive_mount() -> None:
    game = _fresh(seed=66)
    assert is_valid_shunshou_target(game.state, "p1", "p1") is False
    _empty_p2_zones(game)
    mount_id = _any_instance_of(game, "sgs_mount_defensive")
    _fixture_set_state(
        game, {mount_id: ZoneRef.equipment("p2", "defense_horse")}
    )
    # 防御坐骑使 p1->p2 有效距离为2：顺手距离1不合法（不抛异常）
    assert is_valid_shunshou_target(game.state, "p1", "p2") is False
    assert _action(game, "use_shunshou", card_key=SHUNSHOU) is None
    # 进攻坐骑恢复距离1后合法
    attack_mount = _any_instance_of(game, "sgs_mount_offensive")
    _fixture_set_state(
        game, {attack_mount: ZoneRef.equipment("p1", "attack_horse")}
    )
    assert is_valid_shunshou_target(game.state, "p1", "p2") is True


def test_guohe_does_not_inherit_shunshou_distance_rule() -> None:
    game = _fresh(seed=66)
    _empty_p2_zones(game)
    mount_id = _any_instance_of(game, "sgs_mount_defensive")
    _fixture_set_state(
        game, {mount_id: ZoneRef.equipment("p2", "defense_horse")}
    )
    adapter = game.formal_registry.adapter_for(GUOHE)
    assert isinstance(adapter, GuoheChaiqiaoAdapter)
    actions = adapter.enumerate_legal_actions(game.state, game._context())
    assert any(action.payload.get("operation") == "use_guohe" for action in actions)
    spec = adapter.rule_spec()
    assert spec["distance_rule"] == "not_applicable"
    shun_adapter = game.formal_registry.adapter_for(SHUNSHOU)
    assert "actual_distance" in str(shun_adapter.rule_spec()["distance_rule"])


def test_stale_and_forged_use_actions_fail_closed() -> None:
    game = _fresh(seed=3)
    action = _action(game, "use_guohe", card_key=GUOHE)
    assert action is not None
    _step(game, action)
    with pytest.raises(InvalidActionError):
        validate_action(game.state, game._context(), action, game.registry)
    context = game._context()
    forged = replace(
        action,
        payload={**action.payload, "card_key": "sgs_trick_juedou"},
    )
    with pytest.raises(InvalidActionError):
        validate_action(game.state, context, forged, game.registry)
    bogus = replace(action, action_id="act_forged_guohe")
    with pytest.raises(InvalidActionError):
        validate_action(game.state, context, bogus, game.registry)

# ---------------------------------------------------------------------
# C. 【无懈可击】响应链
# ---------------------------------------------------------------------


def _wuxie_chain(game: ProductionBasicCardBatch, wuxie_count: int) -> None:
    _pass(game)
    for _ in range(wuxie_count):
        _step(game, _action(game, "use_wuxie"))
        _pass(game)
    _pass(game)


def test_wuxie_nullifies_guohe_no_target_card_moved() -> None:
    game = _fresh(seed=3)
    assert "sgs_trick_wuxiekeji" in _hand_keys(game, "p2")
    trick_id = _use_trick(game, "use_guohe", GUOHE)
    _wuxie_chain(game, 1)
    assert game.phase is ProductionPhase.PLAY
    assert game.runtime.pending_zone_choice is None
    cancelled = [
        event
        for event in game.events
        if event.event_type is EventType.CARD_EFFECT_CANCELLED
        and event.card_instance_id == trick_id
    ]
    assert len(cancelled) == 1
    assert cancelled[0].payload.get("reason") == "nullified_by_wuxie"
    assert not [
        event
        for event in game.events
        if event.event_type is EventType.CARD_DISCARDED
        and event.payload.get("reason") == "guohechaiqiao_effect"
    ]
    assert game.state.location_of(trick_id) == DISCARD_PILE


def test_two_wuxie_restore_guohe_effect() -> None:
    game = _fresh(seed=21)
    assert _hand_keys(game, "p2").count("sgs_trick_wuxiekeji") >= 2
    trick_id = _use_trick(game, "use_guohe", GUOHE)
    _wuxie_chain(game, 2)
    assert game.phase is ProductionPhase.ZONE_CHOICE
    assert game.runtime.pending_zone_choice is not None
    assert game.runtime.pending_zone_choice.trick_instance_id == trick_id
    _choose_zone(game, "hand")
    assert game.phase is ProductionPhase.PLAY
    assert game.state.location_of(trick_id) == DISCARD_PILE


def test_wuxie_nullifies_shunshou_no_target_card_moved() -> None:
    game = _fresh(seed=14)
    assert "sgs_trick_wuxiekeji" in _hand_keys(game, "p2")
    trick_id = _use_trick(game, "use_shunshou", SHUNSHOU)
    _wuxie_chain(game, 1)
    assert game.phase is ProductionPhase.PLAY
    assert game.runtime.pending_zone_choice is None
    cancelled = [
        event
        for event in game.events
        if event.event_type is EventType.CARD_EFFECT_CANCELLED
        and event.card_instance_id == trick_id
    ]
    assert len(cancelled) == 1
    assert not [
        event
        for event in game.events
        if event.event_type is EventType.CARD_GAINED
        and event.payload.get("reason") == "shunshouqianyang_effect"
    ]
    assert game.state.location_of(trick_id) == DISCARD_PILE


def test_two_wuxie_restore_shunshou_effect() -> None:
    game = _fresh(seed=51)
    assert _hand_keys(game, "p2").count("sgs_trick_wuxiekeji") >= 2
    trick_id = _use_trick(game, "use_shunshou", SHUNSHOU)
    _wuxie_chain(game, 2)
    assert game.phase is ProductionPhase.ZONE_CHOICE
    assert game.runtime.pending_zone_choice is not None
    _choose_zone(game, "hand")
    assert game.phase is ProductionPhase.PLAY
    assert game.state.location_of(trick_id) == DISCARD_PILE


def test_both_reuse_audited_response_to_chain() -> None:
    for seed, operation, key in (
        (3, "use_guohe", GUOHE),
        (2, "use_shunshou", SHUNSHOU),
    ):
        game = _fresh(seed=seed)
        trick_id = _use_trick(game, operation, key)
        runtime = game.runtime
        assert runtime.pending_trick is not None
        assert runtime.pending_trick.trick_instance_id == trick_id
        assert runtime.trick_direct_response_to == trick_id
        assert runtime.trick_response_order == ("p1", "p2")
        assert runtime.response_window_id.startswith("trick:")
        wuxie = _action(game, "use_wuxie")
        if wuxie is not None:
            assert wuxie.payload.get("response_to") == trick_id


def test_nullified_trick_opens_no_zone_choice_window() -> None:
    game = _fresh(seed=3)
    _use_trick(game, "use_guohe", GUOHE)
    _wuxie_chain(game, 1)
    assert game.phase is ProductionPhase.PLAY
    assert game.runtime.pending_zone_choice is None
    assert _action(game, "choose_target_zone_card") is None
    assert not any(
        action.payload.get("operation") == "choose_target_zone_card"
        for action in game.legal_actions()
    )


def test_nullified_trick_still_records_used_and_in_discard() -> None:
    game = _fresh(seed=3)
    trick_id = _use_trick(game, "use_guohe", GUOHE)
    _wuxie_chain(game, 1)
    used = [
        event
        for event in game.events
        if event.event_type is EventType.CARD_USED
        and event.card_instance_id == trick_id
    ]
    assert len(used) == 1
    assert used[0].payload.get("purpose") == "discard_one_target_zone_card"
    assert used[0].card_user == "p1"
    assert game.state.location_of(trick_id) == DISCARD_PILE

# ---------------------------------------------------------------------
# D. 【过河拆桥】效果
# ---------------------------------------------------------------------


def _guohe_effect_game(**fixture: object) -> ProductionBasicCardBatch:
    game = _fresh(seed=66)
    _use_trick(game, "use_guohe", GUOHE)
    _pass(game)
    _pass(game)
    assert game.phase is ProductionPhase.ZONE_CHOICE
    return game


def test_guohe_discards_target_hand_card() -> None:
    game = _guohe_effect_game()
    p2_hand = set(game.state.card_ids_in(ZoneRef.hand("p2")))
    assert p2_hand
    choice = _action(game, "choose_target_zone_card")
    assert choice is not None and choice.payload.get("zone") == "hand"
    _step(game, choice)
    assert game.phase is ProductionPhase.PLAY
    moved = [
        event
        for event in game.events
        if event.event_type is EventType.CARD_MOVED
        and event.payload.get("reason") == "guohechaiqiao_effect"
    ]
    assert len(moved) == 1
    instance_id = moved[0].card_instance_id
    assert instance_id in p2_hand
    assert game.state.location_of(instance_id) == DISCARD_PILE
    assert instance_id not in game.state.card_ids_in(ZoneRef.hand("p2"))
    discarded = [
        event
        for event in game.events
        if event.event_type is EventType.CARD_DISCARDED
        and event.card_instance_id == instance_id
    ]
    assert len(discarded) == 1
    game.state.assert_card_conservation()


def test_guohe_discards_target_equipment_card() -> None:
    game = _fresh(seed=66)
    _use_trick(game, "use_guohe", GUOHE)
    _pass(game)
    _pass(game)
    assert game.phase is ProductionPhase.ZONE_CHOICE
    equipment_id = _any_equipment_instance(game)
    slot = game.state.cards_by_id[equipment_id].equipment_slot
    assert slot is not None
    _fixture_set_state(game, {equipment_id: ZoneRef.equipment("p2", slot)})
    _choose_zone(game, f"equipment:{slot}")
    assert game.state.location_of(equipment_id) == DISCARD_PILE
    moved = [
        event
        for event in game.events
        if event.event_type is EventType.CARD_MOVED
        and event.card_instance_id == equipment_id
        and event.payload.get("reason") == "guohechaiqiao_effect"
    ]
    assert len(moved) == 1
    assert moved[0].payload["source"]["kind"] == "equipment"
    assert moved[0].payload["source"]["owner_id"] == "p2"
    assert moved[0].payload["destination"]["kind"] == "discard_pile"
    assert moved[0].payload["from_hidden_zone"] is False


def test_guohe_discards_target_judgment_card() -> None:
    game = _fresh(seed=66)
    _use_trick(game, "use_guohe", GUOHE)
    _pass(game)
    _pass(game)
    assert game.phase is ProductionPhase.ZONE_CHOICE
    judgment_id = _any_instance_of(game, "sgs_delayed_shandian")
    _fixture_set_state(game, {judgment_id: ZoneRef.judgment("p2")})
    _choose_zone(game, "judgment")
    assert game.state.location_of(judgment_id) == DISCARD_PILE
    moved = [
        event
        for event in game.events
        if event.event_type is EventType.CARD_MOVED
        and event.card_instance_id == judgment_id
        and event.payload.get("reason") == "guohechaiqiao_effect"
    ]
    assert len(moved) == 1
    assert moved[0].payload["source"]["kind"] == "judgment"
    assert moved[0].payload["destination"]["kind"] == "discard_pile"


def test_guohe_has_no_gain_then_discard_intermediate() -> None:
    game = _guohe_effect_game()
    p2_hand = set(game.state.card_ids_in(ZoneRef.hand("p2")))
    choice = _action(game, "choose_target_zone_card")
    _step(game, choice)
    effect_moves = [
        event
        for event in game.events
        if event.event_type is EventType.CARD_MOVED
        and event.payload.get("reason") == "guohechaiqiao_effect"
    ]
    assert len(effect_moves) == 1
    assert effect_moves[0].payload["movement"] == "discard_direct"
    assert effect_moves[0].payload["source"]["kind"] == "hand"
    instance_id = effect_moves[0].card_instance_id
    gained_by_user = [
        event
        for event in game.events
        if event.event_type is EventType.CARD_GAINED
        and event.card_instance_id == instance_id
        and event.target_ids == ("p1",)
    ]
    assert gained_by_user == []
    lost = [
        event
        for event in game.events
        if event.event_type is EventType.CARD_LOST
        and event.card_instance_id == instance_id
    ]
    assert len(lost) == 1
    assert lost[0].payload.get("reason") == "guohechaiqiao_discard"
    assert lost[0].payload.get("source_zone") == "hand"
    assert instance_id in p2_hand


def test_guohe_move_event_source_zone_reason_correct() -> None:
    game = _guohe_effect_game()
    trick_id = game.runtime.pending_zone_choice.trick_instance_id  # type: ignore[union-attr]
    p2_hand = set(game.state.card_ids_in(ZoneRef.hand("p2")))
    _choose_zone(game, "hand")
    moved = [
        event
        for event in game.events
        if event.event_type is EventType.CARD_MOVED
        and event.payload.get("reason") == "guohechaiqiao_effect"
    ]
    assert len(moved) == 1
    payload = moved[0].payload
    assert payload["source"]["owner_id"] == "p2"
    assert payload["destination"]["kind"] == "discard_pile"
    assert payload["trick_instance_id"] == trick_id
    assert payload["from_hidden_zone"] is True
    assert moved[0].target_ids == ("p2",)
    assert moved[0].card_user == "p1"
    assert moved[0].card_instance_id in p2_hand


def test_guohe_no_legal_zone_card_at_resolution() -> None:
    game = _fresh(seed=3)
    trick_id = _use_trick(game, "use_guohe", GUOHE)
    _pass(game)
    _empty_p2_zones(game)
    _pass(game)
    assert game.phase is ProductionPhase.PLAY
    assert game.runtime.pending_zone_choice is None
    finish = [
        event
        for event in game.events
        if event.payload.get("reason") == f"{GUOHE}_effect_resolved_no_legal_zone_card"
    ]
    assert len(finish) == 1
    assert finish[0].payload.get("no_legal_zone_card") is True
    assert not [
        event
        for event in game.events
        if event.event_type is EventType.CARD_DISCARDED
        and event.payload.get("reason") == "guohechaiqiao_effect"
    ]
    assert game.state.location_of(trick_id) == DISCARD_PILE

# ---------------------------------------------------------------------
# E. 【顺手牵羊】效果
# ---------------------------------------------------------------------


def _shunshou_effect_game(**fixture: object) -> ProductionBasicCardBatch:
    game = _fresh(seed=2)
    _use_trick(game, "use_shunshou", SHUNSHOU)
    _pass(game)
    _pass(game)
    assert game.phase is ProductionPhase.ZONE_CHOICE
    return game


def test_shunshou_gains_target_hand_card() -> None:
    game = _shunshou_effect_game()
    p2_hand = set(game.state.card_ids_in(ZoneRef.hand("p2")))
    choice = _action(game, "choose_target_zone_card")
    assert choice is not None and choice.payload.get("zone") == "hand"
    _step(game, choice)
    assert game.phase is ProductionPhase.PLAY
    gained = [
        event
        for event in game.events
        if event.event_type is EventType.CARD_GAINED
        and event.payload.get("reason") == "shunshouqianyang_effect"
    ]
    assert len(gained) == 1
    instance_id = gained[0].card_instance_id
    assert instance_id in p2_hand
    assert game.state.location_of(instance_id) == ZoneRef.hand("p1")
    assert instance_id in game.state.card_ids_in(ZoneRef.hand("p1"))
    assert instance_id not in game.state.card_ids_in(ZoneRef.hand("p2"))
    assert gained[0].target_ids == ("p1",)


def test_shunshou_gains_target_equipment_card() -> None:
    game = _shunshou_effect_game()
    equipment_id = _any_equipment_instance(game)
    slot = game.state.cards_by_id[equipment_id].equipment_slot
    assert slot is not None
    _fixture_set_state(game, {equipment_id: ZoneRef.equipment("p2", slot)})
    _choose_zone(game, f"equipment:{slot}")
    assert game.state.location_of(equipment_id) == ZoneRef.hand("p1")
    moved = [
        event
        for event in game.events
        if event.event_type is EventType.CARD_MOVED
        and event.card_instance_id == equipment_id
        and event.payload.get("reason") == "shunshouqianyang_effect"
    ]
    assert len(moved) == 1
    assert moved[0].payload["source"]["kind"] == "equipment"
    assert moved[0].payload["source"]["owner_id"] == "p2"
    assert moved[0].payload["destination"]["kind"] == "hand"
    assert moved[0].payload["destination"]["owner_id"] == "p1"
    assert moved[0].payload["from_hidden_zone"] is False


def test_shunshou_gains_target_judgment_card() -> None:
    game = _shunshou_effect_game()
    judgment_id = _any_instance_of(game, "sgs_delayed_shandian")
    _fixture_set_state(game, {judgment_id: ZoneRef.judgment("p2")})
    _choose_zone(game, "judgment")
    assert game.state.location_of(judgment_id) == ZoneRef.hand("p1")
    moved = [
        event
        for event in game.events
        if event.event_type is EventType.CARD_MOVED
        and event.card_instance_id == judgment_id
        and event.payload.get("reason") == "shunshouqianyang_effect"
    ]
    assert len(moved) == 1
    assert moved[0].payload["source"]["kind"] == "judgment"
    assert moved[0].payload["destination"]["kind"] == "hand"


def test_shunshou_owner_transfer_recorded() -> None:
    game = _shunshou_effect_game()
    p2_hand = set(game.state.card_ids_in(ZoneRef.hand("p2")))
    _choose_zone(game, "hand")
    gained = [
        event
        for event in game.events
        if event.event_type is EventType.CARD_GAINED
        and event.payload.get("reason") == "shunshouqianyang_effect"
    ]
    lost = [
        event
        for event in game.events
        if event.event_type is EventType.CARD_LOST
        and event.payload.get("reason") == "shunshouqianyang_gain"
    ]
    assert len(gained) == 1 and len(lost) == 1
    instance_id = gained[0].card_instance_id
    assert instance_id == lost[0].card_instance_id
    assert lost[0].target_ids == ("p2",)
    assert lost[0].payload.get("source_zone") == "hand"
    assert gained[0].target_ids == ("p1",)
    moved = [
        event
        for event in game.events
        if event.event_type is EventType.CARD_MOVED
        and event.card_instance_id == instance_id
        and event.payload.get("reason") == "shunshouqianyang_effect"
    ]
    assert len(moved) == 1
    assert moved[0].payload["source"]["owner_id"] == "p2"
    assert moved[0].payload["destination"]["owner_id"] == "p1"
    assert moved[0].payload["movement"] == "gain_direct"
    assert moved[0].payload["from_hidden_zone"] is True
    assert instance_id in p2_hand


def test_shunshou_card_conservation_160() -> None:
    game = _shunshou_effect_game()
    _choose_zone(game, "hand")
    zone_total = sum(
        len(game.state.card_ids_in(zone)) for zone in game.state.zone_order
    )
    assert zone_total == len(game.state.cards) == 160
    game.state.assert_card_conservation()


def test_shunshou_no_legal_zone_card_at_resolution() -> None:
    game = _fresh(seed=2)
    trick_id = _use_trick(game, "use_shunshou", SHUNSHOU)
    _pass(game)
    _empty_p2_zones(game)
    _pass(game)
    assert game.phase is ProductionPhase.PLAY
    assert game.runtime.pending_zone_choice is None
    finish = [
        event
        for event in game.events
        if event.payload.get("reason") == f"{SHUNSHOU}_effect_resolved_no_legal_zone_card"
    ]
    assert len(finish) == 1
    assert finish[0].payload.get("no_legal_zone_card") is True
    assert not [
        event
        for event in game.events
        if event.event_type is EventType.CARD_GAINED
        and event.payload.get("reason") == "shunshouqianyang_effect"
    ]
    assert game.state.location_of(trick_id) == DISCARD_PILE

# ---------------------------------------------------------------------
# F. 隐藏信息
# ---------------------------------------------------------------------


def test_hidden_hand_choice_payload_leaks_no_card_face() -> None:
    game = _guohe_effect_game()
    hand_actions = [
        action
        for action in game.legal_actions()
        if action.payload.get("zone") == "hand"
    ]
    assert hand_actions
    for action in hand_actions:
        assert set(action.payload) == _HAND_CHOICE_PAYLOAD_KEYS
        assert action.card_instance_id is None
        assert "card_key" not in action.payload
        handle = action.payload.get("handle")
        assert isinstance(handle, str) and handle.startswith("h_")
        assert handle not in game.state.card_ids_in(ZoneRef.hand("p2"))
        assert handle not in game.state.cards_by_id


def test_different_hidden_hands_produce_same_decision_structure() -> None:
    stable_fields: set[tuple[tuple[str, object], ...]] = set()
    handles: set[str] = set()
    for seed in (66, 3):
        game = _fresh(seed=seed)
        if _action(game, "use_guohe", card_key=GUOHE) is None:
            continue
        _use_trick(game, "use_guohe", GUOHE)
        _pass(game)
        _pass(game)
        hand_actions = [
            action
            for action in game.legal_actions()
            if action.payload.get("zone") == "hand"
        ]
        assert hand_actions
        for action in hand_actions:
            assert set(action.payload) == _HAND_CHOICE_PAYLOAD_KEYS
            payload = dict(action.payload)
            for key in ("handle", "state_hash", "window_id",
                        "trick_instance_id", "root_trick_instance_id"):
                payload.pop(key)
            handles.add(str(action.payload.get("handle")))
            stable_fields.add(tuple(sorted(payload.items())))
    assert len(handles) >= 2
    # 不同隐藏手牌下，非窗口绑定字段的决策输入结构完全相同
    assert len(stable_fields) == 1
    assert stable_fields == {
        (
            ("operation", "choose_target_zone_card"),
            ("target_id", "p2"),
            ("user_id", "p1"),
            ("zone", "hand"),
        )
    }


def test_public_zones_expose_explicit_entity_candidates() -> None:
    game = _guohe_effect_game()
    equipment_id = _any_equipment_instance(game)
    slot = game.state.cards_by_id[equipment_id].equipment_slot
    _fixture_set_state(game, {equipment_id: ZoneRef.equipment("p2", slot)})
    actions = [
        action
        for action in game.legal_actions()
        if action.payload.get("zone") == f"equipment:{slot}"
    ]
    assert len(actions) == 1
    assert actions[0].card_instance_id == equipment_id
    assert actions[0].payload.get("card_key") == game.state.cards_by_id[equipment_id].card_key
    _step(game, actions[0])
    assert game.state.location_of(equipment_id) == DISCARD_PILE


def test_handle_resolves_to_real_entity() -> None:
    game = _guohe_effect_game()
    p2_hand = set(game.state.card_ids_in(ZoneRef.hand("p2")))
    hand_actions = [
        action
        for action in game.legal_actions()
        if action.payload.get("zone") == "hand"
    ]
    assert hand_actions
    _step(game, hand_actions[0])
    discarded = [
        event
        for event in game.events
        if event.event_type is EventType.CARD_DISCARDED
        and event.payload.get("reason") == "guohechaiqiao_effect"
    ]
    assert len(discarded) == 1
    assert discarded[0].card_instance_id in p2_hand


def test_forged_handle_fails_closed() -> None:
    game = _guohe_effect_game()
    context = game._context()
    real = next(
        action
        for action in game.legal_actions()
        if action.payload.get("zone") == "hand"
    )
    forged = replace(
        real,
        payload={**real.payload, "handle": "h_" + "0" * 32},
    )
    with pytest.raises(InvalidActionError):
        validate_action(game.state, context, forged, game.registry)
    canonical = validate_action(game.state, context, real, game.registry)
    tampered = replace(
        canonical,
        payload={**canonical.payload, "handle": "h_" + "0" * 32},
    )
    adapter = game.formal_registry.adapter_for(GUOHE)
    with pytest.raises(InvalidActionError):
        adapter.apply_action(game.state, context, tampered)


def test_stale_handle_fails_closed_after_hand_change() -> None:
    game = _guohe_effect_game()
    context = game._context()
    real = next(
        action
        for action in game.legal_actions()
        if action.payload.get("zone") == "hand"
    )
    moved_id = game.state.card_ids_in(ZoneRef.hand("p2"))[0]
    _fixture_set_state(game, {moved_id: DISCARD_PILE})
    with pytest.raises(InvalidActionError):
        validate_action(game.state, context, real, game.registry)


def test_unauthorized_actor_sees_no_zone_choice_actions() -> None:
    game = _guohe_effect_game()
    assert game.current_actor_id == "p1"
    context = replace(game._context(), actor_id="p2")
    assert game.enumerate_zone_choice_actions(game.state, context) == ()
    metadata = game._context().metadata
    assert metadata.get("pending_zone_choice") is not None
    assert "zone_choice_handles" not in metadata
    assert "handle" not in str(metadata.get("pending_zone_choice"))

def test_new_owner_can_know_gained_card() -> None:
    game = _shunshou_effect_game()
    p2_hand = set(game.state.card_ids_in(ZoneRef.hand("p2")))
    _choose_zone(game, "hand")
    gained = [
        event
        for event in game.events
        if event.event_type is EventType.CARD_GAINED
        and event.payload.get("reason") == "shunshouqianyang_effect"
    ]
    assert len(gained) == 1
    instance_id = gained[0].card_instance_id
    assert instance_id in p2_hand
    card = game.state.cards_by_id[instance_id]
    assert game.state.location_of(instance_id) == ZoneRef.hand("p1")
    assert card.card_key and card.card_name
    assert gained[0].target_ids == ("p1",)


def test_other_player_gets_no_automatic_card_face_in_decision_input() -> None:
    game = _shunshou_effect_game()
    p2_hand = set(game.state.card_ids_in(ZoneRef.hand("p2")))
    _choose_zone(game, "hand")
    gained = [
        event
        for event in game.events
        if event.event_type is EventType.CARD_GAINED
        and event.payload.get("reason") == "shunshouqianyang_effect"
    ]
    instance_id = gained[0].card_instance_id
    assert instance_id in p2_hand
    # 后续整局中，其他角色的决策输入不得引用被获得的实体牌本体；
    # 同名牌出现于他人自身手牌动作时只允许通过其自己的实体ID表达。
    while not game.is_finished and game.step_count < 400:
        context = game._context()
        if context.actor_id == "p2":
            for action in game.legal_actions():
                assert str(instance_id) not in str(action.payload)
                if action.card_instance_id is not None:
                    assert action.card_instance_id in game.state.card_ids_in(
                        ZoneRef.hand("p2")
                    )
                    assert action.card_instance_id != instance_id
        game.step(BatchReferenceController())


# ---------------------------------------------------------------------
# G. 回放与失败关闭
# ---------------------------------------------------------------------


def test_replay_reexecutes_guohe_discard_hand_path() -> None:
    record = record_reference_production_batch(
        seed=3,
        controller=ScriptedBatchController(
            [
                {"operation": "use_guohe", "card_key": GUOHE},
                {"operation": "pass_trick_response"},
                {"operation": "pass_trick_response"},
                {"operation": "choose_target_zone_card", "zone": "hand"},
            ]
        ),
    )
    discarded = [
        event
        for event in record.events
        if event.get("event_type") == "card_discarded"
        and event.get("payload", {}).get("reason") == "guohechaiqiao_effect"
    ]
    assert len(discarded) == 1
    result = reexecute_production_replay(record)
    assert result.verified is True
    assert result.winner_id == record.outcome["winner_id"]


def test_player_visible_zone_choice_window_actor_projection() -> None:
    """B1-a/B1-b：zone-choice 窗口公共视图无私有动作与权威摘要。"""

    record = record_reference_production_batch(
        seed=3,
        controller=ScriptedBatchController(
            [
                {"operation": "use_guohe", "card_key": GUOHE},
                {"operation": "pass_trick_response"},
                {"operation": "pass_trick_response"},
                {"operation": "choose_target_zone_card", "zone": "hand"},
            ]
        ),
    )
    public = record.player_visible_payload()
    for decision in public["decisions"]:
        assert "chosen_action" not in decision
        assert "legal_actions" not in decision
        assert "state_before_sha256" not in decision
        assert "state_after_sha256" not in decision
    actor = record.player_visible_payload(viewer_id="p1")
    for decision in actor["decisions"]:
        if decision.get("context", {}).get("actor_id") != "p1":
            assert "chosen_action" not in decision
            assert "legal_actions" not in decision
        else:
            for action in decision.get("legal_actions", []):
                assert "state_hash" not in action
                assert "state_sha256" not in action
                assert "action_id" not in action
    # 权威回放仍可严格重执行
    assert reexecute_production_replay(record).verified is True


def test_replay_reexecutes_shunshou_gain_hand_path() -> None:
    record = record_reference_production_batch(
        seed=2,
        controller=ScriptedBatchController(
            [
                {"operation": "use_shunshou", "card_key": SHUNSHOU},
                {"operation": "pass_trick_response"},
                {"operation": "pass_trick_response"},
                {"operation": "choose_target_zone_card", "zone": "hand"},
            ]
        ),
    )
    gained = [
        event
        for event in record.events
        if event.get("event_type") == "card_gained"
        and event.get("payload", {}).get("reason") == "shunshouqianyang_effect"
    ]
    assert len(gained) == 1
    result = reexecute_production_replay(record)
    assert result.verified is True


def test_public_zone_path_strictly_reproducible() -> None:
    """公开装备区／判定区路径的确定性复现：同夹具、同决策两次独立运行
    必须产生完全相同的事件流与最终状态（严格重执行语义的事件哈希一致）。"""
    runs: list[list[dict]] = []
    for _ in range(2):
        game = _fresh(seed=66)
        _use_trick(game, "use_guohe", GUOHE)
        _pass(game)
        _pass(game)
        assert game.phase is ProductionPhase.ZONE_CHOICE
        equipment_id = _any_equipment_instance(game)
        slot = game.state.cards_by_id[equipment_id].equipment_slot
        _fixture_set_state(game, {equipment_id: ZoneRef.equipment("p2", slot)})
        _choose_zone(game, f"equipment:{slot}")
        assert game.state.location_of(equipment_id) == DISCARD_PILE
        runs.append(
            [event.to_replay_dict() for event in game.events]
        )
    assert runs[0] == runs[1]


def test_replay_reexecutes_nullified_path() -> None:
    record = record_reference_production_batch(
        seed=3,
        controller=ScriptedBatchController(
            [
                {"operation": "use_guohe", "card_key": GUOHE},
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
        and event.get("card_key") == GUOHE
    ]
    assert cancelled
    assert not any(
        event.get("payload", {}).get("reason") == "guohechaiqiao_effect"
        for event in record.events
    )
    result = reexecute_production_replay(record)
    assert result.verified is True

def test_tampered_zone_choice_replay_fails_closed() -> None:
    record = record_reference_production_batch(
        seed=3,
        controller=ScriptedBatchController(
            [
                {"operation": "use_guohe", "card_key": GUOHE},
                {"operation": "pass_trick_response"},
                {"operation": "pass_trick_response"},
                {"operation": "choose_target_zone_card", "zone": "hand"},
            ]
        ),
    )
    decisions = record.to_dict()["decisions"]
    assert any(
        decision["chosen_action"].get("payload", {}).get("operation")
        == "choose_target_zone_card"
        for decision in decisions
    )

    # 篡改隐藏句柄：伪造handle
    tampered = copy.deepcopy(record.to_dict())
    zone_decision = next(
        decision
        for decision in tampered["decisions"]
        if decision["chosen_action"].get("payload", {}).get("operation")
        == "choose_target_zone_card"
    )
    zone_decision["chosen_action"]["payload"]["handle"] = "h_" + "0" * 32
    del tampered["record_sha256"]
    rebuilt = ProductionReexecutionReplay.from_dict(tampered)
    with pytest.raises(ProductionReplayDivergenceError):
        reexecute_production_replay(rebuilt)

    # 篡改目标区域：hand -> equipment:weapon
    tampered = copy.deepcopy(record.to_dict())
    zone_decision = next(
        decision
        for decision in tampered["decisions"]
        if decision["chosen_action"].get("payload", {}).get("operation")
        == "choose_target_zone_card"
    )
    zone_decision["chosen_action"]["payload"]["zone"] = "equipment:weapon"
    del tampered["record_sha256"]
    rebuilt = ProductionReexecutionReplay.from_dict(tampered)
    with pytest.raises(ProductionReplayDivergenceError):
        reexecute_production_replay(rebuilt)

    # 篡改事件：弃置事件的卡牌键
    tampered = copy.deepcopy(record.to_dict())
    discarded_event = next(
        event
        for event in tampered["events"]
        if event.get("event_type") == "card_discarded"
        and event.get("payload", {}).get("reason") == "guohechaiqiao_effect"
    )
    discarded_event["card_key"] = "sgs_basic_sha"
    del tampered["record_sha256"]
    with pytest.raises(ProductionReplayFormatError):
        ProductionReexecutionReplay.from_dict(tampered)


def test_finished_game_opens_no_zone_window() -> None:
    game = _fresh(seed=3)
    game.run()
    assert game.is_finished
    event_count = len(game.events)
    with pytest.raises(ProductionBatchFinishedError):
        game.legal_actions()
    with pytest.raises(ProductionBatchFinishedError):
        game.step()
    assert len(game.events) == event_count


def test_safety_limit_still_fails_closed() -> None:
    game = _fresh(seed=3)
    with pytest.raises(ProductionBatchSafetyLimitError):
        game.run(max_steps=1)
    assert not game.is_finished
    assert game.runtime.pending_zone_choice is None


def test_all_paths_keep_conservation_and_hash_chain() -> None:
    for seed, operation, key in (
        (38, "use_guohe", GUOHE),
        (2, "use_shunshou", SHUNSHOU),
        (21, "use_guohe", GUOHE),
        (51, "use_shunshou", SHUNSHOU),
    ):
        game = _fresh(seed=seed)
        _use_trick(game, operation, key)
        _wuxie_chain(game, 2 if seed in (21, 51) else 0)
        if game.phase is ProductionPhase.ZONE_CHOICE:
            _choose_zone(game, "hand")
        zone_total = sum(
            len(game.state.card_ids_in(zone)) for zone in game.state.zone_order
        )
        assert zone_total == len(game.state.cards) == 160
        game.state.assert_card_conservation()
    record = record_reference_production_batch(
        seed=38,
        controller=ScriptedBatchController(
            [
                {"operation": "use_guohe", "card_key": GUOHE},
                {"operation": "pass_trick_response"},
                {"operation": "pass_trick_response"},
                {"operation": "choose_target_zone_card", "zone": "hand"},
                {"operation": "use_shunshou", "card_key": SHUNSHOU},
                {"operation": "pass_trick_response"},
                {"operation": "pass_trick_response"},
                {"operation": "choose_target_zone_card", "zone": "hand"},
            ]
        ),
    )
    result = reexecute_production_replay(record)
    assert result.verified is True
