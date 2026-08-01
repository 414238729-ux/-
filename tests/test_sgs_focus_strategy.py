from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from scripts import (
    FocusActionCandidate,
    FocusActionKind,
    FocusRecalculationEvent,
    FocusState,
    FocusSwitchReason,
    TargetAssessment,
    allocate_single_target_attacks,
    plan_focus_actions,
    score_focus_target,
    select_focus_target,
)


ROOT = Path(__file__).resolve().parents[1]
SIMULATION_SPEC = ROOT / "knowledge" / "三国杀模拟规范.md"
CARD_RULES = ROOT / "knowledge" / "三国杀卡牌效果.md"
MODE_RULES = ROOT / "knowledge" / "三国杀模式规则.md"
INSTRUCTIONS = ROOT / "GPT_INSTRUCTIONS.md"


def _target(target_id: str, **changes) -> TargetAssessment:
    base = TargetAssessment(
        target_id,
        static_power=5,
        current_threat=5,
        kill_probability=0.5,
        expected_resources_to_kill=2,
        expected_turns_to_kill=2,
        estimated_kill_value=5,
        number_advantage_value=4,
    )
    return replace(base, **changes)


def test_default_single_target_attacks_are_focused_not_averaged() -> None:
    decision = select_focus_target((_target("甲"), _target("乙")))

    assert decision.primary_focus_target == "甲"
    assert allocate_single_target_attacks(4, decision, ("甲", "乙")) == (
        "甲",
        "甲",
        "甲",
        "甲",
    )


def test_equal_targets_prefer_lower_defense_and_lower_kill_cost() -> None:
    defended = _target(
        "防御者",
        defensive_value=4,
        expected_resources_to_kill=4,
    )
    undefended = _target(
        "无防御者",
        defensive_value=0,
        expected_resources_to_kill=1,
    )

    decision = select_focus_target((defended, undefended))
    assert decision.primary_focus_target == "无防御者"
    assert "击杀资源成本较低" in decision.explanation


def test_two_undefended_targets_prefer_clearly_stronger_current_threat() -> None:
    stronger = _target("强者", static_power=9, current_threat=9)
    weaker = _target("弱者", static_power=3, current_threat=3)

    assert select_focus_target((weaker, stronger)).primary_focus_target == "强者"


def test_near_certain_immediate_kill_can_override_static_power() -> None:
    strong_but_not_close = _target(
        "强者",
        static_power=10,
        current_threat=7,
        kill_probability=0.35,
        expected_resources_to_kill=5,
        expected_turns_to_kill=3,
    )
    weak_but_lethal = _target(
        "弱者",
        static_power=3,
        current_threat=3,
        kill_probability=0.98,
        expected_resources_to_kill=0.5,
        expected_turns_to_kill=0,
    )

    assert (
        select_focus_target((strong_but_not_close, weak_but_lethal))
        .primary_focus_target
        == "弱者"
    )


def test_high_defense_strong_vs_easy_weak_is_dynamic_not_fixed() -> None:
    hard_strong = _target(
        "高防强者",
        static_power=9,
        current_threat=5,
        defensive_value=7,
        kill_probability=0.25,
        expected_resources_to_kill=6,
        expected_turns_to_kill=3,
    )
    easy_weak = _target(
        "易杀弱者",
        static_power=3,
        current_threat=3,
        kill_probability=0.85,
        expected_resources_to_kill=1,
        expected_turns_to_kill=1,
    )
    normal = select_focus_target((hard_strong, easy_weak))
    imminent = select_focus_target(
        (replace(hard_strong, immediate_lethal_threat=9), easy_weak)
    )

    assert normal.primary_focus_target == "易杀弱者"
    assert imminent.primary_focus_target == "高防强者"


def test_blood_profit_target_is_avoided_when_it_cannot_be_killed() -> None:
    blood_profit = _target(
        "卖血者",
        kill_probability=0.15,
        on_damage_benefit=20,
        post_failure_threat=8,
        expected_turns_to_kill=4,
        continue_focus_negative=True,
    )

    decision = select_focus_target((blood_profit,))
    assert decision.primary_focus_target is None
    assert "暂不建立单体集火目标" in decision.explanation


def test_blood_profit_target_can_still_be_focused_for_one_round_kill() -> None:
    blood_profit = _target(
        "可斩杀卖血者",
        kill_probability=0.98,
        on_damage_benefit=20,
        expected_resources_to_kill=1,
        expected_turns_to_kill=0,
        estimated_kill_value=8,
    )

    assert select_focus_target((blood_profit,)).primary_focus_target == "可斩杀卖血者"


def test_imminent_enemy_lethal_threat_overrides_easier_target() -> None:
    easy = _target(
        "易杀目标",
        kill_probability=0.8,
        expected_resources_to_kill=1,
        expected_turns_to_kill=1,
    )
    lethal = _target(
        "即将行动的输出",
        kill_probability=0.35,
        expected_resources_to_kill=4,
        immediate_lethal_threat=8,
    )

    decision = select_focus_target((easy, lethal))
    assert decision.primary_focus_target == "即将行动的输出"
    assert "即时致命威胁" in decision.explanation


