"""三国杀正式模拟的失败关闭入口。

精确模式 ``formal_160_card_no_skill_duel`` 的状态与门禁来自生产核心提供的
``inspect_formal_duel_readiness`` 现场检查；调用方提交的 capability 布尔值或
计数不能授予正式资格。其他历史模式继续使用原有失败关闭 manifest 契约。
任何真实 blocker 存在时都不会创建结果文件，也不会降级到近似器。

本模块只引用仓库内的牌堆加载器和正式门禁，不导入仓库外部程序。
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from .deck_data import load_deck_csv
from .sgs_engine.formal_duel import (
    FormalDuelConfiguration,
    FormalDuelReadiness,
    build_formal_acceptance_artifact,
    inspect_formal_duel_readiness,
    run_formal_duel_seed_sweep,
)
from .sgs_engine.production_batch import FORMAL_NO_SKILL_DUEL_MODE
from .sgs_engine_gate import (
    DeckReadiness,
    EngineSourceReadiness,
    FormalSimulationBlockedError,
    FormalSimulationExecutionFailedError,
    FormalSimulationManifest,
    GeneralReadiness,
    evaluate_formal_run_gate,
    inspect_engine_source,
    require_formal_simulation_ready,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
FORMAL_DECK_PATH = REPOSITORY_ROOT / "knowledge" / "三国杀牌堆数据.csv"
STATUS_SCHEMA_VERSION = "sgs-formal-runner-status-v1"
FORMAL_RESULT_SCHEMA_VERSION = "sgs-formal-duel-result-v1"


@dataclass(frozen=True)
class CoreFoundationReadiness:
    """权威核心基础设施的实际导入与最小自检结果。"""

    available: bool
    module_path: str | None
    source_sha256: str | None
    issues: tuple[str, ...]


def _nonempty(value: str, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label}必须是非空字符串")
    return value.strip()


def _normalise_generals(general_names: Sequence[str]) -> tuple[str, ...]:
    names = tuple(_nonempty(name, "武将名称") for name in general_names)
    if len(names) != len(set(names)):
        raise ValueError("参战武将名称不能重复")
    return names


def _inspect_formal_duel_safely(
) -> tuple[FormalDuelReadiness | None, str | None]:
    """现场读取 canonical readiness；任何损坏均结构化失败关闭。"""

    try:
        readiness = inspect_formal_duel_readiness()
    except Exception as exc:
        return None, f"{type(exc).__name__}:{exc}"
    if not isinstance(readiness, FormalDuelReadiness):
        return None, "canonical inspector返回了错误的结果类型"
    return readiness, None


def _load_current_deck() -> tuple[DeckReadiness, str, tuple[str, ...]]:
    """从正式 Knowledge 路径加载牌堆并返回门禁状态、哈希和问题。"""

    try:
        records, audit = load_deck_csv(FORMAL_DECK_PATH, expected_total=160)
        raw = FORMAL_DECK_PATH.read_bytes()
    except Exception as exc:  # 状态入口必须把数据损坏转换为结构化阻塞。
        return (
            DeckReadiness(loaded=False, card_count=0, unique_instance_ids=False),
            "",
            (f"error:deck_load_failed:{type(exc).__name__}:{exc}",),
        )

    instance_ids = tuple(record.instance_id for record in records)
    unique_ids = (
        len(instance_ids) == len(set(instance_ids))
        and all(instance_id.strip() for instance_id in instance_ids)
    )
    issues = [
        f"{issue.severity}:{issue.code}:{issue.message}" for issue in audit.issues
    ]
    if len(records) != 160 or audit.total_quantity != 160:
        issues.append(
            "error:formal_deck_count:"
            f"正式牌堆必须为160张；记录数={len(records)}，quantity合计={audit.total_quantity}"
        )
    if not unique_ids:
        issues.append("error:instance_id:正式牌堆实体ID为空或重复")
    readiness = DeckReadiness(
        loaded=audit.is_valid and len(records) == 160 and unique_ids,
        card_count=audit.total_quantity,
        unique_instance_ids=unique_ids,
    )
    return readiness, hashlib.sha256(raw).hexdigest(), tuple(issues)


def inspect_authoritative_core_foundation() -> CoreFoundationReadiness:
    """实际导入核心包并执行无对局、无近似的最小确定性自检。

    该结果只表示基础类型可导入和随机流可复现，不表示卡牌、模式、武将、
    AI 或完整 ``run_game`` 已实现。
    """

    issues: list[str] = []
    module_path: str | None = None
    digest: str | None = None
    try:
        core = importlib.import_module("scripts.sgs_engine")
        raw_path = getattr(core, "__file__", None)
        if not raw_path:
            issues.append("权威核心模块没有可审计的源文件路径")
        else:
            resolved = Path(raw_path).resolve(strict=False)
            module_path = str(resolved)
            canonical_root = (REPOSITORY_ROOT / "scripts" / "sgs_engine").resolve()
            if not resolved.is_file() or canonical_root not in resolved.parents:
                issues.append("导入的sgs_engine不来自正式仓库核心目录")
            else:
                digest = hashlib.sha256(resolved.read_bytes()).hexdigest()

        required = (
            "AuthoritativeCoreSession",
            "CardInstance",
            "PlayerState",
            "GameState",
            "EventQueue",
            "ResponseWindow",
            "DamageEvent",
            "LegalAction",
            "DeterministicRNG",
            "ReplayRecord",
            "enumerate_legal_actions",
            "UnsupportedRuleError",
        )
        missing = tuple(name for name in required if not hasattr(core, name))
        if missing:
            issues.append("权威核心公共接口缺失：" + "、".join(missing))

        rng_type = getattr(core, "DeterministicRNG", None)
        if rng_type is not None:
            first = rng_type(20260801)
            second = rng_type(20260801)
            first_values = (first.random(), first.randint(1, 1000))
            second_values = (second.random(), second.randint(1, 1000))
            if first_values != second_values:
                issues.append("确定性随机最小复现检查失败")
    except Exception as exc:
        issues.append(f"权威核心导入或最小自检失败：{type(exc).__name__}:{exc}")

    return CoreFoundationReadiness(
        available=not issues,
        module_path=module_path,
        source_sha256=digest,
        issues=tuple(issues),
    )


def build_current_manifest(
    *,
    mode_name: str,
    general_names: Sequence[str] = (),
) -> FormalSimulationManifest:
    """根据当前仓库真实能力建立正式模拟门禁清单。

    精确正式单挑的字段来自 canonical inspector；这些字段只是状态展示，
    最终 gate 会再次现场检查而不信任本对象。其他模式保持原有 blocked
    manifest 行为。
    """

    mode = _nonempty(mode_name, "模式名称")
    names = _normalise_generals(general_names)
    source = inspect_engine_source(
        repository_root=REPOSITORY_ROOT,
        entrypoint_path=Path(__file__),
    )
    if mode == FORMAL_NO_SKILL_DUEL_MODE:
        readiness, inspection_error = _inspect_formal_duel_safely()
        return _build_formal_duel_manifest(
            mode=mode,
            names=names,
            source=source,
            readiness=readiness,
            inspection_error=inspection_error,
        )

    deck, _, _ = _load_current_deck()
    return FormalSimulationManifest(
        mode_name=mode,
        ruleset_version=None,
        unsupported_rules=1,
        approximation_count=0,
        mode_implemented=False,
        ai_implemented=False,
        generals=tuple(
            GeneralReadiness(
                general_name=name,
                implemented=False,
                deterministic_tests_passed=False,
            )
            for name in names
        ),
        deck=deck,
        source=source,
    )


def _build_formal_duel_manifest(
    *,
    mode: str,
    names: tuple[str, ...],
    source: EngineSourceReadiness,
    readiness: FormalDuelReadiness | None,
    inspection_error: str | None,
) -> FormalSimulationManifest:
    """把一次现场结果投影为兼容 manifest；gate 不信任该投影。"""

    if readiness is None:
        deck, _, _ = _load_current_deck()
        unsupported_rules = 1
        approximation_count = 0
        mode_implemented = False
        controller_implemented = False
    else:
        deck = DeckReadiness(
            loaded=(
                readiness.deck_count == 160
                and readiness.registered_instance_count == 160
            ),
            card_count=readiness.deck_count,
            unique_instance_ids=(
                readiness.registered_instance_count == readiness.deck_count
            ),
        )
        unsupported_rules = readiness.unsupported_rules
        approximation_count = readiness.approximation_count
        mode_implemented = readiness.mode_implemented
        controller_implemented = readiness.deterministic_controller_implemented
    # ``inspection_error`` 只决定失败关闭投影；详细错误由 status 与现场 gate
    # 输出。这里显式引用，避免误把 inspector 异常当成无 blocker。
    if inspection_error is not None:
        unsupported_rules = max(1, unsupported_rules)
    return FormalSimulationManifest(
        mode_name=mode,
        # 正式单挑规则 profile 尚未确认；不得用实现版本冒充规则版本。
        ruleset_version=None,
        unsupported_rules=unsupported_rules,
        approximation_count=approximation_count,
        mode_implemented=mode_implemented,
        # 兼容旧 manifest 字段：这里表示确定性验收控制器可达，不宣称竞技AI。
        ai_implemented=controller_implemented,
        generals=tuple(
            GeneralReadiness(
                general_name=name,
                implemented=False,
                deterministic_tests_passed=False,
            )
            for name in names
        ),
        deck=deck,
        source=source,
    )


def build_current_status(
    *,
    mode_name: str,
    general_names: Sequence[str] = (),
) -> dict[str, object]:
    """返回稳定、无时间戳且不执行模拟的结构化能力状态。"""

    mode = _nonempty(mode_name, "模式名称")
    names = _normalise_generals(general_names)
    live_readiness: FormalDuelReadiness | None = None
    live_inspection_error: str | None = None
    if mode == FORMAL_NO_SKILL_DUEL_MODE:
        live_readiness, live_inspection_error = _inspect_formal_duel_safely()
        source = inspect_engine_source(
            repository_root=REPOSITORY_ROOT,
            entrypoint_path=Path(__file__),
        )
        manifest = _build_formal_duel_manifest(
            mode=mode,
            names=names,
            source=source,
            readiness=live_readiness,
            inspection_error=live_inspection_error,
        )
    else:
        manifest = build_current_manifest(
            mode_name=mode,
            general_names=names,
        )
    gate = evaluate_formal_run_gate(manifest)
    _, deck_hash, deck_issues = _load_current_deck()
    foundation = inspect_authoritative_core_foundation()
    capabilities: dict[str, object] = {
        "authoritative_core_foundation": foundation.available,
        "authoritative_core_foundation_path": foundation.module_path,
        "authoritative_core_foundation_sha256": foundation.source_sha256,
        "authoritative_core_foundation_issues": list(foundation.issues),
        # MB-B-004：正式单挑 ready 绝不等于完整引擎 ready。
        "authoritative_full_game_core": False,
        "multi_player_production_proven": False,
        "milestone_b_complete": False,
        "mode_implemented": manifest.mode_implemented,
        "ai_implemented": manifest.ai_implemented,
        "ruleset_version": manifest.ruleset_version,
        "unsupported_rules": manifest.unsupported_rules,
        "approximation_count": manifest.approximation_count,
    }
    formal_duel_status: dict[str, object] | None = None
    if mode == FORMAL_NO_SKILL_DUEL_MODE:
        if live_readiness is None:
            formal_duel_status = {
                "mode_id": FORMAL_NO_SKILL_DUEL_MODE,
                "inspection_error": live_inspection_error,
                "formal_duel_no_skill_ready": False,
            }
            capabilities.update(
                {
                    "authoritative_full_game_core": False,
                    "multi_player_production_proven": False,
                    "milestone_b_complete": False,
                    "mode_runtime_reachable": False,
                    "deterministic_controller_implemented": False,
                    "duel_scope_all_cards_sufficient": False,
                    "global_all_cards_implemented": False,
                    "reexecution_replay_supported": False,
                    "formal_duel_no_skill_ready": False,
                }
            )
        else:
            formal_duel_status = live_readiness.to_dict()
            capabilities.update(
                {
                    "authoritative_full_game_core": False,
                    "multi_player_production_proven": False,
                    "milestone_b_complete": False,
                    "mode_runtime_reachable": (
                        live_readiness.mode_runtime_reachable
                    ),
                    "deterministic_controller_implemented": (
                        live_readiness.deterministic_controller_implemented
                    ),
                    "duel_scope_all_cards_sufficient": (
                        live_readiness.duel_scope_all_cards_sufficient
                    ),
                    "global_all_cards_implemented": (
                        live_readiness.global_all_cards_implemented
                    ),
                    "reexecution_replay_supported": (
                        live_readiness.reexecution_replay_supported
                    ),
                    "formal_duel_no_skill_ready": (
                        live_readiness.formal_duel_no_skill_ready
                    ),
                }
            )
    status = {
        "schema_version": STATUS_SCHEMA_VERSION,
        "simulation_executed": False,
        "formal_run_ready": gate.ready,
        "request": {
            "mode_name": manifest.mode_name,
            "general_names": [item.general_name for item in manifest.generals],
        },
        "capabilities": capabilities,
        "deck": {
            "path": str(FORMAL_DECK_PATH),
            "loaded": manifest.deck.loaded,
            "card_count": manifest.deck.card_count,
            "expected_card_count": manifest.deck.expected_card_count,
            "unique_instance_ids": manifest.deck.unique_instance_ids,
            "sha256": deck_hash,
            "audit_issues": list(deck_issues),
        },
        "entrypoint": {
            "path": str(manifest.source.entrypoint_path),
            "inside_repository": manifest.source.entrypoint_inside_repository,
            "source_kind": manifest.source.source_kind.value,
            "uses_authoritative_rule_core": (
                manifest.source.uses_authoritative_rule_core
            ),
            "source_sha256": manifest.source.source_sha256,
            "imported_core_modules": list(manifest.source.imported_core_modules),
            "inspection_issues": list(manifest.source.inspection_issues),
        },
        "gate_issues": [
            {"code": issue.code.value, "message": issue.message}
            for issue in gate.issues
        ],
    }
    if formal_duel_status is not None:
        status["formal_duel"] = formal_duel_status
    return status


def _atomic_write_json(output_path: Path, payload: object) -> None:
    """在目标目录内完整写入临时文件，再原子替换最终结果。"""

    parent = output_path.parent
    parent.mkdir(parents=True, exist_ok=True)
    file_descriptor, temporary_name = tempfile.mkstemp(
        dir=parent,
        prefix=f".{output_path.name}.",
        suffix=".tmp",
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(file_descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(_json_text(payload))
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, output_path)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise


def run_formal_simulation(
    *,
    mode_name: str,
    general_names: Sequence[str] = (),
    output_path: str | Path | None = None,
    seeds: Sequence[int] | None = None,
    max_steps: int = 2000,
) -> Path:
    """通过现场门禁后，现场执行正式 100-seed 验收并原子写为正式结果。

    当前任何 blocker 都会在检查 ``output_path`` 或创建目录之前失败关闭。
    调用方只可指定精确模式和结果路径，不能提交 capability、配置或 seed
    汇总来授予正式资格。``seeds`` 默认精确 0..99；测试可以传入更小的
    seed 子集以真实执行入口（CLI 不暴露该参数），但只有完整 0..99 才
    会被 ``write_formal_acceptance_artifact`` 接受为正式验收 artifact。
    ``simulation_executed=true`` 只在该命令确实现场执行后写出；绝不把
    复制缓存称为已执行（MB-B-001）。
    """

    if max_steps != 2000:
        raise ValueError("正式运行入口固定使用2000步安全上限")
    manifest = build_current_manifest(
        mode_name=mode_name,
        general_names=general_names,
    )
    require_formal_simulation_ready(manifest)
    if manifest.mode_name != FORMAL_NO_SKILL_DUEL_MODE:
        raise ValueError(
            "正式运行入口只接受精确模式"
            f"{FORMAL_NO_SKILL_DUEL_MODE!r}"
        )

    if output_path is None:
        raise ValueError("正式单挑门禁通过后必须提供JSON结果输出路径")
    output = Path(output_path)
    if not output.name or (output.exists() and output.is_dir()):
        raise ValueError("正式单挑结果输出路径必须指向JSON文件")

    prepared_seeds = tuple(range(100)) if seeds is None else tuple(seeds)
    if (
        not prepared_seeds
        or any(
            isinstance(seed, bool) or not isinstance(seed, int)
            for seed in prepared_seeds
        )
        or len(prepared_seeds) != len(set(prepared_seeds))
    ):
        raise ValueError("正式运行的seed集合必须是互不重复的整数")

    started = time.time()
    seed_results = run_formal_duel_seed_sweep(
        prepared_seeds,
        configuration=FormalDuelConfiguration.formal_profile(),
        analysis_only=False,
        max_steps=max_steps,
    )
    elapsed = time.time() - started
    if len(seed_results) != len(prepared_seeds) or any(
        item.natural_end is not True
        or item.formal_result_eligible is not True
        or item.reexecution_verified is not True
        or item.winner not in {"p1", "p2"}
        or item.unsupported_rules != 0
        or item.approximation_count != 0
        or item.safety_cap_triggered
        or item.exception_type is not None
        or not isinstance(item.final_state_hash, str)
        for item in seed_results
    ):
        # MB-B-001：live execution 已真实发生（simulation_executed=true），
        # 但结果失败——必须写出 failed artifact，绝不能输出 passed。
        failed_payload: dict[str, object] = {
            "schema": "SGS_FORMAL_DUEL_RUN_FAILED_v1",
            "schema_version": FORMAL_RESULT_SCHEMA_VERSION,
            "status": "failed",
            "simulation_executed": True,
            "result_source": "live_execution",
            "mode": FORMAL_NO_SKILL_DUEL_MODE,
            "seeds": list(prepared_seeds),
            "analysis_only": False,
            "max_steps": max_steps,
            "seed_results": [item.to_dict() for item in seed_results],
            "note": (
                "正式 run 命令确实现场执行了 seeds；live 结果存在失败项，"
                "status=failed。simulation_executed=true 只表示执行已发生，"
                "不表示执行成功（MB-B-001）。"
            ),
        }
        _atomic_write_json(output, failed_payload)
        raise FormalSimulationExecutionFailedError(failed_payload)

    if tuple(prepared_seeds) == tuple(range(100)):
        payload = build_formal_acceptance_artifact(
            seed_results, elapsed_seconds=elapsed
        )
    else:
        # 测试专用 seed 子集：仍真实执行并逐 seed 记录，但不是正式验收
        # artifact（gate 只接受精确 0..99 + 全部 provenance 绑定）。
        payload = {
            "schema": "SGS_FORMAL_DUEL_RUN_SUBSET_v1",
            "mode": FORMAL_NO_SKILL_DUEL_MODE,
            "seeds": list(prepared_seeds),
            "analysis_only": False,
            "max_steps": max_steps,
            "seed_results": [item.to_dict() for item in seed_results],
            "note": (
                "测试专用正式入口执行子集；不是正式验收证据，"
                "gate 不接受该 schema"
            ),
        }
    payload["schema_version"] = FORMAL_RESULT_SCHEMA_VERSION
    payload["status"] = "passed"
    payload["simulation_executed"] = True
    payload["result_source"] = "live_execution"
    _atomic_write_json(output, payload)
    return output


def _json_text(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="三国杀正式模拟失败关闭入口")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("status", "run"):
        child = subparsers.add_parser(command)
        child.add_argument("--mode", required=True, help="待检查的模式名称")
        child.add_argument(
            "--general",
            action="append",
            default=[],
            help="参战武将名称；可重复提供",
        )
        if command == "run":
            child.add_argument("--output", help="预期结果路径；门禁失败时不会创建")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    # Windows 的继承控制台编码可能不是 UTF-8；CLI 契约固定输出 UTF-8
    # JSON，便于审计程序可靠读取中文字段。
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8")
    args = _parser().parse_args(argv)
    if args.command == "status":
        print(
            _json_text(
                build_current_status(
                    mode_name=args.mode,
                    general_names=args.general,
                )
            )
        )
        return 0

    try:
        run_formal_simulation(
            mode_name=args.mode,
            general_names=args.general,
            output_path=args.output,
        )
    except FormalSimulationBlockedError as exc:
        payload = {
            "status": "blocked",
            "simulation_executed": False,
            "issues": [
                {"code": issue.code.value, "message": issue.message}
                for issue in exc.result.issues
            ],
        }
        print(_json_text(payload), file=sys.stderr)
        return 2
    except FormalSimulationExecutionFailedError as exc:
        payload = exc.payload
        print(_json_text(payload), file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "CoreFoundationReadiness",
    "FORMAL_DECK_PATH",
    "FORMAL_RESULT_SCHEMA_VERSION",
    "REPOSITORY_ROOT",
    "STATUS_SCHEMA_VERSION",
    "build_current_manifest",
    "build_current_status",
    "inspect_authoritative_core_foundation",
    "main",
    "run_formal_simulation",
]
