import csv
import re
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
KNOWLEDGE = ROOT / "knowledge"
MODE_PATH = KNOWLEDGE / "三国杀模式规则.md"
TERMS_PATH = KNOWLEDGE / "三国杀基础术语与通用机制.md"
CARDS_PATH = KNOWLEDGE / "三国杀卡牌效果.md"
SIMULATION_PATH = KNOWLEDGE / "三国杀模拟规范.md"
CARD_DATA_PATH = KNOWLEDGE / "三国杀卡牌结构化数据.csv"

ALLOWED_STATUSES = {
    "当前确认",
    "用户整理解释",
    "文本推导",
    "模拟假设",
    "待核验",
    "历史规则",
    "分析约定",
}


@pytest.fixture(scope="module")
def sgs_documents() -> dict[str, str]:
    return {
        "mode": MODE_PATH.read_text(encoding="utf-8"),
        "terms": TERMS_PATH.read_text(encoding="utf-8"),
        "cards": CARDS_PATH.read_text(encoding="utf-8"),
        "simulation": SIMULATION_PATH.read_text(encoding="utf-8"),
    }


def _heading_levels(text: str) -> list[int]:
    return [
        len(match.group(1))
        for line in text.splitlines()
        if (match := re.match(r"^(#{1,6})\s+\S", line))
    ]


def test_new_knowledge_documents_have_valid_heading_hierarchy(
    sgs_documents,
) -> None:
    for text in sgs_documents.values():
        levels = _heading_levels(text)
        assert levels.count(1) == 1
        assert levels[0] == 1
        assert all(
            current <= previous + 1
            for previous, current in zip(levels, levels[1:])
        )


def test_new_knowledge_documents_only_use_allowed_status_labels(
    sgs_documents,
) -> None:
    for name, text in sgs_documents.items():
        statuses = {
            match.group(1).strip()
            for match in re.finditer(r"状态：([^*\r\n]+)", text)
        }
        assert statuses, f"{name} 没有可审计的状态标签"
        assert statuses <= ALLOWED_STATUSES


def test_new_knowledge_documents_contain_no_jump_or_tracking_links(
    sgs_documents,
) -> None:
    forbidden = ("http://", "https://", "zhihu", "utm_", "target=")
    for text in sgs_documents.values():
        lowered = text.lower()
        assert all(token not in lowered for token in forbidden)


def test_mode_and_basic_rules_are_kept_in_separate_documents(
    sgs_documents,
) -> None:
    mode = sgs_documents["mode"]
    terms = sgs_documents["terms"]
    cards = sgs_documents["cards"]

    assert "## 2. 2v2排位模式" in mode
    assert "## 3. 斗地主模式" in mode
    assert "## 4. 军争身份模式" in mode
    assert "## 5. 移动版八人军争特殊玩法：主公立储与内奸择途" in mode
    assert "## 6. 两种模式共用的换将卡规则" in mode
    assert "叫地主" not in terms
    assert "手气卡" not in terms
    assert "换将卡" not in terms
    assert "### 7.1 【诸葛连弩】" in cards
    assert "### 8.1 【八卦阵】" in cards
    assert "### 9.1 【攻击坐骑（-1坐骑）】" in cards


def test_required_metadata_is_preserved(sgs_documents) -> None:
    mode = sgs_documents["mode"]
    for expected in (
        "游戏平台：三国杀移动版",
        "适用模式：2v2排位、斗地主、军争身份模式",
        "其他服务器或桌游版规则，仅在对应章节明确说明时适用",
        "整理日期：2026-07-25",
        "来源类型：用户个人总结与游戏内观察",
        "官方统一来源：未提供",
        "资料完整性：可能仍有遗漏",
    ):
        assert expected in mode

    for text in (sgs_documents["terms"], sgs_documents["cards"]):
        for expected in (
            "主要游戏平台：三国杀移动版",
            "其他服务器或桌游版：仅在对应章节明确说明时适用",
            "适用版本：用户确认规则集",
            "整理日期：2026-07-25",
            "来源类型：用户摘取、修改并整理的通俗说明",
            "是否官方原文：否",
            "用途：私人 GPT 进行规则理解、收益分析和概率模拟",
            "资料完整性：只包含本次用户提供的内容，可能存在遗漏",
        ):
            assert expected in text


