"""可玩模式的生产装配与开局规则适配器。没有近似战斗逻辑。"""

from __future__ import annotations

from dataclasses import replace
import secrets

from ..sgs_modes import build_landlord_bidding_order, resolve_landlord_bidding_with_seats
from .actions import (ActionContext, ActionType, InvalidActionError, LegalAction,
                      RuleAdapter, RuleRegistry, apply_action, enumerate_legal_actions)
from .events import EventType, GameEvent
from .generals import create_authoritative_general_batch_v1_registry
from .mode_2v2 import Formal2v2Configuration, TwoVsTwoModePolicy, TwoVsTwoOutcomePolicy
from .mode_doudizhu import (FormalDoudizhuConfiguration, DoudizhuModePolicy,
                           DoudizhuOutcomePolicy)
from .mode_identity import (FormalIdentityConfiguration, FormalEightPlayerIdentityConfiguration,
                            IdentityModePolicy, IdentityOutcomePolicy, StandardIdentityRole)
from .mode_identity_heir import (FormalHeirAndSpyChoiceIdentityConfiguration,
    HeirAndSpyChoiceModePolicy, HeirAndSpyChoiceOutcomePolicy, HeirAndSpyChoiceVariantState)
from .model import (DRAW_PILE, GameState, PlayerState, ZoneRef,
                    CharacterMetadata, CharacterGender)
from .multiplayer import DuelOutcomePolicy
from .playable_config import GameConfig, SOLDIER, derive_seed
from .production_batch import BatchActionIdController, ProductionBasicCardBatch
from .rng import DeterministicRNG
from .skill_impl_v1 import create_proof_slice_v1_registry


class PlayableProductionSession(ProductionBasicCardBatch):
    """新开发身份；旧 formal / Bridge / C8 factory 和门禁保持原范围。"""

    MODE_ID = "post_c8_playable_production_v1"


def assemble_production_game(config: GameConfig, selected: dict[str, str],
                             roles: dict[str, str]) -> PlayableProductionSession:
    physical = config.player_ids
    first = next((pid for pid in physical if roles.get(pid) in ("lord", "landlord")), physical[0])
    index = physical.index(first)
    order = physical[index:] + physical[:index]
    registry = create_authoritative_general_batch_v1_registry()
    definitions = {pid: registry.get_general(key) for pid, key in selected.items() if key != SOLDIER}
    hp = tuple(definitions[pid].starting_hp if pid in definitions else 4 for pid in order)
    max_hp = tuple(definitions[pid].max_hp if pid in definitions else 4 for pid in order)
    policy = None
    bonuses = {first: 1} if config.mode == "doudizhu" or config.mode.startswith("identity") else {}
    hand_counts = (4,) * len(order)
    if config.mode == "2v2":
        cfg = Formal2v2Configuration(player_ids=order, base_hp=hp, base_max_hp=max_hp)
        policy = TwoVsTwoModePolicy(cfg)
        outcome = TwoVsTwoOutcomePolicy(cfg.teams_by_player())
        hand_counts = cfg.initial_hand_counts
    elif config.mode == "doudizhu":
        cfg = FormalDoudizhuConfiguration(player_ids=order, first_player_id=first)
        policy = DoudizhuModePolicy(cfg)
        outcome = DoudizhuOutcomePolicy(cfg.camps_by_player())
    elif config.mode == "identity8_heir":
        cfg = FormalHeirAndSpyChoiceIdentityConfiguration.formal_profile()
        variant = HeirAndSpyChoiceVariantState(
            original_lord_player_id=first, current_lord_player_id=first,
            role_original=dict(roles), role_current=dict(roles),
            players_had_normal_turn_this_round=(first,), normal_turn_cycle=1)
        policy = HeirAndSpyChoiceModePolicy(cfg, order, first, variant)
        outcome = HeirAndSpyChoiceOutcomePolicy(roles, first)
    elif config.mode.startswith("identity"):
        cfg = (FormalEightPlayerIdentityConfiguration.formal_profile() if len(order) == 8
               else FormalIdentityConfiguration.formal_profile())
        identities = {pid: StandardIdentityRole(role) for pid, role in roles.items()}
        policy = IdentityModePolicy(cfg, identities, order, first)
        outcome = IdentityOutcomePolicy(identities)
    else:
        outcome = DuelOutcomePolicy()
        # 单挑先手随机；物理座位不旋转。
        first = None
    general_assignments = {pid: key for pid, key in selected.items() if key != SOLDIER}
    core = PlayableProductionSession(
        seed=derive_seed(config.seed, "production-deck-and-effects-v1"),
        player_hp=hp, player_max_hp=max_hp, player_ids=order,
        initial_hp_bonuses=bonuses, outcome_policy=outcome,
        initial_hand_counts=hand_counts, first_player_id=first, mode_policy=policy,
        general_registry=registry if general_assignments else None,
        general_assignments=general_assignments or None,
        skill_registry=create_proof_slice_v1_registry() if general_assignments else None)
    # 士兵是明确的测试角色，不把未实现武将降级成士兵。
    soldier = CharacterMetadata(SOLDIER, CharacterGender.NONE, CharacterGender.NONE)
    core._state = replace(core.state, players=tuple(
        replace(p, character=soldier) if selected[p.player_id] == SOLDIER else p
        for p in core.state.players))
    if config.mode == "identity8_heir":
        policy.bind_session(core)
    if config.mode.startswith("identity"):
        core._events.extend((GameEvent(event_type=EventType.IDENTITY_REVEALED,
            target_ids=(order[0],), payload={"reason": "initial_lord_reveal", "identity": "lord"}),))
    return core


