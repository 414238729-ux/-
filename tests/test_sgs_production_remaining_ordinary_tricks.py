# -*- coding: utf-8 -*-
"""CP-04I：五谷丰登完整生产语义＋铁索连环牌本体生产垂直切片。

全部用例走真实生产入口（enumerate→validate→apply）；定向负向测试直接
调用生产适配器以证明失败关闭；不使用 mock 替代核心结算，无 skip、无
xfail。铁索只证明牌本体（使用、一至二目标、横置切换、逐目标无懈、重铸、
严格回放与隐藏信息边界），属性伤害传导保持未实现并被明确证明不会误写
为完成。
"""

from __future__ import annotations

import copy
import json

import pytest

from scripts.sgs_engine.actions import (
    ActionType,
    InvalidActionError,
    LegalAction,
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
    ZoneRef,
)
from scripts.sgs_engine.production_batch import (
    BatchActionIdController,
    ProductionBasicCardBatch,
    ProductionBatchDeckExhaustedError,
    ProductionPhase,
    ScriptedBatchController,
    _replace_player,
)
from scripts.sgs_engine.production_replay import (
    ProductionReexecutionReplay,
    ProductionReplayDivergenceError,
    ProductionReplayFormatError,
    record_reference_production_batch,
    reexecute_production_replay,
)
from scripts.sgs_engine.replay import state_sha256

WUGU = "sgs_trick_wugufengdeng"
TIESUO = "sgs_trick_tiesuolianhuan"
JIEDAO = "sgs_trick_jiedaosharen"


# ----------------------------------------------------------------------
# 基础夹具与助手
# ----------------------------------------------------------------------


def _fresh(
    seed: int,
    *,
    player_hp: tuple[int, int] = (4, 4),
    initial_hand_count: int = 4,
) -> ProductionBasicCardBatch:
    return ProductionBasicCardBatch(
        seed=seed,
        player_hp=player_hp,
        initial_hand_count=initial_hand_count,
    )


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
    """把牌堆中的五谷、铁索与无懈实体移到双方手牌。"""

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
    # 当前行动角色手牌至少一张无懈；对手手牌也至少一张（双无懈用例）
    for index, instance_id in enumerate(wuxie_ids):
        target = player_id if index % 2 == 0 else opponent_id
        _move_to_hand(game, instance_id, target)
    return wugu_ids, tiesuo_ids


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


def _pass_trick(game: ProductionBasicCardBatch) -> None:
    _step(game, _action(game, "pass_trick_response"))


def _close_trick_window(game: ProductionBasicCardBatch) -> None:
    _pass_trick(game)
    _pass_trick(game)


def _pass_trick_until(
    game: ProductionBasicCardBatch, phase: ProductionPhase
) -> None:
    """持续放弃锦囊响应直到进入目标阶段（有界保护）。"""

    for _ in range(12):
        if game.phase is phase:
            return
        pass_action = _action(game, "pass_trick_response")
        assert pass_action is not None, (
            f"无法推进到{phase.value}，当前阶段{game.phase.value}"
        )
        _step(game, pass_action)
    raise AssertionError(f"连续放弃响应后仍未进入{phase.value}")


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


def _use_wugu(game: ProductionBasicCardBatch) -> str:
    action = _action(game, "use_wugu", card_key=WUGU)
    assert action is not None, "出牌阶段必须能枚举使用五谷"
    trick_id = action.card_instance_id
    assert trick_id is not None
    _step(game, action)
    return trick_id


def _wugu_pick(game: ProductionBasicCardBatch) -> LegalAction:
    picks = [
        action
        for action in game.legal_actions()
        if action.payload.get("operation") == "pick_wugu_card"
    ]
    assert picks, "五谷选牌阶段必须能枚举展示池选择"
    return picks[0]


def _hand_keys(game: ProductionBasicCardBatch, player_id: str) -> tuple[str, ...]:
    return tuple(
        game.state.cards_by_id[instance_id].card_key
        for instance_id in game.state.card_ids_in(ZoneRef.hand(player_id))
    )


class _TrickReplayController(ScriptedBatchController):
    """录制控制器：支持五谷选牌池索引与铁索目标数量的规格匹配。"""

    def _matches(
        self, action: LegalAction, spec: dict[str, object]
    ) -> bool:
        operation = action.payload.get("operation")
        if operation == "pick_wugu_card":
            if spec.get("operation") != "pick_wugu_card":
                return False
            if (
                "pool_index" in spec
                and action.payload.get("pool_index") != spec["pool_index"]
            ):
                return False
            return True
        if operation == "use_tiesuo":
            if spec.get("operation") != "use_tiesuo":
                return False
            if (
                spec.get("card_key") is not None
                and action.payload.get("card_key") != spec["card_key"]
            ):
                return False
            if (
                spec.get("target_count") is not None
                and len(action.target_ids) != spec["target_count"]
            ):
                return False
            if spec.get("include_self") and not any(
                target == action.actor_id for target in action.target_ids
            ):
                return False
            return True
        return super()._matches(action, spec)


def _load_tampered(record: ProductionReexecutionReplay) -> dict[str, object]:
    tampered = copy.deepcopy(record.to_dict())
    del tampered["record_sha256"]
    return tampered


# ----------------------------------------------------------------------
# A. 五谷：注册表与展示
# ----------------------------------------------------------------------


def test_wugu_registry_and_two_entities() -> None:
    game = _fresh(3)
    registry = game.formal_registry
    assert WUGU in registry.implemented_card_keys
    records = registry.instances_of(WUGU)
    assert len(records) == 2
    assert len({record.instance_id for record in records}) == 2
    adapter = registry.adapter_for(WUGU)
    assert adapter.implemented is True and adapter.tested is True
    spec = registry.rule_spec_for(WUGU)
    assert spec["target_filter"] == (
        "all_alive_characters_including_user;snapshot_at_use_time"
    )


def test_wugu_use_rejects_player_submitted_targets() -> None:
    game = _fresh(3)
    _stock_tricks(game)
    context = game._context()
    adapter = game.formal_registry.adapter_for(WUGU)
    trick_id = next(
        instance_id
        for instance_id in game.state.card_ids_in(ZoneRef.hand(_me(game)))
        if game.state.cards_by_id[instance_id].card_key == WUGU
    )
    forged = LegalAction(
        action_type=ActionType.USE_CARD,
        actor_id=_me(game),
        card_instance_id=trick_id,
        target_ids=("p1", "p2"),
        payload={
            "operation": "use_wugu",
            "card_key": WUGU,
            "card_name": "五谷丰登",
        },
        action_id="act_wugu_targets",
    )
    with pytest.raises(InvalidActionError):
        validate_action(game.state, context, forged, game.registry)
    with pytest.raises(InvalidActionError, match="目标集合由服务器自动生成"):
        adapter.apply_action(game.state, context, forged)


