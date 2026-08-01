import pytest

from scripts.sgs_ai_strategy_v24 import (
    GUO_NUWANG_AUDIT_FIELDS,
    NINE_LEVEL_STRENGTH,
    SHEN_LUBU_AUDIT_FIELDS,
    SUN_CHEN_AUDIT_FIELDS,
    V24_CONTENT_PROFILE,
    V24_STRENGTH_REFERENCES,
    XIN_XIANYING_AUDIT_FIELDS,
    JiejieChoiceOption,
    NiguDiscardOption,
    ShenLubuRagePlan,
    YichongChoice,
    choose_jiejie_option,
    choose_shen_lubu_rage_plan,
    choose_sunchen_action_order,
    choose_sunchen_nigu_option,
    choose_yichong_target,
    plan_jiejie_suit_count_order,
    score_nigu_discard_option,
    shenfen_net_rage,
    should_activate_shenfen,
    should_give_card_to_sunchen,
    should_guo_use_damage_while_enemy_is_bird,
    should_xin_xianying_accept_damage,
    wuqian_preservation_probability,
)


def _nigu_option(
    option_id: str,
    *,
    cards: int,
    cost: float,
    cleared: int,
    non_givers: float,
    damage_events: float,
) -> NiguDiscardOption:
    suits = ("黑桃", "红桃", "梅花", "方块")[:cards]
    return NiguDiscardOption(
        option_id=option_id,
        card_ids=tuple(f"c{i}" for i in range(cards)),
        suits=suits,
        resource_cost=cost,
        cleared_category_count=cleared,
        participant_count=3,
        expected_non_givers=non_givers,
        expected_damage_events=damage_events,
    )


def test_sunchen_nigu_enumerates_distinct_suit_discard_and_prefers_category_loop() -> None:
    cheap = _nigu_option("弃一张", cards=1, cost=0.2, cleared=0, non_givers=1, damage_events=2)
    loop = _nigu_option("弃三张清两类", cards=3, cost=1.2, cleared=2, non_givers=2, damage_events=3)

    chosen, audit = choose_sunchen_nigu_option((cheap, loop))

    assert chosen is loop
    assert audit.strategy_version == "V2.2"
    assert audit.content_profile == V24_CONTENT_PROFILE
    assert audit.metrics["nigu.multi_discard_to_clear_categories"] == 1
    assert "清除2个手牌类别" in audit.reason


def test_sunchen_nigu_rejects_zero_or_duplicate_suits() -> None:
    with pytest.raises(ValueError, match="1至4"):
        NiguDiscardOption("空", (), (), 0, 0, 0, 0, 0)
    with pytest.raises(ValueError, match="花色"):
        NiguDiscardOption("重复", ("a", "b"), ("黑桃", "黑桃"), 0, 0, 1, 1, 1)


def test_sunchen_action_order_and_enemy_give_are_dynamic() -> None:
    assert choose_sunchen_action_order(
        nigu_first_value=2,
        lulian_first_value=2.5,
        nigu_clears_blocking_category=True,
    ) == "先逆固"
    assert should_give_card_to_sunchen(
        card_opportunity_cost=2,
        prevented_bonus_damage_value=0.5,
        prevents_immediate_kill=False,
        card_is_equipment=True,
    ) is False
    assert should_give_card_to_sunchen(
        card_opportunity_cost=2,
        prevented_bonus_damage_value=0.5,
        prevents_immediate_kill=True,
        card_is_equipment=True,
    ) is True


def test_sunchen_score_penalizes_losing_required_range() -> None:
    base = _nigu_option("保范围", cards=1, cost=0.2, cleared=0, non_givers=1, damage_events=1)
    lose = NiguDiscardOption(**{**base.__dict__, "option_id": "失去关键范围", "loses_required_attack_range": True})
    assert score_nigu_discard_option(base) > score_nigu_discard_option(lose)


def test_xin_xianying_jiejie_scores_cancel_as_real_choice() -> None:
    options = (
        JiejieChoiceOption("红桃", 1.0, 0.5, discarded_card_cost=2.0),
        JiejieChoiceOption("取消", 0.0, 1.0),
    )
    chosen, audit = choose_jiejie_option(options, actor_relation="enemy")
    assert chosen.choice == "取消"
    assert audit.metrics["jiejie.cancelled_after_view"] == 1


