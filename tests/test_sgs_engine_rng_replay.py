from __future__ import annotations

import json
import random

import pytest

from scripts.sgs_engine.replay import (
    NOT_LOADED_HASH,
    ReplayFormatError,
    ReplayHeader,
    ReplayIntegrityError,
    ReplayRecord,
    canonical_json,
    state_sha256,
)
from scripts.sgs_engine.rng import (
    RNG_ALGORITHM,
    RNG_IMPLEMENTATION,
    RNG_STATE_SCHEMA,
    DeterministicRNG,
)


def test_rng_uses_one_persistent_stream_and_records_every_consumption() -> None:
    expected = random.Random(20260801)
    rng = DeterministicRNG(20260801)

    actual_values = [rng.random(), rng.random(), rng.randrange(2, 19, 3)]
    expected_values = [expected.random(), expected.random(), expected.randrange(2, 19, 3)]

    assert actual_values == expected_values
    assert actual_values[0] != actual_values[1]
    assert rng.call_count == 3
    assert [call.index for call in rng.calls] == [0, 1, 2]
    assert [call.method for call in rng.calls] == ["random", "random", "randrange"]
    assert rng.calls[2].arguments == {"start": 2, "stop": 19, "step": 3}


def test_same_seed_and_same_call_order_reproduce_mutations_and_results() -> None:
    def consume(rng: DeterministicRNG) -> tuple[list[str], str, list[int], list[str]]:
        cards = ["杀", "闪", "桃", "酒", "无懈可击"]
        rng.shuffle(cards)
        chosen = rng.choice(cards)
        sampled = rng.sample(range(10), 4)
        weighted = rng.choices(["红", "黑"], weights=[3, 2], k=5)
        return cards, chosen, sampled, weighted

    first = DeterministicRNG(77)
    second = DeterministicRNG(77)

    assert consume(first) == consume(second)
    assert first.export_calls() == second.export_calls()
    assert [call.method for call in first.calls] == [
        "shuffle",
        "choice",
        "sample",
        "choices",
    ]
    assert first.calls[0].arguments["before"] == ("杀", "闪", "桃", "酒", "无懈可击")
    assert set(first.calls[0].result["after"]) == {"杀", "闪", "桃", "酒", "无懈可击"}


def test_rng_rejects_empty_choice_with_chinese_error() -> None:
    rng = DeterministicRNG(1)
    with pytest.raises(ValueError, match="不能为空"):
        rng.choice([])
    assert rng.call_count == 0


def test_rng_call_snapshot_is_deeply_frozen_and_export_is_independent_copy() -> None:
    candidates = [
        {"card": "杀", "tags": ["basic"]},
        {"card": "桃", "tags": ["basic", "heal"]},
    ]
    rng = DeterministicRNG(5)
    rng.choice(candidates)
    candidates[0]["tags"].append("外部改写")

    call = rng.calls[0]
    assert "外部改写" not in call.arguments["population"][0]["tags"]
    with pytest.raises(TypeError):
        call.arguments["population"] = ()  # type: ignore[index]
    with pytest.raises(AttributeError):
        call.arguments["population"][0]["tags"].append("篡改")

    exported = rng.export_calls()
    exported[0]["arguments"]["population"][0]["tags"].append("仅改导出副本")
    assert "仅改导出副本" not in rng.calls[0].arguments["population"][0]["tags"]


def test_rng_initial_state_exports_complete_canonical_random_state() -> None:
    rng = DeterministicRNG(20260801)
    exported = rng.export_initial_state()
    expected_state = random.Random(20260801).getstate()

    assert exported["schema"] == RNG_STATE_SCHEMA
    assert exported["implementation"] == RNG_IMPLEMENTATION
    assert exported["algorithm"] == RNG_ALGORITHM
    assert exported["state_version"] == random.Random.VERSION
    assert exported["seed"] == 20260801
    assert exported["call_count"] == 0
    assert exported["getstate"][0] == expected_state[0]
    assert exported["getstate"][1] == list(expected_state[1])
    assert exported["getstate"][2] == expected_state[2]
    assert len(exported["getstate"][1]) == len(expected_state[1])
    assert rng.export_current_state() == exported
    assert rng.current_state_sha256 == rng.initial_state_sha256
    assert rng.call_count == 0


