# -*- coding: utf-8 -*-
"""PRODUCTION skill replay: cold from_dict, fresh session, signed action_ids, tamper matrix."""

from __future__ import annotations

from dataclasses import replace
import gc
import json

import pytest

import scripts.sgs_engine.production_batch as production_batch_module
import scripts.sgs_engine.skill_replay as skill_replay_module
from scripts.sgs_engine.production_batch import (
    BatchActionIdController,
    ProductionBasicCardBatch,
    ProductionPhase,
)
from scripts.sgs_engine.skill_impl_v1 import PojiangSkillHandler
from scripts.sgs_engine.skill_registry import create_skill_registry
from scripts.sgs_engine.skill_replay import (
    SKILL_PRODUCTION_REPLAY_CONTRACT_IDENTITY_V1,
    SkillProductionReplayEnvelope,
    SkillReplayDivergenceError,
    action_semantics,
    compute_state_hash,
    legal_actions_semantic_hash,
    reexecute_skill_production_replay,
    reexecute_skill_replay,
    rng_calls_hash,
)
from scripts.sgs_engine.actions import UnsupportedRuleError


def _step_named(game: ProductionBasicCardBatch, operation: str) -> str:
    action = next(
        item for item in game.legal_actions() if item.payload.get("operation") == operation
    )
    assert action.action_id
    game.step(BatchActionIdController(action.action_id))
    return action.action_id


def _record_pojiang_envelope() -> tuple[SkillProductionReplayEnvelope, object]:
    registry = create_skill_registry((PojiangSkillHandler(),))
    session_id = "a" * 32
    secret = b"\x22" * 32
    game = ProductionBasicCardBatch(
        seed=1,
        session_id=session_id,
        session_secret=secret,
        skill_registry=registry,
        skill_assignments={"p1": ("sgs_skill_pojiang",)},
    )
    action_ids: list[str] = []
    legal_hashes: list[str] = []
    semantics: list[dict] = []

    def take(action: object) -> None:
        legal = game.legal_actions()
        legal_hashes.append(legal_actions_semantic_hash(legal))
        assert action.action_id
        semantics.append(action_semantics(action))  # type: ignore[arg-type]
        action_ids.append(action.action_id)
        game.step(BatchActionIdController(action.action_id))

    for operation in ("proceed_prepare", "proceed_judgment", "proceed_draw"):
        current = next(
            item for item in game.legal_actions() if item.payload.get("operation") == operation
        )
        take(current)
    assert game.phase is ProductionPhase.PLAY
    state_before = compute_state_hash(game.state)
    skill_state = game.skill_runtime.get_skill_state("p1", "sgs_skill_pojiang")  # type: ignore[union-attr]
    usage_before = {
        "uses_this_phase": skill_state.uses_this_phase,
        "uses_this_turn": skill_state.uses_this_turn,
    }
    marks_before = dict(skill_state.marks)
    chosen = next(
        item for item in game.legal_actions() if item.skill_id == "sgs_skill_pojiang"
    )
    take(chosen)
    skill_state = game.skill_runtime.get_skill_state("p1", "sgs_skill_pojiang")  # type: ignore[union-attr]
    envelope = SkillProductionReplayEnvelope(
        seed=1,
        session_id=session_id,
        session_secret_hex=secret.hex(),
        registry_identity=registry.registry_identity,
        skill_profile_identities={
            "sgs_skill_pojiang": registry.get_skill("sgs_skill_pojiang").profile_identity
        },
        skill_assignments={"p1": ("sgs_skill_pojiang",)},
        skill_id="sgs_skill_pojiang",
        skill_version=registry.get_skill("sgs_skill_pojiang").version,
        owner_id="p1",
        trigger_event_sequence=None,
        trigger_event_type=None,
        action_ids=tuple(action_ids),
        legal_set_hashes=tuple(legal_hashes),
        chosen_action_semantics=tuple(semantics),
        usage_before=usage_before,
        usage_after={
            "uses_this_phase": skill_state.uses_this_phase,
            "uses_this_turn": skill_state.uses_this_turn,
        },
        marks_before=marks_before,
        marks_after=dict(skill_state.marks),
        event_slice=tuple(event.to_replay_dict() for event in game.events),
        state_hash_before=state_before,
        state_hash_after=compute_state_hash(game.state),
        rng_hash=rng_calls_hash(game.rng_calls),
    )
    return envelope, registry


