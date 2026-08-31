# -*- coding: utf-8 -*-
"""Cold-load replay and deep-tamper tests for G3 Wang Yuanji."""

from __future__ import annotations

import copy
import hashlib
import json

import pytest

import scripts.sgs_engine.production_batch as production_batch_module
import scripts.sgs_engine.skill_replay as skill_replay_module
from scripts.sgs_engine.actions import ActionType, LegalAction
from scripts.sgs_engine.events import EventType
from scripts.sgs_engine.generals import create_authoritative_general_batch_v1_registry
from scripts.sgs_engine.model import ZoneRef
from scripts.sgs_engine.production_batch import (
    BatchActionIdController,
    ProductionBasicCardBatch,
    ProductionPhase,
    _hand_choice_handle,
)
from scripts.sgs_engine.replay import sha256_value
from scripts.sgs_engine.skill_impl_v1 import create_proof_slice_v1_registry
from scripts.sgs_engine.skill_replay import (
    GENERAL_PRODUCTION_REPLAY_CONTRACT_IDENTITY_V1,
    GENERAL_PRODUCTION_REPLAY_CONTRACT_IDENTITY_V2,
    GENERAL_PRODUCTION_REPLAY_CONTRACT_VERSION_G3_AUTHORITY_V2,
    GENERAL_PRODUCTION_REPLAY_CONTRACT_VERSION_LEGACY,
    GENERAL_PRODUCTION_REPLAY_G3_REQUIRED_AUTHORITY_CAPABILITIES,
    GeneralProductionReplayEnvelope,
    SkillReplayDivergenceError,
    action_semantics,
    compute_state_hash,
    legal_actions_semantic_hash,
    reexecute_general_production_replay,
    rng_calls_hash,
)


