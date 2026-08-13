# -*- coding: utf-8 -*-
"""MILESTONE_B_AUDIT_REMEDIATION_3 专项测试。

覆盖：MB-B-001（唯一 canonical live-result validator；malformed hash／
deck_count／action_count／turn_count／passed=false／missing／duplicate seed
全部必须 status=failed；runner 不得覆写 validator）；MB-M-005（trusted
capability 私有 sentinel：公开 import＋直接构造／forged token 均失败关闭，
copy/deepcopy 只能经内部 canonical factory，replay 只恢复 value）；
MB-M-009（真实缺口测试矩阵）；MB-M-010（manifest/docs current-state
consistency）；R2-NEW-001（execution snapshot 完整化：四个 runtime 字段
进入 execution hash，pending_slash_choice 与 runtime.pending_slash 一致性
invariant，boosted 变化改变 hash 且确实影响伤害）。
"""

from __future__ import annotations

import copy
import dataclasses
import json
import re
from pathlib import Path

import pytest

import scripts.sgs_formal_runner as formal_runner
from scripts.sgs_engine.formal_duel import (
    FormalDuelConfiguration,
    FormalDuelConfigurationError,
    FormalDuelSeedResult,
    FormalNoSkillDuelSession,
    TrustedFormalDuelConfiguration,
    implementation_identity,
    validate_formal_live_result,
)
from scripts.sgs_engine.production_batch import (
    EXECUTION_HASH_RUNTIME_INVENTORY,
    FINISHED_TRANSIENT_RUNTIME_FIELDS,
    ProductionBatchError,
    ProductionPhase,
    _BatchRuntime,
    _PendingDiscardTwo,
    _PendingHanbingDiscard,
    _PendingSlash,
    _PendingSlashChoice,
)
from scripts.sgs_engine.model import CharacterMetadata
from scripts.sgs_engine_gate import FormalSimulationExecutionFailedError


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def _good_result(seed: int = 0) -> FormalDuelSeedResult:
    return FormalDuelSeedResult(
        seed=seed,
        deck_count=160,
        winner="p1" if seed % 2 == 0 else "p2",
        action_count=10,
        turn_count=2,
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
        reexecution_verified=True,
        final_state_hash=f"{seed:064x}"[:64],
    )


def _fresh_seed_game(seed: int = 3) -> FormalNoSkillDuelSession:
    from scripts.sgs_engine.formal_duel import FormalDuelReferenceController

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


class _FileMutation:
    """对仓库文件做临时字节级修改并在 finally 恢复（测试内自包含）。"""

    def __init__(self, relpath: str) -> None:
        self.path = REPOSITORY_ROOT / relpath
        self.original = self.path.read_bytes()

    def __enter__(self) -> "_FileMutation":
        return self

    def __exit__(self, *exc: object) -> None:
        self.path.write_bytes(self.original)

    def write(self, data: bytes) -> None:
        self.path.write_bytes(data)


