# -*- coding: utf-8 -*-
"""POST-B C1：多人权威核心基础（MP_AUTHORITATIVE_FOUNDATION）验收测试。

覆盖 C1 的 12 项生产路径验收：

1. 两人局拓扑退化为既有对手语义（行为保持）；
2. 四人局初始化：座次稳定、轮转发牌、自定义ID与参数校验；
3. 存活角色环任意锚点遍历（座次递增、环回、排除锚点、基础距离）；
4. 生产回合继任跳过死亡角色；
5. 死亡不重编号座次 + 拓扑校验边界失败关闭；
6. 四人局完整回合循环（p1→p2→p3→p4→p1）；
7. 群体锦囊四目标快照顺序（含跳过死亡角色）；
8. 玩家可见回放四观察者隔离与非法观察者失败关闭；
9. 四人局回放携带模式胜负策略与夹具严格重执行（策略不匹配/缺失失败关闭）；
10. 未注册策略的四人局死亡胜负判定失败关闭（不猜2v2/身份场/最后一人）；
11. 两人局 formal duel 终局行为保持不变（seed 0/7 对照 R5 记录）；
12. 四人局伪造/过期多人动作失败关闭。

本测试明确不把 multi_player_production_proven / authoritative_full_game_core
置为 true，不声明 2v2 就绪：C1 只证明拓扑、回合循环、群体目标顺序、
死亡座位遍历与胜负策略边界。
"""

from __future__ import annotations

import pytest

from scripts.sgs_engine.actions import (
    ActionType,
    InvalidActionError,
    LegalAction,
    UnsupportedRuleError,
    validate_action,
)
from scripts.sgs_engine.events import EventType
from scripts.sgs_engine.model import (
    DISCARD_PILE,
    DRAW_PILE,
    PlayerState,
    ZoneRef,
)
from scripts.sgs_engine.multiplayer import (
    OutcomePolicy,
    PlayerTopology,
    resolve_victory_after_death,
)
from scripts.sgs_engine.production_batch import (
    BatchActionIdController,
    ProductionBatchError,
    ProductionBasicCardBatch,
    ProductionPhase,
    _replace_player,
)
from scripts.sgs_engine.production_replay import (
    ProductionReplayFormatError,
    record_reference_production_batch,
    reexecute_production_replay,
)

SHA = "sgs_basic_sha"
SHAN = "sgs_basic_shan"
TAO = "sgs_basic_tao"
JIU = "sgs_basic_jiu"
NANMAN = "sgs_trick_nanmanruqin"

# seed 2 的四人局首回合角色是 p1（本文件多个测试依赖该确定性事实）。
_FOUR_PLAYER_SEED = 2


# ----------------------------------------------------------------------
# C1 测试专用脚手架：模式胜负策略（不是真实模式规则）
# ----------------------------------------------------------------------


class _FirstBloodOutcomePolicy(OutcomePolicy):
    """C1 测试脚手架：首次确认死亡即终局，胜者为座次最小的其他存活角色。

    该策略只用于证明生产回放/可见性管线的策略注册边界，不是任何真实
    模式的胜负规则；真实 2v2/身份场/最后一人规则属于后续模式层。
    """

    def __init__(self) -> None:
        object.__setattr__(self, "policy_id", "c1_test_first_blood_scaffold")

    def resolve_winner_after_death(
        self, topology: PlayerTopology, dying_id: str
    ) -> str:
        alive = topology.alive_ids
        for candidate in alive:
            if candidate != dying_id:
                return candidate
        raise UnsupportedRuleError("first blood 脚手架找不到非死亡存活角色")


class _MismatchedScaffoldPolicy(OutcomePolicy):
    """身份不同的脚手架策略：只用于验证策略身份不一致时失败关闭。"""

    def __init__(self) -> None:
        object.__setattr__(self, "policy_id", "c1_test_other_scaffold")

    def resolve_winner_after_death(
        self, topology: PlayerTopology, dying_id: str
    ) -> str:
        del topology, dying_id
        raise UnsupportedRuleError("该脚手架策略不参与真实结算")


