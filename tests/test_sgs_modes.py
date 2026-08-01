import pytest

from scripts import (
    DEFAULT_DRAW_COUNT,
    OMNISCIENT_UPPER_BOUND_MARKER,
    STANDARD_TURN_PHASES,
    FarmerRewardChoice,
    HandVisibility,
    TwoVsTwoTable,
    apply_landlord_health_bonus,
    default_hand_limit,
    eligible_replacement_generals,
    increasing_circular_seat_order,
    landlord_hand_information,
    replace_general_candidate,
    reroll_landlord_starting_hand,
    reroll_starting_hand,
    reroll_two_v_two_starting_hand,
    resolve_dying_rescue,
    resolve_farmer_death_reward,
    resolve_judgment_retrials,
    resolve_landlord_bidding,
    resolve_ordered_responses,
    standard_turn_defaults,
    two_v_two_base_distance,
    two_v_two_death_reward,
    two_v_two_hand_information,
    two_v_two_starting_hand_size,
    two_v_two_teammate,
)


def test_two_v_two_teammates_share_hands_but_enemies_do_not() -> None:
    teammate = two_v_two_hand_information(1, 4)
    enemy = two_v_two_hand_information(1, 2)

    assert teammate.actual_visibility is HandVisibility.VISIBLE
    assert teammate.analysis_visibility is HandVisibility.VISIBLE
    assert not teammate.omniscient_upper_bound
    assert enemy.actual_visibility is HandVisibility.HIDDEN
    assert enemy.analysis_visibility is HandVisibility.HIDDEN


def test_two_v_two_hand_visibility_uses_fixed_team_after_swap() -> None:
    table = TwoVsTwoTable().swap_seats(1, 2)
    assert table.action_order == (2, 1, 3, 4)

    assert (
        two_v_two_hand_information(1, 4).actual_visibility
        is HandVisibility.VISIBLE
    )
    assert (
        two_v_two_hand_information(1, 2).actual_visibility
        is HandVisibility.HIDDEN
    )


def test_landlord_players_do_not_share_other_players_hands() -> None:
    assert (
        landlord_hand_information(1, 1).actual_visibility
        is HandVisibility.VISIBLE
    )
    assert (
        landlord_hand_information(1, 2).actual_visibility
        is HandVisibility.HIDDEN
    )
    assert (
        landlord_hand_information(2, 3).actual_visibility
        is HandVisibility.HIDDEN
    )


def test_omniscient_analysis_is_explicitly_marked_as_upper_bound() -> None:
    result = landlord_hand_information(2, 3, assume_omniscient=True)

    assert result.actual_visibility is HandVisibility.HIDDEN
    assert result.analysis_visibility is HandVisibility.VISIBLE
    assert result.omniscient_upper_bound
    assert result.assumption_marker == (
        "理论上限假设，不代表实际游戏信息条件"
    )
    assert result.assumption_marker == OMNISCIENT_UPPER_BOUND_MARKER


def test_visible_hand_information_does_not_need_an_omniscient_marker() -> None:
    result = two_v_two_hand_information(
        1,
        4,
        assume_omniscient=True,
    )

    assert result.analysis_visibility is HandVisibility.VISIBLE
    assert not result.omniscient_upper_bound
    assert result.assumption_marker is None


def test_landlord_health_bonus_increases_both_values_by_one() -> None:
    three_hp = apply_landlord_health_bonus(3, 3)
    four_hp = apply_landlord_health_bonus(4, 4)
    wounded_start = apply_landlord_health_bonus(4, 3)

    assert (three_hp.maximum_hp, three_hp.initial_hp) == (4, 4)
    assert (four_hp.maximum_hp, four_hp.initial_hp) == (5, 5)
    assert (wounded_start.maximum_hp, wounded_start.initial_hp) == (5, 4)


def test_landlord_health_rejects_impossible_base_values() -> None:
    with pytest.raises(ValueError, match="不能超过"):
        apply_landlord_health_bonus(3, 4)


@pytest.mark.parametrize(
    ("player_count", "start", "expected"),
    [
        (4, 1, (1, 2, 3, 4)),
        (4, 2, (2, 3, 4, 1)),
        (4, 3, (3, 4, 1, 2)),
        (4, 4, (4, 1, 2, 3)),
        (3, 1, (1, 2, 3)),
        (3, 2, (2, 3, 1)),
        (3, 3, (3, 1, 2)),
    ],
)
def test_increasing_circular_order_for_three_and_four_players(
    player_count: int,
    start: int,
    expected: tuple[int, ...],
) -> None:
    assert increasing_circular_seat_order(player_count, start) == expected


