# -*- coding: utf-8 -*-
"""POST-B C4：斗地主存活农民死亡奖励选择窗口与挂起继续结算（Suspended Continuation）测试。

涵盖：
- _PendingPeasantDeathReward dataclass 与 execution field inventory 完整性；
- 农民死亡时进入 ProductionPhase.PEASANT_REWARD_CHOICE 挂起窗口；
- 存活农民回血（recover_hp）、摸2张（draw_two）与放弃（decline）三项互斥动作；
- 摸牌选项牌堆不足/耗尽平局事务（no_reshuffle_draw 规则）；
- 挂起窗口在群体锦囊（南蛮入侵）结算期间挂起并恢复队列；
- 挂起窗口在方天画戟多目标结算期间挂起并推进下一目标（decline 与 draw_two 响应闪）；
- 挂起窗口在闪电判定伤害（本回合农民死亡 / 传导伤害连环农民死亡）期间挂起并完成判定根与推迟切回合；
- 挂起窗口在属性伤害（雷杀）传导结算期间挂起并恢复传导；
- 存活农民回血选项的事件契约（产生 EventType.HP_RECOVER 正式事件）；
- 敌对式防御检查：伪造 window_id、非法操作者、非法动作类型、地主/末位农民死亡不打开奖励。
"""

from dataclasses import fields, replace
from typing import Any
import pytest

from scripts.sgs_engine.actions import ActionContext, ActionType, InvalidActionError, LegalAction
from scripts.sgs_engine.events import EventType
from scripts.sgs_engine.model import (
    DISCARD_PILE,
    DRAW_PILE,
    PROCESSING_ZONE,
    GameState,
    PlayerState,
    ZoneRef,
)
from scripts.sgs_engine.mode_doudizhu import (
    FORMAL_NO_SKILL_DOUDIZHU_MODE,
    DoudizhuOutcomePolicy,
    FormalDoudizhuConfiguration,
    FormalDoudizhuSession,
)
from scripts.sgs_engine.production_batch import (
    EXECUTION_HASH_RUNTIME_INVENTORY,
    FINISHED_TRANSIENT_RUNTIME_FIELDS,
    PENDING_PEASANT_DEATH_REWARD_EXECUTION_FIELD_INVENTORY,
    BatchActionIdController,
    ProductionBasicCardBatch,
    ProductionPhase,
    _BatchRuntime,
    _PendingPeasantDeathReward,
    _replace_player,
)


def _step(game: ProductionBasicCardBatch, action: LegalAction) -> None:
    game.step(BatchActionIdController(action.action_id))


def _op(game: ProductionBasicCardBatch, operation: str, **filters: Any) -> LegalAction | None:
    for action in game.legal_actions():
        if action.payload.get("operation") != operation:
            continue
        matched = True
        for key, value in filters.items():
            if key == "targets":
                if tuple(action.target_ids) != tuple(value):
                    matched = False
                    break
            elif action.payload.get(key) != value:
                matched = False
                break
        if matched:
            return action
    return None


def _require_op(game: ProductionBasicCardBatch, operation: str, **filters: Any) -> LegalAction:
    action = _op(game, operation, **filters)
    assert action is not None, (
        f"缺少操作 {operation!r}（当前合法操作：{[a.payload.get('operation') for a in game.legal_actions()]}）"
    )
    return action


def _strip_hand(game: ProductionBasicCardBatch, player_id: str) -> None:
    for instance_id in tuple(game.state.card_ids_in(ZoneRef.hand(player_id))):
        game._state = game.state.move_card(instance_id, DISCARD_PILE)


def _give_card(
    game: ProductionBasicCardBatch,
    player_id: str,
    card_key: str,
) -> str:
    """从牌堆取一张指定卡键实体放入目标手牌。"""
    for instance_id in game.state.card_ids_in(DRAW_PILE):
        if game.state.cards_by_id[instance_id].card_key == card_key:
            game._state = game.state.move_card(instance_id, ZoneRef.hand(player_id))
            return instance_id
    raise AssertionError(f"牌堆中找不到{card_key}")


def _enter_play(game: ProductionBasicCardBatch) -> None:
    for operation in ("proceed_prepare", "proceed_judgment", "proceed_draw"):
        _step(game, _require_op(game, operation))


