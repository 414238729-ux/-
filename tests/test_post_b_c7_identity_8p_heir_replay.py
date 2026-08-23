# -*- coding: utf-8 -*-
"""POST-B C7：一等 strict replay、跨模式篡改失败关闭与自然胜利轨迹。"""

from __future__ import annotations

from typing import Any, Callable, Mapping, Sequence

import pytest

from scripts.sgs_engine.actions import ActionContext, LegalAction
from scripts.sgs_engine.mode_identity import (
    FORMAL_NO_SKILL_IDENTITY_8P_MODE,
    FormalEightPlayerIdentityConfiguration,
)
from scripts.sgs_engine.mode_identity_heir import (
    C7_CANONICAL_DRAW_REACHABILITY_STATUS,
    FORMAL_NO_SKILL_IDENTITY_8P_HEIR_MODE,
    FormalHeirAndSpyChoiceIdentityConfiguration,
    FormalHeirAndSpyChoiceIdentitySession,
)
from scripts.sgs_engine.production_batch import (
    BatchActionIdController,
    ProductionPhase,
    ScriptedBatchController,
)
from scripts.sgs_engine.production_replay import (
    SUPPORTED_REPLAY_MODES,
    ProductionReexecutionReplay,
    ProductionReplayDivergenceError,
    ProductionReplayFormatError,
    record_reference_formal_eight_player_identity,
    record_reference_formal_heir_and_spy_choice_identity,
    reexecute_production_replay,
)

PHYSICAL = ("p1", "p2", "p3", "p4", "p5", "p6", "p7", "p8")
ROLE_CARDS = (
    "lord",
    "loyalist",
    "loyalist",
    "rebel",
    "rebel",
    "rebel",
    "rebel",
    "spy",
)
NATURAL_VICTORY_SEEDS = {
    "lord_and_loyalists": 16,
    "rebels": 7,
    "spy": 49,
}
_RECORD_CACHE: dict[int, ProductionReexecutionReplay] = {}


def _record(seed: int) -> ProductionReexecutionReplay:
    cached = _RECORD_CACHE.get(seed)
    if cached is not None:
        return cached
    record = record_reference_formal_heir_and_spy_choice_identity(
        seed,
        configuration=FormalHeirAndSpyChoiceIdentityConfiguration.formal_profile(),
        analysis_only=False,
        max_steps=8000,
    )
    _RECORD_CACHE[seed] = record
    return record


def _assert_c7_record(record: ProductionReexecutionReplay) -> None:
    assert record.header["mode_id"] == FORMAL_NO_SKILL_IDENTITY_8P_HEIR_MODE
    assert record.header["fixture_applied"] is False
    config = record.header["initial_configuration"]
    assert set(config) == {
        "formal_heir_and_spy_choice_identity_configuration",
        "physical_player_ids",
        "identities",
        "numbered_player_order",
        "lord_player_id",
        "analysis_only",
        "max_steps",
    }
    assert "formal_eight_player_identity_configuration" not in config
    assert "formal_identity_configuration" not in config
    formal_config = config["formal_heir_and_spy_choice_identity_configuration"]
    assert formal_config["schema"] == (
        "formal-no-skill-identity-8p-heir-and-spy-choice-configuration-v1"
    )
    assert formal_config["variant_id"] == "mobile_8p_heir_and_spy_choice"
    assert tuple(formal_config["physical_player_ids"]) == PHYSICAL
    assert tuple(formal_config["identity_cards"]) == ROLE_CARDS
    identities = dict(config["identities"])
    assert list(identities.values()).count("lord") == 1
    assert list(identities.values()).count("loyalist") == 2
    assert list(identities.values()).count("rebel") == 4
    assert list(identities.values()).count("spy") == 1
    assert record.random_consumptions[0]["method"] == "shuffle"
    assert record.random_consumptions[1]["method"] == "shuffle"
    assert record.header["initial_rng_call_count"] == 2
    assert record.outcome["finish_reason"] in {
        "identity_victory",
        "identity_draw_deck_exhausted",
    }


def test_c7_mode_is_first_class_supported_replay_input() -> None:
    assert FORMAL_NO_SKILL_IDENTITY_8P_HEIR_MODE in SUPPORTED_REPLAY_MODES
    assert FORMAL_NO_SKILL_IDENTITY_8P_HEIR_MODE != FORMAL_NO_SKILL_IDENTITY_8P_MODE