def test_circular_order_rejects_unmodeled_player_count() -> None:
    with pytest.raises(ValueError, match="只支持 3 人或 4 人"):
        increasing_circular_seat_order(5, 1)


@pytest.mark.parametrize(
    ("first_seat", "second_seat", "expected"),
    [
        (1, 2, 1),
        (2, 3, 1),
        (3, 4, 1),
        (4, 1, 1),
        (1, 3, 2),
        (2, 4, 2),
    ],
)
def test_two_v_two_base_distance_matches_confirmed_pairs(
    first_seat: int,
    second_seat: int,
    expected: int,
) -> None:
    assert two_v_two_base_distance(first_seat, second_seat) == expected


def test_two_v_two_base_distance_validates_seats() -> None:
    assert two_v_two_base_distance(2, 2) == 0

    with pytest.raises(ValueError, match="只能为 1 至 4"):
        two_v_two_base_distance(1, 5)


def test_two_v_two_distance_uses_current_seats_after_swap() -> None:
    initial = TwoVsTwoTable()
    swapped = initial.swap_seats(1, 2)

    assert initial.base_distance(1, 3) == 2
    assert swapped.seat_of(1) == 2
    assert swapped.base_distance(1, 3) == 1
    assert swapped.are_teammates(1, 4)


def test_processing_order_uses_current_seat_after_swap_without_reteaming() -> None:
    table = TwoVsTwoTable().swap_seats(1, 3)
    current_turn_seat = table.seat_of(1)
    seat_order = increasing_circular_seat_order(4, current_turn_seat)
    player_order = tuple(
        table.occupants_by_seat[seat - 1]
        for seat in seat_order
    )

    assert current_turn_seat == 3
    assert seat_order == (3, 4, 1, 2)
    assert player_order == (1, 4, 3, 2)
    assert table.are_teammates(1, 4)
    assert not table.are_teammates(1, 3)


def test_standard_turn_defaults_are_lightweight_and_explicit() -> None:
    defaults = standard_turn_defaults(current_hp=3)

    assert defaults.phases == (
        "准备阶段",
        "判定阶段",
        "摸牌阶段",
        "出牌阶段",
        "弃牌阶段",
        "结束阶段",
    )
    assert defaults.phases == STANDARD_TURN_PHASES
    assert defaults.draw_count == DEFAULT_DRAW_COUNT == 2
    assert defaults.hand_limit == default_hand_limit(3) == 3


def test_default_hand_limit_rejects_negative_hp() -> None:
    with pytest.raises(ValueError, match="当前体力必须大于或等于 0"):
        default_hand_limit(-1)


def test_first_bidder_becomes_landlord_when_others_pass() -> None:
    result = resolve_landlord_bidding((1, None, None))

    assert result.landlord_call_position == 1
    assert result.winning_multiplier == 1


@pytest.mark.parametrize(
    ("bids", "landlord", "multiplier"),
    [
        ((1, 2, None), 2, 2),
        ((1, None, 2), 3, 2),
        ((1, 3), 2, 3),
        ((1, 2, 3), 3, 3),
    ],
)
def test_valid_strictly_increasing_landlord_bids(
    bids: tuple[int | None, ...],
    landlord: int,
    multiplier: int,
) -> None:
    result = resolve_landlord_bidding(bids)

    assert result.landlord_call_position == landlord
    assert result.winning_multiplier == multiplier


@pytest.mark.parametrize(
    "bids",
    [(None, None, None), (2, None, None), (1.0, None, None)],
)
def test_first_landlord_bid_must_be_one(
    bids: tuple[int | None, ...],
) -> None:
    with pytest.raises(ValueError, match="第一名玩家必须叫 1 倍"):
        resolve_landlord_bidding(bids)


@pytest.mark.parametrize(
    "bids",
    [
        (1, 1, None),
        (1, 2, 2),
        (1, 2, 1),
    ],
)
def test_later_landlord_bid_must_strictly_raise_or_pass(
    bids: tuple[int | None, ...],
) -> None:
    with pytest.raises(ValueError, match="必须严格高于"):
        resolve_landlord_bidding(bids)