# ---------------------------------------------------------------------------
# MB-B-001 / MB-M-009：唯一 canonical live-result validator + runner 矩阵
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "label,mutator,expected_reason",
    [
        ("malformed_hash", lambda r: dataclasses.replace(r, final_state_hash="a" * 63), "final_state_hash_invalid"),
        ("uppercase_hash", lambda r: dataclasses.replace(r, final_state_hash="A" * 64), "final_state_hash_invalid"),
        ("bad_deck_count", lambda r: dataclasses.replace(r, deck_count=159), "deck_count"),
        ("zero_action_count", lambda r: dataclasses.replace(r, action_count=0), "action_count_zero"),
        ("zero_turn_count", lambda r: dataclasses.replace(r, turn_count=0), "turn_count_zero"),
        ("strict_false", lambda r: dataclasses.replace(r, reexecution_verified=False), "reexecution_not_verified"),
        ("natural_false", lambda r: dataclasses.replace(r, natural_end=False), "not_natural_end"),
        ("unsupported", lambda r: dataclasses.replace(r, unsupported_rules=1), "unsupported_rules"),
        ("approximation", lambda r: dataclasses.replace(r, approximation_count=1), "approximation_count"),
        ("illegal_winner", lambda r: dataclasses.replace(r, winner="p3"), "winner_missing"),
        ("exception", lambda r: dataclasses.replace(r, exception_type="ValueError"), "exception:ValueError"),
    ],
)
def test_runner_live_result_validation_matrix_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    label: str,
    mutator: object,
    expected_reason: str,
) -> None:
    """每个非法 live result → status=failed、simulation_executed=true。"""

    del label
    bad = mutator(_good_result(seed=0))  # type: ignore[operator]
    ok, reason = validate_formal_live_result(bad)
    assert ok is False
    assert expected_reason in reason
    output = tmp_path / "matrix-failed.json"
    monkeypatch.setattr(
        formal_runner,
        "run_formal_duel_seed_sweep",
        lambda *a, **k: (bad,),
    )
    with pytest.raises(FormalSimulationExecutionFailedError) as captured:
        formal_runner.run_formal_simulation(
            mode_name="formal_160_card_no_skill_duel",
            output_path=output,
            seeds=(0,),
        )
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["status"] == "failed"
    assert payload["simulation_executed"] is True
    assert payload["result_source"] == "live_execution"
    assert captured.value.payload["status"] == "failed"
    validation = payload["validation"]
    assert validation["failure_count"] >= 1
    assert any(
        expected_reason in str(item.get("reason", ""))
        for item in validation["failures"]
    )


def test_runner_missing_seed_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "missing-seed.json"
    monkeypatch.setattr(
        formal_runner,
        "run_formal_duel_seed_sweep",
        lambda *a, **k: (_good_result(0), _good_result(2)),
    )
    with pytest.raises(FormalSimulationExecutionFailedError):
        formal_runner.run_formal_simulation(
            mode_name="formal_160_card_no_skill_duel",
            output_path=output,
            seeds=(0, 1),
        )
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["status"] == "failed"
    assert payload["validation"]["seed_set_exact"] is False


def test_runner_duplicate_seed_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "duplicate-seed.json"
    monkeypatch.setattr(
        formal_runner,
        "run_formal_duel_seed_sweep",
        lambda *a, **k: (_good_result(0), _good_result(0)),
    )
    with pytest.raises(FormalSimulationExecutionFailedError):
        formal_runner.run_formal_simulation(
            mode_name="formal_160_card_no_skill_duel",
            output_path=output,
            seeds=(0, 1),
        )
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["status"] == "failed"
    assert payload["validation"]["seed_unique"] is False


def test_full_artifact_passed_false_never_becomes_status_passed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """100 局逐 seed 全通过但 artifact passed=false 时，runner 不得覆写。"""

    output = tmp_path / "artifact-passed-false.json"
    hundred = tuple(_good_result(seed=seed) for seed in range(100))
    monkeypatch.setattr(
        formal_runner,
        "run_formal_duel_seed_sweep",
        lambda *a, **k: hundred,
    )
    forged_artifact = {
        "schema": "FORMAL_MILESTONE_B_100_SEED_ACCEPTANCE_v2",
        "passed": False,
        "failure_count": 1,
        "seeds_detail": [],
    }
    monkeypatch.setattr(
        formal_runner,
        "build_formal_acceptance_artifact",
        lambda *a, **k: forged_artifact,
    )
    with pytest.raises(FormalSimulationExecutionFailedError):
        formal_runner.run_formal_simulation(
            mode_name="formal_160_card_no_skill_duel",
            output_path=output,
        )
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["status"] == "failed"
    assert payload["simulation_executed"] is True
    assert "artifact 的 passed 被判定为 false" in payload["note"]


def test_validate_formal_live_result_set_recomputes_failures_from_details() -> None:
    from scripts.sgs_engine.formal_duel import validate_formal_live_result_set

    results = tuple(_good_result(seed=seed) for seed in range(100))
    results = dataclasses.replace(
        results[0], final_state_hash="b" * 63
    ), *results[1:]
    summary = validate_formal_live_result_set(results)
    assert summary.all_valid is False
    assert summary.failure_count == 1
    assert summary.failures[0]["seed"] == 0
    assert "final_state_hash_invalid" in summary.failures[0]["reason"]


