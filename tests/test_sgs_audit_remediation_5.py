# -*- coding: utf-8 -*-
"""MILESTONE_B_AUDIT_REMEDIATION_5 定向回归。

只覆盖 R4-NEW-001（父包 initializer/eager import 与 implementation identity
绑定）和 R4-NEW-002（持久项目状态、历史候选形成快照、实时 Git 状态三层
模型）。游戏规则、状态机和 replay 由既有专项继续回归。
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

import pytest

from scripts.sgs_engine.formal_duel import (
    FORMAL_SIMULATION_TRANSITIVE_INPUT_INVENTORY,
    _implementation_source_files,
    implementation_identity,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = REPOSITORY_ROOT / "docs" / "CHECKPOINT_MANIFEST.json"

EXPECTED_PARENT_PACKAGE_STARTUP_INPUTS = frozenset(
    {
        "scripts/__init__.py",
        "scripts/card_draw.py",
        "scripts/damage.py",
        "scripts/monte_carlo.py",
        "scripts/ranking.py",
        "scripts/sgs_ai_strategy_v22.py",
        "scripts/sgs_ai_strategy_v24.py",
        "scripts/sgs_card_rules.py",
        "scripts/sgs_card_strategy.py",
        "scripts/sgs_chain_strategy.py",
        "scripts/sgs_extended_rules.py",
        "scripts/sgs_focus_strategy.py",
        "scripts/sgs_general_ai_v21.py",
        "scripts/sgs_general_rules.py",
        "scripts/sgs_general_strategy.py",
        "scripts/sgs_incremental_generals.py",
        "scripts/sgs_incremental_mechanics.py",
        "scripts/sgs_jink_response.py",
        "scripts/sgs_limited_identity_variant.py",
        "scripts/sgs_mode_evaluation.py",
        "scripts/sgs_modes.py",
        "scripts/sgs_skill_framework.py",
        "scripts/sgs_special_general_rules.py",
        "scripts/sgs_structured_data.py",
        "scripts/sgs_team_strategy.py",
        "scripts/sgs_v24_generals.py",
        "scripts/summary.py",
        "scripts/trigger.py",
    }
)


@pytest.fixture
def isolated_formal_root(tmp_path: Path) -> Path:
    """复制正式代码/数据输入；子进程不复用 pytest 已加载的 ``scripts``。"""

    root = tmp_path / "isolated-repository"
    root.mkdir()
    ignored = shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache")
    shutil.copytree(REPOSITORY_ROOT / "scripts", root / "scripts", ignore=ignored)
    shutil.copytree(REPOSITORY_ROOT / "knowledge", root / "knowledge", ignore=ignored)
    return root


def _replace_file(path: Path, data: bytes) -> None:
    path.write_bytes(data)


def _fresh_session_probe(root: Path) -> dict[str, str]:
    code = """
import json
from scripts.sgs_engine.formal_duel import (
    FormalDuelConfiguration,
    FormalNoSkillDuelSession,
    implementation_identity,
)

payload = {"identity": implementation_identity()}
try:
    FormalNoSkillDuelSession(
        seed=0,
        configuration=FormalDuelConfiguration.formal_profile(),
        analysis_only=False,
    )
except Exception as exc:
    payload["session"] = f"{type(exc).__name__}:{exc}"
else:
    payload["session"] = "SESSION_ACCEPTED"
print(json.dumps(payload, ensure_ascii=False))
"""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    completed = subprocess.run(
        [sys.executable, "-X", "utf8", "-B", "-c", code],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    return json.loads(completed.stdout.strip().splitlines()[-1])


def test_parent_package_initializer_and_eager_imports_are_explicit_inputs() -> None:
    declared = tuple(FORMAL_SIMULATION_TRANSITIVE_INPUT_INVENTORY)
    assert len(declared) == len(set(declared))
    assert EXPECTED_PARENT_PACKAGE_STARTUP_INPUTS <= set(declared)
    # engine initializer 已由 scripts/sgs_engine/**/*.py 覆盖，不重复显式登记。
    assert "scripts/sgs_engine/__init__.py" not in declared
    assert (REPOSITORY_ROOT / "scripts" / "sgs_engine" / "__init__.py").resolve() in {
        path.resolve() for path in _implementation_source_files()
    }


def test_fresh_formal_import_has_no_unhashed_local_python_input(
    isolated_formal_root: Path,
) -> None:
    code = """
import json
import pathlib
import sys
import scripts.sgs_formal_runner
from scripts.sgs_engine.formal_duel import _implementation_source_files