def test_landlord_bid_cannot_exceed_three() -> None:
    with pytest.raises(ValueError, match="1 至 3 倍"):
        resolve_landlord_bidding((1, 4))


def test_incomplete_bidding_without_three_is_rejected() -> None:
    with pytest.raises(ValueError, match="三名玩家的完整叫价"):
        resolve_landlord_bidding((1, None))


def test_no_valid_bidding_can_have_all_pass_or_a_tied_highest() -> None:
    invalid_sequences = (
        (None, None, None),
        (1, 1, None),
        (1, 2, 2),
    )

    for bids in invalid_sequences:
        with pytest.raises(ValueError):
            resolve_landlord_bidding(bids)


def test_reroll_returns_current_hand_to_pool_before_drawing() -> None:
    assert reroll_starting_hand([], ["刚换掉的牌"], seed=0) == [
        "刚换掉的牌"
    ]


def test_reroll_does_not_permanently_exclude_old_hand() -> None:
    remaining = ["牌堆牌"]
    old_hand = ["旧手牌"]

    outcomes = {
        tuple(reroll_starting_hand(remaining, old_hand, seed=seed))
        for seed in range(20)
    }

    assert ("旧手牌",) in outcomes
    assert ("牌堆牌",) in outcomes
    assert remaining == ["牌堆牌"]
    assert old_hand == ["旧手牌"]


def test_two_v_two_reroll_sizes_are_position_specific() -> None:
    assert [
        two_v_two_starting_hand_size(position)
        for position in (1, 2, 3, 4)
    ] == [3, 4, 4, 5]

    for position, size in ((1, 3), (2, 4), (3, 4), (4, 5)):
        hand = [f"手牌{index}" for index in range(size)]
        drawn = reroll_two_v_two_starting_hand(
            ["牌堆牌"],
            hand,
            position,
            seed=7,
        )
        assert len(drawn) == size


def test_two_v_two_reroll_rejects_wrong_hand_size() -> None:
    with pytest.raises(ValueError, match="1 号位每次应重抽 3 张"):
        reroll_two_v_two_starting_hand([], ["甲", "乙"], 1, seed=0)


def test_landlord_reroll_always_draws_four() -> None:
    hand = ["甲", "乙", "丙", "丁"]
    assert len(reroll_landlord_starting_hand(["戊"], hand, seed=9)) == 4

    with pytest.raises(ValueError, match="应重抽 4 张"):
        reroll_landlord_starting_hand([], hand[:3], seed=9)


def test_starting_hand_rerolls_are_reproducible_with_fixed_seed() -> None:
    deck = list(range(20))
    hand = list(range(20, 24))

    assert reroll_landlord_starting_hand(
        deck, hand, seed=20260725
    ) == reroll_landlord_starting_hand(deck, hand, seed=20260725)


def test_initial_positions_define_fixed_teammates() -> None:
    assert two_v_two_teammate(1) == 4
    assert two_v_two_teammate(4) == 1
    assert two_v_two_teammate(2) == 3
    assert two_v_two_teammate(3) == 2


def test_swapping_seats_changes_order_but_not_teammates() -> None:
    initial = TwoVsTwoTable()
    swapped = initial.swap_seats(1, 2)

    assert initial.action_order == (1, 2, 3, 4)
    assert swapped.action_order == (2, 1, 3, 4)
    assert swapped.are_teammates(1, 4)
    assert swapped.are_teammates(2, 3)
    assert not swapped.are_teammates(1, 2)


def test_table_rejects_non_integer_player_identity() -> None:
    with pytest.raises(TypeError, match="初始位置必须是整数"):
        TwoVsTwoTable((1.0, 2, 3, 4))


def test_two_v_two_death_reward_uses_fixed_identity_after_swap() -> None:
    swapped = TwoVsTwoTable().swap_seats(1, 3)
    assert swapped.action_order == (3, 2, 1, 4)

    reward = two_v_two_death_reward(1, living_players=(2, 3, 4))

    assert reward is not None
    assert reward.recipient == 4
    assert reward.draw_count == 1
    assert reward.may_decline is False


def test_two_v_two_death_reward_is_absent_if_teammate_is_not_alive() -> None:
    assert two_v_two_death_reward(1, living_players=(2, 3)) is None