def test_c7_default_strict_replay_reexecutes() -> None:
    record = _record(0)
    _assert_c7_record(record)
    result = reexecute_production_replay(record)
    assert result.verified is True
    assert result.winner_id == record.outcome["winner_id"]
    assert result.decision_count == len(record.decisions)
    assert result.final_execution_hash == record.outcome["final_execution_hash"]


@pytest.mark.parametrize(
    ("token", "seed"),
    tuple(NATURAL_VICTORY_SEEDS.items()),
)
def test_c7_natural_identity_victories_strict_reexecute(
    token: str, seed: int
) -> None:
    record = _record(seed)
    _assert_c7_record(record)
    assert record.header["formal_result"] is True
    assert record.outcome["winner_id"] == token
    result = reexecute_production_replay(record)
    assert result.verified is True
    assert result.winner_id == token


def test_c7_heir_select_scripted_strict_replay() -> None:
    game = FormalHeirAndSpyChoiceIdentitySession(
        seed=0,
        configuration=FormalHeirAndSpyChoiceIdentityConfiguration.formal_profile(),
        analysis_only=False,
        session_id="c7-scripted-heir",
        session_secret=b"c7-scripted-heir-secret-00000001",
    )
    other = game.numbered_player_order[1]
    controller = ScriptedBatchController(
        (
            {"operation": "proceed_prepare"},
            {"operation": "proceed_judgment"},
            {"operation": "proceed_draw"},
            {"operation": "end_play_phase"},
            {"operation": "end_turn"},
            {"operation": "select_heir", "target": other},
        )
    )
    record = record_reference_formal_heir_and_spy_choice_identity(
        0,
        configuration=FormalHeirAndSpyChoiceIdentityConfiguration.formal_profile(),
        analysis_only=False,
        controller=controller,
        max_steps=8000,
    )
    assert record.header["formal_result"] is True
    assert any(
        decision["chosen_action"].get("payload", {}).get("operation")
        == "select_heir"
        for decision in record.decisions
    )
    result = reexecute_production_replay(record)
    assert result.verified is True


def test_c7_draw_reachability_remains_unresolved() -> None:
    assert C7_CANONICAL_DRAW_REACHABILITY_STATUS == (
        "C7_CANONICAL_DRAW_REACHABILITY_UNRESOLVED"
    )
    assert C7_CANONICAL_DRAW_REACHABILITY_STATUS not in {
        "N/A",
        "PROVEN_UNREACHABLE",
        "mathematically impossible",
    }


def _set_record_hash_blank(payload: dict[str, object]) -> None:
    payload["record_sha256"] = ""


def _mode_spoof_c6(payload: dict[str, object]) -> None:
    payload["header"]["mode_id"] = FORMAL_NO_SKILL_IDENTITY_8P_MODE


def _schema_spoof_c6(payload: dict[str, object]) -> None:
    config = payload["header"]["initial_configuration"]
    config["formal_heir_and_spy_choice_identity_configuration"]["schema"] = (
        "formal-no-skill-identity-8p-configuration-v1"
    )


def _c7_field_on_c6_schema(payload: dict[str, object]) -> None:
    config = payload["header"]["initial_configuration"]
    config["variant_id"] = "mobile_8p_heir_and_spy_choice"


def _physical_reorder(payload: dict[str, object]) -> None:
    config = payload["header"]["initial_configuration"]
    config["physical_player_ids"] = list(reversed(config["physical_player_ids"]))


def _analysis_int_alias(payload: dict[str, object]) -> None:
    payload["header"]["initial_configuration"]["analysis_only"] = 0


@pytest.mark.parametrize(
    "mutator",
    (
        _mode_spoof_c6,
        _schema_spoof_c6,
        _c7_field_on_c6_schema,
        _physical_reorder,
        _analysis_int_alias,
    ),
)
def test_c7_tamper_and_c6_cross_mode_fail_closed(
    mutator: Callable[[dict[str, object]], None],
) -> None:
    payload = _record(0).to_dict()
    mutator(payload)
    _set_record_hash_blank(payload)
    with pytest.raises(
        (ProductionReplayFormatError, ProductionReplayDivergenceError)
    ):
        reexecute_production_replay(ProductionReexecutionReplay.from_dict(payload))


