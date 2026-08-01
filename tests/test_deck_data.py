from collections import Counter
from dataclasses import replace
from fractions import Fraction
from math import comb
from pathlib import Path

import pytest

from scripts import (
    DeckRecord,
    count_by_field,
    draw_without_replacement,
    exact_probability_at_least_one,
    load_deck_csv,
    probability_at_least_one_by_field,
    validate_deck_records,
)


DECK_ID = "sgs_mobile_non_special_20260725_unofficial"
DECK_PATH = (
    Path(__file__).resolve().parents[1]
    / "knowledge"
    / "三国杀牌堆数据.csv"
)


@pytest.fixture(scope="module")
def actual_deck() -> tuple[tuple[DeckRecord, ...], object]:
    return load_deck_csv(DECK_PATH, expected_total=160)


def test_actual_deck_total_and_full_group_counts(actual_deck) -> None:
    records, audit = actual_deck

    assert len(records) == 160
    assert audit.total_quantity == 160
    assert audit.expected_total == 160
    assert audit.is_valid
    assert audit.issues == ()
    assert audit.counts_by_card_name == {
        "丈八蛇矛": 1,
        "万箭齐发": 1,
        "五谷丰登": 2,
        "仁王盾": 1,
        "借刀杀人": 2,
        "八卦阵": 2,
        "兵粮寸断": 2,
        "决斗": 3,
        "南蛮入侵": 3,
        "古锭刀": 1,
        "大宛": 1,
        "寒冰剑": 1,
        "方天画戟": 1,
        "无中生有": 4,
        "无懈可击": 7,
        "朱雀羽扇": 1,
        "杀": 30,
        "桃": 12,
        "桃园结义": 1,
        "火攻": 3,
        "火杀": 5,
        "爪黄飞电": 1,
        "白银狮子": 1,
        "的卢": 1,
        "紫骍": 1,
        "绝影": 1,
        "贯石斧": 1,
        "赤兔": 1,
        "过河拆桥": 6,
        "酒": 5,
        "铁索连环": 6,
        "闪": 24,
        "闪电": 2,
        "雌雄双股剑": 1,
        "雷杀": 9,
        "青釭剑": 1,
        "青龙偃月刀": 1,
        "顺手牵羊": 5,
        "骅骝": 1,
        "麒麟弓": 1,
        "乐不思蜀": 3,
        "藤甲": 2,
        "诸葛连弩": 2,
    }
    assert audit.counts_by_card_type == {
        "基本牌": 85,
        "装备牌": 25,
        "锦囊牌": 50,
    }
    assert audit.counts_by_color == {"红": 80, "黑": 80}
    assert audit.counts_by_suit == {"♠": 40, "♣": 40, "♥": 40, "♦": 40}
    assert sum(audit.counts_by_card_name.values()) == 160
    assert sum(audit.counts_by_card_type.values()) == 160
    assert sum(audit.counts_by_color.values()) == 160
    assert sum(audit.counts_by_suit.values()) == 160


