"""三国杀权威核心的开发期命令行入口。

本入口只暴露测试专用单挑纵向切片及其严格重执行回放。输出中的
``test_only`` 和 ``formal_result`` 是不可省略的审计标记；这里不会计算或
输出任何胜率。
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
import sys
from typing import TextIO


# 同时支持 ``python -m scripts.sgs_dev_runner`` 与从仓库根目录直接执行文件。
if __package__ in {None, ""}:  # pragma: no cover - 子进程测试主要走 ``-m``
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.sgs_engine.duel_replay import (  # noqa: E402
    DuelReexecutionReplay,
    record_reference_duel,
    reexecute_duel_replay,
)


def _positive_int(raw: str) -> int:
    try:
        value = int(raw)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("必须是正整数") from exc
    if value < 1:
        raise argparse.ArgumentTypeError("必须是正整数")
    return value


def _field(container: object, *names: str) -> object:
    """从 dataclass/对象或映射读取第一个存在的字段，缺失时失败关闭。"""

    for name in names:
        if isinstance(container, Mapping) and name in container:
            return container[name]
        if hasattr(container, name):
            return getattr(container, name)
    joined = "、".join(names)
    raise ValueError(f"回放记录缺少必需字段：{joined}")


def _integer_field(container: object, *names: str) -> int:
    value = _field(container, *names)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"回放字段{name_or_names(names)}必须是非负整数")
    return value


def name_or_names(names: Sequence[str]) -> str:
    return "或".join(names)


def _text_field(container: object, *names: str) -> str:
    value = _field(container, *names)
    if not isinstance(value, str) or not value:
        raise ValueError(f"回放字段{name_or_names(names)}必须是非空字符串")
    return value


def _safety_step_limit(header: object) -> int:
    try:
        return _integer_field(header, "max_steps", "safety_step_limit")
    except ValueError as direct_error:
        for config_name in ("initial_configuration", "config"):
            try:
                config = _field(header, config_name)
                return _integer_field(config, "max_steps", "safety_step_limit")
            except ValueError:
                continue
        raise direct_error


def _base_summary(record: DuelReexecutionReplay) -> dict[str, object]:
    header = record.header
    outcome = record.outcome
    final_execution_hash = _text_field(outcome, "final_execution_hash")
    final_game_state_hash = _text_field(outcome, "final_game_state_hash")
    return {
        "test_only": True,
        "formal_result": False,
        "mode_id": _text_field(header, "mode_id"),
        "winner": _text_field(outcome, "winner_id"),
        "steps": _integer_field(outcome, "step_count"),
        "turns": _integer_field(outcome, "turn_count"),
        "decision_count": _integer_field(outcome, "decision_count"),
        "event_count": _integer_field(outcome, "event_count"),
        "random_consumption_count": _integer_field(
            outcome, "random_consumption_count"
        ),
        "final_hash": final_game_state_hash,
        "final_execution_hash": final_execution_hash,
        "final_game_state_hash": final_game_state_hash,
        "record_sha256": _text_field(record, "record_sha256"),
        "reexecution_replay_supported": True,
        # 两个零值只描述三牌纵向切片已经声明支持的范围，不得外推到正式牌堆。
        "unsupported_rules": 0,
        "approximation_count": 0,
        "safety_step_limit": _safety_step_limit(header),
    }


def _emit(payload: Mapping[str, object], stream: TextIO) -> None:
    json.dump(payload, stream, ensure_ascii=False, sort_keys=True, indent=2)
    stream.write("\n")


def _run_duel_smoke(args: argparse.Namespace) -> dict[str, object]:
    record = record_reference_duel(seed=args.seed, max_steps=args.max_steps)
    payload = {
        "ok": True,
        "command": "duel-smoke",
        **_base_summary(record),
    }
    if args.save_replay is not None:
        saved_path = record.save(args.save_replay)
        payload["saved_replay"] = str(Path(saved_path).resolve())
    return payload


def _run_replay(args: argparse.Namespace) -> dict[str, object]:
    record = DuelReexecutionReplay.load(args.path)
    verification = reexecute_duel_replay(record)
    verified = _field(verification, "verified")
    if verified is not True:
        raise RuntimeError("严格重执行未通过，拒绝输出伪造的验证结果")

    payload = {
        "ok": True,
        "command": "replay",
        **_base_summary(record),
        "verified": True,
        "replay_path": str(Path(args.path).resolve()),
    }

    # 验证结果必须与记录摘要一致；任何偏差都失败关闭。
    comparisons = {
        "winner": _text_field(verification, "winner_id"),
        "decision_count": _integer_field(verification, "decision_count"),
        "event_count": _integer_field(verification, "event_count"),
        "random_consumption_count": _integer_field(
            verification, "random_consumption_count"
        ),
        "final_execution_hash": _text_field(
            verification, "final_execution_hash"
        ),
        "final_game_state_hash": _text_field(
            verification, "final_game_state_hash"
        ),
    }
    for key, actual in comparisons.items():
        if payload[key] != actual:
            raise RuntimeError(f"严格重执行摘要不一致：{key}")
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sgs-dev-runner",
        description="运行测试专用三国杀单挑纵向切片或严格重执行回放。",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    smoke = subparsers.add_parser(
        "duel-smoke", help="运行一次测试专用单挑纵向切片"
    )
    smoke.add_argument("--seed", type=int, required=True, help="固定随机种子")
    smoke.add_argument(
        "--max-steps",
        type=_positive_int,
        default=500,
        help="动作安全上限（默认：500）",
    )
    smoke.add_argument(
        "--save-replay", type=Path, help="将严格重执行记录保存到指定路径"
    )
    smoke.set_defaults(handler=_run_duel_smoke)

    replay = subparsers.add_parser("replay", help="加载并严格重执行回放")
    replay.add_argument("path", type=Path, help="回放 JSON 文件")
    replay.set_defaults(handler=_run_replay)
    return parser


def _configure_utf8_console() -> None:
    """让 Windows 管道输出与回放 JSON 一样稳定使用 UTF-8。"""

    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="strict")


def main(argv: Sequence[str] | None = None) -> int:
    _configure_utf8_console()
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        payload = args.handler(args)
    except Exception as exc:  # CLI 边界必须将真实失败转换为非零退出码。
        _emit(
            {
                "ok": False,
                "test_only": True,
                "formal_result": False,
                "error_type": type(exc).__name__,
                "error": str(exc),
            },
            sys.stderr,
        )
        return 1
    _emit(payload, sys.stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
