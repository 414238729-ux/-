"""Production Heuristic AI V1：只消费普通玩家视图与其合法历史记忆。

分数与未知身份估计都是分析约定，不是游戏规则或训练后强度。规则候选
由生产引擎给出，本模块不判定合法性、不生成规则动作、不导入生产会话。
"""

from __future__ import annotations

import copy
from math import isfinite
import random

from ..sgs_ai_strategy_v22 import (DynamicCardValue, StrategyAction, choose_v22_action,
                                 evaluate_shamoke_weapon_swap)
from ..sgs_card_strategy import (HarvestCardOption, select_harvest_card, DisruptionTarget,
    select_disruption_target, evaluate_defense_card_spend, evaluate_group_card_use,
    evaluate_borrowed_sword_response, Relationship)
from ..sgs_team_strategy import RescueResource, plan_team_rescue, evaluate_nullification_decision
from ..sgs_focus_strategy import TargetAssessment, score_focus_target
from ..sgs_general_strategy import TargetSituation, calculate_target_priority
from ..sgs_chain_strategy import ChainStrategyKind, evaluate_chain_strategy
from .playable_config import AI_VERSION, INFORMATION_VERSION, integer
from .playable_communication import current_answer, MEANINGS, ANSWERS


class AISchemaError(ValueError):
    """不理解的新动作必须定位修正，不能吞异常选第一项。"""


SLASHES = {"sgs_basic_sha", "sgs_basic_huosha", "sgs_basic_leisha"}
ELEMENTAL = {"sgs_basic_huosha", "sgs_basic_leisha", "sgs_trick_huogong"}
RESPONSE_OPS = {"play_dodge", "play_slash_for_duel", "play_slash_for_nanman", "play_jink_for_wanjian", "activate_bagua"}
ATTACK_OPS = {"use_slash", "qinglong_use_slash", "use_duel", "use_fire_attack"}
PASS_OPS = {"pass_judgment_wuxie", "pass_slash_response", "pass_trick_response", "pass_duel_slash",
           "pass_fire_attack_discard", "pass_nanman_slash", "pass_wanjian_jink", "pass_rescue",
           "pass_weapon_choice", "pass_cixiong", "pass_skill", "feiyang_decline", "peasant_reward_decline",
           "ambitionist_reward_decline", "pass_mode_decision", "succession_obtain_none"}
OPTION_FIELDS = {"schema", "action_id", "ordinal", "operation", "type", "targets", "skill", "card",
                 "cost_cards", "selected_cards", "remaining_cards", "option", "zone", "virtual_key",
                 "converted_to_fire", "description"}


