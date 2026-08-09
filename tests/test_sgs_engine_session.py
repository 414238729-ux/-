from __future__ import annotations

import csv
from dataclasses import replace
import hashlib
from pathlib import Path
import random

import pytest

from scripts.sgs_engine.engine import (
    AuthoritativeCoreSession,
    DeckInitializationError,
    EventValidationError,
    UnsupportedRuleError,
    _event_payload,
    canonical_state_snapshot,
)
from scripts.sgs_engine.events import DamageEvent, EventType, GameEvent
from scripts.sgs_engine.model import (
    DRAW_PILE,
    CharacterGender,
    CharacterMetadata,
    PlayerState,
    ZoneRef,
)
from scripts.sgs_engine.replay import NOT_LOADED_HASH
from scripts.sgs_engine.replay import state_sha256
from scripts.sgs_formal_runner import FORMAL_DECK_PATH


DECK_PATH = (
    Path(__file__).resolve().parents[1]
    / "knowledge"
    / "三国杀牌堆数据.csv"
)


def _players() -> tuple[PlayerState, PlayerState]:
    return (
        PlayerState(player_id="玩家甲", seat=1, hp=4, max_hp=4),
        PlayerState(player_id="玩家乙", seat=2, hp=3, max_hp=3),
    )


def _session(seed: int = 20260801) -> AuthoritativeCoreSession:
    return AuthoritativeCoreSession(
        players=_players(),
        seed=seed,
        deck_path=DECK_PATH,
        mode="基础设施专项测试",
    )