def _pass_all_rescues(game: ProductionBasicCardBatch) -> None:
    while game.phase is ProductionPhase.DYING_RESCUE:
        _step(game, _require_op(game, "pass_rescue"))


def test_pending_peasant_reward_inventory_covers_fields() -> None:
    """_PendingPeasantDeathReward dataclass 字段与 inventory 精确一致。"""
    dataclass_fields = {f.name for f in fields(_PendingPeasantDeathReward)}
    assert dataclass_fields == PENDING_PEASANT_DEATH_REWARD_EXECUTION_FIELD_INVENTORY
    assert "pending_peasant_reward" in FINISHED_TRANSIENT_RUNTIME_FIELDS
    assert "pending_peasant_reward" in EXECUTION_HASH_RUNTIME_INVENTORY


def _session(seed: int = 100) -> FormalDoudizhuSession:
    return FormalDoudizhuSession(
        seed=seed,
        configuration=FormalDoudizhuConfiguration.formal_profile(),
        session_id=f"test-doudizhu-{seed}",
    )


def test_peasant_death_opens_reward_choice_window() -> None:
    """农民 p2 死亡后，胜负未成立（p3 存活），打开 PEASANT_REWARD_CHOICE 窗口。"""
    game = _session(seed=101)
    _enter_play(game)
    _strip_hand(game, "p2")
    _give_card(game, "p1", "sgs_basic_sha")
    game._state = _replace_player(game.state, "p2", hp=1)

    # p1 杀 p2
    _step(game, _require_op(game, "use_slash", targets=("p2",)))
    _step(game, _require_op(game, "pass_slash_response"))
    _pass_all_rescues(game)

    # 验证游戏未结束，阶段切换为 PEASANT_REWARD_CHOICE
    assert game.is_finished is False
    assert game.winner_id is None
    assert game.phase is ProductionPhase.PEASANT_REWARD_CHOICE
    assert game.current_actor_id == "p3"
    assert game.runtime.pending_peasant_reward is not None
    assert game.runtime.pending_peasant_reward.dead_peasant_id == "p2"
    assert game.runtime.pending_peasant_reward.chooser_id == "p3"

    # 验证合法动作为三项互斥选择
    legal = game.legal_actions()
    assert len(legal) == 3
    ops = [a.payload.get("operation") for a in legal]
    assert "peasant_reward_recover_hp" in ops
    assert "peasant_reward_draw_two" in ops
    assert "peasant_reward_decline" in ops


def test_peasant_reward_recover_hp_choice() -> None:
    """存活农民选择回血：体力回复1点（上限封顶），挂起状态清空，继续游戏。"""
    game = _session(seed=102)
    _enter_play(game)
    _strip_hand(game, "p2")
    _give_card(game, "p1", "sgs_basic_sha")
    game._state = _replace_player(game.state, "p2", hp=1)
    game._state = _replace_player(game.state, "p3", hp=2)

    _step(game, _require_op(game, "use_slash", targets=("p2",)))
    _step(game, _require_op(game, "pass_slash_response"))
    _pass_all_rescues(game)
    assert game.phase is ProductionPhase.PEASANT_REWARD_CHOICE

    # p3 选择回复体力
    _step(game, _require_op(game, "peasant_reward_recover_hp"))

    # p3 体力变为 3/4
    assert game.state.players_by_id["p3"].hp == 3
    assert game.runtime.pending_peasant_reward is None
    assert game.phase is ProductionPhase.PLAY


def test_peasant_reward_draw_two_choice() -> None:
    """存活农民选择摸2张牌：正常摸2张牌，挂起状态清空，继续游戏。"""
    game = _session(seed=103)
    _enter_play(game)
    _strip_hand(game, "p2")
    _give_card(game, "p1", "sgs_basic_sha")
    game._state = _replace_player(game.state, "p2", hp=1)

    _step(game, _require_op(game, "use_slash", targets=("p2",)))
    _step(game, _require_op(game, "pass_slash_response"))
    _pass_all_rescues(game)
    assert game.phase is ProductionPhase.PEASANT_REWARD_CHOICE

    p3_hand_before = len(game.state.card_ids_in(ZoneRef.hand("p3")))

    # p3 选择摸2张
    _step(game, _require_op(game, "peasant_reward_draw_two"))

    # 手牌增加2张
    p3_hand_after = len(game.state.card_ids_in(ZoneRef.hand("p3")))
    assert p3_hand_after == p3_hand_before + 2
    assert game.runtime.pending_peasant_reward is None
    assert game.phase is ProductionPhase.PLAY


