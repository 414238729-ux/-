from __future__ import annotations

import pytest
import scripts

from scripts.sgs_incremental_generals import (
    BottomDrawExhausted,
    CardEntity,
    ChenglueMode,
    ChenglueState,
    FeiliBranch,
    HuAction,
    JueCard,
    JueyongEndAction,
    JueyongState,
    QiaomengOption,
    ShicaiCardType,
    ShicaiTurnState,
    WuMarkState,
    XuYouRole,
    YicongBranch,
    YicongState,
    activate_yicong,
    add_wu_mark,
    base_hp_vulnerability_adjustment,
    chenglue_permission,
    draw_from_bottom,
    hu_action_allowed,
    resolve_chenglue,
    resolve_feili,
    resolve_jueyong_capture,
    resolve_jueyong_end_phase,
    resolve_pojiang,
    resolve_qiaomeng,
    resolve_shicai,
    resolve_wu_card_event,
    resolve_zengou_shared_name_replacement,
    start_wu_independent_turn,
    start_xu_you_play_phase,
    start_yicong_round,
    validate_zengou_sequence,
    xu_you_initial_stats,
    zengou_option_one_available,
    zengou_slash_exemption_active,
)


def card(card_id: str, name: str, suit: str | None = None) -> CardEntity:
    return CardEntity(card_id, name, suit)


def test_public_package_exports_incremental_general_interfaces() -> None:
    names = (
        "xu_you_initial_stats",
        "resolve_chenglue",
        "resolve_shicai",
        "draw_from_bottom",
        "resolve_zengou_shared_name_replacement",
        "resolve_feili",
        "resolve_pojiang",
        "resolve_jueyong_capture",
        "activate_yicong",
        "resolve_qiaomeng",
    )
    assert all(name in scripts.__all__ for name in names)
    assert all(hasattr(scripts, name) for name in names)


# ---------------------------------------------------------------------------
# 许攸


def test_xu_you_base_stats_are_uniquely_three_three() -> None:
    stats = xu_you_initial_stats()
    assert (stats.base_hp, stats.base_max_hp) == (3, 3)
    assert (stats.initial_hp, stats.initial_max_hp) == (3, 3)


@pytest.mark.parametrize("role", [XuYouRole.LORD, XuYouRole.LANDLORD])
def test_xu_you_lord_or_landlord_is_four_four_not_five_five(role: XuYouRole) -> None:
    stats = xu_you_initial_stats(role)
    assert (stats.base_hp, stats.base_max_hp) == (3, 3)
    assert (stats.initial_hp, stats.initial_max_hp) == (4, 4)


def test_xu_you_three_hp_baseline_reaches_target_scoring_even_with_role_bonus() -> None:
    normal = xu_you_initial_stats()
    landlord = xu_you_initial_stats(XuYouRole.LANDLORD)
    assert base_hp_vulnerability_adjustment(normal) == pytest.approx(0.45)
    assert base_hp_vulnerability_adjustment(landlord) == pytest.approx(0.45)


def test_chenglue_yang_draws_first_then_discards_and_grants_actual_suits() -> None:
    result = resolve_chenglue(
        ChenglueState(),
        hand_before=(card("h1", "闪", "红桃"), card("h2", "桃", "方块")),
        drawn_cards=(card("d1", "杀", "黑桃"),),
        discard_card_ids=("h2", "d1"),
    )
    assert result.discarded_card_ids == ("h2", "d1")
    assert result.granted_suits == frozenset({"方块", "黑桃"})
    assert result.state_after.mode is ChenglueMode.YIN
    assert result.state_after.used_this_play_phase is True
    assert tuple(c.card_id for c in result.hand_after) == ("h1",)


def test_chenglue_can_activate_with_insufficient_cards_and_only_actual_discard_counts() -> None:
    result = resolve_chenglue(
        ChenglueState(),
        hand_before=(),
        drawn_cards=(card("d1", "杀", "梅花"),),
        discard_card_ids=("d1",),
    )
    assert result.granted_suits == frozenset({"梅花"})
    assert result.hand_after == ()


