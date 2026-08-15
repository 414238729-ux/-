# -*- coding: utf-8 -*-
"""MILESTONE_B_AUDIT_REMEDIATION_7 定向回归。

R6 targeted re-audit（MILESTONE_B_REMEDIATION_6_TARGETED_REAUDIT_FAILED）：
- R4-NEW-002 仍 OPEN（黑名单式字段检查无法覆盖同义字段）；
- R6-NEW-001：Markdown 中 R5 状态互斥；
- R6-NEW-002：whole-manifest validator 存在语义字段绕过（靠名称/substring
  授予 historical 豁免）。

本轮收口为显式 state_role 数据模型：

- ALLOWED_STATE_ROLES = {persisted_current, historical_snapshot, audit_history}
- historical 豁免只由精确枚举值 state_role=="historical_snapshot" 授予；
  名称、prose、ancestor substring 一律不构成豁免（
  "nonhistorical_current_state" 必须失败）。
- persisted_current 采用字段白名单（允许什么，而不是禁止什么），未知字段
  fail closed，同义 Git/worktree 字段无法绕过。
- 每个 state 节点必须有合法 role，无 role 的 legacy 状态节点 fail closed。

本文件的 validator 真正解析 JSON 树并递归检查，不是 grep 字符串。
"""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = REPOSITORY_ROOT / "docs" / "CHECKPOINT_MANIFEST.json"

R7_BASE_COMMIT = "758de61ad2fc984aabebb7f4f1fb4837ffb8f47b"
R7_PARENT_COMMIT = "c283aa4e049b9a0dc728735d5695302c346901c7"
R6_CONCLUSION = "MILESTONE_B_REMEDIATION_6_TARGETED_REAUDIT_FAILED"

ALLOWED_STATE_ROLES = frozenset(
    {"persisted_current", "historical_snapshot", "audit_history"}
)

# 语义检测（defense-in-depth；主正确性由白名单/role 决定，不依赖此枚举穷尽）
GIT_SEMANTIC_KEY_RE = re.compile(
    r"(?<![a-z0-9])(worktree|branch|head|staged|untracked|dirty|clean|precommit|commit|pending)(?![a-z0-9])",
    re.IGNORECASE,
)
# 纯容器 key（其 value 是容器表，容器自身不做 state-node 判定；子节点照常检查）
CONTAINER_KEYS = frozenset(
    {
        "git",
        "checkpoints",
        "final_verification",
        "sha256",
        "feature_status",
        "stage_status",
        "current_milestone_b_development",
        "audit_history",
        "rounds",
        "persisted_project_state",
        "historical_candidate_formation_snapshots",
        "historical_development_state",
        "live_git_state_policy",
        "documentation_invariants",
    }
)
AUDIT_SEMANTIC_KEYS = frozenset(
    {
        "audit_conclusion",
        "independent_audit_done",
        "independent_reaudit_status",
        "independent_reaudit_status_at_formation",
        "audit_result_commit",
    }
)
PENDING_STATUS_VALUES = frozenset({"committed_pending_audit", "worktree_pending"})
SHA40_RE = re.compile(r"^[0-9a-f]{40}$")


def _value_kind(value) -> str:
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, str):
        return "str"
    if isinstance(value, list):
        return "list"
    if isinstance(value, dict):
        return "dict"
    if isinstance(value, int):
        return "int"
    if value is None:
        return "null"
    return "any"


PERSISTED_PROJECT_STATE_SCHEMA = {
    "state_role": "str",
    "layer": "str",
    "formal_duel_capability": "str",
    "latest_completed_independent_reaudit": "str",
    "next_candidate": "str",
    "next_candidate_independent_reaudit": "str",
    "historical_audit_chain": "list",
    "r3_finding_status": "dict",
    "r4_open_findings": "list",
    "r4_closed_findings": "dict",
    "r6_finding_status": "dict",
    "implementation_identity_policy": "str",
    "audit_history_reference": "str",
}

