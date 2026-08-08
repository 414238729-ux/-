# -*- coding: utf-8 -*-
"""CP-04P：正式武器技能完整化（已验证部分）生产验收测试。

本批完成并证明：诸葛连弩（无限出杀）、青釭剑（真实 ignore_armor 生命周期）、
古锭刀（无手牌目标伤害+1）、方天画戟（双人生产入口范围内目标集合不变）。
规则来源：knowledge/三国杀卡牌效果.md 7.1／7.2／7.5／7.9（用户整理解释／
当前确认）与 knowledge/三国杀卡牌结构化数据.csv（攻击范围）。
其余武器（寒冰剑、雌雄双股剑、青龙偃月刀、贯石斧、丈八蛇矛、朱雀羽扇、
麒麟弓）保持集中式失败关闭门禁，如实记录在 WEAPON_SKILL_STATUS。
所有正向路径都经过真实生产注册表与 enumerate→validate→apply。
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
    PROCESSING_ZONE,
    ZoneRef,
)
from scripts.sgs_engine.production_batch import (
    BatchActionIdController,
    BatchReferenceController,
    ProductionBatchError,
    ProductionBasicCardBatch,
    ProductionPhase,
    ScriptedBatchController,
    _replace_player,
)
from scripts.sgs_engine.production_cards import (
    SLASH_CARD_KEYS,
    WEAPON_SKILL_STATUS,
    FormalCardRegistry,
    attack_range_of,
    equipped_weapon_key,
    weapon_attack_ranges,
)
from scripts.sgs_engine.production_replay import (
    ProductionReplayDivergenceError,
    ProductionReplayFormatError,
    ProductionReexecutionReplay,
    record_reference_production_batch,
    reexecute_production_replay,
)


EXPECTED_RANGES = {
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

COMPLETE_WEAPONS = frozenset(
    key for key, status in WEAPON_SKILL_STATUS.items() if status == "COMPLETE"
)


def _fresh(*args: object, **kwargs: object) -> ProductionBasicCardBatch:
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
) -> object | None:
    for action in game.legal_actions():
        if action.payload.get("operation") != operation:
            continue
        if card_key is not None and action.payload.get("card_key") != card_key:
            continue
        return action
    return None


def _step(game: ProductionBasicCardBatch, action: object) -> None:
    assert action is not None and getattr(action, "action_id", None), action
    game.step(BatchActionIdController(action.action_id))  # type: ignore[attr-defined]


def _equip(
    game: ProductionBasicCardBatch,
    key: str,
    player_id: str = "p1",
) -> str:
    record = next(
        r for r in game.formal_registry.records if r.card_key == key
    )
    game._state = game.state.move_card(
        record.instance_id, ZoneRef.equipment(player_id, "weapon")
    )
    return record.instance_id


def _equip_armor(
    game: ProductionBasicCardBatch,
    key: str,
    player_id: str = "p2",
) -> str:
    record = next(
        r for r in game.formal_registry.records if r.card_key == key
    )
    game._state = game.state.move_card(
        record.instance_id, ZoneRef.equipment(player_id, "armor")
    )
    return record.instance_id


def _put_hand(
    game: ProductionBasicCardBatch,
    key: str,
    player_id: str = "p1",
) -> str:
    record = next(
        r
        for r in game.formal_registry.records
        if r.card_key == key
        and game.state.location_of(r.instance_id) != ZoneRef.hand(player_id)
    )
    game._state = game.state.move_card(record.instance_id, ZoneRef.hand(player_id))
    return record.instance_id


def _use_slash_and_pass(
    game: ProductionBasicCardBatch,
    *,
    card_key: str = "sgs_basic_sha",
) -> list[object]:
    slash_action = _action(game, "use_slash", card_key=card_key)
    assert slash_action is not None, "必须能枚举出杀动作"
    _step(game, slash_action)
    assert game.phase is ProductionPhase.SLASH_RESPONSE
    pass_action = _action(game, "pass_slash_response")
    assert pass_action is not None
    _step(game, pass_action)
    return [event for event in game.events if event.event_type is EventType.DAMAGE]


def _damages(game: ProductionBasicCardBatch) -> list[object]:
    return [event for event in game.events if event.event_type is EventType.DAMAGE]


def _assert_conservation(game: ProductionBasicCardBatch) -> None:
    assert len(game.state.cards) == 160
    assert sum(
        len(game.state.card_ids_in(zone)) for zone in game.state.zone_order
    ) == 160


def _set_hp(game: ProductionBasicCardBatch, player_id: str, hp: int) -> None:
    game._state = _replace_player(game.state, player_id, hp=hp)


# ----------------------------------------------------------------------
# A. 武器清单
# ----------------------------------------------------------------------


def test_all_weapon_entities_present_with_ranges_and_status() -> None:
    game = _fresh(seed=3)
    registry = game.formal_registry
    weapon_records = [
        r for r in registry.records if r.card_key.startswith("sgs_weapon_")
    ]
    assert len(weapon_records) == 12
    counts = {
        key: sum(1 for r in weapon_records if r.card_key == key)
        for key in EXPECTED_RANGES
    }
    assert counts == {
        "sgs_weapon_zhugeliannu": 2,
        "sgs_weapon_qinggangjian": 1,
        "sgs_weapon_hanbingjian": 1,
        "sgs_weapon_cixiongshuanggujian": 1,
        "sgs_weapon_gudingdao": 1,
        "sgs_weapon_qinglongyanyuedao": 1,
        "sgs_weapon_guanshifu": 1,
        "sgs_weapon_zhangbashemao": 1,
        "sgs_weapon_fangtianhuaji": 1,
        "sgs_weapon_zhuqueyushan": 1,
        "sgs_weapon_qilingong": 1,
    }
    assert dict(weapon_attack_ranges()) == EXPECTED_RANGES
    for key in EXPECTED_RANGES:
        adapter = registry.adapter_for(key)
        spec = adapter.rule_spec()
        assert spec["attack_range"] == EXPECTED_RANGES[key]
        assert spec["skill_status"] == WEAPON_SKILL_STATUS[key].lower()
    assert COMPLETE_WEAPONS == {
        "sgs_weapon_zhugeliannu",
        "sgs_weapon_qinggangjian",
        "sgs_weapon_hanbingjian",
        "sgs_weapon_gudingdao",
        "sgs_weapon_qinglongyanyuedao",
        "sgs_weapon_guanshifu",
        "sgs_weapon_zhuqueyushan",
        "sgs_weapon_qilingong",
    }


# ----------------------------------------------------------------------
# B. 诸葛连弩
# ----------------------------------------------------------------------


def test_zhugeliannu_allows_second_slash_without_limit() -> None:
    game = _fresh(seed=3)
    _equip(game, "sgs_weapon_zhugeliannu")
    _put_hand(game, "sgs_basic_sha")
    _put_hand(game, "sgs_basic_sha")
    _use_slash_and_pass(game)
    assert game.runtime.slash_used_counts.get("p1", 0) == 1
    second = _action(game, "use_slash", card_key="sgs_basic_sha")
    assert second is not None, "连弩下次数用尽仍必须能枚举出杀"
    _step(game, second)
    assert game.runtime.slash_used_counts.get("p1", 0) == 2
    # 计数仍按角色记录，第二张杀正常进入响应窗口
    assert game.phase is ProductionPhase.SLASH_RESPONSE
    _assert_conservation(game)


def test_zhugeliannu_slash_usage_still_counted() -> None:
    game = _fresh(seed=3)
    _equip(game, "sgs_weapon_zhugeliannu")
    _put_hand(game, "sgs_basic_sha")
    _put_hand(game, "sgs_basic_sha")
    _use_slash_and_pass(game)
    _step(game, _action(game, "use_slash", card_key="sgs_basic_sha"))
    assert game.runtime.slash_used_counts.get("p1", 0) == 2


def test_zhugeliannu_removed_weapon_restores_limit() -> None:
    game = _fresh(seed=3)
    crossbow = _equip(game, "sgs_weapon_zhugeliannu")
    _put_hand(game, "sgs_basic_sha")
    _use_slash_and_pass(game)
    # 替换武器：连弩离开武器槽，次数限制恢复
    game._state = game.state.move_card(crossbow, DISCARD_PILE)
    _equip(game, "sgs_weapon_qinggangjian")
    assert equipped_weapon_key(game.state, "p1") == "sgs_weapon_qinggangjian"
    assert crossbow in game.state.card_ids_in(DISCARD_PILE)
    _put_hand(game, "sgs_basic_sha")
    assert _action(game, "use_slash", card_key="sgs_basic_sha") is None
    _assert_conservation(game)


# ----------------------------------------------------------------------
# C. 青釭剑：真实 ignore_armor 生命周期
# ----------------------------------------------------------------------


def test_qinggang_ignores_renwang_black_slash_invalidation() -> None:
    game = _fresh(seed=3)
    _equip(game, "sgs_weapon_qinggangjian")
    _equip_armor(game, "sgs_armor_renwangdun")
    _put_hand(game, "sgs_basic_leisha")
    _step(game, _action(game, "use_slash", card_key="sgs_basic_leisha"))
    assert game.phase is ProductionPhase.SLASH_RESPONSE, (
        "青釭剑下仁王盾黑杀无效化必须被抑制"
    )
    _step(game, _action(game, "pass_slash_response"))
    damages = _damages(game)
    assert len(damages) == 1
    assert damages[0].amount == 1
    assert damages[0].payload["armor_ignored"] is True
    # 防具实体未被移除
    assert game.state.card_ids_in(ZoneRef.equipment("p2", "armor"))
    _assert_conservation(game)


def test_qinggang_ignores_tengjia_plain_slash_invalidation() -> None:
    game = _fresh(seed=3)
    _equip(game, "sgs_weapon_qinggangjian")
    _equip_armor(game, "sgs_armor_tengjia")
    _put_hand(game, "sgs_basic_sha")
    _step(game, _action(game, "use_slash", card_key="sgs_basic_sha"))
    assert game.phase is ProductionPhase.SLASH_RESPONSE
    _step(game, _action(game, "pass_slash_response"))
    damages = _damages(game)
    assert len(damages) == 1 and damages[0].payload["armor_ignored"] is True
    # 藤甲火属性+1也不生效（防具无效抑制全部防具修正）
    assert "tengjia_fire_plus_one" not in damages[0].payload["modifiers"]


def test_qinggang_suppresses_bagua_judgment_activation() -> None:
    game = _fresh(seed=3)
    _equip(game, "sgs_weapon_qinggangjian")
    _equip_armor(game, "sgs_armor_baguazhen")
    _put_hand(game, "sgs_basic_sha")
    _step(game, _action(game, "use_slash", card_key="sgs_basic_sha"))
    assert game.phase is ProductionPhase.SLASH_RESPONSE
    assert (
        _action(game, "activate_bagua") is None
    ), "青釭剑下八卦阵响应判定必须被抑制"
    _step(game, _action(game, "pass_slash_response"))
    assert _damages(game)


def test_qinggang_suppresses_baiyin_cap_on_wine_slash() -> None:
    game = _fresh(seed=3)
    _equip(game, "sgs_weapon_qinggangjian")
    _equip_armor(game, "sgs_armor_baiyinshizi")
    _put_hand(game, "sgs_basic_jiu")
    _put_hand(game, "sgs_basic_sha")
    _step(game, _action(game, "use_wine_buff", card_key="sgs_basic_jiu"))
    _use_slash_and_pass(game)
    damages = _damages(game)
    assert len(damages) == 1
    assert damages[0].amount == 2, "青釭剑下白银狮子限伤必须被抑制"
    assert damages[0].payload["armor_ignored"] is True
    assert "baiyin_cap_one" not in damages[0].payload["modifiers"]


def test_qinggang_not_equipped_armor_remains_effective() -> None:
    game = _fresh(seed=3)
    _equip_armor(game, "sgs_armor_renwangdun")
    _put_hand(game, "sgs_basic_leisha")
    _step(game, _action(game, "use_slash", card_key="sgs_basic_leisha"))
    # 未装备青釭剑：黑杀被仁王盾无效化
    assert game.phase is not ProductionPhase.SLASH_RESPONSE
    assert not _damages(game)
    cancelled = [
        e
        for e in game.events
        if e.event_type is EventType.CARD_EFFECT_CANCELLED
    ]
    assert cancelled and cancelled[-1].payload["reason"] == (
        "renwangdun_black_slash"
    )


def test_qinggang_effect_does_not_residue_after_slash() -> None:
    game = _fresh(seed=3)
    _equip(game, "sgs_weapon_qinggangjian")
    _equip_armor(game, "sgs_armor_renwangdun")
    _put_hand(game, "sgs_basic_sha")
    _use_slash_and_pass(game)
    assert game.phase is ProductionPhase.PLAY
    # 结算结束后 ignore_armor 上下文随 pending_slash 清理，不残留
    assert game.runtime.pending_slash is None
    # 失去青釭剑后，下一次杀必须恢复防具无效化（不残留防具无效状态）
    weapon_id = game.state.card_ids_in(ZoneRef.equipment("p1", "weapon"))[0]
    game._state = game.state.move_card(weapon_id, DISCARD_PILE)
    from dataclasses import replace
    from types import MappingProxyType

    game._runtime = replace(
        game._runtime, slash_used_counts=MappingProxyType({"p1": 0})
    )
    _put_hand(game, "sgs_basic_leisha")
    _step(game, _action(game, "use_slash", card_key="sgs_basic_leisha"))
    assert game.phase is not ProductionPhase.SLASH_RESPONSE, (
        "失去青釭剑后下一次杀必须恢复防具无效化"
    )
    _assert_conservation(game)


def test_qinggang_borrowed_sword_gate_no_longer_fails_closed() -> None:
    game = _fresh(seed=3)
    _equip(game, "sgs_weapon_qinggangjian", "p2")
    # 借刀强制杀决策：青釭剑已实现，门禁直接放行（不再失败关闭）
    from scripts.sgs_engine.production_cards import check_weapon_skill_gate

    check_weapon_skill_gate(
        game.state,
        actor_id="p2",
        decision="forced_slash",
        target_id="p1",
        slash_card_key="sgs_basic_sha",
    )


# ----------------------------------------------------------------------
# D. 古锭刀
# ----------------------------------------------------------------------


def test_gudingdao_plus_one_when_target_has_no_hand() -> None:
    game = _fresh(seed=3)
    _equip(game, "sgs_weapon_gudingdao")
    for instance_id in list(game.state.card_ids_in(ZoneRef.hand("p2"))):
        game._state = game.state.move_card(instance_id, DISCARD_PILE)
    _put_hand(game, "sgs_basic_sha")
    _use_slash_and_pass(game)
    damages = _damages(game)
    assert len(damages) == 1
    assert damages[0].amount == 2
    assert damages[0].payload["weapon_damage_bonus"] == 1


# ----------------------------------------------------------------------
# J. 贯石斧（被闪后弃自己手牌+装备2张强制命中）
# ----------------------------------------------------------------------


def _dodge_and_open_weapon_window(
    game: ProductionBasicCardBatch,
) -> None:
    """使用杀→目标打出闪→返回武器选择窗口（贯石斧/青龙偃月刀）。"""

    _step(game, _action(game, "use_slash", card_key="sgs_basic_sha"))
    assert game.phase is ProductionPhase.SLASH_RESPONSE
    _step(game, _action(game, "play_dodge"))
    assert game.phase is ProductionPhase.WEAPON_SLASH_CHOICE


def _select_two_discard_two(game: ProductionBasicCardBatch) -> None:
    """在弃2张窗口中选择恰好2张牌并提交。"""

    first = _action(game, "select_discard_two")
    assert first is not None
    _step(game, first)
    second = _action(game, "select_discard_two")
    assert second is not None
    _step(game, second)
    submit = _action(game, "discard_two_submit")
    assert submit is not None, "选择2张后必须出现提交动作"
    _step(game, submit)


def test_guanshifu_force_hit_after_dodge() -> None:
    game = _fresh(seed=3)
    _equip(game, "sgs_weapon_guanshifu")
    _put_hand(game, "sgs_basic_sha")
    _dodge_and_open_weapon_window(game)
    _step(game, _action(game, "weapon_force_hit"))
    assert game.phase is ProductionPhase.WEAPON_DISCARD_TWO
    _select_two_discard_two(game)
    damages = _damages(game)
    assert len(damages) == 1
    assert damages[0].amount == 1
    assert damages[0].payload["weapon_effect"] == "guanshifu_force_hit"
    assert game.state.players_by_id["p2"].hp == 3
    assert game.phase is ProductionPhase.PLAY
    _assert_conservation(game)


def test_guanshifu_pass_no_damage() -> None:
    game = _fresh(seed=3)
    _equip(game, "sgs_weapon_guanshifu")
    _put_hand(game, "sgs_basic_sha")
    _dodge_and_open_weapon_window(game)
    _step(game, _action(game, "pass_weapon_choice"))
    assert not _damages(game)
    assert game.phase is ProductionPhase.PLAY
    cancelled = [
        e
        for e in game.events
        if e.event_type is EventType.CARD_EFFECT_CANCELLED
    ]
    assert cancelled and cancelled[-1].payload["reason"] == "dodge"
    _assert_conservation(game)


def test_guanshifu_no_window_when_insufficient_cards() -> None:
    game = _fresh(seed=3)
    _equip(game, "sgs_weapon_guanshifu")
    for instance_id in list(game.state.card_ids_in(ZoneRef.hand("p1"))):
        game._state = game.state.move_card(instance_id, DISCARD_PILE)
    _put_hand(game, "sgs_basic_sha")
    _step(game, _action(game, "use_slash", card_key="sgs_basic_sha"))
    _step(game, _action(game, "play_dodge"))
    assert game.phase is ProductionPhase.PLAY, (
        "攻击者弃牌不足2张时不得打开贯石斧窗口"
    )
    assert not _damages(game)
    _assert_conservation(game)


def test_guanshifu_forged_and_cross_player_rejected() -> None:
    game = _fresh(seed=3)
    _equip(game, "sgs_weapon_guanshifu")
    _put_hand(game, "sgs_basic_sha")
    _dodge_and_open_weapon_window(game)
    forged = LegalAction(
        action_type=ActionType.PASS,
        actor_id="p2",
        payload={
            "operation": "weapon_force_hit",
            "window_id": "forged",
        },
        action_id="act_forged_guanshifu",
    )
    with pytest.raises(InvalidActionError):
        validate_action(game.state, game._context(), forged, game.registry)
    _step(game, _action(game, "weapon_force_hit"))
    assert game.phase is ProductionPhase.WEAPON_DISCARD_TWO
    # 非选择者不能选择待弃牌
    forged_select = LegalAction(
        action_type=ActionType.CHOOSE_OPTION,
        actor_id="p2",
        card_instance_id="x",
        target_ids=("p1",),
        payload={
            "operation": "select_discard_two",
            "window_id": "forged",
            "state_hash": "x",
            "handle": "h_forged",
        },
        action_id="act_forged_select_two",
    )
    with pytest.raises(InvalidActionError):
        validate_action(
            game.state, game._context(), forged_select, game.registry
        )


# ----------------------------------------------------------------------
# K. 寒冰剑（伤害前防止＋弃目标手牌+装备至多2张）
# ----------------------------------------------------------------------


def _use_slash_to_hanbing_window(
    game: ProductionBasicCardBatch,
) -> None:
    _step(game, _action(game, "use_slash", card_key="sgs_basic_sha"))
    assert game.phase is ProductionPhase.SLASH_RESPONSE
    _step(game, _action(game, "pass_slash_response"))
    assert game.phase is ProductionPhase.WEAPON_SLASH_CHOICE, (
        "寒冰剑伤害前必须打开防止伤害窗口"
    )


def _hanbing_discard_one(game: ProductionBasicCardBatch) -> None:
    action = _action(game, "hanbing_discard_card")
    assert action is not None, "寒冰剑逐张弃置窗口必须提供弃置候选"
    _step(game, action)


def test_hanbing_prevent_damage_and_sequential_discards() -> None:
    """2026-08-08 用户移动版实测确认：寒冰剑两张牌是一张一张弃置，
    不是同时选择、同时弃置；两次弃置是两个连续的正式弃置步骤。"""

    game = _fresh(seed=3)
    _equip(game, "sgs_weapon_hanbingjian")
    _put_hand(game, "sgs_basic_sha")
    _use_slash_to_hanbing_window(game)
    _step(game, _action(game, "weapon_prevent_damage"))
    assert game.phase is ProductionPhase.HANBING_DISCARD
    assert game.runtime.pending_hanbing_discard is not None
    assert game.runtime.pending_hanbing_discard.step == 1
    step1_window = game.runtime.pending_hanbing_discard.window_id
    # 第1次弃置：只弃1张，产生真实card movement事件，第2张尚未离开
    _hanbing_discard_one(game)
    moved = [
        e
        for e in game.events
        if e.event_type is EventType.CARD_MOVED
        and e.payload.get("reason") == "hanbing_discard"
    ]
    assert len(moved) == 1, "第1次弃置必须只产生一张牌的card_moved事件"
    assert moved[0].payload["hanbing_step"] == 1
    assert moved[0].payload["window_id"] == step1_window
    assert len(game.state.card_ids_in(ZoneRef.hand("p2"))) == 3, (
        "第1次弃置后目标手牌应只减少1张"
    )
    # 第2张尚未离开：进入第2次弃置窗口，且基于最新权威状态重新枚举
    assert game.phase is ProductionPhase.HANBING_DISCARD
    assert game.runtime.pending_hanbing_discard is not None
    assert game.runtime.pending_hanbing_discard.step == 2
    assert game.runtime.pending_hanbing_discard.window_id != step1_window, (
        "第2次弃置必须使用新的选择窗口"
    )
    step2_actions = [
        a
        for a in game.legal_actions()
        if a.payload.get("operation") == "hanbing_discard_card"
    ]
    assert len(step2_actions) == 3, "第2次枚举必须只包含剩余3张候选"
    _hanbing_discard_one(game)
    moved = [
        e
        for e in game.events
        if e.event_type is EventType.CARD_MOVED
        and e.payload.get("reason") == "hanbing_discard"
    ]
    assert len(moved) == 2, "两张牌必须分两次弃置，不是一次batch"
    assert moved[1].payload["hanbing_step"] == 2
    assert not _damages(game), "寒冰剑防止伤害后不得产生damage事件"
    assert game.state.players_by_id["p2"].hp == 4, "防止路径不得扣减HP"
    prevented = [
        e
        for e in game.events
        if e.event_type is EventType.DAMAGE_PREVENTED
    ]
    assert len(prevented) == 1
    assert prevented[0].payload["modifiers"] == ("hanbing_prevent",)
    # 逐张弃2张后目标手牌从4张变为2张
    assert len(game.state.card_ids_in(ZoneRef.hand("p2"))) == 2
    assert game.phase is ProductionPhase.PLAY
    _assert_conservation(game)


def test_hanbing_pass_continues_normal_damage() -> None:
    game = _fresh(seed=3)
    _equip(game, "sgs_weapon_hanbingjian")
    _put_hand(game, "sgs_basic_sha")
    _use_slash_to_hanbing_window(game)
    _step(game, _action(game, "pass_weapon_choice"))
    damages = _damages(game)
    assert len(damages) == 1
    assert damages[0].amount == 1
    assert game.state.players_by_id["p2"].hp == 3
    assert game.phase is ProductionPhase.PLAY
    _assert_conservation(game)


def test_hanbing_target_one_card_discards_one() -> None:
    """7.3 特殊说明：目标只有1张牌时只能弃1张。"""

    game = _fresh(seed=3)
    _equip(game, "sgs_weapon_hanbingjian")
    for instance_id in list(game.state.card_ids_in(ZoneRef.hand("p2"))):
        game._state = game.state.move_card(instance_id, DISCARD_PILE)
    _put_hand(game, "sgs_basic_shan", player_id="p2")
    _put_hand(game, "sgs_basic_sha")
    _use_slash_to_hanbing_window(game)
    _step(game, _action(game, "weapon_prevent_damage"))
    assert game.phase is ProductionPhase.HANBING_DISCARD
    _hanbing_discard_one(game)
    # 第1张（也是唯一一张）弃置后目标无可弃牌：直接完成，不打开第2次窗口
    assert game.phase is ProductionPhase.PLAY
    assert not _damages(game)
    assert not game.state.card_ids_in(ZoneRef.hand("p2"))
    prevented = [
        e
        for e in game.events
        if e.event_type is EventType.DAMAGE_PREVENTED
    ]
    assert len(prevented) == 1
    assert game.phase is ProductionPhase.PLAY
    _assert_conservation(game)


def test_hanbing_stale_second_step_fails_without_rollback() -> None:
    """第2步stale动作失败关闭：不得回滚已经合法完成的第1次弃置，
    也不得错误地直接完成寒冰剑。"""

    game = _fresh(seed=3)
    _equip(game, "sgs_weapon_hanbingjian")
    _put_hand(game, "sgs_basic_sha")
    _use_slash_to_hanbing_window(game)
    _step(game, _action(game, "weapon_prevent_damage"))
    _hanbing_discard_one(game)
    assert game.phase is ProductionPhase.HANBING_DISCARD
    assert len(game.state.card_ids_in(ZoneRef.hand("p2"))) == 3
    # 使用伪造窗口ID的stale第2步动作
    stale = LegalAction(
        action_type=ActionType.CHOOSE_OPTION,
        actor_id="p1",
        card_instance_id="x",
        target_ids=("p2",),
        payload={
            "operation": "hanbing_discard_card",
            "window_id": "forged-step2",
            "state_hash": "x",
            "step": 2,
            "handle": "h_forged",
        },
        action_id="act_forged_hanbing_step2",
    )
    with pytest.raises(InvalidActionError):
        validate_action(game.state, game._context(), stale, game.registry)
    # 第1次弃置保持合法完成状态：手牌仍3张、弃牌堆已有1张、窗口仍打开
    assert len(game.state.card_ids_in(ZoneRef.hand("p2"))) == 3
    assert game.phase is ProductionPhase.HANBING_DISCARD
    assert game.runtime.pending_hanbing_discard.step == 2
    assert not _damages(game)
    assert game.state.players_by_id["p2"].hp == 4
    _assert_conservation(game)


def test_hanbing_second_step_sees_armor_leave_state_change() -> None:
    """第1张弃置产生装备状态变化（白银狮子离区回复）后，第2次选择
    必须基于更新后的权威状态重新枚举：回复事件在两次弃置之间产生。"""

    game = _fresh(seed=3)
    _equip(game, "sgs_weapon_hanbingjian")
    _equip_armor(game, "sgs_armor_baiyinshizi")
    _set_hp(game, "p2", 3)
    for instance_id in list(game.state.card_ids_in(ZoneRef.hand("p2"))):
        game._state = game.state.move_card(instance_id, DISCARD_PILE)
    _put_hand(game, "sgs_basic_shan", player_id="p2")
    _put_hand(game, "sgs_basic_sha")
    _use_slash_to_hanbing_window(game)
    _step(game, _action(game, "weapon_prevent_damage"))
    # 第1张弃置白银狮子：必须立即触发离区回复
    baiyin = game.state.card_ids_in(
        ZoneRef.equipment("p2", "armor")
    )[0]
    armor_action = next(
        a
        for a in game.legal_actions()
        if a.payload.get("operation") == "hanbing_discard_card"
        and a.card_instance_id == baiyin
    )
    _step(game, armor_action)
    recovered = [
        e
        for e in game.events
        if e.event_type is EventType.ARMOR_RECOVERED
    ]
    assert len(recovered) == 1, "白银狮子第1次弃置离区必须立即回复"
    assert game.state.players_by_id["p2"].hp == 4
    # 第2次窗口基于最新状态枚举：只剩1张手牌候选，不再出现白银狮子
    assert game.phase is ProductionPhase.HANBING_DISCARD
    step2_candidates = [
        a
        for a in game.legal_actions()
        if a.payload.get("operation") == "hanbing_discard_card"
    ]
    assert len(step2_candidates) == 1
    assert step2_candidates[0].card_instance_id in game.state.card_ids_in(
        ZoneRef.hand("p2")
    )
    _hanbing_discard_one(game)
    assert game.phase is ProductionPhase.PLAY
    assert not _damages(game)
    assert not game.state.card_ids_in(ZoneRef.hand("p2"))
    _assert_conservation(game)


# ----------------------------------------------------------------------
# L. 青龙偃月刀（被闪后继续对原目标使用一张杀）
# ----------------------------------------------------------------------


def test_qinglong_continue_slash_after_dodge() -> None:
    game = _fresh(seed=3)
    _equip(game, "sgs_weapon_qinglongyanyuedao")
    _put_hand(game, "sgs_basic_sha")
    _put_hand(game, "sgs_basic_sha")
    _dodge_and_open_weapon_window(game)
    continue_slash = _action(game, "qinglong_use_slash")
    assert continue_slash is not None, "手中有杀时必须出现继续使用杀动作"
    _step(game, continue_slash)
    assert game.phase is ProductionPhase.SLASH_RESPONSE
    _step(game, _action(game, "pass_slash_response"))
    damages = _damages(game)
    assert len(damages) == 1
    assert damages[0].amount == 1
    assert game.phase is ProductionPhase.PLAY
    _assert_conservation(game)


def test_qinglong_pass_after_dodge_no_damage() -> None:
    game = _fresh(seed=3)
    _equip(game, "sgs_weapon_qinglongyanyuedao")
    _put_hand(game, "sgs_basic_sha")
    _put_hand(game, "sgs_basic_sha")
    _dodge_and_open_weapon_window(game)
    _step(game, _action(game, "pass_weapon_choice"))
    assert not _damages(game)
    assert game.phase is ProductionPhase.PLAY
    _assert_conservation(game)


def test_qinglong_no_window_without_slash_in_hand() -> None:
    game = _fresh(seed=3)
    _equip(game, "sgs_weapon_qinglongyanyuedao")
    for instance_id in list(game.state.card_ids_in(ZoneRef.hand("p1"))):
        game._state = game.state.move_card(instance_id, DISCARD_PILE)
    _put_hand(game, "sgs_basic_sha")
    _step(game, _action(game, "use_slash", card_key="sgs_basic_sha"))
    _step(game, _action(game, "play_dodge"))
    assert game.phase is ProductionPhase.PLAY, (
        "手中没有第二张杀时不得打开青龙偃月刀窗口"
    )
    assert not _damages(game)
    _assert_conservation(game)


# ----------------------------------------------------------------------
# M. 青釭剑生命周期（QINGGANG_LIFECYCLE_CONFIRMED）
# ----------------------------------------------------------------------


def test_qinggang_armor_invalid_cleared_after_dodge() -> None:
    """终点A：目标以【闪】完成响应后，本次【杀】的青釭剑防具无效状态
    即清除；后续窗口与独立牌结算不再受本次青釭剑影响。"""

    game = _fresh(seed=3)
    _equip(game, "sgs_weapon_qinggangjian")
    _equip_armor(game, "sgs_armor_renwangdun")
    _put_hand(game, "sgs_basic_sha")
    _step(game, _action(game, "use_slash", card_key="sgs_basic_sha"))
    assert game.runtime.pending_slash is not None
    assert game.runtime.pending_slash.ignore_armor is True
    _step(game, _action(game, "play_dodge"))
    # 闪结算完成后生命周期清除：runtime与窗口快照均不再携带 ignore_armor
    assert game.phase is ProductionPhase.PLAY
    assert game.runtime.pending_slash is None
    _assert_conservation(game)


def test_qinggang_armor_invalid_cleared_after_damage_then_baiyin_recovers() -> None:
    """终点B：本次伤害结算完成后青釭剑防具无效状态清除；随后由正式效果
    （过河拆桥）弃置【白银狮子】时，防具已经恢复正常并触发回复。"""

    game = _fresh(seed=3)
    _equip(game, "sgs_weapon_qinggangjian")
    _equip_armor(game, "sgs_armor_baiyinshizi")
    _put_hand(game, "sgs_basic_sha")
    _use_slash_and_pass(game)
    damages = _damages(game)
    assert len(damages) == 1
    assert damages[0].payload["armor_ignored"] is True
    assert game.phase is ProductionPhase.PLAY
    assert game.runtime.pending_slash is None
    # 伤害结算完成后由后续正式效果（过河拆桥）弃置白银狮子：正常回复
    guohe = next(
        r for r in game.formal_registry.records if r.card_key == "sgs_trick_guohechaiqiao"
    )
    game._state = game.state.move_card(
        guohe.instance_id, ZoneRef.hand("p1")
    )
    _step(game, _action(game, "use_guohe", card_key="sgs_trick_guohechaiqiao"))
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
    recovered = [
        e
        for e in game.events
        if e.event_type is EventType.ARMOR_RECOVERED
    ]
    assert len(recovered) == 1, "青釭剑清除后白银狮子必须正常触发回复"
    assert recovered[0].payload["reason"] == "guohechaiqiao_discard"
    _assert_conservation(game)


    _assert_conservation(game)


def test_gudingdao_no_bonus_when_target_has_hand() -> None:
    game = _fresh(seed=3)
    _equip(game, "sgs_weapon_gudingdao")
    _put_hand(game, "sgs_basic_sha")
    _use_slash_and_pass(game)
    damages = _damages(game)
    assert len(damages) == 1
    assert damages[0].amount == 1
    assert damages[0].payload["weapon_damage_bonus"] == 0


def test_gudingdao_wine_slash_three_without_armor() -> None:
    game = _fresh(seed=3)
    _equip(game, "sgs_weapon_gudingdao")
    for instance_id in list(game.state.card_ids_in(ZoneRef.hand("p2"))):
        game._state = game.state.move_card(instance_id, DISCARD_PILE)
    _put_hand(game, "sgs_basic_jiu")
    _put_hand(game, "sgs_basic_sha")
    _step(game, _action(game, "use_wine_buff", card_key="sgs_basic_jiu"))
    _use_slash_and_pass(game)
    damages = _damages(game)
    assert len(damages) == 1
    assert damages[0].amount == 3  # 酒2 + 古锭1
    assert damages[0].payload["weapon_damage_bonus"] == 1


def test_gudingdao_wine_slash_capped_by_baiyin() -> None:
    game = _fresh(seed=3)
    _equip(game, "sgs_weapon_gudingdao")
    _equip_armor(game, "sgs_armor_baiyinshizi")
    for instance_id in list(game.state.card_ids_in(ZoneRef.hand("p2"))):
        game._state = game.state.move_card(instance_id, DISCARD_PILE)
    _put_hand(game, "sgs_basic_jiu")
    _put_hand(game, "sgs_basic_sha")
    _step(game, _action(game, "use_wine_buff", card_key="sgs_basic_jiu"))
    _use_slash_and_pass(game)
    damages = _damages(game)
    assert len(damages) == 1
    assert damages[0].amount == 1  # 酒2+古锭1=3 → 白银狮子限伤1
    assert damages[0].payload["weapon_damage_bonus"] == 1
    assert "baiyin_cap_one" in damages[0].payload["modifiers"]


# ----------------------------------------------------------------------
# E. 方天画戟（双人生产入口范围）
# ----------------------------------------------------------------------


def test_fangtian_two_player_slice_normal_slash() -> None:
    game = _fresh(seed=3)
    _equip(game, "sgs_weapon_fangtianhuaji")
    _put_hand(game, "sgs_basic_sha")
    assert _action(game, "use_slash", card_key="sgs_basic_sha") is not None
    _use_slash_and_pass(game)
    assert _damages(game)
    _assert_conservation(game)


# ----------------------------------------------------------------------
# F. 跨系统：距离、动作安全、守恒、回放、隐私
# ----------------------------------------------------------------------


def test_weapon_attack_range_applies_to_slash_legality() -> None:
    game = _fresh(seed=3)
    _equip(game, "sgs_weapon_qinggangjian")  # 攻击范围2
    assert attack_range_of(game.state, "p1") == 2
    _put_hand(game, "sgs_basic_sha")
    # 双人相邻距离1 ≤ 2：合法
    assert _action(game, "use_slash", card_key="sgs_basic_sha") is not None


def test_weapon_forged_slash_damage_payload_rejected() -> None:
    game = _fresh(seed=3)
    _equip(game, "sgs_weapon_gudingdao")
    for instance_id in list(game.state.card_ids_in(ZoneRef.hand("p2"))):
        game._state = game.state.move_card(instance_id, DISCARD_PILE)
    _put_hand(game, "sgs_basic_sha")
    _step(game, _action(game, "use_slash", card_key="sgs_basic_sha"))
    # 客户端不得直接提交伤害结果/武器修正
    forged = LegalAction(
        action_type=ActionType.PASS,
        actor_id="p2",
        payload={
            "operation": "pass_slash_response",
            "damage_amount": 9,
            "weapon_damage_bonus": 99,
        },
        action_id="act_forged_weapon_damage",
    )
    with pytest.raises(InvalidActionError):
        validate_action(game.state, game._context(), forged, game.registry)
    # 伪造 ignore_armor=true 也不能直接提交
    forged_armor = LegalAction(
        action_type=ActionType.PASS,
        actor_id="p2",
        payload={
            "operation": "pass_slash_response",
            "ignore_armor": True,
        },
        action_id="act_forged_ignore_armor",
    )
    with pytest.raises(InvalidActionError):
        validate_action(
            game.state, game._context(), forged_armor, game.registry
        )


def test_partial_weapons_stay_fail_closed() -> None:
    from scripts.sgs_engine.production_cards import check_weapon_skill_gate

    # 雌雄双股剑（PARTIAL）：性别数据缺失，对另一角色使用杀失败关闭
    game1 = _fresh(seed=3)
    _equip(game1, "sgs_weapon_cixiongshuanggujian")
    _put_hand(game1, "sgs_basic_sha")
    with pytest.raises(UnsupportedRuleError):
        check_weapon_skill_gate(
            game1.state, actor_id="p1", decision="use_slash", target_id="p2"
        )
    # 丈八蛇矛（PARTIAL）：subcard生命周期时点规则缺口，手牌>=2时失败关闭
    game2 = _fresh(seed=3)
    _equip(game2, "sgs_weapon_zhangbashemao")
    with pytest.raises(UnsupportedRuleError):
        check_weapon_skill_gate(
            game2.state, actor_id="p1", decision="use_slash", target_id="p2"
        )


def test_weapon_skills_replay_reexecutes() -> None:
    record = record_reference_production_batch(seed=3)
    assert record.outcome["step_count"] > 0
    result = reexecute_production_replay(record)
    assert result.verified is True
    assert result.winner_id == record.outcome["winner_id"]


def test_replay_weapon_damage_tamper_rejected() -> None:
    record = record_reference_production_batch(seed=3)
    tampered = copy.deepcopy(record.to_dict())
    damage_event = next(
        event
        for event in tampered["events"]
        if event.get("event_type") == "damage"
    )
    damage_event["payload"]["armor_ignored"] = not damage_event["payload"].get(
        "armor_ignored", False
    )
    del tampered["record_sha256"]
    with pytest.raises(
        (ProductionReplayFormatError, ProductionReplayDivergenceError)
    ):
        reexecute_production_replay(
            ProductionReexecutionReplay.from_dict(tampered)
        )


def test_weapon_card_conservation_after_skill_paths() -> None:
    game = _fresh(seed=3)
    _equip(game, "sgs_weapon_qinggangjian")
    _equip_armor(game, "sgs_armor_renwangdun")
    _put_hand(game, "sgs_basic_sha")
    _use_slash_and_pass(game)
    _assert_conservation(game)
    game2 = _fresh(seed=3)
    _equip(game2, "sgs_weapon_gudingdao")
    for instance_id in list(game2.state.card_ids_in(ZoneRef.hand("p2"))):
        game2._state = game2.state.move_card(instance_id, DISCARD_PILE)
    _put_hand(game2, "sgs_basic_sha")
    _use_slash_and_pass(game2)
    _assert_conservation(game2)


# ----------------------------------------------------------------------
# G. 麒麟弓（伤害后弃坐骑）
# ----------------------------------------------------------------------


def _use_slash_to_damage(
    game: ProductionBasicCardBatch,
) -> ProductionBasicCardBatch:
    _step(game, _action(game, "use_slash", card_key="sgs_basic_sha"))
    _step(game, _action(game, "pass_slash_response"))
    return game


def test_qilingong_discards_target_mount_after_damage() -> None:
    """麒麟弓窗口在本次伤害真正结算、HP扣减之前打开（USER_CONFIRMED_
    MOBILE_RULE＋IN_GAME_CARD_TEXT_CONFIRMED）：弃坐骑完成 → HP扣减/DAMAGE。
    事件顺序必须为：麒麟弓坐骑移动/失牌 → DAMAGE → HP最终状态。"""

    game = _fresh(seed=3)
    _equip(game, "sgs_weapon_qilingong")
    mount = next(
        r for r in game.formal_registry.records if r.card_key == "sgs_mount_offensive"
    )
    game._state = game.state.move_card(
        mount.instance_id, ZoneRef.equipment("p2", "attack_horse")
    )
    _put_hand(game, "sgs_basic_sha")
    _use_slash_to_damage(game)
    assert game.phase is ProductionPhase.WEAPON_AFTER_DAMAGE
    # 窗口打开时：HP尚未扣减、DAMAGE事件尚未产生
    assert game.state.players_by_id["p2"].hp == 4, (
        "麒麟弓窗口必须出现在HP扣减之前"
    )
    assert not _damages(game), "麒麟弓窗口打开时不得已有DAMAGE事件"
    discard = _action(game, "weapon_discard_mount")
    assert discard is not None and discard.card_instance_id == mount.instance_id
    _step(game, discard)
    # 弃坐骑完成后：坐骑移动/失牌事件先于DAMAGE事件
    mount_events = [
        e
        for e in game.events
        if e.card_instance_id == mount.instance_id
        and e.event_type in (EventType.CARD_MOVED, EventType.CARD_LOST)
        and e.payload.get("reason") == "qilingong_mount_discard"
    ]
    damages = _damages(game)
    assert len(mount_events) == 2
    assert len(damages) == 1 and damages[0].amount == 1
    assert max(e.sequence for e in mount_events) < damages[0].sequence, (
        "坐骑移动/失牌事件必须先于DAMAGE事件"
    )
    assert mount.instance_id in game.state.card_ids_in(DISCARD_PILE)
    assert game.state.players_by_id["p2"].hp == 3
    assert game.phase is ProductionPhase.PLAY
    _assert_conservation(game)


def test_qilingong_pass_keeps_mount() -> None:
    game = _fresh(seed=3)
    _equip(game, "sgs_weapon_qilingong")
    mount = next(
        r for r in game.formal_registry.records if r.card_key == "sgs_mount_defensive"
    )
    game._state = game.state.move_card(
        mount.instance_id, ZoneRef.equipment("p2", "defense_horse")
    )
    _put_hand(game, "sgs_basic_sha")
    _use_slash_to_damage(game)
    assert game.phase is ProductionPhase.WEAPON_AFTER_DAMAGE
    # 放弃窗口时HP尚未扣减、无DAMAGE
    assert game.state.players_by_id["p2"].hp == 4
    assert not _damages(game)
    _step(game, _action(game, "pass_weapon_choice"))
    assert mount.instance_id in game.state.card_ids_in(
        ZoneRef.equipment("p2", "defense_horse")
    )
    # 放弃后进入真正伤害结算：HP扣减+DAMAGE
    damages = _damages(game)
    assert len(damages) == 1 and damages[0].amount == 1
    assert game.state.players_by_id["p2"].hp == 3
    assert game.phase is ProductionPhase.PLAY
    _assert_conservation(game)


def test_qilingong_dying_after_mount_then_damage() -> None:
    """目标1HP：麒麟弓先处理 → 再扣到0 → 再进入DYING。"""

    game = _fresh(seed=3)
    _equip(game, "sgs_weapon_qilingong")
    _set_hp(game, "p2", 1)
    mount = next(
        r for r in game.formal_registry.records if r.card_key == "sgs_mount_defensive"
    )
    game._state = game.state.move_card(
        mount.instance_id, ZoneRef.equipment("p2", "defense_horse")
    )
    _put_hand(game, "sgs_basic_sha")
    _use_slash_to_damage(game)
    assert game.phase is ProductionPhase.WEAPON_AFTER_DAMAGE
    assert game.state.players_by_id["p2"].hp == 1
    assert not _damages(game)
    discard = _action(game, "weapon_discard_mount")
    assert discard is not None
    _step(game, discard)
    assert mount.instance_id in game.state.card_ids_in(DISCARD_PILE)
    damages = _damages(game)
    assert len(damages) == 1 and damages[0].amount == 1
    assert game.state.players_by_id["p2"].hp == 0
    assert game.phase is ProductionPhase.DYING_RESCUE, (
        "麒麟弓处理完成后扣到0，再进入DYING"
    )
    _assert_conservation(game)


def test_qilingong_pass_then_dying() -> None:
    """目标1HP且放弃麒麟弓：放弃窗口结束 → damage → dying。"""

    game = _fresh(seed=3)
    _equip(game, "sgs_weapon_qilingong")
    _set_hp(game, "p2", 1)
    mount = next(
        r for r in game.formal_registry.records if r.card_key == "sgs_mount_defensive"
    )
    game._state = game.state.move_card(
        mount.instance_id, ZoneRef.equipment("p2", "defense_horse")
    )
    _put_hand(game, "sgs_basic_sha")
    _use_slash_to_damage(game)
    assert game.phase is ProductionPhase.WEAPON_AFTER_DAMAGE
    _step(game, _action(game, "pass_weapon_choice"))
    assert mount.instance_id in game.state.card_ids_in(
        ZoneRef.equipment("p2", "defense_horse")
    )
    assert len(_damages(game)) == 1
    assert game.state.players_by_id["p2"].hp == 0
    assert game.phase is ProductionPhase.DYING_RESCUE
    _assert_conservation(game)


def test_qilingong_no_window_when_target_has_no_mount() -> None:
    game = _fresh(seed=3)
    _equip(game, "sgs_weapon_qilingong")
    _put_hand(game, "sgs_basic_sha")
    _use_slash_to_damage(game)
    assert game.phase is ProductionPhase.PLAY, (
        "目标无坐骑时不打开麒麟弓窗口"
    )
    assert _damages(game)


def test_qilingong_forged_and_cross_player_rejected() -> None:
    game = _fresh(seed=3)
    _equip(game, "sgs_weapon_qilingong")
    mount = next(
        r for r in game.formal_registry.records if r.card_key == "sgs_mount_offensive"
    )
    game._state = game.state.move_card(
        mount.instance_id, ZoneRef.equipment("p2", "attack_horse")
    )
    _put_hand(game, "sgs_basic_sha")
    _use_slash_to_damage(game)
    assert game.phase is ProductionPhase.WEAPON_AFTER_DAMAGE
    # 非武器持有者不能弃坐骑
    forged = LegalAction(
        action_type=ActionType.MOVE_CARD,
        actor_id="p2",
        card_instance_id=mount.instance_id,
        target_ids=("p2",),
        payload={
            "operation": "weapon_discard_mount",
            "card_key": "sgs_mount_offensive",
            "window_id": "forged",
        },
        action_id="act_forged_qilingong",
    )
    with pytest.raises(InvalidActionError):
        validate_action(game.state, game._context(), forged, game.registry)
    # 伪造窗口ID的放弃动作被拒绝
    forged_pass = LegalAction(
        action_type=ActionType.PASS,
        actor_id="p1",
        payload={
            "operation": "pass_weapon_choice",
            "window_id": "forged-window",
        },
        action_id="act_forged_pass_weapon",
    )
    with pytest.raises(InvalidActionError):
        validate_action(
            game.state, game._context(), forged_pass, game.registry
        )


# ----------------------------------------------------------------------
# H. 朱雀羽扇（普通杀转火杀）
# ----------------------------------------------------------------------


def test_zhuque_converts_plain_slash_to_fire_damage() -> None:
    game = _fresh(seed=3)
    _equip(game, "sgs_weapon_zhuqueyushan")
    _put_hand(game, "sgs_basic_sha")
    converted = next(
        a
        for a in game.legal_actions()
        if a.payload.get("operation") == "use_slash"
        and a.payload.get("converted_to_fire") is True
    )
    _step(game, converted)
    _step(game, _action(game, "pass_slash_response"))
    damages = _damages(game)
    assert len(damages) == 1
    assert damages[0].damage_type == "火属性"
    assert damages[0].payload["armor_ignored"] is False
    _assert_conservation(game)


def test_zhuque_unconverted_slash_stays_plain() -> None:
    game = _fresh(seed=3)
    _equip(game, "sgs_weapon_zhuqueyushan")
    _put_hand(game, "sgs_basic_sha")
    plain = next(
        a
        for a in game.legal_actions()
        if a.payload.get("operation") == "use_slash"
        and a.payload.get("converted_to_fire") is None
    )
    _step(game, plain)
    _step(game, _action(game, "pass_slash_response"))
    damages = _damages(game)
    assert len(damages) == 1
    assert damages[0].damage_type == "无属性"


def test_zhuque_does_not_convert_elemental_slash() -> None:
    game = _fresh(seed=3)
    _equip(game, "sgs_weapon_zhuqueyushan")
    _put_hand(game, "sgs_basic_leisha")
    actions = [
        a
        for a in game.legal_actions()
        if a.payload.get("operation") == "use_slash"
    ]
    assert all(
        a.payload.get("converted_to_fire") is None
        and a.payload.get("card_key") == "sgs_basic_leisha"
        for a in actions
    )


def test_zhuque_converted_fire_slash_ignores_tengjia_immunity() -> None:
    """转火杀不是普通杀：藤甲不再免疫，但火属性伤害+1生效。"""
    game = _fresh(seed=3)
    _equip(game, "sgs_weapon_zhuqueyushan")
    _equip_armor(game, "sgs_armor_tengjia")
    _put_hand(game, "sgs_basic_sha")
    converted = next(
        a
        for a in game.legal_actions()
        if a.payload.get("operation") == "use_slash"
        and a.payload.get("converted_to_fire") is True
    )
    _step(game, converted)
    assert game.phase is ProductionPhase.SLASH_RESPONSE, (
        "转火杀不被藤甲免疫，必须进入响应窗口"
    )
    _step(game, _action(game, "pass_slash_response"))
    damages = _damages(game)
    assert len(damages) == 1
    assert damages[0].damage_type == "火属性"
    assert damages[0].amount == 2  # 1 + 藤甲火属性+1
    assert "tengjia_fire_plus_one" in damages[0].payload["modifiers"]


# ----------------------------------------------------------------------
# I. 古锭刀触发时机（“使用【杀】时”判定，非“造成伤害时”）
# ----------------------------------------------------------------------


def test_gudingdao_bonus_when_target_handless_at_damage_time() -> None:
    """目标从指定到伤害全程0手牌：造成伤害时判定成立，伤害+1。"""
    game = _fresh(seed=3)
    _equip(game, "sgs_weapon_gudingdao")
    for instance_id in list(game.state.card_ids_in(ZoneRef.hand("p2"))):
        game._state = game.state.move_card(instance_id, DISCARD_PILE)
    _put_hand(game, "sgs_basic_sha")
    _use_slash_and_pass(game)
    damages = _damages(game)
    assert len(damages) == 1
    assert damages[0].amount == 2
    assert damages[0].payload["weapon_damage_bonus"] == 1


def test_gudingdao_no_bonus_when_target_gains_hand_before_damage() -> None:
    """核心回归（用户移动版实测：神甘宁古锭刀杀势王昶，指定后伤害前
    目标因技能获得1张手牌→伤害时1手牌→古锭刀不+1，只受1点伤害）。
    当前引擎无武将技能系统，用最小的正式 damage-window 状态边界构造：
    响应窗口内（伤害前）把一张牌移入目标手牌。"""

    game = _fresh(seed=3)
    _equip(game, "sgs_weapon_gudingdao")
    for instance_id in list(game.state.card_ids_in(ZoneRef.hand("p2"))):
        game._state = game.state.move_card(instance_id, DISCARD_PILE)
    _put_hand(game, "sgs_basic_sha")
    _step(game, _action(game, "use_slash", card_key="sgs_basic_sha"))
    assert game.phase is ProductionPhase.SLASH_RESPONSE
    # 指定目标时0手牌；伤害前通过正式状态变化获得1张手牌
    assert not game.state.card_ids_in(ZoneRef.hand("p2"))
    gained = next(
        r for r in game.formal_registry.records if r.card_key == "sgs_basic_shan"
    )
    game._state = game.state.move_card(
        gained.instance_id, ZoneRef.hand("p2")
    )
    _step(game, _action(game, "pass_slash_response"))
    damages = _damages(game)
    assert len(damages) == 1
    assert damages[0].amount == 1, "伤害时目标有1张手牌：古锭刀不得+1"
    assert damages[0].payload["weapon_damage_bonus"] == 0
    assert game.state.players_by_id["p2"].hp == 3
    _assert_conservation(game)


def test_gudingdao_bonus_when_target_loses_last_hand_before_damage() -> None:
    """指定目标时有手牌、伤害发生前失去最后1张→伤害时0手牌→+1。
    用最小的正式 damage-window 状态边界构造（模拟伤害前目标失去手牌的
    合法技能路径；不伪造“闪后仍造成伤害”的不可能路径）。"""

    game = _fresh(seed=3)
    _equip(game, "sgs_weapon_gudingdao")
    for instance_id in list(game.state.card_ids_in(ZoneRef.hand("p2"))):
        game._state = game.state.move_card(instance_id, DISCARD_PILE)
    _put_hand(game, "sgs_basic_shan", player_id="p2")
    _put_hand(game, "sgs_basic_sha")
    _step(game, _action(game, "use_slash", card_key="sgs_basic_sha"))
    assert game.phase is ProductionPhase.SLASH_RESPONSE
    # 指定时1手牌；伤害前失去最后1张
    last = game.state.card_ids_in(ZoneRef.hand("p2"))[0]
    game._state = game.state.move_card(last, DISCARD_PILE)
    assert not game.state.card_ids_in(ZoneRef.hand("p2"))
    _step(game, _action(game, "pass_slash_response"))
    damages = _damages(game)
    assert len(damages) == 1
    assert damages[0].amount == 2, "伤害时目标0手牌：古锭刀必须+1"
    assert damages[0].payload["weapon_damage_bonus"] == 1
    _assert_conservation(game)


def test_gudingdao_replay_weapon_bonus_matches_damage_time_state() -> None:
    """replay 中 weapon_damage_bonus 与伤害时权威状态一致；篡改该值被
    strict replay 拒绝。"""

    def fixture(game: ProductionBasicCardBatch) -> None:
        _equip(game, "sgs_weapon_gudingdao")
        for instance_id in list(game.state.card_ids_in(ZoneRef.hand("p2"))):
            game._state = game.state.move_card(instance_id, DISCARD_PILE)

    class _SlashController(BatchReferenceController):
        strategy_version = "production-batch-gudingdao-controller.v1"

        def choose(self, legal_actions, context):
            for action in legal_actions:
                if action.payload.get("operation") == "use_slash":
                    return action
            return super().choose(legal_actions, context)

    record = record_reference_production_batch(
        seed=3, fixture=fixture, controller=_SlashController()
    )
    damage = next(
        event
        for event in record.events
        if event.get("event_type") == "damage"
    )
    assert damage["payload"]["weapon_damage_bonus"] == 1
    assert damage["payload"]["final_amount"] == 2
    result = reexecute_production_replay(record, fixture=fixture)
    assert result.verified is True
    # 篡改 weapon_damage_bonus：重执行必须发散拒绝
    tampered = copy.deepcopy(record.to_dict())
    tampered_damage = next(
        event
        for event in tampered["events"]
        if event.get("event_type") == "damage"
    )
    tampered_damage["payload"]["weapon_damage_bonus"] = 99
    del tampered["record_sha256"]
    with pytest.raises(
        (ProductionReplayFormatError, ProductionReplayDivergenceError)
    ):
        reexecute_production_replay(
            ProductionReexecutionReplay.from_dict(tampered), fixture=fixture
        )


# ----------------------------------------------------------------------
# N. 青龙偃月刀追杀不消耗普通出牌阶段【杀】次数额度
#    （USER_CONFIRMED_MOBILE_RULE，2026-08-08 用户移动版实测确认）
# ----------------------------------------------------------------------


def test_qinglong_chase_does_not_consume_slash_quota() -> None:
    """正常使用第1张杀（消耗额度）→被闪→青龙追出第2张杀：
    追杀不额外消耗普通出牌阶段额度，额度保持第1张后的值。"""

    game = _fresh(seed=3)
    _equip(game, "sgs_weapon_qinglongyanyuedao")
    _put_hand(game, "sgs_basic_sha")
    _put_hand(game, "sgs_basic_sha")
    # 1. 正常使用第1张杀：消耗正常额度
    _step(game, _action(game, "use_slash", card_key="sgs_basic_sha"))
    assert game.runtime.slash_used_counts["p1"] == 1
    # 2. 对方使用闪
    _step(game, _action(game, "play_dodge"))
    assert game.phase is ProductionPhase.WEAPON_SLASH_CHOICE
    # 3. 青龙追出第2张杀
    _step(game, _action(game, "qinglong_use_slash"))
    assert game.phase is ProductionPhase.SLASH_RESPONSE
    # 4. 追杀不额外消耗正常额度
    assert game.runtime.slash_used_counts["p1"] == 1
    # 完成追杀结算（目标放弃响应→伤害）
    _step(game, _action(game, "pass_slash_response"))
    assert _damages(game)
    # 5. 追杀后额度状态符合规则：仍为1（未因追杀变成2/3）
    assert game.runtime.slash_used_counts["p1"] == 1
    assert game.phase is ProductionPhase.PLAY
    _assert_conservation(game)


def test_qinglong_chase_no_residual_quota_lock() -> None:
    """额外正常出杀权限/额度重置构造下，普通杀额度状态符合规则：
    追杀不产生残留锁定，手牌其他杀恢复可正常使用。"""

    game = _fresh(seed=3)
    _equip(game, "sgs_weapon_qinglongyanyuedao")
    _put_hand(game, "sgs_basic_sha")
    _put_hand(game, "sgs_basic_sha")
    _step(game, _action(game, "use_slash", card_key="sgs_basic_sha"))
    _step(game, _action(game, "play_dodge"))
    _step(game, _action(game, "qinglong_use_slash"))
    _step(game, _action(game, "pass_slash_response"))
    assert game.phase is ProductionPhase.PLAY
    assert game.runtime.slash_used_counts["p1"] == 1
    from dataclasses import replace
    from types import MappingProxyType

    # 模拟下一出牌阶段开始/额外正常出杀权限：普通出杀额度重置为0
    game._runtime = replace(
        game._runtime, slash_used_counts=MappingProxyType({"p1": 0})
    )
    # 手牌其他杀恢复可正常使用状态（不残留锁定）
    assert any(
        a.payload.get("operation") == "use_slash"
        for a in game.legal_actions()
    ), "手牌其他杀必须恢复可正常使用状态"
    _assert_conservation(game)


def test_qinglong_chase_chain_no_quota_consumption() -> None:
    """6-7. 青龙追杀再次被闪后可以继续发动青龙；每一张追杀都不消耗
    普通PLAY阶段杀额度。"""

    game = _fresh(seed=3)
    _equip(game, "sgs_weapon_qinglongyanyuedao")
    _put_hand(game, "sgs_basic_sha")
    _put_hand(game, "sgs_basic_sha")
    _put_hand(game, "sgs_basic_sha")
    _put_hand(game, "sgs_basic_shan", player_id="p2")
    _put_hand(game, "sgs_basic_shan", player_id="p2")
    # 第1张正常杀
    _step(game, _action(game, "use_slash", card_key="sgs_basic_sha"))
    # 被闪 → 第2张（第一次追杀）
    _step(game, _action(game, "play_dodge"))
    assert game.phase is ProductionPhase.WEAPON_SLASH_CHOICE
    _step(game, _action(game, "qinglong_use_slash"))
    assert game.runtime.slash_used_counts["p1"] == 1
    # 第2张（追杀）再次被闪 → 第3张（第二次追杀）
    _step(game, _action(game, "play_dodge"))
    assert game.phase is ProductionPhase.WEAPON_SLASH_CHOICE, (
        "青龙追杀再次被闪后必须可以继续发动青龙"
    )
    _step(game, _action(game, "qinglong_use_slash"))
    assert game.phase is ProductionPhase.SLASH_RESPONSE
    # 两次追杀都不消耗额度：额度仍为第1张正常杀后的值
    assert game.runtime.slash_used_counts["p1"] == 1
    _step(game, _action(game, "pass_slash_response"))
    assert _damages(game)
    assert game.runtime.slash_used_counts["p1"] == 1
    assert game.phase is ProductionPhase.PLAY
    _assert_conservation(game)


def test_qinglong_chase_each_is_real_use_not_duplicate() -> None:
    """8. 每一张追杀都是真实CARD_USED/Slash结算，不得伪装成同一张杀
    重复结算：两次使用事件实体不同、追杀独立完成伤害。"""

    game = _fresh(seed=3)
    _equip(game, "sgs_weapon_qinglongyanyuedao")
    _put_hand(game, "sgs_basic_sha")
    _put_hand(game, "sgs_basic_sha")
    _step(game, _action(game, "use_slash", card_key="sgs_basic_sha"))
    first_slash_id = game.runtime.pending_slash.slash_instance_id
    _step(game, _action(game, "play_dodge"))
    _step(game, _action(game, "qinglong_use_slash"))
    chase_slash_id = game.runtime.pending_slash.slash_instance_id
    assert chase_slash_id != first_slash_id
    used_events = [
        e
        for e in game.events
        if e.event_type is EventType.CARD_USED
        and e.card_user == "p1"
        and e.card_instance_id in (first_slash_id, chase_slash_id)
    ]
    assert len(used_events) == 2, "两张杀必须各有独立CARD_USED事件"
    assert {e.card_instance_id for e in used_events} == {
        first_slash_id,
        chase_slash_id,
    }
    _step(game, _action(game, "pass_slash_response"))
    damages = _damages(game)
    assert len(damages) == 1
    assert damages[0].card_instance_id == chase_slash_id
    assert game.phase is ProductionPhase.PLAY
    _assert_conservation(game)


# ----------------------------------------------------------------------
# O. 贯石斧自身不能作为发动代价
#    （USER_CONFIRMED_MOBILE_RULE，2026-08-08 用户移动版实测确认）
# ----------------------------------------------------------------------


def test_guanshifu_self_excluded_from_candidates() -> None:
    """贯石斧自身不出现在合法候选集合；伪造提交贯石斧自身失败关闭。"""

    game = _fresh(seed=3)
    guanshifu_id = _equip(game, "sgs_weapon_guanshifu")
    _put_hand(game, "sgs_basic_sha")
    _dodge_and_open_weapon_window(game)
    _step(game, _action(game, "weapon_force_hit"))
    assert game.phase is ProductionPhase.WEAPON_DISCARD_TWO
    select_actions = [
        a
        for a in game.legal_actions()
        if a.payload.get("operation") == "select_discard_two"
    ]
    assert select_actions, "贯石斧窗口必须提供合法候选"
    assert all(
        a.card_instance_id != guanshifu_id for a in select_actions
    ), "贯石斧自身不得出现在合法候选"
    assert all(
        a.payload.get("zone") != "equipment:weapon" for a in select_actions
    ), "武器槽不得作为弃置候选"
    # 伪造提交贯石斧自身：动作不在合法集合，失败关闭
    forged = LegalAction(
        action_type=ActionType.MOVE_CARD,
        actor_id="p1",
        card_instance_id=guanshifu_id,
        target_ids=("p1",),
        payload={
            "operation": "select_discard_two",
            "zone": "equipment:weapon",
            "card_key": "sgs_weapon_guanshifu",
            "window_id": "forged",
            "state_hash": "forged",
        },
        action_id="act_forged_guanshifu_self",
    )
    with pytest.raises(InvalidActionError):
        validate_action(game.state, game._context(), forged, game.registry)
    # 状态不变：贯石斧仍在武器槽，窗口保持打开
    assert guanshifu_id in game.state.card_ids_in(
        ZoneRef.equipment("p1", "weapon")
    )
    assert game.phase is ProductionPhase.WEAPON_DISCARD_TWO
    _assert_conservation(game)


def test_guanshifu_self_plus_other_rejected_state_unchanged() -> None:
    """贯石斧自身＋另一张牌组合失败且状态不变（原子失败关闭）。"""

    game = _fresh(seed=3)
    guanshifu_id = _equip(game, "sgs_weapon_guanshifu")
    hand_before = tuple(game.state.card_ids_in(ZoneRef.hand("p1")))
    _put_hand(game, "sgs_basic_sha")
    _dodge_and_open_weapon_window(game)
    _step(game, _action(game, "weapon_force_hit"))
    # 先选择一张合法手牌（选择过程不移动牌）
    hand_action = next(
        a
        for a in game.legal_actions()
        if a.payload.get("operation") == "select_discard_two"
        and a.payload.get("zone", "hand") == "hand"
    )
    _step(game, hand_action)
    # 伪造选择贯石斧自身作为第二张代价：失败关闭
    forged = LegalAction(
        action_type=ActionType.MOVE_CARD,
        actor_id="p1",
        card_instance_id=guanshifu_id,
        target_ids=("p1",),
        payload={
            "operation": "select_discard_two",
            "zone": "equipment:weapon",
            "card_key": "sgs_weapon_guanshifu",
            "window_id": "forged",
            "state_hash": "forged",
        },
        action_id="act_forged_guanshifu_self_2",
    )
    with pytest.raises(InvalidActionError):
        validate_action(game.state, game._context(), forged, game.registry)
    # 状态不变：手牌/武器槽/弃牌堆均无变化，任何牌都没有移动
    assert tuple(game.state.card_ids_in(ZoneRef.hand("p1"))) == hand_before
    assert guanshifu_id in game.state.card_ids_in(
        ZoneRef.equipment("p1", "weapon")
    )
    assert not any(
        e.event_type is EventType.CARD_MOVED
        and e.payload.get("reason") == "guanshifu_discard"
        for e in game.events
    )
    assert game.phase is ProductionPhase.WEAPON_DISCARD_TWO
    _assert_conservation(game)


def test_guanshifu_hand_plus_other_equipment_as_costs() -> None:
    """手牌＋其他装备可以作为两张代价；合法两张仍一次批量弃置并令杀
    造成伤害；贯石斧自身保留在武器槽。"""

    game = _fresh(seed=3)
    guanshifu_id = _equip(game, "sgs_weapon_guanshifu")
    mount = next(
        r
        for r in game.formal_registry.records
        if r.card_key == "sgs_mount_defensive"
    )
    game._state = game.state.move_card(
        mount.instance_id, ZoneRef.equipment("p1", "defense_horse")
    )
    _put_hand(game, "sgs_basic_sha")
    _dodge_and_open_weapon_window(game)
    _step(game, _action(game, "weapon_force_hit"))
    assert game.phase is ProductionPhase.WEAPON_DISCARD_TWO
    # 选择装备区坐骑＋一张手牌
    mount_action = next(
        a
        for a in game.legal_actions()
        if a.payload.get("operation") == "select_discard_two"
        and a.card_instance_id == mount.instance_id
    )
    _step(game, mount_action)
    hand_action = next(
        a
        for a in game.legal_actions()
        if a.payload.get("operation") == "select_discard_two"
        and a.payload.get("zone", "hand") == "hand"
    )
    _step(game, hand_action)
    _step(game, _action(game, "discard_two_submit"))
    # 两张代价一次批量弃置：同一窗口ID下的两个CARD_MOVED事件
    moved = [
        e
        for e in game.events
        if e.event_type is EventType.CARD_MOVED
        and e.payload.get("reason") == "guanshifu_discard"
    ]
    assert len(moved) == 2
    assert len({e.payload.get("window_id") for e in moved}) == 1
    # 贯石斧自身保留在武器槽；坐骑与手牌进入弃牌堆
    assert guanshifu_id in game.state.card_ids_in(
        ZoneRef.equipment("p1", "weapon")
    )
    assert mount.instance_id in game.state.card_ids_in(DISCARD_PILE)
    # 强制命中造成伤害
    damages = _damages(game)
    assert len(damages) == 1
    assert damages[0].amount == 1
    assert game.phase is ProductionPhase.PLAY
    _assert_conservation(game)


def test_guanshifu_no_window_when_only_self_and_one_hand_card() -> None:
    """贯石斧自身不作为代价计数：使用杀后只剩1张手牌＋贯石斧自身时，
    可弃代价只有1张，不得打开贯石斧窗口。"""

    game = _fresh(seed=3)
    _equip(game, "sgs_weapon_guanshifu")
    for instance_id in list(game.state.card_ids_in(ZoneRef.hand("p1"))):
        game._state = game.state.move_card(instance_id, DISCARD_PILE)
    _put_hand(game, "sgs_basic_sha")
    _put_hand(game, "sgs_basic_sha")
    _step(game, _action(game, "use_slash", card_key="sgs_basic_sha"))
    _step(game, _action(game, "play_dodge"))
    assert game.phase is ProductionPhase.PLAY, (
        "只剩贯石斧自身＋1张手牌时不得打开贯石斧窗口"
    )
    assert not _damages(game)
    _assert_conservation(game)


def test_guanshifu_submit_authoritative_rejects_self() -> None:
    """submit 时权威再次验证（不能只依赖枚举阶段曾经排除）：即使待弃
    集合被构造为包含贯石斧自身，提交也失败关闭且整批不移动。"""

    game = _fresh(seed=3)
    guanshifu_id = _equip(game, "sgs_weapon_guanshifu")
    _put_hand(game, "sgs_basic_sha")
    _dodge_and_open_weapon_window(game)
    _step(game, _action(game, "weapon_force_hit"))
    assert game.phase is ProductionPhase.WEAPON_DISCARD_TWO
    hand_id = game.state.card_ids_in(ZoneRef.hand("p1"))[0]
    from dataclasses import replace
    from types import MappingProxyType

    discard_two = game.runtime.pending_discard_two
    game._runtime = replace(
        game._runtime,
        pending_discard_two=replace(
            discard_two,
            selected_ids=(hand_id, guanshifu_id),
            selected_zones=MappingProxyType(
                {
                    hand_id: "hand",
                    guanshifu_id: "equipment:weapon",
                }
            ),
        ),
    )
    submit = _action(game, "discard_two_submit")
    assert submit is not None
    with pytest.raises(InvalidActionError):
        game.apply_discard_two_submit(game.state, game._context(), submit)
    # 状态不变：任何牌都没有移动
    assert guanshifu_id in game.state.card_ids_in(
        ZoneRef.equipment("p1", "weapon")
    )
    assert hand_id in game.state.card_ids_in(ZoneRef.hand("p1"))
    assert not any(
        e.event_type is EventType.CARD_MOVED
        and e.payload.get("reason") == "guanshifu_discard"
        for e in game.events
    )
    assert game.phase is ProductionPhase.WEAPON_DISCARD_TWO
    _assert_conservation(game)


# ----------------------------------------------------------------------
# G-003 修复：丈八统一 fail-closed（WHOLE_REPO_AUDIT_REMEDIATION_1）
# ----------------------------------------------------------------------


def _zhangba_non_slash_hand(game, player_id: str) -> None:
    """清空该角色手牌并放入两张非实体杀手牌（满足材料数量但无实体杀）。"""
    for instance_id in list(game.state.card_ids_in(ZoneRef.hand(player_id))):
        game._state = game.state.move_card(instance_id, DISCARD_PILE)
    for key in ("sgs_basic_shan", "sgs_basic_tao"):
        record = next(r for r in game.formal_registry.records if r.card_key == key)
        game._state = game.state.move_card(
            record.instance_id, ZoneRef.hand(player_id)
        )


def test_zhangba_play_public_legal_actions_fails_closed() -> None:
    """装备丈八＋两张非实体杀手牌：出牌阶段 public legal_actions 必须以
    PARTIAL/UnsupportedRule 边界失败关闭，而不是生成 virtual:zhangba:*
    candidate 后撞公共实体验证器。"""
    game = _fresh(seed=3)
    _equip(game, "sgs_weapon_zhangbashemao")
    _zhangba_non_slash_hand(game, "p1")
    with pytest.raises(UnsupportedRuleError):
        game.legal_actions()
    _assert_conservation(game)


def test_zhangba_duel_public_legal_actions_fails_closed() -> None:
    """响应【决斗】时装备丈八＋两张非实体杀手牌：决斗响应 public
    legal_actions 必须在枚举 virtual proposal 之前直接失败关闭。"""
    game = _fresh(seed=3)
    _equip(game, "sgs_weapon_zhangbashemao", "p2")
    _zhangba_non_slash_hand(game, "p2")
    _step(game, _action(game, "use_duel"))
    _step(game, _action(game, "pass_trick_response"))
    _step(game, _action(game, "pass_trick_response"))
    assert game.phase is ProductionPhase.DUEL_RESPONSE
    with pytest.raises(UnsupportedRuleError):
        game.legal_actions()
    _assert_conservation(game)


def test_zhangba_nanman_public_legal_actions_fails_closed() -> None:
    """响应【南蛮入侵】时装备丈八＋两张非实体杀手牌：南蛮响应 public
    legal_actions 必须在枚举 virtual proposal 之前直接失败关闭。"""
    game = _fresh(seed=3)
    _equip(game, "sgs_weapon_zhangbashemao", "p2")
    _zhangba_non_slash_hand(game, "p2")
    _put_hand(game, "sgs_trick_nanmanruqin")
    _step(game, _action(game, "use_nanman"))
    _step(game, _action(game, "pass_trick_response"))
    _step(game, _action(game, "pass_trick_response"))
    assert game.phase is ProductionPhase.NANMAN_RESPONSE
    with pytest.raises(UnsupportedRuleError):
        game.legal_actions()
    _assert_conservation(game)


def test_qilingong_timing_replay_reexecutes() -> None:
    """麒麟弓 choice 与事件顺序（坐骑移动/失牌→DAMAGE）必须被 strict
    replay 确定性重现；篡改事件顺序被拒绝。"""

    def fixture(game: ProductionBasicCardBatch) -> None:
        _equip(game, "sgs_weapon_qilingong")
        for instance_id in list(game.state.card_ids_in(ZoneRef.hand("p2"))):
            game._state = game.state.move_card(instance_id, DISCARD_PILE)
        mount = next(
            r
            for r in game.formal_registry.records
            if r.card_key == "sgs_mount_offensive"
        )
        game._state = game.state.move_card(
            mount.instance_id, ZoneRef.equipment("p2", "attack_horse")
        )
        _put_hand(game, "sgs_basic_sha")

    from scripts.sgs_engine.production_replay import (
        ProductionReplayDivergenceError,
        ProductionReplayFormatError,
        ProductionReexecutionReplay,
        record_reference_production_batch,
        reexecute_production_replay,
    )

    class _QilinController(BatchReferenceController):
        strategy_version = "production-batch-qilin-controller.v1"

        def choose(self, legal_actions, context):
            for action in legal_actions:
                if action.payload.get("operation") == "use_slash":
                    return action
            return super().choose(legal_actions, context)

    record = record_reference_production_batch(
        seed=3, fixture=fixture, controller=_QilinController()
    )
    # 事件顺序：坐骑移动/失牌先于DAMAGE
    mount_seq = [
        e["sequence"]
        for e in record.events
        if e.get("payload", {}).get("reason") == "qilingong_mount_discard"
        and e.get("event_type") in ("card_moved", "card_lost")
    ]
    damage_seq = [
        e["sequence"]
        for e in record.events
        if e.get("event_type") == "damage"
    ]
    assert mount_seq and damage_seq
    assert max(mount_seq) < damage_seq[0]
    result = reexecute_production_replay(record, fixture=fixture)
    assert result.verified is True
    # 篡改：把DAMAGE sequence 提前到坐骑移动之前（交换sequence）
    tampered = copy.deepcopy(record.to_dict())
    events = tampered["events"]
    dmg = next(e for e in events if e.get("event_type") == "damage")
    mount = next(
        e
        for e in events
        if e.get("payload", {}).get("reason") == "qilingong_mount_discard"
        and e.get("event_type") == "card_moved"
    )
    dmg["sequence"], mount["sequence"] = mount["sequence"], dmg["sequence"]
    del tampered["record_sha256"]
    with pytest.raises(
        (ProductionReplayFormatError, ProductionReplayDivergenceError)
    ):
        reexecute_production_replay(
            ProductionReexecutionReplay.from_dict(tampered), fixture=fixture
        )
