# -*- coding: utf-8 -*-
from __future__ import annotations

from copy import deepcopy
from dataclasses import fields, replace
from typing import Mapping

import pytest

from scripts.sgs_engine.actions import ActionContext, LegalAction
from scripts.sgs_engine.mode_identity_heir import (
    FORMAL_NO_SKILL_IDENTITY_8P_HEIR_MODE,
    FormalHeirAndSpyChoiceIdentityConfiguration,
    FormalHeirAndSpyChoiceIdentitySession,
)
from scripts.sgs_engine.production_batch import BatchActionIdController, ProductionBatchError
from scripts.sgs_engine.production_replay import (
    ProductionReplayDivergenceError,
    ProductionReplayFormatError,
)
from scripts.sgs_engine.replay import sha256_value
from scripts.sgs_engine import c7_active_mode_decision_full_game as active
from scripts.sgs_engine import production_replay as production_replay_module


def _outer_hash(payload: Mapping[str, object]) -> str:
    return sha256_value(
        {
            "schema": payload["schema"],
            "header": payload["header"],
            "production_replay_v1": payload["production_replay_v1"],
            "required_active_decision_proof": payload[
                "required_active_decision_proof"
            ],
        }
    )


@pytest.fixture(scope="module")
def scenario_rows() -> dict[str, active.C7ActiveModeDecisionFullGameRowV1]:
    orchestrator = active.C7ActiveModeDecisionFullGameOrchestratorV1()
    return {
        scenario_id: orchestrator.run_scenario(scenario_id)
        for scenario_id in active.C7_ACTIVE_MODE_DECISION_REQUIRED_SCENARIOS_V1
    }


def test_frozen_contract_controller_and_scenario_matrix() -> None:
    assert active.C7_ACTIVE_MODE_DECISION_ACCEPTANCE_CONTROLLER_V1_ID == (
        "c7-active-mode-decision-acceptance-controller-v1"
    )
    assert active.C7_ACTIVE_MODE_DECISION_ACCEPTANCE_CONTROLLER_V1_VERSION == "1"
    assert active.C7_ACTIVE_MODE_DECISION_SCENARIO_SCHEMA_V1 == (
        "sgs-c7-active-mode-decision-scenario-v1"
    )
    assert active.C7_ACTIVE_MODE_DECISION_FULL_GAME_REPLAY_SCHEMA_V1 == (
        "sgs-c7-active-mode-decision-full-game-replay-v1"
    )
    assert active.C7_ACTIVE_MODE_DECISION_FULL_GAME_MATRIX_SCHEMA_V1 == (
        "sgs-c7-active-mode-decision-full-game-matrix-v1"
    )
    assert active.C7_ACTIVE_MODE_DECISION_REQUIRED_SCENARIOS_V1 == (
        active.HEIR_SUCCESSION,
        active.SPY_TO_LOYALIST,
        active.SPY_TO_AMBITIONIST,
    )
    assert dict(active.C7_ACTIVE_MODE_DECISION_FROZEN_SEEDS_V1) == {
        active.HEIR_SUCCESSION: 1,
        active.SPY_TO_LOYALIST: 1,
        active.SPY_TO_AMBITIONIST: 2,
    }
    assert set(active.C7_ACTIVE_MODE_DECISION_SCENARIO_CONFIGS_V1) == set(
        active.C7_ACTIVE_MODE_DECISION_REQUIRED_SCENARIOS_V1
    )
    for scenario_id, scenario in active.C7_ACTIVE_MODE_DECISION_SCENARIO_CONFIGS_V1.items():
        assert scenario.scenario_id == scenario_id
        assert scenario.mode_id == FORMAL_NO_SKILL_IDENTITY_8P_HEIR_MODE
        assert scenario.configuration_sha256 == sha256_value(scenario.to_dict())


