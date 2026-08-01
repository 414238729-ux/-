from __future__ import annotations

from dataclasses import replace

import pytest

from scripts.sgs_extended_rules import LivingSeatRing
from scripts.sgs_limited_identity_variant import (
    LIMITED_MODE_VARIANT,
    AmbitionistMark,
    CardRegion,
    CurrentRole,
    LordRegions,
    ModeVariant,
    PlayerRoleState,
    RegionCardChoice,
    SpyPathChoice,
    VariantVictory,
    VirtualPeachTiming,
    ambitionist_mode_skills_active,
    apply_spy_path_at_turn_start,
    can_choose_spy_path,
    can_heir_succeed,
    choose_spy_path,
    counts_as_lord_or_loyalist_death_for_spy_path,
    determine_variant_victory,
    expire_heir_selection,
    finalize_old_lord_formal_death_after_succession,
    finalize_old_lord_formal_death_without_succession,
    initial_heir_selection_state,
    initial_spy_path_state,
    load_variant_features,
    next_living_player_after,
    ordinary_card_effect_can_affect_ambitionist_mark,
    reveal_current_identity_after_confirmed_death,
    retarget_pending_spy_path_after_seat_death,
    resolve_heir_confirmed_death,
    resolve_heir_succession_after_failed_rescue,
    resolve_variant_identity_kill_reward,
    resolve_variant_sequential_deaths,
    select_heir,
    use_ambitionist_mark_as_peach,
    use_ambitionist_mark_to_draw_two,
    view_heir_information,
)


def test_package_exports_limited_variant_entrypoints() -> None:
    from scripts import LIMITED_MODE_VARIANT as exported_mode
    from scripts import load_variant_features as exported_loader

    assert exported_mode == LIMITED_MODE_VARIANT
    assert exported_loader(exported_mode).special_rules_loaded


def _selected_heir(target: int = 5):
    state = initial_heir_selection_state(LIMITED_MODE_VARIANT, 1)
    return select_heir(
        state,
        target,
        alive_players=range(1, 9),
        first_round_active=True,
    )


def _roles(heir_role: CurrentRole = CurrentRole.LOYALIST):
    return {
        1: CurrentRole.LORD,
        2: CurrentRole.REBEL,
        3: CurrentRole.REBEL,
        4: CurrentRole.REBEL,
        5: heir_role,
        6: CurrentRole.LOYALIST,
        7: CurrentRole.REBEL,
        8: CurrentRole.SPY,
    }


def _successful_succession(
    *,
    selected_card: RegionCardChoice | None = None,
    regions: LordRegions[str] | None = None,
):
    return resolve_heir_succession_after_failed_rescue(
        _selected_heir(),
        rescue_failed=True,
        roles_current=_roles(),
        living_seat_ring=LivingSeatRing.all_alive(8),
        old_lord_regions=regions
        or LordRegions(
            hand=("主公手牌",),
            equipment=("主公装备",),
            judgment=("主公判定牌",),
        ),
        new_lord_hand_before=("储君原手牌",),
        new_lord_maximum_hp_before=4,
        new_lord_current_hp_before=3,
        selected_card=selected_card,
        new_lord_has_lord_skill=True,
    )


def test_standard_mode_does_not_load_heir_or_spy_path_rules() -> None:
    features = load_variant_features(ModeVariant.STANDARD_EIGHT_PLAYER)
    heir = initial_heir_selection_state(ModeVariant.STANDARD_EIGHT_PLAYER, 1)

    assert not features.special_rules_loaded
    assert not features.heir_selection_enabled
    assert not features.spy_path_enabled
    assert not heir.heir_selection_available
    with pytest.raises(ValueError, match="仅在移动版八人军争限时变体"):
        select_heir(heir, 2, alive_players=range(1, 9), first_round_active=True)
    assert not can_choose_spy_path(
        ModeVariant.STANDARD_EIGHT_PLAYER,
        role_current=CurrentRole.SPY,
        player_alive=True,
        alive_player_count=8,
        lord_or_loyalist_confirmed_dead=True,
    )
    forged_pending = replace(
        initial_spy_path_state(ModeVariant.STANDARD_EIGHT_PLAYER),
        spy_path_choice=SpyPathChoice.LOYALIST,
        spy_path_pending=True,
        spy_path_locked=True,
        spy_path_effective_turn_player_id=2,
    )
    with pytest.raises(ValueError, match="仅在移动版八人军争限时变体"):
        apply_spy_path_at_turn_start(
            forged_pending,
            PlayerRoleState(CurrentRole.SPY, CurrentRole.SPY),
            turn_player_id=2,
        )


