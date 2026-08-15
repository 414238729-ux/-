# -*- coding: utf-8 -*-
"""MILESTONE_B_AUDIT_REMEDIATION_6 定向回归（R7 收口版）。

R6 独立复审（MILESTONE_B_REMEDIATION_6_TARGETED_REAUDIT_FAILED）指出 R6 的
whole-manifest validator 依赖字段黑名单与名称/substring 的 historical 豁免，
存在语义字段绕过（R6-NEW-002）。因此本文件的校验逻辑已移交：

    tests/test_sgs_audit_remediation_7.py 的 schema-aware validator
    （state_role 精确枚举 + persisted_current 字段白名单 fail-closed）。

本文件保留 R6 轮次必须保持的机器事实断言（advancement/R1/R2 遗留清理、
R5/R6/R7 记录、快照迁移、根级 git 迁移、封存轨道不回归、提交后稳定性），
并主动构造 R6-NEW-002 类负例，证明旧黑名单式的旁路已被数据模型封死。
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
MANIFEST_PATH = REPOSITORY_ROOT / "docs" / "CHECKPOINT_MANIFEST.json"

from test_sgs_audit_remediation_7 import (  # noqa: E402
    ALLOWED_STATE_ROLES,
    R6_CONCLUSION,
    R7_BASE_COMMIT,
    validate_manifest,
)

R6_BASE_COMMIT = "c283aa4e049b9a0dc728735d5695302c346901c7"


def _manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def _checkpoints() -> dict[str, dict]:
    return {
        str(item.get("checkpoint_id") or item.get("id")): item
        for item in _manifest()["checkpoints"]
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


# ---------------------------------------------------------------------------
# schema-aware validator（R6-NEW-002 收口）
# ---------------------------------------------------------------------------


def test_real_manifest_passes_schema_aware_validator() -> None:
    assert validate_manifest(_manifest()) == []


def test_negative_root_legacy_git_object_commit_null_must_fail() -> None:
    legacy = {
        "git": {
            "milestone_b_audit_remediation_1": {
                "branch": "sol-ultra-milestone-b-formal-duel",
                "start_head": "ebd656754ed2a528e0d08cd5175b68385fdb8140",
                "commit": None,
                "commit_status": "pending",
            }
        }
    }
    assert validate_manifest(legacy) != []


def test_negative_nonhistorical_substring_role_must_fail() -> None:
    node = {"state_role": "nonhistorical_current_state", "branch": "x"}
    assert validate_manifest(node) != []


def test_negative_current_live_marker_in_audit_history_must_fail() -> None:
    node = {
        "checkpoints": [
            {
                "checkpoint_id": "MILESTONE_B_AUDIT_REMEDIATION_1",
                "state_role": "audit_history",
                "commit_note": "【CURRENT LIVE】伪造 live 标记",
                "independent_audit_done": True,
                "audit_conclusion": "MILESTONE_B_REMEDIATION_1_REAUDIT_FAILED",
            }
        ]
    }
    assert validate_manifest(node) != []


def test_negative_persisted_current_unknown_git_synonym_must_fail() -> None:
    for injected in (
        {"checkpoint_commit": None},
        {"final_doc_commit": None},
        {"audit_gap_fix_commit": None},
        {"implementation_worktree_branch": "deepseek-x"},
        {"status": "committed_pending_audit"},
    ):
        node = {
            "state_role": "persisted_current",
            "formal_duel_capability": "formal 160-card no-skill two-player duel only",
            **injected,
        }
        assert validate_manifest(node) != [], injected


# ---------------------------------------------------------------------------
# 根级 git 与 legacy 迁移
# ---------------------------------------------------------------------------


def test_root_git_object_has_only_available_and_three_layer_model() -> None:
    git = _manifest()["git"]
    assert set(git.keys()) == {"available", "current_milestone_b_development"}
    dev = git["current_milestone_b_development"]
    assert set(dev.keys()) == {
        "persisted_project_state",
        "historical_candidate_formation_snapshots",
        "live_git_state_policy",
        "documentation_invariants",
        "historical_development_state",
        "audit_history",
    }


def test_root_git_legacy_fields_migrated_to_historical_snapshot() -> None:
    metadata = _manifest()["git"]["current_milestone_b_development"][
        "historical_development_state"
    ]
    assert metadata["state_role"] == "historical_snapshot"
    assert metadata["snapshot_kind"] == "development_branch_and_commit_metadata"
    assert metadata["as_of"] == "2026-08-14"
    for key in (
        "implementation_branch",
        "baseline_commit",
        "milestone_a_commit",
        "milestone_b1_commit",
        "duel_fire_attack_worktree_branch",
        "cp04k_worktree_branch",
        "wr_audit_remediation_6_worktree_branch",
        "repository_local_identity",
    ):
        assert key in metadata, key


def test_formation_snapshots_all_declare_historical_snapshot_role() -> None:
    snaps = _manifest()["git"]["current_milestone_b_development"][
        "historical_candidate_formation_snapshots"
    ]
    assert snaps["state_role"] == "historical_snapshot"
    assert snaps["snapshot_kind"] == "candidate_formation_snapshot_collection"
    for name in (
        "initial_milestone_b",
        "remediation_1",
        "remediation_3",
        "remediation_4",
        "remediation_5_start",
        "remediation_6",
        "remediation_7",
    ):
        entry = snaps[name]
        assert entry["state_role"] == "historical_snapshot", name
        assert entry["snapshot_kind"], name
        assert entry["as_of"], name


# ---------------------------------------------------------------------------
# CURRENT LIVE legacy 清理（advancement / R1 / R2）
# ---------------------------------------------------------------------------


def test_no_current_live_marker_anywhere() -> None:
    assert "【CURRENT LIVE】" not in json.dumps(_manifest(), ensure_ascii=False)


def test_advancement_record_is_audit_history() -> None:
    record = _checkpoints()["MILESTONE_B_FORMAL_160_CARD_NO_SKILL_DUEL_ADVANCEMENT"]
    assert record["state_role"] == "audit_history"
    assert record["status"] == "audited_failed"
    assert record["audit_conclusion"] == "REMEDIATION_1_REAUDIT_FAILED"
    assert record["independent_audit_done"] is True
    assert record["implementation_commit"] == "8ce497064fbb4686177cf63cca5265e902037129"
    snapshot = record["historical_precommit_snapshot"]
    assert snapshot["state_role"] == "historical_snapshot"
    assert snapshot["snapshot_kind"] == "candidate_formation_precommit"
    assert snapshot["candidate_commit_at_formation"] is None
    assert snapshot["candidate_commit_status_at_formation"] == "pending"
    assert snapshot["audit_conclusion"] == "NOT_AUDITED_YET"


def test_r1_record_is_audit_history_with_historical_machine_state() -> None:
    record = _checkpoints()["MILESTONE_B_AUDIT_REMEDIATION_1"]
    assert record["state_role"] == "audit_history"
    assert record["status"] == "audited_failed"
    assert record["audit_conclusion"] == "MILESTONE_B_REMEDIATION_1_REAUDIT_FAILED"
    machine = record["historical_pre_audit_machine_state"]
    assert machine["state_role"] == "historical_snapshot"
    assert machine["snapshot_kind"] == "pre_audit_machine_state"
    assert machine["as_of"] == "2026-08-11"
    assert machine["independent_audit_done"] is False
    assert machine["audit_conclusion"] == "NOT_AUDITED_YET"
    assert record["commit_note"].startswith("【AUDIT HISTORY】")


def test_r2_record_is_audit_history() -> None:
    record = _checkpoints()["MILESTONE_B_AUDIT_REMEDIATION_2"]
    assert record["state_role"] == "audit_history"
    assert record["status"] == "audited_failed"
    assert record["audit_conclusion"] == "MILESTONE_B_REMEDIATION_2_REAUDIT_FAILED"
    assert record["commit_note"].startswith("【AUDIT HISTORY】")


def test_r5_record_audit_history_with_historical_precommit_verification() -> None:
    record = _checkpoints()["MILESTONE_B_AUDIT_REMEDIATION_5"]
    assert record["state_role"] == "audit_history"
    assert "state_model" not in record
    assert record["audit_conclusion"] == "MILESTONE_B_REMEDIATION_5_FINAL_REAUDIT_FAILED"
    assert record["open_findings"] == ["R4-NEW-002"]
    assert record["closed_findings"] == {"R4-NEW-001": "CLOSED"}
    verification = record["precommit_verification"]
    assert verification["state_role"] == "historical_snapshot"
    assert verification["snapshot_kind"] == "precommit_verification"
    assert verification["as_of"] == "2026-08-14"


def test_r6_record_reflects_targeted_reaudit_failed() -> None:
    record = _checkpoints()["MILESTONE_B_AUDIT_REMEDIATION_6"]
    assert record["state_role"] == "audit_history"
    assert record["status"] == "independent_reaudit_failed"
    assert record["independent_audit_done"] is True
    assert record["audit_conclusion"] == R6_CONCLUSION
    assert record["open_findings"] == ["R4-NEW-002", "R6-NEW-001", "R6-NEW-002"]
    assert record["closed_findings"] == {"R4-NEW-001": "CLOSED"}
    assert "commit" not in record


def test_r7_record_is_persisted_current_candidate() -> None:
    record = _checkpoints()["MILESTONE_B_AUDIT_REMEDIATION_7"]
    assert record["state_role"] == "persisted_current"
    assert record["status"] == "candidate_awaiting_independent_reaudit"
    assert record["independent_reaudit_status"] == "NOT_YET_PERFORMED"
    assert record["audit_conclusion"] == "NOT_YET_PERFORMED"
    assert record["remediation_scope"] == ["R4-NEW-002", "R6-NEW-001", "R6-NEW-002"]
    assert _all_keys(record).isdisjoint(
        {"commit", "head", "branch", "worktree_commit_pending", "worktree_state"}
    )


def test_whole_repo_track_sealed_conclusions_unchanged() -> None:
    checkpoints = _checkpoints()
    expected = {
        "WHOLE_REPO_AUDIT_REMEDIATION_1": ("REMEDIATION_REAUDIT_FAILED", "audited_failed"),
        "WHOLE_REPO_AUDIT_REMEDIATION_2": ("REMEDIATION_2_REAUDIT_FAILED", "audited_failed"),
        "WHOLE_REPO_AUDIT_REMEDIATION_3": ("REMEDIATION_3_REAUDIT_FAILED", "audited_failed"),
        "WHOLE_REPO_AUDIT_REMEDIATION_4": ("REMEDIATION_4_REAUDIT_FAILED", "audited_failed"),
        "WHOLE_REPO_AUDIT_REMEDIATION_5": ("REMEDIATION_5_REAUDIT_FAILED", "audited_failed"),
        "WHOLE_REPO_AUDIT_REMEDIATION_6": ("REMEDIATION_6_REAUDIT_PASSED", "audited"),
    }
    for record_id, (conclusion, status) in expected.items():
        record = checkpoints[record_id]
        assert record["state_role"] == "audit_history"
        assert record["audit_conclusion"] == conclusion
        assert record["status"] == status
        assert record["worktree_commit_pending"] is False


# ---------------------------------------------------------------------------
# persisted_current / audit_history / 提交后稳定性
# ---------------------------------------------------------------------------


def test_persisted_project_state_holds_only_allowlisted_persistent_facts() -> None:
    persisted = _manifest()["git"]["current_milestone_b_development"][
        "persisted_project_state"
    ]
    assert persisted["state_role"] == "persisted_current"
    assert persisted["latest_completed_independent_reaudit"] == R6_CONCLUSION
    assert persisted["next_candidate"] == "MILESTONE_B_AUDIT_REMEDIATION_7"
    assert persisted["audit_history_reference"] == (
        "git.current_milestone_b_development.audit_history"
    )
    assert persisted["r6_finding_status"] == {
        "R4-NEW-002": "OPEN",
        "R6-NEW-001": "OPEN",
        "R6-NEW-002": "OPEN",
    }
    assert _all_keys(persisted).isdisjoint(
        {"branch", "head", "commit", "worktree_commit_pending", "worktree_state"}
    )
    assert not re.search(
        r"(?<![0-9a-f])[0-9a-f]{40}(?![0-9a-f])", json.dumps(persisted)
    )


def test_audit_history_is_canonical_single_source() -> None:
    manifest = _manifest()
    rounds = manifest["git"]["current_milestone_b_development"]["audit_history"]["rounds"]
    assert rounds[0]["conclusion"] == "MILESTONE_B_INITIAL_INDEPENDENT_AUDIT_FAILED"
    for index, expected in enumerate(
        (
            "MILESTONE_B_REMEDIATION_1_REAUDIT_FAILED",
            "MILESTONE_B_REMEDIATION_2_REAUDIT_FAILED",
            "MILESTONE_B_REMEDIATION_3_PRE_AUDIT_FAILED",
            "MILESTONE_B_REMEDIATION_4_FINAL_REAUDIT_FAILED",
            "MILESTONE_B_REMEDIATION_5_FINAL_REAUDIT_FAILED",
            R6_CONCLUSION,
        ),
        start=1,
    ):
        assert rounds[index]["conclusion"] == expected
    assert rounds[7]["conclusion"] == "NOT_YET_PERFORMED"
    persisted_chain = manifest["git"]["current_milestone_b_development"][
        "persisted_project_state"
    ]["historical_audit_chain"]
    canonical_chain = [entry["conclusion"] for entry in rounds if entry["audit_round"] != 7]
    assert persisted_chain == canonical_chain


def test_post_commit_stability_r7_needs_no_future_sha() -> None:
    manifest = _manifest()
    text = json.dumps(manifest, ensure_ascii=False)
    r7 = _checkpoints()["MILESTONE_B_AUDIT_REMEDIATION_7"]
    assert "commit" not in r7
    base_index = text.find(R7_BASE_COMMIT)
    assert base_index >= 0
    assert R7_BASE_COMMIT not in json.dumps(
        manifest["git"]["current_milestone_b_development"]["persisted_project_state"],
        ensure_ascii=False,
    )
    invariants = manifest["git"]["current_milestone_b_development"][
        "documentation_invariants"
    ]
    assert (
        "A persisted_current state node must not store live Git or worktree scalars, regardless of field name."
        in invariants
    )
    assert (
        "Historical exemption is granted only by the exact state_role value 'historical_snapshot', never by names or prose containing the word historical."
        in invariants
    )


def test_schema_version_bumped() -> None:
    assert _manifest()["schema_version"] == "1.3"


def test_acceptance_artifact_identity_unchanged() -> None:
    manifest = _manifest()
    sha = manifest["sha256"]
    assert sha["docs/FORMAL_MILESTONE_B_100_SEED_ACCEPTANCE.json"] == (
        "8fb694713f68f4da7e1f1b07e266168c476c7b1d14daa436b79b03c7b6f1c695"
    )
    assert "tests/test_sgs_audit_remediation_7.py" in sha
