from __future__ import annotations

import pytest
import scripts

from scripts.sgs_mode_evaluation import (
    ClientHexReference,
    HexScoreSource,
    LandlordSuitability,
    MainPoolCandidate,
    NEW_CAOCHUN_CLIENT_HEX_REFERENCE,
    NpcRoleWhitelist,
    SpyGameResult,
    SpyRewardScope,
    apply_other_mode_coverage_penalty,
    audit_main_evaluation_pool,
    evaluate_landlord_suitability,
    npc_can_appear,
    standard_spy_server_reward,
    summarize_standard_spy_rewards,
)


def test_spy_actual_win_is_three_and_never_stacks_duel_reward() -> None:
    assert standard_spy_server_reward(True, True) == 3
    assert standard_spy_server_reward(True, False) == 3


def test_spy_duel_reward_applies_only_when_spy_did_not_win() -> None:
    assert standard_spy_server_reward(False, True) == 1
    assert standard_spy_server_reward(False, False) == 0


def test_spy_summary_keeps_raw_win_duel_probability_and_reward_separate() -> None:
    summary = summarize_standard_spy_rewards(
        (
            SpyGameResult(True, True),
            SpyGameResult(False, True),
            SpyGameResult(False, False),
            SpyGameResult(False, False),
        )
    )

    assert summary.raw_spy_win_rate == pytest.approx(0.25)
    assert summary.lord_spy_duel_probability == pytest.approx(0.5)
    assert summary.server_reward_total == 4
    assert summary.server_reward_score == pytest.approx(1.0)
    assert summary.reward_score_is_raw_win_rate is False
    assert summary.raw_win_rate == summary.raw_spy_win_rate
    assert summary.duel_probability == summary.lord_spy_duel_probability
    assert summary.reward_score == summary.server_reward_score


def test_limited_special_mode_does_not_auto_use_standard_spy_reward() -> None:
    with pytest.raises(ValueError, match="仅适用于标准非限时八人军争"):
        standard_spy_server_reward(
            True,
            True,
            scope=SpyRewardScope.LIMITED_SPECIAL_EIGHT_PLAYER,
        )

    with pytest.raises(ValueError, match="不能自动套用"):
        summarize_standard_spy_rewards(
            (
                SpyGameResult(
                    True,
                    True,
                    scope=SpyRewardScope.LIMITED_SPECIAL_EIGHT_PLAYER,
                ),
            )
        )


def test_landlord_raw_equal_role_score_is_always_retained() -> None:
    result = evaluate_landlord_suitability(0.6, 0.4)

    assert result.landlord_win_rate == pytest.approx(0.6)
    assert result.farmer_win_rate == pytest.approx(0.4)
    assert result.raw_equal_role_score == pytest.approx(0.5)
    assert result.selectable_score == pytest.approx(0.5)
    assert result.selectable_roles == ("地主", "农民")
    assert (result.L, result.F, result.S_raw, result.S_selectable) == pytest.approx(
        (0.6, 0.4, 0.5, 0.5)
    )


@pytest.mark.parametrize(
    ("suitability", "expected_score", "expected_roles", "formula"),
    (
        (LandlordSuitability.FARMER_ONLY, 0.36, ("农民",), "0.9 * F"),
        (LandlordSuitability.LANDLORD_ONLY, 0.54, ("地主",), "0.9 * L"),
    ),
)
def test_landlord_single_role_penalty_is_multiplication(
    suitability: LandlordSuitability,
    expected_score: float,
    expected_roles: tuple[str, ...],
    formula: str,
) -> None:
    result = evaluate_landlord_suitability(0.6, 0.4, suitability)

    assert result.raw_equal_role_score == pytest.approx(0.5)
    assert result.selectable_score == pytest.approx(expected_score)
    assert result.selectable_roles == expected_roles
    assert result.formula == formula


def test_wholly_unsuitable_general_is_excluded_from_landlord_and_npc_pool() -> None:
    result = evaluate_landlord_suitability(
        0.7,
        0.6,
        LandlordSuitability.UNSUITABLE,
    )

    assert result.raw_equal_role_score == pytest.approx(0.65)
    assert result.selectable_score is None
    assert result.selectable_roles == ()
    assert result.included_in_landlord_pool is False
    assert result.npc_can_appear_in_landlord_mode is False
    assert result.other_major_mode_multiplier == pytest.approx(0.9)
    assert dict(
        apply_other_mode_coverage_penalty(
            {"2v2": 0.8, "军争身份": 0.5},
            result,
        )
    ) == pytest.approx({"2v2": 0.72, "军争身份": 0.45})


