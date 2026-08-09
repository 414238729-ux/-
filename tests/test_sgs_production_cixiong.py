# -*- coding: utf-8 -*-
"""雌雄双股剑生产状态机的独立验收测试。"""

from __future__ import annotations

from dataclasses import replace
import json

import pytest

from scripts.sgs_engine.actions import (
    ActionType,
    InvalidActionError,
    LegalAction,
    UnsupportedRuleError,
    validate_action,
)
from scripts.sgs_engine.events import EventType
from scripts.sgs_engine.model import (
    DISCARD_PILE,
    CharacterGender,
    CharacterMetadata,
    ZoneRef,
)
from scripts.sgs_engine.production_batch import (
    BatchActionIdController,
    ProductionBasicCardBatch,
    ProductionPhase,
    ScriptedBatchController,
    _replace_player,
)
from scripts.sgs_engine.production_cards import (
    WEAPON_SKILL_STATUS,
    check_weapon_skill_gate,
)
from scripts.sgs_engine.production_replay import (
    record_reference_production_batch,
    reexecute_production_replay,
)


CIXIONG = "sgs_weapon_cixiongshuanggujian"
SHA = "sgs_basic_sha"
RENWANG = "sgs_armor_renwangdun"
BAGUA = "sgs_armor_baguazhen"
BAIYIN = "sgs_armor_baiyinshizi"
JIEDAO = "sgs_trick_jiedaosharen"


def _fresh(*, seed: int = 17) -> ProductionBasicCardBatch:
    game = ProductionBasicCardBatch(
        seed=seed, initial_hand_count=1, shuffle=False
    )
    for operation in ("proceed_prepare", "proceed_judgment", "proceed_draw"):
        _step(game, _action(game, operation))
    assert game.phase is ProductionPhase.PLAY
    return game


def _step(game: ProductionBasicCardBatch, action: LegalAction) -> None:
    assert action.action_id is not None
    game.step(BatchActionIdController(action.action_id))


def _action(
    game: ProductionBasicCardBatch,
    operation: str,
    *,
    card_instance_id: str | None = None,
) -> LegalAction:
    for action in game.legal_actions():
        if action.payload.get("operation") != operation:
            continue
        if (
            card_instance_id is not None
            and action.card_instance_id != card_instance_id
        ):
            continue
        return action
    raise AssertionError(f"当前阶段缺少动作{operation!r}")


def _record_id(
    game: ProductionBasicCardBatch,
    card_key: str,
    *,
    color: str | None = None,
    excluded: tuple[str, ...] = (),
) -> str:
    return next(
        record.instance_id
        for record in game.formal_registry.records
        if record.card_key == card_key
        and record.instance_id not in excluded
        and (
            color is None
            or game.state.cards_by_id[record.instance_id].color == color
        )
    )


def _move_key(
    game: ProductionBasicCardBatch,
    card_key: str,
    destination: ZoneRef,
    *,
    color: str | None = None,
    excluded: tuple[str, ...] = (),
) -> str:
    instance_id = _record_id(
        game, card_key, color=color, excluded=excluded
    )
    if game.state.location_of(instance_id) != destination:
        game._state = game.state.move_card(instance_id, destination)
    return instance_id


def _equip(
    game: ProductionBasicCardBatch,
    player_id: str,
    card_key: str,
    slot: str,
) -> str:
    zone = ZoneRef.equipment(player_id, slot)
    for existing in tuple(game.state.card_ids_in(zone)):
        game._state = game.state.move_card(existing, DISCARD_PILE)
    return _move_key(game, card_key, zone)


def _set_character(
    game: ProductionBasicCardBatch,
    player_id: str,
    gender: CharacterGender | None,
) -> None:
    game._state = replace(
        game.state,
        players=tuple(
            replace(
                player,
                character=CharacterMetadata(f"test_{player_id}", gender),
            )
            if player.player_id == player_id
            else player
            for player in game.state.players
        ),
        revision=game.state.revision + 1,
    )


