from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODE_PATH = ROOT / "knowledge" / "三国杀模式规则.md"
TERMS_PATH = ROOT / "knowledge" / "三国杀基础术语与通用机制.md"
INSTRUCTIONS_PATH = ROOT / "GPT_INSTRUCTIONS.md"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_mode_hand_visibility_rules_do_not_swap_information_models() -> None:
    mode = _read(MODE_PATH)

    assert "同阵营队友可以查看彼此当前实际手牌" in mode
    assert "敌方不能查看这些手牌" in mode
    assert "两名农民之间也不共享手牌信息" in mode
    assert "不得让一名农民在模拟决策中直接读取" in mode
    assert "理论上限假设，不代表实际游戏信息条件" in mode
    assert "2v2队友不能查看彼此手牌" not in mode
    assert "斗地主农民可以查看队友手牌" not in mode


def test_landlord_health_bonus_changes_both_initial_values() -> None:
    mode = _read(MODE_PATH)

    assert "初始体力上限+1，初始体力值也+1" in mode
    assert "不是游戏开始时发动的技能、回复体力" in mode
    assert "3点体力上限、3点初始体力" in mode
    assert "4点体力上限、4点初始体力" in mode
    assert "5点体力上限、5点初始体力" in mode
    assert "游戏正式开始前已完成" in mode
    assert "不进入游戏开始事件队列" in mode
    assert "不存在由玩家选择地主加成与开局技能先后顺序的问题" in mode


def test_two_v_two_distance_and_position_swap_rules_are_explicit() -> None:
    mode = _read(MODE_PATH)

    for relation in (
        "1号位与2号位之间为1",
        "2号位与3号位之间为1",
        "3号位与4号位之间为1",
        "4号位与1号位之间为1",
        "1号位与3号位之间为2",
        "2号位与4号位之间为2",
    ):
        assert relation in mode
    assert "1号位和4号位虽然数字不连续" in mode
    assert "距离按交换后的当前座次重新计算" in mode
    assert "已经确定的阵营、队友关系、胜负关系和死亡奖励身份不变" in mode


def test_standard_turn_phase_order_and_defaults_are_recorded() -> None:
    terms = _read(TERMS_PATH)
    phase_markers = (
        "1. 准备阶段",
        "2. 判定阶段",
        "3. 摸牌阶段",
        "4. 出牌阶段",
        "5. 弃牌阶段",
        "6. 结束阶段",
    )

    positions = [terms.index(marker) for marker in phase_markers]
    assert positions == sorted(positions)
    assert "经过准备阶段但没有发生效果，不等于跳过准备阶段" in terms
    assert "玩家不能任意跳过该阶段" in terms
    assert "通常从牌堆顶摸 2 张牌" in terms
    assert "默认手牌上限等于当前体力值" in terms
    assert "“使用”与“打出”必须区分" in terms


def test_counterclockwise_means_increasing_current_seat_numbers() -> None:
    terms = _read(TERMS_PATH)

    assert "“逆时针”是当前座次数字递增的方向" in terms
    for order in (
        "1→2→3→4",
        "2→3→4→1",
        "3→4→1→2",
        "4→1→2→3",
        "1→2→3",
        "2→3→1",
        "3→1→2",
    ):
        assert order in terms
    assert "不得将“逆时针”解释成数字递减" in terms


def test_dying_rescue_and_death_are_distinct_nodes() -> None:
    terms = _read(TERMS_PATH)

    assert "进入濒死不等于已经死亡" in terms
    assert "体力恢复到大于或等于 1 时，才脱离濒死状态" in terms
    assert "体力值为 -1 时恢复 1 点" in terms
    assert "体力变为 0，仍处于濒死状态" in terms
    assert "救援顺序从当前回合角色开始" in terms
    assert "救援流程立即结束，不再询问后续角色" in terms
    assert "才确认死亡" in terms
    assert "确认死亡后，才结算" in terms


def test_multiple_responses_and_rejudgments_are_sequential() -> None:
    terms = _read(TERMS_PATH)

    assert "每名角色先作出决定，并完整结算当前内容" in terms
    assert "后续角色应基于轮到自己时的最新状态" in terms
    assert "不是同时提交决定，也不是同时结算" in terms
    assert "新的判定牌或判定结果成为当前结果" in terms
    assert "后续角色看到当前结果后，可以继续改判" in terms
    assert "不是同时针对原判定牌进行改判" in terms


def test_gpt_instructions_route_mode_details_instead_of_copying_them() -> None:
    instructions = _read(INSTRUCTIONS_PATH)

    required = (
        "`三国杀模式规则.md`",
        "`三国杀基础术语与通用机制.md`",
        "不得将不同平台、模式、版本、历史时期、模组、房规",
        "隐藏信息存在时，角色只能使用当时可见的信息",
        "前一步结算会改变后一步条件时，必须逐步更新状态",
        "明确特殊规则优先于通用规则",
    )
    for item in required:
        assert item in instructions

    detailed_rules = (
        "默认同一阵营的队友可以查看彼此当前实际持有的手牌",
        "初始体力上限和初始体力值各+1",
        "4与1的距离均为1",
        "完整救援顺序后仍未达到1点，才确认死亡",
    )
    for item in detailed_rules:
        assert item not in instructions
