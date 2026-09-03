# -*- coding: utf-8 -*-
"""BRIDGE-C public-only acceptance controller and bounded live façade tests."""

from __future__ import annotations

import ast
from dataclasses import FrozenInstanceError, replace
import inspect
import textwrap

import pytest

from scripts.sgs_engine import skill_aware_fixed_assignment_full_game_bridge as bridge
from scripts.sgs_engine.actions import ActionContext, ActionType, LegalAction
from scripts.sgs_engine.formal_duel import FormalDuelConfiguration, FormalNoSkillDuelSession
from scripts.sgs_engine.production_batch import ProductionBasicCardBatch, ProductionPhase


def _window_kind(phase: str) -> str:
    if phase == ProductionPhase.DYING_RESCUE.value:
        return "rescue"
    if phase in {
        ProductionPhase.JUDGMENT_WUXIE.value,
        ProductionPhase.SLASH_RESPONSE.value,
        ProductionPhase.TRICK_RESPONSE.value,
        ProductionPhase.DUEL_RESPONSE.value,
        ProductionPhase.FIRE_ATTACK_REVEAL.value,
        ProductionPhase.FIRE_ATTACK_DISCARD.value,
        ProductionPhase.BORROWED_SWORD_CHOICE.value,
        ProductionPhase.NANMAN_RESPONSE.value,
        ProductionPhase.WANJIAN_RESPONSE.value,
    }:
        return "response"
    if phase in {
        ProductionPhase.ZONE_CHOICE.value,
        ProductionPhase.WUGU_PICK.value,
        ProductionPhase.CIXIONG_TARGET_CHOICE.value,
        ProductionPhase.SUCCESSION_CARD_CHOICE.value,
    }:
        return "public_choice"
    if phase in {
        ProductionPhase.DISCARD.value,
        ProductionPhase.WEAPON_DISCARD_TWO.value,
        ProductionPhase.HANBING_DISCARD.value,
    }:
        return "discard"
    return "phase"


def _context(
    phase: str = ProductionPhase.PLAY.value,
    *,
    actor_id: str = "p1",
    revision: int = 7,
) -> bridge.PublicActionContextV1:
    return bridge.PublicActionContextV1(
        mode_id=bridge.MODE_ID,
        phase=phase,
        actor_id=actor_id,
        turn_player_id="p1",
        response_window_id=("window-1" if _window_kind(phase) in {"response", "rescue"} else None),
        expected_revision=revision,
        seat_order=bridge.PARTICIPANT_IDS,
        action_window_kind=_window_kind(phase),
    )


def _action(
    action_id: str,
    operation: str,
    *,
    context: bridge.PublicActionContextV1 | None = None,
    action_type: ActionType = ActionType.CHOOSE_OPTION,
    actor_id: str | None = None,
    target_ids: tuple[str, ...] = (),
    ordinal: int = 0,
    virtual: bool = False,
    choice: str | None = None,
    skill_id: str | None = None,
) -> bridge.PublicLegalActionProjectionV1:
    public_context = context or _context()
    return bridge.PublicLegalActionProjectionV1(
        action_id=action_id,
        action_type=action_type.value,
        operation=operation,
        actor_id=actor_id or public_context.actor_id,
        target_ids=target_ids,
        virtual=virtual,
        public_source_zone=None,
        choice_ordinal=ordinal,
        public_choice_token=None,
        public_choice_value=choice,
        public_skill_id=skill_id,
        response_window_kind=public_context.action_window_kind,
        revision=public_context.expected_revision,
    )


def _choose(
    context: bridge.PublicActionContextV1,
    *actions: bridge.ControllerActionProjectionV1,
) -> str:
    return bridge.SkillAwareFixedAssignmentAcceptanceControllerV1().choose(
        tuple(actions), context
    )


def test_exact_controller_id_version_and_stateless_shape() -> None:
    controller = bridge.SkillAwareFixedAssignmentAcceptanceControllerV1()
    assert controller.controller_id == "skill-aware-fixed-assignment-acceptance-controller-v1"
    assert controller.controller_version == 1
    assert controller.strategy_version == (
        "skill-aware-fixed-assignment-acceptance-controller-v1.1"
    )
    assert not hasattr(controller, "__dict__")


