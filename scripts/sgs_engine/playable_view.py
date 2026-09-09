"""可信单向投影：正常玩家与 AI 只接收本模块创建的白名单数据。"""

from __future__ import annotations

import hashlib
import hmac
from typing import Callable

from .actions import LegalAction, UnsupportedRuleError
from .model import (DISCARD_PILE, DRAW_PILE, EQUIPMENT_SLOTS, PROCESSING_ZONE,
                    REVEALED_ZONE, ZoneKind, ZoneRef)
from .playable_config import canonical, general_catalog
from .playable_information import public_gain_sequences
from .playable_game import PlayableGame
from .production_cards import attack_range_of, actual_distance, weapon_attack_ranges


OPERATION_LABELS = {
    "proceed_prepare": "结算准备阶段", "proceed_judgment": "结算判定阶段",
    "proceed_draw": "摸牌", "end_play_phase": "结束出牌", "end_turn": "结算结束阶段并结束回合",
    "use_slash": "使用杀", "heal_self": "使用桃回复", "use_wine_buff": "使用酒强化下一张杀",
    "use_wuzhong": "使用无中生有", "use_guohe": "使用过河拆桥", "use_shunshou": "使用顺手牵羊",
    "use_duel": "使用决斗", "use_fire_attack": "使用火攻", "use_nanman": "使用南蛮入侵",
    "use_wanjian": "使用万箭齐发", "use_taoyuan": "使用桃园结义", "use_wugu": "使用五谷丰登",
    "use_tiesuo": "使用铁索连环", "recast_tiesuo": "重铸铁索连环", "use_jiedao": "使用借刀杀人",
    "use_lebusi": "使用乐不思蜀", "use_bingliang": "使用兵粮寸断", "use_shandian": "使用闪电",
    "use_weapon": "装备武器", "use_armor": "装备防具", "use_mount": "装备坐骑",
    "use_wuxie": "使用无懈可击", "play_dodge": "使用闪", "play_slash_for_duel": "决斗打出杀",
    "play_slash_for_nanman": "南蛮打出杀", "play_jink_for_wanjian": "万箭使用闪",
    "activate_bagua": "发动八卦阵", "activate_cixiong": "发动雌雄双股剑",
    "pass_cixiong": "不发动雌雄双股剑", "cixiong_allow_draw": "允许对方摸牌",
    "cixiong_discard_card": "雌雄双股剑弃牌", "weapon_discard_mount": "麒麟弓弃置坐骑",
    "weapon_force_hit": "发动贯石斧（随后选择两张代价牌）",
    "weapon_prevent_damage": "发动寒冰剑（防止伤害，随后逐张弃牌）",
    "qinglong_use_slash": "青龙偃月刀继续出杀", "hanbing_discard_card": "寒冰剑弃置目标牌",
    "select_discard_two": "选择两张代价牌之一", "unselect_discard_two": "取消选择代价牌",
    "discard_two_submit": "确认支付两张代价牌", "select_discard_card": "选择待弃手牌",
    "unselect_discard_card": "取消待弃手牌", "discard_phase_submit": "确认整批弃牌",
    "choose_target_zone_card": "选择目标区域牌", "reveal_card_for_fire_attack": "选择火攻展示牌",
    "discard_same_suit_for_fire_attack": "弃同花色牌造成火焰伤害",
    "choose_borrowed_sword_slash": "响应借刀使用杀", "refuse_borrowed_sword_slash": "拒绝出杀并交出武器",
    "pick_wugu_card": "选择五谷公开牌", "rescue_with_peach": "使用桃救援",
    "rescue_with_wine": "使用酒自救", "feiyang_activate": "发动飞扬", "feiyang_decline": "不发动飞扬",
    "peasant_reward_recover_hp": "农民奖励：回复1点体力", "peasant_reward_draw_two": "农民奖励：摸2张",
    "peasant_reward_decline": "放弃农民奖励", "activate_skill": "发动技能", "pass_skill": "不发动技能",
    "qianchong_choice": "谦冲选择牌类", "private_card_selection_submit": "罪论选择获得牌并保留其余牌顶顺序",
    "skill_lose_hp_target_choice": "罪论选择共同失去体力的角色", "select_heir": "秘密立储",
    "choose_spy_path": "秘密选择内奸择途", "pass_mode_decision": "暂不作模式选择",
    "succession_obtain_card": "继位时取得原主公一张牌", "succession_obtain_none": "继位时不取牌",
    "ambitionist_mark_draw_two": "移去野心家标记摸2张", "ambitionist_reward_draw_three": "野心家奖励摸3张",
    "ambitionist_reward_decline": "放弃野心家奖励", "opening_bid": "叫地主",
    "opening_choose_general": "选择武将", "opening_keep_hand": "保留整手牌", "opening_reroll_hand": "整手回库重摸",
}
for _op in ("pass_judgment_wuxie", "pass_slash_response", "pass_trick_response", "pass_duel_slash",
            "pass_fire_attack_discard", "pass_nanman_slash", "pass_wanjian_jink", "pass_rescue", "pass_weapon_choice"):
    OPERATION_LABELS[_op] = "放弃本次响应／发动"