def test_c6_replay_cannot_be_reexecuted_as_c7() -> None:
    payload = record_reference_formal_eight_player_identity(
        16,
        configuration=FormalEightPlayerIdentityConfiguration.formal_profile(),
        analysis_only=False,
        max_steps=8000,
    ).to_dict()
    payload["header"]["mode_id"] = FORMAL_NO_SKILL_IDENTITY_8P_HEIR_MODE
    _set_record_hash_blank(payload)
    with pytest.raises(
        (ProductionReplayFormatError, ProductionReplayDivergenceError)
    ):
        reexecute_production_replay(ProductionReexecutionReplay.from_dict(payload))


# ---------------------------------------------------------------------------
# C7-REM-002/003/004：canonical untouched opening 的权威 strict trajectories
# ---------------------------------------------------------------------------

C7_STRICT_CANONICAL_SEED = 1
C7_STRICT_ORIGINAL_LORD = "p6"
C7_STRICT_HEIR_TARGET = "p3"
C7_STRICT_SPY_ID = "p5"
C7_STRICT_SPY_PATH = "ambitionist"
C7_STRICT_MID_TARGETS = ("p1", "p2", "p4", "p7", "p8")
_STRICT_SESSION_SECRET = b"c7-canonical-strict-trajectory-secret-01"
_STRICT_RECORD_CACHE: dict[str, ProductionReexecutionReplay] = {}
_STRICT_TRACE_CACHE: dict[str, dict[str, Any]] = {}


def _action_operation(action: LegalAction) -> str:
    return str(action.payload.get("operation", ""))


def _action_target(action: LegalAction) -> str | None:
    if action.target_ids:
        return action.target_ids[0]
    raw = action.payload.get("target_id")
    return raw if type(raw) is str else None


def _first_legal(
    legal_actions: Sequence[LegalAction], predicate: Callable[[LegalAction], bool]
) -> LegalAction | None:
    for action in legal_actions:
        if predicate(action):
            return action
    return None


