"""Experimental active-response modifier v1 contract tests.

All scenarios begin from the frozen configuration and the registered deck.  The
tests inspect naturally dealt cards to select deterministic seeds; they never
write ``_state``/``_runtime`` or inject skill state.
"""

from __future__ import annotations

from dataclasses import replace
from functools import lru_cache

import pytest

from scripts.sgs_engine.actions import InvalidActionError, LegalAction, UnsupportedRuleError
from scripts.sgs_engine.experimental_active_response import (
    EXPERIMENTAL_ACTIVE_RESPONSE_EXECUTION_SCHEMA,
    ExperimentalActiveResponseConfiguration,
    ExperimentalActiveResponseConfigurationError,
    ExperimentalActiveResponseSession,
    create_experimental_active_response_session,
)
from scripts.sgs_engine.model import DISCARD_PILE, PROCESSING_ZONE, ZoneRef
from scripts.sgs_engine.production_batch import (
    BatchActionIdController,
    BatchReferenceController,
    ProductionPhase,
)
from scripts.sgs_engine.production_replay import (
    ExperimentalActiveResponseReplay,
    ProductionReplayDivergenceError,
    ProductionReplayFormatError,
    record_experimental_active_response_replay,
    reexecute_experimental_active_response_replay,
)
from scripts.sgs_engine.replay import sha256_value


HOLDER = "experimental_modifier_holder"
OPPONENT = "experimental_opponent"
SHA = "sgs_basic_sha"
SHAN = "sgs_basic_shan"
DUEL = "sgs_trick_juedou"


@lru_cache(maxsize=1)
def _configuration() -> ExperimentalActiveResponseConfiguration:
    return ExperimentalActiveResponseConfiguration.default_profile()


def _game(seed: int) -> ExperimentalActiveResponseSession:
    return ExperimentalActiveResponseSession(seed=seed, configuration=_configuration())


def _hand_keys(game: ExperimentalActiveResponseSession, player_id: str) -> tuple[str, ...]:
    return tuple(
        game.state.cards_by_id[instance_id].card_key
        for instance_id in game.state.card_ids_in(ZoneRef.hand(player_id))
    )


def _action(
    game: ExperimentalActiveResponseSession,
    operation: str,
    *,
    card_key: str | None = None,
) -> LegalAction:
    for action in game.legal_actions():
        if action.payload.get("operation") != operation:
            continue
        if card_key is not None and action.payload.get("card_key") != card_key:
            continue
        return action
    raise AssertionError(f"找不到操作{operation!r} card_key={card_key!r}")


def _step_action(game: ExperimentalActiveResponseSession, action: LegalAction) -> LegalAction:
    assert action.action_id is not None
    return game.step(BatchActionIdController(action.action_id))


def _advance_current_player_to_play(game: ExperimentalActiveResponseSession) -> None:
    for operation in ("proceed_prepare", "proceed_judgment", "proceed_draw"):
        _step_action(game, _action(game, operation))
    assert game.phase is ProductionPhase.PLAY


def _pass_trick_to_duel(game: ExperimentalActiveResponseSession) -> None:
    while game.phase is ProductionPhase.TRICK_RESPONSE:
        _step_action(game, _action(game, "pass_trick_response"))
    assert game.phase is ProductionPhase.DUEL_RESPONSE


def _end_holder_turn(game: ExperimentalActiveResponseSession) -> None:
    assert game.phase is ProductionPhase.PLAY
    _step_action(game, _action(game, "end_play_phase"))
    while game.phase is ProductionPhase.DISCARD:
        try:
            submit = _action(game, "discard_phase_submit")
        except AssertionError:
            choices = [
                action
                for action in game.legal_actions()
                if action.payload.get("operation") == "select_discard_card"
            ]
            assert choices
            # Preserve H's real Slash for the later required=1 response.
            choice = next(
                (
                    item
                    for item in choices
                    if item.payload.get("card_key") != SHA
                ),
                choices[0],
            )
            _step_action(game, choice)
        else:
            _step_action(game, submit)
    assert game.phase is ProductionPhase.END
    _step_action(game, _action(game, "end_turn"))
    _advance_current_player_to_play(game)
    assert game.current_actor_id == OPPONENT


@lru_cache(maxsize=1)
def _seed_holder_slash_opponent_two_dodge() -> int:
    for seed in range(500):
        game = _game(seed)
        if SHA in _hand_keys(game, HOLDER) and _hand_keys(game, OPPONENT).count(SHAN) >= 2:
            return seed
    raise AssertionError("500个自然seed内没有找到双闪场景")


