# -*- coding: utf-8 -*-
"""Production semantics for G3 Wang Yuanji 【谦冲】 and 【尚俭】."""

from __future__ import annotations

from dataclasses import replace
import pytest

from scripts.sgs_engine.actions import (
    ActionContext,
    ActionType,
    InvalidActionError,
    LegalAction,
)
from scripts.sgs_engine.engine import canonical_state_snapshot
from scripts.sgs_engine.events import EventType, GameEvent
from scripts.sgs_engine.model import DISCARD_PILE, DRAW_PILE, ZoneKind, ZoneRef
from scripts.sgs_engine.multiplayer import OutcomePolicy, PlayerTopology
from scripts.sgs_engine.production_batch import (
    BatchActionIdController,
    ProductionBasicCardBatch,
    ProductionBatchError,
    ProductionPhase,
    _replace_player,
)
from scripts.sgs_engine.replay import sha256_value
from scripts.sgs_engine.skill_impl_v1 import create_proof_slice_v1_registry


class _AlwaysFeiyangPolicy:
    """Minimal production mode hook used to expose Feiyang for p1."""

    identity = "test:always-feiyang"

    @staticmethod
    def feiyang_available(
        *, player_id: str, seat: int, turn_number: int
    ) -> bool:
        del player_id, seat, turn_number
        return True


def _game(
    *,
    seed: int = 11,
    players: int = 2,
    first_player_id: str = "p1",
    assignments: dict[str, str] | None = None,
    outcome_policy: OutcomePolicy | None = None,
    mode_policy: object | None = None,
    initial_hand_count: int = 1,
    shuffle: bool = False,
    player_hp: tuple[int, ...] | None = None,
    player_max_hp: tuple[int, ...] | None = None,
) -> ProductionBasicCardBatch:
    ids = tuple(f"p{i}" for i in range(1, players + 1))
    general_map = assignments if assignments is not None else {"p1": "wangyuanji"}
    gen_hp = {"wangyuanji": 3, "zhugezhan": 3, "shamoke": 4}
    hp = player_hp or tuple(gen_hp.get(general_map.get(pid, ""), 4) for pid in ids)
    max_hp = player_max_hp or hp
    return ProductionBasicCardBatch(
        seed=seed,
        shuffle=shuffle,
        first_player_id=first_player_id,
        player_ids=ids,
        player_hp=hp,
        player_max_hp=max_hp,
        outcome_policy=outcome_policy,
        mode_policy=mode_policy,
        initial_hand_count=initial_hand_count,
        general_assignments=general_map,
        skill_registry=create_proof_slice_v1_registry(),
        session_id="g3-wangyuanji-production-session",
        session_secret=b"w" * 32,
    )


def _skill_game(
    *,
    seed: int = 11,
    players: int = 3,
    first_player_id: str = "p2",
    skill_assignments: dict[str, tuple[str, ...]],
    initial_hand_count: int = 1,
) -> ProductionBasicCardBatch:
    """Build a production session with explicit non-general skill assignments.

    This is only a fixture for static-modifier coverage (not a replacement for
    the canonical Wang Yuanji general path used by the other tests).
    """

    ids = tuple(f"p{i}" for i in range(1, players + 1))
    return ProductionBasicCardBatch(
        seed=seed,
        shuffle=False,
        first_player_id=first_player_id,
        player_ids=ids,
        player_hp=(4,) * players,
        player_max_hp=(4,) * players,
        initial_hand_count=initial_hand_count,
        skill_registry=create_proof_slice_v1_registry(),
        skill_assignments=skill_assignments,
        session_id="g3-wangyuanji-static-session",
        session_secret=b"s" * 32,
    )


def _step(game: ProductionBasicCardBatch, action: LegalAction) -> None:
    assert action.action_id
    game.step(BatchActionIdController(action.action_id))


def _take(game: ProductionBasicCardBatch, operation: str, **matches: object) -> LegalAction:
    action = next(
        item
        for item in game.legal_actions()
        if item.payload.get("operation") == operation
        and all(
            (
                item.skill_id == value
                if key == "skill_id"
                else item.target_ids == value
                if key == "target_ids"
                else item.card_instance_id == value
                if key == "card_instance_id"
                else item.payload.get(key) == value
            )
            for key, value in matches.items()
        )
    )
    _step(game, action)
    return action


def _advance_to_play(game: ProductionBasicCardBatch) -> None:
    _take(game, "proceed_prepare")
    _take(game, "proceed_judgment")
    _take(game, "proceed_draw")
    if game.skill_pending is not None and game.skill_pending.skill_id == "sgs_skill_qianchong":
        _take(game, "qianchong_choice", chosen_card_type="basic")
    assert game.phase is ProductionPhase.PLAY


def _set_hand_keys(
    game: ProductionBasicCardBatch,
    player_id: str,
    keys: tuple[str, ...],
    *,
    color: str | None = None,
) -> tuple[str, ...]:
    state = game.state
    moves: dict[str, ZoneRef] = {
        card_id: DRAW_PILE
        for card_id in state.card_ids_in(ZoneRef.hand(player_id))
    }
    chosen: list[str] = []
    for key in keys:
        card_id = next(
            card.instance_id
            for card in state.cards
            if card.card_key == key
            and (color is None or card.color == color)
            and card.instance_id not in chosen
            and state.location_of(card.instance_id) in (DRAW_PILE, DISCARD_PILE)
            and card.instance_id not in moves
        )
        chosen.append(card_id)
        moves[card_id] = ZoneRef.hand(player_id)
    game._state = state.move_cards(moves)
    game.state.assert_card_conservation()
    return tuple(chosen)


def _set_equip(
    game: ProductionBasicCardBatch,
    player_id: str,
    slot: str,
    card_key: str,
    *,
    color: str | None = None,
) -> str:
    state = game.state
    card = next(
        c
        for c in state.cards
        if c.card_key == card_key
        and (color is None or c.color == color)
        and state.location_of(c.instance_id) in (DRAW_PILE, DISCARD_PILE)
    )
    actual_slot = card.equipment_slot or slot
    target_slot = ZoneRef.equipment(player_id, actual_slot)
    game._state = state.move_card(card.instance_id, target_slot)
    game._reconcile_qianchong_for_all(game.state)
    game.state.assert_card_conservation()
    return card.instance_id


def _tiesuo_actions(game: ProductionBasicCardBatch) -> tuple[LegalAction, ...]:
    return tuple(
        action
        for action in game.legal_actions()
        if action.payload.get("operation") == "use_tiesuo"
    )


def test_static_weimu_filters_black_tiesuo_single_and_two_target_actions() -> None:
    game = _skill_game(
        first_player_id="p2",
        players=3,
        skill_assignments={"p1": ("sgs_skill_weimu",)},
    )
    _advance_to_play(game)
    _set_hand_keys(
        game,
        "p2",
        ("sgs_trick_tiesuolianhuan",),
        color="黑",
    )

    actions = _tiesuo_actions(game)
    assert actions
    assert all("p1" not in action.target_ids for action in actions)
    assert any(action.target_ids == ("p2",) for action in actions)
    assert any(set(action.target_ids) == {"p2", "p3"} for action in actions)


def test_dynamic_qianchong_weimu_filters_black_tiesuo_through_signed_production() -> None:
    game = _game(first_player_id="p1", players=3)
    _set_hand_keys(game, "p1", ("sgs_armor_baguazhen",))
    _set_hand_keys(
        game,
        "p2",
        ("sgs_trick_tiesuolianhuan",),
        color="黑",
    )
    _advance_to_play(game)
    _take(game, "use_armor")
    assert game.skill_runtime.has_skill("p1", "sgs_skill_weimu")
    _take(game, "end_play_phase")
    _take(game, "end_turn")
    _advance_to_play(game)

    actions = _tiesuo_actions(game)
    assert actions
    assert all("p1" not in action.target_ids for action in actions)


def test_qianchong_weimu_revoke_restores_black_tiesuo_target_legality() -> None:
    game = _game(first_player_id="p1", players=3)
    state = game.state
    black_armor = next(
        card.instance_id
        for card in state.cards
        if card.card_key == "sgs_armor_baguazhen"
        and card.color == "黑"
        and state.location_of(card.instance_id) in (DRAW_PILE, DISCARD_PILE)
    )
    red_weapon = next(
        card.instance_id
        for card in state.cards
        if card.card_key == "sgs_weapon_zhuqueyushan"
        and card.color == "红"
    )
    moves = {
        card_id: DRAW_PILE
        for card_id in state.card_ids_in(ZoneRef.hand("p1"))
    }
    moves[black_armor] = ZoneRef.hand("p1")
    moves[red_weapon] = ZoneRef.hand("p1")
    game._state = state.move_cards(moves)
    _set_hand_keys(
        game,
        "p2",
        ("sgs_trick_tiesuolianhuan",),
        color="黑",
    )

    _advance_to_play(game)
    _take(game, "use_armor")
    assert game.skill_runtime.has_skill("p1", "sgs_skill_weimu")
    _take(game, "use_weapon", card_key="sgs_weapon_zhuqueyushan")
    assert not game.skill_runtime.has_skill("p1", "sgs_skill_weimu")
    _take(game, "end_play_phase")
    _take(game, "end_turn")
    _advance_to_play(game)

    assert any("p1" in action.target_ids for action in _tiesuo_actions(game))


@pytest.mark.parametrize("target_count", (1, 2))
def test_black_tiesuo_without_weimu_single_and_two_target_signed_use(
    target_count: int,
) -> None:
    game = _skill_game(
        first_player_id="p2",
        players=3,
        skill_assignments={},
    )
    _advance_to_play(game)
    _set_hand_keys(
        game,
        "p2",
        ("sgs_trick_tiesuolianhuan",),
        color="黑",
    )
    action = next(
        item
        for item in _tiesuo_actions(game)
        if len(item.target_ids) == target_count and "p1" in item.target_ids
    )
    _step(game, action)
    assert game.phase is ProductionPhase.TRICK_RESPONSE
    assert game.turn_loss_ledger.count_losses_this_turn("p2") == 1


def test_signed_tiesuo_action_becomes_stale_when_dynamic_weimu_appears() -> None:
    game = _game(first_player_id="p2", players=3)
    _advance_to_play(game)
    tiesuo_id = _set_hand_keys(
        game,
        "p2",
        ("sgs_trick_tiesuolianhuan",),
        color="黑",
    )[0]
    signed_before_grant = next(
        action
        for action in _tiesuo_actions(game)
        if action.target_ids == ("p1",)
    )
    assert signed_before_grant.action_id

    _set_equip(game, "p1", "armor", "sgs_armor_baguazhen", color="黑")
    assert game.skill_runtime.has_skill("p1", "sgs_skill_weimu")
    with pytest.raises(InvalidActionError):
        game.formal_registry.adapter_for(
            "sgs_trick_tiesuolianhuan"
        ).apply_action(
            game.state,
            ActionContext(mode=game.mode_id, phase="play", actor_id="p2"),
            signed_before_grant,
        )
    assert game.state.location_of(tiesuo_id) == ZoneRef.hand("p2")


def test_static_weimu_does_not_block_targetless_tiesuo_recast() -> None:
    game = _skill_game(
        first_player_id="p2",
        players=3,
        skill_assignments={"p1": ("sgs_skill_weimu",)},
    )
    _advance_to_play(game)
    tiesuo_id = _set_hand_keys(
        game,
        "p2",
        ("sgs_trick_tiesuolianhuan",),
        color="黑",
    )[0]
    before = game.turn_loss_ledger.count_losses_this_turn("p2")
    _take(game, "recast_tiesuo", card_instance_id=tiesuo_id)
    assert game.phase is ProductionPhase.PLAY
    assert game.turn_loss_ledger.count_losses_this_turn("p2") == before + 1
    authority = [
        entry
        for entry in game.card_movement_authority
        if entry.card_instance_id == tiesuo_id
    ]
    assert len(authority) == 1
    assert authority[0].source_zone == "hand"
    assert authority[0].destination_zone == "discard"
    assert authority[0].semantic_reason == "tiesuo_recast"
    assert authority[0].movement_kind == "recast"
    assert authority[0].counts_as_shangjian_loss is True
    assert not any(
        event.event_type is EventType.CARD_USED
        and event.card_instance_id == tiesuo_id
        for event in game.events
    )


def test_qianchong_all_black_grants_weimu_and_filters_black_tricks() -> None:
    game = _game(first_player_id="p2")
    _set_equip(game, "p1", "armor", "sgs_armor_baguazhen")
    assert game.skill_runtime.has_skill("p1", "sgs_skill_weimu")
    assert not game.skill_runtime.has_skill("p1", "sgs_skill_mingzhe")

    _take(game, "proceed_prepare")
    _take(game, "proceed_judgment")
    _take(game, "proceed_draw")
    assert game.phase is ProductionPhase.PLAY

    _set_hand_keys(game, "p2", ("sgs_trick_guohechaiqiao",))
    _set_hand_keys(game, "p1", ("sgs_basic_tao",))

    chaiqiao_actions = [
        a for a in game.legal_actions()
        if a.payload.get("operation") == "use_guohe" and a.target_ids == ("p1",)
    ]
    assert len(chaiqiao_actions) == 0


def test_qianchong_all_red_grants_mingzhe_and_triggers_on_red_loss() -> None:
    game = _game(first_player_id="p2")
    _set_equip(game, "p1", "weapon", "sgs_weapon_zhuqueyushan", color="红")
    assert game.skill_runtime.has_skill("p1", "sgs_skill_mingzhe")
    assert not game.skill_runtime.has_skill("p1", "sgs_skill_weimu")

    tao_cards = [
        c for c in game.state.cards
        if c.card_key == "sgs_basic_tao" and c.color == "红"
    ]

    _take(game, "proceed_prepare")
    _take(game, "proceed_judgment")
    _take(game, "proceed_draw")

    _set_hand_keys(game, "p1", (tao_cards[0].card_key,))
    _set_hand_keys(game, "p2", ("sgs_trick_guohechaiqiao",))

    _take(game, "use_guohe", target_ids=("p1",))
    _take(game, "pass_trick_response")
    _take(game, "pass_trick_response")
    _take(game, "choose_target_zone_card", zone="hand")

    assert game.skill_pending is not None
    assert game.skill_pending.skill_id == "sgs_skill_mingzhe"
    assert game.skill_pending.actor_id == "p1"

    p1_hand_before = len(game.state.card_ids_in(ZoneRef.hand("p1")))
    _take(game, "activate_skill", skill_id="sgs_skill_mingzhe")
    p1_hand_after = len(game.state.card_ids_in(ZoneRef.hand("p1")))
    assert p1_hand_after == p1_hand_before + 1


def test_qianchong_mixed_equipment_revokes_both_grants() -> None:
    game = _game()
    _set_equip(game, "p1", "armor", "sgs_armor_baguazhen")
    assert game.skill_runtime.has_skill("p1", "sgs_skill_weimu")

    _set_equip(game, "p1", "weapon", "sgs_weapon_zhuqueyushan", color="红")
    assert not game.skill_runtime.has_skill("p1", "sgs_skill_weimu")
    assert not game.skill_runtime.has_skill("p1", "sgs_skill_mingzhe")


