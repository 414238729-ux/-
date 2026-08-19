# -*- coding: utf-8 -*-
"""POST-B C123 全局 remediation 1：C123-GLOBAL-001 回归与相邻场景测试。

Finding 编号：C123-GLOBAL-001
Severity：BLOCKER
名称：MULTITARGET_SLASH_ROOT_PREMATURE_FINISH_AFTER_RESCUED_CHAIN_TARGET

核心问题：
方天画戟多目标【火杀】第一目标受到火焰伤害触发铁索传导，第一目标进入 DYING
并被桃救回后，_resume_chain_after_rescue 错误地提前 _finish_processing 根【火杀】，
导致实体牌提前离开 PROCESSING_ZONE。外层 Fangtian Slash root 继续推进剩余目标时，
第二次尝试 finish 同一实体根牌，抛出 ProductionBatchError("只有处理区中的实体牌可以完成结算")。

所有测试走真实 Formal2v2Session / ProductionBasicCardBatch 生产路径。
"""

from __future__ import annotations

from typing import Any

import pytest

from scripts.sgs_engine.actions import (
    LegalAction,
    UnsupportedRuleError,
)
from scripts.sgs_engine.events import EventType
from scripts.sgs_engine.mode_2v2 import (
    Formal2v2Configuration,
    Formal2v2Session,
)
from scripts.sgs_engine.model import (
    DISCARD_PILE,
    DRAW_PILE,
    PROCESSING_ZONE,
    ZoneRef,
)
from scripts.sgs_engine.production_batch import (
    BatchActionIdController,
    ProductionBasicCardBatch,
    ProductionPhase,
    _replace_player,
)


HUOSHA = "sgs_basic_huosha"
LEISHA = "sgs_basic_leisha"
PUTONG_SHA = "sgs_basic_sha"
TAO = "sgs_basic_tao"
SHAN = "sgs_basic_shan"
JIU = "sgs_basic_jiu"
FANGTIAN = "sgs_weapon_fangtianhuaji"
ZHANGBA = "sgs_weapon_zhangbashemao"
ZHUQUE = "sgs_weapon_zhuqueyushan"
SHANDIAN = "sgs_delayed_shandian"
SPADE_7_SHA = "sgs-mobile-20260725-140"
RESCUE_OR_DODGE_KEYS = frozenset({TAO, SHAN, JIU})


def _session(*, seed: int = 2) -> Formal2v2Session:
    return Formal2v2Session(
        seed=seed,
        configuration=Formal2v2Configuration.formal_profile(),
        analysis_only=False,
    )


def _op(
    game: ProductionBasicCardBatch, operation: str, **filters: Any
) -> LegalAction | None:
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


def _require_op(
    game: ProductionBasicCardBatch, operation: str, **filters: Any
) -> LegalAction:
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


def _strip_rescue_and_dodge(game: ProductionBasicCardBatch) -> None:
    for player in game.state.players:
        for instance_id in tuple(
            game.state.card_ids_in(ZoneRef.hand(player.player_id))
        ):
            if game.state.cards_by_id[instance_id].card_key in RESCUE_OR_DODGE_KEYS:
                game._state = game.state.move_card(instance_id, DISCARD_PILE)


def _give_card(
    game: ProductionBasicCardBatch,
    player_id: str,
    card_key: str,
) -> str:
    for zone in (DRAW_PILE, DISCARD_PILE):
        for instance_id in game.state.card_ids_in(zone):
            if game.state.cards_by_id[instance_id].card_key == card_key:
                game._state = game.state.move_card(
                    instance_id, ZoneRef.hand(player_id)
                )
                return instance_id
    raise AssertionError(f"找不到{card_key}")


def _equip_weapon(
    game: ProductionBasicCardBatch, player_id: str, card_key: str
) -> str:
    for instance_id, card in game.state.cards_by_id.items():
        if card.card_key == card_key:
            game._state = game.state.move_card(
                instance_id, ZoneRef.equipment(player_id, "weapon")
            )
            return instance_id
    raise AssertionError(f"找不到武器{card_key}")


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


def _pass_rescues_for(game: ProductionBasicCardBatch, dying_id: str) -> None:
    while (
        game.phase is ProductionPhase.DYING_RESCUE
        and game.runtime.pending_dying_id == dying_id
    ):
        _step(game, _require_op(game, "pass_rescue"))


def _chain_all(game: ProductionBasicCardBatch) -> None:
    for player_id in game.player_ids:
        game._state = _replace_player(game.state, player_id, chained=True)


