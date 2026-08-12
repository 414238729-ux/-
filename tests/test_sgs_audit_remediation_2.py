# -*- coding: utf-8 -*-
"""MILESTONE_B_AUDIT_REMEDIATION_2 专项测试。

覆盖：MB-B-001（artifact 是缓存报告不是执行凭证；static eligibility /
cached report validity / live result 三层分离；invalid live results 必须
FAILED 且 simulation_executed=true 只表示执行已发生）；MB-M-005（trusted
provenance 只能由内部 canonical factory 产生，普通构造/from_dict/replace/
copy/JSON roundtrip/exact canonical values 均不能自我提升）；MB-M-008
（FINISHED transient inventory 完整性与 seed 3 复现、负例矩阵）；MB-M-009
（真实缺口的负面测试）；R1-NEW-001（manifest SHA-256 清单：64 hex、现场
重算 mismatch=0、self_excluded）；R1-NEW-003（根目录 hygiene）。
"""

from __future__ import annotations

import copy
import dataclasses
import json
import re
from pathlib import Path

import pytest

import scripts.sgs_formal_runner as formal_runner
from scripts.sgs_engine.actions import UnsupportedRuleError
from scripts.sgs_engine.formal_duel import (
    FormalDuelConfiguration,
    FormalDuelConfigurationError,
    FormalDuelReferenceController,
    FormalDuelSeedResult,
    FormalNoSkillDuelSession,
    TrustedFormalDuelConfiguration,
    inspect_formal_duel_readiness,
    run_formal_duel_seed_sweep,
)
from scripts.sgs_engine.model import CharacterMetadata
from scripts.sgs_engine.production_batch import (
    FINISHED_TRANSIENT_RUNTIME_FIELDS,
    ProductionBatchError,
)
from scripts.sgs_engine_gate import (
    FormalSimulationExecutionFailedError,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def _fresh_seed_game(seed: int = 3) -> FormalNoSkillDuelSession:
    game = FormalNoSkillDuelSession(
        seed=seed,
        configuration=FormalDuelConfiguration.formal_profile(),
        analysis_only=False,
    )
    controller = FormalDuelReferenceController()
    while not game.is_finished:
        if game.step_count >= 2000:
            break
        game.step(controller)
    assert game.is_finished
    return game


# ---------------------------------------------------------------------------
# MB-M-005：trusted provenance 只能由内部 canonical factory 产生
# ---------------------------------------------------------------------------


def test_trusted_provenance_parameter_does_not_exist() -> None:
    with pytest.raises(TypeError):
        FormalDuelConfiguration(
            platform="三国杀移动版",
            version="2026-07-25牌堆快照",
            source_location="x",
            verification_status="当前确认",
            deck_applicable=True,
            initial_hand_count=4,
            player_hp=(4, 4),
            player_max_hp=(4, 4),
            first_player_policy="deterministic_rng",
            participants=(
                CharacterMetadata("soldier", "none", "none"),
                CharacterMetadata("soldier", "none", "none"),
            ),
            _trusted_provenance=True,
        )


def test_normal_constructor_cannot_self_authorize() -> None:
    profile = FormalDuelConfiguration.formal_profile()
    canonical_value = profile.to_dict()
    # 数值完全等于 canonical 的普通构造也不能提升。
    crafted = FormalDuelConfiguration(
        platform=canonical_value["platform"],
        version=canonical_value["version"],
        source_location=canonical_value["source_location"],
        verification_status=canonical_value["verification_status"],
        deck_applicable=canonical_value["deck_applicable"],
        initial_hand_count=canonical_value["initial_hand_count"],
        player_hp=tuple(canonical_value["player_hp"]),
        player_max_hp=tuple(canonical_value["player_max_hp"]),
        first_player_policy=canonical_value["first_player_policy"],
        participants=(
            CharacterMetadata("soldier", "none", "none"),
            CharacterMetadata("soldier", "none", "none"),
        ),
    )
    assert not isinstance(crafted, TrustedFormalDuelConfiguration)
    assert crafted.source_confirmed is False


def test_from_dict_and_json_roundtrip_cannot_self_authorize() -> None:
    profile = FormalDuelConfiguration.formal_profile()
    value = profile.to_dict()
    restored = FormalDuelConfiguration.from_dict(value)
    assert not isinstance(restored, TrustedFormalDuelConfiguration)
    assert restored.source_confirmed is False
    # JSON roundtrip 同样只恢复 value，不是 trusted capability。
    via_json = FormalDuelConfiguration.from_dict(
        json.loads(json.dumps(value, ensure_ascii=False))
    )
    assert not isinstance(via_json, TrustedFormalDuelConfiguration)
    assert via_json.source_confirmed is False


def test_replace_copy_deepcopy_cannot_self_authorize() -> None:
    profile = FormalDuelConfiguration.formal_profile()
    value = profile.to_dict()
    untrusted = FormalDuelConfiguration.from_dict(value)
    assert dataclasses.replace(untrusted).source_confirmed is False
    assert copy.copy(untrusted).source_confirmed is False
    assert copy.deepcopy(untrusted).source_confirmed is False
    # trusted 类型被 replace 篡改时必须失败关闭。
    with pytest.raises(FormalDuelConfigurationError):
        dataclasses.replace(
            profile,
            participants=(
                CharacterMetadata("soldier", "male", "male"),
                CharacterMetadata("soldier", "none", "none"),
            ),
        )
    # 未经篡改的 trusted 副本保持可信（值仍等于 canonical）。
    assert copy.deepcopy(profile).source_confirmed is True


def test_only_canonical_factory_yields_trusted() -> None:
    trusted = FormalDuelConfiguration.formal_profile()
    assert isinstance(trusted, TrustedFormalDuelConfiguration)
    assert trusted.source_confirmed is True


# ---------------------------------------------------------------------------
# MB-M-008：FINISHED transient inventory
# ---------------------------------------------------------------------------


def test_finished_transient_inventory_covers_all_transient_fields() -> None:
    # 对照 _BatchRuntime 字段，确保所有 transient/pending 字段已登记。
    from scripts.sgs_engine.production_batch import _BatchRuntime

    runtime_fields = set(_BatchRuntime.__dataclass_fields__)
    permanent = {
        "current_player_id",
        "turn_number",
        "phase",
        "slash_used_counts",
        "judgment_entry_indices",
        "judgment_entry_counter",
    }
    known_transient = set(FINISHED_TRANSIENT_RUNTIME_FIELDS)
    unclassified = runtime_fields - permanent - known_transient - {"winner_id"}
    assert unclassified == set(), f"未分类 runtime 字段: {unclassified}"


def test_seed_3_natural_end_has_no_transient_residual() -> None:
    game = _fresh_seed_game(seed=3)
    assert game.winner_id in {"p1", "p2"}
    # 修复前独立复审观察到的残留字段必须为空。
    runtime = game.runtime
    for field in (
        "pending_trick",
        "trick_effect_active",
        "trick_response_order",
        "trick_response_index",
        "trick_decision_count",
        "trick_direct_response_to",
        "zone_choice_snapshot_digest",
        "pending_damage_rescue_reason",
        "pending_damage_death_reason",
    ):
        assert getattr(runtime, field) in (None, (), {}, 0, False), field
    game.assert_finished_state_invariants()


@pytest.mark.parametrize("field", sorted(FINISHED_TRANSIENT_RUNTIME_FIELDS))
def test_finished_invariant_negative_matrix(field: str) -> None:
    """每个必须为空的 transient 字段注入单个非法残留，invariant 必须失败。"""

    game = _fresh_seed_game(seed=3)
    runtime = game.runtime
    sample = {
        "pending_trick": "residual",
        "pending_slash": "residual",
        "pending_judgment": "residual",
        "pending_borrowed_sword": "residual",
        "pending_group_trick": "residual",
        "pending_duel": "residual",
        "pending_fire_attack": "residual",
        "pending_wugu": "residual",
        "pending_cixiong_choice": "residual",
        "pending_weapon_choice": "residual",
        "pending_slash_choice": "residual",
        "pending_discard_two": "residual",
        "pending_hanbing_discard": "residual",
        "pending_zone_choice": "residual",
        "pending_chain": "residual",
        "pending_dying_id": "p1",
        "response_window_id": "x",
        "response_window_order": ("p1",),
        "response_window_source_sequence": 1,
        "rescue_order": ("p1",),
        "rescue_index": 1,
        "rescue_decision_count": 1,
        "trick_effect_active": True,
        "trick_consecutive_passes": 1,
        "trick_response_order": ("p1",),
        "trick_response_index": 1,
        "trick_decision_count": 1,
        "trick_direct_response_to": "x",
        "zone_choice_handles": {"x": "y"},
        "zone_choice_snapshot_digest": "x",
        "fire_attack_reveal_handles": {"x": "y"},
        "group_response_handles": {"x": "y"},
        "group_response_snapshot_digest": "x",
        "borrowed_sword_slash_handles": {"x": "y"},
        "borrowed_sword_slash_snapshot_digest": "x",
        "pending_damage_card_id": "x",
        "pending_damage_source_id": "p1",
        "pending_damage_kill_credit": "p1",
        "pending_damage_rescue_reason": "x",
        "pending_damage_death_reason": "x",
        "bagua_attempted": True,
        "defer_damage_card_finish": True,
        "damage_card_already_finished": True,
        "wine_buff_owner_id": "p1",
        "wine_buff_used_this_play_phase": True,
        "skipped_phases": {"p1": "draw"},
        "phase_skip_reasons": {"p1": "x"},
        "discard_phase_window_id": "x",
        "discard_phase_selected_ids": ("x",),
        "discard_phase_handles": {"x": "y"},
        "discard_phase_snapshot_digest": "x",
        "processed_judgment_instance_ids": ("x",),
    }
    injected = sample.get(field, "residual")
    bad = dataclasses.replace(runtime, **{field: injected})
    game._runtime = bad
    with pytest.raises(ProductionBatchError, match=field):
        game.assert_finished_state_invariants()


# ---------------------------------------------------------------------------
# MB-B-001 / MB-M-009：artifact 缓存 vs live execution
# ---------------------------------------------------------------------------


def test_cached_report_is_not_live_execution(monkeypatch: pytest.MonkeyPatch) -> None:
    """缓存报告有效（cached_acceptance_report_valid）不表示 simulation 已执行。"""

    readiness = inspect_formal_duel_readiness()
    assert readiness.cached_acceptance_report_valid is True
    assert readiness.formal_duel_execution_ready is True
    # status 命令（build_current_status）绝不伪装 simulation executed。
    status = formal_runner.build_current_status(
        mode_name="formal_160_card_no_skill_duel"
    )
    assert status["simulation_executed"] is False
    assert status["formal_duel"]["cached_acceptance_report_valid"] is True
    assert (
        status["formal_duel"]["formal_duel_execution_ready"] is True
    )


def test_invalid_live_results_force_failed_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """live results 中任意非法项 → status=failed、simulation_executed=true。"""

    output = tmp_path / "live-failed.json"
    bad_result = FormalDuelSeedResult(
        seed=0,
        deck_count=160,
        winner="p1",
        action_count=10,
        turn_count=1,
        draw_pile_count=0,
        reshuffle_count=0,
        unsupported_rules=0,
        approximation_count=0,
        safety_cap_triggered=False,
        exception_type=None,
        exception_message=None,
        reached_card_keys=(),
        natural_end=True,
        formal_result_eligible=True,
        reexecution_verified=False,  # strict replay 未通过
        final_state_hash="a" * 64,
    )
    monkeypatch.setattr(
        formal_runner,
        "run_formal_duel_seed_sweep",
        lambda *a, **k: (bad_result,),
    )
    with pytest.raises(FormalSimulationExecutionFailedError) as captured:
        formal_runner.run_formal_simulation(
            mode_name="formal_160_card_no_skill_duel",
            output_path=output,
        )
    assert output.exists() is True
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["status"] == "failed"
    assert payload["simulation_executed"] is True
    assert payload["result_source"] == "live_execution"
    assert captured.value.payload["status"] == "failed"


def test_stale_cache_does_not_block_live_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """artifact stale（cached invalid）不得阻止静态资格满足时的 live run。"""

    import scripts.sgs_engine_gate as engine_gate
    from dataclasses import replace

    current = engine_gate.inspect_formal_duel_readiness()
    stale = replace(
        current,
        cached_acceptance_report_valid=False,
        cached_acceptance_seed_count=0,
        cached_acceptance_natural_end_count=0,
        cached_acceptance_failure_count=0,
        cached_fixed_seed_acceptance_passed=False,
    )
    monkeypatch.setattr(
        engine_gate, "inspect_formal_duel_readiness", lambda: stale
    )
    output = tmp_path / "stale-cache-run.json"
    # 真实执行小 seed 子集（CLI/正式入口固定 0..99；此处用测试子集路径）。
    result_path = formal_runner.run_formal_simulation(
        mode_name="formal_160_card_no_skill_duel",
        output_path=output,
        seeds=(0, 1),
    )
    assert result_path.exists()
    payload = json.loads(result_path.read_text(encoding="utf-8"))
    assert payload["simulation_executed"] is True
    assert payload["status"] == "passed"


# ---------------------------------------------------------------------------
# R1-NEW-001：manifest SHA-256 inventory
# ---------------------------------------------------------------------------


def test_manifest_sha256_inventory_is_true_sha256() -> None:
    from scripts.sgs_hash_inventory import git_normalized_sha256

    manifest = json.loads(
        (REPOSITORY_ROOT / "docs" / "CHECKPOINT_MANIFEST.json").read_text(
            encoding="utf-8"
        )
    )
    sha = manifest["sha256"]
    assert sha.get("self_excluded") is True
    assert "hash_note" in sha
    mismatches = []
    entries = 0
    for key, value in sha.items():
        if key in ("hash_note", "self_excluded"):
            continue
        entries += 1
        assert len(value) == 64, (key, value)
        assert re.fullmatch(r"[0-9a-f]{64}", value), (key, value)
        if value != git_normalized_sha256(key):
            mismatches.append(key)
    assert mismatches == []
    assert entries >= 50


# ---------------------------------------------------------------------------
# R1-NEW-003：根目录 hygiene
# ---------------------------------------------------------------------------


def test_repository_root_has_no_git_warning_junk() -> None:
    for path in REPOSITORY_ROOT.iterdir():
        if not path.is_file():
            continue
        try:
            content = path.read_text(encoding="utf-8", errors="strict")
        except Exception:
            continue
        if "LF will be replaced by CRLF" in content and len(content.splitlines()) < 40:
            raise AssertionError(
                f"仓库根目录存在 Git warning 垃圾文件: {path.name}"
            )


def test_closed_findings_same_seed_different_secret_determinism() -> None:
    """MB-B-003 回归：same seed / different session secret 结果一致。"""

    first = run_formal_duel_seed_sweep(
        (17,),
        configuration=FormalDuelConfiguration.formal_profile(),
        analysis_only=False,
        max_steps=2000,
    )
    second = run_formal_duel_seed_sweep(
        (17,),
        configuration=FormalDuelConfiguration.formal_profile(),
        analysis_only=False,
        max_steps=2000,
    )
    assert first[0].winner == second[0].winner
    assert first[0].action_count == second[0].action_count
    assert first[0].final_state_hash == second[0].final_state_hash
