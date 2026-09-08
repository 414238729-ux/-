# -*- coding: utf-8 -*-
from __future__ import annotations

# Pure v3 policy examples are source-grammar tests, never natural production evidence.
def _public_ordinal_v3_entry(n=3, phase="discard"):
    from scripts.sgs_engine import c8_timed_8p_full_game_contract_v1 as c
    return c.open_public_ordinal_progress_v1(run_binding_identity="1"*64,
        execution_order_profile_identity="2"*64, opening_ref_identity="3"*64,
        opening_context_identity="4"*64, entry_step_index=4, global_window_index=5,
        deadline_at=497, phase=phase, turn_number=1, turn_player_id="p1", actor_id="p1",
        proposal_count=n, entry_pre_context_identity="5"*64, entry_pre_phase="play", entry_pre_actor_id="p1")


def test_public_ordinal_v3_r2_select_select_commit_and_strict_variant():
    from scripts.sgs_engine import c8_timed_8p_full_game_contract_v1 as c
    s = _public_ordinal_v3_entry()
    variants = [s.variant]
    ordinals = []
    for phase, count in [("discard", 3), ("discard", 4), ("end", 1)]:
        ordinal, kind = c.certified_ordinal_choice_v1(s, s.shape_count)
        ordinals.append((ordinal, kind))
        s = c.advance_public_ordinal_progress_v1(s, chosen_ordinal=ordinal, post_step_count=s.accepted_step_index+1,
            next_phase=phase, next_actor_id="p1", next_turn_number=1, next_turn_player_id="p1", next_proposal_count=count)
        variants.append(s.variant)
    assert ordinals == [(0, "PROGRESS"), (0, "PROGRESS"), (3, "COMMIT")]
    assert variants == [4, 3, 2, 0]
    assert s.certified_required_count == 2
    assert s.stage == "DONE"


def test_public_ordinal_v3_exhausted_forward_without_commit_is_unresolved():
    from scripts.sgs_engine import c8_timed_8p_full_game_contract_v1 as c
    s = _public_ordinal_v3_entry(1)
    s = c.advance_public_ordinal_progress_v1(s, chosen_ordinal=0, post_step_count=5,
        next_phase="discard", next_actor_id="p1", next_turn_number=1, next_turn_player_id="p1", next_proposal_count=1)
    with pytest.raises(c.C8G1ContractError, match="DRIVER_LIVENESS_UNRESOLVED"):
        c.certified_ordinal_choice_v1(s, 1)


def test_public_ordinal_v3_missing_entry_or_unknown_source_rejected():
    from scripts.sgs_engine import c8_timed_8p_full_game_contract_v1 as c
    for key, value in [("entry_pre_phase", "discard"), ("source_certificate_identity", "f"*64),
                       ("candidate_count", True), ("certified_selected_progress_count", True),
                       ("phase", "unknown"), ("accepted_step_index", 3)]:
        d = _public_ordinal_v3_entry().to_dict()
        d[key] = value
        with pytest.raises(c.C8G1ContractError):
            c.PublicOrdinalProgressV1.from_dict(d)


def test_public_ordinal_v3_wrong_transition_retains_original_history():
    from scripts.sgs_engine import c8_timed_8p_full_game_contract_v1 as c
    s = _public_ordinal_v3_entry()
    original = s.to_dict()
    for ordinal, phase, count in [(2, "discard", 3), (0, "play", 3), (0, "discard", 2)]:
        with pytest.raises(c.C8G1ContractError):
            c.advance_public_ordinal_progress_v1(s, chosen_ordinal=ordinal, post_step_count=5,
                next_phase=phase, next_actor_id="p1", next_turn_number=1, next_turn_player_id="p1", next_proposal_count=count)
    assert s.to_dict() == original


def test_public_ordinal_v3_hanbing_has_separate_two_discard_certificate():
    from scripts.sgs_engine import c8_timed_8p_full_game_contract_v1 as c
    s = _public_ordinal_v3_entry(3, "hanbing_discard")
    s = c.advance_public_ordinal_progress_v1(s, chosen_ordinal=2, post_step_count=5,
        next_phase="hanbing_discard", next_actor_id="p1", next_turn_number=1, next_turn_player_id="p1", next_proposal_count=2)
    with pytest.raises(c.C8G1ContractError):
        c.advance_public_ordinal_progress_v1(s, chosen_ordinal=1, post_step_count=6,
            next_phase="hanbing_discard", next_actor_id="p1", next_turn_number=1, next_turn_player_id="p1", next_proposal_count=1)
    final = c.advance_public_ordinal_progress_v1(s, chosen_ordinal=1, post_step_count=6,
        next_phase="play", next_actor_id="p1", next_turn_number=1, next_turn_player_id="p1", next_proposal_count=5)
    assert final.variant == 0 and final.certified_required_count is None
"""Cheap contract-only tests for provisional C8-G1."""

import ast
from copy import deepcopy
from dataclasses import replace
import hashlib
from pathlib import Path

import pytest

from scripts.sgs_engine import c8_timed_8p_full_game_contract_v1 as g


REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("phase", ["discard", "weapon_discard_two"])
@pytest.mark.parametrize("n,required", [(n,r) for n in range(1,6) for r in range(1,n+1)])
def test_v3_gate_pinned_grammar_reachable_boundaries(n, required, phase):
    """Abstract grammar inputs only; this is not production required-count observation."""
    state = _public_ordinal_v3_entry(n, phase)
    steps = 0
    for selected in range(required):
        assert g.certified_ordinal_choice_v1(state, state.shape_count) == (0,"PROGRESS")
        old_variant = state.variant
        state = g.advance_public_ordinal_progress_v1(state, chosen_ordinal=0, post_step_count=5+steps,
            next_phase=phase,next_actor_id="p1",next_turn_number=1,next_turn_player_id="p1",
            next_proposal_count=n+int(selected+1==required))
        steps += 1
        assert state.variant < old_variant
    assert g.certified_ordinal_choice_v1(state, state.shape_count) == (n,"COMMIT")
    state = g.advance_public_ordinal_progress_v1(state,chosen_ordinal=n,post_step_count=5+steps,
        next_phase="play",next_actor_id="p1",next_turn_number=1,next_turn_player_id="p1",next_proposal_count=1)
    assert state.variant == 0 and state.certified_required_count == required
    assert steps+1 <= n+1


@pytest.mark.parametrize("chooser,expected", [("last",[0,1,0,1,0,1,0]),("first",[0,1,2,3,2,3,2])])
def test_v3_gate_unconditional_first_last_counterexamples(chooser,expected):
    n, required, selected = 3, 2, 0
    trajectory = [selected]
    for _ in range(6):
        grammar = ["forward"]*(n-selected)+["reverse"]*selected+["commit"]*int(selected==required)
        operation = grammar[0 if chooser == "first" else -1]
        assert operation != "commit"
        selected += 1 if operation == "forward" else -1
        trajectory.append(selected)
    assert trajectory == expected


