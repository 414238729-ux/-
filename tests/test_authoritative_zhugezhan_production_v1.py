# -*- coding: utf-8 -*-
"""Production semantics for G2 Zhugezhan 【罪论】 and 【父荫】."""

from __future__ import annotations

from dataclasses import replace

import pytest

from scripts.sgs_engine.actions import ActionType, InvalidActionError, LegalAction
from scripts.sgs_engine.engine import canonical_state_snapshot
from scripts.sgs_engine.events import DamageEvent, EventType, GameEvent
from scripts.sgs_engine.model import DISCARD_PILE, DRAW_PILE, ZoneRef
from scripts.sgs_engine.multiplayer import OutcomePolicy, PlayerTopology
from scripts.sgs_engine.production_batch import (
    BatchActionIdController,
    ProductionBasicCardBatch,
    ProductionPhase,
    _replace_player,
)
from scripts.sgs_engine.production_replay import _project_public_events
from scripts.sgs_engine.replay import sha256_value
from scripts.sgs_engine.skill_impl_v1 import create_proof_slice_v1_registry


LEBUSI = "sgs_delayed_lebusi"
BINGLIANG = "sgs_delayed_bingliang"


def _game(
    *,
    seed: int = 11,
    players: int = 2,
    first_player_id: str = "p1",
    assignments: dict[str, str] | None = None,
    outcome_policy: OutcomePolicy | None = None,
    initial_hand_count: int = 1,
    shuffle: bool = False,
    player_hp: tuple[int, ...] | None = None,
    player_max_hp: tuple[int, ...] | None = None,
) -> ProductionBasicCardBatch:
    ids = tuple(f"p{i}" for i in range(1, players + 1))
    hp = player_hp or tuple(3 if pid == "p1" else 4 for pid in ids)
    max_hp = player_max_hp or hp
    return ProductionBasicCardBatch(
        seed=seed,
        shuffle=shuffle,
        first_player_id=first_player_id,
        player_ids=ids,
        player_hp=hp,
        player_max_hp=max_hp,
        outcome_policy=outcome_policy,
        initial_hand_count=initial_hand_count,
        general_assignments=assignments or {"p1": "zhugezhan"},
        skill_registry=create_proof_slice_v1_registry(),
        session_id="g2-zhugezhan-production-session",
        session_secret=b"z" * 32,
    )


class _NonterminalThreePlayerPolicy(OutcomePolicy):
    def __init__(self) -> None:
        object.__setattr__(self, "policy_id", "g2_nonterminal_three_player_fixture")

    def resolve_winner_after_death(
        self, topology: PlayerTopology, dying_id: str
    ) -> str | None:
        del topology, dying_id
        return None


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
                else item.payload.get(key) == value
            )
            for key, value in matches.items()
        )
    )
    _step(game, action)
    return action


def _advance_to_play(game: ProductionBasicCardBatch) -> None:
    for operation in ("proceed_prepare", "proceed_judgment", "proceed_draw"):
        _take(game, operation)
    assert game.phase is ProductionPhase.PLAY


def _set_hand_keys(
    game: ProductionBasicCardBatch, player_id: str, keys: tuple[str, ...]
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
            and card.instance_id not in chosen
            and state.location_of(card.instance_id) in (DRAW_PILE, DISCARD_PILE)
            and card.instance_id not in moves
        )
        chosen.append(card_id)
        moves[card_id] = ZoneRef.hand(player_id)
    game._state = state.move_cards(moves)
    game.state.assert_card_conservation()
    return tuple(chosen)


def _set_hand_count(
    game: ProductionBasicCardBatch, player_id: str, count: int
) -> tuple[str, ...]:
    generic = (
        "sgs_basic_tao",
        "sgs_basic_shan",
        "sgs_basic_jiu",
        "sgs_basic_sha",
    )
    return _set_hand_keys(game, player_id, generic[:count])


def _put_draw_prefix(
    game: ProductionBasicCardBatch, instance_ids: tuple[str, ...]
) -> None:
    pile = list(game.state.card_ids_in(DRAW_PILE))
    assert all(instance_id in pile for instance_id in instance_ids)
    remaining = [instance_id for instance_id in pile if instance_id not in instance_ids]
    game._state = game.state.reorder_zone(DRAW_PILE, (*instance_ids, *remaining))


def _close_judgment_wuxie(game: ProductionBasicCardBatch) -> None:
    assert game.phase is ProductionPhase.JUDGMENT_WUXIE
    while game.phase is ProductionPhase.JUDGMENT_WUXIE:
        _take(game, "pass_judgment_wuxie")


def _discard_to_end(game: ProductionBasicCardBatch) -> None:
    while game.phase is ProductionPhase.DISCARD:
        submit = next(
            (
                item
                for item in game.legal_actions()
                if item.payload.get("operation") == "discard_phase_submit"
            ),
            None,
        )
        if submit is not None:
            _step(game, submit)
        else:
            _take(game, "select_discard_card")


def _reach_delayed_skip_end_entry(
    *, initial_hand_count: int, skip_draw_too: bool = False
) -> ProductionBasicCardBatch:
    """Use signed delayed-trick actions, then reach p2's skipped phase flow."""

    game = _game(
        first_player_id="p1",
        assignments={"p2": "zhugezhan"},
        initial_hand_count=initial_hand_count,
        player_hp=(4, 3),
        player_max_hp=(4, 3),
    )
    _advance_to_play(game)
    keys = (LEBUSI, BINGLIANG) if skip_draw_too else (LEBUSI,)
    delayed_ids = _set_hand_keys(game, "p1", keys)
    lebusi_id = delayed_ids[0]
    lebusi = next(
        item
        for item in game.legal_actions()
        if item.card_instance_id == lebusi_id and item.target_ids == ("p2",)
    )
    _step(game, lebusi)
    if skip_draw_too:
        bingliang_id = delayed_ids[1]
        bingliang = next(
            item
            for item in game.legal_actions()
            if item.card_instance_id == bingliang_id
            and item.target_ids == ("p2",)
        )
        _step(game, bingliang)

    spades = tuple(
        card.instance_id
        for card in game.state.cards
        if card.suit == "♠" and game.state.location_of(card.instance_id) == DRAW_PILE
    )
    _put_draw_prefix(game, spades[: 2 if skip_draw_too else 1])
    _take(game, "end_play_phase")
    _take(game, "end_turn")
    _take(game, "proceed_prepare")
    _take(game, "proceed_judgment")
    _close_judgment_wuxie(game)
    if skip_draw_too:
        _take(game, "proceed_judgment")
        _close_judgment_wuxie(game)
    _take(game, "proceed_judgment")
    if not skip_draw_too:
        assert game.phase is ProductionPhase.DRAW
        _take(game, "proceed_draw")
    return game


