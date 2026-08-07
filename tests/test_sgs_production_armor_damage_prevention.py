# -*- coding: utf-8 -*-
"""CP-04M：正式防具与伤害修正／防止基础设施生产垂直切片测试。

覆盖四种防具（【八卦阵】【仁王盾】【藤甲】【白银狮子】）的正式实体绑定、
主动装备与同槽替换、统一防具伤害修正管线（藤甲火属性伤害+1、白银狮子
限伤、仁王盾黑杀无效、藤甲免疫普通杀／南蛮／万箭）、统一“无视防具”
接口、八卦阵响应窗口内可选发动判定与虚拟闪、白银狮子统一离区恢复、
prevented_zero 语义、伤害事件审计字段、严格回放与 player_visible 隐私。

所有正式正向测试都经过 enumerate -> validate -> apply 真实路径；不使用
mock／monkeypatch／skip／xfail。双人生产切片不可达的边界（真实武器
“无视防具”调用、多人传导顺序、防止类效果）明确标为 B（结构级）或
NOT PROVEN，不宣称完整武器技能或完整装备系统完成。
"""
from __future__ import annotations

import copy

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
    ArmorDamageResolution,
    BatchActionIdController,
    ProductionBasicCardBatch,
    ProductionBatchDeckExhaustedError,
    ProductionBatchFinishedError,
    ProductionPhase,
    ScriptedBatchController,
    _replace_player,
    armor_invalidates_effect,
    resolve_armor_damage,
)
from scripts.sgs_engine.production_cards import (
    PRODUCTION_ARMOR_KEYS,
    BaiyinShiziAdapter,
    BaguaZhenAdapter,
    FormalCardRegistry,
    RenwangDunAdapter,
    TengjiaAdapter,
)
from scripts.sgs_engine.production_replay import (
    ProductionReplayDivergenceError,
    ProductionReplayFormatError,
    ProductionReexecutionReplay,
    record_reference_production_batch,
    reexecute_production_replay,
)

SHA = "sgs_basic_sha"
HUOSHA = "sgs_basic_huosha"
LEISHA = "sgs_basic_leisha"
SHAN = "sgs_basic_shan"
WUXIE = "sgs_trick_wuxiekeji"
WANJIAN = "sgs_trick_wanjianqifa"
NANMAN = "sgs_trick_nanmanruqin"
GUOHE = "sgs_trick_guohechaiqiao"
SHUNSHOU = "sgs_trick_shunshouqianyang"
TAO = "sgs_basic_tao"

BAGUA = "sgs_armor_baguazhen"
RENWANG = "sgs_armor_renwangdun"
TENGJIA = "sgs_armor_tengjia"
BAIYIN = "sgs_armor_baiyinshizi"

# 正式实体（CSV）
BAGUA_045 = "sgs-mobile-20260725-045"  # ♣2 黑
BAGUA_125 = "sgs-mobile-20260725-125"  # ♠2 黑
RENWANG_047 = "sgs-mobile-20260725-047"  # ♣2 黑 EX
TENGJIA_046 = "sgs-mobile-20260725-046"  # ♣2 黑
TENGJIA_126 = "sgs-mobile-20260725-126"  # ♠2 黑
BAIYIN_043 = "sgs-mobile-20260725-043"  # ♣A 黑
RED_SHA_016 = "sgs-mobile-20260725-016"  # ♦6 红
BLACK_SHA_140 = "sgs-mobile-20260725-140"  # ♠7 黑
RED_HEART_098 = "sgs-mobile-20260725-098"  # ♥6 红（八卦红判判定牌）
BLACK_CLUB_058 = "sgs-mobile-20260725-058"  # ♣6 黑（八卦黑判判定牌）
WANJIAN_082 = "sgs-mobile-20260725-082"  # 万箭齐发实体
NANMAN_141 = "sgs-mobile-20260725-141"  # 南蛮入侵实体


# ----------------------------------------------------------------------
# 夹具与路径助手（全部使用不可变GameState与正式牌区移动接口）
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


def _put_on_top(game: ProductionBasicCardBatch, instance_id: str) -> None:
    """把实体牌放到牌堆顶（确定性夹具；仅重排与换位，保持160守恒）。"""
    if game.state.location_of(instance_id) != DRAW_PILE:
        game._state = game.state.move_card(instance_id, DRAW_PILE)
    pile = list(game.state.card_ids_in(DRAW_PILE))
    pile.remove(instance_id)
    game._state = game.state.reorder_zone(DRAW_PILE, (instance_id, *pile))


def _put_draw_third(game: ProductionBasicCardBatch, instance_id: str) -> None:
    """放到牌堆第3位：闪电判定前对手回合的摸牌会消耗前2张。"""
    if game.state.location_of(instance_id) != DRAW_PILE:
        game._state = game.state.move_card(instance_id, DRAW_PILE)
    pile = list(game.state.card_ids_in(DRAW_PILE))
    pile.remove(instance_id)
    pile.insert(2, instance_id)
    game._state = game.state.reorder_zone(DRAW_PILE, tuple(pile))


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


def _events_of(
    game: ProductionBasicCardBatch, event_type: EventType
) -> list:
    return [event for event in game.events if event.event_type is event_type]


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


def _give_exact_hand(
    game: ProductionBasicCardBatch, instance_id: str, player_id: str
) -> None:
    _swap(game, instance_id, ZoneRef.hand(player_id))


def _equip_armor_fixture(
    game: ProductionBasicCardBatch,
    armor_key: str,
    player_id: str,
) -> str:
    """测试夹具：把正式防具实体放入角色防具槽（仅区域移动，非生产装备）。"""
    occupied = {
        instance_id
        for player in game.state.players_by_id
        for instance_id in game.state.card_ids_in(
            ZoneRef.equipment(player, "armor")
        )
    }
    record = next(
        r
        for r in game.formal_registry.records
        if r.card_key == armor_key and r.instance_id not in occupied
    )
    _swap(game, record.instance_id, ZoneRef.equipment(player_id, "armor"))
    return record.instance_id


def _equip_armor_formal(
    game: ProductionBasicCardBatch,
    armor_key: str,
) -> str:
    """当前回合角色通过正式装备路径装备防具。"""
    player_id = _me(game)
    record = next(r for r in game.formal_registry.records if r.card_key == armor_key)
    _give_exact_hand(game, record.instance_id, player_id)
    action = _action(game, "use_armor", card_key=armor_key)
    assert action is not None, "出牌阶段必须能枚举防具装备动作"
    _step(game, action)
    assert game.phase is ProductionPhase.PLAY
    return record.instance_id