def test_limited_mode_explicitly_loads_special_rules() -> None:
    features = load_variant_features(LIMITED_MODE_VARIANT)
    assert features.special_rules_loaded
    assert features.heir_selection_enabled
    assert features.spy_path_enabled


def test_lord_can_select_any_other_alive_role_during_first_round_once() -> None:
    state = initial_heir_selection_state(LIMITED_MODE_VARIANT, 1)
    selected = select_heir(
        state,
        8,
        alive_players=range(1, 9),
        first_round_active=True,
    )
    assert selected.heir_player_id == 8
    assert selected.heir_selected and selected.heir_selection_used
    assert not selected.heir_selection_available
    with pytest.raises(ValueError, match="已经使用或失效"):
        select_heir(
            selected,
            7,
            alive_players=range(1, 9),
            first_round_active=True,
        )


def test_heir_selection_expires_after_first_round_and_is_optional() -> None:
    state = initial_heir_selection_state(LIMITED_MODE_VARIANT, 1)
    expired = expire_heir_selection(state)
    assert not expired.heir_selected
    assert not expired.heir_selection_available
    with pytest.raises(ValueError, match="第一轮已经结束"):
        select_heir(
            state,
            2,
            alive_players=range(1, 9),
            first_round_active=False,
        )


def test_heir_target_must_be_other_alive_player() -> None:
    state = initial_heir_selection_state(LIMITED_MODE_VARIANT, 1)
    with pytest.raises(ValueError, match="不能选择自己"):
        select_heir(state, 1, alive_players=range(1, 9), first_round_active=True)
    with pytest.raises(ValueError, match="仍在场"):
        select_heir(state, 8, alive_players=range(1, 8), first_round_active=True)


def test_heir_identity_and_selection_status_are_secret_from_every_non_owner() -> None:
    state = _selected_heir(5)
    lord_view = view_heir_information(state, 1)
    heir_view = view_heir_information(state, 5)
    other_view = view_heir_information(state, 6)

    assert lord_view.selection_status_known and lord_view.heir_player_id == 5
    assert heir_view == other_view
    assert not heir_view.selection_status_known
    assert heir_view.heir_selected is None and heir_view.heir_player_id is None


def test_heir_death_causes_hp_loss_not_damage_and_clears_secret_status() -> None:
    result = resolve_heir_confirmed_death(
        _selected_heir(),
        5,
        current_lord_player_id=1,
        alive_players_before_death=range(1, 9),
        current_lord_hp=1,
    )
    assert result.triggered
    assert (result.lord_hp_before, result.lord_hp_after) == (1, 0)
    assert result.hp_loss_amount == 1 and result.lord_enters_dying
    assert not result.is_damage and not result.triggers_damage_events
    assert result.damage_source is None and result.damage_type is None
    assert not result.heir_state_after.heir_selected
    assert result.heir_state_after.heir_player_id is None


@pytest.mark.parametrize(
    "heir_role",
    [
        CurrentRole.LOYALIST,
        CurrentRole.REBEL,
        CurrentRole.SPY,
        CurrentRole.AMBITIONIST,
    ],
)
def test_heir_death_hp_loss_does_not_depend_on_current_role(
    heir_role: CurrentRole,
) -> None:
    # 身份不作为该函数输入，确保所有当前身份走同一储君死亡结算。
    assert heir_role in CurrentRole
    result = resolve_heir_confirmed_death(
        _selected_heir(),
        5,
        current_lord_player_id=1,
        alive_players_before_death=range(1, 9),
        current_lord_hp=4,
    )
    assert result.triggered and result.lord_hp_after == 3


