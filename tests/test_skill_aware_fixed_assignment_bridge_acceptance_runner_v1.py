# -*- coding: utf-8 -*-
"""Cheap H5 runner/checkpoint/resume tests; no formal matrix gameplay."""

from __future__ import annotations

from pathlib import Path
from types import MappingProxyType, SimpleNamespace

import pytest

from scripts.sgs_engine.replay import sha256_value
from scripts.sgs_engine.skill_aware_fixed_assignment_bridge_acceptance_v1 import (
    BRIDGE_ACCEPTANCE_ARTIFACT_SCHEMA_V1,
    BRIDGE_ACCEPTANCE_CELL_PROOF_SCHEMA_V1,
    BRIDGE_ACCEPTANCE_PROOF_FLAG_NAMES_V1,
    BRIDGE_H_CONTRACT_VERSION,
    BRIDGE_REQUIRED_EVENT_IDS_V1,
    PROVISIONAL_PENDING_AUDIT,
    BridgeAcceptanceArtifactV1,
    BridgeAcceptanceAuthorityV1,
    BridgeAcceptanceCellProofV1,
    BridgeAcceptanceContractError,
    BridgeCellKindV1,
    BridgeSentinelDiscoveryStatusV1,
    bridge_acceptance_baseline_registry_v1,
    create_bridge_baseline_acceptance_cell_v1,
    create_bridge_sentinel_registry_record_v1,
)
from scripts.sgs_engine.skill_aware_fixed_assignment_bridge_acceptance_runner_v1 import (
    BASELINE_EVENT_UNION_FILENAME_V1,
    DISCOVERY_OBSERVATIONS_FILENAME_V1,
    DISCOVERY_PROGRESS_FILENAME_V1,
    MATRIX_FILENAME_V1,
    PROGRESS_FILENAME_V1,
    SENTINEL_REGISTRY_FILENAME_V1,
    BridgeAcceptanceCellBundleV1,
    BridgeAcceptanceRunnerError,
    BridgeCellExecutionV1,
    append_completed_artifact_v1,
    atomic_write_json_v1,
    build_argument_parser_v1,
    build_formal_cell_specs_v1,
    create_discovery_observations_payload_v1,
    create_discovery_union_payload_v1,
    create_initial_progress_v1,
    derive_acceptance_cell_from_bridge_proof_v1,
    execute_formal_cell_production_v1,
    file_sha256_v1,
    load_json_strict_v1,
    run_discovery_mode_v1,
    run_formal_mode_v1,
    validate_progress_v1,
    verify_cell_bundle_production_v1,
)
from scripts.sgs_engine.skill_aware_fixed_assignment_full_game_bridge_replay import (
    BridgeFullGameCellProofV1,
)
import scripts.sgs_engine.skill_aware_fixed_assignment_bridge_acceptance_runner_v1 as runner


ONE64 = "1" * 64
TWO64 = "2" * 64
THREE64 = "3" * 64


def _terminal() -> dict[str, object]:
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


def _sentinel_not_run():
    return create_bridge_sentinel_registry_record_v1(
        authority=BridgeAcceptanceAuthorityV1.current(),
        baseline_event_ids=(),
        selected_candidates=(),
        remaining_event_ids=BRIDGE_REQUIRED_EVENT_IDS_V1,
        discovery_status=BridgeSentinelDiscoveryStatusV1.NOT_RUN,
    )


def _h_proof(identity: str) -> BridgeAcceptanceCellProofV1:
    return BridgeAcceptanceCellProofV1.from_dict(
        {
            "schema": BRIDGE_ACCEPTANCE_CELL_PROOF_SCHEMA_V1,
            "version": BRIDGE_H_CONTRACT_VERSION,
            "trace_scope": "NATURAL_FULL_GAME",
            "finished": True,
            "source_proof_flags": {
                name: True for name in BRIDGE_ACCEPTANCE_PROOF_FLAG_NAMES_V1
            },
            "terminal_invariants": _terminal(),
            "source_cell_proof_identity": identity,
            "provisional_pending_audit": PROVISIONAL_PENDING_AUDIT,
        }
    )