# ---------------------------------------------------------------------------
# MB-M-005：trusted capability 不可公开构造
# ---------------------------------------------------------------------------


def test_direct_construction_of_trusted_type_without_token_fails() -> None:
    with pytest.raises(FormalDuelConfigurationError):
        TrustedFormalDuelConfiguration(
            platform="三国杀移动版",
            version="2026-07-25牌堆快照",
            source_location="USER_CONFIRMED_PROJECT_FORMAL_PROFILE（2026-08-09 用户确认）",
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
        )


def test_direct_construction_with_forged_token_fails() -> None:
    with pytest.raises(FormalDuelConfigurationError):
        TrustedFormalDuelConfiguration(
            platform="三国杀移动版",
            version="2026-07-25牌堆快照",
            source_location="USER_CONFIRMED_PROJECT_FORMAL_PROFILE（2026-08-09 用户确认）",
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
            _capability_token=object(),
        )


def test_replace_cannot_drop_or_forge_capability() -> None:
    profile = FormalDuelConfiguration.formal_profile()
    with pytest.raises(FormalDuelConfigurationError):
        dataclasses.replace(profile, _capability_token=None)
    with pytest.raises(FormalDuelConfigurationError):
        dataclasses.replace(profile, _capability_token=object())
    # 无字段变化的 replace 保持同一受控能力（值仍等于 canonical）。
    assert dataclasses.replace(profile).trusted_capability_held is True


def test_copy_deepcopy_only_recreate_via_canonical_factory() -> None:
    profile = FormalDuelConfiguration.formal_profile()
    for cloned in (copy.copy(profile), copy.deepcopy(profile)):
        assert isinstance(cloned, TrustedFormalDuelConfiguration)
        assert cloned.trusted_capability_held is True
        assert cloned.to_dict() == profile.to_dict()


def test_session_rejects_untrusted_and_capability_less_configs() -> None:
    canonical_value = FormalDuelConfiguration.formal_profile().to_dict()
    untrusted = FormalDuelConfiguration.from_dict(canonical_value)
    with pytest.raises(FormalDuelConfigurationError):
        FormalNoSkillDuelSession(
            seed=0,
            configuration=untrusted,
            analysis_only=False,
        )
    # 数值完全等于 canonical 的普通构造同样被拒。
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
    with pytest.raises(FormalDuelConfigurationError):
        FormalNoSkillDuelSession(
            seed=0,
            configuration=crafted,
            analysis_only=False,
        )


def test_subclass_cannot_bypass_capability_gate() -> None:
    class _EvilTrusted(TrustedFormalDuelConfiguration):
        def __post_init__(self) -> None:  # type: ignore[override]
            FormalDuelConfiguration.__post_init__(self)

    evil = _EvilTrusted(
        platform="三国杀移动版",
        version="2026-07-25牌堆快照",
        source_location="USER_CONFIRMED_PROJECT_FORMAL_PROFILE（2026-08-09 用户确认）",
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
        _capability_token=object(),
    )
    # 即使子类覆写 __post_init__ 绕过值校验，伪造 token 也不持有真实
    # capability identity；正式会话必须拒绝（不只依赖 isinstance）。
    assert evil.trusted_capability_held is False
    with pytest.raises(FormalDuelConfigurationError):
        FormalNoSkillDuelSession(
            seed=0,
            configuration=evil,
            analysis_only=False,
        )


def test_replay_value_roundtrip_does_not_restore_capability() -> None:
    profile = FormalDuelConfiguration.formal_profile()
    value = profile.to_dict()
    restored = FormalDuelConfiguration.from_dict(
        json.loads(json.dumps(value, ensure_ascii=False))
    )
    assert not isinstance(restored, TrustedFormalDuelConfiguration)
    assert restored.source_confirmed is False
    # replay 记录只保存 profile value；不得包含 capability token 字段。
    serialized = json.dumps(value, ensure_ascii=False)
    assert "capability" not in serialized
    assert "token" not in serialized


# ---------------------------------------------------------------------------
# MB-B-001：implementation bundle 覆盖真实语义依赖
# ---------------------------------------------------------------------------


