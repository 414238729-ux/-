# -*- coding: utf-8 -*-
"""【借刀杀人】＋11种武器牌本体生产垂直切片测试（CP-04K）。

覆盖武器牌本体（主动装备、同槽替换、攻击范围动态计算、公开装备区、
严格回放）、【借刀杀人】两次目标检测、无懈边界、强制使用【杀】与按角色
出杀计数、拒绝后武器进入使用者手牌、挂起与终局清理、11种武器专属技能的
集中式失败关闭门禁、隐藏句柄与严格回放篡改检测。

所有正式正向测试都经过 enumerate -> validate -> apply 真实路径；不使用
mock／monkeypatch／skip／xfail／轻量结算器，不临时修改 current_actor，
不临时清零出杀计数。双人切片内不可达的边界（如使用者死亡但游戏未结束、
第二目标超出攻击范围）明确标为结构级，不宣称双人端到端 PROVEN。
"""
from __future__ import annotations

import copy
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType

import pytest

from scripts.sgs_engine.actions import (
    ActionType,
    InvalidActionError,
    LegalAction,
    UnsupportedRuleError,
)
from scripts.sgs_engine.events import EventType
from scripts.sgs_engine.model import (
    DISCARD_PILE,
    PROCESSING_ZONE,
    ZoneKind,
    ZoneRef,
)
from scripts.sgs_engine.production_batch import (
    BatchActionIdController,
    BatchReferenceController,
    ProductionBasicCardBatch,
    ProductionBatchError,
    ProductionPhase,
    ScriptedBatchController,
    _replace_player,
)
from scripts.sgs_engine.production_cards import (
    PRODUCTION_ARMOR_KEYS,
    PRODUCTION_BASIC_CARD_KEYS,
    PRODUCTION_DELAYED_TRICK_KEYS,
    PRODUCTION_MOUNT_KEYS,
    PRODUCTION_TRICK_KEYS,
    PRODUCTION_WEAPON_KEYS,
    SLASH_CARD_KEYS,
    WEAPON_SKILL_STATUS,
    WeaponCardAdapter,
    attack_range_of,
    check_weapon_skill_gate,
    weapon_attack_ranges,
)
from scripts.sgs_engine.production_replay import (
    ProductionReplayDivergenceError,
    ProductionReplayFormatError,
    ProductionReexecutionReplay,
    record_reference_production_batch,
    reexecute_production_replay,
)

JIEDAO = "sgs_trick_jiedaosharen"
WUXIE = "sgs_trick_wuxiekeji"
SHA = "sgs_basic_sha"
HUOSHA = "sgs_basic_huosha"
LEISHA = "sgs_basic_leisha"
SHAN = "sgs_basic_shan"
TAO = "sgs_basic_tao"
WEAPON_QINGGANG = "sgs_weapon_qinggangjian"

REPO_ROOT = Path(__file__).resolve().parent.parent

_BS_CHOICE_PAYLOAD_KEYS = {
    "operation",
    "trick_instance_id",
    "root_trick_instance_id",
    "user_id",
    "first_target_id",
    "second_target_id",
    "window_id",
    "state_hash",
    "handle",
}


# ---------------------------------------------------------------------
# 夹具与路径助手（全部使用不可变GameState与正式牌区移动接口）
# ---------------------------------------------------------------------


def _swap(game: ProductionBasicCardBatch, instance_id: str, dest: ZoneRef) -> None:
    """把实体牌移动到目标区域并保持160张牌守恒的确定性夹具。"""
    src = game.state.location_of(instance_id)
    if src == dest:
        return
    moves: dict[str, ZoneRef] = {}
    if dest.kind is ZoneKind.HAND and dest.owner_id is not None:
        hand_ids = list(game.state.card_ids_in(ZoneRef.hand(dest.owner_id)))
        if hand_ids:
            moves[hand_ids[0]] = src
    moves[instance_id] = dest
    game._state = game.state.move_cards(moves)


def _set_hp(game: ProductionBasicCardBatch, player_id: str, hp: int) -> None:
    game._state = _replace_player(game.state, player_id, hp=hp)


def _set_chained(game: ProductionBasicCardBatch, player_id: str, chained: bool) -> None:
    game._state = _replace_player(game.state, player_id, chained=chained)


def _action(
    game: ProductionBasicCardBatch, operation: str, **kw: object
) -> object | None:
    for action in game.legal_actions():
        if action.payload.get("operation") != operation:
            continue
        if kw.get("card_key") is not None and action.payload.get("card_key") != kw[
            "card_key"
        ]:
            continue
        if kw.get("target") is not None and action.target_ids[0] != kw["target"]:
            continue
        return action
    return None


def _step(game: ProductionBasicCardBatch, action: object) -> None:
    assert action is not None and getattr(action, "action_id", None), action
    game.step(BatchActionIdController(action.action_id))  # type: ignore[attr-defined]


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

def _events_of(game: ProductionBasicCardBatch, event_type: EventType) -> list:
    return [event for event in game.events if event.event_type is event_type]


def _jiedao_fixture(
    game: ProductionBasicCardBatch,
    *,
    weapon_key: str = WEAPON_QINGGANG,
    slash_keys: tuple[str, ...] = (SHA,),
    give_p2_wuxie: bool = False,
    give_p1_wuxie: bool = False,
) -> tuple[str, str, list[str]]:
    """p1持【借刀杀人】，p2装备武器并持有指定实体杀；返回(借刀ID, 武器ID, 杀ID列表)。"""
    registry = game.formal_registry
    jiedao = next(r for r in registry.records if r.card_key == JIEDAO)
    weapon = next(r for r in registry.records if r.card_key == weapon_key)
    _swap(game, jiedao.instance_id, ZoneRef.hand("p1"))
    _swap(game, weapon.instance_id, ZoneRef.equipment("p2", "weapon"))
    # 先移除p2手牌中的既有实体杀，保证选择窗口候选集合完全由slash_keys决定
    for instance_id in list(game.state.card_ids_in(ZoneRef.hand("p2"))):
        if game.state.cards_by_id[instance_id].card_key in SLASH_CARD_KEYS:
            game._state = game.state.move_card(instance_id, DISCARD_PILE)
    slash_ids: list[str] = []
    for key in slash_keys:
        record = next(r for r in registry.records if r.card_key == key)
        _swap(game, record.instance_id, ZoneRef.hand("p2"))
        slash_ids.append(record.instance_id)
    if give_p2_wuxie:
        wuxie = next(r for r in registry.records if r.card_key == WUXIE)
        _swap(game, wuxie.instance_id, ZoneRef.hand("p2"))
    if give_p1_wuxie:
        wuxie = next(r for r in registry.records if r.card_key == WUXIE)
        _swap(game, wuxie.instance_id, ZoneRef.hand("p1"))
    return jiedao.instance_id, weapon.instance_id, slash_ids


def _use_jiedao(game: ProductionBasicCardBatch) -> str:
    """使用【借刀杀人】并关闭无懈链，返回借刀实体ID。"""
    action = _action(game, "use_jiedao", card_key=JIEDAO)
    assert action is not None, "出牌阶段必须能枚举借刀使用动作"
    assert action.target_ids == ("p2",)
    assert action.payload.get("second_target_id") == "p1"
    jiedao_id = action.card_instance_id
    assert jiedao_id is not None
    _step(game, action)
    assert game.phase is ProductionPhase.TRICK_RESPONSE
    _step(game, _action(game, "pass_trick_response"))
    _step(game, _action(game, "pass_trick_response"))
    return jiedao_id


def _choice_handle_for(
    game: ProductionBasicCardBatch, instance_id: str
) -> str:
    handles = game.runtime.borrowed_sword_slash_handles
    for handle, mapped in handles.items():
        if mapped == instance_id:
            return handle
    raise AssertionError(f"借刀选择窗口缺少实体{instance_id}的句柄")


def _choose_borrowed_slash(game: ProductionBasicCardBatch, instance_id: str) -> None:
    assert game.phase is ProductionPhase.BORROWED_SWORD_CHOICE
    handle = _choice_handle_for(game, instance_id)
    action = next(
        a
        for a in game.legal_actions()
        if a.payload.get("operation") == "choose_borrowed_sword_slash"
        and a.payload.get("handle") == handle
    )
    _step(game, action)


def _refuse_borrowed_slash(game: ProductionBasicCardBatch) -> None:
    assert game.phase is ProductionPhase.BORROWED_SWORD_CHOICE
    _step(game, _action(game, "refuse_borrowed_sword_slash"))


def _close_trick_window(game: ProductionBasicCardBatch) -> None:
    _step(game, _action(game, "pass_trick_response"))
    _step(game, _action(game, "pass_trick_response"))


def _hand_keys(game: ProductionBasicCardBatch, player_id: str) -> tuple[str, ...]:
    return tuple(
        game.state.cards_by_id[instance_id].card_key
        for instance_id in game.state.card_ids_in(ZoneRef.hand(player_id))
    )


# ---------------------------------------------------------------------
# 0. 注册表与正式牌堆计数
# ---------------------------------------------------------------------


def test_weapon_entities_all_registered_and_attack_ranges_from_csv() -> None:
    game = _fresh(seed=3)
    registry = game.formal_registry
    assert len(PRODUCTION_WEAPON_KEYS) == 11
    records = [
        record
        for record in registry.records
        if record.card_key in PRODUCTION_WEAPON_KEYS
    ]
    assert len(records) == 12
    assert len({record.instance_id for record in records}) == 12
    expected_ranges = {
        "sgs_weapon_zhugeliannu": 1,
        "sgs_weapon_qinggangjian": 2,
        "sgs_weapon_hanbingjian": 2,
        "sgs_weapon_cixiongshuanggujian": 2,
        "sgs_weapon_gudingdao": 2,
        "sgs_weapon_qinglongyanyuedao": 3,
        "sgs_weapon_guanshifu": 3,
        "sgs_weapon_zhangbashemao": 3,
        "sgs_weapon_fangtianhuaji": 4,
        "sgs_weapon_zhuqueyushan": 4,
        "sgs_weapon_qilingong": 5,
    }
    assert dict(weapon_attack_ranges()) == expected_ranges
    for key in PRODUCTION_WEAPON_KEYS:
        adapter = registry.adapter_for(key)
        assert isinstance(adapter, WeaponCardAdapter)
        spec = adapter.rule_spec()
        assert spec["attack_range"] == expected_ranges[key]
        assert spec["equipment_slot"] == "weapon"
        assert spec["skill_status"] == WEAPON_SKILL_STATUS[key].lower()


def test_implemented_and_remaining_card_counts_updated() -> None:
    game = _fresh(seed=3)
    registry = game.formal_registry
    assert JIEDAO in registry.implemented_card_keys
    assert len(registry.implemented_card_keys) == 38
    assert len(registry.unimplemented_card_keys) == 0
    # 完整实现口径：38种／160张（CP-04P：11种武器全部COMPLETE——
    # 丈八蛇矛已按 USER_CONFIRMED_RULE（2026-08-09）完成材料
    # HAND→PROCESSING→DISCARD 生命周期；方天画戟多人多目标语义已由
    # POST-B C2 实现（Knowledge 7.9 用户整理解释），不再保持 PARTIAL）
    complete_keys = (
        set(PRODUCTION_BASIC_CARD_KEYS)
        | set(PRODUCTION_TRICK_KEYS)
        | set(PRODUCTION_DELAYED_TRICK_KEYS)
        | set(PRODUCTION_ARMOR_KEYS)
        | set(PRODUCTION_MOUNT_KEYS)
        | {
            key
            for key, status in WEAPON_SKILL_STATUS.items()
            if status == "COMPLETE"
        }
    )
    assert len(complete_keys) == 38
    assert sum(len(registry.instances_of(key)) for key in complete_keys) == 160
    # 注册表口径：38种适配器／160张实体
    assert sum(len(registry.instances_of(key)) for key in registry.implemented_card_keys) == 160
    assert set(registry.unimplemented_card_keys) == set()
    assert not any(key.startswith("sgs_trick_") for key in registry.unimplemented_card_keys)
    assert not any(key.startswith("sgs_delayed_") for key in registry.unimplemented_card_keys)
    assert not any(key.startswith("sgs_armor_") for key in registry.unimplemented_card_keys)


def test_formal_deck_remains_160_with_unique_ids() -> None:
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


def test_other_unimplemented_cards_stay_fail_closed() -> None:
    game = _fresh(seed=3)
    registry = game.formal_registry
    assert not registry.unimplemented_card_keys
    registry.assert_no_unimplemented_fallback()



# ---------------------------------------------------------------------
# A. 武器牌本体
# ---------------------------------------------------------------------


def test_all_12_weapon_entities_equipped_from_hand_via_formal_path() -> None:
    # N2：不按11个card_key各取第一张，而是从正式注册表枚举全部12张武器实体，
    # 每张实体分别走 enumerate -> validate -> apply 真实装备路径。
    game = _fresh(seed=3)
    registry = game.formal_registry
    weapon_records = [
        record
        for record in registry.records
        if record.card_key in PRODUCTION_WEAPON_KEYS
    ]
    assert len(PRODUCTION_WEAPON_KEYS) == 11
    assert len(weapon_records) == 12
    zhuge_records = [
        record
        for record in weapon_records
        if record.card_key == "sgs_weapon_zhugeliannu"
    ]
    assert len(zhuge_records) == 2  # 两张诸葛连弩必须分别实际装备
    for record in weapon_records:
        equipped_game = _fresh(seed=3)
        _swap(equipped_game, record.instance_id, ZoneRef.hand("p1"))
        action = _action(
            equipped_game, "use_weapon", card_key=record.card_key
        )
        assert action is not None, (
            f"{record.card_key}/{record.instance_id}必须能从手牌主动装备"
        )
        assert action.card_instance_id == record.instance_id
        # 真实路径：step 内部执行 validate_action -> apply_action
        _step(equipped_game, action)
        slot = equipped_game.state.card_ids_in(
            ZoneRef.equipment("p1", "weapon")
        )
        assert slot == (record.instance_id,), (
            f"{record.instance_id}必须进入weapon槽"
        )
        assert record.instance_id not in equipped_game.state.card_ids_in(
            ZoneRef.hand("p1")
        ), f"{record.instance_id}必须从手牌离开"
        equipped_events = _events_of(
            equipped_game, EventType.EQUIPMENT_EQUIPPED
        )
        assert len(equipped_events) == 1
        assert equipped_events[0].card_instance_id == record.instance_id, (
            f"{record.instance_id}的equipment_equipped事件实体ID必须正确"
        )
        assert equipped_game.phase is ProductionPhase.PLAY


