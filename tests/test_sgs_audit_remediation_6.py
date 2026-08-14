# -*- coding: utf-8 -*-
"""MILESTONE_B_AUDIT_REMEDIATION_6 定向回归：R4-NEW-002 收尾。

R4-NEW-002 的问题仅位于 committed documentation/machine-state consistency：
docs/CHECKPOINT_MANIFEST.json 曾存在绕过 persisted/historical/live 三层模型的
legacy 状态节点。本文件新增（不是 grep 字符串，而是真正解析 JSON 树并递归
检查每一个 machine-state/Git-state scalar 的 ancestor path）：

- WHOLE_MANIFEST_TRAVERSAL：整个 manifest 的递归遍历 invariant；
- CURRENT_STATE_INVARIANT：CURRENT/CURRENT LIVE/persisted_project_state 节点
  不得携带会随 commit/checkout/worktree 改变而失效的 Git scalar，不得与已
  封存 FAILED/PASSED 审计历史冲突；
- HISTORICAL_STATE_INVARIANT：显式 HISTORICAL/AS-OF/PRECOMMIT SNAPSHOT 祖先
  下的 commit=null/pending/NOT_AUDITED_YET 必须允许；
- POST_COMMIT_STABILITY：静态文档不需要知道未来 commit SHA 仍然正确；
- 主动构造的负例矩阵，防止校验器退化为字符串 grep。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = REPOSITORY_ROOT / "docs" / "CHECKPOINT_MANIFEST.json"

R6_BASE_COMMIT = "c283aa4e049b9a0dc728735d5695302c346901c7"

HISTORICAL_PATH_MARKERS = (
    "historical",
    "as_of",
    "precommit",
    "pre_audit",
    "pre-audit",
)

LIVE_GIT_SCALAR_KEYS = frozenset(
    {
        "branch",
        "head",
        "current_head",
        "start_head",
        "worktree_dirty",
        "worktree_clean",
        "worktree_pending",
        "staged",
        "untracked",
    }
)

AUDITED_FAILED_ROUNDS = frozenset({1, 2, 4, 5})
NOT_YET_AUDITED_ROUNDS = frozenset({6})


def _layer_is_historical(node: object) -> bool:
    if isinstance(node, dict):
        layer = node.get("layer")
        if isinstance(layer, str) and "HISTORICAL" in layer.upper():
            return True
    return False


def _key_is_historical(key: str) -> bool:
    lowered = key.lower()
    return any(marker in lowered for marker in HISTORICAL_PATH_MARKERS)


def _iter_scalars(node, path, historical):
    """递归遍历 JSON 树，产出 (path, scalar_value, historical_scope)。

    historical_scope 为 True 表示该 scalar 位于显式 HISTORICAL/AS-OF/
    PRECOMMIT SNAPSHOT 语义的 ancestor（祖先 key 含 historical/as_of/
    precommit/pre-audit 标记，或任一祖先对象的 layer 字段显式标记
    HISTORICAL）之下。
    """
    if isinstance(node, dict):
        node_historical = historical or _layer_is_historical(node)
        for key, value in node.items():
            child_historical = node_historical or _key_is_historical(str(key))
            if isinstance(value, (dict, list)):
                yield from _iter_scalars(value, path + [str(key)], child_historical)
            else:
                yield path + [str(key)], value, child_historical
    elif isinstance(node, list):
        for index, value in enumerate(node):
            if isinstance(value, (dict, list)):
                yield from _iter_scalars(value, path + [str(index)], historical)
            else:
                yield path + [str(index)], value, historical


def whole_manifest_violations(manifest) -> list[tuple]:
    """遍历整个 manifest：禁止的实时/预提交 scalar 必须位于历史祖先之下。"""
    violations: list[tuple] = []
    for path, value, historical in _iter_scalars(manifest, [], False):
        if historical:
            continue
        key = str(path[-1])
        if key in LIVE_GIT_SCALAR_KEYS:
            violations.append((tuple(path), value, "live-git-scalar"))
        elif key == "commit" and value is None:
            violations.append((tuple(path), value, "commit=null"))
        elif key == "commit_status" and value == "pending":
            violations.append((tuple(path), value, "commit_status=pending"))
        elif key == "worktree_commit_pending" and value is True:
            violations.append((tuple(path), value, "worktree-pending"))
        elif key.endswith("state_at_formation") and value == "PRECOMMIT":
            violations.append((tuple(path), value, "PRECOMMIT"))
        elif key in (
            "audit_conclusion",
            "independent_reaudit_status",
            "independent_reaudit_status_at_formation",
        ) and value == "NOT_AUDITED_YET":
            violations.append((tuple(path), value, "NOT_AUDITED_YET"))
    return violations


def _remediation_round(record: dict) -> int | None:
    record_id = str(record.get("checkpoint_id") or record.get("id") or "")
    match = re.fullmatch(r"MILESTONE_B_AUDIT_REMEDIATION_(\d+)", record_id)
    if not match:
        return None
    return int(match.group(1))


def current_conflict_violations(manifest) -> list[tuple]:
    """CURRENT 节点不得与已封存审计历史冲突；R6 不得预写 PASSED。"""
    violations: list[tuple] = []
    for record in manifest.get("checkpoints", []):
        if not isinstance(record, dict):
            continue
        rid = _remediation_round(record)
        if rid is None:
            continue
        for path, value, historical in _iter_scalars(record, [], False):
            if historical:
                continue
            key = str(path[-1])
            if rid in AUDITED_FAILED_ROUNDS:
                if key == "audit_conclusion" and value in (
                    "NOT_AUDITED_YET",
                    "NOT_YET_PERFORMED",
                ):
                    violations.append(
                        (tuple(path), value, f"R{rid} audited but claims {value}")
                    )
                if key == "independent_reaudit_status" and value == "NOT_YET_PERFORMED":
                    violations.append((tuple(path), value, f"R{rid} NOT_YET_PERFORMED"))
                if key == "independent_audit_done" and value is False:
                    violations.append((tuple(path), value, f"R{rid} audit not done"))
            elif rid in NOT_YET_AUDITED_ROUNDS:
                if key in ("audit_conclusion", "independent_reaudit_status"):
                    if isinstance(value, str) and "PASSED" in value:
                        violations.append((tuple(path), value, "R6 prewritten PASSED"))
                if key == "independent_audit_done" and value is True:
                    violations.append((tuple(path), value, "R6 prewritten audit done"))
                if key in ("commit", "worktree_commit_pending"):
                    violations.append((tuple(path), value, "R6 future git scalar"))
    return violations


def current_live_violations(manifest) -> list[tuple]:
    """commit_note 以【CURRENT LIVE】开头的记录：非历史子树内不得出现
    NOT_AUDITED_YET/NOT_YET_PERFORMED/independent_audit_done=false 或
    实时 Git scalar。"""
    violations: list[tuple] = []
    for record in manifest.get("checkpoints", []):
        if not isinstance(record, dict):
            continue
        note = record.get("commit_note")
        if not (isinstance(note, str) and note.startswith("【CURRENT LIVE】")):
            continue
        for path, value, historical in _iter_scalars(record, [], False):
            if historical:
                continue
            key = str(path[-1])
            if key == "audit_conclusion" and value in (
                "NOT_AUDITED_YET",
                "NOT_YET_PERFORMED",
            ):
                violations.append((tuple(path), value, "CURRENT LIVE NOT_AUDITED_YET"))
            if key == "independent_audit_done" and value is False:
                violations.append((tuple(path), value, "CURRENT LIVE audit not done"))
            if (
                key in LIVE_GIT_SCALAR_KEYS
                or (key == "commit" and value is None)
                or (key == "commit_status" and value == "pending")
                or (key == "worktree_commit_pending" and value is True)
            ):
                violations.append((tuple(path), value, "CURRENT LIVE git scalar"))
    return violations


def _manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# WHOLE_MANIFEST_TRAVERSAL
# ---------------------------------------------------------------------------


def test_whole_manifest_has_no_unscoped_live_or_precommit_scalars() -> None:
    violations = whole_manifest_violations(_manifest())
    assert violations == []


def test_whole_manifest_traversal_actually_walks_json_tree() -> None:
    """证明校验器确实解析 JSON 树而不是 grep 字符串：一个把禁止字段写进
    narrative 字符串的合法树不应被判违规，而把它写成真 scalar 就必须违规。"""
    benign = {
        "git": {
            "note": "某段叙事提到 commit=null、commit_status=pending、NOT_AUDITED_YET 无妨"
        }
    }
    assert whole_manifest_violations(benign) == []
    flagged = {"git": {"milestone_b_audit_remediation_1": {"commit": None}}}
    assert whole_manifest_violations(flagged) != []


# ---------------------------------------------------------------------------
# 负例矩阵（主动构造，必须按预期通过/失败）
# ---------------------------------------------------------------------------


def test_negative_case_root_legacy_git_object_commit_null_must_fail() -> None:
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
    violations = whole_manifest_violations(legacy)
    paths = {path for path, _, _ in violations}
    assert ("git", "milestone_b_audit_remediation_1", "branch") in paths
    assert ("git", "milestone_b_audit_remediation_1", "commit") in paths
    assert ("git", "milestone_b_audit_remediation_1", "commit_status") in paths


def test_negative_case_current_live_not_audited_yet_must_fail() -> None:
    conflicting = {
        "checkpoints": [
            {
                "checkpoint_id": "MILESTONE_B_AUDIT_REMEDIATION_1",
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
    assert whole_manifest_violations(conflicting) != []
    assert current_conflict_violations(conflicting) != []
    assert current_live_violations(conflicting) != []


def test_negative_case_historical_precommit_snapshot_commit_null_must_pass() -> None:
    allowed = {
        "git": {
            "current_milestone_b_development": {
                "historical_candidate_formation_snapshots": {
                    "remediation_3": {
                        "layer": "HISTORICAL/AS-OF R3 CANDIDATE FORMATION PRECOMMIT SNAPSHOT",
                        "worktree_state_at_formation": "PRECOMMIT",
                        "commit": None,
                        "commit_status": "pending",
                        "worktree_commit_pending": True,
                        "independent_reaudit_status_at_formation": "NOT_AUDITED_YET",
                    }
                }
            }
        }
    }
    assert whole_manifest_violations(allowed) == []


def test_negative_case_persisted_current_without_git_scalars_must_pass() -> None:
    manifest = _manifest()
    persisted = manifest["git"]["current_milestone_b_development"][
        "persisted_project_state"
    ]
    violations = whole_manifest_violations(persisted)
    assert violations == []
    assert not re.search(
        r"(?<![0-9a-f])[0-9a-f]{40}(?![0-9a-f])", json.dumps(persisted)
    )


# ---------------------------------------------------------------------------
# CURRENT_STATE_INVARIANT
# ---------------------------------------------------------------------------


def test_current_nodes_carry_no_live_git_scalars() -> None:
    manifest = _manifest()
    assert current_conflict_violations(manifest) == []
    assert current_live_violations(manifest) == []

    development = manifest["git"]["current_milestone_b_development"]
    live_policy = development["live_git_state_policy"]
    assert live_policy["source"] == "runtime_derived"
    assert live_policy["persisted"] is False

    advancement = next(
        item
        for item in manifest["checkpoints"]
        if item.get("id") == "MILESTONE_B_FORMAL_160_CARD_NO_SKILL_DUEL_ADVANCEMENT"
    )
    assert advancement["independent_audit_done"] is True
    assert advancement["audit_conclusion"] == "REMEDIATION_1_REAUDIT_FAILED"
    assert advancement["implementation_commit"] == (
        "8ce497064fbb4686177cf63cca5265e902037129"
    )
    snapshot = advancement["historical_precommit_snapshot"]
    assert "HISTORICAL" in snapshot["layer"]
    assert snapshot["candidate_commit_at_formation"] is None
    assert snapshot["candidate_commit_status_at_formation"] == "pending"
    assert snapshot["audit_conclusion"] == "NOT_AUDITED_YET"

    r1 = next(
        item
        for item in manifest["checkpoints"]
        if item.get("checkpoint_id") == "MILESTONE_B_AUDIT_REMEDIATION_1"
    )
    machine = r1["historical_pre_audit_machine_state"]
    assert "HISTORICAL" in machine["layer"]
    assert machine["audit_conclusion"] == "NOT_AUDITED_YET"
    assert machine["independent_audit_done"] is False


# ---------------------------------------------------------------------------
# HISTORICAL_STATE_INVARIANT / 审计历史一致性
# ---------------------------------------------------------------------------


def test_audit_history_chain_r1_to_r5_failed_and_r6_not_yet_audited() -> None:
    manifest = _manifest()
    persisted = manifest["git"]["current_milestone_b_development"][
        "persisted_project_state"
    ]
    assert persisted["latest_completed_independent_reaudit"] == (
        "MILESTONE_B_REMEDIATION_5_FINAL_REAUDIT_FAILED"
    )
    assert persisted["next_candidate"] == "MILESTONE_B_AUDIT_REMEDIATION_6"
    assert persisted["historical_audit_chain"] == [
        "MILESTONE_B_INITIAL_INDEPENDENT_AUDIT_FAILED",
        "MILESTONE_B_REMEDIATION_1_REAUDIT_FAILED",
        "MILESTONE_B_REMEDIATION_2_REAUDIT_FAILED",
        "MILESTONE_B_REMEDIATION_3_PRE_AUDIT_FAILED",
        "MILESTONE_B_REMEDIATION_4_FINAL_REAUDIT_FAILED",
        "MILESTONE_B_REMEDIATION_5_FINAL_REAUDIT_FAILED",
    ]
    assert persisted["r4_open_findings"] == ["R4-NEW-002"]
    assert persisted["r4_closed_findings"] == {"R4-NEW-001": "CLOSED"}

    by_id = {
        str(item.get("checkpoint_id") or item.get("id")): item
        for item in manifest["checkpoints"]
    }
    r5 = by_id["MILESTONE_B_AUDIT_REMEDIATION_5"]
    assert r5["status"] == "independent_reaudit_failed"
    assert r5["audit_conclusion"] == "MILESTONE_B_REMEDIATION_5_FINAL_REAUDIT_FAILED"
    assert r5["open_findings"] == ["R4-NEW-002"]
    assert r5["closed_findings"] == {"R4-NEW-001": "CLOSED"}

    r6 = by_id["MILESTONE_B_AUDIT_REMEDIATION_6"]
    assert r6["status"] == "candidate_pending_independent_reaudit"
    assert r6["independent_reaudit_status"] == "NOT_YET_PERFORMED"
    assert r6["audit_conclusion"] == "NOT_YET_PERFORMED"
    assert r6["remediation_scope"] == ["R4-NEW-002"]
    assert "commit" not in r6
    assert not any(
        isinstance(value, str) and "PASSED" in value
        for path, value, _historical in _iter_scalars(r6, [], False)
        if str(path[-1]) in ("audit_conclusion", "independent_reaudit_status")
    )

    text = json.dumps(manifest, ensure_ascii=False)
    assert "MILESTONE_B_REMEDIATION_6_REAUDIT_PASSED" not in text
    assert "MILESTONE_B_AUDIT_REMEDIATION_6_TARGETED_REAUDIT" not in text


def test_r6_formation_snapshot_is_explicit_historical() -> None:
    snapshot = _manifest()["git"]["current_milestone_b_development"][
        "historical_candidate_formation_snapshots"
    ]["remediation_6"]
    assert "HISTORICAL" in snapshot["layer"]
    assert "AS-OF" in snapshot["layer"]
    assert "PRECOMMIT SNAPSHOT" in snapshot["layer"]
    assert snapshot["base_commit"] == R6_BASE_COMMIT
    assert snapshot["parent_commit_at_formation"] == (
        "3df02b5cfae9af436ba77d8f1c19a7b9959022b1"
    )
    assert snapshot["worktree_state_at_formation"] == "PRECOMMIT"
    assert snapshot["candidate_commit_at_formation"] is None
    assert snapshot["independent_reaudit_status_at_formation"] == "NOT_AUDITED_YET"


def test_legacy_root_git_object_eliminated_and_moved_to_history() -> None:
    manifest = _manifest()
    assert "milestone_b_audit_remediation_1" not in manifest["git"]
    snapshot = manifest["git"]["current_milestone_b_development"][
        "historical_candidate_formation_snapshots"
    ]["remediation_1"]
    assert "HISTORICAL" in snapshot["layer"]
    assert snapshot["base_commit"] == "ebd656754ed2a528e0d08cd5175b68385fdb8140"
    assert snapshot["branch_at_formation"] == "sol-ultra-milestone-b-formal-duel"
    assert snapshot["candidate_commit_at_formation"] is None
    assert snapshot["candidate_commit_status_at_formation"] == "pending"
    assert snapshot["worktree_state_at_formation"] == "PRECOMMIT"


def test_already_closed_findings_do_not_regress() -> None:
    manifest = _manifest()
    persisted = manifest["git"]["current_milestone_b_development"][
        "persisted_project_state"
    ]
    assert persisted["r3_finding_status"] == {
        "R3-NEW-001": "CLOSED",
        "R3-NEW-002": "CLOSED",
        "R3-NEW-003": "CLOSED",
        "DOC-OBS-001": "CLOSED",
    }
    by_id = {
        str(item.get("checkpoint_id") or item.get("id")): item
        for item in manifest["checkpoints"]
    }
    r4 = by_id["MILESTONE_B_AUDIT_REMEDIATION_4"]
    assert r4["open_findings"] == ["R4-NEW-001", "R4-NEW-002"]
    assert r4["closed_findings"] == {
        "R3-NEW-001": "CLOSED",
        "R3-NEW-002": "CLOSED",
        "R3-NEW-003": "CLOSED",
        "DOC-OBS-001": "CLOSED",
    }
    r3 = by_id["MILESTONE_B_AUDIT_REMEDIATION_3"]
    assert r3["audit_conclusion"] == "NO_FINAL_SOL_INDEPENDENT_REAUDIT_PERFORMED"
    assert r3["pre_audit"]["conclusion"] == "MILESTONE_B_REMEDIATION_3_PRE_AUDIT_FAILED"


def test_whole_repo_track_sealed_conclusions_unchanged() -> None:
    manifest = _manifest()
    by_id = {
        str(item.get("checkpoint_id") or item.get("id")): item
        for item in manifest["checkpoints"]
    }
    expected = {
        "WHOLE_REPO_AUDIT_REMEDIATION_1": "REMEDIATION_REAUDIT_FAILED",
        "WHOLE_REPO_AUDIT_REMEDIATION_2": "REMEDIATION_2_REAUDIT_FAILED",
        "WHOLE_REPO_AUDIT_REMEDIATION_3": "REMEDIATION_3_REAUDIT_FAILED",
        "WHOLE_REPO_AUDIT_REMEDIATION_4": "REMEDIATION_4_REAUDIT_FAILED",
        "WHOLE_REPO_AUDIT_REMEDIATION_5": "REMEDIATION_5_REAUDIT_FAILED",
        "WHOLE_REPO_AUDIT_REMEDIATION_6": "REMEDIATION_6_REAUDIT_PASSED",
    }
    for record_id, conclusion in expected.items():
        assert by_id[record_id]["audit_conclusion"] == conclusion
        assert by_id[record_id]["worktree_commit_pending"] is False


# ---------------------------------------------------------------------------
# POST_COMMIT_STABILITY
# ---------------------------------------------------------------------------


def test_post_commit_stability_static_docs_need_no_future_sha() -> None:
    manifest = _manifest()
    text = json.dumps(manifest, ensure_ascii=False)

    # R6 base commit 只能出现在显式历史快照之下。
    for path, value, historical in _iter_scalars(manifest, [], False):
        if isinstance(value, str) and value == R6_BASE_COMMIT:
            assert historical, (path, value)
            assert "historical" in str(path).lower()

    # persisted / live 层不含任何 40 位 SHA。
    development = manifest["git"]["current_milestone_b_development"]
    assert not re.search(
        r"(?<![0-9a-f])[0-9a-f]{40}(?![0-9a-f])",
        json.dumps(development["persisted_project_state"]),
    )
    assert not re.search(
        r"(?<![0-9a-f])[0-9a-f]{40}(?![0-9a-f])",
        json.dumps(development["live_git_state_policy"]),
    )

    invariants = development["documentation_invariants"]
    assert (
        "A committed documentation snapshot must not require knowing the SHA of the commit that contains the snapshot."
        in invariants
    )
    assert (
        "A precommit Git worktree state must never be labelled persistent CURRENT state."
        in invariants
    )

    # 未来 commit 形成后：manifest 不引用任何未来 SHA（包括 R6 自身）。
    assert "f" * 40 not in text
    r6 = next(
        item
        for item in manifest["checkpoints"]
        if item.get("checkpoint_id") == "MILESTONE_B_AUDIT_REMEDIATION_6"
    )
    assert "commit" not in r6


def test_manifest_still_parses_and_schema_intact() -> None:
    manifest = _manifest()
    assert manifest["schema_version"] == "1.2"
    assert isinstance(manifest["checkpoints"], list)
    assert isinstance(manifest["git"], dict)
    assert isinstance(manifest["final_verification"], dict)
    assert isinstance(manifest["sha256"], dict)