def test_implementation_identity_changes_on_production_source_mutation() -> None:
    before = implementation_identity()
    with _FileMutation("scripts/sgs_engine/events.py") as mutation:
        mutation.write(mutation.original + b"\n# remediation-3 identity mutation\n")
        after = implementation_identity()
    assert after != before
    assert implementation_identity() == before


def test_implementation_identity_changes_on_structured_csv_mutation() -> None:
    csv_path = REPOSITORY_ROOT / "knowledge" / "三国杀卡牌结构化数据.csv"
    rows = csv_path.read_text(encoding="utf-8-sig").splitlines()
    header = rows[0]
    assert "attack_range" in header
    target_index = next(
        index
        for index, row in enumerate(rows[1:], start=1)
        if row.split(",", 1)[0].strip().strip('"')
        == "sgs_weapon_qinglongyanyuedao"
    )
    before = implementation_identity()
    with _FileMutation("knowledge/三国杀卡牌结构化数据.csv") as mutation:
        mutated = list(rows)
        mutated[target_index] = mutated[target_index] + ",#identity-mutation"
        mutation.write("\n".join(mutated).encode("utf-8"))
        after = implementation_identity()
    assert after != before
    assert implementation_identity() == before


def test_implementation_identity_changes_on_deck_data_mutation() -> None:
    before = implementation_identity()
    with _FileMutation("scripts/deck_data.py") as mutation:
        mutation.write(mutation.original + b"\n# remediation-3 deck data mutation\n")
        after = implementation_identity()
    assert after != before
    assert implementation_identity() == before


def test_implementation_identity_unchanged_on_docs_only_mutation() -> None:
    before = implementation_identity()
    with _FileMutation("docs/SOURCE_AND_CALLCHAIN_AUDIT.md") as mutation:
        mutation.write(mutation.original + b"\n")
        after = implementation_identity()
    assert after == before
    assert implementation_identity() == before


def test_implementation_identity_unchanged_on_acceptance_artifact_mutation() -> None:
    before = implementation_identity()
    with _FileMutation("docs/FORMAL_MILESTONE_B_100_SEED_ACCEPTANCE.json") as mutation:
        mutation.write(mutation.original + b"\n")
        after = implementation_identity()
    assert after == before
    assert implementation_identity() == before


def test_implementation_identity_unchanged_on_line_ending_change() -> None:
    before = implementation_identity()
    with _FileMutation("scripts/deck_data.py") as mutation:
        text = mutation.original.decode("utf-8")
        converted = text.replace("\r\n", "\n").replace("\n", "\r\n")
        mutation.write(converted.encode("utf-8"))
        after = implementation_identity()
    assert after == before
    assert implementation_identity() == before


def test_implementation_identity_changes_on_deck_csv_mutation() -> None:
    before = implementation_identity()
    with _FileMutation("knowledge/三国杀牌堆数据.csv") as mutation:
        mutation.write(mutation.original + b"\n#identity-mutation\n")
        after = implementation_identity()
    assert after != before
    assert implementation_identity() == before


def test_implementation_bundle_includes_declared_transitive_inputs() -> None:
    from scripts.sgs_engine.formal_duel import (
        FORMAL_SIMULATION_TRANSITIVE_INPUT_INVENTORY,
    )

    assert "scripts/deck_data.py" in FORMAL_SIMULATION_TRANSITIVE_INPUT_INVENTORY
    assert (
        "knowledge/三国杀卡牌结构化数据.csv"
        in FORMAL_SIMULATION_TRANSITIVE_INPUT_INVENTORY
    )
    assert "knowledge/三国杀牌堆数据.csv" in FORMAL_SIMULATION_TRANSITIVE_INPUT_INVENTORY
    for relative in FORMAL_SIMULATION_TRANSITIVE_INPUT_INVENTORY:
        assert (REPOSITORY_ROOT / relative).is_file(), relative


# ---------------------------------------------------------------------------
# R2-NEW-001：execution snapshot 完整化
# ---------------------------------------------------------------------------