def _synthetic_execution(spec, relative_path: str) -> BridgeCellExecutionV1:
    records_identity = sha256_value({"records": spec.cell_id})
    execution_identity = sha256_value({"execution": spec.cell_id})
    replay_identity = sha256_value({"replay": spec.cell_id})
    replay = {
        "schema": "synthetic-bridge-runner-proof-v1",
        "cell_id": spec.cell_id,
        "records_identity": records_identity,
        "execution_identity": execution_identity,
        "replay_identity": replay_identity,
    }
    source = spec.source_authority
    assert spec.cell_kind is BridgeCellKindV1.BASELINE
    cell = create_bridge_baseline_acceptance_cell_v1(
        registry_cell=source,
        replay_artifact_path=relative_path,
        replay_artifact_sha256=sha256_value(replay),
        records_identity=records_identity,
        execution_identity=execution_identity,
        replay_identity=replay_identity,
        proof=_h_proof(sha256_value({"proof": spec.cell_id})),
        required_event_witnesses=(),
    )
    return BridgeCellExecutionV1(replay_payload=MappingProxyType(replay), cell=cell)


def _synthetic_verifier(spec, bundle):
    assert bundle.cell.cell_id == spec.cell_id
    return bundle.cell


def _artifact(cell_id: str) -> BridgeAcceptanceArtifactV1:
    material = {
        "schema": BRIDGE_ACCEPTANCE_ARTIFACT_SCHEMA_V1,
        "version": BRIDGE_H_CONTRACT_VERSION,
        "cell_id": cell_id,
        "artifact_path": f"cells/{cell_id}.json",
        "artifact_sha256": ONE64,
        "replay_identity": TWO64,
        "cell_identity": THREE64,
        "provisional_pending_audit": PROVISIONAL_PENDING_AUDIT,
    }
    return BridgeAcceptanceArtifactV1(
        **material,
        artifact_identity=sha256_value(material),
    )


def _write_sentinel(output_dir: Path) -> None:
    atomic_write_json_v1(
        output_dir / SENTINEL_REGISTRY_FILENAME_V1,
        _sentinel_not_run().to_dict(),
    )


def _source_proof(
    spec,
    *,
    witnesses=(),
    target_witnesses=(),
    qianchong_choices=(),
    qianchong_grants=(),
    shangjian=(),
) -> tuple[dict[str, object], BridgeFullGameCellProofV1]:
    records_identity = sha256_value({"source-records": spec.cell_id})
    execution_identity = sha256_value({"source-execution": spec.cell_id})
    replay_identity = sha256_value({"source-replay": spec.cell_id})
    replay = {
        "records_identity": records_identity,
        "execution_identity": execution_identity,
        "replay_identity": replay_identity,
    }
    proof = BridgeFullGameCellProofV1(
        cell_id=spec.cell_id,
        general_key=spec.general_key,
        seat_assignment=spec.seat_assignment.value,
        seed=spec.seed,
        trace_scope="NATURAL_FULL_GAME",
        steps=3,
        turns=1,
        winner="p1",
        finish_reason="opponent_confirmed_dead",
        decision_count=3,
        event_count=3,
        random_count=3,
        skill_trace_count=1,
        skill_window_count=len(witnesses),
        witnesses=tuple(MappingProxyType(item) for item in witnesses),
        private_selection_witnesses=(),
        hp_loss_witnesses=(),
        target_effect_first_chance_witnesses=tuple(
            MappingProxyType(item) for item in target_witnesses
        ),
        end_dispatcher_resume=MappingProxyType({"resume_proven": True}),
        terminal_invariants=MappingProxyType(_terminal()),
        strict_replay_proof_flags=MappingProxyType(
            {name: True for name in BRIDGE_ACCEPTANCE_PROOF_FLAG_NAMES_V1}
        ),
        skill_event_coverage="PROVEN",
        proof_flags=MappingProxyType(
            {name: True for name in BRIDGE_ACCEPTANCE_PROOF_FLAG_NAMES_V1}
        ),
        records_identity=records_identity,
        execution_identity=execution_identity,
        replay_identity=replay_identity,
        qianchong_choice_witnesses=tuple(
            MappingProxyType(item) for item in qianchong_choices
        ),
        qianchong_dynamic_grant_witnesses=tuple(
            MappingProxyType(item) for item in qianchong_grants
        ),
        shangjian_condition_witnesses=tuple(
            MappingProxyType(item) for item in shangjian
        ),
        qianchong_event_coverage="PROVEN",
        shangjian_event_coverage="PROVEN",
    )
    return replay, proof


def test_h5_cli_requires_repo_output_mode_and_supports_resume() -> None:
    parser = build_argument_parser_v1()
    args = parser.parse_args(
        [
            "--repo",
            "D:/repo",
            "--output-dir",
            "D:/output",
            "--mode",
            "formal",
            "--resume",
        ]
    )
    assert args.repo == Path("D:/repo")
    assert args.output_dir == Path("D:/output")
    assert args.mode == "formal"
    assert args.resume is True


