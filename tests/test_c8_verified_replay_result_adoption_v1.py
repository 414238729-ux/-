# -*- coding: utf-8 -*-
"""固定真实证据的廉价 adoption 验证；绝不启动 replay 或伪造审计 YES。"""
import ast
import copy
import hashlib
import json
import os
from pathlib import Path
from dataclasses import replace

import pytest
from scripts.sgs_engine import c8_verified_replay_result_adoption_v1 as a
from scripts.sgs_engine import c8_timed_replay_version_compatibility_v1 as c
from scripts.sgs_engine import c8_timed_8p_full_game_production_replay_v1 as g3
from scripts.sgs_engine import c8_timed_8p_full_game_contract_v1 as g1


@pytest.fixture(scope="module")
def material():
    config_path = os.environ.get("C8_ADOPTION_TEST_CONFIG")
    if not config_path:
        pytest.skip("需要独立固定的 adoption 测试配置；不自动执行 gameplay")
    config = json.loads(Path(config_path).read_bytes())
    policy = a.PinnedAdoptionPolicyV1.load(Path(config["policy"]), expected_sha256=config["policy_sha256"])
    envelopes = {kind: Path(config[kind.lower()+"_envelope"]).read_bytes() for kind in ("INNER", "TIMED")}
    latch = a.resign_current_latch_v1(policy=policy, inner_envelope=envelopes["INNER"], timed_envelope=envelopes["TIMED"])
    return config, policy, envelopes, latch


