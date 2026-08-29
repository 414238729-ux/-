# -*- coding: utf-8 -*-
"""Production tests for Authoritative Shamoke 【蒺藜】 implementation and F-001..F-006 closure."""

from __future__ import annotations

from dataclasses import replace

import pytest

from scripts.sgs_engine.actions import (
    ActionType,
    InvalidActionError,
    LegalAction,
    UnsupportedRuleError,
)
from scripts.sgs_engine.events import EventType, GameEvent
from scripts.sgs_engine.engine import canonical_state_snapshot
from scripts.sgs_engine.generals import create_authoritative_general_batch_v1_registry
from scripts.sgs_engine.model import CharacterGender, ZoneRef, DISCARD_PILE, DRAW_PILE, PROCESSING_ZONE
from scripts.sgs_engine.mode_identity_heir import (
    FormalHeirAndSpyChoiceIdentityConfiguration,
    HeirAndSpyChoiceModePolicy,
    HeirAndSpyChoiceOutcomePolicy,
    HeirAndSpyChoiceRole,
    HeirAndSpyChoiceVariantState,
)
from scripts.sgs_engine.production_batch import (
    BatchActionIdController,
    ProductionBatchDeckExhaustedError,
    ProductionBatchError,
    ProductionBasicCardBatch,
    ProductionPhase,
)
from scripts.sgs_engine.skill_impl_v1 import create_proof_slice_v1_registry
from scripts.sgs_engine.replay import sha256_value


def _fresh_shamoke_game(
    seed: int = 12345,
    players: int = 2,
    assignments: dict[str, str] | None = None,
    player_hp: tuple[int, ...] | None = None,
    player_max_hp: tuple[int, ...] | None = None,
    first_player_id: str = "p1",
) -> ProductionBasicCardBatch:
    if assignments is None:
        assignments = {"p1": "shamoke"}
    kwargs: dict[str, object] = {
        "seed": seed,
        "first_player_id": first_player_id,
        "shuffle": False,
        "general_assignments": assignments,
    }
    if player_hp is not None:
        kwargs["player_hp"] = player_hp
    if player_max_hp is not None:
        kwargs["player_max_hp"] = player_max_hp
    return ProductionBasicCardBatch(**kwargs)


def _step(game: ProductionBasicCardBatch, action: LegalAction) -> None:
    game.step(BatchActionIdController(action.action_id))


def _advance_to_play(game: ProductionBasicCardBatch) -> None:
    for _ in range(20):
        if game.phase is ProductionPhase.PLAY:
            return
        legal = game.legal_actions()
        assert legal, "没有合法动作推进到 PLAY 阶段"
        _step(game, legal[0])
    assert game.phase is ProductionPhase.PLAY


def _give_hand_cards(game: ProductionBasicCardBatch, player_id: str, card_keys: list[str]) -> list[str]:
    """Deterministically place requested card keys into player's hand."""
    state = game.state
    assigned_instances: list[str] = []
    moves: dict[str, ZoneRef] = {}
    cards_in_hand = state.card_ids_in(ZoneRef.hand(player_id))
    for cid in cards_in_hand:
        moves[cid] = DRAW_PILE

    for key in card_keys:
        found_id = None
        for c in state.cards:
            if c.card_key == key and c.instance_id not in moves and c.instance_id not in assigned_instances:
                if state.location_of(c.instance_id) in (DRAW_PILE, DISCARD_PILE):
                    found_id = c.instance_id
                    break
        assert found_id is not None, f"未在牌堆中找到卡牌键 {key}"
        assigned_instances.append(found_id)
        moves[found_id] = ZoneRef.hand(player_id)

    game._state = state.move_cards(moves)
    game._state.assert_card_conservation()
    game.assert_resolution_invariants()
    return assigned_instances


def _resolve_pending_trick(game: ProductionBasicCardBatch) -> None:
    """Resolve pending trick windows (wuxie passes, zone choices, etc.) until back in PLAY or finished."""
    for _ in range(15):
        if game.phase is ProductionPhase.PLAY or game.is_finished:
            return
        legal = game.legal_actions()
        if not legal:
            return
        # Zone choice pick (shunshou / guohe)
        zone_pick = next((a for a in legal if a.payload.get("operation") == "choose_target_zone_card"), None)
        if zone_pick is not None:
            _step(game, zone_pick)
            continue
        # Trick response pass (Wuxie pass)
        pass_trick = next((a for a in legal if a.action_type is ActionType.PASS and a.payload.get("operation") == "pass_trick_response"), None)
        if pass_trick is not None:
            _step(game, pass_trick)
            continue
        break


def _signed_jili_choices(
    game: ProductionBasicCardBatch,
) -> tuple[LegalAction, LegalAction]:
    """Return the signed ACTIVATE/PASS pair for a live Jili window."""
    legal = game.legal_actions()
    activate = next(
        action
        for action in legal
        if action.action_type is ActionType.ACTIVATE_SKILL
        and action.skill_id == "sgs_skill_jili"
    )
    decline = next(
        action
        for action in legal
        if action.action_type is ActionType.PASS
        and action.skill_id == "sgs_skill_jili"
    )
    assert activate.action_id
    assert decline.action_id
    assert activate.payload["continuation_identity"] == decline.payload[
        "continuation_identity"
    ]
    assert activate.payload["decision"] == "activate"
    assert decline.payload["decision"] == "pass"
    return activate, decline


def _authoritative_atomicity_snapshot(
    game: ProductionBasicCardBatch,
) -> dict[str, object]:
    """Exact public and private semantic state used by continuation rollback proof."""

    state_snapshot = canonical_state_snapshot(game.state)
    pending = game._pending_card_continuation
    skill_runtime = game.skill_runtime
    return {
        "state_reference": game.state,
        "state_snapshot": state_snapshot,
        "state_hash": sha256_value(state_snapshot),
        "events": tuple(event.to_replay_dict() for event in game.events),
        "event_next_sequence": game._events.next_sequence,
        "rng_state": game._rng.export_current_state(),
        "rng_hash": game._rng.current_state_sha256,
        "rng_calls": game.rng_calls,
        "rng_call_count": game._rng.call_count,
        "skill_runtime_reference": skill_runtime,
        "skill_runtime_snapshot": (
            None if skill_runtime is None else skill_runtime.audit_fingerprint()
        ),
        "batch_runtime_reference": game.runtime,
        "batch_runtime_snapshot": game.runtime.audit_value(),
        "checkpointed_card_event_sequences": (
            game._checkpointed_card_event_sequences
        ),
        "skill_consumed_triggers": game._skill_consumed_triggers,
        "skill_pending": game._skill_pending,
        "skill_trigger_queue": tuple(game._skill_trigger_queue),
        "pending_continuation_reference": pending,
        "pending_continuation_identity": (
            None if pending is None else pending.continuation_id
        ),
        "pending_continuation_source": (
            None
            if pending is None
            else (
                pending.source_event_sequence,
                pending.source_event_type,
                pending.card_action_identity,
            )
        ),
        "consumed_card_continuations": game._consumed_card_continuations,
        "continuation_in_progress_id": game._continuation_in_progress_id,
        "card_locations": tuple(sorted(game.state.card_locations.items())),
        "zone_order": tuple(
            sorted(
                (
                    (
                        zone.kind.value,
                        zone.owner_id,
                        zone.equipment_slot,
                        zone.special_zone,
                    ),
                    instance_ids,
                )
                for zone, instance_ids in game.state.zone_order.items()
            )
        ),
        "wine_buff_owner_id": game.runtime.wine_buff_owner_id,
        "wine_buff_used_this_play_phase": (
            game.runtime.wine_buff_used_this_play_phase
        ),
        "phase_history": game.phase_history,
        "step_count": game.step_count,
        "skill_hand_limit_exempt_ids": game._skill_hand_limit_exempt_ids,
        "turn_start_sequence": game._turn_start_sequence,
        "active_validated_action": game._active_validated_action,
        "mode_policy_snapshot": (
            None
            if game.mode_policy is None
            or not hasattr(game.mode_policy, "snapshot_authoritative_state")
            else game.mode_policy.snapshot_authoritative_state()
        ),
    }


def _equip_fixture(
    game: ProductionBasicCardBatch,
    player_id: str,
    card_key: str,
    slot: str,
) -> str:
    record = next(
        record
        for record in game.formal_registry.records
        if record.card_key == card_key
    )
    game._state = game.state.move_card(
        record.instance_id, ZoneRef.equipment(player_id, slot)
    )
    return record.instance_id


def _put_draw_top(game: ProductionBasicCardBatch, instance_id: str) -> None:
    if game.state.location_of(instance_id) != DRAW_PILE:
        game._state = game.state.move_card(instance_id, DRAW_PILE)
    pile = list(game.state.card_ids_in(DRAW_PILE))
    pile.remove(instance_id)
    game._state = game.state.reorder_zone(DRAW_PILE, (instance_id, *pile))


