import csv
from pathlib import Path

import pytest

from scripts.sgs_card_rules import (
    CardUseEvent,
    EquipmentState,
    WinePlayPhaseState,
    can_nullification_respond_to_card_use,
    resolve_nonresponsive_card_use,
    resolve_structured_card_usage,
    use_dying_recovery_card,
    use_equipment_card,
    use_peach_for_self_heal,
    use_wine_for_slash_buff,
)
from scripts.sgs_extended_rules import (
    DeckOperation,
    RuleStatus,
    TableCardState,
    meets_normal_death_condition,
    resolve_death_state_machine,
    take_top_cards,
)
from scripts.sgs_limited_identity_variant import (
    LIMITED_MODE_VARIANT,
    CardRegion,
    CurrentRole,
    LordRegions,
    RegionCardChoice,
    finalize_old_lord_formal_death_after_succession,
    initial_heir_selection_state,
    resolve_heir_succession_after_failed_rescue,
    select_heir,
)
from scripts.sgs_extended_rules import LivingSeatRing


CARD_DATA_PATH = (
    Path(__file__).resolve().parents[1]
    / "knowledge"
    / "三国杀卡牌结构化数据.csv"
)
CARD_USE_MODE_PATH = (
    Path(__file__).resolve().parents[1]
    / "knowledge"
    / "三国杀卡牌使用方式.csv"
)
PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _card_row(name: str) -> dict[str, str]:
    with CARD_DATA_PATH.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    return next(row for row in rows if row["card_name"] == name)


def _card_use_mode_row(card_key: str, context: str) -> dict[str, str]:
    with CARD_USE_MODE_PATH.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    return next(
        row
        for row in rows
        if row["card_key"] == card_key and row["use_mode"] == context
    )


def test_normal_death_condition_is_not_formal_death() -> None:
    assert not meets_normal_death_condition(0, rescue_completed=False)
    assert meets_normal_death_condition(0, rescue_completed=True)
    assert not meets_normal_death_condition(1, rescue_completed=True)

    result = resolve_death_state_machine(
        {"formally_dead": False},
        current_hp=0,
        rescue_completed=False,
        confirm_formal_death=lambda state: {**state, "formally_dead": True},
        check_victory=lambda _state: False,
    )
    assert not result.normal_death_condition_met
    assert not result.formal_death_confirmed
    assert result.final_state["formally_dead"] is False


def test_normal_mode_confirms_death_without_override() -> None:
    result = resolve_death_state_machine(
        {"events": ()},
        current_hp=-1,
        rescue_completed=True,
        confirm_formal_death=lambda state: {
            "events": state["events"] + ("正式死亡",)
        },
        after_formal_death_events=lambda state: {
            "events": state["events"] + ("死亡后事件",)
        },
        check_victory=lambda _state: False,
    )
    assert result.normal_death_condition_met
    assert result.formal_death_confirmed
    assert result.before_formal_death_override_count == 0
    assert result.final_state["events"] == ("正式死亡", "死亡后事件")


def test_heir_override_runs_before_formal_death_and_before_region_cleanup() -> None:
    heir_state = select_heir(
        initial_heir_selection_state(LIMITED_MODE_VARIANT, 1),
        5,
        alive_players=range(1, 9),
        first_round_active=True,
    )
    initial = {
        "events": (),
        "regions": LordRegions(
            hand=("储君可取得的手牌", "剩余手牌"),
            equipment=("武器",),
        ),
        "ring": LivingSeatRing.all_alive(8),
        "succession": None,
    }

    def succession_override(state):
        assert state["regions"].hand == ("储君可取得的手牌", "剩余手牌")
        succession = resolve_heir_succession_after_failed_rescue(
            heir_state,
            rescue_failed=True,
            roles_current={
                1: CurrentRole.LORD,
                2: CurrentRole.REBEL,
                3: CurrentRole.REBEL,
                4: CurrentRole.LOYALIST,
                5: CurrentRole.LOYALIST,
                6: CurrentRole.REBEL,
                7: CurrentRole.REBEL,
                8: CurrentRole.SPY,
            },
            living_seat_ring=state["ring"],
            old_lord_regions=state["regions"],
            new_lord_maximum_hp_before=4,
            new_lord_current_hp_before=3,
            selected_card=RegionCardChoice(CardRegion.HAND, 0),
        )
        return {
            **state,
            "events": state["events"] + ("继位",),
            "regions": succession.remaining_old_lord_regions,
            "succession": succession,
        }

    def confirm_formal_death(state):
        assert state["events"] == ("继位",)
        assert state["succession"].obtained_card == "储君可取得的手牌"
        ring = finalize_old_lord_formal_death_after_succession(
            state["succession"], 1
        )
        return {**state, "events": state["events"] + ("正式死亡",), "ring": ring}

    def after_death(state):
        return {
            **state,
            "events": state["events"] + ("区域清理",),
            "regions": LordRegions(),
        }

    result = resolve_death_state_machine(
        initial,
        current_hp=0,
        rescue_completed=True,
        before_formal_death_overrides=(succession_override,),
        confirm_formal_death=confirm_formal_death,
        after_formal_death_events=after_death,
        check_victory=lambda _state: False,
    )
    assert result.final_state["events"] == ("继位", "正式死亡", "区域清理")
    assert result.event_order.index("完成正式死亡前模式覆盖:1") < (
        result.event_order.index("确认正式死亡")
    )
    assert result.final_state["succession"].rebel_instant_win_from_old_lord_death is False


