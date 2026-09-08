# -*- coding: utf-8 -*-
"""Saved canonical evidence and explicitly opted-in TEST_ONLY R2 integration.
R2 generation requires its own authorization environment; ordinary collection
never starts C6. Historical evidence remains in its original identity domain.
"""
import copy
import functools
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest
from scripts.sgs_engine import c8_timed_8p_full_game_contract_v1 as contract
from scripts.sgs_engine import c8_timed_8p_full_game_replay_v1 as replay
from scripts.sgs_engine import c8_timed_8p_full_game_runner_v1 as runner
from scripts.sgs_engine import c8_timed_8p_full_game_production_replay_v1 as g3

REPO = Path(__file__).resolve().parents[1]


@functools.lru_cache(maxsize=1)
def get_fixture():
    incoming = os.environ.get("C8_TYPED_FIXTURE_IN")
    if incoming:
        return g3.preflight_composition_v1(replay._strict_json(Path(incoming).read_bytes()), full_game=False)
    pytest.skip("一次性bounded artifact尚未提供；测试不得自动启动gameplay")


def test_real_typed_fixture_actual_revision_and_step_domains():
    artifact = get_fixture()
    t = artifact["timed_artifact"]
    counters = t["private_production_record"]["counters"]
    assert [(v["pre_revision"],v["post_revision"]) for v in counters[:3]] == [(0,0),(0,0),(0,2)]
    assert [(v["pre_step_count"],v["post_step_count"]) for v in counters] == [(i,i+1) for i in range(t["completed_production_steps"])]
    assert t["completed_windows"] == 8 and t["completed_production_steps"] <= 12
    assert artifact["full_game"] is False


def test_saved_once_fresh_composition_report_matches_exact_artifact():
    incoming = os.environ.get("C8_TYPED_REPORT_IN")
    if not incoming:
        pytest.skip("一次bounded fresh composition尚未提供；不自动重跑worker")
    result = replay._strict_json(Path(incoming).read_bytes())
    artifact = get_fixture()
    assert result["status"] == "MATCH"
    assert result["artifact_identity"] == artifact["artifact_identity"]
    assert result["ordered_production_sequence_identity"] == artifact["ordered_production_sequence_identity"]
    assert result["accepted_steps"] == artifact["timed_artifact"]["completed_production_steps"]
    assert result["windows"] == 8
    assert result["scope"] == "BOUNDED_VERIFIER_TEST_ONLY"
    assert result["full_game"] is result["promotion"] is False
    assert result["old_c6_full_game_verifier"] == "NOT_CALLED_FOR_PREFIX"


@pytest.mark.parametrize("mutation", ["old-v1","old-v2","full","extra","bool-version","live-ownership","source"])
def test_preflight_rejects_legacy_scope_source_and_serialized_ownership(mutation,monkeypatch):
    d = copy.deepcopy(get_fixture())
    if mutation.startswith("old-"):
        d["schema"] = "sgs-c8-timed-8p-full-game-replay-"+mutation[4:]
    elif mutation == "full":
        d["full_game"] = True
    elif mutation == "extra":
        d["verified"] = True
    elif mutation == "bool-version":
        d["contract_version"] = True
    elif mutation == "live-ownership":
        d["timed_artifact"]["private_production_record"]["receipt_ownership"] = {}
    else:
        d["g3_binding"]["global_source_identity"] = "a"*64
    monkeypatch.setattr(g3,"_cold_workers",lambda *a:pytest.fail("must reject before workers"))
    with pytest.raises(ValueError):
        g3.verify_bounded_composition_v1(d)


def test_bounded_cannot_issue_full_game_result(monkeypatch):
    monkeypatch.setattr(g3,"_cold_workers",lambda *a:pytest.fail("scope before gameplay"))
    with pytest.raises(ValueError):
        g3.verify_full_game_composition_v1(get_fixture())
    with pytest.raises(ValueError):
        contract.FullGameResultV1.from_dict({"verified":True})
    with pytest.raises(ValueError):
        g3.BoundedCompositionResultV1("a"*64,"b"*64,8,8)


@pytest.mark.parametrize("mutation", ["missing","duplicate","reorder","tail","cross-cell","revision","count-bool"])
def test_ordered_production_sequence_rejects_structural_splices(mutation):
    decisions = [copy.deepcopy(s["decision"]) for s in runner.flat_step_records_v4(get_fixture()["timed_artifact"])]
    if mutation == "missing":
        decisions.pop(1)
    elif mutation == "duplicate":
        decisions[1] = copy.deepcopy(decisions[0])
    elif mutation == "reorder":
        decisions[0],decisions[1] = decisions[1],decisions[0]
    elif mutation == "tail":
        decisions.append(copy.deepcopy(decisions[-1]))
    else:
        b = decisions[1]["binding"]
        b[{"cross-cell":"cell_execution_identity","revision":"pre_revision","count-bool":"pre_step_count"}[mutation]] = {"cross-cell":"f"*64,"revision":9,"count-bool":True}[mutation]
        decisions[1]["evidence_identity"] = contract.identity_v1({k:v for k,v in decisions[1].items() if k != "evidence_identity"})
    with pytest.raises(ValueError):
        replay.ordered_production_sequence_v1(decisions)


