# -*- coding: utf-8 -*-
"""MILESTONE_B_AUDIT_REMEDIATION_8 定向回归：R7-NEW-001 收口。

R7 targeted re-audit（MILESTONE_B_REMEDIATION_7_TARGETED_REAUDIT_FAILED）唯一新
blocker：R7-NEW-001——validator 仍把 state_role 部分视为节点自声明，canonical
node 可通过删除 role、置 null、或在合法枚举间换角色来绕过 schema。

本轮修复原则（PATH_ROLE_BINDING）：

    canonical path / node type
    → CANONICAL_NODE_REGISTRY 决定唯一允许的 state_role
    → 节点声明必须精确匹配

validator 决定角色，数据只能证明自己符合该角色；节点不能自行换角色。
缺失/null/空串/非法值/合法枚举互换一律 fail closed，即使节点同时补齐目标
角色的其它要件（as_of/snapshot_kind 等）仍必须失败。

persisted_current 采用递归 schema（nested dict/list 的白名单逐层校验），
未知 sibling、nested key、list item state object 全部 fail closed。
"""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = REPOSITORY_ROOT / "docs" / "CHECKPOINT_MANIFEST.json"

R7_CONCLUSION = "MILESTONE_B_REMEDIATION_7_TARGETED_REAUDIT_FAILED"
R8_BASE_COMMIT = "7c5d172d3fcaaf0a71921eb415a9e94e04231dfa"
R8_PARENT_COMMIT = "758de61ad2fc984aabebb7f4f1fb4837ffb8f47b"

ALLOWED_STATE_ROLES = frozenset(
    {"persisted_current", "historical_snapshot", "audit_history"}
)

