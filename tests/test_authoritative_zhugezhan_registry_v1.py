# -*- coding: utf-8 -*-
"""Canonical registry and derivation tests for G2 Zhugezhan."""

from __future__ import annotations

import pytest

from scripts.sgs_engine.generals import (
    create_authoritative_general_batch_v1_registry,
)
from scripts.sgs_engine.model import CharacterGender
from scripts.sgs_engine.production_batch import ProductionBasicCardBatch
from scripts.sgs_engine.skill_impl_v1 import create_proof_slice_v1_registry


def test_zhugezhan_canonical_definition_and_derived_skills() -> None:
    registry = create_authoritative_general_batch_v1_registry()
    definition = registry.get_general("zhugezhan")

    assert definition.name == "诸葛瞻"
    assert definition.gender is CharacterGender.MALE
    assert definition.starting_hp == 3
    assert definition.max_hp == 3
    assert definition.skill_ids == (
        "sgs_skill_zuilun",
        "sgs_skill_fuyin",
    )
    assert definition.profile_identity == definition.canonical_profile_identity()

    game = ProductionBasicCardBatch(
        seed=1,
        shuffle=False,
        first_player_id="p1",
        player_hp=(3, 4),
        player_max_hp=(3, 4),
        general_registry=registry,
        general_assignments={"p1": "zhugezhan"},
        skill_registry=create_proof_slice_v1_registry(),
    )
    assert game.general_assignments == {"p1": "zhugezhan"}
    assert game.skill_runtime is not None
    assert game.skill_runtime.has_skill("p1", "sgs_skill_zuilun")
    assert game.skill_runtime.has_skill("p1", "sgs_skill_fuyin")
    assert game.state.players_by_id["p1"].character is not None
    assert game.state.players_by_id["p1"].character.intrinsic_gender is CharacterGender.MALE


def test_zhugezhan_hp_authority_rejects_conflicting_override() -> None:
    with pytest.raises(ValueError, match="权威体力 3/3.*冲突"):
        ProductionBasicCardBatch(
            seed=1,
            player_hp=(4, 4),
            player_max_hp=(4, 4),
            general_assignments={"p1": "zhugezhan"},
        )


def test_unassigned_no_skill_path_remains_identity() -> None:
    game = ProductionBasicCardBatch(seed=2, shuffle=False, first_player_id="p1")
    assert game.general_registry is None
    assert game.skill_runtime is None
    assert game.execution_snapshot.get("skill_authority") is None


@pytest.mark.parametrize(
    ("field_name", "replacement"),
    (
        ("gender", CharacterGender.FEMALE),
        ("starting_hp", 2),
        ("max_hp", 4),
        ("skill_ids", ("sgs_skill_jili",)),
    ),
)
def test_zhugezhan_frozen_live_payload_tamper_fails_canonical_preflight(
    field_name: str, replacement: object
) -> None:
    registry = create_authoritative_general_batch_v1_registry()
    definition = registry.get_general("zhugezhan")
    object.__setattr__(definition, field_name, replacement)
    with pytest.raises((TypeError, ValueError), match="canonical|规范|哈希|体力"):
        registry.assert_canonical_integrity()