def _fresh_c7_virtual_peach_shamoke_game() -> ProductionBasicCardBatch:
    """Build the real C7 mode-policy seam on ProductionBasicCardBatch."""
    players = tuple(f"p{index}" for index in range(1, 9))
    role_original = {
        "p1": HeirAndSpyChoiceRole.LORD.value,
        "p2": HeirAndSpyChoiceRole.LOYALIST.value,
        "p3": HeirAndSpyChoiceRole.LOYALIST.value,
        "p4": HeirAndSpyChoiceRole.REBEL.value,
        "p5": HeirAndSpyChoiceRole.REBEL.value,
        "p6": HeirAndSpyChoiceRole.REBEL.value,
        "p7": HeirAndSpyChoiceRole.REBEL.value,
        "p8": HeirAndSpyChoiceRole.SPY.value,
    }
    role_current = {
        **role_original,
        "p8": HeirAndSpyChoiceRole.AMBITIONIST.value,
    }
    variant = HeirAndSpyChoiceVariantState(
        original_lord_player_id="p1",
        current_lord_player_id="p1",
        role_original=role_original,
        role_current=role_current,
        heir_window_open=False,
        spy_path_locked=True,
        ambitionist_mark_available={"p8": True},
    )
    configuration = FormalHeirAndSpyChoiceIdentityConfiguration.formal_profile()
    policy = HeirAndSpyChoiceModePolicy(
        configuration, players, "p1", variant
    )
    game = ProductionBasicCardBatch(
        seed=31,
        player_hp=(4,) * 8,
        player_max_hp=(4,) * 8,
        player_ids=players,
        outcome_policy=HeirAndSpyChoiceOutcomePolicy(role_current, "p1"),
        first_player_id="p8",
        mode_policy=policy,
        shuffle=False,
        general_assignments={"p8": "shamoke"},
    )
    policy.bind_session(game)
    return game


def test_f001_general_hp_authority_override_rejected() -> None:
    """F-001: 传入与武将定义冲突的 player_hp / player_max_hp 时 fail-closed."""
    with pytest.raises(ValueError, match="权威体力 4/4.*冲突"):
        ProductionBasicCardBatch(
            seed=1,
            player_hp=(3, 4),
            player_max_hp=(4, 4),
            general_assignments={"p1": "shamoke"},
        )

    with pytest.raises(ValueError, match="权威体力 4/4.*冲突"):
        ProductionBasicCardBatch(
            seed=1,
            player_hp=(4, 4),
            player_max_hp=(5, 4),
            general_assignments={"p1": "shamoke"},
        )


def test_f001_general_hp_authority_default_injected() -> None:
    """F-001: 未传冲突体力时自动从 GeneralDefinition 注入 4/4 与角色性别元数据."""
    game = _fresh_shamoke_game()
    p1 = game.state.players_by_id["p1"]
    assert p1.hp == 4
    assert p1.max_hp == 4
    assert p1.character is not None
    assert p1.character.character_key == "shamoke"
    assert p1.character.intrinsic_gender is CharacterGender.MALE

    # 未分配武将的角色没有 character metadata
    p2 = game.state.players_by_id["p2"]
    assert p2.character is None


def test_f003_barehand_range_1_deterministic() -> None:
    """F-003: 攻击范围 1（徒手）确定性测试：第 1 张牌触发摸 1 张牌，第 2 张不触发."""
    game = _fresh_shamoke_game()
    _advance_to_play(game)

    # 确定性给予两张可用牌（杀、酒）
    cids = _give_hand_cards(game, "p1", ["sgs_basic_sha", "sgs_basic_jiu"])

    # 第 1 张牌：杀
    legal = game.legal_actions()
    play_slash = next(a for a in legal if a.action_type is ActionType.USE_CARD and a.card_instance_id == cids[0])
    _step(game, play_slash)

    # 触发【蒺藜】决策窗口
    pending_legal = game.legal_actions()
    jili_act = next(a for a in pending_legal if a.action_type is ActionType.ACTIVATE_SKILL and a.skill_id == "sgs_skill_jili")
    assert jili_act.payload.get("draw_count") == 1
    _step(game, jili_act)

    # 验证摸牌事件
    gain_events = [e for e in game.events if e.event_type is EventType.CARD_GAINED and e.payload.get("reason") == "sgs_skill_jili"]
    assert len(gain_events) == 1
    assert gain_events[0].target_ids == ("p1",)

    # 目标 p2 闪响应选择 Pass
    dodge_pass = next(a for a in game.legal_actions() if a.action_type is ActionType.PASS and a.payload.get("operation") == "pass_slash_response")
    _step(game, dodge_pass)

    # 伤害确认
    assert game.phase is ProductionPhase.PLAY

    # 第 2 张牌：酒
    legal2 = game.legal_actions()
    play_jiu = next(a for a in legal2 if a.action_type is ActionType.USE_CARD and a.card_instance_id == cids[1])
    _step(game, play_jiu)

    # 第 2 张牌在攻击范围 1 下不触发蒺藜
    legal_after_jiu = game.legal_actions()
    assert not any(a.skill_id == "sgs_skill_jili" for a in legal_after_jiu)


def test_f003_range_2_deterministic() -> None:
    """F-003: 攻击范围 2 确定性测试：第 1 张不触发，第 2 张触发摸 2 张牌."""
    game = _fresh_shamoke_game()
    # 先将寒冰剑（范围2）装备到 p1
    hb_id = next(c.instance_id for c in game.state.cards if c.card_key == "sgs_weapon_hanbingjian")
    game._state = game.state.move_card(hb_id, ZoneRef.equipment("p1", "weapon"))
    _advance_to_play(game)

    cids = _give_hand_cards(game, "p1", ["sgs_basic_sha", "sgs_basic_jiu"])

    # 第 1 张牌：杀（范围2下第1张不触发）
    play_slash = next(a for a in game.legal_actions() if a.action_type is ActionType.USE_CARD and a.card_instance_id == cids[0])
    _step(game, play_slash)

    # 确认无技能决策窗口直接进入闪响应
    dodge_pass = next(a for a in game.legal_actions() if a.action_type is ActionType.PASS and a.payload.get("operation") == "pass_slash_response")
    _step(game, dodge_pass)
    # 寒冰剑技能 Pass
    hb_pass = next((a for a in game.legal_actions() if a.action_type is ActionType.PASS and a.payload.get("operation") == "pass_weapon_choice"), None)
    if hb_pass is not None:
        _step(game, hb_pass)

    assert game.phase is ProductionPhase.PLAY

    # 第 2 张牌：酒（第2张与范围2匹配，触发蒺藜）
    play_jiu = next(a for a in game.legal_actions() if a.action_type is ActionType.USE_CARD and a.card_instance_id == cids[1])
    _step(game, play_jiu)

    jili_act = next(a for a in game.legal_actions() if a.action_type is ActionType.ACTIVATE_SKILL and a.skill_id == "sgs_skill_jili")
    assert jili_act.payload.get("draw_count") == 2
    _step(game, jili_act)

    gain_events = [e for e in game.events if e.event_type is EventType.CARD_GAINED and e.payload.get("reason") == "sgs_skill_jili"]
    assert len(gain_events) == 2


def test_f003_range_3_deterministic() -> None:
    """F-003: 攻击范围 3 确定性测试：第 1、2 张不触发，第 3 张触发摸 3 张牌."""
    game = _fresh_shamoke_game()
    ql_id = next(c.instance_id for c in game.state.cards if c.card_key == "sgs_weapon_qinglongyanyuedao")
    game._state = game.state.move_card(ql_id, ZoneRef.equipment("p1", "weapon"))
    _advance_to_play(game)

    cids = _give_hand_cards(game, "p1", ["sgs_basic_jiu", "sgs_trick_wuzhongshengyou", "sgs_basic_sha"])

    # 第 1 张牌：酒
    play_jiu = next(a for a in game.legal_actions() if a.action_type is ActionType.USE_CARD and a.card_instance_id == cids[0])
    _step(game, play_jiu)
    assert not any(a.skill_id == "sgs_skill_jili" for a in game.legal_actions())

    # 第 2 张牌：无中生有
    play_wz = next(a for a in game.legal_actions() if a.action_type is ActionType.USE_CARD and a.card_instance_id == cids[1])
    _step(game, play_wz)
    assert not any(a.skill_id == "sgs_skill_jili" for a in game.legal_actions())
    _resolve_pending_trick(game)

    assert game.phase is ProductionPhase.PLAY

    # 第 3 张牌：杀
    play_slash = next(a for a in game.legal_actions() if a.action_type is ActionType.USE_CARD and a.card_instance_id == cids[2])
    _step(game, play_slash)

    # 触发蒺藜，摸 3 张牌
    jili_act = next(a for a in game.legal_actions() if a.action_type is ActionType.ACTIVATE_SKILL and a.skill_id == "sgs_skill_jili")
    assert jili_act.payload.get("draw_count") == 3
    _step(game, jili_act)

    gain_events = [e for e in game.events if e.event_type is EventType.CARD_GAINED and e.payload.get("reason") == "sgs_skill_jili"]
    assert len(gain_events) == 3


def test_f003_range_4_deterministic() -> None:
    """F-003: 攻击范围 4 确定性测试：第 1..3 张不触发，第 4 张触发摸 4 张牌."""
    game = _fresh_shamoke_game()
    ft_id = next(c.instance_id for c in game.state.cards if c.card_key == "sgs_weapon_fangtianhuaji")
    game._state = game.state.move_card(ft_id, ZoneRef.equipment("p1", "weapon"))
    _advance_to_play(game)

    cids = _give_hand_cards(game, "p1", ["sgs_basic_jiu", "sgs_trick_wuzhongshengyou", "sgs_trick_shunshouqianyang", "sgs_basic_sha"])

    # 第 1 张：酒
    _step(game, next(a for a in game.legal_actions() if a.action_type is ActionType.USE_CARD and a.card_instance_id == cids[0]))
    assert not any(a.skill_id == "sgs_skill_jili" for a in game.legal_actions())

    # 第 2 张：无中生有
    _step(game, next(a for a in game.legal_actions() if a.action_type is ActionType.USE_CARD and a.card_instance_id == cids[1]))
    assert not any(a.skill_id == "sgs_skill_jili" for a in game.legal_actions())
    _resolve_pending_trick(game)

    # 第 3 张：顺手牵羊
    _step(game, next(a for a in game.legal_actions() if a.action_type is ActionType.USE_CARD and a.card_instance_id == cids[2]))
    assert not any(a.skill_id == "sgs_skill_jili" for a in game.legal_actions())
    _resolve_pending_trick(game)

    assert game.phase is ProductionPhase.PLAY

    # 第 4 张：杀
    _step(game, next(a for a in game.legal_actions() if a.action_type is ActionType.USE_CARD and a.card_instance_id == cids[3]))

    # 触发蒺藜，摸 4 张牌
    jili_act = next(a for a in game.legal_actions() if a.action_type is ActionType.ACTIVATE_SKILL and a.skill_id == "sgs_skill_jili")
    assert jili_act.payload.get("draw_count") == 4
    _step(game, jili_act)

    gain_events = [e for e in game.events if e.event_type is EventType.CARD_GAINED and e.payload.get("reason") == "sgs_skill_jili"]
    assert len(gain_events) == 4