def test_qianchong_losing_last_red_equipment_revokes_mingzhe_before_trigger() -> None:
    # QIANCHONG_DYNAMIC_SKILL_EVENT_ORDER = POST_MOVEMENT_EFFECTIVE_SKILL_SET
    game = _game(first_player_id="p2")
    _set_equip(game, "p1", "weapon", "sgs_weapon_zhuqueyushan", color="红")
    assert game.skill_runtime.has_skill("p1", "sgs_skill_mingzhe")

    _take(game, "proceed_prepare")
    _take(game, "proceed_judgment")
    _take(game, "proceed_draw")

    _set_hand_keys(game, "p2", ("sgs_trick_guohechaiqiao",))
    _take(game, "use_guohe", target_ids=("p1",))
    _take(game, "pass_trick_response")
    _take(game, "pass_trick_response")
    _take(game, "choose_target_zone_card", zone="equipment:weapon")

    assert game.skill_pending is None
    assert not game.skill_runtime.has_skill("p1", "sgs_skill_mingzhe")


def test_qianchong_revokes_materialized_mingzhe_after_prior_trigger_use() -> None:
    """A used dynamic Mingzhe state must not survive its Qianchong grant."""
    game = _game(
        first_player_id="p2",
        players=3,
        assignments={"p1": "wangyuanji", "p2": "zhugezhan", "p3": "shamoke"},
    )
    initial_hand_ids = tuple(
        card_id
        for player_id in ("p1", "p2", "p3")
        for card_id in game.state.card_ids_in(ZoneRef.hand(player_id))
    )
    game._state = game.state.move_cards({card_id: DRAW_PILE for card_id in initial_hand_ids})
    _set_equip(game, "p1", "weapon", "sgs_weapon_zhuqueyushan", color="红")
    assert game.skill_runtime.has_skill("p1", "sgs_skill_mingzhe")

    _advance_to_play(game)
    _set_hand_keys(game, "p1", ("sgs_basic_tao",), color="红")
    _set_hand_keys(game, "p2", ("sgs_trick_guohechaiqiao", "sgs_trick_guohechaiqiao"))

    # First red hand loss uses the dynamic Mingzhe state, materializing usage.
    _take(game, "use_guohe", target_ids=("p1",))
    _take(game, "pass_trick_response")
    _take(game, "pass_trick_response")
    _take(game, "pass_trick_response")
    _take(game, "choose_target_zone_card", zone="hand")
    assert game.skill_pending is not None
    assert game.skill_pending.skill_id == "sgs_skill_mingzhe"
    _take(game, "activate_skill", skill_id="sgs_skill_mingzhe")
    assert game.skill_runtime.has_skill("p1", "sgs_skill_mingzhe")
    materialized_state = game.skill_runtime.get_skill_state("p1", "sgs_skill_mingzhe")
    assert materialized_state.source == "dynamic_grant:sgs_skill_qianchong"
    assert materialized_state.uses_this_phase == 1

    # The unique red equipment then leaves: the grant is revoked and the
    # materialized synthetic state must disappear with it.
    _take(game, "use_guohe", target_ids=("p1",))
    _take(game, "pass_trick_response")
    _take(game, "pass_trick_response")
    _take(game, "pass_trick_response")
    _take(game, "choose_target_zone_card", zone="equipment:weapon")
    assert not game.skill_runtime.has_skill("p1", "sgs_skill_mingzhe")


def test_qianchong_play_phase_start_choice_basic_bypasses_slash_limits_and_distance() -> None:
    game = _game(first_player_id="p1")
    _take(game, "proceed_prepare")
    _take(game, "proceed_judgment")
    _take(game, "proceed_draw")

    assert game.skill_pending is not None
    assert game.skill_pending.skill_id == "sgs_skill_qianchong"

    _take(game, "qianchong_choice", chosen_card_type="basic")
    assert game.phase is ProductionPhase.PLAY
    assert game.qianchong_phase_permission is not None
    assert game.qianchong_phase_permission.chosen_card_type == "basic"

    sha_cards = [c.card_key for c in game.state.cards if c.card_key == "sgs_basic_sha"]
    _set_hand_keys(game, "p1", (sha_cards[0], sha_cards[1]))

    _take(game, "use_slash", target_ids=("p2",))
    _take(game, "pass_slash_response")
    assert game.phase is ProductionPhase.PLAY

    _take(game, "use_slash", target_ids=("p2",))
    _take(game, "pass_slash_response")
    assert game.phase is ProductionPhase.PLAY


def test_qianchong_play_phase_start_choice_trick_bypasses_shunshou_distance() -> None:
    game = _game(first_player_id="p1", players=3)
    _take(game, "proceed_prepare")
    _take(game, "proceed_judgment")
    _take(game, "proceed_draw")

    assert game.skill_pending is not None
    _take(game, "qianchong_choice", chosen_card_type="trick")
    assert game.phase is ProductionPhase.PLAY

    # p3 is at distance 2 from p1
    _set_hand_keys(game, "p1", ("sgs_trick_shunshouqianyang",))
    _set_hand_keys(game, "p3", ("sgs_basic_shan",))

    shunshou_to_p3 = [
        a for a in game.legal_actions()
        if a.payload.get("operation") == "use_shunshou" and a.target_ids == ("p3",)
    ]
    assert len(shunshou_to_p3) == 1


def test_qianchong_equipment_change_during_play_retains_permission() -> None:
    game = _game(first_player_id="p1")
    _advance_to_play(game)

    assert game.qianchong_phase_permission is not None
    assert game.qianchong_phase_permission.chosen_card_type == "basic"

    _set_equip(game, "p1", "armor", "sgs_armor_baguazhen")
    assert game.skill_runtime.has_skill("p1", "sgs_skill_weimu")
    assert game.is_slash_limit_bypassed("p1")


def test_shangjian_loss_ledger_draws_exact_losses_if_le_hp() -> None:
    game = _game(first_player_id="p1", player_hp=(3, 4))
    _advance_to_play(game)

    sha_cards = [c.card_key for c in game.state.cards if c.card_key == "sgs_basic_sha"]
    _set_hand_keys(game, "p1", (sha_cards[0], sha_cards[1]))

    _take(game, "use_slash", target_ids=("p2",))
    _take(game, "pass_slash_response")
    _take(game, "use_slash", target_ids=("p2",))
    _take(game, "pass_slash_response")

    assert game.turn_loss_ledger.count_losses_this_turn("p1") == 2

    p1_hand_before_end = len(game.state.card_ids_in(ZoneRef.hand("p1")))
    _take(game, "end_play_phase")
    assert game.phase is ProductionPhase.END
    p1_hand_after_end = len(game.state.card_ids_in(ZoneRef.hand("p1")))
    assert p1_hand_after_end == p1_hand_before_end + 2


def test_shangjian_loss_ledger_draws_zero_if_losses_exceed_hp() -> None:
    game = _game(first_player_id="p1", player_hp=(3, 4))
    _advance_to_play(game)
    game._state = _replace_player(game.state, "p1", hp=1)

    sha_cards = [c.card_key for c in game.state.cards if c.card_key == "sgs_basic_sha"]
    _set_hand_keys(game, "p1", (sha_cards[0], sha_cards[1]))

    _take(game, "use_slash", target_ids=("p2",))
    _take(game, "pass_slash_response")
    _take(game, "use_slash", target_ids=("p2",))
    _take(game, "pass_slash_response")

    p1_hand_before_end = len(game.state.card_ids_in(ZoneRef.hand("p1")))
    _take(game, "end_play_phase")
    assert game.phase is ProductionPhase.END
    p1_hand_after_end = len(game.state.card_ids_in(ZoneRef.hand("p1")))
    assert p1_hand_after_end == p1_hand_before_end


def test_shangjian_self_equip_does_not_count_as_loss() -> None:
    game = _game(first_player_id="p1", player_hp=(3, 4))
    _advance_to_play(game)

    armor_id = _set_hand_keys(game, "p1", ("sgs_armor_baguazhen",))[0]

    _take(game, "use_armor")
    assert game.turn_loss_ledger.count_losses_this_turn("p1") == 0
    authority = [
        entry
        for entry in game.card_movement_authority
        if entry.card_instance_id == armor_id
    ]
    assert [(entry.source_zone, entry.destination_zone) for entry in authority] == [
        ("hand", "processing"),
        ("processing", "equipment:armor"),
    ]
    assert len({entry.root_operation_identity for entry in authority}) == 1
    assert not any(entry.counts_as_shangjian_loss for entry in authority)


def test_discard_phase_three_cards_records_l3_draws_three_and_skips_own_turn_mingzhe() -> None:
    game = _game(
        first_player_id="p1",
        player_hp=(3, 4),
        initial_hand_count=4,
    )
    red_weapon_id = next(
        card.instance_id
        for card in game.state.cards
        if card.card_key == "sgs_weapon_zhuqueyushan" and card.color == "红"
    )
    game._state = game.state.move_card(
        red_weapon_id, ZoneRef.equipment("p1", "weapon")
    )
    game._reconcile_qianchong_for_all(game.state)
    assert game.skill_runtime.has_skill("p1", "sgs_skill_mingzhe")
    _advance_to_play(game)

    state = game.state
    red_cards = tuple(
        card.instance_id
        for card in state.cards
        if card.color == "红"
        and state.location_of(card.instance_id) in (DRAW_PILE, DISCARD_PILE)
    )[:6]
    assert len(red_cards) == 6
    moves = {
        card_id: DRAW_PILE
        for card_id in state.card_ids_in(ZoneRef.hand("p1"))
    }
    moves.update({card_id: ZoneRef.hand("p1") for card_id in red_cards})
    game._state = state.move_cards(moves)
    game.state.assert_card_conservation()
    assert len(game.state.card_ids_in(ZoneRef.hand("p1"))) == 6

    _take(game, "end_play_phase")
    assert game.phase is ProductionPhase.DISCARD
    selected_ids = red_cards[:3]
    for card_id in selected_ids:
        action = next(
            item
            for item in game.legal_actions()
            if item.payload.get("operation") == "select_discard_card"
            and item.card_instance_id == card_id
        )
        _step(game, action)
    _take(game, "discard_phase_submit")

    assert game.phase is ProductionPhase.END
    assert game.turn_loss_ledger.count_losses_this_turn("p1") == 3
    authority = [
        entry
        for entry in game.card_movement_authority
        if entry.semantic_reason == "discard_phase"
    ]
    assert {entry.card_instance_id for entry in authority} == set(selected_ids)
    assert len({entry.root_operation_identity for entry in authority}) == 1
    assert all(entry.counts_as_shangjian_loss for entry in authority)
    assert all(entry.mingzhe_discovery_eligible for entry in authority)
    assert len(game.state.card_ids_in(ZoneRef.hand("p1"))) == 6
    shangjian_draws = [
        event
        for event in game.events
        if event.event_type is EventType.CARD_MOVED
        and event.payload.get("reason") == "sgs_skill_shangjian"
    ]
    assert len(shangjian_draws) == 3
    assert game.skill_pending is None
    assert not any(
        event.event_type is EventType.SKILL_CONDITION_EVALUATED
        and event.payload.get("skill_id") == "sgs_skill_mingzhe"
        for event in game.events
    )


def test_normal_basic_use_processing_chain_counts_once() -> None:
    game = _game(first_player_id="p1")
    _advance_to_play(game)
    wine_id = _set_hand_keys(game, "p1", ("sgs_basic_jiu",))[0]
    _take(game, "use_wine_buff", card_instance_id=wine_id)

    authority = [
        entry
        for entry in game.card_movement_authority
        if entry.card_instance_id == wine_id
    ]
    assert [(entry.source_zone, entry.destination_zone) for entry in authority] == [
        ("hand", "processing"),
        ("processing", "discard"),
    ]
    assert sum(entry.counts_as_shangjian_loss for entry in authority) == 1
    assert authority[0].mingzhe_discovery_eligible is True
    assert authority[1].mingzhe_discovery_eligible is False
    assert game.turn_loss_ledger.count_losses_this_turn("p1") == 1


def test_fire_attack_same_suit_discard_adds_one_loss_through_signed_production() -> None:
    game = _game(first_player_id="p1")
    _advance_to_play(game)
    state = game.state
    available = [
        card
        for card in state.cards
        if state.location_of(card.instance_id) in (DRAW_PILE, DISCARD_PILE)
    ]
    fire = next(card for card in available if card.card_key == "sgs_trick_huogong")
    target_card = next(
        card
        for card in available
        if card.instance_id != fire.instance_id
        and any(
            other.instance_id not in (fire.instance_id, card.instance_id)
            and other.suit == card.suit
            for other in available
        )
    )
    same_suit_cost = next(
        card
        for card in available
        if card.instance_id not in (fire.instance_id, target_card.instance_id)
        and card.suit == target_card.suit
    )
    moves = {
        card_id: DRAW_PILE
        for player_id in ("p1", "p2")
        for card_id in state.card_ids_in(ZoneRef.hand(player_id))
    }
    moves.update(
        {
            fire.instance_id: ZoneRef.hand("p1"),
            same_suit_cost.instance_id: ZoneRef.hand("p1"),
            target_card.instance_id: ZoneRef.hand("p2"),
        }
    )
    game._state = state.move_cards(moves)
    game.state.assert_card_conservation()

    _take(game, "use_fire_attack", target_ids=("p2",))
    while game.phase is ProductionPhase.TRICK_RESPONSE:
        _take(game, "pass_trick_response")
    _take(game, "reveal_card_for_fire_attack")
    before_discard = game.turn_loss_ledger.count_losses_this_turn("p1")
    _take(
        game,
        "discard_same_suit_for_fire_attack",
        card_instance_id=same_suit_cost.instance_id,
    )

    assert game.turn_loss_ledger.count_losses_this_turn("p1") == before_discard + 1
    movement = next(
        entry
        for entry in game.card_movement_authority
        if entry.card_instance_id == same_suit_cost.instance_id
    )
    assert movement.source_zone == "hand"
    assert movement.destination_zone == "discard"
    assert movement.semantic_reason == "fire_attack_discard_same_suit"
    assert movement.movement_kind == "discard"
    assert movement.counts_as_shangjian_loss is True
    assert movement.mingzhe_discovery_eligible is True
    assert game.skill_pending is None


def test_delayed_trick_use_folds_two_nodes_into_one_loss_root() -> None:
    game = _game(first_player_id="p1")
    _advance_to_play(game)
    delayed_id = _set_hand_keys(game, "p1", ("sgs_delayed_lebusi",))[0]
    before = game.turn_loss_ledger.count_losses_this_turn("p1")
    _take(game, "use_lebusi", target_ids=("p2",))

    assert game.state.location_of(delayed_id) == ZoneRef.judgment("p2")
    authority = [
        entry
        for entry in game.card_movement_authority
        if entry.card_instance_id == delayed_id
    ]
    assert [(entry.source_zone, entry.destination_zone) for entry in authority] == [
        ("hand", "processing"),
        ("processing", "judgment"),
    ]
    assert len({entry.root_operation_identity for entry in authority}) == 1
    assert sum(entry.counts_as_shangjian_loss for entry in authority) == 1
    assert authority[0].mingzhe_discovery_eligible is True
    assert authority[1].mingzhe_discovery_eligible is False
    assert game.turn_loss_ledger.count_losses_this_turn("p1") == before + 1


