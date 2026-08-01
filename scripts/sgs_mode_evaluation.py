"""三国杀模式适性、服务器奖励与外部参考的轻量评估工具。

本模块只实现项目当前采用的计算口径，不把评分公式描述为官方规则：

* 标准、非限时八人军争中，内奸实际获胜的 3 个有效胜场与进入主内
  单挑的 1 个有效胜场互斥；
* 斗地主同时保留地主、农民原始胜率及身份等权原始分，再按明确的
  身份适性选择性地乘以 0.9；
* NPC 只能出现在白名单身份，主评测池的通用武将比例可独立审计；
* 客户端六边形评分只保存为低权重外部参考及异常检查线索。

所有比率均使用 ``0`` 至 ``1`` 的小数。生产逻辑只依赖 Python 标准库。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Iterable, Mapping, Sequence

from ._validation import ensure_finite_real


def _strict_bool(value: object, label: str) -> bool:
    if not isinstance(value, bool):
        raise TypeError(f"{label}必须是布尔值")
    return value


def _nonempty_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label}必须是非空字符串")
    return value.strip()


def _probability(value: object, label: str) -> float:
    if isinstance(value, bool):
        raise TypeError(f"{label}必须是 0 至 1 的有限实数，不能使用布尔值")
    number = ensure_finite_real(value, label)
    if not 0.0 <= number <= 1.0:
        raise ValueError(f"{label}必须位于 0 至 1 之间，当前值为 {number}")
    return number


class SpyRewardScope(Enum):
    """内奸服务器奖励口径的适用范围。"""

    STANDARD_NON_LIMITED_EIGHT_PLAYER = "标准非限时八人军争"
    LIMITED_SPECIAL_EIGHT_PLAYER = "限时八人特殊玩法"


def _coerce_spy_scope(value: object) -> SpyRewardScope:
    if isinstance(value, SpyRewardScope):
        return value
    try:
        return SpyRewardScope(value)
    except (TypeError, ValueError) as exc:
        allowed = "、".join(item.value for item in SpyRewardScope)
        raise ValueError(f"奖励适用范围只能是：{allowed}") from exc


@dataclass(frozen=True)
class SpyGameResult:
    """一局内奸结果；胜利、单挑与奖励分保持为不同字段。"""

    actual_spy_win: bool
    reached_lord_spy_duel: bool
    scope: SpyRewardScope | str = SpyRewardScope.STANDARD_NON_LIMITED_EIGHT_PLAYER

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "actual_spy_win",
            _strict_bool(self.actual_spy_win, "内奸是否实际获胜"),
        )
        object.__setattr__(
            self,
            "reached_lord_spy_duel",
            _strict_bool(self.reached_lord_spy_duel, "是否进入主内单挑"),
        )
        object.__setattr__(self, "scope", _coerce_spy_scope(self.scope))


def standard_spy_server_reward(
    actual_spy_win: bool,
    reached_lord_spy_duel: bool,
    *,
    scope: SpyRewardScope | str = SpyRewardScope.STANDARD_NON_LIMITED_EIGHT_PLAYER,
) -> int:
    """返回单局服务器奖励口径有效胜场，且绝不叠加 3 与 1。

    该口径没有被确认适用于限时八人特殊玩法，所以传入该范围会直接
    报错，而不是静默复用标准模式公式。
    """

    win = _strict_bool(actual_spy_win, "内奸是否实际获胜")
    duel = _strict_bool(reached_lord_spy_duel, "是否进入主内单挑")
    parsed_scope = _coerce_spy_scope(scope)
    if parsed_scope is not SpyRewardScope.STANDARD_NON_LIMITED_EIGHT_PLAYER:
        raise ValueError("内奸服务器奖励口径仅适用于标准非限时八人军争")
    if win:
        return 3
    if duel:
        return 1
    return 0


@dataclass(frozen=True)
class SpyRewardSummary:
    """分栏后的内奸统计，服务器奖励得分不是原始胜率。"""

    sample_count: int
    actual_win_count: int
    duel_count: int
    raw_spy_win_rate: float
    lord_spy_duel_probability: float
    server_reward_total: int
    server_reward_score: float
    scope: SpyRewardScope = SpyRewardScope.STANDARD_NON_LIMITED_EIGHT_PLAYER
    reward_score_is_raw_win_rate: bool = False

    @property
    def raw_win_rate(self) -> float:
        """``raw_spy_win_rate`` 的报告友好别名。"""

        return self.raw_spy_win_rate

    @property
    def duel_probability(self) -> float:
        """``lord_spy_duel_probability`` 的报告友好别名。"""

        return self.lord_spy_duel_probability

    @property
    def reward_score(self) -> float:
        """服务器奖励得分别名；该值仍不代表原始胜率。"""

        return self.server_reward_score


def summarize_standard_spy_rewards(
    results: Iterable[SpyGameResult],
) -> SpyRewardSummary:
    """汇总非空的标准八人内奸结果，并分别报告三个核心指标。"""

    if isinstance(results, (str, bytes)):
        raise TypeError("内奸对局结果必须是 SpyGameResult 的可迭代对象")
    try:
        records = tuple(results)
    except TypeError as exc:
        raise TypeError("内奸对局结果必须是 SpyGameResult 的可迭代对象") from exc
    if not records:
        raise ValueError("至少需要一局内奸对局结果才能汇总")
    if any(not isinstance(record, SpyGameResult) for record in records):
        raise TypeError("每项内奸对局结果都必须是 SpyGameResult")
    if any(
        record.scope is not SpyRewardScope.STANDARD_NON_LIMITED_EIGHT_PLAYER
        for record in records
    ):
        raise ValueError("限时八人特殊玩法不能自动套用标准内奸服务器奖励口径")

    actual_wins = sum(record.actual_spy_win for record in records)
    duels = sum(record.reached_lord_spy_duel for record in records)
    reward_total = sum(
        standard_spy_server_reward(
            record.actual_spy_win,
            record.reached_lord_spy_duel,
            scope=record.scope,
        )
        for record in records
    )
    count = len(records)
    return SpyRewardSummary(
        sample_count=count,
        actual_win_count=actual_wins,
        duel_count=duels,
        raw_spy_win_rate=actual_wins / count,
        lord_spy_duel_probability=duels / count,
        server_reward_total=reward_total,
        server_reward_score=reward_total / count,
    )


class LandlordSuitability(Enum):
    """武将在斗地主中的身份适性。"""

    BOTH = "地主和农民均适合"
    FARMER_ONLY = "只适合农民"
    LANDLORD_ONLY = "只适合地主"
    UNSUITABLE = "整个斗地主模式不适合"


def _coerce_landlord_suitability(value: object) -> LandlordSuitability:
    if isinstance(value, LandlordSuitability):
        return value
    try:
        return LandlordSuitability(value)
    except (TypeError, ValueError) as exc:
        allowed = "、".join(item.value for item in LandlordSuitability)
        raise ValueError(f"斗地主身份适性只能是：{allowed}") from exc


@dataclass(frozen=True)
class LandlordSuitabilityEvaluation:
    """保留原始身份数据并公开适性公式的计算结果。"""

    landlord_win_rate: float
    farmer_win_rate: float
    raw_equal_role_score: float
    suitability: LandlordSuitability
    selectable_score: float | None
    selectable_roles: tuple[str, ...]
    included_in_landlord_pool: bool
    npc_can_appear_in_landlord_mode: bool
    other_major_mode_multiplier: float
    formula: str

    @property
    def L(self) -> float:  # noqa: N802 - 与项目公式记号保持一致
        return self.landlord_win_rate

    @property
    def F(self) -> float:  # noqa: N802 - 与项目公式记号保持一致
        return self.farmer_win_rate

    @property
    def S_raw(self) -> float:  # noqa: N802 - 与项目公式记号保持一致
        return self.raw_equal_role_score

    @property
    def S_selectable(self) -> float | None:  # noqa: N802 - 与项目公式记号保持一致
        return self.selectable_score


def evaluate_landlord_suitability(
    landlord_win_rate: float,
    farmer_win_rate: float,
    suitability: LandlordSuitability | str = LandlordSuitability.BOTH,
) -> LandlordSuitabilityEvaluation:
    """计算斗地主等权原始分及身份适性修正。

    ``0.9`` 是乘法惩罚，不是从胜率中减去 ``0.10``。
    """

    landlord = _probability(landlord_win_rate, "地主原始胜率")
    farmer = _probability(farmer_win_rate, "农民原始胜率")
    parsed = _coerce_landlord_suitability(suitability)
    raw = (landlord + farmer) / 2.0

    if parsed is LandlordSuitability.BOTH:
        score = raw
        roles = ("地主", "农民")
        formula = "(L + F) / 2"
        included = True
        npc_allowed = True
        other_multiplier = 1.0
    elif parsed is LandlordSuitability.FARMER_ONLY:
        score = 0.9 * farmer
        roles = ("农民",)
        formula = "0.9 * F"
        included = True
        npc_allowed = True
        other_multiplier = 1.0
    elif parsed is LandlordSuitability.LANDLORD_ONLY:
        score = 0.9 * landlord
        roles = ("地主",)
        formula = "0.9 * L"
        included = True
        npc_allowed = True
        other_multiplier = 1.0
    else:
        score = None
        roles = ()
        formula = "排除：整个斗地主模式不适合"
        included = False
        npc_allowed = False
        other_multiplier = 0.9

    return LandlordSuitabilityEvaluation(
        landlord_win_rate=landlord,
        farmer_win_rate=farmer,
        raw_equal_role_score=raw,
        suitability=parsed,
        selectable_score=score,
        selectable_roles=roles,
        included_in_landlord_pool=included,
        npc_can_appear_in_landlord_mode=npc_allowed,
        other_major_mode_multiplier=other_multiplier,
        formula=formula,
    )


def apply_other_mode_coverage_penalty(
    scores: Mapping[str, float],
    evaluation: LandlordSuitabilityEvaluation,
) -> Mapping[str, float]:
    """按适性结果修正其余各大模式分数，并保留不可变结果。

    只有“整个斗地主模式不适合”会令乘数成为 ``0.9``；本函数不会把
    该乘数误写成减去 10 个百分点。
    """

    if not isinstance(scores, Mapping) or not scores:
        raise ValueError("其余大模式评分必须是非空映射")
    if not isinstance(evaluation, LandlordSuitabilityEvaluation):
        raise TypeError("斗地主适性结果必须是 LandlordSuitabilityEvaluation")
    adjusted: dict[str, float] = {}
    for raw_mode, raw_score in scores.items():
        mode = _nonempty_text(raw_mode, "大模式名称")
        if isinstance(raw_score, bool):
            raise TypeError("大模式评分必须是有限实数，不能使用布尔值")
        score = ensure_finite_real(raw_score, f"{mode}评分")
        adjusted[mode] = score * evaluation.other_major_mode_multiplier
    return MappingProxyType(adjusted)


@dataclass(frozen=True)
class NpcRoleWhitelist:
    """NPC 可登场身份的显式白名单；空白名单表示不登场。"""

    general_name: str
    suitable_roles: frozenset[str]

    def __post_init__(self) -> None:
        object.__setattr__(self, "general_name", _nonempty_text(self.general_name, "武将名称"))
        try:
            raw_roles = tuple(self.suitable_roles)
        except TypeError as exc:
            raise TypeError("NPC适合身份必须是字符串集合") from exc
        roles = frozenset(_nonempty_text(role, "NPC适合身份") for role in raw_roles)
        object.__setattr__(self, "suitable_roles", roles)

    def allows(self, role: str) -> bool:
        return _nonempty_text(role, "待检查身份") in self.suitable_roles


def npc_can_appear(whitelist: NpcRoleWhitelist, role: str) -> bool:
    """仅当身份位于该武将白名单时允许 NPC 登场。"""

    if not isinstance(whitelist, NpcRoleWhitelist):
        raise TypeError("NPC身份白名单必须是 NpcRoleWhitelist")
    return whitelist.allows(role)


@dataclass(frozen=True)
class MainPoolCandidate:
    """综合主评测池中一名候选武将的通用性条件。"""

    general_name: str
    all_modes_usable: bool
    low_targeting: bool
    no_extreme_role_dependency: bool
    no_core_mechanism_lock: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "general_name", _nonempty_text(self.general_name, "武将名称"))
        for field_name, label in (
            ("all_modes_usable", "是否全模式可用"),
            ("low_targeting", "是否低针对性"),
            ("no_extreme_role_dependency", "是否无极端身份依赖"),
            ("no_core_mechanism_lock", "是否不封锁核心机制"),
        ):
            object.__setattr__(
                self,
                field_name,
                _strict_bool(getattr(self, field_name), label),
            )

    @property
    def is_generalist(self) -> bool:
        return all(
            (
                self.all_modes_usable,
                self.low_targeting,
                self.no_extreme_role_dependency,
                self.no_core_mechanism_lock,
            )
        )


@dataclass(frozen=True)
class MainPoolAudit:
    total_count: int
    generalist_count: int
    generalist_ratio: float
    minimum_ratio: float
    meets_recommendation: bool
    non_generalist_names: tuple[str, ...]


def audit_main_evaluation_pool(
    candidates: Sequence[MainPoolCandidate],
    *,
    minimum_generalist_ratio: float = 0.75,
) -> MainPoolAudit:
    """审计主评测池是否至少有指定比例同时满足四项通用条件。"""

    if isinstance(candidates, (str, bytes)) or not isinstance(candidates, Sequence):
        raise TypeError("主评测池候选必须是 MainPoolCandidate 序列")
    if not candidates:
        raise ValueError("主评测池至少需要一名候选武将")
    if any(not isinstance(item, MainPoolCandidate) for item in candidates):
        raise TypeError("主评测池每项都必须是 MainPoolCandidate")
    names = tuple(item.general_name for item in candidates)
    if len(set(names)) != len(names):
        raise ValueError("主评测池不能包含重复武将名称")
    threshold = _probability(minimum_generalist_ratio, "主评测池通用武将最低比例")
    generalists = sum(item.is_generalist for item in candidates)
    ratio = generalists / len(candidates)
    return MainPoolAudit(
        total_count=len(candidates),
        generalist_count=generalists,
        generalist_ratio=ratio,
        minimum_ratio=threshold,
        meets_recommendation=ratio >= threshold,
        non_generalist_names=tuple(
            item.general_name for item in candidates if not item.is_generalist
        ),
    )


class HexScoreSource(Enum):
    CLIENT_DIRECT_DISPLAY = "客户端直接显示"
    LEGACY_MANUAL_GRAPH = "旧式六边形人工读图"


def _coerce_hex_source(value: object) -> HexScoreSource:
    if isinstance(value, HexScoreSource):
        return value
    try:
        return HexScoreSource(value)
    except (TypeError, ValueError) as exc:
        allowed = "、".join(item.value for item in HexScoreSource)
        raise ValueError(f"六边形评分来源只能是：{allowed}") from exc


@dataclass(frozen=True)
class ClientHexReference:
    """客户端六边形评分容器，不参与原始胜率字段。

    旧式人工读图只保存整数刻度；客户端直接显示的小数则原样保留。
    """

    general_name: str
    role_scores: Mapping[str, float]
    source: HexScoreSource | str = HexScoreSource.CLIENT_DIRECT_DISPLAY
    evidence_status: str = "分析约定"
    evidence_role: str = "低权重外部参考与异常检查线索"
    is_raw_win_rate: bool = False
    is_official_strength_conclusion: bool = False
    is_required_simulation_fit_target: bool = False
    is_unique_ranking_basis: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "general_name", _nonempty_text(self.general_name, "武将名称"))
        if not isinstance(self.role_scores, Mapping) or not self.role_scores:
            raise ValueError("客户端六边形评分必须包含至少一个身份分值")
        parsed_source = _coerce_hex_source(self.source)
        parsed_scores: dict[str, float] = {}
        for raw_role, raw_score in self.role_scores.items():
            role = _nonempty_text(raw_role, "六边形身份名称")
            if isinstance(raw_score, bool):
                raise TypeError("六边形评分必须是非负有限实数，不能使用布尔值")
            score = ensure_finite_real(raw_score, f"{role}六边形评分")
            if score < 0:
                raise ValueError(f"{role}六边形评分不能为负数")
            if parsed_source is HexScoreSource.LEGACY_MANUAL_GRAPH and not score.is_integer():
                raise ValueError("旧式六边形人工读图只记录整数分，不使用半分")
            parsed_scores[role] = score
        object.__setattr__(self, "role_scores", MappingProxyType(parsed_scores))
        object.__setattr__(self, "source", parsed_source)
        if self.evidence_status != "分析约定":
            raise ValueError("客户端六边形评分的正式状态必须保持为“分析约定”")
        if self.evidence_role != "低权重外部参考与异常检查线索":
            raise ValueError("客户端六边形评分只能披露为低权重外部参考与异常检查线索")
        for field_name in (
            "is_raw_win_rate",
            "is_official_strength_conclusion",
            "is_required_simulation_fit_target",
            "is_unique_ranking_basis",
        ):
            if _strict_bool(getattr(self, field_name), field_name):
                raise ValueError("客户端六边形评分不得冒充胜率、官方结论或唯一排名依据")

    @property
    def disclosure(self) -> str:
        return (
            "客户端六边形评分仅作低权重外部参考与异常检查线索；"
            "不是真实胜率、官方严谨强度结论、强制拟合目标或唯一排名依据。"
        )


NEW_CAOCHUN_CLIENT_HEX_REFERENCE = ClientHexReference(
    general_name="新版曹纯",
    role_scores={
        "地主": 7.4,
        "主公": 6.7,
        "忠臣": 6.8,
        "反贼": 6.4,
        "内奸": 6.7,
        "农民": 7.0,
    },
    source=HexScoreSource.CLIENT_DIRECT_DISPLAY,
)