class _C7CanonicalStrictTrajectoryController:
    """固定 seed 的确定性合法策略：只从当前 legal_actions 选择。"""

    strategy_version = "c7-canonical-strict-trajectory-controller.v1"

    def __init__(
        self,
        *,
        original_lord_id: str,
        heir_target: str,
        protect_id: str,
        spy_path: str,
        mid_targets: tuple[str, ...],
    ) -> None:
        self.original_lord_id = original_lord_id
        self.heir_target = heir_target
        self.protect_id = protect_id
        self.spy_path = spy_path
        self.mid_targets = mid_targets
        self.heir_selected = False
        self.succession_seen = False
        self.spy_path_chosen = False

    def hunt_targets(self) -> tuple[str, ...]:
        if not self.heir_selected:
            return ()
        if not self.succession_seen:
            return (self.original_lord_id,)
        return self.mid_targets + (self.heir_target,)

    def choose(
        self, legal_actions: Sequence[LegalAction], context: ActionContext
    ) -> LegalAction:
        if not legal_actions:
            raise AssertionError("C7 strict controller 收到空的合法动作集合")
        if context.phase == ProductionPhase.SUCCESSION_CARD_CHOICE.value:
            self.succession_seen = True
        selected = self._select(legal_actions, context)
        if selected not in legal_actions:
            raise AssertionError("C7 strict controller 返回了非合法动作")
        operation = _action_operation(selected)
        if operation == "select_heir":
            self.heir_selected = True
        elif operation == "choose_spy_path":
            self.spy_path_chosen = True
        elif operation in {"succession_obtain_none", "succession_obtain_card"}:
            self.succession_seen = True
        return selected

    def _select(
        self, legal_actions: Sequence[LegalAction], context: ActionContext
    ) -> LegalAction:
        phase = context.phase
        actor = context.actor_id
        hunts = self.hunt_targets()
        if phase == ProductionPhase.MODE_DECISION.value:
            chosen = _first_legal(
                legal_actions,
                lambda action: (
                    _action_operation(action) == "select_heir"
                    and _action_target(action) == self.heir_target
                ),
            )
            if chosen is not None:
                return chosen
            chosen = _first_legal(
                legal_actions,
                lambda action: (
                    _action_operation(action) == "choose_spy_path"
                    and action.payload.get("path") == self.spy_path
                ),
            )
            if chosen is not None:
                return chosen
            chosen = _first_legal(
                legal_actions,
                lambda action: _action_operation(action) == "pass_mode_decision",
            )
            if chosen is not None:
                return chosen
        if phase == ProductionPhase.SUCCESSION_CARD_CHOICE.value:
            chosen = _first_legal(
                legal_actions,
                lambda action: _action_operation(action) == "succession_obtain_none",
            )
            if chosen is not None:
                return chosen
        if phase == ProductionPhase.DYING_RESCUE.value:
            dying = next(
                (
                    action.target_ids[0]
                    for action in legal_actions
                    if action.target_ids
                ),
                None,
            )
            if dying == self.protect_id:
                chosen = _first_legal(
                    legal_actions,
                    lambda action: _action_operation(action)
                    in {"rescue_with_peach", "rescue_with_wine"},
                )
                if chosen is not None:
                    return chosen
            chosen = _first_legal(
                legal_actions,
                lambda action: _action_operation(action) == "pass_rescue",
            )
            if chosen is not None:
                return chosen
        if phase == ProductionPhase.SLASH_RESPONSE.value:
            chosen = _first_legal(
                legal_actions,
                lambda action: _action_operation(action) == "pass_slash_response",
            )
            if chosen is not None:
                return chosen
        if phase == ProductionPhase.TRICK_RESPONSE.value:
            chosen = _first_legal(
                legal_actions,
                lambda action: _action_operation(action) == "pass_trick_response",
            )
            if chosen is not None:
                return chosen
        if phase == ProductionPhase.DUEL_RESPONSE.value:
            if actor == self.protect_id:
                chosen = _first_legal(
                    legal_actions,
                    lambda action: _action_operation(action) == "play_slash_for_duel",
                )
                if chosen is not None:
                    return chosen
            chosen = _first_legal(
                legal_actions,
                lambda action: _action_operation(action) == "pass_duel_slash",
            )
            if chosen is not None:
                return chosen
        if phase == ProductionPhase.NANMAN_RESPONSE.value:
            if actor == self.protect_id:
                chosen = _first_legal(
                    legal_actions,
                    lambda action: _action_operation(action)
                    == "play_slash_for_nanman",
                )
                if chosen is not None:
                    return chosen
            chosen = _first_legal(
                legal_actions,
                lambda action: _action_operation(action) == "pass_nanman_slash",
            )
            if chosen is not None:
                return chosen
        if phase == ProductionPhase.WANJIAN_RESPONSE.value:
            if actor == self.protect_id:
                chosen = _first_legal(
                    legal_actions,
                    lambda action: _action_operation(action)
                    == "play_jink_for_wanjian",
                )
                if chosen is not None:
                    return chosen
            chosen = _first_legal(
                legal_actions,
                lambda action: _action_operation(action) == "pass_wanjian_jink",
            )
            if chosen is not None:
                return chosen
        if phase == ProductionPhase.IDENTITY_REWARD_CHOICE.value:
            chosen = _first_legal(
                legal_actions,
                lambda action: _action_operation(action)
                == "ambitionist_reward_decline",
            )
            if chosen is not None:
                return chosen
        if phase == ProductionPhase.JUDGMENT_WUXIE.value:
            chosen = _first_legal(
                legal_actions,
                lambda action: _action_operation(action) == "pass_judgment_wuxie",
            )
            if chosen is not None:
                return chosen
        if phase == ProductionPhase.FEIYANG_ACTIVATE.value:
            chosen = _first_legal(
                legal_actions,
                lambda action: _action_operation(action) == "feiyang_decline",
            )
            if chosen is not None:
                return chosen
        if phase in {
            ProductionPhase.PREPARE.value,
            ProductionPhase.JUDGMENT.value,
            ProductionPhase.DRAW.value,
            ProductionPhase.END.value,
        }:
            return legal_actions[0]
        if phase == ProductionPhase.PLAY.value:
            return self._choose_play(legal_actions, actor, hunts)
        if phase in {
            ProductionPhase.WEAPON_SLASH_CHOICE.value,
            ProductionPhase.WEAPON_AFTER_DAMAGE.value,
            ProductionPhase.BORROWED_SWORD_CHOICE.value,
        }:
            for hunt in hunts:
                chosen = _first_legal(
                    legal_actions,
                    lambda action, target=hunt: _action_target(action) == target
                    and _action_operation(action)
                    in {
                        "qinglong_use_slash",
                        "weapon_force_hit",
                        "choose_borrowed_sword_slash",
                    },
                )
                if chosen is not None:
                    return chosen
            chosen = _first_legal(
                legal_actions,
                lambda action: _action_operation(action)
                in {"pass_weapon_choice", "refuse_borrowed_sword_slash"},
            )
            if chosen is not None:
                return chosen
        if phase == ProductionPhase.DISCARD.value:
            chosen = _first_legal(
                legal_actions,
                lambda action: _action_operation(action) == "discard_phase_submit",
            )
            if chosen is not None:
                return chosen
            chosen = _first_legal(
                legal_actions,
                lambda action: _action_operation(action) == "select_discard_card",
            )
            if chosen is not None:
                return chosen
        if phase == ProductionPhase.CIXIONG_ACTIVATE.value:
            chosen = _first_legal(
                legal_actions,
                lambda action: _action_operation(action) == "pass_cixiong",
            )
            if chosen is not None:
                return chosen
        if phase == ProductionPhase.FIRE_ATTACK_DISCARD.value:
            if actor == self.protect_id:
                chosen = _first_legal(
                    legal_actions,
                    lambda action: _action_operation(action)
                    == "discard_same_suit_for_fire_attack",
                )
                if chosen is not None:
                    return chosen
            chosen = _first_legal(
                legal_actions,
                lambda action: _action_operation(action)
                == "pass_fire_attack_discard",
            )
            if chosen is not None:
                return chosen
        return legal_actions[0]

    def _choose_play(
        self,
        legal_actions: Sequence[LegalAction],
        actor: str,
        hunts: tuple[str, ...],
    ) -> LegalAction:
        if actor == self.protect_id:
            chosen = _first_legal(
                legal_actions,
                lambda action: _action_operation(action)
                == "ambitionist_mark_draw_two",
            )
            if chosen is not None:
                return chosen
            chosen = _first_legal(
                legal_actions,
                lambda action: _action_operation(action) == "heal_self"
                and action.payload.get("virtual") is True,
            )
            if chosen is not None:
                return chosen
            chosen = _first_legal(
                legal_actions,
                lambda action: _action_operation(action) == "heal_self",
            )
            if chosen is not None:
                return chosen
        hunt_slash = None
        hunt_duel = None
        hunt_fire = None
        for hunt in hunts:
            if hunt_slash is None:
                hunt_slash = _first_legal(
                    legal_actions,
                    lambda action, target=hunt: _action_operation(action)
                    == "use_slash"
                    and _action_target(action) == target
                    and action.payload.get("zhangba_virtual") is not True
                    and not str(action.card_instance_id or "").startswith(
                        "virtual:zhangba"
                    ),
                )
            if hunt_duel is None:
                hunt_duel = _first_legal(
                    legal_actions,
                    lambda action, target=hunt: _action_operation(action)
                    == "use_duel"
                    and _action_target(action) == target,
                )
            if hunt_fire is None:
                hunt_fire = _first_legal(
                    legal_actions,
                    lambda action, target=hunt: _action_operation(action)
                    == "use_fire_attack"
                    and _action_target(action) == target,
                )
        if hunt_slash is not None:
            wine = _first_legal(
                legal_actions,
                lambda action: _action_operation(action) == "use_wine_buff",
            )
            if wine is not None:
                return wine
            return hunt_slash
        if hunt_duel is not None:
            return hunt_duel
        if hunt_fire is not None:
            return hunt_fire
        chosen = _first_legal(
            legal_actions, lambda action: _action_operation(action) == "use_weapon"
        )
        if chosen is not None:
            return chosen
        chosen = _first_legal(
            legal_actions, lambda action: _action_operation(action) == "use_wuzhong"
        )
        if chosen is not None:
            return chosen
        chosen = _first_legal(
            legal_actions,
            lambda action: _action_operation(action) == "end_play_phase",
        )
        if chosen is not None:
            return chosen
        return legal_actions[0]


