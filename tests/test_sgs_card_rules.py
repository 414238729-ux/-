import pytest

from scripts.sgs_card_rules import (
    CardSelectionWording,
    CardZone,
    ChainParticipant,
    DamageEvent,
    DamageType,
    DelayedTrick,
    DelayedTrickDestination,
    DelayedTrickMoment,
    RecipientDamageOutcome,
    can_nullify_trick_effect,
    can_pay_stone_axe_cost,
    is_delayed_trick_nullification_window,
    resolve_chain_damage,
    resolve_delayed_trick,
    resolve_multi_target_trick,
    resolve_nullification_chain,
    selectable_card_zones,
    transform_zhangba_spear,
)


def _participants(*, chained=(1, 2, 3, 4)) -> tuple[ChainParticipant, ...]:
    return tuple(
        ChainParticipant(f"P{seat}", seat, chained=seat in chained)
        for seat in range(1, 5)
    )


def _targets(result) -> list[str]:
    return [step.target for step in result.steps]


def _final_by_id(result):
    return {
        participant.character_id: participant
        for participant in result.final_participants
    }


def test_card_wording_uses_hand_and_equipment_but_not_judgment() -> None:
    assert selectable_card_zones("牌") == {
        CardZone.HAND,
        CardZone.EQUIPMENT,
    }
    assert selectable_card_zones(CardSelectionWording.CARDS_IN_ZONES) == {
        CardZone.HAND,
        CardZone.EQUIPMENT,
        CardZone.JUDGMENT,
    }


@pytest.mark.parametrize(
    "zones",
    [
        (CardZone.HAND, CardZone.HAND),
        (CardZone.EQUIPMENT, CardZone.EQUIPMENT),
        (CardZone.HAND, CardZone.EQUIPMENT),
    ],
)
def test_stone_axe_accepts_two_cards_from_hand_or_equipment(zones) -> None:
    assert can_pay_stone_axe_cost(zones)


def test_stone_axe_rejects_judgment_cards_and_wrong_count() -> None:
    assert not can_pay_stone_axe_cost((CardZone.HAND, CardZone.JUDGMENT))
    assert not can_pay_stone_axe_cost((CardZone.HAND,))


def test_nullification_is_not_limited_to_harmful_or_damage_tricks() -> None:
    assert can_nullify_trick_effect(
        is_trick=True,
        effect_targets_character=True,
        deals_damage=False,
        is_harmful=False,
    )
    assert not can_nullify_trick_effect(
        is_trick=False,
        effect_targets_character=True,
        deals_damage=True,
        is_harmful=True,
    )


def test_multi_target_nullification_only_cancels_the_corresponding_target() -> None:
    result = resolve_multi_target_trick(
        ("甲", "乙", "丙"),
        {"乙": 1},
    )
    assert [item.effect_applies for item in result] == [True, False, True]


@pytest.mark.parametrize(
    ("response_count", "cancelled"),
    [(0, False), (1, True), (2, False), (101, True), (102, False)],
)
def test_nullification_can_counter_nullification_without_artificial_cap(
    response_count: int,
    cancelled: bool,
) -> None:
    result = resolve_nullification_chain(response_count)
    assert result.original_effect_cancelled is cancelled


def test_delayed_trick_nullification_window_is_before_judgment_only() -> None:
    assert not is_delayed_trick_nullification_window(
        DelayedTrickMoment.ENTERED_JUDGMENT_ZONE
    )
    assert is_delayed_trick_nullification_window(
        DelayedTrickMoment.BEFORE_JUDGMENT
    )


@pytest.mark.parametrize(
    ("suit", "effect_applied", "skipped_phase"),
    [("红桃", False, None), ("黑桃", True, "出牌阶段")],
)
def test_indulgence_always_goes_to_discard_pile_after_judgment(
    suit: str,
    effect_applied: bool,
    skipped_phase: str | None,
) -> None:
    result = resolve_delayed_trick(
        DelayedTrick.INDULGENCE,
        nullified=False,
        judgment_suit=suit,
    )
    assert result.judgment_performed
    assert result.effect_applied is effect_applied
    assert result.skipped_phase == skipped_phase
    assert result.destination is DelayedTrickDestination.DISCARD_PILE
    assert result.movement_wording == "置入弃牌堆"
    assert not result.discard_action_performed


