# -*- coding: utf-8 -*-
"""Cheap contract/type tests for provisional Bridge-H acceptance V1."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import MISSING, fields

import pytest

from scripts.sgs_engine.replay import sha256_value
from scripts.sgs_engine.skill_aware_fixed_assignment_bridge_acceptance_v1 import (
    BRIDGE_ACCEPTANCE_ARTIFACT_SCHEMA_V1,
    BRIDGE_ACCEPTANCE_CELL_PROOF_SCHEMA_V1,
    BRIDGE_ACCEPTANCE_CELL_SCHEMA_V1,
    BRIDGE_ACCEPTANCE_MATRIX_SCHEMA_V1,
    BRIDGE_ACCEPTANCE_PROGRESS_SCHEMA_V1,
    BRIDGE_ACCEPTANCE_PROOF_FLAG_NAMES_V1,
    BRIDGE_ACCEPTANCE_REGISTRY_CELL_SCHEMA_V1,
    BRIDGE_ACCEPTANCE_REGISTRY_SCHEMA_V1,
    BRIDGE_ACCEPTANCE_RESULT_SCHEMA_V1,
    BRIDGE_H_CONTRACT_IDENTITY_V1,
    BRIDGE_H_CONTRACT_VERSION,
    BRIDGE_REQUIRED_EVENT_COVERAGE_SCHEMA_V1,
    BRIDGE_REQUIRED_EVENT_IDS_V1,
    BRIDGE_REQUIRED_EVENT_WITNESS_SCHEMA_V1,
    BRIDGE_SENTINEL_CANDIDATE_SCHEMA_V1,
    BRIDGE_SENTINEL_REGISTRY_SCHEMA_V1,
    PROVISIONAL_PENDING_AUDIT,
    BridgeAcceptanceArtifactV1,
    BridgeAcceptanceAuthorityV1,
    BridgeAcceptanceCellProofV1,
    BridgeAcceptanceCellV1,
    BridgeAcceptanceContractError,
    BridgeAcceptanceMatrixV1,
    BridgeAcceptanceProgressV1,
    BridgeAcceptanceRegistryCellV1,
    BridgeAcceptanceRegistryV1,
    BridgeAcceptanceResultV1,
    BridgeRequiredEventCoverageV1,
    BridgeRequiredEventWitnessV1,
    BridgeSentinelCandidateV1,
    BridgeSentinelDiscoveryStatusV1,
    BridgeSentinelObservationV1,
    BridgeSentinelRegistryV1,
    assert_bridge_acceptance_aggregate_complete_v1,
    bridge_acceptance_baseline_registry_v1,
    canonical_bridge_sentinel_search_keys_v1,
    create_bridge_acceptance_matrix_v1,
    create_bridge_baseline_acceptance_cell_v1,
    create_bridge_required_event_witness_v1,
    create_bridge_sentinel_registry_record_v1,
    create_bridge_sentinel_observation_v1,
    derive_bridge_acceptance_result_v1,
    validate_bridge_acceptance_matrix_v1,
    validate_bridge_acceptance_result_v1,
    select_bridge_sentinel_registry_v1,
    validate_bridge_sentinel_selection_v1,
)
from scripts.sgs_engine.skill_aware_fixed_assignment_full_game_bridge import (
    BASELINE_18,
    BASELINE_18_REGISTRY_IDENTITY,
    FixedAssignment,
)


ZERO64 = "0" * 64
ONE64 = "1" * 64
TWO64 = "2" * 64
THREE64 = "3" * 64
FOUR64 = "4" * 64


def _with_identity(payload: dict[str, object], identity_field: str) -> dict[str, object]:
    result = deepcopy(payload)
    result[identity_field] = sha256_value(payload)
    return result


def _authority_payload() -> dict[str, object]:
    return BridgeAcceptanceAuthorityV1.current().to_dict()


def _terminal_payload() -> dict[str, object]:
    return {
        "engine_finished_invariants_passed": True,
        "skill_pending_none": True,
        "skill_trigger_queue_empty": True,
        "pending_private_card_selection_none": True,
        "pending_skill_hp_loss_none": True,
        "pending_card_continuation_none": True,
        "end_phase_dispatch_state_none": True,
        "continuation_in_progress_none": True,
        "response_window_none": True,
        "pending_dying_none": True,
        "processing_empty": True,
        "revealed_empty": True,
        "post_finish_step_blocked": True,
        "post_finish_action_surface_blocked": True,
        "end_dispatcher_cannot_resume": True,
        "finished": True,
        "phase": "finished",
        "winner": "p1",
        "finish_reason": "opponent_confirmed_dead",
    }


def _proof_payload() -> dict[str, object]:
    return {
        "schema": BRIDGE_ACCEPTANCE_CELL_PROOF_SCHEMA_V1,
        "version": BRIDGE_H_CONTRACT_VERSION,
        "trace_scope": "NATURAL_FULL_GAME",
        "finished": True,
        "source_proof_flags": {
            name: True for name in BRIDGE_ACCEPTANCE_PROOF_FLAG_NAMES_V1
        },
        "terminal_invariants": _terminal_payload(),
        "source_cell_proof_identity": ONE64,
        "provisional_pending_audit": PROVISIONAL_PENDING_AUDIT,
    }


def _event_witness_payload(
    *,
    event_id: str = "EV-G1-JILI-01",
    general_key: str = "shamoke",
    cell_id: str = "B18-001",
    source_kind: str = "SKILL_OPTIONAL_WINDOW",
    source_replay_identity: str = FOUR64,
) -> dict[str, object]:
    material = {
        "schema": BRIDGE_REQUIRED_EVENT_WITNESS_SCHEMA_V1,
        "version": BRIDGE_H_CONTRACT_VERSION,
        "event_id": event_id,
        "general_key": general_key,
        "cell_id": cell_id,
        "source_kind": source_kind,
        "source_index": 0,
        "source_witness_identity": THREE64,
        "source_replay_identity": source_replay_identity,
        "provisional_pending_audit": PROVISIONAL_PENDING_AUDIT,
    }
    return _with_identity(material, "witness_binding_identity")


def _coverage_payload(
    event_id: str,
    general_key: str,
    witness_cell_ids: list[str] | None = None,
    witness_binding_identities: list[str] | None = None,
) -> dict[str, object]:
    material = {
        "schema": BRIDGE_REQUIRED_EVENT_COVERAGE_SCHEMA_V1,
        "version": BRIDGE_H_CONTRACT_VERSION,
        "event_id": event_id,
        "general_key": general_key,
        "witness_cell_ids": witness_cell_ids or [],
        "witness_binding_identities": witness_binding_identities or [],
        "provisional_pending_audit": PROVISIONAL_PENDING_AUDIT,
    }
    return _with_identity(material, "coverage_identity")


def _sentinel_candidate_payload() -> dict[str, object]:
    material = {
        "schema": BRIDGE_SENTINEL_CANDIDATE_SCHEMA_V1,
        "version": BRIDGE_H_CONTRACT_VERSION,
        "candidate_id": "SENTINEL-SHAMOKE-P1-SEED-2",
        "general_key": "shamoke",
        "seat_assignment": "GENERAL_AS_P1",
        "seed": 2,
        "closes_event_ids": ["EV-G1-JILI-01"],
        "discovery_artifact_sha256": TWO64,
        "discovery_witness_identities": [THREE64],
        "discovery_is_formal_evidence": False,
        "provisional_pending_audit": PROVISIONAL_PENDING_AUDIT,
    }
    return _with_identity(material, "candidate_identity")


def _sentinel_registry_payload() -> dict[str, object]:
    material = {
        "schema": BRIDGE_SENTINEL_REGISTRY_SCHEMA_V1,
        "version": BRIDGE_H_CONTRACT_VERSION,
        "authority": _authority_payload(),
        "baseline_event_ids": [],
        "selected_candidates": [],
        "remaining_event_ids": list(BRIDGE_REQUIRED_EVENT_IDS_V1),
        "discovery_status": "NOT_RUN",
        "discovery_is_formal_evidence": False,
        "provisional_pending_audit": PROVISIONAL_PENDING_AUDIT,
    }
    return _with_identity(material, "registry_identity")


def _cell_payload() -> dict[str, object]:
    witness = _event_witness_payload()
    material = {
        "schema": BRIDGE_ACCEPTANCE_CELL_SCHEMA_V1,
        "version": BRIDGE_H_CONTRACT_VERSION,
        "authority": _authority_payload(),
        "cell_kind": "BASELINE",
        "cell_id": "B18-001",
        "general_key": "shamoke",
        "seat_assignment": "GENERAL_AS_P1",
        "general_player_id": "p1",
        "no_skill_player_id": "p2",
        "seed": 0,
        "registry_cell_identity": ZERO64,
        "replay_artifact_path": "synthetic/B18-001.replay.json",
        "replay_artifact_sha256": ONE64,
        "records_identity": TWO64,
        "execution_identity": THREE64,
        "replay_identity": FOUR64,
        "proof": _proof_payload(),
        "required_event_witnesses": [witness],
        "provisional_pending_audit": PROVISIONAL_PENDING_AUDIT,
    }
    return _with_identity(material, "cell_identity")


def _matrix_payload() -> dict[str, object]:
    material = {
        "schema": BRIDGE_ACCEPTANCE_MATRIX_SCHEMA_V1,
        "version": BRIDGE_H_CONTRACT_VERSION,
        "authority": _authority_payload(),
        "ordered_registry_identity": ZERO64,
        "ordered_cell_ids": [],
        "cells": [],
        "sentinel_registry": _sentinel_registry_payload(),
        "provisional_pending_audit": PROVISIONAL_PENDING_AUDIT,
    }
    return _with_identity(material, "matrix_identity")


def _artifact_payload() -> dict[str, object]:
    material = {
        "schema": BRIDGE_ACCEPTANCE_ARTIFACT_SCHEMA_V1,
        "version": BRIDGE_H_CONTRACT_VERSION,
        "cell_id": "B18-001",
        "artifact_path": "synthetic/B18-001.replay.json",
        "artifact_sha256": ONE64,
        "replay_identity": TWO64,
        "cell_identity": THREE64,
        "provisional_pending_audit": PROVISIONAL_PENDING_AUDIT,
    }
    return _with_identity(material, "artifact_identity")


def _progress_payload() -> dict[str, object]:
    material = {
        "schema": BRIDGE_ACCEPTANCE_PROGRESS_SCHEMA_V1,
        "version": BRIDGE_H_CONTRACT_VERSION,
        "authority": _authority_payload(),
        "mode": "formal",
        "ordered_registry_identity": ZERO64,
        "sentinel_registry_identity": ONE64,
        "ordered_expected_cell_ids": [],
        "completed_cell_ids": [],
        "failed_cell_ids": [],
        "artifacts": [],
        "final_artifact_exists": False,
        "provisional_pending_audit": PROVISIONAL_PENDING_AUDIT,
    }
    return _with_identity(material, "progress_identity")


def _result_payload() -> dict[str, object]:
    general_by_event = {
        "EV-G1-JILI-01": "shamoke",
        "EV-G2-ZUILUN-01": "zhugezhan",
        "EV-G2-FUYIN-01": "zhugezhan",
        "EV-G3-QIANCHONG-01": "wangyuanji",
        "EV-G3-SHANGJIAN-01": "wangyuanji",
    }
    coverage = [
        _coverage_payload(event_id, general_by_event[event_id])
        for event_id in BRIDGE_REQUIRED_EVENT_IDS_V1
    ]
    material = {
        "schema": BRIDGE_ACCEPTANCE_RESULT_SCHEMA_V1,
        "version": BRIDGE_H_CONTRACT_VERSION,
        "authority": _authority_payload(),
        "matrix_identity": ZERO64,
        "aggregate_proof_flags": {
            name: False for name in BRIDGE_ACCEPTANCE_PROOF_FLAG_NAMES_V1
        },
        "required_event_coverage": coverage,
        "missing_required_event_ids": list(BRIDGE_REQUIRED_EVENT_IDS_V1),
        "provisional_pending_audit": PROVISIONAL_PENDING_AUDIT,
    }
    return _with_identity(material, "result_identity")


def test_h1_frozen_authority_and_required_event_ids_are_exact() -> None:
    authority = BridgeAcceptanceAuthorityV1.current()
    assert len(BRIDGE_H_CONTRACT_IDENTITY_V1) == 64
    assert authority.bridge_h_contract_identity == BRIDGE_H_CONTRACT_IDENTITY_V1
    assert BRIDGE_REQUIRED_EVENT_IDS_V1 == (
        "EV-G1-JILI-01",
        "EV-G2-ZUILUN-01",
        "EV-G2-FUYIN-01",
        "EV-G3-QIANCHONG-01",
        "EV-G3-SHANGJIAN-01",
    )
    assert authority.provisional_pending_audit == "YES"


@pytest.mark.parametrize(
    ("contract_type", "payload_factory"),
    (
        (BridgeAcceptanceAuthorityV1, _authority_payload),
        (BridgeAcceptanceCellProofV1, _proof_payload),
        (BridgeRequiredEventWitnessV1, _event_witness_payload),
        (
            BridgeRequiredEventCoverageV1,
            lambda: _coverage_payload("EV-G1-JILI-01", "shamoke"),
        ),
        (BridgeAcceptanceCellV1, _cell_payload),
        (BridgeSentinelCandidateV1, _sentinel_candidate_payload),
        (BridgeSentinelRegistryV1, _sentinel_registry_payload),
        (BridgeAcceptanceMatrixV1, _matrix_payload),
        (BridgeAcceptanceArtifactV1, _artifact_payload),
        (BridgeAcceptanceProgressV1, _progress_payload),
        (BridgeAcceptanceResultV1, _result_payload),
    ),
)
def test_h1_all_contract_types_round_trip_exactly(
    contract_type: type, payload_factory
) -> None:
    payload = payload_factory()
    parsed = contract_type.from_dict(deepcopy(payload))
    assert parsed.to_dict() == payload


@pytest.mark.parametrize(
    "contract_type",
    (
        BridgeAcceptanceCellV1,
        BridgeAcceptanceMatrixV1,
        BridgeAcceptanceProgressV1,
        BridgeAcceptanceResultV1,
        BridgeSentinelCandidateV1,
        BridgeSentinelRegistryV1,
        BridgeRequiredEventCoverageV1,
    ),
)
def test_h1_named_contract_constructors_have_no_defaults(contract_type: type) -> None:
    for field in fields(contract_type):
        assert field.default is MISSING
        assert field.default_factory is MISSING


@pytest.mark.parametrize(
    ("contract_type", "payload_factory"),
    (
        (BridgeAcceptanceAuthorityV1, _authority_payload),
        (BridgeAcceptanceCellV1, _cell_payload),
        (BridgeAcceptanceMatrixV1, _matrix_payload),
        (BridgeAcceptanceProgressV1, _progress_payload),
        (BridgeAcceptanceResultV1, _result_payload),
        (BridgeSentinelCandidateV1, _sentinel_candidate_payload),
        (BridgeSentinelRegistryV1, _sentinel_registry_payload),
        (
            BridgeRequiredEventCoverageV1,
            lambda: _coverage_payload("EV-G1-JILI-01", "shamoke"),
        ),
    ),
)
def test_h1_missing_and_unknown_fields_fail_closed(
    contract_type: type, payload_factory
) -> None:
    payload = payload_factory()
    missing = deepcopy(payload)
    missing.pop(next(iter(missing)))
    with pytest.raises(BridgeAcceptanceContractError, match="missing="):
        contract_type.from_dict(missing)

    extra = deepcopy(payload)
    extra["unknown_authority"] = "forged"
    with pytest.raises(BridgeAcceptanceContractError, match="extra="):
        contract_type.from_dict(extra)


@pytest.mark.parametrize(
    "forbidden_field",
    ("ready", "event_union_complete", "sentinel_not_required"),
)
def test_h1_cached_authority_fields_are_not_accepted(forbidden_field: str) -> None:
    for contract_type, payload in (
        (BridgeAcceptanceCellV1, _cell_payload()),
        (BridgeAcceptanceMatrixV1, _matrix_payload()),
        (BridgeAcceptanceResultV1, _result_payload()),
        (BridgeSentinelRegistryV1, _sentinel_registry_payload()),
    ):
        attacked = deepcopy(payload)
        attacked[forbidden_field] = True
        with pytest.raises(BridgeAcceptanceContractError, match="extra="):
            contract_type.from_dict(attacked)


def test_h1_unknown_nested_authority_and_type_drift_fail_closed() -> None:
    attacked = _matrix_payload()
    attacked["authority"]["private_runtime"] = {"state": "leak"}
    with pytest.raises(BridgeAcceptanceContractError, match="extra="):
        BridgeAcceptanceMatrixV1.from_dict(attacked)

    drift = _authority_payload()
    drift["controller_version"] = True
    with pytest.raises(BridgeAcceptanceContractError, match="精确整数"):
        BridgeAcceptanceAuthorityV1.from_dict(drift)


def test_h1_event_general_and_witness_kind_attribution_fail_closed() -> None:
    wrong_general = _event_witness_payload()
    wrong_general["general_key"] = "zhugezhan"
    with pytest.raises(BridgeAcceptanceContractError, match="General归属"):
        BridgeRequiredEventWitnessV1.from_dict(wrong_general)

    wrong_kind = _event_witness_payload()
    wrong_kind["source_kind"] = "TARGET_EFFECT_FIRST_CHANCE"
    with pytest.raises(BridgeAcceptanceContractError, match="source_kind"):
        BridgeRequiredEventWitnessV1.from_dict(wrong_kind)


def test_h1_provisional_marker_is_mandatory_everywhere() -> None:
    attacked = _cell_payload()
    attacked["provisional_pending_audit"] = "NO"
    attacked = _with_identity(
        {key: value for key, value in attacked.items() if key != "cell_identity"},
        "cell_identity",
    )
    with pytest.raises(BridgeAcceptanceContractError, match="PROVISIONAL"):
        BridgeAcceptanceCellV1.from_dict(attacked)

    stripped = _result_payload()
    stripped.pop("provisional_pending_audit")
    with pytest.raises(BridgeAcceptanceContractError, match="missing="):
        BridgeAcceptanceResultV1.from_dict(stripped)


def test_h2_acceptance_registry_is_exact_view_of_canonical_baseline_18() -> None:
    registry = bridge_acceptance_baseline_registry_v1()
    assert registry.source_registry_identity == BASELINE_18_REGISTRY_IDENTITY
    assert registry.ordered_cell_ids == tuple(item.cell_id for item in BASELINE_18)
    assert registry.ordered_cell_ids == tuple(f"B18-{index:03d}" for index in range(1, 19))
    assert len(registry.cells) == 18
    for actual, source in zip(registry.cells, BASELINE_18, strict=True):
        descriptor = source.to_registry_descriptor()
        assert {
            "cell_id": actual.cell_id,
            "general_key": actual.general_key,
            "seat_assignment": actual.seat_assignment.value,
            "general_player_id": actual.general_player_id,
            "no_skill_player_id": actual.no_skill_player_id,
            "seed": actual.seed,
        } == descriptor
        assert actual.registry_cell_identity == sha256_value(descriptor)
    assert BridgeAcceptanceRegistryV1.from_dict(registry.to_dict()) == registry


def test_h2_registry_types_have_required_constructor_fields_and_exact_schema() -> None:
    registry = bridge_acceptance_baseline_registry_v1()
    assert registry.schema == BRIDGE_ACCEPTANCE_REGISTRY_SCHEMA_V1
    assert registry.cells[0].schema == BRIDGE_ACCEPTANCE_REGISTRY_CELL_SCHEMA_V1
    for contract_type in (BridgeAcceptanceRegistryCellV1, BridgeAcceptanceRegistryV1):
        for field in fields(contract_type):
            assert field.default is MISSING
            assert field.default_factory is MISSING

    missing = registry.to_dict()
    missing.pop("cells")
    with pytest.raises(BridgeAcceptanceContractError, match="missing="):
        BridgeAcceptanceRegistryV1.from_dict(missing)

    extra = registry.to_dict()
    extra["cached_ready"] = True
    with pytest.raises(BridgeAcceptanceContractError, match="extra="):
        BridgeAcceptanceRegistryV1.from_dict(extra)


@pytest.mark.parametrize("attack", ("missing", "extra", "duplicate", "reorder"))
def test_h2_registry_shape_attacks_fail_closed(attack: str) -> None:
    payload = bridge_acceptance_baseline_registry_v1().to_dict()
    cells = payload["cells"]
    if attack == "missing":
        cells.pop()
    elif attack == "extra":
        cells.append(deepcopy(cells[-1]))
    elif attack == "duplicate":
        cells[1] = deepcopy(cells[0])
    else:
        cells[0], cells[1] = cells[1], cells[0]
    with pytest.raises(BridgeAcceptanceContractError, match="BASELINE_18"):
        BridgeAcceptanceRegistryV1.from_dict(payload)


@pytest.mark.parametrize(
    ("field_name", "forged_value"),
    (
        ("general_key", "zhugezhan"),
        ("seat_assignment", "GENERAL_AS_P2"),
        ("general_player_id", "p2"),
        ("no_skill_player_id", "p1"),
        ("seed", 1),
        ("cell_id", "B18-999"),
    ),
)
def test_h2_registry_row_fact_attacks_fail_closed(
    field_name: str, forged_value: object
) -> None:
    payload = bridge_acceptance_baseline_registry_v1().to_dict()
    payload["cells"][0][field_name] = forged_value
    with pytest.raises(BridgeAcceptanceContractError):
        BridgeAcceptanceRegistryV1.from_dict(payload)


def test_h2_registry_cell_identity_and_source_identity_attacks_fail_closed() -> None:
    payload = bridge_acceptance_baseline_registry_v1().to_dict()
    payload["cells"][0]["registry_cell_identity"] = ZERO64
    with pytest.raises(BridgeAcceptanceContractError, match="registry_cell_identity"):
        BridgeAcceptanceRegistryV1.from_dict(payload)

    source_drift = bridge_acceptance_baseline_registry_v1().to_dict()
    source_drift["source_registry_identity"] = ZERO64
    with pytest.raises(BridgeAcceptanceContractError, match="source identity"):
        BridgeAcceptanceRegistryV1.from_dict(source_drift)


_H3_WITNESS_SPECS = {
    "B18-001": (
        ("EV-G1-JILI-01", "SKILL_OPTIONAL_WINDOW"),
    ),
    "B18-007": (
        ("EV-G2-ZUILUN-01", "SKILL_OPTIONAL_WINDOW_END_RESUME"),
        ("EV-G2-FUYIN-01", "TARGET_EFFECT_FIRST_CHANCE"),
    ),
    "B18-013": (
        ("EV-G3-QIANCHONG-01", "QIANCHONG_CHOICE"),
        ("EV-G3-SHANGJIAN-01", "SHANGJIAN_LIVE_CONDITION"),
    ),
}


def _synthetic_complete_matrix() -> BridgeAcceptanceMatrixV1:
    registry = bridge_acceptance_baseline_registry_v1()
    cells = []
    for registry_cell in registry.cells:
        replay_identity = sha256_value(
            {"synthetic_replay": registry_cell.cell_id}
        )
        proof_payload = _proof_payload()
        proof_payload["source_cell_proof_identity"] = sha256_value(
            {"synthetic_proof": registry_cell.cell_id}
        )
        proof = BridgeAcceptanceCellProofV1.from_dict(proof_payload)
        witnesses = tuple(
            create_bridge_required_event_witness_v1(
                event_id=event_id,
                cell_id=registry_cell.cell_id,
                source_kind=source_kind,
                source_index=index,
                source_witness_identity=sha256_value(
                    {
                        "synthetic_witness": registry_cell.cell_id,
                        "event_id": event_id,
                    }
                ),
                source_replay_identity=replay_identity,
            )
            for index, (event_id, source_kind) in enumerate(
                _H3_WITNESS_SPECS.get(registry_cell.cell_id, ())
            )
        )
        cells.append(
            create_bridge_baseline_acceptance_cell_v1(
                registry_cell=registry_cell,
                replay_artifact_path=(
                    f"synthetic/{registry_cell.cell_id}.replay.json"
                ),
                replay_artifact_sha256=sha256_value(
                    {"artifact": registry_cell.cell_id}
                ),
                records_identity=sha256_value(
                    {"records": registry_cell.cell_id}
                ),
                execution_identity=sha256_value(
                    {"execution": registry_cell.cell_id}
                ),
                replay_identity=replay_identity,
                proof=proof,
                required_event_witnesses=witnesses,
            )
        )
    sentinel_registry = create_bridge_sentinel_registry_record_v1(
        authority=registry.authority,
        baseline_event_ids=BRIDGE_REQUIRED_EVENT_IDS_V1,
        selected_candidates=(),
        remaining_event_ids=(),
        discovery_status=BridgeSentinelDiscoveryStatusV1.NOT_REQUIRED,
    )
    return create_bridge_acceptance_matrix_v1(
        cells=tuple(cells), sentinel_registry=sentinel_registry
    )


def _rehash_without(payload: dict[str, object], identity_field: str) -> None:
    material = {
        key: value for key, value in payload.items() if key != identity_field
    }
    payload[identity_field] = sha256_value(material)


def test_h3_matrix_rederives_all_twelve_flags_and_five_event_unions() -> None:
    matrix = _synthetic_complete_matrix()
    assert validate_bridge_acceptance_matrix_v1(matrix.to_dict()) == matrix
    result = derive_bridge_acceptance_result_v1(matrix.to_dict())
    assert tuple(result.aggregate_proof_flags) == (
        BRIDGE_ACCEPTANCE_PROOF_FLAG_NAMES_V1
    )
    assert all(result.aggregate_proof_flags.values())
    assert tuple(item.event_id for item in result.required_event_coverage) == (
        BRIDGE_REQUIRED_EVENT_IDS_V1
    )
    expected_cells = {
        "EV-G1-JILI-01": ("B18-001",),
        "EV-G2-ZUILUN-01": ("B18-007",),
        "EV-G2-FUYIN-01": ("B18-007",),
        "EV-G3-QIANCHONG-01": ("B18-013",),
        "EV-G3-SHANGJIAN-01": ("B18-013",),
    }
    assert {
        item.event_id: item.witness_cell_ids
        for item in result.required_event_coverage
    } == expected_cells
    assert result.missing_required_event_ids == ()
    assert result.all_required_events_covered is True
    assert result.all_cell_proofs_proven is True
    assert_bridge_acceptance_aggregate_complete_v1(result)


def test_h3_aggregate_bool_forge_fails_against_cell_rederivation() -> None:
    matrix = _synthetic_complete_matrix()
    attacked = derive_bridge_acceptance_result_v1(matrix).to_dict()
    attacked["aggregate_proof_flags"]["PRODUCTION_REACHABLE"] = False
    _rehash_without(attacked, "result_identity")
    parsed = BridgeAcceptanceResultV1.from_dict(attacked)
    assert parsed.aggregate_proof_flags["PRODUCTION_REACHABLE"] is False
    with pytest.raises(BridgeAcceptanceContractError, match="重新派生"):
        validate_bridge_acceptance_result_v1(matrix, parsed)


def test_h3_cell_proof_flag_forge_fails_closed() -> None:
    matrix_payload = _synthetic_complete_matrix().to_dict()
    cell = matrix_payload["cells"][0]
    cell["proof"]["source_proof_flags"]["STRICT_REPLAY_PROVEN"] = False
    _rehash_without(cell, "cell_identity")
    _rehash_without(matrix_payload, "matrix_identity")
    with pytest.raises(BridgeAcceptanceContractError, match="STRICT_REPLAY_PROVEN"):
        BridgeAcceptanceMatrixV1.from_dict(matrix_payload)

    injected = _synthetic_complete_matrix().to_dict()
    injected["cells"][0]["proof_flags"] = {
        name: True for name in BRIDGE_ACCEPTANCE_PROOF_FLAG_NAMES_V1
    }
    with pytest.raises(BridgeAcceptanceContractError, match="extra="):
        BridgeAcceptanceMatrixV1.from_dict(injected)


def test_h3_event_coverage_forge_fails_against_witness_union() -> None:
    matrix = _synthetic_complete_matrix()
    attacked = derive_bridge_acceptance_result_v1(matrix).to_dict()
    coverage = attacked["required_event_coverage"][0]
    coverage["witness_cell_ids"] = ["B18-007"]
    _rehash_without(coverage, "coverage_identity")
    _rehash_without(attacked, "result_identity")
    parsed = BridgeAcceptanceResultV1.from_dict(attacked)
    with pytest.raises(BridgeAcceptanceContractError, match="重新派生"):
        validate_bridge_acceptance_result_v1(matrix, parsed)


def test_h3_missing_witness_fails_closed_before_cached_union_can_claim_it() -> None:
    attacked = _synthetic_complete_matrix().to_dict()
    first_cell = attacked["cells"][0]
    first_cell["required_event_witnesses"] = []
    _rehash_without(first_cell, "cell_identity")
    _rehash_without(attacked, "matrix_identity")
    with pytest.raises(BridgeAcceptanceContractError, match="event union"):
        validate_bridge_acceptance_matrix_v1(attacked)


def test_h3_wrong_cell_to_event_attribution_fails_closed() -> None:
    attacked = _synthetic_complete_matrix().to_dict()
    witness = attacked["cells"][0]["required_event_witnesses"][0]
    witness["cell_id"] = "B18-007"
    _rehash_without(witness, "witness_binding_identity")
    _rehash_without(attacked["cells"][0], "cell_identity")
    _rehash_without(attacked, "matrix_identity")
    with pytest.raises(BridgeAcceptanceContractError, match="错误cell"):
        BridgeAcceptanceMatrixV1.from_dict(attacked)


def test_h3_matrix_missing_duplicate_and_reorder_cells_fail_closed() -> None:
    for attack in ("missing", "duplicate", "reorder"):
        payload = _synthetic_complete_matrix().to_dict()
        if attack == "missing":
            payload["cells"].pop()
        elif attack == "duplicate":
            payload["cells"][1] = deepcopy(payload["cells"][0])
        else:
            payload["cells"][0], payload["cells"][1] = (
                payload["cells"][1],
                payload["cells"][0],
            )
        _rehash_without(payload, "matrix_identity")
        with pytest.raises(BridgeAcceptanceContractError, match="顺序|缺失|重复"):
            validate_bridge_acceptance_matrix_v1(payload)


def _h4_observation(
    key: tuple[str, FixedAssignment, int],
    event_ids: tuple[str, ...],
) -> BridgeSentinelObservationV1:
    general_key, seat, seed = key
    return create_bridge_sentinel_observation_v1(
        general_key=general_key,
        seat_assignment=seat,
        seed=seed,
        observed_event_ids=event_ids,
        discovery_artifact_sha256=sha256_value(
            {
                "synthetic_discovery": [general_key, seat.value, seed],
                "events": list(event_ids),
            }
        ),
        discovery_witness_identities=tuple(
            sha256_value(
                {
                    "synthetic_discovery_witness": [
                        general_key,
                        seat.value,
                        seed,
                        event_id,
                    ]
                }
            )
            for event_id in event_ids
        ),
    )


def _h4_prefix(
    target_key: tuple[str, FixedAssignment, int],
    events_by_key: dict[tuple[str, FixedAssignment, int], tuple[str, ...]],
) -> tuple[BridgeSentinelObservationV1, ...]:
    observations = []
    for key in canonical_bridge_sentinel_search_keys_v1():
        observations.append(_h4_observation(key, events_by_key.get(key, ())))
        if key == target_key:
            return tuple(observations)
    raise AssertionError(f"target key不在canonical search：{target_key}")


def test_h4_zero_sentinel_when_baseline_union_is_complete() -> None:
    registry = select_bridge_sentinel_registry_v1(
        baseline_event_ids=BRIDGE_REQUIRED_EVENT_IDS_V1,
        observations=(),
    )
    assert registry.discovery_status is BridgeSentinelDiscoveryStatusV1.NOT_REQUIRED
    assert registry.selected_candidates == ()
    assert registry.remaining_event_ids == ()
    assert registry.discovery_is_formal_evidence is False


def test_h4_one_sentinel_closes_one_gap() -> None:
    first_key = canonical_bridge_sentinel_search_keys_v1()[0]
    baseline = tuple(
        item
        for item in BRIDGE_REQUIRED_EVENT_IDS_V1
        if item != "EV-G1-JILI-01"
    )
    observations = (_h4_observation(first_key, ("EV-G1-JILI-01",)),)
    registry = select_bridge_sentinel_registry_v1(
        baseline_event_ids=baseline,
        observations=observations,
    )
    assert registry.discovery_status is BridgeSentinelDiscoveryStatusV1.SELECTED
    assert tuple(item.candidate_id for item in registry.selected_candidates) == (
        "SENTINEL-SHAMOKE-P1-SEED-2",
    )
    assert registry.selected_candidates[0].closes_event_ids == (
        "EV-G1-JILI-01",
    )
    assert registry.selected_candidates[0].discovery_is_formal_evidence is False


def test_h4_one_sentinel_can_close_two_same_general_gaps() -> None:
    target = ("zhugezhan", FixedAssignment.GENERAL_AS_P1, 2)
    gaps = ("EV-G2-ZUILUN-01", "EV-G2-FUYIN-01")
    baseline = tuple(
        item for item in BRIDGE_REQUIRED_EVENT_IDS_V1 if item not in gaps
    )
    observations = _h4_prefix(target, {target: gaps})
    registry = select_bridge_sentinel_registry_v1(
        baseline_event_ids=baseline,
        observations=observations,
    )
    assert len(registry.selected_candidates) == 1
    assert registry.selected_candidates[0].candidate_id == (
        "SENTINEL-ZHUGEZHAN-P1-SEED-2"
    )
    assert registry.selected_candidates[0].closes_event_ids == gaps


def test_h4_deterministic_tie_uses_earliest_canonical_candidate() -> None:
    keys = canonical_bridge_sentinel_search_keys_v1()
    assert keys[:2] == (
        ("shamoke", FixedAssignment.GENERAL_AS_P1, 2),
        ("shamoke", FixedAssignment.GENERAL_AS_P1, 3),
    )
    baseline = tuple(
        item
        for item in BRIDGE_REQUIRED_EVENT_IDS_V1
        if item != "EV-G1-JILI-01"
    )
    earliest = (_h4_observation(keys[0], ("EV-G1-JILI-01",)),)
    registry = select_bridge_sentinel_registry_v1(
        baseline_event_ids=baseline,
        observations=earliest,
    )
    assert registry.selected_candidates[0].seed == 2


def test_h4_wrong_observation_order_fails_closed() -> None:
    keys = canonical_bridge_sentinel_search_keys_v1()
    wrong = (_h4_observation(keys[1], ("EV-G1-JILI-01",)),)
    baseline = tuple(
        item
        for item in BRIDGE_REQUIRED_EVENT_IDS_V1
        if item != "EV-G1-JILI-01"
    )
    with pytest.raises(BridgeAcceptanceContractError, match="continuous canonical"):
        select_bridge_sentinel_registry_v1(
            baseline_event_ids=baseline,
            observations=wrong,
        )


def test_h4_redundant_sentinel_is_removed_and_forged_registry_rejected() -> None:
    seed2 = ("wangyuanji", FixedAssignment.GENERAL_AS_P1, 2)
    seed3 = ("wangyuanji", FixedAssignment.GENERAL_AS_P1, 3)
    qianchong = "EV-G3-QIANCHONG-01"
    shangjian = "EV-G3-SHANGJIAN-01"
    baseline = tuple(
        item
        for item in BRIDGE_REQUIRED_EVENT_IDS_V1
        if item not in (qianchong, shangjian)
    )
    observations = _h4_prefix(
        seed3,
        {
            seed2: (qianchong,),
            seed3: (qianchong, shangjian),
        },
    )
    selected = select_bridge_sentinel_registry_v1(
        baseline_event_ids=baseline,
        observations=observations,
    )
    assert tuple(item.seed for item in selected.selected_candidates) == (3,)
    assert selected.selected_candidates[0].closes_event_ids == (
        qianchong,
        shangjian,
    )

    first_observation = next(item for item in observations if item.search_key == seed2)
    first_material = {
        "schema": BRIDGE_SENTINEL_CANDIDATE_SCHEMA_V1,
        "version": BRIDGE_H_CONTRACT_VERSION,
        "candidate_id": "SENTINEL-WANGYUANJI-P1-SEED-2",
        "general_key": "wangyuanji",
        "seat_assignment": "GENERAL_AS_P1",
        "seed": 2,
        "closes_event_ids": [qianchong],
        "discovery_artifact_sha256": first_observation.discovery_artifact_sha256,
        "discovery_witness_identities": [
            first_observation.discovery_witness_identities[0]
        ],
        "discovery_is_formal_evidence": False,
        "provisional_pending_audit": PROVISIONAL_PENDING_AUDIT,
    }
    forged_first = BridgeSentinelCandidateV1.from_dict(
        _with_identity(first_material, "candidate_identity")
    )
    forged = create_bridge_sentinel_registry_record_v1(
        authority=selected.authority,
        baseline_event_ids=baseline,
        selected_candidates=(forged_first, selected.selected_candidates[0]),
        remaining_event_ids=(),
        discovery_status=BridgeSentinelDiscoveryStatusV1.SELECTED,
    )
    with pytest.raises(BridgeAcceptanceContractError, match="inclusion-minimal"):
        validate_bridge_sentinel_selection_v1(
            forged,
            observations=observations,
        )


def test_h4_exhausted_zero_to_99_returns_discovery_blocked() -> None:
    keys = canonical_bridge_sentinel_search_keys_v1()
    assert len(keys) == 3 * 2 * 97
    observations = tuple(_h4_observation(key, ()) for key in keys)
    baseline = tuple(
        item
        for item in BRIDGE_REQUIRED_EVENT_IDS_V1
        if item != "EV-G1-JILI-01"
    )
    registry = select_bridge_sentinel_registry_v1(
        baseline_event_ids=baseline,
        observations=observations,
    )
    assert registry.discovery_status is (
        BridgeSentinelDiscoveryStatusV1.SENTINEL_DISCOVERY_BLOCKED
    )
    assert registry.remaining_event_ids == ("EV-G1-JILI-01",)
    assert registry.selected_candidates == ()
