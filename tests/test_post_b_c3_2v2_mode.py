# -*- coding: utf-8 -*-
"""POST-B C3：正式无武将技能 2v2 模式专项测试。

覆盖：canonical profile / 队伍模型 / 座次顺序 / 初始化 / 回合循环 /
OutcomePolicy（队伍胜负、逐次死亡确认、平局）/ 濒死救援 / 死亡后果
（死亡奖励摸牌、单体根牌继续、群体锦囊继续、当前回合角色死亡立即结束
回合、传导死亡继续）/ 模式能力（飞扬窗口、发动、放弃、可用边界）/
队伍目标合法性 / 模式层执行快照 / 正式门禁 / 固定种子自然结束与严格
重执行 / 平局终局。

只走真实生产路径：enumerate_legal_actions → validate_action →
apply_action → strict replay；不建立第二套引擎。
"""

from __future__ import annotations

from typing import Any

import pytest

from scripts.sgs_engine.actions import (
    InvalidActionError,
    LegalAction,
    UnsupportedRuleError,
)
from scripts.sgs_engine.events import EventType
from scripts.sgs_engine.mode_2v2 import (
    FORMAL_NO_SKILL_2V2_MODE,
    Formal2v2Configuration,
    Formal2v2ConfigurationError,
    Formal2v2Session,
    TrustedFormal2v2Configuration,
    TwoVsTwoOutcomePolicy,
    assert_trusted_formal_2v2_configuration,
    inspect_formal_2v2_readiness,
)
from scripts.sgs_engine.model import DISCARD_PILE, DRAW_PILE, ZoneRef
from scripts.sgs_engine.production_batch import (
    BatchActionIdController,
    BatchReferenceController,
    ProductionBasicCardBatch,
    ProductionPhase,
    _replace_player,
)
from scripts.sgs_engine.production_replay import (
    record_reference_formal_2v2,
    reexecute_production_replay,
)
from scripts.sgs_engine.multiplayer import PlayerTopology

SHA = "sgs_basic_sha"
TAO = "sgs_basic_tao"


# ----------------------------------------------------------------------
# 测试辅助
# ----------------------------------------------------------------------


def _session(*, seed: int = 2, **kwargs: Any) -> Formal2v2Session:
    return Formal2v2Session(
        seed=seed,
        configuration=Formal2v2Configuration.formal_profile(),
        analysis_only=False,
        **kwargs,
    )


def _op(game: ProductionBasicCardBatch, operation: str, **filters: Any) -> LegalAction | None:
    for action in game.legal_actions():
        if action.payload.get("operation") != operation:
            continue
        ok = True
        for key, value in filters.items():
            if key == "targets" and action.target_ids != value:
                ok = False
            if key == "card_key" and action.payload.get("card_key") != value:
                ok = False
        if ok:
            return action
    return None


def _require_op(game: ProductionBasicCardBatch, operation: str, **filters: Any) -> LegalAction:
    action = _op(game, operation, **filters)
    assert action is not None, (
        f"缺少操作{operation!r}："
        f"{sorted({a.payload.get('operation') for a in game.legal_actions()})}"
    )
    return action


def _step(game: ProductionBasicCardBatch, action: LegalAction) -> None:
    game.step(BatchActionIdController(action.action_id))


def _strip_hand(game: ProductionBasicCardBatch, player_id: str) -> None:
    for instance_id in tuple(game.state.card_ids_in(ZoneRef.hand(player_id))):
        game._state = game.state.move_card(instance_id, DISCARD_PILE)


def _give_card(
    game: ProductionBasicCardBatch,
    player_id: str,
    card_key: str,
) -> str:
    """从牌堆取一张指定卡键实体放入目标手牌（确定性测试夹具）。"""
    for instance_id in game.state.card_ids_in(DRAW_PILE):
        if game.state.cards_by_id[instance_id].card_key == card_key:
            game._state = game.state.move_card(instance_id, ZoneRef.hand(player_id))
            return instance_id
    raise AssertionError(f"牌堆中找不到{card_key}")


def _enter_play(game: ProductionBasicCardBatch) -> None:
    for operation in ("proceed_prepare", "proceed_judgment", "proceed_draw"):
        _step(game, _require_op(game, operation))


