"""V2.4 四名增量武将的 56 项确定性规则测试。"""

from __future__ import annotations

import pytest

from scripts.sgs_card_rules import (
    ChainParticipant,
    DamageEvent,
    DamageType,
    RecipientDamageOutcome,
    resolve_chain_damage,
)
from scripts.sgs_incremental_mechanics import EffectRequirements, PendingGainCard, effect_requirements_satisfied
from scripts.sgs_v24_generals import (
    BirdMarkState,
    CardZone,
    JiejieRoundState,
    LulianTarget,
    LulianUseContext,
    NiguParticipant,
    NiguState,
    ShenLubuReworkState,
    ShenfenDamageOutcome,
    ShenfenParticipant,
    V24Card,
    WumouAction,
    WumouTrick,
    activate_wuqian,
    apply_nigu_damage_charge,
    clear_bird_when_holder_leaves,
    convert_wumou_trick,
    gain_rage_from_damage,
    jiejie_use_permission,
    legal_chengshi_targets,
    qingshi_trigger_count,
    remove_wuqian_target,
    resolve_bird_gain_event,
    resolve_jiejie,
    resolve_lulian,
    resolve_nigu,
    resolve_qingshi,
    resolve_shenfen,
    resolve_wufei_after_damage,
    resolve_wufei_damage_context,
    resolve_wuqian_damage_card_completion,
    resolve_wuqian_end_phase,
    resolve_yichong,
    start_nigu_play_phase,
    start_shen_lubu_play_phase,
)


def _card(
    card_id: str,
    card_name: str = "测试牌",
    suit: str | None = "♠",
    zone: CardZone = CardZone.HAND,
    *,
    category: str | None = None,
    damage: bool = False,
) -> V24Card:
    return V24Card(card_id, card_name, suit, zone, category, damage)


# ---------------------------------------------------------------------------
# 势·孙綝：11 项


def test_sunchen_01_nigu_cannot_discard_zero_cards() -> None:
    with pytest.raises(ValueError, match="至少弃置一张"):
        resolve_nigu(
            NiguState(),
            owner_id="孙綝",
            discarded_cards=(),
            attack_range_after_discard=1,
            participants=(),
        )


def test_sunchen_02_nigu_discarded_suits_must_be_distinct() -> None:
    with pytest.raises(ValueError, match="花色必须两两不同"):
        resolve_nigu(
            NiguState(),
            owner_id="孙綝",
            discarded_cards=(_card("a", suit="♠"), _card("b", suit="黑桃")),
            attack_range_after_discard=1,
            participants=(),
        )


def test_sunchen_03_nigu_only_accepts_hand_or_equipment_cards() -> None:
    with pytest.raises(ValueError, match="手牌区或装备区"):
        resolve_nigu(
            NiguState(),
            owner_id="孙綝",
            discarded_cards=(_card("j", zone=CardZone.JUDGMENT),),
            attack_range_after_discard=1,
            participants=(),
        )


def test_sunchen_04_nigu_uses_attack_range_after_weapon_is_discarded() -> None:
    result = resolve_nigu(
        NiguState(),
        owner_id="孙綝",
        discarded_cards=(_card("weapon", "武器", "♦", CardZone.EQUIPMENT),),
        attack_range_after_discard=1,
        participants=(
            NiguParticipant("近处", 1, True, True, "near-card"),
            NiguParticipant("远处", 2, True, False),
        ),
    )
    assert result.attack_range_used == 1
    assert result.participants == ("近处",)
    assert result.cards_given_face_down == ("near-card",)


def test_sunchen_05_nigu_cardless_participant_is_a_non_giver() -> None:
    result = resolve_nigu(
        NiguState(),
        owner_id="孙綝",
        discarded_cards=(_card("cost"),),
        attack_range_after_discard=1,
        participants=(NiguParticipant("空手目标", 1, False, False),),
    )
    assert result.non_giver_ids == ("空手目标",)
    assert result.state_after.damage_bonus_charges == 1


def test_sunchen_06_nigu_giver_does_not_create_damage_charge() -> None:
    result = resolve_nigu(
        NiguState(),
        owner_id="孙綝",
        discarded_cards=(_card("cost"),),
        attack_range_after_discard=1,
        participants=(NiguParticipant("交牌目标", 1, True, True, "given"),),
    )
    assert result.non_giver_ids == ()
    assert result.cards_given_face_down == ("given",)
    assert result.state_after.damage_bonus_charges == 0
    with pytest.raises(ValueError, match="每个出牌阶段限一次"):
        resolve_nigu(
            result.state_after,
            owner_id="孙綝",
            discarded_cards=(_card("again"),),
            attack_range_after_discard=1,
            participants=(),
        )