class _OpeningAdapter(RuleAdapter):
    adapter_version = "post-c8-opening-v1"

    def __init__(self, driver: "PlayableGame") -> None:
        self.driver = driver

    def audit_state(self) -> dict:
        d = self.driver
        return {"domain": d._signing_domain, "stage": d.stage,
                "config": d.config.to_dict(), "roles": d.roles,
                "selected": d.selected, "candidates": d.candidates,
                "selection_order": d.selection_order, "selection_index": d.selection_index,
                "bidding_order": d.bidding_order, "bids": d.bids,
                "mulligan_index": d.mulligan_index, "rerolls": d.rerolls,
                "generation": d.opening_generation}

    def enumerate_legal_actions(self, state: GameState, context: ActionContext):
        d = self.driver
        actor = context.actor_id
        if actor != d.actor:
            return ()
        values = []
        if d.stage == "bidding":
            bids = [1] if not d.bids else [None] + list(range(max(x or 0 for x in d.bids) + 1, 4))
            values = [{"operation": "opening_bid", "bid": bid} for bid in bids]
        elif d.stage == "selection":
            values = [{"operation": "opening_choose_general", "general": key}
                      for key in d.candidates[actor]]
        elif d.stage == "mulligan":
            values = [{"operation": "opening_keep_hand"}]
            if d.rerolls[actor] < d.config.mulligan_limit:
                values.append({"operation": "opening_reroll_hand"})
        else:
            raise InvalidActionError(f"非法开局阶段{d.stage}")
        return tuple(LegalAction(action_type=ActionType.CHOOSE_OPTION, actor_id=actor,
                                 payload=value) for value in values)

    def apply_action(self, state: GameState, context: ActionContext,
                     action: LegalAction) -> GameState:
        return self.driver._apply_opening(state, action)