def test_scenario_configuration_contains_no_hidden_role_steering_oracle() -> None:
    assert {field.name for field in fields(active.C7ActiveModeDecisionScenarioV1)} == {
        "scenario_id",
        "seed",
        "target_operation",
        "target_id",
        "target_path",
        "expected_winner_id",
        "expected_finish_reason",
        "mode_id",
        "schema",
    }
    forbidden = {
        "target_actor_id",
        "protected_player_id",
        "pre_transition_targets",
        "post_transition_targets",
    }
    for scenario in active.C7_ACTIVE_MODE_DECISION_SCENARIO_CONFIGS_V1.values():
        assert forbidden.isdisjoint(scenario.to_dict())
    loyalist = active.c7_active_mode_decision_scenario_v1(active.SPY_TO_LOYALIST)
    ambitionist = active.c7_active_mode_decision_scenario_v1(
        active.SPY_TO_AMBITIONIST
    )
    assert "p5" not in repr(loyalist.to_dict())
    assert "p7" not in repr(ambitionist.to_dict())


def test_controller_choice_is_invariant_to_unseen_hidden_role_mapping() -> None:
    game = FormalHeirAndSpyChoiceIdentitySession(
        seed=1,
        configuration=FormalHeirAndSpyChoiceIdentityConfiguration.formal_profile(),
        analysis_only=False,
        session_id="c7-hidden-invariance",
        session_secret=b"a" * 32,
    )
    public_actions = game.legal_actions()
    public_context = active.C7PublicActionContextV1.from_action_context(game._context())
    hidden_a = dict(game._variant.role_original)
    hidden_b = dict(hidden_a)
    swappable = [
        player_id
        for player_id, role in hidden_b.items()
        if player_id not in {game.current_lord_player_id, "p3"}
        and role != "lord"
    ]
    first = next(
        player_id
        for player_id in swappable
        if hidden_b[player_id] != hidden_b[swappable[0]]
    )
    hidden_b[swappable[0]], hidden_b[first] = (
        hidden_b[first],
        hidden_b[swappable[0]],
    )
    assert hidden_a != hidden_b
    altered_hidden_game = FormalHeirAndSpyChoiceIdentitySession(
        seed=1,
        configuration=FormalHeirAndSpyChoiceIdentityConfiguration.formal_profile(),
        analysis_only=False,
        session_id="c7-hidden-invariance-altered",
        session_secret=b"b" * 32,
    )
    altered_hidden_game._variant.role_original.clear()
    altered_hidden_game._variant.role_original.update(hidden_b)
    altered_hidden_game._variant.role_current.clear()
    altered_hidden_game._variant.role_current.update(hidden_b)
    assert dict(altered_hidden_game._variant.role_original) == hidden_b

    scenario = active.c7_active_mode_decision_scenario_v1(active.HEIR_SUCCESSION)
    choice_a = active.C7ActiveModeDecisionAcceptanceControllerV1(
        scenario
    ).choose_action_id(public_actions, public_context)
    choice_b = active.C7ActiveModeDecisionAcceptanceControllerV1(
        scenario
    ).choose_action_id(public_actions, public_context)
    assert choice_a == choice_b


def test_public_context_excludes_metadata_and_controller_returns_only_issued_id() -> None:
    assert {field.name for field in fields(active.C7PublicActionContextV1)} == {
        "mode_id",
        "phase",
        "actor_id",
        "turn_player_id",
        "response_window_id",
        "expected_revision",
    }
    context = ActionContext(
        mode=FORMAL_NO_SKILL_IDENTITY_8P_HEIR_MODE,
        phase="mode_decision",
        actor_id="p6",
        turn_player_id="p6",
        response_window_id="secret-window",
        expected_revision=4,
        metadata={"private_hand": ["must-not-cross"]},
    )
    public = active.C7PublicActionContextV1.from_action_context(context)
    assert not hasattr(public, "metadata")
    assert "must-not-cross" not in repr(public)

    game = FormalHeirAndSpyChoiceIdentitySession(
        seed=1,
        configuration=FormalHeirAndSpyChoiceIdentityConfiguration.formal_profile(),
        analysis_only=False,
    )
    legal = game.legal_actions()
    controller = active.C7ActiveModeDecisionAcceptanceControllerV1(
        active.c7_active_mode_decision_scenario_v1(active.HEIR_SUCCESSION)
    )
    action_id = controller.choose_action_id(
        legal, active.C7PublicActionContextV1.from_action_context(game._context())
    )
    assert action_id in {action.action_id for action in legal}
    chosen = next(action for action in legal if action.action_id == action_id)
    assert chosen.payload["operation"] == "select_heir"
    assert chosen.payload["target_id"] == "p3"