def test_wugu_use_requires_hand_entity() -> None:
    game = _fresh(3)
    _stock_tricks(game)
    context = game._context()
    adapter = game.formal_registry.adapter_for(WUGU)
    trick_id = next(
        instance_id
        for instance_id in game.state.card_ids_in(ZoneRef.hand(_me(game)))
        if game.state.cards_by_id[instance_id].card_key == WUGU
    )
    # 实体已不在手牌（移入处理区）时拒绝使用
    game._state = game.state.move_card(trick_id, PROCESSING_ZONE)
    stale = LegalAction(
        action_type=ActionType.USE_CARD,
        actor_id=_me(game),
        card_instance_id=trick_id,
        target_ids=(),
        payload={
            "operation": "use_wugu",
            "card_key": WUGU,
            "card_name": "五谷丰登",
        },
        action_id="act_wugu_stale",
    )
    with pytest.raises(InvalidActionError, match="真实手牌"):
        adapter.apply_action(game.state, context, stale)


def test_wugu_target_sequence_includes_user_snapshot() -> None:
    game = _fresh(3)
    _stock_tricks(game)
    trick_id = _use_wugu(game)
    group = game.runtime.pending_group_trick
    assert group is not None
    assert group.trick_instance_id == trick_id
    assert group.target_sequence == (_me(game), _other(game))
    assert game.state.location_of(trick_id) == PROCESSING_ZONE
    pool = game.state.card_ids_in(REVEALED_ZONE)
    assert len(pool) == 2
    assert len(set(pool)) == 2


def test_wugu_dual_player_reveals_two_public_cards() -> None:
    game = _fresh(3)
    _stock_tricks(game)
    trick_id = _use_wugu(game)
    revealed = _events_of(game, EventType.CARD_REVEALED)
    assert len(revealed) == 2
    assert all(
        event.card_instance_id is not None for event in revealed
    )
    for index, event in enumerate(revealed):
        payload = event.payload
        assert payload["reason"] == "wugu_reveal"
        assert payload["card_name"] in (
            game.state.cards_by_id[event.card_instance_id].card_name,
        )
        assert payload["suit"]
        assert payload["rank"]
        assert payload["pool_index"] == index
        assert payload["pool_size"] == 2
        assert payload["root_trick_instance_id"] == trick_id
    moved = _events_of(game, EventType.CARD_MOVED)
    reveal_moves = [
        event
        for event in moved
        if event.payload.get("reason") == "wugu_reveal"
    ]
    assert len(reveal_moves) == 2
    assert all(
        event.payload["destination"]["kind"] == "revealed"
        for event in reveal_moves
    )


def test_wugu_user_picks_first_then_opponent_in_order() -> None:
    game = _fresh(3)
    _stock_tricks(game)
    trick_id = _use_wugu(game)
    _close_trick_window(game)
    assert game.phase is ProductionPhase.WUGU_PICK
    assert game.current_actor_id == _me(game)
    first_pick = _wugu_pick(game)
    _step(game, first_pick)
    resolved = _events_of(game, EventType.GROUP_TARGET_RESOLVED)
    assert [event.payload["target_index"] for event in resolved] == [0]
    assert resolved[0].payload["result"] == "picked"
    assert resolved[0].card_instance_id == trick_id
    assert _events_of(game, EventType.CARD_GAINED)  # 选牌进入手牌
    # 第二目标窗口与选牌
    _close_trick_window(game)
    assert game.phase is ProductionPhase.WUGU_PICK
    assert game.current_actor_id == _other(game)
    second_pick = _wugu_pick(game)
    _step(game, second_pick)
    resolved = _events_of(game, EventType.GROUP_TARGET_RESOLVED)
    assert [event.payload["target_index"] for event in resolved] == [0, 1]
    assert game.phase is ProductionPhase.PLAY


def test_wugu_pick_moves_unique_entity_to_hand() -> None:
    game = _fresh(3)
    _stock_tricks(game)
    _use_wugu(game)
    _close_trick_window(game)
    pick = _wugu_pick(game)
    picked_id = pick.card_instance_id
    assert picked_id is not None
    actor = game.current_actor_id
    _step(game, pick)
    assert game.state.location_of(picked_id) == ZoneRef.hand(actor)
    assert picked_id not in game.state.card_ids_in(REVEALED_ZONE)
    gained = _events_of(game, EventType.CARD_GAINED)
    assert gained[-1].card_instance_id == picked_id
    assert gained[-1].target_ids == (actor,)
    assert gained[-1].payload["reason"] == "wugu_pick"


def test_wugu_remaining_pool_discarded_after_all_targets() -> None:
    game = _fresh(3)
    _stock_tricks(game)
    trick_id = _use_wugu(game)
    # 使用者被无懈：第一目标跳过选牌，展示池保持
    wuxie = _action(game, "use_wuxie")
    assert wuxie is not None
    _step(game, wuxie)
    _pass_trick(game)
    assert game.phase is ProductionPhase.TRICK_RESPONSE
    pool_before = game.state.card_ids_in(REVEALED_ZONE)
    assert len(pool_before) == 2
    # 关闭第一目标窗口：被无懈，不选牌；随后进入第二目标窗口
    _close_trick_window(game)
    assert game.phase is ProductionPhase.TRICK_RESPONSE
    # 第二目标选走一张，剩余一张进入弃牌堆
    _pass_trick_until(game, ProductionPhase.WUGU_PICK)
    _step(game, _wugu_pick(game))
    assert game.phase is ProductionPhase.PLAY
    assert not game.state.card_ids_in(REVEALED_ZONE)
    assert game.state.location_of(trick_id) == DISCARD_PILE
    remaining_moves = [
        event
        for event in _events_of(game, EventType.CARD_MOVED)
        if event.payload.get("reason") == "wugu_remaining_to_discard"
    ]
    assert len(remaining_moves) == 1
    assert remaining_moves[0].payload["source"]["kind"] == "revealed"
    assert remaining_moves[0].payload["destination"]["kind"] == "discard_pile"


