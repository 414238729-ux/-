import pytest

from scripts.sgs_general_rules import (
    EIGHT_PLAYER_GENERAL_SLOTS,
    EXCLUDED_GENERAL_NAMES,
    GENERAL_CANDIDATE_SLOTS,
    GENERAL_RULE_RECORDS,
    MODE_GENERAL_SAMPLE_SIZES,
    ORIGINAL_EIGHT_GENERAL_SLOTS,
    TAUNT_LEVEL_ORDER,
    BellCard,
    CaoyingState,
    CaochunState,
    CaochunVersion,
    CardEventKind,
    CardLossEvent,
    CategoryCard,
    DianhuaTurnState,
    FaluMark,
    FuyinTurnState,
    JiliTurnState,
    LingrenPlayPhaseState,
    Suit,
    XingGanningState,
    ZhangQiyingState,
    ZhonghuiState,
    WangYuanjiState,
    apply_lingren_result_to_caoying_state,
    bell_can_be_used_when_hand_cards_forbidden,
    bell_can_be_zhangba_material,
    bell_can_pay_hand_only_cost,
    bell_counts_as_hand_card,
    build_wangyuanji_state,
    caochun_version_probabilities,
    choose_caochun_version,
    count_wangyuanji_lost_cards,
    delayed_tricks_last_in_first_out,
    evaluate_qianchong_equipment,
    expire_caoying_temporary_skills_at_turn_start,
    leave_bells_and_search_same_suit,
    materialize_eight_player_test_pool,
    sample_general_lineup,
    mingzhe_draw_opportunities,
    quanji_damage_opportunities,
    record_caochun_card_loss,
    restore_falu_marks,
    resolve_dianhua,
    resolve_fujian,
    resolve_fuyin_target,
    resolve_gouchen,
    resolve_houtu,
    resolve_jili_card_event,
    resolve_lingren,
    resolve_paiyi,
    resolve_shangjian,
    resolve_shanjia,
    resolve_sheque,
    resolve_temporary_jianxiong,
    resolve_temporary_xingshang,
    resolve_yuqing,
    resolve_ziwei,
    resolve_zuilun,
    simulate_jili_pre_effect_ranges,
    start_jili_independent_turn,
    store_bells,
    zhangqiying_elemental_target_modifier,
    resolve_zili,
)


def test_all_current_candidate_general_version_records_are_registered() -> None:
    assert len(GENERAL_RULE_RECORDS) == 14
    assert set(GENERAL_RULE_RECORDS) == {
        "shamoke",
        "zhugezhan",
        "jie_zhonghui",
        "caochun_old",
        "caochun_new",
        "wangyuanji",
        "caoying",
        "zhangqiying",
        "star_ganning",
        "xuyou",
        "qinghe_princess",
        "fuqian",
        "strategist_gongsunzan",
        "baoxin",
    }
    assert TAUNT_LEVEL_ORDER == ("B+", "A-", "A", "A+", "S-", "S", "S+")


def test_xuyou_formal_record_is_uniquely_three_hp() -> None:
    xuyou = GENERAL_RULE_RECORDS["xuyou"]
    assert (xuyou.base_hp, xuyou.base_max_hp) == (3, 3)
    assert xuyou.skill_names == ("成略", "恃才", "寸目")


def test_jili_checks_pre_effect_attack_range_and_counts_invalidated_use() -> None:
    first = resolve_jili_card_event(
        JiliTurnState(),
        event_kind=CardEventKind.USE,
        attack_range_before_card_effect=1,
    )
    assert first.triggered and first.draw_count == 1
    second = resolve_jili_card_event(
        first.state_after,
        event_kind=CardEventKind.USE,
        attack_range_before_card_effect=2,
    )
    assert second.triggered and second.draw_count == 2
    assert second.state_after.cards_used_or_responded_this_turn == 2


@pytest.mark.parametrize(
    "event_kind",
    [
        CardEventKind.DISCARD,
        CardEventKind.LOSE,
        CardEventKind.RECAST,
        CardEventKind.REVEAL,
        CardEventKind.PLACE_ON_GENERAL,
        CardEventKind.SKILL_ONLY,
    ],
)
def test_jili_does_not_count_non_use_or_response_events(event_kind) -> None:
    result = resolve_jili_card_event(
        JiliTurnState(),
        event_kind=event_kind,
        attack_range_before_card_effect=1,
    )
    assert not result.counted
    assert result.state_after.cards_used_or_responded_this_turn == 0