def _end_turn(game: ProductionBasicCardBatch) -> None:
    _step(game, _require_op(game, "end_play_phase"))
    while game.phase is ProductionPhase.DISCARD:
        if _op(game, "discard_phase_submit") is not None:
            _step(game, _require_op(game, "discard_phase_submit"))
        else:
            _step(game, _require_op(game, "select_discard_card"))
    _step(game, _require_op(game, "end_turn"))


def _pass_all_rescues(game: ProductionBasicCardBatch) -> None:
    while game.phase is ProductionPhase.DYING_RESCUE:
        _step(game, _require_op(game, "pass_rescue"))


# ----------------------------------------------------------------------
# 1. MODE_PROFILE / TEAM_MODEL / 配置边界
# ----------------------------------------------------------------------


def test_canonical_profile_values_and_team_model() -> None:
    profile = Formal2v2Configuration.formal_profile()
    assert type(profile) is TrustedFormal2v2Configuration
    assert profile.player_ids == ("p1", "p2", "p3", "p4")
    assert profile.base_hp == (4, 4, 4, 4)
    assert profile.base_max_hp == (4, 4, 4, 4)
    assert profile.initial_hand_counts == (3, 4, 4, 5)
    assert profile.hand_qi_ka_allowed is False
    assert profile.feiyang_seat == 4
    assert profile.feiyang_first_round_only is True
    assert profile.death_reward_draw_count == 1
    assert profile.deck_supply_mode == "no_reshuffle_draw"
    teams = profile.teams_by_player()
    assert dict(teams) == {
        "p1": "team_a",
        "p2": "team_b",
        "p3": "team_b",
        "p4": "team_a",
    }
    assert profile.team_of(1) == "team_a"
    assert profile.team_of(4) == "team_a"
    assert profile.team_of(2) == "team_b"
    assert profile.team_of(3) == "team_b"
    assert profile.teammate_of("p1") == "p4"
    assert profile.teammate_of("p4") == "p1"
    assert profile.teammate_of("p2") == "p3"


def test_configuration_from_dict_roundtrip() -> None:
    profile = Formal2v2Configuration.formal_profile()
    rebuilt = Formal2v2Configuration.from_dict(profile.to_dict())
    assert rebuilt.to_dict() == profile.to_dict()
    assert rebuilt is not profile
    assert type(rebuilt) is Formal2v2Configuration  # 普通重建不获得 trusted


def test_configuration_rejects_non_canonical_values() -> None:
    with pytest.raises(Formal2v2ConfigurationError):
        Formal2v2Configuration(player_ids=("p1", "p2", "p3", "p4"),
                               initial_hand_counts=(3, 4, 4, 4))
    with pytest.raises(Formal2v2ConfigurationError):
        Formal2v2Configuration(player_ids=("p1", "p1", "p3", "p4"))
    with pytest.raises(Formal2v2ConfigurationError):
        Formal2v2Configuration(player_ids=("p1", "p2", "p3", "p4"),
                               deck_supply_mode="reshuffle")
    with pytest.raises(Formal2v2ConfigurationError):
        Formal2v2Configuration(player_ids=("p1", "p2", "p3", "p4"),
                               feiyang_seat=5)


def test_trusted_configuration_boundary() -> None:
    plain = Formal2v2Configuration.from_dict(
        Formal2v2Configuration.formal_profile().to_dict()
    )
    with pytest.raises(Formal2v2ConfigurationError):
        assert_trusted_formal_2v2_configuration(plain)
    with pytest.raises(TypeError):
        assert_trusted_formal_2v2_configuration("not-a-config")  # type: ignore[arg-type]
    assert_trusted_formal_2v2_configuration(
        Formal2v2Configuration.formal_profile()
    )


def test_session_rejects_untrusted_and_forged_configuration() -> None:
    plain = Formal2v2Configuration.from_dict(
        Formal2v2Configuration.formal_profile().to_dict()
    )
    with pytest.raises(Formal2v2ConfigurationError, match="canonical factory"):
        Formal2v2Session(seed=0, configuration=plain, analysis_only=False)
    # 伪造同值对象：即使字段完全一致，普通构造也不获得 trusted provenance。
    forged = Formal2v2Configuration(
        player_ids=("p1", "p2", "p3", "p4"),
        base_hp=(4, 4, 4, 4),
        base_max_hp=(4, 4, 4, 4),
        initial_hand_counts=(3, 4, 4, 5),
        hand_qi_ka_allowed=False,
        feiyang_seat=4,
        feiyang_first_round_only=True,
        death_reward_draw_count=1,
        deck_supply_mode="no_reshuffle_draw",
    )
    with pytest.raises(Formal2v2ConfigurationError):
        Formal2v2Session(seed=0, configuration=forged, analysis_only=False)


