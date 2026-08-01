from __future__ import annotations

import pytest

from scripts import (
    LIMITED_MODE_VARIANT,
    LANDLORD_MULLIGAN_LIMIT,
    RoundTracker,
    SGS_PRIMARY_PLATFORM,
    apply_landlord_health_bonus,
    begin_turn,
    candidate_selection_simulation_scope,
    initial_heir_selection_state,
    landlord_mulligan_limit,
    limited_mode_is_available,
    limited_mode_metadata,
    resolve_disconnected_general_selection,
    select_heir_in_turn,
    two_v_two_first_round_flying_allowance,
)


def _start_normal_turns(tracker: RoundTracker, count: int) -> RoundTracker:
    for _ in range(count):
        tracker = begin_turn(tracker, is_extra_turn=False).tracker_after_start
    return tracker


def test_primary_platform_and_limited_mode_date_are_explicit() -> None:
    metadata = limited_mode_metadata()
    assert SGS_PRIMARY_PLATFORM == "三国杀移动版"
    assert metadata.platform == SGS_PRIMARY_PLATFORM
    assert metadata.first_known_promotion_or_open_date == "2026-05-16"
    assert metadata.rules_version is None
    assert limited_mode_is_available(game_version=None)


def test_landlord_uses_eight_current_mulligans() -> None:
    assert LANDLORD_MULLIGAN_LIMIT == 8
    assert landlord_mulligan_limit() == 8


@pytest.mark.parametrize(
    ("base_maximum_hp", "base_initial_hp", "expected"),
    ((3, 3, (4, 4)), (4, 4, (5, 5))),
)
def test_landlord_bonus_is_pre_game_base_state(
    base_maximum_hp: int,
    base_initial_hp: int,
    expected: tuple[int, int],
) -> None:
    health = apply_landlord_health_bonus(base_maximum_hp, base_initial_hp)
    assert (health.maximum_hp, health.initial_hp) == expected
    assert health.applied_before_game_start
    assert not health.counts_as_recovery
    assert not health.emits_in_game_hp_change_event
    assert not health.emits_in_game_maximum_hp_change_event


def test_first_round_extra_turn_preserves_round_and_normal_cycle() -> None:
    tracker = _start_normal_turns(RoundTracker(player_count=4), 4)
    assert (tracker.round_number, tracker.normal_turn_cycle) == (1, 4)

    extra = begin_turn(tracker, is_extra_turn=True)
    assert extra.is_extra_turn
    assert (extra.round_number, extra.normal_turn_cycle) == (1, 4)
    assert extra.tracker_after_start == tracker

    second_round = begin_turn(extra.tracker_after_start, is_extra_turn=False)
    assert not second_round.is_extra_turn
    assert (second_round.round_number, second_round.normal_turn_cycle) == (2, 1)


def test_eight_player_extra_turn_does_not_close_first_round_by_event_count() -> None:
    tracker = _start_normal_turns(RoundTracker(player_count=8), 8)
    extra = begin_turn(tracker, is_extra_turn=True)
    assert (extra.round_number, extra.normal_turn_cycle) == (1, 8)

    next_normal = begin_turn(extra.tracker_after_start, is_extra_turn=False)
    assert (next_normal.round_number, next_normal.normal_turn_cycle) == (2, 1)


def test_fourth_seat_gets_independent_flying_allowance_in_each_first_round_turn() -> None:
    tracker = RoundTracker(player_count=4)
    normal = begin_turn(tracker, is_extra_turn=False)
    extra = begin_turn(normal.tracker_after_start, is_extra_turn=True)

    assert two_v_two_first_round_flying_allowance(4, normal) == 1
    assert two_v_two_first_round_flying_allowance(4, extra) == 1
    assert normal != extra
    assert two_v_two_first_round_flying_allowance(1, extra) == 0


def test_fourth_seat_has_no_first_round_flying_in_second_round() -> None:
    tracker = _start_normal_turns(RoundTracker(player_count=4), 4)
    second_round = begin_turn(tracker, is_extra_turn=False)
    assert two_v_two_first_round_flying_allowance(4, second_round) == 0


def test_heir_can_be_selected_in_first_round_extra_turn_but_not_second_round() -> None:
    state = initial_heir_selection_state(LIMITED_MODE_VARIANT, lord_player_id=1)
    tracker = _start_normal_turns(RoundTracker(player_count=8), 8)
    extra = begin_turn(tracker, is_extra_turn=True)

    selected = select_heir_in_turn(
        state,
        2,
        alive_players=range(1, 9),
        turn=extra,
    )
    assert selected.heir_player_id == 2

    second_round = begin_turn(extra.tracker_after_start, is_extra_turn=False)
    fresh_state = initial_heir_selection_state(LIMITED_MODE_VARIANT, lord_player_id=1)
    with pytest.raises(ValueError, match="第一轮已经结束"):
        select_heir_in_turn(
            fresh_state,
            2,
            alive_players=range(1, 9),
            turn=second_round,
        )


def test_disconnect_uses_clicked_candidate_or_first_candidate() -> None:
    clicked = resolve_disconnected_general_selection(
        ("甲", "乙", "丙"),
        clicked_general="乙",
    )
    assert clicked.selected_general == "乙"
    assert clicked.used_clicked_candidate
    assert not clicked.used_first_candidate_fallback

    fallback = resolve_disconnected_general_selection(("甲", "乙", "丙"))
    assert fallback.selected_general == "甲"
    assert not fallback.used_clicked_candidate
    assert fallback.used_first_candidate_fallback


def test_fixed_lineup_does_not_load_random_or_disconnect_selection() -> None:
    scope = candidate_selection_simulation_scope(
        fixed_lineup=True,
        include_random_candidate_generation=True,
        include_disconnect_auto_selection=True,
    )
    assert scope.fixed_lineup
    assert not scope.random_candidate_generation_loaded
    assert not scope.disconnect_auto_selection_loaded
