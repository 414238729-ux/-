from __future__ import annotations

import pytest

import scripts
from scripts.sgs_card_rules import DamageType
from scripts.sgs_incremental_mechanics import (
    AttributedDamageEvent,
    CardEffectOutcome,
    CardRestrictions,
    CardUseLifecycle,
    DamageProvenance,
    DamageTriggerBasis,
    GeneralSidePhysicalCard,
    OriginatingPhysicalCard,
    SpecialCardAction,
    SpecialCardVisibility,
    check_general_side_card_permission,
    damage_trigger_basis_from_text,
    damage_trigger_count,
    derive_chain_damage_events,
    record_card_response,
    resolve_card_use_lifecycle,
)


def _bell(
    name: str = "闪",
    category: str = "基本牌",
) -> GeneralSidePhysicalCard:
    return GeneralSidePhysicalCard("bell-1", name, category)


def test_per_damage_point_and_per_event_trigger_counts_are_distinct() -> None:
    assert damage_trigger_count(2, DamageTriggerBasis.PER_DAMAGE_POINT) == 2
    assert damage_trigger_count(2, DamageTriggerBasis.PER_DAMAGE_EVENT) == 1
    assert damage_trigger_count(5, "每个伤害事件") == 1


def test_zero_actual_damage_produces_no_damage_trigger() -> None:
    assert damage_trigger_count(0, DamageTriggerBasis.PER_DAMAGE_POINT) == 0
    assert damage_trigger_count(0, DamageTriggerBasis.PER_DAMAGE_EVENT) == 0


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("每造成1点伤害，你摸一张牌", DamageTriggerBasis.PER_DAMAGE_POINT),
        ("每受到1点伤害，获得标记", DamageTriggerBasis.PER_DAMAGE_POINT),
        ("造成伤害后，你可以摸牌", DamageTriggerBasis.PER_DAMAGE_EVENT),
        ("当你受到伤害时，你可以发动", DamageTriggerBasis.PER_DAMAGE_EVENT),
    ],
)
def test_damage_trigger_wording_is_classified(
    text: str,
    expected: DamageTriggerBasis,
) -> None:
    assert damage_trigger_basis_from_text(text) is expected


def test_unknown_damage_trigger_wording_is_not_guessed() -> None:
    with pytest.raises(ValueError, match="未包含可识别"):
        damage_trigger_basis_from_text("你可以获得一个标记")


def test_chain_events_inherit_source_attribute_and_original_physical_card() -> None:
    card = OriginatingPhysicalCard(
        card_name="火杀",
        physical_card_ids=("deck-041",),
        owner_id="甲",
    )
    provenance = DamageProvenance("甲", DamageType.FIRE, card)
    original = AttributedDamageEvent(10, "乙", 2, provenance)

    propagated = derive_chain_damage_events(
        original,
        (("丙", 2), ("丁", 1)),
    )

    assert [event.event_id for event in propagated] == [11, 12]
    assert [event.target_id for event in propagated] == ["丙", "丁"]
    assert [event.actual_damage for event in propagated] == [2, 1]
    assert all(event.parent_event_id == 10 for event in propagated)
    assert all(event.is_chain_propagation for event in propagated)
    assert all(event.provenance is provenance for event in propagated)
    assert all(event.provenance.source_id == "甲" for event in propagated)
    assert all(event.provenance.damage_type is DamageType.FIRE for event in propagated)
    assert all(event.provenance.originating_card is card for event in propagated)
    assert all(event.provenance.originating_card.owner_id == "甲" for event in propagated)


def test_each_chain_recipient_is_an_independent_damage_event() -> None:
    original = AttributedDamageEvent(
        1,
        "入口",
        3,
        DamageProvenance("伤害来源", DamageType.THUNDER),
    )
    events = derive_chain_damage_events(original, (("目标一", 3), ("目标二", 3)))

    assert len({event.event_id for event in events}) == 2
    assert all(event.trigger_is_independent_damage_event for event in events)
    assert [
        damage_trigger_count(event.actual_damage, DamageTriggerBasis.PER_DAMAGE_EVENT)
        for event in events
    ] == [1, 1]
    assert [
        damage_trigger_count(event.actual_damage, DamageTriggerBasis.PER_DAMAGE_POINT)
        for event in events
    ] == [3, 3]