def _copy_deck_with_rows(
    target: Path,
    *,
    row_count: int = 160,
    duplicate_first_id: bool = False,
) -> Path:
    with DECK_PATH.open("r", encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        assert reader.fieldnames is not None
        rows = list(reader)[:row_count]
        fieldnames = reader.fieldnames
    if duplicate_first_id:
        rows[1]["instance_id"] = rows[0]["instance_id"]
    with target.open("w", encoding="utf-8", newline="") as destination:
        writer = csv.DictWriter(destination, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return target


def test_session_loads_and_audits_exactly_160_unique_formal_cards() -> None:
    session = _session()

    assert session.deck_path == DECK_PATH.resolve()
    assert session.deck_audit.is_valid
    assert session.deck_audit.total_quantity == 160
    assert len(session.deck_records) == 160
    assert len(session.state.cards) == 160
    assert len({card.instance_id for card in session.state.cards}) == 160
    assert session.state.deck_id == "sgs_mobile_non_special_20260725_unofficial"
    assert set(session.state.card_ids_in(DRAW_PILE)) == {
        card.instance_id for card in session.state.cards
    }
    assert session.rng_call_count == 1
    assert session.rng_calls[0].method == "shuffle"
    replay = session.replay
    assert replay.header.deck_hash
    assert replay.header.metadata["card_count"] == 160
    assert replay.header.metadata["supports_full_game"] is False
    session.state.assert_card_conservation()


def test_same_seed_produces_identical_shuffle_snapshot_and_header_hash() -> None:
    first = _session(seed=77)
    second = _session(seed=77)
    different = _session(seed=78)

    assert first.state.card_ids_in(DRAW_PILE) == second.state.card_ids_in(DRAW_PILE)
    assert first.rng_calls == second.rng_calls
    assert first.state_snapshot == second.state_snapshot
    assert first.state_hash == second.state_hash
    assert first.replay.header_sha256 == second.replay.header_sha256
    assert first.state.card_ids_in(DRAW_PILE) != different.state.card_ids_in(DRAW_PILE)


def test_character_metadata_is_bound_into_canonical_state_hash() -> None:
    base_state = _session(seed=77).state
    base_snapshot = canonical_state_snapshot(base_state)
    assert base_snapshot["players"][0]["character"] is None

    p1 = base_state.players_by_id["玩家甲"]
    male_state = replace(
        base_state,
        players=tuple(
            replace(
                player,
                character=CharacterMetadata(
                    character_key="test_general_a",
                    gender=CharacterGender.MALE,
                ),
            )
            if player.player_id == p1.player_id
            else player
            for player in base_state.players
        ),
    )
    unknown_gender_state = replace(
        male_state,
        players=tuple(
            replace(
                player,
                character=CharacterMetadata(
                    character_key="test_general_a",
                    gender=None,
                ),
            )
            if player.player_id == p1.player_id
            else player
            for player in male_state.players
        ),
    )
    male_snapshot = canonical_state_snapshot(male_state)
    unknown_snapshot = canonical_state_snapshot(unknown_gender_state)

    assert male_snapshot["players"][0]["character"] == {
        "character_key": "test_general_a",
        "gender": "male",
    }
    assert unknown_snapshot["players"][0]["character"] == {
        "character_key": "test_general_a",
        "gender": None,
    }
    assert state_sha256(base_snapshot) != state_sha256(male_snapshot)
    assert state_sha256(unknown_snapshot) != state_sha256(male_snapshot)


def test_deck_hash_matches_formal_runner_raw_csv_bytes() -> None:
    session = _session()
    raw_hash = hashlib.sha256(DECK_PATH.read_bytes()).hexdigest()
    runner_hash = hashlib.sha256(FORMAL_DECK_PATH.read_bytes()).hexdigest()

    assert FORMAL_DECK_PATH.resolve() == DECK_PATH.resolve()
    assert session.replay.header.deck_hash == raw_hash == runner_hash


def test_header_marks_unloaded_inputs_and_records_reproduction_environment() -> None:
    session = _session()
    header = session.replay.header
    metadata = header.metadata

    assert header.ruleset_hash == NOT_LOADED_HASH
    assert header.general_data_hash == NOT_LOADED_HASH
    assert header.strategy_version == NOT_LOADED_HASH
    assert metadata["ruleset_loaded"] is False
    assert metadata["general_data_loaded"] is False
    assert metadata["python_version"]
    assert metadata["python_implementation"]
    assert metadata["random_implementation"] == "python.random.Random"
    assert metadata["random_algorithm"] == "MT19937"
    assert metadata["random_state_version"] == random.Random.VERSION
    assert state_sha256(metadata["initial_state_snapshot"]) == session.state_hash
    assert metadata["initial_state_sha256"] == session.state_hash
    assert len(metadata["initial_rng_calls"]) == 1
    assert metadata["initial_rng_calls"][0]["method"] == "shuffle"


def test_atomic_move_preserves_old_state_conservation_and_records_replay() -> None:
    session = _session()
    before = session.state
    card_id = before.card_ids_in(DRAW_PILE)[0]
    destination = ZoneRef.hand("玩家甲")

    queued = session.move_card(
        card_id,
        destination,
        card_user="玩家甲",
        reason="确定性测试移动",
    )

    assert before.location_of(card_id) == DRAW_PILE
    assert session.state.location_of(card_id) == destination
    assert session.state.revision == before.revision + 1
    assert queued.event_type is EventType.CARD_MOVED
    assert queued.sequence == 1
    assert queued.payload["source"]["kind"] == "draw_pile"
    assert queued.payload["destination"]["owner_id"] == "玩家甲"
    assert [event.sequence for event in session.event_queue_snapshot] == [1]
    replay = session.replay
    assert len(replay.entries) == 1
    assert replay.entries[0].event_type == "card_moved"
    assert replay.entries[0].payload["sequence"] == 1
    assert replay.verify_integrity()
    assert replay.verify_state(0, session.state_snapshot)
    session.state.assert_card_conservation()


def test_two_real_moves_assign_monotonic_sequences_and_hash_chain() -> None:
    session = _session()
    first_id, second_id = session.state.card_ids_in(DRAW_PILE)[:2]

    first = session.move_card(first_id, ZoneRef.hand("玩家甲"))
    second = session.move_card(second_id, ZoneRef.hand("玩家乙"))

    assert first.sequence == 1
    assert second.sequence == 2
    assert session.state.location_of(first_id) == ZoneRef.hand("玩家甲")
    assert session.state.location_of(second_id) == ZoneRef.hand("玩家乙")
    assert [event.sequence for event in session.event_queue_snapshot] == [1, 2]
    replay = session.replay
    assert [entry.index for entry in replay.entries] == [0, 1]
    assert (
        replay.entries[1].previous_entry_sha256
        == replay.entries[0].entry_sha256
    )
    assert replay.verify_integrity()


def test_damage_replay_preserves_amount_type_target_and_separate_attribution() -> None:
    damage = DamageEvent(
        target_id="玩家乙",
        amount=2,
        damage_type="火属性",
        damage_source="玩家甲",
        skill_owner="玩家乙",
        kill_credit="玩家甲",
        payload={"说明": "只验证序列化字段，不登记虚假伤害事件"},
    )

    recorded = _event_payload(damage)
    assert recorded["target_id"] == "玩家乙"
    assert recorded["target_ids"] == ["玩家乙"]
    assert recorded["amount"] == 2
    assert recorded["damage_type"] == "火属性"
    assert recorded["damage_source"] == "玩家甲"
    assert recorded["skill_owner"] == "玩家乙"
    assert recorded["kill_credit"] == "玩家甲"


def test_event_reference_validation_rejects_unknown_virtual_card_material() -> None:
    session = _session()
    event = GameEvent(
        event_type=EventType.CARD_USED,
        card_key="virtual_slash",
        card_user="玩家甲",
        target_ids=("玩家乙",),
        material_card_instance_ids=("不存在的实体牌",),
    )

    with pytest.raises(EventValidationError, match="不存在的转化材料实体牌"):
        session._validate_event_references(event)


def test_core_mutable_components_are_not_exposed_for_bypass() -> None:
    session = _session()
    card_id = session.state.card_ids_in(DRAW_PILE)[0]
    session.move_card(card_id, ZoneRef.hand("玩家甲"))

    assert not hasattr(session, "rng")
    assert not hasattr(session, "event_queue")
    assert not hasattr(session, "emit_event")
    assert isinstance(session.rng_calls, tuple)
    assert isinstance(session.event_queue_snapshot, tuple)
    assert not hasattr(session.rng_calls, "random")
    assert not hasattr(session.event_queue_snapshot, "enqueue")
    with pytest.raises(TypeError):
        session.rng_calls[0].arguments["before"] = ()  # type: ignore[index]
    with pytest.raises(TypeError):
        session.event_queue_snapshot[0].payload["reason"] = "篡改"  # type: ignore[index]

    replay_copy = session.replay
    replay_copy.add_entry("伪造事件", {}, session.state_snapshot)
    assert len(replay_copy.entries) == 2
    assert len(session.replay.entries) == 1

    replay_dict = session.replay_snapshot
    replay_dict["header"]["mode"] = "被外部篡改"
    assert session.replay.header.mode == "基础设施专项测试"


def test_state_event_cannot_be_recorded_without_a_matching_state_transition() -> None:
    session = _session()

    assert not hasattr(session, "emit_event")
    assert len(session.event_queue_snapshot) == 0
    assert len(session.replay.entries) == 0
    assert session.state.revision == 1


def test_invalid_destination_owner_fails_without_partial_state_or_event() -> None:
    session = _session()
    card_id = session.state.card_ids_in(DRAW_PILE)[0]
    before_state = session.state
    before_hash = session.state_hash

    with pytest.raises(ValueError, match="区域所有者.*不存在"):
        session.move_card(card_id, ZoneRef.hand("不存在的玩家"))

    assert session.state is before_state
    assert session.state_hash == before_hash
    assert session.event_queue_snapshot == ()
    assert len(session.replay.entries) == 0


def test_unknown_move_actor_or_card_fails_with_clear_chinese_error() -> None:
    session = _session()
    real_card_id = session.state.card_ids_in(DRAW_PILE)[0]

    with pytest.raises(EventValidationError, match="不存在的玩家"):
        session.move_card(
            real_card_id,
            ZoneRef.hand("玩家甲"),
            card_user="幽灵玩家",
        )
    with pytest.raises(ValueError, match="找不到实体牌"):
        session.move_card(
            "不存在的实体牌",
            ZoneRef.hand("玩家甲"),
            card_user="玩家甲",
        )

    assert session.event_queue_snapshot == ()
    assert len(session.replay.entries) == 0


def test_incomplete_formal_deck_is_rejected_instead_of_silently_running(
    tmp_path: Path,
) -> None:
    incomplete = _copy_deck_with_rows(tmp_path / "不完整牌堆.csv", row_count=159)

    with pytest.raises(DeckInitializationError, match="160"):
        AuthoritativeCoreSession(
            players=_players(),
            seed=1,
            deck_path=incomplete,
        )


def test_duplicate_formal_instance_id_is_rejected(
    tmp_path: Path,
) -> None:
    duplicate = _copy_deck_with_rows(
        tmp_path / "重复实体ID牌堆.csv",
        duplicate_first_id=True,
    )

    with pytest.raises(DeckInitializationError, match="实体牌.*冲突|instance_id"):
        AuthoritativeCoreSession(
            players=_players(),
            seed=1,
            deck_path=duplicate,
        )


def test_canonical_snapshot_is_stable_and_covers_all_card_locations() -> None:
    session = _session()

    first = canonical_state_snapshot(session.state)
    second = canonical_state_snapshot(session.state)

    assert first == second
    assert len(first["cards"]) == 160
    assert sum(len(zone["instance_ids"]) for zone in first["zones"]) == 160


def test_run_game_fails_closed_without_probability_or_fixed_value_fallback() -> None:
    session = _session()
    before_hash = session.state_hash

    with pytest.raises(UnsupportedRuleError, match="完整对局规则尚未实现.*拒绝"):
        session.run_game()

    assert session.state_hash == before_hash
    assert len(session.replay.entries) == 0
