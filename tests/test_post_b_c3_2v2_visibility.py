# -*- coding: utf-8 -*-
"""POST-B C3：正式2v2 可见性策略专项测试（§2.4 队友可见手牌）。

覆盖：队友可见队友的手牌获得实体（初始发牌/摸牌/死亡奖励摸牌），
对手与公共视图只保留数量与 reason；非法观察者失败关闭；权威记录
本身不做任何脱敏（严格重执行仍可验证）。
"""

from __future__ import annotations

from typing import Mapping, Sequence

import pytest

from scripts.sgs_engine.mode_2v2 import Formal2v2Configuration
from scripts.sgs_engine.production_replay import (
    record_reference_formal_2v2,
    reexecute_production_replay,
)

_SEED = 0
_VALID_PLAYER_IDS = ("p1", "p2", "p3", "p4")
_TEAMS = {"p1": "team_a", "p2": "team_b", "p3": "team_b", "p4": "team_a"}


def _teammate_of(player_id: str) -> str:
    team = _TEAMS[player_id]
    return next(
        candidate
        for candidate, candidate_team in _TEAMS.items()
        if candidate != player_id and candidate_team == team
    )


def _opponent_of(player_id: str) -> str:
    team = _TEAMS[player_id]
    return next(
        candidate
        for candidate, candidate_team in _TEAMS.items()
        if candidate_team != team
    )


@pytest.fixture(scope="module")
def _record():
    record = record_reference_formal_2v2(
        _SEED,
        configuration=Formal2v2Configuration.formal_profile(),
        analysis_only=True,
        max_steps=6000,
    )
    assert reexecute_production_replay(record).verified is True
    return record


def _find_events(
    events: Sequence[Mapping[str, object]],
    *,
    event_type: str,
    reason: str | None = None,
    recipient: str | None = None,
) -> list[Mapping[str, object]]:
    found: list[Mapping[str, object]] = []
    for event in events:
        if event.get("event_type") != event_type:
            continue
        payload = event.get("payload")
        if reason is not None and (
            not isinstance(payload, Mapping)
            or payload.get("reason") != reason
        ):
            continue
        if recipient is not None:
            target_ids = event.get("target_ids")
            if not isinstance(target_ids, (list, tuple)) or not target_ids:
                continue
            if target_ids[0] != recipient:
                continue
        found.append(event)
    return found


def test_authoritative_record_keeps_full_material(_record) -> None:
    """权威记录不做脱敏：私有获得事件保留实体ID（严格重执行依赖）。"""
    initial_gains = _find_events(
        _record.events, event_type="card_gained", reason="initial_hand"
    )
    assert len(initial_gains) == 16
    assert all(event["card_instance_id"] is not None for event in initial_gains)


def test_teammate_sees_death_reward_draw(_record) -> None:
    """§2.7 死亡奖励摸牌对同队队友可见。"""
    reward_events = _find_events(
        _record.events,
        event_type="card_gained",
        reason="death_reward_teammate_draw",
    )
    assert reward_events, "固定种子对局应包含死亡奖励摸牌事件"
    for authority_event in reward_events:
        recipient = authority_event["target_ids"][0]
        teammate_view = _record.player_visible_payload(
            viewer_id=_teammate_of(recipient),
            valid_player_ids=_VALID_PLAYER_IDS,
        )
        visible = _find_events(
            teammate_view["events"],
            event_type="card_gained",
            reason="death_reward_teammate_draw",
            recipient=recipient,
        )
        assert visible, f"{recipient} 的死亡奖励摸牌应被队友看到"
        assert visible[0]["card_instance_id"] is not None


