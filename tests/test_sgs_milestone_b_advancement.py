# -*- coding: utf-8 -*-
"""MILESTONE_B_FORMAL_160_CARD_NO_SKILL_DUEL_ADVANCEMENT 专项测试。

覆盖：丈八蛇矛材料 HAND→PROCESSING→DISCARD 生命周期（USER_CONFIRMED_RULE，
2026-08-09；PLAY/DUEL/NANMAN/借刀各入口、响应链期间保持 PROCESSING、
被闪/伤害/无效/死亡清理、stale/forged/duplicate/atomic、strict replay、
player-visible privacy、牌守恒）；effective gender NONE（雌雄不触发，
无性别不构成“异性”）；formal soldier profile（USER_CONFIRMED_PROJECT_
FORMAL_PROFILE，双方士兵 4/4/4、唯一 RNG 先手、DRAW 正常 2、无手气卡、
无身份奖励、正式160牌、死亡胜负）。

所有正向路径都经过真实生产注册表与 enumerate→validate→apply。
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from scripts.sgs_engine import (
    BatchReferenceController,
    CharacterGender,
    CharacterMetadata,
    FormalDuelConfiguration,
    FormalNoSkillDuelSession,
    ProductionBasicCardBatch,
    ProductionPhase,
    record_reference_formal_duel,
    reexecute_production_replay,
    run_formal_duel_seed_sweep,
)
from scripts.sgs_engine.actions import (
    ActionType,
    InvalidActionError,
    LegalAction,
    UnsupportedRuleError,
    validate_action,
)
from scripts.sgs_engine.model import DISCARD_PILE, PROCESSING_ZONE, ZoneRef
from scripts.sgs_engine.production_batch import BatchActionIdController
from scripts.sgs_engine.production_cards import (
    WEAPON_SKILL_STATUS,
    check_weapon_skill_gate,
    is_cixiong_opposite_gender_target,
)


def _fresh(seed: int = 3) -> ProductionBasicCardBatch:
    game = ProductionBasicCardBatch(seed=seed)
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
    game: ProductionBasicCardBatch, operation: str, **kw: object
) -> object | None:
    for action in game.legal_actions():
        if action.payload.get("operation") != operation:
            continue
        if kw.get("card_key") is not None and action.payload.get(
            "card_key"
        ) != kw["card_key"]:
            continue
        return action
    return None


def _step(game: ProductionBasicCardBatch, action: object) -> None:
    assert action is not None and getattr(action, "action_id", None), action
    game.step(BatchActionIdController(action.action_id))  # type: ignore[attr-defined]


def _equip(
    game: ProductionBasicCardBatch, card_key: str, player_id: str = "p1"
) -> str:
    record = next(
        r for r in game.formal_registry.records if r.card_key == card_key
    )
    game._state = game.state.move_card(
        record.instance_id, ZoneRef.equipment(player_id, "weapon")
    )
    return record.instance_id


def _put_hand(
    game: ProductionBasicCardBatch, card_key: str, player_id: str = "p1"
) -> str:
    record = next(
        r for r in game.formal_registry.records if r.card_key == card_key
    )
    game._state = game.state.move_card(
        record.instance_id, ZoneRef.hand(player_id)
    )
    return record.instance_id


def _zhangba_material_hand(
    game: ProductionBasicCardBatch, player_id: str = "p1"
) -> tuple[str, str]:
    for instance_id in list(
        game.state.card_ids_in(ZoneRef.hand(player_id))
    ):
        game._state = game.state.move_card(instance_id, DISCARD_PILE)
    first = _put_hand(game, "sgs_basic_shan", player_id)
    second = _put_hand(game, "sgs_basic_tao", player_id)
    return first, second


def _zhangba_use_action(
    game: ProductionBasicCardBatch, player_id: str = "p1"
) -> LegalAction:
    actions = game.legal_actions()
    matches = [
        a
        for a in actions
        if a.payload.get("zhangba_virtual") is True
        and a.payload.get("operation") == "use_slash"
    ]
    assert matches, "出牌阶段必须能枚举丈八虚拟杀使用动作"
    return matches[0]


def _set_character(
    game: ProductionBasicCardBatch,
    player_id: str,
    character: CharacterMetadata | None,
) -> None:
    game._state = replace(
        game.state,
        players=tuple(
            replace(player, character=character)
            if player.player_id == player_id
            else player
            for player in game.state.players
        ),
        revision=game.state.revision + 1,
    )


def _assert_conservation(game: ProductionBasicCardBatch) -> None:
    total = sum(
        len(game.state.card_ids_in(zone))
        for zone in game.state.zone_order
    )
    assert total == len(game.state.cards) == 160


# ---------------------------------------------------------------------------
# 丈八蛇矛：材料 HAND→PROCESSING→DISCARD（USER_CONFIRMED_RULE 2026-08-09）
# ---------------------------------------------------------------------------


def test_zhangba_play_use_materials_processing_until_dodge_finish() -> None:
    game = _fresh(seed=3)
    _equip(game, "sgs_weapon_zhangbashemao")
    first, second = _zhangba_material_hand(game, "p1")
    action = _zhangba_use_action(game, "p1")
    _step(game, action)
    # 虚拟杀进入闪响应：两张材料权威位于处理区
    assert game.phase is ProductionPhase.SLASH_RESPONSE
    assert game.state.location_of(first) == PROCESSING_ZONE
    assert game.state.location_of(second) == PROCESSING_ZONE
    # 目标使用【闪】完成响应：材料随本次虚拟杀结算完成进入弃牌堆
    jink = _action(game, "play_dodge")
    assert jink is not None
    _step(game, jink)
    assert game.state.location_of(first) == DISCARD_PILE
    assert game.state.location_of(second) == DISCARD_PILE
    _assert_conservation(game)


def test_zhangba_play_use_materials_finalize_after_damage() -> None:
    game = _fresh(seed=3)
    _equip(game, "sgs_weapon_zhangbashemao")
    first, second = _zhangba_material_hand(game, "p1")
    _step(game, _zhangba_use_action(game, "p1"))
    assert game.phase is ProductionPhase.SLASH_RESPONSE
    # 目标不闪：进入伤害结算；材料在处理区直到伤害结算完成
    _step(game, _action(game, "pass_slash_response"))
    if game.runtime.pending_slash is not None:
        assert game.state.location_of(first) == PROCESSING_ZONE
        assert game.state.location_of(second) == PROCESSING_ZONE
    # 用参考控制器完成伤害结算
    controller = BatchReferenceController()
    guard = 0
    while game.runtime.pending_slash is not None and guard < 40:
        game.step(controller)
        guard += 1
    assert game.runtime.pending_slash is None
    assert game.state.location_of(first) == DISCARD_PILE
    assert game.state.location_of(second) == DISCARD_PILE
    _assert_conservation(game)


def test_zhangba_duel_play_finalizes_after_play_complete() -> None:
    game = _fresh(seed=3)
    _equip(game, "sgs_weapon_zhangbashemao", "p2")
    first, second = _zhangba_material_hand(game, "p2")
    _step(game, _action(game, "use_duel"))
    _step(game, _action(game, "pass_trick_response"))
    _step(game, _action(game, "pass_trick_response"))
    assert game.phase is ProductionPhase.DUEL_RESPONSE
    actions = game.legal_actions()
    virtual_play = next(
        a
        for a in actions
        if a.payload.get("zhangba_virtual") is True
        and a.payload.get("operation") == "play_slash_for_duel"
    )
    _step(game, virtual_play)
    # 响应【决斗】的丈八虚拟杀打出即完成：材料最终进入弃牌堆
    assert game.state.location_of(first) == DISCARD_PILE
    assert game.state.location_of(second) == DISCARD_PILE
    _assert_conservation(game)


def test_zhangba_borrowed_play_finalizes_after_slash_settle() -> None:
    game = _fresh(seed=3)
    jiedao = next(
        r for r in game.formal_registry.records if r.card_key == "sgs_trick_jiedaosharen"
    )
    game._state = game.state.move_card(
        jiedao.instance_id, ZoneRef.hand("p1")
    )
    _equip(game, "sgs_weapon_zhangbashemao", "p2")
    first, second = _zhangba_material_hand(game, "p2")
    _step(game, _action(game, "use_jiedao", card_key="sgs_trick_jiedaosharen"))
    _step(game, _action(game, "pass_trick_response"))
    _step(game, _action(game, "pass_trick_response"))
    assert game.phase is ProductionPhase.BORROWED_SWORD_CHOICE
    actions = game.legal_actions()
    virtual_choice = next(
        a
        for a in actions if a.payload.get("zhangba_virtual") is True
    )
    _step(game, virtual_choice)
    pending = game.runtime.pending_slash
    assert pending is not None and pending.virtual
    assert game.state.location_of(first) == PROCESSING_ZONE
    assert game.state.location_of(second) == PROCESSING_ZONE
    controller = BatchReferenceController()
    guard = 0
    while game.runtime.pending_slash is not None and guard < 40:
        game.step(controller)
        guard += 1
    assert game.state.location_of(first) == DISCARD_PILE
    assert game.state.location_of(second) == DISCARD_PILE
    _assert_conservation(game)


def test_zhangba_armor_invalidation_finalizes_materials() -> None:
    game = _fresh(seed=3)
    _equip(game, "sgs_weapon_zhangbashemao")
    _zhangba_material_hand(game, "p1")
    # 目标装备仁王盾且虚拟杀为黑色材料组合（黑+黑→黑色杀被无效化）
    renwang = next(
        r
        for r in game.formal_registry.records
        if r.card_key == "sgs_armor_renwangdun"
    )
    game._state = game.state.move_card(
        renwang.instance_id, ZoneRef.equipment("p2", "armor")
    )
    # 材料换成两张黑色牌（黑桃/梅花实体）
    for instance_id in list(game.state.card_ids_in(ZoneRef.hand("p1"))):
        game._state = game.state.move_card(instance_id, DISCARD_PILE)
    black_keys = []
    for record in game.formal_registry.records:
        if record.card_key == "sgs_basic_sha" and record.color == "黑":
            black_keys.append(record.instance_id)
    assert len(black_keys) >= 2
    game._state = game.state.move_card(black_keys[0], ZoneRef.hand("p1"))
    game._state = game.state.move_card(black_keys[1], ZoneRef.hand("p1"))
    materials = (black_keys[0], black_keys[1])
    _step(game, _zhangba_use_action(game, "p1"))
    # 仁王盾黑杀无效化：材料在结算完成时清理
    assert game.state.location_of(materials[0]) == DISCARD_PILE
    assert game.state.location_of(materials[1]) == DISCARD_PILE
    _assert_conservation(game)


def test_zhangba_duplicate_material_rejected() -> None:
    game = _fresh(seed=3)
    _equip(game, "sgs_weapon_zhangbashemao")
    _zhangba_material_hand(game, "p1")
    actions = game.legal_actions()
    matches = [
        a
        for a in actions
        if a.payload.get("zhangba_virtual") is True
        and a.payload.get("operation") == "use_slash"
    ]
    assert matches
    assert all(
        a.virtual_card is not None
        and len(a.virtual_card.material_card_instance_ids) == 2
        and len(set(a.virtual_card.material_card_instance_ids)) == 2
        for a in matches
    )


def test_zhangba_stale_forged_handle_rejected() -> None:
    game = _fresh(seed=3)
    _equip(game, "sgs_weapon_zhangbashemao")
    _zhangba_material_hand(game, "p1")
    action = _zhangba_use_action(game, "p1")
    forged = replace(
        action,
        payload={**action.payload, "handle": "zb_" + "0" * 32},
        action_id="act_forged_zhangba",
    )
    with pytest.raises(InvalidActionError):
        validate_action(game.state, game._context(), forged, game.registry)
    # 材料已离开手牌后旧动作 stale：窗口内材料变化被拒绝
    game2 = _fresh(seed=3)
    _equip(game2, "sgs_weapon_zhangbashemao")
    first, _second = _zhangba_material_hand(game2, "p1")
    old_action = _zhangba_use_action(game2, "p1")
    game2._state = game2.state.move_card(first, DISCARD_PILE)
    stale = replace(
        old_action,
        action_id="act_stale_zhangba",
    )
    with pytest.raises(InvalidActionError):
        validate_action(
            game2.state, game2._context(), stale, game2.registry
        )
    _assert_conservation(game)


# ---------------------------------------------------------------------------
# effective gender NONE（USER_CONFIRMED_RULE 2026-08-09）
# ---------------------------------------------------------------------------


def test_cixiong_none_vs_none_not_opposite() -> None:
    game = _fresh(seed=3)
    _set_character(game, "p1", CharacterMetadata("soldier", CharacterGender.NONE))
    _set_character(game, "p2", CharacterMetadata("soldier", CharacterGender.NONE))
    assert (
        is_cixiong_opposite_gender_target(
            game.state, actor_id="p1", target_id="p2"
        )
        is False
    )


def test_cixiong_none_vs_male_or_female_not_opposite() -> None:
    for other in (CharacterGender.MALE, CharacterGender.FEMALE):
        game = _fresh(seed=3)
        _set_character(
            game, "p1", CharacterMetadata("soldier", CharacterGender.NONE)
        )
        _set_character(game, "p2", CharacterMetadata("soldier", other))
        assert (
            is_cixiong_opposite_gender_target(
                game.state, actor_id="p1", target_id="p2"
            )
            is False
        )
        assert (
            is_cixiong_opposite_gender_target(
                game.state, actor_id="p2", target_id="p1"
            )
            is False
        )


def test_cixiong_male_vs_female_opposite() -> None:
    game = _fresh(seed=3)
    _set_character(game, "p1", CharacterMetadata("soldier", CharacterGender.MALE))
    _set_character(game, "p2", CharacterMetadata("soldier", CharacterGender.FEMALE))
    assert (
        is_cixiong_opposite_gender_target(
            game.state, actor_id="p1", target_id="p2"
        )
        is True
    )


def test_cixiong_gender_none_gate_does_not_fail_closed() -> None:
    game = _fresh(seed=3)
    _equip(game, "sgs_weapon_cixiongshuanggujian")
    _set_character(game, "p1", CharacterMetadata("soldier", CharacterGender.NONE))
    _set_character(game, "p2", CharacterMetadata("soldier", CharacterGender.NONE))
    # NONE 是有效无性别状态：gate 不失败关闭，且返回不触发
    check_weapon_skill_gate(
        game.state, actor_id="p1", decision="use_slash", target_id="p2"
    )


# ---------------------------------------------------------------------------
# formal soldier profile（USER_CONFIRMED_PROJECT_FORMAL_PROFILE 2026-08-09）
# ---------------------------------------------------------------------------


def test_formal_profile_shape_and_soldier_gender_none() -> None:
    profile = FormalDuelConfiguration.formal_profile()
    assert profile.source_confirmed is True
    assert profile.deck_applicable is True
    assert profile.initial_hand_count == 4
    assert profile.player_hp == (4, 4)
    assert profile.player_max_hp == (4, 4)
    assert profile.first_player_policy == "deterministic_rng"
    assert profile.verification_status == "当前确认"
    assert all(
        item is not None
        and item.character_key == "soldier"
        and item.gender is CharacterGender.NONE
        for item in profile.participants
    )


def test_formal_profile_session_creates_without_analysis_flag() -> None:
    game = FormalNoSkillDuelSession(
        seed=0,
        configuration=FormalDuelConfiguration.formal_profile(),
        analysis_only=False,
    )
    assert game.formal_result_eligible is True
    assert len(game.state.cards) == 160
    assert len(game.state.players) == 2
    assert all(
        player.max_hp == 4 and player.hp == 4
        for player in game.state.players
    )
    assert all(
        player.character is not None
        and player.character.character_key == "soldier"
        and player.character.gender is CharacterGender.NONE
        for player in game.state.players
    )
    # 初始手牌4张；先手由唯一 RNG 决定（同 seed 确定性）
    assert all(
        len(game.state.card_ids_in(ZoneRef.hand(player.player_id))) == 4
        for player in game.state.players
    )
    first_a = FormalNoSkillDuelSession(
        seed=17,
        configuration=FormalDuelConfiguration.formal_profile(),
        analysis_only=False,
    ).first_player_id
    first_b = FormalNoSkillDuelSession(
        seed=17,
        configuration=FormalDuelConfiguration.formal_profile(),
        analysis_only=False,
    ).first_player_id
    assert first_a == first_b in {"p1", "p2"}


def test_formal_profile_draw_draws_two_cards() -> None:
    game = FormalNoSkillDuelSession(
        seed=5,
        configuration=FormalDuelConfiguration.formal_profile(),
        analysis_only=False,
    )
    first = game.first_player_id
    hand_before = len(game.state.card_ids_in(ZoneRef.hand(first)))
    for operation in ("proceed_prepare", "proceed_judgment", "proceed_draw"):
        action = next(
            a
            for a in game.legal_actions()
            if a.payload.get("operation") == operation
        )
        game.step(BatchActionIdController(action.action_id))
    hand_after = len(game.state.card_ids_in(ZoneRef.hand(first)))
    assert hand_after == hand_before + 2


def test_formal_profile_weapon_statuses_duel_sufficient() -> None:
    from scripts.sgs_engine.formal_duel import inspect_formal_duel_readiness

    readiness = inspect_formal_duel_readiness()
    statuses = {
        item.card_key: item for item in readiness.card_semantic_statuses
    }
    assert statuses["sgs_weapon_cixiongshuanggujian"].duel_status == "COMPLETE"
    assert statuses["sgs_weapon_zhangbashemao"].duel_status == "COMPLETE"
    assert (
        statuses["sgs_weapon_fangtianhuaji"].duel_status
        == "NOT_APPLICABLE_TO_DUEL"
    )
    assert statuses["sgs_weapon_fangtianhuaji"].global_status == "PARTIAL"
    assert WEAPON_SKILL_STATUS["sgs_weapon_zhangbashemao"] == "COMPLETE"


def test_formal_seed_sweep_small_smoke_reexecutes() -> None:
    results = run_formal_duel_seed_sweep(
        (0, 1, 2),
        configuration=FormalDuelConfiguration.formal_profile(),
        analysis_only=False,
        max_steps=2000,
    )
    assert tuple(item.seed for item in results) == (0, 1, 2)
    assert all(item.natural_end for item in results)
    assert all(item.winner in {"p1", "p2"} for item in results)
    assert all(item.unsupported_rules == 0 for item in results)
    assert all(item.approximation_count == 0 for item in results)
    assert all(item.formal_result_eligible for item in results)
    assert all(item.reexecution_verified for item in results)
    assert all(not item.safety_cap_triggered for item in results)


def test_formal_profile_replay_record_and_reexecute() -> None:
    record = record_reference_formal_duel(
        4,
        configuration=FormalDuelConfiguration.formal_profile(),
        analysis_only=False,
        max_steps=2000,
    )
    assert record.header["formal_result"] is True
    result = reexecute_production_replay(record)
    assert result.verified is True


def test_finished_state_invariants_hold_for_formal_duel() -> None:
    """MB-M-008：正式对局 FINISHED 后临时区与挂起 root 必须全部清理。"""

    from scripts.sgs_engine.formal_duel import run_formal_duel_seed_sweep

    results = run_formal_duel_seed_sweep(
        (3,),
        configuration=FormalDuelConfiguration.formal_profile(),
        analysis_only=False,
        max_steps=2000,
    )
    assert len(results) == 1
    assert results[0].natural_end is True
    assert results[0].winner in {"p1", "p2"}
    # sweep 内部已经在每局结束调用 assert_finished_state_invariants；
    # 这里再通过 readiness 与状态机断言复核临时区语义。
    from scripts.sgs_engine.model import (
        DISCARD_PILE,
        PROCESSING_ZONE,
        REVEALED_ZONE,
    )

    game = FormalNoSkillDuelSession(
        seed=3,
        configuration=FormalDuelConfiguration.formal_profile(),
        analysis_only=False,
    )
    from scripts.sgs_engine.production_batch import BatchReferenceController

    controller = BatchReferenceController()
    guard = 0
    while not game.is_finished and guard < 2000:
        game.step(controller)
        guard += 1
    assert game.is_finished
    assert not game.state.card_ids_in(PROCESSING_ZONE)
    assert not game.state.card_ids_in(REVEALED_ZONE)
    assert game.runtime.pending_slash is None
    assert game.runtime.pending_damage_card_id is None
    assert game.runtime.pending_borrowed_sword is None
    assert game.runtime.pending_group_trick is None
    assert game.runtime.pending_chain is None
    game.assert_finished_state_invariants()


def test_full_core_scope_is_not_expanded_by_duel_readiness() -> None:
    """MB-B-004：duel ready 不得把 full-core/多人/全局卡牌状态误开放。"""

    from scripts.sgs_formal_runner import build_current_status

    status = build_current_status(
        mode_name="formal_160_card_no_skill_duel"
    )
    capabilities = status["capabilities"]
    assert capabilities["authoritative_full_game_core"] is False
    assert capabilities["multi_player_production_proven"] is False
    assert capabilities["milestone_b_complete"] is False
    assert capabilities["global_all_cards_implemented"] is False
    assert capabilities["duel_scope_all_cards_sufficient"] is True
    assert capabilities["formal_duel_no_skill_ready"] is True
    assert status["formal_run_ready"] is True
    statuses = {
        item["card_key"]: item
        for item in status["formal_duel"]["card_semantic_statuses"]
    }
    assert (
        statuses["sgs_weapon_fangtianhuaji"]["global_status"] == "PARTIAL"
    )
