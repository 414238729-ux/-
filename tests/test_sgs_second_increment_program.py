from __future__ import annotations

import pytest
import scripts

from scripts.sgs_general_rules import (
    CORE_LORD_POOL,
    EVALUATION_ONLY_GENERAL_NAMES,
    GENERAL_CANDIDATE_SLOTS,
    SPECIALIZED_LORD_POOL,
    build_lord_evaluation_plan,
    lord_eight_player_initial_stats,
)
from scripts.sgs_incremental_mechanics import (
    PhysicalCardIdentity,
    actual_distance_within_limit,
    count_current_hand_slashes,
    resolve_explicit_damage_source,
    resolve_generated_card_after_source_death,
)
from scripts.sgs_modes import (
    standard_eight_player_mulligan_limit,
    standard_eight_player_setup,
    two_v_two_hand_information,
)
from scripts.sgs_special_general_rules import (
    ColoredHandCard,
    QuediChoice,
    QuediTurnState,
    RectificationCardRecord,
    RectificationReward,
    RectificationTask,
    ShijiVictimInput,
    TaoluanChoice,
    TaoluanTurnState,
    WENYANG_ROUTE_TAUNT,
    WenyangRoute,
    XionghuoPunishment,
    XionghuoState,
    XueyiTurnState,
    assign_xionghuo_brutality,
    create_jiejian_mark,
    evaluate_rectification,
    mou_yuanshao_has_guaranteed_other_qun,
    resolve_chongjian_recipients,
    resolve_choujue_kill,
    resolve_jiejian_marked_turn_end,
    resolve_jiejian_target_event,
    resolve_mutao,
    resolve_quedi,
    resolve_shajue,
    resolve_shiji_chain,
    resolve_taoluan,
    resolve_taoluan_fire_slash,
    resolve_xionghuo_play_phase_start,
    resolve_xueyi_targets,
    resolve_yimou_gain_random_slash,
    resolve_zhuifeng_generated_duel,
    resolve_zujin_conversion,
    ruoyu_can_awaken,
    should_xurong_spy_attack,
    start_zujin_global_turn,
    xionghuo_chain_damages,
    yanzhu_option_one_available,
    yimou_trigger_count,
)
from scripts.sgs_team_strategy import (
    FarmerCoordinationKnowledge,
    FarmerPeachKnowledge,
    FarmerSlashCountKnowledge,
)


def card(
    card_id: str,
    current_name: str,
    *,
    original_name: str | None = None,
    use_as: str | None = None,
    zone: str = "手牌区",
    counts_as_hand: bool = True,
) -> PhysicalCardIdentity:
    return PhysicalCardIdentity(
        card_id,
        original_name or current_name,
        current_name,
        use_as,
        zone,
        counts_as_hand,
    )


# ---------------------------------------------------------------------------
# 模式、池与信息边界


def test_public_exports_include_second_increment_interfaces() -> None:
    names = {
        "standard_eight_player_setup",
        "count_current_hand_slashes",
        "resolve_mutao",
        "resolve_shajue",
        "resolve_zujin_conversion",
        "resolve_zhuifeng_generated_duel",
        "resolve_taoluan",
    }
    assert names <= set(scripts.__all__)
    assert all(hasattr(scripts, name) for name in names)


def test_standard_eight_player_is_one_two_four_one_without_limited_state_machine() -> None:
    setup = standard_eight_player_setup()
    assert dict(setup.identity_counts) == {"主公": 1, "忠臣": 2, "反贼": 4, "内奸": 1}
    assert setup.limited_variant_enabled is False
    assert setup.mulligan_limit == standard_eight_player_mulligan_limit() == 8


def test_ordinary_pool_is_thirteen_and_isolated_from_lord_and_huangfusong_pools() -> None:
    assert len(GENERAL_CANDIDATE_SLOTS) == len(set(GENERAL_CANDIDATE_SLOTS)) == 13
    assert GENERAL_CANDIDATE_SLOTS.count("曹纯") == 1
    assert "鲍信" in GENERAL_CANDIDATE_SLOTS
    assert "谋皇甫嵩" in EVALUATION_ONLY_GENERAL_NAMES
    assert not EVALUATION_ONLY_GENERAL_NAMES & set(GENERAL_CANDIDATE_SLOTS)
    assert not (set(CORE_LORD_POOL) | set(SPECIALIZED_LORD_POOL)) & set(GENERAL_CANDIDATE_SLOTS)
    assert "界曹丕" in CORE_LORD_POOL and "标曹丕" in SPECIALIZED_LORD_POOL
    assert "界孙权" in CORE_LORD_POOL and "谋张角" in SPECIALIZED_LORD_POOL