def _use_slash_on(
    game: ProductionBasicCardBatch,
    slash_instance_id: str,
    target: str,
) -> str:
    """当前回合角色使用指定实体【杀】；返回杀实体ID。"""
    player_id = _me(game)
    _give_exact_hand(game, slash_instance_id, player_id)
    action = _action(game, "use_slash", card_key=game.state.cards_by_id[
        slash_instance_id
    ].card_key)
    assert action is not None and action.target_ids[0] == target
    _step(game, action)
    return slash_instance_id


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
# A. 注册与牌堆
# ----------------------------------------------------------------------


def test_four_armors_all_entities_from_formal_csv() -> None:
    game = _fresh(seed=3)
    registry = game.formal_registry
    assert isinstance(registry, FormalCardRegistry)
    by_id = {record.instance_id: record for record in registry.records}
    assert {record.instance_id for record in registry.instances_of(BAGUA)} == {
        BAGUA_045,
        BAGUA_125,
    }
    assert {record.instance_id for record in registry.instances_of(RENWANG)} == {
        RENWANG_047,
    }
    assert {record.instance_id for record in registry.instances_of(TENGJIA)} == {
        TENGJIA_046,
        TENGJIA_126,
    }
    assert {record.instance_id for record in registry.instances_of(BAIYIN)} == {
        BAIYIN_043,
    }
    assert by_id[BAGUA_045].suit == "♣" and by_id[BAGUA_045].rank == "2"
    assert by_id[BAGUA_125].suit == "♠" and by_id[BAGUA_125].rank == "2"
    assert by_id[RENWANG_047].suit == "♣" and by_id[RENWANG_047].rank == "2"
    assert by_id[TENGJIA_046].suit == "♣" and by_id[TENGJIA_046].rank == "2"
    assert by_id[TENGJIA_126].suit == "♠" and by_id[TENGJIA_126].rank == "2"
    assert by_id[BAIYIN_043].suit == "♣" and by_id[BAIYIN_043].rank == "A"
    assert len({record.instance_id for record in registry.records}) == 160


def test_armor_adapters_registered_with_specs() -> None:
    game = _fresh(seed=3)
    registry = game.formal_registry
    assert set(PRODUCTION_ARMOR_KEYS) <= set(registry.implemented_card_keys)
    assert isinstance(registry.adapter_for(BAGUA), BaguaZhenAdapter)
    assert isinstance(registry.adapter_for(RENWANG), RenwangDunAdapter)
    assert isinstance(registry.adapter_for(TENGJIA), TengjiaAdapter)
    assert isinstance(registry.adapter_for(BAIYIN), BaiyinShiziAdapter)
    for key in PRODUCTION_ARMOR_KEYS:
        spec = registry.adapter_for(key).rule_spec()
        assert spec["equipment_slot"] == "armor"
        assert spec["use_timing"] == "own_play_phase"
        assert spec["implemented"] is True


def test_registry_counts_updated_after_armor_batch() -> None:
    game = _fresh(seed=3)
    registry = game.formal_registry
    assert len(registry.implemented_card_keys) == 38
    assert len(registry.unimplemented_card_keys) == 0
    assert set(registry.unimplemented_card_keys) == set()
    assert sum(
        len(registry.instances_of(key)) for key in registry.implemented_card_keys
    ) == 160
    registry.assert_no_unimplemented_fallback()
    _assert_conservation(game)


def test_armor_equip_formal_path_and_slot_replacement() -> None:
    game = _fresh(seed=3)
    first = _equip_armor_formal(game, BAGUA)
    armor_slot = ZoneRef.equipment(_me(game), "armor")
    assert game.state.card_ids_in(armor_slot) == (first,)
    equipped = _events_of(game, EventType.EQUIPMENT_EQUIPPED)
    assert len(equipped) == 1
    assert equipped[0].payload["slot"] == "armor"
    # 同槽替换：旧防具进入弃牌堆
    second = next(
        r.instance_id
        for r in game.formal_registry.records
        if r.card_key == RENWANG
    )
    _give_exact_hand(game, second, _me(game))
    action = _action(game, "use_armor", card_key=RENWANG)
    assert action is not None
    _step(game, action)
    assert game.state.card_ids_in(armor_slot) == (second,)
    assert first in game.state.card_ids_in(DISCARD_PILE)
    assert _events_of(game, EventType.EQUIPMENT_REPLACED)
    removed = _events_of(game, EventType.EQUIPMENT_REMOVED)
    assert removed[-1].card_instance_id == first
    _assert_conservation(game)


# ----------------------------------------------------------------------
# B. 八卦阵
# ----------------------------------------------------------------------


def test_bagua_red_judgment_virtual_dodge_cancels_slash() -> None:
    game = _fresh(seed=3)
    _equip_armor_fixture(game, BAGUA, _other(game))
    _put_on_top(game, RED_HEART_098)  # ♥6 红 → 判定成功
    slash_id = _use_slash_on(game, BLACK_SHA_140, _other(game))
    assert game.phase is ProductionPhase.SLASH_RESPONSE
    action = _action(game, "activate_bagua")
    assert action is not None
    _step(game, action)
    # 红判成功：虚拟闪抵消杀，回到出牌阶段
    assert game.phase is ProductionPhase.PLAY
    virtual_dodges = [
        event
        for event in _events_of(game, EventType.CARD_USED)
        if event.card_instance_id is None
        and event.card_key == SHAN
        and event.payload.get("purpose") == "bagua_virtual_dodge"
    ]
    assert len(virtual_dodges) == 1
    cancelled = [
        event
        for event in _events_of(game, EventType.CARD_EFFECT_CANCELLED)
        if event.card_instance_id == slash_id
    ]
    assert cancelled and cancelled[-1].payload["reason"] == "bagua_dodge"
    assert slash_id in game.state.card_ids_in(DISCARD_PILE)
    assert not _events_of(game, EventType.DAMAGE)
    assert not game.state.card_ids_in(REVEALED_ZONE)
    assert not game.state.card_ids_in(PROCESSING_ZONE)
    # 判定牌进入弃牌堆
    assert RED_HEART_098 in game.state.card_ids_in(DISCARD_PILE)
    results = _events_of(game, EventType.ARMOR_JUDGMENT_RESULT)
    assert len(results) == 1
    assert results[0].payload["success"] is True
    assert results[0].payload["judgment_color"] == "红"
    assert results[0].payload["virtual_response_kind"] == "use_dodge"
    started = _events_of(game, EventType.ARMOR_JUDGMENT_STARTED)
    assert len(started) == 1
    assert started[0].payload["response_to_card_key"] == SHA
    _assert_conservation(game)