def test_target_window_pass_duplicate_unissued_and_stale_ids_fail_closed() -> None:
    scenario = active.c7_active_mode_decision_scenario_v1(active.HEIR_SUCCESSION)
    game = FormalHeirAndSpyChoiceIdentitySession(
        seed=1,
        configuration=FormalHeirAndSpyChoiceIdentityConfiguration.formal_profile(),
        analysis_only=False,
    )
    legal = game.legal_actions()
    public = active.C7PublicActionContextV1.from_action_context(game._context())
    target = next(
        action
        for action in legal
        if action.payload.get("operation") == "select_heir"
        and action.payload.get("target_id") == "p3"
    )
    without_target = tuple(action for action in legal if action is not target)
    with pytest.raises(active.C7ActiveModeDecisionFullGameError, match="缺少唯一目标动作"):
        active.C7ActiveModeDecisionAcceptanceControllerV1(scenario).choose_action_id(
            without_target, public
        )
    duplicate_target = replace(target, action_id="act_distinct_duplicate_target")
    with pytest.raises(active.C7ActiveModeDecisionFullGameError, match="重复目标动作"):
        active.C7ActiveModeDecisionAcceptanceControllerV1(scenario).choose_action_id(
            (*legal, duplicate_target), public
        )
    unissued = replace(target, action_id=None)
    with pytest.raises(ProductionBatchError, match="已签发"):
        active.C7ActiveModeDecisionAcceptanceControllerV1(scenario).choose_action_id(
            (unissued,), public
        )

    controller = active.C7ActiveModeDecisionAcceptanceControllerV1(scenario)
    chosen_id = controller.choose_action_id(legal, public)
    game.step(BatchActionIdController(chosen_id))
    with pytest.raises(ProductionBatchError, match="过期|伪造"):
        game.step(BatchActionIdController(chosen_id))


def test_three_frozen_seed_production_full_games_and_required_proofs(
    scenario_rows: dict[str, active.C7ActiveModeDecisionFullGameRowV1],
) -> None:
    for scenario_id, row in scenario_rows.items():
        assert row.seed == active.C7_ACTIVE_MODE_DECISION_FROZEN_SEEDS_V1[scenario_id]
        replay = row.replay
        assert replay.header["controller_id"] == (
            active.C7_ACTIVE_MODE_DECISION_ACCEPTANCE_CONTROLLER_V1_ID
        )
        assert replay.header["controller_version"] == "1"
        assert replay.header["production_replay_v1_sha256"] == (
            replay.production_replay_v1.record_sha256
        )
        assert replay.production_replay_v1.header["fixture_applied"] is False
        assert replay.production_replay_v1.header["formal_result"] is True
        assert replay.production_replay_v1.header["initial_configuration"][
            "analysis_only"
        ] is False
        proof = replay.required_active_decision_proof
        assert proof["scenario_proven"] is True
        assert proof["active_decision"]["target_match_count"] == 1
        assert proof["common"]["target_action_selected_exactly_once"] is True
        assert proof["common"]["target_window_passed"] is False
        assert proof["common"]["terminal"] is True
        assert proof["common"]["unsupported_or_approximation"] is False

    heir = scenario_rows[active.HEIR_SUCCESSION].replay.required_active_decision_proof[
        "scenario_evidence"
    ]
    assert heir["old_lord_id"] == "p6"
    assert heir["heir_id"] == "p3"
    assert heir["old_lord_dead"] is True
    assert heir["old_lord_natural_death_event"] is True
    assert heir["succession_event"] is True
    assert heir["seat_unchanged"] is True
    assert heir["numbered_order_unchanged"] is True
    assert heir["max_hp_plus_one"] is True
    assert heir["hp_recovery_correct"] is True
    assert heir["is_extra_turn"] is False
    assert heir["natural_identity_victory"] is True

    loyalist = scenario_rows[
        active.SPY_TO_LOYALIST
    ].replay.required_active_decision_proof["scenario_evidence"]
    assert loyalist["role_after_choice"] == "spy"
    assert loyalist["pending_after_choice"] is True
    assert loyalist["locked_after_choice"] is True
    assert loyalist["converted_role"] == "loyalist"
    assert loyalist["conversion_at_later_turn_start"] is True
    assert loyalist["conversion_event"] is True
    assert loyalist["natural_identity_victory"] is True

    ambitionist = scenario_rows[
        active.SPY_TO_AMBITIONIST
    ].replay.required_active_decision_proof["scenario_evidence"]
    assert ambitionist["role_after_choice"] == "spy"
    assert ambitionist["pending_after_choice"] is True
    assert ambitionist["locked_after_choice"] is True
    assert ambitionist["converted_role"] == "ambitionist"
    assert ambitionist["conversion_event"] is True
    assert ambitionist["ambitionist_mark_established"] is True
    assert ambitionist["ambitionist_mark_use_count"] >= 1
    assert ambitionist["natural_identity_victory"] is True
    assert scenario_rows[active.SPY_TO_AMBITIONIST].replay.production_replay_v1.outcome[
        "winner_id"
    ] == "ambitionist"
    assert scenario_rows[active.SPY_TO_AMBITIONIST].replay.production_replay_v1.outcome[
        "finish_reason"
    ] == "identity_victory"