def test_weapon_equip_uses_card_used_and_public_events() -> None:
    game = _fresh(seed=3)
    registry = game.formal_registry
    record = next(r for r in registry.records if r.card_key == WEAPON_QINGGANG)
    _swap(game, record.instance_id, ZoneRef.hand("p1"))
    _step(game, _action(game, "use_weapon", card_key=WEAPON_QINGGANG))
    used = _events_of(game, EventType.CARD_USED)
    assert any(
        event.card_instance_id == record.instance_id and event.card_user == "p1"
        for event in used
    )
    equipped = _events_of(game, EventType.EQUIPMENT_EQUIPPED)
    assert len(equipped) == 1
    assert equipped[0].card_instance_id == record.instance_id
    assert equipped[0].equipment_owner == "p1"
    assert equipped[0].target_ids == ("p1",)
    assert equipped[0].payload == {"slot": "weapon", "reason": "equip"}
    # 装备区公开：装备事件与card_moved均进入事件链
    moved = _events_of(game, EventType.CARD_MOVED)
    assert any(
        event.card_instance_id == record.instance_id
        and event.payload.get("destination", {}).get("owner_id") == "p1"
        and event.payload.get("destination", {}).get("equipment_slot") == "weapon"
        for event in moved
    )


def test_no_weapon_default_attack_range_is_one() -> None:
    game = _fresh(seed=3)
    assert attack_range_of(game.state, "p1") == 1
    assert attack_range_of(game.state, "p2") == 1


def test_each_weapon_uses_formal_csv_attack_range() -> None:
    ranges = dict(weapon_attack_ranges())
    for weapon_key, expected in ranges.items():
        game = _fresh(seed=3)
        record = next(
            r for r in game.formal_registry.records if r.card_key == weapon_key
        )
        game._state = game.state.move_card(
            record.instance_id, ZoneRef.equipment("p1", "weapon")
        )
        assert attack_range_of(game.state, "p1") == expected
        assert attack_range_of(game.state, "p2") == 1


def test_weapon_dynamically_changes_slash_distance() -> None:
    # 双人环实际距离恒为1；武器改变攻击范围进而改变杀目标合法性判定入口。
    game = _fresh(seed=3)
    registry = game.formal_registry
    record = next(r for r in registry.records if r.card_key == WEAPON_QINGGANG)
    _swap(game, record.instance_id, ZoneRef.hand("p1"))
    _step(game, _action(game, "use_weapon", card_key=WEAPON_QINGGANG))
    assert attack_range_of(game.state, "p1") == 2
    # 攻击范围读取是动态的：卸下武器后回到默认1
    game._state = game.state.move_card(
        record.instance_id, ZoneRef.hand("p1")
    )
    assert attack_range_of(game.state, "p1") == 1


def test_same_slot_replacement_moves_old_weapon_to_discard() -> None:
    game = _fresh(seed=3)
    registry = game.formal_registry
    old = next(r for r in registry.records if r.card_key == WEAPON_QINGGANG)
    new = next(r for r in registry.records if r.card_key == "sgs_weapon_zhugeliannu")
    _swap(game, old.instance_id, ZoneRef.hand("p1"))
    _step(game, _action(game, "use_weapon", card_key=WEAPON_QINGGANG))
    _swap(game, new.instance_id, ZoneRef.hand("p1"))
    _step(game, _action(game, "use_weapon", card_key="sgs_weapon_zhugeliannu"))
    slot = game.state.card_ids_in(ZoneRef.equipment("p1", "weapon"))
    assert slot == (new.instance_id,)
    assert old.instance_id in game.state.card_ids_in(DISCARD_PILE)
    # 替换时三个装备事件顺序稳定：removed -> replaced -> equipped
    removed = _events_of(game, EventType.EQUIPMENT_REMOVED)
    replaced = _events_of(game, EventType.EQUIPMENT_REPLACED)
    equipped = _events_of(game, EventType.EQUIPMENT_EQUIPPED)
    assert len(removed) == 1 and len(replaced) == 1 and len(equipped) == 2
    assert removed[0].card_instance_id == old.instance_id
    assert replaced[0].payload == {
        "slot": "weapon",
        "old_instance_id": old.instance_id,
        "new_instance_id": new.instance_id,
    }
    sequences = [
        event.sequence
        for event in [removed[0], replaced[0], equipped[-1]]
    ]
    assert sequences == sorted(sequences)


def test_same_slot_replacement_is_atomic() -> None:
    # 替换后武器槽恰好一张新武器、旧武器在弃牌堆、全牌守恒；中间不存在
    # 同槽两张武器的非法GameState。
    game = _fresh(seed=3)
    registry = game.formal_registry
    old = next(r for r in registry.records if r.card_key == WEAPON_QINGGANG)
    new = next(r for r in registry.records if r.card_key == "sgs_weapon_zhugeliannu")
    _swap(game, old.instance_id, ZoneRef.hand("p1"))
    _step(game, _action(game, "use_weapon", card_key=WEAPON_QINGGANG))
    _swap(game, new.instance_id, ZoneRef.hand("p1"))
    _step(game, _action(game, "use_weapon", card_key="sgs_weapon_zhugeliannu"))
    assert len(game.state.card_ids_in(ZoneRef.equipment("p1", "weapon"))) == 1
    game.state.assert_card_conservation()


def test_equipment_zone_is_public_and_entity_identity_preserved() -> None:
    game = _fresh(seed=3)
    registry = game.formal_registry
    record = next(r for r in registry.records if r.card_key == WEAPON_QINGGANG)
    _swap(game, record.instance_id, ZoneRef.hand("p1"))
    _step(game, _action(game, "use_weapon", card_key=WEAPON_QINGGANG))
    slot_id = game.state.card_ids_in(ZoneRef.equipment("p1", "weapon"))[0]
    assert slot_id == record.instance_id
    assert game.state.cards_by_id[slot_id].card_name == "青釭剑"
    assert game.state.cards_by_id[slot_id].card_key == WEAPON_QINGGANG


def test_weapon_equip_strictly_reproducible() -> None:
    runs: list[list[dict]] = []
    for _ in range(2):
        game = _fresh(seed=3)
        registry = game.formal_registry
        record = next(r for r in registry.records if r.card_key == WEAPON_QINGGANG)
        _swap(game, record.instance_id, ZoneRef.hand("p1"))
        _step(game, _action(game, "use_weapon", card_key=WEAPON_QINGGANG))
        runs.append([event.to_replay_dict() for event in game.events])
    assert runs[0] == runs[1]


def test_tampered_weapon_entity_fails_closed() -> None:
    from scripts.sgs_engine.actions import validate_action

    game = _fresh(seed=3)
    registry = game.formal_registry
    record = next(r for r in registry.records if r.card_key == WEAPON_QINGGANG)
    _swap(game, record.instance_id, ZoneRef.hand("p1"))
    # 伪造装备动作：实体被替换为其他武器，必须不能通过验证
    other = next(
        r for r in registry.records if r.card_key == "sgs_weapon_hanbingjian"
    )
    forged = LegalAction(
        action_type=ActionType.USE_CARD,
        actor_id="p1",
        card_instance_id=other.instance_id,
        target_ids=("p1",),
        payload={
            "operation": "use_weapon",
            "card_key": WEAPON_QINGGANG,
            "card_name": "青釭剑",
        },
        action_id="act_weapon_forged",
    )
    with pytest.raises(InvalidActionError):
        validate_action(game.state, game._context(), forged, game.registry)


def test_tampered_attack_range_fails_closed() -> None:
    # 攻击范围由正式结构化CSV登记；武器槽状态非法（两张武器同槽）时，
    # 状态层本身必须失败关闭，不允许出现被范围计算消费的非法状态。
    from scripts.sgs_engine.model import ModelValidationError

    game = _fresh(seed=3)
    registry = game.formal_registry
    w1 = next(r for r in registry.records if r.card_key == WEAPON_QINGGANG)
    w2 = next(r for r in registry.records if r.card_key == "sgs_weapon_zhugeliannu")
    with pytest.raises(ModelValidationError):
        game.state.move_cards(
            {w1.instance_id: ZoneRef.equipment("p1", "weapon"),
             w2.instance_id: ZoneRef.equipment("p1", "weapon")}
        )
    # 正式牌堆中全部武器都已登记攻击范围；未知武器键不存在于合法状态。
    assert set(weapon_attack_ranges()) == set(PRODUCTION_WEAPON_KEYS)


def test_tampered_replacement_order_fails_closed() -> None:
    # 装备事件顺序（removed->replaced->equipped）进入事件哈希链；改变顺序
    # 会导致严格重执行或事件流校验失败关闭。
    game = _fresh(seed=3)
    registry = game.formal_registry
    old = next(r for r in registry.records if r.card_key == WEAPON_QINGGANG)
    new = next(r for r in registry.records if r.card_key == "sgs_weapon_zhugeliannu")
    _swap(game, old.instance_id, ZoneRef.hand("p1"))
    _step(game, _action(game, "use_weapon", card_key=WEAPON_QINGGANG))
    _swap(game, new.instance_id, ZoneRef.hand("p1"))
    _step(game, _action(game, "use_weapon", card_key="sgs_weapon_zhugeliannu"))
    removed = [e for e in _events_of(game, EventType.EQUIPMENT_REMOVED)]
    equipped = [e for e in _events_of(game, EventType.EQUIPMENT_EQUIPPED)]
    assert removed and equipped
    # 从事件链上重放时顺序是事件序号决定的：序号必须单调且removed早于equipped
    assert removed[0].sequence is not None and equipped[-1].sequence is not None
    assert removed[0].sequence < equipped[-1].sequence


def test_equipment_three_event_contract_legal_and_illegal() -> None:
    from scripts.sgs_engine.events import GameEvent

    # 合法构造
    ok = GameEvent(
        event_type=EventType.EQUIPMENT_EQUIPPED,
        card_instance_id="sgs-mobile-20260725-138",
        card_key=WEAPON_QINGGANG,
        equipment_owner="p1",
        target_ids=("p1",),
        payload={"slot": "weapon", "reason": "equip"},
    )
    assert ok.equipment_owner == "p1"
    # 非法：缺equipment_owner
    with pytest.raises(ValueError):
        GameEvent(
            event_type=EventType.EQUIPMENT_EQUIPPED,
            card_instance_id="sgs-mobile-20260725-138",
            card_key=WEAPON_QINGGANG,
            target_ids=("p1",),
            payload={"slot": "weapon", "reason": "equip"},
        )
    # 非法：target_ids不是装备拥有者
    with pytest.raises(ValueError):
        GameEvent(
            event_type=EventType.EQUIPMENT_REMOVED,
            card_instance_id="sgs-mobile-20260725-138",
            card_key=WEAPON_QINGGANG,
            equipment_owner="p1",
            target_ids=("p2",),
            payload={"slot": "weapon", "reason": "replaced"},
        )
    # 非法：payload字段集合不符
    with pytest.raises(ValueError):
        GameEvent(
            event_type=EventType.EQUIPMENT_REPLACED,
            card_instance_id="sgs-mobile-20260725-001",
            card_key="sgs_weapon_zhugeliannu",
            equipment_owner="p1",
            target_ids=("p1",),
            payload={"slot": "weapon"},
        )
    # 非法：非正式装备栏
    with pytest.raises(ValueError):
        GameEvent(
            event_type=EventType.EQUIPMENT_EQUIPPED,
            card_instance_id="sgs-mobile-20260725-138",
            card_key=WEAPON_QINGGANG,
            equipment_owner="p1",
            target_ids=("p1",),
            payload={"slot": "hand", "reason": "equip"},
        )



# ---------------------------------------------------------------------
# B. 借刀目标与无懈边界
# ---------------------------------------------------------------------


def test_first_target_must_have_weapon() -> None:
    game = _fresh(seed=3)
    registry = game.formal_registry
    jiedao = next(r for r in registry.records if r.card_key == JIEDAO)
    _swap(game, jiedao.instance_id, ZoneRef.hand("p1"))
    # p2 未装备武器：借刀使用动作不能被枚举
    assert _action(game, "use_jiedao", card_key=JIEDAO) is None


def test_first_target_cannot_be_user() -> None:
    game = _fresh(seed=3)
    registry = game.formal_registry
    jiedao = next(r for r in registry.records if r.card_key == JIEDAO)
    weapon = next(r for r in registry.records if r.card_key == WEAPON_QINGGANG)
    _swap(game, jiedao.instance_id, ZoneRef.hand("p1"))
    _swap(game, weapon.instance_id, ZoneRef.equipment("p1", "weapon"))
    # 只有自己装备武器：第一目标不能是自己，故无合法使用动作
    assert _action(game, "use_jiedao", card_key=JIEDAO) is None
    # 伪造以自己为第一目标的动作必须失败关闭
    forged = LegalAction(
        action_type=ActionType.USE_CARD,
        actor_id="p1",
        card_instance_id=jiedao.instance_id,
        target_ids=("p1",),
        payload={
            "operation": "use_jiedao",
            "card_key": JIEDAO,
            "second_target_id": "p2",
        },
        action_id="act_jiedao_self",
    )
    with pytest.raises(InvalidActionError):
        game.formal_registry.adapter_for(JIEDAO).apply_action(
            game.state, game._context(), forged
        )


def test_second_target_must_differ_from_first() -> None:
    game = _fresh(seed=3)
    jiedao_id, _, _ = _jiedao_fixture(game)
    forged = LegalAction(
        action_type=ActionType.USE_CARD,
        actor_id="p1",
        card_instance_id=jiedao_id,
        target_ids=("p2",),
        payload={
            "operation": "use_jiedao",
            "card_key": JIEDAO,
            "second_target_id": "p2",
        },
        action_id="act_jiedao_same",
    )
    with pytest.raises(InvalidActionError):
        game.formal_registry.adapter_for(JIEDAO).apply_action(
            game.state, game._context(), forged
        )


def test_second_target_can_be_user_and_first_check_requires_range() -> None:
    # 双人切片：第二目标只能是使用者p1；枚举即证明“第二目标可以是使用者”。
    game = _fresh(seed=3)
    _jiedao_fixture(game)
    action = _action(game, "use_jiedao", card_key=JIEDAO)
    assert action is not None
    assert action.target_ids == ("p2",)
    assert action.payload.get("second_target_id") == "p1"
    # 第一次检测要求第二目标处于第一目标当前攻击范围（青釭剑范围2，距离1）
    assert attack_range_of(game.state, "p2") == 2


