from __future__ import annotations

import json

import pytest

from scripts.sgs_engine.duel import TestOnlyDuelGame
from scripts.sgs_engine.duel_replay import (
    REEXECUTION_SCHEMA,
    DuelReplayFormatError,
    DuelReexecutionReplay,
    ReplayDivergenceError,
    _build_event_hash_chain,
    record_reference_duel,
    reexecute_duel_replay,
)
from scripts.sgs_engine.replay import sha256_value


def _record(seed: int = 3) -> DuelReexecutionReplay:
    # 1/1体力只缩短测试耗时，不绕过任何真实阶段、响应、伤害或死亡路径。
    return record_reference_duel(
        seed,
        player_hp=(1, 1),
        player_max_hp=(1, 1),
    )


def _reseal(payload: dict[str, object]) -> DuelReexecutionReplay:
    event_chain = _build_event_hash_chain(payload["events"])
    payload["event_hash_chain"] = list(event_chain)
    payload["outcome"]["event_chain_tip"] = event_chain[-1]
    material = {key: value for key, value in payload.items() if key != "record_sha256"}
    payload["record_sha256"] = sha256_value(material)
    return DuelReexecutionReplay.from_dict(payload)


def test_record_contains_strict_header_initial_random_prefix_and_outcome() -> None:
    record = _record()
    header = record.header

    assert header["schema_version"] == REEXECUTION_SCHEMA
    assert header["mode_id"] == "test_only_duel_vertical_slice"
    assert header["test_only"] is True
    assert header["formal_result"] is False
    assert header["engine_version"]
    assert header["ruleset_version"]
    assert len(header["ruleset_hash"]) == 64
    assert len(header["deck_hash"]) == 64
    assert header["initial_rng_state"]["algorithm"] == "MT19937"
    assert header["initial_rng_state"]["call_count"] == 0
    assert header["initial_rng_call_count"] == 2
    assert tuple(call["method"] for call in record.random_consumptions[:2]) == (
        "choice",
        "shuffle",
    )
    assert record.outcome["winner_id"] in {"p1", "p2"}
    assert record.outcome["decision_count"] == len(record.decisions)
    assert record.outcome["event_count"] == len(record.events)
    assert len(record.event_hash_chain) == len(record.events)
    assert record.outcome["event_chain_tip"] == record.event_hash_chain[-1]
    assert record.outcome["random_consumption_count"] == len(
        record.random_consumptions
    )
    assert record.verify_integrity()


def test_same_seed_configuration_and_real_decisions_produce_identical_record() -> None:
    first = _record(3)
    second = _record(3)

    assert first.to_dict() == second.to_dict()
    assert first.record_sha256 == second.record_sha256


def test_reexecution_rebuilds_game_and_verifies_every_stream() -> None:
    record = _record(2)
    result = reexecute_duel_replay(record)

    assert result.verified is True
    assert result.winner_id == record.outcome["winner_id"]
    assert result.decision_count == len(record.decisions)
    assert result.random_consumption_count == len(record.random_consumptions)
    assert result.event_count == len(record.events)
    assert result.final_execution_hash == record.outcome["final_execution_hash"]
    assert result.final_game_state_hash == record.outcome["final_game_state_hash"]


def test_reexecution_detects_resealed_random_result_tampering() -> None:
    payload = _record().to_dict()
    calls = payload["random_consumptions"]
    calls[0]["result"] = "p1" if calls[0]["result"] == "p2" else "p2"
    tampered = _reseal(payload)

    with pytest.raises(ReplayDivergenceError) as captured:
        reexecute_duel_replay(tampered)

    assert captured.value.kind == "rng"
    assert captured.value.index == 0


def test_reexecution_detects_resealed_decision_tampering() -> None:
    payload = _record().to_dict()
    payload["decisions"][0]["chosen_action_id"] = "act_" + "0" * 64
    tampered = _reseal(payload)

    with pytest.raises(ReplayDivergenceError) as captured:
        reexecute_duel_replay(tampered)

    assert captured.value.kind == "decision"
    assert captured.value.index == 0


def test_reexecution_detects_resealed_event_tampering() -> None:
    payload = _record().to_dict()
    payload["events"][0]["payload"]["reason"] = "tampered"
    tampered = _reseal(payload)

    with pytest.raises(ReplayDivergenceError) as captured:
        reexecute_duel_replay(tampered)

    assert captured.value.kind == "event"
    assert captured.value.index == 0


@pytest.mark.parametrize(
    ("field", "replacement", "kind"),
    [
        ("winner_id", "not-the-winner", "winner"),
        ("final_execution_hash", "f" * 64, "state"),
        ("final_game_state_hash", "e" * 64, "state"),
    ],
)
def test_reexecution_verifies_final_hash_and_winner(
    field: str, replacement: str, kind: str
) -> None:
    payload = _record().to_dict()
    payload["outcome"][field] = replacement
    tampered = _reseal(payload)

    with pytest.raises(ReplayDivergenceError) as captured:
        reexecute_duel_replay(tampered)

    assert captured.value.kind == kind


def test_reexecution_rejects_decision_appended_after_victory() -> None:
    payload = _record().to_dict()
    extra = json.loads(json.dumps(payload["decisions"][-1], ensure_ascii=False))
    extra["index"] = len(payload["decisions"])
    payload["decisions"].append(extra)
    payload["outcome"]["decision_count"] += 1
    tampered = _reseal(payload)

    with pytest.raises(ReplayDivergenceError) as captured:
        reexecute_duel_replay(tampered)

    assert captured.value.kind == "decision"
    assert "胜利" in str(captured.value)


def test_save_load_round_trip_then_rules_reexecute(tmp_path) -> None:
    original = _record(1)
    path = tmp_path / "测试专用规则重执行回放.json"

    assert original.save(path) == path
    loaded = DuelReexecutionReplay.load(path)
    result = reexecute_duel_replay(loaded)

    assert loaded.to_dict() == original.to_dict()
    assert result.verified
    assert result.winner_id == original.outcome["winner_id"]
    assert "test_only_duel_vertical_slice" in path.read_text(encoding="utf-8")


def test_direct_tampering_without_resealing_fails_record_integrity() -> None:
    payload = _record().to_dict()
    payload["events"][0]["event_type"] = "forged"

    with pytest.raises(DuelReplayFormatError, match="event_hash_chain|总记录SHA-256"):
        DuelReexecutionReplay.from_dict(payload)


def test_initial_random_prefix_matches_fresh_game_before_first_decision() -> None:
    record = _record(28)
    config = record.header["initial_configuration"]
    fresh = TestOnlyDuelGame(
        seed=record.header["seed"],
        deck_keys=tuple(config["deck_keys"]),
        player_hp=tuple(config["player_hp"]),
        player_max_hp=tuple(config["player_max_hp"]),
        shuffle=config["shuffle"],
    )

    expected_prefix = [call.to_dict() for call in fresh.rng_calls]
    recorded_prefix = record.to_dict()["random_consumptions"][
        : record.header["initial_rng_call_count"]
    ]
    assert recorded_prefix == expected_prefix
    assert fresh.step_count == 0
