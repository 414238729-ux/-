# -*- coding: utf-8 -*-
"""POST-B C6：普通八人标准身份 canonical profile、authority 与胜负奖惩。"""

from __future__ import annotations

import copy
from dataclasses import fields, replace
import importlib.util
from pathlib import Path
from typing import Any

import pytest

import scripts.sgs_engine.mode_identity as identity_module
from scripts.sgs_engine.events import EventType
from scripts.sgs_engine.model import DRAW_PILE, PlayerState, ZoneRef
from scripts.sgs_engine.mode_identity import (
    C6_CANONICAL_DRAW_REACHABILITY_STATUS,
    FORMAL_NO_SKILL_IDENTITY_8P_MODE,
    POST_B_C6_FORMAL_IDENTITY_CONTRACT_ID,
    FormalEightPlayerIdentityConfiguration,
    FormalEightPlayerIdentityReadiness,
    FormalEightPlayerIdentitySession,
    FormalIdentityConfiguration,
    FormalIdentityConfigurationError,
    IdentityOutcomePolicy,
    StandardIdentityRole,
    TrustedFormalEightPlayerIdentityConfiguration,
    assert_trusted_formal_eight_player_identity_configuration,
    inspect_formal_eight_player_identity_readiness,
)
from scripts.sgs_engine.multiplayer import PlayerTopology
from scripts.sgs_engine.production_batch import ProductionPhase, _replace_player

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
_SECRET = b"c6-mode-test-session-secret-0001"


def _profile() -> TrustedFormalEightPlayerIdentityConfiguration:
    return FormalEightPlayerIdentityConfiguration.formal_profile()


def _session(
    seed: int = 0, *, analysis_only: bool = False
) -> FormalEightPlayerIdentitySession:
    return FormalEightPlayerIdentitySession(
        seed=seed,
        configuration=_profile(),
        analysis_only=analysis_only,
        session_id=f"c6-mode-{seed}-{int(analysis_only)}",
        session_secret=_SECRET,
    )