@pytest.mark.parametrize("phase", ["cixiong_target_choice","zone_choice","fire_attack_reveal","borrowed_sword_choice","wugu_pick"])
def test_v3_gate_single_private_choice_retains_last_and_cannot_repeat(phase):
    state = _public_ordinal_v3_entry(3,phase)
    assert g.certified_ordinal_choice_v1(state,3) == (2,"PROGRESS")
    with pytest.raises(ValueError, match="未知第二步"):
        g.advance_public_ordinal_progress_v1(state,chosen_ordinal=2,post_step_count=5,
            next_phase=phase,next_actor_id="p1",next_turn_number=1,next_turn_player_id="p1",next_proposal_count=2)
    out = g.advance_public_ordinal_progress_v1(state,chosen_ordinal=2,post_step_count=5,
        next_phase=phase if phase=="wugu_pick" else "play",next_actor_id="p2",next_turn_number=1,next_turn_player_id="p1",next_proposal_count=2)
    assert out.stage == "DONE"


@pytest.mark.parametrize("field,value", [("next_turn_number",True),("next_proposal_count",True),
    ("next_phase",None),("next_actor_id",None),("next_proposal_count",0)])
def test_v3_gate_accepted_public_boundary_exact_types(field,value):
    post = dict(next_phase="discard",next_actor_id="p1",next_turn_number=1,next_turn_player_id="p1",next_proposal_count=3)
    post[field] = value
    with pytest.raises(ValueError):
        g.advance_public_ordinal_progress_v1(_public_ordinal_v3_entry(),chosen_ordinal=0,post_step_count=5,**post)


def test_v3_gate_forward_bucket_permutation_does_not_change_eligible_ordinal():
    # All candidates are opaque: no card ID/handle ordering is supplied to G1.
    for order in (("A","B","C"),("C","A","B")):
        state = _public_ordinal_v3_entry(len(order))
        assert g.certified_ordinal_choice_v1(state,len(order))[0] == 0
    changed_source = _public_ordinal_v3_entry().to_dict()
    changed_source["source_certificate_identity"] = "f"*64
    with pytest.raises(ValueError):
        g.PublicOrdinalProgressV1.from_dict(changed_source)


def _id(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _actions(*families: str) -> tuple[g.PublicActionOptionV1, ...]:
    return tuple(
        g.PublicActionOptionV1(index, family)
        for index, family in enumerate(families)
    )


def _driver_input(
    index: int,
    *,
    kind: g.PublicWindowKindV1 = g.PublicWindowKindV1.OTHER_PUBLIC,
    applicability: g.TimeoutApplicabilityV1 = g.TimeoutApplicabilityV1.APPLICABLE,
    families: tuple[str, ...] = ("ACTION_A", "ACTION_B"),
) -> g.FormalDriverInputV1:
    actions = _actions(*families)
    return g.FormalDriverInputV1(
        formal_seed=0,
        global_window_index=index,
        turn_number=1,
        turn_player_id="p1",
        actor_id="p1",
        phase="play",
        window_kind=kind,
        deadline_at=index * 100,
        timeout_applicability=applicability,
        proposal_order_identity=g.identity_v1(
            [item.to_dict() for item in actions]
        ),
        public_actions=actions,
    )


def _complete_witnesses(
    *, missing: str | None = None
) -> tuple[g.RequiredEventWitnessV1, ...]:
    result: list[g.RequiredEventWitnessV1] = []
    for obligation in g.REQUIRED_EVENT_OBLIGATIONS_V1:
        if obligation.obligation_id == missing:
            status = g.WitnessStatusV1.MISSING
            identities: tuple[str, ...] = ()
            scope = "FULL_GAME_REAL_PRODUCTION_TRACE"
        elif obligation.applicability is (
            g.ObligationApplicabilityV1.NOT_APPLICABLE_IN_C6_NO_SKILL_8P
        ):
            status = g.WitnessStatusV1.NOT_APPLICABLE_IN_C6_NO_SKILL_8P
            identities = ()
            scope = "C6_NO_SKILL_STRUCTURAL_AUTHORITY_DECISION"
        elif obligation.level is g.ObligationLevelV1.AUDITED_PREREQUISITE:
            status = g.WitnessStatusV1.AUDITED_PREREQUISITE_PASSED
            identities = ()
            scope = "C8_E_INDEPENDENT_TARGETED_AUDIT_PASSED"
        elif obligation.obligation_id == "FG-TIMER-09":
            status = g.WitnessStatusV1.NOT_NATURALLY_OBSERVED
            identities = ()
            scope = "FULL_GAME_REAL_PRODUCTION_TRACE"
        else:
            status = g.WitnessStatusV1.OBSERVED
            identities = (_id(f"witness:{obligation.obligation_id}"),)
            scope = "FULL_GAME_REAL_PRODUCTION_TRACE"
        result.append(
            g.RequiredEventWitnessV1(
                obligation.obligation_id,
                obligation.level,
                obligation.applicability,
                status,
                identities,
                scope,
            )
        )
    return tuple(result)


def _good_result(
    seed: int,
    registry: g.FullGameRegistryV1,
    implementation_identity: str,
    **overrides: object,
) -> g.FullGameResultV1:
    assert seed in {item.seed for item in registry.selected_cells}
    candidate_registry = (
        g.FullGameRegistryV1.canonical()
        if seed in g.C8_G1_BASELINE_SEEDS
        else g.FullGameRegistryV1.canonical((seed,))
    )
    values: dict[str, object] = {
        "cell_id": g.canonical_cell_id_v1(seed),
        "seed": seed,
        "mode_id": g.C8_G1_BASE_MODE_ID,
        "registry_identity": candidate_registry.registry_identity,
        "current_implementation_identity": implementation_identity,
        "contract_identity": g.C8_G1_CONTRACT_IDENTITY,
        "timer_profile_id": g.C8_G1_TIMER_PROFILE_ID,
        "driver_policy_identity": g.C8_G1_DRIVER_POLICY_IDENTITY,
        "replay_schema": g.C8_G1_REPLAY_SCHEMA,
        "replay_scope": "FULL_GAME_REAL_PRODUCTION_TRACE",
        "production_adapter_id": g.C8_G1_E_ADAPTER_ID,
        "production_adapter_contract_identity": g.C8_G1_E_CONTRACT_IDENTITY,
        "controller_contract_identity": g.C8_G1_C_CONTROLLER_CONTRACT_IDENTITY,
        "artifact_scope": g.CandidateScopeV1.FORMAL_QUALITY_CANDIDATE,
        "run_status": g.CellRunStatusV1.COMPLETE,
        "artifact_complete": True,
        "full_game": True,
        "formal_matrix_cell": True,
        "natural_terminal": True,
        "safety_cap_hit": False,
        "strict_replay_verified": True,
        "replay_identity": _id(f"replay:{seed}"),
        "artifact_identity": _id(f"artifact:{seed}"),
        "verified_fact_ids": g.CELL_ATOMIC_PROOF_FACTS_V1,
        "required_event_witnesses": _complete_witnesses(),
    }
    values.update(overrides)
    return g._fresh_full_game_result_v1(**values)


def _good_matrix(
    registry: g.FullGameRegistryV1,
    implementation_identity: str,
) -> tuple[g.FullGameResultV1, ...]:
    return tuple(
        _good_result(cell.seed, registry, implementation_identity)
        for cell in registry.selected_cells
    )


def _gap_state(*gap_ids: str) -> g.BaselineGapStateV1:
    return g._baseline_gap_state_for_policy_test_v1(gap_ids)


def test_frozen_descriptor_and_claim_boundary() -> None:
    descriptor = g.contract_descriptor_v1()
    assert g.C8_G1_PRIOR_CONTRACT_IDENTITY == (
        "901bcfd02449786ee2a527b54eeaa435b293c588f5910fc17965c0f08a089472"
    )
    assert g.C8_G1_CONTRACT_IDENTITY != g.C8_G1_PRIOR_CONTRACT_IDENTITY
    assert g.C8_G1_CONTRACT_VERSION == 4
    assert descriptor["contract_version"] == 4
    assert descriptor["supersession_status"] == (
        "SUPERSEDED_FOR_CURRENT_G3_SCHEMA"
    )
    relation = descriptor["parent_child_relation_model"]
    assert relation["post_commit_active_parent_ref"] is None
    assert relation["post_commit_parent_deadline_reuse"] == "FORBIDDEN"
    assert descriptor["baseline_seeds"] == [0, 1, 49]
    assert descriptor["timeout_schedule"] == {
        "global_window_index_base": 1,
        "timeout_modulo": 4,
        "timeout_remainder": 0,
        "unresolved_context_policy": "FORCE_ON_TIME_AND_RECORD",
    }
    assert descriptor["max_production_steps_guard"] == 4000
    assert descriptor["max_timer_windows_guard"] == 8192
    assert g.C8_G1_FULL_GAME_REPLAY_EXECUTION == "NOT_PROVEN"
    assert g.C8_G2_STATUS == "PARTIAL_DRAFT_NOT_DELIVERED"
    assert g.C8_G2_PRIOR_BOUNDED_SMOKE_STATUS == "FAILED_AT_WINDOW_4_NO_ARTIFACT"
    assert g.C8_FULL_GAME_STATUS == "NOT_PROVEN"
    assert g.C8_FULL_GAME_MATRIX_STATUS == "NOT_STARTED"


def test_contract_module_is_pure_and_has_no_rng_wall_clock_or_gameplay_calls() -> None:
    path = REPO_ROOT / "scripts/sgs_engine/c8_timed_8p_full_game_contract_v1.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imported_roots = {
        alias.name.split(".", 1)[0]
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    called_names = {
        node.func.attr if isinstance(node.func, ast.Attribute) else node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, (ast.Attribute, ast.Name))
    }
    assert {"random", "time", "datetime"}.isdisjoint(imported_roots)
    assert {"create_session", "step", "run_game"}.isdisjoint(called_names)