def test_growth_target_rises_when_resources_near_burst_threshold() -> None:
    slow = _target(
        "发育者",
        current_threat=2,
        growth_threat=7,
        hand_dependency=6,
        resource_readiness=0.1,
    )
    ready = replace(slow, resource_readiness=0.95)

    assert score_focus_target(ready).target_priority_score > score_focus_target(
        slow
    ).target_priority_score
    assert "资源已接近爆发阈值" in score_focus_target(ready).reasons


def test_focus_lock_ignores_small_temporary_score_advantage() -> None:
    original = _target("甲", kill_probability=0.55)
    other = _target("乙", current_threat=5.5)
    state = FocusState("甲", True)

    decision = select_focus_target(
        (original, other),
        state=state,
        recalculation_event=FocusRecalculationEvent.HP_CHANGE,
    )
    assert decision.primary_focus_target == "甲"
    assert decision.focus_target_switch_reason is FocusSwitchReason.KEEP_FOCUS


def test_other_immediate_kill_allows_focus_switch() -> None:
    current = _target("甲", kill_probability=0.4)
    new_lethal = _target(
        "乙",
        kill_probability=0.95,
        expected_resources_to_kill=1,
        expected_turns_to_kill=0,
    )

    decision = select_focus_target(
        (current, new_lethal),
        state=FocusState("甲", True),
        recalculation_event=FocusRecalculationEvent.HP_CHANGE,
    )
    assert decision.primary_focus_target == "乙"
    assert (
        decision.focus_target_switch_reason
        is FocusSwitchReason.OTHER_IMMEDIATE_KILL
    )


def test_unreachable_theoretical_target_is_distinguished_from_executable_target() -> None:
    unreachable = _target(
        "理论高优先级",
        static_power=10,
        current_threat=10,
        legal_target=False,
        focus_accessibility=0,
    )
    reachable = _target("当前可执行", static_power=3, current_threat=3)

    decision = select_focus_target((unreachable, reachable))
    assert decision.theoretical_priority_target == "理论高优先级"
    assert decision.primary_focus_target == "当前可执行"


def test_defense_spike_and_team_focus_loss_allow_switch() -> None:
    alternative = _target("乙", kill_probability=0.7)
    defense_spike = select_focus_target(
        (_target("甲", defense_spike=True), alternative),
        state=FocusState("甲", True),
        recalculation_event=FocusRecalculationEvent.SKILL_OR_MARK_CHANGE,
    )
    team_lost = select_focus_target(
        (_target("甲", team_focus_support=0), alternative),
        state=FocusState("甲", True),
        recalculation_event=FocusRecalculationEvent.TEAM_FOCUS_CHANGE,
    )

    assert defense_spike.primary_focus_target == "乙"
    assert (
        defense_spike.focus_target_switch_reason
        is FocusSwitchReason.TARGET_DEFENSE_SPIKE
    )
    assert team_lost.primary_focus_target == "乙"
    assert team_lost.focus_target_switch_reason is FocusSwitchReason.TEAM_FOCUS_LOST


def test_dead_unreachable_or_negative_locked_target_does_not_force_persistence() -> None:
    alternative = _target("乙", kill_probability=0.7)
    cases = (
        (
            _target("甲", alive=False),
            FocusRecalculationEvent.DYING_OR_DEATH,
            FocusSwitchReason.TARGET_DEAD,
        ),
        (
            _target("甲", legal_target=False, focus_accessibility=0),
            FocusRecalculationEvent.DISTANCE_CHANGE,
            FocusSwitchReason.TARGET_UNREACHABLE,
        ),
        (
            _target("甲", continue_focus_negative=True, on_damage_benefit=10),
            FocusRecalculationEvent.HP_CHANGE,
            FocusSwitchReason.NEGATIVE_ON_DAMAGE_TRADE,
        ),
    )

    for current, event, expected_reason in cases:
        decision = select_focus_target(
            (current, alternative),
            state=FocusState("甲", True),
            recalculation_event=event,
        )
        assert decision.primary_focus_target == "乙"
        assert decision.focus_target_switch_reason is expected_reason


def test_dangerous_death_effect_reduces_target_priority() -> None:
    safe = _target("安全死亡", kill_probability=0.8)
    dangerous = _target(
        "危险死亡技",
        kill_probability=0.8,
        death_effect_risk=10,
    )

    assert select_focus_target((dangerous, safe)).primary_focus_target == "安全死亡"


def test_victory_on_kill_significantly_raises_priority() -> None:
    ordinary = _target("普通目标", static_power=8, current_threat=8)
    winning = _target(
        "胜利目标",
        static_power=3,
        current_threat=3,
        kill_probability=0.8,
        victory_progress_value=6,
    )

    decision = select_focus_target((ordinary, winning))
    assert decision.primary_focus_target == "胜利目标"
    assert "推进或满足胜利条件" in decision.explanation