def _end_phase_events(game: ProductionBasicCardBatch) -> list[GameEvent]:
    return [
        event
        for event in game.events
        if event.event_type is EventType.END_PHASE_STARTED
        and event.target_ids == (game.runtime.current_player_id,)
    ]


def _zuilun_choices(game: ProductionBasicCardBatch) -> tuple[LegalAction, LegalAction]:
    legal = game.legal_actions()
    activate = next(
        item
        for item in legal
        if item.action_type is ActionType.ACTIVATE_SKILL
        and item.skill_id == "sgs_skill_zuilun"
    )
    decline = next(
        item
        for item in legal
        if item.action_type is ActionType.PASS
        and item.skill_id == "sgs_skill_zuilun"
    )
    assert activate.payload["trigger_event_type"] == EventType.END_PHASE_STARTED.value
    assert activate.payload["continuation_identity"] == decline.payload[
        "continuation_identity"
    ]
    return activate, decline


def _open_zuilun(game: ProductionBasicCardBatch, n: int) -> tuple[LegalAction, LegalAction]:
    _advance_to_play(game)
    if n == 0:
        _set_hand_count(game, "p1", 3)
        _set_hand_count(game, "p2", 1)
        discarded = game.state.card_ids_in(ZoneRef.hand("p1"))[0]
        game._state = game.discard_cards_for_skill(
            game.state,
            (discarded,),
            owner_id="p1",
            reason="g2_zuilun_fact_fixture",
            skill_owner="p1",
        )
    elif n == 1:
        _set_hand_count(game, "p1", 2)
        _set_hand_count(game, "p2", 1)
    else:
        _set_hand_count(game, "p1", 1)
        _set_hand_count(game, "p2", 2)
        if n == 3:
            game._events.extend(
                (
                    DamageEvent(
                        target_id="p2",
                        amount=1,
                        damage_source="p1",
                        damage_type="无属性",
                    ),
                )
            )
    _take(game, "end_play_phase")
    activate, decline = _zuilun_choices(game)
    assert activate.payload["n"] == n
    return activate, decline


def _finish_play_and_discard(game: ProductionBasicCardBatch) -> None:
    _take(game, "end_play_phase")
    while game.phase is ProductionPhase.DISCARD:
        submit = next(
            (
                item for item in game.legal_actions()
                if item.payload.get("operation") == "discard_phase_submit"
            ),
            None,
        )
        if submit is not None:
            _step(game, submit)
            continue
        _take(game, "select_discard_card")


def _open_zuilun_from_production(n: int) -> tuple[ProductionBasicCardBatch, LegalAction]:
    """Reach each n only through initial configuration plus signed production actions."""

    initial_hand_count = 1 if n == 1 else 2
    seed = 2 if n in (2, 3) else 19
    game = _game(
        seed=seed,
        initial_hand_count=initial_hand_count,
        shuffle=True,
    )
    _advance_to_play(game)
    if n == 3:
        equipment = next(
            item for item in game.legal_actions()
            if item.action_type is ActionType.USE_CARD
            and item.payload.get("card_key") == "sgs_weapon_hanbingjian"
        )
        _step(game, equipment)
    if n in (2, 3):
        slash = next(
            item for item in game.legal_actions()
            if item.action_type is ActionType.USE_CARD
            and item.payload.get("card_key")
            in {"sgs_basic_sha", "sgs_basic_huosha", "sgs_basic_leisha"}
            and item.target_ids == ("p2",)
        )
        _step(game, slash)
        _take(game, "pass_slash_response")
        if n == 3 and game.phase is ProductionPhase.WEAPON_SLASH_CHOICE:
            _take(game, "pass_weapon_choice")
    _finish_play_and_discard(game)
    activate, _ = _zuilun_choices(game)
    assert activate.payload["n"] == n
    return game, activate


@pytest.mark.parametrize(
    ("n", "expected"),
    (
        (0, (False, True, False, 3, 2)),
        (1, (False, False, False, 3, 1)),
        (2, (True, False, False, 3, 2)),
        (3, (True, False, True, 2, 2)),
    ),
)
def test_zuilun_all_condition_counts_from_signed_production_actions(
    n: int, expected: tuple[bool, bool, bool, int, int]
) -> None:
    game, activate = _open_zuilun_from_production(n)
    facts = (
        activate.payload["dealt_damage_this_turn"],
        activate.payload["discarded_card_this_turn"],
        activate.payload["has_minimum_hand_count"],
        activate.payload["owner_hand_count"],
        activate.payload["minimum_alive_hand_count"],
    )
    assert facts == expected
    assert any(event.event_type is EventType.END_PHASE_STARTED for event in game.events)


@pytest.mark.parametrize("n", (1, 2, 3))
def test_zuilun_positive_private_top_three_selection(n: int) -> None:
    game = _game(seed=10 + n)
    activate, _ = _open_zuilun(game, n)
    top_before = tuple(game.state.card_ids_in(DRAW_PILE)[:3])
    continuation = str(activate.payload["continuation_identity"])
    _step(game, activate)

    legal = game.legal_actions()
    assert len(legal) == {1: 3, 2: 3, 3: 1}[n]
    selected_action = legal[-1]
    selected = tuple(selected_action.payload["selected_card_ids"])
    remaining = tuple(card for card in top_before if card not in selected)
    _step(game, selected_action)

    assert all(
        game.state.location_of(card) == ZoneRef.hand("p1") for card in selected
    )
    assert tuple(game.state.card_ids_in(DRAW_PILE)[: len(remaining)]) == remaining
    assert continuation in game.consumed_skill_continuation_identities
    gained = [
        event
        for event in game.events
        if event.event_type is EventType.CARD_GAINED
        and event.payload.get("reason") == "sgs_skill_zuilun"
    ]
    assert len(gained) == n
    assert all(event.payload.get("not_draw") is True for event in gained)