def test_sunchen_07_prevented_damage_still_consumes_nigu_charge() -> None:
    result = apply_nigu_damage_charge(
        NiguState(True, 1),
        base_damage=2,
        prevented=True,
    )
    assert result.actual_damage == 0
    assert result.charge_consumed is True
    assert result.state_after.damage_bonus_charges == 0


def test_sunchen_08_lulian_accepts_last_equipment_and_off_turn_peach_or_wine_use() -> None:
    target = LulianTarget("目标", hp=2, equipment_count=0)
    for category in ("装备牌", "基本牌-桃", "基本牌-酒"):
        result = resolve_lulian(
            LulianUseContext(category=category, same_category_hand_count_after=0),
            owner_hp=3,
            owner_equipment_count=0,
            original_targets=(target,),
            all_alive_characters=(LulianTarget("孙綝", 3, 0), target),
        )
        assert result.triggered is True
        assert result.chengshi_granted is True


def test_sunchen_09_lulian_rejects_non_hand_virtual_played_or_targetless_cases() -> None:
    target = LulianTarget("目标", hp=2, equipment_count=0)
    invalid_contexts = (
        LulianUseContext("基本牌", pure_virtual=True),
        LulianUseContext("基本牌", from_special_zone=True),
        LulianUseContext("基本牌", used_other_players_hand=True),
        LulianUseContext("基本牌", only_played=True),
    )
    for context in invalid_contexts:
        result = resolve_lulian(
            context,
            owner_hp=3,
            owner_equipment_count=0,
            original_targets=(target,),
            all_alive_characters=(target,),
        )
        assert result.triggered is False
    targetless = resolve_lulian(
        LulianUseContext("基本牌"),
        owner_hp=3,
        owner_equipment_count=0,
        original_targets=(),
        all_alive_characters=(target,),
    )
    assert targetless.triggered is False


def test_sunchen_10_lulian_conditions_may_be_satisfied_by_different_surviving_targets() -> None:
    hp_target = LulianTarget("低体力", hp=2, equipment_count=3)
    equip_target = LulianTarget("少装备", hp=4, equipment_count=0)
    dead_target = LulianTarget("已死亡", hp=1, equipment_count=0, alive=False)
    result = resolve_lulian(
        LulianUseContext("锦囊牌"),
        owner_hp=3,
        owner_equipment_count=1,
        original_targets=(hp_target, equip_target, dead_target),
        all_alive_characters=(LulianTarget("孙綝", 3, 1), hp_target, equip_target, dead_target),
    )
    assert result.surviving_target_ids == ("低体力", "少装备")
    assert result.hp_condition_met is True
    assert result.equipment_condition_met is True
    assert all(target.chained for target in result.targets_after)
    assert result.draw_count == 1
    assert result.chengshi_granted is True


def test_sunchen_11_chengshi_and_chain_damage_do_not_cumulatively_raise_chain_base() -> None:
    assert legal_chengshi_targets(
        (LulianTarget("孙綝", 3, 0), LulianTarget("甲", 1, 0), LulianTarget("乙", 2, 0))
    ) == ("孙綝", "乙")
    assert legal_chengshi_targets(
        (LulianTarget("孙綝", 2, 0), LulianTarget("甲", 2, 0))
    ) == ()

    charges = NiguState(True, 2)

    def resolve_recipient(_target, base, _damage_type, _source, _state):
        nonlocal charges
        modified = apply_nigu_damage_charge(charges, base_damage=base)
        charges = modified.state_after
        # 逆固只修正该独立伤害，不把 +1 写回后续铁索传导基础。
        return RecipientDamageOutcome(actual_damage=modified.actual_damage)

    chain = resolve_chain_damage(
        (
            ChainParticipant("甲", 1),
            ChainParticipant("乙", 2),
            ChainParticipant("丙", 3),
        ),
        DamageEvent("甲", 2, DamageType.FIRE, "孙綝"),
        player_count=3,
        current_turn_seat=1,
        recipient_resolver=resolve_recipient,
    )
    assert [step.actual_damage for step in chain.steps] == [2, 3, 3]
    assert charges.damage_bonus_charges == 0
    assert start_nigu_play_phase(NiguState(True, 0)).used_this_play_phase is False


# ---------------------------------------------------------------------------
# 势·辛宪英：11 项