def test_rng_state_hash_changes_after_consumption_and_initial_state_is_stable() -> None:
    rng = DeterministicRNG(31)
    initial = rng.export_initial_state()
    initial_hash = rng.initial_state_sha256

    rng.randrange(10)
    current = rng.export_current_state()

    assert current["call_count"] == 1
    assert current["getstate"] != initial["getstate"]
    assert rng.current_state_sha256 != initial_hash
    assert rng.export_initial_state() == initial
    assert rng.initial_state_sha256 == initial_hash
    assert rng.call_count == 1


def test_same_seed_and_consumptions_have_same_rng_state_hash() -> None:
    first = DeterministicRNG(88)
    second = DeterministicRNG(88)

    for rng in (first, second):
        rng.choice(["杀", "闪", "桃"])
        cards = [1, 2, 3, 4]
        rng.shuffle(cards)

    assert first.export_initial_state() == second.export_initial_state()
    assert first.initial_state_sha256 == second.initial_state_sha256
    assert first.export_current_state() == second.export_current_state()
    assert first.current_state_sha256 == second.current_state_sha256


def test_rng_state_exports_are_independent_mutable_copies() -> None:
    rng = DeterministicRNG(19)
    initial_hash = rng.initial_state_sha256
    initial = rng.export_initial_state()
    current = rng.export_current_state()

    initial["algorithm"] = "tampered"
    initial["getstate"][1][0] = -1
    current["getstate"][1].append(-1)
    current["call_count"] = 999

    assert rng.export_initial_state()["algorithm"] == RNG_ALGORITHM
    assert rng.export_initial_state()["getstate"][1][0] != -1
    assert len(rng.export_current_state()["getstate"][1]) == 625
    assert rng.export_current_state()["call_count"] == 0
    assert rng.initial_state_sha256 == initial_hash
    assert rng.current_state_sha256 == initial_hash
    assert rng.call_count == 0


@pytest.mark.parametrize(
    "invoke",
    [
        lambda rng: rng.randrange(True),
        lambda rng: rng.randrange(0, 3, False),
        lambda rng: rng.randint(False, 3),
        lambda rng: rng.sample([1, 2], True),
        lambda rng: rng.sample([1, 2], 1, counts=[1, False]),
        lambda rng: rng.choices([1, 2], k=True),
    ],
)
def test_rng_integer_parameters_strictly_reject_bool(invoke) -> None:
    rng = DeterministicRNG(9)
    with pytest.raises((TypeError, ValueError), match="整数|布尔值"):
        invoke(rng)
    assert rng.call_count == 0


@pytest.mark.parametrize(
    "invoke",
    [
        lambda rng: rng.uniform(float("nan"), 1.0),
        lambda rng: rng.uniform(0.0, float("inf")),
        lambda rng: rng.choices([1, 2], weights=[1.0, float("nan")]),
        lambda rng: rng.choices([1, 2], cum_weights=[1.0, float("inf")]),
    ],
)
def test_rng_rejects_nonfinite_float_parameters_before_consuming(invoke) -> None:
    rng = DeterministicRNG(11)
    with pytest.raises(ValueError, match="有限"):
        invoke(rng)
    assert rng.call_count == 0


def test_rng_rejects_negative_cumulative_weights_before_consuming() -> None:
    rng = DeterministicRNG(12)

    with pytest.raises(ValueError, match="cum_weights.*负数"):
        rng.choices(["甲", "乙"], cum_weights=[-1, 1], k=1)

    assert rng.call_count == 0


