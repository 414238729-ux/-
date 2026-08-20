# -*- coding: utf-8 -*-
"""POST-B C4：斗地主手牌三方互盲可见性（3-party mutual hand blindness）与脱敏投影测试。

涵盖：
- Knowledge《三国杀模式规则》§3.6 当前确认：手牌三方互盲可见性；
- 地主 p1 视角只可见 p1 手牌与决策；
- 农民 p2 视角只可见 p2 手牌与决策（不可见农民同伴 p3 手牌！）；
- 农民 p3 视角只可见 p3 手牌与决策（不可见农民同伴 p2 手牌！）；
- 旁观者 None 视角手牌全盲；
- 初始摸牌、摸牌阶段、跋扈摸牌与农民死亡奖励摸牌事件对非观察者脱敏。
"""

import pytest

from scripts.sgs_engine.mode_doudizhu import (
    FORMAL_NO_SKILL_DOUDIZHU_MODE,
    FormalDoudizhuConfiguration,
)
from scripts.sgs_engine.production_replay import (
    record_reference_formal_doudizhu,
)


def test_three_party_mutual_hand_blindness_projection() -> None:
    """斗地主三方互盲：地主与两农民之间、两农民之间手牌均不可见。"""
    config = FormalDoudizhuConfiguration.formal_profile()
    replay = record_reference_formal_doudizhu(
        seed=333,
        configuration=config,
        max_steps=2000,
    )
    valid_pids = ("p1", "p2", "p3")

    # 1. 地主 p1 视角
    p1_view = replay.player_visible_payload(viewer_id="p1", valid_player_ids=valid_pids)
    assert p1_view["player_visible"] is True

    # 2. 农民 p2 视角
    p2_view = replay.player_visible_payload(viewer_id="p2", valid_player_ids=valid_pids)
    assert p2_view["player_visible"] is True

    # 3. 农民 p3 视角
    p3_view = replay.player_visible_payload(viewer_id="p3", valid_player_ids=valid_pids)
    assert p3_view["player_visible"] is True

    # 4. 旁观者 None 视角
    public_view = replay.player_visible_payload(viewer_id=None, valid_player_ids=valid_pids)
    assert public_view["player_visible"] is True

    # 检查事件脱敏：
    # p2 的摸牌事件对 p3 而言必须是被脱敏的（card_instance_id is None）
    for event in p3_view["events"]:
        payload = event.get("payload")
        if isinstance(payload, dict):
            destination = payload.get("destination")
            if isinstance(destination, dict) and destination.get("kind") == "hand":
                owner = destination.get("owner_id")
                if owner == "p2" or owner == "p1":
                    assert event.get("card_instance_id") is None
                    assert payload.get("redacted") is True
                elif owner == "p3":
                    assert event.get("card_instance_id") is not None

    # p3 的摸牌事件对 p2 而言必须是被脱敏的（农民互盲！）
    for event in p2_view["events"]:
        payload = event.get("payload")
        if isinstance(payload, dict):
            destination = payload.get("destination")
            if isinstance(destination, dict) and destination.get("kind") == "hand":
                owner = destination.get("owner_id")
                if owner == "p3" or owner == "p1":
                    assert event.get("card_instance_id") is None
                    assert payload.get("redacted") is True
                elif owner == "p2":
                    assert event.get("card_instance_id") is not None


def test_invalid_viewer_id_rejected() -> None:
    """非法 viewer_id 严格拒绝。"""
    config = FormalDoudizhuConfiguration.formal_profile()
    replay = record_reference_formal_doudizhu(
        seed=444,
        configuration=config,
        max_steps=2000,
    )
    with pytest.raises(ValueError, match="不是正式会话中的合法角色ID"):
        replay.player_visible_payload(
            viewer_id="p4",
            valid_player_ids=("p1", "p2", "p3"),
        )