def test_wugu_single_wuxie_skips_only_current_target() -> None:
    game = _fresh(3)
    _stock_tricks(game)
    _use_wugu(game)
    wuxie = _action(game, "use_wuxie")
    assert wuxie is not None
    _step(game, wuxie)
    # 关闭当前目标窗口：一整轮无人再响应，效果按最终状态结算
    _close_trick_window(game)
    cancelled = _events_of(game, EventType.CARD_EFFECT_CANCELLED)
    assert len(cancelled) == 1
    assert cancelled[0].target_ids == (_me(game),)
    assert cancelled[0].payload["reason"] == "nullified_by_wuxie"
    resolved = _events_of(game, EventType.GROUP_TARGET_RESOLVED)
    assert resolved[0].payload["result"] == "cancelled"
    # 展示池未被第一目标取走
    assert len(game.state.card_ids_in(REVEALED_ZONE)) == 2
    # 第二目标仍可正常选牌
    _close_trick_window(game)
    assert game.phase is ProductionPhase.WUGU_PICK
    assert game.current_actor_id == _other(game)
    second_pick = _wugu_pick(game)
    assert second_pick.card_instance_id in (
        game.state.card_ids_in(REVEALED_ZONE)
    )


def test_wugu_double_wuxie_restores_current_target_effect() -> None:
    game = _fresh(3)
    _stock_tricks(game)
    _use_wugu(game)
    wuxie1 = _action(game, "use_wuxie")
    _step(game, wuxie1)
    wuxie2 = _action(game, "use_wuxie")
    assert wuxie2 is not None
    _step(game, wuxie2)
    _pass_trick(game)
    _pass_trick(game)
    # 双无懈后效果恢复：当前目标进入选牌阶段
    assert game.phase is ProductionPhase.WUGU_PICK
    assert game.current_actor_id == _me(game)
    assert len(_events_of(game, EventType.CARD_EFFECT_CANCELLED)) == 0


def test_wugu_per_target_independent_wuxie_windows() -> None:
    game = _fresh(3)
    _stock_tricks(game)
    _use_wugu(game)
    first_window = game.runtime.response_window_id
    assert first_window is not None and first_window.endswith("gt0:dec0")
    # 第一目标不无懈
    _close_trick_window(game)
    _step(game, _wugu_pick(game))
    second_window = game.runtime.response_window_id
    assert second_window is not None and second_window.endswith("gt1:dec0")
    assert second_window != first_window


def test_wugu_trick_stays_in_processing_until_all_targets() -> None:
    game = _fresh(3)
    _stock_tricks(game)
    trick_id = _use_wugu(game)
    assert game.state.location_of(trick_id) == PROCESSING_ZONE
    _close_trick_window(game)
    _step(game, _wugu_pick(game))
    assert game.state.location_of(trick_id) == PROCESSING_ZONE
    _close_trick_window(game)
    _step(game, _wugu_pick(game))
    assert game.state.location_of(trick_id) == DISCARD_PILE


def test_wugu_deck_insufficient_reshuffles_and_reveals() -> None:
    game = _fresh(3)
    _stock_tricks(game)
    # 让牌堆只剩1张：其余牌堆实体移入弃牌堆（可重洗）
    draw_ids = game.state.card_ids_in(DRAW_PILE)
    assert len(draw_ids) > 1
    keep = draw_ids[0]
    to_discard = draw_ids[1:]
    game._state = game.state.move_cards(
        {instance_id: DISCARD_PILE for instance_id in to_discard}
    )
    assert len(game.state.card_ids_in(DRAW_PILE)) == 1
    trick_id = _use_wugu(game)
    pool = game.state.card_ids_in(REVEALED_ZONE)
    assert len(pool) == 2
    assert keep in pool or keep in game.state.card_ids_in(DISCARD_PILE)
    reshuffles = [
        event
        for event in _events_of(game, EventType.CARD_MOVED)
        if event.payload.get("reason") == "reshuffle"
    ]
    assert reshuffles, "牌堆不足时五谷展示必须复用正式重洗逻辑"
    assert game.state.location_of(trick_id) == PROCESSING_ZONE
    game.state.assert_card_conservation()


def test_wugu_deck_insufficient_fails_closed() -> None:
    game = _fresh(3)
    _stock_tricks(game)
    draw_ids = game.state.card_ids_in(DRAW_PILE)
    game._state = game.state.move_cards(
        {
            instance_id: ZoneRef.hand("p1" if _me(game) == "p2" else "p2")
            for instance_id in draw_ids
        }
    )
    assert not game.state.card_ids_in(DRAW_PILE)
    assert not game.state.card_ids_in(DISCARD_PILE)
    with pytest.raises(ProductionBatchDeckExhaustedError):
        _use_wugu(game)


# ----------------------------------------------------------------------
# B. 五谷：选择句柄与失败关闭
# ----------------------------------------------------------------------


def test_wugu_pick_payload_binds_window_pool_digest_and_state_hash() -> None:
    game = _fresh(3)
    _stock_tricks(game)
    _use_wugu(game)
    _close_trick_window(game)
    pick = _wugu_pick(game)
    payload = pick.payload
    assert payload["operation"] == "pick_wugu_card"
    assert payload["user_id"] == _me(game)
    assert payload["target_id"] == _me(game)
    assert payload["target_index"] == 0
    assert payload["window_id"] == game.runtime.pending_wugu.window_id
    assert payload["pool_digest"] == game.runtime.pending_wugu.pool_digest
    assert payload["state_hash"] == state_sha256(
        canonical_state_snapshot(game.state)
    )
    assert payload["card_instance_id"] == pick.card_instance_id
    assert "pool_index" in payload


def test_wugu_stale_pool_digest_rejected() -> None:
    game = _fresh(3)
    _stock_tricks(game)
    _use_wugu(game)
    _close_trick_window(game)
    old_pick = _wugu_pick(game)
    picked_id = old_pick.card_instance_id
    _step(game, old_pick)
    _close_trick_window(game)
    # 当前窗口的合法选牌动作被替换为过期池摘要：直接应用被拒绝
    fresh = _wugu_pick(game)
    forged = LegalAction(
        action_type=ActionType.MOVE_CARD,
        actor_id=fresh.actor_id,
        card_instance_id=fresh.card_instance_id,
        target_ids=fresh.target_ids,
        payload={
            **dict(fresh.payload),
            "pool_digest": "0" * 64,
        },
        action_id="act_wugu_stale_digest",
    )
    context = game._context()
    adapter = game.formal_registry.adapter_for(WUGU)
    with pytest.raises(InvalidActionError, match="展示池摘要已过期"):
        adapter.apply_action(game.state, context, forged)
    # 池中唯一实体移除后，旧选牌动作的实体不再属于展示池
    assert picked_id not in game.state.card_ids_in(REVEALED_ZONE)


