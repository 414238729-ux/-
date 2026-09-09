"""短验收：实际Windows spawn、同seed语义、自然终局与失败分母。"""
from dataclasses import replace
import os

import pytest

from scripts.sgs_engine.playable_config import GameConfig
from scripts.sgs_engine import playable_simulator as sim


def _failing_initializer(*args):
    raise RuntimeError("命名负向场景：worker初始化失败")


def test_windows_spawn_same_game_semantics_and_natural_result():
    cfg = sim.SimulationConfig(GameConfig(control="AI_VS_AI", mulligan=False, max_steps=1200),
                               games=2, seeds=(0, 1), workers=1)
    single = sim.run_simulation(cfg)
    multi = sim.run_simulation(replace(cfg, workers=2))
    assert sim.semantic_results(single) == sim.semantic_results(multi)
    assert single["statistics"]["completed"] == 2, single["results"]
    assert single["statistics"]["errors"] == single["statistics"]["aborted"] == 0
    assert all(r["metadata"]["pid"] != os.getpid() for r in multi["results"])
    assert len({r["metadata"]["pid"] for r in multi["results"]}) == 2
    assert sum(single["statistics"]["winners_by_game"].values()) == single["statistics"]["wins"]
    assert single["statistics"]["wins"] + single["statistics"]["draws"] == 2
    assert any("sgs_card_strategy" in name for r in single["results"] for name in r["actual_strategies"])


def test_game_ids_and_randomness_exclude_workers_completion_order_and_list_size():
    cfg = sim.SimulationConfig(GameConfig(control="AI_VS_AI"), games=3, seeds=(7, 8, 7))
    a = sim.build_jobs(cfg)
    assert len({j["game_id"] for j in a}) == 3
    assert a[0]["game"] == a[2]["game"]
    assert a[0]["game"]["ai_seed"] == a[1]["game"]["ai_seed"] == cfg.game.ai_seed
    assert a == sim.build_jobs(replace(cfg, workers=3))
    short = sim.build_jobs(replace(cfg, games=1, seeds=(7,)))
    assert a[0] == short[0]


def test_doudizhu_public_observations_and_questions_match_spawn_workers():
    # 有意使用工程上限的短确定性回归，不把未自然完成的局算成平局。
    cfg = sim.SimulationConfig(GameConfig(mode="doudizhu", control="AI_VS_AI", mulligan=False,
        landlord_seat=1, ai_seed=7, max_steps=250), games=2, seeds=(0, 1), workers=1)
    single = sim.run_simulation(cfg)
    multi = sim.run_simulation(replace(cfg, workers=2))
    assert sim.semantic_results(single) == sim.semantic_results(multi)
    assert single["statistics"]["errors"] == 0, single["results"]
    counts = [r["public_information_counts"] for r in single["results"]]
    assert sum(c.get("nullification_observation", 0) for c in counts) > 0
    assert all(r["public_information_sha256"] for r in multi["results"])
    assert len({r["metadata"]["pid"] for r in multi["results"]}) == 2


def _cooperation_scenario_job(index):
    """命名锦囊窗口fixture，之后由同一生产AI推进；不是自然发牌覆盖声明。"""
    from test_post_c8_information import protection_fixture
    key = "sgs_trick_nanmanruqin" if index == 0 else "sgs_trick_wanjianqifa"
    s, sid, session = protection_fixture(key, control="AI_VS_AI")
    start = session.accepted
    for _ in range(32):
        if session.accepted >= start + 24 or s.get_result(sid)["status"] != "IN_PROGRESS":
            break
        s.advance_until_human_or_terminal(sid, max_steps=3, time_slice_ms=1000)
    result = s.abort_game(sid)
    result.update(game_id=f"public-qa-fixture:{index}", participants=sim._participants(session.game),
        semantic_trace_sha256=session.semantic_digest.hexdigest(),
        public_information_sha256=session.public_information_digest.hexdigest(),
        public_information_counts=session.public_information_counts,
        public_events=[e for e in s.get_events(sid, 1)["events"] if e["type"].startswith(("cooperation_", "nullification_"))])
    for seat in (2, 3):
        assert result["public_events"] == [e for e in s.get_events(sid, seat)["events"] if e["type"].startswith(("cooperation_", "nullification_"))]
    s.close_game(sid)
    return result


