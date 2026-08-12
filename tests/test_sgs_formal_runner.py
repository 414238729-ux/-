from __future__ import annotations

from dataclasses import replace
import json
import subprocess
import sys
from pathlib import Path

import pytest

import scripts.sgs_engine_gate as engine_gate
import scripts.sgs_formal_runner as formal_runner
from scripts.sgs_engine import duel as test_only_duel_module
from scripts.sgs_engine.formal_duel import (
    inspect_formal_duel_readiness,
)
from scripts.sgs_engine.production_batch import FORMAL_NO_SKILL_DUEL_MODE
from scripts.sgs_engine_gate import FormalSimulationBlockedError, GateIssueCode
from scripts.sgs_engine.duel import TEST_ONLY_DUEL_MODE
from scripts.sgs_formal_runner import (
    FORMAL_DECK_PATH,
    REPOSITORY_ROOT,
    build_current_manifest,
    build_current_status,
    inspect_authoritative_core_foundation,
    run_formal_simulation,
)


def test_current_manifest_audits_real_entrypoint_and_fixed_160_card_deck() -> None:
    manifest = build_current_manifest(
        mode_name="2v2",
        general_names=("测试武将甲", "测试武将乙"),
    )

    assert FORMAL_DECK_PATH == REPOSITORY_ROOT / "knowledge" / "三国杀牌堆数据.csv"
    assert FORMAL_DECK_PATH.is_file()
    assert manifest.deck.loaded is True
    assert manifest.deck.card_count == 160
    assert manifest.deck.expected_card_count == 160
    assert manifest.deck.unique_instance_ids is True
    assert manifest.source.entrypoint_exists is True
    assert manifest.source.entrypoint_inside_repository is True
    assert manifest.source.source_sha256 is not None
    assert manifest.source.uses_authoritative_rule_core is True
    assert "scripts.sgs_engine" in manifest.source.imported_core_modules
    assert manifest.source.inspection_issues == ()


def test_core_foundation_is_derived_by_real_import_and_minimum_self_check() -> None:
    foundation = inspect_authoritative_core_foundation()

    assert foundation.available is True
    assert foundation.module_path is not None
    assert Path(foundation.module_path).is_file()
    assert foundation.source_sha256 is not None
    assert foundation.issues == ()


def test_exact_formal_duel_status_is_derived_from_canonical_live_readiness() -> None:
    readiness = inspect_formal_duel_readiness()
    manifest = build_current_manifest(mode_name=FORMAL_NO_SKILL_DUEL_MODE)
    status = build_current_status(mode_name=FORMAL_NO_SKILL_DUEL_MODE)

    assert manifest.mode_name == FORMAL_NO_SKILL_DUEL_MODE
    assert manifest.deck.card_count == readiness.deck_count == 160
    assert manifest.unsupported_rules == readiness.unsupported_rules
    assert manifest.approximation_count == readiness.approximation_count
    assert manifest.mode_implemented is readiness.mode_implemented
    assert manifest.ai_implemented is readiness.deterministic_controller_implemented
    assert status["simulation_executed"] is False
    assert status["formal_run_ready"] is readiness.formal_duel_no_skill_ready
    assert status["formal_duel"] == readiness.to_dict()
    capabilities = status["capabilities"]
    assert capabilities["mode_runtime_reachable"] is readiness.mode_runtime_reachable
    assert (
        capabilities["duel_scope_all_cards_sufficient"]
        is readiness.duel_scope_all_cards_sufficient
    )
    assert (
        capabilities["global_all_cards_implemented"]
        is readiness.global_all_cards_implemented
    )
    # MB-B-004：formal duel ready 绝不扩大为完整引擎/多人已证明。
    assert capabilities["authoritative_full_game_core"] is False
    assert capabilities["multi_player_production_proven"] is False
    assert capabilities["milestone_b_complete"] is False
    assert (
        capabilities["reexecution_replay_supported"]
        is readiness.reexecution_replay_supported
    )
    assert (
        capabilities["formal_duel_no_skill_ready"]
        is readiness.formal_duel_no_skill_ready
    )
    # formal profile（USER_CONFIRMED_PROJECT_FORMAL_PROFILE）与丈八材料
    # 生命周期（USER_CONFIRMED_RULE，HAND→PROCESSING→DISCARD）已关闭；
    # 当前 blocker 为空，但正式就绪仍由 100-seed 固定验收现场派生。
    blocker_codes = {item["code"] for item in status["formal_duel"]["blockers"]}
    assert blocker_codes == set()
    assert status["formal_run_ready"] is True


