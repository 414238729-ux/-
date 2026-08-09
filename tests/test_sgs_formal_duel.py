from __future__ import annotations

import json

import pytest
import scripts.sgs_engine.formal_duel as formal_duel_module

from scripts.sgs_engine import (
    FORMAL_NO_SKILL_DUEL_MODE,
    PRODUCTION_BASIC_CARDS_MODE,
    BatchReferenceController,
    CharacterMetadata,
    FormalDuelConfiguration,
    FormalDuelConfigurationError,
    FormalNoSkillDuelSession,
    GameState,
    ProductionBasicCardBatch,
    ProductionReplayFormatError,
    canonical_json,
    inspect_formal_duel_readiness,
    record_reference_formal_duel,
    reexecute_production_replay,
    run_formal_duel_seed_sweep,
)


def test_formal_duel_factory_reuses_authoritative_production_core() -> None:
    configuration = FormalDuelConfiguration.analysis_convention()
    game = FormalNoSkillDuelSession(
        seed=17,
        configuration=configuration,
        analysis_only=True,
        session_id="formal-duel-test",
        session_secret=b"f" * 32,
    )

    assert isinstance(game, ProductionBasicCardBatch)
    assert isinstance(game.state, GameState)
    assert game.mode_id == FORMAL_NO_SKILL_DUEL_MODE
    assert game.mode_id != PRODUCTION_BASIC_CARDS_MODE
    assert len(game.state.cards) == 160
    assert len(game.state.players) == 2
    assert game.formal_result_eligible is False
    binding = game.registry.binding_value(game.mode_id, game.phase.value)
    assert binding["adapter_version"] == "production-basic-cards-batch-rules.v2"
    assert game._context().mode == FORMAL_NO_SKILL_DUEL_MODE
    assert game.execution_snapshot["mode"] == FORMAL_NO_SKILL_DUEL_MODE


def test_formal_duel_configuration_cannot_self_authorize_formal_result() -> None:
    confirmed_by_caller = FormalDuelConfiguration(
        platform="三国杀移动版",
        version="untrusted-test-value",
        source_location="caller-payload-is-not-a-trust-boundary",
        verification_status="当前确认",
        deck_applicable=True,
        initial_hand_count=4,
        player_hp=(4, 4),
        player_max_hp=(4, 4),
        first_player_policy="deterministic_rng",
        participants=(
            CharacterMetadata("test_general_a", "male"),
            CharacterMetadata("test_general_b", "female"),
        ),
    )

    assert confirmed_by_caller.source_confirmed is True
    with pytest.raises(FormalDuelConfigurationError, match="门禁未关闭"):
        FormalNoSkillDuelSession(
            seed=0,
            configuration=confirmed_by_caller,
            analysis_only=False,
        )

    class CallerReleasedSubclass(FormalNoSkillDuelSession):
        FORMAL_EXECUTION_RELEASED = True

    with pytest.raises(TypeError, match="canonical会话不允许通过子类"):
        CallerReleasedSubclass(
            seed=0,
            configuration=confirmed_by_caller,
            analysis_only=False,
        )


def test_live_readiness_has_exact_mode_scoped_card_semantics() -> None:
    readiness = inspect_formal_duel_readiness()
    statuses = {
        item.card_key: item for item in readiness.card_semantic_statuses
    }

    assert readiness.deck_count == 160
    assert readiness.registered_card_key_count == 38
    assert readiness.registered_instance_count == 160
    assert readiness.global_complete_card_key_count == 36
    assert readiness.global_complete_instance_count == 158
    assert readiness.duel_complete_card_key_count == 37
    assert readiness.duel_complete_instance_count == 159
    assert len(statuses) == 38
    assert statuses["sgs_weapon_fangtianhuaji"].global_status == "PARTIAL"
    assert (
        statuses["sgs_weapon_fangtianhuaji"].duel_status
        == "NOT_APPLICABLE_TO_DUEL"
    )
    assert statuses["sgs_weapon_cixiongshuanggujian"].global_status == "COMPLETE"
    assert statuses["sgs_weapon_cixiongshuanggujian"].duel_status == "COMPLETE"
    assert statuses["sgs_weapon_zhangbashemao"].duel_status == (
        "RULE_SOURCE_GAP"
    )
    assert "typed virtual-card/subcard" in (
        statuses["sgs_weapon_zhangbashemao"].reason or ""
    )
    blocker_codes = {item.code for item in readiness.blockers}
    assert "TYPED_VIRTUAL_CARD_REFERENCE_NOT_IMPLEMENTED" not in blocker_codes
    assert readiness.mode_runtime_reachable is True
    assert readiness.reexecution_replay_supported is True
    assert readiness.unsupported_rules == 2
    assert readiness.approximation_count == 0
    assert readiness.acceptance_seed_count == 0
    assert readiness.acceptance_natural_end_count == 0
    assert readiness.acceptance_failure_count == 0
    assert readiness.acceptance_seed_results == ()
    assert readiness.fixed_seed_acceptance_passed is False
    assert readiness.all_cards_implemented is False
    assert readiness.mode_implemented is False
    assert readiness.formal_duel_no_skill_ready is False


