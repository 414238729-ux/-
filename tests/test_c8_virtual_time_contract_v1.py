# -*- coding: utf-8 -*-
"""Dedicated cheap tests for C8-A; no gameplay/session integration is executed."""

from __future__ import annotations

import ast
from dataclasses import FrozenInstanceError
import inspect
import json
from pathlib import Path

import pytest

from scripts.sgs_engine import c8_virtual_time_contract_v1 as c8


DECISION_ID = "1" * 64
OBLIGATION_ID = "2" * 64
AUTH_ID = "3" * 64
PRIVATE_BINDING_ID = "4" * 64
PRIVATE_COMMITMENT = "5" * 64


def _state_with_window(
    kind: c8.TimedWindowKindV1 = c8.TimedWindowKindV1.PLAY,
) -> c8.VirtualTimeStateV1:
    state = c8.VirtualTimeStateV1.initial(c8.CLOCK_DOMAIN_V1)
    return c8.open_decision_window_v1(
        state,
        actor_id="p1",
        window_kind=kind,
        decision_identity=DECISION_ID,
        obligation_identity=OBLIGATION_ID,
        duration_profile=c8.ENGINEERING_TEST_PROFILE_V1,
        fallback_policy=c8.TIMEOUT_FALLBACK_POLICY_BY_KIND_V1[kind],
    )


def _legal_set(
    window: c8.TimedDecisionWindowV1,
    families: tuple[c8.PublicActionFamilyV1, ...],
    *,
    suffix: str = "a",
) -> c8.PublicLegalSetProjectionV1:
    actions = tuple(
        c8.PublicLegalActionCandidateV1.build(
            window_id=window.window_id,
            actor_id=window.actor_id,
            decision_identity=window.decision_identity,
            obligation_identity=window.obligation_identity,
            public_ordinal=index,
            action_id=f"issued-{suffix}-{index}",
            action_family=family,
        )
        for index, family in enumerate(families)
    )
    return c8.PublicLegalSetProjectionV1.build(
        window_id=window.window_id,
        actor_id=window.actor_id,
        decision_identity=window.decision_identity,
        obligation_identity=window.obligation_identity,
        actions=actions,
        ordering_contract_id=c8.PUBLIC_ORDERING_CONTRACT_ID,
    )


def _advance_input(
    state: c8.VirtualTimeStateV1,
    requested_tick: int,
    *,
    input_seq: int | None = None,
) -> c8.VirtualTimeAdvanceInputV1:
    active = state.window_stack.active_window
    assert active is not None
    return c8.VirtualTimeAdvanceInputV1.issue(
        input_seq=state.next_input_seq if input_seq is None else input_seq,
        source_id="test-authenticated-driver",
        domain_id=c8.CLOCK_DOMAIN_ID,
        window_id=active.window_id,
        requested_tick=requested_tick,
        authentication_evidence_identity=AUTH_ID,
    )


def _control_input(
    state: c8.VirtualTimeStateV1,
    input_kind: c8.VirtualTimeControlInputKindV1,
    *,
    input_seq: int | None = None,
) -> c8.VirtualTimeControlInputV1:
    active = state.window_stack.active_window
    assert active is not None
    return c8.VirtualTimeControlInputV1.issue(
        input_kind=input_kind,
        input_seq=state.next_input_seq if input_seq is None else input_seq,
        source_id="test-authenticated-driver",
        domain_id=c8.CLOCK_DOMAIN_ID,
        window_id=active.window_id,
        authentication_evidence_identity=AUTH_ID,
    )


def _deadline_result(
    kind: c8.TimedWindowKindV1 = c8.TimedWindowKindV1.PLAY,
) -> c8.VirtualTimeAdvanceResultV1:
    state = _state_with_window(kind)
    active = state.window_stack.active_window
    assert active is not None
    result = c8.advance_virtual_time_v1(
        state,
        _advance_input(state, active.deadline_at),
        c8.CLOCK_DOMAIN_V1,
    )
    assert result.derived_deadline is not None
    return result


def _json_round_trip(value: object) -> object:
    return json.loads(json.dumps(value, ensure_ascii=False, sort_keys=True))


def test_contract_ids_and_engineering_profile_are_explicitly_non_official() -> None:
    assert c8.C8_A_MILESTONE == "C8-A_VIRTUAL_TIME_CONTRACT_FREEZE_V1"
    assert c8.C8_SELECTED_MODE_ID == "C8_TIMED_8P_DETERMINISTIC_VIRTUAL_TIME_V1"
    assert c8.C8_BASE_MODE_ID == "CANONICAL_C6_STANDARD_NO_SKILL_8P"
    assert c8.CLOCK_DOMAIN_V1.unit is c8.ClockUnitV1.VIRTUAL_MILLISECOND
    assert c8.CLOCK_DOMAIN_V1.wall_clock_semantics is c8.WallClockSemanticsV1.FORBIDDEN
    assert c8.ENGINEERING_TEST_PROFILE_V1.designation == (
        "NON_OFFICIAL_ENGINEERING_PROFILE"
    )
    assert c8.ENGINEERING_TEST_PROFILE_V1.official_client_parity is False
    assert tuple(item.window_kind for item in c8.ENGINEERING_TEST_PROFILE_V1.durations) == tuple(
        c8.TimedWindowKindV1
    )
    assert all(item.duration_ticks == 100 for item in c8.ENGINEERING_TEST_PROFILE_V1.durations)
    assert c8.C8_A_CONTRACT_DESCRIPTOR_V1["timeout_unresolved"] == (
        "FAIL_CLOSED_AND_FUTURE_OUTER_TRANSACTION_ROLLBACK"
    )
    assert c8.C8_A_CONTRACT_DESCRIPTOR_V1["multi_step_deadline_refresh"] == "FORBIDDEN"
    assert c8.C8_A_CONTRACT_IDS_V1["multi_step_timeout_rule"] == (
        c8.MULTI_STEP_TIMEOUT_RULE_ID
    )
    assert c8.C8_A_CONTRACT_IDS_V1["timeout_unresolved_rule"] == (
        c8.TIMEOUT_UNRESOLVED_RULE_ID
    )