def test_jili_extra_turn_resets_and_weapon_chain_draws_one_to_five() -> None:
    assert start_jili_independent_turn().cards_used_or_responded_this_turn == 0
    assert simulate_jili_pre_effect_ranges([1, 2, 3, 4, 5]) == (1, 2, 3, 4, 5)


def test_zuilun_keeps_one_card_per_condition_and_tied_minimum_counts() -> None:
    result = resolve_zuilun(
        activate=True,
        caused_damage_this_turn=True,
        discarded_card_this_turn=False,
        hand_count=1,
        all_alive_hand_counts=[1, 1, 4],
    )
    assert result.satisfied_conditions == 3
    assert result.cards_kept == 3


def test_zuilun_zero_conditions_can_be_declined_or_stops_after_game_end() -> None:
    declined = resolve_zuilun(
        activate=False,
        caused_damage_this_turn=False,
        discarded_card_this_turn=True,
        hand_count=3,
        all_alive_hand_counts=[1, 2, 3],
    )
    assert not declined.activated
    resolved = resolve_zuilun(
        activate=True,
        caused_damage_this_turn=False,
        discarded_card_this_turn=True,
        hand_count=3,
        all_alive_hand_counts=[1, 2, 3],
        game_ended_after_self_loss=True,
    )
    assert resolved.event_order[:2] == ("诸葛瞻失去1点体力", "处理诸葛瞻濒死、死亡与胜负")
    assert resolved.other_hp_loss == 0


def test_fuyin_consumes_first_opportunity_even_when_condition_fails() -> None:
    first = resolve_fuyin_target(
        FuyinTurnState(),
        card_name="杀",
        defender_hand_count=3,
        user_hand_count_after_use=2,
    )
    assert first.opportunity_consumed and not first.card_invalidated
    second = resolve_fuyin_target(
        first.state_after,
        card_name="决斗",
        defender_hand_count=0,
        user_hand_count_after_use=5,
    )
    assert not second.opportunity_consumed and not second.card_invalidated


def test_fuyin_uses_attacker_hand_after_used_card_left_hand() -> None:
    result = resolve_fuyin_target(
        FuyinTurnState(),
        card_name="决斗",
        defender_hand_count=2,
        user_hand_count_after_use=2,
    )
    assert result.card_invalidated


def test_zhugezhan_turn_state_keeps_all_required_counters() -> None:
    state = FuyinTurnState(
        caused_damage_this_turn=True,
        discarded_card_this_turn=True,
    )
    result = resolve_fuyin_target(
        state,
        card_name="杀",
        defender_hand_count=1,
        user_hand_count_after_use=1,
    )
    assert result.state_after.fuyin_checked_this_turn
    assert result.state_after.caused_damage_this_turn
    assert result.state_after.discarded_card_this_turn


def test_quanji_gives_one_opportunity_per_damage_only_after_successful_rescue() -> None:
    assert quanji_damage_opportunities(2, rescued_if_dying=True) == 2
    assert quanji_damage_opportunities(2, rescued_if_dying=False) == 0


def test_zili_is_mandatory_at_three_quan_and_only_completes_once() -> None:
    state = ZhonghuiState(("q1", "q2", "q3"))
    result = resolve_zili(state, choice="摸2张牌")
    assert result.awakened and result.draw_count == 2 and result.max_hp_loss == 1
    assert not resolve_zili(result.state_after, choice="回复1点体力").awakened


def test_paiyi_draws_before_comparison_and_self_target_never_takes_damage() -> None:
    state = ZhonghuiState(("q1",), zili_awakened=True)
    enemy = resolve_paiyi(
        state,
        power_card_id="q1",
        target_hand_before_draw=1,
        zhonghui_hand_after_target_draw=2,
        target_is_self=False,
    )
    assert enemy.target_hand_after_draw == 3 and enemy.damage_to_target == 1
    self_result = resolve_paiyi(
        ZhonghuiState(("q1",), zili_awakened=True),
        power_card_id="q1",
        target_hand_before_draw=1,
        zhonghui_hand_after_target_draw=3,
        target_is_self=True,
    )
    assert self_result.damage_to_target == 0