def _rehash(value,key):
    value[key] = contract.identity_v1({k:v for k,v in value.items() if k != key})


def rehash_g_document(d, *, recompute_sequence=True):
    """Adversary recomputes ALL G envelopes WITHOUT invoking a validation gate.
    B/C/E and C6 commitments remain their own authority domains. Malicious scalar
    edits are intentionally not repaired. This helper never creates live authority.
    """
    if "trusted_private_artifact" in d:
        return _rehash_r2_document(d)
    timed = d["timed_artifact"]
    private = timed["private_production_record"]
    _rehash(private,"record_identity")
    steps = runner.flat_step_records_v4(timed)
    old_window_ids = {}
    for window in timed["window_records"]:
        relation = window["relation"]
        prior = relation["causal_parent_window_identity"]
        if prior is not None:
            relation["causal_parent_window_identity"] = old_window_ids.get(prior,prior)
            relation["parent_window_close_evidence_identity"] = contract.identity_v1({
                "schema":"sgs-c8-g1-parent-close-evidence-v3",
                **{k:relation[k] for k in ("causal_parent_window_identity","originating_step_identity",
                    "originating_decision_kind","originating_decision_evidence_identity","originating_completion_identity","parent_window_close_status")}})
            relation["post_step_observe_identity"] = contract.identity_v1({
                "schema":"sgs-c8-g1-post-step-observe-evidence-v3","contract_version":contract.C8_G1_CONTRACT_VERSION,
                **{k:relation[k] for k in ("originating_step_identity","originating_post_production_revision",
                    "originating_post_public_state_identity","causal_parent_context_identity","post_step_context_identity")}})
        old_id = window["record_identity"]
        for local,step in enumerate(window["steps"]):
            decision = step["decision"]
            b = decision["binding"]
            b["relation_ref"] = contract.identity_v1(relation) if local == 0 else contract.identity_v1({"opening_window_ref":window["window_ref"]["authority_ref_identity"]})
            for label in ("pre_state","post_state"):
                _rehash(step[label],"state_identity")
            observation = step["post_step_observation"]
            observation["observation_identity"] = contract.identity_v1({"schema":"sgs-c8-g-post-step-observation-v4",
                "inner_decision_identity":b["inner_decision_identity"],"next_context":observation["next_context"],
                "post_state_identity":step["post_state"]["state_identity"]})
            decision["completion"]["post_step_observation_identity"] = observation["observation_identity"]
            schedule = decision if decision["kind"] == replay.ON_TIME_KIND else decision["timeout_schedule_decision"]
            schedule["driver_decision"]["driver_input_identity"] = contract.identity_v1(schedule["driver_input"])
            if decision["kind"] == replay.ON_TIME_KIND:
                legal = decision["fresh_public_legal_set"]
                legal["legal_set_commitment"] = contract.identity_v1(legal["actions"])
                if decision["completion"]["kind"] == "ON_TIME_OBLIGATION_CONTINUED":
                    before = decision["liveness"]["before"]
                    decision["completion"]["logical_step_identity"] = contract.identity_v1({
                        "schema":"sgs-c8-g-on-time-logical-step-v1","logical_obligation_identity":before["logical_obligation_identity"],
                        **{k:b[k] for k in ("window_authority_ref_identity","step_index","window_step_index","production_context_identity",
                            "inner_decision_identity","production_action_ref","pre_step_count","post_step_count","deadline_at","decision_tick")}})
            _rehash(decision,"evidence_identity")
            c = step["completion"]
            c.update(decision_evidence_identity=decision["evidence_identity"],
                action_binding_identity=contract.identity_v1({"schema":"sgs-c8-g-production-action-binding-v1",**b}),
                disposition_event_identity=b["window_disposition_ref"],post_step_observation_identity=observation["observation_identity"])
            _rehash(c,"completion_identity")
            _rehash(step,"record_identity")
        _rehash(window,"record_identity")
        old_window_ids[old_id] = window["record_identity"]
    for label in ("initial_state","final_state"):
        _rehash(timed[label],"state_identity")
    public = timed["public_projection"]
    public["relations"] = [w["relation"] for w in timed["window_records"]]
    public["completed_windows"] = timed["completed_windows"]
    public["completed_production_steps"] = timed["completed_production_steps"]
    binding_keys = tuple(public["decisions"][0]["binding"])
    public["decisions"] = [{**{k:v for k,v in s["decision"].items() if k != "binding"},
        "binding":{k:s["decision"]["binding"][k] for k in binding_keys}} for s in steps]
    _rehash(timed,"artifact_identity")
    if recompute_sequence:
        sequence_keys = tuple(d["ordered_production_sequence"][0])
        d["ordered_production_sequence"] = [{k:s["decision"]["binding"][k] for k in sequence_keys} for s in steps]
        d["ordered_production_sequence_identity"] = contract.identity_v1({"schema":"sgs-c8-g-ordered-production-sequence-v1","sequence":d["ordered_production_sequence"]})
    _rehash(d,"artifact_identity")