class PlayableGame:
    """可信生产边界；控制器仅由 runtime 获得过滤后的普通字典。"""

    def __init__(self, config: GameConfig) -> None:
        self.config = config
        self.core: PlayableProductionSession | None = None
        self._signing_domain = secrets.token_hex(32)
        self._state = GameState(cards=(), players=tuple(PlayerState(pid, i + 1, 4, 4)
            for i, pid in enumerate(config.player_ids)), card_locations={}, deck_id="opening")
        setup_rng = DeterministicRNG(derive_seed(config.seed, "opening-v1"))
        self.roles: dict[str, str] = {}
        if config.mode.startswith("identity"):
            roles = list(config.identities or (
                ["lord"] + ["loyalist"] * (2 if len(config.player_ids) == 8 else 1)
                + ["rebel"] * (4 if len(config.player_ids) == 8 else 2) + ["spy"]))
            if not config.identities:
                setup_rng.shuffle(roles)
            self.roles = dict(zip(config.player_ids, roles))
        elif config.mode == "doudizhu" and config.landlord_seat is not None:
            self.roles = {pid: "landlord" if pid == f"p{config.landlord_seat}" else "peasants"
                          for pid in config.player_ids}
        elif config.mode == "2v2":
            self.roles = dict(zip(config.player_ids, ("team_a", "team_b", "team_b", "team_a")))
        self.bidding_order = (build_landlord_bidding_order(config.player_ids,
            setup_rng.choice(config.player_ids)) if config.mode == "doudizhu" else ())
        self.bids: list[int | None] = []
        self.selected = dict(zip(config.player_ids, config.fixed_generals or tuple(
            config.enabled_generals[i % len(config.enabled_generals)] for i in range(len(config.player_ids))))) if config.selection == "fixed" else {}
        self.candidates = {pid: tuple(setup_rng.sample(config.enabled_generals, config.candidate_count))
                           for pid in config.player_ids} if config.selection == "candidates" else {}
        self.selection_order = config.player_ids
        self.selection_index = 0
        self.mulligan_index = 0
        self.rerolls = dict.fromkeys(config.player_ids, 0)
        self.opening_generation = 0
        self.opening_events: list[dict] = []
        self.stage = "bidding" if config.mode == "doudizhu" and not self.roles else "selection"
        self.registry = RuleRegistry()
        self.registry.register("post_c8_opening_v1", "opening", _OpeningAdapter(self))
        if self.stage != "bidding":
            self._after_roles()

    def _after_roles(self) -> None:
        if self.selected:
            self._start_production()
        else:
            first = next((pid for pid, role in self.roles.items() if role == "lord"), None)
            self.selection_order = ((first,) + tuple(pid for pid in self.config.player_ids if pid != first)
                                    if first else self.config.player_ids)
            self.stage = "selection"

    def _start_production(self) -> None:
        self.core = assemble_production_game(self.config, self.selected, self.roles)
        self.stage = "mulligan" if self.config.mulligan_limit else "playing"

    @property
    def state(self) -> GameState:
        return self.core.state if self.core else self._state

    @property
    def is_finished(self) -> bool:
        return self.core is not None and self.core.is_finished

    @property
    def actor(self) -> str:
        if self.stage == "bidding":
            return self.bidding_order[len(self.bids)]
        if self.stage == "selection":
            return self.selection_order[self.selection_index]
        if self.stage == "mulligan":
            return self.config.player_ids[self.mulligan_index]
        if self.core is None:
            raise RuntimeError("生产核心尚未初始化")
        return self.core.current_actor_id

    def context(self) -> ActionContext:
        if self.stage == "playing":
            return self.core._context()
        return ActionContext(mode="post_c8_opening_v1", phase="opening", actor_id=self.actor,
            expected_revision=self.state.revision, metadata={"generation": self.opening_generation})

    def legal_actions(self) -> tuple[LegalAction, ...]:
        if self.is_finished:
            return ()
        return (self.core.legal_actions() if self.stage == "playing" else
                enumerate_legal_actions(self.state, self.context(), self.registry))

    def step(self, action_id: str) -> LegalAction:
        if self.stage == "playing":
            return self.core.step(BatchActionIdController(action_id))
        legal = self.legal_actions()
        chosen = next((a for a in legal if a.action_id == action_id), None)
        if chosen is None:
            raise InvalidActionError("开局动作已过期或签名无效")
        # 开局同样具备失败回滚：不能留下半个叫价／选将／重摸提交。
        saved = (self.stage, dict(self.selected), dict(self.roles), list(self.bids),
                 self.selection_order, self.selection_index, self.mulligan_index,
                 dict(self.rerolls), self.opening_generation, list(self.opening_events), self.core)
        transaction = self.core._snapshot_authoritative_mutation_state() if self.core else None
        try:
            updated = apply_action(self.state, self.context(), chosen, self.registry)
            if self.core:
                self.core._state = updated
            else:
                self._state = updated
            return chosen
        except Exception:
            (self.stage, self.selected, self.roles, self.bids, self.selection_order,
             self.selection_index, self.mulligan_index, self.rerolls,
             self.opening_generation, self.opening_events, self.core) = saved
            if transaction is not None:
                self.core._restore_authoritative_mutation_state(transaction)
            raise

    def _apply_opening(self, state: GameState, action: LegalAction) -> GameState:
        op = action.payload["operation"]
        actor = action.actor_id
        if op == "opening_bid":
            bid = action.payload["bid"]
            self.bids.append(bid)
            self.opening_events.append({"type": "bid", "actor": actor, "bid": bid})
            if bid == 3 or len(self.bids) == 3:
                result = resolve_landlord_bidding_with_seats(
                    self.config.player_ids, self.bidding_order[0], self.bids)
                landlord = self.bidding_order[result.bid_result.landlord_call_position - 1]
                self.roles = {pid: "landlord" if pid == landlord else "peasants" for pid in self.config.player_ids}
                self._after_roles()
        elif op == "opening_choose_general":
            self.selected[actor] = action.payload["general"]
            # 选将事件只保存私有范围；最终公开阵容由当前视图提供。
            self.opening_events.append({"type": "general_selected", "actor": actor,
                                        "general": action.payload["general"]})
            self.selection_index += 1
            if self.selection_index == len(self.selection_order):
                self._start_production()
        elif op == "opening_keep_hand":
            self.mulligan_index += 1
            if self.mulligan_index == len(self.config.player_ids):
                self.stage = "playing"
        elif op == "opening_reroll_hand":
            hand = state.card_ids_in(ZoneRef.hand(actor))
            returned = state.move_cards({cid: DRAW_PILE for cid in hand})
            deck = list(returned.card_ids_in(DRAW_PILE))
            self.core._rng.shuffle(deck)
            orders = dict(returned.zone_order)
            orders[DRAW_PILE] = tuple(deck)
            returned = replace(returned, zone_order=orders, revision=returned.revision + 1)
            drawn = tuple(deck[:len(hand)])
            state = returned.move_cards({cid: ZoneRef.hand(actor) for cid in drawn})
            self.rerolls[actor] += 1
            # pre-game：不进入游戏中的失牌 ledger 或技能触发 checkpoint。
            self.core._events.extend(GameEvent(event_type=EventType.CARD_GAINED,
                target_ids=(actor,), card_instance_id=cid,
                card_key=state.cards_by_id[cid].card_key,
                payload={"reason": "opening_mulligan"}) for cid in drawn)
        else:
            raise InvalidActionError(f"未知开局动作{op}")
        self.opening_generation += 1
        if self.core and op in ("opening_bid", "opening_choose_general"):
            return self.core.state
        return replace(state, revision=state.revision + 1)

    def current_roles(self) -> dict[str, str]:
        if self.core and self.config.mode.startswith("identity"):
            return self.core.mode_policy.identities_as_str()
        return dict(self.roles)

    def result(self) -> dict:
        if not self.is_finished:
            return {"status": "IN_PROGRESS"}
        winner = self.core.winner_id
        roles = self.current_roles()
        if winner is None:
            winning = []
        elif winner == "lord_and_loyalists":
            winning = [pid for pid, role in roles.items() if role in ("lord", "loyalist")]
        elif winner == "rebels":
            winning = [pid for pid, role in roles.items() if role == "rebel"]
        elif winner in ("spy", "ambitionist"):
            winning = [p.player_id for p in self.state.players if p.alive and roles.get(p.player_id) == winner]
        elif winner in self.config.player_ids:
            winning = [winner]
        else:
            winning = [pid for pid, role in roles.items() if role == winner]
        return {"status": "DRAW" if winner is None else "WIN", "winner": winner,
                "winning_players": winning, "reason": self.core.runtime.game_over_reason,
                "steps": self.core.step_count, "turns": self.core.runtime.turn_number}
