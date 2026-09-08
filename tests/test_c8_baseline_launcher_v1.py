# -*- coding: utf-8 -*-
"""Baseline身份/launcher cheap regression；禁止启动gameplay或replay worker。"""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path

import pytest
from scripts.sgs_engine import c8_baseline_launcher_v1 as launch
from scripts.sgs_engine import c8_bounded_timed_8p_trace_v1 as f
from scripts.sgs_engine import c8_strict_replay_v1 as d


@pytest.fixture(scope="module")
def identities():
    return {s: launch.construct_baseline_identity_v1(cell_id=f"C8G-FG-{s:03d}", seed=s)
            for s in (0, 1, 49)}


@pytest.fixture(scope="module")
def release():
    path = Path(os.environ["C8_BASELINE_TEST_RELEASE"])
    pin = os.environ["C8_BASELINE_TEST_RELEASE_SHA256"]
    return path, pin, launch.load_release_v1(path, expected_sha256=pin)


def plan_for(release, seed):
    path, pin, value = release
    cell = f"C8G-FG-{seed:03d}"
    return launch.launch_plan_v1(release_path=path, release_sha256=pin,
        cell_id=cell, seed=seed,
        artifact_root=str(Path(value["run_parent"]) / cell / "attempt-001"))


@pytest.mark.parametrize("seed", [0, 1, 49])
def test_constructor_valid_and_deterministic(identities, seed):
    value = identities[seed]
    assert launch.validate_baseline_identity_v1(value, cell_id=value["cell_id"], seed=seed) == value
    assert value["run_binding_identity"] == value["cell_execution_identity"]
    assert value["construction"]["seed"] == seed


@pytest.mark.parametrize("cell,seed", [("C8G-FG-000", 1), ("C8G-FG-001", 49),
    ("C8G-FG-049", 0), ("C8G-FG-999", 999), ("C8G-FG-002", 2),
    ("c8g-fg-001", 1), ("C8G-FG-01", 1), ("../C8G-FG-001", 1),
    ("C8G-FG-001", True), ("C8G-FG-000", False), ("C8G-FG-001", "1"),
    (None, 1), ("", 1), ("C8G-FG-001", -1)])
def test_wrong_pair_unknown_malformed_rejected(cell, seed):
    with pytest.raises((ValueError, TypeError)):
        launch.construct_baseline_identity_v1(cell_id=cell, seed=seed)


@pytest.mark.parametrize("key", ["shared_implementation_identity", "cell_execution_identity",
    "run_binding_identity", "seed_specific_input_identity", "session_binding_identity",
    "global_source_identity", "controller_instance_identity"])
def test_wrong_shared_or_cell_hash_rejected(identities, key):
    edited = deepcopy(identities[1]); edited[key] = "a" * 64
    edited["identity"] = launch.contract.identity_v1({k:v for k,v in edited.items() if k != "identity"})
    with pytest.raises(ValueError):
        launch.validate_baseline_identity_v1(edited, cell_id="C8G-FG-001", seed=1)


def test_shared_and_seed_specific_definition(identities):
    shared = ["shared_implementation_identity", "g1_identity", "g2_identity", "g3_current_implementation_identity",
              "global_source_identity", "driver_identity", "execution_order_profile"]
    specific = ["seed_specific_input_identity", "cell_execution_identity", "run_binding_identity",
                "session_binding_identity", "runtime_instance_identity", "controller_instance_identity", "identity"]
    for key in shared:
        assert identities[0][key] == identities[1][key] == identities[49][key]
    for key in specific:
        assert len({identities[s][key] for s in identities}) == 3


@pytest.mark.parametrize("label", ["c8_b_source", "c8_b_test", "c8_d_source", "c8_d_test"])
def test_four_shared_guards_remain_strict(monkeypatch, label):
    original = f._file_sha256
    target = (launch._root() / f._AUDITED_PATHS[label]).resolve()
    monkeypatch.setattr(f, "_file_sha256", lambda p: "0"*64 if p.resolve() == target else original(p))
    with pytest.raises(f.C8FTraceError, match="AUDITED_HASH_DRIFT"):
        launch.construct_baseline_identity_v1(cell_id="C8G-FG-001", seed=1)