def _rehash_r2_document(d):
    """Recompute detached R2 envelopes without repairing semantic mutations."""
    timed = d["trusted_private_artifact"]["timed_artifact"]
    wrapper = {"timed_artifact": timed,
               "ordered_production_sequence": d["ordered_production_sequence"]}
    # Keep the stored ordered sequence as an independent commitment.  A
    # malicious semantic edit must not be normalized by this adversarial
    # helper, and rebuilding it would invoke the typed driver gate before the
    # envelope can demonstrate fresh semantic rejection.
    rehash_g_document(wrapper, recompute_sequence=False)
    timed = wrapper["timed_artifact"]
    d["trusted_private_artifact"]["timed_artifact"] = timed
    if "timed_artifact" in d:
        d["timed_artifact"] = timed
    setup = d["trusted_private_artifact"]["fixture_setup"]
    sequence = d["ordered_production_sequence"]
    d["public_projection"] = g3._r2_public_projection_v1(
        timed, setup, d["call_trace"], sequence)
    aliases = {"timed_artifact", "setup"}
    d["artifact_identity"] = contract.identity_v1({
        key: value for key, value in d.items()
        if key not in aliases and key != "artifact_identity"
    })


def test_all_g_rehash_helper_preserves_valid_current_bytes():
    original = get_fixture()
    d = copy.deepcopy(original)
    rehash_g_document(d)
    assert d == original
    g3.preflight_composition_v1(d,full_game=False)


@pytest.mark.parametrize("mutation,gate", [
    ("ordinal","on-time chosen ordinal"),("action","inner outer signed action"),
    ("continuation-local","liveness local step"),("continuation-q","fresh public induction transition"),
    ("continuation-actor","driver/binding actor_id"),("continuation-deadline","driver/binding deadline_at"),
    ("continuation-O","稳定义务入口绑定")])
def test_all_g_rehashed_action_ordinal_and_continuation_splices_hit_semantic_gate(mutation,gate,monkeypatch):
    d = copy.deepcopy(get_fixture())
    window = next(w for w in d["timed_artifact"]["window_records"] if len(w["steps"]) > 1)
    first,last = window["steps"][0],window["steps"][1]
    decision = first["decision"] if mutation in {"ordinal","action","continuation-q"} else last["decision"]
    b = decision["binding"]
    if mutation == "ordinal":
        legal = decision["fresh_public_legal_set"]["actions"]
        b["production_action_ref"]["executed_public_ordinal"] = 1
        b["production_action_ref"]["signed_action_id_commitment"] = legal[1]["signed_action_id_commitment"]
    elif mutation == "action":
        b["production_action_ref"]["signed_action_id_commitment"] = "f"*64
        decision["fresh_public_legal_set"]["actions"][0]["signed_action_id_commitment"] = "f"*64
    elif mutation == "continuation-local":
        b["window_step_index"] += 1
    elif mutation == "continuation-q":
        decision["liveness"]["after"]["certified_selected_progress_count"] += 1
    elif mutation == "continuation-actor":
        b["actor_id"] = "spliced-actor"
    elif mutation == "continuation-deadline":
        b["deadline_at"] += 1
        b["opened_at"] += 1
    else:
        decision["driver_input"]["public_ordinal_progress"]["logical_obligation_identity"] = "f"*64
        decision["liveness"]["before"]["logical_obligation_identity"] = "f"*64
    rehash_g_document(d)
    assert d["artifact_identity"] == contract.identity_v1({k:v for k,v in d.items() if k!="artifact_identity"})
    monkeypatch.setattr(g3,"_cold_workers",lambda *a:pytest.fail("semantic gate must reject before workers"))
    # The helper itself performed no validation. Inspect the actual parser failure.
    with pytest.raises(ValueError,match=gate):
        g3.verify_bounded_composition_v1(d)


@pytest.mark.parametrize("field", ["initial_rng_call_count","initial_event_count"])
def test_initial_c6_counts_reject_bool_before_gameplay(field,monkeypatch):
    d = copy.deepcopy(get_fixture())
    d["timed_artifact"]["private_production_record"]["header"][field] = True
    rehash_g_document(d)
    monkeypatch.setattr(g3,"_cold_workers",lambda *a:pytest.fail("counts before gameplay"))
    with pytest.raises(ValueError):
        g3.verify_bounded_composition_v1(d)