def test_execution_hash_runtime_inventory_fully_serialized() -> None:
    game = _fresh_seed_game(seed=3)
    runtime_fields = set(_BatchRuntime.__dataclass_fields__)
    # A 类行为字段全部登记。
    assert EXECUTION_HASH_RUNTIME_INVENTORY <= runtime_fields
    # audit_value 必须覆盖全部登记字段。
    audit = game.runtime.audit_value()
    assert set(audit) >= EXECUTION_HASH_RUNTIME_INVENTORY
    # FINISHED 时四个 remediation-3 字段必须为空。
    for field in (
        "damage_card_already_finished",
        "pending_slash_choice",
        "pending_discard_two",
        "pending_hanbing_discard",
    ):
        assert getattr(game.runtime, field) in (False, None), field


def _weapon_choice_runtime(
    game: FormalNoSkillDuelSession, boosted: bool
) -> _BatchRuntime:
    slash = _PendingSlash(
        attacker_id="p1",
        target_id="p2",
        slash_instance_id="slash-identity-test",
        boosted=boosted,
    )
    choice = _PendingSlashChoice(
        weapon_key="sgs_weapon_guanshifu",
        kind="guanshifu_force_hit",
        attacker_id="p1",
        target_id="p2",
        window_id="window-identity-test",
        pending_slash=slash,
    )
    return dataclasses.replace(
        game.runtime,
        phase=ProductionPhase.WEAPON_SLASH_CHOICE,
        pending_slash=slash,
        pending_slash_choice=choice,
    )


def test_execution_hash_changes_on_pending_slash_choice_boosted() -> None:
    game = _fresh_seed_game(seed=3)
    game._runtime = _weapon_choice_runtime(game, boosted=False)
    hash_false = game.execution_hash
    game._runtime = _weapon_choice_runtime(game, boosted=True)
    hash_true = game.execution_hash
    assert hash_false != hash_true
    audit = game.runtime.audit_value()
    nested = audit["pending_slash_choice"]["pending_slash"]
    assert nested["boosted"] is True
    # 行为意义：pending.boosted 直接决定贯石斧强制命中路径的伤害基数 1/2。
    source = (
        REPOSITORY_ROOT / "scripts" / "sgs_engine" / "production_batch.py"
    ).read_text(encoding="utf-8")
    assert "2 if pending.boosted else 1" in source


def test_execution_hash_changes_on_damage_card_already_finished() -> None:
    game = _fresh_seed_game(seed=3)
    runtime = _weapon_choice_runtime(game, boosted=False)
    base = game.execution_hash
    game._runtime = dataclasses.replace(runtime, damage_card_already_finished=True)
    assert game.execution_hash != base


def test_execution_hash_changes_on_pending_discard_two() -> None:
    game = _fresh_seed_game(seed=3)
    runtime = _weapon_choice_runtime(game, boosted=False)
    base = game.execution_hash
    game._runtime = dataclasses.replace(
        runtime,
        pending_discard_two=_PendingDiscardTwo(
            chooser_id="p1",
            cards_owner_id="p1",
            source_kind="guanshifu_force_hit",
            window_id="discard-two-window",
        ),
    )
    assert game.execution_hash != base


def test_execution_hash_changes_on_pending_hanbing_discard() -> None:
    game = _fresh_seed_game(seed=3)
    runtime = _weapon_choice_runtime(game, boosted=False)
    base = game.execution_hash
    game._runtime = dataclasses.replace(
        runtime,
        pending_hanbing_discard=_PendingHanbingDiscard(
            attacker_id="p1",
            target_id="p2",
            window_id="hanbing-window",
            step=1,
        ),
    )
    assert game.execution_hash != base