def test_bagua_black_judgment_fail_then_real_dodge() -> None:
    game = _fresh(seed=3)
    _equip_armor_fixture(game, BAGUA, _other(game))
    _put_on_top(game, BLACK_CLUB_058)  # ♣6 黑 → 判定失败
    dodge = _give_hand(game, _other(game), SHAN)
    _use_slash_on(game, BLACK_SHA_140, _other(game))
    assert game.phase is ProductionPhase.SLASH_RESPONSE
    _step(game, _action(game, "activate_bagua"))
    # 判定失败：仍在闪响应窗口，可继续用真实【闪】
    assert game.phase is ProductionPhase.SLASH_RESPONSE
    results = _events_of(game, EventType.ARMOR_JUDGMENT_RESULT)
    assert results[-1].payload["success"] is False
    assert results[-1].payload["virtual_response_kind"] is None
    # 同一窗口不得再次发动八卦阵
    assert _action(game, "activate_bagua") is None
    _step(game, _action(game, "play_dodge", card_key=SHAN))
    assert game.phase is ProductionPhase.PLAY
    assert dodge in game.state.card_ids_in(DISCARD_PILE)
    assert not _events_of(game, EventType.DAMAGE)


def test_bagua_black_judgment_fail_then_pass_takes_damage() -> None:
    game = _fresh(seed=3)
    _equip_armor_fixture(game, BAGUA, _other(game))
    _put_on_top(game, BLACK_CLUB_058)
    _use_slash_on(game, BLACK_SHA_140, _other(game))
    _step(game, _action(game, "activate_bagua"))
    assert game.phase is ProductionPhase.SLASH_RESPONSE
    hp_before = game.state.players_by_id[_other(game)].hp
    _step(game, _action(game, "pass_slash_response"))
    damages = [
        event
        for event in game.events
        if event.event_type.value == "damage"
    ]
    assert len(damages) == 1
    assert game.state.players_by_id[_other(game)].hp == hp_before - 1


def test_bagua_wanjian_red_judgment_virtual_play_jink() -> None:
    game = _fresh(seed=3)
    _equip_armor_fixture(game, BAGUA, _other(game))
    _put_on_top(game, RED_HEART_098)
    _give_exact_hand(game, WANJIAN_082, _me(game))
    action = _action(game, "use_wanjian", card_key=WANJIAN)
    assert action is not None
    _step(game, action)
    # 无懈链关闭
    _step(game, _action(game, "pass_trick_response"))
    _step(game, _action(game, "pass_trick_response"))
    assert game.phase is ProductionPhase.WANJIAN_RESPONSE
    _step(game, _action(game, "activate_bagua"))
    virtual_plays = [
        event
        for event in _events_of(game, EventType.CARD_PLAYED)
        if event.card_instance_id is None
        and event.card_key == SHAN
        and event.payload.get("purpose") == "bagua_virtual_jink"
    ]
    assert len(virtual_plays) == 1
    assert game.phase is ProductionPhase.PLAY
    assert WANJIAN_082 in game.state.card_ids_in(DISCARD_PILE)
    assert not _events_of(game, EventType.DAMAGE)


def test_bagua_wanjian_black_fail_then_real_jink() -> None:
    game = _fresh(seed=3)
    _equip_armor_fixture(game, BAGUA, _other(game))
    _put_on_top(game, BLACK_CLUB_058)
    _give_hand(game, _other(game), SHAN)
    _give_exact_hand(game, WANJIAN_082, _me(game))
    _step(game, _action(game, "use_wanjian", card_key=WANJIAN))
    _step(game, _action(game, "pass_trick_response"))
    _step(game, _action(game, "pass_trick_response"))
    assert game.phase is ProductionPhase.WANJIAN_RESPONSE
    _step(game, _action(game, "activate_bagua"))
    assert game.phase is ProductionPhase.WANJIAN_RESPONSE
    assert _action(game, "activate_bagua") is None
    _step(game, _action(game, "play_jink_for_wanjian"))
    assert game.phase is ProductionPhase.PLAY
    assert not _events_of(game, EventType.DAMAGE)


def test_bagua_judgment_has_no_wuxie_window() -> None:
    game = _fresh(seed=3)
    _equip_armor_fixture(game, BAGUA, _other(game))
    _put_on_top(game, RED_HEART_098)
    _use_slash_on(game, BLACK_SHA_140, _other(game))
    assert game.phase is ProductionPhase.SLASH_RESPONSE
    assert _action(game, "use_wuxie") is None
    assert not _events_of(game, EventType.JUDGMENT_STARTED)
    _step(game, _action(game, "activate_bagua"))
    # 判定是同步原子步骤，不经过 TRICK_RESPONSE／JUDGMENT_WUXIE 窗口
    assert not _events_of(game, EventType.JUDGMENT_STARTED)
    assert not _events_of(game, EventType.PHASE_SKIPPED)


def test_bagua_deck_exhausted_atomic_failure() -> None:
    game = _fresh(seed=3)
    _equip_armor_fixture(game, BAGUA, _other(game))
    _use_slash_on(game, BLACK_SHA_140, _other(game))
    assert game.phase is ProductionPhase.SLASH_RESPONSE
    # 清空牌堆与弃牌堆
    moves = {
        instance_id: ZoneRef.hand(_me(game))
        for instance_id in game.state.card_ids_in(DRAW_PILE)
    }
    moves.update(
        {
            instance_id: ZoneRef.hand(_me(game))
            for instance_id in game.state.card_ids_in(DISCARD_PILE)
        }
    )
    game._state = game.state.move_cards(moves)
    rng_before = len(game.rng_calls)
    events_before = len(game.events)
    snapshot_before = game.execution_snapshot
    with pytest.raises(ProductionBatchDeckExhaustedError):
        _step(game, _action(game, "activate_bagua"))
    assert len(game.rng_calls) == rng_before
    assert len(game.events) == events_before
    assert game.execution_snapshot == snapshot_before
    assert game.phase is ProductionPhase.SLASH_RESPONSE
    assert game.runtime.bagua_attempted is False
    assert not _events_of(game, EventType.CARD_REVEALED)


