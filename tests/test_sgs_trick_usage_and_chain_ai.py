from __future__ import annotations

import csv
from pathlib import Path

import pytest

from scripts import (
    ChainParticipant,
    ChainStrategyKind,
    DamageEvent,
    DamageType,
    TrickTimingCode,
    assess_chain_propagation,
    can_use_trick_at_timing,
    estimate_cooperative_fire_attack_success,
    evaluate_chain_strategy,
    resolve_structured_trick_usage,
    resolve_chain_damage,
    select_best_chain_strategy,
)


CARD_DATA_PATH = (
    Path(__file__).resolve().parents[1]
    / "knowledge"
    / "三国杀卡牌结构化数据.csv"
)


def _card_row(card_name: str) -> dict[str, str]:
    with CARD_DATA_PATH.open(encoding="utf-8", newline="") as handle:
        rows = csv.DictReader(handle)
        return next(row for row in rows if row["card_name"] == card_name)


def test_active_trick_inherits_play_phase_and_allows_multiple_legal_uses() -> None:
    rule = resolve_structured_trick_usage(_card_row("火攻"))

    assert rule.specific_timing is None
    assert rule.inherited_generic_timing == TrickTimingCode.PLAY_PHASE.value
    assert can_use_trick_at_timing(
        rule,
        TrickTimingCode.PLAY_PHASE,
        has_legal_target=True,
        has_card_or_conversion=True,
        prior_uses_in_play_phase=20,
    )
    assert not can_use_trick_at_timing(
        rule,
        "turn_outside",
        has_legal_target=True,
        has_card_or_conversion=True,
    )
    assert not can_use_trick_at_timing(
        rule,
        TrickTimingCode.PLAY_PHASE,
        has_legal_target=False,
        has_card_or_conversion=True,
    )


def test_nullification_is_response_only_and_cannot_be_used_without_window() -> None:
    rule = resolve_structured_trick_usage(_card_row("无懈可击"))

    assert rule.specific_timing == TrickTimingCode.RESPONSE_WINDOW.value
    assert rule.response_only
    assert not can_use_trick_at_timing(
        rule,
        TrickTimingCode.PLAY_PHASE,
        has_legal_target=True,
        has_card_or_conversion=True,
    )
    assert not can_use_trick_at_timing(
        rule,
        TrickTimingCode.RESPONSE_WINDOW,
        has_legal_target=True,
        has_card_or_conversion=True,
        response_window_open=False,
    )
    assert can_use_trick_at_timing(
        rule,
        TrickTimingCode.RESPONSE_WINDOW,
        has_legal_target=True,
        has_card_or_conversion=True,
        response_window_open=True,
        prior_uses_in_play_phase=99,
    )


def test_blank_specific_timing_must_inherit_and_skill_can_explicitly_override() -> None:
    row = _card_row("决斗")
    rule = resolve_structured_trick_usage(row, skill_override_timing="turn_outside")

    assert rule.skill_override_applied
    assert can_use_trick_at_timing(
        rule,
        "turn_outside",
        has_legal_target=True,
        has_card_or_conversion=True,
    )

    invalid = dict(row, specific_timing="", inherits_generic_timing="")
    with pytest.raises(ValueError, match="必须明确填写继承"):
        resolve_structured_trick_usage(invalid)


def test_chain_propagation_requires_actual_damage_and_current_chain_state() -> None:
    success = assess_chain_propagation(
        entry_actual_damage=1,
        entry_was_chained=True,
        target_still_chained=True,
        game_over_before_target=False,
    )
    prevented = assess_chain_propagation(
        entry_actual_damage=0,
        entry_was_chained=True,
        target_still_chained=True,
        game_over_before_target=False,
    )
    ended = assess_chain_propagation(
        entry_actual_damage=1,
        entry_was_chained=True,
        target_still_chained=True,
        game_over_before_target=True,
    )

    assert success.will_propagate and success.conditional_certainty
    assert "不再要求闪或重新火攻" in success.reason
    assert not prevented.will_propagate
    assert not ended.will_propagate


@pytest.mark.parametrize("entry_player", ["自己", "队友"])
def test_self_or_ally_fire_entry_propagates_to_chained_enemy(
    entry_player: str,
) -> None:
    participants = (
        ChainParticipant(entry_player, 1, True),
        ChainParticipant("敌方", 2, True),
    )
    result = resolve_chain_damage(
        participants,
        DamageEvent(entry_player, 1, DamageType.FIRE, "火攻使用者"),
        player_count=2,
        current_turn_seat=1,
    )

    assert [step.target for step in result.steps] == [entry_player, "敌方"]
    assert all(step.actual_damage == 1 for step in result.steps)


def test_fire_attack_probability_respects_distinct_cards_and_information() -> None:
    self_exact = estimate_cooperative_fire_attack_success(
        ["红桃", "红桃"],
        ["红桃", "红桃"],
        same_character=True,
        target_hand_fully_known=True,
    )
    self_insufficient = estimate_cooperative_fire_attack_success(
        ["红桃"],
        ["红桃"],
        same_character=True,
        target_hand_fully_known=True,
    )
    ally_known = estimate_cooperative_fire_attack_success(
        ["梅花"],
        ["梅花"],
        same_character=False,
        target_hand_fully_known=True,
    )
    ally_unknown = estimate_cooperative_fire_attack_success(
        ["梅花"],
        ["梅花"],
        same_character=False,
        target_hand_fully_known=False,
    )

    assert self_exact.probability == 1.0
    assert self_insufficient.probability == 0.0
    assert ally_known.probability == 1.0
    assert ally_unknown.probability is None
    assert not ally_unknown.exact