def test_h5_formal_specs_are_exact_baseline_registry_order() -> None:
    registry = bridge_acceptance_baseline_registry_v1()
    specs = build_formal_cell_specs_v1(registry, _sentinel_not_run())
    assert tuple(item.cell_id for item in specs) == tuple(
        f"B18-{index:03d}" for index in range(1, 19)
    )
    assert all(item.cell_kind is BridgeCellKindV1.BASELINE for item in specs)


def test_h5_progress_accepts_only_strict_continuous_prefix() -> None:
    registry = bridge_acceptance_baseline_registry_v1()
    sentinel = _sentinel_not_run()
    progress = create_initial_progress_v1(registry, sentinel)
    first = append_completed_artifact_v1(progress, _artifact("B18-001"))
    assert first.completed_cell_ids == ("B18-001",)
    with pytest.raises(BridgeAcceptanceRunnerError, match="连续"):
        append_completed_artifact_v1(progress, _artifact("B18-002"))
    with pytest.raises(BridgeAcceptanceRunnerError, match="连续"):
        append_completed_artifact_v1(first, _artifact("B18-001"))
    with pytest.raises(BridgeAcceptanceRunnerError, match="连续"):
        append_completed_artifact_v1(first, _artifact("UNKNOWN"))


@pytest.mark.parametrize(
    "attack", ["reorder", "duplicate", "failed-extra", "failed-future"]
)
def test_h5_resume_progress_shape_attacks_fail_closed(attack: str) -> None:
    registry = bridge_acceptance_baseline_registry_v1()
    sentinel = _sentinel_not_run()
    progress = create_initial_progress_v1(registry, sentinel)
    first = append_completed_artifact_v1(progress, _artifact("B18-001"))
    second = append_completed_artifact_v1(first, _artifact("B18-002"))
    if attack == "reorder":
        completed = ("B18-002", "B18-001")
        artifacts = (second.artifacts[1], second.artifacts[0])
        failed = ()
    elif attack == "duplicate":
        completed = ("B18-001", "B18-001")
        artifacts = (second.artifacts[0], second.artifacts[0])
        failed = ()
    elif attack == "failed-extra":
        completed = second.completed_cell_ids
        artifacts = second.artifacts
        failed = ("UNEXPECTED",)
    else:
        completed = second.completed_cell_ids
        artifacts = second.artifacts
        failed = ("B18-004",)
    with pytest.raises(BridgeAcceptanceContractError):
        forged = runner._progress_record(
            authority=second.authority,
            mode=second.mode,
            ordered_registry_identity=second.ordered_registry_identity,
            sentinel_registry_identity=second.sentinel_registry_identity,
            ordered_expected_cell_ids=second.ordered_expected_cell_ids,
            completed_cell_ids=completed,
            failed_cell_ids=failed,
            artifacts=artifacts,
            final_artifact_exists=False,
        )
        validate_progress_v1(forged, registry=registry, sentinel_registry=sentinel)


def test_h5_atomic_json_and_duplicate_key_loader(tmp_path: Path) -> None:
    path = tmp_path / "atomic.json"
    digest = atomic_write_json_v1(path, {"b": 2, "a": 1})
    assert digest == file_sha256_v1(path)
    assert load_json_strict_v1(path) == {"a": 1, "b": 2}
    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text('{"a":1,"a":2}\n', encoding="utf-8")
    with pytest.raises(BridgeAcceptanceRunnerError, match="重复字段"):
        load_json_strict_v1(duplicate)


def test_h5_partial_run_and_resume_reverify_entire_old_prefix(
    tmp_path: Path,
) -> None:
    output = tmp_path / "formal"
    _write_sentinel(output)
    first = run_formal_mode_v1(
        repo=Path.cwd(),
        output_dir=output,
        resume=False,
        executor=_synthetic_execution,
        verifier=_synthetic_verifier,
        max_new_cells=2,
    )
    assert first.progress.completed_cell_ids == ("B18-001", "B18-002")
    verified: list[str] = []

    def verifier(spec, bundle):
        verified.append(spec.cell_id)
        return _synthetic_verifier(spec, bundle)

    second = run_formal_mode_v1(
        repo=Path.cwd(),
        output_dir=output,
        resume=True,
        executor=_synthetic_execution,
        verifier=verifier,
        max_new_cells=1,
    )
    assert verified == ["B18-001", "B18-002"]
    assert second.progress.completed_cell_ids == (
        "B18-001",
        "B18-002",
        "B18-003",
    )
    assert second.matrix_written is False
    assert second.result_written is False