def _c7_strict_controller() -> _C7CanonicalStrictTrajectoryController:
    return _C7CanonicalStrictTrajectoryController(
        original_lord_id=C7_STRICT_ORIGINAL_LORD,
        heir_target=C7_STRICT_HEIR_TARGET,
        protect_id=C7_STRICT_SPY_ID,
        spy_path=C7_STRICT_SPY_PATH,
        mid_targets=C7_STRICT_MID_TARGETS,
    )


def _event_payload(event: Mapping[str, Any] | Any) -> Mapping[str, Any]:
    if isinstance(event, Mapping):
        payload = event.get("payload")
        if isinstance(payload, Mapping):
            return payload
        return {}
    payload = getattr(event, "payload", {})
    if isinstance(payload, Mapping):
        return payload
    return {}


def _c7_strict_walk_trace() -> dict[str, Any]:
    cached = _STRICT_TRACE_CACHE.get("canonical")
    if cached is not None:
        return cached
    controller = _c7_strict_controller()
    game = FormalHeirAndSpyChoiceIdentitySession(
        seed=C7_STRICT_CANONICAL_SEED,
        configuration=FormalHeirAndSpyChoiceIdentityConfiguration.formal_profile(),
        analysis_only=False,
        session_id="c7-canonical-strict-walk",
        session_secret=_STRICT_SESSION_SECRET,
    )
    numbered_before = game.numbered_player_order
    heir_seat_before = game.seat_by_player[C7_STRICT_HEIR_TARGET]
    heir_max_before = game.state.players_by_id[C7_STRICT_HEIR_TARGET].max_hp
    heir_hp_before = game.state.players_by_id[C7_STRICT_HEIR_TARGET].hp
    trace: dict[str, Any] = {
        "select_heir_phase": None,
        "selected_heir": None,
        "old_lord_dying": False,
        "old_lord_rescue_passed": 0,
        "succession_window": False,
        "succession_event": False,
        "extra_turn_after_succession": None,
        "new_lord": None,
        "seat_before": heir_seat_before,
        "seat_after": None,
        "max_hp_before": heir_max_before,
        "max_hp_after": None,
        "hp_before": heir_hp_before,
        "hp_after": None,
        "old_lord_dead": False,
        "numbered_unchanged": None,
        "spy_choice_phase": None,
        "spy_choice_payload": None,
        "chooser": None,
        "pending_role": None,
        "pending_locked": None,
        "alive_at_choice": None,
        "converted_role": None,
        "application_turn": None,
        "application_player": None,
        "application_phase": None,
        "conversion_after_turn_start": False,
        "steps": 0,
    }
    last_operation = None
    waiting_conversion = False
    while not game.is_finished:
        legal = game.legal_actions()
        context = game._context()
        if context.phase == ProductionPhase.SUCCESSION_CARD_CHOICE.value:
            trace["succession_window"] = True
        dying_id = (
            game._runtime.pending_dying_id
            if game.phase is ProductionPhase.DYING_RESCUE
            else None
        )
        if dying_id == C7_STRICT_ORIGINAL_LORD:
            trace["old_lord_dying"] = True
        chosen = controller.choose(legal, context)
        assert chosen in legal
        operation = _action_operation(chosen)
        game.step(BatchActionIdController(chosen.action_id))
        trace["steps"] += 1
        last_operation = operation
        if operation == "select_heir":
            trace["select_heir_phase"] = context.phase
            trace["selected_heir"] = chosen.payload.get("target_id") or _action_target(
                chosen
            )
            assert context.phase == ProductionPhase.MODE_DECISION.value
        if operation == "pass_rescue" and dying_id == C7_STRICT_ORIGINAL_LORD:
            trace["old_lord_rescue_passed"] += 1
        if operation == "choose_spy_path":
            trace["spy_choice_phase"] = context.phase
            trace["spy_choice_payload"] = dict(chosen.payload)
            trace["chooser"] = chosen.actor_id
            trace["pending_role"] = game.role_current[C7_STRICT_SPY_ID]
            trace["pending_locked"] = (
                game._variant.spy_path_pending and game._variant.spy_path_locked
            )
            trace["alive_at_choice"] = sum(
                1 for player in game.state.players if player.alive
            )
            assert context.phase == ProductionPhase.MODE_DECISION.value
            waiting_conversion = True
        if trace["succession_window"] and trace["new_lord"] is None:
            if game.current_lord_player_id == C7_STRICT_HEIR_TARGET:
                successor = game.state.players_by_id[C7_STRICT_HEIR_TARGET]
                trace["new_lord"] = C7_STRICT_HEIR_TARGET
                trace["seat_after"] = game.seat_by_player[C7_STRICT_HEIR_TARGET]
                trace["max_hp_after"] = successor.max_hp
                trace["hp_after"] = successor.hp
                trace["old_lord_dead"] = not game.state.players_by_id[
                    C7_STRICT_ORIGINAL_LORD
                ].alive
                trace["extra_turn_after_succession"] = game._variant.is_extra_turn
                trace["numbered_unchanged"] = (
                    game.numbered_player_order == numbered_before
                )
                trace["succession_event"] = any(
                    event.event_type.value == "identity_revealed"
                    and _event_payload(event).get("reason") == "succession_lord_reveal"
                    for event in game.events
                )
        if waiting_conversion and game.role_current[C7_STRICT_SPY_ID] != "spy":
            trace["converted_role"] = game.role_current[C7_STRICT_SPY_ID]
            trace["application_turn"] = game._runtime.turn_number
            trace["application_player"] = game.current_player_id
            trace["application_phase"] = game.phase.value
            trace["conversion_after_turn_start"] = last_operation in {
                "end_turn",
                "pass_mode_decision",
                "proceed_prepare",
            } or game.phase in {
                ProductionPhase.PREPARE,
                ProductionPhase.MODE_DECISION,
            }
            waiting_conversion = False
    trace["winner"] = game.winner_id
    trace["finish_reason"] = game._runtime.game_over_reason or (
        game.outcome_policy.finish_reason if game.outcome_policy is not None else None
    )
    trace["formal_result_eligible"] = game.formal_result_eligible
    trace["analysis_only"] = game.analysis_only
    trace["current_lord"] = game.current_lord_player_id
    _STRICT_TRACE_CACHE["canonical"] = trace
    return trace


