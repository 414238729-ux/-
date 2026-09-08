# -*- coding: utf-8 -*-
import copy
import json
import os
import subprocess
import sys
from pathlib import Path
import pytest
from scripts.sgs_engine import c8_timed_8p_full_game_contract_v1 as contract
from scripts.sgs_engine import c8_timed_8p_full_game_replay_v1 as replay
from scripts.sgs_engine import c8_timed_8p_full_game_runner_v1 as runner
from scripts.sgs_engine import c8_c6_production_adapter_v1 as adapter
from test_c8_timed_8p_full_game_production_replay_v1 import get_fixture, REPO, rehash_g_document


@pytest.mark.parametrize("ordinal,family", [
    (2, "pass_response"), (3, "public_choice"), (0, "pass_response"),
    (3, "mandatory_action"), (2, "mandatory_action"), (0, "public_choice"),
    (2, "decline_optional"), (2, "PASS"),
])
def test_step1362_g2_rejects_family_spoofing(ordinal, family, monkeypatch):
    from test_c8_c6_production_adapter_v1 import _step1362_stack
    stack = _step1362_stack()
    target_id = stack.session.legal_actions()[ordinal].action_id
    original = adapter._family_for_action
    supplied = family if family == "PASS" else adapter.c8.PublicActionFamilyV1(family)
    monkeypatch.setattr(adapter, "_family_for_action",
        lambda a, c: supplied if a.action_id == target_id else original(a, c))
    with pytest.raises(adapter.C8C6ProductionAdapterError, match="SEMANTIC_REJECT"):
        runner.public_driver_input_v1(session=stack.session, context_value=stack.context,
            formal_seed=0, global_window_index=1328, deadline_at=100)
    assert stack.session.step_count == 4 and stack.runtime.active_window_ref() == stack.ref


@pytest.mark.parametrize("field", ["operation", "raw_operation", "card_id", "card_instance_id", "handle", "private_payload", "payload"])
def test_step1362_g1_private_injection_rejected(field):
    from test_c8_c6_production_adapter_v1 import _step1362_stack
    stack = _step1362_stack()
    value, _ = runner.public_driver_input_v1(session=stack.session, context_value=stack.context,
        formal_seed=0, global_window_index=1328, deadline_at=100)
    material = value.identity_material()
    assert [v["public_action_family"] for v in material["public_actions"]] == ["RESPOND", "RESPOND", "ACTIVATE", "PASS"]
    assert all(set(v) == {"public_ordinal", "public_action_family"} for v in material["public_actions"])
    assert not any(v in json.dumps(material) for v in ("activate_bagua", "pass_slash_response", "play_dodge"))
    material["public_actions"][2][field] = "private-forbidden"
    with pytest.raises(ValueError):
        runner._driver_input_from_dict(material)
    assert stack.session.step_count == 4


def test_step1362_g1_non_decline_eligibility_and_profile_migration():
    from test_c8_c6_production_adapter_v1 import _step1362_stack
    stack = _step1362_stack()
    value, _ = runner.public_driver_input_v1(session=stack.session, context_value=stack.context,
        formal_seed=0, global_window_index=1327, deadline_at=100)
    assert contract._eligible_ordinals(value) == (0, 1, 2)
    decision = contract.choose_formal_driver_action_v1(value)
    assert not decision.actual_timeout and decision.chosen_public_ordinal in (0, 1, 2)
    assert contract.C8_G1_DRIVER_MATERIAL_VERSION == 3
    assert contract.C8_G1_DRIVER_POLICY_IDENTITY == contract.identity_v1(contract.formal_driver_policy_descriptor_v1())
    assert contract.C8_G1_DRIVER_POLICY_IDENTITY != "f5bf5d07e990bb0ea1fb78bc636abf2e8300e009c8a4636dfbbf840761139514"
    current = runner.validate_execution_order_profile_v1()
    assert current["version"] == 1
    assert contract.PRIVATE_ORDINAL_CERTIFICATE_IDENTITY_V1 == contract.identity_v1(dict(contract.PRIVATE_ORDINAL_ORDER_CERTIFICATE_V1))
    old = copy.deepcopy(current)
    old["source_certificate_identity"] = "dda7b550e300a811a61e869885c3f3d776674068de068f6fb0dfbd651889b0f0"
    old["profile_identity"] = contract.identity_v1({k:v for k,v in old.items() if k != "profile_identity"})
    assert old["profile_identity"] == "ae7f1cae9717625b7d6e19ca6aa1bcbf3ddfe50b44aada8bc17edba08e281ed1"
    with pytest.raises(ValueError, match="execution-order"):
        runner.validate_execution_order_profile_v1(old)


