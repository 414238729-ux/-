# -*- coding: utf-8 -*-
"""Replay tests for Authoritative General Replay Envelope and Shamoke verification."""

from __future__ import annotations

import copy
from dataclasses import replace
import hashlib
import json
import pytest

import scripts.sgs_engine.production_batch as production_batch_module
import scripts.sgs_engine.skill_replay as skill_replay_module

from scripts.sgs_engine.actions import ActionType
from scripts.sgs_engine.events import EventType
from scripts.sgs_engine.generals import (
    GeneralDefinition,
    create_authoritative_general_batch_v1_registry,
)
from scripts.sgs_engine.model import CharacterGender
from scripts.sgs_engine.production_batch import (
    BatchActionIdController,
    ProductionBasicCardBatch,
    ProductionPhase,
)
from scripts.sgs_engine.skill_impl_v1 import create_proof_slice_v1_registry
from scripts.sgs_engine.skill_replay import (
    GENERAL_PRODUCTION_REPLAY_CONTRACT_IDENTITY_V1,
    GENERAL_PRODUCTION_REPLAY_SCHEMA_V1,
    GeneralProductionReplayEnvelope,
    SkillReplayDivergenceError,
    action_semantics,
    compute_state_hash,
    legal_actions_semantic_hash,
    reexecute_general_production_replay,
    rng_calls_hash,
)
from scripts.sgs_engine.replay import sha256_value


def _recompute_general_envelope_identities(data: dict) -> None:
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


def _semantic_profile_identity(payload: dict) -> str:
    canonical = dict(payload)
    canonical.pop("profile_identity")
    return sha256_value(canonical)


def _record_shamoke_replay(seed: int = 1) -> tuple[GeneralProductionReplayEnvelope, ProductionBasicCardBatch]:
    gen_registry = create_authoritative_general_batch_v1_registry()
    skill_registry = create_proof_slice_v1_registry()
    assignments = {"p1": "shamoke"}
    session_id = "a" * 32
    secret = b"\x22" * 32

    game = ProductionBasicCardBatch(
        seed=seed,
        first_player_id="p1",
        session_id=session_id,
        session_secret=secret,
        general_registry=gen_registry,
        general_assignments=assignments,
        skill_registry=skill_registry,
    )

    action_ids: list[str] = []
    legal_hashes: list[str] = []
    chosen_semantics: list[dict] = []

    def take(action: object) -> None:
        legal = game.legal_actions()
        legal_hashes.append(legal_actions_semantic_hash(legal))
        assert action.action_id
        chosen_semantics.append(action_semantics(action))
        action_ids.append(action.action_id)
        game.step(BatchActionIdController(action.action_id))

    state_before = compute_state_hash(game.state)

    for operation in ("proceed_prepare", "proceed_judgment", "proceed_draw"):
        current = next(
            item for item in game.legal_actions() if item.payload.get("operation") == operation
        )
        take(current)

    assert game.phase is ProductionPhase.PLAY

    # Play card #1
    play_action = next(a for a in game.legal_actions() if a.action_type is ActionType.USE_CARD)
    take(play_action)

    # Activate Jili
    jili_activate = next(
        a for a in game.legal_actions()
        if a.action_type is ActionType.ACTIVATE_SKILL and a.skill_id == "sgs_skill_jili"
    )
    assert game.skill_runtime is not None
    before_skill = game.skill_runtime.get_skill_state("p1", "sgs_skill_jili")
    usage_before = {
        "uses_this_phase": before_skill.uses_this_phase,
        "uses_this_turn": before_skill.uses_this_turn,
    }
    marks_before = dict(before_skill.marks)
    trigger_event_sequence = jili_activate.payload["trigger_event_sequence"]
    trigger_event_type = jili_activate.payload["trigger_event_type"]
    continuation_identity = jili_activate.payload["continuation_identity"]
    take(jili_activate)
    after_skill = game.skill_runtime.get_skill_state("p1", "sgs_skill_jili")
    usage_after = {
        "uses_this_phase": after_skill.uses_this_phase,
        "uses_this_turn": after_skill.uses_this_turn,
    }
    marks_after = dict(after_skill.marks)

    state_after = compute_state_hash(game.state)
    events = tuple(e.to_replay_dict() for e in game.events)

    gen_profiles = {k: gen_registry.get_general(k).profile_identity for k in ("shamoke",)}
    gen_semantics = {k: gen_registry.get_general(k).to_dict() for k in ("shamoke",)}
    skill_profiles = {k: skill_registry.get_skill(k).profile_identity for k in ("sgs_skill_jili",)}
    derived = {"p1": ("sgs_skill_jili",)}

    envelope = GeneralProductionReplayEnvelope(
        seed=seed,
        session_id=session_id,
        session_secret_hex=secret.hex(),
        initial_hand_count=4,
        general_registry_identity=gen_registry.registry_identity,
        general_profile_identities=gen_profiles,
        general_semantic_payloads=gen_semantics,
        general_assignments=assignments,
        skill_registry_identity=skill_registry.registry_identity,
        skill_profile_identities=skill_profiles,
        derived_skill_assignments=derived,
        primary_general_key="shamoke",
        owner_id="p1",
        trigger_event_sequence=trigger_event_sequence,
        trigger_event_type=trigger_event_type,
        usage_before=usage_before,
        usage_after=usage_after,
        marks_before=marks_before,
        marks_after=marks_after,
        skill_runtime_after=game.skill_runtime.audit_fingerprint(),
        continuation_identity=continuation_identity,
        action_ids=tuple(action_ids),
        legal_set_hashes=tuple(legal_hashes),
        chosen_action_semantics=tuple(chosen_semantics),
        event_slice=events,
        state_hash_before=state_before,
        state_hash_after=state_after,
        rng_hash=rng_calls_hash(game.rng_calls),
    )
    return envelope, game


