"""同一生产引擎／ProductionAIController 的单进程与 Windows spawn 模拟。"""

from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, replace
from collections import Counter
import hashlib
import multiprocessing
import os
from pathlib import Path
import time
import traceback

from .engine import canonical_state_snapshot
from .playable_config import GameConfig, canonical, integer
from .playable_runtime import GameService
from .playable_information import INFORMATION_VERSION


REPO_ROOT = Path(__file__).resolve().parents[2]
CLAIM = "该规则、对手分布与AI策略下的模拟胜率；不是武将绝对强度或真人胜率"


def source_identity() -> dict:
    """保守源码包：含所有 scripts 代码及 Knowledge，覆盖动态 import 与CSV。

    不将旧 pin 当作新权限；新源码每次运行重新派生，不写回旧 manifest。
    """
    inventory = {}
    for folder in ("scripts", "knowledge"):
        for path in sorted((REPO_ROOT / folder).rglob("*")):
            if path.is_file() and path.suffix in (".py", ".csv", ".md", ".json"):
                rel = path.relative_to(REPO_ROOT).as_posix()
                inventory[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    return {"schema": "post-c8-development-source-v1", "files": inventory,
            "sha256": hashlib.sha256(canonical(inventory).encode()).hexdigest()}


@dataclass(frozen=True)
class SimulationConfig:
    game: GameConfig
    games: int = 1
    seeds: tuple[int, ...] = ()
    workers: int = 1

    def __post_init__(self):
        if type(self.game) is not GameConfig:
            raise ValueError("game必须为GameConfig")
        if self.game.control != "AI_VS_AI" or self.game.omniscient_debug:
            raise ValueError("统计模拟必须使用AI_VS_AI与正常信息边界")
        integer(self.games, "请求局数", 1)
        integer(self.workers, "worker数", 1)
        if not isinstance(self.seeds, (tuple, list)):
            raise ValueError("seed清单必须为整数列表")
        for seed in self.seeds:
            integer(seed, "单局seed")
        if self.seeds and len(self.seeds) != self.games:
            raise ValueError("seed清单长度必须等于请求局数")
        object.__setattr__(self, "seeds", tuple(self.seeds) or tuple(range(self.game.seed, self.game.seed + self.games)))

    def to_dict(self) -> dict:
        return {"game": self.game.to_dict(), "games": self.games, "seeds": list(self.seeds), "workers": self.workers}

    @classmethod
    def from_dict(cls, value: dict) -> "SimulationConfig":
        if type(value) is not dict or set(value) - {"game", "games", "seeds", "workers"} or "game" not in value:
            raise ValueError("批量配置必须含game，其他允许字段为games、seeds、workers")
        return cls(game=GameConfig.from_dict(value["game"]), **{k: v for k, v in value.items() if k != "game"})


def build_jobs(config: SimulationConfig) -> list[dict]:
    occurrences = Counter()
    jobs = []
    for index, seed in enumerate(config.seeds):
        # 游戏seed绝不混入AIseed。每局重新创建同一指定策略随机流；
        # 选择随该局合法局势变化，控制器无法从传入的策略seed枚举游戏seed。
        game = replace(config.game, seed=seed)
        identity = {"schema": "production-game-v1", "game": game.to_dict(), "occurrence": occurrences[seed]}
        occurrences[seed] += 1
        jobs.append({"game_id": hashlib.sha256(canonical(identity).encode()).hexdigest(),
                     "index": index, "seed": seed, "game": game.to_dict()})
    return jobs


def _initialize_worker(expected_source: str) -> None:
    if source_identity()["sha256"] != expected_source:
        raise RuntimeError("WORKER_SOURCE_DRIFT：worker启动时源码与派发源码不同")


def _failure(job: dict, exc: BaseException, *, steps: int = 0, phase: str | None = None,
             decision: int | None = None) -> dict:
    return {"game_id": job["game_id"], "index": job["index"], "seed": job["seed"],
            "status": "ERROR", "winner": None, "winning_players": [], "participants": [],
            "steps": steps, "error": {"type": type(exc).__name__, "message": str(exc),
                "phase": phase, "decision": decision,
                "traceback": "".join(traceback.format_exception(exc))[-6000:]}}


def _participants(game) -> list[dict]:
    roles = game.current_roles()
    return [{"player": p.player_id, "physical_seat": int(p.player_id[1:]), "seat": p.seat,
        "general": game.selected.get(p.player_id), "role": roles.get(p.player_id, p.player_id),
        "initial_role": game.roles.get(p.player_id, p.player_id),
        "team": ("lord_and_loyalists" if roles.get(p.player_id) in ("lord", "loyalist")
                 else "rebels" if roles.get(p.player_id) == "rebel" else roles.get(p.player_id, p.player_id))}
        for p in game.state.players]


def run_game_job(job: dict) -> dict:
    """模块顶层worker函数；每次任务独立创建控制器、注册表、随机流和会话。"""
    start = time.perf_counter()
    service = GameService()
    sid = None
    try:
        cfg = GameConfig.from_dict(job["game"])
        sid = service.create_game(cfg)
        while service.get_result(sid)["status"] == "IN_PROGRESS":
            service.advance_until_human_or_terminal(sid, max_steps=64, time_slice_ms=1000)
        session = service._sessions[sid]
        game = session.game
        result = service.get_result(sid)
        result.update(game_id=job["game_id"], index=job["index"], seed=job["seed"],
            participants=_participants(game), steps=session.accepted,
            semantic_trace_sha256=session.semantic_digest.hexdigest(),
            information_version=INFORMATION_VERSION,
            public_information_sha256=session.public_information_digest.hexdigest(),
            public_information_counts=dict(sorted(session.public_information_counts.items())),
            final_state_sha256=hashlib.sha256(canonical(canonical_state_snapshot(game.state)).encode()).hexdigest(),
            spy_duel_reached=session.spy_duel_reached,
            actual_strategies=sorted({strategy for controller in session.controllers.values()
                for strategy in getattr(controller, "used_strategies", ())}),
            selected_operations={pid: dict(getattr(controller, "selected_operations", {}))
                for pid, controller in session.controllers.items()})
    except Exception as exc:
        session = service._sessions.get(sid)
        result = _failure(job, exc, steps=session.accepted if session else 0,
            phase=(session.game.core.phase.value if session.game.core else session.game.stage) if session else None,
            decision=session.generation if session else None)
        if session:
            result["participants"] = _participants(session.game)
    finally:
        if sid is not None:
            service.close_game(sid)
    result["metadata"] = {"pid": os.getpid(), "elapsed_seconds": time.perf_counter() - start}
    return result


def _increment(row: dict, status: str, won: bool) -> None:
    row["appearances"] += 1
    if status in ("WIN", "DRAW"):
        row["completed"] += 1
        row["wins"] += int(won)
        row["draws"] += int(status == "DRAW")
        row["losses"] += int(status == "WIN" and not won)
    else:
        row["errors" if status == "ERROR" else "aborted"] += 1


def aggregate_results(results: list[dict], requested: int, mode: str) -> dict:
    if len(results) != requested or len({r["game_id"] for r in results}) != requested:
        raise ValueError("结果必须逐game_id完整覆盖请求局数，不能重复或丢失")
    counts = Counter(r["status"] for r in results)
    if set(counts) - {"WIN", "DRAW", "ERROR", "ABORTED"}:
        raise ValueError("统计结果含未知终局状态")
    groups = {key: {} for key in ("general", "seat", "physical_seat", "role", "initial_role", "team", "general_role")}
    empty = {"appearances": 0, "completed": 0, "wins": 0, "losses": 0, "draws": 0, "errors": 0, "aborted": 0}
    winners = Counter()
    for result in results:
        if result["status"] == "WIN":
            winners[result["winner"]] += 1
        teams_seen = set()
        for p in result["participants"]:
            won = p["player"] in result["winning_players"]
            for dimension, rows in groups.items():
                value = (f"{p['general']}|{p['initial_role']}" if dimension == "general_role" else str(p[dimension]))
                if dimension == "team":
                    if value in teams_seen:
                        continue
                    teams_seen.add(value)
                    won_team = result["status"] == "WIN" and result["winner"] == p["team"]
                else:
                    won_team = won
                row = rows.setdefault(value, dict(empty))
                _increment(row, result["status"], won_team)
    for rows in groups.values():
        for row in rows.values():
            row["win_rate"] = row["wins"] / row["completed"] if row["completed"] else None
    completed = counts["WIN"] + counts["DRAW"]
    summary = {"requested": requested, "completed": completed, "wins": counts["WIN"],
        "draws": counts["DRAW"], "errors": counts["ERROR"], "aborted": counts["ABORTED"],
        "winners_by_game": dict(sorted(winners.items())), "by": groups,
        "denominator": "win_rate=获胜出场/自然完成出场（含规则平局）；异常及工程上限中止均排除。team每局每队只计一次。",
        "claim": CLAIM}
    if mode == "doudizhu":
        values = {}
        for general in groups["general"]:
            l = groups["general_role"].get(f"{general}|landlord", {}).get("win_rate")
            f = groups["general_role"].get(f"{general}|peasants", {}).get("win_rate")
            values[general] = {"L": l, "F": f, "S_raw": (l + f) / 2 if l is not None and f is not None else None,
                               "S_selectable": (l + f) / 2 if l is not None and f is not None else None,
                               "suitability_adjustment": "未启用；没有额外技能结构证据不自行修正"}
        summary["doudizhu_by_general"] = values
    if mode == "identity8":
        finished = [r for r in results if r["status"] in ("WIN", "DRAW")]
        spy_wins = sum(r["winner"] == "spy" for r in finished)
        reached = sum(r.get("spy_duel_reached", False) for r in finished)
        reward = sum(3 if r["winner"] == "spy" else int(r.get("spy_duel_reached", False)) for r in finished)
        summary["spy_statistics"] = {"completed_games": completed, "actual_wins": spy_wins,
            "raw_win_rate": spy_wins / completed if completed else None,
            "lord_spy_duel_games": reached, "lord_spy_duel_probability": reached / completed if completed else None,
            "server_reward_points": reward, "server_reward_mean": reward / completed if completed else None,
            "rule": "实际获胜3分，否则曾进入主内单挑1分，其余0分；互斥计分，不是胜率"}
    return summary


def semantic_results(report: dict) -> dict:
    return {"results": [{k: v for k, v in result.items() if k != "metadata"} for result in report["results"]],
            "statistics": report["statistics"]}


def run_simulation(config: SimulationConfig) -> dict:
    start = time.perf_counter()
    source = source_identity()
    jobs = build_jobs(config)
    if config.workers == 1:
        _initialize_worker(source["sha256"])
        results = [run_game_job(job) for job in jobs]
    else:
        results = []
        with ProcessPoolExecutor(max_workers=config.workers,
            mp_context=multiprocessing.get_context("spawn"), initializer=_initialize_worker,
            initargs=(source["sha256"],)) as pool:
            futures = {}
            for job in jobs:
                try:
                    futures[pool.submit(run_game_job, job)] = job
                except Exception as exc:
                    failed = _failure(job, exc)
                    failed["metadata"] = {"pid": None, "elapsed_seconds": None}
                    results.append(failed)
            for future in as_completed(futures):
                job = futures[future]
                try:
                    results.append(future.result())
                except Exception as exc:
                    failed = _failure(job, exc)
                    failed["metadata"] = {"pid": None, "elapsed_seconds": None}
                    results.append(failed)
    results.sort(key=lambda item: item["index"])
    post_source = source_identity()
    if source["sha256"] != post_source["sha256"]:
        raise RuntimeError("SOURCE_DRIFT：模拟期间源码变化，不能发布为同一实现结果")
    return {"schema": "production-simulation-v1", "config": config.to_dict(),
        "source_identity": source, "source_after_sha256": post_source["sha256"],
        "results": results, "statistics": aggregate_results(results, config.games, config.game.mode),
        "elapsed_seconds": time.perf_counter() - start,
        "assumptions": [CLAIM, "启用池及候选数为自用配置，候选等概率是假设，不代表客户端真实出现权重。",
            "固定阵容允许重复武将用于自用对照；随机候选为各座位启用池的无放回子集，不模拟账号或官方将池。",
            "2v2／斗地主耗尽平局；身份场观看／亮牌／判定彻底不足按项目分析约定平局。",
            "不加载墙钟评分胜负；工程动作上限独立记ABORTED。"]}
