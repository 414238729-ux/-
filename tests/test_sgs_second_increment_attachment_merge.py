from __future__ import annotations

from pathlib import Path

from scripts.sgs_general_rules import GENERAL_CANDIDATE_SLOTS, GENERAL_RULE_RECORDS


ROOT = Path(__file__).resolve().parents[1]
KNOWLEDGE = ROOT / "knowledge"
GENERAL_DOC = KNOWLEDGE / "三国杀武将规则补充.md"
BASE_DOC = KNOWLEDGE / "三国杀基础术语与通用机制.md"
MODE_DOC = KNOWLEDGE / "三国杀模式规则.md"
SIM_DOC = KNOWLEDGE / "三国杀模拟规范.md"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_xuyou_latest_three_three_overrides_attachment_old_four_everywhere_formal() -> None:
    record = GENERAL_RULE_RECORDS["xuyou"]
    assert (record.base_hp, record.base_max_hp) == (3, 3)
    section = _read(GENERAL_DOC).split("## 11. 许攸", 1)[1].split("## 12.", 1)[0]
    assert "- 基础体力：3" in section
    assert "- 基础体力上限：3" in section
    assert "推导为`4/4`" in section
    for stale in ("- 基础体力：4", "- 基础体力上限：4", "推导为`5/5`"):
        assert stale not in section


def test_base_terms_merge_damage_special_card_chain_and_lifecycle_boundaries() -> None:
    text = _read(BASE_DOC)
    for phrase in (
        "每造成 1 点伤害",
        "每个独立伤害事件只计算 1 次",
        "继承该原始实体牌及其归属信息",
        "每一名传导角色受到的伤害都应建立独立伤害事件标识",
        "武将牌旁的实体特殊牌",
        "默认公开",
        "不能使用牌",
        "不计入手牌数或手牌上限",
        "转化牌的实体牌名与属性",
        "effect_cancelled_by_nullification",
        "card_or_effect_invalidated",
        "card_use_completed",
        "effect_resolved",
    ):
        assert phrase in text


def test_mode_document_keeps_standard_eight_player_default_and_pre_game_health_bonus() -> None:
    text = _read(MODE_DOC)
    assert "常规八人测试默认采用标准八人军争" in text
    assert "用户未明确指定第5章限时变体时，不加载该章任何专属规则" in text
    assert "主公1、忠臣2、反贼4、内奸1" in text
    assert "游戏正式开始前" in text
    assert "不得另插入一项“地主体力+1”游戏内事件" in text
    assert "内奸实际获胜，记3个有效胜场" in text
    assert "不得把一次内奸胜利计算为4个有效胜场" in text


def test_simulation_document_contains_all_new_evaluation_and_current_ai_routes() -> None:
    text = _read(SIM_DOC)
    for phrase in (
        "S_raw = (L + F) / 2",
        "S_selectable = 0.9 * F",
        "S_selectable = 0.9 * L",
        "至少四分之三",
        "新版曹纯客户端直接显示参考值",
        "地主`7.4`",
        "统一AI武将与反制规范V2.2",
        "4! = 24",
        "联合枚举选择哪些花色",
        "允许保留本出牌阶段唯一一次发动机会",
        "删除“开局无条件强制完成完整武器阶梯”的策略",
    ):
        assert phrase in text


def test_candidate_pool_has_thirteen_unique_slots_and_excludes_unselected_names() -> None:
    assert len(GENERAL_CANDIDATE_SLOTS) == 13
    assert len(set(GENERAL_CANDIDATE_SLOTS)) == 13
    assert GENERAL_CANDIDATE_SLOTS.count("曹纯") == 1
    assert {"许攸", "清河公主", "傅佥", "谋·公孙瓒", "鲍信"} <= set(
        GENERAL_CANDIDATE_SLOTS
    )
    assert not {
        "谋·曹仁",
        "界徐盛",
        "神太史慈",
        "骧·张辽",
        "司马懿",
    } & set(GENERAL_CANDIDATE_SLOTS)


def test_only_one_formal_file_exists_for_each_sgs_knowledge_kind() -> None:
    expected = {
        "三国杀AI信息规则.md",
        "三国杀模拟规范.md",
        "三国杀模式规则.md",
        "三国杀基础术语与通用机制.md",
        "三国杀卡牌效果.md",
        "三国杀武将规则补充.md",
        "三国杀增量规则整理_第二次汇总之后.md",
        "三国杀卡牌结构化数据.csv",
        "三国杀卡牌使用方式.csv",
        "三国杀牌堆数据.csv",
    }
    actual = {path.name for path in KNOWLEDGE.iterdir() if path.name.startswith("三国杀")}
    assert actual == expected
    forbidden = ("副本", "新版", "备份", "copy", "时间戳")
    assert not any(any(marker in name for marker in forbidden) for name in actual)
