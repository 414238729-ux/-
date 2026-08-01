from __future__ import annotations

import pytest

from scripts.sgs_team_strategy import (
    FarmerPeachKnowledge,
    FarmerPeachSignal,
    NullificationAvailability,
    NullificationKnowledgeState,
    RescueResource,
    RescueResourceKind,
    evaluate_nullification_bait,
    evaluate_nullification_decision,
    plan_team_rescue,
    rescue_resource_from_farmer_signal,
)


def test_farmer_peach_signal_is_three_state_and_reveals_no_other_cards() -> None:
    has_peach = FarmerPeachKnowledge("农民甲", FarmerPeachSignal.HAS_PEACH)
    no_peach = FarmerPeachKnowledge("农民乙", FarmerPeachSignal.NO_PEACH)
    unknown = FarmerPeachKnowledge("农民丙", FarmerPeachSignal.UNKNOWN)

    assert has_peach.minimum_known_peaches == 1
    assert not has_peach.exact_quantity_known
    assert no_peach.minimum_known_peaches == 0
    assert no_peach.exact_quantity_known
    assert unknown.minimum_known_peaches == 0
    assert not unknown.exact_quantity_known
    assert not has_peach.discloses_other_cards


def test_using_one_signaled_peach_makes_remaining_quantity_unknown() -> None:
    knowledge = FarmerPeachKnowledge("农民甲", "has_peach")

    updated = knowledge.after_observed_peach_use()

    assert updated.signal is FarmerPeachSignal.UNKNOWN
    assert updated.minimum_known_peaches == 0
    assert "剩余数量未知" in updated.knowledge_source


def test_farmer_signal_contributes_only_one_guaranteed_peach() -> None:
    known = FarmerPeachKnowledge("农民甲", FarmerPeachSignal.HAS_PEACH)
    resource = rescue_resource_from_farmer_signal(known)

    assert resource is not None
    assert resource.available_uses == 1
    assert resource.kind is RescueResourceKind.PEACH
    assert rescue_resource_from_farmer_signal(
        FarmerPeachKnowledge("农民甲", FarmerPeachSignal.UNKNOWN)
    ) is None


def test_known_team_resources_force_minimum_resource_rescue() -> None:
    resources = (
        RescueResource("甲的桃", "甲", "peach", available_uses=2),
        RescueResource(
            "濒死者的酒",
            "乙",
            "self_wine",
            preservation_cost=0.5,
        ),
        RescueResource(
            "队友的酒",
            "甲",
            "self_wine",
            available_uses=9,
        ),
    )

    plan = plan_team_rescue(-2, "乙", ("甲",), resources)

    assert plan.required_recovery == 3
    assert plan.can_guarantee_rescue
    assert plan.must_rescue
    assert sum(item.uses for item in plan.selected_uses) == 3
    assert plan.expected_hp_after == 1
    assert "队友的酒" in plan.excluded_resource_ids
    assert "必须" in plan.explanation


def test_non_dying_teammate_wine_never_counts_as_rescue() -> None:
    plan = plan_team_rescue(
        0,
        "濒死者",
        ("队友",),
        (RescueResource("队友酒", "队友", "self_wine"),),
    )

    assert plan.known_legal_healing == 0
    assert not plan.can_guarantee_rescue
    assert not plan.must_rescue
    assert plan.selected_uses == ()


def test_rescue_plan_minimizes_number_of_resources_before_cost() -> None:
    plan = plan_team_rescue(
        -1,
        "乙",
        ("甲",),
        (
            RescueResource("甲桃", "甲", "peach", available_uses=2),
            RescueResource(
                "双回复技能",
                "乙",
                "skill",
                healing_per_use=2,
                preservation_cost=3,
            ),
        ),
    )

    assert len(plan.selected_uses) == 1
    assert plan.selected_uses[0].resource_id == "双回复技能"
    assert plan.expected_hp_after == 1


def test_insufficient_known_resources_do_not_claim_guaranteed_rescue() -> None:
    plan = plan_team_rescue(
        -1,
        "乙",
        ("甲",),
        (RescueResource("甲桃", "甲", "peach"),),
    )

    assert not plan.can_guarantee_rescue
    assert not plan.must_rescue
    assert "不足" in plan.explanation