def test_shamoke_production_replay_clean_pass() -> None:
    envelope, _ = _record_shamoke_replay()
    gen_registry = create_authoritative_general_batch_v1_registry()
    skill_registry = create_proof_slice_v1_registry()

    result = reexecute_general_production_replay(envelope, gen_registry, skill_registry)
    assert result.verified
    assert result.registry_identity_matched
    assert result.state_hashes_matched
    assert result.steps_verified == len(envelope.action_ids)


def test_shamoke_replay_adversarial_general_registry_tampering() -> None:
    envelope, _ = _record_shamoke_replay()
    gen_registry = create_authoritative_general_batch_v1_registry()
    skill_registry = create_proof_slice_v1_registry()

    # Tampered general_registry_identity
    data = envelope.to_dict()
    data["general_registry_identity"] = "a" * 64
    with pytest.raises(SkillReplayDivergenceError, match="execution_identity 与信封内容不一致|武将注册表身份不匹配"):
        tampered_env = GeneralProductionReplayEnvelope.from_dict(data)
        reexecute_general_production_replay(tampered_env, gen_registry, skill_registry)


def test_shamoke_replay_adversarial_skill_registry_tampering() -> None:
    envelope, _ = _record_shamoke_replay()
    gen_registry = create_authoritative_general_batch_v1_registry()
    skill_registry = create_proof_slice_v1_registry()

    data = envelope.to_dict()
    data["skill_registry_identity"] = "b" * 64
    with pytest.raises(SkillReplayDivergenceError, match="execution_identity 与信封内容不一致|技能注册表身份不匹配"):
        tampered_env = GeneralProductionReplayEnvelope.from_dict(data)
        reexecute_general_production_replay(tampered_env, gen_registry, skill_registry)


def test_shamoke_replay_adversarial_action_tampering() -> None:
    envelope, _ = _record_shamoke_replay()
    gen_registry = create_authoritative_general_batch_v1_registry()
    skill_registry = create_proof_slice_v1_registry()

    data = envelope.to_dict()
    actions = list(data["action_ids"])
    actions[-1] = "act_" + "f" * 64
    data["action_ids"] = actions
    with pytest.raises(SkillReplayDivergenceError, match="records_identity 与内层回放记录不一致|chosen action_id 不在"):
        tampered_env = GeneralProductionReplayEnvelope.from_dict(data)
        reexecute_general_production_replay(tampered_env, gen_registry, skill_registry)


def test_shamoke_replay_adversarial_derived_skill_tampering() -> None:
    envelope, _ = _record_shamoke_replay()
    gen_registry = create_authoritative_general_batch_v1_registry()
    skill_registry = create_proof_slice_v1_registry()

    data = envelope.to_dict()
    data["derived_skill_assignments"] = {"p1": ["sgs_skill_weimu"]}
    with pytest.raises(SkillReplayDivergenceError, match="execution_identity 与信封内容不一致|派生的技能集合不匹配"):
        tampered_env = GeneralProductionReplayEnvelope.from_dict(data)
        reexecute_general_production_replay(tampered_env, gen_registry, skill_registry)


