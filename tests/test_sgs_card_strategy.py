from __future__ import annotations

import pytest

from scripts.sgs_card_strategy import (
    DisruptionTarget,
    GroupCardKind,
    HarvestCardOption,
    Relationship,
    evaluate_borrowed_sword_response,
    evaluate_defense_card_spend,
    evaluate_group_card_use,
    evaluate_harvest_use,
    score_indulgence_target,
    score_supply_shortage_target,
    select_disruption_target,
    select_harvest_card,
)


def test_harvest_prefers_distance_card_needed_for_primary_focus() -> None:
    choice = select_harvest_card(
        (
            HarvestCardOption("普通收益", "无中生有", base_marginal_value=4),
            HarvestCardOption("距离牌", "紫骍", enables_focus_distance=True),
        ),
        needs_distance_to_focus=True,
    )

    assert choice.target_id == "距离牌"
    assert "攻击主要集火目标" in choice.reason
    assert choice.parameters["focus_distance_weight"] == 6.0


def test_harvest_prefers_slash_for_slash_dependent_skill_without_slash() -> None:
    choice = select_harvest_card(
        (
            HarvestCardOption("锦囊", "过河拆桥", base_marginal_value=3),
            HarvestCardOption("杀", "杀", is_slash=True),
        ),
        slash_dependent_skill=True,
        has_slash=False,
    )

    assert choice.target_id == "杀"
    assert "技能依赖【杀】" in choice.reason


def test_harvest_can_take_peach_to_deny_enemy_rescue() -> None:
    choice = select_harvest_card(
        (
            HarvestCardOption("桃", "桃", is_peach=True),
            HarvestCardOption("高基础", "无中生有", base_marginal_value=3),
        ),
        deny_enemy_rescue=True,
    )

    assert choice.target_id == "桃"
    assert "阻止敌方" in choice.reason


def test_harvest_can_leave_peach_for_reliable_ally() -> None:
    choice = select_harvest_card(
        (
            HarvestCardOption("桃", "桃", is_peach=True, base_marginal_value=3),
            HarvestCardOption("锦囊", "顺手牵羊", base_marginal_value=2),
        ),
        reliable_ally_can_take_peach=True,
    )

    assert choice.target_id == "锦囊"
    assert "安全取得【桃】" in select_harvest_card(
        (HarvestCardOption("桃", "桃", is_peach=True),),
        reliable_ally_can_take_peach=True,
    ).reason


def test_harvest_is_not_used_when_enemy_pick_order_makes_net_negative() -> None:
    decision = evaluate_harvest_use(
        friendly_expected_gain=3,
        enemy_expected_gain=3,
        two_enemies_before_next_ally=True,
        friendly_nullification_available=False,
    )

    assert not decision.should_act
    assert decision.score == -2
    assert "两名敌人连续取牌" in decision.reason


def test_harvest_critical_override_can_make_use_positive() -> None:
    decision = evaluate_harvest_use(
        friendly_expected_gain=2,
        enemy_expected_gain=4,
        two_enemies_before_next_ally=True,
        friendly_nullification_available=False,
        critical_flip_value=6,
    )

    assert decision.should_act
    assert "关键翻盘" in decision.reason


def test_borrowed_sword_from_ally_can_transfer_needed_weapon() -> None:
    decision = evaluate_borrowed_sword_response(
        user_relationship=Relationship.ALLY,
        target_relationship=Relationship.ENEMY,
        has_slash=True,
        target_is_legal=True,
        teammate_needs_weapon=True,
        weapon_retention_value=5,
    )

    assert not decision.should_act
    assert "让武器转移给队友" in decision.decision


def test_borrowed_sword_usually_slashes_enemy_and_keeps_weapon() -> None:
    decision = evaluate_borrowed_sword_response(
        user_relationship=Relationship.ENEMY,
        target_relationship=Relationship.ENEMY,
        has_slash=True,
        target_is_legal=True,
        weapon_retention_value=2,
        slash_effect_value=2,
    )

    assert decision.should_act
    assert "指定目标为敌方" in decision.reason


