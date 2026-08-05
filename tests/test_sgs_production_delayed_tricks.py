# -*- coding: utf-8 -*-
"""CP-04L：三种延时锦囊＋判定与阶段基础设施生产垂直切片测试。

覆盖【乐不思蜀】【兵粮寸断】【闪电】的正式实体绑定、出牌阶段使用与
判定区放置、同名限制、判定前【无懈可击】链、判定牌生命周期、动态LIFO
与判定区进入序号、乐不思蜀／兵粮寸断的阶段跳过、闪电命中／转移／回置、
无来源雷属性伤害与传导、濒死救援、死亡与胜利清理、判定彻底不足的原子
失败、player_visible 牌堆顺序脱敏与双视角手牌隐私、严格回放与篡改失败
关闭、事件契约与实体牌守恒。

所有正式正向测试都经过 enumerate -> validate -> apply 真实路径；不使用
mock／monkeypatch／skip／xfail。双人生产切片不可达的多人边界（三人以上
响应顺序、三人以上闪电搜索、多人传导）明确标为 B（内部结构级）或 N
（NOT PROVEN），不宣称双人端到端 PROVEN。
"""
from __future__ import annotations

import copy
import json
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
    REVEALED_ZONE,
    ZoneRef,
)
from scripts.sgs_engine.production_batch import (
    BatchActionIdController,
    ProductionBasicCardBatch,
    ProductionBatchDeckExhaustedError,
    ProductionBatchError,
    ProductionBatchFinishedError,
    ProductionPhase,
    ScriptedBatchController,
    _replace_player,
)
from scripts.sgs_engine.production_cards import (
    PRODUCTION_DELAYED_TRICK_KEYS,
    BingliangAdapter,
    FormalCardRegistry,
    LebusiAdapter,
    ShandianAdapter,
)
from scripts.sgs_engine.production_replay import (
    ProductionReplayDivergenceError,
    ProductionReplayFormatError,
    ProductionReexecutionReplay,
    record_reference_production_batch,
    reexecute_production_replay,
)
from scripts.sgs_engine.replay import sha256_value

LEBUSI = "sgs_delayed_lebusi"
BINGLIANG = "sgs_delayed_bingliang"
SHANDIAN = "sgs_delayed_shandian"
WUXIE = "sgs_trick_wuxiekeji"
TAO = "sgs_basic_tao"

# 正式实体（CSV）
LEBUSI_058 = "sgs-mobile-20260725-058"  # ♣6
LEBUSI_098 = "sgs-mobile-20260725-098"  # ♥6
LEBUSI_137 = "sgs-mobile-20260725-137"  # ♠6
BINGLIANG_053 = "sgs-mobile-20260725-053"  # ♣4
BINGLIANG_151 = "sgs-mobile-20260725-151"  # ♠10
SHANDIAN_117 = "sgs-mobile-20260725-117"  # ♥Q
SHANDIAN_122 = "sgs-mobile-20260725-122"  # ♠A
SPADE_7_SHA = "sgs-mobile-20260725-140"  # ♠7 杀（闪电命中判定牌）
SPADE_2_BAGUA = "sgs-mobile-20260725-125"  # ♠2 八卦阵（闪电命中判定牌）


# ----------------------------------------------------------------------
# 夹具与路径助手（全部使用不可变GameState与正式牌区移动接口）
# ----------------------------------------------------------------------


def _fresh(
    seed: int,
    *,
    player_hp: tuple[int, int] = (4, 4),
    initial_hand_count: int = 4,
) -> ProductionBasicCardBatch:
    """创建生产批处理会话并推进到出牌阶段（CP-04L 正式阶段流）。"""
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
    assert game.phase is ProductionPhase.PLAY
    return game


def _me(game: ProductionBasicCardBatch) -> str:
    return game._first_player_id


def _other(game: ProductionBasicCardBatch) -> str:
    return "p1" if _me(game) == "p2" else "p2"


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


def _put_draw_at(
    game: ProductionBasicCardBatch,
    instance_id: str,
    position: int,
) -> None:
    """把实体牌放到牌堆指定位置（0-based），其余相对顺序保持不变。

    牌不在牌堆时先追加到牌堆尾再重排；只改变位置归属，保持160张守恒，
    不把牌堆顶牌挤入其他区域。"""
    if game.state.location_of(instance_id) != DRAW_PILE:
        game._state = game.state.move_card(instance_id, DRAW_PILE)
    pile = list(game.state.card_ids_in(DRAW_PILE))
    pile.remove(instance_id)
    pile.insert(position, instance_id)
    game._state = game.state.reorder_zone(DRAW_PILE, tuple(pile))


def _put_on_top(game: ProductionBasicCardBatch, instance_id: str) -> None:
    _put_draw_at(game, instance_id, 0)


def _put_third(game: ProductionBasicCardBatch, instance_id: str) -> None:
    """放到牌堆第3位：闪电判定前对手回合的摸牌会消耗前2张。"""
    _put_draw_at(game, instance_id, 2)


def _set_hp(game: ProductionBasicCardBatch, player_id: str, hp: int) -> None:
    game._state = _replace_player(game.state, player_id, hp=hp)


def _set_chained(
    game: ProductionBasicCardBatch, player_id: str, chained: bool
) -> None:
    game._state = _replace_player(game.state, player_id, chained=chained)


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


def _events_of(
    game: ProductionBasicCardBatch, event_type: EventType
) -> list:
    return [event for event in game.events if event.event_type is event_type]


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


def _close_judgment_wuxie(game: ProductionBasicCardBatch) -> None:
    """在当前判定无懈窗口连续放弃，直到窗口关闭并完成判定结算。"""
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
    assert game.phase in (ProductionPhase.JUDGMENT, ProductionPhase.DYING_RESCUE), (
        "判定无懈窗口关闭后必须回到判定阶段或进入濒死救援"
    )


def _end_turn(game: ProductionBasicCardBatch) -> None:
    _proceed(game, "end_play_phase")
    assert game.phase is ProductionPhase.END
    _proceed(game, "end_turn")
    assert game.phase is ProductionPhase.PREPARE


def _to_judgment(game: ProductionBasicCardBatch) -> None:
    """从当前角色PREPARE推进到JUDGMENT（可能打开判定无懈窗口）。"""
    _proceed(game, "proceed_prepare")
    assert game.phase is ProductionPhase.JUDGMENT
    _proceed(game, "proceed_judgment")


def _give_hand(
    game: ProductionBasicCardBatch,
    player_id: str,
    key: str,
    *,
    exclude: tuple[str, ...] = (),
) -> str:
    record = next(
        r
        for r in game.formal_registry.records
        if r.card_key == key
        and game.state.location_of(r.instance_id) != ZoneRef.hand(player_id)
        and r.instance_id not in exclude
    )
    _swap(game, record.instance_id, ZoneRef.hand(player_id))
    return record.instance_id


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


# ----------------------------------------------------------------------
# A. 三种牌全部7张正式实体
# ----------------------------------------------------------------------


