from __future__ import annotations

from collections import Counter

import pytest

from scripts.sgs_card_rules import DamageType, DelayedTrick, transform_zhangba_spear
from scripts.sgs_extended_rules import (
    DeckOperation,
    Identity,
    IdentityTable,
    IdentityVictory,
    LivingSeatRing,
    TableCardState,
    apply_lord_health_bonus,
    can_place_delayed_trick,
    deal_standard_identities,
    determine_identity_victory,
    resolve_identity_kill_consequence,
    resolve_sequential_effect,
    search_current_draw_pile,
    skip_entire_judgment_phase,
    standard_identity_counts,
    take_bottom_cards,
    take_top_cards,
)


def test_draw_uses_existing_top_then_reshuffles_discard_to_continue() -> None:
    state = TableCardState(draw_pile=("牌堆顶",), discard_pile=("弃1", "弃2"))

    first = take_top_cards(state, 3, seed=20260726)
    second = take_top_cards(state, 3, seed=20260726)

    assert first.cards[0] == "牌堆顶"
    assert set(first.cards[1:]) == {"弃1", "弃2"}
    assert first.completed and first.reshuffled and not first.game_tied
    assert first == second
    assert first.remaining_state.draw_pile == ()
    assert first.remaining_state.discard_pile == ()


def test_cunmu_style_draw_takes_bottom_sequentially_and_reshuffles_if_needed() -> None:
    state = TableCardState(
        draw_pile=("顶", "中", "底"),
        discard_pile=("弃1", "弃2"),
    )

    result = take_bottom_cards(state, 5, seed=20260727)

    assert result.cards[:3] == ("底", "中", "顶")
    assert set(result.cards[3:]) == {"弃1", "弃2"}
    assert result.reshuffled and result.completed and not result.game_tied


def test_cunmu_bottom_draw_uses_same_exhaustion_rule() -> None:
    result = take_bottom_cards(
        TableCardState(draw_pile=("唯一牌",), discard_pile=()),
        2,
    )
    assert result.cards == ("唯一牌",)
    assert result.game_tied
    assert result.exhaustion_policy is not None


def test_reshuffle_uses_only_actual_discard_pile() -> None:
    state = TableCardState(
        draw_pile=("原牌堆",),
        discard_pile=("实际弃牌",),
        resolving_cards=("正在结算",),
        hand_cards=("手牌",),
        equipment_cards=("装备",),
        judgment_cards=("判定区",),
        power_cards=("权",),
        special_zone_cards=("特殊区",),
        removed_from_game_cards=("移出游戏",),
        retained_cards=("效果保留",),
    )

    result = take_top_cards(state, 2, seed=7)

    assert result.cards == ("原牌堆", "实际弃牌")
    assert result.remaining_state.resolving_cards == ("正在结算",)
    assert result.remaining_state.hand_cards == ("手牌",)
    assert result.remaining_state.equipment_cards == ("装备",)
    assert result.remaining_state.judgment_cards == ("判定区",)
    assert result.remaining_state.power_cards == ("权",)
    assert result.remaining_state.special_zone_cards == ("特殊区",)
    assert result.remaining_state.removed_from_game_cards == ("移出游戏",)
    assert result.remaining_state.retained_cards == ("效果保留",)
    assert not {
        "正在结算",
        "手牌",
        "装备",
        "判定区",
        "权",
        "特殊区",
        "移出游戏",
        "效果保留",
    }.intersection(result.cards)


def test_draw_ties_only_when_next_required_card_cannot_be_obtained() -> None:
    state = TableCardState(draw_pile=("甲",), discard_pile=("乙",))

    insufficient = take_top_cards(state, 3, seed=1)
    exact = take_top_cards(state, 2, seed=1)

    assert insufficient.cards == ("甲", "乙")
    assert not insufficient.completed and insufficient.game_tied
    assert exact.cards == ("甲", "乙")
    assert exact.completed and not exact.game_tied


@pytest.mark.parametrize(
    "operation",
    [
        DeckOperation.VIEW_TOP,
        DeckOperation.REVEAL_TOP,
        DeckOperation.JUDGMENT,
    ],
)
def test_other_top_card_operations_use_current_temporary_tie_rule(
    operation: DeckOperation,
) -> None:
    result = take_top_cards(
        TableCardState(draw_pile=(), discard_pile=()),
        1,
        operation=operation,
    )
    assert result.game_tied
    assert not result.completed


def test_zero_requested_cards_never_causes_tie_or_reshuffle() -> None:
    state = TableCardState(draw_pile=(), discard_pile=("弃牌",))
    result = take_top_cards(state, 0)
    assert result.completed and not result.game_tied and not result.reshuffled
    assert result.remaining_state == state