def test_xinxianying_01_qingshi_triggers_once_per_independent_damage_after_rescue() -> None:
    assert qingshi_trigger_count(actual_damage=4, survived_after_rescue=True) == 1
    assert qingshi_trigger_count(actual_damage=4, survived_after_rescue=False) == 0
    assert qingshi_trigger_count(actual_damage=0, survived_after_rescue=True) == 0


def test_xinxianying_02_qingshi_self_target_draws_two() -> None:
    result = resolve_qingshi(owner_id="辛宪英", target_id="辛宪英", same_camp=True)
    assert (result.draw_by_owner, result.draw_by_target) == (2, 0)
    assert result.same_camp_result_public is True


def test_xinxianying_03_qingshi_same_camp_each_draws_one() -> None:
    result = resolve_qingshi(owner_id="辛宪英", target_id="队友", same_camp=True)
    assert (result.draw_by_owner, result.draw_by_target) == (1, 1)
    assert result.discarded_by_owner == result.discarded_by_target == ()


def test_xinxianying_04_qingshi_different_camp_discards_only_available_area_cards() -> None:
    target_cards = (
        _card("equip", zone=CardZone.EQUIPMENT),
        _card("judge", zone=CardZone.JUDGMENT),
    )
    result = resolve_qingshi(
        owner_id="辛宪英",
        target_id="敌方",
        same_camp=False,
        owner_cards=(),
        target_cards=target_cards,
        target_discard_card_id="equip",
    )
    assert result.discarded_by_owner == ()
    assert result.discarded_by_target == ("equip",)
    assert result.same_camp_result_public is False


def test_xinxianying_05_jiejie_requires_at_least_one_hand_card() -> None:
    with pytest.raises(ValueError, match="没有手牌"):
        resolve_jiejie(
            JiejieRoundState(),
            current_player_id="甲",
            play_phase_id="甲-1",
            viewed_hand=(),
            selection="取消",
        )


def test_xinxianying_06_jiejie_is_once_per_independent_play_phase() -> None:
    first = resolve_jiejie(
        JiejieRoundState(),
        current_player_id="甲",
        play_phase_id="甲-1",
        viewed_hand=(_card("a"),),
        selection="取消",
    )
    with pytest.raises(ValueError, match="独立出牌阶段限发动一次"):
        resolve_jiejie(
            first.state_after,
            current_player_id="甲",
            play_phase_id="甲-1",
            viewed_hand=(_card("a"),),
            selection="取消",
        )


def test_xinxianying_07_jiejie_cancel_still_records_original_suits_and_forces_qingshi() -> None:
    result = resolve_jiejie(
        JiejieRoundState(),
        current_player_id="甲",
        play_phase_id="甲-1",
        viewed_hand=(_card("a", suit="♠"), _card("b", suit="♥")),
        selection="取消",
    )
    assert result.original_suit_count == 2
    assert result.forced_qingshi is True
    assert result.forced_qingshi_target_id == "甲"
    assert result.state_after.view_records[-1].selection.value == "取消"


def test_xinxianying_08_existing_suit_discards_other_suits_and_only_ignores_use_count() -> None:
    result = resolve_jiejie(
        JiejieRoundState(),
        current_player_id="甲",
        play_phase_id="甲-1",
        viewed_hand=(_card("s1", suit="♠"), _card("h1", suit="♥")),
        selection="♠",
    )
    assert result.discarded_card_ids == ("h1",)
    assert [card.card_id for card in result.remaining_hand] == ["s1"]
    permission = jiejie_use_permission(unlimited_suit=result.unlimited_suit, actual_used_card_suit="黑桃")
    assert permission.ignores_card_use_limit is True
    assert permission.ignores_timing is False
    assert permission.ignores_target_rule is False
    assert permission.ignores_distance is False
    assert permission.ignores_other_conditions is False


def test_xinxianying_09_missing_suit_searches_only_current_draw_pile_reproducibly() -> None:
    pile = (
        _card("club", suit="♣", zone=CardZone.DRAW_PILE),
        _card("diamond", suit="♦", zone=CardZone.DRAW_PILE),
    )
    kwargs = dict(
        current_player_id="甲",
        play_phase_id="甲-1",
        viewed_hand=(_card("spade", suit="♠"),),
        selection="♦",
        draw_pile=pile,
        seed=7,
    )
    first = resolve_jiejie(JiejieRoundState(), **kwargs)
    second = resolve_jiejie(JiejieRoundState(), **kwargs)
    assert first.gained_card == second.gained_card
    assert first.gained_card is not None and first.gained_card.card_id == "diamond"
    assert first.gained_card.zone is CardZone.HAND
    assert [card.card_id for card in first.remaining_draw_pile] == ["club"]