def test_component_runtime_replay_is_not_production_authority() -> None:
    with pytest.raises(UnsupportedRuleError, match="不是生产权威证明"):
        reexecute_skill_replay()


def test_production_skill_replay_roundtrip() -> None:
    envelope, registry = _record_pojiang_envelope()
    loaded = SkillProductionReplayEnvelope.from_dict(envelope.to_dict())
    result = reexecute_skill_production_replay(loaded, registry)
    assert result.verified
    assert result.steps_verified == len(envelope.action_ids)


def test_production_skill_replay_exact_cold_json_roundtrip() -> None:
    envelope, registry = _record_pojiang_envelope()
    assert envelope.contract_identity == SKILL_PRODUCTION_REPLAY_CONTRACT_IDENTITY_V1
    assert envelope.implementation_identity
    assert envelope.records_identity
    serialized = json.dumps(envelope.to_dict(), ensure_ascii=False, sort_keys=True)
    del envelope
    del registry
    gc.collect()
    cold_payload = json.loads(serialized)
    loaded = SkillProductionReplayEnvelope.from_dict(cold_payload)
    fresh_registry = create_skill_registry((PojiangSkillHandler(),))
    result = reexecute_skill_production_replay(loaded, fresh_registry)
    assert result.verified is True
    assert result.steps_verified == len(loaded.action_ids)


def test_from_dict_ignores_serialized_verified_flag() -> None:
    envelope, registry = _record_pojiang_envelope()
    payload = envelope.to_dict()
    payload["verified"] = True
    payload["scenario_proven"] = True
    with pytest.raises(SkillReplayDivergenceError, match="verified"):
        SkillProductionReplayEnvelope.from_dict(payload)


@pytest.mark.parametrize("pass_field", ["verified", "scenario_proven"])
def test_from_dict_rejects_serialized_pass_fields_even_when_false(
    pass_field: str,
) -> None:
    envelope, _registry = _record_pojiang_envelope()
    payload = envelope.to_dict()
    payload[pass_field] = False
    with pytest.raises(SkillReplayDivergenceError, match="extra"):
        SkillProductionReplayEnvelope.from_dict(payload)


def test_from_dict_rejects_extra_missing_and_non_dict_root() -> None:
    envelope, _registry = _record_pojiang_envelope()
    extra = envelope.to_dict()
    extra["unexpected"] = "forbidden"
    with pytest.raises(SkillReplayDivergenceError, match="extra"):
        SkillProductionReplayEnvelope.from_dict(extra)

    missing = envelope.to_dict()
    missing.pop("rng_hash")
    with pytest.raises(SkillReplayDivergenceError, match="missing"):
        SkillProductionReplayEnvelope.from_dict(missing)

    with pytest.raises(SkillReplayDivergenceError, match="JSON object"):
        SkillProductionReplayEnvelope.from_dict([])  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("field", "invalid"),
    [
        ("seed", True),
        ("seed", "1"),
        ("session_id", 1),
        ("skill_id", ""),
        ("trigger_event_sequence", True),
        ("trigger_event_type", 7),
        ("execution_identity", 1),
    ],
)
def test_from_dict_rejects_scalar_coercion_and_empty_ids(
    field: str, invalid: object
) -> None:
    envelope, _registry = _record_pojiang_envelope()
    payload = envelope.to_dict()
    payload[field] = invalid
    with pytest.raises(SkillReplayDivergenceError):
        SkillProductionReplayEnvelope.from_dict(payload)