def test_bagua_forged_and_duplicate_actions_fail_closed() -> None:
    game = _fresh(seed=3)
    armor_id = _equip_armor_fixture(game, BAGUA, _other(game))
    _put_on_top(game, RED_HEART_098)
    _use_slash_on(game, BLACK_SHA_140, _other(game))
    forged = LegalAction(
        action_type=ActionType.PASS,
        actor_id=_other(game),
        card_instance_id=armor_id,
        target_ids=(_other(game),),
        payload={
            "operation": "activate_bagua",
            "card_key": BAGUA,
            "card_name": "八卦阵",
            "response_to_card_key": SHA,
            "response_window_id": "forged-window",
        },
        action_id="act_bagua_forged",
    )
    with pytest.raises(InvalidActionError):
        validate_action(game.state, game._context(), forged, game.registry)
    # 非响应者不能发动
    forged_actor = LegalAction(
        action_type=ActionType.PASS,
        actor_id=_me(game),
        card_instance_id=armor_id,
        target_ids=(_me(game),),
        payload={
            "operation": "activate_bagua",
            "card_key": BAGUA,
            "card_name": "八卦阵",
            "response_to_card_key": SHA,
            "response_window_id": "slash-window",
        },
        action_id="act_bagua_wrong_actor",
    )
    with pytest.raises(InvalidActionError):
        validate_action(game.state, game._context(), forged_actor, game.registry)
    _step(game, _action(game, "activate_bagua"))
    assert _action(game, "activate_bagua") is None


# ----------------------------------------------------------------------
# C. 仁王盾
# ----------------------------------------------------------------------


def test_renwang_black_slash_invalidated_without_dodge_or_damage() -> None:
    game = _fresh(seed=3)
    _equip_armor_fixture(game, RENWANG, _other(game))
    slash_id = _use_slash_on(game, BLACK_SHA_140, _other(game))
    # 黑杀无效：不打开闪响应窗口，直接回到出牌阶段
    assert game.phase is ProductionPhase.PLAY
    cancelled = [
        event
        for event in _events_of(game, EventType.CARD_EFFECT_CANCELLED)
        if event.card_instance_id == slash_id
    ]
    assert len(cancelled) == 1
    assert cancelled[0].payload["reason"] == "renwangdun_black_slash"
    assert cancelled[0].payload["invalidated_by_armor"] is True
    assert slash_id in game.state.card_ids_in(DISCARD_PILE)
    assert not _events_of(game, EventType.DAMAGE)
    assert not game.state.card_ids_in(REVEALED_ZONE)
    assert not game.state.card_ids_in(PROCESSING_ZONE)
    # 杀使用次数仍计
    assert game.runtime.slash_used_counts.get(_me(game), 0) == 1
    _assert_conservation(game)


def test_renwang_red_slash_normal_damage() -> None:
    game = _fresh(seed=3)
    _equip_armor_fixture(game, RENWANG, _other(game))
    _use_slash_on(game, RED_SHA_016, _other(game))
    assert game.phase is ProductionPhase.SLASH_RESPONSE
    hp_before = game.state.players_by_id[_other(game)].hp
    _step(game, _action(game, "pass_slash_response"))
    assert game.state.players_by_id[_other(game)].hp == hp_before - 1
    assert not _events_of(game, EventType.CARD_EFFECT_CANCELLED)


def test_renwang_attribute_slash_color_rules() -> None:
    # 火杀全红：正常结算；雷杀全黑：被无效
    game = _fresh(seed=3)
    _equip_armor_fixture(game, RENWANG, _other(game))
    _use_slash_on(game, "sgs-mobile-20260725-012", _other(game))  # 火杀♦4红
    assert game.phase is ProductionPhase.SLASH_RESPONSE
    _step(game, _action(game, "pass_slash_response"))
    damages = [
        event
        for event in game.events
        if event.event_type.value == "damage"
    ]
    assert len(damages) == 1 and damages[0].damage_type == "火属性"
    game2 = _fresh(seed=5)
    _equip_armor_fixture(game2, RENWANG, _other(game2))
    _use_slash_on(game2, "sgs-mobile-20260725-056", _other(game2))  # 雷杀♣5黑
    assert game2.phase is ProductionPhase.PLAY
    cancelled = _events_of(game2, EventType.CARD_EFFECT_CANCELLED)
    assert cancelled and cancelled[-1].payload["reason"] == "renwangdun_black_slash"
    assert not _events_of(game2, EventType.DAMAGE)


def test_renwang_ignore_armor_context_disables_invalidation() -> None:
    game = _fresh(seed=3)
    game._state = _replace_player(game.state, _other(game), hp=4)
    _equip_armor_fixture(game, RENWANG, _other(game))
    # 统一接口：无视防具时黑杀不再被仁王盾无效（真实武器调用 NOT PROVEN）
    result = armor_invalidates_effect(
        game.state,
        victim_id=_other(game),
        card_instance_id=BLACK_SHA_140,
        card_key=SHA,
    )
    assert result is not None
    ignored = armor_invalidates_effect(
        game.state,
        victim_id=_other(game),
        card_instance_id=BLACK_SHA_140,
        card_key=SHA,
        ignore_armor=True,
    )
    assert ignored is None


def test_renwang_no_dodge_consumed_no_dying_no_chain() -> None:
    game = _fresh(seed=3)
    _equip_armor_fixture(game, RENWANG, _other(game))
    dodge = _give_hand(game, _other(game), SHAN)
    _set_chained(game, _other(game), True)
    _use_slash_on(game, BLACK_SHA_140, _other(game))
    assert game.phase is ProductionPhase.PLAY
    # 目标手牌中的【闪】未被消耗
    assert dodge in game.state.card_ids_in(ZoneRef.hand(_other(game)))
    assert not _events_of(game, EventType.DYING)
    assert not _events_of(game, EventType.CHAIN_DAMAGE_STARTED)
    assert game.state.players_by_id[_other(game)].hp == 4


# ----------------------------------------------------------------------
# D. 藤甲
# ----------------------------------------------------------------------