@pytest.mark.parametrize("state", ["initial_state","final_state"])
@pytest.mark.parametrize("mutation", ["unknown","bool-depth"])
def test_root_state_closed_keys_and_exact_counts(state,mutation,monkeypatch):
    d = copy.deepcopy(get_fixture())
    d["timed_artifact"][state]["unknown" if mutation=="unknown" else "window_depth"] = False
    rehash_g_document(d)
    monkeypatch.setattr(g3,"_cold_workers",lambda *a:pytest.fail("state before gameplay"))
    with pytest.raises(ValueError):
        g3.verify_bounded_composition_v1(d)


def test_bounded_without_rescue_does_not_claim_successful_rescue():
    assert get_fixture()["timed_artifact"]["private_production_record"]["successful_rescue_evidence"] == []


def test_v3_gate_worker_environment_profile_checked_before_any_c6_session(monkeypatch):
    monkeypatch.setattr(g3.PrivateIncrementalC6RecorderV1,"cold_session",lambda *a:pytest.fail("profile before session"))
    # No real artifact/session required to exercise this fail-closed preflight.
    monkeypatch.setenv("PYTHONHASHSEED","42")
    d = {"timed_artifact":{"construction":{"execution_order_profile":{}},"private_production_record":{},"window_records":[]}}
    for worker in (g3._fresh_inner,g3._fresh_timed,g3._fresh_unresolved):
        with pytest.raises(ValueError,match="EXECUTION_ORDER_PROFILE_MISMATCH"):
            worker(d)


R2_TASK = g3.R2_TEST_ONLY_TASK
R2_SCOPE = g3.R2_TEST_ONLY_SCOPE
R2_BOUNDARIES = list(g3.R2_TEST_ONLY_BOUNDARIES)


def _r2_setup_only(session):
    """Compatibility hook routed through the trusted production factory."""
    factory = g3.ExplicitTestOnlyFixtureFactoryV1()
    return factory.prepare_session_v1(session, seed=0)


def _r2_wrap(timed, setup, calls):
    return g3.build_test_only_evidence_envelope_v1(
        timed, setup, calls, repo_root=REPO
    )


def _r2_validate(document):
    """Compatibility view over the exact frozen R2 envelope."""
    aliases = {"timed_artifact", "setup"}
    canonical = {key: value for key, value in document.items() if key not in aliases}
    parsed = g3.r2_test_only_evidence_from_dict_v1(canonical, repo_root=REPO)
    return {**parsed,
        "timed_artifact": parsed["trusted_private_artifact"]["timed_artifact"],
        "setup": parsed["trusted_private_artifact"]["fixture_setup"]}


@pytest.fixture(scope="module")
def r2_targeted_artifact():
    incoming = os.environ.get("C8_R2_ARTIFACT_IN")
    if incoming:
        return _r2_validate(replay._strict_json(Path(incoming).read_bytes()))
    if os.environ.get("C8_R2_GENERATE_AUTHORIZATION") != R2_TASK:
        pytest.skip("R2 test-only production execution requires explicit task opt-in")
    root = Path(os.environ["C8_R2_EVIDENCE_ROOT"])
    target = root / "private" / "r2_targeted_artifact.json"
    assert not target.exists(), "one R2 generation only; never overwrite or retry a saved run"
    factory = g3.ExplicitTestOnlyFixtureFactoryV1()
    calls, stack = [], []

    codes = {
        runner.runtime_v1.C8TimedSessionRuntimeV1.forward_on_time_signed_action_id.__code__: "B_NORMAL_FORWARD",
        runner.prod.C8C6ProductionAdapterV1.apply_signed_action_id_v1.__code__: "E_APPLY_SIGNED_ACTION_ID",
        g3.FormalEightPlayerIdentitySession.step.__code__: "C6_STEP",
    }

    def observe(frame, event, _value):
        label = codes.get(frame.f_code)
        if label is None or event not in {"call", "return"}:
            return
        if event == "call":
            row = {"event": "call", "method": label, "stack": [], "pre_step_count": None}
            stack.append((label, row))
            row["stack"] = [item[0] for item in stack]
            if label == "C6_STEP":
                count = frame.f_locals["self"].step_count
                for _name, active in stack:
                    active["pre_step_count"] = count
            calls.append(row)
        else:
            assert stack.pop()[0] == label

    previous_profile = sys.getprofile()
    try:
        sys.setprofile(observe)  # Observation only: no replacement of B/E/C6 methods.
        timed = runner.execute_bounded_smoke_v1(repo_root=REPO, seed=0,
            max_steps=8, max_windows=6, run_label="r2-test-only-targeted",
            bundle_factory=factory, test_only=True,
            diagnostic_sink=runner.ReportOnlyDiagnosticSinkV1(root / "diagnostics"))
    finally:
        sys.setprofile(previous_profile)
    calls = [row for row in calls if row["pre_step_count"] in (4, 5, 6)]
    document = _r2_wrap(timed, factory.setup_evidence_v1(), calls)
    runner._atomic_json(target, document)
    runner._atomic_json(root / "public" / "r2_public_projection.json", document["public_projection"])
    runner._atomic_json(root / "private" / "r2_call_trace.json", document["call_trace"])
    return _r2_validate(document)


