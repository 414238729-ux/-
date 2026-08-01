from __future__ import annotations

import pytest

from scripts.sgs_skill_framework import (
    AwakeningSkillState,
    CardTerm,
    CardZone,
    ChargeState,
    ConversionSkillState,
    ConversionState,
    EquipmentEffectFrequency,
    InvalidationKind,
    LimitedSkillState,
    MissionSkillState,
    MissionState,
    SkillInvalidation,
    SkillInvalidationScope,
    SkillSource,
    SkillState,
    SkillType,
    activation_is_mandatory,
    invalidate_skills,
    record_card_use,
    resolve_damage_then_after_damage_skill,
    zones_for_card_term,
)


def _temporary(end: str = "回合结束") -> SkillInvalidation:
    return SkillInvalidation(InvalidationKind.TEMPORARY, duration=end)


def test_skill_type_tags_can_be_combined() -> None:
    skill = SkillState(
        "复合技能",
        type_tags=("锁定技", "持恒技", "转换技", "蓄力技"),
    )
    assert skill.type_tags == frozenset(
        {
            SkillType.LOCKED,
            SkillType.PERSEVERING,
            SkillType.CONVERSION,
            SkillType.CHARGE,
        }
    )


def test_locked_skill_is_mandatory_but_you_may_text_remains_optional() -> None:
    skill = SkillState("锁定效果", type_tags=(SkillType.LOCKED,))
    assert activation_is_mandatory(skill, conditions_met=True)
    assert not activation_is_mandatory(
        skill,
        conditions_met=True,
        text_allows_choice=True,
    )
    assert not activation_is_mandatory(skill, conditions_met=False)


def test_limited_awakening_and_mission_states_are_independent() -> None:
    limited = LimitedSkillState().consume()
    assert not limited.can_activate
    with pytest.raises(ValueError, match="限定技次数已经消耗"):
        limited.consume()
    assert limited.restore().can_activate

    awakening = AwakeningSkillState().resolve(conditions_met=True)
    assert awakening.awakened
    awakening_skill = SkillState("觉醒", type_tags=(SkillType.AWAKENING,))
    assert activation_is_mandatory(awakening_skill, conditions_met=True)

    mission = MissionSkillState().resolve(MissionState.SUCCESS)
    assert mission.status is MissionState.SUCCESS
    with pytest.raises(ValueError, match="使命已经结算"):
        mission.resolve(MissionState.FAILURE)


def test_persevering_skill_is_not_invalidated_but_can_be_lost() -> None:
    skill = SkillState("持恒", type_tags=(SkillType.PERSEVERING,))
    invalidation_attempt = skill.invalidate(_temporary())
    assert invalidation_attempt is skill
    assert invalidation_attempt.effective

    lost = skill.lose()
    assert lost.lost
    assert not lost.owned
    assert not lost.effective


def test_skill_invalidation_and_skill_loss_are_separate_states() -> None:
    skill = SkillState("普通技能")
    invalidated = skill.invalidate(_temporary())
    assert invalidated.owned
    assert invalidated.invalidated
    assert not invalidated.lost

    lost = invalidated.lose()
    assert lost.lost
    assert not lost.owned
    assert not lost.invalidated


def test_general_card_only_invalidation_does_not_touch_landlord_or_granted_skills() -> None:
    skills = (
        SkillState("武将技", source=SkillSource.GENERAL_CARD),
        SkillState("飞扬", source=SkillSource.IDENTITY),
        SkillState("跋扈", source=SkillSource.IDENTITY),
        SkillState("他授技能", source=SkillSource.GRANTED_BY_CHARACTER),
    )
    result = invalidate_skills(
        skills,
        scope=SkillInvalidationScope.GENERAL_CARD_ONLY,
        effect=_temporary(),
    )
    assert result[0].invalidated
    assert all(skill.effective for skill in result[1:])


def test_all_skill_invalidation_covers_identity_and_granted_but_excludes_persevering() -> None:
    skills = (
        SkillState("武将技", source=SkillSource.GENERAL_CARD),
        SkillState("飞扬", source=SkillSource.IDENTITY),
        SkillState("他授技能", source=SkillSource.GRANTED_BY_CHARACTER),
        SkillState(
            "持恒身份技",
            source=SkillSource.IDENTITY,
            type_tags=(SkillType.PERSEVERING,),
        ),
    )
    result = invalidate_skills(
        skills,
        scope=SkillInvalidationScope.ALL_OWNED_SKILLS,
        effect=_temporary(),
    )
    assert all(skill.invalidated for skill in result[:3])
    assert result[3].effective


def test_temporary_invalidation_recovers_at_its_duration_event() -> None:
    skill = SkillState("临时失效测试").invalidate(_temporary("下回合开始"))
    assert skill.recover("回合结束").invalidated
    recovered = skill.recover("下回合开始")
    assert recovered.effective
    assert recovered.invalidation is None


def test_semi_permanent_invalidation_only_recovers_on_named_condition() -> None:
    effect = SkillInvalidation(
        InvalidationKind.SEMI_PERMANENT,
        recovery_condition="重新获得指定标记",
    )
    skill = SkillState("半永久失效测试").invalidate(effect)
    assert skill.recover("回合结束").invalidated
    assert skill.recover("重新获得指定标记").effective


def test_lost_skill_is_not_restored_by_invalidation_recovery_event() -> None:
    lost = SkillState("已失去").lose()
    assert lost.recover("回合结束") is lost
    assert not lost.owned


