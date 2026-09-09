"""公开、可选、绑定具体语境的农民问答，不是手牌共享或自由聊天。

花/蛋含义来自用户确认；探测预算是本AI建模约束，不是官方互动次数。
"""
from __future__ import annotations
from dataclasses import dataclass
from .actions import ActionType, LegalAction, RuleAdapter

ANSWERS = ("YES", "NO", "NO_RESPONSE")
ANSWER_LABELS = {"YES": "花：YES／同意", "NO": "蛋：NO／不同意", "NO_RESPONSE": "不回答／UNKNOWN"}
MEANINGS = {"nullification_protection": "action_advice", "rescue_desire": "action_advice",
            "peach_available": "resource_fact", "jiedao_has_slash": "resource_fact",
            "jiedao_can_supply": "capability", "jiedao_willing": "willingness",
            "skill_consent": "willingness", "baoxin_distribution": "proposition"}


def _offer(view, topic, respondent, target, plan, text):
    window = view.get("nullification", {}).get("window")
    return {"schema": "cooperation-context-v1", "topic": topic, "meaning": MEANINGS[topic],
            "asker": view["viewer"], "respondent": respondent, "target": target,
            "plan": plan, "text": text,
            "window_id": window["id"] if window and window["active"] else None,
            "layer": window["layer"] if window and window["active"] else None}


def question_offers(view):
    """只读取询问者合法视图及生产候选，不接受外部任意问题参数。"""
    if view["mode"] != "doudizhu" or view.get("stage") != "playing" or not view.get("decision"):
        return []
    players = {p["id"]: p for p in view["players"]}
    asker = view["viewer"]
    if players[asker]["role"] != "peasants":
        return []
    mate = next((p["id"] for p in players.values()
                 if p["id"] != asker and p["role"] == "peasants" and p["alive"]), None)
    if mate is None:
        return []
    options, pending = view["decision"]["options"], view["pending"]
    window = view.get("nullification", {}).get("window")
    offers = []
    if (window and window["active"] and pending.get("target") == mate
            and pending.get("card_key") in {"sgs_trick_nanmanruqin", "sgs_trick_wanjianqifa"}
            and any(a["operation"] == "use_wuxie" for a in options)):
        plan = {"operation": "use_wuxie" if window["effect_active"] else "pass_trick_response", "targets": [mate]}
        offers.append(_offer(view, "nullification_protection", mate, mate, plan,
            "这次是否需要我为你使用无懈？" if window["effect_active"] else
            "这次是否希望我保留无懈，让对你的锦囊效果继续被抵消？"))
    if pending.get("dying"):
        target = pending["dying"]
        if target == mate and any(a["operation"] == "rescue_with_peach" for a in options):
            offers.append(_offer(view, "rescue_desire", mate, target,
                {"operation": "rescue_with_peach", "targets": [target]}, "这次是否希望我为你使用桃救援？"))
        elif any(a["operation"] == "pass_rescue" for a in options):
            offers.append(_offer(view, "peach_available", mate, target,
                {"operation": "rescue_with_peach", "targets": [target]}, "针对这次濒死救援，你现在是否至少有一张桃？"))
    # 拥有借刀合法候选并不意味着队友已经知道，必须先有公开展示记忆。
    if "sgs_trick_jiedaosharen" in view.get("public_known_hand_keys", {}).get(asker, []):
        plans = set()
        for a in options:
            if a["operation"] != "use_jiedao" or len(a["targets"]) != 2 or a["targets"][0] != mate:
                continue
            targets = tuple(a["targets"])
            if targets in plans:
                continue
            plans.add(targets)
            for topic, wording in (("jiedao_has_slash", "你现在是否至少有一张杀？"),
                                   ("jiedao_can_supply", "你是否能为这次借刀提供一张杀？"),
                                   ("jiedao_willing", "你是否愿意配合这次借刀？")):
                offers.append(_offer(view, topic, mate, targets[1],
                    {"operation": "use_jiedao", "targets": list(targets)}, wording))
    for a in options:
        if a["operation"] == "skill_lose_hp_target_choice" and a["targets"] == [mate]:
            offers.append(_offer(view, "skill_consent", mate, mate,
                {"operation": a["operation"], "targets": [mate], "skill": "sgs_skill_zuilun"},
                "这次罪论是否同意我选择你，与我各失去1点体力？"))
    return offers


