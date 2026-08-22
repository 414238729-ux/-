# -*- coding: utf-8 -*-
"""POST-B C6：普通八人一等 strict replay、三种自然胜利与篡改失败关闭。"""

from __future__ import annotations

from typing import Any, Callable

import pytest

from scripts.sgs_engine.model import DRAW_PILE, ZoneRef
from scripts.sgs_engine.mode_identity import (
    C6_CANONICAL_DRAW_REACHABILITY_STATUS,
    FORMAL_NO_SKILL_IDENTITY_8P_MODE,
    FormalEightPlayerIdentityConfiguration,
    FormalEightPlayerIdentitySession,
)
from scripts.sgs_engine.production_replay import (
    SUPPORTED_REPLAY_MODES,
    ProductionReexecutionReplay,
    ProductionReplayDivergenceError,
    ProductionReplayFormatError,
    record_reference_formal_eight_player_identity,
    record_reference_production_batch,
    reexecute_production_replay,
)

PHYSICAL = ("p1", "p2", "p3", "p4", "p5", "p6", "p7", "p8")
ROLE_CARDS = (
    "lord",
    "loyalist",
    "loyalist",
    "rebel",
    "rebel",
    "rebel",
    "rebel",
    "spy",
)
NATURAL_VICTORY_SEEDS = {
    "lord_and_loyalists": 16,
    "rebels": 7,
    "spy": 49,
}
_RECORD_CACHE: dict[int, ProductionReexecutionReplay] = {}


def _record(seed: int) -> ProductionReexecutionReplay:
    cached = _RECORD_CACHE.get(seed)
    if cached is not None:
        return cached
    record = record_reference_formal_eight_player_identity(
        seed,
        configuration=FormalEightPlayerIdentityConfiguration.formal_profile(),
        analysis_only=False,
        max_steps=8000,
    )
    _RECORD_CACHE[seed] = record
    return record


def _assert_c6_record(
    record: ProductionReexecutionReplay, expected_winner: str
) -> None:
    assert record.header["mode_id"] == FORMAL_NO_SKILL_IDENTITY_8P_MODE
    assert record.header["formal_result"] is True
    assert record.header["fixture_applied"] is False
    config = record.header["initial_configuration"]
    assert set(config) == {
        "formal_eight_player_identity_configuration",
        "physical_player_ids",
        "identities",
        "numbered_player_order",
        "lord_player_id",
        "analysis_only",
        "max_steps",
    }
    assert "formal_identity_configuration" not in config
    assert config["analysis_only"] is False
    formal_config = config["formal_eight_player_identity_configuration"]
    assert formal_config["schema"] == (
        "formal-no-skill-identity-8p-configuration-v1"
    )
    assert tuple(formal_config["physical_player_ids"]) == PHYSICAL
    assert tuple(formal_config["identity_cards"]) == ROLE_CARDS
    assert tuple(config["physical_player_ids"]) == PHYSICAL
    identities = dict(config["identities"])
    assert set(identities) == set(PHYSICAL)
    assert list(identities.values()).count("lord") == 1
    assert list(identities.values()).count("loyalist") == 2
    assert list(identities.values()).count("rebel") == 4
    assert list(identities.values()).count("spy") == 1
    lord = config["lord_player_id"]
    assert identities[lord] == "lord"
    lord_index = PHYSICAL.index(lord)
    assert tuple(config["numbered_player_order"]) == (
        PHYSICAL[lord_index:] + PHYSICAL[:lord_index]
    )
    assert record.random_consumptions[0]["method"] == "shuffle"
    assert tuple(
        record.random_consumptions[0]["arguments"]["before"]
    ) == ROLE_CARDS
    assert record.random_consumptions[1]["method"] == "shuffle"
    assert len(record.random_consumptions[1]["arguments"]["before"]) == 160
    assert record.header["initial_rng_call_count"] == 2
    assert record.header["initial_event_count"] == 33
    assert record.outcome["winner_id"] == expected_winner
    assert record.outcome["finish_reason"] == "identity_victory"
    assert len(record.decisions) > 0
    assert len(record.record_sha256) == 64
    assert len(record.header["initial_execution_hash"]) == 64
    assert len(record.header["initial_game_state_hash"]) == 64
    assert len(record.outcome["final_execution_hash"]) == 64
    assert len(record.outcome["final_game_state_hash"]) == 64


def test_c6_mode_is_first_class_supported_replay_input() -> None:
    assert FORMAL_NO_SKILL_IDENTITY_8P_MODE in SUPPORTED_REPLAY_MODES
    assert FORMAL_NO_SKILL_IDENTITY_8P_MODE != "formal_no_skill_identity_5p"


@pytest.mark.parametrize(
    ("winner", "seed"),
    tuple(NATURAL_VICTORY_SEEDS.items()),
)
def test_c6_three_natural_victories_authoritative_strict_reexecute(
    winner: str, seed: int
) -> None:
    record = _record(seed)
    _assert_c6_record(record, winner)
    result = reexecute_production_replay(record)
    assert result.verified is True
    assert result.winner_id == winner
    assert result.decision_count == len(record.decisions)
    assert result.random_consumption_count == len(record.random_consumptions)
    assert result.event_count == len(record.events)
    assert result.final_execution_hash == record.outcome["final_execution_hash"]
    assert result.final_game_state_hash == record.outcome["final_game_state_hash"]


def test_c6_analysis_only_flag_is_rebuilt_and_cannot_be_formal_result() -> None:
    """同一自然记录只改变 authority flag；规则执行材料必须仍严格重建。"""

    payload = _record(7).to_dict()
    payload["header"]["formal_result"] = False
    payload["header"]["initial_configuration"]["analysis_only"] = True
    payload["record_sha256"] = ""
    analysis_record = ProductionReexecutionReplay.from_dict(payload)
    assert analysis_record.header["formal_result"] is False
    assert analysis_record.header["initial_configuration"]["analysis_only"] is True
    result = reexecute_production_replay(analysis_record)
    assert result.verified is True
    assert result.winner_id == "rebels"