def test_borrowed_sword_against_ally_compares_weapon_and_damage_cost() -> None:
    keep_weapon = evaluate_borrowed_sword_response(
        user_relationship="敌方",
        target_relationship="己方",
        has_slash=True,
        target_is_legal=True,
        weapon_retention_value=8,
        teammate_damage_cost=3,
    )
    protect_ally = evaluate_borrowed_sword_response(
        user_relationship="敌方",
        target_relationship="己方",
        has_slash=True,
        target_is_legal=True,
        weapon_retention_value=2,
        teammate_damage_cost=5,
    )

    assert keep_weapon.should_act
    assert not protect_ally.should_act


def test_crossbow_combo_increases_willingness_to_slash() -> None:
    ordinary = evaluate_borrowed_sword_response(
        user_relationship="敌方",
        target_relationship="己方",
        has_slash=True,
        target_is_legal=True,
        weapon_retention_value=1,
        teammate_damage_cost=4,
    )
    crossbow = evaluate_borrowed_sword_response(
        user_relationship="敌方",
        target_relationship="己方",
        has_slash=True,
        target_is_legal=True,
        weapon_retention_value=1,
        teammate_damage_cost=4,
        crossbow_combo_value=5,
    )

    assert not ordinary.should_act
    assert crossbow.should_act
    assert "诸葛连弩" in crossbow.reason


def test_borrowed_sword_unknown_identity_does_not_invent_team_relation() -> None:
    decision = evaluate_borrowed_sword_response(
        user_relationship="未知",
        target_relationship="未知",
        has_slash=True,
        target_is_legal=True,
        weapon_retention_value=2,
    )

    assert "未把隐藏身份当作己方或敌方" in decision.reason


def test_low_value_action_does_not_spend_key_defense_card() -> None:
    decision = evaluate_defense_card_spend(tactical_gain=1, defense_value=5)

    assert not decision.should_act
    assert decision.decision == "保留防御牌"


def test_immediate_kill_can_justify_spending_defense_card() -> None:
    decision = evaluate_defense_card_spend(
        tactical_gain=1,
        defense_value=5,
        immediate_kill_value=8,
    )

    assert decision.should_act
    assert "即时击杀" in decision.reason


def test_disruption_prioritizes_dangerous_delayed_trick_on_ally() -> None:
    decision = select_disruption_target(
        (
            DisruptionTarget("队友", "乐不思蜀", dangerous_delayed_on_ally=True),
            DisruptionTarget("敌人", "防具", focus_target_armor=True),
        )
    )

    assert decision.target_id == "队友:乐不思蜀"
    assert "危险延时锦囊" in decision.reason


def test_disruption_prioritizes_focus_horse_and_effective_armor() -> None:
    horse = select_disruption_target(
        (
            DisruptionTarget("主目标", "+1马", focus_target_plus_one_horse=True),
            DisruptionTarget("次目标", "普通装备", base_expected_value=2),
        )
    )
    armor = select_disruption_target(
        (
            DisruptionTarget("主目标", "八卦阵", focus_target_armor=True),
            DisruptionTarget("次目标", "普通装备", base_expected_value=2),
        )
    )

    assert horse.target_id == "主目标:+1马"
    assert armor.target_id == "主目标:八卦阵"


def test_enemy_crossbow_burst_can_override_normal_equipment_priority() -> None:
    decision = select_disruption_target(
        (
            DisruptionTarget("主目标", "防具", focus_target_armor=True),
            DisruptionTarget("爆发敌人", "诸葛连弩", enemy_crossbow_burst=True),
        )
    )

    assert decision.target_id == "爆发敌人:诸葛连弩"
    assert "高爆发" in decision.reason


def test_disruption_does_not_use_illegal_hidden_information() -> None:
    decision = select_disruption_target(
        (
            DisruptionTarget(
                "敌人甲",
                "隐藏桃",
                known_peach=True,
                information_legal=False,
            ),
            DisruptionTarget("敌人乙", "公开连弩", enemy_crossbow_burst=True),
        )
    )

    assert decision.target_id == "敌人乙:公开连弩"


def test_indulgence_values_hand_overflow() -> None:
    overflow = score_indulgence_target(
        "甲",
        base_threat=3,
        hand_count=7,
        hand_limit=3,
        expected_play_phase_loss=2,
        next_to_act=False,
    )
    no_overflow = score_indulgence_target(
        "乙",
        base_threat=3,
        hand_count=3,
        hand_limit=3,
        expected_play_phase_loss=2,
        next_to_act=False,
    )

    assert overflow.score > no_overflow.score
    assert overflow.parameters["hand_overflow"] == 4


