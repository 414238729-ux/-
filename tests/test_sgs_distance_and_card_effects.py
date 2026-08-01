import pytest

from scripts import (
    CardEffectKind,
    DamageType,
    TwoVsTwoDistanceState,
    TwoVsTwoTable,
    apply_silver_lion_damage,
    apply_silver_lion_to_hp_loss,
    can_target_attack_range_effect,
    can_target_distance_one_trick,
    can_target_fire_attack,
    can_target_snatch,
    can_target_supply_shortage,
    can_target_with_slash,
    get_actual_distance,
    is_in_attack_range,
    resolve_card_damage_defaults,
    resolve_fire_attack,
    resolve_silver_lion_leaving,
    resolve_vine_armor,
)


def test_supply_shortage_accepts_only_actual_distance_one() -> None:
    state = TwoVsTwoDistanceState()

    assert get_actual_distance(1, 2, state) == 1
    assert can_target_supply_shortage(1, 2, state)
    assert get_actual_distance(1, 3, state) == 2
    assert not can_target_supply_shortage(1, 3, state)


def test_weapon_attack_range_does_not_change_distance_one_tricks() -> None:
    state = TwoVsTwoDistanceState(attack_ranges={1: 3})

    assert get_actual_distance(1, 3, state) == 2
    assert is_in_attack_range(1, 3, state)
    assert can_target_with_slash(1, 3, state)
    assert not can_target_snatch(1, 3, state)
    assert not can_target_supply_shortage(1, 3, state)


def test_attack_mount_can_reduce_actual_distance_two_to_one() -> None:
    state = TwoVsTwoDistanceState(
        outgoing_actual_distance_modifiers={1: -1}
    )

    assert get_actual_distance(1, 3, state) == 1
    assert can_target_snatch(1, 3, state)
    assert can_target_supply_shortage(1, 3, state)


def test_defensive_mount_can_increase_actual_distance_one_to_two() -> None:
    state = TwoVsTwoDistanceState(
        incoming_actual_distance_modifiers={2: 1}
    )

    assert get_actual_distance(1, 2, state) == 2
    assert not can_target_snatch(1, 2, state)
    assert not can_target_supply_shortage(1, 2, state)


def test_distance_uses_current_seats_after_position_swap() -> None:
    initial = TwoVsTwoDistanceState()
    swapped = TwoVsTwoDistanceState(
        table=TwoVsTwoTable().swap_seats(1, 2)
    )

    assert get_actual_distance(1, 3, initial) == 2
    assert not can_target_supply_shortage(1, 3, initial)
    assert get_actual_distance(1, 3, swapped) == 1
    assert can_target_supply_shortage(1, 3, swapped)
    assert swapped.table.are_teammates(1, 4)


@pytest.mark.parametrize(
    ("target", "expected"),
    [(2, True), (3, False), (4, True)],
)
def test_snatch_and_supply_shortage_share_actual_distance_logic(
    target: int,
    expected: bool,
) -> None:
    state = TwoVsTwoDistanceState()

    assert can_target_distance_one_trick(1, target, state) is expected
    assert can_target_snatch(1, target, state) is expected
    assert can_target_supply_shortage(1, target, state) is expected


def test_explicit_attack_range_and_distance_wording_use_separate_checks() -> None:
    state = TwoVsTwoDistanceState(attack_ranges={1: 3})

    assert can_target_attack_range_effect(1, 3, state)
    assert not can_target_distance_one_trick(1, 3, state)


def test_invalid_distance_state_uses_clear_chinese_error() -> None:
    with pytest.raises(TypeError, match="整数修正值"):
        TwoVsTwoDistanceState(outgoing_actual_distance_modifiers={1: -1.0})
    with pytest.raises(ValueError, match="攻击范围必须大于或等于 1"):
        TwoVsTwoDistanceState(attack_ranges={1: 0})


def test_fire_attack_requires_a_hand_card_when_target_is_selected() -> None:
    assert can_target_fire_attack(1)
    assert not can_target_fire_attack(0)
    with pytest.raises(ValueError, match="至少有一张手牌"):
        resolve_fire_attack(0, 0)


def test_fire_attack_ends_if_legal_target_has_no_hand_at_reveal() -> None:
    result = resolve_fire_attack(1, 0)

    assert result.ended_due_to_no_hand
    assert not result.hand_card_revealed
    assert not result.matching_suit_discard_step_available
    assert not result.fire_damage_step_available


def test_fire_attack_continues_when_target_still_has_a_hand_at_reveal() -> None:
    result = resolve_fire_attack(2, 1)

    assert not result.ended_due_to_no_hand
    assert result.hand_card_revealed
    assert result.matching_suit_discard_step_available
    assert result.fire_damage_step_available


def test_normal_slash_is_invalidated_by_vine_armor() -> None:
    result = resolve_vine_armor(CardEffectKind.NORMAL_SLASH)

    assert not result.card_effective
    assert not result.reaches_damage_stage
    assert result.damage_type is None