def test_module_has_no_wall_clock_rng_or_private_runtime_dependency() -> None:
    source_path = Path(inspect.getsourcefile(c8) or "")
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    imported_roots = {
        alias.name.split(".", 1)[0]
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    assert imported_roots.isdisjoint({"datetime", "random", "secrets", "time"})
    assert tuple(inspect.signature(c8.resolve_timeout_v1).parameters) == (
        "window",
        "current_tick",
        "public_legal_set",
        "fallback_policy",
    )


def test_core_contracts_json_round_trip_and_immutable() -> None:
    state = _state_with_window()
    active = state.window_stack.active_window
    assert active is not None
    assert c8.ClockDomainV1.from_dict(_json_round_trip(c8.CLOCK_DOMAIN_V1.to_dict())) == (
        c8.CLOCK_DOMAIN_V1
    )
    assert c8.DurationProfileV1.from_dict(
        _json_round_trip(c8.ENGINEERING_TEST_PROFILE_V1.to_dict())
    ) == c8.ENGINEERING_TEST_PROFILE_V1
    assert c8.TimeoutFallbackRegistryV1.from_dict(
        _json_round_trip(c8.TIMEOUT_FALLBACK_REGISTRY_V1.to_dict())
    ) == c8.TIMEOUT_FALLBACK_REGISTRY_V1
    assert c8.VirtualTimeStateV1.from_dict(_json_round_trip(state.to_dict())) == state
    with pytest.raises(c8.C8VirtualTimeContractError, match="frozen C8-A clock domain"):
        c8.VirtualTimeStateV1.build(
            clock_domain_identity="f" * 64,
            now_tick=state.now_tick,
            next_input_seq=state.next_input_seq,
            next_window_seq=state.next_window_seq,
            clock_revision=state.clock_revision,
            globally_paused=state.globally_paused,
            window_stack=state.window_stack,
            event_chain=state.event_chain,
        )
    with pytest.raises(FrozenInstanceError):
        active.deadline_at = 999  # type: ignore[misc]


def test_monotonic_advance_and_surplus_stops_at_active_deadline() -> None:
    state = _state_with_window()
    active = state.window_stack.active_window
    assert active is not None and active.deadline_at == 100
    first = c8.advance_virtual_time_v1(
        state, _advance_input(state, 40), c8.CLOCK_DOMAIN_V1
    )
    assert first.state.now_tick == 40
    assert first.state.next_input_seq == 1
    assert first.consumed_ticks == 40
    assert first.unconsumed_ticks == 0
    assert first.derived_deadline is None

    second = c8.advance_virtual_time_v1(
        first.state, _advance_input(first.state, 140), c8.CLOCK_DOMAIN_V1
    )
    assert second.state.now_tick == 100
    assert second.applied_tick == 100
    assert second.consumed_ticks == 60
    assert second.unconsumed_ticks == 40
    assert second.derived_deadline is not None
    assert second.derived_deadline.reached_at == active.deadline_at
    assert second.state.event_chain_tip == second.derived_deadline.event_identity
    with pytest.raises(c8.C8VirtualTimeContractError, match="必须先resolve"):
        c8.advance_virtual_time_v1(
            second.state,
            _advance_input(second.state, 100),
            c8.CLOCK_DOMAIN_V1,
        )


def test_negative_backward_bool_and_reordered_advance_fail_closed() -> None:
    state = _state_with_window()
    with pytest.raises(c8.C8VirtualTimeContractError):
        _advance_input(state, -1)
    payload = _advance_input(state, 10).to_dict()
    payload["requested_tick"] = True
    with pytest.raises(c8.C8VirtualTimeContractError):
        c8.VirtualTimeAdvanceInputV1.from_dict(payload)
    with pytest.raises(c8.C8VirtualTimeContractError, match="sequence"):
        c8.advance_virtual_time_v1(
            state,
            _advance_input(state, 10, input_seq=1),
            c8.CLOCK_DOMAIN_V1,
        )
    advanced = c8.advance_virtual_time_v1(
        state, _advance_input(state, 40), c8.CLOCK_DOMAIN_V1
    ).state
    with pytest.raises(c8.C8VirtualTimeContractError, match="倒退"):
        c8.advance_virtual_time_v1(
            advanced,
            _advance_input(advanced, 39),
            c8.CLOCK_DOMAIN_V1,
        )


def test_caller_forged_deadline_reached_input_is_rejected() -> None:
    state = _state_with_window()
    payload = _advance_input(state, 100).to_dict()
    payload["input_kind"] = "DEADLINE_REACHED"
    with pytest.raises(c8.C8VirtualTimeContractError):
        c8.VirtualTimeAdvanceInputV1.from_dict(payload)
    payload = _advance_input(state, 100).to_dict()
    payload["event_kind"] = "DEADLINE_REACHED"
    with pytest.raises(c8.C8VirtualTimeContractError, match="extra"):
        c8.VirtualTimeAdvanceInputV1.from_dict(payload)


def test_derived_deadline_requires_live_derivation_and_strict_rederive() -> None:
    state = _state_with_window()
    advance_input = _advance_input(state, 100)
    result = c8.advance_virtual_time_v1(state, advance_input, c8.CLOCK_DOMAIN_V1)
    event = result.derived_deadline
    assert event is not None
    active = result.state.window_stack.active_window
    assert active is not None
    loaded = c8.DerivedDeadlineReachedV1.from_dict(
        _json_round_trip(event.to_dict()),
        prior_state=state,
        current_tick=result.state.now_tick,
        caused_by_input=advance_input,
        previous_event_chain_tip=state.event_chain_tip,
    )
    assert loaded == event
    attacked = event.to_dict()
    attacked["deadline_at"] = 99
    with pytest.raises(c8.C8VirtualTimeContractError, match="fresh derivation"):
        c8.DerivedDeadlineReachedV1.from_dict(
            attacked,
            prior_state=state,
            current_tick=result.state.now_tick,
            caused_by_input=advance_input,
            previous_event_chain_tip=state.event_chain_tip,
        )
    wrong_input = c8.VirtualTimeAdvanceInputV1.issue(
        input_seq=state.next_input_seq + 1,
        source_id="test-authenticated-driver",
        domain_id=c8.CLOCK_DOMAIN_ID,
        window_id=active.window_id,
        requested_tick=active.deadline_at,
        authentication_evidence_identity=AUTH_ID,
    )
    with pytest.raises(c8.C8VirtualTimeContractError, match="sequence"):
        c8.DerivedDeadlineReachedV1.from_dict(
            event.to_dict(),
            prior_state=state,
            current_tick=result.state.now_tick,
            caused_by_input=wrong_input,
            previous_event_chain_tip=state.event_chain_tip,
        )
    type_drift = event.to_dict()
    type_drift["caused_by_input_seq"] = False
    with pytest.raises(c8.C8VirtualTimeContractError, match="fresh derivation"):
        c8.DerivedDeadlineReachedV1.from_dict(
            type_drift,
            prior_state=state,
            current_tick=result.state.now_tick,
            caused_by_input=advance_input,
            previous_event_chain_tip=state.event_chain_tip,
        )


def test_exact_boundary_interval_deadline_wins() -> None:
    state = _state_with_window()
    policy = c8.TIMEOUT_FALLBACK_POLICY_BY_KIND_V1[c8.TimedWindowKindV1.PLAY]
    before = c8.advance_virtual_time_v1(
        state, _advance_input(state, 99), c8.CLOCK_DOMAIN_V1
    ).state
    before_window = before.window_stack.active_window
    assert before_window is not None
    before_legal_set = _legal_set(
        before_window, (c8.PublicActionFamilyV1.END_PLAY_PHASE,)
    )
    assert c8.deadline_precedence_v1(before_window, 99) is (
        c8.DeadlinePrecedenceV1.ACTION_ELIGIBLE_BEFORE_DEADLINE
    )
    assert c8.resolve_timeout_v1(
        before_window, 99, before_legal_set, policy
    ).resolution_kind is (
        c8.TimeoutResolutionKindV1.TIMEOUT_NOT_DUE
    )
    closed_before = c8.close_decision_window_v1(
        before,
        window_id=before_window.window_id,
        close_status=c8.TimedWindowStatusV1.CLOSED_BY_ACTION,
    )
    assert closed_before.closed_window.status is c8.TimedWindowStatusV1.CLOSED_BY_ACTION

    deadline_result = _deadline_result()
    at_deadline = deadline_result.state
    deadline_window = at_deadline.window_stack.active_window
    assert deadline_window is not None
    deadline_legal_set = _legal_set(
        deadline_window, (c8.PublicActionFamilyV1.END_PLAY_PHASE,)
    )
    assert c8.deadline_precedence_v1(deadline_window, 100) is (
        c8.DeadlinePrecedenceV1.TIMEOUT_PRIORITY_AT_OR_AFTER_DEADLINE
    )
    resolved = c8.resolve_timeout_v1(
        deadline_window, 100, deadline_legal_set, policy
    )
    assert resolved.resolution_kind is (
        c8.TimeoutResolutionKindV1.RESOLVE_TO_PUBLIC_ACTION_ORDINAL
    )
    assert resolved.resolved_public_ordinal == 0
    assert resolved.resolution_tick == deadline_window.deadline_at
    assert c8.TimeoutResolutionV1.from_dict(
        _json_round_trip(resolved.to_dict()),
        window=deadline_window,
        current_tick=deadline_window.deadline_at,
        public_legal_set=deadline_legal_set,
        fallback_policy=policy,
    ) == resolved
    resigned_early = resolved.to_dict()
    resigned_early["resolution_tick"] = 99
    resigned_early["resolution_identity"] = c8._canonical_sha256(
        {
            key: value
            for key, value in resigned_early.items()
            if key != "resolution_identity"
        }
    )
    with pytest.raises(c8.C8VirtualTimeContractError, match="fresh resolver"):
        c8.TimeoutResolutionV1.from_dict(
            resigned_early,
            window=deadline_window,
            current_tick=deadline_window.deadline_at,
            public_legal_set=deadline_legal_set,
            fallback_policy=policy,
        )
    with pytest.raises(c8.C8VirtualTimeContractError, match="exact deadline"):
        c8.TimeoutResolutionV1._build(
            resolution_kind=c8.TimeoutResolutionKindV1.RESOLVE_TO_PUBLIC_ACTION_ORDINAL,
            reason=c8.TimeoutResolutionReasonV1.EXPLICIT_FALLBACK,
            current_tick=99,
            window=before_window,
            legal_set=before_legal_set,
            policy=policy,
            candidate=before_legal_set.actions[0],
            same_tick_chain_required=False,
        )
    with pytest.raises(c8.C8VirtualTimeContractError, match="不得越过deadline"):
        c8.resolve_timeout_v1(
            deadline_window,
            deadline_window.deadline_at + 1,
            deadline_legal_set,
            policy,
        )
    with pytest.raises(c8.C8VirtualTimeContractError, match=r"\[opened_at, deadline_at\)"):
        c8.close_decision_window_v1(
            at_deadline,
            window_id=deadline_window.window_id,
            close_status=c8.TimedWindowStatusV1.CLOSED_BY_ACTION,
        )
    timeout_closed = c8.close_decision_window_v1(
        at_deadline,
        window_id=deadline_window.window_id,
        close_status=c8.TimedWindowStatusV1.CLOSED_BY_TIMEOUT,
    )
    assert timeout_closed.closed_window.status is c8.TimedWindowStatusV1.CLOSED_BY_TIMEOUT


def test_nested_child_pauses_parent_and_resume_preserves_remaining_budget() -> None:
    state = _state_with_window()
    state = c8.advance_virtual_time_v1(
        state, _advance_input(state, 30), c8.CLOCK_DOMAIN_V1
    ).state
    parent_before = state.window_stack.active_window
    assert parent_before is not None
    parent_binding = parent_before.window_binding_identity
    parent_state_identity = parent_before.window_state_identity
    state = c8.open_decision_window_v1(
        state,
        actor_id="p2",
        window_kind=c8.TimedWindowKindV1.OPTIONAL_RESPONSE,
        decision_identity="6" * 64,
        obligation_identity="7" * 64,
        duration_profile=c8.ENGINEERING_TEST_PROFILE_V1,
        fallback_policy=c8.TIMEOUT_FALLBACK_POLICY_BY_KIND_V1[
            c8.TimedWindowKindV1.OPTIONAL_RESPONSE
        ],
    )
    parent_suspended, child = state.window_stack.windows
    assert parent_suspended.status is c8.TimedWindowStatusV1.SUSPENDED_BY_CHILD
    assert parent_suspended.remaining_ticks == 70
    assert parent_suspended.window_binding_identity == parent_binding
    assert parent_suspended.window_state_identity != parent_state_identity
    state = c8.advance_virtual_time_v1(
        state, _advance_input(state, 80), c8.CLOCK_DOMAIN_V1
    ).state
    closed = c8.close_decision_window_v1(
        state,
        window_id=child.window_id,
        close_status=c8.TimedWindowStatusV1.CLOSED_BY_ACTION,
    )
    resumed = closed.state.window_stack.active_window
    assert resumed is not None
    assert resumed.window_id == parent_before.window_id
    assert resumed.window_binding_identity == parent_binding
    assert resumed.remaining_ticks == 70
    assert resumed.deadline_at == 150
    assert resumed.status is c8.TimedWindowStatusV1.ACTIVE
    parent_timeout = c8.advance_virtual_time_v1(
        closed.state, _advance_input(closed.state, 150), c8.CLOCK_DOMAIN_V1
    )
    assert parent_timeout.derived_deadline is not None
    assert parent_timeout.derived_deadline.opened_at == 0
    assert parent_timeout.derived_deadline.deadline_at == 150
    assert parent_timeout.derived_deadline.budget_ticks == 100
    assert parent_timeout.derived_deadline.elapsed_ticks == 100
    assert parent_timeout.derived_deadline.elapsed_semantics == "ACTIVE_BUDGET_TICKS_ONLY"


def test_malformed_parent_and_non_lifo_close_fail_closed() -> None:
    state = _state_with_window()
    state = c8.advance_virtual_time_v1(
        state, _advance_input(state, 10), c8.CLOCK_DOMAIN_V1
    ).state
    state = c8.open_decision_window_v1(
        state,
        actor_id="p2",
        window_kind=c8.TimedWindowKindV1.OPTIONAL_RESPONSE,
        decision_identity="6" * 64,
        obligation_identity="7" * 64,
        duration_profile=c8.ENGINEERING_TEST_PROFILE_V1,
        fallback_policy=c8.TIMEOUT_FALLBACK_POLICY_BY_KIND_V1[
            c8.TimedWindowKindV1.OPTIONAL_RESPONSE
        ],
    )
    parent, child = state.window_stack.windows
    with pytest.raises(c8.C8VirtualTimeContractError, match="LIFO"):
        c8.close_decision_window_v1(
            state,
            window_id=parent.window_id,
            close_status=c8.TimedWindowStatusV1.CLOSED_BY_ACTION,
        )
    wrong_child = c8.TimedDecisionWindowV1.open(
        window_sequence=child.window_sequence,
        actor_id=child.actor_id,
        window_kind=child.window_kind,
        opened_at=child.opened_at,
        parent_window_id=None,
        decision_identity=child.decision_identity,
        obligation_identity=child.obligation_identity,
        duration_profile=c8.ENGINEERING_TEST_PROFILE_V1,
        fallback_policy=c8.TIMEOUT_FALLBACK_POLICY_BY_KIND_V1[child.window_kind],
    )
    with pytest.raises(c8.C8VirtualTimeContractError, match="parent"):
        c8.TimedWindowStackV1.build((parent, wrong_child))


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("actor_id", "p8"),
        ("window_kind", c8.TimedWindowKindV1.MODE_DECISION.value),
        ("deadline_at", 101),
        ("duration_profile_identity", "9" * 64),
        ("fallback_policy_identity", "8" * 64),
        ("decision_identity", "7" * 64),
        ("obligation_identity", "6" * 64),
    ],
)
def test_window_authority_tamper_rejected(field: str, replacement: object) -> None:
    window = _state_with_window().window_stack.active_window
    assert window is not None
    payload = window.to_dict()
    payload[field] = replacement
    with pytest.raises(c8.C8VirtualTimeContractError):
        c8.TimedDecisionWindowV1.from_dict(payload)