@lru_cache(maxsize=1)
def _seed_holder_duel_opponent_two_slash() -> int:
    for seed in range(500):
        game = _game(seed)
        if DUEL in _hand_keys(game, HOLDER) and _hand_keys(game, OPPONENT).count(SHA) >= 2:
            return seed
    raise AssertionError("500个自然seed内没有找到双杀决斗场景")


@lru_cache(maxsize=1)
def _seed_opponent_duel_holder_slash() -> int:
    for seed in range(500):
        game = _game(seed)
        if DUEL in _hand_keys(game, OPPONENT) and SHA in _hand_keys(game, HOLDER):
            return seed
    raise AssertionError("500个自然seed内没有找到反向决斗场景")


def _open_holder_slash_response() -> ExperimentalActiveResponseSession:
    game = _game(_seed_holder_slash_opponent_two_dodge())
    _advance_current_player_to_play(game)
    _step_action(game, _action(game, "use_slash", card_key=SHA))
    assert game.phase is ProductionPhase.SLASH_RESPONSE
    assert game.current_actor_id == OPPONENT
    return game


def _open_holder_duel() -> ExperimentalActiveResponseSession:
    game = _game(_seed_holder_duel_opponent_two_slash())
    _advance_current_player_to_play(game)
    _step_action(game, _action(game, "use_duel", card_key=DUEL))
    _pass_trick_to_duel(game)
    assert game.current_actor_id == OPPONENT
    return game


class _DirectController:
    def __init__(self, action: LegalAction) -> None:
        self._action = action

    def choose(
        self, legal_actions: tuple[LegalAction, ...], context: object
    ) -> LegalAction:
        del legal_actions, context
        return self._action


def test_strict_configuration_and_no_external_injection() -> None:
    configuration = _configuration()
    assert configuration.experimental is True
    assert configuration.formal_result is False
    assert configuration.skill_profile.activation_policy == "configuration_static"
    raw = configuration.to_dict()
    raw["unexpected"] = True
    with pytest.raises(ExperimentalActiveResponseConfigurationError):
        ExperimentalActiveResponseConfiguration.from_dict(raw)
    with pytest.raises(TypeError):
        ExperimentalActiveResponseSession(  # type: ignore[call-arg]
            seed=1,
            configuration=configuration,
            wushuang_active=True,
        )
    with pytest.raises(TypeError):
        create_experimental_active_response_session(  # type: ignore[call-arg]
            seed=1,
            configuration=configuration,
            provider=object(),
        )
    with pytest.raises(TypeError):
        record_experimental_active_response_replay(  # type: ignore[call-arg]
            1,
            configuration=configuration,
            fixture=lambda _game: None,
        )


def test_experimental_snapshot_is_separate_and_formal_result_is_false() -> None:
    game = _game(1)
    snapshot = game.execution_snapshot
    assert snapshot["schema"] == EXPERIMENTAL_ACTIVE_RESPONSE_EXECUTION_SCHEMA
    assert snapshot["experimental"] is True
    assert snapshot["formal_result"] is False
    assert snapshot["configuration"] == _configuration().to_dict()
    assert snapshot["pending_response_obligation"] is None
    assert snapshot["production_execution_snapshot"]["schema"] == "production-basic-batch-execution-v2"
    assert game.formal_result_eligible is False


def test_double_dodge_then_pass_consumes_first_and_keeps_root_processing() -> None:
    game = _open_holder_slash_response()
    root = game.runtime.pending_slash
    assert root is not None
    root_id = root.slash_instance_id
    first = _action(game, "play_dodge", card_key=SHAN)
    binding = first.payload
    assert binding["response_obligation_root_card_id"] == root_id
    assert binding["response_obligation_required_count"] == 2
    assert binding["response_obligation_provided_count"] == 0
    assert binding["response_obligation_duel_response_index"] is None
    before_event_count = len(game.events)
    _step_action(game, first)
    obligation = game.pending_response_obligation
    assert obligation is not None
    assert obligation.provided_response_count == 1
    assert obligation.required_response_count == 2
    assert game.phase is ProductionPhase.SLASH_RESPONSE
    assert game.state.location_of(root_id) == PROCESSING_ZONE
    assert game.state.players_by_id[OPPONENT].hp == 4
    events = game.events[before_event_count:]
    assert [event.event_type.value for event in events] == [
        "card_used",
        "card_moved",
        "card_moved",
    ]
    assert events[0].payload["experimental_response_obligation"]["provided_response_count"] == 1
    _step_action(game, _action(game, "pass_slash_response"))
    assert game.pending_response_obligation is None
    assert game.state.players_by_id[OPPONENT].hp == 3