def test_shamoke_replay_adversarial_general_profile_tampering() -> None:
    envelope, _ = _record_shamoke_replay()
    gen_registry = create_authoritative_general_batch_v1_registry()
    skill_registry = create_proof_slice_v1_registry()

    data = envelope.to_dict()
    data["general_profile_identities"] = {"shamoke": "c" * 64}
    with pytest.raises(SkillReplayDivergenceError, match="execution_identity 与信封内容不一致|武将 profile identity 不匹配"):
        tampered_env = GeneralProductionReplayEnvelope.from_dict(data)
        reexecute_general_production_replay(tampered_env, gen_registry, skill_registry)


def test_shamoke_replay_adversarial_skill_profile_tampering() -> None:
    envelope, _ = _record_shamoke_replay()
    gen_registry = create_authoritative_general_batch_v1_registry()
    skill_registry = create_proof_slice_v1_registry()

    data = envelope.to_dict()
    data["skill_profile_identities"] = {"sgs_skill_jili": "d" * 64}
    with pytest.raises(SkillReplayDivergenceError, match="execution_identity 与信封内容不一致|技能 profile identity 不匹配"):
        tampered_env = GeneralProductionReplayEnvelope.from_dict(data)
        reexecute_general_production_replay(tampered_env, gen_registry, skill_registry)


def test_shamoke_replay_adversarial_legal_set_hash_tampering() -> None:
    envelope, _ = _record_shamoke_replay()
    gen_registry = create_authoritative_general_batch_v1_registry()
    skill_registry = create_proof_slice_v1_registry()

    data = envelope.to_dict()
    hashes = list(data["legal_set_hashes"])
    hashes[-1] = "e" * 64
    data["legal_set_hashes"] = hashes
    with pytest.raises(SkillReplayDivergenceError, match="records_identity 与内层回放记录不一致|合法动作集哈希不匹配"):
        tampered_env = GeneralProductionReplayEnvelope.from_dict(data)
        reexecute_general_production_replay(tampered_env, gen_registry, skill_registry)


def test_shamoke_replay_adversarial_state_hash_tampering() -> None:
    envelope, _ = _record_shamoke_replay()
    gen_registry = create_authoritative_general_batch_v1_registry()
    skill_registry = create_proof_slice_v1_registry()

    data = envelope.to_dict()
    data["state_hash_after"] = "f" * 64
    with pytest.raises(SkillReplayDivergenceError, match="records_identity 与内层回放记录不一致|execution_identity 与信封内容不一致|重放后 state_hash 不匹配"):
        tampered_env = GeneralProductionReplayEnvelope.from_dict(data)
        reexecute_general_production_replay(tampered_env, gen_registry, skill_registry)


def test_shamoke_replay_adversarial_rng_tampering() -> None:
    envelope, _ = _record_shamoke_replay()
    gen_registry = create_authoritative_general_batch_v1_registry()
    skill_registry = create_proof_slice_v1_registry()

    data = envelope.to_dict()
    data["rng_hash"] = "0" * 64
    with pytest.raises(SkillReplayDivergenceError, match="records_identity 与内层回放记录不一致|execution_identity 与信封内容不一致|重放 RNG 调用哈希不匹配"):
        tampered_env = GeneralProductionReplayEnvelope.from_dict(data)
        reexecute_general_production_replay(tampered_env, gen_registry, skill_registry)