def test_session_exact_type_boundary() -> None:
    class SneakySubclass(Formal2v2Session):
        pass

    with pytest.raises(TypeError, match="子类"):
        SneakySubclass(
            seed=0,
            configuration=Formal2v2Configuration.formal_profile(),
            analysis_only=True,
        )


# ----------------------------------------------------------------------
# 2. INITIALIZATION / TURN_ORDER / SEAT_ORDER
# ----------------------------------------------------------------------


def test_initialization_canonical() -> None:
    game = _session(seed=3)
    assert game.mode_id == FORMAL_NO_SKILL_2V2_MODE
    assert len(game.state.cards) == 160
    assert len(game.state.players) == 4
    assert game.first_player_id == "p1"
    assert game.deck_supply_mode == "no_reshuffle_draw"
    hand_sizes = tuple(
        len(game.state.card_ids_in(ZoneRef.hand(player_id)))
        for player_id in ("p1", "p2", "p3", "p4")
    )
    assert hand_sizes == (3, 4, 4, 5)
    for player in game.state.players:
        assert player.hp == 4 and player.max_hp == 4
    assert game.outcome_policy is not None
    assert game.outcome_policy.identity() == "outcome:formal_no_skill_2v2"
    assert game.mode_policy is not None
    assert game.mode_policy.identity == "mode:formal_no_skill_2v2"
    assert game.runtime.phase is ProductionPhase.PREPARE


def test_turn_order_full_cycle() -> None:
    game = _session(seed=3)
    order: list[str] = []
    for _ in range(4):
        order.append(game.current_player_id)
        _enter_play(game)
        _end_turn(game)
    assert order == ["p1", "p2", "p3", "p4"]
    assert game.current_player_id == "p1"
    assert game.runtime.turn_number == 5


def test_turn_order_skips_dead_player() -> None:
    game = _session(seed=3)
    _enter_play(game)
    # p1 回合内 p2 确认死亡：继任沿存活环跳过 p2 → p3；座次不重编号
    game._state = _replace_player(game.state, "p2", hp=0, alive=False)
    _end_turn(game)
    assert game.current_player_id == "p3"
    assert game.state.players_by_id["p2"].seat == 2


# ----------------------------------------------------------------------
# 3. OUTCOME_POLICY / DYING_RESCUE / DEATH_CONSEQUENCES
# ----------------------------------------------------------------------


def test_outcome_policy_sequential_team_elimination() -> None:
    policy = TwoVsTwoOutcomePolicy(
        {
            "p1": "team_a",
            "p2": "team_b",
            "p3": "team_b",
            "p4": "team_a",
        }
    )
    game = _session(seed=3)
    base = game.state

    def topo(alive_ids: set[str]) -> PlayerTopology:
        state = base
        for player in base.players:
            alive = player.player_id in alive_ids
            state = _replace_player(
                state,
                player.player_id,
                hp=player.hp if alive else 0,
                alive=alive,
            )
        return PlayerTopology.from_state(state)

    assert policy.resolve_winner_after_death(topo({"p1", "p2", "p3", "p4"}), "p2") is None
    assert policy.resolve_winner_after_death(topo({"p1", "p3", "p4"}), "p2") is None
    assert policy.resolve_winner_after_death(topo({"p1", "p4"}), "p3") == "team_a"
    assert policy.resolve_winner_after_death(topo({"p2", "p3"}), "p1") == "team_b"
    with pytest.raises(UnsupportedRuleError, match="失败关闭"):
        policy.resolve_winner_after_death(topo(set()), "p1")