def test_f003_range_5_deterministic() -> None:
    """F-003: 攻击范围 5 确定性测试：第 1..4 张不触发，第 5 张触发摸 5 张牌."""
    game = _fresh_shamoke_game()
    qlg_id = next(c.instance_id for c in game.state.cards if c.card_key == "sgs_weapon_qilingong")
    game._state = game.state.move_card(qlg_id, ZoneRef.equipment("p1", "weapon"))
    _advance_to_play(game)

    cids = _give_hand_cards(
        game,
        "p1",
        ["sgs_basic_jiu", "sgs_trick_wuzhongshengyou", "sgs_trick_guohechaiqiao", "sgs_trick_shunshouqianyang", "sgs_basic_sha"],
    )

    # 第 1 张：酒
    _step(game, next(a for a in game.legal_actions() if a.action_type is ActionType.USE_CARD and a.card_instance_id == cids[0]))
    assert not any(a.skill_id == "sgs_skill_jili" for a in game.legal_actions())

    # 第 2 张：无中生有
    _step(game, next(a for a in game.legal_actions() if a.action_type is ActionType.USE_CARD and a.card_instance_id == cids[1]))
    assert not any(a.skill_id == "sgs_skill_jili" for a in game.legal_actions())
    _resolve_pending_trick(game)

    # 第 3 张：过河拆桥
    _step(game, next(a for a in game.legal_actions() if a.action_type is ActionType.USE_CARD and a.card_instance_id == cids[2]))
    assert not any(a.skill_id == "sgs_skill_jili" for a in game.legal_actions())
    _resolve_pending_trick(game)

    # 第 4 张：顺手牵羊
    _step(game, next(a for a in game.legal_actions() if a.action_type is ActionType.USE_CARD and a.card_instance_id == cids[3]))
    assert not any(a.skill_id == "sgs_skill_jili" for a in game.legal_actions())
    _resolve_pending_trick(game)

    assert game.phase is ProductionPhase.PLAY

    # 第 5 张：杀
    _step(game, next(a for a in game.legal_actions() if a.action_type is ActionType.USE_CARD and a.card_instance_id == cids[4]))

    # 触发蒺藜，摸 5 张牌
    jili_act = next(a for a in game.legal_actions() if a.action_type is ActionType.ACTIVATE_SKILL and a.skill_id == "sgs_skill_jili")
    assert jili_act.payload.get("draw_count") == 5
    _step(game, jili_act)


def test_f004_weapon_equip_reads_range_before_slot_entry_and_event_order() -> None:
    """F-004: 武器牌作为第 X 张：验证触发发生在 EQUIPMENT_EQUIPPED / 装备入槽之前，自然读取原范围."""
    game = _fresh_shamoke_game()
    _advance_to_play(game)

    # 给予一张青龙偃月刀（范围3）、杀、酒
    cids = _give_hand_cards(game, "p1", ["sgs_weapon_qinglongyanyuedao", "sgs_basic_sha", "sgs_basic_jiu"])

    # 第 1 张牌：装备青龙偃月刀
    weapon_action = next(a for a in game.legal_actions() if a.action_type is ActionType.USE_CARD and a.card_instance_id == cids[0])
    _step(game, weapon_action)

    # 此时武器在 PROCESSING_ZONE，武器槽为空，攻击范围仍为 1
    assert game.state.location_of(cids[0]) == PROCESSING_ZONE
    assert not game.state.card_ids_in(ZoneRef.equipment("p1", "weapon"))

    # 触发【蒺藜】（第1张牌，范围1 -> draw_count 1）
    jili_act = next(a for a in game.legal_actions() if a.action_type is ActionType.ACTIVATE_SKILL and a.skill_id == "sgs_skill_jili")
    assert jili_act.payload.get("draw_count") == 1
    _step(game, jili_act)

    # 激活蒺藜后，武器正式入槽，EQUIPMENT_EQUIPPED 事件产生
    assert game.state.location_of(cids[0]) == ZoneRef.equipment("p1", "weapon")

    # 检查事件发生严格顺序：CARD_USED -> CARD_GAINED(Jili) -> EQUIPMENT_EQUIPPED
    event_types = [e.event_type for e in game.events]
    used_idx = event_types.index(EventType.CARD_USED)
    gain_idx = next(i for i, e in enumerate(game.events) if e.event_type is EventType.CARD_GAINED and e.payload.get("reason") == "sgs_skill_jili")
    equip_idx = event_types.index(EventType.EQUIPMENT_EQUIPPED)

    assert used_idx < gain_idx < equip_idx, f"事件顺序错误: used={used_idx}, gain={gain_idx}, equip={equip_idx}"

    # 此时攻击范围已更新为 3
    # 第 2 张牌：杀（范围3下第2张不触发）
    _step(game, next(a for a in game.legal_actions() if a.action_type is ActionType.USE_CARD and a.card_instance_id == cids[1]))
    # 目标闪 Pass
    _step(game, next(a for a in game.legal_actions() if a.action_type is ActionType.PASS and a.payload.get("operation") == "pass_slash_response"))
    assert not any(a.skill_id == "sgs_skill_jili" for a in game.legal_actions())

    # 第 3 张牌：酒（范围3下第3张触发摸3张）
    _step(game, next(a for a in game.legal_actions() if a.action_type is ActionType.USE_CARD and a.card_instance_id == cids[2]))
    jili_act3 = next(a for a in game.legal_actions() if a.action_type is ActionType.ACTIVATE_SKILL and a.skill_id == "sgs_skill_jili")
    assert jili_act3.payload.get("draw_count") == 3
    _step(game, jili_act3)


def test_f006_response_jink_vs_slash_counts_for_jili() -> None:
    """F-006: 真实响应场景：Jink vs Slash (CARD_USED) 计入蒺藜."""
    game = _fresh_shamoke_game(assignments={"p1": "shamoke"}, first_player_id="p2")
    _advance_to_play(game)

    p2_slash = _give_hand_cards(game, "p2", ["sgs_basic_sha"])[0]
    p1_jink = _give_hand_cards(game, "p1", ["sgs_basic_shan"])[0]

    # p2 对 p1 使用杀
    _step(game, next(a for a in game.legal_actions() if a.action_type is ActionType.USE_CARD and a.card_instance_id == p2_slash))

    # p1 响应出闪（ActionType.USE_CARD, operation="play_dodge"）
    dodge_action = next(a for a in game.legal_actions() if a.action_type is ActionType.USE_CARD and a.payload.get("operation") == "play_dodge")
    _step(game, dodge_action)

    # p1 在 p2 回合使用的第 1 张牌（闪），范围为 1 -> 触发蒺藜摸 1 张
    jili_act = next(a for a in game.legal_actions() if a.action_type is ActionType.ACTIVATE_SKILL and a.skill_id == "sgs_skill_jili")
    assert jili_act.payload.get("draw_count") == 1
    assert jili_act.actor_id == "p1"
    _step(game, jili_act)

    gain_events = [e for e in game.events if e.event_type is EventType.CARD_GAINED and e.payload.get("reason") == "sgs_skill_jili" and e.target_ids == ("p1",)]
    assert len(gain_events) == 1


def test_f006_response_jink_vs_wanjian_counts_for_jili() -> None:
    """F-006: 真实响应场景：Jink vs Wanjian (CARD_PLAYED) 计入蒺藜."""
    game = _fresh_shamoke_game(assignments={"p1": "shamoke"}, first_player_id="p2")
    _advance_to_play(game)

    p2_wanjian = _give_hand_cards(game, "p2", ["sgs_trick_wanjianqifa"])[0]
    p1_jink = _give_hand_cards(game, "p1", ["sgs_basic_shan"])[0]

    # p2 使用万箭齐发
    _step(game, next(a for a in game.legal_actions() if a.action_type is ActionType.USE_CARD and a.card_instance_id == p2_wanjian))
    # 双方 Pass 无懈可击
    _resolve_pending_trick(game)

    # p1 响应打出闪 (CARD_PLAYED)
    dodge_action = next(a for a in game.legal_actions() if a.action_type is ActionType.PLAY_CARD and a.payload.get("operation") == "play_jink_for_wanjian")
    _step(game, dodge_action)

    # p1 在 p2 回合打出的第 1 张牌（闪），范围 1 -> 触发蒺藜摸 1 张
    jili_act = next(a for a in game.legal_actions() if a.action_type is ActionType.ACTIVATE_SKILL and a.skill_id == "sgs_skill_jili")
    assert jili_act.payload.get("draw_count") == 1
    assert jili_act.actor_id == "p1"
    _step(game, jili_act)

    gain_events = [e for e in game.events if e.event_type is EventType.CARD_GAINED and e.payload.get("reason") == "sgs_skill_jili" and e.target_ids == ("p1",)]
    assert len(gain_events) == 1