def test_double_dodge_only_cancels_after_second_and_event_order_is_auditable() -> None:
    game = _open_holder_slash_response()
    root = game.runtime.pending_slash
    assert root is not None
    root_id = root.slash_instance_id
    _step_action(game, _action(game, "play_dodge", card_key=SHAN))
    assert game.state.location_of(root_id) == PROCESSING_ZONE
    _step_action(game, _action(game, "play_dodge", card_key=SHAN))
    assert game.pending_response_obligation is None
    assert game.state.location_of(root_id) == DISCARD_PILE
    used = [
        index
        for index, event in enumerate(game.events)
        if event.event_type.value == "card_used" and event.card_key == SHAN
    ]
    cancelled = next(
        index
        for index, event in enumerate(game.events)
        if event.event_type.value == "card_effect_cancelled" and event.card_instance_id == root_id
    )
    finished = next(
        index
        for index, event in enumerate(game.events)
        if event.event_type.value == "card_moved"
        and event.card_instance_id == root_id
        and event.payload.get("destination", {}).get("kind") == "discard_pile"
    )
    assert len(used) >= 2
    assert used[-2] < used[-1] < cancelled < finished


def test_duel_opponent_needs_two_then_holder_needs_one() -> None:
    game = _open_holder_duel()
    duel = game.runtime.pending_duel
    assert duel is not None
    assert game.pending_response_obligation is not None
    assert game.pending_response_obligation.required_response_count == 2
    first = _action(game, "play_slash_for_duel", card_key=SHA)
    assert first.payload["response_obligation_duel_response_index"] == 0
    forged_duel_index = replace(
        first,
        payload={
            **first.payload,
            "response_obligation_duel_response_index": 1,
        },
    )
    before_forged = game.execution_snapshot
    with pytest.raises(InvalidActionError):
        game.step(_DirectController(forged_duel_index))
    assert game.execution_snapshot == before_forged
    _step_action(game, first)
    assert game.runtime.pending_duel == duel
    assert game.pending_response_obligation is not None
    assert game.pending_response_obligation.provided_response_count == 1
    holder_hp = game.state.players_by_id[HOLDER].hp
    opponent_hp = game.state.players_by_id[OPPONENT].hp
    _step_action(game, _action(game, "pass_duel_slash"))
    assert game.state.players_by_id[HOLDER].hp == holder_hp
    assert game.state.players_by_id[OPPONENT].hp == opponent_hp - 1

    game = _open_holder_duel()
    _step_action(game, _action(game, "play_slash_for_duel", card_key=SHA))
    _step_action(game, _action(game, "play_slash_for_duel", card_key=SHA))
    duel = game.runtime.pending_duel
    assert duel is not None
    assert duel.responder_id == HOLDER
    assert duel.response_index == 1
    assert game.pending_response_obligation is not None
    assert game.pending_response_obligation.required_response_count == 1
    _step_action(game, _action(game, "play_slash_for_duel", card_key=SHA))
    duel = game.runtime.pending_duel
    assert duel is not None
    assert duel.responder_id == OPPONENT
    assert duel.response_index == 2
    assert game.pending_response_obligation is not None
    assert game.pending_response_obligation.required_response_count == 2


def test_duel_reverse_direction_holder_still_needs_only_one() -> None:
    game = _game(_seed_opponent_duel_holder_slash())
    _advance_current_player_to_play(game)
    _end_holder_turn(game)
    _step_action(game, _action(game, "use_duel", card_key=DUEL))
    _pass_trick_to_duel(game)
    assert game.current_actor_id == HOLDER
    assert game.pending_response_obligation is not None
    assert game.pending_response_obligation.required_response_count == 1
    _step_action(game, _action(game, "play_slash_for_duel", card_key=SHA))
    assert game.current_actor_id == OPPONENT
    assert game.pending_response_obligation is not None
    assert game.pending_response_obligation.required_response_count == 2


def test_stale_and_forged_response_actions_fail_closed() -> None:
    game = _open_holder_slash_response()
    first = _action(game, "play_dodge", card_key=SHAN)
    _step_action(game, first)
    before = game.execution_snapshot
    with pytest.raises(InvalidActionError):
        game.step(_DirectController(first))
    assert game.execution_snapshot == before
    for field, forged_value in (
        ("response_obligation_id", "aro_forged"),
        ("response_obligation_root_card_id", "forged-root"),
        ("response_obligation_root_card_type", "duel"),
        ("response_obligation_required_count", 1),
        ("response_obligation_provided_count", 99),
        ("response_obligation_duel_response_index", 0),
    ):
        current = _action(game, "play_dodge", card_key=SHAN)
        forged = replace(
            current,
            payload={
                **current.payload,
                field: forged_value,
            },
        )
        with pytest.raises(InvalidActionError):
            game.step(_DirectController(forged))
        assert game.execution_snapshot == before