def test_teammate_death_continues_with_reward_draw() -> None:
    """单体根牌（普通【杀】）杀死 p2：队伍未全灭 → 继续，p3 摸1张。"""
    game = _session(seed=2)
    _enter_play(game)
    _strip_hand(game, "p2")
    game._state = _replace_player(game.state, "p2", hp=1)
    p3_hand_before = len(game.state.card_ids_in(ZoneRef.hand("p3")))
    _step(game, _require_op(game, "use_slash", targets=("p2",)))
    _step(game, _require_op(game, "pass_slash_response"))
    _pass_all_rescues(game)
    assert game.is_finished is False
    assert game.winner_id is None
    assert game.state.players_by_id["p2"].alive is False
    assert game.phase is ProductionPhase.PLAY
    assert game.current_player_id == "p1"
    assert len(game.state.card_ids_in(ZoneRef.hand("p3"))) == p3_hand_before + 1
    reasons = [event.payload.get("reason") for event in game.events]
    assert "death_reward_teammate_draw" in reasons
    # 事件顺序：根牌收尾 → 死亡清理 → 死亡 → 死亡奖励摸牌
    death_index = next(
        i for i, e in enumerate(game.events) if e.event_type is EventType.DEATH
    )
    reward_index = next(
        i for i, e in enumerate(game.events)
        if e.payload.get("reason") == "death_reward_teammate_draw"
    )
    assert death_index < reward_index


def test_team_victory_after_second_member_death() -> None:
    """顺序死亡：p2（继续）后 p3 死亡 → team_b 全灭 → team_a 立即获胜。"""
    game = _session(seed=2)
    # 第1回合：p1 杀 p2（非终局死亡，继续）
    _enter_play(game)
    _strip_hand(game, "p2")
    game._state = _replace_player(game.state, "p2", hp=1)
    _step(game, _require_op(game, "use_slash", targets=("p2",)))
    _step(game, _require_op(game, "pass_slash_response"))
    _pass_all_rescues(game)
    _end_turn(game)
    # p3 回合：跳过
    _enter_play(game)
    _end_turn(game)
    # p4 回合：杀 p3 → team_b 全灭 → team_a 胜利
    _enter_play(game)
    _strip_hand(game, "p3")
    game._state = _replace_player(game.state, "p3", hp=1)
    _step(game, _require_op(game, "use_slash", targets=("p3",)))
    _step(game, _require_op(game, "pass_slash_response"))
    _pass_all_rescues(game)
    assert game.is_finished is True
    assert game.winner_id == "team_a"
    victory = [e for e in game.events if e.event_type is EventType.VICTORY]
    assert len(victory) == 1
    assert victory[0].target_ids == ("team_a",)
    game.assert_finished_state_invariants()


def test_dying_rescue_prevents_death() -> None:
    """p2 濒死被 p1 用【桃】救回：不死亡、无死亡奖励、对局继续。"""
    game = _session(seed=2)
    _enter_play(game)
    _strip_hand(game, "p2")
    game._state = _replace_player(game.state, "p2", hp=1)
    _give_card(game, "p1", TAO)
    _step(game, _require_op(game, "use_slash", targets=("p2",)))
    _step(game, _require_op(game, "pass_slash_response"))
    assert game.phase is ProductionPhase.DYING_RESCUE
    _step(game, _require_op(game, "rescue_with_peach"))
    assert game.state.players_by_id["p2"].alive is True
    assert game.state.players_by_id["p2"].hp == 1
    reasons = [event.payload.get("reason") for event in game.events]
    assert "death_reward_teammate_draw" not in reasons


def test_group_trick_target_death_continues_queue() -> None:
    """南蛮目标 p2 死亡后继续 p3/p4（C1 路径 + 2v2 死亡奖励）。"""
    game = _session(seed=2)
    _enter_play(game)
    _give_card(game, "p1", "sgs_trick_nanmanruqin")
    for player_id in ("p2", "p3", "p4"):
        _strip_hand(game, player_id)
    game._state = _replace_player(game.state, "p2", hp=1)
    game._state = _replace_player(game.state, "p3", hp=4)
    game._state = _replace_player(game.state, "p4", hp=4)
    p3_hand_before = len(game.state.card_ids_in(ZoneRef.hand("p3")))
    _step(game, _require_op(game, "use_nanman"))
    assert game.phase is ProductionPhase.TRICK_RESPONSE
    # p2 的无懈窗口关闭 → 南蛮响应：无【杀】→ 1伤 → 濒死 → 死亡
    while _op(game, "pass_trick_response") is not None:
        _step(game, _require_op(game, "pass_trick_response"))
    assert game.phase is ProductionPhase.NANMAN_RESPONSE
    _step(game, _require_op(game, "pass_nanman_slash"))
    _pass_all_rescues(game)
    assert game.state.players_by_id["p2"].alive is False
    assert game.is_finished is False
    assert len(game.state.card_ids_in(ZoneRef.hand("p3"))) == p3_hand_before + 1
    # p3、p4 继续承受南蛮（无【杀】各受1伤，hp>0 不死亡）
    for _ in range(2):
        while _op(game, "pass_trick_response") is not None:
            _step(game, _require_op(game, "pass_trick_response"))
        _step(game, _require_op(game, "pass_nanman_slash"))
    assert game.state.players_by_id["p3"].hp == 3
    assert game.state.players_by_id["p4"].hp == 3
    assert game.phase is ProductionPhase.PLAY