def test_chenglue_is_once_per_play_phase_and_only_nonconverted_matching_suit_ignores_limits() -> None:
    resolved = resolve_chenglue(
        ChenglueState(),
        hand_before=(card("h1", "闪", "红桃"),),
        drawn_cards=(card("d1", "杀", "黑桃"),),
        discard_card_ids=("h1", "d1"),
    )
    permission = chenglue_permission(
        resolved.state_after, card_suit="红桃", is_converted=False
    )
    assert permission.ignore_distance and permission.ignore_frequency
    assert permission.other_legality_still_required
    assert not chenglue_permission(
        resolved.state_after, card_suit="红桃", is_converted=True
    ).ignore_distance
    with pytest.raises(ValueError, match="已经发动过"):
        resolve_chenglue(
            resolved.state_after,
            hand_before=(),
            drawn_cards=(card("x1", "桃", "红桃"), card("x2", "闪", "方块")),
            discard_card_ids=("x1",),
        )
    reset = start_xu_you_play_phase(resolved.state_after)
    assert reset.mode is ChenglueMode.YIN
    assert not reset.used_this_play_phase and not reset.unrestricted_suits


def test_shicai_nullification_cancelled_card_can_trigger_but_true_invalidation_cannot() -> None:
    cancelled = resolve_shicai(
        ShicaiTurnState(),
        card_type=ShicaiCardType.TRICK,
        physical_card_ids=("t1",),
        card_use_completed=True,
        effect_cancelled_by_nullification=True,
    )
    assert cancelled.can_trigger and cancelled.topdeck_card_ids == ("t1",)
    assert cancelled.draw_count == 1

    invalid = resolve_shicai(
        ShicaiTurnState(),
        card_type=ShicaiCardType.TRICK,
        physical_card_ids=("t2",),
        card_use_completed=False,
        card_or_effect_invalidated=True,
    )
    assert not invalid.can_trigger
    assert not invalid.type_recorded


def test_shicai_delayed_trick_occupies_type_but_cannot_topdeck() -> None:
    delayed = resolve_shicai(
        ShicaiTurnState(),
        card_type="锦囊牌",
        physical_card_ids=("delay",),
        card_use_completed=True,
        delayed_trick=True,
    )
    assert not delayed.can_trigger
    assert delayed.type_recorded
    next_trick = resolve_shicai(
        delayed.state_after,
        card_type="锦囊牌",
        physical_card_ids=("normal",),
        card_use_completed=True,
    )
    assert not next_trick.can_trigger


def test_shicai_multi_entity_order_and_moved_entity_boundary() -> None:
    multi = resolve_shicai(
        ShicaiTurnState(),
        card_type="基本牌",
        physical_card_ids=("a", "b"),
        topdeck_order=("b", "a"),
        card_use_completed=True,
    )
    assert multi.topdeck_card_ids == ("b", "a")
    moved = resolve_shicai(
        ShicaiTurnState(),
        card_type="装备牌",
        physical_card_ids=("e",),
        card_use_completed=True,
        entities_movable=False,
    )
    assert moved.type_recorded and not moved.can_trigger


def test_cunmu_draws_sequentially_from_bottom_and_exact_last_card_is_not_failure() -> None:
    result = draw_from_bottom(("top", "middle", "bottom"), 3)
    assert result.drawn_card_ids == ("bottom", "middle", "top")
    assert result.deck_after == ()


def test_cunmu_reshuffles_then_continues_from_new_bottom_reproducibly() -> None:
    first = draw_from_bottom(("only",), 3, discard_pile=("d1", "d2"), seed=19)
    second = draw_from_bottom(("only",), 3, discard_pile=("d1", "d2"), seed=19)
    assert first == second
    assert first.drawn_card_ids[0] == "only"
    assert first.reshuffle_count == 1


def test_cunmu_reports_draw_exhaustion_only_when_another_card_is_still_required() -> None:
    with pytest.raises(BottomDrawExhausted) as exc_info:
        draw_from_bottom(("last",), 2)
    assert exc_info.value.drawn_card_ids == ("last",)


# ---------------------------------------------------------------------------
# 清河公主


def test_zengou_first_option_requires_a_complete_distinct_two_card_sequence() -> None:
    assert not zengou_option_one_available({"杀": ("火杀",)})
    assert zengou_option_one_available({"杀": ("桃",)})
    sequence = validate_zengou_sequence(
        selected_first="火杀",
        selected_second="桃",
        legal_first_names=("杀",),
        legal_second_names_after_first=("桃", "酒"),
    )
    assert (sequence.first_card_name, sequence.second_card_name) == ("杀", "桃")
    assert sequence.ignores_normal_frequency and sequence.requires_other_legality
    with pytest.raises(ValueError, match="不同牌名"):
        validate_zengou_sequence(
            selected_first="杀",
            selected_second="雷杀",
            legal_first_names=("杀",),
            legal_second_names_after_first=("杀",),
        )


