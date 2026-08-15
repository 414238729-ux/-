# -*- coding: utf-8 -*-
"""MILESTONE_B_AUDIT_REMEDIATION_7 定向回归（R8 收口版）。

R7 的 validator 已由 R8 的 canonical node registry 版本取代
（tests/test_sgs_audit_remediation_8.py），本文件保留 R7 轮次必须保持的
负例/正例与机器事实断言，并全部改为运行 R8 registry-bound validator。
"""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path
import sys

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
MANIFEST_PATH = REPOSITORY_ROOT / "docs" / "CHECKPOINT_MANIFEST.json"

from test_sgs_audit_remediation_8 import (  # noqa: E402
    ALLOWED_STATE_ROLES,
    R7_CONCLUSION,
    R8_BASE_COMMIT,
    canonical_root_report,
    validate_manifest,
    _key_semantic_class,
)

R7_BASE_COMMIT = "758de61ad2fc984aabebb7f4f1fb4837ffb8f47b"
R7_PARENT_COMMIT = "c283aa4e049b9a0dc728735d5695302c346901c7"


def _manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# R8 registry-bound validator
# ---------------------------------------------------------------------------


def test_real_manifest_passes_registry_bound_validator() -> None:
    assert validate_manifest(_manifest()) == []


def test_whole_tree_report_unclassified_zero() -> None:
    rows, mismatches, unclassified, violations = canonical_root_report(_manifest())
    assert mismatches == []
    assert unclassified == 0
    counts = {}
    for row in rows:
        counts[row["expected_role"]] = counts.get(row["expected_role"], 0) + 1
    assert counts["persisted_current"] > 0
    assert counts["historical_snapshot"] > 0
    assert counts["audit_history"] > 0
    for row in rows:
        assert row["expected_role"] in ALLOWED_STATE_ROLES
    print(
        f"WHOLE_TREE_REPORT: {len(rows)} registry-bound nodes, "
        f"roles={counts}, unclassified={unclassified}, violations={len(violations)}"
    )


# ---------------------------------------------------------------------------
# 主动负例矩阵（R7 原文要求，经 R8 validator 复核）
# ---------------------------------------------------------------------------


def test_negative_persisted_current_checkpoint_commit_null_must_fail() -> None:
    node = {"state_role": "persisted_current", "formal_duel_capability": "x", "checkpoint_commit": None}
    assert validate_manifest(node) != []


def test_negative_persisted_current_final_doc_commit_null_must_fail() -> None:
    node = {"state_role": "persisted_current", "formal_duel_capability": "x", "final_doc_commit": None}
    assert validate_manifest(node) != []


def test_negative_persisted_current_worktree_branch_must_fail() -> None:
    node = {"state_role": "persisted_current", "formal_duel_capability": "x", "implementation_worktree_branch": "x"}
    assert validate_manifest(node) != []


def test_negative_persisted_current_committed_pending_audit_status_must_fail() -> None:
    node = {"state_role": "persisted_current", "formal_duel_capability": "x", "status": "committed_pending_audit"}
    assert validate_manifest(node) != []


def test_negative_nonhistorical_substring_role_must_fail() -> None:
    node = {"state_role": "nonhistorical_current_state", "branch": "x"}
    assert validate_manifest(node) != []


def test_negative_missing_role_legacy_git_object_must_fail() -> None:
    node = {
        "git": {
            "milestone_b_audit_remediation_1": {
                "branch": "sol-ultra-milestone-b-formal-duel",
                "start_head": "ebd656754ed2a528e0d08cd5175b68385fdb8140",
                "commit": None,
                "commit_status": "pending",
            }
        }
    }
    assert validate_manifest(node) != []


def test_negative_current_live_failed_audit_with_pending_machine_state_must_fail() -> None:
    node = {
        "checkpoints": [
            {
                "checkpoint_id": "MILESTONE_B_AUDIT_REMEDIATION_1",
                "state_role": "audit_history",
                "commit_note": "【CURRENT LIVE】R1 已提交且独立复审失败。",
                "independent_audit_done": True,
                "audit_conclusion": "MILESTONE_B_REMEDIATION_1_REAUDIT_FAILED",
                "machine_state": {
                    "independent_audit_done": False,
                    "audit_conclusion": "NOT_AUDITED_YET",
                },
            }
        ]
    }
    assert validate_manifest(node) != []


