from __future__ import annotations

import json
from pathlib import Path

import pytest
import scripts.sgs_engine.formal_duel as formal_duel_module

from scripts.sgs_engine import (
    FORMAL_NO_SKILL_DUEL_MODE,
    PRODUCTION_BASIC_CARDS_MODE,
    BatchReferenceController,
    BatchActionIdController,
    CharacterMetadata,
    FormalDuelConfiguration,
    FormalDuelConfigurationError,
    FormalDuelReferenceController,
    FormalDuelSeedResult,
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

# 冻结 Milestone B R8 时代的实现身份（历史证据常量，不得改写）。
FROZEN_R8_IMPLEMENTATION_IDENTITY = (
    "06c8b2d3ead9adb52a18252e398eae137eb8fb51f657909051500893672b0e33"
)
_ACCEPTANCE_ARTIFACT_PATH = (
    Path(__file__).resolve().parents[1]
    / "docs"
    / "FORMAL_MILESTONE_B_100_SEED_ACCEPTANCE.json"
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

    # MB-M-005：调用方自建配置即使数值看起来“当前确认”，也不能自行获得
    # trusted provenance；source_confirmed 只能由 canonical factory 授予。
    assert confirmed_by_caller.source_confirmed is False
    with pytest.raises(
        FormalDuelConfigurationError, match="TrustedFormalDuelConfiguration"
    ):
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
    assert readiness.global_complete_card_key_count == 37
    assert readiness.global_complete_instance_count == 159
    assert readiness.duel_complete_card_key_count == 38
    assert readiness.duel_complete_instance_count == 160
    assert len(statuses) == 38
    assert statuses["sgs_weapon_fangtianhuaji"].global_status == "PARTIAL"
    assert (
        statuses["sgs_weapon_fangtianhuaji"].duel_status
        == "NOT_APPLICABLE_TO_DUEL"
    )
    assert statuses["sgs_weapon_cixiongshuanggujian"].global_status == "COMPLETE"
    assert statuses["sgs_weapon_cixiongshuanggujian"].duel_status == "COMPLETE"
    assert statuses["sgs_weapon_zhangbashemao"].global_status == "COMPLETE"
    assert statuses["sgs_weapon_zhangbashemao"].duel_status == "COMPLETE"
    assert "HAND→PROCESSING→DISCARD" in (
        statuses["sgs_weapon_zhangbashemao"].reason or ""
    )
    blocker_codes = {item.code for item in readiness.blockers}
    assert blocker_codes == set()
    assert readiness.mode_runtime_reachable is True
    assert readiness.reexecution_replay_supported is True
    assert readiness.unsupported_rules == 0
    assert readiness.approximation_count == 0
    # MB-B-001：缓存报告有效性只由身份绑定决定；静态执行资格与缓存分离。
    # POST-B C1：冻结 R8 acceptance artifact 是历史证据，不是 current
    # certification。其规则/牌堆身份未变，只有 implementation identity
    # 被 C1 有意改变 → 缓存证据按设计 stale（valid=False / 0 seeds），
    # 静态执行资格（formal_duel_execution_ready）不受影响。
    assert readiness.formal_duel_execution_ready is True
    artifact_payload = json.loads(
        _ACCEPTANCE_ARTIFACT_PATH.read_text(encoding="utf-8")
    )
    assert (
        artifact_payload["implementation_identity"]
        == FROZEN_R8_IMPLEMENTATION_IDENTITY
    )
    assert (
        formal_duel_module.rules_profile_identity()
        == artifact_payload["rules_profile_identity"]
    )
    assert (
        formal_duel_module.deck_identity()
        == artifact_payload["deck_identity"]
    )
    identity_matches = (
        formal_duel_module.implementation_identity()
        == FROZEN_R8_IMPLEMENTATION_IDENTITY
    )
    assert readiness.cached_acceptance_report_valid is identity_matches
    assert readiness.cached_acceptance_seed_count == (
        100 if identity_matches else 0
    )
    assert readiness.acceptance_seed_count == (
        readiness.cached_acceptance_seed_count
    )
    assert readiness.acceptance_natural_end_count == (
        100 if identity_matches else 0
    )
    assert readiness.fixed_seed_acceptance_passed is identity_matches
    assert readiness.cached_fixed_seed_acceptance_passed is identity_matches
    assert len(readiness.acceptance_seed_results) == (
        readiness.acceptance_seed_count
    )
    # MB-B-004：能力必须分层——duel scope 充分，但全局完整引擎不得成立。
    assert readiness.duel_scope_all_cards_sufficient is True
    assert readiness.global_all_cards_implemented is False
    assert readiness.global_card_semantics_complete is False
    assert readiness.mode_implemented is True
    assert readiness.formal_duel_no_skill_ready is True


def test_formal_configuration_rejects_non_string_participant_fields() -> None:
    payload = FormalDuelConfiguration.analysis_convention().to_dict()
    payload["participants"] = [
        {
            "character_key": "general_a",
            "intrinsic_gender": "male",
            "effective_gender": None,
            7: "forged",
        },
        None,
    ]

    with pytest.raises(FormalDuelConfigurationError, match="字段名必须是字符串"):
        FormalDuelConfiguration.from_dict(payload)


def test_from_dict_cannot_self_authorize_canonical_profile() -> None:
    """普通 JSON 反序列化即使与 canonical 数值完全相同，也不能获得可信来源。"""

    canonical = FormalDuelConfiguration.formal_profile()
    rebuilt = FormalDuelConfiguration.from_dict(canonical.to_dict())
    assert rebuilt.to_dict() == canonical.to_dict()
    assert rebuilt.source_confirmed is False
    with pytest.raises(
        FormalDuelConfigurationError, match="TrustedFormalDuelConfiguration"
    ):
        FormalNoSkillDuelSession(
            seed=0,
            configuration=rebuilt,
            analysis_only=False,
        )


def test_from_canonical_profile_value_accepts_only_exact_profile() -> None:
    """replay 加载正式记录时验证 canonical 内容，而不是让 payload 自证。"""

    from scripts.sgs_engine.formal_duel import (
        FormalDuelConfiguration as _Config,
    )

    canonical = _Config.formal_profile()
    trusted = _Config.from_canonical_profile_value(canonical.to_dict())
    assert trusted.source_confirmed is True
    assert trusted == canonical

    tampered = dict(canonical.to_dict())
    tampered["initial_hand_count"] = 5
    with pytest.raises(
        FormalDuelConfigurationError, match="必须与项目 canonical formal profile"
    ):
        _Config.from_canonical_profile_value(tampered)


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
    real_init = real_factory.__init__

    def flaky_init(self: object, *args: object, **kwargs: object):
        seed = kwargs.get("seed")
        if seed == 12:
            raise RuntimeError("deterministic factory failure")
        real_init(self, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(
        real_factory, "__init__", flaky_init
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


# ---------------------------------------------------------------------------
# MB-B-001：acceptance artifact provenance 攻击矩阵
# ---------------------------------------------------------------------------


def _fake_seed_results() -> tuple[FormalDuelSeedResult, ...]:
    return tuple(
        FormalDuelSeedResult(
            seed=seed,
            deck_count=160,
            winner="p1" if seed % 2 == 0 else "p2",
            action_count=100 + seed,
            turn_count=10 + seed,
            draw_pile_count=20,
            reshuffle_count=seed % 3,
            unsupported_rules=0,
            approximation_count=0,
            safety_cap_triggered=False,
            exception_type=None,
            exception_message=None,
            reached_card_keys=("sgs_basic_sha",),
            natural_end=True,
            formal_result_eligible=True,
            reexecution_verified=True,
            final_state_hash="a" * 64,
        )
        for seed in range(100)
    )


def _write_artifact(
    tmp_path, mutator=None
):
    path = tmp_path / "artifact.json"
    formal_duel_module.write_formal_acceptance_artifact(
        _fake_seed_results(), path, elapsed_seconds=1.0
    )
    if mutator is not None:
        payload = json.loads(path.read_text(encoding="utf-8"))
        mutator(payload)
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    return path


def test_acceptance_artifact_valid_roundtrip_loads_100_seeds(tmp_path) -> None:
    path = _write_artifact(tmp_path)
    valid, loaded = formal_duel_module._load_acceptance_evidence(path)
    assert valid is True
    assert len(loaded) == 100
    assert tuple(item.seed for item in loaded) == tuple(range(100))
    assert all(item.reexecution_verified for item in loaded)


def test_acceptance_artifact_attack_matrix_fail_closed(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """全部清单性篡改必须 fail-closed，不允许任何一项伪装成验收证据。"""

    def mutate_seeds(payload):
        payload["seeds"] = list(range(99)) + [101]

    def mutate_seed_count(payload):
        payload["seed_count"] = 99

    def mutate_missing_seed(payload):
        payload["seeds_detail"] = payload["seeds_detail"][:-1]

    def mutate_duplicate_seed(payload):
        payload["seeds_detail"][99]["seed"] = 0

    def mutate_out_of_range_seed(payload):
        payload["seeds_detail"][0]["seed"] = 100

    def mutate_illegal_winner(payload):
        payload["seeds_detail"][0]["winner"] = "p3"

    def mutate_strict_false(payload):
        payload["seeds_detail"][0]["strict_reexecution"] = False

    def mutate_unsupported(payload):
        payload["seeds_detail"][0]["unsupported_rules"] = 1

    def mutate_approximation(payload):
        payload["seeds_detail"][0]["approximation_count"] = 1

    def mutate_natural_end(payload):
        payload["seeds_detail"][0]["natural_end"] = False

    def mutate_hash_x(payload):
        payload["seeds_detail"][0]["final_state_hash"] = "x"

    def mutate_hash_malformed(payload):
        payload["seeds_detail"][0]["final_state_hash"] = "a" * 63

    def mutate_analysis_only(payload):
        payload["analysis_only"] = True

    def mutate_profile(payload):
        payload["canonical_formal_profile"]["initial_hand_count"] = 5

    def mutate_deck_identity(payload):
        payload["deck_identity"] = "0" * 64

    def mutate_rules_identity(payload):
        payload["rules_profile_identity"] = "0" * 64

    def mutate_implementation_identity(payload):
        payload["implementation_identity"] = "0" * 64

    def mutate_passed(payload):
        payload["passed"] = False

    def mutate_failures(payload):
        payload["failures"] = [{"seed": 0, "reason": "forged"}]

    def mutate_extra_field(payload):
        payload["forged_extra"] = True

    def mutate_missing_field(payload):
        del payload["seeds"]

    def mutate_detail_extra_field(payload):
        payload["seeds_detail"][0]["forged"] = True

    def mutate_detail_missing_field(payload):
        del payload["seeds_detail"][0]["winner"]

    def mutate_action_count_zero(payload):
        payload["seeds_detail"][0]["action_count"] = 0

    mutators = (
        mutate_seeds,
        mutate_seed_count,
        mutate_missing_seed,
        mutate_duplicate_seed,
        mutate_out_of_range_seed,
        mutate_illegal_winner,
        mutate_strict_false,
        mutate_unsupported,
        mutate_approximation,
        mutate_natural_end,
        mutate_hash_x,
        mutate_hash_malformed,
        mutate_analysis_only,
        mutate_profile,
        mutate_deck_identity,
        mutate_rules_identity,
        mutate_implementation_identity,
        mutate_passed,
        mutate_failures,
        mutate_extra_field,
        mutate_missing_field,
        mutate_detail_extra_field,
        mutate_detail_missing_field,
        mutate_action_count_zero,
    )
    for index, mutator in enumerate(mutators):
        path = _write_artifact(tmp_path / f"case-{index}", mutator)
        assert formal_duel_module._load_acceptance_evidence(path) == (False, ()), (
            f"篡改用例 #{index} 必须 fail-closed：{mutator.__name__}"
        )


# ---------------------------------------------------------------------------
# MB-B-003：同一 seed、不同 session secret 的语义确定性
# ---------------------------------------------------------------------------


def _semantic_action_value(action) -> dict[str, object]:
    payload = {
        key: value
        for key, value in action.payload.items()
        if key != "handle"
    }
    return {
        "action_type": action.action_type.value,
        "actor_id": action.actor_id,
        "card_instance_id": action.card_instance_id,
        "virtual_card": (
            None if action.virtual_card is None else action.virtual_card.to_dict()
        ),
        "target_ids": list(action.target_ids),
        "payload": payload,
    }


def _semantic_trace(
    seed: int, session_secret: bytes
) -> tuple[list[list[dict[str, object]]], str | None, int, str, list[dict[str, object]]]:
    from scripts.sgs_engine.engine import canonical_state_snapshot
    from scripts.sgs_engine.replay import state_sha256

    game = FormalNoSkillDuelSession(
        seed=seed,
        configuration=FormalDuelConfiguration.formal_profile(),
        analysis_only=False,
        session_id="determinism-test",
        session_secret=session_secret,
    )
    controller = FormalDuelReferenceController()
    semantic_steps: list[list[dict[str, object]]] = []
    raw_actions: list[dict[str, object]] = []
    guard = 0
    while not game.is_finished:
        if guard >= 2000:
            raise RuntimeError("determinism 测试未在2000步内结束")
        legal = game.legal_actions()
        context = game._context()
        chosen = controller.choose(legal, context)
        semantic_steps.append([_semantic_action_value(item) for item in legal])
        raw_actions.append(_semantic_action_value(chosen))
        game.step(BatchActionIdController(chosen.action_id))
        guard += 1
    final_hash = state_sha256(canonical_state_snapshot(game.state))
    return (
        semantic_steps,
        game.winner_id,
        game.step_count,
        final_hash,
        raw_actions,
    )


def test_same_seed_different_session_secret_is_semantically_deterministic() -> None:
    """session secret 只保护 opaque handle；不得改变语义顺序/选择/胜负。"""

    trace_a, winner_a, count_a, hash_a, chosen_a = _semantic_trace(
        7, b"a" * 32
    )
    trace_b, winner_b, count_b, hash_b, chosen_b = _semantic_trace(
        7, b"b" * 32
    )

    assert trace_a == trace_b
    assert chosen_a == chosen_b
    assert winner_a == winner_b
    assert count_a == count_b
    assert hash_a == hash_b
    assert winner_a in {"p1", "p2"}