class ProductionAIController:
    version = AI_VERSION

    def __init__(self, *, seed: int = 0, parameters: dict | None = None) -> None:
        integer(seed, "策略随机种子")
        self._rng = random.Random(seed)
        self.parameters = {"aggression": 1.0, "preservation": 1.0, "tie_randomness": 1.0}
        for key, value in (parameters or {}).items():
            if key not in self.parameters or type(value) not in (int, float) or not isfinite(value) or not 0 <= value <= 10:
                raise ValueError(f"非法AI参数{key!r}；须为已知参数及0..10有限数值")
            self.parameters[key] = float(value)
        self._event_cursor = 0
        self._lord_id = None
        self._hostility_to_lord: dict[str, float] = {}
        self._focus = None
        self.last_trace: dict = {}
        self.used_strategies: set[str] = set()
        self._strategy_calls: set[str] = set()
        self._turn_number = None
        self._jili_ranges: set[int] = set()
        self.selected_operations: dict[str, int] = {}

    def observe(self, events: list[dict]) -> None:
        if self._event_cursor > len(events):
            raise AISchemaError("AI历史游标倒退；不可把其他会话历史接入本控制器")
        for event in events[self._event_cursor:]:
            targets = event.get("targets", ())
            if event.get("type") == "identity_revealed" and event.get("identity") == "lord" and targets:
                self._lord_id = targets[0]
            if event.get("type") == "card_used" and self._lord_id in targets and event.get("actor"):
                key = (event.get("card") or {}).get("key", "")
                change = (1.0 if key in SLASHES | {"sgs_trick_juedou", "sgs_trick_guohechaiqiao", "sgs_trick_shunshouqianyang",
                                                   "sgs_delayed_lebusi", "sgs_delayed_bingliang"}
                          else -1.0 if key == "sgs_basic_tao" else 0.0)
                actor = event["actor"]
                self._hostility_to_lord[actor] = max(-3.0, min(3.0, self._hostility_to_lord.get(actor, 0) + change))
        self._event_cursor = len(events)

    def relation(self, view: dict, target: str) -> float:
        """+1己方，-1敌方，中间值为基于公开行为的身份推断。"""
        if target == view["viewer"]:
            return 1.0
        players = {p["id"]: p for p in view["players"]}
        me, them = players[view["viewer"]], players[target]
        own, role = me["role"], them["role"]
        if view["mode"] == "duel":
            return -1.0
        if view["mode"] in ("2v2", "doudizhu"):
            return 1.0 if own == role else -1.0
        evidence = self._hostility_to_lord.get(target, 0.0)
        if own in ("lord", "loyalist"):
            if role in ("lord", "loyalist"):
                return 1.0
            if role in ("rebel", "spy", "ambitionist"):
                return -1.0
            return max(-0.9, min(0.8, -0.3 - evidence * 0.4))
        if own == "rebel":
            if role == "rebel":
                return 1.0
            if role in ("lord", "loyalist", "ambitionist"):
                return -1.0
            return max(-0.8, min(0.8, evidence * 0.4 - 0.15))
        if own in ("spy", "ambitionist"):
            alive = sum(p["alive"] for p in players.values())
            return 0.8 if role == "lord" and alive > 2 else -1.0
        return -0.2  # 开局尚未确定身份；只是选将的中性估值。

    @staticmethod
    def _me(view: dict) -> dict:
        return next(p for p in view["players"] if p["id"] == view["viewer"])

    def choose_question(self, view):
        communication = view.get("communication")
        if communication is None:
            return None
        if type(communication) is not dict or communication.get("kind") not in {"ask", "answer"}:
            raise AISchemaError("无法解释的communication决策schema")
        if communication["kind"] != "ask":
            return None
        for option in communication["options"]:
            topic = option["question"]["topic"]
            if topic not in MEANINGS:
                raise AISchemaError(f"未知协作问题：{topic}")
            if topic == "peach_available" and self.relation(view, option["question"]["target"]) <= 0:
                continue
            if topic in {"nullification_protection", "rescue_desire", "peach_available", "jiedao_willing"}:
                self.used_strategies.add("public_context_question")
                return option["action_id"]
        return None

    def cooperation_answer(self, view, question):
        """自己的合法信息决定一个答案；私有理由和分数绝不进入公共回答。"""
        topic = question.get("topic")
        fields = {"schema", "topic", "meaning", "asker", "respondent", "target", "plan", "text", "window_id", "layer"}
        if (not fields <= set(question) or set(question) - fields - {"question_id", "generation", "answer", "valid", "decision_id"}
                or question.get("schema") != "cooperation-context-v1" or topic not in MEANINGS
                or question.get("meaning") != MEANINGS[topic]):
            raise AISchemaError(f"不支持的协作问题schema：{topic!r}")
        if question["respondent"] != view["viewer"]:
            raise AISchemaError("不得替另一座位回答协作问题")
        me = self._me(view)
        hand = me.get("hand")
        if hand is None:
            raise AISchemaError("回答者缺少自己的合法手牌视图")
        if topic == "nullification_protection":
            pending = view["pending"]
            key = pending.get("card_key")
            if key not in {"sgs_trick_nanmanruqin", "sgs_trick_wanjianqifa"} or pending.get("target") != me["id"]:
                return "NO_RESPONSE"
            response_keys = SLASHES if key == "sgs_trick_nanmanruqin" else {"sgs_basic_shan"}
            has_response = any(c["key"] in response_keys for c in hand)
            if me["hp"] <= pending.get("damage", 1):
                return "YES"  # 致命风险时即使有杀/闪也可能希望保留响应资源。
            if not has_response and me["hp"] >= 3 and self.parameters["preservation"] >= 2:
                return "NO"  # 愿承伤以保留团队无懈，不表示持有响应牌。
            if has_response and self.parameters["preservation"] >= 3:
                return "YES"
            return "NO" if has_response else "YES"
        if topic == "rescue_desire":
            return "YES" if view["pending"].get("dying") == me["id"] else "NO_RESPONSE"
        if topic == "peach_available":
            return "YES" if any(c["key"] == "sgs_basic_tao" for c in hand) else "NO"
        if topic == "jiedao_has_slash":
            return "YES" if any(c["key"] in SLASHES for c in hand) else "NO"
        if topic == "jiedao_can_supply":
            spear = any(c["key"] == "sgs_weapon_zhangbashemao" for c in me["equipment"])
            return "YES" if any(c["key"] in SLASHES for c in hand) or (spear and len(hand) >= 2) else "NO"
        if topic == "jiedao_willing":
            # 意愿只按公开目标关系；NO不表达有没有杀。
            return "YES" if self.relation(view, question["target"]) < 0 else "NO"
        if topic == "skill_consent":
            return "NO"  # V1没有把已实现武将的失去体力视为确定合作收益。
        if topic == "baoxin_distribution":
            count = sum(c["key"] in SLASHES for c in hand)
            plan = question["plan"]
            proposition = plan["proposition"]
            if proposition["kind"] == "count_equals":
                answer = count == proposition["count"]
            elif proposition["kind"] == "last_recipient":
                ring = plan["ring"]
                answer = bool(count) and ring[(ring.index(me["id"]) + count) % len(ring)] == question["target"]
            else:
                raise AISchemaError("无法解释鲍信分发命题")
            return "YES" if answer else "NO"
        raise AISchemaError(f"协作问题未实现：{topic}")

    def answer_question(self, view):
        c = view.get("communication")
        if not c or c["kind"] != "answer":
            raise AISchemaError("当前不是本座位的问答决策")
        answer = self.cooperation_answer(view, c["question"])
        if answer not in ANSWERS:
            raise AISchemaError("协作答案必须为YES/NO/NO_RESPONSE")
        self.used_strategies.add("public_context_answer:" + c["question"]["topic"])
        choices = [o for o in c["options"] if o.get("answer") == answer]
        if len(choices) != 1 or any(o.get("answer") not in ANSWERS for o in c["options"]):
            raise AISchemaError("公开问答合法答案集合不匹配")
        return choices[0]["action_id"]

    def card_value(self, card: dict | None, view: dict) -> float:
        if card is None:
            return 2.0  # 仅未知手牌选择的策略期望，不假装知道牌面。
        me = self._me(view)
        key = card["key"]
        hand = me.get("hand") or []
        copies = sum(c["key"] == key for c in hand)
        base = 2.0
        if key == "sgs_basic_tao":
            base = 5.0 + max(0, 3 - me["hp"]) * 2
        elif key == "sgs_basic_shan":
            base = 4.5 if copies <= 1 else 2.5
        elif key == "sgs_basic_jiu":
            base = 5.0 if me["hp"] <= 1 else 2.8
        elif key in SLASHES:
            base = 3.8 if copies <= 1 else 2.0
        elif key == "sgs_trick_wuxiekeji":
            base = 4.5
        elif key == "sgs_trick_wuzhongshengyou":
            base = 5.5
        elif card.get("slot"):
            base = self.equipment_value(card, view)
        synergy = 0.0
        if me.get("general") == "wangyuanji" and card.get("color") == "红":
            synergy = 0.4  # 明哲潜力仅作为策略偏好，不更改规则。
        self._strategy_calls.add("sgs_ai_strategy_v22.DynamicCardValue")
        return DynamicCardValue(base_utility=base,
                                skill_synergy=synergy).total

    def equipment_value(self, card: dict, view: dict) -> float:
        me = self._me(view)
        key, slot = card["key"], card.get("slot")
        if slot == "weapon":
            slashes = sum(c["key"] in SLASHES for c in me.get("hand") or ())
            return 2 + (card.get("attack_range") or 1) * 0.5 + (
                max(0, slashes - 1) * 2 if key == "sgs_weapon_zhugeliannu" else 0)
        if slot == "armor":
            if key == "sgs_armor_tengjia":
                fire_threat = any(e["key"] == "sgs_weapon_zhuqueyushan" for p in view["players"]
                    if p["alive"] and self.relation(view, p["id"]) < 0 for e in p["equipment"])
                return 1.0 if fire_threat else 3.0
            return 3.5 + (1 if key == "sgs_armor_baiyinshizi" and me["hp"] <= 2 else 0)
        return 3.0

    def _harm(self, view: dict, target_id: str, damage: int = 1) -> float:
        self._strategy_calls.update(("sgs_general_strategy.calculate_target_priority", "sgs_focus_strategy.score_focus_target"))
        target = next(p for p in view["players"] if p["id"] == target_id)
        relation = self.relation(view, target_id)
        vulnerability = calculate_target_priority(TargetSituation(
            target_id=target_id, base_max_hp=target["max_hp"], initial_hp=target["max_hp"],
            current_hp=target["hp"], hand_count=target["hand_count"],
            current_threat=target["hand_count"] * 0.1,
            kill_efficiency=max(0, 4 - target["hp"]),
            already_primary_focus=target_id == self._focus)).target_priority
        focus = score_focus_target(TargetAssessment(target_id=target_id,
            current_threat=target["hand_count"] * 0.15,
            estimated_kill_value=3.0,
            kill_probability=0.8 if target["hp"] <= damage and target["hand_count"] == 0 else 0.15,
            victory_progress_value=4.0 if target.get("role") == "lord" else 1.0,
            defensive_value=len(target["equipment"]) * 0.2)).target_priority_score
        lethal = 6.0 if target["hp"] <= damage else 0.0
        return -relation * (damage * 3 + lethal + max(0, vulnerability) * 0.12 + max(0, focus) * 0.15)

    def _chain(self, view: dict, target_id: str, damage: int) -> float:
        target = next(p for p in view["players"] if p["id"] == target_id)
        if not target["chained"]:
            return 0.0
        other = [p for p in view["players"] if p["alive"] and p["chained"] and p["id"] != target_id]
        enemy = sum(max(0, self._harm(view, p["id"], damage)) for p in other)
        friendly = sum(max(0, -self._harm(view, p["id"], damage)) for p in other)
        self._strategy_calls.add("sgs_chain_strategy.evaluate_chain_strategy")
        return evaluate_chain_strategy(ChainStrategyKind.ENEMY_CHAIN,
            enemy_expected_hp_loss=enemy, friendly_expected_hp_loss=friendly).score

    def _rescue_score(self, view: dict, option: dict) -> tuple[float, str]:
        dying = view["pending"].get("dying") or (option["targets"] or [view["viewer"]])[0]
        players = {p["id"]: p for p in view["players"]}
        relation = self.relation(view, dying)
        if relation <= 0:
            return -8.0, "身份／敌我推断不支持救援此目标"
        team = [p["id"] for p in players.values() if p["id"] != dying and self.relation(view, p["id"]) > 0.5]
        resources = []
        for p in players.values():
            if p["id"] not in [dying, *team] or not p["alive"]:
                continue
            for c in p.get("hand") or ():
                if c["key"] in ("sgs_basic_tao", "sgs_basic_jiu"):
                    resources.append(RescueResource(c["ref"], p["id"],
                        "peach" if c["key"] == "sgs_basic_tao" else "self_wine",
                        legal_target_ids=frozenset([dying])))
            if p.get("hand") is None:
                answer = current_answer(view, "peach_available", respondent=p["id"], target=dying)
                if answer == "YES":
                    resources.append(RescueResource("public_answer:" + p["id"], p["id"], "peach",
                        legal_target_ids=frozenset([dying])))
        plan = plan_team_rescue(players[dying]["hp"], dying, team, resources)
        return (100.0 if plan.must_rescue or dying == view["viewer"] else 8.0,
                "sgs_team_strategy.plan_team_rescue：" + plan.explanation)

    def _score(self, view: dict, a: dict) -> tuple[float, str, str]:
        op = a["operation"]
        me = self._me(view)
        hand = me.get("hand") or []
        targets = a["targets"]
        target = targets[0] if targets else view["pending"].get("target")
        card = a["card"]
        key = a["virtual_key"] or (card or {}).get("key")
        cost = sum(self.card_value(c, view) for c in a["cost_cards"])
        source, reason = "heuristic_v1", op
        if op in PASS_OPS:
            score = 0.0
        elif op in ("proceed_prepare", "proceed_judgment", "proceed_draw", "end_turn"):
            score = 1.0
        elif op == "end_play_phase":
            score = 0.0
        elif op == "opening_bid":
            score = 1.0 if a["option"] is None else (0.5 if a["option"] == 1 else -float(a["option"]))
            reason = "未见手牌时采用保守叫价分析约定；首叫1倍由规则强制"
        elif op == "opening_choose_general":
            profile = next(p for p in view["general_catalog"] if p["general_key"] == a["option"])
            score = profile["starting_hp"] * 0.4 + len(profile["skill_ids"]) * 0.3
            if a["option"] == "wangyuanji" and view["mode"] in ("2v2", "identity8", "identity8_heir"):
                score += 0.8
            reason = "自定义候选：基础生存、技能完整性与人数收益的普通权重"
        elif op in ("opening_keep_hand", "opening_reroll_hand"):
            keep = sum(self.card_value(c, view) for c in hand)
            score = keep if op == "opening_keep_hand" else len(hand) * 3.5
            reason = "按自己合法可见起手牌保留价值判断整手重摸"
        elif op == "heal_self":
            score = 9.0 if me["hp"] <= 2 else 5.0
        elif op == "use_wine_buff":
            has_attack = any(x["operation"] == "use_slash" for x in view["decision"]["options"])
            score = 5.0 if has_attack else -5.0
        elif op == "use_wuzhong":
            score = 7.0
        elif op in ATTACK_OPS:
            score = sum(self._harm(view, tid) for tid in targets) * self.parameters["aggression"]
            score -= cost * 0.55 + (0.8 if card else 0)
            if op == "use_fire_attack":
                suits = {c["suit"] for c in hand if c["ref"] != (card or {}).get("ref")}
                score *= min(0.85, len(suits) / 4)
                score -= 1.5
            if op == "use_duel":
                score += sum(c["key"] in SLASHES for c in hand) * 0.5 - 0.8
            if target and (key in ELEMENTAL or a["converted_to_fire"]):
                score += self._chain(view, target, 1)
            source = "heuristic_v1.attack"
            reason = "公开体力／手牌数、关系推断、集火可达性和属性传导净收益"
        elif op in RESPONSE_OPS:
            damage = view["pending"].get("damage", 1)
            lethal = me["hp"] <= damage
            score = (14 if lethal else 4.0 * damage) - self.card_value(card, view) * 0.55 - cost * 0.6
            if op == "activate_bagua":
                score = 20 if lethal else 7.0
            if me["general"] == "shamoke" and view.get("public_turn_use_counts", {}).get(me["id"], 0) + 1 == me.get("attack_range", 1):
                score += me.get("attack_range", 1) * 2
                reason = "响应可兑现自己的蒺藜；致命伤害优先避免"
            else:
                reason = "响应收益与防御牌保留价值比较；低收益时允许承伤"
        elif op in ("rescue_with_peach", "rescue_with_wine"):
            score, reason = self._rescue_score(view, a)
            advice = current_answer(view, "rescue_desire", target=target)
            if advice is not None:
                score += 3 if advice == "YES" else -110
                reason += "；本次公开救援意愿=" + advice
                self._strategy_calls.add("public_rescue_advice")
            if op == "rescue_with_wine":
                score += 0.5
            source = "sgs_team_strategy.plan_team_rescue"
        elif op == "use_wuxie":
            pending = view["pending"]
            relation = self.relation(view, pending["target"]) if pending.get("target") else 0
            beneficial = pending.get("card_key") in ("sgs_trick_wuzhongshengyou", "sgs_trick_taoyuanjieyi", "sgs_trick_wugufengdeng")
            negative = (-relation if beneficial else relation) * (4.0 if beneficial else 5.0)
            if not pending.get("trick_active", True):
                negative = -negative
            rows = view.get("nullification", {}).get("players", {})
            holders = [pid for pid, k in rows.items() if k["availability"] == "known_usable"]
            enemies = sum(self.relation(view, pid) < 0 for pid in holders)
            allies = any(pid != view["viewer"] and self.relation(view, pid) > 0 for pid in holders)
            decision = evaluate_nullification_decision(max(0.0, negative),
                future_preservation_value=1.8 * self.parameters["preservation"],
                known_enemy_nullification_holders=enemies, allied_counter_available=allies)
            score, reason = decision.decision_score, decision.explanation
            if rows:
                reason += f"；公共读条已知敌方可用者{enemies}，其余未知不作无人有无懈解释"
                self._strategy_calls.add("public_nullification_knowledge")
            plan = {"operation": "use_wuxie" if pending.get("trick_active", True) else "pass_trick_response",
                    "targets": [pending.get("target")]}
            advice = current_answer(view, "nullification_protection", respondent=pending.get("target"),
                                    target=pending.get("target"), plan=plan)
            if advice is not None:
                direction = 1 if pending.get("trick_active", True) else -1
                score += (4.0 if advice == "YES" else -6.0) * direction
                reason += "；本目标本响应层公开保护建议=" + advice + "（不表示杀/闪事实）"
                self._strategy_calls.add("public_nullification_protection_advice")
            source = "sgs_team_strategy.evaluate_nullification_decision"
        elif op in ("select_discard_card", "select_discard_two", "cixiong_discard_card"):
            score = 8.0 - self.card_value(card, view)
            reason = "保留关键桃闪与稀缺进攻牌，选择低边际价值代价"
        elif op in ("unselect_discard_card", "unselect_discard_two"):
            score = -100.0
        elif op in ("discard_phase_submit", "discard_two_submit"):
            score = 100.0
        elif op in ("use_weapon", "use_armor", "use_mount"):
            old = next((c for c in me["equipment"] if c["slot"] == card["slot"]), None)
            old_value = self.equipment_value(old, view) if old else 0.0
            score = self.equipment_value(card, view) - old_value
            if old and old["key"] == "sgs_armor_baiyinshizi" and me["hp"] < me["max_hp"]:
                score += 4.0
            if op == "use_weapon" and me["general"] == "shamoke":
                swap = evaluate_shamoke_weapon_swap(high_range_triggered=any(r >= 3 for r in self._jili_ranges),
                    original_weapon_value=old_value, replacement_weapon_name=card["name"],
                    replacement_weapon_value=self.equipment_value(card, view),
                    slash_count=sum(c["key"] in SLASHES for c in hand),
                    next_turn_jili_value=(card.get("attack_range") or 1) * 0.4)
                score, reason = swap.swap_value - swap.keep_value, swap.reason
                source = "sgs_ai_strategy_v22.evaluate_shamoke_weapon_swap"
        elif op in ("use_guohe", "use_shunshou", "use_lebusi", "use_bingliang"):
            p = next(p for p in view["players"] if p["id"] == target)
            relation = self.relation(view, target)
            score = -relation * (3.5 + min(2, p["hand_count"] * 0.3))
            if op in ("use_guohe", "use_shunshou") and relation > 0 and p["judgment"]:
                score = 6.5
            reason = "结合关系与公开区域牌判断控制收益；拆顺可帮助己方移除判定牌"
        elif op in ("choose_target_zone_card", "hanbing_discard_card", "succession_obtain_card", "weapon_discard_mount"):
            relation = self.relation(view, target) if target else -1.0
            enemy = relation < 0
            disruption = select_disruption_target([DisruptionTarget(target or me["id"], str(a["ordinal"]),
                base_expected_value=self.card_value(card, view) * (-relation),
                dangerous_delayed_on_ally=relation > 0 and a["zone"] == "judgment",
                focus_target_armor=enemy and (card or {}).get("slot") == "armor",
                focus_target_plus_one_horse=enemy and (card or {}).get("slot") == "defense_horse",
                known_peach=enemy and (card or {}).get("key") == "sgs_basic_tao")])
            score, reason = disruption.score, disruption.reason
            if op == "succession_obtain_card":
                score = self.card_value(card, view)
            source = "sgs_card_strategy.select_disruption_target"
        elif op == "pick_wugu_card":
            harvest = select_harvest_card([HarvestCardOption(str(a["ordinal"]), card["name"],
                base_marginal_value=self.card_value(card, view), is_slash=key in SLASHES,
                is_peach=key == "sgs_basic_tao")],
                has_slash=any(c["key"] in SLASHES for c in hand),
                slash_dependent_skill=me["general"] == "shamoke",
                team_needs_rescue=any(p["hp"] <= 1 and self.relation(view, p["id"]) > 0 for p in view["players"] if p["alive"]))
            score, reason, source = harvest.score, harvest.reason, "sgs_card_strategy.select_harvest_card"
        elif op in ("use_nanman", "use_wanjian", "use_taoyuan"):
            benefit = harm = 0.0
            for tid in targets:
                p = next(p for p in view["players"] if p["id"] == tid)
                value = (self.relation(view, tid) * min(1, p["max_hp"] - p["hp"]) * 4
                         if op == "use_taoyuan" else self._harm(view, tid))
                benefit += max(0, value)
                harm += max(0, -value)
            group = evaluate_group_card_use({"use_nanman": "南蛮入侵", "use_wanjian": "万箭齐发",
                "use_taoyuan": "桃园结义"}[op], enemy_expected_loss=benefit, friendly_expected_loss=harm)
            score, reason, source = group.score - 1.0, group.reason, "sgs_card_strategy.evaluate_group_card_use"
        elif op == "use_wugu":
            score = sum(self.relation(view, p["id"]) for p in view["players"] if p["alive"]) * 1.5 - 0.5
        elif op == "use_tiesuo":
            has_elemental = any(c["key"] in ELEMENTAL for c in hand)
            score = 0.0
            for tid in targets:
                p = next(p for p in view["players"] if p["id"] == tid)
                rel = self.relation(view, tid)
                score += (rel * 3 if p["chained"] else -rel * (2.5 if has_elemental else 0.8))
            score -= 1.0
        elif op == "recast_tiesuo":
            score = 1.2
        elif op == "use_shandian":
            score = -2.0
            reason = "缺少改判控制时采用保守通用评分，合法动作仍保留"
        elif op == "use_jiedao":
            if len(targets) != 2:
                raise AISchemaError("借刀使用schema必须含持械者与被杀目标两个有序目标")
            holder, victim = targets
            p = next(p for p in view["players"] if p["id"] == holder)
            slash_count = sum(c["key"] in SLASHES for c in p["hand"]) if p.get("hand") is not None else None
            chance = 0.5 if slash_count is None else float(slash_count > 0)
            plan = {"operation": "use_jiedao", "targets": targets}
            fact = current_answer(view, "jiedao_has_slash", respondent=holder, target=victim, plan=plan)
            capability = current_answer(view, "jiedao_can_supply", respondent=holder, target=victim, plan=plan)
            willingness = current_answer(view, "jiedao_willing", respondent=holder, target=victim, plan=plan)
            if capability is not None:
                chance = 0.8 if capability == "YES" else 0.0
            elif fact is not None:
                chance = 0.8 if fact == "YES" else 0.3  # 没有实体杀仍可能有丈八转化能力。
            if willingness is not None:
                chance *= 1.4 if willingness == "YES" else 0.25  # 意愿只调整概率，不改写资源事实。
            chance = min(1.0, chance)
            score = chance * self._harm(view, victim) - (1 - chance) * self.relation(view, holder) * 2 - 0.6
            source, reason = "heuristic_v1.borrowed_sword_use", "依据可见手牌及本次公开事实/能力/意愿回答分别估计；无回答保持概率"
        elif op in ("choose_borrowed_sword_slash", "refuse_borrowed_sword_slash"):
            if op == "refuse_borrowed_sword_slash":
                score = 0.0
            else:
                user = view["pending"].get("source")
                decision = evaluate_borrowed_sword_response(
                    user_relationship=Relationship.ALLY if user and self.relation(view, user) > 0 else Relationship.ENEMY,
                    target_relationship=Relationship.ALLY if self.relation(view, target) > 0 else Relationship.ENEMY,
                    has_slash=True, target_is_legal=True, weapon_retention_value=3.0,
                    slash_effect_value=self._harm(view, target))
                score, reason, source = decision.score, decision.reason, "sgs_card_strategy.evaluate_borrowed_sword_response"
        elif op == "reveal_card_for_fire_attack":
            score = -self.card_value(card, view) * 0.1
            reason = "无法知道对方隐藏花色，展示最低保留价值的合法牌"
        elif op == "discard_same_suit_for_fire_attack":
            gain = self._harm(view, target) + self._chain(view, target, 1)
            decision = evaluate_defense_card_spend(tactical_gain=max(0, gain), defense_value=self.card_value(card, view))
            score, reason, source = decision.score, decision.reason, "sgs_card_strategy.evaluate_defense_card_spend"
        elif op == "activate_cixiong":
            score = 3.0 if not target or self.relation(view, target) < 0 else -3.0
        elif op == "cixiong_allow_draw":
            score = 1.5
        elif op in ("weapon_force_hit", "weapon_prevent_damage"):
            value = self._harm(view, target)
            if op == "weapon_force_hit":
                cheapest = sorted(self.card_value(c, view) for c in hand + me["equipment"]
                                  if c["key"] != "sgs_weapon_guanshifu")[:2]
                score = value - sum(cheapest) * 0.6
            else:
                p = next(p for p in view["players"] if p["id"] == target)
                score = -self.relation(view, target) * min(2, p["hand_count"] + len(p["equipment"])) * 2 - value
            reason = "按发动后的实际代价与伤害／弃牌净收益评分，底层PASS不等于放弃"
        elif op == "feiyang_activate":
            score = 8.0 - cost * 0.6
        elif op == "peasant_reward_recover_hp":
            score = 9 if me["hp"] <= 2 else (4 if me["hp"] < me["max_hp"] else -1)
        elif op == "peasant_reward_draw_two":
            score = 6.0
        elif op == "activate_skill":
            skill = a["skill"]
            if skill == "sgs_skill_zuilun":
                facts = view["pending"].get("skill_facts", {})
                count = facts.get("n", 0)
                score = count * 4 if count else (-10 if me["hp"] <= 1 else 0.5)
            elif skill in ("sgs_skill_jili", "sgs_skill_mingzhe"):
                score = 5.0 + (me.get("attack_range", 1) if skill == "sgs_skill_jili" else 0)
            elif skill == "sgs_skill_pojiang":
                score = 1.0
                reason = "已知技能的通用手牌上限收益；未宣称完整武将专项策略"
            else:
                raise AISchemaError(f"缺少技能策略schema：{skill!r}，operation={op}")
        elif op == "qianchong_choice":
            category = a["option"]
            if category not in ("basic", "trick", "equipment"):
                raise AISchemaError(f"未知谦冲分支{category!r}")
            chinese = {"basic": "基本牌", "trick": "锦囊牌", "equipment": "装备牌"}[category]
            score = sum(1.0 + self.card_value(c, view) * 0.2 for c in hand
                        if c["category"] == chinese or (category == "trick" and "锦囊" in c["category"]))
            reason = "按本阶段实际手牌类别选择谦冲距离／次数许可"
        elif op == "private_card_selection_submit":
            score = sum(self.card_value(c, view) for c in a["selected_cards"])
            reason = "只使用罪论依法观看的三张牌，按本人手牌保留价值选择"
        elif op == "skill_lose_hp_target_choice":
            score = self._harm(view, target)
            consent = current_answer(view, "skill_consent", respondent=target, target=target,
                plan={"operation": op, "targets": targets, "skill": "sgs_skill_zuilun"})
            if consent is not None:
                score += 2 if consent == "YES" else -6
                reason = "公开本次技能意愿只影响评分，不替代技能费用与合法性"
                self._strategy_calls.add("public_skill_consent")
        elif op == "select_heir":
            p = next(p for p in view["players"] if p["id"] == target)
            score = self.relation(view, target) * 4 + p["hp"] * 0.2
            reason = "用公开行为推断忠臣可能性，不能读取隐藏忠臣身份"
        elif op == "choose_spy_path":
            if a["option"] not in ("loyalist", "ambitionist"):
                raise AISchemaError("未知内奸择途分支")
            score = (2 if me["hp"] >= 3 else 0.5) if a["option"] == "ambitionist" else 1.0
        elif op == "ambitionist_mark_draw_two":
            score = 6.0 if me["hp"] >= 3 else -1.0
        elif op == "ambitionist_reward_draw_three":
            score = 8.0
        else:
            raise AISchemaError(f"未覆盖生产动作：operation={op!r}, type={a.get('type')!r}, ordinal={a.get('ordinal')}")
        if not isfinite(score):
            raise AISchemaError(f"非有限策略分数：{op}")
        return float(score), reason, source

    def choose(self, view: dict) -> str:
        if type(view) is not dict or view.get("schema") != "player-view-v1" or not view.get("decision"):
            raise AISchemaError("AI需要player-view-v1及当前本座位决策")
        if view["actor"] != view["viewer"]:
            raise AISchemaError("AI视图不是当前行动者")
        options = view["decision"]["options"]
        if self._turn_number != view.get("turn_number", 0):
            self._turn_number = view.get("turn_number", 0)
            self._jili_ranges.clear()
        if not options:
            raise AISchemaError("AI收到空合法集合")
        scored = []
        self._strategy_calls = set()
        for index, option in enumerate(options):
            if (type(option) is not dict or set(option) != OPTION_FIELDS
                    or option["schema"] != "production-action-option-v1"
                    or type(option["ordinal"]) is not int or option["ordinal"] != index
                    or option["type"] not in ("use_card", "play_card", "activate_skill", "respond", "pass", "choose_option", "move_card")):
                raise AISchemaError(f"无法解释的动作schema，ordinal={index}")
            score, reason, source = self._score(view, option)
            scored.append((score, index, reason, source))
        # 同分顺序只依赖权威枚举序与独立AI随机流，不排序会话签名或牌引用。
        best = max(row[0] for row in scored)
        tied = [row for row in scored if row[0] == best]
        winner = self._rng.choice(tied) if self.parameters["tie_randomness"] else tied[0]
        ordered = [winner] + [row for row in scored if row[1] != winner[1]]
        audit = choose_v22_action([StrategyAction(action_id=f"ordinal:{index}", immediate_value=score,
                reason=reason) for score, index, reason, source in ordered])
        chosen_index = int(audit.chosen_action.split(":")[1])
        chosen = options[chosen_index]
        if chosen["operation"] == "activate_skill" and chosen["skill"] == "sgs_skill_jili":
            self._jili_ranges.add(view["pending"].get("skill_facts", {}).get("draw_count", self._me(view).get("attack_range", 1)))
        if chosen["operation"] in ATTACK_OPS and chosen["targets"]:
            self._focus = chosen["targets"][0]
        self.last_trace = {"ai_version": self.version, "information_version": INFORMATION_VERSION, "parameters": dict(self.parameters),
            "decision_id": view["decision"]["decision_id"], "viewer": view["viewer"],
            "chosen_ordinal": chosen_index, "operation": chosen["operation"],
            "score": winner[0], "reason": audit.reason, "candidate_count": len(options),
            "strategies": sorted({row[3] for row in scored} | self._strategy_calls | {"sgs_ai_strategy_v22.choose_v22_action"}),
            "scores": [{"ordinal": row[1], "score": row[0], "reason": row[2], "strategy": row[3]}
                       for row in scored], "identity_inference": copy.deepcopy(self._hostility_to_lord)}
        self.used_strategies.update(self.last_trace["strategies"])
        self.selected_operations[chosen["operation"]] = self.selected_operations.get(chosen["operation"], 0) + 1
        return chosen["action_id"]
