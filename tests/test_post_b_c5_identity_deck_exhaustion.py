# -*- coding: utf-8 -*-
"""POST-B C5：reshuffle_draw 与彻底不足平局 inventory。"""

from __future__ import annotations

from typing import Any

from scripts.sgs_engine.actions import LegalAction
from scripts.sgs_engine.events import EventType
from scripts.sgs_engine.model import DISCARD_PILE, DRAW_PILE, PROCESSING_ZONE, REVEALED_ZONE, ZoneRef
from scripts.sgs_engine.mode_identity import (
    FormalIdentityConfiguration,
    FormalIdentitySession,
    StandardIdentityRole,
)
from scripts.sgs_engine.production_batch import (
    BatchActionIdController,
    ProductionBasicCardBatch,
    ProductionPhase,
    _replace_player,
)

SHA = "sgs_basic_sha"
_SECRET = b"0123456789abcdef0123456789abcdef"


def _session(seed: int = 15) -> FormalIdentitySession:
    return FormalIdentitySession(
        seed=seed,
        configuration=FormalIdentityConfiguration.formal_profile(),
        session_id=f"c5-exh-{seed}",
        session_secret=_SECRET,
    )


def _step(game: ProductionBasicCardBatch, action: LegalAction) -> None:
    game.step(BatchActionIdController(action.action_id))


def _op(game: ProductionBasicCardBatch, operation: str, **filters: Any) -> LegalAction | None:
    for action in game.legal_actions():
        if action.payload.get("operation") != operation:
            continue
        if "targets" in filters and tuple(action.target_ids) != tuple(filters["targets"]):
            continue
        return action
    return None


def _require_op(game: ProductionBasicCardBatch, operation: str, **filters: Any) -> LegalAction:
    action = _op(game, operation, **filters)
    assert action is not None, operation
    return action


def _enter_play(game: ProductionBasicCardBatch) -> None:
    for operation in ("proceed_prepare", "proceed_judgment", "proceed_draw"):
        _step(game, _require_op(game, operation))


def _drain_draw_to(game: ProductionBasicCardBatch, count: int) -> None:
    ids = list(game.state.card_ids_in(DRAW_PILE))
    extra = ids[count:]
    if extra:
        game._state = game.state.move_cards(
            {instance_id: DISCARD_PILE for instance_id in extra}
        )


def _empty_discard(game: ProductionBasicCardBatch) -> None:
    ids = list(game.state.card_ids_in(DISCARD_PILE))
    if not ids:
        return
    # 不可重洗区：移入手牌再测彻底不足时会污染手牌。测试彻底不足时
    # 直接把弃牌堆再移到牌堆外的 REMOVED 不允许。改为保留或清空到
    # 判定区会改变 reshuffle 集合。本函数只在需要“弃牌堆足够”时不用。
    game._state = game.state.move_cards(
        {instance_id: DRAW_PILE for instance_id in ids}
    )


def test_reshuffle_when_discard_sufficient() -> None:
    game = _session(16)
    _enter_play(game)
    _drain_draw_to(game, 0)
    assert game.state.card_ids_in(DRAW_PILE) == ()
    assert game.state.card_ids_in(DISCARD_PILE)
    before_rng = len(game.rng_calls)
    actor = game.current_player_id
    before_hand = len(game.state.card_ids_in(ZoneRef.hand(actor)))
    _give = None
    del _give
    _step(game, _require_op(game, "end_play_phase"))
    while game.phase is ProductionPhase.DISCARD:
        submit = _op(game, "discard_phase_submit")
        if submit is not None:
            _step(game, submit)
        else:
            _step(game, _require_op(game, "select_discard_card"))
    _step(game, _require_op(game, "end_turn"))
    _step(game, _require_op(game, "proceed_prepare"))
    _step(game, _require_op(game, "proceed_judgment"))
    _step(game, _require_op(game, "proceed_draw"))
    assert game.is_finished is False
    assert len(game.rng_calls) > before_rng
    assert any(
        event.event_type is EventType.CARD_MOVED
        and event.payload.get("reason") == "reshuffle"
        for event in game.events
    )
    assert len(game.state.card_ids_in(ZoneRef.hand(game.current_player_id))) >= before_hand