def test_wugu_old_target_window_replay_rejected() -> None:
    game = _fresh(3)
    _stock_tricks(game)
    _use_wugu(game)
    _close_trick_window(game)
    first_pick = _wugu_pick(game)
    _step(game, first_pick)
    _close_trick_window(game)
    # 当前目标已是第二目标：第一目标的旧窗口动作直接应用被拒绝
    context = game._context()
    adapter = game.formal_registry.adapter_for(WUGU)
    with pytest.raises(
        InvalidActionError,
        match="目标不是当前五谷目标|选择窗口已过期",
    ):
        adapter.apply_action(game.state, context, first_pick)


def test_wugu_non_current_target_cannot_pick() -> None:
    game = _fresh(3)
    _stock_tricks(game)
    _use_wugu(game)
    _close_trick_window(game)
    # 非当前目标的动作集合为空
    assert game.current_actor_id == _me(game)
    actions_for_other = [
        action
        for action in game.legal_actions()
        if action.payload.get("operation") == "pick_wugu_card"
        and action.actor_id == _other(game)
    ]
    assert actions_for_other == []
    # 直接提交绑定非当前目标的选牌被拒绝
    pick = _wugu_pick(game)
    forged_actor = LegalAction(
        action_type=ActionType.MOVE_CARD,
        actor_id=_me(game),
        card_instance_id=next(
            instance_id
            for instance_id in game.state.card_ids_in(REVEALED_ZONE)
        ),
        target_ids=(_other(game),),
        payload={
            **dict(pick.payload),
            "target_id": _other(game),
        },
        action_id="act_wugu_wrong_actor",
    )
    context = game._context()
    adapter = game.formal_registry.adapter_for(WUGU)
    with pytest.raises(InvalidActionError, match="目标不是当前五谷目标"):
        adapter.apply_action(game.state, context, forged_actor)


def test_wugu_out_of_pool_entity_rejected() -> None:
    game = _fresh(3)
    _stock_tricks(game)
    _use_wugu(game)
    _close_trick_window(game)
    pick = _wugu_pick(game)
    outside = next(
        instance_id
        for instance_id in game.state.card_ids_in(DRAW_PILE)
        if instance_id not in game.state.card_ids_in(REVEALED_ZONE)
    )
    forged = LegalAction(
        action_type=ActionType.MOVE_CARD,
        actor_id=pick.actor_id,
        card_instance_id=outside,
        target_ids=pick.target_ids,
        payload={
            **dict(pick.payload),
            "card_instance_id": outside,
        },
        action_id="act_wugu_outside",
    )
    context = game._context()
    adapter = game.formal_registry.adapter_for(WUGU)
    with pytest.raises(InvalidActionError, match="当前展示池"):
        adapter.apply_action(game.state, context, forged)


def test_wugu_duplicate_pick_rejected() -> None:
    game = _fresh(3)
    _stock_tricks(game)
    _use_wugu(game)
    _close_trick_window(game)
    pick = _wugu_pick(game)
    picked_id = pick.card_instance_id
    _step(game, pick)
    # 被选走的牌已离开展示池，重复选择同一实体被拒绝
    _close_trick_window(game)
    context = game._context()
    adapter = game.formal_registry.adapter_for(WUGU)
    duplicate = LegalAction(
        action_type=ActionType.MOVE_CARD,
        actor_id=game.current_actor_id,
        card_instance_id=picked_id,
        target_ids=(game.current_actor_id,),
        payload={
            "operation": "pick_wugu_card",
            "card_key": WUGU,
            "trick_instance_id": game.runtime.pending_wugu.trick_instance_id,
            "root_trick_instance_id": (
                game.runtime.pending_wugu.trick_instance_id
            ),
            "user_id": game.runtime.pending_wugu.user_id,
            "target_id": game.current_actor_id,
            "target_index": game.runtime.pending_wugu.current_target_index,
            "window_id": game.runtime.pending_wugu.window_id,
            "pool_digest": game.runtime.pending_wugu.pool_digest,
            "state_hash": state_sha256(
                canonical_state_snapshot(game.state)
            ),
            "card_instance_id": picked_id,
        },
        action_id="act_wugu_duplicate",
    )
    with pytest.raises(InvalidActionError, match="当前展示池"):
        adapter.apply_action(game.state, context, duplicate)


def test_wugu_cross_session_pick_rejected() -> None:
    game = _fresh(3)
    _stock_tricks(game)
    _use_wugu(game)
    _close_trick_window(game)
    pick = _wugu_pick(game)
    other_game = _fresh(11)
    _stock_tricks(other_game)
    _use_wugu(other_game)
    _close_trick_window(other_game)
    context = other_game._context()
    adapter = other_game.formal_registry.adapter_for(WUGU)
    with pytest.raises(InvalidActionError):
        adapter.apply_action(other_game.state, context, pick)


def test_wugu_forged_use_action_not_in_legal_set() -> None:
    game = _fresh(3)
    _stock_tricks(game)
    context = game._context()
    trick_id = next(
        instance_id
        for instance_id in game.state.card_ids_in(ZoneRef.hand(_me(game)))
        if game.state.cards_by_id[instance_id].card_key == WUGU
    )
    forged = LegalAction(
        action_type=ActionType.USE_CARD,
        actor_id=_me(game),
        card_instance_id=trick_id,
        target_ids=(),
        payload={
            "operation": "use_wugu",
            "card_key": WUGU,
            "card_name": "五谷丰登",
        },
        action_id="act_wugu_forged",
    )
    with pytest.raises(InvalidActionError, match="不在当前最新合法动作集合"):
        validate_action(game.state, context, forged, game.registry)


# ----------------------------------------------------------------------
# C. 铁索：注册表与正常使用
# ----------------------------------------------------------------------


def test_tiesuo_registry_and_six_entities() -> None:
    game = _fresh(3)
    registry = game.formal_registry
    assert TIESUO in registry.implemented_card_keys
    records = registry.instances_of(TIESUO)
    assert len(records) == 6
    assert len({record.instance_id for record in records}) == 6
    adapter = registry.adapter_for(TIESUO)
    assert adapter.implemented is True and adapter.tested is True
    spec = registry.rule_spec_for(TIESUO)
    assert spec["chain_damage_implemented"] is False
    assert spec["full_semantics_complete"] is False
    assert spec["recast"]["legal"] is True
    assert spec["recast"]["no_card_used_or_played"] is True


