# -*- coding: utf-8 -*-
"""CP-04N：正式坐骑与距离／攻击范围基础设施生产垂直切片测试。

覆盖两种坐骑（进攻坐骑-1、防御坐骑+1）的正式实体绑定、装备与同栏位替换、
统一有效距离模型（基础座次距离＋坐骑方向性修正）、武器攻击范围与有效距离
的区别、杀／借刀／顺手／兵粮的距离接入、装备离区立即重算、动作安全与
严格回放、player_visible 隐私与旧批次回归。

所有正式正向测试都经过 enumerate -> validate -> apply 真实路径；不使用
mock／monkeypatch／skip／xfail。多人死亡后座次距离与三人以上距离语义保持
NOT PROVEN，不宣称 multi_player_production_proven。"""
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
    CardInstance,
    GameState,
    PlayerState,
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
    PRODUCTION_MOUNT_KEYS,
    FormalCardRegistry,
    MountCardAdapter,
    actual_distance,
    attack_range_of,
    base_seat_distance,
    effective_distance,
    is_target_within_distance,
    is_valid_shunshou_target,
    is_valid_slash_target,
    SLASH_CARD_KEYS,
    weapon_attack_ranges,
)
from scripts.sgs_engine.production_replay import (
    ProductionReplayDivergenceError,
    ProductionReplayFormatError,
    ProductionReexecutionReplay,
    record_reference_production_batch,
    reexecute_production_replay,
)

SHA = "sgs_basic_sha"
SHAN = "sgs_basic_shan"
GUOHE = "sgs_trick_guohechaiqiao"
SHUNSHOU = "sgs_trick_shunshouqianyang"
BINGLIANG = "sgs_delayed_bingliang"
JIEDAO = "sgs_trick_jiedaosharen"

MOUNT_OFFENSIVE = "sgs_mount_offensive"
MOUNT_DEFENSIVE = "sgs_mount_defensive"

# 正式坐骑实体（CSV）
ZIXUAN_039 = "sgs-mobile-20260725-039"  # 紫骍 ♦K 红（进攻）
CHITU_094 = "sgs-mobile-20260725-094"  # 赤兔 ♥5 红（进攻）
DAWAN_159 = "sgs-mobile-20260725-159"  # 大宛 ♠K 黑（进攻）
HUALIU_040 = "sgs-mobile-20260725-040"  # 骅骝 ♦K 红（防御）
DILU_055 = "sgs-mobile-20260725-055"  # 的卢 ♣5 黑（防御）
ZHAOHUANG_119 = "sgs-mobile-20260725-119"  # 爪黄飞电 ♥K 红（防御）
JUEYING_135 = "sgs-mobile-20260725-135"  # 绝影 ♠5 黑（防御）

BLACK_SHA_140 = "sgs-mobile-20260725-140"  # ♠7 黑杀
RED_SHA_016 = "sgs-mobile-20260725-016"  # ♦6 红杀
QINGGANG = "sgs_weapon_qinggangjian"


# ----------------------------------------------------------------------
# 夹具与路径助手
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


def _set_hp(game: ProductionBasicCardBatch, player_id: str, hp: int) -> None:
    game._state = _replace_player(game.state, player_id, hp=hp)


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


def _give_exact_hand(
    game: ProductionBasicCardBatch, instance_id: str, player_id: str
) -> None:
    _swap(game, instance_id, ZoneRef.hand(player_id))


def _equip_mount_fixture(
    game: ProductionBasicCardBatch,
    mount_key: str,
    player_id: str,
) -> str:
    """测试夹具：把正式坐骑实体放入角色对应坐骑栏（仅区域移动）。"""
    occupied = {
        instance_id
        for player in game.state.players_by_id
        for slot in ("attack_horse", "defense_horse")
        for instance_id in game.state.card_ids_in(
            ZoneRef.equipment(player, slot)
        )
    }
    record = next(
        r
        for r in game.formal_registry.records
        if r.card_key == mount_key and r.instance_id not in occupied
    )
    slot = (
        "attack_horse"
        if mount_key == MOUNT_OFFENSIVE
        else "defense_horse"
    )
    _swap(game, record.instance_id, ZoneRef.equipment(player_id, slot))
    return record.instance_id


def _equip_mount_formal(
    game: ProductionBasicCardBatch,
    mount_key: str,
) -> str:
    """当前回合角色通过正式装备路径装备坐骑。"""
    player_id = _me(game)
    record = next(
        r for r in game.formal_registry.records if r.card_key == mount_key
    )
    _give_exact_hand(game, record.instance_id, player_id)
    action = _action(game, "use_mount", card_key=mount_key)
    assert action is not None, "出牌阶段必须能枚举坐骑装备动作"
    _step(game, action)
    assert game.phase is ProductionPhase.PLAY
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
# A. 正式牌堆与注册
# ----------------------------------------------------------------------


def test_all_seven_mount_entities_from_formal_csv() -> None:
    game = _fresh(seed=3)
    registry = game.formal_registry
    assert isinstance(registry, FormalCardRegistry)
    offensive = registry.instances_of(MOUNT_OFFENSIVE)
    defensive = registry.instances_of(MOUNT_DEFENSIVE)
    assert len(offensive) == 3
    assert len(defensive) == 4
    assert {record.instance_id for record in offensive} == {
        ZIXUAN_039,
        CHITU_094,
        DAWAN_159,
    }
    assert {record.instance_id for record in defensive} == {
        HUALIU_040,
        DILU_055,
        ZHAOHUANG_119,
        JUEYING_135,
    }
    by_id = {record.instance_id: record for record in registry.records}
    assert by_id[ZIXUAN_039].suit == "♦" and by_id[ZIXUAN_039].rank == "K"
    assert by_id[CHITU_094].suit == "♥" and by_id[CHITU_094].rank == "5"
    assert by_id[DAWAN_159].suit == "♠" and by_id[DAWAN_159].rank == "K"
    assert by_id[HUALIU_040].suit == "♦" and by_id[HUALIU_040].rank == "K"
    assert by_id[DILU_055].suit == "♣" and by_id[DILU_055].rank == "5"
    assert by_id[ZHAOHUANG_119].suit == "♥" and by_id[ZHAOHUANG_119].rank == "K"
    assert by_id[JUEYING_135].suit == "♠" and by_id[JUEYING_135].rank == "5"
    assert len({record.instance_id for record in registry.records}) == 160