def test_landlord_rate_out_of_range_has_clear_chinese_error() -> None:
    with pytest.raises(ValueError, match="地主原始胜率必须位于 0 至 1"):
        evaluate_landlord_suitability(1.2, 0.5)


def test_npc_can_only_appear_in_explicit_role_whitelist() -> None:
    whitelist = NpcRoleWhitelist("测试武将", frozenset({"农民", "忠臣"}))

    assert npc_can_appear(whitelist, "农民") is True
    assert npc_can_appear(whitelist, "地主") is False
    assert NpcRoleWhitelist("不适合斗地主", frozenset()).allows("农民") is False


def _candidate(name: str, *, generalist: bool = True) -> MainPoolCandidate:
    return MainPoolCandidate(
        name,
        all_modes_usable=generalist,
        low_targeting=True,
        no_extreme_role_dependency=True,
        no_core_mechanism_lock=True,
    )


def test_main_pool_passes_when_three_of_four_are_generalists() -> None:
    audit = audit_main_evaluation_pool(
        (_candidate("甲"), _candidate("乙"), _candidate("丙"), _candidate("丁", generalist=False))
    )

    assert audit.generalist_count == 3
    assert audit.generalist_ratio == pytest.approx(0.75)
    assert audit.meets_recommendation is True
    assert audit.non_generalist_names == ("丁",)


def test_main_pool_requires_all_four_conditions_for_generalist_count() -> None:
    audit = audit_main_evaluation_pool(
        (
            _candidate("通用甲"),
            _candidate("通用乙"),
            MainPoolCandidate(
                "强针对",
                all_modes_usable=True,
                low_targeting=False,
                no_extreme_role_dependency=True,
                no_core_mechanism_lock=True,
            ),
        )
    )

    assert audit.generalist_ratio == pytest.approx(2 / 3)
    assert audit.meets_recommendation is False


def test_client_hex_reference_preserves_direct_decimal_and_discloses_low_weight() -> None:
    reference = ClientHexReference(
        "新曹纯",
        {"地主": 7.4, "主公": 6.7, "忠臣": 6.8},
    )

    assert reference.role_scores["地主"] == pytest.approx(7.4)
    assert reference.source is HexScoreSource.CLIENT_DIRECT_DISPLAY
    assert reference.evidence_status == "分析约定"
    assert reference.is_raw_win_rate is False
    assert reference.is_official_strength_conclusion is False
    assert "低权重外部参考" in reference.disclosure
    assert "不是真实胜率" in reference.disclosure
    with pytest.raises(TypeError):
        reference.role_scores["地主"] = 9.0  # type: ignore[index]


def test_legacy_manual_hex_reference_rejects_half_score() -> None:
    with pytest.raises(ValueError, match="只记录整数分"):
        ClientHexReference(
            "旧式图武将",
            {"主公": 6.5},
            source=HexScoreSource.LEGACY_MANUAL_GRAPH,
        )


def test_new_caochun_reference_keeps_all_six_user_provided_values() -> None:
    assert dict(NEW_CAOCHUN_CLIENT_HEX_REFERENCE.role_scores) == pytest.approx(
        {
            "地主": 7.4,
            "主公": 6.7,
            "忠臣": 6.8,
            "反贼": 6.4,
            "内奸": 6.7,
            "农民": 7.0,
        }
    )
    assert NEW_CAOCHUN_CLIENT_HEX_REFERENCE.is_raw_win_rate is False


def test_public_package_exports_mode_evaluation_interfaces() -> None:
    names = (
        "standard_spy_server_reward",
        "summarize_standard_spy_rewards",
        "evaluate_landlord_suitability",
        "audit_main_evaluation_pool",
        "NEW_CAOCHUN_CLIENT_HEX_REFERENCE",
    )
    assert all(name in scripts.__all__ for name in names)
    assert all(hasattr(scripts, name) for name in names)
