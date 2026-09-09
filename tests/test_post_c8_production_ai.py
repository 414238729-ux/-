"""策略场景使用局面信息验证选择，不以小样本胜率要求AI获胜。"""
from copy import deepcopy
from dataclasses import replace

import pytest

from scripts.sgs_engine.playable_config import GameConfig, MODE_SEATS
from scripts.sgs_engine.playable_runtime import GameService
from scripts.sgs_engine.production_ai import ProductionAIController, AISchemaError
from scripts.sgs_engine.playable_view import OPERATION_LABELS
from scripts.sgs_engine.model import ZoneRef
from scripts.sgs_engine.production_batch import ProductionPhase


def card(key="sgs_basic_sha", name="杀", **kwargs):
    return {"ref": key, "key": key, "name": name, "suit": "♠", "color": "黑", "rank": "7",
            "category": "基本牌", "slot": None, "attack_range": None, **kwargs}


def option(op, *, target=None, c=None, skill=None, value=None, type="choose_option"):
    return {"schema": "production-action-option-v1", "action_id": "",
            "ordinal": 0, "operation": op, "type": type,
            "targets": [target] if target else [], "skill": skill, "card": c,
            "cost_cards": [], "selected_cards": [], "remaining_cards": [], "option": value,
            "zone": None, "virtual_key": None, "converted_to_fire": False,
            "description": OPERATION_LABELS.get(op, op)}


def scene(options, mode="2v2"):
    options = deepcopy(options)
    for i, o in enumerate(options):
        o["ordinal"] = i
        o["action_id"] = f"signed:{i}"
    players = [{"id": f"p{i}", "hp": 3, "max_hp": 4, "hand_count": 2, "hand": None,
                "alive": True, "chained": False, "equipment": [], "judgment": [],
                "role": "team_a" if i in (1, 4) else "team_b", "general": "shamoke",
                "attack_range": 1} for i in range(1, 5)]
    players[0]["hand"] = [card(), card("sgs_basic_shan", "闪")]
    players[3]["hand"] = []
    return {"schema": "player-view-v1", "mode": mode, "viewer": "p1", "actor": "p1",
            "players": players, "pending": {}, "decision": {"decision_id": "d", "options": options},
            "public_turn_use_counts": {"p1": 0}}


def chosen(view):
    ai = ProductionAIController(seed=7, parameters={"tie_randomness": 0})
    token = ai.choose(view)
    return next(o for o in view["decision"]["options"] if o["action_id"] == token), ai


def test_attack_enemy_and_prioritize_vulnerable_enemy():
    v = scene([option("use_slash", target=f"p{i}", c=card()) for i in (2, 3, 4)] + [option("end_play_phase")])
    v["players"][2]["hp"] = 1
    assert chosen(v)[0]["targets"] == ["p3"]
    v["players"][2]["role"] = "team_a"
    assert chosen(v)[0]["targets"] == ["p2"]


def test_lethal_response_and_known_rescue_prioritized():
    v = scene([option("pass_slash_response"), option("play_dodge", c=card("sgs_basic_shan", "闪"))])
    v["players"][0]["hp"] = 1
    v["pending"] = {"source": "p2", "target": "p1", "damage": 1}
    assert chosen(v)[0]["operation"] == "play_dodge"
    v = scene([option("pass_rescue"), option("rescue_with_peach", target="p4", c=card("sgs_basic_tao", "桃"))])
    v["players"][3]["hp"] = 0
    v["players"][0]["hand"] = [card("sgs_basic_tao", "桃")]
    v["pending"]["dying"] = "p4"
    picked, ai = chosen(v)
    assert picked["operation"] == "rescue_with_peach"
    assert "sgs_team_strategy.plan_team_rescue" in ai.last_trace["strategies"]
    v["players"][3]["role"] = "team_b"
    assert chosen(v)[0]["operation"] == "pass_rescue"


def test_nullification_parity_and_enemy_benefit():
    v = scene([option("pass_trick_response"), option("use_wuxie", c=card("sgs_trick_wuxiekeji", "无懈可击"))])
    v["pending"] = {"target": "p4", "card_key": "sgs_trick_juedou", "trick_active": True}
    assert chosen(v)[0]["operation"] == "use_wuxie"
    v["pending"]["trick_active"] = False
    assert chosen(v)[0]["operation"] == "pass_trick_response"
    v["pending"] = {"target": "p2", "card_key": "sgs_trick_wuzhongshengyou", "trick_active": True}
    assert chosen(v)[0]["operation"] == "use_wuxie"


