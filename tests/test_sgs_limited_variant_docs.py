from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODES = ROOT / "knowledge" / "三国杀模式规则.md"
TERMS = ROOT / "knowledge" / "三国杀基础术语与通用机制.md"
SPEC = ROOT / "knowledge" / "三国杀模拟规范.md"
DECK = ROOT / "knowledge" / "三国杀牌堆数据.csv"
INSTRUCTIONS = ROOT / "GPT_INSTRUCTIONS.md"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _variant_section() -> str:
    text = _read(MODES)
    return text.split(
        "## 5. 移动版八人军争特殊玩法：主公立储与内奸择途",
        1,
    )[1].split("## 6. 两种模式共用的换将卡规则", 1)[0]


def test_limited_variant_is_separate_from_standard_identity_rules() -> None:
    modes = _read(MODES)
    assert modes.count("## 5. 移动版八人军争特殊玩法：主公立储与内奸择途") == 1
    standard = modes.split("## 4. 军争身份模式", 1)[1].split(
        "## 5. 移动版八人军争特殊玩法：主公立储与内奸择途",
        1,
    )[0]
    for special_rule in ("立储", "储君", "内奸择途", "野心家标记"):
        assert special_rule not in standard


def test_variant_documents_mode_switch_and_confirmed_shared_deck() -> None:
    variant = _variant_section()
    spec = _read(SPEC)
    assert "mode_variant = mobile_8p_heir_and_spy_choice" in variant
    assert "mode_variant = mobile_8p_heir_and_spy_choice" in spec
    assert "只有显式启用" in variant
    assert "直接复用 `deck_id=sgs_mobile_non_special_20260725_unofficial`" in variant
    assert "不另建重复牌堆 CSV" in variant
    assert "复用 `deck_id=sgs_mobile_non_special_20260725_unofficial`" in spec
    assert "八人军争限时变体" in _read(DECK)
    assert "对照实卡逐张核验" in variant
    assert "官方发布或官方逐牌认证" in variant


def test_variant_locks_confirmed_succession_and_kill_reward_boundaries() -> None:
    variant = _variant_section()
    assert "濒死救援失败之后、正式确认死亡之前" in variant
    assert "不重新编号" in variant
    assert "不移动到原1号位" in variant
    assert "不能摸6张" in variant
    assert "同一次击杀最多因身份规则获得一次3张牌奖励" in variant

    metadata = variant.split("### 5.18 时间元数据与规则快照", 1)[1]
    assert "首次已知宣传或开启日期为2026-05-16" in metadata
    assert "版本号未提供不妨碍加载" in metadata
    assert "额外回合期间仍可立储" in metadata
    assert "本限时变体待核验事项" not in variant
    assert "储君继位后是否重新编号" not in variant
    assert "野心家击杀反贼是否叠加摸6张" not in variant


def test_latest_three_player_skill_threshold_replaces_old_wording() -> None:
    variant = _variant_section()
    assert "alive_player_count >= 3" in variant
    assert "当前存活人数不少于3人时生效" in variant
    assert "只剩2名存活角色时失效" in variant
    assert "界面文字" not in variant
    assert "界面原文" not in variant


def test_hidden_and_public_information_layers_are_distinct() -> None:
    variant = _variant_section()
    for expected in (
        "被立储者本人也不知道自己是储君",
        "全场会知道“已有一名内奸转化为忠臣”",
        "转忠者具体是谁不公开",
        "野心家转化生效后身份立即公开",
        "新主公继位后身份立即公开",
    ):
        assert expected in variant


def test_general_terms_define_state_mark_and_virtual_card_without_enabling_mode() -> None:
    terms = _read(TERMS)
    assert "## 20. 补充通用概念：身份、隐藏状态、特殊标记与虚拟牌" in terms
    assert "不得因为本文定义了这些概念，就在标准模式中自动启用" in terms
    assert "分别记录开局身份和当前真实身份" in terms
    assert "role_original" in _read(SPEC)
    assert "role_current" in _read(SPEC)
    assert "不放入手牌、装备区、判定区、牌堆或弃牌堆" in terms
    assert "虚拟牌可以被依赖“使用该牌”或“使用牌”的规则识别" in terms


def test_instructions_remain_compact_and_route_to_mode_knowledge() -> None:
    instructions = _read(INSTRUCTIONS)
    assert 5000 <= len(instructions) <= 6500
    assert "三国杀模式规则.md" in instructions
    assert "军争身份" in instructions
    for copied_detail in (
        "heir_player_id",
        "ambitionist_mark_available",
        "野心家击杀反贼时总共只摸3张",
    ):
        assert copied_detail not in instructions


def test_markdown_heading_levels_do_not_jump() -> None:
    for path in (MODES, TERMS, SPEC):
        previous = 0
        for line in _read(path).splitlines():
            if not line.startswith("#"):
                continue
            hashes, separator, _ = line.partition(" ")
            if not separator or set(hashes) != {"#"}:
                continue
            level = len(hashes)
            if previous:
                assert level <= previous + 1, f"{path.name} 标题发生跳级：{line}"
            else:
                assert level == 1
            previous = level