def test_second_target_is_not_trick_target() -> None:
    game = _fresh(seed=3)
    jiedao_id, _, _ = _jiedao_fixture(game)
    action = _action(game, "use_jiedao", card_key=JIEDAO)
    assert action is not None
    _step(game, action)
    used = _events_of(game, EventType.CARD_USED)
    use_event = next(e for e in used if e.card_instance_id == jiedao_id)
    # card_used 的 target_ids 只包含第一目标
    assert use_event.target_ids == ("p2",)
    assert use_event.payload.get("second_target_id") == "p1"
    assert use_event.payload.get("purpose") == "force_slash_or_weapon_gain"


def test_second_target_has_no_independent_wuxie_window() -> None:
    game = _fresh(seed=3)
    _jiedao_fixture(game)
    _step(game, _action(game, "use_jiedao", card_key=JIEDAO))
    assert game.phase is ProductionPhase.TRICK_RESPONSE
    # 无懈必须以第一目标p2为锦囊目标；以第二目标p1为目标的伪造无懈失败关闭
    wuxie = next(
        r for r in game.formal_registry.records if r.card_key == WUXIE
    )
    _swap(game, wuxie.instance_id, ZoneRef.hand("p1"))
    forged = LegalAction(
        action_type=ActionType.USE_CARD,
        actor_id="p1",
        card_instance_id=wuxie.instance_id,
        target_ids=("p1",),
        payload={
            "operation": "use_wuxie",
            "card_key": WUXIE,
            "response_to": wuxie.instance_id,
            "root_trick_instance_id": wuxie.instance_id,
        },
        action_id="act_wuxie_wrong_target",
    )
    with pytest.raises(InvalidActionError):
        game.formal_registry.adapter_for(WUXIE).apply_action(
            game.state, game._context(), forged
        )


def test_second_target_can_still_wuxie_first_target_effect() -> None:
    # 第二目标本人（p1）仍可对作用于第一目标p2的借刀效果使用无懈。
    game = _fresh(seed=3)
    _jiedao_fixture(game, give_p1_wuxie=True)
    _step(game, _action(game, "use_jiedao", card_key=JIEDAO))
    wuxie_action = _action(game, "use_wuxie")
    assert wuxie_action is not None
    assert wuxie_action.target_ids == ("p2",)
    _step(game, wuxie_action)
    # 无懈后继续响应链，最终借刀被取消：无杀请求、无武器移动
    _step(game, _action(game, "pass_trick_response"))
    _step(game, _action(game, "pass_trick_response"))
    assert game.phase is ProductionPhase.PLAY
    assert game.runtime.pending_borrowed_sword is None


def test_nullified_jiedao_opens_no_slash_window_and_moves_no_weapon() -> None:
    game = _fresh(seed=3)
    jiedao_id, weapon_id, _ = _jiedao_fixture(game, give_p2_wuxie=True)
    _step(game, _action(game, "use_jiedao", card_key=JIEDAO))
    _step(game, _action(game, "pass_trick_response"))  # p1 pass
    _step(game, _action(game, "use_wuxie"))             # p2 无懈
    _step(game, _action(game, "pass_trick_response"))   # p1 pass
    _step(game, _action(game, "pass_trick_response"))   # p2 pass -> 取消
    assert game.phase is ProductionPhase.PLAY
    assert game.runtime.pending_borrowed_sword is None
    assert game.runtime.borrowed_sword_slash_handles == {}
    assert weapon_id in game.state.card_ids_in(ZoneRef.equipment("p2", "weapon"))
    assert weapon_id not in game.state.card_ids_in(ZoneRef.hand("p1"))
    assert jiedao_id in game.state.card_ids_in(DISCARD_PILE)
    assert jiedao_id not in game.state.card_ids_in(PROCESSING_ZONE)
    cancelled = _events_of(game, EventType.CARD_EFFECT_CANCELLED)
    assert any(e.card_instance_id == jiedao_id for e in cancelled)


def test_nullified_jiedao_root_discarded_once() -> None:
    game = _fresh(seed=3)
    jiedao_id, _, _ = _jiedao_fixture(game, give_p2_wuxie=True)
    _step(game, _action(game, "use_jiedao", card_key=JIEDAO))
    _step(game, _action(game, "pass_trick_response"))
    _step(game, _action(game, "use_wuxie"))
    _step(game, _action(game, "pass_trick_response"))
    _step(game, _action(game, "pass_trick_response"))
    moved = [
        e
        for e in _events_of(game, EventType.CARD_MOVED)
        if e.card_instance_id == jiedao_id
    ]
    # 手牌→处理区→弃牌堆：恰好一次进入处理区、一次进入弃牌堆
    assert len(moved) == 2


# ---------------------------------------------------------------------
# C. 强制使用【杀】
# ---------------------------------------------------------------------


def test_borrowed_slash_entity_plain_sha() -> None:
    game = _fresh(seed=3)
    jiedao_id, _, slash_ids = _jiedao_fixture(game, slash_keys=(SHA,))
    _use_jiedao(game)
    assert game.phase is ProductionPhase.BORROWED_SWORD_CHOICE
    _choose_borrowed_slash(game, slash_ids[0])
    used = _events_of(game, EventType.CARD_USED)
    slash_use = next(e for e in used if e.card_instance_id == slash_ids[0])
    assert slash_use.card_user == "p2"
    assert slash_use.target_ids == ("p1",)
    assert slash_use.payload.get("forced_use_context") == "borrowed_sword"
    assert slash_use.payload.get("ignore_slash_use_limit") is True
    assert slash_use.payload.get("root_trick_instance_id") == jiedao_id
    assert slash_use.payload.get("damage_nature") == "无属性"
    assert game.phase is ProductionPhase.SLASH_RESPONSE


def test_borrowed_slash_entity_huosha() -> None:
    game = _fresh(seed=3)
    _, _, slash_ids = _jiedao_fixture(game, slash_keys=(HUOSHA,))
    _use_jiedao(game)
    _choose_borrowed_slash(game, slash_ids[0])
    used = _events_of(game, EventType.CARD_USED)
    slash_use = next(e for e in used if e.card_instance_id == slash_ids[0])
    assert slash_use.card_user == "p2"
    assert slash_use.payload.get("damage_nature") == "火属性"


def test_borrowed_slash_entity_leisha() -> None:
    game = _fresh(seed=3)
    _, _, slash_ids = _jiedao_fixture(game, slash_keys=(LEISHA,))
    _use_jiedao(game)
    _choose_borrowed_slash(game, slash_ids[0])
    used = _events_of(game, EventType.CARD_USED)
    slash_use = next(e for e in used if e.card_instance_id == slash_ids[0])
    assert slash_use.card_user == "p2"
    assert slash_use.payload.get("damage_nature") == "雷属性"


def test_borrowed_slash_allowed_even_at_normal_use_limit() -> None:
    game = _fresh(seed=3)
    _, _, slash_ids = _jiedao_fixture(game, slash_keys=(SHA,))
    # 构造“第一目标本出牌阶段已经使用过杀”的状态：计数按角色保存，不临时清零。
    game._runtime = replace(
        game._runtime,
        slash_used_counts=MappingProxyType({"p2": 1}),
    )
    _use_jiedao(game)
    assert game.phase is ProductionPhase.BORROWED_SWORD_CHOICE
    _choose_borrowed_slash(game, slash_ids[0])
    assert game.phase is ProductionPhase.SLASH_RESPONSE
    assert game.runtime.slash_used_counts.get("p2") == 2


def test_borrowed_slash_increments_first_target_count_only() -> None:
    game = _fresh(seed=3)
    _, _, slash_ids = _jiedao_fixture(game, slash_keys=(SHA,))
    assert game.runtime.slash_used_counts.get("p2", 0) == 0
    assert game.runtime.slash_used_counts.get("p1", 0) == 0
    _use_jiedao(game)
    _choose_borrowed_slash(game, slash_ids[0])
    assert game.runtime.slash_used_counts.get("p2") == 1
    assert game.runtime.slash_used_counts.get("p1", 0) == 0


def test_borrowed_slash_does_not_ignore_attack_range() -> None:
    game = _fresh(seed=3)
    _jiedao_fixture(game)
    _use_jiedao(game)
    assert game.phase is ProductionPhase.BORROWED_SWORD_CHOICE
    # 篡改第二目标使杀目标非法：第二次动态重检失败关闭
    choice = next(
        a
        for a in game.legal_actions()
        if a.payload.get("operation") == "choose_borrowed_sword_slash"
    )
    forged = replace(choice, payload={**choice.payload, "second_target_id": "p2"})
    with pytest.raises(InvalidActionError):
        game.formal_registry.adapter_for(JIEDAO).apply_action(
            game.state, game._context(), forged
        )


def test_second_dynamic_recheck_rereads_current_weapon() -> None:
    # 无懈链期间第一目标武器消失：杀请求仍可进行（武器不是杀合法性的前提），
    # 且不使用使用借刀时保存的旧武器快照。
    game = _fresh(seed=3)
    jiedao_id, weapon_id, slash_ids = _jiedao_fixture(game, slash_keys=(SHA,))
    _step(game, _action(game, "use_jiedao", card_key=JIEDAO))
    # 无懈链期间移除第一目标武器（夹具）
    game._state = game.state.move_card(
        weapon_id, ZoneRef.hand("p1")
    )
    _close_trick_window(game)
    assert game.phase is ProductionPhase.BORROWED_SWORD_CHOICE
    _choose_borrowed_slash(game, slash_ids[0])
    assert game.phase is ProductionPhase.SLASH_RESPONSE
    # 使用杀后视为履行要求；武器已消失则不再交付
    _step(game, _action(game, "pass_slash_response"))
    assert game.phase is ProductionPhase.PLAY
    assert jiedao_id in game.state.card_ids_in(DISCARD_PILE)
    assert weapon_id not in game.state.card_ids_in(ZoneRef.equipment("p2", "weapon"))


def test_second_dynamic_recheck_target_invalid_skips_window() -> None:
    # 结构级边界：双人正式入口下“无懈链期间第二目标死亡但游戏未结束”
    # 不可达（死亡角色无法继续参与弃权响应）。直接调用内部状态机验证
    # 第二次检测的目标失效分支，不宣称双人端到端PROVEN。
    game = _fresh(seed=3)
    jiedao_id, weapon_id, _ = _jiedao_fixture(game, slash_keys=(SHA,))
    _step(game, _action(game, "use_jiedao", card_key=JIEDAO))
    assert game.phase is ProductionPhase.TRICK_RESPONSE
    dead_state = _replace_player(game.state, "p1", hp=0, alive=False)
    next_state, next_runtime = game._open_borrowed_sword(
        dead_state, game._runtime, game._runtime.pending_trick
    )
    # 不开杀选择窗口：直接进入武器交付路径（使用者死亡 -> 无牌可交）
    assert next_runtime.phase is ProductionPhase.PLAY
    assert next_runtime.pending_borrowed_sword is None
    assert weapon_id in next_state.card_ids_in(ZoneRef.equipment("p2", "weapon"))
    assert jiedao_id in next_state.card_ids_in(DISCARD_PILE)


def test_borrowed_slash_choice_uses_opaque_handle_only() -> None:
    game = _fresh(seed=3)
    _, _, slash_ids = _jiedao_fixture(game, slash_keys=(SHA,))
    _use_jiedao(game)
    assert game.phase is ProductionPhase.BORROWED_SWORD_CHOICE
    actions = [
        a
        for a in game.legal_actions()
        if a.payload.get("operation") == "choose_borrowed_sword_slash"
    ]
    assert actions
    for action in actions:
        assert action.card_instance_id is None
        assert set(action.payload) == _BS_CHOICE_PAYLOAD_KEYS
        assert "card_key" not in action.payload
        assert "suit" not in action.payload
        assert "rank" not in action.payload
        handle = str(action.payload["handle"])
        assert handle.startswith("bs_")
    # 拒绝动作与选择动作并存
    assert _action(game, "refuse_borrowed_sword_slash") is not None


def test_bare_entity_id_submission_rejected() -> None:
    game = _fresh(seed=3)
    _, _, slash_ids = _jiedao_fixture(game, slash_keys=(SHA,))
    _use_jiedao(game)
    choice = next(
        a
        for a in game.legal_actions()
        if a.payload.get("operation") == "choose_borrowed_sword_slash"
    )
    forged = replace(choice, payload={**choice.payload, "handle": slash_ids[0]})
    with pytest.raises(InvalidActionError):
        game.formal_registry.adapter_for(JIEDAO).apply_action(
            game.state, game._context(), forged
        )


def test_borrowed_slash_produces_normal_card_used_and_dodge_response() -> None:
    game = _fresh(seed=3)
    jiedao_id, weapon_id, slash_ids = _jiedao_fixture(game, slash_keys=(SHA,))
    _use_jiedao(game)
    _choose_borrowed_slash(game, slash_ids[0])
    assert game.phase is ProductionPhase.SLASH_RESPONSE
    # p1用【闪】响应
    shan = next(r for r in game.formal_registry.records if r.card_key == SHAN)
    _swap(game, shan.instance_id, ZoneRef.hand("p1"))
    _step(game, _action(game, "play_dodge"))
    assert game.phase is ProductionPhase.PLAY
    # 被闪抵消后仍视为已履行要求：不交武器，根借刀弃置一次
    assert weapon_id in game.state.card_ids_in(ZoneRef.equipment("p2", "weapon"))
    assert weapon_id not in game.state.card_ids_in(ZoneRef.hand("p1"))
    assert jiedao_id in game.state.card_ids_in(DISCARD_PILE)
    assert game.runtime.pending_borrowed_sword is None
    # 杀实体正常消耗（手牌→处理区→弃牌堆）
    assert slash_ids[0] in game.state.card_ids_in(DISCARD_PILE)


def test_borrowed_slash_dodged_still_fulfilled_no_weapon() -> None:
    game = _fresh(seed=3)
    jiedao_id, weapon_id, slash_ids = _jiedao_fixture(game, slash_keys=(SHA,))
    _use_jiedao(game)
    _choose_borrowed_slash(game, slash_ids[0])
    shan = next(r for r in game.formal_registry.records if r.card_key == SHAN)
    _swap(game, shan.instance_id, ZoneRef.hand("p1"))
    _step(game, _action(game, "play_dodge"))
    # 即使杀被闪抵消，也不得再交武器；第一目标保留武器
    assert weapon_id in game.state.card_ids_in(ZoneRef.equipment("p2", "weapon"))
    assert jiedao_id in game.state.card_ids_in(DISCARD_PILE)
    cancelled = _events_of(game, EventType.CARD_EFFECT_CANCELLED)
    assert any(e.card_instance_id == slash_ids[0] for e in cancelled)


