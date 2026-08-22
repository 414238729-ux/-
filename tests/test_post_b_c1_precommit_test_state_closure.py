# -*- coding: utf-8 -*-
"""POST_B_C1_PRECOMMIT_TEST_STATE_CLOSURE：冻结 R8 证据与当前 C1 身份的边界。

把“预期身份分歧”从 pytest failure 修正为显式的安全测试语义：

- 冻结 Milestone B R8 acceptance artifact 是历史证据，不是 current
  certification；
- 其规则/牌堆身份与结构完整性仍必须通过；
- 其 implementation identity 仍是 R8 值（不得改写）；
- 当前 C1 implementation identity 已变，二者必须不匹配；
- current gate 对 stale artifact 必须拒绝（valid=False、0 seeds、
  不构成 fixed-seed 认证），且绝不产生 simulation_executed；
- fresh C1 live execution 不依赖旧 artifact（MB-B-001 静态执行资格）。

本文件不改任何生产代码、不改冻结 artifact/manifest 历史事实。
"""

from __future__ import annotations

import json
from pathlib import Path

import scripts.sgs_engine.formal_duel as formal_duel_module
import scripts.sgs_formal_runner as formal_runner

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_ACCEPTANCE_ARTIFACT_PATH = (
    REPOSITORY_ROOT / "docs" / "FORMAL_MILESTONE_B_100_SEED_ACCEPTANCE.json"
)

FROZEN_R8_IMPLEMENTATION_IDENTITY = (
    "06c8b2d3ead9adb52a18252e398eae137eb8fb51f657909051500893672b0e33"
)
# 当前 post-B 实现身份：随 post-B 轨道（C1→C6）更新；冻结 R8 值永不变。
POST_B_CURRENT_IMPLEMENTATION_IDENTITY = (
    "b6a312c06ea176ea5f66ad4c1dd4131b74ff56ca14dbc114ceceec25ed9a87f3"
)
FROZEN_R8_RULES_PROFILE_IDENTITY = (
    "9a7b0e9f45c05292a207c500e5b024a77d97b4a6c9446230d81d357c7b514283"
)
FROZEN_R8_DECK_IDENTITY = (
    "e490631698e6b7695c6a9b3ad0c355e421ccfafab696e5b3a97418c9ec80f38b"
)