def test_mount_adapters_registered_with_specs() -> None:
    game = _fresh(seed=3)
    registry = game.formal_registry
    assert set(PRODUCTION_MOUNT_KEYS) <= set(registry.implemented_card_keys)
    offensive = registry.adapter_for(MOUNT_OFFENSIVE)
    defensive = registry.adapter_for(MOUNT_DEFENSIVE)
    assert isinstance(offensive, MountCardAdapter)
    assert isinstance(defensive, MountCardAdapter)
    assert offensive.rule_spec()["equipment_slot"] == "attack_horse"
    assert offensive.rule_spec()["distance_modifier"] == -1
    assert defensive.rule_spec()["equipment_slot"] == "defense_horse"
    assert defensive.rule_spec()["distance_modifier"] == 1


def test_registry_now_covers_all_160_entities() -> None:
    game = _fresh(seed=3)
    registry = game.formal_registry
    assert len(registry.implemented_card_keys) == 38
    assert len(registry.unimplemented_card_keys) == 0
    assert sum(
        len(registry.instances_of(key)) for key in registry.implemented_card_keys
    ) == 160
    registry.assert_no_unimplemented_fallback()
    _assert_conservation(game)


def test_formal_deck_160_unique_ids_conservation() -> None:
    game = _fresh(seed=3)
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


# ----------------------------------------------------------------------
# B. 坐骑装备
# ----------------------------------------------------------------------


def test_mount_equip_formal_path_both_slots() -> None:
    game = _fresh(seed=3)
    player = _me(game)
    _equip_mount_formal(game, MOUNT_OFFENSIVE)
    assert game.state.card_ids_in(
        ZoneRef.equipment(player, "attack_horse")
    ) == (ZIXUAN_039,)
    _equip_mount_formal(game, MOUNT_DEFENSIVE)
    assert game.state.card_ids_in(
        ZoneRef.equipment(player, "defense_horse")
    ) == (HUALIU_040,)
    # 进攻与防御坐骑同时存在，互不覆盖
    assert game.state.card_ids_in(
        ZoneRef.equipment(player, "attack_horse")
    ) == (ZIXUAN_039,)
    equipped = _events_of(game, EventType.EQUIPMENT_EQUIPPED)
    assert len(equipped) == 2
    assert {event.payload["slot"] for event in equipped} == {
        "attack_horse",
        "defense_horse",
    }
    _assert_conservation(game)


def test_mount_same_slot_replacement_atomic() -> None:
    game = _fresh(seed=3)
    player = _me(game)
    _equip_mount_formal(game, MOUNT_OFFENSIVE)
    # 同栏位替换：赤兔（进攻）替换紫骍（进攻）
    _give_exact_hand(game, CHITU_094, player)
    action = _action(game, "use_mount", card_key=MOUNT_OFFENSIVE)
    assert action is not None and action.card_instance_id == CHITU_094
    _step(game, action)
    assert game.state.card_ids_in(
        ZoneRef.equipment(player, "attack_horse")
    ) == (CHITU_094,)
    assert ZIXUAN_039 in game.state.card_ids_in(DISCARD_PILE)
    assert _events_of(game, EventType.EQUIPMENT_REPLACED)
    # 防御坐骑槽不受影响
    _equip_mount_formal(game, MOUNT_DEFENSIVE)
    assert game.state.card_ids_in(
        ZoneRef.equipment(player, "defense_horse")
    ) == (HUALIU_040,)
    _assert_conservation(game)


def test_mount_guohe_discard_and_shunshou_gain() -> None:
    # 过河弃置坐骑
    game = _fresh(seed=3)
    _equip_mount_fixture(game, MOUNT_DEFENSIVE, _other(game))
    guohe = next(r for r in game.formal_registry.records if r.card_key == GUOHE)
    _give_exact_hand(game, guohe.instance_id, _me(game))
    action = _action(game, "use_guohe", card_key=GUOHE)
    assert action is not None and action.target_ids == (_other(game),)
    _step(game, action)
    _step(game, _action(game, "pass_trick_response"))
    _step(game, _action(game, "pass_trick_response"))
    assert game.phase is ProductionPhase.ZONE_CHOICE
    mount_choice = next(
        a
        for a in game.legal_actions()
        if a.payload.get("operation") == "choose_target_zone_card"
        and a.payload.get("zone") == "equipment:defense_horse"
    )
    _step(game, mount_choice)
    assert HUALIU_040 in game.state.card_ids_in(DISCARD_PILE)
    assert not game.state.card_ids_in(
        ZoneRef.equipment(_other(game), "defense_horse")
    )
    # 顺手获得坐骑
    game2 = _fresh(seed=5)
    _equip_mount_fixture(game2, MOUNT_OFFENSIVE, _other(game2))
    shunshou = next(
        r for r in game2.formal_registry.records if r.card_key == SHUNSHOU
    )
    _give_exact_hand(game2, shunshou.instance_id, _me(game2))
    action2 = _action(game2, "use_shunshou", card_key=SHUNSHOU)
    assert action2 is not None and action2.target_ids == (_other(game2),)
    _step(game2, action2)
    _step(game2, _action(game2, "pass_trick_response"))
    _step(game2, _action(game2, "pass_trick_response"))
    assert game2.phase is ProductionPhase.ZONE_CHOICE
    mount_choice2 = next(
        a
        for a in game2.legal_actions()
        if a.payload.get("operation") == "choose_target_zone_card"
        and a.payload.get("zone") == "equipment:attack_horse"
    )
    _step(game2, mount_choice2)
    assert ZIXUAN_039 in game2.state.card_ids_in(ZoneRef.hand(_me(game2)))
    assert not game2.state.card_ids_in(
        ZoneRef.equipment(_other(game2), "attack_horse")
    )
    _assert_conservation(game2)


def test_mount_death_cleanup_and_public_projection() -> None:
    game = _fresh(seed=3)
    _equip_mount_fixture(game, MOUNT_OFFENSIVE, _other(game))
    _equip_mount_fixture(game, MOUNT_DEFENSIVE, _other(game))
    _equip_mount_fixture(game, MOUNT_OFFENSIVE, _me(game))
    _set_hp(game, _other(game), 1)
    _give_exact_hand(game, BLACK_SHA_140, _me(game))
    _step(game, _action(game, "use_slash", card_key=SHA))
    _step(game, _action(game, "pass_slash_response"))
    _step(game, _action(game, "pass_rescue"))
    _step(game, _action(game, "pass_rescue"))
    assert game.is_finished
    assert ZIXUAN_039 in game.state.card_ids_in(DISCARD_PILE)
    assert HUALIU_040 in game.state.card_ids_in(DISCARD_PILE)
    _assert_conservation(game)