def test_slash_converted_to_fire_before_armor_check_affects_vine() -> None:
    result = resolve_vine_armor(
        CardEffectKind.NORMAL_SLASH,
        converted_before_armor_check=CardEffectKind.FIRE_SLASH,
    )

    assert result.card_effective
    assert result.reaches_damage_stage
    assert result.card_at_armor_check is CardEffectKind.FIRE_SLASH
    assert result.damage_type is DamageType.FIRE
    assert result.fire_damage_bonus == 1


def test_late_damage_conversion_cannot_restore_invalidated_normal_slash() -> None:
    result = resolve_vine_armor(
        CardEffectKind.NORMAL_SLASH,
        late_damage_type=DamageType.FIRE,
    )

    assert not result.card_effective
    assert not result.reaches_damage_stage
    assert result.damage_type is None


@pytest.mark.parametrize(
    "card_effect",
    [CardEffectKind.BARBARIAN_INVASION, CardEffectKind.ARCHERY_ATTACK],
)
def test_aoe_remains_invalid_against_vine_after_late_conversion(
    card_effect: CardEffectKind,
) -> None:
    result = resolve_vine_armor(
        card_effect,
        late_damage_type=DamageType.FIRE,
    )

    assert not result.card_effective
    assert not result.reaches_damage_stage


@pytest.mark.parametrize(
    "card_effect",
    [CardEffectKind.BARBARIAN_INVASION, CardEffectKind.ARCHERY_ATTACK],
)
def test_aoe_resolves_normally_when_vine_armor_is_inactive(
    card_effect: CardEffectKind,
) -> None:
    result = resolve_vine_armor(card_effect, armor_active=False)

    assert result.card_effective
    assert result.reaches_damage_stage
    assert result.damage_type is DamageType.UNATTRIBUTED


@pytest.mark.parametrize(
    "damage_type",
    [DamageType.UNATTRIBUTED, DamageType.FIRE, DamageType.THUNDER],
)
def test_silver_lion_reduces_all_damage_types_to_one(
    damage_type: DamageType,
) -> None:
    assert apply_silver_lion_damage(2, damage_type, source="甲") == 1
    assert apply_silver_lion_damage(5, damage_type, source="甲") == 1


def test_silver_lion_applies_to_sourceless_damage_but_not_hp_loss() -> None:
    assert apply_silver_lion_damage(3, DamageType.THUNDER, source=None) == 1
    assert apply_silver_lion_to_hp_loss(3) == 3


def test_silver_lion_leaves_zero_and_one_damage_unchanged() -> None:
    assert apply_silver_lion_damage(0, DamageType.UNATTRIBUTED) == 0
    assert apply_silver_lion_damage(1, DamageType.FIRE) == 1


@pytest.mark.parametrize(("damage_amount", "expected"), [(0, 0), (1, 1)])
def test_silver_lion_does_not_increase_damage_below_two(
    damage_amount: int,
    expected: int,
) -> None:
    assert (
        apply_silver_lion_damage(
            damage_amount,
            DamageType.UNATTRIBUTED,
        )
        == expected
    )


@pytest.mark.parametrize(
    "reason",
    ["被弃置", "被获得", "被替换", "移动到判定区", "技能令其离开"],
)
def test_silver_lion_recovers_when_leaving_equipment_by_any_method(
    reason: str,
) -> None:
    result = resolve_silver_lion_leaving(2, 4, reason)

    assert result.recovered_amount == 1
    assert result.hp_after == 3


def test_silver_lion_recovery_does_not_exceed_maximum_hp() -> None:
    result = resolve_silver_lion_leaving(4, 4, "被替换")

    assert result.recovered_amount == 0
    assert result.hp_after == 4


@pytest.mark.parametrize("card_name", ["南蛮入侵", "万箭齐发"])
def test_aoe_defaults_to_unattributed_damage_from_user(card_name: str) -> None:
    result = resolve_card_damage_defaults(card_name, "使用者甲")

    assert result.damage_type is DamageType.UNATTRIBUTED
    assert result.source == "使用者甲"


def test_lightning_remains_the_sourceless_damage_exception() -> None:
    result = resolve_card_damage_defaults("闪电", "使用者甲")

    assert result.damage_type is DamageType.THUNDER
    assert result.source is None


def test_generated_special_card_uses_same_unspecified_defaults() -> None:
    result = resolve_card_damage_defaults("技能生成的特殊卡牌", "技能使用者")

    assert result.damage_type is DamageType.UNATTRIBUTED
    assert result.source == "技能使用者"


def test_explicit_card_damage_source_overrides_the_default() -> None:
    redirected = resolve_card_damage_defaults(
        "特殊卡牌",
        "使用者甲",
        stated_source="来源乙",
    )
    sourceless = resolve_card_damage_defaults(
        "特殊卡牌",
        "使用者甲",
        stated_source=None,
    )

    assert redirected.source == "来源乙"
    assert sourceless.source is None