def test_tiesuo_single_target_toggles_chained() -> None:
    game = _fresh(3)
    wugu_ids, tiesuo_ids = _stock_tricks(game)
    assert tiesuo_ids
    action = _action(
        game, "use_tiesuo", card_key=TIESUO, targets=(_other(game),)
    )
    assert action is not None
    _step(game, action)
    assert game.phase is ProductionPhase.TRICK_RESPONSE
    _close_trick_window(game)
    assert game.state.players_by_id[_other(game)].chained is True
    assert game.state.players_by_id[_me(game)].chained is False
    assert game.phase is ProductionPhase.PLAY


def test_tiesuo_two_targets_normalized_and_both_toggled() -> None:
    game = _fresh(3)
    _stock_tricks(game)
    action = _action(
        game,
        "use_tiesuo",
        card_key=TIESUO,
        targets=(_me(game), _other(game)),
    )
    assert action is not None
    _step(game, action)
    group = game.runtime.pending_group_trick
    assert group is not None
    # 服务器以使用者为锚点规范化：使用者优先结算
    assert group.target_sequence == (_me(game), _other(game))
    _close_trick_window(game)
    assert game.state.players_by_id[_me(game)].chained is True
    _close_trick_window(game)
    assert game.state.players_by_id[_other(game)].chained is True
    assert game.phase is ProductionPhase.PLAY


def test_tiesuo_server_normalizes_submitted_order() -> None:
    game = _fresh(3)
    _stock_tricks(game)
    adapter = game.formal_registry.adapter_for(TIESUO)
    context = game._context()
    trick_id = next(
        instance_id
        for instance_id in game.state.card_ids_in(ZoneRef.hand(_me(game)))
        if game.state.cards_by_id[instance_id].card_key == TIESUO
    )
    # 玩家以相反顺序提交：服务器仍按行动顺序结算
    reversed_order = LegalAction(
        action_type=ActionType.USE_CARD,
        actor_id=_me(game),
        card_instance_id=trick_id,
        target_ids=(_other(game), _me(game)),
        payload={
            "operation": "use_tiesuo",
            "card_key": TIESUO,
            "card_name": "铁索连环",
        },
        action_id="act_tiesuo_reversed",
    )
    # 未规范化动作不在合法集合中（validate 失败关闭）
    with pytest.raises(InvalidActionError, match="不在当前最新合法动作集合"):
        validate_action(game.state, context, reversed_order, game.registry)
    # 直接应用仍由服务器规范化，不信任提交顺序
    adapter.apply_action(game.state, context, reversed_order)
    group = game.runtime.pending_group_trick
    assert group is not None
    assert group.target_sequence == (_me(game), _other(game))


def test_tiesuo_duplicate_target_rejected() -> None:
    game = _fresh(3)
    _stock_tricks(game)
    # 重复目标在合法动作边界即被拒绝（LegalAction 不允许重复角色），
    # 合法枚举也绝不产生重复目标的使用动作
    with pytest.raises(ValueError, match="目标角色不能重复"):
        LegalAction(
            action_type=ActionType.USE_CARD,
            actor_id=_me(game),
            card_instance_id="sgs-mobile-20260725-071",
            target_ids=(_me(game), _me(game)),
            payload={
                "operation": "use_tiesuo",
                "card_key": TIESUO,
                "card_name": "铁索连环",
            },
            action_id="act_tiesuo_duplicate",
        )
    for action in game.legal_actions():
        if action.payload.get("operation") == "use_tiesuo":
            assert len(action.target_ids) == len(set(action.target_ids))


def test_tiesuo_empty_and_three_targets_rejected() -> None:
    game = _fresh(3)
    _stock_tricks(game)
    adapter = game.formal_registry.adapter_for(TIESUO)
    context = game._context()
    trick_id = next(
        instance_id
        for instance_id in game.state.card_ids_in(ZoneRef.hand(_me(game)))
        if game.state.cards_by_id[instance_id].card_key == TIESUO
    )
    empty = LegalAction(
        action_type=ActionType.USE_CARD,
        actor_id=_me(game),
        card_instance_id=trick_id,
        target_ids=(),
        payload={
            "operation": "use_tiesuo",
            "card_key": TIESUO,
            "card_name": "铁索连环",
        },
        action_id="act_tiesuo_empty",
    )
    with pytest.raises(InvalidActionError, match="一名或两名"):
        adapter.apply_action(game.state, context, empty)
    # 双人入口无法构造三名互异目标；三名目标（含重复）在动作边界即拒绝
    with pytest.raises(ValueError, match="目标角色不能重复"):
        LegalAction(
            action_type=ActionType.USE_CARD,
            actor_id=_me(game),
            card_instance_id=trick_id,
            target_ids=("p1", "p2", "p1"),
            payload={
                "operation": "use_tiesuo",
                "card_key": TIESUO,
                "card_name": "铁索连环",
            },
            action_id="act_tiesuo_three",
        )
    assert all(
        len(action.target_ids) <= 2
        for action in game.legal_actions()
        if action.payload.get("operation") == "use_tiesuo"
    )


def test_tiesuo_use_requires_hand_entity() -> None:
    game = _fresh(3)
    _stock_tricks(game)
    adapter = game.formal_registry.adapter_for(TIESUO)
    context = game._context()
    trick_id = next(
        instance_id
        for instance_id in game.state.card_ids_in(ZoneRef.hand(_me(game)))
        if game.state.cards_by_id[instance_id].card_key == TIESUO
    )
    game._state = game.state.move_card(trick_id, DISCARD_PILE)
    stale = LegalAction(
        action_type=ActionType.USE_CARD,
        actor_id=_me(game),
        card_instance_id=trick_id,
        target_ids=(_other(game),),
        payload={
            "operation": "use_tiesuo",
            "card_key": TIESUO,
            "card_name": "铁索连环",
        },
        action_id="act_tiesuo_stale",
    )
    with pytest.raises(InvalidActionError, match="真实手牌"):
        adapter.apply_action(game.state, context, stale)