def test_mount_forged_equip_action_fails_closed() -> None:
    game = _fresh(seed=3)
    player = _me(game)
    _give_exact_hand(game, ZIXUAN_039, player)
    forged = LegalAction(
        action_type=ActionType.USE_CARD,
        actor_id=player,
        card_instance_id=ZIXUAN_039,
        target_ids=(player,),
        payload={
            "operation": "use_mount",
            "card_key": MOUNT_OFFENSIVE,
            "card_name": "攻击坐骑（-1坐骑）",
            "distance_modifier": -5,
        },
        action_id="act_mount_forged",
    )
    with pytest.raises(InvalidActionError):
        validate_action(game.state, game._context(), forged, game.registry)
    # 伪造 distance 负载不影响权威计算
    assert ZIXUAN_039 in game.state.card_ids_in(ZoneRef.hand(player))


# ----------------------------------------------------------------------
# C. 距离公式
# ----------------------------------------------------------------------


def test_base_seat_distance_two_player_ring() -> None:
    game = _fresh(seed=3)
    assert base_seat_distance(game.state, "p1", "p2") == 1
    assert base_seat_distance(game.state, "p2", "p1") == 1
    assert base_seat_distance(game.state, "p1", "p1") == 0
    with pytest.raises(UnsupportedRuleError):
        base_seat_distance(game.state, "p1", "p3")


def test_effective_distance_offensive_only() -> None:
    game = _fresh(seed=3)
    _equip_mount_fixture(game, MOUNT_OFFENSIVE, "p1")
    # 不同角色距离下限为1：-1坐骑不得把相邻角色距离修正为0
    assert effective_distance(game.state, "p1", "p2") == 1
    # 进攻坐骑只影响装备者到别人，不影响别人到装备者
    assert effective_distance(game.state, "p2", "p1") == 1


def test_effective_distance_defensive_only() -> None:
    game = _fresh(seed=3)
    _equip_mount_fixture(game, MOUNT_DEFENSIVE, "p2")
    assert effective_distance(game.state, "p1", "p2") == 2
    # 防御坐骑只影响别人到装备者，不影响装备者到别人
    assert effective_distance(game.state, "p2", "p1") == 1


def test_effective_distance_both_mounts_combination() -> None:
    game = _fresh(seed=3)
    _equip_mount_fixture(game, MOUNT_OFFENSIVE, "p1")
    _equip_mount_fixture(game, MOUNT_DEFENSIVE, "p2")
    assert effective_distance(game.state, "p1", "p2") == 1
    # 同一角色同时装备进攻与防御坐骑：方向性独立
    game2 = _fresh(seed=5)
    _equip_mount_fixture(game2, MOUNT_OFFENSIVE, "p1")
    _equip_mount_fixture(game2, MOUNT_DEFENSIVE, "p1")
    assert effective_distance(game2.state, "p1", "p2") == 1
    assert effective_distance(game2.state, "p2", "p1") == 2


def test_effective_distance_never_below_one_for_distinct_players() -> None:
    game = _fresh(seed=3)
    _equip_mount_fixture(game, MOUNT_OFFENSIVE, "p1")
    assert effective_distance(game.state, "p1", "p2") == 1
    # 自己到自己的距离固定为0且不被坐骑修正改变
    assert effective_distance(game.state, "p1", "p1") == 0


def test_mount_leaving_restores_distance_immediately() -> None:
    game = _fresh(seed=3)
    _equip_mount_fixture(game, MOUNT_DEFENSIVE, "p2")
    assert effective_distance(game.state, "p1", "p2") == 2
    # 坐骑被移走（夹具移动到弃牌堆）后距离立即恢复
    game._state = game.state.move_card(HUALIU_040, DISCARD_PILE)
    assert effective_distance(game.state, "p1", "p2") == 1
    _assert_conservation(game)


def test_weapon_range_is_separate_from_effective_distance() -> None:
    game = _fresh(seed=3)
    # 武器攻击范围不参与 effective_distance
    qinggang = next(
        r for r in game.formal_registry.records if r.card_key == QINGGANG
    )
    _equip_mount_fixture(game, MOUNT_DEFENSIVE, "p2")
    _swap(game, qinggang.instance_id, ZoneRef.equipment("p1", "weapon"))
    assert weapon_attack_ranges()[QINGGANG] == 2
    assert attack_range_of(game.state, "p1") == 2
    # 防御坐骑仍使有效距离为2；武器只扩大攻击范围
    assert effective_distance(game.state, "p1", "p2") == 2
    assert is_valid_slash_target(game.state, "p1", "p2") is True


# ----------------------------------------------------------------------
# D. 杀与武器范围
# ----------------------------------------------------------------------


def test_slash_legality_with_mounts_and_weapons() -> None:
    # 无坐骑无武器：距离1<=范围1，合法
    game = _fresh(seed=3)
    assert is_valid_slash_target(game.state, "p1", "p2") is True
    # 目标防御坐骑：距离2>范围1，不合法
    game2 = _fresh(seed=5)
    _equip_mount_fixture(game2, MOUNT_DEFENSIVE, "p2")
    assert is_valid_slash_target(game2.state, "p1", "p2") is False
    # 攻击坐骑缩短距离：距离0<=范围1，合法
    game3 = _fresh(seed=7)
    _equip_mount_fixture(game3, MOUNT_OFFENSIVE, "p1")
    assert is_valid_slash_target(game3.state, "p1", "p2") is True
    # 武器（范围2）+防御坐骑：2<=2，合法
    game4 = _fresh(seed=9)
    _equip_mount_fixture(game4, MOUNT_DEFENSIVE, "p2")
    qinggang = next(
        r for r in game4.formal_registry.records if r.card_key == QINGGANG
    )
    _swap(game4, qinggang.instance_id, ZoneRef.equipment("p1", "weapon"))
    assert is_valid_slash_target(game4.state, "p1", "p2") is True
    # 双方坐骑组合：1<=1，合法
    game5 = _fresh(seed=11)
    _equip_mount_fixture(game5, MOUNT_OFFENSIVE, "p1")
    _equip_mount_fixture(game5, MOUNT_DEFENSIVE, "p2")
    assert is_valid_slash_target(game5.state, "p1", "p2") is True


def test_slash_use_enumerate_validate_apply_with_defensive_mount() -> None:
    # 目标防御坐骑时，出牌阶段不能枚举到杀目标；伪造动作失败且不消耗杀
    game = _fresh(seed=3)
    _equip_mount_fixture(game, MOUNT_DEFENSIVE, _other(game))
    _give_exact_hand(game, BLACK_SHA_140, _me(game))
    assert _action(game, "use_slash", card_key=SHA) is None
    forged = LegalAction(
        action_type=ActionType.USE_CARD,
        actor_id=_me(game),
        card_instance_id=BLACK_SHA_140,
        target_ids=(_other(game),),
        payload={
            "operation": "use_slash",
            "card_key": SHA,
            "card_name": "杀",
        },
        action_id="act_slash_forged",
    )
    with pytest.raises(InvalidActionError):
        validate_action(game.state, game._context(), forged, game.registry)
    assert BLACK_SHA_140 in game.state.card_ids_in(ZoneRef.hand(_me(game)))
    assert not _events_of(game, EventType.CARD_USED)
    assert game.runtime.slash_used_counts.get(_me(game), 0) == 0