def test_formal_configuration_rejects_non_string_participant_fields() -> None:
    payload = FormalDuelConfiguration.analysis_convention().to_dict()
    payload["participants"] = [
        {"character_key": "general_a", "gender": "male", 7: "forged"},
        None,
    ]

    with pytest.raises(FormalDuelConfigurationError, match="字段名必须是字符串"):
        FormalDuelConfiguration.from_dict(payload)


def test_analysis_formal_duel_strictly_reexecutes_without_second_replay() -> None:
    record = record_reference_formal_duel(
        6,
        configuration=FormalDuelConfiguration.analysis_convention(),
        analysis_only=True,
        controller=BatchReferenceController(),
        max_steps=500,
    )

    assert record.header["mode_id"] == FORMAL_NO_SKILL_DUEL_MODE
    assert record.header["formal_result"] is False
    assert record.header["fixture_applied"] is False
    assert set(record.header["initial_configuration"]) == {
        "formal_duel_configuration",
        "analysis_only",
        "max_steps",
    }
    result = reexecute_production_replay(record)
    assert result.verified is True
    assert result.decision_count == len(record.decisions)

    public = record.player_visible_payload(viewer_id="p1")
    assert "authoritative_private" not in public
    assert public["header"]["mode_id"] == FORMAL_NO_SKILL_DUEL_MODE
    assert public["header"]["formal_result"] is False
    assert "session_secret_hex" not in canonical_json(public)