def test_required_event_registry_is_exact_and_layered() -> None:
    assert g.REQUIRED_EVENT_OBLIGATION_IDS_V1 == tuple(
        f"FG-TIMER-{index:02d}" for index in range(1, 14)
    )
    by_id = {
        item.obligation_id: item for item in g.REQUIRED_EVENT_OBLIGATIONS_V1
    }
    assert all(
        by_id[f"FG-TIMER-{index:02d}"].level
        is g.ObligationLevelV1.PER_CELL_REQUIRED
        for index in (1, 2, 3, 4, 5, 6, 10, 12)
    )
    assert by_id["FG-TIMER-07"].level is g.ObligationLevelV1.MATRIX_UNION_REQUIRED
    assert by_id["FG-TIMER-08"].level is g.ObligationLevelV1.MATRIX_UNION_REQUIRED
    assert by_id["FG-TIMER-09"].level is (
        g.ObligationLevelV1.CONDITIONAL_MATRIX_UNION_REQUIRED
    )
    assert by_id["FG-TIMER-11"].level is g.ObligationLevelV1.AUDITED_PREREQUISITE
    assert by_id["FG-TIMER-07"].semantic_name == (
        "POST_COMMIT_OPTIONAL_RESPONSE_CAUSAL_CHILD_TIMER"
    )
    assert by_id["FG-TIMER-08"].semantic_name == (
        "POST_COMMIT_DYING_RESCUE_CAUSAL_CHILD_TIMER"
    )
    assert by_id["FG-TIMER-13"].semantic_name == (
        "INTRA_DECISION_NESTED_CHILD_PAUSE_RESUME_AUTHORITY"
    )
    assert by_id["FG-TIMER-13"].applicability is (
        g.ObligationApplicabilityV1.NOT_APPLICABLE_IN_C6_NO_SKILL_8P
    )
    assert g.RequiredEventObligationV1.from_dict(
        by_id["FG-TIMER-01"].to_dict()
    ) == by_id["FG-TIMER-01"]


def test_not_applicable_is_not_a_coverage_gap_but_cannot_spoof_current_07_08() -> None:
    assert g.obligation_status_is_gap_v1(
        g.ObligationLevelV1.NOT_APPLICABLE_IN_C6_NO_SKILL_8P,
        g.WitnessStatusV1.NOT_APPLICABLE_IN_C6_NO_SKILL_8P,
    ) is False
    obligation = g.REQUIRED_EVENT_OBLIGATIONS_V1[6]
    with pytest.raises(g.C8G1ContractError):
        g.RequiredEventWitnessV1(
            obligation.obligation_id,
            obligation.level,
            obligation.applicability,
            g.WitnessStatusV1.NOT_APPLICABLE_IN_C6_NO_SKILL_8P,
            (),
            "FULL_GAME_REAL_PRODUCTION_TRACE",
        )
    structural = g.REQUIRED_EVENT_OBLIGATIONS_V1[-1]
    witness = g.RequiredEventWitnessV1(
        structural.obligation_id,
        structural.level,
        structural.applicability,
        g.WitnessStatusV1.NOT_APPLICABLE_IN_C6_NO_SKILL_8P,
        (),
        "C6_NO_SKILL_STRUCTURAL_AUTHORITY_DECISION",
    )
    assert g.obligation_status_is_gap_v1(witness.level, witness.status) is False


def test_parent_child_relation_model_is_strict_and_mutually_exclusive() -> None:
    independent = g.WindowRelationEvidenceV3.independent_decision_v3()
    assert g.WindowRelationEvidenceV3.from_dict(independent.to_dict()) == independent
    active_parent = g.WindowRelationEvidenceV3.intra_decision_nested_child_v3(
        active_parent_window_id="parent-window",
        active_parent_window_identity=_id("active-parent-window"),
    )
    assert active_parent.expected_active_parent_ref == (
        active_parent.active_parent_window_identity
    )
    assert active_parent.parent_decision_committed is False
    post = g.WindowRelationEvidenceV3.post_commit_v3(
        causal_relation_kind=g.CausalRelationKindV2.POST_COMMIT_CAUSAL_SUCCESSOR,
        causal_parent_window_identity=_id("closed-parent-window"),
        causal_parent_context_identity=_id("closed-parent-context"),
        originating_step_index=4,
        originating_step_identity=_id("origin-step"),
        originating_post_production_revision=4,
        originating_post_public_state_identity=_id("post-public"),
        originating_decision_kind="TIMEOUT_PRODUCTION_DECISION",
        originating_decision_evidence_identity=_id("timeout-evidence"),
        originating_completion_identity=_id("timeout-completion"),
        parent_window_close_status="CLOSED_BY_TIMEOUT",
        post_step_context_identity=_id("discard-context"),
    )
    assert post.expected_active_parent_ref is None
    assert post.active_parent_window_id is None
    assert post.parent_decision_committed is True
    assert post.parent_closed_before_child_open is True
    g.validate_relation_window_kind_v2(
        post, g.PublicWindowKindV1.MULTI_STEP_OBLIGATION
    )
    injected = post.to_dict()
    injected["active_parent_window_id"] = "closed-parent-window"
    with pytest.raises(g.C8G1ContractError):
        g.WindowRelationEvidenceV3.from_dict(injected)
    missing = post.to_dict()
    missing["causal_parent_window_identity"] = None
    with pytest.raises(g.C8G1ContractError):
        g.WindowRelationEvidenceV3.from_dict(missing)