def test_feiyang_hand_cost_counts_two_and_judgment_source_counts_zero() -> None:
    game = _game(
        first_player_id="p1",
        initial_hand_count=3,
        mode_policy=_AlwaysFeiyangPolicy(),
    )
    judgment_id = next(
        card.instance_id
        for card in game.state.cards
        if game.state.location_of(card.instance_id) in (DRAW_PILE, DISCARD_PILE)
    )
    game._state = game.state.move_card(judgment_id, ZoneRef.judgment("p1"))
    game.state.assert_card_conservation()

    _take(game, "proceed_prepare")
    assert game.phase is ProductionPhase.FEIYANG_ACTIVATE
    action = next(
        item
        for item in game.legal_actions()
        if item.payload.get("operation") == "feiyang_activate"
    )
    hand_ids = tuple(action.payload["hand_ids"])
    _step(game, action)

    assert game.phase is ProductionPhase.JUDGMENT
    assert game.turn_loss_ledger.count_losses_this_turn("p1") == 2
    authority = [
        entry
        for entry in game.card_movement_authority
        if entry.card_instance_id in (*hand_ids, judgment_id)
    ]
    assert len(authority) == 3
    assert len({entry.root_operation_identity for entry in authority}) == 1
    hand_entries = [entry for entry in authority if entry.card_instance_id in hand_ids]
    judgment_entry = next(
        entry for entry in authority if entry.card_instance_id == judgment_id
    )
    assert all(entry.semantic_reason == "feiyang_cost" for entry in hand_entries)
    assert all(entry.counts_as_shangjian_loss for entry in hand_entries)
    assert judgment_entry.source_zone == "judgment"
    assert judgment_entry.semantic_reason == "feiyang_judgment_discard"
    assert judgment_entry.counts_as_shangjian_loss is False


def test_same_card_can_leave_hand_in_two_independent_roots_and_counts_twice() -> None:
    game = _game(first_player_id="p1")
    card_id = game.state.card_ids_in(ZoneRef.hand("p1"))[0]
    game._state = game._commit_authoritative_card_movements(
        game.state,
        {card_id: DISCARD_PILE},
        semantic_reason="independent_loss_one",
        movement_kind="discard",
        root_operation_identity="independent-root-one",
        action_actor_id="p1",
        card_user_id="p1",
    )
    game._state = game._commit_authoritative_card_movements(
        game.state,
        {card_id: ZoneRef.hand("p1")},
        semantic_reason="independent_regain",
        movement_kind="gain",
        root_operation_identity="independent-root-regain",
        action_actor_id="p1",
        card_user_id="p1",
    )
    game._state = game._commit_authoritative_card_movements(
        game.state,
        {card_id: DISCARD_PILE},
        semantic_reason="independent_loss_two",
        movement_kind="discard",
        root_operation_identity="independent-root-two",
        action_actor_id="p1",
        card_user_id="p1",
    )

    counted = [
        entry
        for entry in game.card_movement_authority
        if entry.card_instance_id == card_id
        and entry.counts_as_shangjian_loss
    ]
    assert [entry.root_operation_identity for entry in counted] == [
        "independent-root-one",
        "independent-root-two",
    ]
    assert len({entry.movement_identity for entry in counted}) == 2
    assert game.turn_loss_ledger.count_losses_this_turn("p1") == 2


def test_death_cleanup_counts_each_hand_and_equipment_but_not_judgment() -> None:
    game = _game(first_player_id="p1")
    equip_id = _set_equip(game, "p1", "armor", "sgs_armor_baguazhen")
    judgment_id = next(
        card.instance_id
        for card in game.state.cards
        if game.state.location_of(card.instance_id) in (DRAW_PILE, DISCARD_PILE)
    )
    game._state = game.state.move_card(judgment_id, ZoneRef.judgment("p1"))
    hand_ids = tuple(game.state.card_ids_in(ZoneRef.hand("p1")))

    next_state, cleanup_events = game._death_zone_cleanup(game.state, "p1")
    game._state = next_state
    expected_counted = set((*hand_ids, equip_id))
    authority = [
        entry
        for entry in game.card_movement_authority
        if entry.semantic_reason == "death_cleanup"
    ]
    assert {entry.card_instance_id for entry in authority} == {
        *expected_counted,
        judgment_id,
    }
    assert {
        entry.card_instance_id
        for entry in authority
        if entry.counts_as_shangjian_loss
    } == expected_counted
    judgment_entry = next(
        entry for entry in authority if entry.card_instance_id == judgment_id
    )
    assert judgment_entry.source_zone == "judgment"
    assert judgment_entry.counts_as_shangjian_loss is False
    assert len(cleanup_events) == len(authority)
    assert game.turn_loss_ledger.count_losses_this_turn("p1") == len(expected_counted)
    game.state.assert_card_conservation()


def test_normal_red_self_equip_does_not_retroactively_trigger_mingzhe() -> None:
    """The HAND -> PROCESSING loss node precedes the later red-equip grant."""
    game = _game(first_player_id="p1", players=2)
    _advance_to_play(game)
    assert not game.skill_runtime.has_skill("p1", "sgs_skill_mingzhe")
    red_weapon = next(
        card
        for card in game.state.cards
        if card.card_key == "sgs_weapon_zhuqueyushan" and card.color == "红"
    )
    hand = set(game.state.card_ids_in(ZoneRef.hand("p1")))
    moves = {card_id: DRAW_PILE for card_id in hand if card_id != red_weapon.instance_id}
    if game.state.location_of(red_weapon.instance_id) != ZoneRef.hand("p1"):
        moves[red_weapon.instance_id] = ZoneRef.hand("p1")
    game._state = game.state.move_cards(moves)
    game.state.assert_card_conservation()

    _take(game, "use_weapon", card_key="sgs_weapon_zhuqueyushan")

    assert game.turn_loss_ledger.count_losses_this_turn("p1") == 0
    assert game.skill_runtime.has_skill("p1", "sgs_skill_mingzhe")
    assert game.skill_pending is None
    assert not any(
        event.payload.get("skill_id") == "sgs_skill_mingzhe"
        for event in game.events
    )


def test_shangjian_triggers_on_other_players_end_phase() -> None:
    game = _game(first_player_id="p2", player_hp=(3, 4))
    _take(game, "proceed_prepare")
    _take(game, "proceed_judgment")
    _take(game, "proceed_draw")

    _set_hand_keys(game, "p1", ("sgs_basic_shan",))
    _set_hand_keys(game, "p2", ("sgs_trick_guohechaiqiao",))
    _take(game, "use_guohe", target_ids=("p1",))
    _take(game, "pass_trick_response")
    _take(game, "pass_trick_response")
    _take(game, "choose_target_zone_card", zone="hand")

    assert game.turn_loss_ledger.count_losses_this_turn("p1") == 1

    p1_hand_before_end = len(game.state.card_ids_in(ZoneRef.hand("p1")))
    _take(game, "end_play_phase")
    assert game.phase is ProductionPhase.END
    p1_hand_after_end = len(game.state.card_ids_in(ZoneRef.hand("p1")))
    assert p1_hand_after_end == p1_hand_before_end + 1


def test_qianchong_permission_does_not_modify_base_attack_range_or_distance() -> None:
    from scripts.sgs_engine.production_cards import attack_range_of
    game = _game(first_player_id="p1", players=3)
    _take(game, "proceed_prepare")
    _take(game, "proceed_judgment")
    _take(game, "proceed_draw")
    _take(game, "qianchong_choice", chosen_card_type="basic")

    assert attack_range_of(game.state, "p1") == 1
    assert game.is_slash_limit_bypassed("p1") is True
    assert game.is_card_distance_bypassed("p1", "basic") is True
    assert game.is_card_distance_bypassed("p1", "trick") is False


def test_shangjian_and_zuilun_coexist_in_multiplayer_seating_order() -> None:
    game = _game(
        first_player_id="p2",
        players=3,
        assignments={"p1": "wangyuanji", "p2": "zhugezhan"},
        player_hp=(3, 3, 4),
        player_max_hp=(3, 3, 4),
    )
    _take(game, "proceed_prepare")
    _take(game, "proceed_judgment")
    _take(game, "proceed_draw")

    _set_hand_keys(game, "p1", ("sgs_basic_shan",))
    _set_hand_keys(game, "p2", ("sgs_trick_guohechaiqiao",))
    _take(game, "use_guohe", target_ids=("p1",))
    _take(game, "pass_trick_response")
    _take(game, "pass_trick_response")
    _take(game, "pass_trick_response")
    _take(game, "choose_target_zone_card", zone="hand")

    assert game.turn_loss_ledger.count_losses_this_turn("p1") == 1

    p1_hand_before_end = len(game.state.card_ids_in(ZoneRef.hand("p1")))
    _take(game, "end_play_phase")
    assert game.phase is ProductionPhase.END
    # In seating order p2 (Zhuge Zhan) triggers Zuilun decision window first
    if game.skill_pending is not None and game.skill_pending.skill_id == "sgs_skill_zuilun":
        _take(game, "pass_skill")
    # Shangjian resolved for p1 during end phase dispatcher
    p1_hand_after_end = len(game.state.card_ids_in(ZoneRef.hand("p1")))
    assert p1_hand_after_end == p1_hand_before_end + 1


def test_end_dispatcher_pauses_and_does_not_execute_later_seat_shangjian_while_zuilun_is_pending() -> None:
    game = _game(
        first_player_id="p2",
        players=3,
        assignments={"p1": "wangyuanji", "p2": "zhugezhan"},
        player_hp=(3, 3, 4),
        player_max_hp=(3, 3, 4),
    )
    _take(game, "proceed_prepare")
    _take(game, "proceed_judgment")
    _take(game, "proceed_draw")

    _set_hand_keys(game, "p1", ("sgs_basic_shan",))
    _set_hand_keys(game, "p2", ("sgs_trick_guohechaiqiao",))
    _take(game, "use_guohe", target_ids=("p1",))
    _take(game, "pass_trick_response")
    _take(game, "pass_trick_response")
    _take(game, "pass_trick_response")
    _take(game, "choose_target_zone_card", zone="hand")

    assert game.turn_loss_ledger.count_losses_this_turn("p1") == 1
    p1_hand_before_end = len(game.state.card_ids_in(ZoneRef.hand("p1")))
    top_deck_card_before = game.state.card_ids_in(DRAW_PILE)[0]

    _take(game, "end_play_phase")
    assert game.phase is ProductionPhase.END
    # Seat 0 (p2 Zhugezhan) has Zuilun decision window open
    assert game.skill_pending is not None
    assert game.skill_pending.skill_id == "sgs_skill_zuilun"
    assert game.skill_pending.actor_id == "p2"

    # Breakpoint assertions: later-seat p1 (Wang Yuanji) has NOT executed Shangjian yet!
    assert len(game.state.card_ids_in(ZoneRef.hand("p1"))) == p1_hand_before_end
    shangjian_eval_events = [
        e for e in game.events
        if e.event_type == EventType.SKILL_CONDITION_EVALUATED
        and e.payload.get("skill_id") == "sgs_skill_shangjian"
    ]
    assert len(shangjian_eval_events) == 0
    shangjian_draw_events = [
        e for e in game.events
        if e.payload.get("reason") == "sgs_skill_shangjian"
    ]
    assert len(shangjian_draw_events) == 0
    # Deck top was not consumed by Shangjian
    assert game.state.card_ids_in(DRAW_PILE)[0] == top_deck_card_before


def test_end_dispatcher_zuilun_pass_resumes_and_executes_shangjian() -> None:
    game = _game(
        first_player_id="p2",
        players=3,
        assignments={"p1": "wangyuanji", "p2": "zhugezhan"},
        player_hp=(3, 3, 4),
        player_max_hp=(3, 3, 4),
    )
    _take(game, "proceed_prepare")
    _take(game, "proceed_judgment")
    _take(game, "proceed_draw")

    _set_hand_keys(game, "p1", ("sgs_basic_shan",))
    _set_hand_keys(game, "p2", ("sgs_trick_guohechaiqiao",))
    _take(game, "use_guohe", target_ids=("p1",))
    _take(game, "pass_trick_response")
    _take(game, "pass_trick_response")
    _take(game, "pass_trick_response")
    _take(game, "choose_target_zone_card", zone="hand")
    _take(game, "end_play_phase")

    assert game.skill_pending is not None and game.skill_pending.skill_id == "sgs_skill_zuilun"
    # p2 passes Zuilun
    _take(game, "pass_skill")
    # Resumed dispatcher reaches p1 and executes Shangjian
    assert len(game.state.card_ids_in(ZoneRef.hand("p1"))) == 1
    shangjian_eval_events = [
        e for e in game.events
        if e.event_type == EventType.SKILL_CONDITION_EVALUATED
        and e.payload.get("skill_id") == "sgs_skill_shangjian"
    ]
    assert len(shangjian_eval_events) == 1
    assert shangjian_eval_events[0].payload.get("condition_met") is True
    assert shangjian_eval_events[0].payload.get("draw_count") == 1


def test_end_dispatcher_zuilun_activate_full_resumes_and_executes_shangjian() -> None:
    game = _game(
        first_player_id="p2",
        players=3,
        assignments={"p1": "wangyuanji", "p2": "zhugezhan"},
        player_hp=(3, 3, 4),
        player_max_hp=(3, 3, 4),
    )
    _take(game, "proceed_prepare")
    _take(game, "proceed_judgment")
    _take(game, "proceed_draw")

    _set_hand_keys(game, "p1", ("sgs_basic_shan",))
    _set_hand_keys(game, "p2", ("sgs_trick_guohechaiqiao",))
    _take(game, "use_guohe", target_ids=("p1",))
    _take(game, "pass_trick_response")
    _take(game, "pass_trick_response")
    _take(game, "pass_trick_response")
    _take(game, "choose_target_zone_card", zone="hand")
    _take(game, "end_play_phase")

    assert game.skill_pending is not None and game.skill_pending.skill_id == "sgs_skill_zuilun"
    top_before_zuilun = tuple(game.state.card_ids_in(DRAW_PILE)[:3])
    _take(game, "activate_skill")
    # Select one of the private top cards and let the resumable dispatcher run.
    selection = next(
        action
        for action in game.legal_actions()
        if action.payload.get("operation") == "private_card_selection_submit"
    )
    selected = tuple(selection.payload["selected_card_ids"])
    remaining_after_zuilun = tuple(
        card_id for card_id in top_before_zuilun if card_id not in selected
    )
    _step(game, selection)

    # After Zuilun completes, dispatcher resumes and executes Shangjian for p1
    assert len(game.state.card_ids_in(ZoneRef.hand("p1"))) == 1
    shangjian_eval_events = [
        e for e in game.events
        if e.event_type == EventType.SKILL_CONDITION_EVALUATED
        and e.payload.get("skill_id") == "sgs_skill_shangjian"
    ]
    assert len(shangjian_eval_events) == 1
    shangjian_draws = [
        event
        for event in game.events
        if event.event_type is EventType.CARD_MOVED
        and event.payload.get("reason") == "sgs_skill_shangjian"
    ]
    assert len(shangjian_draws) == 1
    # The later seat consumes the live deck after Zuilun's selection, not the
    # pre-selection top card.
    assert shangjian_draws[0].card_instance_id == remaining_after_zuilun[0]


