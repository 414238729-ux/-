"""权威规则核心的最小可审计会话。

本模块把正式实体牌堆、不可变状态、单一确定性随机流、事件队列和回放
记录连接成一个最小会话。它只提供通用的实体牌原子移动，不
实现任何具体卡牌效果、武将技能、模式状态机、合法动作枚举或完整对局。
遇到未实现规则时必须失败关闭，绝不以概率或固定收益静默替代。
"""

from __future__ import annotations

from dataclasses import replace
import hashlib
from pathlib import Path
import platform
import random
from typing import Iterable

from ..deck_data import DeckAuditReport, DeckRecord, load_deck_csv
from .actions import UnsupportedRuleError
from .events import EventQueue, EventType, GameEvent
from .model import DRAW_PILE, GameState, PlayerState, ZoneRef
from .replay import NOT_LOADED_HASH, ReplayHeader, ReplayRecord, state_sha256
from .rng import DeterministicRNG


ENGINE_VERSION = "sgs-authoritative-core-scaffold-0.1.0"
DEFAULT_DECK_PATH = (
    Path(__file__).resolve().parents[2] / "knowledge" / "三国杀牌堆数据.csv"
)


class CoreSessionError(ValueError):
    """最小权威会话初始化或操作失败。"""


class DeckInitializationError(CoreSessionError):
    """正式实体牌堆无法通过权威会话门槛。"""


class EventValidationError(CoreSessionError):
    """事件引用了会话中不存在的实体。"""


def _zone_snapshot(zone: ZoneRef) -> dict[str, object]:
    return {
        "kind": zone.kind.value,
        "owner_id": zone.owner_id,
        "equipment_slot": zone.equipment_slot,
        "special_zone": zone.special_zone,
    }


def _zone_sort_key(zone: ZoneRef) -> tuple[str, str, str, str]:
    return (
        zone.kind.value,
        zone.owner_id or "",
        zone.equipment_slot or "",
        zone.special_zone or "",
    )


def canonical_state_snapshot(state: GameState) -> dict[str, object]:
    """把不可变 ``GameState`` 转换成稳定、可哈希的规范快照。"""

    if not isinstance(state, GameState):
        raise TypeError("状态快照来源必须是GameState")
    state.assert_card_conservation()
    cards_by_id = state.cards_by_id
    assert state.zone_order is not None
    return {
        "schema": "sgs-authoritative-core-state-v1",
        "deck_id": state.deck_id,
        "revision": state.revision,
        "players": [
            {
                "player_id": player.player_id,
                "seat": player.seat,
                "hp": player.hp,
                "max_hp": player.max_hp,
                "alive": player.alive,
            }
            for player in sorted(state.players, key=lambda item: item.seat)
        ],
        "cards": [
            {
                "instance_id": card.instance_id,
                "deck_id": card.deck_id,
                "card_key": card.card_key,
                "card_name": card.card_name,
                "card_type": card.card_type,
                "suit": card.suit,
                "color": card.color,
                "rank": card.rank,
                "card_variant": card.card_variant,
                "equipment_slot": card.equipment_slot,
                "distance_modifier": card.distance_modifier,
                "location": _zone_snapshot(state.location_of(card.instance_id)),
            }
            for card in sorted(cards_by_id.values(), key=lambda item: item.instance_id)
        ],
        "zones": [
            {
                "zone": _zone_snapshot(zone),
                "instance_ids": list(state.card_ids_in(zone)),
            }
            for zone in sorted(state.zone_order, key=_zone_sort_key)
        ],
    }


def _event_payload(event: GameEvent) -> dict[str, object]:
    return event.to_replay_dict()