def test_replay_roundtrip_strict_reexecutes_and_rederives_controller_proof(
    scenario_rows: dict[str, active.C7ActiveModeDecisionFullGameRowV1],
) -> None:
    replay = scenario_rows[active.SPY_TO_AMBITIONIST].replay
    rebuilt = active.C7ActiveModeDecisionFullGameReplayV1.from_dict(replay.to_dict())
    assert rebuilt.replay_sha256 == replay.replay_sha256
    assert rebuilt.scenario_id == active.SPY_TO_AMBITIONIST
    assert rebuilt.required_active_decision_proof["scenario_proven"] is True


@pytest.mark.parametrize(
    "mutation,match",
    (
        (lambda payload: payload.__setitem__("schema", "forged"), "schema"),
        (
            lambda payload: payload["header"].__setitem__("controller_id", "drift"),
            "controller id",
        ),
        (
            lambda payload: payload["header"].__setitem__(
                "implementation_identity", "0" * 64
            ),
            "身份漂移|implementation_identity|不匹配",
        ),
        (
            lambda payload: payload["header"].__setitem__(
                "scenario_configuration_sha256", "0" * 64
            ),
            "configuration hash",
        ),
        (
            lambda payload: payload["header"].__setitem__(
                "production_replay_v1_sha256", "0" * 64
            ),
            "production replay-v1 hash",
        ),
    ),
)
def test_schema_controller_config_identity_and_hash_drift_fail_before_reexecution(
    scenario_rows: dict[str, active.C7ActiveModeDecisionFullGameRowV1],
    mutation,
    match: str,
) -> None:
    payload = deepcopy(scenario_rows[active.HEIR_SUCCESSION].replay.to_dict())
    mutation(payload)
    payload["replay_sha256"] = _outer_hash(payload)
    with pytest.raises((active.C7ActiveModeDecisionFullGameError, ProductionReplayDivergenceError), match=match):
        active.C7ActiveModeDecisionFullGameReplayV1.from_dict(payload)


