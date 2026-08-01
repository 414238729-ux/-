from __future__ import annotations

from scripts.sgs_card_rules import (
    EquipmentEffectRule,
    EquipmentSlot,
    EquipmentState,
    NAMED_MOUNT_RULES,
    check_equipment_effect_trigger,
    use_named_mount,
)


def test_two_attack_horses_replace_in_same_slot() -> None:
    state = EquipmentState({})
    first = use_named_mount(state, "赤兔")
    second = use_named_mount(first.state_after, "大宛")

    assert second.replaced_card == "赤兔"
    assert second.state_after.slots == {"attack_horse": "大宛"}


def test_two_defense_horses_replace_in_same_slot() -> None:
    state = EquipmentState({})
    first = use_named_mount(state, "的卢")
    second = use_named_mount(first.state_after, "绝影")

    assert second.replaced_card == "的卢"
    assert second.state_after.slots == {"defense_horse": "绝影"}


def test_attack_and_defense_horses_can_coexist() -> None:
    state = use_named_mount(EquipmentState({}), "紫骍").state_after
    state = use_named_mount(state, "骅骝").state_after

    assert state.slots == {"attack_horse": "紫骍", "defense_horse": "骅骝"}


def test_all_seven_named_mounts_have_slot_and_distance_mapping() -> None:
    assert set(NAMED_MOUNT_RULES) == {
        "紫骍",
        "赤兔",
        "大宛",
        "骅骝",
        "的卢",
        "爪黄飞电",
        "绝影",
    }
    assert {
        item.distance_modifier
        for item in NAMED_MOUNT_RULES.values()
        if item.equipment_slot is EquipmentSlot.ATTACK_HORSE
    } == {-1}
    assert {
        item.distance_modifier
        for item in NAMED_MOUNT_RULES.values()
        if item.equipment_slot is EquipmentSlot.DEFENSE_HORSE
    } == {1}


def test_equipment_effect_without_explicit_limit_can_trigger_each_event() -> None:
    rule = EquipmentEffectRule(explicit_limit=None, simulation_hard_limit=5)

    assert check_equipment_effect_trigger(rule, prior_activations=0, condition_met=True).can_trigger
    assert check_equipment_effect_trigger(rule, prior_activations=3, condition_met=True).can_trigger


def test_equipment_effect_is_not_automatically_once_per_turn() -> None:
    check = check_equipment_effect_trigger(
        EquipmentEffectRule(), prior_activations=1, condition_met=True
    )

    assert check.can_trigger
    assert not check.stopped_by_rule_limit


def test_explicit_rule_limit_and_program_hard_limit_are_distinct() -> None:
    rule_limited = check_equipment_effect_trigger(
        EquipmentEffectRule(explicit_limit=1),
        prior_activations=1,
        condition_met=True,
    )
    simulation_limited = check_equipment_effect_trigger(
        EquipmentEffectRule(explicit_limit=None, simulation_hard_limit=2),
        prior_activations=2,
        condition_met=True,
    )

    assert rule_limited.stopped_by_rule_limit
    assert not rule_limited.truncated_by_simulation_limit
    assert simulation_limited.truncated_by_simulation_limit
    assert not simulation_limited.stopped_by_rule_limit
    assert "不是游戏规则次数限制" in simulation_limited.reason

