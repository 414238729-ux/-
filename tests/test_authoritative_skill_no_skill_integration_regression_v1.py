# -*- coding: utf-8 -*-
"""No-skill production regression after the skill opt-in seam.

Does not modify frozen no-skill / C7 replay schemas. Historical artifact
implementation identities are not rewritten.
"""

from __future__ import annotations

import json

from scripts.sgs_engine.actions import ActionType
from scripts.sgs_engine.authoritative_no_skill_full_game import (
    AUTHORITATIVE_NO_SKILL_REPLAY_V2_SCHEMA,
    AuthoritativeNoSkillFullGameOrchestrator,
    AuthoritativeNoSkillReplayV2,
    reexecute_authoritative_no_skill_replay_v2,
)
from scripts.sgs_engine import c7_active_mode_decision_full_game as c7_active
from scripts.sgs_engine.c7_active_mode_decision_full_game import (
    C7_ACTIVE_MODE_DECISION_FULL_GAME_REPLAY_SCHEMA_V1,
)
from scripts.sgs_engine.formal_duel import (
    FormalDuelConfiguration,
    FormalNoSkillDuelSession,
)
from scripts.sgs_engine.production_batch import (
    FORMAL_NO_SKILL_DUEL_MODE,
    BatchActionIdController,
    ProductionBasicCardBatch,
    ProductionPhase,
)


def _fresh_play(seed: int = 1) -> ProductionBasicCardBatch:
    game = ProductionBasicCardBatch(seed=seed)
    for operation in ("proceed_prepare", "proceed_judgment", "proceed_draw"):
        action = next(
            item
            for item in game.legal_actions()
            if item.payload.get("operation") == operation
        )
        game.step(BatchActionIdController(action.action_id))
    assert game.phase is ProductionPhase.PLAY
    return game


def test_old_replay_schema_constants_unchanged() -> None:
    assert AUTHORITATIVE_NO_SKILL_REPLAY_V2_SCHEMA == (
        "sgs-authoritative-no-skill-full-game-replay-v2"
    )
    assert C7_ACTIVE_MODE_DECISION_FULL_GAME_REPLAY_SCHEMA_V1 == (
        "sgs-c7-active-mode-decision-full-game-replay-v1"
    )


def test_no_skill_play_legal_actions_have_no_skill_ids() -> None:
    game = _fresh_play(1)
    assert game.skill_runtime is None
    actions = game.legal_actions()
    assert actions
    assert all(action.skill_id is None for action in actions)
    assert all(action.action_type is not ActionType.ACTIVATE_SKILL for action in actions)


def test_no_skill_duel_session_legal_action_snapshot() -> None:
    session = FormalNoSkillDuelSession(
        configuration=FormalDuelConfiguration.formal_profile(),
        seed=7,
    )
    assert session.skill_runtime is None
    for operation in ("proceed_prepare", "proceed_judgment", "proceed_draw"):
        action = next(
            item
            for item in session.legal_actions()
            if item.payload.get("operation") == operation
        )
        session.step(BatchActionIdController(action.action_id))
    actions = session.legal_actions()
    assert all(action.skill_id is None for action in actions)
    assert any(action.payload.get("operation") == "end_play_phase" for action in actions)


def _assert_replay_has_no_skill_runtime_surface(record: object) -> None:
    header = record.header
    assert all("skill" not in str(key).lower() for key in header)
    initial = header["initial_configuration"]
    assert "skill_registry" not in initial
    assert "skill_assignments" not in initial
    assert "skill_runtime" not in initial
    for decision in record.decisions:
        chosen = decision["chosen_action"]
        assert chosen["skill_id"] is None
        assert chosen["action_type"] != ActionType.ACTIVATE_SKILL.value
        assert "skill_registry" not in chosen["payload"]
        assert "skill_runtime" not in chosen["payload"]
    for event in record.events:
        assert event.get("skill_owner") is None
        reason = event.get("payload", {}).get("reason")
        assert not (isinstance(reason, str) and reason.startswith("sgs_skill_"))


def test_real_authoritative_no_skill_replay_roundtrip_and_strict_reexecute() -> None:
    cell = AuthoritativeNoSkillFullGameOrchestrator().run_cell(
        FORMAL_NO_SKILL_DUEL_MODE,
        0,
    )
    cold_payload = json.loads(json.dumps(cell.replay_v2.to_dict(), sort_keys=True))
    loaded = AuthoritativeNoSkillReplayV2.from_dict(cold_payload)
    result = reexecute_authoritative_no_skill_replay_v2(loaded)
    assert result.verified is True
    assert result.decision_count == len(loaded.production_replay_v1.decisions)
    _assert_replay_has_no_skill_runtime_surface(loaded.production_replay_v1)


def test_real_c7_replay_roundtrip_and_strict_reexecute_keeps_no_skill_path() -> None:
    recorded = c7_active.record_c7_active_mode_decision_full_game_v1(
        c7_active.HEIR_SUCCESSION
    )
    cold_payload = json.loads(json.dumps(recorded.to_dict(), sort_keys=True))
    loaded = c7_active.C7ActiveModeDecisionFullGameReplayV1.from_dict(cold_payload)
    result = c7_active.reexecute_c7_active_mode_decision_full_game_replay_v1(loaded)
    assert result.verified is True
    assert result.scenario_id == c7_active.HEIR_SUCCESSION
    assert result.seed == 1
    assert result.proof["scenario_proven"] is True
    assert loaded.to_dict()["schema"] == C7_ACTIVE_MODE_DECISION_FULL_GAME_REPLAY_SCHEMA_V1
    _assert_replay_has_no_skill_runtime_surface(loaded.production_replay_v1)
