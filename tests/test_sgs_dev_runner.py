from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def _run(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "scripts.sgs_dev_runner", *arguments],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
    )


def _success_payload(result: subprocess.CompletedProcess[str]) -> dict[str, object]:
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    return payload


def test_duel_smoke_command_outputs_stable_test_only_summary() -> None:
    result = _run("duel-smoke", "--seed", "20260801", "--max-steps", "300")
    payload = _success_payload(result)

    assert payload["command"] == "duel-smoke"
    assert payload["test_only"] is True
    assert payload["formal_result"] is False
    assert payload["mode_id"] == "test_only_duel_vertical_slice"
    assert payload["winner"] in {"p1", "p2"}
    assert payload["steps"] > 0
    assert payload["turns"] > 0
    assert payload["event_count"] > 0
    assert payload["random_consumption_count"] > 0
    assert len(payload["final_hash"]) == 64
    assert payload["reexecution_replay_supported"] is True
    assert payload["unsupported_rules"] == 0
    assert payload["approximation_count"] == 0
    assert payload["safety_step_limit"] == 300
    assert "win_rate" not in payload
    assert "胜率" not in result.stdout


def test_duel_smoke_can_save_and_strictly_reexecute_replay(tmp_path: Path) -> None:
    replay_path = tmp_path / "duel-replay.json"
    smoke = _run(
        "duel-smoke",
        "--seed",
        "20260801",
        "--max-steps",
        "300",
        "--save-replay",
        str(replay_path),
    )
    smoke_payload = _success_payload(smoke)
    assert replay_path.is_file()

    replay = _run("replay", str(replay_path))
    replay_payload = _success_payload(replay)
    assert replay_payload["verified"] is True
    assert replay_payload["test_only"] is True
    assert replay_payload["formal_result"] is False
    assert replay_payload["reexecution_replay_supported"] is True
    for key in (
        "mode_id",
        "winner",
        "steps",
        "turns",
        "decision_count",
        "event_count",
        "random_consumption_count",
        "final_hash",
        "final_execution_hash",
        "final_game_state_hash",
        "record_sha256",
        "unsupported_rules",
        "approximation_count",
        "safety_step_limit",
    ):
        assert replay_payload[key] == smoke_payload[key]


def test_cli_never_labels_vertical_slice_as_formal_result() -> None:
    payload = _success_payload(_run("duel-smoke", "--seed", "20260801"))

    assert payload == {
        **payload,
        "test_only": True,
        "formal_result": False,
        "reexecution_replay_supported": True,
        "unsupported_rules": 0,
        "approximation_count": 0,
        "safety_step_limit": 500,
    }
    assert not any("rate" in key.lower() for key in payload)


def test_replay_rejects_invalid_json_without_fabricating_result(tmp_path: Path) -> None:
    invalid = tmp_path / "invalid.json"
    invalid.write_text("{不是合法 JSON", encoding="utf-8")

    result = _run("replay", str(invalid))

    assert result.returncode != 0
    assert result.stdout == ""
    payload = json.loads(result.stderr)
    assert payload["ok"] is False
    assert payload["test_only"] is True
    assert payload["formal_result"] is False
    assert "winner" not in payload
    assert "verified" not in payload


def test_replay_rejects_tampered_record_hash(tmp_path: Path) -> None:
    replay_path = tmp_path / "duel-replay.json"
    _success_payload(
        _run(
            "duel-smoke",
            "--seed",
            "20260801",
            "--max-steps",
            "300",
            "--save-replay",
            str(replay_path),
        )
    )
    document = json.loads(replay_path.read_text(encoding="utf-8"))
    assert isinstance(document["record_sha256"], str)
    document["record_sha256"] = "0" * 64
    replay_path.write_text(
        json.dumps(document, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )

    result = _run("replay", str(replay_path))

    assert result.returncode != 0
    assert result.stdout == ""
    payload = json.loads(result.stderr)
    assert payload["ok"] is False
    assert payload["formal_result"] is False
    assert "winner" not in payload
    assert "verified" not in payload