def _c7_strict_record() -> ProductionReexecutionReplay:
    cached = _STRICT_RECORD_CACHE.get("canonical")
    if cached is not None:
        return cached
    record = record_reference_formal_heir_and_spy_choice_identity(
        C7_STRICT_CANONICAL_SEED,
        configuration=FormalHeirAndSpyChoiceIdentityConfiguration.formal_profile(),
        analysis_only=False,
        controller=_c7_strict_controller(),
        max_steps=8000,
    )
    _STRICT_RECORD_CACHE["canonical"] = record
    return record


def _decision_operation(decision: Mapping[str, Any]) -> str:
    chosen = decision.get("chosen_action")
    if not isinstance(chosen, Mapping):
        return ""
    payload = chosen.get("payload")
    if not isinstance(payload, Mapping):
        return ""
    return str(payload.get("operation", ""))


def test_c7_canonical_strict_successful_succession_replay() -> None:
    trace = _c7_strict_walk_trace()
    assert trace["select_heir_phase"] == ProductionPhase.MODE_DECISION.value
    assert trace["selected_heir"] == C7_STRICT_HEIR_TARGET
    assert trace["old_lord_dying"] is True
    assert trace["old_lord_rescue_passed"] >= 1
    assert trace["succession_window"] is True
    assert trace["succession_event"] is True
    assert trace["new_lord"] == C7_STRICT_HEIR_TARGET
    assert trace["seat_before"] == trace["seat_after"]
    assert trace["max_hp_after"] == trace["max_hp_before"] + 1
    assert trace["hp_after"] == trace["hp_before"] + 1
    assert trace["old_lord_dead"] is True
    assert trace["numbered_unchanged"] is True
    assert trace["extra_turn_after_succession"] is False
    assert trace["current_lord"] == C7_STRICT_HEIR_TARGET or trace["new_lord"] == (
        C7_STRICT_HEIR_TARGET
    )
    record = _c7_strict_record()
    _assert_c7_record(record)
    assert record.header["fixture_applied"] is False
    assert record.header["formal_result"] is True
    assert record.header["initial_configuration"]["analysis_only"] is False
    assert record.outcome["decision_count"] == trace["steps"]
    operations = [_decision_operation(decision) for decision in record.decisions]
    assert "select_heir" in operations
    assert "succession_obtain_none" in operations
    heir_decision = next(
        decision
        for decision in record.decisions
        if _decision_operation(decision) == "select_heir"
    )
    assert heir_decision["context"]["phase"] == ProductionPhase.MODE_DECISION.value
    assert any(
        event.get("event_type") == "identity_revealed"
        and _event_payload(event).get("reason") == "succession_lord_reveal"
        for event in record.events
    )
    assert any(
        event.get("event_type") == "hp_recover"
        and _event_payload(event).get("reason") == "succession_recover"
        for event in record.events
    )
    assert any(
        event.get("event_type") == "death"
        and C7_STRICT_ORIGINAL_LORD in event.get("target_ids", ())
        for event in record.events
    )
    result = reexecute_production_replay(record)
    assert result.verified is True