@pytest.mark.parametrize("family", ["decline_optional", "mandatory_action"])
def test_w592_g2_rejects_e_semantic_family_mismatch(family, monkeypatch):
    from test_c8_c6_production_adapter_v1 import _w592_stack
    stack = _w592_stack("guanshifu_force_hit")
    monkeypatch.setattr(adapter, "_family_for_action", lambda *args: adapter.c8.PublicActionFamilyV1(family))
    with pytest.raises(adapter.C8C6ProductionAdapterError, match="SEMANTIC_REJECT"):
        runner.public_driver_input_v1(session=stack.session, context_value=stack.context,
            formal_seed=0, global_window_index=592, deadline_at=100)
    assert stack.session.step_count == 5


@pytest.mark.parametrize("field", ["operation", "card_instance_id", "handle", "payload"])
def test_w592_g1_input_rejects_private_material(field):
    from test_c8_c6_production_adapter_v1 import _w592_stack
    stack = _w592_stack("guanshifu_force_hit")
    value, _ = runner.public_driver_input_v1(session=stack.session, context_value=stack.context,
        formal_seed=0, global_window_index=592, deadline_at=100)
    material = value.identity_material()
    assert not any(key in json.dumps(material) for key in ("weapon_force_hit", "pass_weapon_choice", "card_instance_id", "handle"))
    material["public_actions"][0][field] = "private-forbidden"
    with pytest.raises(ValueError):
        runner._driver_input_from_dict(material)


def test_w592_certificate_constructs_new_driver_and_rejects_old_profile():
    import hashlib
    for relative, digest in contract.PRIVATE_ORDINAL_SOURCE_HASHES_V1.items():
        assert hashlib.sha256((REPO/relative).read_bytes()).hexdigest() == digest
    assert contract.PRIVATE_ORDINAL_SOURCE_HASHES_V1["scripts/sgs_engine/c8_c6_production_adapter_v1.py"] != "cc0a552233fac6022568393da267c505620fb552e25647fc7acec67d80cdb011"
    assert contract.PRIVATE_ORDINAL_CERTIFICATE_IDENTITY_V1 == contract.identity_v1(dict(contract.PRIVATE_ORDINAL_ORDER_CERTIFICATE_V1))
    assert contract.C8_G1_DRIVER_MATERIAL_VERSION == 3
    assert contract.C8_G1_DRIVER_POLICY_IDENTITY == contract.identity_v1(contract.formal_driver_policy_descriptor_v1())
    current = runner.validate_execution_order_profile_v1()
    assert current["version"] == 1
    old = copy.deepcopy(current)
    old["source_certificate_identity"] = "eb3ec94079c6985bddc29dfe6ef618018a4929a8a7e06022714addd30840750a"
    old["profile_identity"] = contract.identity_v1({k:v for k,v in old.items() if k != "profile_identity"})
    assert old["profile_identity"] == "6e40b7c0900bf04e44f6e71fdb163dd6cdd995739f69d69a8fa52f009e1d02a5"
    with pytest.raises(ValueError, match="execution-order"):
        runner.validate_execution_order_profile_v1(old)