def test_d_native_guard_and_latch_are_current():
    d._assert_current_dependencies()
    latch = d.C8DCurrentContractLatchV1.canonical()
    assert latch.c8_b_source_sha256 == hashlib.sha256(Path(d.rt.__file__).read_bytes()).hexdigest()
    assert latch.c8_d_current_implementation_identity == d.C8_D_CURRENT_IMPLEMENTATION_IDENTITY


@pytest.mark.parametrize("seed", [1, 49])
def test_launch_dry_run_no_terminal_or_old_proof(release, identities, seed, monkeypatch):
    popen = launch.subprocess.Popen
    def forbidden(*args, **kwargs):
        raise AssertionError("禁止启动worker或natural")
    def git_only(command, *args, **kwargs):
        if command[0] != "git":
            forbidden()
        return popen(command, *args, **kwargs)
    monkeypatch.setattr(launch.subprocess, "Popen", git_only)
    monkeypatch.setattr(launch.runner, "_execute_timed_v3", forbidden)
    plan = plan_for(release, seed)
    raw = json.dumps(plan, ensure_ascii=False)
    for forbidden_text in ("C8G-FG-000", "c8g-fg-000", "1677", "1631", "rebels", "identity_victory", "old_cell_proof"):
        # Arbitrary SHA digests may contain these digit substrings; inspect actual values below.
        if forbidden_text in ("1677", "1631"):
            assert f': {forbidden_text},' not in raw
        else:
            assert forbidden_text not in raw
    assert plan["identities"] == identities[seed]
    assert plan["natural_started"] is False and plan["pid"] is None
    assert not Path(plan["root"]).exists()
    assert plan["environment"] == {"PYTHONHASHSEED": "0", "PYTHONDONTWRITEBYTECODE": "1"}
    assert plan["detached_owner"]["creationflags"] == launch.CREATE_FLAGS
    assert plan["owner_command"][plan["owner_command"].index("--seed")+1] == str(seed)


@pytest.mark.parametrize("seed", [1, 49])
def test_other_cell_root_and_seed0_root_rejected(release, seed):
    path, pin, value = release
    root = Path(value["run_parent"])
    for wrong in (root / "C8G-FG-000" / "attempt-001", root / "C8G-FG-001" / ".." / "attempt-001",
                  launch._root(), root / f"C8G-FG-{seed:03d}" / "seed0-proof"):
        with pytest.raises(ValueError):
            launch.launch_plan_v1(release_path=path, release_sha256=pin,
                cell_id=f"C8G-FG-{seed:03d}", seed=seed, artifact_root=str(wrong))


@pytest.mark.parametrize("key", ["old_cell_proof", "terminal", "winner", "accepted_steps", "identities"])
def test_seed0_proof_or_identity_cannot_be_injected_into_launcher(release, identities, key, monkeypatch):
    plan = plan_for(release, 1)
    plan[key] = identities[0] if key == "identities" else "C8G-FG-000 sealed evidence"
    with pytest.raises(ValueError, match="启动计划全部材料"):
        launch.detached_launch_v1(plan, authorization=plan["authorization"])
    assert not Path(plan["root"]).exists()


def test_seed0_sealed_launcher_rejected(release):
    with pytest.raises(ValueError, match="封存"):
        plan_for(release, 0)


def test_release_wrong_independent_pin_rejected(release):
    with pytest.raises(ValueError, match="独立pin"):
        launch.load_release_v1(release[0], expected_sha256="0" * 64)


def test_formal_bundle_wrong_seed_or_run_label_rejected():
    with pytest.raises(ValueError):
        launch.runner.create_canonical_session_bundle_v1(seed=1, run_label="c8g-fg-001-s1", baseline_cell_id="C8G-FG-049")


def test_formal_formula_preserved(identities):
    for seed, value in identities.items():
        binding = launch.runner.current_binding_snapshot_v1(launch.contract.FullGameRegistryV1.canonical())
        expected = launch.contract.identity_v1({"schema": "sgs-c8-g-cell-execution-v1",
            "construction": value["construction"], "session_binding_identity": value["session_binding_identity"],
            "g2_binding_identity": launch.contract.identity_v1(binding)})
        assert value["cell_execution_identity"] == expected