def test_serialization_missing_extra_type_drift_and_deep_tamper_fail_closed() -> None:
    state = _state_with_window()
    payload = state.to_dict()
    missing = _json_round_trip(payload)
    assert isinstance(missing, dict)
    del missing["next_input_seq"]
    with pytest.raises(c8.C8VirtualTimeContractError, match="missing"):
        c8.VirtualTimeStateV1.from_dict(missing)
    extra = _json_round_trip(payload)
    assert isinstance(extra, dict)
    extra["unknown"] = "rejected"
    with pytest.raises(c8.C8VirtualTimeContractError, match="extra"):
        c8.VirtualTimeStateV1.from_dict(extra)
    drift = _json_round_trip(payload)
    assert isinstance(drift, dict)
    drift["clock_revision"] = True
    with pytest.raises(c8.C8VirtualTimeContractError):
        c8.VirtualTimeStateV1.from_dict(drift)
    deep = _json_round_trip(payload)
    assert isinstance(deep, dict)
    deep_stack = deep["window_stack"]
    assert isinstance(deep_stack, dict)
    deep_windows = deep_stack["windows"]
    assert isinstance(deep_windows, list)
    assert isinstance(deep_windows[0], dict)
    deep_windows[0]["actor_id"] = "p8"
    with pytest.raises(c8.C8VirtualTimeContractError):
        c8.VirtualTimeStateV1.from_dict(deep)