@pytest.mark.parametrize("conflict", ("inner_record_hash", "outer_replay_hash"))
def test_inner_and_outer_hash_conflicts_reject_before_both_session_constructors(
    scenario_rows: dict[str, active.C7ActiveModeDecisionFullGameRowV1],
    monkeypatch: pytest.MonkeyPatch,
    conflict: str,
) -> None:
    payload = deepcopy(scenario_rows[active.HEIR_SUCCESSION].replay.to_dict())
    constructor_calls = {"active_import": 0, "runtime_type": 0}

    def active_constructor_bomb(*args, **kwargs):
        del args, kwargs
        constructor_calls["active_import"] += 1
        raise AssertionError("ACTIVE_SESSION_CONSTRUCTOR_REACHED")

    def runtime_constructor_bomb(*args, **kwargs):
        del args, kwargs
        constructor_calls["runtime_type"] += 1
        raise AssertionError("RUNTIME_SESSION_CONSTRUCTOR_REACHED")

    runtime_session_type = production_replay_module._identity_replay_runtime(
        FORMAL_NO_SKILL_IDENTITY_8P_HEIR_MODE
    )[1]
    assert runtime_session_type is FormalHeirAndSpyChoiceIdentitySession
    monkeypatch.setattr(
        active,
        "FormalHeirAndSpyChoiceIdentitySession",
        active_constructor_bomb,
    )
    monkeypatch.setattr(runtime_session_type, "__init__", runtime_constructor_bomb)
    if conflict == "inner_record_hash":
        # 同时调整表层 header 与 outer hash，使拒绝只能来自 embedded
        # production record 的 inner record_sha256 校验。
        payload["production_replay_v1"]["record_sha256"] = "0" * 64
        payload["header"]["production_replay_v1_sha256"] = "0" * 64
        payload["replay_sha256"] = _outer_hash(payload)
        assert payload["header"]["production_replay_v1_sha256"] == payload[
            "production_replay_v1"
        ]["record_sha256"]
        error_types = (ProductionReplayFormatError,)
    else:
        payload["replay_sha256"] = "0" * 64
        error_types = (active.C7ActiveModeDecisionFullGameError,)
    with pytest.raises(error_types):
        active.C7ActiveModeDecisionFullGameReplayV1.from_dict(payload)
    assert constructor_calls == {"active_import": 0, "runtime_type": 0}


def test_replay_mismatch_and_forged_proof_fail_closed(
    scenario_rows: dict[str, active.C7ActiveModeDecisionFullGameRowV1],
) -> None:
    replay = scenario_rows[active.SPY_TO_LOYALIST].replay
    mismatch = deepcopy(replay.to_dict())
    mismatch["production_replay_v1"]["decisions"][0]["chosen_action_id"] = "forged"
    mismatch["replay_sha256"] = _outer_hash(mismatch)
    with pytest.raises((active.C7ActiveModeDecisionFullGameError, ProductionReplayFormatError)):
        active.C7ActiveModeDecisionFullGameReplayV1.from_dict(mismatch)

    forged = deepcopy(replay.to_dict())
    forged["required_active_decision_proof"]["scenario_proven"] = False
    forged["replay_sha256"] = _outer_hash(forged)
    with pytest.raises(active.C7ActiveModeDecisionFullGameError, match="serialized"):
        active.C7ActiveModeDecisionFullGameReplayV1.from_dict(forged)


