"""进程内会话 API；座位指固定物理座位，当前座次由视图另外提供。"""

from __future__ import annotations

from dataclasses import dataclass, field
import copy
import hashlib
import hmac
import secrets
import threading
import time
from typing import Mapping

from .actions import InvalidActionError, RuleRegistry, ActionContext, enumerate_legal_actions, apply_action
from .playable_communication import (CooperationAdapter, ProbeBudget, question_offers,
                                     ANSWERS, ANSWER_LABELS)
from .playable_information import PublicInformation, INFORMATION_VERSION
from .model import ZoneRef
from .playable_config import GameConfig, canonical, derive_seed, integer
from .playable_game import PlayableGame
from .playable_view import ViewProjector


class RuntimeProtocolError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(f"{code}: {message}")


@dataclass(frozen=True)
class HumanController:
    """人工席位标记；由 submit_action 提交签名候选。"""


def _plain(value):
    if isinstance(value, Mapping):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain(v) for v in value]
    return value


@dataclass
class _Session:
    game: PlayableGame
    secret: bytes = field(default_factory=lambda: secrets.token_bytes(32))
    lock: threading.RLock = field(default_factory=threading.RLock)
    generation: int = 0
    accepted: int = 0
    legal: tuple | None = None
    tokens: dict = field(default_factory=dict)
    receipts: dict = field(default_factory=dict)
    requests: dict = field(default_factory=dict)
    controllers: dict = field(default_factory=dict)
    event_logs: dict = field(default_factory=dict)
    core_event_cursor: int = 0
    opening_event_cursor: int = 0
    terminal: dict | None = None
    semantic_digest: object = field(default_factory=hashlib.sha256)
    spy_duel_reached: bool = False
    questions: list = field(default_factory=list)
    pending_question: dict | None = None
    question_epochs: dict = field(default_factory=dict)
    communication_generation: int = 0
    communication_receipts: dict = field(default_factory=dict)
    communication_requests: dict = field(default_factory=dict)
    probe_budget: object = field(default_factory=ProbeBudget)
    information: object = None
    committed_action: tuple | None = None
    public_information_digest: object = field(default_factory=hashlib.sha256)
    public_information_counts: dict = field(default_factory=dict)

    def __post_init__(self):
        self.projector = ViewProjector(self.game, self.secret)
        self.information = PublicInformation(self.game.config.player_ids)
        self.event_logs = {pid: [] for pid in self.game.config.player_ids}
        for pid in self.game.config.player_ids:
            if pid in self.game.config.human_player_ids:
                self.controllers[pid] = HumanController()
            else:
                from .production_ai import ProductionAIController
                self.controllers[pid] = ProductionAIController(
                    seed=derive_seed(self.game.config.ai_seed, f"seat:{pid}"),
                    parameters=dict(self.game.config.ai_parameters))