def test_slash_stale_action_fails_after_mount_change() -> None:
    game = _fresh(seed=3)
    _give_exact_hand(game, BLACK_SHA_140, _me(game))
    action = _action(game, "use_slash", card_key=SHA)
    assert action is not None
    # 装备防御坐骑改变距离后，旧动作必须失败关闭
    _equip_mount_fixture(game, MOUNT_DEFENSIVE, _other(game))
    with pytest.raises(InvalidActionError):
        validate_action(game.state, game._context(), action, game.registry)
    assert BLACK_SHA_140 in game.state.card_ids_in(ZoneRef.hand(_me(game)))


def test_slash_action_payload_has_no_trusted_distance() -> None:
    game = _fresh(seed=3)
    _give_exact_hand(game, BLACK_SHA_140, _me(game))
    action = _action(game, "use_slash", card_key=SHA)
    assert action is not None
    payload = action.payload
    assert "distance" not in payload
    assert "range" not in payload
    assert "mount_modifier" not in payload


def test_attribute_slashes_follow_same_distance_rules() -> None:
    game = _fresh(seed=3)
    _equip_mount_fixture(game, MOUNT_DEFENSIVE, _other(game))
    _give_exact_hand(game, "sgs-mobile-20260725-012", _me(game))  # 火杀
    assert _action(game, "use_slash", card_key="sgs_basic_huosha") is None
    game2 = _fresh(seed=5)
    _give_exact_hand(game2, "sgs-mobile-20260725-056", _me(game2))  # 雷杀
    action = _action(game2, "use_slash", card_key="sgs_basic_leisha")
    assert action is not None
    _step(game2, action)
    assert game2.phase is ProductionPhase.SLASH_RESPONSE


# ----------------------------------------------------------------------
# E. 借刀杀人
# ----------------------------------------------------------------------


def test_jiedao_second_target_uses_first_target_weapon_and_mounts() -> None:
    game = _fresh(seed=3)
    # p2 装备青釭剑（范围2）作为第一目标；p1 装备防御坐骑使 p2->p1 距离为2
    qinggang = next(
        r for r in game.formal_registry.records if r.card_key == QINGGANG
    )
    _swap(game, qinggang.instance_id, ZoneRef.equipment("p2", "weapon"))
    _equip_mount_fixture(game, MOUNT_DEFENSIVE, "p1")
    jiedao = next(r for r in game.formal_registry.records if r.card_key == JIEDAO)
    _give_exact_hand(game, jiedao.instance_id, "p1")
    action = _action(game, "use_jiedao", card_key=JIEDAO)
    # 第二目标 p1：p2 攻击范围2 >= p2->p1 距离2（p1防御坐骑）→ 合法
    assert action is not None
    assert action.payload.get("second_target_id") == "p1"
    # p1 进攻坐骑不影响第二目标（p2->p1 方向）
    _equip_mount_fixture(game, MOUNT_OFFENSIVE, "p1")
    assert effective_distance(game.state, "p2", "p1") == 2
    action2 = _action(game, "use_jiedao", card_key=JIEDAO)
    assert action2 is not None


def test_jiedao_second_target_blocked_by_defensive_mount() -> None:
    game = _fresh(seed=3)
    # p2 装备攻击范围1的武器（诸葛连弩），p1 装备防御坐骑 → p2->p1 距离2 > 1
    crossbow = next(
        r
        for r in game.formal_registry.records
        if r.card_key == "sgs_weapon_zhugeliannu"
    )
    _swap(game, crossbow.instance_id, ZoneRef.equipment("p2", "weapon"))
    _equip_mount_fixture(game, MOUNT_DEFENSIVE, "p1")
    jiedao = next(r for r in game.formal_registry.records if r.card_key == JIEDAO)
    _give_exact_hand(game, jiedao.instance_id, "p1")
    # 双人切片第二目标只能是 p1；距离不合法 → 借刀不可用（无合法目标组合）
    assert _action(game, "use_jiedao", card_key=JIEDAO) is None


def test_jiedao_weapon_gain_path_regression_with_mounts() -> None:
    game = _fresh(seed=3)
    # 第一目标 p2 装备青釭剑，拒绝出杀 → 武器交付给 p1
    qinggang = next(
        r for r in game.formal_registry.records if r.card_key == QINGGANG
    )
    _swap(game, qinggang.instance_id, ZoneRef.equipment("p2", "weapon"))
    _equip_mount_fixture(game, MOUNT_OFFENSIVE, "p1")
    jiedao = next(r for r in game.formal_registry.records if r.card_key == JIEDAO)
    _give_exact_hand(game, jiedao.instance_id, "p1")
    action = _action(game, "use_jiedao", card_key=JIEDAO)
    assert action is not None
    _step(game, action)
    _step(game, _action(game, "pass_trick_response"))
    _step(game, _action(game, "pass_trick_response"))
    assert game.phase is ProductionPhase.BORROWED_SWORD_CHOICE
    refuse = next(
        a
        for a in game.legal_actions()
        if a.payload.get("operation") == "refuse_borrowed_sword_slash"
    )
    _step(game, refuse)
    assert qinggang.instance_id in game.state.card_ids_in(ZoneRef.hand("p1"))
    _assert_conservation(game)


# ----------------------------------------------------------------------
# F. 顺手牵羊与兵粮寸断
# ----------------------------------------------------------------------


def test_shunshou_distance_boundary_with_mounts() -> None:
    # 无坐骑：距离1 合法
    game = _fresh(seed=3)
    assert is_valid_shunshou_target(game.state, "p1", "p2") is True
    # 目标防御坐骑：距离2 不合法
    game2 = _fresh(seed=5)
    _equip_mount_fixture(game2, MOUNT_DEFENSIVE, "p2")
    assert is_valid_shunshou_target(game2.state, "p1", "p2") is False
    # 源进攻坐骑：距离下限为1，相邻角色仍为1 → 合法
    game3 = _fresh(seed=7)
    _equip_mount_fixture(game3, MOUNT_OFFENSIVE, "p1")
    assert effective_distance(game3.state, "p1", "p2") == 1
    assert is_valid_shunshou_target(game3.state, "p1", "p2") is True
    # 双方坐骑：距离1 合法
    game4 = _fresh(seed=9)
    _equip_mount_fixture(game4, MOUNT_OFFENSIVE, "p1")
    _equip_mount_fixture(game4, MOUNT_DEFENSIVE, "p2")
    assert is_valid_shunshou_target(game4.state, "p1", "p2") is True