def test_peach_can_be_used_repeatedly_until_hp_reaches_one() -> None:
    first = use_dying_recovery_card(
        "桃", user_player_id=1, target_player_id=1, current_hp=-1
    )
    assert first.hp_after == 0 and first.remains_dying
    second = use_dying_recovery_card(
        "桃", user_player_id=1, target_player_id=1, current_hp=first.hp_after
    )
    assert second.hp_after == 1 and second.rescue_ended
    with pytest.raises(ValueError, match="已脱离濒死"):
        use_dying_recovery_card(
            "桃", user_player_id=1, target_player_id=1, current_hp=1
        )


def test_peach_can_be_used_repeatedly_in_own_play_phase_until_full_hp() -> None:
    first = use_peach_for_self_heal(
        user_player_id=1,
        target_player_id=1,
        current_hp=2,
        maximum_hp=4,
    )
    assert first.hp_after == 3
    assert not first.reached_maximum_hp
    second = use_peach_for_self_heal(
        user_player_id=1,
        target_player_id=1,
        current_hp=first.hp_after,
        maximum_hp=4,
    )
    assert second.hp_after == 4
    assert second.reached_maximum_hp
    with pytest.raises(ValueError, match="未受伤"):
        use_peach_for_self_heal(
            user_player_id=1,
            target_player_id=1,
            current_hp=4,
            maximum_hp=4,
        )


def test_peach_play_phase_unlimited_does_not_bypass_legality_or_resources() -> None:
    with pytest.raises(ValueError, match="自己的出牌阶段"):
        use_peach_for_self_heal(
            user_player_id=1,
            target_player_id=1,
            current_hp=2,
            maximum_hp=4,
            in_own_play_phase=False,
        )
    with pytest.raises(ValueError, match="只能对自己"):
        use_peach_for_self_heal(
            user_player_id=1,
            target_player_id=2,
            current_hp=2,
            maximum_hp=4,
        )
    with pytest.raises(ValueError, match="实体牌或合法技能转化"):
        use_peach_for_self_heal(
            user_player_id=1,
            target_player_id=1,
            current_hp=2,
            maximum_hp=4,
            has_card_or_conversion=False,
        )


def test_peach_can_rescue_another_character_repeatedly_in_one_opportunity() -> None:
    first = use_dying_recovery_card(
        "桃", user_player_id=1, target_player_id=2, current_hp=-1
    )
    assert first.hp_after == 0 and first.remains_dying
    assert first.use_resolution.use_context.value == "rescue_other_dying_character"
    second = use_dying_recovery_card(
        "桃", user_player_id=1, target_player_id=2, current_hp=first.hp_after
    )
    assert second.hp_after == 1 and second.rescue_ended
    with pytest.raises(ValueError, match="已脱离濒死"):
        use_dying_recovery_card(
            "桃", user_player_id=1, target_player_id=2, current_hp=1
        )
    with pytest.raises(ValueError, match="合法濒死救援时机"):
        use_dying_recovery_card(
            "桃",
            user_player_id=1,
            target_player_id=2,
            current_hp=0,
            legal_rescue_window=False,
        )


def test_three_peach_contexts_do_not_share_a_once_per_turn_quota() -> None:
    play_phase = use_peach_for_self_heal(
        user_player_id=1,
        target_player_id=1,
        current_hp=2,
        maximum_hp=4,
    )
    other_rescue = use_dying_recovery_card(
        "桃", user_player_id=1, target_player_id=2, current_hp=0
    )
    self_rescue = use_dying_recovery_card(
        "桃", user_player_id=1, target_player_id=1, current_hp=0
    )
    later_play_phase = use_peach_for_self_heal(
        user_player_id=1,
        target_player_id=1,
        current_hp=play_phase.hp_after,
        maximum_hp=4,
    )
    assert other_rescue.rescue_ended and self_rescue.rescue_ended
    assert later_play_phase.hp_after == 4