def test_exact_public_context_schema_is_immutable_and_metadata_free() -> None:
    raw = ActionContext(
        mode=bridge.MODE_ID,
        phase=ProductionPhase.PLAY.value,
        actor_id="p1",
        turn_player_id="p1",
        response_window_id=None,
        expected_revision=3,
        metadata={
            "private_hand": ["secret-a"],
            "deck_contents": ["future-a"],
            "rng": "secret-state",
            "expected_winner": "p1",
        },
    )
    public = bridge.PublicActionContextV1.from_action_context(raw)
    assert set(public.to_dict()) == {
        "mode_id",
        "phase",
        "actor_id",
        "turn_player_id",
        "response_window_id",
        "expected_revision",
        "seat_order",
        "action_window_kind",
    }
    assert public.as_action_context().metadata == {}
    assert not set(public.to_dict()) & bridge.CONTROLLER_PRIVATE_FIELD_DENYLIST
    with pytest.raises(FrozenInstanceError):
        public.phase = "draw"  # type: ignore[misc]


@pytest.mark.parametrize("field", ["unknown", "metadata", "private_hand", "seed"])
def test_public_context_unknown_or_private_field_rejected(field: str) -> None:
    data = _context().to_dict()
    data[field] = "forbidden"
    with pytest.raises(bridge.BridgeContractError):
        bridge.PublicActionContextV1.from_dict(data)


def test_exact_public_gameplay_projection_schema_and_private_data_stripping() -> None:
    context = _context(revision=11)
    raw = LegalAction(
        action_type=ActionType.USE_CARD,
        actor_id="p1",
        card_instance_id="private-hand-card-001",
        target_ids=("p2",),
        payload={
            "operation": "use_slash",
            "card_name": "杀",
            "suit": "spade",
            "rank": 7,
            "handle": "private-handle",
            "future_cards": ["private-future"],
            "expected_revision": 11,
        },
        action_id="signed-slash",
    )
    projected = bridge.project_signed_legal_actions_v1((raw,), context)
    assert len(projected) == 1
    item = projected[0]
    assert type(item) is bridge.PublicLegalActionProjectionV1
    assert set(item.to_dict()) == {
        "action_id",
        "action_type",
        "operation",
        "actor_id",
        "target_ids",
        "virtual",
        "public_source_zone",
        "choice_ordinal",
        "public_choice_token",
        "public_choice_value",
        "public_skill_id",
        "response_window_kind",
        "revision",
    }
    assert not set(item.to_dict()) & bridge.CONTROLLER_PRIVATE_FIELD_DENYLIST
    assert "private-hand-card-001" not in repr(item.to_dict())
    assert item.operation == "use_slash"


@pytest.mark.parametrize(
    "field",
    [
        "card_instance_id",
        "card_name",
        "card_type",
        "suit",
        "rank",
        "color",
        "deck_index",
        "future_draw_consequence",
        "handle",
        "material_card_instance_ids",
        "unknown",
    ],
)
def test_public_gameplay_projection_rejects_private_or_unknown_field(field: str) -> None:
    data = _action("signed-a", "use_slash").to_dict()
    data[field] = "forbidden"
    with pytest.raises(bridge.BridgeContractError):
        bridge.PublicLegalActionProjectionV1.from_dict(data)


def test_raw_session_state_runtime_and_legal_action_are_not_controller_inputs() -> None:
    game = bridge.create_skill_aware_fixed_assignment_duel_session_v1(
        seed=0,
        general_key="shamoke",
        seat_assignment="GENERAL_AS_P1",
    )
    controller = bridge.SkillAwareFixedAssignmentAcceptanceControllerV1()
    context = _context()
    with pytest.raises(TypeError):
        controller.choose(game, context)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        controller.choose((game.state,), context)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        controller.choose((game.skill_runtime,), context)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        controller.choose(game.legal_actions(), context)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        controller.choose((_action("signed-a", "use_slash"),), game)  # type: ignore[arg-type]