def test_current_player_death_ends_turn_immediately() -> None:
    """当前回合角色 p1 输掉决斗死亡：其回合立即结束，推进到 p2 回合。"""
    game = _session(seed=2)
    _enter_play(game)
    _strip_hand(game, "p1")
    _strip_hand(game, "p2")
    _give_card(game, "p1", "sgs_trick_juedou")
    _give_card(game, "p2", SHA)
    game._state = _replace_player(game.state, "p1", hp=1)
    turn_before = game.runtime.turn_number
    _step(game, _require_op(game, "use_duel", targets=("p2",)))
    # 无懈窗口逐名关闭（响应顺序从回合角色起绕存活环）
    while _op(game, "pass_trick_response") is not None:
        _step(game, _require_op(game, "pass_trick_response"))
    # 决斗响应：p2 打出【杀】，p1 无【杀】→ 受1点伤害
    _step(game, _require_op(game, "play_slash_for_duel"))
    _step(game, _require_op(game, "pass_duel_slash"))
    _pass_all_rescues(game)
    assert game.state.players_by_id["p1"].alive is False
    assert game.is_finished is False
    assert game.current_player_id == "p2"
    assert game.runtime.turn_number == turn_before + 1
    assert game.phase is ProductionPhase.PREPARE
    # 队伍 A 仅剩 p4：死亡奖励由 p4 获得
    reasons = [event.payload.get("reason") for event in game.events]
    assert "death_reward_teammate_draw" in reasons


# ----------------------------------------------------------------------
# 4. MODE_ABILITIES：飞扬（feiyang）
# ----------------------------------------------------------------------


def _feiyang_fixture(game: ProductionBasicCardBatch) -> None:
    """把 p1 手牌第一张移入 p4 判定区（测试装配；只走真实移动接口）。"""
    hand_ids = tuple(game.state.card_ids_in(ZoneRef.hand("p1")))
    game._state = game.state.move_card(hand_ids[0], ZoneRef.judgment("p4"))


def _run_to_p4_first_judgment(game: ProductionBasicCardBatch) -> None:
    """推进到 p4 首回合判定阶段入口（经过 p1/p2/p3 完整回合）。"""
    for _ in range(3):
        _enter_play(game)
        _end_turn(game)
    assert game.current_player_id == "p4"
    _step(game, _require_op(game, "proceed_prepare"))


def test_feiyang_window_opens_for_seat4_first_round() -> None:
    game = _session(seed=2)
    _feiyang_fixture(game)
    _run_to_p4_first_judgment(game)
    assert game.phase is ProductionPhase.FEIYANG_ACTIVATE
    assert game.runtime.feiyang_window_id is not None
    assert game.runtime.feiyang_snapshot_digest is not None
    operations = {
        action.payload.get("operation") for action in game.legal_actions()
    }
    assert operations == {"feiyang_decline", "feiyang_activate"}


def test_feiyang_activate_discards_cost_and_benefit() -> None:
    game = _session(seed=2)
    _feiyang_fixture(game)
    _run_to_p4_first_judgment(game)
    hand_before = set(game.state.card_ids_in(ZoneRef.hand("p4")))
    judgment_before = set(game.state.card_ids_in(ZoneRef.judgment("p4")))
    activate = _require_op(game, "feiyang_activate")
    hand_ids = tuple(activate.payload["hand_ids"])
    judgment_id = str(activate.payload["judgment_id"])
    assert set(hand_ids) <= hand_before
    assert judgment_id in judgment_before
    _step(game, activate)
    assert game.phase is ProductionPhase.JUDGMENT
    hand_after = set(game.state.card_ids_in(ZoneRef.hand("p4")))
    judgment_after = set(game.state.card_ids_in(ZoneRef.judgment("p4")))
    assert hand_after == hand_before - set(hand_ids)
    assert judgment_after == judgment_before - {judgment_id}
    assert game.runtime.feiyang_selected_ids == tuple(sorted(hand_ids))
    assert game.runtime.feiyang_judgment_choice == judgment_id
    discard_reasons = [
        event.payload.get("reason") for event in game.events
    ]
    assert discard_reasons.count("feiyang_cost") == 2
    assert discard_reasons.count("feiyang_judgment_discard") == 1
    # 判定区实体离开后 entry_index 一并移除
    assert judgment_id not in game.runtime.judgment_entry_indices
    game.assert_resolution_invariants()