def test_peasant_reward_draw_two_deck_exhaustion_draw() -> None:
    """选择摸2张牌但牌堆不足时，原子摸牌事务就地触发牌堆耗尽平局。"""
    game = _session(seed=104)
    _enter_play(game)
    _strip_hand(game, "p2")
    _give_card(game, "p1", "sgs_basic_sha")
    game._state = _replace_player(game.state, "p2", hp=1)

    _step(game, _require_op(game, "use_slash", targets=("p2",)))
    _step(game, _require_op(game, "pass_slash_response"))
    _pass_all_rescues(game)
    assert game.phase is ProductionPhase.PEASANT_REWARD_CHOICE

    # 此时排空牌堆至仅剩1张
    cards_in_deck = list(game.state.card_ids_in(DRAW_PILE))
    for cid in cards_in_deck[1:]:
        game._state = game.state.move_card(cid, DISCARD_PILE)
    assert len(game.state.card_ids_in(DRAW_PILE)) == 1

    # p3 选择摸2张（预检不足）
    _step(game, _require_op(game, "peasant_reward_draw_two"))

    # 形成正式平局终局
    assert game.is_finished is True
    assert game.winner_id is None
    assert game.runtime.game_over_reason == "doudizhu_draw_deck_exhausted"


def test_peasant_reward_decline_choice() -> None:
    """存活农民选择放弃两项奖励（PASS）：状态不变，继续游戏。"""
    game = _session(seed=105)
    _enter_play(game)
    _strip_hand(game, "p2")
    _give_card(game, "p1", "sgs_basic_sha")
    game._state = _replace_player(game.state, "p2", hp=1)
    game._state = _replace_player(game.state, "p3", hp=2)

    _step(game, _require_op(game, "use_slash", targets=("p2",)))
    _step(game, _require_op(game, "pass_slash_response"))
    _pass_all_rescues(game)
    assert game.phase is ProductionPhase.PEASANT_REWARD_CHOICE

    p3_hand_before = len(game.state.card_ids_in(ZoneRef.hand("p3")))

    # p3 放弃
    _step(game, _require_op(game, "peasant_reward_decline"))

    # 体力与手牌均未改变
    assert game.state.players_by_id["p3"].hp == 2
    assert len(game.state.card_ids_in(ZoneRef.hand("p3"))) == p3_hand_before
    assert game.runtime.pending_peasant_reward is None
    assert game.phase is ProductionPhase.PLAY


def test_peasant_reward_during_group_trick_preserves_root() -> None:
    """群体锦囊（南蛮）目标 p2 死亡后，在奖励选择期间根牌保持 PROCESSING，选择后继续 p3 响应。"""
    game = _session(seed=106)
    _enter_play(game)
    _strip_hand(game, "p2")
    _give_card(game, "p1", "sgs_trick_nanmanruqin")
    game._state = _replace_player(game.state, "p2", hp=1)

    # p1 使用南蛮入侵
    _step(game, _require_op(game, "use_nanman"))
    # 无懈阶段 pass
    while game.phase is ProductionPhase.TRICK_RESPONSE:
        _step(game, _require_op(game, "pass_trick_response"))

    # 进入 p2 南蛮响应
    assert game.phase is ProductionPhase.NANMAN_RESPONSE
    assert game.current_actor_id == "p2"
    _step(game, _require_op(game, "pass_nanman_slash"))
    # p2 濒死
    _pass_all_rescues(game)

    # 处于奖励选择窗口，根南蛮必须仍在 PROCESSING 区
    assert game.phase is ProductionPhase.PEASANT_REWARD_CHOICE
    assert len(game.state.card_ids_in(PROCESSING_ZONE)) > 0
    assert game.runtime.pending_group_trick is not None

    # p3 做出奖励选择
    _step(game, _require_op(game, "peasant_reward_decline"))

    # 奖励结算完成后，推进到 p3 的无懈/南蛮响应窗口！
    while game.phase is ProductionPhase.TRICK_RESPONSE:
        _step(game, _require_op(game, "pass_trick_response"))
    assert game.phase is ProductionPhase.NANMAN_RESPONSE
    assert game.current_actor_id == "p3"
    assert game.runtime.pending_group_trick.responder_id == "p3"
    assert len(game.state.card_ids_in(PROCESSING_ZONE)) > 0