@dataclass(frozen=True)
class DistributionPlan:
    """鲍信公开规则场景；该武将未进入生产，因此runtime不提供此入口。"""
    asker: str
    respondent: str
    recipient: str
    ring: tuple[str, ...]
    proposed_count: int | None = None

    def question(self):
        if (len(set(self.ring)) != len(self.ring) or len(self.ring) != 3
                or any(p not in self.ring for p in (self.asker, self.respondent, self.recipient))
                or len({self.asker, self.respondent, self.recipient}) != 3):
            raise ValueError("鲍信分发场景须有三个不同的公开角色和确定座次")
        if self.proposed_count is not None and (type(self.proposed_count) is not int or self.proposed_count < 0):
            raise ValueError("数量命题必须是明确的非负整数，不可传入任意通信载荷")
        proposition = {"kind": "count_equals", "count": self.proposed_count} if self.proposed_count is not None else {"kind": "last_recipient"}
        return {"schema": "cooperation-context-v1", "topic": "baoxin_distribution", "meaning": "proposition",
                "asker": self.asker, "respondent": self.respondent, "target": self.recipient,
                "plan": {"operation": "baoxin_distribution_scenario", "targets": [self.recipient],
                         "ring": list(self.ring), "proposition": proposition},
                "text": (f"这次分发方案中的命题：你当前有{self.proposed_count}张杀，是否成立？"
                         if self.proposed_count is not None else "按本次公开分发顺序，最后一张杀会到地主，是否成立？"),
                "window_id": None, "layer": None}


class ProbeBudget:
    """事实/数量每对农民每个回答者手牌时期一次；建议每个决策一次。"""
    def __init__(self):
        self.used = set()

    @staticmethod
    def key(offer, generation, hand_epoch):
        domain = ("hidden_state", hand_epoch) if offer["meaning"] in {"resource_fact", "capability", "proposition"} else ("decision", generation)
        return offer["asker"], offer["respondent"], *domain

    def permits(self, offer, generation, hand_epoch):
        return self.key(offer, generation, hand_epoch) not in self.used

    def reserve(self, offer, generation, hand_epoch):
        key = self.key(offer, generation, hand_epoch)
        if key in self.used:
            raise ValueError("本AI建模约束禁止同一隐藏状态连续枚举、二分或编码探测")
        self.used.add(key)


class CooperationAdapter(RuleAdapter):
    adapter_version = "post-c8-public-cooperation-v1"

    def __init__(self, domain, generation, actor, choices):
        self.domain, self.generation, self.actor, self.choices = domain, generation, actor, choices

    def audit_state(self):
        return {"domain": self.domain, "generation": self.generation, "actor": self.actor, "choices": self.choices}

    def enumerate_legal_actions(self, state, context):
        if context.actor_id != self.actor:
            return ()
        return tuple(LegalAction(action_type=ActionType.CHOOSE_OPTION, actor_id=self.actor, payload=choice)
                     for choice in self.choices)

    def apply_action(self, state, context, action):
        # 公共 apply_action 重新枚举、验证签名；问答不移动牌也不执行生产 step。
        return state


def current_answer(view, topic, *, respondent=None, target=None, plan=None):
    """只解释关联命题，不把建议当成手牌事实；过期回答仅留作公开历史。"""
    decision = view.get("decision") or {}
    if not decision.get("decision_id"):
        return None
    window = view.get("nullification", {}).get("window")
    for record in reversed(view.get("cooperation_history", [])):
        if not record.get("valid") or record["topic"] != topic or record["meaning"] != MEANINGS[topic]:
            continue
        if record.get("decision_id") != decision.get("decision_id") or record["asker"] != view["viewer"]:
            continue
        if respondent is not None and record["respondent"] != respondent:
            continue
        if target is not None and record["target"] != target:
            continue
        if plan is not None and record["plan"] != plan:
            continue
        if record["window_id"] is not None and (not window or not window["active"] or
                (record["window_id"], record["layer"]) != (window["id"], window["layer"])):
            continue
        answer = record.get("answer")
        return answer if answer in ("YES", "NO") else None
    return None
