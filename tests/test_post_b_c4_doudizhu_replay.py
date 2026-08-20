# -*- coding: utf-8 -*-
"""POST-B C4：正式斗地主 严格回放专项测试。

覆盖：
- 阵营胜终局记录/重执行往返（winner in ('landlord', 'peasants')）；
- 牌堆耗尽平局终局记录/重执行往返（winner=None + doudizhu_draw_deck_exhausted）；
- 正式模式禁止夹具；
- 阵营映射一等输入与篡改失败关闭；
- canonical profile 绑定；
- 严格规则重执行逐决策验证一致。
"""

from __future__ import annotations

from typing import Any, Sequence
import pytest

from scripts.sgs_engine.actions import LegalAction
from scripts.sgs_engine.mode_doudizhu import (
    FORMAL_NO_SKILL_DOUDIZHU_MODE,
    FormalDoudizhuConfiguration,
    FormalDoudizhuConfigurationError,
    FormalDoudizhuSession,
)
from scripts.sgs_engine.production_replay import (
    SUPPORTED_REPLAY_MODES,
    ProductionReexecutionReplay,
    ProductionReplayDivergenceError,
    ProductionReplayFormatError,
    record_reference_formal_doudizhu,
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
        "peasant_reward_decline",
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

    用于把对局确定性地推到牌堆耗尽平局（§3.4）：无人死亡，
    牌堆耗尽时由核心立即形成平局。
    """

    strategy_version = "c4-pacifist-controller.v1"

    def choose(
        self, legal_actions: Sequence[LegalAction], context: Any
    ) -> LegalAction:
        return _op_by_priority(legal_actions, str(getattr(context, "phase", "")))


def test_supported_replay_modes_include_doudizhu() -> None:
    assert FORMAL_NO_SKILL_DOUDIZHU_MODE in SUPPORTED_REPLAY_MODES


def test_camp_victory_replay_roundtrip() -> None:
    """阵营胜终局：记录 winner=camp id、重执行逐决策验证一致。"""
    record = record_reference_formal_doudizhu(
        0,
        configuration=FormalDoudizhuConfiguration.formal_profile(),
        analysis_only=False,
        max_steps=6000,
    )
    assert record.header["mode_id"] == FORMAL_NO_SKILL_DOUDIZHU_MODE
    assert record.outcome["winner_id"] in ("landlord", "peasants")
    assert record.outcome["finish_reason"] == "team_eliminated"
    config = record.header["initial_configuration"]
    assert tuple(config["formal_doudizhu_configuration"]["player_ids"]) == (
        "p1",
        "p2",
        "p3",
    )
    assert dict(config["camps"]) == {
        "p1": "landlord",
        "p2": "peasants",
        "p3": "peasants",
    }
    result = reexecute_production_replay(record)
    assert result.verified is True
    assert result.winner_id == record.outcome["winner_id"]
    assert result.decision_count == record.outcome["decision_count"]


def test_deck_exhaustion_draw_replay_roundtrip() -> None:
    """和平脚本把对局推到牌堆耗尽：记录/重执行平局终局一致。"""
    record = record_reference_formal_doudizhu(
        5,
        configuration=FormalDoudizhuConfiguration.formal_profile(),
        analysis_only=False,
        controller=_PacifistController(),
        max_steps=6000,
    )
    assert record.outcome["winner_id"] is None
    assert record.outcome["finish_reason"] == "doudizhu_draw_deck_exhausted"
    result = reexecute_production_replay(record)
    assert result.verified is True
    assert result.winner_id is None


def test_formal_doudizhu_replay_rejects_fixture() -> None:
    game = FormalDoudizhuSession(
        seed=1,
        configuration=FormalDoudizhuConfiguration.formal_profile(),
        analysis_only=True,
    )
    with pytest.raises(
        ProductionReplayFormatError, match="正式斗地主回放禁止夹具"
    ):
        record_reference_production_batch(
            1,
            _game=game,
            fixture=lambda _game: None,
        )


def test_replay_camps_tamper_fails_closed() -> None:
    """阵营映射是回放一等输入：篡改后重执行必须失败关闭。"""
    record = record_reference_formal_doudizhu(
        2,
        configuration=FormalDoudizhuConfiguration.formal_profile(),
        analysis_only=True,
        max_steps=6000,
    )
    payload = record.to_dict()
    payload["header"]["initial_configuration"]["camps"]["p1"] = "peasants"
    payload["record_sha256"] = ""  # 重新计算记录哈希，测试结构校验本身
    tampered = ProductionReexecutionReplay.from_dict(payload)
    with pytest.raises(ProductionReplayFormatError, match="阵营映射"):
        reexecute_production_replay(tampered)


def test_replay_config_tamper_fails_closed() -> None:
    """formal_doudizhu_configuration 篡改：配置重建校验失败关闭。"""
    record = record_reference_formal_doudizhu(
        2,
        configuration=FormalDoudizhuConfiguration.formal_profile(),
        analysis_only=True,
        max_steps=6000,
    )
    payload = record.to_dict()
    payload["header"]["initial_configuration"]["formal_doudizhu_configuration"][
        "initial_hand_counts"
    ] = [3, 3, 3]
    payload["record_sha256"] = ""  # 重新计算记录哈希，测试结构校验本身
    tampered = ProductionReexecutionReplay.from_dict(payload)
    with pytest.raises(FormalDoudizhuConfigurationError, match="合计12"):
        reexecute_production_replay(tampered)
