# -*- coding: utf-8 -*-
"""CP-04O：正式弃牌阶段与权威回合循环基础设施的验收测试。

覆盖：标准回合顺序、弃牌阶段（手牌上限、选择N张→一次正式批量提交、动作安全）、延时
锦囊跳过阶段接入回合循环、每回合状态重置、死亡/胜利/下一行动者、
严格回放与玩家可见隐私、卡牌守恒。所有正向路径都经过真实生产注册表
与 enumerate_legal_actions -> validate_action -> apply_action；不使用
固定概率、固定收益、fallback 或自证式断言。
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
    GameState,
    PlayerState,
    ZoneRef,
)
from scripts.sgs_engine.production_batch import (
    BatchActionIdController,
    ProductionBatchFinishedError,
    ProductionBatchError,
    ProductionBasicCardBatch,
    ProductionPhase,
    ScriptedBatchController,
    _replace_player,
)
from scripts.sgs_engine.production_cards import (
    FormalCardRegistry,
    hand_limit_of,
)
from scripts.sgs_engine.production_replay import (
    ProductionReplayDivergenceError,
    ProductionReplayFormatError,
    ProductionReexecutionReplay,
    record_reference_production_batch,
    reexecute_production_replay,
)


# ----------------------------------------------------------------------
# 测试夹具与辅助
# ----------------------------------------------------------------------


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
    assert game.phase is ProductionPhase.PLAY
    return game


def _action(
    game: ProductionBasicCardBatch,
    operation: str,
    *,
    card_key: str | None = None,
    target: str | None = None,
) -> object | None:
    for action in game.legal_actions():
        if action.payload.get("operation") != operation:
            continue
        if card_key is not None and action.payload.get("card_key") != card_key:
            continue
        if target is not None and action.target_ids[0] != target:
            continue
        return action
    return None


def _step(game: ProductionBasicCardBatch, action: object) -> None:
    assert action is not None and getattr(action, "action_id", None), action
    game.step(BatchActionIdController(action.action_id))  # type: ignore[attr-defined]


def _proceed(game: ProductionBasicCardBatch, operation: str) -> None:
    action = next(
        a
        for a in game.legal_actions()
        if a.payload.get("operation") == operation
    )
    _step(game, action)


def _discard_to_end(
    game: ProductionBasicCardBatch,
    keep: tuple[str, ...] = (),
) -> None:
    """弃牌阶段：选择恰好超限数量的手牌并一次性提交（CP-04O 批量弃置）。

    ``keep`` 指定必须保留在手牌中的实体ID，选择时跳过这些牌；选择过程
    不移动牌，只有提交动作确认后全部选中牌才一次性离开手牌。"""
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
            and (
                action.card_instance_id is None
                or action.card_instance_id not in keep
            )
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


def _end_turn(game: ProductionBasicCardBatch) -> None:
    _proceed(game, "end_play_phase")
    _discard_to_end(game)
    assert game.phase is ProductionPhase.END
    _proceed(game, "end_turn")
    assert game.phase is ProductionPhase.PREPARE


def _complete_turn(game: ProductionBasicCardBatch) -> None:
    """从PREPARE开始完整走完当前角色回合（准备→判定→摸牌→出牌→弃牌→结束）。"""
    if game.phase is ProductionPhase.PREPARE:
        _proceed(game, "proceed_prepare")
        _proceed(game, "proceed_judgment")
        _proceed(game, "proceed_draw")
    _end_turn(game)


def _events_of(
    game: ProductionBasicCardBatch, event_type: EventType
) -> list[object]:
    return [event for event in game.events if event.event_type is event_type]


def _assert_conservation(game: ProductionBasicCardBatch) -> None:
    assert len(game.state.cards) == 160
    assert sum(
        len(game.state.card_ids_in(zone)) for zone in game.state.zone_order
    ) == 160
    for card in game.state.cards:
        locations = [
            zone
            for zone in game.state.zone_order
            if card.instance_id in game.state.card_ids_in(zone)
        ]
        assert len(locations) == 1


# 正式实体常量（来自 knowledge/三国杀牌堆数据.csv 的正式牌堆）
LEBUSI = "sgs_delayed_lebusi"
BINGLIANG = "sgs_delayed_bingliang"
SHANDIAN = "sgs_delayed_shandian"
TAO = "sgs_basic_tao"
LEBUSI_098 = "sgs-mobile-20260725-098"  # ♥6
LEBUSI_137 = "sgs-mobile-20260725-137"  # ♠6
BINGLIANG_151 = "sgs-mobile-20260725-151"  # ♠10
BINGLIANG_053 = "sgs-mobile-20260725-053"  # ♣4
SPADE_7_SHA = "sgs-mobile-20260725-140"  # ♠7 杀
SHANDIAN_117 = "sgs-mobile-20260725-117"  # ♥Q


def _use_delayed(
    game: ProductionBasicCardBatch,
    operation: str,
    key: str,
    target: str,
) -> str:
    """出牌阶段使用延时锦囊并返回实体ID；使用后必须仍处于出牌阶段。"""
    action = _action(game, operation, card_key=key, target=target)
    assert action is not None, f"出牌阶段必须能枚举{operation}使用动作"
    trick_id = action.card_instance_id
    assert trick_id is not None
    _step(game, action)
    assert game.phase is ProductionPhase.PLAY, "延时锦囊使用后不得打开普通锦囊窗口"
    return trick_id


def _put_draw_at(
    game: ProductionBasicCardBatch,
    instance_id: str,
    position: int,
) -> None:
    """把实体牌放到牌堆指定位置（0-based），其余相对顺序保持不变。"""
    if game.state.location_of(instance_id) != DRAW_PILE:
        game._state = game.state.move_card(instance_id, DRAW_PILE)
    pile = list(game.state.card_ids_in(DRAW_PILE))
    pile.remove(instance_id)
    pile.insert(position, instance_id)
    game._state = game.state.reorder_zone(DRAW_PILE, tuple(pile))


def _set_hp(
    game: ProductionBasicCardBatch,
    player_id: str,
    hp: int,
    max_hp: int | None = None,
) -> None:
    if max_hp is None:
        game._state = _replace_player(game.state, player_id, hp=hp)
        return
    game._state = replace(
        game.state,
        players=tuple(
            replace(player, hp=hp, max_hp=max_hp)
            if player.player_id == player_id
            else player
            for player in game.state.players
        ),
        revision=game.state.revision + 1,
    )


def _swap(game: ProductionBasicCardBatch, instance_id: str, dest: ZoneRef) -> None:
    """把实体牌移动到目标区域并保持160张牌守恒的确定性夹具。"""
    src = game.state.location_of(instance_id)
    if src == dest:
        return
    moves: dict[str, ZoneRef] = {}
    if dest.kind.value == "hand" and dest.owner_id is not None:
        hand_ids = list(game.state.card_ids_in(ZoneRef.hand(dest.owner_id)))
        if hand_ids:
            moves[hand_ids[0]] = src
    moves[instance_id] = dest
    game._state = game.state.move_cards(moves)


@pytest.fixture(scope="module")
def turn_cycle_record() -> ProductionReexecutionReplay:
    """参考控制器完整对局记录：覆盖多回合、弃牌与结束循环。"""
    return record_reference_production_batch(seed=3)


# ----------------------------------------------------------------------
# A. 标准回合
# ----------------------------------------------------------------------


def test_standard_phase_order_prepare_judgment_draw_play_discard_end() -> None:
    game = _fresh(seed=3)
    assert game.phase is ProductionPhase.PLAY
    assert game.current_player_id == "p1"
    assert game.runtime.turn_number == 1
    # 出牌阶段主动结束 → 手牌6>上限4 → 弃牌阶段
    _proceed(game, "end_play_phase")
    assert game.phase is ProductionPhase.DISCARD
    assert game.current_player_id == "p1"
    # 逐张弃置到上限后自动进入结束阶段
    _discard_to_end(game)
    assert game.phase is ProductionPhase.END
    _proceed(game, "end_turn")
    assert game.phase is ProductionPhase.PREPARE
    assert game.current_player_id == "p2"
    assert game.runtime.turn_number == 2
    _assert_conservation(game)


def test_end_play_phase_only_by_current_player() -> None:
    game = _fresh(seed=3)
    forged = LegalAction(
        action_type=ActionType.PASS,
        actor_id="p2",
        payload={"operation": "end_play_phase"},
        action_id="act_wrong_end_play",
    )
    with pytest.raises(InvalidActionError):
        validate_action(game.state, game._context(), forged, game.registry)


def test_full_turn_cycles_to_next_player_repeatedly() -> None:
    game = _fresh(seed=3)
    for expected_turn in (2, 3):
        _complete_turn(game)
        assert game.runtime.turn_number == expected_turn
        assert game.current_player_id == (
            "p1" if expected_turn % 2 == 1 else "p2"
        )


# ----------------------------------------------------------------------
# B. 弃牌阶段
# ----------------------------------------------------------------------


def _select(game: ProductionBasicCardBatch) -> object:
    """重新枚举并按实例ID确定性选择一张待弃手牌。"""
    action = min(
        (
            a
            for a in game.legal_actions()
            if a.payload.get("operation") == "select_discard_card"
        ),
        key=lambda a: a.card_instance_id or "",
    )
    _step(game, action)
    return action


def _submit(game: ProductionBasicCardBatch) -> object:
    """重新枚举并提交当前待弃集合。"""
    action = next(
        a
        for a in game.legal_actions()
        if a.payload.get("operation") == "discard_phase_submit"
    )
    _step(game, action)
    return action


def _forge_discard_action(
    game: ProductionBasicCardBatch,
    *,
    operation: str,
    actor_id: str,
    instance_id: object = None,
    payload: dict[str, object] | None = None,
) -> LegalAction:
    """构造伪造的弃牌阶段动作：action_id 未签发，validate 必须拒绝。"""
    return LegalAction(
        action_type=ActionType.CHOOSE_OPTION,
        actor_id=actor_id,
        card_instance_id=instance_id,
        target_ids=(actor_id,),
        payload={
            "operation": operation,
            **(payload or {}),
        },
        action_id="act_forged_discard",
    )


def test_discard_auto_passes_when_hand_equals_limit() -> None:
    game = _fresh(seed=3)
    # 手牌6张；先移2张到弃牌堆使手牌=4张（仅构造，不经过弃牌动作）
    hand_ids = list(game.state.card_ids_in(ZoneRef.hand("p1")))
    game._state = game.state.move_cards(
        {hand_ids[0]: DISCARD_PILE, hand_ids[1]: DISCARD_PILE}
    )
    assert len(game.state.card_ids_in(ZoneRef.hand("p1"))) == 4
    _proceed(game, "end_play_phase")
    # 手牌数==上限：自动完成弃牌阶段并进入结束阶段，不开放任何弃牌动作
    assert game.phase is ProductionPhase.END
    assert _action(game, "select_discard_card") is None
    assert _action(game, "discard_phase_submit") is None


def test_discard_auto_passes_when_hand_below_limit() -> None:
    game = _fresh(seed=3)
    hand_ids = list(game.state.card_ids_in(ZoneRef.hand("p1")))
    game._state = game.state.move_cards(
        {
            hand_ids[0]: DISCARD_PILE,
            hand_ids[1]: DISCARD_PILE,
            hand_ids[2]: DISCARD_PILE,
        }
    )
    _proceed(game, "end_play_phase")
    assert game.phase is ProductionPhase.END
    assert _action(game, "select_discard_card") is None
    assert _action(game, "discard_phase_submit") is None


def test_discard_batch_exactly_excess_selection_and_atomic_submit() -> None:
    """上限3手牌5：玩家必须一次提交恰好2张（清单1、3）。"""
    game = _fresh(seed=3)
    hand_ids = list(game.state.card_ids_in(ZoneRef.hand("p1")))
    game._state = game.state.move_cards({hand_ids[0]: DISCARD_PILE})
    _set_hp(game, "p1", 3, max_hp=3)
    assert len(game.state.card_ids_in(ZoneRef.hand("p1"))) == 5
    _proceed(game, "end_play_phase")
    assert game.phase is ProductionPhase.DISCARD
    # 未选满前没有提交入口
    assert _action(game, "discard_phase_submit") is None
    selected = _select(game)
    assert selected.card_instance_id is not None
    first_id = selected.card_instance_id
    assert _action(game, "discard_phase_submit") is None
    selected = _select(game)
    second_id = selected.card_instance_id
    assert second_id != first_id
    # 恰好2张后出现提交入口
    assert _action(game, "discard_phase_submit") is not None
    _submit(game)
    assert game.phase is ProductionPhase.END
    assert len(game.state.card_ids_in(ZoneRef.hand("p1"))) == 3
    assert {first_id, second_id}.issubset(
        set(game.state.card_ids_in(DISCARD_PILE))
    )
    _assert_conservation(game)


def test_discard_selection_before_submit_keeps_cards_in_hand() -> None:
    """确认前：被选择的牌仍在权威手牌区，不产生正式弃牌状态变化（清单2）。"""
    game = _fresh(seed=3)
    _proceed(game, "end_play_phase")
    assert game.phase is ProductionPhase.DISCARD
    hand_before = list(game.state.card_ids_in(ZoneRef.hand("p1")))
    events_before = len(game.events)
    _select(game)
    _select(game)
    # 选择过程不修改权威手牌区、手牌数与卡牌守恒
    assert list(game.state.card_ids_in(ZoneRef.hand("p1"))) == hand_before
    assert len(game.state.card_ids_in(ZoneRef.hand("p1"))) == 6
    selection_events = game.events[events_before:]
    assert not any(
        event.event_type
        in (EventType.CARD_MOVED, EventType.CARD_LOST, EventType.CARD_DISCARDED)
        for event in selection_events
    )
    _assert_conservation(game)
    # 提交前取消选择也不产生状态变化
    unselect = next(
        a
        for a in game.legal_actions()
        if a.payload.get("operation") == "unselect_discard_card"
    )
    _step(game, unselect)
    assert list(game.state.card_ids_in(ZoneRef.hand("p1"))) == hand_before
    selection_events = game.events[events_before:]
    assert not any(
        event.event_type
        in (EventType.CARD_MOVED, EventType.CARD_LOST, EventType.CARD_DISCARDED)
        for event in selection_events
    )


def test_discard_batch_all_selected_leave_hand_once_after_submit() -> None:
    """确认后：全部选中牌一次性离开手牌，5→3，一次弃牌阶段操作完成。"""
    game = _fresh(seed=3)
    hand_ids = list(game.state.card_ids_in(ZoneRef.hand("p1")))
    game._state = game.state.move_cards({hand_ids[0]: DISCARD_PILE})
    _set_hp(game, "p1", 3, max_hp=3)
    _proceed(game, "end_play_phase")
    selected_ids: set[str] = set()
    for _ in range(2):
        action = _select(game)
        assert action.card_instance_id is not None
        selected_ids.add(action.card_instance_id)
    before = len(game.events)
    _submit(game)
    new_events = game.events[before:]
    moved = [
        event
        for event in new_events
        if event.payload.get("reason") == "discard_phase"
    ]
    # 每张牌 CARD_MOVED＋CARD_LOST＋CARD_DISCARDED，且全部属于同一提交
    assert len(moved) == 6
    assert {event.card_instance_id for event in moved} == selected_ids
    assert len(
        {event.payload.get("window_id") for event in moved}
    ) == 1
    assert len(game.state.card_ids_in(ZoneRef.hand("p1"))) == 3
    assert selected_ids.issubset(set(game.state.card_ids_in(DISCARD_PILE)))
    _assert_conservation(game)


def test_discard_submit_under_selection_rejected_atomically() -> None:
    """少选1张：没有提交入口，伪造提交失败且状态完全不变（清单4）。"""
    game = _fresh(seed=3)
    _proceed(game, "end_play_phase")
    _select(game)  # 只选1张，excess=2
    assert _action(game, "discard_phase_submit") is None
    hand_before = list(game.state.card_ids_in(ZoneRef.hand("p1")))
    forged = _forge_discard_action(
        game, operation="discard_phase_submit", actor_id="p1"
    )
    with pytest.raises(InvalidActionError):
        validate_action(game.state, game._context(), forged, game.registry)
    assert game.phase is ProductionPhase.DISCARD
    assert list(game.state.card_ids_in(ZoneRef.hand("p1"))) == hand_before
    assert not _events_of(game, EventType.CARD_DISCARDED)


def test_discard_submit_over_selection_rejected_atomically() -> None:
    """多选1张：没有提交入口，伪造提交失败且状态完全不变（清单5）。"""
    game = _fresh(seed=3)
    _proceed(game, "end_play_phase")
    for _ in range(3):  # 手牌6、上限4、excess=2，选3张属于多选
        _select(game)
    assert _action(game, "discard_phase_submit") is None
    hand_before = list(game.state.card_ids_in(ZoneRef.hand("p1")))
    forged = _forge_discard_action(
        game, operation="discard_phase_submit", actor_id="p1"
    )
    with pytest.raises(InvalidActionError):
        validate_action(game.state, game._context(), forged, game.registry)
    assert game.phase is ProductionPhase.DISCARD
    assert list(game.state.card_ids_in(ZoneRef.hand("p1"))) == hand_before
    assert not _events_of(game, EventType.CARD_DISCARDED)
    # 取消一张后回到恰好excess，可正常提交
    for _ in range(1):
        unselect = next(
            a
            for a in game.legal_actions()
            if a.payload.get("operation") == "unselect_discard_card"
        )
        _step(game, unselect)
    _submit(game)
    assert game.phase is ProductionPhase.END


def test_discard_duplicate_selection_rejected() -> None:
    """重复选择同一张：已选牌不再枚举选择动作，伪造重复选择失败（清单6）。"""
    game = _fresh(seed=3)
    _proceed(game, "end_play_phase")
    first = _select(game)
    assert first.card_instance_id is not None
    remaining = [
        a.card_instance_id
        for a in game.legal_actions()
        if a.payload.get("operation") == "select_discard_card"
    ]
    assert first.card_instance_id not in remaining
    forged = _forge_discard_action(
        game,
        operation="select_discard_card",
        actor_id="p1",
        instance_id=first.card_instance_id,
        payload={"handle": "forged-handle"},
    )
    with pytest.raises(InvalidActionError):
        validate_action(game.state, game._context(), forged, game.registry)
    assert game.runtime.discard_phase_selected_ids == (
        first.card_instance_id,
    )


def test_discard_equipment_card_selection_rejected() -> None:
    """混入装备牌：选择动作只枚举手牌，伪造含装备/非手牌的选择失败（清单7）。"""
    game = _fresh(seed=3)
    _proceed(game, "end_play_phase")
    weapon_id = next(
        record.instance_id
        for record in game.formal_registry.records
        if record.card_key == "sgs_weapon_guanshifu"
    )
    game._state = game.state.move_card(
        weapon_id, ZoneRef.equipment("p1", "weapon")
    )
    hand_ids = set(game.state.card_ids_in(ZoneRef.hand("p1")))
    assert weapon_id not in hand_ids
    select_ids = {
        a.card_instance_id
        for a in game.legal_actions()
        if a.payload.get("operation") == "select_discard_card"
    }
    assert weapon_id not in select_ids
    forged = _forge_discard_action(
        game,
        operation="select_discard_card",
        actor_id="p1",
        instance_id=weapon_id,
        payload={"handle": "forged-equipment-handle"},
    )
    with pytest.raises(InvalidActionError):
        validate_action(game.state, game._context(), forged, game.registry)


def test_discard_other_player_card_selection_rejected() -> None:
    """混入其他角色牌：选择动作只枚举手牌，伪造他人手牌选择失败（清单8）。"""
    game = _fresh(seed=3)
    _proceed(game, "end_play_phase")
    other_hand_id = game.state.card_ids_in(ZoneRef.hand("p2"))[0]
    forged = _forge_discard_action(
        game,
        operation="select_discard_card",
        actor_id="p1",
        instance_id=other_hand_id,
        payload={"handle": "forged-other-hand-handle"},
    )
    with pytest.raises(InvalidActionError):
        validate_action(game.state, game._context(), forged, game.registry)


def test_discard_stale_after_hp_limit_change() -> None:
    """stale选择：枚举后HP变化导致hand_limit变化，旧选择/提交失败（清单9）。"""
    game = _fresh(seed=3)
    _proceed(game, "end_play_phase")
    first = _select(game)
    stale_select_id = first.action_id
    # 体力上限提升：hand_limit 6 >= 手牌6，excess=0
    _set_hp(game, "p1", 6, max_hp=6)
    assert hand_limit_of(game.state, "p1") == 6
    assert _action(game, "select_discard_card") is None
    assert _action(game, "discard_phase_submit") is None
    with pytest.raises(ProductionBatchError):
        game.step(BatchActionIdController(stale_select_id))  # type: ignore[attr-defined]


def test_discard_stale_after_hand_change() -> None:
    """stale选择：手牌变化导致excess变化，旧提交失败关闭（清单10）。"""
    game = _fresh(seed=3)
    _proceed(game, "end_play_phase")
    _select(game)
    # 外部效果把手牌移走一张：快照摘要变化，选择窗口失效
    hand_ids = list(game.state.card_ids_in(ZoneRef.hand("p1")))
    game._state = game.state.move_card(hand_ids[0], DISCARD_PILE)
    assert _action(game, "select_discard_card") is None
    assert _action(game, "discard_phase_submit") is None
    forged = _forge_discard_action(
        game, operation="discard_phase_submit", actor_id="p1"
    )
    with pytest.raises(InvalidActionError):
        validate_action(game.state, game._context(), forged, game.registry)


def test_discard_batch_card_conservation() -> None:
    """批量弃置前后卡牌守恒（清单11）。"""
    game = _fresh(seed=3)
    _proceed(game, "end_play_phase")
    for _ in range(2):
        _select(game)
    _assert_conservation(game)
    _submit(game)
    assert game.phase is ProductionPhase.END
    _assert_conservation(game)
    _proceed(game, "end_turn")
    _assert_conservation(game)


def test_discard_batch_completes_to_end() -> None:
    """批量弃置完成后自动进入结束阶段（清单12）。"""
    game = _fresh(seed=3)
    _proceed(game, "end_play_phase")
    for _ in range(2):
        _select(game)
    assert game.phase is ProductionPhase.DISCARD
    _submit(game)
    assert game.phase is ProductionPhase.END
    assert _action(game, "select_discard_card") is None
    assert _action(game, "discard_phase_submit") is None


def test_no_discard_submit_when_not_needed() -> None:
    """不需要弃牌时不开放任何弃牌动作（清单13）。"""
    game = _fresh(seed=3)
    hand_ids = list(game.state.card_ids_in(ZoneRef.hand("p1")))
    game._state = game.state.move_cards(
        {hand_ids[0]: DISCARD_PILE, hand_ids[1]: DISCARD_PILE}
    )
    _proceed(game, "end_play_phase")
    assert game.phase is ProductionPhase.END
    assert _action(game, "select_discard_card") is None
    assert _action(game, "discard_phase_submit") is None


def test_discard_submit_rejects_other_player() -> None:
    """非当前玩家不能提交（清单14）。"""
    game = _fresh(seed=3)
    _proceed(game, "end_play_phase")
    forged = _forge_discard_action(
        game, operation="discard_phase_submit", actor_id="p2"
    )
    with pytest.raises(InvalidActionError):
        validate_action(game.state, game._context(), forged, game.registry)
    forged_select = _forge_discard_action(
        game, operation="select_discard_card", actor_id="p2"
    )
    with pytest.raises(InvalidActionError):
        validate_action(
            game.state, game._context(), forged_select, game.registry
        )


def test_discard_cross_turn_forged_handle_rejected() -> None:
    """跨回合/跨会话/伪造句柄失败关闭（清单15）。"""
    game = _fresh(seed=3)
    _proceed(game, "end_play_phase")
    select_action = min(
        (
            a
            for a in game.legal_actions()
            if a.payload.get("operation") == "select_discard_card"
        ),
        key=lambda a: a.card_instance_id or "",
    )
    _step(game, select_action)
    second_select = min(
        (
            a
            for a in game.legal_actions()
            if a.payload.get("operation") == "select_discard_card"
        ),
        key=lambda a: a.card_instance_id or "",
    )
    _step(game, second_select)
    _submit(game)
    _proceed(game, "end_turn")
    # 旧回合的选择动作跨回合失败关闭
    with pytest.raises(ProductionBatchError):
        game.step(
            BatchActionIdController(select_action.action_id)  # type: ignore[attr-defined]
        )
    # 伪造句柄在任意阶段都被拒绝
    forged = _forge_discard_action(
        game,
        operation="select_discard_card",
        actor_id="p1",
        payload={"handle": "forged-cross-session"},
    )
    with pytest.raises(InvalidActionError):
        validate_action(game.state, game._context(), forged, game.registry)


def test_discard_three_cards_same_batch_root_action() -> None:
    """一次弃3张属于同一个弃牌阶段batch/root action（清单18）。"""
    game = _fresh(seed=3)
    hand_ids = list(game.state.card_ids_in(ZoneRef.hand("p1")))
    game._state = game.state.move_cards({hand_ids[0]: DISCARD_PILE})
    _set_hp(game, "p1", 2, max_hp=2)  # 上限2、手牌5、excess=3
    _proceed(game, "end_play_phase")
    assert game.phase is ProductionPhase.DISCARD
    selected_ids: set[str] = set()
    for _ in range(3):
        action = _select(game)
        assert action.card_instance_id is not None
        selected_ids.add(action.card_instance_id)
    assert _action(game, "discard_phase_submit") is not None
    before = len(game.events)
    window_id = game.runtime.discard_phase_window_id
    assert window_id is not None
    submit = _submit(game)
    new_events = game.events[before:]
    discard_events = [
        event
        for event in new_events
        if event.payload.get("reason") == "discard_phase"
    ]
    assert len(discard_events) == 9  # 3张 × CARD_MOVED/CARD_LOST/CARD_DISCARDED
    # 同一提交动作 = 同一 batch：全部事件共享同一公开稳定的window_id
    assert len(
        {event.payload.get("window_id") for event in discard_events}
    ) == 1
    assert all(
        event.payload.get("window_id") == window_id
        for event in discard_events
    )
    assert all(
        event.payload.get("window_id") is not None
        for event in discard_events
    )
    # 提交动作作为该批次的root action被回放decisions权威记录
    assert submit.action_id is not None
    assert {event.card_instance_id for event in discard_events} == selected_ids
    assert game.phase is ProductionPhase.END
    assert len(game.state.card_ids_in(ZoneRef.hand("p1"))) == 2
    _assert_conservation(game)


# ----------------------------------------------------------------------
# C. 延时锦囊与阶段跳过接入回合循环
# ----------------------------------------------------------------------


def test_lebusi_hit_skips_play_and_reaches_discard() -> None:
    game = _fresh(seed=3)
    _swap(game, LEBUSI_098, ZoneRef.hand("p1"))
    _use_delayed(game, "use_lebusi", LEBUSI, "p2")
    _put_draw_at(game, SPADE_7_SHA, 0)  # ♠7 非红桃命中
    _end_turn(game)
    _proceed(game, "proceed_prepare")
    _proceed(game, "proceed_judgment")
    assert game.phase is ProductionPhase.JUDGMENT_WUXIE
    for _ in range(4):
        if game.phase is not ProductionPhase.JUDGMENT_WUXIE:
            break
        action = next(
            a
            for a in game.legal_actions()
            if a.payload.get("operation") == "pass_judgment_wuxie"
        )
        _step(game, action)
    _proceed(game, "proceed_judgment")
    assert game.phase is ProductionPhase.DRAW
    _proceed(game, "proceed_draw")
    # 乐命中：PLAY被跳过，直接进入弃牌阶段
    assert game.phase is ProductionPhase.DISCARD
    skipped = [
        event
        for event in game.events
        if event.event_type is EventType.PHASE_SKIPPED
    ]
    assert len(skipped) == 1
    assert skipped[0].payload["skipped_phase"] == "play"
    _discard_to_end(game)
    assert game.phase is ProductionPhase.END
    _assert_conservation(game)


def test_lebusi_miss_enters_play_phase() -> None:
    game = _fresh(seed=3)
    _swap(game, LEBUSI_137, ZoneRef.hand("p1"))
    _use_delayed(game, "use_lebusi", LEBUSI, "p2")
    _put_draw_at(game, LEBUSI_098, 0)  # ♥6 红桃 → 不跳过
    _end_turn(game)
    _proceed(game, "proceed_prepare")
    _proceed(game, "proceed_judgment")
    for _ in range(4):
        if game.phase is not ProductionPhase.JUDGMENT_WUXIE:
            break
        action = next(
            a
            for a in game.legal_actions()
            if a.payload.get("operation") == "pass_judgment_wuxie"
        )
        _step(game, action)
    _proceed(game, "proceed_judgment")
    _proceed(game, "proceed_draw")
    assert game.phase is ProductionPhase.PLAY
    assert not _events_of(game, EventType.PHASE_SKIPPED)


def test_bingliang_hit_skips_draw_phase() -> None:
    game = _fresh(seed=3)
    _swap(game, BINGLIANG_151, ZoneRef.hand("p1"))
    _use_delayed(game, "use_bingliang", BINGLIANG, "p2")
    _put_draw_at(game, LEBUSI_137, 0)  # ♠6 非梅花 → 跳过摸牌
    _end_turn(game)
    _proceed(game, "proceed_prepare")
    _proceed(game, "proceed_judgment")
    for _ in range(4):
        if game.phase is not ProductionPhase.JUDGMENT_WUXIE:
            break
        action = next(
            a
            for a in game.legal_actions()
            if a.payload.get("operation") == "pass_judgment_wuxie"
        )
        _step(game, action)
    hand_before = len(game.state.card_ids_in(ZoneRef.hand("p2")))
    _proceed(game, "proceed_judgment")
    assert game.phase is ProductionPhase.PLAY
    assert len(game.state.card_ids_in(ZoneRef.hand("p2"))) == hand_before
    skipped = [
        event
        for event in game.events
        if event.event_type is EventType.PHASE_SKIPPED
    ]
    assert skipped[-1].payload["skipped_phase"] == "draw"


def test_bingliang_miss_draws_normally() -> None:
    game = _fresh(seed=3)
    _swap(game, BINGLIANG_151, ZoneRef.hand("p1"))
    _use_delayed(game, "use_bingliang", BINGLIANG, "p2")
    _put_draw_at(game, BINGLIANG_053, 0)  # ♣4 梅花 → 不跳过
    _end_turn(game)
    _proceed(game, "proceed_prepare")
    _proceed(game, "proceed_judgment")
    for _ in range(4):
        if game.phase is not ProductionPhase.JUDGMENT_WUXIE:
            break
        action = next(
            a
            for a in game.legal_actions()
            if a.payload.get("operation") == "pass_judgment_wuxie"
        )
        _step(game, action)
    hand_before = len(game.state.card_ids_in(ZoneRef.hand("p2")))
    _proceed(game, "proceed_judgment")
    _proceed(game, "proceed_draw")
    assert game.phase is ProductionPhase.PLAY
    assert len(game.state.card_ids_in(ZoneRef.hand("p2"))) == hand_before + 2


def test_lightning_judgment_continues_turn_after_rescue() -> None:
    game = _fresh(seed=3)
    _set_hp(game, "p1", 2)
    _swap(game, SHANDIAN_117, ZoneRef.hand("p1"))
    _use_delayed(game, "use_shandian", SHANDIAN, "p1")
    _put_draw_at(game, SPADE_7_SHA, 2)
    _end_turn(game)
    _proceed(game, "proceed_prepare")
    _proceed(game, "proceed_judgment")
    _proceed(game, "proceed_draw")
    _proceed(game, "end_play_phase")
    _discard_to_end(game)
    _proceed(game, "end_turn")
    # p1判定：闪电命中，2血-3=-1进入濒死
    _proceed(game, "proceed_prepare")
    _proceed(game, "proceed_judgment")
    for _ in range(4):
        if game.phase is not ProductionPhase.JUDGMENT_WUXIE:
            break
        action = next(
            a
            for a in game.legal_actions()
            if a.payload.get("operation") == "pass_judgment_wuxie"
        )
        _step(game, action)
    assert game.phase is ProductionPhase.DYING_RESCUE
    # 两张桃救援（直接把桃移入手中，弃牌阶段后手牌已压至上限）
    peach_ids = [
        record.instance_id
        for record in game.formal_registry.instances_of(TAO)
        if game.state.location_of(record.instance_id)
        != ZoneRef.hand("p1")
    ]
    for peach_id in peach_ids[:2]:
        game._state = game.state.move_card(peach_id, ZoneRef.hand("p1"))
    for _ in range(2):
        action = _action(game, "rescue_with_peach", card_key=TAO)
        assert action is not None, "濒死救援窗口必须能枚举桃救援动作"
        _step(game, action)
    assert game.state.players_by_id["p1"].hp == 1
    # 回合继续：判定→摸牌→出牌→弃牌→结束
    _proceed(game, "proceed_judgment")
    assert game.phase is ProductionPhase.DRAW
    _proceed(game, "proceed_draw")
    assert game.phase is ProductionPhase.PLAY
    _proceed(game, "end_play_phase")
    _discard_to_end(game)
    assert game.phase is ProductionPhase.END
    _assert_conservation(game)


def test_current_player_death_during_judgment_stops_turn_cycle() -> None:
    game = _fresh(seed=3)
    _set_hp(game, "p1", 1)
    _swap(game, SHANDIAN_117, ZoneRef.hand("p1"))
    _use_delayed(game, "use_shandian", SHANDIAN, "p1")
    _put_draw_at(game, SPADE_7_SHA, 2)
    _end_turn(game)
    _proceed(game, "proceed_prepare")
    _proceed(game, "proceed_judgment")
    _proceed(game, "proceed_draw")
    _proceed(game, "end_play_phase")
    _discard_to_end(game)
    _proceed(game, "end_turn")
    _proceed(game, "proceed_prepare")
    _proceed(game, "proceed_judgment")
    for _ in range(4):
        if game.phase is not ProductionPhase.JUDGMENT_WUXIE:
            break
        action = next(
            a
            for a in game.legal_actions()
            if a.payload.get("operation") == "pass_judgment_wuxie"
        )
        _step(game, action)
    assert game.phase is ProductionPhase.DYING_RESCUE
    _step(game, _action(game, "pass_rescue"))
    _step(game, _action(game, "pass_rescue"))
    assert game.is_finished
    assert game.winner_id == "p2"
    with pytest.raises(ProductionBatchFinishedError):
        game.legal_actions()
    _assert_conservation(game)


# ----------------------------------------------------------------------
# D. 每回合状态与重置
# ----------------------------------------------------------------------


def test_slash_limit_within_play_phase_and_reset_next_own_turn() -> None:
    game = _fresh(seed=3)
    slash_action = _action(game, "use_slash")
    assert slash_action is not None
    _step(game, slash_action)
    _step(game, _action(game, "pass_slash_response"))
    assert game.runtime.slash_used_counts.get("p1", 0) == 1
    assert all(
        action.payload.get("operation") != "use_slash"
        for action in game.legal_actions()
    )
    # 回合内不提前恢复：弃牌、结束阶段后仍保持1
    _proceed(game, "end_play_phase")
    _discard_to_end(game)
    _proceed(game, "end_turn")
    assert game.runtime.slash_used_counts.get("p1", 0) == 1
    # p2回合结束
    _proceed(game, "proceed_prepare")
    _proceed(game, "proceed_judgment")
    _proceed(game, "proceed_draw")
    _proceed(game, "end_play_phase")
    _discard_to_end(game)
    _proceed(game, "end_turn")
    # p1新的出牌阶段：计数复位
    _proceed(game, "proceed_prepare")
    _proceed(game, "proceed_judgment")
    _proceed(game, "proceed_draw")
    assert game.runtime.slash_used_counts.get("p1", 0) == 0
    assert _action(game, "use_slash") is not None


def test_phase_skip_markers_cleared_next_turn() -> None:
    game = _fresh(seed=3)
    _swap(game, LEBUSI_098, ZoneRef.hand("p1"))
    _use_delayed(game, "use_lebusi", LEBUSI, "p2")
    _put_draw_at(game, SPADE_7_SHA, 0)
    _end_turn(game)
    _proceed(game, "proceed_prepare")
    _proceed(game, "proceed_judgment")
    for _ in range(4):
        if game.phase is not ProductionPhase.JUDGMENT_WUXIE:
            break
        action = next(
            a
            for a in game.legal_actions()
            if a.payload.get("operation") == "pass_judgment_wuxie"
        )
        _step(game, action)
    _proceed(game, "proceed_judgment")
    _proceed(game, "proceed_draw")
    _discard_to_end(game)
    _proceed(game, "end_turn")
    # 新回合：跳过标记不残留
    skipped_before = len(_events_of(game, EventType.PHASE_SKIPPED))
    _proceed(game, "proceed_prepare")
    assert game.runtime.skipped_phases == {}
    assert game.runtime.phase_skip_reasons == {}
    _proceed(game, "proceed_judgment")
    _proceed(game, "proceed_draw")
    assert game.phase is ProductionPhase.PLAY
    assert (
        len(_events_of(game, EventType.PHASE_SKIPPED)) == skipped_before
    )


def test_response_window_state_closed_before_discard() -> None:
    game = _fresh(seed=3)
    slash_action = _action(game, "use_slash")
    assert slash_action is not None
    _step(game, slash_action)
    # 响应窗口：p2放弃
    pass_action = _action(game, "pass_slash_response")
    assert pass_action is not None
    _step(game, pass_action)
    assert game.phase is ProductionPhase.PLAY
    assert game.runtime.pending_slash is None
    _proceed(game, "end_play_phase")
    assert game.phase is ProductionPhase.DISCARD
    # 响应窗口状态不跨阶段残留
    assert game.runtime.pending_slash is None
    assert game.runtime.response_window_id is None


# ----------------------------------------------------------------------
# E. 下一行动者、死亡与胜利
# ----------------------------------------------------------------------


def test_two_player_alternation_continues_after_death_rescue() -> None:
    game = _fresh(seed=3)
    _complete_turn(game)
    assert game.current_player_id == "p2"
    _complete_turn(game)
    assert game.current_player_id == "p1"


def test_victory_stops_turn_cycle() -> None:
    game = _fresh(seed=3)
    _set_hp(game, "p2", 1)
    slash_action = _action(game, "use_slash")
    assert slash_action is not None and slash_action.target_ids == ("p2",)
    _step(game, slash_action)
    _step(game, _action(game, "pass_slash_response"))
    assert game.phase is ProductionPhase.DYING_RESCUE
    _step(game, _action(game, "pass_rescue"))
    _step(game, _action(game, "pass_rescue"))
    assert game.is_finished
    assert game.winner_id == "p1"
    with pytest.raises(ProductionBatchFinishedError):
        game.legal_actions()


def test_no_turn_advance_after_winner() -> None:
    game = _fresh(seed=3)
    _set_hp(game, "p2", 1)
    _step(game, _action(game, "use_slash"))
    _step(game, _action(game, "pass_slash_response"))
    _step(game, _action(game, "pass_rescue"))
    _step(game, _action(game, "pass_rescue"))
    assert game.is_finished
    assert game.runtime.current_player_id == "p1"
    assert game.runtime.turn_number == 1


# ----------------------------------------------------------------------
# F. 动作安全
# ----------------------------------------------------------------------


def test_stale_end_play_action_fails_closed() -> None:
    game = _fresh(seed=3)
    end_play = _action(game, "end_play_phase")
    assert end_play is not None
    _step(game, end_play)
    # 已进入弃牌阶段：旧end_play动作过期失败
    with pytest.raises(ProductionBatchError):
        game.step(BatchActionIdController(end_play.action_id))  # type: ignore[attr-defined]


def test_forged_phase_transition_rejected() -> None:
    game = _fresh(seed=3)
    # 客户端不得直接声明next_phase/next_player/skip_phase
    for operation, payload in (
        ("advance_phase", {"operation": "advance_phase", "next_phase": "discard"}),
        ("skip_phase", {"operation": "skip_phase", "phase": "draw"}),
        ("set_next_player", {"operation": "set_next_player", "next_player": "p2"}),
    ):
        forged = LegalAction(
            action_type=ActionType.PASS,
            actor_id="p1",
            payload=payload,
            action_id=f"act_forged_{operation}",
        )
        with pytest.raises(InvalidActionError):
            validate_action(game.state, game._context(), forged, game.registry)


def test_cross_turn_action_rejected() -> None:
    game = _fresh(seed=3)
    end_play = _action(game, "end_play_phase")
    assert end_play is not None
    _step(game, end_play)
    _discard_to_end(game)
    _proceed(game, "end_turn")
    _proceed(game, "proceed_prepare")
    # p1旧回合动作在p2回合失败关闭
    with pytest.raises(ProductionBatchError):
        game.step(BatchActionIdController(end_play.action_id))  # type: ignore[attr-defined]


def test_discard_handle_tamper_rejected() -> None:
    game = _fresh(seed=3)
    _proceed(game, "end_play_phase")
    real = min(
        (
            a
            for a in game.legal_actions()
            if a.payload.get("operation") == "select_discard_card"
        ),
        key=lambda a: a.card_instance_id or "",
    )
    assert real.card_instance_id is not None
    tampered = LegalAction(
        action_type=ActionType.MOVE_CARD,
        actor_id="p1",
        card_instance_id="sgs-mobile-20260725-999",  # 不存在的实体
        target_ids=("p1",),
        payload={
            "operation": "select_discard_card",
            "handle": "forged-handle",
        },
        action_id="act_forged_handle",
    )
    with pytest.raises(InvalidActionError):
        validate_action(game.state, game._context(), tampered, game.registry)


def test_duplicate_discard_apply_rejected() -> None:
    game = _fresh(seed=3)
    _proceed(game, "end_play_phase")
    action = min(
        (
            a
            for a in game.legal_actions()
            if a.payload.get("operation") == "select_discard_card"
        ),
        key=lambda a: a.card_instance_id or "",
    )
    _step(game, action)
    # 同一选择动作再次提交：已过期，失败关闭
    with pytest.raises(ProductionBatchError):
        game.step(BatchActionIdController(action.action_id))  # type: ignore[attr-defined]
    assert game.phase is ProductionPhase.DISCARD
    assert len(game.state.card_ids_in(ZoneRef.hand("p1"))) == 6


# ----------------------------------------------------------------------
# G. 严格回放与玩家可见
# ----------------------------------------------------------------------


def test_strict_reexecute_full_turn_cycle_with_discard(
    turn_cycle_record: ProductionReexecutionReplay,
) -> None:
    record = turn_cycle_record
    assert record.outcome["step_count"] > 0
    discard_events = [
        event
        for event in record.events
        if event.get("event_type") == "card_discarded"
        and event.get("payload", {}).get("reason") == "discard_phase"
    ]
    assert discard_events
    # 同一提交动作的批量弃置事件共享同一 batch_action_id
    batch_ids = {
        event.get("payload", {}).get("window_id")
        for event in discard_events
    }
    assert batch_ids
    assert all(
        event.get("payload", {}).get("window_id") in batch_ids
        for event in discard_events
    )
    result = reexecute_production_replay(record)
    assert result.verified is True
    assert result.winner_id == record.outcome["winner_id"]


def test_replay_phase_tamper_rejected(
    turn_cycle_record: ProductionReexecutionReplay,
) -> None:
    record = turn_cycle_record
    tampered = copy.deepcopy(record.to_dict())
    discard_decision = next(
        decision
        for decision in tampered["decisions"]
        if decision["chosen_action"].get("payload", {}).get("operation")
        == "discard_phase_submit"
    )
    discard_decision["context"]["phase"] = "end"
    del tampered["record_sha256"]
    with pytest.raises(
        (ProductionReplayFormatError, ProductionReplayDivergenceError)
    ):
        reexecute_production_replay(
            ProductionReexecutionReplay.from_dict(tampered)
        )


def test_replay_active_player_tamper_rejected(
    turn_cycle_record: ProductionReexecutionReplay,
) -> None:
    record = turn_cycle_record
    tampered = copy.deepcopy(record.to_dict())
    discard_decision = next(
        decision
        for decision in tampered["decisions"]
        if decision["chosen_action"].get("payload", {}).get("operation")
        == "discard_phase_submit"
    )
    discard_decision["context"]["actor_id"] = (
        "p2" if discard_decision["context"]["actor_id"] == "p1" else "p1"
    )
    del tampered["record_sha256"]
    with pytest.raises(
        (ProductionReplayFormatError, ProductionReplayDivergenceError)
    ):
        reexecute_production_replay(
            ProductionReexecutionReplay.from_dict(tampered)
        )


def test_replay_discard_semantics_tamper_rejected(
    turn_cycle_record: ProductionReexecutionReplay,
) -> None:
    record = turn_cycle_record
    tampered = copy.deepcopy(record.to_dict())
    discard_event = next(
        event
        for event in tampered["events"]
        if event.get("event_type") == "card_discarded"
        and event.get("payload", {}).get("reason") == "discard_phase"
    )
    discard_event["card_instance_id"] = "sgs-mobile-20260725-001"
    del tampered["record_sha256"]
    with pytest.raises(
        (ProductionReplayFormatError, ProductionReplayDivergenceError)
    ):
        reexecute_production_replay(
            ProductionReexecutionReplay.from_dict(tampered)
        )


def test_replay_batch_selection_set_tamper_rejected(
    turn_cycle_record: ProductionReexecutionReplay,
) -> None:
    """修改批量弃置牌集合（换一张）的语义篡改必须被拒绝（清单17）。"""
    record = turn_cycle_record
    tampered = copy.deepcopy(record.to_dict())
    select_decision = next(
        decision
        for decision in tampered["decisions"]
        if decision["chosen_action"].get("payload", {}).get("operation")
        == "select_discard_card"
    )
    original = select_decision["chosen_action"]["card_instance_id"]
    replacement = next(
        event["card_instance_id"]
        for event in tampered["events"]
        if event.get("card_instance_id") is not None
        and event["card_instance_id"] != original
    )
    select_decision["chosen_action"]["card_instance_id"] = replacement
    del tampered["record_sha256"]
    with pytest.raises(
        (ProductionReplayFormatError, ProductionReplayDivergenceError)
    ):
        reexecute_production_replay(
            ProductionReexecutionReplay.from_dict(tampered)
        )


def test_player_visible_discard_public_and_legal_actions_redacted(
    turn_cycle_record: ProductionReexecutionReplay,
) -> None:
    record = turn_cycle_record
    view = record.player_visible_payload()
    assert view["player_visible"] is True
    # 弃牌阶段实体公开：公共视图保留discard_phase事件实体
    public_discards = [
        event
        for event in view["events"]
        if event.get("payload", {}).get("reason") == "discard_phase"
    ]
    assert public_discards
    assert all(
        event.get("card_instance_id") for event in public_discards
    )
    # 公共视图省略全部私有动作与权威摘要
    for decision in view["decisions"]:
        assert "chosen_action" not in decision
        assert "legal_actions" not in decision
    # 私人获得（initial_hand/draw_phase）不暴露实体
    for event in view["events"]:
        if (
            event.get("event_type") == "card_gained"
            and event.get("payload", {}).get("reason")
            in ("initial_hand", "draw_phase")
        ):
            assert event.get("card_instance_id") is None


def test_player_visible_hidden_hand_not_leaked(
    turn_cycle_record: ProductionReexecutionReplay,
) -> None:
    record = turn_cycle_record
    view = record.player_visible_payload(viewer_id="p2")
    # 对手视图：p1的私人获得必须脱敏
    for event in view["events"]:
        if (
            event.get("event_type") == "card_gained"
            and event.get("payload", {}).get("reason") == "initial_hand"
            and (event.get("target_ids") or [None])[0] == "p1"
        ):
            assert event.get("card_instance_id") is None
            assert event.get("card_key") is None


# ----------------------------------------------------------------------
# H. 回归
# ----------------------------------------------------------------------


def test_hand_limit_equals_current_hp() -> None:
    game = _fresh(seed=3)
    assert hand_limit_of(game.state, "p1") == 4
    _set_hp(game, "p1", 2)
    assert hand_limit_of(game.state, "p1") == 2
    # 体力降低后弃牌阶段必须弃到新上限
    _proceed(game, "end_play_phase")
    assert game.phase is ProductionPhase.DISCARD
    _discard_to_end(game)
    assert game.phase is ProductionPhase.END
    assert len(game.state.card_ids_in(ZoneRef.hand("p1"))) == 2
    _assert_conservation(game)


def test_hand_limit_ignores_equipment_and_judgment_zones() -> None:
    game = _fresh(seed=3)
    # 手牌先降到上限，再放入装备区与判定区：这些区域的牌不进入手牌数
    hand_ids = list(game.state.card_ids_in(ZoneRef.hand("p1")))
    game._state = game.state.move_cards(
        {hand_ids[0]: DISCARD_PILE, hand_ids[1]: DISCARD_PILE}
    )
    weapon_id = next(
        record.instance_id
        for record in game.formal_registry.records
        if record.card_key == "sgs_weapon_guanshifu"
    )
    game._state = game.state.move_card(
        weapon_id, ZoneRef.equipment("p1", "weapon")
    )
    game._state = game.state.move_card(
        LEBUSI_098, ZoneRef.judgment("p1")
    )
    hand_count = len(game.state.card_ids_in(ZoneRef.hand("p1")))
    assert hand_count == 4
    assert hand_limit_of(game.state, "p1") == 4
    _proceed(game, "end_play_phase")
    assert game.phase is ProductionPhase.END
    _assert_conservation(game)


def test_delayed_trick_regression_lebusi_end_to_end() -> None:
    game = _fresh(seed=3)
    _swap(game, LEBUSI_098, ZoneRef.hand("p1"))
    trick_id = _use_delayed(game, "use_lebusi", LEBUSI, "p2")
    _put_draw_at(game, SPADE_7_SHA, 0)  # ♠7 命中 → 确定流程
    _end_turn(game)
    _proceed(game, "proceed_prepare")
    _proceed(game, "proceed_judgment")
    for _ in range(4):
        if game.phase is not ProductionPhase.JUDGMENT_WUXIE:
            break
        action = next(
            a
            for a in game.legal_actions()
            if a.payload.get("operation") == "pass_judgment_wuxie"
        )
        _step(game, action)
    _proceed(game, "proceed_judgment")
    assert game.phase is ProductionPhase.DRAW
    _proceed(game, "proceed_draw")
    _discard_to_end(game)
    _proceed(game, "end_turn")
    assert trick_id in game.state.card_ids_in(DISCARD_PILE)
    _assert_conservation(game)


def test_regression_160_deck_conservation_after_major_branches() -> None:
    game = _fresh(seed=3)
    _proceed(game, "end_play_phase")
    _discard_to_end(game)
    _proceed(game, "end_turn")
    _proceed(game, "proceed_prepare")
    _proceed(game, "proceed_judgment")
    _proceed(game, "proceed_draw")
    _proceed(game, "end_play_phase")
    _discard_to_end(game)
    _proceed(game, "end_turn")
    _assert_conservation(game)
    assert len(game.state.cards) == 160
    assert len(game.formal_registry.records) == 160