def test_non_heir_death_does_not_reduce_lord_hp() -> None:
    result = resolve_heir_confirmed_death(
        _selected_heir(),
        4,
        current_lord_player_id=1,
        alive_players_before_death=range(1, 9),
        current_lord_hp=4,
    )
    assert not result.triggered and result.lord_hp_after == 4


@pytest.mark.parametrize(
    ("role", "expected"),
    [
        (CurrentRole.LOYALIST, True),
        (CurrentRole.REBEL, False),
        (CurrentRole.SPY, False),
        (CurrentRole.AMBITIONIST, False),
    ],
)
def test_only_current_loyalist_heir_can_succeed(
    role: CurrentRole, expected: bool
) -> None:
    assert can_heir_succeed(
        _selected_heir(), _roles(role), range(1, 9)
    ) is expected


def test_converted_spy_who_is_now_loyalist_can_succeed() -> None:
    role_record = PlayerRoleState(CurrentRole.SPY, CurrentRole.LOYALIST)
    roles = _roles(role_record.role_current)
    assert can_heir_succeed(_selected_heir(), roles, range(1, 9))


@pytest.mark.parametrize(
    ("region", "expected_card"),
    [
        (CardRegion.HAND, "主公手牌"),
        (CardRegion.EQUIPMENT, "主公装备"),
        (CardRegion.JUDGMENT, "主公判定牌"),
    ],
)
def test_heir_may_obtain_one_card_from_any_old_lord_region(
    region: CardRegion, expected_card: str
) -> None:
    result = _successful_succession(selected_card=RegionCardChoice(region, 0))
    assert result.succeeded
    assert result.obtained_card == expected_card
    assert result.obtained_from is region
    assert result.new_lord_hand == ("储君原手牌", expected_card)


def test_heir_may_choose_to_obtain_zero_cards() -> None:
    result = _successful_succession(selected_card=None)
    assert result.succeeded
    assert result.obtained_card is None
    assert result.new_lord_hand == ("储君原手牌",)


def test_succession_is_after_failed_rescue_and_before_formal_death() -> None:
    result = _successful_succession()
    assert result.checked_after_rescue_failure
    assert result.checked_before_formal_death
    assert result.succession_completed_before_formal_death
    assert not result.rebel_instant_win_from_old_lord_death
    assert result.completed_event_order == (
        "完成濒死救援",
        "检查合法储君",
        "处理从原主公区域内获得至多1张牌的选择",
        "公开新主公身份并更新当前主公",
        "新主公体力上限增加1",
        "新主公回复1点体力",
        "启用新主公自身的主公技",
    )
    assert result.next_required_event == "确认原主公正式死亡"
    assert "确认原主公正式死亡" not in result.completed_event_order


def test_heir_obtains_card_before_remaining_old_lord_regions_leave() -> None:
    result = _successful_succession(
        selected_card=RegionCardChoice(CardRegion.HAND, 0),
        regions=LordRegions(
            hand=("被储君取得", "原主公剩余手牌"),
            equipment=("原主公装备",),
            judgment=("原主公判定牌",),
        ),
    )

    assert result.obtained_card == "被储君取得"
    assert result.new_lord_hand[-1] == "被储君取得"
    assert result.remaining_old_lord_regions == LordRegions(
        hand=("原主公剩余手牌",),
        equipment=("原主公装备",),
        judgment=("原主公判定牌",),
    )
    assert 1 in result.living_seat_ring.alive_players
    assert result.current_lord_player_id == 5


def test_no_legal_heir_formally_dies_then_checks_rebel_victory() -> None:
    roles = _roles(CurrentRole.REBEL)
    check = resolve_heir_succession_after_failed_rescue(
        _selected_heir(),
        rescue_failed=True,
        roles_current=roles,
        living_seat_ring=LivingSeatRing.all_alive(8),
        old_lord_regions=LordRegions(hand=("仍在原主公区域的牌",)),
        new_lord_maximum_hp_before=4,
        new_lord_current_hp_before=4,
    )

    assert not check.succeeded
    assert check.completed_event_order == ("完成濒死救援", "检查合法储君")
    assert check.next_required_event == "确认原主公正式死亡"
    assert check.remaining_old_lord_regions.hand == ("仍在原主公区域的牌",)
    after_formal_death = finalize_old_lord_formal_death_without_succession(
        check, 1
    )
    assert 1 not in after_formal_death.alive_players
    assert (
        determine_variant_victory(
            roles,
            after_formal_death.alive_players,
            current_lord_player_id=1,
        )
        is VariantVictory.REBELS
    )