def _topology(alive: dict[str, bool]) -> PlayerTopology:
    return PlayerTopology(
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


def _c5_live_scenarios() -> Any:
    """复用 C5 已有强场景驱动，但将唯一 session factory 换成真实 C6。"""

    path = Path(__file__).with_name("test_post_b_c5_identity_mode.py")
    spec = importlib.util.spec_from_file_location(
        "_c6_reused_c5_identity_mode_scenarios", path
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载C5身份强场景：{path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module._session = _session
    return module


@pytest.fixture(scope="module")
def live_scenarios() -> Any:
    return _c5_live_scenarios()


def test_c6_contract_and_exact_canonical_profile() -> None:
    config = _profile()
    assert POST_B_C6_FORMAL_IDENTITY_CONTRACT_ID == (
        "POST_B_C6_FORMAL_NO_SKILL_NORMAL_EIGHT_PLAYER_IDENTITY_MODE"
    )
    assert FORMAL_NO_SKILL_IDENTITY_8P_MODE == "formal_no_skill_identity_8p"
    assert type(config) is TrustedFormalEightPlayerIdentityConfiguration
    assert config.physical_player_ids == PHYSICAL
    assert config.identity_cards == ROLE_CARDS
    assert config.base_hp == config.base_max_hp == 4
    assert config.lord_hp == config.lord_max_hp == 5
    assert config.initial_hand_count == 4
    assert config.hand_qi_ka_allowed is False
    assert config.deck_supply_mode == "reshuffle_draw"
    assert [item.name for item in fields(FormalEightPlayerIdentityConfiguration)] == [
        "physical_player_ids",
        "identity_cards",
        "base_hp",
        "base_max_hp",
        "lord_hp",
        "lord_max_hp",
        "initial_hand_count",
        "hand_qi_ka_allowed",
        "deck_supply_mode",
    ]
    assert config.to_dict()["schema"] == (
        "formal-no-skill-identity-8p-configuration-v1"
    )
    assert_trusted_formal_eight_player_identity_configuration(config)
    assert C6_CANONICAL_DRAW_REACHABILITY_STATUS == (
        "C6_CANONICAL_DRAW_REACHABILITY_UNRESOLVED"
    )


class _DictSubclass(dict[str, object]):
    pass


@pytest.mark.parametrize(
    "factory",
    (
        pytest.param(
            lambda: FormalEightPlayerIdentityConfiguration(base_hp=True),
            id="bool-int-alias",
        ),
        pytest.param(
            lambda: FormalEightPlayerIdentityConfiguration(
                hand_qi_ka_allowed=0  # type: ignore[arg-type]
            ),
            id="false-zero-alias",
        ),
        pytest.param(
            lambda: FormalEightPlayerIdentityConfiguration(lord_hp=5.0),
            id="float-int-alias",
        ),
        pytest.param(
            lambda: FormalEightPlayerIdentityConfiguration(
                physical_player_ids=list(PHYSICAL)  # type: ignore[arg-type]
            ),
            id="list-tuple-alias",
        ),
        pytest.param(
            lambda: FormalEightPlayerIdentityConfiguration(
                identity_cards=(
                    StandardIdentityRole.LORD,
                    *ROLE_CARDS[1:],
                )  # type: ignore[arg-type]
            ),
            id="enum-string-alias",
        ),
        pytest.param(
            lambda: FormalEightPlayerIdentityConfiguration(
                physical_player_ids=("p1", "p1", *PHYSICAL[2:])
            ),
            id="duplicate-physical-id",
        ),
        pytest.param(
            lambda: FormalEightPlayerIdentityConfiguration(
                identity_cards=("lord", "loyalist", *ROLE_CARDS[3:], "spy")
            ),
            id="wrong-role-composition",
        ),
        pytest.param(
            lambda: FormalEightPlayerIdentityConfiguration(
                hand_qi_ka_allowed=True
            ),
            id="hand-reroll",
        ),
        pytest.param(
            lambda: FormalEightPlayerIdentityConfiguration(
                deck_supply_mode="no_reshuffle_draw"
            ),
            id="wrong-deck-supply",
        ),
    ),
)
def test_c6_exact_scalar_container_and_role_types_fail_closed(factory: Any) -> None:
    with pytest.raises(FormalIdentityConfigurationError):
        factory()


def test_c6_recursive_canonical_parser_rejects_alias_extra_missing_null() -> None:
    canonical = _profile().to_dict()
    assert type(
        FormalEightPlayerIdentityConfiguration.from_canonical_profile_value(
            canonical
        )
    ) is TrustedFormalEightPlayerIdentityConfiguration

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
    value["identity_cards"] = None
    attacks.append(value)
    for attack in attacks:
        with pytest.raises(FormalIdentityConfigurationError):
            FormalEightPlayerIdentityConfiguration.from_canonical_profile_value(
                attack
            )

    with pytest.raises(FormalIdentityConfigurationError, match="dict子类"):
        FormalEightPlayerIdentityConfiguration.from_dict(
            _DictSubclass(canonical)
        )
    tuple_payload = dict(canonical)
    tuple_payload["identity_cards"] = tuple(ROLE_CARDS)
    with pytest.raises(FormalIdentityConfigurationError, match="exact JSON数组"):
        FormalEightPlayerIdentityConfiguration.from_dict(tuple_payload)


def test_c6_private_capability_cannot_be_publicly_minted_or_copied() -> None:
    public_trusted = TrustedFormalEightPlayerIdentityConfiguration()
    with pytest.raises(FormalIdentityConfigurationError, match="capability"):
        assert_trusted_formal_eight_player_identity_configuration(public_trusted)
    with pytest.raises(FormalIdentityConfigurationError, match="capability"):
        FormalEightPlayerIdentitySession(
            seed=1,
            configuration=public_trusted,
            analysis_only=False,
        )

    trusted = _profile()
    for reconstructed in (
        copy.copy(trusted),
        copy.deepcopy(trusted),
        replace(trusted),
    ):
        with pytest.raises(FormalIdentityConfigurationError, match="capability"):
            assert_trusted_formal_eight_player_identity_configuration(
                reconstructed
            )

    forged = TrustedFormalEightPlayerIdentityConfiguration()
    object.__setattr__(forged, "_capability_token", object())
    with pytest.raises(FormalIdentityConfigurationError, match="capability"):
        assert_trusted_formal_eight_player_identity_configuration(forged)


def test_c6_subclasses_and_c5_configuration_cannot_cross_authority() -> None:
    class TrustedSub(TrustedFormalEightPlayerIdentityConfiguration):
        pass

    class SessionSub(FormalEightPlayerIdentitySession):
        pass

    with pytest.raises(FormalIdentityConfigurationError, match="exact type"):
        assert_trusted_formal_eight_player_identity_configuration(TrustedSub())
    with pytest.raises(TypeError, match="不允许子类"):
        SessionSub(seed=2, configuration=_profile())
    with pytest.raises(TypeError, match="FormalEightPlayerIdentityConfiguration"):
        FormalEightPlayerIdentitySession(
            seed=2,
            configuration=FormalIdentityConfiguration.formal_profile(),  # type: ignore[arg-type]
        )


def test_c6_analysis_only_untrusted_runs_but_never_formal() -> None:
    untrusted = FormalEightPlayerIdentityConfiguration()
    with pytest.raises(FormalIdentityConfigurationError, match="exact type"):
        FormalEightPlayerIdentitySession(
            seed=3,
            configuration=untrusted,
            analysis_only=False,
        )
    game = FormalEightPlayerIdentitySession(
        seed=3,
        configuration=untrusted,
        analysis_only=True,
        session_id="c6-analysis-untrusted",
        session_secret=_SECRET,
    )
    assert game.analysis_only is True
    assert game.formal_result_eligible is False


def test_c6_initialization_rotation_hp_hands_and_single_rng() -> None:
    game = _session(0)
    assert game.mode_id == FORMAL_NO_SKILL_IDENTITY_8P_MODE
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
    assert game.phase is ProductionPhase.PREPARE
    assert game.seat_by_player == {
        player_id: index
        for index, player_id in enumerate(game.numbered_player_order, start=1)
    }
    assert game.state.players_by_id[lord].hp == 5
    assert game.state.players_by_id[lord].max_hp == 5
    for player_id in PHYSICAL:
        player = game.state.players_by_id[player_id]
        assert player.character is not None
        assert player.character.character_key == "soldier"
        if player_id != lord:
            assert (player.hp, player.max_hp) == (4, 4)
        assert len(game.state.card_ids_in(ZoneRef.hand(player_id))) == 4
    assert len(game.state.card_ids_in(DRAW_PILE)) == 128
    assert not any(
        event.event_type in {EventType.DAMAGE, EventType.HP_RECOVER}
        for event in game.events
    )
    assert [call.method for call in game.rng_calls] == ["shuffle", "shuffle"]
    assert list(game.rng_calls[0].arguments["before"]) == list(ROLE_CARDS)
    assert list(game.rng_calls[1].arguments["before"]).__len__() == 160
    assert all(call.method != "choice" for call in game.rng_calls)
    same = _session(0)
    assert dict(same.identities_by_player) == dict(game.identities_by_player)
    assert [call.to_dict() for call in same.rng_calls] == [
        call.to_dict() for call in game.rng_calls
    ]

    dead = game.numbered_player_order[3]
    original_seats = dict(game.seat_by_player)
    game._state = _replace_player(game.state, dead, hp=0, alive=False)
    assert dict(game.seat_by_player) == original_seats
    assert game.state.players_by_id[dead].seat == original_seats[dead]


def test_c6_special_variant_character_selection_and_server_statistics_absent() -> None:
    game = _session(4)
    forbidden_names = {
        "heir_player_id",
        "current_lord",
        "current_lord_player_id",
        "ambitionist_mark",
        "delayed_identity_transformation",
        "effective_wins",
        "server_score",
        "lord_spy_duel_reward",
        "candidate_pool",
        "lord_skill",
        "character_skill",
    }
    assert all(not hasattr(game, name) for name in forbidden_names)
    assert all(not hasattr(game.mode_policy, name) for name in forbidden_names)
    assert forbidden_names.isdisjoint(game.formal_configuration.to_dict())
    assert {
        role.value for role in game.identities_by_player.values()
    } == {"lord", "loyalist", "rebel", "spy"}


def test_c6_outcome_matrix_shared_standard_semantics() -> None:
    identities = {
        "p1": StandardIdentityRole.LORD,
        "p2": StandardIdentityRole.LOYALIST,
        "p3": StandardIdentityRole.LOYALIST,
        "p4": StandardIdentityRole.REBEL,
        "p5": StandardIdentityRole.REBEL,
        "p6": StandardIdentityRole.REBEL,
        "p7": StandardIdentityRole.REBEL,
        "p8": StandardIdentityRole.SPY,
    }
    policy = IdentityOutcomePolicy(identities)
    assert policy.identity() == "outcome:formal_no_skill_identity_8p"
    assert policy.finish_reason == "identity_victory"
    assert policy.draw_finish_reason == "identity_draw_deck_exhausted"

    alive = {player_id: False for player_id in PHYSICAL}
    alive.update({"p1": True, "p2": True})
    assert policy.resolve_winner_after_death(_topology(alive), "p7") == (
        "lord_and_loyalists"
    )
    alive = {player_id: False for player_id in PHYSICAL}
    alive.update({"p1": True, "p8": True})
    assert policy.resolve_winner_after_death(_topology(alive), "p7") is None
    alive = {player_id: False for player_id in PHYSICAL}
    alive["p8"] = True
    assert policy.resolve_winner_after_death(_topology(alive), "p1") == "spy"
    for remaining in ({"p2"}, {"p4"}, {"p2", "p4"}, set()):
        alive = {player_id: player_id in remaining for player_id in PHYSICAL}
        assert policy.resolve_winner_after_death(_topology(alive), "p1") == (
            "rebels"
        )


@pytest.mark.parametrize(
    "scenario_name",
    (
        "test_real_session_rebels_win_when_lord_dies_with_others",
        "test_spy_death_blocks_later_spy_victory",
        "test_any_identity_killing_rebel_draws_three",
        "test_non_lord_killing_loyalist_has_no_lord_penalty",
        "test_no_damage_source_creates_no_identity_consequence",
        "test_death_context_is_required_and_not_guessed",
    ),
)
def test_c6_live_outcome_and_death_consequence_scenarios(
    live_scenarios: Any, scenario_name: str
) -> None:
    """每个 C5 强驱动在真实 8p session 上重跑；不允许弱路径或提前 return。"""

    getattr(live_scenarios, scenario_name)()


def test_c6_terminal_final_rebel_stops_reward_immediately(
    live_scenarios: Any,
) -> None:
    game = _session(11)
    lord = game.lord_player_id
    spy = live_scenarios._players_of_role(game, StandardIdentityRole.SPY)[0]
    rebels = live_scenarios._players_of_role(game, StandardIdentityRole.REBEL)
    live_scenarios._kill(game, lord, spy)
    assert game.is_finished is False
    for rebel in rebels[:-1]:
        live_scenarios._kill(game, lord, rebel)
        assert game.is_finished is False
    before_events = len(game.events)
    live_scenarios._kill(game, lord, rebels[-1])
    assert game.is_finished is True
    assert game.winner_id == "lord_and_loyalists"
    assert not any(
        event.event_type is EventType.CARD_GAINED
        and event.payload.get("reason") == "identity_kill_rebel_draw"
        for event in game.events[before_events:]
    )


def test_c6_spy_victory_requires_spy_as_unique_survivor_after_lord(
    live_scenarios: Any,
) -> None:
    game = _session(21)
    lord = game.lord_player_id
    spy = live_scenarios._players_of_role(game, StandardIdentityRole.SPY)[0]
    rebels = live_scenarios._players_of_role(game, StandardIdentityRole.REBEL)
    loyalists = live_scenarios._players_of_role(
        game, StandardIdentityRole.LOYALIST
    )
    for victim in (*rebels, *loyalists):
        live_scenarios._kill(game, spy, victim)
        assert game.is_finished is False
    live_scenarios._kill(game, spy, lord)
    assert game.is_finished is True
    assert game.winner_id == "spy"


def test_c6_checks_outcome_after_each_of_four_rebel_deaths(
    live_scenarios: Any,
) -> None:
    game = _session(51)
    lord = game.lord_player_id
    spy = live_scenarios._players_of_role(game, StandardIdentityRole.SPY)[0]
    rebels = live_scenarios._players_of_role(game, StandardIdentityRole.REBEL)
    live_scenarios._kill(game, lord, spy)
    assert game.winner_id is None
    winners: list[str | None] = []
    for rebel in rebels:
        live_scenarios._kill(game, lord, rebel)
        winners.append(game.winner_id)
    assert winners[:-1] == [None, None, None]
    assert winners[-1] == "lord_and_loyalists"


def test_c6_lord_kills_loyalist_discards_hand_equipment_retains_judgment(
    live_scenarios: Any,
) -> None:
    from scripts.sgs_engine.model import DISCARD_PILE

    game = _session(71)
    lord = game.lord_player_id
    loyalists = live_scenarios._players_of_role(
        game, StandardIdentityRole.LOYALIST
    )
    loyalist = min(
        loyalists,
        key=lambda player_id: game.topology.base_seat_distance(lord, player_id),
    )
    assert game.phase is ProductionPhase.PREPARE
    live_scenarios._enter_play(game)
    delayed = live_scenarios._give_card(game, lord, "sgs_delayed_lebusi")
    game._state = game.state.move_card(delayed, ZoneRef.judgment(lord))
    weapon = live_scenarios._give_card(
        game, lord, "sgs_weapon_qinglongyanyuedao"
    )
    game._state = game.state.move_card(
        weapon, ZoneRef.equipment(lord, "weapon")
    )
    live_scenarios._kill(game, lord, loyalist)
    assert game.is_finished is False
    assert game.state.card_ids_in(ZoneRef.hand(lord)) == ()
    assert game.state.card_ids_in(ZoneRef.equipment(lord, "weapon")) == ()
    assert delayed in game.state.card_ids_in(ZoneRef.judgment(lord))
    assert game.state.location_of(weapon) == DISCARD_PILE


def test_c6_readiness_probes_analysis_and_trusted_runtime() -> None:
    readiness = inspect_formal_eight_player_identity_readiness()
    assert isinstance(readiness, FormalEightPlayerIdentityReadiness)
    assert readiness.contract_id == POST_B_C6_FORMAL_IDENTITY_CONTRACT_ID
    assert readiness.mode_id == FORMAL_NO_SKILL_IDENTITY_8P_MODE
    assert readiness.deck_count == 160
    assert readiness.registered_card_key_count == 38
    assert readiness.registered_instance_count == 160
    assert readiness.global_card_semantics_complete is True
    assert readiness.mode_runtime_reachable is True
    assert readiness.formal_trusted_runtime_reachable is True
    assert readiness.reexecution_replay_supported is True
    assert readiness.unsupported_rules == 0
    assert readiness.approximation_count == 0
    assert readiness.formal_eight_player_identity_no_skill_ready is True
    assert readiness.identity_8p_ready is True
    assert readiness.multi_player_production_proven is False
    assert readiness.authoritative_full_game_core is False
    assert readiness.blockers == ()


def test_c6_readiness_fails_when_only_trusted_path_breaks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_init = FormalEightPlayerIdentitySession.__init__

    def fail_trusted(
        self: FormalEightPlayerIdentitySession,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        if kwargs.get("analysis_only") is False:
            raise FormalIdentityConfigurationError("trusted-only failure")
        original_init(self, *args, **kwargs)

    monkeypatch.setattr(
        identity_module.FormalEightPlayerIdentitySession,
        "__init__",
        fail_trusted,
    )
    readiness = inspect_formal_eight_player_identity_readiness()
    assert readiness.mode_runtime_reachable is True
    assert readiness.formal_trusted_runtime_reachable is False
    assert readiness.formal_eight_player_identity_no_skill_ready is False
    assert readiness.identity_8p_ready is False
    assert any(
        blocker.code
        == "FORMAL_EIGHT_PLAYER_IDENTITY_TRUSTED_RUNTIME_UNREACHABLE"
        for blocker in readiness.blockers
    )