def test_all_seven_delayed_trick_entities_from_formal_csv() -> None:
    game = _fresh(seed=3)
    registry = game.formal_registry
    assert isinstance(registry, FormalCardRegistry)
    lebusi = registry.instances_of(LEBUSI)
    bingliang = registry.instances_of(BINGLIANG)
    shandian = registry.instances_of(SHANDIAN)
    assert len(lebusi) == 3
    assert len(bingliang) == 2
    assert len(shandian) == 2
    assert {record.instance_id for record in lebusi} == {
        LEBUSI_058,
        LEBUSI_098,
        LEBUSI_137,
    }
    assert {record.instance_id for record in bingliang} == {
        BINGLIANG_053,
        BINGLIANG_151,
    }
    assert {record.instance_id for record in shandian} == {
        SHANDIAN_117,
        SHANDIAN_122,
    }
    by_id = {record.instance_id: record for record in registry.records}
    assert by_id[LEBUSI_058].suit == "♣" and by_id[LEBUSI_058].rank == "6"
    assert by_id[LEBUSI_098].suit == "♥" and by_id[LEBUSI_098].rank == "6"
    assert by_id[LEBUSI_137].suit == "♠" and by_id[LEBUSI_137].rank == "6"
    assert by_id[BINGLIANG_053].suit == "♣" and by_id[BINGLIANG_053].rank == "4"
    assert by_id[BINGLIANG_151].suit == "♠" and by_id[BINGLIANG_151].rank == "10"
    assert by_id[SHANDIAN_117].suit == "♥" and by_id[SHANDIAN_117].rank == "Q"
    assert by_id[SHANDIAN_122].suit == "♠" and by_id[SHANDIAN_122].rank == "A"
    assert len({record.instance_id for record in registry.records}) == 160


def test_delayed_trick_adapters_registered_with_specs() -> None:
    game = _fresh(seed=3)
    registry = game.formal_registry
    assert set(PRODUCTION_DELAYED_TRICK_KEYS) <= set(
        registry.implemented_card_keys
    )
    lebusi = registry.adapter_for(LEBUSI)
    bingliang = registry.adapter_for(BINGLIANG)
    shandian = registry.adapter_for(SHANDIAN)
    assert isinstance(lebusi, LebusiAdapter)
    assert isinstance(bingliang, BingliangAdapter)
    assert isinstance(shandian, ShandianAdapter)
    assert lebusi.implemented and lebusi.tested and lebusi.production_adapter
    assert lebusi.rule_spec()["use_timing"] == "own_play_phase"
    assert bingliang.rule_spec()["distance_rule"].startswith(
        "actual_distance(user,target)==1"
    )
    assert "spade_2_to_9" in shandian.rule_spec()["judgment"]


# ----------------------------------------------------------------------
# B/C/D. 使用、判定区放置、同名限制、使用时无懈不可响应
# ----------------------------------------------------------------------


def test_use_lebusi_places_into_judgment_zone_without_response_window() -> None:
    game = _fresh(seed=3)
    _swap(game, LEBUSI_098, ZoneRef.hand("p1"))
    trick_id = _use_delayed(game, "use_lebusi", LEBUSI, "p2")
    assert trick_id == LEBUSI_098
    assert LEBUSI_098 in game.state.card_ids_in(ZoneRef.judgment("p2"))
    used = _events_of(game, EventType.CARD_USED)
    assert any(
        event.card_instance_id == LEBUSI_098
        and event.payload.get("purpose") == "place_delayed_trick"
        for event in used
    )
    moved = _events_of(game, EventType.CARD_MOVED)
    placed = [
        event
        for event in moved
        if event.payload.get("reason") == "delayed_trick_placed"
    ]
    assert len(placed) == 1
    assert placed[0].card_instance_id == LEBUSI_098
    assert placed[0].payload["source"]["kind"] == "hand"
    assert placed[0].payload["destination"]["kind"] == "judgment"
    assert placed[0].payload["judgment_zone_entry_index"] == 1
    assert game.runtime.judgment_entry_indices[LEBUSI_098] == 1
    assert game.runtime.judgment_entry_counter == 1
    # 使用时不得误开普通TRICK_RESPONSE，也不得枚举无懈响应
    assert game.phase is ProductionPhase.PLAY
    assert _action(game, "use_wuxie") is None
    _assert_conservation(game)


def test_use_shandian_only_self_and_same_name_restriction() -> None:
    game = _fresh(seed=3)
    _swap(game, SHANDIAN_117, ZoneRef.hand("p1"))
    action = _action(game, "use_shandian", card_key=SHANDIAN)
    assert action is not None
    assert action.target_ids == ("p1",)
    _step(game, action)
    assert game.phase is ProductionPhase.PLAY
    assert SHANDIAN_117 in game.state.card_ids_in(ZoneRef.judgment("p1"))
    # 自己判定区已有闪电后不能再使用第二张闪电
    _swap(game, SHANDIAN_122, ZoneRef.hand("p1"))
    assert _action(game, "use_shandian", card_key=SHANDIAN) is None
    forged = LegalAction(
        action_type=ActionType.USE_CARD,
        actor_id="p1",
        card_instance_id=SHANDIAN_122,
        target_ids=("p2",),
        payload={
            "operation": "use_shandian",
            "card_key": SHANDIAN,
            "card_name": "闪电",
        },
        action_id="act_shandian_forged",
    )
    with pytest.raises(InvalidActionError):
        validate_action(game.state, game._context(), forged, game.registry)


def test_same_name_restriction_blocks_enumerate_and_apply() -> None:
    game = _fresh(seed=3)
    # p2判定区已有【乐不思蜀】（夹具放正式实体，仅区域移动）
    _swap(game, LEBUSI_098, ZoneRef.judgment("p2"))
    _swap(game, LEBUSI_137, ZoneRef.hand("p1"))
    assert _action(game, "use_lebusi", card_key=LEBUSI) is None
    # 直接伪造同名使用动作也必须失败关闭
    forged = LegalAction(
        action_type=ActionType.USE_CARD,
        actor_id="p1",
        card_instance_id=LEBUSI_137,
        target_ids=("p2",),
        payload={
            "operation": "use_lebusi",
            "card_key": LEBUSI,
            "card_name": "乐不思蜀",
        },
        action_id="act_lebusi_dup",
    )
    with pytest.raises(InvalidActionError):
        validate_action(game.state, game._context(), forged, game.registry)


def test_different_delayed_tricks_can_coexist_and_entry_increases() -> None:
    game = _fresh(seed=3)
    _swap(game, LEBUSI_098, ZoneRef.hand("p1"))
    _use_delayed(game, "use_lebusi", LEBUSI, "p2")
    _swap(game, BINGLIANG_151, ZoneRef.hand("p1"))
    _use_delayed(game, "use_bingliang", BINGLIANG, "p2")
    judgment = game.state.card_ids_in(ZoneRef.judgment("p2"))
    assert set(judgment) == {LEBUSI_098, BINGLIANG_151}
    assert game.runtime.judgment_entry_indices[LEBUSI_098] == 1
    assert game.runtime.judgment_entry_indices[BINGLIANG_151] == 2
    assert game.runtime.judgment_entry_counter == 2
    # 不同名可共存：再使用【乐不思蜀】应被同名限制阻止，但【兵粮寸断】不受影响
    _swap(game, LEBUSI_137, ZoneRef.hand("p1"))
    assert _action(game, "use_lebusi", card_key=LEBUSI) is None
    _assert_conservation(game)