def test_peach_has_no_nullification_window_but_explicit_skill_can_invalidate() -> None:
    assert not can_nullification_respond_to_card_use("桃", "基本牌")
    invalidated = use_dying_recovery_card(
        "桃",
        user_player_id=1,
        target_player_id=1,
        current_hp=0,
        invalidated_by_skill=True,
        skill_explicitly_can_invalidate=True,
    )
    assert invalidated.hp_after == 0 and invalidated.remains_dying
    use = invalidated.use_resolution
    assert use.counts_as_used and not use.effect_resolved
    assert CardUseEvent.CARD_USED in use.events
    assert CardUseEvent.CARD_EFFECT_INVALIDATED in use.events
    assert CardUseEvent.CARD_EFFECT_RESOLVED not in use.events
    assert CardUseEvent.AFTER_CARD_EFFECT_RESOLVED not in use.events
    assert use.use_trigger_available
    assert not use.after_resolution_trigger_available

    play_phase_invalidated = use_peach_for_self_heal(
        user_player_id=1,
        target_player_id=1,
        current_hp=2,
        maximum_hp=4,
        invalidated_by_skill=True,
        skill_explicitly_can_invalidate=True,
    )
    assert play_phase_invalidated.hp_after == 2
    assert play_phase_invalidated.use_resolution.counts_as_used
    assert not play_phase_invalidated.use_resolution.effect_resolved
    assert not play_phase_invalidated.use_resolution.after_resolution_triggered


def test_wine_rescue_is_unlimited_and_does_not_consume_slash_buff_quota() -> None:
    play_phase = WinePlayPhaseState(play_phase_id=1)
    first = use_dying_recovery_card(
        "酒", user_player_id=2, target_player_id=2, current_hp=-1
    )
    second = use_dying_recovery_card(
        "酒", user_player_id=2, target_player_id=2, current_hp=first.hp_after
    )
    assert second.hp_after == 1
    assert not play_phase.slash_buff_use_consumed
    buff = use_wine_for_slash_buff(play_phase)
    assert buff.state_after.slash_buff_use_consumed
    assert buff.state_after.slash_damage_bonus == 1


def test_wine_slash_buff_is_once_per_independent_play_phase() -> None:
    first_phase = use_wine_for_slash_buff(WinePlayPhaseState(1)).state_after
    with pytest.raises(ValueError, match="额度已经使用"):
        use_wine_for_slash_buff(first_phase)
    second_phase = use_wine_for_slash_buff(WinePlayPhaseState(2)).state_after
    assert second_phase.slash_buff_use_consumed


def test_invalidated_wine_still_consumes_use_but_grants_no_effect() -> None:
    result = use_wine_for_slash_buff(
        WinePlayPhaseState(1),
        invalidated_by_skill=True,
        skill_explicitly_can_invalidate=True,
    )
    assert result.state_after.slash_buff_use_consumed
    assert result.state_after.slash_damage_bonus == 0
    assert result.use_resolution.counts_as_used
    assert not result.use_resolution.effect_resolved
    assert not can_nullification_respond_to_card_use("酒", "基本牌")


def test_equipment_can_be_used_repeatedly_and_same_slot_replaces_old_card() -> None:
    state = EquipmentState({})
    weapon = use_equipment_card(state, "青釭剑", "武器")
    armor = use_equipment_card(weapon.state_after, "八卦阵", "防具")
    replacement = use_equipment_card(armor.state_after, "古锭刀", "武器")
    assert armor.state_after.slots == {"武器": "青釭剑", "防具": "八卦阵"}
    assert replacement.replaced_card == "青釭剑"
    assert replacement.state_after.slots["武器"] == "古锭刀"
    assert not can_nullification_respond_to_card_use("古锭刀", "装备牌")


def test_invalidated_equipment_is_used_but_does_not_enter_equipment_zone() -> None:
    state = EquipmentState({"武器": "青釭剑"})
    result = use_equipment_card(
        state,
        "古锭刀",
        "武器",
        invalidated_by_skill=True,
        skill_explicitly_can_invalidate=True,
    )
    assert result.state_after is state
    assert not result.entered_equipment_zone
    assert not result.equipment_success_triggered
    assert result.use_resolution.counts_as_used
    assert not result.use_resolution.effect_resolved


def test_structured_peach_modes_define_all_three_unlimited_contexts() -> None:
    peach = _card_row("桃")
    expected = {
        "own_play_phase_self_heal": ("own_play_phase", "self", True, False),
        "dying_self_rescue": (
            "legal_dying_rescue_window",
            "self",
            False,
            True,
        ),
        "rescue_other_dying_character": (
            "legal_dying_rescue_window",
            "other_dying_character",
            False,
            True,
        ),
    }
    for context, (timing, target_scope, wounded, dying) in expected.items():
        rule = resolve_structured_card_usage(
            peach,
            use_context=context,
            use_mode_row=_card_use_mode_row(peach["card_id"], context),
        )
        assert rule.default_timing == timing
        assert rule.base_use_limit == "unlimited"
        assert rule.target_scope == target_scope
        assert rule.requires_wounded is wounded
        assert rule.requires_target_dying is dying
        assert not rule.can_be_responded_by_card