def _r2_window(document):
    windows = [w for w in document["timed_artifact"]["window_records"] if w["context"]["phase"] == "discard"]
    assert len(windows) == 1
    return windows[0]


def test_r2_exact_real_c6_production_sequence(r2_targeted_artifact):
    d = r2_targeted_artifact
    timed, window = d["timed_artifact"], _r2_window(d)
    steps = window["steps"]
    assert len(steps) == 3
    assert timed["completed_windows"] == 6 and timed["completed_production_steps"] == 8
    inner = timed["private_production_record"]["decisions"][4:7]
    assert [s["chosen_action"]["payload"]["operation"] for s in inner] == [
        "select_discard_card", "select_discard_card", "discard_phase_submit"]
    assert inner[0]["chosen_action"]["card_instance_id"] != inner[1]["chosen_action"]["card_instance_id"]
    assert [sum(a["payload"].get("operation") == "unselect_discard_card" for a in s["legal_actions"]) for s in inner] == [0, 1, 2]
    assert [s["decision"]["binding"]["production_action_ref"]["executed_public_ordinal"] for s in steps] == [0, 0, 7]
    assert [len(s["legal_actions"]) for s in inner] == [7, 7, 8]
    assert all(a["payload"]["excess_count"] == 2 for a in inner[0]["legal_actions"])
    for local, step in enumerate(steps):
        before, after = (step["decision"]["liveness"][k] for k in ("before", "after"))
        assert before["candidate_count"] == 7
        assert before["certified_selected_progress_count"] == local
        assert after["certified_selected_progress_count"] == min(local+1, 2)
        assert after["stage"] == ("DONE" if local == 2 else "SELECTING")
        assert step["completion"]["disposition"] == ("CLOSED_BY_ACTION" if local == 2 else "CONTINUED")
        assert step["decision"]["binding"]["pre_step_count"] == 4+local
        assert step["decision"]["binding"]["post_step_count"] == 5+local
    assert steps[1]["decision"]["liveness"]["after"]["certified_required_count"] == 2
    commit_options = [i for i,a in enumerate(inner[2]["legal_actions"]) if a["payload"].get("operation") == "discard_phase_submit"]
    assert commit_options == [7]
    assert steps[-1]["post_state"]["phase"] == "end"
    events = timed["private_production_record"]["events"][inner[-1]["event_start"]:inner[-1]["event_end"]]
    assert sum(e["event_type"] == "card_discarded" for e in events) == 2
    assert d["call_trace"] == [
        {"event": "call", "method": method, "stack": ["B_NORMAL_FORWARD", "E_APPLY_SIGNED_ACTION_ID", "C6_STEP"][:i+1], "pre_step_count": count}
        for count in (4,5,6) for i,method in enumerate(("B_NORMAL_FORWARD", "E_APPLY_SIGNED_ACTION_ID", "C6_STEP"))]


@pytest.mark.parametrize("field", ["test_only", "formal_result", "fixture_applied"])
def test_r2_native_c6_header_preserves_frozen_semantics(r2_targeted_artifact, field):
    """The fixture changes eligibility; the R2 lane belongs to the outer envelope."""
    document = r2_targeted_artifact
    assert document["test_only"] is True
    assert document["timed_artifact"]["test_only"] is True
    header = document["timed_artifact"]["private_production_record"]["header"]
    assert header["test_only"] is False
    assert header["formal_result"] is False
    assert header["fixture_applied"] is False
    mutated = copy.deepcopy(document)
    mutated["timed_artifact"]["private_production_record"]["header"][field] = True
    rehash_g_document(mutated)
    with pytest.raises(ValueError, match="C6 header "+field):
        _r2_validate(mutated)