# ----------------------------------------------------------------------
# 测试辅助
# ----------------------------------------------------------------------


def _fresh_four(*, hp: int = 8) -> ProductionBasicCardBatch:
    """四人局会话（seed 2，首回合 p1）；默认 hp 8 使手牌上限 8 免弃牌选择。"""
    game = ProductionBasicCardBatch(
        seed=_FOUR_PLAYER_SEED,
        player_hp=(hp, hp, hp, hp),
        player_max_hp=(hp, hp, hp, hp),
    )
    assert game.first_player_id == "p1"
    return game


def _proceed(game: ProductionBasicCardBatch, operation: str) -> None:
    action = next(
        a
        for a in game.legal_actions()
        if a.payload.get("operation") == operation
    )
    game.step(BatchActionIdController(action.action_id))


def _step(game: ProductionBasicCardBatch, action: object) -> None:
    assert action is not None and getattr(action, "action_id", None), action
    game.step(BatchActionIdController(action.action_id))  # type: ignore[attr-defined]


def _action(
    game: ProductionBasicCardBatch,
    operation: str,
    *,
    card_key: str | None = None,
    target: str | None = None,
) -> LegalAction | None:
    for action in game.legal_actions():
        if action.payload.get("operation") != operation:
            continue
        if card_key is not None and action.payload.get("card_key") != card_key:
            continue
        if target is not None and (
            not action.target_ids or action.target_ids[0] != target
        ):
            continue
        return action
    return None


def _enter_play(game: ProductionBasicCardBatch) -> None:
    for operation in ("proceed_prepare", "proceed_judgment", "proceed_draw"):
        _proceed(game, operation)
    assert game.phase is ProductionPhase.PLAY


def _complete_turn(game: ProductionBasicCardBatch) -> None:
    """从 PREPARE 完整走完当前角色回合；hp 上限 8 时弃牌阶段自动跳过。"""
    if game.phase is ProductionPhase.PREPARE:
        _enter_play(game)
    _proceed(game, "end_play_phase")
    assert game.phase is ProductionPhase.END, "手牌不超过上限时弃牌阶段自动完成"
    _proceed(game, "end_turn")
    assert game.phase is ProductionPhase.PREPARE


def _move_to_hand(
    game: ProductionBasicCardBatch, instance_id: str, player_id: str
) -> None:
    if game.state.location_of(instance_id) != ZoneRef.hand(player_id):
        game._state = game.state.move_card(instance_id, ZoneRef.hand(player_id))


def _give_slash_to_first_player(game: ProductionBasicCardBatch) -> str:
    """把一张不在任何手牌区的杀放入 p1 手牌（确定性夹具）。"""
    state = game.state
    slash_id = next(
        record.instance_id
        for record in game.formal_registry.instances_of(SHA)
        if state.location_of(record.instance_id).kind.value != "hand"
    )
    game._state = state.move_card(slash_id, ZoneRef.hand("p1"))
    return slash_id


def _strip_rescue_and_dodge_cards(game: ProductionBasicCardBatch) -> None:
    """移走所有角色手牌中的桃/酒与 p2 手牌中的闪，保证无救援、无闪避。"""
    state = game.state
    for player_id in game.player_ids:
        for instance_id in list(state.card_ids_in(ZoneRef.hand(player_id))):
            key = state.cards_by_id[instance_id].card_key
            if key in (TAO, JIU) or (player_id == "p2" and key == SHAN):
                state = state.move_card(instance_id, DRAW_PILE)
    game._state = state


def _first_blood_fixture(game: ProductionBasicCardBatch) -> None:
    """录制/重执行共享夹具：p1 持杀、p2（体力1）无闪、全员无桃酒。

    必须与 record_reference_production_batch 与
    reexecute_production_replay 使用同一个函数对象。
    """
    _strip_rescue_and_dodge_cards(game)
    _give_slash_to_first_player(game)