def test_frozen_profile_policy_and_suspended_remaining_budget_are_latched() -> None:
    alternate_profile = c8.DurationProfileV1.build(
        profile_id="c8-alternate-engineering-profile-v1",
        durations=c8.ENGINEERING_TEST_PROFILE_V1.durations,
    )
    state = c8.VirtualTimeStateV1.initial(c8.CLOCK_DOMAIN_V1)
    with pytest.raises(c8.C8VirtualTimeContractError, match="frozen engineering profile"):
        c8.open_decision_window_v1(
            state,
            actor_id="p1",
            window_kind=c8.TimedWindowKindV1.PLAY,
            decision_identity=DECISION_ID,
            obligation_identity=OBLIGATION_ID,
            duration_profile=alternate_profile,
            fallback_policy=c8.TIMEOUT_FALLBACK_POLICY_BY_KIND_V1[
                c8.TimedWindowKindV1.PLAY
            ],
        )
    alternate_policy = c8.TimeoutFallbackPolicyV1.build(
        policy_id="c8-alternate-play-policy-v1",
        window_kind=c8.TimedWindowKindV1.PLAY,
        selector=c8.TimeoutFallbackSelectorV1.EXPLICIT_ACTION_FAMILY,
        allowed_action_families=(c8.PublicActionFamilyV1.END_PLAY_PHASE,),
    )
    with pytest.raises(c8.C8VirtualTimeContractError, match="frozen fallback policy"):
        c8.open_decision_window_v1(
            state,
            actor_id="p1",
            window_kind=c8.TimedWindowKindV1.PLAY,
            decision_identity=DECISION_ID,
            obligation_identity=OBLIGATION_ID,
            duration_profile=c8.ENGINEERING_TEST_PROFILE_V1,
            fallback_policy=alternate_policy,
        )
    canonical_window = _state_with_window().window_stack.active_window
    assert canonical_window is not None
    with pytest.raises(c8.C8VirtualTimeContractError, match="frozen engineering duration"):
        c8.TimedDecisionWindowV1._build(
            window_sequence=canonical_window.window_sequence,
            actor_id=canonical_window.actor_id,
            window_kind=canonical_window.window_kind,
            opened_at=canonical_window.opened_at,
            deadline_at=canonical_window.deadline_at + 1,
            budget_ticks=canonical_window.budget_ticks + 1,
            remaining_ticks=canonical_window.remaining_ticks + 1,
            parent_window_id=canonical_window.parent_window_id,
            status=canonical_window.status,
            decision_identity=canonical_window.decision_identity,
            obligation_identity=canonical_window.obligation_identity,
            duration_profile_identity=canonical_window.duration_profile_identity,
            fallback_policy_identity=canonical_window.fallback_policy_identity,
        )

    nested = _state_with_window()
    nested = c8.advance_virtual_time_v1(
        nested, _advance_input(nested, 30), c8.CLOCK_DOMAIN_V1
    ).state
    nested = c8.open_decision_window_v1(
        nested,
        actor_id="p2",
        window_kind=c8.TimedWindowKindV1.OPTIONAL_RESPONSE,
        decision_identity="6" * 64,
        obligation_identity="7" * 64,
        duration_profile=c8.ENGINEERING_TEST_PROFILE_V1,
        fallback_policy=c8.TIMEOUT_FALLBACK_POLICY_BY_KIND_V1[
            c8.TimedWindowKindV1.OPTIONAL_RESPONSE
        ],
    )
    parent, child = nested.window_stack.windows
    minted_parent = parent.with_runtime_state(
        deadline_at=parent.deadline_at,
        remaining_ticks=parent.remaining_ticks + 1,
        status=c8.TimedWindowStatusV1.SUSPENDED_BY_CHILD,
    )
    minted_stack = c8.TimedWindowStackV1.build((minted_parent, child))
    with pytest.raises(c8.C8VirtualTimeContractError, match="remaining budget"):
        c8.VirtualTimeStateV1.build(
            clock_domain_identity=nested.clock_domain_identity,
            now_tick=nested.now_tick,
            next_input_seq=nested.next_input_seq,
            next_window_seq=nested.next_window_seq,
            clock_revision=nested.clock_revision,
            globally_paused=nested.globally_paused,
            window_stack=minted_stack,
            event_chain=nested.event_chain,
        )


def test_stack_sequence_and_live_rollback_bypass_fail_closed() -> None:
    state = _state_with_window()
    parent = state.window_stack.active_window
    assert parent is not None
    suspended = parent.with_runtime_state(
        deadline_at=parent.deadline_at,
        remaining_ticks=parent.remaining_ticks,
        status=c8.TimedWindowStatusV1.SUSPENDED_BY_CHILD,
    )
    non_increasing_child = c8.TimedDecisionWindowV1.open(
        window_sequence=parent.window_sequence,
        actor_id="p2",
        window_kind=c8.TimedWindowKindV1.OPTIONAL_RESPONSE,
        opened_at=state.now_tick,
        parent_window_id=parent.window_id,
        decision_identity="6" * 64,
        obligation_identity="7" * 64,
        duration_profile=c8.ENGINEERING_TEST_PROFILE_V1,
        fallback_policy=c8.TIMEOUT_FALLBACK_POLICY_BY_KIND_V1[
            c8.TimedWindowKindV1.OPTIONAL_RESPONSE
        ],
    )
    with pytest.raises(c8.C8VirtualTimeContractError, match="sequence"):
        c8.TimedWindowStackV1.build((suspended, non_increasing_child))
    with pytest.raises(c8.C8VirtualTimeContractError, match="Snapshot"):
        c8.close_decision_window_v1(
            state,
            window_id=parent.window_id,
            close_status=c8.TimedWindowStatusV1.ROLLED_BACK,
        )


