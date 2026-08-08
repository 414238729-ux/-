"""Fail-closed legal-action routing for the authoritative SGS core.

The module deliberately contains no card, mode, phase, or AI policy.  A caller
must register an explicit adapter for the exact ``(mode, phase)`` pair.  Legal
actions are re-enumerated immediately before execution, which rejects stale or
forged actions instead of silently approximating an unsupported rule.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field, replace
from enum import Enum
import hashlib
import json
import math
from types import MappingProxyType
from typing import Iterable, Mapping

from .model import GameState, ZoneRef


class ActionError(RuntimeError):
    """Base error for action routing and execution."""


class UnsupportedRuleError(ActionError):
    """Raised when the exact mode/phase rule adapter is unavailable."""


class RuleRegistrationError(ActionError):
    """Raised for an invalid or duplicate rule-adapter registration."""


class InvalidActionError(ActionError):
    """Raised when an action is invalid, stale, forged, or unauthorized."""


class ActionType(str, Enum):
    USE_CARD = "use_card"
    PLAY_CARD = "play_card"
    ACTIVATE_SKILL = "activate_skill"
    RESPOND = "respond"
    PASS = "pass"
    CHOOSE_OPTION = "choose_option"
    MOVE_CARD = "move_card"


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label}必须是非空字符串")
    return value.strip()


def _freeze_json(value: object, label: str) -> object:
    """Validate and deeply freeze a JSON-compatible value."""

    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{label}不能包含非有限浮点数")
        return value
    if isinstance(value, Mapping):
        frozen: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str) or not key.strip():
                raise ValueError(f"{label}的键必须是非空字符串")
            normalized_key = key.strip()
            if normalized_key in frozen:
                raise ValueError(f"{label}包含规范化后重复的键{normalized_key!r}")
            frozen[normalized_key] = _freeze_json(item, f"{label}.{normalized_key}")
        return MappingProxyType(frozen)
    if isinstance(value, (tuple, list)):
        return tuple(_freeze_json(item, f"{label}[]") for item in value)
    raise TypeError(f"{label}只能包含JSON兼容值")


def _jsonable(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _jsonable(item) for key, item in sorted(value.items())}
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    return value


@dataclass(frozen=True, slots=True, kw_only=True)
class ActionContext:
    """The exact rule-dispatch context for one actor."""

    mode: str
    phase: str
    actor_id: str
    turn_player_id: str | None = None
    response_window_id: str | None = None
    expected_revision: int | None = None
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "mode", _text(self.mode, "模式"))
        object.__setattr__(self, "phase", _text(self.phase, "阶段"))
        object.__setattr__(self, "actor_id", _text(self.actor_id, "行动角色"))
        if self.turn_player_id is not None:
            object.__setattr__(
                self, "turn_player_id", _text(self.turn_player_id, "当前回合角色")
            )
        if self.response_window_id is not None:
            object.__setattr__(
                self,
                "response_window_id",
                _text(self.response_window_id, "响应窗口"),
            )
        if self.expected_revision is not None:
            if (
                isinstance(self.expected_revision, bool)
                or not isinstance(self.expected_revision, int)
                or self.expected_revision < 0
            ):
                raise ValueError("预期状态版本必须是非负整数或空值")
        if not isinstance(self.metadata, Mapping):
            raise TypeError("行动上下文metadata必须是映射")
        object.__setattr__(self, "metadata", _freeze_json(self.metadata, "metadata"))


@dataclass(frozen=True, slots=True, kw_only=True)
class LegalAction:
    """A proposed or enumerated legal action.

    Adapters must return proposals with ``action_id=None``.  The public
    enumerator binds each proposal to the complete state and context.
    """

    action_type: ActionType
    actor_id: str
    card_instance_id: str | None = None
    target_ids: tuple[str, ...] = ()
    skill_id: str | None = None
    payload: Mapping[str, object] = field(default_factory=dict)
    action_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.action_type, ActionType):
            raise TypeError("action_type必须是ActionType")
        object.__setattr__(self, "actor_id", _text(self.actor_id, "行动角色"))
        if self.card_instance_id is not None:
            object.__setattr__(
                self,
                "card_instance_id",
                _text(self.card_instance_id, "实体牌ID"),
            )
        if self.skill_id is not None:
            object.__setattr__(self, "skill_id", _text(self.skill_id, "技能ID"))
        if isinstance(self.target_ids, str):
            raise TypeError("目标必须是角色ID序列，不能是字符串")
        targets = tuple(_text(target, "目标角色") for target in self.target_ids)
        if len(targets) != len(set(targets)):
            raise ValueError("目标角色不能重复")
        object.__setattr__(self, "target_ids", targets)
        if not isinstance(self.payload, Mapping):
            raise TypeError("行动payload必须是映射")
        object.__setattr__(self, "payload", _freeze_json(self.payload, "payload"))
        if self.action_id is not None:
            object.__setattr__(self, "action_id", _text(self.action_id, "行动ID"))


class RuleAdapter(ABC):
    """Explicit implementation for one exact mode/phase pair.

    Production adapters must expose a stable, manually maintained
    :attr:`adapter_version`.  Changing rule behaviour without changing that
    version is a contract violation.  ``audit_state`` must expose every piece
    of mutable adapter state that can affect legal-action enumeration.  The
    public enumerator snapshots that state before and after enumeration and
    rejects observable side effects.
    """

    @property
    @abstractmethod
    def adapter_version(self) -> str:
        """Return the stable implementation/rules version for action binding."""

        raise NotImplementedError

    @abstractmethod
    def audit_state(self) -> Mapping[str, object]:
        """Return JSON-compatible mutable state relevant to enumeration.

        A stateless adapter should return an empty mapping.  Implementations
        must not omit mutable counters, caches, RNG state, or configuration
        that can change the legal-action set.
        """

        raise NotImplementedError

    @abstractmethod
    def enumerate_legal_actions(
        self, state: GameState, context: ActionContext
    ) -> Iterable[LegalAction]:
        raise NotImplementedError

    @abstractmethod
    def apply_action(
        self, state: GameState, context: ActionContext, action: LegalAction
    ) -> GameState:
        raise NotImplementedError


class RuleRegistry:
    """Exact-match mode/phase adapter registry; no fallback is permitted."""

    def __init__(self) -> None:
        self._adapters: dict[tuple[str, str], RuleAdapter] = {}
        self._adapter_versions: dict[tuple[str, str], str] = {}

    def register(self, mode: str, phase: str, adapter: RuleAdapter) -> None:
        key = (_text(mode, "模式"), _text(phase, "阶段"))
        if not isinstance(adapter, RuleAdapter):
            raise TypeError("规则处理器必须是RuleAdapter实例")
        if key in self._adapters:
            raise RuleRegistrationError(
                f"模式{key[0]!r}的阶段{key[1]!r}已经注册处理器，禁止静默覆盖"
            )
        version = _adapter_version(adapter)
        _adapter_audit_value(adapter)
        self._adapters[key] = adapter
        self._adapter_versions[key] = version

    def resolve(self, mode: str, phase: str) -> RuleAdapter:
        key = (_text(mode, "模式"), _text(phase, "阶段"))
        try:
            adapter = self._adapters[key]
        except KeyError as exc:
            raise UnsupportedRuleError(
                f"模式{key[0]!r}的阶段{key[1]!r}尚未实现；禁止空默认或近似处理"
            ) from exc
        registered_version = self._adapter_versions[key]
        current_version = _adapter_version(adapter)
        if current_version != registered_version:
            raise RuleRegistrationError(
                f"模式{key[0]!r}阶段{key[1]!r}的处理器版本在注册后由"
                f"{registered_version!r}变为{current_version!r}；必须重新建立注册表"
            )
        return adapter

    @property
    def registered_keys(self) -> tuple[tuple[str, str], ...]:
        return tuple(sorted(self._adapters))

    def binding_value(self, mode: str, phase: str) -> dict[str, object]:
        """Return the exact immutable registration identity used by action IDs."""

        key = (_text(mode, "模式"), _text(phase, "阶段"))
        adapter = self.resolve(*key)
        registrations: list[dict[str, object]] = []
        for registered_key in sorted(self._adapters):
            registered_adapter = self._adapters[registered_key]
            stored_version = self._adapter_versions[registered_key]
            current_version = _adapter_version(registered_adapter)
            if current_version != stored_version:
                raise RuleRegistrationError(
                    f"模式{registered_key[0]!r}阶段{registered_key[1]!r}的处理器版本"
                    f"在注册后由{stored_version!r}变为{current_version!r}；"
                    "必须重新建立注册表"
                )
            registrations.append(
                {
                    "mode": registered_key[0],
                    "phase": registered_key[1],
                    "adapter_type": _adapter_type_name(registered_adapter),
                    "adapter_version": stored_version,
                }
            )
        registry_encoded = json.dumps(
            registrations,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return {
            "registry_fingerprint": hashlib.sha256(
                registry_encoded.encode("utf-8")
            ).hexdigest(),
            "adapter_type": _adapter_type_name(adapter),
            "adapter_version": self._adapter_versions[key],
        }


def _adapter_type_name(adapter: RuleAdapter) -> str:
    adapter_type = type(adapter)
    return f"{adapter_type.__module__}.{adapter_type.__qualname__}"


def _adapter_version(adapter: RuleAdapter) -> str:
    try:
        version = adapter.adapter_version
    except Exception as exc:  # pragma: no cover - defensive adapter boundary
        raise RuleRegistrationError("无法读取规则处理器的稳定版本") from exc
    try:
        return _text(version, "规则处理器版本")
    except (TypeError, ValueError) as exc:
        raise RuleRegistrationError("规则处理器必须声明稳定的非空版本") from exc


def _adapter_audit_value(adapter: RuleAdapter) -> dict[str, object]:
    try:
        audit_state = adapter.audit_state()
    except Exception as exc:  # pragma: no cover - defensive adapter boundary
        raise InvalidActionError("无法读取规则处理器的可观察审计状态") from exc
    if not isinstance(audit_state, Mapping):
        raise TypeError("规则处理器audit_state必须返回映射")
    frozen = _freeze_json(audit_state, "规则处理器审计状态")
    assert isinstance(frozen, Mapping)
    jsonable = _jsonable(frozen)
    assert isinstance(jsonable, dict)
    return jsonable


def _zone_value(zone: ZoneRef) -> dict[str, object]:
    return {
        "kind": zone.kind.value,
        "owner_id": zone.owner_id,
        "equipment_slot": zone.equipment_slot,
        "special_zone": zone.special_zone,
    }


def _state_fingerprint(state: GameState) -> str:
    assert state.zone_order is not None
    material = {
        "deck_id": state.deck_id,
        "revision": state.revision,
        "players": [
            {
                "id": player.player_id,
                "seat": player.seat,
                "hp": player.hp,
                "max_hp": player.max_hp,
                "alive": player.alive,
            }
            for player in sorted(state.players, key=lambda item: item.player_id)
        ],
        "cards": [
            {
                "id": card.instance_id,
                "key": card.card_key,
                "name": card.card_name,
                "type": card.card_type,
                "suit": card.suit,
                "color": card.color,
                "rank": card.rank,
                "variant": card.card_variant,
                "slot": card.equipment_slot,
                "distance": card.distance_modifier,
                "location": _zone_value(state.card_locations[card.instance_id]),
            }
            for card in sorted(state.cards, key=lambda item: item.instance_id)
        ],
        "zone_order": sorted(
            [
                (
                    _zone_value(zone),
                    list(instance_ids),
                )
                for zone, instance_ids in state.zone_order.items()
            ],
            key=lambda item: json.dumps(item[0], ensure_ascii=False, sort_keys=True),
        ),
    }
    encoded = json.dumps(material, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _context_value(context: ActionContext) -> dict[str, object]:
    return {
        "mode": context.mode,
        "phase": context.phase,
        "actor_id": context.actor_id,
        "turn_player_id": context.turn_player_id,
        "response_window_id": context.response_window_id,
        "expected_revision": context.expected_revision,
        "metadata": _jsonable(context.metadata),
    }


def _action_value(action: LegalAction) -> dict[str, object]:
    return {
        "action_type": action.action_type.value,
        "actor_id": action.actor_id,
        "card_instance_id": action.card_instance_id,
        "target_ids": list(action.target_ids),
        "skill_id": action.skill_id,
        "payload": _jsonable(action.payload),
    }


def _validate_state_context(state: GameState, context: ActionContext) -> None:
    if not isinstance(state, GameState):
        raise TypeError("state必须是GameState")
    if not isinstance(context, ActionContext):
        raise TypeError("context必须是ActionContext")
    if context.expected_revision is not None and context.expected_revision != state.revision:
        raise InvalidActionError(
            f"行动上下文绑定状态版本{context.expected_revision}，当前版本为{state.revision}"
        )
    players = state.players_by_id
    actor = players.get(context.actor_id)
    if actor is None:
        raise InvalidActionError(f"行动角色{context.actor_id!r}不存在")
    if not actor.alive:
        raise InvalidActionError(f"行动角色{context.actor_id!r}已经死亡")
    if context.turn_player_id is not None and context.turn_player_id not in players:
        raise InvalidActionError(f"当前回合角色{context.turn_player_id!r}不存在")


def enumerate_legal_actions(
    state: GameState,
    context: ActionContext,
    registry: RuleRegistry,
) -> tuple[LegalAction, ...]:
    """Enumerate a stable, complete action set bound to state and context."""

    _validate_state_context(state, context)
    if not isinstance(registry, RuleRegistry):
        raise TypeError("registry必须是RuleRegistry")
    adapter = registry.resolve(context.mode, context.phase)
    state_before = _state_fingerprint(state)
    adapter_before = _adapter_audit_value(adapter)
    binding_before = registry.binding_value(context.mode, context.phase)
    proposed = adapter.enumerate_legal_actions(state, context)
    if isinstance(proposed, (str, bytes)):
        raise TypeError("规则处理器必须返回LegalAction序列")
    try:
        candidates = tuple(proposed)
    except TypeError as exc:
        raise TypeError("规则处理器必须返回LegalAction序列") from exc

    state_after = _state_fingerprint(state)
    adapter_after = _adapter_audit_value(adapter)
    binding_after = registry.binding_value(context.mode, context.phase)
    if state_after != state_before:
        raise InvalidActionError(
            "规则处理器在枚举合法动作时修改了传入GameState；枚举必须无副作用"
        )
    if adapter_after != adapter_before:
        raise InvalidActionError(
            "规则处理器在枚举合法动作时修改了可观察审计状态；枚举必须无副作用"
        )
    if binding_after != binding_before:
        raise InvalidActionError(
            "规则注册表或处理器版本在枚举合法动作期间发生变化"
        )

    state_hash = state_before
    context_value = _context_value(context)
    bound: list[LegalAction] = []
    seen_ids: set[str] = set()
    players = state.players_by_id
    cards = state.cards_by_id
    for candidate in candidates:
        if not isinstance(candidate, LegalAction):
            raise TypeError("规则处理器只能返回LegalAction")
        if candidate.action_id is not None:
            raise InvalidActionError("规则处理器不得自行签发action_id")
        if candidate.actor_id != context.actor_id:
            raise InvalidActionError("规则处理器返回了不属于当前行动角色的动作")
        # CP-04P 丈八蛇矛的虚拟杀已因 VIRTUAL_CARD_SUBCARD_LIFECYCLE_RULE_GAP
        # 保持 PARTIAL/fail-closed：撤回“virtual:”前缀的全局实体牌验证放行，
        # 避免扩大其他已证明生产路径的安全面。待丈八规则缺口解决并与丈八
        # 正式实现一起启用后再恢复（届时只放行服务器权威枚举的合法虚拟动作，
        # 客户端不能仅通过构造任意 virtual:* 字符串绕过实体牌验证）。
        if candidate.card_instance_id is not None and candidate.card_instance_id not in cards:
            raise InvalidActionError(
                f"规则处理器引用了不存在的实体牌{candidate.card_instance_id!r}"
            )
        unknown_targets = [target for target in candidate.target_ids if target not in players]
        if unknown_targets:
            raise InvalidActionError(f"规则处理器引用了不存在的目标{unknown_targets!r}")
        identity = {
            "state": state_hash,
            "context": context_value,
            "rule_binding": binding_before,
            "adapter_audit_state": adapter_before,
            "action": _action_value(candidate),
        }
        encoded = json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        action_id = "act_" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        if action_id in seen_ids:
            raise InvalidActionError("规则处理器返回了语义重复的合法动作")
        seen_ids.add(action_id)
        bound.append(replace(candidate, action_id=action_id))
    return tuple(sorted(bound, key=lambda item: item.action_id or ""))


def apply_action(
    state: GameState,
    context: ActionContext,
    action: LegalAction,
    registry: RuleRegistry,
) -> GameState:
    """Apply only an action present in the freshly enumerated legal set."""

    current = validate_action(state, context, action, registry)
    adapter = registry.resolve(context.mode, context.phase)
    updated = adapter.apply_action(state, context, current)
    if not isinstance(updated, GameState):
        raise TypeError("规则处理器apply_action必须返回GameState")
    updated.assert_card_conservation()
    return updated


def validate_action(
    state: GameState,
    context: ActionContext,
    action: LegalAction,
    registry: RuleRegistry,
) -> LegalAction:
    """Validate an issued action against the freshly enumerated legal set.

    The returned value is the canonical action emitted by the current adapter.
    Keeping validation as a public, side-effect-free step lets controllers and
    replay executors follow the explicit ``enumerate -> validate -> apply``
    pipeline without duplicating the anti-forgery checks.
    """

    if not isinstance(action, LegalAction):
        raise TypeError("action必须是LegalAction")
    if action.action_id is None:
        raise InvalidActionError("未签发action_id的动作不能执行")
    if action.actor_id != context.actor_id:
        raise InvalidActionError("动作角色与当前行动上下文不一致")
    legal_by_id = {
        candidate.action_id: candidate
        for candidate in enumerate_legal_actions(state, context, registry)
    }
    current = legal_by_id.get(action.action_id)
    if current is None:
        raise InvalidActionError("动作不在当前最新合法动作集合中，可能已过期或系伪造")
    if _action_value(current) != _action_value(action):
        raise InvalidActionError("动作内容与action_id绑定内容不一致，拒绝伪造动作")
    return current


__all__ = [
    "ActionContext",
    "ActionError",
    "ActionType",
    "InvalidActionError",
    "LegalAction",
    "RuleAdapter",
    "RuleRegistrationError",
    "RuleRegistry",
    "UnsupportedRuleError",
    "apply_action",
    "enumerate_legal_actions",
    "validate_action",
]
