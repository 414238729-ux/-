"""短路径 API、安全与多步交互回归。"""
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest

from scripts.sgs_engine.playable_config import GameConfig
from scripts.sgs_engine.playable_runtime import GameService, RuntimeProtocolError
from scripts.sgs_engine.model import ZoneRef, DRAW_PILE
from scripts.sgs_engine.production_batch import ProductionPhase


def game(mode="2v2", **kw):
    service = GameService()
    sid = service.create_game(GameConfig(mode=mode, control="ALL_HUMAN", mulligan=False, **kw))
    return service, sid


def action(service, sid, seat, operation):
    view = service.get_player_view(sid, seat)
    decision = view["decision"]
    option = next(x for x in decision["options"] if x["operation"] == operation)
    return decision["decision_id"], option["action_id"]


def test_mode_specific_hands_and_identities():
    for mode in ("2v2", "doudizhu", "identity8"):
        s, sid = game(mode, landlord_seat=1 if mode == "doudizhu" else None)
        view = s.get_player_view(sid, 1)
        hands = [p["id"] for p in view["players"] if p["hand"] is not None]
        assert hands == (["p1", "p4"] if mode == "2v2" else ["p1"])
        raw = json.dumps(view)
        assert "sgs-mobile-20260725-" not in raw
        assert "session_secret" not in raw and '"seed"' not in raw
        if mode == "identity8":
            for p in view["players"]:
                assert p["role"] in (None, "lord") or p["id"] == "p1"
        events = s.get_events(sid, 1)["events"]
        for e in events:
            if e["type"] == "card_gained" and "card" in e:
                assert any(pid in hands for pid in e["targets"])


def test_signed_stale_repeat_wrong_actor_and_cross_session():
    s, sid = game()
    did, token = action(s, sid, 1, "proceed_prepare")
    other = s.create_game(GameConfig(control="ALL_HUMAN", mulligan=False))
    with pytest.raises(RuntimeProtocolError, match="INVALID_ACTION"):
        odid = s.get_player_view(other, 1)["decision"]["decision_id"]
        s.submit_action(other, 1, odid, token)
    with pytest.raises(RuntimeProtocolError, match="WRONG_ACTOR"):
        s.submit_action(sid, 2, did, token)
    receipt = s.submit_action(sid, 1, did, token, "req1")
    assert receipt["accepted_steps"] == 1
    assert s.submit_action(sid, 1, did, token, "req1")["duplicate"]
    assert s.submit_action(sid, 1, did, token)["duplicate"]
    with pytest.raises(RuntimeProtocolError, match="STALE_DECISION"):
        s.submit_action(sid, 1, did, token + "x")
    new_did, new_token = action(s, sid, 1, "proceed_judgment")
    with pytest.raises(RuntimeProtocolError, match="REQUEST_ID_CONFLICT"):
        s.submit_action(sid, 1, new_did, new_token, "req1")


def test_concurrent_duplicate_commits_once():
    s, sid = game()
    did, token = action(s, sid, 1, "proceed_prepare")
    with ThreadPoolExecutor(2) as pool:
        answers = list(pool.map(lambda _: s.submit_action(sid, 1, did, token, "r"), range(2)))
    assert sorted(a["duplicate"] for a in answers) == [False, True]


def test_multiple_choice_advances_decision_without_state_revision():
    s, sid = game(enabled_generals=("soldier",))
    for op in ("proceed_prepare", "proceed_judgment", "proceed_draw", "end_play_phase"):
        s.submit_action(sid, 1, *action(s, sid, 1, op))
    internal = s._sessions[sid]
    before = internal.game.state.revision
    view = s.get_player_view(sid, 1)
    old_did = view["decision"]["decision_id"]
    choices = [a for a in view["decision"]["options"] if a["operation"] == "select_discard_card"]
    s.submit_action(sid, 1, old_did, choices[0]["action_id"])
    assert internal.game.state.revision == before
    assert s.get_player_view(sid, 1)["decision"]["decision_id"] != old_did
    with pytest.raises(RuntimeProtocolError, match="STALE_DECISION"):
        s.submit_action(sid, 1, old_did, choices[1]["action_id"])
    s.submit_action(sid, 1, *action(s, sid, 1, "discard_phase_submit"))


def test_all_human_stops_and_no_omniscient_default():
    s, sid = game()
    assert s.advance_until_human_or_terminal(sid)["stop"] == "HUMAN"
    with pytest.raises(RuntimeProtocolError, match="DEBUG_DISABLED"):
        s.get_omniscient_debug_view(sid)


def test_legacy_automatic_signals_removed_without_hand_sharing():
    s, sid = game("doudizhu", landlord_seat=1, enabled_generals=("soldier",))
    for seat in (1, 2, 3):
        view = s.get_player_view(sid, seat)
        assert "signals" not in view
        assert view["cooperation_history"] == []
        assert [p["id"] for p in view["players"] if p["hand"] is not None] == [f"p{seat}"]
    with pytest.raises(RuntimeProtocolError, match="LEGACY_SIGNAL_REMOVED"):
        s.submit_signal(sid, 2, "old_decision", "old_token")