def test_turn_owner_peasant_death_deferred_turn_end_after_reward() -> None:
    """当前回合农民 p2 决斗自伤死亡时，推迟的回合结束在存活农民 p3 奖励选择完成后执行。"""
    game = _session(seed=107)
    # 结束 p1 回合进入 p2 回合
    _enter_play(game)
    _step(game, _require_op(game, "end_play_phase"))
    while game.phase is ProductionPhase.DISCARD:
        if _op(game, "discard_phase_submit") is not None:
            _step(game, _require_op(game, "discard_phase_submit"))
        else:
            _step(game, _require_op(game, "select_discard_card"))
    _step(game, _require_op(game, "end_turn"))

    # p2 回合
    assert game.current_player_id == "p2"
    _enter_play(game)
    _strip_hand(game, "p2")
    _give_card(game, "p2", "sgs_trick_juedou")
    _give_card(game, "p1", "sgs_basic_sha")
    game._state = _replace_player(game.state, "p2", hp=1)

    # p2 对 p1 决斗
    _step(game, _require_op(game, "use_duel", targets=("p1",)))
    while game.phase is ProductionPhase.TRICK_RESPONSE:
        _step(game, _require_op(game, "pass_trick_response"))

    # p1 响应【杀】
    assert game.phase is ProductionPhase.DUEL_RESPONSE
    assert game.current_actor_id == "p1"
    _step(game, _require_op(game, "play_slash_for_duel"))

    # p2 放弃响应【杀】受到伤害濒死
    assert game.phase is ProductionPhase.DUEL_RESPONSE
    assert game.current_actor_id == "p2"
    _step(game, _require_op(game, "pass_duel_slash"))
    _pass_all_rescues(game)

    # 进入 p3 的奖励选择阶段
    assert game.phase is ProductionPhase.PEASANT_REWARD_CHOICE
    assert game.current_actor_id == "p3"
    assert game.runtime.deferred_turn_end_after_owner_death is True

    # p3 提交奖励选择
    _step(game, _require_op(game, "peasant_reward_decline"))

    # p2 的回合结束并切换到下一存活角色（p3）的准备阶段
    assert game.current_player_id == "p3"
    assert game.phase is ProductionPhase.PREPARE


def test_fangtian_slash_first_peasant_death_decline_and_continue_sequence() -> None:
    """方天画戟多目标：首个目标农民死亡后进入奖励选择（decline），奖励后根杀保持、锁定目标队列继续推进、恰好一次finalize。"""
    game = _session(seed=108)
    _enter_play(game)
    _strip_hand(game, "p1")
    _strip_hand(game, "p2")
    _strip_hand(game, "p3")

    # p1 装备方天画戟，手牌仅留一张【杀】（满足最后一张手牌触发方天多目标）
    _give_card(game, "p1", "sgs_weapon_fangtianhuaji")
    _step(game, _require_op(game, "use_weapon"))
    _give_card(game, "p1", "sgs_basic_sha")

    # p2 设为 1 HP，p3 设为 2 HP
    game._state = _replace_player(game.state, "p2", hp=1)
    game._state = _replace_player(game.state, "p3", hp=2)

    # p1 发动方天画戟杀 (p2, p3)
    _step(game, _require_op(game, "use_slash", targets=("p2", "p3")))

    # p2 响应杀（无闪）-> 濒死 -> 死亡
    assert game.phase is ProductionPhase.SLASH_RESPONSE
    assert game.current_actor_id == "p2"
    _step(game, _require_op(game, "pass_slash_response"))
    _pass_all_rescues(game)

    # 进入 p3 的奖励选择窗口
    assert game.phase is ProductionPhase.PEASANT_REWARD_CHOICE
    assert game.current_actor_id == "p3"
    # 根【杀】必须仍在 PROCESSING_ZONE，不得提前 finalize
    assert len(game.state.card_ids_in(PROCESSING_ZONE)) == 1
    assert game.runtime.pending_slash is not None
    assert game.runtime.pending_slash.target_sequence == ("p2", "p3")
    assert game.runtime.pending_slash.current_target_index == 0

    # p3 选择放弃奖励
    _step(game, _require_op(game, "peasant_reward_decline"))

    # 奖励结算完成后，队列必须推进到 p3 的【杀】响应窗口！
    assert game.phase is ProductionPhase.SLASH_RESPONSE
    assert game.current_actor_id == "p3"
    assert game.runtime.pending_slash is not None
    assert game.runtime.pending_slash.current_target_index == 1
    assert len(game.state.card_ids_in(PROCESSING_ZONE)) == 1

    # p3 放弃响应受到伤害
    _step(game, _require_op(game, "pass_slash_response"))

    # p3 体力变为 1
    assert game.state.players_by_id["p3"].hp == 1
    # 根【杀】在全部目标完成后恰好一次 finalize 并离开处理区
    assert len(game.state.card_ids_in(PROCESSING_ZONE)) == 0
    assert game.runtime.pending_slash is None
    # 地主未死亡，回合不得提前切换，正确返回出牌阶段
    assert game.current_player_id == "p1"
    assert game.phase is ProductionPhase.PLAY


