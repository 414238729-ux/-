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

import sys
import time
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.sgs_engine.formal_duel import (
    FormalDuelConfiguration,
    run_formal_duel_seed_sweep,
    write_formal_acceptance_artifact,
)


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
    try:
        written = write_formal_acceptance_artifact(
            results, output_path, elapsed_seconds=elapsed
        )
    except Exception as exc:
        print(
            "ACCEPTANCE FAILED: artifact 写出被拒绝："
            f"{type(exc).__name__}:{exc}",
            file=sys.stderr,
        )
        return 1
    failures = [
        item
        for item in results
        if not (
            item.natural_end
            and item.formal_result_eligible
            and item.reexecution_verified
            and item.winner in {"p1", "p2"}
            and item.deck_count == 160
            and item.unsupported_rules == 0
            and item.approximation_count == 0
            and not item.safety_cap_triggered
            and item.exception_type is None
        )
    ]
    passed = len(results) == 100 and not failures
    print(
        "ACCEPTANCE %s: %d/%d seeds passed, failures=%d, %.1fs"
        % (
            "PASSED" if passed else "FAILED",
            len(results) - len(failures),
            len(results),
            len(failures),
            elapsed,
        )
    )
    for item in failures:
        print("  seed %s: 不合格" % (item.seed,))
    print("artifact:", written)
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