def _four_player_first_blood_record():
    """录制一局 9 步四人局首杀终局（首杀策略脚手架）。"""
    game = ProductionBasicCardBatch(
        seed=_FOUR_PLAYER_SEED,
        player_hp=(4, 1, 4, 4),
        player_max_hp=(4, 1, 4, 4),
        outcome_policy=_FirstBloodOutcomePolicy(),
    )
    record = record_reference_production_batch(
        seed=_FOUR_PLAYER_SEED,
        player_hp=(4, 1, 4, 4),
        player_max_hp=(4, 1, 4, 4),
        _game=game,
        fixture=_first_blood_fixture,
    )
    return record


# ----------------------------------------------------------------------
# 1. 两人局拓扑退化为既有对手语义
# ----------------------------------------------------------------------


def test_two_player_topology_matches_legacy_opponent_semantics() -> None:
    game = ProductionBasicCardBatch(seed=1)
    topo = game.topology
    assert topo.player_count == 2
    assert topo.alive_ids == ("p1", "p2")
    # 存活环顺序与 legacy opponent_of 完全一致
    assert topo.next_alive("p1") == "p2" == game.opponent_of("p1")
    assert topo.next_alive("p2") == "p1" == game.opponent_of("p2")
    assert topo.alive_ring_from("p1") == ("p1", "p2")
    assert topo.alive_ring_from("p2") == ("p2", "p1")
    assert topo.all_other_alive_ids("p1") == ("p2",)
    assert topo.all_other_alive_ids("p2") == ("p1",)
    assert topo.base_seat_distance("p1", "p2") == 1
    assert topo.base_seat_distance("p1", "p1") == 0
    # 两人局未注册策略：快照身份为隐式双人单挑
    snapshot = game.execution_snapshot
    assert snapshot["schema"] == "production-basic-batch-execution-v2"
    assert snapshot["player_count"] == 2
    assert snapshot["outcome_policy_identity"] == "implicit_two_player_duel"


# ----------------------------------------------------------------------
# 2. 四人局初始化：座次稳定与轮转发牌
# ----------------------------------------------------------------------


def test_four_player_initialization_stable_seats_and_dealing() -> None:
    game = _fresh_four(hp=4)
    assert game.player_ids == ("p1", "p2", "p3", "p4")
    players = game.state.players
    assert [player.seat for player in players] == [1, 2, 3, 4]
    assert [player.player_id for player in players] == ["p1", "p2", "p3", "p4"]
    assert all(player.alive and player.hp == 4 for player in players)
    # 轮转发牌：每名玩家4张、互不重叠、其余进入牌堆
    hands = [
        tuple(game.state.card_ids_in(ZoneRef.hand(player_id)))
        for player_id in game.player_ids
    ]
    assert all(len(hand) == 4 for hand in hands)
    dealt = [card for hand in hands for card in hand]
    assert len(set(dealt)) == 16
    assert len(game.state.card_ids_in(DRAW_PILE)) == 160 - 16
    assert game.execution_snapshot["player_count"] == 4
    assert (
        game.execution_snapshot["outcome_policy_identity"]
        == "unregistered_outcome_policy"
    )


def test_four_player_custom_ids_and_parameter_validation() -> None:
    game = ProductionBasicCardBatch(
        seed=1,
        player_hp=(4, 4, 4),
        player_max_hp=(4, 4, 4),
        player_ids=("a", "b", "c"),
    )
    assert game.player_ids == ("a", "b", "c")
    assert [player.seat for player in game.state.players] == [1, 2, 3]
    assert game.topology.player_count == 3
    # 边界：玩家数量、ID 长度/重复、策略类型均失败关闭
    with pytest.raises(ValueError):
        ProductionBasicCardBatch(seed=1, player_hp=(4,), player_max_hp=(4,))
    with pytest.raises(ValueError):
        ProductionBasicCardBatch(seed=1, player_hp=(4, 4), player_max_hp=(4, 3))
    with pytest.raises(ValueError):
        ProductionBasicCardBatch(
            seed=1,
            player_hp=(4, 4, 4),
            player_max_hp=(4, 4, 4),
            player_ids=("a", "b"),
        )
    with pytest.raises(ValueError):
        ProductionBasicCardBatch(
            seed=1,
            player_hp=(4, 4, 4),
            player_max_hp=(4, 4, 4),
            player_ids=("a", "a", "c"),
        )
    with pytest.raises(TypeError):
        ProductionBasicCardBatch(
            seed=1,
            player_hp=(4, 4, 4),
            player_max_hp=(4, 4, 4),
            player_ids=["a", "b", "c"],  # type: ignore[arg-type]
        )
    with pytest.raises(TypeError):
        ProductionBasicCardBatch(
            seed=1,
            player_hp=(4, 4, 4),
            player_max_hp=(4, 4, 4),
            outcome_policy="not-a-policy",  # type: ignore[arg-type]
        )