def test_f006_turn_reset_behavior() -> None:
    """F-006: 他人回合响应计入该回合用牌数，下一回合开始重置为 0."""
    game = _fresh_shamoke_game(assignments={"p1": "shamoke"}, first_player_id="p2")
    _advance_to_play(game)

    p2_slash = _give_hand_cards(game, "p2", ["sgs_basic_sha"])[0]
    p1_jink = _give_hand_cards(game, "p1", ["sgs_basic_shan", "sgs_basic_jiu"])[0]

    # p2 杀 p1，p1 闪 -> 触发第 1 次蒺藜
    _step(game, next(a for a in game.legal_actions() if a.action_type is ActionType.USE_CARD and a.card_instance_id == p2_slash))
    _step(game, next(a for a in game.legal_actions() if a.action_type is ActionType.USE_CARD and a.payload.get("operation") == "play_dodge"))
    _step(game, next(a for a in game.legal_actions() if a.action_type is ActionType.ACTIVATE_SKILL and a.skill_id == "sgs_skill_jili"))

    # p2 结束出牌和弃牌阶段，轮到 p1
    _step(game, next(a for a in game.legal_actions() if a.payload.get("operation") == "end_play_phase"))
    # p2 弃牌阶段
    discard_submit = next((a for a in game.legal_actions() if a.payload.get("operation") == "discard_phase_submit"), None)
    if discard_submit is not None:
        _step(game, discard_submit)
    end_turn = next((a for a in game.legal_actions() if a.payload.get("operation") == "end_turn"), None)
    if end_turn is not None:
        _step(game, end_turn)

    # 轮到 p1 回合
    assert game.current_player_id == "p1"
    _advance_to_play(game)

    # p1 在自己回合使用第 1 张牌（酒）：计数已重置为 0，本次作为第 1 张牌，再次触发蒺藜摸 1 张牌！
    p1_jiu = next(c for c in game.state.card_ids_in(ZoneRef.hand("p1")) if game.state.cards_by_id[c].card_key == "sgs_basic_jiu")
    _step(game, next(a for a in game.legal_actions() if a.action_type is ActionType.USE_CARD and a.card_instance_id == p1_jiu))

    jili_act = next(a for a in game.legal_actions() if a.action_type is ActionType.ACTIVATE_SKILL and a.skill_id == "sgs_skill_jili")
    assert jili_act.payload.get("draw_count") == 1
    _step(game, jili_act)


def test_unassigned_player_has_no_skills() -> None:
    """未分配武将的角色没有任何技能，即使出牌也不触发蒺藜."""
    game = _fresh_shamoke_game(assignments={"p1": "shamoke"}, first_player_id="p2")
    _advance_to_play(game)

    p2_cards = _give_hand_cards(game, "p2", ["sgs_basic_jiu"])
    _step(game, next(a for a in game.legal_actions() if a.action_type is ActionType.USE_CARD and a.card_instance_id == p2_cards[0]))

    # p2 不触发任何技能
    assert not any(a.action_type in (ActionType.ACTIVATE_SKILL, ActionType.PASS) and a.skill_id for a in game.legal_actions())


def _first_card_jili_window(
    card_key: str,
    *,
    player_hp: tuple[int, ...] | None = None,
) -> tuple[ProductionBasicCardBatch, str, LegalAction]:
    game = _fresh_shamoke_game()
    if player_hp is not None:
        game._state = replace(
            game.state,
            players=tuple(
                replace(player, hp=player_hp[index])
                for index, player in enumerate(game.state.players)
            ),
            revision=game.state.revision + 1,
        )
    _advance_to_play(game)
    card_id = _give_hand_cards(game, "p1", [card_key])[0]
    use = next(
        action
        for action in game.legal_actions()
        if action.action_type is ActionType.USE_CARD
        and action.card_instance_id == card_id
    )
    _step(game, use)
    jili = next(
        action
        for action in game.legal_actions()
        if action.skill_id == "sgs_skill_jili"
        and action.action_type is ActionType.ACTIVATE_SKILL
    )
    return game, card_id, jili


def test_f004_generic_checkpoint_wine_before_effect() -> None:
    game, _, jili = _first_card_jili_window("sgs_basic_jiu")
    assert game.runtime.wine_buff_owner_id is None
    assert game.runtime.wine_buff_used_this_play_phase is False
    continuation_id = jili.payload["continuation_identity"]

    _step(game, jili)

    assert game.runtime.wine_buff_owner_id == "p1"
    assert game.runtime.wine_buff_used_this_play_phase is True
    assert game.pending_card_continuation_identity is None
    assert continuation_id in game.consumed_card_continuation_identities


def test_f004_generic_checkpoint_peach_before_recovery() -> None:
    game, _, jili = _first_card_jili_window(
        "sgs_basic_tao", player_hp=(3, 4)
    )
    assert game.state.players_by_id["p1"].hp == 3

    _step(game, jili)

    assert game.state.players_by_id["p1"].hp == 4


def test_f004_generic_checkpoint_wuzhong_before_response_and_effect() -> None:
    game, _, jili = _first_card_jili_window("sgs_trick_wuzhongshengyou")
    assert game.phase is ProductionPhase.PLAY
    assert not any(
        event.event_type is EventType.CARD_GAINED
        and event.payload.get("reason") == "wuzhongshengyou"
        for event in game.events
    )

    _step(game, jili)

    assert game.phase is ProductionPhase.TRICK_RESPONSE
    used_index = next(
        index
        for index, event in enumerate(game.events)
        if event.event_type is EventType.CARD_USED
        and event.card_key == "sgs_trick_wuzhongshengyou"
    )
    jili_index = next(
        index
        for index, event in enumerate(game.events)
        if event.event_type is EventType.CARD_GAINED
        and event.payload.get("reason") == "sgs_skill_jili"
    )
    assert used_index < jili_index


def test_f004_generic_checkpoint_delayed_trick_before_judgment_placement() -> None:
    game, card_id, jili = _first_card_jili_window("sgs_delayed_lebusi")
    assert game.state.location_of(card_id) == PROCESSING_ZONE

    _step(game, jili)

    assert game.state.location_of(card_id) == ZoneRef.judgment("p2")
    used_index = next(
        index
        for index, event in enumerate(game.events)
        if event.event_type is EventType.CARD_USED
        and event.card_key == "sgs_delayed_lebusi"
    )
    jili_index = next(
        index
        for index, event in enumerate(game.events)
        if event.event_type is EventType.CARD_GAINED
        and event.payload.get("reason") == "sgs_skill_jili"
    )
    placement_index = next(
        index
        for index, event in enumerate(game.events)
        if event.event_type is EventType.CARD_MOVED
        and event.card_instance_id == card_id
        and event.payload.get("reason") == "delayed_trick_placed"
    )
    assert used_index < jili_index < placement_index


def test_f004_generic_checkpoint_wuxie_before_nullification_effect() -> None:
    game = _fresh_shamoke_game(
        assignments={"p2": "shamoke"}, first_player_id="p1"
    )
    _advance_to_play(game)
    trick_id = _give_hand_cards(
        game, "p1", ["sgs_trick_wuzhongshengyou"]
    )[0]
    wuxie_id = _give_hand_cards(
        game, "p2", ["sgs_trick_wuxiekeji"]
    )[0]
    _step(
        game,
        next(
            action
            for action in game.legal_actions()
            if action.card_instance_id == trick_id
        ),
    )
    _step(
        game,
        next(
            action
            for action in game.legal_actions()
            if action.payload.get("operation") == "pass_trick_response"
        ),
    )
    _step(
        game,
        next(
            action
            for action in game.legal_actions()
            if action.payload.get("operation") == "use_wuxie"
            and action.card_instance_id == wuxie_id
        ),
    )
    assert game.runtime.trick_effect_active is True
    jili = next(
        action
        for action in game.legal_actions()
        if action.skill_id == "sgs_skill_jili"
        and action.action_type is ActionType.ACTIVATE_SKILL
    )

    _step(game, jili)

    assert game.runtime.trick_effect_active is False
    used_index = next(
        index
        for index, event in enumerate(game.events)
        if event.event_type is EventType.CARD_USED
        and event.card_instance_id == wuxie_id
    )
    jili_index = next(
        index
        for index, event in enumerate(game.events)
        if event.event_type is EventType.CARD_GAINED
        and event.payload.get("reason") == "sgs_skill_jili"
    )
    assert used_index < jili_index


def _open_dying_self_rescue_jili(
    rescue_card_key: str,
) -> tuple[ProductionBasicCardBatch, LegalAction]:
    game = _fresh_shamoke_game(first_player_id="p2")
    game._state = replace(
        game.state,
        players=tuple(
            replace(player, hp=1) if player.player_id == "p1" else player
            for player in game.state.players
        ),
        revision=game.state.revision + 1,
    )
    _advance_to_play(game)
    slash_id = _give_hand_cards(game, "p2", ["sgs_basic_sha"])[0]
    rescue_id = _give_hand_cards(game, "p1", [rescue_card_key])[0]
    _step(
        game,
        next(
            action
            for action in game.legal_actions()
            if action.card_instance_id == slash_id
        ),
    )
    _step(
        game,
        next(
            action
            for action in game.legal_actions()
            if action.payload.get("operation") == "pass_slash_response"
        ),
    )
    rescue_operation = (
        "rescue_with_wine"
        if rescue_card_key == "sgs_basic_jiu"
        else "rescue_with_peach"
    )
    for _ in range(2):
        rescue = next(
            (
                action
                for action in game.legal_actions()
                if action.payload.get("operation") == rescue_operation
                and action.card_instance_id == rescue_id
            ),
            None,
        )
        if rescue is not None:
            _step(game, rescue)
            break
        _step(
            game,
            next(
                action
                for action in game.legal_actions()
                if action.payload.get("operation") == "pass_rescue"
            ),
        )
    else:
        raise AssertionError("未进入 p1 的濒死自救窗口")
    assert game.state.players_by_id["p1"].hp == 0
    jili = next(
        action
        for action in game.legal_actions()
        if action.skill_id == "sgs_skill_jili"
        and action.action_type is ActionType.ACTIVATE_SKILL
    )
    return game, jili


