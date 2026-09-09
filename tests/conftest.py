"""POST-C8 测试身份边界：明确冻结的 C8 合约测试在原冻结源码子进程执行。

不修改原 verifier、不把 current bytes 伪装成旧 hash。子进程运行原 nodeid 的
原测试字节，父进程转发 pytest 实际 setup/call/teardown 报告，不生成预期 PASS。
新 production、信息模型及技能测试仍在当前开发树运行。
"""
from pathlib import Path
import json
import os
import subprocess
import sys
import time

import pytest
from _pytest.reports import TestReport

FROZEN_COMMIT = "9991abc8091943e7316875734bae2e5967cc6e64"
FROZEN_MODULES = {"test_c8_baseline_launcher_v1.py", "test_c8_bounded_timed_8p_trace_v1.py"}
ORDER_TESTS = {
    "test_step1362_g1_non_decline_eligibility_and_profile_migration",
    "test_w592_certificate_constructs_new_driver_and_rejects_old_profile",
    "test_v3_gate_two_fresh_processes_agree_on_public_order",
    "test_v3_gate_diagnostic_50_rows_atomic_private_separation_and_no_resume",
    "test_v3_gate_io_retries_exact_bytes_once_and_does_not_advance_gameplay",
    "test_v3_gate_diagnostic_snapshot_strict_rehashed_envelope",
    "test_v3_gate_failed_accepted_evidence_tail_keeps_unknown_metrics_explicit",
    "test_v3_gate_private_write_before_pointer_and_unwritable_tail_is_truthful",
}


def frozen_item(item):
    filename = Path(str(item.path)).name
    return filename in FROZEN_MODULES or (
        filename == "test_c8_timed_8p_full_game_runner_v1.py"
        and item.originalname in ORDER_TESTS)


def pytest_collection_modifyitems(config, items):
    config._post_c8_frozen_nodes = [item.nodeid for item in items if frozen_item(item)]


def _execute_frozen_tests(config):
    root = Path(__file__).resolve().parents[1]
    base = config._tmp_path_factory.getbasetemp()
    evidence = base / "fc8e"
    evidence.mkdir(exist_ok=False)
    request = evidence / "request.json"
    request.write_text(json.dumps({"repo": str(root), "commit": FROZEN_COMMIT,
        "frozen_root": str(base / "fc8"), "evidence": str(evidence),
        "nodeids": config._post_c8_frozen_nodes}), encoding="utf-8")
    command = [sys.executable, "-B", str(root / "tests/post_c8_frozen_source.py"), str(request)]
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONHASHSEED": "0", "PYTHONUTF8": "1"}
    started = time.time()
    with (evidence / "pytest.log").open("wb") as log:
        process = subprocess.Popen(command, cwd=root, env=env, stdout=log, stderr=subprocess.STDOUT)
        record = {"command": command, "pid": process.pid, "started": started, "exit_code": None}
        (evidence / "process.json").write_text(json.dumps(record), encoding="utf-8")
        code = process.wait()
    record.update(exit_code=code, duration=time.time()-started)
    (evidence / "process.json").write_text(json.dumps(record), encoding="utf-8")
    reports = {}
    path = evidence / "reports.jsonl"
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            raw = json.loads(line)
            reports.setdefault(raw["nodeid"], []).append(raw)
    verified = evidence / "source_verified.json"
    verification = json.loads(verified.read_text(encoding="utf-8")) if verified.exists() else {}
    if (code not in (0, 1) or verification.get("pytest_exit_code") != code
            or not verification.get("before_after_equal")):
        reports = {}  # 无完整源核验不得转发 passing reports。
    for nodeid, phases in list(reports.items()):
        kinds = [report["when"] for report in phases]
        setup = next((report for report in phases if report["when"] == "setup"), None)
        required = ["setup", "call", "teardown"] if setup and setup["outcome"] == "passed" else ["setup", "teardown"]
        if kinds != required:
            del reports[nodeid]  # 子进程未完成该测试的生命周期不能充当通过。
    return reports, record, evidence


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_protocol(item, nextitem):
    if not frozen_item(item):
        return None
    config = item.config
    if not hasattr(config, "_post_c8_frozen_run"):
        config._post_c8_frozen_run = _execute_frozen_tests(config)
    reports, record, evidence = config._post_c8_frozen_run
    raw_reports = reports.get(item.nodeid, [])
    item.ihook.pytest_runtest_logstart(nodeid=item.nodeid, location=item.location)
    if not any(r["when"] == "call" for r in raw_reports):
        # 真正的 fixture/子进程错误：绝不把未执行的原测试报成通过。
        if not raw_reports:
            raw_reports = [TestReport(nodeid=item.nodeid, location=item.location,
                keywords={}, outcome="failed", longrepr=f"冻结测试未完成：{record}；日志 {evidence / 'pytest.log'}",
                when="setup")._to_json()]
    for raw in raw_reports:
        report = TestReport._from_json(raw)
        report.user_properties.append(("execution_source", "FROZEN_C8:" + FROZEN_COMMIT))
        item.ihook.pytest_runtest_logreport(report=report)
    item.ihook.pytest_runtest_logfinish(nodeid=item.nodeid, location=item.location)
    return True