def _load_artifact_payload() -> dict[str, object]:
    payload = json.loads(_ACCEPTANCE_ARTIFACT_PATH.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


# ----------------------------------------------------------------------
# 1. 冻结 R8 artifact 身份 != 当前 post-B 实现身份
# ----------------------------------------------------------------------


def test_frozen_r8_artifact_identity_differs_from_c1_current_identity() -> None:
    artifact = _load_artifact_payload()
    assert (
        artifact["implementation_identity"]
        == FROZEN_R8_IMPLEMENTATION_IDENTITY
    )
    current_identity = formal_duel_module.implementation_identity()
    assert current_identity == POST_B_CURRENT_IMPLEMENTATION_IDENTITY
    assert current_identity != artifact["implementation_identity"]


# ----------------------------------------------------------------------
# 2. artifact 可解析且关键结构完整
# ----------------------------------------------------------------------


def test_frozen_r8_artifact_is_parseable_and_structurally_complete() -> None:
    artifact = _load_artifact_payload()
    assert artifact["schema"] == "FORMAL_MILESTONE_B_100_SEED_ACCEPTANCE_v2"
    assert artifact["mode"] == "formal_160_card_no_skill_duel"
    assert artifact["passed"] is True
    assert artifact["analysis_only"] is False
    assert artifact["max_steps"] == 2000
    assert tuple(artifact["seeds"]) == tuple(range(100))
    assert artifact["seed_count"] == 100
    assert artifact["natural_end_count"] == 100
    assert artifact["reexecution_verified_count"] == 100
    assert artifact["failure_count"] == 0
    assert artifact["failures"] == []
    assert isinstance(artifact["canonical_formal_profile"], dict)
    details = artifact["seeds_detail"]
    assert isinstance(details, list) and len(details) == 100
    for index, item in enumerate(details):
        assert isinstance(item, dict)
        assert item["seed"] == index
        assert item["winner"] in {"p1", "p2"}
        assert item["natural_end"] is True
        assert item["passed"] is True
        assert item["strict_reexecution"] is True
        assert (
            isinstance(item["final_state_hash"], str)
            and len(item["final_state_hash"]) == 64
        )


# ----------------------------------------------------------------------
# 3. 历史 artifact 完整性仍通过（规则/牌堆身份与历史终局记录未变）
# ----------------------------------------------------------------------


def test_historical_artifact_integrity_still_passes() -> None:
    artifact = _load_artifact_payload()
    # C1 只改了实现源码：规则 profile 与牌堆身份必须仍与冻结值一致。
    assert (
        formal_duel_module.rules_profile_identity()
        == FROZEN_R8_RULES_PROFILE_IDENTITY
        == artifact["rules_profile_identity"]
    )
    assert (
        formal_duel_module.deck_identity()
        == FROZEN_R8_DECK_IDENTITY
        == artifact["deck_identity"]
    )
    assert (
        artifact["implementation_identity"]
        == FROZEN_R8_IMPLEMENTATION_IDENTITY
    )
    # 历史终局记录逐项保持（与 R5 记录对照）：seed 0 → p2/388/43；
    # seed 7 → p2/162/17。
    details = {item["seed"]: item for item in artifact["seeds_detail"]}
    assert details[0]["winner"] == "p2"
    assert details[0]["action_count"] == 388
    assert details[0]["turn_count"] == 43
    assert details[7]["winner"] == "p2"
    assert details[7]["action_count"] == 162
    assert details[7]["turn_count"] == 17


# ----------------------------------------------------------------------
# 4. current gate 拒绝 stale artifact
# ----------------------------------------------------------------------


def test_current_gate_rejects_stale_artifact() -> None:
    valid, results = formal_duel_module._load_acceptance_evidence()
    assert valid is False
    assert results == ()
    readiness = formal_duel_module.inspect_formal_duel_readiness()
    assert readiness.cached_acceptance_report_valid is False
    assert readiness.cached_acceptance_seed_count == 0
    assert readiness.acceptance_seed_count == 0
    assert readiness.acceptance_natural_end_count == 0
    assert readiness.fixed_seed_acceptance_passed is False
    assert readiness.cached_fixed_seed_acceptance_passed is False
    assert len(readiness.acceptance_seed_results) == 0


# ----------------------------------------------------------------------
# 5. stale artifact 不能产生 simulation_executed / current certification
# ----------------------------------------------------------------------


def test_stale_artifact_cannot_produce_simulation_executed_or_certification() -> None:
    status = formal_runner.build_current_status(
        mode_name="formal_160_card_no_skill_duel"
    )
    assert status["simulation_executed"] is False
    formal_duel_status = status["formal_duel"]
    assert formal_duel_status["cached_acceptance_report_valid"] is False
    assert formal_duel_status["cached_acceptance_seed_count"] == 0
    assert formal_duel_status["acceptance_seed_count"] == 0
    assert formal_duel_status["fixed_seed_acceptance_passed"] is False
    assert formal_duel_status["cached_fixed_seed_acceptance_passed"] is False
    # 静态执行资格与缓存分离：stale 不影响执行资格，但也绝不构成认证。
    assert formal_duel_status["formal_duel_execution_ready"] is True


# ----------------------------------------------------------------------
# 6. fresh C1 live execution 不依赖旧 artifact 即可运行
# ----------------------------------------------------------------------


def test_fresh_c1_live_execution_does_not_depend_on_stale_artifact() -> None:
    # 前置：artifact 此刻 stale，静态执行资格仍成立（MB-B-001）。
    readiness = formal_duel_module.inspect_formal_duel_readiness()
    assert readiness.cached_acceptance_report_valid is False
    assert readiness.formal_duel_execution_ready is True
    # 真实 live execution：不经缓存证据，直接运行 seed 0 并严格重执行。
    results = formal_duel_module.run_formal_duel_seed_sweep(
        (0,),
        configuration=(
            formal_duel_module.FormalDuelConfiguration.formal_profile()
        ),
        analysis_only=False,
        max_steps=2000,
    )
    assert len(results) == 1
    result = results[0]
    assert result.natural_end is True
    assert result.reexecution_verified is True
    assert result.formal_result_eligible is True
    # C1 生产行为与 R5/R8 记录一致：seed 0 → p2 胜、388 动作、43 回合。
    assert result.winner == "p2"
    assert result.action_count == 388
    assert result.turn_count == 43