def test_xinxianying_10_jiejie_requires_strictly_higher_suit_count_not_a_tie() -> None:
    first = resolve_jiejie(
        JiejieRoundState(),
        current_player_id="甲",
        play_phase_id="甲-1",
        viewed_hand=(_card("s", suit="♠"), _card("h", suit="♥")),
        selection="取消",
    )
    tie = resolve_jiejie(
        first.state_after,
        current_player_id="乙",
        play_phase_id="乙-1",
        viewed_hand=(_card("c", suit="♣"), _card("d", suit="♦")),
        selection="取消",
    )
    assert first.forced_qingshi is True
    assert tie.original_suit_count == 2
    assert tie.forced_qingshi is False


def test_xinxianying_11_jiejie_forced_qingshi_has_two_per_round_quota_only() -> None:
    state = JiejieRoundState()
    for player, phase, hand in (
        ("甲", "p1", (_card("a", suit="♠"),)),
        ("乙", "p2", (_card("b", suit="♠"), _card("c", suit="♥"))),
    ):
        result = resolve_jiejie(
            state,
            current_player_id=player,
            play_phase_id=phase,
            viewed_hand=hand,
            selection="取消",
        )
        assert result.forced_qingshi is True
        state = result.state_after
    third = resolve_jiejie(
        state,
        current_player_id="丙",
        play_phase_id="p3",
        viewed_hand=(
            _card("d", suit="♠"),
            _card("e", suit="♥"),
            _card("f", suit="♣"),
        ),
        selection="取消",
    )
    assert third.original_suit_count == 3
    assert third.forced_qingshi is False
    assert third.state_after.forced_qingshi_used == 2
    # 普通伤害触发清识不读取、也不消耗诫节的轮次额度。
    assert qingshi_trigger_count(actual_damage=1, survived_after_rescue=True) == 1
    assert state.forced_qingshi_used == 2


# ---------------------------------------------------------------------------
# SP郭女王：15 项


def test_guonuwang_01_yichong_creates_bird_even_without_matching_cards() -> None:
    result = resolve_yichong(
        guo_nuwang_id="郭女王",
        target_id="甲",
        designated_suit="♥",
        target_hand=(_card("s", suit="♠"),),
    )
    assert result.equipment_cards_gained == ()
    assert result.random_hand_card_gained is None
    assert result.bird_state.holder_id == "甲"
    assert result.bird_state.designated_suit == "♥"


def test_guonuwang_02_yichong_gains_all_matching_equipment() -> None:
    equipment = (
        _card("h-e1", suit="♥", zone=CardZone.EQUIPMENT),
        _card("s-e", suit="♠", zone=CardZone.EQUIPMENT),
        _card("h-e2", suit="♥", zone=CardZone.EQUIPMENT),
    )
    result = resolve_yichong(
        guo_nuwang_id="郭女王",
        target_id="甲",
        designated_suit="红桃",
        target_equipment=equipment,
    )
    assert [card.card_id for card in result.equipment_cards_gained] == ["h-e1", "h-e2"]
    assert [card.card_id for card in result.target_equipment_after] == ["s-e"]
    assert all(card.zone is CardZone.HAND for card in result.equipment_cards_gained)


def test_guonuwang_03_yichong_randomly_gains_exactly_one_matching_hand_card_reproducibly() -> None:
    hand = (_card("h1", suit="♥"), _card("h2", suit="♥"), _card("s", suit="♠"))
    first = resolve_yichong(
        guo_nuwang_id="郭女王",
        target_id="甲",
        designated_suit="♥",
        target_hand=hand,
        seed=19,
    )
    second = resolve_yichong(
        guo_nuwang_id="郭女王",
        target_id="甲",
        designated_suit="♥",
        target_hand=hand,
        seed=19,
    )
    assert first.random_hand_card_gained == second.random_hand_card_gained
    assert first.random_hand_card_gained is not None
    assert len(first.target_hand_after) == 2


def test_guonuwang_04_yichong_transfers_the_single_previous_bird() -> None:
    old = BirdMarkState("郭女王", "旧目标", "♠", "下回合开始")
    result = resolve_yichong(
        guo_nuwang_id="郭女王",
        target_id="新目标",
        designated_suit="♦",
        previous_bird=old,
    )
    assert result.previous_bird_transferred is True
    assert result.bird_state.holder_id == "新目标"
    assert result.bird_state.designated_suit == "♦"