def test_chain_metadata_is_not_reassigned_to_chain_card_or_first_victim() -> None:
    origin = OriginatingPhysicalCard("雷杀", ("slash-7",), "原使用者")
    event = AttributedDamageEvent(
        5,
        "首名受伤者",
        1,
        DamageProvenance("原使用者", DamageType.THUNDER, origin),
    )
    propagated = derive_chain_damage_events(event, (("后续目标", 1),))[0]

    assert propagated.provenance.source_id == "原使用者"
    assert propagated.provenance.originating_card.card_name == "雷杀"
    assert propagated.provenance.originating_card.card_name != "铁索连环"
    assert propagated.provenance.source_id != "首名受伤者"


def test_non_elemental_or_zero_damage_cannot_create_chain_events() -> None:
    ordinary = AttributedDamageEvent(
        1,
        "甲",
        1,
        DamageProvenance("乙", DamageType.UNATTRIBUTED),
    )
    with pytest.raises(ValueError, match="只有火属性或雷属性"):
        derive_chain_damage_events(ordinary, (("丙", 1),))

    prevented = AttributedDamageEvent(
        2,
        "甲",
        0,
        DamageProvenance("乙", DamageType.FIRE),
    )
    with pytest.raises(ValueError, match="未实际造成伤害"):
        derive_chain_damage_events(prevented, (("丙", 0),))


def test_general_side_physical_card_is_public_by_default() -> None:
    bell = _bell()
    assert bell.is_public
    assert bell.visibility is SpecialCardVisibility.PUBLIC
    assert bell.public_face_information == (
        "牌名",
        "花色",
        "点数",
        "类别",
        "其他正常牌面信息",
    )


def test_explicit_hidden_wording_overrides_default_publicity() -> None:
    hidden = GeneralSidePhysicalCard(
        "secret-1",
        "未知牌",
        "基本牌",
        visibility=SpecialCardVisibility.FACE_DOWN,
    )
    assert not hidden.is_public
    assert hidden.public_face_information == ()


@pytest.mark.parametrize(
    "action",
    [SpecialCardAction.USE, SpecialCardAction.RESPOND],
)
def test_hand_only_ban_does_not_block_general_side_card(
    action: SpecialCardAction,
) -> None:
    restrictions = CardRestrictions(
        hand_use_forbidden=True,
        hand_response_forbidden=True,
    )
    result = check_general_side_card_permission(
        _bell(),
        action,
        restrictions=restrictions,
    )
    assert result.allowed
    assert not result.counts_as_normal_hand_card


@pytest.mark.parametrize(
    "action",
    [
        SpecialCardAction.DISCARD_HAND_COST,
        SpecialCardAction.GIVE_HAND_COST,
        SpecialCardAction.SHOW_HAND_COST,
        SpecialCardAction.EXCHANGE_HAND_COST,
        SpecialCardAction.COUNT_AS_HAND,
    ],
)
def test_acting_as_hand_does_not_pay_normal_hand_only_costs(
    action: SpecialCardAction,
) -> None:
    result = check_general_side_card_permission(_bell(), action)
    assert not result.allowed
    assert "不等于普通手牌" in result.reason


def test_global_use_and_response_bans_apply_to_special_cards() -> None:
    use = check_general_side_card_permission(
        _bell("杀"),
        SpecialCardAction.USE,
        restrictions=CardRestrictions(all_card_use_forbidden=True),
    )
    response = check_general_side_card_permission(
        _bell(),
        SpecialCardAction.RESPOND,
        restrictions=CardRestrictions(all_card_response_forbidden=True),
    )
    assert not use.allowed and "不能使用牌" in use.reason
    assert not response.allowed and "不能响应" in response.reason


def test_current_unrespondable_card_blocks_special_card_response() -> None:
    result = check_general_side_card_permission(
        _bell(),
        SpecialCardAction.RESPOND,
        restrictions=CardRestrictions(current_card_unrespondable=True),
    )
    assert not result.allowed
    assert "不可被响应" in result.reason


def test_forbidden_card_name_and_category_apply_to_special_cards() -> None:
    slash = check_general_side_card_permission(
        _bell("杀"),
        SpecialCardAction.USE,
        restrictions=CardRestrictions(forbidden_card_names=frozenset({"杀"})),
    )
    nullification = check_general_side_card_permission(
        _bell("无懈可击", "锦囊牌"),
        SpecialCardAction.RESPOND,
        restrictions=CardRestrictions(forbidden_categories=frozenset({"锦囊牌"})),
    )
    assert not slash.allowed
    assert not nullification.allowed