def test_pending_slash_choice_divergence_fails_closed() -> None:
    """只修改 pending_slash_choice 内部副本而 runtime.pending_slash 不变：
    不允许静默分叉，execution_snapshot 必须失败关闭（而非漏检）。"""

    game = _fresh_seed_game(seed=3)
    slash_false = _PendingSlash(
        attacker_id="p1",
        target_id="p2",
        slash_instance_id="slash-identity-test",
        boosted=False,
    )
    slash_true = dataclasses.replace(slash_false, boosted=True)
    choice = _PendingSlashChoice(
        weapon_key="sgs_weapon_guanshifu",
        kind="guanshifu_force_hit",
        attacker_id="p1",
        target_id="p2",
        window_id="window-identity-test",
        pending_slash=slash_true,  # 与 runtime.pending_slash 分叉
    )
    game._runtime = dataclasses.replace(
        game.runtime,
        phase=ProductionPhase.WEAPON_SLASH_CHOICE,
        pending_slash=slash_false,
        pending_slash_choice=choice,
    )
    with pytest.raises(ProductionBatchError, match="不一致"):
        _ = game.execution_snapshot


# ---------------------------------------------------------------------------
# MB-M-010：manifest/docs current-state consistency
# ---------------------------------------------------------------------------


def _manifest() -> dict[str, object]:
    return json.loads(
        (REPOSITORY_ROOT / "docs" / "CHECKPOINT_MANIFEST.json").read_text(
            encoding="utf-8"
        )
    )


def test_manifest_current_milestone_b_state_consistent() -> None:
    manifest = _manifest()
    dev = manifest["git"]["current_milestone_b_development"]
    # CURRENT LIVE 分层必须存在且不能是 commit=null/pending。
    current = dev.get("current_live", {})
    assert current.get("branch") == "sol-ultra-milestone-b-formal-duel"
    assert re.fullmatch(r"[0-9a-f]{40}", str(current.get("head")))
    assert current.get("commit_status") == "committed"
    assert current.get("worktree_commit_pending") is False
    # R1/R2 已审计失败，不得再写 NOT_AUDITED_YET。
    checkpoints = manifest["checkpoints"]
    by_id = {
        cp.get("checkpoint_id") or cp.get("id"): cp for cp in checkpoints
    }
    r1 = by_id["MILESTONE_B_AUDIT_REMEDIATION_1"]
    assert r1["audit_conclusion"] == "MILESTONE_B_REMEDIATION_1_REAUDIT_FAILED"
    r2 = by_id["MILESTONE_B_AUDIT_REMEDIATION_2"]
    assert r2["commit"] == "0793c819ad45cc21328fad7d8afa6882d6197613"
    assert r2["audit_conclusion"] == "MILESTONE_B_REMEDIATION_2_REAUDIT_FAILED"
    assert r2["worktree_commit_pending"] is False
    # R3 当前只能 NOT_AUDITED_YET（工作树 precommit）。
    r3 = by_id["MILESTONE_B_AUDIT_REMEDIATION_3"]
    assert r3["status"] == "worktree_pending_precommit"
    assert r3["independent_audit_done"] is False
    assert r3["audit_conclusion"] == "NOT_AUDITED_YET"


def test_manifest_no_r3_passed_claim() -> None:
    text = json.dumps(_manifest(), ensure_ascii=False)
    assert "MILESTONE_B_REMEDIATION_3_REAUDIT_PASSED" not in text
    assert "REMEDIATION_3_PASSED" not in text


def test_manifest_current_scope_flags_unique_and_correct() -> None:
    feature_status = _manifest()["feature_status"]
    for key in (
        "authoritative_full_game_core",
        "multi_player_production_proven",
        "milestone_b_complete",
        "formal_duel_global_all_cards_implemented",
    ):
        assert feature_status[key] is False, key
    assert feature_status["formal_duel_no_skill_ready"] is True
    assert feature_status["formal_duel_duel_scope_all_cards_sufficient"] is True


def test_four_docs_current_remediation_3_state() -> None:
    for name in (
        "ENGINE_STATUS.md",
        "IMPLEMENTATION_MATRIX.md",
        "MASTER_IMPLEMENTATION_PLAN.md",
        "MILESTONE_B_DEPENDENCY_GRAPH.md",
    ):
        text = (REPOSITORY_ROOT / "docs" / name).read_text(encoding="utf-8")
        assert "MILESTONE_B_REMEDIATION_2_REAUDIT_FAILED" in text, name
        assert "NOT_AUDITED_YET" in text, name
        assert "MILESTONE_B_REMEDIATION_3_REAUDIT_PASSED" not in text, name
