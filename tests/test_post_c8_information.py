"""用户确认的信息规则：真实生产开窗、公共摘要、上下文问答的短回归。"""
from dataclasses import replace
import json

from scripts.sgs_engine.playable_config import GameConfig
from scripts.sgs_engine.playable_runtime import GameService
from scripts.sgs_engine.model import DRAW_PILE, ZoneRef
from scripts.sgs_engine.production_batch import ProductionPhase
from scripts.sgs_team_strategy import NullificationAvailability
import pytest
from scripts.sgs_engine.playable_runtime import RuntimeProtocolError, HumanController
from scripts.sgs_engine.production_ai import ProductionAIController
from scripts.sgs_engine.playable_communication import current_answer, DistributionPlan, ProbeBudget


def fixture(hands, actor="p1", mode="doudizhu", control="ALL_HUMAN", generals=("soldier",)):
    """命名局面 fixture，只重排初始牌；之后全部经生产合法签名提交。"""
    service = GameService()
    sid = service.create_game(GameConfig(mode=mode, control=control, mulligan=False,
        landlord_seat=1 if mode == "doudizhu" else None, enabled_generals=generals))
    session = service._sessions[sid]
    core = session.game.core
    state = core.state
    for pid in session.game.config.player_ids:
        for cid in state.card_ids_in(ZoneRef.hand(pid)):
            state = state.move_card(cid, DRAW_PILE)
    used = set()
    for pid, keys in hands.items():
        for key in keys:
            cid = next(c.instance_id for c in state.cards if c.card_key == key and c.instance_id not in used)
            used.add(cid)
            state = state.move_card(cid, ZoneRef.hand(pid))
    core._state = state
    core._runtime = replace(core.runtime, phase=ProductionPhase.PLAY, current_player_id=actor)
    # 已发过的初始摸牌与 fixture 不作为正式观察；基于空知识重新记录当前手牌基准。
    session.information._hands = {p: frozenset(state.card_ids_in(ZoneRef.hand(p)))
                                  for p in session.game.config.player_ids}
    return service, sid, session


def submit(service, sid, operation, *, target=None):
    session = service._sessions[sid]
    seat = int(session.game.actor[1:])
    view = service.get_player_view(sid, seat)
    choice = next(o for o in view["decision"]["options"] if o["operation"] == operation
                  and (target is None or target in o["targets"]))
    return service.submit_action(sid, seat, view["decision"]["decision_id"], choice["action_id"])


def test_real_public_window_pass_and_counter_window():
    s, sid, session = fixture({"p1": ["sgs_trick_wuzhongshengyou"],
                                "p2": ["sgs_trick_wuxiekeji"] * 2})
    for seat in (1, 2, 3):
        v = s.get_player_view(sid, seat)["nullification"]
        assert all(x["availability"] == "unknown" for x in v["players"].values())
        assert v["has_unknown"] and not v["all_none"]
    submit(s, sid, "use_wuzhong")
    views = [s.get_player_view(sid, i)["nullification"] for i in (1, 2, 3)]
    assert views[0] == views[1] == views[2]
    assert views[0]["players"]["p2"]["availability"] == "known_usable"
    assert views[0]["players"]["p1"]["availability"] == "known_none"
    wid = views[0]["window"]["id"]
    submit(s, sid, "pass_trick_response")
    submit(s, sid, "pass_trick_response")
    v = s.get_player_view(sid, 1)["nullification"]
    assert v["window"]["id"] == wid and "p2" in v["window"]["passed"]
    assert v["players"]["p2"]["availability"] == "known_usable"
    passes = [e for e in s.get_events(sid, 1)["events"] if e["type"] == "nullification_passed"]
    assert [(e["actor"], e["observed_availability"], e["consumed"]) for e in passes] == [
        ("p1", "known_none", False), ("p2", "known_usable", False)]
    # 新开一局使用无懈，后续反无懈观察依据真实剩余资格；不推断一张即用尽。
    s, sid, session = fixture({"p1": ["sgs_trick_wuzhongshengyou"], "p2": ["sgs_trick_wuxiekeji"] * 2})
    submit(s, sid, "use_wuzhong")
    submit(s, sid, "pass_trick_response")
    submit(s, sid, "use_wuxie")
    v = s.get_player_view(sid, 3)["nullification"]
    assert v["window"]["layer"] == 1 and v["window"]["id"] != wid
    assert v["players"]["p2"]["availability"] == "known_usable"
    events = [e for e in s.get_events(sid, 1)["events"] if e["type"].startswith("nullification_")]
    assert next(e for e in events if e["type"] == "nullification_used")["remaining"] == "unknown"
    observations = [e for e in events if e["type"] == "nullification_observation"]
    assert len(observations) == 2
    raw = json.dumps(observations)
    assert all(x not in raw for x in ("instance_id", "rank", "suit", "quantity", "sgs-mobile", "seed"))
    for seat in (2, 3):
        assert events == [e for e in s.get_events(sid, seat)["events"] if e["type"].startswith("nullification_")]