def test_guonuwang_05_bird_intercepts_the_earliest_matching_card_in_acquisition_order() -> None:
    state = BirdMarkState("郭女王", "甲", "♥", "下回合开始")
    result = resolve_bird_gain_event(
        state,
        original_recipient_id="甲",
        pending_cards=(
            PendingGainCard("s", "牌S", "♠"),
            PendingGainCard("h1", "牌H1", "♥"),
            PendingGainCard("h2", "牌H2", "♥"),
        ),
        actor_order=("郭女王", "甲"),
    )
    assert result.intercepted_card_id == "h1"
    entries = {entry.card_id: entry.recipient_id for entry in result.actual_zone_entries}
    assert entries == {"h1": "郭女王", "s": "甲", "h2": "甲"}


def test_guonuwang_06_original_gain_effect_sees_card_when_it_resolves_before_bird() -> None:
    result = resolve_bird_gain_event(
        BirdMarkState("郭女王", "甲", "♥", "下回合开始"),
        original_recipient_id="甲",
        pending_cards=(PendingGainCard("h", "红桃牌", "♥"),),
        actor_order=("甲", "郭女王"),
    )
    assert result.effect_order == ("original_recipient_gain_time", "yichong_interception")
    assert result.original_gain_time_seen_card_ids == ("h",)


def test_guonuwang_07_bird_first_removes_card_before_original_gain_effect_observes_it() -> None:
    result = resolve_bird_gain_event(
        BirdMarkState("郭女王", "甲", "♥", "下回合开始"),
        original_recipient_id="甲",
        pending_cards=(PendingGainCard("h", "红桃牌", "♥"),),
        actor_order=("郭女王", "甲"),
    )
    assert result.effect_order == ("yichong_interception", "original_recipient_gain_time")
    assert result.original_gain_time_seen_card_ids == ()
    assert result.actual_zone_entries[0].redirected is True


def test_guonuwang_08_bird_remains_after_its_one_pending_interception_is_consumed() -> None:
    state = BirdMarkState("郭女王", "甲", "♥", "下回合开始")
    result = resolve_bird_gain_event(
        state,
        original_recipient_id="甲",
        pending_cards=(PendingGainCard("h", "红桃牌", "♥"),),
        actor_order=("郭女王", "甲"),
    )
    assert result.bird_state_after.holder_id == "甲"
    assert result.bird_state_after.interception_pending is False
    second = resolve_bird_gain_event(
        result.bird_state_after,
        original_recipient_id="甲",
        pending_cards=(PendingGainCard("h2", "另一红桃牌", "♥"),),
        actor_order=("郭女王", "甲"),
    )
    assert second.intercepted_card_id is None
    assert second.actual_zone_entries[0].recipient_id == "甲"


def test_guonuwang_09_bird_is_cleared_only_when_its_holder_leaves() -> None:
    state = BirdMarkState("郭女王", "甲", "♥", "下回合开始")
    assert clear_bird_when_holder_leaves(state, leaving_player_id="乙") == state
    assert clear_bird_when_holder_leaves(state, leaving_player_id="甲") is None


def test_guonuwang_10_wufei_replaces_slash_damage_source_but_not_card_user() -> None:
    state = BirdMarkState("郭女王", "雀持有者", "♥", "下回合开始", False)
    context = resolve_wufei_damage_context(
        guo_nuwang_id="郭女王",
        bird_state=state,
        bird_holder_alive=True,
        damage_card_name="火杀",
        damage_target_id="目标",
        card_type="基本牌",
    )
    assert context.card_user_id == "郭女王"
    assert context.damage_source_id == "雀持有者"
    assert context.source_replaced is True


def test_guonuwang_11_wufei_replaces_normal_damage_trick_source() -> None:
    context = resolve_wufei_damage_context(
        guo_nuwang_id="郭女王",
        bird_state=BirdMarkState("郭女王", "雀持有者", "♣", "下回合开始"),
        bird_holder_alive=True,
        damage_card_name="决斗",
        damage_target_id="目标",
        card_type="伤害类普通锦囊",
    )
    assert context.damage_source_id == "雀持有者"
    assert context.card_user_id == "郭女王"


def test_guonuwang_12_lightning_is_excluded_from_wufei_source_replacement() -> None:
    context = resolve_wufei_damage_context(
        guo_nuwang_id="郭女王",
        bird_state=BirdMarkState("郭女王", "雀持有者", "♠", "下回合开始"),
        bird_holder_alive=True,
        damage_card_name="闪电",
        damage_target_id="目标",
        card_type="延时锦囊",
    )
    assert context.damage_source_id == "郭女王"
    assert context.source_replaced is False


