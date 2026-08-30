# -*- coding: utf-8 -*-
"""Cold-load replay and deep-tamper tests for G2 Zhugezhan."""

from __future__ import annotations

import copy
import hashlib
import json

import pytest

import scripts.sgs_engine.production_batch as production_batch_module
from scripts.sgs_engine.actions import ActionType, LegalAction
from scripts.sgs_engine.events import EventType
from scripts.sgs_engine.generals import create_authoritative_general_batch_v1_registry
from scripts.sgs_engine.model import ZoneRef
from scripts.sgs_engine.production_batch import (
    BatchActionIdController,
    ProductionBasicCardBatch,
    ProductionPhase,
)
from scripts.sgs_engine.replay import sha256_value
from scripts.sgs_engine.skill_impl_v1 import create_proof_slice_v1_registry
from scripts.sgs_engine.skill_replay import (
    GeneralProductionReplayEnvelope,
    SkillReplayDivergenceError,
    action_semantics,
    compute_state_hash,
    legal_actions_semantic_hash,
    reexecute_general_production_replay,
    rng_calls_hash,
)


def _rehash(data: dict[str, object]) -> None:
    data["records_identity"] = sha256_value(
        {
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
    )
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
) -> ProductionBasicCardBatch:
    return ProductionBasicCardBatch(
        seed=seed,
        first_player_id=first_player_id,
        player_hp=(3, 4),
        player_max_hp=(3, 4),
        initial_hand_count=initial_hand_count,
        general_registry=create_authoritative_general_batch_v1_registry(),
        general_assignments=general_assignments or {"p1": "zhugezhan"},
        skill_registry=create_proof_slice_v1_registry(),
        session_id="b" * 32,
        session_secret=b"\x33" * 32,
    )


def _record_common(
    game: ProductionBasicCardBatch,
    choose: list[LegalAction],
) -> tuple[list[str], list[str], list[dict[str, object]]]:
    action_ids: list[str] = []
    legal_hashes: list[str] = []
    semantics: list[dict[str, object]] = []
    for action in choose:
        legal = game.legal_actions()
        live = next(item for item in legal if item.action_id == action.action_id)
        legal_hashes.append(legal_actions_semantic_hash(legal))
        semantics.append(action_semantics(live))
        assert live.action_id
        action_ids.append(live.action_id)
        game.step(BatchActionIdController(live.action_id))
    return action_ids, legal_hashes, semantics


class _Recorder:
    def __init__(self, game: ProductionBasicCardBatch) -> None:
        self.game = game
        self.action_ids: list[str] = []
        self.legal_hashes: list[str] = []
        self.semantics: list[dict[str, object]] = []

    def take(self, action: LegalAction) -> None:
        legal = self.game.legal_actions()
        live = next(item for item in legal if item.action_id == action.action_id)
        self.legal_hashes.append(legal_actions_semantic_hash(legal))
        self.semantics.append(action_semantics(live))
        assert live.action_id
        self.action_ids.append(live.action_id)
        self.game.step(BatchActionIdController(live.action_id))

    def operation(self, name: str) -> LegalAction:
        action = next(
            item for item in self.game.legal_actions()
            if item.payload.get("operation") == name
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
    primary_general_key: str = "zhugezhan",
    owner_id: str = "p1",
    general_assignments: dict[str, str] | None = None,
) -> GeneralProductionReplayEnvelope:
    game = recorder.game
    general_registry = game.general_registry
    skill_registry = game.skill_runtime.registry
    assignments = general_assignments or {"p1": "zhugezhan"}
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
    )