def test_r2_same_window_deadline_open_schedule_and_last_parent(r2_targeted_artifact):
    timed = r2_targeted_artifact["timed_artifact"]
    window = _r2_window(r2_targeted_artifact)
    bindings = [s["decision"]["binding"] for s in window["steps"]]
    for key in ("window_authority_ref_identity", "opening_production_context_identity", "deadline_at", "decision_tick", "actor_id", "global_window_index"):
        assert len({b[key] for b in bindings}) == 1
    assert [b["window_step_index"] for b in bindings] == [0,1,2]
    assert len({b["production_context_identity"] for b in bindings}) == 3
    assert bindings[0]["opening_production_context_identity"] == bindings[0]["production_context_identity"]
    assert bindings[0]["deadline_at"] == 497 and bindings[0]["decision_tick"] == 496
    for s in window["steps"][1:]:
        assert not {o["name"] for o in s["operations"]} & {"OPEN", "REFRESH", "ADVANCE", "DUE", "RESOLVE"}
    assert len({s["decision"]["liveness"]["before"]["logical_obligation_identity"] for s in window["steps"]}) == 1
    events = [e for t in timed["private_timed_transcript"] for e in t["runtime_events"]]
    assert sum(e["event_kind"] == "WINDOW_OPENED" for e in events) == 6
    assert sum(e["event_kind"] == "MULTI_STEP_CONTINUED" for e in events) == 2
    assert [w["sequence"] for w in timed["window_records"] if w["steps"][0]["decision"]["kind"] == replay.TIMEOUT_KIND] == [4]
    for t in timed["private_timed_transcript"][4:7]:
        assert all(t[k] is None for k in ("e_legal_snapshot", "e_issuance", "due", "controller_result"))
        assert t["controller_events"] == []
    successor = timed["window_records"][5]
    assert successor["relation"] == contract.WindowRelationEvidenceV3.independent_decision_v3().to_dict()
    assert successor["relation"]["originating_step_index"] is None
    assert successor["relation"]["originating_step_identity"] is None
    assert successor["steps"][0]["decision"]["driver_decision"]["actual_timeout"] is False


def test_r2_old_v2_last_ordinal_is_reversal_and_ineligible(r2_targeted_artifact):
    window = _r2_window(r2_targeted_artifact)
    step = window["steps"][1]
    progress = contract.PublicOrdinalProgressV1.from_dict(step["decision"]["liveness"]["before"])
    legal = r2_targeted_artifact["timed_artifact"]["private_production_record"]["decisions"][5]["legal_actions"]
    assert legal[-1]["payload"]["operation"] == "unselect_discard_card"
    assert contract.certified_ordinal_choice_v1(progress, len(legal)) == (0, "PROGRESS")
    with pytest.raises(ValueError, match="ordinal或accepted边界不匹配"):
        contract.advance_public_ordinal_progress_v1(progress, chosen_ordinal=len(legal)-1,
            post_step_count=6, **step["decision"]["liveness"]["post_public_boundary"])


@pytest.mark.parametrize("mutation", ["q", "N", "stage", "ordinal", "continuation",
    "second-reversal", "second-cancel", "commit-early", "commit-late", "ref", "deadline", "actor", "O", "opening-parent"])
def test_r2_rehashed_semantic_tamper_fails_closed(r2_targeted_artifact, mutation):
    d = copy.deepcopy(r2_targeted_artifact)
    w = _r2_window(d)
    decision = w["steps"][2 if mutation == "commit-late" else 1]["decision"]
    b = decision["binding"]
    progress = decision["liveness"]["before"]
    if mutation in {"q", "N", "stage"}:
        key = {"q": "certified_selected_progress_count", "N": "candidate_count", "stage": "stage"}[mutation]
        progress[key] = "DONE" if mutation == "stage" else progress[key]+1
        decision["driver_input"]["public_ordinal_progress"][key] = progress[key]
    elif mutation in {"ordinal", "second-reversal", "commit-early", "commit-late"}:
        ordinal = 7 if mutation == "commit-early" else 0 if mutation == "commit-late" else 6
        b["production_action_ref"]["executed_public_ordinal"] = ordinal
        if ordinal < len(decision["fresh_public_legal_set"]["actions"]):
            b["production_action_ref"]["signed_action_id_commitment"] = decision["fresh_public_legal_set"]["actions"][ordinal]["signed_action_id_commitment"]
        if mutation != "ordinal":
            decision["driver_decision"]["chosen_public_ordinal"] = ordinal
    elif mutation == "second-cancel":
        b["production_action_ref"]["executed_public_action_family"] = "CANCEL"
    elif mutation == "continuation":
        b["window_step_index"] += 1
    elif mutation == "ref":
        b["window_authority_ref_identity"] = "f"*64
    elif mutation == "deadline":
        b["deadline_at"] += 1
        b["opened_at"] += 1
    elif mutation == "actor":
        b["actor_id"] = "spliced-actor"
    elif mutation == "O":
        progress["logical_obligation_identity"] = "f"*64
        decision["driver_input"]["public_ordinal_progress"]["logical_obligation_identity"] = "f"*64
    else:
        d["timed_artifact"]["window_records"][5]["relation"]["originating_step_identity"] = w["steps"][0]["decision"]["binding"]["inner_decision_identity"]
    rehash_g_document(d)
    assert d["artifact_identity"] == contract.identity_v1({
        k: v for k, v in d.items()
        if k not in {"artifact_identity", "timed_artifact", "setup"}
    })
    with pytest.raises(ValueError) as error:
        _r2_validate(d)
    message = str(error.value)
    assert not any(gate in message for gate in ("artifact hash", "envelope hash", "current source identity")), message
    if mutation == "opening-parent":
        assert "parent" in message
    root = os.environ.get("C8_R2_EVIDENCE_ROOT")
    if root:
        runner._atomic_json(Path(root)/"negatives"/(mutation+".json"), {"mutation": mutation,
            "outer_hash_recomputed": True, "status": "REJECTED", "semantic_error": message})