def test_negative_r5_both_failed_and_not_yet_audited_must_fail() -> None:
    node = {
        "git": {
            "current_milestone_b_development": {
                "audit_history": {
                    "state_role": "audit_history",
                    "rounds": [
                        {"audit_round": 5, "conclusion": "MILESTONE_B_REMEDIATION_5_FINAL_REAUDIT_FAILED", "status": "audited_failed"}
                    ],
                }
            }
        },
        "checkpoints": [
            {
                "checkpoint_id": "MILESTONE_B_AUDIT_REMEDIATION_5",
                "state_role": "audit_history",
                "independent_audit_done": False,
                "audit_conclusion": "NOT_YET_PERFORMED",
            }
        ],
    }
    assert validate_manifest(node) != []


# ---------------------------------------------------------------------------
# 正例
# ---------------------------------------------------------------------------


def test_positive_historical_snapshot_may_carry_git_scalars() -> None:
    node = {
        "state_role": "historical_snapshot",
        "snapshot_kind": "candidate_formation_precommit",
        "as_of": "2026-08-09",
        "branch": "sol-ultra-milestone-b-formal-duel",
        "start_head": "ebd656754ed2a528e0d08cd5175b68385fdb8140",
        "checkpoint_commit": None,
        "commit": None,
        "commit_status": "pending",
        "status": "committed_pending_audit",
        "worktree_state_at_formation": "PRECOMMIT",
    }
    assert validate_manifest(node) == []


def test_positive_persisted_current_with_only_persistent_facts_passes() -> None:
    node = {
        "state_role": "persisted_current",
        "layer": "PERSISTED PROJECT STATE",
        "formal_duel_capability": "formal 160-card no-skill two-player duel only",
        "latest_completed_independent_reaudit": R7_CONCLUSION,
        "next_candidate": "MILESTONE_B_AUDIT_REMEDIATION_8",
        "next_candidate_independent_reaudit": "NOT_YET_PERFORMED",
        "historical_audit_chain": [R7_CONCLUSION],
        "r3_finding_status": {},
        "r4_open_findings": [],
        "r4_closed_findings": {},
        "r6_finding_status": {},
        "r7_finding_status": {},
        "implementation_identity_policy": "docs excluded",
        "audit_history_reference": "git.current_milestone_b_development.audit_history",
    }
    assert validate_manifest(node) == []


def test_positive_audit_history_r1_to_r6_failed_passes() -> None:
    node = {
        "state_role": "audit_history",
        "rounds": [
            {"audit_round": 1, "conclusion": "MILESTONE_B_REMEDIATION_1_REAUDIT_FAILED", "status": "audited_failed"},
            {"audit_round": 2, "conclusion": "MILESTONE_B_REMEDIATION_2_REAUDIT_FAILED", "status": "audited_failed"},
            {"audit_round": 3, "conclusion": "MILESTONE_B_REMEDIATION_3_PRE_AUDIT_FAILED", "status": "pre_audit_failed", "final_sol_reaudit": "NO_FINAL_SOL_INDEPENDENT_REAUDIT_PERFORMED"},
            {"audit_round": 4, "conclusion": "MILESTONE_B_REMEDIATION_4_FINAL_REAUDIT_FAILED", "status": "audited_failed"},
            {"audit_round": 5, "conclusion": "MILESTONE_B_REMEDIATION_5_FINAL_REAUDIT_FAILED", "status": "audited_failed"},
            {"audit_round": 6, "conclusion": "MILESTONE_B_REMEDIATION_6_TARGETED_REAUDIT_FAILED", "status": "audited_failed"},
        ],
    }
    assert validate_manifest(node) == []


# ---------------------------------------------------------------------------
# REAL_MANIFEST_MUTATION_TESTS（原文件不落盘）
# ---------------------------------------------------------------------------


def _mutated(mutator):
    mutated = copy.deepcopy(_manifest())
    mutator(mutated)
    return mutated, validate_manifest(mutated)


def test_mutation_checkpoint_commit_null_in_persisted_must_fail() -> None:
    def inject(manifest):
        manifest["git"]["current_milestone_b_development"]["persisted_project_state"]["checkpoint_commit"] = None
    _, violations = _mutated(inject)
    assert violations != []