def _set_hp(game: ProductionBasicCardBatch, player_id: str, hp: int) -> None:
    game._state = _replace_player(game.state, player_id, hp=hp)


def _drain_deck_to(game: ProductionBasicCardBatch, count: int) -> None:
    ids = list(game.state.card_ids_in(DRAW_PILE))
    assert len(ids) >= count
    game._state = game.state.move_cards(
        {instance_id: DISCARD_PILE for instance_id in ids[count:]}
    )


def _reasons(game: ProductionBasicCardBatch) -> list[object]:
    return [event.payload.get("reason") for event in game.events]


def _slash_discard_moves(
    game: ProductionBasicCardBatch, slash_id: str
) -> list[object]:
    return [
        event
        for event in game.events
        if event.event_type is EventType.CARD_MOVED
        and event.card_instance_id == slash_id
        and event.payload.get("destination", {}).get("kind") == "discard_pile"
    ]


# ----------------------------------------------------------------------
# A. C123-GLOBAL-001 主 finding：
#    方天火杀多目标 + 第一目标连环濒死被救 + 传导继续 + 剩余目标继续
# ----------------------------------------------------------------------


def test_c123_global_001_fangtian_huosha_first_target_rescued_chain_continues() -> None:
    """4 人 2v2：p1 装备方天画戟，最后一张手牌使用【火杀】指定 p2, p3, p4。

    全员横置，p2 HP=1。
    1. p1 使用方天火杀：targets = (p2, p3, p4)。
    2. p2 不出闪，受到 1 点火焰伤害，建立 chain，进入 DYING_RESCUE。
    3. p1 放弃救援，p2 使用【桃】自救恢复至 1 HP。
    4. 传导继续处理 p3, p4（p3/p4 各受 1 点传导火焰伤害）。
    5. chain 结束后回到方天火杀根结算，推进剩余目标 p3、p4。
    6. p3, p4 依次不出闪受害，最终根【火杀】恰好 finalize 一次。
    """

    game = _session()
    _enter_play(game)
    _strip_rescue_and_dodge(game)
    _equip_weapon(game, "p1", FANGTIAN)
    _strip_hand(game, "p1")
    slash_id = _give_card(game, "p1", HUOSHA)
    _chain_all(game)
    _set_hp(game, "p1", 4)
    _set_hp(game, "p2", 1)
    _set_hp(game, "p3", 4)
    _set_hp(game, "p4", 4)
    _give_card(game, "p2", TAO)

    # 1. p1 使用方天火杀
    _step(game, _require_op(game, "use_slash", card_key=HUOSHA, targets=("p2", "p3", "p4")))
    assert game.runtime.pending_slash is not None
    assert game.runtime.pending_slash.target_sequence == ("p2", "p3", "p4")
    assert game.runtime.pending_slash.current_target_index == 0
    assert game.state.location_of(slash_id) == PROCESSING_ZONE

    # 2. p2 不出闪，受到火焰伤害，进入濒死
    _step(game, _require_op(game, "pass_slash_response"))
    assert game.phase is ProductionPhase.DYING_RESCUE
    assert game.runtime.pending_dying_id == "p2"
    assert game.runtime.pending_chain is not None

    # 3. p1 放弃救援，轮到 p2 出桃自救
    _step(game, _require_op(game, "pass_rescue"))
    _step(game, _require_op(game, "rescue_with_peach", card_key=TAO, targets=("p2",)))
    assert game.state.players_by_id["p2"].hp == 1
    assert game.state.players_by_id["p2"].alive is True

    # 核心不变量：此时根【火杀】必须仍位于 PROCESSING_ZONE
    assert game.state.location_of(slash_id) == PROCESSING_ZONE

    # 4. 传导伤害已触发（p3, p4 横置解除并受到 1 点传导火焰伤害）
    assert game.state.players_by_id["p3"].hp == 3
    assert game.state.players_by_id["p4"].hp == 3
    assert game.runtime.pending_chain is None

    # 5. 回到方天根结算，推进到第 2 目标 p3
    assert game.phase is ProductionPhase.SLASH_RESPONSE
    assert game.runtime.pending_slash is not None
    assert game.runtime.pending_slash.target_id == "p3"
    assert game.runtime.pending_slash.current_target_index == 1
    assert game.state.location_of(slash_id) == PROCESSING_ZONE

    # p3 不出闪，受到 1 点火杀伤害（HP: 3 -> 2）
    _step(game, _require_op(game, "pass_slash_response"))
    assert game.state.players_by_id["p3"].hp == 2

    # 推进到第 3 目标 p4
    assert game.phase is ProductionPhase.SLASH_RESPONSE
    assert game.runtime.pending_slash is not None
    assert game.runtime.pending_slash.target_id == "p4"
    assert game.runtime.pending_slash.current_target_index == 2
    assert game.state.location_of(slash_id) == PROCESSING_ZONE

    # p4 不出闪，受到 1 点火杀伤害（HP: 3 -> 2）
    _step(game, _require_op(game, "pass_slash_response"))
    assert game.state.players_by_id["p4"].hp == 2

    # 6. 全部目标结算完成，根【火杀】恰好 finalize 一次
    assert game.runtime.pending_slash is None
    assert game.state.location_of(slash_id) == DISCARD_PILE
    assert not game.state.card_ids_in(PROCESSING_ZONE)
    assert len(_slash_discard_moves(game, slash_id)) == 1
    game.assert_resolution_invariants()
    assert game.phase is ProductionPhase.PLAY


