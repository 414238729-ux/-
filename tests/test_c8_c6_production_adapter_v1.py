# -*- coding: utf-8 -*-
"""Targeted real-C6 evidence for provisional C8-E production integration."""

from __future__ import annotations

from copy import copy, deepcopy
from dataclasses import asdict, dataclass, replace
import hashlib
import json
import pickle

import pytest

from scripts.sgs_engine import c8_c6_production_adapter_v1 as prod
from scripts.sgs_engine import c8_strict_replay_v1 as replay
from scripts.sgs_engine import c8_timed_session_runtime_v1 as rt
from scripts.sgs_engine import c8_timeout_controller_integration_v1 as ctl
from scripts.sgs_engine import c8_virtual_time_contract_v1 as c8
from scripts.sgs_engine.actions import ActionType
from scripts.sgs_engine.mode_identity import (
    FORMAL_NO_SKILL_IDENTITY_8P_MODE,
    FormalEightPlayerIdentitySession,
)
from scripts.sgs_engine.production_batch import (
    BatchActionIdController,
    ProductionBatchError,
    ProductionPhase,
)


def _step1362_stack(dodges=2, bagua=True, other_hand=False, judgment_color=None,
                    response_phase=ProductionPhase.SLASH_RESPONSE) -> _Stack:
    """Fresh detached step0 fixture; never resumes the failed natural session.

    Only this initial fixture edits card zones/order. All later transitions
    use fresh C6 signed IDs through B/E, with no runtime/pending mutation.
    """
    from scripts.sgs_engine.model import DRAW_PILE, ZoneRef
    from scripts.sgs_engine import c8_timed_8p_full_game_runner_v1 as runner
    wanjian = response_phase is ProductionPhase.WANJIAN_RESPONSE
    seed = 1 if wanjian else 0
    session = prod.create_canonical_c6_no_skill_session_v1(seed)
    assert session.step_count == 0 and session.formal_result_eligible
    initial_state = session.state  # Keep the original object alive, as in W592.
    actor = session.current_player_id
    order = session.numbered_player_order
    target = order[(order.index(actor) + 1) % len(order)]
    for zone in (ZoneRef.hand(target), ZoneRef.equipment(target, "armor"),
                 ZoneRef.equipment(actor, "weapon")):
        for card_id in session.state.card_ids_in(zone):
            session._state = session.state.move_card(card_id, DRAW_PILE)
    used = set()
    def put(key, zone):
        record = next(r for r in session.formal_registry.records
                      if r.card_key == key and r.instance_id not in used)
        used.add(record.instance_id)
        session._state = session.state.move_card(record.instance_id, zone)
        return record.instance_id
    slash = put("sgs_trick_wanjianqifa" if wanjian else "sgs_basic_sha", ZoneRef.hand(actor))
    for _ in range(dodges):
        put("sgs_basic_shan", ZoneRef.hand(target))
    if other_hand:
        put("sgs_basic_tao", ZoneRef.hand(target))
    if bagua:
        put("sgs_armor_baguazhen", ZoneRef.equipment(target, "armor"))
    if judgment_color is not None:
        deck = list(session.state.card_ids_in(DRAW_PILE))
        judge = next(cid for cid in deck if session.state.cards_by_id[cid].color == judgment_color)
        deck.remove(judge)
        deck.insert(2, judge)  # The real preparation path draws two cards first.
        session._state = session.state.reorder_zone(DRAW_PILE, deck)
    session.state.assert_card_conservation()
    assert session.state is not initial_state
    assert session.step_count == 0 and not session.formal_result_eligible
    bundle = runner._assemble_bundle_v3(session, seed=seed, run_label="response-targeted")
    use_operation = "use_wanjian" if wanjian else "use_slash"
    for operation in ("proceed_prepare", "proceed_judgment", "proceed_draw", use_operation):
        context, ref, opened = bundle.orchestrator.observe_and_open_or_refresh_v1()
        assert opened
        action, = [a for a in session.legal_actions() if a.payload.get("operation") == operation
                   and (operation != use_operation or (a.card_instance_id == slash and (wanjian or a.target_ids == (target,))))]
        before = session.step_count
        bundle.runtime.forward_on_time_signed_action_id(ref, signed_action_id=action.action_id)
        assert session.step_count == before + 1
        bundle.orchestrator.close_completed_on_time_context_v1(ref, context)
    # Resolve real nullification windows through signed B/E submissions only.
    for _ in range(32):
        if session.phase is response_phase:
            break
        assert wanjian and session.phase is ProductionPhase.TRICK_RESPONSE
        context, ref, opened = bundle.orchestrator.observe_and_open_or_refresh_v1()
        action, = [a for a in session.legal_actions() if a.payload.get("operation") == "pass_trick_response"]
        bundle.runtime.forward_on_time_signed_action_id(ref, signed_action_id=action.action_id)
        bundle.orchestrator.close_completed_on_time_context_v1(ref, context)
    assert session.phase is response_phase
    context, ref, opened = bundle.orchestrator.observe_and_open_or_refresh_v1()
    assert opened
    assert [a.payload["operation"] for a in session.legal_actions()] == (
        ["play_jink_for_wanjian" if wanjian else "play_dodge"] * dodges
        + (["activate_bagua"] if bagua else [])
        + ["pass_wanjian_jink" if wanjian else "pass_slash_response"]
    )
    return _Stack(session, bundle.adapter, bundle.runtime, bundle.orchestrator,
                  bundle.controller, bundle.controller_instance_identity, context, ref)