def test_borrowed_fire_slash_enters_chain_damage() -> None:
    game = _fresh(seed=3)
    jiedao_id, weapon_id, slash_ids = _jiedao_fixture(game, slash_keys=(HUOSHA,))
    # p1横置（属性传导目标）与p2横置（原受伤者）——双人环传导候选
    _set_chained(game, "p1", True)
    _set_chained(game, "p2", True)
    _use_jiedao(game)
    _choose_borrowed_slash(game, slash_ids[0])
    _step(game, _action(game, "pass_slash_response"))
    chain_started = _events_of(game, EventType.CHAIN_DAMAGE_STARTED)
    assert chain_started, "火杀伤害必须进入属性传导"
    assert chain_started[0].payload["root_card_instance_id"] == slash_ids[0]
    # 传导结束后借刀完成：根借刀弃置、挂起清理
    assert game.phase is ProductionPhase.PLAY
    assert game.runtime.pending_borrowed_sword is None
    assert jiedao_id in game.state.card_ids_in(DISCARD_PILE)
    assert weapon_id in game.state.card_ids_in(ZoneRef.equipment("p2", "weapon"))


def test_borrowed_slash_dying_rescue_recovers_and_fulfills() -> None:
    game = _fresh(seed=3)
    jiedao_id, weapon_id, slash_ids = _jiedao_fixture(game, slash_keys=(SHA,))
    _set_hp(game, "p1", 1)
    _use_jiedao(game)
    _choose_borrowed_slash(game, slash_ids[0])
    _step(game, _action(game, "pass_slash_response"))
    assert game.phase is ProductionPhase.DYING_RESCUE
    assert game.runtime.pending_borrowed_sword is not None
    assert game.runtime.pending_borrowed_sword.stage == "slash_resolving"
    tao = next(r for r in game.formal_registry.records if r.card_key == TAO)
    _swap(game, tao.instance_id, ZoneRef.hand("p1"))
    _step(game, _action(game, "rescue_with_peach"))
    assert game.phase is ProductionPhase.PLAY
    assert game.state.players_by_id["p1"].hp == 1
    assert game.runtime.pending_borrowed_sword is None
    assert jiedao_id in game.state.card_ids_in(DISCARD_PILE)
    assert weapon_id in game.state.card_ids_in(ZoneRef.equipment("p2", "weapon"))


def test_borrowed_slash_keeps_first_target_weapon_and_no_repeat() -> None:
    game = _fresh(seed=3)
    jiedao_id, weapon_id, slash_ids = _jiedao_fixture(game, slash_keys=(SHA,))
    _use_jiedao(game)
    _choose_borrowed_slash(game, slash_ids[0])
    assert weapon_id in game.state.card_ids_in(ZoneRef.equipment("p2", "weapon"))
    _step(game, _action(game, "pass_slash_response"))
    # 不重复请求杀：无新的借刀选择窗口
    assert game.phase is ProductionPhase.PLAY
    assert _action(game, "choose_borrowed_sword_slash") is None
    assert game.runtime.pending_borrowed_sword is None
    # 不重复计数：p2只增加一次
    assert game.runtime.slash_used_counts.get("p2") == 1



# ---------------------------------------------------------------------
# D. 拒绝与武器进入使用者手牌
# ---------------------------------------------------------------------


def test_has_legal_slash_but_voluntarily_refuses() -> None:
    game = _fresh(seed=3)
    jiedao_id, weapon_id, slash_ids = _jiedao_fixture(game, slash_keys=(SHA,))
    _use_jiedao(game)
    assert game.phase is ProductionPhase.BORROWED_SWORD_CHOICE
    assert _action(game, "choose_borrowed_sword_slash") is not None
    # N3-A：拒绝前记录双方按角色出杀计数
    counts_before = dict(game.runtime.slash_used_counts)
    first_target_count_before = counts_before.get("p2", 0)
    user_count_before = counts_before.get("p1", 0)
    _refuse_borrowed_slash(game)
    assert game.phase is ProductionPhase.PLAY
    assert weapon_id in game.state.card_ids_in(ZoneRef.hand("p1"))
    assert jiedao_id in game.state.card_ids_in(DISCARD_PILE)
    assert game.runtime.pending_borrowed_sword is None
    # 拒绝与武器交付完成后，第一目标与借刀使用者计数均完全不变
    counts_after = dict(game.runtime.slash_used_counts)
    assert counts_after.get("p2", 0) == first_target_count_before
    assert counts_after.get("p1", 0) == user_count_before
    assert not any(
        event.event_type is EventType.CARD_USED
        and event.card_user == "p2"
        and event.payload.get("forced_use_context") == "borrowed_sword"
        for event in game.events
    )


def test_no_entity_slash_skips_window_and_delivers_weapon() -> None:
    game = _fresh(seed=3)
    jiedao_id, weapon_id, _ = _jiedao_fixture(game, slash_keys=())
    _use_jiedao(game)
    # 无实体杀：不打开选择窗口，直接交付武器
    assert game.phase is ProductionPhase.PLAY
    assert weapon_id in game.state.card_ids_in(ZoneRef.hand("p1"))
    assert weapon_id not in game.state.card_ids_in(ZoneRef.equipment("p2", "weapon"))
    assert jiedao_id in game.state.card_ids_in(DISCARD_PILE)


def test_second_check_target_invalid_delivers_no_weapon_when_user_dead() -> None:
    # 结构级边界：双人正式入口下“使用者死亡但游戏未结束”不可达；此处用
    # 权威状态转换助手构造内部状态机边界，不宣称双人端到端PROVEN。
    game = _fresh(seed=3)
    jiedao_id, weapon_id, _ = _jiedao_fixture(game, slash_keys=(SHA,))
    _step(game, _action(game, "use_jiedao", card_key=JIEDAO))
    dead_state = _replace_player(game.state, "p1", hp=0, alive=False)
    next_state, next_runtime = game._open_borrowed_sword(
        dead_state, game._runtime, game._runtime.pending_trick
    )
    assert next_runtime.phase is ProductionPhase.PLAY
    assert next_runtime.pending_borrowed_sword is None
    # 使用者已死亡：无牌可交，武器仍留在第一目标装备区
    assert weapon_id in next_state.card_ids_in(ZoneRef.equipment("p2", "weapon"))
    assert weapon_id not in next_state.card_ids_in(ZoneRef.hand("p1"))
    assert jiedao_id in next_state.card_ids_in(DISCARD_PILE)


def test_out_of_range_second_check_is_structural_unreachable() -> None:
    # 结构级说明：双人环无坐骑时实际距离恒为1，任何武器攻击范围>=1，
    # 因此“第二次检测超出攻击范围”在双人生产切片不可达；该分支由
    # is_valid_slash_target 动态重检守护，不得宣称双人端到端PROVEN。
    game = _fresh(seed=3)
    _jiedao_fixture(game)
    from scripts.sgs_engine.production_cards import actual_distance

    assert actual_distance(game.state, "p2", "p1") == 1
    assert attack_range_of(game.state, "p2") >= 1


def test_refusal_delivers_weapon_to_user_hand_not_equipment() -> None:
    game = _fresh(seed=3)
    jiedao_id, weapon_id, _ = _jiedao_fixture(game, slash_keys=())
    # 使用者自己已装备另一把武器：交付不得进入装备区、不得触发替换
    own = next(
        r
        for r in game.formal_registry.records
        if r.card_key == "sgs_weapon_zhugeliannu"
    )
    _swap(game, own.instance_id, ZoneRef.equipment("p1", "weapon"))
    _use_jiedao(game)
    assert weapon_id in game.state.card_ids_in(ZoneRef.hand("p1"))
    assert weapon_id not in game.state.card_ids_in(ZoneRef.equipment("p1", "weapon"))
    # 使用者原武器保持原实体
    assert own.instance_id in game.state.card_ids_in(ZoneRef.equipment("p1", "weapon"))
    # 第一目标武器槽清空
    assert weapon_id not in game.state.card_ids_in(ZoneRef.equipment("p2", "weapon"))
    # 不产生装备事件（不触发装备替换）
    equipped = _events_of(game, EventType.EQUIPMENT_EQUIPPED)
    replaced = _events_of(game, EventType.EQUIPMENT_REPLACED)
    assert not any(e.card_instance_id == weapon_id for e in equipped)
    assert not replaced


def test_weapon_delivery_events_order_and_fields() -> None:
    game = _fresh(seed=3)
    jiedao_id, weapon_id, _ = _jiedao_fixture(game, slash_keys=())
    _use_jiedao(game)
    moved = [
        e
        for e in _events_of(game, EventType.CARD_MOVED)
        if e.card_instance_id == weapon_id
    ]
    lost = [
        e
        for e in _events_of(game, EventType.CARD_LOST)
        if e.card_instance_id == weapon_id
    ]
    gained = [
        e
        for e in _events_of(game, EventType.CARD_GAINED)
        if e.card_instance_id == weapon_id
    ]
    assert len(moved) == 1 and len(lost) == 1 and len(gained) == 1
    assert moved[0].payload["reason"] == "jiedaosharen_weapon_gain"
    assert moved[0].payload["source"]["owner_id"] == "p2"
    assert moved[0].payload["source"]["equipment_slot"] == "weapon"
    assert moved[0].payload["destination"]["owner_id"] == "p1"
    assert moved[0].payload["destination"]["kind"] == "hand"
    assert lost[0].target_ids == ("p2",)
    assert gained[0].target_ids == ("p1",)
    sequences = [moved[0].sequence, lost[0].sequence, gained[0].sequence]
    assert sequences == sorted(sequences)
    assert sequences[0] < sequences[1] < sequences[2]


def test_weapon_disappeared_during_resolution_delivers_nothing() -> None:
    # 第一目标武器在无懈链期间消失：拒绝时无牌可交，不抛异常、不虚构武器。
    game = _fresh(seed=3)
    jiedao_id, weapon_id, slash_ids = _jiedao_fixture(game, slash_keys=(SHA,))
    _step(game, _action(game, "use_jiedao", card_key=JIEDAO))
    game._state = game.state.move_card(weapon_id, ZoneRef.hand("p1"))
    _close_trick_window(game)
    assert game.phase is ProductionPhase.BORROWED_SWORD_CHOICE
    _refuse_borrowed_slash(game)
    assert game.phase is ProductionPhase.PLAY
    # 武器已移动到p1手牌（夹具所致），交付路径没有再次移动它
    moved = [
        e
        for e in _events_of(game, EventType.CARD_MOVED)
        if e.card_instance_id == weapon_id
        and e.payload.get("reason") == "jiedaosharen_weapon_gain"
    ]
    assert not moved
    assert jiedao_id in game.state.card_ids_in(DISCARD_PILE)


def test_no_weapon_no_exception_and_finish_once() -> None:
    game = _fresh(seed=3)
    jiedao_id, weapon_id, _ = _jiedao_fixture(game, slash_keys=())
    # 第一目标武器在结算开始前消失：使用借刀时第一次检测就不会通过；
    # 因此在无懈链后武器消失的路径中，交付必须无异常且只结束一次。
    game._state = game.state.move_card(weapon_id, ZoneRef.hand("p1"))
    assert _action(game, "use_jiedao", card_key=JIEDAO) is None
    # 武器消失后无牌可交路径：直接验证no_weapon_to_transfer只结束一次
    game2 = _fresh(seed=3)
    jiedao2, weapon2, _ = _jiedao_fixture(game2, slash_keys=())
    _use_jiedao(game2)
    finish_events = [
        e
        for e in _events_of(game2, EventType.CARD_MOVED)
        if e.card_instance_id == jiedao2
        and e.payload.get("destination", {}).get("kind") == "discard_pile"
    ]
    assert len(finish_events) == 1
    assert finish_events[0].payload.get("decision") == "no_legal_slash"
    assert finish_events[0].payload.get("no_weapon_to_transfer") is False
    assert finish_events[0].payload.get("weapon_delivered") is True


def test_no_weapon_to_transfer_flag_when_nothing_to_deliver() -> None:
    game = _fresh(seed=3)
    jiedao_id, weapon_id, _ = _jiedao_fixture(game, slash_keys=(SHA,))
    _step(game, _action(game, "use_jiedao", card_key=JIEDAO))
    # 无懈链期间武器消失：仍重新检查实体杀并打开选择窗口
    game._state = game.state.move_card(weapon_id, ZoneRef.hand("p1"))
    _close_trick_window(game)
    assert game.phase is ProductionPhase.BORROWED_SWORD_CHOICE
    _refuse_borrowed_slash(game)
    finish_events = [
        e
        for e in _events_of(game, EventType.CARD_MOVED)
        if e.card_instance_id == jiedao_id
        and e.payload.get("destination", {}).get("kind") == "discard_pile"
    ]
    assert len(finish_events) == 1
    assert finish_events[0].payload.get("no_weapon_to_transfer") is True
    assert finish_events[0].payload.get("weapon_delivered") is False


# ---------------------------------------------------------------------
# E. 挂起与终局清理
# ---------------------------------------------------------------------


def test_pending_kept_while_slash_awaits_dodge() -> None:
    game = _fresh(seed=3)
    _, _, slash_ids = _jiedao_fixture(game, slash_keys=(SHA,))
    _use_jiedao(game)
    _choose_borrowed_slash(game, slash_ids[0])
    assert game.phase is ProductionPhase.SLASH_RESPONSE
    pending = game.runtime.pending_borrowed_sword
    assert pending is not None
    assert pending.stage == "slash_resolving"
    assert pending.chosen_slash_instance_id == slash_ids[0]
    assert pending.decision == "use_slash"
    assert pending.requirement_fulfilled is True


def test_pending_kept_during_dying_rescue() -> None:
    game = _fresh(seed=3)
    _, _, slash_ids = _jiedao_fixture(game, slash_keys=(SHA,))
    _set_hp(game, "p1", 1)
    _use_jiedao(game)
    _choose_borrowed_slash(game, slash_ids[0])
    _step(game, _action(game, "pass_slash_response"))
    assert game.phase is ProductionPhase.DYING_RESCUE
    pending = game.runtime.pending_borrowed_sword
    assert pending is not None and pending.stage == "slash_resolving"
    # 救援恢复后完成结算
    tao = next(r for r in game.formal_registry.records if r.card_key == TAO)
    _swap(game, tao.instance_id, ZoneRef.hand("p1"))
    _step(game, _action(game, "rescue_with_peach"))
    assert game.runtime.pending_borrowed_sword is None
    assert game.phase is ProductionPhase.PLAY


