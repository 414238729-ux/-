from __future__ import annotations

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
KNOWLEDGE = ROOT / "knowledge"
SUMMARY = KNOWLEDGE / "三国杀增量规则整理_第二次汇总之后.md"
BASE = KNOWLEDGE / "三国杀基础术语与通用机制.md"
INSTRUCTIONS = ROOT / "GPT_INSTRUCTIONS.md"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_increment_summary_is_complete_unique_and_not_tool_truncated() -> None:
    text = _read(SUMMARY)
    assert text.startswith("# 三国杀增量规则整理（第二次汇总之后）")
    assert "truncated" not in text
    assert "六、徐荣" in text
    assert "七、王经" in text
    assert "八、文鸯：魏、吴双势力路线" in text
    assert "九、主公武将规则摘要" in text
    assert "十、鲍信" in text
    assert "十一、谋皇甫嵩" in text
    assert "十四、仍需保留的未知与防误写项" in text
    assert len(list(KNOWLEDGE.glob("三国杀增量规则整理_第二次汇总之后*.md"))) == 1


def test_increment_summary_has_unique_headings_and_project_status_labels() -> None:
    text = _read(SUMMARY)
    headings = [line for line in text.splitlines() if re.match(r"^#{1,6}\s", line)]
    assert len(headings) == len(set(headings))
    allowed = {
        "当前确认",
        "用户整理解释",
        "文本推导",
        "模拟假设",
        "待核验",
        "历史规则",
        "分析约定",
    }
    standalone_labels = {
        match.group(1)
        for match in re.finditer(r"^【([^】]+)】$", text, flags=re.MULTILINE)
    }
    assert standalone_labels <= allowed
    assert text.count("用户提供的既有模拟结果摘要（本轮未重新运行）") == 3


def test_increment_summary_keeps_xuyou_pool_and_information_corrections() -> None:
    text = _read(SUMMARY)
    assert "正式基础体力与基础体力上限唯一为`3/3`" in text
    assert "成为主公或地主并取得对应模式的体力与上限各加1后为`4/4`" in text
    assert "加入鲍信后为13个普通武将名额" in text
    assert "谋皇甫嵩正式通过后才扩展为14个名额" in text
    assert "有桃或无桃" in text
    assert "确认队友当前手牌中的【杀】数量" in text
    assert "不自动公开完整手牌" in text


def test_base_terms_route_new_generic_resolution_boundaries() -> None:
    text = _read(BASE)
    for phrase in (
        "角色与自己的实际距离为 0",
        "original_card_name",
        "current_card_name",
        "use_as_card_name",
        "来源角色死亡不自动删除或取消",
        "skill_activator",
        "翻开的判定牌与发起判定的延时锦囊本体",
    ):
        assert phrase in text


def test_instructions_only_adds_increment_route_and_stays_compact() -> None:
    text = _read(INSTRUCTIONS)
    assert "三国杀增量规则整理_第二次汇总之后.md" in text
    assert len(text) <= 7000