def test_zengou_shared_names_are_snapshotted_and_slash_shortage_is_accepted() -> None:
    result = resolve_zengou_shared_name_replacement(
        qinghe_id="Q",
        target_id="T",
        qinghe_hand=(card("q_peach", "桃"), card("q_slash", "杀")),
        target_hand=(card("t_peach", "桃"),),
        deck=(card("deck_slash", "杀"), card("deck_flash", "闪")),
        seed=2,
    )
    # 开始替换前只有“桃”为共有牌名；清河取得杀后不会把“杀”追加进共有集合。
    assert result.shared_name_snapshot == frozenset({"桃"})
    assert result.qinghe_replaced_card_ids == ("q_peach",)
    assert result.target_replaced_card_ids == ("t_peach",)
    assert len(result.qinghe_slash_card_ids) == 1
    assert len(result.target_slash_card_ids) <= 1


def test_zengou_slash_hand_limit_exemption_is_bound_to_entity_and_original_owner() -> None:
    result = resolve_zengou_shared_name_replacement(
        qinghe_id="Q",
        target_id="T",
        qinghe_hand=(card("q", "桃"),),
        target_hand=(card("t", "桃"),),
        deck=(card("s1", "杀"), card("s2", "杀")),
        seed=1,
    )
    slash_id = result.qinghe_slash_card_ids[0]
    assert zengou_slash_exemption_active(
        result,
        card_id=slash_id,
        current_owner_id="Q",
        still_in_owner_hand=True,
        owner_next_end_phase_reached=False,
    )
    assert not zengou_slash_exemption_active(
        result,
        card_id=slash_id,
        current_owner_id="T",
        still_in_owner_hand=True,
        owner_next_end_phase_reached=False,
    )
    assert not zengou_slash_exemption_active(
        result,
        card_id=slash_id,
        current_owner_id="Q",
        still_in_owner_hand=False,
        owner_next_end_phase_reached=False,
    )
    # 离手后即使回到原取得者手里，也不能恢复免计手牌上限状态。
    assert not zengou_slash_exemption_active(
        result,
        card_id=slash_id,
        current_owner_id="Q",
        still_in_owner_hand=True,
        owner_next_end_phase_reached=False,
        ever_left_original_owner_hand=True,
    )


def test_wu_marks_do_not_stack_same_name_and_ordinary_response_does_not_occupy_first_use() -> None:
    state = add_wu_mark(add_wu_mark(WuMarkState(), "火杀"), "杀")
    assert state.mark_names == frozenset({"杀"})
    response = resolve_wu_card_event(
        state,
        event_is_use=False,
        original_entity_name="杀",
    )
    assert not response.occupied_first_use
    assert not response.state_after.first_use_checked_this_turn


def test_wu_first_use_uses_original_entity_name_unless_name_is_explicitly_rewritten() -> None:
    state = WuMarkState(frozenset({"桃", "杀"}))
    transformed = resolve_wu_card_event(
        state,
        event_is_use=True,
        original_entity_name="桃",
    )
    assert transformed.hp_loss == 1
    assert transformed.checked_card_name == "桃"
    assert transformed.state_after.mark_names == frozenset({"杀"})
    reset = start_wu_independent_turn(transformed.state_after)
    rewritten = resolve_wu_card_event(
        reset,
        event_is_use=True,
        original_entity_name="桃",
        explicitly_rewritten_name="杀",
    )
    assert rewritten.hp_loss == 1
    assert rewritten.checked_card_name == "杀"


def test_wu_nonbasic_first_use_occupies_check_without_matching_basic_mark() -> None:
    result = resolve_wu_card_event(
        WuMarkState(frozenset({"杀"})),
        event_is_use=True,
        original_entity_name="决斗",
    )
    assert result.occupied_first_use
    assert not result.matched_mark and result.hp_loss == 0
    assert result.state_after.mark_names == frozenset({"杀"})


def test_feili_prevents_entire_damage_event_and_checks_each_branch_cost() -> None:
    ordinary = resolve_feili(
        incoming_damage=3,
        branch=FeiliBranch.DISCARD_TWO,
        qinghe_has_zengou=True,
        discardable_card_count=2,
    )
    assert ordinary.damage_after == 0 and ordinary.prevented_entire_event
    assert ordinary.discarded_count == 2
    with pytest.raises(ValueError, match="两张牌"):
        resolve_feili(
            incoming_damage=1,
            branch=FeiliBranch.DISCARD_TWO,
            qinghe_has_zengou=True,
            discardable_card_count=1,
        )