def test_pending_kept_during_chain_damage() -> None:
    game = _fresh(seed=3)
    jiedao_id, weapon_id, slash_ids = _jiedao_fixture(game, slash_keys=(HUOSHA,))
    _set_chained(game, "p1", True)
    _set_chained(game, "p2", True)
    _set_hp(game, "p2", 1)
    _use_jiedao(game)
    _choose_borrowed_slash(game, slash_ids[0])
    _step(game, _action(game, "pass_slash_response"))
    # 原始角色p1受火属性伤害 -> 传导开始 -> 传导目标p2受伤害进入濒死
    assert _events_of(game, EventType.CHAIN_DAMAGE_STARTED)
    assert game.phase is ProductionPhase.DYING_RESCUE
    # 传导暂停期间借刀保持挂起
    pending = game.runtime.pending_borrowed_sword
    assert pending is not None and pending.stage == "slash_resolving"
    # 救援p2后传导继续并完成，借刀完成：根借刀弃置、挂起清理
    tao = next(r for r in game.formal_registry.records if r.card_key == TAO)
    _swap(game, tao.instance_id, ZoneRef.hand("p1"))
    _step(game, _action(game, "rescue_with_peach"))
    assert game.phase is ProductionPhase.PLAY
    assert game.runtime.pending_borrowed_sword is None
    assert jiedao_id in game.state.card_ids_in(DISCARD_PILE)
    assert weapon_id in game.state.card_ids_in(ZoneRef.equipment("p2", "weapon"))


def test_game_over_cleans_pending_and_discards_root() -> None:
    # 借刀杀杀死使用者：胜利成立后挂起清理、根借刀进弃牌堆、处理区无遗留。
    game = _fresh(seed=3)
    jiedao_id, weapon_id, slash_ids = _jiedao_fixture(game, slash_keys=(SHA,))
    _set_hp(game, "p1", 1)
    _use_jiedao(game)
    _choose_borrowed_slash(game, slash_ids[0])
    _step(game, _action(game, "pass_slash_response"))
    assert game.phase is ProductionPhase.DYING_RESCUE
    # 双方都不救援 -> 死亡与胜利
    _step(game, _action(game, "pass_rescue"))
    _step(game, _action(game, "pass_rescue"))
    assert game.is_finished
    assert game.winner_id == "p2"
    assert game.runtime.pending_borrowed_sword is None
    assert jiedao_id in game.state.card_ids_in(DISCARD_PILE)
    assert jiedao_id not in game.state.card_ids_in(PROCESSING_ZONE)
    assert not game.state.card_ids_in(PROCESSING_ZONE)
    # 不再交武器：武器仍在第一目标装备区
    assert weapon_id in game.state.card_ids_in(ZoneRef.equipment("p2", "weapon"))
    assert weapon_id not in game.state.card_ids_in(ZoneRef.hand("p1"))
    # 根借刀只弃置一次、杀只移动一次
    jiedao_moves = [
        e
        for e in _events_of(game, EventType.CARD_MOVED)
        if e.card_instance_id == jiedao_id
    ]
    assert len(jiedao_moves) == 2  # 手牌→处理区、处理区→弃牌堆
    slash_moves = [
        e
        for e in _events_of(game, EventType.CARD_MOVED)
        if e.card_instance_id == slash_ids[0]
    ]
    assert len(slash_moves) == 2


def test_victory_death_cleanup_event_order_deterministic() -> None:
    game = _fresh(seed=3)
    jiedao_id, _, slash_ids = _jiedao_fixture(game, slash_keys=(SHA,))
    _set_hp(game, "p1", 1)
    _use_jiedao(game)
    _choose_borrowed_slash(game, slash_ids[0])
    _step(game, _action(game, "pass_slash_response"))
    _step(game, _action(game, "pass_rescue"))
    _step(game, _action(game, "pass_rescue"))
    order = [(e.event_type.value, e.sequence) for e in game.events]
    # 杀完成结算 -> 根借刀终局清理 -> 死亡 -> 胜利（顺序固定）
    finish = [
        (t, s)
        for t, s in order
        if t == "card_moved"
        and any(
            e.card_instance_id == jiedao_id
            and e.payload.get("reason") == "jiedaosharen_victory_cleanup"
            for e in game.events
            if e.sequence == s
        )
    ]
    assert finish
    death_seq = next(s for t, s in order if t == "death")
    victory_seq = next(s for t, s in order if t == "victory")
    assert finish[0][1] < death_seq < victory_seq


def test_borrowed_sword_pending_never_replaced_by_other_pending() -> None:
    # 借刀使用杀后：pending_slash 是子结算，pending_borrowed_sword 是外层根，
    # 两者并存，不互相覆盖。
    game = _fresh(seed=3)
    _, _, slash_ids = _jiedao_fixture(game, slash_keys=(SHA,))
    _use_jiedao(game)
    _choose_borrowed_slash(game, slash_ids[0])
    assert game.runtime.pending_slash is not None
    assert game.runtime.pending_borrowed_sword is not None
    assert game.runtime.pending_slash.slash_instance_id == slash_ids[0]



# ---------------------------------------------------------------------
# F. 武器技能失败关闭门禁
# ---------------------------------------------------------------------


def _equip_weapon(
    game: ProductionBasicCardBatch, weapon_key: str, player_id: str = "p1"
) -> None:
    record = next(
        r for r in game.formal_registry.records if r.card_key == weapon_key
    )
    game._state = game.state.move_card(
        record.instance_id, ZoneRef.equipment(player_id, "weapon")
    )


def test_cixiong_holder_slash_fails_closed() -> None:
    game = _fresh(seed=3)
    _equip_weapon(game, "sgs_weapon_cixiongshuanggujian")
    sha = next(r for r in game.formal_registry.records if r.card_key == SHA)
    _swap(game, sha.instance_id, ZoneRef.hand("p1"))
    with pytest.raises(UnsupportedRuleError):
        game.legal_actions()
    # 借刀强制杀同样失败关闭（第一目标持雌雄双股剑时无法证明目标非异性）
    game2 = _fresh(seed=3)
    _equip_weapon(game2, "sgs_weapon_cixiongshuanggujian", "p2")
    with pytest.raises(UnsupportedRuleError):
        check_weapon_skill_gate(
            game2.state,
            actor_id="p2",
            decision="forced_slash",
            target_id="p1",
            slash_card_key=SHA,
        )


def test_zhangba_possible_expansion_enumerates_virtual() -> None:
    # USER_CONFIRMED_RULE（2026-08-09）：丈八材料 HAND→PROCESSING→DISCARD
    # 已确认并实现（VIRTUAL_CARD_SUBCARD_LIFECYCLE_RULE_GAP 已关闭）；
    # 手牌>=2时 legal_actions 枚举丈八虚拟杀使用选项，不再失败关闭
    game = _fresh(seed=3)
    _equip_weapon(game, "sgs_weapon_zhangbashemao")
    actions = game.legal_actions()
    assert any(
        a.payload.get("zhangba_virtual") is True
        and a.payload.get("operation") == "use_slash"
        for a in actions
    )
    # 手牌<2张时可证明无转化材料：按实体杀流程继续
    game2 = _fresh(seed=3)
    _equip_weapon(game2, "sgs_weapon_zhangbashemao")
    hand = list(game2.state.card_ids_in(ZoneRef.hand("p1")))
    # 把p1手牌清到1张（移到牌堆）
    for instance_id in hand[1:]:
        game2._state = game2.state.move_card(instance_id, DISCARD_PILE)
    sha = next(r for r in game2.formal_registry.records if r.card_key == SHA)
    _swap(game2, sha.instance_id, ZoneRef.hand("p1"))
    ops = [a.payload.get("operation") for a in game2.legal_actions()]
    assert "use_slash" in ops
    assert not any(
        a.payload.get("zhangba_virtual") is True for a in game2.legal_actions()
    )


def test_zhuque_entity_plain_slash_convertible_now_implemented() -> None:
    """CP-04P：朱雀羽扇实现后普通杀不再失败关闭，可枚举转火杀动作。"""
    game = _fresh(seed=3)
    _equip_weapon(game, "sgs_weapon_zhuqueyushan")
    sha = next(r for r in game.formal_registry.records if r.card_key == SHA)
    _swap(game, sha.instance_id, ZoneRef.hand("p1"))
    ops = [
        a.payload.get("operation")
        for a in game.legal_actions()
        if a.payload.get("operation") == "use_slash"
    ]
    assert "use_slash" in ops
    converted = [
        a
        for a in game.legal_actions()
        if a.payload.get("converted_to_fire") is True
    ]
    assert converted, "朱雀羽扇下普通杀必须可枚举转火杀动作"
    # 实体火杀不受朱雀羽扇影响：可继续
    game2 = _fresh(seed=3)
    _equip_weapon(game2, "sgs_weapon_zhuqueyushan")
    huosha = next(r for r in game2.formal_registry.records if r.card_key == HUOSHA)
    _swap(game2, huosha.instance_id, ZoneRef.hand("p1"))
    ops = [a.payload.get("operation") for a in game2.legal_actions()]
    assert "use_slash" in ops


def test_zhuge_active_extra_slash_available_when_count_exhausted() -> None:
    """CP-04P：诸葛连弩实现后，出牌阶段次数用尽仍可主动使用【杀】。"""
    game = _fresh(seed=3)
    _equip_weapon(game, "sgs_weapon_zhugeliannu")
    game._runtime = replace(
        game._runtime,
        slash_used_counts=MappingProxyType({"p1": 1}),
    )
    sha = next(r for r in game.formal_registry.records if r.card_key == SHA)
    _swap(game, sha.instance_id, ZoneRef.hand("p1"))
    ops = [a.payload.get("operation") for a in game.legal_actions()]
    assert "use_slash" in ops


def test_zhuge_borrowed_forced_slash_not_dependent_on_skill() -> None:
    game = _fresh(seed=3)
    _equip_weapon(game, "sgs_weapon_zhugeliannu")
    # 借刀强制杀绕过次数限制来自借刀规则本身，不依赖连弩无限杀技能
    check_weapon_skill_gate(
        game.state,
        actor_id="p1",
        decision="forced_slash",
        target_id="p2",
        slash_used_count=1,
    )


def test_other_weapons_impact_matrix_provable_no_impact_and_fail_states() -> None:
    # 方天画戟：双人环额外目标不存在，可证明目标集合不变 -> 无影响
    game = _fresh(seed=3)
    _equip_weapon(game, "sgs_weapon_fangtianhuaji")
    sha = next(r for r in game.formal_registry.records if r.card_key == SHA)
    _swap(game, sha.instance_id, ZoneRef.hand("p1"))
    ops = [a.payload.get("operation") for a in game.legal_actions()]
    assert "use_slash" in ops
    # 青釭剑：目标无防具 -> 无影响；目标装备防具 -> 真实无视防具（CP-04P）
    game2 = _fresh(seed=3)
    _equip_weapon(game2, "sgs_weapon_qinggangjian")
    sha2 = next(r for r in game2.formal_registry.records if r.card_key == SHA)
    _swap(game2, sha2.instance_id, ZoneRef.hand("p1"))
    ops2 = [a.payload.get("operation") for a in game2.legal_actions()]
    assert "use_slash" in ops2
    game3 = _fresh(seed=3)
    _equip_weapon(game3, "sgs_weapon_qinggangjian")
    armor = next(
        r for r in game3.formal_registry.records if r.card_key == "sgs_armor_baguazhen"
    )
    game3._state = game3.state.move_card(
        armor.instance_id, ZoneRef.equipment("p2", "armor")
    )
    sha3 = next(r for r in game3.formal_registry.records if r.card_key == SHA)
    _swap(game3, sha3.instance_id, ZoneRef.hand("p1"))
    ops3 = [a.payload.get("operation") for a in game3.legal_actions()]
    assert "use_slash" in ops3
    # 古锭刀：目标无手牌 -> 真实伤害+1（CP-04P）；目标有手牌 -> 无影响
    game4 = _fresh(seed=3)
    _equip_weapon(game4, "sgs_weapon_gudingdao")
    sha4 = next(r for r in game4.formal_registry.records if r.card_key == SHA)
    _swap(game4, sha4.instance_id, ZoneRef.hand("p1"))
    for instance_id in list(game4.state.card_ids_in(ZoneRef.hand("p2"))):
        game4._state = game4.state.move_card(instance_id, DISCARD_PILE)
    ops4 = [a.payload.get("operation") for a in game4.legal_actions()]
    assert "use_slash" in ops4
    # 麒麟弓：目标无坐骑 -> 不触发窗口；目标有坐骑 -> 伤害后打开弃坐骑
    # 窗口（CP-04P 已实现，门禁不再失败关闭）
    game5 = _fresh(seed=3)
    _equip_weapon(game5, "sgs_weapon_qilingong", "p1")
    check_weapon_skill_gate(
        game5.state, actor_id="p1", decision="slash_damage", target_id="p2"
    )
    game6 = _fresh(seed=3)
    _equip_weapon(game6, "sgs_weapon_qilingong", "p1")
    mount = next(
        r for r in game6.formal_registry.records if r.card_key == "sgs_mount_offensive"
    )
    game6._state = game6.state.move_card(
        mount.instance_id, ZoneRef.equipment("p2", "attack_horse")
    )
    # 门禁放行（技能已实现，窗口在结算路径真实处理）
    check_weapon_skill_gate(
        game6.state, actor_id="p1", decision="slash_damage", target_id="p2"
    )