def test_normal_play_equipment_target_and_phase_ranking() -> None:
    context = _context()
    actions = (
        _action("end", "end_play_phase", context=context, action_type=ActionType.PASS, ordinal=0),
        _action("equip", "use_weapon", context=context, action_type=ActionType.USE_CARD, ordinal=1),
        _action("slash", "use_slash", context=context, action_type=ActionType.USE_CARD, target_ids=("p2",), ordinal=2),
        _action("heal", "heal_self", context=context, action_type=ActionType.USE_CARD, target_ids=("p1",), ordinal=3),
    )
    assert _choose(context, *actions) == "heal"
    assert _choose(context, *reversed(actions)) == "heal"
    assert _choose(context, actions[0], actions[1]) == "equip"

    choice_context = _context(ProductionPhase.ZONE_CHOICE.value)
    target_p2 = _action(
        "target-p2",
        "choose_target_zone_card",
        context=choice_context,
        target_ids=("p2",),
        ordinal=0,
    )
    target_p1 = replace(target_p2, action_id="target-p1", target_ids=("p1",), choice_ordinal=1)
    assert _choose(choice_context, target_p2, target_p1) == "target-p1"

    prepare = _context(ProductionPhase.PREPARE.value)
    proceed = _action(
        "proceed",
        "proceed_prepare",
        context=prepare,
        action_type=ActionType.PASS,
    )
    assert _choose(prepare, proceed) == "proceed"


@pytest.mark.parametrize(
    ("phase", "response_operation", "pass_operation"),
    [
        (ProductionPhase.SLASH_RESPONSE.value, "play_dodge", "pass_slash_response"),
        (ProductionPhase.DUEL_RESPONSE.value, "play_slash_for_duel", "pass_duel_slash"),
        (ProductionPhase.NANMAN_RESPONSE.value, "play_slash_for_nanman", "pass_nanman_slash"),
        (ProductionPhase.WANJIAN_RESPONSE.value, "play_jink_for_wanjian", "pass_wanjian_jink"),
        (ProductionPhase.TRICK_RESPONSE.value, "use_wuxie", "pass_trick_response"),
    ],
)
def test_response_windows_choose_only_signed_response(
    phase: str, response_operation: str, pass_operation: str
) -> None:
    context = _context(phase)
    passed = _action(
        "pass",
        pass_operation,
        context=context,
        action_type=ActionType.PASS,
        ordinal=0,
    )
    response = _action(
        "response",
        response_operation,
        context=context,
        action_type=ActionType.RESPOND,
        ordinal=1,
    )
    assert _choose(context, passed, response) == "response"
    assert _choose(context, passed) == "pass"


def test_rescue_precedence_never_fabricates_an_action() -> None:
    context = _context(ProductionPhase.DYING_RESCUE.value, actor_id="p1")
    passed = _action("pass", "pass_rescue", context=context, action_type=ActionType.PASS, ordinal=0)
    other_peach = _action(
        "other-peach",
        "rescue_with_peach",
        context=context,
        action_type=ActionType.USE_CARD,
        target_ids=("p2",),
        ordinal=1,
    )
    self_wine = _action(
        "self-wine",
        "rescue_with_wine",
        context=context,
        action_type=ActionType.USE_CARD,
        target_ids=("p1",),
        ordinal=2,
    )
    self_peach = _action(
        "self-peach",
        "rescue_with_peach",
        context=context,
        action_type=ActionType.USE_CARD,
        target_ids=("p1",),
        ordinal=3,
    )
    assert _choose(context, passed, other_peach, self_wine, self_peach) == "self-peach"
    assert _choose(context, passed) == "pass"


def test_discard_and_equipment_selection_are_loop_resistant() -> None:
    discard = _context(ProductionPhase.DISCARD.value)
    select = _action("select", "select_discard_card", context=discard, ordinal=0)
    unselect = _action("unselect", "unselect_discard_card", context=discard, ordinal=1)
    assert {_choose(discard, select, unselect) for _ in range(20)} == {"select"}
    submit = _action("submit", "discard_phase_submit", context=discard, ordinal=2)
    assert {_choose(discard, select, unselect, submit) for _ in range(20)} == {"submit"}

    weapon = _context(ProductionPhase.WEAPON_DISCARD_TWO.value)
    w_select = _action("w-select", "select_discard_two", context=weapon, ordinal=0)
    w_unselect = _action("w-unselect", "unselect_discard_two", context=weapon, ordinal=1)
    assert {_choose(weapon, w_select, w_unselect) for _ in range(20)} == {"w-select"}


