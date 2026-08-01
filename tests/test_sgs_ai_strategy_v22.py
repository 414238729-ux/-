from __future__ import annotations

import pytest

from scripts.sgs_ai_strategy_v22 import (
    STRATEGY_VERSION,
    CaochunVersion,
    CounterplayProfile,
    DynamicCardValue,
    DynamicTauntInput,
    FuqianMode,
    GeneralPolicy,
    PressureCard,
    QuediBranch,
    StrategyAction,
    WuyangSlashTarget,
    V22AuditMetrics,
    build_optional_response_actions,
    choose_shamoke_slash_response,
    choose_v22_action,
    choose_wuyang_equipment_slash_target,
    chongjian_equipment_gain_count,
    evaluate_caochun_counterplay,
    evaluate_attack_into_shamoke,
    evaluate_fuqian_pressure,
    evaluate_gouchen_activation,
    evaluate_pojiang_activation,
    evaluate_qinghe_combo,
    evaluate_qinghe_last_slash_hold,
    evaluate_shamoke_weapon_disruption,
    evaluate_shamoke_weapon_swap,
    evaluate_wuyang_quedi,
)
from scripts.sgs_special_general_rules import apply_choujue_maximum_hp_gain


def test_v22_policy_dynamic_value_taunt_and_counterplay_are_separate_layers() -> None:
    policy = GeneralPolicy(
        core_plan="保留核心资源后爆发",
        core_resources=("杀", "武器"),
        opponent_counterplay=("拆除关键装备",),
    )
    counter = CounterplayProfile(
        depends_on=("装备",),
        threat_tags=("爆发型",),
    )
    card = DynamicCardValue(
        base_utility=1,
        skill_synergy=2,
        sequence_plan_value=1,
        kill_or_rescue_value=3,
        opportunity_cost=1,
        counterplay_risk=0.5,
    )
    target = DynamicTauntInput(
        target_id="敌人",
        kill_and_number_value=3,
        immediate_threat=2,
        inaccessible_cost=1,
    )
    assert policy.core_plan == "保留核心资源后爆发"
    assert counter.threat_tags == ("爆发型",)
    assert card.total == pytest.approx(5.5)
    assert target.score == pytest.approx(4.0)


def test_response_and_no_response_are_both_legal_candidates() -> None:
    actions = build_optional_response_actions(
        effect_cost=1,
        response_card_cost=0.5,
        skill_response_available=True,
        skill_response_cost=0.2,
    )
    audit = choose_v22_action(actions)
    assert set(audit.legal_actions) == {
        "respond_with_card",
        "do_not_respond",
        "respond_with_skill_or_equipment",
    }
    assert audit.strategy_version == STRATEGY_VERSION == "V2.2"
    assert audit.incorrectly_pruned_legal_actions == 0
    assert audit.special_metrics == V22AuditMetrics()

    with pytest.raises(ValueError, match="不允许因策略剪枝"):
        V22AuditMetrics(incorrectly_pruned_legal_actions=1)


def test_unavailable_response_card_is_not_fabricated_as_legal_action() -> None:
    actions = build_optional_response_actions(
        effect_cost=1,
        response_card_cost=0.5,
        response_card_available=False,
    )
    audit = choose_v22_action(actions)

    assert audit.legal_actions == ("do_not_respond",)
    assert "respond_with_card" not in audit.rejected_actions


def test_special_metrics_are_preserved_in_decision_audit() -> None:
    metrics = V22AuditMetrics(
        core_combo_attempts=2,
        core_combo_successes=1,
        ordinary_attack_skipped_to_hold_resources=3,
        opponent_specific_counterplays=4,
    )
    audit = choose_v22_action(
        (StrategyAction("hold", immediate_value=1),),
        special_metrics=metrics,
    )

    assert audit.special_metrics is metrics
    assert audit.special_metrics.core_combo_attempts == 2

    with pytest.raises(TypeError, match="专项审计指标"):
        choose_v22_action(
            (StrategyAction("hold", immediate_value=1),),
            special_metrics="invalid",  # type: ignore[arg-type]
        )


def test_all_legal_targets_enter_audit_and_hidden_information_is_enforced() -> None:
    actions = (
        StrategyAction("target_self", target_id="自己", immediate_value=0),
        StrategyAction("target_enemy_a", target_id="敌A", immediate_value=1),
        StrategyAction("target_enemy_b", target_id="敌B", immediate_value=2),
    )
    audit = choose_v22_action(
        actions,
        hidden_information_used=("2v2队友手牌",),
        authorized_information=("2v2队友手牌",),
    )
    assert audit.legal_actions == ("target_self", "target_enemy_a", "target_enemy_b")
    assert audit.chosen_action == "target_enemy_b"
    assert audit.hidden_information_used == ("2v2队友手牌",)

    with pytest.raises(ValueError, match="未授权隐藏信息"):
        choose_v22_action(
            actions,
            hidden_information_used=("敌方完整手牌",),
            authorized_information=(),
        )


