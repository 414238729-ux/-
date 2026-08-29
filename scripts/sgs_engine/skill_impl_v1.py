# -*- coding: utf-8 -*-
"""V1 mandatory proof skills implementations: 【募讨】(Mutao), 【明哲】(Mingzhe), 【帷幕】(Weimu).

Each skill implements SkillHandler with exact Knowledge rules and zero approximations:
- Mutao: Active play-phase card transfer with discrete branch options (draw bonus vs slash bonus).
- Mingzhe: Optional trigger on losing red cards off-turn, drawing 1 card through production path.
- Weimu: Locked static modifier prohibiting black trick cards from targeting the skill owner.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import Any, Sequence

from .actions import (
    ActionContext,
    ActionType,
    InvalidActionError,
    LegalAction,
    UnsupportedRuleError,
)
from .events import EventType, GameEvent
from .model import (
    CardInstance,
    DRAW_PILE,
    GameState,
    ZoneKind,
    ZoneRef,
)
from .skill_registry import AuthoritativeSkillRegistry, create_skill_registry


def _mingzhe_loser_id(event: GameEvent) -> str | None:
    """Identify who lost the card for 使用/打出/弃置, not generic movement.

    CARD_DISCARDED from 【过河拆桥】 uses card_user=拆桥者 and target_ids=失去者.
    CARD_USED / CARD_PLAYED use card_user as the character who spent the card.
    """
    if event.event_type is EventType.CARD_DISCARDED:
        if event.target_ids:
            return event.target_ids[0]
        return event.card_user
    if event.event_type in (EventType.CARD_USED, EventType.CARD_PLAYED):
        return event.card_user
    return None
from .skills import (
    AuthoritativeSkillKind,
    AuthoritativeSkillTag,
    SkillDefinition,
    SkillHandler,
    SkillRuntimeState,
    SkillTimingWindow,
    SkillTriggerContext,
)


class MutaoSkillHandler(SkillHandler):
    """【募讨】：出牌阶段限一次，你可以将一张手牌交给一名其他角色，并选择一项分支。"""

    def __init__(self) -> None:
        self._definition = SkillDefinition(
            skill_id="sgs_skill_mutao",
            skill_name="募讨",
            version="1.0.0",
            kind=AuthoritativeSkillKind.ACTIVE,
            tags=frozenset(),
            timing_windows=frozenset({SkillTimingWindow.PLAY_PHASE_ACTION}),
            is_mandatory=False,
            max_uses_per_phase=1,
            description=(
                "出牌阶段限一次，你可以将一张手牌交给一名其他角色，并选择一项："
                "1.令其于其下个回合的摸牌阶段多摸一张牌；2.令其于其下个回合的出牌阶段可以多使用一张【杀】。"
            ),
        )

    @property
    def definition(self) -> SkillDefinition:
        return self._definition

    def enumerate_active_actions(
        self,
        context: ActionContext,
        state: GameState,
        skill_state: SkillRuntimeState,
    ) -> tuple[LegalAction, ...]:
        actor_id = skill_state.owner_id
        if context.actor_id != actor_id:
            return ()

        # Check hand cards
        hand_zone = ZoneRef.hand(actor_id)
        hand_card_ids = state.card_ids_in(hand_zone)
        if not hand_card_ids:
            return ()

        # Other alive players
        other_alive_targets = [
            p.player_id for p in state.players if p.alive and p.player_id != actor_id
        ]
        if not other_alive_targets:
            return ()

        actions: list[LegalAction] = []
        for card_id in sorted(hand_card_ids):
            for target_id in sorted(other_alive_targets):
                for branch in (1, 2):
                    actions.append(
                        LegalAction(
                            action_type=ActionType.ACTIVATE_SKILL,
                            actor_id=actor_id,
                            card_instance_id=card_id,
                            target_ids=(target_id,),
                            skill_id="sgs_skill_mutao",
                            payload={"branch": branch, "material_card_instance_id": card_id},
                        )
                    )
        return tuple(actions)

    def apply_action(
        self,
        action: LegalAction,
        context: ActionContext,
        state: GameState,
        skill_state: SkillRuntimeState,
    ) -> tuple[GameState, SkillRuntimeState, tuple[GameEvent, ...]]:
        actor_id = skill_state.owner_id
        if action.actor_id != actor_id:
            raise InvalidActionError(f"动作执行角色 {action.actor_id} 与技能所有者 {actor_id} 不一致")
        if not action.target_ids or len(action.target_ids) != 1:
            raise InvalidActionError("【募讨】必须且只能指定一名目标角色")
        target_id = action.target_ids[0]
        if target_id == actor_id:
            raise InvalidActionError("【募讨】只能指定其他角色为目标")

        target_player = state.players_by_id.get(target_id)
        if target_player is None or not target_player.alive:
            raise InvalidActionError(f"【募讨】目标角色 {target_id} 不存在或已死亡")

        card_id = action.card_instance_id
        if not card_id:
            raise InvalidActionError("【募讨】必须指定一张手牌实体ID")

        current_location = state.location_of(card_id)
        expected_location = ZoneRef.hand(actor_id)
        if current_location != expected_location:
            raise InvalidActionError(f"【募讨】材料牌 {card_id} 不在 {actor_id} 的手牌区")

        branch = action.payload.get("branch")
        if branch not in (1, 2):
            raise InvalidActionError("【募讨】分支选项必须为 1 或 2")

        # Transfer card from actor's hand to target's hand
        destination = ZoneRef.hand(target_id)
        new_state = state.move_card(card_id, destination)

        event = GameEvent(
            event_type=EventType.CARD_MOVED,
            card_instance_id=card_id,
            card_user=actor_id,
            skill_owner=actor_id,
            target_ids=(target_id,),
            payload={
                "reason": "sgs_skill_mutao",
                "branch": branch,
                "from_player_id": actor_id,
                "to_player_id": target_id,
            },
        )
        return new_state, skill_state, (event,)


class MingzheSkillHandler(SkillHandler):
    """【明哲】：当你于回合外失去一张红色牌时，你可以摸一张牌。"""

    def __init__(self) -> None:
        self._definition = SkillDefinition(
            skill_id="sgs_skill_mingzhe",
            skill_name="明哲",
            version="1.0.0",
            kind=AuthoritativeSkillKind.TRIGGERED,
            tags=frozenset(),
            timing_windows=frozenset(
                {
                    SkillTimingWindow.ON_CARD_USED,
                    SkillTimingWindow.ON_CARD_PLAYED,
                    SkillTimingWindow.ON_CARD_DISCARDED,
                }
            ),
            is_mandatory=False,
            description="当你于回合外失去一张红色牌时，你可以摸一张牌。",
        )

    @property
    def definition(self) -> SkillDefinition:
        return self._definition

    def evaluate_trigger(
        self,
        context: SkillTriggerContext,
        state: GameState,
        skill_state: SkillRuntimeState,
    ) -> bool:
        owner_id = skill_state.owner_id
        # Off-turn condition: current turn player is not owner
        if context.turn_player_id == owner_id:
            return False

        event = context.event
        if event is None:
            return False
        if event.event_type not in (
            EventType.CARD_USED,
            EventType.CARD_PLAYED,
            EventType.CARD_DISCARDED,
        ):
            return False
        card_id = event.card_instance_id
        if not card_id:
            return False
        loser_id = _mingzhe_loser_id(event)
        if loser_id != owner_id:
            return False
        card = state.cards_by_id.get(card_id)
        if card is None:
            return False
        return card.color == "红"

    def enumerate_trigger_actions(
        self,
        context: SkillTriggerContext,
        state: GameState,
        skill_state: SkillRuntimeState,
    ) -> tuple[LegalAction, ...]:
        owner_id = skill_state.owner_id
        seq = context.event.sequence if context.event else None
        return (
            LegalAction(
                action_type=ActionType.ACTIVATE_SKILL,
                actor_id=owner_id,
                skill_id="sgs_skill_mingzhe",
                payload={"decision": "activate", "trigger_event_sequence": seq},
            ),
            LegalAction(
                action_type=ActionType.PASS,
                actor_id=owner_id,
                skill_id="sgs_skill_mingzhe",
                payload={"decision": "pass", "trigger_event_sequence": seq},
            ),
        )

    def apply_action(
        self,
        action: LegalAction,
        context: ActionContext,
        state: GameState,
        skill_state: SkillRuntimeState,
    ) -> tuple[GameState, SkillRuntimeState, tuple[GameEvent, ...]]:
        owner_id = skill_state.owner_id
        if action.actor_id != owner_id:
            raise InvalidActionError(f"动作执行角色 {action.actor_id} 与技能所有者 {owner_id} 不一致")
        if action.payload.get("decision") == "pass" or action.action_type is ActionType.PASS:
            return state, skill_state, ()
        raise UnsupportedRuleError(
            "【明哲】组件 apply_action 不能执行生产摸牌；必须通过 ProductionBasicCardBatch.step"
        )

    def apply_in_production(
        self,
        session: object,
        action: LegalAction,
        context: ActionContext,
        state: GameState,
        skill_state: SkillRuntimeState,
    ) -> GameState:
        if action.payload.get("decision") == "pass" or action.action_type is ActionType.PASS:
            raise InvalidActionError("【明哲】放弃必须走 pass_skill 生产入口，不得进入效果结算")
        owner_id = skill_state.owner_id
        if action.actor_id != owner_id:
            raise InvalidActionError(f"动作执行角色 {action.actor_id} 与技能所有者 {owner_id} 不一致")
        return session.draw_cards_for_skill(
            state,
            owner_id,
            1,
            reason="sgs_skill_mingzhe",
            skill_owner=owner_id,
        )


class WeimuSkillHandler(SkillHandler):
    """【帷幕】: prohibit all black tricks at target-legality formation."""

    def __init__(self) -> None:
        self._definition = SkillDefinition(
            skill_id="sgs_skill_weimu",
            skill_name="帷幕",
            version="1.0.0",
            kind=AuthoritativeSkillKind.STATIC_MODIFIER,
            tags=frozenset({AuthoritativeSkillTag.LOCKED}),
            timing_windows=frozenset({SkillTimingWindow.TARGET_FILTER}),
            is_mandatory=True,
            description=(
                "锁定技，你不能成为黑色锦囊牌的目标。适用于普通、群体与"
                "延时锦囊，并在目标合法性或自动目标集合形成阶段生效。"
            ),
        )

    @property
    def definition(self) -> SkillDefinition:
        return self._definition

    def filter_target_legality(
        self,
        target_id: str,
        card_instance: CardInstance | None,
        card_key: str,
        user_id: str,
        state: GameState,
        skill_state: SkillRuntimeState,
    ) -> bool:
        if target_id != skill_state.owner_id:
            return True
        if card_instance is None:
            raise UnsupportedRuleError("【帷幕】目标过滤必须提供实体牌以判定颜色，禁止只凭 card_key 猜测")
        is_trick = card_instance.card_type in {"锦囊牌", "延时锦囊牌"} or (
            card_key.startswith("sgs_trick_")
            or card_key.startswith("sgs_delayed_")
        )
        if is_trick and card_instance.color == "黑":
            return False
        return True

    def apply_action(
        self,
        action: LegalAction,
        context: ActionContext,
        state: GameState,
        skill_state: SkillRuntimeState,
    ) -> tuple[GameState, SkillRuntimeState, tuple[GameEvent, ...]]:
        raise InvalidActionError("【帷幕】为锁定静态修改技能，不接受主动 ACTIVATE_SKILL 动作")


class PojiangSkillHandler(SkillHandler):
    """【破降】CURRENT CONFIRMED: 交一张牌、摸三、移除绝、流失1体力。"""

    def __init__(self) -> None:
        self._definition = SkillDefinition(
            skill_id="sgs_skill_pojiang",
            skill_name="破降",
            version="1.0.0",
            kind=AuthoritativeSkillKind.ACTIVE,
            timing_windows=frozenset({SkillTimingWindow.PLAY_PHASE_ACTION}),
            max_uses_per_phase=1,
            description=(
                "出牌阶段限一次，你可以交给一名其他角色一张牌，然后你摸三张牌，"
                "移除所有“绝”并流失1点体力。你以此法获得的牌本回合不计入手牌上限。"
            ),
        )

    @property
    def definition(self) -> SkillDefinition:
        return self._definition

    def enumerate_active_actions(
        self,
        context: ActionContext,
        state: GameState,
        skill_state: SkillRuntimeState,
    ) -> tuple[LegalAction, ...]:
        owner_id = skill_state.owner_id
        if context.actor_id != owner_id:
            return ()
        owner = state.players_by_id.get(owner_id)
        if owner is None or not owner.alive:
            return ()
        material_ids = list(state.card_ids_in(ZoneRef.hand(owner_id)))
        for slot in ("weapon", "armor", "attack_horse", "defense_horse", "treasure"):
            material_ids.extend(state.card_ids_in(ZoneRef.equipment(owner_id, slot)))
        targets = [
            player.player_id
            for player in state.players
            if player.alive and player.player_id != owner_id
        ]
        if not material_ids or not targets:
            return ()
        actions: list[LegalAction] = []
        for card_id in sorted(material_ids):
            for target_id in sorted(targets):
                actions.append(
                    LegalAction(
                        action_type=ActionType.ACTIVATE_SKILL,
                        actor_id=owner_id,
                        card_instance_id=card_id,
                        target_ids=(target_id,),
                        skill_id="sgs_skill_pojiang",
                        payload={"material_card_instance_id": card_id},
                    )
                )
        return tuple(actions)

    def apply_in_production(
        self,
        session: object,
        action: LegalAction,
        context: ActionContext,
        state: GameState,
        skill_state: SkillRuntimeState,
    ) -> GameState:
        owner_id = skill_state.owner_id
        if action.actor_id != owner_id:
            raise InvalidActionError("【破降】发动者必须是技能所有者")
        if not action.target_ids or len(action.target_ids) != 1:
            raise InvalidActionError("【破降】必须且只能指定一名其他角色")
        target_id = action.target_ids[0]
        if target_id == owner_id:
            raise InvalidActionError("【破降】只能交给其他角色")
        target = state.players_by_id.get(target_id)
        if target is None or not target.alive:
            raise InvalidActionError("【破降】目标不存在或已死亡")
        card_id = action.card_instance_id
        if not card_id:
            raise InvalidActionError("【破降】必须指定一张实体牌")
        location = state.location_of(card_id)
        hand = ZoneRef.hand(owner_id)
        equipment_ok = (
            location.kind.value == "equipment" and location.owner_id == owner_id
        )
        if location != hand and not equipment_ok:
            raise InvalidActionError("【破降】材料必须是自己手牌区或装备区的一张牌")
        owner = state.players_by_id[owner_id]
        if owner.hp <= 1:
            raise UnsupportedRuleError(
                "V1 【破降】在流失1点体力后进入濒死时失败关闭"
            )
        next_state = session.transfer_card_for_skill(
            state,
            card_id,
            ZoneRef.hand(target_id),
            from_player_id=owner_id,
            to_player_id=target_id,
            reason="sgs_skill_pojiang",
            skill_owner=owner_id,
        )
        before_gained = {
            event.sequence
            for event in session.events
            if event.event_type is EventType.CARD_GAINED and event.sequence is not None
        }
        next_state = session.draw_cards_for_skill(
            next_state,
            owner_id,
            3,
            reason="sgs_skill_pojiang",
            skill_owner=owner_id,
        )
        drawn = tuple(
            event.card_instance_id
            for event in session.events
            if event.event_type is EventType.CARD_GAINED
            and event.sequence is not None
            and event.sequence not in before_gained
            and event.card_instance_id is not None
        )
        session.note_hand_limit_exempt_cards(drawn)
        next_state = session.lose_hp_for_skill(
            next_state,
            owner_id,
            1,
            reason="sgs_skill_pojiang",
        )
        return next_state


class JiliSkillHandler(SkillHandler):
    """【蒺藜】：当你于一回合内使用或打出第X张牌时，你可以摸X张牌（X为你的攻击范围）。"""

    def __init__(self) -> None:
        self._definition = SkillDefinition(
            skill_id="sgs_skill_jili",
            skill_name="蒺藜",
            version="1.0.0",
            kind=AuthoritativeSkillKind.TRIGGERED,
            timing_windows=frozenset(
                {
                    SkillTimingWindow.ON_CARD_USED,
                    SkillTimingWindow.ON_CARD_PLAYED,
                }
            ),
            is_mandatory=False,
            description="当你于一回合内使用或打出第X张牌时，你可以摸X张牌（X为你的攻击范围）。",
        )

    @property
    def definition(self) -> SkillDefinition:
        return self._definition

    def evaluate_trigger(
        self,
        context: SkillTriggerContext,
        state: GameState,
        skill_state: SkillRuntimeState,
    ) -> bool:
        owner_id = skill_state.owner_id
        event = context.event
        if event is None:
            return False
        if event.event_type not in (EventType.CARD_USED, EventType.CARD_PLAYED):
            return False
        if event.card_user != owner_id:
            return False
        turn_card_count = context.payload.get("turn_card_count")
        if turn_card_count is None or not isinstance(turn_card_count, int) or turn_card_count < 1:
            return False
        pre_attack_range = context.payload.get("pre_attack_range")
        if pre_attack_range is None or not isinstance(pre_attack_range, int) or pre_attack_range < 1:
            return False
        return turn_card_count == pre_attack_range

    def enumerate_trigger_actions(
        self,
        context: SkillTriggerContext,
        state: GameState,
        skill_state: SkillRuntimeState,
    ) -> tuple[LegalAction, ...]:
        owner_id = skill_state.owner_id
        seq = context.event.sequence if context.event else None
        draw_count = context.payload.get("pre_attack_range", 1)
        return (
            LegalAction(
                action_type=ActionType.ACTIVATE_SKILL,
                actor_id=owner_id,
                skill_id="sgs_skill_jili",
                payload={
                    "decision": "activate",
                    "draw_count": draw_count,
                    "trigger_event_sequence": seq,
                },
            ),
            LegalAction(
                action_type=ActionType.PASS,
                actor_id=owner_id,
                skill_id="sgs_skill_jili",
                payload={"decision": "pass", "trigger_event_sequence": seq},
            ),
        )

    def apply_action(
        self,
        action: LegalAction,
        context: ActionContext,
        state: GameState,
        skill_state: SkillRuntimeState,
    ) -> tuple[GameState, SkillRuntimeState, tuple[GameEvent, ...]]:
        owner_id = skill_state.owner_id
        if action.actor_id != owner_id:
            raise InvalidActionError(f"动作执行角色 {action.actor_id} 与技能所有者 {owner_id} 不一致")
        if action.payload.get("decision") == "pass" or action.action_type is ActionType.PASS:
            return state, skill_state, ()
        raise UnsupportedRuleError(
            "【蒺藜】组件 apply_action 不能执行生产摸牌；必须通过 ProductionBasicCardBatch.step"
        )

    def apply_in_production(
        self,
        session: object,
        action: LegalAction,
        context: ActionContext,
        state: GameState,
        skill_state: SkillRuntimeState,
    ) -> GameState:
        if action.payload.get("decision") == "pass" or action.action_type is ActionType.PASS:
            raise InvalidActionError("【蒺藜】放弃必须走 pass_skill 生产入口，不得进入效果结算")
        owner_id = skill_state.owner_id
        if action.actor_id != owner_id:
            raise InvalidActionError(f"动作执行角色 {action.actor_id} 与技能所有者 {owner_id} 不一致")
        draw_count = action.payload.get("draw_count")
        if draw_count is None or not isinstance(draw_count, int) or draw_count < 1:
            raise InvalidActionError("【蒺藜】摸牌数量必须为正整数")
        return session.draw_cards_for_skill(
            state,
            owner_id,
            draw_count,
            reason="sgs_skill_jili",
            skill_owner=owner_id,
        )


def create_proof_slice_v1_handlers() -> tuple[SkillHandler, ...]:
    """V1 production proof handlers: 破降 / 明哲 / 帷幕 / 蒺藜. Mutao is component-only."""
    return (
        PojiangSkillHandler(),
        MingzheSkillHandler(),
        WeimuSkillHandler(),
        JiliSkillHandler(),
    )


def create_proof_slice_v1_registry() -> AuthoritativeSkillRegistry:
    """Create and freeze an AuthoritativeSkillRegistry with V1 proof skills."""
    return create_skill_registry(create_proof_slice_v1_handlers())
