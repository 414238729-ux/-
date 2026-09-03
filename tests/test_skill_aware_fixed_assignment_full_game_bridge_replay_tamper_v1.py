# -*- coding: utf-8 -*-
"""BRIDGE-D deep tamper model with attacker-recomputed outer identities."""

from __future__ import annotations

from copy import deepcopy

import pytest

from scripts.sgs_engine.skill_aware_fixed_assignment_full_game_bridge_replay import (
    BridgeFullGameReplayV1,
    BridgeReplayDivergenceError,
    BridgeReplayIdentityError,
    record_bounded_skill_aware_fixed_assignment_bridge_replay_v1,
    recompute_bridge_replay_identities_v1,
    reexecute_skill_aware_fixed_assignment_bridge_replay_v1,
)


@pytest.fixture(scope="module")
def source() -> dict[str, object]:
    return record_bounded_skill_aware_fixed_assignment_bridge_replay_v1(
        general_key="zhugezhan",
        seat_assignment="GENERAL_AS_P1",
        seed=0,
        max_steps=25,
        cell_id="BRIDGE-D-ZHUGEZHAN-P1-SEED-0",
    ).to_dict()


def _rehash(payload: dict[str, object]) -> dict[str, object]:
    return recompute_bridge_replay_identities_v1(payload)


def _must_fail(payload: dict[str, object]) -> None:
    with pytest.raises((BridgeReplayDivergenceError, BridgeReplayIdentityError)):
        loaded = BridgeFullGameReplayV1.from_dict(_rehash(payload))
        reexecute_skill_aware_fixed_assignment_bridge_replay_v1(loaded)


@pytest.mark.parametrize(
    "field,value",
    (
        ("schema", "legacy-replay-v1"),
        ("replay_version", 2),
        ("contract_id", "forged-contract"),
        ("contract_identity", "0" * 64),
        ("ruleset_identity", "0" * 64),
        ("bridge_mode_profile_identity", "0" * 64),
        ("formal_duel_profile_identity", "0" * 64),
        ("deck_identity", "0" * 64),
        ("general_registry_identity", "0" * 64),
        ("bridge_skill_registry_identity", "0" * 64),
        ("bridge_authority_profile_identity", "0" * 64),
        ("controller_id", "forged-controller"),
        ("controller_version", 2),
        ("cell_id", "FORGED-CELL"),
        ("seed", 1),
    ),
)
def test_static_and_identity_tamper_fails_with_outer_hashes_recomputed(
    source: dict[str, object], field: str, value: object
) -> None:
    attacked = deepcopy(source)
    attacked[field] = value
    _must_fail(attacked)


def test_assignment_stats_skills_dynamic_grant_and_pojiang_forgery_fail(
    source: dict[str, object],
) -> None:
    attacks = []
    wrong_seat = deepcopy(source)
    wrong_seat["initialization"]["assignment"]["seat_assignment"] = "GENERAL_AS_P2"
    attacks.append(wrong_seat)
    wrong_general = deepcopy(source)
    wrong_general["initialization"]["assignment"]["general_key"] = "shamoke"
    attacks.append(wrong_general)
    missing_assignment = deepcopy(source)
    missing_assignment["initialization"]["assignment"]["participants"].pop()
    attacks.append(missing_assignment)
    extra_general = deepcopy(source)
    extra_general["initialization"]["assignment"]["participants"].append(
        deepcopy(extra_general["initialization"]["assignment"]["participants"][0])
    )
    attacks.append(extra_general)
    wrong_stats = deepcopy(source)
    wrong_stats["initialization"]["assignment"]["participants"][0]["hp"] += 1
    attacks.append(wrong_stats)
    wrong_skills = deepcopy(source)
    wrong_skills["initialization"]["base_skill_derivation"]["base_skill_ids"] = []
    attacks.append(wrong_skills)
    pojiang = deepcopy(source)
    pojiang["initialization"]["base_skill_derivation"]["base_skill_ids"].append(
        "sgs_skill_pojiang"
    )
    attacks.append(pojiang)
    dynamic = deepcopy(source)
    dynamic["initialization"]["initial_dynamic_reconcile_result"]["dynamic_grants"][
        "p1"
    ] = [{"target_skill_id": "sgs_skill_weimu", "active": True}]
    attacks.append(dynamic)
    dual = deepcopy(source)
    dual["initialization"]["initial_dynamic_reconcile_result"][
        "player_effective_skills"
    ]["p1"].extend(["sgs_skill_weimu", "sgs_skill_mingzhe"])
    attacks.append(dual)
    for attacked in attacks:
        _must_fail(attacked)


