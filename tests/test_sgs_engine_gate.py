from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from scripts.sgs_engine_gate import (
    FORMAL_DECK_CARD_COUNT,
    DeckReadiness,
    EngineSourceKind,
    FormalSimulationBlockedError,
    FormalSimulationManifest,
    GateIssueCode,
    GeneralReadiness,
    evaluate_formal_run_gate,
    inspect_engine_source,
    require_formal_simulation_ready,
)


def _verified_formal_source(tmp_path: Path):
    repository = tmp_path / "formal-repository"
    core = repository / "scripts" / "sgs_engine"
    core.mkdir(parents=True, exist_ok=True)
    (core / "__init__.py").write_text(
        "from .engine import AuthoritativeCoreSession\n", encoding="utf-8"
    )
    (core / "engine.py").write_text(
        "class AuthoritativeCoreSession:\n    pass\n", encoding="utf-8"
    )
    entrypoint = repository / "scripts" / "run_formal_simulation.py"
    entrypoint.write_text(
        "from scripts.sgs_engine import AuthoritativeCoreSession\n\n"
        "def build_session():\n"
        "    return AuthoritativeCoreSession()\n",
        encoding="utf-8",
    )
    return inspect_engine_source(
        repository_root=repository,
        entrypoint_path=entrypoint,
    )


def _manifest(tmp_path: Path, **overrides: object) -> FormalSimulationManifest:
    """默认保持至少一个真实阻塞项，避免用全True清单自证正式可运行。"""

    values: dict[str, object] = {
        "mode_name": "2v2",
        "ruleset_version": "sgs-mobile-user-ruleset-2026-08-01",
        "unsupported_rules": 1,
        "approximation_count": 0,
        "mode_implemented": False,
        "ai_implemented": False,
        "generals": (
            GeneralReadiness("武将甲", False, False),
            GeneralReadiness("武将乙", False, False),
        ),
        "deck": DeckReadiness(True, 160, unique_instance_ids=True),
        "source": _verified_formal_source(tmp_path),
    }
    values.update(overrides)
    return FormalSimulationManifest(**values)  # type: ignore[arg-type]


def test_source_kind_core_use_and_hash_are_derived_from_real_source(tmp_path: Path) -> None:
    source = _verified_formal_source(tmp_path)

    assert source.source_kind is EngineSourceKind.FORMAL_RULE_CORE
    assert source.uses_authoritative_rule_core is True
    assert source.inspection_issues == ()
    assert source.imported_core_modules == ("scripts.sgs_engine",)
    assert source.source_sha256 == hashlib.sha256(source.entrypoint_path.read_bytes()).hexdigest()


def test_source_inspector_rejects_caller_supplied_source_claims(tmp_path: Path) -> None:
    entry = tmp_path / "run.py"
    entry.write_text("# 没有核心导入\n", encoding="utf-8")

    with pytest.raises(TypeError):
        inspect_engine_source(  # type: ignore[call-arg]
            repository_root=tmp_path,
            entrypoint_path=entry,
            source_kind=EngineSourceKind.FORMAL_RULE_CORE,
            uses_authoritative_rule_core=True,
        )


def test_comment_only_fake_entrypoint_cannot_claim_formal_capability(tmp_path: Path) -> None:
    repository = tmp_path / "repo"
    entry = repository / "scripts" / "runner.py"
    entry.parent.mkdir(parents=True)
    entry.write_text("# formal test entrypoint\n", encoding="utf-8")

    source = inspect_engine_source(repository_root=repository, entrypoint_path=entry)

    assert source.source_kind is EngineSourceKind.UNKNOWN
    assert source.uses_authoritative_rule_core is False
    assert any("未导入" in issue for issue in source.inspection_issues)


def test_import_claim_without_real_core_package_is_rejected(tmp_path: Path) -> None:
    repository = tmp_path / "repo"
    entry = repository / "scripts" / "runner.py"
    entry.parent.mkdir(parents=True)
    entry.write_text("from scripts.sgs_engine import AuthoritativeCoreSession\n", encoding="utf-8")

    source = inspect_engine_source(repository_root=repository, entrypoint_path=entry)

    assert source.uses_authoritative_rule_core is False
    assert source.source_kind is EngineSourceKind.UNKNOWN
    assert any("核心包不完整" in issue for issue in source.inspection_issues)


def test_repo_test_path_remains_test_double_even_when_importing_core(tmp_path: Path) -> None:
    source = _verified_formal_source(tmp_path)
    test_entry = source.repository_root / "tests" / "fake_engine.py"
    test_entry.parent.mkdir()
    test_entry.write_text("from scripts.sgs_engine import AuthoritativeCoreSession\n", encoding="utf-8")

    audited = inspect_engine_source(
        repository_root=source.repository_root,
        entrypoint_path=test_entry,
    )

    assert audited.source_kind is EngineSourceKind.TEST_DOUBLE
    assert audited.uses_authoritative_rule_core is True


def test_external_legacy_filename_is_derived_and_rejected(tmp_path: Path) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    legacy = tmp_path / "downloads" / "sgs_sim_engine_worker.py"
    legacy.parent.mkdir()
    legacy.write_text("import random\n", encoding="utf-8")
    source = inspect_engine_source(repository_root=repository, entrypoint_path=legacy)

    result = evaluate_formal_run_gate(_manifest(tmp_path, source=source))

    assert source.source_kind is EngineSourceKind.LEGACY_APPROXIMATOR
    assert GateIssueCode.ENTRYPOINT_OUTSIDE_REPOSITORY in result.issue_codes
    assert GateIssueCode.LEGACY_SOURCE in result.issue_codes
    assert GateIssueCode.AUTHORITATIVE_CORE_NOT_USED in result.issue_codes