def test_conversion_skill_starts_yang_and_toggles_after_each_effect() -> None:
    conversion = ConversionSkillState()
    assert conversion.state is ConversionState.YANG
    assert conversion.initial_state is ConversionState.YANG
    assert conversion.state_specific_limit is None
    assert conversion.can_resolve(uses_in_scope=999)

    yin = conversion.resolve_effect()
    assert yin.state is ConversionState.YIN
    assert yin.resolve_effect().state is ConversionState.YANG


def test_conversion_skill_respects_only_an_explicit_limit() -> None:
    conversion = ConversionSkillState(state_specific_limit=1)
    assert conversion.can_resolve(uses_in_scope=0)
    assert not conversion.can_resolve(uses_in_scope=1)
    with pytest.raises(ValueError, match="明确规定的次数限制"):
        conversion.resolve_effect(uses_in_scope=1)


def test_charge_three_over_four_parses_initial_and_maximum() -> None:
    charge = ChargeState.parse("3/4", resource_key="技能甲蓄力")
    assert charge.initial == 3
    assert charge.current == 3
    assert charge.maximum == 4
    assert charge.resource_key == "技能甲蓄力"


def test_charge_gain_is_capped_and_does_not_auto_restore() -> None:
    charge = ChargeState.parse("3/4")
    capped = charge.gain(10)
    assert capped.current == 4
    assert capped.initial == 3
    assert charge.current == 3


def test_charge_cannot_spend_more_than_current_points() -> None:
    charge = ChargeState.parse("3/4").spend(2)
    assert charge.current == 1
    with pytest.raises(ValueError, match="不能超过当前点数"):
        charge.spend(2)


def test_charge_rejects_invalid_notation_with_chinese_error() -> None:
    with pytest.raises(ValueError, match="初始点数/上限"):
        ChargeState.parse("三比四")
    with pytest.raises(ValueError, match="不能超过蓄力上限"):
        ChargeState.parse("5/4")


def test_after_damage_skill_waits_until_dying_rescue_succeeds() -> None:
    callback_hp: list[int] = []
    result = resolve_damage_then_after_damage_skill(
        1,
        2,
        rescue_amounts=(1, 1),
        on_after_damage=callback_hp.append,
    )
    assert result.hp_after_damage == -1
    assert result.final_hp == 1
    assert result.entered_dying
    assert result.rescued
    assert not result.died
    assert result.after_damage_skill_resolved
    assert callback_hp == [1]
    assert result.event_log.index("脱离濒死") < result.event_log.index(
        "结算普通受到伤害后技能"
    )


def test_after_damage_skill_does_not_resolve_if_rescue_fails() -> None:
    called: list[int] = []
    result = resolve_damage_then_after_damage_skill(
        1,
        2,
        rescue_amounts=(1,),
        on_after_damage=called.append,
    )
    assert result.final_hp == 0
    assert result.died
    assert not result.after_damage_skill_resolved
    assert called == []
    assert result.event_log[-1] == "确认死亡"


def test_nonlethal_damage_resolves_after_damage_skill_without_rescue() -> None:
    called: list[int] = []
    result = resolve_damage_then_after_damage_skill(
        4,
        1,
        on_after_damage=called.append,
    )
    assert not result.entered_dying
    assert not result.died
    assert called == [3]


def test_card_term_excludes_judgment_but_cards_in_zones_include_all_three() -> None:
    assert zones_for_card_term(CardTerm.CARD) == frozenset(
        {CardZone.HAND, CardZone.EQUIPMENT}
    )
    assert zones_for_card_term("手牌") == frozenset({CardZone.HAND})
    assert zones_for_card_term("区域内的牌") == frozenset(
        {CardZone.HAND, CardZone.EQUIPMENT, CardZone.JUDGMENT}
    )


def test_invalidated_card_effect_still_records_use_event_and_count() -> None:
    result = record_card_use(
        "决斗",
        prior_turn_use_count=2,
        effect_invalidated=True,
    )
    assert result.use_event_recorded
    assert result.use_sequence == 3
    assert result.turn_use_count == 3
    assert result.effect_invalidated
    assert not result.effect_completed
    assert not result.after_resolution_event_recorded


def test_normal_card_effect_records_both_use_and_completed_resolution() -> None:
    result = record_card_use("杀")
    assert result.use_event_recorded
    assert result.effect_completed
    assert result.after_resolution_event_recorded


def test_equipment_effect_without_written_limit_can_trigger_repeatedly() -> None:
    unlimited = EquipmentEffectFrequency()
    assert unlimited.can_trigger(0)
    assert unlimited.can_trigger(999)

    once_per_event = EquipmentEffectFrequency(
        explicit_limit=1,
        limit_scope="每次事件",
    )
    assert once_per_event.can_trigger(0)
    assert not once_per_event.can_trigger(1)


def test_invalid_framework_inputs_raise_clear_chinese_errors() -> None:
    with pytest.raises(ValueError, match="技能类型标签只能是"):
        SkillState("错误标签", type_tags=("被动",))
    with pytest.raises(ValueError, match="半永久失效必须注明恢复条件"):
        SkillInvalidation(InvalidationKind.SEMI_PERMANENT)
    with pytest.raises(TypeError, match="本回合此前使用牌数必须是整数"):
        record_card_use("杀", prior_turn_use_count=True)