def _step1362_targeted_result(dodges, bagua, other_hand, monkeypatch,
                             response_phase=ProductionPhase.SLASH_RESPONSE):
    from scripts.sgs_engine import c8_timed_8p_full_game_contract_v1 as contract
    from scripts.sgs_engine import c8_timed_8p_full_game_runner_v1 as runner
    stack = _step1362_stack(dodges, bagua, other_hand, "红" if bagua else None, response_phase)
    wanjian = response_phase is ProductionPhase.WANJIAN_RESPONSE
    decline = "pass_wanjian_jink" if wanjian else "pass_slash_response"
    seed, window = (1, 912) if wanjian else (0, 1328)
    local_prefix = stack.session.step_count
    calls, resolutions = [], []
    def wrap(cls, name, label):
        original = getattr(cls, name)
        def observed(self, *args, **kwargs):
            calls.append(label)
            return original(self, *args, **kwargs)
        monkeypatch.setattr(cls, name, observed)
    wrap(rt.C8TimedSessionRuntimeV1, "forward_timeout_due_signed_action_id_v1", "B_TIMEOUT_FORWARD")
    wrap(prod.C8C6ProductionAdapterV1, "apply_signed_action_id_v1", "E_APPLY_SIGNED_ACTION_ID")
    wrap(FormalEightPlayerIdentitySession, "step", "C6_STEP")
    original_resolve = c8.resolve_timeout_v1
    def observed_resolve(*args, **kwargs):
        result = original_resolve(*args, **kwargs)
        resolutions.append(result)
        return result
    monkeypatch.setattr(c8, "resolve_timeout_v1", observed_resolve)
    real = stack.session.legal_actions()
    active = stack.runtime.state.virtual_time_state.window_stack.active_window
    value, action_ids = runner.public_driver_input_v1(session=stack.session, context_value=stack.context,
        formal_seed=seed, global_window_index=window, deadline_at=active.deadline_at)
    expected = (["mandatory_action"] * dodges + (["public_choice"] if bagua else []) + ["pass_response"])
    families = [prod._family_for_action(a, stack.context).value for a in real]
    assert families == expected and families.count("pass_response") == 1
    assert [a.public_action_family for a in value.public_actions] == (
        ["RESPOND"] * dodges + (["ACTIVATE"] if bagua else []) + ["PASS"])
    assert type(value) is contract.FormalDriverInputV1
    assert runner._driver_input_from_dict(value.identity_material()) == value
    decision = runner.driver_decision_dict_v1(value)
    assert decision["actual_timeout"] is True
    before, event_start = stack.session.step_count, len(stack.session.events)
    result = stack.controller.resolve_timeout_v1(stack.ref, timeout_due_commitment=_make_due(stack))
    assert result.result_kind == "RESOLVED_SINGLE" and len(result.selected_actions) == 1
    selected = result.selected_actions[0]
    assert selected.public_ordinal == len(real) - 1
    assert selected.signed_action_id == action_ids[selected.public_ordinal]
    assert real[selected.public_ordinal].payload["operation"] == decline
    assert stack.session.step_count == before + 1
    assert len(result.receipt_identities) == 1
    assert calls == ["B_TIMEOUT_FORWARD", "E_APPLY_SIGNED_ACTION_ID", "C6_STEP"]
    assert resolutions and all(r.reason.value == "EXPLICIT_FALLBACK" for r in resolutions)
    assert all(r.resolved_public_ordinal == selected.public_ordinal for r in resolutions)
    next_context = stack.adapter.observe_production_decision_context_v1()
    calls.append("POST_OBSERVE")
    assert next_context.context_identity != stack.context.context_identity
    stack.orchestrator.confirm_timeout_context_closed_v1(stack.ref, stack.context)
    calls.append("CONFIRM_TIMEOUT_CLOSED")
    assert stack.runtime.active_window_ref() is None
    public_set = stack.adapter.public_legal_set_evidence_v1()[-1].public_legal_set
    assert tuple(a.action_id for a in public_set.actions) == action_ids
    assert [a.action_family.value for a in public_set.actions] == families
    events = stack.session.events[event_start:]
    assert not any(e.event_type.value.startswith("armor_judgment") for e in events)
    assert not any(e.payload.get("purpose") == "bagua_virtual_dodge" for e in events)
    assert not stack.session.formal_result_eligible
    accepted = stack.session.step_count
    with pytest.raises((prod.C8C6ProductionAdapterError, rt.C8TimedSessionRuntimeError)):
        stack.runtime.forward_on_time_signed_action_id(stack.ref, signed_action_id=selected.signed_action_id)
    calls.append("STALE_REJECT")
    assert stack.session.step_count == accepted
    return {"scope": "DETACHED_C6_PRODUCTION_INTEGRATION_TEST_ONLY", "test_only": True,
        "natural": False, "full_game": False, "promotion_authority": False, "resume_capable": False,
        "formal_result_eligible": False, "shape_equivalent_to_step1362": dodges == 2 and bagua,
        "local_accepted_prefix": local_prefix, "driver_window_index_for_timeout_schedule": window,
        "context": stack.context.to_public_dict_v1(), "G2_typed_input_class": type(value).__name__,
        "G1_input": value.identity_material(), "G1_decision": decision,
        "E_families": families, "E_legal_set": asdict(public_set),
        "A_resolutions": [r.to_dict() for r in resolutions], "C_result": asdict(result),
        "fallback_count": 1, "selected_operation": decline,
        "selected_public_ordinal": selected.public_ordinal, "selected_action_count": 1,
        "accepted_before": before, "accepted_after": accepted, "window_closed": True,
        "post_context": next_context.to_public_dict_v1(), "call_trace": calls,
        "bagua_judgment_triggered_by_timeout": False, "stale_reject": True}


@pytest.mark.parametrize("dodges,bagua,other_hand", [
    (1, True, False), (2, True, False), (0, True, True),
    (1, False, False), (0, True, False), (0, False, False),
])
def test_step1362_six_real_timeout_shapes(dodges, bagua, other_hand, monkeypatch):
    _step1362_targeted_result(dodges, bagua, other_hand, monkeypatch)


@pytest.mark.parametrize("families", [
    (c8.PublicActionFamilyV1.PASS_RESPONSE, c8.PublicActionFamilyV1.PASS_RESPONSE),
    (c8.PublicActionFamilyV1.PUBLIC_CHOICE,),
    (c8.PublicActionFamilyV1.MANDATORY_ACTION, c8.PublicActionFamilyV1.MANDATORY_ACTION),
])
def test_step1362_detached_typed_policy_ambiguity_never_commits(families, monkeypatch):
    # These sets cannot occur in canonical C6 slash enumeration. No C6 IDs or
    # receipts are forged: this is the existing independent typed C harness.
    from test_c8_timeout_controller_integration_v1 import _controller_harness
    controller, adapter, runtime, inner, _, ref, due = _controller_harness(
        label="step1362-policy-negative-" + "-".join(v.value for v in families),
        kind=c8.TimedWindowKindV1.OPTIONAL_RESPONSE,
        families_by_step=(families,))
    seen = []
    original = c8.resolve_timeout_v1
    def observe(*args, **kwargs):
        result = original(*args, **kwargs)
        seen.append(result)
        return result
    monkeypatch.setattr(c8, "resolve_timeout_v1", observe)
    result = controller.resolve_timeout_v1(ref, timeout_due_commitment=due)
    assert result.result_kind == "TIMEOUT_UNRESOLVED"
    assert result.selected_actions == () and result.receipt_identities == ()
    assert seen and all(v.resolution_kind.value == "TIMEOUT_UNRESOLVED" for v in seen)
    assert all(v.resolved_public_ordinal is None for v in seen)
    assert inner.public_counter == 0 and adapter.issuances == []
    assert runtime.active_window_ref() == ref


@pytest.mark.parametrize("operation,action_type", [
    ("unknown_pass", ActionType.PASS), ("", ActionType.PASS), (None, ActionType.PASS),
    ("activate_bagua", ActionType.RESPOND), ("pass_slash_response", ActionType.USE_CARD),
    ("play_dodge", ActionType.PASS),
])
def test_step1362_unknown_or_wrong_type_fails_closed(operation, action_type):
    stack = _step1362_stack()
    original = stack.session.legal_actions()[2]
    detached = replace(original, action_type=action_type, payload={"operation": operation})
    with pytest.raises(prod.C8C6ProductionAdapterError, match="SEMANTICS_UNRESOLVED"):
        prod._family_for_action(detached, stack.context)
    assert stack.session.step_count == 4 and stack.runtime.active_window_ref() == stack.ref


