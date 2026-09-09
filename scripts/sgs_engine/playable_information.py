"""可信运行层的公共读条知识。仅提交成功后调用；视图读取没有探测能力。

观察口径是用户确认的项目规则，不代表官方统一客户端规则。
内部实体仅用于识别同一响应层及手牌变化，公开摘要不含实体、数量或 seed。
"""
from __future__ import annotations

import copy

from ..sgs_team_strategy import NullificationKnowledgeState
from .playable_config import INFORMATION_VERSION
from .model import ZoneRef
from .production_cards import WuxiekejiAdapter


RESPONSE_PHASES = {"trick_response", "judgment_wuxie"}


def public_gain_sequences(events):
    """公开区域→手牌的实际移动；不根据取得牌的私有牌名决定可见性。"""
    public_moves = set()
    sequences = set()
    for event in events:
        if event.event_type.value == "card_moved":
            source = event.payload.get("source", {})
            destination = event.payload.get("destination", {})
            if (source.get("kind") in {"equipment", "judgment", "discard_pile", "revealed", "processing"}
                    and destination.get("kind") == "hand"):
                public_moves.add(event.card_instance_id)
            else:
                public_moves.discard(event.card_instance_id)
        if event.event_type.value == "card_gained" and event.card_instance_id in public_moves:
            sequences.add(event.sequence)
    return sequences


