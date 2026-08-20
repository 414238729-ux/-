# -*- coding: utf-8 -*-
"""POST-B C4：正式无武将技能斗地主模式（mode_doudizhu）核心机制测试。

涵盖：
- Canonical profile 结构、座次、阵营、初始手牌 4/4/4、先手 1 号位地主、
  地主初始体力 5/5、农民 4/4、不可变性与边界门禁；
- 现场现场自检 inspect_formal_doudizhu_readiness 派生与门禁；
- 地主永久“跋扈”准备阶段摸1张牌修饰器与牌堆耗尽平局事务；
- 地主永久“跋扈”出牌阶段使用【杀】次数上限为2，农民为1；
- 地主永久“飞扬”每轮每回合判定阶段入口可用性（农民不可用）；
- DoudizhuOutcomePolicy 阵营胜负判定与牌堆耗尽平局判定。
"""

from types import MappingProxyType
import pytest

from scripts.sgs_engine.actions import ActionType, InvalidActionError, LegalAction
from scripts.sgs_engine.model import (
    DISCARD_PILE,
    DRAW_PILE,
    GameState,
    PlayerState,
    ZoneRef,
)
from scripts.sgs_engine.mode_doudizhu import (
    FORMAL_NO_SKILL_DOUDIZHU_MODE,
    DoudizhuModePolicy,
    DoudizhuOutcomePolicy,
    FormalDoudizhuBlocker,
    FormalDoudizhuConfiguration,
    FormalDoudizhuConfigurationError,
    FormalDoudizhuReadiness,
    FormalDoudizhuSession,
    TrustedFormalDoudizhuConfiguration,
    assert_trusted_formal_doudizhu_configuration,
    inspect_formal_doudizhu_readiness,
)
from scripts.sgs_engine.multiplayer import PlayerTopology
from scripts.sgs_engine.production_batch import (
    ProductionBasicCardBatch,
    ProductionPhase,
    _DeckExhaustedDraw,
)


def test_canonical_profile_identity_and_immutable() -> None:
    """Canonical formal no-skill doudizhu profile 必须满足规则规范（§3.1-§3.5）。"""
    config = FormalDoudizhuConfiguration.formal_profile()
    assert isinstance(config, TrustedFormalDoudizhuConfiguration)
    assert config.player_ids == ("p1", "p2", "p3")
    assert config.base_hp == (5, 4, 4)
    assert config.base_max_hp == (5, 4, 4)
    assert config.initial_hand_counts == (4, 4, 4)
    assert config.first_player_id == "p1"
    assert config.feiyang_seat == 1
    assert config.feiyang_enabled is True
    assert config.bahu_prepare_draw_enabled is True
    assert config.bahu_slash_limit == 2
    assert config.peasant_slash_limit == 1
    assert config.death_reward_mode == "choice_heal1_draw2_decline"
    assert config.deck_supply_mode == "no_reshuffle_draw"

    # 座次与阵营映射
    assert config.camp_of(1) == "landlord"
    assert config.camp_of(2) == "peasants"
    assert config.camp_of(3) == "peasants"
    assert dict(config.camps_by_player()) == {
        "p1": "landlord",
        "p2": "peasants",
        "p3": "peasants",
    }

    # Authority boundary: trusted capability
    assert_trusted_formal_doudizhu_configuration(config)


def test_custom_profile_rejection_in_trusted_boundary() -> None:
    """普通构造的 FormalDoudizhuConfiguration 不具备 trusted 权限。"""
    custom = FormalDoudizhuConfiguration(
        player_ids=("p1", "p2", "p3"),
        base_hp=(5, 4, 4),
        base_max_hp=(5, 4, 4),
        initial_hand_counts=(4, 4, 4),
        first_player_id="p1",
    )
    with pytest.raises(FormalDoudizhuConfigurationError, match="exact type"):
        assert_trusted_formal_doudizhu_configuration(custom)

    with pytest.raises(TypeError, match="FormalDoudizhuConfiguration"):
        assert_trusted_formal_doudizhu_configuration("not_a_config")  # type: ignore[arg-type]