@pytest.mark.parametrize("attack", ["byte-tamper", "missing", "orphan", "final"])
def test_h5_resume_artifact_attacks_fail_closed(
    tmp_path: Path, attack: str
) -> None:
    output = tmp_path / attack
    _write_sentinel(output)
    run_formal_mode_v1(
        repo=Path.cwd(),
        output_dir=output,
        resume=False,
        executor=_synthetic_execution,
        verifier=_synthetic_verifier,
        max_new_cells=1,
    )
    artifact = output / "cells" / "B18-001.json"
    if attack == "byte-tamper":
        artifact.write_bytes(artifact.read_bytes() + b" ")
    elif attack == "missing":
        artifact.unlink()
    elif attack == "orphan":
        (output / "cells" / "B18-999.json").write_text("{}", encoding="utf-8")
    else:
        (output / MATRIX_FILENAME_V1).write_text("{}", encoding="utf-8")
    with pytest.raises(BridgeAcceptanceContractError):
        run_formal_mode_v1(
            repo=Path.cwd(),
            output_dir=output,
            resume=True,
            executor=_synthetic_execution,
            verifier=_synthetic_verifier,
            max_new_cells=0,
        )


def test_h5_bundle_schema_omission_and_replay_forgery_fail_closed() -> None:
    registry = bridge_acceptance_baseline_registry_v1()
    spec = build_formal_cell_specs_v1(registry, _sentinel_not_run())[0]
    execution = _synthetic_execution(spec, "cells/B18-001.json")
    bundle = BridgeAcceptanceCellBundleV1.create(
        execution.replay_payload, execution.cell
    )
    missing = bundle.to_dict()
    missing.pop("replay_sha256")
    with pytest.raises(BridgeAcceptanceRunnerError, match="字段必须精确"):
        BridgeAcceptanceCellBundleV1.from_dict(missing)
    forged = bundle.to_dict()
    forged["replay"]["cell_id"] = "B18-999"
    forged["bundle_identity"] = sha256_value(
        {key: value for key, value in forged.items() if key != "bundle_identity"}
    )
    with pytest.raises(BridgeAcceptanceContractError):
        BridgeAcceptanceCellBundleV1.from_dict(forged)


def test_h5_pure_discovery_zero_sentinel_and_final_resume_refusal(
    tmp_path: Path,
) -> None:
    output = tmp_path / "discovery"
    atomic_write_json_v1(
        output / BASELINE_EVENT_UNION_FILENAME_V1,
        create_discovery_union_payload_v1(BRIDGE_REQUIRED_EVENT_IDS_V1),
    )
    atomic_write_json_v1(
        output / DISCOVERY_OBSERVATIONS_FILENAME_V1,
        create_discovery_observations_payload_v1(()),
    )
    selected = run_discovery_mode_v1(
        repo=Path.cwd(), output_dir=output, resume=False
    )
    assert selected.discovery_status is BridgeSentinelDiscoveryStatusV1.NOT_REQUIRED
    assert selected.selected_candidates == ()
    assert (output / SENTINEL_REGISTRY_FILENAME_V1).is_file()
    assert (output / DISCOVERY_PROGRESS_FILENAME_V1).is_file()
    with pytest.raises(BridgeAcceptanceRunnerError, match="final artifact"):
        run_discovery_mode_v1(repo=Path.cwd(), output_dir=output, resume=True)


@pytest.mark.parametrize(
    ("cell_index", "source", "expected_events"),
    [
        (
            0,
            {
                "witnesses": (
                    {"cell_id": "B18-001", "skill_id": "sgs_skill_jili"},
                )
            },
            ("EV-G1-JILI-01",),
        ),
        (
            6,
            {
                "witnesses": (
                    {"cell_id": "B18-007", "skill_id": "sgs_skill_zuilun"},
                ),
                "target_witnesses": (
                    {"cell_id": "B18-007", "skill_id": "sgs_skill_fuyin"},
                ),
            },
            ("EV-G2-ZUILUN-01", "EV-G2-FUYIN-01"),
        ),
        (
            12,
            {
                "qianchong_choices": (
                    {"cell_id": "B18-013", "skill_id": "sgs_skill_qianchong"},
                ),
                "qianchong_grants": ({"cell_id": "B18-013", "grant": "weimu"},),
                "shangjian": ({"cell_id": "B18-013", "condition": True},),
            },
            (
                "EV-G3-QIANCHONG-01",
                "EV-G3-QIANCHONG-01",
                "EV-G3-SHANGJIAN-01",
            ),
        ),
    ],
)
def test_h5_source_proof_adapter_derives_required_event_witnesses(
    cell_index: int,
    source: dict[str, tuple[dict[str, object], ...]],
    expected_events: tuple[str, ...],
) -> None:
    registry = bridge_acceptance_baseline_registry_v1()
    spec = build_formal_cell_specs_v1(registry, _sentinel_not_run())[cell_index]
    replay, proof = _source_proof(spec, **source)
    cell = derive_acceptance_cell_from_bridge_proof_v1(
        spec=spec,
        replay_payload=replay,
        source_proof=proof,
        replay_artifact_path=f"cells/{spec.cell_id}.json",
    )
    assert tuple(item.event_id for item in cell.required_event_witnesses) == (
        expected_events
    )
    assert all(
        item.source_replay_identity == proof.replay_identity
        for item in cell.required_event_witnesses
    )