def test_named_public_qa_scenarios_same_results_events_and_statistics_with_spawn():
    import multiprocessing
    from concurrent.futures import ProcessPoolExecutor
    single = [_cooperation_scenario_job(i) for i in range(2)]
    with ProcessPoolExecutor(2, mp_context=multiprocessing.get_context("spawn")) as pool:
        multiple = list(pool.map(_cooperation_scenario_job, range(2)))
    assert single == multiple
    assert sim.aggregate_results(single, 2, "doudizhu") == sim.aggregate_results(multiple, 2, "doudizhu")
    for r in single:
        assert r["public_information_counts"]["cooperation_question"] >= 1
        assert r["public_information_counts"]["cooperation_answer"] >= 1
        assert r["public_information_counts"]["nullification_observation"] >= 2


def test_actual_spawn_worker_exception_reported_without_fabricated_loss(monkeypatch):
    original = sim.build_jobs
    def invalid_jobs(config):
        jobs = original(config)
        jobs[0]["game"]["mode"] = "named_invalid_worker_config"
        return jobs
    monkeypatch.setattr(sim, "build_jobs", invalid_jobs)
    cfg = sim.SimulationConfig(GameConfig(control="AI_VS_AI", max_steps=2), games=2, workers=2)
    report = sim.run_simulation(cfg)
    assert [r["status"] for r in report["results"]] == ["ERROR", "ABORTED"]
    assert report["results"][0]["metadata"]["pid"] != os.getpid()
    assert "named_invalid_worker_config" in report["results"][0]["error"]["message"]
    assert report["statistics"]["completed"] == 0
    assert report["statistics"]["wins"] == report["statistics"]["draws"] == 0


def test_actual_spawn_initializer_failure_accounts_for_every_job(monkeypatch):
    monkeypatch.setattr(sim, "_initialize_worker", _failing_initializer)
    cfg = sim.SimulationConfig(GameConfig(control="AI_VS_AI"), games=3, workers=2)
    report = sim.run_simulation(cfg)
    assert report["statistics"]["errors"] == 3
    assert all(r["error"]["type"] == "BrokenProcessPool" for r in report["results"])


def _result(index, status, winner=None, *, roles=("landlord", "peasants", "peasants"), duel=False):
    ps = [{"player": f"p{i+1}", "seat": i+1, "physical_seat": i+1,
           "general": "shamoke", "role": role, "initial_role": role, "team": role}
          for i, role in enumerate(roles)]
    return {"game_id": str(index), "status": status, "winner": winner,
            "winning_players": [p["player"] for p in ps if status == "WIN" and p["team"] == winner],
            "participants": ps, "spy_duel_reached": duel}


def test_team_count_role_denominators_and_doudizhu_formula():
    rows = [_result(0, "WIN", "peasants"), _result(1, "WIN", "landlord"),
            _result(2, "DRAW"), _result(3, "ERROR"), _result(4, "ABORTED")]
    s = sim.aggregate_results(rows, 5, "doudizhu")
    assert (s["completed"], s["wins"], s["draws"], s["errors"], s["aborted"]) == (3, 2, 1, 1, 1)
    assert s["by"]["team"]["peasants"]["appearances"] == 5
    assert s["by"]["team"]["peasants"]["wins"] == 1
    assert s["by"]["role"]["peasants"]["wins"] == 2
    assert s["doudizhu_by_general"]["shamoke"]["L"] == pytest.approx(1/3)
    assert s["doudizhu_by_general"]["shamoke"]["F"] == pytest.approx(1/3)
    assert s["doudizhu_by_general"]["shamoke"]["S_raw"] == pytest.approx(1/3)
    with pytest.raises(ValueError, match="重复或丢失"):
        sim.aggregate_results(rows + rows[:1], 6, "doudizhu")


def test_spy_reward_mutually_exclusive_and_not_loaded_for_variant():
    roles = ("lord", "spy")
    rows = [_result(0, "WIN", "spy", roles=roles, duel=True),
            _result(1, "WIN", "lord", roles=roles, duel=True), _result(2, "DRAW", roles=roles),
            _result(3, "ABORTED", roles=roles, duel=True)]
    s = sim.aggregate_results(rows, 4, "identity8")["spy_statistics"]
    assert s["server_reward_points"] == 4
    assert s["actual_wins"] == 1 and s["lord_spy_duel_games"] == 2 and s["completed_games"] == 3
    assert "spy_statistics" not in sim.aggregate_results(rows, 4, "identity8_heir")