def test_tiesuo_per_target_wuxie_windows_and_single_cancel() -> None:
    game = _fresh(3)
    _stock_tricks(game)
    _step(
        game,
        _action(
            game,
            "use_tiesuo",
            card_key=TIESUO,
            targets=(_me(game), _other(game)),
        ),
    )
    first_window = game.runtime.response_window_id
    assert first_window is not None and first_window.endswith("gt0:dec0")
    # 第一目标被无懈：不改变横置状态
    wuxie = _action(game, "use_wuxie")
    assert wuxie is not None
    _step(game, wuxie)
    _close_trick_window(game)
    assert game.state.players_by_id[_me(game)].chained is False
    cancelled = _events_of(game, EventType.CARD_EFFECT_CANCELLED)
    assert len(cancelled) == 1
    assert cancelled[0].target_ids == (_me(game),)
    # 第二目标独立窗口：未被无懈，切换横置
    second_window = game.runtime.response_window_id
    assert second_window is not None and second_window.endswith("gt1:dec0")
    _close_trick_window(game)
    assert game.state.players_by_id[_other(game)].chained is True
    assert game.state.players_by_id[_me(game)].chained is False
    assert game.phase is ProductionPhase.PLAY


def test_tiesuo_false_to_true_and_true_to_false() -> None:
    game = _fresh(3)
    _stock_tricks(game)
    _step(
        game,
        _action(
            game,
            "use_tiesuo",
            card_key=TIESUO,
            targets=(_other(game),),
        ),
    )
    _close_trick_window(game)
    assert game.state.players_by_id[_other(game)].chained is True
    # 已横置角色再次成为目标：解除横置
    _step(
        game,
        _action(
            game,
            "use_tiesuo",
            card_key=TIESUO,
            targets=(_other(game),),
        ),
    )
    _close_trick_window(game)
    assert game.state.players_by_id[_other(game)].chained is False


def test_tiesuo_chained_state_event_fields() -> None:
    game = _fresh(3)
    _stock_tricks(game)
    use = _action(
        game,
        "use_tiesuo",
        card_key=TIESUO,
        targets=(_other(game),),
    )
    assert use is not None and use.card_instance_id is not None
    trick_id = use.card_instance_id
    _step(game, use)
    _close_trick_window(game)
    events = _events_of(game, EventType.CHAINED_STATE)
    assert len(events) == 1
    event = events[0]
    assert event.card_instance_id == trick_id
    assert event.card_key == TIESUO
    assert event.target_ids == (_other(game),)
    payload = event.payload
    assert payload["actor"] == _me(game)
    assert payload["target"] == _other(game)
    assert payload["old_value"] is False
    assert payload["new_value"] is True
    assert payload["root_card_instance_id"] == trick_id
    assert payload["reason"] == "tiesuolianhuan_toggle"
    assert payload["target_index"] == 0
    assert payload["target_count"] == 1


def test_tiesuo_trick_stays_in_processing_until_all_targets() -> None:
    game = _fresh(3)
    _stock_tricks(game)
    use = _action(
        game,
        "use_tiesuo",
        card_key=TIESUO,
        targets=(_me(game), _other(game)),
    )
    assert use is not None and use.card_instance_id is not None
    trick_id = use.card_instance_id
    _step(game, use)
    assert game.state.location_of(trick_id) == PROCESSING_ZONE
    _close_trick_window(game)
    assert game.state.location_of(trick_id) == PROCESSING_ZONE
    _close_trick_window(game)
    assert game.state.location_of(trick_id) == DISCARD_PILE


# ----------------------------------------------------------------------
# D. 铁索：重铸
# ----------------------------------------------------------------------


def test_tiesuo_recast_is_not_use_or_play() -> None:
    game = _fresh(3)
    _stock_tricks(game)
    action = _action(game, "recast_tiesuo", card_key=TIESUO)
    assert action is not None
    _step(game, action)
    assert _events_of(game, EventType.CARD_USED) == []
    assert _events_of(game, EventType.CARD_PLAYED) == []
    recasts = _events_of(game, EventType.CARD_RECAST)
    assert len(recasts) == 1
    assert recasts[0].card_user == _me(game)
    assert recasts[0].target_ids == ()
    assert recasts[0].payload["reason"] == "recast"
    assert recasts[0].payload["recast_by"] == _me(game)
    assert recasts[0].payload["source"]["kind"] == "hand"
    assert recasts[0].payload["destination"]["kind"] == "discard_pile"


def test_tiesuo_recast_discards_and_draws_one() -> None:
    game = _fresh(3)
    _stock_tricks(game)
    recast = _action(game, "recast_tiesuo", card_key=TIESUO)
    assert recast is not None and recast.card_instance_id is not None
    recast_id = recast.card_instance_id
    hand_before = len(game.state.card_ids_in(ZoneRef.hand(_me(game))))
    _step(game, recast)
    assert game.state.location_of(recast_id) == DISCARD_PILE
    assert len(game.state.card_ids_in(ZoneRef.hand(_me(game)))) == hand_before
    gained = _events_of(game, EventType.CARD_GAINED)
    assert gained[-1].target_ids == (_me(game),)
    assert gained[-1].payload["reason"] == "tiesuo_recast"
    assert game.phase is ProductionPhase.PLAY


def test_tiesuo_recast_targetless_required() -> None:
    game = _fresh(3)
    _stock_tricks(game)
    adapter = game.formal_registry.adapter_for(TIESUO)
    context = game._context()
    trick_id = next(
        instance_id
        for instance_id in game.state.card_ids_in(ZoneRef.hand(_me(game)))
        if game.state.cards_by_id[instance_id].card_key == TIESUO
    )
    with_targets = LegalAction(
        action_type=ActionType.MOVE_CARD,
        actor_id=_me(game),
        card_instance_id=trick_id,
        target_ids=(_other(game),),
        payload={
            "operation": "recast_tiesuo",
            "card_key": TIESUO,
            "card_name": "铁索连环",
        },
        action_id="act_recast_targets",
    )
    with pytest.raises(InvalidActionError, match="重铸不能指定目标"):
        adapter.apply_action(game.state, context, with_targets)


