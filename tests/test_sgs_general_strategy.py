from __future__ import annotations

import pytest

from scripts.sgs_general_strategy import (
    GeneralProfile,
    StrategyLevel,
    StrengthTier,
    TargetSituation,
    TauntDefaults,
    build_on_demand_general_profiles,
    calculate_target_priority,
    choose_executable_priority_target,
)


def test_fixed_lineup_builds_only_participant_profiles_without_complete_database() -> None:
    supplied = {
        "甲": GeneralProfile(
            general_name="甲",
            base_hp=4,
            base_max_hp=4,
            skill_text="用户提供的技能文字",
            skill_version="本次确认版本",
            source="用户提供",
            confidence="当前确认",
        ),
        "未参战武将": GeneralProfile(general_name="未参战武将"),
    }

    result = build_on_demand_general_profiles(("甲", "乙"), supplied)

    assert set(result.profiles) == {"甲", "乙"}
    assert result.missing_general_inputs == ("乙",)
    assert result.complete_general_database_required is False
    assert result.common_rules_simulation_available is True
    assert "skill_text" in result.profiles["乙"].missing_fields


def test_profile_does_not_fill_missing_skill_from_memory() -> None:
    result = build_on_demand_general_profiles(("未知武将",), {})
    profile = result.profiles["未知武将"]

    assert profile.skill_text is None
    assert profile.parsed_skill_rules == ()
    assert profile.confidence == "待核验"


def test_same_strength_prefers_target_without_defense() -> None:
    undefended = calculate_target_priority(TargetSituation(target_id="无防御"))
    defended = calculate_target_priority(
        TargetSituation(target_id="有防御", defense_level=StrategyLevel.STRONG)
    )

    assert undefended.target_priority > defended.target_priority


def test_two_undefended_targets_prefer_explicitly_stronger_one() -> None:
    weak = calculate_target_priority(
        TargetSituation(target_id="较弱", strength_tier=StrengthTier.WEAK)
    )
    strong = calculate_target_priority(
        TargetSituation(target_id="较强", strength_tier=StrengthTier.STRONG)
    )

    assert strong.target_priority > weak.target_priority


def test_immediate_kill_can_override_static_strength() -> None:
    weak_lethal = calculate_target_priority(
        TargetSituation(
            target_id="可立即击杀",
            strength_tier=StrengthTier.WEAK,
            immediate_kill_available=True,
        )
    )
    strong = calculate_target_priority(
        TargetSituation(target_id="强但未到击杀线", strength_tier=StrengthTier.STRONG)
    )

    assert weak_lethal.target_priority > strong.target_priority
    assert "即时击杀" in weak_lethal.reasons[0]


def test_on_damage_benefit_reduces_scattered_attack_when_not_killable() -> None:
    ordinary = calculate_target_priority(TargetSituation(target_id="普通目标"))
    masochism = calculate_target_priority(
        TargetSituation(target_id="卖血目标", on_damage_level=StrategyLevel.STRONG)
    )
    killable_masochism = calculate_target_priority(
        TargetSituation(
            target_id="可集中击杀的卖血目标",
            on_damage_level=StrategyLevel.STRONG,
            immediate_kill_available=True,
        )
    )

    assert masochism.target_priority < ordinary.target_priority
    assert killable_masochism.target_priority > masochism.target_priority


def test_emergency_threat_overrides_normal_target_order() -> None:
    normal = calculate_target_priority(
        TargetSituation(target_id="普通强者", strength_tier=StrengthTier.STRONG)
    )
    emergency = calculate_target_priority(
        TargetSituation(target_id="下回合致命", emergency_lethal_intensity=1.0)
    )

    assert emergency.target_priority > normal.target_priority


def test_more_cards_can_raise_threat_and_lower_killability_at_same_time() -> None:
    score = calculate_target_priority(
        TargetSituation(target_id="手牌依赖", hand_count=7, hand_dependent=True)
    )

    assert score.hand_based_threat_bonus == pytest.approx(0.75)
    assert score.kill_efficiency < 0


def test_three_hp_base_target_gets_transparent_kill_efficiency_modifier() -> None:
    xuyou = calculate_target_priority(
        TargetSituation(
            target_id="许攸",
            base_max_hp=3,
            initial_hp=3,
            current_hp=3,
        )
    )
    four_hp = calculate_target_priority(
        TargetSituation(
            target_id="四体力目标",
            base_max_hp=4,
            initial_hp=4,
            current_hp=4,
        )
    )

    assert xuyou.base_hp_vulnerability == pytest.approx(0.45)
    assert xuyou.kill_efficiency > four_hp.kill_efficiency
    assert xuyou.target_priority > four_hp.target_priority
    assert any("基础体力上限低于四体力基准" in reason for reason in xuyou.reasons)


def test_mode_bonus_does_not_rewrite_xuyou_base_three_hp_profile() -> None:
    lord_xuyou = TargetSituation(
        target_id="主公许攸",
        base_max_hp=3,
        initial_hp=4,
        current_hp=4,
    )
    score = calculate_target_priority(lord_xuyou)

    assert lord_xuyou.base_max_hp == 3
    assert lord_xuyou.initial_hp == 4
    assert score.base_hp_vulnerability == pytest.approx(0.45)


def test_focus_lock_bonus_and_parameters_are_reported() -> None:
    score = calculate_target_priority(
        TargetSituation(target_id="已锁定", already_primary_focus=True),
        defaults=TauntDefaults(),
    )

    assert score.focus_continuity == pytest.approx(0.4)
    assert score.parameters["immediate_kill_bonus"] == pytest.approx(2.5)
    assert any("避免无理由切换" in reason for reason in score.reasons)


def test_unreachable_high_threat_does_not_block_legal_action() -> None:
    selected, all_scores = choose_executable_priority_target(
        (
            TargetSituation(
                target_id="不可达高威胁",
                current_threat=10,
                focus_accessibility=0,
            ),
            TargetSituation(target_id="当前可达", focus_accessibility=1),
        )
    )

    assert selected.target_id == "当前可达"
    assert max(all_scores, key=lambda item: item.current_threat).target_id == "不可达高威胁"


def test_invalid_hand_dependency_parameter_is_rejected() -> None:
    with pytest.raises(ValueError, match="0.15 至 0.4"):
        TauntDefaults(hand_based_threat_per_extra_card=0.8)
