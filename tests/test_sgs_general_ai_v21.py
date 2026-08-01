from __future__ import annotations

import math

import pytest
import scripts

from scripts.sgs_general_ai_v21 import (
    JinfanCardOption,
    LingrenOpportunity,
    ShequeFactors,
    WeaponSwapStep,
    ZhangbaMaterialOption,
    choose_shamoke_weapon_chain,
    choose_zhangba_materials,
    optimize_dianhua_order,
    optimize_jinfan_storage,
    sheque_net_value,
    should_use_lingren_now,
)


def test_dianhua_enumerates_all_twenty_four_orders_for_four_cards() -> None:
    wanted = ("d", "c", "b", "a")
    result = optimize_dianhua_order(
        ("a", "b", "c", "d"),
        lambda order: 10.0 if order == wanted else 0.0,
    )

    assert result.ordered_card_ids == wanted
    assert result.evaluated_permutations == math.factorial(4)


def test_dianhua_rejects_more_than_four_or_duplicate_entities() -> None:
    with pytest.raises(ValueError, match="最多处理四张"):
        optimize_dianhua_order(("1", "2", "3", "4", "5"), lambda _: 0)
    with pytest.raises(ValueError, match="不能重复"):
        optimize_dianhua_order(("same", "same"), lambda _: 0)


def test_jinfan_jointly_selects_suits_and_best_card_within_each_suit() -> None:
    choice = optimize_jinfan_storage(
        (
            JinfanCardOption("spade-high-cost", "♠", "桃", preserve_value=5, slot_value=1),
            JinfanCardOption("spade-good", "♠", "杀", preserve_value=1, sheque_value=3),
            JinfanCardOption("heart-bad", "♥", "闪", preserve_value=3, slot_value=1),
            JinfanCardOption("club-good", "♣", "装备", clearing_value=2),
        )
    )

    assert {card.card_id for card in choice.selected_cards} == {"spade-good", "club-good"}
    assert len({card.suit for card in choice.selected_cards}) == len(choice.selected_cards)
    assert choice.evaluated_combinations > 1


def test_jinfan_can_leave_negative_value_suit_empty() -> None:
    choice = optimize_jinfan_storage(
        (JinfanCardOption("peach", "♥", "桃", preserve_value=10),)
    )
    assert choice.selected_cards == ()
    assert choice.score == 0


def test_sheque_accounts_for_kill_on_damage_gouchen_and_identity_exposure() -> None:
    profitable = sheque_net_value(
        ShequeFactors(kill_value=8, slash_resource_cost=1, identity_exposure_cost=1)
    )
    harmful = sheque_net_value(
        ShequeFactors(
            kill_value=1,
            target_on_damage_benefit=2,
            zhangqiying_gouchen_cost=2,
            identity_exposure_cost=1,
        )
    )
    assert profitable > 0
    assert harmful < 0


def test_zhangba_materials_use_exactly_two_and_preserve_defense() -> None:
    chosen = choose_zhangba_materials(
        (
            ZhangbaMaterialOption("桃", preserve_value=5, defense_value=3),
            ZhangbaMaterialOption("低值铃", slot_clearing_value=2),
            ZhangbaMaterialOption("可替换铃", bell_replacement_value=2),
        )
    )
    assert {item.card_id for item in chosen} == {"低值铃", "可替换铃"}


def test_lingren_can_save_phase_only_opportunity_for_better_information() -> None:
    current = LingrenOpportunity("当前低信息目标", expected_value=1, known_hand_fraction=0)
    later = LingrenOpportunity("后续完整信息目标", expected_value=1, known_hand_fraction=1)
    assert not should_use_lingren_now(current, (later,))
    assert should_use_lingren_now(later, (), play_phase_ending=True)


def test_shamoke_weapon_chain_is_not_unconditionally_full_ladder() -> None:
    steps = (
        WeaponSwapStep("范围1", draw_gain=2, replacement_loss=0.5),
        WeaponSwapStep("范围2", draw_gain=1, replacement_loss=0.5),
        WeaponSwapStep("高价值范围3", draw_gain=1, retained_weapon_value=3, replacement_loss=8),
        WeaponSwapStep("范围4", draw_gain=1, replacement_loss=1),
    )
    chosen = choose_shamoke_weapon_chain(steps)
    assert tuple(step.weapon_name for step in chosen) == ("范围1", "范围2")


def test_ai_v21_numeric_inputs_must_be_finite() -> None:
    with pytest.raises(ValueError, match="有限数值"):
        JinfanCardOption("x", "♠", "杀", preserve_value=float("nan"))


def test_public_package_exports_ai_v21_interfaces() -> None:
    names = (
        "optimize_dianhua_order",
        "optimize_jinfan_storage",
        "sheque_net_value",
        "choose_zhangba_materials",
        "should_use_lingren_now",
        "choose_shamoke_weapon_chain",
    )
    assert all(name in scripts.__all__ for name in names)
    assert all(hasattr(scripts, name) for name in names)