def test_nullified_indulgence_skips_judgment_and_goes_to_discard_pile() -> None:
    result = resolve_delayed_trick("乐不思蜀", nullified=True)
    assert not result.judgment_performed
    assert not result.effect_applied
    assert result.destination is DelayedTrickDestination.DISCARD_PILE
    assert not result.discard_action_performed


@pytest.mark.parametrize(
    ("suit", "effect_applied", "skipped_phase"),
    [("梅花", False, None), ("方块", True, "摸牌阶段")],
)
def test_supply_shortage_always_goes_to_discard_pile_after_judgment(
    suit: str,
    effect_applied: bool,
    skipped_phase: str | None,
) -> None:
    result = resolve_delayed_trick(
        "兵粮寸断",
        nullified=False,
        judgment_suit=suit,
    )
    assert result.judgment_performed
    assert result.effect_applied is effect_applied
    assert result.skipped_phase == skipped_phase
    assert result.destination is DelayedTrickDestination.DISCARD_PILE
    assert not result.discard_action_performed


def test_nullified_supply_shortage_skips_judgment_and_goes_to_discard() -> None:
    result = resolve_delayed_trick("兵粮寸断", nullified=True)
    assert not result.judgment_performed
    assert result.destination is DelayedTrickDestination.DISCARD_PILE
    assert result.movement_wording == "置入弃牌堆"


def test_lightning_hit_deals_three_thunder_and_goes_to_discard_pile() -> None:
    result = resolve_delayed_trick(
        "闪电",
        nullified=False,
        judgment_suit="黑桃",
        judgment_rank=7,
        current_seat=4,
        player_count=4,
    )
    assert result.judgment_performed
    assert result.effect_applied
    assert result.damage_amount == 3
    assert result.damage_type == "雷属性"
    assert result.destination is DelayedTrickDestination.DISCARD_PILE
    assert result.next_seat is None
    assert result.resolution_steps == (
        "进行判定",
        "造成3点雷属性伤害",
        "完整结算伤害及其引发的技能、濒死和死亡",
        "置入弃牌堆",
    )


def test_lightning_miss_transfers_to_current_next_seat() -> None:
    result = resolve_delayed_trick(
        "闪电",
        nullified=False,
        judgment_suit="黑桃",
        judgment_rank=10,
        current_seat=4,
        player_count=4,
    )
    assert result.judgment_performed
    assert result.damage_amount == 0
    assert result.destination is DelayedTrickDestination.NEXT_PLAYER_JUDGMENT_ZONE
    assert result.next_seat == 1
    assert result.movement_wording == "移至下家判定区"


def test_nullified_lightning_does_not_judge_or_damage_and_transfers() -> None:
    result = resolve_delayed_trick(
        "闪电",
        nullified=True,
        current_seat=2,
        player_count=3,
    )
    assert not result.judgment_performed
    assert result.damage_amount == 0
    assert result.destination is DelayedTrickDestination.NEXT_PLAYER_JUDGMENT_ZONE
    assert result.next_seat == 3
    assert not result.discard_action_performed
    assert "进行判定" not in result.resolution_steps
    assert result.resolution_steps[-1] == "移至下家判定区"


@pytest.mark.parametrize("nullified", [False, True])
def test_lightning_transfer_skips_dead_seats(nullified: bool) -> None:
    result = resolve_delayed_trick(
        "闪电",
        nullified=nullified,
        judgment_suit=None if nullified else "红桃",
        judgment_rank=None if nullified else 1,
        current_seat=2,
        player_count=5,
        living_seats=(1, 2, 4, 5),
    )

    assert result.next_seat == 4
    assert result.destination is DelayedTrickDestination.NEXT_PLAYER_JUDGMENT_ZONE


def test_unattributed_damage_does_not_trigger_chain_or_unchain() -> None:
    result = resolve_chain_damage(
        _participants(),
        DamageEvent("P1", 1, DamageType.UNATTRIBUTED, "来源"),
        player_count=4,
        current_turn_seat=2,
    )
    assert _targets(result) == ["P1"]
    assert result.rounds_started == 0
    assert _final_by_id(result)["P1"].chained