def test_v3_gate_real_b_public_continuation_keeps_owner_deadline_and_counter():
    """Real B with its existing test-only opaque adapter; not a C6 production trace."""
    from test_c8_timed_session_runtime_v1 import _runtime, _open, _advance, _sha, c8
    runtime, inner = _runtime()
    ref = _open(runtime, kind=c8.TimedWindowKindV1.MULTI_STEP_OBLIGATION)
    _advance(runtime, 99)
    for i in range(3):
        runtime.forward_on_time_signed_action_id(ref, signed_action_id=f"test-only-step-{i}")
        assert inner.public_counter == i+1
        if i < 2:
            runtime.continue_multi_step_obligation(ref, expected_step_index=i, logical_step_identity=_sha(f"accepted-{i}"))
            assert runtime.state.logical_obligations[-1].next_step_index == i+1
            assert runtime.active_window_ref() == ref
            assert runtime.state.virtual_time_state.now_tick == 99
            assert runtime.state.virtual_time_state.window_stack.active_window.deadline_at == 100
    runtime.close_window_by_action(ref)
    assert runtime.active_window_ref() is None
    assert inner.private_payload_calls == 0
    events = [v.event_kind.value for v in runtime.state.runtime_events]
    assert events.count("WINDOW_OPENED") == 1
    assert events.count("INNER_SIGNED_ACTION_FORWARDED") == 3
    assert events.count("MULTI_STEP_CONTINUED") == 2
    assert events.count("WINDOW_CLOSED_BY_ACTION") == 1


def test_v3_gate_duplicate_progress_fails_without_reverting_accepted_step():
    from test_c8_timed_session_runtime_v1 import _runtime, _open, _advance, _sha, c8
    runtime, inner = _runtime()
    ref = _open(runtime, kind=c8.TimedWindowKindV1.MULTI_STEP_OBLIGATION)
    _advance(runtime, 99)
    runtime.forward_on_time_signed_action_id(ref, signed_action_id="test-only-accepted")
    runtime.continue_multi_step_obligation(ref, expected_step_index=0, logical_step_identity=_sha("accepted"))
    with pytest.raises(runner.runtime_v1.C8TimedSessionRuntimeError):
        runtime.continue_multi_step_obligation(ref, expected_step_index=0, logical_step_identity=_sha("accepted"))
    assert inner.public_counter == 1
    assert not any(v == "restore_transaction_snapshot_v1" for v in inner.calls)


@pytest.mark.parametrize("field", ["originating_decision_evidence_identity","originating_completion_identity","originating_step_identity"])
def test_v3_gate_fully_rehashed_parent_reaches_actual_semantic_origin_check(field):
    # Detached model records only; actual parser calls this exact semantic gate.
    origin = dict(causal_relation_kind=contract.CausalRelationKindV2.POST_COMMIT_CAUSAL_SUCCESSOR,
        causal_parent_window_identity="1"*64,causal_parent_context_identity="2"*64,
        originating_step_index=6,originating_step_identity="3"*64,originating_post_production_revision=2,
        originating_post_public_state_identity="4"*64,originating_decision_kind=replay.ON_TIME_KIND,
        originating_decision_evidence_identity="5"*64,originating_completion_identity="6"*64,
        parent_window_close_status="CLOSED_BY_ACTION",post_step_context_identity="7"*64)
    parent = {"record_identity":"1"*64,"steps":[{"decision":{"kind":replay.ON_TIME_KIND,
        "evidence_identity":"5"*64,"binding":{"production_context_identity":"2"*64,"step_index":6,
            "inner_decision_identity":"3"*64,"post_revision":2}},
        "completion":{"completion_identity":"6"*64},"post_state":{"state_identity":"4"*64}}]}
    runner._validate_parent_origin_v4(contract.WindowRelationEvidenceV3.post_commit_v3(**origin),parent)
    origin[field] = "f"*64
    malicious = contract.WindowRelationEvidenceV3.post_commit_v3(**origin).to_dict()
    parsed = contract.WindowRelationEvidenceV3.from_dict(malicious)
    with pytest.raises(ValueError,match="typed parent origin "+field):
        runner._validate_parent_origin_v4(parsed,parent)