def test_guonuwang_13_user_source_equipment_and_kill_ownership_remain_independent() -> None:
    context = resolve_wufei_damage_context(
        guo_nuwang_id="郭女王",
        bird_state=BirdMarkState("郭女王", "雀持有者", "♥", "下回合开始"),
        bird_holder_alive=True,
        damage_card_name="杀",
        damage_target_id="目标",
        card_type="基本牌",
    )
    assert effect_requirements_satisfied("郭女王", context, EffectRequirements(requires_card_user=True))
    assert effect_requirements_satisfied("雀持有者", context, EffectRequirements(requires_damage_source=True))
    assert effect_requirements_satisfied("郭女王", context, EffectRequirements(requires_equipment_owner=True))
    assert not effect_requirements_satisfied(
        "郭女王", context, EffectRequirements(requires_same_user_and_source=True)
    )
    assert context.kill_owner_id == "雀持有者"


def test_guonuwang_14_wufei_rechecks_each_damage_and_reverts_after_bird_holder_dies() -> None:
    state = BirdMarkState("郭女王", "雀持有者", "♥", "下回合开始")
    first = resolve_wufei_damage_context(
        guo_nuwang_id="郭女王",
        bird_state=state,
        bird_holder_alive=True,
        damage_card_name="南蛮入侵",
        damage_target_id="甲",
        card_type="伤害类普通锦囊",
    )
    later = resolve_wufei_damage_context(
        guo_nuwang_id="郭女王",
        bird_state=state,
        bird_holder_alive=False,
        damage_card_name="南蛮入侵",
        damage_target_id="乙",
        card_type="伤害类普通锦囊",
    )
    assert first.damage_source_id == "雀持有者"
    assert later.damage_source_id == "郭女王"


def test_guonuwang_15_wufei_after_damage_waits_for_rescue_and_deals_sourceless_non_elemental_one() -> None:
    state = BirdMarkState("郭女王", "雀持有者", "♦", "下回合开始")
    result = resolve_wufei_after_damage(
        guo_alive_after_rescue=True,
        guo_hp_after_damage=2,
        bird_state=state,
        bird_holder_alive=True,
        bird_holder_hp=4,
        activate=True,
    )
    assert result.eligible is True and result.activated is True
    assert result.target_id == "雀持有者"
    assert result.damage_amount == 1
    assert result.damage_source_id is None
    assert result.damage_type == "无属性"
    dead = resolve_wufei_after_damage(
        guo_alive_after_rescue=False,
        guo_hp_after_damage=0,
        bird_state=state,
        bird_holder_alive=True,
        bird_holder_hp=4,
        activate=True,
    )
    assert dead.eligible is False and dead.damage_amount == 0


# ---------------------------------------------------------------------------
# 未上线神吕布重制原型：19 项


def test_shenlubu_01_rework_state_starts_with_two_rage() -> None:
    state = ShenLubuReworkState()
    assert state.rage == 2
    assert state.dynamic_x == 0


def test_shenlubu_02_rage_gain_uses_actual_dealt_and_received_points_without_cap() -> None:
    state = gain_rage_from_damage(ShenLubuReworkState(rage=999), damage_dealt=7, damage_received=5)
    assert state.rage == 1011


def test_shenlubu_03_wumou_only_converts_normal_tricks() -> None:
    card = WumouTrick("delay", "闪电", False, True, "self_only", "无距离")
    with pytest.raises(ValueError, match="只能转换普通锦囊牌"):
        convert_wumou_trick(card, action="使用", owner_id="神吕布")


def test_shenlubu_04_wumou_actual_name_is_slash_and_keeps_original_template_and_distance() -> None:
    card = WumouTrick("snatch", "顺手牵羊", True, False, "one_other", "实际距离1")
    result = convert_wumou_trick(
        card,
        action="使用",
        owner_id="神吕布",
        original_legal_target_ids=("甲",),
    )
    assert result.legal is True
    assert result.actual_card_name == "杀"
    assert result.target_template == "one_other"
    assert result.distance_rule == "实际距离1"
    assert result.uses_attack_range is False


def test_shenlubu_05_self_only_trick_cannot_be_actively_used_as_wumou_slash() -> None:
    card = WumouTrick("draw", "无中生有", True, False, "self_only", "无距离")
    result = convert_wumou_trick(card, action="使用", owner_id="神吕布")
    assert result.legal is False
    assert result.target_ids == ()
    assert "不能以自己为目标" in result.reason