def _set_opposite_genders(
    game: ProductionBasicCardBatch, attacker: str, target: str
) -> None:
    _set_character(game, attacker, CharacterGender.MALE)
    _set_character(game, target, CharacterGender.FEMALE)


def _clear_hand(game: ProductionBasicCardBatch, player_id: str) -> None:
    for instance_id in tuple(game.state.card_ids_in(ZoneRef.hand(player_id))):
        game._state = game.state.move_card(instance_id, DISCARD_PILE)


def _clear_equipment(game: ProductionBasicCardBatch, player_id: str) -> None:
    for slot in ("weapon", "armor", "attack_horse", "defense_horse", "treasure"):
        for instance_id in tuple(
            game.state.card_ids_in(ZoneRef.equipment(player_id, slot))
        ):
            game._state = game.state.move_card(instance_id, DISCARD_PILE)


def _prepare_cixiong_slash(
    game: ProductionBasicCardBatch,
    *,
    slash_color: str | None = None,
) -> tuple[str, str, str]:
    attacker = game.current_actor_id
    target = game.opponent_of(attacker)
    _set_opposite_genders(game, attacker, target)
    _equip(game, attacker, CIXIONG, "weapon")
    slash_id = _move_key(
        game, SHA, ZoneRef.hand(attacker), color=slash_color
    )
    return attacker, target, slash_id


def _use_slash(
    game: ProductionBasicCardBatch, slash_id: str
) -> LegalAction:
    action = _action(game, "use_slash", card_instance_id=slash_id)
    _step(game, action)
    return action


def test_cixiong_status_and_gender_metadata_fail_closed_without_seat_guess() -> None:
    assert WEAPON_SKILL_STATUS[CIXIONG] == "COMPLETE"
    game = _fresh()
    attacker = game.current_actor_id
    target = game.opponent_of(attacker)
    _equip(game, attacker, CIXIONG, "weapon")
    _move_key(game, SHA, ZoneRef.hand(attacker))

    with pytest.raises(
        UnsupportedRuleError,
        match="CHARACTER_GENDER_METADATA_NOT_AVAILABLE",
    ):
        game.legal_actions()

    _set_character(game, attacker, CharacterGender.MALE)
    _set_character(game, target, None)
    with pytest.raises(
        UnsupportedRuleError,
        match="CHARACTER_GENDER_METADATA_NOT_AVAILABLE",
    ):
        check_weapon_skill_gate(
            game.state,
            actor_id=attacker,
            decision="use_slash",
            target_id=target,
        )


def test_same_gender_slash_does_not_open_cixiong_window() -> None:
    game = _fresh()
    attacker = game.current_actor_id
    target = game.opponent_of(attacker)
    _set_character(game, attacker, CharacterGender.MALE)
    _set_character(game, target, CharacterGender.MALE)
    _equip(game, attacker, CIXIONG, "weapon")
    slash_id = _move_key(game, SHA, ZoneRef.hand(attacker))

    _use_slash(game, slash_id)

    assert game.phase is ProductionPhase.SLASH_RESPONSE
    assert game.runtime.pending_cixiong_choice is None


def test_attacker_can_pass_and_same_pending_slash_enters_response() -> None:
    game = _fresh()
    _, _, slash_id = _prepare_cixiong_slash(game)
    _use_slash(game, slash_id)
    pending = game.runtime.pending_slash

    assert game.phase is ProductionPhase.CIXIONG_ACTIVATE
    assert {
        action.payload.get("operation") for action in game.legal_actions()
    } == {"activate_cixiong", "pass_cixiong"}
    _step(game, _action(game, "pass_cixiong"))

    assert game.phase is ProductionPhase.SLASH_RESPONSE
    assert game.runtime.pending_slash is pending
    assert game.runtime.pending_cixiong_choice is None