def test_response_dying_are_post_commit_children_but_discard_is_successor() -> None:
    parent = _id("parent-context")
    assert g.classify_post_commit_relation_v2(
        window_kind=g.PublicWindowKindV1.OPTIONAL_RESPONSE,
        causal_parent_context_identity=parent,
    ) is g.CausalRelationKindV2.POST_COMMIT_CAUSAL_CHILD
    assert g.classify_post_commit_relation_v2(
        window_kind=g.PublicWindowKindV1.RESCUE_RESPONSE,
        causal_parent_context_identity=parent,
    ) is g.CausalRelationKindV2.POST_COMMIT_CAUSAL_CHILD
    assert g.classify_post_commit_relation_v2(
        window_kind=g.PublicWindowKindV1.MULTI_STEP_OBLIGATION,
        causal_parent_context_identity=parent,
    ) is g.CausalRelationKindV2.POST_COMMIT_CAUSAL_SUCCESSOR
    assert g.classify_post_commit_relation_v2(
        window_kind=g.PublicWindowKindV1.OTHER_PUBLIC,
        causal_parent_context_identity=None,
    ) is g.CausalRelationKindV2.INDEPENDENT_DECISION


def test_synthetic_or_bounded_evidence_cannot_satisfy_nested_obligation() -> None:
    obligation = g.REQUIRED_EVENT_OBLIGATIONS_V1[6]
    for source in ("GENERIC_TIMED_SESSION_CONTROLLER_TRACE_ONLY", "BOUNDED_REAL_PRODUCTION_TRACE_ONLY"):
        with pytest.raises(g.C8G1ContractError):
            g.RequiredEventWitnessV1(
                obligation.obligation_id,
                obligation.level,
                obligation.applicability,
                g.WitnessStatusV1.OBSERVED,
                (_id(source),),
                source,
            )


def test_baseline_registry_exact_round_trip_and_required_field_parity() -> None:
    registry = g.FullGameRegistryV1.canonical()
    assert [(item.cell_id, item.seed) for item in registry.baseline_cells] == [
        ("C8G-FG-000", 0),
        ("C8G-FG-001", 1),
        ("C8G-FG-049", 49),
    ]
    assert registry.sentinel_cells == ()
    assert g.FullGameRegistryV1.from_dict(registry.to_dict()) == registry
    assert registry.to_dict()["baseline_registry_identity"] == (
        g.C8_G1_BASELINE_REGISTRY_IDENTITY
    )


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.pop("registry_identity"),
        lambda value: value.__setitem__("unknown_authority", "x"),
        lambda value: value["baseline_cells"].pop(),
        lambda value: value["baseline_cells"].reverse(),
        lambda value: value["baseline_cells"].__setitem__(
            1, deepcopy(value["baseline_cells"][0])
        ),
        lambda value: value["baseline_cells"][0].__setitem__("seed", 2),
        lambda value: value["baseline_cells"][0].__setitem__("cell_id", "C8G-FG-099"),
        lambda value: value["baseline_cells"][0].__setitem__("seed", True),
    ],
    ids=[
        "missing",
        "extra",
        "missing-cell",
        "reorder",
        "duplicate",
        "wrong-seed",
        "wrong-cell-id",
        "bool-int-alias",
    ],
)
def test_baseline_registry_tamper_fails_closed(mutation: object) -> None:
    value = g.FullGameRegistryV1.canonical().to_dict()
    mutation(value)  # type: ignore[operator]
    with pytest.raises((g.C8G1ContractError, TypeError, ValueError)):
        g.FullGameRegistryV1.from_dict(value)


def test_sentinel_registry_rejects_extra_duplicate_reorder_and_baseline_seed() -> None:
    assert [item.seed for item in g.FullGameRegistryV1.canonical((2, 3)).sentinel_cells] == [2, 3]
    for seeds in ((3, 2), (2, 2), (0,), (1,), (49,), (100,)):
        with pytest.raises(g.C8G1ContractError):
            g.FullGameRegistryV1.canonical(seeds)


def test_formal_driver_uses_global_every_fourth_schedule_and_exact_ticks() -> None:
    decisions = [
        g.choose_formal_driver_action_v1(_driver_input(index))
        for index in range(1, 9)
    ]
    assert [item.marker.value for item in decisions] == [
        "ON_TIME",
        "ON_TIME",
        "ON_TIME",
        "TIMEOUT",
        "ON_TIME",
        "ON_TIME",
        "ON_TIME",
        "TIMEOUT",
    ]
    assert decisions[2].decision_tick == 299
    assert decisions[3].decision_tick == 400
    assert decisions[3].timeout_intent is True
    assert decisions[3].actual_timeout is True
    assert decisions[3].chosen_public_ordinal is None
    assert decisions[3].chosen_public_action_family is None
    assert decisions[3].choice_digest is None
    assert g.formal_driver_policy_descriptor_v1()["timeout_selection_authority"] == (
        "C_RESOLVER_RESULT_B_RECEIPT_E_EVIDENCE_ONLY"
    )


def test_formal_driver_progress_safe_public_family_rules_and_determinism() -> None:
    play = _driver_input(
        1,
        kind=g.PublicWindowKindV1.PLAY,
        families=("END_PLAY_PHASE", "USE_CARD", "EQUIP"),
    )
    optional = _driver_input(
        2,
        kind=g.PublicWindowKindV1.OPTIONAL_RESPONSE,
        families=("PASS", "RESPOND"),
    )
    assert g.choose_formal_driver_action_v1(play).chosen_public_action_family != (
        "END_PLAY_PHASE"
    )
    assert g.choose_formal_driver_action_v1(optional).chosen_public_action_family == (
        "RESPOND"
    )
    assert g.choose_formal_driver_action_v1(play) == g.choose_formal_driver_action_v1(play)
    later_deadline = replace(play, deadline_at=999)
    assert g.choose_formal_driver_action_v1(later_deadline).choice_digest == (
        g.choose_formal_driver_action_v1(play).choice_digest
    )
    assert set(g.formal_driver_policy_descriptor_v1()["forbidden_inputs"]) == {
        "private_payload",
        "card_identity",
        "hidden_choice",
        "rng",
        "wall_clock",
    }