@pytest.mark.parametrize(
    ("kind", "fallback_family"),
    [
        (c8.TimedWindowKindV1.PLAY, c8.PublicActionFamilyV1.END_PLAY_PHASE),
        (
            c8.TimedWindowKindV1.OPTIONAL_RESPONSE,
            c8.PublicActionFamilyV1.PASS_RESPONSE,
        ),
        (
            c8.TimedWindowKindV1.RESCUE_RESPONSE,
            c8.PublicActionFamilyV1.PASS_RESCUE,
        ),
        (
            c8.TimedWindowKindV1.OPTIONAL_SKILL_DECISION,
            c8.PublicActionFamilyV1.DECLINE_OPTIONAL,
        ),
        (
            c8.TimedWindowKindV1.MODE_DECISION,
            c8.PublicActionFamilyV1.PASS_MODE_DECISION,
        ),
    ],
)
def test_explicit_fallback_families_resolve_only_the_registered_action(
    kind: c8.TimedWindowKindV1,
    fallback_family: c8.PublicActionFamilyV1,
) -> None:
    deadline_result = _deadline_result(kind)
    window = deadline_result.state.window_stack.active_window
    assert window is not None
    legal_set = _legal_set(
        window,
        (c8.PublicActionFamilyV1.MANDATORY_ACTION, fallback_family),
    )
    resolved = c8.resolve_timeout_v1(
        window,
        window.deadline_at,
        legal_set,
        c8.TIMEOUT_FALLBACK_POLICY_BY_KIND_V1[kind],
    )
    assert resolved.reason is c8.TimeoutResolutionReasonV1.EXPLICIT_FALLBACK
    assert resolved.resolved_public_ordinal == 1
    assert resolved.resolved_action_family is fallback_family


def test_mandatory_single_selects_only_action_and_rejects_ambiguity() -> None:
    kind = c8.TimedWindowKindV1.MANDATORY_SINGLE_ACTION
    window = _deadline_result(kind).state.window_stack.active_window
    assert window is not None
    policy = c8.TIMEOUT_FALLBACK_POLICY_BY_KIND_V1[kind]
    single = _legal_set(window, (c8.PublicActionFamilyV1.MANDATORY_ACTION,))
    resolved = c8.resolve_timeout_v1(window, window.deadline_at, single, policy)
    assert resolved.reason is c8.TimeoutResolutionReasonV1.UNIQUE_MANDATORY_ACTION
    assert resolved.resolved_public_ordinal == 0
    multiple = _legal_set(
        window,
        (
            c8.PublicActionFamilyV1.MANDATORY_ACTION,
            c8.PublicActionFamilyV1.MANDATORY_ACTION,
        ),
    )
    unresolved = c8.resolve_timeout_v1(window, window.deadline_at, multiple, policy)
    assert unresolved.resolution_kind is c8.TimeoutResolutionKindV1.TIMEOUT_UNRESOLVED


def test_mandatory_public_choice_uses_caller_verified_ordinal_zero() -> None:
    kind = c8.TimedWindowKindV1.MANDATORY_PUBLIC_CHOICE
    window = _deadline_result(kind).state.window_stack.active_window
    assert window is not None
    legal_set = _legal_set(
        window,
        (c8.PublicActionFamilyV1.PUBLIC_CHOICE, c8.PublicActionFamilyV1.PUBLIC_CHOICE),
    )
    resolved = c8.resolve_timeout_v1(
        window,
        window.deadline_at,
        legal_set,
        c8.TIMEOUT_FALLBACK_POLICY_BY_KIND_V1[kind],
    )
    assert resolved.reason is c8.TimeoutResolutionReasonV1.CANONICAL_PUBLIC_ORDINAL
    assert resolved.resolved_public_ordinal == 0
    assert resolved.resolved_candidate_identity == legal_set.actions[0].candidate_identity
    wrong_family = _legal_set(
        window,
        (
            c8.PublicActionFamilyV1.END_PLAY_PHASE,
            c8.PublicActionFamilyV1.MANDATORY_ACTION,
        ),
        suffix="wrong-family",
    )
    assert c8.resolve_timeout_v1(
        window,
        window.deadline_at,
        wrong_family,
        c8.TIMEOUT_FALLBACK_POLICY_BY_KIND_V1[kind],
    ).resolution_kind is c8.TimeoutResolutionKindV1.TIMEOUT_UNRESOLVED


def test_public_ordinal_must_be_caller_validated_and_resolver_never_sorts() -> None:
    kind = c8.TimedWindowKindV1.MANDATORY_PUBLIC_CHOICE
    window = _state_with_window(kind).window_stack.active_window
    assert window is not None
    first = c8.PublicLegalActionCandidateV1.build(
        window_id=window.window_id,
        actor_id=window.actor_id,
        decision_identity=window.decision_identity,
        obligation_identity=window.obligation_identity,
        public_ordinal=1,
        action_id="issued-one",
        action_family=c8.PublicActionFamilyV1.PUBLIC_CHOICE,
    )
    second = c8.PublicLegalActionCandidateV1.build(
        window_id=window.window_id,
        actor_id=window.actor_id,
        decision_identity=window.decision_identity,
        obligation_identity=window.obligation_identity,
        public_ordinal=0,
        action_id="issued-zero",
        action_family=c8.PublicActionFamilyV1.PUBLIC_CHOICE,
    )
    with pytest.raises(c8.C8VirtualTimeContractError, match="canonical public ordinals"):
        c8.PublicLegalSetProjectionV1.build(
            window_id=window.window_id,
            actor_id=window.actor_id,
            decision_identity=window.decision_identity,
            obligation_identity=window.obligation_identity,
            actions=(first, second),
            ordering_contract_id=c8.PUBLIC_ORDERING_CONTRACT_ID,
        )


def test_no_unique_safe_fallback_is_unresolved_and_deterministic() -> None:
    kind = c8.TimedWindowKindV1.PLAY
    window = _deadline_result(kind).state.window_stack.active_window
    assert window is not None
    legal_set = _legal_set(window, (c8.PublicActionFamilyV1.MANDATORY_ACTION,))
    policy = c8.TIMEOUT_FALLBACK_POLICY_BY_KIND_V1[kind]
    results = tuple(
        c8.resolve_timeout_v1(window, window.deadline_at, legal_set, policy)
        for _ in range(20)
    )
    assert len(set(results)) == 1
    assert results[0].resolution_kind is c8.TimeoutResolutionKindV1.TIMEOUT_UNRESOLVED
    assert results[0].reason is (
        c8.TimeoutResolutionReasonV1.NO_SAFE_DETERMINISTIC_FALLBACK
    )


def test_duplicate_explicit_fallback_is_unresolved_not_hash_sorted() -> None:
    window = _deadline_result().state.window_stack.active_window
    assert window is not None
    legal_set = _legal_set(
        window,
        (
            c8.PublicActionFamilyV1.END_PLAY_PHASE,
            c8.PublicActionFamilyV1.END_PLAY_PHASE,
        ),
    )
    result = c8.resolve_timeout_v1(
        window,
        window.deadline_at,
        legal_set,
        c8.TIMEOUT_FALLBACK_POLICY_BY_KIND_V1[c8.TimedWindowKindV1.PLAY],
    )
    assert result.resolution_kind is c8.TimeoutResolutionKindV1.TIMEOUT_UNRESOLVED