def _end_play_to_next_prepare(game: ProductionBasicCardBatch) -> None:
    if game.phase is ProductionPhase.PLAY:
        _step(game, _require_op(game, "end_play_phase"))
    while game.phase is ProductionPhase.DISCARD:
        submit = _op(game, "discard_phase_submit")
        if submit is not None:
            _step(game, submit)
        else:
            _step(game, _require_op(game, "select_discard_card"))
    if game.phase is ProductionPhase.END:
        _step(game, _require_op(game, "end_turn"))
    assert game.phase is ProductionPhase.PREPARE


def _enter_draw_setup(game: ProductionBasicCardBatch) -> None:
    _end_play_to_next_prepare(game)
    _step(game, _require_op(game, "proceed_prepare"))
    _step(game, _require_op(game, "proceed_judgment"))
    assert game.phase is ProductionPhase.DRAW


def _park_away(
    game: ProductionBasicCardBatch, instance_ids: list[str], holder: str
) -> None:
    if not instance_ids:
        return
    game._state = game.state.move_cards(
        {instance_id: ZoneRef.hand(holder) for instance_id in instance_ids}
    )


def _strip_hand(game: ProductionBasicCardBatch, player_id: str) -> None:
    for instance_id in tuple(game.state.card_ids_in(ZoneRef.hand(player_id))):
        game._state = game.state.move_card(instance_id, DISCARD_PILE)


def _give_card(game: ProductionBasicCardBatch, player_id: str, card_key: str) -> str:
    for instance_id, card in game.state.cards_by_id.items():
        if card.card_key == card_key:
            destination = ZoneRef.hand(player_id)
            if game.state.location_of(instance_id) != destination:
                game._state = game.state.move_card(instance_id, destination)
            return instance_id
    raise AssertionError(card_key)


def test_complete_last_card_is_not_draw() -> None:
    game = _session(17)
    _enter_play(game)
    _enter_draw_setup(game)
    drawer = game.current_player_id
    holder = next(pid for pid in game.player_ids if pid != drawer)
    remaining = list(game.state.card_ids_in(DRAW_PILE))
    keep = remaining[:2]
    _park_away(game, remaining[2:], holder)
    _park_away(game, list(game.state.card_ids_in(DISCARD_PILE)), holder)
    del keep
    assert len(game.state.card_ids_in(DRAW_PILE)) == 2
    assert game.state.card_ids_in(DISCARD_PILE) == ()
    _step(game, _require_op(game, "proceed_draw"))
    assert game.is_finished is False
    assert game.winner_id is None
    assert game.state.card_ids_in(DRAW_PILE) == ()


def test_need_next_card_with_both_piles_empty_is_identity_draw() -> None:
    game = _session(18)
    _enter_play(game)
    _enter_draw_setup(game)
    drawer = game.current_player_id
    holder = next(pid for pid in game.player_ids if pid != drawer)
    remaining = list(game.state.card_ids_in(DRAW_PILE))
    _park_away(game, remaining[1:], holder)
    _park_away(game, list(game.state.card_ids_in(DISCARD_PILE)), holder)
    assert len(game.state.card_ids_in(DRAW_PILE)) == 1
    assert game.state.card_ids_in(DISCARD_PILE) == ()
    _step(game, _require_op(game, "proceed_draw"))
    assert game.is_finished is True
    assert game.winner_id is None
    assert game.runtime.game_over_reason == "identity_draw_deck_exhausted"
    assert any(event.event_type is EventType.DRAW for event in game.events)
    assert len(game.state.card_ids_in(PROCESSING_ZONE)) == 0
    assert len(game.state.card_ids_in(REVEALED_ZONE)) == 0


def test_partial_draw_keeps_already_moved_cards() -> None:
    game = _session(19)
    _enter_play(game)
    _enter_draw_setup(game)
    drawer = game.current_player_id
    holder = next(pid for pid in game.player_ids if pid != drawer)
    remaining = list(game.state.card_ids_in(DRAW_PILE))
    last_id = remaining[0]
    _park_away(game, remaining[1:], holder)
    _park_away(game, list(game.state.card_ids_in(DISCARD_PILE)), holder)
    hand_before = game.state.card_ids_in(ZoneRef.hand(drawer))
    _step(game, _require_op(game, "proceed_draw"))
    assert game.is_finished is True
    assert last_id in game.state.card_ids_in(ZoneRef.hand(drawer))
    assert last_id not in hand_before