def test_discard_harvest_and_skill_branch_use_hand_information():
    tao, junk = card("sgs_basic_tao", "桃"), card("sgs_delayed_shandian", "闪电")
    v = scene([option("select_discard_card", c=c) for c in (tao, junk)])
    assert chosen(v)[0]["card"]["key"] == junk["key"]
    v = scene([option("pick_wugu_card", c=c) for c in (junk, tao)])
    v["players"][0]["hp"] = 1
    assert chosen(v)[0]["card"]["key"] == tao["key"]
    v = scene([option("qianchong_choice", value=x) for x in ("basic", "trick", "equipment")])
    assert chosen(v)[0]["option"] == "basic"
    v["players"][0]["hand"] = [card("sgs_trick_wuzhongshengyou", "无中生有", category="锦囊牌")]
    assert chosen(v)[0]["option"] == "trick"


def test_pass_typed_activation_is_scored_as_activation():
    v = scene([option("weapon_force_hit", target="p2", type="pass"), option("pass_weapon_choice", type="pass")])
    v["players"][1]["hp"] = 1
    assert chosen(v)[0]["operation"] == "weapon_force_hit"


def test_unsafe_friendly_elemental_chain_changes_choice():
    v = scene([option("use_slash", target="p2", c=card("sgs_basic_huosha", "火杀")),
               option("use_slash", target="p2", c=card()), option("end_play_phase")])
    v["players"][1]["chained"] = True
    v["players"][3]["chained"] = True
    v["players"][3]["hp"] = 1
    assert chosen(v)[0]["card"]["key"] == "sgs_basic_sha"


def test_unknown_schema_and_operation_fail_locatably():
    v = scene([option("new_unsupported")])
    with pytest.raises(AISchemaError, match="new_unsupported"):
        chosen(v)
    v = scene([option("end_play_phase")])
    v["decision"]["options"][0]["new_field"] = 7
    with pytest.raises(AISchemaError, match="schema"):
        chosen(v)


def test_new_signatures_do_not_change_tied_semantic_choice():
    v = scene([option("select_discard_card", c=card()) for _ in range(4)])
    a, b = ProductionAIController(seed=21), ProductionAIController(seed=21)
    v2 = deepcopy(v)
    for i, o in enumerate(v2["decision"]["options"]):
        o["action_id"] = f"other-session:{3-i}"
        o["card"]["ref"] = f"other-card:{i}"
    for _ in range(8):
        a.choose(v); b.choose(v2)
        assert a.last_trace["chosen_ordinal"] == b.last_trace["chosen_ordinal"]


def test_borrowed_sword_uses_legally_shared_2v2_hand():
    a = option("use_jiedao", target="p4")
    a["targets"] = ["p4", "p2"]
    v = scene([a, option("end_play_phase")])
    v["players"][3]["hand"] = [card()]
    assert chosen(v)[0]["operation"] == "use_jiedao"
    v["players"][3]["hand"] = []
    assert chosen(v)[0]["operation"] == "end_play_phase"


@pytest.mark.parametrize("mode", MODE_SEATS)
def test_each_mode_short_real_production_ai_path(mode):
    service = GameService()
    sid = service.create_game(GameConfig(mode=mode, control="AI_VS_AI", mulligan=False))
    result = service.advance_until_human_or_terminal(sid, max_steps=28, time_slice_ms=10000)
    assert result["stop"] == "YIELD" and result["advanced"] + result["communication_steps"] == 28


def test_human_response_and_mixed_seats_route_current_actor():
    service = GameService()
    sid = service.create_game(GameConfig(mode="2v2", control="HUMAN_VS_AI", human_seats=(2, 4),
                                        enabled_generals=("soldier",), mulligan=False))
    session = service._sessions[sid]
    core = session.game.core
    sha = next(c.instance_id for c in core.state.cards if c.card_key == "sgs_basic_sha")
    core._state = core.state.move_card(sha, ZoneRef.hand("p1"))
    core._runtime = replace(core.runtime, phase=ProductionPhase.PLAY)
    view = service.get_player_view(sid, 1)
    attack = next(o for o in view["decision"]["options"] if o["operation"] == "use_slash" and o["targets"] == ["p2"])
    service.submit_action(sid, 1, view["decision"]["decision_id"], attack["action_id"])
    assert service.advance_until_human_or_terminal(sid) == {"stop": "HUMAN", "advanced": 0, "communication_steps": 0, "seat": 2}
    response = service.get_player_view(sid, 2)
    assert response["turn_player"] == "p1" and response["actor"] == "p2"
    assert service.get_player_view(sid, 1)["decision"] is None


def test_ai_step_slice_and_engine_cap_are_not_draws():
    service = GameService()
    sid = service.create_game(GameConfig(control="AI_VS_AI", max_steps=2, mulligan=False))
    assert service.advance_until_human_or_terminal(sid, max_steps=1)["advanced"] == 1
    service.advance_until_human_or_terminal(sid, max_steps=1)
    assert service.get_result(sid)["status"] == "ABORTED"