def test_syntax_error_is_hashed_but_fails_source_inspection(tmp_path: Path) -> None:
    repository = tmp_path / "repo"
    entry = repository / "scripts" / "runner.py"
    entry.parent.mkdir(parents=True)
    entry.write_text("def broken(:\n", encoding="utf-8")

    source = inspect_engine_source(repository_root=repository, entrypoint_path=entry)

    assert source.source_sha256 is not None
    assert source.source_kind is EngineSourceKind.UNKNOWN
    assert any("AST解析失败" in issue for issue in source.inspection_issues)


def test_missing_entrypoint_is_structurally_reported(tmp_path: Path) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    source = inspect_engine_source(
        repository_root=repository,
        entrypoint_path=repository / "scripts" / "missing.py",
    )

    result = evaluate_formal_run_gate(_manifest(tmp_path, source=source))

    assert source.source_sha256 is None
    assert GateIssueCode.ENTRYPOINT_NOT_FOUND in result.issue_codes
    assert GateIssueCode.SOURCE_INSPECTION_FAILED in result.issue_codes


def test_gate_reinspects_source_and_rejects_stale_snapshot(tmp_path: Path) -> None:
    source = _verified_formal_source(tmp_path)
    manifest = _manifest(tmp_path, source=source)
    source.entrypoint_path.write_text("# core import removed\n", encoding="utf-8")

    result = evaluate_formal_run_gate(manifest)

    assert GateIssueCode.SOURCE_INSPECTION_FAILED in result.issue_codes
    assert GateIssueCode.AUTHORITATIVE_CORE_NOT_USED in result.issue_codes


def test_formal_deck_expected_count_is_fixed_and_not_caller_configurable(tmp_path: Path) -> None:
    deck = DeckReadiness(loaded=True, card_count=12, unique_instance_ids=True)
    assert deck.expected_card_count == FORMAL_DECK_CARD_COUNT == 160

    result = evaluate_formal_run_gate(_manifest(tmp_path, deck=deck))
    assert GateIssueCode.DECK_INCOMPLETE in result.issue_codes

    with pytest.raises(TypeError):
        DeckReadiness(  # type: ignore[call-arg]
            loaded=True,
            card_count=12,
            expected_card_count=12,
            unique_instance_ids=True,
        )


@pytest.mark.parametrize(
    ("deck", "expected_code"),
    (
        (DeckReadiness(False, 0), GateIssueCode.DECK_NOT_LOADED),
        (DeckReadiness(True, 159), GateIssueCode.DECK_INCOMPLETE),
        (DeckReadiness(True, 160, unique_instance_ids=False), GateIssueCode.DECK_INSTANCE_IDS_NOT_UNIQUE),
    ),
)
def test_unloaded_or_incomplete_deck_closes_gate(
    tmp_path: Path, deck: DeckReadiness, expected_code: GateIssueCode
) -> None:
    result = evaluate_formal_run_gate(_manifest(tmp_path, deck=deck))
    assert expected_code in result.issue_codes


def test_unimplemented_or_untested_generals_are_named(tmp_path: Path) -> None:
    manifest = _manifest(
        tmp_path,
        generals=(
            GeneralReadiness("未实现武将", False, False),
            GeneralReadiness("未过测试武将", True, False),
        ),
    )

    result = evaluate_formal_run_gate(manifest)
    messages = "\n".join(issue.message for issue in result.issues)

    assert GateIssueCode.GENERAL_NOT_IMPLEMENTED in result.issue_codes
    assert GateIssueCode.GENERAL_TESTS_FAILED in result.issue_codes
    assert "未实现武将" in messages
    assert "未过测试武将" in messages


def test_empty_participant_list_is_not_a_formal_game(tmp_path: Path) -> None:
    result = evaluate_formal_run_gate(_manifest(tmp_path, generals=()))
    assert GateIssueCode.NO_PARTICIPATING_GENERALS in result.issue_codes


def test_gate_is_deterministic_and_does_not_mutate_manifest(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path, unsupported_rules=2)
    first = evaluate_formal_run_gate(manifest)
    second = evaluate_formal_run_gate(manifest)
    assert first == second
    assert manifest.unsupported_rules == 2


def test_require_ready_raises_aggregated_chinese_error_without_fallback(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path, unsupported_rules=3, approximation_count=2)

    with pytest.raises(FormalSimulationBlockedError) as captured:
        require_formal_simulation_ready(manifest)

    message = str(captured.value)
    assert "正式模拟已被失败关闭门禁拒绝" in message
    assert "3项规则未实现" in message
    assert "2项近似替代" in message
    assert captured.value.result.ready is False


def test_caller_cannot_self_certify_full_game_core(tmp_path: Path) -> None:
    manifest = _manifest(
        tmp_path,
        unsupported_rules=0,
        approximation_count=0,
        mode_implemented=True,
        ai_implemented=True,
        ruleset_version="test-ruleset",
    )

    result = evaluate_formal_run_gate(manifest)

    assert manifest.authoritative_full_game_core is False
    assert GateIssueCode.FULL_GAME_CORE_NOT_IMPLEMENTED in result.issue_codes
    with pytest.raises(TypeError):
        FormalSimulationManifest(
            mode_name=manifest.mode_name,
            ruleset_version=manifest.ruleset_version,
            unsupported_rules=0,
            approximation_count=0,
            mode_implemented=True,
            ai_implemented=True,
            generals=manifest.generals,
            deck=manifest.deck,
            source=manifest.source,
            authoritative_full_game_core=True,
        )


def test_invalid_counts_are_rejected_with_clear_chinese_error(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="未支持规则数量不能小于0"):
        _manifest(tmp_path, unsupported_rules=-1)
    with pytest.raises(TypeError, match="近似替代数量必须是非负整数"):
        _manifest(tmp_path, approximation_count=True)
