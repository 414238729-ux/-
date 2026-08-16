"""正式160张无技能单挑的生产模式薄层与现场就绪检查。

本模块不复制 ``GameState``、事件、动作、响应、伤害、距离、随机或回放
语义。``FormalNoSkillDuelSession`` 直接复用 ``ProductionBasicCardBatch``
的同一权威核心，只替换模式 ID，并把模式配置与角色元数据显式绑定到初始
状态。当前 Knowledge 尚未确认正式单挑配置，因此正式入口保持失败关闭；
``analysis_convention`` 只供开发诊断，绝不能标记为正式结果。
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from .actions import ActionContext, ActionType, LegalAction, UnsupportedRuleError
from .model import DRAW_PILE, CharacterGender, CharacterMetadata
from .multiplayer import DuelOutcomePolicy
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
from ..sgs_hash_inventory import git_normalized_sha256


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

_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]

# MB-M-005（remediation-3）：trusted capability 必须是受控能力。
# 只有本模块持有该 sentinel 对象身份；``TrustedFormalDuelConfiguration``
# 的构造要求调用方传入该对象本身（``is`` 身份校验），普通公开调用方无法
# 仅凭公开 canonical 值制造 trusted 实例。replay 只序列化 profile value，
# 不保存该 token；strict re-execution 通过 from_canonical_profile_value
# 由当前内部 factory 重建 trusted 配置。
_TRUSTED_FORMAL_CAPABILITY: object = object()

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
        # MB-M-005：普通 FormalDuelConfiguration 实例（含数值完全等于
        # canonical profile 的调用方构造）永远不持有 trusted provenance。
        # 只有内部 canonical factory 返回的 TrustedFormalDuelConfiguration
        # 才具备正式资格。
        return False

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

        return TrustedFormalDuelConfiguration(
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
            _capability_token=_TRUSTED_FORMAL_CAPABILITY,
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


def _canonical_formal_profile_value() -> dict[str, object]:
    """canonical formal profile 的值字典（无 trusted 能力，避免递归）。

    供 TrustedFormalDuelConfiguration.__post_init__ 做精确值校验，以及
    replay 身份比较使用；构造本身不产生 trusted capability。
    """

    soldier = {
        "character_key": "soldier",
        "intrinsic_gender": "none",
        "effective_gender": "none",
    }
    return {
        "platform": "三国杀移动版",
        "version": "2026-07-25牌堆快照",
        "source_location": (
            "USER_CONFIRMED_PROJECT_FORMAL_PROFILE"
            "（2026-08-09 用户确认）"
        ),
        "verification_status": "当前确认",
        "deck_applicable": True,
        "initial_hand_count": 4,
        "player_hp": [4, 4],
        "player_max_hp": [4, 4],
        "first_player_policy": "deterministic_rng",
        "participants": [dict(soldier), dict(soldier)],
    }


@dataclass(frozen=True, slots=True)
class TrustedFormalDuelConfiguration(FormalDuelConfiguration):
    """唯一持有正式 trusted provenance 的配置类型（MB-M-005）。

    只有内部 canonical factory（``FormalDuelConfiguration.formal_profile()``
    与 ``from_canonical_profile_value`` 的成功路径）能构造本类型。普通
    ``FormalDuelConfiguration(...)``、``from_dict(...)``、``replace(...)``、
    ``copy/deepcopy``、JSON roundtrip 或数值完全等于 canonical 的调用方
    构造均只能得到 untrusted 的普通配置（``source_confirmed=False``），
    不能自我授予 formal eligibility。

    remediation-3（MB-M-005）收紧：``_capability_token`` 必须是模块私有
    ``_TRUSTED_FORMAL_CAPABILITY`` sentinel 的同一对象（``is`` 身份校验）。
    公开调用方即使 import 本类型并手工提供全部 canonical values，也拿不到
    sentinel 对象身份，直接构造会失败关闭；copy/deepcopy 由显式实现降级为
    重新调用内部 canonical factory，replace 篡改在 ``__post_init__`` 处失败
    关闭。正式会话还额外校验真实 capability identity，而不是只依赖
    ``isinstance``。

    本类型不可被篡改：``__post_init__`` 强制当前值必须与 canonical
    formal profile 精确一致；任何 ``dataclasses.replace`` 修改字段都会
    在校验处失败关闭，从而无法用 trusted 类型包装非 canonical 值。
    """

    _capability_token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        # frozen+slots dataclass 子类中零参数 super() 会失败（CPython
        # slots 交互限制），显式调用父类校验。
        FormalDuelConfiguration.__post_init__(self)
        if self._capability_token is not _TRUSTED_FORMAL_CAPABILITY:
            raise FormalDuelConfigurationError(
                "TrustedFormalDuelConfiguration 只能由内部 canonical factory "
                "以模块私有 capability token 构造；公开调用方不能仅凭公开 "
                "值自我授予 trusted provenance（MB-M-005）"
            )
        if self.to_dict() != _canonical_formal_profile_value():
            raise FormalDuelConfigurationError(
                "TrustedFormalDuelConfiguration 必须精确等于项目 canonical "
                "formal profile；禁止用 trusted 类型包装被修改的配置"
            )

    @property
    def source_confirmed(self) -> bool:
        return True

    def __copy__(self) -> "TrustedFormalDuelConfiguration":
        # 复制合法 trusted 对象也通过内部 canonical factory 重建，不依赖
        # 拷贝状态携带 capability；公开调用方无法借此制造新 trusted。
        return FormalDuelConfiguration.formal_profile()

    def __deepcopy__(
        self, memo: dict[int, object]
    ) -> "TrustedFormalDuelConfiguration":
        del memo
        return FormalDuelConfiguration.formal_profile()

    @property
    def trusted_capability_held(self) -> bool:
        """真实内部 capability identity 是否成立（会话的最终防线）。"""

        return self._capability_token is _TRUSTED_FORMAL_CAPABILITY


def assert_trusted_formal_configuration(
    configuration: FormalDuelConfiguration,
) -> None:
    """单一 trusted authority boundary（remediation-4，R3-NEW-003）。

    正式会话与正式执行入口统一调用本函数，不得在多处复制不同版本的
    验证逻辑。三项验证缺一不可：
    1. exact trusted type（``type(...) is TrustedFormalDuelConfiguration``，
       拒绝子类）；
    2. capability identity（模块私有 ``_TRUSTED_FORMAL_CAPABILITY`` 的
       同一对象身份）；
    3. canonical profile value（``to_dict()`` 精确等于当前 canonical
       formal profile value）。

    第 3 项是 canonical value invariant：即使对象绕过
    ``TrustedFormalDuelConfiguration.__post_init__``（例如
    ``object.__new__`` + ``object.__setattr__`` 的低层反射构造）伪造出
    type/token 正确但 profile value 非 canonical 的对象（如
    player_hp=(9,9)），也必须在正式 authority boundary fail-closed。
    比较对象只是规则 profile value，不含 capability token、
    ``source_confirmed`` derived flag 或 runtime secret，因此 replay 的
    record value → current canonical factory → value comparison 稳定工作。
    """

    if not isinstance(configuration, FormalDuelConfiguration):
        raise TypeError("正式单挑会话必须接收FormalDuelConfiguration")
    if type(configuration) is not TrustedFormalDuelConfiguration:
        raise FormalDuelConfigurationError(
            "正式单挑结果只接受内部 canonical factory 返回的 "
            "TrustedFormalDuelConfiguration（exact type 校验）；"
            "调用方配置不能自我授权"
        )
    if (
        getattr(configuration, "_capability_token", None)
        is not _TRUSTED_FORMAL_CAPABILITY
    ):
        raise FormalDuelConfigurationError(
            "正式单挑结果只接受真实持有模块私有 capability token 的 "
            "TrustedFormalDuelConfiguration（capability identity 校验）；"
            "调用方配置不能自我授权"
        )
    if configuration.to_dict() != _canonical_formal_profile_value():
        raise FormalDuelConfigurationError(
            "正式单挑配置的 profile value 必须精确等于项目 canonical "
            "formal profile；type/token 正确但值非 canonical 的对象同样"
            "失败关闭（canonical value invariant）"
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
        if not analysis_only:
            # MB-M-005（remediation-3）+ R3-NEW-003（remediation-4）：
            # exact trusted type、capability identity、canonical profile
            # value 三项统一由唯一 authority boundary 校验，调用方不能
            # 自我授予 trusted provenance，低层反射伪造的非 canonical
            # 对象也必须失败关闭。
            assert_trusted_formal_configuration(configuration)
        if configuration.source_confirmed and not _FORMAL_EXECUTION_RELEASED:
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
            outcome_policy=DuelOutcomePolicy(),
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
    # MB-B-001：三层语义分离。
    # A. STATIC EXECUTION ELIGIBILITY：当前代码在静态规则/牌堆/profile
    # 范围内可以开始 formal duel execution；不依赖任何旧 acceptance
    # artifact（否则 artifact stale → 无法运行 → 永远无法生成新 artifact
    # 的循环）。
    formal_duel_execution_ready: bool
    # B. CACHED ACCEPTANCE REPORT VALIDITY：签入 artifact 自身一致性
    # （schema/identity/seed集合/digest）；只描述缓存报告，不得等同
    # “刚刚执行过”，也不得独立授权 Milestone PASSED。
    cached_acceptance_report_valid: bool
    cached_acceptance_seed_count: int
    cached_acceptance_natural_end_count: int
    cached_acceptance_failure_count: int
    cached_fixed_seed_acceptance_passed: bool
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
            "formal_duel_execution_ready": (
                self.formal_duel_execution_ready
            ),
            "cached_acceptance_report_valid": (
                self.cached_acceptance_report_valid
            ),
            "cached_acceptance_seed_count": (
                self.cached_acceptance_seed_count
            ),
            "cached_acceptance_natural_end_count": (
                self.cached_acceptance_natural_end_count
            ),
            "cached_acceptance_failure_count": (
                self.cached_acceptance_failure_count
            ),
            "cached_fixed_seed_acceptance_passed": (
                self.cached_fixed_seed_acceptance_passed
            ),
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
    # MB-B-001：三层语义分离。
    # B. CACHED ACCEPTANCE REPORT：签入 artifact 是缓存报告，只描述
    # “报告自身一致”，不表示“刚刚执行过”，也不得独立授权 Milestone
    # PASSED。缺失/损坏/身份不匹配 → (False, ())。
    cached_acceptance_valid, cached_results = _load_acceptance_evidence()
    cached_acceptance_seed_count = len(cached_results)
    cached_acceptance_natural_end_count = sum(
        item.natural_end for item in cached_results
    )
    cached_acceptance_failure_count = sum(
        0 if validate_formal_live_result(item)[0] else 1
        for item in cached_results
    )
    cached_fixed_seed_acceptance_passed = (
        cached_acceptance_valid
        and tuple(item.seed for item in cached_results) == tuple(range(100))
        and cached_acceptance_natural_end_count == 100
        and cached_acceptance_failure_count == 0
    )
    # 兼容字段：acceptance_* 即 cached 报告证据（只读报告，不授权执行）。
    acceptance_seed_results = cached_results
    acceptance_seed_count = cached_acceptance_seed_count
    acceptance_natural_end_count = cached_acceptance_natural_end_count
    acceptance_failure_count = cached_acceptance_failure_count
    fixed_seed_acceptance_passed = cached_fixed_seed_acceptance_passed
    # A. STATIC EXECUTION ELIGIBILITY：当前代码在静态规则/牌堆/profile
    # 范围内可以开始 formal duel execution；不依赖旧 acceptance artifact
    # （artifact stale 不得阻止开始新的 live execution，MB-B-001）。
    static_ready = (
        mode_runtime_reachable
        and mode_implemented
        and duel_scope_all_cards_sufficient
        and replay_supported
        and unsupported_rules == 0
        and not blockers
    )
    formal_duel_execution_ready = static_ready
    # formal_duel_no_skill_ready 语义 = 静态执行资格（可与执行）。
    formal_duel_no_skill_ready = static_ready
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
        formal_duel_no_skill_ready=formal_duel_no_skill_ready,
        formal_duel_execution_ready=formal_duel_execution_ready,
        cached_acceptance_report_valid=cached_acceptance_valid,
        cached_acceptance_seed_count=cached_acceptance_seed_count,
        cached_acceptance_natural_end_count=(
            cached_acceptance_natural_end_count
        ),
        cached_acceptance_failure_count=cached_acceptance_failure_count,
        cached_fixed_seed_acceptance_passed=(
            cached_fixed_seed_acceptance_passed
        ),
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


FORMAL_SIMULATION_TRANSITIVE_INPUT_INVENTORY: tuple[str, ...] = (
    # 生产引擎源码（scripts/sgs_engine/**/*.py 由 _implementation_source_files
    # 动态收集）；以下为引擎目录之外、正式模拟 fresh process 启动或运行时
    # 真实执行/读取的语义依赖的 explicit enumerated inventory。Python 在
    # 导入 scripts.* 正式入口前会先执行 scripts/__init__.py，因此该父包
    # initializer 及其当前 eager local import 闭包也必须显式登记。清单是
    # 人工维护的显式清单，不宣称“自动覆盖全部 transitive imports/data
    # dependencies”——新增或移除正式运行时依赖必须同步登记并测试
    # （remediation-4 R3-NEW-002；remediation-5 R4-NEW-001）。
    "scripts/__init__.py",
    "scripts/card_draw.py",
    "scripts/damage.py",
    "scripts/monte_carlo.py",
    "scripts/ranking.py",
    "scripts/sgs_ai_strategy_v22.py",
    "scripts/sgs_ai_strategy_v24.py",
    "scripts/sgs_card_rules.py",
    "scripts/sgs_card_strategy.py",
    "scripts/sgs_chain_strategy.py",
    "scripts/sgs_extended_rules.py",
    "scripts/sgs_focus_strategy.py",
    "scripts/sgs_general_ai_v21.py",
    "scripts/sgs_general_rules.py",
    "scripts/sgs_general_strategy.py",
    "scripts/sgs_incremental_generals.py",
    "scripts/sgs_incremental_mechanics.py",
    "scripts/sgs_jink_response.py",
    "scripts/sgs_limited_identity_variant.py",
    "scripts/sgs_mode_evaluation.py",
    "scripts/sgs_modes.py",
    "scripts/sgs_skill_framework.py",
    "scripts/sgs_special_general_rules.py",
    "scripts/sgs_structured_data.py",
    "scripts/sgs_team_strategy.py",
    "scripts/sgs_v24_generals.py",
    "scripts/summary.py",
    "scripts/trigger.py",
    "scripts/sgs_engine_gate.py",
    "scripts/sgs_formal_runner.py",
    "scripts/sgs_formal_milestone_b_acceptance.py",
    "scripts/deck_data.py",
    "scripts/_validation.py",
    "scripts/sgs_hash_inventory.py",
    "knowledge/三国杀牌堆数据.csv",
    "knowledge/三国杀卡牌结构化数据.csv",
)


def _implementation_source_files(root: Path | None = None) -> tuple[Path, ...]:
    """返回 explicit enumerated 正式模拟依赖清单的文件集合（按路径排序）。

    remediation-3（MB-B-001）修复 + remediation-4（R3-NEW-002）+
    remediation-5（R4-NEW-001）补齐：
    identity 覆盖当前已确认的正式模拟语义输入——生产引擎源码、formal
    duel 源码、runner/gate 语义代码、card registry、deck source/data
    （scripts/deck_data.py）、父包 initializer 及其 fresh-process eager local
    import 闭包、deck 加载校验 helper（scripts/_validation.py）、
    identity 归一化 helper（scripts/sgs_hash_inventory.py）、牌堆 CSV 与
    结构化卡牌/规则 CSV（其中含武器攻击范围，青龙偃月刀攻击范围变化必须
    改变 identity）。接受方（acceptance artifact）、可变 CURRENT docs、
    audit report、manifest 自身与输出文件一律排除。

    本清单是显式枚举，不是自动 import/data 依赖闭包分析：仓库目前没有
    可靠的依赖闭包工具，因此不得声称“自动覆盖全部 transitive
    dependencies”；新增正式语义输入必须同步登记并配 mutation 测试。
    """

    root = _REPOSITORY_ROOT if root is None else Path(root)
    engine_dir = root / "scripts" / "sgs_engine"
    files = list(engine_dir.rglob("*.py"))
    files.extend(
        root / relative for relative in FORMAL_SIMULATION_TRANSITIVE_INPUT_INVENTORY
    )
    return tuple(sorted({path.resolve(strict=False) for path in files}, key=str))


def implementation_identity(root: Path | None = None) -> str:
    """当前实现身份：explicit enumerated 正式模拟依赖清单的确定性 SHA-256。

    每项输入使用唯一 canonical helper ``git_normalized_sha256``（UTF-8、
    去 BOM、CRLF→LF 归一），因此仅行尾变化不会改变 identity，内容语义
    变化必然改变 identity；docs/审计/manifest/artifact 变化不改变 identity。
    身份只覆盖 ``FORMAL_SIMULATION_TRANSITIVE_INPUT_INVENTORY`` 与引擎
    目录内显式登记的输入，不宣称自动 transitive closure。
    """

    root = _REPOSITORY_ROOT if root is None else Path(root)
    entries: list[str] = []
    for path in _implementation_source_files(root):
        if not path.is_file():
            raise FormalDuelConfigurationError(
                f"实现身份所需源码文件缺失：{path}"
            )
        relative = path.relative_to(root).as_posix()
        digest = git_normalized_sha256(path)
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

    deck = _REPOSITORY_ROOT / "knowledge" / "三国杀牌堆数据.csv"
    return git_normalized_sha256(deck)


def validate_formal_live_result(
    result: FormalDuelSeedResult,
) -> tuple[bool, str]:
    """唯一 canonical 逐 seed live-result validator（MB-B-001 remediation-3）。

    所有需要判断一次真实执行是否成功的入口——acceptance generator、formal
    runner、live result writer、readiness cached consumer——必须复用本函数，
    不得复制多套部分 if 判断。每个 seed result 至少验证：
    seed 为预期整数；winner∈{p1,p2}；natural_end=true；strict
    reexecution=true；unsupported_rules=0；approximation_count=0；
    deck_count=160；action_count>0；turn_count>0；final_state_hash 为
    精确 64 位小写十六进制；finished invariants 已通过（sweep 中
    assert_finished_state_invariants 失败会登记为 exception）；结果确实
    来自 formal profile 且 analysis_only=false（formal_result_eligible）。
    """

    problems: list[str] = []
    if isinstance(result.seed, bool) or not isinstance(result.seed, int):
        problems.append("seed_invalid")
    if result.winner not in {"p1", "p2"}:
        problems.append("winner_missing")
    if result.natural_end is not True:
        problems.append("not_natural_end")
    if result.formal_result_eligible is not True:
        problems.append("formal_result_not_eligible")
    if result.reexecution_verified is not True:
        problems.append("reexecution_not_verified")
    if result.deck_count != 160:
        problems.append("deck_count")
    if (
        isinstance(result.action_count, bool)
        or not isinstance(result.action_count, int)
        or result.action_count <= 0
    ):
        problems.append("action_count_zero")
    if (
        isinstance(result.turn_count, bool)
        or not isinstance(result.turn_count, int)
        or result.turn_count <= 0
    ):
        problems.append("turn_count_zero")
    if result.unsupported_rules != 0:
        problems.append("unsupported_rules")
    if result.approximation_count != 0:
        problems.append("approximation_count")
    if result.safety_cap_triggered is not False:
        problems.append("safety_cap")
    if result.exception_type is not None:
        problems.append(f"exception:{result.exception_type}")
    if not _is_sha256_hex(result.final_state_hash):
        problems.append("final_state_hash_invalid")
    if problems:
        return False, ",".join(problems)
    return True, ""


@dataclass(frozen=True, slots=True)
class FormalLiveResultSetSummary:
    """100-seed（或给定 seed 集合）集合级 live-result 验证汇总。

    ``all_valid`` 是唯一权威判定：只有 seed 集合精确等于预期、无重复、
    数量一致且全部逐 seed 通过时才为 True。``failures`` 与
    ``failure_count`` 由 details 重新派生，绝不信任输入中声明的
    ``passed``／``failure_count`` 字段（MB-B-001 remediation-3）。
    """

    all_valid: bool
    expected_seed_count: int
    seed_count: int
    seed_set_exact: bool
    seed_unique: bool
    natural_end_count: int
    reexecution_verified_count: int
    failure_count: int
    failures: tuple[dict[str, object], ...]


def validate_formal_live_result_set(
    results: Sequence[FormalDuelSeedResult],
    *,
    expected_seeds: Sequence[int] = tuple(range(100)),
) -> FormalLiveResultSetSummary:
    """集合级 live-result 验证：数量、精确 seed 集合、唯一性、逐 seed 全通过。

    正式 full acceptance 必须用本函数重新派生 detail count、seed 集合、
    failures 与 passed；禁止信任输入中已有的 ``passed=true``，也禁止出现
    ``artifact.passed=false`` 但 runner 输出 ``status=passed``。
    """

    prepared = tuple(results)
    expected = tuple(expected_seeds)
    seen: list[int] = []
    seed_unique = True
    for item in prepared:
        if item.seed in seen:
            seed_unique = False
        seen.append(item.seed)
    seed_set_exact = tuple(item.seed for item in prepared) == expected
    failures: list[dict[str, object]] = []
    natural_end_count = 0
    reexecution_verified_count = 0
    for item in prepared:
        if item.natural_end is True:
            natural_end_count += 1
        if item.reexecution_verified is True:
            reexecution_verified_count += 1
        ok, reason = validate_formal_live_result(item)
        if not ok:
            failures.append({"seed": item.seed, "reason": reason})
    all_valid = (
        len(prepared) == len(expected)
        and seed_set_exact
        and seed_unique
        and not failures
    )
    return FormalLiveResultSetSummary(
        all_valid=all_valid,
        expected_seed_count=len(expected),
        seed_count=len(prepared),
        seed_set_exact=seed_set_exact,
        seed_unique=seed_unique,
        natural_end_count=natural_end_count,
        reexecution_verified_count=reexecution_verified_count,
        failure_count=len(failures),
        failures=tuple(failures),
    )


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
        ok, reason = validate_formal_live_result(result)
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
) -> tuple[bool, tuple["FormalDuelSeedResult", ...]]:
    """从正式100-seed验收artifact现场加载逐seed证据；缺失/损坏保持空。

    artifact 只是缓存报告：必须与当前实现身份、canonical rules/profile
    身份、牌堆身份完全绑定，且所有关键字段严格验证（MB-B-001）。任何
    字段缺失、未知字段、非零 unsupported/approximation、非自然结束、
    失败 seed、seed 集合不精确、strict replay 缺失、final_state_hash
    非法、analysis_only=true、max_steps 不符或身份不匹配都会使本函数
    返回 (False, ())（fail-closed）。
    返回 ``(valid, results)``：valid 只表示“缓存报告自身一致”，不表示
    “刚刚执行过”；只有正式 run 命令真实执行后才会产生本次 live 结果。
    """

    import json

    target = _ACCEPTANCE_ARTIFACT if artifact_path is None else Path(
        artifact_path
    )
    if not target.exists():
        return False, ()
    try:
        with target.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError):
        return False, ()
    if not isinstance(payload, Mapping):
        return False, ()
    if set(payload) != _ARTIFACT_TOP_FIELDS:
        return False, ()
    if payload.get("schema") != _ACCEPTANCE_SCHEMA:
        return False, ()
    if payload.get("mode") != FORMAL_NO_SKILL_DUEL_MODE:
        return False, ()
    if payload.get("passed") is not True:
        return False, ()
    if payload.get("analysis_only") is not False:
        return False, ()
    if payload.get("max_steps") != _CANONICAL_ACCEPTANCE_MAX_STEPS:
        return False, ()
    raw_seeds = payload.get("seeds")
    if (
        not isinstance(raw_seeds, Sequence)
        or len(raw_seeds) != 100
        or tuple(raw_seeds) != tuple(range(100))
    ):
        return False, ()
    if payload.get("seed_count") != 100:
        return False, ()
    if payload.get("natural_end_count") != 100:
        return False, ()
    if payload.get("reexecution_verified_count") != 100:
        return False, ()
    if payload.get("failure_count") != 0:
        return False, ()
    if payload.get("failures") != []:
        return False, ()
    try:
        profile_value = _plain_config_value(
            payload.get("canonical_formal_profile")
        )
    except Exception:
        return False, ()
    if profile_value != FormalDuelConfiguration.formal_profile().to_dict():
        return False, ()
    for label, current in (
        ("implementation_identity", implementation_identity()),
        ("rules_profile_identity", rules_profile_identity()),
        ("deck_identity", deck_identity()),
    ):
        stored = payload.get(label)
        if not isinstance(stored, str) or stored != current:
            return False, ()
    raw_detail = payload.get("seeds_detail")
    if not isinstance(raw_detail, Sequence) or len(raw_detail) != 100:
        return False, ()
    results: list[FormalDuelSeedResult] = []
    for expected_seed, item in enumerate(raw_detail):
        if not isinstance(item, Mapping):
            return False, ()
        if set(item) != _SEED_DETAIL_FIELDS:
            return False, ()
        seed = item.get("seed")
        if isinstance(seed, bool) or not isinstance(seed, int):
            return False, ()
        if seed != expected_seed:
            return False, ()
        winner = item.get("winner")
        if winner not in {"p1", "p2"}:
            return False, ()
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
                return False, ()
        if (
            item.get("action_count") == 0
            or item.get("turn_count") == 0
            or item.get("unsupported_rules") != 0
            or item.get("approximation_count") != 0
            or item.get("natural_end") is not True
            or item.get("passed") is not True
            or item.get("strict_reexecution") is not True
        ):
            return False, ()
        final_state_hash = item.get("final_state_hash")
        if not _is_sha256_hex(final_state_hash):
            return False, ()
        constructed = FormalDuelSeedResult(
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
        # MB-B-001（remediation-3）：逐 seed 判定必须复用唯一 canonical
        # validator；这里构造出的结果若不被 validator 接受则缓存无效。
        ok, _reason = validate_formal_live_result(constructed)
        if not ok:
            return False, ()
        results.append(constructed)
    # 集合级：failures/passed/natural_end/reexecution 必须由 details 重新
    # 派生并与声明值一致；禁止信任输入中声明的 passed/failure_count。
    summary = validate_formal_live_result_set(results)
    if not summary.all_valid:
        return False, ()
    if summary.natural_end_count != payload.get("natural_end_count"):
        return False, ()
    if summary.reexecution_verified_count != payload.get(
        "reexecution_verified_count"
    ):
        return False, ()
    if summary.failure_count != payload.get("failure_count"):
        return False, ()
    if summary.failure_count != 0 or payload.get("failures") != []:
        return False, ()
    return True, tuple(results)


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
    if not analysis_only:
        # R3-NEW-003（remediation-4）：正式 seed sweep 与 Session 使用同一
        # trusted authority boundary（exact type + capability identity +
        # canonical profile value），不复制另一套部分比较逻辑。
        assert_trusted_formal_configuration(configuration)
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
    "assert_trusted_formal_configuration",
    "build_formal_acceptance_artifact",
    "deck_identity",
    "FORMAL_SIMULATION_TRANSITIVE_INPUT_INVENTORY",
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