def _record() -> ReplayRecord:
    record = ReplayRecord(
        ReplayHeader(
            engine_version="sgs-core-test",
            mode="2v2",
            seed=123,
            ruleset_hash="1" * 64,
            deck_hash="2" * 64,
            general_data_hash="3" * 64,
            strategy_version="strategy",
            metadata={"说明": "中文回放"},
        )
    )
    record.add_entry(
        "card_used",
        {"card": "杀", "source": "玩家甲", "target": "玩家乙"},
        {"players": {"玩家甲": {"hand": 3}, "玩家乙": {"hp": 4}}},
    )
    record.add_entry(
        "damage",
        {"source": "玩家甲", "target": "玩家乙", "amount": 1},
        {"players": {"玩家甲": {"hand": 3}, "玩家乙": {"hp": 3}}},
    )
    return record


def _header_kwargs() -> dict[str, object]:
    return {
        "engine_version": "engine-v1",
        "mode": "2v2",
        "seed": 1,
        "ruleset_hash": "1" * 64,
        "deck_hash": "2" * 64,
        "general_data_hash": "3" * 64,
        "strategy_version": "strategy",
    }


@pytest.mark.parametrize(
    "field_name",
    [
        "engine_version",
        "mode",
        "ruleset_hash",
        "deck_hash",
        "general_data_hash",
        "strategy_version",
    ],
)
def test_replay_header_rejects_empty_required_text(field_name: str) -> None:
    values = _header_kwargs()
    values[field_name] = ""
    with pytest.raises(ReplayFormatError, match=field_name):
        ReplayHeader(**values)  # type: ignore[arg-type]


def test_replay_header_rejects_unsupported_schema_and_bool_seed() -> None:
    with pytest.raises(ReplayFormatError, match="仅支持 1.0"):
        ReplayHeader(**_header_kwargs(), schema_version="2.0")  # type: ignore[arg-type]
    values = _header_kwargs()
    values["seed"] = True
    with pytest.raises(ReplayFormatError, match="布尔值"):
        ReplayHeader(**values)  # type: ignore[arg-type]


def test_replay_header_requires_real_hash_or_explicit_not_loaded_marker() -> None:
    values = _header_kwargs()
    values["deck_hash"] = "looks-like-a-name"
    with pytest.raises(ReplayFormatError, match="deck_hash.*64位SHA-256"):
        ReplayHeader(**values)  # type: ignore[arg-type]

    values = _header_kwargs()
    values["ruleset_hash"] = NOT_LOADED_HASH
    values["general_data_hash"] = NOT_LOADED_HASH
    header = ReplayHeader(**values)  # type: ignore[arg-type]
    assert header.ruleset_hash == NOT_LOADED_HASH
    assert header.general_data_hash == NOT_LOADED_HASH


def test_replay_loader_requires_schema_and_rejects_unknown_fields() -> None:
    payload = _record().to_dict()
    del payload["header"]["schema_version"]
    with pytest.raises(ReplayFormatError, match="schema_version"):
        ReplayRecord.from_dict(payload)

    payload = _record().to_dict()
    payload["unexpected"] = True
    with pytest.raises(ReplayFormatError, match="根节点包含未知字段"):
        ReplayRecord.from_dict(payload)


def test_replay_metadata_payload_state_and_entries_are_deeply_readonly() -> None:
    metadata = {"labels": ["正式"]}
    header = ReplayHeader(**_header_kwargs(), metadata=metadata)  # type: ignore[arg-type]
    metadata["labels"].append("外部改写")
    assert header.metadata["labels"] == ("正式",)
    with pytest.raises(TypeError):
        header.metadata["new"] = True  # type: ignore[index]

    payload = {"targets": ["乙"]}
    state = {"players": {"乙": {"hp": 3}}}
    record = ReplayRecord(header)
    record.add_entry("damage", payload, state)
    payload["targets"].append("丙")
    state["players"]["乙"]["hp"] = 99

    assert record.entries[0].payload["targets"] == ("乙",)
    assert record.entries[0].state_snapshot["players"]["乙"]["hp"] == 3
    with pytest.raises(TypeError):
        record.entries[0].state_snapshot["players"]["乙"]["hp"] = 1
    with pytest.raises(AttributeError):
        record.entries.append(record.entries[0])

    exported = record.to_dict()
    exported["entries"][0]["payload"]["targets"].append("只改副本")
    assert record.entries[0].payload["targets"] == ("乙",)