GIT_SEMANTIC_KEY_RE = re.compile(
    r"(?<![a-z0-9])(worktree|branch|head|staged|untracked|dirty|clean|precommit|commit|pending)(?![a-z0-9])",
    re.IGNORECASE,
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

CANDIDATE_ALLOWED_STATUS = frozenset({"candidate_awaiting_independent_reaudit"})

FV_AUDIT_ENTRY_NAMES = frozenset(
    {
        "cp04j_final_reaudit",
        "hidden_handle_security_fix",
        "milestone_b_audit_remediation_1",
        "milestone_b_audit_remediation_2",
    }
)
FV_SNAPSHOT_ENTRY_NAMES = frozenset(
    {
        "test_only_duel_status",
        "formal_status",
        "milestone_b_analysis_seed_diagnostic",
        "milestone_b_blockers",
        "milestone_b_audit_remediation_3",
        "historical_milestone_b_formal_duel_advancement_precommit_snapshot",
    }
)

# ---------------------------------------------------------------------------
# 递归 schema（persisted_current 白名单逐层校验）
# ---------------------------------------------------------------------------

PERSISTED_PROJECT_STATE_SCHEMA = {
    "state_role": "str",
    "layer": "str",
    "formal_duel_capability": "str",
    "latest_completed_independent_reaudit": "str",
    "next_candidate": "str",
    "next_candidate_independent_reaudit": "str",
    "historical_audit_chain": "list[str]",
    "r3_finding_status": "dict[str,str]",
    "r4_open_findings": "list[str]",
    "r4_closed_findings": "dict[str,str]",
    "r6_finding_status": "dict[str,str]",
    "r7_finding_status": "dict[str,str]",
    "implementation_identity_policy": "str",
    "audit_history_reference": "str",
}

CANDIDATE_RECORD_SCHEMA = {
    "checkpoint_id": "str",
    "batch_name": "str",
    "state_role": "str",
    "status": "enum",
    "independent_reaudit_status": "str",
    "audit_conclusion": "str",
    "latest_completed_independent_reaudit": "str",
    "remediation_scope": "list[str]",
    "historical_base_reference": "str",
    "candidate_identity_policy": "str",
    "implementation_note": "str",
    "independent_reaudit_note": "str",
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

ROUND_ENTRY_SCHEMA = {
    "audit_round": "int|str",
    "conclusion": "str",
    "status": "str",
    "open_findings": "list[str]",
    "closed_findings": "dict[str,str]",
    "final_sol_reaudit": "str",
}


def _check_value_schema(value, spec, violations, path, context):
    if spec == "str":
        if not isinstance(value, str):
            violations.append((path, value, context + " expected str"))
    elif spec == "bool":
        if not isinstance(value, bool):
            violations.append((path, value, context + " expected bool"))
    elif spec == "int|str":
        if not isinstance(value, (int, str)):
            violations.append((path, value, context + " expected int|str"))
    elif spec == "enum":
        if value not in CANDIDATE_ALLOWED_STATUS:
            violations.append((path, value, context + f" expected one of {sorted(CANDIDATE_ALLOWED_STATUS)}"))
    elif spec == "list[str]":
        if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
            violations.append((path, value, context + " expected list[str]"))
    elif spec == "dict[str,str]":
        if not isinstance(value, dict) or any(
            not isinstance(k, str) or not isinstance(v, str) for k, v in value.items()
        ):
            violations.append((path, value, context + " expected dict[str,str]"))
    else:  # pragma: no cover
        raise AssertionError(spec)


def _validate_schema(node, schema, violations, path, context):
    for key in node:
        if key not in schema:
            violations.append(
                (path + (str(key),), node[key],
                 context + f" unknown field {key!r} (recursive schema fail-closed)")
            )
    for key, spec in schema.items():
        if key in node:
            _check_value_schema(node[key], spec, violations, path + (str(key),), context)


# ---------------------------------------------------------------------------
# CANONICAL_NODE_REGISTRY：path/node-type → required role + schema
# ---------------------------------------------------------------------------

def _make_rules():
    rules = []

    def rule(matcher, role, schema=None, description=""):
        rules.append({
            "matches": matcher,
            "required_role": role,
            "schema": schema,
            "description": description,
        })

    def matcher_persisted(node, path, ctx):
        if bool(path) and path[-1] == "persisted_project_state":
            return True
        return not path and "formal_duel_capability" in node

    rule(matcher_persisted, "persisted_current", PERSISTED_PROJECT_STATE_SCHEMA,
         "persisted_project_state")

    def matcher_candidate(node, path, ctx):
        if not (len(path) == 2 and path[0] == "checkpoints"):
            return False
        rid = str(node.get("checkpoint_id") or node.get("id") or "")
        next_candidate = ctx.get("next_candidate", "")
        return rid and rid == next_candidate

    rule(matcher_candidate, "persisted_current", CANDIDATE_RECORD_SCHEMA,
         "current remediation candidate record")

    def matcher_feature(node, path, ctx):
        if bool(path) and path[-1] == "feature_status":
            return True
        return not path and "authoritative_core_foundation" in node

    rule(matcher_feature, "persisted_current",
         {"state_role": "str", **{k: "bool" for k in FEATURE_STATUS_KEYS}},
         "feature_status")

    def matcher_stage(node, path, ctx):
        if bool(path) and path[-1] == "stage_status":
            return True
        return not path and "1_source_and_callchain_audit" in node

    rule(matcher_stage, "persisted_current",
         {"state_role": "str", **{k: "str" for k in STAGE_STATUS_KEYS}},
         "stage_status")

    def matcher_snapshot_collection(node, path, ctx):
        return bool(path) and path[-1] == "historical_candidate_formation_snapshots"

    rule(matcher_snapshot_collection, "historical_snapshot", None,
         "historical_candidate_formation_snapshots collection")

    def matcher_formation_snapshot(node, path, ctx):
        return len(path) >= 2 and path[-2] == "historical_candidate_formation_snapshots"

    rule(matcher_formation_snapshot, "historical_snapshot", None,
         "historical_candidate_formation_snapshots.* entry")

    def matcher_development_state(node, path, ctx):
        return bool(path) and path[-1] == "historical_development_state"

    rule(matcher_development_state, "historical_snapshot", None,
         "historical_development_state")

    def matcher_audit_history(node, path, ctx):
        return bool(path) and path[-1] == "audit_history"

    rule(matcher_audit_history, "audit_history", None, "audit_history")

    def matcher_audit_round(node, path, ctx):
        return len(path) >= 2 and path[-2:] == ("audit_history", "rounds")

    rule(matcher_audit_round, "audit_history", ROUND_ENTRY_SCHEMA,
         "audit_history.rounds entry")

    def matcher_embedded_snapshot(node, path, ctx):
        return (
            len(path) >= 3
            and path[0] == "checkpoints"
            and "snapshot_kind" in node
            and "as_of" in node
        )

    rule(matcher_embedded_snapshot, "historical_snapshot", None,
         "record-embedded historical snapshot")

    def matcher_checkpoint_record(node, path, ctx):
        return len(path) == 2 and path[0] == "checkpoints"

    rule(matcher_checkpoint_record, "audit_history", None, "checkpoints record")

    def matcher_fv_audit(node, path, ctx):
        if len(path) != 2 or path[0] != "final_verification":
            return False
        name = path[1]
        return name in FV_AUDIT_ENTRY_NAMES or name.startswith("production_") or name.startswith("whole_repo_audit_remediation_")

    rule(matcher_fv_audit, "audit_history", None, "final_verification audit entry")

    def matcher_fv_snapshot(node, path, ctx):
        return len(path) == 2 and path[0] == "final_verification" and path[1] in FV_SNAPSHOT_ENTRY_NAMES

    rule(matcher_fv_snapshot, "historical_snapshot", None, "final_verification snapshot entry")

    def matcher_generic_snapshot(node, path, ctx):
        # 仅用于非 canonical 路径的合成节点；真实 manifest 节点全部命中上面的规则。
        return "snapshot_kind" in node and "as_of" in node

    rule(matcher_generic_snapshot, "historical_snapshot", None, "generic snapshot node (synthetic only)")

    return rules


REGISTRY_RULES = _make_rules()


def registry_match(node, path, ctx):
    for rule in REGISTRY_RULES:
        if rule["matches"](node, path, ctx):
            return rule
    return None


# ---------------------------------------------------------------------------
# 语义层（defense-in-depth；与 R7 一致，但角色由 registry 绑定）
# ---------------------------------------------------------------------------

def _key_semantic_class(key):
    lowered = str(key).lower()
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


def _is_state_bearing(node):
    if any(k in AUDIT_SEMANTIC_KEYS for k in node):
        return True
    return any(_key_semantic_class(k) is not None for k in node)


def _ctx(manifest):
    dev = manifest.get("git", {}).get("current_milestone_b_development", {})
    return {
        "next_candidate": dev.get("persisted_project_state", {}).get("next_candidate", ""),
    }


def validate_manifest(manifest):
    violations: list = []
    ctx = _ctx(manifest)
    walk_bound(manifest, violations, path=(), bound_role=None, ctx=ctx)
    cross_check_audit_history(manifest, violations)
    return violations


def walk_bound(node, violations, path, bound_role, ctx, is_container=False):
    if isinstance(node, dict):
        matched = registry_match(node, path, ctx)
        declared = node.get("state_role", "<missing>")
        if matched is not None:
            if not isinstance(declared, str) or declared == "":
                violations.append(
                    (path + ("state_role",), declared,
                     f"canonical {matched['description']} missing state_role (fail closed)")
                )
            elif declared != matched["required_role"]:
                violations.append(
                    (path + ("state_role",), declared,
                     f"canonical {matched['description']} requires {matched['required_role']!r}, got {declared!r} (legal role swap fails closed)")
                )
            if matched["schema"] is not None and declared == matched["required_role"]:
                _validate_schema(node, matched["schema"], violations, path,
                                 f"{matched['description']}:")
            role = matched["required_role"]
        else:
            role = bound_role

        if role == "historical_snapshot" and matched is not None:
            if not isinstance(node.get("as_of"), str) or not node.get("as_of"):
                violations.append((path, None, "historical_snapshot missing as_of"))
            if not isinstance(node.get("snapshot_kind"), str) or not node.get("snapshot_kind"):
                violations.append((path, None, "historical_snapshot missing snapshot_kind"))
        if role == "audit_history" and matched is not None:
            note = node.get("commit_note")
            if isinstance(note, str) and ("【CURRENT LIVE】" in note or note.startswith("【CURRENT LIVE】")):
                violations.append((path + ("commit_note",), None, "audit_history carries CURRENT LIVE marker"))

        if role is None and matched is None and not is_container and _is_state_bearing(node):
            violations.append((path, None, "unclassified state node (not covered by canonical node registry)"))

        for key, value in node.items():
            child_role = role
            child_is_container = str(key) in CONTAINER_KEYS
            semantic = _key_semantic_class(key)
            audit_semantic = str(key) in AUDIT_SEMANTIC_KEYS
            if isinstance(value, (dict, list)):
                walk_bound(value, violations, path + (str(key),), child_role, ctx,
                           is_container=child_is_container)
                continue
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
                sibling = node.get("audit_conclusion")
                if sibling == "NOT_AUDITED_YET" and role != "historical_snapshot":
                    violations.append((path + (str(key),), value, "not-audited machine state outside historical_snapshot"))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            walk_bound(value, violations, path + (str(index),), bound_role, ctx,
                       is_container=is_container)


def cross_check_audit_history(manifest, violations):
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
    canonical_chain = [entry.get("conclusion") for entry in rounds if entry.get("status") != "NOT_YET_PERFORMED"]
    if list(persisted_chain) != list(canonical_chain):
        violations.append((("persisted_project_state", "historical_audit_chain"), persisted_chain, "chain diverges from audit_history"))


# ---------------------------------------------------------------------------
# canonical roots 覆盖报告
# ---------------------------------------------------------------------------

def canonical_root_report(manifest):
    rows = []
    ctx = _ctx(manifest)

    def walk(node, path=()):
        if isinstance(node, dict):
            matched = registry_match(node, path, ctx)
            if matched is not None:
                rows.append({
                    "path": ".".join(str(p) for p in path) or "<root>",
                    "expected_role": matched["required_role"],
                    "actual_role": node.get("state_role"),
                    "registry_source": matched["description"],
                    "ok": (
                        isinstance(node.get("state_role"), str)
                        and node.get("state_role") == matched["required_role"]
                    ),
                })
            for key, value in node.items():
                if isinstance(value, (dict, list)):
                    walk(value, path + (str(key),))
        elif isinstance(node, list):
            for index, value in enumerate(node):
                walk(value, path + (str(index),))

    walk(manifest)
    violations = validate_manifest(manifest)
    unclassified = sum(1 for v in violations if str(v[2]).startswith("unclassified"))
    mismatches = [row for row in rows if not row["ok"]]
    return rows, mismatches, unclassified, violations


def _manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# 真实 manifest 基线
# ---------------------------------------------------------------------------


def test_real_manifest_passes_registry_bound_validator() -> None:
    assert validate_manifest(_manifest()) == []


def test_canonical_roots_fully_covered_and_bound() -> None:
    rows, mismatches, unclassified, violations = canonical_root_report(_manifest())
    assert mismatches == []
    assert unclassified == 0, [v for v in violations if str(v[2]).startswith("unclassified")]
    assert len(rows) > 40
    print(
        f"CANONICAL_ROOT_COVERAGE: registry-bound nodes={len(rows)}, "
        f"mismatches={len(mismatches)}, unclassified={unclassified}"
    )


# ---------------------------------------------------------------------------
# 固定 blocker matrix（真实 manifest deepcopy；原文件不落盘）
# ---------------------------------------------------------------------------

def _mutated(mutator):
    mutated = copy.deepcopy(_manifest())
    mutator(mutated)
    return mutated, validate_manifest(mutated)


def test_matrix_A_missing_persisted_role_must_fail() -> None:
    def m(m):
        del m["git"]["current_milestone_b_development"]["persisted_project_state"]["state_role"]
    _, violations = _mutated(m)
    assert violations != []


def test_matrix_B_null_persisted_role_must_fail() -> None:
    def m(m):
        m["git"]["current_milestone_b_development"]["persisted_project_state"]["state_role"] = None
    _, violations = _mutated(m)
    assert violations != []


def test_matrix_C_persisted_to_historical_with_full_credentials_must_fail() -> None:
    def m(m):
        persisted = m["git"]["current_milestone_b_development"]["persisted_project_state"]
        persisted["state_role"] = "historical_snapshot"
        persisted["as_of"] = "2026-08-14"
        persisted["snapshot_kind"] = "candidate_formation_precommit"
    _, violations = _mutated(m)
    assert violations != []


def test_matrix_D_persisted_to_audit_history_must_fail() -> None:
    def m(m):
        m["git"]["current_milestone_b_development"]["persisted_project_state"]["state_role"] = "audit_history"
    _, violations = _mutated(m)
    assert violations != []


def test_matrix_E_historical_to_persisted_must_fail() -> None:
    def m(m):
        snap = m["git"]["current_milestone_b_development"]["historical_candidate_formation_snapshots"]["remediation_8"]
        snap["state_role"] = "persisted_current"
    _, violations = _mutated(m)
    assert violations != []


def test_matrix_F_audit_history_to_historical_must_fail() -> None:
    def m(m):
        ah = m["git"]["current_milestone_b_development"]["audit_history"]
        ah["state_role"] = "historical_snapshot"
        ah["as_of"] = "2026-08-14"
        ah["snapshot_kind"] = "audit_history_as_snapshot"
    _, violations = _mutated(m)
    assert violations != []


def test_matrix_G_candidate_missing_role_must_fail() -> None:
    def m(m):
        for record in m["checkpoints"]:
            if str(record.get("checkpoint_id")) == "MILESTONE_B_AUDIT_REMEDIATION_8":
                del record["state_role"]
                return
        raise AssertionError("candidate record not found")
    _, violations = _mutated(m)
    assert violations != []


def test_matrix_H_candidate_swapped_to_legal_role_must_fail() -> None:
    def m(m):
        for record in m["checkpoints"]:
            if str(record.get("checkpoint_id")) == "MILESTONE_B_AUDIT_REMEDIATION_8":
                record["state_role"] = "audit_history"
                return
        raise AssertionError("candidate record not found")
    _, violations = _mutated(m)
    assert violations != []


def test_matrix_I_nested_dict_git_injection_must_fail() -> None:
    def m(m):
        persisted = m["git"]["current_milestone_b_development"]["persisted_project_state"]
        persisted["r3_finding_status"]["candidate_commit"] = None
    _, violations = _mutated(m)
    assert violations != []


def test_matrix_J_nested_list_dict_injection_must_fail() -> None:
    def m(m):
        persisted = m["git"]["current_milestone_b_development"]["persisted_project_state"]
        persisted["historical_audit_chain"].append({"repository_head": "deadbeef"})
    _, violations = _mutated(m)
    assert violations != []


def test_matrix_K_deep_nested_unknown_must_fail() -> None:
    def m(m):
        persisted = m["git"]["current_milestone_b_development"]["persisted_project_state"]
        persisted["r6_finding_status"]["nested"] = {"random_future_git_field": "x"}
    _, violations = _mutated(m)
    assert violations != []


def test_matrix_L_legal_historical_snapshot_passes() -> None:
    node = {
        "state_role": "historical_snapshot",
        "snapshot_kind": "candidate_formation_precommit",
        "as_of": "2026-08-09",
        "checkpoint_commit": None,
        "commit": None,
        "commit_status": "pending",
        "branch": "sol-ultra-milestone-b-formal-duel",
        "worktree_state_at_formation": "PRECOMMIT",
    }
    assert validate_manifest(node) == []


def test_matrix_M_legal_audit_history_canonical_record_passes() -> None:
    assert validate_manifest(_manifest()) == []
    record = next(
        r for r in _manifest()["checkpoints"]
        if str(r.get("checkpoint_id")) == "MILESTONE_B_AUDIT_REMEDIATION_7"
    )
    assert record["state_role"] == "audit_history"
    assert record["audit_conclusion"] == R7_CONCLUSION
    assert record["closed_findings"] == {
        "R4-NEW-002": "CLOSED",
        "R6-NEW-001": "CLOSED",
        "R6-NEW-002": "CLOSED",
    }
    assert record["open_findings"] == ["R7-NEW-001"]


def test_matrix_N_legal_persisted_current_baseline_passes() -> None:
    persisted = _manifest()["git"]["current_milestone_b_development"]["persisted_project_state"]
    assert validate_manifest(persisted) == []


# ---------------------------------------------------------------------------
# R7 旧绕过回归（不能因 R8 修复重新开放）
# ---------------------------------------------------------------------------

def test_r7_bypass_regression_still_closed() -> None:
    cases = [
        {"state_role": "persisted_current", "formal_duel_capability": "x", "checkpoint_commit": None},
        {"state_role": "persisted_current", "formal_duel_capability": "x", "final_doc_commit": None},
        {"state_role": "persisted_current", "formal_duel_capability": "x", "implementation_worktree_branch": "deepseek-x"},
        {"state_role": "persisted_current", "formal_duel_capability": "x", "status": "committed_pending_audit"},
        {"state_role": "nonhistorical_current_state", "branch": "x"},
        {"git": {"milestone_b_audit_remediation_1": {"branch": "b", "commit": None, "commit_status": "pending"}}},
        {
            "checkpoints": [
                {
                    "checkpoint_id": "MILESTONE_B_AUDIT_REMEDIATION_1",
                    "state_role": "audit_history",
                    "commit_note": "【CURRENT LIVE】伪造",
                    "independent_audit_done": True,
                    "audit_conclusion": "MILESTONE_B_REMEDIATION_1_REAUDIT_FAILED",
                    "machine_state": {"independent_audit_done": False, "audit_conclusion": "NOT_AUDITED_YET"},
                }
            ]
        },
    ]
    for case in cases:
        assert validate_manifest(case) != [], case
    persisted_unknown = {
        "state_role": "persisted_current",
        "formal_duel_capability": "x",
        "random_future_git_field": "x",
    }
    assert validate_manifest(persisted_unknown) != []
    nested_unknown = {
        "state_role": "persisted_current",
        "formal_duel_capability": "x",
        "r3_finding_status": {"R3-NEW-001": {"deep": "x"}},
    }
    assert validate_manifest(nested_unknown) != []


# ---------------------------------------------------------------------------
# 审计历史 / 提交后稳定性
# ---------------------------------------------------------------------------

def test_audit_history_chain_r1_to_r7_failed_and_r8_not_yet() -> None:
    manifest = _manifest()
    rounds = manifest["git"]["current_milestone_b_development"]["audit_history"]["rounds"]
    by_round = {entry["audit_round"]: entry for entry in rounds}
    for round_number, conclusion in {
        "initial": "MILESTONE_B_INITIAL_INDEPENDENT_AUDIT_FAILED",
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


def test_r8_formation_snapshot_explicit_historical() -> None:
    snap = _manifest()["git"]["current_milestone_b_development"][
        "historical_candidate_formation_snapshots"
    ]["remediation_8"]
    assert snap["state_role"] == "historical_snapshot"
    assert snap["snapshot_kind"] == "candidate_formation_precommit"
    assert snap["as_of"] == "2026-08-14"
    assert snap["base_commit"] == R8_BASE_COMMIT
    assert snap["parent_commit_at_formation"] == R8_PARENT_COMMIT
    assert snap["candidate_commit_at_formation"] is None


def test_post_commit_stability_no_future_r8_sha() -> None:
    manifest = _manifest()
    by_id = {str(r.get("checkpoint_id") or r.get("id")): r for r in manifest["checkpoints"]}
    r8 = by_id["MILESTONE_B_AUDIT_REMEDIATION_8"]
    assert "commit" not in r8
    assert r8["state_role"] == "persisted_current"
    for record in manifest["checkpoints"]:
        if str(record.get("checkpoint_id")) == "MILESTONE_B_AUDIT_REMEDIATION_7":
            assert "commit" not in record
    persisted = manifest["git"]["current_milestone_b_development"]["persisted_project_state"]
    assert not re.search(r"(?<![0-9a-f])[0-9a-f]{40}(?![0-9a-f])", json.dumps(persisted))
    invariants = manifest["git"]["current_milestone_b_development"]["documentation_invariants"]
    assert (
        "A canonical state node's state_role is decided by the canonical node registry, never by the node's own declaration."
        in invariants
    )


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
        assert canonical[4]["conclusion"] in text, name
        assert canonical[5]["conclusion"] in text, name
        assert canonical[6]["conclusion"] in text, name
        assert canonical[7]["conclusion"] in text, name
        assert "MILESTONE_B_AUDIT_REMEDIATION_8" in text, name
        assert "NOT_YET_PERFORMED" in text, name
        assert "R7 候选" not in text, name
        assert "R7 尚未独立复审" not in text, name
        assert not re.search(r"R7（`MILESTONE_B_AUDIT_REMEDIATION_7`）尚未独立复审", text), name
        assert not re.search(r"R5.{0,30}尚未(独立|经独立)复审", text), name
        assert "R6 候选" not in text, name
