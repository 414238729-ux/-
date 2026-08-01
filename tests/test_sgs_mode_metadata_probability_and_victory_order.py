from __future__ import annotations

import csv
from pathlib import Path

import pytest

from scripts import (
    GENERAL_CANDIDATE_EQUAL_ASSUMPTION_DISCLOSURE,
    LIMITED_MODE_DECK_ID,
    LIMITED_MODE_VARIANT,
    CurrentRole,
    Identity,
    IdentityVictory,
    LivingSeatRing,
    LordRegions,
    VariantVictory,
    finalize_old_lord_formal_death_after_succession,
    general_candidate_probability_context,
    initial_heir_selection_state,
    limited_mode_is_available,
    limited_mode_metadata,
    replace_general_candidate,
    resolve_heir_succession_after_failed_rescue,
    resolve_sequential_effect,
    resolve_standard_identity_death,
    resolve_variant_identity_death,
    select_heir,
)


ROOT = Path(__file__).resolve().parents[1]
DECK = ROOT / "knowledge" / "三国杀牌堆数据.csv"
CARD_DATA = ROOT / "knowledge" / "三国杀卡牌结构化数据.csv"
SPEC = ROOT / "knowledge" / "三国杀模拟规范.md"
MODES = ROOT / "knowledge" / "三国杀模式规则.md"
TERMS = ROOT / "knowledge" / "三国杀基础术语与通用机制.md"
CARDS = ROOT / "knowledge" / "三国杀卡牌效果.md"


def _csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_current_deck_has_160_cards_and_no_treasure_records() -> None:
    rows = _csv_rows(DECK)
    assert sum(int(row["quantity"]) for row in rows) == 160
    assert {row["deck_id"] for row in rows} == {LIMITED_MODE_DECK_ID}
    assert all("宝物牌" not in value for row in rows for value in row.values())
    assert all("野心家标记" not in value for row in rows for value in row.values())

    structured_rows = _csv_rows(CARD_DATA)
    assert all(row["subtype"] != "宝物" for row in structured_rows)


def test_shared_deck_is_not_duplicated_for_the_special_mode() -> None:
    rows = _csv_rows(DECK)
    assert {row["deck_id"] for row in rows} == {
        "sgs_mobile_non_special_20260725_unofficial"
    }
    assert all("八人军争限时变体" in row["mode"] for row in rows)
    assert limited_mode_metadata().deck_id == next(iter({row["deck_id"] for row in rows}))


def test_treasure_absence_is_scope_not_a_pending_gap() -> None:
    combined = "\n".join(_read(path) for path in (SPEC, TERMS, CARDS))
    assert "当前160张基础牌堆不包含宝物牌" in combined
    assert "这不是需要补齐" in combined or "不是当前模拟资料缺口" in combined
    for obsolete in ("宝物牌效果尚未提供", "是否需要加入宝物牌", "本次未提供的宝物牌"):
        assert obsolete not in combined


def test_special_mode_metadata_does_not_invent_an_official_name() -> None:
    metadata = limited_mode_metadata()
    assert metadata.descriptive_title == "移动版八人军争特殊玩法：主公立储与内奸择途"
    assert metadata.platform == "三国杀移动版"
    assert metadata.official_formal_name is None
    assert metadata.internal_mode_id == LIMITED_MODE_VARIANT
    assert metadata.internal_mode_id not in metadata.official_display_text
    assert metadata.availability_label == "限时开启"
    assert metadata.first_known_promotion_or_open_date == "2026-05-16"
    assert metadata.rules_version is None
    assert metadata.end_date is None
    assert metadata.permanent_status == "未知"
    assert metadata.last_verified_date == "2026-07-26"
    assert metadata.available_on_last_verification


def test_version_change_does_not_automatically_disable_limited_mode() -> None:
    assert limited_mode_is_available(game_version="未来普通版本")
    assert not limited_mode_is_available(
        game_version="未来普通版本",
        confirmed_removed_or_closed=True,
    )


