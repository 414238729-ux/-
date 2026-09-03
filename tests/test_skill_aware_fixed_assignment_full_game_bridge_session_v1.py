# -*- coding: utf-8 -*-
"""BRIDGE-B production-session integration and initialization matrix."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from scripts.sgs_engine import skill_aware_fixed_assignment_full_game_bridge as bridge
from scripts.sgs_engine.events import EventType
from scripts.sgs_engine.formal_duel import (
    FormalDuelConfiguration,
    FormalNoSkillDuelSession,
)
from scripts.sgs_engine.model import (
    DISCARD_PILE,
    DRAW_PILE,
    PROCESSING_ZONE,
    REVEALED_ZONE,
    CharacterGender,
    ZoneRef,
)
from scripts.sgs_engine.multiplayer import DuelOutcomePolicy
from scripts.sgs_engine.production_batch import ProductionBatchError, ProductionPhase


EXPECTED_GENERAL_AUTHORITY = {
    "shamoke": (4, 4, CharacterGender.MALE, ("sgs_skill_jili",)),
    "zhugezhan": (
        3,
        3,
        CharacterGender.MALE,
        ("sgs_skill_zuilun", "sgs_skill_fuyin"),
    ),
    "wangyuanji": (
        3,
        3,
        CharacterGender.FEMALE,
        ("sgs_skill_qianchong", "sgs_skill_shangjian"),
    ),
}


def _create(cell: bridge.BaselineCellDescriptor):
    return bridge.create_skill_aware_fixed_assignment_duel_session_v1(
        seed=cell.seed,
        general_key=cell.general_key,
        seat_assignment=cell.seat_assignment,
    )


def _semantic_legal_projection(game) -> tuple[tuple[object, ...], ...]:
    return tuple(
        (
            action.action_type.value,
            action.actor_id,
            action.card_instance_id,
            action.target_ids,
            action.skill_id,
            dict(action.payload),
        )
        for action in game.legal_actions()
    )


@pytest.mark.parametrize("cell", bridge.BASELINE_18, ids=lambda item: item.cell_id)
def test_bridge_b_initialization_matrix_18_cells(
    cell: bridge.BaselineCellDescriptor,
) -> None:
    game = _create(cell)
    clone = _create(cell)
    no_skill = FormalNoSkillDuelSession(
        seed=cell.seed,
        configuration=FormalDuelConfiguration.formal_profile(),
    )

    assert game.mode_id == bridge.MODE_ID
    assert game.assignment.general_key == cell.general_key
    assert game.assignment.seat_assignment is cell.seat_assignment
    assert game.assignment.general_player_id == cell.general_player_id
    assert game.assignment.no_skill_player_id == cell.no_skill_player_id
    assert game.mode_modifier is bridge.ModeModifier.NONE
    assert game.formal_configuration.source_confirmed is True
    assert game.formal_result_eligible is True

    hp, max_hp, gender, skills = EXPECTED_GENERAL_AUTHORITY[cell.general_key]
    general = game.state.players_by_id[cell.general_player_id]
    soldier = game.state.players_by_id[cell.no_skill_player_id]
    assert (general.hp, general.max_hp) == (hp, max_hp)
    assert general.character is not None
    assert general.character.character_key == cell.general_key
    assert general.character.intrinsic_gender is gender
    assert soldier.character is not None
    assert soldier.character.character_key == "soldier"
    assert soldier.character.effective_gender is CharacterGender.NONE
    assert (soldier.hp, soldier.max_hp) == (4, 4)

    runtime = game.skill_runtime
    assert runtime is not None
    assert runtime.registry.registry_identity == bridge.BRIDGE_SKILL_REGISTRY_IDENTITY
    assert tuple(runtime.player_skills[cell.general_player_id]) == skills
    assert runtime.get_effective_skill_map(cell.no_skill_player_id) == {}
    assert runtime.dynamic_grants.get(cell.general_player_id, ()) == ()

    assert game.phase is ProductionPhase.PREPARE
    assert game.current_player_id == game.first_player_id
    assert len(game.state.card_ids_in(ZoneRef.hand("p1"))) == 4
    assert len(game.state.card_ids_in(ZoneRef.hand("p2"))) == 4
    assert len(game.state.card_ids_in(DRAW_PILE)) == 152
    assert game.state.card_ids_in(DISCARD_PILE) == ()
    assert game.state.card_ids_in(PROCESSING_ZONE) == ()
    assert game.state.card_ids_in(REVEALED_ZONE) == ()
    assert game.runtime.response_window_id is None
    assert game.runtime.pending_dying_id is None
    assert game.runtime.pending_slash is None
    assert game.runtime.pending_trick is None
    assert game.runtime.pending_judgment is None
    assert game.skill_pending is None
    assert game._skill_trigger_queue == []
    assert game._pending_private_card_selection is None
    assert game._pending_skill_hp_loss is None
    assert game._pending_card_continuation is None
    assert game._end_phase_dispatch_state is None
    assert game.turn_loss_ledger.entries == ()
    assert game.qianchong_phase_permission is None
    assert len(game.events) == 8
    assert all(event.event_type is EventType.CARD_GAINED for event in game.events)
    assert all(event.payload.get("reason") == "initial_hand" for event in game.events)
    assert game.is_finished is False
    assert game.winner_id is None
    assert isinstance(game._outcome_policy, DuelOutcomePolicy)
    assert game._outcome_policy.identity() == DuelOutcomePolicy().identity()

    assert game.first_player_id == no_skill.first_player_id
    for player_id in bridge.PARTICIPANT_IDS:
        assert game.state.card_ids_in(ZoneRef.hand(player_id)) == (
            no_skill.state.card_ids_in(ZoneRef.hand(player_id))
        )
    assert game.state.card_ids_in(DRAW_PILE) == no_skill.state.card_ids_in(DRAW_PILE)
    assert game.rng_calls == no_skill.rng_calls
    assert game._rng.current_state_sha256 == no_skill._rng.current_state_sha256
    assert _semantic_legal_projection(game) == _semantic_legal_projection(clone)
    assert game.initial_state_identity == clone.initial_state_identity
    assert game.initial_execution_identity == clone.initial_execution_identity
    assert tuple(item.action_id for item in game.initial_legal_actions) == tuple(
        item.action_id for item in clone.initial_legal_actions
    )
    assert game.legal_actions() == game.initial_legal_actions
    assert all(item.action_id and item.action_id.startswith("act_") for item in game.legal_actions())


def test_initialization_order_and_initial_trigger_absence() -> None:
    game = bridge.create_skill_aware_fixed_assignment_duel_session_v1(
        seed=0,
        general_key="wangyuanji",
        seat_assignment="GENERAL_AS_P2",
    )
    assert game.initialization_trace == bridge.INITIALIZATION_SEQUENCE
    assert tuple(item.value for item in game.initialization_trace) == (
        "validate_formal_profile",
        "validate_assignment",
        "derive_general_stats",
        "apply_mode_modifier_none",
        "first_player_rng",
        "shuffle_and_deal",
        "derive_base_skills",
        "initial_qianchong_reconcile",
        "sign_initial_state",
        "enumerate_first_legal_set",
    )
    assert len(game.events) == 8
    assert all(event.event_type is EventType.CARD_GAINED for event in game.events)
    assert all(event.payload.get("reason") == "initial_hand" for event in game.events)
    assert not any(event.event_type.value.startswith("skill") for event in game.events)
    assert game.turn_loss_ledger.entries == ()
    assert game._skill_consumed_triggers == frozenset()
    assert game._consumed_skill_continuations == frozenset()
    assert game._consumed_card_continuations == frozenset()
    runtime = game.skill_runtime
    assert runtime is not None
    assert runtime.has_skill("p2", "sgs_skill_qianchong")
    assert not runtime.has_skill("p2", "sgs_skill_weimu")
    assert not runtime.has_skill("p2", "sgs_skill_mingzhe")
    assert runtime.dynamic_grants.get("p2", ()) == ()


@pytest.mark.parametrize("seat", tuple(bridge.FixedAssignment))
def test_wangyuanji_initial_qianchong_reconcile_is_empty_and_eventless(
    seat: bridge.FixedAssignment,
) -> None:
    game = bridge.create_skill_aware_fixed_assignment_duel_session_v1(
        seed=49,
        general_key="wangyuanji",
        seat_assignment=seat,
    )
    owner = game.assignment.general_player_id
    assert all(
        game.state.card_ids_in(ZoneRef.equipment(owner, slot)) == ()
        for slot in ("weapon", "armor", "attack_horse", "defense_horse", "treasure")
    )
    assert game.skill_runtime is not None
    assert game.skill_runtime.has_skill(owner, "sgs_skill_qianchong")
    assert not game.skill_runtime.has_skill(owner, "sgs_skill_weimu")
    assert not game.skill_runtime.has_skill(owner, "sgs_skill_mingzhe")
    assert game.skill_runtime.dynamic_grants.get(owner, ()) == ()
    assert game.turn_loss_ledger.entries == ()
    assert len(game.rng_calls) == 2


def test_signed_legal_action_forwards_to_production_step_dispatcher() -> None:
    game = bridge.create_skill_aware_fixed_assignment_duel_session_v1(
        seed=1,
        general_key="shamoke",
        seat_assignment="GENERAL_AS_P1",
    )
    adapter_audit = game.registry.resolve(game.mode_id, game.phase.value).audit_state()
    assert adapter_audit["skill_authority"]["runtime"]["registry_identity"] == (
        bridge.BRIDGE_SKILL_REGISTRY_IDENTITY
    )
    chosen = game.legal_actions()[0]
    assert chosen.action_id is not None
    assert game.step(chosen.action_id) == chosen
    assert game.step_count == 1
    assert game.phase is ProductionPhase.JUDGMENT
    assert all(item.action_id is not None for item in game.legal_actions())
    with pytest.raises(ProductionBatchError):
        game.step(chosen.action_id)


def test_bridge_transaction_snapshot_wraps_existing_production_authority() -> None:
    game = bridge.create_skill_aware_fixed_assignment_duel_session_v1(
        seed=1,
        general_key="zhugezhan",
        seat_assignment="GENERAL_AS_P2",
    )
    snapshot = game._snapshot_authoritative_mutation_state()
    assert snapshot.assignment_identity == game.assignment_identity
    assert snapshot.bridge_skill_registry_identity == bridge.BRIDGE_SKILL_REGISTRY_IDENTITY
    assert snapshot.bridge_contract_identity == bridge.PROPOSED_BRIDGE_CONTRACT_IDENTITY
    production = snapshot.production_snapshot
    assert production.skill_runtime is game.skill_runtime
    assert production.turn_loss_ledger is game.turn_loss_ledger
    assert production.qianchong_phase_permission is game.qianchong_phase_permission
    assert production.skill_pending is None
    assert production.skill_trigger_queue == ()
    assert production.pending_private_card_selection is None
    assert production.pending_skill_hp_loss is None
    assert production.consumed_skill_continuations == frozenset()
    assert production.pending_card_continuation is None
    assert production.consumed_card_continuations == frozenset()
    assert production.continuation_in_progress_id is None
    assert production.end_phase_dispatch_state is None
    assert production.outcome_policy is game._outcome_policy
    assert production.rng_calls == game.rng_calls


def test_mutation_failure_rolls_back_complete_bridge_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    game = bridge.create_skill_aware_fixed_assignment_duel_session_v1(
        seed=0,
        general_key="wangyuanji",
        seat_assignment="GENERAL_AS_P1",
    )
    chosen = game.legal_actions()[0]
    assert chosen.action_id is not None
    before = {
        "execution": game.execution_snapshot,
        "execution_hash": game.execution_hash,
        "rng_state": game._rng.export_current_state(),
        "rng_hash": game._rng.current_state_sha256,
        "runtime": game.skill_runtime.audit_fingerprint(),
        "runtime_ref": game.skill_runtime,
        "legal": game.legal_actions(),
        "assignment": game.assignment,
        "assignment_identity": game.assignment_identity,
    }

    def fail_after_mutation() -> None:
        raise RuntimeError("BRIDGE-B controlled post-mutation failure")

    monkeypatch.setattr(game, "assert_resolution_invariants", fail_after_mutation)
    with pytest.raises(RuntimeError, match="controlled post-mutation failure"):
        game.step(chosen.action_id)

    assert game.execution_snapshot == before["execution"]
    assert game.execution_hash == before["execution_hash"]
    assert game._rng.export_current_state() == before["rng_state"]
    assert game._rng.current_state_sha256 == before["rng_hash"]
    assert game.skill_runtime is before["runtime_ref"]
    assert game.skill_runtime.audit_fingerprint() == before["runtime"]
    assert game.legal_actions() == before["legal"]
    assert game.assignment is before["assignment"]
    assert game.assignment_identity == before["assignment_identity"]


@pytest.mark.parametrize(
    ("general_key", "seat_assignment"),
    [
        ("unknown", "GENERAL_AS_P1"),
        (("shamoke", "zhugezhan"), "GENERAL_AS_P1"),
        (None, "GENERAL_AS_P1"),
        ("shamoke", "GENERAL_AS_P3"),
    ],
)
def test_factory_rejects_unknown_two_zero_general_or_wrong_seat(
    general_key: object, seat_assignment: object
) -> None:
    with pytest.raises(bridge.BridgeContractError):
        bridge.create_skill_aware_fixed_assignment_duel_session_v1(
            seed=0,
            general_key=general_key,
            seat_assignment=seat_assignment,
        )


@pytest.mark.parametrize("attack", ["wrong_participant", "caller_hp", "caller_skills", "two_generals", "zero_general"])
def test_session_rejects_tampered_assignment_descriptor(attack: str) -> None:
    data = bridge.create_bridge_assignment("shamoke", "GENERAL_AS_P1").to_dict()
    if attack == "wrong_participant":
        data["participants"][1]["player_id"] = "p3"
    elif attack == "caller_hp":
        data["participants"][0]["hp"] = 99
    elif attack == "caller_skills":
        data["participants"][0]["skill_ids"] = ["sgs_skill_pojiang"]
    elif attack == "two_generals":
        second = dict(data["participants"][0])
        second["player_id"] = "p2"
        data["participants"][1] = second
    else:
        first = dict(data["participants"][1])
        first["player_id"] = "p1"
        data["participants"][0] = first
    with pytest.raises(bridge.BridgeContractError):
        bridge.BridgeAssignmentDescriptor.from_dict(data)


@pytest.mark.parametrize(
    "forbidden",
    [
        "profile",
        "deck",
        "registry",
        "skill_registry",
        "session",
        "runtime",
        "handlers",
        "pojiang",
        "dynamic_grants",
        "fixture",
        "premutation",
        "analysis_only",
    ],
)
def test_canonical_factory_has_no_caller_authority_ingress(forbidden: str) -> None:
    kwargs = {
        "seed": 0,
        "general_key": "shamoke",
        "seat_assignment": "GENERAL_AS_P1",
        forbidden: object(),
    }
    with pytest.raises(TypeError):
        bridge.create_skill_aware_fixed_assignment_duel_session_v1(**kwargs)


def test_wrong_bridge_contract_identity_fails_closed() -> None:
    with pytest.raises(bridge.BridgeIdentityError, match="contract identity"):
        bridge.create_skill_aware_fixed_assignment_duel_session_v1(
            seed=0,
            general_key="shamoke",
            seat_assignment="GENERAL_AS_P1",
            bridge_contract_identity="0" * 64,
        )


def test_assignment_is_immutable() -> None:
    game = bridge.create_skill_aware_fixed_assignment_duel_session_v1(
        seed=0,
        general_key="shamoke",
        seat_assignment="GENERAL_AS_P1",
    )
    with pytest.raises(FrozenInstanceError):
        game.assignment.general_key = "zhugezhan"  # type: ignore[misc]


def test_no_skill_constructor_cannot_see_bridge_assignment_or_skill_authority() -> None:
    assignment = bridge.create_bridge_assignment("shamoke", "GENERAL_AS_P1")
    with pytest.raises(TypeError):
        FormalNoSkillDuelSession(
            seed=0,
            configuration=FormalDuelConfiguration.formal_profile(),
            bridge_assignment=assignment,  # type: ignore[call-arg]
        )
    game = FormalNoSkillDuelSession(
        seed=0,
        configuration=FormalDuelConfiguration.formal_profile(),
    )
    assert game.skill_runtime is None
    assert game.general_registry is None
    assert game.general_assignments is None
    assert all(player.character.character_key == "soldier" for player in game.state.players)
    assert not any(action.skill_id for action in game.legal_actions())
    assert not any(event.event_type.value.startswith("skill") for event in game.events)