def test_bagua_is_explicitly_blocked_and_not_enumerated() -> None:
    game = _open_holder_slash_response()
    assert "activate_bagua" not in {
        action.payload.get("operation") for action in game.legal_actions()
    }
    with pytest.raises(UnsupportedRuleError, match="BLOCKED_BY_RULE_SOURCE"):
        game.apply_bagua_activate(game.state, game._context(), _action(game, "pass_slash_response"), object())


class _DoubleDodgeThenReference:
    """Record a natural double-dodge trajectory, then let the reference finish."""

    def __init__(self) -> None:
        self._opened = False
        self._dodge_count = 0
        self._reference = BatchReferenceController()

    def choose(
        self, legal_actions: tuple[LegalAction, ...], context: object
    ) -> LegalAction:
        for action in legal_actions:
            if (
                not self._opened
                and action.payload.get("operation") == "use_slash"
                and action.payload.get("card_key") == SHA
            ):
                self._opened = True
                return action
        for action in legal_actions:
            if action.payload.get("operation") == "play_dodge" and self._dodge_count < 2:
                self._dodge_count += 1
                return action
        return self._reference.choose(legal_actions, context)  # type: ignore[arg-type]


@lru_cache(maxsize=1)
def _strict_record() -> ExperimentalActiveResponseReplay:
    return record_experimental_active_response_replay(
        _seed_holder_slash_opponent_two_dodge(),
        configuration=_configuration(),
        controller=_DoubleDodgeThenReference(),
        max_steps=1000,
    )


def test_strict_replay_rebuilds_experimental_config_skill_and_obligation() -> None:
    record = _strict_record()
    result = reexecute_experimental_active_response_replay(record)
    assert result.verified is True
    raw = record.to_dict()
    raw["header"]["experimental"] = False
    raw["record_sha256"] = sha256_value(
        {key: value for key, value in raw.items() if key != "record_sha256"}
    )
    with pytest.raises(ProductionReplayFormatError):
        ExperimentalActiveResponseReplay.from_dict(raw)

    raw = record.to_dict()
    raw["header"]["configuration"]["skill_profile"]["modifier_owner_id"] = OPPONENT
    raw["record_sha256"] = sha256_value(
        {key: value for key, value in raw.items() if key != "record_sha256"}
    )
    with pytest.raises((ProductionReplayFormatError, ProductionReplayDivergenceError)):
        reexecute_experimental_active_response_replay(raw)


def _with_recomputed_record_digest(raw: dict[str, object]) -> dict[str, object]:
    raw["record_sha256"] = sha256_value(
        {key: value for key, value in raw.items() if key != "record_sha256"}
    )
    return raw


def _tamper_engine_version(raw: dict[str, object]) -> None:
    raw["header"]["engine_version"] = "forged-engine"  # type: ignore[index]


def _tamper_deck_hash(raw: dict[str, object]) -> None:
    raw["header"]["deck_hash"] = "0" * 64  # type: ignore[index]


def _tamper_initial_skill_state(raw: dict[str, object]) -> None:
    raw["header"]["initial_skill_state"]["modifier_active"] = False  # type: ignore[index]


def _tamper_bound_response_payload(raw: dict[str, object]) -> None:
    decision = next(
        item
        for item in raw["decisions"]  # type: ignore[index]
        if item["pending_response_obligation_before"] is not None
    )
    decision["chosen_action"]["payload"]["response_obligation_provided_count"] = 99


def _tamper_event(raw: dict[str, object]) -> None:
    raw["events"][0]["payload"]["reason"] = "forged_initial_hand"  # type: ignore[index]


def _tamper_final_execution_hash(raw: dict[str, object]) -> None:
    raw["outcome"]["final_execution_hash"] = "0" * 64  # type: ignore[index]


@pytest.mark.parametrize(
    "tamper",
    (
        _tamper_engine_version,
        _tamper_deck_hash,
        _tamper_initial_skill_state,
        _tamper_bound_response_payload,
        _tamper_event,
        _tamper_final_execution_hash,
    ),
)
def test_strict_replay_tamper_matrix_fails_closed(
    tamper: object,
) -> None:
    raw = _strict_record().to_dict()
    assert callable(tamper)
    tamper(raw)
    with pytest.raises((ProductionReplayFormatError, ProductionReplayDivergenceError)):
        reexecute_experimental_active_response_replay(
            _with_recomputed_record_digest(raw)
        )