# ----------------------------------------------------------------------
# B. 第一目标死亡（非终局）：
#    方天火杀多目标 + 第一目标死亡 + 传导继续 + 剩余目标继续
# ----------------------------------------------------------------------


def test_c123_global_001_fangtian_huosha_first_target_dies_nonterminal_chain_and_targets_continue() -> None:
    """p2 无救援死亡（非终局）：传导继续处理 p3/p4，随后方天剩余目标继续推进。"""

    game = _session()
    _enter_play(game)
    _strip_rescue_and_dodge(game)
    _equip_weapon(game, "p1", FANGTIAN)
    _strip_hand(game, "p1")
    slash_id = _give_card(game, "p1", HUOSHA)
    _chain_all(game)
    _set_hp(game, "p1", 4)
    _set_hp(game, "p2", 1)
    _set_hp(game, "p3", 4)
    _set_hp(game, "p4", 4)

    _step(game, _require_op(game, "use_slash", card_key=HUOSHA, targets=("p2", "p3", "p4")))
    _step(game, _require_op(game, "pass_slash_response"))
    assert game.phase is ProductionPhase.DYING_RESCUE
    assert game.runtime.pending_dying_id == "p2"

    _pass_all_rescues(game)
    assert game.state.players_by_id["p2"].alive is False
    assert game.is_finished is False

    # 传导已处理：p3, p4 各受 1 点传导火焰伤害（HP: 4 -> 3）
    assert game.state.players_by_id["p3"].hp == 3
    assert game.state.players_by_id["p4"].hp == 3

    # 方天根推进到 p3
    assert game.phase is ProductionPhase.SLASH_RESPONSE
    assert game.runtime.pending_slash is not None
    assert game.runtime.pending_slash.target_id == "p3"
    assert game.runtime.pending_slash.current_target_index == 1
    assert game.state.location_of(slash_id) == PROCESSING_ZONE

    _step(game, _require_op(game, "pass_slash_response"))
    assert game.state.players_by_id["p3"].hp == 2

    # 方天根推进到 p4
    assert game.phase is ProductionPhase.SLASH_RESPONSE
    assert game.runtime.pending_slash is not None
    assert game.runtime.pending_slash.target_id == "p4"
    assert game.runtime.pending_slash.current_target_index == 2
    assert game.state.location_of(slash_id) == PROCESSING_ZONE

    _step(game, _require_op(game, "pass_slash_response"))
    assert game.state.players_by_id["p4"].hp == 2

    assert game.runtime.pending_slash is None
    assert game.state.location_of(slash_id) == DISCARD_PILE
    assert not game.state.card_ids_in(PROCESSING_ZONE)
    assert len(_slash_discard_moves(game, slash_id)) == 1
    game.assert_resolution_invariants()
    assert game.phase is ProductionPhase.PLAY


# ----------------------------------------------------------------------
# C. 第一目标不进入 DYING：
#    方天火杀多目标 + 传导触发 + 根牌保持 PROCESSING 直到所有目标完成
# ----------------------------------------------------------------------