@pytest.mark.parametrize("rescue_card_key", ("sgs_basic_tao", "sgs_basic_jiu"))
def test_f004_generic_checkpoint_dying_peach_or_wine_before_recovery(
    rescue_card_key: str,
) -> None:
    game, jili = _open_dying_self_rescue_jili(rescue_card_key)

    _step(game, jili)

    assert game.state.players_by_id["p1"].hp == 1
    assert game.runtime.pending_dying_id is None


def test_continuation_pass_resumes_once_and_duplicate_resume_rejected() -> None:
    game, _, jili = _first_card_jili_window("sgs_basic_jiu")
    continuation_id = jili.payload["continuation_identity"]
    decline = next(
        action
        for action in game.legal_actions()
        if action.action_type is ActionType.PASS
        and action.skill_id == "sgs_skill_jili"
    )

    _step(game, decline)

    assert game.runtime.wine_buff_used_this_play_phase is True
    assert continuation_id in game.consumed_card_continuation_identities
    with pytest.raises(InvalidActionError, match="duplicate resume"):
        game._resume_pending_card_continuation(game.state, continuation_id)


def test_continuation_activate_resumes_once_and_duplicate_paths_are_atomic() -> None:
    game, _, activate = _first_card_jili_window("sgs_basic_jiu")
    continuation_id = activate.payload["continuation_identity"]

    _step(game, activate)

    state_after = game.state
    events_after = game.events
    rng_after = game.rng_calls
    assert game.runtime.wine_buff_used_this_play_phase is True
    assert game.pending_card_continuation_identity is None
    assert continuation_id in game.consumed_card_continuation_identities

    with pytest.raises(InvalidActionError, match="duplicate resume"):
        game._resume_pending_card_continuation(game.state, continuation_id)
    with pytest.raises(ProductionBatchError):
        _step(game, activate)

    assert game.state == state_after
    assert game.events == events_after
    assert game.rng_calls == rng_after


def test_continuation_stale_revision_rejected() -> None:
    game, _, jili = _first_card_jili_window("sgs_basic_jiu")
    pending = game._pending_card_continuation
    assert pending is not None
    game._pending_card_continuation = replace(
        pending, expected_revision=pending.expected_revision + 1
    )
    with pytest.raises(UnsupportedRuleError, match="expected revision"):
        game._resume_pending_card_continuation(
            game.state, jili.payload["continuation_identity"]
        )


def test_continuation_skill_invalidated_or_lost_fails_closed() -> None:
    for mutation in ("invalidate", "lose"):
        game, _, _ = _first_card_jili_window("sgs_basic_jiu")
        assert game.skill_runtime is not None
        if mutation == "invalidate":
            game._skill_runtime = game.skill_runtime.invalidate_skill(
                "p1", "sgs_skill_jili", "test"
            )
        else:
            game._skill_runtime = game.skill_runtime.lose_skill(
                "p1", "sgs_skill_jili"
            )
        with pytest.raises(UnsupportedRuleError, match="失效或失去"):
            game.legal_actions()


def test_continuation_material_leaves_expected_zone_fails_closed() -> None:
    game, card_id, jili = _first_card_jili_window("sgs_delayed_lebusi")
    game._state = game.state.move_card(card_id, DRAW_PILE)
    assert game._pending_card_continuation is not None
    game._pending_card_continuation = replace(
        game._pending_card_continuation,
        expected_revision=game.state.revision,
    )
    with pytest.raises(UnsupportedRuleError, match="离开预期牌区"):
        game._resume_pending_card_continuation(
            game.state, jili.payload["continuation_identity"]
        )


def test_continuation_target_death_fails_closed() -> None:
    game, _, jili = _first_card_jili_window("sgs_delayed_lebusi")
    game._state = replace(
        game.state,
        players=tuple(
            replace(player, alive=False, hp=0)
            if player.player_id == "p2"
            else player
            for player in game.state.players
        ),
        revision=game.state.revision + 1,
    )
    assert game._pending_card_continuation is not None
    game._pending_card_continuation = replace(
        game._pending_card_continuation,
        expected_revision=game.state.revision,
    )
    with pytest.raises(UnsupportedRuleError, match="目标已死亡"):
        game._resume_pending_card_continuation(
            game.state, jili.payload["continuation_identity"]
        )


def test_continuation_terminal_state_fails_closed() -> None:
    game, _, jili = _first_card_jili_window("sgs_basic_jiu")
    game._runtime = replace(
        game.runtime,
        phase=ProductionPhase.FINISHED,
        winner_id="p1",
        game_over_reason="victory",
    )
    with pytest.raises(UnsupportedRuleError, match="终局状态"):
        game._resume_pending_card_continuation(
            game.state, jili.payload["continuation_identity"]
        )


def test_continuation_pending_dying_identity_change_fails_closed() -> None:
    game, _, jili = _first_card_jili_window("sgs_basic_jiu")
    game._runtime = replace(game.runtime, pending_dying_id="p2")
    with pytest.raises(UnsupportedRuleError, match="pending dying"):
        game._resume_pending_card_continuation(
            game.state, jili.payload["continuation_identity"]
        )


def test_continuation_owner_death_before_skill_resolution_fails_closed() -> None:
    game, _, _ = _first_card_jili_window("sgs_basic_jiu")
    game._state = replace(
        game.state,
        players=tuple(
            replace(player, alive=False, hp=0)
            if player.player_id == "p1"
            else player
            for player in game.state.players
        ),
        revision=game.state.revision + 1,
    )
    with pytest.raises(InvalidActionError, match="已经死亡"):
        game.legal_actions()


@pytest.mark.parametrize("decision_name", ["pass", "activate"])
def test_nested_signed_card_step_is_pre_mutation_atomic_and_retryable(
    monkeypatch: pytest.MonkeyPatch,
    decision_name: str,
) -> None:
    game = _fresh_shamoke_game()
    _advance_to_play(game)
    wine_id, weapon_id = _give_hand_cards(
        game,
        "p1",
        ["sgs_basic_jiu", "sgs_weapon_qinggangjian"],
    )
    wine = next(
        action
        for action in game.legal_actions()
        if action.card_instance_id == wine_id
    )
    _step(game, wine)
    activate, decline = _signed_jili_choices(game)
    decision = decline if decision_name == "pass" else activate
    pending = game._pending_card_continuation
    assert pending is not None
    continuation_id = pending.continuation_id
    source_sequence = pending.source_event_sequence
    source_type = pending.source_event_type
    source_action_identity = pending.card_action_identity
    before = _authoritative_atomicity_snapshot(game)

    original_commit = game._commit_runtime
    nested_actions: list[LegalAction] = []
    successful_action_records: list[str] = []
    reentered = False

    def commit_and_reenter(old_runtime: object, new_runtime: object) -> None:
        nonlocal reentered
        original_commit(old_runtime, new_runtime)
        if reentered or not getattr(
            new_runtime, "wine_buff_used_this_play_phase", False
        ):
            return
        reentered = True
        nested = next(
            action
            for action in game.legal_actions()
            if action.card_instance_id == weapon_id
        )
        assert nested.action_id
        nested_actions.append(nested)
        _step(game, nested)

    monkeypatch.setattr(game, "_commit_runtime", commit_and_reenter)
    with pytest.raises(UnsupportedRuleError, match="嵌套.*mutation 前失败关闭"):
        _step(game, decision)
        successful_action_records.append(decision.action_id)

    assert len(nested_actions) == 1
    assert successful_action_records == []
    after = _authoritative_atomicity_snapshot(game)
    for field, expected in before.items():
        assert after[field] == expected, field

    pending_after = game._pending_card_continuation
    assert pending_after is not None
    assert pending_after.continuation_id == continuation_id
    assert (
        pending_after.source_event_sequence,
        pending_after.source_event_type,
        pending_after.card_action_identity,
    ) == (source_sequence, source_type, source_action_identity)
    assert continuation_id not in game.consumed_card_continuation_identities
    assert game._continuation_in_progress_id is None
    assert game.state.location_of(weapon_id) == ZoneRef.hand("p1")
    assert not any(
        event.card_instance_id == weapon_id
        and event.event_type
        in (EventType.CARD_USED, EventType.CARD_MOVED, EventType.EQUIPMENT_EQUIPPED)
        and event.sequence is not None
        and event.sequence >= before["event_next_sequence"]
        for event in game.events
    )
    assert not any(
        event.event_type is EventType.EQUIPMENT_EQUIPPED
        and event.card_instance_id == weapon_id
        for event in game.events
    )
    game.state.assert_card_conservation()
    game.assert_resolution_invariants()

    # Rollback returns the exact signed decision window, so the original action
    # can be submitted again and only that successful return is recordable.
    monkeypatch.setattr(game, "_commit_runtime", original_commit)
    assert any(action.action_id == decision.action_id for action in game.legal_actions())
    _step(game, decision)
    successful_action_records.append(decision.action_id)
    assert successful_action_records == [decision.action_id]
    assert game.pending_card_continuation_identity is None
    assert continuation_id in game.consumed_card_continuation_identities
    assert game._continuation_in_progress_id is None
    assert game.runtime.wine_buff_owner_id == "p1"
    assert game.runtime.wine_buff_used_this_play_phase is True
    game.state.assert_card_conservation()
    game.assert_resolution_invariants()