def _record_zuilun() -> GeneralProductionReplayEnvelope:
    game = _new_game(17, first_player_id="p1")
    recorder = _Recorder(game)
    state_before = compute_state_hash(game.state)
    for operation in ("proceed_prepare", "proceed_judgment", "proceed_draw"):
        recorder.operation(operation)
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
    activate = next(
        item for item in game.legal_actions()
        if item.action_type is ActionType.ACTIVATE_SKILL
        and item.skill_id == "sgs_skill_zuilun"
    )
    skill_before = game.skill_runtime.get_skill_state("p1", "sgs_skill_zuilun")
    trigger_sequence = int(activate.payload["trigger_event_sequence"])
    trigger_type = str(activate.payload["trigger_event_type"])
    continuation = str(activate.payload["continuation_identity"])
    recorder.take(activate)
    selection = game.legal_actions()[0]
    recorder.take(selection)
    skill_after = game.skill_runtime.get_skill_state("p1", "sgs_skill_zuilun")
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


def _finish_play_and_discard(recorder: _Recorder) -> None:
    game = recorder.game
    recorder.operation("end_play_phase")
    while game.phase is ProductionPhase.DISCARD:
        submit = next(
            (
                item for item in game.legal_actions()
                if item.payload.get("operation") == "discard_phase_submit"
            ),
            None,
        )
        if submit is not None:
            recorder.take(submit)
        else:
            recorder.operation("select_discard_card")


def _record_zuilun_n0_nonterminal() -> GeneralProductionReplayEnvelope:
    game = _new_game(19, first_player_id="p1", initial_hand_count=2)
    recorder = _Recorder(game)
    state_before = compute_state_hash(game.state)
    for operation in ("proceed_prepare", "proceed_judgment", "proceed_draw"):
        recorder.operation(operation)
    _finish_play_and_discard(recorder)
    activate = next(
        item for item in game.legal_actions()
        if item.action_type is ActionType.ACTIVATE_SKILL
        and item.skill_id == "sgs_skill_zuilun"
    )
    assert activate.payload["n"] == 0
    skill_before = game.skill_runtime.get_skill_state("p1", "sgs_skill_zuilun")
    trigger_sequence = int(activate.payload["trigger_event_sequence"])
    trigger_type = str(activate.payload["trigger_event_type"])
    continuation = str(activate.payload["continuation_identity"])
    recorder.take(activate)
    target = next(
        item for item in game.legal_actions()
        if item.payload.get("operation") == "skill_lose_hp_target_choice"
        and item.target_ids == ("p2",)
    )
    recorder.take(target)
    skill_after = game.skill_runtime.get_skill_state("p1", "sgs_skill_zuilun")
    assert [
        event.target_ids for event in game.events
        if event.event_type is EventType.LOSE_HP
    ][-2:] == [("p1",), ("p2",)]
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
        initial_hand_count=2,
    )


def _record_zuilun_n0_terminal() -> GeneralProductionReplayEnvelope:
    game = _new_game(9462, first_player_id="p1", initial_hand_count=2)
    recorder = _Recorder(game)
    state_before = compute_state_hash(game.state)
    for operation in ("proceed_prepare", "proceed_judgment", "proceed_draw"):
        recorder.operation(operation)
    for _ in range(2):
        duel = next(
            item for item in game.legal_actions()
            if item.action_type is ActionType.USE_CARD
            and item.payload.get("card_key") == "sgs_trick_juedou"
            and item.target_ids == ("p2",)
        )
        recorder.take(duel)
        while game.phase is ProductionPhase.TRICK_RESPONSE:
            recorder.operation("pass_trick_response")
        recorder.operation("play_slash_for_duel")
        recorder.operation("pass_duel_slash")
    assert game.state.players_by_id["p1"].hp == 1
    assert len(game.state.card_ids_in(ZoneRef.hand("p2"))) == 0
    _finish_play_and_discard(recorder)
    activate = next(
        item for item in game.legal_actions()
        if item.action_type is ActionType.ACTIVATE_SKILL
        and item.skill_id == "sgs_skill_zuilun"
    )
    assert activate.payload["n"] == 0
    skill_before = game.skill_runtime.get_skill_state("p1", "sgs_skill_zuilun")
    trigger_sequence = int(activate.payload["trigger_event_sequence"])
    trigger_type = str(activate.payload["trigger_event_type"])
    continuation = str(activate.payload["continuation_identity"])
    recorder.take(activate)
    while not game.is_finished:
        recorder.operation("pass_rescue")
    skill_after = game.skill_runtime.get_skill_state("p1", "sgs_skill_zuilun")
    assert not game.state.players_by_id["p1"].alive
    assert not any(
        event.event_type is EventType.LOSE_HP and event.target_ids == ("p2",)
        for event in game.events
    )
    assert any(event.event_type is EventType.VICTORY for event in game.events)
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
        initial_hand_count=2,
    )