def test_from_dict_rejects_nested_unknown_types_and_duplicate_ids() -> None:
    envelope, _registry = _record_pojiang_envelope()

    nested_unknown = envelope.to_dict()
    nested_unknown["chosen_action_semantics"][0]["unexpected"] = True
    with pytest.raises(SkillReplayDivergenceError, match="extra"):
        SkillProductionReplayEnvelope.from_dict(nested_unknown)

    event_unknown = envelope.to_dict()
    event_unknown["event_slice"][0]["unexpected"] = True
    with pytest.raises(SkillReplayDivergenceError, match="extra"):
        SkillProductionReplayEnvelope.from_dict(event_unknown)

    wrong_sequence = envelope.to_dict()
    wrong_sequence["action_ids"] = tuple(wrong_sequence["action_ids"])
    with pytest.raises(SkillReplayDivergenceError, match="JSON array"):
        SkillProductionReplayEnvelope.from_dict(wrong_sequence)

    duplicate_action = envelope.to_dict()
    duplicate_action["action_ids"][1] = duplicate_action["action_ids"][0]
    with pytest.raises(SkillReplayDivergenceError, match="重复 ID"):
        SkillProductionReplayEnvelope.from_dict(duplicate_action)

    duplicate_assignment = envelope.to_dict()
    duplicate_assignment["skill_assignments"]["p1"] = [
        "sgs_skill_pojiang",
        "sgs_skill_pojiang",
    ]
    with pytest.raises(SkillReplayDivergenceError, match="重复 ID"):
        SkillProductionReplayEnvelope.from_dict(duplicate_assignment)

    bad_usage = envelope.to_dict()
    bad_usage["usage_after"]["extra"] = 0
    with pytest.raises(SkillReplayDivergenceError, match="extra"):
        SkillProductionReplayEnvelope.from_dict(bad_usage)


def _tamper(envelope: SkillProductionReplayEnvelope, **changes: object) -> SkillProductionReplayEnvelope:
    # Recompute both inner and outer identities so semantic attacks do not all
    # die at the outer-hash gate.
    return replace(
        envelope,
        **changes,
        records_identity="",
        execution_identity="",
    )


@pytest.mark.parametrize(
    ("field", "value", "match"),
    [
        ("registry_identity", "0" * 64, "注册表身份"),
        ("skill_id", "sgs_skill_mingzhe", "profile 集合|技能"),
        ("skill_version", "9.9.9", "版本"),
        ("owner_id", "p2", "未拥有"),
        ("state_hash_before", "1" * 64, "前置状态哈希"),
        ("state_hash_after", "2" * 64, "终态哈希"),
        ("rng_hash", "3" * 64, "RNG"),
        ("trigger_event_sequence", 1, "触发事件"),
        ("trigger_event_type", "card_used", "触发事件"),
    ],
)
def test_production_replay_rejects_independent_field_tampering(
    field: str, value: object, match: str
) -> None:
    envelope, registry = _record_pojiang_envelope()
    tampered = _tamper(envelope, **{field: value})
    with pytest.raises(SkillReplayDivergenceError, match=match):
        reexecute_skill_production_replay(tampered, registry)


def test_production_replay_rejects_profile_identity_tamper() -> None:
    envelope, registry = _record_pojiang_envelope()
    tampered = _tamper(
        envelope,
        skill_profile_identities={"sgs_skill_pojiang": "0" * 64},
    )
    with pytest.raises(SkillReplayDivergenceError, match="profile identity"):
        reexecute_skill_production_replay(tampered, registry)


def test_production_replay_rejects_payload_and_legal_set_tamper() -> None:
    envelope, registry = _record_pojiang_envelope()
    semantics = [dict(item) for item in envelope.chosen_action_semantics]
    semantics[-1] = dict(semantics[-1])
    payload = dict(semantics[-1]["payload"])
    payload["operation"] = "tampered"
    semantics[-1]["payload"] = payload
    tampered = _tamper(envelope, chosen_action_semantics=semantics)
    with pytest.raises(
        SkillReplayDivergenceError,
        match="chosen_action_semantics|chosen action 语义",
    ):
        reexecute_skill_production_replay(tampered, registry)

    hashes = list(envelope.legal_set_hashes)
    hashes[-1] = "4" * 64
    tampered_hash = _tamper(envelope, legal_set_hashes=hashes)
    with pytest.raises(SkillReplayDivergenceError, match="合法动作语义集合"):
        reexecute_skill_production_replay(tampered_hash, registry)