def test_unknown_gain_invalidates_only_recipient_and_views_do_not_refresh():
    s, sid, session = fixture({"p1": ["sgs_trick_wuzhongshengyou"], "p2": ["sgs_trick_wuxiekeji"]})
    submit(s, sid, "use_wuzhong")
    for _ in range(3):
        submit(s, sid, "pass_trick_response")
    rows = s.get_player_view(sid, 1)["nullification"]["players"]
    assert rows["p1"]["availability"] == "unknown"
    assert rows["p2"]["availability"] == "known_usable"
    assert rows["p3"]["availability"] == "known_none"
    snapshot = session.information.nullification.snapshot()
    for _ in range(3):
        s.get_player_view(sid, 1)
        s.get_player_view(sid, 2)
    assert session.information.nullification.snapshot() == snapshot
    assert snapshot["p1"].availability is NullificationAvailability.UNKNOWN


def protection_fixture(key="sgs_trick_nanmanruqin", response=None, control="ALL_HUMAN"):
    s, sid, session = fixture({"p1": [key], "p2": ["sgs_trick_wuxiekeji"],
                               "p3": [response] if response else []}, control=control)
    submit(s, sid, "use_nanman" if key.endswith("nanmanruqin") else "use_wanjian")
    for _ in range(20):
        actor = session.game.actor
        v = s.get_player_view(sid, int(actor[1:]))
        c = v["communication"]
        if actor == "p2" and c and any(o["question"]["topic"] == "nullification_protection" for o in c["options"]):
            return s, sid, session
        op = next(o for o in v["decision"]["options"] if o["operation"].startswith("pass_"))
        s.submit_action(sid, int(actor[1:]), v["decision"]["decision_id"], op["action_id"])
    raise AssertionError("生产群体牌未到达第二农民的真实无懈窗口")


def ask_protection(s, sid):
    v = s.get_player_view(sid, 2)
    c = v["communication"]
    offer = next(o for o in c["options"] if o["question"]["topic"] == "nullification_protection")
    return s.ask_question(sid, 2, c["decision_id"], offer["action_id"], "ask-1"), offer, c["decision_id"]


@pytest.mark.parametrize("key,response,expected", [
    ("sgs_trick_nanmanruqin", None, "YES"), ("sgs_trick_nanmanruqin", "sgs_basic_sha", "NO"),
    ("sgs_trick_wanjianqifa", None, "YES"), ("sgs_trick_wanjianqifa", "sgs_basic_shan", "NO")])
def test_real_protection_public_qa_and_ai_decision(key, response, expected):
    s, sid, session = protection_fixture(key, response)
    before_state, before_runtime, before_steps = session.game.state, session.game.core.runtime, session.accepted
    ask, offer, did = ask_protection(s, sid)
    assert s.ask_question(sid, 2, did, offer["action_id"], "ask-1")["duplicate"]
    assert s.advance_until_human_or_terminal(sid)["stop"] == "HUMAN_ANSWER"
    assert s.advance_until_human_or_terminal(sid)["seat"] == 3
    with pytest.raises(RuntimeProtocolError, match="ANSWER_PENDING"):
        submit(s, sid, "use_wuxie")
    view = s.get_player_view(sid, 3)
    assert view["decision"] is None  # 游戏行动者仍是p2，回答者不能代交无懈。
    ai = ProductionAIController(parameters={"tie_randomness": 0})
    token = ai.answer_question(view)
    answer = s.answer_question(sid, 3, ask["question_id"], token, "answer-1")
    assert answer["answer"] == expected
    assert s.answer_question(sid, 3, ask["question_id"], token, "answer-1")["duplicate"]
    assert session.game.state is before_state and session.game.core.runtime is before_runtime and session.accepted == before_steps
    assert len(session.questions) == 1
    qa = [e for e in s.get_events(sid, 1)["events"] if e["type"].startswith("cooperation_")]
    for seat in (2, 3):
        assert qa == [e for e in s.get_events(sid, seat)["events"] if e["type"].startswith("cooperation_")]
    assert len(qa) == 2 and qa[-1]["question"]["answer"] == expected
    raw = json.dumps(qa)
    assert all(x not in raw for x in ("hand", "reason", "score", "sgs_basic_sha", "sgs_basic_shan", "action_id", "seed", "suit"))
    view = s.get_player_view(sid, 2)
    ai = ProductionAIController(parameters={"tie_randomness": 0})
    choice = ai.choose(view)
    op = next(o["operation"] for o in view["decision"]["options"] if o["action_id"] == choice)
    assert op == ("use_wuxie" if expected == "YES" else "pass_trick_response")
    assert "public_nullification_protection_advice" in ai.last_trace["strategies"]
    assert current_answer(view, "jiedao_has_slash", respondent="p3") is None
    receipt = s.submit_action(sid, 2, view["decision"]["decision_id"], choice, "game-1")
    assert s.submit_action(sid, 2, view["decision"]["decision_id"], choice, "game-1")["duplicate"]
    assert session.accepted == before_steps + 1 and receipt["accepted_steps"] == before_steps + 1
    assert not session.questions[0]["valid"]
    assert current_answer(s.get_player_view(sid, 2), "nullification_protection", target="p3") is None