def test_private_unresolved_timeout_intent_forces_on_time_and_records_skip() -> None:
    progress = g.open_public_ordinal_progress_v1(run_binding_identity="1"*64,
        execution_order_profile_identity="2"*64, opening_ref_identity="3"*64,
        opening_context_identity="4"*64, entry_step_index=3, global_window_index=4,
        deadline_at=400, phase="discard", turn_number=1, turn_player_id="p1", actor_id="p1",
        proposal_count=3, entry_pre_context_identity="5"*64, entry_pre_phase="play", entry_pre_actor_id="p1")
    decision = g.choose_formal_driver_action_v1(
        replace(_driver_input(
            4,
            kind=g.PublicWindowKindV1.PRIVATE_ORDINAL_TIMEOUT_UNRESOLVED,
            applicability=g.TimeoutApplicabilityV1.PRIVATE_ORDINAL_TIMEOUT_UNRESOLVED,
            families=("PRIVATE_ORDINAL",)*3,
        ), phase="discard", public_ordinal_progress=progress)
    )
    assert decision.marker is g.DriverDecisionMarkerV1.TIMEOUT_INTENT_SKIPPED_UNRESOLVED
    assert decision.actual_timeout is False
    assert decision.decision_tick == 399
    assert decision.chosen_public_ordinal == 0
    assert decision.skip_reason == "PRIVATE_ORDINAL_TIMEOUT_UNRESOLVED"


def test_n_a_context_naturally_appearing_on_timeout_slot_is_drift() -> None:
    for index in (1, 4):
        with pytest.raises(g.C8G1ContractError):
            g.choose_formal_driver_action_v1(
                _driver_input(
                    index,
                    applicability=g.TimeoutApplicabilityV1.NOT_APPLICABLE_IN_C6_NO_SKILL_8P,
                )
            )


def test_driver_rejects_noncanonical_action_order_and_bool_int_alias() -> None:
    actions = (
        g.PublicActionOptionV1(1, "A"),
        g.PublicActionOptionV1(0, "B"),
    )
    with pytest.raises(g.C8G1ContractError):
        g.FormalDriverInputV1(
            formal_seed=0,
            global_window_index=True,
            turn_number=1,
            turn_player_id="p1",
            actor_id="p1",
            phase="play",
            window_kind=g.PublicWindowKindV1.PLAY,
            deadline_at=100,
            timeout_applicability=g.TimeoutApplicabilityV1.APPLICABLE,
            proposal_order_identity=_id("wrong"),
            public_actions=actions,
        )


def test_sentinel_zero_gap_one_gap_and_multi_gap_selection() -> None:
    assert g.select_sentinels_v1(_gap_state(), ()).selected_seeds == ()
    one = g.select_sentinels_v1(
        _gap_state("FG-TIMER-07"),
        (
            g.SentinelCandidateV1(
                2,
                ("FG-TIMER-07",),
                g.CandidateScopeV1.ORDINARY_DISCOVERY,
            ),
        ),
        examined_seeds=(2,),
    )
    assert one.status is g.SentinelSelectionStatusV1.COMPLETE
    assert one.selected_seeds == (2,)
    multi = g.select_sentinels_v1(
        _gap_state("FG-TIMER-07", "FG-TIMER-08"),
        (
            g.SentinelCandidateV1(
                2,
                ("FG-TIMER-07", "FG-TIMER-08"),
                g.CandidateScopeV1.FORMAL_QUALITY_CANDIDATE,
            ),
        ),
        examined_seeds=(2,),
    )
    assert multi.selected_seeds == (2,)


def test_sentinel_canonical_order_exclusions_redundancy_and_exhaustion() -> None:
    with pytest.raises(g.C8G1ContractError):
        g.select_sentinels_v1(
            _gap_state("FG-TIMER-07"),
            (
                g.SentinelCandidateV1(3, ("FG-TIMER-07",), g.CandidateScopeV1.ORDINARY_DISCOVERY),
                g.SentinelCandidateV1(2, ("FG-TIMER-07",), g.CandidateScopeV1.ORDINARY_DISCOVERY),
            ),
            examined_seeds=(2, 3),
        )
    with pytest.raises(g.C8G1ContractError):
        g.SentinelCandidateV1(49, ("FG-TIMER-07",), g.CandidateScopeV1.ORDINARY_DISCOVERY)
    minimal = g.select_sentinels_v1(
        _gap_state("FG-TIMER-07", "FG-TIMER-08"),
        (
            g.SentinelCandidateV1(2, ("FG-TIMER-07",), g.CandidateScopeV1.ORDINARY_DISCOVERY),
            g.SentinelCandidateV1(3, ("FG-TIMER-07", "FG-TIMER-08"), g.CandidateScopeV1.ORDINARY_DISCOVERY),
        ),
        examined_seeds=(2, 3),
    )
    assert minimal.selected_seeds == (3,)
    blocked = g.select_sentinels_v1(
        _gap_state("FG-TIMER-08"),
        (
            g.SentinelCandidateV1(2, ("FG-TIMER-07",), g.CandidateScopeV1.ORDINARY_DISCOVERY),
        ),
        examined_seeds=tuple(
            seed for seed in range(100) if seed not in g.C8_G1_BASELINE_SEEDS
        ),
    )
    assert blocked.status is g.SentinelSelectionStatusV1.SENTINEL_DISCOVERY_BLOCKED
    assert blocked.remaining_gap_ids == ("FG-TIMER-08",)


def test_sentinel_discovery_requires_fresh_complete_baseline_derivation() -> None:
    registry = g.FullGameRegistryV1.canonical()
    implementation = _id("baseline-gap-authority")
    results = _good_matrix(registry, implementation)
    assert g.derive_baseline_gap_state_v1(
        results, expected_current_implementation_identity=implementation
    ).required_gap_ids == ()
    missing = tuple(
        replace(
            item,
            required_event_witnesses=_complete_witnesses(missing="FG-TIMER-08"),
        )
        for item in results
    )
    gap_state = g.derive_baseline_gap_state_v1(
        missing, expected_current_implementation_identity=implementation
    )
    assert gap_state.required_gap_ids == ("FG-TIMER-08",)
    with pytest.raises(g.C8G1ContractError):
        g.BaselineGapStateV1(
            tuple(item.cell_id for item in registry.baseline_cells),
            registry.registry_identity,
            (),
        )


def test_formal_quality_baseline_promotes_in_place_without_sentinel() -> None:
    registry = g.FullGameRegistryV1.canonical()
    implementation = _id("current-g1")
    decision = g.evaluate_promotion_v1(
        registry,
        _good_matrix(registry, implementation),
        expected_current_implementation_identity=implementation,
    )
    assert decision.status is g.PromotionStatusV1.PROMOTABLE_TO_FORMAL
    assert decision.required_event_gaps == ()
    assert decision.selected_cell_ids == ("C8G-FG-000", "C8G-FG-001", "C8G-FG-049")


def test_formal_quality_baseline_plus_selected_sentinel_promotes_as_one_registry() -> None:
    registry = g.FullGameRegistryV1.canonical((2,))
    implementation = _id("current-g1-sentinel")
    results = _good_matrix(registry, implementation)
    decision = g.evaluate_promotion_v1(
        registry,
        results,
        expected_current_implementation_identity=implementation,
    )
    assert decision.promotable_to_formal is True
    assert decision.selected_cell_ids[-1] == "C8G-FG-002"
    assert results[0].registry_identity == g.FullGameRegistryV1.canonical().registry_identity
    assert results[-1].registry_identity == g.FullGameRegistryV1.canonical((2,)).registry_identity
    assert decision.promoted_candidate_artifacts[-1] == (
        "C8G-FG-002",
        results[-1].artifact_identity,
    )