def test_c7_canonical_strict_spy_path_conversion_replay() -> None:
    trace = _c7_strict_walk_trace()
    assert trace["old_lord_dead"] is True
    assert trace["alive_at_choice"] is not None and trace["alive_at_choice"] > 4
    assert trace["spy_choice_phase"] == ProductionPhase.MODE_DECISION.value
    assert trace["chooser"] == C7_STRICT_SPY_ID
    payload = trace["spy_choice_payload"]
    assert isinstance(payload, dict)
    assert payload.get("operation") == "choose_spy_path"
    assert payload.get("path") == C7_STRICT_SPY_PATH
    assert "target_id" not in payload
    assert payload.get("apply_at") is None
    assert trace["pending_role"] == "spy"
    assert trace["pending_locked"] is True
    assert trace["converted_role"] == "ambitionist"
    assert trace["application_player"] != trace["chooser"]
    assert trace["conversion_after_turn_start"] is True
    record = _c7_strict_record()
    _assert_c7_record(record)
    operations = [_decision_operation(decision) for decision in record.decisions]
    assert "choose_spy_path" in operations
    choice = next(
        decision
        for decision in record.decisions
        if _decision_operation(decision) == "choose_spy_path"
    )
    assert choice["context"]["phase"] == ProductionPhase.MODE_DECISION.value
    assert choice["context"]["actor_id"] == C7_STRICT_SPY_ID
    choice_payload = choice["chosen_action"]["payload"]
    assert choice_payload.get("path") == C7_STRICT_SPY_PATH
    assert "target_id" not in choice_payload
    assert any(
        event.get("event_type") == "identity_revealed"
        and _event_payload(event).get("reason") == "ambitionist_conversion"
        for event in record.events
    )
    public = record.player_visible_payload(None, valid_player_ids=PHYSICAL)
    public_blob = repr(public)
    assert "heir_player_id" not in public_blob
    assert "spy_path_pending" not in public_blob
    assert "spy_path_choice" not in public_blob
    result = reexecute_production_replay(record)
    assert result.verified is True


def test_c7_canonical_strict_ambitionist_victory_replay() -> None:
    trace = _c7_strict_walk_trace()
    assert trace["analysis_only"] is False
    assert trace["formal_result_eligible"] is True
    assert trace["converted_role"] == "ambitionist"
    assert trace["winner"] == "ambitionist"
    assert trace["finish_reason"] == "identity_victory"
    record = _c7_strict_record()
    _assert_c7_record(record)
    assert record.header["fixture_applied"] is False
    assert record.header["formal_result"] is True
    assert record.header["initial_configuration"]["analysis_only"] is False
    assert record.outcome["winner_id"] == "ambitionist"
    assert record.outcome["finish_reason"] == "identity_victory"
    assert record.outcome["decision_count"] == trace["steps"]
    result = reexecute_production_replay(record)
    assert result.verified is True
    assert result.winner_id == "ambitionist"
    assert result.decision_count == record.outcome["decision_count"]