def test_real_zuilun_private_choice_and_event_never_share_topdeck_with_teammate():
    s, sid = game(enabled_generals=("zhugezhan",))
    for op in ("proceed_prepare", "proceed_judgment", "proceed_draw", "end_play_phase"):
        s.submit_action(sid, 1, *action(s, sid, 1, op))
    while s._sessions[sid].game.core.phase == ProductionPhase.DISCARD:
        view = s.get_player_view(sid, 1)
        options = view["decision"]["options"]
        choice = next((o for o in options if o["operation"] == "discard_phase_submit"), None)
        choice = choice or next(o for o in options if o["operation"] == "select_discard_card")
        s.submit_action(sid, 1, view["decision"]["decision_id"], choice["action_id"])
    s.submit_action(sid, 1, *action(s, sid, 1, "activate_skill"))
    own, mate = s.get_player_view(sid, 1), s.get_player_view(sid, 4)
    assert len(own["pending"]["observed_cards"]) == 3
    assert "observed_cards" not in mate["pending"] and mate["decision"] is None
    private = [e for e in s.get_events(sid, 1)["events"] if e["type"] == "private_cards_observed"]
    assert len(private) == 1 and len(private[0]["cards"]) == 3
    assert not any(e["type"] == "private_cards_observed" for e in s.get_events(sid, 4)["events"])
    core = s._sessions[sid].game.core
    for cid in core._pending_private_card_selection.observed_ids:
        assert cid not in json.dumps(own)
    choice = own["decision"]["options"][0]
    assert choice["operation"] == "private_card_selection_submit"
    s.submit_action(sid, 1, own["decision"]["decision_id"], choice["action_id"])
    assert core._pending_private_card_selection is None


def test_heir_private_memory_and_no_hidden_role_in_other_views():
    roles = ("lord", "loyalist", "loyalist", "rebel", "rebel", "rebel", "rebel", "spy")
    s, sid = game("identity8_heir", identities=roles, enabled_generals=("soldier",))
    s.submit_action(sid, 1, *action(s, sid, 1, "proceed_prepare"))
    s.submit_action(sid, 1, *action(s, sid, 1, "select_heir"))
    assert s.get_player_view(sid, 1)["own_mode_memory"]["heir"] is not None
    for seat in (2, 3, 8):
        view = s.get_player_view(sid, seat)
        assert view["own_mode_memory"] == {}
        assert not any("heir" in json.dumps(e) for e in s.get_events(sid, seat)["events"])


def test_committed_receipt_survives_projection_error_without_double_apply(monkeypatch):
    s, sid = game()
    did, token = action(s, sid, 1, "proceed_prepare")
    def fail(session):
        raise ValueError("命名投影失败注入")
    monkeypatch.setattr(s, "_capture_events", fail)
    with pytest.raises(RuntimeProtocolError, match="EVENT_PROJECTION_FAILED"):
        s.submit_action(sid, 1, did, token)
    assert s.submit_action(sid, 1, did, token)["duplicate"]
    assert s.get_result(sid)["status"] == "ERROR" and s._sessions[sid].accepted == 1


def test_borrowed_sword_projects_both_production_targets_to_human_and_ai():
    s, sid = game(enabled_generals=("soldier",))
    core = s._sessions[sid].game.core
    trick = next(c.instance_id for c in core.state.cards if c.card_key == "sgs_trick_jiedaosharen")
    weapon = next(c.instance_id for c in core.state.cards if c.card_key == "sgs_weapon_guanshifu")
    core._state = core.state.move_cards({trick: ZoneRef.hand("p1"), weapon: ZoneRef.equipment("p4", "weapon")})
    core._runtime = replace(core.runtime, phase=ProductionPhase.PLAY)
    options = s.get_player_view(sid, 1)["decision"]["options"]
    jiedao = [o for o in options if o["operation"] == "use_jiedao"]
    assert jiedao and all(len(o["targets"]) == 2 for o in jiedao)
    assert all(all(pid in o["description"] for pid in o["targets"]) for o in jiedao)


def test_post_commit_statistics_exception_keeps_receipt_and_closes_decision(monkeypatch):
    roles = ("lord", "loyalist", "loyalist", "rebel", "rebel", "rebel", "rebel", "spy")
    s, sid = game("identity8", identities=roles, enabled_generals=("soldier",))
    did, token = action(s, sid, 1, "proceed_prepare")
    internal = s._sessions[sid]
    def fail():
        raise ValueError("命名提交后统计失败")
    monkeypatch.setattr(internal.game, "current_roles", fail)
    with pytest.raises(RuntimeProtocolError, match="POST_COMMIT_BOOKKEEPING_FAILED"):
        s.submit_action(sid, 1, did, token, "durable")
    assert s.submit_action(sid, 1, did, token, "durable")["duplicate"]
    assert internal.accepted == internal.generation == internal.game.core.step_count == 1
    assert s.get_result(sid)["status"] == "ERROR"