def test_end_dispatcher_zuilun_n0_resume_reads_live_hp_before_shangjian() -> None:
    """n=0's target HP loss must be visible to the later END seat."""

    game = _game(
        first_player_id="p2",
        players=3,
        assignments={"p1": "wangyuanji", "p2": "zhugezhan"},
        player_hp=(3, 3, 4),
        player_max_hp=(3, 3, 4),
        initial_hand_count=4,
    )
    _take(game, "proceed_prepare")
    _take(game, "proceed_judgment")
    _take(game, "proceed_draw")
    _set_hand_keys(
        game,
        "p2",
        (
            "sgs_trick_guohechaiqiao",
            "sgs_trick_guohechaiqiao",
            "sgs_trick_guohechaiqiao",
            "sgs_basic_tao",
        ),
    )
    _set_hand_keys(
        game,
        "p1",
        ("sgs_basic_shan", "sgs_basic_tao", "sgs_basic_shan"),
    )
    _set_hand_keys(game, "p3", ("sgs_basic_shan",))

    for _ in range(3):
        _take(game, "use_guohe", target_ids=("p1",))
        _take(game, "pass_trick_response")
        _take(game, "pass_trick_response")
        _take(game, "pass_trick_response")
        _take(game, "choose_target_zone_card", zone="hand")

    assert game.turn_loss_ledger.count_losses_this_turn("p1") == 3
    _take(game, "end_play_phase")
    assert game.skill_pending is not None
    assert game.skill_pending.skill_id == "sgs_skill_zuilun"
    assert not any(
        event.payload.get("skill_id") == "sgs_skill_shangjian"
        for event in game.events
        if event.event_type is EventType.SKILL_CONDITION_EVALUATED
    )

    _take(game, "activate_skill")
    assert any(
        action.payload.get("operation") == "skill_lose_hp_target_choice"
        for action in game.legal_actions()
    )
    _take(game, "skill_lose_hp_target_choice", target_ids=("p1",))

    assert game.state.players_by_id["p1"].hp == 2
    shangjian_eval = next(
        event
        for event in game.events
        if event.event_type is EventType.SKILL_CONDITION_EVALUATED
        and event.payload.get("skill_id") == "sgs_skill_shangjian"
    )
    assert shangjian_eval.payload["l_count"] == 3
    assert shangjian_eval.payload["h_hp"] == 2
    assert shangjian_eval.payload["condition_met"] is False
    assert shangjian_eval.payload["draw_count"] == 0
    assert not any(
        event.payload.get("reason") == "sgs_skill_shangjian"
        for event in game.events
    )
    assert game._skill_audit_value()["end_phase_dispatch_state"] is None


def test_end_dispatcher_game_over_stops_later_seat_shangjian() -> None:
    game = _game(
        first_player_id="p2",
        players=2,
        assignments={"p1": "wangyuanji", "p2": "zhugezhan"},
        player_hp=(3, 3),
        player_max_hp=(3, 3),
    )
    game._state = _replace_player(game.state, "p2", hp=1)
    _take(game, "proceed_prepare")
    _take(game, "proceed_judgment")
    _take(game, "proceed_draw")
    _set_hand_keys(
        game,
        "p2",
        ("sgs_basic_tao", "sgs_basic_shan", "sgs_basic_jiu"),
    )
    p1_card = _set_hand_keys(game, "p1", ("sgs_basic_shan",))[0]
    p2_discard = game.state.card_ids_in(ZoneRef.hand("p2"))[1]
    game._state = game.discard_cards_for_skill(
        game.state,
        (p2_discard,),
        owner_id="p2",
        reason="g3_end_terminal_zuilun_fact_fixture",
        skill_owner="p2",
    )
    game._state = game.discard_cards_for_skill(
        game.state,
        (p1_card,),
        owner_id="p1",
        reason="g3_end_terminal_shangjian_fact_fixture",
        skill_owner="p2",
    )
    assert game.turn_loss_ledger.count_losses_this_turn("p1") == 1

    _take(game, "end_play_phase")
    while game.phase is ProductionPhase.DISCARD:
        submit = next(
            (
                action
                for action in game.legal_actions()
                if action.payload.get("operation") == "discard_phase_submit"
            ),
            None,
        )
        if submit is not None:
            _step(game, submit)
        else:
            _take(game, "select_discard_card")
    assert game.skill_pending is not None
    assert game.skill_pending.skill_id == "sgs_skill_zuilun"
    activate = next(
        action
        for action in game.legal_actions()
        if action.action_type is ActionType.ACTIVATE_SKILL
        and action.skill_id == "sgs_skill_zuilun"
    )
    assert activate.payload["n"] == 0
    _step(game, activate)
    while game.phase is ProductionPhase.DYING_RESCUE:
        _take(game, "pass_rescue")

    assert game.is_finished
    assert game.winner_id == "p1"
    assert not game.state.players_by_id["p2"].alive
    assert not any(
        event.event_type is EventType.SKILL_CONDITION_EVALUATED
        and event.payload.get("skill_id") == "sgs_skill_shangjian"
        for event in game.events
    )
    assert not any(
        event.payload.get("reason") == "sgs_skill_shangjian"
        for event in game.events
    )


def test_jiedao_black_trick_filters_dynamic_weimu_and_apply_rejected() -> None:
    # Dynamic Weimu: p1's all-black equipment is the only source of the filter.
    game = _game(
        first_player_id="p2",
        players=3,
        assignments={"p1": "wangyuanji", "p2": "zhugezhan", "p3": "shamoke"},
    )
    _set_equip(game, "p1", "armor", "sgs_armor_baguazhen")  # black armor -> dynamic Weimu
    _set_equip(game, "p1", "weapon", "sgs_weapon_qinggangjian")  # black weapon -> still all black Weimu
    _set_equip(game, "p3", "weapon", "sgs_weapon_zhugeliannu")  # p3 has weapon

    _take(game, "proceed_prepare")
    _take(game, "proceed_judgment")
    _take(game, "proceed_draw")

    black_jiedao = next(
        c.instance_id for c in game.state.cards
        if c.card_key == "sgs_trick_jiedaosharen" and c.color == "黑"
    )
    # Give p2 black Jiedao
    game._state = game.state.move_card(black_jiedao, ZoneRef.hand("p2"))

    legal = game.legal_actions()
    jiedao_targets = {
        action.target_ids[0]
        for action in legal
        if action.payload.get("operation") == "use_jiedao"
    }
    # p1 has Weimu -> cannot be chosen as first target of black Jiedao!
    assert "p1" not in jiedao_targets
    assert "p3" in jiedao_targets

    # Forged apply check: directly submitting stale/forged action targeting p1 is rejected by apply
    forged_action = LegalAction(
        action_type=ActionType.USE_CARD,
        actor_id="p2",
        card_instance_id=black_jiedao,
        target_ids=("p1",),
        payload={
            "operation": "use_jiedao",
            "card_key": "sgs_trick_jiedaosharen",
            "card_name": "借刀杀人",
            "second_target_id": "p3",
        },
    )
    with pytest.raises(InvalidActionError, match="第一目标不能被该锦囊指定"):
        game.apply_jiedao_use(
            game.state,
            ActionContext(mode="standard_duel", phase="play", actor_id="p2"),
            forged_action,
            game.formal_registry.adapter_for("sgs_trick_jiedaosharen"),
        )


def test_jiedao_black_trick_filters_static_weimu_and_normal_target_remains_legal() -> None:
    game = _skill_game(
        first_player_id="p2",
        players=3,
        skill_assignments={"p1": ("sgs_skill_weimu",)},
    )
    _set_equip(game, "p1", "weapon", "sgs_weapon_qinggangjian")
    _set_equip(game, "p3", "weapon", "sgs_weapon_zhugeliannu")

    _take(game, "proceed_prepare")
    _take(game, "proceed_judgment")
    _take(game, "proceed_draw")
    jiedao_id = _set_hand_keys(game, "p2", ("sgs_trick_jiedaosharen",))[0]

    legal = game.legal_actions()
    jiedao_actions = [
        action
        for action in legal
        if action.payload.get("operation") == "use_jiedao"
    ]
    assert jiedao_actions
    assert {action.target_ids[0] for action in jiedao_actions} == {"p3"}

    forged_action = LegalAction(
        action_type=ActionType.USE_CARD,
        actor_id="p2",
        card_instance_id=jiedao_id,
        target_ids=("p1",),
        payload={
            "operation": "use_jiedao",
            "card_key": "sgs_trick_jiedaosharen",
            "card_name": "借刀杀人",
            "second_target_id": "p3",
        },
    )
    with pytest.raises(InvalidActionError, match="第一目标不能被该锦囊指定"):
        game.apply_jiedao_use(
            game.state,
            ActionContext(mode=game.mode_id, phase="play", actor_id="p2"),
            forged_action,
            game.formal_registry.adapter_for("sgs_trick_jiedaosharen"),
        )


def test_jiedao_weapon_transfer_loss_ledger_and_mingzhe_revocation() -> None:
    game = _game(first_player_id="p2", players=3)
    # p1 has unique red weapon (Zhugeliannu red diamonds)
    red_weapon_id = next(
        c.instance_id for c in game.state.cards
        if c.card_key == "sgs_weapon_zhugeliannu" and c.color == "红"
    )
    game._state = game.state.move_card(red_weapon_id, ZoneRef.equipment("p1", "weapon"))
    game._reconcile_qianchong_for_all(game.state)
    assert game.skill_runtime.has_skill("p1", "sgs_skill_mingzhe")

    _take(game, "proceed_prepare")
    _take(game, "proceed_judgment")
    _take(game, "proceed_draw")

    jiedao_id = next(
        c.instance_id for c in game.state.cards
        if c.card_key == "sgs_trick_jiedaosharen"
    )
    game._state = game.state.move_card(jiedao_id, ZoneRef.hand("p2"))

    _take(game, "use_jiedao", target_ids=("p1",), second_target_id="p3")
    _take(game, "pass_trick_response")
    _take(game, "pass_trick_response")
    _take(game, "pass_trick_response")
    # p1 has no slash in hand -> weapon transferred automatically to p2

    # p1 equipment is now empty -> Mingzhe revoked
    assert len(game.state.card_ids_in(ZoneRef.equipment("p1", "weapon"))) == 0
    assert not game.skill_runtime.has_skill("p1", "sgs_skill_mingzhe")
    # Shangjian loss ledger recorded 1 loss for p1
    assert game.turn_loss_ledger.count_losses_this_turn("p1") == 1
    assert game.turn_loss_ledger.entries[-1].to_dict() == {
        "losing_player_id": "p1",
        "card_instance_id": red_weapon_id,
        "source_zone": "equipment:weapon",
        "destination_zone": "hand",
        "semantic_reason": "jiedaosharen_weapon_gain",
        "event_sequence": game.turn_loss_ledger.entries[-1].event_sequence,
        "counts_as_loss": True,
    }
    # Mingzhe did NOT trigger because Mingzhe was revoked upon unique red equipment leaving
    mingzhe_events = [
        e for e in game.events
        if e.payload.get("skill_id") == "sgs_skill_mingzhe"
    ]
    assert len(mingzhe_events) == 0


def test_shunshou_equipment_steal_records_source_destination_and_revokes_mingzhe() -> None:
    game = _game(first_player_id="p2", players=2)
    _set_equip(game, "p1", "weapon", "sgs_weapon_zhuqueyushan", color="红")
    assert game.skill_runtime.has_skill("p1", "sgs_skill_mingzhe")

    _take(game, "proceed_prepare")
    _take(game, "proceed_judgment")
    _take(game, "proceed_draw")
    shunshou_id = _set_hand_keys(
        game, "p2", ("sgs_trick_shunshouqianyang",)
    )[0]
    _take(game, "use_shunshou", target_ids=("p1",))
    _take(game, "pass_trick_response")
    _take(game, "pass_trick_response")
    _take(game, "choose_target_zone_card", zone="equipment:weapon")

    assert game.state.location_of(shunshou_id) == DISCARD_PILE
    assert len(game.state.card_ids_in(ZoneRef.equipment("p1", "weapon"))) == 0
    assert not game.skill_runtime.has_skill("p1", "sgs_skill_mingzhe")
    entry = game.turn_loss_ledger.entries[-1]
    assert entry.losing_player_id == "p1"
    assert entry.source_zone == "equipment:weapon"
    assert entry.destination_zone == "hand"
    assert entry.semantic_reason == "shunshouqianyang_gain"
    assert entry.counts_as_loss is True
    assert not any(
        event.payload.get("skill_id") == "sgs_skill_mingzhe"
        for event in game.events
    )


def test_equipment_replacement_records_only_old_equipment_as_shangjian_loss() -> None:
    game = _game(first_player_id="p1", players=2)
    red_weapon_keys = [
        card.card_key
        for card in game.state.cards
        if card.card_type == "装备牌"
        and card.equipment_slot == "weapon"
        and card.color == "红"
        and game.state.location_of(card.instance_id) in (DRAW_PILE, DISCARD_PILE)
    ]
    assert len(set(red_weapon_keys)) >= 2
    old_key, new_key = tuple(dict.fromkeys(red_weapon_keys))[:2]
    old_id = _set_equip(game, "p1", "weapon", old_key, color="红")
    assert game.skill_runtime.has_skill("p1", "sgs_skill_mingzhe")

    _take(game, "proceed_prepare")
    _take(game, "proceed_judgment")
    _take(game, "proceed_draw")
    _set_hand_keys(game, "p1", (new_key,), color="红")
    _take(game, "use_weapon", card_key=new_key)

    assert game.state.location_of(old_id) == DISCARD_PILE
    new_id = next(
        card.instance_id
        for card in game.state.cards
        if card.card_key == new_key
    )
    assert game.state.location_of(new_id) == ZoneRef.equipment("p1", "weapon")
    assert game.turn_loss_ledger.count_losses_this_turn("p1") == 1
    assert any(
        entry.card_instance_id == old_id
        and entry.source_zone == "equipment:weapon"
        and entry.destination_zone == "discard"
        and entry.semantic_reason == "equip_replaced"
        and entry.counts_as_loss
        for entry in game.turn_loss_ledger.entries
    )
    assert any(
        entry.card_instance_id == new_id and not entry.counts_as_loss
        for entry in game.turn_loss_ledger.entries
    )
    old_authority = [
        entry
        for entry in game.card_movement_authority
        if entry.card_instance_id == old_id
    ]
    new_authority = [
        entry
        for entry in game.card_movement_authority
        if entry.card_instance_id == new_id
    ]
    assert len(old_authority) == 1
    assert len(new_authority) == 2
    assert old_authority[0].counts_as_shangjian_loss is True
    assert not any(entry.counts_as_shangjian_loss for entry in new_authority)
    assert {
        old_authority[0].root_operation_identity,
        *(entry.root_operation_identity for entry in new_authority),
    } == {old_authority[0].root_operation_identity}
    assert game.skill_runtime.has_skill("p1", "sgs_skill_mingzhe")