def test_hidden_identity_or_hand_information_is_not_used() -> None:
    hidden = _target(
        "隐藏身份候选",
        static_power=99,
        current_threat=99,
        information_legal=False,
    )
    public = _target("合法推断候选", static_power=3, current_threat=3)

    assert select_focus_target((hidden, public)).primary_focus_target == "合法推断候选"
    with pytest.raises(ValueError, match="必须明确披露"):
        _target(
            "非法全知候选",
            uses_omniscient_information=True,
            omniscient_assumption_disclosed=False,
        )


def test_disruption_targets_primary_defense_and_control_can_cover_other_enemy() -> None:
    primary = _target(
        "主目标",
        kill_probability=0.95,
        victory_progress_value=5,
    )
    secondary = _target(
        "次目标",
        current_threat=3,
        immediate_lethal_threat=2,
    )
    decision = select_focus_target((primary, secondary))
    planned = plan_focus_actions(
        (
            FocusActionCandidate(
                "过河拆桥",
                FocusActionKind.DISRUPT_DEFENSE_OR_RESCUE,
                ("主目标", "次目标"),
            ),
            FocusActionCandidate(
                "乐不思蜀",
                FocusActionKind.CONTROL,
                ("主目标", "次目标"),
            ),
        ),
        decision,
    )

    assert planned[0].target_id == "主目标"
    assert "防御或救援" in planned[0].reason
    assert planned[1].target_id == "次目标"
    assert "保护集火过程" in planned[1].reason


def test_damage_duel_chain_and_fire_actions_serve_primary_target() -> None:
    decision = select_focus_target(
        (
            _target("主目标", kill_probability=0.9),
            _target("次目标", kill_probability=0.4),
        )
    )
    planned = plan_focus_actions(
        (
            FocusActionCandidate(
                "杀",
                FocusActionKind.SINGLE_TARGET_DAMAGE,
                ("主目标", "次目标"),
            ),
            FocusActionCandidate(
                "决斗",
                FocusActionKind.DUEL,
                ("主目标", "次目标"),
            ),
            FocusActionCandidate(
                "铁索火攻组合",
                FocusActionKind.CHAIN_OR_FIRE_COMBO,
                ("主目标", "次目标"),
            ),
        ),
        decision,
    )

    assert {action.target_id for action in planned} == {"主目标"}
    assert all(action.serves_primary_focus for action in planned)
    assert "铁索或火攻组合服务于主要目标" in planned[2].reason


def test_same_input_produces_stable_target_and_explanation() -> None:
    targets = (_target("甲"), _target("乙"))

    first = select_focus_target(targets)
    second = select_focus_target(targets)
    assert first == second
    assert "选择集火甲" in first.explanation
    assert not first.explanation.endswith("分数。")


def test_invalid_target_values_have_clear_chinese_errors() -> None:
    with pytest.raises(ValueError, match="必须在0到1之间"):
        _target("甲", kill_probability=1.1)
    with pytest.raises(ValueError, match="非负有限数值"):
        _target("甲", expected_resources_to_kill=-1)


def test_focus_strategy_is_documented_once_in_simulation_layer() -> None:
    spec = SIMULATION_SPEC.read_text(encoding="utf-8")
    cards = CARD_RULES.read_text(encoding="utf-8")
    modes = MODE_RULES.read_text(encoding="utf-8")

    heading = "### 5.13 集火与攻击目标选择AI策略"
    assert spec.count(heading) == 1
    assert heading not in cards
    assert heading not in modes
    for field_name in (
        "static_power",
        "current_threat",
        "immediate_lethal_threat",
        "kill_probability",
        "expected_resources_to_kill",
        "expected_turns_to_kill",
        "defensive_value",
        "on_damage_benefit",
        "retaliation_risk",
        "growth_threat",
        "hand_dependency",
        "focus_accessibility",
        "death_effect_risk",
        "target_priority_score",
        "primary_focus_target",
        "focus_target_lock",
        "focus_target_switch_reason",
    ):
        assert f"`{field_name}`" in spec or f"{field_name}:" in spec
    assert "不得仅因两名敌人都可攻击就轮流或平均分配伤害" in spec
    assert "单体资源的默认分配是集中而不是轮流" in spec
    assert "本节属于理性AI的计算策略，不是卡牌效果或模式基础规则" in spec


def test_instructions_only_add_compact_focus_strategy_route() -> None:
    instructions = INSTRUCTIONS.read_text(encoding="utf-8")
    route = (
        "目标选择应查询模拟规范中的集火、威胁、击杀效率和卖血收益策略，"
        "不得随机分散攻击。"
    )

    assert instructions.count(route) == 1
    assert len(instructions) <= 7000
    assert "static_power" not in instructions
    assert "focus_target_switch_reason" not in instructions
