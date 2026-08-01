"""仅供权威核心验收使用的双人无技能纵向切片。

这个模块故意使用专用模式标识 ``test_only_duel_vertical_slice``。它不是
正式单挑模式，也不会读取或替代正式 160 张牌堆。它的唯一用途，是让核心
基础设施通过一条真实的、失败关闭的路径证明以下契约能够连通：不可变
``GameState``、实体牌守恒、``EventQueue``、单局 ``DeterministicRNG``，以及
``RuleRegistry -> enumerate_legal_actions -> apply_action``。

切片只实现【杀】【闪】【桃】、两名无技能角色和六个标准阶段。任何不在这
个明确范围内的规则都不会被概率、固定收益或空默认替代。
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
import json
from types import MappingProxyType
from typing import Iterable, Mapping, Sequence

from .actions import (
    ActionContext,
    ActionType,
    LegalAction,
    RuleAdapter,
    RuleRegistry,
    apply_action,
    enumerate_legal_actions,
    validate_action,
)
from .engine import canonical_state_snapshot
from .events import DamageEvent, EventQueue, EventType, GameEvent
from .model import (
    DISCARD_PILE,
    DRAW_PILE,
    PROCESSING_ZONE,
    CardInstance,
    GameState,
    PlayerState,
    ZoneRef,
)
from .rng import DeterministicRNG, RNGCall
from .replay import canonical_json, sha256_value


TEST_ONLY_DUEL_MODE = "test_only_duel_vertical_slice"
TEST_ONLY_DECK_ID = "test_only_duel_three_card_deck"


class DuelVerticalSliceError(RuntimeError):
    """纵向切片不能继续执行时的基础异常。"""


class DuelDeckExhaustedError(DuelVerticalSliceError):
    """摸牌堆与可重洗弃牌堆都不足时失败关闭。"""


class DuelSafetyLimitError(DuelVerticalSliceError):
    """动作步数超过显式安全上限时失败关闭。"""


class DuelFinishedError(DuelVerticalSliceError):
    """胜利已经成立后仍尝试继续推进对局。"""


class DuelPhase(str, Enum):
    PREPARE = "prepare"
    JUDGMENT = "judgment"
    DRAW = "draw"
    PLAY = "play"
    DISCARD = "discard"
    END = "end"
    SLASH_RESPONSE = "slash_response"
    DYING_RESCUE = "dying_rescue"
    FINISHED = "finished"


STANDARD_PHASES: tuple[DuelPhase, ...] = (
    DuelPhase.PREPARE,
    DuelPhase.JUDGMENT,
    DuelPhase.DRAW,
    DuelPhase.PLAY,
    DuelPhase.DISCARD,
    DuelPhase.END,
)


@dataclass(frozen=True, slots=True)
class PhaseEntry:
    turn_number: int
    turn_player_id: str
    phase: DuelPhase


@dataclass(frozen=True, slots=True)
class DuelResult:
    winner_id: str
    step_count: int
    turn_count: int
    final_state: GameState
    events: tuple[GameEvent, ...]
    rng_calls: tuple[RNGCall, ...]
    phase_history: tuple[PhaseEntry, ...]


@dataclass(frozen=True, slots=True)
class _RuntimeState:
    current_player_id: str
    phase: DuelPhase = DuelPhase.PREPARE
    turn_number: int = 1
    slash_used: bool = False
    pending_attacker_id: str | None = None
    pending_target_id: str | None = None
    pending_slash_id: str | None = None
    rescue_order: tuple[str, ...] = ()
    rescue_index: int = 0
    winner_id: str | None = None

    def audit_value(self) -> dict[str, object]:
        return {
            "current_player_id": self.current_player_id,
            "phase": self.phase.value,
            "turn_number": self.turn_number,
            "slash_used": self.slash_used,
            "pending_attacker_id": self.pending_attacker_id,
            "pending_target_id": self.pending_target_id,
            "pending_slash_id": self.pending_slash_id,
            "rescue_order": list(self.rescue_order),
            "rescue_index": self.rescue_index,
            "winner_id": self.winner_id,
        }


def _zone_payload(zone: ZoneRef) -> dict[str, object]:
    return {
        "kind": zone.kind.value,
        "owner_id": zone.owner_id,
        "equipment_slot": zone.equipment_slot,
        "special_zone": zone.special_zone,
    }


def _replace_player(
    state: GameState,
    player_id: str,
    *,
    hp: int | None = None,
    alive: bool | None = None,
) -> GameState:
    """只由规则适配器调用的不可变玩家状态事务。"""

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
        raise DuelVerticalSliceError(f"找不到玩家{player_id!r}")
    return replace(state, players=tuple(players), revision=state.revision + 1)


def _card_key(state: GameState, instance_id: str) -> str:
    return state.cards_by_id[instance_id].card_key


class DeterministicReferenceController:
    """验收用确定性控制器；只从已经签发的合法动作集合中选择。

    这不是 AI。它不读取隐藏状态、不建立评分，也不创造候选动作。固定优先
    级仅用于让同一状态得到稳定、可解释的验收路径。
    """

    strategy_version = "deterministic-reference-controller.v1"

    def choose(
        self,
        legal_actions: Sequence[LegalAction],
        context: ActionContext,
    ) -> LegalAction:
        if not legal_actions:
            raise DuelVerticalSliceError("规则适配器没有返回任何合法动作")
        if any(action.action_id is None for action in legal_actions):
            raise DuelVerticalSliceError("控制器只能接收已经签发ID的合法动作")

        def priority(action: LegalAction) -> tuple[int, str, str]:
            operation = str(action.payload.get("operation", ""))
            card_key = str(action.payload.get("card_key", ""))
            if context.phase == DuelPhase.SLASH_RESPONSE.value:
                rank = 0 if operation == "play_dodge" else 9
            elif context.phase == DuelPhase.DYING_RESCUE.value:
                dying_id = action.target_ids[0] if action.target_ids else None
                rank = 0 if operation == "rescue_with_peach" and dying_id == action.actor_id else 9
            elif context.phase == DuelPhase.PLAY.value:
                if operation == "heal_self" and card_key == "桃":
                    rank = 0
                elif operation == "use_slash" and card_key == "杀":
                    rank = 1
                else:
                    rank = 9
            elif context.phase == DuelPhase.DISCARD.value:
                rank = 0 if operation == "discard_for_limit" else 9
            else:
                rank = 0 if action.action_type is not ActionType.PASS else 1
            return rank, action.card_instance_id or "", action.action_id or ""

        return min(legal_actions, key=priority)


class _DuelRuleAdapter(RuleAdapter):
    def __init__(self, game: "TestOnlyDuelGame") -> None:
        self._game = game

    @property
    def adapter_version(self) -> str:
        return "test-only-duel-vertical-slice-rules.v1"

    def audit_state(self) -> Mapping[str, object]:
        return MappingProxyType(self._game._runtime.audit_value())

    def enumerate_legal_actions(
        self, state: GameState, context: ActionContext
    ) -> Iterable[LegalAction]:
        return self._game._enumerate_for_adapter(state, context)

    def apply_action(
        self, state: GameState, context: ActionContext, action: LegalAction
    ) -> GameState:
        return self._game._apply_for_adapter(state, context, action)


class TestOnlyDuelGame:
    """【杀】【闪】【桃】双人无技能纵向切片的可执行会话。"""

    __test__ = False

    def __init__(
        self,
        *,
        seed: int,
        deck_keys: Iterable[str] | None = None,
        player_hp: tuple[int, int] = (4, 4),
        player_max_hp: tuple[int, int] = (4, 4),
        shuffle: bool = True,
    ) -> None:
        if isinstance(seed, bool) or not isinstance(seed, int):
            raise TypeError("随机种子必须是整数")
        if len(player_hp) != 2 or len(player_max_hp) != 2:
            raise ValueError("双人切片必须提供恰好两名角色的体力")
        for index, (hp, max_hp) in enumerate(zip(player_hp, player_max_hp), start=1):
            if (
                isinstance(hp, bool)
                or not isinstance(hp, int)
                or isinstance(max_hp, bool)
                or not isinstance(max_hp, int)
            ):
                raise TypeError(f"第{index}名角色的初始体力与上限必须是整数")
            if hp < 1 or max_hp < 1:
                raise ValueError(f"第{index}名角色必须以至少1点体力和体力上限开始")
            if hp > max_hp:
                raise ValueError(f"第{index}名角色的初始体力不能高于体力上限")
        if not isinstance(shuffle, bool):
            raise TypeError("shuffle必须是布尔值")

        keys = tuple(deck_keys) if deck_keys is not None else self.default_deck_keys()
        if len(keys) < 12:
            raise ValueError("测试专用小牌堆至少需要12张实体牌")
        if any(key not in {"杀", "闪", "桃"} for key in keys):
            raise ValueError("测试专用小牌堆只支持【杀】【闪】【桃】")
        missing = {"杀", "闪", "桃"} - set(keys)
        if missing:
            raise ValueError("测试专用小牌堆必须同时包含【杀】【闪】【桃】")

        self._rng = DeterministicRNG(seed)
        # 生命周期先决定先手，再由同一条随机流洗牌；该调用顺序属于重执行契约。
        first_player_id = self._rng.choice(("p1", "p2"))
        self._first_player_id = first_player_id
        cards = self._build_cards(keys)
        ordered_ids = [card.instance_id for card in cards]
        if shuffle:
            self._rng.shuffle(ordered_ids)
        cards_by_id = {card.instance_id: card for card in cards}

        # 轮流发四张；这是初始状态构造，不是绕过规则适配器修改既有状态。
        p1_hand = tuple(ordered_ids[index] for index in (0, 2, 4, 6))
        p2_hand = tuple(ordered_ids[index] for index in (1, 3, 5, 7))
        dealt = set(p1_hand) | set(p2_hand)
        draw_order = tuple(instance_id for instance_id in ordered_ids if instance_id not in dealt)
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
        players = (
            PlayerState("p1", 1, player_hp[0], player_max_hp[0]),
            PlayerState("p2", 2, player_hp[1], player_max_hp[1]),
        )
        self._state = GameState(
            cards=tuple(cards_by_id[instance_id] for instance_id in sorted(cards_by_id)),
            players=players,
            card_locations=locations,
            zone_order={
                ZoneRef.hand("p1"): p1_hand,
                ZoneRef.hand("p2"): p2_hand,
                DRAW_PILE: draw_order,
                DISCARD_PILE: (),
                PROCESSING_ZONE: (),
            },
            deck_id=TEST_ONLY_DECK_ID,
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

        self._runtime = _RuntimeState(current_player_id=first_player_id)
        self._phase_history: list[PhaseEntry] = [
            PhaseEntry(1, first_player_id, DuelPhase.PREPARE)
        ]
        self._step_count = 0
        self._registry = RuleRegistry()
        adapter = _DuelRuleAdapter(self)
        for phase in (*STANDARD_PHASES, DuelPhase.SLASH_RESPONSE, DuelPhase.DYING_RESCUE):
            self._registry.register(TEST_ONLY_DUEL_MODE, phase.value, adapter)

    @staticmethod
    def default_deck_keys() -> tuple[str, ...]:
        """返回明确的小牌堆；它不是正式160张牌堆。"""

        return tuple(["杀"] * 18 + ["闪"] * 3 + ["桃"] * 3)

    @staticmethod
    def _build_cards(keys: Sequence[str]) -> tuple[CardInstance, ...]:
        suits = ("spade", "heart", "club", "diamond")
        colors = {"spade": "black", "club": "black", "heart": "red", "diamond": "red"}
        return tuple(
            CardInstance(
                instance_id=f"test-card-{index:03d}",
                deck_id=TEST_ONLY_DECK_ID,
                card_key=key,
                card_name=key,
                card_type="basic",
                suit=suits[(index - 1) % len(suits)],
                color=colors[suits[(index - 1) % len(suits)]],
                rank=str(((index - 1) % 13) + 1),
            )
            for index, key in enumerate(keys, start=1)
        )

    @property
    def state(self) -> GameState:
        return self._state

    @property
    def registry(self) -> RuleRegistry:
        return self._registry

    @property
    def phase(self) -> DuelPhase:
        return self._runtime.phase

    @property
    def current_player_id(self) -> str:
        return self._runtime.current_player_id

    @property
    def first_player_id(self) -> str:
        return self._first_player_id

    @property
    def current_actor_id(self) -> str:
        if self.phase is DuelPhase.SLASH_RESPONSE:
            assert self._runtime.pending_target_id is not None
            return self._runtime.pending_target_id
        if self.phase is DuelPhase.DYING_RESCUE:
            return self._runtime.rescue_order[self._runtime.rescue_index]
        return self._runtime.current_player_id

    @property
    def is_finished(self) -> bool:
        return self.phase is DuelPhase.FINISHED

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
    def phase_history(self) -> tuple[PhaseEntry, ...]:
        return tuple(self._phase_history)

    @property
    def step_count(self) -> int:
        return self._step_count

    @property
    def execution_snapshot(self) -> dict[str, object]:
        """返回可序列化的稳定执行快照，供严格重执行逐步比较。"""

        snapshot = {
            "schema": "test-only-duel-execution-v1",
            "mode": TEST_ONLY_DUEL_MODE,
            "runtime": self._runtime.audit_value(),
            "first_player_id": self.first_player_id,
            "current_actor_id": None if self.is_finished else self.current_actor_id,
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
        # 事件负载经过深冻结后可能包含 MappingProxyType；通过统一规范 JSON
        # 边界生成独立普通对象，保证快照本身也可直接保存，而不只是可哈希。
        normalized = json.loads(canonical_json(snapshot))
        assert isinstance(normalized, dict)
        return normalized

    @property
    def execution_hash(self) -> str:
        return sha256_value(self.execution_snapshot)

    def _context(self) -> ActionContext:
        if self.is_finished:
            raise DuelFinishedError("胜利已经成立，对局不得继续执行动作")
        response_window_id = None
        if self.phase is DuelPhase.SLASH_RESPONSE:
            response_window_id = f"slash:{self._runtime.pending_slash_id}"
        elif self.phase is DuelPhase.DYING_RESCUE:
            response_window_id = (
                f"dying:{self._runtime.pending_target_id}:{self._runtime.turn_number}"
            )
        return ActionContext(
            mode=TEST_ONLY_DUEL_MODE,
            phase=self.phase.value,
            actor_id=self.current_actor_id,
            turn_player_id=self.current_player_id,
            response_window_id=response_window_id,
            expected_revision=self.state.revision,
            metadata={
                "turn_number": self._runtime.turn_number,
                "slash_used": self._runtime.slash_used,
                "pending_target_id": self._runtime.pending_target_id,
            },
        )

    def legal_actions(self) -> tuple[LegalAction, ...]:
        return enumerate_legal_actions(self.state, self._context(), self.registry)

    def step(
        self, controller: DeterministicReferenceController | None = None
    ) -> LegalAction:
        if self.is_finished:
            raise DuelFinishedError("胜利已经成立，对局不得继续执行动作")
        selected_controller = controller or DeterministicReferenceController()
        context = self._context()
        legal = enumerate_legal_actions(self.state, context, self.registry)
        chosen = selected_controller.choose(legal, context)
        validated = validate_action(self.state, context, chosen, self.registry)
        self._state = apply_action(self.state, context, validated, self.registry)
        self._step_count += 1
        self._state.assert_card_conservation()
        return validated

    def run(
        self,
        controller: DeterministicReferenceController | None = None,
        *,
        max_steps: int = 500,
    ) -> DuelResult:
        if isinstance(max_steps, bool) or not isinstance(max_steps, int) or max_steps < 1:
            raise ValueError("安全动作上限必须是正整数")
        selected_controller = controller or DeterministicReferenceController()
        executed = 0
        while not self.is_finished and executed < max_steps:
            self.step(selected_controller)
            executed += 1
        if not self.is_finished:
            raise DuelSafetyLimitError(
                f"测试对局在{max_steps}个动作后仍未结束；禁止静默判胜或近似收尾"
            )
        assert self.winner_id is not None
        return DuelResult(
            winner_id=self.winner_id,
            step_count=self.step_count,
            turn_count=self._runtime.turn_number,
            final_state=self.state,
            events=self.events,
            rng_calls=self.rng_calls,
            phase_history=self.phase_history,
        )

    def _enumerate_for_adapter(
        self, state: GameState, context: ActionContext
    ) -> tuple[LegalAction, ...]:
        if context.mode != TEST_ONLY_DUEL_MODE or context.phase != self.phase.value:
            raise DuelVerticalSliceError("行动上下文与测试对局当前阶段不一致")
        actor = context.actor_id
        hand = state.card_ids_in(ZoneRef.hand(actor))
        actions: list[LegalAction] = []

        if self.phase in {DuelPhase.PREPARE, DuelPhase.JUDGMENT, DuelPhase.END}:
            return (LegalAction(action_type=ActionType.PASS, actor_id=actor),)
        if self.phase is DuelPhase.DRAW:
            return (
                LegalAction(
                    action_type=ActionType.CHOOSE_OPTION,
                    actor_id=actor,
                    payload={"operation": "draw_two"},
                ),
            )
        if self.phase is DuelPhase.PLAY:
            player = state.players_by_id[actor]
            if player.hp < player.max_hp:
                for instance_id in hand:
                    if _card_key(state, instance_id) == "桃":
                        actions.append(
                            LegalAction(
                                action_type=ActionType.USE_CARD,
                                actor_id=actor,
                                card_instance_id=instance_id,
                                target_ids=(actor,),
                                payload={"operation": "heal_self", "card_key": "桃"},
                            )
                        )
            if not self._runtime.slash_used:
                target = self._opponent(actor)
                for instance_id in hand:
                    if _card_key(state, instance_id) == "杀":
                        actions.append(
                            LegalAction(
                                action_type=ActionType.USE_CARD,
                                actor_id=actor,
                                card_instance_id=instance_id,
                                target_ids=(target,),
                                payload={"operation": "use_slash", "card_key": "杀"},
                            )
                        )
            actions.append(LegalAction(action_type=ActionType.PASS, actor_id=actor))
            return tuple(actions)
        if self.phase is DuelPhase.DISCARD:
            player = state.players_by_id[actor]
            excess = len(hand) - max(player.hp, 0)
            if excess <= 0:
                return (LegalAction(action_type=ActionType.PASS, actor_id=actor),)
            return tuple(
                LegalAction(
                    action_type=ActionType.MOVE_CARD,
                    actor_id=actor,
                    card_instance_id=instance_id,
                    payload={
                        "operation": "discard_for_limit",
                        "card_key": _card_key(state, instance_id),
                    },
                )
                for instance_id in hand
            )
        if self.phase is DuelPhase.SLASH_RESPONSE:
            for instance_id in hand:
                if _card_key(state, instance_id) == "闪":
                    actions.append(
                        LegalAction(
                            action_type=ActionType.USE_CARD,
                            actor_id=actor,
                            card_instance_id=instance_id,
                            payload={"operation": "play_dodge", "card_key": "闪"},
                        )
                    )
            actions.append(LegalAction(action_type=ActionType.PASS, actor_id=actor))
            return tuple(actions)
        if self.phase is DuelPhase.DYING_RESCUE:
            dying_id = self._runtime.pending_target_id
            assert dying_id is not None
            for instance_id in hand:
                if _card_key(state, instance_id) == "桃":
                    actions.append(
                        LegalAction(
                            action_type=ActionType.USE_CARD,
                            actor_id=actor,
                            card_instance_id=instance_id,
                            target_ids=(dying_id,),
                            payload={"operation": "rescue_with_peach", "card_key": "桃"},
                        )
                    )
            actions.append(LegalAction(action_type=ActionType.PASS, actor_id=actor))
            return tuple(actions)
        raise DuelVerticalSliceError(f"阶段{self.phase.value!r}不在测试切片范围内")

    def _apply_for_adapter(
        self, state: GameState, context: ActionContext, action: LegalAction
    ) -> GameState:
        runtime = self._runtime
        next_runtime = runtime
        next_state = state
        pending_events: list[GameEvent] = []
        operation = str(action.payload.get("operation", ""))

        if self.phase is DuelPhase.PREPARE:
            next_runtime = replace(runtime, phase=DuelPhase.JUDGMENT)
        elif self.phase is DuelPhase.JUDGMENT:
            next_runtime = replace(runtime, phase=DuelPhase.DRAW)
        elif self.phase is DuelPhase.DRAW:
            next_state, draw_events = self._draw_cards(state, context.actor_id, 2)
            pending_events.extend(draw_events)
            next_runtime = replace(runtime, phase=DuelPhase.PLAY)
        elif self.phase is DuelPhase.PLAY and operation == "heal_self":
            assert action.card_instance_id is not None
            next_state, move_events = self._consume_immediately(
                state, action.card_instance_id, context.actor_id, "peach_resolve"
            )
            player = next_state.players_by_id[context.actor_id]
            next_state = _replace_player(
                next_state, context.actor_id, hp=min(player.max_hp, player.hp + 1)
            )
            pending_events.extend(
                (
                    GameEvent(
                        event_type=EventType.CARD_USED,
                        card_instance_id=action.card_instance_id,
                        card_key="桃",
                        card_user=context.actor_id,
                        target_ids=(context.actor_id,),
                        payload={"purpose": "heal_self"},
                    ),
                    *move_events,
                )
            )
        elif self.phase is DuelPhase.PLAY and operation == "use_slash":
            assert action.card_instance_id is not None and action.target_ids
            target = action.target_ids[0]
            next_state, move_event = self._move_to_processing(
                state, action.card_instance_id, context.actor_id, "slash_use"
            )
            pending_events.extend(
                (
                    GameEvent(
                        event_type=EventType.CARD_USED,
                        card_instance_id=action.card_instance_id,
                        card_key="杀",
                        card_user=context.actor_id,
                        target_ids=(target,),
                    ),
                    move_event,
                )
            )
            next_runtime = replace(
                runtime,
                phase=DuelPhase.SLASH_RESPONSE,
                slash_used=True,
                pending_attacker_id=context.actor_id,
                pending_target_id=target,
                pending_slash_id=action.card_instance_id,
            )
        elif self.phase is DuelPhase.PLAY and action.action_type is ActionType.PASS:
            next_runtime = replace(runtime, phase=DuelPhase.DISCARD)
        elif self.phase is DuelPhase.DISCARD and operation == "discard_for_limit":
            assert action.card_instance_id is not None
            next_state, move_event = self._move_to_discard(
                state, action.card_instance_id, context.actor_id, "discard_phase"
            )
            pending_events.extend(
                (
                    GameEvent(
                        event_type=EventType.CARD_DISCARDED,
                        card_instance_id=action.card_instance_id,
                        card_key=_card_key(state, action.card_instance_id),
                        card_user=context.actor_id,
                        payload={"reason": "hand_limit"},
                    ),
                    move_event,
                )
            )
        elif self.phase is DuelPhase.DISCARD and action.action_type is ActionType.PASS:
            next_runtime = replace(runtime, phase=DuelPhase.END)
        elif self.phase is DuelPhase.END:
            opponent = self._opponent(runtime.current_player_id)
            next_runtime = replace(
                runtime,
                current_player_id=opponent,
                phase=DuelPhase.PREPARE,
                turn_number=runtime.turn_number + 1,
                slash_used=False,
            )
        elif self.phase is DuelPhase.SLASH_RESPONSE and operation == "play_dodge":
            assert action.card_instance_id is not None
            next_state, dodge_move_events = self._consume_immediately(
                state, action.card_instance_id, context.actor_id, "dodge_response_complete"
            )
            assert runtime.pending_slash_id is not None
            next_state, slash_finish_event = self._finish_processing(
                next_state, runtime.pending_slash_id, "slash_cancelled_by_dodge"
            )
            pending_events.extend(
                (
                    GameEvent(
                        event_type=EventType.CARD_USED,
                        card_instance_id=action.card_instance_id,
                        card_key="闪",
                        card_user=context.actor_id,
                        payload={"response_to": runtime.pending_slash_id},
                    ),
                    *dodge_move_events,
                    GameEvent(
                        event_type=EventType.CARD_EFFECT_CANCELLED,
                        card_instance_id=runtime.pending_slash_id,
                        card_key="杀",
                        target_ids=(context.actor_id,),
                        payload={"reason": "dodge"},
                    ),
                    slash_finish_event,
                )
            )
            next_runtime = self._return_to_play(runtime)
        elif self.phase is DuelPhase.SLASH_RESPONSE and action.action_type is ActionType.PASS:
            next_state, next_runtime, damage_events = self._resolve_slash_damage(state, runtime)
            pending_events.extend(damage_events)
        elif self.phase is DuelPhase.DYING_RESCUE and operation == "rescue_with_peach":
            assert action.card_instance_id is not None
            dying_id = runtime.pending_target_id
            assert dying_id is not None
            next_state, move_events = self._consume_immediately(
                state, action.card_instance_id, context.actor_id, "dying_rescue"
            )
            dying = next_state.players_by_id[dying_id]
            next_state = _replace_player(
                next_state, dying_id, hp=min(dying.max_hp, dying.hp + 1)
            )
            pending_events.extend(
                (
                    GameEvent(
                        event_type=EventType.CARD_USED,
                        card_instance_id=action.card_instance_id,
                        card_key="桃",
                        card_user=context.actor_id,
                        target_ids=(dying_id,),
                        payload={"purpose": "dying_rescue"},
                    ),
                    *move_events,
                )
            )
            if next_state.players_by_id[dying_id].hp >= 1:
                assert runtime.pending_slash_id is not None
                next_state, slash_finish_event = self._finish_processing(
                    next_state, runtime.pending_slash_id, "slash_damage_resolved_after_rescue"
                )
                pending_events.append(slash_finish_event)
                next_runtime = self._return_to_play(runtime)
        elif self.phase is DuelPhase.DYING_RESCUE and action.action_type is ActionType.PASS:
            next_state, next_runtime, rescue_events = self._pass_rescue(state, runtime)
            pending_events.extend(rescue_events)
        else:
            raise DuelVerticalSliceError(
                f"阶段{self.phase.value!r}不支持动作{action.action_type.value!r}"
            )

        next_state.assert_card_conservation()
        # EventQueue.extend会先完整验证pending，再分配单调序号；通过后才提交运行态。
        self._events.extend(pending_events)
        previous_entry = (
            runtime.turn_number,
            runtime.current_player_id,
            runtime.phase,
        )
        next_entry = (
            next_runtime.turn_number,
            next_runtime.current_player_id,
            next_runtime.phase,
        )
        self._runtime = next_runtime
        if next_entry != previous_entry:
            self._phase_history.append(
                PhaseEntry(
                    next_runtime.turn_number,
                    next_runtime.current_player_id,
                    next_runtime.phase,
                )
            )
        return next_state

    def _draw_cards(
        self, state: GameState, player_id: str, count: int
    ) -> tuple[GameState, tuple[GameEvent, ...]]:
        if len(state.card_ids_in(DRAW_PILE)) + len(state.card_ids_in(DISCARD_PILE)) < count:
            raise DuelDeckExhaustedError(
                f"仍需摸{count}张牌，但牌堆与可重洗弃牌堆合计不足；测试切片失败关闭"
            )
        next_state = state
        events: list[GameEvent] = []
        for _ in range(count):
            if not next_state.card_ids_in(DRAW_PILE):
                discard_ids = list(next_state.card_ids_in(DISCARD_PILE))
                self._rng.shuffle(discard_ids)
                sources = {instance_id: next_state.location_of(instance_id) for instance_id in discard_ids}
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
            next_state = next_state.move_card(instance_id, ZoneRef.hand(player_id))
            events.extend(
                (
                    GameEvent(
                        event_type=EventType.CARD_MOVED,
                        card_instance_id=instance_id,
                        card_key=_card_key(next_state, instance_id),
                        payload={
                            "source": _zone_payload(source),
                            "destination": _zone_payload(ZoneRef.hand(player_id)),
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

    def _move_to_discard(
        self, state: GameState, instance_id: str, card_user: str, reason: str
    ) -> tuple[GameState, GameEvent]:
        source = state.location_of(instance_id)
        if source != ZoneRef.hand(card_user):
            raise DuelVerticalSliceError("只能使用或弃置当前行动角色真实手牌中的实体牌")
        next_state = state.move_card(instance_id, DISCARD_PILE)
        return next_state, GameEvent(
            event_type=EventType.CARD_MOVED,
            card_instance_id=instance_id,
            card_key=_card_key(state, instance_id),
            card_user=card_user,
            payload={
                "source": _zone_payload(source),
                "destination": _zone_payload(DISCARD_PILE),
                "reason": reason,
            },
        )

    def _move_to_processing(
        self, state: GameState, instance_id: str, card_user: str, reason: str
    ) -> tuple[GameState, GameEvent]:
        source = state.location_of(instance_id)
        if source != ZoneRef.hand(card_user):
            raise DuelVerticalSliceError("只能处理当前行动角色真实手牌中的实体牌")
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
        self, state: GameState, instance_id: str, reason: str
    ) -> tuple[GameState, GameEvent]:
        source = state.location_of(instance_id)
        if source != PROCESSING_ZONE:
            raise DuelVerticalSliceError("只有处理区中的实体牌可以完成结算")
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
        self, state: GameState, instance_id: str, card_user: str, reason: str
    ) -> tuple[GameState, tuple[GameEvent, GameEvent]]:
        processing_state, enter_event = self._move_to_processing(
            state, instance_id, card_user, f"{reason}:enter_processing"
        )
        finished_state, leave_event = self._finish_processing(
            processing_state, instance_id, f"{reason}:leave_processing"
        )
        return finished_state, (enter_event, leave_event)

    def _resolve_slash_damage(
        self, state: GameState, runtime: _RuntimeState
    ) -> tuple[GameState, _RuntimeState, tuple[GameEvent, ...]]:
        attacker = runtime.pending_attacker_id
        target = runtime.pending_target_id
        slash_id = runtime.pending_slash_id
        assert attacker is not None and target is not None and slash_id is not None
        victim = state.players_by_id[target]
        next_state = _replace_player(state, target, hp=victim.hp - 1)
        events: list[GameEvent] = [
            DamageEvent(
                target_id=target,
                amount=1,
                damage_type="无属性",
                card_instance_id=slash_id,
                card_key="杀",
                card_user=attacker,
                damage_source=attacker,
                kill_credit=attacker,
            )
        ]
        if next_state.players_by_id[target].hp <= 0:
            events.append(
                GameEvent(
                    event_type=EventType.DYING,
                    damage_source=attacker,
                    kill_credit=attacker,
                    target_ids=(target,),
                )
            )
            rescue_order = (runtime.current_player_id, self._opponent(runtime.current_player_id))
            return (
                next_state,
                replace(
                    runtime,
                    phase=DuelPhase.DYING_RESCUE,
                    rescue_order=rescue_order,
                    rescue_index=0,
                ),
                tuple(events),
            )
        next_state, finish_event = self._finish_processing(
            next_state, slash_id, "slash_damage_resolved"
        )
        events.append(finish_event)
        return next_state, self._return_to_play(runtime), tuple(events)

    def _pass_rescue(
        self, state: GameState, runtime: _RuntimeState
    ) -> tuple[GameState, _RuntimeState, tuple[GameEvent, ...]]:
        next_index = runtime.rescue_index + 1
        if next_index < len(runtime.rescue_order):
            return state, replace(runtime, rescue_index=next_index), ()
        dying_id = runtime.pending_target_id
        assert dying_id is not None
        dying = state.players_by_id[dying_id]
        if dying.hp >= 1:
            return state, self._return_to_play(runtime), ()
        slash_id = runtime.pending_slash_id
        assert slash_id is not None
        next_state, finish_event = self._finish_processing(
            state, slash_id, "slash_damage_resolved_with_death"
        )
        next_state = _replace_player(next_state, dying_id, alive=False)
        winner = self._opponent(dying_id)
        events = (
            finish_event,
            GameEvent(
                event_type=EventType.DEATH,
                damage_source=runtime.pending_attacker_id,
                kill_credit=runtime.pending_attacker_id,
                target_ids=(dying_id,),
            ),
            GameEvent(event_type=EventType.VICTORY, target_ids=(winner,)),
        )
        return (
            next_state,
            replace(
                runtime,
                phase=DuelPhase.FINISHED,
                winner_id=winner,
                rescue_order=(),
                rescue_index=0,
            ),
            events,
        )

    @staticmethod
    def _return_to_play(runtime: _RuntimeState) -> _RuntimeState:
        return replace(
            runtime,
            phase=DuelPhase.PLAY,
            pending_attacker_id=None,
            pending_target_id=None,
            pending_slash_id=None,
            rescue_order=(),
            rescue_index=0,
        )

    @staticmethod
    def _opponent(player_id: str) -> str:
        if player_id == "p1":
            return "p2"
        if player_id == "p2":
            return "p1"
        raise DuelVerticalSliceError(f"测试切片不存在玩家{player_id!r}")


__all__ = [
    "STANDARD_PHASES",
    "TEST_ONLY_DECK_ID",
    "TEST_ONLY_DUEL_MODE",
    "DeterministicReferenceController",
    "DuelDeckExhaustedError",
    "DuelFinishedError",
    "DuelPhase",
    "DuelResult",
    "DuelSafetyLimitError",
    "DuelVerticalSliceError",
    "PhaseEntry",
    "TestOnlyDuelGame",
]