def _record_fuyin(*, ineffective: bool = False) -> GeneralProductionReplayEnvelope:
    selected: tuple[ProductionBasicCardBatch, LegalAction] | None = None
    seeds = (231,) if ineffective else range(1, 80)
    initial_hand_count = 2 if ineffective else 4
    for seed in seeds:
        candidate = _new_game(
            seed,
            first_player_id="p2",
            initial_hand_count=initial_hand_count,
        )
        rec = _Recorder(candidate)
        for operation in ("proceed_prepare", "proceed_judgment", "proceed_draw"):
            rec.operation(operation)
        if ineffective:
            wine = next(
                item for item in candidate.legal_actions()
                if item.action_type is ActionType.USE_CARD
                and item.payload.get("card_key") == "sgs_basic_jiu"
            )
            rec.take(wine)
        slash = next(
            (
                item for item in candidate.legal_actions()
                if item.action_type is ActionType.USE_CARD
                and item.payload.get("card_key") in {
                    "sgs_basic_sha", "sgs_basic_huosha", "sgs_basic_leisha"
                }
                and item.target_ids == ("p1",)
            ),
            None,
        )
        if slash is not None:
            selected = (candidate, slash)
            recorder = rec
            break
    assert selected is not None
    game, slash = selected
    state_before_game = _new_game(
        game._rng.seed,
        first_player_id="p2",
        initial_hand_count=initial_hand_count,
    )
    state_before = compute_state_hash(state_before_game.state)
    skill_before = game.skill_runtime.get_skill_state("p1", "sgs_skill_fuyin")
    recorder.take(slash)
    source = next(
        event for event in game.events
        if event.event_type is EventType.CARD_USED
        and event.card_instance_id == slash.card_instance_id
    )
    checked = next(
        event for event in game.events
        if event.event_type is EventType.SKILL_CONDITION_EVALUATED
        and event.payload.get("skill_id") == "sgs_skill_fuyin"
        and event.payload.get("source_event_sequence") == source.sequence
    )
    target_events = [
        event for event in game.events
        if event.event_type is EventType.TARGET_EFFECT_INEFFECTIVE
        and event.payload.get("source_event_sequence") == source.sequence
    ]
    assert checked.payload["target_effect_ineffective"] is ineffective
    assert len(target_events) == int(ineffective)
    skill_after = game.skill_runtime.get_skill_state("p1", "sgs_skill_fuyin")
    return _build_envelope(
        recorder,
        trigger_sequence=int(source.sequence),
        trigger_type=source.event_type.value,
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
        continuation_identity=str(checked.payload["resolution_identity"]),
        state_before=state_before,
        initial_hand_count=initial_hand_count,
    )


def _record_fuyin_true() -> GeneralProductionReplayEnvelope:
    return _record_fuyin(ineffective=True)


