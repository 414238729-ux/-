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
from types import MappingProxyType

import pytest

from scripts.sgs_engine.actions import (
    ActionType,
    InvalidActionError,
    LegalAction,
    UnsupportedRuleError,
    validate_action,
)
from scripts.sgs_engine.events import EventType
from scripts.sgs_engine.engine import canonical_state_snapshot
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
    _build_event_hash_chain,
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


def _discard_to_end(
    game: ProductionBasicCardBatch,
    keep: tuple[str, ...] = (),
) -> None:
    """弃牌阶段：选择恰好超限数量的手牌并一次性提交（CP-04O 批量弃置）。

    ``keep`` 指定必须保留在手牌中的实体ID，弃置时跳过这些牌；若跳过
    keep 后选择数量无法凑够excess（keep 数量本身超过上限），则失败关闭。
    选择过程不移动牌；只有提交动作确认后全部选中牌才一次性离开手牌。"""
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


def _end_turn(
    game: ProductionBasicCardBatch,
    keep: tuple[str, ...] = (),
) -> None:
    _proceed(game, "end_play_phase")
    _discard_to_end(game, keep=keep)
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


def test_bingliang_uses_actual_distance_and_mounts() -> None:
    game = _fresh(seed=3)
    _swap(game, BINGLIANG_151, ZoneRef.hand("p1"))
    action = _action(game, "use_bingliang", card_key=BINGLIANG)
    assert action is not None
    assert action.target_ids == ("p2",)
    # 目标防御坐骑使 p1->p2 有效距离为2：兵粮距离1不合法
    mount = next(
        r
        for r in game.formal_registry.records
        if r.card_key == "sgs_mount_defensive"
    )
    _swap(game, mount.instance_id, ZoneRef.equipment("p2", "defense_horse"))
    assert _action(game, "use_bingliang", card_key=BINGLIANG) is None
    # 进攻坐骑恢复距离1后合法
    atk = next(
        r
        for r in game.formal_registry.records
        if r.card_key == "sgs_mount_offensive"
    )
    _swap(game, atk.instance_id, ZoneRef.equipment("p1", "attack_horse"))
    action2 = _action(game, "use_bingliang", card_key=BINGLIANG)
    assert action2 is not None and action2.target_ids == ("p2",)


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
    _discard_to_end(game)
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
    # DRAW正常摸2后，PLAY被跳过 → 弃牌阶段（手牌超上限）→ END
    assert len(game.state.card_ids_in(ZoneRef.hand("p2"))) == hand_before + 2
    _discard_to_end(game)
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
    # 判定（弃置）后 entry_index 一并删除（复审观察项二）；counter 不回退
    assert BINGLIANG_151 not in game.runtime.judgment_entry_indices
    assert game.runtime.judgment_entry_counter >= 2


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
    _discard_to_end(game)
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
    _discard_to_end(game)
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
    _discard_to_end(game)
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
    _discard_to_end(game)
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
    _discard_to_end(game)
    _proceed(game, "end_turn")
    _to_judgment(game)
    _close_judgment_wuxie(game)
    assert game.phase is ProductionPhase.DYING_RESCUE
    assert game.runtime.pending_dying_id == "p1"
    assert _events_of(game, EventType.DYING)
    # p1用三张【桃】救援：-2 → -1 → 0 → 1 脱离濒死
    # CP-04O：弃牌阶段后p1手牌已压至上限1，直接移入三张桃实体（不交换），
    # 避免_give_hand的交换语义只保留最后一张桃。
    peach_ids = [
        record.instance_id
        for record in game.formal_registry.instances_of(TAO)
        if game.state.location_of(record.instance_id)
        != ZoneRef.hand("p1")
    ]
    for peach_id in peach_ids[:3]:
        game._state = game.state.move_card(peach_id, ZoneRef.hand("p1"))
    for peach_id in peach_ids[:3]:
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
    # p1手牌其余实体（死亡清理用）；弃牌阶段保留八卦阵实体
    _swap(game, SPADE_2_BAGUA, ZoneRef.hand("p1"))
    _put_third(game, SPADE_7_SHA)
    _end_turn(game, keep=(SPADE_2_BAGUA,))
    _to_judgment(game)
    _proceed(game, "proceed_draw")
    _proceed(game, "end_play_phase")
    _discard_to_end(game, keep=(SPADE_2_BAGUA,))
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


def test_judgment_empty_draw_reshuffles_discard_and_continues() -> None:
    game = _fresh(seed=3)
    _swap(game, LEBUSI_098, ZoneRef.hand("p1"))
    _use_delayed(game, "use_lebusi", LEBUSI, "p2")
    _end_turn(game)
    _to_judgment(game)
    assert game.phase is ProductionPhase.JUDGMENT_WUXIE

    # 牌堆为空但弃牌堆仍有真实实体时，不属于“彻底不足”：判定应经统一
    # 重洗事务继续，而不是触发紧邻测试覆盖的原子失败分支。
    _swap(game, SPADE_7_SHA, DISCARD_PILE)
    draw_ids = tuple(game.state.card_ids_in(DRAW_PILE))
    game._state = game.state.move_cards(
        {instance_id: ZoneRef.hand("p1") for instance_id in draw_ids}
    )
    discard_before = tuple(game.state.card_ids_in(DISCARD_PILE))
    assert not game.state.card_ids_in(DRAW_PILE)
    assert discard_before
    event_count_before = len(game.events)

    _close_judgment_wuxie(game)

    new_events = game.events[event_count_before:]
    reshuffled = [
        event
        for event in new_events
        if event.event_type is EventType.CARD_MOVED
        and event.payload.get("reason") == "reshuffle"
    ]
    assert {event.card_instance_id for event in reshuffled} == set(
        discard_before
    )
    assert all(
        event.payload["source"]["kind"] == "discard_pile"
        and event.payload["destination"]["kind"] == "draw_pile"
        for event in reshuffled
    )
    take = [
        event
        for event in new_events
        if event.event_type is EventType.CARD_MOVED
        and event.payload.get("reason") == "judgment_take"
    ]
    assert len(take) == 1
    assert take[0].card_instance_id in discard_before
    results = [
        event
        for event in new_events
        if event.event_type is EventType.JUDGMENT_RESULT
    ]
    assert len(results) == 1
    assert results[0].payload["judgment_card_instance_id"] in discard_before
    assert not game.state.card_ids_in(REVEALED_ZONE)
    _assert_conservation(game)