@pytest.mark.parametrize("invalidate", ("weapon_removed", "target_dead"))
def test_cixiong_window_fails_closed_when_trigger_source_becomes_invalid(
    invalidate: str,
) -> None:
    game = _fresh()
    attacker, target, slash_id = _prepare_cixiong_slash(game)
    _use_slash(game, slash_id)
    stale_action = _action(game, "activate_cixiong")
    choice = game.runtime.pending_cixiong_choice
    assert choice is not None

    if invalidate == "weapon_removed":
        game._state = game.state.move_card(
            choice.weapon_instance_id, DISCARD_PILE
        )
    else:
        game._state = _replace_player(
            game.state, target, hp=0, alive=False
        )

    assert game.legal_actions() == ()
    with pytest.raises(InvalidActionError):
        validate_action(
            game.state, game._context(), stale_action, game.registry
        )
    assert game.runtime.pending_slash is not None
    assert game.runtime.pending_slash.attacker_id == attacker
    assert game.runtime.pending_slash.slash_instance_id == slash_id


def test_activate_with_zero_discardable_cards_only_allows_draw() -> None:
    game = _fresh()
    attacker, target, slash_id = _prepare_cixiong_slash(game)
    _clear_hand(game, target)
    _clear_equipment(game, target)
    attacker_hand_before = len(game.state.card_ids_in(ZoneRef.hand(attacker)))
    _use_slash(game, slash_id)
    pending = game.runtime.pending_slash
    source_sequence = game.runtime.response_window_source_sequence
    _step(game, _action(game, "activate_cixiong"))

    actions = game.legal_actions()
    assert [action.payload.get("operation") for action in actions] == [
        "cixiong_allow_draw"
    ]
    _step(game, actions[0])

    assert len(game.state.card_ids_in(ZoneRef.hand(attacker))) == (
        attacker_hand_before
    )
    # 使用杀先令攻击者手牌-1，雌雄选择再令其摸1，最终回到使用前数量。
    assert game.phase is ProductionPhase.SLASH_RESPONSE
    assert game.runtime.pending_slash is pending
    assert game.runtime.response_window_source_sequence == source_sequence
    assert any(
        event.event_type is EventType.CARD_GAINED
        and event.target_ids == (attacker,)
        and event.payload.get("reason") == "cixiong_target_allow_draw"
        for event in game.events
    )