def _record_lebusi_skip_play_auto_end() -> GeneralProductionReplayEnvelope:
    for seed in range(1, 500):
        game = _new_game(
            seed,
            first_player_id="p2",
            initial_hand_count=1,
        )
        recorder = _Recorder(game)
        state_before = compute_state_hash(game.state)
        for operation in ("proceed_prepare", "proceed_judgment", "proceed_draw"):
            recorder.operation(operation)
        lebusi = next(
            (
                item
                for item in game.legal_actions()
                if item.action_type is ActionType.USE_CARD
                and item.payload.get("card_key") == "sgs_delayed_lebusi"
                and item.target_ids == ("p1",)
            ),
            None,
        )
        if lebusi is None:
            continue
        recorder.take(lebusi)
        _finish_play_and_discard(recorder)
        recorder.operation("end_turn")
        recorder.operation("proceed_prepare")
        recorder.operation("proceed_judgment")
        while game.phase is ProductionPhase.JUDGMENT_WUXIE:
            recorder.operation("pass_judgment_wuxie")
        if "play" not in game.runtime.skipped_phases:
            continue
        recorder.operation("proceed_judgment")
        assert game.phase is ProductionPhase.DRAW
        recorder.operation("proceed_draw")
        if game.phase is not ProductionPhase.END:
            continue
        decline = next(
            item
            for item in game.legal_actions()
            if item.action_type is ActionType.PASS
            and item.skill_id == "sgs_skill_zuilun"
        )
        skill_before = game.skill_runtime.get_skill_state(
            "p1", "sgs_skill_zuilun"
        )
        trigger_sequence = int(decline.payload["trigger_event_sequence"])
        continuation = str(decline.payload["continuation_identity"])
        recorder.take(decline)
        skill_after = game.skill_runtime.get_skill_state(
            "p1", "sgs_skill_zuilun"
        )
        assert len(
            [
                event
                for event in game.events
                if event.event_type is EventType.END_PHASE_STARTED
                and event.target_ids == ("p1",)
            ]
        ) == 1
        return _build_envelope(
            recorder,
            trigger_sequence=trigger_sequence,
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
            continuation_identity=continuation,
            state_before=state_before,
            initial_hand_count=1,
        )
    raise AssertionError("未找到可重放的乐不思蜀 skip-PLAY → auto-END seed")


def _record_jili_activate_with_fuyin_runtime_merge() -> GeneralProductionReplayEnvelope:
    assignments = {"p1": "zhugezhan", "p2": "shamoke"}
    for seed in range(1, 200):
        game = _new_game(
            seed,
            first_player_id="p2",
            initial_hand_count=1,
            general_assignments=assignments,
        )
        recorder = _Recorder(game)
        state_before = compute_state_hash(game.state)
        for operation in ("proceed_prepare", "proceed_judgment", "proceed_draw"):
            recorder.operation(operation)
        slash = next(
            (
                item
                for item in game.legal_actions()
                if item.action_type is ActionType.USE_CARD
                and item.payload.get("card_key")
                in {"sgs_basic_sha", "sgs_basic_huosha", "sgs_basic_leisha"}
                and item.target_ids == ("p1",)
            ),
            None,
        )
        if slash is None:
            continue
        recorder.take(slash)
        activate = next(
            item
            for item in game.legal_actions()
            if item.action_type is ActionType.ACTIVATE_SKILL
            and item.skill_id == "sgs_skill_jili"
        )
        skill_before = game.skill_runtime.get_skill_state(
            "p2", "sgs_skill_jili"
        )
        trigger_sequence = int(activate.payload["trigger_event_sequence"])
        trigger_type = str(activate.payload["trigger_event_type"])
        continuation = str(activate.payload["continuation_identity"])
        recorder.take(activate)
        skill_after = game.skill_runtime.get_skill_state(
            "p2", "sgs_skill_jili"
        )
        fuyin_after = game.skill_runtime.get_skill_state(
            "p1", "sgs_skill_fuyin"
        )
        assert skill_after.uses_this_turn == 1
        assert (
            fuyin_after.marks["fuyin_consumed_turn"]
            == game.runtime.turn_number
        )
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
            primary_general_key="shamoke",
            owner_id="p2",
            general_assignments=assignments,
        )
    raise AssertionError("未找到可重放的 Jili ACTIVATE + Fuyin seed")