FEATURE_STATUS_KEYS = {
    "authoritative_core_foundation",
    "minimal_duel_vertical_slice",
    "reexecution_replay_supported",
    "authoritative_full_game_core",
    "formal_duel_no_skill_ready",
    "formal_run_ready",
    "formal_duel_mode_runtime_reachable",
    "formal_duel_mode_implemented",
    "production_basic_cards_batch",
    "production_single_target_trick_slice",
    "production_zone_target_trick_batch",
    "hidden_handle_hmac_security_fix",
    "production_duel_fire_attack_batch",
    "production_group_target_trick_batch",
    "production_remaining_ordinary_trick_batch",
    "production_chain_damage_infrastructure",
    "production_borrowed_sword_weapon_system",
    "production_delayed_trick_judgment_infrastructure",
    "production_armor_damage_prevention_infrastructure",
    "production_mount_distance_infrastructure",
    "production_turn_cycle_discard_infrastructure",
    "production_weapon_skill_completion",
    "formal_duel_duel_scope_all_cards_sufficient",
    "formal_duel_global_all_cards_implemented",
    "multi_player_production_proven",
    "milestone_b_complete",
}
FEATURE_STATUS_SCHEMA = {"state_role": "str", **{k: "bool" for k in FEATURE_STATUS_KEYS}}

STAGE_STATUS_KEYS = {
    "1_source_and_callchain_audit",
    "2_legacy_invalidation_and_fail_closed_gate",
    "3_existing_engine_inventory",
    "4_authoritative_core",
    "5_cards_and_modes",
    "6_generals",
    "7_web_and_replay_ui",
    "8_unified_ai",
    "9_multiprocess_formal_winrate",
}
STAGE_STATUS_SCHEMA = {"state_role": "str", **{k: "str" for k in STAGE_STATUS_KEYS}}

R7_CANDIDATE_SCHEMA = {
    "checkpoint_id": "str",
    "batch_name": "str",
    "state_role": "str",
    "status": "str",
    "independent_reaudit_status": "str",
    "audit_conclusion": "str",
    "latest_completed_independent_reaudit": "str",
    "remediation_scope": "list",
    "historical_base_reference": "str",
    "candidate_identity_policy": "str",
    "implementation_note": "str",
    "independent_reaudit_note": "str",
}
R7_CANDIDATE_ALLOWED_STATUS = {"candidate_awaiting_independent_reaudit"}


def _classify_persisted_node(node: dict) -> dict | None:
    if "formal_duel_capability" in node:
        return PERSISTED_PROJECT_STATE_SCHEMA
    if node.get("checkpoint_id") == "MILESTONE_B_AUDIT_REMEDIATION_7":
        return R7_CANDIDATE_SCHEMA
    if "authoritative_core_foundation" in node:
        return FEATURE_STATUS_SCHEMA
    if "1_source_and_callchain_audit" in node:
        return STAGE_STATUS_SCHEMA
    return None


def _key_semantic_class(key: str) -> str | None:
    lowered = key.lower()
    if lowered.endswith("_note") or lowered.endswith("_narrative"):
        return "prose"
    if GIT_SEMANTIC_KEY_RE.search(lowered):
        if "worktree" in lowered or "staged" in lowered or "untracked" in lowered:
            return "worktree"
        if "dirty" in lowered or "clean" in lowered:
            return "worktree"
        if "branch" in lowered:
            return "branch"
        if "head" in lowered:
            return "head"
        if "pending" in lowered or "precommit" in lowered:
            return "pending"
        if "commit" in lowered:
            return "commit"
    return None


def _is_state_bearing(node: dict) -> bool:
    if "state_role" in node:
        return True
    for key in node:
        if key in AUDIT_SEMANTIC_KEYS:
            return True
        if _key_semantic_class(str(key)) is not None:
            return True
    return False