def test_v3_gate_two_fresh_processes_agree_on_public_order():
    code = "from scripts.sgs_engine.c8_timed_8p_full_game_runner_v1 import validate_execution_order_profile_v1; import json; print(json.dumps(validate_execution_order_profile_v1(), sort_keys=True))"
    env = {**os.environ, "PYTHONHASHSEED":"0", "PYTHONDONTWRITEBYTECODE":"1"}
    results = [subprocess.run([sys.executable, "-B", "-c", code], cwd=REPO, capture_output=True, env=env, timeout=8, check=True) for _ in range(2)]
    assert results[0].stdout == results[1].stdout
    assert json.loads(results[0].stdout)["public_equipment_slot_order"] == list(contract.PUBLIC_EQUIPMENT_SLOT_ORDER_V1)


@pytest.mark.parametrize("seed", [None, "1", "42"])
def test_v3_gate_wrong_startup_profile_rejected_before_session(seed):
    code = "from scripts.sgs_engine import c8_timed_8p_full_game_runner_v1 as r; r.prod.create_canonical_c6_no_skill_session_v1=lambda *a: (_ for _ in ()).throw(AssertionError('SESSION_MUST_NOT_BE_CREATED')); r.create_canonical_session_bundle_v1(seed=0)"
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE":"1"}
    env.pop("PYTHONHASHSEED", None)
    if seed is not None:
        env["PYTHONHASHSEED"] = seed
    result = subprocess.run([sys.executable,"-B","-c",code],cwd=REPO,capture_output=True,env=env,timeout=8)
    assert result.returncode != 0
    assert b"EXECUTION_ORDER_PROFILE_MISMATCH" in result.stderr
    assert b"AssertionError: SESSION_MUST_NOT_BE_CREATED" not in result.stderr


def test_v3_gate_order_source_drift_rejected_before_factory(monkeypatch):
    original = runner._file_sha256
    monkeypatch.setattr(runner, "_file_sha256", lambda p: "f"*64 if p.name == "production_batch.py" else original(p))
    monkeypatch.setattr(runner.prod, "create_canonical_c6_no_skill_session_v1", lambda *a: pytest.fail("source mismatch before session"))
    with pytest.raises(ValueError, match="source/order certificate"):
        runner.create_canonical_session_bundle_v1(seed=0)


def _v3_diagnostic_boundary(step):
    public = {"accepted_step_count":step,"state_revision":0,"event_count":0,"rng_count":0,
        "alive_count":8,"alive_hp_sum":32,"alive_hp_min":4,"alive_hp_max":4,"dying_count":0,
        "effects_delta":{k:0 for k in runner.DIAGNOSTIC_EFFECT_FIELDS_V1}}
    return contract.canonical_json_bytes_v1({"public":public,"private":{"per_player_hp":{"p1":4},"secret":"PRIVATE_CANARY"}})


def _v3_sink(tmp_path):
    sink = runner.ReportOnlyDiagnosticSinkV1(tmp_path)
    sink.start(_v3_diagnostic_boundary(0), construction={"run_label":"test-only-diagnostic", "execution_order_profile":runner.validate_execution_order_profile_v1()},
        cell_execution_identity="a"*64,binding=runner.current_binding_snapshot_v1(contract.FullGameRegistryV1.canonical()),
        position_bytes=contract.canonical_json_bytes_v1({"turn_number":1,"turn_player_id":"p1","actor_id":"p1","phase":"play","availability":"PUBLIC_BOUNDARY","reason":None}))
    sink.note_open(contract.canonical_json_bytes_v1({"window_index":1,"timeout_intent":False,"actual_timeout":False,"skipped_unresolved":False}))
    return sink