def test_successor_gets_max_hp_then_one_recovery_and_lord_skill() -> None:
    result = _successful_succession()
    assert result.new_lord_maximum_hp == 5
    assert result.new_lord_current_hp == 4
    assert result.new_lord_identity_revealed
    assert result.lord_skill_enabled
    assert result.roles_current[5] is CurrentRole.LORD


def test_rescue_success_prevents_succession_check() -> None:
    result = resolve_heir_succession_after_failed_rescue(
        _selected_heir(),
        rescue_failed=False,
        roles_current=_roles(),
        living_seat_ring=LivingSeatRing.all_alive(8),
        old_lord_regions=LordRegions(),
        new_lord_maximum_hp_before=4,
        new_lord_current_hp_before=4,
    )
    assert not result.succeeded
    assert not result.checked_after_rescue_failure
    assert result.current_lord_player_id == 1


def test_succession_keeps_seat_numbers_and_grants_no_extra_turn() -> None:
    result = _successful_succession()
    assert result.current_lord_player_id == 5
    assert result.living_seat_ring.current_seat_of(5) == 5
    assert result.living_seat_ring.occupants_by_current_seat == tuple(range(1, 9))
    # 继位已完成但原主公尚未正式死亡，因此此时仍在存活角色环中。
    assert result.living_seat_ring.living_order == tuple(range(1, 9))
    assert not result.seats_renumbered
    assert not result.extra_turn_granted
    assert not result.heir_state_after.heir_selection_available

    after_formal_death = finalize_old_lord_formal_death_after_succession(
        result, 1
    )
    assert after_formal_death.occupants_by_current_seat == tuple(range(1, 9))
    assert after_formal_death.living_order == (2, 3, 4, 5, 6, 7, 8)
    assert after_formal_death.base_distance(2, 8) == 1
    assert after_formal_death.base_distance(5, 7) == 2


def test_new_lord_cannot_select_another_heir() -> None:
    state = _successful_succession().heir_state_after
    with pytest.raises(ValueError, match="已经使用或失效"):
        select_heir(
            state,
            6,
            alive_players=range(2, 9),
            first_round_active=True,
        )


def test_spy_path_requires_more_than_four_alive_and_main_camp_death() -> None:
    assert can_choose_spy_path(
        LIMITED_MODE_VARIANT,
        role_current=CurrentRole.SPY,
        player_alive=True,
        alive_player_count=5,
        lord_or_loyalist_confirmed_dead=True,
    )
    assert not can_choose_spy_path(
        LIMITED_MODE_VARIANT,
        role_current=CurrentRole.SPY,
        player_alive=True,
        alive_player_count=4,
        lord_or_loyalist_confirmed_dead=True,
    )
    assert not can_choose_spy_path(
        LIMITED_MODE_VARIANT,
        role_current=CurrentRole.SPY,
        player_alive=True,
        alive_player_count=8,
        lord_or_loyalist_confirmed_dead=False,
    )


@pytest.mark.parametrize(
    ("role", "was_lord", "expected"),
    [
        (CurrentRole.LORD, False, True),
        (CurrentRole.LOYALIST, False, True),
        (CurrentRole.SPY, True, True),
        (CurrentRole.REBEL, False, False),
        (CurrentRole.SPY, False, False),
        (CurrentRole.AMBITIONIST, False, False),
    ],
)
def test_spy_path_main_camp_death_uses_current_role_or_lord_status(
    role: CurrentRole,
    was_lord: bool,
    expected: bool,
) -> None:
    assert (
        counts_as_lord_or_loyalist_death_for_spy_path(
            role,
            was_current_lord=was_lord,
        )
        is expected
    )


def test_deferring_spy_choice_leaves_state_unlocked() -> None:
    state = initial_spy_path_state(LIMITED_MODE_VARIANT)
    assert state.spy_path_choice is None
    assert not state.spy_path_pending and not state.spy_path_locked

    chosen_later = choose_spy_path(
        state,
        SpyPathChoice.AMBITIONIST,
        role_current=CurrentRole.SPY,
        player_alive=True,
        alive_player_count=5,
        lord_or_loyalist_confirmed_dead=True,
        effective_turn_player_id=4,
    )
    assert chosen_later.spy_path_pending and chosen_later.spy_path_locked