def test_feili_alternative_removes_only_source_marks_draws_two_and_blocks_that_source() -> None:
    result = resolve_feili(
        incoming_damage=2,
        branch=FeiliBranch.REMOVE_SOURCE_WU,
        qinghe_has_zengou=True,
        discardable_card_count=0,
        source_id="enemy-a",
        source_wu_names=("杀", "桃"),
    )
    assert result.removed_wu_names == frozenset({"杀", "桃"})
    assert result.draw_count == 2
    assert result.newly_blocked_zengou_source == "enemy-a"


# ---------------------------------------------------------------------------
# 傅佥


def test_jueyong_captures_first_eligible_physical_single_target_cards_up_to_current_hp() -> None:
    state = JueyongState()
    for index in range(2):
        result = resolve_jueyong_capture(
            state,
            fu_qian_id="F",
            current_hp=2,
            card=JueCard(f"c{index}", "杀", "E"),
            target_ids=("F",),
        )
        assert result.captured and result.target_cancelled
        assert result.derived_target_effects_invalid
        assert result.card_still_counted_as_used
        state = result.state_after
    full = resolve_jueyong_capture(
        state,
        fu_qian_id="F",
        current_hp=2,
        card=JueCard("c2", "决斗", "E"),
        target_ids=("F",),
    )
    assert not full.captured


@pytest.mark.parametrize(
    "card_kwargs,targets",
    [
        ({"is_virtual": True}, ("F",)),
        ({"is_converted": True}, ("F",)),
        ({"used_by_jueyong": True}, ("F",)),
        ({}, ("F", "X")),
    ],
)
def test_jueyong_bypass_conditions(card_kwargs: dict[str, bool], targets: tuple[str, ...]) -> None:
    result = resolve_jueyong_capture(
        JueyongState(),
        fu_qian_id="F",
        current_hp=4,
        card=JueCard("c", "杀", "E", **card_kwargs),
        target_ids=targets,
    )
    assert not result.captured


def test_pojiang_gives_area_card_draws_three_clears_jue_and_loses_hp_not_damage() -> None:
    state = JueyongState((JueCard("j1", "杀", "E"), JueCard("j2", "决斗", "E")))
    result = resolve_pojiang(
        current_hp=1,
        self_id="F",
        recipient_id="R",
        give_card_id="equip",
        hand_card_ids=("hand",),
        equipment_card_ids=("equip",),
        drawn_card_ids=("d1", "d2", "d3"),
        jue_state=state,
    )
    assert result.discarded_jue_card_ids == ("j1", "j2")
    assert result.hand_limit_exempt_card_ids == frozenset({"d1", "d2", "d3"})
    assert result.current_hp_after == 0 and result.enters_dying
    assert result.lost_hp == 1 and not result.loss_is_damage


def test_jueyong_end_phase_is_fifo_and_does_not_ignore_distance_or_target_legality() -> None:
    state = JueyongState(
        (
            JueCard("first", "杀", "A"),
            JueCard("second", "顺手牵羊", "B"),
            JueCard("third", "决斗", "dead"),
        )
    )
    result = resolve_jueyong_end_phase(
        state,
        living_user_ids=("A", "B"),
        currently_legal_reuse_card_ids=("first",),
    )
    assert [event.card_id for event in result.events] == ["first", "second", "third"]
    assert result.events[0].action is JueyongEndAction.REUSE
    assert result.events[1].action is JueyongEndAction.DISCARD
    assert "距离" in result.events[1].reason
    assert result.events[0].ignores_timing and result.events[0].ignores_frequency
    assert not result.events[0].ignores_distance
    assert result.state_after.jue_cards == ()


def test_jueyong_same_delayed_tricks_can_wait_in_jue_but_only_first_can_enter_judgment() -> None:
    state = JueyongState(
        (
            JueCard("l1", "乐不思蜀", "A", delayed_trick=True),
            JueCard("l2", "乐不思蜀", "B", delayed_trick=True),
        )
    )
    result = resolve_jueyong_end_phase(
        state,
        living_user_ids=("A", "B"),
        currently_legal_reuse_card_ids=("l1", "l2"),
    )
    assert result.events[0].action is JueyongEndAction.REUSE
    assert result.events[1].action is JueyongEndAction.DISCARD
    assert result.judgment_delayed_trick_names_after == frozenset({"乐不思蜀"})


# ---------------------------------------------------------------------------
# 谋·公孙瓒