def test_qilin_discard_unique_red_mount_revokes_mingzhe_and_remaining_red_triggers() -> None:
    # Part 1: unique red mount lost -> revoked -> 0 triggers
    game = _game(first_player_id="p2", players=2)
    _set_equip(game, "p2", "weapon", "sgs_weapon_qilingong")
    # p1 has unique red defense horse
    red_horse_key = next(
        c.card_key for c in game.state.cards
        if c.card_type == "装备牌" and c.equipment_slot in ("defense_horse", "attack_horse") and c.color == "红"
    )
    red_horse_id = _set_equip(
        game, "p1", "defense_horse", red_horse_key, color="红"
    )
    red_horse_slot = next(
        card.equipment_slot
        for card in game.state.cards
        if card.instance_id == red_horse_id
    )
    assert game.skill_runtime.has_skill("p1", "sgs_skill_mingzhe")

    _advance_to_play(game)
    sha_id = _set_hand_keys(game, "p2", ("sgs_basic_sha",))[0]
    _take(game, "use_slash", target_ids=("p1",))
    _take(game, "pass_slash_response")
    # p2 chooses to discard p1's mount via Qilingong
    _take(game, "weapon_discard_mount", card_instance_id=red_horse_id)

    assert game.turn_loss_ledger.count_losses_this_turn("p1") == 1
    assert game.turn_loss_ledger.entries[-1].source_zone == f"equipment:{red_horse_slot}"
    assert game.turn_loss_ledger.entries[-1].destination_zone == "discard"
    assert game.turn_loss_ledger.entries[-1].semantic_reason == "qilingong_mount_discard"
    assert not game.skill_runtime.has_skill("p1", "sgs_skill_mingzhe")
    mingzhe_events = [
        e for e in game.events
        if e.payload.get("skill_id") == "sgs_skill_mingzhe"
    ]
    assert len(mingzhe_events) == 0

    # Part 2: 2 red equipments, 1 discarded -> remaining still all-red -> Mingzhe triggers!
    game2 = _game(first_player_id="p2", players=2)
    _set_equip(game2, "p2", "weapon", "sgs_weapon_qilingong")
    _set_equip(game2, "p1", "defense_horse", red_horse_key, color="红")
    # p1 also has red weapon (Zhugeliannu red)
    red_weapon_id = next(
        c.instance_id for c in game2.state.cards
        if c.card_key == "sgs_weapon_zhugeliannu" and c.color == "红"
    )
    game2._state = game2.state.move_card(red_weapon_id, ZoneRef.equipment("p1", "weapon"))
    game2._reconcile_qianchong_for_all(game2.state)
    assert game2.skill_runtime.has_skill("p1", "sgs_skill_mingzhe")

    _advance_to_play(game2)
    _set_hand_keys(game2, "p2", ("sgs_basic_sha",))
    _take(game2, "use_slash", target_ids=("p1",))
    _take(game2, "pass_slash_response")
    # p2 discards p1 mount
    _take(game2, "weapon_discard_mount", card_instance_id=red_horse_id)

    # Remaining equipment is red weapon -> Mingzhe is STILL active!
    assert game2.skill_runtime.has_skill("p1", "sgs_skill_mingzhe")
    assert game2.turn_loss_ledger.entries[-1].source_zone == f"equipment:{red_horse_slot}"
    assert game2.turn_loss_ledger.entries[-1].destination_zone == "discard"
    # Mingzhe decision window opened for p1!
    assert game2.skill_pending is not None
    assert game2.skill_pending.skill_id == "sgs_skill_mingzhe"
    assert game2.skill_pending.actor_id == "p1"
    hand_before_mingzhe = len(game2.state.card_ids_in(ZoneRef.hand("p1")))
    _take(game2, "activate_skill")
    assert len(game2.state.card_ids_in(ZoneRef.hand("p1"))) == hand_before_mingzhe + 1


def test_qianchong_basic_permission_allows_second_wine_use_and_ordinary_rejected() -> None:
    # Wang Yuanji with Qianchong basic permission
    game = _game(first_player_id="p1", players=2)
    _advance_to_play(game)  # chooses 'basic' for Qianchong

    wine_keys = [c.card_key for c in game.state.cards if c.card_key == "sgs_basic_jiu"]
    _set_hand_keys(game, "p1", (wine_keys[0], wine_keys[1]))

    # Use first Wine
    _take(game, "use_wine_buff")
    assert game.runtime.wine_buff_owner_id == "p1"

    # Second Wine is present in legal actions!
    legal = game.legal_actions()
    wine_actions = [a for a in legal if a.payload.get("operation") == "use_wine_buff"]
    assert len(wine_actions) == 1

    # Uses second Wine successfully
    _take(game, "use_wine_buff")
    assert game.turn_loss_ledger.count_losses_this_turn("p1") == 2

    # Ordinary player without permission
    game2 = _game(first_player_id="p2", players=2, assignments={"p2": "zhugezhan"})
    _advance_to_play(game2)
    wine_ids = _set_hand_keys(game2, "p2", (wine_keys[0], wine_keys[1]))
    _take(game2, "use_wine_buff")
    assert game2.runtime.wine_buff_owner_id == "p2"

    legal2 = game2.legal_actions()
    wine_actions2 = [a for a in legal2 if a.payload.get("operation") == "use_wine_buff"]
    assert len(wine_actions2) == 0

    forged_wine_action = LegalAction(
        action_type=ActionType.USE_CARD,
        actor_id="p2",
        card_instance_id=wine_ids[1],
        target_ids=("p2",),
        payload={"operation": "use_wine_buff", "card_key": "sgs_basic_jiu", "card_name": "酒"},
    )
    with pytest.raises(InvalidActionError, match="出牌阶段【酒】强化用途每出牌阶段限一次"):
        game2.apply_wine_buff(
            game2.state,
            ActionContext(mode="standard_duel", phase="play", actor_id="p2"),
            forged_wine_action,
            game2.formal_registry.adapter_for("sgs_basic_jiu"),
        )


def test_qianchong_reconcile_same_state_has_bounded_grant_history() -> None:
    game = _game(first_player_id="p2")
    _set_equip(game, "p1", "armor", "sgs_armor_baguazhen")
    before = tuple(
        grant.to_dict()
        for grant in game.skill_runtime.dynamic_grants["p1"]
    )

    for _ in range(100):
        game._reconcile_qianchong_for_all(game.state)

    after = tuple(
        grant.to_dict()
        for grant in game.skill_runtime.dynamic_grants["p1"]
    )
    assert after == before
    assert len(after) == 1