root = pathlib.Path.cwd().resolve()
hashed = {path.resolve() for path in _implementation_source_files(root)}
loaded = set()
for module in tuple(sys.modules.values()):
    filename = getattr(module, "__file__", None)
    if not filename:
        continue
    path = pathlib.Path(filename).resolve()
    try:
        path.relative_to(root / "scripts")
    except ValueError:
        continue
    if path.suffix == ".py":
        loaded.add(path)
print(json.dumps(sorted(path.relative_to(root).as_posix() for path in loaded - hashed)))
"""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(isolated_formal_root)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    completed = subprocess.run(
        [sys.executable, "-X", "utf8", "-B", "-c", code],
        cwd=isolated_formal_root,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    assert json.loads(completed.stdout.strip().splitlines()[-1]) == []


def test_initializer_effective_content_changes_identity(
    isolated_formal_root: Path,
) -> None:
    before = implementation_identity(isolated_formal_root)
    initializer = isolated_formal_root / "scripts" / "__init__.py"
    original = initializer.read_bytes()
    _replace_file(initializer, original + b"\nR5_IDENTITY_PROBE = True\n")
    assert implementation_identity(isolated_formal_root) != before


def test_fresh_process_loader_change_also_changes_identity(
    isolated_formal_root: Path,
) -> None:
    """父包首次导入重绑真实 deck loader 时，行为和 identity 必须同步变化。"""

    baseline = _fresh_session_probe(isolated_formal_root)
    assert baseline["session"] == "SESSION_ACCEPTED"

    initializer = isolated_formal_root / "scripts" / "__init__.py"
    mutation = b'''\n\n# remediation-5 fresh-process semantic probe\nfrom . import deck_data as _r5_deck_data\ndef _r5_rejected_deck_loader(*args, **kwargs):\n    raise RuntimeError("R5_PACKAGE_INITIALIZER_LOADER_CHANGED")\n_r5_deck_data.load_deck_csv = _r5_rejected_deck_loader\n'''
    _replace_file(initializer, initializer.read_bytes() + mutation)

    changed = _fresh_session_probe(isolated_formal_root)
    assert changed["identity"] != baseline["identity"]
    assert "R5_PACKAGE_INITIALIZER_LOADER_CHANGED" in changed["session"]


def test_initializer_lf_and_crlf_have_same_identity(
    isolated_formal_root: Path,
) -> None:
    initializer = isolated_formal_root / "scripts" / "__init__.py"
    original = initializer.read_bytes()
    lf = original.replace(b"\r\n", b"\n")
    crlf = lf.replace(b"\n", b"\r\n")
    _replace_file(initializer, lf)
    lf_identity = implementation_identity(isolated_formal_root)
    _replace_file(initializer, crlf)
    crlf_identity = implementation_identity(isolated_formal_root)
    assert lf_identity == crlf_identity


def test_docs_change_does_not_change_identity(isolated_formal_root: Path) -> None:
    before = implementation_identity(isolated_formal_root)
    docs = isolated_formal_root / "docs"
    docs.mkdir()
    (docs / "ENGINE_STATUS.md").write_text("docs only\n", encoding="utf-8")
    assert implementation_identity(isolated_formal_root) == before


def test_acceptance_artifact_change_does_not_change_identity(
    isolated_formal_root: Path,
) -> None:
    before = implementation_identity(isolated_formal_root)
    docs = isolated_formal_root / "docs"
    docs.mkdir()
    artifact = docs / "FORMAL_MILESTONE_B_100_SEED_ACCEPTANCE.json"
    artifact.write_text('{"artifact_only": true}\n', encoding="utf-8")
    assert implementation_identity(isolated_formal_root) == before


@pytest.mark.parametrize(
    "relative",
    sorted(EXPECTED_PARENT_PACKAGE_STARTUP_INPUTS),
    ids=lambda value: value.replace("/", "_"),
)
def test_each_parent_package_startup_input_changes_identity(
    isolated_formal_root: Path, relative: str
) -> None:
    """initializer 及每个当前 eager 本地模块都必须真正参与 identity。"""

    before = implementation_identity(isolated_formal_root)
    path = isolated_formal_root / relative
    _replace_file(path, path.read_bytes() + b"\n# remediation-5 startup digest probe\n")
    assert implementation_identity(isolated_formal_root) != before


def _manifest() -> dict[str, object]:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def _checkpoints() -> dict[str, dict[str, object]]:
    return {
        str(item.get("checkpoint_id") or item.get("id")): item
        for item in _manifest()["checkpoints"]  # type: ignore[union-attr]
    }


def _all_keys(value: object) -> set[str]:
    if isinstance(value, dict):
        keys = {str(key) for key in value}
        for child in value.values():
            keys.update(_all_keys(child))
        return keys
    if isinstance(value, list):
        keys: set[str] = set()
        for child in value:
            keys.update(_all_keys(child))
        return keys
    return set()


def test_persisted_project_state_contains_no_live_git_scalars() -> None:
    development = _manifest()["git"]["current_milestone_b_development"]  # type: ignore[index]
    persisted = development["persisted_project_state"]  # type: ignore[index]
    forbidden = {
        "branch",
        "current_branch",
        "head",
        "current_head",
        "worktree_clean",
        "worktree_dirty",
        "worktree_pending",
        "worktree_commit_pending",
        "staged",
        "untracked",
        "unmerged",
        "commit",
    }
    assert _all_keys(persisted).isdisjoint(forbidden)
    assert not re.search(r"(?<![0-9a-f])[0-9a-f]{40}(?![0-9a-f])", json.dumps(persisted))


def test_live_git_state_is_runtime_derived_and_not_persisted() -> None:
    development = _manifest()["git"]["current_milestone_b_development"]  # type: ignore[index]
    policy = development["live_git_state_policy"]  # type: ignore[index]
    assert policy["persisted"] is False  # type: ignore[index]
    assert policy["source"] == "runtime_derived"  # type: ignore[index]
    commands = policy["commands"]  # type: ignore[index]
    assert "git rev-parse HEAD" in commands
    assert "git status --short" in commands
    assert "git ls-files -u" in commands


def test_historical_r4_candidate_formation_snapshot_is_explicit() -> None:
    development = _manifest()["git"]["current_milestone_b_development"]  # type: ignore[index]
    snapshot = development["historical_candidate_formation_snapshots"][  # type: ignore[index]
        "remediation_4"
    ]
    assert "HISTORICAL" in snapshot["layer"]
    assert "AS-OF" in snapshot["layer"]
    assert snapshot["base_commit"] == "5d970560e306b84af518798e11db12c2a42dfc44"
    assert snapshot["candidate_commit_at_formation"] is None
    assert snapshot["worktree_state_at_formation"] == "PRECOMMIT"
    assert snapshot["independent_reaudit_status_at_formation"] == "NOT_AUDITED_YET"


def test_legacy_r3_precommit_verification_is_only_a_historical_reference() -> None:
    verification = _manifest()["final_verification"][  # type: ignore[index]
        "milestone_b_audit_remediation_3"
    ]
    assert "HISTORICAL" in verification["layer"]
    assert "AS-OF" in verification["layer"]
    assert verification["historical_candidate_formation_snapshot"].endswith(
        ".remediation_3"
    )
    assert _all_keys(verification).isdisjoint(
        {
            "worktree_state",
            "independent_audit_done",
            "audit_conclusion",
            "implementation_commit",
            "worktree_commit_pending",
        }
    )


def test_dependency_graph_persisted_table_has_no_live_git_scalars() -> None:
    text = (REPOSITORY_ROOT / "docs" / "MILESTONE_B_DEPENDENCY_GRAPH.md").read_text(
        encoding="utf-8"
    )
    persisted = text.split("| 字段 | PERSISTED PROJECT STATE |", 1)[1].split(
        "\n\n", 1
    )[0]
    for live_label in ("开发分支", "HEAD", "工作树", "unmerged", "staged", "untracked"):
        assert live_label not in persisted
    historical = text.split(
        "| 字段 | HISTORICAL/AS-OF R5 REMEDIATION START SNAPSHOT |", 1
    )[1].split("\n\n", 1)[0]
    assert "固定起点分支" in historical
    assert "固定起点 commit" in historical
    assert "起点工作树核对" in historical
    assert "起点 unmerged 核对" in historical


def test_r4_failed_history_r5_r6_failed_and_r7_not_yet_audited() -> None:
    checkpoints = _checkpoints()
    r4 = checkpoints["MILESTONE_B_AUDIT_REMEDIATION_4"]
    assert r4["commit"] == "3df02b5cfae9af436ba77d8f1c19a7b9959022b1"
    assert r4["audit_conclusion"] == "MILESTONE_B_REMEDIATION_4_FINAL_REAUDIT_FAILED"
    assert r4["independent_audit_done"] is True
    assert r4["open_findings"] == ["R4-NEW-001", "R4-NEW-002"]
    assert r4["closed_findings"] == {
        "R3-NEW-001": "CLOSED",
        "R3-NEW-002": "CLOSED",
        "R3-NEW-003": "CLOSED",
        "DOC-OBS-001": "CLOSED",
    }

    r5 = checkpoints["MILESTONE_B_AUDIT_REMEDIATION_5"]
    assert r5["independent_audit_done"] is True
    assert r5["audit_conclusion"] == "MILESTONE_B_REMEDIATION_5_FINAL_REAUDIT_FAILED"
    assert r5["closed_findings"] == {"R4-NEW-001": "CLOSED"}
    assert r5["open_findings"] == ["R4-NEW-002"]
    assert _all_keys(r5).isdisjoint(
        {"head", "current_head", "commit", "worktree_commit_pending", "worktree_state"}
    )

    r6 = checkpoints["MILESTONE_B_AUDIT_REMEDIATION_6"]
    assert r6["independent_audit_done"] is True
    assert r6["audit_conclusion"] == "MILESTONE_B_REMEDIATION_6_TARGETED_REAUDIT_FAILED"
    assert r6["open_findings"] == ["R4-NEW-002", "R6-NEW-001", "R6-NEW-002"]
    assert r6["closed_findings"] == {"R4-NEW-001": "CLOSED"}
    assert _all_keys(r6).isdisjoint(
        {"head", "current_head", "commit", "worktree_commit_pending", "worktree_state"}
    )

    r7 = checkpoints["MILESTONE_B_AUDIT_REMEDIATION_7"]
    assert r7["state_role"] == "audit_history"
    assert r7["independent_audit_done"] is True
    assert r7["audit_conclusion"] == "MILESTONE_B_REMEDIATION_7_TARGETED_REAUDIT_FAILED"
    assert r7["open_findings"] == ["R7-NEW-001"]
    assert r7["closed_findings"] == {
        "R4-NEW-002": "CLOSED",
        "R6-NEW-001": "CLOSED",
        "R6-NEW-002": "CLOSED",
    }
    assert _all_keys(r7).isdisjoint(
        {"head", "current_head", "commit", "worktree_commit_pending", "worktree_state"}
    )

    r8 = checkpoints["MILESTONE_B_AUDIT_REMEDIATION_8"]
    assert r8["state_role"] == "persisted_current"
    assert r8["independent_reaudit_status"] == "NOT_YET_PERFORMED"
    assert r8["audit_conclusion"] == "NOT_YET_PERFORMED"
    assert r8["remediation_scope"] == ["R7-NEW-001"]
    assert _all_keys(r8).isdisjoint(
        {"head", "current_head", "commit", "worktree_commit_pending", "worktree_state"}
    )


def test_commit_sha_independent_documentation_invariants_are_persisted() -> None:
    development = _manifest()["git"]["current_milestone_b_development"]  # type: ignore[index]
    invariants = development["documentation_invariants"]  # type: ignore[index]
    assert (
        "A committed documentation snapshot must not require knowing the SHA of the commit that contains the snapshot."
        in invariants
    )
    assert (
        "A precommit Git worktree state must never be labelled persistent CURRENT state."
        in invariants
    )


def test_six_docs_share_persisted_state_and_r7_audit_history() -> None:
    manifest = _manifest()
    audit_history = manifest["git"]["current_milestone_b_development"]["audit_history"]
    canonical = {
        str(round_entry["audit_round"]): str(round_entry["conclusion"])
        for round_entry in audit_history["rounds"]
    }
    for name in (
        "CHECKPOINT_MANIFEST.json",
        "ENGINE_STATUS.md",
        "IMPLEMENTATION_MATRIX.md",
        "MASTER_IMPLEMENTATION_PLAN.md",
        "MILESTONE_B_DEPENDENCY_GRAPH.md",
        "SOURCE_AND_CALLCHAIN_AUDIT.md",
    ):
        text = (REPOSITORY_ROOT / "docs" / name).read_text(encoding="utf-8")
        assert "PERSISTED PROJECT STATE" in text, name
        assert "HISTORICAL" in text and "R4 CANDIDATE FORMATION" in text, name
        assert "LIVE GIT STATE" in text and "runtime-derived" in text, name
        assert "R4-NEW-001" in text and "R4-NEW-002" in text, name
        assert "NOT_YET_PERFORMED" in text, name
        # canonical audit mapping：每个文档都必须携带同一组机器结论
        assert canonical["4"] in text, name
        assert canonical["5"] in text, name
        assert canonical["6"] in text, name
        assert canonical["7"] in text, name
        assert "MILESTONE_B_AUDIT_REMEDIATION_8" in text, name
        # R6-NEW-001 / R7 互斥修复：不得再把 R5/R6/R7 说成尚未复审
        assert not re.search(r"R5.{0,30}尚未(独立|经独立)复审", text), name
        assert not re.search(r"尚未(独立|经独立)复审.{0,30}R5", text), name
        assert "R6 候选" not in text, name
        assert "R6 尚未独立复审" not in text, name
        assert "R7 候选" not in text, name
        assert "R7 尚未独立复审" not in text, name