def test_private_observation_projection_owner_public_and_other_player() -> None:
    game, activate = _open_zuilun_from_production(2)
    _step(game, activate)
    observed = tuple(game.legal_actions()[0].payload["observed_card_ids"])
    selection = game.legal_actions()[-1]
    selected = tuple(selection.payload["selected_card_ids"])
    _step(game, selection)

    authoritative = tuple(event.to_replay_dict() for event in game.events)
    owner = _project_public_events(authoritative, "p1", frozenset())
    public = _project_public_events(authoritative, None, frozenset())
    other = _project_public_events(authoritative, "p2", frozenset())

    owner_blob = repr(owner)
    assert all(card_id in owner_blob for card_id in observed)
    assert all(card_id in owner_blob for card_id in selected)
    for projected in (public, other):
        blob = repr(projected)
        assert all(card_id not in blob for card_id in observed)
        assert all(card_id not in blob for card_id in selected)
        private_events = [
            event for event in projected
            if event.get("event_type") == EventType.PRIVATE_CARDS_OBSERVED.value
        ]
        assert private_events
        assert all(event["payload"].get("redacted") is True for event in private_events)
        assert all(
            not {
                "observed_card_ids",
                "observed_order",
                "selected_card_ids",
                "remaining_top_order",
                "window_id",
                "continuation_identity",
            }
            & set(event["payload"])
            for event in private_events
        )

    authoritative_blob = repr(authoritative)
    assert all(card_id in authoritative_blob for card_id in observed)


def test_zuilun_pass_has_no_effect_and_consumes_only_window() -> None:
    game = _game()
    _, decline = _open_zuilun(game, 2)
    before = canonical_state_snapshot(game.state)
    event_count = len(game.events)
    continuation = str(decline.payload["continuation_identity"])
    _step(game, decline)

    assert canonical_state_snapshot(game.state) == before
    assert len(game.events) == event_count
    assert continuation in game.consumed_skill_continuation_identities
    skill_state = game.skill_runtime.get_skill_state("p1", "sgs_skill_zuilun")
    assert skill_state.uses_this_turn == 0
    assert game.phase is ProductionPhase.END


def test_zuilun_n0_self_then_other_lose_hp() -> None:
    game = _game()
    activate, _ = _open_zuilun(game, 0)
    _step(game, activate)
    assert game.state.players_by_id["p1"].hp == 2
    target = next(
        item
        for item in game.legal_actions()
        if item.payload.get("operation") == "skill_lose_hp_target_choice"
        and item.target_ids == ("p2",)
    )
    _step(game, target)
    assert game.state.players_by_id["p2"].hp == 3
    lose_hp = [event for event in game.events if event.event_type is EventType.LOSE_HP]
    assert [event.target_ids for event in lose_hp[-2:]] == [("p1",), ("p2",)]
    assert game.phase is ProductionPhase.END


def test_zuilun_self_dying_rescued_then_other_segment_continues() -> None:
    game = _game()
    _advance_to_play(game)
    _set_hand_keys(game, "p1", ("sgs_basic_tao", "sgs_basic_shan", "sgs_basic_jiu"))
    _set_hand_keys(game, "p2", ())
    discarded = game.state.card_ids_in(ZoneRef.hand("p1"))[1:]
    game._state = game.discard_cards_for_skill(
        game.state,
        discarded,
        owner_id="p1",
        reason="g2_zuilun_fact_fixture",
        skill_owner="p1",
    )
    game._state = _replace_player(game.state, "p1", hp=1)
    _take(game, "end_play_phase")
    activate, _ = _zuilun_choices(game)
    assert activate.payload["n"] == 0
    _step(game, activate)
    assert game.phase is ProductionPhase.DYING_RESCUE

    peach = next(
        item
        for item in game.legal_actions()
        if item.payload.get("card_key") == "sgs_basic_tao"
    )
    _step(game, peach)
    assert game.state.players_by_id["p1"].hp == 1
    assert game.phase is ProductionPhase.END
    target = next(
        item for item in game.legal_actions()
        if item.payload.get("operation") == "skill_lose_hp_target_choice"
    )
    _step(game, target)
    assert game.state.players_by_id[target.target_ids[0]].hp == 3


def test_zuilun_self_death_terminal_stops_other_segment() -> None:
    game = _game()
    activate, _ = _open_zuilun(game, 0)
    game._state = _replace_player(game.state, "p1", hp=1)
    # Refresh the signed END_PHASE window after the deliberate test fixture change.
    game._skill_pending = replace(game._skill_pending, window_revision=game.state.revision)
    activate = next(
        item for item in game.legal_actions()
        if item.action_type is ActionType.ACTIVATE_SKILL
    )
    _step(game, activate)
    for _ in range(4):
        if game.is_finished:
            break
        _take(game, "pass_rescue")
    assert game.is_finished
    assert not game.state.players_by_id["p1"].alive
    p2_losses = [
        event for event in game.events
        if event.event_type is EventType.LOSE_HP and event.target_ids == ("p2",)
    ]
    assert not p2_losses


def test_zuilun_self_death_nonterminal_still_opens_other_target_choice() -> None:
    game = _game(players=3, outcome_policy=_NonterminalThreePlayerPolicy())
    activate, _ = _open_zuilun(game, 0)
    game._state = _replace_player(game.state, "p1", hp=1)
    game._skill_pending = replace(game._skill_pending, window_revision=game.state.revision)
    activate = next(
        item for item in game.legal_actions()
        if item.action_type is ActionType.ACTIVATE_SKILL
    )
    _step(game, activate)
    for _ in range(6):
        if game.phase is not ProductionPhase.DYING_RESCUE:
            break
        _take(game, "pass_rescue")
    assert not game.is_finished
    assert not game.state.players_by_id["p1"].alive
    targets = game.legal_actions()
    assert {item.target_ids for item in targets} == {("p2",), ("p3",)}
    chosen = next(item for item in targets if item.target_ids == ("p3",))
    _step(game, chosen)
    assert game.state.players_by_id["p3"].hp == 3


