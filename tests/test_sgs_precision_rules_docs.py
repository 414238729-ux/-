from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
KNOWLEDGE = ROOT / "knowledge"
TERMS_PATH = KNOWLEDGE / "三国杀基础术语与通用机制.md"
CARDS_PATH = KNOWLEDGE / "三国杀卡牌效果.md"
SPEC_PATH = KNOWLEDGE / "三国杀模拟规范.md"
INSTRUCTIONS_PATH = ROOT / "GPT_INSTRUCTIONS.md"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _section_after(text: str, heading: str) -> str:
    return text.split(heading, maxsplit=1)[1]


def test_card_and_area_scope_replaces_the_old_wrong_definition() -> None:
    terms = _read(TERMS_PATH)
    cards = _read(CARDS_PATH)

    assert "指手牌区内的牌和装备区内的牌，不包括判定区内的牌" in terms
    assert "指手牌区、装备区和判定区内的牌" in terms
    assert "牌＝手牌区＋判定区" not in terms
    assert "都来自手牌区、都来自装备区" in cards
    assert "一张来自手牌区加一张来自装备区" in cards
    assert "不能弃置自己判定区内的牌" in cards


def test_nullification_is_target_specific_and_not_harm_filtered() -> None:
    cards = _read(CARDS_PATH)
    section = cards.split("### 4.12 【无懈可击】", maxsplit=1)[1]
    section = section.split("## 5. 延时锦囊牌", maxsplit=1)[0]

    assert "不限于造成伤害、负面或敌方锦囊" in section
    assert "有利锦囊" in section
    assert "多目标或全体锦囊按目标依次结算" in section
    assert "只令该角色不受本次效果" in section
    assert "不影响之后其他角色的结算" in section
    assert "另一张【无懈可击】可以抵消前一张" in section
    assert "不设置与实际持牌情况无关的人为响应张数上限" in section
    assert "刚进入判定区时不进入此响应时机" in section


def test_delayed_tricks_use_precise_nullification_timing_and_destinations() -> None:
    terms = _read(TERMS_PATH)
    cards = _read(CARDS_PATH)

    assert "刚被使用、刚进入判定区时，不立即进入【无懈可击】" in terms
    assert "即将进行判定、决定该牌是否生效之前" in terms
    assert "【乐不思蜀】从判定区置入弃牌堆" in terms
    assert "【兵粮寸断】从判定区置入弃牌堆" in terms
    assert "移至当前角色下家的判定区" in terms
    assert "完整结算该次伤害、技能、濒死和死亡后" in terms
    assert "将【闪电】置入弃牌堆" in terms
    assert "被【无懈可击】抵消或完成判定后均置入弃牌堆" in cards
    assert "被【无懈可击】抵消或判定未命中时均不置入弃牌堆" in cards
    assert "延时锦囊结算后的去向按通常方式处理" not in terms
    assert "延时锦囊结算后的去向按通常方式处理" not in cards


def test_put_into_discard_pile_is_not_automatically_a_discard_action() -> None:
    terms = _read(TERMS_PATH)
    spec = _read(SPEC_PATH)

    assert "统一使用“置入弃牌堆”，不统一写成“弃置”" in terms
    assert "不得自动视为某名角色执行了一次“弃置牌”的操作" in terms
    assert "卡牌进入弃牌堆不自动表示某名角色执行了一次弃置牌操作" in spec
    assert "`acting_player` 不得伪造" in spec


def test_chain_transmission_rules_are_complete_and_ordered() -> None:
    terms = _read(TERMS_PATH)
    section = terms.split("## 15. 横置状态与属性伤害传导", maxsplit=1)[1]
    section = section.split("## 16. 距离", maxsplit=1)[0]

    required = (
        "实际受到大于 0 点的火属性或雷属性伤害",
        "无属性伤害不触发传导",
        "保持横置状态",
        "原始受伤角色不进入本轮剩余传导对象",
        "以当前回合角色为锚点",
        "按照当前座次数递增方向循环",
        "先重新确认其此时是否仍处于横置状态",
        "全部处理完成后，才处理下一名角色",
        "仍继续结算本轮剩余合法传导角色",
        "传导属性伤害继承原始属性伤害的伤害来源",
        "最终实际受到的属性伤害点数，是本轮传导的基础伤害点数",
        "局部变化默认只影响该角色",
        "才能修改后续角色使用的传导基础伤害",
        "本轮传导立即终止",
        "独立开启一轮新传导",
        "再返回原传导流程",
    )
    for item in required:
        assert item in section


def test_serpent_spear_always_has_no_rank_regardless_of_color() -> None:
    cards = _read(CARDS_PATH)
    spec = _read(SPEC_PATH)
    section = cards.split("### 7.8 【丈八蛇矛】", maxsplit=1)[1]
    section = section.split("### 7.9 【方天画戟】", maxsplit=1)[0]

    assert "均没有花色和点数" in section
    assert "均为红色时" in section
    assert "均为黑色时" in section
    assert "一红一黑时" in section
    assert "不得继承、合计或选择原手牌的花色或点数" in section
    assert "`suit=无花色`" in spec
    assert "`rank=无点数`" in spec


def test_resolved_topics_are_removed_from_pending_sections() -> None:
    terms_pending = _section_after(_read(TERMS_PATH), "## 21. 待核验事项")
    cards = _read(CARDS_PATH)

    for resolved in (
        "横置属性伤害传导的完整起点与顺序",
        "“牌”与“区域内的牌”的术语范围",
        "延时锦囊判定完成后的统一去向表述",
        "环形座次下距离计算的完整规则",
        "同一角色判定区内是否可同时存在同名延时锦囊",
        "跳过判定阶段时，判定区内延时锦囊的留存与延后结算",
    ):
        assert resolved not in terms_pending

    for resolved in (
        "【无懈可击】对多目标锦囊的精确结算",
        "丈八蛇矛转化【杀】的颜色、花色和点数规则",
        "丈八蛇矛转化【杀】的花色是否存在其他特殊判定",
        "延时锦囊判定完成后的统一去向表述",
        "【闪电】的“下家”是否始终按结算时当前座次确定",
    ):
        assert resolved not in cards


def test_gpt_instructions_are_compact_and_route_precision_rules() -> None:
    instructions = _read(INSTRUCTIONS_PATH)
    required = (
        "`三国杀模拟规范.md`",
        "`三国杀基础术语与通用机制.md`",
        "`三国杀卡牌效果.md`",
        "`三国杀卡牌结构化数据.csv`",
        "详细效果不得复制到 Instructions",
        "实际距离与攻击范围必须区分",
        "未注明属性而只写“造成伤害”时，默认是无属性伤害",
        "未注明其他来源的卡牌伤害默认以该牌使用者为来源",
        "“使用”“打出”“弃置”“置入弃牌堆”",
        "卡牌颜色、花色、点数和伤害属性",
    )
    for item in required:
        assert item in instructions

    assert 5000 <= len(instructions) <= 6500
    for copied_detail in (
        "黑桃2至9",
        "原始受伤角色不再加入同一轮传导队列",
        "`chain_base_damage`",
        "转化出的【杀】始终没有点数",
    ):
        assert copied_detail not in instructions