class GameService:
    def __init__(self) -> None:
        self._sessions: dict[str, _Session] = {}
        self._lock = threading.RLock()

    def create_game(self, config: GameConfig | dict) -> str:
        cfg = config if type(config) is GameConfig else GameConfig.from_dict(config)
        session = _Session(PlayableGame(cfg))
        sid = secrets.token_hex(16)
        with self._lock:
            self._sessions[sid] = session
        self._capture_events(session)
        return sid

    def _get(self, session_id: str) -> _Session:
        if type(session_id) is not str:
            raise RuntimeProtocolError("UNKNOWN_SESSION", "会话标识必须是字符串")
        with self._lock:
            session = self._sessions.get(session_id)
        if session is None:
            raise RuntimeProtocolError("UNKNOWN_SESSION", "会话不存在")
        return session

    @staticmethod
    def _seat(session: _Session, seat: int) -> str:
        if type(seat) is not int or f"p{seat}" not in session.game.config.player_ids:
            raise RuntimeProtocolError("INVALID_SEAT", "物理座位不属于本局")
        return f"p{seat}"

    @staticmethod
    def _decision_id(sid: str, s: _Session) -> str:
        # 不是 GameState.revision：包括不移动实体牌的 select/unselect 等。
        return f"{sid}:{s.generation}"

    def _prepare(self, sid: str, s: _Session) -> None:
        if s.legal is not None or s.terminal or s.game.is_finished:
            return
        s.legal = s.game.legal_actions()
        if not s.legal:
            raise RuntimeProtocolError("EMPTY_LEGAL_SET", "非终局没有合法动作")
        did = self._decision_id(sid, s)
        s.tokens = {}
        for ordinal, action in enumerate(s.legal):
            message = canonical([sid, did, action.actor_id, ordinal, action.action_id]).encode()
            token = hmac.new(s.secret, message, hashlib.sha256).hexdigest()
            s.tokens[token] = (ordinal, action)

    def _view(self, sid: str, s: _Session, pid: str, *, with_communication=True) -> dict:
        result = s.projector.view(pid)
        if not s.terminal and not s.game.is_finished and s.game.actor == pid:
            self._prepare(sid, s)
            result["decision"] = {"decision_id": self._decision_id(sid, s),
                "seat": int(pid[1:]), "options": [s.projector.action(action, pid, ordinal, token)
                    for token, (ordinal, action) in s.tokens.items()]}
        if s.terminal:
            result["actor"] = None
        result["status"] = self._result(s)["status"]
        result["information_version"] = INFORMATION_VERSION
        result["nullification"] = s.information.view()
        result["public_known_hand_keys"] = s.information.public_hand_keys()
        result["cooperation_history"] = [dict(copy.deepcopy(q),
            valid=q["valid"] and result["status"] == "IN_PROGRESS" and q["generation"] == s.generation,
            decision_id=self._decision_id(sid, s) if q["generation"] == s.generation else None)
            for q in s.questions[-16:]]
        result["communication"] = None
        if with_communication and not s.terminal and not s.game.is_finished:
            if s.pending_question and s.pending_question["respondent"] == pid:
                _, _, actions = self._communication_actions(sid, s, pid, "answer")
                result["communication"] = {"kind": "answer", "question": copy.deepcopy(s.pending_question),
                    "options": [{"action_id": a.action_id, "answer": a.payload["answer"],
                                 "description": ANSWER_LABELS[a.payload["answer"]]} for a in actions]}
            elif result["decision"] and not s.pending_question:
                _, _, actions = self._communication_actions(sid, s, pid, "ask", view=result)
                result["communication"] = {"kind": "ask", "decision_id": self._decision_id(sid, s),
                    "options": [{"action_id": a.action_id, "question": _plain(a.payload["question"])} for a in actions]}
        return result

    def _communication_actions(self, sid, s, pid, kind, *, view=None):
        choices = []
        if kind == "ask" and pid == s.game.actor and not s.pending_question:
            view = view or self._view(sid, s, pid, with_communication=False)
            already_asked = any(q["generation"] == s.generation and q["asker"] == pid for q in s.questions[-16:])
            if not already_asked:
                choices = [{"operation": "ask_cooperation", "question": q} for q in question_offers(view)
                    if s.probe_budget.permits(q, s.generation, s.information.hand_epochs[q["respondent"]])]
        elif kind == "answer" and s.pending_question and s.pending_question["respondent"] == pid:
            choices = [{"operation": "answer_cooperation", "question_id": s.pending_question["question_id"],
                        "answer": answer} for answer in ANSWERS]
        registry = RuleRegistry()
        registry.register("post_c8_communication", kind, CooperationAdapter(
            s.secret.hex() + sid, (s.generation, s.communication_generation), pid, choices))
        context = ActionContext(mode="post_c8_communication", phase=kind, actor_id=pid,
            expected_revision=s.game.state.revision,
            metadata={"decision": s.generation, "communication": s.communication_generation})
        return registry, context, enumerate_legal_actions(s.game.state, context, registry)

    @staticmethod
    def _communication_request(s, kind, pid, scope, token, request_id):
        if type(scope) is not str or type(token) is not str:
            raise RuntimeProtocolError("INVALID_REQUEST", "问答关联号与签名必须是字符串")
        if request_id is not None and (type(request_id) is not str or not 1 <= len(request_id) <= 128):
            raise RuntimeProtocolError("INVALID_REQUEST", "请求号必须为1..128字符")
        key = (kind, pid, scope, token)
        request_key = (pid, request_id)
        if request_id is not None and request_key in s.communication_requests and s.communication_requests[request_key] != key:
            raise RuntimeProtocolError("REQUEST_ID_CONFLICT", "同一问答请求号不能发送不同内容")
        return key, request_key, s.communication_receipts.get(key)

    def _save_communication(self, s, key, request_key, request_id, receipt, event):
        s.communication_receipts[key] = receipt
        if request_id is not None:
            s.communication_requests[request_key] = key
        s.communication_generation += 1
        try:
            self._publish_information(s, event)
        except Exception as exc:
            s.terminal = {"status": "ERROR", "reason": "COMMUNICATION_PROJECTION_FAILED",
                "steps": s.accepted, "winning_players": [], "winner": None}
            receipt["status"] = "ERROR"
            raise RuntimeProtocolError("COMMUNICATION_PROJECTION_FAILED", "问答回执已保存，公共投影失败，已停止") from exc
        return copy.deepcopy(receipt)

    def ask_question(self, session_id, seat, decision_id, action_id, request_id=None):
        s = self._get(session_id)
        with s.lock:
            pid = self._seat(s, seat)
            key, request_key, old = self._communication_request(s, "ask", pid, decision_id, action_id, request_id)
            if old:
                if request_id is not None:
                    s.communication_requests[request_key] = key
                return {**copy.deepcopy(old), "duplicate": True}
            if s.terminal or s.game.is_finished:
                raise RuntimeProtocolError("GAME_FINISHED", "对局已结束")
            if decision_id != self._decision_id(session_id, s):
                raise RuntimeProtocolError("STALE_DECISION", "问题所关联的游戏决策已过期")
            if pid != s.game.actor:
                raise RuntimeProtocolError("WRONG_ACTOR", "只能由当前游戏行动者提出场景问题")
            if s.pending_question:
                raise RuntimeProtocolError("ANSWER_PENDING", "当前问题尚待回答或选择不回答")
            registry, context, actions = self._communication_actions(session_id, s, pid, "ask")
            action = next((a for a in actions if a.action_id == action_id), None)
            if action is None:
                raise RuntimeProtocolError("INVALID_ACTION", "问题签名、公开语境或探测预算不匹配")
            apply_action(s.game.state, context, action, registry)
            # payload 为冻结映射；经规范 JSON 转成普通关联数据，无客户端任意载荷。
            offer = _plain(action.payload["question"])
            s.probe_budget.reserve(offer, s.generation, s.information.hand_epochs[offer["respondent"]])
            record = dict(offer, question_id=f"question:{len(s.questions) + 1}",
                          generation=s.generation, answer=None, valid=True)
            s.questions.append(record)
            s.pending_question = record
            s.question_epochs[record["question_id"]] = (s.information.hand_epochs[pid],
                s.information.hand_epochs[record["respondent"]])
            receipt = {"accepted": True, "duplicate": False, "question_id": record["question_id"]}
            return self._save_communication(s, key, request_key, request_id, receipt,
                                           {"type": "cooperation_question", "question": copy.deepcopy(record)})

    def answer_question(self, session_id, seat, question_id, action_id, request_id=None):
        s = self._get(session_id)
        with s.lock:
            pid = self._seat(s, seat)
            key, request_key, old = self._communication_request(s, "answer", pid, question_id, action_id, request_id)
            if old:
                if request_id is not None:
                    s.communication_requests[request_key] = key
                return {**copy.deepcopy(old), "duplicate": True}
            q = s.pending_question
            if s.terminal or s.game.is_finished:
                raise RuntimeProtocolError("GAME_FINISHED", "对局已结束")
            if not q or q["question_id"] != question_id or q["generation"] != s.generation:
                raise RuntimeProtocolError("STALE_QUESTION", "问题已回答或所属游戏决策已过期")
            if q["respondent"] != pid:
                raise RuntimeProtocolError("WRONG_ACTOR", "只能由问题指定的队友回答")
            registry, context, actions = self._communication_actions(session_id, s, pid, "answer")
            action = next((a for a in actions if a.action_id == action_id), None)
            if action is None:
                raise RuntimeProtocolError("INVALID_ACTION", "回答签名、会话或当前问题不匹配")
            apply_action(s.game.state, context, action, registry)
            q["answer"] = action.payload["answer"]
            s.pending_question = None
            receipt = {"accepted": True, "duplicate": False, "question_id": question_id, "answer": q["answer"]}
            return self._save_communication(s, key, request_key, request_id, receipt,
                {"type": "cooperation_answer", "question": copy.deepcopy(q)})

    def submit_signal(self, *args, **kwargs):
        raise RuntimeProtocolError("LEGACY_SIGNAL_REMOVED", "自动桃/杀共享已移除，请使用具体公开问答")

    def get_player_view(self, session_id: str, viewer_seat: int) -> dict:
        s = self._get(session_id)
        with s.lock:
            pid = self._seat(s, viewer_seat)
            return self._view(session_id, s, pid)

    def get_omniscient_debug_view(self, session_id: str) -> dict:
        s = self._get(session_id)
        with s.lock:
            if not s.game.config.omniscient_debug or s.game.config.control != "ALL_HUMAN":
                raise RuntimeProtocolError("DEBUG_DISABLED", "未显式开启全手控全知观察")
            # 仍不导出牌堆未来顺序、密钥或内部状态；全知只合并座位视角。
            return {"schema": "omniscient-debug-view-v1", "views": [
                self._view(session_id, s, pid) for pid in s.game.config.player_ids]}

    def submit_action(self, session_id: str, seat: int, decision_id: str,
                      action_id: str, request_id: str | None = None) -> dict:
        s = self._get(session_id)
        with s.lock:
            pid = self._seat(s, seat)
            if type(decision_id) is not str or type(action_id) is not str:
                raise RuntimeProtocolError("INVALID_REQUEST", "决策号和动作签名必须是字符串")
            if request_id is not None and (type(request_id) is not str or not 1 <= len(request_id) <= 128):
                raise RuntimeProtocolError("INVALID_REQUEST", "请求号必须为1..128字符")
            key = (pid, decision_id, action_id)
            request_key = (pid, request_id)
            if request_id is not None and request_key in s.requests and s.requests[request_key] != key:
                raise RuntimeProtocolError("REQUEST_ID_CONFLICT", "同一请求号不能提交不同内容")
            if key in s.receipts:
                if request_id is not None:
                    s.requests[request_key] = key
                return {**s.receipts[key], "duplicate": True}
            if s.terminal or s.game.is_finished:
                raise RuntimeProtocolError("GAME_FINISHED", "对局已结束或已中止")
            if decision_id != self._decision_id(session_id, s):
                raise RuntimeProtocolError("STALE_DECISION", "决策已过期，请重新读取当前玩家视图")
            if pid != s.game.actor:
                raise RuntimeProtocolError("WRONG_ACTOR", "此决策不属于提交座位")
            if s.pending_question:
                raise RuntimeProtocolError("ANSWER_PENDING", "请让指定队友回答或选择不回答，再提交游戏动作")
            self._prepare(session_id, s)
            choice = s.tokens.get(action_id)
            if choice is None:
                raise RuntimeProtocolError("INVALID_ACTION", "签名、会话或当前合法集合不匹配")
            ordinal, action = choice
            if action.actor_id != pid:
                raise RuntimeProtocolError("WRONG_ACTOR", "生产动作的行动者与当前座位不符")
            selected_semantics = s.projector.action(action, pid, ordinal, "")
            def without_session_refs(value):
                if isinstance(value, dict):
                    return {k: without_session_refs(v) for k, v in value.items() if k not in ("ref", "action_id")}
                if isinstance(value, list):
                    return [without_session_refs(v) for v in value]
                return value
            staged_digest = s.semantic_digest.copy()
            staged_digest.update(canonical([s.generation, pid, without_session_refs(selected_semantics)]).encode())
            receipt = {"accepted": True, "duplicate": False, "decision_id": decision_id,
                       "accepted_steps": s.accepted + 1, "status": "COMMITTED"}
            try:
                s.game.step(action.action_id)
            except InvalidActionError as exc:
                raise RuntimeProtocolError("ENGINE_REJECTED", "生产引擎拒绝了过期或无效动作") from exc
            # 提交后的第一组赋值关闭旧决策并保存回执，不夹入可失败的投影／统计调用。
            s.accepted = receipt["accepted_steps"]
            s.generation += 1
            s.legal = None
            s.tokens = {}
            s.receipts[key] = receipt
            if request_id is not None:
                s.requests[request_key] = key
            error_code = "POST_COMMIT_BOOKKEEPING_FAILED"
            try:
                s.semantic_digest = staged_digest
                s.committed_action = (pid, action.payload.get("operation"))
                if s.game.config.mode == "identity8" and s.game.core:
                    roles = s.game.current_roles()
                    alive_roles = [roles[p.player_id] for p in s.game.state.players if p.alive]
                    s.spy_duel_reached |= sorted(alive_roles) == ["lord", "spy"]
                if s.accepted >= s.game.config.max_steps and not s.game.is_finished:
                    s.terminal = {"status": "ABORTED", "reason": "MAX_STEPS", "steps": s.accepted,
                                  "winning_players": [], "winner": None}
                receipt["status"] = self._result(s)["status"]
                error_code = "EVENT_PROJECTION_FAILED"
                self._capture_events(s)
            except Exception as exc:
                s.terminal = {"status": "ERROR", "reason": error_code,
                    "winning_players": [], "winner": None, "steps": s.accepted}
                receipt["status"] = "ERROR"
                raise RuntimeProtocolError(error_code, "提交已保存，后续统计或投影失败，对局已停止") from exc
            return dict(receipt)

    def advance_until_human_or_terminal(self, session_id: str, *, max_steps: int = 32,
                                        time_slice_ms: int = 50) -> dict:
        integer(max_steps, "自动推进步数", 1)
        integer(time_slice_ms, "自动推进时间片毫秒", 1)
        s = self._get(session_id)
        start = time.monotonic()
        done = communications = 0
        with s.lock:
            while done + communications < max_steps:
                result = self._result(s)
                if result["status"] != "IN_PROGRESS":
                    return {"stop": "TERMINAL", "advanced": done, "communication_steps": communications, "result": result}
                answering = s.pending_question is not None
                actor = s.pending_question["respondent"] if answering else s.game.actor
                controller = s.controllers[actor]
                if isinstance(controller, HumanController):
                    return {"stop": "HUMAN_ANSWER" if answering else "HUMAN", "advanced": done,
                            "communication_steps": communications, "seat": int(actor[1:])}
                if done + communications and (time.monotonic() - start) * 1000 >= time_slice_ms:
                    break
                view = self._view(session_id, s, actor)
                # AI 的问答和出牌均只消费本座位合法视图；不传 core/config/游戏 seed。
                controller.observe(s.event_logs[actor])
                if answering:
                    token = controller.answer_question(view)
                    self.answer_question(session_id, int(actor[1:]), s.pending_question["question_id"], token)
                    communications += 1
                    continue
                question = controller.choose_question(view)
                if question is not None:
                    self.ask_question(session_id, int(actor[1:]), view["decision"]["decision_id"], question)
                    communications += 1
                    continue
                token = controller.choose(view)
                self.submit_action(session_id, int(actor[1:]), view["decision"]["decision_id"], token)
                done += 1
            return {"stop": "YIELD", "advanced": done, "communication_steps": communications}

    def get_events(self, session_id: str, viewer_seat: int, cursor: int = 0) -> dict:
        s = self._get(session_id)
        with s.lock:
            pid = self._seat(s, viewer_seat)
            integer(cursor, "事件游标", 0)
            events = s.event_logs[pid]
            if cursor > len(events):
                raise RuntimeProtocolError("INVALID_CURSOR", "事件游标超出本座位事件流")
            return {"events": copy.deepcopy(events[cursor:]), "cursor": len(events)}

    @staticmethod
    def _result(s: _Session) -> dict:
        return dict(s.terminal) if s.terminal else s.game.result()

    def get_result(self, session_id: str) -> dict:
        s = self._get(session_id)
        with s.lock:
            return copy.deepcopy(self._result(s))

    def get_ai_trace(self, session_id: str, viewer_seat: int) -> dict | None:
        """仅取指定座位自己的评分；不能用对手座位日志填充玩家视图。"""
        s = self._get(session_id)
        with s.lock:
            pid = self._seat(s, viewer_seat)
            return copy.deepcopy(getattr(s.controllers[pid], "last_trace", None))

    def abort_game(self, session_id: str) -> dict:
        s = self._get(session_id)
        with s.lock:
            if self._result(s)["status"] == "IN_PROGRESS":
                s.terminal = {"status": "ABORTED", "reason": "USER_STOP",
                    "steps": s.accepted, "winner": None, "winning_players": []}
            return self._result(s)

    def _capture_events(self, s: _Session) -> None:
        game = s.game
        for event in game.opening_events[s.opening_event_cursor:]:
            for pid in game.config.player_ids:
                if event["type"] == "bid" or pid == event["actor"] or (
                        game.config.mode == "2v2" and game.roles[pid] == game.roles[event["actor"]]) or (
                        game.config.mode.startswith("identity") and game.roles[event["actor"]] == "lord"):
                    s.event_logs[pid].append(dict(event))
        s.opening_event_cursor = len(game.opening_events)
        if game.core:
            new_events = game.core.events[s.core_event_cursor:]
            for pid in game.config.player_ids:
                s.event_logs[pid].extend(s.projector.events(pid, new_events))
            for event in s.information.after_commit(game, new_events, s.generation, s.committed_action):
                self._publish_information(s, event)
            s.core_event_cursor = len(game.core.events)
            s.committed_action = None
            for q in s.questions:
                epochs = (s.information.hand_epochs[q["asker"]], s.information.hand_epochs[q["respondent"]])
                if q["valid"] and (q["generation"] != s.generation or epochs != s.question_epochs[q["question_id"]]):
                    q["valid"] = False
                    self._publish_information(s, {"type": "cooperation_expired", "question_id": q["question_id"],
                                                  "reason": "decision_or_hand_changed"})

    @staticmethod
    def _publish_information(s: _Session, event: dict) -> None:
        # 全场完全相同的最小公共事件；不合并任何座位私有投影或 AI 解释。
        for log in s.event_logs.values():
            log.append(copy.deepcopy(event))
        s.public_information_digest.update(canonical(event).encode())
        kind = event["type"]
        s.public_information_counts[kind] = s.public_information_counts.get(kind, 0) + 1

    def close_game(self, session_id: str) -> None:
        with self._lock:
            if session_id not in self._sessions:
                raise RuntimeProtocolError("UNKNOWN_SESSION", "会话不存在")
            del self._sessions[session_id]


_default_service = GameService()
create_game = _default_service.create_game
get_player_view = _default_service.get_player_view
submit_action = _default_service.submit_action
advance_until_human_or_terminal = _default_service.advance_until_human_or_terminal
get_events = _default_service.get_events
get_result = _default_service.get_result
close_game = _default_service.close_game

ask_question = _default_service.ask_question
answer_question = _default_service.answer_question