def test_c6_formal_replay_rejects_fixture_before_recording() -> None:
    game = FormalEightPlayerIdentitySession(
        seed=7,
        configuration=FormalEightPlayerIdentityConfiguration.formal_profile(),
        analysis_only=True,
    )
    with pytest.raises(ProductionReplayFormatError, match="正式身份回放禁止夹具"):
        record_reference_production_batch(
            7,
            _game=game,
            fixture=lambda _game: None,
        )


def test_c6_premutated_state_cannot_mint_formal_replay() -> None:
    game = FormalEightPlayerIdentitySession(
        seed=7,
        configuration=FormalEightPlayerIdentityConfiguration.formal_profile(),
        analysis_only=False,
    )
    moved = game.state.card_ids_in(DRAW_PILE)[0]
    game._state = game.state.move_card(moved, ZoneRef.hand(game.lord_player_id))
    assert game.formal_result_eligible is False
    with pytest.raises(ProductionReplayFormatError, match="预突变state"):
        record_reference_production_batch(7, _game=game, max_steps=8000)


def test_c6_draw_reachability_remains_independently_unresolved() -> None:
    assert C6_CANONICAL_DRAW_REACHABILITY_STATUS == (
        "C6_CANONICAL_DRAW_REACHABILITY_UNRESOLVED"
    )
    assert C6_CANONICAL_DRAW_REACHABILITY_STATUS not in {
        "C5_CANONICAL_DRAW_REACHABILITY_UNRESOLVED",
        "N/A",
        "mathematically impossible",
        "PROVEN_UNREACHABLE",
        "proven unreachable",
    }


def _set_record_hash_blank(payload: dict[str, object]) -> None:
    payload["record_sha256"] = ""


def _mode_spoof(payload: dict[str, object]) -> None:
    payload["header"]["mode_id"] = "formal_no_skill_identity_5p"


def _schema_spoof(payload: dict[str, object]) -> None:
    config = payload["header"]["initial_configuration"]
    config["formal_eight_player_identity_configuration"]["schema"] = (
        "formal-no-skill-identity-5p-configuration-v1"
    )


def _physical_reorder(payload: dict[str, object]) -> None:
    config = payload["header"]["initial_configuration"]
    config["physical_player_ids"] = list(reversed(config["physical_player_ids"]))


def _identity_bool_alias(payload: dict[str, object]) -> None:
    config = payload["header"]["initial_configuration"]
    lord = config["lord_player_id"]
    config["identities"][lord] = True


def _numbered_reorder(payload: dict[str, object]) -> None:
    config = payload["header"]["initial_configuration"]
    config["numbered_player_order"] = list(
        reversed(config["numbered_player_order"])
    )


def _analysis_int_alias(payload: dict[str, object]) -> None:
    payload["header"]["initial_configuration"]["analysis_only"] = 0


def _extra_configuration_field(payload: dict[str, object]) -> None:
    payload["header"]["initial_configuration"]["heir_player_id"] = None


def _missing_configuration_field(payload: dict[str, object]) -> None:
    del payload["header"]["initial_configuration"]["lord_player_id"]


def _null_identity_map(payload: dict[str, object]) -> None:
    payload["header"]["initial_configuration"]["identities"] = None


@pytest.mark.parametrize(
    "mutator",
    (
        _mode_spoof,
        _schema_spoof,
        _physical_reorder,
        _identity_bool_alias,
        _numbered_reorder,
        _analysis_int_alias,
        _extra_configuration_field,
        _missing_configuration_field,
        _null_identity_map,
    ),
)
def test_c6_profile_assignment_and_exact_field_tamper_fail_closed(
    mutator: Callable[[dict[str, object]], None],
) -> None:
    payload = _record(7).to_dict()
    mutator(payload)
    _set_record_hash_blank(payload)
    with pytest.raises(
        (ProductionReplayFormatError, ProductionReplayDivergenceError)
    ):
        tampered = ProductionReexecutionReplay.from_dict(payload)
        reexecute_production_replay(tampered)


def _random_result_tamper(payload: dict[str, object]) -> None:
    after = payload["random_consumptions"][0]["result"]["after"]
    payload["random_consumptions"][0]["result"]["after"] = list(
        reversed(after)
    )


def _decision_context_tamper(payload: dict[str, object]) -> None:
    payload["decisions"][0]["context"]["actor_id"] = "p8"


def _event_tamper(payload: dict[str, object]) -> None:
    payload["events"][0]["payload"]["reason"] = "tampered_initial_hand"


def _initial_state_hash_tamper(payload: dict[str, object]) -> None:
    payload["header"]["initial_game_state_hash"] = "0" * 64


def _final_execution_hash_tamper(payload: dict[str, object]) -> None:
    payload["outcome"]["final_execution_hash"] = "0" * 64


@pytest.mark.parametrize(
    "mutator",
    (
        _random_result_tamper,
        _decision_context_tamper,
        _event_tamper,
        _initial_state_hash_tamper,
        _final_execution_hash_tamper,
    ),
)
def test_c6_rng_decision_event_state_execution_tamper_fail_closed(
    mutator: Callable[[dict[str, object]], None],
) -> None:
    payload = _record(7).to_dict()
    mutator(payload)
    _set_record_hash_blank(payload)
    with pytest.raises(
        (ProductionReplayFormatError, ProductionReplayDivergenceError)
    ):
        tampered = ProductionReexecutionReplay.from_dict(payload)
        reexecute_production_replay(tampered)