def test_actual_general_distribution_and_equal_simulation_are_separated() -> None:
    context = general_candidate_probability_context(fixed_lineup=False)
    assert context.actual_distribution == "非等概率"
    assert not context.actual_weights_known
    assert context.simulate_appearance_probability
    assert context.simulation_distribution == "合法候选等概率"
    assert context.disclosure == GENERAL_CANDIDATE_EQUAL_ASSUMPTION_DISCLOSURE

    replacement = replace_general_candidate(
        ["甲", "乙", "丙", "丁"],
        ["甲", "乙", "丙"],
        0,
        seed=0,
    )
    assert replacement.assumption_disclosure == context.disclosure
    assert not replacement.represents_actual_client_weights


def test_fixed_lineup_does_not_simulate_general_appearance_probability() -> None:
    context = general_candidate_probability_context(fixed_lineup=True)
    assert context.fixed_lineup
    assert not context.simulate_appearance_probability
    assert context.simulation_distribution is None
    assert "不计算武将刷出概率" in context.disclosure


def test_last_rebel_death_ends_game_before_draw_three_reward() -> None:
    identities = {
        1: Identity.LORD,
        2: Identity.LOYALIST,
        3: Identity.REBEL,
    }
    result = resolve_standard_identity_death(
        identities,
        {1, 2},
        killer_player_id=2,
        victim_player_id=3,
    )
    assert result.victory is IdentityVictory.LORD_AND_LOYALISTS
    assert result.game_over
    assert not result.identity_consequence_processed
    assert result.identity_consequence is None

    reward_draw_attempted = result.identity_consequence is not None
    assert not reward_draw_attempted


def test_rebel_death_with_spy_alive_still_draws_three() -> None:
    identities = {
        1: Identity.LORD,
        2: Identity.LOYALIST,
        3: Identity.REBEL,
        4: Identity.SPY,
    }
    result = resolve_standard_identity_death(
        identities,
        {1, 2, 4},
        killer_player_id=2,
        victim_player_id=3,
    )
    assert result.victory is IdentityVictory.ONGOING
    assert not result.game_over
    assert result.identity_consequence_processed
    assert result.identity_consequence is not None
    assert result.identity_consequence.draw_count == 3


def test_lord_killing_loyalist_penalty_runs_when_game_continues() -> None:
    identities = {
        1: Identity.LORD,
        2: Identity.LOYALIST,
        3: Identity.REBEL,
        4: Identity.SPY,
    }
    result = resolve_standard_identity_death(
        identities,
        {1, 3, 4},
        killer_player_id=1,
        victim_player_id=2,
        killer_hand=("手牌",),
        killer_equipment=("装备",),
        killer_judgment=("判定牌",),
    )
    assert result.victory is IdentityVictory.ONGOING
    assert result.identity_consequence is not None
    assert result.identity_consequence.discarded_hand == ("手牌",)
    assert result.identity_consequence.discarded_equipment == ("装备",)
    assert result.identity_consequence.retained_judgment == ("判定牌",)


def test_ambitionist_victory_skips_optional_kill_draw_three() -> None:
    roles = {1: CurrentRole.LORD, 8: CurrentRole.AMBITIONIST}
    result = resolve_variant_identity_death(
        roles,
        {8},
        current_lord_player_id=1,
        killer_player_id=8,
        victim_player_id=1,
        victory_prerequisites_completed=True,
    )
    assert result.victory is VariantVictory.AMBITIONIST
    assert result.game_over
    assert not result.identity_reward_processed
    assert result.identity_reward is None


def _variant_roles() -> dict[int, CurrentRole]:
    return {
        1: CurrentRole.LORD,
        2: CurrentRole.REBEL,
        3: CurrentRole.REBEL,
        4: CurrentRole.REBEL,
        5: CurrentRole.LOYALIST,
        6: CurrentRole.LOYALIST,
        7: CurrentRole.REBEL,
        8: CurrentRole.SPY,
    }