def test_lord_evaluation_forces_tested_lord_and_preregisters_subpools() -> None:
    plan = build_lord_evaluation_plan(
        "鲍信",
        synergy_lords=("曹叡",),
        counter_lords=("谋张角",),
    )
    assert plan.tested_lord == "鲍信"
    assert plan.synergy_lords == ("曹叡",)
    assert plan.counter_lords == ("谋张角",)
    assert lord_eight_player_initial_stats("曹叡") == (4, 4)
    assert lord_eight_player_initial_stats("界孙权") == (5, 5)
    assert lord_eight_player_initial_stats("界董卓") == (9, 9)


def test_information_permissions_keep_identity_hidden_two_v_two_visible_and_farmer_signal_narrow() -> None:
    assert two_v_two_hand_information(1, 4).actual_visibility.value == "可见"
    assert two_v_two_hand_information(1, 2).actual_visibility.value == "隐藏"
    peach = FarmerPeachKnowledge("农民甲", "has_peach")
    slash = FarmerSlashCountKnowledge("农民甲", 3)
    combined = FarmerCoordinationKnowledge(peach, slash)
    assert slash.current_slash_count == 3 and slash.exact_quantity_known
    assert not slash.discloses_other_card_names
    assert not slash.discloses_suits_or_ranks
    assert not combined.reveals_full_hand
    assert peach.minimum_known_peaches == 1
    invalidated = slash.after_hand_change()
    assert invalidated.current_slash_count is None
    assert not invalidated.exact_quantity_known


# ---------------------------------------------------------------------------
# 跨武将通用结算


def test_current_card_name_counts_as_slash_but_use_as_only_and_special_zone_do_not() -> None:
    cards = (
        card("s1", "杀"),
        card("s2", "火杀"),
        card("s3", "雷杀"),
        card("s4", "杀", original_name="闪"),
        card("m1", "闪", use_as="杀"),
        card("z1", "杀", zone="武将牌旁", counts_as_hand=False),
    )
    assert count_current_hand_slashes(cards) == 4


def test_distance_one_or_less_includes_self_distance_zero() -> None:
    assert actual_distance_within_limit(0, 1)
    assert actual_distance_within_limit(1, 1)
    assert not actual_distance_within_limit(2, 1)


def test_generated_card_continues_after_source_death_but_stops_when_dead_source_must_respond() -> None:
    continues = resolve_generated_card_after_source_death(
        generated_legally=True,
        source_alive=False,
    )
    stops = resolve_generated_card_after_source_death(
        generated_legally=True,
        source_alive=False,
        next_step_requires_source_action=True,
    )
    assert continues.continues_after_source_death and continues.next_step_can_be_performed
    assert stops.continues_after_source_death and not stops.next_step_can_be_performed
    assert stops.resolution_ends_now


def test_explicit_actor_is_damage_source_and_receives_identity_kill_consequence() -> None:
    result = resolve_explicit_damage_source(actor_id="原目标", skill_owner_id="鲍信", target_id="末位")
    assert result.source_id == result.kill_reward_or_penalty_owner_id == "原目标"
    assert result.skill_owner_id == "鲍信"


# ---------------------------------------------------------------------------
# 徐荣


def test_each_xionghuo_chain_recipient_independently_gets_plus_one() -> None:
    result = xionghuo_chain_damages((("甲", 1, True), ("乙", 1, True), ("丙", 1, False)))
    assert dict(result) == {"甲": 2, "乙": 2, "丙": 1}


def test_xionghuo_starts_with_three_and_cannot_duplicate_or_mark_self() -> None:
    state = XionghuoState()
    after = assign_xionghuo_brutality(state, xurong_id="徐荣", target_id="甲")
    assert state.available_brutality == 3
    assert after.available_brutality == 2 and after.marked_other_ids == {"甲"}
    with pytest.raises(ValueError, match="已经有暴戾"):
        assign_xionghuo_brutality(after, xurong_id="徐荣", target_id="甲")
    with pytest.raises(ValueError, match="其他角色"):
        assign_xionghuo_brutality(after, xurong_id="徐荣", target_id="徐荣")