@pytest.mark.parametrize("operation,color", [("play_dodge", None), ("activate_bagua", "红"), ("activate_bagua", "黑")])
def test_step1362_on_time_jink_and_bagua_use_semantics(operation, color):
    stack = _step1362_stack(judgment_color=color)
    action = next(a for a in stack.session.legal_actions() if a.payload["operation"] == operation)
    start = len(stack.session.events)
    stack.runtime.forward_on_time_signed_action_id(stack.ref, signed_action_id=action.action_id)
    assert stack.session.step_count == 5
    next_context = stack.adapter.observe_production_decision_context_v1()
    stack.orchestrator.close_completed_on_time_context_v1(stack.ref, stack.context)
    assert stack.runtime.active_window_ref() is None
    events = stack.session.events[start:]
    jinks = [e for e in events if e.card_key == "sgs_basic_shan" and e.event_type.value in {"card_used", "card_played"}]
    judgments = [e for e in events if e.event_type.value == "armor_judgment_result"]
    if operation == "play_dodge":
        assert len(jinks) == 1 and jinks[0].event_type.value == "card_used"
        assert jinks[0].card_instance_id == action.card_instance_id and judgments == []
    else:
        assert len(judgments) == 1 and judgments[0].payload["judgment_color"] == color
        if color == "红":
            assert len(jinks) == 1 and jinks[0].event_type.value == "card_used"
            assert jinks[0].card_instance_id is None and jinks[0].payload["physical_or_virtual"] == "virtual"
            assert next_context.phase is not ProductionPhase.SLASH_RESPONSE
        else:
            assert jinks == [] and next_context.phase is ProductionPhase.SLASH_RESPONSE
            assert [a.payload["operation"] for a in stack.session.legal_actions()] == ["play_dodge", "play_dodge", "pass_slash_response"]
            fresh, ref, opened = stack.orchestrator.observe_and_open_or_refresh_v1()
            assert opened and fresh.context_identity == next_context.context_identity
            response = next(a for a in stack.session.legal_actions() if a.payload["operation"] == "play_dodge")
            stack.runtime.forward_on_time_signed_action_id(ref, signed_action_id=response.action_id)
            stack.orchestrator.close_completed_on_time_context_v1(ref, fresh)
            assert stack.session.step_count == 6 and stack.runtime.active_window_ref() is None


def test_step1362_uncommitted_context_cannot_close():
    stack = _step1362_stack()
    with pytest.raises(prod.C8C6ProductionAdapterError, match="尚未完成"):
        stack.orchestrator.close_completed_on_time_context_v1(stack.ref, stack.context)
    with pytest.raises(prod.C8C6ProductionAdapterError, match="未关闭"):
        stack.orchestrator.confirm_timeout_context_closed_v1(stack.ref, stack.context)
    assert stack.session.step_count == 4 and stack.runtime.active_window_ref() == stack.ref


def _w592_stack(kind: str) -> _Stack:
    """Explicit test-only step0 card setup; every subsequent step uses B/E/C6.

    This exercises the confirmed W592 seam, without replaying its natural prefix.
    No pending runtime, action signature, receipt, step counter or RNG is edited.
    """
    from scripts.sgs_engine.model import ZoneRef
    from scripts.sgs_engine import c8_timed_8p_full_game_runner_v1 as runner
    session = prod.create_canonical_c6_no_skill_session_v1(0)
    assert session.step_count == 0 and session.formal_result_eligible is True
    initial_state = session.state  # Retain the original immutable fixture object.
    actor = session.current_player_id
    order = session.numbered_player_order
    target = order[(order.index(actor) + 1) % len(order)]
    weapon = {"guanshifu_force_hit": "sgs_weapon_guanshifu",
              "qinglong_continue": "sgs_weapon_qinglongyanyuedao",
              "hanbing_prevent": "sgs_weapon_hanbingjian"}[kind]
    used: set[str] = set()
    def put(key, zone):
        record = next(r for r in session.formal_registry.records if r.card_key == key and r.instance_id not in used)
        used.add(record.instance_id)
        session._state = session.state.move_card(record.instance_id, zone)
        return record.instance_id
    put(weapon, ZoneRef.equipment(actor, "weapon"))
    slash = put("sgs_basic_sha", ZoneRef.hand(actor))
    put("sgs_basic_sha", ZoneRef.hand(actor))
    dodge = put("sgs_basic_shan", ZoneRef.hand(target))
    session.state.assert_card_conservation()
    assert session.state is not initial_state
    assert session.step_count == 0 and session.formal_result_eligible is False
    bundle = runner._assemble_bundle_v3(session, seed=0, run_label="w592-targeted")
    for operation in ("proceed_prepare", "proceed_judgment", "proceed_draw", "use_slash",
                      "pass_slash_response" if kind == "hanbing_prevent" else "play_dodge"):
        context, ref, opened = bundle.orchestrator.observe_and_open_or_refresh_v1()
        assert opened
        actions = [a for a in session.legal_actions() if a.payload.get("operation") == operation
                   and (operation != "use_slash" or (a.card_instance_id == slash and a.target_ids == (target,)))
                   and (operation != "play_dodge" or a.card_instance_id == dodge)]
        assert len(actions) == 1, (operation, len(actions))
        before = session.step_count
        bundle.runtime.forward_on_time_signed_action_id(ref, signed_action_id=actions[0].action_id)
        assert session.step_count == before + 1
        bundle.orchestrator.close_completed_on_time_context_v1(ref, context)
    assert session.phase is ProductionPhase.WEAPON_SLASH_CHOICE
    assert session._runtime.pending_slash_choice.kind == kind
    context, ref, opened = bundle.orchestrator.observe_and_open_or_refresh_v1()
    assert opened
    return _Stack(session, bundle.adapter, bundle.runtime, bundle.orchestrator,
                  bundle.controller, bundle.controller_instance_identity, context, ref)