def test_legal_heir_succeeds_before_victory_is_checked() -> None:
    selected = select_heir(
        initial_heir_selection_state(LIMITED_MODE_VARIANT, 1),
        5,
        alive_players=range(1, 9),
        first_round_active=True,
    )
    succession = resolve_heir_succession_after_failed_rescue(
        selected,
        rescue_failed=True,
        roles_current=_variant_roles(),
        living_seat_ring=LivingSeatRing.all_alive(8),
        old_lord_regions=LordRegions(),
        new_lord_maximum_hp_before=4,
        new_lord_current_hp_before=4,
    )
    assert succession.succeeded
    ring_after_death = finalize_old_lord_formal_death_after_succession(
        succession,
        1,
    )
    result = resolve_variant_identity_death(
        succession.roles_current,
        ring_after_death.alive_players,
        current_lord_player_id=succession.current_lord_player_id,
        killer_player_id=2,
        victim_player_id=1,
        victory_prerequisites_completed=True,
    )
    assert succession.current_lord_player_id == 5
    assert result.victory is VariantVictory.ONGOING
    assert not result.game_over


def test_no_legal_heir_uses_normal_lord_death_victory() -> None:
    selected = select_heir(
        initial_heir_selection_state(LIMITED_MODE_VARIANT, 1),
        2,
        alive_players=range(1, 9),
        first_round_active=True,
    )
    succession = resolve_heir_succession_after_failed_rescue(
        selected,
        rescue_failed=True,
        roles_current=_variant_roles(),
        living_seat_ring=LivingSeatRing.all_alive(8),
        old_lord_regions=LordRegions(),
        new_lord_maximum_hp_before=4,
        new_lord_current_hp_before=4,
    )
    assert not succession.succeeded
    result = resolve_variant_identity_death(
        succession.roles_current,
        set(range(2, 9)),
        current_lord_player_id=1,
        killer_player_id=2,
        victim_player_id=1,
        victory_prerequisites_completed=True,
    )
    assert result.victory is VariantVictory.REBELS
    assert result.game_over
    assert result.identity_reward is None


def test_variant_death_rejects_victory_check_before_heir_prerequisites() -> None:
    with pytest.raises(ValueError, match="必须先完成"):
        resolve_variant_identity_death(
            _variant_roles(),
            set(range(2, 9)),
            current_lord_player_id=1,
            killer_player_id=2,
            victim_player_id=1,
            victory_prerequisites_completed=False,
        )


@pytest.mark.parametrize("effect_name", ["铁索连环", "全体锦囊"])
def test_victory_stops_remaining_chain_or_aoe_targets(effect_name: str) -> None:
    def resolve_one(log: tuple[str, ...], target: int) -> tuple[str, ...]:
        return log + (f"{effect_name}:{target}:胜利成立",)

    result = resolve_sequential_effect(
        (2, 3, 4),
        (),
        resolve_one,
        lambda log: bool(log),
    )
    assert result.processed_targets == (2,)
    assert result.stopped_by_game_over
    assert all(":3:" not in entry and ":4:" not in entry for entry in result.final_state)


def test_documents_lock_current_probability_and_victory_order() -> None:
    modes = _read(MODES)
    spec = _read(SPEC)
    combined = modes + "\n" + spec
    assert "实际客户端中，合法武将的出现概率不是等概率" in modes
    assert GENERAL_CANDIDATE_EQUAL_ASSUMPTION_DISCLOSURE in combined
    assert "用户已经固定参战武将或阵容时，不计算" in modes
    assert "游戏立即结束，不再执行本次身份击杀奖励或惩罚" in modes
    assert "不得因本应跳过的奖励摸牌触发重洗、牌堆耗尽或平局" in modes
    assert "继位属于胜利前置状态" in modes