@pytest.mark.parametrize(
    "record",
    (
        _record_zuilun,
        _record_zuilun_n0_nonterminal,
        _record_zuilun_n0_terminal,
        _record_fuyin,
        _record_fuyin_true,
        _record_lebusi_skip_play_auto_end,
        _record_jili_activate_with_fuyin_runtime_merge,
    ),
)
def test_zhugezhan_cold_load_replay_clean(record: object) -> None:
    envelope = record()
    result = reexecute_general_production_replay(
        envelope,
        create_authoritative_general_batch_v1_registry(),
        create_proof_slice_v1_registry(),
    )
    assert result.verified
    assert result.steps_verified == len(envelope.action_ids)


def test_lebusi_skip_play_auto_end_replay_has_one_formal_end_checkpoint() -> None:
    envelope = _record_lebusi_skip_play_auto_end()
    assert any(
        event["event_type"] == EventType.PHASE_SKIPPED.value
        and event["payload"].get("skipped_phase") == "play"
        for event in envelope.event_slice
    )
    assert len(
        [
            event
            for event in envelope.event_slice
            if event["event_type"] == EventType.END_PHASE_STARTED.value
            and event["target_ids"] == ["p1"]
        ]
    ) == 1


@pytest.mark.parametrize("tamper_case", ("jili_usage", "fuyin_consumed"))
def test_jili_fuyin_full_runtime_after_deep_tamper_rejected(
    tamper_case: str,
) -> None:
    data = copy.deepcopy(_record_jili_activate_with_fuyin_runtime_merge().to_dict())
    players = data["skill_runtime_after"]["player_skills"]
    if tamper_case == "jili_usage":
        players["p2"]["sgs_skill_jili"]["uses_this_turn"] = 0
    else:
        players["p1"]["sgs_skill_fuyin"]["marks"].pop(
            "fuyin_consumed_turn"
        )
    _rehash(data)
    tampered = GeneralProductionReplayEnvelope.from_dict(data)
    with pytest.raises(
        SkillReplayDivergenceError, match="完整 SkillRuntime runtime_after"
    ):
        reexecute_general_production_replay(
            tampered,
            create_authoritative_general_batch_v1_registry(),
            create_proof_slice_v1_registry(),
        )


@pytest.mark.parametrize(
    "tamper_case",
    (
        "condition_n",
        "condition_fact",
        "top3_order",
        "selected_card",
        "remaining_order",
    ),
)
def test_zuilun_deep_tamper_rehashed_outer_records_rejected(tamper_case: str) -> None:
    data = copy.deepcopy(_record_zuilun().to_dict())
    semantics = data["chosen_action_semantics"]
    activate = next(item for item in semantics if item["skill_id"] == "sgs_skill_zuilun")
    selection = next(
        item for item in semantics
        if item["payload"].get("operation") == "private_card_selection_submit"
    )
    observed_event = next(
        item for item in data["event_slice"]
        if item["event_type"] == EventType.PRIVATE_CARDS_OBSERVED.value
        and item["payload"]["stage"] == "observed"
    )
    if tamper_case == "condition_n":
        activate["payload"]["n"] = (activate["payload"]["n"] + 1) % 4
    elif tamper_case == "condition_fact":
        activate["payload"]["dealt_damage_this_turn"] = not activate["payload"][
            "dealt_damage_this_turn"
        ]
    elif tamper_case == "top3_order":
        observed_event["payload"]["observed_card_ids"][:2] = reversed(
            observed_event["payload"]["observed_card_ids"][:2]
        )
    elif tamper_case == "selected_card":
        selection["payload"]["selected_card_ids"] = selection["payload"][
            "remaining_top_order"
        ][:1]
    else:
        selection["payload"]["remaining_top_order"] = list(
            reversed(selection["payload"]["remaining_top_order"])
        )
    _rehash(data)
    tampered = GeneralProductionReplayEnvelope.from_dict(data)
    with pytest.raises(SkillReplayDivergenceError):
        reexecute_general_production_replay(
            tampered,
            create_authoritative_general_batch_v1_registry(),
            create_proof_slice_v1_registry(),
        )


