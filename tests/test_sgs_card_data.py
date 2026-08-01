import csv
from pathlib import Path

import pandas as pd

from scripts.sgs_structured_data import link_card_definitions_and_use_modes


CARD_DATA_PATH = (
    Path(__file__).resolve().parents[1]
    / "knowledge"
    / "三国杀卡牌结构化数据.csv"
)
USE_MODE_PATH = CARD_DATA_PATH.with_name("三国杀卡牌使用方式.csv")

EXPECTED_FIELDS = (
    "card_id",
    "card_name",
    "category",
    "subtype",
    "attack_range",
    "use_timing",
    "trigger_timing",
    "target_rule",
    "response_card",
    "base_effect",
    "damage_amount",
    "damage_type",
    "use_limit",
    "specific_timing",
    "inherits_generic_timing",
    "base_use_limit",
    "inherits_generic_use_limit",
    "response_only",
    "skill_override_allowed",
    "can_recast",
    "equipment_slot",
    "delayed_trick",
    "placement_zone",
    "judgment_condition",
    "success_effect",
    "failure_effect",
    "transfer_rule",
    "skipped_phase",
    "confidence_status",
    "source_type",
    "notes",
    "use_context",
    "default_timing",
    "response_window",
    "can_be_responded_by_card",
    "can_be_invalidated_by_skill",
    "counts_as_used_if_invalidated",
    "effect_resolved_if_invalidated",
    "after_resolution_trigger_if_invalidated",
    "inherits_generic_rule",
    "use_modes",
    "is_static_damage_card",
    "is_damage_trick",
    "is_normal_trick",
    "is_delayed_trick",
    "target_template",
    "distance_rule_source",
    "uses_attack_range",
    "can_target_self",
    "converted_slash_uses_limit",
    "wufei_source_replacement_eligible",
)

EXPECTED_CARD_NAMES = {
    "杀",
    "雷杀",
    "火杀",
    "闪",
    "桃",
    "酒",
    "过河拆桥",
    "顺手牵羊",
    "决斗",
    "火攻",
    "铁索连环",
    "借刀杀人",
    "无中生有",
    "南蛮入侵",
    "万箭齐发",
    "五谷丰登",
    "桃园结义",
    "无懈可击",
    "乐不思蜀",
    "兵粮寸断",
    "闪电",
    "诸葛连弩",
    "青釭剑",
    "寒冰剑",
    "雌雄双股剑",
    "古锭刀",
    "青龙偃月刀",
    "贯石斧",
    "丈八蛇矛",
    "方天画戟",
    "朱雀羽扇",
    "麒麟弓",
    "八卦阵",
    "仁王盾",
    "白银狮子",
    "藤甲",
    "攻击坐骑（-1坐骑）",
    "防御坐骑（+1坐骑）",
}

ALLOWED_STATUSES = {
    "当前确认",
    "用户整理解释",
    "文本推导",
    "模拟假设",
    "待核验",
    "历史规则",
    "分析约定",
}


def _read_with_standard_csv() -> tuple[list[str], list[dict[str, str]]]:
    with CARD_DATA_PATH.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
    assert reader.fieldnames is not None
    return reader.fieldnames, rows


def test_structured_card_csv_is_readable_by_standard_csv() -> None:
    fieldnames, rows = _read_with_standard_csv()

    assert tuple(fieldnames) == EXPECTED_FIELDS
    assert len(rows) == 38
    assert all(None not in row for row in rows)
    assert all(value is not None for row in rows for value in row.values())
    assert all(len(row) == len(EXPECTED_FIELDS) for row in rows)


def test_structured_card_csv_is_readable_by_pandas() -> None:
    frame = pd.read_csv(
        CARD_DATA_PATH,
        dtype=str,
        keep_default_na=False,
        encoding="utf-8",
    )

    assert tuple(frame.columns) == EXPECTED_FIELDS
    assert frame.shape == (38, len(EXPECTED_FIELDS))
    assert not frame["card_name"].str.strip().eq("").any()
    assert not frame["category"].str.strip().eq("").any()


def test_structured_card_csv_has_exactly_the_user_supplied_cards() -> None:
    _, rows = _read_with_standard_csv()

    names = {row["card_name"] for row in rows}
    assert names == EXPECTED_CARD_NAMES
    assert len(names) == len(rows)