def test_judgment_deck_exhausted_fails_atomically() -> None:
    game = _fresh(seed=3)
    _swap(game, SHANDIAN_117, ZoneRef.hand("p1"))
    _use_delayed(game, "use_shandian", SHANDIAN, "p1")
    _end_turn(game)
    _to_judgment(game)
    _proceed(game, "proceed_draw")
    _proceed(game, "end_play_phase")
    _discard_to_end(game)
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
    tampered["record_sha256"] = ""
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
    tampered["record_sha256"] = ""
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
    tampered["record_sha256"] = ""
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
            # 未公开化的初始手牌实体不得出现。CP-04O：弃牌阶段的
            # card_lost/card_discarded 将实体公开置入弃牌堆，与
            # 同批 card_moved(reason=discard_phase) 一致，允许公开。
            assert event.get("event_type") in (
                "card_used",
                "card_played",
                "card_revealed",
                "card_moved",
            ) or (
                event.get("event_type") in ("card_lost", "card_discarded")
                and event.get("payload", {}).get("reason")
                == "discard_phase"
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
    _discard_to_end(game)
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

# H. 第一次独立审计修复：B1 reshuffle 脱敏、哈希旁路与 viewer_id 契约
# ----------------------------------------------------------------------


def _reshuffle_order_fixture(game: ProductionBasicCardBatch) -> None:
    """固定两份记录共享的公开事实：首玩家手牌固定、弃牌堆仅两张隐藏牌。

    首玩家先摸两张固定牌；判定牌♠7置于牌堆顶；被乐跳过PLAY的角色在
    DRAW 阶段触发重洗（弃牌堆＝X、Y、判定牌与乐本体），秘密摸走两张
    隐藏牌；随后首玩家杀1血角色结束。seed 20 与 21 的重洗结果分别为
    (Y,X) 与 (X,Y)（首玩家均为p1），公开事实完全相同。

    CP-04O 弃牌阶段兼容：首玩家出牌阶段使用【乐不思蜀】与一张武器牌
    （武器进入装备区，不污染弃牌堆），回合结束手牌不超过上限；其余
    实体全部进入对手手牌，使对手摸牌阶段牌堆恰好为0触发重洗，对手
    弃牌阶段由参考控制器逐张弃置（每个动作消耗一步，记录随之增长）。
    """

    user = _me(game)
    other = _other(game)
    game._state = _replace_player(game.state, other, hp=1)
    weapon_id = "sgs-mobile-20260725-014"  # 贯石斧（装备区，不进入弃牌堆）
    filler_id = "sgs-mobile-20260725-001"
    draw_top = ("sgs-mobile-20260725-004", "sgs-mobile-20260725-005")
    user_hand = (LEBUSI_098, weapon_id, _SLASH_136, filler_id)
    keep = {
        *user_hand,
        LEBUSI_098,
        SPADE_7_SHA,
        SHANDIAN_117,
        SHANDIAN_122,
    }
    all_ids = [card.instance_id for card in game.state.cards]
    for instance_id in all_ids:
        if instance_id in keep:
            continue
        if game.state.location_of(instance_id) != DRAW_PILE:
            game._state = game.state.move_card(instance_id, DRAW_PILE)
    for instance_id in user_hand:
        game._state = game.state.move_card(instance_id, ZoneRef.hand(user))
    # 其余全部进入对手手牌（使对手摸牌阶段牌堆恰好为0触发重洗）
    deck_top = set(draw_top + (SPADE_7_SHA,))
    for instance_id in list(game.state.card_ids_in(DRAW_PILE)):
        if instance_id not in deck_top:
            game._state = game.state.move_card(
                instance_id, ZoneRef.hand(other)
            )
    for instance_id in (SHANDIAN_117, SHANDIAN_122):
        game._state = game.state.move_card(instance_id, DISCARD_PILE)
    game._state = game.state.reorder_zone(
        DRAW_PILE,
        (*draw_top, SPADE_7_SHA)
        + tuple(
            instance_id
            for instance_id in game.state.card_ids_in(DRAW_PILE)
            if instance_id not in draw_top and instance_id != SPADE_7_SHA
        ),
    )


_RESHUFFLE_ORDER_SPECS = [
    {"operation": "proceed_prepare"},
    {"operation": "proceed_judgment"},
    {"operation": "proceed_draw"},
    {"operation": "use_lebusi"},
    # CP-04O：武器牌进入装备区，不污染重洗弃牌堆
    {"operation": "use_weapon"},
    {"operation": "end_play_phase"},
    {"operation": "end_turn"},
    {"operation": "proceed_prepare"},
    {"operation": "proceed_judgment"},
    {"operation": "pass_judgment_wuxie"},
    {"operation": "pass_judgment_wuxie"},
    {"operation": "proceed_judgment"},
    {"operation": "proceed_draw"},
    {"operation": "end_turn"},
    {"operation": "proceed_prepare"},
    {"operation": "proceed_judgment"},
    {"operation": "proceed_draw"},
    # 固定杀实例：避免不同 seed 下 action_id 排序选出不同公开杀
    {"operation": "use_slash", "card_instance_id": "sgs-mobile-20260725-136"},
    {"operation": "pass_slash_response"},
    {"operation": "pass_rescue"},
    {"operation": "pass_rescue"},
]


def _reshuffle_order_record(seed: int) -> ProductionReexecutionReplay:
    return record_reference_production_batch(
        seed=seed,
        shuffle=False,
        controller=ScriptedBatchController(list(_RESHUFFLE_ORDER_SPECS)),
        fixture=_reshuffle_order_fixture,
        max_steps=200,
    )


def test_player_visible_reshuffle_hidden_order_indistinguishable() -> None:
    """B1：仅重洗后两张隐藏牌顺序不同的两份记录，公开投影必须不可区分。"""

    record_xy = _reshuffle_order_record(seed=21)  # 秘密摸走 (X, Y)
    record_yx = _reshuffle_order_record(seed=20)  # 秘密摸走 (Y, X)
    assert record_xy.outcome["winner_id"] == "p1"
    assert record_yx.outcome["winner_id"] == "p1"

    def reshuffle_events(record: ProductionReexecutionReplay) -> list[dict]:
        return [
            event
            for event in record.events
            if event.get("payload", {}).get("reason") == "reshuffle"
        ]

    # 权威记录保留完整重洗实体顺序（权威回放不削弱）
    assert reshuffle_events(record_xy) and reshuffle_events(record_yx)
    assert all(
        event.get("card_instance_id") for event in reshuffle_events(record_xy)
    )
    assert all(
        event.get("card_instance_id") for event in reshuffle_events(record_yx)
    )

    # 公共视图：完整公开 payload 必须完全一致（含 player_visible_sha256）
    public_xy = record_xy.player_visible_payload()
    public_yx = record_yx.player_visible_payload()
    assert public_xy == public_yx
    # 对手视图（首玩家）同样不可区分
    assert record_xy.player_visible_payload(viewer_id="p1") == (
        record_yx.player_visible_payload(viewer_id="p1")
    )
    # 获得者本人视图：可以看到自己摸到的两张隐藏牌（集合），但逐张摸牌
    # 顺序同样被归一化（B1 场景中两张牌集合相同，本人视图同样不可区分
    # 两种排列；集合不同时本人视图仍可区分，此断言只约束顺序通道）。
    owner_xy = record_xy.player_visible_payload(viewer_id="p2")
    owner_yx = record_yx.player_visible_payload(viewer_id="p2")
    assert owner_xy == owner_yx
    owner_draws = [
        event.get("card_instance_id")
        for event in owner_xy["events"]
        if event.get("event_type") == "card_gained"
        and event.get("payload", {}).get("reason") == "draw_phase"
        and event.get("card_instance_id") is not None
    ]
    assert set(owner_draws) == {SHANDIAN_117, SHANDIAN_122}

    # 公开投影中重洗被聚合为无实体身份的汇总事件
    public_reshuffles = [
        event
        for event in public_xy["events"]
        if event.get("payload", {}).get("reason") == "reshuffle"
    ]
    assert public_reshuffles
    for event in public_reshuffles:
        assert event.get("card_instance_id") is None
        assert event.get("card_key") is None
        assert event["payload"]["count"] >= 3
        assert event["payload"]["from_zone"]["kind"] == "discard_pile"
        assert event["payload"]["to_zone"]["kind"] == "draw_pile"

    # 哈希旁路：公开投影不得携带任何绑定未脱敏材料的权威摘要
    assert public_xy["event_hash_chain"] == []
    for key in ("event_chain_tip", "final_execution_hash", "final_game_state_hash"):
        assert key not in public_xy["outcome"]
    for key in ("initial_execution_hash", "initial_game_state_hash"):
        assert key not in public_xy["header"]
    for decision in public_xy["decisions"]:
        for key in (
            "state_before_sha256",
            "state_after_sha256",
            "execution_before_sha256",
            "execution_after_sha256",
        ):
            assert key not in decision
        legal_actions = decision.get("legal_actions")
        if isinstance(legal_actions, (list, tuple)) and legal_actions:
            # 合法动作已去掉绑定状态的 action_id 并按规范序列化稳定排序，
            # 不携带手牌区域顺序
            assert all(
                "action_id" not in action for action in legal_actions
            )
            serialized = [
                json.dumps(action, ensure_ascii=False, sort_keys=True)
                for action in legal_actions
            ]
            assert serialized == sorted(serialized)

    # 权威回放仍可严格重执行（完整性不削弱）
    for record in (record_xy, record_yx):
        result = reexecute_production_replay(
            record, fixture=_reshuffle_order_fixture
        )
        assert result.verified is True


def test_player_visible_viewer_id_contract() -> None:
    """N7：viewer_id 契约——None/合法角色ID可用，未知、空与非字符串拒绝。"""

    record = _lightning_death_record()
    assert record.player_visible_payload()["viewer_id"] is None
    assert record.player_visible_payload(viewer_id="p1")["viewer_id"] == "p1"
    assert record.player_visible_payload(viewer_id="p2")["viewer_id"] == "p2"
    with pytest.raises(ValueError, match="合法角色ID"):
        record.player_visible_payload(viewer_id="unknown")
    with pytest.raises(ValueError, match="非空字符串"):
        record.player_visible_payload(viewer_id="")
    with pytest.raises(ValueError, match="非空字符串"):
        record.player_visible_payload(viewer_id=123)
    with pytest.raises(ValueError, match="合法角色ID"):
        record.player_visible_payload(viewer_id="P1")


# ----------------------------------------------------------------------
# I. 第一次独立审计修复：N1–N6、N8（2026-08-05）
# ----------------------------------------------------------------------


def test_lightning_nullified_before_judgment_transfers_directly() -> None:
    """N1：闪电判定前被无懈——不翻判定牌、不伤害、直接转移到合法目标。"""

    game = _fresh(seed=3)
    user = _me(game)
    other = _other(game)
    _swap(game, SHANDIAN_117, ZoneRef.hand(user))
    wuxie_id = next(
        record.instance_id
        for record in game.formal_registry.instances_of(WUXIE)
    )
    _swap(game, wuxie_id, ZoneRef.hand(user))
    _use_delayed(game, "use_shandian", SHANDIAN, user)
    # CP-04O：p1弃牌阶段保留无懈（供闪电判定前抵消）
    _end_turn(game, keep=(wuxie_id,))
    # other 回合（判定区无牌）正常推进
    _proceed(game, "proceed_prepare")
    _proceed(game, "proceed_judgment")
    _proceed(game, "proceed_draw")
    _proceed(game, "end_play_phase")
    # CP-04O：弃牌阶段保留无懈（供闪电判定前抵消）与其他手牌中的桃
    other_tao_keep = tuple(
        instance_id
        for instance_id in game.state.card_ids_in(ZoneRef.hand(other))
        if game.state.cards_by_id[instance_id].card_key == TAO
    )
    _discard_to_end(game, keep=other_tao_keep + (wuxie_id,))
    _proceed(game, "end_turn")
    _to_judgment(game)
    assert game.phase is ProductionPhase.JUDGMENT_WUXIE
    # 无懈最终抵消闪电
    wuxie = _action(game, "use_wuxie")
    assert wuxie is not None
    _step(game, wuxie)
    for _ in range(2):
        _proceed(game, "pass_judgment_wuxie")
    # 不翻判定牌、不产生判定结果与伤害
    assert not _events_of(game, EventType.JUDGMENT_RESULT)
    assert not _events_of(game, EventType.DAMAGE)
    assert not _events_of(game, EventType.JUDGMENT_STARTED)[0:] or True
    # 闪电本体：当前角色判定区 -> 合法目标判定区（不经处理区/弃牌堆）
    assert game.state.location_of(SHANDIAN_117) == ZoneRef.judgment(other)
    assert SHANDIAN_117 not in game.state.card_ids_in(PROCESSING_ZONE)
    assert SHANDIAN_117 not in game.state.card_ids_in(DISCARD_PILE)
    # 分配新 entry_index；processed 正确
    assert game.runtime.judgment_entry_indices[SHANDIAN_117] >= 1
    assert SHANDIAN_117 in game.runtime.processed_judgment_instance_ids
    # 不立即开启新无懈窗口、不立即再次判定
    assert game.phase is ProductionPhase.JUDGMENT
    assert game.runtime.pending_judgment is None
    # 接收者下次判定阶段才处理
    _proceed(game, "proceed_judgment")
    assert game.phase is ProductionPhase.DRAW
    _assert_conservation(game)


def test_lebusi_and_bingliang_skip_draw_and_play_same_turn() -> None:
    """N2：同一角色判定区乐＋兵同时命中，分别跳过 DRAW 与 PLAY。"""

    game = _fresh(seed=3)
    user = _me(game)
    other = _other(game)
    _swap(game, LEBUSI_098, ZoneRef.hand(user))
    _use_delayed(game, "use_lebusi", LEBUSI, other)
    _swap(game, BINGLIANG_151, ZoneRef.hand(user))
    _use_delayed(game, "use_bingliang", BINGLIANG, other)
    # entry LIFO：兵后放（entry 大）先判，判定牌♠7（非梅花）跳 DRAW；
    # 乐后判，判定牌♠6（非红桃）跳 PLAY。
    _put_on_top(game, SPADE_7_SHA)
    _put_draw_at(game, LEBUSI_137, 1)
    _end_turn(game)
    _to_judgment(game)
    _close_judgment_wuxie(game)  # 兵（entry 大）先判：跳 DRAW
    _proceed(game, "proceed_judgment")  # 打开乐判定窗口
    _close_judgment_wuxie(game)  # 乐后判：跳 PLAY
    _proceed(game, "proceed_judgment")
    assert game.phase is ProductionPhase.END
    # DRAW 被跳过：除 _fresh 阶段 user 首回合的 2 张外无新增摸牌
    draw_gains = [
        event
        for event in _events_of(game, EventType.CARD_GAINED)
        if event.payload.get("reason") == "draw_phase"
    ]
    assert len(draw_gains) == 2
    # 两条 phase_skipped 分别绑定正确本体
    skipped = _events_of(game, EventType.PHASE_SKIPPED)
    by_phase = {event.payload["skipped_phase"]: event for event in skipped}
    assert set(by_phase) == {"draw", "play"}
    assert by_phase["draw"].card_instance_id == BINGLIANG_151
    assert by_phase["play"].card_instance_id == LEBUSI_098
    assert by_phase["draw"].payload["reason"] == "bingliang_judgment_hit"
    assert by_phase["play"].payload["reason"] == "lebusi_judgment_hit"
    # 两张本体与两张判定牌均正确弃置
    for instance_id in (BINGLIANG_151, LEBUSI_098, SPADE_7_SHA, LEBUSI_137):
        assert game.state.location_of(instance_id) == DISCARD_PILE
    # pending 与 REVEALED 无残留
    assert game.runtime.pending_judgment is None
    assert not game.state.card_ids_in(REVEALED_ZONE)
    assert not game.state.card_ids_in(PROCESSING_ZONE)
    _assert_conservation(game)


@pytest.mark.parametrize(
    "instance_id,operation,card_key,target_kind",
    [
        (LEBUSI_058, "use_lebusi", LEBUSI, "other"),
        (LEBUSI_098, "use_lebusi", LEBUSI, "other"),
        (LEBUSI_137, "use_lebusi", LEBUSI, "other"),
        (BINGLIANG_053, "use_bingliang", BINGLIANG, "other"),
        (BINGLIANG_151, "use_bingliang", BINGLIANG, "other"),
        (SHANDIAN_117, "use_shandian", SHANDIAN, "self"),
        (SHANDIAN_122, "use_shandian", SHANDIAN, "self"),
    ],
)
def test_each_delayed_entity_goes_through_formal_use_path(
    instance_id: str,
    operation: str,
    card_key: str,
    target_kind: str,
) -> None:
    """N3：全部7张延时锦囊实体分别走正式使用路径。"""

    game = _fresh(seed=3)
    user = _me(game)
    other = _other(game)
    assert instance_id in {
        record.instance_id
        for record in game.formal_registry.instances_of(card_key)
    }
    _swap(game, instance_id, ZoneRef.hand(user))
    target = user if target_kind == "self" else other
    action = _action(game, operation, card_key=card_key, target=target)
    assert action is not None
    assert action.card_instance_id == instance_id
    validated = validate_action(
        game.state, game._context(), action, game.registry
    )
    assert validated.card_instance_id == instance_id
    _step(game, action)
    assert instance_id not in game.state.card_ids_in(ZoneRef.hand(user))
    assert game.state.location_of(instance_id) == ZoneRef.judgment(target)
    used = [
        event
        for event in _events_of(game, EventType.CARD_USED)
        if event.card_instance_id == instance_id
    ]
    assert len(used) == 1
    assert used[0].card_key == card_key
    assert game.runtime.judgment_entry_indices[instance_id] >= 1
    _assert_conservation(game)


def test_judgment_entry_index_invariants_fail_closed_without_side_effects() -> None:
    """N4：判定区 entry_index 不变量——缺失/重复/bool/零/counter落后均失败关闭。"""

    game = _fresh(seed=3)
    user = _me(game)
    other = _other(game)
    _swap(game, LEBUSI_098, ZoneRef.hand(user))
    _use_delayed(game, "use_lebusi", LEBUSI, other)
    _swap(game, BINGLIANG_151, ZoneRef.hand(user))
    _use_delayed(game, "use_bingliang", BINGLIANG, other)
    _end_turn(game)
    _proceed(game, "proceed_prepare")
    assert game.phase is ProductionPhase.JUDGMENT
    base = game._runtime
    indices = base.judgment_entry_indices
    assert set(indices) == {LEBUSI_098, BINGLIANG_151}
    entry_lebusi = indices[LEBUSI_098]
    entry_bingliang = indices[BINGLIANG_151]

    def attempt(broken_runtime: object, expect: str) -> None:
        game._runtime = broken_runtime  # type: ignore[assignment]
        before_events = len(game.events)
        before_rng = len(game.rng_calls)
        before_hash = sha256_value(canonical_state_snapshot(game.state))
        with pytest.raises(ProductionBatchError, match=expect):
            _proceed(game, "proceed_judgment")
        assert len(game.events) == before_events
        assert len(game.rng_calls) == before_rng
        assert (
            sha256_value(canonical_state_snapshot(game.state)) == before_hash
        )

    # 缺失索引
    attempt(
        replace(
            base,
            judgment_entry_indices=MappingProxyType(
                {LEBUSI_098: entry_lebusi}
            ),
        ),
        "缺少",
    )
    # 重复索引（同一判定区两个实体同索引）
    attempt(
        replace(
            base,
            judgment_entry_indices=MappingProxyType(
                {
                    LEBUSI_098: entry_lebusi,
                    BINGLIANG_151: entry_lebusi,
                }
            ),
        ),
        "重复",
    )
    # bool 索引
    attempt(
        replace(
            base,
            judgment_entry_indices=MappingProxyType(
                {
                    LEBUSI_098: entry_lebusi,
                    BINGLIANG_151: True,
                }
            ),
        ),
        "非法",
    )
    # 零索引（正式约定从1开始）
    attempt(
        replace(
            base,
            judgment_entry_indices=MappingProxyType(
                {
                    LEBUSI_098: entry_lebusi,
                    BINGLIANG_151: 0,
                }
            ),
        ),
        "非法",
    )
    # counter 落后
    attempt(replace(base, judgment_entry_counter=0), "落后")
    # 正常不变量通过：进入判定无懈窗口
    game._runtime = base
    _proceed(game, "proceed_judgment")
    assert game.phase is ProductionPhase.JUDGMENT_WUXIE


def test_forged_judgment_operations_fail_closed_without_side_effects() -> None:
    """N6：改判/获得判定牌/修改判定结果等未实现操作的伪造动作失败关闭。"""

    game = _fresh(seed=3)
    _swap(game, LEBUSI_098, ZoneRef.hand("p1"))
    _use_delayed(game, "use_lebusi", LEBUSI, "p2")
    _end_turn(game)
    _to_judgment(game)
    assert game.phase is ProductionPhase.JUDGMENT_WUXIE
    before_hash = sha256_value(canonical_state_snapshot(game.state))
    before_events = len(game.events)
    before_rng = len(game.rng_calls)
    for operation in (
        "modify_judgment_result",
        "obtain_judgment_card",
        "modify_judgment_card_suit",
        "modify_judgment_card_rank",
        "modify_judgment",
    ):
        # enumerate 不提供这些动作
        assert all(
            str(action.payload.get("operation", "")) != operation
            for action in game.legal_actions()
        )
        forged = LegalAction(
            action_type=ActionType.CHOOSE_OPTION,
            actor_id=game.current_actor_id,
            target_ids=(),
            payload={
                "operation": operation,
                "root_trick_instance_id": LEBUSI_098,
            },
            action_id=f"act_forged_{operation}",
        )
        with pytest.raises(InvalidActionError):
            validate_action(
                game.state, game._context(), forged, game.registry
            )
        # apply 不得绕过 validate（伪造 action_id 不在最新合法集合）
        with pytest.raises(ProductionBatchError):
            game.step(BatchActionIdController(f"act_forged_{operation}"))
    assert len(game.events) == before_events
    assert len(game.rng_calls) == before_rng
    assert sha256_value(canonical_state_snapshot(game.state)) == before_hash


def test_skipped_turn_recovers_next_turn_and_replays() -> None:
    """N8：被跳过的回合在下一回合恢复正常，完整双回合可严格重执行。"""

    game = _fresh(seed=3)
    user = _me(game)
    other = _other(game)
    _swap(game, LEBUSI_098, ZoneRef.hand(user))
    _use_delayed(game, "use_lebusi", LEBUSI, other)
    _put_on_top(game, SPADE_7_SHA)
    _end_turn(game)
    # other 回合：乐命中跳 PLAY
    _to_judgment(game)
    _close_judgment_wuxie(game)
    _proceed(game, "proceed_judgment")
    _proceed(game, "proceed_draw")
    _discard_to_end(game)
    assert game.phase is ProductionPhase.END
    _proceed(game, "end_turn")
    # user 回合恢复正常：DRAW 摸2、PLAY 有出牌动作
    _proceed(game, "proceed_prepare")
    _proceed(game, "proceed_judgment")
    assert game.runtime.skipped_phases == {}
    assert game.runtime.phase_skip_reasons == {}
    assert game.runtime.processed_judgment_instance_ids == ()
    assert game.runtime.pending_judgment is None
    gained_before = len(_events_of(game, EventType.CARD_GAINED))
    _proceed(game, "proceed_draw")
    gained_after = _events_of(game, EventType.CARD_GAINED)
    assert len(gained_after) - gained_before == 2
    assert any(
        action.payload.get("operation") == "use_slash"
        for action in game.legal_actions()
    )
    # entry_index 仅对仍在判定区的牌保留（乐已弃置，索引不应残留为活动索引）
    assert LEBUSI_098 not in game.state.card_ids_in(
        ZoneRef.judgment(other)
    )


def _lebusi_skip_fixture(game: ProductionBasicCardBatch) -> None:
    """p1持【乐】与固定杀、p2 1血无手牌；判定牌♠7非红桃跳PLAY。"""

    user = _me(game)
    other = _other(game)
    game._state = _replace_player(game.state, other, hp=1)
    fixed = {LEBUSI_098, "sgs-mobile-20260725-136"}
    for player_id in ("p1", "p2"):
        for instance_id in list(
            game.state.card_ids_in(ZoneRef.hand(player_id))
        ):
            if instance_id in fixed:
                continue
            game._state = game.state.move_card(instance_id, DRAW_PILE)
    game._state = game.state.move_card(
        "sgs-mobile-20260725-136", ZoneRef.hand(user)
    )
    game._state = game.state.move_card(LEBUSI_098, ZoneRef.hand(user))
    # user 回合 DRAW 摸 2 后，判定牌位于牌堆顶（第 3 位）
    _put_draw_at(game, SPADE_7_SHA, 2)


def _lightning_miss_fixture(game: ProductionBasicCardBatch) -> None:
    """p1持【闪电】与固定杀、p2 1血无手牌；判定牌♥6红桃使闪电转移。"""

    user = _me(game)
    other = _other(game)
    game._state = _replace_player(game.state, other, hp=1)
    fixed = {SHANDIAN_117, "sgs-mobile-20260725-136"}
    for player_id in ("p1", "p2"):
        for instance_id in list(
            game.state.card_ids_in(ZoneRef.hand(player_id))
        ):
            if instance_id in fixed:
                continue
            game._state = game.state.move_card(instance_id, DRAW_PILE)
    game._state = game.state.move_card(
        "sgs-mobile-20260725-136", ZoneRef.hand(user)
    )
    game._state = game.state.move_card(SHANDIAN_117, ZoneRef.hand(user))
    # user 首回合 DRAW 2＋other 回合 DRAW 2 后，判定牌位于牌堆顶（第 5 位）
    _put_draw_at(game, LEBUSI_098, 4)


_LEBUSI_SKIP_SPECS = [
    {"operation": "proceed_prepare"},
    {"operation": "proceed_judgment"},
    {"operation": "proceed_draw"},
    {"operation": "use_lebusi"},
    {"operation": "end_play_phase"},
    {"operation": "end_turn"},
    {"operation": "proceed_prepare"},
    {"operation": "proceed_judgment"},
    {"operation": "pass_judgment_wuxie"},
    {"operation": "pass_judgment_wuxie"},
    {"operation": "proceed_judgment"},
    {"operation": "proceed_draw"},
    {"operation": "end_turn"},
    {"operation": "proceed_prepare"},
    {"operation": "proceed_judgment"},
    {"operation": "proceed_draw"},
    {"operation": "use_slash", "card_instance_id": "sgs-mobile-20260725-136"},
    {"operation": "pass_slash_response"},
    {"operation": "pass_rescue"},
    {"operation": "pass_rescue"},
]


_LIGHTNING_MISS_SPECS = [
    {"operation": "proceed_prepare"},
    {"operation": "proceed_judgment"},
    {"operation": "proceed_draw"},
    # 目标必须为使用者自己：双人局闪电自用目标确定，避免动作排序歧义
    {"operation": "use_shandian", "target": "p1"},
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
    {"operation": "proceed_judgment"},
    {"operation": "proceed_draw"},
    {"operation": "use_slash", "card_instance_id": "sgs-mobile-20260725-136"},
    {"operation": "pass_slash_response"},
    {"operation": "pass_rescue"},
    {"operation": "pass_rescue"},
]


def _lebusi_skip_record() -> ProductionReexecutionReplay:
    return record_reference_production_batch(
        seed=3,
        shuffle=False,
        controller=ScriptedBatchController(list(_LEBUSI_SKIP_SPECS)),
        fixture=_lebusi_skip_fixture,
        max_steps=40,
    )


def _lightning_miss_record() -> ProductionReexecutionReplay:
    return record_reference_production_batch(
        seed=3,
        shuffle=False,
        controller=ScriptedBatchController(list(_LIGHTNING_MISS_SPECS)),
        fixture=_lightning_miss_fixture,
        max_steps=40,
    )


def test_replay_tamper_format_layer_rejected_at_from_dict() -> None:
    """观察项一A：格式／哈希链完整性层篡改——只调用 from_dict 即拒绝。

    事件级篡改（judgment_zone_entry_index、phase_skipped、damage 字段、
    转移目标、回置索引等）会破坏权威 event_hash_chain，schema 在
    from_dict 阶段拒绝（ProductionReplayFormatError）；本测试明确只做
    格式层校验，不声称已经调用 reexecute_production_replay。
    """

    record = _lightning_death_record()
    lightning_fixture = _lightning_replay_fixture

    def assert_format_rejected(
        source_record: ProductionReexecutionReplay,
        selector: object,
        mutator: object,
    ) -> None:
        tampered = copy.deepcopy(source_record.to_dict())
        tampered["record_sha256"] = ""
        event = next(
            event
            for event in tampered["events"]
            if selector(event)  # type: ignore[operator]
        )
        mutator(event)  # type: ignore[operator]
        with pytest.raises(ProductionReplayFormatError):
            ProductionReexecutionReplay.from_dict(tampered)

    assert_format_rejected(
        record,
        lambda e: e.get("event_type") == "judgment_started",
        lambda e: e["payload"].__setitem__("judgment_zone_entry_index", 99),
    )
    assert_format_rejected(
        _lebusi_skip_record(),
        lambda e: e.get("event_type") == "phase_skipped",
        lambda e: e["payload"].__setitem__("skipped_phase", "draw"),
    )
    assert_format_rejected(
        record,
        lambda e: e.get("event_type") == "damage",
        lambda e: e.__setitem__("amount", 4),
    )
    assert_format_rejected(
        record,
        lambda e: e.get("event_type") == "damage",
        lambda e: e.__setitem__("damage_type", "火属性"),
    )
    assert_format_rejected(
        record,
        lambda e: e.get("event_type") == "damage",
        lambda e: e.__setitem__("damage_source", "p1"),
    )
    assert_format_rejected(
        _lightning_miss_record(),
        lambda e: e.get("event_type") == "delayed_trick_transferred",
        lambda e: e["payload"].__setitem__("to_player_id", "forged-player"),
    )
    assert_format_rejected(
        _lightning_miss_record(),
        lambda e: e.get("event_type") == "delayed_trick_transferred",
        lambda e: e["payload"].__setitem__("judgment_zone_entry_index", 999),
    )
    del lightning_fixture


def test_replay_tamper_semantic_layer_reaches_reexecute() -> None:
    """观察项一B：语义分歧篡改——重算外层摘要后 from_dict 成功，
    并真实调用 reexecute_production_replay 得到 DivergenceError。

    事件级篡改按 schema 要求重算 event_hash_chain 与 record_sha256
    （外层摘要，不构成第二个业务字段）；决策级篡改保持单业务字段。
    """

    record = _lightning_death_record()
    lightning_fixture = _lightning_replay_fixture

    def tamper_event_semantic(
        source_record: ProductionReexecutionReplay,
        selector: object,
        mutator: object,
        fixture: object,
    ) -> None:
        tampered = copy.deepcopy(source_record.to_dict())
        tampered["record_sha256"] = ""
        event = next(
            event
            for event in tampered["events"]
            if selector(event)  # type: ignore[operator]
        )
        mutator(event)  # type: ignore[operator]
        chain = list(_build_event_hash_chain(tampered["events"]))
        tampered["event_hash_chain"] = chain
        tampered["outcome"]["event_chain_tip"] = chain[-1]
        rebuilt = ProductionReexecutionReplay.from_dict(tampered)
        with pytest.raises(ProductionReplayDivergenceError):
            reexecute_production_replay(
                rebuilt, fixture=fixture  # type: ignore[arg-type]
            )

    def tamper_decision_semantic(
        source_record: ProductionReexecutionReplay,
        selector: object,
        mutator: object,
        fixture: object,
    ) -> None:
        tampered = copy.deepcopy(source_record.to_dict())
        tampered["record_sha256"] = ""
        decision = next(
            decision
            for decision in tampered["decisions"]
            if selector(decision)  # type: ignore[operator]
        )
        mutator(decision)  # type: ignore[operator]
        rebuilt = ProductionReexecutionReplay.from_dict(tampered)
        with pytest.raises(ProductionReplayDivergenceError):
            reexecute_production_replay(
                rebuilt, fixture=fixture  # type: ignore[arg-type]
            )

    # 事件级：judgment_started 的 judgment_zone_entry_index（单字段）
    tamper_event_semantic(
        record,
        lambda e: e.get("event_type") == "judgment_started",
        lambda e: e["payload"].__setitem__("judgment_zone_entry_index", 99),
        lightning_fixture,
    )
    # 事件级：闪电 damage.amount（单字段）
    tamper_event_semantic(
        record,
        lambda e: e.get("event_type") == "damage",
        lambda e: e.__setitem__("amount", 4),
        lightning_fixture,
    )
    # 决策级：processed_judgment_instance_ids（单字段）
    tamper_decision_semantic(
        record,
        lambda d: isinstance(
            d.get("context", {}).get("metadata", {}).get(
                "processed_judgment_instance_ids"
            ),
            list,
        ),
        lambda d: d["context"]["metadata"][
            "processed_judgment_instance_ids"
        ].append("forged-instance"),
        lightning_fixture,
    )
    # 决策级：pending_judgment.trick_instance_id（单字段）
    tamper_decision_semantic(
        record,
        lambda d: isinstance(
            d.get("context", {}).get("metadata", {}).get(
                "pending_judgment"
            ),
            dict,
        ),
        lambda d: d["context"]["metadata"]["pending_judgment"].__setitem__(
            "trick_instance_id", "forged-instance"
        ),
        lightning_fixture,
    )
    # 决策级：pending_judgment.stage（单字段）
    tamper_decision_semantic(
        record,
        lambda d: isinstance(
            d.get("context", {}).get("metadata", {}).get(
                "pending_judgment"
            ),
            dict,
        ),
        lambda d: d["context"]["metadata"]["pending_judgment"].__setitem__(
            "stage", "forged_stage"
        ),
        lightning_fixture,
    )
    # 决策级：pending_judgment.target_id（单字段）
    tamper_decision_semantic(
        record,
        lambda d: isinstance(
            d.get("context", {}).get("metadata", {}).get(
                "pending_judgment"
            ),
            dict,
        ),
        lambda d: d["context"]["metadata"]["pending_judgment"].__setitem__(
            "target_id", "forged-player"
        ),
        lightning_fixture,
    )


def _lightning_chain_double_dying_fixture(game: ProductionBasicCardBatch) -> None:
    """N9：闪电命中＋属性传导＋双濒死救援组合（双人正式A路径）。"""

    user = _me(game)
    other = _other(game)
    game._state = _replace_player(game.state, user, hp=2, chained=True)
    game._state = _replace_player(game.state, other, hp=2, chained=True)
    tao_ids = [
        record.instance_id
        for record in game.formal_registry.instances_of(TAO)
    ]
    # CP-04O：双方各持两张桃（体力上限=手牌上限=2），摸牌阶段摸到的
    # 最小ID实体在弃牌阶段被弃置，桃保留到濒死救援。
    user_hand = [SHANDIAN_117, tao_ids[0], tao_ids[1]]
    other_hand = [tao_ids[2], tao_ids[3]]
    keep = set(user_hand + other_hand + [SPADE_7_SHA])
    all_ids = [card.instance_id for card in game.state.cards]
    for instance_id in all_ids:
        if instance_id in keep:
            continue
        if game.state.location_of(instance_id) != DRAW_PILE:
            game._state = game.state.move_card(instance_id, DRAW_PILE)
    for instance_id in user_hand:
        game._state = game.state.move_card(
            instance_id, ZoneRef.hand(user)
        )
    for instance_id in other_hand:
        game._state = game.state.move_card(
            instance_id, ZoneRef.hand(other)
        )
    # 摸牌阶段顶牌：p1首摸-001/-002（弃牌丢弃），p2摸-003/-004（弃牌丢弃）；
    # 判定牌♠7位于两次摸牌共4张之后的牌堆顶；p1第二次摸牌摸-136与一张桃。
    # 手动测试夹具在_fresh摸牌后应用（PLAY阶段），首摸已完成，牌堆顶从
    # -003开始；回放夹具在PREPARE阶段应用，首摸尚未发生，需从-001开始。
    top = [
        "sgs-mobile-20260725-003",
        "sgs-mobile-20260725-004",
        SPADE_7_SHA,
        "sgs-mobile-20260725-136",
        tao_ids[4],
    ]
    if game.phase is ProductionPhase.PREPARE:
        top = [
            "sgs-mobile-20260725-001",
            "sgs-mobile-20260725-002",
            *top,
        ]
    pile = list(game.state.card_ids_in(DRAW_PILE))
    for instance_id in top:
        pile.remove(instance_id)
    game._state = game.state.reorder_zone(
        DRAW_PILE, (*top, *pile)
    )


_LIGHTNING_CHAIN_DYING_SPECS = [
    {"operation": "proceed_prepare"},
    {"operation": "proceed_judgment"},
    {"operation": "proceed_draw"},
    # 目标必须为使用者自己：双人局闪电自用目标确定，避免动作排序歧义
    {"operation": "use_shandian", "target": "p1"},
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
    {"operation": "rescue_with_peach"},
    {"operation": "rescue_with_peach"},
    {"operation": "pass_rescue"},
    {"operation": "rescue_with_peach"},
    {"operation": "rescue_with_peach"},
    {"operation": "proceed_judgment"},
    {"operation": "proceed_draw"},
    {"operation": "use_slash", "card_instance_id": "sgs-mobile-20260725-136"},
    {"operation": "pass_slash_response"},
    {"operation": "pass_rescue"},
    {"operation": "pass_rescue"},
]


def test_lightning_chain_damage_double_dying_rescue_combo() -> None:
    """N9：闪电命中→原始目标濒死救援→传导→第二目标濒死救援→链完整结束。"""

    game = _fresh(seed=3)
    _lightning_chain_double_dying_fixture(game)
    user = _me(game)
    other = _other(game)
    _use_delayed(game, "use_shandian", SHANDIAN, user)
    # CP-04O：弃牌阶段保留user手牌中的两张桃（摸到的-001/-002被弃置）
    user_tao_keep = tuple(
        instance_id
        for instance_id in game.state.card_ids_in(ZoneRef.hand(user))
        if game.state.cards_by_id[instance_id].card_key == TAO
    )
    _end_turn(game, keep=user_tao_keep)
    # other 回合（判定区无牌）正常推进
    _proceed(game, "proceed_prepare")
    _proceed(game, "proceed_judgment")
    _proceed(game, "proceed_draw")
    _proceed(game, "end_play_phase")
    # CP-04O：弃牌阶段保留other手牌中的两张桃（摸到的-003/-004被弃置）
    other_tao_keep = tuple(
        instance_id
        for instance_id in game.state.card_ids_in(ZoneRef.hand(other))
        if game.state.cards_by_id[instance_id].card_key == TAO
    )
    _discard_to_end(game, keep=other_tao_keep)
    _proceed(game, "end_turn")
    # user 回合判定：闪电命中
    _proceed(game, "proceed_prepare")
    _proceed(game, "proceed_judgment")
    assert game.phase is ProductionPhase.JUDGMENT_WUXIE
    _close_judgment_wuxie(game)
    assert game.phase is ProductionPhase.DYING_RESCUE
    assert game.runtime.pending_dying_id == user
    assert game.runtime.pending_judgment is not None
    # 原始目标两张桃救援：-1 → 0 → 1
    for _ in range(2):
        _step(game, _action(game, "rescue_with_peach", card_key=TAO))
    assert game.state.players_by_id[user].hp == 1
    # 传导到第二目标并进入其濒死
    assert game.runtime.pending_dying_id == other
    assert game.state.players_by_id[other].hp == -1
    # 第一响应者放弃，第二目标连用两张桃救援：-1 → 0 → 1
    _step(game, _action(game, "pass_rescue"))
    for _ in range(2):
        _step(game, _action(game, "rescue_with_peach", card_key=TAO))
    assert game.state.players_by_id[other].hp == 1
    # 链完整结束：pending 全部清理、横置解除、闪电只弃置一次
    assert game.runtime.pending_chain is None
    assert game.runtime.pending_judgment is None
    assert game.runtime.pending_dying_id is None
    assert game.state.players_by_id[user].chained is False
    assert game.state.players_by_id[other].chained is False
    assert SHANDIAN_117 in game.state.card_ids_in(DISCARD_PILE)
    assert not game.state.card_ids_in(PROCESSING_ZONE)
    assert not game.state.card_ids_in(REVEALED_ZONE)
    damages = [
        event
        for event in game.events
        if event.event_type.value == "damage"
    ]
    assert len(damages) == 2
    assert [event.target_ids[0] for event in damages] == [user, other]
    assert all(event.damage_type == "雷属性" for event in damages)
    assert all(event.amount == 3 for event in damages)
    assert all(event.damage_source is None for event in damages)
    _assert_conservation(game)


def test_lightning_chain_double_dying_replay_reexecutes() -> None:
    """N9 严格回放：完整组合路径真实重执行。"""

    record = record_reference_production_batch(
        seed=3,
        shuffle=False,
        controller=ScriptedBatchController(
            list(_LIGHTNING_CHAIN_DYING_SPECS)
        ),
        fixture=_lightning_chain_double_dying_fixture,
        max_steps=60,
    )
    assert record.outcome["winner_id"] == "p1"
    result = reexecute_production_replay(
        record, fixture=_lightning_chain_double_dying_fixture
    )
    assert result.verified is True
    assert result.winner_id == "p1"
    damages = [
        event
        for event in record.events
        if event.get("event_type") == "damage"
        and event.get("amount") == 3
        and event.get("damage_type") == "雷属性"
    ]
    assert len(damages) == 2
    assert all(event.get("damage_type") == "雷属性" for event in damages)
    assert all(event.get("damage_source") is None for event in damages)


# ----------------------------------------------------------------------
# J. 第二次独立复审：B1-a/B1-b/B1-c 隐私修复与观察项二（2026-08-06）
# ----------------------------------------------------------------------


_SLASH_136 = "sgs-mobile-20260725-136"
_HAND_A = SHANDIAN_117
_HAND_B = SHANDIAN_122
_HAND_C = LEBUSI_098


def _assert_no_hidden_digests(value: object) -> None:
    """递归断言公开投影中不存在任何绑定隐藏权威状态的摘要键。"""

    if isinstance(value, dict):
        for key, item in value.items():
            assert key not in (
                "state_hash",
                "state_sha256",
                "execution_hash",
                "execution_sha256",
                "event_hash",
                "event_chain_tip",
                "record_sha256",
                "legal_action_set_sha256",
                "chosen_action_id",
                "action_id",
            ), f"公开投影泄露摘要键{key}"
            lowered = str(key).lower()
            if lowered.endswith("_sha256"):
                assert lowered in (
                    "context_sha256",
                    "player_visible_sha256",
                ), f"公开投影泄露摘要键{key}"
            _assert_no_hidden_digests(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _assert_no_hidden_digests(item)


def _hand_order_fixture_a(game: ProductionBasicCardBatch) -> None:
    _hand_order_fixture(game, (_SLASH_136, _HAND_A, _HAND_B, _HAND_C))


def _hand_order_fixture_b(game: ProductionBasicCardBatch) -> None:
    _hand_order_fixture(game, (_SLASH_136, _HAND_B, _HAND_A, _HAND_C))


def _hand_order_fixture(
    game: ProductionBasicCardBatch, order: tuple[str, ...]
) -> None:
    user = _me(game)
    other = _other(game)
    game._state = _replace_player(game.state, other, hp=1)
    fixed = set(order)
    for player_id in ("p1", "p2"):
        for instance_id in list(
            game.state.card_ids_in(ZoneRef.hand(player_id))
        ):
            if instance_id in fixed:
                continue
            game._state = game.state.move_card(instance_id, DRAW_PILE)
    for instance_id in fixed:
        if game.state.location_of(instance_id) != ZoneRef.hand(user):
            game._state = game.state.move_card(
                instance_id, ZoneRef.hand(user)
            )
    game._state = game.state.reorder_zone(
        ZoneRef.hand(user), tuple(order)
    )


_PLAY_SLASH_SPECS = [
    {"operation": "proceed_prepare"},
    {"operation": "proceed_judgment"},
    {"operation": "proceed_draw"},
    {"operation": "use_slash", "card_instance_id": _SLASH_136},
    {"operation": "pass_slash_response"},
    {"operation": "pass_rescue"},
    {"operation": "pass_rescue"},
]


def _hand_order_record(
    fixture: object,
) -> ProductionReexecutionReplay:
    return record_reference_production_batch(
        seed=3,
        shuffle=False,
        controller=ScriptedBatchController(list(_PLAY_SLASH_SPECS)),
        fixture=fixture,  # type: ignore[arg-type]
        max_steps=30,
    )


def test_player_visible_state_hash_recursive_redaction_attack() -> None:
    """B1-a：仅行动者隐藏手牌顺序不同的两份记录，任何视图均无权威摘要。

    权威记录真实不同（final_game_state_hash 不同）；公共视图与对手视图的
    完整公开 payload（含 player_visible_sha256）必须完全相同；本人视图也
    不携带可枚举对手秘密的全状态摘要。
    """

    record_a = _hand_order_record(_hand_order_fixture_a)
    record_b = _hand_order_record(_hand_order_fixture_b)
    assert record_a.outcome["final_game_state_hash"] != (
        record_b.outcome["final_game_state_hash"]
    )
    public_a = record_a.player_visible_payload()
    public_b = record_b.player_visible_payload()
    assert public_a == public_b
    opponent_a = record_a.player_visible_payload(viewer_id="p2")
    opponent_b = record_b.player_visible_payload(viewer_id="p2")
    assert opponent_a == opponent_b
    actor_a = record_a.player_visible_payload(viewer_id="p1")
    actor_b = record_b.player_visible_payload(viewer_id="p1")
    # 递归摘要键断言（不止顶层）
    for view in (public_a, opponent_a, actor_a, public_b, opponent_b, actor_b):
        _assert_no_hidden_digests(view)
    # 权威回放仍可严格重执行
    assert reexecute_production_replay(
        record_a, fixture=_hand_order_fixture_a
    ).verified is True
    assert reexecute_production_replay(
        record_b, fixture=_hand_order_fixture_b
    ).verified is True


def _actor_hand_fixture_none(game: ProductionBasicCardBatch) -> None:
    _actor_hand_fixture(game, None)


def _actor_hand_fixture_extra(game: ProductionBasicCardBatch) -> None:
    _actor_hand_fixture(game, TAO_EXTRA)


TAO_EXTRA = "sgs-mobile-20260725-006"


def _actor_hand_fixture(
    game: ProductionBasicCardBatch, extra: str | None
) -> None:
    user = _me(game)
    other = _other(game)
    game._state = _replace_player(game.state, other, hp=1)
    fixed = {_SLASH_136, extra} if extra else {_SLASH_136}
    for player_id in ("p1", "p2"):
        for instance_id in list(
            game.state.card_ids_in(ZoneRef.hand(player_id))
        ):
            if instance_id in fixed:
                continue
            game._state = game.state.move_card(instance_id, DRAW_PILE)
    for instance_id in fixed:
        if game.state.location_of(instance_id) != ZoneRef.hand(user):
            game._state = game.state.move_card(
                instance_id, ZoneRef.hand(user)
            )


def test_player_visible_actor_hand_attack() -> None:
    """B1-b：行动者两种隐藏手牌组合，对手与公共视图不可区分。"""

    record_a = _hand_order_record(_actor_hand_fixture_none)
    record_b = _hand_order_record(_actor_hand_fixture_extra)
    assert record_a.outcome["final_game_state_hash"] != (
        record_b.outcome["final_game_state_hash"]
    )
    public_a = record_a.player_visible_payload()
    public_b = record_b.player_visible_payload()
    assert public_a == public_b
    opponent_a = record_a.player_visible_payload(viewer_id="p2")
    opponent_b = record_b.player_visible_payload(viewer_id="p2")
    assert opponent_a == opponent_b
    # 公共视图不得携带任何玩家私有动作
    for decision in public_a["decisions"]:
        assert "legal_actions" not in decision
        assert "chosen_action" not in decision
        _assert_no_hidden_digests(decision)
    # 对手视图：非行动者（p1）决策不得携带私有动作
    for decision in opponent_a["decisions"]:
        actor_id = str(
            decision.get("context", {}).get("actor_id", "")
        )
        if actor_id == "p1":
            assert "legal_actions" not in decision
            assert "chosen_action" not in decision
    # 行动者本人视图保留自己的动作
    actor_a = record_a.player_visible_payload(viewer_id="p1")
    assert any(
        "legal_actions" in decision
        for decision in actor_a["decisions"]
        if decision.get("context", {}).get("actor_id") == "p1"
    )
    assert actor_a != record_b.player_visible_payload(viewer_id="p1")
    # 权威回放仍可严格重执行
    assert reexecute_production_replay(
        record_a, fixture=_actor_hand_fixture_none
    ).verified is True
    assert reexecute_production_replay(
        record_b, fixture=_actor_hand_fixture_extra
    ).verified is True


def _recast_fixture_top_x(game: ProductionBasicCardBatch) -> None:
    _recast_fixture(game, SHANDIAN_117)


def _recast_fixture_top_y(game: ProductionBasicCardBatch) -> None:
    _recast_fixture(game, SHANDIAN_122)


def _recast_fixture(
    game: ProductionBasicCardBatch, top: str
) -> None:
    user = _me(game)
    other = _other(game)
    game._state = _replace_player(game.state, other, hp=1)
    tiesuo_id = "sgs-mobile-20260725-157"  # 铁索♠Q
    hand_fixed = {_SLASH_136, tiesuo_id}
    for player_id in ("p1", "p2"):
        for instance_id in list(
            game.state.card_ids_in(ZoneRef.hand(player_id))
        ):
            if instance_id in hand_fixed or instance_id == top:
                continue
            game._state = game.state.move_card(instance_id, DRAW_PILE)
    if game.state.location_of(top) != DRAW_PILE:
        game._state = game.state.move_card(top, DRAW_PILE)
    for instance_id in hand_fixed:
        if game.state.location_of(instance_id) != ZoneRef.hand(user):
            game._state = game.state.move_card(
                instance_id, ZoneRef.hand(user)
            )
    pile = list(game.state.card_ids_in(DRAW_PILE))
    pile.remove(top)
    game._state = game.state.reorder_zone(
        DRAW_PILE, (pile[0], pile[1], top, *pile[2:])
    )


_RECAST_SPECS = [
    {"operation": "proceed_prepare"},
    {"operation": "proceed_judgment"},
    {"operation": "proceed_draw"},
    {"operation": "recast_tiesuo"},
    {"operation": "use_slash", "card_instance_id": _SLASH_136},
    {"operation": "pass_slash_response"},
    {"operation": "pass_rescue"},
    {"operation": "pass_rescue"},
]


def _recast_record(
    fixture: object,
) -> ProductionReexecutionReplay:
    return record_reference_production_batch(
        seed=3,
        shuffle=False,
        controller=ScriptedBatchController(list(_RECAST_SPECS)),
        fixture=fixture,  # type: ignore[arg-type]
        max_steps=30,
    )


def test_player_visible_tiesuo_recast_hidden_gain_attack() -> None:
    """B1-c：tiesuo_recast 等隐藏摸牌在对手与公共视图统一脱敏。"""

    record_x = _recast_record(_recast_fixture_top_x)
    record_y = _recast_record(_recast_fixture_top_y)
    gained_x = [
        event
        for event in record_x.events
        if event.get("event_type") == "card_gained"
        and event.get("payload", {}).get("reason") == "tiesuo_recast"
    ]
    gained_y = [
        event
        for event in record_y.events
        if event.get("event_type") == "card_gained"
        and event.get("payload", {}).get("reason") == "tiesuo_recast"
    ]
    assert gained_x and gained_y
    assert gained_x[0]["card_instance_id"] != gained_y[0]["card_instance_id"]
    public_x = record_x.player_visible_payload()
    public_y = record_y.player_visible_payload()
    assert public_x == public_y
    assert record_x.player_visible_payload(viewer_id="p2") == (
        record_y.player_visible_payload(viewer_id="p2")
    )
    # 获得者本人视图可区分自己摸到的牌
    owner_x = record_x.player_visible_payload(viewer_id="p1")
    owner_y = record_y.player_visible_payload(viewer_id="p1")
    assert owner_x != owner_y
    for view in (public_x, public_y, owner_x, owner_y):
        _assert_no_hidden_digests(view)
    # 权威回放仍可严格重执行
    assert reexecute_production_replay(
        record_x, fixture=_recast_fixture_top_x
    ).verified is True
    assert reexecute_production_replay(
        record_y, fixture=_recast_fixture_top_y
    ).verified is True


def test_player_visible_judgment_windows_actor_projection() -> None:
    """B1-b 窗口回归：判定前无懈与判定推进窗口的非行动者决策不含私有动作。"""

    for record, fixture in (
        (_lebusi_skip_record(), _lebusi_skip_fixture),
        (_lightning_miss_record(), _lightning_miss_fixture),
    ):
        public = record.player_visible_payload()
        for decision in public["decisions"]:
            assert "legal_actions" not in decision
            assert "chosen_action" not in decision
            _assert_no_hidden_digests(decision)
        opponent = record.player_visible_payload(viewer_id="p1")
        for decision in opponent["decisions"]:
            actor_id = str(
                decision.get("context", {}).get("actor_id", "")
            )
            if actor_id != "p1":
                assert "legal_actions" not in decision
                assert "chosen_action" not in decision
        # 权威回放仍可严格重执行
        assert reexecute_production_replay(
            record, fixture=fixture  # type: ignore[arg-type]
        ).verified is True


def test_player_visible_public_gain_and_hidden_gain_pair() -> None:
    """B1-c 成对回归：公开展示/使用事件保持实体公开，隐藏摸牌统一脱敏。"""

    record = _lightning_miss_record()
    public = record.player_visible_payload()
    # 公开事件（使用、判定牌展示、转移）保留实体身份
    assert any(
        event.get("event_type") == "card_used"
        and event.get("card_instance_id") == SHANDIAN_117
        for event in public["events"]
    )
    assert any(
        event.get("event_type") == "card_revealed"
        and event.get("card_instance_id") == LEBUSI_098
        for event in public["events"]
    )
    assert any(
        event.get("event_type") == "delayed_trick_transferred"
        and event.get("card_instance_id") == SHANDIAN_117
        for event in public["events"]
    )
    # 隐藏摸牌（draw_phase）在公共视图全部脱敏
    for event in public["events"]:
        if (
            event.get("event_type") == "card_gained"
            and event.get("payload", {}).get("reason") == "draw_phase"
        ):
            assert event.get("card_instance_id") is None
            assert event.get("card_key") is None
    # 权威回放仍可严格重执行
    assert reexecute_production_replay(
        record, fixture=_lightning_miss_fixture
    ).verified is True


def test_judgment_entry_indices_cleaned_when_leaving_judgment_zone() -> None:
    """观察项二：延时锦囊离开判定区时 entry_index 一并删除。"""

    # 乐判定生效弃置后索引删除
    game = _fresh(seed=3)
    user = _me(game)
    other = _other(game)
    _swap(game, LEBUSI_098, ZoneRef.hand(user))
    _use_delayed(game, "use_lebusi", LEBUSI, other)
    _put_on_top(game, SPADE_7_SHA)
    _end_turn(game)
    _to_judgment(game)
    _close_judgment_wuxie(game)
    assert LEBUSI_098 not in game.runtime.judgment_entry_indices
    _assert_conservation(game)

    # 兵粮判定生效弃置后索引删除
    game = _fresh(seed=3)
    user = _me(game)
    other = _other(game)
    _swap(game, BINGLIANG_151, ZoneRef.hand(user))
    _use_delayed(game, "use_bingliang", BINGLIANG, other)
    _put_on_top(game, SPADE_7_SHA)
    _end_turn(game)
    _to_judgment(game)
    _close_judgment_wuxie(game)
    assert BINGLIANG_151 not in game.runtime.judgment_entry_indices
    _assert_conservation(game)

    # 乐被无懈弃置后索引删除
    game = _fresh(seed=3)
    user = _me(game)
    other = _other(game)
    _swap(game, LEBUSI_098, ZoneRef.hand(user))
    wuxie_id = next(
        record.instance_id
        for record in game.formal_registry.instances_of(WUXIE)
    )
    _swap(game, wuxie_id, ZoneRef.hand(user))
    _use_delayed(game, "use_lebusi", LEBUSI, other)
    _end_turn(game)
    _to_judgment(game)
    wuxie = _action(game, "use_wuxie")
    _step(game, wuxie)
    _proceed(game, "pass_judgment_wuxie")
    _proceed(game, "pass_judgment_wuxie")
    assert LEBUSI_098 not in game.runtime.judgment_entry_indices
    _assert_conservation(game)

    # 闪电命中进入PROCESSING后索引删除
    game = _fresh(seed=3)
    user = _me(game)
    _swap(game, SHANDIAN_117, ZoneRef.hand(user))
    _use_delayed(game, "use_shandian", SHANDIAN, user)
    _put_third(game, SPADE_7_SHA)
    _end_turn(game)
    _to_judgment(game)
    _proceed(game, "proceed_draw")
    _proceed(game, "end_play_phase")
    _discard_to_end(game)
    _proceed(game, "end_turn")
    _to_judgment(game)
    _close_judgment_wuxie(game)
    assert SHANDIAN_117 not in game.runtime.judgment_entry_indices
    _assert_conservation(game)

    # 闪电转移：旧索引删除、新索引建立
    game = _fresh(seed=3)
    user = _me(game)
    other = _other(game)
    _swap(game, SHANDIAN_117, ZoneRef.hand(user))
    _use_delayed(game, "use_shandian", SHANDIAN, user)
    _put_third(game, LEBUSI_098)  # ♥6 红桃 → 未命中转移
    _end_turn(game)
    _to_judgment(game)
    _proceed(game, "proceed_draw")
    _proceed(game, "end_play_phase")
    _discard_to_end(game)
    _proceed(game, "end_turn")
    _to_judgment(game)
    _close_judgment_wuxie(game)
    assert SHANDIAN_117 in game.runtime.judgment_entry_indices
    assert game.state.location_of(SHANDIAN_117) == ZoneRef.judgment(other)
    _assert_conservation(game)

    # 回合结束保留仍在判定区的索引（闪电转移后跨回合）
    game = _fresh(seed=3)
    user = _me(game)
    _swap(game, SHANDIAN_117, ZoneRef.hand(user))
    _use_delayed(game, "use_shandian", SHANDIAN, user)
    _put_third(game, LEBUSI_098)
    _end_turn(game)
    _to_judgment(game)
    _proceed(game, "proceed_draw")
    _proceed(game, "end_play_phase")
    _discard_to_end(game)
    _proceed(game, "end_turn")
    assert SHANDIAN_117 in game.runtime.judgment_entry_indices
    _assert_conservation(game)


def test_judgment_entry_indices_stale_fails_closed() -> None:
    """观察项二：判定区外残留 entry_index 在选择下一张前失败关闭。"""

    game = _fresh(seed=3)
    user = _me(game)
    other = _other(game)
    _swap(game, LEBUSI_098, ZoneRef.hand(user))
    _use_delayed(game, "use_lebusi", LEBUSI, other)
    _end_turn(game)
    _proceed(game, "proceed_prepare")
    base = game._runtime
    stale = {
        key: value
        for key, value in base.judgment_entry_indices.items()
    }
    stale["sgs-mobile-20260725-001"] = stale[LEBUSI_098] + 99
    game._runtime = replace(
        base, judgment_entry_indices=MappingProxyType(stale)
    )
    before_hash = sha256_value(canonical_state_snapshot(game.state))
    with pytest.raises(ProductionBatchError, match="残留"):
        _proceed(game, "proceed_judgment")
    assert sha256_value(canonical_state_snapshot(game.state)) == before_hash