def test_shamoke_reconsiders_crossbow_after_high_range_trigger() -> None:
    decision = evaluate_shamoke_weapon_swap(
        high_range_triggered=True,
        original_weapon_value=2,
        replacement_weapon_name="诸葛连弩",
        replacement_weapon_value=1,
        slash_count=4,
        next_turn_jili_value=1,
    )
    assert decision.should_swap
    assert decision.swap_value > decision.keep_value

    immediate_combo = evaluate_shamoke_weapon_swap(
        high_range_triggered=False,
        original_weapon_value=0,
        replacement_weapon_name="诸葛连弩",
        replacement_weapon_value=9,
        slash_count=5,
    )
    hold_for_unrealized_trigger = evaluate_shamoke_weapon_swap(
        high_range_triggered=False,
        original_weapon_value=1,
        replacement_weapon_name="低收益武器",
        replacement_weapon_value=1,
        unrealized_current_jili_value=5,
    )
    assert immediate_combo.should_swap
    assert not hold_for_unrealized_trigger.should_swap


def test_opponent_does_not_blindly_reduce_shamoke_to_range_one_at_count_zero() -> None:
    decision = evaluate_shamoke_weapon_disruption(
        current_count=0,
        current_range=3,
        response_likely=True,
        can_force_response_before_disruption=True,
        key_weapon_removal_value=1,
    )
    assert decision.wait_for_count_advance
    assert decision.delayed_value > decision.direct_value

    key_weapon = evaluate_shamoke_weapon_disruption(
        current_count=0,
        current_range=3,
        response_likely=True,
        can_force_response_before_disruption=True,
        key_weapon_removal_value=5,
        immediate_kill_value=4,
    )
    assert not key_weapon.wait_for_count_advance


def test_shamoke_disruption_reads_actual_post_removal_range() -> None:
    no_range_one_trigger = evaluate_shamoke_weapon_disruption(
        current_count=0,
        current_range=3,
        post_removal_attack_range=2,
        response_likely=True,
        can_force_response_before_disruption=True,
        key_weapon_removal_value=1,
    )
    range_two_trigger = evaluate_shamoke_weapon_disruption(
        current_count=1,
        current_range=3,
        post_removal_attack_range=2,
        response_likely=True,
        can_force_response_before_disruption=True,
        key_weapon_removal_value=1,
    )

    assert not no_range_one_trigger.wait_for_count_advance
    assert range_two_trigger.wait_for_count_advance


def test_shamoke_critical_count_downweights_only_ordinary_probe() -> None:
    ordinary = evaluate_attack_into_shamoke(
        current_count=2,
        attack_range=3,
        base_attack_value=1,
        response_likely=True,
    )
    kill = evaluate_attack_into_shamoke(
        current_count=2,
        attack_range=3,
        base_attack_value=1,
        response_likely=True,
        certain_kill=True,
    )
    assert ordinary.critical_response_would_trigger_jili
    assert not ordinary.should_probe
    assert kill.should_probe


def test_shamoke_critical_count_can_choose_no_flash_but_danger_overrides() -> None:
    ordinary = choose_shamoke_slash_response(
        current_count=2,
        attack_range=3,
        first_qinglong_slash=True,
        likely_followup_slash=True,
    )
    assert "do_not_respond" in ordinary.legal_actions
    assert ordinary.chosen_action == "do_not_respond"

    lethal = choose_shamoke_slash_response(
        current_count=2,
        attack_range=3,
        first_qinglong_slash=True,
        likely_followup_slash=True,
        lethal=True,
    )
    assert lethal.chosen_action == "respond_with_card"

    wine_chain = choose_shamoke_slash_response(
        current_count=2,
        attack_range=3,
        wine_buffed=True,
        dangerous_elemental_chain=True,
    )
    assert wine_chain.chosen_action == "respond_with_card"

    no_jink = choose_shamoke_slash_response(
        current_count=2,
        attack_range=3,
        response_card_available=False,
        lethal=True,
    )
    assert no_jink.legal_actions == ("do_not_respond",)


def test_caochun_counterplay_tracks_versions_growth_and_key_equipment() -> None:
    old = evaluate_caochun_counterplay(
        version="旧版",
        lost_equipment_count=0,
        can_target_hand=True,
    )
    new = evaluate_caochun_counterplay(
        version=CaochunVersion.NEW,
        lost_equipment_count=0,
        can_target_hand=True,
    )
    grown = evaluate_caochun_counterplay(
        version="新版",
        lost_equipment_count=2,
        can_target_hand=True,
    )
    key = evaluate_caochun_counterplay(
        version="新版",
        lost_equipment_count=0,
        can_target_hand=True,
        key_equipment_value=5,
    )
    assert old.target_zone == "手牌"
    assert old.activation_timing == "出牌阶段开始时"
    assert new.activation_timing == "出牌阶段内可选择时机"
    assert grown.hand_pressure_bonus < old.hand_pressure_bonus
    assert key.target_zone == "装备区"


