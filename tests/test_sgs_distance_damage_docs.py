from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
KNOWLEDGE = ROOT / "knowledge"
TERMS_PATH = KNOWLEDGE / "三国杀基础术语与通用机制.md"
CARDS_PATH = KNOWLEDGE / "三国杀卡牌效果.md"
SPEC_PATH = KNOWLEDGE / "三国杀模拟规范.md"
INSTRUCTIONS_PATH = ROOT / "GPT_INSTRUCTIONS.md"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _section(text: str, start: str, end: str) -> str:
    return text.split(start, maxsplit=1)[1].split(end, maxsplit=1)[0]


def test_actual_distance_and_attack_range_are_distinct_terms() -> None:
    terms = _read(TERMS_PATH)
    distance = _section(terms, "## 16. 实际距离", "## 17. 攻击范围与文本判定")
    attack_range = _section(
        terms,
        "## 17. 攻击范围与文本判定",
        "## 18. 装备栏与替换装备",
    )

    assert "经过全部距离修正后的实际距离" in distance
    assert "武器增加攻击范围，不会降低" in distance
    assert "角色交换位置后" in distance
    assert "只有文本明确写“攻击范围内”" in attack_range
    assert "文本写“距离”时检查实际距离" in attack_range
    assert "文本写“攻击范围内”时检查攻击范围" in attack_range
    assert "【顺手牵羊】与【兵粮寸断】" in attack_range


def test_snatch_and_supply_shortage_use_the_same_actual_distance_rule() -> None:
    cards = _read(CARDS_PATH)
    snatch = _section(cards, "### 4.2 【顺手牵羊】", "### 4.3 【决斗】")
    shortage = _section(cards, "### 5.2 【兵粮寸断】", "### 5.3 【闪电】")
    spec = _read(SPEC_PATH)

    for section in (snatch, shortage):
        assert "与使用者实际距离为 1 的一名其他角色" in section
        assert "武器" in section
        assert "攻击坐骑、防御坐骑" in section
        assert "资料状态：当前确认" in section
    assert "不得把本牌解释为对攻击范围内" in shortage
    assert "必须调用同一个实际距离函数" in spec
    assert "不得调用攻击范围判定这两张牌的目标" in spec


def test_unspecified_damage_and_default_card_source_are_confirmed() -> None:
    terms = _read(TERMS_PATH)
    damage = _section(
        terms,
        "## 13. 伤害属性与未注明属性的伤害",
        "## 14. 伤害来源与卡牌伤害的默认来源",
    )
    source = _section(
        terms,
        "## 14. 伤害来源与卡牌伤害的默认来源",
        "## 15. 横置状态与属性伤害传导",
    )

    assert "默认造成无属性伤害" in damage
    assert "技能生成、加入游戏或未收录于普通牌堆" in damage
    assert "“伤害”是上位概念" in damage
    assert "“失去体力”不是伤害" in damage
    assert "伤害来源默认为该牌的使用者" in source
    assert "【南蛮入侵】和【万箭齐发】" in source
    assert "【闪电】造成的伤害没有伤害来源" in source
    assert "传导伤害继续继承原始伤害来源" in source


def test_fire_attack_vine_and_silver_lion_are_precise() -> None:
    cards = _read(CARDS_PATH)
    fire_attack = _section(cards, "### 4.4 【火攻】", "### 4.5 【铁索连环】")
    silver_lion = _section(cards, "### 8.3 【白银狮子】", "### 8.4 【藤甲】")
    vine = _section(cards, "### 8.4 【藤甲】", "## 9. 坐骑牌")

    assert "一名至少有一张手牌的角色" in fire_attack
    assert "结算到展示步骤前已无手牌" in fire_attack
    assert "不能用装备区或判定区的牌代替" in fire_attack

    assert "无属性、火属性和雷属性伤害" in silver_lion
    assert "无来源伤害" in silver_lion
    assert "“失去体力”不是伤害" in silver_lion
    assert "以任何方式离开" in silver_lion
    assert "不能超过体力上限" in silver_lion

    assert "判断藤甲是否令普通【杀】无效前已完成转换" in vine
    assert "较晚的伤害属性转换不能令其重新生效" in vine
    assert "【南蛮入侵】和【万箭齐发】同样先因藤甲而无效" in vine
    assert "藤甲被无视、防具技能失效、藤甲离开装备区" in vine


def test_aoe_damage_type_source_and_lightning_exception_are_explicit() -> None:
    cards = _read(CARDS_PATH)
    for name, next_heading, response in (
        ("南蛮入侵", "万箭齐发", "【杀】"),
        ("万箭齐发", "五谷丰登", "【闪】"),
    ):
        section = _section(
            cards,
            f"### 4.{8 if name == '南蛮入侵' else 9} 【{name}】",
            f"### 4.{9 if name == '南蛮入侵' else 10} 【{next_heading}】",
        )
        assert response in section
        assert "1 点无属性伤害" in section
        assert f"默认伤害来源为【{name}】的使用者" in section
        assert "资料状态：当前确认" in section

    lightning = _section(cards, "### 5.3 【闪电】", "## 6. 装备牌通用规则")
    assert "该 3 点雷属性伤害没有伤害来源" in lightning


def test_resolved_topics_are_no_longer_pending() -> None:
    cards = _read(CARDS_PATH)
    for resolved in (
        "【顺手牵羊】的目标距离限制",
        "【火攻】对没有手牌目标的处理",
        "藤甲无效化与伤害属性转换的结算顺序",
        "白银狮子离开装备区时的完整恢复条件",
        "【南蛮入侵】与【万箭齐发】的伤害属性和伤害来源细节",
        "【闪电】造成的 3 点雷属性伤害在当前客户端是否始终无伤害来源",
    ):
        assert resolved not in cards


def test_instructions_only_keep_compact_routes_and_general_principles() -> None:
    instructions = _read(INSTRUCTIONS_PATH)

    assert 5000 <= len(instructions) <= 6500
    assert "实际距离与攻击范围必须区分" in instructions
    assert "必须查询对应 Knowledge" in instructions
    assert "详细效果不得复制到 Instructions" in instructions
    assert "未注明属性而只写“造成伤害”时，默认是无属性伤害" in instructions
    assert "未注明其他来源的卡牌伤害默认以该牌使用者为来源" in instructions
    assert "【闪电】以及明确写明无来源" in instructions

    for copied_detail in (
        "判定为黑桃 2 至 9",
        "本轮传导基础伤害",
        "两张牌均为红色时",
        "被【无懈可击】抵消后均从判定区置入弃牌堆",
    ):
        assert copied_detail not in instructions