def test_dying_rescue_starts_at_current_turn_and_stops_at_one_hp() -> None:
    result = resolve_dying_rescue(
        0,
        {3: 0, 4: 1, 1: 5},
        player_count=4,
        current_turn_seat=3,
        dying_seat=1,
    )

    assert result.dying_seat == 1
    assert result.rescue_order == (3, 4, 1, 2)
    assert result.rescue_order[0] != result.dying_seat
    assert [step.seat for step in result.steps] == [3, 4]
    assert result.final_hp == 1
    assert result.rescued
    assert not result.death_confirmed
    assert result.stopped_at_seat == 4


def test_dying_rescue_passes_updated_hp_to_the_next_seat() -> None:
    result = resolve_dying_rescue(
        -1,
        {4: 1, 1: 1},
        player_count=4,
        current_turn_seat=4,
        dying_seat=2,
    )

    assert [(step.hp_before, step.hp_after) for step in result.steps] == [
        (-1, 0),
        (0, 1),
    ]
    assert result.stopped_at_seat == 1
    assert result.rescued


def test_death_is_confirmed_only_after_a_complete_failed_rescue_round() -> None:
    result = resolve_dying_rescue(
        -1,
        {2: 1},
        player_count=3,
        current_turn_seat=2,
        dying_seat=1,
    )

    assert result.rescue_order == (2, 3, 1)
    assert [step.seat for step in result.steps] == [2, 3, 1]
    assert result.final_hp == 0
    assert not result.rescued
    assert result.death_confirmed
    assert result.stopped_at_seat is None


def test_dying_rescue_skips_confirmed_dead_seats() -> None:
    result = resolve_dying_rescue(
        0,
        {4: 1},
        player_count=4,
        current_turn_seat=1,
        dying_seat=4,
        living_seats=(1, 2, 4),
    )

    assert result.rescue_order == (1, 2, 4)
    assert [step.seat for step in result.steps] == [1, 2, 4]
    assert result.rescued
    assert result.stopped_at_seat == 4


def test_non_dying_character_cannot_enter_rescue_sequence() -> None:
    with pytest.raises(ValueError, match="当前体力小于 1"):
        resolve_dying_rescue(
            1,
            {},
            player_count=4,
            current_turn_seat=1,
            dying_seat=2,
        )


def test_dying_rescue_rejects_negative_recovery_amount() -> None:
    with pytest.raises(ValueError, match="恢复量必须大于或等于 0"):
        resolve_dying_rescue(
            0,
            {1: -1},
            player_count=3,
            current_turn_seat=1,
            dying_seat=2,
        )


def test_death_rewards_do_not_resolve_before_death_confirmation() -> None:
    assert two_v_two_death_reward(
        1,
        living_players=(2, 3, 4),
        death_confirmed=False,
    ) is None
    assert resolve_farmer_death_reward(
        FarmerRewardChoice.DRAW_TWO,
        death_confirmed=False,
    ) is None


@pytest.mark.parametrize(
    ("choice", "recover", "draw"),
    [
        (FarmerRewardChoice.RECOVER_ONE, 1, 0),
        (FarmerRewardChoice.DRAW_TWO, 0, 2),
        (FarmerRewardChoice.DECLINE_BOTH, 0, 0),
    ],
)
def test_farmer_death_reward_has_exactly_three_legal_choices(
    choice: FarmerRewardChoice,
    recover: int,
    draw: int,
) -> None:
    result = resolve_farmer_death_reward(choice)

    assert result.recover_amount == recover
    assert result.draw_count == draw
    assert not (result.recover_amount and result.draw_count)


def test_farmer_cannot_recover_and_draw_at_the_same_time() -> None:
    with pytest.raises(ValueError, match="不能同时回血和摸牌"):
        resolve_farmer_death_reward("回血并摸牌")


def test_multi_response_state_is_passed_in_increasing_circular_order() -> None:
    seen: list[tuple[int, tuple[str, ...]]] = []

    def handler(seat: int):
        def update(state: tuple[str, ...]) -> tuple[str, ...]:
            seen.append((seat, state))
            return state + (f"{seat}号响应",)

        return update

    result = resolve_ordered_responses(
        ("初始",),
        {4: handler(4), 1: handler(1), 2: handler(2)},
        player_count=4,
        current_turn_seat=3,
    )

    assert result.processing_order == (3, 4, 1, 2)
    assert seen == [
        (4, ("初始",)),
        (1, ("初始", "4号响应")),
        (2, ("初始", "4号响应", "1号响应")),
    ]
    assert result.final_state == (
        "初始",
        "4号响应",
        "1号响应",
        "2号响应",
    )
    assert [step.handled for step in result.steps] == [
        False,
        True,
        True,
        True,
    ]