def test_dodge_time_weapon_gates_qinglong_and_guanshifu() -> None:
    # 青龙偃月刀（CP-04P COMPLETE）：被闪后门禁放行，继续杀窗口在结算
    # 路径真实处理；有杀与无杀两种状态均不再失败关闭
    game = _fresh(seed=3)
    _equip_weapon(game, "sgs_weapon_qinglongyanyuedao")
    sha = next(r for r in game.formal_registry.records if r.card_key == SHA)
    _swap(game, sha.instance_id, ZoneRef.hand("p1"))
    check_weapon_skill_gate(
        game.state, actor_id="p1", decision="slash_dodged", target_id="p2"
    )
    game2 = _fresh(seed=3)
    _equip_weapon(game2, "sgs_weapon_qinglongyanyuedao")
    for instance_id in list(game2.state.card_ids_in(ZoneRef.hand("p1"))):
        if game2.state.cards_by_id[instance_id].card_key in SLASH_CARD_KEYS:
            game2._state = game2.state.move_card(instance_id, DISCARD_PILE)
    check_weapon_skill_gate(
        game2.state, actor_id="p1", decision="slash_dodged", target_id="p2"
    )
    # 贯石斧（CP-04P COMPLETE）：被闪后门禁放行，弃2张强制命中窗口在
    # 结算路径真实处理；可弃牌充足与不足两种状态均不再失败关闭
    game3 = _fresh(seed=3)
    _equip_weapon(game3, "sgs_weapon_guanshifu")
    check_weapon_skill_gate(
        game3.state, actor_id="p1", decision="slash_dodged", target_id="p2"
    )
    game4 = _fresh(seed=3)
    _equip_weapon(game4, "sgs_weapon_guanshifu")
    for instance_id in list(game4.state.card_ids_in(ZoneRef.hand("p1"))):
        game4._state = game4.state.move_card(instance_id, DISCARD_PILE)
    check_weapon_skill_gate(
        game4.state, actor_id="p1", decision="slash_dodged", target_id="p2"
    )


def test_hanbingjian_damage_gate_passes_open() -> None:
    # 寒冰剑（CP-04P COMPLETE）：伤害前防止窗口在结算路径真实处理，
    # 门禁放行；被闪路径不受寒冰剑影响，同样放行
    game = _fresh(seed=3)
    _equip_weapon(game, "sgs_weapon_hanbingjian")
    check_weapon_skill_gate(
        game.state, actor_id="p1", decision="slash_damage", target_id="p2"
    )
    check_weapon_skill_gate(
        game.state, actor_id="p1", decision="slash_dodged", target_id="p2"
    )


def test_gate_failure_leaves_state_events_rng_pending_hash_unchanged() -> None:
    game = _fresh(seed=3)
    _equip_weapon(game, "sgs_weapon_cixiongshuanggujian")
    sha = next(r for r in game.formal_registry.records if r.card_key == SHA)
    _swap(game, sha.instance_id, ZoneRef.hand("p1"))
    before_state = game.state
    before_events = len(game.events)
    before_rng = len(game.rng_calls)
    before_pending = game.runtime.pending_borrowed_sword
    before_hash = game.execution_hash
    with pytest.raises(UnsupportedRuleError):
        game.legal_actions()
    assert game.state == before_state
    assert len(game.events) == before_events
    assert len(game.rng_calls) == before_rng
    assert game.runtime.pending_borrowed_sword == before_pending
    assert game.execution_hash == before_hash


def test_zhangba_borrowed_without_entity_slash_uses_virtual() -> None:
    """借刀要求使用【杀】时，装备丈八且无实体杀的第一目标可以选择丈八
    虚拟杀履行（USER_CONFIRMED_RULE，2026-08-09）；材料 HAND→PROCESSING，
    结算完成后 PROCESSING→DISCARD；借刀履行后武器保留、不交付。"""
    game = _fresh(seed=3)
    jiedao_id, weapon_id, slash_ids = _jiedao_fixture(
        game,
        weapon_key="sgs_weapon_zhangbashemao",
        slash_keys=(),
    )
    assert slash_ids == []
    p2_hand = tuple(game.state.card_ids_in(ZoneRef.hand("p2")))
    assert len(p2_hand) >= 2
    assert not any(
        game.state.cards_by_id[instance_id].card_key in SLASH_CARD_KEYS
        for instance_id in p2_hand
    )

    _step(game, _action(game, "use_jiedao", card_key=JIEDAO))
    _step(game, _action(game, "pass_trick_response"))
    _step(game, _action(game, "pass_trick_response"))
    assert game.phase is ProductionPhase.BORROWED_SWORD_CHOICE
    zhangba_choices = [
        a
        for a in game.legal_actions()
        if a.payload.get("zhangba_virtual") is True
    ]
    assert zhangba_choices
    chosen = zhangba_choices[0]
    assert str(chosen.card_instance_id or "").startswith("virtual:zhangba:")
    assert "handle" in chosen.payload
    _step(game, chosen)
    # 材料权威移入处理区；进入杀结算链
    pending = game.runtime.pending_slash
    assert pending is not None and pending.virtual
    materials = pending.material_ids
    assert len(materials) == 2
    for instance_id in materials:
        assert game.state.location_of(instance_id) == PROCESSING_ZONE
    # 完成闪响应/伤害结算（参考控制器），材料在结算完成后进入弃牌堆
    controller = BatchReferenceController()
    guard = 0
    while game.runtime.pending_slash is not None and guard < 40:
        game.step(controller)
        guard += 1
    assert game.runtime.pending_slash is None
    for instance_id in materials:
        assert game.state.location_of(instance_id) == DISCARD_PILE
    # 借刀已履行：武器保留，不交付给使用者
    assert weapon_id in game.state.card_ids_in(
        ZoneRef.equipment("p2", "weapon")
    )
    assert weapon_id not in game.state.card_ids_in(ZoneRef.hand("p1"))
    assert not any(
        event.payload.get("reason") == "borrowed_sword_gain"
        for event in game.events
    )


def test_zhangba_borrowed_dying_rescue_finalizes_materials() -> None:
    """MB-B-002/C：借刀丈八杀 → DYING → 桃救回，材料恰好 finalize。"""

    game = _fresh(seed=3)
    jiedao_id, weapon_id, slash_ids = _jiedao_fixture(
        game,
        weapon_key="sgs_weapon_zhangbashemao",
        slash_keys=(),
    )
    assert slash_ids == []
    _set_hp(game, "p1", 1)
    _step(game, _action(game, "use_jiedao", card_key=JIEDAO))
    _step(game, _action(game, "pass_trick_response"))
    _step(game, _action(game, "pass_trick_response"))
    assert game.phase is ProductionPhase.BORROWED_SWORD_CHOICE
    zhangba_choices = [
        a
        for a in game.legal_actions()
        if a.payload.get("zhangba_virtual") is True
    ]
    assert zhangba_choices
    _step(game, zhangba_choices[0])
    _step(game, _action(game, "pass_slash_response"))
    assert game.phase is ProductionPhase.DYING_RESCUE
    pending = game.runtime.pending_slash
    assert pending is not None and pending.virtual
    materials = pending.material_ids
    for instance_id in materials:
        assert game.state.location_of(instance_id) == PROCESSING_ZONE
    tao = next(r for r in game.formal_registry.records if r.card_key == TAO)
    _swap(game, tao.instance_id, ZoneRef.hand("p1"))
    _step(game, _action(game, "rescue_with_peach"))
    assert game.phase is ProductionPhase.PLAY
    for instance_id in materials:
        assert game.state.location_of(instance_id) == DISCARD_PILE
    assert not game.state.card_ids_in(PROCESSING_ZONE)
    assert game.runtime.pending_borrowed_sword is None
    assert jiedao_id in game.state.card_ids_in(DISCARD_PILE)
    assert weapon_id in game.state.card_ids_in(
        ZoneRef.equipment("p2", "weapon")
    )


def test_zhangba_borrowed_dying_death_game_over_finalizes_materials() -> None:
    """MB-B-002/D：借刀丈八杀 → DYING → 死亡/game over，材料不悬空。"""

    game = _fresh(seed=3)
    jiedao_id, weapon_id, slash_ids = _jiedao_fixture(
        game,
        weapon_key="sgs_weapon_zhangbashemao",
        slash_keys=(),
    )
    assert slash_ids == []
    _set_hp(game, "p1", 1)
    _step(game, _action(game, "use_jiedao", card_key=JIEDAO))
    _step(game, _action(game, "pass_trick_response"))
    _step(game, _action(game, "pass_trick_response"))
    zhangba_choices = [
        a
        for a in game.legal_actions()
        if a.payload.get("zhangba_virtual") is True
    ]
    _step(game, zhangba_choices[0])
    _step(game, _action(game, "pass_slash_response"))
    assert game.phase is ProductionPhase.DYING_RESCUE
    pending = game.runtime.pending_slash
    assert pending is not None and pending.virtual
    materials = pending.material_ids
    _step(game, _action(game, "pass_rescue"))
    _step(game, _action(game, "pass_rescue"))
    assert game.is_finished
    assert game.winner_id == "p2"
    for instance_id in materials:
        assert game.state.location_of(instance_id) == DISCARD_PILE
    assert not game.state.card_ids_in(PROCESSING_ZONE)
    assert game.runtime.pending_borrowed_sword is None
    assert jiedao_id in game.state.card_ids_in(DISCARD_PILE)
    assert weapon_id in game.state.card_ids_in(
        ZoneRef.equipment("p2", "weapon")
    )
    game.assert_finished_state_invariants()


def test_weapon_gates_never_approximate_unknown_weapons() -> None:
    # 未知武器键（理论上不可能出现在正式牌堆，但防御性断言）必须失败关闭，
    # 不得静默当作白板；approximation_count 始终为0（由源码审计与门禁覆盖）。
    game = _fresh(seed=3)
    from scripts.sgs_engine.production_cards import weapon_attack_ranges as _r

    assert set(_r()) == set(PRODUCTION_WEAPON_KEYS)
    # 武器技能影响门禁对未知决策类型失败关闭
    with pytest.raises(UnsupportedRuleError):
        check_weapon_skill_gate(game.state, actor_id="p1", decision="unknown_kind")


# ---------------------------------------------------------------------
# G. 严格回放与安全
# ---------------------------------------------------------------------


def _jiedao_replay_fixture(game: ProductionBasicCardBatch) -> None:
    registry = game.formal_registry
    jiedao = next(r for r in registry.records if r.card_key == JIEDAO)
    weapon = next(r for r in registry.records if r.card_key == WEAPON_QINGGANG)
    slash = next(r for r in registry.records if r.card_key == SHA)
    _swap(game, jiedao.instance_id, ZoneRef.hand("p1"))
    _swap(game, weapon.instance_id, ZoneRef.equipment("p2", "weapon"))
    _swap(game, slash.instance_id, ZoneRef.hand("p2"))


def _jiedao_use_slash_record() -> ProductionReexecutionReplay:
    return record_reference_production_batch(
        seed=3,
        controller=ScriptedBatchController(
            [
                {"operation": "use_jiedao", "card_key": JIEDAO},
                {"operation": "pass_trick_response"},
                {"operation": "pass_trick_response"},
                {"operation": "choose_borrowed_sword_slash"},
                {"operation": "pass_slash_response"},
            ]
        ),
        fixture=_jiedao_replay_fixture,
    )


def _jiedao_refuse_record() -> ProductionReexecutionReplay:
    return record_reference_production_batch(
        seed=3,
        controller=ScriptedBatchController(
            [
                {"operation": "use_jiedao", "card_key": JIEDAO},
                {"operation": "pass_trick_response"},
                {"operation": "pass_trick_response"},
                {"operation": "refuse_borrowed_sword_slash"},
            ]
        ),
        fixture=_jiedao_replay_fixture,
    )


def _jiedao_victory_fixture(game: ProductionBasicCardBatch) -> None:
    _jiedao_replay_fixture(game)
    _set_hp(game, "p1", 1)


def _jiedao_victory_record() -> ProductionReexecutionReplay:
    return record_reference_production_batch(
        seed=3,
        controller=ScriptedBatchController(
            [
                {"operation": "use_jiedao", "card_key": JIEDAO},
                {"operation": "pass_trick_response"},
                {"operation": "pass_trick_response"},
                {"operation": "choose_borrowed_sword_slash"},
                {"operation": "pass_slash_response"},
                {"operation": "pass_rescue"},
                {"operation": "pass_rescue"},
            ]
        ),
        fixture=_jiedao_victory_fixture,
    )


def test_jiedao_use_slash_path_strictly_reexecutes() -> None:
    record = _jiedao_use_slash_record()
    assert record.header["fixture_applied"] is True
    result = reexecute_production_replay(record, fixture=_jiedao_replay_fixture)
    assert result.verified is True
    assert result.winner_id == record.outcome["winner_id"]
    # 借刀根锦囊完成弃置
    assert any(
        event.get("event_type") == "card_moved"
        and event.get("payload", {}).get("reason") == "jiedaosharen_fulfilled"
        for event in record.events
    )
    # 强制杀产生第一目标自己的card_used（含绕过标志）
    forced = [
        event
        for event in record.events
        if event.get("event_type") == "card_used"
        and event.get("payload", {}).get("forced_use_context") == "borrowed_sword"
    ]
    assert len(forced) == 1
    assert forced[0]["payload"]["ignore_slash_use_limit"] is True
    assert forced[0]["card_user"] == "p2"
    # 轮换后仍可再次严格重执行（往返）
    roundtrip = ProductionReexecutionReplay.from_dict(record.to_dict())
    roundtrip.verify_integrity()
    again = reexecute_production_replay(roundtrip, fixture=_jiedao_replay_fixture)
    assert again.verified is True
    assert again.final_execution_hash == result.final_execution_hash


def test_jiedao_refuse_path_strictly_reexecutes() -> None:
    record = _jiedao_refuse_record()
    result = reexecute_production_replay(record, fixture=_jiedao_replay_fixture)
    assert result.verified is True
    gained = [
        event
        for event in record.events
        if event.get("event_type") == "card_gained"
        and event.get("payload", {}).get("reason") == "jiedaosharen_weapon_gain"
    ]
    assert len(gained) == 1
    assert tuple(gained[0]["target_ids"]) == ("p1",)


