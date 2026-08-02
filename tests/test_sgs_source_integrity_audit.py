from __future__ import annotations

import json
from pathlib import Path

import pytest

import scripts.sgs_source_integrity_audit as audit_module
from scripts.sgs_source_integrity_audit import (
    AuditInputError,
    FindingClassification,
    FindingKind,
    SourceScope,
    main,
    scan_python_sources,
)


def _write(root: Path, relative: str, source: str) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")
    return path


def _find(report, kind: FindingKind):
    return [finding for finding in report.findings if finding.kind is kind]


def test_detects_real_self_confirming_assertion_in_nested_code(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "scripts/audit_case.py",
        """def run(flag, expected):
    if flag:
        chosen = expected
        assert chosen == expected
    return chosen
""",
    )

    report = scan_python_sources(tmp_path)

    findings = _find(report, FindingKind.SELF_CONFIRMING_ASSERTION)
    assert len(findings) == 1
    finding = findings[0]
    assert finding.path == "scripts/audit_case.py"
    assert finding.line == 4
    assert finding.classification is FindingClassification.DEFECT
    assert finding.scope is SourceScope.FORMAL_SOURCE
    assert "chosen = expected" in finding.evidence
    assert "assert chosen == expected" in finding.evidence


def test_does_not_flag_real_computation_or_non_adjacent_assertion(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "valid.py",
        """def choose(actions, expected):
    chosen = actions[0]
    assert chosen == expected
    chosen = expected
    verify(chosen)
    assert chosen == expected
""",
    )

    report = scan_python_sources(tmp_path)

    assert _find(report, FindingKind.SELF_CONFIRMING_ASSERTION) == []


def test_legacy_import_and_path_reference_are_reported(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "scripts/formal_entry.py",
        """import sgs_sim_engine_worker
from sgs_ai_audit_20260729 import audit

LEGACY = r\"C:\\Users\\Demo\\Downloads\\sgs_sim_aggregate.py\"
""",
    )

    report = scan_python_sources(tmp_path)

    imports = _find(report, FindingKind.LEGACY_IMPORT)
    paths = _find(report, FindingKind.LEGACY_PATH_REFERENCE)
    assert len(imports) == 2
    assert len(paths) == 1
    assert all(item.classification is FindingClassification.DEFECT for item in imports + paths)
    assert {item.line for item in imports} == {1, 2}
    assert paths[0].line == 4


def test_legacy_reference_in_test_is_audit_item_not_formal_defect(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path,
        "tests/test_legacy_fixture.py",
        'fixture_path = "sgs_sim_engine_worker.py"\n',
    )

    report = scan_python_sources(tmp_path)

    finding = _find(report, FindingKind.LEGACY_PATH_REFERENCE)[0]
    assert finding.scope is SourceScope.TEST_CODE
    assert finding.classification is FindingClassification.AUDIT_ITEM
    assert report.defect_count == 0


def test_custom_legacy_name_is_supported(tmp_path: Path) -> None:
    _write(tmp_path, "entry.py", 'path = "old_custom_engine.py"\n')

    report = scan_python_sources(
        tmp_path,
        legacy_filenames=("old_custom_engine.py",),
    )

    finding = _find(report, FindingKind.LEGACY_PATH_REFERENCE)[0]
    assert "old_custom_engine.py" in finding.message


def test_explicit_markers_are_audit_items_and_prose_is_ignored(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "status.py",
        '''"""The words approximation_count and unsupported_rules are documentation."""
approximation_count = 2
status = {"unsupported_rules": 1}
message = "unsupported rules are discussed here"
''',
    )

    report = scan_python_sources(tmp_path)

    approximation = _find(report, FindingKind.EXPLICIT_APPROXIMATION_MARKER)
    unsupported = _find(report, FindingKind.EXPLICIT_UNSUPPORTED_MARKER)
    assert approximation
    assert unsupported
    assert {item.line for item in approximation} == {2}
    assert {item.line for item in unsupported} == {3}
    assert all(
        item.classification is FindingClassification.AUDIT_ITEM
        for item in approximation + unsupported
    )
    assert report.defect_count == 0


def test_auditor_does_not_report_its_own_marker_vocabulary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    auditor = _write(
        tmp_path,
        "scripts/sgs_source_integrity_audit.py",
        "approximation_count = 0\nunsupported_rules = 0\n",
    )
    monkeypatch.setattr(audit_module, "__file__", str(auditor))

    report = scan_python_sources(tmp_path)

    assert report.scanned_files == ("scripts/sgs_source_integrity_audit.py",)
    assert report.findings == ()