def test_tengjia_normal_slash_nanman_wanjian_invalidated() -> None:
    # 普通杀无效
    game = _fresh(seed=3)
    _equip_armor_fixture(game, TENGJIA, _other(game))
    slash_id = _use_slash_on(game, BLACK_SHA_140, _other(game))
    assert game.phase is ProductionPhase.PLAY
    cancelled = _events_of(game, EventType.CARD_EFFECT_CANCELLED)
    assert cancelled and cancelled[-1].payload["reason"] == "tengjia_invalidates"
    assert slash_id in game.state.card_ids_in(DISCARD_PILE)
    # 南蛮无效：不打开南蛮响应阶段
    game2 = _fresh(seed=7)
    _equip_armor_fixture(game2, TENGJIA, _other(game2))
    _give_exact_hand(game2, NANMAN_141, _me(game2))
    _step(game2, _action(game2, "use_nanman", card_key=NANMAN))
    _step(game2, _action(game2, "pass_trick_response"))
    _step(game2, _action(game2, "pass_trick_response"))
    assert game2.phase is ProductionPhase.PLAY
    resolved = [
        event
        for event in game2.events
        if event.event_type.value == "group_target_resolved"
    ]
    assert resolved and resolved[-1].payload.get("result") == "armor_invalidated"
    assert not _events_of(game2, EventType.DAMAGE)
    # 万箭无效
    game3 = _fresh(seed=9)
    _equip_armor_fixture(game3, TENGJIA, _other(game3))
    _give_exact_hand(game3, WANJIAN_082, _me(game3))
    _step(game3, _action(game3, "use_wanjian", card_key=WANJIAN))
    _step(game3, _action(game3, "pass_trick_response"))
    _step(game3, _action(game3, "pass_trick_response"))
    assert game3.phase is ProductionPhase.PLAY
    assert not _events_of(game3, EventType.DAMAGE)
    assert WANJIAN_082 in game3.state.card_ids_in(DISCARD_PILE)


def test_tengjia_fire_damage_plus_one_thunder_unaffected() -> None:
    # 火杀：1 → 2
    game = _fresh(seed=3)
    _equip_armor_fixture(game, TENGJIA, _other(game))
    _use_slash_on(game, "sgs-mobile-20260725-012", _other(game))
    _step(game, _action(game, "pass_slash_response"))
    damages = [
        event
        for event in game.events
        if event.event_type.value == "damage"
    ]
    assert len(damages) == 1
    assert damages[0].amount == 2
    assert damages[0].damage_type == "火属性"
    assert damages[0].payload["declared_amount"] == 1
    assert damages[0].payload["final_amount"] == 2
    assert damages[0].payload["modifiers"] == ("tengjia_fire_plus_one",)
    assert game.state.players_by_id[_other(game)].hp == 2
    # 雷杀：1（不增加）
    game2 = _fresh(seed=5)
    _equip_armor_fixture(game2, TENGJIA, _other(game2))
    _use_slash_on(game2, "sgs-mobile-20260725-056", _other(game2))
    _step(game2, _action(game2, "pass_slash_response"))
    damages2 = [
        event
        for event in game2.events
        if event.event_type.value == "damage"
    ]
    assert len(damages2) == 1
    assert damages2[0].amount == 1
    assert damages2[0].damage_type == "雷属性"
    assert damages2[0].payload["modifiers"] == ()


def test_tengjia_fire_attack_damage_plus_one() -> None:
    game = _fresh(seed=3)
    _equip_armor_fixture(game, TENGJIA, _other(game))
    # p1 用【火攻】p2：p2 展示 ♥ 手牌，p1 弃 ♥ 手牌
    huogong = next(
        r for r in game.formal_registry.records if r.card_key == "sgs_trick_huogong"
    )
    _give_exact_hand(game, huogong.instance_id, _me(game))
    reveal_record = next(
        r
        for r in game.formal_registry.records
        if r.card_key == "sgs_basic_shan" and r.suit == "♥"
    )
    _give_exact_hand(game, reveal_record.instance_id, _other(game))
    heart_discard = next(
        r
        for r in game.formal_registry.records
        if r.card_key == "sgs_basic_tao" and r.suit == "♥"
    )
    _give_exact_hand(game, heart_discard.instance_id, _me(game))
    action = _action(game, "use_fire_attack", target=_other(game))
    assert action is not None and action.target_ids == (_other(game),)
    _step(game, action)
    _step(game, _action(game, "pass_trick_response"))
    _step(game, _action(game, "pass_trick_response"))
    assert game.phase is ProductionPhase.FIRE_ATTACK_REVEAL
    reveal_actions = [
        a
        for a in game.legal_actions()
        if a.payload.get("operation") == "reveal_card_for_fire_attack"
    ]
    assert reveal_actions
    reveal_handles = game.runtime.fire_attack_reveal_handles
    reveal_handle = next(
        handle
        for handle, instance_id in reveal_handles.items()
        if instance_id == reveal_record.instance_id
    )
    reveal_action = next(
        a
        for a in reveal_actions
        if a.payload.get("handle") == reveal_handle
    )
    _step(game, reveal_action)
    assert game.phase is ProductionPhase.FIRE_ATTACK_DISCARD
    discard_actions = [
        a
        for a in game.legal_actions()
        if a.payload.get("operation") == "discard_same_suit_for_fire_attack"
    ]
    assert discard_actions
    discard_action = next(
        a
        for a in discard_actions
        if a.card_instance_id == heart_discard.instance_id
    )
    _step(game, discard_action)
    damages = [
        event
        for event in game.events
        if event.event_type.value == "damage"
    ]
    assert len(damages) == 1
    assert damages[0].amount == 2
    assert damages[0].damage_type == "火属性"
    assert game.state.players_by_id[_other(game)].hp == 2


def test_tengjia_fire_chain_each_target_modified_independently() -> None:
    game = _fresh(seed=3)
    # p1（当前回合角色）装备藤甲作为原始受伤角色；p2 也装备藤甲
    _equip_armor_fixture(game, TENGJIA, _me(game))
    _equip_armor_fixture(game, TENGJIA, _other(game))
    _set_chained(game, _me(game), True)
    _set_chained(game, _other(game), True)
    # p1 用火杀 p2：p2 火伤 1→2（藤甲）→ 传导基础 2 → p1 火伤 2→3（藤甲）
    _use_slash_on(game, "sgs-mobile-20260725-012", _other(game))
    _step(game, _action(game, "pass_slash_response"))
    damages = [
        event
        for event in game.events
        if event.event_type.value == "damage"
    ]
    assert len(damages) == 2
    assert damages[0].target_ids == (_other(game),)
    assert damages[0].amount == 2
    assert damages[1].target_ids == (_me(game),)
    assert damages[1].amount == 3
    assert damages[1].payload["is_chain_transmitted"] is True
    assert game.state.players_by_id[_other(game)].hp == 2
    assert game.state.players_by_id[_me(game)].hp == 1
    _assert_conservation(game)