def test_h5_production_executor_delegates_to_existing_authorities(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = bridge_acceptance_baseline_registry_v1()
    spec = build_formal_cell_specs_v1(registry, _sentinel_not_run())[0]
    expected = _synthetic_execution(spec, "cells/B18-001.json")
    calls: list[str] = []
    assignment = SimpleNamespace(
        general_key=spec.general_key,
        seat_assignment=spec.seat_assignment,
        general_player_id=spec.general_player_id,
        no_skill_player_id=spec.no_skill_player_id,
    )
    monkeypatch.setattr(
        runner,
        "create_skill_aware_fixed_assignment_duel_session_v1",
        lambda **kwargs: calls.append("factory") or SimpleNamespace(assignment=assignment),
    )
    monkeypatch.setattr(
        runner,
        "record_natural_full_game_skill_aware_fixed_assignment_bridge_replay_v1",
        lambda **kwargs: calls.append("recorder")
        or SimpleNamespace(to_dict=lambda: dict(expected.replay_payload)),
    )
    cold = object()
    monkeypatch.setattr(
        runner.BridgeFullGameReplayV1,
        "from_dict",
        staticmethod(lambda value: calls.append("cold") or cold),
    )
    monkeypatch.setattr(
        runner,
        "reexecute_skill_aware_fixed_assignment_bridge_replay_v1",
        lambda value: calls.append("strict")
        or SimpleNamespace(
            replay_identity=expected.cell.replay_identity, finished=True
        ),
    )
    source_proof = SimpleNamespace(replay_identity=expected.cell.replay_identity)
    monkeypatch.setattr(
        runner,
        "derive_bridge_full_game_cell_proof_v1",
        lambda value: calls.append("derive") or source_proof,
    )
    monkeypatch.setattr(
        runner,
        "derive_acceptance_cell_from_bridge_proof_v1",
        lambda **kwargs: calls.append("adapt") or expected.cell,
    )
    actual = execute_formal_cell_production_v1(spec, "cells/B18-001.json")
    assert actual.cell == expected.cell
    assert calls == ["factory", "recorder", "cold", "strict", "derive", "adapt"]


def test_h5_default_resume_verifier_cold_reexecutes_before_accepting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec = build_formal_cell_specs_v1(
        bridge_acceptance_baseline_registry_v1(), _sentinel_not_run()
    )[0]
    execution = _synthetic_execution(spec, "cells/B18-001.json")
    bundle = BridgeAcceptanceCellBundleV1.create(
        execution.replay_payload, execution.cell
    )
    calls: list[str] = []
    cold = object()
    monkeypatch.setattr(
        runner.BridgeFullGameReplayV1,
        "from_dict",
        staticmethod(lambda value: calls.append("cold") or cold),
    )
    monkeypatch.setattr(
        runner,
        "reexecute_skill_aware_fixed_assignment_bridge_replay_v1",
        lambda value: calls.append("strict")
        or SimpleNamespace(
            replay_identity=execution.cell.replay_identity, finished=True
        ),
    )
    source_proof = SimpleNamespace(replay_identity=execution.cell.replay_identity)
    monkeypatch.setattr(
        runner,
        "derive_bridge_full_game_cell_proof_v1",
        lambda value: calls.append("derive") or source_proof,
    )
    monkeypatch.setattr(
        runner,
        "derive_acceptance_cell_from_bridge_proof_v1",
        lambda **kwargs: calls.append("adapt") or execution.cell,
    )
    assert verify_cell_bundle_production_v1(spec, bundle) == execution.cell
    assert calls == ["cold", "strict", "derive", "adapt"]


def test_h5_current_recorder_fails_closed_for_unfrozen_sentinel() -> None:
    forged = SimpleNamespace(cell_kind=BridgeCellKindV1.SENTINEL)
    with pytest.raises(BridgeAcceptanceRunnerError, match="未授权sentinel"):
        execute_formal_cell_production_v1(forged, "cells/sentinel.json")