def _v3_report_row(index):
    from test_c8_timed_8p_full_game_replay_v1 import pure_continued_decision_v3
    decision = pure_continued_decision_v3()
    decision["binding"]["post_step_count"] = index
    decision["binding"]["window_step_index"] = index-1
    decision["binding"]["global_window_index"] = 1
    return runner.diagnostic_step_projection_v1({"decision":decision,"post_state":{"window_depth":1,
        "turn_number":1,"current_player_id":"p1","current_actor_id":"p1","phase":"discard","production_finished":False}})


def test_v3_gate_diagnostic_50_rows_atomic_private_separation_and_no_resume(tmp_path):
    sink = _v3_sink(tmp_path)
    for index in range(1, 52):
        sink.accept(_v3_diagnostic_boundary(index), step_bytes=_v3_report_row(index), completed_window_count=0)
    sink.finish(status="FAILED", last_accepted_step=51,last_fully_evidenced_step=51,completed_window_count=0)
    public = [json.loads(p.read_bytes()) for p in sorted((tmp_path/"progress").glob("*.json"))]
    assert [len(p["delta_step_rows"]) for p in public] == [0,50,1]
    assert [p["last_accepted_step"] for p in public] == [0,50,51]
    for p in public:
        assert p["checksum"] == contract.identity_v1({k:v for k,v in p.items() if k != "checksum"})
        assert p["scope"] == "REPORT_ONLY"
        assert p["resume_capable"] is p["gameplay_authority"] is p["promotion_authority"] is False
        assert "PRIVATE_CANARY" not in json.dumps(p)
        assert "per_player_hp" not in json.dumps(p)
        assert p["last_authoritative_replay_step"] is None
    assert "PRIVATE_CANARY" in next((tmp_path/"private").glob("*.json")).read_text()
    latest = json.loads((tmp_path/"latest.json").read_bytes())
    assert latest["last_durable_diagnostic_step"] == 51 and latest["resume_capability"] == "NONE"
    with pytest.raises(ValueError, match="禁止resume"):
        runner.ReportOnlyDiagnosticSinkV1(tmp_path)


def test_v3_gate_io_retries_exact_bytes_once_and_does_not_advance_gameplay(tmp_path,monkeypatch):
    sink = _v3_sink(tmp_path)
    seen = []
    def failure(src,dst):
        seen.append(Path(src).read_bytes())
        raise PermissionError("test-only unavailable disk")
    monkeypatch.setattr(runner.os,"replace",failure)
    with pytest.raises(runner.DiagnosticIOFailureV1):
        sink._write_bytes(tmp_path/"private"/"test.json", b"IMMUTABLE", immutable=True)
    assert seen == [b"IMMUTABLE",b"IMMUTABLE"]
    assert sink.last_durable == 0 and sink.boundary["public"]["accepted_step_count"] == 0
    assert not any(hasattr(sink, key) for key in ("session","driver","runtime","recorder","resume","step"))


@pytest.mark.parametrize("field", ["payload","per_player_hp","private_state_identity"])
def test_v3_gate_diagnostic_public_unknown_or_private_fields_fail_closed(field):
    d = json.loads(_v3_diagnostic_boundary(0))
    d["public"][field] = "PRIVATE_CANARY"
    with pytest.raises(ValueError):
        runner._diagnostic_boundary_from_bytes_v1(contract.canonical_json_bytes_v1(d))


@pytest.mark.parametrize("field,value", [("version",True),("last_accepted_step",True),
    ("gameplay_authority",True),("resume_capability","LIVE"),("payload",{})])
def test_v3_gate_diagnostic_snapshot_strict_rehashed_envelope(tmp_path,field,value):
    _v3_sink(tmp_path)
    d = json.loads(next((tmp_path/"progress").glob("*.json")).read_bytes())
    d[field] = value
    d["checksum"] = contract.identity_v1({k:v for k,v in d.items() if k!="checksum"})
    with pytest.raises(ValueError):
        runner.diagnostic_snapshot_from_dict_v1(d)


