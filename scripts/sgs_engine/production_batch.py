# -*- coding: utf-8 -*-
"""正式160张牌堆中六种基本牌的生产批处理会话。

本模块在权威核心（GameState、EventQueue、ResponseWindow、DamageEvent、
LegalAction、单一 DeterministicRNG 与状态哈希）之上，为六种基本牌和
最小普通锦囊垂直切片（【无中生有】、【无懈可击】）提供真实的生产结算
路径。它明确不是完整整局引擎：只包含本批次卡牌完成使用、响应、无效、
伤害、濒死、救援、死亡与胜负所需的阶段与窗口；遇到未实现卡牌时在
注册表层失败关闭。

所有动作都经过：

    enumerate_legal_actions -> validate_action -> apply_action

控制器、测试或任何调用方都不能直接修改状态；合法动作一旦签发就绑定
状态、上下文、注册表指纹与适配器审计状态，过期或伪造动作会被拒绝。
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
import json
from pathlib import Path
from types import MappingProxyType
from typing import Iterable, Mapping, Sequence

from ..deck_data import DeckRecord, load_deck_csv
from .actions import (
    ActionContext,
    ActionType,
    InvalidActionError,
    LegalAction,
    RuleAdapter,
    RuleRegistry,
    UnsupportedRuleError,
    apply_action,
    enumerate_legal_actions,
    validate_action,
)
from .engine import (
    DEFAULT_DECK_PATH,
    ENGINE_VERSION,
    AuthoritativeCoreSession,
    canonical_state_snapshot,
)
from .events import (
    DamageEvent,
    EventQueue,
    EventType,
    GameEvent,
    ResponseWindow,
)
from .model import (
    DISCARD_PILE,
    DRAW_PILE,
    PROCESSING_ZONE,
    CardInstance,
    GameState,
    PlayerState,
    ZoneRef,
)
from .production_cards import (
    FormalCardRegistry,
    SlashAdapter,
    WuxiekejiAdapter,
    WuzhongshengyouAdapter,
    is_valid_slash_target,
)
from .replay import canonical_json, sha256_value
from .rng import DeterministicRNG, RNGCall


PRODUCTION_BASIC_CARDS_MODE = "production_basic_cards_batch"


class ProductionPhase(str, Enum):
    PLAY = "play"
    SLASH_RESPONSE = "slash_response"
    TRICK_RESPONSE = "trick_response"
    DYING_RESCUE = "dying_rescue"
    END = "end"
    FINISHED = "finished"


BATCH_PHASES: tuple[ProductionPhase, ...] = (
    ProductionPhase.PLAY,
    ProductionPhase.SLASH_RESPONSE,
    ProductionPhase.TRICK_RESPONSE,
    ProductionPhase.DYING_RESCUE,
    ProductionPhase.END,
)


class ProductionBatchError(RuntimeError):
    """生产基本牌批处理会话不能继续执行时的基础异常。"""


class ProductionBatchFinishedError(ProductionBatchError):
    """胜利已经成立后仍尝试继续推进对局。"""


class ProductionBatchSafetyLimitError(ProductionBatchError):
    """动作步数超过显式安全上限时失败关闭。"""


class ProductionBatchDeckExhaustedError(ProductionBatchError):
    """牌堆与可重洗弃牌堆合计不足时失败关闭。"""


@dataclass(frozen=True, slots=True)
class BatchPhaseEntry:
    turn_number: int
    turn_player_id: str
    phase: ProductionPhase


@dataclass(frozen=True, slots=True)
class _PendingSlash:
    attacker_id: str
    target_id: str
    slash_instance_id: str
    boosted: bool


@dataclass(frozen=True, slots=True)
class _PendingTrick:
    user_id: str
    target_id: str
    trick_instance_id: str
    trick_key: str


@dataclass(frozen=True, slots=True)
class _BatchRuntime:
    current_player_id: str
    turn_number: int = 1
    phase: ProductionPhase = ProductionPhase.PLAY
    slash_used: bool = False
    wine_buff_owner_id: str | None = None
    wine_buff_used_this_play_phase: bool = False
    pending_slash: _PendingSlash | None = None
    pending_trick: _PendingTrick | None = None
    trick_effect_active: bool = False
    trick_consecutive_passes: int = 0
    trick_response_order: tuple[str, ...] = ()
    trick_response_index: int = 0
    trick_decision_count: int = 0
    pending_dying_id: str | None = None
    rescue_order: tuple[str, ...] = ()
    rescue_index: int = 0
    rescue_decision_count: int = 0
    response_window_id: str | None = None
    response_window_order: tuple[str, ...] = ()
    response_window_source_sequence: int | None = None
    winner_id: str | None = None

    def audit_value(self) -> dict[str, object]:
        pending = None
        if self.pending_slash is not None:
            pending = {
                "attacker_id": self.pending_slash.attacker_id,
                "target_id": self.pending_slash.target_id,
                "slash_instance_id": self.pending_slash.slash_instance_id,
                "boosted": self.pending_slash.boosted,
            }
        pending_trick = None
        if self.pending_trick is not None:
            pending_trick = {
                "user_id": self.pending_trick.user_id,
                "target_id": self.pending_trick.target_id,
                "trick_instance_id": self.pending_trick.trick_instance_id,
                "trick_key": self.pending_trick.trick_key,
            }
        return {
            "current_player_id": self.current_player_id,
            "turn_number": self.turn_number,
            "phase": self.phase.value,
            "slash_used": self.slash_used,
            "wine_buff_owner_id": self.wine_buff_owner_id,
            "wine_buff_used_this_play_phase": self.wine_buff_used_this_play_phase,
            "pending_slash": pending,
            "pending_trick": pending_trick,
            "trick_effect_active": self.trick_effect_active,
            "trick_consecutive_passes": self.trick_consecutive_passes,
            "trick_response_order": list(self.trick_response_order),
            "trick_response_index": self.trick_response_index,
            "trick_decision_count": self.trick_decision_count,
            "pending_dying_id": self.pending_dying_id,
            "rescue_order": list(self.rescue_order),
            "rescue_index": self.rescue_index,
            "rescue_decision_count": self.rescue_decision_count,
            "response_window_id": self.response_window_id,
            "response_window_order": list(self.response_window_order),
            "response_window_source_sequence": self.response_window_source_sequence,
            "winner_id": self.winner_id,
        }


def _zone_payload(zone: ZoneRef) -> dict[str, object]:
    return {
        "kind": zone.kind.value,
        "owner_id": zone.owner_id,
        "equipment_slot": zone.equipment_slot,
        "special_zone": zone.special_zone,
    }


def _card_key(state: GameState, instance_id: str) -> str:
    return state.cards_by_id[instance_id].card_key


def _replace_player(
    state: GameState,
    player_id: str,
    *,
    hp: int | None = None,
    alive: bool | None = None,
) -> GameState:
    """只由批处理会话调用的不可变玩家状态事务。"""

    players: list[PlayerState] = []
    found = False
    for player in state.players:
        if player.player_id != player_id:
            players.append(player)
            continue
        found = True
        players.append(
            replace(
                player,
                hp=player.hp if hp is None else hp,
                alive=player.alive if alive is None else alive,
            )
        )
    if not found:
        raise ProductionBatchError(f"找不到玩家{player_id!r}")
    return replace(state, players=tuple(players), revision=state.revision + 1)

class BatchActionIdController:
    """只从当前真实合法集合中返回指定ID，用于测试与规则重执行。"""

    strategy_version = "production-batch-action-id-controller.v1"

    def __init__(self, action_id: str) -> None:
        self._action_id = action_id

    def choose(
        self, legal_actions: Sequence[LegalAction], context: ActionContext
    ) -> LegalAction:
        del context
        for action in legal_actions:
            if action.action_id == self._action_id:
                return action
        raise ProductionBatchError(
            "指定动作不在当前真实合法动作集合中，可能已过期或系伪造"
        )


class BatchReferenceController:
    """验收用确定性控制器；只从已经签发的合法动作集合中选择。

    这不是AI。固定优先级只用于让同一状态得到稳定、可解释的验收路径。
    """

    strategy_version = "production-batch-reference-controller.v1"

    def choose(
        self, legal_actions: Sequence[LegalAction], context: ActionContext
    ) -> LegalAction:
        if not legal_actions:
            raise ProductionBatchError("规则适配器没有返回任何合法动作")
        if any(action.action_id is None for action in legal_actions):
            raise ProductionBatchError("控制器只能接收已经签发ID的合法动作")

        def priority(action: LegalAction) -> tuple[int, str, str]:
            operation = str(action.payload.get("operation", ""))
            if context.phase == ProductionPhase.SLASH_RESPONSE.value:
                rank = 0 if operation == "play_dodge" else 9
            elif context.phase == ProductionPhase.TRICK_RESPONSE.value:
                rank = 0 if operation == "use_wuxie" else 1
            elif context.phase == ProductionPhase.DYING_RESCUE.value:
                if operation == "rescue_with_peach" and action.target_ids == (
                    action.actor_id,
                ):
                    rank = 0
                elif operation == "rescue_with_wine":
                    rank = 1
                elif operation == "rescue_with_peach":
                    rank = 2
                else:
                    rank = 9
            elif context.phase == ProductionPhase.PLAY.value:
                if operation == "heal_self":
                    rank = 0
                elif operation == "use_wine_buff":
                    rank = 1
                elif operation == "use_slash":
                    rank = 2
                else:
                    rank = 9
            else:
                rank = 0 if action.action_type is not ActionType.PASS else 1
            return rank, action.card_instance_id or "", action.action_id or ""

        return min(legal_actions, key=priority)


class ScriptedBatchController:
    """按预置操作序列从真实合法集合中选动作。

    序列用尽后回退到 BatchReferenceController。用于录制包含【杀】【闪】
    【桃】【酒】的固定生产路径，不绕过合法动作集合。
    """

    strategy_version = "production-batch-scripted-controller.v1"

    def __init__(self, specs: Sequence[Mapping[str, object]]) -> None:
        self._specs: list[Mapping[str, object]] = [dict(spec) for spec in specs]
        self._reference = BatchReferenceController()

    def choose(
        self, legal_actions: Sequence[LegalAction], context: ActionContext
    ) -> LegalAction:
        for index, spec in enumerate(self._specs):
            candidates = [
                action for action in legal_actions if self._matches(action, spec)
            ]
            if candidates:
                del self._specs[index]
                return min(candidates, key=lambda action: action.action_id or "")
        return self._reference.choose(legal_actions, context)

    @staticmethod
    def _matches(action: LegalAction, spec: Mapping[str, object]) -> bool:
        for key, value in spec.items():
            if key == "operation":
                if action.payload.get("operation") != value:
                    return False
            elif key == "card_key":
                if action.payload.get("card_key") != value:
                    return False
            elif key == "target":
                if not action.target_ids or action.target_ids[0] != value:
                    return False
            elif key == "card_instance_id":
                if action.card_instance_id != value:
                    return False
            else:
                return False
        return True


class _BatchRuleAdapter(RuleAdapter):
    """生产基本牌批处理会话的阶段处理器；不包含任何卡牌规则。"""

    def __init__(self, session: "ProductionBasicCardBatch") -> None:
        self._session = session

    @property
    def adapter_version(self) -> str:
        return "production-basic-cards-batch-rules.v1"

    def audit_state(self) -> Mapping[str, object]:
        return MappingProxyType(self._session.runtime.audit_value())

    def enumerate_legal_actions(
        self, state: GameState, context: ActionContext
    ) -> Iterable[LegalAction]:
        return self._session._enumerate_for_adapter(state, context)

    def apply_action(
        self, state: GameState, context: ActionContext, action: LegalAction
    ) -> GameState:
        return self._session._apply_for_adapter(state, context, action)


@dataclass(frozen=True, slots=True)
class ProductionBatchResult:
    """生产批处理会话运行结束后的只读结果。"""

    winner_id: str
    step_count: int
    turn_count: int
    final_state: GameState
    events: tuple[GameEvent, ...]
    rng_calls: tuple[RNGCall, ...]
    phase_history: tuple[BatchPhaseEntry, ...]

class ProductionBasicCardBatch:
    """正式160张牌堆上六种基本牌的生产批处理会话。

    会话从正式牌堆CSV真实读取160张实体牌并建立
    :class:`FormalCardRegistry`，只允许六种基本牌接入生产适配器；其他
    卡牌保持未实现标记且不能fallback结算。阶段机只包含完成六种基本牌
    使用、响应、伤害、濒死、救援、死亡与胜负所需的阶段与窗口，不是
    完整整局引擎，也不允许把本批次解释为里程碑B完成。
    """

    __test__ = False

    def __init__(
        self,
        *,
        seed: int,
        deck_path: str | Path = DEFAULT_DECK_PATH,
        player_hp: tuple[int, int] = (4, 4),
        player_max_hp: tuple[int, int] = (4, 4),
        initial_hand_count: int = 4,
        shuffle: bool = True,
    ) -> None:
        if isinstance(seed, bool) or not isinstance(seed, int):
            raise TypeError("随机种子必须是整数")
        if len(player_hp) != 2 or len(player_max_hp) != 2:
            raise ValueError("生产批处理会话必须提供恰好两名角色的体力")
        for index, (hp, max_hp) in enumerate(
            zip(player_hp, player_max_hp), start=1
        ):
            if (
                isinstance(hp, bool)
                or not isinstance(hp, int)
                or isinstance(max_hp, bool)
                or not isinstance(max_hp, int)
            ):
                raise TypeError(f"第{index}名角色的初始体力与上限必须是整数")
            if hp < 1 or max_hp < 1:
                raise ValueError(f"第{index}名角色必须以至少1点体力开始")
            if hp > max_hp:
                raise ValueError(f"第{index}名角色的初始体力不能高于体力上限")
        if (
            isinstance(initial_hand_count, bool)
            or not isinstance(initial_hand_count, int)
            or initial_hand_count < 1
        ):
            raise ValueError("初始手牌数必须是正整数")
        if not isinstance(shuffle, bool):
            raise TypeError("shuffle必须是布尔值")

        deck_path = Path(deck_path)
        records, audit = load_deck_csv(deck_path, expected_total=160)
        AuthoritativeCoreSession._validate_formal_deck(records, audit)
        self._deck_path = deck_path
        self._rng = DeterministicRNG(seed)
        self._formal_registry = FormalCardRegistry(records, session=self)
        self._formal_registry.ensure_all_basic_cards_implemented()

        first_player_id = self._rng.choice(("p1", "p2"))
        self._first_player_id = first_player_id
        ordered_ids = [record.instance_id for record in records]
        if shuffle:
            self._rng.shuffle(ordered_ids)
        p1_hand = tuple(
            ordered_ids[index]
            for index in range(0, 2 * initial_hand_count, 2)
        )
        p2_hand = tuple(
            ordered_ids[index]
            for index in range(1, 2 * initial_hand_count, 2)
        )
        dealt = set(p1_hand) | set(p2_hand)
        draw_order = tuple(
            instance_id
            for instance_id in ordered_ids
            if instance_id not in dealt
        )
        players = (
            PlayerState("p1", 1, player_hp[0], player_max_hp[0]),
            PlayerState("p2", 2, player_hp[1], player_max_hp[1]),
        )
        locations = {
            instance_id: (
                ZoneRef.hand("p1")
                if instance_id in p1_hand
                else ZoneRef.hand("p2")
                if instance_id in p2_hand
                else DRAW_PILE
            )
            for instance_id in ordered_ids
        }
        self._state = GameState(
            cards=tuple(
                CardInstance.from_deck_record(record) for record in records
            ),
            players=players,
            card_locations=locations,
            zone_order={
                ZoneRef.hand("p1"): p1_hand,
                ZoneRef.hand("p2"): p2_hand,
                DRAW_PILE: draw_order,
                DISCARD_PILE: (),
                PROCESSING_ZONE: (),
            },
            deck_id=records[0].deck_id,
        )
        self._state.assert_card_conservation()
        self._events = EventQueue()
        for player_id, hand in (("p1", p1_hand), ("p2", p2_hand)):
            self._events.extend(
                GameEvent(
                    event_type=EventType.CARD_GAINED,
                    card_instance_id=instance_id,
                    card_key=_card_key(self._state, instance_id),
                    target_ids=(player_id,),
                    payload={"reason": "initial_hand"},
                )
                for instance_id in hand
            )
        # 首名角色的回合开始摸2张；这是回合结构的一部分，不是卡牌效果。
        self._state, draw_events = self._draw_cards(
            self._state, first_player_id, 2
        )
        self._events.extend(draw_events)

        self._runtime = _BatchRuntime(current_player_id=first_player_id)
        self._phase_history: list[BatchPhaseEntry] = [
            BatchPhaseEntry(1, first_player_id, ProductionPhase.PLAY)
        ]
        self._step_count = 0
        self._registry = RuleRegistry()
        for phase in BATCH_PHASES:
            self._registry.register(
                PRODUCTION_BASIC_CARDS_MODE, phase.value, _BatchRuleAdapter(self)
            )
        for key, adapter in self._formal_registry.adapters.items():
            self._registry.register(
                PRODUCTION_BASIC_CARDS_MODE, f"card:{key}", adapter
            )

    @property
    def state(self) -> GameState:
        return self._state

    @property
    def registry(self) -> RuleRegistry:
        return self._registry

    @property
    def formal_registry(self) -> FormalCardRegistry:
        return self._formal_registry

    @property
    def runtime(self) -> _BatchRuntime:
        return self._runtime

    @property
    def phase(self) -> ProductionPhase:
        return self._runtime.phase

    @property
    def current_player_id(self) -> str:
        return self._runtime.current_player_id

    @property
    def first_player_id(self) -> str:
        return self._first_player_id

    @property
    def is_finished(self) -> bool:
        return self._runtime.phase is ProductionPhase.FINISHED

    @property
    def winner_id(self) -> str | None:
        return self._runtime.winner_id

    @property
    def events(self) -> tuple[GameEvent, ...]:
        return self._events.snapshot()

    @property
    def rng_calls(self) -> tuple[RNGCall, ...]:
        return self._rng.calls

    @property
    def phase_history(self) -> tuple[BatchPhaseEntry, ...]:
        return tuple(self._phase_history)

    @property
    def step_count(self) -> int:
        return self._step_count

    @property
    def current_actor_id(self) -> str:
        runtime = self._runtime
        if runtime.phase is ProductionPhase.SLASH_RESPONSE:
            if runtime.pending_slash is None:
                raise ProductionBatchError("响应阶段缺少待响应的【杀】")
            return runtime.pending_slash.target_id
        if runtime.phase is ProductionPhase.TRICK_RESPONSE:
            if runtime.pending_trick is None:
                raise ProductionBatchError("锦囊响应阶段缺少待响应的锦囊")
            if not runtime.trick_response_order:
                raise ProductionBatchError("锦囊响应顺序为空")
            if runtime.trick_response_index >= len(runtime.trick_response_order):
                raise ProductionBatchError("锦囊响应顺序已经耗尽")
            return runtime.trick_response_order[runtime.trick_response_index]
        if runtime.phase is ProductionPhase.DYING_RESCUE:
            if not runtime.rescue_order:
                raise ProductionBatchError("濒死阶段缺少救援顺序")
            if runtime.rescue_index >= len(runtime.rescue_order):
                raise ProductionBatchError("濒死救援顺序已经耗尽")
            return runtime.rescue_order[runtime.rescue_index]
        if runtime.phase in (ProductionPhase.PLAY, ProductionPhase.END):
            return runtime.current_player_id
        raise ProductionBatchError(
            f"阶段{runtime.phase.value!r}没有可行动角色"
        )

    @staticmethod
    def opponent_of(player_id: str) -> str:
        if player_id == "p1":
            return "p2"
        if player_id == "p2":
            return "p1"
        raise ProductionBatchError(f"生产批处理会话不存在玩家{player_id!r}")

    def _context(self) -> ActionContext:
        if self.is_finished:
            raise ProductionBatchFinishedError(
                "胜利已经成立，对局不得继续执行动作"
            )
        runtime = self._runtime
        return ActionContext(
            mode=PRODUCTION_BASIC_CARDS_MODE,
            phase=runtime.phase.value,
            actor_id=self.current_actor_id,
            turn_player_id=runtime.current_player_id,
            response_window_id=runtime.response_window_id,
            expected_revision=self.state.revision,
            metadata={
                "turn_number": runtime.turn_number,
                "slash_used": runtime.slash_used,
                "wine_buff_owner_id": runtime.wine_buff_owner_id,
                "wine_buff_used_this_play_phase": (
                    runtime.wine_buff_used_this_play_phase
                ),
                "pending_trick": (
                    None
                    if runtime.pending_trick is None
                    else {
                        "user_id": runtime.pending_trick.user_id,
                        "target_id": runtime.pending_trick.target_id,
                        "trick_instance_id": (
                            runtime.pending_trick.trick_instance_id
                        ),
                        "trick_key": runtime.pending_trick.trick_key,
                    }
                ),
                "trick_effect_active": runtime.trick_effect_active,
                "trick_consecutive_passes": (
                    runtime.trick_consecutive_passes
                ),
                "trick_response_index": runtime.trick_response_index,
                "pending_dying_id": runtime.pending_dying_id,
                "rescue_index": runtime.rescue_index,
            },
        )

    def legal_actions(self) -> tuple[LegalAction, ...]:
        return enumerate_legal_actions(
            self.state, self._context(), self.registry
        )

    def step(
        self,
        controller: (
            BatchActionIdController
            | BatchReferenceController
            | ScriptedBatchController
            | None
        ) = None,
    ) -> LegalAction:
        if self.is_finished:
            raise ProductionBatchFinishedError(
                "胜利已经成立，对局不得继续执行动作"
            )
        selected = controller or BatchReferenceController()
        context = self._context()
        legal = enumerate_legal_actions(self.state, context, self.registry)
        chosen = selected.choose(legal, context)
        validated = validate_action(self.state, context, chosen, self.registry)
        self._state = apply_action(
            self.state, context, validated, self.registry
        )
        self._step_count += 1
        self._state.assert_card_conservation()
        return validated

    def run(
        self,
        controller: (
            BatchActionIdController
            | BatchReferenceController
            | ScriptedBatchController
            | None
        ) = None,
        *,
        max_steps: int = 500,
    ) -> ProductionBatchResult:
        if (
            isinstance(max_steps, bool)
            or not isinstance(max_steps, int)
            or max_steps < 1
        ):
            raise ValueError("安全动作上限必须是正整数")
        selected = controller or BatchReferenceController()
        executed = 0
        while not self.is_finished and executed < max_steps:
            self.step(selected)
            executed += 1
        if not self.is_finished:
            raise ProductionBatchSafetyLimitError(
                f"生产批处理会话在{max_steps}个动作后仍未结束；"
                "禁止静默判胜或近似收尾"
            )
        assert self.winner_id is not None
        return ProductionBatchResult(
            winner_id=self.winner_id,
            step_count=self.step_count,
            turn_count=self._runtime.turn_number,
            final_state=self.state,
            events=self.events,
            rng_calls=self.rng_calls,
            phase_history=self.phase_history,
        )

    @property
    def execution_snapshot(self) -> dict[str, object]:
        """返回可序列化的稳定执行快照，供严格重执行逐步比较。"""

        snapshot = {
            "schema": "production-basic-batch-execution-v1",
            "mode": PRODUCTION_BASIC_CARDS_MODE,
            "runtime": self._runtime.audit_value(),
            "first_player_id": self.first_player_id,
            "current_actor_id": (
                None if self.is_finished else self.current_actor_id
            ),
            "step_count": self.step_count,
            "event_count": len(self.events),
            "events": [event.to_replay_dict() for event in self.events],
            "rng_call_count": len(self.rng_calls),
            "rng_calls": [call.to_dict() for call in self.rng_calls],
            "phase_history": [
                {
                    "turn_number": entry.turn_number,
                    "turn_player_id": entry.turn_player_id,
                    "phase": entry.phase.value,
                }
                for entry in self.phase_history
            ],
            "game_state": canonical_state_snapshot(self.state),
        }
        normalized = json.loads(canonical_json(snapshot))
        assert isinstance(normalized, dict)
        return normalized

    @property
    def execution_hash(self) -> str:
        return sha256_value(self.execution_snapshot)

    def _enumerate_for_adapter(
        self, state: GameState, context: ActionContext
    ) -> tuple[LegalAction, ...]:
        if (
            context.mode != PRODUCTION_BASIC_CARDS_MODE
            or context.phase != self.phase.value
        ):
            raise ProductionBatchError(
                "行动上下文与生产批处理会话当前阶段不一致"
            )
        actor = context.actor_id
        actions: list[LegalAction] = []
        if self.phase is ProductionPhase.PLAY:
            for adapter in self._formal_registry.adapters.values():
                actions.extend(adapter.enumerate_legal_actions(state, context))
            actions.append(
                LegalAction(
                    action_type=ActionType.PASS,
                    actor_id=actor,
                    payload={"operation": "end_play_phase"},
                )
            )
        elif self.phase is ProductionPhase.END:
            actions.append(
                LegalAction(
                    action_type=ActionType.PASS,
                    actor_id=actor,
                    payload={"operation": "end_turn"},
                )
            )
        elif self.phase is ProductionPhase.SLASH_RESPONSE:
            for adapter in self._formal_registry.adapters.values():
                actions.extend(adapter.enumerate_legal_actions(state, context))
            actions.append(
                LegalAction(
                    action_type=ActionType.PASS,
                    actor_id=actor,
                    payload={"operation": "pass_slash_response"},
                )
            )
        elif self.phase is ProductionPhase.TRICK_RESPONSE:
            for adapter in self._formal_registry.adapters.values():
                actions.extend(adapter.enumerate_legal_actions(state, context))
            actions.append(
                LegalAction(
                    action_type=ActionType.PASS,
                    actor_id=actor,
                    payload={"operation": "pass_trick_response"},
                )
            )
        elif self.phase is ProductionPhase.DYING_RESCUE:
            for adapter in self._formal_registry.adapters.values():
                actions.extend(adapter.enumerate_legal_actions(state, context))
            actions.append(
                LegalAction(
                    action_type=ActionType.PASS,
                    actor_id=actor,
                    payload={"operation": "pass_rescue"},
                )
            )
        else:
            raise ProductionBatchError(
                f"阶段{self.phase.value!r}不能枚举合法动作"
            )
        return tuple(actions)

    def _apply_for_adapter(
        self, state: GameState, context: ActionContext, action: LegalAction
    ) -> GameState:
        if (
            context.mode != PRODUCTION_BASIC_CARDS_MODE
            or context.phase != self.phase.value
        ):
            raise ProductionBatchError(
                "行动上下文与生产批处理会话当前阶段不一致"
            )
        operation = str(action.payload.get("operation", ""))

        if self.phase is ProductionPhase.PLAY:
            if operation == "use_slash":
                adapter = self._adapter_for_action(state, action)
                return adapter.apply_action(state, context, action)
            if operation == "heal_self":
                return self._formal_registry.adapter_for(
                    "sgs_basic_tao"
                ).apply_action(state, context, action)
            if operation == "use_wine_buff":
                return self._formal_registry.adapter_for(
                    "sgs_basic_jiu"
                ).apply_action(state, context, action)
            if operation == "use_wuzhong":
                return self._formal_registry.adapter_for(
                    "sgs_trick_wuzhongshengyou"
                ).apply_action(state, context, action)
            if action.action_type is ActionType.PASS and operation == (
                "end_play_phase"
            ):
                return self._apply_end_play_phase(state, context, action)
            raise InvalidActionError(
                "出牌阶段不支持当前动作；动作未经过合法枚举或已过期"
            )

        if self.phase is ProductionPhase.END:
            if action.action_type is ActionType.PASS and operation == "end_turn":
                return self._apply_end_turn(state, context, action)
            raise InvalidActionError("结束阶段只能结束回合")

        if self.phase is ProductionPhase.SLASH_RESPONSE:
            if operation == "play_dodge":
                return self._formal_registry.adapter_for(
                    "sgs_basic_shan"
                ).apply_action(state, context, action)
            if action.action_type is ActionType.PASS and operation == (
                "pass_slash_response"
            ):
                return self.apply_slash_damage(state, context, action)
            raise InvalidActionError("【杀】响应阶段不支持当前动作")

        if self.phase is ProductionPhase.TRICK_RESPONSE:
            if operation == "use_wuxie":
                return self._formal_registry.adapter_for(
                    "sgs_trick_wuxiekeji"
                ).apply_action(state, context, action)
            if action.action_type is ActionType.PASS and operation == (
                "pass_trick_response"
            ):
                return self.apply_pass_trick_response(state, context, action)
            raise InvalidActionError("锦囊响应阶段不支持当前动作")

        if self.phase is ProductionPhase.DYING_RESCUE:
            if operation == "rescue_with_peach":
                return self._formal_registry.adapter_for(
                    "sgs_basic_tao"
                ).apply_action(state, context, action)
            if operation == "rescue_with_wine":
                return self._formal_registry.adapter_for(
                    "sgs_basic_jiu"
                ).apply_action(state, context, action)
            if action.action_type is ActionType.PASS and operation == (
                "pass_rescue"
            ):
                return self.apply_pass_rescue(state, context, action)
            raise InvalidActionError("濒死救援阶段不支持当前动作")

        raise ProductionBatchError(
            f"阶段{self.phase.value!r}不能应用动作"
        )

    def _adapter_for_action(
        self, state: GameState, action: LegalAction
    ) -> SlashAdapter:
        if action.card_instance_id is None:
            raise InvalidActionError("卡牌动作必须指定实体牌")
        card_key = state.cards_by_id[action.card_instance_id].card_key
        adapter = self._formal_registry.adapter_for(card_key)
        if not isinstance(adapter, SlashAdapter):
            raise InvalidActionError(
                f"实体牌{action.card_instance_id!r}不是本批次【杀】"
            )
        return adapter

    def _build_window(self, runtime: _BatchRuntime) -> ResponseWindow:
        if (
            runtime.response_window_id is None
            or not runtime.response_window_order
        ):
            raise ProductionBatchError("当前阶段没有已建立的响应窗口")
        source = None
        if runtime.response_window_source_sequence is not None:
            for event in self._events.snapshot():
                if event.sequence == runtime.response_window_source_sequence:
                    source = event
                    break
            if source is None:
                raise ProductionBatchError(
                    "响应窗口的来源事件不存在，状态或回放异常"
                )
        return ResponseWindow(
            responder_order=runtime.response_window_order,
            window_id=runtime.response_window_id,
            source_event=source,
            close_on_first_response=True,
            allowed_event_types=(EventType.CARD_USED,),
        )

    def _commit_runtime(
        self, previous: _BatchRuntime, next_runtime: _BatchRuntime
    ) -> None:
        previous_entry = (
            previous.turn_number,
            previous.current_player_id,
            previous.phase,
        )
        next_entry = (
            next_runtime.turn_number,
            next_runtime.current_player_id,
            next_runtime.phase,
        )
        self._runtime = next_runtime
        if next_entry != previous_entry:
            self._phase_history.append(
                BatchPhaseEntry(
                    next_runtime.turn_number,
                    next_runtime.current_player_id,
                    next_runtime.phase,
                )
            )

    def _return_to_play(self, runtime: _BatchRuntime) -> _BatchRuntime:
        return replace(
            runtime,
            phase=ProductionPhase.PLAY,
            pending_slash=None,
            pending_trick=None,
            trick_effect_active=False,
            trick_consecutive_passes=0,
            trick_response_order=(),
            trick_response_index=0,
            trick_decision_count=0,
            pending_dying_id=None,
            rescue_order=(),
            rescue_index=0,
            rescue_decision_count=0,
            response_window_id=None,
            response_window_order=(),
            response_window_source_sequence=None,
        )

    # ------------------------------------------------------------------
    # 卡牌与阶段结算（全部经过适配器路由，绝不直接修改状态）
    # ------------------------------------------------------------------

    def apply_slash_use(
        self,
        state: GameState,
        context: ActionContext,
        action: LegalAction,
        adapter: SlashAdapter,
    ) -> GameState:
        runtime = self._runtime
        if runtime.phase is not ProductionPhase.PLAY:
            raise InvalidActionError("【杀】只能在出牌阶段使用")
        if runtime.slash_used:
            raise InvalidActionError("本出牌阶段已经使用过【杀】，受次数限制")
        if action.card_instance_id is None or len(action.target_ids) != 1:
            raise InvalidActionError("【杀】必须指定一张实体牌和恰好一名目标")
        card = state.cards_by_id[action.card_instance_id]
        if card.card_key != adapter.card_key:
            raise InvalidActionError("【杀】动作的实体牌与适配器卡牌键不一致")
        if str(action.payload.get("card_key", "")) != adapter.card_key:
            raise InvalidActionError("【杀】动作负载与适配器卡牌键不一致")
        target = action.target_ids[0]
        if target == context.actor_id or not is_valid_slash_target(
            state, context.actor_id, target
        ):
            raise InvalidActionError("【杀】目标不在攻击范围内或目标非法")
        if state.location_of(action.card_instance_id) != ZoneRef.hand(
            context.actor_id
        ):
            raise InvalidActionError("只能使用行动角色真实手牌中的实体牌")

        next_state, move_event = self._move_to_processing(
            state, action.card_instance_id, context.actor_id, "slash_use"
        )
        boosted = runtime.wine_buff_owner_id == context.actor_id
        used_event = GameEvent(
            event_type=EventType.CARD_USED,
            card_instance_id=action.card_instance_id,
            card_key=adapter.card_key,
            card_user=context.actor_id,
            target_ids=(target,),
            payload={
                "damage_nature": adapter.damage_nature,
                "boosted": boosted,
            },
        )
        queued = self._events.extend((used_event, move_event))
        used_sequence = queued[0].sequence
        assert used_sequence is not None
        next_runtime = replace(
            runtime,
            phase=ProductionPhase.SLASH_RESPONSE,
            slash_used=True,
            wine_buff_owner_id=None,
            pending_slash=_PendingSlash(
                context.actor_id, target, action.card_instance_id, boosted
            ),
            response_window_id=(
                f"slash:{runtime.turn_number}:{action.card_instance_id}"
            ),
            response_window_order=(target,),
            response_window_source_sequence=used_sequence,
        )
        self._commit_runtime(runtime, next_runtime)
        return next_state

    def apply_dodge(
        self,
        state: GameState,
        context: ActionContext,
        action: LegalAction,
        adapter: object,
    ) -> GameState:
        del adapter
        runtime = self._runtime
        if runtime.phase is not ProductionPhase.SLASH_RESPONSE:
            raise InvalidActionError("【闪】只能响应【杀】响应窗口")
        if runtime.pending_slash is None:
            raise InvalidActionError("当前没有待响应的【杀】")
        if context.actor_id != runtime.pending_slash.target_id:
            raise InvalidActionError("只有【杀】目标可以响应")
        if action.card_instance_id is None:
            raise InvalidActionError("响应【杀】必须使用真实实体【闪】")
        card = state.cards_by_id[action.card_instance_id]
        if card.card_key != "sgs_basic_shan":
            raise InvalidActionError("响应【杀】的实体牌必须是【闪】")
        if state.location_of(action.card_instance_id) != ZoneRef.hand(
            context.actor_id
        ):
            raise InvalidActionError("只能使用行动角色真实手牌中的实体牌")

        window = self._build_window(runtime)
        dodge_event = GameEvent(
            event_type=EventType.CARD_USED,
            card_instance_id=action.card_instance_id,
            card_key="sgs_basic_shan",
            card_user=context.actor_id,
            payload={"response_to": runtime.pending_slash.slash_instance_id},
        )
        record = window.respond(context.actor_id, dodge_event)
        assert record.response_event is not None
        bound_event = record.response_event
        next_state, dodge_move_events = self._consume_immediately(
            state,
            action.card_instance_id,
            context.actor_id,
            "dodge_response_complete",
        )
        slash_id = runtime.pending_slash.slash_instance_id
        next_state, slash_finish = self._finish_processing(
            next_state, slash_id, "slash_cancelled_by_dodge"
        )
        self._events.extend(
            (
                bound_event,
                *dodge_move_events,
                GameEvent(
                    event_type=EventType.CARD_EFFECT_CANCELLED,
                    card_instance_id=slash_id,
                    card_key=_card_key(state, slash_id),
                    target_ids=(context.actor_id,),
                    payload={"reason": "dodge"},
                ),
                slash_finish,
            )
        )
        self._commit_runtime(runtime, self._return_to_play(runtime))
        return next_state

    def apply_slash_damage(
        self,
        state: GameState,
        context: ActionContext,
        action: LegalAction,
    ) -> GameState:
        del action
        runtime = self._runtime
        if runtime.phase is not ProductionPhase.SLASH_RESPONSE:
            raise InvalidActionError("【杀】伤害结算只能在响应窗口进行")
        if runtime.pending_slash is None:
            raise InvalidActionError("当前没有待结算的【杀】")
        if context.actor_id != runtime.pending_slash.target_id:
            raise InvalidActionError("只有【杀】目标可以放弃响应")
        window = self._build_window(runtime)
        window.pass_response(context.actor_id)

        pending = runtime.pending_slash
        slash = state.cards_by_id[pending.slash_instance_id]
        adapter = self._formal_registry.adapter_for(slash.card_key)
        if not isinstance(adapter, SlashAdapter):
            raise InvalidActionError("【杀】伤害结算必须使用【杀】生产适配器")
        amount = 2 if pending.boosted else 1
        victim = state.players_by_id[pending.target_id]
        next_state = _replace_player(
            state, pending.target_id, hp=victim.hp - amount
        )
        damage_event = DamageEvent(
            target_id=pending.target_id,
            amount=amount,
            damage_type=adapter.damage_nature,
            card_instance_id=pending.slash_instance_id,
            card_key=slash.card_key,
            card_user=pending.attacker_id,
            damage_source=pending.attacker_id,
            kill_credit=pending.attacker_id,
        )
        if next_state.players_by_id[pending.target_id].hp <= 0:
            dying_event = GameEvent(
                event_type=EventType.DYING,
                damage_source=pending.attacker_id,
                kill_credit=pending.attacker_id,
                target_ids=(pending.target_id,),
            )
            self._events.extend((damage_event, dying_event))
            dying_sequence = self._events.snapshot()[-1].sequence
            assert dying_sequence is not None
            rescue_order = (
                runtime.current_player_id,
                self.opponent_of(runtime.current_player_id),
            )
            next_runtime = replace(
                runtime,
                phase=ProductionPhase.DYING_RESCUE,
                pending_dying_id=pending.target_id,
                rescue_order=rescue_order,
                rescue_index=0,
                rescue_decision_count=0,
                response_window_id=(
                    f"dying:{runtime.turn_number}:{pending.target_id}"
                    ":seat0:dec0"
                ),
                response_window_order=(rescue_order[0],),
                response_window_source_sequence=dying_sequence,
            )
        else:
            next_state, finish_event = self._finish_processing(
                next_state,
                pending.slash_instance_id,
                "slash_damage_resolved",
            )
            self._events.extend((damage_event, finish_event))
            next_runtime = self._return_to_play(runtime)
        self._commit_runtime(runtime, next_runtime)
        return next_state

    # ------------------------------------------------------------------
    # 普通锦囊结算（【无中生有】与【无懈可击】）
    # ------------------------------------------------------------------

    def _trick_window_id(
        self, runtime: _BatchRuntime, decision_index: int
    ) -> str:
        if runtime.pending_trick is None:
            raise ProductionBatchError("锦囊响应窗口缺少待响应的锦囊")
        return (
            f"trick:{runtime.turn_number}:"
            f"{runtime.pending_trick.trick_instance_id}:dec{decision_index}"
        )

    def apply_wuzhong_use(
        self,
        state: GameState,
        context: ActionContext,
        action: LegalAction,
        adapter: WuzhongshengyouAdapter,
    ) -> GameState:
        runtime = self._runtime
        if runtime.phase is not ProductionPhase.PLAY:
            raise InvalidActionError("【无中生有】只能在出牌阶段使用")
        if context.actor_id != runtime.current_player_id:
            raise InvalidActionError("只有当前回合角色可以使用【无中生有】")
        if action.card_instance_id is None:
            raise InvalidActionError("使用【无中生有】必须指定实体牌")
        card = state.cards_by_id[action.card_instance_id]
        if card.card_key != adapter.card_key:
            raise InvalidActionError(
                "【无中生有】动作的实体牌与适配器卡牌键不一致"
            )
        if action.target_ids != (context.actor_id,):
            raise InvalidActionError("【无中生有】只能以自己为目标")
        if state.location_of(action.card_instance_id) != ZoneRef.hand(
            context.actor_id
        ):
            raise InvalidActionError("只能使用行动角色真实手牌中的实体牌")

        next_state, move_event = self._move_to_processing(
            state, action.card_instance_id, context.actor_id, "wuzhong_use"
        )
        used_event = GameEvent(
            event_type=EventType.CARD_USED,
            card_instance_id=action.card_instance_id,
            card_key=adapter.card_key,
            card_user=context.actor_id,
            target_ids=(context.actor_id,),
            payload={"purpose": "draw_2", "card_name": adapter.card_name},
        )
        queued = self._events.extend((used_event, move_event))
        used_sequence = queued[0].sequence
        assert used_sequence is not None
        order = (
            runtime.current_player_id,
            self.opponent_of(runtime.current_player_id),
        )
        next_runtime = replace(
            runtime,
            phase=ProductionPhase.TRICK_RESPONSE,
            pending_trick=_PendingTrick(
                context.actor_id,
                context.actor_id,
                action.card_instance_id,
                adapter.card_key,
            ),
            trick_effect_active=True,
            trick_consecutive_passes=0,
            trick_response_order=order,
            trick_response_index=0,
            trick_decision_count=0,
            response_window_id=(
                f"trick:{runtime.turn_number}:"
                f"{action.card_instance_id}:dec0"
            ),
            response_window_order=(order[0],),
            response_window_source_sequence=used_sequence,
        )
        self._commit_runtime(runtime, next_runtime)
        return next_state

    def apply_wuxie(
        self,
        state: GameState,
        context: ActionContext,
        action: LegalAction,
        adapter: WuxiekejiAdapter,
    ) -> GameState:
        del adapter
        runtime = self._runtime
        if runtime.phase is not ProductionPhase.TRICK_RESPONSE:
            raise InvalidActionError("【无懈可击】只能在合法锦囊响应窗口使用")
        trick = runtime.pending_trick
        if trick is None:
            raise InvalidActionError("当前没有待响应的锦囊")
        if not runtime.trick_response_order:
            raise InvalidActionError("锦囊响应顺序为空")
        if runtime.trick_response_index >= len(runtime.trick_response_order):
            raise InvalidActionError("锦囊响应顺序已经耗尽")
        if (
            context.actor_id
            != runtime.trick_response_order[runtime.trick_response_index]
        ):
            raise InvalidActionError("当前不是该角色的锦囊响应时机")
        if action.card_instance_id is None:
            raise InvalidActionError("响应锦囊必须使用真实实体【无懈可击】")
        card = state.cards_by_id[action.card_instance_id]
        if card.card_key != "sgs_trick_wuxiekeji":
            raise InvalidActionError("响应锦囊的实体牌必须是【无懈可击】")
        if action.target_ids != (trick.target_id,):
            raise InvalidActionError(
                "【无懈可击】只能以当前锦囊效果对应的角色为目标"
            )
        if state.location_of(action.card_instance_id) != ZoneRef.hand(
            context.actor_id
        ):
            raise InvalidActionError("只能使用行动角色真实手牌中的实体牌")

        window = self._build_window(runtime)
        wuxie_event = GameEvent(
            event_type=EventType.CARD_USED,
            card_instance_id=action.card_instance_id,
            card_key="sgs_trick_wuxiekeji",
            card_user=context.actor_id,
            target_ids=(trick.target_id,),
            payload={
                "response_to": trick.trick_instance_id,
                "response_action": "use",
                "purpose": "nullify_trick_effect",
                "creates_card_used_event": True,
                "creates_card_played_event": False,
                "counts_for_use_or_play_total": True,
                "physical_or_virtual": "physical",
                "response_provider": context.actor_id,
            },
        )
        record = window.respond(context.actor_id, wuxie_event)
        assert record.response_event is not None
        next_state, move_events = self._consume_immediately(
            state, action.card_instance_id, context.actor_id, "wuxie_response"
        )
        self._events.extend((record.response_event, *move_events))
        next_index = (runtime.trick_response_index + 1) % len(
            runtime.trick_response_order
        )
        next_runtime = replace(
            runtime,
            trick_effect_active=not runtime.trick_effect_active,
            trick_consecutive_passes=0,
            trick_response_index=next_index,
            trick_decision_count=runtime.trick_decision_count + 1,
            response_window_id=self._trick_window_id(
                runtime, runtime.trick_decision_count + 1
            ),
            response_window_order=(runtime.trick_response_order[next_index],),
        )
        self._commit_runtime(runtime, next_runtime)
        return next_state

    def apply_pass_trick_response(
        self,
        state: GameState,
        context: ActionContext,
        action: LegalAction,
    ) -> GameState:
        del action
        runtime = self._runtime
        if runtime.phase is not ProductionPhase.TRICK_RESPONSE:
            raise InvalidActionError("放弃响应只能在锦囊响应窗口进行")
        trick = runtime.pending_trick
        if trick is None or not runtime.trick_response_order:
            raise InvalidActionError("当前没有进行中的锦囊响应")
        if runtime.trick_response_index >= len(runtime.trick_response_order):
            raise InvalidActionError("锦囊响应顺序已经耗尽")
        if (
            context.actor_id
            != runtime.trick_response_order[runtime.trick_response_index]
        ):
            raise InvalidActionError("当前不是该角色的锦囊响应时机")
        window = self._build_window(runtime)
        window.pass_response(context.actor_id)

        next_passes = runtime.trick_consecutive_passes + 1
        if next_passes >= len(runtime.trick_response_order):
            # 连续一整轮无人响应：窗口关闭，按最终生效状态结算。
            if runtime.trick_effect_active:
                next_state, draw_events = self._draw_cards(
                    state, trick.target_id, 2
                )
                self._events.extend(draw_events)
                next_state, finish_event = self._finish_processing(
                    next_state,
                    trick.trick_instance_id,
                    "wuzhong_effect_resolved",
                )
                self._events.extend((finish_event,))
            else:
                cancelled_event = GameEvent(
                    event_type=EventType.CARD_EFFECT_CANCELLED,
                    card_instance_id=trick.trick_instance_id,
                    card_key=trick.trick_key,
                    card_user=trick.user_id,
                    target_ids=(trick.target_id,),
                    payload={"reason": "nullified_by_wuxie"},
                )
                next_state, finish_event = self._finish_processing(
                    state,
                    trick.trick_instance_id,
                    "wuzhong_nullified",
                )
                self._events.extend((cancelled_event, finish_event))
            next_runtime = self._return_to_play(runtime)
        else:
            next_state = state
            next_index = (runtime.trick_response_index + 1) % len(
                runtime.trick_response_order
            )
            next_runtime = replace(
                runtime,
                trick_consecutive_passes=next_passes,
                trick_response_index=next_index,
                trick_decision_count=runtime.trick_decision_count + 1,
                response_window_id=self._trick_window_id(
                    runtime, runtime.trick_decision_count + 1
                ),
                response_window_order=(runtime.trick_response_order[next_index],),
            )
        self._commit_runtime(runtime, next_runtime)
        return next_state

    def apply_peach_self_heal(
        self,
        state: GameState,
        context: ActionContext,
        action: LegalAction,
        adapter: object,
    ) -> GameState:
        del adapter
        runtime = self._runtime
        if runtime.phase is not ProductionPhase.PLAY:
            raise InvalidActionError("【桃】普通回复只能在出牌阶段使用")
        player = state.players_by_id[context.actor_id]
        if player.hp >= player.max_hp:
            raise InvalidActionError("满体力时不能通过普通自用【桃】获得回复")
        if action.card_instance_id is None:
            raise InvalidActionError("使用【桃】必须指定实体牌")
        card = state.cards_by_id[action.card_instance_id]
        if card.card_key != "sgs_basic_tao":
            raise InvalidActionError("回复动作的实体牌必须是【桃】")
        if action.target_ids != (context.actor_id,):
            raise InvalidActionError("出牌阶段普通自用【桃】只能以自己为目标")
        if state.location_of(action.card_instance_id) != ZoneRef.hand(
            context.actor_id
        ):
            raise InvalidActionError("只能使用行动角色真实手牌中的实体牌")

        next_state, move_events = self._consume_immediately(
            state, action.card_instance_id, context.actor_id, "peach_resolve"
        )
        healed = next_state.players_by_id[context.actor_id]
        next_state = _replace_player(
            next_state,
            context.actor_id,
            hp=min(healed.max_hp, healed.hp + 1),
        )
        self._events.extend(
            (
                GameEvent(
                    event_type=EventType.CARD_USED,
                    card_instance_id=action.card_instance_id,
                    card_key="sgs_basic_tao",
                    card_user=context.actor_id,
                    target_ids=(context.actor_id,),
                    payload={"purpose": "heal_self"},
                ),
                *move_events,
            )
        )
        self._commit_runtime(runtime, runtime)
        return next_state

    def apply_wine_buff(
        self,
        state: GameState,
        context: ActionContext,
        action: LegalAction,
        adapter: object,
    ) -> GameState:
        del adapter
        runtime = self._runtime
        if runtime.phase is not ProductionPhase.PLAY:
            raise InvalidActionError("【酒】强化用途只能在出牌阶段使用")
        if runtime.wine_buff_used_this_play_phase:
            raise InvalidActionError("出牌阶段【酒】强化用途每出牌阶段限一次")
        if action.card_instance_id is None:
            raise InvalidActionError("使用【酒】必须指定实体牌")
        card = state.cards_by_id[action.card_instance_id]
        if card.card_key != "sgs_basic_jiu":
            raise InvalidActionError("强化动作的实体牌必须是【酒】")
        if action.target_ids != (context.actor_id,):
            raise InvalidActionError("出牌阶段【酒】只能以自己为目标")
        if state.location_of(action.card_instance_id) != ZoneRef.hand(
            context.actor_id
        ):
            raise InvalidActionError("只能使用行动角色真实手牌中的实体牌")

        next_state, move_events = self._consume_immediately(
            state, action.card_instance_id, context.actor_id, "wine_buff_resolve"
        )
        self._events.extend(
            (
                GameEvent(
                    event_type=EventType.CARD_USED,
                    card_instance_id=action.card_instance_id,
                    card_key="sgs_basic_jiu",
                    card_user=context.actor_id,
                    target_ids=(context.actor_id,),
                    payload={"purpose": "play_phase_slash_buff"},
                ),
                *move_events,
            )
        )
        next_runtime = replace(
            runtime,
            wine_buff_owner_id=context.actor_id,
            wine_buff_used_this_play_phase=True,
        )
        self._commit_runtime(runtime, next_runtime)
        return next_state

    def _rescue_window_id(
        self, runtime: _BatchRuntime, seat: int, decision_count: int
    ) -> str:
        assert runtime.pending_dying_id is not None
        return (
            f"dying:{runtime.turn_number}:{runtime.pending_dying_id}"
            f":seat{seat}:dec{decision_count}"
        )

    def apply_peach_rescue(
        self,
        state: GameState,
        context: ActionContext,
        action: LegalAction,
        adapter: object,
    ) -> GameState:
        del adapter
        runtime = self._runtime
        if runtime.phase is not ProductionPhase.DYING_RESCUE:
            raise InvalidActionError("【桃】救援只能在濒死救援窗口使用")
        dying_id = runtime.pending_dying_id
        if dying_id is None or not runtime.rescue_order:
            raise InvalidActionError("当前没有进行中的濒死救援")
        if runtime.rescue_index >= len(runtime.rescue_order):
            raise InvalidActionError("濒死救援顺序已经耗尽")
        if context.actor_id != runtime.rescue_order[runtime.rescue_index]:
            raise InvalidActionError("当前不是该角色的救援时机")
        if action.card_instance_id is None:
            raise InvalidActionError("救援必须使用真实实体【桃】")
        card = state.cards_by_id[action.card_instance_id]
        if card.card_key != "sgs_basic_tao":
            raise InvalidActionError("救援动作的实体牌必须是【桃】")
        if action.target_ids != (dying_id,):
            raise InvalidActionError("救援【桃】只能以濒死角色为目标")
        if state.players_by_id[dying_id].hp >= 1:
            raise InvalidActionError("目标已经脱离濒死，无需继续救援")
        if state.location_of(action.card_instance_id) != ZoneRef.hand(
            context.actor_id
        ):
            raise InvalidActionError("只能使用救援角色真实手牌中的实体牌")

        window = self._build_window(runtime)
        rescue_event = GameEvent(
            event_type=EventType.CARD_USED,
            card_instance_id=action.card_instance_id,
            card_key="sgs_basic_tao",
            card_user=context.actor_id,
            target_ids=(dying_id,),
            payload={"purpose": "dying_rescue"},
        )
        record = window.respond(context.actor_id, rescue_event)
        assert record.response_event is not None
        next_state, move_events = self._consume_immediately(
            state, action.card_instance_id, context.actor_id, "dying_rescue"
        )
        dying = next_state.players_by_id[dying_id]
        next_state = _replace_player(
            next_state, dying_id, hp=min(dying.max_hp, dying.hp + 1)
        )
        pending_events: list[GameEvent] = [
            record.response_event,
            *move_events,
        ]
        if next_state.players_by_id[dying_id].hp >= 1:
            assert runtime.pending_slash is not None
            next_state, finish_event = self._finish_processing(
                next_state,
                runtime.pending_slash.slash_instance_id,
                "slash_damage_resolved_after_rescue",
            )
            pending_events.append(finish_event)
            self._events.extend(pending_events)
            next_runtime = self._return_to_play(runtime)
        else:
            self._events.extend(pending_events)
            decision_count = runtime.rescue_decision_count + 1
            next_runtime = replace(
                runtime,
                rescue_decision_count=decision_count,
                response_window_id=self._rescue_window_id(
                    runtime, runtime.rescue_index, decision_count
                ),
                response_window_order=(context.actor_id,),
            )
        self._commit_runtime(runtime, next_runtime)
        return next_state

    def apply_wine_self_rescue(
        self,
        state: GameState,
        context: ActionContext,
        action: LegalAction,
        adapter: object,
    ) -> GameState:
        del adapter
        runtime = self._runtime
        if runtime.phase is not ProductionPhase.DYING_RESCUE:
            raise InvalidActionError("【酒】自救只能在濒死救援窗口使用")
        dying_id = runtime.pending_dying_id
        if dying_id is None or not runtime.rescue_order:
            raise InvalidActionError("当前没有进行中的濒死救援")
        if runtime.rescue_index >= len(runtime.rescue_order):
            raise InvalidActionError("濒死救援顺序已经耗尽")
        if context.actor_id != runtime.rescue_order[runtime.rescue_index]:
            raise InvalidActionError("当前不是该角色的救援时机")
        if context.actor_id != dying_id:
            raise InvalidActionError("濒死自救【酒】只能对濒死的自己使用")
        if action.card_instance_id is None:
            raise InvalidActionError("自救必须使用真实实体【酒】")
        card = state.cards_by_id[action.card_instance_id]
        if card.card_key != "sgs_basic_jiu":
            raise InvalidActionError("自救动作的实体牌必须是【酒】")
        if action.target_ids != (context.actor_id,):
            raise InvalidActionError("濒死自救【酒】只能以自己为目标")
        if state.players_by_id[dying_id].hp >= 1:
            raise InvalidActionError("角色已经脱离濒死，无需继续自救")
        if state.location_of(action.card_instance_id) != ZoneRef.hand(
            context.actor_id
        ):
            raise InvalidActionError("只能使用自救角色真实手牌中的实体牌")

        window = self._build_window(runtime)
        rescue_event = GameEvent(
            event_type=EventType.CARD_USED,
            card_instance_id=action.card_instance_id,
            card_key="sgs_basic_jiu",
            card_user=context.actor_id,
            target_ids=(context.actor_id,),
            payload={"purpose": "dying_self_rescue"},
        )
        record = window.respond(context.actor_id, rescue_event)
        assert record.response_event is not None
        next_state, move_events = self._consume_immediately(
            state, action.card_instance_id, context.actor_id, "dying_self_rescue"
        )
        dying = next_state.players_by_id[dying_id]
        next_state = _replace_player(
            next_state, dying_id, hp=min(dying.max_hp, dying.hp + 1)
        )
        pending_events: list[GameEvent] = [
            record.response_event,
            *move_events,
        ]
        if next_state.players_by_id[dying_id].hp >= 1:
            assert runtime.pending_slash is not None
            next_state, finish_event = self._finish_processing(
                next_state,
                runtime.pending_slash.slash_instance_id,
                "slash_damage_resolved_after_rescue",
            )
            pending_events.append(finish_event)
            self._events.extend(pending_events)
            next_runtime = self._return_to_play(runtime)
        else:
            self._events.extend(pending_events)
            decision_count = runtime.rescue_decision_count + 1
            next_runtime = replace(
                runtime,
                rescue_decision_count=decision_count,
                response_window_id=self._rescue_window_id(
                    runtime, runtime.rescue_index, decision_count
                ),
                response_window_order=(context.actor_id,),
            )
        self._commit_runtime(runtime, next_runtime)
        return next_state

    def apply_pass_rescue(
        self,
        state: GameState,
        context: ActionContext,
        action: LegalAction,
    ) -> GameState:
        del action
        runtime = self._runtime
        if runtime.phase is not ProductionPhase.DYING_RESCUE:
            raise InvalidActionError("放弃救援只能在濒死救援窗口进行")
        dying_id = runtime.pending_dying_id
        if dying_id is None or not runtime.rescue_order:
            raise InvalidActionError("当前没有进行中的濒死救援")
        if runtime.rescue_index >= len(runtime.rescue_order):
            raise InvalidActionError("濒死救援顺序已经耗尽")
        if context.actor_id != runtime.rescue_order[runtime.rescue_index]:
            raise InvalidActionError("当前不是该角色的救援时机")
        window = self._build_window(runtime)
        window.pass_response(context.actor_id)

        next_index = runtime.rescue_index + 1
        if next_index < len(runtime.rescue_order):
            next_runtime = replace(
                runtime,
                rescue_index=next_index,
                rescue_decision_count=0,
                response_window_id=self._rescue_window_id(
                    runtime, next_index, 0
                ),
                response_window_order=(runtime.rescue_order[next_index],),
            )
            self._commit_runtime(runtime, next_runtime)
            return state
        dying = state.players_by_id[dying_id]
        if dying.hp >= 1:
            assert runtime.pending_slash is not None
            next_state, finish_event = self._finish_processing(
                state,
                runtime.pending_slash.slash_instance_id,
                "slash_damage_resolved_after_rescue",
            )
            self._events.extend((finish_event,))
            next_runtime = self._return_to_play(runtime)
            self._commit_runtime(runtime, next_runtime)
            return next_state
        assert runtime.pending_slash is not None
        next_state, finish_event = self._finish_processing(
            state,
            runtime.pending_slash.slash_instance_id,
            "slash_damage_resolved_with_death",
        )
        next_state = _replace_player(next_state, dying_id, alive=False)
        winner = self.opponent_of(dying_id)
        self._events.extend(
            (
                finish_event,
                GameEvent(
                    event_type=EventType.DEATH,
                    damage_source=runtime.pending_slash.attacker_id,
                    kill_credit=runtime.pending_slash.attacker_id,
                    target_ids=(dying_id,),
                ),
                GameEvent(
                    event_type=EventType.VICTORY,
                    target_ids=(winner,),
                ),
            )
        )
        next_runtime = replace(
            runtime,
            phase=ProductionPhase.FINISHED,
            winner_id=winner,
            pending_slash=None,
            pending_dying_id=None,
            rescue_order=(),
            rescue_index=0,
            rescue_decision_count=0,
            response_window_id=None,
            response_window_order=(),
            response_window_source_sequence=None,
        )
        self._commit_runtime(runtime, next_runtime)
        return next_state

    def _apply_end_play_phase(
        self,
        state: GameState,
        context: ActionContext,
        action: LegalAction,
    ) -> GameState:
        del action
        runtime = self._runtime
        if runtime.phase is not ProductionPhase.PLAY:
            raise InvalidActionError("只有出牌阶段可以结束出牌阶段")
        if context.actor_id != runtime.current_player_id:
            raise InvalidActionError("只有当前回合角色可以结束出牌阶段")
        next_runtime = replace(runtime, phase=ProductionPhase.END)
        self._commit_runtime(runtime, next_runtime)
        return state

    def _apply_end_turn(
        self,
        state: GameState,
        context: ActionContext,
        action: LegalAction,
    ) -> GameState:
        del action
        runtime = self._runtime
        if runtime.phase is not ProductionPhase.END:
            raise InvalidActionError("只有结束阶段可以结束回合")
        if context.actor_id != runtime.current_player_id:
            raise InvalidActionError("只有当前回合角色可以结束回合")
        next_player = self.opponent_of(runtime.current_player_id)
        next_state, draw_events = self._draw_cards(state, next_player, 2)
        self._events.extend(draw_events)
        next_runtime = replace(
            runtime,
            current_player_id=next_player,
            turn_number=runtime.turn_number + 1,
            phase=ProductionPhase.PLAY,
            slash_used=False,
            wine_buff_owner_id=None,
            wine_buff_used_this_play_phase=False,
            pending_slash=None,
            pending_trick=None,
            trick_effect_active=False,
            trick_consecutive_passes=0,
            trick_response_order=(),
            trick_response_index=0,
            trick_decision_count=0,
            pending_dying_id=None,
            rescue_order=(),
            rescue_index=0,
            rescue_decision_count=0,
            response_window_id=None,
            response_window_order=(),
            response_window_source_sequence=None,
        )
        self._commit_runtime(runtime, next_runtime)
        return next_state

    # ------------------------------------------------------------------
    # 实体牌移动与摸牌事务（真实 move_card / move_cards 原子移动）
    # ------------------------------------------------------------------

    def _move_to_processing(
        self,
        state: GameState,
        instance_id: str,
        card_user: str,
        reason: str,
    ) -> tuple[GameState, GameEvent]:
        source = state.location_of(instance_id)
        if source != ZoneRef.hand(card_user):
            raise ProductionBatchError(
                "只能处理当前行动角色真实手牌中的实体牌"
            )
        next_state = state.move_card(instance_id, PROCESSING_ZONE)
        return next_state, GameEvent(
            event_type=EventType.CARD_MOVED,
            card_instance_id=instance_id,
            card_key=_card_key(state, instance_id),
            card_user=card_user,
            payload={
                "source": _zone_payload(source),
                "destination": _zone_payload(PROCESSING_ZONE),
                "reason": reason,
            },
        )

    def _finish_processing(
        self,
        state: GameState,
        instance_id: str,
        reason: str,
    ) -> tuple[GameState, GameEvent]:
        source = state.location_of(instance_id)
        if source != PROCESSING_ZONE:
            raise ProductionBatchError("只有处理区中的实体牌可以完成结算")
        next_state = state.move_card(instance_id, DISCARD_PILE)
        return next_state, GameEvent(
            event_type=EventType.CARD_MOVED,
            card_instance_id=instance_id,
            card_key=_card_key(state, instance_id),
            payload={
                "source": _zone_payload(source),
                "destination": _zone_payload(DISCARD_PILE),
                "reason": reason,
            },
        )

    def _consume_immediately(
        self,
        state: GameState,
        instance_id: str,
        card_user: str,
        reason: str,
    ) -> tuple[GameState, tuple[GameEvent, GameEvent]]:
        processing_state, enter_event = self._move_to_processing(
            state, instance_id, card_user, f"{reason}:enter_processing"
        )
        finished_state, leave_event = self._finish_processing(
            processing_state, instance_id, f"{reason}:leave_processing"
        )
        return finished_state, (enter_event, leave_event)

    def _draw_cards(
        self,
        state: GameState,
        player_id: str,
        count: int,
    ) -> tuple[GameState, tuple[GameEvent, ...]]:
        if (
            len(state.card_ids_in(DRAW_PILE))
            + len(state.card_ids_in(DISCARD_PILE))
            < count
        ):
            raise ProductionBatchDeckExhaustedError(
                f"仍需摸{count}张牌，但牌堆与可重洗弃牌堆合计不足；"
                "生产批处理会话失败关闭"
            )
        next_state = state
        events: list[GameEvent] = []
        for _ in range(count):
            if not next_state.card_ids_in(DRAW_PILE):
                discard_ids = list(next_state.card_ids_in(DISCARD_PILE))
                self._rng.shuffle(discard_ids)
                sources = {
                    instance_id: next_state.location_of(instance_id)
                    for instance_id in discard_ids
                }
                next_state = next_state.move_cards(
                    {instance_id: DRAW_PILE for instance_id in discard_ids}
                )
                events.extend(
                    GameEvent(
                        event_type=EventType.CARD_MOVED,
                        card_instance_id=instance_id,
                        card_key=_card_key(next_state, instance_id),
                        payload={
                            "source": _zone_payload(sources[instance_id]),
                            "destination": _zone_payload(DRAW_PILE),
                            "reason": "reshuffle",
                        },
                    )
                    for instance_id in discard_ids
                )
            instance_id = next_state.card_ids_in(DRAW_PILE)[0]
            source = next_state.location_of(instance_id)
            next_state = next_state.move_card(
                instance_id, ZoneRef.hand(player_id)
            )
            events.extend(
                (
                    GameEvent(
                        event_type=EventType.CARD_MOVED,
                        card_instance_id=instance_id,
                        card_key=_card_key(next_state, instance_id),
                        payload={
                            "source": _zone_payload(source),
                            "destination": _zone_payload(
                                ZoneRef.hand(player_id)
                            ),
                            "reason": "draw_phase",
                        },
                    ),
                    GameEvent(
                        event_type=EventType.CARD_GAINED,
                        card_instance_id=instance_id,
                        card_key=_card_key(next_state, instance_id),
                        target_ids=(player_id,),
                        payload={"reason": "draw_phase"},
                    ),
                )
            )
        return next_state, tuple(events)


__all__ = [
    "BATCH_PHASES",
    "PRODUCTION_BASIC_CARDS_MODE",
    "BatchActionIdController",
    "BatchPhaseEntry",
    "BatchReferenceController",
    "ProductionBatchDeckExhaustedError",
    "ProductionBatchError",
    "ProductionBatchFinishedError",
    "ProductionBatchResult",
    "ProductionBatchSafetyLimitError",
    "ProductionBasicCardBatch",
    "ProductionPhase",
    "ScriptedBatchController",
]