def test_xionghuo_random_take_checks_hand_and_equipment_independently_and_is_reproducible() -> None:
    first = resolve_xionghuo_play_phase_start(
        punishment=XionghuoPunishment.TAKE_CARDS,
        hand_card_ids=("h1", "h2"),
        equipment_card_ids=(),
        seed=7,
    )
    second = resolve_xionghuo_play_phase_start(
        punishment=XionghuoPunishment.TAKE_CARDS,
        hand_card_ids=("h1", "h2"),
        equipment_card_ids=(),
        seed=7,
    )
    assert first == second
    assert first.obtained_hand_card_id in {"h1", "h2"}
    assert first.obtained_equipment_card_id is None


def test_shajue_only_triggers_below_zero_and_unavailable_card_does_not_get_created() -> None:
    assert not resolve_shajue(
        target_is_other=True,
        hp_after_damage=0,
        damage_card_id="d1",
        damage_card_obtainable=True,
    ).triggered
    unavailable = resolve_shajue(
        target_is_other=True,
        hp_after_damage=-1,
        damage_card_id="d1",
        damage_card_obtainable=False,
    )
    assert unavailable.triggered and unavailable.brutality_gained == 1
    assert unavailable.obtained_damage_card_id is None


def test_xurong_spy_can_decline_low_value_attack() -> None:
    assert not should_xurong_spy_attack(-0.1)
    assert not should_xurong_spy_attack(0)
    assert should_xurong_spy_attack(0.1)


# ---------------------------------------------------------------------------
# 王经


def test_zujin_tracks_three_converted_names_separately_per_global_turn() -> None:
    state = start_zujin_global_turn("甲的回合")
    slash = resolve_zujin_conversion(
        state,
        converted_name="杀",
        current_hp=2,
        maximum_hp=3,
        all_alive_hp=(1, 2, 3),
    )
    dodge = resolve_zujin_conversion(
        slash.state_after,
        converted_name="闪",
        current_hp=2,
        maximum_hp=3,
        all_alive_hp=(1, 2, 3),
    )
    nullification = resolve_zujin_conversion(
        dodge.state_after,
        converted_name="无懈可击",
        current_hp=2,
        maximum_hp=3,
        all_alive_hp=(1, 2, 3),
    )
    repeated = resolve_zujin_conversion(
        nullification.state_after,
        converted_name="杀",
        current_hp=2,
        maximum_hp=3,
        all_alive_hp=(1, 2, 3),
    )
    assert slash.legal and dodge.legal and nullification.legal
    assert not repeated.legal


def test_zujin_wounded_tied_for_global_minimum_cannot_convert_slash() -> None:
    result = resolve_zujin_conversion(
        start_zujin_global_turn("甲的回合"),
        converted_name="杀",
        current_hp=2,
        maximum_hp=3,
        all_alive_hp=(2, 2, 4),
    )
    assert not result.legal
    assert "并列最低" in result.reason


def test_jiejian_does_not_trigger_on_direct_attack_to_wang_but_intercepts_marked_beneficial_card() -> None:
    mark = create_jiejian_mark(
        wangjing_id="王经",
        marked_id="敌人",
        marked_current_hp=2,
        given_card_ids=("gift",),
    )
    direct = resolve_jiejian_target_event(
        mark,
        global_turn_id="敌人回合",
        target_ids=("王经",),
        delayed_trick=False,
    )
    peach = resolve_jiejian_target_event(
        mark,
        global_turn_id="敌人回合",
        target_ids=("敌人",),
        delayed_trick=False,
    )
    assert not direct.triggered
    assert peach.triggered and peach.target_redirected_to == "王经" and peach.draw_count == 1