def test_feiyang_decline_proceeds_to_judgment_untouched() -> None:
    game = _session(seed=2)
    _feiyang_fixture(game)
    _run_to_p4_first_judgment(game)
    hand_before = set(game.state.card_ids_in(ZoneRef.hand("p4")))
    judgment_before = set(game.state.card_ids_in(ZoneRef.judgment("p4")))
    _step(game, _require_op(game, "feiyang_decline"))
    assert game.phase is ProductionPhase.JUDGMENT
    assert set(game.state.card_ids_in(ZoneRef.hand("p4"))) == hand_before
    assert set(game.state.card_ids_in(ZoneRef.judgment("p4"))) == judgment_before


def test_feiyang_not_available_outside_seat4_first_round() -> None:
    # p1/p2/p3 首回合判定入口无窗口（座次非4号位）
    game = _session(seed=2)
    for expected_player in ("p1", "p2", "p3"):
        _enter_play(game)
        assert game.phase is ProductionPhase.PLAY, (
            f"{expected_player} 首回合不应进入飞扬窗口"
        )
        _end_turn(game)
    # p4 首回合无判定区牌 → 无可执行收益 → 不打开窗口
    assert game.current_player_id == "p4"
    _step(game, _require_op(game, "proceed_prepare"))
    assert game.phase is ProductionPhase.JUDGMENT


def test_feiyang_second_round_not_available() -> None:
    game = _session(seed=2)
    _feiyang_fixture(game)
    # 第一轮 p4 放弃飞扬，完成第4回合与后续三个回合
    _run_to_p4_first_judgment(game)
    _step(game, _require_op(game, "feiyang_decline"))
    # 移除测试注入的判定区牌（非延时锦囊，不能进入正式判定），继续回合
    injected = next(iter(game.state.card_ids_in(ZoneRef.judgment("p4"))))
    game._state = game.state.move_card(injected, DISCARD_PILE)
    _step(game, _require_op(game, "proceed_judgment"))
    _step(game, _require_op(game, "proceed_draw"))
    _end_turn(game)
    for _ in range(3):
        _enter_play(game)
        _end_turn(game)
    # 第二轮 p4 判定入口不再有窗口（feiyang_first_round_only）
    assert game.current_player_id == "p4"
    assert game.runtime.turn_number == 8
    _step(game, _require_op(game, "proceed_prepare"))
    assert game.phase is ProductionPhase.JUDGMENT


def test_feiyang_activate_rejects_forged_payload() -> None:
    game = _session(seed=2)
    _feiyang_fixture(game)
    _run_to_p4_first_judgment(game)
    real = _require_op(game, "feiyang_activate")

    class _ForgedController:
        def choose(self, legal_actions: Any, context: Any) -> LegalAction:
            del legal_actions, context
            return LegalAction(
                action_type=real.action_type,
                actor_id=game.current_player_id,
                action_id=real.action_id,
                card_instance_id=real.card_instance_id,
                target_ids=real.target_ids,
                payload={
                    "operation": "feiyang_activate",
                    "hand_ids": ["not-a-real-card-a", "not-a-real-card-b"],
                    "judgment_id": "not-a-real-judgment",
                },
            )

    with pytest.raises(InvalidActionError):
        game.step(_ForgedController())


# ----------------------------------------------------------------------
# 5. TEAM_TARGET_LEGALITY / 卡牌核心复用
# ----------------------------------------------------------------------


def test_slash_targets_include_teammate() -> None:
    """2v2 无禁止攻击队友规则：目标枚举由距离驱动，不排除队友。"""
    game = _session(seed=2)
    _enter_play(game)
    slash_targets = {
        action.target_ids
        for action in game.legal_actions()
        if action.payload.get("operation") == "use_slash"
    }
    # 默认攻击范围1：p4（队友）与 p2（距离1）同为合法目标
    assert ("p4",) in slash_targets
    assert ("p2",) in slash_targets
    # 装备麒麟弓（范围5）后距离2的 p3 同样进入目标集合（距离驱动）
    for instance_id in game.state.card_ids_in(DRAW_PILE):
        if game.state.cards_by_id[instance_id].card_key == "sgs_weapon_qilingong":
            game._state = game.state.move_card(
                instance_id, ZoneRef.equipment("p1", "weapon")
            )
            break
    slash_targets = {
        action.target_ids
        for action in game.legal_actions()
        if action.payload.get("operation") == "use_slash"
    }
    assert ("p3",) in slash_targets


