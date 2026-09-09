import csv
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
KNOWLEDGE = ROOT / "knowledge"
SIMULATION = KNOWLEDGE / "三国杀模拟规范.md"
MODES = KNOWLEDGE / "三国杀模式规则.md"
MECHANICS = KNOWLEDGE / "三国杀基础术语与通用机制.md"
CARD_RULES = KNOWLEDGE / "三国杀卡牌效果.md"
CARD_DEFINITIONS = KNOWLEDGE / "三国杀卡牌结构化数据.csv"
CARD_USE_MODES = KNOWLEDGE / "三国杀卡牌使用方式.csv"
DECK = KNOWLEDGE / "三国杀牌堆数据.csv"
INSTRUCTIONS = ROOT / "GPT_INSTRUCTIONS.md"


def _read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def test_fixed_lineup_uses_on_demand_profiles_without_complete_database() -> None:
    text = SIMULATION.read_text(encoding="utf-8")
    assert "固定阵容与按需武将画像" in text
    assert "武将技能与全部特殊问答数据库不是固定阵容模拟的前置条件" in text
    for field in (
        "general_name",
        "base_hp",
        "base_max_hp",
        "skill_text",
        "skill_version",
        "strength_tier",
        "defense_value",
        "on_damage_benefit",
        "retaliation_risk",
        "burst_threat",
        "control_threat",
        "growth_threat",
        "hand_dependency",
        "equipment_dependency",
        "kill_difficulty",
        "special_interactions",
        "source",
        "confidence",
    ):
        assert f"`{field}`" in text or f"{field}:" in text


def test_target_priority_weights_are_strategy_parameters() -> None:
    text = SIMULATION.read_text(encoding="utf-8")
    for field in (
        "static_threat",
        "current_threat",
        "kill_efficiency",
        "defense_cost",
        "on_damage_benefit",
        "retaliation_risk",
        "immediate_lethal_threat",
        "focus_accessibility",
        "focus_continuity",
        "target_priority_score",
    ):
        assert f"`{field}`" in text
    assert "可调计算参数" in text
    assert "不得仅因两名敌人都可攻击就轮流或平均分配伤害" in text


def test_mode_visibility_and_team_rescue_boundaries_are_explicit() -> None:
    modes = MODES.read_text(encoding="utf-8")
    simulation = SIMULATION.read_text(encoding="utf-8")
    assert "同阵营队友可以查看彼此当前实际手牌" in modes
    assert "敌方不能查看这些手牌" in modes
    assert "花=YES、蛋=NO" in modes
    assert "公开语境和答案向地主及双农民一致公开" in modes
    assert "无懈保护建议只回答本次是否需要保护" in modes
    assert "不是私密手牌共享" in modes
    assert "非濒死队友的【酒】不能救人" in simulation
    assert "默认必须救援" in simulation


def test_nullification_timer_knowledge_is_dynamic_and_limited() -> None:
    simulation = SIMULATION.read_text(encoding="utf-8")
    mechanics = MECHANICS.read_text(encoding="utf-8")
    information = (SIMULATION.parent / "三国杀AI信息规则.md").read_text(encoding="utf-8")
    assert "三国杀AI信息规则" in simulation
    assert "首次真正进入无懈响应窗口前" in information
    assert "KNOWN_USABLE` / `KNOWN_NONE" in information
    assert "不消耗牌，也不自动变成`KNOWN_NONE`" in information
    assert "实际使用一张只确认这一张被使用" in information
    assert "公开摘要不含精确张数" in information
    assert "读取视图、AI评分、普通轮询或普通阶段转换不产生观察" in information
    assert "真实无懈响应窗口出现时" in mechanics
    assert "三国杀AI信息规则" in mechanics


def test_card_decision_strategies_stay_in_simulation_layer() -> None:
    simulation = SIMULATION.read_text(encoding="utf-8")
    card_rules = CARD_RULES.read_text(encoding="utf-8")
    for phrase in (
        "【五谷丰登】选牌与使用",
        "【借刀杀人】应答",
        "防御牌保留",
        "【顺手牵羊】【过河拆桥】",
        "【乐不思蜀】",
        "【兵粮寸断】",
        "【桃园结义】与AOE",
    ):
        assert phrase in simulation
    assert "单牌目标与多人牌理性策略" not in card_rules


def test_mount_wine_and_equipment_frequency_rules_are_consistent() -> None:
    mechanics = MECHANICS.read_text(encoding="utf-8")
    cards = CARD_RULES.read_text(encoding="utf-8")
    assert "equip_slot=attack_horse" in mechanics
    assert "equip_slot=defense_horse" in mechanics
    assert "紫骍、赤兔、大宛" in mechanics
    assert "骅骝、的卢、爪黄飞电、绝影" in mechanics
    assert "每个独立出牌阶段限一次" in cards
    assert "濒死自救没有基础使用次数限制" in cards
    assert "每次满足触发与支付条件均可发动或生效" in cards


def test_structured_layers_link_without_putting_ai_in_card_csv() -> None:
    definitions = _read_rows(CARD_DEFINITIONS)
    modes = _read_rows(CARD_USE_MODES)
    definition_keys = {row["card_id"] for row in definitions}
    assert {row["card_key"] for row in modes} <= definition_keys
    assert {row["use_mode"] for row in modes if row["card_key"] == "sgs_basic_tao"} == {
        "own_play_phase_self_heal",
        "dying_self_rescue",
        "rescue_other_dying_character",
    }
    assert {row["use_mode"] for row in modes if row["card_key"] == "sgs_basic_jiu"} == {
        "play_phase_slash_buff",
        "dying_self_rescue",
    }
    combined = CARD_DEFINITIONS.read_text(encoding="utf-8")
    for strategy_field in (
        "target_priority_weights",
        "nullification_strategy",
        "rescue_strategy",
        "harvest_strategy",
    ):
        assert strategy_field not in combined


def test_deck_is_instance_level_and_user_verified_not_official() -> None:
    rows = _read_rows(DECK)
    assert len(rows) == 160
    assert len({row["instance_id"] for row in rows}) == 160
    assert {row["quantity"] for row in rows} == {"1"}
    assert {row["verification_status"] for row in rows} == {
        "user_verified_against_actual_cards"
    }
    assert {row["source_type"] for row in rows} == {
        "unofficial_transcription_then_user_verified"
    }
    assert all("不代表官方逐牌认证" in row["notes"] for row in rows)


def test_instructions_keep_only_compact_strategy_routing() -> None:
    text = INSTRUCTIONS.read_text(encoding="utf-8")
    assert 5000 <= len(text) <= 7000
    assert "目标选择应查询模拟规范中的集火、威胁、击杀效率和卖血收益策略，不得随机分散攻击。" in text
    assert "fixed阵容" not in text
    assert "target_priority_weights" not in text
    assert "farmer_peach_signal" not in text