def _rehash(data: dict[str, object]) -> None:
    records: dict[str, object] = {
        "action_ids": list(data["action_ids"]),
        "chosen_action_semantics": data["chosen_action_semantics"],
        "event_slice": data["event_slice"],
        "legal_set_hashes": list(data["legal_set_hashes"]),
        "owner_id": data["owner_id"],
        "primary_general_key": data["primary_general_key"],
        "trigger_event_sequence": data["trigger_event_sequence"],
        "trigger_event_type": data["trigger_event_type"],
        "usage_before": data["usage_before"],
        "usage_after": data["usage_after"],
        "marks_before": data["marks_before"],
        "marks_after": data["marks_after"],
        "skill_runtime_after": data["skill_runtime_after"],
        "continuation_identity": data["continuation_identity"],
        "rng_hash": data["rng_hash"],
        "state_hash_after": data["state_hash_after"],
        "state_hash_before": data["state_hash_before"],
    }
    if (
        data.get("replay_contract_version")
        == GENERAL_PRODUCTION_REPLAY_CONTRACT_VERSION_G3_AUTHORITY_V2
    ):
        records["participant_player_ids"] = list(
            data.get("participant_player_ids") or ()
        )
        records["replay_contract_version"] = data["replay_contract_version"]
        records["required_authority_capabilities"] = list(
            data.get("required_authority_capabilities") or ()
        )
        records["production_authority_after"] = data.get(
            "production_authority_after"
        )
        records["production_authority_trace"] = data.get(
            "production_authority_trace"
        )
    elif data.get("production_authority_after") or data.get(
        "production_authority_trace"
    ):
        records["production_authority_after"] = data.get(
            "production_authority_after"
        )
        records["production_authority_trace"] = data.get(
            "production_authority_trace"
        )
    data["records_identity"] = sha256_value(records)
    outer = copy.deepcopy(data)
    outer.pop("execution_identity", None)
    data["execution_identity"] = hashlib.sha256(
        json.dumps(
            outer,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _rehash_present_fields(data: dict[str, object]) -> None:
    """Attacker-side rehash after stripping or downgrading authority fields."""

    records = {
        "action_ids": list(data["action_ids"]),
        "chosen_action_semantics": data["chosen_action_semantics"],
        "event_slice": data["event_slice"],
        "legal_set_hashes": list(data["legal_set_hashes"]),
        "owner_id": data["owner_id"],
        "primary_general_key": data["primary_general_key"],
        "trigger_event_sequence": data["trigger_event_sequence"],
        "trigger_event_type": data["trigger_event_type"],
        "usage_before": data["usage_before"],
        "usage_after": data["usage_after"],
        "marks_before": data["marks_before"],
        "marks_after": data["marks_after"],
        "skill_runtime_after": data["skill_runtime_after"],
        "continuation_identity": data["continuation_identity"],
        "rng_hash": data["rng_hash"],
        "state_hash_after": data["state_hash_after"],
        "state_hash_before": data["state_hash_before"],
    }
    for field_name in (
        "replay_contract_version",
        "required_authority_capabilities",
        "production_authority_after",
        "production_authority_trace",
        "participant_player_ids",
    ):
        if field_name in data:
            records[field_name] = data[field_name]
    data["records_identity"] = sha256_value(records)
    outer = copy.deepcopy(data)
    outer.pop("execution_identity", None)
    data["execution_identity"] = hashlib.sha256(
        json.dumps(
            outer,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _new_game(
    seed: int,
    *,
    first_player_id: str,
    initial_hand_count: int = 4,
    general_assignments: dict[str, str] | None = None,
    player_hp: tuple[int, ...] | None = None,
    player_ids: tuple[str, ...] | None = None,
) -> ProductionBasicCardBatch:
    assignments = general_assignments or {"p1": "wangyuanji"}
    participants = player_ids or ("p1", "p2")
    hp = player_hp or tuple(
        3 if assignments.get(player_id) in {"wangyuanji", "zhugezhan"} else 4
        for player_id in participants
    )
    return ProductionBasicCardBatch(
        seed=seed,
        first_player_id=first_player_id,
        player_hp=hp,
        player_max_hp=hp,
        player_ids=participants,
        initial_hand_count=initial_hand_count,
        general_registry=create_authoritative_general_batch_v1_registry(),
        general_assignments=assignments,
        skill_registry=create_proof_slice_v1_registry(),
        session_id="w" * 32,
        session_secret=b"\x33" * 32,
    )


class _Recorder:
    def __init__(self, game: ProductionBasicCardBatch) -> None:
        self.game = game
        self.action_ids: list[str] = []
        self.legal_hashes: list[str] = []
        self.semantics: list[dict[str, object]] = []
        self.authority_trace: list[dict[str, object]] = []

    def take(self, action: LegalAction) -> None:
        legal = self.game.legal_actions()
        live = next(item for item in legal if item.action_id == action.action_id)
        self.legal_hashes.append(legal_actions_semantic_hash(legal))
        self.semantics.append(action_semantics(live))
        assert live.action_id
        self.action_ids.append(live.action_id)
        self.game.step(BatchActionIdController(live.action_id))
        authority = self.game._skill_audit_value()
        assert authority is not None
        self.authority_trace.append(copy.deepcopy(authority))

    def operation(self, name: str, **kwargs: object) -> LegalAction:
        action = next(
            item for item in self.game.legal_actions()
            if item.payload.get("operation") == name
            and all(item.payload.get(k) == v for k, v in kwargs.items())
        )
        self.take(action)
        return action


def _build_envelope(
    recorder: _Recorder,
    *,
    trigger_sequence: int,
    trigger_type: str,
    usage_before: dict[str, int],
    usage_after: dict[str, int],
    marks_before: dict[str, int],
    marks_after: dict[str, int],
    continuation_identity: str,
    state_before: str,
    initial_hand_count: int = 4,
    primary_general_key: str = "wangyuanji",
    owner_id: str = "p1",
    general_assignments: dict[str, str] | None = None,
) -> GeneralProductionReplayEnvelope:
    game = recorder.game
    general_registry = game.general_registry
    skill_registry = game.skill_runtime.registry
    assignments = general_assignments or {"p1": "wangyuanji"}
    general_keys = tuple(sorted(set(assignments.values())))
    derived = {
        player_id: general_registry.get_general(general_key).skill_ids
        for player_id, general_key in assignments.items()
    }
    skill_ids = {
        skill_id
        for player_skills in derived.values()
        for skill_id in player_skills
    }
    return GeneralProductionReplayEnvelope(
        seed=game._rng.seed,
        session_id=game.session_id,
        session_secret_hex=game.session_secret_hex,
        initial_hand_count=initial_hand_count,
        general_registry_identity=general_registry.registry_identity,
        general_profile_identities={
            key: general_registry.get_general(key).profile_identity
            for key in general_keys
        },
        general_semantic_payloads={
            key: general_registry.get_general(key).to_dict()
            for key in general_keys
        },
        general_assignments=assignments,
        skill_registry_identity=skill_registry.registry_identity,
        skill_profile_identities={
            skill_id: skill_registry.get_skill(skill_id).profile_identity
            for skill_id in sorted(skill_ids)
        },
        derived_skill_assignments=derived,
        primary_general_key=primary_general_key,
        owner_id=owner_id,
        trigger_event_sequence=trigger_sequence,
        trigger_event_type=trigger_type,
        usage_before=usage_before,
        usage_after=usage_after,
        marks_before=marks_before,
        marks_after=marks_after,
        skill_runtime_after=game.skill_runtime.audit_fingerprint(),
        continuation_identity=continuation_identity,
        action_ids=tuple(recorder.action_ids),
        legal_set_hashes=tuple(recorder.legal_hashes),
        chosen_action_semantics=tuple(recorder.semantics),
        event_slice=tuple(event.to_replay_dict() for event in game.events),
        state_hash_before=state_before,
        state_hash_after=compute_state_hash(game.state),
        rng_hash=rng_calls_hash(game.rng_calls),
        production_authority_after=game._skill_audit_value() or {},
        production_authority_trace=tuple(recorder.authority_trace),
        participant_player_ids=tuple(game._player_ids),
        replay_contract_version=GENERAL_PRODUCTION_REPLAY_CONTRACT_VERSION_G3_AUTHORITY_V2,
        required_authority_capabilities=GENERAL_PRODUCTION_REPLAY_G3_REQUIRED_AUTHORITY_CAPABILITIES,
        contract_identity=GENERAL_PRODUCTION_REPLAY_CONTRACT_IDENTITY_V2,
    )


def _record_qianchong() -> GeneralProductionReplayEnvelope:
    game = _new_game(11, first_player_id="p1")
    recorder = _Recorder(game)
    state_before = compute_state_hash(game.state)
    for operation in ("proceed_prepare", "proceed_judgment", "proceed_draw"):
        recorder.operation(operation)
    assert game.skill_pending is not None
    assert game.skill_pending.skill_id == "sgs_skill_qianchong"
    skill_before = game.skill_runtime.get_skill_state("p1", "sgs_skill_qianchong")
    trigger_sequence = game.skill_pending.trigger_event_sequence
    trigger_type = game.skill_pending.trigger_event_type
    continuation = str(game.skill_pending.payload.get("continuation_identity", ""))
    recorder.operation("qianchong_choice", chosen_card_type="basic")
    recorder.operation("end_play_phase")
    while game.phase is ProductionPhase.DISCARD:
        legal = game.legal_actions()
        submit = next(
            (item for item in legal if item.payload.get("operation") == "discard_phase_submit"),
            None,
        )
        if submit is not None:
            recorder.take(submit)
            break
        select = next(
            item for item in legal
            if item.payload.get("operation") == "select_discard_card"
        )
        recorder.take(select)
    skill_after = game.skill_runtime.get_skill_state("p1", "sgs_skill_qianchong")
    return _build_envelope(
        recorder,
        trigger_sequence=trigger_sequence,
        trigger_type=trigger_type,
        usage_before={
            "uses_this_phase": skill_before.uses_this_phase,
            "uses_this_turn": skill_before.uses_this_turn,
        },
        usage_after={
            "uses_this_phase": skill_after.uses_this_phase,
            "uses_this_turn": skill_after.uses_this_turn,
        },
        marks_before=dict(skill_before.marks),
        marks_after=dict(skill_after.marks),
        continuation_identity=continuation,
        state_before=state_before,
    )


def _record_shangjian() -> GeneralProductionReplayEnvelope:
    # Seed 3 deterministically deals a real 【杀】 to p1 so the replay carries
    # a production HAND -> PROCESSING loss-ledger entry.
    game = _new_game(3, first_player_id="p1")
    recorder = _Recorder(game)
    state_before = compute_state_hash(game.state)
    for operation in ("proceed_prepare", "proceed_judgment", "proceed_draw"):
        recorder.operation(operation)
    assert game.skill_pending is not None
    recorder.operation("qianchong_choice", chosen_card_type="basic")
    slash = next(
        item
        for item in game.legal_actions()
        if item.payload.get("card_key")
        in {"sgs_basic_sha", "sgs_basic_huosha", "sgs_basic_leisha"}
        and item.target_ids == ("p2",)
    )
    recorder.take(slash)
    recorder.operation("pass_slash_response")
    skill_before = game.skill_runtime.get_skill_state("p1", "sgs_skill_shangjian")
    recorder.operation("end_play_phase")
    while game.phase is ProductionPhase.DISCARD:
        legal = game.legal_actions()
        submit = next(
            (item for item in legal if item.payload.get("operation") == "discard_phase_submit"),
            None,
        )
        if submit is not None:
            recorder.take(submit)
            break
        select = next(
            item for item in legal
            if item.payload.get("operation") == "select_discard_card"
        )
        recorder.take(select)
    end_started_event = next(
        e for e in game.events
        if e.event_type is EventType.END_PHASE_STARTED
    )
    eval_event = next(
        e for e in game.events
        if e.event_type is EventType.SKILL_CONDITION_EVALUATED
        and e.payload.get("skill_id") == "sgs_skill_shangjian"
    )
    skill_after = game.skill_runtime.get_skill_state("p1", "sgs_skill_shangjian")
    return _build_envelope(
        recorder,
        trigger_sequence=end_started_event.sequence,
        trigger_type=EventType.END_PHASE_STARTED.value,
        usage_before={
            "uses_this_phase": skill_before.uses_this_phase,
            "uses_this_turn": skill_before.uses_this_turn,
        },
        usage_after={
            "uses_this_phase": skill_after.uses_this_phase,
            "uses_this_turn": skill_after.uses_this_turn,
        },
        marks_before=dict(skill_before.marks),
        marks_after=dict(skill_after.marks),
        continuation_identity=str(eval_event.payload.get("evaluation_identity")),
        state_before=state_before,
    )


def _record_end_dispatcher_resume() -> GeneralProductionReplayEnvelope:
    assignments = {"p1": "wangyuanji", "p2": "zhugezhan"}
    game = _new_game(
        29,
        first_player_id="p2",
        initial_hand_count=1,
        general_assignments=assignments,
        player_hp=(3, 3),
    )
    recorder = _Recorder(game)
    state_before = compute_state_hash(game.state)
    for operation in ("proceed_prepare", "proceed_judgment", "proceed_draw"):
        recorder.operation(operation)
    skill_before = game.skill_runtime.get_skill_state("p1", "sgs_skill_shangjian")
    recorder.operation("end_play_phase")
    assert game.skill_pending is not None
    assert game.skill_pending.skill_id == "sgs_skill_zuilun"
    recorder.operation("pass_skill")
    while game.phase is ProductionPhase.DISCARD:
        submit = next(
            (
                item
                for item in game.legal_actions()
                if item.payload.get("operation") == "discard_phase_submit"
            ),
            None,
        )
        if submit is not None:
            recorder.take(submit)
            break
        recorder.operation("select_discard_card")
    end_started_event = next(
        event
        for event in game.events
        if event.event_type is EventType.END_PHASE_STARTED
    )
    eval_event = next(
        event
        for event in game.events
        if event.event_type is EventType.SKILL_CONDITION_EVALUATED
        and event.payload.get("skill_id") == "sgs_skill_shangjian"
    )
    skill_after = game.skill_runtime.get_skill_state("p1", "sgs_skill_shangjian")
    return _build_envelope(
        recorder,
        trigger_sequence=end_started_event.sequence,
        trigger_type=EventType.END_PHASE_STARTED.value,
        usage_before={
            "uses_this_phase": skill_before.uses_this_phase,
            "uses_this_turn": skill_before.uses_this_turn,
        },
        usage_after={
            "uses_this_phase": skill_after.uses_this_phase,
            "uses_this_turn": skill_after.uses_this_turn,
        },
        marks_before=dict(skill_before.marks),
        marks_after=dict(skill_after.marks),
        continuation_identity=str(eval_event.payload["evaluation_identity"]),
        state_before=state_before,
        initial_hand_count=1,
        general_assignments=assignments,
    )


def _record_guanshi_three_player_pause_resume() -> tuple[
    GeneralProductionReplayEnvelope,
    int,
    str,
    ProductionBasicCardBatch,
]:
    """FINAL-002 exact signed p1/p2/p3 Guanshi -> Mingzhe A/P replay."""

    assignments = {"p1": "wangyuanji"}
    game = _new_game(
        126,
        first_player_id="p1",
        initial_hand_count=6,
        general_assignments=assignments,
        player_hp=(3, 4, 4),
        player_ids=("p1", "p2", "p3"),
    )
    recorder = _Recorder(game)
    state_before = compute_state_hash(game.state)

    for operation in ("proceed_prepare", "proceed_judgment", "proceed_draw"):
        recorder.operation(operation)
    assert game.skill_pending is not None
    assert game.skill_pending.skill_id == "sgs_skill_qianchong"
    recorder.operation("qianchong_choice", chosen_card_type="basic")
    recorder.operation("use_weapon", card_key="sgs_weapon_guanshifu")
    assert game.skill_runtime.has_skill("p1", "sgs_skill_mingzhe")

    hand_ids = game.state.card_ids_in(ZoneRef.hand("p1"))
    slash_id = next(
        card_id
        for card_id in hand_ids
        if game.state.cards_by_id[card_id].card_key
        in {"sgs_basic_sha", "sgs_basic_huosha", "sgs_basic_leisha"}
    )
    red_cost_ids = tuple(
        card_id
        for card_id in hand_ids
        if game.state.cards_by_id[card_id].color == "红"
        and game.state.cards_by_id[card_id].card_key
        not in {"sgs_basic_sha", "sgs_basic_huosha", "sgs_basic_leisha"}
    )[:2]
    assert len(red_cost_ids) == 2
    keep_ids = {slash_id, *red_cost_ids}

    recorder.operation("end_play_phase")
    while game.phase is ProductionPhase.DISCARD:
        legal = game.legal_actions()
        submit = next(
            (
                item
                for item in legal
                if item.payload.get("operation") == "discard_phase_submit"
            ),
            None,
        )
        if submit is not None:
            recorder.take(submit)
            break
        select = next(
            item
            for item in legal
            if item.payload.get("operation") == "select_discard_card"
            and item.card_instance_id not in keep_ids
        )
        recorder.take(select)
    assert game.phase is ProductionPhase.END
    assert set(game.state.card_ids_in(ZoneRef.hand("p1"))) == keep_ids
    recorder.operation("end_turn")

    for operation in ("proceed_prepare", "proceed_judgment", "proceed_draw"):
        recorder.operation(operation)
    jiedao = next(
        item
        for item in game.legal_actions()
        if item.payload.get("operation") == "use_jiedao"
        and item.target_ids == ("p1",)
        and item.payload.get("second_target_id") == "p3"
    )
    recorder.take(jiedao)
    while any(
        item.payload.get("operation") == "pass_trick_response"
        for item in game.legal_actions()
    ):
        recorder.operation("pass_trick_response")
    recorder.operation("choose_borrowed_sword_slash")
    recorder.operation("play_dodge")
    recorder.operation("weapon_force_hit")
    for card_id in red_cost_ids:
        select = next(
            item
            for item in game.legal_actions()
            if item.payload.get("operation") == "select_discard_two"
            and item.card_instance_id == card_id
        )
        recorder.take(select)
    recorder.operation("discard_two_submit")

    pause_index = len(recorder.action_ids) - 1
    pending_zero = game.skill_pending
    queue = tuple(game._skill_trigger_queue)
    continuation = game._pending_card_continuation
    assert pending_zero is not None and pending_zero.trigger_index == 0
    assert len(queue) == 1 and queue[0].trigger_index == 1
    assert continuation is not None
    assert continuation.continuation_kind == "guanshifu_force_hit_damage"
    assert pending_zero.window_revision == game.state.revision
    assert not [event for event in game.events if event.event_type is EventType.DAMAGE]
    assert game.state.players_by_id["p3"].hp == 4
    skill_before = game.skill_runtime.get_skill_state("p1", "sgs_skill_mingzhe")
    continuation_id = continuation.continuation_id
    trigger_sequence = pending_zero.trigger_event_sequence
    trigger_type = pending_zero.trigger_event_type

    recorder.operation("activate_skill")
    assert game.skill_pending is not None
    assert game.skill_pending.trigger_index == 1
    assert game._pending_card_continuation is not None
    assert not [event for event in game.events if event.event_type is EventType.DAMAGE]
    recorder.operation("pass_skill")

    damage_events = [
        event for event in game.events if event.event_type is EventType.DAMAGE
    ]
    assert len(damage_events) == 1
    assert damage_events[0].payload.get("weapon_effect") == "guanshifu_force_hit"
    assert game.state.players_by_id["p3"].hp == 3
    assert game.phase is ProductionPhase.PLAY
    assert game.current_player_id == "p2"
    assert game._pending_card_continuation is None
    assert continuation_id in game.consumed_card_continuation_identities
    mingzhe_draws = [
        event
        for event in game.events
        if event.event_type is EventType.CARD_MOVED
        and event.payload.get("reason") == "sgs_skill_mingzhe"
    ]
    assert len(mingzhe_draws) == 1
    skill_after = game.skill_runtime.get_skill_state("p1", "sgs_skill_mingzhe")
    envelope = _build_envelope(
        recorder,
        trigger_sequence=trigger_sequence,
        trigger_type=trigger_type,
        usage_before={
            "uses_this_phase": skill_before.uses_this_phase,
            "uses_this_turn": skill_before.uses_this_turn,
        },
        usage_after={
            "uses_this_phase": skill_after.uses_this_phase,
            "uses_this_turn": skill_after.uses_this_turn,
        },
        marks_before=dict(skill_before.marks),
        marks_after=dict(skill_after.marks),
        continuation_identity=continuation_id,
        state_before=state_before,
        initial_hand_count=6,
        general_assignments=assignments,
    )
    return envelope, pause_index, continuation_id, game


def test_wangyuanji_guanshi_three_player_replay_cold_load_roundtrip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cold load/fresh reexecution recreates pause #0/#1 and resumes once."""

    envelope, pause_index, continuation_id, recorded_game = (
        _record_guanshi_three_player_pause_resume()
    )
    serialized = json.loads(json.dumps(envelope.to_dict(), ensure_ascii=False))
    cold_loaded = GeneralProductionReplayEnvelope.from_dict(serialized)
    assert cold_loaded.participant_player_ids == ("p1", "p2", "p3")
    pause = cold_loaded.production_authority_trace[pause_index]
    pending = pause["pending_skill_decision"]
    queue = pause["pending_skill_decision_queue"]
    continuation = pause["pending_card_continuation"]
    assert pending["trigger_index"] == 0
    assert pending["skill_id"] == "sgs_skill_mingzhe"
    assert len(queue) == 1 and queue[0]["trigger_index"] == 1
    assert pending["consumption_key"] != queue[0]["consumption_key"]
    assert continuation["continuation_id"] == continuation_id
    assert continuation["continuation_kind"] == "guanshifu_force_hit_damage"
    assert pause["consumed_card_continuations"] == []

    constructed: list[ProductionBasicCardBatch] = []
    live_steps: list[dict[str, object]] = []
    original_construct = skill_replay_module._construct_general_production_replay_session
    original_step = ProductionBasicCardBatch.step

    def capture_construct(*args: object, **kwargs: object) -> ProductionBasicCardBatch:
        fresh = original_construct(*args, **kwargs)
        assert isinstance(fresh, ProductionBasicCardBatch)
        constructed.append(fresh)
        return fresh

    def capture_step(
        self: ProductionBasicCardBatch, controller: object
    ) -> object:
        result = original_step(self, controller)
        if constructed and self is constructed[0]:
            live_steps.append(
                {
                    "authority": copy.deepcopy(self._skill_audit_value()),
                    "p3_hp": self.state.players_by_id["p3"].hp,
                    "damage_count": len(
                        [
                            event
                            for event in self.events
                            if event.event_type is EventType.DAMAGE
                        ]
                    ),
                }
            )
        return result

    monkeypatch.setattr(
        skill_replay_module,
        "_construct_general_production_replay_session",
        capture_construct,
    )
    monkeypatch.setattr(ProductionBasicCardBatch, "step", capture_step)
    result = reexecute_general_production_replay(
        cold_loaded,
        create_authoritative_general_batch_v1_registry(),
        create_proof_slice_v1_registry(),
    )
    assert result.verified
    assert result.steps_verified == len(cold_loaded.action_ids)
    assert live_steps[pause_index]["authority"] == pause
    assert live_steps[pause_index]["p3_hp"] == 4
    assert live_steps[pause_index]["damage_count"] == 0
    fresh = constructed[0]
    assert fresh.player_ids == ("p1", "p2", "p3")
    assert fresh.state.players_by_id["p3"].hp == 3
    assert fresh.phase is recorded_game.phase is ProductionPhase.PLAY
    assert fresh.current_player_id == recorded_game.current_player_id == "p2"
    assert fresh._pending_card_continuation is None
    assert continuation_id in fresh.consumed_card_continuation_identities
    assert len(
        [event for event in fresh.events if event.event_type is EventType.DAMAGE]
    ) == 1
    assert len(
        [
            event
            for event in fresh.events
            if event.event_type is EventType.CARD_MOVED
            and event.payload.get("reason") == "sgs_skill_mingzhe"
        ]
    ) == 1


_GUANSHI_CONTINUATION_TAMPERS = (
    "continuation_id",
    "continuation_kind",
    "anchor_source_event_sequence",
    "anchor_card_action_identity",
    "queued_trigger_identity",
    "consumed_continuation_identity",
    "pause_without_continuation",
    "drained_queue_with_pending_continuation",
)


@pytest.mark.parametrize("attack", _GUANSHI_CONTINUATION_TAMPERS)
def test_wangyuanji_guanshi_replay_rejects_rehashed_continuation_semantic_tamper(
    attack: str,
) -> None:
    """Attacker rehashes both layers; fresh signed reexecution must still reject."""

    envelope, pause_index, _continuation_id, _recorded_game = (
        _record_guanshi_three_player_pause_resume()
    )
    data = copy.deepcopy(envelope.to_dict())
    trace = data["production_authority_trace"]
    pause = trace[pause_index]
    continuation = pause["pending_card_continuation"]
    assert continuation is not None
    if attack == "continuation_id":
        continuation["continuation_id"] = "0" * 64
    elif attack == "continuation_kind":
        continuation["continuation_kind"] = "forged_callback_semantic_kind"
    elif attack == "anchor_source_event_sequence":
        continuation["source_event_sequence"] += 1
    elif attack == "anchor_card_action_identity":
        continuation["card_action_identity"] = data["action_ids"][0]
    elif attack == "queued_trigger_identity":
        assert len(pause["pending_skill_decision_queue"]) == 1
        pause["pending_skill_decision_queue"][0]["trigger_index"] = 99
    elif attack == "consumed_continuation_identity":
        trace[-1]["consumed_card_continuations"] = ["0" * 64]
        data["production_authority_after"]["consumed_card_continuations"] = [
            "0" * 64
        ]
    elif attack == "pause_without_continuation":
        pause["pending_card_continuation"] = None
    elif attack == "drained_queue_with_pending_continuation":
        forged_pending = copy.deepcopy(continuation)
        forged_pending["consumed"] = False
        trace[-1]["pending_card_continuation"] = forged_pending
        data["production_authority_after"]["pending_card_continuation"] = (
            copy.deepcopy(forged_pending)
        )
    else:  # pragma: no cover - parameter list is exhaustive
        raise AssertionError(attack)
    _rehash(data)

    cold_loaded = GeneralProductionReplayEnvelope.from_dict(data)
    with pytest.raises(
        SkillReplayDivergenceError,
        match="production authority 快照不匹配|runtime_after 不匹配",
    ):
        reexecute_general_production_replay(
            cold_loaded,
            create_authoritative_general_batch_v1_registry(),
            create_proof_slice_v1_registry(),
        )


def test_wangyuanji_qianchong_replay_roundtrip() -> None:
    envelope = _record_qianchong()
    assert (
        envelope.replay_contract_version
        == GENERAL_PRODUCTION_REPLAY_CONTRACT_VERSION_G3_AUTHORITY_V2
    )
    assert envelope.required_authority_capabilities
    assert envelope.production_authority_trace
    assert envelope.production_authority_after
    result = reexecute_general_production_replay(
        envelope,
        create_authoritative_general_batch_v1_registry(),
        create_proof_slice_v1_registry(),
    )
    assert result.verified
    assert result.steps_verified == len(envelope.action_ids)


@pytest.mark.parametrize(
    "attack",
    (
        "trace_empty",
        "trace_deleted",
        "authority_after_empty",
        "authority_after_deleted",
        "both_empty",
        "both_deleted",
        "participant_deleted",
        "implicit_legacy_fields",
        "explicit_legacy_claim",
        "explicit_legacy_without_authority",
    ),
)
def test_wangyuanji_current_contract_rejects_rehashed_authority_downgrade(
    attack: str,
) -> None:
    data = copy.deepcopy(_record_qianchong().to_dict())
    if attack == "trace_empty":
        data["production_authority_trace"] = []
    elif attack == "trace_deleted":
        data.pop("production_authority_trace")
    elif attack == "authority_after_empty":
        data["production_authority_after"] = {}
    elif attack == "authority_after_deleted":
        data.pop("production_authority_after")
    elif attack == "both_empty":
        data["production_authority_trace"] = []
        data["production_authority_after"] = {}
    elif attack == "both_deleted":
        data.pop("production_authority_trace")
        data.pop("production_authority_after")
    elif attack == "participant_deleted":
        data.pop("participant_player_ids")
    elif attack == "implicit_legacy_fields":
        data.pop("replay_contract_version")
        data.pop("required_authority_capabilities")
    elif attack == "explicit_legacy_claim":
        data["replay_contract_version"] = (
            GENERAL_PRODUCTION_REPLAY_CONTRACT_VERSION_LEGACY
        )
        data["required_authority_capabilities"] = []
        data["contract_identity"] = (
            GENERAL_PRODUCTION_REPLAY_CONTRACT_IDENTITY_V1
        )
    elif attack == "explicit_legacy_without_authority":
        data["replay_contract_version"] = (
            GENERAL_PRODUCTION_REPLAY_CONTRACT_VERSION_LEGACY
        )
        data["required_authority_capabilities"] = []
        data["contract_identity"] = (
            GENERAL_PRODUCTION_REPLAY_CONTRACT_IDENTITY_V1
        )
        data.pop("production_authority_trace")
        data.pop("production_authority_after")
    else:  # pragma: no cover - parameter list is exhaustive
        raise AssertionError(attack)
    _rehash_present_fields(data)

    with pytest.raises(SkillReplayDivergenceError):
        cold_loaded = GeneralProductionReplayEnvelope.from_dict(data)
        reexecute_general_production_replay(
            cold_loaded,
            create_authoritative_general_batch_v1_registry(),
            create_proof_slice_v1_registry(),
        )


def test_wangyuanji_current_contract_rejects_missing_authority_snapshot_schema() -> None:
    data = copy.deepcopy(_record_qianchong().to_dict())
    del data["production_authority_trace"][0]["turn_loss_ledger"]
    _rehash_present_fields(data)
    with pytest.raises(
        SkillReplayDivergenceError,
        match="缺少当前 G3 authority 字段",
    ):
        GeneralProductionReplayEnvelope.from_dict(data)


def test_wangyuanji_shangjian_replay_roundtrip() -> None:
    envelope = _record_shangjian()
    result = reexecute_general_production_replay(
        envelope,
        create_authoritative_general_batch_v1_registry(),
        create_proof_slice_v1_registry(),
    )
    assert result.verified
    assert result.steps_verified == len(envelope.action_ids)


def test_wangyuanji_replay_rejects_tampered_action() -> None:
    envelope = _record_qianchong()
    data = envelope.to_dict()
    actions = list(data["action_ids"])
    actions[0] = "act_" + "0" * 64
    data["action_ids"] = actions
    _rehash(data)
    with pytest.raises(SkillReplayDivergenceError, match="chosen action_id 不在 live legal_actions 中"):
        reexecute_general_production_replay(
            GeneralProductionReplayEnvelope.from_dict(data),
            create_authoritative_general_batch_v1_registry(),
            create_proof_slice_v1_registry(),
        )


def test_wangyuanji_replay_rejects_tampered_semantics() -> None:
    envelope = _record_qianchong()
    data = envelope.to_dict()
    semantics = list(data["chosen_action_semantics"])
    # Modify payload without breaking schema
    semantics[0] = {**semantics[0], "payload": {**semantics[0].get("payload", {}), "tampered": True}}
    data["chosen_action_semantics"] = semantics
    _rehash(data)
    with pytest.raises(SkillReplayDivergenceError, match="chosen action 语义不匹配"):
        reexecute_general_production_replay(
            GeneralProductionReplayEnvelope.from_dict(data),
            create_authoritative_general_batch_v1_registry(),
            create_proof_slice_v1_registry(),
        )


def test_wangyuanji_replay_rejects_tampered_state_before() -> None:
    envelope = _record_qianchong()
    data = envelope.to_dict()
    data["state_hash_before"] = "0" * 64
    _rehash(data)
    with pytest.raises(SkillReplayDivergenceError, match="起始状态哈希不匹配"):
        reexecute_general_production_replay(
            GeneralProductionReplayEnvelope.from_dict(data),
            create_authoritative_general_batch_v1_registry(),
            create_proof_slice_v1_registry(),
        )


def test_wangyuanji_replay_rejects_tampered_state_after() -> None:
    envelope = _record_qianchong()
    data = envelope.to_dict()
    data["state_hash_after"] = "0" * 64
    _rehash(data)
    with pytest.raises(SkillReplayDivergenceError, match="终态哈希不匹配"):
        reexecute_general_production_replay(
            GeneralProductionReplayEnvelope.from_dict(data),
            create_authoritative_general_batch_v1_registry(),
            create_proof_slice_v1_registry(),
        )


def test_wangyuanji_replay_rejects_rehashed_qianchong_permission_tamper() -> None:
    data = copy.deepcopy(_record_qianchong().to_dict())
    trace = list(data["production_authority_trace"])
    permission = next(
        item["qianchong_phase_permission"]
        for item in trace
        if item["qianchong_phase_permission"] is not None
    )
    permission["chosen_card_type"] = "trick"
    data["production_authority_trace"] = trace
    _rehash(data)
    with pytest.raises(SkillReplayDivergenceError, match="production authority 快照不匹配"):
        reexecute_general_production_replay(
            GeneralProductionReplayEnvelope.from_dict(data),
            create_authoritative_general_batch_v1_registry(),
            create_proof_slice_v1_registry(),
        )


def test_wangyuanji_replay_rejects_rehashed_shangjian_ledger_tamper() -> None:
    data = copy.deepcopy(_record_shangjian().to_dict())
    trace = list(data["production_authority_trace"])
    ledger_entry = next(
        item["turn_loss_ledger"]["entries"][0]
        for item in trace
        if item["turn_loss_ledger"]["entries"]
    )
    ledger_entry["source_zone"] = "equipment:weapon"
    data["production_authority_trace"] = trace
    _rehash(data)
    with pytest.raises(SkillReplayDivergenceError, match="production authority 快照不匹配"):
        reexecute_general_production_replay(
            GeneralProductionReplayEnvelope.from_dict(data),
            create_authoritative_general_batch_v1_registry(),
            create_proof_slice_v1_registry(),
        )


def test_wangyuanji_replay_rejects_rehashed_dynamic_grant_provenance_tamper() -> None:
    data = copy.deepcopy(_record_qianchong().to_dict())
    fake_grant = {
        "grant_id": "grant:tampered",
        "owner_id": "p1",
        "source_skill_id": "sgs_skill_qianchong",
        "target_skill_id": "sgs_skill_mingzhe",
        "source_instance_id": None,
        "lifetime_kind": "conditional",
        "condition_identity": "all_red",
        "created_turn_number": 1,
        "created_phase": "play",
        "active": True,
        "revoke_reason": None,
        "revoke_turn_number": None,
        "revoke_phase": None,
    }
    trace = list(data["production_authority_trace"])
    trace[0]["runtime"]["dynamic_grants"]["p1"] = [fake_grant]
    data["production_authority_trace"] = trace
    _rehash(data)
    with pytest.raises(SkillReplayDivergenceError, match="production authority 快照不匹配"):
        reexecute_general_production_replay(
            GeneralProductionReplayEnvelope.from_dict(data),
            create_authoritative_general_batch_v1_registry(),
            create_proof_slice_v1_registry(),
        )


def test_wangyuanji_replay_rejects_rehashed_end_dispatcher_cursor_tamper() -> None:
    data = copy.deepcopy(_record_end_dispatcher_resume().to_dict())
    trace = list(data["production_authority_trace"])
    dispatch = next(
        item["end_phase_dispatch_state"]
        for item in trace
        if item["end_phase_dispatch_state"] is not None
    )
    dispatch["current_seat_index"] = 1
    data["production_authority_trace"] = trace
    _rehash(data)
    with pytest.raises(SkillReplayDivergenceError, match="production authority 快照不匹配"):
        reexecute_general_production_replay(
            GeneralProductionReplayEnvelope.from_dict(data),
            create_authoritative_general_batch_v1_registry(),
            create_proof_slice_v1_registry(),
        )


def test_wangyuanji_replay_rejects_rehashed_shangjian_live_h_hp_tamper() -> None:
    data = copy.deepcopy(_record_shangjian().to_dict())
    condition = next(
        item
        for item in data["event_slice"]
        if item["event_type"] == EventType.SKILL_CONDITION_EVALUATED.value
        and item["payload"].get("skill_id") == "sgs_skill_shangjian"
    )
    condition["payload"]["h_hp"] = 99
    _rehash(data)
    with pytest.raises(SkillReplayDivergenceError, match="事件内容或序号切片不匹配"):
        reexecute_general_production_replay(
            GeneralProductionReplayEnvelope.from_dict(data),
            create_authoritative_general_batch_v1_registry(),
            create_proof_slice_v1_registry(),
        )


# ---------------------------------------------------------------------------
# G3-CLOSURE-004  deep-tamper 正式矩阵
#
# helper 设计：所有攻击复用同一个 test-only 流程——篡改 envelope dict 的某个
# semantic 字段 → _rehash 重算 records_identity 与 execution_identity（攻击者
# 已重算两层 outer identities）→ from_dict 冷加载 → fresh reexecute → 必须被
# semantic contract validation 或 fresh authoritative reexecution 拒绝。
# clean envelope 一律由正式 production recorder（_Recorder/_build_envelope）
# 生成，helper 不替代 production recording。
# ---------------------------------------------------------------------------


def _record_mingzhe_grant_and_trigger() -> GeneralProductionReplayEnvelope:
    """E1：谦冲选择 + 普通自己上装备 + 动态【明哲】授予 + 回合外红牌被拆触发。

    seed 25 确定性发牌：p1 初始手牌含红色诸葛连弩与红色【桃】，p2 持有
    【过河拆桥】。信封内同时携带：dynamic grant（明哲）、equip-play 移动
    （不计尚俭）、谦冲 permission、弃牌 ledger、尚俭评估、真实明哲触发窗口。
    """
    game = _new_game(25, first_player_id="p1")
    recorder = _Recorder(game)
    state_before = compute_state_hash(game.state)
    for operation in ("proceed_prepare", "proceed_judgment", "proceed_draw"):
        recorder.operation(operation)
    assert game.skill_pending is not None
    assert game.skill_pending.skill_id == "sgs_skill_qianchong"
    skill_before = game.skill_runtime.get_skill_state("p1", "sgs_skill_qianchong")
    trigger_sequence = game.skill_pending.trigger_event_sequence
    trigger_type = game.skill_pending.trigger_event_type
    continuation = str(game.skill_pending.payload.get("continuation_identity", ""))
    recorder.operation("qianchong_choice", chosen_card_type="basic")
    recorder.operation("use_weapon", card_key="sgs_weapon_zhugeliannu")
    assert game.skill_runtime.has_skill("p1", "sgs_skill_mingzhe")
    keeper_id = next(
        card_id
        for card_id in game.state.card_ids_in(ZoneRef.hand("p1"))
        if game.state.cards_by_id[card_id].card_key == "sgs_basic_tao"
    )
    recorder.operation("end_play_phase")
    while game.phase is ProductionPhase.DISCARD:
        legal = game.legal_actions()
        submit = next(
            (
                item
                for item in legal
                if item.payload.get("operation") == "discard_phase_submit"
            ),
            None,
        )
        if submit is not None:
            recorder.take(submit)
            break
        select = next(
            item
            for item in legal
            if item.payload.get("operation") == "select_discard_card"
            and item.card_instance_id != keeper_id
        )
        recorder.take(select)
    assert game.phase is ProductionPhase.END
    end_turn = next(
        item
        for item in game.legal_actions()
        if item.payload.get("operation") == "end_turn"
    )
    recorder.take(end_turn)
    for operation in ("proceed_prepare", "proceed_judgment", "proceed_draw"):
        recorder.operation(operation)
    assert game.phase is ProductionPhase.PLAY
    guohe = next(
        item
        for item in game.legal_actions()
        if item.payload.get("operation") == "use_guohe"
        and item.target_ids == ("p1",)
    )
    recorder.take(guohe)
    while game.phase is ProductionPhase.TRICK_RESPONSE:
        recorder.operation("pass_trick_response")
    choice = game.runtime.pending_zone_choice
    assert choice is not None
    digest = game.runtime.zone_choice_snapshot_digest
    assert digest is not None
    handle = _hand_choice_handle(
        game.session_id,
        game._session_secret,
        choice.window_id,
        "p1",
        "hand",
        digest,
        keeper_id,
    )
    pick = next(
        item
        for item in game.legal_actions()
        if item.payload.get("operation") == "choose_target_zone_card"
        and item.payload.get("handle") == handle
    )
    recorder.take(pick)
    assert game.skill_pending is not None
    assert game.skill_pending.skill_id == "sgs_skill_mingzhe"
    assert game.skill_pending.trigger_index == 0
    recorder.operation("activate_skill")
    skill_after = game.skill_runtime.get_skill_state("p1", "sgs_skill_qianchong")
    return _build_envelope(
        recorder,
        trigger_sequence=trigger_sequence,
        trigger_type=trigger_type,
        usage_before={
            "uses_this_phase": skill_before.uses_this_phase,
            "uses_this_turn": skill_before.uses_this_turn,
        },
        usage_after={
            "uses_this_phase": skill_after.uses_this_phase,
            "uses_this_turn": skill_after.uses_this_turn,
        },
        marks_before=dict(skill_before.marks),
        marks_after=dict(skill_after.marks),
        continuation_identity=continuation,
        state_before=state_before,
    )


def _record_equipment_replacement() -> GeneralProductionReplayEnvelope:
    """E2：装备替换——旧红色装备离区计 L=1，动态授予从明哲翻转为帷幕。

    seed 157 确定性发牌：p1 初始手牌为红色朱雀羽扇，摸牌阶段摸得青釭剑。
    """
    game = _new_game(157, first_player_id="p1", initial_hand_count=1)
    recorder = _Recorder(game)
    state_before = compute_state_hash(game.state)
    for operation in ("proceed_prepare", "proceed_judgment", "proceed_draw"):
        recorder.operation(operation)
    assert game.skill_pending is not None
    assert game.skill_pending.skill_id == "sgs_skill_qianchong"
    skill_before = game.skill_runtime.get_skill_state("p1", "sgs_skill_qianchong")
    trigger_sequence = game.skill_pending.trigger_event_sequence
    trigger_type = game.skill_pending.trigger_event_type
    continuation = str(game.skill_pending.payload.get("continuation_identity", ""))
    recorder.operation("qianchong_choice", chosen_card_type="basic")
    recorder.operation("use_weapon", card_key="sgs_weapon_zhuqueyushan")
    assert game.skill_runtime.has_skill("p1", "sgs_skill_mingzhe")
    recorder.operation("use_weapon", card_key="sgs_weapon_qinggangjian")
    assert not game.skill_runtime.has_skill("p1", "sgs_skill_mingzhe")
    assert game.skill_runtime.has_skill("p1", "sgs_skill_weimu")
    recorder.operation("end_play_phase")
    assert game.phase is ProductionPhase.END
    skill_after = game.skill_runtime.get_skill_state("p1", "sgs_skill_qianchong")
    return _build_envelope(
        recorder,
        trigger_sequence=trigger_sequence,
        trigger_type=trigger_type,
        usage_before={
            "uses_this_phase": skill_before.uses_this_phase,
            "uses_this_turn": skill_before.uses_this_turn,
        },
        usage_after={
            "uses_this_phase": skill_after.uses_this_phase,
            "uses_this_turn": skill_after.uses_this_turn,
        },
        marks_before=dict(skill_before.marks),
        marks_after=dict(skill_after.marks),
        continuation_identity=continuation,
        state_before=state_before,
        initial_hand_count=1,
    )


def test_wangyuanji_mingzhe_grant_trigger_replay_roundtrip() -> None:
    envelope = _record_mingzhe_grant_and_trigger()
    result = reexecute_general_production_replay(
        envelope,
        create_authoritative_general_batch_v1_registry(),
        create_proof_slice_v1_registry(),
    )
    assert result.verified
    assert result.steps_verified == len(envelope.action_ids)


def test_wangyuanji_equipment_replacement_replay_roundtrip() -> None:
    envelope = _record_equipment_replacement()
    result = reexecute_general_production_replay(
        envelope,
        create_authoritative_general_batch_v1_registry(),
        create_proof_slice_v1_registry(),
    )
    assert result.verified
    assert result.steps_verified == len(envelope.action_ids)


# ---------------------------------------------------------------------------
# G3-CLOSURE-004  24 类 semantic deep-tamper 正式矩阵
#
# helper 设计（test-only）：clean envelope 由正式 production recorder 生成并
# 缓存 → deepcopy → 篡改某一 semantic 字段 → _rehash 重算 records_identity 与
# execution_identity（攻击者已重算两层 outer identities）→ from_dict 冷加载
# → fresh reexecute → 必须由 semantic contract validation 或 fresh
# authoritative reexecution 拒绝（绝不允许仅靠 outer identity mismatch）。
# ---------------------------------------------------------------------------

_ENVELOPE_CACHE: dict[str, dict[str, object]] = {}


def _envelope_dict(kind: str) -> dict[str, object]:
    if kind not in _ENVELOPE_CACHE:
        factory = {
            "E1": _record_mingzhe_grant_and_trigger,
            "E2": _record_equipment_replacement,
            "B": _record_shangjian,
            "C": _record_end_dispatcher_resume,
            "A": _record_qianchong,
        }[kind]
        _ENVELOPE_CACHE[kind] = factory().to_dict()
    return copy.deepcopy(_ENVELOPE_CACHE[kind])


def _first_snap_with(
    data: dict[str, object], predicate: object
) -> dict[str, object]:
    for snap in data["production_authority_trace"]:
        if predicate(snap):  # type: ignore[operator]
            return snap
    raise AssertionError("deep-tamper 矩阵前置条件失败：未找到目标快照")


def _grant_snap(data: dict[str, object]) -> dict[str, object]:
    return _first_snap_with(
        data, lambda s: s["runtime"]["dynamic_grants"].get("p1")
    )


def _tamper_01_grant_source_skill_id(data: dict[str, object]) -> None:
    _grant_snap(data)["runtime"]["dynamic_grants"]["p1"][0][
        "source_skill_id"
    ] = "sgs_skill_shangjian"


def _tamper_02_grant_target_skill_id(data: dict[str, object]) -> None:
    _grant_snap(data)["runtime"]["dynamic_grants"]["p1"][0][
        "target_skill_id"
    ] = "sgs_skill_weimu"


def _tamper_03_grant_revoke_timing(data: dict[str, object]) -> None:
    snap = _first_snap_with(
        data,
        lambda s: any(
            grant.get("revoke_reason")
            for grant in s["runtime"]["dynamic_grants"].get("p1", [])
        ),
    )
    revoked = next(
        grant
        for grant in snap["runtime"]["dynamic_grants"]["p1"]
        if grant.get("revoke_reason")
    )
    revoked["revoke_turn_number"] = 99
    revoked["active"] = True


def _tamper_04_fake_dual_weimu_mingzhe(data: dict[str, object]) -> None:
    snap = _grant_snap(data)
    real = snap["runtime"]["dynamic_grants"]["p1"][0]
    fake = dict(real)
    fake["grant_id"] = (
        "grant:p1:sgs_skill_qianchong:sgs_skill_weimu:all_black:1:play:forged"
    )
    fake["target_skill_id"] = "sgs_skill_weimu"
    fake["condition_identity"] = "all_black"
    snap["runtime"]["dynamic_grants"]["p1"].append(fake)


def _tamper_05_effective_skill_set(data: dict[str, object]) -> None:
    # 篡改第 0 步快照中的有效技能集：【谦冲】被伪造为失效。
    snap = data["production_authority_trace"][0]
    snap["runtime"]["player_skills"]["p1"]["sgs_skill_qianchong"][
        "effective"
    ] = False


def _tamper_06_loss_movement_sequence(data: dict[str, object]) -> None:
    snap = _first_snap_with(
        data,
        lambda s: any(
            entry["mingzhe_discovery_eligible"]
            for entry in s["card_movement_authority"]
        ),
    )
    entry = next(
        item
        for item in snap["card_movement_authority"]
        if item["mingzhe_discovery_eligible"]
    )
    entry["movement_sequence"] = entry["movement_sequence"] + 1000


def _tamper_07_retroactive_trigger_forgery(data: dict[str, object]) -> None:
    # 在任何真实失牌发生之前，伪造一个已消费的【明哲】trigger（retroactive）。
    data["production_authority_trace"][0]["consumed_triggers"].append(
        ["1", "p1", "sgs_skill_mingzhe", "0"]
    )


def _mingzhe_pending_snap(data: dict[str, object]) -> dict[str, object]:
    return _first_snap_with(
        data,
        lambda s: (s["pending_skill_decision"] or {}).get("skill_id")
        == "sgs_skill_mingzhe",
    )


def _tamper_08_mingzhe_card_instance_id(data: dict[str, object]) -> None:
    _mingzhe_pending_snap(data)["pending_skill_decision"][
        "card_instance_id"
    ] = "sgs-mobile-20260725-000"


def _tamper_09_mingzhe_trigger_index(data: dict[str, object]) -> None:
    _mingzhe_pending_snap(data)["pending_skill_decision"]["trigger_index"] = 1


def _tamper_10_self_equip_forged_l_plus_one(data: dict[str, object]) -> None:
    snap = _first_snap_with(
        data,
        lambda s: any(
            entry["semantic_reason"] == "weapon_equip:enter_processing"
            and not entry["counts_as_loss"]
            for entry in s["turn_loss_ledger"]["entries"]
        ),
    )
    entry = next(
        item
        for item in snap["turn_loss_ledger"]["entries"]
        if item["semantic_reason"] == "weapon_equip:enter_processing"
    )
    entry["counts_as_loss"] = True


def _tamper_11_replacement_forged_l_zero(data: dict[str, object]) -> None:
    snap = _first_snap_with(
        data,
        lambda s: any(
            entry["semantic_reason"] == "equip_replaced"
            for entry in s["turn_loss_ledger"]["entries"]
        ),
    )
    entry = next(
        item
        for item in snap["turn_loss_ledger"]["entries"]
        if item["semantic_reason"] == "equip_replaced"
    )
    entry["counts_as_loss"] = False


def _ledger_snap(data: dict[str, object]) -> dict[str, object]:
    return _first_snap_with(
        data, lambda s: bool(s["turn_loss_ledger"]["entries"])
    )


def _tamper_12_duplicate_ledger_entry(data: dict[str, object]) -> None:
    entries = _ledger_snap(data)["turn_loss_ledger"]["entries"]
    entries.append(dict(entries[0]))


def _tamper_13_missing_ledger_entry(data: dict[str, object]) -> None:
    _ledger_snap(data)["turn_loss_ledger"]["entries"].pop(0)


def _tamper_14_ledger_source_zone(data: dict[str, object]) -> None:
    _ledger_snap(data)["turn_loss_ledger"]["entries"][0][
        "source_zone"
    ] = "equipment:weapon"


def _tamper_15_ledger_semantic_reason(data: dict[str, object]) -> None:
    _ledger_snap(data)["turn_loss_ledger"]["entries"][0][
        "semantic_reason"
    ] = "equip_replaced"


def _shangjian_eval_event(data: dict[str, object]) -> dict[str, object]:
    return next(
        item
        for item in data["event_slice"]
        if item["event_type"] == EventType.SKILL_CONDITION_EVALUATED.value
        and item["payload"].get("skill_id") == "sgs_skill_shangjian"
    )


def _tamper_16_total_l(data: dict[str, object]) -> None:
    _shangjian_eval_event(data)["payload"]["l_count"] = 99


def _tamper_17_live_h(data: dict[str, object]) -> None:
    _shangjian_eval_event(data)["payload"]["h_hp"] = 99


def _tamper_18_shangjian_draw_count(data: dict[str, object]) -> None:
    _shangjian_eval_event(data)["payload"]["draw_count"] = 99


def _permission_snap(data: dict[str, object]) -> dict[str, object]:
    return _first_snap_with(
        data, lambda s: s["qianchong_phase_permission"] is not None
    )


def _tamper_19_permission_category(data: dict[str, object]) -> None:
    _permission_snap(data)["qianchong_phase_permission"][
        "chosen_card_type"
    ] = "trick"


def _tamper_20_permission_phase_identity(data: dict[str, object]) -> None:
    _permission_snap(data)["qianchong_phase_permission"]["turn_number"] = 99


def _dispatch_snap(data: dict[str, object]) -> dict[str, object]:
    return _first_snap_with(
        data, lambda s: s["end_phase_dispatch_state"] is not None
    )


def _tamper_21_end_dispatch_seat_cursor(data: dict[str, object]) -> None:
    _dispatch_snap(data)["end_phase_dispatch_state"]["current_seat_index"] = 1


def _tamper_22_completed_trigger_identity(data: dict[str, object]) -> None:
    dispatch = _dispatch_snap(data)["end_phase_dispatch_state"]
    dispatch["completed_triggers"][0][1] = "sgs_skill_mingzhe"


def _tamper_23_missing_required_capability(data: dict[str, object]) -> None:
    data["required_authority_capabilities"] = list(
        data["required_authority_capabilities"]
    )[:-1]


def _tamper_24_reduced_capability_set(data: dict[str, object]) -> None:
    data["required_authority_capabilities"] = []


_AUTHORITY_MISMATCH = "production authority 快照不匹配"
_EVENT_MISMATCH = "事件内容或序号切片不匹配"
_CAPABILITY_INCOMPLETE = "required_authority_capabilities 不完整"

_DEEP_TAMPER_CASES = (
    # Dynamic grants（E1/E2）
    ("01_grant_source_skill_id", "E1", _tamper_01_grant_source_skill_id, _AUTHORITY_MISMATCH),
    ("02_grant_target_skill_id", "E1", _tamper_02_grant_target_skill_id, _AUTHORITY_MISMATCH),
    ("03_grant_revoke_timing_active_state", "E2", _tamper_03_grant_revoke_timing, _AUTHORITY_MISMATCH),
    ("04_fake_dual_weimu_mingzhe", "E1", _tamper_04_fake_dual_weimu_mingzhe, _AUTHORITY_MISMATCH),
    ("05_effective_skill_set", "E1", _tamper_05_effective_skill_set, _AUTHORITY_MISMATCH),
    # Mingzhe（E1）
    ("06_actual_loss_movement_sequence", "E1", _tamper_06_loss_movement_sequence, _AUTHORITY_MISMATCH),
    ("07_retroactive_trigger_forgery", "E1", _tamper_07_retroactive_trigger_forgery, _AUTHORITY_MISMATCH),
    ("08_mingzhe_card_instance_id", "E1", _tamper_08_mingzhe_card_instance_id, _AUTHORITY_MISMATCH),
    ("09_mingzhe_trigger_index", "E1", _tamper_09_mingzhe_trigger_index, _AUTHORITY_MISMATCH),
    # Shangjian / movement（E1/E2/B）
    ("10_self_equip_forged_l_plus_one", "E1", _tamper_10_self_equip_forged_l_plus_one, _AUTHORITY_MISMATCH),
    ("11_replacement_forged_l_zero", "E2", _tamper_11_replacement_forged_l_zero, _AUTHORITY_MISMATCH),
    ("12_duplicate_ledger_entry", "B", _tamper_12_duplicate_ledger_entry, _AUTHORITY_MISMATCH),
    ("13_missing_ledger_entry", "B", _tamper_13_missing_ledger_entry, _AUTHORITY_MISMATCH),
    ("14_ledger_source_zone", "B", _tamper_14_ledger_source_zone, _AUTHORITY_MISMATCH),
    ("15_ledger_semantic_reason", "B", _tamper_15_ledger_semantic_reason, _AUTHORITY_MISMATCH),
    ("16_total_l", "B", _tamper_16_total_l, _EVENT_MISMATCH),
    ("17_live_h", "B", _tamper_17_live_h, _EVENT_MISMATCH),
    ("18_shangjian_draw_count", "B", _tamper_18_shangjian_draw_count, _EVENT_MISMATCH),
    # Qianchong permission（E1）
    ("19_permission_category", "E1", _tamper_19_permission_category, _AUTHORITY_MISMATCH),
    ("20_permission_phase_identity", "E1", _tamper_20_permission_phase_identity, _AUTHORITY_MISMATCH),
    # END dispatcher（C）
    ("21_end_dispatch_seat_cursor", "C", _tamper_21_end_dispatch_seat_cursor, _AUTHORITY_MISMATCH),
    ("22_completed_trigger_identity", "C", _tamper_22_completed_trigger_identity, _AUTHORITY_MISMATCH),
    # Replay contract capability（A）
    ("23_missing_required_capability", "A", _tamper_23_missing_required_capability, _CAPABILITY_INCOMPLETE),
    ("24_reduced_capability_set", "A", _tamper_24_reduced_capability_set, _CAPABILITY_INCOMPLETE),
)


@pytest.mark.parametrize(
    "axis,kind,mutate,match",
    _DEEP_TAMPER_CASES,
    ids=[case[0] for case in _DEEP_TAMPER_CASES],
)
def test_wangyuanji_deep_tamper_matrix_rejects_rehashed_semantic_tamper(
    axis: str,
    kind: str,
    mutate: object,
    match: str,
) -> None:
    del axis
    data = _envelope_dict(kind)
    mutate(data)  # type: ignore[operator]
    _rehash(data)
    with pytest.raises(SkillReplayDivergenceError, match=match):
        cold_loaded = GeneralProductionReplayEnvelope.from_dict(data)
        reexecute_general_production_replay(
            cold_loaded,
            create_authoritative_general_batch_v1_registry(),
            create_proof_slice_v1_registry(),
        )


# ---------------------------------------------------------------------------
# G3-FINAL2-001 Replay Constructor Remediation Test Matrices
# ---------------------------------------------------------------------------


def _envelope_to_kwargs(
    envelope: GeneralProductionReplayEnvelope,
) -> dict[str, object]:
    return {
        "schema": envelope.schema,
        "seed": envelope.seed,
        "session_id": envelope.session_id,
        "session_secret_hex": envelope.session_secret_hex,
        "initial_hand_count": envelope.initial_hand_count,
        "general_registry_identity": envelope.general_registry_identity,
        "general_profile_identities": dict(envelope.general_profile_identities),
        "general_semantic_payloads": dict(envelope.general_semantic_payloads),
        "general_assignments": dict(envelope.general_assignments),
        "skill_registry_identity": envelope.skill_registry_identity,
        "skill_profile_identities": dict(envelope.skill_profile_identities),
        "derived_skill_assignments": dict(envelope.derived_skill_assignments),
        "primary_general_key": envelope.primary_general_key,
        "owner_id": envelope.owner_id,
        "trigger_event_sequence": envelope.trigger_event_sequence,
        "trigger_event_type": envelope.trigger_event_type,
        "usage_before": dict(envelope.usage_before),
        "usage_after": dict(envelope.usage_after),
        "marks_before": dict(envelope.marks_before),
        "marks_after": dict(envelope.marks_after),
        "skill_runtime_after": dict(envelope.skill_runtime_after),
        "continuation_identity": envelope.continuation_identity,
        "action_ids": tuple(envelope.action_ids),
        "legal_set_hashes": tuple(envelope.legal_set_hashes),
        "chosen_action_semantics": tuple(envelope.chosen_action_semantics),
        "event_slice": tuple(envelope.event_slice),
        "state_hash_before": envelope.state_hash_before,
        "state_hash_after": envelope.state_hash_after,
        "rng_hash": envelope.rng_hash,
        "replay_contract_version": envelope.replay_contract_version,
        "required_authority_capabilities": tuple(
            envelope.required_authority_capabilities or ()
        ),
        "participant_player_ids": tuple(
            envelope.participant_player_ids or ()
        ),
        "production_authority_after": dict(
            envelope.production_authority_after
        ),
        "production_authority_trace": tuple(
            envelope.production_authority_trace
        ),
        "contract_identity": envelope.contract_identity,
    }


def test_wangyuanji_honest_constructor_pass() -> None:
    envelope = _record_qianchong()
    kwargs = _envelope_to_kwargs(envelope)
    constructed = GeneralProductionReplayEnvelope(**kwargs)
    assert (
        constructed.replay_contract_version
        == GENERAL_PRODUCTION_REPLAY_CONTRACT_VERSION_G3_AUTHORITY_V2
    )
    assert constructed.participant_player_ids == ("p1", "p2")
    assert (
        constructed.contract_identity
        == GENERAL_PRODUCTION_REPLAY_CONTRACT_IDENTITY_V2
    )
    result = reexecute_general_production_replay(
        constructed,
        create_authoritative_general_batch_v1_registry(),
        create_proof_slice_v1_registry(),
    )
    assert result.verified


@pytest.mark.parametrize(
    "case,mutate,match",
    (
        (
            "A_participant_none",
            lambda kw: kw.update(participant_player_ids=None),
            "participant_player_ids",
        ),
        (
            "B_participant_omitted",
            lambda kw: kw.pop("participant_player_ids"),
            "participant_player_ids",
        ),
        (
            "C_participant_empty",
            lambda kw: kw.update(participant_player_ids=()),
            "participant_player_ids",
        ),
        (
            "D_participant_single",
            lambda kw: kw.update(participant_player_ids=("p1",)),
            "participant_player_ids",
        ),
        (
            "E_participant_duplicate",
            lambda kw: kw.update(participant_player_ids=("p1", "p1")),
            "participant_player_ids",
        ),
        (
            "F_capabilities_none",
            lambda kw: kw.update(required_authority_capabilities=None),
            "required_authority_capabilities",
        ),
        (
            "G_capabilities_empty",
            lambda kw: kw.update(required_authority_capabilities=()),
            "required_authority_capabilities",
        ),
        (
            "H_version_empty",
            lambda kw: kw.update(replay_contract_version=""),
            "replay_contract_version",
        ),
        (
            "I_contract_identity_empty",
            lambda kw: kw.update(contract_identity=""),
            "contract_identity",
        ),
    ),
)
def test_wangyuanji_constructor_adversarial_matrix_rejects(
    case: str,
    mutate: object,
    match: str,
) -> None:
    del case
    kwargs = _envelope_to_kwargs(_record_qianchong())
    mutate(kwargs)  # type: ignore[operator]
    with pytest.raises(SkillReplayDivergenceError, match=match):
        GeneralProductionReplayEnvelope(**kwargs)


def test_wangyuanji_three_player_guanshi_constructor_matrix() -> None:
    envelope_3p, _pause, _cont, _game = (
        _record_guanshi_three_player_pause_resume()
    )
    assert envelope_3p.participant_player_ids == ("p1", "p2", "p3")

    # 1. participant_player_ids=None -> constructor reject (must NOT canonicalize to ("p1", "p2"))
    kwargs = _envelope_to_kwargs(envelope_3p)
    kwargs["participant_player_ids"] = None
    with pytest.raises(
        SkillReplayDivergenceError, match="participant_player_ids"
    ):
        GeneralProductionReplayEnvelope(**kwargs)

    # 2. participant_player_ids duplicate ("p1", "p2", "p3", "p3") -> constructor reject
    kwargs_dup = _envelope_to_kwargs(envelope_3p)
    kwargs_dup["participant_player_ids"] = ("p1", "p2", "p3", "p3")
    with pytest.raises(
        SkillReplayDivergenceError, match="participant_player_ids"
    ):
        GeneralProductionReplayEnvelope(**kwargs_dup)

    # 3. participant_player_ids truncated to ("p1", "p2") -> constructor passes schema check, but reexecution fails closed
    kwargs_trunc = _envelope_to_kwargs(envelope_3p)
    kwargs_trunc["participant_player_ids"] = ("p1", "p2")
    constructed_trunc = GeneralProductionReplayEnvelope(**kwargs_trunc)
    with pytest.raises(SkillReplayDivergenceError):
        reexecute_general_production_replay(
            constructed_trunc,
            create_authoritative_general_batch_v1_registry(),
            create_proof_slice_v1_registry(),
        )

    # 4. participant_player_ids reordered to ("p2", "p1", "p3") -> reexecution fails closed
    kwargs_reorder = _envelope_to_kwargs(envelope_3p)
    kwargs_reorder["participant_player_ids"] = ("p2", "p1", "p3")
    constructed_reorder = GeneralProductionReplayEnvelope(**kwargs_reorder)
    with pytest.raises(SkillReplayDivergenceError):
        reexecute_general_production_replay(
            constructed_reorder,
            create_authoritative_general_batch_v1_registry(),
            create_proof_slice_v1_registry(),
        )

    # 5. participant_player_ids p3->p4 ("p1", "p2", "p4") -> reexecution fails closed
    kwargs_p4 = _envelope_to_kwargs(envelope_3p)
    kwargs_p4["participant_player_ids"] = ("p1", "p2", "p4")
    constructed_p4 = GeneralProductionReplayEnvelope(**kwargs_p4)
    with pytest.raises(SkillReplayDivergenceError):
        reexecute_general_production_replay(
            constructed_p4,
            create_authoritative_general_batch_v1_registry(),
            create_proof_slice_v1_registry(),
        )

    # 6. participant_player_ids +p4 ("p1", "p2", "p3", "p4") -> reexecution fails closed
    kwargs_plus_p4 = _envelope_to_kwargs(envelope_3p)
    kwargs_plus_p4["participant_player_ids"] = ("p1", "p2", "p3", "p4")
    constructed_plus_p4 = GeneralProductionReplayEnvelope(**kwargs_plus_p4)
    with pytest.raises(SkillReplayDivergenceError):
        reexecute_general_production_replay(
            constructed_plus_p4,
            create_authoritative_general_batch_v1_registry(),
            create_proof_slice_v1_registry(),
        )


@pytest.mark.parametrize(
    "field_name,ctor_value,dict_value",
    (
        ("participant_player_ids", None, None),
        ("participant_player_ids", (), []),
        ("participant_player_ids", ("p1",), ["p1"]),
        ("participant_player_ids", ("p1", "p1"), ["p1", "p1"]),
        ("required_authority_capabilities", None, None),
        ("required_authority_capabilities", (), []),
        ("replay_contract_version", "", ""),
        ("contract_identity", "", ""),
    ),
)
def test_wangyuanji_constructor_vs_from_dict_parity(
    field_name: str,
    ctor_value: object,
    dict_value: object,
) -> None:
    envelope = _record_qianchong()
    kwargs = _envelope_to_kwargs(envelope)
    kwargs[field_name] = ctor_value

    data = copy.deepcopy(envelope.to_dict())
    if dict_value is None:
        data.pop(field_name, None)
    else:
        data[field_name] = dict_value

    # Constructor MUST reject
    with pytest.raises(SkillReplayDivergenceError):
        GeneralProductionReplayEnvelope(**kwargs)

    # from_dict MUST reject
    with pytest.raises(SkillReplayDivergenceError):
        GeneralProductionReplayEnvelope.from_dict(data)


def test_wangyuanji_constructor_vs_from_dict_explicit_missing_cases() -> None:
    envelope = _record_qianchong()

    # 1. participant missing
    kw_p = _envelope_to_kwargs(envelope)
    kw_p.pop("participant_player_ids")
    with pytest.raises(
        SkillReplayDivergenceError, match="participant_player_ids"
    ):
        GeneralProductionReplayEnvelope(**kw_p)

    d_p = copy.deepcopy(envelope.to_dict())
    d_p.pop("participant_player_ids")
    with pytest.raises(SkillReplayDivergenceError):
        GeneralProductionReplayEnvelope.from_dict(d_p)

    # 2. capability missing
    kw_c = _envelope_to_kwargs(envelope)
    kw_c["required_authority_capabilities"] = None
    with pytest.raises(
        SkillReplayDivergenceError, match="required_authority_capabilities"
    ):
        GeneralProductionReplayEnvelope(**kw_c)

    d_c = copy.deepcopy(envelope.to_dict())
    d_c.pop("required_authority_capabilities")
    with pytest.raises(SkillReplayDivergenceError):
        GeneralProductionReplayEnvelope.from_dict(d_c)

    # 3. version missing
    kw_v = _envelope_to_kwargs(envelope)
    kw_v["replay_contract_version"] = ""
    with pytest.raises(
        SkillReplayDivergenceError, match="replay_contract_version"
    ):
        GeneralProductionReplayEnvelope(**kw_v)

    d_v = copy.deepcopy(envelope.to_dict())
    d_v.pop("replay_contract_version")
    with pytest.raises(SkillReplayDivergenceError):
        GeneralProductionReplayEnvelope.from_dict(d_v)

    # 4. contract identity missing
    kw_i = _envelope_to_kwargs(envelope)
    kw_i["contract_identity"] = ""
    with pytest.raises(
        SkillReplayDivergenceError, match="contract_identity"
    ):
        GeneralProductionReplayEnvelope(**kw_i)

    d_i = copy.deepcopy(envelope.to_dict())
    d_i.pop("contract_identity")
    with pytest.raises(SkillReplayDivergenceError):
        GeneralProductionReplayEnvelope.from_dict(d_i)


def test_wangyuanji_g3_final3_001_exploit_regression() -> None:
    """G3-FINAL3-001 regression: reclassifying content to non-G3 while keeping V2 identity must fail-closed.

    Direct constructor and from_dict must NOT fall into legacy branch (which would
    otherwise silently fill participant_player_ids=('p1', 'p2'), version='v1.legacy', capabilities=()).
    """
    envelope = _record_qianchong()
    gen_registry = create_authoritative_general_batch_v1_registry()
    skill_registry = create_proof_slice_v1_registry()
    shamoke_gen = gen_registry.get_general("shamoke")
    jili_skill = skill_registry.get_skill("sgs_skill_jili")

    kwargs = _envelope_to_kwargs(envelope)
    kwargs["primary_general_key"] = "shamoke"
    kwargs["general_assignments"] = {"p1": "shamoke", "p2": "zhugezhan"}
    kwargs["general_profile_identities"] = {
        "shamoke": shamoke_gen.profile_identity,
        "zhugezhan": gen_registry.get_general("zhugezhan").profile_identity,
    }
    kwargs["general_semantic_payloads"] = {
        "shamoke": shamoke_gen.to_dict(),
        "zhugezhan": gen_registry.get_general("zhugezhan").to_dict(),
    }
    kwargs["skill_profile_identities"] = {
        "sgs_skill_jili": jili_skill.profile_identity,
    }
    kwargs["derived_skill_assignments"] = {"p1": ("sgs_skill_jili",), "p2": ()}
    kwargs["participant_player_ids"] = None
    kwargs["required_authority_capabilities"] = None
    kwargs["replay_contract_version"] = ""
    kwargs["contract_identity"] = GENERAL_PRODUCTION_REPLAY_CONTRACT_IDENTITY_V2

    # Direct constructor MUST reject
    with pytest.raises(SkillReplayDivergenceError, match="participant_player_ids"):
        GeneralProductionReplayEnvelope(**kwargs)

    # from_dict MUST also reject
    data = copy.deepcopy(envelope.to_dict())
    data["primary_general_key"] = "shamoke"
    data["general_assignments"] = {"p1": "shamoke", "p2": "zhugezhan"}
    data["general_profile_identities"] = kwargs["general_profile_identities"]
    data["general_semantic_payloads"] = kwargs["general_semantic_payloads"]
    data["skill_profile_identities"] = kwargs["skill_profile_identities"]
    data["derived_skill_assignments"] = {"p1": ["sgs_skill_jili"], "p2": []}
    data.pop("participant_player_ids", None)
    data.pop("required_authority_capabilities", None)
    data.pop("replay_contract_version", None)
    data["contract_identity"] = GENERAL_PRODUCTION_REPLAY_CONTRACT_IDENTITY_V2
    _rehash(data)
    with pytest.raises(SkillReplayDivergenceError):
        GeneralProductionReplayEnvelope.from_dict(data)


def test_current_marker_latch_matrix() -> None:
    """Current marker latch matrix against non-G3 content.

    Any single current marker latches current strict branch and fails closed
    if required fields are missing/omitted.
    """
    envelope = _record_qianchong()
    gen_registry = create_authoritative_general_batch_v1_registry()
    skill_registry = create_proof_slice_v1_registry()
    shamoke_gen = gen_registry.get_general("shamoke")
    jili_skill = skill_registry.get_skill("sgs_skill_jili")

    base_kwargs = _envelope_to_kwargs(envelope)
    base_kwargs["primary_general_key"] = "shamoke"
    base_kwargs["general_assignments"] = {"p1": "shamoke", "p2": "zhugezhan"}
    base_kwargs["general_profile_identities"] = {
        "shamoke": shamoke_gen.profile_identity,
        "zhugezhan": gen_registry.get_general("zhugezhan").profile_identity,
    }
    base_kwargs["general_semantic_payloads"] = {
        "shamoke": shamoke_gen.to_dict(),
        "zhugezhan": gen_registry.get_general("zhugezhan").to_dict(),
    }
    base_kwargs["skill_profile_identities"] = {
        "sgs_skill_jili": jili_skill.profile_identity,
    }
    base_kwargs["derived_skill_assignments"] = {"p1": ("sgs_skill_jili",), "p2": ()}

    # Case A: Only keep V2 version -> latches strict -> rejects missing participant_player_ids
    kw_a = dict(base_kwargs)
    kw_a["replay_contract_version"] = (
        GENERAL_PRODUCTION_REPLAY_CONTRACT_VERSION_G3_AUTHORITY_V2
    )
    kw_a["participant_player_ids"] = None
    kw_a["required_authority_capabilities"] = None
    kw_a["contract_identity"] = ""
    with pytest.raises(SkillReplayDivergenceError, match="participant_player_ids"):
        GeneralProductionReplayEnvelope(**kw_a)

    # Case B: Only keep V2 contract_identity -> latches strict -> rejects missing participant_player_ids
    kw_b = dict(base_kwargs)
    kw_b["replay_contract_version"] = ""
    kw_b["participant_player_ids"] = None
    kw_b["required_authority_capabilities"] = None
    kw_b["contract_identity"] = GENERAL_PRODUCTION_REPLAY_CONTRACT_IDENTITY_V2
    with pytest.raises(SkillReplayDivergenceError, match="participant_player_ids"):
        GeneralProductionReplayEnvelope(**kw_b)

    # Case C: Only keep G3 required capabilities -> latches strict -> rejects missing participant_player_ids
    kw_c = dict(base_kwargs)
    kw_c["replay_contract_version"] = ""
    kw_c["participant_player_ids"] = None
    kw_c["required_authority_capabilities"] = (
        GENERAL_PRODUCTION_REPLAY_G3_REQUIRED_AUTHORITY_CAPABILITIES
    )
    kw_c["contract_identity"] = ""
    with pytest.raises(SkillReplayDivergenceError, match="participant_player_ids"):
        GeneralProductionReplayEnvelope(**kw_c)

    # Case D: Keep V2 version + V2 identity -> latches strict -> rejects missing capabilities
    kw_d = dict(base_kwargs)
    kw_d["replay_contract_version"] = (
        GENERAL_PRODUCTION_REPLAY_CONTRACT_VERSION_G3_AUTHORITY_V2
    )
    kw_d["participant_player_ids"] = ("p1", "p2")
    kw_d["required_authority_capabilities"] = None
    kw_d["contract_identity"] = GENERAL_PRODUCTION_REPLAY_CONTRACT_IDENTITY_V2
    with pytest.raises(
        SkillReplayDivergenceError, match="required_authority_capabilities"
    ):
        GeneralProductionReplayEnvelope(**kw_d)

    # Case E: Keep V2 identity + capabilities -> latches strict -> rejects missing version
    kw_e = dict(base_kwargs)
    kw_e["replay_contract_version"] = ""
    kw_e["participant_player_ids"] = ("p1", "p2")
    kw_e["required_authority_capabilities"] = (
        GENERAL_PRODUCTION_REPLAY_G3_REQUIRED_AUTHORITY_CAPABILITIES
    )
    kw_e["contract_identity"] = GENERAL_PRODUCTION_REPLAY_CONTRACT_IDENTITY_V2
    with pytest.raises(
        SkillReplayDivergenceError, match="replay_contract_version"
    ):
        GeneralProductionReplayEnvelope(**kw_e)

    # Case F: Content itself is Wang Yuanji, but all explicit markers deleted -> content classifier latches strict -> rejects missing participants
    kw_f = dict(_envelope_to_kwargs(envelope))
    kw_f["participant_player_ids"] = None
    kw_f["replay_contract_version"] = ""
    kw_f["required_authority_capabilities"] = None
    kw_f["contract_identity"] = ""
    with pytest.raises(SkillReplayDivergenceError, match="participant_player_ids"):
        GeneralProductionReplayEnvelope(**kw_f)


@pytest.mark.parametrize(
    "case,version,identity,capabilities,match",
    (
        (
            "1_v2_version_with_v1_identity",
            GENERAL_PRODUCTION_REPLAY_CONTRACT_VERSION_G3_AUTHORITY_V2,
            GENERAL_PRODUCTION_REPLAY_CONTRACT_IDENTITY_V1,
            GENERAL_PRODUCTION_REPLAY_G3_REQUIRED_AUTHORITY_CAPABILITIES,
            "contract_identity 与当前生产回放合同不匹配",
        ),
        (
            "2_v1_version_with_v2_identity",
            GENERAL_PRODUCTION_REPLAY_CONTRACT_VERSION_LEGACY,
            GENERAL_PRODUCTION_REPLAY_CONTRACT_IDENTITY_V2,
            GENERAL_PRODUCTION_REPLAY_G3_REQUIRED_AUTHORITY_CAPABILITIES,
            "当前 G3 武将回放不能降级为 legacy contract",
        ),
        (
            "3_v2_identity_with_empty_version",
            "",
            GENERAL_PRODUCTION_REPLAY_CONTRACT_IDENTITY_V2,
            GENERAL_PRODUCTION_REPLAY_G3_REQUIRED_AUTHORITY_CAPABILITIES,
            "当前 G3 回放必须显式提供 replay_contract_version",
        ),
        (
            "4_v2_version_with_empty_capabilities",
            GENERAL_PRODUCTION_REPLAY_CONTRACT_VERSION_G3_AUTHORITY_V2,
            GENERAL_PRODUCTION_REPLAY_CONTRACT_IDENTITY_V2,
            (),
            "当前 G3 回放 required_authority_capabilities 不完整",
        ),
        (
            "5_g3_caps_with_v1_version",
            GENERAL_PRODUCTION_REPLAY_CONTRACT_VERSION_LEGACY,
            GENERAL_PRODUCTION_REPLAY_CONTRACT_IDENTITY_V2,
            GENERAL_PRODUCTION_REPLAY_G3_REQUIRED_AUTHORITY_CAPABILITIES,
            "当前 G3 武将回放不能降级为 legacy contract",
        ),
        (
            "6_g3_caps_with_v1_identity",
            GENERAL_PRODUCTION_REPLAY_CONTRACT_VERSION_G3_AUTHORITY_V2,
            GENERAL_PRODUCTION_REPLAY_CONTRACT_IDENTITY_V1,
            GENERAL_PRODUCTION_REPLAY_G3_REQUIRED_AUTHORITY_CAPABILITIES,
            "contract_identity 与当前生产回放合同不匹配",
        ),
    ),
)
def test_marker_conflict_matrix_rejects(
    case: str,
    version: str,
    identity: str,
    capabilities: tuple[str, ...],
    match: str,
) -> None:
    del case
    envelope = _record_qianchong()
    kwargs = _envelope_to_kwargs(envelope)
    kwargs["replay_contract_version"] = version
    kwargs["contract_identity"] = identity
    kwargs["required_authority_capabilities"] = capabilities

    # Constructor MUST reject with exact fail-closed divergence
    with pytest.raises(SkillReplayDivergenceError, match=match):
        GeneralProductionReplayEnvelope(**kwargs)

    # from_dict parity
    data = copy.deepcopy(envelope.to_dict())
    if version:
        data["replay_contract_version"] = version
    else:
        data.pop("replay_contract_version", None)
    if identity:
        data["contract_identity"] = identity
    else:
        data.pop("contract_identity", None)
    data["required_authority_capabilities"] = list(capabilities)
    _rehash(data)
    with pytest.raises(SkillReplayDivergenceError):
        GeneralProductionReplayEnvelope.from_dict(data)


def test_requires_current_general_production_replay_contract_helper() -> None:
    fn = skill_replay_module._requires_current_general_production_replay_contract

    # 1. Honest G3 content -> True regardless of markers
    assert (
        fn(
            primary_general_key="wangyuanji",
            general_assignments={"p1": "wangyuanji"},
            derived_skill_assignments={"p1": ("sgs_skill_qianchong",)},
        )
        is True
    )

    # 2. Honest non-G3 content + all empty -> False (legacy)
    assert (
        fn(
            primary_general_key="shamoke",
            general_assignments={"p1": "shamoke"},
            derived_skill_assignments={"p1": ("sgs_skill_jili",)},
        )
        is False
    )
    # 3. Non-G3 + V2 version -> True (latched)
    assert (
        fn(
            primary_general_key="shamoke",
            general_assignments={"p1": "shamoke"},
            derived_skill_assignments={"p1": ("sgs_skill_jili",)},
            replay_contract_version=GENERAL_PRODUCTION_REPLAY_CONTRACT_VERSION_G3_AUTHORITY_V2,
        )
        is True
    )

    # 4. Non-G3 + V2 identity -> True (latched)
    assert (
        fn(
            primary_general_key="shamoke",
            general_assignments={"p1": "shamoke"},
            derived_skill_assignments={"p1": ("sgs_skill_jili",)},
            contract_identity=GENERAL_PRODUCTION_REPLAY_CONTRACT_IDENTITY_V2,
        )
        is True
    )

    # 5. Non-G3 + G3 capabilities -> True (latched)
    assert (
        fn(
            primary_general_key="shamoke",
            general_assignments={"p1": "shamoke"},
            derived_skill_assignments={"p1": ("sgs_skill_jili",)},
            required_authority_capabilities=GENERAL_PRODUCTION_REPLAY_G3_REQUIRED_AUTHORITY_CAPABILITIES,
        )
        is True
    )

    # 6. Non-G3 + single G3 capability -> True (latched)
    assert (
        fn(
            primary_general_key="shamoke",
            general_assignments={"p1": "shamoke"},
            derived_skill_assignments={"p1": ("sgs_skill_jili",)},
            required_authority_capabilities=("production_authority_trace_per_step",),
        )
        is True
    )

    # 7. Non-G3 + V1 version + V1 identity + empty caps -> False
    assert (
        fn(
            primary_general_key="shamoke",
            general_assignments={"p1": "shamoke"},
            derived_skill_assignments={"p1": ("sgs_skill_jili",)},
            replay_contract_version=GENERAL_PRODUCTION_REPLAY_CONTRACT_VERSION_LEGACY,
            contract_identity=GENERAL_PRODUCTION_REPLAY_CONTRACT_IDENTITY_V1,
            required_authority_capabilities=(),
        )
        is False
    )
