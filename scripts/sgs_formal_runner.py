"""三国杀正式模拟的最小失败关闭入口。

当前仓库已经能够读取并审计正式的 160 张实体牌堆，也已经提供不可变
状态、事件、动作路由、确定性随机和回放完整性基础设施；但尚不存在把
完整对局状态机、全部模式、武将技能和统一 AI 串联起来的权威整局核心。因此本入口只提供可机器读取的
``status``，并对 ``run`` 无条件执行真实门禁检查。门禁未通过时不会创建
结果文件，也不会降级到任何近似器。

本模块只引用仓库内的牌堆加载器和正式门禁，不导入仓库外部程序。
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn, Sequence

from .deck_data import load_deck_csv
from .sgs_engine_gate import (
    DeckReadiness,
    FormalSimulationBlockedError,
    FormalSimulationManifest,
    GeneralReadiness,
    evaluate_formal_run_gate,
    inspect_engine_source,
    require_formal_simulation_ready,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
FORMAL_DECK_PATH = REPOSITORY_ROOT / "knowledge" / "三国杀牌堆数据.csv"
STATUS_SCHEMA_VERSION = "sgs-formal-runner-status-v1"


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

    ``unsupported_rules=1`` 表示当前至少缺少“可运行的权威完整对局”这一
    阻塞能力，而不是声称只剩一条具体游戏规则。基础设施存在不等于完整
    引擎存在；模式、AI 和参战武将亦
    分别保持未就绪，避免把零散函数误报成可运行整局。
    """

    mode = _nonempty(mode_name, "模式名称")
    names = _normalise_generals(general_names)
    deck, _, _ = _load_current_deck()
    source = inspect_engine_source(
        repository_root=REPOSITORY_ROOT,
        entrypoint_path=Path(__file__),
    )
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


def build_current_status(
    *,
    mode_name: str,
    general_names: Sequence[str] = (),
) -> dict[str, object]:
    """返回稳定、无时间戳且不执行模拟的结构化能力状态。"""

    manifest = build_current_manifest(
        mode_name=mode_name,
        general_names=general_names,
    )
    gate = evaluate_formal_run_gate(manifest)
    _, deck_hash, deck_issues = _load_current_deck()
    foundation = inspect_authoritative_core_foundation()
    return {
        "schema_version": STATUS_SCHEMA_VERSION,
        "simulation_executed": False,
        "formal_run_ready": gate.ready,
        "request": {
            "mode_name": manifest.mode_name,
            "general_names": [item.general_name for item in manifest.generals],
        },
        "capabilities": {
            "authoritative_core_foundation": foundation.available,
            "authoritative_core_foundation_path": foundation.module_path,
            "authoritative_core_foundation_sha256": foundation.source_sha256,
            "authoritative_core_foundation_issues": list(foundation.issues),
            "authoritative_full_game_core": False,
            "mode_implemented": manifest.mode_implemented,
            "ai_implemented": manifest.ai_implemented,
            "ruleset_version": manifest.ruleset_version,
            "unsupported_rules": manifest.unsupported_rules,
            "approximation_count": manifest.approximation_count,
        },
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


def run_formal_simulation(
    *,
    mode_name: str,
    general_names: Sequence[str] = (),
    output_path: str | Path | None = None,
) -> NoReturn:
    """尝试正式运行；当前能力不足时明确拒绝且不接触输出路径。

    ``output_path`` 仅用于固定 CLI/API 契约。在门禁真正开放并接入权威
    核心前，本函数不会创建其父目录、临时文件或结果文件。
    """

    del output_path
    manifest = build_current_manifest(
        mode_name=mode_name,
        general_names=general_names,
    )
    require_formal_simulation_ready(manifest)
    # 当前 manifest 必然被上面的失败关闭门禁拒绝。保留显式防线，防止
    # 将来仅修改门禁清单后在尚无整局核心时意外返回“成功”。
    raise RuntimeError("权威整局规则核心尚未接入，禁止生成正式模拟结果")


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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "CoreFoundationReadiness",
    "FORMAL_DECK_PATH",
    "REPOSITORY_ROOT",
    "STATUS_SCHEMA_VERSION",
    "build_current_manifest",
    "build_current_status",
    "inspect_authoritative_core_foundation",
    "main",
    "run_formal_simulation",
]
