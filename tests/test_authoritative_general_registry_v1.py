# -*- coding: utf-8 -*-
"""Tests for Authoritative General Registry and GeneralDefinition canonical identity."""

from __future__ import annotations

import pytest

from scripts.sgs_engine.actions import UnsupportedRuleError
from scripts.sgs_engine.generals import (
    GENERAL_SCHEMA_V1,
    AuthoritativeGeneralRegistry,
    GeneralDefinition,
    create_authoritative_general_batch_v1_registry,
)
from scripts.sgs_engine.model import CharacterGender, CharacterMetadata
from scripts.sgs_engine.replay import sha256_value


def test_general_definition_canonical_profile_identity() -> None:
    g = GeneralDefinition(
        general_key="shamoke",
        name="沙摩柯",
        version="1.0.0",
        gender=CharacterGender.MALE,
        max_hp=4,
        starting_hp=4,
        skill_ids=("sgs_skill_jili",),
        description="蜀势力武将沙摩柯",
    )
    assert g.profile_identity
    assert len(g.profile_identity) == 64

    # Exact canonical match
    payload = g.to_canonical_payload()
    assert g.profile_identity == sha256_value(payload)


def test_general_definition_rejects_forged_profile_identity() -> None:
    with pytest.raises(ValueError, match="与规范语义哈希不一致"):
        GeneralDefinition(
            general_key="shamoke",
            name="沙摩柯",
            version="1.0.0",
            gender=CharacterGender.MALE,
            max_hp=4,
            starting_hp=4,
            skill_ids=("sgs_skill_jili",),
            profile_identity="a" * 64,
        )


def test_general_definition_from_dict_recomputes_and_validates() -> None:
    g = GeneralDefinition(
        general_key="shamoke",
        name="沙摩柯",
        version="1.0.0",
        gender=CharacterGender.MALE,
        max_hp=4,
        starting_hp=4,
        skill_ids=("sgs_skill_jili",),
    )
    data = g.to_dict()
    loaded = GeneralDefinition.from_dict(data)
    assert loaded.profile_identity == g.profile_identity

    # Tamper payload with valid hp relationship (3/3) but tampered against serialized profile_identity (4/4)
    data_tampered = dict(data)
    data_tampered["max_hp"] = 3
    data_tampered["starting_hp"] = 3
    with pytest.raises(ValueError, match="与规范语义哈希不一致"):
        GeneralDefinition.from_dict(data_tampered)


def test_general_semantic_mutation_changes_identity() -> None:
    g1 = GeneralDefinition(
        general_key="shamoke",
        name="沙摩柯",
        version="1.0.0",
        gender=CharacterGender.MALE,
        max_hp=4,
        starting_hp=4,
        skill_ids=("sgs_skill_jili",),
    )
    g2 = GeneralDefinition(
        general_key="shamoke",
        name="沙摩柯",
        version="1.0.0",
        gender=CharacterGender.MALE,
        max_hp=3,
        starting_hp=3,
        skill_ids=("sgs_skill_jili",),
    )
    assert g1.profile_identity != g2.profile_identity


def test_registry_registration_and_freezing() -> None:
    reg = AuthoritativeGeneralRegistry()
    g = GeneralDefinition(
        general_key="shamoke",
        name="沙摩柯",
        version="1.0.0",
        gender=CharacterGender.MALE,
        max_hp=4,
        starting_hp=4,
        skill_ids=("sgs_skill_jili",),
    )
    reg.register(g)
    assert reg.has_general("shamoke")
    assert not reg.is_frozen
    with pytest.raises(ValueError, match="尚未冻结"):
        _ = reg.registry_identity

    reg.freeze()
    assert reg.is_frozen
    assert len(reg.registry_identity) == 64

    # Frozen rejects modification
    with pytest.raises(ValueError, match="已冻结"):
        reg.register(g)


def test_batch_v1_registry_contains_shamoke() -> None:
    reg = create_authoritative_general_batch_v1_registry()
    assert reg.is_frozen
    assert reg.has_general("shamoke")
    shamoke = reg.get_general("shamoke")
    assert shamoke.name == "沙摩柯"
    assert shamoke.gender is CharacterGender.MALE
    assert shamoke.max_hp == 4
    assert shamoke.starting_hp == 4
    assert shamoke.skill_ids == ("sgs_skill_jili",)