def test_structured_card_csv_has_unique_ids_and_allowed_statuses() -> None:
    _, rows = _read_with_standard_csv()
    card_ids = [row["card_id"] for row in rows]

    assert len(card_ids) == len(set(card_ids))
    assert all(card_id.strip() for card_id in card_ids)
    assert {row["confidence_status"] for row in rows} <= ALLOWED_STATUSES
    assert {row["source_type"] for row in rows} == {
        "用户整理并修订的规则说明"
    }


def test_delayed_tricks_preserve_the_confirmed_status_and_no_deck_fields() -> None:
    fieldnames, rows = _read_with_standard_csv()
    delayed = {
        row["card_name"]: row
        for row in rows
        if row["subtype"] == "延时锦囊"
    }

    assert set(delayed) == {"乐不思蜀", "兵粮寸断", "闪电"}
    assert {
        row["confidence_status"] for row in delayed.values()
    } == {"当前确认"}
    assert {"suit", "rank", "quantity"}.isdisjoint(fieldnames)


def test_structured_fields_preserve_ranges_and_explicit_unknowns() -> None:
    _, rows = _read_with_standard_csv()
    by_name = {row["card_name"]: row for row in rows}

    expected_weapon_ranges = {
        "诸葛连弩": "1",
        "青釭剑": "2",
        "寒冰剑": "2",
        "雌雄双股剑": "2",
        "古锭刀": "2",
        "青龙偃月刀": "3",
        "贯石斧": "3",
        "丈八蛇矛": "3",
        "方天画戟": "4",
        "朱雀羽扇": "4",
        "麒麟弓": "5",
    }
    assert {
        name: by_name[name]["attack_range"]
        for name in expected_weapon_ranges
    } == expected_weapon_ranges

    assert by_name["顺手牵羊"]["attack_range"] == ""
    assert by_name["顺手牵羊"]["use_timing"] == "出牌阶段"
    assert by_name["火攻"]["use_timing"] == "出牌阶段"
    assert by_name["无懈可击"]["trigger_timing"] == (
        "锦囊牌即将对一名角色产生效果时；"
        "延时锦囊在判定阶段即将判定前"
    )
    assert by_name["南蛮入侵"]["damage_type"] == "无属性"
    assert by_name["万箭齐发"]["damage_type"] == "无属性"


def test_revised_card_records_match_confirmed_precision_rules() -> None:
    _, rows = _read_with_standard_csv()
    by_name = {row["card_name"]: row for row in rows}

    nullification = by_name["无懈可击"]
    assert nullification["confidence_status"] == "当前确认"
    assert "多目标锦囊逐名结算" in nullification["notes"]
    assert "多目标锦囊的精确结算待核验" not in nullification["notes"]

    for name, skipped_phase in (
        ("乐不思蜀", "出牌阶段"),
        ("兵粮寸断", "摸牌阶段"),
    ):
        row = by_name[name]
        assert row["response_card"] == "无懈可击"
        assert "置入弃牌堆" in row["success_effect"]
        assert "置入弃牌堆" in row["failure_effect"]
        assert row["transfer_rule"] == (
            "被无懈或判定完成后置入弃牌堆；不转移"
        )
        assert row["skipped_phase"] == skipped_phase

    lightning = by_name["闪电"]
    assert lightning["response_card"] == "无懈可击"
    assert "判定命中后置入弃牌堆" in lightning["transfer_rule"]
    assert "被无懈或判定未命中时移至下家判定区" in (
        lightning["transfer_rule"]
    )

    stone_axe = by_name["贯石斧"]
    assert stone_axe["confidence_status"] == "当前确认"
    assert "不能选择判定区内的牌" in stone_axe["notes"]

    serpent_spear = by_name["丈八蛇矛"]
    assert serpent_spear["confidence_status"] == "当前确认"
    assert "均无花色、无点数" in serpent_spear["notes"]
    assert "不得继承、合计或另行生成" in serpent_spear["notes"]