def test_optional_skill_activate_before_pass_and_pass_only() -> None:
    context = _context(ProductionPhase.END.value)
    passed = _action(
        "pass-skill",
        "pass_skill",
        context=context,
        action_type=ActionType.PASS,
        ordinal=0,
        skill_id="sgs_skill_jili",
    )
    activate = _action(
        "activate",
        "activate_skill",
        context=context,
        action_type=ActionType.ACTIVATE_SKILL,
        ordinal=1,
        skill_id="sgs_skill_jili",
    )
    assert _choose(context, passed, activate) == "activate"
    assert _choose(context, passed) == "pass-skill"


def test_qianchong_category_policy_is_basic_trick_equipment() -> None:
    context = _context()
    equipment = _action(
        "equipment",
        "qianchong_choice",
        context=context,
        choice="equipment",
        skill_id="sgs_skill_qianchong",
        ordinal=0,
    )
    trick = replace(equipment, action_id="trick", public_choice_value="trick", choice_ordinal=1)
    basic = replace(equipment, action_id="basic", public_choice_value="basic", choice_ordinal=2)
    assert _choose(context, equipment, trick, basic) == "basic"


def test_zuilun_private_projection_is_exact_opaque_and_ordinal_only() -> None:
    context = _context(ProductionPhase.END.value, revision=22)

    def raw(action_id: str, observed: list[str], selected: list[str]) -> LegalAction:
        return LegalAction(
            action_type=ActionType.CHOOSE_OPTION,
            actor_id="p1",
            skill_id="sgs_skill_zuilun",
            payload={
                "operation": "private_card_selection_submit",
                "window_id": "private-window",
                "continuation_identity": "private-continuation",
                "observed_card_ids": observed,
                "selected_card_ids": selected,
                "remaining_top_order": [item for item in observed if item not in selected],
                "expected_revision": 22,
            },
            action_id=action_id,
        )

    first = bridge.project_signed_legal_actions_v1(
        (
            raw("signed-0", ["red-peach", "black-slash", "club-trick"], ["red-peach"]),
            raw("signed-1", ["red-peach", "black-slash", "club-trick"], ["black-slash"]),
            raw("signed-2", ["red-peach", "black-slash", "club-trick"], ["club-trick"]),
        ),
        context,
    )
    swapped = bridge.project_signed_legal_actions_v1(
        (
            raw("signed-0", ["club-trick", "red-peach", "black-slash"], ["club-trick"]),
            raw("signed-1", ["club-trick", "red-peach", "black-slash"], ["red-peach"]),
            raw("signed-2", ["club-trick", "red-peach", "black-slash"], ["black-slash"]),
        ),
        context,
    )
    assert first == swapped
    assert all(set(item.to_dict()) == bridge.PRIVATE_SELECTION_ALLOWED_FIELDS for item in first)
    assert _choose(context, *first) == "signed-0"
    assert _choose(context, *swapped) == "signed-0"


@pytest.mark.parametrize(
    "field",
    sorted(bridge.CONTROLLER_PRIVATE_FIELD_DENYLIST - {"metadata"}),
)
def test_zuilun_private_projection_adversarial_fields_fail_closed(field: str) -> None:
    data = {
        "action_id": "signed-0",
        "choice_token": "opaque:0",
        "ordinal": 0,
        "publicly_allowed_action_type": ActionType.CHOOSE_OPTION.value,
        field: "private",
    }
    with pytest.raises(bridge.BridgeContractError):
        bridge.PublicOpaqueChoiceProjection.from_dict(data)


