"""测试专用双人纵向切片的严格规则重执行回放。

保存的状态、事件与随机结果只作为重执行的期望值。本模块重放时会重新
构造 :class:`TestOnlyDuelGame`，重新枚举合法动作，并把记录的 ``action_id``
通过真实 ``step`` 路径提交；绝不会用保存的状态快照推进游戏。
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from types import MappingProxyType
from typing import Any, Iterable, Mapping, Sequence

from .actions import ActionContext, LegalAction
from .duel import (
    TEST_ONLY_DUEL_MODE,
    DeterministicReferenceController,
    DuelSafetyLimitError,
    TestOnlyDuelGame,
)
from .engine import ENGINE_VERSION, canonical_state_snapshot
from .replay import canonical_json, sha256_value, state_sha256


REEXECUTION_SCHEMA = "sgs-duel-reexecution-v1"
_EVENT_CHAIN_ANCHOR = sha256_value(
    {"schema": REEXECUTION_SCHEMA, "stream": "event_hash_chain"}
)


class DuelReplayFormatError(ValueError):
    """回放文件的结构或总记录哈希无效。"""


class ReplayDivergenceError(AssertionError):
    """规则重执行首次偏离已记录期望时抛出。"""

    def __init__(
        self,
        kind: str,
        index: int | None,
        message: str,
        *,
        expected: object = None,
        actual: object = None,
    ) -> None:
        location = "初始化/终局" if index is None else f"索引{index}"
        super().__init__(f"规则重执行在{kind}的{location}发生偏差：{message}")
        self.kind = kind
        self.index = index
        self.expected = expected
        self.actual = actual


def _plain(value: object) -> Any:
    """Return a detached JSON value with the same canonical representation."""

    return json.loads(canonical_json(value))


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, tuple):
        return tuple(_freeze(item) for item in value)
    return value


def _require_mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise DuelReplayFormatError(f"{label}必须是JSON对象")
    return value


def _require_sequence(value: object, label: str) -> Sequence[object]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise DuelReplayFormatError(f"{label}必须是JSON数组")
    return value


def _require_exact_fields(
    value: Mapping[str, object], required: set[str], label: str
) -> None:
    missing = sorted(required.difference(value))
    extra = sorted(set(value).difference(required))
    if missing:
        raise DuelReplayFormatError(f"{label}缺少字段：{', '.join(missing)}")
    if extra:
        raise DuelReplayFormatError(f"{label}包含未知字段：{', '.join(extra)}")


def _context_value(context: ActionContext) -> dict[str, object]:
    return _plain(
        {
            "mode": context.mode,
            "phase": context.phase,
            "actor_id": context.actor_id,
            "turn_player_id": context.turn_player_id,
            "response_window_id": context.response_window_id,
            "expected_revision": context.expected_revision,
            "metadata": context.metadata,
        }
    )


def _action_value(action: LegalAction) -> dict[str, object]:
    return _plain(
        {
            "action_id": action.action_id,
            "action_type": action.action_type.value,
            "actor_id": action.actor_id,
            "card_instance_id": action.card_instance_id,
            "target_ids": action.target_ids,
            "skill_id": action.skill_id,
            "payload": action.payload,
        }
    )


def _event_values(game: TestOnlyDuelGame) -> list[dict[str, object]]:
    return [_plain(event.to_replay_dict()) for event in game.events]


def _rng_values(game: TestOnlyDuelGame) -> list[dict[str, object]]:
    return [_plain(call.to_dict()) for call in game.rng_calls]


def _build_event_hash_chain(events: Sequence[object]) -> tuple[str, ...]:
    """Build a forward SHA-256 chain over the complete canonical event stream."""

    previous = _EVENT_CHAIN_ANCHOR
    chain: list[str] = []
    for index, event in enumerate(events):
        previous = sha256_value(
            {"index": index, "previous_event_sha256": previous, "event": event}
        )
        chain.append(previous)
    return tuple(chain)


def _execution_hash(game: TestOnlyDuelGame) -> str:
    return sha256_value(game.execution_snapshot)


def _game_state_hash(game: TestOnlyDuelGame) -> str:
    return state_sha256(canonical_state_snapshot(game.state))


def _deck_definition(keys: Sequence[str]) -> dict[str, object]:
    cards = TestOnlyDuelGame._build_cards(keys)
    return {
        "deck_id": cards[0].deck_id if cards else "",
        "cards": [
            {
                "position": index,
                "instance_id": card.instance_id,
                "deck_id": card.deck_id,
                "card_key": card.card_key,
                "card_name": card.card_name,
                "card_type": card.card_type,
                "suit": card.suit,
                "color": card.color,
                "rank": card.rank,
                "card_variant": card.card_variant,
                "equipment_slot": card.equipment_slot,
                "distance_modifier": card.distance_modifier,
            }
            for index, card in enumerate(cards)
        ],
    }


def _ruleset_value(game: TestOnlyDuelGame) -> dict[str, str]:
    binding = game.registry.binding_value(TEST_ONLY_DUEL_MODE, game.phase.value)
    value = {
        "mode_id": TEST_ONLY_DUEL_MODE,
        "adapter_type": str(binding["adapter_type"]),
        "ruleset_version": str(binding["adapter_version"]),
        "registry_fingerprint": str(binding["registry_fingerprint"]),
    }
    value["ruleset_hash"] = sha256_value(value)
    return value


_HEADER_FIELDS = {
    "schema_version",
    "engine_version",
    "mode_id",
    "test_only",
    "formal_result",
    "ruleset_version",
    "ruleset_hash",
    "registry_fingerprint",
    "initial_configuration",
    "deck_definition",
    "deck_hash",
    "seed",
    "initial_rng_state",
    "initial_rng_state_sha256",
    "initial_rng_call_count",
    "initial_event_count",
    "initial_execution_hash",
    "initial_game_state_hash",
}
_DECISION_FIELDS = {
    "index",
    "context",
    "context_sha256",
    "legal_actions",
    "legal_action_set_sha256",
    "chosen_action_id",
    "chosen_action",
    "state_before_sha256",
    "state_after_sha256",
    "execution_before_sha256",
    "execution_after_sha256",
    "rng_start",
    "rng_end",
    "event_start",
    "event_end",
}
_OUTCOME_FIELDS = {
    "winner_id",
    "finish_reason",
    "step_count",
    "turn_count",
    "decision_count",
    "random_consumption_count",
    "event_count",
    "event_chain_tip",
    "final_execution_hash",
    "final_game_state_hash",
}
_ROOT_FIELDS = {
    "header",
    "decisions",
    "random_consumptions",
    "events",
    "event_hash_chain",
    "outcome",
    "record_sha256",
}


@dataclass(frozen=True, slots=True)
class DuelReexecutionReplay:
    """完整、可保存且可由真实规则路径重新执行的测试单挑记录。"""

    header: Mapping[str, object]
    decisions: tuple[Mapping[str, object], ...]
    random_consumptions: tuple[Mapping[str, object], ...]
    events: tuple[Mapping[str, object], ...]
    event_hash_chain: tuple[str, ...]
    outcome: Mapping[str, object]
    record_sha256: str = field(default="")

    def __post_init__(self) -> None:
        header = _plain(_require_mapping(self.header, "header"))
        decisions = tuple(
            _plain(_require_mapping(item, f"decisions[{index}]"))
            for index, item in enumerate(_require_sequence(self.decisions, "decisions"))
        )
        random_consumptions = tuple(
            _plain(_require_mapping(item, f"random_consumptions[{index}]"))
            for index, item in enumerate(
                _require_sequence(self.random_consumptions, "random_consumptions")
            )
        )
        events = tuple(
            _plain(_require_mapping(item, f"events[{index}]"))
            for index, item in enumerate(_require_sequence(self.events, "events"))
        )
        event_hash_chain = tuple(
            item
            for item in _require_sequence(self.event_hash_chain, "event_hash_chain")
        )
        if any(not isinstance(item, str) or len(item) != 64 for item in event_hash_chain):
            raise DuelReplayFormatError("event_hash_chain每一项必须是64位SHA-256")
        outcome = _plain(_require_mapping(self.outcome, "outcome"))
        _require_exact_fields(header, _HEADER_FIELDS, "header")
        _require_exact_fields(outcome, _OUTCOME_FIELDS, "outcome")
        for index, decision in enumerate(decisions):
            _require_exact_fields(decision, _DECISION_FIELDS, f"decisions[{index}]")
            if decision["index"] != index:
                raise DuelReplayFormatError("决策索引必须从0连续递增")

        if header["schema_version"] != REEXECUTION_SCHEMA:
            raise DuelReplayFormatError("不支持的规则重执行回放schema")
        if header["mode_id"] != TEST_ONLY_DUEL_MODE:
            raise DuelReplayFormatError("规则重执行回放模式必须是测试专用单挑")
        if header["test_only"] is not True or header["formal_result"] is not False:
            raise DuelReplayFormatError("测试专用回放必须标记test_only=true、formal_result=false")
        if outcome["decision_count"] != len(decisions):
            raise DuelReplayFormatError("终局decision_count与决策数量不一致")
        if outcome["random_consumption_count"] != len(random_consumptions):
            raise DuelReplayFormatError("终局random_consumption_count与随机记录数量不一致")
        if outcome["event_count"] != len(events):
            raise DuelReplayFormatError("终局event_count与事件数量不一致")
        expected_event_chain = _build_event_hash_chain(events)
        if event_hash_chain != expected_event_chain:
            raise DuelReplayFormatError("event_hash_chain与完整事件流不一致")
        expected_tip = expected_event_chain[-1] if expected_event_chain else _EVENT_CHAIN_ANCHOR
        if outcome["event_chain_tip"] != expected_tip:
            raise DuelReplayFormatError("终局event_chain_tip与事件前向哈希链不一致")
        if header["deck_hash"] != sha256_value(header["deck_definition"]):
            raise DuelReplayFormatError("牌堆定义哈希不匹配")
        if header["initial_rng_state_sha256"] != sha256_value(
            header["initial_rng_state"]
        ):
            raise DuelReplayFormatError("初始随机状态哈希不匹配")

        object.__setattr__(self, "header", _freeze(header))
        object.__setattr__(self, "decisions", _freeze(decisions))
        object.__setattr__(self, "random_consumptions", _freeze(random_consumptions))
        object.__setattr__(self, "events", _freeze(events))
        object.__setattr__(self, "event_hash_chain", event_hash_chain)
        object.__setattr__(self, "outcome", _freeze(outcome))

        calculated = sha256_value(self._material_dict())
        supplied = self.record_sha256
        if supplied:
            if not isinstance(supplied, str) or len(supplied) != 64:
                raise DuelReplayFormatError("record_sha256必须是64位SHA-256")
            if supplied != calculated:
                raise DuelReplayFormatError("总记录SHA-256不匹配，回放可能被篡改")
        object.__setattr__(self, "record_sha256", calculated)

    def _material_dict(self) -> dict[str, object]:
        return {
            "header": _plain(self.header),
            "decisions": _plain(self.decisions),
            "random_consumptions": _plain(self.random_consumptions),
            "events": _plain(self.events),
            "event_hash_chain": list(self.event_hash_chain),
            "outcome": _plain(self.outcome),
        }

    def verify_integrity(self) -> bool:
        if sha256_value(self._material_dict()) != self.record_sha256:
            raise DuelReplayFormatError("总记录SHA-256不匹配，回放可能被篡改")
        return True

    def to_dict(self) -> dict[str, object]:
        value = self._material_dict()
        value["record_sha256"] = self.record_sha256
        return value

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "DuelReexecutionReplay":
        root = _require_mapping(value, "回放根节点")
        _require_exact_fields(root, _ROOT_FIELDS, "回放根节点")
        record_hash = root["record_sha256"]
        if not isinstance(record_hash, str) or not record_hash:
            raise DuelReplayFormatError("回放根节点record_sha256必须是非空字符串")
        return cls(
            header=_require_mapping(root["header"], "header"),
            decisions=tuple(_require_sequence(root["decisions"], "decisions")),
            random_consumptions=tuple(
                _require_sequence(root["random_consumptions"], "random_consumptions")
            ),
            events=tuple(_require_sequence(root["events"], "events")),
            event_hash_chain=tuple(
                _require_sequence(root["event_hash_chain"], "event_hash_chain")
            ),
            outcome=_require_mapping(root["outcome"], "outcome"),
            record_sha256=record_hash,
        )

    def save(self, path: str | Path) -> Path:
        target = Path(path)
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(canonical_json(self.to_dict()) + "\n", encoding="utf-8")
        except OSError as exc:
            raise DuelReplayFormatError(f"保存规则重执行回放失败：{target}：{exc}") from exc
        return target

    @classmethod
    def load(cls, path: str | Path) -> "DuelReexecutionReplay":
        source = Path(path)
        try:
            text = source.read_text(encoding="utf-8-sig")
            parsed = json.loads(text)
        except OSError as exc:
            raise DuelReplayFormatError(f"读取规则重执行回放失败：{source}：{exc}") from exc
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise DuelReplayFormatError("规则重执行回放不是有效UTF-8 JSON") from exc
        return cls.from_dict(_require_mapping(parsed, "回放根节点"))


@dataclass(frozen=True, slots=True)
class ReplayVerificationResult:
    verified: bool
    winner_id: str
    decision_count: int
    random_consumption_count: int
    event_count: int
    final_execution_hash: str
    final_game_state_hash: str


class _ActionIdController:
    """只从当前真实合法集合中返回指定ID，用于记录和重执行。"""

    def __init__(self, action_id: str) -> None:
        self._action_id = action_id

    def choose(
        self, legal_actions: Sequence[LegalAction], context: ActionContext
    ) -> LegalAction:
        del context
        for action in legal_actions:
            if action.action_id == self._action_id:
                return action
        raise ReplayDivergenceError(
            "decision",
            None,
            "记录动作不在当前真实合法动作集合中",
            expected=self._action_id,
            actual=[action.action_id for action in legal_actions],
        )


def record_reference_duel(
    seed: int,
    max_steps: int = 500,
    deck_keys: Iterable[str] | None = None,
    player_hp: tuple[int, int] = (4, 4),
    player_max_hp: tuple[int, int] = (4, 4),
    shuffle: bool = True,
) -> DuelReexecutionReplay:
    """运行参考控制器并记录一局可严格重执行的测试专用单挑。"""

    if isinstance(max_steps, bool) or not isinstance(max_steps, int) or max_steps < 1:
        raise ValueError("安全动作上限必须是正整数")
    keys = (
        TestOnlyDuelGame.default_deck_keys()
        if deck_keys is None
        else tuple(deck_keys)
    )
    game = TestOnlyDuelGame(
        seed=seed,
        deck_keys=keys,
        player_hp=player_hp,
        player_max_hp=player_max_hp,
        shuffle=shuffle,
    )
    controller = DeterministicReferenceController()
    ruleset = _ruleset_value(game)
    deck_definition = _deck_definition(keys)
    initial_configuration = {
        "deck_keys": list(keys),
        "player_hp": list(player_hp),
        "player_max_hp": list(player_max_hp),
        "shuffle": shuffle,
        "max_steps": max_steps,
    }
    header = {
        "schema_version": REEXECUTION_SCHEMA,
        "engine_version": ENGINE_VERSION,
        "mode_id": TEST_ONLY_DUEL_MODE,
        "test_only": True,
        "formal_result": False,
        "ruleset_version": ruleset["ruleset_version"],
        "ruleset_hash": ruleset["ruleset_hash"],
        "registry_fingerprint": ruleset["registry_fingerprint"],
        "initial_configuration": initial_configuration,
        "deck_definition": deck_definition,
        "deck_hash": sha256_value(deck_definition),
        "seed": seed,
        "initial_rng_state": game._rng.export_initial_state(),
        "initial_rng_state_sha256": game._rng.initial_state_sha256,
        "initial_rng_call_count": len(game.rng_calls),
        "initial_event_count": len(game.events),
        "initial_execution_hash": _execution_hash(game),
        "initial_game_state_hash": _game_state_hash(game),
    }
    decisions: list[dict[str, object]] = []
    while not game.is_finished:
        if len(decisions) >= max_steps:
            raise DuelSafetyLimitError(
                f"测试对局在{max_steps}个动作后仍未结束；禁止静默判胜或近似收尾"
            )
        context = game._context()
        legal = game.legal_actions()
        chosen = controller.choose(legal, context)
        assert chosen.action_id is not None
        rng_start = len(game.rng_calls)
        event_start = len(game.events)
        before_state_hash = _game_state_hash(game)
        before_execution_hash = _execution_hash(game)
        executed = game.step(_ActionIdController(chosen.action_id))
        if executed.action_id != chosen.action_id:
            raise RuntimeError("参考控制器提交的动作ID在真实step路径中发生变化")
        context_value = _context_value(context)
        legal_values = [_action_value(action) for action in legal]
        decisions.append(
            {
                "index": len(decisions),
                "context": context_value,
                "context_sha256": sha256_value(context_value),
                "legal_actions": legal_values,
                "legal_action_set_sha256": sha256_value(legal_values),
                "chosen_action_id": chosen.action_id,
                "chosen_action": _action_value(chosen),
                "state_before_sha256": before_state_hash,
                "state_after_sha256": _game_state_hash(game),
                "execution_before_sha256": before_execution_hash,
                "execution_after_sha256": _execution_hash(game),
                "rng_start": rng_start,
                "rng_end": len(game.rng_calls),
                "event_start": event_start,
                "event_end": len(game.events),
            }
        )

    assert game.winner_id is not None
    outcome = {
        "winner_id": game.winner_id,
        "finish_reason": "opponent_confirmed_dead",
        "step_count": game.step_count,
        "turn_count": game._runtime.turn_number,
        "decision_count": len(decisions),
        "random_consumption_count": len(game.rng_calls),
        "event_count": len(game.events),
        "event_chain_tip": _build_event_hash_chain(_event_values(game))[-1],
        "final_execution_hash": _execution_hash(game),
        "final_game_state_hash": _game_state_hash(game),
    }
    event_values = tuple(_event_values(game))
    return DuelReexecutionReplay(
        header=header,
        decisions=tuple(decisions),
        random_consumptions=tuple(_rng_values(game)),
        events=event_values,
        event_hash_chain=_build_event_hash_chain(event_values),
        outcome=outcome,
    )


def _expect_equal(
    kind: str,
    index: int | None,
    expected: object,
    actual: object,
    message: str,
) -> None:
    if _plain(expected) != _plain(actual):
        raise ReplayDivergenceError(
            kind, index, message, expected=_plain(expected), actual=_plain(actual)
        )


def _compare_sequence(
    kind: str,
    start_index: int,
    expected: Sequence[object],
    actual: Sequence[object],
) -> None:
    shared = min(len(expected), len(actual))
    for offset in range(shared):
        _expect_equal(
            kind,
            start_index + offset,
            expected[offset],
            actual[offset],
            "记录值与规则重新执行值不一致",
        )
    if len(expected) != len(actual):
        raise ReplayDivergenceError(
            kind,
            start_index + shared,
            "记录数量与规则重新执行数量不一致",
            expected=len(expected),
            actual=len(actual),
        )


def reexecute_duel_replay(
    record: DuelReexecutionReplay,
) -> ReplayVerificationResult:
    """从配置重新执行规则并严格验证每项决策、随机、事件和状态。"""

    if not isinstance(record, DuelReexecutionReplay):
        raise TypeError("规则重执行必须接收DuelReexecutionReplay")
    record.verify_integrity()
    header = record.header
    config = _require_mapping(header["initial_configuration"], "initial_configuration")
    game = TestOnlyDuelGame(
        seed=int(header["seed"]),
        deck_keys=tuple(_require_sequence(config["deck_keys"], "deck_keys")),
        player_hp=tuple(config["player_hp"]),  # type: ignore[arg-type]
        player_max_hp=tuple(config["player_max_hp"]),  # type: ignore[arg-type]
        shuffle=config["shuffle"],  # type: ignore[arg-type]
    )
    live_ruleset = _ruleset_value(game)
    _expect_equal("engine", None, header["engine_version"], ENGINE_VERSION, "引擎版本不一致")
    _expect_equal(
        "ruleset", None, header["ruleset_version"], live_ruleset["ruleset_version"], "规则版本不一致"
    )
    _expect_equal("ruleset", None, header["ruleset_hash"], live_ruleset["ruleset_hash"], "规则哈希不一致")
    _expect_equal(
        "ruleset",
        None,
        header["registry_fingerprint"],
        live_ruleset["registry_fingerprint"],
        "规则注册表指纹不一致",
    )
    _expect_equal("deck", None, header["deck_definition"], _deck_definition(tuple(config["deck_keys"])), "牌堆定义不一致")
    _expect_equal("rng", None, header["initial_rng_state"], game._rng.export_initial_state(), "初始随机状态不一致")
    _expect_equal("state", None, header["initial_execution_hash"], _execution_hash(game), "初始执行状态不一致")
    _expect_equal("state", None, header["initial_game_state_hash"], _game_state_hash(game), "初始GameState不一致")

    initial_rng_count = int(header["initial_rng_call_count"])
    initial_event_count = int(header["initial_event_count"])
    _compare_sequence(
        "rng", 0, list(record.random_consumptions[:initial_rng_count]), _rng_values(game)
    )
    _compare_sequence("event", 0, list(record.events[:initial_event_count]), _event_values(game))

    for index, decision in enumerate(record.decisions):
        if game.is_finished:
            raise ReplayDivergenceError(
                "decision", index, "记录在胜利成立后仍包含附加决策"
            )
        context = game._context()
        context_value = _context_value(context)
        legal = game.legal_actions()
        legal_values = [_action_value(action) for action in legal]
        _expect_equal("context", index, decision["context"], context_value, "行动上下文不一致")
        _expect_equal("context", index, decision["context_sha256"], sha256_value(context_value), "行动上下文哈希不一致")
        _expect_equal("legal_actions", index, decision["legal_actions"], legal_values, "完整合法动作集合不一致")
        _expect_equal(
            "legal_actions",
            index,
            decision["legal_action_set_sha256"],
            sha256_value(legal_values),
            "合法动作集合哈希不一致",
        )
        _expect_equal("state", index, decision["state_before_sha256"], _game_state_hash(game), "动作前GameState不一致")
        _expect_equal("state", index, decision["execution_before_sha256"], _execution_hash(game), "动作前执行状态不一致")
        _expect_equal("rng", index, decision["rng_start"], len(game.rng_calls), "动作前随机索引不一致")
        _expect_equal("event", index, decision["event_start"], len(game.events), "动作前事件索引不一致")

        chosen_id = str(decision["chosen_action_id"])
        chosen = next((action for action in legal if action.action_id == chosen_id), None)
        if chosen is None:
            raise ReplayDivergenceError(
                "decision",
                index,
                "记录动作不在重新枚举的合法动作集合中",
                expected=chosen_id,
                actual=[action.action_id for action in legal],
            )
        _expect_equal("decision", index, decision["chosen_action"], _action_value(chosen), "选择动作内容不一致")
        executed = game.step(_ActionIdController(chosen_id))
        _expect_equal("decision", index, chosen_id, executed.action_id, "真实step提交了不同动作")

        rng_end = int(decision["rng_end"])
        event_end = int(decision["event_end"])
        _compare_sequence(
            "rng",
            int(decision["rng_start"]),
            list(record.random_consumptions[int(decision["rng_start"]):rng_end]),
            _rng_values(game)[int(decision["rng_start"]):],
        )
        _compare_sequence(
            "event",
            int(decision["event_start"]),
            list(record.events[int(decision["event_start"]):event_end]),
            _event_values(game)[int(decision["event_start"]):],
        )
        _expect_equal("rng", index, rng_end, len(game.rng_calls), "动作后随机索引不一致")
        _expect_equal("event", index, event_end, len(game.events), "动作后事件索引不一致")
        _expect_equal("state", index, decision["state_after_sha256"], _game_state_hash(game), "动作后GameState不一致")
        _expect_equal("state", index, decision["execution_after_sha256"], _execution_hash(game), "动作后执行状态不一致")

    if not game.is_finished:
        raise ReplayDivergenceError("decision", len(record.decisions), "决策记录结束但对局尚未结束")
    _compare_sequence("rng", 0, list(record.random_consumptions), _rng_values(game))
    _compare_sequence("event", 0, list(record.events), _event_values(game))
    live_event_chain = _build_event_hash_chain(_event_values(game))
    _compare_sequence(
        "event_hash_chain", 0, list(record.event_hash_chain), list(live_event_chain)
    )
    outcome = record.outcome
    _expect_equal("winner", None, outcome["winner_id"], game.winner_id, "胜者不一致")
    _expect_equal("outcome", None, outcome["step_count"], game.step_count, "动作总数不一致")
    _expect_equal("outcome", None, outcome["turn_count"], game._runtime.turn_number, "回合总数不一致")
    _expect_equal("outcome", None, outcome["decision_count"], len(record.decisions), "决策总数不一致")
    _expect_equal("outcome", None, outcome["random_consumption_count"], len(game.rng_calls), "随机消费总数不一致")
    _expect_equal("outcome", None, outcome["event_count"], len(game.events), "事件总数不一致")
    live_event_tip = live_event_chain[-1] if live_event_chain else _EVENT_CHAIN_ANCHOR
    _expect_equal(
        "event_hash_chain",
        None,
        outcome["event_chain_tip"],
        live_event_tip,
        "终局事件链尖端不一致",
    )
    _expect_equal("state", None, outcome["final_execution_hash"], _execution_hash(game), "最终执行哈希不一致")
    _expect_equal("state", None, outcome["final_game_state_hash"], _game_state_hash(game), "最终GameState哈希不一致")
    assert game.winner_id is not None
    return ReplayVerificationResult(
        verified=True,
        winner_id=game.winner_id,
        decision_count=len(record.decisions),
        random_consumption_count=len(game.rng_calls),
        event_count=len(game.events),
        final_execution_hash=_execution_hash(game),
        final_game_state_hash=_game_state_hash(game),
    )


__all__ = [
    "DuelReplayFormatError",
    "DuelReexecutionReplay",
    "REEXECUTION_SCHEMA",
    "ReplayDivergenceError",
    "ReplayVerificationResult",
    "record_reference_duel",
    "reexecute_duel_replay",
]