def test_bingliang_uses_actual_distance_and_mount_gate() -> None:
    game = _fresh(seed=3)
    _swap(game, BINGLIANG_151, ZoneRef.hand("p1"))
    action = _action(game, "use_bingliang", card_key=BINGLIANG)
    assert action is not None
    assert action.target_ids == ("p2",)
    # 坐骑栏被夹具占用时（坐骑语义未实现）必须失败关闭
    mount = next(
        r
        for r in game.formal_registry.records
        if r.card_key == "sgs_mount_offensive"
    )
    _swap(game, mount.instance_id, ZoneRef.equipment("p2", "attack_horse"))
    with pytest.raises(UnsupportedRuleError):
        _action(game, "use_bingliang", card_key=BINGLIANG)


def test_lebusi_cannot_target_self() -> None:
    game = _fresh(seed=3)
    _swap(game, LEBUSI_098, ZoneRef.hand("p1"))
    assert _action(game, "use_lebusi", card_key=LEBUSI, target="p1") is None
    forged = LegalAction(
        action_type=ActionType.USE_CARD,
        actor_id="p1",
        card_instance_id=LEBUSI_098,
        target_ids=("p1",),
        payload={
            "operation": "use_lebusi",
            "card_key": LEBUSI,
            "card_name": "乐不思蜀",
        },
        action_id="act_lebusi_self",
    )
    with pytest.raises(InvalidActionError):
        validate_action(game.state, game._context(), forged, game.registry)


# ----------------------------------------------------------------------
# 正式阶段流
# ----------------------------------------------------------------------


def test_formal_phase_flow_prepare_judgment_draw_play_end() -> None:
    game = ProductionBasicCardBatch(seed=3, initial_hand_count=4)
    assert game.phase is ProductionPhase.PREPARE
    assert len(game.state.card_ids_in(ZoneRef.hand("p1"))) == 4
    _proceed(game, "proceed_prepare")
    assert game.phase is ProductionPhase.JUDGMENT
    _proceed(game, "proceed_judgment")
    assert game.phase is ProductionPhase.DRAW
    hand_before = len(game.state.card_ids_in(ZoneRef.hand("p1")))
    _proceed(game, "proceed_draw")
    assert game.phase is ProductionPhase.PLAY
    assert len(game.state.card_ids_in(ZoneRef.hand("p1"))) == hand_before + 2
    _proceed(game, "end_play_phase")
    assert game.phase is ProductionPhase.END
    _proceed(game, "end_turn")
    assert game.phase is ProductionPhase.PREPARE
    assert game.runtime.current_player_id == "p2"
    assert game.runtime.turn_number == 2


# ----------------------------------------------------------------------
# H/I. 乐不思蜀与兵粮寸断的阶段跳过
# ----------------------------------------------------------------------


def test_lebusi_non_heart_skips_play_phase() -> None:
    game = _fresh(seed=3)
    _swap(game, LEBUSI_098, ZoneRef.hand("p1"))
    _use_delayed(game, "use_lebusi", LEBUSI, "p2")
    _put_on_top(game, LEBUSI_058)  # ♣6 非红桃 → 跳过PLAY
    _end_turn(game)
    assert game.runtime.current_player_id == "p2"
    _to_judgment(game)
    assert game.phase is ProductionPhase.JUDGMENT_WUXIE
    _close_judgment_wuxie(game)
    # 判定♣6命中：记录跳过PLAY；继续判定阶段（无剩余牌）→DRAW
    _proceed(game, "proceed_judgment")
    assert game.phase is ProductionPhase.DRAW
    hand_before = len(game.state.card_ids_in(ZoneRef.hand("p2")))
    _proceed(game, "proceed_draw")
    # DRAW正常摸2后，PLAY被跳过 → 直接END
    assert len(game.state.card_ids_in(ZoneRef.hand("p2"))) == hand_before + 2
    assert game.phase is ProductionPhase.END
    skipped = _events_of(game, EventType.PHASE_SKIPPED)
    assert len(skipped) == 1
    assert skipped[0].payload["player_id"] == "p2"
    assert skipped[0].payload["skipped_phase"] == "play"
    assert skipped[0].payload["reason"] == "lebusi_judgment_hit"
    assert skipped[0].payload["delayed_trick_instance_id"] == LEBUSI_098
    assert skipped[0].target_ids == ("p2",)
    assert skipped[0].payload["turn_number"] == 2
    # 本体与判定牌都已进入弃牌堆
    assert LEBUSI_098 in game.state.card_ids_in(DISCARD_PILE)
    assert LEBUSI_058 in game.state.card_ids_in(DISCARD_PILE)
    assert not game.state.card_ids_in(REVEALED_ZONE)
    assert game.runtime.pending_judgment is None
    assert LEBUSI_098 in game.runtime.processed_judgment_instance_ids
    _assert_conservation(game)


def test_lebusi_heart_does_not_skip_play_phase() -> None:
    game = _fresh(seed=3)
    _swap(game, LEBUSI_137, ZoneRef.hand("p1"))
    _use_delayed(game, "use_lebusi", LEBUSI, "p2")
    _put_on_top(game, LEBUSI_098)  # ♥6 → 不跳过
    _end_turn(game)
    _to_judgment(game)
    _close_judgment_wuxie(game)
    _proceed(game, "proceed_judgment")
    _proceed(game, "proceed_draw")
    assert game.phase is ProductionPhase.PLAY
    assert not _events_of(game, EventType.PHASE_SKIPPED)
    assert _action(game, "end_play_phase") is not None


def test_bingliang_non_club_skips_draw_phase() -> None:
    game = _fresh(seed=3)
    _swap(game, BINGLIANG_151, ZoneRef.hand("p1"))
    _use_delayed(game, "use_bingliang", BINGLIANG, "p2")
    _put_on_top(game, LEBUSI_137)  # ♠6 非梅花 → 跳过DRAW
    _end_turn(game)
    _to_judgment(game)
    _close_judgment_wuxie(game)
    hand_before = len(game.state.card_ids_in(ZoneRef.hand("p2")))
    _proceed(game, "proceed_judgment")
    assert game.phase is ProductionPhase.PLAY
    # DRAW被跳过：不摸牌
    assert len(game.state.card_ids_in(ZoneRef.hand("p2"))) == hand_before
    skipped = _events_of(game, EventType.PHASE_SKIPPED)
    assert len(skipped) == 1
    assert skipped[0].payload["player_id"] == "p2"
    assert skipped[0].payload["skipped_phase"] == "draw"
    assert skipped[0].payload["reason"] == "bingliang_judgment_hit"
    assert skipped[0].payload["delayed_trick_instance_id"] == BINGLIANG_151
    assert BINGLIANG_151 in game.state.card_ids_in(DISCARD_PILE)
    assert not game.state.card_ids_in(REVEALED_ZONE)
    _assert_conservation(game)


def test_bingliang_club_does_not_skip_draw_phase() -> None:
    game = _fresh(seed=3)
    _swap(game, BINGLIANG_151, ZoneRef.hand("p1"))
    _use_delayed(game, "use_bingliang", BINGLIANG, "p2")
    _put_on_top(game, BINGLIANG_053)  # ♣4 → 不跳过
    _end_turn(game)
    _to_judgment(game)
    _close_judgment_wuxie(game)
    hand_before = len(game.state.card_ids_in(ZoneRef.hand("p2")))
    _proceed(game, "proceed_judgment")
    assert game.phase is ProductionPhase.DRAW
    _proceed(game, "proceed_draw")
    assert game.phase is ProductionPhase.PLAY
    assert len(game.state.card_ids_in(ZoneRef.hand("p2"))) == hand_before + 2
    assert not _events_of(game, EventType.PHASE_SKIPPED)