def test_latest_distance_damage_source_and_armor_rules_are_structured() -> None:
    _, rows = _read_with_standard_csv()
    by_name = {row["card_name"]: row for row in rows}

    for name in ("顺手牵羊", "兵粮寸断"):
        row = by_name[name]
        assert "与使用者实际距离为1的一名其他角色" in row["target_rule"]
        assert "武器攻击范围不影响" in row["notes"]
        assert row["confidence_status"] == "当前确认"

    fire_attack = by_name["火攻"]
    assert fire_attack["target_rule"] == "一名有至少一张手牌的角色，可包括自己"
    assert "结算到展示步骤时若目标已无手牌" in fire_attack["notes"]
    assert fire_attack["confidence_status"] == "当前确认"

    for name in ("南蛮入侵", "万箭齐发"):
        row = by_name[name]
        assert row["damage_type"] == "无属性"
        assert "默认伤害来源为使用者" in row["notes"]
        assert "藤甲仍令此牌无效" in row["notes"]
        assert row["confidence_status"] == "当前确认"

    silver_lion = by_name["白银狮子"]
    assert "无属性、火属性或雷属性" in silver_lion["base_effect"]
    assert "失去体力不属于伤害" in silver_lion["notes"]
    assert "以任何方式离开装备区" in silver_lion["base_effect"]
    assert silver_lion["confidence_status"] == "当前确认"

    vine = by_name["藤甲"]
    assert "藤甲无效判定前已转为属性【杀】" in vine["notes"]
    assert "仅在伤害阶段转换属性" in vine["notes"]
    assert vine["confidence_status"] == "当前确认"

    lightning = by_name["闪电"]
    assert "该伤害没有伤害来源" in lightning["notes"]

    duel = by_name["决斗"]
    assert duel["damage_type"] == "无属性"
    assert "未注明属性" in duel["notes"]

    assert all(
        row["damage_type"].strip()
        for row in rows
        if row["damage_amount"].strip()
    )


def test_all_tricks_inherit_explicit_generic_timing_and_use_limit() -> None:
    _, rows = _read_with_standard_csv()
    tricks = [row for row in rows if row["category"] == "锦囊牌"]

    assert len(tricks) == 15
    assert all(row["base_use_limit"] == "unlimited" for row in tricks)
    assert all(row["inherits_generic_use_limit"] == "true" for row in tricks)
    assert all(row["skill_override_allowed"] == "true" for row in tricks)
    assert all(row["use_limit"] == "无基础每回合次数限制" for row in tricks)

    nullification = next(row for row in tricks if row["card_name"] == "无懈可击")
    assert nullification["specific_timing"] == "trick_response_window"
    assert nullification["inherits_generic_timing"] == "false"
    assert nullification["response_only"] == "true"
    assert nullification["use_timing"] == "合法锦囊响应窗口"

    active_tricks = [row for row in tricks if row["card_name"] != "无懈可击"]
    assert all(row["specific_timing"] == "" for row in active_tricks)
    assert all(
        row["inherits_generic_timing"] == "trick_play_phase"
        for row in active_tricks
    )
    assert all(row["response_only"] == "false" for row in active_tricks)
    assert all(row["use_timing"] == "出牌阶段" for row in active_tricks)
    assert all("使用时机未提供" not in row["notes"] for row in tricks)