def test_no_response_is_unknown_and_context_cannot_be_reused():
    from copy import deepcopy
    s, sid, session = protection_fixture()
    ask, _, _ = ask_protection(s, sid)
    view = s.get_player_view(sid, 3)
    token = next(o["action_id"] for o in view["communication"]["options"] if o["answer"] == "NO_RESPONSE")
    with pytest.raises(RuntimeProtocolError, match="WRONG_ACTOR"):
        s.answer_question(sid, 1, ask["question_id"], token)
    with pytest.raises(RuntimeProtocolError, match="INVALID_ACTION"):
        s.answer_question(sid, 3, ask["question_id"], token + "x")
    s.answer_question(sid, 3, ask["question_id"], token)
    v = s.get_player_view(sid, 2)
    assert current_answer(v, "nullification_protection", target="p3") is None
    v["cooperation_history"][-1]["answer"] = "YES"  # 纯策略上下文负例。
    assert current_answer(v, "nullification_protection", target="p3") == "YES"
    for mutate in (lambda x: x["nullification"]["window"].update(layer=99),
                   lambda x: x["decision"].update(decision_id="new"),
                   lambda x: x["cooperation_history"][-1].update(target="p1"),
                   lambda x: x["cooperation_history"][-1].update(valid=False)):
        other = deepcopy(v); mutate(other)
        assert current_answer(other, "nullification_protection", target="p3") is None
    with pytest.raises(RuntimeProtocolError, match="LEGACY_SIGNAL_REMOVED"):
        s.submit_signal(sid, 2, "d", "token")


def test_same_advice_does_not_determine_private_response_cards():
    # YES也可表达希望保留响应资源；NO也可表达愿承伤保留队友无懈。
    answers = []
    for card in (None, "sgs_basic_sha"):
        s, sid, session = protection_fixture(response=card)
        ask_protection(s, sid)
        v = s.get_player_view(sid, 3)
        ai = ProductionAIController(parameters={"preservation": 3})
        low = json.loads(json.dumps(v)); next(p for p in low["players"] if p["id"] == "p3")["hp"] = 1
        assert ai.cooperation_answer(low, v["communication"]["question"]) == "YES"
        if card is None:
            assert ai.cooperation_answer(v, v["communication"]["question"]) == "NO"
        token = next(o["action_id"] for o in v["communication"]["options"] if o["answer"] == "YES")
        s.answer_question(sid, 3, v["communication"]["question"]["question_id"], token)
        answers.append([e for e in s.get_events(sid, 1)["events"] if e["type"] == "cooperation_answer"])
    assert answers[0] == answers[1]  # 同答案无不同私有理由、牌面或签名信息。


def test_mixed_ai_ask_stops_for_human_answer_and_ai_answer_has_time_slice():
    s, sid, session = protection_fixture()
    session.controllers["p2"] = ProductionAIController()
    assert s.advance_until_human_or_terminal(sid, max_steps=4)["stop"] == "HUMAN_ANSWER"
    assert session.game.actor == "p2"
    session.controllers["p3"] = ProductionAIController()
    before = session.accepted
    r = s.advance_until_human_or_terminal(sid, max_steps=1)
    assert r["stop"] == "YIELD" and r["advanced"] == 0 and r["communication_steps"] == 1
    assert session.accepted == before and session.questions[-1]["answer"] == "YES"