def test_qianchong_permission_failure_rolls_back_authority_and_pending(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    game = _game(first_player_id="p1", players=2)
    _take(game, "proceed_prepare")
    _take(game, "proceed_judgment")
    _take(game, "proceed_draw")
    assert game.skill_pending is not None
    assert game.skill_pending.skill_id == "sgs_skill_qianchong"
    choice = next(
        action
        for action in game.legal_actions()
        if action.payload.get("operation") == "qianchong_choice"
        and action.payload.get("chosen_card_type") == "basic"
    )
    before = game.execution_snapshot

    def explode(*args: object, **kwargs: object) -> None:
        raise RuntimeError("g3 Qianchong permission rollback sentinel")

    monkeypatch.setattr(game, "_open_next_queued_skill_decision", explode)
    with pytest.raises(RuntimeError, match="g3 Qianchong permission rollback sentinel"):
        _step(game, choice)
    assert game.execution_snapshot == before


def _open_multiplayer_zuilun_pending() -> ProductionBasicCardBatch:
    game = _game(
        first_player_id="p2",
        players=3,
        assignments={"p1": "wangyuanji", "p2": "zhugezhan"},
        player_hp=(3, 3, 4),
        player_max_hp=(3, 3, 4),
    )
    _take(game, "proceed_prepare")
    _take(game, "proceed_judgment")
    _take(game, "proceed_draw")
    _set_hand_keys(game, "p1", ("sgs_basic_shan",))
    _set_hand_keys(game, "p2", ("sgs_trick_guohechaiqiao",))
    _take(game, "use_guohe", target_ids=("p1",))
    _take(game, "pass_trick_response")
    _take(game, "pass_trick_response")
    _take(game, "pass_trick_response")
    _take(game, "choose_target_zone_card", zone="hand")
    _take(game, "end_play_phase")
    assert game.skill_pending is not None
    assert game.skill_pending.skill_id == "sgs_skill_zuilun"
    return game


def test_end_dispatcher_resume_failure_rolls_back_cursor_pending_and_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    game = _open_multiplayer_zuilun_pending()
    pass_action = next(
        action
        for action in game.legal_actions()
        if action.payload.get("operation") == "pass_skill"
    )
    before = game.execution_snapshot
    original = game._run_end_phase_dispatcher

    def explode(state: object) -> object:
        original(state)
        raise RuntimeError("g3 end dispatcher rollback sentinel")

    monkeypatch.setattr(game, "_run_end_phase_dispatcher", explode)
    with pytest.raises(RuntimeError, match="g3 end dispatcher rollback sentinel"):
        _step(game, pass_action)
    assert game.execution_snapshot == before


def test_equipment_movement_ledger_and_reconcile_failure_rolls_back_atomically(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    game = _game(first_player_id="p2", players=2)
    _set_equip(game, "p1", "weapon", "sgs_weapon_zhuqueyushan", color="红")
    _take(game, "proceed_prepare")
    _take(game, "proceed_judgment")
    _take(game, "proceed_draw")
    _set_hand_keys(game, "p2", ("sgs_trick_guohechaiqiao",))
    _take(game, "use_guohe", target_ids=("p1",))
    _take(game, "pass_trick_response")
    _take(game, "pass_trick_response")
    choose = next(
        action
        for action in game.legal_actions()
        if action.payload.get("operation") == "choose_target_zone_card"
        and action.payload.get("zone") == "equipment:weapon"
    )
    before = game.execution_snapshot
    original = game._record_authoritative_card_movement

    def explode(*args: object, **kwargs: object) -> object:
        result = original(*args, **kwargs)
        source_zone = kwargs.get("source_zone")
        if getattr(source_zone, "kind", None) is ZoneKind.EQUIPMENT:
            raise RuntimeError("g3 equipment movement rollback sentinel")
        return result

    monkeypatch.setattr(game, "_record_authoritative_card_movement", explode)
    with pytest.raises(RuntimeError, match="g3 equipment movement rollback sentinel"):
        _step(game, choose)
    assert game.execution_snapshot == before


def test_discard_phase_movement_authority_rolls_back_with_failed_end_entry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    game = _game(
        first_player_id="p1",
        player_hp=(3, 4),
        initial_hand_count=4,
    )
    _advance_to_play(game)
    assert len(game.state.card_ids_in(ZoneRef.hand("p1"))) == 6
    _take(game, "end_play_phase")
    for _ in range(3):
        _take(game, "select_discard_card")
    submit = next(
        action
        for action in game.legal_actions()
        if action.payload.get("operation") == "discard_phase_submit"
    )
    before = game.execution_snapshot
    authority_before = game.card_movement_authority

    def explode(*args: object, **kwargs: object) -> object:
        del args, kwargs
        raise RuntimeError("g3 discard movement rollback sentinel")

    monkeypatch.setattr(game, "_enter_end_phase", explode)
    with pytest.raises(RuntimeError, match="g3 discard movement rollback sentinel"):
        _step(game, submit)
    assert game.execution_snapshot == before
    assert game.card_movement_authority == authority_before


def test_shangjian_draw_failure_rolls_back_end_dispatcher_and_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    game = _game(first_player_id="p2", players=2)
    _take(game, "proceed_prepare")
    _take(game, "proceed_judgment")
    _take(game, "proceed_draw")
    _set_hand_keys(game, "p1", ("sgs_basic_shan",))
    _set_hand_keys(game, "p2", ("sgs_trick_guohechaiqiao",))
    _take(game, "use_guohe", target_ids=("p1",))
    _take(game, "pass_trick_response")
    _take(game, "pass_trick_response")
    _take(game, "choose_target_zone_card", zone="hand")
    assert game.turn_loss_ledger.count_losses_this_turn("p1") == 1
    end_action = next(
        action
        for action in game.legal_actions()
        if action.payload.get("operation") == "end_play_phase"
    )
    before = game.execution_snapshot
    original = game.draw_cards_for_skill

    def explode(*args: object, **kwargs: object) -> object:
        original(*args, **kwargs)
        raise RuntimeError("g3 Shangjian draw rollback sentinel")

    monkeypatch.setattr(game, "draw_cards_for_skill", explode)
    with pytest.raises(RuntimeError, match="g3 Shangjian draw rollback sentinel"):
        _step(game, end_action)
    assert game.execution_snapshot == before


# ---------------------------------------------------------------------------
# G3-CLOSURE-002  明哲 same-root per-card trigger identity (#0..#N-1)
#
# 证据分类（本轮修正后）：
#   * REAL SIGNED PRODUCTION PROOF（主证明，N=2）：真实已签名链
#     【借刀杀人】→ 王元姬被迫出【杀】→ 目标出【闪】→【贯石斧】强制命中
#     → 已签名 select_discard_two ×2 → discard_two_submit，同一 root 一次
#     批量失去两张红牌触发明哲 #0/#1，全部经已签名 ACTIVATE/PASS 消费。
#     证明：#0/#1 全部处理前贯石斧伤害未发生；全部完成后原【杀】伤害
#     恰好结算一次；stale/wrong 消费身份失败关闭；transaction rollback
#     仍正确（含父 continuation 保留）。见 test_guanshi_mingzhe_* 系列。
#   * INTERNAL CONTRACT SCALING PROOF（内部合同层扩展证明，非 production
#     签名路径）：_commit_same_root_batch_discard 直接调用内部 seam
#     （_commit_authoritative_card_movements + 手工构造 GameEvent +
#     _discover_production_skill_triggers），仅覆盖 N>=3 的 trigger_index
#     扩展性与合同级消费行为，不得称为 production/real/signed 路径证明。
#   * transaction failure proof：见本节末尾的 CLOSURE-003 测试。
#
# 历史更正（保留为事实记录）：本轮之前的分类说明曾声称“当前仓库没有任何
# 已签名 production action 能在‘同一 root 且回合外’让明哲持有者同时失去
# N>=2 张红牌”，并据此把内部 seam 证明当作主证明；上一轮甚至把手工构造
# GameEvent / 直接调用内部函数的证明错误报告为“寒冰剑/麒麟弓真实
# production path”。该声明与报告均为错误：【贯石斧】强制命中一次弃两牌
# 即是真实已签名 N=2 路径；且当时只验证了 trigger 创建，从未验证
# consumption——该路径 consumption 半段曾真实存在 stale-window 死锁
# （discovery 后伤害结算 bump revision 使窗口过期），本轮已通过
# continuation/pause-resume 生产修复解决（见 production_batch.py 中
# apply_discard_two_submit 的 G3-CLOSURE-002 修复注释）。
# ---------------------------------------------------------------------------

# ...........................................................................
# REAL SIGNED PRODUCTION PROOF（主证明，N=2，真实已签名链）
# ...........................................................................


def _guanshi_mingzhe_pause_chain() -> tuple[ProductionBasicCardBatch, tuple[str, str]]:
    """真实已签名 production 链，停在明哲 #0/#1 决策窗口（伤害尚未结算）。

    链：p2【借刀杀人】(target=p1, second=p3) → 王元姬(p1) 被迫出【杀】
    → p3 出【闪】→ p1【贯石斧】强制命中 → 已签名 select_discard_two ×2
    （两张红色非【杀】非装备实体牌）→ discard_two_submit。两牌在同一
    root 一次批量失去，discovery 打开明哲 #0/#1 决策窗口，父级贯石斧
    伤害挂起为 card continuation（pause/resume 修复后的冻结时序）。
    全程只使用 legal_actions → action_id → step，不触碰任何内部 seam。
    """
    game = _game(first_player_id="p2", players=3)
    _set_equip(game, "p1", "weapon", "sgs_weapon_guanshifu", color="红")
    _set_hand_keys(game, "p1", ("sgs_basic_sha",), color="黑")
    state = game.state
    red_candidates = [
        card
        for card in state.cards
        if card.color == "红"
        and card.card_type != "装备牌"
        and card.card_key != "sgs_basic_sha"
        and state.location_of(card.instance_id) in (DRAW_PILE, DISCARD_PILE)
    ]
    red_ids = (red_candidates[0].instance_id, red_candidates[1].instance_id)
    game._state = game.state.move_cards(
        {card_id: ZoneRef.hand("p1") for card_id in red_ids}
    )
    game.state.assert_card_conservation()
    _set_hand_keys(game, "p3", ("sgs_basic_shan",))
    _set_hand_keys(game, "p2", ("sgs_trick_jiedaosharen",))

    _take(game, "proceed_prepare")
    _take(game, "proceed_judgment")
    _take(game, "proceed_draw")
    _take(game, "use_jiedao", target_ids=("p1",), second_target_id="p3")
    while any(
        action.payload.get("operation") == "pass_trick_response"
        for action in game.legal_actions()
    ):
        _take(game, "pass_trick_response")
    _take(game, "choose_borrowed_sword_slash")
    _take(game, "play_dodge")
    _take(game, "weapon_force_hit")
    _take(game, "select_discard_two", card_instance_id=red_ids[0])
    _take(game, "select_discard_two", card_instance_id=red_ids[1])
    _take(game, "discard_two_submit")
    return game, red_ids


def _damage_events(game: ProductionBasicCardBatch) -> tuple[GameEvent, ...]:
    return tuple(
        event for event in game.events if event.event_type is EventType.DAMAGE
    )


def _mingzhe_draw_events(game: ProductionBasicCardBatch) -> tuple[GameEvent, ...]:
    return tuple(
        event
        for event in game.events
        if event.event_type is EventType.CARD_MOVED
        and event.payload.get("reason") == "sgs_skill_mingzhe"
    )


def _assert_guanshi_mingzhe_pause(
    game: ProductionBasicCardBatch,
    red_ids: tuple[str, str],
    p3_max_hp: int,
) -> tuple[object, object]:
    """暂停态证明：#0/#1 同 root 触发身份完整、窗口新鲜、伤害尚未发生。"""
    pending = game.skill_pending
    queued = tuple(game._skill_trigger_queue)
    assert pending is not None
    assert pending.skill_id == "sgs_skill_mingzhe"
    assert pending.actor_id == "p1"
    assert pending.trigger_index == 0
    assert pending.trigger_event_type == EventType.CARD_DISCARDED.value
    assert len(queued) == 1
    assert queued[0].skill_id == "sgs_skill_mingzhe"
    assert queued[0].actor_id == "p1"
    assert queued[0].trigger_index == 1
    assert queued[0].trigger_event_type == EventType.CARD_DISCARDED.value
    # 同一 root、两张不同红牌；触发顺序由权威事件序决定（非 set/dict 迭代序）
    assert pending.card_instance_id == red_ids[0]
    assert queued[0].card_instance_id == red_ids[1]
    assert pending.card_instance_id != queued[0].card_instance_id
    assert pending.trigger_event_sequence < queued[0].trigger_event_sequence
    roots = {
        entry.root_operation_identity
        for entry in game.card_movement_authority
        if entry.card_instance_id in red_ids
    }
    assert len(roots) == 1
    # 决策窗口新鲜：pause/resume 修复后 discovery 是该 step 最后一次 mutation
    assert pending.window_revision == game.state.revision
    # 消费身份 / 决策窗口身份（#0/#1 各不相同且尚未消费）
    assert pending.consumption_key == (
        str(pending.trigger_event_sequence),
        "p1",
        "sgs_skill_mingzhe",
        "0",
    )
    assert queued[0].consumption_key == (
        str(queued[0].trigger_event_sequence),
        "p1",
        "sgs_skill_mingzhe",
        "1",
    )
    assert pending.decision_window_id.endswith(":0")
    assert queued[0].decision_window_id.endswith(":1")
    assert pending.consumption_key not in game._skill_consumed_triggers
    assert queued[0].consumption_key not in game._skill_consumed_triggers
    # REQ-1：#0/#1 全部处理前，贯石斧伤害尚未发生
    assert game.state.players_by_id["p3"].hp == p3_max_hp
    assert _damage_events(game) == ()
    assert game.phase is ProductionPhase.WEAPON_DISCARD_TWO
    # 父级贯石斧伤害 continuation 已挂起（单层）
    continuation = game._pending_card_continuation
    assert continuation is not None
    assert continuation.owner_id == "p1"
    assert continuation.target_ids == ("p3",)
    assert continuation.card_instance_id is None
    assert continuation.expected_phase == ProductionPhase.WEAPON_DISCARD_TWO.value
    # 两张红牌已进入弃牌堆（actual card-loss 已提交）
    for card_id in red_ids:
        assert game.state.location_of(card_id) == DISCARD_PILE
    # 本回合 p1 共失去 3 张牌：被借刀打出的【杀】 + 贯石斧代价两张红牌
    assert game.turn_loss_ledger.count_losses_this_turn("p1") == 3
    return pending, queued[0]


def _assert_guanshi_damage_resolved(
    game: ProductionBasicCardBatch,
    *,
    expected_draws: int,
    hand_at_pause: int,
    p3_max_hp: int,
) -> None:
    """REQ-2：全部触发消费完成后，原【杀】伤害恰好结算一次，无重复/遗漏。"""
    assert game.skill_pending is None
    assert not game._skill_trigger_queue
    # 父 continuation 已消费且不会再次触发（无 lost/duplicate continuation）
    assert game._pending_card_continuation is None
    damage = _damage_events(game)
    assert len(damage) == 1
    assert damage[0].payload.get("weapon_effect") == "guanshifu_force_hit"
    assert damage[0].card_user == "p1"
    assert game.state.players_by_id["p3"].hp == p3_max_hp - 1
    assert game.phase is ProductionPhase.PLAY
    hand = len(game.state.card_ids_in(ZoneRef.hand("p1")))
    assert hand == hand_at_pause + expected_draws
    # 明哲摸牌事件数 == ACTIVATE 次数（无重复触发）
    assert len(_mingzhe_draw_events(game)) == expected_draws
    game.state.assert_card_conservation()


def test_guanshi_mingzhe_real_signed_chain_trigger_identity_and_pause() -> None:
    """REAL SIGNED PRODUCTION PROOF 主证明（N=2，真实已签名链）。

    全程仅使用已签名 production action（legal_actions → action_id →
    step），不触碰任何内部 seam：证明同一 root 一次批量失去两张红牌时，
    明哲在真实 production 路径上发现 #0/#1 两个触发，身份完整
    （owner/skill/root/卡牌实体/源事件/trigger_index/decision_window_id/
    consumption_key），且父级贯石斧伤害在全部触发处理前暂停（未发生）。
    """
    game, red_ids = _guanshi_mingzhe_pause_chain()
    p3_max_hp = game.state.players_by_id["p3"].hp
    pending, _queued_first = _assert_guanshi_mingzhe_pause(
        game, red_ids, p3_max_hp
    )
    # 决策动作经真实枚举暴露（已签名、绑定当前窗口与当前消费身份）
    activate = next(
        action
        for action in game.legal_actions()
        if action.payload.get("operation") == "activate_skill"
    )
    assert activate.skill_id == "sgs_skill_mingzhe"
    assert activate.actor_id == "p1"
    assert tuple(activate.payload.get("consumption_key") or ()) == (
        pending.consumption_key
    )
    pass_action = next(
        action
        for action in game.legal_actions()
        if action.payload.get("operation") == "pass_skill"
    )
    assert pass_action.skill_id == "sgs_skill_mingzhe"
    assert tuple(pass_action.payload.get("consumption_key") or ()) == (
        pending.consumption_key
    )


def test_guanshi_mingzhe_decision_combo_activate_pass_draws_one() -> None:
    """组合 A：#0 ACTIVATE / #1 PASS → 恰好摸 1 张，伤害恰好一次。"""
    game, red_ids = _guanshi_mingzhe_pause_chain()
    p3_max_hp = game.state.players_by_id["p3"].hp
    hand_at_pause = len(game.state.card_ids_in(ZoneRef.hand("p1")))
    _assert_guanshi_mingzhe_pause(game, red_ids, p3_max_hp)

    _take(game, "activate_skill", skill_id="sgs_skill_mingzhe")
    # #0 已消费、#1 待决：伤害仍未发生，#1 窗口推进且新鲜
    pending = game.skill_pending
    assert pending is not None
    assert pending.trigger_index == 1
    assert pending.window_revision == game.state.revision
    assert _damage_events(game) == ()
    assert game.state.players_by_id["p3"].hp == p3_max_hp
    assert game.phase is ProductionPhase.WEAPON_DISCARD_TWO
    assert game._pending_card_continuation is not None
    assert len(_mingzhe_draw_events(game)) == 1

    _take(game, "pass_skill", skill_id="sgs_skill_mingzhe")
    _assert_guanshi_damage_resolved(
        game, expected_draws=1, hand_at_pause=hand_at_pause, p3_max_hp=p3_max_hp
    )


def test_guanshi_mingzhe_decision_combo_pass_activate_draws_one() -> None:
    """组合 B：#0 PASS / #1 ACTIVATE → 恰好摸 1 张，伤害恰好一次。"""
    game, red_ids = _guanshi_mingzhe_pause_chain()
    p3_max_hp = game.state.players_by_id["p3"].hp
    hand_at_pause = len(game.state.card_ids_in(ZoneRef.hand("p1")))
    _assert_guanshi_mingzhe_pause(game, red_ids, p3_max_hp)

    _take(game, "pass_skill", skill_id="sgs_skill_mingzhe")
    pending = game.skill_pending
    assert pending is not None
    assert pending.trigger_index == 1
    assert pending.window_revision == game.state.revision
    assert _damage_events(game) == ()
    assert game.state.players_by_id["p3"].hp == p3_max_hp
    assert game.phase is ProductionPhase.WEAPON_DISCARD_TWO
    assert game._pending_card_continuation is not None
    assert _mingzhe_draw_events(game) == ()

    _take(game, "activate_skill", skill_id="sgs_skill_mingzhe")
    _assert_guanshi_damage_resolved(
        game, expected_draws=1, hand_at_pause=hand_at_pause, p3_max_hp=p3_max_hp
    )


def test_guanshi_mingzhe_decision_combo_both_activate_draws_two() -> None:
    """组合 C：#0/#1 均 ACTIVATE → 恰好摸 2 张，伤害恰好一次。"""
    game, red_ids = _guanshi_mingzhe_pause_chain()
    p3_max_hp = game.state.players_by_id["p3"].hp
    hand_at_pause = len(game.state.card_ids_in(ZoneRef.hand("p1")))
    _assert_guanshi_mingzhe_pause(game, red_ids, p3_max_hp)

    _take(game, "activate_skill", skill_id="sgs_skill_mingzhe")
    pending = game.skill_pending
    assert pending is not None
    assert pending.trigger_index == 1
    assert _damage_events(game) == ()
    assert game.state.players_by_id["p3"].hp == p3_max_hp
    assert len(_mingzhe_draw_events(game)) == 1

    _take(game, "activate_skill", skill_id="sgs_skill_mingzhe")
    _assert_guanshi_damage_resolved(
        game, expected_draws=2, hand_at_pause=hand_at_pause, p3_max_hp=p3_max_hp
    )


def test_guanshi_mingzhe_decision_combo_both_pass_draws_nothing() -> None:
    """组合 D：#0/#1 均 PASS → 不摸牌，伤害仍恰好结算一次。"""
    game, red_ids = _guanshi_mingzhe_pause_chain()
    p3_max_hp = game.state.players_by_id["p3"].hp
    hand_at_pause = len(game.state.card_ids_in(ZoneRef.hand("p1")))
    _assert_guanshi_mingzhe_pause(game, red_ids, p3_max_hp)

    _take(game, "pass_skill", skill_id="sgs_skill_mingzhe")
    pending = game.skill_pending
    assert pending is not None
    assert pending.trigger_index == 1
    assert _damage_events(game) == ()
    assert game.state.players_by_id["p3"].hp == p3_max_hp

    _take(game, "pass_skill", skill_id="sgs_skill_mingzhe")
    _assert_guanshi_damage_resolved(
        game, expected_draws=0, hand_at_pause=hand_at_pause, p3_max_hp=p3_max_hp
    )


_TRIGGER_IDENTITY_FIELDS = (
    "decision_window_id",
    "trigger_event_sequence",
    "trigger_event_type",
    "trigger_index",
    "consumption_key",
    "continuation_identity",
    "owner_id",
    "actor_id",
    "payload_skill_id",
    "action_skill_id",
    "expected_revision",
    "skill_version",
    "skill_profile_identity",
    "card_instance_id",
)


def _forge_pending_skill_identity(action: LegalAction, field_name: str) -> LegalAction:
    """Independently tamper one signed field while preserving every redundant peer."""

    payload = dict(action.payload)
    if field_name == "decision_window_id":
        payload[field_name] = f"{payload[field_name]}:forged"
    elif field_name == "trigger_event_sequence":
        payload[field_name] = int(payload[field_name]) + 1000
    elif field_name == "trigger_event_type":
        payload[field_name] = "forged_trigger_type"
    elif field_name == "trigger_index":
        payload[field_name] = int(payload[field_name]) + 1
    elif field_name == "consumption_key":
        forged_key = list(payload[field_name])
        forged_key[-1] = str(int(forged_key[-1]) + 1)
        payload[field_name] = forged_key
    elif field_name == "continuation_identity":
        payload[field_name] = "0" * 64
    elif field_name == "owner_id":
        payload[field_name] = "p2"
    elif field_name == "actor_id":
        return replace(action, actor_id="p2")
    elif field_name == "payload_skill_id":
        payload["skill_id"] = "sgs_skill_shangjian"
    elif field_name == "action_skill_id":
        return replace(action, skill_id="sgs_skill_shangjian")
    elif field_name == "expected_revision":
        payload[field_name] = int(payload[field_name]) + 1
    elif field_name == "skill_version":
        payload[field_name] = f"{payload[field_name]}-forged"
    elif field_name == "skill_profile_identity":
        payload[field_name] = "0" * 64
    elif field_name == "card_instance_id":
        return replace(action, card_instance_id=None)
    else:  # pragma: no cover - parameter list is exhaustive
        raise AssertionError(field_name)
    return replace(action, payload=payload)


def test_guanshi_mingzhe_direct_apply_rejects_each_forged_trigger_identity_atomically(
) -> None:
    """FINAL-001: ACTIVATE/PASS share one canonical fail-closed validator."""

    game, red_ids = _guanshi_mingzhe_pause_chain()
    p3_max_hp = game.state.players_by_id["p3"].hp
    _assert_guanshi_mingzhe_pause(game, red_ids, p3_max_hp)
    before = game.execution_snapshot
    queue_before = tuple(game._skill_trigger_queue)
    continuation_before = game._pending_card_continuation
    context = ActionContext(
        mode=game.mode_id, phase=game.phase.value, actor_id="p1"
    )
    actions = {
        operation: next(
            item
            for item in game.legal_actions()
            if item.payload.get("operation") == operation
        )
        for operation in ("activate_skill", "pass_skill")
    }
    for operation, action in actions.items():
        for field_name in _TRIGGER_IDENTITY_FIELDS:
            forged = _forge_pending_skill_identity(action, field_name)
            # The special trigger_index case deliberately leaves the redundant
            # consumption_key untouched; the validator must still reject it.
            if field_name == "trigger_index":
                assert forged.payload["consumption_key"] == (
                    action.payload["consumption_key"]
                )
            if field_name == "decision_window_id":
                for peer in (
                    "trigger_event_sequence",
                    "trigger_event_type",
                    "trigger_index",
                    "consumption_key",
                    "continuation_identity",
                ):
                    assert forged.payload[peer] == action.payload[peer]
            expected_field = {
                "payload_skill_id": "skill_id",
                "action_skill_id": "skill_id",
            }.get(field_name, field_name)
            with pytest.raises(
                InvalidActionError,
                match=rf"技能决策身份字段 {expected_field} 与当前窗口不一致",
            ):
                if operation == "activate_skill":
                    game._apply_production_skill_action(game.state, context, forged)
                else:
                    game._apply_production_skill_pass(game.state, context, forged)

            assert game.execution_snapshot == before
            assert tuple(game._skill_trigger_queue) == queue_before
            assert game._pending_card_continuation is continuation_before
            assert game.skill_pending is not None
            assert game.skill_pending.trigger_index == 0
            assert _damage_events(game) == ()


def test_guanshi_mingzhe_complete_stale_zero_payload_cannot_consume_trigger_one() -> None:
    """A whole #0 payload is stale at #1 even when state revision did not change."""

    game, red_ids = _guanshi_mingzhe_pause_chain()
    p3_max_hp = game.state.players_by_id["p3"].hp
    _assert_guanshi_mingzhe_pause(game, red_ids, p3_max_hp)
    stale_zero = next(
        item
        for item in game.legal_actions()
        if item.payload.get("operation") == "activate_skill"
    )
    _take(game, "pass_skill", skill_id="sgs_skill_mingzhe")
    assert game.skill_pending is not None
    assert game.skill_pending.trigger_index == 1
    assert stale_zero.payload["expected_revision"] == game.state.revision
    before = game.execution_snapshot
    context = ActionContext(
        mode=game.mode_id, phase=game.phase.value, actor_id="p1"
    )
    with pytest.raises(
        InvalidActionError,
        match="技能决策身份字段 .* 与当前窗口不一致",
    ):
        game._apply_production_skill_action(game.state, context, stale_zero)
    assert game.execution_snapshot == before


def test_guanshi_mingzhe_forged_consumption_identity_fails_closed() -> None:
    """伪造/过期消费身份（consumption_key / trigger_index）必须失败关闭。"""
    game, red_ids = _guanshi_mingzhe_pause_chain()
    p3_max_hp = game.state.players_by_id["p3"].hp
    hand_at_pause = len(game.state.card_ids_in(ZoneRef.hand("p1")))
    pending0, queued_first = _assert_guanshi_mingzhe_pause(
        game, red_ids, p3_max_hp
    )
    context = ActionContext(
        mode=game.mode_id, phase=game.phase.value, actor_id="p1"
    )

    # #0 窗口上伪造 #1 的真实消费身份（#0 窗口不得接受 #1 身份）
    activate0 = next(
        action
        for action in game.legal_actions()
        if action.payload.get("operation") == "activate_skill"
    )
    forged_as_queued = replace(
        activate0,
        payload={
            **activate0.payload,
            "consumption_key": list(queued_first.consumption_key),
        },
    )
    with pytest.raises(
        InvalidActionError,
        match="技能决策身份字段 consumption_key 与当前窗口不一致",
    ):
        game._apply_production_skill_action(game.state, context, forged_as_queued)
    # #0 窗口上伪造越界 index
    for forged_index in ("2", "9"):
        forged = replace(
            activate0,
            payload={
                **activate0.payload,
                "consumption_key": [
                    str(pending0.trigger_event_sequence),
                    "p1",
                    "sgs_skill_mingzhe",
                    forged_index,
                ],
            },
        )
        with pytest.raises(
            InvalidActionError,
            match="技能决策身份字段 consumption_key 与当前窗口不一致",
        ):
            game._apply_production_skill_action(game.state, context, forged)
    # 全部伪造被拒后窗口未被消费、伤害仍未发生
    assert game.skill_pending is not None
    assert game.skill_pending.trigger_index == 0
    assert _damage_events(game) == ()

    # 真实消费 #0；#1 窗口上伪造 #0 的过期消费身份（#0 不得冒充 #1）
    _take(game, "pass_skill", skill_id="sgs_skill_mingzhe")
    pending1 = game.skill_pending
    assert pending1 is not None
    assert pending1.trigger_index == 1
    activate1 = next(
        action
        for action in game.legal_actions()
        if action.payload.get("operation") == "activate_skill"
    )
    forged_as_stale0 = replace(
        activate1,
        payload={
            **activate1.payload,
            "consumption_key": list(pending0.consumption_key),
        },
    )
    with pytest.raises(
        InvalidActionError,
        match="技能决策身份字段 consumption_key 与当前窗口不一致",
    ):
        game._apply_production_skill_action(game.state, context, forged_as_stale0)
    assert game.execution_snapshot["skill_authority"] == (
        game._skill_audit_value()
    )

    # 清理：真实消费 #1，伤害恰好一次
    _take(game, "pass_skill", skill_id="sgs_skill_mingzhe")
    _assert_guanshi_damage_resolved(
        game, expected_draws=0, hand_at_pause=hand_at_pause, p3_max_hp=p3_max_hp
    )


def test_guanshi_mingzhe_unknown_and_stale_action_id_fails_closed() -> None:
    """controller 层：未知/过期 action_id 必须失败关闭；#1 身份必须新鲜。"""
    game, red_ids = _guanshi_mingzhe_pause_chain()
    p3_max_hp = game.state.players_by_id["p3"].hp
    hand_at_pause = len(game.state.card_ids_in(ZoneRef.hand("p1")))
    _pending0, queued_first = _assert_guanshi_mingzhe_pause(
        game, red_ids, p3_max_hp
    )

    # 未知（伪造）action_id：不在当前真实合法动作集合中
    activate0 = next(
        action
        for action in game.legal_actions()
        if action.payload.get("operation") == "activate_skill"
    )
    unknown_id = "act_" + (
        "0" if activate0.action_id[4] != "0" else "1"
    ) + activate0.action_id[5:]
    with pytest.raises(
        ProductionBatchError, match="指定动作不在当前真实合法动作集合中"
    ):
        game.step(BatchActionIdController(unknown_id))
    assert game.skill_pending is not None
    assert game.skill_pending.trigger_index == 0
    assert _damage_events(game) == ()

    # 真实消费 #0；过期 #0 action_id 不得经 controller 重放
    _step(game, activate0)
    assert game.skill_pending is not None
    assert game.skill_pending.trigger_index == 1
    with pytest.raises(
        ProductionBatchError, match="指定动作不在当前真实合法动作集合中"
    ):
        game.step(BatchActionIdController(activate0.action_id))
    # 过期 #0 动作直接 apply：动作枚举时绑定的状态版本已过期，失败关闭
    context = ActionContext(
        mode=game.mode_id, phase=game.phase.value, actor_id="p1"
    )
    with pytest.raises(
        InvalidActionError,
        match="技能决策身份字段 .* 与当前窗口不一致",
    ):
        game._apply_production_skill_action(game.state, context, activate0)
    # #1 的枚举身份新鲜且与 #0 完全不同（#0 不得冒充 #1）
    activate1 = next(
        action
        for action in game.legal_actions()
        if action.payload.get("operation") == "activate_skill"
    )
    assert activate1.action_id != activate0.action_id
    assert activate1.payload.get("trigger_index") == 1
    assert tuple(activate1.payload.get("consumption_key") or ()) == tuple(
        queued_first.consumption_key
    )
    assert activate1.payload.get("decision_window_id") != (
        activate0.payload.get("decision_window_id")
    )
    # 真实消费 #1 → 伤害恰好一次
    _step(game, activate1)
    _assert_guanshi_damage_resolved(
        game, expected_draws=2, hand_at_pause=hand_at_pause, p3_max_hp=p3_max_hp
    )


_GUANSHI_SECOND_TRIGGER_SENTINEL = "g3 guanshi mingzhe second trigger rollback sentinel"


def test_guanshi_mingzhe_second_trigger_failure_rolls_back_with_continuation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """真实链 transaction 证明：#0 step 已提交保留；失败的 #1 step 整体回滚，
    父级贯石斧 continuation 必须保留（不得丢失/重复），恢复后可正常结算。"""
    game, red_ids = _guanshi_mingzhe_pause_chain()
    p3_max_hp = game.state.players_by_id["p3"].hp
    hand_at_pause = len(game.state.card_ids_in(ZoneRef.hand("p1")))
    _assert_guanshi_mingzhe_pause(game, red_ids, p3_max_hp)

    first_key = tuple(game.skill_pending.consumption_key)
    _take(game, "activate_skill", skill_id="sgs_skill_mingzhe")
    assert first_key in game._skill_consumed_triggers
    pending = game.skill_pending
    assert pending is not None
    assert pending.trigger_index == 1
    second_key = tuple(pending.consumption_key)

    before = game.execution_snapshot
    queue_before = tuple(game._skill_trigger_queue)
    hand_before = len(game.state.card_ids_in(ZoneRef.hand("p1")))
    events_before = tuple(event.to_replay_dict() for event in game.events)
    continuation_before = game._pending_card_continuation
    assert continuation_before is not None
    activate = next(
        action
        for action in game.legal_actions()
        if action.payload.get("operation") == "activate_skill"
    )

    def explode(*args: object, **kwargs: object) -> object:
        del args, kwargs
        raise RuntimeError(_GUANSHI_SECOND_TRIGGER_SENTINEL)

    monkeypatch.setattr(game, "draw_cards_for_skill", explode)
    with pytest.raises(RuntimeError, match=_GUANSHI_SECOND_TRIGGER_SENTINEL):
        _step(game, activate)

    # 已提交的 #0 step 保留；失败的 #1 step 整体回滚（含父 continuation）
    assert first_key in game._skill_consumed_triggers
    assert game.execution_snapshot == before
    assert tuple(game._skill_trigger_queue) == queue_before
    assert game.skill_pending is not None
    assert tuple(game.skill_pending.consumption_key) == second_key
    assert game.skill_pending.trigger_index == 1
    assert second_key not in game._skill_consumed_triggers
    assert game._pending_card_continuation is continuation_before
    assert len(game.state.card_ids_in(ZoneRef.hand("p1"))) == hand_before
    assert tuple(event.to_replay_dict() for event in game.events) == events_before
    assert len(_mingzhe_draw_events(game)) == 1
    assert _damage_events(game) == ()
    assert game.state.players_by_id["p3"].hp == p3_max_hp
    assert game.phase is ProductionPhase.WEAPON_DISCARD_TWO

    # 恢复后 #1 可正常消费，父 continuation 恢复伤害恰好一次
    monkeypatch.undo()
    _take(game, "activate_skill", skill_id="sgs_skill_mingzhe")
    _assert_guanshi_damage_resolved(
        game, expected_draws=2, hand_at_pause=hand_at_pause, p3_max_hp=p3_max_hp
    )


def test_mingzhe_independent_roots_each_restart_at_trigger_zero() -> None:
    """真实签名【过河拆桥】对照路径：不同 root 各自从 #0 开始，不做全局计数。"""
    game = _mingzhe_equipped_game(initial_hand_count=2)
    _set_hand_keys(game, "p2", ("sgs_trick_guohechaiqiao", "sgs_trick_guohechaiqiao"))
    red_ids = _set_hand_red_cards(game, "p1", 2)

    _take(game, "use_guohe", target_ids=("p1",))
    _take(game, "pass_trick_response")
    _take(game, "pass_trick_response")
    _take(game, "choose_target_zone_card", zone="hand")
    first = game.skill_pending
    assert first is not None
    assert first.skill_id == "sgs_skill_mingzhe"
    assert first.trigger_index == 0
    first_root = _root_of_last_eligible_movement(game, "p1")

    _take(game, "pass_skill")
    assert game.skill_pending is None

    _take(game, "use_guohe", target_ids=("p1",))
    _take(game, "pass_trick_response")
    _take(game, "pass_trick_response")
    _take(game, "choose_target_zone_card", zone="hand")
    second = game.skill_pending
    assert second is not None
    assert second.skill_id == "sgs_skill_mingzhe"
    assert second.trigger_index == 0
    second_root = _root_of_last_eligible_movement(game, "p1")

    assert first_root != second_root
    assert first.trigger_event_sequence != second.trigger_event_sequence
    assert len({red_ids[0], red_ids[1]}) == 2


def _root_of_last_eligible_movement(
    game: ProductionBasicCardBatch, owner_id: str
) -> str:
    eligible = [
        entry
        for entry in game.card_movement_authority
        if entry.source_owner_id == owner_id and entry.mingzhe_discovery_eligible
    ]
    assert eligible
    return eligible[-1].root_operation_identity


# ...........................................................................
# INTERNAL CONTRACT SCALING PROOF（内部合同层扩展证明，非 production 签名路径）
#
# 以下测试通过 _commit_same_root_batch_discard 直接调用内部 seam（手工构造
# GameEvent + 直接 _commit_authoritative_card_movements + 直接
# _discover_production_skill_triggers），仅用于 N>=3 的 trigger_index 扩展性
# 与合同级消费行为证明；不得称为 production/real/signed 路径证明。
# ...........................................................................

_MINGZHE_CONTRACT_ROOT = "g3-mingzhe-same-root-contract-root"


def _mingzhe_equipped_game(
    *,
    first_player_id: str = "p2",
    initial_hand_count: int = 1,
) -> ProductionBasicCardBatch:
    """p1 全红装备（动态【明哲】生效），轮到 first_player_id 的出牌阶段。"""
    game = _game(
        first_player_id=first_player_id,
        initial_hand_count=initial_hand_count,
    )
    red_weapon_key = next(
        card.card_key
        for card in game.state.cards
        if card.card_type == "装备牌"
        and card.equipment_slot == "weapon"
        and card.color == "红"
        and game.state.location_of(card.instance_id) in (DRAW_PILE, DISCARD_PILE)
    )
    _set_equip(game, "p1", "weapon", red_weapon_key, color="红")
    assert game.skill_runtime.has_skill("p1", "sgs_skill_mingzhe")
    _advance_to_play(game)
    assert game.current_player_id == first_player_id
    return game


def _set_hand_red_cards(
    game: ProductionBasicCardBatch, player_id: str, count: int
) -> tuple[str, ...]:
    """把 player_id 的手牌整体替换为 count 张真实红色实体牌。"""
    state = game.state
    moves: dict[str, ZoneRef] = {
        card_id: DRAW_PILE
        for card_id in state.card_ids_in(ZoneRef.hand(player_id))
    }
    chosen: list[str] = []
    for card in state.cards:
        if len(chosen) == count:
            break
        if card.color != "红":
            continue
        if state.location_of(card.instance_id) not in (DRAW_PILE, DISCARD_PILE):
            continue
        chosen.append(card.instance_id)
        moves[card.instance_id] = ZoneRef.hand(player_id)
    game._state = state.move_cards(moves)
    game.state.assert_card_conservation()
    assert len(chosen) == count
    assert len(game.state.card_ids_in(ZoneRef.hand(player_id))) == count
    return tuple(chosen)


def _commit_same_root_batch_discard(
    game: ProductionBasicCardBatch,
    *,
    loser_id: str,
    actor_id: str,
    card_ids: tuple[str, ...],
    root_identity: str,
) -> None:
    """INTERNAL CONTRACT SEAM（非 production 签名路径）：同一 root 批量弃置。

    直接调用内部函数：先经 ``_commit_authoritative_card_movements`` 一次
    提交整批移动，再手工构造并发射 CARD_MOVED / CARD_LOST / CARD_DISCARDED
    事件组，最后直接调用 ``_discover_production_skill_triggers``。仅用于
    INTERNAL CONTRACT SCALING PROOF（N>=3 扩展性与合同级消费行为），
    不得作为 production/real/signed 路径证明；真实签名路径证明见
    test_guanshi_mingzhe_* 系列。
    """
    event_seq_before = game._events.next_sequence
    next_state = game._commit_authoritative_card_movements(
        game.state,
        {card_id: DISCARD_PILE for card_id in card_ids},
        semantic_reason="contract_batch_discard",
        movement_kind="discard",
        root_operation_identity=root_identity,
        action_actor_id=actor_id,
        card_user_id=actor_id,
    )
    game._state = next_state
    events: list[GameEvent] = []
    for card_id in card_ids:
        card_key = next(
            card.card_key
            for card in game.state.cards
            if card.instance_id == card_id
        )
        events.append(
            GameEvent(
                event_type=EventType.CARD_MOVED,
                card_instance_id=card_id,
                card_key=card_key,
                card_user=actor_id,
                target_ids=(loser_id,),
                payload={
                    "source": "hand",
                    "destination": "discard",
                    "reason": "contract_batch_discard",
                },
            )
        )
        events.append(
            GameEvent(
                event_type=EventType.CARD_LOST,
                card_instance_id=card_id,
                card_key=card_key,
                target_ids=(loser_id,),
                payload={
                    "reason": "contract_batch_discard",
                    "source_zone": f"hand:{loser_id}",
                },
            )
        )
        events.append(
            GameEvent(
                event_type=EventType.CARD_DISCARDED,
                card_instance_id=card_id,
                card_key=card_key,
                card_user=actor_id,
                target_ids=(loser_id,),
                payload={
                    "reason": "contract_batch_discard",
                    "source_zone": f"hand:{loser_id}",
                },
            )
        )
    game._events.extend(tuple(events))
    game._discover_production_skill_triggers(event_seq_before, state=game.state)


def _pending_and_queued(
    game: ProductionBasicCardBatch,
) -> tuple[object, tuple[object, ...]]:
    return game.skill_pending, tuple(game._skill_trigger_queue)


def test_internal_mingzhe_same_root_two_qualifying_losses_get_indices_zero_and_one() -> None:
    game = _mingzhe_equipped_game()
    card_ids = _set_hand_red_cards(game, "p1", 2)
    _commit_same_root_batch_discard(
        game,
        loser_id="p1",
        actor_id="p2",
        card_ids=card_ids,
        root_identity=_MINGZHE_CONTRACT_ROOT,
    )

    pending, queued = _pending_and_queued(game)
    assert pending is not None
    assert pending.skill_id == "sgs_skill_mingzhe"
    assert len(queued) == 1
    assert pending.trigger_index == 0
    assert queued[0].trigger_index == 1
    # 顺序由权威事件/移动顺序决定，不是 set/dict 迭代顺序
    assert pending.card_instance_id == card_ids[0]
    assert queued[0].card_instance_id == card_ids[1]
    assert pending.trigger_event_sequence < queued[0].trigger_event_sequence
    assert pending.consumption_key == (
        str(pending.trigger_event_sequence),
        "p1",
        "sgs_skill_mingzhe",
        "0",
    )
    assert queued[0].consumption_key == (
        str(queued[0].trigger_event_sequence),
        "p1",
        "sgs_skill_mingzhe",
        "1",
    )
    assert pending.decision_window_id.endswith(":0")
    assert queued[0].decision_window_id.endswith(":1")
    roots = {
        entry.root_operation_identity
        for entry in game.card_movement_authority
        if entry.card_instance_id in card_ids
    }
    assert roots == {_MINGZHE_CONTRACT_ROOT}
    assert game.turn_loss_ledger.count_losses_this_turn("p1") == 2


def test_internal_mingzhe_same_root_three_qualifying_losses_get_indices_zero_to_two() -> None:
    game = _mingzhe_equipped_game()
    card_ids = _set_hand_red_cards(game, "p1", 3)
    _commit_same_root_batch_discard(
        game,
        loser_id="p1",
        actor_id="p2",
        card_ids=card_ids,
        root_identity=_MINGZHE_CONTRACT_ROOT,
    )

    pending, queued = _pending_and_queued(game)
    assert pending is not None
    assert [pending.trigger_index, *(item.trigger_index for item in queued)] == [0, 1, 2]
    bound_cards = [pending.card_instance_id, *(item.card_instance_id for item in queued)]
    assert tuple(bound_cards) == card_ids
    assert len(set(bound_cards)) == 3


def test_internal_mingzhe_same_root_mixed_decisions_draw_exactly_two() -> None:
    game = _mingzhe_equipped_game()
    card_ids = _set_hand_red_cards(game, "p1", 3)
    _commit_same_root_batch_discard(
        game,
        loser_id="p1",
        actor_id="p2",
        card_ids=card_ids,
        root_identity=_MINGZHE_CONTRACT_ROOT,
    )

    hand_before = len(game.state.card_ids_in(ZoneRef.hand("p1")))
    consumed_keys: list[tuple[str, ...]] = []
    # #0 ACTIVATE
    assert game.skill_pending is not None
    consumed_keys.append(tuple(game.skill_pending.consumption_key))
    _take(game, "activate_skill")
    # #1 PASS
    assert game.skill_pending is not None
    assert game.skill_pending.trigger_index == 1
    consumed_keys.append(tuple(game.skill_pending.consumption_key))
    _take(game, "pass_skill")
    # #2 ACTIVATE
    assert game.skill_pending is not None
    assert game.skill_pending.trigger_index == 2
    consumed_keys.append(tuple(game.skill_pending.consumption_key))
    _take(game, "activate_skill")

    assert game.skill_pending is None
    assert not game._skill_trigger_queue
    assert len(game.state.card_ids_in(ZoneRef.hand("p1"))) == hand_before + 2
    assert [key[-1] for key in consumed_keys] == ["0", "1", "2"]
    assert len(set(consumed_keys)) == 3
    for key in consumed_keys:
        assert key in game._skill_consumed_triggers
    mingzhe_draws = [
        event
        for event in game.events
        if event.event_type is EventType.CARD_MOVED
        and event.payload.get("reason") == "sgs_skill_mingzhe"
    ]
    assert len(mingzhe_draws) == 2


def test_internal_mingzhe_same_root_all_pass_draws_nothing() -> None:
    game = _mingzhe_equipped_game()
    card_ids = _set_hand_red_cards(game, "p1", 2)
    _commit_same_root_batch_discard(
        game,
        loser_id="p1",
        actor_id="p2",
        card_ids=card_ids,
        root_identity=_MINGZHE_CONTRACT_ROOT,
    )

    hand_before = len(game.state.card_ids_in(ZoneRef.hand("p1")))
    _take(game, "pass_skill")
    assert game.skill_pending is not None
    assert game.skill_pending.trigger_index == 1
    _take(game, "pass_skill")

    assert game.skill_pending is None
    assert len(game.state.card_ids_in(ZoneRef.hand("p1"))) == hand_before
    assert not [
        event
        for event in game.events
        if event.event_type is EventType.CARD_MOVED
        and event.payload.get("reason") == "sgs_skill_mingzhe"
    ]


def test_internal_mingzhe_same_root_all_activate_draws_two() -> None:
    game = _mingzhe_equipped_game()
    card_ids = _set_hand_red_cards(game, "p1", 2)
    _commit_same_root_batch_discard(
        game,
        loser_id="p1",
        actor_id="p2",
        card_ids=card_ids,
        root_identity=_MINGZHE_CONTRACT_ROOT,
    )

    hand_before = len(game.state.card_ids_in(ZoneRef.hand("p1")))
    _take(game, "activate_skill")
    assert game.skill_pending is not None
    assert game.skill_pending.trigger_index == 1
    _take(game, "activate_skill")

    assert game.skill_pending is None
    assert len(game.state.card_ids_in(ZoneRef.hand("p1"))) == hand_before + 2


def test_internal_mingzhe_wrong_trigger_index_consumption_is_rejected() -> None:
    """伪造／过期 trigger_index 的消费身份必须失败关闭。"""
    game = _mingzhe_equipped_game()
    card_ids = _set_hand_red_cards(game, "p1", 2)
    _commit_same_root_batch_discard(
        game,
        loser_id="p1",
        actor_id="p2",
        card_ids=card_ids,
        root_identity=_MINGZHE_CONTRACT_ROOT,
    )

    _take(game, "pass_skill")  # 消费 #0，窗口推进到 #1
    pending = game.skill_pending
    assert pending is not None
    assert pending.trigger_index == 1
    activate = next(
        action
        for action in game.legal_actions()
        if action.payload.get("operation") == "activate_skill"
    )
    context = ActionContext(
        mode=game.mode_id, phase=game.phase.value, actor_id="p1"
    )
    for forged_index in ("0", "2", "9"):
        forged = replace(
            activate,
            payload={
                **activate.payload,
                "consumption_key": [
                    str(pending.trigger_event_sequence),
                    "p1",
                    "sgs_skill_mingzhe",
                    forged_index,
                ],
            },
        )
        with pytest.raises(
            InvalidActionError,
            match="技能决策身份字段 consumption_key 与当前窗口不一致",
        ):
            game._apply_production_skill_action(game.state, context, forged)
    assert game.execution_snapshot["skill_authority"] == (
        game._skill_audit_value()
    )


# ---------------------------------------------------------------------------
# G3-CLOSURE-003  transaction failure injection
#
# 当前权威 atomicity unit = 一个已签名 step（ProductionBasicCardBatch.step：
# _snapshot_authoritative_mutation_state → apply → invariants → 失败
# _restore_authoritative_mutation_state）。每个 step 是独立事务，因此已经
# 提交的 #0 step 保留，失败的 #1 step 回滚到该 step 开始前。
# ---------------------------------------------------------------------------

_MINGZHE_EQUIP_LOSS_SENTINEL = "g3 mingzhe discovery boundary rollback sentinel"
_MINGZHE_SECOND_TRIGGER_SENTINEL = "g3 mingzhe second trigger rollback sentinel"


def _two_red_equipment_game() -> ProductionBasicCardBatch:
    """p1 持有两张红色装备；p2 持麒麟弓并可弃置 p1 坐骑触发【明哲】。"""
    game = _game(first_player_id="p2", players=2)
    _set_equip(game, "p2", "weapon", "sgs_weapon_qilingong")
    red_horse_key = next(
        card.card_key
        for card in game.state.cards
        if card.card_type == "装备牌"
        and card.equipment_slot in ("defense_horse", "attack_horse")
        and card.color == "红"
    )
    red_horse_id = _set_equip(game, "p1", "defense_horse", red_horse_key, color="红")
    red_horse_slot = next(
        card.equipment_slot
        for card in game.state.cards
        if card.instance_id == red_horse_id
    )
    red_weapon_id = next(
        card.instance_id
        for card in game.state.cards
        if card.card_key == "sgs_weapon_zhugeliannu" and card.color == "红"
    )
    game._state = game.state.move_card(
        red_weapon_id, ZoneRef.equipment("p1", "weapon")
    )
    game._reconcile_qianchong_for_all(game.state)
    game.state.assert_card_conservation()
    assert game.skill_runtime.has_skill("p1", "sgs_skill_mingzhe")

    _advance_to_play(game)
    _set_hand_keys(game, "p2", ("sgs_basic_sha",))
    _take(game, "use_slash", target_ids=("p1",))
    _take(game, "pass_slash_response")
    return game, red_horse_id, red_horse_slot  # type: ignore[return-value]


def test_equipment_loss_then_reconcile_opens_mingzhe_discovery() -> None:
    """正对照：reconcile 后明哲仍生效，discovery 产生挂起触发。"""
    game, red_horse_id, _slot = _two_red_equipment_game()
    _take(game, "weapon_discard_mount", card_instance_id=red_horse_id)
    assert game.skill_runtime.has_skill("p1", "sgs_skill_mingzhe")
    assert game.skill_pending is not None
    assert game.skill_pending.skill_id == "sgs_skill_mingzhe"
    assert game.skill_pending.trigger_index == 0


def test_reconcile_complete_then_mingzhe_discovery_failure_rolls_back_everything(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    game, red_horse_id, red_horse_slot = _two_red_equipment_game()
    discover = next(
        action
        for action in game.legal_actions()
        if action.payload.get("operation") == "weapon_discard_mount"
    )
    before = game.execution_snapshot
    ledger_before = game.turn_loss_ledger.to_dict()
    movement_before = tuple(
        entry.to_dict() for entry in game.card_movement_authority
    )
    grants_before = tuple(
        grant.to_dict() for grant in game.skill_runtime.dynamic_grants["p1"]
    )
    runtime_before = game.skill_runtime.audit_fingerprint()
    events_before = tuple(event.to_replay_dict() for event in game.events)
    rng_before = tuple(call.to_dict() for call in game.rng_calls)
    permission_before = game.qianchong_phase_permission
    hand_before = len(game.state.card_ids_in(ZoneRef.hand("p1")))

    def explode(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise RuntimeError(_MINGZHE_EQUIP_LOSS_SENTINEL)

    monkeypatch.setattr(game, "_discover_production_skill_triggers", explode)
    with pytest.raises(RuntimeError, match=_MINGZHE_EQUIP_LOSS_SENTINEL):
        _step(game, discover)

    # 整个 authoritative step 回滚：不止“牌回来了”
    assert game.execution_snapshot == before
    assert game.turn_loss_ledger.to_dict() == ledger_before
    assert tuple(entry.to_dict() for entry in game.card_movement_authority) == (
        movement_before
    )
    assert tuple(grant.to_dict() for grant in game.skill_runtime.dynamic_grants["p1"]) == (
        grants_before
    )
    assert game.skill_runtime.audit_fingerprint() == runtime_before
    assert tuple(event.to_replay_dict() for event in game.events) == events_before
    assert tuple(call.to_dict() for call in game.rng_calls) == rng_before
    assert game.qianchong_phase_permission is permission_before
    assert len(game.state.card_ids_in(ZoneRef.hand("p1"))) == hand_before
    assert game.state.location_of(red_horse_id) == ZoneRef.equipment(
        "p1", red_horse_slot
    )
    assert game.skill_pending is None
    assert not game._skill_trigger_queue


def test_second_mingzhe_trigger_failure_rolls_back_only_that_step(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#0 step 已提交保留，失败的 #1 step 回滚到该 step 开始前。"""
    game = _mingzhe_equipped_game()
    card_ids = _set_hand_red_cards(game, "p1", 2)
    _commit_same_root_batch_discard(
        game,
        loser_id="p1",
        actor_id="p2",
        card_ids=card_ids,
        root_identity=_MINGZHE_CONTRACT_ROOT,
    )

    first_key = tuple(game.skill_pending.consumption_key)
    _take(game, "activate_skill")  # 提交 #0 step
    assert first_key in game._skill_consumed_triggers
    pending = game.skill_pending
    assert pending is not None
    assert pending.trigger_index == 1
    second_key = tuple(pending.consumption_key)

    before = game.execution_snapshot
    queue_before = tuple(game._skill_trigger_queue)
    hand_before = len(game.state.card_ids_in(ZoneRef.hand("p1")))
    events_before = tuple(event.to_replay_dict() for event in game.events)
    activate = next(
        action
        for action in game.legal_actions()
        if action.payload.get("operation") == "activate_skill"
    )
    original_draw = game.draw_cards_for_skill

    def explode(*args: object, **kwargs: object) -> object:
        del args, kwargs
        raise RuntimeError(_MINGZHE_SECOND_TRIGGER_SENTINEL)

    monkeypatch.setattr(game, "draw_cards_for_skill", explode)
    with pytest.raises(RuntimeError, match=_MINGZHE_SECOND_TRIGGER_SENTINEL):
        _step(game, activate)

    # 已提交的 #0 step 保留
    assert first_key in game._skill_consumed_triggers
    assert original_draw is not None
    # 失败的 #1 step 整体回滚
    assert game.execution_snapshot == before
    assert tuple(game._skill_trigger_queue) == queue_before
    assert game.skill_pending is not None
    assert tuple(game.skill_pending.consumption_key) == second_key
    assert game.skill_pending.trigger_index == 1
    assert second_key not in game._skill_consumed_triggers
    assert len(game.state.card_ids_in(ZoneRef.hand("p1"))) == hand_before
    assert tuple(event.to_replay_dict() for event in game.events) == events_before
    assert len(
        [
            event
            for event in game.events
            if event.event_type is EventType.CARD_MOVED
            and event.payload.get("reason") == "sgs_skill_mingzhe"
        ]
    ) == 1