def test_tengjia_ignore_armor_context() -> None:
    game = _fresh(seed=3)
    result = armor_invalidates_effect(
        game.state,
        victim_id=_other(game),
        card_instance_id=BLACK_SHA_140,
        card_key=SHA,
    )
    assert result is None  # 未装备防具
    _equip_armor_fixture(game, TENGJIA, _other(game))
    result = armor_invalidates_effect(
        game.state,
        victim_id=_other(game),
        card_instance_id=BLACK_SHA_140,
        card_key=SHA,
    )
    assert result is not None
    ignored = armor_invalidates_effect(
        game.state,
        victim_id=_other(game),
        card_instance_id=BLACK_SHA_140,
        card_key=SHA,
        ignore_armor=True,
    )
    assert ignored is None
    resolution = resolve_armor_damage(
        game.state,
        victim_id=_other(game),
        damage_type="火属性",
        declared_amount=1,
        ignore_armor=True,
    )
    assert resolution.final_amount == 1
    assert resolution.modifiers == ()
    assert resolution.armor_ignored is True


# ----------------------------------------------------------------------
# E. 白银狮子
# ----------------------------------------------------------------------


def test_baiyin_damage_cap_to_one() -> None:
    # 普通杀1点不变
    game = _fresh(seed=3)
    _equip_armor_fixture(game, BAIYIN, _other(game))
    _use_slash_on(game, BLACK_SHA_140, _other(game))
    _step(game, _action(game, "pass_slash_response"))
    assert game.state.players_by_id[_other(game)].hp == 3
    damages = [
        event
        for event in game.events
        if event.event_type.value == "damage"
    ]
    assert damages[-1].amount == 1
    assert damages[-1].payload["modifiers"] == ()
    # 闪电3点→1
    game2 = _fresh(seed=5)
    _equip_armor_fixture(game2, BAIYIN, _me(game2))
    shandian = next(
        r for r in game2.formal_registry.records if r.card_key == "sgs_delayed_shandian"
    )
    _give_exact_hand(game2, shandian.instance_id, _me(game2))
    action = _action(game2, "use_shandian", card_key="sgs_delayed_shandian")
    assert action is not None and action.target_ids == (_me(game2),)
    _step(game2, action)
    _put_draw_third(game2, "sgs-mobile-20260725-140")  # ♠7 命中
    _proceed(game2, "end_play_phase")
    _discard_to_end(game2)
    _proceed(game2, "end_turn")
    _proceed(game2, "proceed_prepare")
    _proceed(game2, "proceed_judgment")
    _step(game2, _action(game2, "proceed_draw"))
    _proceed(game2, "end_play_phase")
    _discard_to_end(game2)
    _proceed(game2, "end_turn")
    _proceed(game2, "proceed_prepare")
    _proceed(game2, "proceed_judgment")
    # 判定前无懈窗口关闭
    _step(game2, _action(game2, "pass_judgment_wuxie"))
    _step(game2, _action(game2, "pass_judgment_wuxie"))
    damages2 = [
        event
        for event in game2.events
        if event.event_type.value == "damage"
    ]
    assert len(damages2) == 1
    assert damages2[0].amount == 1
    assert damages2[0].payload["modifiers"] == ("baiyin_cap_one",)
    assert damages2[0].payload["declared_amount"] == 3
    assert game2.state.players_by_id[_me(game2)].hp == 3


def test_baiyin_wine_slash_capped_to_one() -> None:
    game = _fresh(seed=3)
    _equip_armor_fixture(game, BAIYIN, _other(game))
    _give_hand(game, _me(game), "sgs_basic_jiu")
    _step(game, _action(game, "use_wine_buff", card_key="sgs_basic_jiu"))
    _use_slash_on(game, BLACK_SHA_140, _other(game))
    _step(game, _action(game, "pass_slash_response"))
    damages = [
        event
        for event in game.events
        if event.event_type.value == "damage"
    ]
    assert damages[-1].amount == 1
    assert damages[-1].payload["modifiers"] == ("baiyin_cap_one",)
    assert game.state.players_by_id[_other(game)].hp == 3


def test_baiyin_chain_each_target_capped_independently() -> None:
    game = _fresh(seed=3)
    # 双方横置，p2 装备白银狮子；p1 用雷杀 p2（雷伤1不触发cap）
    _equip_armor_fixture(game, BAIYIN, _other(game))
    _set_chained(game, _me(game), True)
    _set_chained(game, _other(game), True)
    _use_slash_on(game, "sgs-mobile-20260725-056", _other(game))
    _step(game, _action(game, "pass_slash_response"))
    damages = [
        event
        for event in game.events
        if event.event_type.value == "damage"
    ]
    assert len(damages) == 2
    assert damages[0].amount == 1  # 原始1点（cap不触发）
    assert damages[1].amount == 1  # 传导1点（cap不触发）
    assert damages[1].payload["is_chain_transmitted"] is True
    assert game.state.players_by_id[_other(game)].hp == 3
    assert game.state.players_by_id[_me(game)].hp == 3


def test_baiyin_equip_replace_recovers_hp() -> None:
    game = _fresh(seed=3)
    _equip_armor_fixture(game, BAIYIN, _other(game))
    _set_hp(game, _other(game), 3)
    # 当前回合角色 p1 通过正式路径装备新防具触发替换（被替换者是p1自己时）
    # ——替换恢复属于装备者本人，因此构造 p1 装备狮子后替换
    game3 = _fresh(seed=7)
    player = _me(game3)
    _equip_armor_fixture(game3, BAIYIN, player)
    _set_hp(game3, player, 3)
    other_armor = next(
        r
        for r in game3.formal_registry.records
        if r.card_key == RENWANG
    )
    _give_exact_hand(game3, other_armor.instance_id, player)
    _step(game3, _action(game3, "use_armor", card_key=RENWANG))
    recovered = _events_of(game3, EventType.ARMOR_RECOVERED)
    assert len(recovered) == 1
    assert recovered[0].payload["owner_id"] == player
    assert recovered[0].payload["hp_before"] == 3
    assert recovered[0].payload["hp_after"] == 4
    assert recovered[0].payload["reason"] == "equip_replaced"
    assert game3.state.players_by_id[player].hp == 4
    assert BAIYIN_043 in game3.state.card_ids_in(DISCARD_PILE)