def test_c123_global_001_fangtian_huosha_first_target_survives_chain_and_targets_continue() -> None:
    """第一目标 HP=3，火杀后 HP=2 不进入濒死；传导完成后顺利推进剩余目标。"""

    game = _session()
    _enter_play(game)
    _strip_rescue_and_dodge(game)
    _equip_weapon(game, "p1", FANGTIAN)
    _strip_hand(game, "p1")
    slash_id = _give_card(game, "p1", HUOSHA)
    _chain_all(game)
    _set_hp(game, "p1", 4)
    _set_hp(game, "p2", 3)
    _set_hp(game, "p3", 3)
    _set_hp(game, "p4", 3)

    _step(game, _require_op(game, "use_slash", card_key=HUOSHA, targets=("p2", "p3", "p4")))
    _step(game, _require_op(game, "pass_slash_response"))

    # p2 受伤 HP=2，传导使 p3=2, p4=2, p1=3
    assert game.state.players_by_id["p2"].hp == 2
    assert game.state.players_by_id["p3"].hp == 2
    assert game.state.players_by_id["p4"].hp == 2
    assert game.state.players_by_id["p1"].hp == 3

    # 方天根推进到 p3
    assert game.phase is ProductionPhase.SLASH_RESPONSE
    assert game.runtime.pending_slash is not None
    assert game.runtime.pending_slash.target_id == "p3"
    assert game.runtime.pending_slash.current_target_index == 1
    assert game.state.location_of(slash_id) == PROCESSING_ZONE

    _step(game, _require_op(game, "pass_slash_response"))
    assert game.state.players_by_id["p3"].hp == 1

    # 方天根推进到 p4
    assert game.phase is ProductionPhase.SLASH_RESPONSE
    assert game.runtime.pending_slash is not None
    assert game.runtime.pending_slash.target_id == "p4"
    assert game.runtime.pending_slash.current_target_index == 2
    assert game.state.location_of(slash_id) == PROCESSING_ZONE

    _step(game, _require_op(game, "pass_slash_response"))
    assert game.state.players_by_id["p4"].hp == 1

    assert game.runtime.pending_slash is None
    assert game.state.location_of(slash_id) == DISCARD_PILE
    assert not game.state.card_ids_in(PROCESSING_ZONE)
    assert len(_slash_discard_moves(game, slash_id)) == 1
    game.assert_resolution_invariants()
    assert game.phase is ProductionPhase.PLAY


# ----------------------------------------------------------------------
# D. 后续 chain child 进入 DYING 并被救：
#    root card 仍不能被 child rescue path 提前 finish
# ----------------------------------------------------------------------


def test_c123_global_001_fangtian_huosha_chain_child_rescued_targets_continue() -> None:
    """p2 HP=3（不濒死），传导导致 p4（HP=1）濒死并被救；root 必须保持在 PROCESSING。"""

    game = _session()
    _enter_play(game)
    _strip_rescue_and_dodge(game)
    _equip_weapon(game, "p1", FANGTIAN)
    _strip_hand(game, "p1")
    slash_id = _give_card(game, "p1", HUOSHA)
    _chain_all(game)
    _set_hp(game, "p1", 4)
    _set_hp(game, "p2", 3)
    _set_hp(game, "p3", 3)
    _set_hp(game, "p4", 1)
    _give_card(game, "p4", TAO)

    # 方天火杀指定 p2, p3
    _step(game, _require_op(game, "use_slash", card_key=HUOSHA, targets=("p2", "p3")))
    _step(game, _require_op(game, "pass_slash_response"))

    # p2 受伤 1 点，传导顺位到 p4 濒死
    assert game.phase is ProductionPhase.DYING_RESCUE
    assert game.runtime.pending_dying_id == "p4"

    # p1, p2, p3 pass, p4 用桃自救
    _step(game, _require_op(game, "pass_rescue"))
    _step(game, _require_op(game, "pass_rescue"))
    _step(game, _require_op(game, "pass_rescue"))
    _step(game, _require_op(game, "rescue_with_peach", card_key=TAO, targets=("p4",)))
    assert game.state.players_by_id["p4"].hp == 1

    # 传导结束，方天根推进到 p3
    assert game.phase is ProductionPhase.SLASH_RESPONSE
    assert game.runtime.pending_slash is not None
    assert game.runtime.pending_slash.target_id == "p3"
    assert game.runtime.pending_slash.current_target_index == 1
    assert game.state.location_of(slash_id) == PROCESSING_ZONE

    _step(game, _require_op(game, "pass_slash_response"))
    assert game.state.players_by_id["p3"].hp == 1  # 传导受1点+直击受1点: 3 -> 2 -> 1

    assert game.runtime.pending_slash is None
    assert game.state.location_of(slash_id) == DISCARD_PILE
    assert not game.state.card_ids_in(PROCESSING_ZONE)
    assert len(_slash_discard_moves(game, slash_id)) == 1
    game.assert_resolution_invariants()
    assert game.phase is ProductionPhase.PLAY