def test_yicong_initial_charge_cap_and_zero_spend_rejected() -> None:
    state = YicongState()
    assert state.charge == 2 and len(state.hu_cards) == 0
    with pytest.raises(ValueError, match="不能小于1"):
        activate_yicong(
            state,
            spend_charge=0,
            branch=YicongBranch.ATTACK,
            deck=(),
        )


def test_yicong_can_overspend_beyond_hu_slots_and_keeps_public_entities() -> None:
    existing = (
        card("h1", "闪"),
        card("h2", "杀"),
        card("h3", "闪"),
    )
    state = YicongState(charge=4, hu_cards=existing)
    deck = (card("s1", "杀"), card("s2", "杀"), card("x", "桃"))
    result = activate_yicong(
        state,
        spend_charge=4,
        branch="进攻",
        deck=deck,
        seed=7,
    )
    assert result.spent_charge == 4
    assert result.state_after.charge == 0
    assert len(result.acquired_hu_card_ids) == 1
    assert len(result.state_after.hu_cards) == 4
    assert result.state_after.outgoing_actual_distance_modifier == -1
    assert result.state_after.incoming_actual_distance_modifier == 0


def test_yicong_shortage_and_fixed_seed_are_reproducible_and_old_hu_persist_next_round() -> None:
    state = YicongState(charge=3)
    deck = (card("f1", "闪"), card("f2", "闪"), card("s", "杀"))
    first = activate_yicong(state, spend_charge=3, branch="防守", deck=deck, seed=5)
    second = activate_yicong(state, spend_charge=3, branch="防守", deck=deck, seed=5)
    assert first == second
    assert len(first.acquired_hu_card_ids) == 2
    assert first.state_after.incoming_actual_distance_modifier == 1
    next_round = start_yicong_round(first.state_after)
    assert next_round.hu_cards == first.state_after.hu_cards
    assert next_round.outgoing_actual_distance_modifier == 0
    assert next_round.incoming_actual_distance_modifier == 0


def test_hu_is_not_hand_but_can_be_used_responded_or_used_as_zhangba_material() -> None:
    for action in (HuAction.USE, HuAction.RESPOND, HuAction.ZHANGBA_MATERIAL):
        assert hu_action_allowed(action, hand_card_use_prohibited=True)
    for action in (
        HuAction.DISCARD_HAND_COST,
        HuAction.GIVE_HAND_COST,
        HuAction.SHOW_HAND_COST,
        HuAction.EXCHANGE_HAND_COST,
        HuAction.COUNT_AS_HAND,
    ):
        assert not hu_action_allowed(action)
    assert not hu_action_allowed(HuAction.USE, all_card_use_or_response_prohibited=True)
    assert not hu_action_allowed(HuAction.RESPOND, specific_card_name_prohibited=True)


def test_qiaomeng_triggers_once_per_actual_slash_damage_event_even_for_two_damage() -> None:
    result = resolve_qiaomeng(
        actual_damage=2,
        damage_is_from_slash=True,
        owns_yicong=True,
        option=QiaomengOption.DISCARD_AND_DRAW,
        current_charge=1,
        target_has_area_card=True,
    )
    assert result.triggered and result.trigger_count_for_event == 1
    assert result.discarded_count == 1 and result.draw_count == 1


def test_qiaomeng_first_option_still_draws_when_target_has_no_area_cards() -> None:
    result = resolve_qiaomeng(
        actual_damage=1,
        damage_is_from_slash=True,
        owns_yicong=True,
        option="弃置区域牌并摸一张",
        current_charge=0,
        target_has_area_card=False,
    )
    assert result.triggered and result.discarded_count == 0 and result.draw_count == 1


def test_qiaomeng_charge_is_capped_and_requires_actual_slash_damage_and_yicong() -> None:
    charged = resolve_qiaomeng(
        actual_damage=1,
        damage_is_from_slash=True,
        owns_yicong=True,
        option="获得三点蓄力",
        current_charge=3,
        target_has_area_card=False,
    )
    assert charged.charge_after == 4
    prevented = resolve_qiaomeng(
        actual_damage=0,
        damage_is_from_slash=True,
        owns_yicong=True,
        option="获得三点蓄力",
        current_charge=2,
        target_has_area_card=False,
    )
    lost_skill = resolve_qiaomeng(
        actual_damage=1,
        damage_is_from_slash=True,
        owns_yicong=False,
        option="获得三点蓄力",
        current_charge=2,
        target_has_area_card=False,
    )
    assert not prevented.triggered and not lost_skill.triggered
