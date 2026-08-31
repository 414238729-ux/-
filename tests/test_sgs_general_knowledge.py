from pathlib import Path

import scripts


ROOT = Path(__file__).resolve().parents[1]
KNOWLEDGE = ROOT / "knowledge"
GENERAL_DOC = KNOWLEDGE / "三国杀武将规则补充.md"
BASE_DOC = KNOWLEDGE / "三国杀基础术语与通用机制.md"
MODE_DOC = KNOWLEDGE / "三国杀模式规则.md"
SIM_DOC = KNOWLEDGE / "三国杀模拟规范.md"
INSTRUCTIONS = ROOT / "GPT_INSTRUCTIONS.md"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_only_one_formal_general_supplement_exists() -> None:
    candidates = [
        path
        for path in KNOWLEDGE.glob("*武将规则补充*.md")
        if path.is_file()
    ]
    assert candidates == [GENERAL_DOC]
    forbidden = ("新版", "副本", "备份", "copy", "最终版")
    assert not any(any(word in path.stem for word in forbidden) for path in candidates)


def test_general_document_preserves_thirteen_entries_and_adds_seventeen() -> None:
    text = _read(GENERAL_DOC)
    headings = (
        "## 2. 沙摩柯",
        "## 3. 诸葛瞻",
        "## 4. 界钟会",
        "## 5. 旧版曹纯",
        "## 6. 新版曹纯",
        "## 7. 王元姬",
        "## 8. 曹婴",
        "## 9. 张琪瑛",
        "## 10. 星·甘宁",
        "## 11. 许攸",
        "## 12. 清河公主",
        "## 13. 傅佥",
        "## 14. 谋·公孙瓒",
        "## 15. 徐荣",
        "## 16. 王经",
        "## 17. 文鸯（魏／吴双路线）",
        "## 18. 曹叡",
        "## 19. 谋袁绍",
        "## 20. 界曹丕",
        "## 21. 刘禅",
        "## 22. 界董卓",
        "## 23. 谋张角",
        "## 24. 孙亮",
        "## 25. 界孙休",
        "## 26. 谋孙策",
        "## 27. 界孙策",
        "## 28. 谋孙权",
        "## 29. 界孙权",
        "## 30. 鲍信",
        "## 31. 谋皇甫嵩",
    )
    assert all(text.count(heading) == 1 for heading in headings)
    assert "原十三个武将/版本条目" in text


def test_general_entries_separate_text_resolution_strategy_and_taunt() -> None:
    text = _read(GENERAL_DOC)
    assert "用户提供的技能原文" in text
    assert "当前项目采用的结算解释" in text
    assert "模拟策略" in text
    assert "嘲讽口径" in text
    assert "不得表述成官方统一裁定" in text
    assert "B+ < A- < A < A+ < S- < S < S+" in text


def test_general_document_contains_all_required_skills_and_key_boundaries() -> None:
    text = _read(GENERAL_DOC)
    for skill in (
        "【蒺藜】",
        "【罪论】",
        "【父荫】",
        "【权计】",
        "【自立】",
        "【排异】",
        "【缮甲】",
        "【谦冲】",
        "【帷幕】",
        "【明哲】",
        "【尚俭】",
        "【凌人】",
        "【伏间】",
        "【法箓】",
        "【真仪】",
        "【点化】",
        "【锦帆】",
        "【射却】",
        "【成略】",
        "【恃才】",
        "【寸目】",
        "【谮构】",
        "【诽离】",
        "【破降】",
        "【绝勇】",
        "【义从】",
        "【趫猛】",
    ):
        assert skill in text
    assert "旧版曹纯与新版曹纯" in text
    assert "同一局不能同时出现" in text
    assert "不以完整三国杀移动版武将数据库为前置条件" in text


def test_general_document_keeps_declared_nonblocking_items_and_resolutions() -> None:
    section = _read(GENERAL_DOC).split("## 36. 待核验事项", maxsplit=1)[1]
    numbered = [line for line in section.splitlines() if line[:1].isdigit() and ". " in line[:4]]
    assert len(numbered) == 14
    assert "清河公主" in section
    assert "其他改判武将" in section
    assert "未加入本次测试的武将" in section
    assert "问题5、问题6" in section
    assert "不再列为待核验" in section
    assert "谋皇甫嵩尚未正式通过前不计入十四名普通候选池" in section