def test_jiedao_victory_cleanup_strictly_reexecutes() -> None:
    # N3-B：借刀要求使用杀→子杀导致濒死→救援失败产生胜利的完整回放。
    record = _jiedao_victory_record()
    result = reexecute_production_replay(
        record, fixture=_jiedao_victory_fixture
    )
    assert result.verified is True
    assert result.winner_id == "p2"
    assert result.final_game_state_hash == (
        record.outcome["final_game_state_hash"]
    )
    assert result.final_execution_hash == (
        record.outcome["final_execution_hash"]
    )
    assert result.event_count == len(record.events)
    assert result.event_count == len(record.event_hash_chain)
    record.verify_integrity()
    assert record.outcome["event_chain_tip"] == record.event_hash_chain[-1]
    roundtrip = ProductionReexecutionReplay.from_dict(record.to_dict())
    roundtrip.verify_integrity()
    again = reexecute_production_replay(
        roundtrip, fixture=_jiedao_victory_fixture
    )
    assert again.verified is True
    use_decision = next(
        decision
        for decision in record.decisions
        if decision["chosen_action"].get("payload", {}).get("operation")
        == "use_jiedao"
    )
    jiedao_id = use_decision["chosen_action"]["card_instance_id"]
    jiedao_moves = [
        event
        for event in record.events
        if event.get("event_type") == "card_moved"
        and event.get("card_instance_id") == jiedao_id
    ]
    assert len(jiedao_moves) == 2  # 手牌→处理区、处理区→弃牌堆（只清理一次）
    cleanup = [
        event
        for event in jiedao_moves
        if event.get("payload", {}).get("reason")
        == "jiedaosharen_victory_cleanup"
    ]
    assert len(cleanup) == 1
    assert cleanup[0]["payload"]["destination"]["kind"] == "discard_pile"
    # 不发生后续武器交付
    assert not any(
        event.get("event_type") == "card_gained"
        and event.get("payload", {}).get("reason")
        == "jiedaosharen_weapon_gain"
        for event in record.events
    )
    # 终局挂起与牌区状态：真实运行同一控制器路径验证
    live = _fresh(seed=3)
    _jiedao_victory_fixture(live)
    live.run(
        ScriptedBatchController(
            [
                {"operation": "use_jiedao", "card_key": JIEDAO},
                {"operation": "pass_trick_response"},
                {"operation": "pass_trick_response"},
                {"operation": "choose_borrowed_sword_slash"},
                {"operation": "pass_slash_response"},
                {"operation": "pass_rescue"},
                {"operation": "pass_rescue"},
            ]
        )
    )
    assert live.is_finished
    assert live.runtime.pending_borrowed_sword is None
    assert jiedao_id in live.state.card_ids_in(DISCARD_PILE)
    assert jiedao_id not in live.state.card_ids_in(PROCESSING_ZONE)
    assert not live.state.card_ids_in(PROCESSING_ZONE)


def test_tampered_no_weapon_to_transfer_flag_fails_closed() -> None:
    # N3-C：合法录制“拒绝且武器存在”路径，其结束事件 no_weapon_to_transfer=False。
    # 真实“第二次检测时已无武器”的确定性路径需要在无懈链期间移除武器，
    # 当前回放夹具只在开局应用、严格重执行记录结构无法表达结算中途的状态
    # 突变（真实缺口，见报告）；因此以等价单字段篡改验证该字段受事件链保护。
    record = _jiedao_refuse_record()
    finish_events = [
        event
        for event in record.events
        if event.get("event_type") == "card_moved"
        and event.get("payload", {}).get("destination", {}).get("kind")
        == "discard_pile"
        and event.get("payload", {}).get("no_weapon_to_transfer") is not None
    ]
    assert len(finish_events) == 1
    assert finish_events[0]["payload"]["no_weapon_to_transfer"] is False
    tampered = copy.deepcopy(record.to_dict())
    target = next(
        event
        for event in tampered["events"]
        if event.get("event_type") == "card_moved"
        and event.get("payload", {}).get("destination", {}).get("kind")
        == "discard_pile"
        and event.get("payload", {}).get("no_weapon_to_transfer") is not None
    )
    target["payload"]["no_weapon_to_transfer"] = True
    tampered["record_sha256"] = ""
    with pytest.raises(ProductionReplayFormatError):
        ProductionReexecutionReplay.from_dict(tampered)


def test_second_target_never_gets_independent_wuxie_window_in_replay() -> None:
    # N3-D：真实借刀回放中，所有借刀无懈响应决策的 pending_trick.target_id
    # 始终是第一目标p2；不存在以第二目标p1为target的新pending_trick。
    record = _jiedao_use_slash_record()
    jiedao_pass_decisions = [
        decision
        for decision in record.decisions
        if decision["chosen_action"].get("payload", {}).get("operation")
        == "pass_trick_response"
        and decision["context"]["metadata"]
        .get("pending_trick", {})
        .get("trick_key")
        == JIEDAO
    ]
    assert len(jiedao_pass_decisions) == 2
    for decision in jiedao_pass_decisions:
        pending_trick = decision["context"]["metadata"]["pending_trick"]
        assert pending_trick["target_id"] == "p2"
        assert pending_trick["target_id"] != "p1"
    assert not any(
        (decision["context"]["metadata"].get("pending_trick") or {}).get(
            "target_id"
        )
        == "p1"
        for decision in record.decisions
    )
    # 伪造第二目标独立窗口：只篡改一个决策上下文的 pending_trick.target_id
    tampered = copy.deepcopy(record.to_dict())
    target_decision = next(
        decision
        for decision in tampered["decisions"]
        if decision["chosen_action"].get("payload", {}).get("operation")
        == "pass_trick_response"
        and decision["context"]["metadata"]
        .get("pending_trick", {})
        .get("trick_key")
        == JIEDAO
    )
    target_decision["context"]["metadata"]["pending_trick"]["target_id"] = "p1"
    tampered["record_sha256"] = ""
    rebuilt = ProductionReexecutionReplay.from_dict(tampered)
    with pytest.raises(ProductionReplayDivergenceError):
        reexecute_production_replay(rebuilt, fixture=_jiedao_replay_fixture)


def test_second_target_only_participates_in_first_target_wuxie_chain() -> None:
    # N3-D 实况路径：无懈链期间每次响应前 pending_trick 都只指向第一目标，
    # 第二目标以同一响应链参与者身份出现，不产生第二套窗口。
    game = _fresh(seed=3)
    _jiedao_fixture(game)
    _step(game, _action(game, "use_jiedao", card_key=JIEDAO))
    assert game.phase is ProductionPhase.TRICK_RESPONSE
    jiedao_id = game.runtime.pending_trick.trick_instance_id
    for _ in range(2):
        assert game.runtime.pending_trick is not None
        assert game.runtime.pending_trick.target_id == "p2"
        assert game.runtime.pending_trick.trick_instance_id == jiedao_id
        assert game.runtime.trick_response_order == ("p1", "p2")
        assert game.runtime.trick_direct_response_to == jiedao_id
        _step(game, _action(game, "pass_trick_response"))
    assert game.phase is ProductionPhase.BORROWED_SWORD_CHOICE
    assert game.runtime.pending_trick is not None
    assert game.runtime.pending_trick.target_id == "p2"


def test_jiedao_nullified_path_strictly_reexecutes() -> None:
    def fixture_with_wuxie(game: ProductionBasicCardBatch) -> None:
        _jiedao_replay_fixture(game)
        wuxie = next(
            r for r in game.formal_registry.records if r.card_key == WUXIE
        )
        _swap(game, wuxie.instance_id, ZoneRef.hand("p2"))

    record = record_reference_production_batch(
        seed=3,
        controller=ScriptedBatchController(
            [
                {"operation": "use_jiedao", "card_key": JIEDAO},
                {"operation": "pass_trick_response"},
                {"operation": "use_wuxie"},
                {"operation": "pass_trick_response"},
                {"operation": "pass_trick_response"},
            ]
        ),
        fixture=fixture_with_wuxie,
    )
    result = reexecute_production_replay(record, fixture=fixture_with_wuxie)
    assert result.verified is True
    use_decision = next(
        d
        for d in record.decisions
        if d["chosen_action"].get("payload", {}).get("operation") == "use_jiedao"
    )
    jiedao_id = use_decision["chosen_action"]["card_instance_id"]
    cancelled = [
        event
        for event in record.events
        if event.get("event_type") == "card_effect_cancelled"
        and event.get("card_instance_id") == jiedao_id
    ]
    assert len(cancelled) == 1
    # 无杀请求、无武器移动
    assert not any(
        event.get("event_type") == "card_used"
        and event.get("payload", {}).get("forced_use_context") == "borrowed_sword"
        for event in record.events
    )
    assert not any(
        event.get("event_type") == "card_gained"
        and event.get("payload", {}).get("reason") == "jiedaosharen_weapon_gain"
        for event in record.events
    )


def test_tampered_first_or_second_target_fails_closed() -> None:
    # 借刀选择负载中 first_target_id=p2（第一目标）、second_target_id=p1（使用者）。
    # 分别篡改为与原值不同的角色：重执行必须失败关闭。
    tamper_map = {"first_target_id": "p1", "second_target_id": "p2"}
    for field, forged_value in tamper_map.items():
        record = _jiedao_use_slash_record()
        tampered = copy.deepcopy(record.to_dict())
        decision = next(
            d
            for d in tampered["decisions"]
            if d["chosen_action"].get("payload", {}).get("operation")
            == "choose_borrowed_sword_slash"
        )
        assert decision["chosen_action"]["payload"][field] != forged_value
        decision["chosen_action"]["payload"][field] = forged_value
        tampered["record_sha256"] = ""
        rebuilt = ProductionReexecutionReplay.from_dict(tampered)
        with pytest.raises(ProductionReplayDivergenceError):
            reexecute_production_replay(rebuilt, fixture=_jiedao_replay_fixture)


def test_tampered_wuxie_result_fails_closed() -> None:
    # 无懈取消路径：删除取消事件即篡改Wuxie结果，事件链/重执行必须失败关闭
    def fixture_with_wuxie(game: ProductionBasicCardBatch) -> None:
        _jiedao_replay_fixture(game)
        wuxie = next(
            r for r in game.formal_registry.records if r.card_key == WUXIE
        )
        _swap(game, wuxie.instance_id, ZoneRef.hand("p2"))

    record = record_reference_production_batch(
        seed=3,
        controller=ScriptedBatchController(
            [
                {"operation": "use_jiedao", "card_key": JIEDAO},
                {"operation": "pass_trick_response"},
                {"operation": "use_wuxie"},
                {"operation": "pass_trick_response"},
                {"operation": "pass_trick_response"},
            ]
        ),
        fixture=fixture_with_wuxie,
    )
    tampered = copy.deepcopy(record.to_dict())
    tampered["events"] = [
        event
        for event in tampered["events"]
        if event.get("event_type") != "card_effect_cancelled"
    ]
    tampered["record_sha256"] = ""
    with pytest.raises(ProductionReplayFormatError):
        ProductionReexecutionReplay.from_dict(tampered)


def test_tampered_use_refuse_decision_fails_closed() -> None:
    record = _jiedao_use_slash_record()
    tampered = copy.deepcopy(record.to_dict())
    decision = next(
        d
        for d in tampered["decisions"]
        if d["chosen_action"].get("payload", {}).get("operation")
        == "choose_borrowed_sword_slash"
    )
    decision["chosen_action"]["payload"]["operation"] = (
        "refuse_borrowed_sword_slash"
    )
    tampered["record_sha256"] = ""
    rebuilt = ProductionReexecutionReplay.from_dict(tampered)
    with pytest.raises(ProductionReplayDivergenceError):
        reexecute_production_replay(rebuilt, fixture=_jiedao_replay_fixture)


def test_tampered_slash_handle_fails_closed() -> None:
    record = _jiedao_use_slash_record()
    tampered = copy.deepcopy(record.to_dict())
    decision = next(
        d
        for d in tampered["decisions"]
        if d["chosen_action"].get("payload", {}).get("operation")
        == "choose_borrowed_sword_slash"
    )
    decision["chosen_action"]["payload"]["handle"] = "bs_" + "0" * 32
    tampered["record_sha256"] = ""
    rebuilt = ProductionReexecutionReplay.from_dict(tampered)
    with pytest.raises(ProductionReplayDivergenceError):
        reexecute_production_replay(rebuilt, fixture=_jiedao_replay_fixture)


def test_tampered_slash_entity_fails_closed() -> None:
    record = _jiedao_use_slash_record()
    tampered = copy.deepcopy(record.to_dict())
    forced = next(
        event
        for event in tampered["events"]
        if event.get("event_type") == "card_used"
        and event.get("payload", {}).get("forced_use_context") == "borrowed_sword"
    )
    forced["card_instance_id"] = "sgs-mobile-forged-slash"
    tampered["record_sha256"] = ""
    with pytest.raises(ProductionReplayFormatError):
        ProductionReexecutionReplay.from_dict(tampered)


def test_tampered_limit_bypass_flag_fails_closed() -> None:
    record = _jiedao_use_slash_record()
    tampered = copy.deepcopy(record.to_dict())
    forced = next(
        event
        for event in tampered["events"]
        if event.get("event_type") == "card_used"
        and event.get("payload", {}).get("forced_use_context") == "borrowed_sword"
    )
    forced["payload"]["ignore_slash_use_limit"] = False
    tampered["record_sha256"] = ""
    with pytest.raises(ProductionReplayFormatError):
        ProductionReexecutionReplay.from_dict(tampered)


def test_tampered_counted_role_fails_closed() -> None:
    record = _jiedao_use_slash_record()
    tampered = copy.deepcopy(record.to_dict())
    decision = next(
        d
        for d in tampered["decisions"]
        if d["chosen_action"].get("payload", {}).get("operation")
        == "choose_borrowed_sword_slash"
    )
    decision["context"]["metadata"]["slash_used_counts"]["p2"] = 5
    tampered["record_sha256"] = ""
    rebuilt = ProductionReexecutionReplay.from_dict(tampered)
    with pytest.raises(ProductionReplayDivergenceError):
        reexecute_production_replay(rebuilt, fixture=_jiedao_replay_fixture)


def test_tampered_weapon_entity_and_destination_fail_closed() -> None:
    record = _jiedao_refuse_record()
    tampered = copy.deepcopy(record.to_dict())
    gained = next(
        event
        for event in tampered["events"]
        if event.get("event_type") == "card_gained"
        and event.get("payload", {}).get("reason") == "jiedaosharen_weapon_gain"
    )
    gained["card_instance_id"] = "sgs-mobile-forged-weapon"
    tampered["record_sha256"] = ""
    with pytest.raises(ProductionReplayFormatError):
        ProductionReexecutionReplay.from_dict(tampered)

    record2 = _jiedao_refuse_record()
    tampered2 = copy.deepcopy(record2.to_dict())
    moved = next(
        event
        for event in tampered2["events"]
        if event.get("event_type") == "card_moved"
        and event.get("payload", {}).get("reason") == "jiedaosharen_weapon_gain"
    )
    moved["payload"]["destination"]["owner_id"] = "p2"
    tampered2["record_sha256"] = ""
    with pytest.raises(ProductionReplayFormatError):
        ProductionReexecutionReplay.from_dict(tampered2)


