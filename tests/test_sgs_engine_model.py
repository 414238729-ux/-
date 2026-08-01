from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

from scripts.deck_data import DeckRecord, load_deck_csv
from scripts.sgs_engine.model import (
    DISCARD_PILE,
    DRAW_PILE,
    CardInstance,
    GameState,
    ModelValidationError,
    PlayerState,
    ZoneKind,
    ZoneRef,
)


DECK_PATH = (
    Path(__file__).resolve().parents[1]
    / "knowledge"
    / "三国杀牌堆数据.csv"
)


@pytest.fixture(scope="module")
def formal_deck_records() -> tuple[DeckRecord, ...]:
    records, audit = load_deck_csv(DECK_PATH, expected_total=160)
    assert audit.is_valid
    return records


@pytest.fixture
def players() -> tuple[PlayerState, PlayerState]:
    return (
        PlayerState(player_id="玩家甲", seat=1, hp=4, max_hp=4),
        PlayerState(player_id="玩家乙", seat=2, hp=3, max_hp=3),
    )


def test_formal_deck_builds_160_unique_immutable_card_instances(
    formal_deck_records: tuple[DeckRecord, ...],
    players: tuple[PlayerState, PlayerState],
) -> None:
    state = GameState.from_deck_records(formal_deck_records, players=players)

    assert len(state.cards) == 160
    assert len(state.cards_by_id) == 160
    assert len({card.instance_id for card in state.cards}) == 160
    assert state.deck_id == "sgs_mobile_non_special_20260725_unofficial"
    assert all(state.location_of(card.instance_id) == DRAW_PILE for card in state.cards)
    assert state.card_ids_in(DRAW_PILE)[:3] == (
        "sgs-mobile-20260725-001",
        "sgs-mobile-20260725-002",
        "sgs-mobile-20260725-003",
    )
    assert state.cards[0] == CardInstance.from_deck_record(formal_deck_records[0])
    assert state.cards[0].instance_id == "sgs-mobile-20260725-001"
    assert state.cards[0].card_name == "诸葛连弩"

    with pytest.raises(FrozenInstanceError):
        state.cards[0].card_name = "被篡改"  # type: ignore[misc]
    with pytest.raises(TypeError):
        state.card_locations[state.cards[0].instance_id] = DISCARD_PILE  # type: ignore[index]
    with pytest.raises(TypeError):
        state.zone_order[DRAW_PILE] = ()  # type: ignore[index]


def test_move_card_returns_new_state_and_preserves_every_entity(
    formal_deck_records: tuple[DeckRecord, ...],
    players: tuple[PlayerState, PlayerState],
) -> None:
    before = GameState.from_deck_records(formal_deck_records, players=players)
    instance_id = before.cards[10].instance_id

    after = before.move_card(instance_id, ZoneRef.hand("玩家甲"))

    assert before.location_of(instance_id) == DRAW_PILE
    assert after.location_of(instance_id) == ZoneRef.hand("玩家甲")
    assert len(before.cards_in(DRAW_PILE)) == 160
    assert len(after.cards_in(DRAW_PILE)) == 159
    assert after.cards_in(ZoneRef.hand("玩家甲")) == (before.cards[10],)
    assert after.revision == before.revision + 1
    assert after.cards == before.cards
    after.assert_card_conservation()


def test_move_cards_preserves_call_order_at_destination_tail(
    formal_deck_records: tuple[DeckRecord, ...],
    players: tuple[PlayerState, PlayerState],
) -> None:
    state = GameState.from_deck_records(formal_deck_records, players=players)
    first_id, second_id, third_id = state.card_ids_in(DRAW_PILE)[:3]

    moved = state.move_card(third_id, DISCARD_PILE).move_cards(
        {
            second_id: DISCARD_PILE,
            first_id: DISCARD_PILE,
        }
    )

    assert moved.card_ids_in(DISCARD_PILE) == (third_id, second_id, first_id)
    assert moved.card_ids_in(DRAW_PILE)[:2] == (
        "sgs-mobile-20260725-004",
        "sgs-mobile-20260725-005",
    )
    assert all(moved.location_of(instance_id) == DISCARD_PILE for instance_id in (
        third_id,
        second_id,
        first_id,
    ))
    moved.assert_card_conservation()


