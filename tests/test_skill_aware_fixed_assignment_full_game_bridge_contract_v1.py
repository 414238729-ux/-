# -*- coding: utf-8 -*-
"""BRIDGE-A contract/type tests; no production game or replay is executed."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from itertools import product

import pytest

from scripts.sgs_engine import skill_aware_fixed_assignment_full_game_bridge as bridge


def _valid_replay_descriptor() -> dict[str, object]:
    sha = "a" * 64
    return {
        "schema": bridge.REPLAY_SCHEMA,
        "replay_version": bridge.REPLAY_VERSION,
        "contract_id": bridge.CONTRACT_ID,
        "contract_identity": bridge.PROPOSED_BRIDGE_CONTRACT_IDENTITY,
        "implementation_identity": sha,
        "ruleset_identity": sha,
        "bridge_mode_profile_identity": bridge.BRIDGE_MODE_PROFILE_IDENTITY,
        "formal_duel_profile_identity": bridge.FORMAL_DUEL_PROFILE_IDENTITY,
        "deck_identity": bridge.DECK_IDENTITY,
        "general_registry_identity": bridge.GENERAL_REGISTRY_IDENTITY,
        "bridge_skill_registry_identity": bridge.BRIDGE_SKILL_REGISTRY_IDENTITY,
        "bridge_authority_profile_identity": bridge.BRIDGE_AUTHORITY_PROFILE_IDENTITY,
        "controller_id": bridge.CONTROLLER_ID,
        "controller_version": bridge.CONTROLLER_VERSION,
        "cell_id": "B18-001",
        "seed": 0,
        "initialization": {},
        "decisions": [],
        "random_consumptions": [],
        "events": [],
        "production_authority_trace": [],
        "skill_decision_authority_trace": [],
        "outcome": {},
        "authoritative_private": {},
        "records_identity": sha,
        "execution_identity": sha,
        "replay_identity": sha,
    }


def test_exact_bridge_identifiers() -> None:
    assert bridge.BRIDGE_NAME == (
        "POST_AUTHORITATIVE_GENERAL_BATCH_V1_SKILL_AWARE_FIXED_ASSIGNMENT_"
        "FULL_GAME_BRIDGE_V1"
    )
    assert bridge.CONTRACT_ID == (
        "post-authoritative-general-batch-v1-skill-aware-fixed-assignment-"
        "full-game-bridge-v1"
    )
    assert bridge.MODE_ID == "skill-aware-fixed-assignment-formal-duel-v1"
    assert bridge.REPLAY_SCHEMA == (
        "sgs-skill-aware-fixed-assignment-full-game-bridge-replay-v1"
    )
    assert bridge.CONTROLLER_ID == (
        "skill-aware-fixed-assignment-acceptance-controller-v1"
    )
    assert bridge.CONTROLLER_VERSION == 1
    assert bridge.CONTRACT_VERSION == 1
    assert bridge.REPLAY_VERSION == 1


def test_frozen_input_identities_are_exact() -> None:
    assert bridge.FORMAL_DUEL_PROFILE_IDENTITY == (
        "9a7b0e9f45c05292a207c500e5b024a77d97b4a6c9446230d81d357c7b514283"
    )
    assert bridge.DECK_IDENTITY == (
        "e490631698e6b7695c6a9b3ad0c355e421ccfafab696e5b3a97418c9ec80f38b"
    )
    assert bridge.GENERAL_REGISTRY_IDENTITY == (
        "409ad3daa5169e9c60c5e926ec309ee6b6b0ea2f8830f16ce5928a86d10a9a09"
    )


def test_exact_general_allowlist_and_source_payloads() -> None:
    assert bridge.GENERAL_ALLOWLIST == ("shamoke", "zhugezhan", "wangyuanji")
    actual = {
        item.general_key: (
            item.gender,
            item.starting_hp,
            item.max_hp,
            item.base_skill_ids,
        )
        for item in bridge.GENERAL_ALLOWLIST_DESCRIPTORS
    }
    assert actual == {
        "shamoke": ("male", 4, 4, ("sgs_skill_jili",)),
        "zhugezhan": (
            "male",
            3,
            3,
            ("sgs_skill_zuilun", "sgs_skill_fuyin"),
        ),
        "wangyuanji": (
            "female",
            3,
            3,
            ("sgs_skill_qianchong", "sgs_skill_shangjian"),
        ),
    }
    for item in bridge.GENERAL_ALLOWLIST_DESCRIPTORS:
        source = item.to_dict()["canonical_source_payload"]
        assert source["general_key"] == item.general_key
        assert source["profile_identity"] == item.profile_identity
        assert tuple(source["skill_ids"]) == item.base_skill_ids


def test_unknown_general_rejected() -> None:
    with pytest.raises(bridge.BridgeContractError, match="未知General"):
        bridge.general_descriptor("pojiang_owner")


def test_exact_bridge_skill_allowlist_and_dedicated_identity() -> None:
    expected = (
        "sgs_skill_fuyin",
        "sgs_skill_jili",
        "sgs_skill_mingzhe",
        "sgs_skill_qianchong",
        "sgs_skill_shangjian",
        "sgs_skill_weimu",
        "sgs_skill_zuilun",
    )
    assert bridge.BRIDGE_SKILL_ALLOWLIST == expected
    registry = bridge.create_bridge_skill_registry()
    assert registry.skill_ids == expected
    assert registry.registry_identity == (
        "26d17f5893ee721d5e4209519f35fd38324b41e577485143b41368dadbd4034f"
    )


@pytest.mark.parametrize("skill_id", ["sgs_skill_pojiang", "sgs_skill_unknown"])
def test_non_allowlisted_skill_rejected(skill_id: str) -> None:
    with pytest.raises(bridge.BridgeContractError, match="非allowlisted"):
        bridge.validate_bridge_skill_id(skill_id)


def test_base_skill_authority_is_derived_from_general_source() -> None:
    assert bridge.BASE_SKILL_AUTHORITY.skills_for("shamoke") == ("sgs_skill_jili",)
    assert bridge.BASE_SKILL_AUTHORITY.skills_for("zhugezhan") == (
        "sgs_skill_zuilun",
        "sgs_skill_fuyin",
    )
    assert bridge.BASE_SKILL_AUTHORITY.skills_for("wangyuanji") == (
        "sgs_skill_qianchong",
        "sgs_skill_shangjian",
    )
    assert bridge.BASE_SKILL_AUTHORITY.skills_for(None) == ()


@pytest.mark.parametrize(
    ("general_key", "equipment_state", "expected"),
    [
        ("wangyuanji", bridge.EquipmentColorState.ALL_BLACK, ("sgs_skill_weimu",)),
        ("wangyuanji", bridge.EquipmentColorState.ALL_RED, ("sgs_skill_mingzhe",)),
        ("wangyuanji", bridge.EquipmentColorState.EMPTY, ()),
        ("wangyuanji", bridge.EquipmentColorState.MIXED, ()),
        ("shamoke", bridge.EquipmentColorState.ALL_BLACK, ()),
        ("zhugezhan", bridge.EquipmentColorState.ALL_RED, ()),
        (None, bridge.EquipmentColorState.ALL_BLACK, ()),
    ],
)
def test_dynamic_derivation_authority_exact_map(
    general_key: str | None,
    equipment_state: bridge.EquipmentColorState,
    expected: tuple[str, ...],
) -> None:
    assert bridge.DYNAMIC_DERIVATION_AUTHORITY.derive(
        general_key, equipment_state
    ) == expected


def test_dynamic_authority_rejects_dual_grant() -> None:
    with pytest.raises(bridge.BridgeContractError, match="双dynamic grant"):
        bridge.DYNAMIC_DERIVATION_AUTHORITY.validate_claim(
            general_key="wangyuanji",
            equipment_state=bridge.EquipmentColorState.ALL_BLACK,
            source_skill_id="sgs_skill_qianchong",
            granted_skill_ids=("sgs_skill_weimu", "sgs_skill_mingzhe"),
        )


@pytest.mark.parametrize(
    ("general_key", "state", "source", "grants"),
    [
        (
            "wangyuanji",
            bridge.EquipmentColorState.ALL_BLACK,
            "sgs_skill_qianchong",
            ("sgs_skill_mingzhe",),
        ),
        (
            "shamoke",
            bridge.EquipmentColorState.ALL_BLACK,
            "sgs_skill_qianchong",
            ("sgs_skill_weimu",),
        ),
        (
            "wangyuanji",
            bridge.EquipmentColorState.EMPTY,
            "sgs_skill_pojiang",
            ("sgs_skill_pojiang",),
        ),
    ],
)
def test_caller_supplied_dynamic_skill_rejected(
    general_key: str,
    state: bridge.EquipmentColorState,
    source: str,
    grants: tuple[str, ...],
) -> None:
    with pytest.raises(bridge.BridgeContractError, match="caller supplied"):
        bridge.DYNAMIC_DERIVATION_AUTHORITY.validate_claim(
            general_key=general_key,
            equipment_state=state,
            source_skill_id=source,
            granted_skill_ids=grants,
        )


def test_runtime_effective_authority_exact_invariant() -> None:
    expected = (
        "sgs_skill_qianchong",
        "sgs_skill_shangjian",
        "sgs_skill_weimu",
    )
    assert bridge.RUNTIME_EFFECTIVE_AUTHORITY.validate(
        general_key="wangyuanji",
        equipment_state=bridge.EquipmentColorState.ALL_BLACK,
        effective_skill_ids=expected,
    ) == expected
    with pytest.raises(bridge.BridgeContractError, match="invariant"):
        bridge.RUNTIME_EFFECTIVE_AUTHORITY.validate(
            general_key="wangyuanji",
            equipment_state=bridge.EquipmentColorState.ALL_BLACK,
            effective_skill_ids=expected + ("sgs_skill_mingzhe",),
        )


@pytest.mark.parametrize(
    ("assignment", "general_player", "soldier_player"),
    [
        (bridge.FixedAssignment.GENERAL_AS_P1, "p1", "p2"),
        (bridge.FixedAssignment.GENERAL_AS_P2, "p2", "p1"),
    ],
)
def test_assignment_seat_mapping_and_no_skill_opponent(
    assignment: bridge.FixedAssignment,
    general_player: str,
    soldier_player: str,
) -> None:
    resolved = bridge.create_bridge_assignment("wangyuanji", assignment)
    assert resolved.general_player_id == general_player
    assert resolved.no_skill_player_id == soldier_player
    by_id = {item.player_id: item for item in resolved.participants}
    assert by_id[general_player].general_key == "wangyuanji"
    assert by_id[general_player].skill_ids == (
        "sgs_skill_qianchong",
        "sgs_skill_shangjian",
    )
    soldier = by_id[soldier_player]
    assert soldier.character_key == "soldier"
    assert soldier.gender == "none"
    assert (soldier.hp, soldier.max_hp) == (4, 4)
    assert soldier.skill_ids == ()


@pytest.mark.parametrize(
    "assignment_request",
    [
        {"general_key": "shamoke"},
        {"seat_assignment": "GENERAL_AS_P1"},
        {
            "general_key": "shamoke",
            "seat_assignment": "GENERAL_AS_P1",
            "hp": 99,
        },
        {
            "general_key": "shamoke",
            "seat_assignment": "RANDOM",
        },
        {
            "general_key": "shamoke",
            "seat_assignment": "GENERAL_AS_P1",
            "skills": ["sgs_skill_pojiang"],
        },
    ],
)
def test_assignment_request_missing_extra_random_or_caller_authority_rejected(
    assignment_request: dict[str, object],
) -> None:
    with pytest.raises(bridge.BridgeContractError):
        bridge.create_bridge_assignment_from_request(assignment_request)


@pytest.mark.parametrize("tamper", ["stats", "skills", "participant", "two_generals"])
def test_assignment_full_descriptor_tamper_rejected(tamper: str) -> None:
    data = bridge.create_bridge_assignment(
        "shamoke", bridge.FixedAssignment.GENERAL_AS_P1
    ).to_dict()
    if tamper == "stats":
        data["participants"][0]["hp"] = 3
    elif tamper == "skills":
        data["participants"][0]["skill_ids"] = ["sgs_skill_pojiang"]
    elif tamper == "participant":
        data["participants"][1]["player_id"] = "p3"
    else:
        data["participants"][1] = dict(data["participants"][0])
        data["participants"][1]["player_id"] = "p2"
    with pytest.raises(bridge.BridgeContractError):
        bridge.BridgeAssignmentDescriptor.from_dict(data)


def test_assignment_descriptor_is_immutable() -> None:
    value = bridge.create_bridge_assignment("shamoke", "GENERAL_AS_P1")
    with pytest.raises(FrozenInstanceError):
        value.general_key = "zhugezhan"  # type: ignore[misc]


def test_nested_participant_direct_construction_rejects_caller_skills() -> None:
    assignment = bridge.create_bridge_assignment("shamoke", "GENERAL_AS_P1")
    soldier = assignment.participants[1]
    with pytest.raises(bridge.BridgeContractError, match="soldier authority"):
        replace(soldier, skill_ids=("sgs_skill_pojiang",))


def test_baseline_18_exact_length_order_and_unique_triples() -> None:
    assert len(bridge.BASELINE_18) == 18
    expected = []
    index = 1
    for general_key, assignment, seed in product(
        bridge.GENERAL_ALLOWLIST,
        (
            bridge.FixedAssignment.GENERAL_AS_P1,
            bridge.FixedAssignment.GENERAL_AS_P2,
        ),
        bridge.BASELINE_SEEDS,
    ):
        expected.append((f"B18-{index:03d}", general_key, assignment, seed))
        index += 1
    actual = [
        (cell.cell_id, cell.general_key, cell.seat_assignment, cell.seed)
        for cell in bridge.BASELINE_18
    ]
    assert actual == expected
    assert len({cell.cell_id for cell in bridge.BASELINE_18}) == 18
    assert len(
        {
            (cell.general_key, cell.seat_assignment, cell.seed)
            for cell in bridge.BASELINE_18
        }
    ) == 18
    assert {cell.seed for cell in bridge.BASELINE_18} == {0, 1, 49}


def test_baseline_18_frozen_execution_flags() -> None:
    for cell in bridge.BASELINE_18:
        assert cell.analysis_only is False
        assert cell.fixture is False
        assert cell.premutation is False
        assert cell.manual_event_injection is False
        assert cell.max_steps == 2000
        assert cell.mode_modifier is bridge.ModeModifier.NONE
        assert cell.general_player_id != cell.no_skill_player_id


def test_baseline_18_registry_identity_recomputed_from_canonical_descriptor() -> None:
    assert bridge.BASELINE_18_SCHEMA == (
        "skill-aware-fixed-assignment-bridge-baseline-matrix-v1"
    )
    descriptor = bridge.baseline_18_canonical_descriptor()
    assert set(descriptor) == {"schema", "contract_id", "cells"}
    assert set(descriptor["cells"][0]) == {
        "cell_id",
        "general_key",
        "seat_assignment",
        "general_player_id",
        "no_skill_player_id",
        "seed",
    }
    assert bridge.compute_baseline_18_registry_identity() == (
        "76e5444cd758851059f25a21a884e9af68b8c9ee48d652455561dd91717c56af"
    )
    assert bridge.BASELINE_18_REGISTRY_IDENTITY == (
        "76e5444cd758851059f25a21a884e9af68b8c9ee48d652455561dd91717c56af"
    )


def test_initialization_sequence_and_prohibitions_are_exact() -> None:
    assert tuple(step.value for step in bridge.INITIALIZATION_SEQUENCE) == (
        "validate_formal_profile",
        "validate_assignment",
        "derive_general_stats",
        "apply_mode_modifier_none",
        "first_player_rng",
        "shuffle_and_deal",
        "derive_base_skills",
        "initial_qianchong_reconcile",
        "sign_initial_state",
        "enumerate_first_legal_set",
    )
    assert bridge.INITIALIZATION_CONTRACT.live_execution_stage == "BRIDGE-B"
    assert bridge.INITIALIZATION_CONTRACT.mode_modifier is bridge.ModeModifier.NONE
    assert set(bridge.INITIALIZATION_PROHIBITIONS) == {
        "initial_deal_not_in_turn_loss_ledger",
        "initialization_does_not_call_gameplay_skill_dispatcher",
        "initialization_does_not_trigger_jili",
        "initialization_does_not_trigger_zuilun",
        "initialization_does_not_trigger_fuyin",
        "initialization_does_not_trigger_mingzhe",
        "initialization_does_not_trigger_shangjian",
        "qianchong_initial_reconcile_is_eventless",
    }
    assert bridge.INITIALIZATION_SEQUENCE_IDENTITY == bridge.sha256_value(
        bridge.INITIALIZATION_CONTRACT.to_dict()
    )


def test_event_obligation_exact_ids_and_unproven_initial_state() -> None:
    assert bridge.EVENT_OBLIGATION_IDS == (
        "EV-G1-JILI-01",
        "EV-G2-ZUILUN-01",
        "EV-G2-FUYIN-01",
        "EV-G3-QIANCHONG-01",
        "EV-G3-SHANGJIAN-01",
    )
    assert all(
        item.initial_status is bridge.WitnessStatus.REQUIRED
        for item in bridge.EVENT_OBLIGATIONS
    )
    assert all(
        item.initial_status is not bridge.WitnessStatus.PROVEN
        for item in bridge.EVENT_OBLIGATIONS
    )
    assert bridge.BASELINE_18_WITNESS_OBLIGATIONS_STATUS is bridge.WitnessStatus.REQUIRED


def test_sentinel_policy_is_undiscovered_and_anti_cherry_picking() -> None:
    policy = bridge.SENTINEL_POLICY
    assert (policy.seed_min, policy.seed_max) == (0, 99)
    assert policy.excluded_seeds == (0, 1, 49)
    assert policy.general_order == bridge.GENERAL_ALLOWLIST
    assert tuple(item.value for item in policy.seat_order) == (
        "GENERAL_AS_P1",
        "GENERAL_AS_P2",
    )
    assert policy.seed_order == "ascending"
    assert policy.inclusion_minimal is True
    assert policy.discovery_is_formal_evidence is False
    assert policy.frozen_failure_may_replace_seed is False
    assert bridge.MINIMAL_REQUIRED_SENTINELS is bridge.SentinelDiscoveryStatus.UNDISCOVERED
    assert bridge.FINAL_ACCEPTANCE_MATRIX == "BASELINE_18 + UNDISCOVERED_SENTINELS"


@pytest.mark.parametrize("seed", [-1, 0, 1, 49, 100])
def test_sentinel_policy_rejects_out_of_range_or_baseline_seed(seed: int) -> None:
    with pytest.raises(bridge.BridgeContractError):
        bridge.SENTINEL_POLICY.validate_candidate(
            general_key="shamoke",
            seat_assignment="GENERAL_AS_P1",
            seed=seed,
            closes_event_ids=("EV-G1-JILI-01",),
        )


def test_valid_public_opaque_choice_projection_contains_no_private_semantics() -> None:
    data = {
        "choice_token": "opaque:0",
        "ordinal": 0,
        "action_id": "signed-action-id",
        "publicly_allowed_action_type": "select_private_choice",
    }
    projection = bridge.PublicOpaqueChoiceProjection.from_dict(data)
    assert projection.to_dict() == data
    assert not set(projection.to_dict()) & bridge.PRIVATE_SELECTION_FORBIDDEN_FIELDS


def test_public_opaque_choice_direct_constructor_validates_exact_types() -> None:
    with pytest.raises(bridge.BridgeContractError, match="ordinal"):
        bridge.PublicOpaqueChoiceProjection(
            choice_token="opaque:0",
            ordinal=True,
            action_id="signed-action-id",
            publicly_allowed_action_type="select_private_choice",
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("card_id", "deck-001"),
        ("card_identity", "sha"),
        ("card_name", "杀"),
        ("suit", "spade"),
        ("rank", 7),
        ("card_value", 99),
        ("private_payload", {"name": "杀"}),
        ("private_semantic_value", "best"),
        ("future_cards", ["deck-002"]),
        ("deck_contents", ["deck-003"]),
    ],
)
def test_zuilun_public_projection_rejects_private_card_payload(
    field: str, value: object
) -> None:
    data = {
        "choice_token": "opaque:0",
        "ordinal": 0,
        "action_id": "signed-action-id",
        "publicly_allowed_action_type": "select_private_choice",
        field: value,
    }
    with pytest.raises(bridge.BridgeContractError, match="private card payload"):
        bridge.PublicOpaqueChoiceProjection.from_dict(data)


def test_replay_required_field_set_is_exact() -> None:
    assert bridge.BRIDGE_REPLAY_REQUIRED_FIELDS == frozenset(_valid_replay_descriptor())
    assert bridge.UNKNOWN_REPLAY_AUTHORITY_FIELD_POLICY.value == "REJECT"


def test_replay_descriptor_skeleton_accepts_exact_schema_without_defaults() -> None:
    data = _valid_replay_descriptor()
    skeleton = bridge.BridgeReplayDescriptorSkeleton.from_dict(data)
    assert skeleton.to_dict() == data


def test_replay_descriptor_skeleton_rejects_direct_constructor_bypass() -> None:
    with pytest.raises(bridge.BridgeContractError, match="strict from_dict"):
        bridge.BridgeReplayDescriptorSkeleton(_valid_replay_descriptor())


@pytest.mark.parametrize("attack", ["missing", "extra"])
def test_replay_descriptor_rejects_missing_or_unknown_authority_field(attack: str) -> None:
    data = _valid_replay_descriptor()
    if attack == "missing":
        data.pop("bridge_authority_profile_identity")
    else:
        data["caller_supplied_authority"] = "forged"
    with pytest.raises(bridge.BridgeContractError, match="字段必须精确匹配"):
        bridge.BridgeReplayDescriptorSkeleton.from_dict(data)


def test_bridge_schema_marker_cannot_be_no_skill_marker() -> None:
    with pytest.raises(bridge.BridgeContractError, match="no-skill/legacy"):
        bridge.validate_bridge_replay_schema_marker(
            "sgs-authoritative-no-skill-full-game-replay-v2"
        )
    data = _valid_replay_descriptor()
    data["schema"] = "sgs-authoritative-no-skill-full-game-replay-v2"
    with pytest.raises(bridge.BridgeContractError, match="no-skill/legacy"):
        bridge.BridgeReplayDescriptorSkeleton.from_dict(data)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("replay_version", True),
        ("controller_version", "1"),
        ("seed", False),
        ("decisions", ()),
        ("initialization", []),
        ("records_identity", "NOT_LOADED"),
    ],
)
def test_replay_descriptor_exact_type_validation(field: str, value: object) -> None:
    data = _valid_replay_descriptor()
    data[field] = value
    with pytest.raises(bridge.BridgeContractError):
        bridge.BridgeReplayDescriptorSkeleton.from_dict(data)


def test_canonical_serialization_is_deterministic() -> None:
    descriptor = bridge.bridge_contract_descriptor()
    reversed_descriptor = dict(reversed(tuple(descriptor.items())))
    assert bridge.canonical_json(descriptor) == bridge.canonical_json(reversed_descriptor)
    assert bridge.sha256_value(descriptor) == bridge.sha256_value(reversed_descriptor)


def test_contract_identity_is_deterministic_and_binds_required_authority() -> None:
    descriptor = bridge.bridge_contract_descriptor()
    assert bridge.compute_bridge_contract_identity() == (
        bridge.PROPOSED_BRIDGE_CONTRACT_IDENTITY
    )
    assert len(bridge.PROPOSED_BRIDGE_CONTRACT_IDENTITY) == 64
    assert descriptor["contract_id"] == bridge.CONTRACT_ID
    assert descriptor["mode_id"] == bridge.MODE_ID
    assert descriptor["replay_schema"] == bridge.REPLAY_SCHEMA
    assert descriptor["controller_id"] == bridge.CONTROLLER_ID
    assert descriptor["formal_duel_profile_identity"] == (
        bridge.FORMAL_DUEL_PROFILE_IDENTITY
    )
    assert descriptor["deck_identity"] == bridge.DECK_IDENTITY
    assert descriptor["general_registry_identity"] == bridge.GENERAL_REGISTRY_IDENTITY
    assert descriptor["bridge_skill_registry_identity"] == (
        bridge.BRIDGE_SKILL_REGISTRY_IDENTITY
    )
    assert descriptor["baseline_18_registry_identity"] == (
        bridge.BASELINE_18_REGISTRY_IDENTITY
    )
    assert descriptor["event_obligation_ids"] == list(bridge.EVENT_OBLIGATION_IDS)
    assert descriptor["mode_modifier"] == "NONE"
    assert descriptor["max_steps"] == 2000
    assert {item["marker"] for item in descriptor["frozen_out_of_scope"]} == set(
        bridge.FROZEN_OUT_OF_SCOPE_MARKERS
    )


def test_contract_identity_changes_on_semantic_descriptor_tamper() -> None:
    descriptor = bridge.bridge_contract_descriptor()
    descriptor["max_steps"] = 1999
    assert bridge.sha256_value(descriptor) != bridge.PROPOSED_BRIDGE_CONTRACT_IDENTITY


def test_baseline_cell_fail_closed_constructor_rejects_execution_ingress() -> None:
    cell = bridge.BASELINE_18[0]
    with pytest.raises(bridge.BridgeContractError, match="analysis_only"):
        replace(cell, analysis_only=True)
    with pytest.raises(bridge.BridgeContractError, match="fixture"):
        replace(cell, fixture=True)
    with pytest.raises(bridge.BridgeContractError, match="premutation"):
        replace(cell, premutation=True)
    with pytest.raises(bridge.BridgeContractError, match="manual_event_injection"):
        replace(cell, manual_event_injection=True)
    with pytest.raises(bridge.BridgeContractError, match="max_steps"):
        replace(cell, max_steps=2001)