# ----------------------------------------------------------------------
# E. 后续 chain child 死亡：
#    root 仍完整继续
# ----------------------------------------------------------------------


def test_c123_global_001_fangtian_huosha_chain_child_dies_targets_continue() -> None:
    """p2 HP=3（不濒死），传导导致 p4（HP=1）死亡（非终局）；root 继续推进 p3。"""

    game = _session()
    _enter_play(game)
    _strip_rescue_and_dodge(game)
    _equip_weapon(game, "p1", FANGTIAN)
    _strip_hand(game, "p1")
    slash_id = _give_card(game, "p1", HUOSHA)
    _chain_all(game)
    _set_hp(game, "p1", 4)
    _set_hp(game, "p2", 3)
    _set_hp(game, "p3", 3)
    _set_hp(game, "p4", 1)

    _step(game, _require_op(game, "use_slash", card_key=HUOSHA, targets=("p2", "p3")))
    _step(game, _require_op(game, "pass_slash_response"))

    # p4 传导濒死
    assert game.phase is ProductionPhase.DYING_RESCUE
    assert game.runtime.pending_dying_id == "p4"

    _pass_all_rescues(game)
    assert game.state.players_by_id["p4"].alive is False
    assert game.is_finished is False

    # 传导结束，方天根推进到 p3
    assert game.phase is ProductionPhase.SLASH_RESPONSE
    assert game.runtime.pending_slash is not None
    assert game.runtime.pending_slash.target_id == "p3"
    assert game.runtime.pending_slash.current_target_index == 1
    assert game.state.location_of(slash_id) == PROCESSING_ZONE

    _step(game, _require_op(game, "pass_slash_response"))
    assert game.state.players_by_id["p3"].hp == 1

    assert game.runtime.pending_slash is None
    assert game.state.location_of(slash_id) == DISCARD_PILE
    assert not game.state.card_ids_in(PROCESSING_ZONE)
    assert len(_slash_discard_moves(game, slash_id)) == 1
    game.assert_resolution_invariants()
    assert game.phase is ProductionPhase.PLAY


# ----------------------------------------------------------------------
# F. terminal victory during chain：
#    终局 cleanup 优先，不得继续剩余 Fangtian target，无 PROCESSING orphan
# ----------------------------------------------------------------------


def test_c123_global_001_chain_terminal_victory_cleans_up_root_card() -> None:
    """p2 与 p3 是 team_b；p3 已死，p2 在传导中死亡导致 team_a 获胜。

    终局清理优先，不得继续推进剩余目标，实体牌不滞留 PROCESSING。
    """

    game = _session()
    _enter_play(game)
    _strip_rescue_and_dodge(game)
    _equip_weapon(game, "p1", FANGTIAN)
    _strip_hand(game, "p1")
    slash_id = _give_card(game, "p1", HUOSHA)
    _chain_all(game)
    # p3 已死
    game._state = _replace_player(game.state, "p3", hp=0, alive=False)
    _set_hp(game, "p1", 4)
    _set_hp(game, "p2", 1)
    _set_hp(game, "p4", 4)

    # 方天火杀指定 p2, p4（p2 死后将直接终局）
    _step(game, _require_op(game, "use_slash", card_key=HUOSHA, targets=("p2", "p4")))
    _step(game, _require_op(game, "pass_slash_response"))
    assert game.phase is ProductionPhase.DYING_RESCUE
    assert game.runtime.pending_dying_id == "p2"

    _pass_all_rescues(game)
    assert game.state.players_by_id["p2"].alive is False
    assert game.is_finished is True
    assert game.winner_id == "team_a"
    assert game.phase is ProductionPhase.FINISHED
    assert game.state.location_of(slash_id) == DISCARD_PILE
    assert not game.state.card_ids_in(PROCESSING_ZONE)
    game.assert_finished_state_invariants()


# ----------------------------------------------------------------------
# G. formal draw during chain/death reward：
#    正式平局优先，不得 double-finish 或 resume root
# ----------------------------------------------------------------------