def test_global_and_player_zones_have_explicit_ownership_boundaries() -> None:
    assert ZoneRef.global_zone(ZoneKind.DISCARD_PILE) == DISCARD_PILE
    assert ZoneRef.hand("玩家甲").kind.is_player_zone
    assert DRAW_PILE.kind.is_global

    with pytest.raises(ModelValidationError, match="全局区域不能设置玩家"):
        ZoneRef(ZoneKind.DRAW_PILE, owner_id="玩家甲")
    with pytest.raises(ModelValidationError, match="必须设置区域所有者"):
        ZoneRef(ZoneKind.HAND)
    with pytest.raises(ModelValidationError, match="特殊区必须设置明确"):
        ZoneRef(ZoneKind.SPECIAL, owner_id="玩家甲")
    with pytest.raises(ModelValidationError, match="合法装备栏"):
        ZoneRef.equipment("玩家甲", "两个武器栏")


def test_game_state_rejects_missing_unknown_and_nonexistent_owner(
    formal_deck_records: tuple[DeckRecord, ...],
    players: tuple[PlayerState, PlayerState],
) -> None:
    cards = tuple(
        CardInstance.from_deck_record(record)
        for record in formal_deck_records[:2]
    )
    with pytest.raises(ModelValidationError, match="缺少位置"):
        GameState(
            cards=cards,
            players=players,
            card_locations={cards[0].instance_id: DRAW_PILE},
        )


def test_zone_order_rejects_duplicate_missing_unknown_and_location_mismatch(
    formal_deck_records: tuple[DeckRecord, ...],
    players: tuple[PlayerState, PlayerState],
) -> None:
    cards = tuple(
        CardInstance.from_deck_record(record)
        for record in formal_deck_records[:2]
    )
    locations = {
        cards[0].instance_id: DRAW_PILE,
        cards[1].instance_id: DRAW_PILE,
    }

    with pytest.raises(ModelValidationError, match="区域顺序中实体牌重复"):
        GameState(
            cards=cards,
            players=players,
            card_locations=locations,
            zone_order={
                DRAW_PILE: (cards[0].instance_id, cards[0].instance_id),
            },
        )
    with pytest.raises(ModelValidationError, match="顺序表缺少"):
        GameState(
            cards=cards,
            players=players,
            card_locations=locations,
            zone_order={DRAW_PILE: (cards[0].instance_id,)},
        )
    with pytest.raises(ModelValidationError, match="顺序表含未知实体牌"):
        GameState(
            cards=cards,
            players=players,
            card_locations=locations,
            zone_order={
                DRAW_PILE: (
                    cards[0].instance_id,
                    cards[1].instance_id,
                    "不存在的牌",
                )
            },
        )
    with pytest.raises(ModelValidationError, match="位置表为 draw_pile"):
        GameState(
            cards=cards,
            players=players,
            card_locations=locations,
            zone_order={
                DRAW_PILE: (cards[0].instance_id,),
                DISCARD_PILE: (cards[1].instance_id,),
            },
        )
    with pytest.raises(ModelValidationError, match="未知实体牌"):
        GameState(
            cards=cards,
            players=players,
            card_locations={
                cards[0].instance_id: DRAW_PILE,
                cards[1].instance_id: DRAW_PILE,
                "不存在的牌": DRAW_PILE,
            },
        )
    with pytest.raises(ModelValidationError, match="区域所有者.*不存在"):
        GameState(
            cards=cards,
            players=players,
            card_locations={
                cards[0].instance_id: ZoneRef.hand("旁观者"),
                cards[1].instance_id: DRAW_PILE,
            },
        )


def test_player_life_state_allows_dying_but_rejects_dead_with_positive_hp() -> None:
    dying = PlayerState("濒死角色", 1, 0, 4, alive=True)
    dead = PlayerState("死亡角色", 1, 0, 4, alive=False)

    assert dying.alive is True
    assert dead.alive is False
    with pytest.raises(ModelValidationError, match="已确认死亡.*不能大于0"):
        PlayerState("矛盾角色", 1, 1, 4, alive=False)


def test_seats_are_unique_positive_and_contiguous() -> None:
    with pytest.raises(ModelValidationError, match="座次不能重复"):
        GameState(
            cards=(),
            players=(
                PlayerState("玩家甲", 1, 4, 4),
                PlayerState("玩家乙", 1, 4, 4),
            ),
            card_locations={},
        )
    with pytest.raises(ModelValidationError, match="从1开始连续编号"):
        GameState(
            cards=(),
            players=(
                PlayerState("玩家甲", 1, 4, 4),
                PlayerState("玩家乙", 3, 4, 4),
            ),
            card_locations={},
        )
    with pytest.raises(ModelValidationError, match="大于或等于1"):
        PlayerState("玩家甲", 0, 4, 4)