def test_zero_elemental_damage_does_not_trigger_chain_or_unchain() -> None:
    result = resolve_chain_damage(
        _participants(),
        DamageEvent("P1", 0, DamageType.FIRE, "来源"),
        player_count=4,
        current_turn_seat=2,
    )
    assert _targets(result) == ["P1"]
    assert result.steps[0].prevented
    assert _final_by_id(result)["P1"].chained


def test_chain_order_uses_current_turn_seat_anchor_and_excludes_origin() -> None:
    result = resolve_chain_damage(
        _participants(),
        DamageEvent("P1", 2, DamageType.FIRE, "甲"),
        player_count=4,
        current_turn_seat=3,
    )
    assert _targets(result) == ["P1", "P3", "P4", "P2"]
    assert _targets(result).count("P1") == 1
    assert all(not item.chained for item in result.final_participants)


def test_chain_searches_in_increasing_order_if_anchor_is_not_chained() -> None:
    result = resolve_chain_damage(
        _participants(chained=(1, 3, 4)),
        DamageEvent("P1", 1, DamageType.THUNDER),
        player_count=4,
        current_turn_seat=2,
    )
    assert _targets(result) == ["P1", "P3", "P4"]


def test_chain_rechecks_chained_state_before_each_recipient() -> None:
    def after_damage(step, state):
        if step.target == "P2":
            state.set_chained("P3", False)
        return None

    result = resolve_chain_damage(
        _participants(),
        DamageEvent("P1", 1, DamageType.FIRE),
        player_count=4,
        current_turn_seat=2,
        after_damage=after_damage,
    )
    assert _targets(result) == ["P1", "P2", "P4"]


def test_chain_inherits_source_and_continues_after_recipient_death() -> None:
    def resolver(target, base, damage_type, source, state):
        return RecipientDamageOutcome(base, died=target == "P2")

    result = resolve_chain_damage(
        _participants(),
        DamageEvent("P1", 2, DamageType.THUNDER, "伤害来源甲"),
        player_count=4,
        current_turn_seat=2,
        recipient_resolver=resolver,
    )
    assert _targets(result) == ["P1", "P2", "P3", "P4"]
    assert all(step.source == "伤害来源甲" for step in result.steps)
    assert not _final_by_id(result)["P2"].alive


def test_chain_stops_only_when_callback_confirms_game_over() -> None:
    def after_damage(step, state):
        if step.target == "P2":
            state.end_game()
        return None

    result = resolve_chain_damage(
        _participants(),
        DamageEvent("P1", 2, DamageType.THUNDER),
        player_count=4,
        current_turn_seat=2,
        after_damage=after_damage,
    )
    assert _targets(result) == ["P1", "P2"]
    assert result.game_over


def test_zero_damage_in_middle_keeps_recipient_chained_and_stops_round() -> None:
    def resolver(target, base, damage_type, source, state):
        return RecipientDamageOutcome(0 if target == "P3" else base)

    result = resolve_chain_damage(
        _participants(),
        DamageEvent("P1", 2, DamageType.FIRE),
        player_count=4,
        current_turn_seat=2,
        recipient_resolver=resolver,
    )
    assert _targets(result) == ["P1", "P2", "P3"]
    assert result.rounds_terminated_by_zero == 1
    final = _final_by_id(result)
    assert final["P3"].chained
    assert final["P4"].chained


def test_local_damage_change_does_not_change_later_chain_base() -> None:
    observed_bases: list[tuple[str, int]] = []

    def resolver(target, base, damage_type, source, state):
        observed_bases.append((target, base))
        return RecipientDamageOutcome(3 if target == "P2" else base)

    result = resolve_chain_damage(
        _participants(chained=(1, 2, 3)),
        DamageEvent("P1", 2, DamageType.FIRE),
        player_count=4,
        current_turn_seat=2,
        recipient_resolver=resolver,
    )
    assert observed_bases == [("P2", 2), ("P3", 2)]
    assert [step.actual_damage for step in result.steps] == [2, 3, 2]