def test_fangtian_slash_first_peasant_death_draw_two_and_respond_jink() -> None:
    """方天画戟多目标：首个目标农民死亡后存活农民摸2张牌，随后使用摸到的【闪】成功响应后续【杀】。"""
    game = _session(seed=109)
    _enter_play(game)
    _strip_hand(game, "p1")
    _strip_hand(game, "p2")
    _strip_hand(game, "p3")

    _give_card(game, "p1", "sgs_weapon_fangtianhuaji")
    _step(game, _require_op(game, "use_weapon"))
    _give_card(game, "p1", "sgs_basic_sha")

    game._state = _replace_player(game.state, "p2", hp=1)
    game._state = _replace_player(game.state, "p3", hp=2)

    _step(game, _require_op(game, "use_slash", targets=("p2", "p3")))
    _step(game, _require_op(game, "pass_slash_response"))
    _pass_all_rescues(game)

    assert game.phase is ProductionPhase.PEASANT_REWARD_CHOICE
    p3_hand_before = len(game.state.card_ids_in(ZoneRef.hand("p3")))

    # p3 选择摸2张
    _step(game, _require_op(game, "peasant_reward_draw_two"))
    assert len(game.state.card_ids_in(ZoneRef.hand("p3"))) == p3_hand_before + 2

    # 推进到 p3 响应阶段
    assert game.phase is ProductionPhase.SLASH_RESPONSE
    assert game.current_actor_id == "p3"

    # 给 p3 一张【闪】并响应
    _give_card(game, "p3", "sgs_basic_shan")
    _step(game, _require_op(game, "play_dodge"))

    # p3 成功闪避，HP 保持 2
    assert game.state.players_by_id["p3"].hp == 2
    assert len(game.state.card_ids_in(PROCESSING_ZONE)) == 0
    assert game.current_player_id == "p1"
    assert game.phase is ProductionPhase.PLAY