def _open_weapon_jili_for_draw_transaction(
    supply_mode: str = "enough",
) -> tuple[ProductionBasicCardBatch, LegalAction, str | None]:
    game = _fresh_shamoke_game()
    _advance_to_play(game)
    weapon_id = _give_hand_cards(
        game, "p1", ["sgs_weapon_qinglongyanyuedao"]
    )[0]
    reshuffle_card: str | None = None
    if supply_mode != "enough":
        draw_ids = list(game.state.card_ids_in(DRAW_PILE))
        discard_ids = list(game.state.card_ids_in(DISCARD_PILE))
        moves = {
            instance_id: ZoneRef.hand("p2")
            for instance_id in (*draw_ids, *discard_ids)
        }
        if supply_mode == "reshuffle":
            reshuffle_card = draw_ids[0]
            moves[reshuffle_card] = DISCARD_PILE
        game._state = game.state.move_cards(moves)
    use = next(
        action
        for action in game.legal_actions()
        if action.action_type is ActionType.USE_CARD
        and action.card_instance_id == weapon_id
    )
    _step(game, use)
    jili = next(
        action
        for action in game.legal_actions()
        if action.action_type is ActionType.ACTIVATE_SKILL
        and action.skill_id == "sgs_skill_jili"
    )
    return game, jili, reshuffle_card


def test_jili_draw_transaction_draw_pile_enough() -> None:
    game, jili, _ = _open_weapon_jili_for_draw_transaction()
    before = len(game.state.card_ids_in(ZoneRef.hand("p1")))
    _step(game, jili)
    assert len(game.state.card_ids_in(ZoneRef.hand("p1"))) == before + 1


def test_jili_draw_transaction_empty_draw_reshuffles_discard() -> None:
    game, jili, reshuffle_card = _open_weapon_jili_for_draw_transaction(
        "reshuffle"
    )
    assert reshuffle_card is not None
    assert not game.state.card_ids_in(DRAW_PILE)
    before_rng = len(game.rng_calls)

    _step(game, jili)

    assert game.state.location_of(reshuffle_card) == ZoneRef.hand("p1")
    assert len(game.rng_calls) == before_rng + 1
    assert any(
        event.event_type is EventType.CARD_MOVED
        and event.card_instance_id == reshuffle_card
        and event.payload.get("reason") == "reshuffle"
        for event in game.events
    )


def test_jili_draw_transaction_true_exhaustion_fails_closed() -> None:
    game, jili, _ = _open_weapon_jili_for_draw_transaction("exhausted")
    assert not game.state.card_ids_in(DRAW_PILE)
    assert not game.state.card_ids_in(DISCARD_PILE)
    before_state = game.state
    before_events = game.events
    before_rng = game.rng_calls

    with pytest.raises(ProductionBatchDeckExhaustedError):
        _step(game, jili)

    assert game.state == before_state
    assert game.events == before_events
    assert game.rng_calls == before_rng


def test_checkpoint_bagua_virtual_jink_pass_resumes_slash_cancellation() -> None:
    game = _fresh_shamoke_game(
        assignments={"p2": "shamoke"}, first_player_id="p1"
    )
    _advance_to_play(game)
    _equip_fixture(game, "p2", "sgs_armor_baguazhen", "armor")
    slash_id = _give_hand_cards(game, "p1", ["sgs_basic_sha"])[0]
    red_judgment = next(
        record.instance_id
        for record in game.formal_registry.records
        if record.instance_id == "sgs-mobile-20260725-098"
    )
    _put_draw_top(game, red_judgment)

    _step(
        game,
        next(
            action
            for action in game.legal_actions()
            if action.card_instance_id == slash_id
        ),
    )
    _step(
        game,
        next(
            action
            for action in game.legal_actions()
            if action.payload.get("operation") == "activate_bagua"
        ),
    )

    _, decline = _signed_jili_choices(game)
    assert game.phase is ProductionPhase.SLASH_RESPONSE
    assert not any(
        event.event_type is EventType.CARD_EFFECT_CANCELLED
        and event.card_instance_id == slash_id
        for event in game.events
    )
    _step(game, decline)

    assert game.phase is ProductionPhase.PLAY
    assert any(
        event.event_type is EventType.CARD_USED
        and event.card_instance_id is None
        and event.card_key == "sgs_basic_shan"
        and event.payload.get("purpose") == "bagua_virtual_dodge"
        for event in game.events
    )
    assert any(
        event.event_type is EventType.CARD_EFFECT_CANCELLED
        and event.card_instance_id == slash_id
        for event in game.events
    )


def test_checkpoint_duel_slash_activate_resumes_duel_chain() -> None:
    game = _fresh_shamoke_game(
        assignments={"p2": "shamoke"}, first_player_id="p1"
    )
    _advance_to_play(game)
    duel_id = _give_hand_cards(game, "p1", ["sgs_trick_juedou"])[0]
    slash_id = _give_hand_cards(game, "p2", ["sgs_basic_sha"])[0]
    _step(
        game,
        next(
            action
            for action in game.legal_actions()
            if action.card_instance_id == duel_id
        ),
    )
    for _ in range(2):
        _step(
            game,
            next(
                action
                for action in game.legal_actions()
                if action.payload.get("operation") == "pass_trick_response"
            ),
        )
    duel_slash = next(
        action
        for action in game.legal_actions()
        if action.payload.get("operation") == "play_slash_for_duel"
        and action.card_instance_id == slash_id
    )
    _step(game, duel_slash)

    activate, _ = _signed_jili_choices(game)
    assert game.runtime.pending_duel is not None
    assert game.runtime.pending_duel.responder_id == "p2"
    _step(game, activate)

    assert game.phase is ProductionPhase.DUEL_RESPONSE
    assert game.runtime.pending_duel is not None
    assert game.runtime.pending_duel.responder_id == "p1"
    assert game.state.location_of(slash_id) == DISCARD_PILE


def test_checkpoint_borrowed_sword_forced_slash_pass_resumes_response() -> None:
    game = _fresh_shamoke_game(
        assignments={"p2": "shamoke"}, first_player_id="p1"
    )
    _advance_to_play(game)
    weapon_id = _equip_fixture(
        game, "p2", "sgs_weapon_zhugeliannu", "weapon"
    )
    trick_id = _give_hand_cards(
        game, "p1", ["sgs_trick_jiedaosharen"]
    )[0]
    slash_id = _give_hand_cards(game, "p2", ["sgs_basic_sha"])[0]
    _step(
        game,
        next(
            action
            for action in game.legal_actions()
            if action.card_instance_id == trick_id
            and action.payload.get("operation") == "use_jiedao"
        ),
    )
    for _ in range(2):
        _step(
            game,
            next(
                action
                for action in game.legal_actions()
                if action.payload.get("operation") == "pass_trick_response"
            ),
        )
    forced_slash = next(
        action
        for action in game.legal_actions()
        if action.payload.get("operation") == "choose_borrowed_sword_slash"
    )
    _step(game, forced_slash)

    _, decline = _signed_jili_choices(game)
    assert game.runtime.pending_borrowed_sword is not None
    assert game.runtime.pending_borrowed_sword.stage == "slash_request"
    _step(game, decline)

    assert game.phase is ProductionPhase.SLASH_RESPONSE
    assert game.runtime.pending_slash is not None
    assert game.runtime.pending_slash.slash_instance_id == slash_id
    _step(
        game,
        next(
            action
            for action in game.legal_actions()
            if action.payload.get("operation") == "pass_slash_response"
        ),
    )
    assert game.phase is ProductionPhase.PLAY
    assert game.state.location_of(slash_id) == DISCARD_PILE
    assert game.state.location_of(weapon_id) == ZoneRef.equipment("p2", "weapon")


def test_checkpoint_qinglong_chase_activate_resumes_slash_response() -> None:
    game = _fresh_shamoke_game()
    _advance_to_play(game)
    _equip_fixture(
        game, "p1", "sgs_weapon_qinglongyanyuedao", "weapon"
    )
    wine_id, first_slash_id, chase_slash_id = _give_hand_cards(
        game,
        "p1",
        ["sgs_basic_jiu", "sgs_basic_sha", "sgs_basic_sha"],
    )
    dodge_id = _give_hand_cards(game, "p2", ["sgs_basic_shan"])[0]
    _step(
        game,
        next(
            action
            for action in game.legal_actions()
            if action.card_instance_id == wine_id
        ),
    )
    _step(
        game,
        next(
            action
            for action in game.legal_actions()
            if action.card_instance_id == first_slash_id
        ),
    )
    _step(
        game,
        next(
            action
            for action in game.legal_actions()
            if action.card_instance_id == dodge_id
        ),
    )
    chase = next(
        action
        for action in game.legal_actions()
        if action.payload.get("operation") == "qinglong_use_slash"
    )
    _step(game, chase)

    activate, _ = _signed_jili_choices(game)
    assert game.phase is ProductionPhase.WEAPON_SLASH_CHOICE
    _step(game, activate)

    assert game.phase is ProductionPhase.SLASH_RESPONSE
    assert game.runtime.pending_slash is not None
    assert game.runtime.pending_slash.slash_instance_id == chase_slash_id
    _step(
        game,
        next(
            action
            for action in game.legal_actions()
            if action.payload.get("operation") == "pass_slash_response"
        ),
    )
    assert game.phase is ProductionPhase.PLAY
    assert any(
        event.event_type is EventType.DAMAGE
        and event.card_instance_id == chase_slash_id
        for event in game.events
    )