def test_baiyin_guohe_discard_recovers_hp() -> None:
    game = _fresh(seed=3)
    _equip_armor_fixture(game, BAIYIN, _other(game))
    _set_hp(game, _other(game), 3)
    guohe = next(r for r in game.formal_registry.records if r.card_key == GUOHE)
    _give_exact_hand(game, guohe.instance_id, _me(game))
    action = _action(game, "use_guohe", card_key=GUOHE)
    assert action is not None and action.target_ids == (_other(game),)
    _step(game, action)
    _step(game, _action(game, "pass_trick_response"))
    _step(game, _action(game, "pass_trick_response"))
    assert game.phase is ProductionPhase.ZONE_CHOICE
    armor_choice = next(
        a
        for a in game.legal_actions()
        if a.payload.get("operation") == "choose_target_zone_card"
        and a.payload.get("zone") == "equipment:armor"
    )
    _step(game, armor_choice)
    recovered = _events_of(game, EventType.ARMOR_RECOVERED)
    assert len(recovered) == 1
    assert recovered[0].payload["reason"] == "guohechaiqiao_discard"
    assert game.state.players_by_id[_other(game)].hp == 4
    assert BAIYIN_043 in game.state.card_ids_in(DISCARD_PILE)
    _assert_conservation(game)


def test_baiyin_shunshou_gain_recovers_hp() -> None:
    game = _fresh(seed=3)
    _equip_armor_fixture(game, BAIYIN, _other(game))
    _set_hp(game, _other(game), 3)
    shunshou = next(
        r for r in game.formal_registry.records if r.card_key == SHUNSHOU
    )
    _give_exact_hand(game, shunshou.instance_id, _me(game))
    action = _action(game, "use_shunshou", card_key=SHUNSHOU)
    assert action is not None and action.target_ids == (_other(game),)
    _step(game, action)
    _step(game, _action(game, "pass_trick_response"))
    _step(game, _action(game, "pass_trick_response"))
    assert game.phase is ProductionPhase.ZONE_CHOICE
    armor_choice = next(
        a
        for a in game.legal_actions()
        if a.payload.get("operation") == "choose_target_zone_card"
        and a.payload.get("zone") == "equipment:armor"
    )
    _step(game, armor_choice)
    recovered = _events_of(game, EventType.ARMOR_RECOVERED)
    assert len(recovered) == 1
    assert recovered[0].payload["reason"] == "shunshouqianyang_gain"
    assert game.state.players_by_id[_other(game)].hp == 4
    assert BAIYIN_043 in game.state.card_ids_in(ZoneRef.hand(_me(game)))
    _assert_conservation(game)


def test_baiyin_full_hp_no_recovery_event() -> None:
    game = _fresh(seed=3)
    player = _me(game)
    _equip_armor_fixture(game, BAIYIN, player)
    other_armor = next(
        r for r in game.formal_registry.records if r.card_key == RENWANG
    )
    _give_exact_hand(game, other_armor.instance_id, player)
    _step(game, _action(game, "use_armor", card_key=RENWANG))
    assert not _events_of(game, EventType.ARMOR_RECOVERED)
    assert game.state.players_by_id[player].hp == 4


def test_baiyin_death_cleanup_no_illegal_recovery() -> None:
    game = _fresh(seed=3)
    _equip_armor_fixture(game, BAIYIN, _other(game))
    _set_hp(game, _other(game), 1)
    _give_hand(game, _other(game), "sgs_basic_tao")  # 无桃场景的手牌残留
    # p1 用杀致死（无闪）
    _use_slash_on(game, BLACK_SHA_140, _other(game))
    _step(game, _action(game, "pass_slash_response"))
    assert game.phase is ProductionPhase.DYING_RESCUE
    _step(game, _action(game, "pass_rescue"))
    _step(game, _action(game, "pass_rescue"))
    assert game.is_finished
    # 死亡清理时白银狮子离区不触发恢复
    assert not _events_of(game, EventType.ARMOR_RECOVERED)
    assert BAIYIN_043 in game.state.card_ids_in(DISCARD_PILE)
    deaths = [
        event
        for event in game.events
        if event.event_type.value == "death"
    ]
    assert len(deaths) == 1


def test_baiyin_ignore_armor_disables_cap() -> None:
    game = _fresh(seed=3)
    _equip_armor_fixture(game, BAIYIN, _other(game))
    resolution = resolve_armor_damage(
        game.state,
        victim_id=_other(game),
        damage_type="雷属性",
        declared_amount=3,
    )
    assert resolution.final_amount == 1
    assert resolution.modifiers == ("baiyin_cap_one",)
    ignored = resolve_armor_damage(
        game.state,
        victim_id=_other(game),
        damage_type="雷属性",
        declared_amount=3,
        ignore_armor=True,
    )
    assert ignored.final_amount == 3
    assert ignored.modifiers == ()
    assert ignored.armor_ignored is True


# ----------------------------------------------------------------------
# F. prevented_zero 与伤害管线
# ----------------------------------------------------------------------


def test_armor_damage_resolution_never_negative_and_prevented_flag() -> None:
    game = _fresh(seed=3)
    resolution = resolve_armor_damage(
        game.state,
        victim_id=_me(game),
        damage_type="无属性",
        declared_amount=0,
    )
    assert resolution.final_amount == 0
    assert resolution.prevented is True
    with pytest.raises(ValueError):
        resolve_armor_damage(
            game.state,
            victim_id=_me(game),
            damage_type="无属性",
            declared_amount=-1,
        )
    with pytest.raises(TypeError):
        resolve_armor_damage(
            game.state,
            victim_id=_me(game),
            damage_type="无属性",
            declared_amount=True,
        )


def test_prevented_zero_no_chain_propagation_regression() -> None:
    """B（结构级）：传导 prevented_zero 语义由 CP-04J 状态机与既有测试
    保持；本批统一接口只提供防止标记，不改变传导终止行为。"""
    from scripts.sgs_engine.production_batch import _chain_recipient_outcome

    unchain, result = _chain_recipient_outcome(0)
    assert unchain is False and result == "prevented_zero"
    unchain, result = _chain_recipient_outcome(1)
    assert unchain is True and result == "damaged"