def test_c123_global_001_chain_death_reward_deck_exhaustion_draw() -> None:
    """牌堆只剩 0 张牌：传导中队友死亡触发死亡摸牌奖励时牌堆耗尽，进入正式平局。"""

    game = _session()
    _enter_play(game)
    _strip_rescue_and_dodge(game)
    _equip_weapon(game, "p1", FANGTIAN)
    _strip_hand(game, "p1")
    slash_id = _give_card(game, "p1", HUOSHA)
    _chain_all(game)
    _set_hp(game, "p1", 4)
    _set_hp(game, "p2", 1)
    _set_hp(game, "p3", 4)
    _set_hp(game, "p4", 4)

    # 抽空牌堆与弃牌堆（使死亡奖励摸牌失败平局）
    _drain_deck_to(game, 0)
    for instance_id in tuple(game.state.card_ids_in(DISCARD_PILE)):
        # 保留必要卡牌
        if instance_id != slash_id:
            pass

    _step(game, _require_op(game, "use_slash", card_key=HUOSHA, targets=("p2", "p3", "p4")))
    _step(game, _require_op(game, "pass_slash_response"))
    assert game.phase is ProductionPhase.DYING_RESCUE

    _pass_all_rescues(game)
    assert game.state.players_by_id["p2"].alive is False
    assert game.is_finished is True
    assert game.runtime.game_over_reason == "2v2_draw_deck_exhausted"
    assert game.phase is ProductionPhase.FINISHED
    assert not game.state.card_ids_in(PROCESSING_ZONE)
    game.assert_finished_state_invariants()


# ----------------------------------------------------------------------
# H. 普通单目标 fire Slash + chain + rescued target：
#    必须继续正确 finish，不能滞留 PROCESSING
# ----------------------------------------------------------------------


def test_c123_global_001_single_target_fire_slash_rescued_finishes_correctly() -> None:
    """单目标火杀 + 受击者濒死被救 + 传导继续：根牌正常移入 DISCARD_PILE。"""

    game = _session()
    _enter_play(game)
    _strip_rescue_and_dodge(game)
    _strip_hand(game, "p1")
    slash_id = _give_card(game, "p1", HUOSHA)
    _chain_all(game)
    _set_hp(game, "p1", 4)
    _set_hp(game, "p2", 1)
    _set_hp(game, "p3", 4)
    _set_hp(game, "p4", 4)
    _give_card(game, "p2", TAO)

    _step(game, _require_op(game, "use_slash", card_key=HUOSHA, targets=("p2",)))
    _step(game, _require_op(game, "pass_slash_response"))
    assert game.phase is ProductionPhase.DYING_RESCUE

    _step(game, _require_op(game, "pass_rescue"))
    _step(game, _require_op(game, "rescue_with_peach", card_key=TAO, targets=("p2",)))
    assert game.state.players_by_id["p2"].hp == 1

    # 传导结束，回到出牌阶段，单目标火杀已进入弃牌堆
    assert game.phase is ProductionPhase.PLAY
    assert game.state.location_of(slash_id) == DISCARD_PILE
    assert not game.state.card_ids_in(PROCESSING_ZONE)
    assert len(_slash_discard_moves(game, slash_id)) == 1
    game.assert_resolution_invariants()


# ----------------------------------------------------------------------
# I. 普通单目标 fire Slash + target dies：
#    同样 exactly once cleanup
# ----------------------------------------------------------------------


def test_c123_global_001_single_target_fire_slash_target_dies_finishes_correctly() -> None:
    """单目标火杀 + 受击者死亡（非终局）+ 传导继续：根牌 exactly-once 弃置。"""

    game = _session()
    _enter_play(game)
    _strip_rescue_and_dodge(game)
    _strip_hand(game, "p1")
    slash_id = _give_card(game, "p1", HUOSHA)
    _chain_all(game)
    _set_hp(game, "p1", 4)
    _set_hp(game, "p2", 1)
    _set_hp(game, "p3", 4)
    _set_hp(game, "p4", 4)

    _step(game, _require_op(game, "use_slash", card_key=HUOSHA, targets=("p2",)))
    _step(game, _require_op(game, "pass_slash_response"))
    assert game.phase is ProductionPhase.DYING_RESCUE

    _pass_all_rescues(game)
    assert game.state.players_by_id["p2"].alive is False
    assert game.is_finished is False

    # 传导结束回到出牌阶段
    assert game.phase is ProductionPhase.PLAY
    assert game.state.location_of(slash_id) == DISCARD_PILE
    assert not game.state.card_ids_in(PROCESSING_ZONE)
    assert len(_slash_discard_moves(game, slash_id)) == 1
    game.assert_resolution_invariants()


# ----------------------------------------------------------------------
# J. 普通非属性 Fangtian multi-target Slash：
#    既有生命周期不受影响
# ----------------------------------------------------------------------