def test_card_core_reuse_38_of_38() -> None:
    game = _session(seed=2)
    keys = {record.card_key for record in game.formal_registry.records}
    assert len(keys) == 38
    assert len(game.state.cards) == 160


# ----------------------------------------------------------------------
# 6. REPLAY_MODE_STATE / FORMAL_GATE
# ----------------------------------------------------------------------


def test_execution_snapshot_mode_fields() -> None:
    game = _session(seed=2)
    snapshot = game.execution_snapshot
    assert snapshot["mode"] == FORMAL_NO_SKILL_2V2_MODE
    assert snapshot["mode_policy_identity"] == "mode:formal_no_skill_2v2"
    assert snapshot["teams"] == {
        "p1": "team_a",
        "p2": "team_b",
        "p3": "team_b",
        "p4": "team_a",
    }
    assert snapshot["outcome_policy_identity"] == "outcome:formal_no_skill_2v2"


def test_formal_2v2_gate_ready() -> None:
    readiness = inspect_formal_2v2_readiness()
    assert readiness.mode_id == FORMAL_NO_SKILL_2V2_MODE
    assert readiness.mode_runtime_reachable is True
    assert readiness.global_card_semantics_complete is True
    assert readiness.reexecution_replay_supported is True
    assert readiness.unsupported_rules == 0
    assert readiness.approximation_count == 0
    assert readiness.formal_2v2_no_skill_ready is True
    assert readiness.ready_2v2 is True
    # §2.12：客户端30分钟墙钟/评分裁定绝不进入模拟门禁
    assert readiness.client_timeout_score_adjudication is False
    assert readiness.blockers == ()
    payload = readiness.to_dict()
    assert payload["2v2_ready"] is True


# ----------------------------------------------------------------------
# 7. 平局终局（牌堆耗尽，§2.11）
# ----------------------------------------------------------------------


def _drain_deck_to(game: ProductionBasicCardBatch, count: int) -> None:
    ids = list(game.state.card_ids_in(DRAW_PILE))
    assert len(ids) >= count
    game._state = game.state.move_cards(
        {instance_id: DISCARD_PILE for instance_id in ids[count:]}
    )


def test_draw_after_draw_phase_consumes_exact_pile() -> None:
    """摸牌阶段原子取牌完整执行后牌堆变为0 → 立即平局。"""
    game = _session(seed=2)
    _drain_deck_to(game, 2)
    hand_before = len(game.state.card_ids_in(ZoneRef.hand("p1")))
    _step(game, _require_op(game, "proceed_prepare"))
    _step(game, _require_op(game, "proceed_judgment"))
    _step(game, _require_op(game, "proceed_draw"))
    assert game.is_finished is True
    assert game.winner_id is None
    assert game.runtime.game_over_reason == "2v2_draw_deck_exhausted"
    assert game.phase is ProductionPhase.FINISHED
    assert len(game.state.card_ids_in(ZoneRef.hand("p1"))) == hand_before + 2
    draw_events = [e for e in game.events if e.event_type is EventType.DRAW]
    assert len(draw_events) == 1
    assert draw_events[0].payload["reason"] == "2v2_draw_deck_exhausted"
    game.assert_finished_state_invariants()


def test_draw_when_insufficient_pile_no_partial_draw() -> None:
    """原子步骤开始时牌量不足 → 不执行半截取牌，直接平局。"""
    game = _session(seed=2)
    _drain_deck_to(game, 1)
    hand_before = len(game.state.card_ids_in(ZoneRef.hand("p1")))
    _step(game, _require_op(game, "proceed_prepare"))
    _step(game, _require_op(game, "proceed_judgment"))
    _step(game, _require_op(game, "proceed_draw"))
    assert game.is_finished is True
    assert game.winner_id is None
    assert game.runtime.game_over_reason == "2v2_draw_deck_exhausted"
    # 不执行半截取牌：手牌数不变、牌堆剩余1张
    assert len(game.state.card_ids_in(ZoneRef.hand("p1"))) == hand_before
    assert len(game.state.card_ids_in(DRAW_PILE)) == 1
    game.assert_finished_state_invariants()