@pytest.mark.parametrize(
    "tamper_case",
    (
        "n_nonzero",
        "condition_fact",
        "self_hp_loss",
        "pending_target_legal_set",
        "target_unknown",
        "target_stale",
        "target_illegal_self",
        "hp_loss_target_choice",
        "trigger_sequence",
        "trigger_type",
        "continuation_identity",
        "per_turn_runtime",
        "state_before",
        "state_after",
        "event_slice",
        "rng_hash",
    ),
)
def test_zuilun_n0_deep_tamper_rehashed_outer_records_rejected(
    tamper_case: str,
) -> None:
    data = copy.deepcopy(_record_zuilun_n0_nonterminal().to_dict())
    semantics = data["chosen_action_semantics"]
    activate = next(
        item for item in semantics
        if item["skill_id"] == "sgs_skill_zuilun"
        and item["payload"].get("operation") == "activate_skill"
    )
    target_index = next(
        index for index, item in enumerate(semantics)
        if item["payload"].get("operation") == "skill_lose_hp_target_choice"
    )
    target = semantics[target_index]
    self_loss = next(
        item for item in data["event_slice"]
        if item["event_type"] == EventType.LOSE_HP.value
        and item["target_ids"] == ["p1"]
    )
    condition = next(
        item for item in data["event_slice"]
        if item["event_type"] == EventType.SKILL_CONDITION_EVALUATED.value
        and item["payload"].get("skill_id") == "sgs_skill_zuilun"
    )

    if tamper_case == "n_nonzero":
        activate["payload"]["n"] = 1
    elif tamper_case == "condition_fact":
        activate["payload"]["no_discard_this_turn"] = True
    elif tamper_case == "self_hp_loss":
        self_loss["payload"]["amount"] = 2
    elif tamper_case == "pending_target_legal_set":
        data["legal_set_hashes"][target_index] = "0" * 64
    elif tamper_case == "target_unknown":
        target["target_ids"] = ["p9"]
        target["payload"]["target_id"] = "p9"
    elif tamper_case == "target_stale":
        target["payload"]["expected_revision"] += 1
    elif tamper_case == "target_illegal_self":
        target["target_ids"] = ["p1"]
        target["payload"]["target_id"] = "p1"
    elif tamper_case == "hp_loss_target_choice":
        target["operation"] = "skill_lose_hp_target_choice_tampered"
        target["payload"]["operation"] = "skill_lose_hp_target_choice_tampered"
    elif tamper_case == "trigger_sequence":
        data["trigger_event_sequence"] += 1
    elif tamper_case == "trigger_type":
        data["trigger_event_type"] = EventType.CARD_USED.value
    elif tamper_case == "continuation_identity":
        data["continuation_identity"] = "0" * 64
    elif tamper_case == "per_turn_runtime":
        data["usage_after"]["uses_this_turn"] += 1
    elif tamper_case == "state_before":
        data["state_hash_before"] = "0" * 64
    elif tamper_case == "state_after":
        data["state_hash_after"] = "0" * 64
    elif tamper_case == "event_slice":
        condition["payload"]["n"] = 1
    else:
        data["rng_hash"] = "0" * 64

    _rehash(data)
    tampered = GeneralProductionReplayEnvelope.from_dict(data)
    with pytest.raises(SkillReplayDivergenceError):
        reexecute_general_production_replay(
            tampered,
            create_authoritative_general_batch_v1_registry(),
            create_proof_slice_v1_registry(),
        )


def test_zuilun_n0_terminal_replay_rejects_phantom_second_hp_loss() -> None:
    data = copy.deepcopy(_record_zuilun_n0_terminal().to_dict())
    phantom = copy.deepcopy(
        next(
            item for item in data["event_slice"]
            if item["event_type"] == EventType.LOSE_HP.value
            and item["target_ids"] == ["p1"]
        )
    )
    phantom["sequence"] = data["event_slice"][-1]["sequence"] + 1
    phantom["target_ids"] = ["p2"]
    phantom["payload"]["reason"] = "sgs_skill_zuilun:other"
    data["event_slice"].append(phantom)
    _rehash(data)
    tampered = GeneralProductionReplayEnvelope.from_dict(data)
    with pytest.raises(SkillReplayDivergenceError):
        reexecute_general_production_replay(
            tampered,
            create_authoritative_general_batch_v1_registry(),
            create_proof_slice_v1_registry(),
        )