def test_actual_deck_rank_variant_and_metadata_counts(actual_deck) -> None:
    records, _ = actual_deck

    assert count_by_field(records, deck_id=DECK_ID, field="rank") == {
        "10": 12,
        "2": 14,
        "3": 12,
        "4": 12,
        "5": 12,
        "6": 12,
        "7": 12,
        "8": 12,
        "9": 12,
        "A": 12,
        "J": 12,
        "K": 12,
        "Q": 14,
    }
    assert count_by_field(
        records, deck_id=DECK_ID, field="card_variant"
    ) == {"EX扩展": 4, "无": 156}
    assert {
        (
            record.deck_id,
            record.platform,
            record.mode,
            record.version,
            record.effective_date,
        )
        for record in records
    } == {
        (
            DECK_ID,
            "三国杀移动版",
            "常规军争身份模式；排位2v2；斗地主；八人军争限时变体",
            "2026-07-25时的版本",
            "2026-07-25",
        )
    }
    assert {record.source for record in records} == {
        "初始来源为非官方网络UP主转录；后经用户与实际卡牌逐张核对"
    }
    assert {record.verification_status for record in records} == {
        "user_verified_against_actual_cards"
    }
    assert {record.source_type for record in records} == {
        "unofficial_transcription_then_user_verified"
    }
    assert {record.verified_date for record in records} == {"2026-07-27"}
    assert len({record.instance_id for record in records}) == 160
    assert all(record.quantity == 1 for record in records)
    assert all(
        str(getattr(record, field)).strip()
        for record in records
        for field in (
            "deck_id",
            "platform",
            "mode",
            "version",
            "effective_date",
            "card_name",
            "card_variant",
            "card_type",
            "suit",
            "color",
            "rank",
            "instance_id",
            "card_key",
            "source",
            "source_type",
            "verification_status",
            "verified_date",
            "notes",
        )
    )


def test_named_mounts_map_to_two_distinct_equipment_slots(actual_deck) -> None:
    records, _ = actual_deck
    mounts = {record.card_name: record for record in records if record.equip_slot.endswith("horse")}

    assert {name for name, row in mounts.items() if row.equip_slot == "attack_horse"} == {
        "紫骍",
        "赤兔",
        "大宛",
    }
    assert {name for name, row in mounts.items() if row.equip_slot == "defense_horse"} == {
        "骅骝",
        "的卢",
        "爪黄飞电",
        "绝影",
    }
    assert {row.distance_modifier for row in mounts.values() if row.equip_slot == "attack_horse"} == {"-1"}
    assert {row.distance_modifier for row in mounts.values() if row.equip_slot == "defense_horse"} == {"+1"}
    assert {row.card_key for row in mounts.values() if row.equip_slot == "attack_horse"} == {"sgs_mount_offensive"}
    assert {row.card_key for row in mounts.values() if row.equip_slot == "defense_horse"} == {"sgs_mount_defensive"}


def test_four_ex_cards_use_user_confirmed_suits_and_ranks(actual_deck) -> None:
    records, _ = actual_deck
    ex_cards = {
        (record.suit, record.rank, record.card_name)
        for record in records
        if record.card_variant == "EX扩展"
    }

    assert ex_cards == {
        ("♦", "Q", "无懈可击"),
        ("♣", "2", "仁王盾"),
        ("♥", "Q", "闪电"),
        ("♠", "2", "寒冰剑"),
    }


def test_probability_of_at_least_one_named_card_is_exact(actual_deck) -> None:
    records, _ = actual_deck
    result = probability_at_least_one_by_field(
        records,
        deck_id=DECK_ID,
        field="card_name",
        value="桃园结义",
        draw_count=4,
    )

    assert result.known_matching_quantity == 1
    assert result.unresolved_quantity == 0
    assert result.probability == Fraction(1, 40)
    assert result.is_exact


def test_without_replacement_formula_and_full_deck_draw(actual_deck) -> None:
    records, _ = actual_deck
    assert exact_probability_at_least_one(4, 2, 2) == Fraction(5, 6)

    expanded = [
        record.card_name
        for record in records
        for _ in range(record.quantity)
    ]
    drawn = draw_without_replacement(expanded, 160, seed=20260725)
    assert Counter(drawn) == Counter(expanded)
    with pytest.raises(ValueError, match="不能超过"):
        draw_without_replacement(expanded, 161, seed=20260725)


def test_probability_by_color_uses_all_quantities(actual_deck) -> None:
    records, _ = actual_deck
    one_draw = probability_at_least_one_by_field(
        records,
        deck_id=DECK_ID,
        field="color",
        value="红",
        draw_count=1,
    )
    two_draws = probability_at_least_one_by_field(
        records,
        deck_id=DECK_ID,
        field="color",
        value="红",
        draw_count=2,
    )

    assert one_draw.probability == Fraction(1, 2)
    assert two_draws.probability == 1 - Fraction(comb(80, 2), comb(160, 2))


