from __future__ import annotations

from pathlib import Path

import pytest

from scripts import (
    assign_landlord_current_seats,
    build_landlord_bidding_order,
    choose_landlord_bidding_start,
    resolve_landlord_bidding_with_seats,
    symmetric_farmer_seat_marginal_assumption,
)


ROOT = Path(__file__).resolve().parents[1]
MODE = ROOT / "knowledge" / "三国杀模式规则.md"
SPEC = ROOT / "knowledge" / "三国杀模拟规范.md"
TERMS = ROOT / "knowledge" / "三国杀基础术语与通用机制.md"
INSTRUCTIONS = ROOT / "GPT_INSTRUCTIONS.md"


@pytest.mark.parametrize(
    ("landlord", "expected"),
    (
        ("A", ("A", "B", "C")),
        ("B", ("B", "C", "A")),
        ("C", ("C", "A", "B")),
    ),
)
def test_landlord_reanchors_current_seats_without_moving_players(
    landlord: str,
    expected: tuple[str, str, str],
) -> None:
    physical_order = ("A", "B", "C")
    assignment = assign_landlord_current_seats(physical_order, landlord)

    assert assignment.physical_seat_order == physical_order
    assert not assignment.physical_positions_changed
    assert assignment.players_by_current_seat == expected
    assert assignment.current_seat_number[landlord] == 1
    assert assignment.current_seat_number[expected[1]] == 2
    assert assignment.current_seat_number[expected[2]] == 3


def test_counterclockwise_next_is_seat_two_and_clockwise_next_is_seat_three() -> None:
    assignment = assign_landlord_current_seats(("A", "B", "C"), "B")
    assert assignment.players_by_current_seat[1] == "C"
    assert assignment.players_by_current_seat[2] == "A"
    assert assignment.players_by_current_seat == ("B", "C", "A")


def test_bidding_order_rotates_on_fixed_physical_ring() -> None:
    physical_order = ("A", "B", "C")
    assert build_landlord_bidding_order(physical_order, "A") == ("A", "B", "C")
    assert build_landlord_bidding_order(physical_order, "B") == ("B", "C", "A")
    assert build_landlord_bidding_order(physical_order, "C") == ("C", "A", "B")


def test_random_bidding_start_supports_fixed_seed() -> None:
    physical_order = ("A", "B", "C")
    first = choose_landlord_bidding_start(physical_order, seed=20260726)
    second = choose_landlord_bidding_start(physical_order, seed=20260726)
    assert first == second
    assert first in physical_order


@pytest.mark.parametrize(
    ("physical_order", "message"),
    (
        (("A", "B"), "恰好包含三名玩家"),
        (("A", "B", "A"), "三名玩家不能重复"),
    ),
)
def test_physical_ring_requires_exactly_three_unique_players(
    physical_order: tuple[str, ...],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        build_landlord_bidding_order(physical_order, "A")


def test_complete_bidding_process_preserves_physical_order_and_maps_landlord() -> None:
    resolution = resolve_landlord_bidding_with_seats(
        ("A", "B", "C"),
        "A",
        (1, 2, None),
    )
    assert resolution.physical_seat_order == ("A", "B", "C")
    assert resolution.bidding_order == ("A", "B", "C")
    assert resolution.landlord_player_id == "B"
    assert resolution.seat_assignment.players_by_current_seat == ("B", "C", "A")


def test_winning_multiplier_does_not_directly_change_seat_mapping() -> None:
    two_times = resolve_landlord_bidding_with_seats(
        ("A", "B", "C"), "A", (1, 2, None)
    )
    three_times = resolve_landlord_bidding_with_seats(
        ("A", "B", "C"), "A", (1, 3, None)
    )
    assert two_times.bid_result.winning_multiplier == 2
    assert three_times.bid_result.winning_multiplier == 3
    assert two_times.landlord_player_id == three_times.landlord_player_id == "B"
    assert (
        two_times.seat_assignment.players_by_current_seat
        == three_times.seat_assignment.players_by_current_seat
        == ("B", "C", "A")
    )


def test_same_physical_order_and_landlord_always_produce_same_seats() -> None:
    first = assign_landlord_current_seats(("A", "B", "C"), "C")
    second = assign_landlord_current_seats(("A", "B", "C"), "C")
    assert first.players_by_current_seat == second.players_by_current_seat
    assert dict(first.current_seat_number) == dict(second.current_seat_number)


def test_current_action_order_is_seat_one_then_two_then_three() -> None:
    assignment = assign_landlord_current_seats(("A", "B", "C"), "B")
    action_order = tuple(
        player
        for _, player in sorted(
            (seat, player) for player, seat in assignment.current_seat_number.items()
        )
    )
    assert action_order == assignment.players_by_current_seat == ("B", "C", "A")


def test_fifty_percent_marginal_is_only_an_explicit_symmetric_assumption() -> None:
    assumption = symmetric_farmer_seat_marginal_assumption(
        physical_seat_order_known=False,
        bidding_start_and_strategy_modeled=False,
        players_fully_symmetric=True,
    )
    assert assumption.seat_2_probability == 0.5
    assert assumption.seat_3_probability == 0.5
    assert assumption.report_label == "计算假设"
    assert assumption.description == "未显式模拟叫地主过程时的边际对称近似"
    assert not assumption.represents_actual_post_landlord_randomization


@pytest.mark.parametrize(
    "kwargs",
    (
        {
            "physical_seat_order_known": True,
            "bidding_start_and_strategy_modeled": False,
            "players_fully_symmetric": True,
        },
        {
            "physical_seat_order_known": False,
            "bidding_start_and_strategy_modeled": True,
            "players_fully_symmetric": True,
        },
        {
            "physical_seat_order_known": False,
            "bidding_start_and_strategy_modeled": False,
            "players_fully_symmetric": False,
        },
    ),
)
def test_fifty_percent_marginal_rejects_known_or_asymmetric_process(kwargs) -> None:
    with pytest.raises(ValueError):
        symmetric_farmer_seat_marginal_assumption(**kwargs)


def test_documents_remove_unknown_seating_and_keep_details_out_of_instructions() -> None:
    mode = MODE.read_text(encoding="utf-8")
    spec = SPEC.read_text(encoding="utf-8")
    terms = TERMS.read_text(encoding="utf-8")
    instructions = INSTRUCTIONS.read_text(encoding="utf-8")

    assert "用户多次客户端实测" in mode
    assert "physical_seat_order" in spec
    assert "物理座位" in terms and "当前座次编号" in terms
    for obsolete in (
        "目前不确定农民谁是2号位",
        "等概率随机分配到2、3号位",
        "农民2、3号位分配是否与叫地主顺序存在固定关联",
    ):
        assert obsolete not in mode
    assert "physical_seat_order" not in instructions
    assert "地主物理右侧" not in instructions