def test_shunshou_weapon_does_not_expand_distance() -> None:
    game = _fresh(seed=3)
    # 武器攻击范围不参与顺手距离：目标防御坐骑使距离2 → 顺手不合法，
    # 即使 p1 装备青釭剑（范围2）也不得扩大“距离为1”限制
    qinggang = next(
        r for r in game.formal_registry.records if r.card_key == QINGGANG
    )
    _swap(game, qinggang.instance_id, ZoneRef.equipment("p1", "weapon"))
    _equip_mount_fixture(game, MOUNT_DEFENSIVE, "p2")
    shunshou = next(
        r for r in game.formal_registry.records if r.card_key == SHUNSHOU
    )
    _give_exact_hand(game, shunshou.instance_id, "p1")
    assert _action(game, "use_shunshou", card_key=SHUNSHOU) is None


def test_bingliang_distance_boundary_with_mounts() -> None:
    game = _fresh(seed=3)
    _equip_mount_fixture(game, MOUNT_DEFENSIVE, _other(game))
    bingliang = next(
        r for r in game.formal_registry.records if r.card_key == BINGLIANG
    )
    _give_exact_hand(game, bingliang.instance_id, _me(game))
    # 防御坐骑使距离2 → 兵粮不可用
    assert _action(game, "use_bingliang", card_key=BINGLIANG) is None
    game2 = _fresh(seed=7)
    _equip_mount_fixture(game2, MOUNT_OFFENSIVE, _me(game2))
    bingliang2 = next(
        r for r in game2.formal_registry.records if r.card_key == BINGLIANG
    )
    _give_exact_hand(game2, bingliang2.instance_id, _me(game2))
    # 进攻坐骑不改变相邻角色距离（下限1）→ 兵粮仍合法
    assert effective_distance(game2.state, _me(game2), _other(game2)) == 1
    action2 = _action(game2, "use_bingliang", card_key=BINGLIANG)
    assert action2 is not None and action2.target_ids == (_other(game2),)
    game3 = _fresh(seed=9)
    _equip_mount_fixture(game3, MOUNT_OFFENSIVE, _me(game3))
    _equip_mount_fixture(game3, MOUNT_DEFENSIVE, _other(game3))
    bingliang3 = next(
        r for r in game3.formal_registry.records if r.card_key == BINGLIANG
    )
    _give_exact_hand(game3, bingliang3.instance_id, _me(game3))
    # 双方坐骑：距离1 合法，判定区生命周期正常
    action = _action(game3, "use_bingliang", card_key=BINGLIANG)
    assert action is not None
    _step(game3, action)
    assert game3.phase is ProductionPhase.PLAY
    assert bingliang3.instance_id in game3.state.card_ids_in(
        ZoneRef.judgment(_other(game3))
    )
    _assert_conservation(game3)


# ----------------------------------------------------------------------
# G. 回放与隐私
# ----------------------------------------------------------------------


def _mount_replay_fixture(game: ProductionBasicCardBatch) -> None:
    """确定性夹具：p1 手牌持进攻坐骑与杀、p2 装备防御坐骑。"""
    _equip_mount_fixture(game, MOUNT_DEFENSIVE, _other(game))
    for instance_id in list(
        game.state.card_ids_in(ZoneRef.hand(_me(game)))
    ):
        if game.state.cards_by_id[instance_id].card_key in SLASH_CARD_KEYS:
            game._state = game.state.move_card(instance_id, DISCARD_PILE)
    _swap(game, BLACK_SHA_140, ZoneRef.hand(_me(game)))
    _swap(game, ZIXUAN_039, ZoneRef.hand(_me(game)))


@pytest.fixture(scope="module")
def mount_replay_record() -> ProductionReexecutionReplay:
    controller = ScriptedBatchController(
        [
            {"operation": "use_mount"},
            {"operation": "use_slash"},
            {"operation": "pass_slash_response"},
            {"operation": "end_play_phase"},
            {"operation": "end_turn"},
        ]
    )
    return record_reference_production_batch(
        seed=3,
        controller=controller,
        fixture=_mount_replay_fixture,
        max_steps=500,
    )


def test_mount_strict_replay_reexecutes_slash_path(
    mount_replay_record: ProductionReexecutionReplay,
) -> None:
    record = mount_replay_record
    assert any(
        event.get("event_type") == "damage"
        for event in record.events
    )
    result = reexecute_production_replay(
        record, fixture=_mount_replay_fixture
    )
    assert result.verified is True


def test_mount_replay_tamper_fails_closed(
    mount_replay_record: ProductionReexecutionReplay,
) -> None:
    record = mount_replay_record
    tampered = copy.deepcopy(record.to_dict())
    # 篡改装备状态：把防御坐骑从装备区移入弃牌堆对应事件删除后重执行
    tampered["events"] = [
        event
        for event in tampered["events"]
        if not (
            event.get("event_type") == "card_moved"
            and event.get("payload", {}).get("destination", {}).get("kind")
            == "equipment"
        )
    ]
    tampered["record_sha256"] = ""
    with pytest.raises(
        (ProductionReplayFormatError, ProductionReplayDivergenceError)
    ):
        reexecute_production_replay(
            ProductionReexecutionReplay.from_dict(tampered),
            fixture=_mount_replay_fixture,
        )


def test_player_visible_mount_equipment_public(
    mount_replay_record: ProductionReexecutionReplay,
) -> None:
    record = mount_replay_record
    view = record.player_visible_payload()
    assert "authoritative_private" not in view
    # 正式装备路径的公开装备事件保留真实实体
    equipped = [
        event
        for event in view["events"]
        if event.get("event_type") == "equipment_equipped"
    ]
    assert any(
        event["card_instance_id"] == ZIXUAN_039
        and event["payload"]["slot"] == "attack_horse"
        for event in equipped
    )
    # 公开杀路径：damage 事件携带根实体
    assert any(
        event.get("event_type") == "damage"
        and event.get("card_instance_id") == BLACK_SHA_140
        for event in view["events"]
    )
    # 初始发牌仍脱敏
    for event in view["events"]:
        if (
            event.get("event_type") == "card_gained"
            and event.get("payload", {}).get("reason") == "initial_hand"
        ):
            assert event.get("card_instance_id") is None


# ----------------------------------------------------------------------
# H. 旧批次回归（轻量组合）
# ----------------------------------------------------------------------