def test_formal_duel_reaches_production_factory_without_test_only_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden_test_only_init(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise AssertionError("正式单挑不得构造TestOnlyDuelGame")

    monkeypatch.setattr(
        test_only_duel_module.TestOnlyDuelGame,
        "__init__",
        forbidden_test_only_init,
    )
    status = build_current_status(mode_name=FORMAL_NO_SKILL_DUEL_MODE)

    assert status["capabilities"]["mode_runtime_reachable"] is True
    imported = set(status["entrypoint"]["imported_core_modules"])
    assert ".sgs_engine.formal_duel" in imported
    assert ".sgs_engine.production_batch" in imported
    assert ".sgs_engine.duel" not in imported
    assert status["entrypoint"]["source_kind"] == "formal_rule_core"


def test_core_foundation_import_failure_is_reported_not_hardcoded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_import(name: str):
        raise ImportError(f"cannot import {name}")

    monkeypatch.setattr(formal_runner.importlib, "import_module", fail_import)

    foundation = formal_runner.inspect_authoritative_core_foundation()
    status = formal_runner.build_current_status(mode_name="2v2")

    assert foundation.available is False
    assert any("导入或最小自检失败" in issue for issue in foundation.issues)
    assert status["capabilities"]["authoritative_core_foundation"] is False
    assert status["capabilities"]["authoritative_core_foundation_issues"]


def test_current_status_is_stable_structured_and_does_not_claim_full_engine() -> None:
    first = build_current_status(
        mode_name="斗地主",
        general_names=("武将甲", "武将乙", "武将丙"),
    )
    second = build_current_status(
        mode_name="斗地主",
        general_names=("武将甲", "武将乙", "武将丙"),
    )

    assert first == second
    assert first["simulation_executed"] is False
    assert first["formal_run_ready"] is False
    assert first["capabilities"]["authoritative_core_foundation"] is True
    assert first["capabilities"]["authoritative_full_game_core"] is False
    assert first["deck"]["card_count"] == 160
    assert first["deck"]["audit_issues"] == []
    assert first["capabilities"]["approximation_count"] == 0
    assert first["entrypoint"]["source_sha256"]
    assert first["entrypoint"]["inspection_issues"] == []
    codes = {issue["code"] for issue in first["gate_issues"]}
    assert GateIssueCode.UNSUPPORTED_RULES.value in codes
    assert GateIssueCode.MODE_NOT_IMPLEMENTED.value in codes
    assert GateIssueCode.AI_NOT_IMPLEMENTED.value in codes
    assert GateIssueCode.AUTHORITATIVE_CORE_NOT_USED.value not in codes


def test_test_only_vertical_slice_cannot_enter_formal_runner() -> None:
    status = build_current_status(mode_name=TEST_ONLY_DUEL_MODE)

    assert status["formal_run_ready"] is False
    assert status["simulation_executed"] is False
    assert status["capabilities"]["authoritative_full_game_core"] is False
    assert status["capabilities"]["unsupported_rules"] == 1
    codes = {issue["code"] for issue in status["gate_issues"]}
    assert GateIssueCode.UNSUPPORTED_RULES.value in codes
    assert GateIssueCode.MODE_NOT_IMPLEMENTED.value in codes


def test_bad_or_missing_deck_becomes_structured_blocked_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    missing = tmp_path / "missing-deck.csv"
    monkeypatch.setattr(formal_runner, "FORMAL_DECK_PATH", missing)

    status = formal_runner.build_current_status(mode_name="2v2")

    assert status["formal_run_ready"] is False
    assert status["deck"]["loaded"] is False
    assert status["deck"]["card_count"] == 0
    assert status["deck"]["sha256"] == ""
    assert any("deck_load_failed" in issue for issue in status["deck"]["audit_issues"])
    codes = {issue["code"] for issue in status["gate_issues"]}
    assert GateIssueCode.DECK_NOT_LOADED.value in codes
    assert GateIssueCode.DECK_INCOMPLETE.value in codes


def test_programmatic_run_fails_closed_before_touching_output(tmp_path: Path) -> None:
    output = tmp_path / "nested" / "formal-result.json"

    with pytest.raises(FormalSimulationBlockedError) as captured:
        run_formal_simulation(
            mode_name="普通八人军争",
            general_names=("武将甲", "武将乙"),
            output_path=output,
        )

    assert output.exists() is False
    assert output.parent.exists() is False
    codes = set(captured.value.result.issue_codes)
    assert GateIssueCode.UNSUPPORTED_RULES in codes
    assert GateIssueCode.MODE_NOT_IMPLEMENTED in codes
    assert GateIssueCode.RULESET_VERSION_MISSING in codes


def test_exact_formal_duel_run_uses_live_blockers_and_writes_nothing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "formal-duel" / "result.json"
    # 真实 live readiness 当前已正式就绪（100-seed 验收通过）；本测试
    # 显式模拟 blocked（acceptance 清零），验证 blocked 路径不写输出。
    current = engine_gate.inspect_formal_duel_readiness()
    blocked = replace(
        current,
        acceptance_seed_results=(),
        acceptance_seed_count=0,
        acceptance_natural_end_count=0,
        acceptance_failure_count=0,
        fixed_seed_acceptance_passed=False,
        formal_duel_no_skill_ready=False,
        formal_duel_execution_ready=False,
        blockers=(
            __import__("scripts.sgs_engine.formal_duel", fromlist=["FormalDuelBlocker"]).FormalDuelBlocker(
                "TEST_BLOCKER", "MODE_GAP", "测试模拟 blocker"
            ),
        ),
    )
    monkeypatch.setattr(
        engine_gate,
        "inspect_formal_duel_readiness",
        lambda: blocked,
    )

    with pytest.raises(FormalSimulationBlockedError) as captured:
        run_formal_simulation(
            mode_name=FORMAL_NO_SKILL_DUEL_MODE,
            output_path=output,
        )

    assert output.exists() is False
    assert output.parent.exists() is False
    codes = set(captured.value.result.issue_codes)
    assert GateIssueCode.MODE_NOT_IMPLEMENTED not in codes
    assert GateIssueCode.ALL_CARDS_NOT_IMPLEMENTED not in codes
    assert GateIssueCode.UNSUPPORTED_RULES not in codes
    assert GateIssueCode.FULL_GAME_CORE_NOT_IMPLEMENTED in codes


def test_formal_duel_run_executes_live_subset_and_never_claims_cache(
    tmp_path: Path,
) -> None:
    """正式 run 入口必须确实现场执行；simulation_executed=true 不是缓存标记。"""

    output = tmp_path / "formal-duel" / "result.json"
    returned = run_formal_simulation(
        mode_name=FORMAL_NO_SKILL_DUEL_MODE,
        output_path=output,
        seeds=(0,),
    )

    assert returned == output
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["status"] == "passed"
    assert payload["simulation_executed"] is True
    assert payload["result_source"] == "live_execution"
    assert payload["schema"] == "SGS_FORMAL_DUEL_RUN_SUBSET_v1"
    assert [item["seed"] for item in payload["seed_results"]] == [0]
    assert payload["seed_results"][0]["natural_end"] is True
    assert payload["seed_results"][0]["reexecution_verified"] is True
    assert payload["seed_results"][0]["winner"] in {"p1", "p2"}
    assert not tuple(output.parent.glob(f".{output.name}.*.tmp"))
    # status 入口从不声称已执行；只有真正执行过的 run 结果才带 true。
    status = build_current_status(mode_name=FORMAL_NO_SKILL_DUEL_MODE)
    assert status["simulation_executed"] is False


def test_formal_duel_run_requires_output_only_after_live_gate() -> None:
    with pytest.raises(ValueError, match="必须提供JSON结果输出路径"):
        run_formal_simulation(
            mode_name=FORMAL_NO_SKILL_DUEL_MODE,
            output_path=None,
            seeds=(0,),
        )


def test_cli_status_outputs_stable_json_without_running_game() -> None:
    command = [
        sys.executable,
        "-m",
        "scripts.sgs_formal_runner",
        "status",
        "--mode",
        "2v2",
        "--general",
        "武将甲",
        "--general",
        "武将乙",
    ]

    first = subprocess.run(
        command,
        cwd=REPOSITORY_ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    second = subprocess.run(
        command,
        cwd=REPOSITORY_ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    assert first.returncode == 0
    assert first.stderr == ""
    assert first.stdout == second.stdout
    payload = json.loads(first.stdout)
    assert payload["simulation_executed"] is False
    assert payload["formal_run_ready"] is False
    assert payload["deck"]["card_count"] == 160


def test_cli_exact_formal_duel_status_reaches_live_factory_and_is_ready() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.sgs_formal_runner",
            "status",
            "--mode",
            FORMAL_NO_SKILL_DUEL_MODE,
        ],
        cwd=REPOSITORY_ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    assert completed.returncode == 0
    assert completed.stderr == ""
    payload = json.loads(completed.stdout)
    assert payload["formal_duel"]["mode_id"] == FORMAL_NO_SKILL_DUEL_MODE
    assert payload["capabilities"]["mode_runtime_reachable"] is True
    assert payload["capabilities"]["formal_duel_no_skill_ready"] is True
    assert payload["formal_run_ready"] is True
    assert payload["simulation_executed"] is False


def test_cli_run_rejects_and_never_writes_requested_output(tmp_path: Path) -> None:
    output = tmp_path / "formal" / "result.json"
    command = [
        sys.executable,
        "-m",
        "scripts.sgs_formal_runner",
        "run",
        "--mode",
        "单挑",
        "--general",
        "武将甲",
        "--general",
        "武将乙",
        "--output",
        str(output),
    ]

    completed = subprocess.run(
        command,
        cwd=REPOSITORY_ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    assert completed.returncode == 2
    assert completed.stdout == ""
    payload = json.loads(completed.stderr)
    assert payload["status"] == "blocked"
    assert payload["simulation_executed"] is False
    assert output.exists() is False
    assert output.parent.exists() is False


def test_formal_runner_source_contains_no_external_legacy_entrypoint_reference() -> None:
    source = (REPOSITORY_ROOT / "scripts" / "sgs_formal_runner.py").read_text(
        encoding="utf-8"
    )

    forbidden = (
        "sgs_sim_engine_worker.py",
        "sgs_sim_aggregate.py",
        "sgs_ai_audit_20260729.py",
        "C:/Users/ASUS/Downloads",
        "C:\\Users\\ASUS\\Downloads",
    )
    assert all(value not in source for value in forbidden)
