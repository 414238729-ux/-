"""简易中文终端与生产并行模拟入口：python -m scripts.sgs_playable。"""

from __future__ import annotations

import argparse
from dataclasses import replace
import json
from pathlib import Path
import sys

from .sgs_engine.playable_config import GameConfig, MODE_SEATS, CONTROL_MODES, general_catalog
from .sgs_engine.playable_runtime import GameService, RuntimeProtocolError
from .sgs_engine.playable_simulator import SimulationConfig, run_simulation, semantic_results


def _json(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def _save(path: str, value: dict) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    # 每次运行由调用者指定新结果；拒绝覆盖历史证据。
    with target.open("x", encoding="utf-8") as output:
        json.dump(value, output, ensure_ascii=False, indent=2, allow_nan=False)
        output.write("\n")


def display_view(view: dict, output=print) -> None:
    def cards(values):
        return "、".join(c["name"] + c["suit"] + c["rank"] for c in values) or "无"
    output(f"\n模式 {view['mode']}｜第 {view['turn_number']} 回合｜{view['phase']}｜当前操作 {view['actor']}")
    for p in view["players"]:
        hand = f"手牌{p['hand_count']}张" if p["hand"] is None else "手牌：" + cards(p["hand"])
        output(f"{p['id']}（物理{p['physical_seat']}／当前{p['seat']}） "
               f"{p['general'] or '未公开武将'} {p['role'] or '隐藏身份'} "
               f"体力{p['hp']}/{p['max_hp']} {'存活' if p['alive'] else '已死亡'} "
               f"{'横置 ' if p['chained'] else ''}{hand}；装备 {cards(p['equipment'])}；判定 {cards(p['judgment'])}")
    if view["pending"]:
        output("当前结算：" + json.dumps(view["pending"], ensure_ascii=False))
    if view.get("nullification"):
        labels = {"unknown": "未知", "known_usable": "已知可用", "known_none": "已知无可用资格"}
        output("公开无懈知识：" + "，".join(pid + " " + labels[k["availability"]]
               for pid, k in view["nullification"]["players"].items()))
    communication = view.get("communication")
    if communication and communication["kind"] == "answer":
        q = communication["question"]
        output(f"公开询问 {q['asker']} → {q['respondent']}：{q['text']} 目标 {q['target']}；方案 {q['plan']}")
        for number, option in enumerate(communication["options"], 1):
            output(f"  {number}. {option['description']}")
    elif view["decision"]:
        for number, option in enumerate(view["decision"]["options"], 1):
            output(f"  {number}. {option['description']}")
        if communication:
            for number, option in enumerate(communication["options"], 1):
                q = option["question"]
                output(f"  a {number}. 公开问 {q['respondent']}：{q['text']} 目标 {q['target']}")


def run_interactive(config: GameConfig, *, input_fn=input, output=print) -> dict:
    service = GameService()
    sid = service.create_game(config)
    cursors = {seat: 0 for seat in range(1, len(config.player_ids) + 1)}
    output("座位编号为固定物理座位；开局叫价后同时显示当前座次。输入编号提交，q结束，v重看。")
    output("斗地主协作：有场景选项时输入 a 编号公开询问；队友选择YES、NO或不回答。")
    try:
        while service.get_result(sid)["status"] == "IN_PROGRESS":
            progress = service.advance_until_human_or_terminal(sid, max_steps=32, time_slice_ms=100)
            if progress["stop"] == "YIELD":
                continue
            if progress["stop"] == "TERMINAL":
                break
            seat = progress["seat"]
            view = service.get_player_view(sid, seat)
            events = service.get_events(sid, seat, cursors[seat])
            cursors[seat] = events["cursor"]
            for event in events["events"]:
                if event["type"] in ("card_used", "card_played", "damage", "hp_recover", "lose_hp", "death", "identity_revealed", "bid") or event["type"].startswith(("nullification_", "cooperation_")):
                    output("事件：" + json.dumps(event, ensure_ascii=False))
            if config.omniscient_debug:
                output("显式全手控全知观察：")
                for own_view in service.get_omniscient_debug_view(sid)["views"]:
                    p = next(p for p in own_view["players"] if p["id"] == own_view["viewer"])
                    output(json.dumps(p, ensure_ascii=False))
            display_view(view, output)
            answer = input_fn(f"p{seat} 请选择：").strip()
            if answer.lower() == "q":
                service.abort_game(sid)
                break
            if answer.lower() == "v":
                continue
            communication = view.get("communication")
            asking = answer.lower().startswith("a ")
            answering = communication and communication["kind"] == "answer"
            try:
                number = int(answer[2:] if asking else answer)
                if asking and (not communication or communication["kind"] != "ask"):
                    raise ValueError
                options = communication["options"] if asking or answering else view["decision"]["options"]
                if not 1 <= number <= len(options):
                    raise ValueError
            except ValueError:
                output("请输入列表中的编号、a 编号、v或q。")
                continue
            action = options[number - 1]
            try:
                if asking:
                    service.ask_question(sid, seat, communication["decision_id"], action["action_id"])
                elif answering:
                    service.answer_question(sid, seat, communication["question"]["question_id"], action["action_id"])
                else:
                    service.submit_action(sid, seat, view["decision"]["decision_id"], action["action_id"])
            except RuntimeProtocolError as exc:
                output(str(exc))
                if service.get_result(sid)["status"] == "ERROR":
                    break
        result = service.get_result(sid)
    except (KeyboardInterrupt, EOFError):
        result = service.abort_game(sid)
    finally:
        service.close_game(sid)
    output("对局结果：" + json.dumps(result, ensure_ascii=False))
    return result


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="三国杀生产后端：中文人工终端、AI自对弈、并行统计")
    sub = p.add_subparsers(dest="command", required=True)
    play = sub.add_parser("play", help="交互对局；全部AI时自动运行到终局或工程上限")
    play.add_argument("--config")
    play.add_argument("--mode", choices=MODE_SEATS)
    play.add_argument("--control", choices=CONTROL_MODES)
    play.add_argument("--human-seats", help="逗号分隔物理座位，例如1,4")
    play.add_argument("--seed", type=int)
    play.add_argument("--ai-seed", type=int)
    play.add_argument("--output", help="新建结果JSON，拒绝覆盖")
    for command in ("simulate", "compare-workers"):
        s = sub.add_parser(command, help="真实生产批量对局" if command == "simulate" else "实际执行1/N workers并比较逐局语义及统计")
        s.add_argument("--config", required=True)
        s.add_argument("--output", required=True, help="新建报告JSON，拒绝覆盖")
    sub.add_parser("catalog", help="列出完整生产武将及显式测试角色")
    return p