def test_v3_gate_failed_accepted_evidence_tail_keeps_unknown_metrics_explicit(tmp_path):
    sink = _v3_sink(tmp_path)
    sink.finish(status="FAILED",last_accepted_step=1,last_fully_evidenced_step=0,completed_window_count=0)
    d = json.loads(sorted((tmp_path/"progress").glob("*.json"))[-1].read_bytes())
    assert d["last_accepted_step"] == 1 and d["metrics_observed_at_step"] == 0
    assert d["metrics_availability"] == "LAST_OBSERVED_BOUNDARY_TAIL_MISSING"
    assert d["io"]["accepted_but_not_evidenced"] is True
    assert d["schedule"]["on_time_window_count"] == d["schedule"]["accepted_on_time_steps"] == 0
    assert d["schedule"]["opened_windows"] == 1


def test_v3_gate_private_write_before_pointer_and_unwritable_tail_is_truthful(tmp_path,monkeypatch,capsys):
    sink = _v3_sink(tmp_path)
    before = (tmp_path/"latest.json").read_bytes()
    sink.accept(_v3_diagnostic_boundary(1),step_bytes=_v3_report_row(1),completed_window_count=0)
    calls = []
    def denied(source,target):
        calls.append((str(target),Path(source).read_bytes()))
        raise PermissionError("PRIVATE_RAW_ERROR_MUST_NOT_LEAK")
    monkeypatch.setattr(runner.os,"replace",denied)
    with pytest.raises(runner.DiagnosticIOFailureV1):
        sink.finish(status="FAILED",last_accepted_step=1,last_fully_evidenced_step=1,completed_window_count=0)
    assert (tmp_path/"latest.json").read_bytes() == before
    assert sink.last_durable == 0 and sink.boundary["public"]["accepted_step_count"] == 1
    assert len(calls) == 4  # one same-byte retry for private generation, one for independent failure receipt
    assert calls[0] == calls[1] and calls[2] == calls[3]
    receipt = json.loads(capsys.readouterr().err)
    assert receipt["last_accepted_step"] == 1 and receipt["last_durable_diagnostic_step"] == 0
    assert "PRIVATE_RAW_ERROR" not in json.dumps(receipt)


def test_v3_gate_private_public_forwarding_never_reads_action_payload_or_card(monkeypatch):
    from types import SimpleNamespace
    from test_c8_timed_8p_full_game_contract_v1 import _public_ordinal_v3_entry
    # Poison attributes at the existing opaque boundary, without constructing a C6 session.
    class Opaque:
        action_id = "signed-test-only"
        def __getattr__(self,name):
            raise AssertionError("private action attribute read: "+name)
    progress = _public_ordinal_v3_entry(1)
    ctx = SimpleNamespace(window_kind=runner.clock_v1.TimedWindowKindV1.MULTI_STEP_OBLIGATION,
        applicability=adapter.ProductionContextApplicabilityV1.PRIVATE_ORDINAL_TIMEOUT_UNRESOLVED,
        phase=SimpleNamespace(value="discard"),turn_number=1,current_actor_id="p1",current_player_id="p1",proposal_count=1)
    monkeypatch.setattr(runner,"_public_actions_raw",lambda *a:(Opaque(),))
    inp,ids = runner.public_driver_input_v1(session=None,context_value=ctx,formal_seed=0,
        global_window_index=5,deadline_at=497,public_ordinal_progress=progress)
    assert ids == ("signed-test-only",)
    assert contract.choose_formal_driver_action_v1(inp).chosen_public_ordinal == 0


def smoke():
    return copy.deepcopy(get_fixture()['timed_artifact'])


def rehash(d):
    d['artifact_identity'] = contract.identity_v1({k:v for k,v in d.items() if k != 'artifact_identity'})