def test_tampered_equipment_events_fail_closed() -> None:
    # 装备事件进入事件链：篡改equipment_equipped的owner/slot必须失败关闭
    record = record_reference_production_batch(
        seed=3,
        controller=ScriptedBatchController(
            [
                {"operation": "use_weapon", "card_key": WEAPON_QINGGANG},
            ]
        ),
        fixture=lambda game: _swap(
            game,
            next(
                r
                for r in game.formal_registry.records
                if r.card_key == WEAPON_QINGGANG
            ).instance_id,
            ZoneRef.hand("p1"),
        ),
    )
    tampered = copy.deepcopy(record.to_dict())
    equipped = next(
        event
        for event in tampered["events"]
        if event.get("event_type") == "equipment_equipped"
    )
    equipped["equipment_owner"] = "p2"
    tampered["record_sha256"] = ""
    with pytest.raises(ProductionReplayFormatError):
        ProductionReexecutionReplay.from_dict(tampered)


def test_deleted_root_cleanup_event_fails_closed() -> None:
    record = _jiedao_use_slash_record()
    tampered = copy.deepcopy(record.to_dict())
    tampered["events"] = [
        event
        for event in tampered["events"]
        if not (
            event.get("event_type") == "card_moved"
            and event.get("payload", {}).get("reason") == "jiedaosharen_fulfilled"
        )
    ]
    tampered["record_sha256"] = ""
    with pytest.raises(ProductionReplayFormatError):
        ProductionReexecutionReplay.from_dict(tampered)


def test_player_visible_replay_leaks_no_other_hands_or_handle_maps() -> None:
    record = _jiedao_use_slash_record()
    visible = record.player_visible_payload()
    assert visible["player_visible"] is True
    assert "authoritative_private" not in visible
    # B1-a/B1-b：公共视图 decisions 无私有动作与权威摘要
    for decision in visible["decisions"]:
        assert "chosen_action" not in decision
        assert "legal_actions" not in decision
    # 玩家可见导出不得包含会话秘密与句柄到实体的映射
    assert "session_secret_hex" not in str(visible)
    assert "borrowed_sword_slash_handles" not in str(visible)
    # 未选择杀实体ID不得出现在事件或决策负载中（公共initial_hand事件除外）
    game = _fresh(seed=3)
    _jiedao_replay_fixture(game)
    hand_ids = set(game.state.card_ids_in(ZoneRef.hand("p2")))
    exposed_ids: set[str] = set()
    for event in record.events:
        if (
            event.get("event_type") == "card_gained"
            and event.get("payload", {}).get("reason") == "initial_hand"
        ):
            continue
        if (
            event.get("event_type")
            in ("card_moved", "card_lost", "card_discarded")
            and event.get("payload", {}).get("reason") == "discard_phase"
        ):
            # CP-04O：弃牌阶段公开置入弃牌堆的实体属于合法公开信息
            continue
        if (
            event.get("event_type") == "card_moved"
            and event.get("payload", {}).get("reason") == "death_cleanup"
        ):
            # 死亡清场公开置入弃牌堆的实体属于合法公开信息
            continue
        if event.get("card_instance_id"):
            exposed_ids.add(str(event["card_instance_id"]))
        for material in event.get("material_card_instance_ids", []) or []:
            exposed_ids.add(str(material))
    for decision in record.decisions:
        chosen = decision["chosen_action"]
        if chosen.get("payload", {}).get("operation") in (
            "select_discard_card",
            "unselect_discard_card",
            "discard_phase_submit",
        ):
            # CP-04O：弃牌阶段公开置入弃牌堆的实体属于合法公开信息；
            # 选择/取消/提交动作是弃牌者本人的弃牌选择，属自信息
            continue
        if chosen.get("card_instance_id"):
            exposed_ids.add(str(chosen["card_instance_id"]))
    used_slash_ids = {
        str(event.get("card_instance_id"))
        for event in record.events
        if event.get("event_type") == "card_used"
    }
    for instance_id in hand_ids:
        if instance_id in used_slash_ids:
            continue
        assert instance_id not in exposed_ids, (
            f"未选择的手牌实体{instance_id}不得进入玩家可见回放"
        )

# ---------------------------------------------------------------------
# 朱雀羽扇×借刀杀人（2026-08-08 用户移动版实测确认）
# ---------------------------------------------------------------------


ZHUQUE = "sgs_weapon_zhuqueyushan"
TENGJIA = "sgs_armor_tengjia"


def _zhuque_jiedao_choice(
    game: ProductionBasicCardBatch,
    sha_id: str,
    *,
    converted: bool,
) -> None:
    """在借刀选择窗口选择指定普通杀，converted=True 时选择朱雀转火杀动作。"""

    assert game.phase is ProductionPhase.BORROWED_SWORD_CHOICE
    handle = _choice_handle_for(game, sha_id)
    candidates = [
        a
        for a in game.legal_actions()
        if a.payload.get("operation") == "choose_borrowed_sword_slash"
        and a.payload.get("handle") == handle
        and (a.payload.get("converted_to_fire") is True) == converted
    ]
    assert len(candidates) == 1
    _step(game, candidates[0])


def test_borrowed_sword_zhuque_plain_slash_unconverted() -> None:
    """A. 借刀时朱雀羽扇同时提供普通使用与转火杀；普通使用不转换。"""

    game = _fresh(seed=3)
    _jiedao_fixture(game, weapon_key=ZHUQUE, slash_keys=(SHA,))
    _use_jiedao(game)
    assert game.phase is ProductionPhase.BORROWED_SWORD_CHOICE
    sha_id = next(
        i
        for i in game.state.card_ids_in(ZoneRef.hand("p2"))
        if game.state.cards_by_id[i].card_key == SHA
    )
    plain_actions = [
        a
        for a in game.legal_actions()
        if a.payload.get("operation") == "choose_borrowed_sword_slash"
        and a.payload.get("converted_to_fire") is None
    ]
    fire_actions = [
        a
        for a in game.legal_actions()
        if a.payload.get("converted_to_fire") is True
    ]
    assert len(plain_actions) == 1
    assert len(fire_actions) == 1
    _zhuque_jiedao_choice(game, sha_id, converted=False)
    assert game.phase is ProductionPhase.SLASH_RESPONSE
    _step(game, _action(game, "pass_slash_response"))
    damages = _events_of(game, EventType.DAMAGE)
    assert len(damages) == 1
    assert damages[0].damage_type == "无属性"
    used = [
        e
        for e in game.events
        if e.event_type is EventType.CARD_USED
        and e.payload.get("converted_to_fire") is not None
    ]
    assert not used, "普通使用不得携带转换标记"
    game.state.assert_card_conservation()


def test_borrowed_sword_zhuque_converted_fire_slash() -> None:
    """B/C. 借刀时选择朱雀转换：从使用入口按火杀身份结算，产生火属性伤害。"""

    game = _fresh(seed=3)
    _jiedao_fixture(game, weapon_key=ZHUQUE, slash_keys=(SHA,))
    _use_jiedao(game)
    sha_id = next(
        i
        for i in game.state.card_ids_in(ZoneRef.hand("p2"))
        if game.state.cards_by_id[i].card_key == SHA
    )
    _zhuque_jiedao_choice(game, sha_id, converted=True)
    assert game.phase is ProductionPhase.SLASH_RESPONSE
    used = [
        e
        for e in game.events
        if e.event_type is EventType.CARD_USED
        and e.payload.get("converted_to_fire") is True
    ]
    assert len(used) == 1
    assert used[0].payload["weapon_convert_context"] == (
        "zhuqueyushan_borrowed_sword"
    )
    assert used[0].payload["damage_nature"] == "火属性"
    assert used[0].payload["forced_use_context"] == "borrowed_sword"
    _step(game, _action(game, "pass_slash_response"))
    damages = _events_of(game, EventType.DAMAGE)
    assert len(damages) == 1
    assert damages[0].damage_type == "火属性"
    game.state.assert_card_conservation()


def test_borrowed_sword_zhuque_converted_vs_tengjia() -> None:
    """D1. 借刀转火杀对藤甲：不被藤甲普通杀免疫，火属性伤害+1生效。"""

    game = _fresh(seed=3)
    _jiedao_fixture(game, weapon_key=ZHUQUE, slash_keys=(SHA,))
    tengjia = next(
        r for r in game.formal_registry.records if r.card_key == TENGJIA
    )
    _swap(game, tengjia.instance_id, ZoneRef.equipment("p1", "armor"))
    _use_jiedao(game)
    sha_id = next(
        i
        for i in game.state.card_ids_in(ZoneRef.hand("p2"))
        if game.state.cards_by_id[i].card_key == SHA
    )
    _zhuque_jiedao_choice(game, sha_id, converted=True)
    assert game.phase is ProductionPhase.SLASH_RESPONSE, (
        "转火杀不被藤甲免疫，必须进入响应窗口"
    )
    _step(game, _action(game, "pass_slash_response"))
    damages = _events_of(game, EventType.DAMAGE)
    assert len(damages) == 1
    assert damages[0].damage_type == "火属性"
    assert damages[0].amount == 2  # 1 + 藤甲火属性+1
    assert "tengjia_fire_plus_one" in damages[0].payload["modifiers"]
    game.state.assert_card_conservation()


def test_borrowed_sword_plain_slash_vs_tengjia_invalidated() -> None:
    """D2. 借刀普通杀不转换时对藤甲：仍按普通杀身份被藤甲无效化。"""

    game = _fresh(seed=3)
    _jiedao_fixture(game, weapon_key=ZHUQUE, slash_keys=(SHA,))
    tengjia = next(
        r for r in game.formal_registry.records if r.card_key == TENGJIA
    )
    _swap(game, tengjia.instance_id, ZoneRef.equipment("p1", "armor"))
    _use_jiedao(game)
    sha_id = next(
        i
        for i in game.state.card_ids_in(ZoneRef.hand("p2"))
        if game.state.cards_by_id[i].card_key == SHA
    )
    _zhuque_jiedao_choice(game, sha_id, converted=False)
    assert game.phase is not ProductionPhase.SLASH_RESPONSE, (
        "未转换的普通杀必须被藤甲无效化"
    )
    assert not _events_of(game, EventType.DAMAGE)
    cancelled = [
        e
        for e in game.events
        if e.event_type is EventType.CARD_EFFECT_CANCELLED
    ]
    assert cancelled and cancelled[-1].payload["reason"] == "tengjia_invalidates"
    assert game.phase is ProductionPhase.PLAY, "借刀根结算应正常完成"
    game.state.assert_card_conservation()


def test_borrowed_sword_no_conversion_without_zhuque() -> None:
    """E. 未装备朱雀羽扇时不得提供转火杀动作。"""

    game = _fresh(seed=3)
    _jiedao_fixture(game, weapon_key=WEAPON_QINGGANG, slash_keys=(SHA,))
    _use_jiedao(game)
    assert game.phase is ProductionPhase.BORROWED_SWORD_CHOICE
    fire_actions = [
        a
        for a in game.legal_actions()
        if a.payload.get("converted_to_fire") is True
    ]
    assert not fire_actions


def test_borrowed_sword_zhuque_conversion_stale_after_weapon_lost() -> None:
    """F. 朱雀羽扇在选择前失去：旧转火杀动作失败关闭。"""

    game = _fresh(seed=3)
    _jiedao_fixture(game, weapon_key=ZHUQUE, slash_keys=(SHA,))
    _use_jiedao(game)
    fire_action = next(
        a
        for a in game.legal_actions()
        if a.payload.get("converted_to_fire") is True
    )
    zhuque_id = game.state.card_ids_in(ZoneRef.equipment("p2", "weapon"))[0]
    game._state = game.state.move_card(zhuque_id, DISCARD_PILE)
    with pytest.raises(ProductionBatchError):
        game.step(BatchActionIdController(fire_action.action_id))
    # 普通使用动作仍然可用（未装备朱雀不影响普通杀使用）
    assert game.phase is ProductionPhase.BORROWED_SWORD_CHOICE
    game.state.assert_card_conservation()


class _ZhuqueConvertReferenceController(BatchReferenceController):
    """验收用控制器：出牌阶段优先使用【借刀杀人】，借刀选择窗口优先
    选择朱雀转火杀动作，其余回退参考策略。"""

    strategy_version = "production-batch-zhuque-convert-controller.v2"

    def choose(
        self, legal_actions, context
    ) -> LegalAction:
        for action in legal_actions:
            if action.payload.get("converted_to_fire") is True:
                return action
        if context.phase == "play":
            for action in legal_actions:
                if action.payload.get("operation") == "use_jiedao":
                    return action
        return super().choose(legal_actions, context)


def test_borrowed_sword_zhuque_conversion_replay_reexecutes() -> None:
    """G. 转火杀路径严格回放：记录、重执行与篡改拒绝。"""

    def fixture(game: ProductionBasicCardBatch) -> None:
        _jiedao_fixture(game, weapon_key=ZHUQUE, slash_keys=(SHA,))
        # 参考控制器在锦囊响应窗口总是优先打出【无懈可击】；为让借刀
        # 真正进入强制使用杀窗口，移除 p2 手牌中的无懈。
        for instance_id in list(game.state.card_ids_in(ZoneRef.hand("p2"))):
            if game.state.cards_by_id[instance_id].card_key == WUXIE:
                game._state = game.state.move_card(instance_id, DISCARD_PILE)

    record = record_reference_production_batch(
        seed=3,
        fixture=fixture,
        controller=_ZhuqueConvertReferenceController(),
    )
    assert any(
        decision.get("chosen_action", {}).get("payload", {}).get(
            "converted_to_fire"
        )
        is True
        for decision in record.decisions
    ), "回放必须包含借刀转火杀决策"
    result = reexecute_production_replay(record, fixture=fixture)
    assert result.verified is True
    # 篡改 used 事件的转换标记：重执行必须发散失败
    tampered = copy.deepcopy(record.to_dict())
    used = next(
        event
        for event in tampered["events"]
        if event.get("event_type") == "card_used"
        and event.get("payload", {}).get("converted_to_fire") is True
    )
    used["payload"]["converted_to_fire"] = False
    tampered["record_sha256"] = ""
    with pytest.raises(
        (ProductionReplayFormatError, ProductionReplayDivergenceError)
    ):
        reexecute_production_replay(
            ProductionReexecutionReplay.from_dict(tampered)
        )