def test_armor_and_white_lion_regression_with_mounts() -> None:
    # 坐骑离区不得触发白银狮子恢复；防具离区仍恢复
    game = _fresh(seed=3)
    _equip_mount_fixture(game, MOUNT_OFFENSIVE, _me(game))
    _swap(game, "sgs-mobile-20260725-043", ZoneRef.equipment(_me(game), "armor"))
    _set_hp(game, _me(game), 3)
    # 坐骑被过河弃置（夹具）：不得产生 ARMOR_RECOVERED
    game._state = game.state.move_card(ZIXUAN_039, DISCARD_PILE)
    assert not _events_of(game, EventType.ARMOR_RECOVERED)
    assert game.state.players_by_id[_me(game)].hp == 3
    # 防具离区（替换）：仍恢复
    other_armor = next(
        r
        for r in game.formal_registry.records
        if r.card_key == "sgs_armor_renwangdun"
    )
    _give_exact_hand(game, other_armor.instance_id, _me(game))
    _step(game, _action(game, "use_armor", card_key="sgs_armor_renwangdun"))
    recovered = _events_of(game, EventType.ARMOR_RECOVERED)
    assert len(recovered) == 1
    assert game.state.players_by_id[_me(game)].hp == 4
    _assert_conservation(game)


def test_delayed_trick_judgment_regression_with_mounts() -> None:
    # 兵粮+坐骑组合下判定区与阶段流不退化
    game = _fresh(seed=9)
    _equip_mount_fixture(game, MOUNT_OFFENSIVE, _me(game))
    _equip_mount_fixture(game, MOUNT_DEFENSIVE, _other(game))
    bingliang = next(
        r for r in game.formal_registry.records if r.card_key == BINGLIANG
    )
    _give_exact_hand(game, bingliang.instance_id, _me(game))
    action = _action(game, "use_bingliang", card_key=BINGLIANG)
    assert action is not None
    _step(game, action)
    assert game.runtime.judgment_entry_counter == 1
    assert game.runtime.judgment_entry_indices[bingliang.instance_id] == 1


def test_finished_game_stops_mount_actions() -> None:
    game = _fresh(seed=5)
    result = game.run()
    assert game.is_finished
    assert game.winner_id == result.winner_id
    with pytest.raises(ProductionBatchFinishedError):
        game.legal_actions()


# ----------------------------------------------------------------------
# I. 距离下限阻塞性复核边界测试（CP-04N 提交前）
# ----------------------------------------------------------------------


def _three_player_state_with_mounts(
    *,
    offensive_on_source: bool = False,
    defensive_on_far_target: bool = False,
) -> GameState:
    """结构级（B）：五人GameState，基础距离 p1-p3=2；坐骑可选装备。"""
    registry = FormalCardRegistry.from_formal_csv()
    mounts = [
        r
        for r in registry.records
        if r.card_key in PRODUCTION_MOUNT_KEYS
    ]
    cards = tuple(
        CardInstance.from_deck_record(record) for record in mounts[:2]
    )
    players = (
        PlayerState(player_id="p1", seat=1, hp=4, max_hp=4),
        PlayerState(player_id="p2", seat=2, hp=4, max_hp=4),
        PlayerState(player_id="p3", seat=3, hp=4, max_hp=4),
        PlayerState(player_id="p4", seat=4, hp=4, max_hp=4),
        PlayerState(player_id="p5", seat=5, hp=4, max_hp=4),
    )
    locations: dict[str, ZoneRef] = {
        card.instance_id: DRAW_PILE for card in cards
    }
    if offensive_on_source:
        locations[mounts[0].instance_id] = ZoneRef.equipment(
            "p1", "attack_horse"
        )
    if defensive_on_far_target:
        locations[mounts[1].instance_id] = ZoneRef.equipment(
            "p3", "defense_horse"
        )
    return GameState(cards=cards, players=players, card_locations=locations)


def test_floor_A_base_distance_one_no_mounts() -> None:
    """A：两个不同角色基础距离=1、无坐骑：有效距离=1。"""
    game = _fresh(seed=3)
    assert base_seat_distance(game.state, "p1", "p2") == 1
    assert effective_distance(game.state, "p1", "p2") == 1
    # 生产路径：杀、顺手、兵粮在距离1时全部可枚举
    _give_exact_hand(game, BLACK_SHA_140, _me(game))
    assert _action(game, "use_slash", card_key=SHA) is not None
    shunshou = next(
        r for r in game.formal_registry.records if r.card_key == SHUNSHOU
    )
    _give_exact_hand(game, shunshou.instance_id, _me(game))
    assert _action(game, "use_shunshou", card_key=SHUNSHOU) is not None


def test_floor_B_offensive_mount_keeps_distance_one() -> None:
    """B：源-1坐骑、目标无+1：相邻角色有效距离仍为1（下限1）。"""
    game = _fresh(seed=3)
    _equip_mount_fixture(game, MOUNT_OFFENSIVE, "p1")
    assert effective_distance(game.state, "p1", "p2") == 1
    # 杀合法（1 <= 攻击范围1）
    _give_exact_hand(game, BLACK_SHA_140, _me(game))
    action = _action(game, "use_slash", card_key=SHA)
    assert action is not None and action.target_ids == (_other(game),)
    # 关键回归：装备-1坐骑绝不能导致相邻角色的顺手/兵粮目标消失
    shunshou = next(
        r for r in game.formal_registry.records if r.card_key == SHUNSHOU
    )
    _give_exact_hand(game, shunshou.instance_id, _me(game))
    shunshou_action = _action(game, "use_shunshou", card_key=SHUNSHOU)
    assert shunshou_action is not None
    assert shunshou_action.target_ids == (_other(game),)
    bingliang = next(
        r for r in game.formal_registry.records if r.card_key == BINGLIANG
    )
    _give_exact_hand(game, bingliang.instance_id, _me(game))
    bingliang_action = _action(game, "use_bingliang", card_key=BINGLIANG)
    assert bingliang_action is not None
    assert bingliang_action.target_ids == (_other(game),)


def test_floor_C_both_mounts_cancel_to_one() -> None:
    """C：源-1坐骑＋目标+1坐骑：抵消后有效距离=1，全部距离牌合法。"""
    game = _fresh(seed=3)
    _equip_mount_fixture(game, MOUNT_OFFENSIVE, "p1")
    _equip_mount_fixture(game, MOUNT_DEFENSIVE, "p2")
    assert effective_distance(game.state, "p1", "p2") == 1
    _give_exact_hand(game, BLACK_SHA_140, _me(game))
    assert _action(game, "use_slash", card_key=SHA) is not None
    shunshou = next(
        r for r in game.formal_registry.records if r.card_key == SHUNSHOU
    )
    _give_exact_hand(game, shunshou.instance_id, _me(game))
    assert _action(game, "use_shunshou", card_key=SHUNSHOU) is not None
    bingliang = next(
        r for r in game.formal_registry.records if r.card_key == BINGLIANG
    )
    _give_exact_hand(game, bingliang.instance_id, _me(game))
    assert _action(game, "use_bingliang", card_key=BINGLIANG) is not None


