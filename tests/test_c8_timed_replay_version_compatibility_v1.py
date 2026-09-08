# -*- coding: utf-8 -*-
"""精确版本兼容的 cheap negative tests；不自动运行 natural/full timed。"""
import copy
import hashlib
import json
import os
from pathlib import Path

import pytest
from scripts.sgs_engine import c8_timed_replay_version_compatibility_v1 as compat
from scripts.sgs_engine import c8_strict_replay_v1 as d


@pytest.fixture(scope="module")
def materials():
    incoming = os.environ.get("C8_COMPAT_TEST_CONFIG")
    if not incoming:
        pytest.skip("需要本批独立固定的 compatibility policy，不自动信任 envelope")
    config = json.loads(Path(incoming).read_bytes())
    policy = compat.PinnedCompatibilityPolicyV1.load(Path(config["policy"]),
        expected_sha256=config["policy_sha256"], producer_root=Path(config["producer_root"]),
        verifier_root=Path(__file__).resolve().parents[1])
    raw = Path(config["bounded_artifact"]).read_bytes()
    envelope = Path(config["bounded_envelope"]).read_bytes()
    return policy, raw, envelope, config


def rehash(value):
    value["envelope_identity"] = compat.identity({k:v for k,v in value.items() if k != "envelope_identity"})
    return compat.canonical(value)


def test_exact_pair_accepted_for_verification_and_default_gate_unchanged(materials):
    policy, raw, envelope, _ = materials
    assert not compat.active_v1()
    e = compat.validate_envelope_v1(envelope, raw, policy=policy)
    assert e["artifact_sha256"] == hashlib.sha256(raw).hexdigest()
    assert e["scope"] == "DEVELOPMENT_VERIFICATION_ONLY" and e["promotion"] is False
    d._assert_current_dependencies()  # Current D was explicitly rebound before this batch.
    assert not compat.active_v1()


@pytest.mark.parametrize("mutation", ["artifact", "producer", "verifier", "policy-identity", "policy-version",
    "comparison-contract", "comparison-schema", "comparison-list", "unknown-pair", "extra-field",
    "bool-version", "tamper-unrehashed", "other-artifact-fields"])
def test_envelope_tamper_and_unknown_pairs_fail_closed(materials, mutation):
    policy, raw, envelope, config = materials
    value = json.loads(envelope)
    if mutation == "artifact": raw += b" "
    elif mutation == "producer": value["producer_identity"] = "a"*64
    elif mutation == "verifier": value["verifier_identity"] = "b"*64
    elif mutation == "policy-identity": value["policy_identity"] = "c"*64
    elif mutation == "policy-version": value["policy_version"] += 1
    elif mutation == "comparison-contract": value["comparison_contract"]["replay_contract_identity"] = "d"*64
    elif mutation == "comparison-schema": value["comparison_contract"]["replay_schema"] = "unknown"
    elif mutation == "comparison-list": value["comparison_contract"]["required_comparisons"].pop()
    elif mutation == "unknown-pair":
        value["producer_identity"], value["verifier_identity"] = "1"*64, "2"*64
    elif mutation == "extra-field": value["verified"] = True
    elif mutation == "bool-version": value["version"] = True
    elif mutation == "tamper-unrehashed": value["promotion"] = True
    elif mutation == "other-artifact-fields":
        other = json.loads(Path(config["natural_envelope"]).read_bytes())
        value.update({k:other[k] for k in ("artifact_sha256", "producer_identity", "comparison_contract", "lane")})
    edited = compat.canonical(value) if mutation == "tamper-unrehashed" else rehash(value)
    with pytest.raises(ValueError):
        compat.validate_envelope_v1(edited, raw, policy=policy)
    assert not compat.active_v1()


def test_policy_cannot_be_replaced_by_self_asserted_envelope(materials):
    policy, raw, envelope, _ = materials
    material = json.loads(policy.raw)
    material["pairs"] = []
    material["policy_identity"] = compat.identity({k:v for k,v in material.items() if k != "policy_identity"})
    forged = compat.PinnedCompatibilityPolicyV1(compat.canonical(material), policy.expected_sha256, policy.producer_root, policy.verifier_root)
    with pytest.raises(compat.C8CompatibilityError, match="policy hash"):
        compat.validate_envelope_v1(envelope, raw, policy=forged)


def test_verified_scope_closes_on_exception_and_cannot_issue_proof(materials):
    policy, raw, envelope, _ = materials
    with pytest.raises(RuntimeError, match="test-error"):
        with compat._verification_scope(envelope, raw, policy):
            # The scope retains the original source domain, not current D constants.
            target = Path(__file__).resolve().parents[1]/"scripts/sgs_engine/c8_timed_session_runtime_v1.py"
            assert compat.execution_source_digest_v1(target) == policy.validate()["producer_sources"]["scripts/sgs_engine/c8_timed_session_runtime_v1.py"]
            with pytest.raises(compat.C8CompatibilityError, match="禁止签发"):
                compat.reject_recording_v1()
            raise RuntimeError("test-error")
    assert not compat.active_v1()
    d._assert_current_dependencies()


def test_unknown_artifact_even_with_correct_producer_and_verifier_rejected(materials):
    policy, raw, envelope, _ = materials
    altered = raw + b"\n"
    e = json.loads(envelope)
    e["artifact_sha256"] = hashlib.sha256(altered).hexdigest()
    with pytest.raises(compat.C8CompatibilityError, match="未明确登记"):
        compat.validate_envelope_v1(rehash(e), altered, policy=policy)


def test_g3_default_gate_and_full_proof_entry_remain_closed(materials):
    from scripts.sgs_engine import c8_timed_8p_full_game_production_replay_v1 as g3
    policy, raw, envelope, _ = materials
    with pytest.raises(ValueError, match="identity|binding|不匹配"):
        g3.preflight_composition_v1(raw, full_game=False)
    with compat._verification_scope(envelope, raw, policy):
        with pytest.raises(compat.C8CompatibilityError, match="禁止签发"):
            g3.verify_full_game_composition_v1(raw)


def test_verifier_drift_on_scope_exit_is_rejected_and_cleared(materials, monkeypatch):
    policy, raw, envelope, _ = materials
    original = compat.file_hash
    target = Path(compat.__file__).resolve()
    with pytest.raises(compat.C8CompatibilityError, match="源码清单漂移"):
        with compat._verification_scope(envelope, raw, policy):
            monkeypatch.setattr(compat, "file_hash", lambda p: "0"*64 if Path(p).resolve() == target else original(p))
    assert not compat.active_v1()