def test_damage_benefit_and_kill_value_raise_chain_strategy_score() -> None:
    base = evaluate_chain_strategy(
        ChainStrategyKind.SELF_IGNITION,
        enemy_expected_hp_loss=2,
        friendly_expected_hp_loss=1,
        friendly_death_risk=1,
    )
    with_damage_skill = evaluate_chain_strategy(
        ChainStrategyKind.SELF_IGNITION,
        enemy_expected_hp_loss=2,
        friendly_expected_hp_loss=1,
        friendly_death_risk=1,
        friendly_damage_skill_benefit=2,
    )
    with_key_kill = evaluate_chain_strategy(
        ChainStrategyKind.ALLY_IGNITION,
        enemy_expected_hp_loss=2,
        enemy_kill_value=5,
        friendly_expected_hp_loss=1,
    )

    assert with_damage_skill.score > base.score
    assert with_key_kill.score > with_damage_skill.score


def test_friendly_risk_and_multiple_friendly_hits_lower_strategy_score() -> None:
    safe = evaluate_chain_strategy(
        ChainStrategyKind.ALLY_IGNITION,
        enemy_expected_hp_loss=3,
        friendly_expected_hp_loss=1,
    )
    dying_without_rescue = evaluate_chain_strategy(
        ChainStrategyKind.ALLY_IGNITION,
        enemy_expected_hp_loss=3,
        friendly_expected_hp_loss=3,
        friendly_death_risk=5,
        rescue_resource_cost=3,
    )

    hold = evaluate_chain_strategy(ChainStrategyKind.HOLD_OR_RECAST)
    assert dying_without_rescue.score < safe.score
    assert select_best_chain_strategy([dying_without_rescue, hold]) is hold


def test_enemy_without_hand_can_make_direct_fire_illegal_but_ally_route_viable() -> None:
    direct = evaluate_chain_strategy(
        ChainStrategyKind.DIRECT_FIRE_ATTACK,
        legal=False,
        enemy_expected_hp_loss=99,
    )
    ally = evaluate_chain_strategy(
        ChainStrategyKind.ALLY_IGNITION,
        success_probability=0.8,
        enemy_expected_hp_loss=4,
        friendly_expected_hp_loss=1,
    )
    hold = evaluate_chain_strategy(ChainStrategyKind.HOLD_OR_RECAST)

    assert select_best_chain_strategy([direct, ally, hold]) is ally


@pytest.mark.parametrize(
    ("best_kind", "direct_score", "self_score", "ally_score"),
    [
        (ChainStrategyKind.DIRECT_FIRE_ATTACK, 6, 3, 2),
        (ChainStrategyKind.SELF_IGNITION, 2, 7, 3),
        (ChainStrategyKind.ALLY_IGNITION, 2, 3, 8),
    ],
)
def test_strategy_selector_chooses_highest_team_net_value(
    best_kind: ChainStrategyKind,
    direct_score: float,
    self_score: float,
    ally_score: float,
) -> None:
    candidates = [
        evaluate_chain_strategy(
            ChainStrategyKind.DIRECT_FIRE_ATTACK,
            enemy_expected_hp_loss=direct_score,
        ),
        evaluate_chain_strategy(
            ChainStrategyKind.SELF_IGNITION,
            enemy_expected_hp_loss=self_score,
        ),
        evaluate_chain_strategy(
            ChainStrategyKind.ALLY_IGNITION,
            enemy_expected_hp_loss=ally_score,
        ),
        evaluate_chain_strategy(ChainStrategyKind.HOLD_OR_RECAST),
    ]

    assert select_best_chain_strategy(candidates).strategy is best_kind


def test_negative_routes_hold_cards_and_selection_is_not_random() -> None:
    costly = [
        evaluate_chain_strategy(
            strategy,
            enemy_expected_hp_loss=1,
            card_resource_cost=2,
        )
        for strategy in (
            ChainStrategyKind.DIRECT_FIRE_ATTACK,
            ChainStrategyKind.SELF_IGNITION,
            ChainStrategyKind.ALLY_IGNITION,
        )
    ]
    hold = evaluate_chain_strategy(ChainStrategyKind.HOLD_OR_RECAST)

    assert select_best_chain_strategy([*costly, hold]) is hold
    first_tied = evaluate_chain_strategy(
        ChainStrategyKind.ENEMY_CHAIN,
        enemy_expected_hp_loss=2,
    )
    second_tied = evaluate_chain_strategy(
        ChainStrategyKind.ALLY_IGNITION,
        enemy_expected_hp_loss=2,
    )
    assert select_best_chain_strategy([first_tied, second_tied]) is first_tied


def test_hidden_identity_information_cannot_drive_ordinary_strategy() -> None:
    hidden_identity_candidate = evaluate_chain_strategy(
        ChainStrategyKind.ALLY_IGNITION,
        information_legal=False,
        enemy_expected_hp_loss=99,
    )
    legal_hold = evaluate_chain_strategy(ChainStrategyKind.HOLD_OR_RECAST)

    assert select_best_chain_strategy(
        [hidden_identity_candidate, legal_hold]
    ) is legal_hold
    with pytest.raises(ValueError, match="必须明确披露"):
        evaluate_chain_strategy(
            ChainStrategyKind.ALLY_IGNITION,
            uses_omniscient_information=True,
            omniscient_assumption_disclosed=False,
        )