def visible_hand_owners(game: PlayableGame, viewer: str) -> set[str]:
    if game.config.mode == "2v2":
        return {pid for pid, team in game.roles.items() if team == game.roles[viewer]}
    return {viewer}


class ViewProjector:
    def __init__(self, game: PlayableGame, secret: bytes) -> None:
        self.game = game
        self._secret = secret

    def card(self, cid: str | None, viewer: str) -> dict | None:
        card = self.game.state.cards_by_id.get(cid)
        if card is None:
            return None
        ref = hmac.new(self._secret, canonical(["card", viewer, cid]).encode(), hashlib.sha256).hexdigest()
        return {"ref": ref, "key": card.card_key, "name": card.card_name,
                "suit": card.suit, "color": card.color, "rank": card.rank,
                "category": card.card_type, "slot": card.equipment_slot,
                "attack_range": weapon_attack_ranges().get(card.card_key)}

    def visible_cards(self, viewer: str) -> set[str]:
        game = self.game
        visible = set()
        owners = visible_hand_owners(game, viewer)
        for cid, zone in game.state.card_locations.items():
            if zone.kind in (ZoneKind.EQUIPMENT, ZoneKind.JUDGMENT, ZoneKind.DISCARD_PILE,
                             ZoneKind.PROCESSING, ZoneKind.REVEALED) or (
                    zone.kind is ZoneKind.HAND and zone.owner_id in owners):
                visible.add(cid)
        if game.core:
            pending = game.core._pending_private_card_selection
            if pending and pending.actor_id == viewer:
                visible.update(pending.observed_ids)
        return visible

    @staticmethod
    def _lookup_handle(handle, mappings) -> str | None:
        if not isinstance(handle, str):
            return None
        for mapping in mappings:
            value = mapping.get(handle)
            if isinstance(value, str):
                return value
        return None

    def action(self, action: LegalAction, viewer: str, ordinal: int, token: str) -> dict:
        if action.actor_id != viewer:
            raise ValueError("只能向当前行动者投影其合法候选")
        op = action.payload.get("operation")
        if op not in OPERATION_LABELS:
            raise UnsupportedRuleError(f"未识别生产动作schema：operation={op!r}，actor={viewer}")
        game = self.game
        visible = self.visible_cards(viewer)
        payload = action.payload
        cid = action.card_instance_id
        if cid is None and game.core:
            r = game.core.runtime
            mappings = [r.zone_choice_handles, r.fire_attack_reveal_handles,
                        r.group_response_handles, r.borrowed_sword_slash_handles,
                        r.discard_phase_handles]
            for field in ("pending_cixiong_choice", "pending_slash_choice", "pending_hanbing_discard",
                          "pending_succession", "pending_duel"):
                pending = getattr(r, field)
                mappings.append(getattr(pending, "handles", {}))
            cid = self._lookup_handle(payload.get("handle"), mappings)
        card = self.card(cid, viewer) if cid in visible else None
        materials = list(action.virtual_card.material_card_instance_ids) if action.virtual_card else []
        if op in ("activate_skill", "pass_skill"):
            # 虚拟牌描述已使用的触发源；其材料已经支付，不是发动/放弃技能的额外费用。
            materials = []
        if op == "feiyang_activate":
            materials = list(payload["hand_ids"])
        # 原始 payload 从不穿透：只逐字段取规则明确允许的信息。
        option = payload.get("chosen_card_type", payload.get("path", payload.get("general")))
        if op == "opening_bid":
            option = payload["bid"]
        selected = [self.card(c, viewer) for c in payload.get("selected_card_ids", ()) if c in visible]
        remaining = [self.card(c, viewer) for c in payload.get("remaining_top_order", ()) if c in visible]
        target_ids = list(action.target_ids)
        if op == "use_jiedao":
            target_ids.append(payload["second_target_id"])
        if op == "choose_borrowed_sword_slash":
            target_ids = [payload["second_target_id"]]
        virtual_key = action.virtual_card.card_key if action.virtual_card else None
        parts = [OPERATION_LABELS[op]]
        if action.skill_id:
            parts.append(action.skill_id.removeprefix("sgs_skill_"))
        if card:
            parts.append(f"{card['name']} {card['suit']}{card['rank']}")
        elif cid is not None and not action.virtual_card:
            parts.append("未知牌面")
        if virtual_key:
            parts.append(f"虚拟牌 {virtual_key}")
        if option is not None:
            names = {item["general_key"]: item["name"] for item in general_catalog()}
            parts.append(names.get(option, {"basic": "基本牌", "trick": "锦囊牌", "equipment": "装备牌"}.get(option, str(option))))
        if target_ids:
            parts.append("目标 " + ",".join(target_ids))
        if materials:
            parts.append("代价 " + ",".join(self.card(c, viewer)["name"] for c in materials if c in visible))
        if selected:
            parts.append("获得 " + ",".join(c["name"] + c["suit"] + c["rank"] for c in selected))
        if remaining:
            parts.append("余牌由顶至底 " + " → ".join(c["name"] + c["suit"] + c["rank"] for c in remaining))
        if payload.get("converted_to_fire"):
            parts.append("转为火杀")
        return {"schema": "production-action-option-v1", "action_id": token, "ordinal": ordinal,
                "operation": op, "type": action.action_type.value, "targets": target_ids,
                "skill": action.skill_id, "card": card,
                "cost_cards": [self.card(c, viewer) for c in materials if c in visible],
                "selected_cards": selected, "remaining_cards": remaining,
                "option": option, "zone": payload.get("zone"),
                "virtual_key": virtual_key, "converted_to_fire": payload.get("converted_to_fire") is True,
                "description": "；".join(parts)}

    def pending(self, viewer: str) -> dict:
        core = self.game.core
        if core is None or core.is_finished:
            return {}
        r = core.runtime
        result = {"dying": r.pending_dying_id, "trick_active": r.trick_effect_active}
        trick = r.pending_trick
        if trick:
            result.update(source=trick.user_id, target=trick.target_id, card_key=trick.trick_key)
        slash = r.pending_slash
        if slash:
            result.update(source=slash.attacker_id, target=slash.target_id,
                          damage=2 if slash.boosted else 1,
                          card_key="sgs_basic_huosha" if slash.fire_converted else
                          (core.state.cards_by_id[slash.slash_instance_id].card_key
                           if slash.slash_instance_id in core.state.cards_by_id else "sgs_basic_sha"))
        if r.pending_duel and core.phase.value == "duel_response":
            result.update(source=r.pending_duel.opponent_id, target=r.pending_duel.responder_id,
                          card_key="sgs_trick_juedou", damage=1)
        if r.pending_group_trick and core.phase.value in ("nanman_response", "wanjian_response"):
            result.update(source=r.pending_group_trick.user_id, target=core.current_actor_id,
                          card_key=r.pending_group_trick.trick_key, damage=1)
        if r.pending_fire_attack:
            p = r.pending_fire_attack
            result.update(source=p.user_id, target=p.target_id, card_key="sgs_trick_huogong",
                          revealed_suit=p.revealed_suit, damage=1)
        if r.pending_borrowed_sword:
            p = r.pending_borrowed_sword
            result.update(borrowed_sword_holder=p.first_target_id, borrowed_sword_target=p.second_target_id)
            if r.pending_trick is None:
                result.update(source=p.user_id, target=p.second_target_id)
        if r.pending_judgment and core.phase.value == "judgment_wuxie":
            p = r.pending_judgment
            result.update(target=p.target_id, card_key=p.trick_key)
        if core.current_actor_id == viewer:
            result["selected_discard"] = [self.card(cid, viewer) for cid in r.discard_phase_selected_ids]
            private = core._pending_private_card_selection
            if private and private.actor_id == viewer:
                result["observed_cards"] = [self.card(cid, viewer) for cid in private.observed_ids]
            pending_skill = core.skill_pending
            if pending_skill:
                result["skill"] = pending_skill.skill_id
                result["skill_facts"] = {key: value for key, value in pending_skill.payload.items()
                    if key in ("n", "draw_count", "dealt_damage_this_turn", "no_discard_this_turn",
                               "has_minimum_hand_count", "owner_hand_count", "minimum_alive_hand_count")
                    and type(value) in (int, bool)}
        return result

    def view(self, viewer: str) -> dict:
        game = self.game
        owners = visible_hand_owners(game, viewer)
        roles = game.current_roles()
        players = []
        for p in game.state.players:
            pid = p.player_id
            role = roles.get(pid)
            role_visible = (not game.config.mode.startswith("identity") or pid == viewer
                            or not p.alive or role in ("lord", "ambitionist"))
            general_visible = (game.core is not None or pid == viewer or
                               game.config.mode == "2v2" and pid in owners or role == "lord")
            info = {"id": pid, "physical_seat": int(pid[1:]), "seat": p.seat,
                    "hp": p.hp, "max_hp": p.max_hp, "alive": p.alive, "chained": p.chained,
                    "role": role if role_visible else None,
                    "general": game.selected.get(pid) if general_visible else None,
                    "hand_count": len(game.state.card_ids_in(ZoneRef.hand(pid))),
                    "hand": [self.card(cid, viewer) for cid in game.state.card_ids_in(ZoneRef.hand(pid))] if pid in owners else None,
                    "equipment": [self.card(cid, viewer) for slot in EQUIPMENT_SLOTS
                                  for cid in game.state.card_ids_in(ZoneRef.equipment(pid, slot))],
                    "judgment": [self.card(cid, viewer) for cid in game.state.card_ids_in(ZoneRef.judgment(pid))]}
            if game.core:
                info["attack_range"] = attack_range_of(game.state, pid)
                if p.alive and game.state.players_by_id[viewer].alive:
                    info["distance_from_viewer"] = actual_distance(game.state, viewer, pid)
            players.append(info)
        core = game.core
        private_mode = core is not None and core.phase.value == "mode_decision" and game.actor != viewer
        result = {"schema": "player-view-v1", "mode": game.config.mode, "viewer": viewer,
                  "stage": game.stage, "phase": ("resolution" if private_mode else core.phase.value) if core else game.stage,
                  "actor": None if game.is_finished or private_mode else game.actor,
                  "turn_player": core.current_player_id if core else None,
                  "turn_number": core.runtime.turn_number if core else 0,
                  "players": players, "pending": {} if private_mode else self.pending(viewer),
                  "discard": [self.card(cid, viewer) for cid in game.state.card_ids_in(DISCARD_PILE)],
                  "revealed": [self.card(cid, viewer) for cid in game.state.card_ids_in(REVEALED_ZONE)],
                  "deck_count": len(game.state.card_ids_in(DRAW_PILE)),
                  "mulligan_remaining": max(0, game.config.mulligan_limit - game.rerolls[viewer]),
                  "bid_history": list(game.bids), "own_candidates": list(game.candidates.get(viewer, ())),
                  "general_catalog": general_catalog(), "decision": None}
        if core:
            if game.config.mode == "identity8_heir":
                variant = core.mode_policy._variant
                result["own_mode_memory"] = {}
                if viewer == variant.original_lord_player_id:
                    result["own_mode_memory"].update(heir=variant.heir_player_id, heir_selection_used=variant.heir_selection_used)
                if viewer == variant.spy_path_chooser_id:
                    result["own_mode_memory"].update(spy_path=variant.spy_path_choice, spy_path_locked=variant.spy_path_locked)
            result["slash_used"] = core.runtime.slash_used_counts.get(viewer, 0)
            result["slash_limit"] = core.normal_play_slash_limit(viewer)
            result["public_turn_use_counts"] = {pid: sum(1 for event in core.events
                if event.card_user == pid and event.event_type.value in ("card_used", "card_played")
                and event.sequence >= core._turn_start_sequence) for pid in game.config.player_ids}
        return result

    def events(self, viewer: str, events: tuple) -> list[dict]:
        """在事件发生后立即投影并按观察者保存；从不重放未过滤内部日志。"""
        owners = visible_hand_owners(self.game, viewer)
        out = []
        public_gains = public_gain_sequences(events)
        card_public_types = {"card_used", "card_played", "card_discarded", "card_revealed",
                             "card_recast", "judgment_result", "armor_judgment_result",
                             "equipment_equipped", "equipment_removed", "equipment_replaced"}
        public_types = card_public_types | {"damage", "hp_recover", "lose_hp", "armor_recovered", "dying", "death",
            "identity_revealed", "victory", "draw", "chained_state", "damage_prevented",
            "phase_skipped", "card_gained", "target_effect_ineffective", "card_effect_cancelled", "card_invalidated"}
        for event in events:
            kind = event.event_type.value
            if kind == "private_cards_observed":
                if event.skill_owner == viewer:
                    out.append({"type": kind, "actor": viewer, "cards": [self.card(cid, viewer)
                        for cid in event.payload.get("observed_card_ids", ())]})
                continue
            if kind not in public_types:
                continue
            payload = event.payload
            entry = {"type": kind, "actor": event.card_user or event.damage_source or event.skill_owner,
                     "targets": [pid for pid in event.target_ids if pid in self.game.config.player_ids]}
            if kind in card_public_types or (kind == "card_gained" and (
                    event.sequence in public_gains or any(pid in owners for pid in event.target_ids))):
                entry["card"] = self.card(event.card_instance_id, viewer)
            if kind == "card_gained":
                entry["count"] = 1
            if kind == "identity_revealed":
                entry["identity"] = payload.get("identity")
            for key in ("amount", "damage_amount", "recovered", "hp_before", "hp_after", "new_value"):
                if type(payload.get(key)) in (int, bool):
                    entry[key] = payload[key]
            out.append(entry)
        return out