def test_next_living_player_skips_dead_seat() -> None:
    ring = LivingSeatRing.all_alive(8).with_player_dead(3)
    assert next_living_player_after(ring, 2) == 4


def test_pending_spy_path_naturally_waits_through_consecutive_deaths() -> None:
    pending = choose_spy_path(
        initial_spy_path_state(LIMITED_MODE_VARIANT),
        SpyPathChoice.LOYALIST,
        role_current=CurrentRole.SPY,
        player_alive=True,
        alive_player_count=7,
        lord_or_loyalist_confirmed_dead=True,
        effective_turn_player_id=3,
    )
    assert pending.spy_path_effective_turn_player_id is None
    ring = (
        LivingSeatRing.all_alive(8)
        .with_player_dead(3)
        .with_player_dead(4)
    )
    unchanged = retarget_pending_spy_path_after_seat_death(pending, ring)
    assert unchanged.spy_path_effective_turn_player_id is None

    role = PlayerRoleState(CurrentRole.SPY, CurrentRole.SPY)
    dead_three = apply_spy_path_at_turn_start(
        unchanged,
        role,
        turn_player_id=3,
        turn_player_alive=False,
    )
    assert not dead_three.applied
    assert dead_three.spy_path_state_after.spy_path_pending
    dead_four = apply_spy_path_at_turn_start(
        dead_three.spy_path_state_after,
        role,
        turn_player_id=4,
        turn_player_alive=False,
    )
    assert not dead_four.applied
    assert dead_four.spy_path_state_after.spy_path_pending

    applied = apply_spy_path_at_turn_start(
        dead_four.spy_path_state_after,
        role,
        turn_player_id=5,
        turn_player_alive=True,
    )
    assert applied.applied


def test_spy_path_applies_at_first_actual_turn_start_without_player_binding() -> None:
    state = choose_spy_path(
        initial_spy_path_state(LIMITED_MODE_VARIANT),
        SpyPathChoice.LOYALIST,
        role_current=CurrentRole.SPY,
        player_alive=True,
        alive_player_count=7,
        lord_or_loyalist_confirmed_dead=True,
        effective_turn_player_id=4,
    )
    role = PlayerRoleState(CurrentRole.SPY, CurrentRole.SPY)
    first_actual_event = apply_spy_path_at_turn_start(
        state,
        role,
        turn_player_id=7,
    )

    assert state.spy_path_pending and state.spy_path_locked
    assert state.spy_path_effective_turn_player_id is None
    assert first_actual_event.applied
    assert first_actual_event.role_state_after.role_current is CurrentRole.LOYALIST
    with pytest.raises(ValueError, match="已经锁定"):
        choose_spy_path(
            state,
            SpyPathChoice.AMBITIONIST,
            role_current=CurrentRole.SPY,
            player_alive=True,
            alive_player_count=7,
            lord_or_loyalist_confirmed_dead=True,
        )


def test_locked_spy_path_still_applies_after_alive_count_falls_below_four() -> None:
    state = choose_spy_path(
        initial_spy_path_state(LIMITED_MODE_VARIANT),
        SpyPathChoice.LOYALIST,
        role_current=CurrentRole.SPY,
        player_alive=True,
        alive_player_count=6,
        lord_or_loyalist_confirmed_dead=True,
        effective_turn_player_id=4,
    )
    # 应用接口故意不再接收原触发条件，锁定后的条件变化不能取消。
    result = apply_spy_path_at_turn_start(
        state,
        PlayerRoleState(CurrentRole.SPY, CurrentRole.SPY),
        turn_player_id=4,
        alive_player_count=3,
    )
    assert result.applied
    assert result.role_state_after.role_current is CurrentRole.LOYALIST