def test_damage_event_audit_fields_present_on_all_paths() -> None:
    # 无防具时 damage payload 仍携带 declared/final/modifiers/armor_ignored
    game = _fresh(seed=3)
    _use_slash_on(game, BLACK_SHA_140, _other(game))
    _step(game, _action(game, "pass_slash_response"))
    damages = [
        event
        for event in game.events
        if event.event_type.value == "damage"
    ]
    assert len(damages) == 1
    assert damages[0].payload["declared_amount"] == 1
    assert damages[0].payload["final_amount"] == 1
    assert damages[0].payload["modifiers"] == ()
    assert damages[0].payload["armor_ignored"] is False


def test_armor_damage_resolution_returns_public_dataclass() -> None:
    game = _fresh(seed=3)
    resolution = resolve_armor_damage(
        game.state,
        victim_id=_me(game),
        damage_type="火属性",
        declared_amount=1,
    )
    assert isinstance(resolution, ArmorDamageResolution)
    assert resolution.declared_amount == 1
    assert resolution.final_amount == 1


# ----------------------------------------------------------------------
# G. 回归与组合
# ----------------------------------------------------------------------


def test_slash_use_still_normal_without_armor() -> None:
    game = _fresh(seed=3)
    _use_slash_on(game, BLACK_SHA_140, _other(game))
    assert game.phase is ProductionPhase.SLASH_RESPONSE
    _step(game, _action(game, "pass_slash_response"))
    assert game.state.players_by_id[_other(game)].hp == 3
    assert not _events_of(game, EventType.CARD_EFFECT_CANCELLED)


def test_qinggang_gate_still_fails_closed_when_target_has_armor() -> None:
    """真实武器“无视防具”调用仍为 NOT PROVEN：青釭剑对穿防具目标使用
    杀时由集中式武器门禁失败关闭，不得静默接入防具无视效果。"""
    game = _fresh(seed=3)
    _equip_armor_fixture(game, TENGJIA, _other(game))
    qinggang = next(
        r
        for r in game.formal_registry.records
        if r.card_key == "sgs_weapon_qinggangjian"
    )
    _give_exact_hand(game, qinggang.instance_id, _me(game))
    _step(game, _action(game, "use_weapon", card_key="sgs_weapon_qinggangjian"))
    slash_record = next(
        r for r in game.formal_registry.records if r.card_key == SHA
    )
    _give_exact_hand(game, slash_record.instance_id, _me(game))
    with pytest.raises(UnsupportedRuleError):
        _action(game, "use_slash", card_key=SHA)


def test_judgment_entry_indices_invariant_regression() -> None:
    """CP-04L 判定区进入序号不变量在本批防具路径后保持不变。"""
    game = _fresh(seed=3)
    _equip_armor_fixture(game, BAGUA, _other(game))
    assert game.runtime.judgment_entry_counter == 0
    assert game.runtime.judgment_entry_indices == {}
    lebusi = next(
        r
        for r in game.formal_registry.records
        if r.card_key == "sgs_delayed_lebusi"
    )
    _give_exact_hand(game, lebusi.instance_id, _me(game))
    _step(game, _action(game, "use_lebusi", card_key="sgs_delayed_lebusi"))
    assert game.runtime.judgment_entry_indices[lebusi.instance_id] == 1
    assert game.runtime.judgment_entry_counter == 1


def test_public_armor_judgment_visible_in_player_visible_replay(
    bagua_replay_record: ProductionReexecutionReplay,
) -> None:
    record = bagua_replay_record
    view = record.player_visible_payload()
    started_events = [
        event
        for event in view["events"]
        if event.get("event_type") == "armor_judgment_started"
    ]
    assert started_events
    assert started_events[0]["card_instance_id"] == BAGUA_045
    # 判定牌公开展示保持真实实体（八卦阵判定不是隐藏手牌）
    assert any(
        event.get("event_type") == "card_revealed"
        and event.get("payload", {}).get("reason") == "bagua_judgment"
        for event in view["events"]
    )


def _bagua_replay_fixture(game: ProductionBasicCardBatch) -> None:
    """确定性夹具：p2装备八卦阵、p1手牌有黑杀，红判判定牌位于牌堆顶。"""
    _swap(game, BAGUA_045, ZoneRef.equipment(_other(game), "armor"))
    _swap(game, BLACK_SHA_140, ZoneRef.hand(_me(game)))
    _put_on_top(game, RED_HEART_098)


@pytest.fixture(scope="module")
def bagua_replay_record() -> ProductionReexecutionReplay:
    controller = ScriptedBatchController(
        [
            {"operation": "use_slash"},
            {"operation": "activate_bagua"},
            {"operation": "end_play_phase"},
            {"operation": "end_turn"},
        ]
    )
    return record_reference_production_batch(
        seed=3,
        controller=controller,
        fixture=_bagua_replay_fixture,
        max_steps=500,
    )


def test_bagua_strict_replay_reexecutes_virtual_dodge_path(
    bagua_replay_record: ProductionReexecutionReplay,
) -> None:
    record = bagua_replay_record
    assert any(
        event.get("event_type") == "armor_judgment_result"
        and event.get("payload", {}).get("success") is True
        for event in record.events
    )
    assert any(
        event.get("event_type") == "card_used"
        and event.get("card_instance_id") is None
        and event.get("card_key") == SHAN
        for event in record.events
    )
    result = reexecute_production_replay(record, fixture=_bagua_replay_fixture)
    assert result.verified is True


def test_bagua_replay_tamper_fails_closed(
    bagua_replay_record: ProductionReexecutionReplay,
) -> None:
    record = bagua_replay_record
    tampered = copy.deepcopy(record.to_dict())
    result_event = next(
        event
        for event in tampered["events"]
        if event.get("event_type") == "armor_judgment_result"
    )
    result_event["payload"]["judgment_color"] = "黑"
    result_event["payload"]["success"] = False
    result_event["payload"]["virtual_response_kind"] = None
    del tampered["record_sha256"]
    with pytest.raises(
        (ProductionReplayFormatError, ProductionReplayDivergenceError)
    ):
        reexecute_production_replay(
            ProductionReexecutionReplay.from_dict(tampered),
            fixture=_bagua_replay_fixture,
        )


def test_finished_game_stops_armor_actions() -> None:
    game = _fresh(seed=5)
    result = game.run()
    assert game.is_finished
    assert game.winner_id == result.winner_id
    with pytest.raises(ProductionBatchFinishedError):
        game.legal_actions()


def _proceed(game: ProductionBasicCardBatch, operation: str) -> None:
    action = next(
        a
        for a in game.legal_actions()
        if a.payload.get("operation") == operation
    )
    _step(game, action)


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