def test_mutation_worktree_branch_in_persisted_must_fail() -> None:
    def inject(manifest):
        manifest["git"]["current_milestone_b_development"]["persisted_project_state"]["implementation_worktree_branch"] = "deepseek-fake-branch"
    _, violations = _mutated(inject)
    assert violations != []


def test_mutation_committed_pending_audit_status_in_persisted_must_fail() -> None:
    def inject(manifest):
        manifest["git"]["current_milestone_b_development"]["persisted_project_state"]["status"] = "committed_pending_audit"
    _, violations = _mutated(inject)
    assert violations != []


def test_mutation_fake_current_live_note_must_fail() -> None:
    def inject(manifest):
        for record in manifest["checkpoints"]:
            if str(record.get("checkpoint_id")) == "MILESTONE_B_AUDIT_REMEDIATION_1":
                record["commit_note"] = "【CURRENT LIVE】注入的伪造 live 标记"
                return
        raise AssertionError("record not found")
    _, violations = _mutated(inject)
    assert violations != []


def test_mutation_nonhistorical_substring_role_must_fail() -> None:
    def inject(manifest):
        snapshot = manifest["git"]["current_milestone_b_development"]["historical_candidate_formation_snapshots"]["remediation_4"]
        snapshot["state_role"] = "nonhistorical_current_state"
    _, violations = _mutated(inject)
    assert violations != []


def test_mutation_unscoped_git_object_at_root_must_fail() -> None:
    def inject(manifest):
        manifest["git"]["injected_legacy"] = {
            "branch": "deepseek-injected",
            "commit": None,
            "commit_status": "pending",
        }
    _, violations = _mutated(inject)
    assert violations != []


def test_mutation_persisted_role_swap_to_historical_must_fail() -> None:
    def inject(manifest):
        persisted = manifest["git"]["current_milestone_b_development"]["persisted_project_state"]
        persisted["state_role"] = "historical_snapshot"
        persisted["as_of"] = "2026-08-14"
        persisted["snapshot_kind"] = "candidate_formation_precommit"
    _, violations = _mutated(inject)
    assert violations != []


# ---------------------------------------------------------------------------
# AUDIT_HISTORY_SOURCE / 机器事实
# ---------------------------------------------------------------------------


def test_audit_history_chain_r1_to_r7_failed_and_r8_not_yet() -> None:
    manifest = _manifest()
    rounds = manifest["git"]["current_milestone_b_development"]["audit_history"]["rounds"]
    by_round = {entry["audit_round"]: entry for entry in rounds}
    assert by_round["initial"]["conclusion"] == "MILESTONE_B_INITIAL_INDEPENDENT_AUDIT_FAILED"
    for round_number, conclusion in {
        1: "MILESTONE_B_REMEDIATION_1_REAUDIT_FAILED",
        2: "MILESTONE_B_REMEDIATION_2_REAUDIT_FAILED",
        3: "MILESTONE_B_REMEDIATION_3_PRE_AUDIT_FAILED",
        4: "MILESTONE_B_REMEDIATION_4_FINAL_REAUDIT_FAILED",
        5: "MILESTONE_B_REMEDIATION_5_FINAL_REAUDIT_FAILED",
        6: "MILESTONE_B_REMEDIATION_6_TARGETED_REAUDIT_FAILED",
        7: R7_CONCLUSION,
    }.items():
        assert by_round[round_number]["conclusion"] == conclusion
    assert by_round[7]["open_findings"] == ["R7-NEW-001"]
    assert by_round[7]["closed_findings"] == {
        "R4-NEW-002": "CLOSED",
        "R6-NEW-001": "CLOSED",
        "R6-NEW-002": "CLOSED",
    }
    assert by_round[8]["status"] == "NOT_YET_PERFORMED"
    persisted = manifest["git"]["current_milestone_b_development"]["persisted_project_state"]
    assert persisted["latest_completed_independent_reaudit"] == R7_CONCLUSION
    assert persisted["next_candidate"] == "MILESTONE_B_AUDIT_REMEDIATION_8"
    assert persisted["r6_finding_status"] == {
        "R4-NEW-002": "CLOSED",
        "R6-NEW-001": "CLOSED",
        "R6-NEW-002": "CLOSED",
    }
    assert persisted["r7_finding_status"] == {"R7-NEW-001": "OPEN"}
    text = json.dumps(manifest, ensure_ascii=False)
    assert "MILESTONE_B_REMEDIATION_8_REAUDIT_PASSED" not in text