def test_equipment_zone_validates_card_slot_and_single_slot_occupancy(
    formal_deck_records: tuple[DeckRecord, ...],
    players: tuple[PlayerState, PlayerState],
) -> None:
    state = GameState.from_deck_records(formal_deck_records, players=players)
    crossbows = [card for card in state.cards if card.card_name == "诸葛连弩"]
    assert len(crossbows) == 2
    equipped = state.move_card(
        crossbows[0].instance_id,
        ZoneRef.equipment("玩家甲", "weapon"),
    )
    assert equipped.location_of(crossbows[0].instance_id) == ZoneRef.equipment(
        "玩家甲", "weapon"
    )

    with pytest.raises(ModelValidationError, match="同时存在实体牌"):
        equipped.move_card(
            crossbows[1].instance_id,
            ZoneRef.equipment("玩家甲", "weapon"),
        )
    with pytest.raises(ModelValidationError, match="装备栏应为 weapon"):
        state.move_card(
            crossbows[0].instance_id,
            ZoneRef.equipment("玩家甲", "armor"),
        )


def test_atomic_equipment_replacement_requires_old_card_to_leave_slot(
    formal_deck_records: tuple[DeckRecord, ...],
    players: tuple[PlayerState, PlayerState],
) -> None:
    state = GameState.from_deck_records(formal_deck_records, players=players)
    weapons = [card for card in state.cards if card.equipment_slot == "weapon"]
    first, second = weapons[:2]
    equipped = state.move_card(
        first.instance_id,
        ZoneRef.equipment("玩家甲", "weapon"),
    )

    replaced_state = equipped.move_cards(
        {
            first.instance_id: DISCARD_PILE,
            second.instance_id: ZoneRef.equipment("玩家甲", "weapon"),
        }
    )

    assert replaced_state.location_of(first.instance_id) == DISCARD_PILE
    assert replaced_state.location_of(second.instance_id) == ZoneRef.equipment(
        "玩家甲", "weapon"
    )
    replaced_state.assert_card_conservation()


def test_reorder_zone_changes_only_order_and_validates_full_zone(
    formal_deck_records: tuple[DeckRecord, ...],
    players: tuple[PlayerState, PlayerState],
) -> None:
    state = GameState.from_deck_records(formal_deck_records, players=players)
    original_order = state.card_ids_in(DRAW_PILE)
    reversed_order = tuple(reversed(original_order))

    shuffled = state.reorder_zone(DRAW_PILE, reversed_order)

    assert state.card_ids_in(DRAW_PILE) == original_order
    assert shuffled.card_ids_in(DRAW_PILE) == reversed_order
    assert shuffled.card_locations == state.card_locations
    assert shuffled.revision == state.revision + 1
    shuffled.assert_card_conservation()

    with pytest.raises(ModelValidationError, match="区域新顺序不能包含重复"):
        state.reorder_zone(
            DRAW_PILE,
            (original_order[0], original_order[0], *original_order[2:]),
        )
    with pytest.raises(ModelValidationError, match="必须覆盖该区域全部实体牌"):
        state.reorder_zone(DRAW_PILE, original_order[:-1])
    with pytest.raises(ModelValidationError, match="不属于该区域"):
        empty_discard = state.card_ids_in(DISCARD_PILE)
        assert empty_discard == ()
        state.reorder_zone(DISCARD_PILE, (original_order[0],))


def test_aggregated_deck_record_cannot_be_silently_expanded(
    formal_deck_records: tuple[DeckRecord, ...],
) -> None:
    aggregated = replace(formal_deck_records[0], quantity=2)

    with pytest.raises(ModelValidationError, match="一行一张且quantity=1"):
        CardInstance.from_deck_record(aggregated)


def test_game_state_rejects_mixed_deck_ids(
    formal_deck_records: tuple[DeckRecord, ...],
    players: tuple[PlayerState, PlayerState],
) -> None:
    first = CardInstance.from_deck_record(formal_deck_records[0])
    second = replace(
        CardInstance.from_deck_record(formal_deck_records[1]),
        deck_id="另一个牌堆",
    )

    with pytest.raises(ModelValidationError, match="不能静默混合多个deck_id"):
        GameState(
            cards=(first, second),
            players=players,
            card_locations={
                first.instance_id: DRAW_PILE,
                second.instance_id: DRAW_PILE,
            },
        )
