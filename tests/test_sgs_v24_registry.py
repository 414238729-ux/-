import pytest

from scripts.sgs_general_rules import (
    EXPERIMENTAL_GENERAL_NAMES,
    GENERAL_CANDIDATE_SLOTS,
    V24_FORMAL_RULE_CANDIDATES,
    V24_GENERAL_BASE_STATS,
    v24_general_base_stats,
)
from scripts.sgs_extended_rules import apply_lord_health_bonus
from scripts.sgs_modes import apply_landlord_health_bonus


def test_v24_formal_rule_candidates_are_registered_without_silent_pool_expansion() -> None:
    assert V24_FORMAL_RULE_CANDIDATES == {
        "势·孙綝",
        "势·辛宪英",
        "SP郭女王",
    }
    assert len(GENERAL_CANDIDATE_SLOTS) == 13
    assert V24_FORMAL_RULE_CANDIDATES.isdisjoint(GENERAL_CANDIDATE_SLOTS)


def test_unreleased_shen_lubu_is_isolated_from_all_formal_candidate_sets() -> None:
    assert EXPERIMENTAL_GENERAL_NAMES == {"神吕布重制原型"}
    assert EXPERIMENTAL_GENERAL_NAMES.isdisjoint(GENERAL_CANDIDATE_SLOTS)
    assert EXPERIMENTAL_GENERAL_NAMES.isdisjoint(V24_FORMAL_RULE_CANDIDATES)


def test_v24_confirmed_base_stats_use_initial_then_maximum_order() -> None:
    assert dict(V24_GENERAL_BASE_STATS) == {
        "势·孙綝": (4, 4),
        "势·辛宪英": (3, 3),
        "SP郭女王": (3, 3),
        "神吕布重制原型": (5, 5),
    }
    for name, expected in V24_GENERAL_BASE_STATS.items():
        assert v24_general_base_stats(name) == expected


def test_v24_base_stats_reject_unregistered_general() -> None:
    with pytest.raises(ValueError, match="没有已登记"):
        v24_general_base_stats("未登记武将")


def test_confirmed_v24_stats_feed_existing_lord_and_landlord_bonus_rules() -> None:
    sunchen_initial, sunchen_maximum = v24_general_base_stats("势·孙綝")
    landlord = apply_landlord_health_bonus(sunchen_maximum, sunchen_initial)
    lord = apply_lord_health_bonus(sunchen_maximum, sunchen_initial)
    assert (landlord.initial_hp, landlord.maximum_hp) == (5, 5)
    assert (lord.initial_hp, lord.maximum_hp) == (5, 5)

    xin_initial, xin_maximum = v24_general_base_stats("势·辛宪英")
    landlord_xin = apply_landlord_health_bonus(xin_maximum, xin_initial)
    assert (landlord_xin.initial_hp, landlord_xin.maximum_hp) == (4, 4)
