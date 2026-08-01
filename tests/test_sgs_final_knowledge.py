import csv
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
KNOWLEDGE = ROOT / "knowledge"
SPEC = KNOWLEDGE / "三国杀模拟规范.md"
MODES = KNOWLEDGE / "三国杀模式规则.md"
TERMS = KNOWLEDGE / "三国杀基础术语与通用机制.md"
CARDS = KNOWLEDGE / "三国杀卡牌效果.md"
CARD_CSV = KNOWLEDGE / "三国杀卡牌结构化数据.csv"
DECK_CSV = KNOWLEDGE / "三国杀牌堆数据.csv"
INSTRUCTIONS = ROOT / "GPT_INSTRUCTIONS.md"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _pending(text: str) -> str:
    if "待核验事项" not in text:
        return text
    return text.rsplit("待核验事项", maxsplit=1)[1]


def test_only_one_upload_copy_of_each_formal_sgs_knowledge_file_exists() -> None:
    expected = {
        "三国杀模拟规范.md",
        "三国杀模式规则.md",
        "三国杀基础术语与通用机制.md",
        "三国杀卡牌效果.md",
        "三国杀卡牌结构化数据.csv",
        "三国杀牌堆数据.csv",
    }
    root_files = {path.name for path in KNOWLEDGE.iterdir() if path.is_file()}
    assert expected <= root_files
    for name in expected:
        assert sum(path.name == name for path in KNOWLEDGE.iterdir()) == 1

    suspicious = [
        path.name
        for path in KNOWLEDGE.iterdir()
        if path.is_file()
        and path.name.startswith("三国杀")
        and re.search(r"(?:旧版|备份|副本|copy|\d{8}[-_]?\d*)", path.stem, re.I)
    ]
    assert suspicious == []


def test_deck_scope_is_exactly_the_four_confirmed_mobile_modes() -> None:
    rows = _csv_rows(DECK_CSV)
    assert {row["deck_id"] for row in rows} == {
        "sgs_mobile_non_special_20260725_unofficial"
    }
    assert {row["platform"] for row in rows} == {"三国杀移动版"}
    assert {row["mode"] for row in rows} == {
        "常规军争身份模式；排位2v2；斗地主；八人军争限时变体"
    }

    spec = _read(SPEC)
    for mode in (
        "常规军争身份模式",
        "排位2v2",
        "斗地主",
        "八人军争“主公立储、内奸择途”特殊玩法",
    ):
        assert mode in spec
    for excluded in (
        "加入专属补充包的其他特殊模式",
        "使用模式专属牌堆的玩法",
        "其他服务器牌堆",
        "未经核验的其他活动模式",
    ):
        assert excluded in spec


def test_deck_exhaustion_rules_separate_confirmed_and_temporary_cases() -> None:
    terms = _read(TERMS)
    spec = _read(SPEC)
    for text in (terms, spec):
        assert "正在使用或" in text and "结算的牌" in text
        assert "手牌" in text and "装备区" in text and "判定区" in text
        assert "权" in text
        assert "游戏立即平局" in text
        assert "检索" in text and "不" in text and "重洗" in text
    assert "观看、亮牌或判定彻底不足" in terms
    assert "资料状态：分析约定" in terms
    assert "当前暂定规则" in spec
    assert "**状态：分析约定**" in spec


def test_delayed_trick_coexistence_and_skipped_judgment_are_confirmed() -> None:
    terms = _read(TERMS)
    cards = _read(CARDS)
    structured = {row["card_name"]: row for row in _csv_rows(CARD_CSV)}

    for text in (terms, cards):
        assert "同一名角色的判定区内不能同时存在两张或更多同名延时锦囊" in text or (
            "同一角色的判定区不能同时存在两张或更多同名延时锦囊" in text
        )
        assert "不同名称" in text and "可以同时存在" in text
        assert "跳过整个判定阶段" in text
        assert "不进入" in text and "【无懈可击】" in text and "时机" in text
        assert "延时锦囊" in text and "留存" in text
        assert "后发先至" in text
        assert "后进先出" in text
        assert "进入" in text and "从晚到早" in text

    for name in ("乐不思蜀", "兵粮寸断", "闪电"):
        row = structured[name]
        assert name in row["target_rule"]
        assert "同名" in row["notes"]
        assert "跳过整个判定阶段" in row["notes"]
        assert "继续留在原判定区" in row["notes"]


def test_zhangba_spear_has_no_suit_or_rank_and_keeps_fields_distinct() -> None:
    cards = _read(CARDS)
    spec = _read(SPEC)
    row = {r["card_name"]: r for r in _csv_rows(CARD_CSV)}["丈八蛇矛"]

    for text in (cards, spec, row["notes"]):
        assert "无花色" in text or "没有花色" in text
        assert "无点数" in text or "没有花色和点数" in text
        assert "普通【杀】" in text
        assert "无属性" in text
    assert "颜色、花色、点数和伤害属性" in cards
    assert "待核验" not in row["notes"]


def test_living_character_ring_and_identity_mode_are_documented() -> None:
    terms = _read(TERMS)
    modes = _read(MODES)

    for expected in (
        "存活角色环",
        "死亡角色不参与距离计算",
        "2 号与 4 号",
        "基础距离为 1",
        "不重新编号",
    ):
        assert expected in terms

    for expected in (
        "## 4. 军争身份模式",
        "主公1名",
        "忠臣1名",
        "反贼2名",
        "忠臣2名",
        "反贼4名",
        "常备主公武将或对应的常备主公奖池",
        "再随机提供3名其他武将",
        "场上只剩主公和内奸时",
        "任意角色击杀一名反贼后",
        "主公击杀忠臣后",
        "游戏立即结束，不再执行本次身份击杀奖励或惩罚",
    ):
        assert expected in modes

    network_selection = modes.split("#### 4.5.1 网络版", 1)[1].split(
        "#### 4.5.2 桌游版", 1
    )[0]
    assert "常备主公武将或奖池＋随机3名其他武将" in network_selection


def test_resolved_topics_do_not_remain_pending() -> None:
    terms_pending = _pending(_read(TERMS))
    cards_pending = _pending(_read(CARDS))
    resolved = (
        "环形座次下距离计算的完整规则",
        "同一角色判定区内是否可同时存在同名延时锦囊",
        "跳过判定阶段时，判定区内延时锦囊的留存与延后结算",
        "丈八蛇矛转化【杀】的花色是否存在其他特殊判定",
        "多张延时锦囊按什么顺序判定",
        "是否按先进入者先判定",
    )
    for item in resolved:
        assert item not in terms_pending
        assert item not in cards_pending


def test_instructions_route_new_rules_without_copying_rule_bodies() -> None:
    instructions = _read(INSTRUCTIONS)
    assert 5000 <= len(instructions) <= 6500
    for route in (
        "军争身份",
        "牌堆耗尽",
        "存活角色环",
        "判定区",
        "`三国杀模式规则.md`",
        "`三国杀模拟规范.md`",
    ):
        assert route in instructions

    for copied_detail in (
        "主公1名",
        "反贼4名",
        "需要摸3张",
        "五人局中3号死亡",
        "同一名角色的判定区内不能同时存在两张",
    ):
        assert copied_detail not in instructions