def test_wuzhong_exhaustion_is_formal_draw() -> None:
    game = _session(20)
    _enter_play(game)
    actor = game.current_player_id
    holder = next(pid for pid in game.player_ids if pid != actor)
    for instance_id in tuple(game.state.card_ids_in(ZoneRef.hand(actor))):
        game._state = game.state.move_card(instance_id, ZoneRef.hand(holder))
    wuzhong = None
    for instance_id, card in game.state.cards_by_id.items():
        if card.card_key == "sgs_trick_wuzhongshengyou":
            wuzhong = instance_id
            game._state = game.state.move_card(instance_id, ZoneRef.hand(actor))
            break
    assert wuzhong is not None
    _park_away(game, list(game.state.card_ids_in(DRAW_PILE)), holder)
    _park_away(game, list(game.state.card_ids_in(DISCARD_PILE)), holder)
    assert game.state.card_ids_in(DRAW_PILE) == ()
    assert game.state.card_ids_in(DISCARD_PILE) == ()
    _step(game, _require_op(game, "use_wuzhong"))
    while not game.is_finished and _op(game, "pass_trick_response") is not None:
        _step(game, _require_op(game, "pass_trick_response"))
    assert game.is_finished is True
    assert game.runtime.game_over_reason == "identity_draw_deck_exhausted"
    assert wuzhong not in game.state.card_ids_in(PROCESSING_ZONE)


def test_judgment_exhaustion_is_formal_draw() -> None:
    from dataclasses import replace
    from types import MappingProxyType

    game = _session(22)
    _enter_play(game)
    _end_play_to_next_prepare(game)
    actor = game.current_player_id
    holder = next(pid for pid in game.player_ids if pid != actor)
    lebusi = None
    for instance_id, card in game.state.cards_by_id.items():
        if card.card_key == "sgs_delayed_lebusi":
            lebusi = instance_id
            break
    assert lebusi is not None
    game._state = game.state.move_card(lebusi, ZoneRef.judgment(actor))
    game._runtime = replace(
        game.runtime,
        judgment_entry_indices=MappingProxyType({lebusi: 1}),
        judgment_entry_counter=1,
    )
    _park_away(game, list(game.state.card_ids_in(DRAW_PILE)), holder)
    _park_away(game, list(game.state.card_ids_in(DISCARD_PILE)), holder)
    _step(game, _require_op(game, "proceed_prepare"))
    _step(game, _require_op(game, "proceed_judgment"))
    while not game.is_finished and (
        _op(game, "pass_judgment_wuxie") is not None
        or _op(game, "pass_trick_response") is not None
    ):
        op = (
            "pass_judgment_wuxie"
            if _op(game, "pass_judgment_wuxie") is not None
            else "pass_trick_response"
        )
        _step(game, _require_op(game, op))
    assert game.is_finished is True
    assert game.runtime.game_over_reason == "identity_draw_deck_exhausted"