def test_c123_global_001_fangtian_normal_slash_multi_target_lifecycle() -> None:
    """普通【杀】+ 方天画戟多目标：目标依次响应，根牌在最后目标完成后弃置。"""

    game = _session()
    _enter_play(game)
    _strip_rescue_and_dodge(game)
    _equip_weapon(game, "p1", FANGTIAN)
    _strip_hand(game, "p1")
    slash_id = _give_card(game, "p1", PUTONG_SHA)
    _set_hp(game, "p1", 4)
    _set_hp(game, "p2", 4)
    _set_hp(game, "p3", 4)
    _set_hp(game, "p4", 4)
    _give_card(game, "p2", SHAN)

    _step(game, _require_op(game, "use_slash", card_key=PUTONG_SHA, targets=("p2", "p3", "p4")))
    assert game.state.location_of(slash_id) == PROCESSING_ZONE

    # p2 出闪抵消
    _step(game, _require_op(game, "play_dodge", card_key=SHAN))
    assert game.state.players_by_id["p2"].hp == 4
    assert game.state.location_of(slash_id) == PROCESSING_ZONE

    # 推进到 p3
    assert game.phase is ProductionPhase.SLASH_RESPONSE
    assert game.runtime.pending_slash.target_id == "p3"
    _step(game, _require_op(game, "pass_slash_response"))
    assert game.state.players_by_id["p3"].hp == 3
    assert game.state.location_of(slash_id) == PROCESSING_ZONE

    # 推进到 p4
    assert game.phase is ProductionPhase.SLASH_RESPONSE
    assert game.runtime.pending_slash.target_id == "p4"
    _step(game, _require_op(game, "pass_slash_response"))
    assert game.state.players_by_id["p4"].hp == 3

    # 全部完成
    assert game.runtime.pending_slash is None
    assert game.state.location_of(slash_id) == DISCARD_PILE
    assert not game.state.card_ids_in(PROCESSING_ZONE)
    assert len(_slash_discard_moves(game, slash_id)) == 1
    game.assert_resolution_invariants()
    assert game.phase is ProductionPhase.PLAY


# ----------------------------------------------------------------------
# K. 丈八蛇矛虚拟杀 + 濒死救援：
#    材料实体恰好 finalize 一次，不发生虚拟卡牌 ID 错误
# ----------------------------------------------------------------------


def test_c123_global_001_zhangba_virtual_slash_dying_rescue_finalizes_materials() -> None:
    """丈八虚拟【杀】指定目标 → 目标濒死出桃自救 → 材料卡牌正常移入 DISCARD_PILE。"""

    game = _session(seed=3)
    _enter_play(game)
    _strip_rescue_and_dodge(game)
    _equip_weapon(game, "p1", ZHANGBA)
    _strip_hand(game, "p1")
    # 给 p1 两张非杀手牌作为丈八材料
    mat1 = _give_card(game, "p1", SHAN)
    mat2 = _give_card(game, "p1", SHAN)
    _set_hp(game, "p1", 4)
    _set_hp(game, "p2", 1)
    _give_card(game, "p2", TAO)

    virtual_uses = [
        a
        for a in game.legal_actions()
        if a.payload.get("zhangba_virtual") is True
        and a.payload.get("operation") == "use_slash"
    ]
    assert virtual_uses
    _step(game, virtual_uses[0])

    # 材料进入 PROCESSING
    assert game.state.location_of(mat1) == PROCESSING_ZONE
    assert game.state.location_of(mat2) == PROCESSING_ZONE

    _step(game, _require_op(game, "pass_slash_response"))
    assert game.phase is ProductionPhase.DYING_RESCUE

    _step(game, _require_op(game, "pass_rescue"))
    _step(game, _require_op(game, "rescue_with_peach", card_key=TAO, targets=("p2",)))
    assert game.state.players_by_id["p2"].hp == 1

    # 结算完成，材料进入 DISCARD_PILE
    assert game.phase is ProductionPhase.PLAY
    assert game.state.location_of(mat1) == DISCARD_PILE
    assert game.state.location_of(mat2) == DISCARD_PILE
    assert not game.state.card_ids_in(PROCESSING_ZONE)
    assert game.runtime.pending_slash is None
    game.assert_resolution_invariants()


# ----------------------------------------------------------------------
# L. 历史门禁 F-004：方天剩余目标在回合所有者传导死亡后继续，root 完成后切回合
# ----------------------------------------------------------------------