def walk_state_tree(manifest, violations: list, path=(), inherited_role=None,
                    is_container=False):
    """递归检查：role 枚举、historical_snapshot 要件、persisted_current 白名单、
    语义 scalar 分层、无 role 的 legacy 状态节点 fail closed。"""
    if isinstance(manifest, dict):
        declared_role = manifest.get("state_role")
        if declared_role is not None:
            if declared_role not in ALLOWED_STATE_ROLES:
                violations.append(
                    (path + ("state_role",), declared_role,
                     f"unknown state_role {declared_role!r}; exact enum required")
                )
                declared_role = None
        role = declared_role if declared_role is not None else inherited_role

        if declared_role == "historical_snapshot":
            if not isinstance(manifest.get("as_of"), str) or not manifest.get("as_of"):
                violations.append((path, None, "historical_snapshot missing as_of"))
            if not isinstance(manifest.get("snapshot_kind"), str) or not manifest.get("snapshot_kind"):
                violations.append((path, None, "historical_snapshot missing snapshot_kind"))
        if declared_role == "persisted_current":
            schema = _classify_persisted_node(manifest)
            if schema is None:
                violations.append((path, None, "persisted_current node matches no registered schema"))
            else:
                for key in manifest:
                    if key not in schema:
                        violations.append(
                            (path + (str(key),), manifest[key],
                             "persisted_current unknown field (allowlist fail-closed)")
                        )
                    elif _value_kind(manifest[key]) != schema[key]:
                        violations.append(
                            (path + (str(key),), manifest[key],
                             f"persisted_current field type mismatch, expected {schema[key]}")
                        )
        if declared_role == "audit_history":
            note = manifest.get("commit_note")
            if isinstance(note, str) and ("【CURRENT LIVE】" in note or note.startswith("【CURRENT LIVE】")):
                violations.append((path + ("commit_note",), None, "audit_history carries CURRENT LIVE marker"))

        if role is None and not is_container and _is_state_bearing(manifest):
            violations.append((path, None, "unclassified state node (no valid state_role)"))

        for key, value in manifest.items():
            child_role = role
            child_is_container = str(key) in CONTAINER_KEYS
            semantic = _key_semantic_class(str(key))
            audit_semantic = str(key) in AUDIT_SEMANTIC_KEYS
            if isinstance(value, (dict, list)):
                walk_state_tree(value, violations, path + (str(key),), child_role,
                                is_container=child_is_container)
                continue
            # scalar rules
            if key == "commit" and value is None:
                if role != "historical_snapshot":
                    violations.append((path + (str(key),), value, "commit=null outside historical_snapshot"))
            if key == "commit_status" and value == "pending":
                if role != "historical_snapshot":
                    violations.append((path + (str(key),), value, "commit_status=pending outside historical_snapshot"))
            if semantic in ("worktree", "branch", "head"):
                if key == "worktree_commit_pending" and value is False:
                    continue
                if role != "historical_snapshot":
                    if isinstance(value, (str, type(None))) or key == "worktree_commit_pending":
                        violations.append((path + (str(key),), value, f"{semantic} git scalar outside historical_snapshot"))
            if semantic == "pending":
                if role != "historical_snapshot" and isinstance(value, (str, type(None))):
                    violations.append((path + (str(key),), value, "pending/precommit scalar outside historical_snapshot"))
            if key == "status" and value in PENDING_STATUS_VALUES:
                if role != "historical_snapshot":
                    violations.append((path + (str(key),), value, "pending status outside historical_snapshot"))
            if isinstance(value, str) and SHA40_RE.match(value):
                if role not in ("historical_snapshot", "audit_history"):
                    violations.append((path + (str(key),), value, "git SHA outside historical_snapshot/audit_history"))
            if audit_semantic and value == "NOT_AUDITED_YET":
                if role != "historical_snapshot":
                    violations.append((path + (str(key),), value, "NOT_AUDITED_YET outside historical_snapshot"))
            if key == "independent_audit_done" and value is False:
                sibling = manifest.get("audit_conclusion")
                if sibling == "NOT_AUDITED_YET" and role != "historical_snapshot":
                    violations.append((path + (str(key),), value, "not-audited machine state outside historical_snapshot"))
    elif isinstance(manifest, list):
        for index, value in enumerate(manifest):
            walk_state_tree(value, violations, path + (str(index),), inherited_role,
                            is_container=is_container)