def test_gouchen_only_decides_activation_and_always_draws_three_categories() -> None:
    use = evaluate_gouchen_activation(
        mark_available=True,
        immediate_three_card_value=5,
        topdeck_control_value=1,
    )
    hold = evaluate_gouchen_activation(
        mark_available=True,
        immediate_three_card_value=2,
        topdeck_control_value=6,
    )
    assert use.activate
    assert use.gained_categories == ("基本牌", "锦囊牌", "装备牌")
    assert use.prospective_categories == ("基本牌", "锦囊牌", "装备牌")
    assert not use.category_choice_available
    assert not hold.activate
    assert hold.gained_categories == ()
    assert hold.prospective_categories == ("基本牌", "锦囊牌", "装备牌")


@pytest.mark.parametrize(
    ("first", "second", "expected", "slander"),
    [
        (True, False, 2, False),
        (False, True, 2, True),
        (False, False, 3, False),
    ],
)
def test_qinghe_virtual_slash_wine_slander_sequence(
    first: bool,
    second: bool,
    expected: int,
    slander: bool,
) -> None:
    result = evaluate_qinghe_combo(
        first_slash_responded=first,
        wine_slash_responded=second,
    )
    assert result.sequence == ("虚拟杀", "虚拟酒", "闪诬", "实体杀")
    assert result.total_hp_loss == expected
    assert result.total_hp_loss >= 2
    assert result.slander_first_used_card_checked is slander


def test_qinghe_hold_last_slash_is_dynamic_not_permanent() -> None:
    hold = evaluate_qinghe_last_slash_hold(
        qinghe_has_not_acted=True,
        qinghe_acts_soon=True,
        holder_is_likely_target=True,
        current_slash_value=0.5,
    )
    kill = evaluate_qinghe_last_slash_hold(
        qinghe_has_not_acted=True,
        qinghe_acts_soon=True,
        holder_is_likely_target=True,
        current_slash_value=0.5,
        immediate_kill_value=5,
    )
    assert hold.hold_last_slash
    assert not kill.hold_last_slash


def test_fuqian_long_pressure_commits_minimum_and_modes_differ() -> None:
    cards = (
        PressureCard("低成本", opportunity_cost=0.2, expected_end_effect=2),
        PressureCard("关键组件", opportunity_cost=4, expected_end_effect=6),
    )
    duel = evaluate_fuqian_pressure(
        current_hp=4,
        current_jue_count=0,
        cards=cards,
        passed_play_phase=False,
        opponent_has_stable_engine=True,
        opponent_can_accumulate_burst=False,
        mode=FuqianMode.DUEL,
    )
    team = evaluate_fuqian_pressure(
        current_hp=4,
        current_jue_count=0,
        cards=cards,
        passed_play_phase=False,
        opponent_has_stable_engine=True,
        opponent_can_accumulate_burst=False,
        mode=FuqianMode.TEAM,
    )
    assert duel.plan == "长期逼破降"
    assert duel.committed_card_ids == ("低成本",)
    assert team.mode_multiplier < duel.mode_multiplier


def test_fuqian_mode_multiplier_changes_marginal_long_pressure_commitment() -> None:
    marginal = (PressureCard("边际施压牌", opportunity_cost=0.4, expected_end_effect=1.0),)
    common = dict(
        current_hp=4,
        current_jue_count=0,
        cards=marginal,
        passed_play_phase=False,
        opponent_has_stable_engine=True,
        opponent_can_accumulate_burst=False,
    )
    duel = evaluate_fuqian_pressure(**common, mode="单挑")
    team = evaluate_fuqian_pressure(**common, mode="团队")

    assert duel.committed_card_ids == ("边际施压牌",)
    assert team.committed_card_ids == ()


def test_fuqian_switches_to_assault_and_compares_pojiang() -> None:
    pressure = evaluate_fuqian_pressure(
        current_hp=1,
        current_jue_count=0,
        cards=(PressureCard("破口", 0, 3),),
        passed_play_phase=False,
        opponent_has_stable_engine=True,
        opponent_can_accumulate_burst=False,
        mode="单挑",
    )
    safe_clear = evaluate_pojiang_activation(
        current_hp=3,
        draw_and_transfer_value=5,
        expected_end_effect_cost=1,
        reliable_rescue=False,
    )
    dangerous_clear = evaluate_pojiang_activation(
        current_hp=1,
        draw_and_transfer_value=2,
        expected_end_effect_cost=1,
        reliable_rescue=False,
    )
    assert pressure.plan == "转入总攻"
    assert safe_clear.activate
    assert not dangerous_clear.activate


