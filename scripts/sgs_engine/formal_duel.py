"""正式160张无技能单挑的生产模式薄层与现场就绪检查。

本模块不复制 ``GameState``、事件、动作、响应、伤害、距离、随机或回放
语义。``FormalNoSkillDuelSession`` 直接复用 ``ProductionBasicCardBatch``
的同一权威核心，只替换模式 ID，并把模式配置与角色元数据显式绑定到初始
状态。当前 Knowledge 尚未确认正式单挑配置，因此正式入口保持失败关闭；
``analysis_convention`` 只供开发诊断，绝不能标记为正式结果。
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from .actions import ActionContext, ActionType, LegalAction, UnsupportedRuleError
from .model import DRAW_PILE, CharacterGender, CharacterMetadata
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
# USER_CONFIRMED_PROJECT_FORMAL_PROFILE（2026-08-09 用户确认）已关闭正式
# 单挑 profile 与角色来源缺口；丈八蛇矛材料生命周期（USER_CONFIRMED_RULE，
# HAND→PROCESSING→DISCARD）已关闭 VIRTUAL_CARD_SUBCARD_LIFECYCLE_RULE_GAP；
# 雌雄双股剑在 formal duel 中由士兵的 effective gender=NONE 权威提供
# （无性别不构成“异性”）。正式执行哨兵因此释放；formal_duel_no_skill_ready
# 仍由 inspect_formal_duel_readiness 依据 100-seed 固定验收现场派生，不由
# 任何调用方配置覆写。
_FORMAL_EXECUTION_RELEASED = True

_ACCEPTANCE_ARTIFACT = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "FORMAL_MILESTONE_B_100_SEED_ACCEPTANCE.json"
)


class FormalDuelConfigurationError(ValueError):
    """正式单挑配置缺失、越界或没有足够规则来源。"""


def _nonempty(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise FormalDuelConfigurationError(f"{label}必须是非空字符串")
    return value.strip()


def _plain_config_value(value: object) -> object:
    """把配置对象规范化为纯 JSON 值（用于 canonical 深比较）。"""

    if isinstance(value, Mapping):
        return {
            str(key): _plain_config_value(item) for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_plain_config_value(item) for item in value]
    return value


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

    ``source_confirmed`` 只能由项目 canonical trusted factory
    （``formal_profile()``）或 ``from_canonical_profile_value()`` 授予；
    普通 ``from_dict`` 反序列化的配置即使数值与 canonical 完全相同，也
    只能作为 analysis/untrusted 配置，不能自行获得“规则来源已确认”的
    证明标签（MB-M-005）。
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
    # 内部可信来源令牌：只有 canonical trusted factory 能把它设为 True。
    # 它不是规则字段，不进入 to_dict；普通反序列化恒为 False。
    _trusted_provenance: bool = False

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
        if not isinstance(self._trusted_provenance, bool):
            raise FormalDuelConfigurationError("内部可信来源令牌必须是布尔值")

    @property
    def source_confirmed(self) -> bool:
        return (
            self._trusted_provenance
            and self.verification_status in _FORMAL_SOURCE_STATUSES
            and self.deck_applicable
            and all(
                item is not None
                and (
                    item.effective_gender is not None
                    or item.intrinsic_gender is not None
                )
                for item in self.participants
            )
        )

    @classmethod
    def from_canonical_profile_value(
        cls, value: Mapping[str, object]
    ) -> "FormalDuelConfiguration":
        """校验 payload 与 canonical formal profile 完全一致后返回可信配置。

    replay／strict reexecute 加载正式记录时验证的是 canonical profile
    内容本身（逐字段深比较），而不是让 payload 自行获得 trusted
    provenance（MB-M-005）。任何字段缺失、多余或数值不同都失败关闭。
        """

        canonical = cls.formal_profile()
        canonical_value = canonical.to_dict()
        if _plain_config_value(value) != canonical_value:
            raise FormalDuelConfigurationError(
                "正式单挑配置必须与项目 canonical formal profile 完全一致；"
                "payload 不能自行获得可信规则来源"
            )
        return canonical

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

    @classmethod
    def formal_profile(cls) -> "FormalDuelConfiguration":
        """当前项目正式无技能单挑 profile（USER_CONFIRMED_PROJECT_FORMAL_PROFILE，2026-08-09）。

        模式：formal 2-player no-skill duel。参与者为 p1/p2 两名固定无技能
        占位角色“士兵”（character_key="soldier"）；双方 max_hp=4、
        initial_hp=4、初始手牌4张；先手由项目唯一 DeterministicRNG 在
        p1/p2 中决定（不使用 Python random／系统时间／另一随机源）；首
        回合正常执行完整回合规则、DRAW 阶段正常摸2张（无首回合少摸/
        跳摸/补正）；手气卡禁用/不存在；无武将技能；无身份/主公技；无
        模式奖励/击杀奖励；正式权威160张牌堆；一方死亡且无法被合法救援
        后另一方立即获胜，game over 后不得继续启动新回合或接受动作。
        士兵 effective gender=NONE（GENDERLESS，USER_CONFIRMED_RULE
        2026-08-09）：雌雄双股剑不会因双方“异性”而发动。
        """

        return cls(
            platform="三国杀移动版",
            version="2026-07-25牌堆快照",
            source_location=(
                "USER_CONFIRMED_PROJECT_FORMAL_PROFILE"
                "（2026-08-09 用户确认）"
            ),
            verification_status="当前确认",
            deck_applicable=True,
            initial_hand_count=4,
            player_hp=(4, 4),
            player_max_hp=(4, 4),
            first_player_policy="deterministic_rng",
            participants=(
                CharacterMetadata(
                    "soldier",
                    CharacterGender.NONE,
                    CharacterGender.NONE,
                ),
                CharacterMetadata(
                    "soldier",
                    CharacterGender.NONE,
                    CharacterGender.NONE,
                ),
            ),
            _trusted_provenance=True,
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
                    "intrinsic_gender": (
                        None
                        if item.intrinsic_gender is None
                        else item.intrinsic_gender.value
                    ),
                    "effective_gender": (
                        None
                        if item.effective_gender is None
                        else item.effective_gender.value
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
                if participant_fields != {
                    "character_key",
                    "intrinsic_gender",
                    "effective_gender",
                }:
                    missing = sorted(
                        {
                            "character_key",
                            "intrinsic_gender",
                            "effective_gender",
                        }
                        - participant_fields
                    )
                    extra = sorted(
                        participant_fields
                        - {
                            "character_key",
                            "intrinsic_gender",
                            "effective_gender",
                        }
                    )
                    raise FormalDuelConfigurationError(
                        "参战角色元数据字段必须精确匹配schema："
                        f"missing={missing}，extra={extra}"
                    )
                participants.append(
                    CharacterMetadata(
                        character_key=item.get("character_key"),  # type: ignore[arg-type]
                        intrinsic_gender=item.get("intrinsic_gender"),  # type: ignore[arg-type]
                        effective_gender=item.get("effective_gender"),  # type: ignore[arg-type]
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
        if (
            configuration.source_confirmed
            and not analysis_only
            and configuration != FormalDuelConfiguration.formal_profile()
        ):
            # 正式结果只能由项目 canonical formal profile 产生；调用方
            # 自行构造的“当前确认”配置不能自我授权正式结果。
            raise FormalDuelConfigurationError(
                "正式单挑结果只接受项目 canonical formal profile；"
                "调用方配置不能自我授权"
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
    # MB-B-004：卡牌实现状态必须分层。duel_scope_all_cards_sufficient
    # 只证明“严格两人无技能单挑范围”所需卡牌语义充分；global_all_cards_
    # implemented 表示全局完整引擎，任何机器消费者不得把前者误读为后者。
    duel_scope_all_cards_sufficient: bool
    global_all_cards_implemented: bool
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
            "duel_scope_all_cards_sufficient": (
                self.duel_scope_all_cards_sufficient
            ),
            "global_all_cards_implemented": (
                self.global_all_cards_implemented
            ),
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
            # 卡牌通用生产语义已经完整；formal soldier profile 提供
            # effective gender=NONE 的权威参与者性别（NONE 不构成“异性”），
            # 不再是模式缺口。
            duel_status = "COMPLETE"
            reason = "异性目标状态机已实现；formal profile 参与者为无性别士兵（NONE）"
        elif card_key == "sgs_weapon_zhangbashemao":
            duel_status = "COMPLETE"
            reason = (
                "USER_CONFIRMED_RULE（2026-08-09）：材料 HAND→PROCESSING→"
                "DISCARD 生命周期已确认并实现；VIRTUAL_CARD_SUBCARD_"
                "LIFECYCLE_RULE_GAP 已关闭"
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
    # USER_CONFIRMED_PROJECT_FORMAL_PROFILE（2026-08-09）关闭正式 profile
    # 与参与者角色/性别来源缺口；USER_CONFIRMED_RULE（2026-08-09）关闭
    # 丈八材料生命周期缺口；雌雄在 formal duel 由士兵 NONE 性别权威提供。
    # 方天画戟多人/多目标语义仍为全局 PARTIAL，但严格两人 duel 中额外
    # 多目标不可触发（NOT_APPLICABLE_TO_DUEL），不构成 formal duel blocker。
    blockers: list[FormalDuelBlocker] = []
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
    duel_scope_all_cards_sufficient = (
        len(registry.records) == 160
        and len(deck_keys) == 38
        and registered_keys == deck_keys
        and all(
            item.duel_status in {"COMPLETE", "NOT_APPLICABLE_TO_DUEL"}
            for item in card_statuses
        )
    )
    global_all_cards_implemented = (
        len(registry.records) == 160
        and global_complete == deck_keys
        and global_instances == len(registry.records)
        and all(
            item.global_status in {"COMPLETE"}
            for item in card_statuses
        )
    )
    # formal profile（USER_CONFIRMED_PROJECT_FORMAL_PROFILE）与丈八材料
    # 生命周期（USER_CONFIRMED_RULE）均已关闭；mode_implemented 由现场
    # blocker 派生，而不是由调用方或静态 manifest 提交。
    mode_implemented = mode_runtime_reachable and not blockers
    # 该能力只指 analysis-only formal 会话接入了现有逐步规则重执行；并不
    # 表示规则源、卡牌语义或正式结果门禁已经通过。
    from .production_replay import (
        record_reference_formal_duel,
        reexecute_production_replay,
    )

    replay_supported = callable(record_reference_formal_duel) and callable(
        reexecute_production_replay
    )
    unsupported_rules = 0
    # 正式 runner 逐个严格重执行固定 seeds 0..99 的现场结果由正式验收
    # artifact 现场加载（_load_acceptance_evidence，fail-closed）；缺失、
    # 损坏或含失败 seed 时保持空，analysis-only 诊断不得冒充验收。
    acceptance_seed_results: tuple[FormalDuelSeedResult, ...] = (
        _load_acceptance_evidence()
    )
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
        and duel_scope_all_cards_sufficient
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
        duel_scope_all_cards_sufficient=duel_scope_all_cards_sufficient,
        global_all_cards_implemented=global_all_cards_implemented,
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
    final_state_hash: str | None = None

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
            "final_state_hash": self.final_state_hash,
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


_ACCEPTANCE_SCHEMA = "FORMAL_MILESTONE_B_100_SEED_ACCEPTANCE_v2"
_CANONICAL_ACCEPTANCE_MAX_STEPS = 2000
_ARTIFACT_TOP_FIELDS = frozenset(
    {
        "schema",
        "rule_source",
        "mode",
        "seeds",
        "seed_count",
        "natural_end_count",
        "reexecution_verified_count",
        "failure_count",
        "passed",
        "elapsed_seconds",
        "analysis_only",
        "max_steps",
        "canonical_formal_profile",
        "implementation_identity",
        "rules_profile_identity",
        "deck_identity",
        "seeds_detail",
        "failures",
        "note",
    }
)
_SEED_DETAIL_FIELDS = frozenset(
    {
        "seed",
        "winner",
        "action_count",
        "turn_count",
        "reshuffle_count",
        "unsupported_rules",
        "approximation_count",
        "strict_reexecution",
        "final_state_hash",
        "natural_end",
        "passed",
    }
)
_SHA256_HEX = frozenset("0123456789abcdef")


def _is_sha256_hex(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(char in _SHA256_HEX for char in value)
    )


def _implementation_source_files() -> tuple[Path, ...]:
    """返回构成当前正式实现身份的全部源码文件（按仓库相对路径排序）。"""

    root = Path(__file__).resolve().parents[2]
    engine_dir = root / "scripts" / "sgs_engine"
    files = list(engine_dir.rglob("*.py"))
    files.extend(
        (
            root / "scripts" / "sgs_engine_gate.py",
            root / "scripts" / "sgs_formal_runner.py",
            root / "scripts" / "sgs_formal_milestone_b_acceptance.py",
        )
    )
    return tuple(sorted({path.resolve(strict=False) for path in files}, key=str))


def implementation_identity() -> str:
    """当前实现身份：核心引擎/门禁/正式入口源码的确定性 SHA-256。"""

    entries: list[str] = []
    root = Path(__file__).resolve().parents[2]
    for path in _implementation_source_files():
        if not path.is_file():
            raise FormalDuelConfigurationError(
                f"实现身份所需源码文件缺失：{path}"
            )
        relative = path.relative_to(root).as_posix()
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        entries.append(f"{relative}:{digest}")
    return hashlib.sha256(
        "\n".join(entries).encode("utf-8")
    ).hexdigest()


def rules_profile_identity() -> str:
    """canonical formal profile 的确定性身份。"""

    import json

    encoded = json.dumps(
        FormalDuelConfiguration.formal_profile().to_dict(),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def deck_identity() -> str:
    """正式 160 张牌堆 CSV 的确定性身份。"""

    deck = (
        Path(__file__).resolve().parents[2]
        / "knowledge"
        / "三国杀牌堆数据.csv"
    )
    return hashlib.sha256(deck.read_bytes()).hexdigest()


def _seed_ok(result: FormalDuelSeedResult) -> tuple[bool, str]:
    """逐 seed 正式验收资格检查（与 acceptance 脚本共用）。"""

    required = (
        result.natural_end
        and result.formal_result_eligible
        and result.reexecution_verified
        and result.winner in {"p1", "p2"}
        and result.deck_count == 160
        and result.unsupported_rules == 0
        and result.approximation_count == 0
        and not result.safety_cap_triggered
        and result.exception_type is None
        and _is_sha256_hex(result.final_state_hash)
    )
    if required:
        return True, ""
    problems: list[str] = []
    if not result.natural_end:
        problems.append("not_natural_end")
    if not result.formal_result_eligible:
        problems.append("formal_result_not_eligible")
    if not result.reexecution_verified:
        problems.append("reexecution_not_verified")
    if result.winner not in {"p1", "p2"}:
        problems.append("winner_missing")
    if result.deck_count != 160:
        problems.append("deck_count")
    if result.unsupported_rules != 0:
        problems.append("unsupported_rules")
    if result.approximation_count != 0:
        problems.append("approximation_count")
    if result.safety_cap_triggered:
        problems.append("safety_cap")
    if result.exception_type is not None:
        problems.append(f"exception:{result.exception_type}")
    if not _is_sha256_hex(result.final_state_hash):
        problems.append("final_state_hash_invalid")
    return False, ",".join(problems)


def build_formal_acceptance_artifact(
    results: Sequence[FormalDuelSeedResult],
    *,
    elapsed_seconds: float | None = None,
) -> dict[str, object]:
    """把现场执行的逐 seed 结果构造成带完整 provenance 的正式验收 artifact。

    artifact 必须绑定当前实现身份、canonical rules/profile 身份、牌堆身份、
    精确 seeds 0..99、seed_count=100、analysis_only=false、max_steps 与
    逐 seed winner/action_count/natural_end/unsupported/approximation/
    strict replay/final_state_hash。任何字段缺失都会使 gate 现场加载
    fail-closed（MB-B-001）。
    """

    prepared = tuple(results)
    if len(prepared) != 100 or tuple(
        item.seed for item in prepared
    ) != tuple(range(100)):
        raise FormalDuelConfigurationError(
            "正式验收 artifact 必须包含精确 seeds 0..99 的 100 条结果"
        )
    seed_records: list[dict[str, object]] = []
    failures: list[dict[str, object]] = []
    for result in prepared:
        ok, reason = _seed_ok(result)
        seed_records.append(
            {
                "seed": result.seed,
                "winner": result.winner,
                "action_count": result.action_count,
                "turn_count": result.turn_count,
                "reshuffle_count": result.reshuffle_count,
                "unsupported_rules": result.unsupported_rules,
                "approximation_count": result.approximation_count,
                "strict_reexecution": result.reexecution_verified,
                "final_state_hash": result.final_state_hash,
                "natural_end": result.natural_end,
                "passed": ok,
            }
        )
        if not ok:
            failures.append({"seed": result.seed, "reason": reason})
    return {
        "schema": _ACCEPTANCE_SCHEMA,
        "rule_source": (
            "USER_CONFIRMED_PROJECT_FORMAL_PROFILE（2026-08-09）"
        ),
        "mode": FORMAL_NO_SKILL_DUEL_MODE,
        "seeds": list(range(100)),
        "seed_count": len(prepared),
        "natural_end_count": sum(1 for item in prepared if item.natural_end),
        "reexecution_verified_count": sum(
            1 for item in prepared if item.reexecution_verified
        ),
        "failure_count": len(failures),
        "passed": len(failures) == 0 and len(prepared) == 100,
        "elapsed_seconds": round(elapsed_seconds, 2)
        if elapsed_seconds is not None
        else None,
        "analysis_only": False,
        "max_steps": _CANONICAL_ACCEPTANCE_MAX_STEPS,
        "canonical_formal_profile": (
            FormalDuelConfiguration.formal_profile().to_dict()
        ),
        "implementation_identity": implementation_identity(),
        "rules_profile_identity": rules_profile_identity(),
        "deck_identity": deck_identity(),
        "seeds_detail": seed_records,
        "failures": failures,
        "note": (
            "正式100-seed验收证据（MB-B-001 provenance v2）；每局为同一"
            "canonical formal session 现场执行并同步 record decisions，"
            "再 strict replay 同一份 record；本 artifact 只是缓存证据，"
            "gate 现场验证全部身份绑定与关键字段。"
        ),
    }


def write_formal_acceptance_artifact(
    results: Sequence[FormalDuelSeedResult],
    output_path: str | Path,
    *,
    elapsed_seconds: float | None = None,
) -> Path:
    """原子写出正式验收 artifact；任何结果不合格都拒绝写出。"""

    import json
    import os
    import tempfile

    payload = build_formal_acceptance_artifact(
        results, elapsed_seconds=elapsed_seconds
    )
    if payload["passed"] is not True:
        raise FormalDuelConfigurationError(
            "正式验收 artifact 存在失败 seed，拒绝写出"
        )
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    file_descriptor, temporary_name = tempfile.mkstemp(
        dir=target.parent,
        prefix=f".{target.name}.",
        suffix=".tmp",
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(
            file_descriptor, "w", encoding="utf-8", newline="\n"
        ) as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, target)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise
    return target


def _load_acceptance_evidence(
    artifact_path: str | Path | None = None,
) -> tuple["FormalDuelSeedResult", ...]:
    """从正式100-seed验收artifact现场加载逐seed证据；缺失/损坏保持空。

    artifact 只是缓存证据：必须与当前实现身份、canonical rules/profile
    身份、牌堆身份完全绑定，且所有关键字段严格验证（MB-B-001）。任何
    字段缺失、未知字段、非零 unsupported/approximation、非自然结束、
    失败 seed、seed 集合不精确、strict replay 缺失、final_state_hash
    非法、analysis_only=true、max_steps 不符或身份不匹配都会使本函数
    返回空（fail-closed），不允许用调用方手写 JSON 或静态布尔值授权。
    """

    import json

    target = _ACCEPTANCE_ARTIFACT if artifact_path is None else Path(
        artifact_path
    )
    if not target.exists():
        return ()
    try:
        with target.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError):
        return ()
    if not isinstance(payload, Mapping):
        return ()
    if set(payload) != _ARTIFACT_TOP_FIELDS:
        return ()
    if payload.get("schema") != _ACCEPTANCE_SCHEMA:
        return ()
    if payload.get("mode") != FORMAL_NO_SKILL_DUEL_MODE:
        return ()
    if payload.get("passed") is not True:
        return ()
    if payload.get("analysis_only") is not False:
        return ()
    if payload.get("max_steps") != _CANONICAL_ACCEPTANCE_MAX_STEPS:
        return ()
    raw_seeds = payload.get("seeds")
    if (
        not isinstance(raw_seeds, Sequence)
        or len(raw_seeds) != 100
        or tuple(raw_seeds) != tuple(range(100))
    ):
        return ()
    if payload.get("seed_count") != 100:
        return ()
    if payload.get("natural_end_count") != 100:
        return ()
    if payload.get("reexecution_verified_count") != 100:
        return ()
    if payload.get("failure_count") != 0:
        return ()
    if payload.get("failures") != []:
        return ()
    try:
        profile_value = _plain_config_value(
            payload.get("canonical_formal_profile")
        )
    except Exception:
        return ()
    if profile_value != FormalDuelConfiguration.formal_profile().to_dict():
        return ()
    for label, current in (
        ("implementation_identity", implementation_identity()),
        ("rules_profile_identity", rules_profile_identity()),
        ("deck_identity", deck_identity()),
    ):
        stored = payload.get(label)
        if not isinstance(stored, str) or stored != current:
            return ()
    raw_detail = payload.get("seeds_detail")
    if not isinstance(raw_detail, Sequence) or len(raw_detail) != 100:
        return ()
    results: list[FormalDuelSeedResult] = []
    for expected_seed, item in enumerate(raw_detail):
        if not isinstance(item, Mapping):
            return ()
        if set(item) != _SEED_DETAIL_FIELDS:
            return ()
        seed = item.get("seed")
        if isinstance(seed, bool) or not isinstance(seed, int):
            return ()
        if seed != expected_seed:
            return ()
        winner = item.get("winner")
        if winner not in {"p1", "p2"}:
            return ()
        for field in (
            "action_count",
            "turn_count",
            "reshuffle_count",
            "unsupported_rules",
            "approximation_count",
        ):
            value = item.get(field)
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or value < 0
            ):
                return ()
        if (
            item.get("action_count") == 0
            or item.get("turn_count") == 0
            or item.get("unsupported_rules") != 0
            or item.get("approximation_count") != 0
            or item.get("natural_end") is not True
            or item.get("passed") is not True
            or item.get("strict_reexecution") is not True
        ):
            return ()
        final_state_hash = item.get("final_state_hash")
        if not _is_sha256_hex(final_state_hash):
            return ()
        results.append(
            FormalDuelSeedResult(
                seed=seed,
                deck_count=160,
                winner=winner,
                action_count=item["action_count"],
                turn_count=item["turn_count"],
                draw_pile_count=0,
                reshuffle_count=item["reshuffle_count"],
                unsupported_rules=0,
                approximation_count=0,
                safety_cap_triggered=False,
                exception_type=None,
                exception_message=None,
                reached_card_keys=(),
                natural_end=True,
                formal_result_eligible=True,
                reexecution_verified=True,
                final_state_hash=final_state_hash,
            )
        )
    return tuple(results)


def run_formal_duel_seed_sweep(
    seeds: Iterable[int],
    *,
    configuration: FormalDuelConfiguration,
    analysis_only: bool,
    max_steps: int = 2000,
) -> tuple[FormalDuelSeedResult, ...]:
    """逐个保留全部 seed 的结果；异常、unsupported 与上限均不重采样。

    MB-B-003/六（acceptance 同局 record/replay）：每个 seed 只创建一个
    canonical formal session，从该同一 session 执行并同步 record
    decisions，得到 winner/action_count/final state，再 strict replay
    同一份 record 验证 final hash/RNG/event/winner。禁止新建另一随机
    session secret 的独立语义局来证明第一局。
    """

    from .production_replay import (
        ProductionReplayFormatError,
        record_reference_production_batch,
        reexecute_production_replay,
    )

    prepared_seeds = tuple(seeds)
    if any(
        isinstance(seed, bool) or not isinstance(seed, int)
        for seed in prepared_seeds
    ):
        raise TypeError("seed集合中的每一项都必须是整数")
    if len(prepared_seeds) != len(set(prepared_seeds)):
        raise ValueError("seed集合不能重复；禁止以重复样本替代失败seed")
    if (
        isinstance(max_steps, bool)
        or not isinstance(max_steps, int)
        or max_steps < 1
    ):
        raise ValueError("安全动作上限必须是正整数")
    if not analysis_only and (
        configuration != FormalDuelConfiguration.formal_profile()
    ):
        raise FormalDuelConfigurationError(
            "正式结果只接受项目 canonical formal profile；"
            "调用方配置不能自我授权"
        )
    results: list[FormalDuelSeedResult] = []
    for seed in prepared_seeds:
        game: FormalNoSkillDuelSession | None = None
        reached: set[str] = set()
        exception: Exception | None = None
        reexecution_verified = False
        final_state_hash: str | None = None
        try:
            game = FormalNoSkillDuelSession(
                seed=seed,
                configuration=configuration,
                analysis_only=analysis_only,
            )
            # 同一 session 现场执行并同步 record decisions；不另建第二局。
            record = record_reference_production_batch(
                seed,
                controller=FormalDuelReferenceController(),
                max_steps=max_steps,
                _game=game,
            )
            for decision in record.decisions:
                chosen = decision["chosen_action"]
                payload = chosen.get("payload")
                if isinstance(payload, Mapping):
                    card_key = payload.get("card_key")
                    if isinstance(card_key, str) and card_key:
                        reached.add(card_key)
            # strict replay 同一份 record：final hash/RNG/event/winner 全部一致。
            verification = reexecute_production_replay(record)
            reexecution_verified = verification.verified
            final_state_hash = record.outcome.get("final_game_state_hash")
            if not _is_sha256_hex(final_state_hash):
                raise ProductionReplayFormatError(
                    "正式单挑回放缺少合法final_game_state_hash"
                )
            game.assert_finished_state_invariants()
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
                approximation_count=(
                    0 if configuration.source_confirmed else 1
                ),
                safety_cap_triggered=safety_cap,
                exception_type=(
                    None if exception is None else type(exception).__name__
                ),
                exception_message=(
                    None if exception is None else str(exception)
                ),
                reached_card_keys=tuple(sorted(reached)),
                natural_end=(
                    game is not None
                    and game.is_finished
                    and exception is None
                ),
                formal_result_eligible=(
                    False if game is None else game.formal_result_eligible
                ),
                reexecution_verified=reexecution_verified,
                final_state_hash=final_state_hash,
            )
        )
    return tuple(results)


__all__ = [
    "_ACCEPTANCE_SCHEMA",
    "ALLOWED_RULE_STATUS",
    "build_formal_acceptance_artifact",
    "deck_identity",
    "FormalDuelBlocker",
    "FormalDuelCardStatus",
    "FormalDuelConfiguration",
    "FormalDuelConfigurationError",
    "FormalDuelReadiness",
    "FormalDuelReferenceController",
    "FormalDuelSeedResult",
    "FormalNoSkillDuelSession",
    "implementation_identity",
    "inspect_formal_duel_readiness",
    "rules_profile_identity",
    "run_formal_duel_seed_sweep",
    "write_formal_acceptance_artifact",
]