def cross_check_audit_history(manifest, violations: list):
    """audit_history 单一事实源与 checkpoints 记录、persisted 链的交叉校验。"""
    dev = manifest.get("git", {}).get("current_milestone_b_development", {})
    rounds = dev.get("audit_history", {}).get("rounds", [])
    by_round = {entry.get("audit_round"): entry for entry in rounds}
    for record in manifest.get("checkpoints", []):
        rid = str(record.get("checkpoint_id") or record.get("id") or "")
        match = re.fullmatch(r"MILESTONE_B_AUDIT_REMEDIATION_(\d+)", rid)
        if not match:
            continue
        round_number = int(match.group(1))
        entry = by_round.get(round_number)
        if entry is None:
            violations.append(((rid,), None, "checkpoint round missing from audit_history"))
            continue
        if entry.get("status") == "NOT_YET_PERFORMED":
            if "PASSED" in str(record.get("audit_conclusion", "")):
                violations.append(((rid,), record.get("audit_conclusion"), "prewritten PASSED"))
            if record.get("independent_audit_done") is True:
                violations.append(((rid,), True, "prewritten independent_audit_done"))
        else:
            if round_number == 3:
                expected = entry.get("final_sol_reaudit")
                if record.get("audit_conclusion") != expected:
                    violations.append(((rid,), record.get("audit_conclusion"), f"R3 conclusion mismatch, expected {expected}"))
                if record.get("independent_audit_done") is not False:
                    violations.append(((rid,), record.get("independent_audit_done"), "R3 must not claim a final Sol re-audit was done"))
            else:
                expected = entry.get("conclusion")
                if record.get("audit_conclusion") != expected:
                    violations.append(((rid,), record.get("audit_conclusion"), f"R{round_number} conclusion mismatch, expected {expected}"))
                if record.get("independent_audit_done") is not True:
                    violations.append(((rid,), record.get("independent_audit_done"), f"R{round_number} audited but machine says not done"))
    persisted_chain = dev.get("persisted_project_state", {}).get("historical_audit_chain", [])
    canonical_chain = [entry.get("conclusion") for entry in rounds if entry.get("audit_round") != 7]
    if list(persisted_chain) != list(canonical_chain):
        violations.append((("persisted_project_state", "historical_audit_chain"), persisted_chain, "chain diverges from audit_history"))


def validate_manifest(manifest) -> list:
    violations: list = []
    walk_state_tree(manifest, violations)
    cross_check_audit_history(manifest, violations)
    return violations


def state_role_report(manifest):
    """只读 whole-tree 报告：每个 state 节点的 path/state_role/snapshot_kind/audit_round。"""
    rows = []

    def walk(node, path=(), role=None):
        if isinstance(node, dict):
            declared = node.get("state_role")
            eff = declared if declared is not None else role
            if eff is not None:
                rows.append({
                    "path": ".".join(str(p) for p in path) or "<root>",
                    "state_role": eff,
                    "snapshot_kind": node.get("snapshot_kind"),
                    "audit_round": node.get("audit_round"),
                    "declared": declared is not None,
                })
            for key, value in node.items():
                if isinstance(value, (dict, list)):
                    walk(value, path + (str(key),), eff)
        elif isinstance(node, list):
            for index, value in enumerate(node):
                walk(value, path + (str(index),), role)

    walk(manifest)
    stats = {
        "persisted_current": sum(1 for row in rows if row["state_role"] == "persisted_current"),
        "historical_snapshot": sum(1 for row in rows if row["state_role"] == "historical_snapshot"),
        "audit_history": sum(1 for row in rows if row["state_role"] == "audit_history"),
    }
    violations = validate_manifest(manifest)
    unclassified = sum(1 for v in violations if str(v[2]).startswith("unclassified"))
    persisted_git = sum(
        1 for v in violations
        if any(str(p) == "persisted_current" or "persisted_current" in str(p) for p in (v[0] if isinstance(v[0], tuple) else ()))
        and not str(v[2]).startswith("unclassified")
    )
    return rows, stats, violations, unclassified, persisted_git


def _manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# WHOLE-MANIFEST VALIDATOR（真实 manifest）
# ---------------------------------------------------------------------------


def test_real_manifest_passes_schema_validator() -> None:
    violations = validate_manifest(_manifest())
    assert violations == []