@pytest.mark.parametrize("field", ["card_instance_id", "payload", "handle", "session_secret_hex"])
def test_r2_fixture_private_material_rejected_by_g1_input(r2_targeted_artifact, field):
    d = copy.deepcopy(_r2_window(r2_targeted_artifact)["steps"][1]["decision"]["driver_input"])
    private = r2_targeted_artifact["setup"]["private"]["moved_card_instance_id"]
    d[field] = private
    with pytest.raises(ValueError):
        replay.driver_input_from_dict_v3(d)
    del d[field]
    d["public_ordinal_progress"][field] = private
    with pytest.raises(ValueError):
        replay.driver_input_from_dict_v3(d)


def test_r2_current_rehash_positive_and_production_scope_rejection(r2_targeted_artifact):
    d = copy.deepcopy(r2_targeted_artifact)
    rehash_g_document(d)
    assert d == r2_targeted_artifact
    _r2_validate(d)
    with pytest.raises(ValueError, match="test-only lane"):
        g3.build_composition_artifact_v1(d["timed_artifact"], repo_root=REPO)
    private = d["timed_artifact"]["private_production_record"]
    canonical = g3.PrivateIncrementalC6RecorderV1.cold_session(private)
    # Dropping the test-only label cannot reconstruct this injected initial state.
    with pytest.raises(ValueError, match="fresh canonical initial header"):
        g3.PrivateIncrementalC6RecorderV1(canonical, seed=0, max_steps=8).compare_initial(private)


def _r2_fresh_worker(mode, incoming, outgoing):
    """Compatibility worker delegating to G3's fresh R2-only implementations."""
    d = _r2_validate(replay._strict_json(Path(incoming).read_bytes()))
    if mode == "inner":
        result = g3._fresh_test_only_inner(d)
    elif mode == "timed":
        result = g3._fresh_test_only_timed(d)
    else:
        raise ValueError("unknown R2 worker")
    replay.exact_equal_v3(result["ordered_sequence"], d["ordered_production_sequence"], "R2 fresh flat sequence")
    report = {"scope": R2_SCOPE, "boundaries": R2_BOUNDARIES, "worker": mode,
        "status": "MATCH", "accepted_steps": 8, "R2_steps": 3, "test_only": True,
        "formal_result_eligible": False, "full_game": False,
        "promotion": False, "artifact_identity": d["artifact_identity"],
        "ordered_production_sequence_identity": replay.ordered_production_sequence_identity_v1(result["ordered_sequence"])}
    runner._atomic_json(Path(outgoing), report)


def test_r2_once_fresh_test_only_composition(r2_targeted_artifact):
    incoming = os.environ.get("C8_R2_COMPOSITION_REPORT_IN")
    if incoming:
        report = replay._strict_json(Path(incoming).read_bytes())
    else:
        if os.environ.get("C8_R2_COMPOSE_AUTHORIZATION") != R2_TASK:
            pytest.skip("test-only composition requires its own explicit once-only opt-in")
        root = Path(os.environ["C8_R2_EVIDENCE_ROOT"])
        report_path = root / "r2_composition_result.json"
        assert not report_path.exists(), "one composition only"
        workers = []
        (root / "logs").mkdir(parents=True, exist_ok=True)
        for mode in ("inner", "timed"):
            output = root / ("r2_fresh_"+mode+".json")
            assert not output.exists(), "no automatic worker retry"
            code = "import sys; sys.path.insert(0, 'tests'); from test_c8_timed_8p_full_game_production_replay_v1 import _r2_fresh_worker; _r2_fresh_worker(*sys.argv[1:])"
            start = time.monotonic()
            completed = subprocess.run([sys.executable, "-B", "-c", code, mode,
                str(root/"private"/"r2_targeted_artifact.json"), str(output)], cwd=REPO,
                env={**os.environ, "PYTHONHASHSEED": "0", "PYTHONDONTWRITEBYTECODE": "1"},
                capture_output=True, timeout=15)
            (root/"logs"/("fresh-"+mode+".stdout.txt")).write_bytes(completed.stdout)
            (root/"logs"/("fresh-"+mode+".stderr.txt")).write_bytes(completed.stderr)
            assert completed.returncode == 0, completed.stderr.decode("utf-8", errors="replace")
            workers.append({**replay._strict_json(output.read_bytes()),
                "timeout_seconds": 15, "elapsed_seconds": time.monotonic()-start})
        report = {"scope": R2_SCOPE, "boundaries": R2_BOUNDARIES, "status": "MATCH",
            "artifact_identity": r2_targeted_artifact["artifact_identity"], "workers": workers,
            "inner_timed_stored_flat_sequence": "EXACT_MATCH_NO_SORT_NO_COLLAPSE",
            "production_composition_entry": "REJECTS_TEST_ONLY_AS_REQUIRED",
            "full_game_verifier": "NOT_CALLED", "full_game": False, "promotion": False}
        runner._atomic_json(report_path, report)
    assert report["status"] == "MATCH"
    assert report["artifact_identity"] == r2_targeted_artifact["artifact_identity"]
    assert all(w["ordered_production_sequence_identity"] == r2_targeted_artifact["ordered_production_sequence_identity"] for w in report["workers"])


