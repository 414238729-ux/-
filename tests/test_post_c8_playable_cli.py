import json
from pathlib import Path
import subprocess
import sys

from scripts.sgs_playable import run_interactive, main
from scripts.sgs_engine.playable_config import GameConfig


def test_interactive_menu_submits_and_explicit_exit_is_abort():
    answers = iter(["wrong", "1", "v", "1", "q"])
    output = []
    result = run_interactive(GameConfig(control="ALL_HUMAN", enabled_generals=("soldier",), mulligan=False),
        input_fn=lambda prompt: next(answers), output=output.append)
    assert result["status"] == "ABORTED" and result["steps"] == 2
    assert any("请输入列表" in line for line in output)
    assert any("1." in line for line in output)


def test_actual_cli_process_and_nonzero_abort_exit():
    p = subprocess.run([sys.executable, "-B", "-m", "scripts.sgs_playable", "play",
        "--mode", "2v2", "--control", "ALL_HUMAN"], input="1\nq\n", text=True,
        encoding="utf-8", capture_output=True, timeout=20)
    assert p.returncode == 2, p.stderr
    assert "ABORTED" in p.stdout and "请选择" in p.stdout


def test_cli_invalid_configuration_is_clear_error(capsys):
    assert main(["play", "--control", "HUMAN_VS_AI", "--human-seats", "9"]) == 2
    assert "座位" in capsys.readouterr().err


def test_evidence_runner_records_actual_nonzero_child_exit(tmp_path):
    from scripts.post_c8_validation import run_recorded
    result = run_recorded([sys.executable, "-B", "-c", "raise SystemExit(7)"], tmp_path, "negative_exit")
    assert result["exit_code"] == 7 and result["pid"] > 0 and result["state"] == "EXITED"
    persisted = json.loads((tmp_path / "negative_exit.json").read_text(encoding="utf-8"))
    assert persisted["exit_code"] == 7 and persisted["pytest_summary_tokens"] == []