def _w592_targeted_result(kind: str, monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    from scripts.sgs_engine import c8_timed_8p_full_game_runner_v1 as runner
    stack = _w592_stack(kind)
    calls = []
    def wrap(cls, name, label):
        original = getattr(cls, name)
        def observed(self, *args, **kwargs):
            calls.append(label)
            return original(self, *args, **kwargs)
        monkeypatch.setattr(cls, name, observed)
    wrap(rt.C8TimedSessionRuntimeV1, "forward_timeout_due_signed_action_id_v1", "B_TIMEOUT_FORWARD")
    wrap(prod.C8C6ProductionAdapterV1, "apply_signed_action_id_v1", "E_APPLY_SIGNED_ACTION_ID")
    wrap(FormalEightPlayerIdentitySession, "step", "C6_STEP")
    real = stack.session.legal_actions()
    active = stack.runtime.state.virtual_time_state.window_stack.active_window
    value, action_ids = runner.public_driver_input_v1(session=stack.session, context_value=stack.context,
        formal_seed=0, global_window_index=592, deadline_at=active.deadline_at)
    e_families = tuple(prod._family_for_action(a, stack.context) for a in real)
    assert e_families.count(c8.PublicActionFamilyV1.DECLINE_OPTIONAL) == 1
    assert tuple(o.public_action_family for o in value.public_actions).count("DECLINE") == 1
    for action, e_family, option in zip(real, e_families, value.public_actions):
        decline = action.payload["operation"] == "pass_weapon_choice"
        assert (e_family is c8.PublicActionFamilyV1.DECLINE_OPTIONAL) == decline
        assert (option.public_action_family == "DECLINE") == decline
    decision = runner.driver_decision_dict_v1(value)
    assert decision["actual_timeout"] is True
    before = stack.session.step_count
    result = stack.controller.resolve_timeout_v1(stack.ref, timeout_due_commitment=_make_due(stack))
    assert result.result_kind == "RESOLVED_SINGLE" and len(result.selected_actions) == 1
    selected = result.selected_actions[0]
    ordinal = action_ids.index(selected.signed_action_id)
    assert real[ordinal].payload["operation"] == "pass_weapon_choice"
    assert stack.session.step_count == before + 1
    assert calls == ["B_TIMEOUT_FORWARD", "E_APPLY_SIGNED_ACTION_ID", "C6_STEP"]
    assert stack.runtime.active_window_ref() is None
    stack.orchestrator.confirm_timeout_context_closed_v1(stack.ref, stack.context)
    public_set = stack.adapter.public_legal_set_evidence_v1()[-1].public_legal_set
    assert tuple(a.action_id for a in public_set.actions) == action_ids
    assert tuple(a.action_family for a in public_set.actions) == e_families
    assert stack.session.formal_result_eligible is False
    return {"scope": "W592_SEMANTIC_TARGETED_TEST_ONLY_NOT_NATURAL_PREFIX_REPLAY",
        "test_only": True, "natural": False, "full_game": False, "formal_result_eligible": False,
        "pending_kind": kind, "fallback_count": 1, "result": asdict(result),
        "selected_operation": "pass_weapon_choice", "accepted_before": before,
        "accepted_after": stack.session.step_count, "window_closed": True,
        "call_trace": calls, "G1_input": value.identity_material(), "G1_decision": decision,
        "E_legal_set": asdict(public_set)}


@pytest.mark.parametrize("kind", ["guanshifu_force_hit", "qinglong_continue", "hanbing_prevent"])
def test_w592_three_real_optional_timeouts_use_unique_decline(kind, monkeypatch):
    _w592_targeted_result(kind, monkeypatch)


@pytest.mark.parametrize("fallback_count", [0, 2])
def test_w592_ambiguous_or_absent_decline_is_unresolved(fallback_count, monkeypatch):
    # Fault injection tests A/C ambiguity, never a positive production witness.
    stack = _w592_stack("guanshifu_force_hit")
    family = c8.PublicActionFamilyV1.DECLINE_OPTIONAL if fallback_count else c8.PublicActionFamilyV1.PUBLIC_CHOICE
    monkeypatch.setattr(prod, "_family_for_action", lambda *args: family)
    before = stack.session.step_count
    result = stack.controller.resolve_timeout_v1(stack.ref, timeout_due_commitment=_make_due(stack))
    assert result.result_kind == "TIMEOUT_UNRESOLVED" and result.selected_actions == ()
    assert stack.session.step_count == before
    assert stack.runtime.active_window_ref() is not None
    evidence = stack.adapter.public_legal_set_evidence_v1()[-1].public_legal_set
    assert sum(a.action_family is c8.PublicActionFamilyV1.DECLINE_OPTIONAL for a in evidence.actions) == fallback_count


@pytest.mark.parametrize("operation,wrong", [("weapon_force_hit", "decline_optional"), ("pass_weapon_choice", "public_choice")])
def test_w592_opposite_optional_semantics_rejected(operation, wrong):
    stack = _w592_stack("guanshifu_force_hit")
    action, = [a for a in stack.session.legal_actions() if a.payload["operation"] == operation]
    with pytest.raises(prod.C8C6ProductionAdapterError, match="SEMANTIC_REJECT"):
        prod.verify_optional_public_action_family_v1(action, stack.context, c8.PublicActionFamilyV1(wrong))


@pytest.mark.parametrize("operation", ["unknown_optional", "", None])
def test_w592_unknown_optional_operation_fails_closed(operation):
    stack = _w592_stack("guanshifu_force_hit")
    original = stack.session.legal_actions()[0]
    detached = replace(original, payload={**original.payload, "operation": operation})
    before = stack.session.step_count
    with pytest.raises(prod.C8C6ProductionAdapterError, match="SEMANTICS_UNRESOLVED"):
        prod._family_for_action(detached, stack.context)
    assert stack.session.step_count == before


def _id(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _end_play_action_id(session: FormalEightPlayerIdentitySession) -> str:
    matches = tuple(
        action
        for action in session.legal_actions()
        if action.action_type is ActionType.PASS
        and action.payload.get("operation") == "end_play_phase"
    )
    assert len(matches) == 1
    assert matches[0].action_id is not None
    return matches[0].action_id


@dataclass
class _Stack:
    session: FormalEightPlayerIdentitySession
    adapter: prod.C8C6ProductionAdapterV1
    runtime: rt.C8TimedSessionRuntimeV1
    orchestrator: prod.C8C6ProductionWindowOrchestratorV1
    controller: ctl.TimeoutResolverControllerIntegrationV1
    controller_identity: str
    context: prod.ProductionDecisionContextV1
    ref: rt.WindowAuthorityRefV1


def _stack(*, label: str, seed: int = 0) -> _Stack:
    session = prod.create_canonical_c6_no_skill_session_v1(seed)
    assert len(prod.advance_canonical_c6_to_first_play_v1(session)) == 3
    adapter = prod.C8C6ProductionAdapterV1(session)
    runtime = rt.C8TimedSessionRuntimeV1(
        inner_adapter=adapter,
        input_authenticator=adapter,
        instance_nonce_identity=_id(f"c8-e-instance:{label}"),
        input_source_id=f"c8-e-targeted-driver-{label}",
        driver_authority_identity=_id(f"c8-e-driver:{label}"),
    )
    controller_identity = _id(f"c8-e-controller:{label}")
    adapter.bind_runtime_v1(
        runtime, controller_identity=controller_identity
    )
    orchestrator = prod.C8C6ProductionWindowOrchestratorV1(adapter, runtime)
    context, ref, opened = orchestrator.observe_and_open_or_refresh_v1()
    assert opened is True
    controller = ctl.TimeoutResolverControllerIntegrationV1(
        runtime,
        adapter,
        controller_instance_identity=controller_identity,
    )
    return _Stack(
        session=session,
        adapter=adapter,
        runtime=runtime,
        orchestrator=orchestrator,
        controller=controller,
        controller_identity=controller_identity,
        context=context,
        ref=ref,
    )


def _make_due(stack: _Stack) -> rt.TimeoutDueCommitmentV1:
    active = stack.runtime.state.virtual_time_state.window_stack.active_window
    assert active is not None
    advance = stack.adapter.issue_virtual_time_advance_v1(
        requested_tick=active.deadline_at
    )
    before = stack.runtime.state.input_chain_tip
    result = stack.runtime.ingest_virtual_time_input(
        advance,
        expected_previous_input_chain_tip=before,
        duration_profile_identity=c8.ENGINEERING_TEST_PROFILE_V1.profile_identity,
    )
    assert result.derived_deadline is not None
    commitment = stack.runtime.current_timeout_due_commitment_v1(stack.ref)
    assert type(commitment) is rt.TimeoutDueCommitmentV1
    return commitment


def test_production_authority_discovery_reaches_exact_canonical_c6() -> None:
    session = prod.create_canonical_c6_no_skill_session_v1(7)
    adapter = prod.C8C6ProductionAdapterV1(session)
    assert type(session) is FormalEightPlayerIdentitySession
    assert not hasattr(adapter, "production_session")
    assert adapter.production_session_finished_v1() is False
    assert session.mode_id == FORMAL_NO_SKILL_IDENTITY_8P_MODE
    assert session.analysis_only is False
    assert session.skill_runtime is None
    assert session.phase is ProductionPhase.PREPARE
    first = session.legal_actions()
    assert len(first) == 1
    assert first[0].action_id is not None
    assert first[0].action_id.startswith("act_")

    signed = prod.advance_canonical_c6_to_first_play_v1(session)

    assert len(signed) == 3
    assert session.phase is ProductionPhase.PLAY
    assert session.step_count == 3
    assert session.formal_result_eligible is True


def test_public_transaction_capability_is_opaque_one_shot_and_exact_restore() -> None:
    session = prod.create_canonical_c6_no_skill_session_v1(0)
    prod.advance_canonical_c6_to_first_play_v1(session)
    before_hash = session.execution_hash
    before_phase = session.phase
    before_step = session.step_count
    before_rng = session.rng_calls
    before_events = session.events
    token = session.capture_authoritative_transaction_v1()
    identity = session.authoritative_transaction_token_identity_v1(token)

    assert len(identity) == 64
    assert "snapshot" not in repr(token).lower()
    assert not hasattr(token, "__dict__")
    with pytest.raises(TypeError):
        copy(token)
    with pytest.raises(TypeError):
        deepcopy(token)
    with pytest.raises(TypeError):
        pickle.dumps(token)

    session.step(BatchActionIdController(_end_play_action_id(session)))
    assert session.execution_hash != before_hash
    session.restore_authoritative_transaction_v1(token)

    assert session.execution_hash == before_hash
    assert session.phase is before_phase
    assert session.step_count == before_step
    assert session.rng_calls == before_rng
    assert session.events == before_events
    assert session.formal_result_eligible is True
    with pytest.raises(ProductionBatchError):
        session.authoritative_transaction_token_identity_v1(token)
    with pytest.raises(ProductionBatchError):
        session.restore_authoritative_transaction_v1(token)


def test_transaction_commit_and_sibling_session_restore_fail_closed() -> None:
    first = prod.create_canonical_c6_no_skill_session_v1(1)
    second = prod.create_canonical_c6_no_skill_session_v1(1)
    token = first.capture_authoritative_transaction_v1()
    first_hash = first.execution_hash
    second_hash = second.execution_hash

    with pytest.raises(ProductionBatchError):
        second.restore_authoritative_transaction_v1(token)
    assert first.authoritative_transaction_token_identity_v1(token)
    first.restore_authoritative_transaction_v1(token)
    assert first.execution_hash == first_hash
    assert second.execution_hash == second_hash

    committed = first.capture_authoritative_transaction_v1()
    first.commit_authoritative_transaction_v1(committed)
    with pytest.raises(ProductionBatchError):
        first.restore_authoritative_transaction_v1(committed)


def test_same_production_context_refresh_preserves_window_and_deadline() -> None:
    stack = _stack(label="same-context-refresh")
    active_before = stack.runtime.state.virtual_time_state.window_stack.active_window
    assert active_before is not None

    context, ref, opened = stack.orchestrator.observe_and_open_or_refresh_v1()
    active_after = stack.runtime.state.virtual_time_state.window_stack.active_window

    assert opened is False
    assert context == stack.context
    assert ref == stack.ref
    assert active_after == active_before
    assert active_after.deadline_at == active_before.deadline_at


def test_real_c6_timeout_closed_loop_uses_typed_receipt_and_normal_step(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stack = _stack(label="real-closed-loop", seed=0)
    real_actions = stack.session.legal_actions()
    real_order = tuple(action.action_id for action in real_actions)
    end_action_id = _end_play_action_id(stack.session)
    pre_execution_hash = stack.session.execution_hash
    pre_public = stack.adapter.public_state_identity_v1()
    pre_authoritative = stack.adapter.authoritative_state_identity_v1()
    receipts: list[rt.TimeoutActionExecutionReceiptV1] = []
    original_forward = rt.C8TimedSessionRuntimeV1.forward_timeout_due_signed_action_id_v1

    def capture_receipt(
        runtime_self: rt.C8TimedSessionRuntimeV1,
        *args: object,
        **kwargs: object,
    ) -> rt.TimeoutActionExecutionReceiptV1:
        receipt = original_forward(runtime_self, *args, **kwargs)  # type: ignore[arg-type]
        receipts.append(receipt)
        return receipt

    monkeypatch.setattr(
        rt.C8TimedSessionRuntimeV1,
        "forward_timeout_due_signed_action_id_v1",
        capture_receipt,
    )
    result = stack.controller.resolve_timeout_v1(
        stack.ref, timeout_due_commitment=_make_due(stack)
    )

    assert result.result_kind == ctl.ControllerResultKindV1.RESOLVED_SINGLE.value
    assert result.reason == "TIMEOUT_RESOLUTION_COMMITTED"
    assert len(receipts) == 1
    receipt = receipts[0]
    assert type(receipt) is rt.TimeoutActionExecutionReceiptV1
    assert receipt.accepted is True and receipt.executed is True
    assert receipt.pre_inner_public_state_identity == pre_public
    assert receipt.pre_inner_authoritative_state_identity == pre_authoritative
    assert receipt.post_inner_public_state_identity == stack.adapter.public_state_identity_v1()
    assert receipt.post_inner_authoritative_state_identity == (
        stack.adapter.authoritative_state_identity_v1()
    )
    selected = result.selected_actions[0]
    assert selected.public_action_reference == end_action_id
    assert selected.signed_action_id == end_action_id
    assert selected.receipt_identity == receipt.receipt_identity
    assert stack.session.execution_hash != pre_execution_hash
    assert stack.session.step_count == 4
    assert stack.runtime.active_window_ref() is None
    assert stack.session.formal_result_eligible is True

    snapshots = stack.adapter.public_legal_set_evidence_v1()
    assert len(snapshots) == 1
    public_set = snapshots[0].public_legal_set
    assert tuple(item.action_id for item in public_set.actions) == real_order
    assert tuple(item.public_ordinal for item in public_set.actions) == tuple(
        range(len(real_order))
    )
    assert public_set.actions[real_order.index(end_action_id)].action_family is (
        c8.PublicActionFamilyV1.END_PLAY_PHASE
    )
    stack.orchestrator.confirm_timeout_context_closed_v1(
        stack.ref, stack.context
    )


def test_public_projection_strips_private_payload_without_resorting() -> None:
    stack = _stack(label="public-projection")
    real_actions = stack.session.legal_actions()
    real_ids = tuple(action.action_id for action in real_actions)
    result = stack.controller.resolve_timeout_v1(
        stack.ref, timeout_due_commitment=_make_due(stack)
    )
    assert result.result_kind == ctl.ControllerResultKindV1.RESOLVED_SINGLE.value
    snapshot = stack.adapter.public_legal_set_evidence_v1()[0]
    public = snapshot.public_legal_set.to_dict()
    encoded = json.dumps(public, ensure_ascii=False, sort_keys=True)

    assert tuple(item["action_id"] for item in public["actions"]) == real_ids
    for forbidden in (
        "card_instance_id",
        "virtual_card",
        "target_ids",
        "payload",
        "handle",
        "card_key",
        "card_name",
    ):
        assert forbidden not in encoded
    private_instance_ids = tuple(
        action.card_instance_id
        for action in real_actions
        if action.card_instance_id is not None
    )
    assert all(instance_id not in encoded for instance_id in private_instance_ids)


def test_stale_context_and_old_action_id_fail_closed_then_cleanup() -> None:
    stack = _stack(label="stale-context")
    old_context = stack.context
    old_ids = tuple(action.action_id for action in stack.session.legal_actions())
    end_id = _end_play_action_id(stack.session)
    pre_outer = stack.runtime.state

    stack.runtime.forward_on_time_signed_action_id(
        stack.ref, signed_action_id=end_id
    )

    assert stack.runtime.state != pre_outer
    assert stack.adapter.observe_production_decision_context_v1() != old_context
    with pytest.raises(prod.C8C6ProductionAdapterError):
        stack.adapter.bind_window_authority_v1(stack.ref, old_context)
    post_step_hash = stack.session.execution_hash
    with pytest.raises(prod.C8C6ProductionAdapterError):
        stack.adapter.apply_signed_action_id_v1(old_ids[0])
    assert stack.session.execution_hash == post_step_hash
    closed = stack.orchestrator.close_completed_on_time_context_v1(
        stack.ref, old_context
    )
    assert closed.status is c8.TimedWindowStatusV1.CLOSED_BY_ACTION
    assert stack.runtime.active_window_ref() is None


def test_wrong_actor_context_cross_session_and_forged_runtime_binding_rejected() -> None:
    first = _stack(label="cross-session-first", seed=2)
    second_session = prod.create_canonical_c6_no_skill_session_v1(2)
    prod.advance_canonical_c6_to_first_play_v1(second_session)
    second_adapter = prod.C8C6ProductionAdapterV1(second_session)

    with pytest.raises(prod.C8C6ProductionAdapterError):
        second_adapter.bind_runtime_v1(
            first.runtime,
            controller_identity=first.controller_identity,
        )
    with pytest.raises(prod.C8C6ProductionAdapterError):
        first.adapter.bind_window_authority_v1(first.ref, second_adapter.observe_production_decision_context_v1())


def test_tampered_order_and_private_payload_injection_are_rejected() -> None:
    stack = _stack(label="tampered-public-evidence")
    result = stack.controller.resolve_timeout_v1(
        stack.ref, timeout_due_commitment=_make_due(stack)
    )
    assert result.result_kind == ctl.ControllerResultKindV1.RESOLVED_SINGLE.value
    value = stack.adapter.public_legal_set_evidence_v1()[0].public_legal_set.to_dict()

    reordered = deepcopy(value)
    reordered["actions"] = list(reversed(reordered["actions"]))
    with pytest.raises(c8.C8VirtualTimeContractError):
        c8.PublicLegalSetProjectionV1.from_dict(reordered)

    injected = deepcopy(value)
    injected["actions"][0]["private_payload"] = {"card_instance_id": "forged"}
    with pytest.raises((ValueError, c8.C8VirtualTimeContractError)):
        c8.PublicLegalSetProjectionV1.from_dict(injected)


def test_preconsume_failure_aborts_reservation_and_duplicate_abort_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stack = _stack(label="preconsume-abort")
    pre_hash = stack.session.execution_hash

    monkeypatch.setattr(
        stack.adapter,
        "verify_and_consume_timeout_action_authorization_v1",
        lambda *args, **kwargs: False,
    )
    result = stack.controller.resolve_timeout_v1(
        stack.ref, timeout_due_commitment=_make_due(stack)
    )

    assert result.result_kind == ctl.ControllerResultKindV1.FAILED_ROLLED_BACK.value
    assert stack.session.execution_hash == pre_hash
    records = tuple(stack.adapter._reservations_by_evidence.values())
    assert len(records) == 1 and records[0].status == "REVOKED"
    with pytest.raises(prod.C8C6ProductionAdapterError):
        stack.adapter.abort_pending_issuance_v1(records[0].capability)


def test_consumed_reservation_replay_cross_session_and_abort_after_consume_rejected() -> None:
    first = _stack(label="consumed-reservation-first")
    resolved = first.controller.resolve_timeout_v1(
        first.ref, timeout_due_commitment=_make_due(first)
    )
    assert resolved.result_kind == ctl.ControllerResultKindV1.RESOLVED_SINGLE.value
    record = next(iter(first.adapter._reservations_by_evidence.values()))
    assert record.status == "CONSUMED"
    assert first.adapter.verify_and_consume_timeout_action_authorization_v1(
        record.signed_action_id,
        record.evidence_identity,
        _id("replay-final-binding"),
    ) is False
    with pytest.raises(prod.C8C6ProductionAdapterError):
        first.adapter.abort_pending_issuance_v1(record.capability)

    second = _stack(label="consumed-reservation-second")
    assert second.adapter.verify_and_consume_timeout_action_authorization_v1(
        record.signed_action_id,
        record.evidence_identity,
        _id("cross-session-binding"),
    ) is False


def test_production_step_reject_rolls_back_inner_and_outer() -> None:
    stack = _stack(label="production-step-reject")
    pre_hash = stack.session.execution_hash
    pre_outer = stack.runtime.state
    with pytest.raises(rt.C8TimedSessionRuntimeError):
        stack.runtime.forward_on_time_signed_action_id(
            stack.ref,
            signed_action_id="act_" + "0" * 64,
        )
    assert stack.session.execution_hash == pre_hash
    assert stack.runtime.state == pre_outer
    assert stack.session.formal_result_eligible is True


def test_production_step_exception_after_mutation_restores_exact_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stack = _stack(label="production-step-exception")
    action_id = _end_play_action_id(stack.session)
    pre_hash = stack.session.execution_hash
    pre_outer = stack.runtime.state
    original = FormalEightPlayerIdentitySession.step

    def apply_then_raise(
        session_self: FormalEightPlayerIdentitySession,
        controller: object = None,
    ) -> object:
        original(session_self, controller)
        raise RuntimeError("hostile exception after successful production step")

    monkeypatch.setattr(FormalEightPlayerIdentitySession, "step", apply_then_raise)
    with pytest.raises(rt.C8TimedSessionRuntimeError):
        stack.runtime.forward_on_time_signed_action_id(
            stack.ref, signed_action_id=action_id
        )

    assert stack.session.execution_hash == pre_hash
    assert stack.runtime.state == pre_outer
    assert stack.session.phase is ProductionPhase.PLAY
    assert stack.session.step_count == 3
    assert stack.session.formal_result_eligible is True


def test_post_binding_mismatch_rolls_back_whole_b_c_gameplay_transaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stack = _stack(label="post-binding-mismatch")
    pre_hash = stack.session.execution_hash
    original_session_identity = stack.adapter.session_binding_identity_v1

    def hostile_session_identity() -> str:
        real = original_session_identity()
        if stack.session.step_count > 3:
            return _id(f"forged-post-binding:{real}")
        return real

    monkeypatch.setattr(
        stack.adapter, "session_binding_identity_v1", hostile_session_identity
    )
    commitment = _make_due(stack)
    pre_outer = stack.runtime.state
    result = stack.controller.resolve_timeout_v1(
        stack.ref, timeout_due_commitment=commitment
    )

    assert result.result_kind == ctl.ControllerResultKindV1.FAILED_ROLLED_BACK.value
    assert stack.session.execution_hash == pre_hash
    assert stack.runtime.state == pre_outer
    assert stack.session.phase is ProductionPhase.PLAY
    assert stack.session.step_count == 3
    assert stack.session.formal_result_eligible is True
    record = next(iter(stack.adapter._reservations_by_evidence.values()))
    assert record.status == "CONSUMED"


def test_adapter_callback_c8_rollback_reentry_is_detected_by_b_guard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stack = _stack(label="callback-reentry")
    commitment = _make_due(stack)
    attacker_snapshot = stack.runtime.capture_transaction()
    pre_hash = stack.session.execution_hash
    original_fresh = stack.adapter.fresh_public_legal_actions_v1

    def reenter_then_fetch() -> ctl.AdapterPublicLegalActionsSnapshotV1:
        stack.runtime.rollback(attacker_snapshot)
        return original_fresh()

    monkeypatch.setattr(
        stack.adapter, "fresh_public_legal_actions_v1", reenter_then_fetch
    )
    result = stack.controller.resolve_timeout_v1(
        stack.ref, timeout_due_commitment=commitment
    )

    assert result.result_kind in {
        ctl.ControllerResultKindV1.FAILED_ROLLED_BACK.value,
        ctl.ControllerResultKindV1.FAILED_POISONED.value,
    }
    assert "FAIL_CLOSED" in result.reason or "ROLLBACK" in result.reason
    assert stack.session.execution_hash == pre_hash
    assert stack.session.step_count == 3


def test_missing_fresh_real_fallback_returns_timeout_unresolved_without_action(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stack = _stack(label="missing-real-fallback")
    real_ids = tuple(action.action_id for action in stack.session.legal_actions())
    pre_hash = stack.session.execution_hash
    monkeypatch.setattr(
        prod,
        "_family_for_action",
        lambda action, context: c8.PublicActionFamilyV1.MANDATORY_ACTION,
    )

    result = stack.controller.resolve_timeout_v1(
        stack.ref, timeout_due_commitment=_make_due(stack)
    )

    assert result.result_kind == ctl.ControllerResultKindV1.TIMEOUT_UNRESOLVED.value
    assert result.step_count == 1
    assert result.selected_actions == ()
    assert stack.session.execution_hash == pre_hash
    assert not stack.adapter.public_issuance_evidence_v1()
    snapshot = stack.adapter.public_legal_set_evidence_v1()[0]
    assert tuple(item.action_id for item in snapshot.public_legal_set.actions) == real_ids


def test_window_mapping_marks_c6_no_skill_limits_truthfully() -> None:
    mapping = prod.production_window_context_mapping_v1()
    assert mapping["play"] == {
        "window_kind": "PLAY",
        "applicability": "APPLICABLE",
    }
    assert mapping["slash_response"]["window_kind"] == "OPTIONAL_RESPONSE"
    assert mapping["dying_rescue"]["window_kind"] == "RESCUE_RESPONSE"
    assert mapping["zone_choice"]["applicability"] == (
        "PRIVATE_ORDINAL_TIMEOUT_UNRESOLVED"
    )
    assert mapping["mode_decision"]["applicability"] == (
        "NOT_APPLICABLE_IN_C6_NO_SKILL_8P"
    )
    assert mapping["character_skill_multi_step"]["applicability"] == (
        "NOT_APPLICABLE_IN_C6_NO_SKILL_8P"
    )


def test_e_public_evidence_is_c8_d_schema_compatible_without_semantic_revision() -> None:
    stack = _stack(label="d-schema-compatibility")
    result = stack.controller.resolve_timeout_v1(
        stack.ref, timeout_due_commitment=_make_due(stack)
    )
    assert result.result_kind == ctl.ControllerResultKindV1.RESOLVED_SINGLE.value
    snapshot = stack.adapter.public_legal_set_evidence_v1()[0]
    snapshot_dict = replay._adapter_snapshot_dict(snapshot)
    assert replay._parse_adapter_snapshot(snapshot_dict) == snapshot
    issuance_dict = stack.adapter.public_issuance_evidence_v1()[0]
    parsed = replay._parse_issuance(issuance_dict)
    assert parsed.signed_action_id == parsed.public_action_reference
    assert parsed.issuance_identity == issuance_dict["issuance_identity"]

# Response-window generalization: detached integration fixtures, never seed1 replay.
@pytest.mark.parametrize("dodges,bagua", [(1, True), (2, True), (0, True), (1, False), (0, False)])
def test_seed1_step943_wanjian_exact_timeout_remediation(dodges, bagua, monkeypatch):
    result = _step1362_targeted_result(dodges, bagua, False, monkeypatch, ProductionPhase.WANJIAN_RESPONSE)
    assert result["selected_operation"] == "pass_wanjian_jink"
    assert result["C_result"]["result_kind"] == "RESOLVED_SINGLE"
    assert result["fallback_count"] == 1 and result["window_closed"]
    assert result["accepted_after"] == result["accepted_before"] + 1
    if dodges == 1 and bagua:
        assert result["E_families"] == ["mandatory_action", "public_choice", "pass_response"]
        assert result["selected_public_ordinal"] == 2
    import os
    from pathlib import Path
    output = os.environ.get("C8_RESPONSE_TARGETED_OUTPUT")
    if output:
        result["shape_equivalent_to_step1362"] = False
        result["shape_equivalent_to_seed1_step943"] = dodges == 1 and bagua
        Path(output, f"wanjian-{dodges}-{bagua}.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")


@pytest.mark.parametrize("phase", [ProductionPhase.SLASH_RESPONSE, ProductionPhase.WANJIAN_RESPONSE])
@pytest.mark.parametrize("color", ["红", "黑"])
def test_response_bagua_virtual_jink_event_semantics_cannot_interchange(phase, color):
    stack = _step1362_stack(judgment_color=color, response_phase=phase)
    action, = [a for a in stack.session.legal_actions() if a.payload["operation"] == "activate_bagua"]
    before, start = stack.session.step_count, len(stack.session.events)
    stack.runtime.forward_on_time_signed_action_id(stack.ref, signed_action_id=action.action_id)
    next_context = stack.adapter.observe_production_decision_context_v1()
    stack.orchestrator.close_completed_on_time_context_v1(stack.ref, stack.context)
    assert stack.session.step_count == before + 1 and stack.runtime.active_window_ref() is None
    events = stack.session.events[start:]
    jinks = [e for e in events if e.card_key == "sgs_basic_shan" and e.event_type.value in {"card_used", "card_played"}]
    judgments = [e for e in events if e.event_type.value == "armor_judgment_result"]
    assert len(judgments) == 1 and judgments[0].payload["judgment_color"] == color
    if color == "红":
        assert len(jinks) == 1
        assert jinks[0].event_type.value == ("card_used" if phase is ProductionPhase.SLASH_RESPONSE else "card_played")
        assert jinks[0].card_instance_id is None and jinks[0].payload["physical_or_virtual"] == "virtual"
    else:
        assert not jinks and next_context.phase is phase
        assert all(a.payload["operation"] != "activate_bagua" for a in stack.session.legal_actions())
    assert not stack.session.formal_result_eligible


@pytest.mark.parametrize("phase", sorted(prod._RESPONSE_OPERATIONS_V1, key=lambda p: p.value))
def test_response_unknown_pass_and_unregistered_phase_fail_closed(phase):
    stack = _step1362_stack()
    kind, applicability = prod._window_mapping(phase)
    context = _detached_response_context(stack.context, phase=phase, window_kind=kind, applicability=applicability)
    action = replace(stack.session.legal_actions()[2], payload={"operation": "unknown_pass"})
    with pytest.raises(prod.C8C6ProductionAdapterError, match="SEMANTICS_UNRESOLVED"):
        prod._family_for_action(action, context)
    # A future response phase without a semantic registration must also close the gate.
    with pytest.raises(prod.C8C6ProductionAdapterError, match="SEMANTICS_UNRESOLVED"):
        prod._family_for_action(action, _detached_response_context(context, phase=ProductionPhase.PLAY))


@pytest.mark.parametrize("phase,operation,action_type,expected", [
    (ProductionPhase.TRICK_RESPONSE, "use_wuxie", ActionType.USE_CARD, "mandatory_action"),
    (ProductionPhase.JUDGMENT_WUXIE, "pass_judgment_wuxie", ActionType.PASS, "pass_response"),
    (ProductionPhase.DUEL_RESPONSE, "play_slash_for_duel", ActionType.PLAY_CARD, "mandatory_action"),
    (ProductionPhase.NANMAN_RESPONSE, "play_slash_for_nanman", ActionType.PLAY_CARD, "mandatory_action"),
    (ProductionPhase.FIRE_ATTACK_DISCARD, "discard_same_suit_for_fire_attack", ActionType.MOVE_CARD, "mandatory_action"),
    (ProductionPhase.DYING_RESCUE, "rescue_with_peach", ActionType.USE_CARD, "mandatory_action"),
    (ProductionPhase.DYING_RESCUE, "pass_rescue", ActionType.PASS, "pass_rescue"),
])
def test_response_adjacent_private_operation_projection(phase, operation, action_type, expected):
    stack = _step1362_stack()
    kind, applicability = prod._window_mapping(phase)
    context = _detached_response_context(stack.context, phase=phase, window_kind=kind, applicability=applicability)
    detached = replace(stack.session.legal_actions()[0], action_type=action_type, payload={"operation": operation})
    assert prod._family_for_action(detached, context).value == expected
    if phase not in (ProductionPhase.SLASH_RESPONSE, ProductionPhase.WANJIAN_RESPONSE):
        with pytest.raises(prod.C8C6ProductionAdapterError, match="SEMANTICS_UNRESOLVED"):
            prod._family_for_action(replace(detached, action_type=ActionType.PASS, payload={"operation": "activate_bagua"}), context)


def test_response_production_bagua_context_inventory_requires_registration():
    import ast, inspect, textwrap
    from scripts.sgs_engine.production_cards import ArmorCardAdapter
    tree = ast.parse(textwrap.dedent(inspect.getsource(ArmorCardAdapter._enumerate_bagua_activate)))
    actual = {n.comparators[0].value for n in ast.walk(tree) if isinstance(n, ast.Compare)
              and isinstance(n.left, ast.Attribute) and n.left.attr == "value"
              and isinstance(n.left.value, ast.Name) and n.left.value.id == "phase"
              and isinstance(n.comparators[0], ast.Constant)}
    registered = {p.value for p, operations in prod._RESPONSE_OPERATIONS_V1.items() if "activate_bagua" in operations}
    assert actual == registered == {"slash_response", "wanjian_response"}
    assert set(prod._RESPONSE_OPERATIONS_V1) == set(prod._OPTIONAL_RESPONSE_PHASES) | {ProductionPhase.DYING_RESCUE}


@pytest.mark.parametrize("ordinal,family", [(1, "pass_response"), (2, "public_choice"), (0, "pass_response"), (1, "mandatory_action"), (2, "mandatory_action"), (1, "PASS")])
def test_response_seed1_e_g2_spoof_rejected(ordinal, family, monkeypatch):
    from scripts.sgs_engine import c8_timed_8p_full_game_runner_v1 as runner
    stack = _step1362_stack(1, response_phase=ProductionPhase.WANJIAN_RESPONSE)
    before = stack.session.step_count
    target_id = stack.session.legal_actions()[ordinal].action_id
    original = prod._family_for_action
    supplied = family if family == "PASS" else c8.PublicActionFamilyV1(family)
    monkeypatch.setattr(prod, "_family_for_action", lambda a, c: supplied if a.action_id == target_id else original(a, c))
    with pytest.raises(prod.C8C6ProductionAdapterError, match="SEMANTIC_REJECT"):
        runner.public_driver_input_v1(session=stack.session, context_value=stack.context,
            formal_seed=1, global_window_index=912, deadline_at=100)
    assert stack.session.step_count == before and stack.runtime.active_window_ref() == stack.ref


@pytest.mark.parametrize("field", ["operation", "raw_operation", "private_payload", "payload", "card_instance_id"])
def test_response_seed1_g1_private_operation_leak_rejected(field):
    from scripts.sgs_engine import c8_timed_8p_full_game_runner_v1 as runner
    stack = _step1362_stack(1, response_phase=ProductionPhase.WANJIAN_RESPONSE)
    value, _ = runner.public_driver_input_v1(session=stack.session, context_value=stack.context,
        formal_seed=1, global_window_index=912, deadline_at=100)
    material = value.identity_material()
    assert [a["public_action_family"] for a in material["public_actions"]] == ["RESPOND", "ACTIVATE", "PASS"]
    assert not any(op in json.dumps(material) for op in ("activate_bagua", "play_jink_for_wanjian", "pass_wanjian_jink"))
    material["public_actions"][1][field] = "activate_bagua"
    with pytest.raises(ValueError):
        runner._driver_input_from_dict(material)


def _detached_response_context(context, **changes):
    # Pure classification probe, never registered with B/E and never executable.
    material = context.identity_material_v1()
    material.update({k: getattr(v, "value", v) for k, v in changes.items()})
    return replace(context, **changes, context_identity=prod._identity(material))


@pytest.mark.parametrize("operation,action_type", [("play_jink_for_wanjian", ActionType.PASS),
    ("activate_bagua", ActionType.RESPOND), ("pass_wanjian_jink", ActionType.USE_CARD),
    ("pass_slash_response", ActionType.PASS)])
def test_response_wanjian_wrong_type_or_cross_phase_rejected(operation, action_type):
    stack = _step1362_stack(1, response_phase=ProductionPhase.WANJIAN_RESPONSE)
    action = replace(stack.session.legal_actions()[1], action_type=action_type, payload={"operation": operation})
    with pytest.raises(prod.C8C6ProductionAdapterError, match="SEMANTICS_UNRESOLVED"):
        prod._family_for_action(action, stack.context)


def test_response_wanjian_physical_jink_is_played():
    stack = _step1362_stack(1, response_phase=ProductionPhase.WANJIAN_RESPONSE)
    action = stack.session.legal_actions()[0]
    before, start = stack.session.step_count, len(stack.session.events)
    stack.runtime.forward_on_time_signed_action_id(stack.ref, signed_action_id=action.action_id)
    stack.adapter.observe_production_decision_context_v1()
    stack.orchestrator.close_completed_on_time_context_v1(stack.ref, stack.context)
    jinks = [e for e in stack.session.events[start:] if e.card_key == "sgs_basic_shan" and e.event_type.value in {"card_used", "card_played"}]
    assert len(jinks) == 1 and jinks[0].event_type.value == "card_played"
    assert jinks[0].card_instance_id is not None and stack.session.step_count == before + 1