def test_other_structured_card_modes_keep_their_existing_rules() -> None:

    wine_row = _card_row("酒")
    wine = resolve_structured_card_usage(
        wine_row,
        use_context="play_phase_slash_buff",
        use_mode_row=_card_use_mode_row(
            wine_row["card_id"], "play_phase_slash_buff"
        ),
    )
    assert wine.base_use_limit == "once_per_play_phase"

    equipment = resolve_structured_card_usage(_card_row("青釭剑"))
    assert equipment.use_context == "equip"
    assert equipment.default_timing == "own_play_phase"
    assert equipment.base_use_limit == "unlimited"


def test_normal_card_response_attempt_is_rejected() -> None:
    for context in (
        "own_play_phase_self_heal",
        "dying_self_rescue",
        "rescue_other_dying_character",
    ):
        with pytest.raises(ValueError, match="不产生普通卡牌响应窗口"):
            resolve_nonresponsive_card_use(
                "桃",
                "基本牌",
                context,
                ordinary_card_response_attempted=True,
            )


def test_deck_exhaustion_reports_two_distinct_status_sources() -> None:
    empty = TableCardState(draw_pile=(), discard_pile=())
    draw = take_top_cards(empty, 1, operation=DeckOperation.DRAW)
    judgment = take_top_cards(empty, 1, operation=DeckOperation.JUDGMENT)
    assert draw.game_tied and judgment.game_tied
    assert draw.exhaustion_policy.code == "draw_exhaustion_rule"
    assert draw.exhaustion_status is RuleStatus.CURRENT_CONFIRMED
    assert "当前确认" in draw.exhaustion_disclosure
    assert judgment.exhaustion_policy.code == "non_draw_deck_exhaustion_assumption"
    assert judgment.exhaustion_status is RuleStatus.ANALYSIS_CONVENTION
    assert "分析约定" in judgment.exhaustion_disclosure


def test_exactly_taking_last_card_has_no_exhaustion_status() -> None:
    result = take_top_cards(
        TableCardState(draw_pile=("最后一张",), discard_pile=()),
        1,
    )
    assert result.completed and not result.game_tied
    assert result.exhaustion_policy is None
    assert result.exhaustion_disclosure is None


def test_death_and_card_documents_use_the_revised_state_boundaries() -> None:
    mode = (PROJECT_ROOT / "knowledge" / "三国杀模式规则.md").read_text(
        encoding="utf-8"
    )
    terms = (
        PROJECT_ROOT / "knowledge" / "三国杀基础术语与通用机制.md"
    ).read_text(encoding="utf-8")
    cards = (PROJECT_ROOT / "knowledge" / "三国杀卡牌效果.md").read_text(
        encoding="utf-8"
    )
    simulation = (PROJECT_ROOT / "knowledge" / "三国杀模拟规范.md").read_text(
        encoding="utf-8"
    )

    death_section = mode.split("### 4.10 死亡与连续伤害", 1)[1].split(
        "## 5.", 1
    )[0]
    assert "满足通常死亡条件" in death_section
    assert "完成全部正式死亡前覆盖规则后，再确认" in death_section
    assert death_section.index("满足通常死亡条件") < death_section.index(
        "确认原角色正式死亡"
    )
    assert "完成正常濒死救援，确定角色是否正式死亡" not in death_section

    assert "card_use_declared" in terms and "card_effect_invalidated" in terms
    assert "draw_exhaustion_rule" in terms
    assert "non_draw_deck_exhaustion_assumption" in terms
    assert "资料状态：分析约定" in terms
    assert "【无懈可击】不能响应装备牌" in cards

    peach = cards.split("### 3.5 【桃】", 1)[1].split("### 3.6", 1)[0]
    wine = cards.split("### 3.6 【酒】", 1)[1].split("## 4.", 1)[0]
    equipment = cards.split("## 6. 装备牌通用规则", 1)[1].split(
        "## 10.", 1
    )[0]
    assert "响应方式：未提供" not in peach + wine + equipment
    assert "次数限制：未提供" not in peach + wine + equipment
    assert "每个独立出牌阶段限一次" in wine
    assert "出牌阶段回复自己" in peach
    assert "濒死时救援自己" in peach
    assert "濒死时救援其他角色" in peach
    assert "三种用途不共享使用额度" in peach
    assert "合法主动使用装备牌没有基础每回合或每个出牌阶段次数限制" in terms
    assert "non_draw_deck_exhaustion_assumption" in simulation
    assert "【分析约定】" in simulation