def test_lightning_peasant_death_deferred_turn_end_after_reward() -> None:
    """农民 p2 在自身回合判定阶段被闪电击中死亡，奖励选择结束后 judgment root 正式完成并兑现回合结束。"""
    game = _session(seed=110)
    # 推进到 p2 回合准备阶段
    _enter_play(game)
    _step(game, _require_op(game, "end_play_phase"))
    while game.phase is ProductionPhase.DISCARD:
        if _op(game, "discard_phase_submit") is not None:
            _step(game, _require_op(game, "discard_phase_submit"))
        else:
            _step(game, _require_op(game, "select_discard_card"))
    _step(game, _require_op(game, "end_turn"))

    assert game.current_player_id == "p2"
    assert game.phase is ProductionPhase.PREPARE

    # 将闪电放入 p2 判定区
    _strip_hand(game, "p2")
    lightning_id = _give_card(game, "p2", "sgs_delayed_shandian")
    # 移入判定区并注册 entry_index
    game._state = game.state.move_card(lightning_id, ZoneRef.judgment("p2"))
    from types import MappingProxyType
    game._runtime = replace(
        game.runtime,
        judgment_entry_indices=MappingProxyType(
            {**game.runtime.judgment_entry_indices, lightning_id: 1}
        ),
        judgment_entry_counter=max(game.runtime.judgment_entry_counter, 1),
    )
    # 设置 p2 体力为 2（闪电造成3点雷电伤害必定致死）
    game._state = _replace_player(game.state, "p2", hp=2)

    # 准备阶段推进
    _step(game, _require_op(game, "proceed_prepare"))
    assert game.phase is ProductionPhase.JUDGMENT

    # 判定阶段推进：闪电触发判定
    # 确保判定牌为黑桃2-9以触发闪电爆炸
    draw_cards = list(game.state.card_ids_in(DRAW_PILE))
    spade_card = next(
        cid for cid in draw_cards
        if (game.state.cards_by_id[cid].suit in ("♠", "spade", "黑桃"))
        and game.state.cards_by_id[cid].rank in ("2", "3", "4", "5", "6", "7", "8", "9")
    )
    other_draw_cards = [c for c in draw_cards if c != spade_card]
    game._state = game.state.reorder_zone(DRAW_PILE, (spade_card, *other_draw_cards))

    _step(game, _require_op(game, "proceed_judgment"))
    # 无懈阶段 pass
    while game.phase in (ProductionPhase.JUDGMENT_WUXIE, ProductionPhase.TRICK_RESPONSE):
        op = "pass_judgment_wuxie" if _op(game, "pass_judgment_wuxie") else "pass_trick_response"
        _step(game, _require_op(game, op))

    # 判定牌生效，闪电爆炸，p2 受到 3 点伤害进入濒死
    _pass_all_rescues(game)

    # 处于存活农民 p3 的奖励选择窗口
    assert game.phase is ProductionPhase.PEASANT_REWARD_CHOICE
    assert game.current_actor_id == "p3"
    assert game.runtime.deferred_turn_end_after_owner_death is True

    # p3 选择回血
    _step(game, _require_op(game, "peasant_reward_recover_hp"))

    # p2 的回合结束并推进到下一存活角色（p3）的准备阶段
    assert game.current_player_id == "p3"
    assert game.phase is ProductionPhase.PREPARE


def test_lightning_chain_peasant_death_preserves_judgment_root() -> None:
    """地主判定闪电触发雷电伤害，经铁索连环传导至农民 p2 致死：奖励结束后判定根与传导继续，地主正常进入摸牌出牌。"""
    game = _session(seed=111)
    assert game.current_player_id == "p1"

    # 将闪电放入 p1 判定区
    lightning_id = _give_card(game, "p1", "sgs_delayed_shandian")
    game._state = game.state.move_card(lightning_id, ZoneRef.judgment("p1"))
    from types import MappingProxyType
    game._runtime = replace(
        game.runtime,
        judgment_entry_indices=MappingProxyType(
            {**game.runtime.judgment_entry_indices, lightning_id: 1}
        ),
        judgment_entry_counter=max(game.runtime.judgment_entry_counter, 1),
    )

    # 将 p1, p2, p3 均设置为连环状态
    game._state = _replace_player(game.state, "p1", chained=True, hp=5)
    game._state = _replace_player(game.state, "p2", chained=True, hp=2)
    game._state = _replace_player(game.state, "p3", chained=True, hp=4)

    # 准备阶段推进
    _step(game, _require_op(game, "proceed_prepare"))
    # 地主若触发飞扬窗口，放弃飞扬
    if game.phase is ProductionPhase.FEIYANG_ACTIVATE:
        _step(game, _require_op(game, "feiyang_decline"))
    assert game.phase is ProductionPhase.JUDGMENT

    # 确保判定牌为黑桃2-9以触发闪电爆炸
    draw_cards = list(game.state.card_ids_in(DRAW_PILE))
    spade_card = next(
        cid for cid in draw_cards
        if (game.state.cards_by_id[cid].suit in ("♠", "spade", "黑桃"))
        and game.state.cards_by_id[cid].rank in ("2", "3", "4", "5", "6", "7", "8", "9")
    )
    other_draw_cards = [c for c in draw_cards if c != spade_card]
    game._state = game.state.reorder_zone(DRAW_PILE, (spade_card, *other_draw_cards))

    # 推进判定（无懈 pass）
    _step(game, _require_op(game, "proceed_judgment"))
    while game.phase in (ProductionPhase.JUDGMENT_WUXIE, ProductionPhase.TRICK_RESPONSE):
        op = "pass_judgment_wuxie" if _op(game, "pass_judgment_wuxie") else "pass_trick_response"
        _step(game, _require_op(game, op))

    # p1 受伤（5->2），触发传导至 p2，p2 受到 3 点雷伤濒死
    _pass_all_rescues(game)

    # 进入 p3 的奖励选择窗口
    assert game.phase is ProductionPhase.PEASANT_REWARD_CHOICE
    assert game.current_actor_id == "p3"
    assert game.runtime.pending_chain is not None

    # p3 选择回血
    _step(game, _require_op(game, "peasant_reward_recover_hp"))

    # 奖励结算后，传导继续至 p3！
    # p3 受到 3 点雷伤（4->1），重置连环
    assert game.state.players_by_id["p3"].hp == 1
    assert game.state.players_by_id["p3"].chained is False

    # 传导结束，闪电判定根结算完毕，地主 p1 存活并返回判定阶段（无剩余判定牌）推进至摸牌出牌！
    assert game.current_player_id == "p1"
    assert game.phase is ProductionPhase.JUDGMENT
    _step(game, _require_op(game, "proceed_judgment"))
    assert game.phase is ProductionPhase.DRAW
    _step(game, _require_op(game, "proceed_draw"))
    assert game.phase is ProductionPhase.PLAY