def test_checkpoint_c7_virtual_peach_pass_resumes_recovery() -> None:
    game = _fresh_c7_virtual_peach_shamoke_game()
    _advance_to_play(game)
    game._state = replace(
        game.state,
        players=tuple(
            replace(player, hp=3) if player.player_id == "p8" else player
            for player in game.state.players
        ),
        revision=game.state.revision + 1,
    )
    virtual_peach = next(
        action
        for action in game.legal_actions()
        if action.payload.get("operation") == "heal_self"
        and action.payload.get("virtual") is True
    )
    assert virtual_peach.action_id
    _step(game, virtual_peach)

    _, decline = _signed_jili_choices(game)
    assert game.state.players_by_id["p8"].hp == 3
    assert game.mode_policy is not None
    assert game.mode_policy._variant.ambitionist_mark_available["p8"] is False
    _step(game, decline)

    assert game.state.players_by_id["p8"].hp == 4
    assert any(
        event.event_type is EventType.HP_RECOVER
        and event.target_ids == ("p8",)
        and event.payload.get("reason") == "ambitionist_mark_virtual_peach"
        for event in game.events
    )


def test_reproduce_f_fifth_001_c7_virtual_peach_mark_rollback_atomicity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """F-FIFTH-001: C7 virtual peach mark mutation must roll back atomically on failure."""
    game = _fresh_c7_virtual_peach_shamoke_game()
    _advance_to_play(game)
    game._state = replace(
        game.state,
        players=tuple(
            replace(player, hp=3) if player.player_id == "p8" else player
            for player in game.state.players
        ),
        revision=game.state.revision + 1,
    )
    assert game.mode_policy is not None
    assert game.mode_policy._variant.ambitionist_mark_available["p8"] is True

    virtual_peach = next(
        action
        for action in game.legal_actions()
        if action.payload.get("operation") == "heal_self"
        and action.payload.get("virtual") is True
    )
    assert virtual_peach.action_id
    before_atomicity = _authoritative_atomicity_snapshot(game)
    before_legal_actions = game.legal_actions()

    original_invariants = game.assert_resolution_invariants

    def _failing_invariants() -> None:
        raise UnsupportedRuleError("Injected failure for F-FIFTH-001 rollback proof")

    monkeypatch.setattr(game, "assert_resolution_invariants", _failing_invariants)
    with pytest.raises(UnsupportedRuleError, match="Injected failure for F-FIFTH-001"):
        _step(game, virtual_peach)

    # Prove exact rollback: mark is True, atomicity snapshot matches, legal_actions match
    assert game.mode_policy._variant.ambitionist_mark_available["p8"] is True
    after_atomicity = _authoritative_atomicity_snapshot(game)
    for field, expected in before_atomicity.items():
        assert after_atomicity[field] == expected, field
    assert game.legal_actions() == before_legal_actions

    # Re-executing signed action must now succeed cleanly
    monkeypatch.setattr(game, "assert_resolution_invariants", original_invariants)
    reissued_virtual_peach = next(
        action
        for action in game.legal_actions()
        if action.payload.get("operation") == "heal_self"
        and action.payload.get("virtual") is True
    )
    assert reissued_virtual_peach.action_id == virtual_peach.action_id
    _step(game, reissued_virtual_peach)

    _, decline = _signed_jili_choices(game)
    assert game.state.players_by_id["p8"].hp == 3
    assert game.mode_policy._variant.ambitionist_mark_available["p8"] is False
    _step(game, decline)

    assert game.state.players_by_id["p8"].hp == 4
    assert any(
        event.event_type is EventType.HP_RECOVER
        and event.target_ids == ("p8",)
        and event.payload.get("reason") == "ambitionist_mark_virtual_peach"
        for event in game.events
    )


def test_c7_ambitionist_mark_draw_two_failure_rollback_atomicity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """C7 ambitionist mark draw two rollback atomicity."""
    game = _fresh_c7_virtual_peach_shamoke_game()
    _advance_to_play(game)
    assert game.mode_policy is not None
    assert game.mode_policy._variant.ambitionist_mark_available["p8"] is True

    draw_two = next(
        action
        for action in game.legal_actions()
        if action.payload.get("operation") == "ambitionist_mark_draw_two"
    )
    assert draw_two.action_id
    before_atomicity = _authoritative_atomicity_snapshot(game)
    before_legal_actions = game.legal_actions()

    original_draw = game._draw_cards

    def _failing_draw(*args: object, **kwargs: object) -> object:
        raise UnsupportedRuleError("Injected draw failure for C7 mark rollback proof")

    monkeypatch.setattr(game, "_draw_cards", _failing_draw)
    with pytest.raises(UnsupportedRuleError, match="Injected draw failure"):
        _step(game, draw_two)

    assert game.mode_policy._variant.ambitionist_mark_available["p8"] is True
    after_atomicity = _authoritative_atomicity_snapshot(game)
    for field, expected in before_atomicity.items():
        assert after_atomicity[field] == expected, field
    assert game.legal_actions() == before_legal_actions

    monkeypatch.setattr(game, "_draw_cards", original_draw)
    reissued_draw_two = next(
        action
        for action in game.legal_actions()
        if action.payload.get("operation") == "ambitionist_mark_draw_two"
    )
    assert reissued_draw_two.action_id == draw_two.action_id
    hand_count_before = len(game.state.card_ids_in(ZoneRef.hand("p8")))
    _step(game, reissued_draw_two)

    assert game.mode_policy._variant.ambitionist_mark_available["p8"] is False
    assert len(game.state.card_ids_in(ZoneRef.hand("p8"))) == hand_count_before + 2


def test_c7_select_heir_failure_rollback_atomicity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """C7 heir selection failure rollback atomicity."""
    players = tuple(f"p{index}" for index in range(1, 9))
    role_original = {
        "p1": HeirAndSpyChoiceRole.LORD.value,
        "p2": HeirAndSpyChoiceRole.LOYALIST.value,
        "p3": HeirAndSpyChoiceRole.LOYALIST.value,
        "p4": HeirAndSpyChoiceRole.REBEL.value,
        "p5": HeirAndSpyChoiceRole.REBEL.value,
        "p6": HeirAndSpyChoiceRole.REBEL.value,
        "p7": HeirAndSpyChoiceRole.REBEL.value,
        "p8": HeirAndSpyChoiceRole.SPY.value,
    }
    variant = HeirAndSpyChoiceVariantState(
        original_lord_player_id="p1",
        current_lord_player_id="p1",
        role_original=dict(role_original),
        role_current=dict(role_original),
        heir_window_open=True,
    )
    configuration = FormalHeirAndSpyChoiceIdentityConfiguration.formal_profile()
    policy = HeirAndSpyChoiceModePolicy(
        configuration, players, "p1", variant
    )
    game = ProductionBasicCardBatch(
        seed=42,
        player_hp=(4,) * 8,
        player_max_hp=(4,) * 8,
        player_ids=players,
        outcome_policy=HeirAndSpyChoiceOutcomePolicy(role_original, "p1"),
        first_player_id="p1",
        mode_policy=policy,
        shuffle=False,
    )
    policy.bind_session(game)
    game._runtime = game._c7_open_mode_decision_window(
        game.runtime, ("p1",)
    )
    assert game.phase is ProductionPhase.MODE_DECISION

    select_heir = next(
        action
        for action in game.legal_actions()
        if action.payload.get("operation") == "select_heir"
        and action.payload.get("target_id") == "p2"
    )
    assert select_heir.action_id
    assert variant.heir_player_id is None
    assert variant.heir_selection_used is False

    before_atomicity = _authoritative_atomicity_snapshot(game)
    before_legal_actions = game.legal_actions()

    original_invariants = game.assert_resolution_invariants

    def _failing_invariants() -> None:
        raise UnsupportedRuleError("Injected failure for heir selection rollback proof")

    monkeypatch.setattr(game, "assert_resolution_invariants", _failing_invariants)
    with pytest.raises(UnsupportedRuleError, match="Injected failure for heir selection"):
        _step(game, select_heir)

    assert variant.heir_player_id is None
    assert variant.heir_selection_used is False
    after_atomicity = _authoritative_atomicity_snapshot(game)
    for field, expected in before_atomicity.items():
        assert after_atomicity[field] == expected, field
    assert game.legal_actions() == before_legal_actions

    monkeypatch.setattr(game, "assert_resolution_invariants", original_invariants)
    reissued_heir = next(
        action
        for action in game.legal_actions()
        if action.payload.get("operation") == "select_heir"
        and action.payload.get("target_id") == "p2"
    )
    assert reissued_heir.action_id == select_heir.action_id
    _step(game, reissued_heir)

    assert variant.heir_player_id == "p2"
    assert variant.heir_selection_used is True