def test_legacy_migration_no_unscoped_current_live_left() -> None:
    manifest = _manifest()
    assert "【CURRENT LIVE】" not in json.dumps(manifest, ensure_ascii=False)
    for record in manifest["checkpoints"]:
        rid = str(record.get("checkpoint_id") or record.get("id"))
        assert "state_role" in record, rid
        assert record["state_role"] in ALLOWED_STATE_ROLES, rid


def test_root_git_has_no_unscoped_branch_scalars() -> None:
    manifest = _manifest()
    git = manifest["git"]
    assert set(git.keys()) == {"available", "current_milestone_b_development"}
    metadata = git["current_milestone_b_development"]["historical_development_state"]
    assert metadata["state_role"] == "historical_snapshot"
    assert metadata["snapshot_kind"] == "development_branch_and_commit_metadata"
    for key in metadata:
        if key in ("state_role", "snapshot_kind", "as_of", "note", "repository_local_identity"):
            continue
        assert _key_semantic_class(key) in ("commit", "branch", "worktree", "prose", "pending"), key


def test_r7_formation_snapshot_is_explicit_historical() -> None:
    snapshot = _manifest()["git"]["current_milestone_b_development"][
        "historical_candidate_formation_snapshots"
    ]["remediation_7"]
    assert snapshot["state_role"] == "historical_snapshot"
    assert snapshot["snapshot_kind"] == "candidate_formation_precommit"
    assert snapshot["as_of"] == "2026-08-14"
    assert snapshot["base_commit"] == R7_BASE_COMMIT
    assert snapshot["parent_commit_at_formation"] == R7_PARENT_COMMIT


def test_post_commit_stability_no_future_sha_needed() -> None:
    manifest = _manifest()
    by_id = {str(r.get("checkpoint_id") or r.get("id")): r for r in manifest["checkpoints"]}
    for rid in ("MILESTONE_B_AUDIT_REMEDIATION_7", "MILESTONE_B_AUDIT_REMEDIATION_8"):
        assert "commit" not in by_id[rid], rid
    persisted = manifest["git"]["current_milestone_b_development"]["persisted_project_state"]
    assert not re.search(r"(?<![0-9a-f])[0-9a-f]{40}(?![0-9a-f])", json.dumps(persisted))
    for sha in (R7_BASE_COMMIT, R8_BASE_COMMIT):
        locations = [p for p, v in _walk_all(manifest) if v == sha]
        assert locations, sha
        for path in locations:
            assert "historical_candidate_formation_snapshots" in ".".join(map(str, path)), (path, sha)


def _walk_all(node, path=()):
    if isinstance(node, dict):
        for key, value in node.items():
            if isinstance(value, (dict, list)):
                yield from _walk_all(value, path + (str(key),))
            else:
                yield path + (str(key),), value
    elif isinstance(node, list):
        for index, value in enumerate(node):
            if isinstance(value, (dict, list)):
                yield from _walk_all(value, path + (str(index),))
            else:
                yield path + (str(index),), value


def test_markdown_matches_canonical_audit_mapping() -> None:
    manifest = _manifest()
    rounds = manifest["git"]["current_milestone_b_development"]["audit_history"]["rounds"]
    canonical = {entry["audit_round"]: entry for entry in rounds}
    for name in (
        "ENGINE_STATUS.md",
        "IMPLEMENTATION_MATRIX.md",
        "MASTER_IMPLEMENTATION_PLAN.md",
        "MILESTONE_B_DEPENDENCY_GRAPH.md",
        "SOURCE_AND_CALLCHAIN_AUDIT.md",
    ):
        text = (REPOSITORY_ROOT / "docs" / name).read_text(encoding="utf-8")
        for round_number in (4, 5, 6, 7):
            assert canonical[round_number]["conclusion"] in text, (name, round_number)
        assert "MILESTONE_B_AUDIT_REMEDIATION_8" in text, name
        assert "NOT_YET_PERFORMED" in text, name
        assert "R7 候选" not in text, name
        assert "R7 尚未独立复审" not in text, name
        assert "R6 候选" not in text, name
        assert not re.search(r"R5.{0,30}尚未(独立|经独立)复审", text), name