def test_tiesuo_recast_non_tiesuo_rejected() -> None:
    game = _fresh(3)
    _stock_tricks(game)
    adapter = game.formal_registry.adapter_for(TIESUO)
    context = game._context()
    non_tiesuo = next(
        instance_id
        for instance_id in game.state.card_ids_in(ZoneRef.hand(_me(game)))
        if game.state.cards_by_id[instance_id].card_key != TIESUO
    )
    forged = LegalAction(
        action_type=ActionType.MOVE_CARD,
        actor_id=_me(game),
        card_instance_id=non_tiesuo,
        target_ids=(),
        payload={
            "operation": "recast_tiesuo",
            "card_key": TIESUO,
            "card_name": "铁索连环",
        },
        action_id="act_recast_wrong_card",
    )
    with pytest.raises(InvalidActionError, match="必须属于【铁索连环】"):
        adapter.apply_action(game.state, context, forged)


def test_tiesuo_recast_non_hand_rejected() -> None:
    game = _fresh(3)
    _stock_tricks(game)
    adapter = game.formal_registry.adapter_for(TIESUO)
    context = game._context()
    trick_id = next(
        instance_id
        for instance_id in game.state.card_ids_in(ZoneRef.hand(_me(game)))
        if game.state.cards_by_id[instance_id].card_key == TIESUO
    )
    game._state = game.state.move_card(trick_id, DISCARD_PILE)
    forged = LegalAction(
        action_type=ActionType.MOVE_CARD,
        actor_id=_me(game),
        card_instance_id=trick_id,
        target_ids=(),
        payload={
            "operation": "recast_tiesuo",
            "card_key": TIESUO,
            "card_name": "铁索连环",
        },
        action_id="act_recast_not_hand",
    )
    with pytest.raises(InvalidActionError, match="自己手牌"):
        adapter.apply_action(game.state, context, forged)


def test_tiesuo_recast_opens_no_wuxie_window() -> None:
    game = _fresh(3)
    _stock_tricks(game)
    _step(game, _action(game, "recast_tiesuo", card_key=TIESUO))
    assert game.phase is ProductionPhase.PLAY
    assert game.runtime.response_window_id is None
    assert game.runtime.pending_trick is None


# ----------------------------------------------------------------------
# E. 状态哈希、未实现传导与终局不变量
# ----------------------------------------------------------------------


def test_chained_enters_state_snapshot_and_hash() -> None:
    game = _fresh(3)
    _stock_tricks(game)
    snapshot = canonical_state_snapshot(game.state)
    assert all("chained" in player for player in snapshot["players"])
    before = state_sha256(canonical_state_snapshot(game.state))
    _step(
        game,
        _action(
            game,
            "use_tiesuo",
            card_key=TIESUO,
            targets=(_other(game),),
        ),
    )
    _close_trick_window(game)
    after = state_sha256(canonical_state_snapshot(game.state))
    assert before != after
    snapshot_after = canonical_state_snapshot(game.state)
    chained_by_id = {
        player["player_id"]: player["chained"]
        for player in snapshot_after["players"]
    }
    assert chained_by_id[_other(game)] is True


def test_property_damage_does_not_conduct_in_this_batch() -> None:
    game = _fresh(3)
    _stock_tricks(game)
    # 横置一名角色后，属性杀造成伤害不得触发任何传导事件
    _step(
        game,
        _action(
            game,
            "use_tiesuo",
            card_key=TIESUO,
            targets=(_other(game),),
        ),
    )
    _close_trick_window(game)
    assert game.state.players_by_id[_other(game)].chained is True
    slash = _action(game, "use_slash")
    if slash is not None:
        _step(game, slash)
        # 杀响应窗口：唯一响应者放弃出闪即关闭
        pass_action = _action(game, "pass_slash_response")
        assert pass_action is not None
        _step(game, pass_action)
    # 传导基础设施未实现：只有铁索切换的横置状态事件，属性伤害不触发传导
    assert len(_events_of(game, EventType.CHAINED_STATE)) == 1
    assert len(_events_of(game, EventType.DAMAGE)) <= 1
    spec = game.formal_registry.rule_spec_for(TIESUO)
    assert spec["chain_damage_implemented"] is False
    assert spec["full_semantics_complete"] is False


def test_finished_state_has_no_temporary_zone_leftovers() -> None:
    game = _fresh(3, player_hp=(1, 1), initial_hand_count=4)
    _stock_tricks(game)
    if _action(game, "use_wugu", card_key=WUGU) is not None:
        _use_wugu(game)
        _close_trick_window(game)
        _step(game, _wugu_pick(game))
        _close_trick_window(game)
        _step(game, _wugu_pick(game))
    assert not game.state.card_ids_in(REVEALED_ZONE)
    # 打到胜利：终局不允许实体滞留在临时区域
    game.run(max_steps=400)
    assert game.is_finished
    assert not game.state.card_ids_in(REVEALED_ZONE)
    assert not game.state.card_ids_in(PROCESSING_ZONE)


# ----------------------------------------------------------------------
# F. 严格回放
# ----------------------------------------------------------------------


_WUGU_REPLAY_SPECS = [
    {"operation": "use_wugu", "card_key": WUGU},
    {"operation": "pass_trick_response"},
    {"operation": "pass_trick_response"},
    {"operation": "pick_wugu_card", "pool_index": 0},
    {"operation": "pass_trick_response"},
    {"operation": "pass_trick_response"},
    {"operation": "pick_wugu_card", "pool_index": 0},
]

_TIESUO_REPLAY_SPECS = [
    {
        "operation": "use_tiesuo",
        "card_key": TIESUO,
        "target_count": 2,
        "include_self": True,
    },
    {"operation": "pass_trick_response"},
    {"operation": "pass_trick_response"},
    {"operation": "pass_trick_response"},
    {"operation": "pass_trick_response"},
    {"operation": "recast_tiesuo", "card_key": TIESUO},
]


@pytest.fixture(scope="module")
def wugu_replay_record() -> ProductionReexecutionReplay:
    return record_reference_production_batch(
        seed=9,
        initial_hand_count=6,
        controller=_TrickReplayController(list(_WUGU_REPLAY_SPECS)),
    )


@pytest.fixture(scope="module")
def tiesuo_replay_record() -> ProductionReexecutionReplay:
    return record_reference_production_batch(
        seed=153,
        initial_hand_count=6,
        controller=_TrickReplayController(list(_TIESUO_REPLAY_SPECS)),
    )


def test_wugu_replay_reexecutes(
    wugu_replay_record: ProductionReexecutionReplay,
) -> None:
    record = wugu_replay_record
    result = reexecute_production_replay(record)
    assert result.verified is True
    assert result.decision_count == len(record.decisions)
    assert result.final_execution_hash == record.outcome["final_execution_hash"]
    revealed = _events_with_type(record.events, "card_revealed")
    assert len(revealed) == 2
    assert revealed[0]["payload"]["reason"] == "wugu_reveal"
    picked = [
        event
        for event in record.events
        if event.get("event_type") == "group_target_resolved"
        and event.get("payload", {}).get("result") == "picked"
    ]
    assert len(picked) == 2