def test_wuyang_full_hp_ordinary_value_does_not_backwater() -> None:
    decision = evaluate_wuyang_quedi(
        current_hp=4,
        current_max_hp=4,
        take_hand_value=1,
        damage_plus_value=1,
        basic_card_cost=0.2,
        future_max_hp_cost=1,
        both_effects_indispensable=False,
    )
    assert decision.actual_hp_loss == 1
    assert decision.hp_after_max_hp_loss == 3
    assert decision.chosen_branch is not QuediBranch.BACKSWATER


def test_wuyang_low_hp_high_max_does_not_auto_forbid_key_backwater() -> None:
    decision = evaluate_wuyang_quedi(
        current_hp=1,
        current_max_hp=4,
        take_hand_value=3,
        damage_plus_value=3,
        basic_card_cost=0.2,
        future_max_hp_cost=0.5,
        both_effects_indispensable=True,
        key_kill_value=5,
    )
    assert decision.actual_hp_loss == 0
    assert decision.chosen_branch is QuediBranch.BACKSWATER


def test_wuyang_regular_branch_suffices_without_extra_max_hp_cost() -> None:
    take = evaluate_wuyang_quedi(
        current_hp=3,
        current_max_hp=4,
        take_hand_value=5,
        damage_plus_value=0,
        basic_card_cost=1,
        future_max_hp_cost=1,
        both_effects_indispensable=False,
    )
    damage = evaluate_wuyang_quedi(
        current_hp=3,
        current_max_hp=4,
        take_hand_value=0,
        damage_plus_value=5,
        basic_card_cost=0.2,
        future_max_hp_cost=1,
        both_effects_indispensable=False,
    )
    assert take.chosen_branch is QuediBranch.TAKE_HAND
    assert damage.chosen_branch is QuediBranch.DAMAGE_PLUS


def test_wuyang_backswater_can_use_newly_taken_basic_card_as_material() -> None:
    decision = evaluate_wuyang_quedi(
        current_hp=2,
        current_max_hp=4,
        take_hand_value=3,
        damage_plus_value=3,
        basic_card_cost=0,
        future_max_hp_cost=0,
        both_effects_indispensable=True,
        basic_material_available_before=False,
        taken_card_is_basic=True,
    )
    assert not decision.branch_legal[QuediBranch.DAMAGE_PLUS]
    assert decision.branch_legal[QuediBranch.BACKSWATER]
    assert decision.chosen_branch is QuediBranch.BACKSWATER


def test_wuyang_quedi_does_not_offer_take_or_backwater_against_empty_hand() -> None:
    decision = evaluate_wuyang_quedi(
        current_hp=3,
        current_max_hp=4,
        take_hand_value=99,
        damage_plus_value=2,
        basic_card_cost=0.2,
        future_max_hp_cost=0,
        both_effects_indispensable=True,
        target_has_hand=False,
        basic_material_available_before=True,
    )

    assert not decision.branch_legal[QuediBranch.TAKE_HAND]
    assert not decision.branch_legal[QuediBranch.BACKSWATER]
    assert decision.chosen_branch is QuediBranch.DAMAGE_PLUS

    with pytest.raises(ValueError, match="不可能取得基本牌"):
        evaluate_wuyang_quedi(
            current_hp=3,
            current_max_hp=4,
            take_hand_value=0,
            damage_plus_value=0,
            basic_card_cost=0,
            future_max_hp_cost=0,
            both_effects_indispensable=False,
            target_has_hand=False,
            taken_card_is_basic=True,
        )


def test_wuyang_equipment_target_is_scored_not_hardcoded() -> None:
    selected = choose_wuyang_equipment_slash_target(
        (
            WuyangSlashTarget(
                "有装备卖血目标",
                True,
                material_equipment_cost=2,
                expected_damage_value=1,
                on_damage_benefit=5,
            ),
            WuyangSlashTarget(
                "无装备关键目标",
                False,
                material_equipment_cost=0.5,
                expected_damage_value=2,
                kill_value=5,
            ),
        )
    )
    assert selected.target_id == "无装备关键目标"


def test_direct_kill_never_counts_chongjian_equipment_gain() -> None:
    assert chongjian_equipment_gain_count(
        target_killed=True,
        target_equipment_count=4,
        damage_dealt=3,
    ) == 0
    assert chongjian_equipment_gain_count(
        target_killed=False,
        target_equipment_count=4,
        damage_dealt=3,
    ) == 3


def test_choujue_maximum_hp_gain_does_not_restore_current_hp() -> None:
    result = apply_choujue_maximum_hp_gain(2, 4)
    assert (result.hp_after, result.maximum_hp_after) == (2, 5)
    assert result.recovered_hp == 0