def test_locked_spy_path_does_not_apply_after_game_has_ended() -> None:
    state = choose_spy_path(
        initial_spy_path_state(LIMITED_MODE_VARIANT),
        SpyPathChoice.LOYALIST,
        role_current=CurrentRole.SPY,
        player_alive=True,
        alive_player_count=6,
        lord_or_loyalist_confirmed_dead=True,
        effective_turn_player_id=4,
    )
    result = apply_spy_path_at_turn_start(
        state,
        PlayerRoleState(CurrentRole.SPY, CurrentRole.SPY),
        turn_player_id=4,
        game_over=True,
    )
    assert not result.applied
    assert result.cancelled
    assert result.cancellation_reason == "游戏已结束"
    assert not result.spy_path_state_after.spy_path_pending
    assert result.role_state_after.role_current is CurrentRole.SPY


def test_locked_spy_path_does_not_apply_after_chooser_dies() -> None:
    state = choose_spy_path(
        initial_spy_path_state(LIMITED_MODE_VARIANT),
        SpyPathChoice.AMBITIONIST,
        role_current=CurrentRole.SPY,
        player_alive=True,
        alive_player_count=6,
        lord_or_loyalist_confirmed_dead=True,
    )
    result = apply_spy_path_at_turn_start(
        state,
        PlayerRoleState(CurrentRole.SPY, CurrentRole.SPY),
        turn_player_id=4,
        chooser_alive=False,
    )
    assert not result.applied
    assert result.cancelled
    assert result.cancellation_reason == "择途选择者已死亡"
    assert not result.spy_path_state_after.spy_path_pending
    assert result.role_state_after.role_current is CurrentRole.SPY


def test_loyalist_conversion_announces_event_but_keeps_player_identity_hidden() -> None:
    state = choose_spy_path(
        initial_spy_path_state(LIMITED_MODE_VARIANT),
        SpyPathChoice.LOYALIST,
        role_current=CurrentRole.SPY,
        player_alive=True,
        alive_player_count=6,
        lord_or_loyalist_confirmed_dead=True,
        effective_turn_player_id=2,
    )
    result = apply_spy_path_at_turn_start(
        state,
        PlayerRoleState(CurrentRole.SPY, CurrentRole.SPY),
        turn_player_id=2,
    )
    assert result.public_conversion_event
    assert result.spy_became_loyalist_announced
    assert not result.converted_loyalist_identity_revealed
    assert not result.converted_player_identity_revealed
    assert result.role_state_after.role_original is CurrentRole.SPY
    assert result.role_state_after.role_current is CurrentRole.LOYALIST

    dead = reveal_current_identity_after_confirmed_death(result.role_state_after)
    assert dead.identity_revealed
    assert dead.role_current is CurrentRole.LOYALIST


def test_lord_killing_converted_loyalist_uses_current_role_penalty() -> None:
    converted = PlayerRoleState(CurrentRole.SPY, CurrentRole.LOYALIST)
    result = resolve_variant_identity_kill_reward(
        CurrentRole.LORD, converted.role_current
    )
    assert result.lord_killed_current_loyalist_penalty_applies
    assert result.identity_draw_count == 0


def test_converted_loyalist_uses_loyalist_victory_condition() -> None:
    roles = {
        1: CurrentRole.LORD,
        2: CurrentRole.LOYALIST,
        8: PlayerRoleState(CurrentRole.SPY, CurrentRole.LOYALIST).role_current,
    }
    assert (
        determine_variant_victory(roles, {1, 2, 8}, current_lord_player_id=1)
        is VariantVictory.LORD_AND_LOYALISTS
    )


def test_main_camp_victory_uses_current_roles_and_waits_for_ambitionist_death() -> None:
    converted_from_rebel = PlayerRoleState(
        CurrentRole.REBEL,
        CurrentRole.LOYALIST,
    )
    converted_from_spy = PlayerRoleState(
        CurrentRole.SPY,
        CurrentRole.LOYALIST,
    )
    roles = {
        1: CurrentRole.LORD,
        2: converted_from_rebel.role_current,
        3: converted_from_spy.role_current,
        8: CurrentRole.AMBITIONIST,
    }
    assert (
        determine_variant_victory(
            roles,
            {1, 2, 3, 8},
            current_lord_player_id=1,
        )
        is VariantVictory.ONGOING
    )
    assert (
        determine_variant_victory(
            roles,
            {1, 2, 3},
            current_lord_player_id=1,
        )
        is VariantVictory.LORD_AND_LOYALISTS
    )