def test_formal_seed_sweep_records_every_failed_seed_without_resampling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requested = (11, 12, 13)
    real_factory = formal_duel_module.FormalNoSkillDuelSession

    def flaky_factory(*args: object, **kwargs: object):
        seed = kwargs.get("seed")
        if seed == 12:
            raise RuntimeError("deterministic factory failure")
        return real_factory(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(
        formal_duel_module,
        "FormalNoSkillDuelSession",
        flaky_factory,
    )
    results = run_formal_duel_seed_sweep(
        requested,
        configuration=FormalDuelConfiguration.analysis_convention(),
        analysis_only=True,
        max_steps=1,
    )

    assert tuple(item.seed for item in results) == requested
    assert len(results) == len(requested)
    assert all(item.natural_end is False for item in results)
    assert results[0].safety_cap_triggered is True
    assert results[0].exception_type == "ProductionBatchSafetyLimitError"
    assert results[1].safety_cap_triggered is False
    assert results[1].exception_type == "RuntimeError"
    assert results[1].action_count == 0
    assert results[2].safety_cap_triggered is True
    assert results[2].exception_type == "ProductionBatchSafetyLimitError"
    assert all(item.unsupported_rules == 1 for item in results)
    assert all(item.approximation_count == 1 for item in results)
    # 结构化记录必须能逐 seed 序列化；不得只保留成功样本。
    assert [item["seed"] for item in json.loads(json.dumps(
        [result.to_dict() for result in results], ensure_ascii=False
    ))] == list(requested)


def test_formal_regression_seeds_have_no_core_consistency_failure() -> None:
    """保留已暴露异常的原 seed；规则缺口之外不得再异常或触发上限。"""

    # 18/31/44/54/79/82 曾因合法动作被action_id哈希重排而优先重铸
    # 【铁索连环】，在“弃铁索→摸回同一张铁索”的可达状态形成无进展循环。
    # 必须保留原seed与2000上限，不能删除失败样本或提高cap。
    requested = (7, 10, 51, 76, 94, 56, 87, 18, 31, 44, 54, 79, 82)
    results = run_formal_duel_seed_sweep(
        requested,
        configuration=FormalDuelConfiguration.analysis_convention(),
        analysis_only=True,
        max_steps=2000,
    )

    assert tuple(item.seed for item in results) == requested
    assert all(item.safety_cap_triggered is False for item in results)
    assert all(
        item.exception_type in (None, "UnsupportedRuleError")
        for item in results
    )


def test_formal_replay_rejects_fixture_injection() -> None:
    game = FormalNoSkillDuelSession(
        seed=1,
        configuration=FormalDuelConfiguration.analysis_convention(),
        analysis_only=True,
    )

    from scripts.sgs_engine.production_replay import record_reference_production_batch

    with pytest.raises(
        ProductionReplayFormatError, match="正式单挑回放禁止夹具"
    ):
        record_reference_production_batch(
            1,
            _game=game,
            fixture=lambda _game: None,
        )


def test_formal_replay_enforces_root_config_cap_and_finish_schema() -> None:
    from scripts.sgs_engine.production_replay import ProductionReexecutionReplay

    record = record_reference_formal_duel(
        6,
        configuration=FormalDuelConfiguration.analysis_convention(),
        analysis_only=True,
        controller=BatchReferenceController(),
        max_steps=500,
    )

    extra_root = record.to_dict()
    extra_root["unexpected_root_field"] = True
    with pytest.raises(ProductionReplayFormatError, match="未知字段"):
        ProductionReexecutionReplay.from_dict(extra_root)

    missing_root = record.to_dict()
    del missing_root["record_sha256"]
    with pytest.raises(ProductionReplayFormatError, match="缺少字段"):
        ProductionReexecutionReplay.from_dict(missing_root)

    extra_config = record.to_dict()
    extra_config["header"]["initial_configuration"]["shuffle"] = True
    with pytest.raises(ProductionReplayFormatError, match="initial_configuration"):
        ProductionReexecutionReplay.from_dict(extra_config)

    bad_cap = record.to_dict()
    bad_cap["header"]["initial_configuration"]["max_steps"] = (
        record.outcome["step_count"] - 1
    )
    with pytest.raises(ProductionReplayFormatError, match="不能小于终局step_count"):
        ProductionReexecutionReplay.from_dict(bad_cap)

    bad_reason = record.to_dict()
    bad_reason["outcome"]["finish_reason"] = "caller_supplied_reason"
    with pytest.raises(ProductionReplayFormatError, match="finish_reason"):
        ProductionReexecutionReplay.from_dict(bad_reason)


def test_formal_replay_internal_game_requires_exact_canonical_type() -> None:
    from scripts.sgs_engine.production_replay import record_reference_production_batch

    class NonCanonicalFormalSession(FormalNoSkillDuelSession):
        def __init__(self) -> None:
            # 绕开 formal 子类构造防线，仅用于验证 replay 工厂本身也独立拒绝。
            ProductionBasicCardBatch.__init__(self, seed=1)

    game = NonCanonicalFormalSession()
    with pytest.raises(
        ProductionReplayFormatError, match="canonical FormalNoSkillDuelSession"
    ):
        record_reference_production_batch(1, _game=game)


def test_internal_game_keeps_ordinary_production_batch_subclass_compatible() -> None:
    from scripts.sgs_engine.production_replay import record_reference_production_batch

    class CompatibleProductionBatch(ProductionBasicCardBatch):
        @property
        def formal_result_eligible(self) -> bool:
            # 普通 batch 即使碰巧暴露同名属性，也不能影响正式结果标记。
            return True

    game = CompatibleProductionBatch(seed=5)
    record = record_reference_production_batch(5, _game=game, max_steps=500)

    assert record.header["mode_id"] == PRODUCTION_BASIC_CARDS_MODE
    assert record.header["formal_result"] is False
    assert reexecute_production_replay(record).verified is True