def test_floor_D_base_distance_two_reduced_to_one() -> None:
    """D（结构级B）：基础距离=2，源-1坐骑 → 有效距离1。"""
    state = _three_player_state_with_mounts()
    assert base_seat_distance(state, "p1", "p3") == 2
    assert effective_distance(state, "p1", "p3") == 2
    state = _three_player_state_with_mounts(offensive_on_source=True)
    assert effective_distance(state, "p1", "p3") == 1
    # 反向：p3->p1 不受 p1 进攻坐骑影响
    assert effective_distance(state, "p3", "p1") == 2
    # 目标+1坐骑：2-1+1=2
    state = _three_player_state_with_mounts(
        offensive_on_source=True, defensive_on_far_target=True
    )
    assert effective_distance(state, "p1", "p3") == 2
    # 距离1 <= 默认攻击范围1 → 杀合法；距离2 不合法
    assert is_valid_slash_target(state, "p1", "p3") is False
    no_mount = _three_player_state_with_mounts()
    assert is_valid_slash_target(no_mount, "p1", "p3") is False
    reduced = _three_player_state_with_mounts(offensive_on_source=True)
    assert is_valid_slash_target(reduced, "p1", "p3") is True


def test_floor_D_distance_two_cards_enter_range() -> None:
    """D（结构级B）：基础距离2＋源-1坐骑→距离1，杀/顺手/兵粮进入合法范围。"""
    no_mount = _three_player_state_with_mounts()
    assert actual_distance(no_mount, "p1", "p3") == 2
    assert is_valid_slash_target(no_mount, "p1", "p3") is False
    assert is_valid_shunshou_target(no_mount, "p1", "p3") is False
    reduced = _three_player_state_with_mounts(offensive_on_source=True)
    assert effective_distance(reduced, "p1", "p3") == 1
    assert actual_distance(reduced, "p1", "p3") == 1
    assert is_valid_slash_target(reduced, "p1", "p3") is True
    assert is_valid_shunshou_target(reduced, "p1", "p3") is True
    # 兵粮“距离为1”使用同一有效距离（1满足条件）
    assert actual_distance(reduced, "p1", "p3") == 1


def test_floor_E_self_distance_zero_never_valid_target() -> None:
    """E：自己到自己的距离为0，但不得因此允许以自己为目标。"""
    game = _fresh(seed=3)
    _equip_mount_fixture(game, MOUNT_OFFENSIVE, _me(game))
    assert effective_distance(game.state, _me(game), _me(game)) == 0
    _give_exact_hand(game, BLACK_SHA_140, _me(game))
    assert _action(game, "use_slash", card_key=SHA, target=_me(game)) is None
    shunshou = next(
        r for r in game.formal_registry.records if r.card_key == SHUNSHOU
    )
    _give_exact_hand(game, shunshou.instance_id, _me(game))
    assert _action(game, "use_shunshou", card_key=SHUNSHOU, target=_me(game)) is None
    bingliang = next(
        r for r in game.formal_registry.records if r.card_key == BINGLIANG
    )
    _give_exact_hand(game, bingliang.instance_id, _me(game))
    assert _action(game, "use_bingliang", card_key=BINGLIANG, target=_me(game)) is None
    # 伪造自己为目标的动作必须失败关闭且不消耗牌
    forged = LegalAction(
        action_type=ActionType.USE_CARD,
        actor_id=_me(game),
        card_instance_id=BLACK_SHA_140,
        target_ids=(_me(game),),
        payload={
            "operation": "use_slash",
            "card_key": SHA,
            "card_name": "杀",
        },
        action_id="act_self_slash_forged",
    )
    with pytest.raises(InvalidActionError):
        validate_action(game.state, game._context(), forged, game.registry)
    assert BLACK_SHA_140 in game.state.card_ids_in(ZoneRef.hand(_me(game)))


def test_floor_F_jiedao_second_target_zero_distance_boundary() -> None:
    """F：借刀第二目标在距离下限边界：第一目标进攻坐骑保持距离1。"""
    game = _fresh(seed=3)
    # p2（第一目标）装备青釭剑（范围2）与进攻坐骑；p1（第二目标）无防御坐骑
    qinggang = next(
        r for r in game.formal_registry.records if r.card_key == QINGGANG
    )
    _swap(game, qinggang.instance_id, ZoneRef.equipment("p2", "weapon"))
    _equip_mount_fixture(game, MOUNT_OFFENSIVE, "p2")
    assert effective_distance(game.state, "p2", "p1") == 1
    jiedao = next(r for r in game.formal_registry.records if r.card_key == JIEDAO)
    _give_exact_hand(game, jiedao.instance_id, "p1")
    action = _action(game, "use_jiedao", card_key=JIEDAO)
    assert action is not None
    assert action.payload.get("second_target_id") == "p1"
    # 防御坐骑把距离抬回1后仍合法（范围2）
    _equip_mount_fixture(game, MOUNT_DEFENSIVE, "p1")
    assert effective_distance(game.state, "p2", "p1") == 1
    action2 = _action(game, "use_jiedao", card_key=JIEDAO)
    assert action2 is not None


def test_floor_G_shunshou_adjacent_with_offensive_mount_full_path() -> None:
    """G（防回归）：相邻角色有牌、使用者装备-1坐骑，顺手必须仍可
    enumerate→validate→apply 并获得目标区域牌，防止距离0错误再次进入。"""
    game = _fresh(seed=3)
    _equip_mount_fixture(game, MOUNT_OFFENSIVE, _me(game))
    assert effective_distance(game.state, _me(game), _other(game)) == 1
    shunshou = next(
        r for r in game.formal_registry.records if r.card_key == SHUNSHOU
    )
    _give_exact_hand(game, shunshou.instance_id, _me(game))
    action = _action(game, "use_shunshou", card_key=SHUNSHOU)
    assert action is not None and action.target_ids == (_other(game),)
    validate_action(game.state, game._context(), action, game.registry)
    _step(game, action)
    _step(game, _action(game, "pass_trick_response"))
    _step(game, _action(game, "pass_trick_response"))
    assert game.phase is ProductionPhase.ZONE_CHOICE
    hand_choice = next(
        a
        for a in game.legal_actions()
        if a.payload.get("operation") == "choose_target_zone_card"
        and a.payload.get("zone") == "hand"
    )
    handles = game.runtime.zone_choice_handles
    chosen_id = handles[hand_choice.payload["handle"]]
    _step(game, hand_choice)
    assert chosen_id in game.state.card_ids_in(ZoneRef.hand(_me(game)))
    assert shunshou.instance_id in game.state.card_ids_in(DISCARD_PILE)
    _assert_conservation(game)