@pytest.mark.parametrize("field", ["formal_result", "test_only", "natural", "full_game", "promotion", "trace_scope"])
def test_r2_scope_and_header_tamper_rejected_before_worker(r2_targeted_artifact, field, monkeypatch):
    document = copy.deepcopy(r2_targeted_artifact)
    document[field] = True if field != "trace_scope" else "FORMAL_FULL_GAME"
    _rehash_r2_document(document)
    monkeypatch.setattr(g3, "_r2_fresh_workers", lambda *args, **kwargs: pytest.fail("header gate before worker"))
    with pytest.raises(ValueError):
        g3.r2_test_only_evidence_from_dict_v1(document, repo_root=REPO)


def test_r2_cross_rejection_is_bidirectional_and_nonpromotable(r2_targeted_artifact):
    document = r2_targeted_artifact
    timed = document["timed_artifact"]
    with pytest.raises(ValueError):
        runner.timed_artifact_from_dict_v3(timed, full_game=False, repo_root=REPO)
    with pytest.raises(ValueError):
        runner.bounded_smoke_from_dict_v1(timed, repo_root=REPO)
    with pytest.raises(ValueError):
        g3.build_composition_artifact_v1(timed, repo_root=REPO)
    with pytest.raises(ValueError):
        g3.preflight_composition_v1(document, full_game=False, repo_root=REPO)
    with pytest.raises(ValueError):
        g3.verify_full_game_composition_v1(document)
    with pytest.raises(ValueError):
        contract.FullGameResultV1.from_dict(document)
    formal_shaped = {"schema": contract.C8_G1_REPLAY_SCHEMA, "full_game": True, "promotion": False}
    with pytest.raises(ValueError):
        g3.r2_test_only_evidence_from_dict_v1(formal_shaped, repo_root=REPO)


def test_r2_from_dict_does_not_rehydrate_live_session(r2_targeted_artifact, monkeypatch):
    monkeypatch.setattr(
        g3.PrivateIncrementalC6RecorderV1, "cold_session",
        staticmethod(lambda *_args, **_kwargs: pytest.fail("detached parser must not create live session")),
    )
    canonical = {key: value for key, value in r2_targeted_artifact.items()
                 if key not in {"timed_artifact", "setup"}}
    parsed = g3.r2_test_only_evidence_from_dict_v1(canonical, repo_root=REPO)
    assert parsed["scope"] == R2_SCOPE


def test_current_identity_canonical_r1_bounded_regression(r2_targeted_artifact):
    root_value = os.environ.get("C8_R2_EVIDENCE_ROOT")
    if not root_value or os.environ.get("C8_R2_GENERATE_AUTHORIZATION") != R2_TASK:
        pytest.skip("current-identity R1 regression requires supervised evidence run")
    root = Path(root_value).resolve()
    target = root / "private" / "canonical_r1_current_identity_bounded.json"
    assert not target.exists(), "one current-identity R1 regression only"
    timed = runner.execute_bounded_smoke_v1(
        repo_root=REPO, seed=0, max_steps=9, max_windows=8,
        run_label="r1-current-identity",
    )
    assert timed["test_only"] is False
    assert timed["completed_windows"] == 8
    assert timed["completed_production_steps"] == 9
    composition = g3.build_composition_artifact_v1(timed, repo_root=REPO)
    result = g3.verify_bounded_composition_v1(composition)
    report = result.to_report_dict()
    assert report["status"] == "MATCH"
    runner._atomic_json(target, timed)
    runner._atomic_json(root / "private" / "canonical_r1_current_identity_composition.json", composition)
    runner._atomic_json(root / "r1_current_identity_regression.json", report)