def test_zuilun_other_target_dying_uses_full_rescue_chain() -> None:
    game = _game()
    activate, _ = _open_zuilun(game, 0)
    game._state = _replace_player(game.state, "p2", hp=1)
    game._skill_pending = replace(game._skill_pending, window_revision=game.state.revision)
    activate = next(
        item for item in game.legal_actions()
        if item.action_type is ActionType.ACTIVATE_SKILL
    )
    _step(game, activate)
    target = next(
        item for item in game.legal_actions() if item.target_ids == ("p2",)
    )
    _step(game, target)
    assert game.phase is ProductionPhase.DYING_RESCUE
    while game.current_actor_id != "p2":
        _take(game, "pass_rescue")
    peach = next(
        item for item in game.legal_actions()
        if item.payload.get("card_key") == "sgs_basic_tao"
    )
    _step(game, peach)
    assert game.state.players_by_id["p2"].hp == 1
    assert game.phase is ProductionPhase.END


def test_zuilun_exact_end_phase_only_and_no_retroactive_fact_change() -> None:
    game = _game()
    _advance_to_play(game)
    assert not any(
        event.event_type is EventType.END_PHASE_STARTED for event in game.events
    )
    _set_hand_count(game, "p1", 1)
    _set_hand_count(game, "p2", 2)
    _take(game, "end_play_phase")
    activate, _ = _zuilun_choices(game)
    assert activate.payload["n"] == 2
    assert game.phase is ProductionPhase.END
    assert not any(event.event_type.value == "turn_end" for event in game.events)
    # A later fact cannot rewrite the already signed END_PHASE decision.
    game._events.extend(
        (DamageEvent(target_id="p2", amount=1, damage_source="p1"),)
    )
    with pytest.raises(InvalidActionError, match="条件事实"):
        game._apply_production_skill_action(
            game.state,
            game._context(),
            activate,
        )


def test_lebusi_skip_play_auto_end_opens_zuilun_exactly_once() -> None:
    game = _reach_delayed_skip_end_entry(initial_hand_count=1)
    assert game.phase is ProductionPhase.END
    assert len(game.state.card_ids_in(ZoneRef.hand("p2"))) == 3
    assert game.state.players_by_id["p2"].hp == 3
    assert [
        event.payload["skipped_phase"]
        for event in game.events
        if event.event_type is EventType.PHASE_SKIPPED
        and event.target_ids == ("p2",)
    ] == ["play"]
    assert len(_end_phase_events(game)) == 1
    _, decline = _zuilun_choices(game)
    _step(game, decline)
    assert len(_end_phase_events(game)) == 1
    _take(game, "end_turn")
    assert len(
        [
            event
            for event in game.events
            if event.event_type is EventType.END_PHASE_STARTED
            and event.target_ids == ("p2",)
        ]
    ) == 1


def test_lebusi_skip_play_discard_then_end_opens_zuilun_exactly_once() -> None:
    game = _reach_delayed_skip_end_entry(initial_hand_count=2)
    assert game.phase is ProductionPhase.DISCARD
    assert not [
        event
        for event in game.events
        if event.event_type is EventType.END_PHASE_STARTED
        and event.target_ids == ("p2",)
    ]
    _discard_to_end(game)
    assert game.phase is ProductionPhase.END
    assert len(_end_phase_events(game)) == 1
    _zuilun_choices(game)


def test_bingliang_and_lebusi_direct_judgment_to_end_opens_zuilun_once() -> None:
    game = _reach_delayed_skip_end_entry(
        initial_hand_count=2, skip_draw_too=True
    )
    assert game.phase is ProductionPhase.END
    assert {
        event.payload["skipped_phase"]
        for event in game.events
        if event.event_type is EventType.PHASE_SKIPPED
        and event.target_ids == ("p2",)
    } == {"draw", "play"}
    assert len(_end_phase_events(game)) == 1
    _zuilun_choices(game)


def test_normal_play_to_auto_end_opens_zuilun_once_and_end_turn_does_not_repeat() -> None:
    game = _game(initial_hand_count=1)
    _advance_to_play(game)
    _set_hand_count(game, "p1", 1)
    _set_hand_count(game, "p2", 2)
    _take(game, "end_play_phase")
    assert game.phase is ProductionPhase.END
    assert len(_end_phase_events(game)) == 1
    _, decline = _zuilun_choices(game)
    _step(game, decline)
    _take(game, "end_turn")
    assert len(
        [
            event
            for event in game.events
            if event.event_type is EventType.END_PHASE_STARTED
            and event.target_ids == ("p1",)
        ]
    ) == 1


def test_zuilun_private_top_three_reuses_formal_reshuffle_supply() -> None:
    game = _game()
    _, _ = _open_zuilun(game, 2)
    draw_ids = tuple(game.state.card_ids_in(DRAW_PILE))
    original_prefix = draw_ids[:2]
    game._state = game.state.move_cards(
        {card_id: DISCARD_PILE for card_id in draw_ids[2:]}
    )
    game._skill_pending = replace(
        game._skill_pending, window_revision=game.state.revision
    )
    activate = next(
        item for item in game.legal_actions()
        if item.action_type is ActionType.ACTIVATE_SKILL
    )
    _step(game, activate)
    observed = tuple(game.legal_actions()[0].payload["observed_card_ids"])
    assert observed[:2] == original_prefix
    assert len(observed) == 3
    assert any(
        event.event_type is EventType.CARD_MOVED
        and event.payload.get("reason") == "reshuffle"
        for event in game.events
    )


def _prepare_fuyin_card(
    *, card_key: str, ineffective: bool, assignments: dict[str, str] | None = None
) -> tuple[ProductionBasicCardBatch, str]:
    game = _game(
        first_player_id="p2",
        assignments=assignments or {"p1": "zhugezhan"},
    )
    _advance_to_play(game)
    owner_keys = ("sgs_basic_shan",) if ineffective else ("sgs_basic_shan",)
    user_keys = (
        (card_key,) if ineffective else (card_key, "sgs_basic_tao", "sgs_basic_jiu")
    )
    _set_hand_keys(game, "p1", owner_keys)
    card_id = _set_hand_keys(game, "p2", user_keys)[0]
    return game, card_id