def test_failed_specific_search_does_not_reshuffle_discard() -> None:
    state = TableCardState(
        draw_pile=("杀", "闪"),
        discard_pile=("桃",),
    )
    result = search_current_draw_pile(state, lambda card: card == "桃")
    assert not result.found
    assert result.card is None
    assert not result.reshuffled
    assert result.remaining_state == state


def test_successful_specific_search_removes_only_matching_draw_pile_card() -> None:
    state = TableCardState(
        draw_pile=("杀", "桃", "闪"),
        discard_pile=("桃",),
    )
    result = search_current_draw_pile(state, lambda card: card == "桃")
    assert result.found and result.card == "桃"
    assert result.remaining_state.draw_pile == ("杀", "闪")
    assert result.remaining_state.discard_pile == ("桃",)


@pytest.mark.parametrize("card", list(DelayedTrick))
def test_same_named_delayed_trick_cannot_coexist(card: DelayedTrick) -> None:
    assert not can_place_delayed_trick(card, [card.value])


def test_different_delayed_tricks_can_coexist() -> None:
    assert can_place_delayed_trick(
        DelayedTrick.SUPPLY_SHORTAGE,
        [DelayedTrick.INDULGENCE, DelayedTrick.LIGHTNING],
    )


def test_skipped_judgment_phase_retains_cards_and_opens_no_flow() -> None:
    result = skip_entire_judgment_phase(
        [DelayedTrick.INDULGENCE, "兵粮寸断", "闪电"]
    )
    assert result.retained_cards == tuple(DelayedTrick)
    assert not result.nullification_window_entered
    assert not result.judgment_performed
    assert not result.effect_applied


@pytest.mark.parametrize(
    ("first", "second", "expected_color"),
    [
        ("红色", "红色", "红色"),
        ("黑色", "黑色", "黑色"),
        ("红色", "黑色", "无色"),
        ("黑色", "红色", "无色"),
    ],
)
def test_zhangba_slash_has_color_but_never_suit_or_rank(
    first: str,
    second: str,
    expected_color: str,
) -> None:
    slash = transform_zhangba_spear(
        first,
        second,
        first_rank="A",
        second_rank=13,
    )
    assert slash.color == expected_color
    assert slash.suit is None
    assert slash.suit_status == "当前确认"
    assert slash.rank is None
    assert slash.damage_type is DamageType.UNATTRIBUTED


def test_dead_player_is_removed_from_five_player_distance_ring_without_renumbering() -> None:
    ring = LivingSeatRing.all_alive(5).with_player_dead(3)
    assert ring.living_order == (1, 2, 4, 5)
    assert ring.base_distance(2, 4) == 1
    assert ring.current_seat_of(4) == 4


def test_turn_order_skips_dead_players() -> None:
    ring = LivingSeatRing.all_alive(5).with_player_dead(3)
    assert ring.turn_order_from(2) == (2, 4, 5, 1)
    with pytest.raises(ValueError, match="存活玩家"):
        ring.turn_order_from(3)


def test_arbitrary_player_count_uses_two_directions_on_living_ring() -> None:
    ring = LivingSeatRing.all_alive(6).with_player_dead(2).with_player_dead(5)
    assert ring.living_order == (1, 3, 4, 6)
    assert ring.base_distance(1, 4) == 2
    assert ring.base_distance(3, 4) == 1


def test_position_swap_recalculates_from_current_ring() -> None:
    initial = LivingSeatRing.all_alive(5)
    swapped = initial.swap_current_seats(2, 3)
    assert initial.base_distance(1, 3) == 2
    assert swapped.occupants_by_current_seat == (1, 3, 2, 4, 5)
    assert swapped.base_distance(1, 3) == 1
    assert swapped.current_seat_of(3) == 2


def test_standard_identity_counts_for_five_and_eight_players() -> None:
    assert standard_identity_counts(5) == {
        Identity.LORD: 1,
        Identity.LOYALIST: 1,
        Identity.REBEL: 2,
        Identity.SPY: 1,
    }
    assert standard_identity_counts(8) == {
        Identity.LORD: 1,
        Identity.LOYALIST: 2,
        Identity.REBEL: 4,
        Identity.SPY: 1,
    }
    with pytest.raises(ValueError, match="只展开了五人局和八人局"):
        standard_identity_counts(6)


def _five_player_table() -> IdentityTable:
    return IdentityTable(
        physical_order=(101, 102, 103, 104, 105),
        identities={
            101: Identity.REBEL,
            102: Identity.LOYALIST,
            103: Identity.LORD,
            104: Identity.SPY,
            105: Identity.REBEL,
        },
    )