# ----------------------------------------------------------------------
# 8. 固定种子自然结束 + 严格重执行（20 种子）
# ----------------------------------------------------------------------


def run_2v2_fixed_seed_sweep(
    start: int = 0,
    count: int = 20,
    *,
    max_steps: int = 6000,
    reexecute: bool = True,
) -> dict[str, object]:
    """正式2v2固定种子验收：自然结束、无安全上限、无未支持规则、
    合法队伍胜者、严格重执行。安全上限触发视为失败（§2.12：
    safety cap 不得伪装客户端30分钟裁定）。"""
    results: list[dict[str, object]] = []
    failures: list[dict[str, object]] = []
    for seed in range(start, start + count):
        try:
            record = record_reference_formal_2v2(
                seed,
                configuration=Formal2v2Configuration.formal_profile(),
                analysis_only=False,
                max_steps=max_steps,
            )
        except Exception as exc:
            failures.append(
                {"seed": seed, "stage": "record",
                 "error": f"{type(exc).__name__}:{exc}"}
            )
            continue
        winner = record.outcome["winner_id"]
        finish_reason = record.outcome["finish_reason"]
        if winner not in (None, "team_a", "team_b") or (
            winner is None and finish_reason != "2v2_draw_deck_exhausted"
        ) or (winner is not None and finish_reason != "team_eliminated"):
            failures.append(
                {"seed": seed, "stage": "outcome",
                 "error": f"非法终局 winner={winner!r} reason={finish_reason!r}"}
            )
            continue
        reexecution_verified = False
        if reexecute:
            try:
                result = reexecute_production_replay(record)
                reexecution_verified = result.verified
            except Exception as exc:
                failures.append(
                    {"seed": seed, "stage": "reexecute",
                     "error": f"{type(exc).__name__}:{exc}"}
                )
                continue
        results.append(
            {
                "seed": seed,
                "winner": winner,
                "finish_reason": finish_reason,
                "step_count": record.outcome["step_count"],
                "turn_count": record.outcome["turn_count"],
                "reexecution_verified": reexecution_verified,
            }
        )
    return {
        "seeds": results,
        "failure_count": len(failures),
        "failures": failures,
        "natural_end_count": len(results),
    }


def test_fixed_seed_20_natural_end_strict_reexecution() -> None:
    report = run_2v2_fixed_seed_sweep(0, 20)
    assert report["failure_count"] == 0, report["failures"]
    assert report["natural_end_count"] == 20
    winners = {item["winner"] for item in report["seeds"]}
    assert winners <= {None, "team_a", "team_b"}
    for item in report["seeds"]:
        assert item["reexecution_verified"] is True
        assert item["step_count"] > 0


def test_determinism_across_fresh_session_secrets() -> None:
    """同一种子、不同会话秘密：胜者/动作数/回合数/终局状态哈希一致。"""
    from scripts.sgs_engine.engine import canonical_state_snapshot
    from scripts.sgs_engine.replay import sha256_value

    def run_once(secret_index: int) -> tuple[object, int, int, str]:
        game = _session(
            seed=9,
            session_id=f"determinism-{secret_index}",
            session_secret=bytes([secret_index + 1]) * 32,
        )
        controller = BatchReferenceController()
        while not game.is_finished and game.step_count < 6000:
            legal = game.legal_actions()
            chosen = controller.choose(legal, game._context())
            game.step(BatchActionIdController(chosen.action_id))
        game.assert_finished_state_invariants()
        return (
            game.winner_id,
            game.step_count,
            game.runtime.turn_number,
            sha256_value(canonical_state_snapshot(game.state)),
        )

    first = run_once(0)
    for secret_index in (1, 2):
        assert run_once(secret_index) == first


def test_safety_cap_is_test_failure_not_auto_win() -> None:
    """§2.12：安全上限触发是测试失败，绝不自动判某队胜利。"""
    game = _session(seed=0)
    controller = BatchReferenceController()
    from scripts.sgs_engine.production_batch import (
        ProductionBatchSafetyLimitError,
    )

    with pytest.raises(ProductionBatchSafetyLimitError):
        game.run(controller, max_steps=40)
    assert game.is_finished is False
    assert game.winner_id is None
    assert game.runtime.game_over_reason is None