def test_private_hands_deck_rng_metadata_general_and_seed_are_policy_invisible() -> None:
    raw_a = ActionContext(
        mode=bridge.MODE_ID,
        phase=ProductionPhase.PLAY.value,
        actor_id="p1",
        turn_player_id="p1",
        expected_revision=9,
        metadata={
            "private_hand": ["A", "B"],
            "deck_contents": ["C", "D"],
            "rng": "rng-a",
            "general_name": "shamoke",
            "seed": 0,
            "expected_winner": "p1",
            "future_cards": ["C"],
        },
    )
    raw_b = replace(
        raw_a,
        metadata={
            "private_hand": ["X", "Y", "Z"],
            "deck_contents": ["Q", "R"],
            "rng": "rng-b",
            "general_name": "wangyuanji",
            "seed": 49,
            "expected_winner": "p2",
            "future_cards": ["Q"],
        },
    )
    public_a = bridge.PublicActionContextV1.from_action_context(raw_a)
    public_b = bridge.PublicActionContextV1.from_action_context(raw_b)
    assert public_a == public_b
    actions = (
        _action("slash", "use_slash", context=public_a, action_type=ActionType.USE_CARD, target_ids=("p2",)),
        _action("end", "end_play_phase", context=public_a, action_type=ActionType.PASS, ordinal=1),
    )
    assert _choose(public_a, *actions) == _choose(public_b, *actions) == "slash"
    source = inspect.getsource(bridge.SkillAwareFixedAssignmentAcceptanceControllerV1)
    for forbidden in ("shamoke", "zhugezhan", "wangyuanji", "seed"):
        assert forbidden not in source


def test_unsigned_duplicate_stale_empty_and_unknown_actions_fail_closed() -> None:
    context = _context(revision=5)
    unsigned = LegalAction(
        action_type=ActionType.PASS,
        actor_id="p1",
        payload={"operation": "end_play_phase"},
    )
    with pytest.raises(bridge.BridgeContractError, match="unsigned"):
        bridge.project_signed_legal_actions_v1((unsigned,), context)
    stale = replace(
        unsigned,
        action_id="signed-stale",
        payload={"operation": "end_play_phase", "expected_revision": 4},
    )
    with pytest.raises(bridge.BridgeContractError, match="revision"):
        bridge.project_signed_legal_actions_v1((stale,), context)
    duplicate = _action("same", "use_slash", context=context)
    with pytest.raises(bridge.BridgeContractError, match="duplicate"):
        _choose(context, duplicate, duplicate)
    same_ordinal = replace(
        duplicate,
        action_id="different-id",
        operation="use_duel",
    )
    with pytest.raises(bridge.BridgeContractError, match="choice_ordinal"):
        _choose(context, duplicate, same_ordinal)
    with pytest.raises(bridge.BridgeContractError, match="empty"):
        _choose(context)
    data = duplicate.to_dict()
    data["operation"] = "unknown_operation"
    with pytest.raises(bridge.BridgeContractError, match="unknown action family"):
        bridge.PublicLegalActionProjectionV1.from_dict(data)


def test_supported_action_family_inventory_is_explicit_and_has_no_fallback() -> None:
    assert bridge.SUPPORTED_ACTION_FAMILIES == (
        "card_use",
        "discard",
        "equipment_decision",
        "equipment_use",
        "mode_decision",
        "phase_advance",
        "private_player_choice",
        "public_target_choice",
        "rescue",
        "response",
        "skill_decision",
    )
    assert len(bridge.SUPPORTED_OPERATION_FAMILIES) == 82
    assert set(bridge.SUPPORTED_OPERATION_FAMILIES.values()) == set(
        bridge.SUPPORTED_ACTION_FAMILIES
    )

    apply_tree = ast.parse(
        textwrap.dedent(inspect.getsource(ProductionBasicCardBatch._apply_for_adapter))
    )
    production_operations: set[str] = set()
    for node in ast.walk(apply_tree):
        if not isinstance(node, ast.Compare):
            continue
        if not any(
            isinstance(item, ast.Name) and item.id == "operation"
            for item in ast.walk(node)
        ):
            continue
        production_operations.update(
            item.value
            for item in ast.walk(node)
            if isinstance(item, ast.Constant)
            and isinstance(item.value, str)
            and item.value
            and not item.value.startswith("sgs_")
        )
    assert set(bridge.SUPPORTED_OPERATION_FAMILIES) == production_operations

    rank_source = inspect.getsource(
        bridge.SkillAwareFixedAssignmentAcceptanceControllerV1._rank
    )
    assert "action_id" not in rank_source
    for forbidden in ("random", "time.", "hash(", "id("):
        assert forbidden not in rank_source