def test_initialization_participants_rng_first_player_public_and_policy_tamper_fail(
    source: dict[str, object],
) -> None:
    attacks = []
    participant_order = deepcopy(source)
    participant_order["initialization"]["participant_ids"].reverse()
    attacks.append(participant_order)
    base_derivation = deepcopy(source)
    base_derivation["initialization"]["base_skill_derivation"]["general_player_id"] = "p2"
    attacks.append(base_derivation)
    dynamic_policy = deepcopy(source)
    dynamic_policy["initialization"]["dynamic_derivation_policy"]["source_skill_id"] = (
        "sgs_skill_pojiang"
    )
    attacks.append(dynamic_policy)
    qianchong = deepcopy(source)
    qianchong["initialization"]["initial_dynamic_reconcile_result"][
        "runtime_identity"
    ] = "0" * 64
    attacks.append(qianchong)
    first_player = deepcopy(source)
    current_first = first_player["initialization"]["first_player_id"]
    first_player["initialization"]["first_player_id"] = (
        "p1" if current_first == "p2" else "p2"
    )
    attacks.append(first_player)
    rng_state = deepcopy(source)
    rng_state["initialization"]["initial_rng_authority"]["post_initialization_state"][
        "call_count"
    ] += 1
    attacks.append(rng_state)
    rng_hash = deepcopy(source)
    rng_hash["initialization"]["initial_rng_authority"][
        "post_initialization_state_identity"
    ] = "0" * 64
    attacks.append(rng_hash)
    public = deepcopy(source)
    public["initialization"]["initial_public_state_commitment"] = "0" * 64
    attacks.append(public)
    initial_state = deepcopy(source)
    initial_state["initialization"]["initial_authoritative_state_hash"] = "0" * 64
    attacks.append(initial_state)
    for attacked in attacks:
        _must_fail(attacked)


@pytest.mark.parametrize(
    "flag",
    ("analysis_only", "fixture_applied", "premutation_applied", "manual_event_injection"),
)
def test_forbidden_initialization_marker_fails_closed(
    source: dict[str, object], flag: str
) -> None:
    attacked = deepcopy(source)
    attacked["initialization"][flag] = True
    _must_fail(attacked)


def test_decision_remove_duplicate_reorder_and_chosen_action_tamper_fail(
    source: dict[str, object],
) -> None:
    attacks = []
    removed = deepcopy(source)
    removed["decisions"].pop(3)
    removed["production_authority_trace"].pop(3)
    attacks.append(removed)
    duplicated = deepcopy(source)
    duplicated["decisions"].insert(3, deepcopy(duplicated["decisions"][2]))
    duplicated["production_authority_trace"].insert(
        3, deepcopy(duplicated["production_authority_trace"][2])
    )
    attacks.append(duplicated)
    reordered = deepcopy(source)
    reordered["decisions"][3], reordered["decisions"][4] = (
        reordered["decisions"][4],
        reordered["decisions"][3],
    )
    attacks.append(reordered)
    chosen = deepcopy(source)
    decision = next(
        item for item in chosen["decisions"] if len(item["legal_action_projections"]) > 1
    )
    alternative = next(
        item
        for item in decision["legal_action_projections"]
        if item["projection"]["action_id"] != decision["chosen_action_id"]
    )
    decision["chosen_action_id"] = alternative["projection"]["action_id"]
    decision["chosen_semantic_projection"] = alternative
    attacks.append(chosen)
    for attacked in attacks:
        _must_fail(attacked)