def test_baoxin_specific_proposition_and_probe_budget_only_scenario():
    s, sid, session = fixture({"p3": ["sgs_basic_sha"] * 2})
    plan = DistributionPlan("p2", "p3", "p1", ("p1", "p2", "p3"), proposed_count=2)
    q = plan.question()
    ai = ProductionAIController()
    v = s.get_player_view(sid, 3)
    assert ai.cooperation_answer(v, q) == "YES"
    assert ai.cooperation_answer(v, replace(plan, proposed_count=1).question()) == "NO"
    budget = ProbeBudget()
    budget.reserve(q, generation=1, hand_epoch=0)
    with pytest.raises(ValueError, match="枚举"):
        budget.reserve(replace(plan, proposed_count=1).question(), generation=2, hand_epoch=0)
    assert budget.permits(q, generation=3, hand_epoch=1)
    with pytest.raises(ValueError):
        replace(plan, proposed_count="杀数:2:桃").question()
    with pytest.raises(ValueError, match="完整|武将|不支持"):
        GameConfig(enabled_generals=("baoxin",))


def jiedao_fixture():
    s, sid, session = fixture({"p2": ["sgs_trick_jiedaosharen", "sgs_trick_huogong"],
                               "p3": ["sgs_basic_tao", "sgs_basic_shan"]}, actor="p2")
    core = session.game.core
    spear = next(c.instance_id for c in core.state.cards if c.card_key == "sgs_weapon_zhangbashemao")
    core._state = core.state.move_card(spear, ZoneRef.equipment("p3", "weapon"))
    return s, sid, session


def test_jiedao_requires_prior_public_knowledge_and_types_are_distinct():
    s, sid, session = jiedao_fixture()
    view = s.get_player_view(sid, 2)
    assert any(o["operation"] == "use_jiedao" for o in view["decision"]["options"])
    assert not view["communication"]["options"]  # 私下持有借刀不能借query传给队友。
    submit(s, sid, "use_fire_attack", target="p2")
    for _ in range(3):
        submit(s, sid, "pass_trick_response")
    submit(s, sid, "reveal_card_for_fire_attack")  # 唯一剩余手牌借刀：真实公开展示。
    submit(s, sid, "pass_fire_attack_discard")
    view = s.get_player_view(sid, 2)
    assert view["public_known_hand_keys"]["p2"] == ["sgs_trick_jiedaosharen"]
    c = view["communication"]
    topics = {o["question"]["topic"]: o for o in c["options"] if o["question"]["target"] == "p1"}
    assert set(topics) == {"jiedao_has_slash", "jiedao_can_supply", "jiedao_willing"}
    own = s.get_player_view(sid, 3)
    ai = ProductionAIController()
    assert ai.cooperation_answer(own, topics["jiedao_has_slash"]["question"]) == "NO"
    assert ai.cooperation_answer(own, topics["jiedao_can_supply"]["question"]) == "YES"  # 丈八能力不等于实体杀事实。
    assert ai.cooperation_answer(own, topics["jiedao_willing"]["question"]) == "YES"
    q = s.ask_question(sid, 2, c["decision_id"], topics["jiedao_willing"]["action_id"])
    v = s.get_player_view(sid, 3)
    s.answer_question(sid, 3, q["question_id"], ai.answer_question(v))
    current = s.get_player_view(sid, 2)
    assert current_answer(current, "jiedao_willing", target="p1") == "YES"
    assert current_answer(current, "jiedao_has_slash", target="p1") is None
    submit(s, sid, "use_jiedao", target="p1")
    # 无懈目标是持械者；真正的被杀目标不能覆盖锦囊效果目标。
    v = s.get_player_view(sid, 2)
    assert v["nullification"]["window"]["target"] == v["pending"]["target"] == "p3"
    assert v["pending"]["borrowed_sword_target"] == "p1"
    assert current_answer(v, "jiedao_willing", target="p1") is None


def _normalize(value):
    if isinstance(value, dict):
        return {k: _normalize(v) for k, v in value.items() if k not in {"ref", "action_id", "decision_id"}}
    if isinstance(value, list):
        return [_normalize(v) for v in value]
    return value