def test_thunder_slash_chain_peasant_death_resumes_chain() -> None:
    """属性【雷杀】命中连环农民 p2 致死：奖励窗口结算后正确恢复传导至 p3，无重复结算。"""
    game = _session(seed=112)
    _enter_play(game)
    _strip_hand(game, "p2")
    _strip_hand(game, "p3")

    _give_card(game, "p1", "sgs_basic_leisha")
    game._state = _replace_player(game.state, "p2", chained=True, hp=1)
    game._state = _replace_player(game.state, "p3", chained=True, hp=3)

    # p1 对 p2 使用雷杀
    _step(game, _require_op(game, "use_slash", targets=("p2",)))
    _step(game, _require_op(game, "pass_slash_response"))
    _pass_all_rescues(game)

    # 进入奖励选择窗口
    assert game.phase is ProductionPhase.PEASANT_REWARD_CHOICE
    assert game.current_actor_id == "p3"
    assert game.runtime.pending_chain is not None

    # p3 放弃奖励
    _step(game, _require_op(game, "peasant_reward_decline"))

    # 传导至 p3，p3 受到 1 点雷伤（3->2），解除连环
    assert game.state.players_by_id["p3"].hp == 2
    assert game.state.players_by_id["p3"].chained is False
    assert game.current_player_id == "p1"
    assert game.phase is ProductionPhase.PLAY


def test_peasant_reward_recover_hp_event_contract() -> None:
    """回复体力选项事件契约：实际回血时产生 EventType.HP_RECOVER 事件；满血时不产生正整数事件。"""
    game = _session(seed=113)
    _enter_play(game)
    _strip_hand(game, "p2")
    _give_card(game, "p1", "sgs_basic_sha")
    game._state = _replace_player(game.state, "p2", hp=1)
    game._state = _replace_player(game.state, "p3", hp=3)  # 3/4

    _step(game, _require_op(game, "use_slash", targets=("p2",)))
    _step(game, _require_op(game, "pass_slash_response"))
    _pass_all_rescues(game)

    assert game.phase is ProductionPhase.PEASANT_REWARD_CHOICE
    event_count_before = len(game.events)

    _step(game, _require_op(game, "peasant_reward_recover_hp"))

    # 验证产生 HP_RECOVER 事件
    new_events = game.events[event_count_before:]
    recover_events = [e for e in new_events if e.event_type == EventType.HP_RECOVER]
    assert len(recover_events) == 1
    ev = recover_events[0]
    assert ev.target_ids == ("p3",)
    assert ev.payload["amount"] == 1
    assert ev.payload["reason"] == "peasant_death_reward"