def test_production_replay_rejects_usage_mark_and_event_tamper() -> None:
    envelope, registry = _record_pojiang_envelope()
    tampered_usage = _tamper(
        envelope, usage_after={"uses_this_phase": 9, "uses_this_turn": 9}
    )
    with pytest.raises(SkillReplayDivergenceError, match="uses_this_phase 后置"):
        reexecute_skill_production_replay(tampered_usage, registry)

    tampered_marks = _tamper(envelope, marks_after={"x": 1})
    with pytest.raises(SkillReplayDivergenceError, match="marks 后置"):
        reexecute_skill_production_replay(tampered_marks, registry)

    events = [dict(item) for item in envelope.event_slice]
    events[-1] = dict(events[-1])
    events[-1]["event_type"] = "victory"
    tampered_events = _tamper(envelope, event_slice=events)
    with pytest.raises(SkillReplayDivergenceError, match="事件内容"):
        reexecute_skill_production_replay(tampered_events, registry)

    ids = list(envelope.action_ids)
    ids[-1] = "act_" + "0" * 64
    tampered_choice = _tamper(envelope, action_ids=ids)
    with pytest.raises(SkillReplayDivergenceError, match="chosen action_id"):
        reexecute_skill_production_replay(tampered_choice, registry)


def test_production_replay_rejects_deep_payload_and_trigger_source_tamper() -> None:
    envelope, registry = _record_pojiang_envelope()
    semantics = [dict(item) for item in envelope.chosen_action_semantics]
    semantics[-1] = dict(semantics[-1])
    skill_payload = dict(semantics[-1]["payload"])
    skill_payload["expected_revision"] = 999
    semantics[-1]["payload"] = skill_payload
    payload_tamper = _tamper(envelope, chosen_action_semantics=tuple(semantics))
    with pytest.raises(SkillReplayDivergenceError, match="chosen action 语义"):
        reexecute_skill_production_replay(payload_tamper, registry)

    trigger_tamper = _tamper(
        envelope,
        trigger_event_sequence=1,
        trigger_event_type="card_used",
    )
    with pytest.raises(SkillReplayDivergenceError, match="触发事件"):
        reexecute_skill_production_replay(trigger_tamper, registry)


def _sentinel_attack(
    envelope: SkillProductionReplayEnvelope, attack: str
) -> SkillProductionReplayEnvelope:
    if attack == "outer_hash":
        return replace(envelope, execution_identity="0" * 64)
    if attack == "inner_hash":
        return replace(
            envelope,
            records_identity="0" * 64,
            execution_identity="",
        )
    if attack == "implementation_identity":
        return replace(
            envelope,
            implementation_identity="0" * 64,
            execution_identity="",
        )
    if attack == "contract_identity":
        return replace(
            envelope,
            contract_identity="0" * 64,
            execution_identity="",
        )
    if attack == "registry_identity":
        return replace(
            envelope,
            registry_identity="0" * 64,
            execution_identity="",
        )
    if attack == "profile_identity":
        return replace(
            envelope,
            skill_profile_identities={"sgs_skill_pojiang": "0" * 64},
            execution_identity="",
        )
    raise AssertionError(attack)


@pytest.mark.parametrize(
    "attack",
    [
        "outer_hash",
        "inner_hash",
        "implementation_identity",
        "contract_identity",
        "registry_identity",
        "profile_identity",
    ],
)
@pytest.mark.parametrize("sentinel_target", ["wrapper", "production_constructor"])
def test_preflight_rejects_before_any_session_constructor(
    monkeypatch: pytest.MonkeyPatch,
    attack: str,
    sentinel_target: str,
) -> None:
    envelope, registry = _record_pojiang_envelope()
    tampered = _sentinel_attack(envelope, attack)
    calls = 0

    def sentinel(*_args: object, **_kwargs: object) -> object:
        nonlocal calls
        calls += 1
        raise AssertionError("认证失败前不得调用任何生产会话构造器")

    if sentinel_target == "wrapper":
        monkeypatch.setattr(
            skill_replay_module,
            "_construct_skill_production_replay_session",
            sentinel,
        )
    else:
        monkeypatch.setattr(
            production_batch_module,
            "ProductionBasicCardBatch",
            sentinel,
        )
    with pytest.raises(SkillReplayDivergenceError):
        reexecute_skill_production_replay(tampered, registry)
    assert calls == 0