def test_c7_spy_path_choice_failure_rollback_atomicity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """C7 spy path choice failure rollback atomicity."""
    players = tuple(f"p{index}" for index in range(1, 9))
    role_original = {
        "p1": HeirAndSpyChoiceRole.LORD.value,
        "p2": HeirAndSpyChoiceRole.LOYALIST.value,
        "p3": HeirAndSpyChoiceRole.LOYALIST.value,
        "p4": HeirAndSpyChoiceRole.REBEL.value,
        "p5": HeirAndSpyChoiceRole.REBEL.value,
        "p6": HeirAndSpyChoiceRole.REBEL.value,
        "p7": HeirAndSpyChoiceRole.REBEL.value,
        "p8": HeirAndSpyChoiceRole.SPY.value,
    }
    variant = HeirAndSpyChoiceVariantState(
        original_lord_player_id="p1",
        current_lord_player_id="p1",
        role_original=dict(role_original),
        role_current=dict(role_original),
        heir_window_open=False,
        lord_or_loyalist_confirmed_dead=True,
    )
    configuration = FormalHeirAndSpyChoiceIdentityConfiguration.formal_profile()
    policy = HeirAndSpyChoiceModePolicy(
        configuration, players, "p1", variant
    )
    game = ProductionBasicCardBatch(
        seed=43,
        player_hp=(4,) * 8,
        player_max_hp=(4,) * 8,
        player_ids=players,
        outcome_policy=HeirAndSpyChoiceOutcomePolicy(role_original, "p1"),
        first_player_id="p8",
        mode_policy=policy,
        shuffle=False,
    )
    policy.bind_session(game)
    game._runtime = game._c7_open_mode_decision_window(
        game.runtime, ("p8",)
    )
    assert game.phase is ProductionPhase.MODE_DECISION

    choose_spy = next(
        action
        for action in game.legal_actions()
        if action.payload.get("operation") == "choose_spy_path"
        and action.payload.get("path") == "ambitionist"
    )
    assert choose_spy.action_id
    assert variant.spy_path_choice is None
    assert variant.spy_path_pending is False
    assert variant.spy_path_locked is False
    assert variant.spy_path_chooser_id is None

    before_atomicity = _authoritative_atomicity_snapshot(game)
    before_legal_actions = game.legal_actions()

    original_invariants = game.assert_resolution_invariants

    def _failing_invariants() -> None:
        raise UnsupportedRuleError("Injected failure for spy path rollback proof")

    monkeypatch.setattr(game, "assert_resolution_invariants", _failing_invariants)
    with pytest.raises(UnsupportedRuleError, match="Injected failure for spy path"):
        _step(game, choose_spy)

    assert variant.spy_path_choice is None
    assert variant.spy_path_pending is False
    assert variant.spy_path_locked is False
    assert variant.spy_path_chooser_id is None
    after_atomicity = _authoritative_atomicity_snapshot(game)
    for field, expected in before_atomicity.items():
        assert after_atomicity[field] == expected, field
    assert game.legal_actions() == before_legal_actions

    monkeypatch.setattr(game, "assert_resolution_invariants", original_invariants)
    reissued_spy = next(
        action
        for action in game.legal_actions()
        if action.payload.get("operation") == "choose_spy_path"
        and action.payload.get("path") == "ambitionist"
    )
    assert reissued_spy.action_id == choose_spy.action_id
    _step(game, reissued_spy)

    assert variant.spy_path_choice == "ambitionist"
    assert variant.spy_path_pending is True
    assert variant.spy_path_locked is True
    assert variant.spy_path_chooser_id == "p8"


def test_c7_succession_choice_failure_rollback_atomicity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """C7 succession card choice failure rollback atomicity."""
    players = tuple(f"p{index}" for index in range(1, 9))
    role_original = {
        "p1": HeirAndSpyChoiceRole.LORD.value,
        "p2": HeirAndSpyChoiceRole.LOYALIST.value,
        "p3": HeirAndSpyChoiceRole.LOYALIST.value,
        "p4": HeirAndSpyChoiceRole.REBEL.value,
        "p5": HeirAndSpyChoiceRole.REBEL.value,
        "p6": HeirAndSpyChoiceRole.REBEL.value,
        "p7": HeirAndSpyChoiceRole.REBEL.value,
        "p8": HeirAndSpyChoiceRole.SPY.value,
    }
    variant = HeirAndSpyChoiceVariantState(
        original_lord_player_id="p1",
        current_lord_player_id="p1",
        role_original=dict(role_original),
        role_current=dict(role_original),
        heir_player_id="p2",
        heir_window_open=True,
    )
    configuration = FormalHeirAndSpyChoiceIdentityConfiguration.formal_profile()
    policy = HeirAndSpyChoiceModePolicy(
        configuration, players, "p1", variant
    )
    game = ProductionBasicCardBatch(
        seed=44,
        player_hp=(4,) * 8,
        player_max_hp=(4,) * 8,
        player_ids=players,
        outcome_policy=HeirAndSpyChoiceOutcomePolicy(role_original, "p1"),
        first_player_id="p3",
        mode_policy=policy,
        shuffle=False,
    )
    policy.bind_session(game)
    game._state = replace(
        game.state,
        players=tuple(
            replace(p, hp=0) if p.player_id == "p1" else p
            for p in game.state.players
        ),
        revision=game.state.revision + 1,
    )
    from scripts.sgs_engine.production_batch import _PendingOuterDeath
    game._state, game._runtime = game._c7_open_succession_window(
        game.state,
        replace(
            game.runtime,
            pending_lose_hp_dying=True,
            pending_damage_death_reason="heir_death_lose_hp",
            pending_outer_death=_PendingOuterDeath(
                dying_id="p1",
                final_damage_source="p3",
                kill_credit="p3",
            ),
        ),
        "p1",
        "p2",
    )
    assert game.phase is ProductionPhase.SUCCESSION_CARD_CHOICE

    succession_pass = next(
        action
        for action in game.legal_actions()
        if action.payload.get("operation") == "succession_obtain_none"
    )
    assert succession_pass.action_id
    assert variant.current_lord_player_id == "p1"
    assert variant.role_current["p2"] == "loyalist"

    before_atomicity = _authoritative_atomicity_snapshot(game)
    before_legal_actions = game.legal_actions()

    original_invariants = game.assert_resolution_invariants

    def _failing_invariants() -> None:
        raise UnsupportedRuleError("Injected failure for succession rollback proof")

    monkeypatch.setattr(game, "assert_resolution_invariants", _failing_invariants)
    with pytest.raises(UnsupportedRuleError, match="Injected failure for succession"):
        _step(game, succession_pass)

    assert variant.current_lord_player_id == "p1"
    assert variant.role_current["p2"] == "loyalist"
    assert variant.heir_player_id == "p2"
    assert variant.heir_window_open is True
    assert variant.successor_cannot_select_heir is False
    after_atomicity = _authoritative_atomicity_snapshot(game)
    for field, expected in before_atomicity.items():
        assert after_atomicity[field] == expected, field
    assert game.legal_actions() == before_legal_actions

    monkeypatch.setattr(game, "assert_resolution_invariants", original_invariants)
    reissued_pass = next(
        action
        for action in game.legal_actions()
        if action.payload.get("operation") == "succession_obtain_none"
    )
    assert reissued_pass.action_id == succession_pass.action_id
    _step(game, reissued_pass)

    assert variant.current_lord_player_id == "p2"
    assert variant.role_current["p2"] == "lord"
    assert variant.heir_player_id is None
    assert variant.heir_window_open is False
    assert variant.successor_cannot_select_heir is True


def test_c7_spy_conversion_turn_start_rollback_atomicity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """C7 spy conversion state mutation rollback atomicity."""
    players = tuple(f"p{index}" for index in range(1, 9))
    role_original = {
        "p1": HeirAndSpyChoiceRole.LORD.value,
        "p2": HeirAndSpyChoiceRole.LOYALIST.value,
        "p3": HeirAndSpyChoiceRole.LOYALIST.value,
        "p4": HeirAndSpyChoiceRole.REBEL.value,
        "p5": HeirAndSpyChoiceRole.REBEL.value,
        "p6": HeirAndSpyChoiceRole.REBEL.value,
        "p7": HeirAndSpyChoiceRole.REBEL.value,
        "p8": HeirAndSpyChoiceRole.SPY.value,
    }
    variant = HeirAndSpyChoiceVariantState(
        original_lord_player_id="p1",
        current_lord_player_id="p1",
        role_original=dict(role_original),
        role_current=dict(role_original),
        heir_window_open=False,
        spy_path_choice="ambitionist",
        spy_path_pending=True,
        spy_path_locked=True,
        spy_path_chooser_id="p8",
    )
    configuration = FormalHeirAndSpyChoiceIdentityConfiguration.formal_profile()
    policy = HeirAndSpyChoiceModePolicy(
        configuration, players, "p1", variant
    )
    game = ProductionBasicCardBatch(
        seed=45,
        player_hp=(4,) * 8,
        player_max_hp=(4,) * 8,
        player_ids=players,
        outcome_policy=HeirAndSpyChoiceOutcomePolicy(role_original, "p1"),
        first_player_id="p1",
        mode_policy=policy,
        shuffle=False,
    )
    policy.bind_session(game)
    pass_prepare = next(
        action
        for action in game.legal_actions()
        if action.payload.get("operation") == "proceed_prepare"
    )
    before_atomicity = _authoritative_atomicity_snapshot(game)
    before_legal_actions = game.legal_actions()

    original_invariants = game.assert_resolution_invariants

    def _failing_invariants() -> None:
        raise UnsupportedRuleError("Injected failure for spy conversion rollback proof")

    monkeypatch.setattr(game, "assert_resolution_invariants", _failing_invariants)
    with pytest.raises(UnsupportedRuleError, match="Injected failure for spy conversion"):
        _step(game, pass_prepare)

    assert variant.role_current["p8"] == "spy"
    assert variant.spy_path_pending is True
    assert variant.ambitionist_mark_available.get("p8") is None
    after_atomicity = _authoritative_atomicity_snapshot(game)
    for field, expected in before_atomicity.items():
        assert after_atomicity[field] == expected, field
    assert game.legal_actions() == before_legal_actions

    monkeypatch.setattr(game, "assert_resolution_invariants", original_invariants)
    reissued_pass = next(
        action
        for action in game.legal_actions()
        if action.payload.get("operation") == "proceed_prepare"
    )
    _step(game, reissued_pass)