def test_resolved_landlord_seating_is_not_kept_as_pending(
    sgs_documents,
) -> None:
    combined = "\n".join(sgs_documents.values())
    mode = sgs_documents["mode"]
    for confirmed_rule in (
        "三名玩家在叫地主前已经具有固定的物理环形座位",
        "将最终地主所在的物理位置定义为1号位",
        "下一名玩家为2号位",
        "上一名玩家为3号位",
    ):
        assert confirmed_rule in combined

    for resolved_topic in (
        "农民2、3号位分配机制状态：待核验",
        "目前不确定农民谁是2号位",
        "等概率随机分配到2、3号位",
        "农民2、3号位分配是否与叫地主顺序存在固定关联",
    ):
        assert resolved_topic not in mode

    assert "具体权重未知" in combined
    assert "未来是否常驻" in combined


def test_card_effect_document_has_exactly_one_section_per_card(
    sgs_documents,
) -> None:
    card_text = sgs_documents["cards"]
    heading_pattern = re.compile(
        r"^###\s+\d+\.\d+\s+【(.+?)】$",
        flags=re.MULTILINE,
    )
    headings = heading_pattern.findall(card_text)
    with CARD_DATA_PATH.open(encoding="utf-8", newline="") as handle:
        csv_names = {
            row["card_name"]
            for row in csv.DictReader(handle)
        }

    assert len(headings) == 38
    assert len(set(headings)) == 38
    assert set(headings) == csv_names

    required_fields = (
        "名称",
        "大类",
        "子类",
        "当前采用效果",
        "使用或触发时机",
        "目标",
        "响应方式",
        "伤害属性",
        "次数限制",
        "攻击范围",
        "特殊说明",
        "资料状态",
    )
    matches = list(heading_pattern.finditer(card_text))
    for index, match in enumerate(matches):
        end = (
            matches[index + 1].start()
            if index + 1 < len(matches)
            else card_text.find("\n## 10. 当前牌库适用范围", match.end())
        )
        section = card_text[match.end():end]
        for field in required_fields:
            assert f"- {field}：" in section


def test_all_trick_sections_use_generic_timing_and_limit_without_stale_reference(
    sgs_documents,
) -> None:
    cards = sgs_documents["cards"]
    assert "复杂结算应同时检查文末“待核验事项”" not in cards
    assert (
        "复杂结算应同时查询《三国杀基础术语与通用机制》和"
        "《三国杀模拟规范》中对应的通用结算与计算策略章节"
    ) in cards

    section_pattern = re.compile(
        r"^###\s+\d+\.\d+\s+【(?P<name>.+?)】\n(?P<body>.*?)(?=^###\s+\d+\.\d+\s+【|^##\s+10\.)",
        flags=re.MULTILINE | re.DOTALL,
    )
    trick_sections = {
        match.group("name"): match.group("body")
        for match in section_pattern.finditer(cards)
        if "- 大类：锦囊牌" in match.group("body")
    }
    assert len(trick_sections) == 15
    for name, section in trick_sections.items():
        assert "- 次数限制：无基础每回合使用次数限制" in section
        assert "使用时机未提供" not in section
        if name == "无懈可击":
            assert "仅在合法锦囊结算响应窗口使用或打出" in section
            assert "不能在无响应对象时主动使用" in section
        else:
            assert "自己的出牌阶段主动" in section
            assert "继承锦囊通用时机" in section


def test_succession_and_chain_strategy_documents_preserve_layering(
    sgs_documents,
) -> None:
    mode = sgs_documents["mode"]
    cards = sgs_documents["cards"]
    simulation = sgs_documents["simulation"]

    assert "暂不确认其死亡、不清空其区域内的牌" in mode
    assert "在正式确认原主公死亡之前，检查是否存在合法储君继位" in mode
    assert "新主公身份立即公开，并立即更新当前主公记录" in mode
    assert "不得先判反贼胜利或先清空原主公区域再继位" in simulation
    for strategy in ("只横置敌方", "自我引火", "友军引火", "保留或重铸"):
        assert strategy in simulation
    assert "本节是决策策略，不是【铁索连环】或【火攻】的强制卡牌效果" in simulation
    assert "自我引火" not in cards
    assert "友军引火" not in cards