def test_invalid_configurations_rejected() -> None:
    """非法配置参数在 __post_init__ 中被拒绝。"""
    # 非3人
    with pytest.raises(FormalDoudizhuConfigurationError, match="恰好3名"):
        FormalDoudizhuConfiguration(player_ids=("p1", "p2"))  # type: ignore[arg-type]

    # 重复ID
    with pytest.raises(FormalDoudizhuConfigurationError, match="不能重复"):
        FormalDoudizhuConfiguration(player_ids=("p1", "p1", "p3"))

    # 手牌和不为12
    with pytest.raises(FormalDoudizhuConfigurationError, match="合计12张"):
        FormalDoudizhuConfiguration(initial_hand_counts=(3, 4, 4))

    # 先手不是1号位地主
    with pytest.raises(FormalDoudizhuConfigurationError, match="先手必须是1号位地主"):
        FormalDoudizhuConfiguration(first_player_id="p2")

    # 体力高于上限
    with pytest.raises(FormalDoudizhuConfigurationError, match="初始体力不能高于体力上限"):
        FormalDoudizhuConfiguration(base_hp=(6, 4, 4), base_max_hp=(5, 4, 4))


def test_inspect_formal_doudizhu_readiness() -> None:
    """现场派生斗地主就绪状态自检。"""
    readiness = inspect_formal_doudizhu_readiness()
    assert isinstance(readiness, FormalDoudizhuReadiness)
    assert readiness.mode_id == FORMAL_NO_SKILL_DOUDIZHU_MODE
    assert readiness.deck_count == 160
    assert readiness.registered_card_key_count == 38
    assert readiness.registered_instance_count == 160
    assert readiness.global_card_semantics_complete is True
    assert readiness.mode_runtime_reachable is True
    assert readiness.mode_implemented is True
    assert readiness.reexecution_replay_supported is True
    assert readiness.unsupported_rules == 0
    assert readiness.approximation_count == 0
    assert readiness.formal_doudizhu_no_skill_ready is True
    assert readiness.doudizhu_ready is True
    assert readiness.client_timeout_score_adjudication is False
    assert readiness.blockers == ()

    payload = readiness.to_dict()
    assert payload["mode_id"] == FORMAL_NO_SKILL_DOUDIZHU_MODE
    assert payload["doudizhu_ready"] is True


def test_doudizhu_session_initialization() -> None:
    """FormalDoudizhuSession 正确初始化各角色座次、体力、手牌与角色 profile。"""
    session = FormalDoudizhuSession(
        seed=42,
        configuration=FormalDoudizhuConfiguration.formal_profile(),
        session_id="test-doudizhu-init",
    )
    assert session.mode_id == FORMAL_NO_SKILL_DOUDIZHU_MODE
    assert session.current_player_id == "p1"
    assert session.first_player_id == "p1"
    assert len(session.state.players) == 3

    # 地主 5/5，农民 4/4
    p1 = session.state.players_by_id["p1"]
    p2 = session.state.players_by_id["p2"]
    p3 = session.state.players_by_id["p3"]
    assert p1.hp == 5 and p1.max_hp == 5
    assert p2.hp == 4 and p2.max_hp == 4
    assert p3.hp == 4 and p3.max_hp == 4

    # 初始手牌 4/4/4
    for pid in ("p1", "p2", "p3"):
        assert len(session.state.card_ids_in(ZoneRef.hand(pid))) == 4

    # 牌堆 160 - 12 = 148
    assert len(session.state.card_ids_in(DRAW_PILE)) == 148

    # 角色档案均为 soldier (gender NONE)
    for p in session.state.players:
        assert p.character.character_key == "soldier"
        assert p.character.gender.value == "none"