def main(argv=None) -> int:
    args = parser().parse_args(argv)
    try:
        if getattr(args, "output", None) and Path(args.output).exists():
            raise ValueError("输出文件已存在，请指定新路径，保留旧结果")
        if args.command == "catalog":
            print(json.dumps(general_catalog(), ensure_ascii=False, indent=2))
            return 0
        if args.command == "play":
            data = _json(args.config) if args.config else {}
            for key in ("mode", "control", "seed", "ai_seed"):
                if getattr(args, key) is not None:
                    data[key] = getattr(args, key)
            if args.human_seats is not None:
                data["human_seats"] = [int(x) for x in args.human_seats.split(",")]
            result = run_interactive(GameConfig.from_dict(data))
            if args.output:
                _save(args.output, result)
            return 0 if result["status"] in ("WIN", "DRAW") else 2
        cfg = SimulationConfig.from_dict(_json(args.config))
        if args.command == "simulate":
            report = run_simulation(cfg)
            _save(args.output, report)
            print(json.dumps({k: v for k, v in report["statistics"].items() if k != "by"}, ensure_ascii=False))
            return 0 if not report["statistics"]["errors"] and not report["statistics"]["aborted"] else 2
        if cfg.workers < 2:
            raise ValueError("比较需要workers至少为2")
        single, parallel = run_simulation(replace(cfg, workers=1)), run_simulation(cfg)
        same = (single["source_identity"] == parallel["source_identity"] and
                semantic_results(single) == semantic_results(parallel))
        report = {"schema": "production-worker-comparison-v1", "semantic_equal": same,
                  "single": single, "parallel": parallel}
        _save(args.output, report)
        print(f"逐局语义及统计相同：{same}；报告：{args.output}")
        return 0 if same and not single["statistics"]["errors"] and not single["statistics"]["aborted"] else 2
    except (ValueError, OSError, RuntimeError) as exc:
        print(f"执行失败：{type(exc).__name__}：{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