@pytest.mark.parametrize(
    ("overrides", "expected_reason"),
    [
        ({"current_implementation_identity": _id("wrong")}, "IMPLEMENTATION_IDENTITY_MISMATCH"),
        ({"timer_profile_id": "wrong-profile"}, "PROFILE_IDENTITY_MISMATCH"),
        ({"driver_policy_identity": _id("wrong-driver")}, "DRIVER_IDENTITY_MISMATCH"),
        ({"production_adapter_contract_identity": _id("wrong-e")}, "E_ADAPTER_IDENTITY_MISMATCH"),
        ({"strict_replay_verified": False}, "STRICT_REPLAY_NOT_VERIFIED"),
        ({"natural_terminal": False}, "NON_NATURAL_TERMINAL"),
        ({"safety_cap_hit": True, "run_status": g.CellRunStatusV1.FAILED_INCOMPLETE_SAFETY_CAP}, "SAFETY_CAP_HIT"),
        ({"artifact_scope": g.CandidateScopeV1.ORDINARY_DISCOVERY}, "NOT_FORMAL_QUALITY_CANDIDATE"),
        ({"artifact_scope": g.CandidateScopeV1.REPORT_ONLY}, "NOT_FORMAL_QUALITY_CANDIDATE"),
        ({"replay_scope": "BOUNDED_REAL_PRODUCTION_TRACE_ONLY"}, "WRONG_REPLAY_SCOPE"),
        ({"artifact_complete": False}, "ARTIFACT_INCOMPLETE"),
        ({"full_game": False}, "FULL_GAME_FORMAL_CELL_SCOPE_MISMATCH"),
    ],
    ids=[
        "wrong-implementation",
        "wrong-profile",
        "wrong-driver",
        "wrong-e-adapter",
        "missing-replay",
        "nonterminal",
        "safety-cap",
        "ordinary-discovery",
        "report-only",
        "bounded-trace",
        "incomplete-artifact",
        "full-game-spoof",
    ],
)
def test_promotion_gate_fails_closed(
    overrides: dict[str, object], expected_reason: str
) -> None:
    registry = g.FullGameRegistryV1.canonical()
    implementation = _id("promotion-current")
    results = list(_good_matrix(registry, implementation))
    results[0] = _good_result(0, registry, implementation, **overrides)
    decision = g.evaluate_promotion_v1(
        registry,
        results,
        expected_current_implementation_identity=implementation,
    )
    assert decision.status is g.PromotionStatusV1.NOT_PROMOTABLE
    assert expected_reason in decision.reason_codes


def test_event_gap_and_wrong_order_block_promotion() -> None:
    registry = g.FullGameRegistryV1.canonical()
    implementation = _id("event-gap")
    results = list(_good_matrix(registry, implementation))
    results[0] = replace(
        results[0], required_event_witnesses=_complete_witnesses(missing="FG-TIMER-07")
    )
    results[1] = replace(
        results[1], required_event_witnesses=_complete_witnesses(missing="FG-TIMER-07")
    )
    results[2] = replace(
        results[2], required_event_witnesses=_complete_witnesses(missing="FG-TIMER-07")
    )
    decision = g.evaluate_promotion_v1(
        registry, results, expected_current_implementation_identity=implementation
    )
    assert "REQUIRED_EVENT_GAP" in decision.reason_codes
    assert "FG-TIMER-07" in decision.required_event_gaps
    reordered = (results[1], results[0], results[2])
    decision = g.evaluate_promotion_v1(
        registry, reordered, expected_current_implementation_identity=implementation
    )
    assert "ORDERED_REGISTRY_MISMATCH" in decision.reason_codes


def test_cell_and_matrix_flags_are_fresh_derived_not_serialized_authority() -> None:
    registry = g.FullGameRegistryV1.canonical()
    implementation = _id("aggregate")
    results = _good_matrix(registry, implementation)
    flags = results[0].proof_flags()
    assert flags["CELL_PRODUCTION_REACHABLE"] is True
    assert flags["CELL_CANONICAL_C6_MODE_PROVEN"] is True
    assert flags["CELL_PUBLIC_ADAPTER_AUTHORITY_PROVEN"] is True
    assert flags["CELL_CONTROLLER_AUTHORITY_PROVEN"] is True
    assert flags["CELL_FULL_GAME_COMPOSITION_PROVEN"] is True
    aggregate = g.derive_matrix_aggregate_v1(
        registry,
        results,
        expected_current_implementation_identity=implementation,
    )
    assert aggregate.matrix_status is (
        g.MatrixStatusV1.PASSED_PROVISIONAL_PENDING_EXTERNAL_AUDIT
    )
    assert aggregate.failed_cell_ids == ()
    with pytest.raises(g.C8G1ContractError):
        g.FullGameResultV1.from_dict({"strict_replay_verified": True, "passed": True})
    with pytest.raises(g.C8G1ContractError):
        replace(results[0], _authority_token=None)
    with pytest.raises(g.C8G1ContractError):
        g.PromotionDecisionV1.from_dict({"promotable_to_formal": True})
    with pytest.raises(g.C8G1ContractError):
        g.FullGameMatrixAggregateV1.from_dict({"ready": True, "coverage_complete": True})


def test_progress_round_trip_has_no_serialized_ready_or_pass_authority() -> None:
    registry = g.FullGameRegistryV1.canonical()
    progress = g.FullGameProgressV1(
        current_implementation_identity=_id("progress"),
        registry=registry,
        completed_cells=(
            g.FullGameCellArtifactRefV1(
                "C8G-FG-000",
                _id("cell-0-replay"),
                _id("cell-0-artifact"),
                _id("cell-0-bytes"),
            ),
        ),
        failed_cell_ids=(),
        replay_execution_status="PARTIAL",
        promotion_status=g.PromotionStatusV1.NOT_PROMOTABLE,
    )
    value = progress.to_dict()
    assert "ready" not in value and "passed" not in value
    assert g.FullGameProgressV1.from_dict(value) == progress
    value["ready"] = True
    with pytest.raises(g.C8G1ContractError):
        g.FullGameProgressV1.from_dict(value)
    with pytest.raises(g.C8G1ContractError):
        g.FullGameProgressV1(
            current_implementation_identity=_id("progress"),
            registry=registry,
            completed_cells=(
                g.FullGameCellArtifactRefV1(
                    "C8G-FG-001",
                    _id("wrong-prefix-replay"),
                    _id("wrong-prefix-artifact"),
                    _id("wrong-prefix-bytes"),
                ),
            ),
            failed_cell_ids=(),
            replay_execution_status="PARTIAL",
            promotion_status=g.PromotionStatusV1.NOT_PROMOTABLE,
        )