def test_jiejian_delayed_trick_draws_without_redirect_and_once_per_character_turn() -> None:
    mark = create_jiejian_mark(
        wangjing_id="王经",
        marked_id="队友",
        marked_current_hp=3,
        given_card_ids=("g1",),
    )
    delayed = resolve_jiejian_target_event(
        mark,
        global_turn_id="甲回合",
        target_ids=("队友",),
        delayed_trick=True,
    )
    repeated = resolve_jiejian_target_event(
        delayed.state_after,
        global_turn_id="甲回合",
        target_ids=("队友",),
        delayed_trick=False,
    )
    assert delayed.triggered and delayed.target_redirected_to is None
    assert delayed.delayed_trick_stays_on_original_target
    assert not repeated.triggered
    retained = resolve_jiejian_marked_turn_end(
        delayed.state_after,
        marked_current_hp=3,
        entire_turn_skipped=True,
    )
    assert not retained.mark_removed and retained.state_after is not None


# ---------------------------------------------------------------------------
# 文鸯


def test_quedi_backwater_order_allows_newly_obtained_basic_card_to_pay_second_step() -> None:
    result = resolve_quedi(
        QuediTurnState(),
        choice=QuediChoice.BACKWATER,
        target_hand_card_ids=("basic-new",),
        selected_obtained_card_id="basic-new",
        selected_obtained_card_is_basic=True,
        basic_card_ids_before=(),
        selected_discard_card_id="basic-new",
    )
    assert result.obtained_card_id == result.discarded_basic_card_id == "basic-new"
    assert result.damage_bonus == 1 and result.maximum_hp_loss == 1
    assert result.event_order == (
        "获得目标一张手牌",
        "弃置一张基本牌并令伤害加一",
        "最后减少一点体力上限",
    )


def test_quedi_newly_obtained_nonbasic_card_cannot_pay_basic_cost() -> None:
    with pytest.raises(ValueError, match="基本牌"):
        resolve_quedi(
            QuediTurnState(),
            choice=QuediChoice.BACKWATER,
            target_hand_card_ids=("trick-new",),
            selected_obtained_card_id="trick-new",
            selected_obtained_card_is_basic=False,
            selected_discard_card_id="trick-new",
        )


def test_choujue_extra_quedi_uses_stack_per_kill() -> None:
    state = QuediTurnState()
    first = resolve_choujue_kill(state)
    second = resolve_choujue_kill(first.quedi_state_after)
    assert second.quedi_state_after.extra_uses_from_kills == 2
    assert second.quedi_state_after.use_limit == 3


def test_wei_wenyang_dies_from_hp_loss_but_generated_duel_reaches_target_response_then_ends() -> None:
    result = resolve_zhuifeng_generated_duel(
        current_hp=1,
        uses_this_play_phase=0,
        target_plays_slash=True,
    )
    assert result.entered_dying and result.source_died and result.generated_duel_started
    assert result.target_played_slash
    assert not result.source_can_play_next_slash
    assert result.duel_ended


def test_wei_wenyang_can_be_rescued_after_hp_loss_and_then_continue_duel() -> None:
    result = resolve_zhuifeng_generated_duel(
        current_hp=1,
        uses_this_play_phase=0,
        target_plays_slash=True,
        rescued_after_hp_loss=True,
    )
    assert result.entered_dying and not result.source_died
    assert result.source_can_play_next_slash and not result.duel_ended


def test_wu_wenyang_cannot_take_directly_killed_target_equipment_but_checks_each_living_chain_recipient() -> None:
    results = resolve_chongjian_recipients(
        (
            ("直接目标", 2, False, ("武器", "防具")),
            ("传导甲", 2, True, ("甲武器", "甲防具", "甲坐骑")),
            ("传导乙", 1, True, ("乙防具",)),
        )
    )
    assert results[0].obtained_equipment_card_ids == ()
    assert results[1].obtained_equipment_card_ids == ("甲武器", "甲防具")
    assert results[2].obtained_equipment_card_ids == ("乙防具",)


def test_wu_wenyang_can_choose_fewer_and_nonprefix_equipment_cards() -> None:
    results = resolve_chongjian_recipients(
        (("目标", 2, True, ("武器", "防具", "坐骑")),),
        selected_equipment_by_target={"目标": ("坐骑",)},
    )
    assert results[0].obtained_equipment_card_ids == ("坐骑",)


def test_wei_and_wu_routes_do_not_share_one_fixed_taunt() -> None:
    assert WENYANG_ROUTE_TAUNT[WenyangRoute.WEI] != WENYANG_ROUTE_TAUNT[WenyangRoute.WU]


# ---------------------------------------------------------------------------
# 主公裁定


