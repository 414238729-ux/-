"""记录真实命令、PID、exit code与前后源码；long仅由外部执行交接启动。"""
from __future__ import annotations

import argparse
import ast
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

from .sgs_engine.playable_simulator import REPO_ROOT, source_identity

SHORT_TARGETS = [
    "tests/test_post_c8_playable_config.py", "tests/test_post_c8_playable_runtime.py",
    "tests/test_post_c8_production_ai.py", "tests/test_post_c8_playable_cli.py",
    "tests/test_post_c8_playable_simulator.py",
    "tests/test_post_c8_information.py", "tests/test_sgs_team_strategy.py",
    "tests/test_post_c8_round1_remediation.py",
    "tests/test_sgs_production_borrowed_sword_weapon_system.py::test_second_target_has_no_independent_wuxie_window",
    "tests/test_sgs_production_borrowed_sword_weapon_system.py::test_second_target_can_still_wuxie_first_target_effect",
    "tests/test_authoritative_zhugezhan_production_v1.py::test_zuilun_positive_private_top_three_selection",
    "tests/test_authoritative_zhugezhan_production_v1.py::test_fuyin_first_slash_or_duel_ineffective",
    "tests/test_authoritative_zhugezhan_production_v1.py::test_fuyin_jili_activate_then_target_effect_checkpoint",
    "tests/test_authoritative_wangyuanji_production_v1.py::test_qianchong_all_black_grants_weimu_and_filters_black_tricks",
    "tests/test_authoritative_wangyuanji_production_v1.py::test_qianchong_all_red_grants_mingzhe_and_triggers_on_red_loss",
    "tests/test_authoritative_wangyuanji_production_v1.py::test_qianchong_play_phase_start_choice_basic_bypasses_slash_limits_and_distance",
    "tests/test_authoritative_wangyuanji_production_v1.py::test_shangjian_loss_ledger_draws_exact_losses_if_le_hp",
    "tests/test_authoritative_wangyuanji_production_v1.py::test_shangjian_loss_ledger_draws_zero_if_losses_exceed_hp",
]


