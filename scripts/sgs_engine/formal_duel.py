"""正式160张无技能单挑的生产模式薄层与现场就绪检查。

本模块不复制 ``GameState``、事件、动作、响应、伤害、距离、随机或回放
语义。``FormalNoSkillDuelSession`` 直接复用 ``ProductionBasicCardBatch``
的同一权威核心，只替换模式 ID，并把模式配置与角色元数据显式绑定到初始
状态。当前 Knowledge 尚未确认正式单挑配置，因此正式入口保持失败关闭；
``analysis_convention`` 只供开发诊断，绝不能标记为正式结果。
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Iterable, Mapping, Sequence

from .actions import ActionContext, ActionType, LegalAction, UnsupportedRuleError
from .model import DRAW_PILE, CharacterMetadata
from .production_batch import (
    FORMAL_NO_SKILL_DUEL_MODE,
    BatchReferenceController,
    ProductionBasicCardBatch,
    ProductionBatchSafetyLimitError,
    ProductionPhase,
)
from .production_cards import (
    PRODUCTION_ARMOR_KEYS,
    PRODUCTION_BASIC_CARD_KEYS,
    PRODUCTION_DELAYED_TRICK_KEYS,
    PRODUCTION_MOUNT_KEYS,
    PRODUCTION_TRICK_KEYS,
    WEAPON_SKILL_STATUS,
    FormalCardRegistry,
)


ALLOWED_RULE_STATUS: frozenset[str] = frozenset(
    {
        "当前确认",
        "用户整理解释",
        "文本推导",
        "模拟假设",
        "待核验",
        "历史规则",
        "分析约定",
    }
)
_FORMAL_SOURCE_STATUSES: frozenset[str] = frozenset({"当前确认"})
# 当前仓库没有经 Knowledge 绑定的正式 duel profile，也没有完成可计入验收的
# 100-seed 严格重执行证据。该哨兵故意是模块私有常量；会话子类或调用方配置
# 不能把它覆写为 True 来制造 formal_result。
_FORMAL_EXECUTION_RELEASED = False


class FormalDuelConfigurationError(ValueError):
    """正式单挑配置缺失、越界或没有足够规则来源。"""


def _nonempty(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise FormalDuelConfigurationError(f"{label}必须是非空字符串")
    return value.strip()


def _pair_of_positive_ints(value: object, label: str) -> tuple[int, int]:
    if isinstance(value, (str, bytes)):
        raise FormalDuelConfigurationError(f"{label}必须恰好包含两个正整数")
    try:
        prepared = tuple(value)  # type: ignore[arg-type]
    except TypeError as exc:
        raise FormalDuelConfigurationError(
            f"{label}必须恰好包含两个正整数"
        ) from exc
    if len(prepared) != 2 or any(
        isinstance(item, bool) or not isinstance(item, int) or item < 1
        for item in prepared
    ):
        raise FormalDuelConfigurationError(f"{label}必须恰好包含两个正整数")
    return prepared  # type: ignore[return-value]


@dataclass(frozen=True, slots=True)
class FormalDuelConfiguration:
    """带来源状态的两人无技能模式配置。

    配置只保存模式真值，不提供默认“p1男/p2女”等推断。角色元数据为
    ``None`` 时，依赖性别的卡牌会在权威规则路径失败关闭。
    """

    platform: str
    version: str
    source_location: str
    verification_status: str
    deck_applicable: bool
    initial_hand_count: int
    player_hp: tuple[int, int]
    player_max_hp: tuple[int, int]
    first_player_policy: str
    participants: tuple[CharacterMetadata | None, CharacterMetadata | None]

    def __post_init__(self) -> None:
        for field_name, label in (
            ("platform", "平台"),
            ("version", "版本"),
            ("source_location", "来源位置"),
        ):
            object.__setattr__(
                self, field_name, _nonempty(getattr(self, field_name), label)
            )
        status = _nonempty(self.verification_status, "核验状态")
        if status not in ALLOWED_RULE_STATUS:
            raise FormalDuelConfigurationError(
                "核验状态只能使用项目允许的三国杀状态标签"
            )
        object.__setattr__(self, "verification_status", status)
        if not isinstance(self.deck_applicable, bool):
            raise FormalDuelConfigurationError("牌堆是否适用必须是布尔值")
        if (
            isinstance(self.initial_hand_count, bool)
            or not isinstance(self.initial_hand_count, int)
            or self.initial_hand_count < 1
        ):
            raise FormalDuelConfigurationError("初始手牌数必须是正整数")
        hp = _pair_of_positive_ints(self.player_hp, "初始体力")
        max_hp = _pair_of_positive_ints(self.player_max_hp, "体力上限")
        if any(current > maximum for current, maximum in zip(hp, max_hp)):
            raise FormalDuelConfigurationError("初始体力不能高于体力上限")
        object.__setattr__(self, "player_hp", hp)
        object.__setattr__(self, "player_max_hp", max_hp)
        policy = _nonempty(self.first_player_policy, "先手策略")
        if policy != "deterministic_rng":
            raise FormalDuelConfigurationError(
                "当前统一核心只支持deterministic_rng先手策略；其他规则必须先实现"
            )
        object.__setattr__(self, "first_player_policy", policy)
        participants = tuple(self.participants)
        if len(participants) != 2 or any(
            item is not None and not isinstance(item, CharacterMetadata)
            for item in participants
        ):
            raise FormalDuelConfigurationError(
                "参战角色元数据必须恰好包含两项CharacterMetadata或None"
            )
        object.__setattr__(self, "participants", participants)

    @property
    def source_confirmed(self) -> bool:
        return (
            self.verification_status in _FORMAL_SOURCE_STATUSES
            and self.deck_applicable
            and all(
                item is not None and item.gender is not None
                for item in self.participants
            )
        )

    @classmethod
    def analysis_convention(cls) -> "FormalDuelConfiguration":
        """返回当前生产批处理参数的显式非正式诊断配置。"""

        return cls(
            platform="三国杀移动版",
            version="2026-07-25牌堆快照",
            source_location="现有生产批处理参数；不是正式单挑规则来源",
            verification_status="分析约定",
            deck_applicable=False,
            initial_hand_count=4,
            player_hp=(4, 4),
            player_max_hp=(4, 4),
            first_player_policy="deterministic_rng",
            participants=(None, None),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "platform": self.platform,
            "version": self.version,
            "source_location": self.source_location,
            "verification_status": self.verification_status,
            "deck_applicable": self.deck_applicable,
            "initial_hand_count": self.initial_hand_count,
            "player_hp": list(self.player_hp),
            "player_max_hp": list(self.player_max_hp),
            "first_player_policy": self.first_player_policy,
            "participants": [
                None
                if item is None
                else {
                    "character_key": item.character_key,
                    "gender": (
                        None if item.gender is None else item.gender.value
                    ),
                }
                for item in self.participants
            ],
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "FormalDuelConfiguration":
        if not isinstance(value, Mapping):
            raise FormalDuelConfigurationError("正式单挑配置必须是JSON对象")
        expected_fields = {
            "platform",
            "version",
            "source_location",
            "verification_status",
            "deck_applicable",
            "initial_hand_count",
            "player_hp",
            "player_max_hp",
            "first_player_policy",
            "participants",
        }
        actual_fields = set(value)
        if any(not isinstance(item, str) for item in actual_fields):
            raise FormalDuelConfigurationError("正式单挑配置字段名必须是字符串")
        if actual_fields != expected_fields:
            missing = sorted(expected_fields - actual_fields)
            extra = sorted(actual_fields - expected_fields)
            raise FormalDuelConfigurationError(
                "正式单挑配置字段必须精确匹配schema："
                f"missing={missing}，extra={extra}"
            )
        raw_participants = value.get("participants")
        if isinstance(raw_participants, (str, bytes)):
            raise FormalDuelConfigurationError("参战角色元数据必须是数组")
        try:
            participant_values = tuple(raw_participants)  # type: ignore[arg-type]
        except TypeError as exc:
            raise FormalDuelConfigurationError("参战角色元数据必须是数组") from exc
        participants: list[CharacterMetadata | None] = []
        for item in participant_values:
            if item is None:
                participants.append(None)
            elif isinstance(item, Mapping):
                participant_fields = set(item)
                if any(not isinstance(field, str) for field in participant_fields):
                    raise FormalDuelConfigurationError(
                        "参战角色元数据字段名必须是字符串"
                    )
                if participant_fields != {"character_key", "gender"}:
                    missing = sorted(
                        {"character_key", "gender"} - participant_fields
                    )
                    extra = sorted(
                        participant_fields - {"character_key", "gender"}
                    )
                    raise FormalDuelConfigurationError(
                        "参战角色元数据字段必须精确匹配schema："
                        f"missing={missing}，extra={extra}"
                    )
                participants.append(
                    CharacterMetadata(
                        character_key=item.get("character_key"),  # type: ignore[arg-type]
                        gender=item.get("gender"),  # type: ignore[arg-type]
                    )
                )
            else:
                raise FormalDuelConfigurationError("参战角色元数据项格式无效")
        return cls(
            platform=value.get("platform"),  # type: ignore[arg-type]
            version=value.get("version"),  # type: ignore[arg-type]
            source_location=value.get("source_location"),  # type: ignore[arg-type]
            verification_status=value.get("verification_status"),  # type: ignore[arg-type]
            deck_applicable=value.get("deck_applicable"),  # type: ignore[arg-type]
            initial_hand_count=value.get("initial_hand_count"),  # type: ignore[arg-type]
            player_hp=value.get("player_hp"),  # type: ignore[arg-type]
            player_max_hp=value.get("player_max_hp"),  # type: ignore[arg-type]
            first_player_policy=value.get("first_player_policy"),  # type: ignore[arg-type]
            participants=tuple(participants),  # type: ignore[arg-type]
        )


class FormalNoSkillDuelSession(ProductionBasicCardBatch):
    """复用同一生产核心的正式单挑模式会话；没有第二套引擎。"""

    MODE_ID = FORMAL_NO_SKILL_DUEL_MODE

    def __init__(
        self,
        *,
        seed: int,
        configuration: FormalDuelConfiguration,
        analysis_only: bool = False,
        session_id: str | None = None,
        session_secret: bytes | None = None,
    ) -> None:
        if type(self) is not _CANONICAL_FORMAL_SESSION_TYPE:
            raise TypeError(
                "正式单挑canonical会话不允许通过子类覆写释放或配置边界"
            )
        if not isinstance(configuration, FormalDuelConfiguration):
            raise TypeError("正式单挑会话必须接收FormalDuelConfiguration")
        if not isinstance(analysis_only, bool):
            raise TypeError("analysis_only必须是布尔值")
        if not configuration.source_confirmed and not analysis_only:
            raise FormalDuelConfigurationError(
                "正式单挑配置尚未由规则源确认；只能显式analysis_only诊断"
            )
        if (
            configuration.source_confirmed
            and not analysis_only
            and not _FORMAL_EXECUTION_RELEASED
        ):
            raise FormalDuelConfigurationError(
                "正式单挑仍有卡牌／重放门禁未关闭，禁止生成正式结果"
            )
        self._formal_configuration = configuration
        self._analysis_only = analysis_only
        super().__init__(
            seed=seed,
            player_hp=configuration.player_hp,
            player_max_hp=configuration.player_max_hp,
            initial_hand_count=configuration.initial_hand_count,
            shuffle=True,
            session_id=session_id,
            session_secret=session_secret,
        )
        players = tuple(
            replace(player, character=configuration.participants[index])
            for index, player in enumerate(self.state.players)
        )
        self._state = replace(self.state, players=players)

    @property
    def formal_configuration(self) -> FormalDuelConfiguration:
        return self._formal_configuration

    @property
    def analysis_only(self) -> bool:
        return self._analysis_only

    @property
    def formal_result_eligible(self) -> bool:
        return (
            _FORMAL_EXECUTION_RELEASED
            and self._formal_configuration.source_confirmed
            and not self._analysis_only
        )


_CANONICAL_FORMAL_SESSION_TYPE = FormalNoSkillDuelSession


class FormalDuelReferenceController:
    """覆盖全部生产卡牌动作的确定性验收控制器，不是竞技AI。"""

    strategy_version = "formal-duel-reference-controller.v1"

    def __init__(self) -> None:
        self._fallback = BatchReferenceController()

    def choose(
        self, legal_actions: Sequence[LegalAction], context: ActionContext
    ) -> LegalAction:
        if context.phase != ProductionPhase.PLAY.value:
            return self._fallback.choose(legal_actions, context)
        if not legal_actions:
            raise ValueError("正式单挑控制器收到空合法动作集合")
        if any(action.action_id is None for action in legal_actions):
            raise ValueError("正式单挑控制器只能接收已签发合法动作")

        def priority(action: LegalAction) -> tuple[int, str]:
            operation = str(action.payload.get("operation", ""))
            if operation == "heal_self":
                rank = 0
            elif operation == "use_wine_buff":
                rank = 1
            elif operation == "use_slash":
                rank = 2
            elif action.action_type is ActionType.PASS:
                rank = 99
            else:
                # 锦囊、延时锦囊、装备与重铸均走真实适配器；同级按公开
                # 实体ID/权威枚举顺序稳定选择，不使用会话秘密派生ID。
                rank = 3
            return rank, action.card_instance_id or ""

        return min(
            enumerate(legal_actions),
            key=lambda indexed: (*priority(indexed[1]), indexed[0]),
        )[1]


@dataclass(frozen=True, slots=True)
class FormalDuelBlocker:
    code: str
    category: str
    message: str


@dataclass(frozen=True, slots=True)
class FormalDuelCardStatus:
    """一类正式牌在全局与严格两人 duel 范围内的独立语义状态。"""

    card_key: str
    instance_count: int
    global_status: str
    duel_status: str
    reason: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "card_key": self.card_key,
            "instance_count": self.instance_count,
            "global_status": self.global_status,
            "duel_status": self.duel_status,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class FormalDuelReadiness:
    mode_id: str
    deck_count: int
    registered_card_key_count: int
    registered_instance_count: int
    global_complete_card_key_count: int
    global_complete_instance_count: int
    duel_complete_card_key_count: int
    duel_complete_instance_count: int
    global_card_semantics_complete: bool
    all_cards_implemented: bool
    mode_runtime_reachable: bool
    mode_implemented: bool
    deterministic_controller_implemented: bool
    reexecution_replay_supported: bool
    unsupported_rules: int
    approximation_count: int
    acceptance_seed_count: int
    acceptance_natural_end_count: int
    acceptance_failure_count: int
    fixed_seed_acceptance_passed: bool
    formal_duel_no_skill_ready: bool
    blockers: tuple[FormalDuelBlocker, ...]
    card_semantic_statuses: tuple[FormalDuelCardStatus, ...]
    # 汇总计数不是验收证据。门禁必须逐项检查这里的 canonical seed 记录，
    # 包括自然结束、异常/上限、unsupported/approximation 与严格重执行。
    acceptance_seed_results: tuple["FormalDuelSeedResult", ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "mode_id": self.mode_id,
            "deck_count": self.deck_count,
            "registered_card_key_count": self.registered_card_key_count,
            "registered_instance_count": self.registered_instance_count,
            "global_complete_card_key_count": self.global_complete_card_key_count,
            "global_complete_instance_count": self.global_complete_instance_count,
            "duel_complete_card_key_count": self.duel_complete_card_key_count,
            "duel_complete_instance_count": self.duel_complete_instance_count,
            "global_card_semantics_complete": self.global_card_semantics_complete,
            "all_cards_implemented": self.all_cards_implemented,
            "mode_runtime_reachable": self.mode_runtime_reachable,
            "mode_implemented": self.mode_implemented,
            "deterministic_controller_implemented": (
                self.deterministic_controller_implemented
            ),
            "reexecution_replay_supported": self.reexecution_replay_supported,
            "unsupported_rules": self.unsupported_rules,
            "approximation_count": self.approximation_count,
            "acceptance_seed_count": self.acceptance_seed_count,
            "acceptance_natural_end_count": self.acceptance_natural_end_count,
            "acceptance_failure_count": self.acceptance_failure_count,
            "fixed_seed_acceptance_passed": self.fixed_seed_acceptance_passed,
            "formal_duel_no_skill_ready": self.formal_duel_no_skill_ready,
            "blockers": [
                {
                    "code": item.code,
                    "category": item.category,
                    "message": item.message,
                }
                for item in self.blockers
            ],
            "card_semantic_statuses": [
                item.to_dict() for item in self.card_semantic_statuses
            ],
            "acceptance_seed_results": [
                item.to_dict() for item in self.acceptance_seed_results
            ],
        }


def _semantic_key_sets() -> tuple[frozenset[str], frozenset[str]]:
    non_weapons = frozenset(
        (*PRODUCTION_BASIC_CARD_KEYS, *PRODUCTION_TRICK_KEYS,
         *PRODUCTION_DELAYED_TRICK_KEYS, *PRODUCTION_ARMOR_KEYS,
         *PRODUCTION_MOUNT_KEYS)
    )
    global_complete = non_weapons | frozenset(
        key for key, status in WEAPON_SKILL_STATUS.items() if status == "COMPLETE"
    )
    # 方天画戟的多人额外目标在恰好两人时不可触发；仅 duel scope 计为充分，
    # 全局 WEAPON_SKILL_STATUS 仍保持 PARTIAL。
    duel_complete = global_complete | frozenset({"sgs_weapon_fangtianhuaji"})
    return global_complete, duel_complete


def inspect_formal_duel_readiness() -> FormalDuelReadiness:
    """从当前正式牌堆、注册表和 canonical factory 现场派生就绪状态。"""

    registry = FormalCardRegistry.from_formal_csv()
    global_complete, duel_complete = _semantic_key_sets()
    global_instances = sum(len(registry.instances_of(key)) for key in global_complete)
    duel_instances = sum(len(registry.instances_of(key)) for key in duel_complete)
    card_statuses: list[FormalDuelCardStatus] = []
    for card_key in sorted(registry.implemented_card_keys):
        global_status = "COMPLETE" if card_key in global_complete else "PARTIAL"
        duel_status = "COMPLETE"
        reason: str | None = None
        if card_key == "sgs_weapon_fangtianhuaji":
            duel_status = "NOT_APPLICABLE_TO_DUEL"
            reason = "恰好两名玩家时不存在可增加的额外目标；全局多人语义仍为PARTIAL"
        elif card_key == "sgs_weapon_cixiongshuanggujian":
            # 卡牌通用生产语义已经完整；正式模式能否提供权威参与者性别是
            # 独立 MODE_GAP，不能再把同一卡牌错误标作实现缺口。
            duel_status = "COMPLETE"
            reason = "异性目标状态机已实现；正式模式的权威角色来源由独立MODE_GAP跟踪"
        elif card_key == "sgs_weapon_zhangbashemao":
            duel_status = "RULE_SOURCE_GAP"
            reason = (
                "typed virtual-card/subcard引用基础设施已就绪；"
                "两张材料牌的区域生命周期时点尚未确认"
            )
        card_statuses.append(
            FormalDuelCardStatus(
                card_key=card_key,
                instance_count=len(registry.instances_of(card_key)),
                global_status=global_status,
                duel_status=duel_status,
                reason=reason,
            )
        )
    blockers: list[FormalDuelBlocker] = [
        FormalDuelBlocker(
            "FORMAL_DUEL_RULE_PROFILE_NOT_CONFIRMED",
            "RULE_SOURCE_GAP",
            "正式单挑牌堆适用、初始配置、先手与角色元数据尚无确认规则源",
        ),
        FormalDuelBlocker(
            "CIXIONG_CHARACTER_METADATA_SOURCE_NOT_AVAILABLE",
            "MODE_GAP",
            "雌雄双股剑通用状态机已实现，但正式单挑尚无可装配的权威参与者性别来源",
        ),
        FormalDuelBlocker(
            "VIRTUAL_CARD_SUBCARD_LIFECYCLE_RULE_GAP",
            "RULE_SOURCE_GAP",
            "丈八蛇矛两张材料进入处理区或直接弃牌的精确时点待确认",
        ),
    ]
    mode_runtime_reachable = False
    try:
        probe = FormalNoSkillDuelSession(
            seed=0,
            configuration=FormalDuelConfiguration.analysis_convention(),
            analysis_only=True,
            session_id="formal-duel-readiness-probe",
            session_secret=b"formal-duel-readiness-probe-0001",
        )
        mode_runtime_reachable = (
            probe.mode_id == FORMAL_NO_SKILL_DUEL_MODE
            and len(probe.state.cards) == 160
            and len(probe.state.players) == 2
        )
    except Exception as exc:  # pragma: no cover - 现场损坏会进入结构化阻塞
        blockers.append(
            FormalDuelBlocker(
                "FORMAL_DUEL_FACTORY_UNREACHABLE",
                "MODE_GAP",
                f"正式单挑canonical factory现场自检失败：{type(exc).__name__}:{exc}",
            )
        )
    if not mode_runtime_reachable:
        blockers.append(
            FormalDuelBlocker(
                "FORMAL_DUEL_RUNTIME_NOT_REACHABLE",
                "MODE_GAP",
                "正式单挑模式不能从canonical factory到达统一生产核心",
            )
        )

    registered_keys = frozenset(registry.implemented_card_keys)
    deck_keys = frozenset(record.card_key for record in registry.records)
    all_cards_implemented = (
        len(registry.records) == 160
        and len(deck_keys) == 38
        and registered_keys == deck_keys
        and all(
            item.duel_status in {"COMPLETE", "NOT_APPLICABLE_TO_DUEL"}
            for item in card_statuses
        )
    )
    # 当前卡牌语义仍缺丈八；雌雄通用状态机已完成但正式角色来源作为
    # 独立MODE_GAP保留，方天仅在duel scope经不可触发证明计入。
    # mode_implemented 由现场 blocker 派生，而不是由调用方或静态 manifest
    # 提交；规则 profile/角色装配尚未关闭时必须保持 false。
    mode_implemented = mode_runtime_reachable and not any(
        item.code
        in {
            "FORMAL_DUEL_RULE_PROFILE_NOT_CONFIRMED",
            "CIXIONG_CHARACTER_METADATA_SOURCE_NOT_AVAILABLE",
        }
        for item in blockers
    )
    # 该能力只指 analysis-only formal 会话接入了现有逐步规则重执行；并不
    # 表示规则源、卡牌语义或正式结果门禁已经通过。
    from .production_replay import (
        record_reference_formal_duel,
        reexecute_production_replay,
    )

    replay_supported = callable(record_reference_formal_duel) and callable(
        reexecute_production_replay
    )
    unsupported_rules = sum(
        item.code
        in {
            "FORMAL_DUEL_RULE_PROFILE_NOT_CONFIRMED",
            "VIRTUAL_CARD_SUBCARD_LIFECYCLE_RULE_GAP",
        }
        for item in blockers
    )
    # 只有 canonical 正式配置、卡牌语义和规则缺口全部关闭后，正式 runner
    # 逐个严格重执行固定 seeds 0..99 的现场结果才能填写这些字段。当前
    # analysis-only 诊断不得冒充验收，因此精确保持 0/false。
    acceptance_seed_results: tuple[FormalDuelSeedResult, ...] = ()
    acceptance_seed_count = len(acceptance_seed_results)
    acceptance_natural_end_count = sum(
        item.natural_end for item in acceptance_seed_results
    )
    acceptance_failure_count = sum(
        not (
            item.natural_end
            and item.formal_result_eligible
            and item.reexecution_verified
            and item.winner in {"p1", "p2"}
            and item.deck_count == 160
            and item.unsupported_rules == 0
            and item.approximation_count == 0
            and not item.safety_cap_triggered
            and item.exception_type is None
        )
        for item in acceptance_seed_results
    )
    fixed_seed_acceptance_passed = (
        tuple(item.seed for item in acceptance_seed_results) == tuple(range(100))
        and acceptance_natural_end_count == 100
        and acceptance_failure_count == 0
    )
    ready = (
        mode_runtime_reachable
        and mode_implemented
        and all_cards_implemented
        and replay_supported
        and unsupported_rules == 0
        and fixed_seed_acceptance_passed
        and acceptance_seed_count >= 100
        and acceptance_natural_end_count == acceptance_seed_count
        and acceptance_failure_count == 0
        and len(acceptance_seed_results) == 100
        and not blockers
    )
    return FormalDuelReadiness(
        mode_id=FORMAL_NO_SKILL_DUEL_MODE,
        deck_count=registry.card_count,
        registered_card_key_count=len(registered_keys),
        registered_instance_count=len(registry.records),
        global_complete_card_key_count=len(global_complete),
        global_complete_instance_count=global_instances,
        duel_complete_card_key_count=len(duel_complete),
        duel_complete_instance_count=duel_instances,
        global_card_semantics_complete=(global_complete == deck_keys),
        all_cards_implemented=all_cards_implemented,
        mode_runtime_reachable=mode_runtime_reachable,
        mode_implemented=mode_implemented,
        deterministic_controller_implemented=True,
        reexecution_replay_supported=replay_supported,
        unsupported_rules=unsupported_rules,
        approximation_count=0,
        acceptance_seed_count=acceptance_seed_count,
        acceptance_natural_end_count=acceptance_natural_end_count,
        acceptance_failure_count=acceptance_failure_count,
        fixed_seed_acceptance_passed=fixed_seed_acceptance_passed,
        formal_duel_no_skill_ready=ready,
        blockers=tuple(blockers),
        card_semantic_statuses=tuple(card_statuses),
        acceptance_seed_results=acceptance_seed_results,
    )


@dataclass(frozen=True, slots=True)
class FormalDuelSeedResult:
    seed: int
    deck_count: int
    winner: str | None
    action_count: int
    turn_count: int
    draw_pile_count: int
    reshuffle_count: int
    unsupported_rules: int
    approximation_count: int
    safety_cap_triggered: bool
    exception_type: str | None
    exception_message: str | None
    reached_card_keys: tuple[str, ...]
    natural_end: bool
    formal_result_eligible: bool
    reexecution_verified: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "seed": self.seed,
            "deck_count": self.deck_count,
            "winner": self.winner,
            "action_count": self.action_count,
            "turn_count": self.turn_count,
            "draw_pile_count": self.draw_pile_count,
            "reshuffle_count": self.reshuffle_count,
            "unsupported_rules": self.unsupported_rules,
            "approximation_count": self.approximation_count,
            "safety_cap_triggered": self.safety_cap_triggered,
            "exception_type": self.exception_type,
            "exception_message": self.exception_message,
            "reached_card_keys": list(self.reached_card_keys),
            "natural_end": self.natural_end,
            "formal_result_eligible": self.formal_result_eligible,
            "reexecution_verified": self.reexecution_verified,
        }


def _reshuffle_count(events: Sequence[object]) -> int:
    count = 0
    previous = False
    for event in events:
        payload = getattr(event, "payload", {})
        current = isinstance(payload, Mapping) and payload.get("reason") == "reshuffle"
        if current and not previous:
            count += 1
        previous = current
    return count


def run_formal_duel_seed_sweep(
    seeds: Iterable[int],
    *,
    configuration: FormalDuelConfiguration,
    analysis_only: bool,
    max_steps: int = 2000,
) -> tuple[FormalDuelSeedResult, ...]:
    """逐个保留全部 seed 的结果；异常、unsupported 与上限均不重采样。"""

    prepared_seeds = tuple(seeds)
    if any(isinstance(seed, bool) or not isinstance(seed, int) for seed in prepared_seeds):
        raise TypeError("seed集合中的每一项都必须是整数")
    if len(prepared_seeds) != len(set(prepared_seeds)):
        raise ValueError("seed集合不能重复；禁止以重复样本替代失败seed")
    if isinstance(max_steps, bool) or not isinstance(max_steps, int) or max_steps < 1:
        raise ValueError("安全动作上限必须是正整数")
    results: list[FormalDuelSeedResult] = []
    for seed in prepared_seeds:
        game: FormalNoSkillDuelSession | None = None
        reached: set[str] = set()
        exception: Exception | None = None
        try:
            game = FormalNoSkillDuelSession(
                seed=seed,
                configuration=configuration,
                analysis_only=analysis_only,
            )
            controller = FormalDuelReferenceController()
            while not game.is_finished:
                if game.step_count >= max_steps:
                    raise ProductionBatchSafetyLimitError(
                        f"正式单挑在{max_steps}个动作后仍未自然结束"
                    )
                action = game.step(controller)
                card_key = action.payload.get("card_key")
                if isinstance(card_key, str) and card_key:
                    reached.add(card_key)
        except Exception as exc:  # 每个失败seed必须原位记录，不得删除重采样
            exception = exc
        profile_unsupported = not configuration.source_confirmed
        runtime_unsupported = isinstance(exception, UnsupportedRuleError)
        safety_cap = isinstance(exception, ProductionBatchSafetyLimitError)
        results.append(
            FormalDuelSeedResult(
                seed=seed,
                deck_count=0 if game is None else len(game.state.cards),
                winner=None if game is None else game.winner_id,
                action_count=0 if game is None else game.step_count,
                turn_count=0 if game is None else game.runtime.turn_number,
                draw_pile_count=(
                    0
                    if game is None
                    else len(game.state.card_ids_in(DRAW_PILE))
                ),
                reshuffle_count=(
                    0 if game is None else _reshuffle_count(game.events)
                ),
                unsupported_rules=(
                    (1 if profile_unsupported else 0)
                    + (1 if runtime_unsupported else 0)
                ),
                # analysis-only 未确认配置是诊断约定，不得在逐seed记录里
                # 冒充零近似；将整个未确认 profile 计为一项显式近似。
                approximation_count=0 if configuration.source_confirmed else 1,
                safety_cap_triggered=safety_cap,
                exception_type=None if exception is None else type(exception).__name__,
                exception_message=None if exception is None else str(exception),
                reached_card_keys=tuple(sorted(reached)),
                natural_end=(
                    game is not None and game.is_finished and exception is None
                ),
                formal_result_eligible=(
                    False if game is None else game.formal_result_eligible
                ),
                reexecution_verified=False,
            )
        )
    return tuple(results)


__all__ = [
    "ALLOWED_RULE_STATUS",
    "FormalDuelBlocker",
    "FormalDuelCardStatus",
    "FormalDuelConfiguration",
    "FormalDuelConfigurationError",
    "FormalDuelReadiness",
    "FormalDuelReferenceController",
    "FormalDuelSeedResult",
    "FormalNoSkillDuelSession",
    "inspect_formal_duel_readiness",
    "run_formal_duel_seed_sweep",
]