# ----------------------------------------------------------------------
# G-001 修复：死亡角色从距离环跳过（WHOLE_REPO_AUDIT_REMEDIATION_1）
# ----------------------------------------------------------------------


def _structured_multi_state(
    alive_seats: list[int], *, hp: int = 4
) -> GameState:
    """构造 N 人结构化 GameState（死亡角色 alive=False），用于距离环测试。

    仅构造状态与调用公开 distance API，不声称 multi_player_production_proven。"""

    players = tuple(
        PlayerState(
            f"p{s}",
            s,
            0 if s not in alive_seats else hp,
            hp,
            alive=(s in alive_seats),
        )
        for s in range(1, max(alive_seats) + 1)
    )
    ids = [f"p{s}" for s in range(1, max(alive_seats) + 1)]
    game = _fresh(seed=3)
    cards = tuple(
        CardInstance.from_deck_record(r)
        for r in game.formal_registry.records
    )
    locations = {card.instance_id: DRAW_PILE for card in cards}
    zone_order = {
        **{ZoneRef.hand(pid): () for pid in ids},
        DRAW_PILE: tuple(card.instance_id for card in cards),
        DISCARD_PILE: (),
        PROCESSING_ZONE: (),
        REVEALED_ZONE: (),
    }
    return GameState(
        cards=cards,
        players=players,
        card_locations=locations,
        zone_order=zone_order,
        deck_id=cards[0].deck_id,
    )


def test_dead_seat_distance_five_player_ring() -> None:
    """5人全存活：1与5相邻（距离1），1与3距离2。"""
    state = _structured_multi_state([1, 2, 3, 4, 5])
    assert base_seat_distance(state, "p1", "p1") == 0
    assert base_seat_distance(state, "p1", "p2") == 1
    assert base_seat_distance(state, "p1", "p3") == 2
    assert base_seat_distance(state, "p1", "p5") == 1
    assert base_seat_distance(state, "p2", "p5") == 2


def test_dead_seat_distance_middle_death_contracts_ring() -> None:
    """5人环中 p3 死亡：p2 与 p4 变为相邻（距离1），p1 与 p5 仍相邻。"""
    state = _structured_multi_state([1, 2, 4, 5])
    assert base_seat_distance(state, "p1", "p2") == 1
    assert base_seat_distance(state, "p2", "p4") == 1
    assert base_seat_distance(state, "p1", "p5") == 1
    assert base_seat_distance(state, "p1", "p4") == 2


def test_dead_seat_distance_multiple_deaths() -> None:
    """多个死亡：p2、p4 死亡后环为 [1,3,5]，p5 与 p1 相邻（距离1）。"""
    state = _structured_multi_state([1, 3, 5])
    assert base_seat_distance(state, "p1", "p3") == 1
    assert base_seat_distance(state, "p3", "p5") == 1
    assert base_seat_distance(state, "p5", "p1") == 1


def test_dead_seat_distance_floor_for_distinct_alive() -> None:
    """不同存活角色基础距离最低为1：相邻死亡后环收缩为两个存活角色仍为1。"""
    state = _structured_multi_state([1, 3])
    assert base_seat_distance(state, "p1", "p3") == 1
    state4 = _structured_multi_state([1, 2, 4])
    assert base_seat_distance(state4, "p2", "p4") == 1
    assert base_seat_distance(state4, "p4", "p1") == 1


def test_dead_seat_distance_dead_participant_fails_closed() -> None:
    """source 或 target 为死亡角色：base_seat_distance 失败关闭。"""
    state = _structured_multi_state([1, 2, 4])
    with pytest.raises(UnsupportedRuleError):
        base_seat_distance(state, "p3", "p1")
    with pytest.raises(UnsupportedRuleError):
        base_seat_distance(state, "p1", "p3")
    with pytest.raises(UnsupportedRuleError):
        effective_distance(state, "p1", "p3")


def test_dead_target_slash_illegal() -> None:
    """is_valid_slash_target 必须拒绝死亡目标（G-001）。"""
    state = _structured_multi_state([1, 2, 4])
    assert is_valid_slash_target(state, "p1", "p2") is True
    assert is_valid_slash_target(state, "p1", "p3") is False
    assert is_valid_slash_target(state, "p1", "p1") is False
    assert is_valid_slash_target(state, "p1", "p9") is False


def test_dead_seat_distance_mount_modifiers() -> None:
    """死亡环收缩后的基础距离仍正确叠加坐骑方向性修正与下限。"""
    game = _fresh(seed=3)
    state = _structured_multi_state([1, 2, 4])
    # 环 [1,2,4]：p1→p4 基础1（相邻）；p1→p2 基础1；p2→p4 基础1
    assert base_seat_distance(state, "p1", "p4") == 1
    assert base_seat_distance(state, "p2", "p4") == 1
    # 给 p4 装防御坐骑（+1）：p1→p4 = 1+1 = 2；p2→p4 = 1+1 = 2
    defensive = next(
        r for r in game.formal_registry.records if r.card_key == "sgs_mount_defensive"
    )
    state = state.move_card(
        defensive.instance_id, ZoneRef.equipment("p4", "defense_horse")
    )
    assert effective_distance(state, "p1", "p4") == 2
    assert effective_distance(state, "p2", "p4") == 2
    # 给 p2 装进攻坐骑（-1）：p2→p4 = 1-1+1 = 1（相邻不能修正为0）
    offensive = next(
        r for r in game.formal_registry.records if r.card_key == "sgs_mount_offensive"
    )
    state2 = state.move_card(
        offensive.instance_id, ZoneRef.equipment("p2", "attack_horse")
    )
    assert effective_distance(state2, "p2", "p4") == 1


def test_dead_self_distance_fails_closed() -> None:
    """G-001 R2 dead-self 边界：死亡角色对自身必须失败关闭，不得返回0。"""
    state = _structured_multi_state([1, 2, 4])
    with pytest.raises(UnsupportedRuleError):
        base_seat_distance(state, "p3", "p3")
    with pytest.raises(UnsupportedRuleError):
        effective_distance(state, "p3", "p3")
    with pytest.raises(UnsupportedRuleError):
        actual_distance(state, "p3", "p3")
    with pytest.raises(UnsupportedRuleError):
        is_target_within_distance(state, "p3", "p3", 5)
    # alive self → 0 保持
    assert base_seat_distance(state, "p1", "p1") == 0
    assert effective_distance(state, "p1", "p1") == 0
    assert actual_distance(state, "p1", "p1") == 0
    assert is_target_within_distance(state, "p1", "p1", 0) is True
    # 既有 dead→alive / alive→dead 继续失败关闭
    with pytest.raises(UnsupportedRuleError):
        base_seat_distance(state, "p3", "p1")
    with pytest.raises(UnsupportedRuleError):
        base_seat_distance(state, "p1", "p3")