def test_rebel_kill_draw_three_mid_exhaustion_keeps_death() -> None:
    game = _session(23)
    lord = game.lord_player_id
    rebel = next(
        pid
        for pid, role in game.identities_by_player.items()
        if role is StandardIdentityRole.REBEL
    )
    _enter_play(game)
    for instance_id in tuple(game.state.card_ids_in(ZoneRef.hand(rebel))):
        game._state = game.state.move_card(instance_id, DISCARD_PILE)
    for instance_id in game.state.card_ids_in(DRAW_PILE):
        if game.state.cards_by_id[instance_id].card_key == SHA:
            game._state = game.state.move_card(instance_id, ZoneRef.hand(lord))
            break
    leftover = list(game.state.card_ids_in(DRAW_PILE))
    keep = leftover[:1]
    dump = leftover[1:]
    other = next(pid for pid in game.player_ids if pid not in {lord, rebel})
    if dump:
        game._state = game.state.move_cards(
            {instance_id: ZoneRef.hand(other) for instance_id in dump}
        )
    leftover_discard = list(game.state.card_ids_in(DISCARD_PILE))
    if leftover_discard:
        game._state = game.state.move_cards(
            {instance_id: ZoneRef.hand(other) for instance_id in leftover_discard}
        )
    game._state = _replace_player(game.state, rebel, hp=1)
    _step(game, _require_op(game, "use_slash", targets=(rebel,)))
    if _op(game, "pass_slash_response") is not None:
        _step(game, _require_op(game, "pass_slash_response"))
    while game.phase is ProductionPhase.DYING_RESCUE:
        _step(game, _require_op(game, "pass_rescue"))
    assert game.state.players_by_id[rebel].alive is False
    assert any(event.event_type is EventType.DEATH for event in game.events)
    assert game.is_finished is True
    assert game.winner_id is None
    assert game.runtime.game_over_reason == "identity_draw_deck_exhausted"
    assert not any(event.event_type is EventType.VICTORY for event in game.events)
    gained = [
        event
        for event in game.events
        if event.event_type is EventType.CARD_GAINED
        and event.payload.get("reason") == "identity_kill_rebel_draw"
    ]
    assert 0 < len(gained) < 3
    assert keep[0] in game.state.card_ids_in(ZoneRef.hand(lord))


def test_tiesuo_recast_reshuffles_when_draw_empty() -> None:
    game = _session(16)
    _enter_play(game)
    actor = game.current_player_id
    _strip_hand(game, actor)
    tiesuo = _give_card(game, actor, "sgs_trick_tiesuolianhuan")
    remaining = list(game.state.card_ids_in(DRAW_PILE))
    game._state = game.state.move_cards(
        {instance_id: DISCARD_PILE for instance_id in remaining}
    )
    assert game.state.card_ids_in(DRAW_PILE) == ()
    assert game.state.card_ids_in(DISCARD_PILE)
    before_rng = len(game.rng_calls)
    before_hand = len(game.state.card_ids_in(ZoneRef.hand(actor)))
    _step(game, _require_op(game, "recast_tiesuo"))
    assert game.is_finished is False
    assert len(game.rng_calls) > before_rng
    assert any(
        event.event_type is EventType.CARD_MOVED
        and event.payload.get("reason") == "reshuffle"
        for event in game.events
    )
    assert any(
        event.event_type is EventType.CARD_RECAST
        and event.card_instance_id == tiesuo
        for event in game.events
    )
    assert len(game.state.card_ids_in(ZoneRef.hand(actor))) == before_hand


def test_tiesuo_recast_self_supplies_when_both_piles_empty() -> None:
    """reshuffle_draw：重铸牌先入弃牌堆，两堆动作前为空时仍摸回该牌，不形成平局。"""

    game = _session(17)
    _enter_play(game)
    actor = game.current_player_id
    holder = next(pid for pid in game.player_ids if pid != actor)
    _strip_hand(game, actor)
    tiesuo = _give_card(game, actor, "sgs_trick_tiesuolianhuan")
    _park_away(game, list(game.state.card_ids_in(DRAW_PILE)), holder)
    _park_away(game, list(game.state.card_ids_in(DISCARD_PILE)), holder)
    assert game.state.card_ids_in(DRAW_PILE) == ()
    assert game.state.card_ids_in(DISCARD_PILE) == ()
    _step(game, _require_op(game, "recast_tiesuo"))
    assert game.is_finished is False
    assert game.runtime.game_over_reason is None
    assert tiesuo in game.state.card_ids_in(ZoneRef.hand(actor))