def test_typed_smoke_current_roundtrip_nonterminal():
    d = runner.bounded_smoke_from_dict_v1(smoke(), repo_root=REPO)
    assert d['schema'] == 'sgs-c8-g2-bounded-integration-smoke-v4'
    assert d['completed_windows'] == 8 and 8 < d['completed_production_steps'] <= 12
    assert d['full_game'] is d['promotion'] is False
    assert d['final_state']['window_depth'] == 0
    assert d['final_security_audit']['guard_active'] is False


def test_closed_play_parent_discard_is_successor_not_response_or_rescue():
    records = smoke()['window_records']
    parent, successor = records[3], records[4]
    assert parent['steps'][-1]['decision']['kind'] == replay.TIMEOUT_KIND
    assert parent['steps'][-1]['decision']['binding']['phase'] == 'play'
    r = successor['relation']
    assert r['causal_relation_kind'] == 'POST_COMMIT_CAUSAL_SUCCESSOR'
    assert r['causal_parent_window_identity'] == parent['record_identity']
    assert r['originating_decision_evidence_identity'] == parent['steps'][-1]['decision']['evidence_identity']
    assert r['originating_completion_identity'] == parent['steps'][-1]['completion']['completion_identity']
    assert r['expected_active_parent_ref'] is None
    assert successor['opened_window']['parent_window_id'] is None
    assert successor['opened_window']['deadline_at'] != parent['opened_window']['deadline_at']


@pytest.mark.parametrize('key', ['originating_decision_kind','originating_decision_evidence_identity','originating_completion_identity','originating_step_identity'])
def test_typed_parent_splice_rejected(key):
    document = copy.deepcopy(get_fixture())
    d = document["timed_artifact"]
    r = d["window_records"][4]["relation"]
    r[key] = replay.ON_TIME_KIND if key == "originating_decision_kind" else "f"*64
    if key == "originating_decision_kind":
        r["parent_window_close_status"] = "CLOSED_BY_ACTION"
    rehash_g_document(document)
    # Relation's own close/observe, decision binding, step/window, public and
    # composition envelopes are all consistent. Failure must reach semantic origin.
    contract.WindowRelationEvidenceV3.from_dict(r)
    with pytest.raises(ValueError, match="typed parent origin "+key):
        runner.bounded_smoke_from_dict_v1(d, repo_root=REPO)


@pytest.mark.parametrize('max_steps,max_windows,seed', [(13,8,0),(8,9,0),(8,8,1),(True,8,0),(8,True,0),(0,1,0)])
def test_limits_rejected_before_factory(max_steps,max_windows,seed):
    with pytest.raises(ValueError):
        runner.execute_bounded_smoke_v1(repo_root=REPO, max_steps=max_steps,max_windows=max_windows,seed=seed,
            bundle_factory=lambda **kw: pytest.fail('limits before factory'),test_only=True)


def test_injected_factory_requires_explicit_test_only():
    with pytest.raises(ValueError):
        runner.execute_bounded_smoke_v1(repo_root=REPO,bundle_factory=lambda **kw: pytest.fail('must reject injection'))


@pytest.mark.parametrize('field', ['completed_windows','completed_production_steps','contract_version'])
def test_root_count_bool_alias_rejected(field):
    d = smoke()
    d[field] = True
    rehash(d)
    with pytest.raises(ValueError):
        runner.bounded_smoke_from_dict_v1(d,repo_root=REPO)


@pytest.mark.parametrize('index', range(8))
def test_each_window_retains_complete_refresh_and_operation_order(index):
    w = smoke()['window_records'][index]
    assert len(w['refreshes']) == 2
    assert w['refreshes'][0] == w['refreshes'][1]
    assert [v['name'] for v in w['steps'][0]['operations']][:4] == ['OPEN','REFRESH','REFRESH','FRESH_EXECUTION_CONTEXT']
    for local,step in enumerate(w["steps"]):
        names = [o["name"] for o in step["operations"]]
        assert names[-1] == ("CONTINUE_ON_TIME" if local < len(w["steps"])-1 else "STALE_REJECT")
        assert step["decision"]["binding"]["post_step_count"] == step["decision"]["binding"]["pre_step_count"]+1
        if local:
            assert not set(names) & {"OPEN","REFRESH","ADVANCE","DUE","RESOLVE"}
            assert step["decision"]["binding"]["deadline_at"] == w["opened_window"]["deadline_at"]