def test_shenlubu_06_self_only_trick_can_be_played_in_a_slash_response_window() -> None:
    card = WumouTrick("draw", "无中生有", True, False, "self_only", "无距离")
    result = convert_wumou_trick(
        card,
        action=WumouAction.PLAY,
        owner_id="神吕布",
        response_requires_slash=True,
    )
    assert result.legal is True
    assert result.action is WumouAction.PLAY
    assert result.consumes_slash_use_limit is False


def test_shenlubu_07_all_character_trick_template_excludes_owner() -> None:
    for name in ("五谷丰登", "桃园结义"):
        result = convert_wumou_trick(
            WumouTrick(name, name, True, False, "all_characters", "全体"),
            action="使用",
            owner_id="神吕布",
            all_player_ids=("神吕布", "甲", "乙"),
        )
        assert result.target_ids == ("甲", "乙")


def test_shenlubu_08_borrowed_sword_template_requires_its_weapon_relation() -> None:
    card = WumouTrick("borrow", "借刀杀人", True, False, "borrowed_sword_relation", "原关系")
    illegal = convert_wumou_trick(
        card,
        action="使用",
        owner_id="神吕布",
        original_legal_target_ids=("甲",),
        borrowed_sword_relation_exists=False,
    )
    legal = convert_wumou_trick(
        card,
        action="使用",
        owner_id="神吕布",
        original_legal_target_ids=("甲",),
        borrowed_sword_relation_exists=True,
    )
    assert illegal.legal is False
    assert legal.legal is True


def test_shenlubu_09_active_wumou_consumes_slash_limit_but_keeps_physical_static_classification() -> None:
    card = WumouTrick("duel", "决斗", True, True, "one_other", "无限制")
    result = convert_wumou_trick(
        card,
        action="使用",
        owner_id="神吕布",
        original_legal_target_ids=("甲",),
    )
    assert result.consumes_slash_use_limit is True
    assert result.actual_use_is_damage_card is True
    assert result.physical_static_damage_card is True
    nondamage = convert_wumou_trick(
        WumouTrick("dismantle", "过河拆桥", True, False, "one_other", "无限制"),
        action="使用",
        owner_id="神吕布",
        original_legal_target_ids=("甲",),
    )
    assert nondamage.actual_use_is_damage_card is True
    assert nondamage.physical_static_damage_card is False


def test_shenlubu_10_wuqian_costs_two_rage_and_rejects_duplicate_active_target() -> None:
    state = activate_wuqian(ShenLubuReworkState(rage=4), target_id="甲")
    assert state.rage == 2
    assert state.wushuang_active is True
    with pytest.raises(ValueError, match="不能重复选择"):
        activate_wuqian(state, target_id="甲")


def test_shenlubu_11_wuqian_dynamic_x_decreases_when_target_leaves() -> None:
    state = activate_wuqian(activate_wuqian(ShenLubuReworkState(rage=6), target_id="甲"), target_id="乙")
    assert state.dynamic_x == 2
    assert state.bonus_slash_limit == 2
    after = remove_wuqian_target(state, target_id="甲")
    assert after.wuqian_targets == frozenset({"乙"})
    assert after.dynamic_x == after.bonus_slash_limit == 1


def test_shenlubu_12_next_damage_card_with_zero_total_actual_damage_clears_all_wuqian_effects() -> None:
    state = activate_wuqian(activate_wuqian(ShenLubuReworkState(rage=6), target_id="甲"), target_id="乙")
    result = resolve_wuqian_damage_card_completion(
        state,
        is_damage_card_use=True,
        actual_damage_by_target=(0, 0),
    )
    assert result.cleared_all is True
    assert result.state_after.wuqian_targets == frozenset()
    assert result.state_after.wushuang_active is False
    assert result.state_after.bonus_slash_limit == 0


def test_shenlubu_13_any_actual_damage_from_multi_target_damage_card_retains_all_wuqian_effects() -> None:
    state = activate_wuqian(activate_wuqian(ShenLubuReworkState(rage=6), target_id="甲"), target_id="乙")
    result = resolve_wuqian_damage_card_completion(
        state,
        is_damage_card_use=True,
        actual_damage_by_target=(0, 1, 0),
    )
    assert result.total_actual_damage == 1
    assert result.cleared_all is False
    assert result.state_after == state