def test_doudizhu_outcome_policy_elimination_and_draw() -> None:
    """胜负判定：地主阵亡农民胜，双农民阵亡地主胜，单农民阵亡继续。"""
    camps = {"p1": "landlord", "p2": "peasants", "p3": "peasants"}
    policy = DoudizhuOutcomePolicy(camps)
    assert policy.finish_reason == "team_eliminated"
    assert policy.draw_finish_reason == "doudizhu_draw_deck_exhausted"

    # 初始全存活 -> winner is None
    players = (
        PlayerState(player_id="p1", seat=1, hp=5, max_hp=5, alive=True),
        PlayerState(player_id="p2", seat=2, hp=4, max_hp=4, alive=True),
        PlayerState(player_id="p3", seat=3, hp=4, max_hp=4, alive=True),
    )
    topo = PlayerTopology(players=players)
    assert policy.resolve_winner_after_death(topo, "p2") is None

    # p2 死亡，p3 存活 -> winner is None (游戏继续)
    players_p2_dead = (
        PlayerState(player_id="p1", seat=1, hp=5, max_hp=5, alive=True),
        PlayerState(player_id="p2", seat=2, hp=0, max_hp=4, alive=False),
        PlayerState(player_id="p3", seat=3, hp=4, max_hp=4, alive=True),
    )
    topo_p2_dead = PlayerTopology(players=players_p2_dead)
    assert policy.resolve_winner_after_death(topo_p2_dead, "p2") is None

    # p2 和 p3 均死亡 -> 地主胜
    players_both_peasants_dead = (
        PlayerState(player_id="p1", seat=1, hp=5, max_hp=5, alive=True),
        PlayerState(player_id="p2", seat=2, hp=0, max_hp=4, alive=False),
        PlayerState(player_id="p3", seat=3, hp=0, max_hp=4, alive=False),
    )
    topo_peasants_dead = PlayerTopology(
        players=players_both_peasants_dead
    )
    assert policy.resolve_winner_after_death(topo_peasants_dead, "p3") == "landlord"

    # 地主 p1 死亡 -> 农民胜
    players_landlord_dead = (
        PlayerState(player_id="p1", seat=1, hp=0, max_hp=5, alive=False),
        PlayerState(player_id="p2", seat=2, hp=4, max_hp=4, alive=True),
        PlayerState(player_id="p3", seat=3, hp=4, max_hp=4, alive=True),
    )
    topo_landlord_dead = PlayerTopology(
        players=players_landlord_dead
    )
    assert policy.resolve_winner_after_death(topo_landlord_dead, "p1") == "peasants"


def test_bahu_prepare_draw_transaction_and_exhaustion() -> None:
    """地主在准备阶段摸1张牌（跋扈），农民不摸。牌堆耗尽时形成正式平局。"""
    from scripts.sgs_engine.events import EventType
    from scripts.sgs_engine.production_batch import BatchActionIdController

    session = FormalDoudizhuSession(
        seed=10,
        configuration=FormalDoudizhuConfiguration.formal_profile(),
        session_id="test-bahu-prepare",
    )
    assert session.phase is ProductionPhase.PREPARE
    assert session.current_player_id == "p1"

    p1_hand_before = len(session.state.card_ids_in(ZoneRef.hand("p1")))
    assert p1_hand_before == 4

    # 地主推进准备阶段
    legal = session.legal_actions()
    proceed_action = next(a for a in legal if a.payload.get("operation") == "proceed_prepare")
    session.step(BatchActionIdController(proceed_action.action_id))

    # 地主摸了1张牌（跋扈摸牌），手牌变为5
    p1_hand_after = len(session.state.card_ids_in(ZoneRef.hand("p1")))
    assert p1_hand_after == 5

    # 检查事件记录中有 reason="bahu_prepare_draw" 的摸牌事件
    draw_events = [
        e for e in session.events
        if e.event_type == EventType.CARD_MOVED
        and hasattr(e, "payload")
        and e.payload is not None
        and e.payload.get("reason") == "bahu_prepare_draw"
    ]
    assert len(draw_events) == 1

    # 准备阶段牌堆耗尽平局测试：将牌堆排空
    session2 = FormalDoudizhuSession(
        seed=11,
        configuration=FormalDoudizhuConfiguration.formal_profile(),
        session_id="test-bahu-prepare-exhaustion",
    )
    # 将牌堆全部移入弃牌堆以测试耗尽平局
    for cid in list(session2.state.card_ids_in(DRAW_PILE)):
        session2._state = session2._state.move_card(cid, DISCARD_PILE)
    assert len(session2.state.card_ids_in(DRAW_PILE)) == 0

    legal2 = session2.legal_actions()
    proceed_action2 = next(a for a in legal2 if a.payload.get("operation") == "proceed_prepare")
    session2.step(BatchActionIdController(proceed_action2.action_id))

    # 立即平局终局
    assert session2.is_finished is True
    assert session2.winner_id is None
    assert session2.runtime.game_over_reason == "doudizhu_draw_deck_exhausted"