def test_indulgence_next_actor_bonus_and_removal_risk_are_dynamic() -> None:
    first = score_indulgence_target(
        "先行动",
        base_threat=3,
        hand_count=4,
        hand_limit=4,
        expected_play_phase_loss=2,
        next_to_act=True,
    )
    later_at_risk = score_indulgence_target(
        "后行动",
        base_threat=3,
        hand_count=4,
        hand_limit=4,
        expected_play_phase_loss=2,
        next_to_act=False,
        removal_probability_before_judgment=0.5,
    )

    assert first.score > later_at_risk.score
    assert first.parameters["next_action_bonus"] == 1.0
    assert later_at_risk.parameters["removal_probability"] == 0.5


def test_supply_shortage_values_low_hand_and_draw_dependency() -> None:
    low_dependent = score_supply_shortage_target(
        "低手牌",
        base_threat=2,
        hand_count=1,
        draw_phase_dependency=4,
        next_to_act=True,
    )
    rich_independent = score_supply_shortage_target(
        "高资源",
        base_threat=2,
        hand_count=6,
        draw_phase_dependency=0.5,
        extra_draw_resilience=1,
        next_to_act=False,
    )

    assert low_dependent.score > rich_independent.score
    assert low_dependent.parameters["low_hand_bonus_per_card"] == 0.2
    assert low_dependent.parameters["next_action_bonus"] == 0.65


def test_peach_garden_is_avoided_when_it_breaks_focus_kill_line() -> None:
    decision = evaluate_group_card_use(
        GroupCardKind.PEACH_GARDEN,
        friendly_heal_value=2,
        enemy_heal_value=2,
        focus_kill_line_loss=4,
    )

    assert not decision.should_act
    assert "破坏当前主要目标的击杀线" in decision.reason


@pytest.mark.parametrize("card", ["南蛮入侵", "万箭齐发"])
def test_aoe_with_kill_value_and_acceptable_friendly_cost_is_used(card: str) -> None:
    decision = evaluate_group_card_use(
        card,
        enemy_expected_loss=3,
        enemy_kill_value=5,
        friendly_expected_loss=1,
        rescue_resource_cost=1,
    )

    assert decision.should_act
    assert "可完成击杀" in decision.reason


def test_aoe_ally_dying_risk_reduces_use_willingness() -> None:
    safe = evaluate_group_card_use("南蛮入侵", enemy_expected_loss=4)
    dangerous = evaluate_group_card_use(
        "南蛮入侵",
        enemy_expected_loss=4,
        ally_dying_risk_cost=6,
    )

    assert safe.should_act
    assert not dangerous.should_act
    assert "危险血线" in dangerous.reason


def test_enemy_on_damage_benefit_can_make_aoe_negative() -> None:
    decision = evaluate_group_card_use(
        "万箭齐发",
        enemy_expected_loss=3,
        enemy_on_damage_benefit=5,
    )

    assert not decision.should_act
    assert "敌方卖血收益" in decision.reason


def test_strategy_decisions_are_stable_explainable_and_parameterized() -> None:
    kwargs = dict(
        friendly_expected_gain=4,
        enemy_expected_gain=2,
        two_enemies_before_next_ally=False,
        friendly_nullification_available=False,
    )
    first = evaluate_harvest_use(**kwargs)
    second = evaluate_harvest_use(**kwargs)

    assert first == second
    assert first.reason
    assert dict(first.parameters) == dict(second.parameters)
    with pytest.raises(TypeError):
        first.parameters["new"] = 1  # type: ignore[index]


def test_invalid_strategy_inputs_have_clear_chinese_errors() -> None:
    with pytest.raises(ValueError, match="0到1"):
        score_indulgence_target(
            "目标",
            base_threat=1,
            hand_count=1,
            hand_limit=1,
            expected_play_phase_loss=1,
            next_to_act=False,
            removal_probability_before_judgment=1.2,
        )
    with pytest.raises(ValueError, match="非负"):
        evaluate_defense_card_spend(tactical_gain=-1, defense_value=2)