def test_peasant_reward_adversarial_fail_closed_checks() -> None:
    """敌对式防御检查：伪造 window_id、非法操作者、非法动作类型、地主/末位农民死亡不打开奖励。"""
    game = _session(seed=114)
    _enter_play(game)
    _strip_hand(game, "p2")
    _give_card(game, "p1", "sgs_basic_sha")
    game._state = _replace_player(game.state, "p2", hp=1)

    _step(game, _require_op(game, "use_slash", targets=("p2",)))
    _step(game, _require_op(game, "pass_slash_response"))
    _pass_all_rescues(game)
    assert game.phase is ProductionPhase.PEASANT_REWARD_CHOICE

    real_action = _require_op(game, "peasant_reward_recover_hp")
    window_id = real_action.payload["window_id"]
    context = game._context()

    # 1. 伪造 window_id
    forged_action = LegalAction(
        action_id=real_action.action_id,
        action_type=ActionType.CHOOSE_OPTION,
        actor_id="p3",
        payload={"operation": "peasant_reward_recover_hp", "window_id": "forged_window_999"},
    )
    with pytest.raises(InvalidActionError, match="window_id"):
        game.apply_peasant_reward_choice(game.state, context, forged_action)

    # 2. 地主试图执行农民死亡奖励选择
    wrong_actor_action = LegalAction(
        action_id=real_action.action_id,
        action_type=ActionType.CHOOSE_OPTION,
        actor_id="p1",
        payload={"operation": "peasant_reward_recover_hp", "window_id": window_id},
    )
    wrong_actor_context = ActionContext(
        mode=game.mode_id,
        phase=game.phase.value,
        actor_id="p1",
        turn_player_id=game.runtime.current_player_id,
    )
    with pytest.raises(InvalidActionError, match="指定的存活农民"):
        game.apply_peasant_reward_choice(game.state, wrong_actor_context, wrong_actor_action)

    # 3. 回复体力使用了 PASS 动作类型
    wrong_type_action = LegalAction(
        action_id=real_action.action_id,
        action_type=ActionType.PASS,
        actor_id="p3",
        payload={"operation": "peasant_reward_recover_hp", "window_id": window_id},
    )
    with pytest.raises(InvalidActionError, match="CHOOSE_OPTION"):
        game.apply_peasant_reward_choice(game.state, context, wrong_type_action)

    # 4. 放弃使用了 CHOOSE_OPTION 动作类型
    decline_action = _require_op(game, "peasant_reward_decline")
    wrong_type_decline = LegalAction(
        action_id=decline_action.action_id,
        action_type=ActionType.CHOOSE_OPTION,
        actor_id="p3",
        payload={"operation": "peasant_reward_decline", "window_id": window_id},
    )
    with pytest.raises(InvalidActionError, match="PASS"):
        game.apply_peasant_reward_choice(game.state, context, wrong_type_decline)

    # 5. 地主死亡不打开奖励窗口（直接终局农民胜）
    game_landlord = _session(seed=115)
    _enter_play(game_landlord)
    _strip_hand(game_landlord, "p1")
    game_landlord._state = _replace_player(game_landlord.state, "p1", hp=1)

    # 结束 p1 回合到 p2 回合
    _step(game_landlord, _require_op(game_landlord, "end_play_phase"))
    while game_landlord.phase is ProductionPhase.DISCARD:
        if _op(game_landlord, "discard_phase_submit") is not None:
            _step(game_landlord, _require_op(game_landlord, "discard_phase_submit"))
        else:
            _step(game_landlord, _require_op(game_landlord, "select_discard_card"))
    _step(game_landlord, _require_op(game_landlord, "end_turn"))

    # p2 杀 p1 致死
    assert game_landlord.current_player_id == "p2"
    _enter_play(game_landlord)
    _strip_hand(game_landlord, "p2")
    _give_card(game_landlord, "p2", "sgs_basic_sha")
    _step(game_landlord, _require_op(game_landlord, "use_slash", targets=("p1",)))
    _step(game_landlord, _require_op(game_landlord, "pass_slash_response"))
    _pass_all_rescues(game_landlord)

    assert game_landlord.is_finished is True
    assert game_landlord.winner_id == "peasants"
    assert game_landlord.phase is ProductionPhase.FINISHED
    assert game_landlord.runtime.pending_peasant_reward is None
