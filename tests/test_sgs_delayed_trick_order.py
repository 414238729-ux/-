from __future__ import annotations

import pytest

from scripts.sgs_card_rules import DelayedTrick
from scripts.sgs_extended_rules import (
    DelayedTrickEntry,
    DelayedTrickZone,
    LivingSeatRing,
    resolve_delayed_trick_zone,
)


def _three_delayed_tricks() -> DelayedTrickZone:
    return (
        DelayedTrickZone()
        .place(DelayedTrick.INDULGENCE)
        .place(DelayedTrick.SUPPLY_SHORTAGE)
        .place(DelayedTrick.LIGHTNING)
    )


def test_entry_indices_increase_and_do_not_reset_after_resolution() -> None:
    zone = _three_delayed_tricks()
    assert [entry.entry_index for entry in zone.entries] == [1, 2, 3]
    assert zone.next_entry_index == 4

    result = resolve_delayed_trick_zone(
        zone,
        (),
        lambda state, entry: state + (entry.card.value,),
        lambda _state: False,
    )
    replacement = result.remaining_zone.place(DelayedTrick.INDULGENCE)

    assert result.remaining_zone.entries == ()
    assert replacement.entries[0].entry_index == 4
    assert replacement.next_entry_index == 5


def test_same_named_delayed_trick_is_rejected_with_chinese_error() -> None:
    zone = DelayedTrickZone().place("乐不思蜀")

    with pytest.raises(ValueError, match="同名延时锦囊"):
        zone.place(DelayedTrick.INDULGENCE)


def test_direct_zone_construction_also_rejects_duplicate_names() -> None:
    with pytest.raises(ValueError, match="同名延时锦囊"):
        DelayedTrickZone(
            entries=(
                DelayedTrickEntry(DelayedTrick.LIGHTNING, 1),
                DelayedTrickEntry(DelayedTrick.LIGHTNING, 2),
            ),
            next_entry_index=3,
        )


def test_multiple_delayed_tricks_resolve_lifo_with_updated_state() -> None:
    result = resolve_delayed_trick_zone(
        _three_delayed_tricks(),
        (),
        lambda state, entry: state + (entry.card.value,),
        lambda _state: False,
    )

    assert [entry.entry_index for entry in result.processed_entries] == [3, 2, 1]
    assert result.final_state == ("闪电", "兵粮寸断", "乐不思蜀")
    assert result.state_after_each_entry == (
        ("闪电",),
        ("闪电", "兵粮寸断"),
        ("闪电", "兵粮寸断", "乐不思蜀"),
    )
    assert result.remaining_zone.entries == ()
    assert not result.stopped_by_game_over


def test_game_over_stops_before_remaining_delayed_tricks() -> None:
    result = resolve_delayed_trick_zone(
        _three_delayed_tricks(),
        (),
        lambda state, entry: state + (entry.card.value,),
        lambda state: state == ("闪电", "兵粮寸断"),
    )

    assert [entry.card.value for entry in result.processed_entries] == [
        "闪电",
        "兵粮寸断",
    ]
    assert [entry.card.value for entry in result.remaining_zone.entries] == [
        "乐不思蜀"
    ]
    assert result.stopped_by_game_over


def test_lightning_transfer_callback_finishes_before_next_card_continues() -> None:
    def resolve_one(state: tuple[str, ...], entry: DelayedTrickEntry) -> tuple[str, ...]:
        if entry.card is DelayedTrick.LIGHTNING:
            return state + ("闪电移至下家判定区",)
        assert state[-1] == "闪电移至下家判定区"
        return state + (f"完整结算{entry.card.value}",)

    zone = (
        DelayedTrickZone()
        .place(DelayedTrick.INDULGENCE)
        .place(DelayedTrick.LIGHTNING)
    )
    result = resolve_delayed_trick_zone(zone, (), resolve_one, lambda _state: False)

    assert result.final_state == (
        "闪电移至下家判定区",
        "完整结算乐不思蜀",
    )
    assert result.remaining_zone.entries == ()


def test_skipping_entire_judgment_phase_preserves_entries_and_order() -> None:
    zone = _three_delayed_tricks()

    def must_not_run(_state: object, _entry: DelayedTrickEntry) -> object:
        raise AssertionError("跳过整个判定阶段时不应调用单牌结算器")

    result = resolve_delayed_trick_zone(
        zone,
        "原状态",
        must_not_run,
        lambda _state: False,
        judgment_phase_skipped=True,
    )

    assert result.processed_entries == ()
    assert result.remaining_zone == zone
    assert result.remaining_zone.resolution_order == zone.resolution_order
    assert result.final_state == "原状态"
    assert result.skipped_judgment_phase


def test_position_exchange_does_not_change_saved_entry_order() -> None:
    zone = _three_delayed_tricks()
    order_before_swap = zone.resolution_order

    table_after_swap = LivingSeatRing.all_alive(4).swap_current_seats(1, 4)

    assert table_after_swap.occupants_by_current_seat == (4, 2, 3, 1)
    assert zone.resolution_order == order_before_swap
    assert [entry.entry_index for entry in zone.resolution_order] == [3, 2, 1]


@pytest.mark.parametrize(
    ("argument", "message"),
    [
        ("resolve_one_entry", "单张延时锦囊结算器必须是可调用对象"),
        ("is_game_over", "游戏结束判断器必须是可调用对象"),
        ("judgment_phase_skipped", "是否跳过判定阶段必须是布尔值"),
    ],
)
def test_invalid_resolution_inputs_have_chinese_errors(
    argument: str,
    message: str,
) -> None:
    kwargs = {
        "zone": DelayedTrickZone(),
        "initial_state": None,
        "resolve_one_entry": lambda state, _entry: state,
        "is_game_over": lambda _state: False,
        "judgment_phase_skipped": False,
    }
    kwargs[argument] = "无效"

    with pytest.raises(TypeError, match=message):
        resolve_delayed_trick_zone(**kwargs)  # type: ignore[arg-type]