def test_whole_tree_report_unclassified_zero() -> None:
    rows, stats, violations, unclassified, persisted_git = state_role_report(_manifest())
    assert unclassified == 0, [v for v in violations if str(v[2]).startswith("unclassified")]
    assert persisted_git == 0
    assert stats["persisted_current"] > 0
    assert stats["historical_snapshot"] > 0
    assert stats["audit_history"] > 0
    for row in rows:
        assert row["state_role"] in ALLOWED_STATE_ROLES, row
        if row["state_role"] == "historical_snapshot" and row["declared"]:
            assert row["snapshot_kind"], row
    print(
        f"WHOLE_TREE_REPORT state_role counts: persisted_current={stats['persisted_current']}, "
        f"historical_snapshot={stats['historical_snapshot']}, "
        f"audit_history={stats['audit_history']}, unclassified={unclassified}"
    )


# ---------------------------------------------------------------------------
# 主动负例矩阵（SEMANTIC_BYPASS_NEGATIVE_TESTS）
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
        "latest_completed_independent_reaudit": R6_CONCLUSION,
        "next_candidate": "MILESTONE_B_AUDIT_REMEDIATION_7",
        "next_candidate_independent_reaudit": "NOT_YET_PERFORMED",
        "historical_audit_chain": [R6_CONCLUSION],
        "r3_finding_status": {},
        "r4_open_findings": [],
        "r4_closed_findings": {},
        "r6_finding_status": {},
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
            {"audit_round": 6, "conclusion": R6_CONCLUSION, "status": "audited_failed"},
        ],
    }
    assert validate_manifest(node) == []


# ---------------------------------------------------------------------------
# REAL_MANIFEST_MUTATION_TESTS（原文件不落盘）
# ---------------------------------------------------------------------------


def _mutated_manifest(mutator) -> tuple[dict, list]:
    original = _manifest()
    mutated = copy.deepcopy(original)
    locations = mutator(mutated)
    violations = validate_manifest(mutated)
    return mutated, violations, locations


def test_mutation_checkpoint_commit_null_in_persisted_must_fail() -> None:
    def inject(manifest):
        persisted = manifest["git"]["current_milestone_b_development"]["persisted_project_state"]
        persisted["checkpoint_commit"] = None
        return [("persisted_project_state", "checkpoint_commit")]
    _, violations, _ = _mutated_manifest(inject)
    assert violations != []


def test_mutation_worktree_branch_in_persisted_must_fail() -> None:
    def inject(manifest):
        persisted = manifest["git"]["current_milestone_b_development"]["persisted_project_state"]
        persisted["implementation_worktree_branch"] = "deepseek-fake-branch"
        return [("persisted_project_state", "implementation_worktree_branch")]
    _, violations, _ = _mutated_manifest(inject)
    assert violations != []


def test_mutation_committed_pending_audit_status_in_persisted_must_fail() -> None:
    def inject(manifest):
        persisted = manifest["git"]["current_milestone_b_development"]["persisted_project_state"]
        persisted["status"] = "committed_pending_audit"
        return [("persisted_project_state", "status")]
    _, violations, _ = _mutated_manifest(inject)
    assert violations != []


def test_mutation_fake_current_live_note_must_fail() -> None:
    def inject(manifest):
        for record in manifest["checkpoints"]:
            if str(record.get("checkpoint_id") or record.get("id")) == "MILESTONE_B_AUDIT_REMEDIATION_1":
                record["commit_note"] = "【CURRENT LIVE】注入的伪造 live 标记"
                return [("checkpoints", "MILESTONE_B_AUDIT_REMEDIATION_1", "commit_note")]
        raise AssertionError("record not found")
    _, violations, _ = _mutated_manifest(inject)
    assert violations != []


def test_mutation_nonhistorical_substring_role_must_fail() -> None:
    def inject(manifest):
        snapshot = manifest["git"]["current_milestone_b_development"]["historical_candidate_formation_snapshots"]["remediation_4"]
        snapshot["state_role"] = "nonhistorical_current_state"
        return [("historical_candidate_formation_snapshots", "remediation_4", "state_role")]
    _, violations, _ = _mutated_manifest(inject)
    assert violations != []