@pytest.mark.parametrize("seed", [0, 1, 49])
def test_step_zero_live_binding_matches_description(identities, seed):
    value = identities[seed]
    bundle = launch.runner.create_canonical_session_bundle_v1(seed=seed,
        run_label=value["run_label"], baseline_cell_id=value["cell_id"])
    assert bundle.session.step_count == 0
    assert bundle.session_binding_identity == value["session_binding_identity"]
    assert bundle.runtime_instance_identity == value["runtime_instance_identity"]
    assert bundle.controller_instance_identity == value["controller_instance_identity"]
    actual = launch.runner.construct_timed_execution_identity_v1(repo_root=launch._root(),
        session_binding_identity=bundle.session_binding_identity, seed=seed,
        run_label=value["run_label"], max_steps=4000, max_windows=8192)
    assert actual["cell_execution_identity"] == value["cell_execution_identity"]


def test_description_does_not_consume_controller_owner_registry():
    c = launch.runner.controller_v1
    before = dict(c._RUNTIME_OWNER_REGISTRY)
    for _ in range(2):
        launch.construct_baseline_identity_v1(cell_id="C8G-FG-001", seed=1)
    assert c._RUNTIME_OWNER_REGISTRY == before


def test_public_session_id_preserves_fresh_signing_secret():
    mode = launch.runner.prod.canonical_no_skill_mode_v1(launch.contract.C8_G1_BASE_MODE_ID)
    public_id = launch.runner.baseline_public_session_id_v1(cell_id="C8G-FG-001", seed=1, run_label="c8g-fg-001-s1")
    first = mode.create_session(1, session_id=public_id)
    second = mode.create_session(1, session_id=public_id)
    assert first.session_id == second.session_id == public_id
    assert first.step_count == second.step_count == 0
    assert tuple(a.action_type for a in first.legal_actions()) == tuple(a.action_type for a in second.legal_actions())
    # PREPARE public action IDs need not contain a secret-dependent card handle.
    # Compare only in memory; neither secret nor commitment is emitted as evidence.
    secrets_are_fresh = first.session_secret_hex != second.session_secret_hex
    assert secrets_are_fresh, "canonical factory必须fresh生成签名secret"


def test_existing_artifact_root_rejected(tmp_path):
    root = tmp_path / "C8G-FG-001" / "attempt-001"
    root.mkdir(parents=True)
    with pytest.raises(ValueError, match="复用"):
        launch._run_root({"run_parent": str(tmp_path)}, "C8G-FG-001", str(root), fresh=True)


def test_seed0_historical_source_and_proof_preserved():
    release_path = Path(os.environ["C8_BASELINE_TEST_RELEASE"])
    migration_path = Path(os.environ.get("C8_BASELINE_TEST_HISTORY_MIGRATION", str(release_path.parent.parent / "IDENTITY_MIGRATION.json")))
    report_root = migration_path.parent
    migration = json.loads(migration_path.read_text(encoding="utf-8"))
    for rel, expected in migration["historical_current_source"].items():
        assert launch._hash(report_root / "support/historical-audited-current" / rel) == expected
    manifest_path = Path(migration["historical_protected_manifest"])
    assert launch._hash(manifest_path) == migration["historical_protected_manifest_sha256"]
    # Check frozen proof bytes directly; no re-signing or replay.
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    proofs = {p:h for p,h in manifest.items() if h == "120322adefb35f2bcbd8f3c480f8b40ad8d8da653a0ea584358afa4e27680464"}
    assert proofs
    for p, expected in proofs.items():
        assert launch._hash(Path(p)) == expected


def test_response_remediated_release_requires_fresh_v2_authority(release):
    plan = plan_for(release, 1)
    assert plan["authorization"] == "C8G_FG_001_SEED1_NATURAL_FASTPATH_V2"
    assert plan["launch_command"][-1] == plan["owner_command"][-1] == plan["authorization"]
    assert plan["natural_started"] is False and plan["pid"] is None