def test_xin_xianying_round_plan_reserves_strictly_increasing_records() -> None:
    assert plan_jiejie_suit_count_order((4, 2, 3, 2))[:2] == (2, 3)
    with pytest.raises(ValueError, match="1至4"):
        plan_jiejie_suit_count_order((0, 2))


def test_xin_xianying_does_not_always_accept_damage() -> None:
    assert should_xin_xianying_accept_damage(
        damage_cost=1,
        qingshi_expected_value=2,
        death_probability=0,
    ) is True
    assert should_xin_xianying_accept_damage(
        damage_cost=1,
        qingshi_expected_value=2,
        death_probability=0.5,
    ) is False


def test_strength_reference_is_analysis_data_and_matches_attachment() -> None:
    assert NINE_LEVEL_STRENGTH["上中"] == 8
    assert V24_STRENGTH_REFERENCES["势·辛宪英"].equal_weight_average == pytest.approx(8.14, abs=0.01)
    assert V24_STRENGTH_REFERENCES["鲍信"].equal_weight_average == pytest.approx(6.08, abs=0.01)


def test_guo_nuwang_joint_target_and_suit_choice_counts_source_risk() -> None:
    safe = YichongChoice("安全方案", "敌人甲", "红桃", 1, 1, 1, 1, source_benefit_to_holder=0)
    risky = YichongChoice("资敌方案", "敌人乙", "黑桃", 2, 1, 1, 2, source_benefit_to_holder=6)
    chosen, audit = choose_yichong_target((risky, safe))
    assert chosen is safe
    assert "敌人甲" in audit.reason
    assert audit.metrics["yichong.suit"] == "红桃"


def test_guo_nuwang_can_suppress_damage_when_enemy_bird_benefits() -> None:
    assert should_guo_use_damage_while_enemy_is_bird(
        direct_damage_value=1,
        enemy_source_benefit=3,
    ) is False
    assert should_guo_use_damage_while_enemy_is_bird(
        direct_damage_value=1,
        enemy_source_benefit=3,
        immediate_kill_or_win_value=5,
    ) is True


def test_wuqian_multi_target_estimate_and_shenfen_scale() -> None:
    assert wuqian_preservation_probability((1.0, 0.0)) == 1.0
    assert wuqian_preservation_probability((0.5, 0.5)) == pytest.approx(0.75)
    assert shenfen_net_rage(7) == 1
    assert shenfen_net_rage(3) == -3


def test_shen_lubu_rage_budget_filters_unaffordable_plans() -> None:
    plans = (
        ShenLubuRagePlan("无前", 2, 4.0),
        ShenLubuRagePlan("神愤", 6, 10.0),
        ShenLubuRagePlan("保留暴怒", 0, 1.0),
    )
    chosen, audit = choose_shen_lubu_rage_plan(4, plans)
    assert chosen.action == "无前"
    assert "神愤" not in audit.legal_actions
    assert audit.metrics["shen_lubu.rage_cost"] == 2


def test_shenfen_uses_team_net_value_not_player_count_alone() -> None:
    assert should_activate_shenfen(
        expected_enemy_loss=8,
        expected_ally_loss=2,
        lethal_or_win_value=2,
        future_rage_opportunity_cost=1,
    ) is True
    assert should_activate_shenfen(
        expected_enemy_loss=2,
        expected_ally_loss=5,
        lethal_or_win_value=0,
        future_rage_opportunity_cost=1,
    ) is False


def test_all_four_general_audit_schemas_include_required_boundaries() -> None:
    assert "nigu.prevented_damage_charges_consumed" in SUN_CHEN_AUDIT_FIELDS
    assert "qingshi.enemy_only_discard_due_self_empty" in XIN_XIANYING_AUDIT_FIELDS
    assert "wufei.same_user_source_effects_blocked" in GUO_NUWANG_AUDIT_FIELDS
    assert "wuqian.full_resets_on_zero_damage_card" in SHEN_LUBU_AUDIT_FIELDS