# ----------------------------------------------------------------------
# 3. 存活角色环任意锚点遍历
# ----------------------------------------------------------------------


def test_alive_ring_traversal_from_arbitrary_anchor() -> None:
    game = _fresh_four(hp=4)
    topo = game.topology
    assert topo.alive_ring_from("p1") == ("p1", "p2", "p3", "p4")
    assert topo.alive_ring_from("p3") == ("p3", "p4", "p1", "p2")
    assert topo.alive_ring_from("p4", include_anchor=False) == (
        "p1",
        "p2",
        "p3",
    )
    assert topo.all_other_alive_ids("p2") == ("p3", "p4", "p1")
    assert [topo.next_alive(pid) for pid in ("p1", "p2", "p3", "p4")] == [
        "p2",
        "p3",
        "p4",
        "p1",
    ]
    # 基础距离：环上两个方向边数较小值
    assert topo.base_seat_distance("p1", "p3") == 2
    assert topo.base_seat_distance("p1", "p4") == 1
    assert topo.base_seat_distance("p2", "p2") == 0
    # 死亡锚点失败关闭
    dead_state = _replace_player(game.state, "p2", hp=0, alive=False)
    dead_topo = PlayerTopology.from_state(dead_state)
    with pytest.raises(UnsupportedRuleError):
        dead_topo.alive_ring_from("p2")
    with pytest.raises(UnsupportedRuleError):
        dead_topo.next_alive("p2")


# ----------------------------------------------------------------------
# 4. 生产回合继任跳过死亡角色
# ----------------------------------------------------------------------


def test_production_turn_successor_skips_dead_player() -> None:
    game = _fresh_four(hp=8)
    _enter_play(game)
    assert game.current_player_id == "p1"
    # 直接在权威状态中确认 p2 死亡（体力归零、不重编号）
    game._state = _replace_player(game.state, "p2", hp=0, alive=False)
    assert game.topology.alive_ids == ("p1", "p3", "p4")
    _proceed(game, "end_play_phase")
    _proceed(game, "end_turn")
    # 继任沿存活环座次递增：p2 已死亡 → p3
    assert game.current_player_id == "p3"
    assert game.runtime.turn_number == 2
    assert game.topology.next_alive("p1") == "p3"


# ----------------------------------------------------------------------
# 5. 死亡不重编号座次 + 拓扑校验边界
# ----------------------------------------------------------------------


def test_death_preserves_seat_numbers_and_topology_validation() -> None:
    game = _fresh_four(hp=4)
    dead_state = _replace_player(game.state, "p2", hp=0, alive=False)
    topo = PlayerTopology.from_state(dead_state)
    # 座次保留、不重编号；死亡角色退出存活环但保留身份
    assert {player.player_id: player.seat for player in topo.players} == {
        "p1": 1,
        "p2": 2,
        "p3": 3,
        "p4": 4,
    }
    assert topo.alive_ids == ("p1", "p3", "p4")
    assert topo.next_alive("p1") == "p3"
    assert topo.alive_ring_from("p4") == ("p4", "p1", "p3")
    # 死亡角色不参与距离环
    with pytest.raises(UnsupportedRuleError):
        topo.base_seat_distance("p1", "p2")
    with pytest.raises(UnsupportedRuleError):
        topo.base_seat_distance("p2", "p1")
    # 拓扑构造边界全部失败关闭
    with pytest.raises(UnsupportedRuleError):
        PlayerTopology((PlayerState("p1", 1, 4, 4),))
    with pytest.raises(UnsupportedRuleError):
        PlayerTopology(
            (PlayerState("p1", 1, 4, 4), PlayerState("p2", 1, 4, 4))
        )  # 座次重复
    with pytest.raises(UnsupportedRuleError):
        PlayerTopology(
            (PlayerState("p1", 1, 4, 4), PlayerState("p2", 3, 4, 4))
        )  # 座次不连续
    with pytest.raises(UnsupportedRuleError):
        PlayerTopology(
            (PlayerState("p1", 1, 4, 4), PlayerState("p1", 2, 4, 4))
        )  # ID 重复
    with pytest.raises(TypeError):
        PlayerTopology((PlayerState("p1", 1, 4, 4), "p2"))  # type: ignore[arg-type]