def test_old_and_new_shanjia_have_distinct_legal_timing() -> None:
    old = resolve_shanjia(
        CaochunState(),
        version=CaochunVersion.OLD,
        timing="出牌阶段开始时",
        discarded_card_types=["装备牌", "装备牌", "装备牌"],
        equipment_lost_during_resolution=3,
    )
    assert old.virtual_slash_available and not old.play_phase_no_distance
    new = resolve_shanjia(
        CaochunState(),
        version=CaochunVersion.NEW,
        timing="出牌阶段内",
        discarded_card_types=["装备牌", "装备牌", "装备牌"],
        equipment_lost_during_resolution=3,
    )
    assert new.virtual_slash_available and new.play_phase_no_distance
    with pytest.raises(ValueError, match="旧版缮甲"):
        resolve_shanjia(
            CaochunState(),
            version="旧版",
            timing="出牌阶段内",
            discarded_card_types=["装备牌"] * 3,
        )


def test_shanjia_discard_count_is_locked_before_equipment_loss() -> None:
    result = resolve_shanjia(
        CaochunState(1),
        version="新版",
        timing="出牌阶段内",
        discarded_card_types=["装备牌", "装备牌"],
        equipment_lost_during_resolution=2,
    )
    assert result.locked_discard_count == 2
    assert result.state_after.equipment_zone_cards_lost_total == 3


def test_only_cards_leaving_equipment_zone_increment_caochun_growth() -> None:
    state = record_caochun_card_loss(CaochunState(), from_zone="手牌区", count=2)
    assert state.equipment_zone_cards_lost_total == 0
    state = record_caochun_card_loss(state, from_zone="装备区", count=2)
    assert state.equipment_zone_cards_lost_total == 2


def test_shanjia_at_three_loss_discards_zero_and_new_rewards_are_independent() -> None:
    zero = resolve_shanjia(
        CaochunState(3),
        version="新版",
        timing="出牌阶段内",
        discarded_card_types=[],
    )
    assert zero.locked_discard_count == 0
    assert zero.virtual_slash_available and zero.play_phase_no_distance
    basic_only = resolve_shanjia(
        CaochunState(2),
        version="新版",
        timing="出牌阶段内",
        discarded_card_types=["基本牌"],
    )
    assert not basic_only.virtual_slash_available and basic_only.play_phase_no_distance
    trick_only = resolve_shanjia(
        CaochunState(2),
        version="新版",
        timing="出牌阶段内",
        discarded_card_types=["锦囊牌"],
    )
    assert trick_only.virtual_slash_available and not trick_only.play_phase_no_distance
    assert not zero.virtual_slash_uses_normal_quota


def test_caochun_is_one_slot_with_equal_version_rule_and_reproducibility() -> None:
    assert EIGHT_PLAYER_GENERAL_SLOTS.count("曹纯") == 1
    assert caochun_version_probabilities() == {
        CaochunVersion.OLD: 0.5,
        CaochunVersion.NEW: 0.5,
    }
    assert choose_caochun_version(7) == choose_caochun_version(7)
    pool = materialize_eight_player_test_pool(9)
    assert len(pool) == 8 and len(set(pool)) == 8
    assert sum(name in {"旧版曹纯", "新版曹纯"} for name in pool) <= 1


def test_current_candidate_pool_and_mode_sampling_are_without_replacement() -> None:
    assert len(ORIGINAL_EIGHT_GENERAL_SLOTS) == 8
    assert len(GENERAL_CANDIDATE_SLOTS) == 13
    assert EIGHT_PLAYER_GENERAL_SLOTS == GENERAL_CANDIDATE_SLOTS
    assert MODE_GENERAL_SAMPLE_SIZES == {"2v2": 4, "斗地主": 3, "八人军争身份": 8}
    for mode, size in MODE_GENERAL_SAMPLE_SIZES.items():
        lineup = sample_general_lineup(mode, seed=20260727)
        assert len(lineup) == size
        assert len(set(lineup)) == size
        assert not set(lineup) & EXCLUDED_GENERAL_NAMES
        assert sum(name in {"旧版曹纯", "新版曹纯"} for name in lineup) <= 1
        assert lineup == sample_general_lineup(mode, seed=20260727)