def test_resolver_rejects_legal_set_binding_and_policy_tamper() -> None:
    window = _deadline_result().state.window_stack.active_window
    assert window is not None
    legal_set = _legal_set(window, (c8.PublicActionFamilyV1.END_PLAY_PHASE,))
    attacked = legal_set.to_dict()
    attacked["actor_id"] = "p8"
    with pytest.raises(c8.C8VirtualTimeContractError):
        c8.PublicLegalSetProjectionV1.from_dict(attacked)
    wrong_policy = c8.TIMEOUT_FALLBACK_POLICY_BY_KIND_V1[
        c8.TimedWindowKindV1.OPTIONAL_RESPONSE
    ]
    with pytest.raises(c8.C8VirtualTimeContractError, match="window kind"):
        c8.resolve_timeout_v1(window, window.deadline_at, legal_set, wrong_policy)
    nonmember = c8.PublicLegalActionCandidateV1.build(
        window_id=window.window_id,
        actor_id=window.actor_id,
        decision_identity=window.decision_identity,
        obligation_identity=window.obligation_identity,
        public_ordinal=0,
        action_id="issued-but-not-in-this-set",
        action_family=c8.PublicActionFamilyV1.END_PLAY_PHASE,
    )
    with pytest.raises(c8.C8VirtualTimeContractError, match="不是legal set"):
        c8.TimeoutResolutionV1._build(
            resolution_kind=c8.TimeoutResolutionKindV1.RESOLVE_TO_PUBLIC_ACTION_ORDINAL,
            reason=c8.TimeoutResolutionReasonV1.EXPLICIT_FALLBACK,
            current_tick=window.deadline_at,
            window=window,
            legal_set=legal_set,
            policy=c8.TIMEOUT_FALLBACK_POLICY_BY_KIND_V1[
                c8.TimedWindowKindV1.PLAY
            ],
            candidate=nonmember,
            same_tick_chain_required=False,
        )


def test_global_pause_freezes_tick_and_resume_preserves_budget() -> None:
    state = _state_with_window()
    state = c8.advance_virtual_time_v1(
        state, _advance_input(state, 25), c8.CLOCK_DOMAIN_V1
    ).state
    pause_input = _control_input(state, c8.VirtualTimeControlInputKindV1.PAUSE)
    assert c8.VirtualTimeControlInputV1.from_dict(
        _json_round_trip(pause_input.to_dict())
    ) == pause_input
    paused = c8.pause_virtual_time_v1(state, pause_input, c8.CLOCK_DOMAIN_V1)
    frozen = paused.window_stack.active_window
    assert paused.now_tick == 25
    assert paused.next_input_seq == state.next_input_seq + 1
    assert frozen is not None
    assert frozen.status is c8.TimedWindowStatusV1.FROZEN_BY_CLOCK_PAUSE
    assert frozen.remaining_ticks == 75
    with pytest.raises(c8.C8VirtualTimeContractError, match="pause"):
        c8.advance_virtual_time_v1(
            paused,
            c8.VirtualTimeAdvanceInputV1.issue(
                input_seq=paused.next_input_seq,
                source_id="test-authenticated-driver",
                domain_id=c8.CLOCK_DOMAIN_ID,
                window_id=frozen.window_id,
                requested_tick=50,
                authentication_evidence_identity=AUTH_ID,
            ),
            c8.CLOCK_DOMAIN_V1,
        )
    resume_input = _control_input(paused, c8.VirtualTimeControlInputKindV1.RESUME)
    resumed = c8.resume_virtual_time_v1(paused, resume_input, c8.CLOCK_DOMAIN_V1)
    active = resumed.window_stack.active_window
    assert active is not None
    assert active.status is c8.TimedWindowStatusV1.ACTIVE
    assert active.remaining_ticks == 75
    assert active.deadline_at == 100
    assert resumed.next_input_seq == paused.next_input_seq + 1
    with pytest.raises(c8.C8VirtualTimeContractError, match="sequence"):
        c8.pause_virtual_time_v1(
            resumed,
            _control_input(
                resumed,
                c8.VirtualTimeControlInputKindV1.PAUSE,
                input_seq=resumed.next_input_seq + 1,
            ),
            c8.CLOCK_DOMAIN_V1,
        )


def test_bounded_same_tick_chain_requires_fresh_legal_set_and_never_refreshes_deadline() -> None:
    kind = c8.TimedWindowKindV1.MULTI_STEP_OBLIGATION
    deadline_result = _deadline_result(kind)
    window = deadline_result.state.window_stack.active_window
    assert window is not None
    assert deadline_result.derived_deadline is not None
    policy = c8.TIMEOUT_FALLBACK_POLICY_BY_KIND_V1[kind]
    public_choices = _legal_set(
        window,
        (
            c8.PublicActionFamilyV1.PUBLIC_CHOICE,
            c8.PublicActionFamilyV1.PUBLIC_CHOICE,
        ),
        suffix="public-choice",
    )
    public_choice_resolution = c8.resolve_timeout_v1(
        window, window.deadline_at, public_choices, policy
    )
    assert public_choice_resolution.reason is (
        c8.TimeoutResolutionReasonV1.CANONICAL_PUBLIC_ORDINAL
    )
    assert public_choice_resolution.resolved_public_ordinal == 0
    explicit = _legal_set(
        window,
        (
            c8.PublicActionFamilyV1.MANDATORY_ACTION,
            c8.PublicActionFamilyV1.DECLINE_OPTIONAL,
        ),
        suffix="explicit",
    )
    assert c8.resolve_timeout_v1(
        window, window.deadline_at, explicit, policy
    ).reason is c8.TimeoutResolutionReasonV1.EXPLICIT_FALLBACK
    ambiguous = _legal_set(
        window,
        (
            c8.PublicActionFamilyV1.MANDATORY_ACTION,
            c8.PublicActionFamilyV1.PUBLIC_CHOICE,
        ),
        suffix="ambiguous",
    )
    assert c8.resolve_timeout_v1(
        window, window.deadline_at, ambiguous, policy
    ).resolution_kind is c8.TimeoutResolutionKindV1.TIMEOUT_UNRESOLVED
    with pytest.raises(c8.C8VirtualTimeContractError, match="exact deadline"):
        c8.BoundedSameTickFallbackChainV1.start(
            deadline_state=_state_with_window(kind),
            derived_deadline=deadline_result.derived_deadline,
            chain_contract=c8.SAME_TICK_FALLBACK_CHAIN_CONTRACT_V1,
        )
    chain = c8.BoundedSameTickFallbackChainV1.start(
        deadline_state=deadline_result.state,
        derived_deadline=deadline_result.derived_deadline,
        chain_contract=c8.SAME_TICK_FALLBACK_CHAIN_CONTRACT_V1,
    )
    forged_noncanonical = c8.TimeoutResolutionV1._build(
        resolution_kind=c8.TimeoutResolutionKindV1.RESOLVE_TO_PUBLIC_ACTION_ORDINAL,
        reason=c8.TimeoutResolutionReasonV1.CANONICAL_PUBLIC_ORDINAL,
        current_tick=window.deadline_at,
        window=window,
        legal_set=public_choices,
        policy=policy,
        candidate=public_choices.actions[1],
        same_tick_chain_required=True,
    )
    with pytest.raises(c8.C8VirtualTimeContractError, match="fresh resolver"):
        chain.append_resolution(
            resolution=forged_noncanonical,
            public_legal_set=public_choices,
            deadline_state=deadline_result.state,
            current_tick=window.deadline_at,
            chain_contract=c8.SAME_TICK_FALLBACK_CHAIN_CONTRACT_V1,
        )
    first_set = _legal_set(
        window,
        (c8.PublicActionFamilyV1.PUBLIC_CHOICE,),
        suffix="step-0",
    )
    first_resolution = c8.resolve_timeout_v1(
        window, window.deadline_at, first_set, policy
    )
    chain = chain.append_resolution(
        resolution=first_resolution,
        public_legal_set=first_set,
        deadline_state=deadline_result.state,
        current_tick=window.deadline_at,
        chain_contract=c8.SAME_TICK_FALLBACK_CHAIN_CONTRACT_V1,
    )
    assert chain.next_step_index == 1
    assert window.deadline_at == 100
    assert c8.SAME_TICK_FALLBACK_CHAIN_CONTRACT_V1.deadline_refresh_forbidden
    with pytest.raises(c8.C8VirtualTimeContractError, match="fresh legal_actions"):
        chain.append_resolution(
            resolution=first_resolution,
            public_legal_set=first_set,
            deadline_state=deadline_result.state,
            current_tick=window.deadline_at,
            chain_contract=c8.SAME_TICK_FALLBACK_CHAIN_CONTRACT_V1,
        )
    second_set = _legal_set(
        window,
        (c8.PublicActionFamilyV1.PUBLIC_CHOICE,),
        suffix="step-1",
    )
    second_resolution = c8.resolve_timeout_v1(
        window, window.deadline_at, second_set, policy
    )
    with pytest.raises(c8.C8VirtualTimeContractError, match="same tick"):
        chain.append_resolution(
            resolution=second_resolution,
            public_legal_set=second_set,
            deadline_state=deadline_result.state,
            current_tick=window.deadline_at + 1,
            chain_contract=c8.SAME_TICK_FALLBACK_CHAIN_CONTRACT_V1,
        )