def test_special_card_can_be_zhangba_material_but_cannot_bypass_slash_ban() -> None:
    allowed = check_general_side_card_permission(
        _bell("桃"),
        SpecialCardAction.ZHANGBA_MATERIAL,
    )
    blocked = check_general_side_card_permission(
        _bell("桃"),
        SpecialCardAction.ZHANGBA_MATERIAL,
        restrictions=CardRestrictions(forbidden_card_names=frozenset({"杀"})),
    )
    assert allowed.allowed
    assert not blocked.allowed
    assert "【杀】" in blocked.reason


def test_zhangba_response_material_respects_response_ban() -> None:
    result = check_general_side_card_permission(
        _bell("桃"),
        SpecialCardAction.ZHANGBA_MATERIAL,
        zhangba_output_action=SpecialCardAction.RESPOND,
        restrictions=CardRestrictions(all_card_response_forbidden=True),
    )
    assert not result.allowed


def test_card_without_act_as_hand_permission_cannot_use_or_respond() -> None:
    special = GeneralSidePhysicalCard(
        "pile-1",
        "杀",
        "基本牌",
        can_act_as_hand_for_use_or_response=False,
    )
    result = check_general_side_card_permission(special, SpecialCardAction.USE)
    assert not result.allowed
    assert "没有授予" in result.reason


def test_normal_card_use_records_use_completion_and_effect_resolution() -> None:
    result = resolve_card_use_lifecycle("过河拆桥")
    assert result.card_used
    assert not result.card_responded
    assert result.card_use_completed
    assert result.effect_resolved
    assert not result.effect_cancelled_by_nullification
    assert not result.card_or_effect_invalidated


def test_nullification_cancels_effect_but_use_flow_still_completes() -> None:
    result = resolve_card_use_lifecycle(
        "过河拆桥",
        CardEffectOutcome.CANCELLED_BY_NULLIFICATION,
    )
    assert result.card_used
    assert result.effect_cancelled_by_nullification
    assert not result.card_or_effect_invalidated
    assert result.card_use_completed
    assert not result.effect_resolved


def test_true_invalidation_keeps_used_event_but_not_completion_nodes() -> None:
    result = resolve_card_use_lifecycle(
        "杀",
        CardEffectOutcome.INVALIDATED,
    )
    assert result.card_used
    assert not result.effect_cancelled_by_nullification
    assert result.card_or_effect_invalidated
    assert not result.card_use_completed
    assert not result.effect_resolved


def test_explicitly_played_response_is_not_automatically_a_used_card() -> None:
    result = record_card_response("杀")
    assert result.card_responded
    assert result.card_played
    assert not result.card_used
    assert not result.card_use_completed


def test_generic_response_api_rejects_context_free_jink() -> None:
    with pytest.raises(ValueError, match="按响应对象区分使用或打出"):
        record_card_response("闪")


def test_nullification_and_true_invalidation_cannot_share_one_state() -> None:
    with pytest.raises(ValueError, match="不能合并"):
        CardUseLifecycle(
            card_name="锦囊",
            card_used=True,
            card_responded=False,
            effect_cancelled_by_nullification=True,
            card_or_effect_invalidated=True,
            card_use_completed=False,
            effect_resolved=False,
        )


def test_invalid_inputs_raise_chinese_errors() -> None:
    with pytest.raises(TypeError, match="最终实际伤害必须是整数"):
        damage_trigger_count(True, DamageTriggerBasis.PER_DAMAGE_EVENT)
    with pytest.raises(ValueError, match="不能重复"):
        OriginatingPhysicalCard("杀", ("same", "same"), "甲")
    with pytest.raises(ValueError, match="晚于原始伤害事件"):
        derive_chain_damage_events(
            AttributedDamageEvent(
                10,
                "乙",
                1,
                DamageProvenance("甲", DamageType.FIRE),
            ),
            (("丙", 1),),
            first_event_id=10,
        )


def test_public_package_exports_incremental_mechanics() -> None:
    names = (
        "AttributedDamageEvent",
        "CardEffectOutcome",
        "CardRestrictions",
        "CardUseLifecycle",
        "DamageProvenance",
        "DamageTriggerBasis",
        "GeneralSidePhysicalCard",
        "OriginatingPhysicalCard",
        "SpecialCardAction",
        "SpecialCardVisibility",
        "damage_trigger_count",
        "derive_chain_damage_events",
        "resolve_card_use_lifecycle",
    )
    assert all(name in scripts.__all__ for name in names)
    assert all(hasattr(scripts, name) for name in names)