def test_peach_wine_and_equipment_have_explicit_use_semantics() -> None:
    _, rows = _read_with_standard_csv()
    by_name = {row["card_name"]: row for row in rows}

    for name in ("桃", "酒"):
        row = by_name[name]
        assert row["use_context"] == "multiple_modes"
        assert row["default_timing"] == "context_dependent"
        assert row["base_use_limit"] == "context_dependent"
        assert row["response_window"] == "none"
        assert row["can_be_responded_by_card"] == "false"
        assert row["can_be_invalidated_by_skill"] == "true"
        assert row["counts_as_used_if_invalidated"] == "true"
        assert row["effect_resolved_if_invalidated"] == "false"
        assert row["after_resolution_trigger_if_invalidated"] == "false"
        assert "未提供" not in row["response_card"]
        assert "未提供" not in row["use_limit"]

    bundle = link_card_definitions_and_use_modes(CARD_DATA_PATH, USE_MODE_PATH)
    peach_modes = {
        mode.use_mode: mode
        for mode in bundle.use_modes_by_key[by_name["桃"]["card_id"]]
    }
    assert set(peach_modes) == {
        "own_play_phase_self_heal",
        "dying_self_rescue",
        "rescue_other_dying_character",
    }
    assert all(mode.limit_count == "unlimited" for mode in peach_modes.values())
    assert peach_modes["own_play_phase_self_heal"].timing == "own_play_phase"
    assert peach_modes["own_play_phase_self_heal"].target_scope == "self"
    assert peach_modes["own_play_phase_self_heal"].condition == "wounded"
    assert peach_modes["dying_self_rescue"].target_scope == "self"
    assert peach_modes["dying_self_rescue"].condition == "dying"
    assert (
        peach_modes["rescue_other_dying_character"].target_scope
        == "other_dying_character"
    )
    assert (
        peach_modes["rescue_other_dying_character"].condition
        == "target_dying"
    )
    assert by_name["桃"]["use_modes"] == ""
    assert "未提供" not in by_name["桃"]["use_limit"]
    assert "未知" not in by_name["桃"]["use_limit"]

    wine_modes = {
        mode.use_mode: mode
        for mode in bundle.use_modes_by_key[by_name["酒"]["card_id"]]
    }
    assert wine_modes["dying_self_rescue"].limit_count == "unlimited"
    assert wine_modes["play_phase_slash_buff"].timing == "own_play_phase"
    assert wine_modes["play_phase_slash_buff"].limit_scope == "play_phase"
    assert wine_modes["play_phase_slash_buff"].limit_count == "1"
    assert by_name["酒"]["use_modes"] == ""

    equipment = [row for row in rows if row["category"] == "装备牌"]
    assert len(equipment) == 17
    assert all(row["use_context"] == "equip" for row in equipment)
    assert all(row["default_timing"] == "own_play_phase" for row in equipment)
    assert all(row["base_use_limit"] == "unlimited" for row in equipment)
    assert all(row["response_window"] == "none" for row in equipment)
    assert all(row["can_be_responded_by_card"] == "false" for row in equipment)
    assert all(row["can_be_invalidated_by_skill"] == "true" for row in equipment)
    assert all(row["counts_as_used_if_invalidated"] == "true" for row in equipment)
    assert all(row["effect_resolved_if_invalidated"] == "false" for row in equipment)
    assert all(
        row["after_resolution_trigger_if_invalidated"] == "false"
        for row in equipment
    )
    assert all(row["inherits_generic_rule"] == "true" for row in equipment)


def test_structured_card_csv_contains_no_web_links_or_tracking_parameters() -> None:
    text = CARD_DATA_PATH.read_text(encoding="utf-8")

    assert "http://" not in text
    assert "https://" not in text
    assert "zhihu" not in text.lower()
    assert "utm_" not in text.lower()


def test_v24_damage_trick_and_source_replacement_classification() -> None:
    _, rows = _read_with_standard_csv()
    by_name = {row["card_name"]: row for row in rows}

    normal_damage_tricks = {"决斗", "火攻", "南蛮入侵", "万箭齐发"}
    for name in normal_damage_tricks:
        row = by_name[name]
        assert row["is_static_damage_card"] == "true"
        assert row["is_damage_trick"] == "true"
        assert row["is_normal_trick"] == "true"
        assert row["is_delayed_trick"] == "false"
        assert row["wufei_source_replacement_eligible"] == "true"

    lightning = by_name["闪电"]
    assert lightning["is_static_damage_card"] == "true"
    assert lightning["is_damage_trick"] == "true"
    assert lightning["is_normal_trick"] == "false"
    assert lightning["is_delayed_trick"] == "true"
    assert lightning["wufei_source_replacement_eligible"] == "false"


def test_v24_conversion_fields_keep_original_target_and_distance_templates() -> None:
    _, rows = _read_with_standard_csv()
    by_name = {row["card_name"]: row for row in rows}

    assert by_name["五谷丰登"]["target_template"] == "all_characters"
    assert by_name["桃园结义"]["target_template"] == "all_wounded_characters"
    assert by_name["无中生有"]["target_template"] == "self"
    assert by_name["借刀杀人"]["target_template"] == (
        "armed_character_plus_designated_slash_target"
    )
    assert by_name["顺手牵羊"]["distance_rule_source"] == "actual_distance_1"
    assert by_name["借刀杀人"]["distance_rule_source"] == "original_trick_relation"
    assert all(
        by_name[name]["uses_attack_range"] == "false"
        for name in ("顺手牵羊", "借刀杀人", "五谷丰登")
    )
    assert all(
        by_name[name]["converted_slash_uses_limit"] == "true"
        for name in ("过河拆桥", "五谷丰登", "桃园结义", "借刀杀人")
    )


def test_v24_empty_structured_value_stays_unknown_for_unexpanded_edge() -> None:
    _, rows = _read_with_standard_csv()
    nullification = next(row for row in rows if row["card_name"] == "无懈可击")

    # V2.4 未展开【无谋】与【无懈可击】的特殊响应边界，不能自行填 true/false。
    assert nullification["converted_slash_uses_limit"] == ""