def test_excludes_venv_and_pycache_and_never_modifies_sources(tmp_path: Path) -> None:
    formal = _write(tmp_path, "src/clean.py", "answer = 42\n")
    _write(
        tmp_path,
        ".venv/bad.py",
        "chosen = expected\nassert chosen == expected\n",
    )
    _write(
        tmp_path,
        "src/__pycache__/bad.py",
        "chosen = expected\nassert chosen == expected\n",
    )
    before = formal.read_bytes()

    report = scan_python_sources(tmp_path)

    assert report.scanned_files == ("src/clean.py",)
    assert report.findings == ()
    assert formal.read_bytes() == before


def test_excludes_pytest_temp_but_still_detects_real_defects(tmp_path: Path) -> None:
    _write(
        tmp_path,
        ".pytest-temp/run/test_fixture/bad_sample.py",
        "chosen = expected\nassert chosen == expected\n",
    )
    _write(
        tmp_path,
        "scripts/real_defect.py",
        "chosen = expected\nassert chosen == expected\n",
    )
    _write(
        tmp_path,
        "tests/real_legacy_fixture.py",
        'fixture_path = "sgs_sim_engine_worker.py"\n',
    )

    report = scan_python_sources(tmp_path)

    assert ".pytest-temp" not in " ".join(report.scanned_files)
    assert report.scanned_files == (
        "scripts/real_defect.py",
        "tests/real_legacy_fixture.py",
    )
    defects = [
        finding
        for finding in report.findings
        if finding.classification is FindingClassification.DEFECT
    ]
    assert len(defects) == 1
    assert defects[0].path == "scripts/real_defect.py"
    assert defects[0].kind is FindingKind.SELF_CONFIRMING_ASSERTION
    assert any(
        finding.path == "tests/real_legacy_fixture.py"
        and finding.kind is FindingKind.LEGACY_PATH_REFERENCE
        and finding.classification is FindingClassification.AUDIT_ITEM
        for finding in report.findings
    )


def test_syntax_error_is_visible_and_does_not_abort_other_files(tmp_path: Path) -> None:
    _write(tmp_path, "a_broken.py", "def broken(:\n")
    _write(tmp_path, "b_valid.py", "value = 1\n")

    report = scan_python_sources(tmp_path)

    errors = _find(report, FindingKind.SYNTAX_ERROR)
    assert len(errors) == 1
    assert errors[0].path == "a_broken.py"
    assert errors[0].classification is FindingClassification.DEFECT
    assert report.scanned_files == ("a_broken.py", "b_valid.py")


def test_report_json_is_stable_sorted_and_machine_readable(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "z.py",
        "chosen = expected\nassert chosen == expected\n",
    )
    _write(tmp_path, "a.py", "unsupported_rules = 0\n")

    first = scan_python_sources(tmp_path)
    second = scan_python_sources(tmp_path)
    payload = json.loads(first.to_json())

    assert first == second
    assert first.to_json() == second.to_json()
    assert payload["schema_version"] == "1.0"
    assert payload["scanned_files"] == ["a.py", "z.py"]
    assert payload["scanned_file_count"] == 2
    assert payload["defect_count"] == 1
    assert payload["audit_item_count"] >= 1
    assert payload["formal_source_finding_count"] == payload["finding_count"]
    assert payload["test_code_finding_count"] == 0
    assert [item["path"] for item in payload["findings"]] == sorted(
        item["path"] for item in payload["findings"]
    )


def test_cli_outputs_json_and_optionally_fails_on_defect(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write(
        tmp_path,
        "bad.py",
        "chosen = expected\nassert chosen == expected\n",
    )

    default_exit = main([str(tmp_path)])
    default_output = json.loads(capsys.readouterr().out)
    strict_exit = main([str(tmp_path), "--fail-on-defect"])
    strict_output = json.loads(capsys.readouterr().out)

    assert default_exit == 0
    assert strict_exit == 1
    assert default_output == strict_output
    assert strict_output["defect_count"] == 1


def test_cli_reports_invalid_root_in_chinese_json(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    missing = tmp_path / "不存在"

    exit_code = main([str(missing)])
    captured = capsys.readouterr()
    payload = json.loads(captured.err)

    assert exit_code == 2
    assert captured.out == ""
    assert payload["error"]["type"] == "input_error"
    assert "审计根目录不存在" in payload["error"]["message"]


def test_library_rejects_file_as_root_with_clear_chinese_error(tmp_path: Path) -> None:
    source_file = _write(tmp_path, "single.py", "value = 1\n")

    with pytest.raises(AuditInputError, match="审计根路径不是目录"):
        scan_python_sources(source_file)