def test_hidden_hand_discard_uses_handle_and_rejects_forged_or_stale_action() -> None:
    game = _fresh()
    _, target, slash_id = _prepare_cixiong_slash(game)
    _clear_hand(game, target)
    hidden_id = _move_key(game, "sgs_basic_tao", ZoneRef.hand(target))
    _use_slash(game, slash_id)
    _step(game, _action(game, "activate_cixiong"))
    discard = _action(game, "cixiong_discard_card")

    assert discard.card_instance_id is None
    assert discard.payload.get("zone") == "hand"
    assert isinstance(discard.payload.get("handle"), str)
    assert hidden_id not in json.dumps(
        {
            "action_type": discard.action_type.value,
            "actor_id": discard.actor_id,
            "card_instance_id": discard.card_instance_id,
            "target_ids": discard.target_ids,
            "payload": dict(discard.payload),
            "action_id": discard.action_id,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    forged = replace(discard, card_instance_id=hidden_id)
    with pytest.raises(InvalidActionError):
        validate_action(game.state, game._context(), forged, game.registry)

    _step(game, discard)
    assert game.state.location_of(hidden_id) == DISCARD_PILE
    with pytest.raises(InvalidActionError):
        validate_action(game.state, game._context(), discard, game.registry)


def test_armor_is_evaluated_after_target_choice_using_latest_state() -> None:
    # 黑杀指定仁王盾目标时，雌雄窗口必须先打开；目标弃掉仁王盾后才进入闪响应。
    game = _fresh()
    _, target, slash_id = _prepare_cixiong_slash(
        game, slash_color="黑"
    )
    armor_id = _equip(game, target, RENWANG, "armor")
    _use_slash(game, slash_id)
    assert game.phase is ProductionPhase.CIXIONG_ACTIVATE
    _step(game, _action(game, "activate_cixiong"))
    discard_armor = _action(
        game, "cixiong_discard_card", card_instance_id=armor_id
    )
    _step(game, discard_armor)

    assert game.state.location_of(armor_id) == DISCARD_PILE
    assert game.phase is ProductionPhase.SLASH_RESPONSE
    assert any(
        event.event_type is EventType.CARD_MOVED
        and event.card_instance_id == armor_id
        and event.payload.get("reason") == "cixiong_target_discard"
        and event.payload.get("source", {}).get("equipment_slot") == "armor"
        for event in game.events
    )

    # 若目标令攻击者摸牌而保留仁王盾，窗口结束后黑杀应立即被既有防具核心取消。
    game2 = _fresh(seed=19)
    _, target2, slash2 = _prepare_cixiong_slash(
        game2, slash_color="黑"
    )
    armor2 = _equip(game2, target2, RENWANG, "armor")
    _use_slash(game2, slash2)
    _step(game2, _action(game2, "activate_cixiong"))
    _step(game2, _action(game2, "cixiong_allow_draw"))
    assert game2.phase is ProductionPhase.PLAY
    assert game2.state.location_of(armor2) == ZoneRef.equipment(
        target2, "armor"
    )
    assert any(
        event.event_type is EventType.CARD_EFFECT_CANCELLED
        and event.card_instance_id == slash2
        and event.payload.get("after_cixiong_choice") is True
        for event in game2.events
    )


def test_bagua_response_starts_only_after_cixiong_target_choice() -> None:
    game = _fresh()
    _, target, slash_id = _prepare_cixiong_slash(game)
    _equip(game, target, BAGUA, "armor")
    _use_slash(game, slash_id)
    assert "activate_bagua" not in {
        action.payload.get("operation") for action in game.legal_actions()
    }
    _step(game, _action(game, "activate_cixiong"))
    assert "activate_bagua" not in {
        action.payload.get("operation") for action in game.legal_actions()
    }
    _step(game, _action(game, "cixiong_allow_draw"))

    assert game.phase is ProductionPhase.SLASH_RESPONSE
    assert "activate_bagua" in {
        action.payload.get("operation") for action in game.legal_actions()
    }


def test_discarding_baiyin_uses_equipment_leave_recovery_before_slash() -> None:
    game = _fresh()
    _, target, slash_id = _prepare_cixiong_slash(game)
    game._state = _replace_player(game.state, target, hp=2)
    armor_id = _equip(game, target, BAIYIN, "armor")
    _use_slash(game, slash_id)
    _step(game, _action(game, "activate_cixiong"))
    _step(
        game,
        _action(game, "cixiong_discard_card", card_instance_id=armor_id),
    )

    assert game.state.players_by_id[target].hp == 3
    assert game.phase is ProductionPhase.SLASH_RESPONSE
    assert any(
        event.event_type is EventType.ARMOR_RECOVERED
        and event.card_instance_id == armor_id
        and event.payload.get("reason") == "cixiong_target_discard"
        for event in game.events
    )


def test_borrowed_sword_forced_slash_uses_same_cixiong_path_and_root_exit() -> None:
    game = _fresh(seed=23)
    user = game.current_actor_id
    forced_attacker = game.opponent_of(user)
    _set_opposite_genders(game, forced_attacker, user)
    _equip(game, forced_attacker, CIXIONG, "weapon")
    jiedao_id = _move_key(game, JIEDAO, ZoneRef.hand(user))
    slash_id = _move_key(game, SHA, ZoneRef.hand(forced_attacker))

    _step(game, _action(game, "use_jiedao", card_instance_id=jiedao_id))
    assert game.phase is ProductionPhase.TRICK_RESPONSE
    _step(game, _action(game, "pass_trick_response"))
    _step(game, _action(game, "pass_trick_response"))
    assert game.phase is ProductionPhase.BORROWED_SWORD_CHOICE
    handle = next(
        handle
        for handle, instance_id in game.runtime.borrowed_sword_slash_handles.items()
        if instance_id == slash_id
    )
    forced_action = next(
        action
        for action in game.legal_actions()
        if action.payload.get("operation") == "choose_borrowed_sword_slash"
        and action.payload.get("handle") == handle
    )
    _step(game, forced_action)

    assert game.phase is ProductionPhase.CIXIONG_ACTIVATE
    assert game.current_actor_id == forced_attacker
    assert game.runtime.pending_borrowed_sword is not None
    assert game.runtime.pending_borrowed_sword.stage == "slash_resolving"
    root = game.runtime.pending_borrowed_sword
    pending = game.runtime.pending_slash
    _step(game, _action(game, "activate_cixiong"))
    assert game.current_actor_id == user
    _step(game, _action(game, "cixiong_allow_draw"))
    assert game.phase is ProductionPhase.SLASH_RESPONSE
    assert game.runtime.pending_borrowed_sword is root
    assert game.runtime.pending_slash is pending
    _step(game, _action(game, "pass_slash_response"))

    assert game.phase is ProductionPhase.PLAY
    assert game.runtime.pending_borrowed_sword is None
    assert game.runtime.pending_slash is None
    assert game.state.location_of(jiedao_id) == DISCARD_PILE
    assert game.state.location_of(slash_id) == DISCARD_PILE


def _cixiong_replay_fixture(game: ProductionBasicCardBatch) -> None:
    attacker = game.current_actor_id
    target = game.opponent_of(attacker)
    _set_opposite_genders(game, attacker, target)
    _equip(game, attacker, CIXIONG, "weapon")
    _move_key(game, SHA, ZoneRef.hand(attacker))
    _clear_hand(game, target)
    _move_key(game, "sgs_basic_tao", ZoneRef.hand(target))


def test_cixiong_runtime_replay_and_player_visible_privacy_are_bound() -> None:
    controller = ScriptedBatchController(
        (
            {"operation": "use_slash", "card_key": SHA},
            {"operation": "activate_cixiong"},
            {"operation": "cixiong_discard_card"},
            {"operation": "pass_slash_response"},
        )
    )
    record = record_reference_production_batch(
        seed=29,
        initial_hand_count=1,
        shuffle=False,
        controller=controller,
        fixture=_cixiong_replay_fixture,
        max_steps=500,
    )
    record_value = record.to_dict()
    target_decision = next(
        decision
        for decision in record_value["decisions"]
        if decision["context"]["phase"]
        == ProductionPhase.CIXIONG_TARGET_CHOICE.value
    )
    assert target_decision["context"]["metadata"][
        "pending_cixiong_choice"
    ]["stage"] == "awaiting_target_choice"
    discarded_id = next(
        event["card_instance_id"]
        for event in record_value["events"]
        if event["event_type"] == EventType.CARD_DISCARDED.value
        and event["payload"].get("reason") == "cixiong_target_discard"
    )
    decision_text = json.dumps(
        target_decision, ensure_ascii=False, sort_keys=True
    )
    assert discarded_id not in decision_text

    result = reexecute_production_replay(
        record, fixture=_cixiong_replay_fixture
    )
    assert result.verified is True

    target_id = target_decision["context"]["actor_id"]
    attacker_id = "p1" if target_id == "p2" else "p2"
    target_visible = record.player_visible_payload(target_id)
    visible_target_decision = next(
        decision
        for decision in target_visible["decisions"]
        if decision["context"]["phase"]
        == ProductionPhase.CIXIONG_TARGET_CHOICE.value
    )
    assert discarded_id not in json.dumps(
        visible_target_decision, ensure_ascii=False, sort_keys=True
    )
    attacker_visible = record.player_visible_payload(attacker_id)
    visible_to_attacker = next(
        decision
        for decision in attacker_visible["decisions"]
        if decision["context"]["phase"]
        == ProductionPhase.CIXIONG_TARGET_CHOICE.value
    )
    assert "chosen_action" not in visible_to_attacker
    assert "legal_actions" not in visible_to_attacker