def test_mutation_unscoped_git_object_at_root_must_fail() -> None:
    def inject(manifest):
        manifest["git"]["injected_legacy"] = {
            "branch": "deepseek-injected",
            "commit": None,
            "commit_status": "pending",
        }
        return [("git", "injected_legacy")]
    _, violations, _ = _mutated_manifest(inject)
    assert violations != []


# ---------------------------------------------------------------------------
# AUDIT_HISTORY_SOURCE / 审计链一致性
# ---------------------------------------------------------------------------


def test_audit_history_chain_r1_to_r6_failed_and_r7_not_yet() -> None:
    manifest = _manifest()
    rounds = manifest["git"]["current_milestone_b_development"]["audit_history"]["rounds"]
    conclusions = {entry["audit_round"]: entry for entry in rounds}
    assert conclusions["initial"]["conclusion"] == "MILESTONE_B_INITIAL_INDEPENDENT_AUDIT_FAILED"
    assert conclusions[1]["conclusion"] == "MILESTONE_B_REMEDIATION_1_REAUDIT_FAILED"
    assert conclusions[2]["conclusion"] == "MILESTONE_B_REMEDIATION_2_REAUDIT_FAILED"
    assert conclusions[3]["conclusion"] == "MILESTONE_B_REMEDIATION_3_PRE_AUDIT_FAILED"
    assert conclusions[4]["conclusion"] == "MILESTONE_B_REMEDIATION_4_FINAL_REAUDIT_FAILED"
    assert conclusions[5]["conclusion"] == "MILESTONE_B_REMEDIATION_5_FINAL_REAUDIT_FAILED"
    assert conclusions[6]["conclusion"] == R6_CONCLUSION
    assert conclusions[6]["open_findings"] == ["R4-NEW-002", "R6-NEW-001", "R6-NEW-002"]
    assert conclusions[6]["closed_findings"] == {"R4-NEW-001": "CLOSED"}
    assert conclusions[7]["status"] == "NOT_YET_PERFORMED"
    assert conclusions[7]["conclusion"] == "NOT_YET_PERFORMED"

    persisted = manifest["git"]["current_milestone_b_development"]["persisted_project_state"]
    assert persisted["latest_completed_independent_reaudit"] == R6_CONCLUSION
    assert persisted["next_candidate"] == "MILESTONE_B_AUDIT_REMEDIATION_7"
    assert persisted["r6_finding_status"] == {
        "R4-NEW-002": "OPEN",
        "R6-NEW-001": "OPEN",
        "R6-NEW-002": "OPEN",
    }
    text = json.dumps(manifest, ensure_ascii=False)
    assert "MILESTONE_B_REMEDIATION_7_REAUDIT_PASSED" not in text
    assert "MILESTONE_B_AUDIT_REMEDIATION_7_TARGETED_REAUDIT" not in text


def test_legacy_migration_no_unscoped_current_live_left() -> None:
    manifest = _manifest()
    text = json.dumps(manifest, ensure_ascii=False)
    assert "【CURRENT LIVE】" not in text
    for record in manifest["checkpoints"]:
        rid = str(record.get("checkpoint_id") or record.get("id"))
        assert "state_role" in record, rid
        assert record["state_role"] in ALLOWED_STATE_ROLES, rid
        if rid == "MILESTONE_B_FORMAL_160_CARD_NO_SKILL_DUEL_ADVANCEMENT":
            assert record["status"] == "audited_failed"
            assert record["audit_conclusion"] == "REMEDIATION_1_REAUDIT_FAILED"
        if rid == "MILESTONE_B_AUDIT_REMEDIATION_1":
            assert record["status"] == "audited_failed"
            machine = record["historical_pre_audit_machine_state"]
            assert machine["state_role"] == "historical_snapshot"
            assert machine["snapshot_kind"] == "pre_audit_machine_state"
            assert machine["as_of"] == "2026-08-11"
        if rid == "MILESTONE_B_AUDIT_REMEDIATION_2":
            assert record["status"] == "audited_failed"