def test_tiesuo_replay_reexecutes(
    tiesuo_replay_record: ProductionReexecutionReplay,
) -> None:
    record = tiesuo_replay_record
    result = reexecute_production_replay(record)
    assert result.verified is True
    chained_events = _events_with_type(record.events, "chained_state")
    assert len(chained_events) == 2
    assert chained_events[0]["payload"]["old_value"] is False
    assert chained_events[0]["payload"]["new_value"] is True
    recast = _events_with_type(record.events, "card_recast")
    assert len(recast) == 1
    assert recast[0]["payload"]["reason"] == "recast"


def test_wugu_replay_tamper_pick_card_fails(
    wugu_replay_record: ProductionReexecutionReplay,
) -> None:
    record = wugu_replay_record
    tampered = _load_tampered(record)
    pick_decision = next(
        decision
        for decision in tampered["decisions"]
        if decision["chosen_action"].get("payload", {}).get("operation")
        == "pick_wugu_card"
    )
    pick_decision["chosen_action"]["payload"]["card_instance_id"] = (
        "forged-out-of-pool"
    )
    rebuilt = ProductionReexecutionReplay.from_dict(tampered)
    with pytest.raises(ProductionReplayDivergenceError):
        reexecute_production_replay(rebuilt)


def test_wugu_replay_tamper_pool_digest_fails(
    wugu_replay_record: ProductionReexecutionReplay,
) -> None:
    record = wugu_replay_record
    tampered = _load_tampered(record)
    for decision in tampered["decisions"]:
        metadata = decision.get("context", {}).get("metadata", {})
        wugu = metadata.get("pending_wugu")
        if wugu and wugu.get("pool_digest"):
            wugu["pool_digest"] = "0" * 64
            break
    else:
        raise AssertionError("回放决策中必须存在五谷池摘要上下文")
    rebuilt = ProductionReexecutionReplay.from_dict(tampered)
    with pytest.raises(ProductionReplayDivergenceError):
        reexecute_production_replay(rebuilt)


def test_wugu_replay_delete_reveal_event_fails(
    wugu_replay_record: ProductionReexecutionReplay,
) -> None:
    record = wugu_replay_record
    tampered = _load_tampered(record)
    tampered["events"] = [
        event
        for event in tampered["events"]
        if not (
            event.get("event_type") == "card_revealed"
            and event.get("payload", {}).get("pool_index") == 1
        )
    ]
    with pytest.raises(ProductionReplayFormatError):
        ProductionReexecutionReplay.from_dict(tampered)


def test_tiesuo_replay_tamper_chained_values_fails(
    tiesuo_replay_record: ProductionReexecutionReplay,
) -> None:
    record = tiesuo_replay_record
    tampered = _load_tampered(record)
    chained_event = next(
        event
        for event in tampered["events"]
        if event.get("event_type") == "chained_state"
    )
    chained_event["payload"]["old_value"] = True
    chained_event["payload"]["new_value"] = False
    with pytest.raises(ProductionReplayFormatError):
        ProductionReexecutionReplay.from_dict(tampered)


def test_tiesuo_replay_tamper_target_order_fails(
    tiesuo_replay_record: ProductionReexecutionReplay,
) -> None:
    record = tiesuo_replay_record
    tampered = _load_tampered(record)
    for decision in tampered["decisions"]:
        metadata = decision.get("context", {}).get("metadata", {})
        group = metadata.get("pending_group_trick")
        if group and len(group.get("target_sequence", [])) == 2:
            group["target_sequence"] = list(
                reversed(group["target_sequence"])
            )
            break
    else:
        raise AssertionError("回放决策中必须存在铁索目标序列上下文")
    rebuilt = ProductionReexecutionReplay.from_dict(tampered)
    with pytest.raises(ProductionReplayDivergenceError):
        reexecute_production_replay(rebuilt)


def test_player_visible_replay_shows_pool_but_no_private_material(
    wugu_replay_record: ProductionReexecutionReplay,
) -> None:
    record = wugu_replay_record
    view = record.player_visible_payload()
    assert view["player_visible"] is True
    assert "authoritative_private" not in view
    blob = json.dumps(view, ensure_ascii=False)
    secret = record.authoritative_private["session_secret_hex"]
    assert secret not in blob
    revealed = _events_with_type(view["events"], "card_revealed")
    assert len(revealed) == 2
    # 跨玩家隐私边界：另一名玩家从未公开化的初始手牌不得出现在
    # 其所有者之外的决策材料中（所有者自己出牌阶段的合法动作枚举
    # 自己的手牌是既有生产口径，属于自信息）。
    game = ProductionBasicCardBatch(seed=9, initial_hand_count=6)
    other_player = "p1" if game._first_player_id == "p2" else "p2"
    other_hand = set(game.state.card_ids_in(ZoneRef.hand(other_player)))
    publicized_ids = {
        event["card_instance_id"]
        for event in view["events"]
        if event.get("event_type")
        in ("card_played", "card_used", "card_revealed", "card_recast")
    }
    never_publicized = other_hand - publicized_ids
    for instance_id in never_publicized:
        leaked_outside_owner = [
            decision
            for decision in view["decisions"]
            if decision.get("context", {}).get("actor_id") != other_player
            and instance_id
            in json.dumps(
                [decision["chosen_action"], *decision["legal_actions"]],
                ensure_ascii=False,
            )
        ]
        assert not leaked_outside_owner, (
            f"实体{instance_id}在非所有者决策材料中被泄露"
        )
    # 玩家可见导出缺少权威私有材料，权威重执行必须失败关闭
    with pytest.raises(ProductionReplayFormatError):
        ProductionReexecutionReplay.from_dict(view)


def test_authoritative_replay_reexecutes_rather_than_restores(
    tiesuo_replay_record: ProductionReexecutionReplay,
) -> None:
    record = tiesuo_replay_record
    assert record.header["test_only"] is False
    assert record.header["formal_result"] is False
    assert len(record.decisions) > 0
    result = reexecute_production_replay(record)
    assert result.verified is True
    assert result.event_count == len(record.events)
    assert result.final_game_state_hash == (
        record.outcome["final_game_state_hash"]
    )
