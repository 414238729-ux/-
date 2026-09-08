# -*- coding: utf-8 -*-
"""G1 v4 typed schema tests. Production fixture is the one externally saved prefix."""
import copy
import json
import pytest
from scripts.sgs_engine import c8_timed_8p_full_game_contract_v1 as contract
from scripts.sgs_engine import c8_timed_8p_full_game_replay_v1 as replay
from test_c8_timed_8p_full_game_production_replay_v1 import get_fixture


def pure_continued_decision_v3():
    """Typed parser example only. It has no C6/session/proof authority."""
    from test_c8_timed_8p_full_game_contract_v1 import _public_ordinal_v3_entry
    progress = _public_ordinal_v3_entry()
    options = tuple(contract.PublicActionOptionV1(i, "PRIVATE_ORDINAL") for i in range(3))
    inp = contract.FormalDriverInputV1(formal_seed=0, global_window_index=5, turn_number=1,
        turn_player_id="p1", actor_id="p1", phase="discard", window_kind=contract.PublicWindowKindV1.PRIVATE_ORDINAL_TIMEOUT_UNRESOLVED,
        deadline_at=497, timeout_applicability=contract.TimeoutApplicabilityV1.PRIVATE_ORDINAL_TIMEOUT_UNRESOLVED,
        proposal_order_identity=contract.identity_v1([a.to_dict() for a in options]), public_actions=options,
        public_ordinal_progress=progress)
    actions = [{**a.to_dict(), "signed_action_id_commitment": str(i+1)*64} for i, a in enumerate(options)]
    binding = {key: "a"*64 for key in replay.BINDING_FIELDS.split()}
    binding.update(inner_decision_index=4, step_index=5, global_window_index=5, window_step_index=0,
        turn_number=1, turn_player_id="p1", actor_id="p1", phase="discard", window_id="pure-window",
        window_authority_ref_identity=progress.opening_ref_identity, opening_production_context_identity=progress.opening_context_identity,
        production_window_kind="MULTI_STEP_OBLIGATION", driver_window_kind=inp.window_kind.value,
        pre_revision=2, post_revision=2, pre_step_count=4, post_step_count=5,
        pre_execution_identity="b"*64, post_execution_identity="c"*64,
        event_start=0, event_end=0, rng_start=0, rng_end=0, opened_at=397, deadline_at=497, decision_tick=496,
        runtime_event_range={"start": 0, "end": 2}, controller_event_range={"start": 0, "end": 0},
        production_action_ref={"inner_decision_index":4,"signed_action_id_commitment": "1"*64,
            "ordered_legal_action_commitment":"d"*64,"executed_public_ordinal":0,"executed_public_action_family":"PRIVATE_ORDINAL"})
    post = {"next_phase":"discard", "next_actor_id":"p1", "next_turn_number":1,"next_turn_player_id":"p1","next_proposal_count":3}
    after = contract.advance_public_ordinal_progress_v1(progress, chosen_ordinal=0, post_step_count=5, **post)
    d = {"schema":replay.ON_TIME_SCHEMA,"kind":replay.ON_TIME_KIND,"binding":binding,
        "fresh_public_legal_set":{"actions":actions,"proposal_order_identity":inp.proposal_order_identity,"legal_set_commitment":contract.identity_v1(actions)},
        "driver_input":inp.identity_material(),"driver_decision":replay.driver_decision_dict_v3(inp),
        "normal_forward":{"returned_public_state_identity":binding["post_public_state_identity"],"inner_transition_identity":"e"*64,"runtime_forward_event_identity":"f"*64},
        "liveness":{"before":progress.to_dict(),"after":after.to_dict(),"post_public_boundary":post},
        "completion":{"kind":"ON_TIME_OBLIGATION_CONTINUED","logical_step_identity":replay.logical_continuation_identity_v1(binding,progress),
            "continue_event_identity":binding["window_disposition_ref"],"progress_identity":"6"*64,"post_step_observation_identity":"7"*64}}
    rehash(d)
    return d


def test_v3_gate_cheap_typed_continued_record_is_data_only():
    d = pure_continued_decision_v3()
    assert replay.production_decision_from_dict_v1(d).to_dict() == d
    assert replay.completion_from_decision_v1(d).disposition == "CONTINUED"


@pytest.mark.parametrize("mutation", ["ordinal", "q", "n", "reverse", "commit", "opening", "unknown", "bool-local"])
def test_v3_gate_rehashed_private_induction_splices_rejected(mutation):
    d = pure_continued_decision_v3()
    if mutation == "ordinal":
        d["binding"]["production_action_ref"].update(executed_public_ordinal=2, signed_action_id_commitment="3"*64)
    elif mutation in {"q", "n"}:
        field = "candidate_count" if mutation == "n" else "certified_selected_progress_count"
        d["liveness"]["after"][field] += 1
    elif mutation == "reverse":
        d["liveness"]["after"]["certified_selected_progress_count"] = 0
    elif mutation == "commit":
        d["completion"] = {"kind":"ON_TIME_CONTEXT_CLOSED", "close_event_identity":"a"*64,
            "closed_window_identity":"b"*64,"completed_context_identity":"4"*64,"post_step_observation_identity":"7"*64}
    elif mutation == "opening":
        d["binding"]["opening_production_context_identity"] = "f"*64
    elif mutation == "unknown":
        d["liveness"]["after"]["private_payload"] = None
    else:
        d["binding"]["window_step_index"] = False
    rehash(d)
    with pytest.raises(ValueError):
        replay.production_decision_from_dict_v1(d)