def test_resume_reuses_saved_fixture_without_gameplay(tmp_path, monkeypatch):
    d = smoke()
    runner._atomic_json(tmp_path/'bounded_smoke.json',d)
    runner._atomic_json(tmp_path/'state.json',{'schema':runner.C8_G2_PROGRESS_SCHEMA,'status':'BOUNDED_STOP',
        'artifact_sha256':runner._file_sha256(tmp_path/'bounded_smoke.json'),'artifact_identity':d['artifact_identity'],
        'last_accepted_step':d['completed_production_steps'],'last_durable_diagnostic_step':d['completed_production_steps'],
        'last_authoritative_replay_step':None,'resume_capability':'NONE'})
    monkeypatch.setattr(runner,'execute_bounded_smoke_v1',lambda **kw:pytest.fail('resume must not replay gameplay'))
    assert runner.run_bounded_runner_v1(repo_root=REPO,output_dir=tmp_path,resume=True)['status'] == 'REUSED_EXISTING_ARTIFACT_NO_GAMEPLAY'


@pytest.mark.parametrize("depth", [0,1])
def test_v3_gate_committed_failure_v5_cursor_keeps_real_b_accepted_step(tmp_path,monkeypatch,depth):
    from types import SimpleNamespace
    from test_c8_timed_session_runtime_v1 import _runtime,_open,_advance
    runtime,inner = _runtime()
    ref = _open(runtime)
    _advance(runtime,99)
    runtime.forward_on_time_signed_action_id(ref,signed_action_id="test-only-accepted")
    if not depth:
        runtime.close_window_by_action(ref)
    session = SimpleNamespace(step_count=inner.public_counter,state=SimpleNamespace(revision=0),phase=SimpleNamespace(value="play"))
    bundle = SimpleNamespace(session=session,runtime=runtime)
    error = runner._committed_failure(bundle,[],1,None,last_evidenced=0,last_durable=0,reason="POST_COMMIT_EVIDENCE_INCOMPLETE")
    failure = runner.committed_step_failure_from_dict_v2(error.failure_artifact)
    assert failure["last_accepted_step"] == failure["committed_step_count"] == 1
    assert failure["last_fully_evidenced_step"] == failure["last_durable_diagnostic_step"] == 0
    assert failure["current_public_cursor"]["window_depth"] == depth
    assert failure["last_authoritative_replay_step"] is None and failure["resume_capability"] == "NONE"
    assert failure["typed_decision"] is None and failure["production_step_rollback_claimed"] is False
    assert inner.public_counter == 1 and "restore_transaction_snapshot_v1" not in inner.calls
    runner._atomic_json(tmp_path/"failure.json",failure)
    runner._atomic_json(tmp_path/"state.json",{"schema":runner.C8_G2_PROGRESS_SCHEMA,"status":"FAILED_INCOMPLETE_AFTER_COMMITTED_STEP"})
    monkeypatch.setattr(runner,"execute_bounded_smoke_v1",lambda **kw:pytest.fail("no replay after accepted failure"))
    with pytest.raises(ValueError,match="禁止resume"):
        runner.run_bounded_runner_v1(repo_root=REPO,output_dir=tmp_path,resume=True)


def test_formal_entry_has_fixed_verifier_and_rejects_bounded():
    with pytest.raises(ValueError):
        runner.run_candidate_or_formal_v1(artifact=get_fixture())
    with pytest.raises(TypeError):
        runner.run_candidate_or_formal_v1(artifact=get_fixture(),verifier=lambda *a:True)