def test_lord_special_rulings_yanzhu_ruoyu_yuanshao_and_xueyi() -> None:
    assert not yanzhu_option_one_available(0)
    assert yanzhu_option_one_available(1)
    assert ruoyu_can_awaken(2, (2, 2, 3, 4))
    assert mou_yuanshao_has_guaranteed_other_qun(
        lord_player_id="主公",
        factions_by_player={"主公": "群", "反贼": "群", "忠臣": "魏"},
    )
    xueyi = resolve_xueyi_targets(("群", "魏", "群", "群"))
    assert xueyi.trigger_count == 3 and xueyi.draw_count == 2
    capped = resolve_xueyi_targets(
        ("群",),
        turn_state=xueyi.state_after,
    )
    assert capped.trigger_count == 1 and capped.draw_count == 0
    assert capped.state_after == XueyiTurnState(2)


# ---------------------------------------------------------------------------
# 鲍信


def test_mutao_empty_target_is_legal_without_distribution_or_damage() -> None:
    result = resolve_mutao(
        baoxin_id="鲍信",
        original_target_id="甲",
        living_ring=("甲", "乙", "丙"),
        hands_by_player={"甲": (), "乙": (), "丙": ()},
        seed=1,
    )
    assert result.activated and not result.distributed
    assert result.last_recipient_id is None and result.damage_amount == 0


def test_mutao_cycles_until_all_slashes_and_original_target_can_be_last_recipient() -> None:
    result = resolve_mutao(
        baoxin_id="鲍信",
        original_target_id="甲",
        living_ring=("甲", "乙", "丙"),
        hands_by_player={
            "甲": (card("s1", "杀"), card("s2", "火杀"), card("s3", "雷杀")),
            "乙": (),
            "丙": (),
        },
        seed=9,
    )
    assert [item.recipient_id for item in result.distributed] == ["乙", "丙", "甲"]
    assert result.last_recipient_id == "甲"
    assert result.damage_source is not None
    assert result.damage_source.source_id == "甲"
    assert result.damage_source.skill_owner_id == "鲍信"
    assert result.damage_is_attributeless and not result.damage_is_from_slash
    assert not result.can_respond_with_dodge


def test_mutao_damage_reads_last_recipient_total_current_slash_count_and_caps_two() -> None:
    result = resolve_mutao(
        baoxin_id="鲍信",
        original_target_id="甲",
        living_ring=("甲", "乙", "丙"),
        hands_by_player={
            "甲": tuple(card(f"s{i}", "杀") for i in range(4)),
            "乙": (card("old", "杀"),),
            "丙": (),
        },
        seed=3,
    )
    assert [item.recipient_id for item in result.distributed] == ["乙", "丙", "甲", "乙"]
    assert result.damage_amount == 2


def test_yimou_self_distance_and_independent_damage_event_counting() -> None:
    assert yimou_trigger_count(actual_damage=2, actual_distance_to_baoxin=0) == 1
    assert yimou_trigger_count(actual_damage=1, actual_distance_to_baoxin=1) == 1
    assert yimou_trigger_count(actual_damage=1, actual_distance_to_baoxin=2) == 0
    assert yimou_trigger_count(actual_damage=0, actual_distance_to_baoxin=0) == 0


def test_yimou_random_slash_search_is_reproducible_and_does_not_create_missing_card() -> None:
    deck = (card("a", "闪"), card("b", "杀"), card("c", "火杀"))
    first = resolve_yimou_gain_random_slash(deck, seed=22)
    second = resolve_yimou_gain_random_slash(deck, seed=22)
    assert first == second and first.obtained_card_id in {"b", "c"}
    assert resolve_yimou_gain_random_slash((card("a", "闪"),), seed=22).obtained_card_id is None


# ---------------------------------------------------------------------------
# 谋皇甫嵩


def test_shiji_reads_latest_hand_state_and_earlier_draws_can_block_later_chain_trigger() -> None:
    events = resolve_shiji_chain(
        huangfusong_id="皇甫嵩",
        huangfusong_hand_count=2,
        other_hand_counts={"甲": 3, "乙": 2},
        victims_in_order=(
            ShijiVictimInput("甲", (ColoredHandCard("r1", "红"), ColoredHandCard("r2", "红"), ColoredHandCard("b1", "黑"))),
            ShijiVictimInput("乙", (ColoredHandCard("r3", "红"), ColoredHandCard("b2", "黑"))),
        ),
    )
    assert events[0].triggered and events[0].draw_count == 2
    assert events[0].huangfusong_hand_count_after == 4
    assert not events[1].triggered