def test_c123_global_001_historical_f004_turn_owner_chain_death_fangtian_continues() -> None:
    """F-004 验证：p1 使用方天火杀 (p2, p3)，全员横置，p1 受到传导伤害死亡。

    p1 死亡后方天剩余目标 p3 必须继续；全部完成后才切回合至 p2。
    """

    game = _session()
    _enter_play(game)
    _strip_rescue_and_dodge(game)
    _equip_weapon(game, "p1", FANGTIAN)
    _strip_hand(game, "p1")
    slash_id = _give_card(game, "p1", HUOSHA)
    _chain_all(game)
    _set_hp(game, "p1", 1)
    _set_hp(game, "p2", 4)
    _set_hp(game, "p3", 4)
    _set_hp(game, "p4", 4)

    _step(game, _require_op(game, "use_slash", card_key=HUOSHA, targets=("p2", "p3")))
    assert game.runtime.pending_slash is not None
    assert game.runtime.pending_slash.target_sequence == ("p2", "p3")

    _step(game, _require_op(game, "pass_slash_response"))
    assert game.runtime.pending_dying_id == "p1"
    _pass_all_rescues(game)
    assert game.state.players_by_id["p1"].alive is False
    assert game.is_finished is False

    # 方天 root 推进到 p3
    assert game.phase is ProductionPhase.SLASH_RESPONSE
    assert game.runtime.pending_slash is not None
    assert game.runtime.pending_slash.target_id == "p3"
    assert game.runtime.pending_slash.current_target_index == 1
    assert game.state.location_of(slash_id) == PROCESSING_ZONE
    game.assert_resolution_invariants()

    _step(game, _require_op(game, "pass_slash_response"))
    assert game.state.players_by_id["p3"].hp == 2
    assert game.runtime.pending_slash is None
    assert game.state.location_of(slash_id) == DISCARD_PILE
    assert not game.state.card_ids_in(PROCESSING_ZONE)
    assert len(_slash_discard_moves(game, slash_id)) == 1
    game.assert_resolution_invariants()
    assert game.phase is ProductionPhase.PREPARE
    assert game.current_player_id == "p2"


# ----------------------------------------------------------------------
# M. 历史门禁 F-005：闪电原角色存活 + chain child 非终局死亡保留 JUDGMENT
# ----------------------------------------------------------------------


def test_c123_global_001_historical_f005_alive_owner_child_death_keeps_judgment() -> None:
    """F-005 验证：闪电原受击者存活，传导子目标死亡，判定根保留并进入 DRAW/PLAY。"""

    game = _session()
    _enter_play(game)
    _strip_rescue_and_dodge(game)
    _strip_hand(game, "p1")
    shandian_id = _give_card(game, "p1", SHANDIAN)
    _step(game, _require_op(game, "use_shandian", card_key=SHANDIAN))
    _end_turn(game)
    for _ in range(3):
        _enter_play(game)
        _end_turn(game)
    assert game.current_player_id == "p1"

    _chain_all(game)
    _set_hp(game, "p1", 4)
    _set_hp(game, "p2", 1)
    _set_hp(game, "p3", 4)
    _set_hp(game, "p4", 4)

    _step(game, _require_op(game, "proceed_prepare"))
    _step(game, _require_op(game, "proceed_judgment"))
    if game.state.location_of(SPADE_7_SHA) != DRAW_PILE:
        game._state = game.state.move_card(SPADE_7_SHA, DRAW_PILE)
    pile = list(game.state.card_ids_in(DRAW_PILE))
    pile.remove(SPADE_7_SHA)
    pile.insert(0, SPADE_7_SHA)
    game._state = game.state.reorder_zone(DRAW_PILE, tuple(pile))

    while _op(game, "pass_judgment_wuxie") is not None:
        _step(game, _require_op(game, "pass_judgment_wuxie"))

    assert game.state.players_by_id["p1"].hp == 1
    assert game.state.players_by_id["p1"].alive is True
    if game.phase is ProductionPhase.DYING_RESCUE:
        assert game.runtime.pending_dying_id == "p2"
        _pass_all_rescues(game)

    assert game.state.players_by_id["p2"].alive is False
    assert game.is_finished is False
    assert "shandian_victory_cleanup" not in _reasons(game)
    assert _reasons(game).count("shandian_resolved") == 1
    assert game.runtime.pending_judgment is None
    assert game.phase is ProductionPhase.JUDGMENT
    assert game.current_player_id == "p1"
    assert game.state.location_of(shandian_id) == DISCARD_PILE

    _step(game, _require_op(game, "proceed_judgment"))
    assert game.phase is ProductionPhase.DRAW
    _step(game, _require_op(game, "proceed_draw"))
    assert game.phase is ProductionPhase.PLAY
