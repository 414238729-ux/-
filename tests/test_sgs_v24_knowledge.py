from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
KNOWLEDGE = ROOT / "knowledge"


def _read(name: str) -> str:
    return (KNOWLEDGE / name).read_text(encoding="utf-8")


def test_v24_generals_have_one_formal_knowledge_entry_each() -> None:
    text = _read("三国杀武将规则补充.md")
    headings = (
        "## 32. 势·孙綝",
        "## 33. 势·辛宪英",
        "## 34. SP郭女王",
        "## 35. 神吕布重制原型（未上线实验规则）",
    )
    for heading in headings:
        assert text.count(heading) == 1


def test_v24_cross_general_event_model_is_documented() -> None:
    text = _read("三国杀基础术语与通用机制.md")
    assert "### 14.1 牌的使用者与伤害来源" in text
    assert "### 14.2 技能资格矩阵" in text
    assert "### 20.11 “获得牌时”与实际进入区域" in text
    assert "未实际进入原目标牌区" in text
    assert "card_user" in text
    assert "damage_source" in text


def test_v24_card_classification_is_a_single_shared_definition() -> None:
    text = _read("三国杀卡牌效果.md")
    section = text.split("### 4.13 普通伤害锦囊的分类口径", maxsplit=1)[1].split(
        "## 5.", maxsplit=1
    )[0]
    for card_name in ("【决斗】", "【火攻】", "【南蛮入侵】", "【万箭齐发】"):
        assert card_name in section
    assert "【闪电】" in section
    assert "延时锦囊" in section


def test_v24_strategy_and_strength_references_are_routed_to_simulation_spec() -> None:
    text = _read("三国杀模拟规范.md")
    for heading in (
        "#### 5.21.1 势·孙綝",
        "#### 5.21.2 势·辛宪英",
        "#### 5.21.4 SP郭女王",
        "#### 5.21.5 神吕布重制原型",
    ):
        assert heading in text
    assert "九级映射" in text
    assert "斗地主8.17" in text
    assert "2v2为8.75" in text
    assert "身份模式7.50" in text
    assert "实验" in text


def test_v24_pool_registration_does_not_silently_change_formal_random_pool() -> None:
    text = _read("三国杀模式规则.md")
    assert "当前13名正式普通候选池" in text
    assert "势·孙綝、势·辛宪英与SP郭女王" in text
    assert "不静默改动现有13名随机池" in text
    assert "神吕布重制原型只允许由实验开关显式加载" in text


def test_v24_confirmed_base_stats_replace_all_previous_pending_values() -> None:
    text = _read("三国杀武将规则补充.md")
    expected = {
        "## 32. 势·孙綝": ("基础体力：4", "基础体力上限：4"),
        "## 33. 势·辛宪英": ("基础体力：3", "基础体力上限：3"),
        "## 34. SP郭女王": ("基础体力：3", "基础体力上限：3"),
        "## 35. 神吕布重制原型（未上线实验规则）": ("基础体力：5", "基础体力上限：5"),
    }
    headings = tuple(expected)
    for index, heading in enumerate(headings):
        section = text.split(heading, maxsplit=1)[1]
        if index + 1 < len(headings):
            section = section.split(headings[index + 1], maxsplit=1)[0]
        for line in expected[heading]:
            assert line in section
        assert "基础体力：待核验" not in section
        assert "基础体力上限：待核验" not in section


def test_knowledge_has_no_attachment_version_copy() -> None:
    names = [path.name for path in KNOWLEDGE.iterdir() if path.is_file()]
    assert not any("V2.2" in name or "V2.4" in name or "pending" in name for name in names)