# Recorded public inputs from the prior successful real G2 smoke; no gameplay.
HISTORICAL_DRIVER_GOLDEN = {'source_sha256': '90d1f936e7f92a09110f8bbdb0d5aebeadbec4ee45e0bda0cbd8c6488a572589', 'policy': {'schema': 'sgs-c8-g-formal-driver-policy-v2', 'contract_version': 2, 'policy_id': 'c8-g-public-context-ordinal-periodic-timeout-v2', 'global_window_index_base': 1, 'timeout_modulo': 4, 'timeout_remainder': 0, 'on_time_tick': 'deadline_at-1', 'timeout_tick': 'deadline_at', 'inputs': ['formal_seed', 'global_window_index', 'turn_number', 'public_actor_and_turn_player', 'phase', 'window_kind', 'proposal_count', 'ordered_public_ordinal_action_family'], 'forbidden_inputs': ['private_payload', 'card_identity', 'hidden_choice', 'rng', 'wall_clock'], 'unresolved_timeout': 'FORCE_ON_TIME_AND_RECORD', 'driver_choice_scope': 'ON_TIME_ONLY', 'timeout_selection_authority': 'C_RESOLVER_RESULT_B_RECEIPT_E_EVIDENCE_ONLY', 'same_tick_chain_cap': 8}, 'policy_identity': '62b85ab0a7ffd95603ad85ca5dd2173d85546a1b92b6e2514464eebe9bfa37d5', 'vectors': [{'input': {'actor_id': 'p5', 'deadline_at': 100, 'formal_seed': 0, 'global_window_index': 1, 'phase': 'prepare', 'proposal_order_identity': 'b68eb3f2bced9b3df7718aff9472691d8c4a8e891cfc8e5b3e4626f453b4b751', 'public_actions': [{'public_action_family': 'MANDATORY_ACTION', 'public_ordinal': 0}], 'timeout_applicability': 'APPLICABLE', 'turn_number': 1, 'turn_player_id': 'p5', 'window_kind': 'OTHER_PUBLIC'}, 'decision': {'policy_id': 'c8-g-public-context-ordinal-periodic-timeout-v2', 'policy_identity': '62b85ab0a7ffd95603ad85ca5dd2173d85546a1b92b6e2514464eebe9bfa37d5', 'driver_input_identity': '2114a1ae1d0aa93f49f72b16dc80111ae50aacf4318d1a10513d2c9da5bc7f10', 'timeout_intent': False, 'actual_timeout': False, 'marker': 'ON_TIME', 'decision_tick': 99, 'chosen_public_ordinal': 0, 'chosen_public_action_family': 'MANDATORY_ACTION', 'choice_digest': 'e257df089d4bae11d14eaa7fc17cc816c355bc95fa7185f094e99bb791e7dabb', 'skip_reason': None}}, {'input': {'actor_id': 'p5', 'deadline_at': 199, 'formal_seed': 0, 'global_window_index': 2, 'phase': 'judgment', 'proposal_order_identity': 'b68eb3f2bced9b3df7718aff9472691d8c4a8e891cfc8e5b3e4626f453b4b751', 'public_actions': [{'public_action_family': 'MANDATORY_ACTION', 'public_ordinal': 0}], 'timeout_applicability': 'APPLICABLE', 'turn_number': 1, 'turn_player_id': 'p5', 'window_kind': 'OTHER_PUBLIC'}, 'decision': {'policy_id': 'c8-g-public-context-ordinal-periodic-timeout-v2', 'policy_identity': '62b85ab0a7ffd95603ad85ca5dd2173d85546a1b92b6e2514464eebe9bfa37d5', 'driver_input_identity': 'e235944b45f683f6b9c54d5bc4dcf5645258a9929d9e3879624c9ae3d67d12e2', 'timeout_intent': False, 'actual_timeout': False, 'marker': 'ON_TIME', 'decision_tick': 198, 'chosen_public_ordinal': 0, 'chosen_public_action_family': 'MANDATORY_ACTION', 'choice_digest': '7155d757360a832fbfeb647e232786a9b8d128a174f31e006ba6ffd188c3d569', 'skip_reason': None}}, {'input': {'actor_id': 'p5', 'deadline_at': 298, 'formal_seed': 0, 'global_window_index': 3, 'phase': 'draw', 'proposal_order_identity': 'b68eb3f2bced9b3df7718aff9472691d8c4a8e891cfc8e5b3e4626f453b4b751', 'public_actions': [{'public_action_family': 'MANDATORY_ACTION', 'public_ordinal': 0}], 'timeout_applicability': 'APPLICABLE', 'turn_number': 1, 'turn_player_id': 'p5', 'window_kind': 'OTHER_PUBLIC'}, 'decision': {'policy_id': 'c8-g-public-context-ordinal-periodic-timeout-v2', 'policy_identity': '62b85ab0a7ffd95603ad85ca5dd2173d85546a1b92b6e2514464eebe9bfa37d5', 'driver_input_identity': '343e03484df93d26dc5ec5adf6da18c3447f44bb241bc1807f5a03918206f8d9', 'timeout_intent': False, 'actual_timeout': False, 'marker': 'ON_TIME', 'decision_tick': 297, 'chosen_public_ordinal': 0, 'chosen_public_action_family': 'MANDATORY_ACTION', 'choice_digest': '8a73da4661c3a063ef883dd8c19324315b043102b3031ba58c48943d982f1a28', 'skip_reason': None}}, {'input': {'actor_id': 'p5', 'deadline_at': 397, 'formal_seed': 0, 'global_window_index': 4, 'phase': 'play', 'proposal_order_identity': '48d49d94de2117afd955b1db1f48c1991ab06edab89ba10c922878d9d2a23175', 'public_actions': [{'public_action_family': 'PROGRESS_ACTION', 'public_ordinal': 0}, {'public_action_family': 'PROGRESS_ACTION', 'public_ordinal': 1}, {'public_action_family': 'PROGRESS_ACTION', 'public_ordinal': 2}, {'public_action_family': 'PROGRESS_ACTION', 'public_ordinal': 3}, {'public_action_family': 'PROGRESS_ACTION', 'public_ordinal': 4}, {'public_action_family': 'PROGRESS_ACTION', 'public_ordinal': 5}, {'public_action_family': 'PROGRESS_ACTION', 'public_ordinal': 6}, {'public_action_family': 'PROGRESS_ACTION', 'public_ordinal': 7}, {'public_action_family': 'PROGRESS_ACTION', 'public_ordinal': 8}, {'public_action_family': 'PROGRESS_ACTION', 'public_ordinal': 9}, {'public_action_family': 'PROGRESS_ACTION', 'public_ordinal': 10}, {'public_action_family': 'PROGRESS_ACTION', 'public_ordinal': 11}, {'public_action_family': 'PROGRESS_ACTION', 'public_ordinal': 12}, {'public_action_family': 'PROGRESS_ACTION', 'public_ordinal': 13}, {'public_action_family': 'PROGRESS_ACTION', 'public_ordinal': 14}, {'public_action_family': 'END_PLAY_PHASE', 'public_ordinal': 15}], 'timeout_applicability': 'APPLICABLE', 'turn_number': 1, 'turn_player_id': 'p5', 'window_kind': 'PLAY'}, 'decision': {'policy_id': 'c8-g-public-context-ordinal-periodic-timeout-v2', 'policy_identity': '62b85ab0a7ffd95603ad85ca5dd2173d85546a1b92b6e2514464eebe9bfa37d5', 'driver_input_identity': '102f11e82089713b13bd363fc89140f74b5f7c9d5ab3e1b43862c55b0cff2369', 'timeout_intent': True, 'actual_timeout': True, 'marker': 'TIMEOUT', 'decision_tick': 397, 'chosen_public_ordinal': None, 'chosen_public_action_family': None, 'choice_digest': None, 'skip_reason': None}}, {'input': {'actor_id': 'p5', 'deadline_at': 497, 'formal_seed': 0, 'global_window_index': 5, 'phase': 'discard', 'proposal_order_identity': '0f8a74835db047d9582bfb941146554d28689259c96c9029cad47a2952138e2a', 'public_actions': [{'public_action_family': 'PRIVATE_ORDINAL', 'public_ordinal': 0}, {'public_action_family': 'PRIVATE_ORDINAL', 'public_ordinal': 1}, {'public_action_family': 'PRIVATE_ORDINAL', 'public_ordinal': 2}, {'public_action_family': 'PRIVATE_ORDINAL', 'public_ordinal': 3}, {'public_action_family': 'PRIVATE_ORDINAL', 'public_ordinal': 4}, {'public_action_family': 'PRIVATE_ORDINAL', 'public_ordinal': 5}], 'timeout_applicability': 'PRIVATE_ORDINAL_TIMEOUT_UNRESOLVED', 'turn_number': 1, 'turn_player_id': 'p5', 'window_kind': 'PRIVATE_ORDINAL_TIMEOUT_UNRESOLVED'}, 'decision': {'policy_id': 'c8-g-public-context-ordinal-periodic-timeout-v2', 'policy_identity': '62b85ab0a7ffd95603ad85ca5dd2173d85546a1b92b6e2514464eebe9bfa37d5', 'driver_input_identity': '2f6c2c5fddc22dfe91beaa668ebe34a63c31ae521f352e5ec80c5f6e8af658db', 'timeout_intent': False, 'actual_timeout': False, 'marker': 'ON_TIME', 'decision_tick': 496, 'chosen_public_ordinal': 5, 'chosen_public_action_family': 'PRIVATE_ORDINAL', 'choice_digest': 'fa21b61604f9606b7f11a8a56a00b3c67ab09f12204f2d37815f126aa1b33701', 'skip_reason': None}}, {'input': {'actor_id': 'p5', 'deadline_at': 596, 'formal_seed': 0, 'global_window_index': 6, 'phase': 'discard', 'proposal_order_identity': '76610762b607c8143821d1aaf7ba633cc2d3df4bb5d646d4354c51eeb5c53a35', 'public_actions': [{'public_action_family': 'PRIVATE_ORDINAL', 'public_ordinal': 0}, {'public_action_family': 'PRIVATE_ORDINAL', 'public_ordinal': 1}, {'public_action_family': 'PRIVATE_ORDINAL', 'public_ordinal': 2}, {'public_action_family': 'PRIVATE_ORDINAL', 'public_ordinal': 3}, {'public_action_family': 'PRIVATE_ORDINAL', 'public_ordinal': 4}, {'public_action_family': 'PRIVATE_ORDINAL', 'public_ordinal': 5}, {'public_action_family': 'PRIVATE_ORDINAL', 'public_ordinal': 6}], 'timeout_applicability': 'PRIVATE_ORDINAL_TIMEOUT_UNRESOLVED', 'turn_number': 1, 'turn_player_id': 'p5', 'window_kind': 'PRIVATE_ORDINAL_TIMEOUT_UNRESOLVED'}, 'decision': {'policy_id': 'c8-g-public-context-ordinal-periodic-timeout-v2', 'policy_identity': '62b85ab0a7ffd95603ad85ca5dd2173d85546a1b92b6e2514464eebe9bfa37d5', 'driver_input_identity': 'b4a7b3654e195e0764b31227751e67e41758a3c44102cb6fd72bf38c4b5fb9c0', 'timeout_intent': False, 'actual_timeout': False, 'marker': 'ON_TIME', 'decision_tick': 595, 'chosen_public_ordinal': 6, 'chosen_public_action_family': 'PRIVATE_ORDINAL', 'choice_digest': '87b96627d2406bb93abf310381fdb0546544bcf812a61d49a0508e6534d995eb', 'skip_reason': None}}, {'input': {'actor_id': 'p5', 'deadline_at': 695, 'formal_seed': 0, 'global_window_index': 7, 'phase': 'end', 'proposal_order_identity': 'b68eb3f2bced9b3df7718aff9472691d8c4a8e891cfc8e5b3e4626f453b4b751', 'public_actions': [{'public_action_family': 'MANDATORY_ACTION', 'public_ordinal': 0}], 'timeout_applicability': 'APPLICABLE', 'turn_number': 1, 'turn_player_id': 'p5', 'window_kind': 'OTHER_PUBLIC'}, 'decision': {'policy_id': 'c8-g-public-context-ordinal-periodic-timeout-v2', 'policy_identity': '62b85ab0a7ffd95603ad85ca5dd2173d85546a1b92b6e2514464eebe9bfa37d5', 'driver_input_identity': '457a38d47564a2f20cb50cb9ddb3732f7fc8663ac5830da586bd03b13c154aac', 'timeout_intent': False, 'actual_timeout': False, 'marker': 'ON_TIME', 'decision_tick': 694, 'chosen_public_ordinal': 0, 'chosen_public_action_family': 'MANDATORY_ACTION', 'choice_digest': '15348d205ffef0fce2bce4d7356538e95c047d2e4fbe529d4442f2975943496c', 'skip_reason': None}}, {'input': {'actor_id': 'p6', 'deadline_at': 794, 'formal_seed': 0, 'global_window_index': 8, 'phase': 'prepare', 'proposal_order_identity': 'b68eb3f2bced9b3df7718aff9472691d8c4a8e891cfc8e5b3e4626f453b4b751', 'public_actions': [{'public_action_family': 'MANDATORY_ACTION', 'public_ordinal': 0}], 'timeout_applicability': 'APPLICABLE', 'turn_number': 2, 'turn_player_id': 'p6', 'window_kind': 'OTHER_PUBLIC'}, 'decision': {'policy_id': 'c8-g-public-context-ordinal-periodic-timeout-v2', 'policy_identity': '62b85ab0a7ffd95603ad85ca5dd2173d85546a1b92b6e2514464eebe9bfa37d5', 'driver_input_identity': '86aadbfdbf7e2bad9eeb99277e9b1248f436f5dfa7b642b6cc1309284df6c350', 'timeout_intent': True, 'actual_timeout': True, 'marker': 'TIMEOUT', 'decision_tick': 794, 'chosen_public_ordinal': None, 'chosen_public_action_family': None, 'choice_digest': None, 'skip_reason': None}}]}

def test_driver_v2_history_golden_vectors_preserved():
    from scripts.sgs_engine import c8_timed_8p_full_game_replay_v1 as r
    assert g.C8_G1_DRIVER_MATERIAL_VERSION == 3
    assert g.C8_G1_DRIVER_POLICY_IDENTITY != HISTORICAL_DRIVER_GOLDEN["policy_identity"]
    preserved = 0
    for vector in HISTORICAL_DRIVER_GOLDEN["vectors"]:
        raw = {**vector["input"], "public_ordinal_progress": None}
        inp = r.driver_input_from_dict_v3(raw)
        if inp.phase == "discard":
            with pytest.raises(g.C8G1ContractError, match="DRIVER_LIVENESS_UNRESOLVED"):
                g.choose_formal_driver_action_v1(inp)
            continue
        fresh = r.driver_decision_dict_v3(inp)
        for key in ("timeout_intent", "actual_timeout", "marker", "decision_tick", "chosen_public_ordinal",
                    "chosen_public_action_family", "choice_digest", "skip_reason"):
            r.exact_equal_v3(fresh[key], vector["decision"][key], "legacy ordinary selection "+key)
        preserved += 1
    assert preserved == 6