def test_canonical_state_hash_is_independent_of_mapping_insertion_order() -> None:
    first = {"b": [2, 3], "a": {"体力": 3, "手牌": 4}}
    second = {"a": {"手牌": 4, "体力": 3}, "b": [2, 3]}

    assert canonical_json(first) == canonical_json(second)
    assert state_sha256(first) == state_sha256(second)


@pytest.mark.parametrize("suffix", [".json", ".jsonl"])
def test_utf8_replay_round_trip_and_stepwise_verification(tmp_path, suffix: str) -> None:
    original = _record()
    path = tmp_path / f"中文对局{suffix}"

    original.save(path)
    loaded = ReplayRecord.load(path)

    assert "中文回放" in path.read_text(encoding="utf-8")
    assert loaded.to_dict() == original.to_dict()
    assert loaded.verify_integrity()
    assert [entry.event_type for entry in loaded.iter_verified_entries()] == [
        "card_used",
        "damage",
    ]
    assert loaded.verify_state(1, loaded.entries[1].state_snapshot)


def test_json_load_detects_tampered_state_snapshot(tmp_path) -> None:
    path = tmp_path / "tampered-state.json"
    _record().save_json(path)
    content = json.loads(path.read_text(encoding="utf-8"))
    content["entries"][1]["state_snapshot"]["players"]["玩家乙"]["hp"] = 99
    path.write_text(json.dumps(content, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(ReplayIntegrityError, match="状态 SHA-256 不匹配"):
        ReplayRecord.load_json(path)


def test_jsonl_load_detects_tampered_event_payload(tmp_path) -> None:
    path = tmp_path / "tampered-event.jsonl"
    _record().save_jsonl(path)
    lines = path.read_text(encoding="utf-8").splitlines()
    event = json.loads(lines[1])
    event["data"]["payload"]["card"] = "桃"
    lines[1] = json.dumps(event, ensure_ascii=False)
    path.write_text("\n".join(lines), encoding="utf-8")

    with pytest.raises(ReplayIntegrityError, match="事件 SHA-256 不匹配"):
        ReplayRecord.load_jsonl(path)


def test_jsonl_loader_rejects_unknown_wrapper_fields(tmp_path) -> None:
    path = tmp_path / "unknown-wrapper.jsonl"
    _record().save_jsonl(path)
    lines = path.read_text(encoding="utf-8").splitlines()
    header = json.loads(lines[0])
    header["unexpected"] = True
    lines[0] = json.dumps(header, ensure_ascii=False)
    path.write_text("\n".join(lines), encoding="utf-8")

    with pytest.raises(ReplayFormatError, match="包含未知字段"):
        ReplayRecord.load_jsonl(path)


def test_header_tampering_breaks_first_entry_anchor(tmp_path) -> None:
    path = tmp_path / "tampered-header.json"
    _record().save_json(path)
    content = json.loads(path.read_text(encoding="utf-8"))
    content["header"]["seed"] = 999
    path.write_text(json.dumps(content, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(ReplayIntegrityError, match="前向哈希不匹配"):
        ReplayRecord.load_json(path)


def test_stepwise_verification_rejects_divergent_live_state() -> None:
    record = _record()
    expected_states = [
        record.entries[0].state_snapshot,
        {"players": {"玩家甲": {"hand": 3}, "玩家乙": {"hp": 2}}},
    ]

    with pytest.raises(ReplayIntegrityError, match="重放状态与记录状态不一致"):
        tuple(record.iter_verified_entries(expected_states))


def test_verify_state_checks_the_whole_chain_before_requested_step() -> None:
    record = _record()
    object.__setattr__(record.entries[0], "entry_sha256", "0" * 64)

    with pytest.raises(ReplayIntegrityError, match="第 0 步事件 SHA-256 不匹配"):
        record.verify_state(1, record.entries[1].state_snapshot)