@pytest.mark.parametrize(
    "tamper_case",
    (
        "general_registry",
        "general_key",
        "general_profile",
        "general_semantic_payload",
        "primary_general_key",
        "owner_id",
        "assignment",
        "derived_skill_set",
        "skill_profile",
        "trigger_sequence",
        "trigger_type",
        "usage_before",
        "usage_after",
        "marks_before",
        "marks_after",
        "legal_set",
        "chosen_action",
        "continuation_identity",
        "event_slice",
        "state_before",
        "state_after",
        "rng",
    ),
)
def test_shamoke_replay_deep_tamper_recomputed_inner_outer_identities(
    tamper_case: str,
) -> None:
    envelope, _ = _record_shamoke_replay()
    gen_registry = create_authoritative_general_batch_v1_registry()
    skill_registry = create_proof_slice_v1_registry()
    data = copy.deepcopy(envelope.to_dict())

    if tamper_case == "general_registry":
        data["general_registry_identity"] = "a" * 64
    elif tamper_case == "general_key":
        payload = data["general_semantic_payloads"].pop("shamoke")
        payload["general_key"] = "tampered_general"
        payload["profile_identity"] = _semantic_profile_identity(payload)
        data["general_semantic_payloads"] = {"tampered_general": payload}
        data["general_profile_identities"] = {
            "tampered_general": payload["profile_identity"]
        }
        data["general_assignments"]["p1"] = "tampered_general"
        data["primary_general_key"] = "tampered_general"
    elif tamper_case == "general_profile":
        data["general_profile_identities"]["shamoke"] = "b" * 64
    elif tamper_case == "general_semantic_payload":
        payload = data["general_semantic_payloads"]["shamoke"]
        payload["version"] = "tampered-version"
        payload["profile_identity"] = _semantic_profile_identity(payload)
    elif tamper_case == "primary_general_key":
        data["primary_general_key"] = "tampered_general"
    elif tamper_case == "owner_id":
        data["owner_id"] = "p2"
    elif tamper_case == "assignment":
        data["general_assignments"]["p2"] = "shamoke"
        data["derived_skill_assignments"]["p2"] = ["sgs_skill_jili"]
    elif tamper_case == "derived_skill_set":
        data["derived_skill_assignments"]["p1"] = ["sgs_skill_weimu"]
        data["skill_profile_identities"] = {
            "sgs_skill_weimu": skill_registry.get_skill(
                "sgs_skill_weimu"
            ).profile_identity
        }
    elif tamper_case == "skill_profile":
        data["skill_profile_identities"]["sgs_skill_jili"] = "c" * 64
    elif tamper_case == "trigger_sequence":
        data["trigger_event_sequence"] += 1
    elif tamper_case == "trigger_type":
        data["trigger_event_type"] = EventType.CARD_PLAYED.value
    elif tamper_case == "usage_before":
        data["usage_before"]["uses_this_phase"] += 1
    elif tamper_case == "usage_after":
        data["usage_after"]["uses_this_turn"] += 1
    elif tamper_case == "marks_before":
        data["marks_before"] = {"tampered": 1}
    elif tamper_case == "marks_after":
        data["marks_after"] = {"tampered": 1}
    elif tamper_case == "legal_set":
        data["legal_set_hashes"][-1] = "d" * 64
    elif tamper_case == "chosen_action":
        data["chosen_action_semantics"][-1]["payload"]["resume"] = True
    elif tamper_case == "continuation_identity":
        data["continuation_identity"] = "e" * 64
    elif tamper_case == "event_slice":
        data["event_slice"][-1]["payload"]["tampered"] = True
    elif tamper_case == "state_before":
        data["state_hash_before"] = "f" * 64
    elif tamper_case == "state_after":
        data["state_hash_after"] = "0" * 64
    elif tamper_case == "rng":
        data["rng_hash"] = "1" * 64
    else:  # pragma: no cover - parameter list is exhaustive
        raise AssertionError(tamper_case)

    _recompute_general_envelope_identities(data)
    tampered = GeneralProductionReplayEnvelope.from_dict(data)
    with pytest.raises(SkillReplayDivergenceError):
        reexecute_general_production_replay(
            tampered, gen_registry, skill_registry
        )


@pytest.mark.parametrize(
    "field_name",
    ("name", "version", "skill_ids", "gender", "max_hp", "starting_hp"),
)
def test_frozen_general_live_payload_mutation_rejected_before_constructor(
    monkeypatch: pytest.MonkeyPatch,
    field_name: str,
) -> None:
    envelope, _ = _record_shamoke_replay()
    gen_registry = create_authoritative_general_batch_v1_registry()
    skill_registry = create_proof_slice_v1_registry()
    definition = gen_registry.get_general("shamoke")
    replacement = {
        "name": "malicious-live-mutation",
        "version": "malicious-live-mutation",
        "skill_ids": ("sgs_skill_weimu",),
        "gender": CharacterGender.FEMALE,
        "max_hp": 5,
        "starting_hp": 3,
    }[field_name]
    object.__setattr__(definition, field_name, replacement)

    import scripts.sgs_engine.production_batch as production_batch_module

    constructor_calls = 0
    original = production_batch_module.ProductionBasicCardBatch

    def sentinel(*args: object, **kwargs: object) -> object:
        nonlocal constructor_calls
        constructor_calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(production_batch_module, "ProductionBasicCardBatch", sentinel)
    with pytest.raises(SkillReplayDivergenceError, match="canonical payload"):
        reexecute_general_production_replay(
            envelope, gen_registry, skill_registry
        )
    assert constructor_calls == 0