def test_root_git_has_no_unscoped_branch_scalars() -> None:
    manifest = _manifest()
    git = manifest["git"]
    assert set(git.keys()) == {"available", "current_milestone_b_development"}
    metadata = git["current_milestone_b_development"]["historical_development_state"]
    assert metadata["state_role"] == "historical_snapshot"
    assert metadata["snapshot_kind"] == "development_branch_and_commit_metadata"
    assert metadata["as_of"] == "2026-08-14"
    for key in metadata:
        if key in ("state_role", "snapshot_kind", "as_of", "note", "repository_local_identity"):
            continue
        assert _key_semantic_class(key) in (
            "commit", "branch", "worktree", "prose", "pending"
        ) or key in ("implementation_branch",), (key,)
    assert metadata["implementation_branch"] == "deepseek-single-target-tricks"
    assert metadata["duel_fire_attack_worktree_branch"] == "deepseek-duel-fire-attack"


def test_r7_formation_snapshot_is_explicit_historical() -> None:
    snapshot = _manifest()["git"]["current_milestone_b_development"][
        "historical_candidate_formation_snapshots"
    ]["remediation_7"]
    assert snapshot["state_role"] == "historical_snapshot"
    assert snapshot["snapshot_kind"] == "candidate_formation_precommit"
    assert snapshot["as_of"] == "2026-08-14"
    assert snapshot["base_commit"] == R7_BASE_COMMIT
    assert snapshot["parent_commit_at_formation"] == R7_PARENT_COMMIT
    assert snapshot["worktree_state_at_formation"] == "PRECOMMIT"
    assert snapshot["candidate_commit_at_formation"] is None
    assert snapshot["independent_reaudit_status_at_formation"] == "NOT_AUDITED_YET"


def test_post_commit_stability_no_future_sha_needed() -> None:
    manifest = _manifest()
    by_id = {str(r.get("checkpoint_id") or r.get("id")): r for r in manifest["checkpoints"]}
    r7 = by_id["MILESTONE_B_AUDIT_REMEDIATION_7"]
    assert "commit" not in r7
    for path, value, reason in _walk_all_scalars(manifest):
        if isinstance(value, str) and value == R7_BASE_COMMIT:
            assert "historical_candidate_formation_snapshots" in ".".join(map(str, path)), (path, value, reason)
    persisted = manifest["git"]["current_milestone_b_development"]["persisted_project_state"]
    assert not re.search(r"(?<![0-9a-f])[0-9a-f]{40}(?![0-9a-f])", json.dumps(persisted))


def _walk_all_scalars(node, path=()):
    if isinstance(node, dict):
        for key, value in node.items():
            if isinstance(value, (dict, list)):
                yield from _walk_all_scalars(value, path + (str(key),))
            else:
                yield path + (str(key),), value, ""
    elif isinstance(node, list):
        for index, value in enumerate(node):
            if isinstance(value, (dict, list)):
                yield from _walk_all_scalars(value, path + (str(index),))
            else:
                yield path + (str(index),), value, ""


def test_markdown_matches_canonical_audit_mapping() -> None:
    manifest = _manifest()
    rounds = manifest["git"]["current_milestone_b_development"]["audit_history"]["rounds"]
    canonical = {entry["audit_round"]: entry for entry in rounds}
    doc_names = (
        "ENGINE_STATUS.md",
        "IMPLEMENTATION_MATRIX.md",
        "MASTER_IMPLEMENTATION_PLAN.md",
        "MILESTONE_B_DEPENDENCY_GRAPH.md",
        "SOURCE_AND_CALLCHAIN_AUDIT.md",
    )
    for name in doc_names:
        text = (REPOSITORY_ROOT / "docs" / name).read_text(encoding="utf-8")
        assert canonical[4]["conclusion"] in text, name
        assert canonical[5]["conclusion"] in text, name
        assert canonical[6]["conclusion"] in text, name
        assert "MILESTONE_B_AUDIT_REMEDIATION_7" in text, name
        assert "NOT_YET_PERFORMED" in text, name
        assert not re.search(r"R5.{0,30}尚未(独立|经独立)复审", text), name
        assert not re.search(r"尚未(独立|经独立)复审.{0,30}R5", text), name
        assert "R6 候选" not in text, name
        assert "R6 尚未独立复审" not in text, name
        assert not re.search(r"R6（`MILESTONE_B_AUDIT_REMEDIATION_6`）尚未独立复审", text), name