def test_controller_conformance_round_trip_and_adversarial_rejection() -> None:
    context = _context()
    actions = (
        _action("slash", "use_slash", context=context, action_type=ActionType.USE_CARD, target_ids=("p2",)),
        _action("end", "end_play_phase", context=context, action_type=ActionType.PASS, ordinal=1),
    )
    record = bridge.create_controller_decision_record_v1(context, actions)
    assert record.chosen_action_id == "slash"
    assert bridge.assert_controller_conformance_v1(record) == "slash"
    assert bridge.ControllerDecisionRecordV1.from_dict(record.to_dict()) == record

    for field, value in (("controller_id", "wrong"), ("controller_version", 2)):
        data = record.to_dict()
        data[field] = value
        with pytest.raises(bridge.BridgeContractError):
            bridge.ControllerDecisionRecordV1.from_dict(data)

    altered_context = record.to_dict()
    altered_context["public_context"]["phase"] = ProductionPhase.DRAW.value
    altered_context["public_context"]["action_window_kind"] = "phase"
    with pytest.raises(bridge.BridgeContractError, match="altered public context"):
        bridge.ControllerDecisionRecordV1.from_dict(altered_context)

    missing = record.to_dict()
    missing["legal_action_projections"] = missing["legal_action_projections"][1:]
    with pytest.raises(bridge.BridgeContractError, match="missing legal action"):
        bridge.ControllerDecisionRecordV1.from_dict(missing)

    wrong_choice = replace(record, chosen_action_id="end")
    with pytest.raises(bridge.BridgeContractError, match="deterministic policy"):
        bridge.assert_controller_conformance_v1(wrong_choice)

    private = record.to_dict()
    private["private_hand"] = ["secret"]
    with pytest.raises(bridge.BridgeContractError, match="private authority"):
        bridge.ControllerDecisionRecordV1.from_dict(private)


@pytest.mark.parametrize("general_key", bridge.GENERAL_ALLOWLIST)
@pytest.mark.parametrize("seat_assignment", tuple(bridge.FixedAssignment))
def test_bounded_live_bridge_trace_25_steps(
    general_key: str, seat_assignment: bridge.FixedAssignment
) -> None:
    game = bridge.create_skill_aware_fixed_assignment_duel_session_v1(
        seed=0,
        general_key=general_key,
        seat_assignment=seat_assignment,
    )
    operations: list[str] = []
    for _ in range(25):
        if game.is_finished:
            break
        public_context, projections = game.public_action_surface_v1()
        assert projections
        decision = bridge.create_controller_decision_record_v1(
            public_context, projections
        )
        assert bridge.assert_controller_conformance_v1(decision) == decision.chosen_action_id
        chosen = next(item for item in projections if item.action_id == decision.chosen_action_id)
        operations.append(
            chosen.publicly_allowed_action_type
            if type(chosen) is bridge.PublicOpaqueChoiceProjection
            else chosen.operation
        )
        game.step(decision.chosen_action_id)
    assert game.step_count == len(operations)
    assert 0 < game.step_count <= 25
    if not game.is_finished:
        assert game.legal_actions()


def test_no_skill_session_does_not_discover_bridge_controller() -> None:
    game = FormalNoSkillDuelSession(
        seed=0,
        configuration=FormalDuelConfiguration.formal_profile(),
    )
    assert game.skill_runtime is None
    assert not hasattr(game, "public_action_surface_v1")
    assert not hasattr(game, "step_with_acceptance_controller_v1")
    assert all(type(item).__name__ != "SkillAwareFixedAssignmentAcceptanceControllerV1" for item in vars(game).values())
