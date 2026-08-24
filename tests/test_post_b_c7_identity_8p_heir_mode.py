# -*- coding: utf-8 -*-
"""POST-B C7：立储择途八人 exact façade、开局、胜负矩阵与变体机制。"""

from __future__ import annotations

import copy
from dataclasses import fields, replace
from typing import Any

import pytest

import scripts.sgs_engine.mode_identity_heir as heir_module
from scripts.sgs_engine.events import EventType
from scripts.sgs_engine.model import DRAW_PILE, PlayerState, ZoneRef
from scripts.sgs_engine.mode_identity import (
    FORMAL_NO_SKILL_IDENTITY_8P_MODE,
    FormalEightPlayerIdentityConfiguration,
    FormalEightPlayerIdentitySession,
    FormalIdentityConfigurationError,
    StandardIdentityRole,
)
from scripts.sgs_engine.mode_identity_heir import (
    C7_CANONICAL_DRAW_REACHABILITY_STATUS,
    FORMAL_NO_SKILL_IDENTITY_8P_HEIR_MODE,
    MOBILE_8P_HEIR_AND_SPY_CHOICE_VARIANT,
    POST_B_C7_FORMAL_IDENTITY_CONTRACT_ID,
    FormalHeirAndSpyChoiceIdentityConfiguration,
    FormalHeirAndSpyChoiceIdentityReadiness,
    FormalHeirAndSpyChoiceIdentitySession,
    HeirAndSpyChoiceOutcomePolicy,
    HeirAndSpyChoiceRole,
    TrustedFormalHeirAndSpyChoiceIdentityConfiguration,
    assert_trusted_formal_heir_and_spy_choice_identity_configuration,
    inspect_formal_heir_and_spy_choice_identity_readiness,
)
from scripts.sgs_engine.multiplayer import PlayerTopology
from scripts.sgs_engine.production_batch import (
    BatchActionIdController,
    ProductionPhase,
    _replace_player,
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
_SECRET = b"c7-mode-test-session-secret-0001"


def _profile() -> TrustedFormalHeirAndSpyChoiceIdentityConfiguration:
    return FormalHeirAndSpyChoiceIdentityConfiguration.formal_profile()


def _session(
    seed: int = 0, *, analysis_only: bool = False
) -> FormalHeirAndSpyChoiceIdentitySession:
    return FormalHeirAndSpyChoiceIdentitySession(
        seed=seed,
        configuration=_profile(),
        analysis_only=analysis_only,
        session_id=f"c7-mode-{seed}-{int(analysis_only)}",
        session_secret=_SECRET,
    )


def _topology(
    alive: dict[str, bool],
    roles: dict[str, str] | None = None,
) -> tuple[PlayerTopology, HeirAndSpyChoiceOutcomePolicy]:
    identities = roles or {
        "p1": "lord",
        "p2": "loyalist",
        "p3": "loyalist",
        "p4": "rebel",
        "p5": "rebel",
        "p6": "rebel",
        "p7": "rebel",
        "p8": "spy",
    }
    topology = PlayerTopology(
        players=tuple(
            PlayerState(
                player_id=player_id,
                seat=index,
                hp=4 if alive.get(player_id, True) else 0,
                max_hp=4,
                alive=alive.get(player_id, True),
            )
            for index, player_id in enumerate(PHYSICAL, start=1)
        )
    )
    lord = next(
        player_id for player_id, role in identities.items() if role == "lord"
    )
    # 若当前主公已死亡，仍用 identities 中的 lord 作为 current_lord。
    policy = HeirAndSpyChoiceOutcomePolicy(identities, lord)
    return topology, policy


def _step(game: FormalHeirAndSpyChoiceIdentitySession | Any, operation: str) -> None:
    for action in game.legal_actions():
        if action.payload.get("operation") == operation:
            game.step(BatchActionIdController(action.action_id))
            return
    raise AssertionError(
        f"缺少 {operation!r}: "
        f"{[item.payload.get('operation') for item in game.legal_actions()]}"
        f" phase={game.phase}"
    )


def _pass_mode(game: FormalHeirAndSpyChoiceIdentitySession) -> None:
    while game.phase is ProductionPhase.MODE_DECISION:
        _step(game, "pass_mode_decision")


def _enter_play(game: FormalHeirAndSpyChoiceIdentitySession) -> None:
    _pass_mode(game)
    for operation in ("proceed_prepare", "proceed_judgment", "proceed_draw"):
        _step(game, operation)
        _pass_mode(game)


def _end_turn(game: FormalHeirAndSpyChoiceIdentitySession) -> None:
    _pass_mode(game)
    if game.phase is ProductionPhase.PLAY:
        _step(game, "end_play_phase")
        _pass_mode(game)
    while game.phase is ProductionPhase.DISCARD:
        operations = [
            action.payload.get("operation") for action in game.legal_actions()
        ]
        if "discard_phase_submit" in operations:
            _step(game, "discard_phase_submit")
        else:
            _step(game, "select_discard_card")
        _pass_mode(game)
    if game.phase is ProductionPhase.END:
        _step(game, "end_turn")


def _operations(game: FormalHeirAndSpyChoiceIdentitySession) -> set[object]:
    return {action.payload.get("operation") for action in game.legal_actions()}


def _give_card(
    game: FormalHeirAndSpyChoiceIdentitySession, player_id: str, card_key: str
) -> str:
    for instance_id, card in game.state.cards_by_id.items():
        if card.card_key != card_key:
            continue
        destination = ZoneRef.hand(player_id)
        if game.state.location_of(instance_id) != destination:
            game._state = game.state.move_card(instance_id, destination)
        return instance_id
    raise AssertionError(card_key)


def test_c7_contract_and_exact_canonical_profile() -> None:
    config = _profile()
    assert POST_B_C7_FORMAL_IDENTITY_CONTRACT_ID == (
        'POST_B_C7_FORMAL_NO_SKILL_MOBILE_EIGHT_PLAYER_HEIR_AND_SPY_CHOICE_IDENTITY_MODE'
    )
    assert len(POST_B_C7_FORMAL_IDENTITY_CONTRACT_ID) == 79
    assert FORMAL_NO_SKILL_IDENTITY_8P_HEIR_MODE == (
        "formal_no_skill_identity_8p_heir_and_spy_choice"
    )
    assert MOBILE_8P_HEIR_AND_SPY_CHOICE_VARIANT == (
        "mobile_8p_heir_and_spy_choice"
    )
    assert type(config) is TrustedFormalHeirAndSpyChoiceIdentityConfiguration
    assert config.physical_player_ids == PHYSICAL
    assert config.identity_cards == ROLE_CARDS
    assert config.mode_id == FORMAL_NO_SKILL_IDENTITY_8P_HEIR_MODE
    assert config.variant_id == MOBILE_8P_HEIR_AND_SPY_CHOICE_VARIANT
    assert config.deck_id == "sgs_mobile_non_special_20260725_unofficial"
    assert config.deck_supply_mode == "reshuffle_draw"
    assert [
        item.name
        for item in fields(FormalHeirAndSpyChoiceIdentityConfiguration)
    ] == [
        "physical_player_ids",
        "identity_cards",
        "base_hp",
        "base_max_hp",
        "lord_hp",
        "lord_max_hp",
        "initial_hand_count",
        "hand_qi_ka_allowed",
        "deck_supply_mode",
        "deck_id",
        "mode_id",
        "variant_id",
    ]
    assert config.to_dict()["schema"] == (
        "formal-no-skill-identity-8p-heir-and-spy-choice-configuration-v1"
    )
    assert_trusted_formal_heir_and_spy_choice_identity_configuration(config)
    assert C7_CANONICAL_DRAW_REACHABILITY_STATUS == (
        "C7_CANONICAL_DRAW_REACHABILITY_UNRESOLVED"
    )


class _DictSubclass(dict[str, object]):
    pass


@pytest.mark.parametrize(
    "factory",
    (
        pytest.param(
            lambda: FormalHeirAndSpyChoiceIdentityConfiguration(base_hp=True),
            id="bool-int-alias",
        ),
        pytest.param(
            lambda: FormalHeirAndSpyChoiceIdentityConfiguration(
                hand_qi_ka_allowed=0  # type: ignore[arg-type]
            ),
            id="false-zero-alias",
        ),
        pytest.param(
            lambda: FormalHeirAndSpyChoiceIdentityConfiguration(lord_hp=5.0),
            id="float-int-alias",
        ),
        pytest.param(
            lambda: FormalHeirAndSpyChoiceIdentityConfiguration(
                physical_player_ids=list(PHYSICAL)  # type: ignore[arg-type]
            ),
            id="list-tuple-alias",
        ),
        pytest.param(
            lambda: FormalHeirAndSpyChoiceIdentityConfiguration(
                identity_cards=(
                    StandardIdentityRole.LORD,
                    *ROLE_CARDS[1:],
                )  # type: ignore[arg-type]
            ),
            id="enum-string-alias",
        ),
        pytest.param(
            lambda: FormalHeirAndSpyChoiceIdentityConfiguration(
                physical_player_ids=("p1", "p1", *PHYSICAL[2:])
            ),
            id="duplicate-physical-id",
        ),
        pytest.param(
            lambda: FormalHeirAndSpyChoiceIdentityConfiguration(
                identity_cards=("lord", "loyalist", *ROLE_CARDS[3:], "spy")
            ),
            id="wrong-role-composition",
        ),
        pytest.param(
            lambda: FormalHeirAndSpyChoiceIdentityConfiguration(
                identity_cards=(
                    "lord",
                    "loyalist",
                    "loyalist",
                    "rebel",
                    "rebel",
                    "rebel",
                    "spy",
                    "spy",
                )
            ),
            id="two-spy",
        ),
        pytest.param(
            lambda: FormalHeirAndSpyChoiceIdentityConfiguration(
                variant_id="standard_8p_identity"
            ),
            id="wrong-variant",
        ),
        pytest.param(
            lambda: FormalHeirAndSpyChoiceIdentityConfiguration(
                mode_id=FORMAL_NO_SKILL_IDENTITY_8P_MODE
            ),
            id="c6-mode-id",
        ),
    ),
)
def test_c7_exact_scalar_container_and_role_types_fail_closed(factory: Any) -> None:
    with pytest.raises(FormalIdentityConfigurationError):
        factory()


def test_c7_recursive_canonical_parser_rejects_alias_extra_missing_null() -> None:
    canonical = _profile().to_dict()
    assert type(
        FormalHeirAndSpyChoiceIdentityConfiguration.from_canonical_profile_value(
            canonical
        )
    ) is TrustedFormalHeirAndSpyChoiceIdentityConfiguration

    attacks: list[dict[str, object]] = []
    value = dict(canonical)
    value["base_hp"] = True
    attacks.append(value)
    value = dict(canonical)
    value["physical_player_ids"] = tuple(PHYSICAL)
    attacks.append(value)
    value = dict(canonical)
    value["extra"] = False
    attacks.append(value)
    value = dict(canonical)
    del value["identity_cards"]
    attacks.append(value)
    value = dict(canonical)
    value["schema"] = "formal-no-skill-identity-8p-configuration-v1"
    attacks.append(value)
    for attack in attacks:
        with pytest.raises(FormalIdentityConfigurationError):
            FormalHeirAndSpyChoiceIdentityConfiguration.from_canonical_profile_value(
                attack
            )
    with pytest.raises(FormalIdentityConfigurationError, match="dict子类"):
        FormalHeirAndSpyChoiceIdentityConfiguration.from_dict(
            _DictSubclass(canonical)
        )


def test_c7_private_capability_cannot_be_publicly_minted_or_copied() -> None:
    public_trusted = TrustedFormalHeirAndSpyChoiceIdentityConfiguration()
    with pytest.raises(FormalIdentityConfigurationError, match="capability"):
        assert_trusted_formal_heir_and_spy_choice_identity_configuration(
            public_trusted
        )
    trusted = _profile()
    for reconstructed in (
        copy.copy(trusted),
        copy.deepcopy(trusted),
        replace(trusted),
    ):
        with pytest.raises(FormalIdentityConfigurationError, match="capability"):
            assert_trusted_formal_heir_and_spy_choice_identity_configuration(
                reconstructed
            )


def test_c7_subclasses_and_c6_configuration_cannot_cross_authority() -> None:
    class TrustedSub(TrustedFormalHeirAndSpyChoiceIdentityConfiguration):
        pass

    class SessionSub(FormalHeirAndSpyChoiceIdentitySession):
        pass

    with pytest.raises(FormalIdentityConfigurationError, match="exact type"):
        assert_trusted_formal_heir_and_spy_choice_identity_configuration(
            TrustedSub()
        )
    with pytest.raises(TypeError, match="不允许子类"):
        SessionSub(seed=2, configuration=_profile())
    with pytest.raises(TypeError, match="FormalHeirAndSpyChoice"):
        FormalHeirAndSpyChoiceIdentitySession(
            seed=2,
            configuration=FormalEightPlayerIdentityConfiguration.formal_profile(),  # type: ignore[arg-type]
        )


def test_c7_analysis_only_untrusted_runs_but_never_formal() -> None:
    untrusted = FormalHeirAndSpyChoiceIdentityConfiguration()
    with pytest.raises(FormalIdentityConfigurationError, match="exact type"):
        FormalHeirAndSpyChoiceIdentitySession(
            seed=3,
            configuration=untrusted,
            analysis_only=False,
        )
    game = FormalHeirAndSpyChoiceIdentitySession(
        seed=3,
        configuration=untrusted,
        analysis_only=True,
        session_id="c7-analysis-untrusted",
        session_secret=_SECRET,
    )
    assert game.analysis_only is True
    assert game.formal_result_eligible is False


def test_c7_initialization_rotation_hp_hands_and_single_rng() -> None:
    game = _session(0)
    assert game.mode_id == FORMAL_NO_SKILL_IDENTITY_8P_HEIR_MODE
    assert game.variant_id == MOBILE_8P_HEIR_AND_SPY_CHOICE_VARIANT
    assert game.state.deck_id == "sgs_mobile_non_special_20260725_unofficial"
    assert game.physical_player_ids == PHYSICAL
    roles = [game.identities_by_player[player_id] for player_id in PHYSICAL]
    assert roles.count(StandardIdentityRole.LORD) == 1
    assert roles.count(StandardIdentityRole.LOYALIST) == 2
    assert roles.count(StandardIdentityRole.REBEL) == 4
    assert roles.count(StandardIdentityRole.SPY) == 1
    lord = game.lord_player_id
    lord_index = PHYSICAL.index(lord)
    assert game.numbered_player_order == PHYSICAL[lord_index:] + PHYSICAL[:lord_index]
    assert game.first_player_id == lord
    assert game.current_player_id == lord
    assert game.original_lord_player_id == lord
    assert game.current_lord_player_id == lord
    assert dict(game.role_original) == dict(game.role_current)
    assert game.seat_by_player[lord] == 1
    assert game.state.players_by_id[lord].hp == 5
    assert game.state.players_by_id[lord].max_hp == 5
    for player_id in PHYSICAL:
        if player_id != lord:
            player = game.state.players_by_id[player_id]
            assert (player.hp, player.max_hp) == (4, 4)
        assert len(game.state.card_ids_in(ZoneRef.hand(player_id))) == 4
    assert len(game.state.card_ids_in(DRAW_PILE)) == 128
    assert len(game.rng_calls) == 2
    assert game.rng_calls[0].method == "shuffle"
    assert game.rng_calls[1].method == "shuffle"
    assert game._variant.heir_player_id is None


def test_c6_standard_mode_never_creates_heir_or_ambitionist_state() -> None:
    game = FormalEightPlayerIdentitySession(
        seed=0,
        configuration=FormalEightPlayerIdentityConfiguration.formal_profile(),
        analysis_only=False,
        session_id="c7-c6-isolation",
        session_secret=_SECRET,
    )
    assert game.mode_id == FORMAL_NO_SKILL_IDENTITY_8P_MODE
    assert not hasattr(game, "_variant")
    assert game.phase is ProductionPhase.PREPARE
    c7_ops = {"select_heir", "choose_spy_path", "pass_mode_decision"}
    for operation in ("proceed_prepare", "proceed_judgment", "proceed_draw"):
        operations = {
            action.payload.get("operation") for action in game.legal_actions()
        }
        assert operations.isdisjoint(c7_ops)
        _step(game, operation)
    operations = {action.payload.get("operation") for action in game.legal_actions()}
    assert operations.isdisjoint(c7_ops)
    assert game.phase is ProductionPhase.PLAY
    assert not hasattr(game, "_variant")
    assert getattr(game.runtime, "pending_mode_decision", None) is None


def test_c7_outcome_matrix_uses_current_lord_and_role_current() -> None:
    alive = {player_id: True for player_id in PHYSICAL}
    topology, policy = _topology(alive)
    assert policy.resolve_winner_after_death(topology, "p4") is None

    alive = {player_id: player_id in {"p1", "p2"} for player_id in PHYSICAL}
    topology, policy = _topology(alive)
    assert policy.resolve_winner_after_death(topology, "p8") == "lord_and_loyalists"

    identities = {
        "p1": "lord",
        "p2": "loyalist",
        "p3": "loyalist",
        "p4": "rebel",
        "p5": "rebel",
        "p6": "rebel",
        "p7": "rebel",
        "p8": "ambitionist",
    }
    alive = {player_id: player_id in {"p1", "p8"} for player_id in PHYSICAL}
    topology, policy = _topology(alive, identities)
    assert policy.resolve_winner_after_death(topology, "p4") is None
    alive = {player_id: player_id == "p8" for player_id in PHYSICAL}
    topology, policy = _topology(alive, identities)
    assert policy.resolve_winner_after_death(topology, "p1") == "ambitionist"

    identities["p8"] = "spy"
    alive = {player_id: player_id == "p8" for player_id in PHYSICAL}
    topology, policy = _topology(alive, identities)
    assert policy.resolve_winner_after_death(topology, "p1") == "spy"

    alive = {player_id: False for player_id in PHYSICAL}
    topology, policy = _topology(alive, identities)
    assert policy.resolve_winner_after_death(topology, "p1") == "rebels"


def test_c7_lord_selects_heir_on_another_players_turn() -> None:
    game = _session(0)
    lord = game.lord_player_id
    other = game.numbered_player_order[1]
    _enter_play(game)
    _end_turn(game)
    assert game.current_player_id == other
    assert game.phase is ProductionPhase.MODE_DECISION
    assert game.current_actor_id == lord
    target = other
    chosen = None
    for action in game.legal_actions():
        if (
            action.payload.get("operation") == "select_heir"
            and action.payload.get("target_id") == target
        ):
            chosen = action
            break
    assert chosen is not None
    game.step(BatchActionIdController(chosen.action_id))
    assert game._variant.heir_player_id == target
    assert game._variant.heir_selection_used is True
    assert game.role_current[target] == game.role_original[target]
    assert not any(
        event.event_type is EventType.IDENTITY_REVEALED
        and event.payload.get("reason") not in {"initial_lord_reveal"}
        for event in game.events
    )
    assert game.current_player_id == other


def test_c7_heir_window_closes_at_second_round_first_normal_turn() -> None:
    game = _session(0)
    _enter_play(game)
    _end_turn(game)
    guard = 0
    while game._variant.round_number < 2:
        _pass_mode(game)
        if game.phase is ProductionPhase.PREPARE:
            _enter_play(game)
        _end_turn(game)
        guard += 1
        assert guard < 40
    assert game._variant.round_number >= 2
    assert game._variant.heir_window_open is False
    _pass_mode(game)
    operations = [action.payload.get("operation") for action in game.legal_actions()]
    assert "select_heir" not in operations


def test_c7_readiness_probes_analysis_and_trusted_runtime() -> None:
    readiness = inspect_formal_heir_and_spy_choice_identity_readiness()
    assert isinstance(readiness, FormalHeirAndSpyChoiceIdentityReadiness)
    assert readiness.contract_id == POST_B_C7_FORMAL_IDENTITY_CONTRACT_ID
    assert readiness.contract_id == (
        'POST_B_C7_FORMAL_NO_SKILL_MOBILE_EIGHT_PLAYER_HEIR_AND_SPY_CHOICE_IDENTITY_MODE'
    )
    assert len(readiness.contract_id) == 79
    assert readiness.mode_id == FORMAL_NO_SKILL_IDENTITY_8P_HEIR_MODE
    assert readiness.variant_id == MOBILE_8P_HEIR_AND_SPY_CHOICE_VARIANT
    assert readiness.deck_count == 160
    assert readiness.registered_card_key_count == 38
    assert readiness.registered_instance_count == 160
    assert readiness.global_card_semantics_complete is True
    assert readiness.mode_runtime_reachable is True
    assert readiness.formal_trusted_runtime_reachable is True
    assert readiness.reexecution_replay_supported is True
    assert readiness.unsupported_rules == 0
    assert readiness.approximation_count == 0
    assert readiness.formal_heir_and_spy_choice_identity_no_skill_ready is True
    assert readiness.identity_8p_heir_ready is True
    assert readiness.multi_player_production_proven is False
    assert readiness.authoritative_full_game_core is False
    assert readiness.blockers == ()


def test_c7_ambitionist_skills_inactive_when_two_alive() -> None:
    game = _session(0)
    spy = next(
        player_id
        for player_id, role in game.role_current.items()
        if role == "spy"
    )
    game._variant.role_current[spy] = HeirAndSpyChoiceRole.AMBITIONIST.value
    game._sync_outcome_policy()
    for player_id in PHYSICAL:
        if player_id not in {game.current_lord_player_id, spy}:
            game._state = _replace_player(game.state, player_id, hp=0, alive=False)
    policy = game.mode_policy
    assert policy.slash_limit(spy) == 1
    assert policy.bahu_prepare_draw(spy) is False
    assert policy.feiyang_available(player_id=spy, seat=2, turn_number=1) is False
    game._state = _replace_player(
        game.state, game.numbered_player_order[1], hp=4, alive=True
    )
    assert policy.slash_limit(spy) == 2
    assert policy.bahu_prepare_draw(spy) is True


def test_c7_lord_can_select_heir_during_another_players_non_prepare_phase() -> None:
    game = _session(0)
    lord = game.lord_player_id
    other = game.numbered_player_order[1]
    turn_before = game.runtime.turn_number
    _enter_play(game)
    _end_turn(game)
    assert game.current_player_id == other
    assert game.phase is ProductionPhase.MODE_DECISION
    _pass_mode(game)
    assert game.phase is ProductionPhase.PREPARE
    assert game.current_player_id == other
    _step(game, "proceed_prepare")
    assert game.phase is ProductionPhase.MODE_DECISION
    pending = game.runtime.pending_mode_decision
    assert pending is not None
    assert pending.actor_id == lord
    assert pending.resume_phase is ProductionPhase.JUDGMENT
    assert game.current_player_id == other
    assert game.current_actor_id == lord
    chosen = None
    for action in game.legal_actions():
        if (
            action.payload.get("operation") == "select_heir"
            and action.payload.get("target_id") == other
        ):
            chosen = action
            break
    assert chosen is not None
    game.step(BatchActionIdController(chosen.action_id))
    assert game._variant.heir_player_id == other
    assert game._variant.heir_selection_used is True
    assert game.phase is ProductionPhase.JUDGMENT
    assert game.current_player_id == other
    assert game.runtime.turn_number == turn_before + 1
    assert game.runtime.pending_mode_decision is None
    assert game._variant.is_extra_turn is False


def test_c7_lord_can_select_heir_during_own_judgment_after_defer() -> None:
    game = _session(0)
    lord = game.lord_player_id
    other = game.numbered_player_order[1]
    assert game.current_player_id == lord
    assert game.phase is ProductionPhase.MODE_DECISION
    pending = game.runtime.pending_mode_decision
    assert pending is not None
    assert pending.actor_id == lord
    assert pending.resume_phase is ProductionPhase.PREPARE
    assert "select_heir" in _operations(game)
    _pass_mode(game)
    assert game.phase is ProductionPhase.PREPARE
    assert game.current_player_id == lord
    assert "select_heir" not in _operations(game)
    assert "pass_mode_decision" not in _operations(game)
    _step(game, "proceed_prepare")
    assert game.phase is ProductionPhase.MODE_DECISION
    pending = game.runtime.pending_mode_decision
    assert pending is not None
    assert pending.actor_id == lord
    assert pending.resume_phase is ProductionPhase.JUDGMENT
    assert game.current_player_id == lord
    assert game.current_actor_id == lord
    assert "select_heir" in _operations(game)
    assert "proceed_judgment" not in _operations(game)
    chosen = None
    for action in game.legal_actions():
        if (
            action.payload.get("operation") == "select_heir"
            and action.payload.get("target_id") == other
        ):
            chosen = action
            break
    assert chosen is not None
    _step(game, "pass_mode_decision")
    assert game._variant.heir_selection_used is False
    assert game.phase is ProductionPhase.JUDGMENT
    assert game.current_player_id == lord
    assert game.current_actor_id == lord
    assert "proceed_judgment" in _operations(game)
    assert "select_heir" not in _operations(game)
    assert "pass_mode_decision" not in _operations(game)


def test_c7_lord_can_select_heir_during_own_draw_after_defer() -> None:
    game = _session(0)
    lord = game.lord_player_id
    other = game.numbered_player_order[1]
    assert game.current_player_id == lord
    _pass_mode(game)
    _step(game, "proceed_prepare")
    _pass_mode(game)
    assert game.phase is ProductionPhase.JUDGMENT
    _step(game, "proceed_judgment")
    assert game.phase is ProductionPhase.MODE_DECISION
    pending = game.runtime.pending_mode_decision
    assert pending is not None
    assert pending.actor_id == lord
    assert pending.resume_phase is ProductionPhase.DRAW
    assert game.current_player_id == lord
    assert game.current_actor_id == lord
    assert "select_heir" in _operations(game)
    assert "proceed_draw" not in _operations(game)
    chosen = None
    for action in game.legal_actions():
        if (
            action.payload.get("operation") == "select_heir"
            and action.payload.get("target_id") == other
        ):
            chosen = action
            break
    assert chosen is not None
    game.step(BatchActionIdController(chosen.action_id))
    assert game._variant.heir_player_id == other
    assert game._variant.heir_selection_used is True
    assert game.phase is ProductionPhase.DRAW
    assert game.current_player_id == lord
    assert game.runtime.pending_mode_decision is None
    assert "proceed_draw" in _operations(game)
    assert "select_heir" not in _operations(game)
    assert "pass_mode_decision" not in _operations(game)


def test_c7_lord_checkpoint_reopens_after_other_player_ordinary_play_action() -> None:
    game = _session(0)
    lord = game.lord_player_id
    other = game.numbered_player_order[1]
    _enter_play(game)
    _end_turn(game)
    assert game.current_player_id == other
    _enter_play(game)
    assert game.phase is ProductionPhase.PLAY
    assert game.current_player_id == other
    assert game.current_actor_id == other
    play_ops = _operations(game)
    assert "pass_mode_decision" not in play_ops
    assert "select_heir" not in play_ops
    assert "end_play_phase" in play_ops
    weapon_id = _give_card(game, other, "sgs_weapon_qinglongyanyuedao")
    ordinary = None
    for action in game.legal_actions():
        if (
            action.payload.get("operation") == "use_weapon"
            and action.card_instance_id == weapon_id
        ):
            ordinary = action
            break
    assert ordinary is not None
    assert ordinary.payload.get("operation") == "use_weapon"
    assert ordinary.payload.get("operation") != "pass_mode_decision"
    game.step(BatchActionIdController(ordinary.action_id))
    assert any(
        event.event_type is EventType.EQUIPMENT_EQUIPPED
        and event.card_instance_id == weapon_id
        for event in game.events
    )
    assert game.phase is ProductionPhase.MODE_DECISION
    pending = game.runtime.pending_mode_decision
    assert pending is not None
    assert pending.actor_id == lord
    assert pending.resume_phase is ProductionPhase.PLAY
    assert game.current_player_id == other
    assert game.current_actor_id == lord
    assert "select_heir" in _operations(game)
    assert "use_weapon" not in _operations(game)
    assert "end_play_phase" not in _operations(game)
    _pass_mode(game)
    assert game.phase is ProductionPhase.PLAY
    assert game.current_player_id == other
    assert game.current_actor_id == other
    resumed_ops = _operations(game)
    assert "end_play_phase" in resumed_ops
    assert "pass_mode_decision" not in resumed_ops
    assert "select_heir" not in resumed_ops


def test_c7_mode_decision_pass_does_not_reopen_without_game_progress() -> None:
    game = _session(0)
    lord = game.lord_player_id
    assert game.current_player_id == lord
    assert game.phase is ProductionPhase.MODE_DECISION
    pending = game.runtime.pending_mode_decision
    assert pending is not None
    assert isinstance(pending.window_id, str) and pending.window_id
    _step(game, "pass_mode_decision")
    assert game.phase is ProductionPhase.PREPARE
    assert game.runtime.pending_mode_decision is None
    first_ops = _operations(game)
    assert "proceed_prepare" in first_ops
    assert "pass_mode_decision" not in first_ops
    assert "select_heir" not in first_ops
    assert game.phase is ProductionPhase.PREPARE
    assert _operations(game) == first_ops
    assert game.runtime.pending_mode_decision is None

    other = game.numbered_player_order[1]
    _enter_play(game)
    _end_turn(game)
    assert game.current_player_id == other
    assert game.phase is ProductionPhase.MODE_DECISION
    _enter_play(game)
    assert game.phase is ProductionPhase.PLAY
    assert game.current_player_id == other
    play_ops = _operations(game)
    assert "pass_mode_decision" not in play_ops
    assert "select_heir" not in play_ops
    assert "end_play_phase" in play_ops
    assert game.phase is ProductionPhase.PLAY
    assert _operations(game) == play_ops
    assert game.runtime.pending_mode_decision is None
