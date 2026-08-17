# -*- coding: utf-8 -*-
"""POST-B C3：正式2v2 严格回放专项测试。

覆盖：队伍胜终局记录/重执行往返、牌堆耗尽平局终局记录/重执行往返
（winner=None + 2v2_draw_deck_exhausted）、正式模式禁止夹具、队伍映射
一等输入与篡改失败关闭、canonical profile 绑定、平局终局合法性。
"""

from __future__ import annotations

from typing import Any, Sequence

import pytest

from scripts.sgs_engine.actions import LegalAction
from scripts.sgs_engine.mode_2v2 import (
    FORMAL_NO_SKILL_2V2_MODE,
    Formal2v2Configuration,
)
from scripts.sgs_engine.production_replay import (
    SUPPORTED_REPLAY_MODES,
    ProductionReexecutionReplay,
    ProductionReplayFormatError,
    record_reference_formal_2v2,
    record_reference_production_batch,
    reexecute_production_replay,
)


def _op_by_priority(
    legal: Sequence[LegalAction], phase: str
) -> LegalAction:
    """确定性脚本控制器：按操作名优先级挑选，覆盖平局终局所需流程。"""
    operations = [str(action.payload.get("operation", "")) for action in legal]
    priority_order = (
        "feiyang_decline",
        "proceed_prepare",
        "proceed_judgment",
        "proceed_draw",
        "heal_self",
        "end_play_phase",
        "discard_phase_submit",
        "select_discard_card",
        "end_turn",
        "pass_trick_response",
        "pass_nanman_slash",
        "pass_wanjian_jink",
        "pass_slash_response",
        "pass_rescue",
    )
    for wanted in priority_order:
        if wanted in operations:
            return next(
                action
                for action in legal
                if action.payload.get("operation") == wanted
            )
    raise AssertionError(f"阶段{phase!r}没有可脚本化操作：{operations}")


class _PacifistController:
    """和平脚本控制器：不攻击、不救人伤害，只摸牌/弃牌/结束回合。

    用于把对局确定性地推到牌堆耗尽平局（§2.11）：每回合固定消费2张
    摸牌，无人死亡，牌堆耗尽时由核心立即形成平局。
    """

    strategy_version = "c3-pacifist-controller.v1"

    def choose(
        self, legal_actions: Sequence[LegalAction], context: Any
    ) -> LegalAction:
        return _op_by_priority(legal_actions, str(getattr(context, "phase", "")))


def test_supported_replay_modes_include_2v2() -> None:
    assert FORMAL_NO_SKILL_2V2_MODE in SUPPORTED_REPLAY_MODES


def test_team_victory_replay_roundtrip() -> None:
    """队伍胜终局：记录 winner=team id、重执行逐决策验证一致。"""
    record = record_reference_formal_2v2(
        0,
        configuration=Formal2v2Configuration.formal_profile(),
        analysis_only=False,
        max_steps=6000,
    )
    assert record.header["mode_id"] == FORMAL_NO_SKILL_2V2_MODE
    assert record.outcome["winner_id"] in ("team_a", "team_b")
    assert record.outcome["finish_reason"] == "team_eliminated"
    config = record.header["initial_configuration"]
    assert tuple(config["formal_2v2_configuration"]["player_ids"]) == (
        "p1",
        "p2",
        "p3",
        "p4",
    )
    assert dict(config["teams"]) == {
        "p1": "team_a",
        "p2": "team_b",
        "p3": "team_b",
        "p4": "team_a",
    }
    result = reexecute_production_replay(record)
    assert result.verified is True
    assert result.winner_id == record.outcome["winner_id"]
    assert result.decision_count == record.outcome["decision_count"]


def test_deck_exhaustion_draw_replay_roundtrip() -> None:
    """和平脚本把对局推到牌堆耗尽：记录/重执行平局终局一致。"""
    record = record_reference_formal_2v2(
        5,
        configuration=Formal2v2Configuration.formal_profile(),
        analysis_only=False,
        controller=_PacifistController(),
        max_steps=6000,
    )
    assert record.outcome["winner_id"] is None
    assert record.outcome["finish_reason"] == "2v2_draw_deck_exhausted"
    result = reexecute_production_replay(record)
    assert result.verified is True
    assert result.winner_id is None


def test_formal_2v2_replay_rejects_fixture() -> None:
    from scripts.sgs_engine.mode_2v2 import Formal2v2Session

    game = Formal2v2Session(
        seed=1,
        configuration=Formal2v2Configuration.formal_profile(),
        analysis_only=True,
    )
    with pytest.raises(
        ProductionReplayFormatError, match="正式2v2回放禁止夹具"
    ):
        record_reference_production_batch(
            1,
            _game=game,
            fixture=lambda _game: None,
        )


def test_replay_teams_tamper_fails_closed() -> None:
    """队伍映射是回放一等输入：篡改后重执行必须失败关闭。"""
    record = record_reference_formal_2v2(
        2,
        configuration=Formal2v2Configuration.formal_profile(),
        analysis_only=True,
        max_steps=6000,
    )
    payload = record.to_dict()
    payload["header"]["initial_configuration"]["teams"]["p4"] = "team_b"
    payload["record_sha256"] = ""  # 重新计算记录哈希，测试结构校验本身
    tampered = ProductionReexecutionReplay.from_dict(payload)
    with pytest.raises(ProductionReplayFormatError, match="队伍映射"):
        reexecute_production_replay(tampered)


def test_replay_config_tamper_fails_closed() -> None:
    """formal_2v2_configuration 篡改：配置重建校验失败关闭。"""
    from scripts.sgs_engine.mode_2v2 import Formal2v2ConfigurationError

    record = record_reference_formal_2v2(
        2,
        configuration=Formal2v2Configuration.formal_profile(),
        analysis_only=True,
        max_steps=6000,
    )
    payload = record.to_dict()
    payload["header"]["initial_configuration"]["formal_2v2_configuration"][
        "initial_hand_counts"
    ] = [3, 3, 3, 3]
    payload["record_sha256"] = ""  # 重新计算记录哈希，测试结构校验本身
    tampered = ProductionReexecutionReplay.from_dict(payload)
    with pytest.raises(Formal2v2ConfigurationError, match="合计16"):
        reexecute_production_replay(tampered)


def test_record_reference_requires_canonical_session_type() -> None:
    """正式2v2回放只接受 canonical Formal2v2Session 类型。"""
    from scripts.sgs_engine.production_batch import ProductionBasicCardBatch

    game = ProductionBasicCardBatch(seed=1, player_hp=(4, 4, 4, 4),
                                    player_max_hp=(4, 4, 4, 4))
    game.MODE_ID = FORMAL_NO_SKILL_2V2_MODE
    with pytest.raises(ProductionReplayFormatError, match="Formal2v2Session"):
        record_reference_production_batch(1, _game=game)


def test_record_reference_mode_whitelist() -> None:
    """未知模式ID 的 _game 拒绝进入回放。"""
    from scripts.sgs_engine.production_batch import ProductionBasicCardBatch

    game = ProductionBasicCardBatch(seed=1, player_hp=(4, 4),
                                    player_max_hp=(4, 4))
    game.MODE_ID = "unknown_mode_id"
    with pytest.raises(ProductionReplayFormatError, match="白名单"):
        record_reference_production_batch(1, _game=game)