# ----------------------------------------------------------------------
# E. 判定前无懈
# ----------------------------------------------------------------------


def test_judgment_wuxie_cancels_lebusi_without_judging() -> None:
    game = _fresh(seed=3)
    _swap(game, LEBUSI_098, ZoneRef.hand("p1"))
    _use_delayed(game, "use_lebusi", LEBUSI, "p2")
    _end_turn(game)
    _to_judgment(game)
    assert game.phase is ProductionPhase.JUDGMENT_WUXIE
    assert _events_of(game, EventType.JUDGMENT_STARTED)
    started = _events_of(game, EventType.JUDGMENT_STARTED)[0]
    assert started.payload["delayed_trick_instance_id"] == LEBUSI_098
    assert started.payload["target_id"] == "p2"
    assert started.payload["judgment_zone_entry_index"] == 1
    # p1使用【无懈可击】取消判定
    _give_hand(game, "p1", WUXIE)
    # 响应顺序：当前回合角色p2 → p1
    _step(game, _action(game, "pass_judgment_wuxie"))
    assert game.phase is ProductionPhase.JUDGMENT_WUXIE
    _step(game, _action(game, "use_wuxie", card_key=WUXIE))
    # 一轮无人再响应后关闭 → 被取消
    _step(game, _action(game, "pass_judgment_wuxie"))
    _step(game, _action(game, "pass_judgment_wuxie"))
    assert game.phase is ProductionPhase.JUDGMENT
    assert not _events_of(game, EventType.CARD_REVEALED)
    assert not _events_of(game, EventType.JUDGMENT_RESULT)
    assert not _events_of(game, EventType.PHASE_SKIPPED)
    assert _events_of(game, EventType.CARD_EFFECT_CANCELLED)
    cancelled = _events_of(game, EventType.CARD_EFFECT_CANCELLED)[-1]
    assert cancelled.card_instance_id == LEBUSI_098
    assert cancelled.target_ids == ("p2",)
    # 本体经PROCESSING进入弃牌堆
    assert LEBUSI_098 in game.state.card_ids_in(DISCARD_PILE)
    assert LEBUSI_098 in game.runtime.processed_judgment_instance_ids
    assert not game.state.card_ids_in(REVEALED_ZONE)
    _assert_conservation(game)


def test_two_wuxie_restore_judgment_and_judge_normally() -> None:
    game = _fresh(seed=3)
    _swap(game, LEBUSI_098, ZoneRef.hand("p1"))
    _use_delayed(game, "use_lebusi", LEBUSI, "p2")
    _put_on_top(game, LEBUSI_058)  # ♣6 命中跳PLAY
    _end_turn(game)
    _to_judgment(game)
    wuxie_p1 = _give_hand(game, "p1", WUXIE)
    wuxie_p2 = _give_hand(game, "p2", WUXIE, exclude=(wuxie_p1,))
    # p2先响应：不用无懈；p1用无懈取消
    _step(game, _action(game, "pass_judgment_wuxie"))
    _step(game, _action(game, "use_wuxie", card_key=WUXIE))
    # p2再用一张无懈恢复；p1不再响应 → 窗口关闭
    _step(game, _action(game, "use_wuxie", card_key=WUXIE))
    _step(game, _action(game, "pass_judgment_wuxie"))
    _step(game, _action(game, "pass_judgment_wuxie"))
    assert game.phase is ProductionPhase.JUDGMENT
    results = _events_of(game, EventType.JUDGMENT_RESULT)
    assert len(results) == 1
    assert results[0].payload["delayed_trick_instance_id"] == LEBUSI_098
    assert results[0].payload["suit"] == "♣"
    assert results[0].payload["hit"] is True
    assert results[0].payload["skipped_phase"] == "play"
    # 两张无懈都消耗进弃牌堆；本体后续正常弃置
    assert not _events_of(game, EventType.CARD_EFFECT_CANCELLED)
    _assert_conservation(game)


# ----------------------------------------------------------------------
# F. 判定牌生命周期
# ----------------------------------------------------------------------


def test_judgment_card_lifecycle_revealed_then_discarded() -> None:
    game = _fresh(seed=3)
    _swap(game, LEBUSI_098, ZoneRef.hand("p1"))
    _use_delayed(game, "use_lebusi", LEBUSI, "p2")
    _put_on_top(game, SPADE_7_SHA)
    _end_turn(game)
    _to_judgment(game)
    _close_judgment_wuxie(game)
    moved = _events_of(game, EventType.CARD_MOVED)
    take = [
        event
        for event in moved
        if event.payload.get("reason") == "judgment_take"
    ]
    resolved = [
        event
        for event in moved
        if event.payload.get("reason") == "judgment_card_resolved"
    ]
    assert len(take) == 1 and take[0].card_instance_id == SPADE_7_SHA
    assert take[0].payload["source"]["kind"] == "draw_pile"
    assert take[0].payload["destination"]["kind"] == "revealed"
    assert take[0].payload["delayed_trick_instance_id"] == LEBUSI_098
    revealed = _events_of(game, EventType.CARD_REVEALED)
    assert len(revealed) == 1
    reveal = revealed[0]
    assert reveal.card_instance_id == SPADE_7_SHA
    assert reveal.payload["reason"] == "judgment"
    assert reveal.payload["card_key"] == "sgs_basic_sha"
    assert reveal.payload["name"] == "杀"
    assert reveal.payload["suit"] == "♠"
    assert reveal.payload["rank"] == "7"
    assert reveal.payload["target_id"] == "p2"
    assert reveal.payload["delayed_trick_instance_id"] == LEBUSI_098
    assert len(resolved) == 1
    assert resolved[0].card_instance_id == SPADE_7_SHA
    assert resolved[0].payload["source"]["kind"] == "revealed"
    assert resolved[0].payload["destination"]["kind"] == "discard_pile"
    results = _events_of(game, EventType.JUDGMENT_RESULT)
    assert len(results) == 1
    result = results[0]
    assert result.card_instance_id == SPADE_7_SHA
    assert result.payload["judgment_card_instance_id"] == SPADE_7_SHA
    assert result.payload["judgment_card_instance_id"] != LEBUSI_098
    assert result.payload["suit"] == "♠" and result.payload["rank"] == "7"
    # 判定牌先弃置、本体再进入PROCESSING并最终弃置
    resolved_seq = resolved[0].sequence
    processing_seq = [
        event.sequence
        for event in moved
        if event.card_instance_id == LEBUSI_098
        and event.payload.get("destination", {}).get("kind") == "processing"
    ]
    assert processing_seq and resolved_seq < processing_seq[0]
    assert SPADE_7_SHA in game.state.card_ids_in(DISCARD_PILE)
    assert LEBUSI_098 in game.state.card_ids_in(DISCARD_PILE)
    assert not game.state.card_ids_in(REVEALED_ZONE)
    assert not game.state.card_ids_in(PROCESSING_ZONE)


# ----------------------------------------------------------------------
# G. 动态LIFO与entry_index
# ----------------------------------------------------------------------


