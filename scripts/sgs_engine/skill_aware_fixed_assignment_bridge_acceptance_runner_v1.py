# -*- coding: utf-8 -*-
"""Bridge-H provisional runner, atomic checkpoint, and strict resume plumbing.

This module orchestrates the existing canonical Bridge factory, natural full-game
recorder, cold parser, strict reexecutor, and cell-proof derivation.  It contains
no gameplay implementation.  All output remains PROVISIONAL_PENDING_AUDIT=YES.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
from types import MappingProxyType
from typing import Callable, Mapping, Sequence
from uuid import uuid4

from .replay import canonical_json, sha256_value
from .skill_aware_fixed_assignment_bridge_acceptance_v1 import (
    BRIDGE_ACCEPTANCE_ARTIFACT_SCHEMA_V1,
    BRIDGE_ACCEPTANCE_CELL_PROOF_SCHEMA_V1,
    BRIDGE_ACCEPTANCE_PROGRESS_SCHEMA_V1,
    BRIDGE_ACCEPTANCE_PROOF_FLAG_NAMES_V1,
    BRIDGE_H_CONTRACT_VERSION,
    BRIDGE_REQUIRED_EVENT_IDS_V1,
    PROVISIONAL_PENDING_AUDIT,
    BridgeAcceptanceArtifactV1,
    BridgeAcceptanceAuthorityV1,
    BridgeAcceptanceCellProofV1,
    BridgeAcceptanceCellV1,
    BridgeAcceptanceContractError,
    BridgeAcceptanceIdentityError,
    BridgeAcceptanceProgressV1,
    BridgeAcceptanceRegistryCellV1,
    BridgeAcceptanceRegistryV1,
    BridgeAcceptanceRunModeV1,
    BridgeCellKindV1,
    BridgeRequiredEventWitnessV1,
    BridgeSentinelCandidateV1,
    BridgeSentinelObservationV1,
    BridgeSentinelRegistryV1,
    assert_bridge_acceptance_aggregate_complete_v1,
    bridge_acceptance_baseline_registry_v1,
    bridge_acceptance_ordered_registry_identity_v1,
    create_bridge_acceptance_matrix_v1,
    create_bridge_baseline_acceptance_cell_v1,
    create_bridge_required_event_witness_v1,
    create_bridge_sentinel_acceptance_cell_v1,
    derive_bridge_acceptance_result_v1,
    select_bridge_sentinel_registry_v1,
)
from .skill_aware_fixed_assignment_full_game_bridge import (
    FixedAssignment,
    create_skill_aware_fixed_assignment_duel_session_v1,
)
from .skill_aware_fixed_assignment_full_game_bridge_replay import (
    BridgeFullGameCellProofV1,
    BridgeFullGameReplayV1,
    derive_bridge_full_game_cell_proof_v1,
    record_natural_full_game_skill_aware_fixed_assignment_bridge_replay_v1,
    reexecute_skill_aware_fixed_assignment_bridge_replay_v1,
)


BRIDGE_ACCEPTANCE_RUNNER_VERSION_V1 = 1
BRIDGE_ACCEPTANCE_CELL_BUNDLE_SCHEMA_V1 = (
    "sgs-bridge-acceptance-cell-bundle-v1"
)
BRIDGE_ACCEPTANCE_DISCOVERY_UNION_SCHEMA_V1 = (
    "sgs-bridge-acceptance-discovery-union-v1"
)
BRIDGE_ACCEPTANCE_DISCOVERY_OBSERVATIONS_SCHEMA_V1 = (
    "sgs-bridge-acceptance-discovery-observations-v1"
)

PROGRESS_FILENAME_V1 = "progress.json"
DISCOVERY_PROGRESS_FILENAME_V1 = "discovery_progress.json"
SENTINEL_REGISTRY_FILENAME_V1 = "sentinel_registry.json"
BASELINE_EVENT_UNION_FILENAME_V1 = "baseline_event_union.json"
DISCOVERY_OBSERVATIONS_FILENAME_V1 = "discovery_observations.json"
MATRIX_FILENAME_V1 = "matrix.json"
RESULT_FILENAME_V1 = "result.json"
CELL_DIRECTORY_V1 = "cells"

_CELL_BUNDLE_FIELDS_V1 = frozenset(
    {
        "schema",
        "version",
        "replay",
        "replay_sha256",
        "cell",
        "bundle_identity",
        "provisional_pending_audit",
    }
)
_DISCOVERY_UNION_FIELDS_V1 = frozenset(
    {
        "schema",
        "version",
        "authority",
        "baseline_event_ids",
        "union_identity",
        "provisional_pending_audit",
    }
)
_DISCOVERY_OBSERVATIONS_FIELDS_V1 = frozenset(
    {
        "schema",
        "version",
        "authority",
        "observations",
        "observations_identity",
        "provisional_pending_audit",
    }
)


class BridgeAcceptanceRunnerError(BridgeAcceptanceContractError):
    """The H5 runner or resume boundary failed closed."""


def _exact_object(value: object, label: str) -> dict[str, object]:
    if type(value) is not dict or any(type(key) is not str for key in value):
        raise BridgeAcceptanceRunnerError(f"{label}必须是精确JSON object")
    return value


def _exact_fields(
    value: Mapping[str, object], expected: frozenset[str], label: str
) -> None:
    actual = frozenset(value)
    if actual != expected:
        raise BridgeAcceptanceRunnerError(
            f"{label}字段必须精确匹配；"
            f"missing={sorted(expected - actual)}, extra={sorted(actual - expected)}"
        )


def _duplicate_rejecting_object(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise BridgeAcceptanceRunnerError(f"JSON包含重复字段：{key}")
        result[key] = value
    return result


def load_json_strict_v1(path: Path) -> object:
    """Load one UTF-8 JSON document while rejecting duplicate object keys."""

    try:
        text = path.read_text(encoding="utf-8")
        return json.loads(text, object_pairs_hook=_duplicate_rejecting_object)
    except BridgeAcceptanceRunnerError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise BridgeAcceptanceRunnerError(f"无法严格读取JSON：{path}") from exc


def _canonical_bytes(value: object) -> bytes:
    return (canonical_json(value) + "\n").encode("utf-8")


def _bytes_sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def file_sha256_v1(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            while True:
                block = handle.read(1024 * 1024)
                if not block:
                    break
                digest.update(block)
    except OSError as exc:
        raise BridgeAcceptanceRunnerError(f"无法读取artifact：{path}") from exc
    return digest.hexdigest()


def atomic_write_json_v1(path: Path, value: object) -> str:
    """Atomically replace one JSON artifact and return its exact byte hash."""

    payload = _canonical_bytes(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except OSError as exc:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise BridgeAcceptanceRunnerError(f"原子写入失败：{path}") from exc
    return _bytes_sha256(payload)


def _current_repository_root() -> Path:
    return Path(__file__).resolve().parents[2]


def validate_repo_and_output_v1(repo: Path, output_dir: Path) -> tuple[Path, Path]:
    repo_root = repo.resolve(strict=True)
    current_root = _current_repository_root()
    if repo_root != current_root:
        raise BridgeAcceptanceRunnerError(
            f"--repo必须精确指向当前Bridge checkout：{current_root}"
        )
    output_root = output_dir.resolve(strict=False)
    if output_root == repo_root or repo_root in output_root.parents:
        raise BridgeAcceptanceRunnerError("--output-dir必须位于repo外")
    return repo_root, output_root


def _artifact_path(output_root: Path, relative_path: str) -> Path:
    relative = Path(relative_path)
    if relative.is_absolute() or ".." in relative.parts:
        raise BridgeAcceptanceRunnerError("artifact_path必须是output内相对路径")
    resolved = (output_root / relative).resolve(strict=False)
    if output_root != resolved and output_root not in resolved.parents:
        raise BridgeAcceptanceRunnerError("artifact_path越出output-dir")
    return resolved


def _cell_relative_path(cell_id: str) -> str:
    if type(cell_id) is not str or not cell_id:
        raise BridgeAcceptanceRunnerError("cell_id必须是非空字符串")
    if any(character in cell_id for character in ("/", "\\", ":")):
        raise BridgeAcceptanceRunnerError("cell_id不得包含路径字符")
    return f"{CELL_DIRECTORY_V1}/{cell_id}.json"


@dataclass(frozen=True, slots=True)
class BridgeRunnerCellSpecV1:
    cell_kind: BridgeCellKindV1
    cell_id: str
    general_key: str
    seat_assignment: FixedAssignment
    general_player_id: str
    no_skill_player_id: str
    seed: int
    registry_cell_identity: str
    source_authority: BridgeAcceptanceRegistryCellV1 | BridgeSentinelCandidateV1

    def __post_init__(self) -> None:
        if type(self.cell_kind) is not BridgeCellKindV1:
            raise BridgeAcceptanceRunnerError("runner cell_kind类型不匹配")
        if type(self.seat_assignment) is not FixedAssignment:
            raise BridgeAcceptanceRunnerError("runner seat类型不匹配")
        if type(self.seed) is not int or self.seed < 0:
            raise BridgeAcceptanceRunnerError("runner seed必须是非负精确整数")
        expected_general = (
            "p1"
            if self.seat_assignment is FixedAssignment.GENERAL_AS_P1
            else "p2"
        )
        if (
            self.general_player_id != expected_general
            or self.no_skill_player_id
            != ("p2" if expected_general == "p1" else "p1")
        ):
            raise BridgeAcceptanceRunnerError("runner seat/player映射不匹配")
        if self.cell_kind is BridgeCellKindV1.BASELINE:
            if type(self.source_authority) is not BridgeAcceptanceRegistryCellV1:
                raise BridgeAcceptanceRunnerError("baseline spec必须绑定registry row")
            source = self.source_authority
            expected = (
                source.cell_id,
                source.general_key,
                source.seat_assignment,
                source.general_player_id,
                source.no_skill_player_id,
                source.seed,
                source.registry_cell_identity,
            )
        else:
            if type(self.source_authority) is not BridgeSentinelCandidateV1:
                raise BridgeAcceptanceRunnerError("sentinel spec必须绑定H4 candidate")
            source = self.source_authority
            expected = (
                source.candidate_id,
                source.general_key,
                source.seat_assignment,
                self.general_player_id,
                self.no_skill_player_id,
                source.seed,
                source.candidate_identity,
            )
        actual = (
            self.cell_id,
            self.general_key,
            self.seat_assignment,
            self.general_player_id,
            self.no_skill_player_id,
            self.seed,
            self.registry_cell_identity,
        )
        if actual != expected:
            raise BridgeAcceptanceRunnerError("runner spec与source authority不一致")


def build_formal_cell_specs_v1(
    registry: BridgeAcceptanceRegistryV1,
    sentinel_registry: BridgeSentinelRegistryV1,
) -> tuple[BridgeRunnerCellSpecV1, ...]:
    current_registry = bridge_acceptance_baseline_registry_v1()
    if registry != current_registry:
        raise BridgeAcceptanceIdentityError("runner registry不是current BASELINE_18 view")
    if sentinel_registry.authority != registry.authority:
        raise BridgeAcceptanceIdentityError("runner sentinel authority不匹配")
    specs: list[BridgeRunnerCellSpecV1] = []
    for source in registry.cells:
        specs.append(
            BridgeRunnerCellSpecV1(
                cell_kind=BridgeCellKindV1.BASELINE,
                cell_id=source.cell_id,
                general_key=source.general_key,
                seat_assignment=source.seat_assignment,
                general_player_id=source.general_player_id,
                no_skill_player_id=source.no_skill_player_id,
                seed=source.seed,
                registry_cell_identity=source.registry_cell_identity,
                source_authority=source,
            )
        )
    for source in sentinel_registry.selected_candidates:
        general_player_id = (
            "p1"
            if source.seat_assignment is FixedAssignment.GENERAL_AS_P1
            else "p2"
        )
        specs.append(
            BridgeRunnerCellSpecV1(
                cell_kind=BridgeCellKindV1.SENTINEL,
                cell_id=source.candidate_id,
                general_key=source.general_key,
                seat_assignment=source.seat_assignment,
                general_player_id=general_player_id,
                no_skill_player_id=(
                    "p2" if general_player_id == "p1" else "p1"
                ),
                seed=source.seed,
                registry_cell_identity=source.candidate_identity,
                source_authority=source,
            )
        )
    identifiers = tuple(item.cell_id for item in specs)
    if len(identifiers) != len(set(identifiers)):
        raise BridgeAcceptanceRunnerError("formal ordered registry包含重复cell")
    return tuple(specs)


@dataclass(frozen=True, slots=True)
class BridgeAcceptanceCellBundleV1:
    schema: str
    version: int
    replay: Mapping[str, object]
    replay_sha256: str
    cell: BridgeAcceptanceCellV1
    bundle_identity: str
    provisional_pending_audit: str

    def __post_init__(self) -> None:
        if self.schema != BRIDGE_ACCEPTANCE_CELL_BUNDLE_SCHEMA_V1:
            raise BridgeAcceptanceRunnerError("cell bundle schema不匹配")
        if (
            type(self.version) is not int
            or self.version != BRIDGE_ACCEPTANCE_RUNNER_VERSION_V1
        ):
            raise BridgeAcceptanceRunnerError("cell bundle version不匹配")
        if not isinstance(self.replay, Mapping):
            raise BridgeAcceptanceRunnerError("cell bundle replay必须是mapping")
        if self.replay_sha256 != sha256_value(self.replay):
            raise BridgeAcceptanceIdentityError("cell bundle replay_sha256不匹配")
        if type(self.cell) is not BridgeAcceptanceCellV1:
            raise BridgeAcceptanceRunnerError("cell bundle cell类型不匹配")
        if self.cell.replay_artifact_sha256 != self.replay_sha256:
            raise BridgeAcceptanceIdentityError("cell与bundle replay hash不匹配")
        for field in ("records_identity", "execution_identity", "replay_identity"):
            if self.replay.get(field) != getattr(self.cell, field):
                raise BridgeAcceptanceIdentityError(
                    f"cell与bundle {field}不匹配"
                )
        if self.bundle_identity != self.compute_identity():
            raise BridgeAcceptanceIdentityError("bundle_identity不匹配")
        if self.provisional_pending_audit != PROVISIONAL_PENDING_AUDIT:
            raise BridgeAcceptanceRunnerError("cell bundle缺少provisional标记")

    def identity_material(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "version": self.version,
            "replay": dict(self.replay),
            "replay_sha256": self.replay_sha256,
            "cell": self.cell.to_dict(),
            "provisional_pending_audit": self.provisional_pending_audit,
        }

    def compute_identity(self) -> str:
        return sha256_value(self.identity_material())

    @classmethod
    def create(
        cls, replay_payload: Mapping[str, object], cell: BridgeAcceptanceCellV1
    ) -> "BridgeAcceptanceCellBundleV1":
        replay = _exact_object(
            json.loads(canonical_json(replay_payload)), "cell bundle replay"
        )
        material = {
            "schema": BRIDGE_ACCEPTANCE_CELL_BUNDLE_SCHEMA_V1,
            "version": BRIDGE_ACCEPTANCE_RUNNER_VERSION_V1,
            "replay": replay,
            "replay_sha256": sha256_value(replay),
            "cell": cell.to_dict(),
            "provisional_pending_audit": PROVISIONAL_PENDING_AUDIT,
        }
        return cls(
            schema=BRIDGE_ACCEPTANCE_CELL_BUNDLE_SCHEMA_V1,
            version=BRIDGE_ACCEPTANCE_RUNNER_VERSION_V1,
            replay=MappingProxyType(replay),
            replay_sha256=sha256_value(replay),
            cell=cell,
            bundle_identity=sha256_value(material),
            provisional_pending_audit=PROVISIONAL_PENDING_AUDIT,
        )

    @classmethod
    def from_dict(cls, value: object) -> "BridgeAcceptanceCellBundleV1":
        data = _exact_object(value, "cell bundle")
        _exact_fields(data, _CELL_BUNDLE_FIELDS_V1, "cell bundle")
        replay = _exact_object(data["replay"], "cell bundle replay")
        if type(data["version"]) is not int:
            raise BridgeAcceptanceRunnerError("cell bundle version必须是精确整数")
        for field in ("schema", "replay_sha256", "bundle_identity"):
            if type(data[field]) is not str:
                raise BridgeAcceptanceRunnerError(f"cell bundle {field}类型不匹配")
        return cls(
            schema=data["schema"],
            version=data["version"],
            replay=MappingProxyType(replay),
            replay_sha256=data["replay_sha256"],
            cell=BridgeAcceptanceCellV1.from_dict(data["cell"]),
            bundle_identity=data["bundle_identity"],
            provisional_pending_audit=data["provisional_pending_audit"],
        )

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_material(), "bundle_identity": self.bundle_identity}


@dataclass(frozen=True, slots=True)
class BridgeCellExecutionV1:
    replay_payload: Mapping[str, object]
    cell: BridgeAcceptanceCellV1

    def __post_init__(self) -> None:
        if not isinstance(self.replay_payload, Mapping):
            raise BridgeAcceptanceRunnerError("execution replay_payload类型不匹配")
        if type(self.cell) is not BridgeAcceptanceCellV1:
            raise BridgeAcceptanceRunnerError("execution cell类型不匹配")


def _progress_record(
    *,
    authority: BridgeAcceptanceAuthorityV1,
    mode: BridgeAcceptanceRunModeV1,
    ordered_registry_identity: str,
    sentinel_registry_identity: str,
    ordered_expected_cell_ids: tuple[str, ...],
    completed_cell_ids: tuple[str, ...],
    failed_cell_ids: tuple[str, ...],
    artifacts: tuple[BridgeAcceptanceArtifactV1, ...],
    final_artifact_exists: bool,
) -> BridgeAcceptanceProgressV1:
    material = {
        "schema": BRIDGE_ACCEPTANCE_PROGRESS_SCHEMA_V1,
        "version": BRIDGE_H_CONTRACT_VERSION,
        "authority": authority.to_dict(),
        "mode": mode.value,
        "ordered_registry_identity": ordered_registry_identity,
        "sentinel_registry_identity": sentinel_registry_identity,
        "ordered_expected_cell_ids": list(ordered_expected_cell_ids),
        "completed_cell_ids": list(completed_cell_ids),
        "failed_cell_ids": list(failed_cell_ids),
        "artifacts": [item.to_dict() for item in artifacts],
        "final_artifact_exists": final_artifact_exists,
        "provisional_pending_audit": PROVISIONAL_PENDING_AUDIT,
    }
    return BridgeAcceptanceProgressV1(
        schema=BRIDGE_ACCEPTANCE_PROGRESS_SCHEMA_V1,
        version=BRIDGE_H_CONTRACT_VERSION,
        authority=authority,
        mode=mode,
        ordered_registry_identity=ordered_registry_identity,
        sentinel_registry_identity=sentinel_registry_identity,
        ordered_expected_cell_ids=ordered_expected_cell_ids,
        completed_cell_ids=completed_cell_ids,
        failed_cell_ids=failed_cell_ids,
        artifacts=artifacts,
        final_artifact_exists=final_artifact_exists,
        progress_identity=sha256_value(material),
        provisional_pending_audit=PROVISIONAL_PENDING_AUDIT,
    )


def create_initial_progress_v1(
    registry: BridgeAcceptanceRegistryV1,
    sentinel_registry: BridgeSentinelRegistryV1,
) -> BridgeAcceptanceProgressV1:
    specs = build_formal_cell_specs_v1(registry, sentinel_registry)
    return _progress_record(
        authority=registry.authority,
        mode=BridgeAcceptanceRunModeV1.FORMAL,
        ordered_registry_identity=bridge_acceptance_ordered_registry_identity_v1(
            registry, sentinel_registry
        ),
        sentinel_registry_identity=sentinel_registry.registry_identity,
        ordered_expected_cell_ids=tuple(item.cell_id for item in specs),
        completed_cell_ids=(),
        failed_cell_ids=(),
        artifacts=(),
        final_artifact_exists=False,
    )


def validate_progress_v1(
    value: object,
    *,
    registry: BridgeAcceptanceRegistryV1,
    sentinel_registry: BridgeSentinelRegistryV1,
) -> BridgeAcceptanceProgressV1:
    progress = (
        value
        if type(value) is BridgeAcceptanceProgressV1
        else BridgeAcceptanceProgressV1.from_dict(value)
    )
    expected = create_initial_progress_v1(registry, sentinel_registry)
    if progress.authority != expected.authority:
        raise BridgeAcceptanceIdentityError("resume authority与current source不匹配")
    if progress.mode is not BridgeAcceptanceRunModeV1.FORMAL:
        raise BridgeAcceptanceRunnerError("formal resume mode不匹配")
    for field in (
        "ordered_registry_identity",
        "sentinel_registry_identity",
        "ordered_expected_cell_ids",
    ):
        if getattr(progress, field) != getattr(expected, field):
            raise BridgeAcceptanceIdentityError(f"resume {field}不匹配")
    if len(progress.completed_cell_ids) != len(set(progress.completed_cell_ids)):
        raise BridgeAcceptanceRunnerError("resume completed prefix包含重复cell")
    prefix = progress.ordered_expected_cell_ids[: len(progress.completed_cell_ids)]
    if progress.completed_cell_ids != prefix:
        raise BridgeAcceptanceRunnerError("resume completed cells不是strict continuous prefix")
    if len(progress.failed_cell_ids) != len(set(progress.failed_cell_ids)):
        raise BridgeAcceptanceRunnerError("resume failed cells包含重复cell")
    if any(
        item not in progress.ordered_expected_cell_ids
        for item in progress.failed_cell_ids
    ):
        raise BridgeAcceptanceRunnerError("resume failed cells包含unexpected cell")
    allowed_failed = (
        ()
        if len(progress.completed_cell_ids) == len(progress.ordered_expected_cell_ids)
        else (progress.ordered_expected_cell_ids[len(progress.completed_cell_ids)],)
    )
    if progress.failed_cell_ids not in ((), allowed_failed):
        raise BridgeAcceptanceRunnerError(
            "resume failed cells只能记录continuous prefix下一项"
        )
    if progress.final_artifact_exists and (
        progress.completed_cell_ids != progress.ordered_expected_cell_ids
    ):
        raise BridgeAcceptanceRunnerError("incomplete prefix不得声明final artifact")
    for artifact, expected_cell_id in zip(
        progress.artifacts, progress.completed_cell_ids, strict=True
    ):
        if artifact.cell_id != expected_cell_id:
            raise BridgeAcceptanceRunnerError("resume artifact顺序不匹配")
        if artifact.artifact_path != _cell_relative_path(expected_cell_id):
            raise BridgeAcceptanceRunnerError("resume artifact_path不是canonical路径")
    return progress


def _artifact_record(
    *, bundle: BridgeAcceptanceCellBundleV1, relative_path: str, byte_sha256: str
) -> BridgeAcceptanceArtifactV1:
    material = {
        "schema": BRIDGE_ACCEPTANCE_ARTIFACT_SCHEMA_V1,
        "version": BRIDGE_H_CONTRACT_VERSION,
        "cell_id": bundle.cell.cell_id,
        "artifact_path": relative_path,
        "artifact_sha256": byte_sha256,
        "replay_identity": bundle.cell.replay_identity,
        "cell_identity": bundle.cell.cell_identity,
        "provisional_pending_audit": PROVISIONAL_PENDING_AUDIT,
    }
    return BridgeAcceptanceArtifactV1(
        schema=BRIDGE_ACCEPTANCE_ARTIFACT_SCHEMA_V1,
        version=BRIDGE_H_CONTRACT_VERSION,
        cell_id=bundle.cell.cell_id,
        artifact_path=relative_path,
        artifact_sha256=byte_sha256,
        replay_identity=bundle.cell.replay_identity,
        cell_identity=bundle.cell.cell_identity,
        artifact_identity=sha256_value(material),
        provisional_pending_audit=PROVISIONAL_PENDING_AUDIT,
    )


def append_completed_artifact_v1(
    progress: BridgeAcceptanceProgressV1,
    artifact: BridgeAcceptanceArtifactV1,
) -> BridgeAcceptanceProgressV1:
    if progress.final_artifact_exists:
        raise BridgeAcceptanceRunnerError("final progress不得追加cell")
    index = len(progress.completed_cell_ids)
    if index >= len(progress.ordered_expected_cell_ids):
        raise BridgeAcceptanceRunnerError("formal registry已完成，禁止unexpected cell")
    expected = progress.ordered_expected_cell_ids[index]
    if artifact.cell_id != expected:
        raise BridgeAcceptanceRunnerError(
            f"cell completion必须连续；expected={expected}, actual={artifact.cell_id}"
        )
    return _progress_record(
        authority=progress.authority,
        mode=progress.mode,
        ordered_registry_identity=progress.ordered_registry_identity,
        sentinel_registry_identity=progress.sentinel_registry_identity,
        ordered_expected_cell_ids=progress.ordered_expected_cell_ids,
        completed_cell_ids=progress.completed_cell_ids + (artifact.cell_id,),
        failed_cell_ids=tuple(
            item for item in progress.failed_cell_ids if item != artifact.cell_id
        ),
        artifacts=progress.artifacts + (artifact,),
        final_artifact_exists=False,
    )


def mark_failed_cell_v1(
    progress: BridgeAcceptanceProgressV1, cell_id: str
) -> BridgeAcceptanceProgressV1:
    index = len(progress.completed_cell_ids)
    if index >= len(progress.ordered_expected_cell_ids):
        raise BridgeAcceptanceRunnerError("completed registry不得记录failed cell")
    if cell_id != progress.ordered_expected_cell_ids[index]:
        raise BridgeAcceptanceRunnerError("failed cell必须是continuous prefix下一项")
    failed = (
        progress.failed_cell_ids
        if cell_id in progress.failed_cell_ids
        else progress.failed_cell_ids + (cell_id,)
    )
    return _progress_record(
        authority=progress.authority,
        mode=progress.mode,
        ordered_registry_identity=progress.ordered_registry_identity,
        sentinel_registry_identity=progress.sentinel_registry_identity,
        ordered_expected_cell_ids=progress.ordered_expected_cell_ids,
        completed_cell_ids=progress.completed_cell_ids,
        failed_cell_ids=failed,
        artifacts=progress.artifacts,
        final_artifact_exists=False,
    )


def _proof_source_material(proof: BridgeFullGameCellProofV1) -> dict[str, object]:
    return {
        "summary": proof.to_dict(),
        "witnesses": [dict(item) for item in proof.witnesses],
        "private_selection_witnesses": [
            dict(item) for item in proof.private_selection_witnesses
        ],
        "hp_loss_witnesses": [dict(item) for item in proof.hp_loss_witnesses],
        "target_effect_first_chance_witnesses": [
            dict(item) for item in proof.target_effect_first_chance_witnesses
        ],
        "end_dispatcher_resume": dict(proof.end_dispatcher_resume),
        "strict_replay_proof_flags": dict(proof.strict_replay_proof_flags),
        "qianchong_choice_witnesses": [
            dict(item) for item in proof.qianchong_choice_witnesses
        ],
        "qianchong_dynamic_grant_witnesses": [
            dict(item) for item in proof.qianchong_dynamic_grant_witnesses
        ],
        "shangjian_condition_witnesses": [
            dict(item) for item in proof.shangjian_condition_witnesses
        ],
    }


def _normalize_event_witnesses_v1(
    proof: BridgeFullGameCellProofV1,
) -> tuple[BridgeRequiredEventWitnessV1, ...]:
    normalized: list[BridgeRequiredEventWitnessV1] = []

    def add(
        event_id: str,
        source_kind: str,
        source_index: int,
        raw: Mapping[str, object],
    ) -> None:
        if raw.get("cell_id") != proof.cell_id:
            raise BridgeAcceptanceRunnerError("source witness绑定到错误cell")
        normalized.append(
            create_bridge_required_event_witness_v1(
                event_id=event_id,
                cell_id=proof.cell_id,
                source_kind=source_kind,
                source_index=source_index,
                source_witness_identity=sha256_value(raw),
                source_replay_identity=proof.replay_identity,
            )
        )

    for index, raw in enumerate(proof.witnesses):
        skill_id = raw.get("skill_id")
        if skill_id == "sgs_skill_jili":
            add("EV-G1-JILI-01", "SKILL_OPTIONAL_WINDOW", index, raw)
        elif skill_id == "sgs_skill_zuilun":
            if proof.end_dispatcher_resume.get("resume_proven") is not True:
                raise BridgeAcceptanceRunnerError(
                    "Zuilun witness缺少fresh END dispatcher resume proof"
                )
            add(
                "EV-G2-ZUILUN-01",
                "SKILL_OPTIONAL_WINDOW_END_RESUME",
                index,
                raw,
            )
    for index, raw in enumerate(proof.target_effect_first_chance_witnesses):
        if raw.get("skill_id") == "sgs_skill_fuyin":
            add("EV-G2-FUYIN-01", "TARGET_EFFECT_FIRST_CHANCE", index, raw)
    for index, raw in enumerate(proof.qianchong_choice_witnesses):
        if raw.get("skill_id") != "sgs_skill_qianchong":
            raise BridgeAcceptanceRunnerError("Qianchong choice witness skill_id错误")
        add("EV-G3-QIANCHONG-01", "QIANCHONG_CHOICE", index, raw)
    for index, raw in enumerate(proof.qianchong_dynamic_grant_witnesses):
        add("EV-G3-QIANCHONG-01", "QIANCHONG_DYNAMIC_GRANT", index, raw)
    for index, raw in enumerate(proof.shangjian_condition_witnesses):
        add("EV-G3-SHANGJIAN-01", "SHANGJIAN_LIVE_CONDITION", index, raw)
    return tuple(normalized)


def derive_acceptance_cell_from_bridge_proof_v1(
    *,
    spec: BridgeRunnerCellSpecV1,
    replay_payload: Mapping[str, object],
    source_proof: BridgeFullGameCellProofV1,
    replay_artifact_path: str,
) -> BridgeAcceptanceCellV1:
    expected_proof_key = (
        spec.cell_id,
        spec.general_key,
        spec.seat_assignment.value,
        spec.seed,
        "NATURAL_FULL_GAME",
    )
    actual_proof_key = (
        source_proof.cell_id,
        source_proof.general_key,
        source_proof.seat_assignment,
        source_proof.seed,
        source_proof.trace_scope,
    )
    if actual_proof_key != expected_proof_key:
        raise BridgeAcceptanceRunnerError("fresh source proof与runner cell spec不一致")
    for field in ("records_identity", "execution_identity", "replay_identity"):
        if replay_payload.get(field) != getattr(source_proof, field):
            raise BridgeAcceptanceIdentityError(f"source proof {field}与replay不一致")
    flags = {
        name: source_proof.proof_flags.get(name)
        for name in BRIDGE_ACCEPTANCE_PROOF_FLAG_NAMES_V1
    }
    h_proof = BridgeAcceptanceCellProofV1.from_dict(
        {
            "schema": BRIDGE_ACCEPTANCE_CELL_PROOF_SCHEMA_V1,
            "version": BRIDGE_H_CONTRACT_VERSION,
            "trace_scope": source_proof.trace_scope,
            "finished": source_proof.terminal_invariants.get("finished"),
            "source_proof_flags": flags,
            "terminal_invariants": json.loads(
                canonical_json(source_proof.terminal_invariants)
            ),
            "source_cell_proof_identity": sha256_value(
                _proof_source_material(source_proof)
            ),
            "provisional_pending_audit": PROVISIONAL_PENDING_AUDIT,
        }
    )
    witnesses = _normalize_event_witnesses_v1(source_proof)
    common = {
        "replay_artifact_path": replay_artifact_path,
        "replay_artifact_sha256": sha256_value(replay_payload),
        "records_identity": source_proof.records_identity,
        "execution_identity": source_proof.execution_identity,
        "replay_identity": source_proof.replay_identity,
        "proof": h_proof,
        "required_event_witnesses": witnesses,
    }
    if spec.cell_kind is BridgeCellKindV1.BASELINE:
        source = spec.source_authority
        if type(source) is not BridgeAcceptanceRegistryCellV1:
            raise BridgeAcceptanceRunnerError("baseline source authority类型错误")
        return create_bridge_baseline_acceptance_cell_v1(
            registry_cell=source, **common
        )
    source = spec.source_authority
    if type(source) is not BridgeSentinelCandidateV1:
        raise BridgeAcceptanceRunnerError("sentinel source authority类型错误")
    return create_bridge_sentinel_acceptance_cell_v1(
        candidate=source, **common
    )


def execute_formal_cell_production_v1(
    spec: BridgeRunnerCellSpecV1, replay_artifact_path: str
) -> BridgeCellExecutionV1:
    """Execute one baseline through existing Bridge authorities only.

    The frozen replay authority currently recognizes natural full-game cell IDs
    only from BASELINE_18.  Sentinel execution therefore fails closed here until
    a separately authorized replay adapter exists; the runner never invents one.
    """

    if spec.cell_kind is not BridgeCellKindV1.BASELINE:
        raise BridgeAcceptanceRunnerError(
            "current frozen Bridge recorder未授权sentinel natural replay；"
            "需要单独授权的只读adapter后才能执行formal sentinel"
        )
    preflight = create_skill_aware_fixed_assignment_duel_session_v1(
        seed=spec.seed,
        general_key=spec.general_key,
        seat_assignment=spec.seat_assignment,
    )
    assignment = preflight.assignment
    if (
        assignment.general_key,
        assignment.seat_assignment,
        assignment.general_player_id,
        assignment.no_skill_player_id,
    ) != (
        spec.general_key,
        spec.seat_assignment,
        spec.general_player_id,
        spec.no_skill_player_id,
    ):
        raise BridgeAcceptanceRunnerError("canonical Bridge factory preflight漂移")
    recorded = record_natural_full_game_skill_aware_fixed_assignment_bridge_replay_v1(
        general_key=spec.general_key,
        seat_assignment=spec.seat_assignment,
        seed=spec.seed,
        cell_id=spec.cell_id,
    )
    replay_payload = recorded.to_dict()
    cold_payload = json.loads(canonical_json(replay_payload))
    cold = BridgeFullGameReplayV1.from_dict(cold_payload)
    verification = reexecute_skill_aware_fixed_assignment_bridge_replay_v1(cold)
    source_proof = derive_bridge_full_game_cell_proof_v1(cold)
    if (
        verification.replay_identity != source_proof.replay_identity
        or verification.finished is not True
    ):
        raise BridgeAcceptanceRunnerError("strict reexecute与derived cell proof不一致")
    cell = derive_acceptance_cell_from_bridge_proof_v1(
        spec=spec,
        replay_payload=replay_payload,
        source_proof=source_proof,
        replay_artifact_path=replay_artifact_path,
    )
    return BridgeCellExecutionV1(
        replay_payload=MappingProxyType(replay_payload), cell=cell
    )


def verify_cell_bundle_production_v1(
    spec: BridgeRunnerCellSpecV1,
    bundle: BridgeAcceptanceCellBundleV1,
) -> BridgeAcceptanceCellV1:
    """Cold-load and strict-reexecute one old prefix artifact before resume."""

    cold_payload = json.loads(canonical_json(bundle.replay))
    cold = BridgeFullGameReplayV1.from_dict(cold_payload)
    verification = reexecute_skill_aware_fixed_assignment_bridge_replay_v1(cold)
    source_proof = derive_bridge_full_game_cell_proof_v1(cold)
    if (
        verification.replay_identity != source_proof.replay_identity
        or verification.finished is not True
    ):
        raise BridgeAcceptanceRunnerError("resume strict proof不一致")
    expected = derive_acceptance_cell_from_bridge_proof_v1(
        spec=spec,
        replay_payload=bundle.replay,
        source_proof=source_proof,
        replay_artifact_path=bundle.cell.replay_artifact_path,
    )
    if expected != bundle.cell:
        raise BridgeAcceptanceRunnerError(
            "resume cell必须由cold strict reexecution重新派生"
        )
    return expected


CellExecutorV1 = Callable[[BridgeRunnerCellSpecV1, str], BridgeCellExecutionV1]
CellVerifierV1 = Callable[
    [BridgeRunnerCellSpecV1, BridgeAcceptanceCellBundleV1],
    BridgeAcceptanceCellV1,
]


def _assert_cell_matches_spec_v1(
    spec: BridgeRunnerCellSpecV1, cell: BridgeAcceptanceCellV1
) -> None:
    expected = (
        spec.cell_kind,
        spec.cell_id,
        spec.general_key,
        spec.seat_assignment,
        spec.general_player_id,
        spec.no_skill_player_id,
        spec.seed,
        spec.registry_cell_identity,
        BridgeAcceptanceAuthorityV1.current(),
    )
    actual = (
        cell.cell_kind,
        cell.cell_id,
        cell.general_key,
        cell.seat_assignment,
        cell.general_player_id,
        cell.no_skill_player_id,
        cell.seed,
        cell.registry_cell_identity,
        cell.authority,
    )
    if actual != expected:
        raise BridgeAcceptanceRunnerError("executor/resume cell与ordered spec不一致")


def _load_sentinel_registry(output_root: Path) -> BridgeSentinelRegistryV1:
    path = output_root / SENTINEL_REGISTRY_FILENAME_V1
    return BridgeSentinelRegistryV1.from_dict(load_json_strict_v1(path))


def _assert_no_final_artifact(output_root: Path) -> None:
    existing = tuple(
        name
        for name in (MATRIX_FILENAME_V1, RESULT_FILENAME_V1)
        if (output_root / name).exists()
    )
    if existing:
        raise BridgeAcceptanceRunnerError(
            f"final artifact已存在，拒绝resume或覆盖：{existing}"
        )


def _load_and_verify_prefix_v1(
    *,
    output_root: Path,
    specs: tuple[BridgeRunnerCellSpecV1, ...],
    progress: BridgeAcceptanceProgressV1,
    verifier: CellVerifierV1,
) -> tuple[BridgeAcceptanceCellV1, ...]:
    expected_paths = {item.artifact_path for item in progress.artifacts}
    cell_dir = output_root / CELL_DIRECTORY_V1
    actual_paths: set[str] = set()
    if cell_dir.exists():
        if not cell_dir.is_dir():
            raise BridgeAcceptanceRunnerError("cells路径不是目录")
        for path in cell_dir.iterdir():
            if not path.is_file():
                raise BridgeAcceptanceRunnerError("cells目录包含unexpected非文件项")
            actual_paths.add(path.relative_to(output_root).as_posix())
    if actual_paths != expected_paths:
        raise BridgeAcceptanceRunnerError(
            "resume cells artifacts与checkpoint不精确一致；"
            f"missing={sorted(expected_paths - actual_paths)}, "
            f"extra={sorted(actual_paths - expected_paths)}"
        )
    cells: list[BridgeAcceptanceCellV1] = []
    for index, artifact in enumerate(progress.artifacts):
        path = _artifact_path(output_root, artifact.artifact_path)
        if file_sha256_v1(path) != artifact.artifact_sha256:
            raise BridgeAcceptanceIdentityError("resume artifact byte hash不匹配")
        bundle = BridgeAcceptanceCellBundleV1.from_dict(load_json_strict_v1(path))
        if (
            bundle.cell.cell_id != artifact.cell_id
            or bundle.cell.cell_identity != artifact.cell_identity
            or bundle.cell.replay_identity != artifact.replay_identity
        ):
            raise BridgeAcceptanceIdentityError("resume artifact binding不匹配")
        _assert_cell_matches_spec_v1(specs[index], bundle.cell)
        cell = verifier(specs[index], bundle)
        if cell != bundle.cell:
            raise BridgeAcceptanceRunnerError("resume verifier未返回exact stored cell")
        cells.append(cell)
    return tuple(cells)


@dataclass(frozen=True, slots=True)
class BridgeFormalRunSummaryV1:
    progress: BridgeAcceptanceProgressV1
    new_cell_count: int
    matrix_written: bool
    result_written: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "completed_cell_ids": list(self.progress.completed_cell_ids),
            "failed_cell_ids": list(self.progress.failed_cell_ids),
            "new_cell_count": self.new_cell_count,
            "matrix_written": self.matrix_written,
            "result_written": self.result_written,
            "provisional_pending_audit": PROVISIONAL_PENDING_AUDIT,
        }


def run_formal_mode_v1(
    *,
    repo: Path,
    output_dir: Path,
    resume: bool,
    executor: CellExecutorV1 = execute_formal_cell_production_v1,
    verifier: CellVerifierV1 = verify_cell_bundle_production_v1,
    max_new_cells: int | None = None,
) -> BridgeFormalRunSummaryV1:
    _repo_root, output_root = validate_repo_and_output_v1(repo, output_dir)
    if max_new_cells is not None and (
        type(max_new_cells) is not int or max_new_cells < 0
    ):
        raise BridgeAcceptanceRunnerError("max_new_cells必须是非负精确整数")
    _assert_no_final_artifact(output_root)
    registry = bridge_acceptance_baseline_registry_v1()
    sentinel_registry = _load_sentinel_registry(output_root)
    specs = build_formal_cell_specs_v1(registry, sentinel_registry)
    progress_path = output_root / PROGRESS_FILENAME_V1
    if resume:
        if not progress_path.is_file():
            raise BridgeAcceptanceRunnerError("--resume缺少progress.json")
        progress = validate_progress_v1(
            load_json_strict_v1(progress_path),
            registry=registry,
            sentinel_registry=sentinel_registry,
        )
        if progress.final_artifact_exists:
            raise BridgeAcceptanceRunnerError("final progress拒绝resume")
        cells = list(
            _load_and_verify_prefix_v1(
                output_root=output_root,
                specs=specs,
                progress=progress,
                verifier=verifier,
            )
        )
    else:
        if progress_path.exists():
            raise BridgeAcceptanceRunnerError("fresh formal run拒绝覆盖progress.json")
        cell_dir = output_root / CELL_DIRECTORY_V1
        if cell_dir.exists() and any(cell_dir.iterdir()):
            raise BridgeAcceptanceRunnerError("fresh formal run发现已有cell artifacts")
        progress = create_initial_progress_v1(registry, sentinel_registry)
        validate_progress_v1(
            progress, registry=registry, sentinel_registry=sentinel_registry
        )
        atomic_write_json_v1(progress_path, progress.to_dict())
        cells = []

    remaining = specs[len(progress.completed_cell_ids) :]
    if max_new_cells is not None:
        remaining = remaining[:max_new_cells]
    new_cell_count = 0
    for spec in remaining:
        relative_path = _cell_relative_path(spec.cell_id)
        try:
            execution = executor(spec, relative_path)
            _assert_cell_matches_spec_v1(spec, execution.cell)
            if execution.cell.replay_artifact_path != relative_path:
                raise BridgeAcceptanceRunnerError("executor返回错误artifact path")
            bundle = BridgeAcceptanceCellBundleV1.create(
                execution.replay_payload, execution.cell
            )
            artifact_path = _artifact_path(output_root, relative_path)
            byte_sha256 = atomic_write_json_v1(artifact_path, bundle.to_dict())
            artifact = _artifact_record(
                bundle=bundle,
                relative_path=relative_path,
                byte_sha256=byte_sha256,
            )
            progress = append_completed_artifact_v1(progress, artifact)
            validate_progress_v1(
                progress, registry=registry, sentinel_registry=sentinel_registry
            )
            atomic_write_json_v1(progress_path, progress.to_dict())
            cells.append(execution.cell)
            new_cell_count += 1
        except Exception:
            progress = mark_failed_cell_v1(progress, spec.cell_id)
            atomic_write_json_v1(progress_path, progress.to_dict())
            raise

    matrix_written = False
    result_written = False
    if progress.completed_cell_ids == progress.ordered_expected_cell_ids:
        matrix = create_bridge_acceptance_matrix_v1(
            cells=tuple(cells), sentinel_registry=sentinel_registry
        )
        result = derive_bridge_acceptance_result_v1(matrix)
        assert_bridge_acceptance_aggregate_complete_v1(result)
        atomic_write_json_v1(output_root / MATRIX_FILENAME_V1, matrix.to_dict())
        matrix_written = True
        atomic_write_json_v1(output_root / RESULT_FILENAME_V1, result.to_dict())
        result_written = True
        progress = _progress_record(
            authority=progress.authority,
            mode=progress.mode,
            ordered_registry_identity=progress.ordered_registry_identity,
            sentinel_registry_identity=progress.sentinel_registry_identity,
            ordered_expected_cell_ids=progress.ordered_expected_cell_ids,
            completed_cell_ids=progress.completed_cell_ids,
            failed_cell_ids=progress.failed_cell_ids,
            artifacts=progress.artifacts,
            final_artifact_exists=True,
        )
        atomic_write_json_v1(progress_path, progress.to_dict())
    return BridgeFormalRunSummaryV1(
        progress=progress,
        new_cell_count=new_cell_count,
        matrix_written=matrix_written,
        result_written=result_written,
    )


def create_discovery_union_payload_v1(
    baseline_event_ids: tuple[str, ...]
) -> dict[str, object]:
    ordered = tuple(
        item for item in BRIDGE_REQUIRED_EVENT_IDS_V1 if item in baseline_event_ids
    )
    if ordered != baseline_event_ids or len(ordered) != len(set(ordered)):
        raise BridgeAcceptanceRunnerError("baseline event union必须canonical且无重复")
    material = {
        "schema": BRIDGE_ACCEPTANCE_DISCOVERY_UNION_SCHEMA_V1,
        "version": BRIDGE_ACCEPTANCE_RUNNER_VERSION_V1,
        "authority": BridgeAcceptanceAuthorityV1.current().to_dict(),
        "baseline_event_ids": list(ordered),
        "provisional_pending_audit": PROVISIONAL_PENDING_AUDIT,
    }
    return {**material, "union_identity": sha256_value(material)}


def create_discovery_observations_payload_v1(
    observations: tuple[BridgeSentinelObservationV1, ...]
) -> dict[str, object]:
    if type(observations) is not tuple or any(
        type(item) is not BridgeSentinelObservationV1 for item in observations
    ):
        raise BridgeAcceptanceRunnerError("discovery observations类型不匹配")
    material = {
        "schema": BRIDGE_ACCEPTANCE_DISCOVERY_OBSERVATIONS_SCHEMA_V1,
        "version": BRIDGE_ACCEPTANCE_RUNNER_VERSION_V1,
        "authority": BridgeAcceptanceAuthorityV1.current().to_dict(),
        "observations": [item.to_dict() for item in observations],
        "provisional_pending_audit": PROVISIONAL_PENDING_AUDIT,
    }
    return {**material, "observations_identity": sha256_value(material)}


def _load_discovery_union_v1(path: Path) -> tuple[str, ...]:
    data = _exact_object(load_json_strict_v1(path), "baseline event union")
    _exact_fields(data, _DISCOVERY_UNION_FIELDS_V1, "baseline event union")
    authority = BridgeAcceptanceAuthorityV1.from_dict(data["authority"])
    if authority != BridgeAcceptanceAuthorityV1.current():
        raise BridgeAcceptanceIdentityError("discovery union authority漂移")
    values = data["baseline_event_ids"]
    if type(values) is not list or any(type(item) is not str for item in values):
        raise BridgeAcceptanceRunnerError("baseline_event_ids必须是字符串array")
    expected = create_discovery_union_payload_v1(tuple(values))
    if data != expected:
        raise BridgeAcceptanceIdentityError("baseline event union identity不匹配")
    return tuple(values)


def _load_discovery_observations_v1(
    path: Path,
) -> tuple[BridgeSentinelObservationV1, ...]:
    data = _exact_object(load_json_strict_v1(path), "discovery observations")
    _exact_fields(
        data, _DISCOVERY_OBSERVATIONS_FIELDS_V1, "discovery observations"
    )
    authority = BridgeAcceptanceAuthorityV1.from_dict(data["authority"])
    if authority != BridgeAcceptanceAuthorityV1.current():
        raise BridgeAcceptanceIdentityError("discovery observations authority漂移")
    values = data["observations"]
    if type(values) is not list:
        raise BridgeAcceptanceRunnerError("observations必须是JSON array")
    observations = tuple(BridgeSentinelObservationV1.from_dict(item) for item in values)
    expected = create_discovery_observations_payload_v1(observations)
    if data != expected:
        raise BridgeAcceptanceIdentityError("discovery observations identity不匹配")
    return observations


def run_discovery_mode_v1(
    *, repo: Path, output_dir: Path, resume: bool
) -> BridgeSentinelRegistryV1:
    """Purely select sentinels from supplied observations; execute no gameplay."""

    _repo_root, output_root = validate_repo_and_output_v1(repo, output_dir)
    _assert_no_final_artifact(output_root)
    registry_path = output_root / SENTINEL_REGISTRY_FILENAME_V1
    progress_path = output_root / DISCOVERY_PROGRESS_FILENAME_V1
    if registry_path.exists() or progress_path.exists():
        action = "resume" if resume else "fresh run"
        raise BridgeAcceptanceRunnerError(
            f"discovery final artifact已存在，拒绝{action}覆盖"
        )
    if resume:
        raise BridgeAcceptanceRunnerError("discovery --resume缺少可恢复的非final prefix")
    baseline_event_ids = _load_discovery_union_v1(
        output_root / BASELINE_EVENT_UNION_FILENAME_V1
    )
    observations = _load_discovery_observations_v1(
        output_root / DISCOVERY_OBSERVATIONS_FILENAME_V1
    )
    sentinel_registry = select_bridge_sentinel_registry_v1(
        baseline_event_ids=baseline_event_ids, observations=observations
    )
    atomic_write_json_v1(registry_path, sentinel_registry.to_dict())
    discovery_registry_identity = sha256_value(
        {
            "mode": BridgeAcceptanceRunModeV1.DISCOVERY.value,
            "baseline_event_ids": list(baseline_event_ids),
            "observation_identities": [
                item.observation_identity for item in observations
            ],
        }
    )
    progress = _progress_record(
        authority=sentinel_registry.authority,
        mode=BridgeAcceptanceRunModeV1.DISCOVERY,
        ordered_registry_identity=discovery_registry_identity,
        sentinel_registry_identity=sentinel_registry.registry_identity,
        ordered_expected_cell_ids=(),
        completed_cell_ids=(),
        failed_cell_ids=(),
        artifacts=(),
        final_artifact_exists=True,
    )
    atomic_write_json_v1(progress_path, progress.to_dict())
    return sentinel_registry


def build_argument_parser_v1() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Bridge-H provisional acceptance runner V1"
    )
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--mode",
        choices=tuple(item.value for item in BridgeAcceptanceRunModeV1),
        required=True,
    )
    parser.add_argument("--resume", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_argument_parser_v1().parse_args(argv)
    if arguments.mode == BridgeAcceptanceRunModeV1.DISCOVERY.value:
        registry = run_discovery_mode_v1(
            repo=arguments.repo,
            output_dir=arguments.output_dir,
            resume=arguments.resume,
        )
        print(canonical_json(registry.to_dict()))
    else:
        summary = run_formal_mode_v1(
            repo=arguments.repo,
            output_dir=arguments.output_dir,
            resume=arguments.resume,
        )
        print(canonical_json(summary.to_dict()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "BASELINE_EVENT_UNION_FILENAME_V1",
    "BRIDGE_ACCEPTANCE_CELL_BUNDLE_SCHEMA_V1",
    "BRIDGE_ACCEPTANCE_DISCOVERY_OBSERVATIONS_SCHEMA_V1",
    "BRIDGE_ACCEPTANCE_DISCOVERY_UNION_SCHEMA_V1",
    "BRIDGE_ACCEPTANCE_RUNNER_VERSION_V1",
    "CELL_DIRECTORY_V1",
    "DISCOVERY_OBSERVATIONS_FILENAME_V1",
    "DISCOVERY_PROGRESS_FILENAME_V1",
    "MATRIX_FILENAME_V1",
    "PROGRESS_FILENAME_V1",
    "RESULT_FILENAME_V1",
    "SENTINEL_REGISTRY_FILENAME_V1",
    "BridgeAcceptanceCellBundleV1",
    "BridgeAcceptanceRunnerError",
    "BridgeCellExecutionV1",
    "BridgeFormalRunSummaryV1",
    "BridgeRunnerCellSpecV1",
    "append_completed_artifact_v1",
    "atomic_write_json_v1",
    "build_argument_parser_v1",
    "build_formal_cell_specs_v1",
    "create_discovery_observations_payload_v1",
    "create_discovery_union_payload_v1",
    "create_initial_progress_v1",
    "derive_acceptance_cell_from_bridge_proof_v1",
    "execute_formal_cell_production_v1",
    "file_sha256_v1",
    "load_json_strict_v1",
    "main",
    "mark_failed_cell_v1",
    "run_discovery_mode_v1",
    "run_formal_mode_v1",
    "validate_progress_v1",
    "validate_repo_and_output_v1",
    "verify_cell_bundle_production_v1",
]