def test_hidden_hand_noninterference_with_equal_public_qa_and_observations(monkeypatch):
    cases = []
    for key in ("sgs_basic_sha", "sgs_basic_huosha"):
        s, sid, session = protection_fixture(response=key)
        ask, _, _ = ask_protection(s, sid)
        respondent = s.get_player_view(sid, 3)
        token = ProductionAIController().answer_question(respondent)
        s.answer_question(sid, 3, ask["question_id"], token)
        v = s.get_player_view(sid, 2)
        history = s.get_events(sid, 2)["events"]
        ai = ProductionAIController(seed=37)
        ai.observe(history)
        ai.choose(v)
        cases.append((_normalize(v), _normalize(history), _normalize(ai.last_trace)))
        # 视图读取和AI再次评分不得重新刷新读条知识。
        def forbidden(*args, **kwargs):
            raise AssertionError("普通轮询不得刷新隐藏资格")
        monkeypatch.setattr(session.information.nullification, "refresh_response_window", forbidden)
        ai.choose(s.get_player_view(sid, 2))
    assert cases[0] == cases[1]


def test_different_real_public_observation_may_change_ai_score():
    cases = []
    for key in ("sgs_basic_sha", "sgs_trick_wuxiekeji"):
        s, sid, session = fixture({"p1": ["sgs_trick_nanmanruqin", key], "p2": ["sgs_trick_wuxiekeji"]})
        submit(s, sid, "use_nanman")
        submit(s, sid, "pass_trick_response")
        v = s.get_player_view(sid, 2)
        ai = ProductionAIController(parameters={"tie_randomness": 0, "preservation": 2.7})
        token = ai.choose(v)
        cases.append((v["nullification"]["players"]["p1"]["availability"],
                      next(o["score"] for o in ai.last_trace["scores"] if o["strategy"] == "sgs_team_strategy.evaluate_nullification_decision"),
                      next(o["operation"] for o in v["decision"]["options"] if o["action_id"] == token)))
    assert cases[0][0] == "known_none" and cases[1][0] == "known_usable"
    assert cases[0][1] > cases[1][1]
    assert cases[0][2] == "use_wuxie" and cases[1][2] == "pass_trick_response"


def test_committed_action_receipt_recovers_after_qa_projection_failure(monkeypatch):
    s, sid, session = protection_fixture()
    ask, _, _ = ask_protection(s, sid)
    v = s.get_player_view(sid, 3)
    s.answer_question(sid, 3, ask["question_id"], ProductionAIController().answer_question(v))
    v = s.get_player_view(sid, 2)
    choice = next(o for o in v["decision"]["options"] if o["operation"] == "use_wuxie")
    before = session.accepted
    def fail(_):
        raise RuntimeError("命名负向：问答后游戏提交成功，投影失败")
    monkeypatch.setattr(s, "_capture_events", fail)
    with pytest.raises(RuntimeProtocolError, match="EVENT_PROJECTION_FAILED"):
        s.submit_action(sid, 2, v["decision"]["decision_id"], choice["action_id"], "once")
    recovered = s.submit_action(sid, 2, v["decision"]["decision_id"], choice["action_id"], "once")
    assert recovered["duplicate"] and session.accepted == before + 1


def test_real_cli_can_ask_and_answer_without_spending_game_action(monkeypatch):
    from scripts import sgs_playable as cli
    s, sid, session = protection_fixture()
    before = session.accepted
    monkeypatch.setattr(cli, "GameService", lambda: s)
    monkeypatch.setattr(s, "create_game", lambda config: sid)
    inputs = iter(["a 1", "3", "q"])
    output = []
    result = cli.run_interactive(session.game.config, input_fn=lambda _: next(inputs), output=output.append)
    assert result["status"] == "ABORTED" and result["steps"] == before
    assert any("公开询问 p2 → p3" in line for line in output)
    assert any("不回答／UNKNOWN" in line for line in output)


def test_unknown_gain_stays_unknown_until_next_real_response_window():
    s, sid, session = fixture({"p1": ["sgs_trick_wuzhongshengyou"] * 2})
    submit(s, sid, "use_wuzhong")
    first = s.get_player_view(sid, 1)["nullification"]["window"]["id"]
    for _ in range(3):
        submit(s, sid, "pass_trick_response")
    assert s.get_player_view(sid, 1)["nullification"]["players"]["p1"]["availability"] == "unknown"
    submit(s, sid, "use_wuzhong")
    v = s.get_player_view(sid, 1)["nullification"]
    assert v["window"]["id"] != first
    assert v["players"]["p1"]["availability"] in {"known_none", "known_usable"}