def test_bounded_same_tick_chain_hard_cap_and_termination() -> None:
    kind = c8.TimedWindowKindV1.MULTI_STEP_OBLIGATION
    deadline_result = _deadline_result(kind)
    window = deadline_result.state.window_stack.active_window
    assert window is not None
    assert deadline_result.derived_deadline is not None
    policy = c8.TIMEOUT_FALLBACK_POLICY_BY_KIND_V1[kind]
    chain = c8.BoundedSameTickFallbackChainV1.start(
        deadline_state=deadline_result.state,
        derived_deadline=deadline_result.derived_deadline,
        chain_contract=c8.SAME_TICK_FALLBACK_CHAIN_CONTRACT_V1,
    )
    for index in range(c8.SAME_TICK_FALLBACK_CHAIN_MAX_STEPS):
        legal_set = _legal_set(
            window,
            (c8.PublicActionFamilyV1.PUBLIC_CHOICE,),
            suffix=f"cap-{index}",
        )
        resolution = c8.resolve_timeout_v1(
            window, window.deadline_at, legal_set, policy
        )
        chain = chain.append_resolution(
            resolution=resolution,
            public_legal_set=legal_set,
            deadline_state=deadline_result.state,
            current_tick=window.deadline_at,
            chain_contract=c8.SAME_TICK_FALLBACK_CHAIN_CONTRACT_V1,
        )
    extra_set = _legal_set(
        window,
        (c8.PublicActionFamilyV1.PUBLIC_CHOICE,),
        suffix="over-cap",
    )
    extra_resolution = c8.resolve_timeout_v1(
        window, window.deadline_at, extra_set, policy
    )
    with pytest.raises(c8.C8VirtualTimeContractError, match="hard cap"):
        chain.append_resolution(
            resolution=extra_resolution,
            public_legal_set=extra_set,
            deadline_state=deadline_result.state,
            current_tick=window.deadline_at,
            chain_contract=c8.SAME_TICK_FALLBACK_CHAIN_CONTRACT_V1,
        )
    terminated = chain.terminate(c8.SameTickFallbackTerminationV1.OBLIGATION_CLOSED)
    assert terminated.status is c8.SameTickFallbackChainStatusV1.TERMINATED
    assert c8.BoundedSameTickFallbackChainV1.from_dict(
        _json_round_trip(terminated.to_dict()),
        deadline_state=deadline_result.state,
    ) == terminated


def test_snapshot_restore_covers_clock_window_event_chain_and_active_chain() -> None:
    kind = c8.TimedWindowKindV1.MULTI_STEP_OBLIGATION
    deadline_result = _deadline_result(kind)
    advanced = deadline_result.state
    active = advanced.window_stack.active_window
    assert active is not None
    assert deadline_result.derived_deadline is not None
    chain = c8.BoundedSameTickFallbackChainV1.start(
        deadline_state=advanced,
        derived_deadline=deadline_result.derived_deadline,
        chain_contract=c8.SAME_TICK_FALLBACK_CHAIN_CONTRACT_V1,
    )
    snapshot = c8.VirtualTimeTransactionSnapshotV1.capture(
        virtual_time_state=advanced,
        active_fallback_chain=chain,
    )
    loaded = c8.VirtualTimeTransactionSnapshotV1.from_dict(
        _json_round_trip(snapshot.to_dict())
    )
    assert loaded == snapshot
    restored_state, restored_chain = loaded.restore()
    assert restored_state == advanced
    assert restored_state.window_stack == advanced.window_stack
    assert restored_state.event_chain == advanced.event_chain
    assert restored_chain == chain
    unrelated_chain = c8.BoundedSameTickFallbackChainV1._build(
        chain_contract_identity=chain.chain_contract_identity,
        window_id=chain.window_id,
        actor_id="p8",
        decision_identity=chain.decision_identity,
        obligation_identity=chain.obligation_identity,
        window_state_identity=chain.window_state_identity,
        fallback_policy_identity=chain.fallback_policy_identity,
        deadline_event_identity=chain.deadline_event_identity,
        timeout_tick=chain.timeout_tick,
        status=c8.SameTickFallbackChainStatusV1.ACTIVE,
        termination_reason=None,
        steps=(),
    )
    with pytest.raises(c8.C8VirtualTimeContractError, match="current timed-out window"):
        c8.VirtualTimeTransactionSnapshotV1.capture(
            virtual_time_state=advanced,
            active_fallback_chain=unrelated_chain,
        )