def test_taoluan_terminates_judgment_keeps_delayed_trick_and_routes_judgment_card() -> None:
    take = resolve_taoluan(
        judgment_suit="黑桃",
        judgment_card_id="judge",
        judged_character_is_self=True,
        choice=TaoluanChoice.TAKE_JUDGMENT_CARD,
        judgment_from_delayed_trick=True,
    )
    fire = resolve_taoluan(
        judgment_suit="黑桃",
        judgment_card_id="judge",
        judged_character_is_self=False,
        choice=TaoluanChoice.FIRE_SLASH,
        judgment_from_delayed_trick=True,
    )
    assert take.judgment_terminated and take.delayed_trick_remains_in_original_zone
    assert not take.delayed_trick_processed_again_this_turn
    assert take.judgment_card_destination == "谋皇甫嵩手牌"
    assert fire.judgment_card_destination == "弃牌堆"
    assert fire.virtual_fire_slash_generated and fire.ignores_distance and fire.ignores_normal_slash_quota


def test_taoluan_non_spade_needs_no_choice_and_does_not_consume_turn_limit() -> None:
    state = TaoluanTurnState()
    miss = resolve_taoluan(
        judgment_suit="红桃",
        judgment_card_id="j0",
        judged_character_is_self=False,
        turn_state=state,
    )
    assert not miss.triggered and not miss.delayed_trick_remains_in_original_zone
    assert miss.turn_state_after == state
    first = resolve_taoluan(
        judgment_suit="黑桃",
        judgment_card_id="j1",
        judged_character_is_self=True,
        choice=TaoluanChoice.TAKE_JUDGMENT_CARD,
        turn_state=miss.turn_state_after,
    )
    with pytest.raises(ValueError, match="已经发动过"):
        resolve_taoluan(
            judgment_suit="黑桃",
            judgment_card_id="j2",
            judged_character_is_self=True,
            choice=TaoluanChoice.TAKE_JUDGMENT_CARD,
            turn_state=first.turn_state_after,
        )


def test_taoluan_fire_slash_can_be_dodged_and_hit_can_trigger_shiji() -> None:
    dodged = resolve_taoluan_fire_slash(target_plays_dodge=True)
    hit = resolve_taoluan_fire_slash(target_plays_dodge=False)
    assert dodged.actual_damage == 0 and not dodged.can_trigger_shiji
    assert hit.actual_damage == 1 and hit.can_trigger_shiji


def test_zhengjun_rewards_are_independent_and_resolve_in_order() -> None:
    result = scripts.resolve_zhengjun_rewards(
        self_choice=RectificationReward.DRAW_TWO,
        other_choice=RectificationReward.RECOVER_ONE,
    )
    assert (result.self_draw_count, result.self_recover_hp) == (2, 0)
    assert (result.other_draw_count, result.other_recover_hp) == (0, 1)
    assert result.event_order[0].startswith("谋皇甫嵩")


def test_zhengjun_may_skip_granting_the_optional_other_reward() -> None:
    result = scripts.resolve_zhengjun_rewards(
        self_choice=RectificationReward.DRAW_TWO,
    )
    assert result.other_choice is None
    assert result.other_draw_count == result.other_recover_hp == 0
    assert result.event_order == ("谋皇甫嵩选择并结算奖励",)


def test_rectification_records_all_cards_and_missing_rank_or_suit_never_auto_passes() -> None:
    leijin = evaluate_rectification(
        RectificationTask.LEIJIN,
        (
            RectificationCardRecord("a", 2, "黑桃"),
            RectificationCardRecord("b", 5, "红桃", effect_invalidated=True),
            RectificationCardRecord("c", 9, "方块"),
        ),
    )
    invalid = evaluate_rectification(
        RectificationTask.BIANZHEN,
        (
            RectificationCardRecord("a", 2, "黑桃"),
            RectificationCardRecord("x", None, None),
        ),
    )
    assert leijin.success and leijin.recorded_card_ids == ("a", "b", "c")
    assert not invalid.success and invalid.recorded_card_ids == ("a", "x")