class PublicInformation:
    def __init__(self, player_ids):
        self.player_ids = tuple(player_ids)
        self.nullification = NullificationKnowledgeState(self.player_ids)
        self.window = None
        self._signature = None
        self._root = None
        self._window_count = 0
        self._hands = {}
        self._alive = set(self.player_ids)
        # 仅由公开展示且仍留在手中的实体建立共同知识；不暴露实体编号。
        self._revealed_hands = {pid: {} for pid in self.player_ids}
        self.hand_epochs = {pid: 0 for pid in self.player_ids}

    def view(self):
        rows = {pid: {"availability": k.availability.value,
                      "source": k.knowledge_source, "time": k.knowledge_time,
                      "window_id": k.window_id}
                for pid, k in self.nullification.snapshot().items()}
        return {"players": rows, "window": copy.deepcopy(self.window),
                "all_none": bool(self._alive) and all(
                    rows[pid]["availability"] == "known_none" for pid in self._alive),
                "has_unknown": any(rows[pid]["availability"] == "unknown" for pid in self._alive)}

    def public_hand_keys(self):
        return {pid: sorted(set(cards.values())) for pid, cards in self._revealed_hands.items()}

    def after_commit(self, game, events, generation, action=None):
        """消费真实提交的事件，再观察提交后实际挂起的响应层。

        生产 step 在窗口/技能选择处返回；卡牌使用检查点未完成时不观察。
        窗口直接抽象客户端最终依法可判断的结果，不模拟显示/消失动画。
        PASS 会推进逐座位 decision id，但不推导、重新扫描或抹除资格。
        无懈自身的 direct_response_to 改变才建立新的反无懈观察层。
        """
        core = game.core
        if core is None:
            return []
        emitted = []
        stamp = f"decision:{generation}"
        def publish(kind, **payload):
            emitted.append({"type": kind, "time": stamp, **payload})

        before = self._hands
        after = {pid: frozenset(game.state.card_ids_in(ZoneRef.hand(pid))) for pid in self.player_ids}
        public_losses = {pid: set() for pid in self.player_ids}
        public_gains = {pid: set() for pid in self.player_ids}
        public_sequences = public_gain_sequences(events)
        gained = set()
        for event in events:
            kind = event.event_type.value
            pid = event.card_user
            cid = event.card_instance_id
            if kind in {"card_used", "card_played", "card_discarded", "card_recast", "equipment_equipped"}:
                for owner in self.player_ids:
                    if cid in before.get(owner, ()):
                        public_losses[owner].add(cid)
            if kind == "card_gained":
                for owner in event.target_ids:
                    if owner in self.player_ids:
                        if event.sequence in public_sequences:
                            public_gains[owner].add(cid)
                        else:
                            gained.add(owner)
            if kind == "card_used" and event.card_key == "sgs_trick_wuxiekeji" and pid in self.player_ids:
                self.nullification.record_nullification_used(pid, knowledge_time=stamp)
                if self.window:
                    self.window["used_by"].append(pid)
                publish("nullification_used", actor=pid,
                        window_id=self.window["id"] if self.window else None,
                        remaining="unknown")
        if action and action[1] in {"pass_trick_response", "pass_judgment_wuxie"} and self.window:
            pid = action[0]
            if pid not in self.window["passed"]:
                self.window["passed"].append(pid)
            publish("nullification_passed", actor=pid, window_id=self.window["id"],
                    observed_availability=self.nullification.knowledge_for(pid).availability.value,
                    consumed=False)
        for pid in self.player_ids:
            old = before.get(pid, frozenset())
            changed = old != after[pid] or pid in gained or bool(public_gains[pid])
            if changed:
                self.hand_epochs[pid] += 1
            unknown_loss = bool((old - after[pid]) - public_losses[pid])
            unknown = pid in gained or bool((after[pid] - old) - public_gains[pid]) or unknown_loss
            if unknown:
                self.nullification.record_unknown_hand_change(pid, knowledge_time=stamp)
                publish("nullification_knowledge_invalidated", actor=pid, reason="hand_change")
            if unknown_loss:
                # 未知失牌时不能用后台实体识别维持“展示牌还在”的知识。
                self._revealed_hands[pid].clear()
            else:
                self._revealed_hands[pid] = {cid: key for cid, key in self._revealed_hands[pid].items()
                                             if cid in after[pid]}
                for cid in sorted(public_gains[pid] & after[pid]):
                    key = game.state.cards_by_id[cid].card_key
                    self._revealed_hands[pid][cid] = key
                    if not unknown and key == "sgs_trick_wuxiekeji":
                        self.nullification.record_public_nullification_gained(pid, knowledge_time=stamp)
                        publish("nullification_public_gain", actor=pid, availability="known_usable")
        for event in events:
            if event.event_type.value == "card_revealed" and event.card_instance_id:
                for pid in self.player_ids:
                    if event.card_instance_id in after[pid]:
                        self._revealed_hands[pid][event.card_instance_id] = event.card_key
        alive = {p.player_id for p in game.state.players if p.alive}
        for pid in sorted(self._alive - alive):
            self.nullification.record_player_removed(pid, knowledge_time=stamp)
            self._revealed_hands[pid].clear()
            publish("nullification_player_removed", actor=pid)
        self._hands, self._alive = after, alive

        runtime = core.runtime
        trick = runtime.pending_trick
        response = core.phase.value in RESPONSE_PHASES and trick is not None
        if not response:
            if self.window and self.window["active"]:
                self.window["active"] = False
                publish("nullification_window_closed", window_id=self.window["id"])
            return emitted
        if core.skill_pending is not None:
            return emitted
        # 与正式当前响应动作相接；模式或技能挂起期间不凭 phase 提前观察。
        operations = {a.payload.get("operation") for a in core.legal_actions()}
        if not operations.intersection({"use_wuxie", "pass_trick_response", "pass_judgment_wuxie"}):
            return emitted
        root = (trick.trick_instance_id, trick.target_id, runtime.response_window_source_sequence)
        signature = (*root, runtime.trick_direct_response_to)
        if signature != self._signature:
            layer = self.window["layer"] + 1 if self.window and root == self._root else 0
            self._signature, self._root = signature, root
            self._window_count += 1
            wid = f"nullification:{self._window_count}"
            adapter = WuxiekejiAdapter(core)
            usable = [pid for pid in self.player_ids if adapter.usable_card_ids(game.state, pid)]
            self.nullification.refresh_response_window(usable, window_id=wid, knowledge_time=stamp)
            self.window = {"id": wid, "layer": layer, "target": trick.target_id,
                           "source": trick.user_id, "card_key": trick.trick_key,
                           "effect_active": runtime.trick_effect_active, "active": True,
                           "passed": [], "used_by": []}
            publish("nullification_observation", window=copy.deepcopy(self.window),
                    players={pid: self.nullification.knowledge_for(pid).availability.value for pid in self.player_ids})
        return emitted