def test_lord_is_redefined_as_seat_one_without_moving_physical_order() -> None:
    table = _five_player_table()
    assert table.physical_order == (101, 102, 103, 104, 105)
    assert table.numbered_player_order == (103, 104, 105, 101, 102)
    assert table.seat_number_of(103) == 1
    assert table.seat_number_of(101) == 4


def test_lord_acts_first_and_dead_players_are_skipped() -> None:
    table = _five_player_table()
    assert table.turn_order() == (103, 104, 105, 101, 102)
    assert table.turn_order({101, 103, 104, 105}) == (103, 104, 105, 101)


def test_non_lord_identity_is_hidden_until_confirmed_death() -> None:
    table = _five_player_table()
    assert table.visible_identity(101, 103) is Identity.LORD
    assert table.visible_identity(101, 101) is Identity.REBEL
    assert table.visible_identity(101, 102) is None
    assert table.visible_identity(101, 102, confirmed_dead={102}) is Identity.LOYALIST


def test_standard_identity_deal_is_seeded_and_has_exact_counts() -> None:
    first = deal_standard_identities((1, 2, 3, 4, 5), seed=20260726)
    second = deal_standard_identities((1, 2, 3, 4, 5), seed=20260726)
    assert first.identities == second.identities
    assert Counter(first.identities.values()) == Counter(standard_identity_counts(5))


def test_lord_health_bonus_increases_both_values() -> None:
    result = apply_lord_health_bonus(4, 4)
    assert (result.maximum_hp, result.initial_hp) == (5, 5)


@pytest.mark.parametrize("killer", list(Identity))
def test_any_identity_killing_rebel_draws_three(killer: Identity) -> None:
    result = resolve_identity_kill_consequence(killer, Identity.REBEL)
    assert result.draw_count == 3


def test_lord_killing_loyalist_discards_hand_and_equipment_but_not_judgment() -> None:
    result = resolve_identity_kill_consequence(
        Identity.LORD,
        Identity.LOYALIST,
        killer_hand=("手牌1", "手牌2"),
        killer_equipment=("武器", "防具"),
        killer_judgment=("闪电",),
    )
    assert result.draw_count == 0
    assert result.discarded_hand == ("手牌1", "手牌2")
    assert result.discarded_equipment == ("武器", "防具")
    assert result.retained_judgment == ("闪电",)


def test_non_lord_killing_loyalist_has_no_lord_penalty() -> None:
    result = resolve_identity_kill_consequence(
        Identity.REBEL,
        Identity.LOYALIST,
        killer_hand=("手牌",),
        killer_equipment=("武器",),
    )
    assert result.discarded_hand == ()
    assert result.discarded_equipment == ()


def test_only_lord_and_spy_remaining_does_not_end_game() -> None:
    table = _five_player_table()
    assert determine_identity_victory(table.identities, {103, 104}) is IdentityVictory.ONGOING


def test_spy_wins_only_as_sole_survivor_after_lord_dies() -> None:
    table = _five_player_table()
    assert determine_identity_victory(table.identities, {104}) is IdentityVictory.SPY


def test_lord_death_with_loyalist_alive_is_rebel_victory() -> None:
    table = _five_player_table()
    assert determine_identity_victory(table.identities, {102, 104}) is IdentityVictory.REBELS


def test_lord_and_loyalists_win_when_no_rebel_or_spy_remains() -> None:
    table = _five_player_table()
    assert determine_identity_victory(table.identities, {102, 103}) is IdentityVictory.LORD_AND_LOYALISTS


def test_continuous_effect_finishes_one_death_then_stops_after_victory() -> None:
    def resolve_one(log: tuple[str, ...], target: int) -> tuple[str, ...]:
        return log + (
            f"伤害:{target}",
            f"确认死亡:{target}",
            f"胜利前置状态:{target}",
            f"胜负检查:{target}",
        )

    result = resolve_sequential_effect(
        (2, 3, 4),
        (),
        resolve_one,
        lambda log: "胜负检查:2" in log,
    )
    assert result.processed_targets == (2,)
    assert result.final_state == (
        "伤害:2",
        "确认死亡:2",
        "胜利前置状态:2",
        "胜负检查:2",
    )
    assert result.stopped_by_game_over
    assert not any(item.endswith(":3") for item in result.final_state)


def test_continuous_effect_processes_next_only_after_previous_handler_returns() -> None:
    def resolve_one(log: tuple[str, ...], target: int) -> tuple[str, ...]:
        return log + (f"开始:{target}", f"死亡完成:{target}")

    result = resolve_sequential_effect(
        (2, 3), (), resolve_one, lambda _state: False
    )
    assert result.final_state == (
        "开始:2",
        "死亡完成:2",
        "开始:3",
        "死亡完成:3",
    )
    assert not result.stopped_by_game_over
