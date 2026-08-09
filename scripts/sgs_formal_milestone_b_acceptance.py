# -*- coding: utf-8 -*-
"""FORMAL_MILESTONE_B_100_SEED_ACCEPTANCE（正式验收，非 analysis）。

以项目 canonical formal profile（USER_CONFIRMED_PROJECT_FORMAL_PROFILE，
2026-08-09）在固定 seeds 0..99 上逐个执行正式无技能单挑，每局要求：

- deck_count=160、unsupported_rules=0、approximation_count=0；
- mode_implemented=true、duel-scope all_cards sufficient；
- 使用唯一正式 runner（FormalNoSkillDuelSession＋FormalDuelReferenceController）；
- 自然结束、safety-cap 未触发、winner 明确（p1/p2）；
- strict rule reexecution 通过、replay final hash 一致、RNG consumption 一致；
- 任何 UnsupportedRuleError／InvalidAction／exception／safety-cap／reexecution
  mismatch／privacy invariant failure／card conservation failure 均判该 seed
  失败，不得跳过、排除或重采样。

输出独立正式 acceptance artifact（JSON），逐 seed 记录 seed／winner／
action_count／reshuffle_count／unsupported_rules／approximation_count／
strict_reexecution／final_state_hash。该 artifact 是正式验收证据，不是
analysis-only 诊断；旧 MILESTONE_B_ANALYSIS_SEED_DIAGNOSTIC 保持原状。

用法：
    python scripts/sgs_formal_milestone_b_acceptance.py [输出路径]
"""

from __future__ import annotations

import io
import json
import os
import sys
import time
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.sgs_engine.formal_duel import (
    FormalDuelConfiguration,
    inspect_formal_duel_readiness,
    run_formal_duel_seed_sweep,
)


def _seed_ok(result: object) -> tuple[bool, str]:
    required = (
        result.natural_end
        and result.formal_result_eligible
        and result.reexecution_verified
        and result.winner in {"p1", "p2"}
        and result.deck_count == 160
        and result.unsupported_rules == 0
        and result.approximation_count == 0
        and not result.safety_cap_triggered
        and result.exception_type is None
        and isinstance(result.final_state_hash, str)
        and result.final_state_hash
    )
    if required:
        return True, ""
    problems = []
    if not result.natural_end:
        problems.append("not_natural_end")
    if not result.formal_result_eligible:
        problems.append("formal_result_not_eligible")
    if not result.reexecution_verified:
        problems.append("reexecution_not_verified")
    if result.winner not in {"p1", "p2"}:
        problems.append("winner_missing")
    if result.deck_count != 160:
        problems.append("deck_count")
    if result.unsupported_rules != 0:
        problems.append("unsupported_rules")
    if result.approximation_count != 0:
        problems.append("approximation_count")
    if result.safety_cap_triggered:
        problems.append("safety_cap")
    if result.exception_type is not None:
        problems.append(f"exception:{result.exception_type}")
    if not isinstance(result.final_state_hash, str) or not result.final_state_hash:
        problems.append("final_state_hash_missing")
    return False, ",".join(problems)


def main(argv: list[str]) -> int:
    output_path = (
        Path(argv[0])
        if argv
        else Path("docs") / "FORMAL_MILESTONE_B_100_SEED_ACCEPTANCE.json"
    )
    profile = FormalDuelConfiguration.formal_profile()
    if not profile.source_confirmed:
        print("正式 profile 未确认；拒绝运行", file=sys.stderr)
        return 2
    started = time.time()
    results = run_formal_duel_seed_sweep(
        range(100),
        configuration=profile,
        analysis_only=False,
        max_steps=2000,
    )
    elapsed = time.time() - started
    seed_records: list[dict[str, object]] = []
    failures: list[dict[str, object]] = []
    for result in results:
        ok, reason = _seed_ok(result)
        record = {
            "seed": result.seed,
            "winner": result.winner,
            "action_count": result.action_count,
            "turn_count": result.turn_count,
            "reshuffle_count": result.reshuffle_count,
            "unsupported_rules": result.unsupported_rules,
            "approximation_count": result.approximation_count,
            "strict_reexecution": result.reexecution_verified,
            "final_state_hash": result.final_state_hash,
            "natural_end": result.natural_end,
            "passed": ok,
        }
        seed_records.append(record)
        if not ok:
            failures.append({"seed": result.seed, "reason": reason})

    readiness = inspect_formal_duel_readiness()
    artifact: dict[str, object] = {
        "schema": "FORMAL_MILESTONE_B_100_SEED_ACCEPTANCE_v1",
        "rule_source": "USER_CONFIRMED_PROJECT_FORMAL_PROFILE（2026-08-09）",
        "mode": "formal_160_card_no_skill_duel",
        "seeds": list(range(100)),
        "seed_count": len(seed_records),
        "natural_end_count": sum(
            1 for r in results if r.natural_end
        ),
        "reexecution_verified_count": sum(
            1 for r in results if r.reexecution_verified
        ),
        "failure_count": len(failures),
        "passed": len(failures) == 0 and len(seed_records) == 100,
        "elapsed_seconds": round(elapsed, 2),
        "live_readiness": readiness.to_dict(),
        "seeds_detail": seed_records,
        "failures": failures,
        "note": (
            "正式100-seed验收证据；与 analysis-only 诊断"
            "（MILESTONE_B_ANALYSIS_SEED_DIAGNOSTIC）分离。"
        ),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with io.open(
        str(output_path), "w", encoding="utf-8", newline="\n"
    ) as handle:
        json.dump(artifact, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print(
        "ACCEPTANCE %s: %d/%d seeds passed, failures=%d, %.1fs"
        % (
            "PASSED" if artifact["passed"] else "FAILED",
            len(seed_records) - len(failures),
            len(seed_records),
            len(failures),
            elapsed,
        )
    )
    for failure in failures:
        print("  seed %s: %s" % (failure["seed"], failure["reason"]))
    print("artifact:", output_path)
    return 0 if artifact["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