def test_dynamic_lifo_processes_newest_entry_first() -> None:
    game = _fresh(seed=3)
    _swap(game, LEBUSI_137, ZoneRef.hand("p1"))
    _use_delayed(game, "use_lebusi", LEBUSI, "p2")  # entry 1
    _swap(game, BINGLIANG_151, ZoneRef.hand("p1"))
    _use_delayed(game, "use_bingliang", BINGLIANG, "p2")  # entry 2
    _put_on_top(game, BINGLIANG_053)  # 兵判定：♣4 不跳
    _end_turn(game)
    _to_judgment(game)
    started = _events_of(game, EventType.JUDGMENT_STARTED)
    assert len(started) == 1
    assert started[0].payload["delayed_trick_instance_id"] == BINGLIANG_151
    _close_judgment_wuxie(game)
    results = _events_of(game, EventType.JUDGMENT_RESULT)
    assert len(results) == 1
    assert results[0].payload["delayed_trick_instance_id"] == BINGLIANG_151
    assert BINGLIANG_151 in game.runtime.processed_judgment_instance_ids
    # 继续判定阶段：乐（entry 1）随后处理
    _put_on_top(game, LEBUSI_098)  # 乐判定：♥6 不跳
    _proceed(game, "proceed_judgment")
    assert game.phase is ProductionPhase.JUDGMENT_WUXIE
    _close_judgment_wuxie(game)
    results = _events_of(game, EventType.JUDGMENT_RESULT)
    assert [r.payload["delayed_trick_instance_id"] for r in results] == [
        BINGLIANG_151,
        LEBUSI_137,
    ]
    assert LEBUSI_137 in game.runtime.processed_judgment_instance_ids
    assert set(
        game.runtime.processed_judgment_instance_ids
    ) == {BINGLIANG_151, LEBUSI_137}
    _proceed(game, "proceed_judgment")
    assert game.phase is ProductionPhase.DRAW
    _assert_conservation(game)


def test_entry_index_preserved_across_turns() -> None:
    game = _fresh(seed=3)
    _swap(game, LEBUSI_137, ZoneRef.hand("p1"))
    _use_delayed(game, "use_lebusi", LEBUSI, "p2")  # entry 1
    _put_on_top(game, LEBUSI_098)  # ♥6 不跳
    _end_turn(game)
    _to_judgment(game)
    _close_judgment_wuxie(game)
    _proceed(game, "proceed_judgment")
    _proceed(game, "proceed_draw")
    # p2回合出牌阶段：p2对p1使用【兵粮寸断】（实际距离1）
    _swap(game, BINGLIANG_151, ZoneRef.hand("p2"))
    action = _action(game, "use_bingliang", card_key=BINGLIANG)
    assert action is not None and action.target_ids == ("p1",)
    _step(game, action)
    assert game.runtime.judgment_entry_indices[BINGLIANG_151] == 2
    assert game.runtime.judgment_entry_counter == 2
    # 跨回合：p1下一回合判定兵粮
    _put_on_top(game, BINGLIANG_053)  # ♣4 不跳
    _end_turn(game)
    _to_judgment(game)
    assert game.phase is ProductionPhase.JUDGMENT_WUXIE
    _close_judgment_wuxie(game)
    results = _events_of(game, EventType.JUDGMENT_RESULT)
    assert results[-1].payload["delayed_trick_instance_id"] == BINGLIANG_151
    assert game.runtime.judgment_entry_indices[BINGLIANG_151] == 2


# ----------------------------------------------------------------------
# J/K/L/N/O. 闪电命中、转移、回置
# ----------------------------------------------------------------------


def test_lightning_hit_three_thunder_no_source() -> None:
    game = _fresh(seed=3)
    _swap(game, SHANDIAN_117, ZoneRef.hand("p1"))
    _use_delayed(game, "use_shandian", SHANDIAN, "p1")
    _put_third(game, SPADE_7_SHA)  # ♠7 → 命中（对手回合摸牌消耗前2张）
    _end_turn(game)
    _to_judgment(game)  # p2无判定牌 → DRAW
    assert game.phase is ProductionPhase.DRAW
    _proceed(game, "proceed_draw")
    _proceed(game, "end_play_phase")
    _proceed(game, "end_turn")
    _to_judgment(game)
    assert game.phase is ProductionPhase.JUDGMENT_WUXIE
    _close_judgment_wuxie(game)
    damages = [
        event
        for event in game.events
        if event.event_type.value == "damage"
    ]
    assert len(damages) == 1
    damage = damages[0]
    assert damage.target_ids == ("p1",)
    assert damage.amount == 3
    assert damage.damage_type == "雷属性"
    assert damage.damage_source is None
    assert damage.card_instance_id == SHANDIAN_117
    assert damage.card_key == SHANDIAN
    assert game.state.players_by_id["p1"].hp == 1
    # 本体PROCESSING→弃牌堆；pending清理；判定牌已弃置
    assert SHANDIAN_117 in game.state.card_ids_in(DISCARD_PILE)
    assert game.runtime.pending_judgment is None
    assert SHANDIAN_117 in game.runtime.processed_judgment_instance_ids
    assert not game.state.card_ids_in(REVEALED_ZONE)
    assert not game.state.card_ids_in(PROCESSING_ZONE)
    assert not _events_of(game, EventType.DELAYED_TRICK_TRANSFERRED)
    _assert_conservation(game)


def test_lightning_miss_transfers_to_other_player_with_new_entry() -> None:
    game = _fresh(seed=3)
    _swap(game, SHANDIAN_117, ZoneRef.hand("p1"))
    _use_delayed(game, "use_shandian", SHANDIAN, "p1")
    _put_third(game, LEBUSI_098)  # ♥6 → 未命中
    _end_turn(game)
    _to_judgment(game)
    _proceed(game, "proceed_draw")
    _proceed(game, "end_play_phase")
    _proceed(game, "end_turn")
    _to_judgment(game)
    _close_judgment_wuxie(game)
    transferred = _events_of(game, EventType.DELAYED_TRICK_TRANSFERRED)
    assert len(transferred) == 1
    assert transferred[0].card_instance_id == SHANDIAN_117
    assert transferred[0].payload["from_player_id"] == "p1"
    assert transferred[0].payload["to_player_id"] == "p2"
    assert transferred[0].payload["reason"] == "shandian_transfer"
    assert transferred[0].payload["judgment_zone_entry_index"] == 2
    assert SHANDIAN_117 in game.state.card_ids_in(ZoneRef.judgment("p2"))
    assert SHANDIAN_117 not in game.state.card_ids_in(DISCARD_PILE)
    assert game.runtime.judgment_entry_indices[SHANDIAN_117] == 2
    assert game.runtime.judgment_entry_counter == 2
    # 转移后不立即打开新无懈窗口、不立即判定
    assert game.phase is ProductionPhase.JUDGMENT
    assert game.runtime.pending_judgment is None
    assert SHANDIAN_117 in game.runtime.processed_judgment_instance_ids
    _assert_conservation(game)