def _apply_ambitionist_path():
    pending = choose_spy_path(
        initial_spy_path_state(LIMITED_MODE_VARIANT),
        SpyPathChoice.AMBITIONIST,
        role_current=CurrentRole.SPY,
        player_alive=True,
        alive_player_count=6,
        lord_or_loyalist_confirmed_dead=True,
        effective_turn_player_id=2,
    )
    return apply_spy_path_at_turn_start(
        pending,
        PlayerRoleState(CurrentRole.SPY, CurrentRole.SPY),
        turn_player_id=2,
    )


def test_ambitionist_conversion_is_public_and_grants_existing_skills_and_mark() -> None:
    result = _apply_ambitionist_path()
    assert result.applied
    assert result.role_state_after.role_current is CurrentRole.AMBITIONIST
    assert result.ambitionist_identity_revealed
    assert result.converted_player_identity_revealed
    assert result.granted_skills == ("飞扬", "跋扈")
    assert result.ambitionist_mark == AmbitionistMark()


def test_ambitionist_heir_status_remains_but_cannot_succeed() -> None:
    heir = _selected_heir(8)
    converted = _apply_ambitionist_path()
    assert heir.heir_selected and heir.heir_player_id == 8
    roles = _roles()
    roles[8] = converted.role_state_after.role_current
    assert not can_heir_succeed(heir, roles, range(1, 9))
    death = resolve_heir_confirmed_death(
        heir,
        8,
        current_lord_player_id=1,
        alive_players_before_death=range(1, 9),
        current_lord_hp=3,
    )
    assert death.triggered and death.lord_hp_after == 2


def test_ambitionist_skills_use_confirmed_three_alive_boundary_only() -> None:
    assert ambitionist_mode_skills_active(3)
    assert not ambitionist_mode_skills_active(2)


def test_ambitionist_mark_is_not_a_card_or_card_zone_resource() -> None:
    mark = AmbitionistMark()
    assert mark.available and mark.count == 1
    assert not mark.is_card and mark.card_zone is None
    assert mark.suit is None and mark.color is None and mark.rank is None
    assert not ordinary_card_effect_can_affect_ambitionist_mark()
    # 弃置全部手牌或装备只会改变卡牌容器，不会改变独立标记对象。
    assert mark == AmbitionistMark()


def test_mark_virtual_peach_can_be_used_on_self_in_play_phase() -> None:
    result = use_ambitionist_mark_as_peach(
        AmbitionistMark(),
        user_player_id=8,
        target_player_id=8,
        timing=VirtualPeachTiming.OWN_PLAY_PHASE,
    )
    assert result.card_name == "桃" and result.virtual_card
    assert result.counts_as_card_use and result.counts_as_peach_use
    assert result.recovery_amount == 1
    assert not result.used_from_hand and not result.physical_card_lost
    assert not result.counts_as_discard and not result.mark_after.available


@pytest.mark.parametrize("target", [8, 3])
def test_mark_virtual_peach_can_rescue_self_or_other_dying_player(target: int) -> None:
    result = use_ambitionist_mark_as_peach(
        AmbitionistMark(),
        user_player_id=8,
        target_player_id=target,
        timing=VirtualPeachTiming.DYING_RESCUE,
        target_is_dying=True,
    )
    assert result.target_player_id == target
    assert result.counts_as_peach_use


def test_mark_can_draw_two_in_play_phase_without_counting_as_card_use() -> None:
    result = use_ambitionist_mark_to_draw_two(
        AmbitionistMark(), in_own_play_phase=True
    )
    assert result.draw_count == 2
    assert not result.counts_as_card_use and not result.physical_card_lost
    assert not result.mark_after.available


def test_mark_two_uses_are_mutually_exclusive_and_do_not_restore() -> None:
    peach = use_ambitionist_mark_as_peach(
        AmbitionistMark(),
        user_player_id=8,
        target_player_id=8,
        timing=VirtualPeachTiming.OWN_PLAY_PHASE,
    )
    with pytest.raises(ValueError, match="已经移去"):
        use_ambitionist_mark_to_draw_two(
            peach.mark_after, in_own_play_phase=True
        )