def decision(index=0):
    from scripts.sgs_engine.c8_timed_8p_full_game_runner_v1 import flat_step_records_v4
    return copy.deepcopy(flat_step_records_v4(get_fixture()['timed_artifact'])[index]['decision'])


def rehash(value):
    value['evidence_identity'] = contract.identity_v1({k:v for k,v in value.items() if k != 'evidence_identity'})


def test_all_flat_typed_decisions_roundtrip_and_completion():
    from scripts.sgs_engine.c8_timed_8p_full_game_runner_v1 import flat_step_records_v4
    for step in flat_step_records_v4(get_fixture()['timed_artifact']):
        d = step['decision']
        parsed = replay.production_decision_from_dict_v1(d)
        replay.exact_equal_v3(parsed.to_dict(), d, 'roundtrip')
        completed = replay.completion_from_decision_v1(d)
        assert contract.DecisionCompletionEvidenceV1.from_dict(completed.to_dict()) == completed


@pytest.mark.parametrize('key', ['timeout_due_commitment','c_resolver_result_and_selected_action_ref','e_fresh_confirmation_and_issuance_evidence','b_timeout_receipt_link','transaction_receipt_identity'])
@pytest.mark.parametrize('value', [None, {}])
def test_on_time_rejects_timeout_fields_even_null(key, value):
    d = decision()
    d[key] = value
    rehash(d)
    with pytest.raises(ValueError):
        replay.production_decision_from_dict_v1(d)


@pytest.mark.parametrize('key', ['timeout_due_commitment','c_resolver_result_and_selected_action_ref','e_fresh_confirmation_and_issuance_evidence','b_timeout_receipt_link','security_operation_evidence'])
def test_timeout_requires_actual_c_e_b_evidence(key):
    d = decision(3)
    del d[key]
    rehash(d)
    with pytest.raises(ValueError):
        replay.production_decision_from_dict_v1(d)


@pytest.mark.parametrize('index,tick', [(0,100),(3,398),(3,401)])
def test_lt_eq_reverse_fails_after_rehash(index, tick):
    d = decision(index)
    d['binding']['decision_tick'] = tick
    rehash(d)
    with pytest.raises(ValueError):
        replay.production_decision_from_dict_v1(d)


@pytest.mark.parametrize('field', ['inner_decision_index','step_index','pre_step_count','post_step_count','pre_revision','post_revision','event_start','event_end','rng_start','rng_end'])
def test_binding_refuses_bool_int_alias(field):
    b = decision()['binding']
    b[field] = True
    with pytest.raises(ValueError):
        replay.ProductionActionBindingV1.from_dict(b)


def test_timeout_c_receipt_crosslink_not_just_rehash():
    d = decision(3)
    d['b_timeout_receipt_link']['receipt_identity'] = 'f'*64
    rehash(d)
    with pytest.raises(ValueError):
        replay.production_decision_from_dict_v1(d)


def test_on_time_unknown_nested_field_refused():
    d = decision()
    d['normal_forward']['timeout_receipt'] = None
    rehash(d)
    with pytest.raises(ValueError):
        replay.production_decision_from_dict_v1(d)


def test_public_projection_excludes_private_material_and_raw_signed_ids():
    artifact = get_fixture()['timed_artifact']
    public = json.dumps(artifact['public_projection'], ensure_ascii=False, sort_keys=True)
    private = artifact['private_production_record']
    assert private['authoritative_private']['session_secret_hex'] not in public
    assert private['authoritative_private']['session_id'] not in public
    for d in private['decisions']:
        assert d['chosen_action_id'] not in public
    for key in ('pre_execution_identity','post_execution_identity','pre_state_identity','inner_decision_identity','legal_actions','payload','private_production_record','private_timed_transcript'):
        assert '"'+key+'"' not in public


@pytest.mark.parametrize('raw', ['{"schema":1,"schema":2}', '{"x":NaN}', '{"x":Infinity}'])
def test_strict_json_duplicate_and_nonfinite_rejected(raw):
    with pytest.raises(ValueError):
        replay._strict_json(raw)


def test_old_v1_v2_full_game_envelopes_fail_before_gameplay(monkeypatch):
    from scripts.sgs_engine import c8_timed_8p_full_game_production_replay_v1 as g3
    monkeypatch.setattr(g3, '_cold_workers', lambda *a: pytest.fail('legacy must fail before gameplay'))
    for version in (1, 2):
        with pytest.raises(ValueError):
            replay.TimedEightPlayerFullGameReplayV1.from_dict({'schema':f'sgs-c8-timed-8p-full-game-replay-v{version}', 'contract_version':version})