@pytest.mark.parametrize(
    ("mutation", "match"),
    (
        (lambda data: data.update({"extra": 1}), "字段"),
        (lambda data: data.pop("rng_hash"), "字段"),
        (lambda data: data.update({"seed": True}), "exact int"),
        (
            lambda data: data.update({"trigger_event_sequence": True}),
            "exact int",
        ),
    ),
)
def test_general_replay_from_dict_exact_schema_rejects(
    mutation: object,
    match: str,
) -> None:
    envelope, _ = _record_shamoke_replay()
    data = copy.deepcopy(envelope.to_dict())
    mutation(data)
    with pytest.raises(SkillReplayDivergenceError, match=match):
        GeneralProductionReplayEnvelope.from_dict(data)


@pytest.mark.parametrize("bad_case", ("extra", "missing", "type", "bool_as_int"))
def test_general_semantic_payload_from_dict_exact_schema_rejects(
    bad_case: str,
) -> None:
    registry = create_authoritative_general_batch_v1_registry()
    payload = registry.get_general("shamoke").to_dict()
    if bad_case == "extra":
        payload["extra"] = 1
    elif bad_case == "missing":
        payload.pop("description")
    elif bad_case == "type":
        payload["skill_ids"] = ("sgs_skill_jili",)
    else:
        payload["max_hp"] = True
    with pytest.raises((TypeError, ValueError)):
        GeneralDefinition.from_dict(payload)


def _general_preflight_attack(
    envelope: GeneralProductionReplayEnvelope,
    attack: str,
) -> GeneralProductionReplayEnvelope:
    if attack == "outer_hash":
        return replace(envelope, execution_identity="0" * 64)
    if attack == "inner_hash":
        return replace(
            envelope, records_identity="0" * 64, execution_identity=""
        )
    if attack == "implementation_identity":
        return replace(
            envelope, implementation_identity="0" * 64, execution_identity=""
        )
    if attack == "contract_identity":
        return replace(
            envelope, contract_identity="0" * 64, execution_identity=""
        )
    if attack == "general_registry_identity":
        return replace(
            envelope,
            general_registry_identity="0" * 64,
            execution_identity="",
        )
    if attack == "general_profile_identity":
        return replace(
            envelope,
            general_profile_identities={"shamoke": "0" * 64},
            execution_identity="",
        )
    raise AssertionError(attack)


@pytest.mark.parametrize(
    "attack",
    (
        "outer_hash",
        "inner_hash",
        "implementation_identity",
        "contract_identity",
        "general_registry_identity",
        "general_profile_identity",
    ),
)
@pytest.mark.parametrize("sentinel_target", ("wrapper", "production_constructor"))
def test_general_preflight_rejects_before_any_session_constructor(
    monkeypatch: pytest.MonkeyPatch,
    attack: str,
    sentinel_target: str,
) -> None:
    envelope, _ = _record_shamoke_replay()
    registry = create_authoritative_general_batch_v1_registry()
    skill_registry = create_proof_slice_v1_registry()
    tampered = _general_preflight_attack(envelope, attack)
    calls = 0

    def sentinel(*_args: object, **_kwargs: object) -> object:
        nonlocal calls
        calls += 1
        raise AssertionError("认证失败前不得调用生产会话构造器")

    if sentinel_target == "wrapper":
        monkeypatch.setattr(
            skill_replay_module,
            "_construct_general_production_replay_session",
            sentinel,
        )
    else:
        monkeypatch.setattr(
            production_batch_module, "ProductionBasicCardBatch", sentinel
        )
    with pytest.raises(SkillReplayDivergenceError):
        reexecute_general_production_replay(
            tampered, registry, skill_registry
        )
    assert calls == 0