def test_lightning_self_restore_when_other_has_lightning() -> None:
    game = _fresh(seed=3)
    _swap(game, SHANDIAN_117, ZoneRef.hand("p1"))
    _use_delayed(game, "use_shandian", SHANDIAN, "p1")
    _put_third(game, LEBUSI_098)  # 未命中牌（p1回合判定用）
    _end_turn(game)
    _to_judgment(game)  # p2无判定 → DRAW
    _proceed(game, "proceed_draw")
    # p2出牌阶段对自已使用【闪电】
    _swap(game, SHANDIAN_122, ZoneRef.hand("p2"))
    action = _action(game, "use_shandian", card_key=SHANDIAN)
    assert action is not None and action.target_ids == ("p2",)
    _step(game, action)
    _proceed(game, "end_play_phase")
    _proceed(game, "end_turn")
    _to_judgment(game)
    assert game.phase is ProductionPhase.JUDGMENT_WUXIE
    _close_judgment_wuxie(game)
    transferred = _events_of(game, EventType.DELAYED_TRICK_TRANSFERRED)
    assert len(transferred) == 1
    assert transferred[0].payload["from_player_id"] == "p1"
    assert transferred[0].payload["to_player_id"] == "p1"
    assert transferred[0].payload["reason"] == "shandian_self_restore"
    assert transferred[0].payload["judgment_zone_entry_index"] == 3
    assert SHANDIAN_117 in game.state.card_ids_in(ZoneRef.judgment("p1"))
    assert SHANDIAN_117 not in game.state.card_ids_in(DISCARD_PILE)
    assert game.runtime.judgment_entry_indices[SHANDIAN_117] == 3
    # 回置后本阶段不得再次判定：继续判定阶段直接进入DRAW
    _proceed(game, "proceed_judgment")
    assert game.phase is ProductionPhase.DRAW
    assert not _events_of(game, EventType.JUDGMENT_STARTED)[1:]
    _assert_conservation(game)


def test_lightning_next_target_skips_dead_and_occupied_structural() -> None:
    """B（内部结构级）：双人切片不可达的多人搜索边界用纯接口覆盖。"""
    game = _fresh(seed=3)
    # 对方判定区已有闪电 → 无合法目标 → 回置自己
    _swap(game, SHANDIAN_117, ZoneRef.judgment("p1"))
    _swap(game, SHANDIAN_122, ZoneRef.judgment("p2"))
    assert game._next_lightning_target(game.state, "p1") == "p1"
    # 对方死亡 → 跳过 → 回置自己
    game._state = _replace_player(game.state, "p2", alive=False, hp=0)
    assert game._next_lightning_target(game.state, "p1") == "p1"
    # 对方存活且无闪电 → 转移给对方
    game._state = _replace_player(game.state, "p2", alive=True)
    game._state = game.state.move_card(SHANDIAN_122, ZoneRef.hand("p2"))
    assert game._next_lightning_target(game.state, "p1") == "p2"


# ----------------------------------------------------------------------
# P/Q/R/S. 传导、濒死救援、死亡与胜利清理
# ----------------------------------------------------------------------


def test_lightning_chained_thunder_damage_propagates() -> None:
    game = _fresh(seed=3)
    _set_chained(game, "p1", True)
    _set_chained(game, "p2", True)
    _swap(game, SHANDIAN_117, ZoneRef.hand("p1"))
    _use_delayed(game, "use_shandian", SHANDIAN, "p1")
    _put_third(game, SPADE_7_SHA)
    _end_turn(game)
    _to_judgment(game)
    _proceed(game, "proceed_draw")
    _proceed(game, "end_play_phase")
    _proceed(game, "end_turn")
    _to_judgment(game)
    _close_judgment_wuxie(game)
    damages = [
        event
        for event in game.events
        if event.event_type.value == "damage"
    ]
    assert len(damages) == 2
    assert [event.target_ids[0] for event in damages] == ["p1", "p2"]
    assert all(event.damage_type == "雷属性" for event in damages)
    assert all(event.amount == 3 for event in damages)
    assert damages[1].card_instance_id == SHANDIAN_117
    assert game.state.players_by_id["p1"].hp == 1
    assert game.state.players_by_id["p2"].hp == 1
    assert game.runtime.pending_chain is None
    assert SHANDIAN_117 in game.state.card_ids_in(DISCARD_PILE)
    assert not game.state.card_ids_in(PROCESSING_ZONE)
    _assert_conservation(game)


def test_lightning_dying_rescue_restores_root_and_continues() -> None:
    game = _fresh(seed=3)
    _set_hp(game, "p1", 1)
    _swap(game, SHANDIAN_117, ZoneRef.hand("p1"))
    _use_delayed(game, "use_shandian", SHANDIAN, "p1")
    _put_third(game, SPADE_7_SHA)
    _end_turn(game)
    _to_judgment(game)
    _proceed(game, "proceed_draw")
    _proceed(game, "end_play_phase")
    _proceed(game, "end_turn")
    _to_judgment(game)
    _close_judgment_wuxie(game)
    assert game.phase is ProductionPhase.DYING_RESCUE
    assert game.runtime.pending_dying_id == "p1"
    assert _events_of(game, EventType.DYING)
    # p1用三张【桃】救援：-2 → -1 → 0 → 1 脱离濒死
    peach_ids: list[str] = []
    for _ in range(3):
        peach_ids.append(
            _give_hand(game, "p1", TAO, exclude=tuple(peach_ids))
        )
    for peach_id in peach_ids:
        action = _action(game, "rescue_with_peach", card_key=TAO)
        assert action is not None, "濒死救援窗口必须能枚举桃救援动作"
        _step(game, action)
    assert game.state.players_by_id["p1"].hp == 1
    assert game.phase is ProductionPhase.JUDGMENT
    assert game.runtime.pending_dying_id is None
    assert game.runtime.pending_judgment is None
    assert SHANDIAN_117 in game.state.card_ids_in(DISCARD_PILE)
    assert not game.state.card_ids_in(PROCESSING_ZONE)
    assert not game.state.card_ids_in(REVEALED_ZONE)
    _assert_conservation(game)


def test_lightning_death_cleanup_and_victory() -> None:
    game = _fresh(seed=3)
    _set_hp(game, "p1", 1)
    _swap(game, SHANDIAN_117, ZoneRef.hand("p1"))
    _use_delayed(game, "use_shandian", SHANDIAN, "p1")
    # p1手牌其余实体（死亡清理用）
    _swap(game, SPADE_2_BAGUA, ZoneRef.hand("p1"))
    _put_third(game, SPADE_7_SHA)
    _end_turn(game)
    _to_judgment(game)
    _proceed(game, "proceed_draw")
    _proceed(game, "end_play_phase")
    _proceed(game, "end_turn")
    _to_judgment(game)
    _close_judgment_wuxie(game)
    assert game.phase is ProductionPhase.DYING_RESCUE
    _step(game, _action(game, "pass_rescue"))
    _step(game, _action(game, "pass_rescue"))
    assert game.is_finished
    assert game.winner_id == "p2"
    deaths = [
        event
        for event in game.events
        if event.event_type.value == "death"
    ]
    assert len(deaths) == 1
    assert deaths[0].target_ids == ("p1",)
    assert _events_of(game, EventType.VICTORY)
    cleanup = [
        event
        for event in game.events
        if event.payload.get("reason") == "death_cleanup"
    ]
    assert any(
        event.card_instance_id == SPADE_2_BAGUA for event in cleanup
    )
    assert SPADE_2_BAGUA in game.state.card_ids_in(DISCARD_PILE)
    assert SHANDIAN_117 in game.state.card_ids_in(DISCARD_PILE)
    assert not game.state.card_ids_in(REVEALED_ZONE)
    assert not game.state.card_ids_in(PROCESSING_ZONE)
    assert game.runtime.pending_judgment is None
    assert not game.state.card_ids_in(ZoneRef.hand("p1"))
    assert not game.state.card_ids_in(ZoneRef.judgment("p1"))
    # 幸存角色区域不因胜利清空
    assert game.state.card_ids_in(ZoneRef.hand("p2"))
    _assert_conservation(game)


