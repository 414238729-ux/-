"""三国杀权威规则核心的事件、事件队列与响应窗口。

本模块只描述通用事件基础设施，不实现具体卡牌或武将规则。事件中的
``card_user``、``damage_source``、``skill_owner``、``equipment_owner`` 与
``kill_credit`` 始终保留为独立字段，调用方不得用其中一个字段猜测另一个。
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field, replace
from enum import Enum
import math
from types import MappingProxyType
from typing import Iterable, Mapping

from .model import EQUIPMENT_SLOTS


class EventType(str, Enum):
    """规则核心可观察的基础事件类型。"""

    CARD_USED = "card_used"
    CARD_PLAYED = "card_played"
    CARD_EFFECT_CANCELLED = "card_effect_cancelled"
    CARD_INVALIDATED = "card_invalidated"
    CARD_GAINED = "card_gained"
    CARD_LOST = "card_lost"
    CARD_DISCARDED = "card_discarded"
    CARD_MOVED = "card_moved"
    CARD_REVEALED = "card_revealed"
    DAMAGE = "damage"
    LOSE_HP = "lose_hp"
    HP_RECOVER = "hp_recover"
    DYING = "dying"
    DEATH = "death"
    VICTORY = "victory"
    GROUP_TARGET_RESOLVED = "group_target_resolved"
    CHAINED_STATE = "chained_state"
    CARD_RECAST = "card_recast"
    CHAIN_DAMAGE_STARTED = "chain_damage_started"
    CHAIN_TARGET_RESOLVED = "chain_target_resolved"
    CHAIN_DAMAGE_FINISHED = "chain_damage_finished"
    JUDGMENT_STARTED = "judgment_started"
    JUDGMENT_RESULT = "judgment_result"
    PHASE_SKIPPED = "phase_skipped"
    DELAYED_TRICK_TRANSFERRED = "delayed_trick_transferred"
    EQUIPMENT_EQUIPPED = "equipment_equipped"
    EQUIPMENT_REMOVED = "equipment_removed"
    EQUIPMENT_REPLACED = "equipment_replaced"
    ARMOR_JUDGMENT_STARTED = "armor_judgment_started"
    ARMOR_JUDGMENT_RESULT = "armor_judgment_result"
    ARMOR_RECOVERED = "armor_recovered"
    DAMAGE_PREVENTED = "damage_prevented"


def _validate_id(value: object, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name}必须是非空字符串")


def _validate_optional_id(value: str | None, field_name: str) -> None:
    if value is not None:
        _validate_id(value, field_name)


def _deep_freeze(value: object, path: str = "payload") -> object:
    """递归复制并冻结规范 JSON 数据，和回放入口使用同一基础边界。"""

    if value is None or isinstance(value, (str, bytes, int, bool)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{path}不能包含NaN或无穷大")
        return value
    if isinstance(value, Enum):
        return _deep_freeze(value.value, path)
    if isinstance(value, bytearray):
        return bytes(value)
    if isinstance(value, Mapping):
        frozen: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError(f"{path}的映射键必须是字符串")
            frozen[key] = _deep_freeze(item, f"{path}[{key!r}]")
        return MappingProxyType(frozen)
    if isinstance(value, (list, tuple)):
        return tuple(_deep_freeze(item, f"{path}[]") for item in value)
    raise TypeError(f"{path}包含不受支持且无法深冻结的类型：{type(value).__name__}")


@dataclass(frozen=True, slots=True, kw_only=True)
class GameEvent:
    """不可变的规则事件。

    ``sequence`` 只允许由 :class:`EventQueue` 分配。新建事件时应保持为
    ``None``。``payload`` 仅承载事件类型特有的补充数据，不能取代显式的
    归因字段。
    """

    event_type: EventType
    card_instance_id: str | None = None
    card_key: str | None = None
    material_card_instance_ids: tuple[str, ...] = ()
    card_user: str | None = None
    damage_source: str | None = None
    skill_owner: str | None = None
    equipment_owner: str | None = None
    kill_credit: str | None = None
    target_ids: tuple[str, ...] = ()
    payload: Mapping[str, object] = field(default_factory=dict)
    sequence: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.event_type, EventType):
            raise TypeError("event_type必须是EventType")
        for field_name in (
            "card_instance_id",
            "card_key",
            "card_user",
            "damage_source",
            "skill_owner",
            "equipment_owner",
            "kill_credit",
        ):
            _validate_optional_id(getattr(self, field_name), field_name)

        if isinstance(self.material_card_instance_ids, str):
            raise TypeError("material_card_instance_ids必须是实体牌ID序列")
        try:
            materials = tuple(self.material_card_instance_ids)
        except TypeError as exc:
            raise TypeError("material_card_instance_ids必须是实体牌ID序列") from exc
        for material_id in materials:
            _validate_id(material_id, "material_card_instance_ids中的实体牌ID")
        if len(materials) != len(set(materials)):
            raise ValueError("material_card_instance_ids不能包含重复实体牌ID")
        object.__setattr__(self, "material_card_instance_ids", materials)

        if isinstance(self.target_ids, str):
            raise TypeError("target_ids必须是角色标识序列，不能是字符串")
        try:
            normalized_targets = tuple(self.target_ids)
        except TypeError as exc:
            raise TypeError("target_ids必须是角色标识序列") from exc
        for target_id in normalized_targets:
            _validate_id(target_id, "target_ids中的角色标识")
        if len(set(normalized_targets)) != len(normalized_targets):
            raise ValueError("target_ids不能包含重复角色")
        object.__setattr__(self, "target_ids", normalized_targets)

        if not isinstance(self.payload, Mapping):
            raise TypeError("payload必须是映射")
        object.__setattr__(self, "payload", _deep_freeze(self.payload))

        if self.sequence is not None:
            if isinstance(self.sequence, bool) or not isinstance(self.sequence, int):
                raise TypeError("事件序号必须是正整数或空值")
            if self.sequence <= 0:
                raise ValueError("事件序号必须大于0")
        validate_event_contract(self)

    def to_replay_dict(self) -> dict[str, object]:
        """返回覆盖显式归因字段的回放负载；子类可追加自身规则字段。"""

        return {
            "sequence": self.sequence,
            "event_type": self.event_type.value,
            "card_instance_id": self.card_instance_id,
            "card_key": self.card_key,
            "material_card_instance_ids": list(self.material_card_instance_ids),
            "card_user": self.card_user,
            "damage_source": self.damage_source,
            "skill_owner": self.skill_owner,
            "equipment_owner": self.equipment_owner,
            "kill_credit": self.kill_credit,
            "target_ids": list(self.target_ids),
            "payload": dict(self.payload),
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class DamageEvent(GameEvent):
    """造成伤害事件；体力流失应使用 ``EventType.LOSE_HP``。"""

    event_type: EventType = field(default=EventType.DAMAGE, init=False)
    target_id: str
    amount: int
    damage_type: str = "无属性"

    def __post_init__(self) -> None:
        _validate_id(self.target_id, "伤害目标")
        if self.target_ids and tuple(self.target_ids) != (self.target_id,):
            raise ValueError("DamageEvent的target_ids必须只包含伤害目标")
        object.__setattr__(self, "target_ids", (self.target_id,))
        GameEvent.__post_init__(self)
        if isinstance(self.amount, bool) or not isinstance(self.amount, int):
            raise TypeError("伤害值必须是正整数")
        if self.amount <= 0:
            raise ValueError("伤害值必须大于0；被防止或减至0时不得生成伤害事件")
        if not isinstance(self.damage_type, str) or not self.damage_type.strip():
            raise ValueError("伤害属性必须是非空字符串")

    def to_replay_dict(self) -> dict[str, object]:
        payload = GameEvent.to_replay_dict(self)
        payload.update(
            {
                "target_id": self.target_id,
                "amount": self.amount,
                "damage_type": self.damage_type,
            }
        )
        return payload


_CHAIN_DAMAGE_TYPES: tuple[str, ...] = ("火属性", "雷属性")
_CHAIN_TARGET_RESULT_VALUES: frozenset[str] = frozenset(
    {"damaged", "skipped_dead", "skipped_unchained", "prevented_zero"}
)
_CHAIN_STOP_REASONS: frozenset[str] = frozenset(
    {"completed", "prevented_zero", "winner", "no_candidates"}
)
_CHAIN_STARTED_FIELDS: frozenset[str] = frozenset(
    {
        "root_damage_event_id",
        "source_id",
        "original_target_id",
        "damage_type",
        "root_card_instance_id",
        "chain_base_damage",
        "candidate_order",
    }
)
_CHAIN_TARGET_RESOLVED_FIELDS: frozenset[str] = frozenset(
    {
        "root_damage_event_id",
        "target_id",
        "target_index",
        "result",
        "chain_base_damage",
        "actual_damage",
        "chained_old",
        "chained_new",
    }
)
_CHAIN_FINISHED_FIELDS: frozenset[str] = frozenset(
    {
        "root_damage_event_id",
        "processed_targets",
        "skipped_targets",
        "stop_reason",
    }
)
_EQUIPMENT_EQUIPPED_REASONS: frozenset[str] = frozenset({"equip"})
_EQUIPMENT_REMOVED_REASONS: frozenset[str] = frozenset({"replaced"})


def _validate_nonempty_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label}必须是非空字符串")
    return value.strip()


def _validate_chain_event_id(value: object, label: str) -> None:
    """根伤害事件ID：非空字符串或仓库既有正整数事件ID。"""

    if isinstance(value, bool):
        raise ValueError(f"{label}必须是事件ID字符串或正整数")
    if isinstance(value, int):
        if value <= 0:
            raise ValueError(f"{label}必须是正整数事件ID")
        return
    _validate_nonempty_text(value, label)


def _validate_strict_int(
    value: object, label: str, *, minimum: int
) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{label}必须是整数")
    if value < minimum:
        raise ValueError(f"{label}必须大于等于{minimum}")
    return value


def _validate_boolean(value: object, label: str) -> None:
    if not isinstance(value, bool):
        raise ValueError(f"{label}必须是布尔值")


def _validate_string_sequence(
    value: object, label: str, *, unique: bool
) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)):
        raise ValueError(f"{label}必须是字符串序列，不能是单个字符串")
    try:
        items = tuple(value)  # type: ignore[arg-type]
    except TypeError as exc:
        raise ValueError(f"{label}必须是字符串序列") from exc
    for item in items:
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"{label}中的元素必须是非空字符串")
    if unique and len(items) != len(set(items)):
        raise ValueError(f"{label}不能包含重复元素")
    return items


def validate_event_contract(event: GameEvent) -> GameEvent:
    """检查跨模块必须一致的基础事件契约并返回原事件。"""

    if not isinstance(event, GameEvent):
        raise TypeError("事件契约只能检查GameEvent")
    if event.event_type is EventType.DAMAGE and not isinstance(event, DamageEvent):
        raise TypeError("damage事件必须使用DamageEvent，不能由普通GameEvent伪装")
    if event.event_type in (EventType.CARD_USED, EventType.CARD_PLAYED):
        if event.card_instance_id is None and event.card_key is None:
            raise ValueError("使用或打出牌事件必须提供实体牌ID或虚拟牌card_key")
        if event.card_user is None:
            raise ValueError("使用或打出牌事件必须提供card_user")
    if event.event_type in (
        EventType.CARD_GAINED,
        EventType.CARD_LOST,
        EventType.CARD_DISCARDED,
        EventType.CARD_MOVED,
    ) and event.card_instance_id is None:
        raise ValueError(f"{event.event_type.value}事件必须提供card_instance_id")
    if event.event_type in (EventType.CARD_GAINED, EventType.CARD_LOST) and len(event.target_ids) != 1:
        raise ValueError("获得或失去牌事件必须且只能指定一名相关角色")
    if event.event_type is EventType.CARD_DISCARDED and event.card_user is None:
        raise ValueError("弃置牌事件必须提供执行弃置的card_user")
    if event.event_type in (EventType.CARD_EFFECT_CANCELLED, EventType.CARD_INVALIDATED):
        if event.card_instance_id is None and event.card_key is None:
            raise ValueError("抵消或无效事件必须提供实体牌ID或card_key")
    if event.event_type is EventType.CARD_REVEALED:
        if event.card_instance_id is None or event.card_key is None:
            raise ValueError("展示牌事件必须提供实体牌ID与card_key")
        if not event.target_ids:
            raise ValueError("展示牌事件必须至少指定一名相关角色")
    if event.event_type in (
        EventType.EQUIPMENT_EQUIPPED,
        EventType.EQUIPMENT_REMOVED,
        EventType.EQUIPMENT_REPLACED,
    ):
        if event.card_instance_id is None:
            raise ValueError(f"{event.event_type.value}事件必须提供card_instance_id")
        if event.equipment_owner is None:
            raise ValueError(f"{event.event_type.value}事件必须提供equipment_owner")
        if (
            len(event.target_ids) != 1
            or event.target_ids[0] != event.equipment_owner
        ):
            raise ValueError(
                f"{event.event_type.value}事件必须且只能以装备拥有者为target"
            )
        slot = event.payload.get("slot")
        if not isinstance(slot, str) or slot not in EQUIPMENT_SLOTS:
            raise ValueError(
                f"{event.event_type.value}事件payload.slot必须是正式装备栏"
            )
    if event.event_type is EventType.EQUIPMENT_EQUIPPED:
        if set(event.payload) != {"slot", "reason"}:
            raise ValueError(
                "装备事件payload字段必须恰好为slot与reason"
            )
        reason = event.payload["reason"]
        if not isinstance(reason, str) or reason not in _EQUIPMENT_EQUIPPED_REASONS:
            raise ValueError(
                "装备事件reason只能是equip；"
                "不得使用任意自由文本或未知reason"
            )
    if event.event_type is EventType.EQUIPMENT_REMOVED:
        if set(event.payload) != {"slot", "reason"}:
            raise ValueError(
                "装备移除事件payload字段必须恰好为slot与reason"
            )
        reason = event.payload["reason"]
        if not isinstance(reason, str) or reason not in _EQUIPMENT_REMOVED_REASONS:
            raise ValueError(
                "装备移除事件reason只能是replaced；"
                "不得使用任意自由文本或未知reason"
            )
    if event.event_type is EventType.EQUIPMENT_REPLACED:
        if set(event.payload) != {
            "slot",
            "old_instance_id",
            "new_instance_id",
        }:
            raise ValueError(
                "装备替换事件payload字段必须恰好为slot、"
                "old_instance_id与new_instance_id"
            )
        # 生产实现中 equipment_replaced 没有 reason 字段，不为统一形式凭空增加。
    if event.event_type is EventType.JUDGMENT_STARTED:
        if event.card_instance_id is None or event.card_key is None:
            raise ValueError("判定开始事件必须提供延时锦囊实体牌ID与card_key")
        if len(event.target_ids) != 1:
            raise ValueError("判定开始事件必须且只能指定一名判定角色")
        payload = event.payload
        if set(payload) != {
            "delayed_trick_instance_id",
            "target_id",
            "judgment_zone_entry_index",
        }:
            raise ValueError(
                "判定开始事件payload字段必须恰好为delayed_trick_instance_id、"
                "target_id与judgment_zone_entry_index"
            )
        if payload["delayed_trick_instance_id"] != event.card_instance_id:
            raise ValueError("判定开始事件delayed_trick_instance_id必须等于实体牌ID")
        if payload["target_id"] != event.target_ids[0]:
            raise ValueError("判定开始事件target_id必须等于target_ids唯一角色")
        index = payload["judgment_zone_entry_index"]
        if isinstance(index, bool) or not isinstance(index, int) or index < 0:
            raise ValueError("判定开始事件judgment_zone_entry_index必须是非负整数")
    if event.event_type is EventType.JUDGMENT_RESULT:
        if event.card_instance_id is None or event.card_key is None:
            raise ValueError("判定结果事件必须提供判定牌实体牌ID与card_key")
        if len(event.target_ids) != 1:
            raise ValueError("判定结果事件必须且只能指定一名判定角色")
        payload = event.payload
        if set(payload) != {
            "delayed_trick_instance_id",
            "judgment_card_instance_id",
            "target_id",
            "suit",
            "rank",
            "hit",
            "skipped_phase",
            "damage_amount",
            "damage_type",
            "effect_applied",
        }:
            raise ValueError("判定结果事件payload字段集与正式契约不一致")
        if payload["judgment_card_instance_id"] != event.card_instance_id:
            raise ValueError("判定结果事件judgment_card_instance_id必须等于判定牌实体ID")
        if payload["target_id"] != event.target_ids[0]:
            raise ValueError("判定结果事件target_id必须等于target_ids唯一角色")
        if not isinstance(payload["suit"], str) or not payload["suit"]:
            raise ValueError("判定结果事件suit必须是非空字符串")
        if not isinstance(payload["rank"], str) or not payload["rank"]:
            raise ValueError("判定结果事件rank必须是非空字符串")
        if not isinstance(payload["hit"], bool):
            raise ValueError("判定结果事件hit必须是布尔值")
        skipped = payload["skipped_phase"]
        if skipped is not None and (
            not isinstance(skipped, str)
            or skipped not in ("draw", "play")
        ):
            raise ValueError("判定结果事件skipped_phase必须是draw、play或空")
        amount = payload["damage_amount"]
        if amount is not None and (
            isinstance(amount, bool)
            or not isinstance(amount, int)
            or amount < 0
        ):
            raise ValueError("判定结果事件damage_amount必须是非负整数或空")
        dmg_type = payload["damage_type"]
        if dmg_type is not None and (
            not isinstance(dmg_type, str)
            or not dmg_type.strip()
        ):
            raise ValueError("判定结果事件damage_type必须是非空字符串或空")
        if not isinstance(payload["effect_applied"], bool):
            raise ValueError("判定结果事件effect_applied必须是布尔值")
    if event.event_type is EventType.PHASE_SKIPPED:
        if event.card_instance_id is None:
            raise ValueError("阶段跳过事件必须提供延时锦囊实体牌ID")
        if len(event.target_ids) != 1:
            raise ValueError("阶段跳过事件必须且只能指定一名角色")
        payload = event.payload
        if set(payload) != {
            "player_id",
            "turn_number",
            "skipped_phase",
            "reason",
            "delayed_trick_instance_id",
        }:
            raise ValueError("阶段跳过事件payload字段集与正式契约不一致")
        if payload["player_id"] != event.target_ids[0]:
            raise ValueError("阶段跳过事件player_id必须等于target_ids唯一角色")
        if payload["delayed_trick_instance_id"] != event.card_instance_id:
            raise ValueError("阶段跳过事件delayed_trick_instance_id必须等于实体牌ID")
        turn = payload["turn_number"]
        if isinstance(turn, bool) or not isinstance(turn, int) or turn < 1:
            raise ValueError("阶段跳过事件turn_number必须是正整数")
        if payload["skipped_phase"] not in ("draw", "play"):
            raise ValueError("阶段跳过事件skipped_phase必须是draw或play")
        if not isinstance(payload["reason"], str) or not payload["reason"]:
            raise ValueError("阶段跳过事件reason必须是非空字符串")
    if event.event_type is EventType.DELAYED_TRICK_TRANSFERRED:
        if event.card_instance_id is None or event.card_key is None:
            raise ValueError("延时锦囊转移事件必须提供实体牌ID与card_key")
        if len(event.target_ids) != 1:
            raise ValueError("延时锦囊转移事件必须且只能指定一名接收角色")
        payload = event.payload
        if set(payload) != {
            "from_player_id",
            "to_player_id",
            "judgment_zone_entry_index",
            "reason",
        }:
            raise ValueError("延时锦囊转移事件payload字段集与正式契约不一致")
        if payload["to_player_id"] != event.target_ids[0]:
            raise ValueError("延时锦囊转移事件to_player_id必须等于target_ids唯一角色")
        index = payload["judgment_zone_entry_index"]
        if isinstance(index, bool) or not isinstance(index, int) or index < 0:
            raise ValueError("延时锦囊转移事件judgment_zone_entry_index必须是非负整数")
        if not isinstance(payload["reason"], str) or not payload["reason"]:
            raise ValueError("延时锦囊转移事件reason必须是非空字符串")
    if event.event_type is EventType.LOSE_HP:
        if len(event.target_ids) != 1:
            raise ValueError("失去体力事件必须且只能指定一名目标角色")
        amount = event.payload.get("amount")
        if isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0:
            raise ValueError("失去体力事件payload.amount必须是正整数")
    if event.event_type is EventType.HP_RECOVER:
        if len(event.target_ids) != 1:
            raise ValueError("恢复体力事件必须且只能指定一名目标角色")
        amount = event.payload.get("amount")
        if isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0:
            raise ValueError("恢复体力事件payload.amount必须是正整数")
    if event.event_type is EventType.GROUP_TARGET_RESOLVED:
        if event.card_instance_id is None:
            raise ValueError("群体锦囊逐目标结算事件必须提供根锦囊实体牌ID")
        if len(event.target_ids) != 1:
            raise ValueError("群体锦囊逐目标结算事件必须且只能指定当前目标角色")
    if event.event_type is EventType.CHAINED_STATE:
        if event.card_instance_id is None or event.card_key is None:
            raise ValueError("横置状态变化事件必须提供实体牌ID与card_key")
        if len(event.target_ids) != 1:
            raise ValueError("横置状态变化事件必须且只能指定一名目标角色")
    if event.event_type is EventType.CHAIN_DAMAGE_STARTED:
        if event.card_instance_id is None or event.card_key is None:
            raise ValueError("传导开始事件必须提供根实体牌ID与card_key")
        if len(event.target_ids) != 1:
            raise ValueError("传导开始事件必须且只能指定原始受伤角色")
        payload = event.payload
        if set(payload) != _CHAIN_STARTED_FIELDS:
            raise ValueError(
                "传导开始事件payload字段必须恰好为root_damage_event_id、"
                "source_id、original_target_id、damage_type、"
                "root_card_instance_id、chain_base_damage、candidate_order"
            )
        _validate_chain_event_id(
            payload["root_damage_event_id"], "传导开始事件root_damage_event_id"
        )
        source_id = payload["source_id"]
        if source_id is not None:
            _validate_nonempty_text(source_id, "传导开始事件source_id")
        original = _validate_nonempty_text(
            payload["original_target_id"], "传导开始事件original_target_id"
        )
        if original != event.target_ids[0]:
            raise ValueError(
                "传导开始事件original_target_id必须与target_ids一致"
            )
        if payload["damage_type"] not in _CHAIN_DAMAGE_TYPES:
            raise ValueError("传导开始事件damage_type只能是火属性或雷属性")
        root_card = payload["root_card_instance_id"]
        if root_card is not None:
            _validate_nonempty_text(
                root_card, "传导开始事件root_card_instance_id"
            )
        base = payload["chain_base_damage"]
        if isinstance(base, bool) or not isinstance(base, int) or base <= 0:
            raise ValueError("传导开始事件chain_base_damage必须是正整数")
        _validate_string_sequence(
            payload["candidate_order"],
            "传导开始事件candidate_order",
            unique=True,
        )
    if event.event_type is EventType.CHAIN_TARGET_RESOLVED:
        if event.card_instance_id is None or event.card_key is None:
            raise ValueError("传导目标结算事件必须提供根实体牌ID与card_key")
        if len(event.target_ids) != 1:
            raise ValueError("传导目标结算事件必须且只能指定当前目标角色")
        payload = event.payload
        if set(payload) != _CHAIN_TARGET_RESOLVED_FIELDS:
            raise ValueError(
                "传导目标结算事件payload字段必须恰好为root_damage_event_id、"
                "target_id、target_index、result、chain_base_damage、"
                "actual_damage、chained_old、chained_new"
            )
        _validate_chain_event_id(
            payload["root_damage_event_id"],
            "传导目标结算事件root_damage_event_id",
        )
        target_id = _validate_nonempty_text(
            payload["target_id"], "传导目标结算事件target_id"
        )
        if target_id != event.target_ids[0]:
            raise ValueError("传导目标结算事件target_id必须与target_ids一致")
        _validate_strict_int(
            payload["target_index"],
            "传导目标结算事件target_index",
            minimum=0,
        )
        result = payload["result"]
        if result not in _CHAIN_TARGET_RESULT_VALUES:
            raise ValueError(
                "传导目标结算事件result只能是damaged、skipped_dead、"
                "skipped_unchained或prevented_zero；"
                "stopped_winner不是生产实现值"
            )
        base = payload["chain_base_damage"]
        if isinstance(base, bool) or not isinstance(base, int) or base <= 0:
            raise ValueError(
                "传导目标结算事件chain_base_damage必须是正整数"
            )
        actual = _validate_strict_int(
            payload["actual_damage"],
            "传导目标结算事件actual_damage",
            minimum=0,
        )
        chained_old = payload["chained_old"]
        chained_new = payload["chained_new"]
        _validate_boolean(chained_old, "传导目标结算事件chained_old")
        _validate_boolean(chained_new, "传导目标结算事件chained_new")
        if result == "damaged":
            if actual <= 0 or chained_old is not True or chained_new is not False:
                raise ValueError(
                    "damaged结果必须满足actual_damage>0、"
                    "chained_old=True且chained_new=False"
                )
        elif result == "prevented_zero":
            if actual != 0 or chained_old is not True or chained_new is not True:
                raise ValueError(
                    "prevented_zero结果必须满足actual_damage=0、"
                    "chained_old=True且chained_new=True"
                )
        else:
            if actual != 0 or chained_old != chained_new:
                raise ValueError(
                    "跳过结果必须满足actual_damage=0且chained_old==chained_new"
                )
    if event.event_type is EventType.CHAIN_DAMAGE_FINISHED:
        if event.card_instance_id is None or event.card_key is None:
            raise ValueError("传导结束事件必须提供根实体牌ID与card_key")
        payload = event.payload
        if set(payload) != _CHAIN_FINISHED_FIELDS:
            raise ValueError(
                "传导结束事件payload字段必须恰好为root_damage_event_id、"
                "processed_targets、skipped_targets、stop_reason"
            )
        _validate_chain_event_id(
            payload["root_damage_event_id"],
            "传导结束事件root_damage_event_id",
        )
        processed = _validate_string_sequence(
            payload["processed_targets"],
            "传导结束事件processed_targets",
            unique=True,
        )
        skipped = _validate_string_sequence(
            payload["skipped_targets"],
            "传导结束事件skipped_targets",
            unique=True,
        )
        if set(processed) & set(skipped):
            raise ValueError(
                "传导结束事件processed_targets与skipped_targets"
                "不能包含同一角色"
            )
        if payload["stop_reason"] not in _CHAIN_STOP_REASONS:
            raise ValueError(
                "传导结束事件stop_reason只能是completed、prevented_zero、"
                "winner或no_candidates"
            )
    if event.event_type is EventType.ARMOR_JUDGMENT_STARTED:
        if event.card_instance_id is None or event.card_key is None:
            raise ValueError("防具判定开始事件必须提供防具实体牌ID与card_key")
        if len(event.target_ids) != 1:
            raise ValueError("防具判定开始事件必须且只能指定一名判定角色")
        payload = event.payload
        if set(payload) != {
            "armor_instance_id",
            "armor_key",
            "target_id",
            "response_to_card_key",
            "response_window_id",
        }:
            raise ValueError(
                "防具判定开始事件payload字段必须恰好为armor_instance_id、"
                "armor_key、target_id、response_to_card_key与response_window_id"
            )
        if payload["armor_instance_id"] != event.card_instance_id:
            raise ValueError("防具判定开始事件armor_instance_id必须等于实体牌ID")
        if payload["armor_key"] != event.card_key:
            raise ValueError("防具判定开始事件armor_key必须等于card_key")
        if payload["target_id"] != event.target_ids[0]:
            raise ValueError("防具判定开始事件target_id必须等于target_ids唯一角色")
        _validate_nonempty_text(
            payload["response_to_card_key"], "防具判定开始事件response_to_card_key"
        )
        _validate_nonempty_text(
            payload["response_window_id"], "防具判定开始事件response_window_id"
        )
    if event.event_type is EventType.ARMOR_JUDGMENT_RESULT:
        if event.card_instance_id is None or event.card_key is None:
            raise ValueError("防具判定结果事件必须提供判定牌实体牌ID与card_key")
        if len(event.target_ids) != 1:
            raise ValueError("防具判定结果事件必须且只能指定一名判定角色")
        payload = event.payload
        if set(payload) != {
            "armor_instance_id",
            "judgment_card_instance_id",
            "judgment_suit",
            "judgment_color",
            "success",
            "virtual_response_kind",
        }:
            raise ValueError(
                "防具判定结果事件payload字段必须恰好为armor_instance_id、"
                "judgment_card_instance_id、judgment_suit、judgment_color、"
                "success与virtual_response_kind"
            )
        if payload["judgment_card_instance_id"] != event.card_instance_id:
            raise ValueError(
                "防具判定结果事件judgment_card_instance_id必须等于判定牌实体ID"
            )
        if payload["armor_instance_id"] == event.card_instance_id:
            raise ValueError("防具判定结果事件的判定牌不得与防具本体相同")
        _validate_nonempty_text(
            payload["armor_instance_id"], "防具判定结果事件armor_instance_id"
        )
        _validate_nonempty_text(
            payload["judgment_suit"], "防具判定结果事件judgment_suit"
        )
        if payload["judgment_color"] not in ("红", "黑"):
            raise ValueError("防具判定结果事件judgment_color只能是红或黑")
        success = payload["success"]
        if not isinstance(success, bool):
            raise ValueError("防具判定结果事件success必须是布尔值")
        kind = payload["virtual_response_kind"]
        if success:
            if kind not in ("use_dodge", "play_jink"):
                raise ValueError(
                    "防具判定成功时virtual_response_kind必须是use_dodge或play_jink"
                )
        elif kind is not None:
            raise ValueError("防具判定失败时virtual_response_kind必须为空")
    if event.event_type is EventType.ARMOR_RECOVERED:
        if event.card_instance_id is None or event.card_key is None:
            raise ValueError("防具恢复事件必须提供防具实体牌ID与card_key")
        if len(event.target_ids) != 1:
            raise ValueError("防具恢复事件必须且只能指定一名恢复角色")
        payload = event.payload
        if set(payload) != {
            "armor_instance_id",
            "armor_key",
            "owner_id",
            "hp_before",
            "hp_after",
            "reason",
        }:
            raise ValueError(
                "防具恢复事件payload字段必须恰好为armor_instance_id、"
                "armor_key、owner_id、hp_before、hp_after与reason"
            )
        if payload["armor_instance_id"] != event.card_instance_id:
            raise ValueError("防具恢复事件armor_instance_id必须等于实体牌ID")
        if payload["armor_key"] != event.card_key:
            raise ValueError("防具恢复事件armor_key必须等于card_key")
        if payload["owner_id"] != event.target_ids[0]:
            raise ValueError("防具恢复事件owner_id必须等于target_ids唯一角色")
        for field_name in ("hp_before", "hp_after"):
            value = payload[field_name]
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(
                    f"防具恢复事件{field_name}必须是非负整数"
                )
        if not isinstance(payload["reason"], str) or not payload["reason"]:
            raise ValueError("防具恢复事件reason必须是非空字符串")
    if event.event_type is EventType.DAMAGE_PREVENTED:
        if event.card_instance_id is None or event.card_key is None:
            raise ValueError("伤害防止事件必须提供根实体牌ID与card_key")
        if len(event.target_ids) != 1:
            raise ValueError("伤害防止事件必须且只能指定一名受害角色")
        payload = event.payload
        if set(payload) != {
            "victim_id",
            "card_key",
            "declared_amount",
            "final_amount",
            "modifiers",
            "armor_ignored",
        }:
            raise ValueError(
                "伤害防止事件payload字段必须恰好为victim_id、card_key、"
                "declared_amount、final_amount、modifiers与armor_ignored"
            )
        if payload["victim_id"] != event.target_ids[0]:
            raise ValueError("伤害防止事件victim_id必须等于target_ids唯一角色")
        if payload["card_key"] != event.card_key:
            raise ValueError("伤害防止事件payload.card_key必须等于card_key")
        declared = payload["declared_amount"]
        if isinstance(declared, bool) or not isinstance(declared, int) or declared <= 0:
            raise ValueError("伤害防止事件declared_amount必须是正整数")
        final = payload["final_amount"]
        if final != 0:
            raise ValueError("伤害防止事件final_amount必须为0")
        modifiers = _validate_string_sequence(
            payload["modifiers"], "伤害防止事件modifiers", unique=True
        )
        if not modifiers:
            raise ValueError("伤害防止事件modifiers不能为空")
        _validate_boolean(payload["armor_ignored"], "伤害防止事件armor_ignored")
    if event.event_type is EventType.CARD_RECAST:
        if event.card_instance_id is None or event.card_key is None:
            raise ValueError("重铸事件必须提供实体牌ID与card_key")
        if event.card_user is None:
            raise ValueError("重铸事件必须提供执行重铸的card_user")
        if event.target_ids:
            raise ValueError("重铸事件不能指定目标")
    if event.event_type in (EventType.DYING, EventType.DEATH) and len(event.target_ids) != 1:
        raise ValueError("濒死或死亡事件必须且只能指定一名目标角色")
    if event.event_type is EventType.VICTORY and not event.target_ids:
        raise ValueError("胜利事件必须至少指定一名获胜角色")
    return event


class EventQueue:
    """为事件分配单调序号并以稳定先进先出顺序处理。"""

    def __init__(self, events: Iterable[GameEvent] = ()) -> None:
        self._events: deque[GameEvent] = deque()
        self._next_sequence = 1
        self.extend(events)

    def __len__(self) -> int:
        return len(self._events)

    def __bool__(self) -> bool:
        return bool(self._events)

    @property
    def next_sequence(self) -> int:
        return self._next_sequence

    def enqueue(self, event: GameEvent) -> GameEvent:
        """加入一个未编号事件，返回队列中带编号的不可变事件。"""

        self._validate_new_event(event)
        queued_event = replace(event, sequence=self._next_sequence)
        self._next_sequence += 1
        self._events.append(queued_event)
        return queued_event

    def extend(self, events: Iterable[GameEvent]) -> tuple[GameEvent, ...]:
        if isinstance(events, (str, bytes)):
            raise TypeError("events必须是GameEvent序列")
        try:
            pending = tuple(events)
        except TypeError as exc:
            raise TypeError("events必须是GameEvent序列") from exc
        for event in pending:
            self._validate_new_event(event)
        return tuple(self.enqueue(event) for event in pending)

    def peek(self) -> GameEvent:
        if not self._events:
            raise IndexError("事件队列为空，无法查看下一事件")
        return self._events[0]

    def dequeue(self) -> GameEvent:
        if not self._events:
            raise IndexError("事件队列为空，无法取出事件")
        return self._events.popleft()

    def snapshot(self) -> tuple[GameEvent, ...]:
        """返回当前队列顺序的只读快照。"""

        return tuple(self._events)

    @staticmethod
    def _validate_new_event(event: GameEvent) -> None:
        if not isinstance(event, GameEvent):
            raise TypeError("事件队列只能接收GameEvent")
        validate_event_contract(event)
        if event.sequence is not None:
            raise ValueError("事件序号只能由EventQueue分配，不能重复入队已编号事件")


class ResponseDecision(str, Enum):
    """响应窗口中每个座次的处理状态。"""

    WAITING = "waiting"
    RESPONDED = "responded"
    PASSED = "passed"
    SKIPPED = "skipped"


@dataclass(frozen=True, slots=True)
class ResponseRecord:
    player_id: str
    seat_index: int
    decision: ResponseDecision
    response_event: GameEvent | None = None


@dataclass(frozen=True, slots=True)
class ResponseWindowSnapshot:
    """不会暴露窗口内部可变容器的响应状态快照。"""

    window_id: str
    source_event: GameEvent | None
    responder_order: tuple[str, ...]
    allowed_event_types: frozenset[EventType]
    current_responder: str | None
    is_closed: bool
    decisions: Mapping[str, ResponseDecision]
    responses: Mapping[str, GameEvent]
    history: tuple[ResponseRecord, ...]


class ResponseWindow:
    """按调用方给定的当前座次顺序逐名处理响应。

    本类不会自行推导座次；位置交换、死亡跳过等规则应先在状态层生成正确
    的 ``responder_order``。默认会询问全部角色；若具体规则在首个合法响应
    后关闭窗口，可设置 ``close_on_first_response=True``。
    """

    def __init__(
        self,
        responder_order: Iterable[str],
        *,
        window_id: str,
        source_event: GameEvent | None = None,
        close_on_first_response: bool = False,
        allowed_event_types: Iterable[EventType] | None = None,
    ) -> None:
        if not isinstance(window_id, str) or not window_id.strip():
            raise ValueError("响应窗口标识必须是非空字符串")
        if isinstance(responder_order, str):
            raise TypeError("响应顺序必须是角色标识序列，不能是字符串")
        try:
            order = tuple(responder_order)
        except TypeError as exc:
            raise TypeError("响应顺序必须是角色标识序列") from exc
        for player_id in order:
            _validate_id(player_id, "响应角色标识")
        if len(set(order)) != len(order):
            raise ValueError("同一响应窗口的响应顺序不能包含重复角色")
        if source_event is not None and not isinstance(source_event, GameEvent):
            raise TypeError("source_event必须是GameEvent或空值")
        if not isinstance(close_on_first_response, bool):
            raise TypeError("close_on_first_response必须是布尔值")
        if allowed_event_types is None:
            allowed_types = frozenset((EventType.CARD_USED, EventType.CARD_PLAYED))
        else:
            if isinstance(allowed_event_types, (str, bytes)):
                raise TypeError("allowed_event_types必须是EventType序列")
            try:
                allowed_types = frozenset(allowed_event_types)
            except TypeError as exc:
                raise TypeError("allowed_event_types必须是EventType序列") from exc
            if not allowed_types:
                raise ValueError("响应窗口必须允许至少一种事件类型")
            if any(not isinstance(event_type, EventType) for event_type in allowed_types):
                raise TypeError("allowed_event_types中的值必须是EventType")

        self.window_id = window_id
        self.source_event = source_event
        self.responder_order = order
        self.close_on_first_response = close_on_first_response
        self.allowed_event_types = allowed_types
        self._cursor = 0
        self._decisions: dict[str, ResponseDecision] = {
            player_id: ResponseDecision.WAITING for player_id in order
        }
        self._responses: dict[str, GameEvent] = {}
        self._history: list[ResponseRecord] = []

    @property
    def is_closed(self) -> bool:
        return self._cursor >= len(self.responder_order)

    @property
    def current_responder(self) -> str | None:
        if self.is_closed:
            return None
        return self.responder_order[self._cursor]

    @property
    def history(self) -> tuple[ResponseRecord, ...]:
        return tuple(self._history)

    @property
    def waiting_responders(self) -> tuple[str, ...]:
        return tuple(
            player_id
            for player_id in self.responder_order
            if self._decisions[player_id] is ResponseDecision.WAITING
        )

    def snapshot(self) -> ResponseWindowSnapshot:
        """返回递归只读的当前响应状态。"""

        return ResponseWindowSnapshot(
            window_id=self.window_id,
            source_event=self.source_event,
            responder_order=self.responder_order,
            allowed_event_types=self.allowed_event_types,
            current_responder=self.current_responder,
            is_closed=self.is_closed,
            decisions=MappingProxyType(dict(self._decisions)),
            responses=MappingProxyType(dict(self._responses)),
            history=tuple(self._history),
        )

    def decision_for(self, player_id: str) -> ResponseDecision:
        if player_id not in self._decisions:
            raise KeyError(f"角色{player_id!r}不在此响应窗口中")
        return self._decisions[player_id]

    def response_for(self, player_id: str) -> GameEvent | None:
        if player_id not in self._decisions:
            raise KeyError(f"角色{player_id!r}不在此响应窗口中")
        return self._responses.get(player_id)

    def pass_response(self, player_id: str) -> ResponseRecord:
        return self._record(player_id, ResponseDecision.PASSED, None)

    def respond(self, player_id: str, response_event: GameEvent) -> ResponseRecord:
        if not isinstance(response_event, GameEvent):
            raise TypeError("合法响应必须记录为GameEvent")
        validate_event_contract(response_event)
        if response_event.sequence is not None:
            raise ValueError("响应窗口只能接收尚未入队编号的新事件")
        if response_event.event_type not in self.allowed_event_types:
            allowed = "、".join(sorted(event_type.value for event_type in self.allowed_event_types))
            raise ValueError(f"此响应窗口只接受以下事件类型：{allowed}")
        if response_event.card_user != player_id:
            raise ValueError("响应事件的card_user必须与当前响应角色一致，禁止冒用他人身份")
        existing_window = response_event.payload.get("response_window_id")
        if existing_window not in (None, self.window_id):
            raise ValueError("响应事件已绑定其他响应窗口")
        causal_payload = dict(response_event.payload)
        causal_payload["response_window_id"] = self.window_id
        if self.source_event is not None:
            causal_payload["source_event_type"] = self.source_event.event_type.value
            causal_payload["source_event_sequence"] = self.source_event.sequence
        bound_event = replace(response_event, payload=causal_payload)
        return self._record(
            player_id,
            ResponseDecision.RESPONDED,
            bound_event,
        )

    def _record(
        self,
        player_id: str,
        decision: ResponseDecision,
        response_event: GameEvent | None,
    ) -> ResponseRecord:
        if self.is_closed:
            raise RuntimeError("响应窗口已经关闭")
        expected = self.current_responder
        if player_id != expected:
            raise ValueError(f"当前应由{expected!r}处理响应，不能由{player_id!r}抢先处理")

        record = ResponseRecord(
            player_id=player_id,
            seat_index=self._cursor,
            decision=decision,
            response_event=response_event,
        )
        self._decisions[player_id] = decision
        if response_event is not None:
            self._responses[player_id] = response_event
        self._history.append(record)
        self._cursor += 1

        if decision is ResponseDecision.RESPONDED and self.close_on_first_response:
            for skipped_player in self.responder_order[self._cursor :]:
                self._decisions[skipped_player] = ResponseDecision.SKIPPED
            self._cursor = len(self.responder_order)
        return record


__all__ = [
    "DamageEvent",
    "EventQueue",
    "EventType",
    "GameEvent",
    "ResponseDecision",
    "ResponseRecord",
    "ResponseWindow",
    "ResponseWindowSnapshot",
    "validate_event_contract",
]