# ----------------------------------------------------------------------
# 6. 四人局完整回合循环
# ----------------------------------------------------------------------


def test_four_player_full_turn_cycle() -> None:
    game = _fresh_four(hp=8)
    for expected in ("p1", "p2", "p3", "p4", "p1"):
        assert game.current_player_id == expected
        _complete_turn(game)
    assert game.runtime.turn_number == 6  # 5个完整回合后进入第6回合
    assert len(game.state.cards) == 160


# ----------------------------------------------------------------------
# 7. 群体锦囊四目标快照顺序
# ----------------------------------------------------------------------


def test_group_target_sequence_four_player_snapshot_order() -> None:
    game = _fresh_four(hp=8)
    _complete_turn(game)  # p1 回合结束
    assert game.current_player_id == "p2"
    _enter_play(game)
    nanman_id = next(
        record.instance_id
        for record in game.formal_registry.instances_of(NANMAN)
    )
    _move_to_hand(game, nanman_id, "p2")
    action = _action(game, "use_nanman", card_key=NANMAN)
    assert action is not None and action.target_ids == ()
    _step(game, action)
    # 服务器在使用时快照：从使用者 p2 沿座次递增，排除使用者
    group = game.runtime.pending_group_trick
    assert group is not None
    assert group.target_sequence == ("p3", "p4", "p1")
    used_event = next(
        event
        for event in game.events
        if event.event_type is EventType.CARD_USED
        and event.card_key == NANMAN
    )
    assert used_event.target_ids == ("p3", "p4", "p1")


def test_group_target_sequence_skips_dead_player() -> None:
    game = _fresh_four(hp=8)
    _complete_turn(game)
    _enter_play(game)
    # p3 已确认死亡：快照顺序跳过 p3，且不使用任何二元对手假设
    game._state = _replace_player(game.state, "p3", hp=0, alive=False)
    nanman_id = next(
        record.instance_id
        for record in game.formal_registry.instances_of(NANMAN)
    )
    _move_to_hand(game, nanman_id, "p2")
    action = _action(game, "use_nanman", card_key=NANMAN)
    assert action is not None
    _step(game, action)
    group = game.runtime.pending_group_trick
    assert group is not None
    assert group.target_sequence == ("p4", "p1")


# ----------------------------------------------------------------------
# 8. 玩家可见回放四观察者隔离
# ----------------------------------------------------------------------