def save(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def utc():
    return datetime.now(timezone.utc).isoformat()


def snapshot():
    files = dict(source_identity()["files"])
    for folder in ("tests", "examples/post_c8"):
        for path in sorted((REPO_ROOT / folder).rglob("*")):
            if path.is_file() and path.suffix in (".py", ".json"):
                files[path.relative_to(REPO_ROOT).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    git = ["git", "-c", f"safe.directory={REPO_ROOT.as_posix()}"]
    facts = {}
    for label, args in (("branch", ["branch", "--show-current"]), ("head", ["rev-parse", "HEAD"]),
                        ("frozen_tag_commit", ["rev-parse", "c8-timed-8p-deterministic-virtual-time-v1-audited^{}"]),
                        ("tracked_changes", ["diff", "--name-only", "HEAD"]), ("status", ["status", "--short"])):
        r = subprocess.run(git + args, cwd=REPO_ROOT, text=True, encoding="utf-8", capture_output=True)
        facts[label] = {"exit_code": r.returncode, "output": r.stdout.strip(), "stderr": r.stderr.strip()}
    return {"time": utc(), "source": source_identity(), "test_and_source_files": files, "git": facts,
            "python": sys.executable, "version": sys.version, "parent_pid": os.getpid()}


def run_recorded(command, root: Path, name: str) -> dict:
    record = {"name": name, "command": command, "cwd": str(REPO_ROOT), "started": utc(),
              "stdout_stderr": str(root / (name + ".log")), "state": "STARTING"}
    path = root / (name + ".json")
    save(path, record)
    start = time.perf_counter()
    try:
        with (root / (name + ".log")).open("x", encoding="utf-8") as log:
            process = subprocess.Popen(command, cwd=REPO_ROOT, stdout=log, stderr=subprocess.STDOUT,
                env={**os.environ, "PYTHONHASHSEED": "0", "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUTF8": "1"})
            record.update(pid=process.pid, state="RUNNING")
            save(path, record)
            print(json.dumps({"name": name, "pid": process.pid, "log": record["stdout_stderr"]}), flush=True)
            try:
                exit_code = process.wait()
            except KeyboardInterrupt:
                process.terminate()
                exit_code = process.wait()
                record["interrupted"] = True
            record.update(exit_code=exit_code, state="EXITED")
    except OSError as exc:
        record.update(state="LAUNCH_ERROR", exit_code=None, error=str(exc))
    record.update(ended=utc(), elapsed_seconds=time.perf_counter() - start)
    log_text = (root / (name + ".log")).read_text(encoding="utf-8", errors="replace") if (root / (name + ".log")).exists() else ""
    summary = re.findall(r"\b\d+ (?:passed|failed|skipped|errors?|xfailed|xpassed)\b", log_text[-5000:])
    record["pytest_summary_tokens"] = summary
    save(path, record)
    print(json.dumps({"name": name, "exit_code": record.get("exit_code"), "summary": summary}), flush=True)
    return record


def audit_bundle(root):
    paths = sorted((REPO_ROOT / "scripts/sgs_engine").glob("playable_*.py")) + [
        REPO_ROOT / "scripts/sgs_engine/production_ai.py", REPO_ROOT / "scripts/sgs_playable.py",
        REPO_ROOT / "scripts/sgs_engine/actions.py", REPO_ROOT / "scripts/sgs_engine/generals.py"]
    paths += sorted((REPO_ROOT / "tests").glob("test_post_c8*.py"))
    paths += [REPO_ROOT / "knowledge/三国杀模式规则.md", REPO_ROOT / "knowledge/三国杀AI信息规则.md",
              REPO_ROOT / "docs/POST_C8_PLAYABLE_GAP_MATRIX.md"]
    chunks = ["""你是独立只读代码审查者。请用中文审查本次 POST_C8 可玩runtime/启发式AI/多进程模拟。
用户授权使用本机Grok，只发送下列必要代码与规则。禁止调用工具、读取其他文件、修改文件或发送消息。
检查生产合法动作签名链、current_actor、多步决策/重复/过期、模式开局和胜负接线、玩家与AI信息边界
（2v2队友共享手牌合法；真实无懈窗口提供全场公开资格；农民问答是全场公开的具体YES/NO/NO_RESPONSE，
不得自动共享杀数/桃状态或把保护建议解码为私牌事实）、策略函数真正使用、spawn确定性、统计分母。
发现问题要给文件和行、可复现触发条件、影响、具体修复建议；不要用未证实的猜想宣称漏洞。
区分缺陷、建议、资料不足；最后给 BLOCKING_FINDINGS 或 NO_BLOCKING_FINDINGS_IN_REVIEWED_SCOPE。
长测/full pytest/完整模式矩阵尚未执行，本次仅为长测前代码审查，不能声称最终验收或外部测试通过。
下列文件有完整当前字节及SHA。production_batch只提供关键方法摘录（注明行号），其他引擎部分不在此次可核查范围。
Windows spawn两局和单进程逐局语义/最终状态/统计比较已在开发短测通过。
请据代码判断，测试概述不代替实际结果；长测和最终字节审查均仍待完成。"""]
    for evidence in sorted((REPO_ROOT / "docs/post_c8_evidence").glob("short_*/execution_summary.json")):
        chunks.append("\nACTUAL_SHORT_TEST_RECORD " + evidence.read_text(encoding="utf-8"))
        log = evidence.parent / "pytest.log"
        if log.exists():
            chunks.append("\nACTUAL_SHORT_TEST_LOG\n" + log.read_text(encoding="utf-8")[-10000:])
    for evidence in sorted((REPO_ROOT / "docs/post_c8_evidence").glob("information_short_*/execution_summary.json")):
        chunks.append("\nACTUAL_INFORMATION_SHORT_TEST_RECORD " + evidence.read_text(encoding="utf-8"))
        log = evidence.parent / "pytest.log"
        if log.exists():
            chunks.append("\nACTUAL_INFORMATION_SHORT_TEST_LOG\n" + log.read_text(encoding="utf-8")[-10000:])
    for path in paths:
        content = path.read_text(encoding="utf-8")
        chunks.append(f"\nFILE {path.relative_to(REPO_ROOT).as_posix()} SHA256 {hashlib.sha256(path.read_bytes()).hexdigest()}\n" +
                      "\n".join(f"{i}: {line}" for i, line in enumerate(content.splitlines(), 1)))
    selections = {
        "scripts/sgs_engine/production_batch.py": {"__init__", "step", "legal_actions", "current_actor_id", "_commit_runtime"},
        "scripts/sgs_ai_strategy_v22.py": {"DynamicCardValue", "StrategyAction", "choose_v22_action", "evaluate_shamoke_weapon_swap"},
        "scripts/sgs_team_strategy.py": {"RescueResource", "plan_team_rescue", "evaluate_nullification_decision",
            "NullificationAvailability", "NullificationPlayerKnowledge", "NullificationKnowledgeState"},
        "scripts/sgs_engine/production_cards.py": {"WuxiekejiAdapter"},
    }
    for filename, names in selections.items():
        text = (REPO_ROOT / filename).read_text(encoding="utf-8-sig")
        lines = text.splitlines()
        tree = ast.parse(text)
        for node in ast.walk(tree):
            if isinstance(node, (ast.ClassDef, ast.FunctionDef)) and node.name in names:
                if filename.endswith("production_batch.py") and node.name == "__init__" and node.lineno < 3200:
                    continue
                chunks.append(f"\nEXCERPT {filename}:{node.lineno}\n" + "\n".join(
                    f"{i+1}: {lines[i]}" for i in range(node.lineno-1, node.end_lineno)))
    prompt = root / "audit_input.txt"
    prompt.write_text("\n".join(chunks), encoding="utf-8")
    save(root / "audit_input_hash.json", {"sha256": hashlib.sha256(prompt.read_bytes()).hexdigest(), "bytes": prompt.stat().st_size})
    return prompt


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("kind", choices=("short", "long", "grok"))
    p.add_argument("--out", required=True, help="全新证据目录，拒绝覆盖历史运行")
    p.add_argument("--basetemp", default="D:/t/pc8")
    p.add_argument("--grok", default="C:/Users/ASUS/.grok/bin/grok.exe")
    args = p.parse_args(argv)
    root = Path(args.out).resolve()
    root.mkdir(parents=True, exist_ok=False)
    before = snapshot()
    save(root / "before.json", before)
    records = []
    if args.kind == "grok":
        prompt = audit_bundle(root)
        records.append(run_recorded([args.grok, "--prompt-file", str(prompt), "--output-format", "plain",
            "--tools", "", "--no-subagents", "--disable-web-search", "--verbatim", "--max-turns", "1",
            "--permission-mode", "plan"], root, "grok"))
    else:
        Path(args.basetemp).resolve().parent.mkdir(parents=True, exist_ok=True)
        targets = SHORT_TARGETS if args.kind == "short" else []
        records.append(run_recorded([sys.executable, "-B", "-m", "pytest", "-q", *targets,
            "-p", "no:cacheprovider", "--basetemp", str(Path(args.basetemp).resolve()),
            "--junitxml", str(root / "pytest.xml")], root, "pytest"))
        # 冻结合约测试的真实子进程报告随本轮证据保存，不依赖临时目录永久存在。
        frozen_evidence = Path(args.basetemp).resolve() / "fc8e"
        if frozen_evidence.is_dir():
            shutil.copytree(frozen_evidence, root / "frozen_test_evidence", ignore=shutil.ignore_patterns("bt"))
        if args.kind == "long" and not records[-1].get("interrupted"):
            # 一个完整外部矩阵，实施阶段不拆分偷跑。全模式×固定/候选×4seeds×1/4workers。
            from .sgs_engine.playable_config import MODE_SEATS
            stop = False
            for mode in MODE_SEATS:
                if stop:
                    break
                for selection in ("fixed", "candidates"):
                    name = f"{mode}_{selection}"
                    config = {"game": {"mode": mode, "control": "AI_VS_AI", "selection": selection,
                        "ai_seed": 10, "mulligan": True, "max_steps": 20000},
                        "games": 4, "seeds": [0, 1, 2, 3], "workers": 4}
                    cfg_path = root / (name + "_config.json")
                    save(cfg_path, config)
                    if snapshot()["test_and_source_files"] != before["test_and_source_files"]:
                        records.append({"name": name, "state": "SKIPPED_SOURCE_DRIFT", "exit_code": None})
                        stop = True
                        break
                    records.append(run_recorded([sys.executable, "-B", "-m", "scripts.sgs_playable", "compare-workers",
                        "--config", str(cfg_path), "--output", str(root / (name + "_result.json"))], root, name))
                    if records[-1].get("interrupted"):
                        stop = True
                        break
    after = snapshot()
    save(root / "after.json", after)
    unchanged = before["test_and_source_files"] == after["test_and_source_files"]
    save(root / "execution_summary.json", {"kind": args.kind, "records": records,
        "source_and_tests_unchanged": unchanged, "source_sha256": before["source"]["sha256"],
        "long_tests_attempted": args.kind == "long", "independent_final_audit": "PENDING"})
    return 0 if unchanged and all(r.get("exit_code") == 0 for r in records) else 1


if __name__ == "__main__":
    raise SystemExit(main())