# ----------------------------------------------------------------------
# T. 判定彻底不足的原子失败
# ----------------------------------------------------------------------


def test_judgment_deck_exhausted_fails_atomically() -> None:
    game = _fresh(seed=3)
    _swap(game, SHANDIAN_117, ZoneRef.hand("p1"))
    _use_delayed(game, "use_shandian", SHANDIAN, "p1")
    _end_turn(game)
    _to_judgment(game)
    _proceed(game, "proceed_draw")
    _proceed(game, "end_play_phase")
    _proceed(game, "end_turn")
    _to_judgment(game)
    assert game.phase is ProductionPhase.JUDGMENT_WUXIE
    # 牌堆与弃牌堆清空：全部实体移入p1手牌（闪电本体仍在判定区）
    draw_ids = list(game.state.card_ids_in(DRAW_PILE))
    discard_ids = list(game.state.card_ids_in(DISCARD_PILE))
    moves = {instance_id: ZoneRef.hand("p1") for instance_id in draw_ids}
    moves.update(
        {instance_id: ZoneRef.hand("p1") for instance_id in discard_ids}
    )
    game._state = game.state.move_cards(moves)
    assert not game.state.card_ids_in(DRAW_PILE)
    assert not game.state.card_ids_in(DISCARD_PILE)
    # 第一个pass推进响应顺序（提交响应窗口状态），第二个pass触发判定翻牌
    _step(game, _action(game, "pass_judgment_wuxie"))
    rng_before = len(game.rng_calls)
    events_before = len(game.events)
    snapshot_before = game.execution_snapshot
    with pytest.raises(ProductionBatchDeckExhaustedError):
        _step(game, _action(game, "pass_judgment_wuxie"))
    assert len(game.rng_calls) == rng_before
    assert len(game.events) == events_before
    assert game.execution_snapshot == snapshot_before
    assert not _events_of(game, EventType.CARD_REVEALED)
    assert not _events_of(game, EventType.JUDGMENT_RESULT)
    assert SHANDIAN_117 in game.state.card_ids_in(ZoneRef.judgment("p1"))
    assert game.runtime.judgment_entry_indices[SHANDIAN_117] == 1
    assert game.runtime.processed_judgment_instance_ids == ()
    assert game.runtime.skipped_phases == {}
    assert game.runtime.phase is ProductionPhase.JUDGMENT_WUXIE


# ----------------------------------------------------------------------
# U/V/W. player_visible 牌堆顺序脱敏与双视角手牌隐私
# ----------------------------------------------------------------------


def _lightning_replay_fixture(game: ProductionBasicCardBatch) -> None:
    """确定性夹具：p1持【闪电】、1血，判定牌♠7位于p1/p2摸牌后的牌堆顶。

    夹具在会话创建后、任何决策前应用，因此p1的DRAW与p2的DRAW合计先消耗
    4张牌，判定牌必须位于第5位。"""
    _set_hp(game, "p1", 1)
    _swap(game, SHANDIAN_117, ZoneRef.hand("p1"))
    pile = list(game.state.card_ids_in(DRAW_PILE))
    pile.remove(SPADE_7_SHA)
    ordered = (*pile[:4], SPADE_7_SHA, *pile[4:])
    game._state = game.state.reorder_zone(DRAW_PILE, ordered)


def _lightning_death_record() -> ProductionReexecutionReplay:
    controller = ScriptedBatchController(
        [
            {"operation": "use_shandian"},
            {"operation": "end_play_phase"},
            {"operation": "end_turn"},
            {"operation": "proceed_prepare"},
            {"operation": "proceed_judgment"},
            {"operation": "proceed_draw"},
            {"operation": "end_play_phase"},
            {"operation": "end_turn"},
            {"operation": "proceed_prepare"},
            {"operation": "proceed_judgment"},
            {"operation": "pass_judgment_wuxie"},
            {"operation": "pass_judgment_wuxie"},
            {"operation": "pass_rescue"},
            {"operation": "pass_rescue"},
        ]
    )
    return record_reference_production_batch(
        seed=3,
        controller=controller,
        fixture=_lightning_replay_fixture,
        max_steps=60,
    )


def test_strict_replay_reexecutes_lightning_death_path() -> None:
    record = _lightning_death_record()
    assert record.outcome["winner_id"] == "p2"
    assert any(
        event.get("event_type") == "judgment_result"
        for event in record.events
    )
    assert any(
        event.get("event_type") == "damage"
        and event.get("damage_source") is None
        and event.get("amount") == 3
        for event in record.events
    )
    result = reexecute_production_replay(record, fixture=_lightning_replay_fixture)
    assert result.verified is True
    assert result.winner_id == "p2"


def test_replay_tamper_delayed_fields_fail_closed() -> None:
    record = _lightning_death_record()
    # 篡改判定结果花色
    tampered = copy.deepcopy(record.to_dict())
    result_event = next(
        event
        for event in tampered["events"]
        if event.get("event_type") == "judgment_result"
    )
    result_event["payload"]["suit"] = "♥"
    del tampered["record_sha256"]
    with pytest.raises(
        (ProductionReplayFormatError, ProductionReplayDivergenceError)
    ):
        reexecute_production_replay(
            ProductionReexecutionReplay.from_dict(tampered),
            fixture=_lightning_replay_fixture,
        )
    # 篡改伤害来源与属性
    tampered = copy.deepcopy(record.to_dict())
    damage_event = next(
        event
        for event in tampered["events"]
        if event.get("event_type") == "damage"
    )
    damage_event["damage_source"] = "p1"
    damage_event["damage_type"] = "火属性"
    del tampered["record_sha256"]
    with pytest.raises(
        (ProductionReplayFormatError, ProductionReplayDivergenceError)
    ):
        reexecute_production_replay(
            ProductionReexecutionReplay.from_dict(tampered),
            fixture=_lightning_replay_fixture,
        )
    # 删除一条打出判定相关事件
    tampered = copy.deepcopy(record.to_dict())
    target_event = next(
        event
        for event in tampered["events"]
        if event.get("event_type") == "judgment_result"
    )
    tampered["events"].remove(target_event)
    del tampered["record_sha256"]
    with pytest.raises(
        (ProductionReplayFormatError, ProductionReplayDivergenceError)
    ):
        reexecute_production_replay(
            ProductionReexecutionReplay.from_dict(tampered),
            fixture=_lightning_replay_fixture,
        )