def test_player_visible_four_observer_isolation() -> None:
    record = _four_player_first_blood_record()
    viewer_ids = ("p1", "p2", "p3", "p4")
    views = {
        viewer_id: record.player_visible_payload(
            viewer_id=viewer_id,
            valid_player_ids=("p1", "p2", "p3", "p4"),
        )
        for viewer_id in viewer_ids
    }
    # 每个视角都能看到公开终局结果，且首杀终局胜者为 p1
    for view in views.values():
        assert view["player_visible"] is True
        assert view["outcome"]["winner_id"] == "p1"
        assert view["outcome"]["finish_reason"] == "opponent_confirmed_dead"
    # 初始发牌：观察者本人可见实体，其他角色一律脱敏（四视角交叉检查）
    for viewer_id, view in views.items():
        for event in view["events"]:
            if (
                event.get("event_type") == "card_gained"
                and event.get("payload", {}).get("reason") == "initial_hand"
            ):
                target = (event.get("target_ids") or [None])[0]
                if target == viewer_id:
                    assert event.get("card_instance_id") is not None
                else:
                    assert event.get("card_instance_id") is None
    # 非行动者视角不保留 chosen_action/legal_actions
    view_p3 = views["p3"]
    p1_decisions = [
        decision
        for decision in view_p3["decisions"]
        if decision.get("context", {}).get("actor_id") == "p1"
    ]
    assert p1_decisions
    assert all("chosen_action" not in d for d in p1_decisions)
    # 公共旁观者视角：全部私有动作脱敏
    observer = record.player_visible_payload()
    assert observer["player_visible"] is True
    assert all("chosen_action" not in d for d in observer["decisions"])
    # 非法观察者失败关闭：未知ID与默认双人合法集合都不静默降级
    with pytest.raises(ValueError):
        record.player_visible_payload(
            viewer_id="p5", valid_player_ids=("p1", "p2", "p3", "p4")
        )
    with pytest.raises(ValueError):
        record.player_visible_payload(viewer_id="p3")


# ----------------------------------------------------------------------
# 9. 四人局回放：策略注册、夹具与严格重执行
# ----------------------------------------------------------------------


def test_four_player_replay_reexecutes_with_policy_and_fixture() -> None:
    record = _four_player_first_blood_record()
    config = record.header["initial_configuration"]
    assert tuple(config["player_hp"]) == (4, 1, 4, 4)
    assert (
        config["outcome_policy_identity"]
        == "outcome:c1_test_first_blood_scaffold"
    )
    assert record.outcome["winner_id"] == "p1"
    assert record.outcome["finish_reason"] == "opponent_confirmed_dead"
    result = reexecute_production_replay(
        record,
        fixture=_first_blood_fixture,
        outcome_policy=_FirstBloodOutcomePolicy(),
    )
    assert result.verified is True
    assert result.winner_id == "p1"
    # 未提供策略 / 策略身份不一致：失败关闭
    with pytest.raises(ProductionReplayFormatError):
        reexecute_production_replay(record, fixture=_first_blood_fixture)
    with pytest.raises(ProductionReplayFormatError):
        reexecute_production_replay(
            record,
            fixture=_first_blood_fixture,
            outcome_policy=_MismatchedScaffoldPolicy(),
        )


# ----------------------------------------------------------------------
# 10. 未注册策略的四人局死亡胜负判定失败关闭
# ----------------------------------------------------------------------


def test_no_policy_four_player_death_fails_closed() -> None:
    game = _fresh_four(hp=4)
    assert game.outcome_policy is None
    assert (
        game.execution_snapshot["outcome_policy_identity"]
        == "unregistered_outcome_policy"
    )
    _enter_play(game)
    _strip_rescue_and_dodge_cards(game)
    _give_slash_to_first_player(game)
    game._state = _replace_player(game.state, "p2", hp=1)
    slash_action = _action(game, "use_slash", target="p2")
    assert slash_action is not None
    _step(game, slash_action)
    _step(game, _action(game, "pass_slash_response"))
    assert game.phase is ProductionPhase.DYING_RESCUE
    # 救援顺序：从当前回合角色沿存活环座次递增（4名角色）
    assert game.runtime.rescue_order == ("p1", "p2", "p3", "p4")
    # 前3次放弃救援成功推进；最后一名救援者放弃后触发死亡→胜负判定，
    # 未注册策略必须失败关闭而不是自行猜测模式规则。
    rescue_passes = 0
    with pytest.raises(UnsupportedRuleError, match="胜负策略"):
        while True:
            pass_action = _action(game, "pass_rescue")
            assert pass_action is not None
            game.step(BatchActionIdController(pass_action.action_id))
            rescue_passes += 1
    assert rescue_passes == 3  # 第4名救援者的放弃触发了失败关闭
    # 失败关闭：没有胜利成立、没有胜负事件、状态未提交终局
    assert game.is_finished is False
    assert game.winner_id is None
    assert not any(
        event.event_type in (EventType.VICTORY, EventType.DEATH)
        for event in game.events
    )
    # 直接调用统一胜负出口：同一状态也必须失败关闭
    post_death_topo = PlayerTopology.from_state(
        _replace_player(game.state, "p2", hp=0, alive=False)
    )
    with pytest.raises(UnsupportedRuleError):
        resolve_victory_after_death(
            post_death_topo, "p2", policy=None, explicit_two_player_fallback=True
        )
    # 注册了脚手架策略后同一状态可以正常判定（边界对照）
    assert (
        resolve_victory_after_death(
            post_death_topo,
            "p2",
            policy=_FirstBloodOutcomePolicy(),
            explicit_two_player_fallback=True,
        )
        == "p1"
    )