@pytest.mark.parametrize(
    "scenario_id,mutation",
    (
        (active.HEIR_SUCCESSION, "wrong_event_type"),
        (active.HEIR_SUCCESSION, "wrong_transition_revision"),
        (active.SPY_TO_LOYALIST, "wrong_turn_player_after"),
        (active.SPY_TO_LOYALIST, "same_name_event_other_actor"),
        (active.SPY_TO_LOYALIST, "loyalist_wrong_event_type"),
        (active.SPY_TO_LOYALIST, "wrong_choice_revision"),
        (active.SPY_TO_LOYALIST, "wrong_conversion_window"),
        (active.SPY_TO_LOYALIST, "same_name_event_other_transition"),
        (active.SPY_TO_AMBITIONIST, "empty_mark_event_indices"),
        (active.SPY_TO_AMBITIONIST, "wrong_mark_use_actor"),
        (active.SPY_TO_AMBITIONIST, "mark_use_before_conversion"),
        (active.SPY_TO_AMBITIONIST, "ambitionist_wrong_turn_player_after"),
        (active.SPY_TO_LOYALIST, "correct_final_wrong_intermediate_chain"),
    ),
)
def test_causal_binding_adversarial_mutations_fail_closed(
    scenario_rows: dict[str, active.C7ActiveModeDecisionFullGameRowV1],
    scenario_id: str,
    mutation: str,
) -> None:
    payload = deepcopy(scenario_rows[scenario_id].replay.to_dict())
    proof = payload["required_active_decision_proof"]
    causal = proof["causal_binding"]
    if mutation == "wrong_event_type":
        causal["succession_transition"]["succession_event"][
            "event_type"
        ] = "damage"
    elif mutation == "wrong_transition_revision":
        causal["succession_transition"]["expected_revision"] = 999999
    elif mutation == "wrong_turn_player_after":
        causal["conversion_transition"]["turn_player_after"] = "p8"
    elif mutation == "same_name_event_other_actor":
        causal["conversion_transition"]["actor_id"] = "p8"
    elif mutation == "loyalist_wrong_event_type":
        causal["conversion_transition"]["conversion_event"][
            "event_type"
        ] = "damage"
    elif mutation == "wrong_choice_revision":
        causal["choice_transition"]["expected_revision"] = 999999
    elif mutation == "wrong_conversion_window":
        causal["conversion_transition"]["response_window_id"] = "wrong-window"
    elif mutation == "same_name_event_other_transition":
        event = causal["conversion_transition"]["conversion_event"]
        event["decision_index"] += 1
    elif mutation == "empty_mark_event_indices":
        causal["mark_use_transition"]["bound_event_indices"] = []
    elif mutation == "wrong_mark_use_actor":
        causal["mark_use_transition"]["actor_id"] = "p8"
    elif mutation == "mark_use_before_conversion":
        causal["mark_use_transition"]["decision_index"] = (
            causal["conversion_transition"]["decision_index"] - 1
        )
    elif mutation == "ambitionist_wrong_turn_player_after":
        causal["conversion_transition"]["turn_player_after"] = "p8"
    elif mutation == "correct_final_wrong_intermediate_chain":
        assert causal["terminal_transition"]["is_finished"] is True
        causal["choice_transition"]["pending_after_choice"] = False
    else:  # pragma: no cover - parameter table is frozen above
        raise AssertionError(mutation)
    assert active._causal_binding_proven(scenario_id, causal) is False
    proof["scenario_proven"] = False
    payload["replay_sha256"] = _outer_hash(payload)
    with pytest.raises(active.C7ActiveModeDecisionFullGameError, match="serialized"):
        active.C7ActiveModeDecisionFullGameReplayV1.from_dict(payload)


def _matrix_payload(
    scenario_rows: dict[str, active.C7ActiveModeDecisionFullGameRowV1],
) -> dict[str, object]:
    return {
        "schema": active.C7_ACTIVE_MODE_DECISION_FULL_GAME_MATRIX_SCHEMA_V1,
        "required_scenarios": list(
            active.C7_ACTIVE_MODE_DECISION_REQUIRED_SCENARIOS_V1
        ),
        "rows": [
            scenario_rows[scenario_id].to_dict()
            for scenario_id in active.C7_ACTIVE_MODE_DECISION_REQUIRED_SCENARIOS_V1
        ],
        "derived_gates": {
            "c7_active_mode_decision_full_game_v1_proven": True
        },
    }


def test_matrix_strict_reexecution_is_the_only_derived_gate(
    scenario_rows: dict[str, active.C7ActiveModeDecisionFullGameRowV1],
) -> None:
    matrix = active.C7ActiveModeDecisionFullGameMatrixV1(
        tuple(
            scenario_rows[scenario_id]
            for scenario_id in active.C7_ACTIVE_MODE_DECISION_REQUIRED_SCENARIOS_V1
        )
    )
    gates = matrix.derived_gates()
    assert gates.to_dict() == {
        "c7_active_mode_decision_full_game_v1_proven": True
    }
    assert set(gates.to_dict()) == {
        "c7_active_mode_decision_full_game_v1_proven"
    }


@pytest.mark.parametrize("kind", ("missing", "duplicate", "extra"))
def test_matrix_missing_duplicate_and_extra_rows_fail_closed(
    scenario_rows: dict[str, active.C7ActiveModeDecisionFullGameRowV1],
    kind: str,
) -> None:
    payload = _matrix_payload(scenario_rows)
    rows = payload["rows"]
    assert isinstance(rows, list)
    if kind == "missing":
        rows.pop()
    elif kind == "duplicate":
        rows[2] = deepcopy(rows[1])
    else:
        rows.append(
            {
                "scenario_id": "UNKNOWN_EXTRA",
                "seed": 9,
                "replay": deepcopy(rows[0]["replay"]),
            }
        )
    with pytest.raises(active.C7ActiveModeDecisionFullGameError, match="row"):
        active.C7ActiveModeDecisionFullGameMatrixV1.from_dict(payload)