def test_explicit_later_chain_modifier_changes_subsequent_base() -> None:
    observed_bases: list[tuple[str, int]] = []

    def resolver(target, base, damage_type, source, state):
        observed_bases.append((target, base))
        if target == "P2":
            return RecipientDamageOutcome(
                actual_damage=3,
                subsequent_chain_base_damage=3,
            )
        return RecipientDamageOutcome(actual_damage=base)

    result = resolve_chain_damage(
        _participants(chained=(1, 2, 3)),
        DamageEvent("P1", 2, DamageType.FIRE),
        player_count=4,
        current_turn_seat=2,
        recipient_resolver=resolver,
    )
    assert observed_bases == [("P2", 2), ("P3", 3)]
    assert result.steps[1].chain_base_damage_after == 3


def test_spawned_elemental_damage_finishes_independent_chain_before_return() -> None:
    def resolver(target, base, damage_type, source, state):
        if target == "P2":
            return RecipientDamageOutcome(
                actual_damage=base,
                spawned_events=(
                    DamageEvent("P4", 1, DamageType.THUNDER, "新来源"),
                ),
            )
        return RecipientDamageOutcome(actual_damage=base)

    result = resolve_chain_damage(
        _participants(),
        DamageEvent("P1", 2, DamageType.FIRE, "原来源"),
        player_count=4,
        current_turn_seat=2,
        recipient_resolver=resolver,
    )
    assert _targets(result) == ["P1", "P2", "P4", "P3"]
    assert result.rounds_started == 2
    assert [step.source for step in result.steps] == [
        "原来源",
        "原来源",
        "新来源",
        "新来源",
    ]
    assert result.steps[2].nested_depth == 1


@pytest.mark.parametrize(
    ("first", "second", "expected"),
    [
        ("红色", "红色", "红色"),
        ("黑色", "黑色", "黑色"),
        ("红色", "黑色", "无色"),
    ],
)
def test_zhangba_spear_color_and_rank_are_independent(
    first: str,
    second: str,
    expected: str,
) -> None:
    slash = transform_zhangba_spear(
        first,
        second,
        first_rank=13,
        second_rank=1,
    )
    assert slash.card_name == "杀"
    assert slash.color == expected
    assert slash.rank is None
    assert slash.suit is None
    assert slash.suit_status == "当前确认"
    assert slash.damage_type is DamageType.UNATTRIBUTED


def test_zhangba_spear_never_derives_sum_max_or_min_rank() -> None:
    for first_rank, second_rank in ((2, 9), (5, 5), (13, 1)):
        slash = transform_zhangba_spear(
            "红色",
            "红色",
            first_rank=first_rank,
            second_rank=second_rank,
        )
        assert slash.rank is None


def test_chain_damage_can_recheck_source_before_each_pending_recipient() -> None:
    bird_alive = {"value": True}

    def source_resolver(target, _original_source, _state):
        assert target in {"P2", "P3", "P4"}
        return "雀" if bird_alive["value"] else "郭女王"

    def after_damage(step, _state):
        if step.target == "P2":
            bird_alive["value"] = False
        return ()

    result = resolve_chain_damage(
        _participants(),
        DamageEvent("P1", 1, DamageType.FIRE, "雀"),
        player_count=4,
        current_turn_seat=1,
        damage_source_resolver=source_resolver,
        after_damage=after_damage,
    )

    transmitted = [step for step in result.steps if step.role == "传导伤害"]
    assert [step.source for step in transmitted] == ["雀", "郭女王", "郭女王"]


def test_invalid_inputs_use_clear_chinese_messages() -> None:
    with pytest.raises(ValueError, match="牌区只能为"):
        can_pay_stone_axe_cost(("手牌区", "未知区域"))
    with pytest.raises(ValueError, match="判定花色"):
        resolve_delayed_trick("乐不思蜀", nullified=False)
    with pytest.raises(ValueError, match="不存在角色"):
        resolve_chain_damage(
            _participants(),
            DamageEvent("未知角色", 1, DamageType.FIRE),
            player_count=4,
            current_turn_seat=1,
        )