@pytest.mark.parametrize("target,topic", [("p3", "rescue_desire"), ("p2", "peach_available")])
def test_real_rescue_public_limited_question(target, topic):
    s, sid, session = fixture({"p1": ["sgs_basic_sha"], "p2": ["sgs_basic_tao"] if target == "p3" else [],
                               "p3": ["sgs_basic_tao"] if target == "p2" else []})
    core = session.game.core
    core._state = replace(core.state, players=tuple(replace(p, hp=1) if p.player_id == target else p for p in core.state.players))
    submit(s, sid, "use_slash", target=target)
    submit(s, sid, "pass_slash_response")
    submit(s, sid, "pass_rescue")
    v = s.get_player_view(sid, 2)
    c = v["communication"]
    option = next(o for o in c["options"] if o["question"]["topic"] == topic)
    q = s.ask_question(sid, 2, c["decision_id"], option["action_id"])
    own = s.get_player_view(sid, 3)
    s.answer_question(sid, 3, q["question_id"], ProductionAIController().answer_question(own))
    records = [s.get_player_view(sid, i)["cooperation_history"][-1] for i in (1, 2, 3)]
    assert records[0] == records[1] == records[2] and records[0]["answer"] == "YES"
    other_topic = "peach_available" if topic == "rescue_desire" else "rescue_desire"
    assert current_answer(s.get_player_view(sid, 2), other_topic, target=target) is None
    assert all("signals" not in s.get_player_view(sid, i) for i in (1, 2, 3))


def test_public_wugu_gain_shares_only_actual_public_card_fact():
    s, sid, session = fixture({"p1": ["sgs_trick_wugufengdeng"]})
    core = session.game.core
    pile = core.state.card_ids_in(DRAW_PILE)
    wuxie = next(cid for cid in pile if core.state.cards_by_id[cid].card_key == "sgs_trick_wuxiekeji")
    core._state = core.state.reorder_zone(DRAW_PILE, (wuxie, *(cid for cid in pile if cid != wuxie)))
    submit(s, sid, "use_wugu")
    for _ in range(3):
        submit(s, sid, "pass_trick_response")
    v = s.get_player_view(sid, 1)
    pick = next(o for o in v["decision"]["options"] if o["operation"] == "pick_wugu_card" and o["card"]["key"] == "sgs_trick_wuxiekeji")
    s.submit_action(sid, 1, v["decision"]["decision_id"], pick["action_id"])
    for seat in (1, 2, 3):
        events = s.get_events(sid, seat)["events"]
        assert any(e["type"] == "nullification_public_gain" and e["actor"] == "p1" for e in events)
        assert any(e["type"] == "card_gained" and e.get("card", {}).get("key") == "sgs_trick_wuxiekeji" for e in events)


def test_real_zuilun_consent_does_not_replace_game_choice_or_cost():
    s, sid, session = fixture({"p2": ["sgs_basic_sha", "sgs_basic_shan", "sgs_basic_tao", "sgs_basic_jiu", "sgs_trick_wuxiekeji"]},
                               actor="p2", generals=("zhugezhan",))
    submit(s, sid, "end_play_phase")
    while session.game.core.phase == ProductionPhase.DISCARD:
        v = s.get_player_view(sid, 2)
        op = "discard_phase_submit" if any(o["operation"] == "discard_phase_submit" for o in v["decision"]["options"]) else "select_discard_card"
        submit(s, sid, op)
    assert s.get_player_view(sid, 2)["pending"]["skill_facts"]["n"] == 0
    submit(s, sid, "activate_skill")
    v = s.get_player_view(sid, 2)
    qop = next(o for o in v["communication"]["options"] if o["question"]["topic"] == "skill_consent")
    hp = session.game.state.players_by_id["p3"].hp
    q = s.ask_question(sid, 2, v["communication"]["decision_id"], qop["action_id"])
    answer = s.get_player_view(sid, 3)["communication"]
    yes = next(o for o in answer["options"] if o["answer"] == "YES")
    s.answer_question(sid, 3, q["question_id"], yes["action_id"])
    assert session.game.state.players_by_id["p3"].hp == hp
    assert current_answer(s.get_player_view(sid, 2), "jiedao_has_slash", respondent="p3") is None
    submit(s, sid, "skill_lose_hp_target_choice", target="p3")
    assert session.game.state.players_by_id["p3"].hp == hp - 1
