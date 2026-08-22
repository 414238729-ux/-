# -*- coding: utf-8 -*-
"""POST-B C5/C6：正式无武将技能标准军争身份模式层。

本模块不是第二套引擎：身份场只提供 mode profile / 身份模型 /
OutcomePolicy / mode policy（初始化、身份公开、击杀奖惩、reshuffle_draw）
与可见性配置，全部消费统一生产核心（ProductionBasicCardBatch、
PlayerTopology、OutcomePolicy、既有 events/actions/damage/dying/death/
phase loop / parent-root continuation / strict replay）。

公开 façade 分别冻结五人（C5）与普通八人（C6）canonical profile；身份
胜负、公开、击杀奖惩、死亡 continuation 与牌堆供给继续共用同一标准身份
核心。范围只含非特殊军争身份、formal no-skill soldier、canonical
post-redraw combat initialization。不包含选将、真实武将技能、手气卡、
换牌、第5章特殊玩法、野心家、储君、继位、内奸择途或完整商业外围流程。
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields, replace
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping

from .actions import UnsupportedRuleError
from .events import EventType, GameEvent
from .model import (
    CharacterGender,
    CharacterMetadata,
    DRAW_PILE,
    GameState,
    ZoneRef,
)
from .multiplayer import OutcomePolicy, PlayerTopology
from .production_batch import (
    DeathConfirmationContext,
    ProductionBasicCardBatch,
    ProductionPhase,
)
from .rng import DeterministicRNG

FORMAL_NO_SKILL_IDENTITY_5P_MODE = "formal_no_skill_identity_5p"
FORMAL_NO_SKILL_IDENTITY_8P_MODE = "formal_no_skill_identity_8p"
POST_B_C6_FORMAL_IDENTITY_CONTRACT_ID = (
    "POST_B_C6_FORMAL_NO_SKILL_NORMAL_EIGHT_PLAYER_IDENTITY_MODE"
)
C6_CANONICAL_DRAW_REACHABILITY_STATUS = (
    "C6_CANONICAL_DRAW_REACHABILITY_UNRESOLVED"
)

_TRUSTED_IDENTITY_CAPABILITY = object()
_TRUSTED_EIGHT_PLAYER_IDENTITY_CAPABILITY = object()

_CANONICAL_PHYSICAL_PLAYER_IDS: tuple[str, str, str, str, str] = (
    "p1",
    "p2",
    "p3",
    "p4",
    "p5",
)
_CANONICAL_IDENTITY_CARDS: tuple[str, str, str, str, str] = (
    "lord",
    "loyalist",
    "rebel",
    "rebel",
    "spy",
)
_CANONICAL_EIGHT_PLAYER_PHYSICAL_PLAYER_IDS: tuple[
    str, str, str, str, str, str, str, str
] = (
    "p1",
    "p2",
    "p3",
    "p4",
    "p5",
    "p6",
    "p7",
    "p8",
)
_CANONICAL_EIGHT_PLAYER_IDENTITY_CARDS: tuple[
    str, str, str, str, str, str, str, str
] = (
    "lord",
    "loyalist",
    "loyalist",
    "rebel",
    "rebel",
    "rebel",
    "rebel",
    "spy",
)


class StandardIdentityRole(str, Enum):
    """五人标准身份场的 canonical 身份 token。"""

    LORD = "lord"
    LOYALIST = "loyalist"
    REBEL = "rebel"
    SPY = "spy"


class FormalIdentityConfigurationError(ValueError):
    """正式身份配置非法。"""


@dataclass(frozen=True, slots=True)
class FormalIdentityBlocker:
    code: str
    category: str
    message: str

    def to_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "category": self.category,
            "message": self.message,
        }


def _strict_canonical_value_equal(
    submitted: object, canonical: object
) -> bool:
    """递归比较 canonical value，同时要求每个节点的 Python 类型相同。"""

    if type(submitted) is not type(canonical):
        return False
    if isinstance(canonical, dict):
        submitted_items = list(submitted.items())  # type: ignore[union-attr]
        if len(submitted_items) != len(canonical):
            return False
        for canonical_key, canonical_item in canonical.items():
            for index, (submitted_key, submitted_item) in enumerate(
                submitted_items
            ):
                if _strict_canonical_value_equal(
                    submitted_key, canonical_key
                ):
                    if not _strict_canonical_value_equal(
                        submitted_item, canonical_item
                    ):
                        return False
                    del submitted_items[index]
                    break
            else:
                return False
        return not submitted_items
    if isinstance(canonical, (list, tuple)):
        return len(submitted) == len(canonical) and all(  # type: ignore[arg-type]
            _strict_canonical_value_equal(submitted_item, canonical_item)
            for submitted_item, canonical_item in zip(  # type: ignore[arg-type]
                submitted, canonical
            )
        )
    return submitted == canonical


def _configuration_profile_value(
    configuration: "FormalIdentityConfiguration",
) -> dict[str, object]:
    return {
        definition.name: getattr(configuration, definition.name)
        for definition in fields(FormalIdentityConfiguration)
    }


def _require_exact_tuple_of_str(
    value: object, size: int, label: str
) -> tuple[str, ...]:
    if type(value) is not tuple or len(value) != size:
        raise FormalIdentityConfigurationError(
            f"{label}必须是长度为{size}的字符串元组"
        )
    if any(type(item) is not str or not item.strip() for item in value):
        raise FormalIdentityConfigurationError(
            f"{label}的每一项都必须是非空字符串"
        )
    return tuple(item.strip() for item in value)


def _require_exact_int(value: object, expected: int, label: str) -> int:
    if type(value) is not int or value != expected:
        raise FormalIdentityConfigurationError(f"{label}必须是整数{expected}")
    return value


@dataclass(frozen=True, slots=True)
class FormalIdentityConfiguration:
    """正式 no-skill 五人标准身份场 canonical profile。

    physical_player_ids 是身份抽取前已经存在的环形不透明 ID；本轮不为
    它们制造第二次物理位置随机。身份牌为固定五张，由会话级同一 RNG
    在牌堆 shuffle 之前洗混后恰好覆盖五名玩家。
    """

    physical_player_ids: tuple[str, str, str, str, str] = (
        _CANONICAL_PHYSICAL_PLAYER_IDS
    )
    identity_cards: tuple[str, str, str, str, str] = _CANONICAL_IDENTITY_CARDS
    base_hp: int = 4
    base_max_hp: int = 4
    lord_hp: int = 5
    lord_max_hp: int = 5
    initial_hand_count: int = 4
    hand_qi_ka_allowed: bool = False
    deck_supply_mode: str = "reshuffle_draw"

    def __post_init__(self) -> None:
        physical = _require_exact_tuple_of_str(
            self.physical_player_ids, 5, "physical_player_ids"
        )
        if len(set(physical)) != 5:
            raise FormalIdentityConfigurationError(
                "physical_player_ids不能重复"
            )
        if physical != _CANONICAL_PHYSICAL_PLAYER_IDS:
            raise FormalIdentityConfigurationError(
                "正式五人身份场 physical_player_ids 必须是 ('p1','p2','p3','p4','p5')"
            )
        cards = _require_exact_tuple_of_str(
            self.identity_cards, 5, "identity_cards"
        )
        if tuple(sorted(cards)) != tuple(sorted(_CANONICAL_IDENTITY_CARDS)):
            raise FormalIdentityConfigurationError(
                "正式五人身份牌必须恰好为1主公、1忠臣、2反贼、1内奸"
            )
        if cards.count("lord") != 1 or cards.count("loyalist") != 1:
            raise FormalIdentityConfigurationError(
                "正式五人身份牌必须恰好1主公与1忠臣"
            )
        if cards.count("rebel") != 2 or cards.count("spy") != 1:
            raise FormalIdentityConfigurationError(
                "正式五人身份牌必须恰好2反贼与1内奸"
            )
        _require_exact_int(self.base_hp, 4, "base_hp")
        _require_exact_int(self.base_max_hp, 4, "base_max_hp")
        _require_exact_int(self.lord_hp, 5, "lord_hp")
        _require_exact_int(self.lord_max_hp, 5, "lord_max_hp")
        _require_exact_int(self.initial_hand_count, 4, "initial_hand_count")
        if type(self.hand_qi_ka_allowed) is not bool or self.hand_qi_ka_allowed:
            raise FormalIdentityConfigurationError(
                "正式身份场禁止手气卡"
            )
        if (
            type(self.deck_supply_mode) is not str
            or self.deck_supply_mode != "reshuffle_draw"
        ):
            raise FormalIdentityConfigurationError(
                "正式身份场牌堆供给口径必须是reshuffle_draw"
            )
        object.__setattr__(self, "physical_player_ids", physical)
        object.__setattr__(self, "identity_cards", cards)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": "formal-no-skill-identity-5p-configuration-v1",
            "physical_player_ids": list(self.physical_player_ids),
            "identity_cards": list(self.identity_cards),
            "base_hp": self.base_hp,
            "base_max_hp": self.base_max_hp,
            "lord_hp": self.lord_hp,
            "lord_max_hp": self.lord_max_hp,
            "initial_hand_count": self.initial_hand_count,
            "hand_qi_ka_allowed": self.hand_qi_ka_allowed,
            "deck_supply_mode": self.deck_supply_mode,
        }

    @classmethod
    def from_dict(
        cls, value: Mapping[str, object]
    ) -> "FormalIdentityConfiguration":
        if type(value) is not dict and not isinstance(value, Mapping):
            raise FormalIdentityConfigurationError("正式身份配置必须是JSON对象")
        expected_fields = {
            "schema",
            "physical_player_ids",
            "identity_cards",
            "base_hp",
            "base_max_hp",
            "lord_hp",
            "lord_max_hp",
            "initial_hand_count",
            "hand_qi_ka_allowed",
            "deck_supply_mode",
        }
        if set(value) != expected_fields:
            raise FormalIdentityConfigurationError("正式身份配置字段集不合法")
        if (
            type(value["schema"]) is not str
            or value["schema"]
            != "formal-no-skill-identity-5p-configuration-v1"
        ):
            raise FormalIdentityConfigurationError("正式身份配置schema不受支持")
        raw_ids = value["physical_player_ids"]
        raw_cards = value["identity_cards"]
        if type(raw_ids) not in (list, tuple) or type(raw_cards) not in (
            list,
            tuple,
        ):
            raise FormalIdentityConfigurationError(
                "physical_player_ids与identity_cards必须是序列"
            )
        return cls(
            physical_player_ids=tuple(raw_ids),  # type: ignore[arg-type]
            identity_cards=tuple(raw_cards),  # type: ignore[arg-type]
            base_hp=value["base_hp"],  # type: ignore[arg-type]
            base_max_hp=value["base_max_hp"],  # type: ignore[arg-type]
            lord_hp=value["lord_hp"],  # type: ignore[arg-type]
            lord_max_hp=value["lord_max_hp"],  # type: ignore[arg-type]
            initial_hand_count=value["initial_hand_count"],  # type: ignore[arg-type]
            hand_qi_ka_allowed=value["hand_qi_ka_allowed"],  # type: ignore[arg-type]
            deck_supply_mode=value["deck_supply_mode"],  # type: ignore[arg-type]
        )

    @staticmethod
    def formal_profile() -> "TrustedFormalIdentityConfiguration":
        """canonical formal no-skill identity profile（唯一正式来源）。"""
        return _canonical_formal_identity_profile_value()

    @classmethod
    def from_canonical_profile_value(
        cls, value: Mapping[str, object]
    ) -> "FormalIdentityConfiguration":
        canonical = cls.formal_profile()
        if not _strict_canonical_value_equal(value, canonical.to_dict()):
            raise FormalIdentityConfigurationError(
                "正式身份配置必须与项目 canonical formal profile 完全一致；"
                "payload 不能自行获得可信规则来源"
            )
        return canonical


@dataclass(frozen=True, slots=True)
class TrustedFormalIdentityConfiguration(FormalIdentityConfiguration):
    """仅由模块内 canonical factory 构造的 trusted 配置。"""

    _capability_token: object | None = field(
        default=None,
        init=False,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        FormalIdentityConfiguration.__post_init__(self)

    def __copy__(self) -> "TrustedFormalIdentityConfiguration":
        return replace(self)

    def __deepcopy__(
        self, memo: dict[int, object]
    ) -> "TrustedFormalIdentityConfiguration":
        del memo
        return replace(self)


def _canonical_formal_identity_profile_value() -> (
    "TrustedFormalIdentityConfiguration"
):
    configuration = TrustedFormalIdentityConfiguration(
        physical_player_ids=_CANONICAL_PHYSICAL_PLAYER_IDS,
        identity_cards=_CANONICAL_IDENTITY_CARDS,
        base_hp=4,
        base_max_hp=4,
        lord_hp=5,
        lord_max_hp=5,
        initial_hand_count=4,
        hand_qi_ka_allowed=False,
        deck_supply_mode="reshuffle_draw",
    )
    object.__setattr__(
        configuration,
        "_capability_token",
        _TRUSTED_IDENTITY_CAPABILITY,
    )
    return configuration


def assert_trusted_formal_identity_configuration(
    configuration: FormalIdentityConfiguration,
) -> None:
    """正式身份 trusted authority boundary（exact type + capability + value）。"""
    if not isinstance(configuration, FormalIdentityConfiguration):
        raise TypeError("正式身份会话必须接收FormalIdentityConfiguration")
    if type(configuration) is not TrustedFormalIdentityConfiguration:
        raise FormalIdentityConfigurationError(
            "正式身份结果只接受内部 canonical factory 返回的 "
            "TrustedFormalIdentityConfiguration（exact type 校验）；调用方配置"
            "不能自我授权"
        )
    if (
        getattr(configuration, "_capability_token", None)
        is not _TRUSTED_IDENTITY_CAPABILITY
    ):
        raise FormalIdentityConfigurationError(
            "正式身份结果只接受真实持有模块私有 capability token 的 "
            "TrustedFormalIdentityConfiguration（capability identity 校验）"
        )
    canonical = _canonical_formal_identity_profile_value()
    if not _strict_canonical_value_equal(
        _configuration_profile_value(configuration),
        _configuration_profile_value(canonical),
    ):
        raise FormalIdentityConfigurationError(
            "正式身份配置的 profile value 必须精确等于项目 canonical "
            "formal no-skill identity profile；type/token 正确但值非 canonical "
            "的对象同样失败关闭（canonical value invariant）"
        )


@dataclass(frozen=True, slots=True)
class FormalEightPlayerIdentityConfiguration:
    """C6 普通八人 formal no-skill 标准身份 canonical profile。

    该类型与 C5 ``FormalIdentityConfiguration`` 完全独立：八人 authority
    不能扩宽五人 schema/type 边界。physical IDs 是身份抽取前已经确定的
    环形位置，只洗身份牌，不再次随机化物理座位。
    """

    physical_player_ids: tuple[
        str, str, str, str, str, str, str, str
    ] = _CANONICAL_EIGHT_PLAYER_PHYSICAL_PLAYER_IDS
    identity_cards: tuple[
        str, str, str, str, str, str, str, str
    ] = _CANONICAL_EIGHT_PLAYER_IDENTITY_CARDS
    base_hp: int = 4
    base_max_hp: int = 4
    lord_hp: int = 5
    lord_max_hp: int = 5
    initial_hand_count: int = 4
    hand_qi_ka_allowed: bool = False
    deck_supply_mode: str = "reshuffle_draw"

    def __post_init__(self) -> None:
        physical = _require_exact_tuple_of_str(
            self.physical_player_ids, 8, "physical_player_ids"
        )
        if len(set(physical)) != 8:
            raise FormalIdentityConfigurationError(
                "physical_player_ids不能重复"
            )
        if physical != _CANONICAL_EIGHT_PLAYER_PHYSICAL_PLAYER_IDS:
            raise FormalIdentityConfigurationError(
                "正式八人身份场 physical_player_ids 必须是 "
                "('p1','p2','p3','p4','p5','p6','p7','p8')"
            )
        cards = _require_exact_tuple_of_str(
            self.identity_cards, 8, "identity_cards"
        )
        if tuple(sorted(cards)) != tuple(
            sorted(_CANONICAL_EIGHT_PLAYER_IDENTITY_CARDS)
        ):
            raise FormalIdentityConfigurationError(
                "正式八人身份牌必须恰好为1主公、2忠臣、4反贼、1内奸"
            )
        if cards.count("lord") != 1 or cards.count("loyalist") != 2:
            raise FormalIdentityConfigurationError(
                "正式八人身份牌必须恰好1主公与2忠臣"
            )
        if cards.count("rebel") != 4 or cards.count("spy") != 1:
            raise FormalIdentityConfigurationError(
                "正式八人身份牌必须恰好4反贼与1内奸"
            )
        _require_exact_int(self.base_hp, 4, "base_hp")
        _require_exact_int(self.base_max_hp, 4, "base_max_hp")
        _require_exact_int(self.lord_hp, 5, "lord_hp")
        _require_exact_int(self.lord_max_hp, 5, "lord_max_hp")
        _require_exact_int(self.initial_hand_count, 4, "initial_hand_count")
        if type(self.hand_qi_ka_allowed) is not bool or self.hand_qi_ka_allowed:
            raise FormalIdentityConfigurationError(
                "正式八人身份场禁止手气卡"
            )
        if (
            type(self.deck_supply_mode) is not str
            or self.deck_supply_mode != "reshuffle_draw"
        ):
            raise FormalIdentityConfigurationError(
                "正式八人身份场牌堆供给口径必须是reshuffle_draw"
            )
        object.__setattr__(self, "physical_player_ids", physical)
        object.__setattr__(self, "identity_cards", cards)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": "formal-no-skill-identity-8p-configuration-v1",
            "physical_player_ids": list(self.physical_player_ids),
            "identity_cards": list(self.identity_cards),
            "base_hp": self.base_hp,
            "base_max_hp": self.base_max_hp,
            "lord_hp": self.lord_hp,
            "lord_max_hp": self.lord_max_hp,
            "initial_hand_count": self.initial_hand_count,
            "hand_qi_ka_allowed": self.hand_qi_ka_allowed,
            "deck_supply_mode": self.deck_supply_mode,
        }

    @classmethod
    def from_dict(
        cls, value: Mapping[str, object]
    ) -> "FormalEightPlayerIdentityConfiguration":
        if cls is not FormalEightPlayerIdentityConfiguration:
            raise FormalIdentityConfigurationError(
                "正式八人身份配置解析禁止通过子类改变exact dataclass type"
            )
        if type(value) is not dict:
            raise FormalIdentityConfigurationError(
                "正式八人身份配置必须是exact JSON对象，禁止dict子类"
            )
        expected_fields = {
            "schema",
            "physical_player_ids",
            "identity_cards",
            "base_hp",
            "base_max_hp",
            "lord_hp",
            "lord_max_hp",
            "initial_hand_count",
            "hand_qi_ka_allowed",
            "deck_supply_mode",
        }
        if set(value) != expected_fields:
            raise FormalIdentityConfigurationError(
                "正式八人身份配置字段集不合法"
            )
        if (
            type(value["schema"]) is not str
            or value["schema"]
            != "formal-no-skill-identity-8p-configuration-v1"
        ):
            raise FormalIdentityConfigurationError(
                "正式八人身份配置schema不受支持"
            )
        raw_ids = value["physical_player_ids"]
        raw_cards = value["identity_cards"]
        if type(raw_ids) is not list or type(raw_cards) is not list:
            raise FormalIdentityConfigurationError(
                "physical_player_ids与identity_cards必须是exact JSON数组"
            )
        return cls(
            physical_player_ids=tuple(raw_ids),  # type: ignore[arg-type]
            identity_cards=tuple(raw_cards),  # type: ignore[arg-type]
            base_hp=value["base_hp"],  # type: ignore[arg-type]
            base_max_hp=value["base_max_hp"],  # type: ignore[arg-type]
            lord_hp=value["lord_hp"],  # type: ignore[arg-type]
            lord_max_hp=value["lord_max_hp"],  # type: ignore[arg-type]
            initial_hand_count=value["initial_hand_count"],  # type: ignore[arg-type]
            hand_qi_ka_allowed=value["hand_qi_ka_allowed"],  # type: ignore[arg-type]
            deck_supply_mode=value["deck_supply_mode"],  # type: ignore[arg-type]
        )

    @staticmethod
    def formal_profile() -> "TrustedFormalEightPlayerIdentityConfiguration":
        """C6 canonical trusted profile 的唯一正式来源。"""

        return _canonical_formal_eight_player_identity_profile_value()

    @classmethod
    def from_canonical_profile_value(
        cls, value: Mapping[str, object]
    ) -> "FormalEightPlayerIdentityConfiguration":
        if cls is not FormalEightPlayerIdentityConfiguration:
            raise FormalIdentityConfigurationError(
                "正式八人身份 canonical 解析禁止子类旁路"
            )
        canonical = cls.formal_profile()
        if not _strict_canonical_value_equal(value, canonical.to_dict()):
            raise FormalIdentityConfigurationError(
                "正式八人身份配置必须与项目 canonical formal profile "
                "递归exact-type完全一致；payload不能自行获得可信规则来源"
            )
        return canonical


@dataclass(frozen=True, slots=True)
class TrustedFormalEightPlayerIdentityConfiguration(
    FormalEightPlayerIdentityConfiguration
):
    """仅由模块内 C6 canonical factory 构造的 trusted 配置。"""

    _capability_token: object | None = field(
        default=None,
        init=False,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        FormalEightPlayerIdentityConfiguration.__post_init__(self)

    def __copy__(self) -> "TrustedFormalEightPlayerIdentityConfiguration":
        return replace(self)

    def __deepcopy__(
        self, memo: dict[int, object]
    ) -> "TrustedFormalEightPlayerIdentityConfiguration":
        del memo
        return replace(self)


def _canonical_formal_eight_player_identity_profile_value() -> (
    "TrustedFormalEightPlayerIdentityConfiguration"
):
    configuration = TrustedFormalEightPlayerIdentityConfiguration(
        physical_player_ids=_CANONICAL_EIGHT_PLAYER_PHYSICAL_PLAYER_IDS,
        identity_cards=_CANONICAL_EIGHT_PLAYER_IDENTITY_CARDS,
        base_hp=4,
        base_max_hp=4,
        lord_hp=5,
        lord_max_hp=5,
        initial_hand_count=4,
        hand_qi_ka_allowed=False,
        deck_supply_mode="reshuffle_draw",
    )
    object.__setattr__(
        configuration,
        "_capability_token",
        _TRUSTED_EIGHT_PLAYER_IDENTITY_CAPABILITY,
    )
    return configuration


def _eight_player_configuration_profile_value(
    configuration: FormalEightPlayerIdentityConfiguration,
) -> dict[str, object]:
    return {
        definition.name: getattr(configuration, definition.name)
        for definition in fields(FormalEightPlayerIdentityConfiguration)
    }


def assert_trusted_formal_eight_player_identity_configuration(
    configuration: FormalEightPlayerIdentityConfiguration,
) -> None:
    """C6 trusted authority：exact type + private capability + exact value。"""

    if not isinstance(configuration, FormalEightPlayerIdentityConfiguration):
        raise TypeError(
            "正式八人身份会话必须接收FormalEightPlayerIdentityConfiguration"
        )
    if type(configuration) is not TrustedFormalEightPlayerIdentityConfiguration:
        raise FormalIdentityConfigurationError(
            "正式八人身份结果只接受内部 canonical factory 返回的 "
            "TrustedFormalEightPlayerIdentityConfiguration（exact type 校验）"
        )
    if (
        getattr(configuration, "_capability_token", None)
        is not _TRUSTED_EIGHT_PLAYER_IDENTITY_CAPABILITY
    ):
        raise FormalIdentityConfigurationError(
            "正式八人身份结果只接受真实持有模块私有 capability token 的 "
            "TrustedFormalEightPlayerIdentityConfiguration"
        )
    canonical = _canonical_formal_eight_player_identity_profile_value()
    if not _strict_canonical_value_equal(
        _eight_player_configuration_profile_value(configuration),
        _eight_player_configuration_profile_value(canonical),
    ):
        raise FormalIdentityConfigurationError(
            "正式八人身份配置必须递归 exact-type 等于项目 canonical profile；"
            "type/token正确但值非canonical的对象同样失败关闭"
        )


@dataclass(frozen=True, slots=True)
class _StandardIdentityProfile:
    """C5/C6 共用的内部标准身份 profile 参数，不是公开 authority。"""

    mode_id: str
    label: str
    player_count: int
    role_counts: tuple[tuple[StandardIdentityRole, int], ...]


_FIVE_PLAYER_IDENTITY_PROFILE = _StandardIdentityProfile(
    mode_id=FORMAL_NO_SKILL_IDENTITY_5P_MODE,
    label="正式五人身份",
    player_count=5,
    role_counts=(
        (StandardIdentityRole.LORD, 1),
        (StandardIdentityRole.LOYALIST, 1),
        (StandardIdentityRole.REBEL, 2),
        (StandardIdentityRole.SPY, 1),
    ),
)
_EIGHT_PLAYER_IDENTITY_PROFILE = _StandardIdentityProfile(
    mode_id=FORMAL_NO_SKILL_IDENTITY_8P_MODE,
    label="正式普通八人身份",
    player_count=8,
    role_counts=(
        (StandardIdentityRole.LORD, 1),
        (StandardIdentityRole.LOYALIST, 2),
        (StandardIdentityRole.REBEL, 4),
        (StandardIdentityRole.SPY, 1),
    ),
)


def _identity_profile_for_configuration(
    configuration: object,
) -> _StandardIdentityProfile:
    if isinstance(configuration, FormalIdentityConfiguration):
        return _FIVE_PLAYER_IDENTITY_PROFILE
    if isinstance(configuration, FormalEightPlayerIdentityConfiguration):
        return _EIGHT_PLAYER_IDENTITY_PROFILE
    raise TypeError("标准身份核心收到不受支持的配置类型")


def _identity_profile_for_player_count(
    player_count: int,
) -> _StandardIdentityProfile:
    if player_count == 5:
        return _FIVE_PLAYER_IDENTITY_PROFILE
    if player_count == 8:
        return _EIGHT_PLAYER_IDENTITY_PROFILE
    raise FormalIdentityConfigurationError(
        "标准身份胜负策略只接受已冻结的五人或普通八人profile"
    )


def _parse_identity_role(value: object, player_id: str) -> StandardIdentityRole:
    if type(value) is StandardIdentityRole:
        return value
    if type(value) is not str:
        raise FormalIdentityConfigurationError(
            f"角色{player_id!r}的身份必须是canonical字符串，不能用其他类型伪装"
        )
    try:
        return StandardIdentityRole(value)
    except ValueError as exc:
        raise FormalIdentityConfigurationError(
            f"角色{player_id!r}的身份{value!r}不是标准身份"
        ) from exc


@dataclass(frozen=True, slots=True)
class IdentityOutcomePolicy(OutcomePolicy):
    """C5/C6 共用的标准身份胜负策略。

    - lord 存活且场上无 rebel/spy → lord_and_loyalists
    - 仅剩 lord + spy → 不终局
    - lord 确认死亡且唯一其他存活角色为 spy → spy
    - lord 确认死亡的其他所有情况（含无人存活）→ rebels
    主忠 / 反贼 outcome 是阵营结果，不把胜者限制成当前存活列表。
    """

    identities: Mapping[str, StandardIdentityRole] = MappingProxyType({})

    def __init__(self, identities: Mapping[str, StandardIdentityRole]) -> None:
        if not isinstance(identities, Mapping):
            raise FormalIdentityConfigurationError(
                "身份胜负策略需要角色→身份映射"
            )
        profile = _identity_profile_for_player_count(len(identities))
        parsed: dict[str, StandardIdentityRole] = {}
        for player_id, raw_role in identities.items():
            if type(player_id) is not str or not player_id.strip():
                raise FormalIdentityConfigurationError(
                    "身份映射的角色ID必须是非空字符串"
                )
            parsed[player_id] = _parse_identity_role(raw_role, player_id)
        roles = tuple(parsed.values())
        if any(
            roles.count(role) != expected
            for role, expected in profile.role_counts
        ):
            composition = (
                "1主公、1忠臣、2反贼、1内奸"
                if profile.player_count == 5
                else "1主公、2忠臣、4反贼、1内奸"
            )
            raise FormalIdentityConfigurationError(
                f"{profile.label}必须恰好{composition}"
            )
        object.__setattr__(self, "policy_id", profile.mode_id)
        object.__setattr__(self, "identities", MappingProxyType(parsed))

    def role_of(self, player_id: str) -> StandardIdentityRole:
        role = self.identities.get(player_id)
        if role is None:
            raise UnsupportedRuleError(
                f"角色{player_id!r}未注册正式身份"
            )
        return role

    def resolve_winner_after_death(
        self, topology: PlayerTopology, dying_id: str
    ) -> str | None:
        del dying_id
        alive_roles = [
            self.role_of(player.player_id)
            for player in topology.players
            if player.alive
        ]
        lord_alive = StandardIdentityRole.LORD in alive_roles
        rebel_alive = StandardIdentityRole.REBEL in alive_roles
        spy_alive = StandardIdentityRole.SPY in alive_roles
        if lord_alive:
            if not rebel_alive and not spy_alive:
                return "lord_and_loyalists"
            return None
        others = [
            player.player_id
            for player in topology.players
            if player.alive
        ]
        if (
            len(others) == 1
            and self.role_of(others[0]) is StandardIdentityRole.SPY
        ):
            return "spy"
        return "rebels"

    @property
    def finish_reason(self) -> str:
        return "identity_victory"

    @property
    def draw_finish_reason(self) -> str:
        return "identity_draw_deck_exhausted"


@dataclass(frozen=True, slots=True)
class IdentityModePolicy:
    """C5/C6 共享身份模式层：初始化、公开与击杀奖惩钩子。"""

    configuration: (
        FormalIdentityConfiguration
        | FormalEightPlayerIdentityConfiguration
    )
    identities: Mapping[str, StandardIdentityRole] = MappingProxyType({})
    numbered_player_order: tuple[str, ...] = ()
    lord_player_id: str = ""
    physical_player_ids: tuple[str, ...] = ()
    seat_by_player: Mapping[str, int] = MappingProxyType({})
    mode_id: str = ""

    def __init__(
        self,
        configuration: (
            FormalIdentityConfiguration
            | FormalEightPlayerIdentityConfiguration
        ),
        identities: Mapping[str, StandardIdentityRole],
        numbered_player_order: tuple[str, ...],
        lord_player_id: str,
    ) -> None:
        profile = _identity_profile_for_configuration(configuration)
        outcome_policy = IdentityOutcomePolicy(identities)
        if outcome_policy.policy_id != profile.mode_id:
            raise FormalIdentityConfigurationError(
                "身份映射人数/组成与配置profile不一致"
            )
        parsed = outcome_policy.identities
        if type(numbered_player_order) is not tuple or len(
            numbered_player_order
        ) != profile.player_count:
            raise FormalIdentityConfigurationError(
                "numbered_player_order必须是"
                f"{profile.player_count}名角色的元组"
            )
        if lord_player_id not in parsed:
            raise FormalIdentityConfigurationError("lord_player_id未出现在身份映射中")
        if parsed[lord_player_id] is not StandardIdentityRole.LORD:
            raise FormalIdentityConfigurationError(
                "lord_player_id必须对应该局唯一主公"
            )
        if numbered_player_order[0] != lord_player_id:
            raise FormalIdentityConfigurationError(
                "numbered_player_order必须以主公为座次1"
            )
        physical = configuration.physical_player_ids
        if set(numbered_player_order) != set(physical):
            raise FormalIdentityConfigurationError(
                "numbered_player_order必须恰好覆盖全部 physical_player_ids"
            )
        lord_index = physical.index(lord_player_id)
        expected = physical[lord_index:] + physical[:lord_index]
        if numbered_player_order != expected:
            raise FormalIdentityConfigurationError(
                "numbered_player_order必须从主公 physical position 沿递增方向旋转"
            )
        seats = {
            player_id: index + 1
            for index, player_id in enumerate(numbered_player_order)
        }
        object.__setattr__(self, "configuration", configuration)
        object.__setattr__(self, "identities", parsed)
        object.__setattr__(self, "numbered_player_order", numbered_player_order)
        object.__setattr__(self, "lord_player_id", lord_player_id)
        object.__setattr__(self, "physical_player_ids", physical)
        object.__setattr__(self, "seat_by_player", MappingProxyType(seats))
        object.__setattr__(self, "mode_id", profile.mode_id)

    @property
    def identity(self) -> str:
        return f"mode:{self.mode_id}"

    @property
    def initial_hand_counts(self) -> tuple[int, ...]:
        count = self.configuration.initial_hand_count
        return tuple(count for _ in self.physical_player_ids)

    @property
    def first_player_id(self) -> str:
        return self.lord_player_id

    @property
    def deck_supply_mode(self) -> str:
        return self.configuration.deck_supply_mode

    def role_of(self, player_id: str) -> StandardIdentityRole:
        role = self.identities.get(player_id)
        if role is None:
            raise FormalIdentityConfigurationError(
                f"角色{player_id!r}未注册正式身份"
            )
        return role

    def identities_as_str(self) -> dict[str, str]:
        return {
            player_id: role.value
            for player_id, role in self.identities.items()
        }

    def identity_reveal_on_confirmed_death(
        self, dying_id: str
    ) -> GameEvent | None:
        """非主公确认死亡后公开该角色身份；主公开局已经公开。"""

        if self.role_of(dying_id) is StandardIdentityRole.LORD:
            return None
        return GameEvent(
            event_type=EventType.IDENTITY_REVEALED,
            target_ids=(dying_id,),
            payload={
                "reason": "confirmed_death",
                "identity": self.role_of(dying_id).value,
            },
        )

    def death_confirmed_hook(
        self,
        session: object,
        state: GameState,
        runtime: object,
        dying_id: str,
        death_context: object | None = None,
    ) -> tuple[GameState, object]:
        """非终局确认死亡后的身份击杀奖惩。

        必须读取 DeathConfirmationContext 中的最终 kill_credit，不得猜
        card_user / 回合角色 / 根牌使用者。无合法 credit 则不创造虚假
        killer。击杀来源已死亡时仍按冻结规则使用该 credit，不额外要求
        killer must be alive。
        """

        if not isinstance(death_context, DeathConfirmationContext):
            raise FormalIdentityConfigurationError(
                "正式身份模式死亡确认钩子需要明确的DeathConfirmationContext"
            )
        if death_context.dying_id != dying_id:
            raise FormalIdentityConfigurationError(
                "死亡确认上下文的dying_id与当前死亡角色不一致"
            )
        credit = death_context.kill_credit
        role = self.role_of(dying_id)
        if role is StandardIdentityRole.REBEL:
            if credit is None:
                return state, runtime
            reward_draw = getattr(session, "_mode_death_reward_draw")
            return reward_draw(
                state,
                runtime,
                credit,
                3,
                reason="identity_kill_rebel_draw",
            )
        if (
            role is StandardIdentityRole.LOYALIST
            and credit is not None
            and credit == self.lord_player_id
        ):
            penalty = getattr(session, "_mode_identity_lord_penalty_discard")
            return penalty(state, runtime, self.lord_player_id)
        return state, runtime


_FORMAL_IDENTITY_EXECUTION_RELEASED = True
_CANONICAL_IDENTITY_TEST_CHARACTER = "soldier"


def _assign_identities(
    configuration: (
        FormalIdentityConfiguration
        | FormalEightPlayerIdentityConfiguration
    ),
    rng: DeterministicRNG,
) -> tuple[
    dict[str, StandardIdentityRole],
    tuple[str, ...],
    str,
]:
    """用会话 RNG 洗混 profile 身份牌并旋转座次；禁止第二 RNG。"""

    cards = list(configuration.identity_cards)
    rng.shuffle(cards)
    identities = {
        player_id: StandardIdentityRole(card)
        for player_id, card in zip(configuration.physical_player_ids, cards)
    }
    lords = [
        player_id
        for player_id, role in identities.items()
        if role is StandardIdentityRole.LORD
    ]
    if len(lords) != 1:
        raise FormalIdentityConfigurationError("身份分配后必须恰好一名主公")
    lord_id = lords[0]
    physical = configuration.physical_player_ids
    lord_index = physical.index(lord_id)
    numbered = physical[lord_index:] + physical[:lord_index]
    return identities, numbered, lord_id


def _assert_trusted_standard_identity_configuration(
    configuration: (
        FormalIdentityConfiguration
        | FormalEightPlayerIdentityConfiguration
    ),
) -> None:
    profile = _identity_profile_for_configuration(configuration)
    if profile.mode_id == FORMAL_NO_SKILL_IDENTITY_5P_MODE:
        assert_trusted_formal_identity_configuration(configuration)  # type: ignore[arg-type]
        return
    assert_trusted_formal_eight_player_identity_configuration(
        configuration  # type: ignore[arg-type]
    )


class _FormalStandardIdentitySession(ProductionBasicCardBatch):
    """C5/C6 共享 canonical 会话初始化与正式资格核心。

    同一条 DeterministicRNG 依序用于：身份牌 shuffle → 正式160张牌堆
    shuffle → 后续普通 reshuffle。调用方不能注入 RNG。
    """

    def _initialize_standard_identity_session(
        self,
        *,
        seed: int,
        configuration: (
            FormalIdentityConfiguration
            | FormalEightPlayerIdentityConfiguration
        ),
        analysis_only: bool = False,
        session_id: str | None = None,
        session_secret: bytes | None = None,
    ) -> None:
        if type(analysis_only) is not bool:
            raise TypeError("analysis_only必须是布尔值")
        profile = _identity_profile_for_configuration(configuration)
        if self.MODE_ID != profile.mode_id:
            raise FormalIdentityConfigurationError(
                "标准身份会话 façade 与 configuration profile 不一致"
            )
        if not analysis_only:
            _assert_trusted_standard_identity_configuration(configuration)
        if not _FORMAL_IDENTITY_EXECUTION_RELEASED:
            raise FormalIdentityConfigurationError(
                "正式身份仍有模式/回放门禁未关闭，禁止生成正式结果"
            )
        if type(seed) is not int:
            raise TypeError("随机种子必须是整数")
        rng = DeterministicRNG(seed)
        identities, numbered, lord_id = _assign_identities(configuration, rng)
        player_hp = tuple(
            configuration.lord_hp if player_id == lord_id else configuration.base_hp
            for player_id in numbered
        )
        player_max_hp = tuple(
            configuration.lord_max_hp
            if player_id == lord_id
            else configuration.base_max_hp
            for player_id in numbered
        )
        hand_counts = tuple(
            configuration.initial_hand_count for _ in numbered
        )
        mode_policy = IdentityModePolicy(
            configuration, identities, numbered, lord_id
        )
        self._formal_configuration = configuration
        self._analysis_only = analysis_only
        self._physical_player_ids = configuration.physical_player_ids
        self._identities_by_player = MappingProxyType(dict(identities))
        self._numbered_player_order = numbered
        self._lord_player_id = lord_id
        self._seat_by_player = MappingProxyType(dict(mode_policy.seat_by_player))
        super().__init__(
            seed=seed,
            player_hp=player_hp,
            player_max_hp=player_max_hp,
            player_ids=numbered,
            outcome_policy=IdentityOutcomePolicy(identities),
            initial_hand_counts=hand_counts,
            first_player_id=lord_id,
            mode_policy=mode_policy,
            shuffle=True,
            session_id=session_id,
            session_secret=session_secret,
            _internal_rng=rng,
        )
        soldier = CharacterMetadata(
            _CANONICAL_IDENTITY_TEST_CHARACTER,
            CharacterGender.NONE,
            CharacterGender.NONE,
        )
        players = tuple(
            replace(player, character=soldier)
            for player in self.state.players
        )
        self._state = replace(self.state, players=players)
        self._events.extend(
            (
                GameEvent(
                    event_type=EventType.IDENTITY_REVEALED,
                    target_ids=(lord_id,),
                    payload={
                        "reason": "initial_lord_reveal",
                        "identity": StandardIdentityRole.LORD.value,
                    },
                ),
            )
        )

    @property
    def formal_configuration(
        self,
    ) -> FormalIdentityConfiguration | FormalEightPlayerIdentityConfiguration:
        return self._formal_configuration

    @property
    def analysis_only(self) -> bool:
        return self._analysis_only

    @property
    def physical_player_ids(self) -> tuple[str, ...]:
        return self._physical_player_ids

    @property
    def identities_by_player(self) -> Mapping[str, StandardIdentityRole]:
        return self._identities_by_player

    @property
    def numbered_player_order(self) -> tuple[str, ...]:
        return self._numbered_player_order

    @property
    def lord_player_id(self) -> str:
        return self._lord_player_id

    @property
    def seat_by_player(self) -> Mapping[str, int]:
        return self._seat_by_player

    @property
    def formal_result_eligible(self) -> bool:
        if not _FORMAL_IDENTITY_EXECUTION_RELEASED or self._analysis_only:
            return False
        try:
            _assert_trusted_standard_identity_configuration(
                self._formal_configuration
            )
        except (TypeError, FormalIdentityConfigurationError):
            return False
        return True


class FormalIdentitySession(_FormalStandardIdentitySession):
    """C5 五人 exact canonical façade；schema/replay 行为保持兼容。"""

    MODE_ID = FORMAL_NO_SKILL_IDENTITY_5P_MODE

    def __init__(
        self,
        *,
        seed: int,
        configuration: FormalIdentityConfiguration,
        analysis_only: bool = False,
        session_id: str | None = None,
        session_secret: bytes | None = None,
    ) -> None:
        if type(self) is not FormalIdentitySession:
            raise TypeError(
                "正式身份 canonical 会话不允许通过子类覆写释放或配置边界"
            )
        if not isinstance(configuration, FormalIdentityConfiguration):
            raise TypeError("正式身份会话必须接收FormalIdentityConfiguration")
        self._initialize_standard_identity_session(
            seed=seed,
            configuration=configuration,
            analysis_only=analysis_only,
            session_id=session_id,
            session_secret=session_secret,
        )


class FormalEightPlayerIdentitySession(_FormalStandardIdentitySession):
    """C6 普通八人 exact canonical façade；直接复用统一生产状态机。"""

    MODE_ID = FORMAL_NO_SKILL_IDENTITY_8P_MODE

    def __init__(
        self,
        *,
        seed: int,
        configuration: FormalEightPlayerIdentityConfiguration,
        analysis_only: bool = False,
        session_id: str | None = None,
        session_secret: bytes | None = None,
    ) -> None:
        if type(self) is not FormalEightPlayerIdentitySession:
            raise TypeError(
                "正式八人身份 canonical 会话不允许子类覆写 authority 边界"
            )
        if not isinstance(
            configuration, FormalEightPlayerIdentityConfiguration
        ):
            raise TypeError(
                "正式八人身份会话必须接收"
                "FormalEightPlayerIdentityConfiguration"
            )
        self._initialize_standard_identity_session(
            seed=seed,
            configuration=configuration,
            analysis_only=analysis_only,
            session_id=session_id,
            session_secret=session_secret,
        )
        self._formal_runtime_integrity_valid = True
        self._formal_runtime_integrity_anchor = (
            self._current_execution_integrity_anchor()
        )

    def _current_execution_integrity_anchor(
        self,
    ) -> tuple[int, int, int, int, int, int]:
        """轻量绑定不可变 state/runtime 对象与追加流长度。"""

        return (
            id(self._state),
            id(self._runtime),
            self.step_count,
            len(self.events),
            len(self.rng_calls),
            len(self.phase_history),
        )

    def step(self, controller: Any = None) -> Any:
        """合法 step 更新 C6 integrity anchor；外部预突变永久撤销正式资格。"""

        if (
            self._current_execution_integrity_anchor()
            != self._formal_runtime_integrity_anchor
        ):
            self._formal_runtime_integrity_valid = False
        validated = super().step(controller)
        self._formal_runtime_integrity_anchor = (
            self._current_execution_integrity_anchor()
        )
        return validated

    @property
    def formal_result_eligible(self) -> bool:
        if not self._formal_runtime_integrity_valid:
            return False
        if (
            self._current_execution_integrity_anchor()
            != self._formal_runtime_integrity_anchor
        ):
            return False
        return super().formal_result_eligible


@dataclass(frozen=True, slots=True)
class FormalIdentityReadiness:
    """正式 no-skill 五人身份现场就绪状态（静态执行资格；不是验收证据）。"""

    mode_id: str
    deck_count: int
    registered_card_key_count: int
    registered_instance_count: int
    global_card_semantics_complete: bool
    mode_runtime_reachable: bool
    mode_implemented: bool
    deterministic_controller_implemented: bool
    reexecution_replay_supported: bool
    unsupported_rules: int
    approximation_count: int
    formal_identity_no_skill_ready: bool
    identity_ready: bool
    multi_player_production_proven: bool
    authoritative_full_game_core: bool
    blockers: tuple[FormalIdentityBlocker, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "mode_id": self.mode_id,
            "deck_count": self.deck_count,
            "registered_card_key_count": self.registered_card_key_count,
            "registered_instance_count": self.registered_instance_count,
            "global_card_semantics_complete": (
                self.global_card_semantics_complete
            ),
            "mode_runtime_reachable": self.mode_runtime_reachable,
            "mode_implemented": self.mode_implemented,
            "deterministic_controller_implemented": (
                self.deterministic_controller_implemented
            ),
            "reexecution_replay_supported": (
                self.reexecution_replay_supported
            ),
            "unsupported_rules": self.unsupported_rules,
            "approximation_count": self.approximation_count,
            "formal_identity_no_skill_ready": (
                self.formal_identity_no_skill_ready
            ),
            "identity_ready": self.identity_ready,
            "multi_player_production_proven": (
                self.multi_player_production_proven
            ),
            "authoritative_full_game_core": (
                self.authoritative_full_game_core
            ),
            "blockers": [item.to_dict() for item in self.blockers],
        }


def inspect_formal_identity_readiness() -> FormalIdentityReadiness:
    """从当前正式牌堆、注册表与 canonical factory 现场派生身份就绪状态。

    ``identity_ready`` / ``formal_identity_no_skill_ready`` 只表示当前
    C5 formal no-skill five-player standard identity combat scope 具备
    静态正式执行资格。不得解释为 FULL_GAME_READY。
    ``multi_player_production_proven`` 与 ``authoritative_full_game_core``
    保持 false。
    """

    from .production_cards import FormalCardRegistry
    from .production_replay import (
        SUPPORTED_REPLAY_MODES,
        record_reference_production_batch,
        reexecute_production_replay,
    )

    registry = FormalCardRegistry.from_formal_csv()
    registered_keys = frozenset(registry.implemented_card_keys)
    deck_keys = frozenset(record.card_key for record in registry.records)
    global_card_semantics_complete = (
        len(registry.records) == 160
        and len(deck_keys) == 38
        and registered_keys == deck_keys
    )
    blockers: list[FormalIdentityBlocker] = []
    mode_runtime_reachable = False
    try:
        probe = FormalIdentitySession(
            seed=0,
            configuration=FormalIdentityConfiguration.formal_profile(),
            analysis_only=True,
            session_id="formal-identity-readiness-probe",
            session_secret=b"formal-identity-readiness-probe-01",
        )
        state = probe.state
        hand_sizes = tuple(
            len(state.card_ids_in(ZoneRef.hand(player_id)))
            for player_id in probe.numbered_player_order
        )
        roles = [probe.identities_by_player[pid] for pid in probe.physical_player_ids]
        lord_id = probe.lord_player_id
        lord_player = state.players_by_id[lord_id]
        others_hp = [
            state.players_by_id[pid]
            for pid in probe.physical_player_ids
            if pid != lord_id
        ]
        mode_runtime_reachable = (
            probe.mode_id == FORMAL_NO_SKILL_IDENTITY_5P_MODE
            and len(state.cards) == 160
            and len(state.players) == 5
            and hand_sizes == (4, 4, 4, 4, 4)
            and roles.count(StandardIdentityRole.LORD) == 1
            and roles.count(StandardIdentityRole.LOYALIST) == 1
            and roles.count(StandardIdentityRole.REBEL) == 2
            and roles.count(StandardIdentityRole.SPY) == 1
            and lord_player.hp == 5
            and lord_player.max_hp == 5
            and all(player.hp == 4 and player.max_hp == 4 for player in others_hp)
            and probe.first_player_id == lord_id
            and probe.numbered_player_order[0] == lord_id
            and probe.seat_by_player[lord_id] == 1
            and probe.deck_supply_mode == "reshuffle_draw"
            and probe.outcome_policy is not None
            and probe.outcome_policy.identity()
            == "outcome:formal_no_skill_identity_5p"
            and probe.runtime.phase is ProductionPhase.PREPARE
        )
    except Exception as exc:  # pragma: no cover
        blockers.append(
            FormalIdentityBlocker(
                "FORMAL_IDENTITY_FACTORY_UNREACHABLE",
                "MODE_GAP",
                f"正式身份 canonical factory 现场自检失败："
                f"{type(exc).__name__}:{exc}",
            )
        )
    if not mode_runtime_reachable:
        blockers.append(
            FormalIdentityBlocker(
                "FORMAL_IDENTITY_RUNTIME_NOT_REACHABLE",
                "MODE_GAP",
                "正式身份模式不能从canonical factory到达统一生产核心",
            )
        )
    formal_runtime_reachable = False
    formal_runtime_error: str | None = None
    try:
        formal_configuration = FormalIdentityConfiguration.formal_profile()
        formal_probe = FormalIdentitySession(
            seed=0,
            configuration=formal_configuration,
            analysis_only=False,
            session_id="formal-identity-trusted-readiness-probe",
            session_secret=b"formal-identity-trusted-probe-01",
        )
        formal_runtime_reachable = (
            formal_probe.analysis_only is False
            and formal_probe.formal_configuration is formal_configuration
            and formal_probe.formal_result_eligible is True
        )
    except Exception as exc:
        formal_runtime_error = f"{type(exc).__name__}:{exc}"
    if not formal_runtime_reachable:
        detail = (
            f"：{formal_runtime_error}"
            if formal_runtime_error is not None
            else "：canonical formal session 未取得正式结果资格"
        )
        blockers.append(
            FormalIdentityBlocker(
                "FORMAL_IDENTITY_TRUSTED_RUNTIME_UNREACHABLE",
                "MODE_GAP",
                "正式身份 analysis_only=False trusted path 现场自检失败"
                f"{detail}",
            )
        )
    if not global_card_semantics_complete:
        blockers.append(
            FormalIdentityBlocker(
                "FORMAL_IDENTITY_CARD_SEMANTICS_INCOMPLETE",
                "CARD_GAP",
                "正式身份依赖C2全局卡牌语义闭合（38/38），当前不满足",
            )
        )
    replay_supported = (
        callable(record_reference_production_batch)
        and callable(reexecute_production_replay)
        and FORMAL_NO_SKILL_IDENTITY_5P_MODE in SUPPORTED_REPLAY_MODES
    )
    if not replay_supported:
        blockers.append(
            FormalIdentityBlocker(
                "FORMAL_IDENTITY_REPLAY_UNSUPPORTED",
                "MODE_GAP",
                "严格回放不支持正式身份模式",
            )
        )
    unsupported_rules = len(blockers)
    # C5 没有另设 approximation/controller registry：前者是 canonical
    # no-skill scope 的 declarative invariant；后者由统一生产核心提供。
    # 两者都不能替代上面的 analysis-only 与 formal trusted runtime probes。
    approximation_count = 0
    mode_implemented = (
        mode_runtime_reachable and formal_runtime_reachable and not blockers
    )
    ready = (
        mode_implemented
        and formal_runtime_reachable
        and replay_supported
        and global_card_semantics_complete
        and unsupported_rules == 0
        and approximation_count == 0
    )
    return FormalIdentityReadiness(
        mode_id=FORMAL_NO_SKILL_IDENTITY_5P_MODE,
        deck_count=registry.card_count,
        registered_card_key_count=len(registered_keys),
        registered_instance_count=len(registry.records),
        global_card_semantics_complete=global_card_semantics_complete,
        mode_runtime_reachable=mode_runtime_reachable,
        mode_implemented=mode_implemented,
        deterministic_controller_implemented=True,
        reexecution_replay_supported=replay_supported,
        unsupported_rules=unsupported_rules,
        approximation_count=approximation_count,
        formal_identity_no_skill_ready=ready,
        identity_ready=ready,
        multi_player_production_proven=False,
        authoritative_full_game_core=False,
        blockers=tuple(blockers),
    )


@dataclass(frozen=True, slots=True)
class FormalEightPlayerIdentityReadiness:
    """C6 普通八人 formal combat 静态就绪状态；不是独立审计结论。"""

    contract_id: str
    mode_id: str
    deck_count: int
    registered_card_key_count: int
    registered_instance_count: int
    global_card_semantics_complete: bool
    mode_runtime_reachable: bool
    formal_trusted_runtime_reachable: bool
    mode_implemented: bool
    deterministic_controller_implemented: bool
    reexecution_replay_supported: bool
    unsupported_rules: int
    approximation_count: int
    formal_eight_player_identity_no_skill_ready: bool
    identity_8p_ready: bool
    multi_player_production_proven: bool
    authoritative_full_game_core: bool
    blockers: tuple[FormalIdentityBlocker, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "contract_id": self.contract_id,
            "mode_id": self.mode_id,
            "deck_count": self.deck_count,
            "registered_card_key_count": self.registered_card_key_count,
            "registered_instance_count": self.registered_instance_count,
            "global_card_semantics_complete": (
                self.global_card_semantics_complete
            ),
            "mode_runtime_reachable": self.mode_runtime_reachable,
            "formal_trusted_runtime_reachable": (
                self.formal_trusted_runtime_reachable
            ),
            "mode_implemented": self.mode_implemented,
            "deterministic_controller_implemented": (
                self.deterministic_controller_implemented
            ),
            "reexecution_replay_supported": (
                self.reexecution_replay_supported
            ),
            "unsupported_rules": self.unsupported_rules,
            "approximation_count": self.approximation_count,
            "formal_eight_player_identity_no_skill_ready": (
                self.formal_eight_player_identity_no_skill_ready
            ),
            "identity_8p_ready": self.identity_8p_ready,
            "multi_player_production_proven": (
                self.multi_player_production_proven
            ),
            "authoritative_full_game_core": (
                self.authoritative_full_game_core
            ),
            "blockers": [item.to_dict() for item in self.blockers],
        }


def inspect_formal_eight_player_identity_readiness() -> (
    FormalEightPlayerIdentityReadiness
):
    """现场 probe C6 analysis 与 canonical trusted 两条路径。

    ready 只表示 C6 ordinary-eight-player formal no-skill identity combat
    scope 的静态执行资格；``multi_player_production_proven`` 与
    ``authoritative_full_game_core`` 必须继续为 false。
    """

    from .production_cards import FormalCardRegistry
    from .production_replay import (
        SUPPORTED_REPLAY_MODES,
        record_reference_formal_eight_player_identity,
        reexecute_production_replay,
    )

    registry = FormalCardRegistry.from_formal_csv()
    registered_keys = frozenset(registry.implemented_card_keys)
    deck_keys = frozenset(record.card_key for record in registry.records)
    global_card_semantics_complete = (
        len(registry.records) == 160
        and len(deck_keys) == 38
        and registered_keys == deck_keys
    )
    blockers: list[FormalIdentityBlocker] = []
    mode_runtime_reachable = False
    try:
        probe = FormalEightPlayerIdentitySession(
            seed=0,
            configuration=(
                FormalEightPlayerIdentityConfiguration.formal_profile()
            ),
            analysis_only=True,
            session_id="formal-identity-8p-readiness-probe",
            session_secret=b"formal-identity-8p-readiness-probe-01",
        )
        state = probe.state
        hand_sizes = tuple(
            len(state.card_ids_in(ZoneRef.hand(player_id)))
            for player_id in probe.numbered_player_order
        )
        roles = [
            probe.identities_by_player[player_id]
            for player_id in probe.physical_player_ids
        ]
        lord_id = probe.lord_player_id
        lord_player = state.players_by_id[lord_id]
        others_hp = [
            state.players_by_id[player_id]
            for player_id in probe.physical_player_ids
            if player_id != lord_id
        ]
        mode_runtime_reachable = (
            probe.mode_id == FORMAL_NO_SKILL_IDENTITY_8P_MODE
            and len(state.cards) == 160
            and len(state.players) == 8
            and len(state.card_ids_in(DRAW_PILE)) == 128
            and hand_sizes == (4, 4, 4, 4, 4, 4, 4, 4)
            and roles.count(StandardIdentityRole.LORD) == 1
            and roles.count(StandardIdentityRole.LOYALIST) == 2
            and roles.count(StandardIdentityRole.REBEL) == 4
            and roles.count(StandardIdentityRole.SPY) == 1
            and lord_player.hp == 5
            and lord_player.max_hp == 5
            and all(
                player.hp == 4 and player.max_hp == 4
                for player in others_hp
            )
            and probe.first_player_id == lord_id
            and probe.numbered_player_order[0] == lord_id
            and probe.seat_by_player[lord_id] == 1
            and probe.deck_supply_mode == "reshuffle_draw"
            and probe.outcome_policy is not None
            and probe.outcome_policy.identity()
            == "outcome:formal_no_skill_identity_8p"
            and probe.runtime.phase is ProductionPhase.PREPARE
            and len(probe.rng_calls) == 2
            and probe.rng_calls[0].method == "shuffle"
            and probe.rng_calls[1].method == "shuffle"
        )
    except Exception as exc:  # pragma: no cover - readiness 要收敛为 blocker
        blockers.append(
            FormalIdentityBlocker(
                "FORMAL_EIGHT_PLAYER_IDENTITY_FACTORY_UNREACHABLE",
                "MODE_GAP",
                "正式八人身份 canonical factory 现场自检失败："
                f"{type(exc).__name__}:{exc}",
            )
        )
    if not mode_runtime_reachable:
        blockers.append(
            FormalIdentityBlocker(
                "FORMAL_EIGHT_PLAYER_IDENTITY_RUNTIME_NOT_REACHABLE",
                "MODE_GAP",
                "正式八人身份不能从canonical factory到达统一生产核心",
            )
        )

    formal_runtime_reachable = False
    formal_runtime_error: str | None = None
    try:
        formal_configuration = (
            FormalEightPlayerIdentityConfiguration.formal_profile()
        )
        formal_probe = FormalEightPlayerIdentitySession(
            seed=0,
            configuration=formal_configuration,
            analysis_only=False,
            session_id="formal-identity-8p-trusted-readiness-probe",
            session_secret=b"formal-identity-8p-trusted-probe-01",
        )
        formal_runtime_reachable = (
            formal_probe.analysis_only is False
            and formal_probe.formal_configuration is formal_configuration
            and formal_probe.formal_result_eligible is True
        )
    except Exception as exc:
        formal_runtime_error = f"{type(exc).__name__}:{exc}"
    if not formal_runtime_reachable:
        detail = (
            f"：{formal_runtime_error}"
            if formal_runtime_error is not None
            else "：canonical formal session 未取得正式结果资格"
        )
        blockers.append(
            FormalIdentityBlocker(
                "FORMAL_EIGHT_PLAYER_IDENTITY_TRUSTED_RUNTIME_UNREACHABLE",
                "MODE_GAP",
                "正式八人身份 analysis_only=False trusted path 现场自检失败"
                f"{detail}",
            )
        )
    if not global_card_semantics_complete:
        blockers.append(
            FormalIdentityBlocker(
                "FORMAL_EIGHT_PLAYER_IDENTITY_CARD_SEMANTICS_INCOMPLETE",
                "CARD_GAP",
                "正式八人身份依赖38/38全局卡牌语义，当前不满足",
            )
        )
    replay_supported = (
        callable(record_reference_formal_eight_player_identity)
        and callable(reexecute_production_replay)
        and FORMAL_NO_SKILL_IDENTITY_8P_MODE in SUPPORTED_REPLAY_MODES
    )
    if not replay_supported:
        blockers.append(
            FormalIdentityBlocker(
                "FORMAL_EIGHT_PLAYER_IDENTITY_REPLAY_UNSUPPORTED",
                "MODE_GAP",
                "严格回放不支持正式普通八人身份模式",
            )
        )
    unsupported_rules = len(blockers)
    approximation_count = 0
    mode_implemented = (
        mode_runtime_reachable
        and formal_runtime_reachable
        and replay_supported
        and not blockers
    )
    ready = (
        mode_implemented
        and global_card_semantics_complete
        and unsupported_rules == 0
        and approximation_count == 0
    )
    return FormalEightPlayerIdentityReadiness(
        contract_id=POST_B_C6_FORMAL_IDENTITY_CONTRACT_ID,
        mode_id=FORMAL_NO_SKILL_IDENTITY_8P_MODE,
        deck_count=registry.card_count,
        registered_card_key_count=len(registered_keys),
        registered_instance_count=len(registry.records),
        global_card_semantics_complete=global_card_semantics_complete,
        mode_runtime_reachable=mode_runtime_reachable,
        formal_trusted_runtime_reachable=formal_runtime_reachable,
        mode_implemented=mode_implemented,
        deterministic_controller_implemented=True,
        reexecution_replay_supported=replay_supported,
        unsupported_rules=unsupported_rules,
        approximation_count=approximation_count,
        formal_eight_player_identity_no_skill_ready=ready,
        identity_8p_ready=ready,
        multi_player_production_proven=False,
        authoritative_full_game_core=False,
        blockers=tuple(blockers),
    )


__all__ = [
    "C6_CANONICAL_DRAW_REACHABILITY_STATUS",
    "FORMAL_NO_SKILL_IDENTITY_5P_MODE",
    "FORMAL_NO_SKILL_IDENTITY_8P_MODE",
    "POST_B_C6_FORMAL_IDENTITY_CONTRACT_ID",
    "FormalEightPlayerIdentityConfiguration",
    "FormalEightPlayerIdentityReadiness",
    "FormalEightPlayerIdentitySession",
    "FormalIdentityBlocker",
    "FormalIdentityConfiguration",
    "FormalIdentityConfigurationError",
    "FormalIdentityReadiness",
    "FormalIdentitySession",
    "IdentityModePolicy",
    "IdentityOutcomePolicy",
    "StandardIdentityRole",
    "TrustedFormalEightPlayerIdentityConfiguration",
    "TrustedFormalIdentityConfiguration",
    "assert_trusted_formal_eight_player_identity_configuration",
    "assert_trusted_formal_identity_configuration",
    "inspect_formal_eight_player_identity_readiness",
    "inspect_formal_identity_readiness",
]