@pytest.mark.parametrize(
    "tamper_case",
    ("consumed", "user_count", "owner_count", "ineffective"),
)
def test_fuyin_deep_tamper_rehashed_outer_records_rejected(tamper_case: str) -> None:
    data = copy.deepcopy(_record_fuyin().to_dict())
    event = next(
        item for item in data["event_slice"]
        if item["event_type"] == EventType.SKILL_CONDITION_EVALUATED.value
        and item["payload"].get("skill_id") == "sgs_skill_fuyin"
    )
    if tamper_case == "consumed":
        data["marks_after"]["fuyin_consumed_turn"] += 1
    elif tamper_case == "user_count":
        event["payload"]["user_hand_count_after_use"] += 1
    elif tamper_case == "owner_count":
        event["payload"]["owner_hand_count"] += 1
    else:
        event["payload"]["target_effect_ineffective"] = not event["payload"][
            "target_effect_ineffective"
        ]
    _rehash(data)
    tampered = GeneralProductionReplayEnvelope.from_dict(data)
    with pytest.raises(SkillReplayDivergenceError):
        reexecute_general_production_replay(
            tampered,
            create_authoritative_general_batch_v1_registry(),
            create_proof_slice_v1_registry(),
        )


def test_fuyin_consumption_and_ineffective_event_are_independently_authenticated() -> None:
    false_data = copy.deepcopy(_record_fuyin().to_dict())
    false_condition = next(
        item for item in false_data["event_slice"]
        if item["event_type"] == EventType.SKILL_CONDITION_EVALUATED.value
        and item["payload"].get("skill_id") == "sgs_skill_fuyin"
    )
    assert false_condition["payload"]["consumed_after"] is True
    assert false_condition["payload"]["target_effect_ineffective"] is False
    assert not any(
        item["event_type"] == EventType.TARGET_EFFECT_INEFFECTIVE.value
        for item in false_data["event_slice"]
    )
    false_condition["payload"]["target_effect_ineffective"] = True
    _rehash(false_data)
    with pytest.raises(SkillReplayDivergenceError):
        reexecute_general_production_replay(
            GeneralProductionReplayEnvelope.from_dict(false_data),
            create_authoritative_general_batch_v1_registry(),
            create_proof_slice_v1_registry(),
        )

    true_data = copy.deepcopy(_record_fuyin_true().to_dict())
    target_index = next(
        index for index, item in enumerate(true_data["event_slice"])
        if item["event_type"] == EventType.TARGET_EFFECT_INEFFECTIVE.value
    )
    true_data["event_slice"].pop(target_index)
    _rehash(true_data)
    with pytest.raises(SkillReplayDivergenceError):
        reexecute_general_production_replay(
            GeneralProductionReplayEnvelope.from_dict(true_data),
            create_authoritative_general_batch_v1_registry(),
            create_proof_slice_v1_registry(),
        )


def test_zhugezhan_live_frozen_object_tamper_rejected_before_constructor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    envelope = _record_zuilun()
    general_registry = create_authoritative_general_batch_v1_registry()
    object.__setattr__(
        general_registry.get_general("zhugezhan"),
        "skill_ids",
        ("sgs_skill_jili",),
    )
    calls = 0

    def sentinel(*args: object, **kwargs: object) -> object:
        nonlocal calls
        calls += 1
        raise AssertionError("tamper preflight must run before constructor")

    monkeypatch.setattr(
        production_batch_module, "ProductionBasicCardBatch", sentinel
    )
    with pytest.raises(SkillReplayDivergenceError, match="canonical payload"):
        reexecute_general_production_replay(
            envelope, general_registry, create_proof_slice_v1_registry()
        )
    assert calls == 0