def test_shenlubu_14_wuqian_end_phase_gains_static_damage_cards_from_current_draw_pile_until_x() -> None:
    state = activate_wuqian(activate_wuqian(ShenLubuReworkState(rage=6), target_id="甲"), target_id="乙")
    result = resolve_wuqian_end_phase(
        state,
        hand_cards=(_card("hand-damage", damage=True),),
        draw_pile=(
            _card("normal", zone=CardZone.DRAW_PILE),
            _card("damage", zone=CardZone.DRAW_PILE, damage=True),
        ),
        seed=3,
    )
    assert result.damage_cards_in_hand_before == 1
    assert [card.card_id for card in result.gained_cards] == ["damage"]
    assert result.gained_cards[0].zone is CardZone.HAND
    assert [card.card_id for card in result.draw_pile_after] == ["normal"]


def test_shenlubu_15_wuqian_end_phase_stops_without_matching_current_pile_card() -> None:
    state = activate_wuqian(activate_wuqian(ShenLubuReworkState(rage=6), target_id="甲"), target_id="乙")
    result = resolve_wuqian_end_phase(
        state,
        hand_cards=(),
        draw_pile=(_card("normal", zone=CardZone.DRAW_PILE, damage=False),),
    )
    assert result.gained_cards == ()
    assert len(result.draw_pile_after) == 1


def test_shenlubu_16_shenfen_costs_six_rage_and_is_once_per_play_phase() -> None:
    result = resolve_shenfen(
        ShenLubuReworkState(rage=6),
        ordered_other_players=(),
    )
    assert result.state_after.rage == 0
    assert result.state_after.shenfen_used_this_play_phase is True
    with pytest.raises(ValueError, match="每个出牌阶段限一次"):
        resolve_shenfen(result.state_after, ordered_other_players=())
    assert start_shen_lubu_play_phase(result.state_after).shenfen_used_this_play_phase is False


def test_shenlubu_17_shenfen_uses_three_complete_rounds_then_flips() -> None:
    result = resolve_shenfen(
        ShenLubuReworkState(rage=6),
        ordered_other_players=(
            ShenfenParticipant("甲", 3, ("甲装1",), ("甲1", "甲2", "甲3", "甲4", "甲5")),
            ShenfenParticipant("乙", 3, ("乙装1", "乙装2"), ("乙1", "乙2")),
        ),
    )
    assert [(event.round_name, event.player_id) for event in result.events] == [
        ("伤害轮", "甲"),
        ("伤害轮", "乙"),
        ("装备轮", "甲"),
        ("装备轮", "乙"),
        ("手牌轮", "甲"),
        ("手牌轮", "乙"),
        ("最后", "神吕布"),
    ]
    assert result.participants_after[0].equipment_card_ids == ()
    assert result.participants_after[0].hand_card_ids == ("甲5",)
    assert result.flipped_at_end is True
    assert result.state_after.face_up is False
    assert result.state_after.rage == 2  # 两名目标各实际受到1点，暴怒各+1。


def test_shenlubu_18_character_dead_in_damage_round_is_skipped_in_later_rounds() -> None:
    def lethal(player: ShenfenParticipant) -> ShenfenDamageOutcome:
        if player.player_id == "甲":
            return ShenfenDamageOutcome(1, 0, False)
        return ShenfenDamageOutcome(1, player.hp - 1, True)

    result = resolve_shenfen(
        ShenLubuReworkState(rage=6),
        ordered_other_players=(
            ShenfenParticipant("甲", 1, ("甲装",), ("甲手",)),
            ShenfenParticipant("乙", 3, ("乙装",), ("乙手",)),
        ),
        damage_resolver=lethal,
    )
    later = [(event.round_name, event.player_id) for event in result.events if event.round_name != "伤害轮"]
    assert ("装备轮", "甲") not in later
    assert ("手牌轮", "甲") not in later
    assert ("装备轮", "乙") in later


def test_shenlubu_19_game_over_during_shenfen_stops_unstarted_damage_and_no_final_flip() -> None:
    def game_ending(player: ShenfenParticipant) -> ShenfenDamageOutcome:
        return ShenfenDamageOutcome(1, player.hp - 1, False, game_over=True)

    result = resolve_shenfen(
        ShenLubuReworkState(rage=6),
        ordered_other_players=(
            ShenfenParticipant("甲", 1, ("甲装",), ("甲手",)),
            ShenfenParticipant("乙", 3, ("乙装",), ("乙手",)),
        ),
        damage_resolver=game_ending,
    )
    assert result.game_over is True
    assert [(event.round_name, event.player_id) for event in result.events] == [("伤害轮", "甲")]
    assert result.flipped_at_end is False
    assert result.state_after.face_up is True

