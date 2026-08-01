from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

import scripts.sgs_formal_runner as formal_runner
from scripts.sgs_engine_gate import FormalSimulationBlockedError, GateIssueCode
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