def test_caochun_version_is_chosen_only_when_single_slot_is_selected() -> None:
    for seed in range(200):
        lineup = sample_general_lineup("2v2", seed)
        versions = [name for name in lineup if name in {"旧版曹纯", "新版曹纯"}]
        assert len(versions) <= 1
        assert "曹纯" not in lineup


def test_qianchong_empty_or_mixed_equipment_can_choose_type() -> None:
    empty = evaluate_qianchong_equipment([])
    assert not empty.has_weimu and not empty.has_mingzhe and empty.can_choose_temporary_card_type
    mixed = evaluate_qianchong_equipment(["红", "黑"])
    assert mixed.can_choose_temporary_card_type
    assert evaluate_qianchong_equipment(["黑", "黑"]).has_weimu
    assert evaluate_qianchong_equipment(["红", "红"]).has_mingzhe


def test_wangyuanji_state_keeps_loss_temporary_type_and_granted_skills() -> None:
    state = build_wangyuanji_state(
        equipment_colors=["红", "黑"],
        cards_lost_this_turn=2,
        temporary_qianchong_card_type="锦囊牌",
    )
    assert isinstance(state, WangYuanjiState)
    assert state.cards_lost_this_turn == 2
    assert state.temporary_qianchong_card_type == "锦囊牌"
    assert not state.has_weimu and not state.has_mingzhe
    with pytest.raises(ValueError, match="不满足选择"):
        build_wangyuanji_state(
            equipment_colors=["黑"],
            temporary_qianchong_card_type="基本牌",
        )


def test_mingzhe_counts_each_red_use_response_or_discard_not_acquisition() -> None:
    events = [
        CardLossEvent("a", "手牌区", "弃牌堆", "打出", "红", True),
        CardLossEvent("b", "手牌区", "弃牌堆", "弃置", "红", True),
        CardLossEvent("c", "手牌区", "其他角色手牌", "被获得", "红", True),
        CardLossEvent("d", "手牌区", "弃牌堆", "使用", "黑", True),
    ]
    assert mingzhe_draw_opportunities(events) == 2


def test_shangjian_counts_entity_losses_but_not_normal_equipping() -> None:
    events = [
        CardLossEvent("a", "手牌区", "弃牌堆", "弃置"),
        CardLossEvent("b", "装备区", "其他角色手牌", "被获得"),
        CardLossEvent("c", "手牌区", "自己的装备区", "使用装备"),
        CardLossEvent("d", "判定区", "弃牌堆", "置入弃牌堆"),
    ]
    assert count_wangyuanji_lost_cards(events) == 2
    assert resolve_shangjian(2, 2) == 2
    assert resolve_shangjian(3, 2) == 0


def test_lingren_zero_hand_all_no_guesses_hit_and_rewards_are_immediate() -> None:
    result = resolve_lingren(
        LingrenPlayPhaseState(),
        guesses_has_type={"基本牌": False, "锦囊牌": False, "装备牌": False},
        actual_hand_types=[],
    )
    assert result.correct_guesses == 3
    assert result.damage_bonus == 1 and result.draw_count == 2
    assert result.grants_jianxiong and result.grants_xingshang
    assert result.temporary_skill_expiry == "下回合开始"

    state = apply_lingren_result_to_caoying_state(
        CaoyingState(known_hand_information={"目标": ()}),
        result,
    )
    assert state.lingren_used_this_play_phase
    assert state.temporary_jianxiong and state.temporary_xingshang
    assert state.temporary_skill_expiry == "下回合开始"
    assert state.known_hand_information == {"目标": ()}


def test_lingren_once_per_independent_play_phase_and_extra_phase_resets() -> None:
    result = resolve_lingren(
        LingrenPlayPhaseState(),
        guesses_has_type={"基本牌": True, "锦囊牌": False, "装备牌": False},
        actual_hand_types=["基本牌"],
    )
    with pytest.raises(ValueError, match="已经发动过凌人"):
        resolve_lingren(
            result.state_after,
            guesses_has_type={"基本牌": True, "锦囊牌": False, "装备牌": False},
            actual_hand_types=["基本牌"],
        )
    reset = resolve_lingren(
        LingrenPlayPhaseState(),
        guesses_has_type={"基本牌": True, "锦囊牌": False, "装备牌": False},
        actual_hand_types=["基本牌"],
    )
    assert reset.correct_guesses == 3