# ----------------------------------------------------------------------
# 11. 两人局 formal duel 终局行为保持不变
# ----------------------------------------------------------------------


def test_two_player_duel_outcomes_unchanged() -> None:
    # 与 R5 记录对照：seed 0 → p2 胜、388 动作；seed 7 → p2 胜、162 动作、17 回合。
    # 使用 canonical formal duel 会话（同一生产核心 + DuelOutcomePolicy）。
    from scripts.sgs_engine.formal_duel import (
        FormalDuelConfiguration,
        FormalDuelReferenceController,
        FormalNoSkillDuelSession,
    )

    def run_seed(seed: int) -> FormalNoSkillDuelSession:
        configuration = FormalDuelConfiguration.formal_profile()
        game = FormalNoSkillDuelSession(
            seed=seed,
            configuration=configuration,
            analysis_only=False,
            session_id=f"c1-duel-{seed}",
            session_secret=b"c" * 32,
        )
        controller = FormalDuelReferenceController()
        while not game.is_finished:
            game.step(controller)
        return game

    game0 = run_seed(0)
    assert game0.winner_id == "p2"
    assert game0.step_count == 388
    assert game0.outcome_policy is not None
    assert (
        game0.outcome_policy.identity() == "outcome:formal_two_player_duel"
    )
    game7 = run_seed(7)
    assert game7.winner_id == "p2"
    assert game7.step_count == 162
    assert game7.runtime.turn_number == 17


# ----------------------------------------------------------------------
# 12. 四人局伪造/过期多人动作失败关闭
# ----------------------------------------------------------------------


def test_forged_and_stale_multiplayer_actions_fail_closed() -> None:
    game = _fresh_four(hp=4)
    _enter_play(game)
    # 非当前角色伪造结束出牌阶段：失败关闭
    forged_end = LegalAction(
        action_type=ActionType.PASS,
        actor_id="p2",
        payload={"operation": "end_play_phase"},
        action_id="act_forged_4p_end_play",
    )
    with pytest.raises(InvalidActionError):
        validate_action(game.state, game._context(), forged_end, game.registry)
    # p1 持杀、p3 已确认死亡：杀目标枚举只包含存活角色
    slash_id = _give_slash_to_first_player(game)
    game._state = _replace_player(game.state, "p3", hp=0, alive=False)
    slash_targets = {
        action.target_ids[0]
        for action in game.legal_actions()
        if action.payload.get("operation") == "use_slash"
    }
    assert slash_targets
    assert "p3" not in slash_targets
    assert slash_targets.issubset({"p2", "p4"})
    # 伪造对死亡角色的杀：失败关闭
    forged_slash = LegalAction(
        action_type=ActionType.USE_CARD,
        actor_id="p1",
        card_instance_id=slash_id,
        target_ids=("p3",),
        payload={
            "operation": "use_slash",
            "card_key": SHA,
            "card_name": "杀",
        },
        action_id="act_forged_4p_dead_slash",
    )
    with pytest.raises(InvalidActionError):
        validate_action(game.state, game._context(), forged_slash, game.registry)
    # 过期动作：枚举后状态变化（杀移出手牌），旧 action_id 失败关闭
    real_slash = _action(game, "use_slash", target="p2")
    assert real_slash is not None
    game._state = game.state.move_card(real_slash.card_instance_id, DISCARD_PILE)
    with pytest.raises(ProductionBatchError):
        game.step(BatchActionIdController(real_slash.action_id))  # type: ignore[arg-type]