def test_opponent_cannot_see_death_reward_draw(_record) -> None:
    """对手视图：死亡奖励摸牌只保留数量与 reason，不暴露实体。"""
    reward_events = _find_events(
        _record.events,
        event_type="card_gained",
        reason="death_reward_teammate_draw",
    )
    assert reward_events
    for authority_event in reward_events:
        recipient = authority_event["target_ids"][0]
        opponent_view = _record.player_visible_payload(
            viewer_id=_opponent_of(recipient),
            valid_player_ids=_VALID_PLAYER_IDS,
        )
        visible = _find_events(
            opponent_view["events"],
            event_type="card_gained",
            reason="death_reward_teammate_draw",
            recipient=recipient,
        )
        assert visible
        assert visible[0]["card_instance_id"] is None
        assert visible[0]["card_key"] is None
        payload = visible[0]["payload"]
        assert payload.get("redacted") is True


def test_teammate_sees_initial_hand(_record) -> None:
    """§2.4：p1 可见队友 p4 的初始发牌实体；对手不可见。"""
    p4_initial = _find_events(
        _record.events,
        event_type="card_gained",
        reason="initial_hand",
        recipient="p4",
    )
    assert len(p4_initial) == 5  # 4号位初始5张
    teammate_view = _record.player_visible_payload(
        viewer_id="p1",
        valid_player_ids=_VALID_PLAYER_IDS,
    )
    visible_to_p1 = _find_events(
        teammate_view["events"],
        event_type="card_gained",
        reason="initial_hand",
        recipient="p4",
    )
    assert len(visible_to_p1) == 5
    assert all(event["card_instance_id"] is not None for event in visible_to_p1)
    opponent_view = _record.player_visible_payload(
        viewer_id="p2",
        valid_player_ids=_VALID_PLAYER_IDS,
    )
    visible_to_p2 = _find_events(
        opponent_view["events"],
        event_type="card_gained",
        reason="initial_hand",
        recipient="p4",
    )
    assert len(visible_to_p2) == 5
    assert all(event["card_instance_id"] is None for event in visible_to_p2)


def test_public_view_redacts_all_private_gains(_record) -> None:
    public = _record.player_visible_payload(
        viewer_id=None,
        valid_player_ids=_VALID_PLAYER_IDS,
    )
    private_gains = [
        event
        for event in public["events"]
        if event.get("event_type") == "card_gained"
        and isinstance(event.get("payload"), Mapping)
        and event["payload"].get("reason") in ("initial_hand", "draw_phase")
    ]
    assert private_gains
    assert all(event["card_instance_id"] is None for event in private_gains)
    assert public["player_visible"] is True
    assert "authoritative_private" not in public


def test_visibility_payload_drops_authority_material(_record) -> None:
    payload = _record.player_visible_payload(
        viewer_id="p1",
        valid_player_ids=_VALID_PLAYER_IDS,
    )
    header = payload["header"]
    assert "seed" not in header
    assert "initial_rng_state" not in header
    assert "authoritative_private" not in payload
    assert payload["random_consumptions"] == []
    assert payload["event_hash_chain"] == []


def test_invalid_viewer_fails_closed(_record) -> None:
    with pytest.raises(ValueError, match="合法角色"):
        _record.player_visible_payload(
            viewer_id="p5",
            valid_player_ids=_VALID_PLAYER_IDS,
        )


def test_teammate_of_teammate_symmetric(_record) -> None:
    """队伍映射来自回放一等输入：p2/p3 互见、p1/p4 互见。"""
    p3_view = _record.player_visible_payload(
        viewer_id="p3",
        valid_player_ids=_VALID_PLAYER_IDS,
    )
    p2_initial = _find_events(
        p3_view["events"],
        event_type="card_gained",
        reason="initial_hand",
        recipient="p2",
    )
    assert len(p2_initial) == 4
    assert all(event["card_instance_id"] is not None for event in p2_initial)
    p1_view = _record.player_visible_payload(
        viewer_id="p1",
        valid_player_ids=_VALID_PLAYER_IDS,
    )
    p2_initial_from_p1 = _find_events(
        p1_view["events"],
        event_type="card_gained",
        reason="initial_hand",
        recipient="p2",
    )
    assert all(
        event["card_instance_id"] is None for event in p2_initial_from_p1
    )