def test_probability_by_structured_card_type(actual_deck) -> None:
    records, _ = actual_deck
    result = probability_at_least_one_by_field(
        records,
        deck_id=DECK_ID,
        field="card_type",
        value="基本牌",
        draw_count=1,
    )

    # 这是对 CSV 中结构化分类的计算，不把该分类称为当前版本官方核验。
    assert result.known_matching_quantity == 85
    assert result.probability == Fraction(85, 160)


def test_audit_detects_duplicate_empty_conflict_and_total_difference(
    actual_deck,
) -> None:
    records, _ = actual_deck
    first = records[0]

    duplicate = validate_deck_records((*records, first), expected_total=161)
    assert any(issue.code == "duplicate_record" for issue in duplicate.errors)

    empty = validate_deck_records(
        (replace(first, source=""),), expected_total=1
    )
    assert any(issue.code == "empty_field" for issue in empty.errors)

    conflict = validate_deck_records(
        (first, replace(first, card_type="测试冲突类别")),
        expected_total=2,
    )
    assert any(issue.code == "conflicting_record" for issue in conflict.errors)

    mismatch = validate_deck_records(records, expected_total=159)
    total_issue = next(
        issue for issue in mismatch.errors if issue.code == "total_mismatch"
    )
    assert "160" in total_issue.message
    assert "159" in total_issue.message
    assert "+1" in total_issue.message


def test_same_deck_id_rejects_mixed_version_metadata(actual_deck) -> None:
    records, _ = actual_deck
    mixed_version = validate_deck_records(
        (records[0], replace(records[1], version="另一个版本")),
        expected_total=2,
    )

    assert any(
        issue.code == "deck_metadata_conflict"
        for issue in mixed_version.errors
    )
    with pytest.raises(ValueError, match="多个平台、模式、版本或日期"):
        count_by_field(
            (records[0], replace(records[1], version="另一个版本")),
            deck_id=DECK_ID,
            field="card_name",
        )


def test_queries_never_mix_two_deck_ids(actual_deck) -> None:
    records, _ = actual_deck
    first = records[0]
    other = replace(
        records[1],
        deck_id="another_deck",
        platform="另一个平台",
        version="另一个版本",
        effective_date="2026-07-26",
    )

    assert count_by_field(
        (first, other), deck_id=DECK_ID, field="card_name"
    ) == {first.card_name: first.quantity}
    probability = probability_at_least_one_by_field(
        (first, other),
        deck_id="another_deck",
        field="card_name",
        value=other.card_name,
        draw_count=1,
    )
    assert probability.deck_size == other.quantity
    assert probability.probability == 1


def test_field_with_unresolved_values_returns_probability_bounds(
    actual_deck,
) -> None:
    records, _ = actual_deck
    one_unknown_rank = replace(records[0], rank="待核验")
    report = validate_deck_records((one_unknown_rank,))
    result = probability_at_least_one_by_field(
        (one_unknown_rank,),
        deck_id=DECK_ID,
        field="rank",
        value="A",
        draw_count=1,
    )

    assert report.unresolved_quantity_by_field["rank"] == 1
    assert result.probability is None
    assert result.lower_bound == 0
    assert result.upper_bound == 1


@pytest.mark.parametrize(
    ("population", "matching", "draws", "message"),
    [
        (4, 5, 1, "匹配牌数不能超过"),
        (4, 1, 5, "抽取数量不能超过"),
        (4, 1, -1, "抽取数量"),
    ],
)
def test_exact_probability_rejects_invalid_inputs(
    population: int,
    matching: int,
    draws: int,
    message: str,
) -> None:
    with pytest.raises((TypeError, ValueError), match=message):
        exact_probability_at_least_one(population, matching, draws)