def test_caoying_temporary_skills_expire_at_any_next_turn_start() -> None:
    assert expire_caoying_temporary_skills_at_turn_start(
        has_temporary_jianxiong=True,
        has_temporary_xingshang=True,
    ) == (False, False)


def test_temporary_jianxiong_requires_entities_and_xingshang_excludes_judgment() -> None:
    assert resolve_temporary_jianxiong(None) == ()
    assert resolve_temporary_jianxiong(["实体杀"]) == ("实体杀",)
    assert resolve_temporary_xingshang(
        dead_hand_cards=["手1"],
        dead_equipment_cards=["装1"],
        dead_judgment_cards=["判1"],
    ) == ("手1", "装1")


def test_fujian_requires_every_alive_character_to_have_hand_and_is_reproducible() -> None:
    assert not resolve_fujian(
        caoying_player_id="曹婴",
        alive_hands={"曹婴": ["a"], "敌人": []},
        seed=1,
    ).triggered
    hands = {"曹婴": ["a"], "敌1": ["b", "c"], "敌2": ["d", "e"]}
    first = resolve_fujian(caoying_player_id="曹婴", alive_hands=hands, seed=5)
    second = resolve_fujian(caoying_player_id="曹婴", alive_hands=hands, seed=5)
    assert first == second and first.triggered
    assert len(first.viewed_card_ids) == 1


def test_falu_starts_with_four_unique_marks_and_only_discard_restores() -> None:
    full = ZhangQiyingState()
    assert full.marks == frozenset(FaluMark)
    assert full.ziwei_mark and full.houtu_mark
    assert full.yuqing_mark and full.gouchen_mark
    missing = ZhangQiyingState(frozenset({FaluMark.ZIWEI}))
    restored = restore_falu_marks(
        missing,
        suits=["♥", "♥", "♦"],
        move_reason="弃置进入弃牌堆",
    )
    assert restored.marks == {FaluMark.ZIWEI, FaluMark.YUQING, FaluMark.GOUCHEN}
    unchanged = restore_falu_marks(
        missing,
        suits=["♣"],
        move_reason="装备替换后置入弃牌堆",
    )
    assert unchanged == missing


def test_ziwei_is_not_final_lock_and_houtu_requires_hand_while_dying() -> None:
    ziwei = resolve_ziwei(ZhangQiyingState(), choose_suit="♠")
    assert ziwei.judgment_rank == "5" and not ziwei.locks_final_judgment
    with pytest.raises(ValueError, match="至少一张手牌"):
        resolve_houtu(ZhangQiyingState(), is_dying=True, hand_count=0)
    after = resolve_houtu(ZhangQiyingState(), is_dying=True, hand_count=1)
    assert FaluMark.HOUTU not in after.marks


def test_yuqing_black_judgment_adds_one_damage() -> None:
    result = resolve_yuqing(ZhangQiyingState(), base_damage=1, judgment_color="黑")
    assert result.final_damage == 2
    assert FaluMark.YUQING not in result.state_after.marks


def test_gouchen_draws_one_from_each_nonempty_category_pool() -> None:
    candidates = [
        CategoryCard("b1", "基本牌", "牌堆"),
        CategoryCard("t1", "锦囊牌", "弃牌堆"),
        CategoryCard("e1", "装备牌", "牌堆"),
    ]
    result = resolve_gouchen(
        ZhangQiyingState(),
        elemental_damage_received=True,
        rescued_if_dying=True,
        candidates=candidates,
        seed=3,
    )
    assert {card.category for card in result.obtained_cards} == {"基本牌", "锦囊牌", "装备牌"}
    partial = resolve_gouchen(
        ZhangQiyingState(),
        elemental_damage_received=True,
        rescued_if_dying=True,
        candidates=[CategoryCard("b1", "基本牌", "牌堆")],
        seed=3,
    )
    assert len(partial.obtained_cards) == 1