def _use_card_on_p1(game: ProductionBasicCardBatch, card_id: str) -> LegalAction:
    action = next(
        item
        for item in game.legal_actions()
        if item.card_instance_id == card_id and item.target_ids == ("p1",)
    )
    _step(game, action)
    return action


def _fuyin_condition_events(game: ProductionBasicCardBatch) -> list[GameEvent]:
    return [
        event for event in game.events
        if event.event_type is EventType.SKILL_CONDITION_EVALUATED
        and event.payload.get("skill_id") == "sgs_skill_fuyin"
    ]


@pytest.mark.parametrize("card_key", ("sgs_basic_sha", "sgs_trick_juedou"))
def test_fuyin_first_slash_or_duel_ineffective(card_key: str) -> None:
    game, card_id = _prepare_fuyin_card(card_key=card_key, ineffective=True)
    hp_before = game.state.players_by_id["p1"].hp
    _use_card_on_p1(game, card_id)
    resolved = [
        event for event in game.events
        if event.event_type is EventType.TARGET_EFFECT_INEFFECTIVE
    ]
    assert len(resolved) == 1
    checked = _fuyin_condition_events(game)
    assert len(checked) == 1
    assert checked[0].payload["user_hand_count_after_use"] == 0
    assert checked[0].payload["owner_hand_count"] == 1
    assert checked[0].payload["target_effect_ineffective"] is True
    assert checked[0].payload["consumed_after"] is True
    if card_key == "sgs_trick_juedou":
        while game.phase is ProductionPhase.TRICK_RESPONSE:
            _take(game, "pass_trick_response")
    assert game.phase is ProductionPhase.PLAY
    assert game.state.players_by_id["p1"].hp == hp_before
    assert not any(event.event_type is EventType.CARD_INVALIDATED for event in game.events)


@pytest.mark.parametrize("card_key", ("sgs_basic_sha", "sgs_trick_juedou"))
def test_fuyin_comparison_false_effect_normal_but_consumed(card_key: str) -> None:
    game, card_id = _prepare_fuyin_card(card_key=card_key, ineffective=False)
    _use_card_on_p1(game, card_id)
    assert not any(
        event.event_type is EventType.TARGET_EFFECT_INEFFECTIVE
        for event in game.events
    )
    checked = _fuyin_condition_events(game)
    assert len(checked) == 1
    assert checked[0].payload["user_hand_count_after_use"] == 2
    assert checked[0].payload["owner_hand_count"] == 1
    assert checked[0].payload["target_effect_ineffective"] is False
    assert checked[0].payload["consumed_after"] is True
    if card_key == "sgs_basic_sha":
        _take(game, "pass_slash_response")
    else:
        while game.phase is ProductionPhase.TRICK_RESPONSE:
            _take(game, "pass_trick_response")
        assert game.phase is ProductionPhase.DUEL_RESPONSE
        _take(game, "pass_duel_slash")
    assert game.state.players_by_id["p1"].hp == 2
    skill_state = game.skill_runtime.get_skill_state("p1", "sgs_skill_fuyin")
    assert skill_state.marks["fuyin_consumed_turn"] == game.runtime.turn_number


def test_fuyin_same_turn_second_card_does_not_trigger_and_nonmatching_does_not_consume() -> None:
    game, slash_id = _prepare_fuyin_card(card_key="sgs_basic_sha", ineffective=True)
    _use_card_on_p1(game, slash_id)
    assert game.phase is ProductionPhase.PLAY
    assert len([e for e in game.events if e.event_type is EventType.TARGET_EFFECT_INEFFECTIVE]) == 1
    assert len(_fuyin_condition_events(game)) == 1

    duel_id = _set_hand_keys(game, "p2", ("sgs_trick_juedou",))[0]
    _use_card_on_p1(game, duel_id)
    assert len([e for e in game.events if e.event_type is EventType.TARGET_EFFECT_INEFFECTIVE]) == 1
    assert len(_fuyin_condition_events(game)) == 1

    fresh = _game(first_player_id="p2")
    _advance_to_play(fresh)
    _set_hand_keys(fresh, "p1", ("sgs_basic_shan",))
    guohe = _set_hand_keys(fresh, "p2", ("sgs_trick_guohechaiqiao",))[0]
    _use_card_on_p1(fresh, guohe)
    fuyin = fresh.skill_runtime.get_skill_state("p1", "sgs_skill_fuyin")
    assert "fuyin_consumed_turn" not in fuyin.marks


def test_fuyin_turn_identity_reset_allows_next_independent_turn() -> None:
    game, slash_id = _prepare_fuyin_card(card_key="sgs_basic_sha", ineffective=True)
    _use_card_on_p1(game, slash_id)
    first_turn = game.runtime.turn_number
    _set_hand_count(game, "p2", 1)
    _take(game, "end_play_phase")
    _take(game, "end_turn")

    _advance_to_play(game)
    _set_hand_count(game, "p1", 1)
    _take(game, "end_play_phase")
    _, decline = _zuilun_choices(game)
    _step(game, decline)
    _take(game, "end_turn")

    _advance_to_play(game)
    _set_hand_keys(game, "p1", ("sgs_basic_shan",))
    second_slash = _set_hand_keys(game, "p2", ("sgs_basic_sha",))[0]
    _use_card_on_p1(game, second_slash)
    events = [
        event for event in game.events
        if event.event_type is EventType.TARGET_EFFECT_INEFFECTIVE
    ]
    assert len(events) == 2
    assert len(_fuyin_condition_events(game)) == 2
    assert events[0].payload["turn_number"] == first_turn
    assert events[1].payload["turn_number"] == game.runtime.turn_number
    assert events[1].payload["turn_number"] > first_turn