def test_initial_nullification_knowledge_does_not_pre_read_first_timer() -> None:
    state = NullificationKnowledgeState(("甲", "乙", "丙"))

    assert all(
        item.availability is NullificationAvailability.UNKNOWN
        for item in state.snapshot().values()
    )


def test_response_timer_records_specific_holders_without_exact_counts() -> None:
    state = NullificationKnowledgeState(("甲", "乙", "丙"))

    state.refresh_response_window(
        ("乙",),
        window_id="锦囊一",
        knowledge_time="第一张锦囊响应时",
    )

    assert (
        state.knowledge_for("乙").availability
        is NullificationAvailability.KNOWN_USABLE
    )
    assert (
        state.knowledge_for("甲").availability
        is NullificationAvailability.KNOWN_NONE
    )
    assert state.knowledge_for("乙").exact_quantity is None
    assert not state.knowledge_for("乙").discloses_other_cards


def test_using_one_nullification_does_not_imply_no_second_copy() -> None:
    state = NullificationKnowledgeState(("甲", "乙"))
    state.refresh_response_window(
        ("乙",),
        window_id="窗口一",
        knowledge_time="t1",
    )

    state.record_nullification_used("乙", knowledge_time="t2")

    knowledge = state.knowledge_for("乙")
    assert knowledge.availability is NullificationAvailability.UNKNOWN
    assert knowledge.exact_quantity is None


def test_unknown_hand_change_invalidates_old_known_none() -> None:
    state = NullificationKnowledgeState(("甲", "乙"))
    state.refresh_response_window(
        (),
        window_id="窗口一",
        knowledge_time="t1",
    )
    assert (
        state.knowledge_for("乙").availability
        is NullificationAvailability.KNOWN_NONE
    )

    state.record_unknown_hand_change("乙", knowledge_time="摸未知牌后")

    assert (
        state.knowledge_for("乙").availability
        is NullificationAvailability.UNKNOWN
    )


def test_new_response_window_fully_refreshes_holder_set() -> None:
    state = NullificationKnowledgeState(("甲", "乙", "丙"))
    state.refresh_response_window(
        ("甲",), window_id="窗口一", knowledge_time="t1"
    )
    state.refresh_response_window(
        ("丙",), window_id="窗口二", knowledge_time="t2"
    )

    assert (
        state.knowledge_for("甲").availability
        is NullificationAvailability.KNOWN_NONE
    )
    assert (
        state.knowledge_for("丙").availability
        is NullificationAvailability.KNOWN_USABLE
    )
    assert state.knowledge_for("丙").window_id == "窗口二"


def test_nullification_is_used_for_lethal_or_high_value_resolution() -> None:
    decision = evaluate_nullification_decision(
        1,
        future_preservation_value=4,
        would_cause_death=True,
        opponent_hand_count=1,
    )

    assert decision.use_nullification
    assert "死亡" in decision.explanation


def test_low_value_nullification_can_be_preserved() -> None:
    decision = evaluate_nullification_decision(
        0.5,
        future_preservation_value=3,
        opponent_hand_count=7,
    )

    assert not decision.use_nullification
    assert "保留价值" in decision.explanation


def test_positive_value_low_cost_trick_can_bait_known_nullification() -> None:
    decision = evaluate_nullification_bait(
        0.5,
        5,
        information_value=0.5,
        known_enemy_has_usable=True,
    )

    assert decision.use_bait
    assert decision.decision_score > 0
    assert "预期收益" in decision.explanation


def test_known_no_nullification_means_no_bait_is_needed() -> None:
    decision = evaluate_nullification_bait(
        0.1,
        10,
        known_enemy_has_usable=False,
    )

    assert not decision.use_bait
    assert "无需" in decision.explanation


def test_strategy_validation_uses_clear_chinese_errors() -> None:
    with pytest.raises(ValueError, match="三态|只能是|信号"):
        FarmerPeachKnowledge("甲", "maybe")
    with pytest.raises(ValueError, match="濒死"):
        plan_team_rescue(1, "甲", (), ())
    with pytest.raises(ValueError, match="0 到 1"):
        evaluate_nullification_bait(
            1,
            1,
            expected_consumption_probability=1.5,
        )