class AuthoritativeCoreSession:
    """连接正式数据与核心基础设施的最小权威会话。

    会话构造时真实读取并审计正式 CSV，要求恰好160张、每行一张、实体
    ID唯一且只包含一个 ``deck_id``。整局只创建一个
    :class:`DeterministicRNG`，首次调用用于洗牌，后续调用方必须继续共享
    同一实例。

    本类刻意没有完整规则执行能力；:meth:`run_game` 永远失败关闭，直到
    卡牌、模式、武将和AI状态机由后续阶段真实接入。
    """

    def __init__(
        self,
        *,
        players: Iterable[PlayerState],
        seed: int,
        deck_path: str | Path = DEFAULT_DECK_PATH,
        mode: str = "core_session",
        ruleset_hash: str = "",
        general_data_hash: str = "",
        strategy_version: str = "",
    ) -> None:
        if not isinstance(mode, str) or not mode.strip():
            raise CoreSessionError("会话模式标识必须是非空字符串")
        if isinstance(seed, bool) or not isinstance(seed, int):
            raise TypeError("随机种子必须是整数")
        for value, label in (
            (ruleset_hash, "规则集哈希"),
            (general_data_hash, "武将数据哈希"),
            (strategy_version, "策略版本"),
        ):
            if not isinstance(value, str):
                raise TypeError(f"{label}必须是字符串")
        try:
            prepared_players = tuple(players)
        except TypeError as exc:
            raise TypeError("玩家列表必须是PlayerState可迭代对象") from exc
        if not prepared_players:
            raise CoreSessionError("权威核心会话至少需要一名玩家")
        if any(not isinstance(player, PlayerState) for player in prepared_players):
            raise TypeError("玩家列表中的每一项都必须是PlayerState")

        path = Path(deck_path).resolve()
        try:
            records, audit = load_deck_csv(path, expected_total=160)
        except (OSError, UnicodeError, ValueError) as exc:
            raise DeckInitializationError(f"正式牌堆加载失败：{exc}") from exc
        self._validate_formal_deck(records, audit)

        self.deck_path = path
        self.deck_records = records
        self.deck_audit = audit
        self._rng = DeterministicRNG(seed)

        state = GameState.from_deck_records(records, players=prepared_players)
        shuffled_ids = list(state.card_ids_in(DRAW_PILE))
        self._rng.shuffle(shuffled_ids)
        state = state.reorder_zone(DRAW_PILE, shuffled_ids)
        state.assert_card_conservation()
        self._state = state
        self._event_queue = EventQueue()

        try:
            deck_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError as exc:
            raise DeckInitializationError(f"无法读取正式牌堆原始字节以计算哈希：{path}") from exc
        initial_snapshot = canonical_state_snapshot(state)
        supplied_ruleset_hash = ruleset_hash.strip()
        supplied_general_hash = general_data_hash.strip()
        effective_ruleset_hash = supplied_ruleset_hash or NOT_LOADED_HASH
        effective_general_hash = supplied_general_hash or NOT_LOADED_HASH
        effective_strategy_version = strategy_version.strip() or NOT_LOADED_HASH
        self._replay = ReplayRecord(
            ReplayHeader(
                engine_version=ENGINE_VERSION,
                mode=mode.strip(),
                seed=seed,
                ruleset_hash=effective_ruleset_hash,
                deck_hash=deck_hash,
                general_data_hash=effective_general_hash,
                strategy_version=effective_strategy_version,
                metadata={
                    "scope": "基础设施会话；未实现完整规则对局",
                    "supports_full_game": False,
                    "unsupported_rule_policy": "raise",
                    "approximation_count": 0,
                    "ruleset_loaded": bool(supplied_ruleset_hash),
                    "general_data_loaded": bool(supplied_general_hash),
                    "deck_path": str(path),
                    "deck_id": state.deck_id,
                    "card_count": len(state.cards),
                    "initial_state_sha256": state_sha256(initial_snapshot),
                    "initial_state_snapshot": initial_snapshot,
                    "initial_rng_calls": self._rng.export_calls(),
                    "python_version": platform.python_version(),
                    "python_implementation": platform.python_implementation(),
                    "random_implementation": "python.random.Random",
                    "random_algorithm": "MT19937",
                    "random_state_version": random.Random.VERSION,
                },
            )
        )

    @staticmethod
    def _validate_formal_deck(
        records: tuple[DeckRecord, ...], audit: DeckAuditReport
    ) -> None:
        if not audit.is_valid:
            details = "；".join(issue.message for issue in audit.errors)
            raise DeckInitializationError(
                f"正式牌堆审计失败，不能建立权威会话：{details}"
            )
        if audit.total_quantity != 160 or len(records) != 160:
            raise DeckInitializationError(
                "正式牌堆必须恰好包含160张逐实体记录；"
                f"当前quantity合计为{audit.total_quantity}，记录数为{len(records)}"
            )
        if any(record.quantity != 1 for record in records):
            raise DeckInitializationError("正式牌堆必须一行一张且每行quantity=1")
        instance_ids = [record.instance_id for record in records]
        if any(not instance_id.strip() for instance_id in instance_ids):
            raise DeckInitializationError("正式牌堆的每张牌都必须具有非空instance_id")
        if len(instance_ids) != len(set(instance_ids)):
            raise DeckInitializationError("正式牌堆的instance_id必须全局唯一")
        deck_ids = {record.deck_id.strip() for record in records if record.deck_id.strip()}
        if len(deck_ids) != 1:
            raise DeckInitializationError("正式牌堆必须且只能包含一个非空deck_id")

    @property
    def state(self) -> GameState:
        return self._state

    @property
    def rng_calls(self) -> tuple[object, ...]:
        """返回只读随机调用快照，不暴露可继续消费的随机数生成器。"""

        return self._rng.calls

    @property
    def rng_call_count(self) -> int:
        return self._rng.call_count

    @property
    def event_queue_snapshot(self) -> tuple[GameEvent, ...]:
        """返回事件队列的不可变快照，不暴露 ``enqueue``/``dequeue``。"""

        return self._event_queue.snapshot()

    @property
    def replay(self) -> ReplayRecord:
        """返回独立回放副本；调用方追加事件不会污染会话权威记录。"""

        return ReplayRecord.from_dict(self._replay.to_dict())

    @property
    def replay_snapshot(self) -> dict[str, object]:
        """返回可独立修改的回放字典副本。"""

        return self._replay.to_dict()

    @property
    def state_snapshot(self) -> dict[str, object]:
        return canonical_state_snapshot(self._state)

    @property
    def state_hash(self) -> str:
        return state_sha256(self.state_snapshot)

    def _validate_event_references(self, event: GameEvent) -> None:
        if not isinstance(event, GameEvent):
            raise TypeError("只能登记GameEvent")
        player_ids = set(self._state.players_by_id)
        referenced_players: list[tuple[str, str]] = []
        for field_name in (
            "card_user",
            "damage_source",
            "skill_owner",
            "equipment_owner",
            "kill_credit",
        ):
            value = getattr(event, field_name)
            if value is not None:
                referenced_players.append((field_name, value))
        referenced_players.extend(("target_ids", value) for value in event.target_ids)
        for field_name, player_id in referenced_players:
            if player_id not in player_ids:
                raise EventValidationError(
                    f"事件字段{field_name}引用了不存在的玩家 {player_id!r}"
                )
        if (
            event.card_instance_id is not None
            and event.card_instance_id not in self._state.cards_by_id
        ):
            raise EventValidationError(
                f"事件引用了不存在的实体牌 {event.card_instance_id!r}"
            )
        unknown_materials = tuple(
            instance_id
            for instance_id in event.material_card_instance_ids
            if instance_id not in self._state.cards_by_id
        )
        if unknown_materials:
            raise EventValidationError(
                "事件引用了不存在的转化材料实体牌："
                + "、".join(repr(instance_id) for instance_id in unknown_materials)
            )

    def _commit_move(
        self,
        *,
        event: GameEvent,
        next_state: GameState,
        source: ZoneRef,
        destination: ZoneRef,
    ) -> GameEvent:
        """验证单张牌真实移动差量，再同步状态、事件与回放。"""

        self._validate_event_references(event)
        next_state.assert_card_conservation()
        if event.event_type is not EventType.CARD_MOVED:
            raise UnsupportedRuleError("最小会话只允许提交真实的card_moved原子事务")
        if event.card_instance_id is None:
            raise CoreSessionError("card_moved事务必须指定实体牌")
        if next_state.revision != self._state.revision + 1:
            raise CoreSessionError("原子移牌后的状态版本必须恰好增加1")
        if next_state.players != self._state.players or next_state.cards != self._state.cards:
            raise CoreSessionError("原子移牌事务不得同时修改玩家或实体牌目录")
        changed = tuple(
            card.instance_id
            for card in self._state.cards
            if self._state.location_of(card.instance_id)
            != next_state.location_of(card.instance_id)
        )
        if changed != (event.card_instance_id,):
            raise CoreSessionError("原子移牌事务必须且只能改变所声明的一张实体牌位置")
        if self._state.location_of(event.card_instance_id) != source:
            raise CoreSessionError("原子移牌事务声明的来源区域与当前状态不一致")
        if next_state.location_of(event.card_instance_id) != destination:
            raise CoreSessionError("原子移牌事务声明的目标区域与结果状态不一致")
        if dict(event.payload.get("source", {})) != _zone_snapshot(source):
            raise CoreSessionError("card_moved事件的来源区域负载与真实差量不一致")
        if dict(event.payload.get("destination", {})) != _zone_snapshot(destination):
            raise CoreSessionError("card_moved事件的目标区域负载与真实差量不一致")

        # 只通过公开序列化接口复制，兼容 ReplayRecord 对 entries 的只读封装。
        staged_replay = ReplayRecord.from_dict(self._replay.to_dict())
        staged_event = replace(event, sequence=self._event_queue.next_sequence)
        staged_replay.add_entry(
            staged_event.event_type.value,
            _event_payload(staged_event),
            canonical_state_snapshot(next_state),
        )
        staged_replay.verify_integrity()

        # 前置校验与回放构造已成功，EventQueue 此时只执行其确定性编号操作。
        queued = self._event_queue.enqueue(event)
        if queued.sequence != staged_event.sequence:  # 防御性检查，不静默容错。
            raise RuntimeError("事件队列序号与预构造回放序号不一致")
        self._state = next_state
        self._replay = staged_replay
        return queued

    def move_card(
        self,
        instance_id: str,
        destination: ZoneRef,
        *,
        card_user: str | None = None,
        reason: str = "generic_atomic_move",
    ) -> GameEvent:
        """原子移动一张实体牌并登记 ``card_moved`` 事件。

        这里只记录卡牌移动事实，不推断它属于使用、打出、弃置、获得或
        失去，也不会执行任何卡牌效果。
        """

        if not isinstance(destination, ZoneRef):
            raise TypeError("移动目标必须是ZoneRef")
        if not isinstance(reason, str) or not reason.strip():
            raise CoreSessionError("实体牌移动原因必须是非空字符串")
        source = self._state.location_of(instance_id)
        card = self._state.cards_by_id[instance_id]
        next_state = self._state.move_card(instance_id, destination)
        event = GameEvent(
            event_type=EventType.CARD_MOVED,
            card_instance_id=instance_id,
            card_key=card.card_key,
            card_user=card_user,
            payload={
                "source": _zone_snapshot(source),
                "destination": _zone_snapshot(destination),
                "reason": reason.strip(),
            },
        )
        return self._commit_move(
            event=event,
            next_state=next_state,
            source=source,
            destination=destination,
        )

    def run_game(self, *args: object, **kwargs: object) -> None:
        """失败关闭：基础设施会话尚不能执行完整对局。"""

        del args, kwargs
        raise UnsupportedRuleError(
            "完整对局规则尚未实现；权威核心拒绝使用概率、固定收益或其他近似替代继续运行"
        )


__all__ = [
    "DEFAULT_DECK_PATH",
    "ENGINE_VERSION",
    "AuthoritativeCoreSession",
    "CoreSessionError",
    "DeckInitializationError",
    "EventValidationError",
    "UnsupportedRuleError",
    "canonical_state_snapshot",
]