def test_player_visible_redacts_rng_and_private_material() -> None:
    record = _lightning_death_record()
    view = record.player_visible_payload()
    assert view["player_visible"] is True
    assert "authoritative_private" not in view
    assert "session_secret_hex" not in json.dumps(view)
    header = view["header"]
    assert "seed" not in header
    assert "initial_rng_state" not in header
    assert "initial_rng_state_sha256" not in header
    assert header["rng_material_redacted"] is True
    assert view["random_consumptions"] == []
    assert view["random_consumption_count"] == len(
        record.random_consumptions
    )
    # 牌堆顺序材料不得通过事件暴露：摸牌事件在公共视图必须脱敏
    for event in view["events"]:
        if event.get("event_type") == "card_gained":
            reason = event.get("payload", {}).get("reason")
            assert reason != "draw_phase" or event.get("card_instance_id") is None


def test_player_visible_two_viewer_hand_privacy_and_public_gain() -> None:
    record = _lightning_death_record()
    game = _fresh(seed=3)
    p1_private = set(game.state.card_ids_in(ZoneRef.hand("p1")))
    p2_private = set(game.state.card_ids_in(ZoneRef.hand("p2")))
    owner_view = record.player_visible_payload(viewer_id="p1")
    opponent_view = record.player_visible_payload(viewer_id="p2")
    public_view = record.player_visible_payload()
    for event in owner_view["events"]:
        if (
            event.get("event_type") == "card_gained"
            and event.get("payload", {}).get("reason") == "initial_hand"
        ):
            recipient = (event.get("target_ids") or [None])[0]
            if recipient == "p1":
                assert event.get("card_instance_id") in p1_private
    for event in opponent_view["events"]:
        if (
            event.get("event_type") == "card_gained"
            and event.get("payload", {}).get("reason") in (
                "initial_hand",
                "draw_phase",
            )
        ):
            assert event.get("card_instance_id") not in p1_private
    for event in public_view["events"]:
        instance_id = event.get("card_instance_id")
        if instance_id in p1_private | p2_private:
            # 公开获得路径（card_used/card_revealed/card_played）可公开；
            # 未公开化的初始手牌实体不得出现
            assert event.get("event_type") in (
                "card_used",
                "card_played",
                "card_revealed",
                "card_moved",
            )
    # W：公开获得事件保留实体信息（闪电使用card_used公开实体）
    assert any(
        event.get("event_type") == "card_used"
        and event.get("card_instance_id") == SHANDIAN_117
        for event in public_view["events"]
    )


# ----------------------------------------------------------------------
# 失败关闭、终局与守恒
# ----------------------------------------------------------------------


def test_judgment_wuxie_rejects_wrong_actor_and_forged_payload() -> None:
    game = _fresh(seed=3)
    _swap(game, LEBUSI_098, ZoneRef.hand("p1"))
    _use_delayed(game, "use_lebusi", LEBUSI, "p2")
    _end_turn(game)
    _to_judgment(game)
    assert game.phase is ProductionPhase.JUDGMENT_WUXIE
    # 非当前响应者（p1）不能pass
    forged_pass = LegalAction(
        action_type=ActionType.PASS,
        actor_id="p1",
        payload={"operation": "pass_judgment_wuxie"},
        action_id="act_wrong_pass",
    )
    with pytest.raises(InvalidActionError):
        validate_action(game.state, game._context(), forged_pass, game.registry)
    # 伪造根锦囊ID的无懈被拒绝
    wuxie = _give_hand(game, "p1", WUXIE)
    forged_wuxie = LegalAction(
        action_type=ActionType.USE_CARD,
        actor_id="p1",
        card_instance_id=wuxie,
        target_ids=("p2",),
        payload={
            "operation": "use_wuxie",
            "card_key": WUXIE,
            "card_name": "无懈可击",
            "response_to": "forged-root",
            "root_trick_instance_id": "forged-trick",
        },
        action_id="act_forged_wuxie",
    )
    with pytest.raises(InvalidActionError):
        validate_action(game.state, game._context(), forged_wuxie, game.registry)


def test_finished_game_stops_judgment_and_moves() -> None:
    game = _fresh(seed=5)
    result = game.run()
    assert game.is_finished
    assert game.winner_id == result.winner_id
    event_count = len(game.events)
    with pytest.raises(ProductionBatchFinishedError):
        game.legal_actions()
    with pytest.raises(ProductionBatchFinishedError):
        game.step()
    assert len(game.events) == event_count


def test_unimplemented_judgment_tools_fail_closed() -> None:
    game = _fresh(seed=3)
    _swap(game, LEBUSI_098, ZoneRef.hand("p1"))
    _use_delayed(game, "use_lebusi", LEBUSI, "p2")
    _end_turn(game)
    _to_judgment(game)
    assert game.phase is ProductionPhase.JUDGMENT_WUXIE
    for action in game.legal_actions():
        operation = str(action.payload.get("operation", ""))
        assert operation in (
            "use_wuxie",
            "pass_judgment_wuxie",
        ), f"判定窗口不得暴露未实现动作{operation}"


def test_card_conservation_after_major_branches() -> None:
    # 乐跳过PLAY分支
    game = _fresh(seed=3)
    _swap(game, LEBUSI_098, ZoneRef.hand("p1"))
    _use_delayed(game, "use_lebusi", LEBUSI, "p2")
    _put_on_top(game, LEBUSI_058)
    _end_turn(game)
    _to_judgment(game)
    _close_judgment_wuxie(game)
    _assert_conservation(game)
    # 兵跳过DRAW分支
    game = _fresh(seed=7)
    _swap(game, BINGLIANG_151, ZoneRef.hand(_me(game)))
    _use_delayed(game, "use_bingliang", BINGLIANG, _other(game))
    _put_on_top(game, LEBUSI_137)
    _end_turn(game)
    _to_judgment(game)
    _close_judgment_wuxie(game)
    _assert_conservation(game)
    # 闪电转移分支
    game = _fresh(seed=9)
    _swap(game, SHANDIAN_117, ZoneRef.hand(_me(game)))
    _use_delayed(game, "use_shandian", SHANDIAN, _me(game))
    _put_third(game, LEBUSI_098)
    _end_turn(game)
    _to_judgment(game)
    _proceed(game, "proceed_draw")
    _proceed(game, "end_play_phase")
    _proceed(game, "end_turn")
    _to_judgment(game)
    _close_judgment_wuxie(game)
    _assert_conservation(game)


def test_judgment_events_carry_exact_contract_fields() -> None:
    game = _fresh(seed=3)
    _swap(game, LEBUSI_098, ZoneRef.hand("p1"))
    _use_delayed(game, "use_lebusi", LEBUSI, "p2")
    _put_on_top(game, SPADE_7_SHA)
    _end_turn(game)
    _to_judgment(game)
    started = _events_of(game, EventType.JUDGMENT_STARTED)
    assert len(started) == 1
    assert set(started[0].payload) == {
        "delayed_trick_instance_id",
        "target_id",
        "judgment_zone_entry_index",
    }
    _close_judgment_wuxie(game)
    results = _events_of(game, EventType.JUDGMENT_RESULT)
    assert set(results[0].payload) == {
        "delayed_trick_instance_id",
        "judgment_card_instance_id",
        "target_id",
        "suit",
        "rank",
        "hit",
        "skipped_phase",
        "damage_amount",
        "damage_type",
        "effect_applied",
    }
    assert results[0].payload["hit"] is True
    assert results[0].payload["skipped_phase"] == "play"
    assert results[0].payload["damage_amount"] is None
    assert results[0].payload["damage_type"] is None