@pytest.mark.parametrize(
    "victim",
    [
        CurrentRole.LORD,
        CurrentRole.LOYALIST,
        CurrentRole.REBEL,
        CurrentRole.SPY,
        CurrentRole.AMBITIONIST,
    ],
)
def test_ambitionist_kill_identity_reward_is_at_most_one_optional_draw_three(
    victim: CurrentRole,
) -> None:
    accepted = resolve_variant_identity_kill_reward(
        CurrentRole.AMBITIONIST, victim
    )
    declined = resolve_variant_identity_kill_reward(
        CurrentRole.AMBITIONIST,
        victim,
        ambitionist_accepts_reward=False,
    )
    assert accepted.identity_draw_count == 3
    assert accepted.identity_reward_event_count == 1
    assert declined.identity_draw_count == 0


def test_ambitionist_killing_rebel_does_not_stack_to_six() -> None:
    result = resolve_variant_identity_kill_reward(
        CurrentRole.AMBITIONIST, CurrentRole.REBEL
    )
    assert result.identity_draw_count == 3
    assert result.total_draw_count == 3
    assert result.identity_reward_event_count == 1
    assert result.standard_rebel_reward_suppressed


def test_killing_ambitionist_has_no_identity_reward_but_skill_draw_still_works() -> None:
    result = resolve_variant_identity_kill_reward(
        CurrentRole.REBEL,
        CurrentRole.AMBITIONIST,
        independent_skill_draw_count=2,
    )
    assert not result.identity_reward_available
    assert result.identity_draw_count == 0
    assert result.independent_skill_draw_count == 2
    assert result.total_draw_count == 2


def test_only_lord_and_ambitionist_remaining_keeps_game_running() -> None:
    roles = {1: CurrentRole.LORD, 8: CurrentRole.AMBITIONIST}
    assert (
        determine_variant_victory(roles, {1, 8}, current_lord_player_id=1)
        is VariantVictory.ONGOING
    )


def test_ambitionist_wins_only_as_sole_survivor_after_current_lord_dies() -> None:
    roles = {
        1: CurrentRole.LORD,
        5: CurrentRole.LORD,
        8: CurrentRole.AMBITIONIST,
    }
    assert (
        determine_variant_victory(roles, {8}, current_lord_player_id=5)
        is VariantVictory.AMBITIONIST
    )


def test_lord_death_without_solo_spy_or_ambitionist_is_rebel_victory() -> None:
    roles = {
        1: CurrentRole.LORD,
        2: CurrentRole.LOYALIST,
        8: CurrentRole.AMBITIONIST,
    }
    assert (
        determine_variant_victory(roles, {2, 8}, current_lord_player_id=1)
        is VariantVictory.REBELS
    )


def test_successful_succession_keeps_victory_centered_on_new_lord() -> None:
    result = _successful_succession()
    assert result.current_lord_player_id == 5
    after_formal_death = finalize_old_lord_formal_death_after_succession(
        result, 1
    )
    assert (
        determine_variant_victory(
            result.roles_current,
            after_formal_death.alive_players,
            current_lord_player_id=5,
        )
        is VariantVictory.ONGOING
    )


def test_sequential_deaths_use_current_role_and_stop_after_game_over() -> None:
    initial = {
        "roles": {2: CurrentRole.LOYALIST, 3: CurrentRole.REBEL},
        "log": (),
        "game_over": False,
    }

    def role_getter(state, player):
        return state["roles"][player]

    def resolve_one(state, player, role):
        return {
            **state,
            "log": state["log"]
            + (
                f"储君与胜利前置状态:{player}:{role.value}",
                f"胜负检查:{player}",
            ),
            "game_over": player == 2,
        }

    result = resolve_variant_sequential_deaths(
        (2, 3),
        initial,
        role_getter,
        resolve_one,
        lambda state: state["game_over"],
    )
    assert [step.player_id for step in result.processed_steps] == [2]
    assert result.processed_steps[0].role_current_at_death is CurrentRole.LOYALIST
    assert result.stopped_by_game_over
    assert not any(":3" in entry for entry in result.final_state["log"])