@pytest.fixture(autouse=True)
def forbidden_replay(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("adoption 验证不得运行任何 replay worker")
    for name in ("_fresh_inner", "_fresh_timed", "_cold_workers", "_fresh_unresolved"):
        # Comparison descriptor uses inspect.getsource(_fresh_inner), so preserve
        # that function and guard its underlying C6 execution / cold constructor.
        if name != "_fresh_inner":
            monkeypatch.setattr(g3, name, forbidden)
    monkeypatch.setattr(g3.PrivateIncrementalC6RecorderV1, "cold_session", forbidden)


def rehash(e):
    e["envelope_identity"] = c.identity({k: v for k, v in e.items() if k != "envelope_identity"})
    return c.canonical(e)


@pytest.mark.parametrize("kind", ["INNER", "TIMED"])
def test_exact_original_result_accepted(material, kind):
    _, policy, envelopes, _ = material
    result = a.validate_envelope_v1(envelopes[kind], expected_kind=kind, policy=policy)
    assert result["binding"]["result_type"] == kind
    assert result["authority_path"] == a.AUTHORITY
    assert result["binding"]["comparison_status"] == "MATCH"


@pytest.mark.parametrize("mutation", ["natural", "artifact", "seed", "cell", "producer", "verifier", "worker", "comparison", "policy_version", "missing_provenance", "failed", "timeout", "partial", "other_run", "inner_for_timed", "timed_for_inner", "unknown_pair", "unrehashed", "extra"])
def test_tamper_unknown_pair_partial_and_kind_substitution_fail_closed(material, mutation):
    _, policy, envelopes, _ = material
    e = json.loads(envelopes["INNER"]); b = e["binding"]; expected = "INNER"
    if mutation == "natural": b["natural_sha256"] = "0"*64
    elif mutation == "artifact": b["result_artifact_sha256"] = "1"*64
    elif mutation == "seed": b["seed"] += 1
    elif mutation == "cell": b["cell_id"] = "C8G-FG-049"
    elif mutation == "producer": b["original_producer_identity"] = "2"*64
    elif mutation == "verifier": b["current_verifier_identity"] = "3"*64
    elif mutation == "worker": b["worker_source_identity"] = "4"*64
    elif mutation == "comparison": b["comparison_contract"]["replay_schema"] = "wrong"
    elif mutation == "policy_version": e["policy_version"] += 1
    elif mutation == "missing_provenance": del b["fresh_execution_provenance"]
    elif mutation == "failed": b["result_status"] = "FAILED"
    elif mutation == "timeout": b["result_status"] = "TIMEOUT"
    elif mutation == "partial": b["complete"] = False
    elif mutation == "other_run": b["fresh_execution_identity"] = "5"*64
    elif mutation == "inner_for_timed": expected = "TIMED"
    elif mutation == "timed_for_inner": e = json.loads(envelopes["TIMED"])
    elif mutation == "unknown_pair": b["result_identity"] = "6"*64
    elif mutation == "unrehashed": e["policy_identity"] = "7"*64
    elif mutation == "extra": e["replay_verified"] = True
    raw = c.canonical(e) if mutation == "unrehashed" else rehash(e)
    with pytest.raises(ValueError):
        a.validate_envelope_v1(raw, expected_kind=expected, policy=policy)


def test_policy_self_asserted_pin_cannot_replace_independent_pin(material):
    _, policy, _, _ = material
    p = json.loads(policy.raw)
    p["pairs"]["INNER"]["result_artifact_sha256"] = "8"*64
    p["policy_identity"] = c.identity({k: v for k, v in p.items() if k != "policy_identity"})
    with pytest.raises(ValueError, match="独立 policy pin"):
        replace(policy, raw=c.canonical(p)).validate()


@pytest.mark.parametrize("kind", ["INNER", "TIMED"])
def test_semantically_identical_result_with_changed_bytes_is_rejected(material, monkeypatch, kind):
    _, policy, envelopes, _ = material
    target = Path(policy.validate()["files"][kind.lower()+"_result"]["path"])
    original = Path.read_bytes
    def altered(path):
        raw = original(path)
        return raw + b"\n" if path == target else raw
    monkeypatch.setattr(Path, "read_bytes", altered)
    with pytest.raises(ValueError, match="exact artifact hash"):
        a.validate_envelope_v1(envelopes[kind], expected_kind=kind, policy=policy)


def test_previous_signed_candidate_latch_is_superseded(material):
    config, policy, envelopes, _ = material
    previous = config.get("superseded_latch")
    if previous is None:
        pytest.skip("首个 candidate 无上一版已签 latch")
    with pytest.raises(ValueError, match="current latch"):
        a.validate_current_latch_v1(Path(previous).read_bytes(), policy=policy, inner_envelope=envelopes["INNER"], timed_envelope=envelopes["TIMED"])


@pytest.mark.parametrize("mutation", ["missing", "stale", "superseded", "verifier", "natural", "audit", "inner", "timed"])
def test_current_latch_missing_stale_and_tamper_fail_closed(material, mutation):
    _, policy, envelopes, raw = material
    latch = json.loads(raw)
    if mutation == "missing": del latch["inner_binding"]
    elif mutation == "stale": latch["generation"] -= 1
    elif mutation == "superseded": latch = {"status": "NOT_RESIGNED"}
    else:
        key = {"verifier": "current_verifier_identity", "natural": "natural_sha256", "audit": "existing_final_audit_sha256", "inner": "inner_adoption_identity", "timed": "timed_adoption_identity"}[mutation]
        latch[key] = "9"*64
    latch["latch_identity"] = c.identity({k:v for k,v in latch.items() if k != "latch_identity"})
    with pytest.raises(ValueError):
        a.validate_current_latch_v1(c.canonical(latch), policy=policy, inner_envelope=envelopes["INNER"], timed_envelope=envelopes["TIMED"])


def test_valid_current_latch_and_execution_identity_domains(material):
    _, policy, envelopes, raw = material
    latch = a.validate_current_latch_v1(raw, policy=policy, inner_envelope=envelopes["INNER"], timed_envelope=envelopes["TIMED"])
    assert latch["authority_path"] == a.AUTHORITY
    assert latch["inner_binding"]["fresh_execution_identity"] != latch["timed_binding"]["fresh_execution_identity"]
    assert latch["inner_binding"]["worker_source_identity"] != latch["current_verifier_identity"]
    assert latch["timed_binding"]["fresh_execution_provenance"]["worker"]["os_pid"] == "NOT_RECORDED"


def test_old_fresh_worker_source_and_comparisons_exactly_unchanged(material):
    _, policy, _, _ = material
    p = policy.validate()
    snapshot = Path(p["historical_verifier_root"])
    for name in ("production_replay.py", "c8_timed_replay_version_compatibility_v1.py"):
        rel = Path("scripts/sgs_engine")/name
        assert (a._root()/rel).read_bytes() == (snapshot/rel).read_bytes()
    # G3 audit reference and G1 source certificate migrate; executable contracts
    # and existing fresh-worker/comparator bodies retain exact original bytes.
    for name, functions in {
        "c8_timed_8p_full_game_production_replay_v1.py": ("_fresh_inner", "_fresh_timed", "_fresh_unresolved", "verify_full_game_composition_v1", "preflight_composition_v1"),
        "c8_timed_8p_full_game_contract_v1.py": ("choose_formal_driver_action_v1", "_eligible_ordinals"),
    }.items():
        rel = Path("scripts/sgs_engine")/name
        def bodies(root):
            source = (root/rel).read_text(encoding="utf-8")
            return {n.name: ast.get_source_segment(source, n) for n in ast.parse(source).body
                    if isinstance(n, ast.FunctionDef) and n.name in functions}
        assert bodies(a._root()) == bodies(snapshot)
        assert set(bodies(snapshot)) == set(functions)


def test_serialized_old_result_still_rejected():
    with pytest.raises(ValueError, match="不得恢复fresh authority"):
        g1.FullGameResultV1.from_dict({"strict_replay_verified": True})


def test_no_proof_without_exact_audit_authority_type(material):
    _, policy, envelopes, latch = material
    with pytest.raises(ValueError, match="final audit authority"):
        a.issue_cell_proof_v1(policy=policy, inner_envelope=envelopes["INNER"], timed_envelope=envelopes["TIMED"], current_latch=latch, audit=None)


@pytest.mark.parametrize("mutation", ["no", "wrong_subject", "wrong_report_hash"])
def test_final_audit_no_or_wrong_binding_cannot_issue_proof(material, mutation):
    _, policy, envelopes, latch = material
    p = policy.validate()
    subject = c.canonical({"schema":"C8AdoptionAuditSubjectV1","version":1,"policy_sha256":policy.expected_sha256,"current_verifier_identity":p["current_verifier_identity"],"current_implementation_identity":a.implementation_identity_v1(p),"source_fingerprint":p["source_fingerprint"],"latch_sha256":hashlib.sha256(latch).hexdigest(),"inner_envelope_sha256":hashlib.sha256(envelopes["INNER"]).hexdigest(),"timed_envelope_sha256":hashlib.sha256(envelopes["TIMED"]).hexdigest(),"targeted_tests_sha256":"a"*64,"preservation_sha256":"b"*64})
    sh = hashlib.sha256(subject).hexdigest()
    # All test reports explicitly deny proof. No fabricated passing audit exists.
    decision = {**a.AUDIT_FLAGS,"ALLOW_C8G_FG_000_CELL_PROOF":"NO","AUDIT_SUBJECT_SHA256":sh if mutation != "wrong_subject" else "c"*64}
    report = ("TEST_ONLY_DENIAL\n```json\n"+json.dumps(decision)+"\n```\n").encode()
    ah = hashlib.sha256(report).hexdigest() if mutation != "wrong_report_hash" else "d"*64
    audit = a.IndependentAuditAuthorityV1(report, ah, subject, sh)
    with pytest.raises(ValueError):
        a.issue_cell_proof_v1(policy=policy, inner_envelope=envelopes["INNER"], timed_envelope=envelopes["TIMED"], current_latch=latch, audit=audit)

@pytest.mark.parametrize("failure", ["exit", "timeout", "wrong_artifact", "extra_receipt"])
def test_historical_parser_failure_or_substitution_fails_closed(material, monkeypatch, failure):
    from types import SimpleNamespace
    _, policy, envelopes, _ = material
    p = policy.validate()
    raw = a._read_evidence(p)
    called = []
    def rejected(argv, **kwargs):
        called.append(argv)
        assert argv[:3] == [a.sys.executable, "-B", "-c"]
        assert argv[3] == a._HISTORICAL_PREFLIGHT
        assert Path(kwargs["cwd"]) == Path(p["historical_verifier_root"]).resolve()
        assert "preflight_composition_v1" in argv[3]
        assert all(name not in argv[3] for name in ("_fresh_inner", "_fresh_timed", "execute_natural", "reexecute_production_replay"))
        if failure == "timeout":
            raise a.subprocess.TimeoutExpired(argv, 60)
        receipt = {"status":"PASSED", "artifact_sha256":p["files"]["natural"]["sha256"],
                   "artifact_identity":c.strict_json(raw["natural"])["artifact_identity"]}
        if failure == "wrong_artifact":receipt["artifact_sha256"] = "0" * 64
        if failure == "extra_receipt":receipt["trusted"] = True
        return SimpleNamespace(returncode=1 if failure == "exit" else 0, stdout=c.canonical(receipt))
    monkeypatch.setattr(a.subprocess, "run", rejected)
    with pytest.raises(ValueError):
        a._preflight_original_composition(p, raw)
    assert len(called) == 1


def test_historical_parser_source_drift_rejected_before_process(material, monkeypatch):
    _, policy, _, _ = material
    p = policy.validate();raw = a._read_evidence(p)
    prior = c.strict_json(raw["prior_policy"])
    target = Path(p["historical_verifier_root"]) / "scripts/sgs_engine/c8_timed_8p_full_game_contract_v1.py"
    real = c.file_hash
    monkeypatch.setattr(c, "file_hash", lambda path: "0"*64 if Path(path) == target else real(path))
    monkeypatch.setattr(a.subprocess, "run", lambda *args, **kwargs: pytest.fail("source drift 后不能启动 parser"))
    with pytest.raises(ValueError, match="源码清单漂移"):
        a._preflight_original_composition(p, raw)