def test_legal_set_public_context_revision_and_opaque_ordinal_tamper_fail(
    source: dict[str, object],
) -> None:
    attacks = []
    removed = deepcopy(source)
    removed["decisions"][0]["legal_action_projections"].pop()
    removed["decisions"][0]["legal_set_identity"] = "0" * 64
    attacks.append(removed)
    extra = deepcopy(source)
    extra["decisions"][0]["legal_action_projections"].append(
        deepcopy(extra["decisions"][0]["legal_action_projections"][0])
    )
    attacks.append(extra)
    semantics = deepcopy(source)
    semantics["decisions"][0]["legal_action_projections"][0]["projection"][
        "operation"
    ] = "end_turn"
    attacks.append(semantics)
    context = deepcopy(source)
    current_actor = context["decisions"][0]["public_context"]["actor_id"]
    context["decisions"][0]["public_context"]["actor_id"] = (
        "p1" if current_actor == "p2" else "p2"
    )
    attacks.append(context)
    revision = deepcopy(source)
    revision["decisions"][0]["state_revision_before"] += 1
    attacks.append(revision)
    opaque = deepcopy(source)
    opaque_decision = next(
        item
        for item in opaque["decisions"]
        if item["chosen_semantic_projection"]["projection_kind"]
        == "private_player_choice"
    )
    opaque_decision["chosen_semantic_projection"]["projection"]["ordinal"] += 1
    attacks.append(opaque)
    for attacked in attacks:
        _must_fail(attacked)


def test_private_card_random_event_skill_and_production_trace_deep_tamper_fail(
    source: dict[str, object],
) -> None:
    attacks = []
    private_card = deepcopy(source)
    selection = private_card["authoritative_private"]["private_skill_selections"][0]
    selection["selected_card_ids"][0] = selection["remaining_top_order"][0]
    attacks.append(private_card)
    initial_hand = deepcopy(source)
    hand = initial_hand["authoritative_private"]["initial_private_state"]
    hand["participant_hands"][0]["card_instance_ids"][0] = "forged-card"
    material = {
        "participant_hands": hand["participant_hands"],
        "draw_pile_order": hand["draw_pile_order"],
    }
    from scripts.sgs_engine.replay import sha256_value

    hand["private_state_identity"] = sha256_value(material)
    attacks.append(initial_hand)
    random_result = deepcopy(source)
    random_result["random_consumptions"][0]["result"] = "forged"
    attacks.append(random_result)
    random_order = deepcopy(source)
    random_order["random_consumptions"][0], random_order["random_consumptions"][1] = (
        random_order["random_consumptions"][1],
        random_order["random_consumptions"][0],
    )
    attacks.append(random_order)
    random_count = deepcopy(source)
    random_count["random_consumptions"][0]["after_call_index"] += 1
    attacks.append(random_count)
    event_removed = deepcopy(source)
    event_removed["events"].pop()
    attacks.append(event_removed)
    event_altered = deepcopy(source)
    event_altered["events"][0]["payload"]["reason"] = "forged"
    attacks.append(event_altered)
    skill_removed = deepcopy(source)
    skill_removed["skill_decision_authority_trace"].pop()
    attacks.append(skill_removed)
    production = deepcopy(source)
    production["production_authority_trace"][0]["runtime_identity_after"] = "0" * 64
    attacks.append(production)
    final_state = deepcopy(source)
    final_state["decisions"][-1]["state_identity_after"] = "0" * 64
    attacks.append(final_state)
    continuation = deepcopy(source)
    continuation["production_authority_trace"][0]["continuation_identity_after"] = "0" * 64
    attacks.append(continuation)
    ledger = deepcopy(source)
    ledger["production_authority_trace"][0][
        "movement_ledger_end_identity_after"
    ] = "0" * 64
    attacks.append(ledger)
    outcome = deepcopy(source)
    outcome["outcome"]["step_count"] += 1
    attacks.append(outcome)
    for attacked in attacks:
        _must_fail(attacked)


def test_explicit_records_execution_and_replay_identity_tamper_fail(
    source: dict[str, object],
) -> None:
    for field in ("records_identity", "execution_identity", "replay_identity"):
        attacked = deepcopy(source)
        attacked[field] = "0" * 64
        with pytest.raises((BridgeReplayIdentityError, BridgeReplayDivergenceError)):
            BridgeFullGameReplayV1.from_dict(attacked)
