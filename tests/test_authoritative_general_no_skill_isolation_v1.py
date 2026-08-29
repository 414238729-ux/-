# -*- coding: utf-8 -*-
"""Isolation tests for Authoritative General Framework: ensuring no-skill default isolation."""

from __future__ import annotations

import pytest

from scripts.sgs_engine.actions import UnsupportedRuleError
from scripts.sgs_engine.generals import (
    AuthoritativeGeneralRegistry,
    GeneralDefinition,
    create_authoritative_general_batch_v1_registry,
)
from scripts.sgs_engine.model import CharacterGender
from scripts.sgs_engine.production_batch import (
    BatchActionIdController,
    ProductionBasicCardBatch,
    ProductionPhase,
)


def test_default_no_skill_isolation() -> None:
    game = ProductionBasicCardBatch(seed=42)
    assert game.general_registry is None
    assert game.general_assignments is None
    assert game.skill_runtime is None


def test_unknown_general_assignment_fail_closed() -> None:
    with pytest.raises(UnsupportedRuleError, match="未包含武将键"):
        ProductionBasicCardBatch(
            seed=42,
            general_assignments={"p1": "unknown_general_xyz"},
        )


def test_unfrozen_general_registry_rejected() -> None:
    registry = AuthoritativeGeneralRegistry()
    shamoke = GeneralDefinition(
        general_key="shamoke",
        name="沙摩柯",
        version="1.0.0",
        gender=CharacterGender.MALE,
        max_hp=4,
        starting_hp=4,
        skill_ids=("sgs_skill_jili",),
    )
    registry.register(shamoke)
    # Not frozen yet
    with pytest.raises(ValueError, match="必须已冻结"):
        ProductionBasicCardBatch(
            seed=42,
            general_registry=registry,
            general_assignments={"p1": "shamoke"},
        )


def test_general_registry_without_assignments_rejected() -> None:
    registry = create_authoritative_general_batch_v1_registry()
    with pytest.raises(ValueError, match="未提供general_assignments"):
        ProductionBasicCardBatch(
            seed=42,
            general_registry=registry,
        )


def test_no_skill_session_step_identical() -> None:
    g1 = ProductionBasicCardBatch(seed=100)
    g2 = ProductionBasicCardBatch(seed=100)

    for _ in range(5):
        l1 = g1.legal_actions()
        l2 = g2.legal_actions()
        assert len(l1) == len(l2)
        assert l1[0].action_type == l2[0].action_type
        g1.step(BatchActionIdController(l1[0].action_id))
        g2.step(BatchActionIdController(l2[0].action_id))
        assert g1.state.revision == g2.state.revision