def test_bahu_slash_limit_two_for_landlord_one_for_peasant() -> None:
    """出牌阶段杀次数上限：地主为2次，农民为1次。"""
    session = FormalDoudizhuSession(
        seed=20,
        configuration=FormalDoudizhuConfiguration.formal_profile(),
        session_id="test-slash-limits",
    )
    assert session.normal_play_slash_limit("p1") == 2
    assert session.normal_play_slash_limit("p2") == 1
    assert session.normal_play_slash_limit("p3") == 1


def test_bahu_prepare_draw_exactly_one_card_exhaustion() -> None:
    """准备阶段开始时牌堆恰好剩1张：地主摸走最后1张后，牌堆变为0，立即形成平局终局，不进入判定阶段。"""
    from scripts.sgs_engine.production_batch import BatchActionIdController

    session = FormalDoudizhuSession(
        seed=12,
        configuration=FormalDoudizhuConfiguration.formal_profile(),
        session_id="test-bahu-exact-one-exhaustion",
    )
    assert session.phase is ProductionPhase.PREPARE
    assert session.current_player_id == "p1"

    # 将牌堆排空至恰好1张
    cards_in_deck = list(session.state.card_ids_in(DRAW_PILE))
    for cid in cards_in_deck[1:]:
        session._state = session._state.move_card(cid, DISCARD_PILE)
    assert len(session.state.card_ids_in(DRAW_PILE)) == 1

    p1_hand_before = len(session.state.card_ids_in(ZoneRef.hand("p1")))

    # 地主推进准备阶段
    legal = session.legal_actions()
    proceed_action = next(a for a in legal if a.payload.get("operation") == "proceed_prepare")
    session.step(BatchActionIdController(proceed_action.action_id))

    # 地主成功摸走最后1张牌（手牌增加1）
    p1_hand_after = len(session.state.card_ids_in(ZoneRef.hand("p1")))
    assert p1_hand_after == p1_hand_before + 1
    assert len(session.state.card_ids_in(DRAW_PILE)) == 0

    # 消费后牌堆耗尽检查立即形成正式平局终局，不进入 JUDGMENT/PLAY
    assert session.is_finished is True
    assert session.winner_id is None
    assert session.runtime.game_over_reason == "doudizhu_draw_deck_exhausted"
    assert session.phase is ProductionPhase.FINISHED


def test_feiyang_available_for_landlord_every_round() -> None:
    """地主永久拥有飞扬，判定区有牌且手牌>=2时每回合判定阶段开始时可用。"""
    policy = DoudizhuModePolicy(FormalDoudizhuConfiguration.formal_profile())
    # 地主（座次 1）每一轮均可用
    assert policy.feiyang_available(player_id="p1", seat=1, turn_number=1) is True
    assert policy.feiyang_available(player_id="p1", seat=1, turn_number=2) is True
    assert policy.feiyang_available(player_id="p1", seat=1, turn_number=10) is True

    # 农民不可用
    assert policy.feiyang_available(player_id="p2", seat=2, turn_number=1) is False
    assert policy.feiyang_available(player_id="p3", seat=3, turn_number=1) is False
