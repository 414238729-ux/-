# -*- coding: utf-8 -*-
"""正式160张牌堆上六种基本牌生产批次的严格规则重执行回放。

保存的状态、事件与随机结果只作为重执行的期望值。本模块重放时会重新
构造 :class:`ProductionBasicCardBatch`，重新枚举合法动作，并把记录的
``action_id`` 通过真实 ``step`` 路径提交；绝不会用保存的状态快照
推进游戏。本回放是生产基本牌批次的验收资产，不是完整整局回放。
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from .actions import ActionContext, LegalAction
from .engine import ENGINE_VERSION, canonical_state_snapshot
from .production_batch import (
    FORMAL_NO_SKILL_DUEL_MODE,
    PRODUCTION_BASIC_CARDS_MODE,
    BatchActionIdController,
    BatchReferenceController,
    ProductionBasicCardBatch,
    ProductionBatchSafetyLimitError,
)
from .replay import canonical_json, sha256_value, state_sha256


REEXECUTION_SCHEMA = "sgs-production-basic-batch-reexecution-v1"
_EVENT_CHAIN_ANCHOR = sha256_value(
    {"schema": REEXECUTION_SCHEMA, "stream": "event_hash_chain"}
)


class ProductionReplayFormatError(ValueError):
    """回放文件的结构或总记录哈希无效。"""


class ProductionReplayDivergenceError(AssertionError):
    """规则重执行首次偏离已记录期望时抛出。"""

    def __init__(
        self,
        kind: str,
        index: int | None,
        message: str,
        *,
        expected: object = None,
        actual: object = None,
    ) -> None:
        location = "初始化/终局" if index is None else f"索引{index}"
        super().__init__(f"规则重执行在{kind}的{location}发生偏差：{message}")
        self.kind = kind
        self.index = index
        self.expected = expected
        self.actual = actual


def _plain(value: object) -> Any:
    """返回与规范表示相同的独立JSON值。"""

    return json.loads(canonical_json(value))


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, tuple):
        return tuple(_freeze(item) for item in value)
    return value


def _require_mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ProductionReplayFormatError(f"{label}必须是JSON对象")
    return value


def _require_sequence(value: object, label: str) -> Sequence[object]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ProductionReplayFormatError(f"{label}必须是JSON数组")
    return value


def _require_exact_fields(
    value: Mapping[str, object], required: set[str], label: str
) -> None:
    missing = sorted(required.difference(value))
    extra = sorted(set(value).difference(required))
    if missing:
        raise ProductionReplayFormatError(f"{label}缺少字段：{', '.join(missing)}")
    if extra:
        raise ProductionReplayFormatError(f"{label}包含未知字段：{', '.join(extra)}")


def _context_value(context: ActionContext) -> dict[str, object]:
    return _plain(
        {
            "mode": context.mode,
            "phase": context.phase,
            "actor_id": context.actor_id,
            "turn_player_id": context.turn_player_id,
            "response_window_id": context.response_window_id,
            "expected_revision": context.expected_revision,
            "metadata": context.metadata,
        }
    )


def _action_value(action: LegalAction) -> dict[str, object]:
    return _plain(
        {
            "action_id": action.action_id,
            "action_type": action.action_type.value,
            "actor_id": action.actor_id,
            "card_instance_id": action.card_instance_id,
            "virtual_card": (
                None
                if action.virtual_card is None
                else action.virtual_card.to_dict()
            ),
            "target_ids": action.target_ids,
            "skill_id": action.skill_id,
            "payload": action.payload,
        }
    )


def _event_values(game: ProductionBasicCardBatch) -> list[dict[str, object]]:
    return [_plain(event.to_replay_dict()) for event in game.events]


def _rng_values(game: ProductionBasicCardBatch) -> list[dict[str, object]]:
    return [_plain(call.to_dict()) for call in game.rng_calls]


def _build_event_hash_chain(events: Sequence[object]) -> tuple[str, ...]:
    """在完整规范事件流上构建前向SHA-256链。"""

    previous = _EVENT_CHAIN_ANCHOR
    chain: list[str] = []
    for index, event in enumerate(events):
        previous = sha256_value(
            {"index": index, "previous_event_sha256": previous, "event": event}
        )
        chain.append(previous)
    return tuple(chain)


def _execution_hash(game: ProductionBasicCardBatch) -> str:
    return sha256_value(game.execution_snapshot)


def _game_state_hash(game: ProductionBasicCardBatch) -> str:
    return state_sha256(canonical_state_snapshot(game.state))


def _deck_definition(records: Sequence[Any]) -> dict[str, object]:
    return {
        "deck_id": records[0].deck_id if records else "",
        "cards": [
            {
                "position": index,
                "instance_id": record.instance_id,
                "deck_id": record.deck_id,
                "card_key": record.card_key,
                "card_name": record.card_name,
                "card_type": record.card_type,
                "suit": record.suit,
                "color": record.color,
                "rank": record.rank,
                "card_variant": record.card_variant,
                "equipment_slot": record.equip_slot or None,
                "distance_modifier": (
                    int(record.distance_modifier)
                    if record.distance_modifier.strip()
                    else None
                ),
            }
            for index, record in enumerate(records)
        ],
    }


def _ruleset_value(game: ProductionBasicCardBatch) -> dict[str, str]:
    binding = game.registry.binding_value(game.mode_id, game.phase.value)
    value = {
        "mode_id": game.mode_id,
        "adapter_type": str(binding["adapter_type"]),
        "ruleset_version": str(binding["adapter_version"]),
        "registry_fingerprint": str(binding["registry_fingerprint"]),
    }
    value["ruleset_hash"] = sha256_value(value)
    return value

_HEADER_FIELDS = {
    "schema_version",
    "engine_version",
    "mode_id",
    "test_only",
    "formal_result",
    "production_basic_cards_batch",
    "ruleset_version",
    "ruleset_hash",
    "registry_fingerprint",
    "initial_configuration",
    "deck_definition",
    "deck_hash",
    "seed",
    "initial_rng_state",
    "initial_rng_state_sha256",
    "initial_rng_call_count",
    "initial_event_count",
    "initial_execution_hash",
    "initial_game_state_hash",
    "fixture_applied",
}
_DECISION_FIELDS = {
    "index",
    "context",
    "context_sha256",
    "legal_actions",
    "legal_action_set_sha256",
    "chosen_action_id",
    "chosen_action",
    "state_before_sha256",
    "state_after_sha256",
    "execution_before_sha256",
    "execution_after_sha256",
    "rng_start",
    "rng_end",
    "event_start",
    "event_end",
}
_OUTCOME_FIELDS = {
    "winner_id",
    "finish_reason",
    "step_count",
    "turn_count",
    "decision_count",
    "random_consumption_count",
    "event_count",
    "event_chain_tip",
    "final_execution_hash",
    "final_game_state_hash",
}
_ROOT_FIELDS = {
    "header",
    "decisions",
    "random_consumptions",
    "events",
    "event_hash_chain",
    "outcome",
    "authoritative_private",
    "player_visible",
    "record_sha256",
}

_PRODUCTION_INITIAL_CONFIGURATION_FIELDS = {
    "deck_path",
    "player_hp",
    "player_max_hp",
    "initial_hand_count",
    "shuffle",
    "max_steps",
    "outcome_policy_identity",
}
_FORMAL_DUEL_INITIAL_CONFIGURATION_FIELDS = {
    "formal_duel_configuration",
    "analysis_only",
    "max_steps",
}

_PRIVATE_FIELDS = {
    "schema",
    "session_id",
    "session_secret_hex",
}

AUTHORITATIVE_PRIVATE_SCHEMA = "sgs-authoritative-private-v1"

# 初始发牌、摸牌阶段与普通摸牌的非公开获得reason；对手/旁观者视图必须脱敏
_PRIVATE_GAIN_REASONS: frozenset[str] = frozenset(
    {"initial_hand", "draw_phase"}
)

# 绑定隐藏权威状态的摘要键：公开投影必须递归移除（B1-a）。
# context_sha256 只绑定公开上下文（不含手牌/牌堆秘密），予以保留。
_HIDDEN_DIGEST_KEYS: frozenset[str] = frozenset(
    {
        "state_hash",
        "state_sha256",
        "execution_hash",
        "execution_sha256",
        "event_hash",
        "event_chain_tip",
        "record_sha256",
        "legal_action_set_sha256",
        "chosen_action_id",
        "action_id",
    }
)


def _redact_hidden_digests(value: object) -> object:
    """递归移除动作负载与选择数据中的全部权威状态摘要（B1-a）。

    对 payload、嵌套 payload、目标选择数据、响应上下文等所有层级生效；
    任何以隐藏权威状态为输入的 *_sha256 都不进入公开投影，仅保留
    ``context_sha256``（绑定公开上下文）与 ``player_visible_sha256``
    （基于已脱敏投影独立计算）。
    """

    if isinstance(value, Mapping):
        redacted: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                redacted[key] = _redact_hidden_digests(item)
                continue
            lowered = key.lower()
            if key in _HIDDEN_DIGEST_KEYS:
                continue
            if (
                lowered.endswith("_sha256")
                and lowered not in ("context_sha256", "player_visible_sha256")
            ):
                continue
            redacted[key] = _redact_hidden_digests(item)
        return redacted
    if isinstance(value, (list, tuple)):
        return [_redact_hidden_digests(item) for item in value]
    return value


def _redact_private_hand_event(
    event: Mapping[str, object], viewer_id: str | None
) -> dict[str, object]:
    """按观察者身份脱敏事件中的隐藏手牌实体信息（CP-04L）。

    公开获得路径（五谷公开选择、顺手牵羊公开获得、借刀交武器等）保持公开；
    仅对初始发牌、摸牌等非公开获得按“接收者本人可见、其他人只见数量与
    reason”规则处理。"""

    event_type = event.get("event_type")
    if event_type == "card_gained":
        payload = event.get("payload", {})
        reason = str(payload.get("reason", "")) if isinstance(payload, Mapping) else ""
        target_ids = event.get("target_ids")
        recipient = None
        if isinstance(target_ids, (list, tuple)) and target_ids:
            recipient = target_ids[0]
        if reason in _PRIVATE_GAIN_REASONS and recipient != viewer_id:
            redacted: dict[str, object] = dict(event)
            redacted["card_instance_id"] = None
            redacted["card_key"] = None
            redacted["payload"] = {
                "reason": reason,
                "redacted": True,
                "redacted_by_viewer": viewer_id,
            }
            return redacted
        return dict(event)
    if event_type == "card_moved":
        payload = event.get("payload", {})
        if not isinstance(payload, Mapping):
            return dict(event)
        source = payload.get("source")
        destination = payload.get("destination")
        if (
            isinstance(source, Mapping)
            and isinstance(destination, Mapping)
            and source.get("kind") == "draw_pile"
            and destination.get("kind") == "hand"
        ):
            owner = destination.get("owner_id")
            if owner != viewer_id:
                redacted = dict(event)
                redacted["card_instance_id"] = None
                redacted["card_key"] = None
                redacted["payload"] = {
                    "source": dict(source),
                    "destination": dict(destination),
                    "reason": str(payload.get("reason", "")),
                    "redacted": True,
                    "redacted_by_viewer": viewer_id,
                }
                return redacted
        return dict(event)
    return dict(event)


_DISCARD_PHASE_OPERATIONS: frozenset[str] = frozenset(
    {
        "select_discard_card",
        "unselect_discard_card",
        "discard_phase_submit",
    }
)


def _redact_discard_selection_handle(
    action: Mapping[str, object],
) -> dict[str, object]:
    """行动者本人视图：把弃牌阶段动作的会话绑定选择句柄确定性置空。

    句柄是绑定会话秘密的一次性隐藏手牌选择材料，对公开投影无意义且会
    破坏跨记录不可区分性（重洗顺序脱敏测试要求两份记录的行动者本人视图
    一致）；弃牌选择动作的实体身份（card_instance_id）仍保留，因为那是
    弃牌者本人的自信息。群体响应等其他窗口的句柄保留策略不受影响。"""

    redacted = dict(action)
    payload = redacted.get("payload")
    if not isinstance(payload, Mapping):
        return redacted
    operation = payload.get("operation")
    if operation not in _DISCARD_PHASE_OPERATIONS:
        return redacted
    new_payload = dict(payload)
    if "handle" in new_payload:
        new_payload["handle"] = None
    redacted["payload"] = new_payload
    return redacted


def _project_public_context(
    context: Mapping[str, object], viewer_id: str | None
) -> dict[str, object]:
    """投影单步公开上下文，防止运行时私有选择状态旁路泄露。

    ``ActionContext`` 是权威重执行材料，不天然等于公开信息。弃牌阶段的
    ``discard_phase_selected_ids`` 是行动者仍在手牌中的实体 ID；对手或
    旁观者只能知道选择进度，不能看到这些 ID。投影同时递归移除绑定隐藏
    状态的摘要，随后由调用方对公开 context 重新计算 ``context_sha256``。
    """

    projected = _redact_hidden_digests(context)
    if not isinstance(projected, Mapping):  # pragma: no cover - context 契约防线
        raise ProductionReplayFormatError("决策context必须是JSON对象")
    result = dict(projected)
    actor_id = str(result.get("actor_id", ""))
    metadata = result.get("metadata")
    if isinstance(metadata, Mapping):
        public_metadata = dict(metadata)
        selected = public_metadata.get("discard_phase_selected_ids")
        if viewer_id != actor_id and isinstance(selected, (list, tuple)):
            public_metadata.pop("discard_phase_selected_ids", None)
            public_metadata["discard_phase_selected_count"] = len(selected)
        result["metadata"] = public_metadata
    return result


def _project_public_events(
    events: Sequence[Mapping[str, object]],
    viewer_id: str | None,
) -> tuple[dict[str, object], ...]:
    """按观察者身份投影公开事件流（CP-04L 审计修复 B1）。

    同一次连续重洗产生的逐卡 ``card_moved(reason=reshuffle)`` 聚合为一条
    公开汇总事件（只公开重洗事实与张数，不公开实体身份或洗后顺序）；
    其余事件继续按隐藏手牌获得规则脱敏。权威回放记录本身不做任何改变，
    本投影只作用于 player_visible 导出。

    B1-c：隐藏获得以来源区域语义判定——任何从 DRAW_PILE 进入某玩家
    HAND 的实体（card_moved 与其配对的 card_gained），无论 reason 为何
    （initial_hand／draw_phase／tiesuo_recast／无中生有等），其牌面实体
    信息默认只对获得者本人可见；对手与公共视图只见获得数量、recipient
    与 reason。公开区域（REVEALED／装备区等）进入手牌保持公开。
    """

    hidden_draw_recipients: dict[str, str] = {}
    for event in events:
        if (
            event.get("event_type") == "card_moved"
            and isinstance(event.get("payload"), Mapping)
            and event.get("card_instance_id") is not None
        ):
            payload = event["payload"]
            source = payload.get("source")
            destination = payload.get("destination")
            if (
                isinstance(source, Mapping)
                and isinstance(destination, Mapping)
                and source.get("kind") == "draw_pile"
                and destination.get("kind") == "hand"
            ):
                hidden_draw_recipients[str(event["card_instance_id"])] = str(
                    destination.get("owner_id") or ""
                )

    def _is_hidden_gain(event: Mapping[str, object]) -> bool:
        if event.get("event_type") == "card_moved":
            payload = event.get("payload", {})
            source = payload.get("source")
            destination = payload.get("destination")
            return (
                isinstance(source, Mapping)
                and isinstance(destination, Mapping)
                and source.get("kind") == "draw_pile"
                and destination.get("kind") == "hand"
            )
        if event.get("event_type") == "card_gained":
            return event.get("card_instance_id") in hidden_draw_recipients
        return False

    def _redact_for_viewer(event: Mapping[str, object]) -> dict[str, object]:
        redacted = _redact_private_hand_event(event, viewer_id)
        if redacted.get("event_type") == "card_gained":
            instance_id = redacted.get("card_instance_id")
            recipient = (redacted.get("target_ids") or [None])[0]
            if (
                instance_id in hidden_draw_recipients
                and hidden_draw_recipients[instance_id] == recipient
                and recipient != viewer_id
            ):
                redacted = dict(redacted)
                redacted["card_instance_id"] = None
                redacted["card_key"] = None
                redacted["payload"] = {
                    "reason": str(
                        redacted.get("payload", {}).get("reason", "")
                    ),
                    "redacted": True,
                    "redacted_by_viewer": viewer_id,
                }
        return redacted

    projected: list[dict[str, object]] = []
    death_cleanup_pending: list[dict[str, object]] = []
    private_gain_pending: list[dict[str, object]] = []

    def _sorted_death_cleanup(
        items: list[dict[str, object]],
    ) -> list[dict[str, object]]:
        ordered = sorted(
            items,
            key=lambda item: str(item.get("card_instance_id", "")),
        )
        start = next(
            (item.get("sequence") for item in items if item.get("sequence") is not None),
            None,
        )
        if start is None:
            return ordered
        renumbered: list[dict[str, object]] = []
        for offset, item in enumerate(ordered):
            copy_item = dict(item)
            copy_item["sequence"] = int(start) + offset
            renumbered.append(_redact_for_viewer(copy_item))
        return renumbered

    def _sorted_private_gain(
        items: list[dict[str, object]],
    ) -> list[dict[str, object]]:
        """隐藏获得批次按实体ID稳定排序并重写批次内sequence。

        摸牌事件的逐张顺序镜像隐藏摸牌顺序（含重洗后的新牌堆顶顺序）；
        即使获得者本人视图也只暴露摸到哪些牌（集合），不暴露摸牌顺序。
        """

        ordered = sorted(
            items,
            key=lambda item: (
                str(item.get("card_instance_id", "")),
                0 if item.get("event_type") == "card_moved" else 1,
            ),
        )
        start = next(
            (
                item.get("sequence")
                for item in items
                if item.get("sequence") is not None
            ),
            None,
        )
        renumbered: list[dict[str, object]] = []
        for offset, item in enumerate(ordered):
            copy_item = dict(item)
            if start is not None:
                copy_item["sequence"] = int(start) + offset
            renumbered.append(_redact_for_viewer(copy_item))
        return renumbered

    for event in events:
        redacted = _redact_for_viewer(event)
        if (
            redacted.get("event_type") == "card_moved"
            and isinstance(redacted.get("payload"), Mapping)
            and redacted["payload"].get("reason") == "reshuffle"
        ):
            if projected and projected[-1].get("_reshuffle_aggregate") is True:
                aggregate = projected[-1]
                payload = aggregate["payload"]
                assert isinstance(payload, dict)
                payload["count"] = int(payload["count"]) + 1
                continue
            projected.append(
                {
                    "event_type": "card_moved",
                    "card_instance_id": None,
                    "card_key": None,
                    "material_card_instance_ids": [],
                    "card_user": None,
                    "damage_source": None,
                    "skill_owner": None,
                    "equipment_owner": None,
                    "kill_credit": None,
                    "target_ids": [],
                    "payload": {
                        "reason": "reshuffle",
                        "count": 1,
                        "from_zone": {"kind": "discard_pile"},
                        "to_zone": {"kind": "draw_pile"},
                        "redacted": True,
                        "redacted_by_viewer": viewer_id,
                    },
                    "_reshuffle_aggregate": True,
                }
            )
            continue
        if (
            redacted.get("event_type") == "card_moved"
            and redacted.get("payload", {}).get("reason") == "death_cleanup"
        ):
            # 死亡清理是公开化事件（死亡时手牌公开），但逐张清理顺序
            # 与 sequence 一起镜像隐藏摸牌顺序；公开投影按实体ID稳定排序
            # 并重写批次内 sequence，消除顺序通道。
            if private_gain_pending:
                projected.extend(_sorted_private_gain(private_gain_pending))
                private_gain_pending = []
            death_cleanup_pending.append(event)
            continue
        if _is_hidden_gain(event):
            if death_cleanup_pending:
                projected.extend(_sorted_death_cleanup(death_cleanup_pending))
                death_cleanup_pending = []
            private_gain_pending.append(event)
            continue
        if death_cleanup_pending:
            projected.extend(_sorted_death_cleanup(death_cleanup_pending))
            death_cleanup_pending = []
        if private_gain_pending:
            projected.extend(_sorted_private_gain(private_gain_pending))
            private_gain_pending = []
        projected.append(redacted)
    if death_cleanup_pending:
        projected.extend(_sorted_death_cleanup(death_cleanup_pending))
    if private_gain_pending:
        projected.extend(_sorted_private_gain(private_gain_pending))
    # 移除内部聚合标记（不进入公开导出）
    return tuple(
        {
            key: value
            for key, value in item.items()
            if key != "_reshuffle_aggregate"
        }
        for item in projected
    )


@dataclass(frozen=True, slots=True)
class ProductionReexecutionReplay:
    """完整、可保存且可由真实规则路径重新执行的生产批次记录。"""

    header: Mapping[str, object]
    decisions: tuple[Mapping[str, object], ...]
    random_consumptions: tuple[Mapping[str, object], ...]
    events: tuple[Mapping[str, object], ...]
    event_hash_chain: tuple[str, ...]
    outcome: Mapping[str, object]
    authoritative_private: Mapping[str, object] = field(default_factory=dict)
    player_visible: bool = False
    record_sha256: str = field(default="")

    def __post_init__(self) -> None:
        header = _plain(_require_mapping(self.header, "header"))
        decisions = tuple(
            _plain(_require_mapping(item, f"decisions[{index}]"))
            for index, item in enumerate(
                _require_sequence(self.decisions, "decisions")
            )
        )
        random_consumptions = tuple(
            _plain(_require_mapping(item, f"random_consumptions[{index}]"))
            for index, item in enumerate(
                _require_sequence(
                    self.random_consumptions, "random_consumptions"
                )
            )
        )
        events = tuple(
            _plain(_require_mapping(item, f"events[{index}]"))
            for index, item in enumerate(
                _require_sequence(self.events, "events")
            )
        )
        event_hash_chain = tuple(
            item
            for item in _require_sequence(
                self.event_hash_chain, "event_hash_chain"
            )
        )
        if any(
            not isinstance(item, str) or len(item) != 64
            for item in event_hash_chain
        ):
            raise ProductionReplayFormatError(
                "event_hash_chain每一项必须是64位SHA-256"
            )
        outcome = _plain(_require_mapping(self.outcome, "outcome"))
        _require_exact_fields(header, _HEADER_FIELDS, "header")
        _require_exact_fields(outcome, _OUTCOME_FIELDS, "outcome")
        private = _plain(
            _require_mapping(self.authoritative_private, "authoritative_private")
        )
        _require_exact_fields(private, _PRIVATE_FIELDS, "authoritative_private")
        if private["schema"] != AUTHORITATIVE_PRIVATE_SCHEMA:
            raise ProductionReplayFormatError(
                "authoritative_private.schema 不是受支持的权威私有材料版本"
            )
        if not isinstance(private["session_id"], str) or not private["session_id"]:
            raise ProductionReplayFormatError(
                "authoritative_private.session_id 必须是非空字符串"
            )
        session_secret_hex = private["session_secret_hex"]
        if not isinstance(session_secret_hex, str) or len(session_secret_hex) != 64:
            raise ProductionReplayFormatError(
                "authoritative_private.session_secret_hex 必须是64位十六进制（32字节）"
            )
        try:
            bytes.fromhex(session_secret_hex)
        except ValueError as exc:
            raise ProductionReplayFormatError(
                "authoritative_private.session_secret_hex 不是合法十六进制"
            ) from exc
        if self.player_visible is not False:
            raise ProductionReplayFormatError(
                "权威回放记录必须标记 player_visible=false"
            )
        for index, decision in enumerate(decisions):
            _require_exact_fields(
                decision, _DECISION_FIELDS, f"decisions[{index}]"
            )
            if decision["index"] != index:
                raise ProductionReplayFormatError(
                    "决策索引必须从0连续递增"
                )

        if header["schema_version"] != REEXECUTION_SCHEMA:
            raise ProductionReplayFormatError("不支持的规则重执行回放schema")
        if header["mode_id"] not in {
            PRODUCTION_BASIC_CARDS_MODE,
            FORMAL_NO_SKILL_DUEL_MODE,
        }:
            raise ProductionReplayFormatError(
                "规则重执行回放模式不属于可信生产模式白名单"
            )
        if header["test_only"] is not False:
            raise ProductionReplayFormatError(
                "生产基本牌批次回放必须标记test_only=false"
            )
        if header["formal_result"] is not False:
            # Milestone B 正式 release 后，正式单挑回放允许 formal_result=true；
            # 防伪要求：仅正式单挑模式，且 initial_configuration 必须绑定
            # 项目 canonical formal profile 且 analysis_only=false（在下方
            # 正式单挑配置解析中继续校验）。
            if header["mode_id"] != FORMAL_NO_SKILL_DUEL_MODE:
                raise ProductionReplayFormatError(
                    "正式结果只能出现在正式单挑模式回放中"
                )
        if header["production_basic_cards_batch"] is not True:
            raise ProductionReplayFormatError(
                "生产基本牌批次回放必须标记production_basic_cards_batch=true"
            )
        initial_configuration = _require_mapping(
            header["initial_configuration"], "header.initial_configuration"
        )
        if header["mode_id"] == FORMAL_NO_SKILL_DUEL_MODE:
            _require_exact_fields(
                initial_configuration,
                _FORMAL_DUEL_INITIAL_CONFIGURATION_FIELDS,
                "正式单挑initial_configuration",
            )
            if not isinstance(initial_configuration["analysis_only"], bool):
                raise ProductionReplayFormatError(
                    "正式单挑initial_configuration.analysis_only必须是布尔值"
                )
            if header["formal_result"] is not False:
                if initial_configuration["analysis_only"] is not False:
                    raise ProductionReplayFormatError(
                        "正式结果回放禁止analysis_only"
                    )
                from .formal_duel import FormalDuelConfiguration

                raw_config = initial_configuration.get(
                    "formal_duel_configuration"
                )
                try:
                    canonical_replay_config = (
                        FormalDuelConfiguration.from_canonical_profile_value(
                            raw_config
                        )
                    )
                except Exception:
                    canonical_replay_config = None
                if canonical_replay_config is None:
                    raise ProductionReplayFormatError(
                        "正式结果回放必须绑定项目canonical formal profile"
                    )
        else:
            _require_exact_fields(
                initial_configuration,
                _PRODUCTION_INITIAL_CONFIGURATION_FIELDS,
                "生产批次initial_configuration",
            )
        max_steps = initial_configuration["max_steps"]
        if (
            isinstance(max_steps, bool)
            or not isinstance(max_steps, int)
            or max_steps < 1
        ):
            raise ProductionReplayFormatError(
                "initial_configuration.max_steps必须是正整数"
            )
        step_count = outcome["step_count"]
        if (
            isinstance(step_count, bool)
            or not isinstance(step_count, int)
            or step_count < 0
        ):
            raise ProductionReplayFormatError("终局step_count必须是非负整数")
        if max_steps < step_count:
            raise ProductionReplayFormatError(
                "initial_configuration.max_steps不能小于终局step_count"
            )
        if outcome["finish_reason"] != "opponent_confirmed_dead":
            raise ProductionReplayFormatError(
                "终局finish_reason必须是opponent_confirmed_dead"
            )
        if outcome["decision_count"] != len(decisions):
            raise ProductionReplayFormatError(
                "终局decision_count与决策数量不一致"
            )
        if outcome["random_consumption_count"] != len(random_consumptions):
            raise ProductionReplayFormatError(
                "终局random_consumption_count与随机记录数量不一致"
            )
        if outcome["event_count"] != len(events):
            raise ProductionReplayFormatError(
                "终局event_count与事件数量不一致"
            )
        expected_event_chain = _build_event_hash_chain(events)
        if event_hash_chain != expected_event_chain:
            raise ProductionReplayFormatError(
                "event_hash_chain与完整事件流不一致"
            )
        expected_tip = (
            expected_event_chain[-1] if expected_event_chain else _EVENT_CHAIN_ANCHOR
        )
        if outcome["event_chain_tip"] != expected_tip:
            raise ProductionReplayFormatError(
                "终局event_chain_tip与事件前向哈希链不一致"
            )
        if header["deck_hash"] != sha256_value(header["deck_definition"]):
            raise ProductionReplayFormatError("牌堆定义哈希不匹配")
        if header["initial_rng_state_sha256"] != sha256_value(
            header["initial_rng_state"]
        ):
            raise ProductionReplayFormatError("初始随机状态哈希不匹配")

        object.__setattr__(self, "header", _freeze(header))
        object.__setattr__(self, "decisions", _freeze(decisions))
        object.__setattr__(
            self, "random_consumptions", _freeze(random_consumptions)
        )
        object.__setattr__(self, "events", _freeze(events))
        object.__setattr__(self, "event_hash_chain", event_hash_chain)
        object.__setattr__(self, "outcome", _freeze(outcome))
        object.__setattr__(
            self,
            "authoritative_private",
            _freeze(
                _require_mapping(
                    self.authoritative_private, "authoritative_private"
                )
            ),
        )

        calculated = sha256_value(self._material_dict())
        supplied = self.record_sha256
        if supplied:
            if not isinstance(supplied, str) or len(supplied) != 64:
                raise ProductionReplayFormatError(
                    "record_sha256必须是64位SHA-256"
                )
            if supplied != calculated:
                raise ProductionReplayFormatError(
                    "总记录SHA-256不匹配，回放可能被篡改"
                )
        object.__setattr__(self, "record_sha256", calculated)

    def _material_dict(self) -> dict[str, object]:
        return {
            "header": _plain(self.header),
            "decisions": _plain(self.decisions),
            "random_consumptions": _plain(self.random_consumptions),
            "events": _plain(self.events),
            "event_hash_chain": list(self.event_hash_chain),
            "outcome": _plain(self.outcome),
            "authoritative_private": _plain(self.authoritative_private),
            "player_visible": self.player_visible,
        }

    def verify_integrity(self) -> bool:
        if sha256_value(self._material_dict()) != self.record_sha256:
            raise ProductionReplayFormatError(
                "总记录SHA-256不匹配，回放可能被篡改"
            )
        return True

    def to_dict(self) -> dict[str, object]:
        value = self._material_dict()
        value["record_sha256"] = self.record_sha256
        return value

    def player_visible_payload(
        self,
        viewer_id: str | None = None,
        *,
        valid_player_ids: tuple[str, ...] = ("p1", "p2"),
    ) -> dict[str, object]:
        """返回不包含权威私有材料的玩家可见回放导出（CP-04L 双视角脱敏）。

        默认 ``viewer_id=None`` 表示公共/旁观者视图；传入角色ID时该角色可以
        看到自己获得到手牌区的实例与牌面，对手视图中初始发牌、摸牌与非公开
        获得的 CARD_GAINED/card_moved 不暴露实例ID、card_key、牌名、花色或
        点数，只保留公开可知的数量变化与reason。导出同时移除 seed、
        initial_rng_state、随机消费记录等可反推牌堆顺序或下一张顶牌的材料，
        以及 ``authoritative_private``（会话秘密与句柄映射）；权威重执行
        拒绝此类导出（缺少私有材料直接失败关闭）。

        POST-B C1：合法观察者集合由 ``valid_player_ids`` 显式提供（默认保持
        正式双人会话的 ("p1", "p2") 以兼容既有调用），不再使用
        ``observer != p1 则按 p2`` 之类的二元逻辑；多人会话应传入其权威
        玩家ID元组，非法ID一律失败关闭而不是静默当作旁观者。
        """

        if viewer_id is not None:
            if not isinstance(viewer_id, str) or not viewer_id.strip():
                raise ValueError(
                    "viewer_id必须是None或非空字符串（正式会话合法角色ID）"
                )
            if not isinstance(valid_player_ids, tuple) or any(
                not isinstance(value, str) or not value.strip()
                for value in valid_player_ids
            ):
                raise TypeError(
                    "valid_player_ids必须是非空字符串元组"
                )
            if viewer_id not in valid_player_ids:
                raise ValueError(
                    f"viewer_id={viewer_id!r}不是正式会话中的合法角色ID；"
                    "不得把非法ID静默当作旁观者"
                )

        value = self._material_dict()
        del value["authoritative_private"]
        header = dict(_plain(value["header"]))
        for key in ("seed", "initial_rng_state", "initial_rng_state_sha256"):
            header.pop(key, None)
        for key in ("initial_execution_hash", "initial_game_state_hash"):
            header.pop(key, None)
        header["rng_material_redacted"] = True
        value["header"] = header
        value["random_consumptions"] = []
        value["random_consumption_count"] = len(self.random_consumptions)
        value["events"] = list(
            _project_public_events(value["events"], viewer_id)
        )
        # 哈希旁路防护：权威事件哈希链与权威状态/执行哈希绑定未脱敏材料，
        # 小候选空间（如两张牌重洗的两种排列）可被穷举恢复，必须从公开
        # 投影移除；权威记录中的原始哈希全部保留。
        value["event_hash_chain"] = []
        outcome = dict(_plain(value["outcome"]))
        for key in (
            "event_chain_tip",
            "final_execution_hash",
            "final_game_state_hash",
        ):
            outcome.pop(key, None)
        value["outcome"] = outcome
        redacted_decisions: list[dict[str, object]] = []
        for decision in value["decisions"]:
            redacted_decision = dict(decision)
            for key in (
                "state_before_sha256",
                "state_after_sha256",
                "execution_before_sha256",
                "execution_after_sha256",
                "chosen_action_id",
                "legal_action_set_sha256",
            ):
                redacted_decision.pop(key, None)
            raw_context = decision.get("context", {})
            if not isinstance(raw_context, Mapping):
                raise ProductionReplayFormatError("决策context必须是JSON对象")
            public_context = _project_public_context(raw_context, viewer_id)
            redacted_decision["context"] = public_context
            # 原 context_sha256 绑定权威 context（可能包含隐藏手牌实体ID），
            # 不能保留；公开视图只发布脱敏 context 的独立哈希。
            redacted_decision["context_sha256"] = sha256_value(public_context)
            actor_id = str(raw_context.get("actor_id", ""))
            if viewer_id == actor_id:
                # 行动者本人视图：保留本人当时的合法动作，但递归移除
                # 全部权威状态摘要（B1-a）并稳定排序（不保留手牌区域
                # 顺序）；本人动作负载中其他角色的隐藏句柄等仍按项目
                # 句柄机制处理，此处不做额外推断。
                chosen_action = decision.get("chosen_action")
                if isinstance(chosen_action, Mapping):
                    redacted_decision["chosen_action"] = (
                        _redact_discard_selection_handle(
                            _redact_hidden_digests(chosen_action)
                        )
                    )
                legal_actions = decision.get("legal_actions")
                if isinstance(legal_actions, (list, tuple)):
                    public_actions = [
                        _redact_discard_selection_handle(
                            _redact_hidden_digests(action)
                        )
                        for action in legal_actions
                    ]
                    redacted_decision["legal_actions"] = sorted(
                        public_actions,
                        key=lambda action: canonical_json(action),
                    )
            else:
                # 非行动者／公共视图：省略本人私有动作集合（数量本身可
                # 能泄露手牌构成），对外可见结果由公开事件表达；保留
                # decision index、context（actor_id/phase/公开元数据）
                # 与随机消费计数等公开事实。
                redacted_decision.pop("legal_actions", None)
                redacted_decision.pop("chosen_action", None)
            redacted_decisions.append(redacted_decision)
        value["decisions"] = redacted_decisions
        value["player_visible"] = True
        value["viewer_id"] = viewer_id
        value["player_visible_sha256"] = sha256_value(value)
        return value

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "ProductionReexecutionReplay":
        mapping = _require_mapping(value, "回放记录")
        _require_exact_fields(mapping, _ROOT_FIELDS, "回放记录")
        return cls(
            header=_require_mapping(mapping.get("header"), "header"),
            decisions=tuple(
                _require_mapping(item, f"decisions[{index}]")
                for index, item in enumerate(
                    _require_sequence(mapping.get("decisions"), "decisions")
                )
            ),
            random_consumptions=tuple(
                _require_mapping(item, f"random_consumptions[{index}]")
                for index, item in enumerate(
                    _require_sequence(
                        mapping.get("random_consumptions"),
                        "random_consumptions",
                    )
                )
            ),
            events=tuple(
                _require_mapping(item, f"events[{index}]")
                for index, item in enumerate(
                    _require_sequence(mapping.get("events"), "events")
                )
            ),
            event_hash_chain=tuple(
                _require_sequence(mapping.get("event_hash_chain"), "event_hash_chain")
            ),
            outcome=_require_mapping(mapping.get("outcome"), "outcome"),
            authoritative_private=_require_mapping(
                mapping.get("authoritative_private"), "authoritative_private"
            ),
            player_visible=(
                mapping["player_visible"]
                if isinstance(mapping.get("player_visible"), bool)
                else _require_mapping(None, "player_visible")
            ),
            record_sha256=(
                str(mapping["record_sha256"])
                if mapping.get("record_sha256") is not None
                else ""
            ),
        )

    def save(self, path: str | Path) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return target

    @classmethod
    def load(cls, path: str | Path) -> "ProductionReexecutionReplay":
        try:
            text = Path(path).read_text(encoding="utf-8")
        except OSError as exc:
            raise ProductionReplayFormatError(f"无法读取回放文件：{path}") from exc
        try:
            value = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ProductionReplayFormatError(f"回放文件不是合法JSON：{path}") from exc
        return cls.from_dict(value)

@dataclass(frozen=True, slots=True)
class ProductionReplayVerificationResult:
    verified: bool
    winner_id: str
    decision_count: int
    random_consumption_count: int
    event_count: int
    final_execution_hash: str
    final_game_state_hash: str


def record_reference_production_batch(
    seed: int,
    *,
    deck_path: str | Path = "knowledge/三国杀牌堆数据.csv",
    player_hp: tuple[int, int] = (4, 4),
    player_max_hp: tuple[int, int] = (4, 4),
    initial_hand_count: int = 4,
    shuffle: bool = True,
    controller: Any | None = None,
    max_steps: int = 500,
    fixture: Any | None = None,
    _game: ProductionBasicCardBatch | None = None,
) -> ProductionReexecutionReplay:
    """运行确定性控制器并记录一局可严格重执行的生产基本牌批次。"""

    if isinstance(max_steps, bool) or not isinstance(max_steps, int) or max_steps < 1:
        raise ValueError("安全动作上限必须是正整数")
    if _game is None:
        game = ProductionBasicCardBatch(
            seed=seed,
            deck_path=deck_path,
            player_hp=player_hp,
            player_max_hp=player_max_hp,
            initial_hand_count=initial_hand_count,
            shuffle=shuffle,
        )
    else:
        if not isinstance(_game, ProductionBasicCardBatch):
            raise TypeError("内部生产回放工厂必须返回ProductionBasicCardBatch")
        if _game.mode_id not in {
            PRODUCTION_BASIC_CARDS_MODE,
            FORMAL_NO_SKILL_DUEL_MODE,
        }:
            raise ProductionReplayFormatError("内部生产回放模式不在可信白名单")
        game = _game
    formal_game = game.mode_id == FORMAL_NO_SKILL_DUEL_MODE
    if formal_game:
        from .formal_duel import FormalNoSkillDuelSession

        if type(game) is not FormalNoSkillDuelSession:
            raise ProductionReplayFormatError(
                "正式单挑回放必须来自canonical FormalNoSkillDuelSession"
            )
    if formal_game and fixture is not None:
        raise ProductionReplayFormatError(
            "正式单挑回放禁止夹具；必须从canonical配置自然初始化"
        )
    if fixture is not None:
        # 测试与编排专用：在初始装配后、任何决策前应用确定性夹具；
        # 夹具必须只使用不可变 GameState 与正式牌区移动接口，且重执行
        # 时传入同一夹具必须得到相同初始状态。
        fixture(game)
    authoritative_private = {
        "schema": AUTHORITATIVE_PRIVATE_SCHEMA,
        "session_id": game.session_id,
        "session_secret_hex": game.session_secret_hex,
    }
    selected_controller = controller or BatchReferenceController()
    ruleset = _ruleset_value(game)
    deck_definition = _deck_definition(game.formal_registry.records)
    initial_configuration: dict[str, object]
    if formal_game:
        formal_configuration = getattr(game, "formal_configuration", None)
        if formal_configuration is None or not hasattr(
            formal_configuration, "to_dict"
        ):
            raise ProductionReplayFormatError(
                "正式单挑会话缺少可重建的FormalDuelConfiguration"
            )
        initial_configuration = {
            "formal_duel_configuration": formal_configuration.to_dict(),
            "analysis_only": bool(getattr(game, "analysis_only", True)),
            "max_steps": max_steps,
        }
    else:
        initial_configuration = {
            "deck_path": str(deck_path),
            "player_hp": list(player_hp),
            "player_max_hp": list(player_max_hp),
            "initial_hand_count": initial_hand_count,
            "shuffle": shuffle,
            "max_steps": max_steps,
            "outcome_policy_identity": (
                game.outcome_policy.identity()
                if game.outcome_policy is not None
                else None
            ),
        }
    header = {
        "schema_version": REEXECUTION_SCHEMA,
        "engine_version": ENGINE_VERSION,
        "mode_id": game.mode_id,
        "test_only": False,
        "formal_result": (
            game.formal_result_eligible if formal_game else False
        ),
        "production_basic_cards_batch": True,
        "ruleset_version": ruleset["ruleset_version"],
        "ruleset_hash": ruleset["ruleset_hash"],
        "registry_fingerprint": ruleset["registry_fingerprint"],
        "initial_configuration": initial_configuration,
        "deck_definition": deck_definition,
        "deck_hash": sha256_value(deck_definition),
        "seed": seed,
        "initial_rng_state": game._rng.export_initial_state(),
        "initial_rng_state_sha256": game._rng.initial_state_sha256,
        "initial_rng_call_count": len(game.rng_calls),
        "initial_event_count": len(game.events),
        "initial_execution_hash": _execution_hash(game),
        "initial_game_state_hash": _game_state_hash(game),
        "fixture_applied": fixture is not None,
    }
    decisions: list[dict[str, object]] = []
    while not game.is_finished:
        if len(decisions) >= max_steps:
            raise ProductionBatchSafetyLimitError(
                f"生产批次在{max_steps}个动作后仍未结束；禁止静默判胜或近似收尾"
            )
        context = game._context()
        legal = game.legal_actions()
        chosen = selected_controller.choose(legal, context)
        assert chosen.action_id is not None
        rng_start = len(game.rng_calls)
        event_start = len(game.events)
        before_state_hash = _game_state_hash(game)
        before_execution_hash = _execution_hash(game)
        executed = game.step(BatchActionIdController(chosen.action_id))
        if executed.action_id != chosen.action_id:
            raise RuntimeError(
                "控制器提交的动作ID在真实step路径中发生变化"
            )
        context_value = _context_value(context)
        legal_values = [_action_value(action) for action in legal]
        decisions.append(
            {
                "index": len(decisions),
                "context": context_value,
                "context_sha256": sha256_value(context_value),
                "legal_actions": legal_values,
                "legal_action_set_sha256": sha256_value(legal_values),
                "chosen_action_id": chosen.action_id,
                "chosen_action": _action_value(chosen),
                "state_before_sha256": before_state_hash,
                "state_after_sha256": _game_state_hash(game),
                "execution_before_sha256": before_execution_hash,
                "execution_after_sha256": _execution_hash(game),
                "rng_start": rng_start,
                "rng_end": len(game.rng_calls),
                "event_start": event_start,
                "event_end": len(game.events),
            }
        )

    assert game.winner_id is not None
    game.assert_finished_state_invariants()
    event_values = tuple(_event_values(game))
    outcome = {
        "winner_id": game.winner_id,
        "finish_reason": (
            game.outcome_policy.finish_reason
            if game.outcome_policy is not None
            else "opponent_confirmed_dead"
        ),
        "step_count": game.step_count,
        "turn_count": game._runtime.turn_number,
        "decision_count": len(decisions),
        "random_consumption_count": len(game.rng_calls),
        "event_count": len(game.events),
        "event_chain_tip": _build_event_hash_chain(event_values)[-1],
        "final_execution_hash": _execution_hash(game),
        "final_game_state_hash": _game_state_hash(game),
    }
    return ProductionReexecutionReplay(
        header=header,
        decisions=tuple(decisions),
        random_consumptions=tuple(_rng_values(game)),
        events=event_values,
        event_hash_chain=_build_event_hash_chain(event_values),
        outcome=outcome,
        authoritative_private=authoritative_private,
        player_visible=False,
    )


def record_reference_formal_duel(
    seed: int,
    *,
    configuration: object,
    analysis_only: bool = True,
    controller: Any | None = None,
    max_steps: int = 2000,
) -> ProductionReexecutionReplay:
    """从可信 formal factory 录制同一生产核心的严格规则重执行回放。

    这里不接受牌堆路径、洗牌开关或夹具，避免调用方把测试配置包装成
    正式单挑记录。正式 profile（USER_CONFIRMED_PROJECT_FORMAL_PROFILE，
    2026-08-09）与正式执行哨兵已释放；analysis_only=false 时只接受
    canonical formal profile。
    """

    from .formal_duel import (
        FormalDuelConfiguration,
        FormalDuelReferenceController,
        FormalNoSkillDuelSession,
    )

    if not isinstance(configuration, FormalDuelConfiguration):
        raise TypeError("正式单挑回放必须接收FormalDuelConfiguration")
    if not isinstance(analysis_only, bool):
        raise TypeError("analysis_only必须是布尔值")
    game = FormalNoSkillDuelSession(
        seed=seed,
        configuration=configuration,
        analysis_only=analysis_only,
    )
    return record_reference_production_batch(
        seed,
        controller=controller or FormalDuelReferenceController(),
        max_steps=max_steps,
        _game=game,
    )


def _expect_equal(
    kind: str,
    index: int | None,
    expected: object,
    actual: object,
    message: str,
) -> None:
    if _plain(expected) != _plain(actual):
        raise ProductionReplayDivergenceError(
            kind,
            index,
            message,
            expected=_plain(expected),
            actual=_plain(actual),
        )


def _compare_sequence(
    kind: str,
    start_index: int,
    expected: Sequence[object],
    actual: Sequence[object],
) -> None:
    shared = min(len(expected), len(actual))
    for offset in range(shared):
        _expect_equal(
            kind,
            start_index + offset,
            expected[offset],
            actual[offset],
            "记录值与规则重新执行值不一致",
        )
    if len(expected) != len(actual):
        raise ProductionReplayDivergenceError(
            kind,
            start_index + shared,
            "记录数量与规则重新执行数量不一致",
            expected=len(expected),
            actual=len(actual),
        )

def reexecute_production_replay(
    record: ProductionReexecutionReplay,
    fixture: Any | None = None,
    outcome_policy: Any | None = None,
) -> ProductionReplayVerificationResult:
    """从配置重新执行规则并严格验证每项决策、随机、事件和状态。

    POST-B C1：基本批次模式的重建可由 ``outcome_policy`` 显式提供模式
    胜负策略（记录中 ``outcome_policy_identity`` 必须与其一致）；未提供
    时按既有双人回退语义重建。策略对象必须与录制时同一实现。
    """

    if not isinstance(record, ProductionReexecutionReplay):
        raise TypeError("规则重执行必须接收ProductionReexecutionReplay")
    record.verify_integrity()
    header = record.header
    config = _require_mapping(
        header["initial_configuration"], "initial_configuration"
    )
    private = _require_mapping(
        record.authoritative_private, "authoritative_private"
    )
    if private["schema"] != AUTHORITATIVE_PRIVATE_SCHEMA:
        raise ProductionReplayFormatError(
            "权威私有材料版本不受支持，无法执行规则重执行"
        )
    session_id = private["session_id"]
    session_secret = bytes.fromhex(str(private["session_secret_hex"]))
    mode_id = str(header["mode_id"])
    if mode_id == PRODUCTION_BASIC_CARDS_MODE:
        recorded_policy_identity = config.get("outcome_policy_identity")
        if recorded_policy_identity not in (None, "unregistered_outcome_policy"):
            if outcome_policy is None or (
                not hasattr(outcome_policy, "identity")
                or outcome_policy.identity() != recorded_policy_identity
            ):
                raise ProductionReplayFormatError(
                    "生产批次回放记录了模式胜负策略，但重执行未提供一致策略"
                )
        elif outcome_policy is not None and hasattr(
            outcome_policy, "identity"
        ) and outcome_policy.identity() not in (
            "unregistered_outcome_policy",
            None,
        ):
            raise ProductionReplayFormatError(
                "生产批次回放未记录模式胜负策略，但重执行提供了策略"
            )
        game = ProductionBasicCardBatch(
            seed=int(header["seed"]),
            deck_path=str(config["deck_path"]),
            player_hp=tuple(config["player_hp"]),  # type: ignore[arg-type]
            player_max_hp=tuple(config["player_max_hp"]),  # type: ignore[arg-type]
            initial_hand_count=int(config["initial_hand_count"]),
            shuffle=config["shuffle"],  # type: ignore[arg-type]
            session_id=session_id,
            session_secret=session_secret,
            outcome_policy=outcome_policy,
        )
    elif mode_id == FORMAL_NO_SKILL_DUEL_MODE:
        from .formal_duel import FormalDuelConfiguration, FormalNoSkillDuelSession

        if header.get("fixture_applied") is not False:
            raise ProductionReplayFormatError("正式单挑回放不得包含初始化夹具")
        formal_value = _require_mapping(
            config.get("formal_duel_configuration"),
            "initial_configuration.formal_duel_configuration",
        )
        analysis_only = config.get("analysis_only")
        if not isinstance(analysis_only, bool):
            raise ProductionReplayFormatError(
                "正式单挑initial_configuration.analysis_only必须是布尔值"
            )
        if analysis_only:
            # analysis-only 记录只重建分析约定配置，不授予可信来源；
            # 会话以 analysis_only=True 运行，不产生正式结果。
            formal_configuration = FormalDuelConfiguration.from_dict(
                formal_value
            )
        else:
            # 正式记录必须与 canonical formal profile 逐字段一致；验证的
            # 是 canonical 内容，而不是让 payload 自行获得 trusted
            # provenance（MB-M-005）。
            formal_configuration = (
                FormalDuelConfiguration.from_canonical_profile_value(
                    formal_value
                )
            )
        game = FormalNoSkillDuelSession(
            seed=int(header["seed"]),
            configuration=formal_configuration,
            analysis_only=analysis_only,
            session_id=session_id,
            session_secret=session_secret,
        )
    else:  # ProductionReexecutionReplay 格式校验本应先拒绝该路径
        raise ProductionReplayFormatError("规则重执行模式不属于可信工厂白名单")
    _expect_equal("mode", None, mode_id, game.mode_id, "重建会话模式不一致")
    if mode_id == FORMAL_NO_SKILL_DUEL_MODE and fixture is not None:
        raise ProductionReplayFormatError("正式单挑规则重执行不得注入夹具")
    if header.get("fixture_applied") is True:
        if fixture is None:
            raise ProductionReplayFormatError(
                "该回放录制时应用了确定性夹具；重执行必须传入同一夹具"
            )
        fixture(game)
    elif fixture is not None:
        raise ProductionReplayFormatError(
            "回放录制时未应用夹具；重执行不得额外应用夹具"
        )
    live_ruleset = _ruleset_value(game)
    _expect_equal("engine", None, header["engine_version"], ENGINE_VERSION, "引擎版本不一致")
    _expect_equal(
        "ruleset", None, header["ruleset_version"], live_ruleset["ruleset_version"], "规则版本不一致"
    )
    _expect_equal(
        "ruleset", None, header["ruleset_hash"], live_ruleset["ruleset_hash"], "规则哈希不一致"
    )
    _expect_equal(
        "ruleset",
        None,
        header["registry_fingerprint"],
        live_ruleset["registry_fingerprint"],
        "规则注册表指纹不一致",
    )
    _expect_equal(
        "deck",
        None,
        header["deck_definition"],
        _deck_definition(game.formal_registry.records),
        "牌堆定义不一致",
    )
    _expect_equal(
        "rng",
        None,
        header["initial_rng_state"],
        game._rng.export_initial_state(),
        "初始随机状态不一致",
    )
    _expect_equal(
        "state", None, header["initial_execution_hash"], _execution_hash(game), "初始执行状态不一致"
    )
    _expect_equal(
        "state", None, header["initial_game_state_hash"], _game_state_hash(game), "初始GameState不一致"
    )

    initial_rng_count = int(header["initial_rng_call_count"])
    initial_event_count = int(header["initial_event_count"])
    _compare_sequence(
        "rng",
        0,
        list(record.random_consumptions[:initial_rng_count]),
        _rng_values(game),
    )
    _compare_sequence(
        "event", 0, list(record.events[:initial_event_count]), _event_values(game)
    )

    for index, decision in enumerate(record.decisions):
        if game.is_finished:
            raise ProductionReplayDivergenceError(
                "decision", index, "记录在胜利成立后仍包含附加决策"
            )
        context = game._context()
        context_value = _context_value(context)
        legal = game.legal_actions()
        legal_values = [_action_value(action) for action in legal]
        _expect_equal("context", index, decision["context"], context_value, "行动上下文不一致")
        _expect_equal(
            "context", index, decision["context_sha256"], sha256_value(context_value), "行动上下文哈希不一致"
        )
        _expect_equal("legal_actions", index, decision["legal_actions"], legal_values, "完整合法动作集合不一致")
        _expect_equal(
            "legal_actions",
            index,
            decision["legal_action_set_sha256"],
            sha256_value(legal_values),
            "合法动作集合哈希不一致",
        )
        _expect_equal(
            "state", index, decision["state_before_sha256"], _game_state_hash(game), "动作前GameState不一致"
        )
        _expect_equal(
            "state",
            index,
            decision["execution_before_sha256"],
            _execution_hash(game),
            "动作前执行状态不一致",
        )
        _expect_equal("rng", index, decision["rng_start"], len(game.rng_calls), "动作前随机索引不一致")
        _expect_equal("event", index, decision["event_start"], len(game.events), "动作前事件索引不一致")

        chosen_id = str(decision["chosen_action_id"])
        chosen = next(
            (action for action in legal if action.action_id == chosen_id), None
        )
        if chosen is None:
            raise ProductionReplayDivergenceError(
                "decision",
                index,
                "记录动作不在重新枚举的合法动作集合中",
                expected=chosen_id,
                actual=[action.action_id for action in legal],
            )
        _expect_equal("decision", index, decision["chosen_action"], _action_value(chosen), "选择动作内容不一致")
        executed = game.step(BatchActionIdController(chosen_id))
        _expect_equal("decision", index, chosen_id, executed.action_id, "真实step提交了不同动作")

        rng_end = int(decision["rng_end"])
        event_end = int(decision["event_end"])
        _compare_sequence(
            "rng",
            int(decision["rng_start"]),
            list(record.random_consumptions[int(decision["rng_start"]):rng_end]),
            _rng_values(game)[int(decision["rng_start"]):],
        )
        _compare_sequence(
            "event",
            int(decision["event_start"]),
            list(record.events[int(decision["event_start"]):event_end]),
            _event_values(game)[int(decision["event_start"]):],
        )
        _expect_equal("rng", index, rng_end, len(game.rng_calls), "动作后随机索引不一致")
        _expect_equal("event", index, event_end, len(game.events), "动作后事件索引不一致")
        _expect_equal(
            "state", index, decision["state_after_sha256"], _game_state_hash(game), "动作后GameState不一致"
        )
        _expect_equal(
            "state",
            index,
            decision["execution_after_sha256"],
            _execution_hash(game),
            "动作后执行状态不一致",
        )

    if not game.is_finished:
        raise ProductionReplayDivergenceError(
            "decision", len(record.decisions), "决策记录结束但对局尚未结束"
        )
    _compare_sequence("rng", 0, list(record.random_consumptions), _rng_values(game))
    _compare_sequence("event", 0, list(record.events), _event_values(game))
    live_event_chain = _build_event_hash_chain(_event_values(game))
    _compare_sequence(
        "event_hash_chain", 0, list(record.event_hash_chain), list(live_event_chain)
    )
    outcome = record.outcome
    _expect_equal("winner", None, outcome["winner_id"], game.winner_id, "胜者不一致")
    _expect_equal(
        "outcome",
        None,
        outcome["finish_reason"],
        "opponent_confirmed_dead",
        "终局原因不一致",
    )
    _expect_equal("outcome", None, outcome["step_count"], game.step_count, "动作总数不一致")
    _expect_equal(
        "outcome", None, outcome["turn_count"], game._runtime.turn_number, "回合总数不一致"
    )
    _expect_equal("outcome", None, outcome["decision_count"], len(record.decisions), "决策总数不一致")
    _expect_equal(
        "outcome", None, outcome["random_consumption_count"], len(game.rng_calls), "随机消费总数不一致"
    )
    _expect_equal("outcome", None, outcome["event_count"], len(game.events), "事件总数不一致")
    live_event_tip = live_event_chain[-1] if live_event_chain else _EVENT_CHAIN_ANCHOR
    _expect_equal(
        "event_hash_chain",
        None,
        outcome["event_chain_tip"],
        live_event_tip,
        "终局事件链尖端不一致",
    )
    _expect_equal(
        "state", None, outcome["final_execution_hash"], _execution_hash(game), "最终执行哈希不一致"
    )
    _expect_equal(
        "state", None, outcome["final_game_state_hash"], _game_state_hash(game), "最终GameState哈希不一致"
    )
    assert game.winner_id is not None
    return ProductionReplayVerificationResult(
        verified=True,
        winner_id=game.winner_id,
        decision_count=len(record.decisions),
        random_consumption_count=len(game.rng_calls),
        event_count=len(game.events),
        final_execution_hash=_execution_hash(game),
        final_game_state_hash=_game_state_hash(game),
    )


__all__ = [
    "ProductionReexecutionReplay",
    "ProductionReplayDivergenceError",
    "ProductionReplayFormatError",
    "ProductionReplayVerificationResult",
    "REEXECUTION_SCHEMA",
    "record_reference_formal_duel",
    "record_reference_production_batch",
    "reexecute_production_replay",
]