def test_ordered_responses_skip_confirmed_dead_seats() -> None:
    seen: list[int] = []

    def handler(seat: int):
        def update(state: tuple[int, ...]) -> tuple[int, ...]:
            seen.append(seat)
            return state + (seat,)

        return update

    result = resolve_ordered_responses(
        (),
        {1: handler(1), 3: handler(3)},
        player_count=4,
        current_turn_seat=1,
        living_seats=(1, 3, 4),
    )

    assert result.processing_order == (1, 3, 4)
    assert seen == [1, 3]
    assert result.final_state == (1, 3)


def test_judgment_retrial_reads_the_previous_latest_result() -> None:
    observed: dict[int, str] = {}

    def fourth_seat(previous: str) -> str:
        observed[4] = previous
        return "红桃判定"

    def first_seat(previous: str) -> str:
        observed[1] = previous
        return "梅花判定"

    result = resolve_judgment_retrials(
        "原始黑桃判定",
        {4: fourth_seat, 1: first_seat},
        player_count=4,
        current_turn_seat=3,
    )

    assert result.processing_order == (3, 4, 1, 2)
    assert observed == {4: "原始黑桃判定", 1: "红桃判定"}
    assert result.final_state == "梅花判定"


def test_judgment_retrial_skips_confirmed_dead_seats() -> None:
    observed: list[int] = []

    def handler(seat: int):
        def update(previous: str) -> str:
            observed.append(seat)
            return f"{previous}->{seat}号改判"

        return update

    result = resolve_judgment_retrials(
        "原始判定",
        {1: handler(1), 3: handler(3)},
        player_count=4,
        current_turn_seat=1,
        living_seats=(1, 3, 4),
    )

    assert result.processing_order == (1, 3, 4)
    assert observed == [1, 3]
    assert result.final_state == "原始判定->1号改判->3号改判"


def test_ordered_response_rejects_non_callable_handler() -> None:
    with pytest.raises(TypeError, match="处理函数必须可调用"):
        resolve_ordered_responses(
            "状态",
            {1: "不是函数"},  # type: ignore[dict-item]
            player_count=3,
            current_turn_seat=1,
        )


def test_replacement_excludes_generals_still_shown_elsewhere() -> None:
    eligible = eligible_replacement_generals(
        ["甲", "乙", "丙", "丁"],
        ["甲", "乙", "丙"],
        0,
    )

    assert eligible == ("丁",)
    assert "甲" not in eligible
    assert "乙" not in eligible
    assert "丙" not in eligible


def test_replaced_general_is_not_permanently_excluded() -> None:
    eligible_after_previous_replacement = eligible_replacement_generals(
        ["甲", "乙", "丙", "丁"],
        ["丁", "乙", "丙"],
        0,
    )

    assert "甲" in eligible_after_previous_replacement


def test_replacement_is_not_whole_pool_without_replacement() -> None:
    first = replace_general_candidate(
        ["甲", "乙", "丙", "丁"],
        ["甲", "乙", "丙"],
        0,
        seed=0,
    )
    second = replace_general_candidate(
        ["甲", "乙", "丙", "丁"],
        first.candidates,
        0,
        seed=0,
    )

    assert first.previous_general == "甲"
    assert first.new_general == "丁"
    assert first.candidates == ("丁", "乙", "丙")
    assert second.previous_general == "丁"
    assert second.new_general == "甲"
    assert second.candidates == ("甲", "乙", "丙")


def test_replacement_is_reproducible_with_fixed_seed() -> None:
    kwargs = {
        "unlocked_generals": ["甲", "乙", "丙", "丁", "戊"],
        "current_candidates": ["甲", "乙", "丙"],
        "slot_index": 1,
        "seed": 42,
    }

    assert replace_general_candidate(**kwargs) == replace_general_candidate(
        **kwargs
    )


def test_current_candidate_frames_cannot_contain_duplicates() -> None:
    with pytest.raises(ValueError, match="不能出现重复武将"):
        replace_general_candidate(
            ["甲", "乙", "丙"],
            ["甲", "甲", "丙"],
            0,
            seed=0,
        )