def test_fuyin_target_scope_preserves_other_fangtian_target() -> None:
    game = _game(players=3, first_player_id="p2")
    _advance_to_play(game)
    weapon = next(
        card.instance_id
        for card in game.state.cards
        if card.card_key == "sgs_weapon_fangtianhuaji"
    )
    game._state = game.state.move_card(weapon, ZoneRef.equipment("p2", "weapon"))
    _set_hand_keys(game, "p1", ("sgs_basic_shan",))
    slash = _set_hand_keys(game, "p2", ("sgs_basic_sha",))[0]
    action = next(
        item for item in game.legal_actions()
        if item.card_instance_id == slash
        and set(item.target_ids) == {"p1", "p3"}
    )
    _step(game, action)
    while game.phase is ProductionPhase.SLASH_RESPONSE:
        _take(game, "pass_slash_response")
    assert game.phase is ProductionPhase.PLAY
    assert game.state.players_by_id["p1"].hp == 3
    assert game.state.players_by_id["p3"].hp == 3
    resolved = next(
        event for event in game.events
        if event.event_type is EventType.TARGET_EFFECT_INEFFECTIVE
    )
    assert resolved.target_ids == ("p1",)
    checked = _fuyin_condition_events(game)
    assert len(checked) == 1
    assert checked[0].target_ids == ("p1",)


def test_fuyin_jili_coexistence_is_deterministic_and_non_overwriting() -> None:
    game, slash_id = _prepare_fuyin_card(
        card_key="sgs_basic_sha",
        ineffective=True,
        assignments={"p1": "zhugezhan", "p2": "shamoke"},
    )
    _use_card_on_p1(game, slash_id)
    assert game.pending_card_continuation_identity is not None
    assert not any(
        event.event_type is EventType.TARGET_EFFECT_INEFFECTIVE for event in game.events
    )
    assert not _fuyin_condition_events(game)
    decline = next(
        item for item in game.legal_actions()
        if item.action_type is ActionType.PASS and item.skill_id == "sgs_skill_jili"
    )
    continuation = str(decline.payload["continuation_identity"])
    _step(game, decline)
    assert continuation in game.consumed_card_continuation_identities
    assert game.pending_card_continuation_identity is None
    assert len(
        [event for event in game.events if event.event_type is EventType.TARGET_EFFECT_INEFFECTIVE]
    ) == 1
    assert len(_fuyin_condition_events(game)) == 1
    assert game.phase is ProductionPhase.PLAY


def test_fuyin_jili_activate_then_target_effect_checkpoint() -> None:
    game, slash_id = _prepare_fuyin_card(
        card_key="sgs_basic_sha",
        ineffective=True,
        assignments={"p1": "zhugezhan", "p2": "shamoke"},
    )
    _use_card_on_p1(game, slash_id)
    activate = next(
        item for item in game.legal_actions()
        if item.action_type is ActionType.ACTIVATE_SKILL
        and item.skill_id == "sgs_skill_jili"
    )
    continuation = str(activate.payload["continuation_identity"])
    _step(game, activate)
    assert continuation in game.consumed_card_continuation_identities
    assert game.pending_card_continuation_identity is None
    assert len(_fuyin_condition_events(game)) == 1
    assert len(
        [event for event in game.events if event.event_type is EventType.TARGET_EFFECT_INEFFECTIVE]
    ) == 1
    jili = game.skill_runtime.get_skill_state("p2", "sgs_skill_jili")
    fuyin = game.skill_runtime.get_skill_state("p1", "sgs_skill_fuyin")
    assert jili.uses_this_turn == 1
    assert fuyin.marks["fuyin_consumed_turn"] == game.runtime.turn_number
    assert game.phase is ProductionPhase.PLAY

    condition_count = len(_fuyin_condition_events(game))
    ineffective_count = len(
        [
            event
            for event in game.events
            if event.event_type is EventType.TARGET_EFFECT_INEFFECTIVE
        ]
    )
    duel_id = _set_hand_keys(game, "p2", ("sgs_trick_juedou",))[0]
    _use_card_on_p1(game, duel_id)
    assert len(_fuyin_condition_events(game)) == condition_count
    assert len(
        [
            event
            for event in game.events
            if event.event_type is EventType.TARGET_EFFECT_INEFFECTIVE
        ]
    ) == ineffective_count
    assert game.phase is ProductionPhase.TRICK_RESPONSE


def test_fuyin_false_condition_jili_activate_preserves_consumption() -> None:
    game, slash_id = _prepare_fuyin_card(
        card_key="sgs_basic_sha",
        ineffective=False,
        assignments={"p1": "zhugezhan", "p2": "shamoke"},
    )
    _use_card_on_p1(game, slash_id)
    activate = next(
        item
        for item in game.legal_actions()
        if item.action_type is ActionType.ACTIVATE_SKILL
        and item.skill_id == "sgs_skill_jili"
    )
    _step(game, activate)
    assert len(_fuyin_condition_events(game)) == 1
    assert not any(
        event.event_type is EventType.TARGET_EFFECT_INEFFECTIVE
        for event in game.events
    )
    assert (
        game.skill_runtime.get_skill_state("p1", "sgs_skill_fuyin").marks[
            "fuyin_consumed_turn"
        ]
        == game.runtime.turn_number
    )
    assert (
        game.skill_runtime.get_skill_state("p2", "sgs_skill_jili").uses_this_turn
        == 1
    )
    assert game.phase is ProductionPhase.SLASH_RESPONSE
    _take(game, "pass_slash_response")
    assert game.phase is ProductionPhase.PLAY

    duel_id = _set_hand_keys(game, "p2", ("sgs_trick_juedou",))[0]
    _use_card_on_p1(game, duel_id)
    assert len(_fuyin_condition_events(game)) == 1
    assert not any(
        event.event_type is EventType.TARGET_EFFECT_INEFFECTIVE
        for event in game.events
    )