def test_dianhua_can_be_used_in_preparation_and_end_and_respects_lifo_judgment() -> None:
    first = resolve_dianhua(
        DianhuaTurnState(),
        phase="准备阶段",
        mark_count=2,
        current_top_cards=["a", "b"],
        reordered_top_cards=["b", "a"],
    )
    second = resolve_dianhua(
        first.state_after,
        phase="结束阶段",
        mark_count=2,
        current_top_cards=["c", "d"],
        reordered_top_cards=["c", "d"],
    )
    assert second.state_after.preparation_used and second.state_after.ending_used
    assert delayed_tricks_last_in_first_out(["先进入", "后进入"]) == ("后进入", "先进入")


def test_nonlethal_elemental_damage_to_zhangqiying_is_strongly_downgraded() -> None:
    assert zhangqiying_elemental_target_modifier(lethal=False) < -2
    assert zhangqiying_elemental_target_modifier(lethal=True) == 0


def _bell(card_id: str, suit: Suit, name: str = "牌") -> BellCard:
    return BellCard(card_id, name, suit, "基本牌")


def test_bells_have_one_public_slot_per_suit_and_are_not_normal_hand() -> None:
    state = store_bells(XingGanningState(), [_bell("s1", Suit.SPADE)])
    with pytest.raises(ValueError, match="同花色铃"):
        store_bells(state, [_bell("s2", Suit.SPADE)])
    assert not bell_counts_as_hand_card()
    assert not bell_can_pay_hand_only_cost()
    assert bell_can_be_used_when_hand_cards_forbidden()
    assert bell_can_be_zhangba_material()


def test_each_leaving_bell_searches_current_draw_pile_without_reshuffle() -> None:
    state = store_bells(
        XingGanningState(),
        [_bell("bell-s", Suit.SPADE), _bell("bell-h", Suit.HEART)],
    )
    pile = [_bell("draw-s", Suit.SPADE), _bell("draw-h", Suit.HEART)]
    result = leave_bells_and_search_same_suit(
        state,
        leaving_suits=[Suit.SPADE, Suit.HEART],
        draw_pile=pile,
        owner_alive=True,
        seed=2,
    )
    assert {card.card_id for card in result.obtained_cards} == {"draw-s", "draw-h"}
    assert result.draw_pile_after == ()


def test_bell_search_failure_does_not_reshuffle_and_death_cleanup_draws_nothing() -> None:
    state = store_bells(XingGanningState(), [_bell("bell-s", Suit.SPADE)])
    no_match = leave_bells_and_search_same_suit(
        state,
        leaving_suits=[Suit.SPADE],
        draw_pile=[_bell("heart", Suit.HEART)],
        owner_alive=True,
        seed=2,
    )
    assert no_match.obtained_cards == ()
    assert len(no_match.draw_pile_after) == 1
    dead = leave_bells_and_search_same_suit(
        state,
        leaving_suits=[Suit.SPADE],
        draw_pile=[_bell("spade", Suit.SPADE)],
        owner_alive=False,
        seed=2,
    )
    assert dead.obtained_cards == ()


@pytest.mark.parametrize("slash_kind", ["杀", "火杀", "雷杀"])
def test_sheque_requires_legal_slash_and_ignores_distance_and_armor(slash_kind) -> None:
    result = resolve_sheque(
        target_is_other=True,
        target_has_equipment=True,
        slash_kind=slash_kind,
    )
    assert result.can_use
    assert result.ignores_distance and result.ignores_armor
    assert not result.consumes_play_phase_slash_quota
    assert not result.changes_attack_range


def test_sheque_can_trigger_in_different_characters_preparation_stages() -> None:
    first = resolve_sheque(
        target_is_other=True,
        target_has_equipment=True,
        slash_kind="杀",
    )
    second = resolve_sheque(
        target_is_other=True,
        target_has_equipment=True,
        slash_kind="雷杀",
    )
    assert first.can_use and second.can_use
    assert not resolve_sheque(
        target_is_other=True,
        target_has_equipment=False,
        slash_kind="杀",
    ).can_use
    assert not resolve_sheque(
        target_is_other=True,
        target_has_equipment=True,
        slash_kind=None,
    ).can_use
