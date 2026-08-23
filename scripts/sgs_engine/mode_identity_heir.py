# -*- coding: utf-8 -*-
"""POST-B C7：正式无武将技能八人军争「主公立储与内奸择途」变体层。

本模块不是第三套独立 identity engine。它复用 C5/C6 共享标准身份核心
（同一 ProductionBasicCardBatch、同一会话 RNG、同一死亡/parent-root
管线），只增加第5章变体状态、精确 façade 与 variant policy。

C6 ``FormalEightPlayerIdentityConfiguration`` 仍只表示普通八人；本模块
的 exact configuration / trusted factory / session 与 C6 完全隔离。

internal mode/variant ID 不是官方模式名称。
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields, replace
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping

from .actions import ActionType, LegalAction, VirtualCardReference
from .events import EventType, GameEvent
from .model import (
    CharacterGender,
    CharacterMetadata,
    DRAW_PILE,
    GameState,
    ZoneRef,
)
from .mode_identity import (
    C6_CANONICAL_DRAW_REACHABILITY_STATUS,
    FormalIdentityBlocker,
    FormalIdentityConfigurationError,
    StandardIdentityRole,
    _CANONICAL_EIGHT_PLAYER_IDENTITY_CARDS,
    _CANONICAL_EIGHT_PLAYER_PHYSICAL_PLAYER_IDS,
    _CANONICAL_IDENTITY_TEST_CHARACTER,
    _FORMAL_IDENTITY_EXECUTION_RELEASED,
    _assign_identities,
    _require_exact_int,
    _require_exact_tuple_of_str,
    _strict_canonical_value_equal,
)
from .multiplayer import OutcomePolicy, PlayerTopology
from .production_batch import (
    DeathConfirmationContext,
    ProductionBasicCardBatch,
    ProductionPhase,
)
from .rng import DeterministicRNG

FORMAL_NO_SKILL_IDENTITY_8P_HEIR_MODE = (
    "formal_no_skill_identity_8p_heir_and_spy_choice"
)
MOBILE_8P_HEIR_AND_SPY_CHOICE_VARIANT = "mobile_8p_heir_and_spy_choice"
POST_B_C7_FORMAL_IDENTITY_CONTRACT_ID = (
    'POST_B_C7_FORMAL_NO_SKILL_MOBILE_EIGHT_PLAYER_HEIR_AND_SPY_CHOICE_IDENTITY_MODE'
)
if (
    POST_B_C7_FORMAL_IDENTITY_CONTRACT_ID
    != (
        'POST_B_C7_FORMAL_NO_SKILL_MOBILE_EIGHT_PLAYER_HEIR_AND_SPY_CHOICE_IDENTITY_MODE'
    )
    or len(POST_B_C7_FORMAL_IDENTITY_CONTRACT_ID) != 79
):
    raise FormalIdentityConfigurationError(
        "C7 formal contract ID必须是exact 79字符字面量"
    )
C7_CANONICAL_DRAW_REACHABILITY_STATUS = (
    "C7_CANONICAL_DRAW_REACHABILITY_UNRESOLVED"
)
C7_CONFIGURATION_SCHEMA = (
    "formal-no-skill-identity-8p-heir-and-spy-choice-configuration-v1"
)
C7_DECK_ID = "sgs_mobile_non_special_20260725_unofficial"
_TRUSTED_HEIR_AND_SPY_CHOICE_CAPABILITY = object()

SPY_PATH_LOYALIST = "loyalist"
SPY_PATH_AMBITIONIST = "ambitionist"
_VIRTUAL_AMBITIONIST_PEACH_ID = "virtual:ambitionist_mark_peach"
_AMBITIONIST_MARK_CONVERSION = "ambitionist_mark_virtual_peach"


class HeirAndSpyChoiceRole(str, Enum):
    """C7 当前/开局身份 token。ambitionist 仅出现在 role_current。"""

    LORD = "lord"
    LOYALIST = "loyalist"
    REBEL = "rebel"
    SPY = "spy"
    AMBITIONIST = "ambitionist"


def _require_exact_str(value: object, expected: str, label: str) -> str:
    if type(value) is not str or value != expected:
        raise FormalIdentityConfigurationError(f"{label}必须是{expected!r}")
    return value


def _heir_configuration_profile_value(
    configuration: "FormalHeirAndSpyChoiceIdentityConfiguration",
) -> dict[str, object]:
    return {
        definition.name: getattr(configuration, definition.name)
        for definition in fields(FormalHeirAndSpyChoiceIdentityConfiguration)
    }


@dataclass(frozen=True, slots=True)
class FormalHeirAndSpyChoiceIdentityConfiguration:
    """C7 特殊八人 formal no-skill exact profile。与 C6 八人 schema 隔离。"""

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
    deck_id: str = C7_DECK_ID
    mode_id: str = FORMAL_NO_SKILL_IDENTITY_8P_HEIR_MODE
    variant_id: str = MOBILE_8P_HEIR_AND_SPY_CHOICE_VARIANT

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
                "正式立储择途八人身份场 physical_player_ids 必须是 "
                "('p1','p2','p3','p4','p5','p6','p7','p8')"
            )
        cards = _require_exact_tuple_of_str(
            self.identity_cards, 8, "identity_cards"
        )
        if tuple(sorted(cards)) != tuple(
            sorted(_CANONICAL_EIGHT_PLAYER_IDENTITY_CARDS)
        ):
            raise FormalIdentityConfigurationError(
                "正式立储择途八人身份牌必须恰好为1主公、2忠臣、4反贼、1内奸"
            )
        if cards.count("lord") != 1 or cards.count("loyalist") != 2:
            raise FormalIdentityConfigurationError(
                "正式立储择途八人身份牌必须恰好1主公与2忠臣"
            )
        if cards.count("rebel") != 4 or cards.count("spy") != 1:
            raise FormalIdentityConfigurationError(
                "正式立储择途八人身份牌必须恰好4反贼与1内奸"
            )
        if "ambitionist" in cards:
            raise FormalIdentityConfigurationError(
                "开局身份牌不得包含野心家；野心家只能由内奸择途正式转化产生"
            )
        _require_exact_int(self.base_hp, 4, "base_hp")
        _require_exact_int(self.base_max_hp, 4, "base_max_hp")
        _require_exact_int(self.lord_hp, 5, "lord_hp")
        _require_exact_int(self.lord_max_hp, 5, "lord_max_hp")
        _require_exact_int(self.initial_hand_count, 4, "initial_hand_count")
        if type(self.hand_qi_ka_allowed) is not bool or self.hand_qi_ka_allowed:
            raise FormalIdentityConfigurationError(
                "正式立储择途八人身份场禁止手气卡"
            )
        _require_exact_str(
            self.deck_supply_mode, "reshuffle_draw", "deck_supply_mode"
        )
        _require_exact_str(self.deck_id, C7_DECK_ID, "deck_id")
        _require_exact_str(
            self.mode_id, FORMAL_NO_SKILL_IDENTITY_8P_HEIR_MODE, "mode_id"
        )
        _require_exact_str(
            self.variant_id,
            MOBILE_8P_HEIR_AND_SPY_CHOICE_VARIANT,
            "variant_id",
        )
        object.__setattr__(self, "physical_player_ids", physical)
        object.__setattr__(self, "identity_cards", cards)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": C7_CONFIGURATION_SCHEMA,
            "physical_player_ids": list(self.physical_player_ids),
            "identity_cards": list(self.identity_cards),
            "base_hp": self.base_hp,
            "base_max_hp": self.base_max_hp,
            "lord_hp": self.lord_hp,
            "lord_max_hp": self.lord_max_hp,
            "initial_hand_count": self.initial_hand_count,
            "hand_qi_ka_allowed": self.hand_qi_ka_allowed,
            "deck_supply_mode": self.deck_supply_mode,
            "deck_id": self.deck_id,
            "mode_id": self.mode_id,
            "variant_id": self.variant_id,
        }

    @classmethod
    def from_dict(
        cls, value: Mapping[str, object]
    ) -> "FormalHeirAndSpyChoiceIdentityConfiguration":
        if cls is not FormalHeirAndSpyChoiceIdentityConfiguration:
            raise FormalIdentityConfigurationError(
                "正式立储择途配置解析禁止通过子类改变exact dataclass type"
            )
        if type(value) is not dict:
            raise FormalIdentityConfigurationError(
                "正式立储择途配置必须是exact JSON对象，禁止dict子类"
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
            "deck_id",
            "mode_id",
            "variant_id",
        }
        if set(value) != expected_fields:
            raise FormalIdentityConfigurationError(
                "正式立储择途配置字段集不合法"
            )
        if (
            type(value["schema"]) is not str
            or value["schema"] != C7_CONFIGURATION_SCHEMA
        ):
            raise FormalIdentityConfigurationError(
                "正式立储择途配置schema不受支持"
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
            deck_id=value["deck_id"],  # type: ignore[arg-type]
            mode_id=value["mode_id"],  # type: ignore[arg-type]
            variant_id=value["variant_id"],  # type: ignore[arg-type]
        )

    @staticmethod
    def formal_profile() -> "TrustedFormalHeirAndSpyChoiceIdentityConfiguration":
        """C7 canonical trusted profile 的唯一正式来源。"""

        return _canonical_formal_heir_and_spy_choice_profile_value()

    @classmethod
    def from_canonical_profile_value(
        cls, value: Mapping[str, object]
    ) -> "FormalHeirAndSpyChoiceIdentityConfiguration":
        if cls is not FormalHeirAndSpyChoiceIdentityConfiguration:
            raise FormalIdentityConfigurationError(
                "正式立储择途 canonical 解析禁止子类旁路"
            )
        canonical = cls.formal_profile()
        if not _strict_canonical_value_equal(value, canonical.to_dict()):
            raise FormalIdentityConfigurationError(
                "正式立储择途配置必须与项目 canonical formal profile "
                "递归exact-type完全一致；payload不能自行获得可信规则来源"
            )
        return canonical


@dataclass(frozen=True, slots=True)
class TrustedFormalHeirAndSpyChoiceIdentityConfiguration(
    FormalHeirAndSpyChoiceIdentityConfiguration
):
    """仅由模块内 C7 canonical factory 构造的 trusted 配置。"""

    _capability_token: object | None = field(
        default=None,
        init=False,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        FormalHeirAndSpyChoiceIdentityConfiguration.__post_init__(self)

    def __copy__(self) -> "TrustedFormalHeirAndSpyChoiceIdentityConfiguration":
        return replace(self)

    def __deepcopy__(
        self, memo: dict[int, object]
    ) -> "TrustedFormalHeirAndSpyChoiceIdentityConfiguration":
        del memo
        return replace(self)


def _canonical_formal_heir_and_spy_choice_profile_value() -> (
    "TrustedFormalHeirAndSpyChoiceIdentityConfiguration"
):
    configuration = TrustedFormalHeirAndSpyChoiceIdentityConfiguration(
        physical_player_ids=_CANONICAL_EIGHT_PLAYER_PHYSICAL_PLAYER_IDS,
        identity_cards=_CANONICAL_EIGHT_PLAYER_IDENTITY_CARDS,
        base_hp=4,
        base_max_hp=4,
        lord_hp=5,
        lord_max_hp=5,
        initial_hand_count=4,
        hand_qi_ka_allowed=False,
        deck_supply_mode="reshuffle_draw",
        deck_id=C7_DECK_ID,
        mode_id=FORMAL_NO_SKILL_IDENTITY_8P_HEIR_MODE,
        variant_id=MOBILE_8P_HEIR_AND_SPY_CHOICE_VARIANT,
    )
    object.__setattr__(
        configuration,
        "_capability_token",
        _TRUSTED_HEIR_AND_SPY_CHOICE_CAPABILITY,
    )
    return configuration


def assert_trusted_formal_heir_and_spy_choice_identity_configuration(
    configuration: FormalHeirAndSpyChoiceIdentityConfiguration,
) -> None:
    """C7 trusted authority：exact type + private capability + exact value。"""

    if not isinstance(
        configuration, FormalHeirAndSpyChoiceIdentityConfiguration
    ):
        raise TypeError(
            "正式立储择途会话必须接收"
            "FormalHeirAndSpyChoiceIdentityConfiguration"
        )
    if type(configuration) is not (
        TrustedFormalHeirAndSpyChoiceIdentityConfiguration
    ):
        raise FormalIdentityConfigurationError(
            "正式立储择途结果只接受内部 canonical factory 返回的 "
            "TrustedFormalHeirAndSpyChoiceIdentityConfiguration"
            "（exact type 校验）"
        )
    if (
        getattr(configuration, "_capability_token", None)
        is not _TRUSTED_HEIR_AND_SPY_CHOICE_CAPABILITY
    ):
        raise FormalIdentityConfigurationError(
            "正式立储择途结果只接受真实持有模块私有 capability token 的 "
            "TrustedFormalHeirAndSpyChoiceIdentityConfiguration"
        )
    canonical = _canonical_formal_heir_and_spy_choice_profile_value()
    if not _strict_canonical_value_equal(
        _heir_configuration_profile_value(configuration),
        _heir_configuration_profile_value(canonical),
    ):
        raise FormalIdentityConfigurationError(
            "正式立储择途配置必须递归 exact-type 等于项目 canonical profile；"
            "type/token正确但值非canonical的对象同样失败关闭"
        )


def _parse_heir_role(value: object, player_id: str) -> HeirAndSpyChoiceRole:
    if type(value) is HeirAndSpyChoiceRole:
        return value
    if type(value) is not str:
        raise FormalIdentityConfigurationError(
            f"角色{player_id!r}的身份必须是canonical字符串，不能用其他类型伪装"
        )
    try:
        return HeirAndSpyChoiceRole(value)
    except ValueError as exc:
        raise FormalIdentityConfigurationError(
            f"角色{player_id!r}的身份{value!r}不是立储择途身份"
        ) from exc


@dataclass
class HeirAndSpyChoiceVariantState:
    """C7 可变变体状态。不进入 C6 配置，也不作为公开 header 字段。"""

    original_lord_player_id: str
    current_lord_player_id: str
    role_original: dict[str, str]
    role_current: dict[str, str]
    heir_player_id: str | None = None
    heir_selection_used: bool = False
    heir_window_open: bool = True
    spy_path_choice: str | None = None
    spy_path_pending: bool = False
    spy_path_locked: bool = False
    spy_path_chooser_id: str | None = None
    lord_or_loyalist_confirmed_dead: bool = False
    ambitionist_mark_available: dict[str, bool] = field(default_factory=dict)
    spy_became_loyalist_announced: bool = False
    converted_loyalist_ids: tuple[str, ...] = ()
    round_number: int = 1
    normal_turn_cycle: int = 0
    is_extra_turn: bool = False
    players_had_normal_turn_this_round: tuple[str, ...] = ()
    successor_cannot_select_heir: bool = False


@dataclass(frozen=True, slots=True)
class HeirAndSpyChoiceOutcomePolicy(OutcomePolicy):
    """C7 胜负：使用 role_current 与 current_lord_player_id。"""

    identities: Mapping[str, HeirAndSpyChoiceRole] = MappingProxyType({})
    current_lord_player_id: str = ""

    def __init__(
        self,
        identities: Mapping[str, str | HeirAndSpyChoiceRole],
        current_lord_player_id: str,
    ) -> None:
        if not isinstance(identities, Mapping):
            raise FormalIdentityConfigurationError(
                "立储择途胜负策略需要角色→身份映射"
            )
        if type(current_lord_player_id) is not str or not current_lord_player_id:
            raise FormalIdentityConfigurationError(
                "current_lord_player_id必须是非空字符串"
            )
        parsed: dict[str, HeirAndSpyChoiceRole] = {}
        for player_id, raw_role in identities.items():
            if type(player_id) is not str or not player_id.strip():
                raise FormalIdentityConfigurationError(
                    "身份映射的角色ID必须是非空字符串"
                )
            parsed[player_id] = _parse_heir_role(raw_role, player_id)
        if current_lord_player_id not in parsed:
            raise FormalIdentityConfigurationError(
                "current_lord_player_id未出现在身份映射中"
            )
        object.__setattr__(
            self, "policy_id", FORMAL_NO_SKILL_IDENTITY_8P_HEIR_MODE
        )
        object.__setattr__(self, "identities", MappingProxyType(parsed))
        object.__setattr__(
            self, "current_lord_player_id", current_lord_player_id
        )

    def role_of(self, player_id: str) -> HeirAndSpyChoiceRole:
        role = self.identities.get(player_id)
        if role is None:
            raise FormalIdentityConfigurationError(
                f"角色{player_id!r}未注册立储择途身份"
            )
        return role

    def resolve_winner_after_death(
        self, topology: PlayerTopology, dying_id: str
    ) -> str | None:
        del dying_id
        alive_ids = [
            player.player_id
            for player in topology.players
            if player.alive
        ]
        lord_id = self.current_lord_player_id
        lord_alive = lord_id in alive_ids
        living_roles = [self.role_of(player_id) for player_id in alive_ids]
        rebel_alive = HeirAndSpyChoiceRole.REBEL in living_roles
        spy_alive = HeirAndSpyChoiceRole.SPY in living_roles
        ambitionist_alive = HeirAndSpyChoiceRole.AMBITIONIST in living_roles
        if lord_alive:
            if not rebel_alive and not spy_alive and not ambitionist_alive:
                return "lord_and_loyalists"
            return None
        others = [player_id for player_id in alive_ids if player_id != lord_id]
        if (
            len(others) == 1
            and self.role_of(others[0]) is HeirAndSpyChoiceRole.SPY
        ):
            return "spy"
        if (
            len(others) == 1
            and self.role_of(others[0]) is HeirAndSpyChoiceRole.AMBITIONIST
        ):
            return "ambitionist"
        return "rebels"

    @property
    def finish_reason(self) -> str:
        return "identity_victory"

    @property
    def draw_finish_reason(self) -> str:
        return "identity_draw_deck_exhausted"


def _alive_count(state: GameState) -> int:
    return sum(1 for player in state.players if player.alive)


def _variant_of(session: object) -> HeirAndSpyChoiceVariantState:
    variant = getattr(session, "_variant", None)
    if not isinstance(variant, HeirAndSpyChoiceVariantState):
        raise FormalIdentityConfigurationError("C7会话缺少变体状态")
    return variant


@dataclass(frozen=True, slots=True)
class HeirAndSpyChoiceModePolicy:
    """C7 variant policy：初始化常量 + 对 session._variant 的钩子。"""

    configuration: FormalHeirAndSpyChoiceIdentityConfiguration
    numbered_player_order: tuple[str, ...]
    original_lord_player_id: str
    physical_player_ids: tuple[str, ...]
    seat_by_player: Mapping[str, int]
    mode_id: str
    variant_id: str
    _variant: HeirAndSpyChoiceVariantState = field(compare=False, repr=False)
    _session_ref: object | None = field(default=None, compare=False, repr=False)

    def __init__(
        self,
        configuration: FormalHeirAndSpyChoiceIdentityConfiguration,
        numbered_player_order: tuple[str, ...],
        original_lord_player_id: str,
        variant: HeirAndSpyChoiceVariantState,
    ) -> None:
        if type(numbered_player_order) is not tuple or len(
            numbered_player_order
        ) != 8:
            raise FormalIdentityConfigurationError(
                "numbered_player_order必须是8名角色的元组"
            )
        physical = configuration.physical_player_ids
        if set(numbered_player_order) != set(physical):
            raise FormalIdentityConfigurationError(
                "numbered_player_order必须恰好覆盖全部 physical_player_ids"
            )
        if numbered_player_order[0] != original_lord_player_id:
            raise FormalIdentityConfigurationError(
                "numbered_player_order必须以开局主公为座次1"
            )
        lord_index = physical.index(original_lord_player_id)
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
        object.__setattr__(self, "numbered_player_order", numbered_player_order)
        object.__setattr__(
            self, "original_lord_player_id", original_lord_player_id
        )
        object.__setattr__(self, "physical_player_ids", physical)
        object.__setattr__(self, "seat_by_player", MappingProxyType(seats))
        object.__setattr__(self, "mode_id", FORMAL_NO_SKILL_IDENTITY_8P_HEIR_MODE)
        object.__setattr__(
            self, "variant_id", MOBILE_8P_HEIR_AND_SPY_CHOICE_VARIANT
        )
        object.__setattr__(self, "_variant", variant)
        object.__setattr__(self, "_session_ref", None)

    @property
    def identity(self) -> str:
        return f"mode:{self.mode_id}"

    @property
    def lord_player_id(self) -> str:
        return self.original_lord_player_id

    @property
    def current_lord_player_id(self) -> str:
        return self._variant.current_lord_player_id

    @property
    def identities(self) -> Mapping[str, HeirAndSpyChoiceRole]:
        return MappingProxyType(
            {
                player_id: HeirAndSpyChoiceRole(role)
                for player_id, role in self._variant.role_current.items()
            }
        )

    @property
    def initial_hand_counts(self) -> tuple[int, ...]:
        count = self.configuration.initial_hand_count
        return tuple(count for _ in self.physical_player_ids)

    @property
    def first_player_id(self) -> str:
        return self.original_lord_player_id

    @property
    def deck_supply_mode(self) -> str:
        return self.configuration.deck_supply_mode

    def role_of(self, player_id: str) -> HeirAndSpyChoiceRole:
        role = self._variant.role_current.get(player_id)
        if role is None:
            raise FormalIdentityConfigurationError(
                f"角色{player_id!r}未注册立储择途当前身份"
            )
        return HeirAndSpyChoiceRole(role)

    def identities_as_str(self) -> dict[str, str]:
        return dict(self._variant.role_current)

    def _ambitionist_skills_active(self, state: GameState, player_id: str) -> bool:
        if self.role_of(player_id) is not HeirAndSpyChoiceRole.AMBITIONIST:
            return False
        player = state.players_by_id.get(player_id)
        if player is None or not player.alive:
            return False
        return _alive_count(state) >= 3

    def feiyang_available(
        self, *, player_id: str, seat: int, turn_number: int
    ) -> bool:
        del seat, turn_number
        session = getattr(self, "_session_ref", None)
        if session is None:
            return False
        return self._ambitionist_skills_active(session.state, player_id)

    def bahu_prepare_draw(self, player_id: str) -> bool:
        session = getattr(self, "_session_ref", None)
        if session is None:
            return False
        return self._ambitionist_skills_active(session.state, player_id)

    def slash_limit(self, player_id: str) -> int:
        session = getattr(self, "_session_ref", None)
        if session is None:
            return 1
        if self._ambitionist_skills_active(session.state, player_id):
            return 2
        return 1

    def bind_session(self, session: object) -> None:
        object.__setattr__(self, "_session_ref", session)

    def identity_reveal_on_confirmed_death(
        self, dying_id: str
    ) -> GameEvent | None:
        role = self.role_of(dying_id)
        if role is HeirAndSpyChoiceRole.LORD:
            return None
        if role is HeirAndSpyChoiceRole.AMBITIONIST:
            return None
        return GameEvent(
            event_type=EventType.IDENTITY_REVEALED,
            target_ids=(dying_id,),
            payload={
                "reason": "confirmed_death",
                "identity": role.value,
            },
        )

    def legal_heir_id(self, state: GameState) -> str | None:
        variant = self._variant
        heir_id = variant.heir_player_id
        if heir_id is None:
            return None
        heir = state.players_by_id.get(heir_id)
        if heir is None or not heir.alive:
            return None
        if self.role_of(heir_id) is not HeirAndSpyChoiceRole.LOYALIST:
            return None
        return heir_id

    def heir_window_available(self, state: GameState) -> bool:
        variant = self._variant
        if not variant.heir_window_open or variant.heir_selection_used:
            return False
        if variant.successor_cannot_select_heir:
            return False
        lord_id = variant.original_lord_player_id
        lord = state.players_by_id.get(lord_id)
        return lord is not None and lord.alive

    def spy_path_chooser_id(self, state: GameState) -> str | None:
        variant = self._variant
        if variant.spy_path_locked:
            return None
        for player_id, role in variant.role_current.items():
            if role != HeirAndSpyChoiceRole.SPY.value:
                continue
            player = state.players_by_id.get(player_id)
            if player is None or not player.alive:
                continue
            if _alive_count(state) <= 4:
                return None
            if not variant.lord_or_loyalist_confirmed_dead:
                return None
            return player_id
        return None

    def extra_play_actions(
        self,
        session: object,
        state: GameState,
        context: object,
    ) -> tuple[LegalAction, ...]:
        actor_id = getattr(context, "actor_id", None)
        if type(actor_id) is not str:
            return ()
        actions: list[LegalAction] = []
        if (
            self.heir_window_available(state)
            and actor_id == self._variant.original_lord_player_id
        ):
            actions.extend(self._heir_select_actions(state, actor_id))
        spy_id = self.spy_path_chooser_id(state)
        if spy_id is not None and actor_id == spy_id:
            actions.extend(self._spy_path_actions(actor_id))
        if (
            self.role_of(actor_id) is HeirAndSpyChoiceRole.AMBITIONIST
            and self._variant.ambitionist_mark_available.get(actor_id, False)
        ):
            player = state.players_by_id[actor_id]
            if player.hp < player.max_hp:
                actions.append(
                    LegalAction(
                        action_type=ActionType.USE_CARD,
                        actor_id=actor_id,
                        card_instance_id=_VIRTUAL_AMBITIONIST_PEACH_ID,
                        virtual_card=VirtualCardReference(
                            card_key="sgs_basic_tao",
                            conversion_rule_id=_AMBITIONIST_MARK_CONVERSION,
                            material_card_instance_ids=(),
                        ),
                        target_ids=(actor_id,),
                        skill_id="ambitionist_mark",
                        payload={
                            "operation": "heal_self",
                            "card_key": "sgs_basic_tao",
                            "card_name": "桃",
                            "virtual": True,
                            "source": "ambitionist_mark",
                        },
                    )
                )
            actions.append(
                LegalAction(
                    action_type=ActionType.ACTIVATE_SKILL,
                    actor_id=actor_id,
                    skill_id="ambitionist_mark_draw_two",
                    payload={
                        "operation": "ambitionist_mark_draw_two",
                    },
                )
            )
        del session
        return tuple(actions)

    def extra_rescue_actions(
        self,
        session: object,
        state: GameState,
        context: object,
        dying_id: str,
    ) -> tuple[LegalAction, ...]:
        del session
        actor_id = getattr(context, "actor_id", None)
        if type(actor_id) is not str:
            return ()
        if self.role_of(actor_id) is not HeirAndSpyChoiceRole.AMBITIONIST:
            return ()
        if not self._variant.ambitionist_mark_available.get(actor_id, False):
            return ()
        return (
            LegalAction(
                action_type=ActionType.USE_CARD,
                actor_id=actor_id,
                card_instance_id=_VIRTUAL_AMBITIONIST_PEACH_ID,
                virtual_card=VirtualCardReference(
                    card_key="sgs_basic_tao",
                    conversion_rule_id=_AMBITIONIST_MARK_CONVERSION,
                    material_card_instance_ids=(),
                ),
                target_ids=(dying_id,),
                skill_id="ambitionist_mark",
                payload={
                    "operation": "rescue_with_peach",
                    "card_key": "sgs_basic_tao",
                    "card_name": "桃",
                    "virtual": True,
                    "source": "ambitionist_mark",
                },
            ),
        )

    def extra_mode_decision_actions(
        self, state: GameState, actor_id: str
    ) -> tuple[LegalAction, ...]:
        actions: list[LegalAction] = []
        if (
            self.heir_window_available(state)
            and actor_id == self._variant.original_lord_player_id
        ):
            actions.extend(self._heir_select_actions(state, actor_id))
        spy_id = self.spy_path_chooser_id(state)
        if spy_id is not None and actor_id == spy_id:
            actions.extend(self._spy_path_actions(actor_id))
        actions.append(
            LegalAction(
                action_type=ActionType.PASS,
                actor_id=actor_id,
                payload={"operation": "pass_mode_decision"},
            )
        )
        return tuple(actions)

    def _heir_select_actions(
        self, state: GameState, actor_id: str
    ) -> tuple[LegalAction, ...]:
        actions: list[LegalAction] = []
        for player in state.players:
            if not player.alive or player.player_id == actor_id:
                continue
            actions.append(
                LegalAction(
                    action_type=ActionType.CHOOSE_OPTION,
                    actor_id=actor_id,
                    target_ids=(player.player_id,),
                    payload={
                        "operation": "select_heir",
                        "target_id": player.player_id,
                    },
                )
            )
        return tuple(actions)

    def _spy_path_actions(self, actor_id: str) -> tuple[LegalAction, ...]:
        return (
            LegalAction(
                action_type=ActionType.CHOOSE_OPTION,
                actor_id=actor_id,
                payload={
                    "operation": "choose_spy_path",
                    "path": SPY_PATH_LOYALIST,
                },
            ),
            LegalAction(
                action_type=ActionType.CHOOSE_OPTION,
                actor_id=actor_id,
                payload={
                    "operation": "choose_spy_path",
                    "path": SPY_PATH_AMBITIONIST,
                },
            ),
        )

    def on_turn_start(
        self,
        session: object,
        state: GameState,
        runtime: object,
        *,
        is_extra_turn: bool,
    ) -> tuple[GameState, object]:
        variant = self._variant
        current_player_id = getattr(runtime, "current_player_id")
        variant.is_extra_turn = bool(is_extra_turn)
        if not is_extra_turn:
            had = variant.players_had_normal_turn_this_round
            if current_player_id in had:
                variant.round_number += 1
                had = ()
                if variant.round_number >= 2:
                    variant.heir_window_open = False
            variant.players_had_normal_turn_this_round = had + (
                current_player_id,
            )
            variant.normal_turn_cycle = len(
                variant.players_had_normal_turn_this_round
            )
        state, runtime = self._apply_pending_spy_conversion(
            session, state, runtime
        )
        if getattr(runtime, "game_over_reason", None) is not None:
            return state, runtime
        if getattr(runtime, "winner_id", None) is not None:
            return state, runtime
        queue = self._mode_decision_queue(state, current_player_id)
        if queue:
            open_window = getattr(session, "_open_c7_mode_decision")
            runtime = open_window(runtime, queue)
        return state, runtime

    def _mode_decision_queue(
        self, state: GameState, current_player_id: str
    ) -> tuple[str, ...]:
        del current_player_id
        queue: list[str] = []
        if self.heir_window_available(state):
            queue.append(self._variant.original_lord_player_id)
        spy_id = self.spy_path_chooser_id(state)
        if spy_id is not None and spy_id not in queue:
            queue.append(spy_id)
        return tuple(queue)

    def _apply_pending_spy_conversion(
        self,
        session: object,
        state: GameState,
        runtime: object,
    ) -> tuple[GameState, object]:
        variant = self._variant
        if not variant.spy_path_pending or not variant.spy_path_locked:
            return state, runtime
        chooser_id = variant.spy_path_chooser_id
        if chooser_id is None:
            variant.spy_path_pending = False
            return state, runtime
        chooser = state.players_by_id.get(chooser_id)
        if chooser is None or not chooser.alive:
            variant.spy_path_pending = False
            variant.spy_path_choice = None
            return state, runtime
        if getattr(runtime, "winner_id", None) is not None:
            variant.spy_path_pending = False
            return state, runtime
        path = variant.spy_path_choice
        apply_fn = getattr(session, "_apply_c7_spy_conversion")
        return apply_fn(state, runtime, chooser_id, path)

    def pre_confirmed_death_hook(
        self,
        session: object,
        state: GameState,
        runtime: object,
        dying_id: str,
    ) -> tuple[GameState, object]:
        if dying_id != self._variant.current_lord_player_id:
            return state, runtime
        heir_id = self.legal_heir_id(state)
        if heir_id is None:
            return state, runtime
        open_window = getattr(session, "_open_c7_succession_window")
        return open_window(state, runtime, dying_id, heir_id)

    def post_confirmed_death_pre_outcome_hook(
        self,
        session: object,
        state: GameState,
        runtime: object,
        dying_id: str,
    ) -> tuple[GameState, object]:
        variant = self._variant
        dying = state.players_by_id[dying_id]
        role = self.role_of(dying_id)
        if (
            role is HeirAndSpyChoiceRole.LORD
            or role is HeirAndSpyChoiceRole.LOYALIST
        ):
            variant.lord_or_loyalist_confirmed_dead = True
        if variant.heir_player_id != dying_id:
            return state, runtime
        variant.heir_player_id = None
        lord_id = variant.current_lord_player_id
        lord = state.players_by_id.get(lord_id)
        if lord is None or not lord.alive:
            return state, runtime
        lose_hp = getattr(session, "_apply_c7_lose_hp")
        return lose_hp(
            state,
            runtime,
            lord_id,
            amount=1,
            reason="heir_confirmed_death",
            outer_dying_id=dying_id,
        )

    def death_confirmed_hook(
        self,
        session: object,
        state: GameState,
        runtime: object,
        dying_id: str,
        death_context: object | None = None,
    ) -> tuple[GameState, object]:
        if not isinstance(death_context, DeathConfirmationContext):
            raise FormalIdentityConfigurationError(
                "正式立储择途死亡确认钩子需要明确的DeathConfirmationContext"
            )
        if death_context.dying_id != dying_id:
            raise FormalIdentityConfigurationError(
                "死亡确认上下文的dying_id与当前死亡角色不一致"
            )
        credit = death_context.kill_credit
        role = self.role_of(dying_id)
        if role is HeirAndSpyChoiceRole.AMBITIONIST:
            return state, runtime
        if credit is not None:
            killer_role = self.role_of(credit)
            if killer_role is HeirAndSpyChoiceRole.AMBITIONIST:
                open_reward = getattr(session, "_open_c7_ambitionist_reward")
                return open_reward(state, runtime, credit, dying_id)
        if role is HeirAndSpyChoiceRole.REBEL:
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
            role is HeirAndSpyChoiceRole.LOYALIST
            and credit is not None
            and credit == self._variant.current_lord_player_id
        ):
            penalty = getattr(session, "_mode_identity_lord_penalty_discard")
            return penalty(
                state, runtime, self._variant.current_lord_player_id
            )
        return state, runtime


class FormalHeirAndSpyChoiceIdentitySession(ProductionBasicCardBatch):
    """C7 exact canonical façade；直接复用统一生产状态机。"""

    MODE_ID = FORMAL_NO_SKILL_IDENTITY_8P_HEIR_MODE

    def __init__(
        self,
        *,
        seed: int,
        configuration: FormalHeirAndSpyChoiceIdentityConfiguration,
        analysis_only: bool = False,
        session_id: str | None = None,
        session_secret: bytes | None = None,
    ) -> None:
        if type(self) is not FormalHeirAndSpyChoiceIdentitySession:
            raise TypeError(
                "正式立储择途 canonical 会话不允许子类覆写 authority 边界"
            )
        if not isinstance(
            configuration, FormalHeirAndSpyChoiceIdentityConfiguration
        ):
            raise TypeError(
                "正式立储择途会话必须接收"
                "FormalHeirAndSpyChoiceIdentityConfiguration"
            )
        if type(analysis_only) is not bool:
            raise TypeError("analysis_only必须是布尔值")
        if not analysis_only:
            assert_trusted_formal_heir_and_spy_choice_identity_configuration(
                configuration
            )
        if not _FORMAL_IDENTITY_EXECUTION_RELEASED:
            raise FormalIdentityConfigurationError(
                "正式立储择途仍有模式/回放门禁未关闭，禁止生成正式结果"
            )
        if type(seed) is not int:
            raise TypeError("随机种子必须是整数")
        rng = DeterministicRNG(seed)
        identities, numbered, lord_id = _assign_identities(configuration, rng)
        role_map = {
            player_id: role.value for player_id, role in identities.items()
        }
        variant = HeirAndSpyChoiceVariantState(
            original_lord_player_id=lord_id,
            current_lord_player_id=lord_id,
            role_original=dict(role_map),
            role_current=dict(role_map),
            players_had_normal_turn_this_round=(lord_id,),
            normal_turn_cycle=1,
        )
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
        mode_policy = HeirAndSpyChoiceModePolicy(
            configuration, numbered, lord_id, variant
        )
        self._formal_configuration = configuration
        self._analysis_only = analysis_only
        self._physical_player_ids = configuration.physical_player_ids
        self._identities_by_player = MappingProxyType(dict(identities))
        self._numbered_player_order = numbered
        self._lord_player_id = lord_id
        self._seat_by_player = MappingProxyType(dict(mode_policy.seat_by_player))
        self._variant = variant
        super().__init__(
            seed=seed,
            player_hp=player_hp,
            player_max_hp=player_max_hp,
            player_ids=numbered,
            outcome_policy=HeirAndSpyChoiceOutcomePolicy(role_map, lord_id),
            initial_hand_counts=hand_counts,
            first_player_id=lord_id,
            mode_policy=mode_policy,
            shuffle=True,
            session_id=session_id,
            session_secret=session_secret,
            _internal_rng=rng,
        )
        mode_policy.bind_session(self)
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
                        "identity": HeirAndSpyChoiceRole.LORD.value,
                    },
                ),
            )
        )
        self._formal_runtime_integrity_valid = True
        self._formal_runtime_integrity_anchor = (
            self._current_execution_integrity_anchor()
        )

    def _current_execution_integrity_anchor(
        self,
    ) -> tuple[int, int, int, int, int, int]:
        return (
            id(self._state),
            id(self._runtime),
            self.step_count,
            len(self.events),
            len(self.rng_calls),
            len(self.phase_history),
        )

    def step(self, controller: Any = None) -> Any:
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

    def _sync_outcome_policy(self) -> None:
        self._outcome_policy = HeirAndSpyChoiceOutcomePolicy(
            self._variant.role_current,
            self._variant.current_lord_player_id,
        )

    @property
    def formal_configuration(self) -> FormalHeirAndSpyChoiceIdentityConfiguration:
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
    def role_original(self) -> Mapping[str, str]:
        return MappingProxyType(dict(self._variant.role_original))

    @property
    def role_current(self) -> Mapping[str, str]:
        return MappingProxyType(dict(self._variant.role_current))

    @property
    def numbered_player_order(self) -> tuple[str, ...]:
        return self._numbered_player_order

    @property
    def lord_player_id(self) -> str:
        return self._lord_player_id

    @property
    def original_lord_player_id(self) -> str:
        return self._variant.original_lord_player_id

    @property
    def current_lord_player_id(self) -> str:
        return self._variant.current_lord_player_id

    @property
    def seat_by_player(self) -> Mapping[str, int]:
        return self._seat_by_player

    @property
    def variant_id(self) -> str:
        return MOBILE_8P_HEIR_AND_SPY_CHOICE_VARIANT

    @property
    def formal_result_eligible(self) -> bool:
        if not self._formal_runtime_integrity_valid:
            return False
        if (
            self._current_execution_integrity_anchor()
            != self._formal_runtime_integrity_anchor
        ):
            return False
        if not _FORMAL_IDENTITY_EXECUTION_RELEASED or self._analysis_only:
            return False
        try:
            assert_trusted_formal_heir_and_spy_choice_identity_configuration(
                self._formal_configuration
            )
        except (TypeError, FormalIdentityConfigurationError):
            return False
        return True

    def _open_c7_mode_decision(
        self, runtime: object, queue: tuple[str, ...]
    ) -> object:
        open_fn = getattr(self, "_c7_open_mode_decision_window")
        return open_fn(runtime, queue)

    def _open_c7_succession_window(
        self,
        state: GameState,
        runtime: object,
        old_lord_id: str,
        successor_id: str,
    ) -> tuple[GameState, object]:
        open_fn = getattr(self, "_c7_open_succession_window")
        return open_fn(state, runtime, old_lord_id, successor_id)

    def _apply_c7_lose_hp(
        self,
        state: GameState,
        runtime: object,
        player_id: str,
        amount: int,
        reason: str,
        outer_dying_id: str | None,
    ) -> tuple[GameState, object]:
        lose_fn = getattr(self, "_c7_apply_lose_hp")
        return lose_fn(
            state,
            runtime,
            player_id,
            amount=amount,
            reason=reason,
            outer_dying_id=outer_dying_id,
        )

    def _apply_c7_spy_conversion(
        self,
        state: GameState,
        runtime: object,
        chooser_id: str,
        path: str | None,
    ) -> tuple[GameState, object]:
        apply_fn = getattr(self, "_c7_apply_spy_conversion")
        return apply_fn(state, runtime, chooser_id, path)

    def _open_c7_ambitionist_reward(
        self,
        state: GameState,
        runtime: object,
        killer_id: str,
        dying_id: str,
    ) -> tuple[GameState, object]:
        open_fn = getattr(self, "_c7_open_ambitionist_reward")
        return open_fn(state, runtime, killer_id, dying_id)


@dataclass(frozen=True, slots=True)
class FormalHeirAndSpyChoiceIdentityReadiness:
    """C7 特殊八人 formal combat 静态就绪状态；不是独立审计结论。"""

    contract_id: str
    mode_id: str
    variant_id: str
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
    formal_heir_and_spy_choice_identity_no_skill_ready: bool
    identity_8p_heir_ready: bool
    multi_player_production_proven: bool
    authoritative_full_game_core: bool
    blockers: tuple[FormalIdentityBlocker, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "contract_id": self.contract_id,
            "mode_id": self.mode_id,
            "variant_id": self.variant_id,
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
            "formal_heir_and_spy_choice_identity_no_skill_ready": (
                self.formal_heir_and_spy_choice_identity_no_skill_ready
            ),
            "identity_8p_heir_ready": self.identity_8p_heir_ready,
            "multi_player_production_proven": (
                self.multi_player_production_proven
            ),
            "authoritative_full_game_core": (
                self.authoritative_full_game_core
            ),
            "blockers": [item.to_dict() for item in self.blockers],
        }


def inspect_formal_heir_and_spy_choice_identity_readiness() -> (
    FormalHeirAndSpyChoiceIdentityReadiness
):
    """现场 probe C7 analysis 与 canonical trusted 两条路径。"""

    from .production_cards import FormalCardRegistry
    from .production_replay import (
        SUPPORTED_REPLAY_MODES,
        record_reference_formal_heir_and_spy_choice_identity,
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
    expected_contract_id = (
        'POST_B_C7_FORMAL_NO_SKILL_MOBILE_EIGHT_PLAYER_HEIR_AND_SPY_CHOICE_IDENTITY_MODE'
    )
    if (
        POST_B_C7_FORMAL_IDENTITY_CONTRACT_ID != expected_contract_id
        or len(POST_B_C7_FORMAL_IDENTITY_CONTRACT_ID) != 79
    ):
        blockers.append(
            FormalIdentityBlocker(
                "FORMAL_HEIR_AND_SPY_CHOICE_CONTRACT_ID_MISMATCH",
                "MODE_GAP",
                "C7 formal contract ID必须是exact 79字符字面量",
            )
        )
    mode_runtime_reachable = False
    try:
        probe = FormalHeirAndSpyChoiceIdentitySession(
            seed=0,
            configuration=(
                FormalHeirAndSpyChoiceIdentityConfiguration.formal_profile()
            ),
            analysis_only=True,
            session_id="formal-identity-8p-heir-readiness-probe",
            session_secret=b"formal-identity-8p-heir-readiness-probe-01",
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
            probe.mode_id == FORMAL_NO_SKILL_IDENTITY_8P_HEIR_MODE
            and probe.variant_id == MOBILE_8P_HEIR_AND_SPY_CHOICE_VARIANT
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
            and probe.current_lord_player_id == lord_id
            and probe.original_lord_player_id == lord_id
            and dict(probe.role_original) == dict(probe.role_current)
            and probe.deck_supply_mode == "reshuffle_draw"
            and probe.outcome_policy is not None
            and probe.outcome_policy.identity()
            == f"outcome:{FORMAL_NO_SKILL_IDENTITY_8P_HEIR_MODE}"
            and probe.runtime.phase is ProductionPhase.PREPARE
            and len(probe.rng_calls) == 2
            and probe.rng_calls[0].method == "shuffle"
            and probe.rng_calls[1].method == "shuffle"
            and C6_CANONICAL_DRAW_REACHABILITY_STATUS
            == "C6_CANONICAL_DRAW_REACHABILITY_UNRESOLVED"
        )
    except Exception as exc:  # pragma: no cover - readiness 收敛为 blocker
        blockers.append(
            FormalIdentityBlocker(
                "FORMAL_HEIR_AND_SPY_CHOICE_FACTORY_UNREACHABLE",
                "MODE_GAP",
                "正式立储择途 canonical factory 现场自检失败："
                f"{type(exc).__name__}:{exc}",
            )
        )
    if not mode_runtime_reachable:
        blockers.append(
            FormalIdentityBlocker(
                "FORMAL_HEIR_AND_SPY_CHOICE_RUNTIME_NOT_REACHABLE",
                "MODE_GAP",
                "正式立储择途不能从canonical factory到达统一生产核心",
            )
        )

    formal_runtime_reachable = False
    formal_runtime_error: str | None = None
    try:
        formal_configuration = (
            FormalHeirAndSpyChoiceIdentityConfiguration.formal_profile()
        )
        formal_probe = FormalHeirAndSpyChoiceIdentitySession(
            seed=0,
            configuration=formal_configuration,
            analysis_only=False,
            session_id="formal-identity-8p-heir-trusted-readiness-probe",
            session_secret=b"formal-identity-8p-heir-trusted-probe-01",
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
                "FORMAL_HEIR_AND_SPY_CHOICE_TRUSTED_RUNTIME_UNREACHABLE",
                "MODE_GAP",
                "正式立储择途 analysis_only=False trusted path 现场自检失败"
                f"{detail}",
            )
        )
    if not global_card_semantics_complete:
        blockers.append(
            FormalIdentityBlocker(
                "FORMAL_HEIR_AND_SPY_CHOICE_CARD_SEMANTICS_INCOMPLETE",
                "CARD_GAP",
                "正式立储择途依赖38/38全局卡牌语义，当前不满足",
            )
        )
    replay_supported = (
        callable(record_reference_formal_heir_and_spy_choice_identity)
        and callable(reexecute_production_replay)
        and FORMAL_NO_SKILL_IDENTITY_8P_HEIR_MODE in SUPPORTED_REPLAY_MODES
    )
    if not replay_supported:
        blockers.append(
            FormalIdentityBlocker(
                "FORMAL_HEIR_AND_SPY_CHOICE_REPLAY_UNSUPPORTED",
                "MODE_GAP",
                "严格回放不支持正式立储择途八人身份模式",
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
    return FormalHeirAndSpyChoiceIdentityReadiness(
        contract_id=POST_B_C7_FORMAL_IDENTITY_CONTRACT_ID,
        mode_id=FORMAL_NO_SKILL_IDENTITY_8P_HEIR_MODE,
        variant_id=MOBILE_8P_HEIR_AND_SPY_CHOICE_VARIANT,
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
        formal_heir_and_spy_choice_identity_no_skill_ready=ready,
        identity_8p_heir_ready=ready,
        multi_player_production_proven=False,
        authoritative_full_game_core=False,
        blockers=tuple(blockers),
    )


__all__ = [
    "C7_CANONICAL_DRAW_REACHABILITY_STATUS",
    "FORMAL_NO_SKILL_IDENTITY_8P_HEIR_MODE",
    "MOBILE_8P_HEIR_AND_SPY_CHOICE_VARIANT",
    "POST_B_C7_FORMAL_IDENTITY_CONTRACT_ID",
    "FormalHeirAndSpyChoiceIdentityConfiguration",
    "FormalHeirAndSpyChoiceIdentityReadiness",
    "FormalHeirAndSpyChoiceIdentitySession",
    "HeirAndSpyChoiceModePolicy",
    "HeirAndSpyChoiceOutcomePolicy",
    "HeirAndSpyChoiceRole",
    "TrustedFormalHeirAndSpyChoiceIdentityConfiguration",
    "assert_trusted_formal_heir_and_spy_choice_identity_configuration",
    "inspect_formal_heir_and_spy_choice_identity_readiness",
]