def test_jili_activate_merges_unrelated_live_skill_mark(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    game, slash_id = _prepare_fuyin_card(
        card_key="sgs_basic_sha",
        ineffective=True,
        assignments={"p1": "zhugezhan", "p2": "shamoke"},
    )
    _use_card_on_p1(game, slash_id)
    original = game._post_target_effect_checkpoint

    def mark_after_resume(*args: object, **kwargs: object) -> object:
        result = original(*args, **kwargs)
        runtime = game.skill_runtime
        zuilun = runtime.get_skill_state("p1", "sgs_skill_zuilun")
        game._skill_runtime = runtime.with_skill_state(
            "p1",
            "sgs_skill_zuilun",
            replace(zuilun, marks={**dict(zuilun.marks), "merge_probe": 7}),
        )
        return result

    monkeypatch.setattr(game, "_post_target_effect_checkpoint", mark_after_resume)
    activate = next(
        item
        for item in game.legal_actions()
        if item.action_type is ActionType.ACTIVATE_SKILL
        and item.skill_id == "sgs_skill_jili"
    )
    _step(game, activate)
    assert (
        game.skill_runtime.get_skill_state("p1", "sgs_skill_zuilun").marks[
            "merge_probe"
        ]
        == 7
    )
    assert (
        game.skill_runtime.get_skill_state("p1", "sgs_skill_fuyin").marks[
            "fuyin_consumed_turn"
        ]
        == game.runtime.turn_number
    )
    assert (
        game.skill_runtime.get_skill_state("p2", "sgs_skill_jili").uses_this_turn
        == 1
    )


def test_jili_activate_nested_failure_rolls_back_usage_and_fuyin_mark(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    game, slash_id = _prepare_fuyin_card(
        card_key="sgs_basic_sha",
        ineffective=True,
        assignments={"p1": "zhugezhan", "p2": "shamoke"},
    )
    _use_card_on_p1(game, slash_id)
    activate = next(
        item
        for item in game.legal_actions()
        if item.action_type is ActionType.ACTIVATE_SKILL
        and item.skill_id == "sgs_skill_jili"
    )
    before_state = canonical_state_snapshot(game.state)
    before_events = tuple(event.to_replay_dict() for event in game.events)
    before_runtime = game.skill_runtime.audit_fingerprint()
    before_audit = game.execution_snapshot
    original = game._post_target_effect_checkpoint

    def explode_after_fuyin(*args: object, **kwargs: object) -> object:
        original(*args, **kwargs)
        assert "fuyin_consumed_turn" in game.skill_runtime.get_skill_state(
            "p1", "sgs_skill_fuyin"
        ).marks
        raise RuntimeError("jili fuyin nested rollback sentinel")

    monkeypatch.setattr(
        game, "_post_target_effect_checkpoint", explode_after_fuyin
    )
    with pytest.raises(RuntimeError, match="nested rollback sentinel"):
        _step(game, activate)
    assert canonical_state_snapshot(game.state) == before_state
    assert tuple(event.to_replay_dict() for event in game.events) == before_events
    assert game.skill_runtime.audit_fingerprint() == before_runtime
    assert game.execution_snapshot == before_audit
    assert game.pending_card_continuation_identity is not None


def test_zuilun_damage_fact_uses_successful_production_damage_only() -> None:
    game = _game()
    _advance_to_play(game)
    slash = _set_hand_keys(game, "p1", ("sgs_basic_sha",))[0]
    vine = next(
        card.instance_id for card in game.state.cards
        if card.card_key == "sgs_armor_tengjia"
    )
    game._state = game.state.move_card(vine, ZoneRef.equipment("p2", "armor"))
    action = next(
        item for item in game.legal_actions()
        if item.card_instance_id == slash and item.target_ids == ("p2",)
    )
    hp_before = game.state.players_by_id["p2"].hp
    _step(game, action)
    if game.phase is ProductionPhase.SLASH_RESPONSE:
        _take(game, "pass_slash_response")
    assert not any(
        event.event_type is EventType.DAMAGE and event.damage_source == "p1"
        for event in game.events
    )
    assert game.state.players_by_id["p2"].hp == hp_before
    _finish_play_and_discard(game)
    activate, _ = _zuilun_choices(game)
    assert activate.payload["dealt_damage_this_turn"] is False
    assert activate.payload["discarded_card_this_turn"] is False


def test_zuilun_multiple_successful_damage_events_remain_boolean_fact() -> None:
    game = _game()
    _advance_to_play(game)
    crossbow, slash_one, slash_two = _set_hand_keys(
        game,
        "p1",
        ("sgs_weapon_zhugeliannu", "sgs_basic_sha", "sgs_basic_huosha"),
    )
    _step(game, next(item for item in game.legal_actions() if item.card_instance_id == crossbow))
    for slash in (slash_one, slash_two):
        _step(
            game,
            next(
                item for item in game.legal_actions()
                if item.card_instance_id == slash and item.target_ids == ("p2",)
            ),
        )
        _take(game, "pass_slash_response")
    damages = [
        event for event in game.events
        if event.event_type is EventType.DAMAGE and event.damage_source == "p1"
    ]
    assert len(damages) == 2
    _finish_play_and_discard(game)
    activate, _ = _zuilun_choices(game)
    assert activate.payload["dealt_damage_this_turn"] is True
    assert type(activate.payload["dealt_damage_this_turn"]) is bool


def test_zuilun_used_and_played_cards_entering_discard_are_not_discarded() -> None:
    game = _game()
    _advance_to_play(game)
    duel, owner_slash = _set_hand_keys(
        game, "p1", ("sgs_trick_juedou", "sgs_basic_sha")
    )
    _set_hand_keys(game, "p2", ("sgs_basic_sha",))
    _step(
        game,
        next(
            item for item in game.legal_actions()
            if item.card_instance_id == duel and item.target_ids == ("p2",)
        ),
    )
    while game.phase is ProductionPhase.TRICK_RESPONSE:
        _take(game, "pass_trick_response")
    _take(game, "play_slash_for_duel")
    response = next(
        item for item in game.legal_actions()
        if item.payload.get("operation") == "play_slash_for_duel"
        and item.card_instance_id == owner_slash
    )
    _step(game, response)
    _take(game, "pass_duel_slash")
    assert any(
        event.event_type is EventType.CARD_PLAYED and event.card_user == "p1"
        for event in game.events
    )
    assert game.state.location_of(owner_slash) == DISCARD_PILE
    _finish_play_and_discard(game)
    activate, _ = _zuilun_choices(game)
    assert activate.payload["discarded_card_this_turn"] is False


def test_zuilun_equipment_discard_counts_by_behavior_executor() -> None:
    game = _game()
    _advance_to_play(game)
    weapon, slash = _set_hand_keys(
        game, "p1", ("sgs_weapon_hanbingjian", "sgs_basic_sha")
    )
    mount = next(
        card.instance_id for card in game.state.cards
        if card.card_key == "sgs_mount_defensive"
    )
    game._state = game.state.move_card(mount, ZoneRef.equipment("p2", "defense_horse"))
    _step(game, next(item for item in game.legal_actions() if item.card_instance_id == weapon))
    _step(
        game,
        next(
            item for item in game.legal_actions()
            if item.card_instance_id == slash and item.target_ids == ("p2",)
        ),
    )
    _take(game, "pass_slash_response")
    _take(game, "weapon_prevent_damage")
    equipment_choice = next(
        item for item in game.legal_actions()
        if item.payload.get("operation") == "hanbing_discard_card"
        and item.card_instance_id == mount
    )
    _step(game, equipment_choice)
    if game.phase is ProductionPhase.HANBING_DISCARD:
        _take(game, "hanbing_discard_card")
    discarded = [
        event for event in game.events
        if event.event_type is EventType.CARD_DISCARDED
        and event.card_user == "p1"
        and event.card_instance_id == mount
    ]
    assert len(discarded) == 1
    assert discarded[0].payload["source_zone"] == "equipment:defense_horse"
    _finish_play_and_discard(game)
    activate, _ = _zuilun_choices(game)
    assert activate.payload["discarded_card_this_turn"] is True


def test_zuilun_card_owned_by_owner_but_discarded_by_other_does_not_count() -> None:
    game = _game(first_player_id="p2")
    _advance_to_play(game)
    owner_card = _set_hand_keys(game, "p1", ("sgs_basic_shan",))[0]
    guohe = _set_hand_keys(game, "p2", ("sgs_trick_guohechaiqiao",))[0]
    _step(
        game,
        next(
            item for item in game.legal_actions()
            if item.card_instance_id == guohe and item.target_ids == ("p1",)
        ),
    )
    while game.phase is ProductionPhase.TRICK_RESPONSE:
        _take(game, "pass_trick_response")
    choice = next(
        item for item in game.legal_actions()
        if item.payload.get("operation") == "choose_target_zone_card"
        and item.payload.get("zone") == "hand"
    )
    _step(game, choice)
    event = next(
        item for item in game.events
        if item.event_type is EventType.CARD_DISCARDED
        and item.card_instance_id == owner_card
    )
    assert event.card_user == "p2"
    assert event.target_ids == ("p1",)
    assert game._zuilun_condition_facts(game.state, "p1")[
        "discarded_card_this_turn"
    ] is False


def test_zuilun_minimum_hand_count_excludes_production_dead_player() -> None:
    game = _game(
        players=3,
        outcome_policy=_NonterminalThreePlayerPolicy(),
        player_hp=(3, 1, 4),
        player_max_hp=(3, 1, 4),
    )
    _advance_to_play(game)
    weapon, slash = _set_hand_keys(
        game, "p1", ("sgs_weapon_fangtianhuaji", "sgs_basic_sha")
    )
    _step(game, next(item for item in game.legal_actions() if item.card_instance_id == weapon))
    _step(
        game,
        next(
            item for item in game.legal_actions()
            if item.card_instance_id == slash
            and set(item.target_ids) == {"p2", "p3"}
        ),
    )
    _take(game, "pass_slash_response")
    while game.phase is ProductionPhase.DYING_RESCUE:
        _take(game, "pass_rescue")
    assert not game.state.players_by_id["p2"].alive
    assert len(game.state.card_ids_in(ZoneRef.hand("p2"))) == 0
    if game.phase is ProductionPhase.SLASH_RESPONSE:
        _take(game, "pass_slash_response")
    _set_hand_count(game, "p1", 1)
    _set_hand_count(game, "p3", 1)
    _finish_play_and_discard(game)
    activate, _ = _zuilun_choices(game)
    assert activate.payload["owner_hand_count"] == 1
    assert activate.payload["minimum_alive_hand_count"] == 1
    assert activate.payload["has_minimum_hand_count"] is True


def test_zuilun_and_fuyin_step_transactions_roll_back_all_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    game = _game()
    activate, _ = _open_zuilun(game, 2)
    _step(game, activate)
    selection = game.legal_actions()[0]
    before_state = canonical_state_snapshot(game.state)
    before_events = tuple(event.to_replay_dict() for event in game.events)
    before_owner_projection = _project_public_events(before_events, "p1", frozenset())
    before_public_projection = _project_public_events(before_events, None, frozenset())
    before_audit = game.execution_snapshot
    original = game._apply_private_card_selection

    def explode(*args: object, **kwargs: object) -> object:
        original(*args, **kwargs)
        raise RuntimeError("g2 rollback sentinel")

    monkeypatch.setattr(game, "_apply_private_card_selection", explode)
    with pytest.raises(RuntimeError, match="rollback sentinel"):
        _step(game, selection)
    assert canonical_state_snapshot(game.state) == before_state
    current_events = tuple(event.to_replay_dict() for event in game.events)
    assert current_events == before_events
    assert _project_public_events(current_events, "p1", frozenset()) == before_owner_projection
    assert _project_public_events(current_events, None, frozenset()) == before_public_projection
    assert game.execution_snapshot == before_audit

    fuyin_game, slash_id = _prepare_fuyin_card(
        card_key="sgs_basic_sha", ineffective=True
    )
    slash = next(
        item for item in fuyin_game.legal_actions()
        if item.card_instance_id == slash_id and item.target_ids == ("p1",)
    )
    before_state = canonical_state_snapshot(fuyin_game.state)
    before_events = tuple(event.to_replay_dict() for event in fuyin_game.events)
    before_runtime = fuyin_game.skill_runtime.audit_fingerprint()
    original_checkpoint = fuyin_game._post_target_effect_checkpoint

    def explode_checkpoint(*args: object, **kwargs: object) -> object:
        original_checkpoint(*args, **kwargs)
        raise RuntimeError("g2 fuyin rollback sentinel")

    monkeypatch.setattr(
        fuyin_game, "_post_target_effect_checkpoint", explode_checkpoint
    )
    with pytest.raises(RuntimeError, match="fuyin rollback sentinel"):
        _step(fuyin_game, slash)
    assert canonical_state_snapshot(fuyin_game.state) == before_state
    assert tuple(event.to_replay_dict() for event in fuyin_game.events) == before_events
    assert fuyin_game.skill_runtime.audit_fingerprint() == before_runtime
