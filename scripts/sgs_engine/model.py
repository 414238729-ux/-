"""三国杀权威规则核心的不可变实体与卡牌位置模型。

本模块只负责保存事实状态和验证状态不变量，不实现任何卡牌效果、武将
技能、AI 决策或概率近似。每张实体牌在一个 :class:`GameState` 中必须且
只能出现于一个区域；状态变化返回新的 ``GameState``，不会原地修改旧状态。
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from types import MappingProxyType
from typing import Iterable, Mapping

from ..deck_data import DeckRecord


class ModelValidationError(ValueError):
    """权威状态不满足不变量时抛出的中文异常。"""


def _nonempty_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ModelValidationError(f"{label}必须是非空字符串")
    return value.strip()


def _strict_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ModelValidationError(f"{label}必须是整数")
    return value


class ZoneKind(str, Enum):
    """规则核心支持的全局区域与玩家区域。"""

    DRAW_PILE = "draw_pile"
    DISCARD_PILE = "discard_pile"
    PROCESSING = "processing"
    REMOVED_FROM_GAME = "removed_from_game"
    REVEALED = "revealed"
    HAND = "hand"
    EQUIPMENT = "equipment"
    JUDGMENT = "judgment"
    SPECIAL = "special"

    @property
    def is_global(self) -> bool:
        return self in GLOBAL_ZONE_KINDS

    @property
    def is_player_zone(self) -> bool:
        return self in PLAYER_ZONE_KINDS


class CharacterGender(str, Enum):
    """会影响卡牌规则的权威角色性别。

    未装配角色由 ``PlayerState.character is None`` 表达；角色已装配但
    性别资料未确认则由 ``CharacterMetadata.gender is None`` 表达。需要
    性别的规则对两种未知状态都必须失败关闭。

    ``NONE`` 表示“无性别／当前视为无性别”这一有效规则状态（例如国战
    中两张武将牌均未明置时当前视为无性别）；它不是资料缺失，任何要求
    角色为男性/女性、或比较双方性别的效果都不得把 NONE 当作男或女，
    也不得把两个 NONE 视为“异性”。``gender is None``（资料未确认）与
    ``gender is CharacterGender.NONE``（确认无性别）语义必须严格区分。
    """

    MALE = "male"
    FEMALE = "female"
    NONE = "none"


@dataclass(frozen=True, slots=True)
class CharacterMetadata:
    """可被未来武将系统复用的最小角色身份元数据。

    同时保存 ``intrinsic_gender``（角色固有性别）与 ``effective_gender``
    （当前生效性别）。两者可以不同（例如 intrinsic=MALE、
    effective=NONE），以便规则效果读取当前生效性别而不无条件使用固有
    性别。``effective_gender`` 为 ``None`` 时表示“无独立覆盖”，读取方应
    回退到 ``intrinsic_gender``；这与 ``CharacterGender.NONE``（确认
    无性别）严格区分。``gender`` 属性保留为 ``intrinsic_gender`` 的只读
    兼容别名。
    """

    character_key: str
    intrinsic_gender: CharacterGender | str | None = None
    effective_gender: CharacterGender | str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "character_key",
            _nonempty_text(self.character_key, "角色规则键"),
        )
        object.__setattr__(
            self,
            "intrinsic_gender",
            _coerce_character_gender(self.intrinsic_gender, "角色固有性别"),
        )
        object.__setattr__(
            self,
            "effective_gender",
            _coerce_character_gender(self.effective_gender, "角色生效性别"),
        )

    @property
    def gender(self) -> CharacterGender | None:
        """兼容只读别名：返回角色固有性别（intrinsic）。"""

        return self.intrinsic_gender


def _coerce_character_gender(
    value: CharacterGender | str | None, label: str
) -> CharacterGender | None:
    """把角色性别字段规范化为枚举；None（资料未知）保持严格区分。"""

    if value is None:
        return None
    if isinstance(value, CharacterGender):
        return value
    try:
        return CharacterGender(value)
    except (TypeError, ValueError) as exc:
        allowed = "、".join(item.value for item in CharacterGender)
        raise ModelValidationError(f"{label}只能是：{allowed}") from exc


GLOBAL_ZONE_KINDS: frozenset[ZoneKind] = frozenset(
    {
        ZoneKind.DRAW_PILE,
        ZoneKind.DISCARD_PILE,
        ZoneKind.PROCESSING,
        ZoneKind.REMOVED_FROM_GAME,
        ZoneKind.REVEALED,
    }
)
PLAYER_ZONE_KINDS: frozenset[ZoneKind] = frozenset(
    {
        ZoneKind.HAND,
        ZoneKind.EQUIPMENT,
        ZoneKind.JUDGMENT,
        ZoneKind.SPECIAL,
    }
)
EQUIPMENT_SLOTS: frozenset[str] = frozenset(
    {"weapon", "armor", "attack_horse", "defense_horse", "treasure"}
)


def _coerce_zone_kind(value: ZoneKind | str) -> ZoneKind:
    if isinstance(value, ZoneKind):
        return value
    try:
        return ZoneKind(value)
    except (TypeError, ValueError) as exc:
        allowed = "、".join(item.value for item in ZoneKind)
        raise ModelValidationError(f"区域类型只能是：{allowed}") from exc


@dataclass(frozen=True, slots=True)
class ZoneRef:
    """一张实体牌所在区域的完整引用。

    全局区域不带 ``owner_id``；玩家区域必须带 ``owner_id``。装备区还必须
    指明装备栏，特殊区必须指明区域名称，避免把“武将牌上的权”等不同区域
    静默合并。
    """

    kind: ZoneKind | str
    owner_id: str | None = None
    equipment_slot: str | None = None
    special_zone: str | None = None

    def __post_init__(self) -> None:
        kind = _coerce_zone_kind(self.kind)
        object.__setattr__(self, "kind", kind)
        owner = None if self.owner_id is None else _nonempty_text(
            self.owner_id, "区域所有者"
        )
        slot = None if self.equipment_slot is None else _nonempty_text(
            self.equipment_slot, "装备栏"
        )
        special = None if self.special_zone is None else _nonempty_text(
            self.special_zone, "特殊区域名称"
        )
        object.__setattr__(self, "owner_id", owner)
        object.__setattr__(self, "equipment_slot", slot)
        object.__setattr__(self, "special_zone", special)

        if kind.is_global:
            if owner is not None or slot is not None or special is not None:
                raise ModelValidationError("全局区域不能设置玩家、装备栏或特殊区名称")
            return

        if owner is None:
            raise ModelValidationError(f"玩家区域 {kind.value} 必须设置区域所有者")
        if kind is ZoneKind.EQUIPMENT:
            if slot not in EQUIPMENT_SLOTS:
                allowed = "、".join(sorted(EQUIPMENT_SLOTS))
                raise ModelValidationError(f"装备区必须指定合法装备栏：{allowed}")
            if special is not None:
                raise ModelValidationError("装备区不能同时设置特殊区域名称")
        elif slot is not None:
            raise ModelValidationError("只有装备区可以设置装备栏")

        if kind is ZoneKind.SPECIAL:
            if special is None:
                raise ModelValidationError("特殊区必须设置明确的特殊区域名称")
        elif special is not None:
            raise ModelValidationError("只有特殊区可以设置特殊区域名称")

    @classmethod
    def global_zone(cls, kind: ZoneKind | str) -> "ZoneRef":
        return cls(kind=kind)

    @classmethod
    def hand(cls, owner_id: str) -> "ZoneRef":
        return cls(kind=ZoneKind.HAND, owner_id=owner_id)

    @classmethod
    def equipment(cls, owner_id: str, slot: str) -> "ZoneRef":
        return cls(
            kind=ZoneKind.EQUIPMENT,
            owner_id=owner_id,
            equipment_slot=slot,
        )

    @classmethod
    def judgment(cls, owner_id: str) -> "ZoneRef":
        return cls(kind=ZoneKind.JUDGMENT, owner_id=owner_id)

    @classmethod
    def special(cls, owner_id: str, name: str) -> "ZoneRef":
        return cls(
            kind=ZoneKind.SPECIAL,
            owner_id=owner_id,
            special_zone=name,
        )


DRAW_PILE = ZoneRef.global_zone(ZoneKind.DRAW_PILE)
DISCARD_PILE = ZoneRef.global_zone(ZoneKind.DISCARD_PILE)
PROCESSING_ZONE = ZoneRef.global_zone(ZoneKind.PROCESSING)
REMOVED_FROM_GAME = ZoneRef.global_zone(ZoneKind.REMOVED_FROM_GAME)
REVEALED_ZONE = ZoneRef.global_zone(ZoneKind.REVEALED)


@dataclass(frozen=True, slots=True)
class CardInstance:
    """由正式牌堆的一行转换而来的不可变实体牌。"""

    instance_id: str
    deck_id: str
    card_key: str
    card_name: str
    card_type: str
    suit: str
    color: str
    rank: str
    card_variant: str = ""
    equipment_slot: str | None = None
    distance_modifier: int | None = None

    def __post_init__(self) -> None:
        for field_name, label in (
            ("instance_id", "实体牌ID"),
            ("deck_id", "牌堆ID"),
            ("card_key", "卡牌规则键"),
            ("card_name", "牌名"),
            ("card_type", "卡牌类别"),
            ("suit", "花色"),
            ("color", "颜色"),
            ("rank", "点数"),
        ):
            object.__setattr__(
                self,
                field_name,
                _nonempty_text(getattr(self, field_name), label),
            )
        if not isinstance(self.card_variant, str):
            raise ModelValidationError("卡牌变体必须是字符串")
        object.__setattr__(self, "card_variant", self.card_variant.strip())

        slot = self.equipment_slot
        if slot is not None:
            slot = _nonempty_text(slot, "实体牌装备栏")
            if slot not in EQUIPMENT_SLOTS:
                allowed = "、".join(sorted(EQUIPMENT_SLOTS))
                raise ModelValidationError(f"实体牌装备栏只能是：{allowed}")
        object.__setattr__(self, "equipment_slot", slot)
        if self.card_type == "装备牌" and slot is None:
            raise ModelValidationError(f"装备牌【{self.card_name}】缺少装备栏")
        if self.card_type != "装备牌" and slot is not None:
            raise ModelValidationError(f"非装备牌【{self.card_name}】不能设置装备栏")

        modifier = self.distance_modifier
        if modifier is not None:
            modifier = _strict_int(modifier, "距离修正")
            if slot not in {"attack_horse", "defense_horse"}:
                raise ModelValidationError("只有坐骑实体牌可以设置距离修正")
            expected = -1 if slot == "attack_horse" else 1
            if modifier != expected:
                raise ModelValidationError(
                    f"装备栏 {slot} 的距离修正必须为 {expected:+d}"
                )
        object.__setattr__(self, "distance_modifier", modifier)

    @classmethod
    def from_deck_record(cls, record: DeckRecord) -> "CardInstance":
        """将一行真实 ``DeckRecord`` 转成唯一实体牌，不展开聚合数量。"""

        if not isinstance(record, DeckRecord):
            raise TypeError("实体牌来源必须是DeckRecord")
        if record.quantity != 1:
            raise ModelValidationError(
                "权威实体牌模型要求DeckRecord一行一张且quantity=1"
            )
        instance_id = _nonempty_text(record.instance_id, "DeckRecord.instance_id")
        modifier_text = record.distance_modifier.strip()
        modifier: int | None
        if modifier_text:
            try:
                modifier = int(modifier_text)
            except ValueError as exc:
                raise ModelValidationError(
                    f"实体牌 {instance_id} 的distance_modifier必须是整数"
                ) from exc
        else:
            modifier = None
        return cls(
            instance_id=instance_id,
            deck_id=record.deck_id,
            card_key=record.card_key,
            card_name=record.card_name,
            card_type=record.card_type,
            suit=record.suit,
            color=record.color,
            rank=record.rank,
            card_variant=record.card_variant,
            equipment_slot=record.equip_slot or None,
            distance_modifier=modifier,
        )


@dataclass(frozen=True, slots=True)
class PlayerState:
    """不可变的玩家身份、座次与体力基础状态。"""

    player_id: str
    seat: int
    hp: int
    max_hp: int
    alive: bool = True
    chained: bool = False
    character: CharacterMetadata | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "player_id", _nonempty_text(self.player_id, "玩家ID"))
        seat = _strict_int(self.seat, "玩家座次")
        if seat < 1:
            raise ModelValidationError("玩家座次必须大于或等于1")
        object.__setattr__(self, "seat", seat)
        hp = _strict_int(self.hp, "当前体力")
        max_hp = _strict_int(self.max_hp, "体力上限")
        if max_hp < 1:
            raise ModelValidationError("体力上限必须大于或等于1")
        if hp > max_hp:
            raise ModelValidationError("当前体力不能高于体力上限")
        if not isinstance(self.alive, bool):
            raise ModelValidationError("存活状态必须是布尔值")
        if not self.alive and hp > 0:
            raise ModelValidationError("已确认死亡的角色当前体力不能大于0")
        if not isinstance(self.chained, bool):
            raise ModelValidationError("横置状态必须是布尔值")
        if self.character is not None and not isinstance(
            self.character, CharacterMetadata
        ):
            raise ModelValidationError(
                "角色元数据必须是CharacterMetadata或None"
            )
        object.__setattr__(self, "hp", hp)
        object.__setattr__(self, "max_hp", max_hp)


@dataclass(frozen=True, slots=True)
class GameState:
    """实体牌位置唯一且守恒的不可变游戏状态。

    ``cards`` 保存整局固定的实体牌目录，``card_locations`` 保存每张实体牌
    当前唯一位置，``zone_order`` 保存每个区域内实体牌的权威顺序。顺序元组
    的第一项是牌堆顶（或该区域队首），最后一项是区域尾端。移动牌不会复制
    或删除实体牌，且位置表与顺序表必须始终互相一致。
    """

    cards: tuple[CardInstance, ...]
    players: tuple[PlayerState, ...]
    card_locations: Mapping[str, ZoneRef]
    zone_order: Mapping[ZoneRef, tuple[str, ...]] | None = None
    deck_id: str = ""
    revision: int = 0

    def __post_init__(self) -> None:
        try:
            cards = tuple(self.cards)
        except TypeError as exc:
            raise TypeError("实体牌目录必须是CardInstance可迭代对象") from exc
        if any(not isinstance(card, CardInstance) for card in cards):
            raise TypeError("实体牌目录中的每一项都必须是CardInstance")
        card_ids = tuple(card.instance_id for card in cards)
        if len(card_ids) != len(set(card_ids)):
            raise ModelValidationError("实体牌ID不能重复")
        object.__setattr__(self, "cards", cards)

        try:
            players = tuple(self.players)
        except TypeError as exc:
            raise TypeError("玩家目录必须是PlayerState可迭代对象") from exc
        if any(not isinstance(player, PlayerState) for player in players):
            raise TypeError("玩家目录中的每一项都必须是PlayerState")
        player_ids = tuple(player.player_id for player in players)
        seats = tuple(player.seat for player in players)
        if len(player_ids) != len(set(player_ids)):
            raise ModelValidationError("玩家ID不能重复")
        if len(seats) != len(set(seats)):
            raise ModelValidationError("玩家座次不能重复")
        if sorted(seats) != list(range(1, len(players) + 1)):
            raise ModelValidationError("玩家座次必须从1开始连续编号")
        object.__setattr__(self, "players", players)

        if not isinstance(self.card_locations, Mapping):
            raise TypeError("实体牌位置必须是instance_id到ZoneRef的映射")
        locations = dict(self.card_locations)
        if any(not isinstance(key, str) or not key.strip() for key in locations):
            raise ModelValidationError("实体牌位置映射的键必须是非空instance_id")
        if any(not isinstance(zone, ZoneRef) for zone in locations.values()):
            raise TypeError("实体牌位置映射的值必须是ZoneRef")
        card_id_set = set(card_ids)
        location_id_set = set(locations)
        missing = sorted(card_id_set - location_id_set)
        extra = sorted(location_id_set - card_id_set)
        if missing or extra:
            details: list[str] = []
            if missing:
                details.append(f"缺少位置：{'、'.join(missing)}")
            if extra:
                details.append(f"未知实体牌：{'、'.join(extra)}")
            raise ModelValidationError("实体牌位置不守恒；" + "；".join(details))

        player_id_set = set(player_ids)
        cards_by_id = {card.instance_id: card for card in cards}
        occupied_slots: dict[tuple[str, str], str] = {}
        for instance_id, zone in locations.items():
            if zone.kind.is_player_zone and zone.owner_id not in player_id_set:
                raise ModelValidationError(
                    f"实体牌 {instance_id} 的区域所有者 {zone.owner_id!r} 不存在"
                )
            if zone.kind is not ZoneKind.EQUIPMENT:
                continue
            card = cards_by_id[instance_id]
            if card.card_type != "装备牌" or card.equipment_slot is None:
                raise ModelValidationError(
                    f"非装备实体牌 {instance_id} 不能置于装备区"
                )
            if card.equipment_slot != zone.equipment_slot:
                raise ModelValidationError(
                    f"实体牌 {instance_id} 的装备栏应为 {card.equipment_slot}，"
                    f"不能置于 {zone.equipment_slot}"
                )
            slot_key = (zone.owner_id or "", zone.equipment_slot or "")
            previous = occupied_slots.get(slot_key)
            if previous is not None:
                raise ModelValidationError(
                    f"玩家 {zone.owner_id} 的装备栏 {zone.equipment_slot} "
                    f"同时存在实体牌 {previous} 与 {instance_id}"
                )
            occupied_slots[slot_key] = instance_id
        object.__setattr__(self, "card_locations", MappingProxyType(locations))

        if self.zone_order is None:
            inferred_order: dict[ZoneRef, list[str]] = {}
            for card in cards:
                zone = locations[card.instance_id]
                inferred_order.setdefault(zone, []).append(card.instance_id)
            raw_zone_order: Mapping[ZoneRef, object] = inferred_order
        elif isinstance(self.zone_order, Mapping):
            raw_zone_order = self.zone_order
        else:
            raise TypeError("区域顺序必须是ZoneRef到实体牌ID序列的映射")

        normalized_order: dict[ZoneRef, tuple[str, ...]] = {}
        ordered_ids: list[str] = []
        for zone, instance_ids in raw_zone_order.items():
            if not isinstance(zone, ZoneRef):
                raise TypeError("区域顺序映射的键必须是ZoneRef")
            if isinstance(instance_ids, (str, bytes)):
                raise TypeError("区域顺序必须是实体牌ID序列，不能是单个字符串")
            try:
                prepared_ids = tuple(instance_ids)  # type: ignore[arg-type]
            except TypeError as exc:
                raise TypeError("区域顺序必须是可迭代的实体牌ID序列") from exc
            for instance_id in prepared_ids:
                if not isinstance(instance_id, str) or not instance_id.strip():
                    raise ModelValidationError("区域顺序中的实体牌ID必须是非空字符串")
            normalized_order[zone] = prepared_ids
            ordered_ids.extend(prepared_ids)

        if len(ordered_ids) != len(set(ordered_ids)):
            duplicates = sorted(
                {
                    instance_id
                    for instance_id in ordered_ids
                    if ordered_ids.count(instance_id) > 1
                }
            )
            raise ModelValidationError(
                f"区域顺序中实体牌重复：{'、'.join(duplicates)}"
            )
        ordered_id_set = set(ordered_ids)
        missing_from_order = sorted(card_id_set - ordered_id_set)
        extra_in_order = sorted(ordered_id_set - card_id_set)
        if missing_from_order or extra_in_order:
            details = []
            if missing_from_order:
                details.append(f"顺序表缺少：{'、'.join(missing_from_order)}")
            if extra_in_order:
                details.append(f"顺序表含未知实体牌：{'、'.join(extra_in_order)}")
            raise ModelValidationError("区域顺序不守恒；" + "；".join(details))
        for zone, instance_ids in normalized_order.items():
            for instance_id in instance_ids:
                actual_zone = locations[instance_id]
                if actual_zone != zone:
                    raise ModelValidationError(
                        f"实体牌 {instance_id} 的位置表为 {actual_zone.kind.value}，"
                        f"但顺序表记录为 {zone.kind.value}"
                    )
        object.__setattr__(
            self,
            "zone_order",
            MappingProxyType(normalized_order),
        )

        revision = _strict_int(self.revision, "状态版本号")
        if revision < 0:
            raise ModelValidationError("状态版本号不能小于0")
        object.__setattr__(self, "revision", revision)

        requested_deck_id = self.deck_id.strip() if isinstance(self.deck_id, str) else ""
        if self.deck_id and not requested_deck_id:
            raise ModelValidationError("牌堆ID必须是非空字符串")
        deck_ids = {card.deck_id for card in cards}
        if len(deck_ids) > 1:
            raise ModelValidationError("一个GameState不能静默混合多个deck_id")
        actual_deck_id = next(iter(deck_ids), requested_deck_id)
        if requested_deck_id and deck_ids and requested_deck_id != actual_deck_id:
            raise ModelValidationError(
                f"GameState牌堆ID {requested_deck_id!r} 与实体牌不一致"
            )
        object.__setattr__(self, "deck_id", actual_deck_id)

    @classmethod
    def from_deck_records(
        cls,
        records: Iterable[DeckRecord],
        *,
        players: Iterable[PlayerState],
        initial_zone: ZoneRef = DRAW_PILE,
    ) -> "GameState":
        """从正式 ``DeckRecord`` 实例行建立初始状态。"""

        if not isinstance(initial_zone, ZoneRef):
            raise TypeError("初始区域必须是ZoneRef")
        try:
            prepared_records = tuple(records)
        except TypeError as exc:
            raise TypeError("牌堆记录必须是DeckRecord可迭代对象") from exc
        cards = tuple(CardInstance.from_deck_record(record) for record in prepared_records)
        locations = {card.instance_id: initial_zone for card in cards}
        return cls(
            cards=cards,
            players=tuple(players),
            card_locations=locations,
            zone_order={initial_zone: tuple(card.instance_id for card in cards)},
        )

    @property
    def cards_by_id(self) -> Mapping[str, CardInstance]:
        return MappingProxyType({card.instance_id: card for card in self.cards})

    @property
    def players_by_id(self) -> Mapping[str, PlayerState]:
        return MappingProxyType({player.player_id: player for player in self.players})

    def location_of(self, instance_id: str) -> ZoneRef:
        requested = _nonempty_text(instance_id, "实体牌ID")
        try:
            return self.card_locations[requested]
        except KeyError as exc:
            raise ModelValidationError(f"找不到实体牌 {requested!r}") from exc

    def cards_in(self, zone: ZoneRef) -> tuple[CardInstance, ...]:
        if not isinstance(zone, ZoneRef):
            raise TypeError("查询区域必须是ZoneRef")
        cards_by_id = self.cards_by_id
        return tuple(
            cards_by_id[instance_id]
            for instance_id in self.card_ids_in(zone)
        )

    def card_ids_in(self, zone: ZoneRef) -> tuple[str, ...]:
        """按权威区域顺序返回实体牌ID；第一项是该区域队首。"""

        if not isinstance(zone, ZoneRef):
            raise TypeError("查询区域必须是ZoneRef")
        assert self.zone_order is not None
        return self.zone_order.get(zone, ())

    def move_card(self, instance_id: str, destination: ZoneRef) -> "GameState":
        """把一张已存在实体牌移动到目标区域并返回新状态。"""

        requested = _nonempty_text(instance_id, "实体牌ID")
        if requested not in self.card_locations:
            raise ModelValidationError(f"找不到实体牌 {requested!r}")
        return self.move_cards({requested: destination})

    def move_cards(self, moves: Mapping[str, ZoneRef]) -> "GameState":
        """原子移动多张牌，并按调用顺序追加到各目标区域尾端。

        所有移动牌会先从原区域顺序中移除，再按 ``moves`` 的迭代顺序追加。
        因此同一区域内移动也可用于把牌移至区域尾端，但洗牌应使用
        :meth:`reorder_zone` 显式表达。
        """

        if not isinstance(moves, Mapping):
            raise TypeError("批量移动必须是instance_id到ZoneRef的映射")
        if not moves:
            raise ModelValidationError("批量移动至少需要一张实体牌")
        updated = dict(self.card_locations)
        assert self.zone_order is not None
        updated_order = {
            zone: list(instance_ids)
            for zone, instance_ids in self.zone_order.items()
        }
        prepared_moves: list[tuple[str, ZoneRef]] = []
        for instance_id, destination in moves.items():
            requested = _nonempty_text(instance_id, "实体牌ID")
            if requested not in updated:
                raise ModelValidationError(f"找不到实体牌 {requested!r}")
            if not isinstance(destination, ZoneRef):
                raise TypeError("移动目标必须是ZoneRef")
            prepared_moves.append((requested, destination))

        moving_ids = {instance_id for instance_id, _ in prepared_moves}
        for zone, instance_ids in updated_order.items():
            updated_order[zone] = [
                instance_id
                for instance_id in instance_ids
                if instance_id not in moving_ids
            ]
        for requested, destination in prepared_moves:
            updated[requested] = destination
            updated_order.setdefault(destination, []).append(requested)
        return replace(
            self,
            card_locations=updated,
            zone_order={
                zone: tuple(instance_ids)
                for zone, instance_ids in updated_order.items()
            },
            revision=self.revision + 1,
        )

    def reorder_zone(
        self,
        zone: ZoneRef,
        ordered_instance_ids: Iterable[str],
    ) -> "GameState":
        """显式替换一个区域的完整顺序，用于确定性洗牌或回放。

        新序列必须与该区域当前实体牌集合完全相同，不得遗漏、增加或重复。
        此操作只改变顺序，不改变任何实体牌的位置归属。
        """

        if not isinstance(zone, ZoneRef):
            raise TypeError("重排区域必须是ZoneRef")
        if isinstance(ordered_instance_ids, (str, bytes)):
            raise TypeError("区域新顺序必须是实体牌ID序列")
        try:
            requested_order = tuple(ordered_instance_ids)
        except TypeError as exc:
            raise TypeError("区域新顺序必须是可迭代的实体牌ID序列") from exc
        if any(
            not isinstance(instance_id, str) or not instance_id.strip()
            for instance_id in requested_order
        ):
            raise ModelValidationError("区域新顺序中的实体牌ID必须是非空字符串")
        if len(requested_order) != len(set(requested_order)):
            raise ModelValidationError("区域新顺序不能包含重复实体牌ID")

        current_order = self.card_ids_in(zone)
        if set(requested_order) != set(current_order) or len(requested_order) != len(
            current_order
        ):
            missing = sorted(set(current_order) - set(requested_order))
            extra = sorted(set(requested_order) - set(current_order))
            details: list[str] = []
            if missing:
                details.append(f"缺少：{'、'.join(missing)}")
            if extra:
                details.append(f"不属于该区域：{'、'.join(extra)}")
            raise ModelValidationError("区域新顺序必须覆盖该区域全部实体牌；" + "；".join(details))

        assert self.zone_order is not None
        updated_order = dict(self.zone_order)
        updated_order[zone] = requested_order
        return replace(
            self,
            zone_order=updated_order,
            revision=self.revision + 1,
        )

    def assert_card_conservation(self) -> None:
        """显式复核实体牌目录和位置映射完全一致。"""

        card_ids = {card.instance_id for card in self.cards}
        if card_ids != set(self.card_locations):
            raise ModelValidationError("实体牌守恒校验失败")
        assert self.zone_order is not None
        ordered_ids = [
            instance_id
            for instance_ids in self.zone_order.values()
            for instance_id in instance_ids
        ]
        if len(ordered_ids) != len(set(ordered_ids)) or set(ordered_ids) != card_ids:
            raise ModelValidationError("实体牌区域顺序守恒校验失败")


__all__ = [
    "DISCARD_PILE",
    "DRAW_PILE",
    "EQUIPMENT_SLOTS",
    "GLOBAL_ZONE_KINDS",
    "PLAYER_ZONE_KINDS",
    "PROCESSING_ZONE",
    "REMOVED_FROM_GAME",
    "REVEALED_ZONE",
    "CardInstance",
    "CharacterGender",
    "CharacterMetadata",
    "GameState",
    "ModelValidationError",
    "PlayerState",
    "ZoneKind",
    "ZoneRef",
]