def test_xuyou_section_has_only_correct_base_three_and_mode_four_values() -> None:
    text = _read(GENERAL_DOC)
    section = text.split("## 11. 许攸", maxsplit=1)[1].split("## 12.", maxsplit=1)[0]
    assert "- 基础体力：3" in section
    assert "- 基础体力上限：3" in section
    assert "基础值唯一按`3/3`初始化" in section
    assert "推导为`4/4`" in section
    assert "基础体力：4" not in section
    assert "体力上限：4" not in section
    assert "5/5" not in section


def test_wangyuanji_qianchong_permission_lifecycle_boundaries_documented() -> None:
    """G3-CLOSURE-001：【谦冲】牌类许可两条 CURRENT 边界必须写入 Knowledge。"""
    text = _read(GENERAL_DOC)
    section = text.split("## 7. 王元姬", maxsplit=1)[1].split("## 8.", maxsplit=1)[0]
    # A. PLAY_PHASE_START 建立的许可持续整次出牌阶段，中途装备变化不撤销。
    assert "QIANCHONG_PERMISSION_LIFECYCLE = ESTABLISHED_AT_PLAY_PHASE_START" in section
    assert "持续到这一次出牌阶段结束" in section
    assert "都不会撤销已经建立的许可" in section
    assert "两套独立生命周期" in section
    # B. 判断时点锁定 PLAY_PHASE_START；后来才变 empty/mixed 不补开选择。
    assert "判断时点明确为 `PLAY_PHASE_START`" in section
    assert "不得补开本次出牌阶段已经错过的【谦冲】牌类选择" in section


def test_base_terms_define_skill_types_sources_and_separate_loss_from_invalidation() -> None:
    text = _read(BASE_DOC)
    for term in ("锁定技", "限定技", "觉醒技", "使命技", "持恒技", "转换技", "蓄力技"):
        assert term in text
    assert "不得用一个布尔值合并“技能失效”和“失去技能”" in text
    assert "武将牌上的技能失效" in text
    assert "身份、他授、装备及模式技能" in text
    assert "3/4" in text
    assert "默认初始为阳" in text


def test_mode_document_routes_candidate_pool_to_single_fact_source() -> None:
    text = _read(MODE_DOC)
    section = text.split("## 9. 武将候选测试池的模式调用", maxsplit=1)[1]
    assert "当前13名正式普通候选池" in section
    assert "第14名准入门槛" in section
    assert "《三国杀模拟规范》第5.17.5节" in section
    assert "候选抽样完成后" in section
    assert "本节不重复技能正文" in section
    assert "每次正式模拟必须明确选择其一" in section


def test_simulation_document_routes_general_rules_and_lists_required_states() -> None:
    text = _read(SIM_DOC)
    assert "`三国杀武将规则补充.md`" in text
    section = text.split("### 5.16 指定武将画像、嘲讽与状态接口", maxsplit=1)[1].split(
        "## 6.", maxsplit=1
    )[0]
    for field in (
        "cards_used_or_responded_this_turn",
        "fuyin_checked_this_turn",
        "caused_damage_this_turn",
        "discarded_card_this_turn",
        "quan_cards",
        "zili_awakened",
        "paiyi_used_this_play_phase",
        "equipment_zone_cards_lost_total",
        "shanjia_used_this_play_phase",
        "cards_lost_this_turn",
        "temporary_qianchong_card_type",
        "has_weimu",
        "has_mingzhe",
        "lingren_used_this_play_phase",
        "temporary_jianxiong",
        "temporary_xingshang",
        "temporary_skill_expiry",
        "known_hand_information",
        "ziwei_mark",
        "houtu_mark",
        "yuqing_mark",
        "gouchen_mark",
        "bell_cards_by_suit",
    ):
        assert f"`{field}`" in section


def test_instructions_only_add_compact_general_knowledge_route() -> None:
    text = _read(INSTRUCTIONS)
    assert "三国杀武将规则补充.md" in text
    assert "技能类型、失效与失去规则查询" in text
    assert "蒺藜：" not in text
    assert "缮甲：" not in text
    assert 5000 <= len(text) <= 6500


def test_public_package_exports_new_framework_and_general_states() -> None:
    for name in (
        "SkillState",
        "ConversionSkillState",
        "ChargeState",
        "GENERAL_RULE_RECORDS",
        "FuyinTurnState",
        "WangYuanjiState",
        "CaoyingState",
        "ZhangQiyingState",
        "XingGanningState",
    ):
        assert name in scripts.__all__
        assert hasattr(scripts, name)