def test_bagua_judgment_reshuffles_when_draw_empty() -> None:
    game = _session(22)
    _enter_play(game)
    lord = game.current_player_id
    victim = next(pid for pid in game.player_ids if pid != lord)
    _strip_hand(game, victim)
    bagua = _give_card(game, victim, "sgs_armor_baguazhen")
    game._state = game.state.move_card(
        bagua, ZoneRef.equipment(victim, "armor")
    )
    _strip_hand(game, lord)
    _give_card(game, lord, SHA)
    qinglong = _give_card(game, lord, "sgs_weapon_qinglongyanyuedao")
    game._state = game.state.move_card(
        qinglong, ZoneRef.equipment(lord, "weapon")
    )
    slash = None
    for action in game.legal_actions():
        if (
            action.payload.get("operation") == "use_slash"
            and victim in action.target_ids
        ):
            slash = action
            break
    assert slash is not None
    _step(game, slash)
    assert _op(game, "activate_bagua") is not None
    remaining = list(game.state.card_ids_in(DRAW_PILE))
    game._state = game.state.move_cards(
        {instance_id: DISCARD_PILE for instance_id in remaining}
    )
    assert game.state.card_ids_in(DRAW_PILE) == ()
    assert game.state.card_ids_in(DISCARD_PILE)
    before_rng = len(game.rng_calls)
    _step(game, _require_op(game, "activate_bagua"))
    assert game.is_finished is False
    assert len(game.rng_calls) > before_rng
    assert any(
        event.event_type is EventType.CARD_MOVED
        and event.payload.get("reason") == "reshuffle"
        for event in game.events
    )
    assert any(
        event.event_type is EventType.ARMOR_JUDGMENT_STARTED
        and event.card_instance_id == bagua
        for event in game.events
    )
    assert any(
        event.event_type is EventType.ARMOR_JUDGMENT_RESULT for event in game.events
    )


def test_bagua_judgment_exhaustion_is_formal_draw() -> None:
    game = _session(24)
    _enter_play(game)
    lord = game.current_player_id
    victim = next(pid for pid in game.player_ids if pid != lord)
    holder = next(
        pid for pid in game.player_ids if pid not in {lord, victim}
    )
    _strip_hand(game, victim)
    bagua = _give_card(game, victim, "sgs_armor_baguazhen")
    game._state = game.state.move_card(
        bagua, ZoneRef.equipment(victim, "armor")
    )
    _strip_hand(game, lord)
    _give_card(game, lord, SHA)
    qinglong = _give_card(game, lord, "sgs_weapon_qinglongyanyuedao")
    game._state = game.state.move_card(
        qinglong, ZoneRef.equipment(lord, "weapon")
    )
    slash = None
    for action in game.legal_actions():
        if (
            action.payload.get("operation") == "use_slash"
            and victim in action.target_ids
        ):
            slash = action
            break
    assert slash is not None
    _step(game, slash)
    assert _op(game, "activate_bagua") is not None
    _park_away(game, list(game.state.card_ids_in(DRAW_PILE)), holder)
    _park_away(game, list(game.state.card_ids_in(DISCARD_PILE)), holder)
    _step(game, _require_op(game, "activate_bagua"))
    assert game.is_finished is True
    assert game.winner_id is None
    assert game.runtime.game_over_reason == "identity_draw_deck_exhausted"
    assert any(event.event_type is EventType.DRAW for event in game.events)
    assert bagua in game.state.card_ids_in(ZoneRef.equipment(victim, "armor"))


def test_wugu_revealed_pool_reshuffles_across_draw_and_discard() -> None:
    game = _session(20)
    _enter_play(game)
    actor = game.current_player_id
    holder = next(pid for pid in game.player_ids if pid != actor)
    _strip_hand(game, actor)
    wugu = _give_card(game, actor, "sgs_trick_wugufengdeng")
    draw_ids = list(game.state.card_ids_in(DRAW_PILE))
    _park_away(game, draw_ids[2:], holder)
    extra = list(game.state.card_ids_in(ZoneRef.hand(holder)))[:3]
    game._state = game.state.move_cards(
        {instance_id: DISCARD_PILE for instance_id in extra}
    )
    assert len(game.state.card_ids_in(DRAW_PILE)) == 2
    assert game.state.card_ids_in(DISCARD_PILE)
    start = len(game.events)
    _step(game, _require_op(game, "use_wugu"))
    assert game.is_finished is False
    assert wugu in game.state.card_ids_in(PROCESSING_ZONE)
    revealed = list(game.state.card_ids_in(REVEALED_ZONE))
    assert len(revealed) == 5
    already_revealed: list[str] = []
    reshuffles = []
    for event in game.events[start:]:
        if (
            event.event_type is EventType.CARD_REVEALED
            and event.payload.get("reason") == "wugu_reveal"
            and event.card_instance_id is not None
        ):
            already_revealed.append(event.card_instance_id)
        if (
            event.event_type is EventType.CARD_MOVED
            and event.payload.get("reason") == "reshuffle"
        ):
            reshuffles.append(event)
            assert event.payload.get("source", {}).get("kind") == "discard_pile"
            assert event.payload.get("destination", {}).get("kind") == "draw_pile"
            assert event.card_instance_id != wugu
            assert event.card_instance_id not in already_revealed
    assert reshuffles
    assert len(already_revealed) == 5


