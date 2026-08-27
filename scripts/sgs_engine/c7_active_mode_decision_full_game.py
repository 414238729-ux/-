# -*- coding: utf-8 -*-
"""C7 主动模式决策完整整局动态验收 V1。

本模块是独立 acceptance envelope。它不修改 C7 规则语义、不放宽
production replay-v1，也不接触 authoritative no-skill full-game replay-v2。
控制器只能读取当前已签发的合法动作、公开上下文投影与冻结场景配置。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import json
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from .actions import ActionContext, LegalAction
from .formal_duel import deck_identity, implementation_identity
from .mode_identity_heir import (
    FORMAL_NO_SKILL_IDENTITY_8P_HEIR_MODE,
    FormalHeirAndSpyChoiceIdentityConfiguration,
    FormalHeirAndSpyChoiceIdentitySession,
)
from .production_batch import (
    BATCH_PHASES,
    BatchActionIdController,
    ProductionBatchError,
    ProductionPhase,
    _BatchRuleAdapter,
)
from .production_cards import _default_adapters
from .production_replay import (
    REEXECUTION_SCHEMA,
    ProductionReexecutionReplay,
    ProductionReplayDivergenceError,
    ProductionReplayFormatError,
    record_reference_production_batch,
    reexecute_production_replay,
)
from .replay import canonical_json, sha256_value


NEXT_STAGE_C7_ACTIVE_MODE_DECISION_FULL_GAME_ACCEPTANCE_V1 = (
    "NEXT_STAGE_C7_ACTIVE_MODE_DECISION_FULL_GAME_ACCEPTANCE_V1"
)
C7_ACTIVE_MODE_DECISION_ACCEPTANCE_CONTROLLER_V1_ID = (
    "c7-active-mode-decision-acceptance-controller-v1"
)
C7_ACTIVE_MODE_DECISION_ACCEPTANCE_CONTROLLER_V1_VERSION = "1"
C7_ACTIVE_MODE_DECISION_SCENARIO_SCHEMA_V1 = (
    "sgs-c7-active-mode-decision-scenario-v1"
)
C7_ACTIVE_MODE_DECISION_FULL_GAME_REPLAY_SCHEMA_V1 = (
    "sgs-c7-active-mode-decision-full-game-replay-v1"
)
C7_ACTIVE_MODE_DECISION_FULL_GAME_MATRIX_SCHEMA_V1 = (
    "sgs-c7-active-mode-decision-full-game-matrix-v1"
)
C7_ACTIVE_MODE_DECISION_PROOF_SCHEMA_V1 = (
    "sgs-c7-active-mode-decision-proof-v1"
)

HEIR_SUCCESSION = "HEIR_SUCCESSION"
SPY_TO_LOYALIST = "SPY_TO_LOYALIST"
SPY_TO_AMBITIONIST = "SPY_TO_AMBITIONIST"
C7_ACTIVE_MODE_DECISION_REQUIRED_SCENARIOS_V1: tuple[str, ...] = (
    HEIR_SUCCESSION,
    SPY_TO_LOYALIST,
    SPY_TO_AMBITIONIST,
)
C7_ACTIVE_MODE_DECISION_FROZEN_SEEDS_V1 = MappingProxyType(
    {
        HEIR_SUCCESSION: 1,
        SPY_TO_LOYALIST: 1,
        SPY_TO_AMBITIONIST: 2,
    }
)


class C7ActiveModeDecisionFullGameError(ValueError):
    """C7 主动决策验收合同、场景或 artifact 违反冻结边界。"""


class C7ActiveModeDecisionReplayIdentityError(ProductionReplayDivergenceError):
    """在 production replay 会话重建前发现身份漂移。"""

    def __init__(self, label: str, expected: str, actual: str) -> None:
        super().__init__(
            "identity",
            None,
            f"C7主动决策回放{label}不匹配；拒绝在身份漂移下重建会话",
            expected=expected,
            actual=actual,
        )
        self.label = label


def _plain(value: object) -> Any:
    return json.loads(canonical_json(value))


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


def _require_mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise C7ActiveModeDecisionFullGameError(f"{label}必须是JSON对象")
    return value


def _require_sequence(value: object, label: str) -> Sequence[object]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise C7ActiveModeDecisionFullGameError(f"{label}必须是JSON数组")
    return value


def _require_exact_fields(
    value: Mapping[str, object], required: frozenset[str], label: str
) -> None:
    missing = sorted(required.difference(value))
    extra = sorted(set(value).difference(required))
    if missing:
        raise C7ActiveModeDecisionFullGameError(
            f"{label}缺少字段：{', '.join(missing)}"
        )
    if extra:
        raise C7ActiveModeDecisionFullGameError(
            f"{label}包含未知字段：{', '.join(extra)}"
        )


def _require_sha256(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise C7ActiveModeDecisionFullGameError(f"{label}必须是小写64位SHA-256")
    return value


def _require_seed(value: object, label: str = "seed") -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise C7ActiveModeDecisionFullGameError(f"{label}必须是非负整数")
    return value


@dataclass(frozen=True, slots=True)
class C7ActiveModeDecisionScenarioV1:
    """冻结场景配置；它是控制器除公开动作输入外的唯一配置输入。"""

    scenario_id: str
    seed: int
    target_operation: str
    target_id: str | None
    target_path: str | None
    expected_winner_id: str
    expected_finish_reason: str = "identity_victory"
    mode_id: str = FORMAL_NO_SKILL_IDENTITY_8P_HEIR_MODE
    schema: str = C7_ACTIVE_MODE_DECISION_SCENARIO_SCHEMA_V1

    def __post_init__(self) -> None:
        if self.schema != C7_ACTIVE_MODE_DECISION_SCENARIO_SCHEMA_V1:
            raise C7ActiveModeDecisionFullGameError("不支持的C7主动决策场景schema")
        if self.scenario_id not in C7_ACTIVE_MODE_DECISION_REQUIRED_SCENARIOS_V1:
            raise C7ActiveModeDecisionFullGameError("未知的C7主动决策scenario_id")
        if self.mode_id != FORMAL_NO_SKILL_IDENTITY_8P_HEIR_MODE:
            raise C7ActiveModeDecisionFullGameError("C7主动决策场景mode_id漂移")
        _require_seed(self.seed)
        for label, value in (
            ("target_operation", self.target_operation),
            ("expected_winner_id", self.expected_winner_id),
            ("expected_finish_reason", self.expected_finish_reason),
        ):
            if not isinstance(value, str) or not value:
                raise C7ActiveModeDecisionFullGameError(f"{label}必须是非空字符串")
        if self.target_id is not None and (
            not isinstance(self.target_id, str) or not self.target_id
        ):
            raise C7ActiveModeDecisionFullGameError("target_id必须是非空字符串或None")
        if self.scenario_id == HEIR_SUCCESSION:
            if (
                self.target_operation != "select_heir"
                or self.target_id != "p3"
                or self.target_path is not None
            ):
                raise C7ActiveModeDecisionFullGameError("HEIR_SUCCESSION目标配置漂移")
        else:
            expected_path = (
                "loyalist"
                if self.scenario_id == SPY_TO_LOYALIST
                else "ambitionist"
            )
            if (
                self.target_operation != "choose_spy_path"
                or self.target_id is not None
                or self.target_path != expected_path
            ):
                raise C7ActiveModeDecisionFullGameError("SPY场景目标配置漂移")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "scenario_id": self.scenario_id,
            "mode_id": self.mode_id,
            "seed": self.seed,
            "target_operation": self.target_operation,
            "target_id": self.target_id,
            "target_path": self.target_path,
            "expected_winner_id": self.expected_winner_id,
            "expected_finish_reason": self.expected_finish_reason,
        }

    @property
    def configuration_sha256(self) -> str:
        return sha256_value(self.to_dict())


_SCENARIOS: tuple[C7ActiveModeDecisionScenarioV1, ...] = (
    C7ActiveModeDecisionScenarioV1(
        scenario_id=HEIR_SUCCESSION,
        seed=1,
        target_operation="select_heir",
        target_id="p3",
        target_path=None,
        expected_winner_id="lord_and_loyalists",
    ),
    C7ActiveModeDecisionScenarioV1(
        scenario_id=SPY_TO_LOYALIST,
        seed=1,
        target_operation="choose_spy_path",
        target_id=None,
        target_path="loyalist",
        expected_winner_id="lord_and_loyalists",
    ),
    C7ActiveModeDecisionScenarioV1(
        scenario_id=SPY_TO_AMBITIONIST,
        seed=2,
        target_operation="choose_spy_path",
        target_id=None,
        target_path="ambitionist",
        expected_winner_id="ambitionist",
    ),
)
C7_ACTIVE_MODE_DECISION_SCENARIO_CONFIGS_V1 = MappingProxyType(
    {scenario.scenario_id: scenario for scenario in _SCENARIOS}
)


def c7_active_mode_decision_scenario_v1(
    scenario_id: str,
) -> C7ActiveModeDecisionScenarioV1:
    try:
        return C7_ACTIVE_MODE_DECISION_SCENARIO_CONFIGS_V1[scenario_id]
    except (KeyError, TypeError) as exc:
        raise C7ActiveModeDecisionFullGameError(
            f"未知的C7主动决策scenario_id={scenario_id!r}"
        ) from exc


def _scenario_from_value(value: object) -> C7ActiveModeDecisionScenarioV1:
    mapping = _require_mapping(value, "scenario_configuration")
    scenario_id = mapping.get("scenario_id")
    if not isinstance(scenario_id, str):
        raise C7ActiveModeDecisionFullGameError(
            "scenario_configuration.scenario_id必须是字符串"
        )
    scenario = c7_active_mode_decision_scenario_v1(scenario_id)
    if _plain(mapping) != scenario.to_dict():
        raise C7ActiveModeDecisionFullGameError("冻结scenario_configuration漂移")
    return scenario


@dataclass(frozen=True, slots=True)
class C7PublicActionContextV1:
    """控制器可读取的公开上下文；刻意排除 ActionContext.metadata。"""

    mode_id: str
    phase: str
    actor_id: str
    turn_player_id: str | None
    response_window_id: str | None
    expected_revision: int | None

    @classmethod
    def from_action_context(cls, context: ActionContext) -> "C7PublicActionContextV1":
        if not isinstance(context, ActionContext):
            raise TypeError("C7主动决策控制器必须接收ActionContext")
        return cls(
            mode_id=context.mode,
            phase=context.phase,
            actor_id=context.actor_id,
            turn_player_id=context.turn_player_id,
            response_window_id=context.response_window_id,
            expected_revision=context.expected_revision,
        )


def _operation(action: LegalAction) -> str:
    return str(action.payload.get("operation", ""))


def _target(action: LegalAction) -> str | None:
    if action.target_ids:
        return action.target_ids[0]
    target_id = action.payload.get("target_id")
    return target_id if type(target_id) is str else None


def _first(
    actions: Sequence[LegalAction], predicate: Callable[[LegalAction], bool]
) -> LegalAction | None:
    return next((action for action in actions if predicate(action)), None)


class C7ActiveModeDecisionAcceptanceControllerV1:
    """冻结 public-only steering；只返回当前已签发 action_id。"""

    controller_id = C7_ACTIVE_MODE_DECISION_ACCEPTANCE_CONTROLLER_V1_ID
    controller_version = C7_ACTIVE_MODE_DECISION_ACCEPTANCE_CONTROLLER_V1_VERSION
    strategy_version = (
        f"{C7_ACTIVE_MODE_DECISION_ACCEPTANCE_CONTROLLER_V1_ID}."
        f"{C7_ACTIVE_MODE_DECISION_ACCEPTANCE_CONTROLLER_V1_VERSION}"
    )

    def __init__(self, scenario: C7ActiveModeDecisionScenarioV1) -> None:
        if type(scenario) is not C7ActiveModeDecisionScenarioV1:
            raise TypeError("C7主动决策控制器必须接收冻结scenario配置")
        canonical = c7_active_mode_decision_scenario_v1(scenario.scenario_id)
        if scenario != canonical:
            raise C7ActiveModeDecisionFullGameError("控制器拒绝非冻结scenario配置")
        self._scenario = scenario
        self._target_selection_count = 0
        self._selected_actor_id: str | None = None
        self._selected_target_id: str | None = None
        self._public_lord_actor_id: str | None = None
        self._succession_seen = False

    @property
    def target_selection_count(self) -> int:
        return self._target_selection_count

    @property
    def selected_actor_id(self) -> str | None:
        """实际 chooser；仅从此前公开签发的目标动作学习。"""

        return self._selected_actor_id

    @property
    def selected_target_id(self) -> str | None:
        """实际 target；仅从此前公开签发的目标动作学习。"""

        return self._selected_target_id

    @property
    def public_lord_actor_id(self) -> str | None:
        """开局主公；仅从公开 select_heir 合法动作窗口学习。"""

        return self._public_lord_actor_id

    def _matches_target(self, action: LegalAction) -> bool:
        scenario = self._scenario
        return (
            _operation(action) == scenario.target_operation
            and _target(action) == scenario.target_id
            and action.payload.get("path") == scenario.target_path
        )

    def _learn_public_window(
        self,
        actions: Sequence[LegalAction],
        context: C7PublicActionContextV1,
    ) -> None:
        if context.phase != ProductionPhase.MODE_DECISION.value:
            return
        heir_actions = [action for action in actions if _operation(action) == "select_heir"]
        if not heir_actions:
            return
        actors = {action.actor_id for action in heir_actions}
        if actors != {context.actor_id}:
            raise C7ActiveModeDecisionFullGameError("公开立储窗口actor绑定不一致")
        if self._public_lord_actor_id not in (None, context.actor_id):
            raise C7ActiveModeDecisionFullGameError("公开主公actor在合法动作轨迹中漂移")
        self._public_lord_actor_id = context.actor_id

    def _protected_public_ids(self) -> frozenset[str]:
        protected: set[str] = set()
        if self._scenario.scenario_id == HEIR_SUCCESSION:
            if self._selected_target_id is not None:
                protected.add(self._selected_target_id)
        elif self._scenario.scenario_id == SPY_TO_LOYALIST:
            if self._selected_actor_id is not None:
                protected.add(self._selected_actor_id)
            if self._public_lord_actor_id is not None:
                protected.add(self._public_lord_actor_id)
        elif self._selected_actor_id is not None:
            protected.add(self._selected_actor_id)
        return frozenset(protected)

    def choose_action_id(
        self,
        legal_actions: Sequence[LegalAction],
        public_context: C7PublicActionContextV1,
    ) -> str:
        if type(public_context) is not C7PublicActionContextV1:
            raise TypeError("C7主动决策控制器只能读取C7PublicActionContextV1")
        if public_context.mode_id != self._scenario.mode_id:
            raise C7ActiveModeDecisionFullGameError("控制器mode_id与冻结场景不一致")
        if not legal_actions:
            raise ProductionBatchError("C7主动决策控制器收到空合法动作集合")
        issued = [action.action_id for action in legal_actions]
        if any(not isinstance(action_id, str) or not action_id for action_id in issued):
            raise ProductionBatchError("C7主动决策控制器只接受已签发action_id")
        if len(set(issued)) != len(issued):
            raise ProductionBatchError("当前合法动作集合包含重复action_id")

        self._learn_public_window(legal_actions, public_context)
        candidates = [action for action in legal_actions if self._matches_target(action)]
        if len(candidates) > 1:
            raise C7ActiveModeDecisionFullGameError("目标窗口出现重复目标动作")
        in_target_window = (
            public_context.phase == ProductionPhase.MODE_DECISION.value
            and any(
                _operation(action) == self._scenario.target_operation
                for action in legal_actions
            )
            and self._target_selection_count == 0
        )
        if candidates:
            if self._target_selection_count != 0:
                raise C7ActiveModeDecisionFullGameError("目标动作在选择后再次出现")
            if not in_target_window:
                raise C7ActiveModeDecisionFullGameError("目标动作出现在错误窗口")
            selected = candidates[0]
        elif in_target_window:
            raise C7ActiveModeDecisionFullGameError(
                "目标窗口缺少唯一目标动作；禁止pass或近似替代"
            )
        else:
            selected = self._public_steering(legal_actions, public_context)

        if selected not in legal_actions or selected.action_id not in issued:
            raise ProductionBatchError("控制器返回了未签发或stale action_id")
        operation = _operation(selected)
        if self._matches_target(selected):
            self._target_selection_count += 1
            self._selected_actor_id = selected.actor_id
            self._selected_target_id = _target(selected)
        if operation in {"succession_obtain_none", "succession_obtain_card"}:
            self._succession_seen = True
        return selected.action_id

    def choose(
        self, legal_actions: Sequence[LegalAction], context: ActionContext
    ) -> LegalAction:
        public = C7PublicActionContextV1.from_action_context(context)
        action_id = self.choose_action_id(legal_actions, public)
        for action in legal_actions:
            if action.action_id == action_id:
                return action
        raise ProductionBatchError("控制器返回的ID不在当前合法动作集合中")

    def _public_steering(
        self,
        actions: Sequence[LegalAction],
        context: C7PublicActionContextV1,
    ) -> LegalAction:
        phase = context.phase
        actor = context.actor_id
        if phase == ProductionPhase.SUCCESSION_CARD_CHOICE.value:
            self._succession_seen = True
            chosen = _first(actions, lambda action: _operation(action) == "succession_obtain_none")
            if chosen is not None:
                return chosen
        if phase == ProductionPhase.MODE_DECISION.value:
            chosen = _first(actions, lambda action: _operation(action) == "pass_mode_decision")
            if chosen is not None:
                return chosen
        if phase == ProductionPhase.DYING_RESCUE.value:
            dying_id = next(
                (action.target_ids[0] for action in actions if action.target_ids),
                None,
            )
            if dying_id in self._protected_public_ids():
                chosen = _first(
                    actions,
                    lambda action: _operation(action)
                    in {"rescue_with_peach", "rescue_with_wine"},
                )
                if chosen is not None:
                    return chosen
            chosen = _first(actions, lambda action: _operation(action) == "pass_rescue")
            if chosen is not None:
                return chosen
        response_pass = {
            ProductionPhase.SLASH_RESPONSE.value: "pass_slash_response",
            ProductionPhase.TRICK_RESPONSE.value: "pass_trick_response",
            ProductionPhase.DUEL_RESPONSE.value: "pass_duel_slash",
            ProductionPhase.NANMAN_RESPONSE.value: "pass_nanman_slash",
            ProductionPhase.WANJIAN_RESPONSE.value: "pass_wanjian_jink",
            ProductionPhase.JUDGMENT_WUXIE.value: "pass_judgment_wuxie",
            ProductionPhase.FEIYANG_ACTIVATE.value: "feiyang_decline",
            ProductionPhase.CIXIONG_ACTIVATE.value: "pass_cixiong",
        }
        if phase in response_pass:
            protected_response = {
                ProductionPhase.DUEL_RESPONSE.value: "play_slash_for_duel",
                ProductionPhase.NANMAN_RESPONSE.value: "play_slash_for_nanman",
                ProductionPhase.WANJIAN_RESPONSE.value: "play_jink_for_wanjian",
            }.get(phase)
            if actor in self._protected_public_ids() and protected_response:
                chosen = _first(
                    actions, lambda action: _operation(action) == protected_response
                )
                if chosen is not None:
                    return chosen
            chosen = _first(
                actions, lambda action: _operation(action) == response_pass[phase]
            )
            if chosen is not None:
                return chosen
        if phase == ProductionPhase.IDENTITY_REWARD_CHOICE.value:
            chosen = _first(
                actions,
                lambda action: _operation(action) == "ambitionist_reward_decline",
            )
            if chosen is not None:
                return chosen
        if phase in {
            ProductionPhase.PREPARE.value,
            ProductionPhase.JUDGMENT.value,
            ProductionPhase.DRAW.value,
            ProductionPhase.END.value,
        }:
            return actions[0]
        if phase == ProductionPhase.PLAY.value:
            if actor in self._protected_public_ids():
                chosen = _first(
                    actions,
                    lambda action: _operation(action) == "ambitionist_mark_draw_two",
                )
                if chosen is not None:
                    return chosen
                chosen = _first(
                    actions,
                    lambda action: _operation(action) == "heal_self"
                    and action.payload.get("virtual") is True,
                )
                if chosen is not None:
                    return chosen
                chosen = _first(actions, lambda action: _operation(action) == "heal_self")
                if chosen is not None:
                    return chosen
            return self._choose_play(actions)
        if phase in {
            ProductionPhase.WEAPON_SLASH_CHOICE.value,
            ProductionPhase.WEAPON_AFTER_DAMAGE.value,
            ProductionPhase.BORROWED_SWORD_CHOICE.value,
        }:
            for hunt in self._hunt_targets(actions, actor):
                chosen = _first(
                    actions,
                    lambda action, hunt=hunt: _target(action) == hunt
                    and _operation(action)
                    in {
                        "qinglong_use_slash",
                        "weapon_force_hit",
                        "choose_borrowed_sword_slash",
                    },
                )
                if chosen is not None:
                    return chosen
            chosen = _first(
                actions,
                lambda action: _operation(action)
                in {"pass_weapon_choice", "refuse_borrowed_sword_slash"},
            )
            if chosen is not None:
                return chosen
        if phase == ProductionPhase.DISCARD.value:
            chosen = _first(
                actions, lambda action: _operation(action) == "discard_phase_submit"
            )
            if chosen is not None:
                return chosen
            chosen = _first(
                actions, lambda action: _operation(action) == "select_discard_card"
            )
            if chosen is not None:
                return chosen
        if phase == ProductionPhase.FIRE_ATTACK_DISCARD.value:
            if actor in self._protected_public_ids():
                chosen = _first(
                    actions,
                    lambda action: _operation(action)
                    == "discard_same_suit_for_fire_attack",
                )
                if chosen is not None:
                    return chosen
            chosen = _first(
                actions,
                lambda action: _operation(action) == "pass_fire_attack_discard",
            )
            if chosen is not None:
                return chosen
        return actions[0]

    def _hunt_targets(
        self, actions: Sequence[LegalAction], actor_id: str
    ) -> tuple[str, ...]:
        """仅由当前公开合法动作生成 deterministic target 顺序。"""

        protected = self._protected_public_ids()
        available = {
            target
            for action in actions
            for target in ((_target(action),) if _target(action) is not None else ())
            if target != actor_id and target not in protected
        }
        ordered: list[str] = []
        if (
            self._scenario.scenario_id == HEIR_SUCCESSION
            and not self._succession_seen
            and self._public_lord_actor_id in available
        ):
            assert self._public_lord_actor_id is not None
            ordered.append(self._public_lord_actor_id)
        ordered.extend(sorted(available.difference(ordered)))
        return tuple(ordered)

    def _choose_play(self, actions: Sequence[LegalAction]) -> LegalAction:
        actor_id = actions[0].actor_id
        for hunt in self._hunt_targets(actions, actor_id):
            slash = _first(
                actions,
                lambda action, hunt=hunt: _operation(action) == "use_slash"
                and _target(action) == hunt
                and action.payload.get("zhangba_virtual") is not True
                and not str(action.card_instance_id or "").startswith("virtual:zhangba"),
            )
            if slash is not None:
                wine = _first(
                    actions, lambda action: _operation(action) == "use_wine_buff"
                )
                return wine or slash
            for operation in ("use_duel", "use_fire_attack"):
                chosen = _first(
                    actions,
                    lambda action, hunt=hunt, operation=operation: _operation(action)
                    == operation
                    and _target(action) == hunt,
                )
                if chosen is not None:
                    return chosen
        for operation in ("use_weapon", "use_wuzhong", "end_play_phase"):
            chosen = _first(
                actions,
                lambda action, operation=operation: _operation(action) == operation,
            )
            if chosen is not None:
                return chosen
        return actions[0]


_REPLAY_FIELDS = frozenset(
    {
        "schema",
        "header",
        "production_replay_v1",
        "required_active_decision_proof",
        "replay_sha256",
    }
)
_HEADER_FIELDS = frozenset(
    {
        "contract_id",
        "scenario_id",
        "seed",
        "mode_id",
        "controller_id",
        "controller_version",
        "scenario_configuration_schema",
        "scenario_configuration",
        "scenario_configuration_sha256",
        "implementation_identity",
        "ruleset_identity",
        "mode_profile_identity",
        "deck_identity",
        "production_replay_v1_sha256",
    }
)


def _stable_adapter_type(adapter: object) -> str:
    adapter_type = type(adapter)
    return f"{adapter_type.__module__}.{adapter_type.__qualname__}"


def _static_c7_ruleset_value() -> dict[str, str]:
    """从正式注册 profile 静态派生 ruleset；严禁为 preflight 构造 session。"""

    batch_adapter = _BatchRuleAdapter(None)  # type: ignore[arg-type]
    registrations = [
        {
            "mode": FORMAL_NO_SKILL_IDENTITY_8P_HEIR_MODE,
            "phase": phase.value,
            "adapter_type": _stable_adapter_type(batch_adapter),
            "adapter_version": batch_adapter.adapter_version,
        }
        for phase in BATCH_PHASES
    ]
    registrations.extend(
        {
            "mode": FORMAL_NO_SKILL_IDENTITY_8P_HEIR_MODE,
            "phase": f"card:{card_key}",
            "adapter_type": _stable_adapter_type(adapter),
            "adapter_version": adapter.adapter_version,
        }
        for card_key, adapter in _default_adapters().items()
    )
    registrations.sort(key=lambda item: (str(item["mode"]), str(item["phase"])))
    value = {
        "mode_id": FORMAL_NO_SKILL_IDENTITY_8P_HEIR_MODE,
        "adapter_type": _stable_adapter_type(batch_adapter),
        "ruleset_version": batch_adapter.adapter_version,
        "registry_fingerprint": sha256_value(registrations),
    }
    value["ruleset_hash"] = sha256_value(value)
    return value


def _current_identity_values() -> dict[str, str]:
    configuration = FormalHeirAndSpyChoiceIdentityConfiguration.formal_profile()
    live_ruleset = _static_c7_ruleset_value()
    return {
        "implementation_identity": implementation_identity(),
        "ruleset_identity": sha256_value(
            {
                "ruleset_version": live_ruleset["ruleset_version"],
                "ruleset_hash": live_ruleset["ruleset_hash"],
                "registry_fingerprint": live_ruleset["registry_fingerprint"],
            }
        ),
        "mode_profile_identity": sha256_value(configuration.to_dict()),
        "deck_identity": deck_identity(),
    }


def _ruleset_identity_from_record_header(header: Mapping[str, object]) -> str:
    return sha256_value(
        {
            "ruleset_version": header.get("ruleset_version"),
            "ruleset_hash": header.get("ruleset_hash"),
            "registry_fingerprint": header.get("registry_fingerprint"),
        }
    )


def _replay_material(
    header: Mapping[str, object],
    production_replay_v1: Mapping[str, object],
    proof: Mapping[str, object],
) -> dict[str, object]:
    return {
        "schema": C7_ACTIVE_MODE_DECISION_FULL_GAME_REPLAY_SCHEMA_V1,
        "header": _plain(header),
        "production_replay_v1": _plain(production_replay_v1),
        "required_active_decision_proof": _plain(proof),
    }


@dataclass(frozen=True, slots=True)
class C7ActiveModeDecisionFullGameReplayV1:
    header: Mapping[str, object]
    production_replay_v1: ProductionReexecutionReplay
    required_active_decision_proof: Mapping[str, object]
    replay_sha256: str = ""

    def __post_init__(self) -> None:
        header = _plain(_require_mapping(self.header, "header"))
        proof = _plain(
            _require_mapping(
                self.required_active_decision_proof,
                "required_active_decision_proof",
            )
        )
        _require_exact_fields(header, _HEADER_FIELDS, "header")
        if not isinstance(self.production_replay_v1, ProductionReexecutionReplay):
            raise TypeError("production_replay_v1必须是ProductionReexecutionReplay")
        scenario = _scenario_from_value(header["scenario_configuration"])
        if header["contract_id"] != NEXT_STAGE_C7_ACTIVE_MODE_DECISION_FULL_GAME_ACCEPTANCE_V1:
            raise C7ActiveModeDecisionFullGameError("C7主动决策contract_id漂移")
        if header["scenario_id"] != scenario.scenario_id:
            raise C7ActiveModeDecisionFullGameError("header scenario_id与配置不一致")
        if header["seed"] != scenario.seed or header["mode_id"] != scenario.mode_id:
            raise C7ActiveModeDecisionFullGameError("header seed/mode与冻结配置不一致")
        if header["controller_id"] != C7_ACTIVE_MODE_DECISION_ACCEPTANCE_CONTROLLER_V1_ID:
            raise C7ActiveModeDecisionFullGameError("controller id漂移")
        if header["controller_version"] != C7_ACTIVE_MODE_DECISION_ACCEPTANCE_CONTROLLER_V1_VERSION:
            raise C7ActiveModeDecisionFullGameError("controller version漂移")
        if header["scenario_configuration_schema"] != C7_ACTIVE_MODE_DECISION_SCENARIO_SCHEMA_V1:
            raise C7ActiveModeDecisionFullGameError("scenario configuration schema漂移")
        if header["scenario_configuration_sha256"] != scenario.configuration_sha256:
            raise C7ActiveModeDecisionFullGameError("scenario configuration hash漂移")
        for label in (
            "implementation_identity",
            "ruleset_identity",
            "mode_profile_identity",
            "deck_identity",
            "production_replay_v1_sha256",
        ):
            _require_sha256(header[label], f"header.{label}")
        if header["production_replay_v1_sha256"] != self.production_replay_v1.record_sha256:
            raise C7ActiveModeDecisionFullGameError("production replay-v1 hash不匹配")
        object.__setattr__(self, "header", _freeze(header))
        object.__setattr__(self, "required_active_decision_proof", _freeze(proof))
        calculated = sha256_value(
            _replay_material(header, self.production_replay_v1.to_dict(), proof)
        )
        supplied = self.replay_sha256
        if supplied:
            _require_sha256(supplied, "replay_sha256")
            if supplied != calculated:
                raise C7ActiveModeDecisionFullGameError("C7主动决策replay_sha256不匹配")
        object.__setattr__(self, "replay_sha256", calculated)

    @property
    def scenario_id(self) -> str:
        return str(self.header["scenario_id"])

    @property
    def seed(self) -> int:
        return int(self.header["seed"])

    def verify_integrity(self) -> bool:
        calculated = sha256_value(
            _replay_material(
                self.header,
                self.production_replay_v1.to_dict(),
                self.required_active_decision_proof,
            )
        )
        if calculated != self.replay_sha256:
            raise C7ActiveModeDecisionFullGameError("C7主动决策replay_sha256不匹配")
        return True

    def to_dict(self) -> dict[str, object]:
        material = _replay_material(
            self.header,
            self.production_replay_v1.to_dict(),
            self.required_active_decision_proof,
        )
        material["replay_sha256"] = self.replay_sha256
        return material

    @classmethod
    def from_dict(
        cls, value: Mapping[str, object]
    ) -> "C7ActiveModeDecisionFullGameReplayV1":
        raw = _require_mapping(value, "C7主动决策replay")
        _require_exact_fields(raw, _REPLAY_FIELDS, "C7主动决策replay")
        if raw["schema"] != C7_ACTIVE_MODE_DECISION_FULL_GAME_REPLAY_SCHEMA_V1:
            raise C7ActiveModeDecisionFullGameError("不支持的C7主动决策replay schema")
        header = _plain(_require_mapping(raw["header"], "header"))
        _require_exact_fields(header, _HEADER_FIELDS, "header")
        scenario = _scenario_from_value(header["scenario_configuration"])
        _preflight_header_identity(header, scenario)
        raw_production = _require_mapping(
            raw["production_replay_v1"], "production_replay_v1"
        )
        raw_record_hash = _require_sha256(
            raw_production.get("record_sha256"),
            "production_replay_v1.record_sha256",
        )
        if raw_record_hash != header["production_replay_v1_sha256"]:
            raise C7ActiveModeDecisionFullGameError("production replay-v1 hash header不匹配")
        proof = _require_mapping(
            raw["required_active_decision_proof"],
            "required_active_decision_proof",
        )
        expected_outer = sha256_value(_replay_material(header, raw_production, proof))
        supplied_outer = _require_sha256(raw["replay_sha256"], "replay_sha256")
        if expected_outer != supplied_outer:
            raise C7ActiveModeDecisionFullGameError("C7主动决策replay_sha256不匹配")
        production = ProductionReexecutionReplay.from_dict(raw_production)
        replay = cls(
            header=header,
            production_replay_v1=production,
            required_active_decision_proof=proof,
            replay_sha256=supplied_outer,
        )
        reexecute_c7_active_mode_decision_full_game_replay_v1(replay)
        return replay


def _preflight_header_identity(
    header: Mapping[str, object], scenario: C7ActiveModeDecisionScenarioV1
) -> None:
    if header.get("contract_id") != NEXT_STAGE_C7_ACTIVE_MODE_DECISION_FULL_GAME_ACCEPTANCE_V1:
        raise C7ActiveModeDecisionFullGameError("C7主动决策contract_id漂移")
    if header.get("scenario_id") != scenario.scenario_id:
        raise C7ActiveModeDecisionFullGameError("header scenario_id与配置不一致")
    if header.get("seed") != scenario.seed or header.get("mode_id") != scenario.mode_id:
        raise C7ActiveModeDecisionFullGameError("header seed/mode与冻结配置不一致")
    if header.get("controller_id") != C7_ACTIVE_MODE_DECISION_ACCEPTANCE_CONTROLLER_V1_ID:
        raise C7ActiveModeDecisionFullGameError("controller id漂移")
    if header.get("controller_version") != C7_ACTIVE_MODE_DECISION_ACCEPTANCE_CONTROLLER_V1_VERSION:
        raise C7ActiveModeDecisionFullGameError("controller version漂移")
    if header.get("scenario_configuration_schema") != C7_ACTIVE_MODE_DECISION_SCENARIO_SCHEMA_V1:
        raise C7ActiveModeDecisionFullGameError("scenario configuration schema漂移")
    if header.get("scenario_configuration_sha256") != scenario.configuration_sha256:
        raise C7ActiveModeDecisionFullGameError("scenario configuration hash漂移")
    current = _current_identity_values()
    for label, actual in current.items():
        expected = _require_sha256(header.get(label), f"header.{label}")
        if expected != actual:
            raise C7ActiveModeDecisionReplayIdentityError(label, expected, actual)


def _event_payload(event: object) -> Mapping[str, object]:
    payload = getattr(event, "payload", {})
    return payload if isinstance(payload, Mapping) else {}


def _event_type(event: object) -> str:
    event_type = getattr(event, "event_type", None)
    value = getattr(event_type, "value", event_type)
    return str(value or "")


def _event_targets(event: object) -> tuple[str, ...]:
    targets = getattr(event, "target_ids", ())
    return tuple(str(item) for item in targets)


def _chosen_payload(decision: Mapping[str, object]) -> Mapping[str, object]:
    chosen = _require_mapping(decision.get("chosen_action"), "decision.chosen_action")
    return _require_mapping(chosen.get("payload"), "decision.chosen_action.payload")


def _event_binding(
    event: object,
    *,
    event_index: int,
    decision_index: int,
    event_start: int,
    event_end: int,
) -> dict[str, object]:
    return {
        "match_count": 1,
        "event_index": event_index,
        "decision_index": decision_index,
        "event_start": event_start,
        "event_end": event_end,
        "event_type": _event_type(event),
        "reason": str(_event_payload(event).get("reason") or ""),
        "payload": _plain(_event_payload(event)),
        "card_user": getattr(event, "card_user", None),
        "target_ids": list(_event_targets(event)),
    }


def _single_event_binding(
    events: Sequence[object],
    *,
    event_start: int,
    event_end: int,
    decision_index: int,
    reason: str,
) -> dict[str, object]:
    matches = [
        (event_start + offset, event)
        for offset, event in enumerate(events)
        if _event_payload(event).get("reason") == reason
    ]
    if len(matches) != 1:
        return {
            "match_count": len(matches),
            "decision_index": decision_index,
            "event_start": event_start,
            "event_end": event_end,
            "reason": reason,
        }
    event_index, event = matches[0]
    binding = _event_binding(
        event,
        event_index=event_index,
        decision_index=decision_index,
        event_start=event_start,
        event_end=event_end,
    )
    binding["match_count"] = 1
    return binding


def _event_binding_matches(
    binding: object,
    *,
    event_type: str,
    reason: str,
    decision_index: int,
    event_start: int,
    event_end: int,
    raw_target_ids: tuple[str, ...],
    card_user: str | None = None,
    required_payload: Mapping[str, object] | None = None,
) -> bool:
    if not isinstance(binding, Mapping):
        return False
    payload = binding.get("payload")
    if not isinstance(payload, Mapping):
        return False
    required = required_payload or {}
    return (
        binding.get("match_count") == 1
        and binding.get("event_type") == event_type
        and binding.get("reason") == reason
        and payload.get("reason", "") == reason
        and all(payload.get(key) == value for key, value in required.items())
        and binding.get("decision_index") == decision_index
        and binding.get("event_start") == event_start
        and binding.get("event_end") == event_end
        and tuple(binding.get("target_ids", ())) == raw_target_ids
        and binding.get("card_user") == card_user
        and isinstance(binding.get("event_index"), int)
        and event_start <= int(binding["event_index"]) < event_end
    )


def _context_binding_matches(value: Mapping[str, object]) -> bool:
    revision = value.get("expected_revision")
    return (
        isinstance(revision, int)
        and not isinstance(revision, bool)
        and revision == value.get("state_revision_before")
        and value.get("response_window_id") == value.get("runtime_response_window_id")
        and isinstance(value.get("state_before_sha256"), str)
        and isinstance(value.get("state_after_sha256"), str)
        and isinstance(value.get("event_start"), int)
        and isinstance(value.get("event_end"), int)
        and int(value["event_end"]) >= int(value["event_start"])
    )


def _natural_turn_advance_matches(value: Mapping[str, object]) -> bool:
    order = value.get("numbered_player_order")
    alive_after = value.get("alive_player_ids_after")
    before = value.get("turn_player_before")
    after = value.get("turn_player_after")
    if (
        isinstance(order, (str, bytes))
        or not isinstance(order, Sequence)
        or isinstance(alive_after, (str, bytes))
        or not isinstance(alive_after, Sequence)
        or not isinstance(before, str)
        or not isinstance(after, str)
    ):
        return False
    normalized_order = tuple(str(item) for item in order)
    normalized_alive = frozenset(str(item) for item in alive_after)
    if before not in normalized_order or after not in normalized_alive:
        return False
    start = normalized_order.index(before)
    expected = next(
        (
            normalized_order[(start + offset) % len(normalized_order)]
            for offset in range(1, len(normalized_order) + 1)
            if normalized_order[(start + offset) % len(normalized_order)]
            in normalized_alive
        ),
        None,
    )
    return expected == after


def _terminal_binding_matches(
    terminal: object, *, scenario_id: str, after_decision_index: int
) -> bool:
    if not isinstance(terminal, Mapping):
        return False
    scenario = c7_active_mode_decision_scenario_v1(scenario_id)
    return (
        terminal.get("is_finished") is True
        and terminal.get("winner_id") == scenario.expected_winner_id
        and terminal.get("finish_reason") == scenario.expected_finish_reason
        and isinstance(terminal.get("last_decision_index"), int)
        and int(terminal["last_decision_index"]) >= after_decision_index
        and isinstance(terminal.get("event_count"), int)
        and int(terminal["event_count"]) > 0
    )


def _mark_use_events_match(
    mark: Mapping[str, object], *, actor_id: str, conversion_event_index: int
) -> bool:
    if mark.get("operation") != "ambitionist_mark_draw_two":
        return False
    raw_indices = mark.get("bound_event_indices")
    raw_events = mark.get("mark_use_events")
    if (
        isinstance(raw_indices, (str, bytes))
        or not isinstance(raw_indices, Sequence)
        or not raw_indices
        or isinstance(raw_events, (str, bytes))
        or not isinstance(raw_events, Sequence)
        or len(raw_events) != 2
    ):
        return False
    indices = tuple(raw_indices)
    if (
        any(isinstance(index, bool) or not isinstance(index, int) for index in indices)
        or len(set(indices)) != len(indices)
        or tuple(sorted(indices)) != indices
        or any(index <= conversion_event_index for index in indices)
    ):
        return False
    event_start = mark.get("event_start")
    event_end = mark.get("event_end")
    decision_index = mark.get("decision_index")
    if not all(isinstance(item, int) for item in (event_start, event_end, decision_index)):
        return False
    events = tuple(raw_events)
    if tuple(event.get("event_index") for event in events if isinstance(event, Mapping)) != indices:
        return False
    return all(
        _event_binding_matches(
            event,
            event_type="card_gained",
            reason="ambitionist_mark_draw_two",
            decision_index=int(decision_index),
            event_start=int(event_start),
            event_end=int(event_end),
            raw_target_ids=(actor_id,),
        )
        for event in events
    )


def _causal_binding_proven(scenario_id: str, binding: object) -> bool:
    """只验证 live proof 字段之间的独立因果约束；任何缺项或漂移均拒绝。"""

    if not isinstance(binding, Mapping):
        return False
    active = binding.get("active_decision")
    if not isinstance(active, Mapping) or not _context_binding_matches(active):
        return False
    actor_id = active.get("actor_id")
    active_index = active.get("decision_index")
    if (
        not isinstance(actor_id, str)
        or not actor_id
        or not isinstance(active_index, int)
        or active.get("target_match_count") != 1
    ):
        return False

    if scenario_id == HEIR_SUCCESSION:
        established = binding.get("heir_established_transition")
        transition = binding.get("succession_transition")
        if not isinstance(established, Mapping) or not isinstance(transition, Mapping):
            return False
        transition_index = transition.get("decision_index")
        event_start = transition.get("event_start")
        event_end = transition.get("event_end")
        old_lord_id = transition.get("old_lord_id")
        successor_id = transition.get("successor_id")
        if (
            actor_id != "p6"
            or active.get("operation") != "select_heir"
            or active.get("target_id") != "p3"
            or active.get("response_window_id") is not None
            or active.get("event_start") != active.get("event_end")
            or established.get("decision_index") != active_index
            or established.get("actor_id") != actor_id
            or established.get("target_id") != active.get("target_id")
            or established.get("operation") != active.get("operation")
            or established.get("expected_revision") != active.get("expected_revision")
            or established.get("state_revision_before") != active.get("state_revision_before")
            or established.get("response_window_id") != active.get("response_window_id")
            or established.get("runtime_response_window_id")
            != active.get("runtime_response_window_id")
            or established.get("state_before_sha256") != active.get("state_before_sha256")
            or established.get("state_after_sha256") != active.get("state_after_sha256")
            or established.get("event_start") != active.get("event_start")
            or established.get("event_end") != active.get("event_end")
            or established.get("heir_player_id_after") != active.get("target_id")
            or established.get("heir_selection_used_after") is not True
            or old_lord_id != actor_id
            or successor_id != active.get("target_id")
            or transition.get("action_actor_id") != successor_id
            or transition.get("pending_old_lord_id") != old_lord_id
            or transition.get("pending_successor_id") != successor_id
            or transition.get("pending_dying_id_before") != old_lord_id
            or transition.get("chosen_window_id") != transition.get("window_id")
            or transition.get("pending_succession_window_id")
            != transition.get("window_id")
            or not isinstance(transition.get("window_id"), str)
            or not transition.get("window_id")
            or not _context_binding_matches(transition)
            or not isinstance(transition.get("response_window_id"), str)
            or not transition.get("response_window_id")
            or not isinstance(transition_index, int)
            or transition_index <= active_index
            or not isinstance(event_start, int)
            or not isinstance(event_end, int)
            or event_end <= event_start
            or transition.get("old_lord_alive_before") is not True
            or transition.get("old_lord_dead_after") is not True
            or transition.get("current_lord_id_after") != successor_id
            or transition.get("seat_before") != transition.get("seat_after")
            or transition.get("numbered_order_unchanged") is not True
            or transition.get("max_hp_after")
            != int(transition.get("max_hp_before", -99)) + 1
            or transition.get("hp_after")
            != min(
                int(transition.get("max_hp_after", -99)),
                int(transition.get("hp_before", -99)) + 1,
            )
            or transition.get("is_extra_turn_after") is not False
        ):
            return False
        causal_events = (
            _event_binding_matches(
                transition.get("death_event"),
                event_type="death",
                reason="",
                decision_index=transition_index,
                event_start=event_start,
                event_end=event_end,
                raw_target_ids=(str(old_lord_id),),
            )
            and _event_binding_matches(
                transition.get("succession_event"),
                event_type="identity_revealed",
                reason="succession_lord_reveal",
                decision_index=transition_index,
                event_start=event_start,
                event_end=event_end,
                raw_target_ids=(str(successor_id),),
                required_payload={"identity": "lord"},
            )
            and _event_binding_matches(
                transition.get("recovery_event"),
                event_type="hp_recover",
                reason="succession_recover",
                decision_index=transition_index,
                event_start=event_start,
                event_end=event_end,
                raw_target_ids=(str(successor_id),),
            )
        )
        return causal_events and _terminal_binding_matches(
            binding.get("terminal_transition"),
            scenario_id=scenario_id,
            after_decision_index=transition_index,
        )

    if scenario_id not in {SPY_TO_LOYALIST, SPY_TO_AMBITIONIST}:
        return False
    expected_path = "loyalist" if scenario_id == SPY_TO_LOYALIST else "ambitionist"
    choice = binding.get("choice_transition")
    conversion = binding.get("conversion_transition")
    if not isinstance(choice, Mapping) or not isinstance(conversion, Mapping):
        return False
    conversion_index = conversion.get("decision_index")
    event_start = conversion.get("event_start")
    event_end = conversion.get("event_end")
    if (
        active.get("operation") != "choose_spy_path"
        or active.get("path") != expected_path
        or active.get("target_id") is not None
        or active.get("response_window_id") is not None
        or choice.get("actor_id") != actor_id
        or choice.get("decision_index") != active_index
        or choice.get("path") != expected_path
        or choice.get("expected_revision") != active.get("expected_revision")
        or choice.get("state_revision_before") != active.get("state_revision_before")
        or choice.get("response_window_id") != active.get("response_window_id")
        or choice.get("runtime_response_window_id")
        != active.get("runtime_response_window_id")
        or choice.get("state_before_sha256") != active.get("state_before_sha256")
        or choice.get("state_after_sha256") != active.get("state_after_sha256")
        or choice.get("event_start") != active.get("event_start")
        or choice.get("event_end") != active.get("event_end")
        or choice.get("role_after_choice") != "spy"
        or choice.get("pending_after_choice") is not True
        or choice.get("locked_after_choice") is not True
        or conversion.get("actor_id") != actor_id
        or conversion.get("spy_path_chooser_id_before") != actor_id
        or conversion.get("spy_path_chooser_id_after") != actor_id
        or conversion.get("spy_path_choice_before") != expected_path
        or conversion.get("spy_path_choice_after") != expected_path
        or conversion.get("pending_before") is not True
        or conversion.get("pending_after") is not False
        or conversion.get("locked_before") is not True
        or conversion.get("locked_after") is not True
        or conversion.get("role_before") != "spy"
        or conversion.get("role_after") != expected_path
        or not _context_binding_matches(conversion)
        or not isinstance(conversion_index, int)
        or conversion_index <= active_index
        or not isinstance(event_start, int)
        or not isinstance(event_end, int)
        or event_end <= event_start
        or conversion.get("turn_after", -1) <= choice.get("turn_after_choice", -1)
        or conversion.get("trigger_operation") != "end_turn"
        or conversion.get("trigger_actor_id") != conversion.get("turn_player_before")
        or not _natural_turn_advance_matches(conversion)
        or conversion.get("phase_after") != ProductionPhase.PREPARE.value
        or conversion.get("is_extra_turn_after") is not False
    ):
        return False
    reason = (
        "spy_converted_loyalist_announced"
        if scenario_id == SPY_TO_LOYALIST
        else "ambitionist_conversion"
    )
    raw_targets = () if scenario_id == SPY_TO_LOYALIST else (actor_id,)
    required_payload = (
        {"identity": "loyalist", "subject_revealed": False}
        if scenario_id == SPY_TO_LOYALIST
        else {"identity": "ambitionist"}
    )
    conversion_event = conversion.get("conversion_event")
    if not _event_binding_matches(
        conversion_event,
        event_type="identity_revealed",
        reason=reason,
        decision_index=conversion_index,
        event_start=event_start,
        event_end=event_end,
        raw_target_ids=raw_targets,
        required_payload=required_payload,
    ):
        return False
    if not isinstance(conversion_event, Mapping):
        return False
    if scenario_id == SPY_TO_LOYALIST:
        causal = conversion.get("mark_available_after") is False
        after_index = conversion_index
    else:
        mark = binding.get("mark_use_transition")
        if not isinstance(mark, Mapping):
            return False
        mark_index = mark.get("decision_index")
        causal = (
            conversion.get("mark_available_after") is True
            and conversion.get("mark_owner_id_after") == actor_id
            and mark.get("actor_id") == actor_id
            and isinstance(mark_index, int)
            and mark_index > conversion_index
            and _context_binding_matches(mark)
            and mark.get("mark_available_before") is True
            and mark.get("mark_available_after") is False
            and _mark_use_events_match(
                mark,
                actor_id=actor_id,
                conversion_event_index=int(conversion_event["event_index"]),
            )
        )
        after_index = int(mark_index) if isinstance(mark_index, int) else conversion_index
    return causal and _terminal_binding_matches(
        binding.get("terminal_transition"),
        scenario_id=scenario_id,
        after_decision_index=after_index,
    )


def _rederive_required_proof(
    record: ProductionReexecutionReplay,
    scenario: C7ActiveModeDecisionScenarioV1,
) -> dict[str, object]:
    private = _require_mapping(record.authoritative_private, "authoritative_private")
    configuration_value = _require_mapping(
        record.header["initial_configuration"], "initial_configuration"
    ).get("formal_heir_and_spy_choice_identity_configuration")
    configuration = (
        FormalHeirAndSpyChoiceIdentityConfiguration.from_canonical_profile_value(
            _plain(configuration_value)
        )
    )
    game = FormalHeirAndSpyChoiceIdentitySession(
        seed=scenario.seed,
        configuration=configuration,
        analysis_only=False,
        session_id=str(private["session_id"]),
        session_secret=bytes.fromhex(str(private["session_secret_hex"])),
    )
    controller = C7ActiveModeDecisionAcceptanceControllerV1(scenario)
    initial_order = tuple(game.numbered_player_order)
    initial_seat = dict(game.seat_by_player)
    active_decision: dict[str, object] | None = None
    target_window_passed = False
    heir_established_transition: dict[str, object] | None = None
    succession_transition: dict[str, object] | None = None
    choice_transition: dict[str, object] | None = None
    conversion_transition: dict[str, object] | None = None
    mark_use_transition: dict[str, object] | None = None

    for index, decision in enumerate(record.decisions):
        if game.is_finished:
            raise ProductionReplayDivergenceError(
                "decision", index, "fresh controller重算时终局后仍有决策"
            )
        legal = game.legal_actions()
        context = game._context()
        public = C7PublicActionContextV1.from_action_context(context)
        chosen_id = controller.choose_action_id(legal, public)
        recorded_id = str(decision["chosen_action_id"])
        if chosen_id != recorded_id:
            raise ProductionReplayDivergenceError(
                "controller",
                index,
                "fresh controller沿live legal_actions重算选择不一致",
                expected=recorded_id,
                actual=chosen_id,
            )
        chosen = next(
            (action for action in legal if action.action_id == chosen_id), None
        )
        if chosen is None:
            raise ProductionReplayDivergenceError(
                "controller", index, "fresh controller返回未签发或stale action_id"
            )
        operation = _operation(chosen)
        state_revision_before = game.state.revision
        runtime_response_window_id = game._runtime.response_window_id
        if (
            context.phase == ProductionPhase.MODE_DECISION.value
            and any(
                _operation(action) == scenario.target_operation
                for action in legal
            )
            and operation == "pass_mode_decision"
            and active_decision is None
        ):
            target_window_passed = True
        if controller._matches_target(chosen):
            if active_decision is not None:
                raise C7ActiveModeDecisionFullGameError("目标动作被选择超过一次")
            active_decision = {
                "decision_index": index,
                "operation": operation,
                "actor_id": chosen.actor_id,
                "target_id": _target(chosen),
                "path": chosen.payload.get("path"),
                "chosen_action_id": chosen_id,
                "legal_action_set_sha256": decision["legal_action_set_sha256"],
                "expected_revision": context.expected_revision,
                "state_revision_before": state_revision_before,
                "response_window_id": context.response_window_id,
                "runtime_response_window_id": runtime_response_window_id,
                "state_before_sha256": decision["state_before_sha256"],
                "state_after_sha256": decision["state_after_sha256"],
                "event_start": decision["event_start"],
                "event_end": decision["event_end"],
                "target_match_count": sum(
                    1 for action in legal if controller._matches_target(action)
                ),
            }
        selected_actor = controller.selected_actor_id
        before_role = (
            game.role_current.get(selected_actor) if selected_actor is not None else None
        )
        mark_available_before = (
            bool(game._variant.ambitionist_mark_available.get(selected_actor, False))
            if selected_actor is not None
            else False
        )
        turn_player_before = game.current_player_id
        alive_player_ids_before = tuple(
            player.player_id for player in game.state.players if player.alive
        )
        spy_path_chooser_id_before = game._variant.spy_path_chooser_id
        spy_path_choice_before = game._variant.spy_path_choice
        spy_path_pending_before = game._variant.spy_path_pending
        spy_path_locked_before = game._variant.spy_path_locked
        event_start = len(game.events)
        if (
            scenario.scenario_id == HEIR_SUCCESSION
            and operation in {"succession_obtain_none", "succession_obtain_card"}
        ):
            old_lord_id = controller.public_lord_actor_id
            successor_id = controller.selected_target_id
            if old_lord_id is None or successor_id is None:
                raise C7ActiveModeDecisionFullGameError("继位窗口缺少公开学习的主公/储君绑定")
            pending_succession = game._runtime.pending_succession
            if pending_succession is None:
                raise C7ActiveModeDecisionFullGameError("继位窗口缺少正式pending_succession")
            heir = game.state.players_by_id[successor_id]
            succession_transition = {
                "decision_index": index,
                "expected_revision": context.expected_revision,
                "state_revision_before": state_revision_before,
                "response_window_id": context.response_window_id,
                "runtime_response_window_id": runtime_response_window_id,
                "window_id": chosen.payload.get("window_id"),
                "chosen_window_id": chosen.payload.get("window_id"),
                "pending_succession_window_id": pending_succession.window_id,
                "operation": operation,
                "action_actor_id": chosen.actor_id,
                "old_lord_id": old_lord_id,
                "successor_id": successor_id,
                "pending_old_lord_id": pending_succession.old_lord_id,
                "pending_successor_id": pending_succession.successor_id,
                "pending_dying_id_before": game._runtime.pending_dying_id,
                "state_before_sha256": decision["state_before_sha256"],
                "state_after_sha256": decision["state_after_sha256"],
                "event_start": decision["event_start"],
                "event_end": decision["event_end"],
                "old_lord_alive_before": game.state.players_by_id[old_lord_id].alive,
                "seat_before": game.seat_by_player[successor_id],
                "max_hp_before": heir.max_hp,
                "hp_before": heir.hp,
            }
        executed = game.step(BatchActionIdController(chosen_id))
        if executed.action_id != chosen_id:
            raise ProductionReplayDivergenceError(
                "controller", index, "fresh controller step执行了不同action_id"
            )
        event_end = len(game.events)
        if event_start != int(decision["event_start"]) or event_end != int(
            decision["event_end"]
        ):
            raise ProductionReplayDivergenceError(
                "event", index, "causal proof观察到的live event slice与记录不一致"
            )
        event_slice = tuple(game.events[event_start:event_end])
        if controller._matches_target(chosen):
            assert active_decision is not None
            if operation == "select_heir":
                heir_established_transition = {
                    "decision_index": index,
                    "operation": operation,
                    "actor_id": chosen.actor_id,
                    "target_id": _target(chosen),
                    "expected_revision": context.expected_revision,
                    "state_revision_before": active_decision["state_revision_before"],
                    "response_window_id": context.response_window_id,
                    "runtime_response_window_id": active_decision[
                        "runtime_response_window_id"
                    ],
                    "state_before_sha256": decision["state_before_sha256"],
                    "state_after_sha256": decision["state_after_sha256"],
                    "event_start": event_start,
                    "event_end": event_end,
                    "heir_player_id_after": game._variant.heir_player_id,
                    "heir_selection_used_after": game._variant.heir_selection_used,
                }
            elif operation == "choose_spy_path":
                assert selected_actor is not None
                choice_transition = {
                    "decision_index": index,
                    "actor_id": selected_actor,
                    "path": chosen.payload.get("path"),
                    "expected_revision": context.expected_revision,
                    "state_revision_before": active_decision["state_revision_before"],
                    "response_window_id": context.response_window_id,
                    "runtime_response_window_id": active_decision[
                        "runtime_response_window_id"
                    ],
                    "state_before_sha256": decision["state_before_sha256"],
                    "state_after_sha256": decision["state_after_sha256"],
                    "event_start": event_start,
                    "event_end": event_end,
                    "turn_after_choice": game._runtime.turn_number,
                    "role_after_choice": game.role_current[selected_actor],
                    "pending_after_choice": game._variant.spy_path_pending,
                    "locked_after_choice": game._variant.spy_path_locked,
                }
        after_role = (
            game.role_current.get(selected_actor) if selected_actor is not None else None
        )
        if (
            selected_actor is not None
            and before_role == "spy"
            and after_role in {"loyalist", "ambitionist"}
        ):
            reason = (
                "spy_converted_loyalist_announced"
                if after_role == "loyalist"
                else "ambitionist_conversion"
            )
            conversion_transition = {
                "decision_index": index,
                "actor_id": selected_actor,
                "expected_revision": context.expected_revision,
                "state_revision_before": state_revision_before,
                "response_window_id": context.response_window_id,
                "runtime_response_window_id": runtime_response_window_id,
                "trigger_operation": operation,
                "trigger_actor_id": chosen.actor_id,
                "state_before_sha256": decision["state_before_sha256"],
                "state_after_sha256": decision["state_after_sha256"],
                "event_start": event_start,
                "event_end": event_end,
                "role_before": before_role,
                "role_after": after_role,
                "spy_path_chooser_id_before": spy_path_chooser_id_before,
                "spy_path_chooser_id_after": game._variant.spy_path_chooser_id,
                "spy_path_choice_before": spy_path_choice_before,
                "spy_path_choice_after": game._variant.spy_path_choice,
                "pending_before": spy_path_pending_before,
                "pending_after": game._variant.spy_path_pending,
                "locked_before": spy_path_locked_before,
                "locked_after": game._variant.spy_path_locked,
                "turn_after": game._runtime.turn_number,
                "turn_player_before": turn_player_before,
                "turn_player_after": game.current_player_id,
                "numbered_player_order": list(game.numbered_player_order),
                "alive_player_ids_before": list(alive_player_ids_before),
                "alive_player_ids_after": [
                    player.player_id for player in game.state.players if player.alive
                ],
                "phase_after": game.phase.value,
                "is_extra_turn_after": game._variant.is_extra_turn,
                "mark_available_after": bool(
                    game._variant.ambitionist_mark_available.get(
                        selected_actor, False
                    )
                ),
                "mark_owner_id_after": (
                    selected_actor
                    if game._variant.ambitionist_mark_available.get(
                        selected_actor, False
                    )
                    else None
                ),
                "conversion_event": _single_event_binding(
                    event_slice,
                    event_start=event_start,
                    event_end=event_end,
                    decision_index=index,
                    reason=reason,
                ),
            }
        mark_available_after = (
            bool(game._variant.ambitionist_mark_available.get(selected_actor, False))
            if selected_actor is not None
            else False
        )
        if (
            selected_actor is not None
            and chosen.actor_id == selected_actor
            and mark_available_before
            and not mark_available_after
            and (
                operation == "ambitionist_mark_draw_two"
                or (
                    chosen.payload.get("source") == "ambitionist_mark"
                    and chosen.payload.get("virtual") is True
                )
            )
        ):
            mark_event_matches = [
                (event_start + offset, event)
                for offset, event in enumerate(event_slice)
                if _event_type(event) == "card_gained"
                and _event_payload(event).get("reason")
                == "ambitionist_mark_draw_two"
                and _event_targets(event) == (selected_actor,)
            ]
            mark_use_transition = {
                "decision_index": index,
                "actor_id": chosen.actor_id,
                "operation": operation,
                "expected_revision": context.expected_revision,
                "state_revision_before": state_revision_before,
                "response_window_id": context.response_window_id,
                "runtime_response_window_id": runtime_response_window_id,
                "state_before_sha256": decision["state_before_sha256"],
                "state_after_sha256": decision["state_after_sha256"],
                "event_start": event_start,
                "event_end": event_end,
                "mark_available_before": mark_available_before,
                "mark_available_after": mark_available_after,
                "bound_event_indices": [
                    event_index for event_index, _event in mark_event_matches
                ],
                "mark_use_events": [
                    _event_binding(
                        event,
                        event_index=event_index,
                        decision_index=index,
                        event_start=event_start,
                        event_end=event_end,
                    )
                    for event_index, event in mark_event_matches
                ],
            }
        if (
            scenario.scenario_id == HEIR_SUCCESSION
            and succession_transition is not None
            and game.current_lord_player_id == succession_transition["successor_id"]
            and "seat_after" not in succession_transition
        ):
            old_lord_id = str(succession_transition["old_lord_id"])
            successor_id = str(succession_transition["successor_id"])
            heir = game.state.players_by_id[successor_id]
            death_matches = [
                (event_start + offset, event)
                for offset, event in enumerate(event_slice)
                if _event_type(event) == "death"
                and _event_targets(event) == (old_lord_id,)
            ]
            death_binding = (
                _event_binding(
                    death_matches[0][1],
                    event_index=death_matches[0][0],
                    decision_index=index,
                    event_start=event_start,
                    event_end=event_end,
                )
                if len(death_matches) == 1
                else {
                    "match_count": len(death_matches),
                    "decision_index": index,
                    "event_start": event_start,
                    "event_end": event_end,
                    "reason": "",
                }
            )
            death_binding["match_count"] = len(death_matches)
            succession_transition.update(
                {
                    "seat_after": game.seat_by_player[successor_id],
                    "max_hp_after": heir.max_hp,
                    "hp_after": heir.hp,
                    "numbered_order_unchanged": tuple(game.numbered_player_order)
                    == initial_order,
                    "old_lord_dead_after": not game.state.players_by_id[
                        old_lord_id
                    ].alive,
                    "current_lord_id_after": game.current_lord_player_id,
                    "is_extra_turn_after": game._variant.is_extra_turn,
                    "death_event": death_binding,
                    "succession_event": _single_event_binding(
                        event_slice,
                        event_start=event_start,
                        event_end=event_end,
                        decision_index=index,
                        reason="succession_lord_reveal",
                    ),
                    "recovery_event": _single_event_binding(
                        event_slice,
                        event_start=event_start,
                        event_end=event_end,
                        decision_index=index,
                        reason="succession_recover",
                    ),
                }
            )

    if not game.is_finished:
        raise ProductionReplayDivergenceError(
            "decision", len(record.decisions), "fresh controller轨迹非终局"
        )
    if active_decision is None or controller.target_selection_count != 1:
        raise C7ActiveModeDecisionFullGameError("目标主动动作未被恰好选择一次")
    if target_window_passed:
        raise C7ActiveModeDecisionFullGameError("目标窗口被pass")

    events = tuple(game.events)
    unsupported = any(
        _event_payload(event).get("unsupported_rule") is True
        or _event_payload(event).get("approximation") is True
        for event in events
    )
    common = {
        "fixture_applied": record.header["fixture_applied"] is False,
        "analysis_only": record.header["initial_configuration"]["analysis_only"]
        is False,
        "formal_result": record.header["formal_result"] is True,
        "target_action_selected_exactly_once": controller.target_selection_count == 1,
        "target_window_passed": target_window_passed,
        "terminal": game.is_finished,
        "unsupported_or_approximation": unsupported,
        "winner_id": game.winner_id,
        "finish_reason": game._runtime.game_over_reason
        or game.outcome_policy.finish_reason,
        "decision_count": len(record.decisions),
        "turn_count": game._runtime.turn_number,
    }
    terminal_transition = {
        "is_finished": game.is_finished,
        "winner_id": game.winner_id,
        "finish_reason": common["finish_reason"],
        "last_decision_index": len(record.decisions) - 1,
        "event_count": len(events),
    }
    scenario_evidence: dict[str, object]
    causal_binding: dict[str, object] = {
        "active_decision": active_decision,
        "terminal_transition": terminal_transition,
    }
    if scenario.scenario_id == HEIR_SUCCESSION:
        if succession_transition is None or heir_established_transition is None:
            raise C7ActiveModeDecisionFullGameError("未动态观察到立储、继位窗口与效果")
        causal_binding["heir_established_transition"] = heir_established_transition
        causal_binding["succession_transition"] = succession_transition
        causal_proven = _causal_binding_proven(scenario.scenario_id, causal_binding)
        scenario_evidence = {
            "old_lord_id": succession_transition["old_lord_id"],
            "heir_id": succession_transition["successor_id"],
            "initial_heir_seat": initial_seat["p3"],
            "select_actor_valid": active_decision["actor_id"] == "p6",
            "select_target_valid": active_decision["target_id"] == "p3",
            "old_lord_dead": succession_transition.get("old_lord_dead_after"),
            "old_lord_natural_death_event": _event_binding_matches(
                succession_transition.get("death_event"),
                event_type="death",
                reason="",
                decision_index=int(succession_transition["decision_index"]),
                event_start=int(succession_transition["event_start"]),
                event_end=int(succession_transition["event_end"]),
                raw_target_ids=(str(succession_transition["old_lord_id"]),),
            ),
            "succession_event": _event_binding_matches(
                succession_transition.get("succession_event"),
                event_type="identity_revealed",
                reason="succession_lord_reveal",
                decision_index=int(succession_transition["decision_index"]),
                event_start=int(succession_transition["event_start"]),
                event_end=int(succession_transition["event_end"]),
                raw_target_ids=(str(succession_transition["successor_id"]),),
                required_payload={"identity": "lord"},
            ),
            "succession_recover_event": _event_binding_matches(
                succession_transition.get("recovery_event"),
                event_type="hp_recover",
                reason="succession_recover",
                decision_index=int(succession_transition["decision_index"]),
                event_start=int(succession_transition["event_start"]),
                event_end=int(succession_transition["event_end"]),
                raw_target_ids=(str(succession_transition["successor_id"]),),
            ),
            "seat_unchanged": succession_transition.get("seat_before")
            == succession_transition.get("seat_after")
            == initial_seat["p3"],
            "numbered_order_unchanged": succession_transition.get(
                "numbered_order_unchanged"
            ),
            "max_hp_plus_one": succession_transition.get("max_hp_after")
            == int(succession_transition["max_hp_before"]) + 1,
            "hp_recovery_correct": succession_transition.get("hp_after")
            == min(
                int(succession_transition["max_hp_after"]),
                int(succession_transition["hp_before"]) + 1,
            ),
            "is_extra_turn": succession_transition.get("is_extra_turn_after"),
            "causal_binding_proven": causal_proven,
            "natural_identity_victory": game.winner_id
            == scenario.expected_winner_id
            and common["finish_reason"] == scenario.expected_finish_reason,
        }
        required = (
            scenario_evidence["select_actor_valid"],
            scenario_evidence["select_target_valid"],
            scenario_evidence["old_lord_dead"],
            scenario_evidence["old_lord_natural_death_event"],
            scenario_evidence["succession_event"],
            scenario_evidence["seat_unchanged"],
            scenario_evidence["numbered_order_unchanged"],
            scenario_evidence["max_hp_plus_one"],
            scenario_evidence["hp_recovery_correct"],
            scenario_evidence["is_extra_turn"] is False,
            scenario_evidence["causal_binding_proven"],
            scenario_evidence["natural_identity_victory"],
        )
    else:
        expected_role = (
            "loyalist"
            if scenario.scenario_id == SPY_TO_LOYALIST
            else "ambitionist"
        )
        if choice_transition is None or conversion_transition is None:
            raise C7ActiveModeDecisionFullGameError("未动态观察到择途与后续转化")
        causal_binding["choice_transition"] = choice_transition
        causal_binding["conversion_transition"] = conversion_transition
        if scenario.scenario_id == SPY_TO_AMBITIONIST:
            causal_binding["mark_use_transition"] = mark_use_transition
        causal_proven = _causal_binding_proven(scenario.scenario_id, causal_binding)
        scenario_evidence = {
            "chooser_id": active_decision["actor_id"],
            "path": active_decision["path"],
            "choice_turn": choice_transition["turn_after_choice"],
            "role_after_choice": choice_transition["role_after_choice"],
            "pending_after_choice": choice_transition["pending_after_choice"],
            "locked_after_choice": choice_transition["locked_after_choice"],
            "converted_role": conversion_transition["role_after"],
            "conversion_turn": conversion_transition["turn_after"],
            "conversion_phase": conversion_transition["phase_after"],
            "conversion_is_extra_turn": conversion_transition[
                "is_extra_turn_after"
            ],
            "choice_actor_valid": active_decision["actor_id"]
            == choice_transition["actor_id"],
            "choice_path_valid": active_decision["path"] == scenario.target_path,
            "conversion_detected": True,
            "conversion_at_later_turn_start": conversion_transition["phase_after"]
            == ProductionPhase.PREPARE.value
            and int(conversion_transition["turn_after"])
            > int(choice_transition["turn_after_choice"])
            and conversion_transition["is_extra_turn_after"] is False,
            "conversion_event": causal_proven,
            "ambitionist_mark_established": conversion_transition[
                "mark_available_after"
            ],
            "ambitionist_mark_use_count": 1 if mark_use_transition else 0,
            "causal_binding_proven": causal_proven,
            "natural_identity_victory": game.winner_id
            == scenario.expected_winner_id
            and common["finish_reason"] == scenario.expected_finish_reason,
        }
        required_list: list[object] = [
            scenario_evidence.get("role_after_choice") == "spy",
            scenario_evidence.get("pending_after_choice") is True,
            scenario_evidence.get("locked_after_choice") is True,
            scenario_evidence["choice_actor_valid"],
            scenario_evidence["choice_path_valid"],
            scenario_evidence.get("converted_role") == expected_role,
            scenario_evidence["conversion_at_later_turn_start"],
            scenario_evidence["conversion_event"],
            scenario_evidence["causal_binding_proven"],
            scenario_evidence["natural_identity_victory"],
        ]
        if scenario.scenario_id == SPY_TO_AMBITIONIST:
            required_list.extend(
                (
                    scenario_evidence["ambitionist_mark_established"],
                    int(scenario_evidence["ambitionist_mark_use_count"]) >= 1,
                )
            )
        required = tuple(required_list)

    scenario_proven = (
        all(required)
        and common["fixture_applied"] is True
        and common["analysis_only"] is True
        and common["formal_result"] is True
        and common["target_action_selected_exactly_once"] is True
        and common["target_window_passed"] is False
        and common["terminal"] is True
        and common["unsupported_or_approximation"] is False
    )
    if not scenario_proven:
        raise C7ActiveModeDecisionFullGameError(
            f"{scenario.scenario_id}未满足冻结的动态proof要求"
        )
    return {
        "schema": C7_ACTIVE_MODE_DECISION_PROOF_SCHEMA_V1,
        "scenario_id": scenario.scenario_id,
        "seed": scenario.seed,
        "active_decision": active_decision,
        "causal_binding": causal_binding,
        "common": common,
        "scenario_evidence": scenario_evidence,
        "scenario_proven": True,
    }


@dataclass(frozen=True, slots=True)
class C7ActiveModeDecisionReplayVerificationResultV1:
    verified: bool
    scenario_id: str
    seed: int
    proof: Mapping[str, object]


def reexecute_c7_active_mode_decision_full_game_replay_v1(
    replay: C7ActiveModeDecisionFullGameReplayV1,
) -> C7ActiveModeDecisionReplayVerificationResultV1:
    if not isinstance(replay, C7ActiveModeDecisionFullGameReplayV1):
        raise TypeError("C7主动决策重执行只接受V1 replay envelope")
    replay.verify_integrity()
    scenario = _scenario_from_value(replay.header["scenario_configuration"])
    _preflight_header_identity(replay.header, scenario)
    record = replay.production_replay_v1
    if record.record_sha256 != replay.header["production_replay_v1_sha256"]:
        raise C7ActiveModeDecisionFullGameError("production replay-v1 hash不匹配")
    production_header = record.header
    if production_header["schema_version"] != REEXECUTION_SCHEMA:
        raise C7ActiveModeDecisionFullGameError("production replay schema漂移")
    if production_header["mode_id"] != scenario.mode_id:
        raise C7ActiveModeDecisionFullGameError("production replay mode漂移")
    if production_header["seed"] != scenario.seed:
        raise C7ActiveModeDecisionFullGameError("production replay seed漂移")
    if production_header["fixture_applied"] is not False:
        raise C7ActiveModeDecisionFullGameError("正式C7主动决策回放禁止fixture")
    if production_header["formal_result"] is not True:
        raise C7ActiveModeDecisionFullGameError("正式C7主动决策回放必须是formal_result")
    initial = _require_mapping(
        production_header["initial_configuration"], "initial_configuration"
    )
    if initial.get("analysis_only") is not False:
        raise C7ActiveModeDecisionFullGameError("正式C7主动决策回放禁止analysis_only")
    if _ruleset_identity_from_record_header(production_header) != replay.header[
        "ruleset_identity"
    ]:
        raise C7ActiveModeDecisionFullGameError("production replay ruleset identity漂移")
    production_result = reexecute_production_replay(record)
    if production_result.verified is not True:
        raise C7ActiveModeDecisionFullGameError("production replay-v1 strict reexecute失败")
    derived = _rederive_required_proof(record, scenario)
    if _plain(replay.required_active_decision_proof) != derived:
        raise C7ActiveModeDecisionFullGameError(
            "serialized required_active_decision_proof与live重新派生值不一致"
        )
    return C7ActiveModeDecisionReplayVerificationResultV1(
        verified=True,
        scenario_id=scenario.scenario_id,
        seed=scenario.seed,
        proof=_freeze(derived),
    )


def record_c7_active_mode_decision_full_game_v1(
    scenario_id: str,
) -> C7ActiveModeDecisionFullGameReplayV1:
    scenario = c7_active_mode_decision_scenario_v1(scenario_id)
    identities_at_start = _current_identity_values()
    game = FormalHeirAndSpyChoiceIdentitySession(
        seed=scenario.seed,
        configuration=FormalHeirAndSpyChoiceIdentityConfiguration.formal_profile(),
        analysis_only=False,
    )
    if type(game) is not FormalHeirAndSpyChoiceIdentitySession:
        raise C7ActiveModeDecisionFullGameError("canonical factory返回错误session类型")
    controller = C7ActiveModeDecisionAcceptanceControllerV1(scenario)
    record = record_reference_production_batch(
        scenario.seed,
        controller=controller,
        max_steps=4000,
        fixture=None,
        _game=game,
    )
    if controller.target_selection_count != 1:
        raise C7ActiveModeDecisionFullGameError("录制轨迹未主动选择目标动作恰好一次")
    identities_at_end = _current_identity_values()
    if identities_at_start != identities_at_end:
        raise C7ActiveModeDecisionReplayIdentityError(
            "implementation/rules/profile/deck identities",
            sha256_value(identities_at_start),
            sha256_value(identities_at_end),
        )
    if _ruleset_identity_from_record_header(record.header) != identities_at_end[
        "ruleset_identity"
    ]:
        raise C7ActiveModeDecisionFullGameError("录制production replay ruleset identity漂移")
    production_result = reexecute_production_replay(record)
    if production_result.verified is not True:
        raise C7ActiveModeDecisionFullGameError("录制后的production strict replay失败")
    proof = _rederive_required_proof(record, scenario)
    header = {
        "contract_id": NEXT_STAGE_C7_ACTIVE_MODE_DECISION_FULL_GAME_ACCEPTANCE_V1,
        "scenario_id": scenario.scenario_id,
        "seed": scenario.seed,
        "mode_id": scenario.mode_id,
        "controller_id": C7_ACTIVE_MODE_DECISION_ACCEPTANCE_CONTROLLER_V1_ID,
        "controller_version": C7_ACTIVE_MODE_DECISION_ACCEPTANCE_CONTROLLER_V1_VERSION,
        "scenario_configuration_schema": C7_ACTIVE_MODE_DECISION_SCENARIO_SCHEMA_V1,
        "scenario_configuration": scenario.to_dict(),
        "scenario_configuration_sha256": scenario.configuration_sha256,
        **identities_at_end,
        "production_replay_v1_sha256": record.record_sha256,
    }
    replay = C7ActiveModeDecisionFullGameReplayV1(
        header=header,
        production_replay_v1=record,
        required_active_decision_proof=proof,
    )
    return replay


@dataclass(frozen=True, slots=True)
class C7ActiveModeDecisionFullGameRowV1:
    scenario_id: str
    seed: int
    replay: C7ActiveModeDecisionFullGameReplayV1

    def __post_init__(self) -> None:
        scenario = c7_active_mode_decision_scenario_v1(self.scenario_id)
        if self.seed != scenario.seed:
            raise C7ActiveModeDecisionFullGameError("matrix row seed与冻结配置不一致")
        if self.replay.scenario_id != self.scenario_id or self.replay.seed != self.seed:
            raise C7ActiveModeDecisionFullGameError("matrix row与replay主键不一致")

    def to_dict(self) -> dict[str, object]:
        return {
            "scenario_id": self.scenario_id,
            "seed": self.seed,
            "replay": self.replay.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class C7ActiveModeDecisionDerivedGatesV1:
    c7_active_mode_decision_full_game_v1_proven: bool

    def to_dict(self) -> dict[str, bool]:
        return {
            "c7_active_mode_decision_full_game_v1_proven": self.c7_active_mode_decision_full_game_v1_proven
        }


@dataclass(frozen=True, slots=True)
class C7ActiveModeDecisionFullGameMatrixV1:
    rows: tuple[C7ActiveModeDecisionFullGameRowV1, ...]

    def __post_init__(self) -> None:
        if type(self.rows) is not tuple:
            raise C7ActiveModeDecisionFullGameError("matrix rows必须是元组")
        ids = tuple(row.scenario_id for row in self.rows)
        if ids != C7_ACTIVE_MODE_DECISION_REQUIRED_SCENARIOS_V1:
            raise C7ActiveModeDecisionFullGameError(
                "matrix rows必须按冻结顺序恰好包含三个required scenarios"
            )

    def derived_gates(self) -> C7ActiveModeDecisionDerivedGatesV1:
        verified = []
        for row in self.rows:
            result = reexecute_c7_active_mode_decision_full_game_replay_v1(row.replay)
            verified.append(
                result.verified is True
                and result.scenario_id == row.scenario_id
                and result.seed == row.seed
                and result.proof["scenario_proven"] is True
            )
        return C7ActiveModeDecisionDerivedGatesV1(
            c7_active_mode_decision_full_game_v1_proven=(
                len(verified) == 3 and all(verified)
            )
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": C7_ACTIVE_MODE_DECISION_FULL_GAME_MATRIX_SCHEMA_V1,
            "required_scenarios": list(
                C7_ACTIVE_MODE_DECISION_REQUIRED_SCENARIOS_V1
            ),
            "rows": [row.to_dict() for row in self.rows],
            "derived_gates": self.derived_gates().to_dict(),
        }

    @classmethod
    def from_dict(
        cls, value: Mapping[str, object]
    ) -> "C7ActiveModeDecisionFullGameMatrixV1":
        raw = _require_mapping(value, "C7主动决策matrix")
        _require_exact_fields(
            raw,
            frozenset({"schema", "required_scenarios", "rows", "derived_gates"}),
            "C7主动决策matrix",
        )
        if raw["schema"] != C7_ACTIVE_MODE_DECISION_FULL_GAME_MATRIX_SCHEMA_V1:
            raise C7ActiveModeDecisionFullGameError("不支持的C7主动决策matrix schema")
        required = tuple(
            str(item)
            for item in _require_sequence(
                raw["required_scenarios"], "required_scenarios"
            )
        )
        if required != C7_ACTIVE_MODE_DECISION_REQUIRED_SCENARIOS_V1:
            raise C7ActiveModeDecisionFullGameError("required_scenarios漂移")
        raw_rows = _require_sequence(raw["rows"], "rows")
        row_ids: list[str] = []
        for index, raw_row in enumerate(raw_rows):
            row_map = _require_mapping(raw_row, f"rows[{index}]")
            _require_exact_fields(
                row_map,
                frozenset({"scenario_id", "seed", "replay"}),
                f"rows[{index}]",
            )
            scenario_id = row_map["scenario_id"]
            if not isinstance(scenario_id, str):
                raise C7ActiveModeDecisionFullGameError("matrix scenario_id必须是字符串")
            row_ids.append(scenario_id)
        if tuple(row_ids) != C7_ACTIVE_MODE_DECISION_REQUIRED_SCENARIOS_V1:
            raise C7ActiveModeDecisionFullGameError(
                "matrix拒绝缺失、重复、未知、额外或乱序row"
            )
        rows: list[C7ActiveModeDecisionFullGameRowV1] = []
        for index, raw_row in enumerate(raw_rows):
            row_map = _require_mapping(raw_row, f"rows[{index}]")
            scenario_id = str(row_map["scenario_id"])
            seed = _require_seed(row_map["seed"], f"rows[{index}].seed")
            replay = C7ActiveModeDecisionFullGameReplayV1.from_dict(
                _require_mapping(row_map["replay"], f"rows[{index}].replay")
            )
            rows.append(C7ActiveModeDecisionFullGameRowV1(scenario_id, seed, replay))
        derived = _require_mapping(raw["derived_gates"], "derived_gates")
        _require_exact_fields(
            derived,
            frozenset({"c7_active_mode_decision_full_game_v1_proven"}),
            "derived_gates",
        )
        if derived["c7_active_mode_decision_full_game_v1_proven"] is not True:
            raise C7ActiveModeDecisionFullGameError("serialized derived gate与严格重执行不一致")
        matrix = cls(tuple(rows))
        # 每行 from_dict 已执行 production strict replay + fresh controller proof；
        # 不信任 serialized bool，只接受三行独立重执行均成功后的 True。
        return matrix


class C7ActiveModeDecisionFullGameOrchestratorV1:
    """只运行冻结三行场景；不接收 caller session/factory/fixture。"""

    def run_scenario(
        self, scenario_id: str
    ) -> C7ActiveModeDecisionFullGameRowV1:
        scenario = c7_active_mode_decision_scenario_v1(scenario_id)
        replay = record_c7_active_mode_decision_full_game_v1(scenario_id)
        return C7ActiveModeDecisionFullGameRowV1(
            scenario_id=scenario.scenario_id,
            seed=scenario.seed,
            replay=replay,
        )

    def run_matrix(self) -> C7ActiveModeDecisionFullGameMatrixV1:
        return C7ActiveModeDecisionFullGameMatrixV1(
            tuple(
                self.run_scenario(scenario_id)
                for scenario_id in C7_ACTIVE_MODE_DECISION_REQUIRED_SCENARIOS_V1
            )
        )


__all__ = [
    "NEXT_STAGE_C7_ACTIVE_MODE_DECISION_FULL_GAME_ACCEPTANCE_V1",
    "C7_ACTIVE_MODE_DECISION_ACCEPTANCE_CONTROLLER_V1_ID",
    "C7_ACTIVE_MODE_DECISION_ACCEPTANCE_CONTROLLER_V1_VERSION",
    "C7_ACTIVE_MODE_DECISION_SCENARIO_SCHEMA_V1",
    "C7_ACTIVE_MODE_DECISION_FULL_GAME_REPLAY_SCHEMA_V1",
    "C7_ACTIVE_MODE_DECISION_FULL_GAME_MATRIX_SCHEMA_V1",
    "C7_ACTIVE_MODE_DECISION_REQUIRED_SCENARIOS_V1",
    "C7_ACTIVE_MODE_DECISION_FROZEN_SEEDS_V1",
    "C7_ACTIVE_MODE_DECISION_SCENARIO_CONFIGS_V1",
    "HEIR_SUCCESSION",
    "SPY_TO_LOYALIST",
    "SPY_TO_AMBITIONIST",
    "C7ActiveModeDecisionFullGameError",
    "C7ActiveModeDecisionReplayIdentityError",
    "C7ActiveModeDecisionScenarioV1",
    "C7PublicActionContextV1",
    "C7ActiveModeDecisionAcceptanceControllerV1",
    "C7ActiveModeDecisionFullGameReplayV1",
    "C7ActiveModeDecisionReplayVerificationResultV1",
    "C7ActiveModeDecisionFullGameRowV1",
    "C7ActiveModeDecisionDerivedGatesV1",
    "C7ActiveModeDecisionFullGameMatrixV1",
    "C7ActiveModeDecisionFullGameOrchestratorV1",
    "c7_active_mode_decision_scenario_v1",
    "record_c7_active_mode_decision_full_game_v1",
    "reexecute_c7_active_mode_decision_full_game_replay_v1",
]