def test_chain_rejects_cross_context_splice_and_paused_or_non_multi_snapshot() -> None:
    kind = c8.TimedWindowKindV1.MULTI_STEP_OBLIGATION
    base_result = _deadline_result(kind)
    base_window = base_result.state.window_stack.active_window
    assert base_window is not None
    assert base_result.derived_deadline is not None
    chain = c8.BoundedSameTickFallbackChainV1.start(
        deadline_state=base_result.state,
        derived_deadline=base_result.derived_deadline,
        chain_contract=c8.SAME_TICK_FALLBACK_CHAIN_CONTRACT_V1,
    )

    other = c8.VirtualTimeStateV1.initial(c8.CLOCK_DOMAIN_V1)
    other = c8.open_decision_window_v1(
        other,
        actor_id="p2",
        window_kind=kind,
        decision_identity="6" * 64,
        obligation_identity="7" * 64,
        duration_profile=c8.ENGINEERING_TEST_PROFILE_V1,
        fallback_policy=c8.TIMEOUT_FALLBACK_POLICY_BY_KIND_V1[kind],
    )
    other_result = c8.advance_virtual_time_v1(
        other, _advance_input(other, 100), c8.CLOCK_DOMAIN_V1
    )
    other_window = other_result.state.window_stack.active_window
    assert other_window is not None
    other_legal = _legal_set(
        other_window, (c8.PublicActionFamilyV1.MANDATORY_ACTION,), suffix="other"
    )
    other_resolution = c8.resolve_timeout_v1(
        other_window,
        other_window.deadline_at,
        other_legal,
        c8.TIMEOUT_FALLBACK_POLICY_BY_KIND_V1[kind],
    )
    with pytest.raises(c8.C8VirtualTimeContractError, match="resolution未绑定"):
        chain.append_resolution(
            resolution=other_resolution,
            public_legal_set=other_legal,
            deadline_state=base_result.state,
            current_tick=base_window.deadline_at,
            chain_contract=c8.SAME_TICK_FALLBACK_CHAIN_CONTRACT_V1,
        )
    with pytest.raises(c8.C8VirtualTimeContractError, match="authoritative deadline state"):
        c8.BoundedSameTickFallbackChainV1.from_dict(
            chain.to_dict(),
            deadline_state=other_result.state,
        )

    frozen = base_window.with_runtime_state(
        deadline_at=base_window.deadline_at,
        remaining_ticks=0,
        status=c8.TimedWindowStatusV1.FROZEN_BY_CLOCK_PAUSE,
    )
    paused_state = c8.VirtualTimeStateV1.build(
        clock_domain_identity=base_result.state.clock_domain_identity,
        now_tick=base_result.state.now_tick,
        next_input_seq=base_result.state.next_input_seq,
        next_window_seq=base_result.state.next_window_seq,
        clock_revision=base_result.state.clock_revision + 1,
        globally_paused=True,
        window_stack=c8.TimedWindowStackV1.build((frozen,)),
        event_chain=base_result.state.event_chain,
    )
    with pytest.raises(c8.C8VirtualTimeContractError, match="current timed-out window"):
        c8.VirtualTimeTransactionSnapshotV1.capture(
            virtual_time_state=paused_state,
            active_fallback_chain=chain,
        )

    play_result = _deadline_result(c8.TimedWindowKindV1.PLAY)
    play_window = play_result.state.window_stack.active_window
    assert play_window is not None
    assert play_result.derived_deadline is not None
    forged_non_multi_chain = c8.BoundedSameTickFallbackChainV1._build(
        chain_contract_identity=c8.SAME_TICK_FALLBACK_CHAIN_CONTRACT_V1.contract_identity,
        window_id=play_window.window_id,
        actor_id=play_window.actor_id,
        decision_identity=play_window.decision_identity,
        obligation_identity=play_window.obligation_identity,
        window_state_identity=play_window.window_state_identity,
        fallback_policy_identity=play_window.fallback_policy_identity,
        deadline_event_identity=play_result.derived_deadline.event_identity,
        timeout_tick=play_window.deadline_at,
        status=c8.SameTickFallbackChainStatusV1.ACTIVE,
        termination_reason=None,
        steps=(),
    )
    with pytest.raises(c8.C8VirtualTimeContractError, match="current timed-out window"):
        c8.VirtualTimeTransactionSnapshotV1.capture(
            virtual_time_state=play_result.state,
            active_fallback_chain=forged_non_multi_chain,
        )


def test_public_private_projection_schemas_are_separate_and_public_rejects_leakage() -> None:
    state = _state_with_window()
    window = state.window_stack.active_window
    assert window is not None
    legal_set = _legal_set(window, (c8.PublicActionFamilyV1.END_PLAY_PHASE,))
    public = c8.TimedPublicProjectionV1.build(
        state=state,
        window=window,
        legal_set=legal_set,
    )
    assert c8.TimedPublicProjectionV1.from_dict(
        _json_round_trip(public.to_dict())
    ) == public
    attacked = public.to_dict()
    attacked["private_choice"] = {"card_id": "forbidden"}
    with pytest.raises(c8.C8VirtualTimeContractError, match="禁止"):
        c8.TimedPublicProjectionV1.from_dict(attacked)
    private = c8.TimedAuthoritativePrivateProjectionV1.build(
        public_projection_identity=public.projection_identity,
        window_state_identity=window.window_state_identity,
        authority_binding_identity=PRIVATE_BINDING_ID,
        private_payload_commitment=PRIVATE_COMMITMENT,
    )
    assert c8.TimedAuthoritativePrivateProjectionV1.from_dict(
        _json_round_trip(private.to_dict())
    ) == private
    assert "private_payload_commitment" not in public.to_dict()


def test_public_projection_rejects_actor_decision_and_obligation_mismatch() -> None:
    state = _state_with_window()
    window = state.window_stack.active_window
    assert window is not None
    valid = _legal_set(window, (c8.PublicActionFamilyV1.END_PLAY_PHASE,))
    for field, replacement in (
        ("actor_id", "p8"),
        ("decision_identity", "8" * 64),
        ("obligation_identity", "9" * 64),
    ):
        payload = valid.to_dict()
        payload[field] = replacement
        for candidate in payload["actions"]:
            candidate[field] = replacement
            candidate["candidate_identity"] = c8._canonical_sha256(
                {
                    key: value
                    for key, value in candidate.items()
                    if key != "candidate_identity"
                }
            )
        payload["legal_set_identity"] = c8._canonical_sha256(
            {
                key: value
                for key, value in payload.items()
                if key != "legal_set_identity"
            }
        )
        mismatched = c8.PublicLegalSetProjectionV1.from_dict(payload)
        with pytest.raises(c8.C8VirtualTimeContractError, match="authority binding"):
            c8.TimedPublicProjectionV1.build(
                state=state,
                window=window,
                legal_set=mismatched,
            )


def test_same_tick_contract_strictly_rejects_numeric_type_drift() -> None:
    payload = c8.SAME_TICK_FALLBACK_CHAIN_CONTRACT_V1.to_dict()
    payload["max_steps"] = float(payload["max_steps"])
    with pytest.raises(c8.C8VirtualTimeContractError, match="canonical contract"):
        c8.SameTickFallbackChainContractV1.from_dict(payload)
    direct = c8.CLOCK_DOMAIN_V1.to_dict()
    direct["tick_min"] = False
    direct["clock_domain_identity"] = c8._canonical_sha256(
        {
            key: value
            for key, value in direct.items()
            if key != "clock_domain_identity"
        }
    )
    with pytest.raises(c8.C8VirtualTimeContractError, match="精确整数"):
        c8.ClockDomainV1(
            schema=direct["schema"],
            contract_version=direct["contract_version"],
            domain_id=direct["domain_id"],
            unit=c8.ClockUnitV1(direct["unit"]),
            tick_min=direct["tick_min"],
            tick_max=direct["tick_max"],
            tie_rule=c8.DeadlineTieRuleV1(direct["tie_rule"]),
            consumption_rule=c8.TickConsumptionRuleV1(direct["consumption_rule"]),
            wall_clock_semantics=c8.WallClockSemanticsV1(
                direct["wall_clock_semantics"]
            ),
            clock_domain_identity=direct["clock_domain_identity"],
        )