def test_wugu_revealed_pool_exhaustion_keeps_revealed_then_cleans_once() -> None:
    game = _session(23)
    _enter_play(game)
    actor = game.current_player_id
    holder = next(pid for pid in game.player_ids if pid != actor)
    _strip_hand(game, actor)
    wugu = _give_card(game, actor, "sgs_trick_wugufengdeng")
    draw_ids = list(game.state.card_ids_in(DRAW_PILE))
    keep = draw_ids[:2]
    _park_away(game, draw_ids[2:], holder)
    _park_away(game, list(game.state.card_ids_in(DISCARD_PILE)), holder)
    assert len(game.state.card_ids_in(DRAW_PILE)) == 2
    assert game.state.card_ids_in(DISCARD_PILE) == ()
    start = len(game.events)
    _step(game, _require_op(game, "use_wugu"))
    assert game.is_finished is True
    assert game.winner_id is None
    assert game.runtime.game_over_reason == "identity_draw_deck_exhausted"
    new_events = game.events[start:]
    revealed_events = [
        event
        for event in new_events
        if event.event_type is EventType.CARD_REVEALED
        and event.payload.get("reason") == "wugu_reveal"
    ]
    assert [event.card_instance_id for event in revealed_events] == keep
    draw_events = [
        event for event in new_events if event.event_type is EventType.DRAW
    ]
    assert len(draw_events) == 1
    assert revealed_events[-1].sequence < draw_events[0].sequence
    cleanups = [
        event
        for event in new_events
        if event.payload.get("reason") == "draw_game_over_cleanup"
    ]
    assert cleanups
    assert all(
        event.sequence > draw_events[0].sequence for event in cleanups
    )
    assert game.state.card_ids_in(REVEALED_ZONE) == ()
    assert game.state.card_ids_in(PROCESSING_ZONE) == ()
    for instance_id in keep:
        assert game.state.location_of(instance_id) == DISCARD_PILE
    assert wugu not in game.state.card_ids_in(PROCESSING_ZONE)


def test_cixiong_not_applicable_in_no_skill_soldier_profile() -> None:
    game = _session(24)
    for player in game.state.players:
        assert player.character.gender.value == "none"
    _enter_play(game)
    operations = {action.payload.get("operation") for action in game.legal_actions()}
    assert "cixiong_allow_draw" not in operations
    assert "activate_cixiong" not in operations


def test_hand_equipment_judgment_not_reshuffled() -> None:
    from dataclasses import replace
    from types import MappingProxyType

    game = _session(25)
    _enter_play(game)
    actor = game.current_player_id
    delayed = next(
        instance_id
        for instance_id, card in game.state.cards_by_id.items()
        if card.card_key == "sgs_delayed_lebusi"
    )
    equipped = next(
        instance_id
        for instance_id, card in game.state.cards_by_id.items()
        if card.card_key == "sgs_weapon_qinglongyanyuedao"
    )
    game._state = game.state.move_card(delayed, ZoneRef.judgment(actor))
    game._state = game.state.move_card(
        equipped, ZoneRef.equipment(actor, "weapon")
    )
    game._runtime = replace(
        game.runtime,
        judgment_entry_indices=MappingProxyType({delayed: 1}),
        judgment_entry_counter=1,
    )
    _end_play_to_next_prepare(game)
    _step(game, _require_op(game, "proceed_prepare"))
    _step(game, _require_op(game, "proceed_judgment"))
    _drain_draw_to(game, 0)
    _step(game, _require_op(game, "proceed_draw"))
    assert game.state.location_of(delayed) == ZoneRef.judgment(actor)
    assert game.state.location_of(equipped) == ZoneRef.equipment(
        actor, "weapon"
    )
