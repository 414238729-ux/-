# -*- coding: utf-8 -*-
"""POST-B C5：正式无武将技能五人标准军争身份模式层。

本模块不是第二套引擎：身份场只提供 mode profile / 身份模型 /
OutcomePolicy / mode policy（初始化、身份公开、击杀奖惩、reshuffle_draw）
与可见性配置，全部消费统一生产核心（ProductionBasicCardBatch、
PlayerTopology、OutcomePolicy、既有 events/actions/damage/dying/death/
phase loop / parent-root continuation / strict replay）。

范围严格限定为：五人标准非特殊军争身份、formal no-skill soldier、
canonical post-redraw combat initialization。不包含选将、真实武将技能、
手气卡、换牌、八人场、野心家、储君、继位、内奸择途或完整商业外围流程。
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields, replace
from enum import Enum
from types import MappingProxyType
from typing import Mapping

from .actions import UnsupportedRuleError
from .events import EventType, GameEvent
from .model import (
    CharacterGender,
    CharacterMetadata,
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

_TRUSTED_IDENTITY_CAPABILITY = object()

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
    """正式五人身份胜负策略。

    - lord 存活且场上无 rebel/spy → lord_and_loyalists
    - 仅剩 lord + spy → 不终局
    - lord 确认死亡且唯一其他存活角色为 spy → spy
    - lord 确认死亡的其他所有情况（含无人存活）→ rebels
    主忠 / 反贼 outcome 是阵营结果，不把胜者限制成当前存活列表。
    """

    identities: Mapping[str, StandardIdentityRole] = MappingProxyType({})

    def __init__(self, identities: Mapping[str, StandardIdentityRole]) -> None:
        if not isinstance(identities, Mapping) or len(identities) != 5:
            raise FormalIdentityConfigurationError(
                "身份胜负策略需要恰好5项角色→身份映射"
            )
        parsed: dict[str, StandardIdentityRole] = {}
        for player_id, raw_role in identities.items():
            if type(player_id) is not str or not player_id.strip():
                raise FormalIdentityConfigurationError(
                    "身份映射的角色ID必须是非空字符串"
                )
            parsed[player_id] = _parse_identity_role(raw_role, player_id)
        roles = tuple(parsed.values())
        if (
            roles.count(StandardIdentityRole.LORD) != 1
            or roles.count(StandardIdentityRole.LOYALIST) != 1
            or roles.count(StandardIdentityRole.REBEL) != 2
            or roles.count(StandardIdentityRole.SPY) != 1
        ):
            raise FormalIdentityConfigurationError(
                "正式五人身份必须恰好1主公、1忠臣、2反贼、1内奸"
            )
        object.__setattr__(self, "policy_id", "formal_no_skill_identity_5p")
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
    """正式身份模式层：初始化输入、身份公开与击杀奖惩钩子。"""

    configuration: FormalIdentityConfiguration
    identities: Mapping[str, StandardIdentityRole] = MappingProxyType({})
    numbered_player_order: tuple[str, ...] = ()
    lord_player_id: str = ""
    physical_player_ids: tuple[str, ...] = ()
    seat_by_player: Mapping[str, int] = MappingProxyType({})

    def __init__(
        self,
        configuration: FormalIdentityConfiguration,
        identities: Mapping[str, StandardIdentityRole],
        numbered_player_order: tuple[str, ...],
        lord_player_id: str,
    ) -> None:
        if not isinstance(configuration, FormalIdentityConfiguration):
            raise TypeError("身份模式层必须接收FormalIdentityConfiguration")
        parsed = IdentityOutcomePolicy(identities).identities
        if type(numbered_player_order) is not tuple or len(
            numbered_player_order
        ) != 5:
            raise FormalIdentityConfigurationError(
                "numbered_player_order必须是5名角色的元组"
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

    @property
    def identity(self) -> str:
        return "mode:formal_no_skill_identity_5p"

    @property
    def initial_hand_counts(self) -> tuple[int, ...]:
        count = self.configuration.initial_hand_count
        return (count, count, count, count, count)

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
    configuration: FormalIdentityConfiguration,
    rng: DeterministicRNG,
) -> tuple[
    dict[str, StandardIdentityRole],
    tuple[str, ...],
    str,
]:
    """用会话 RNG 洗混五张固定身份牌并旋转座次。禁止第二 RNG / seed helper。"""

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


class FormalIdentitySession(ProductionBasicCardBatch):
    """正式 no-skill 五人标准身份 canonical 会话（直接复用统一生产核心）。

    同一条 DeterministicRNG 依序用于：身份牌 shuffle → 正式160张牌堆
    shuffle → 后续普通 reshuffle。调用方不能注入 RNG。
    """

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
        if type(self) is not _CANONICAL_IDENTITY_SESSION_TYPE:
            raise TypeError(
                "正式身份 canonical 会话不允许通过子类覆写释放或配置边界"
            )
        if not isinstance(configuration, FormalIdentityConfiguration):
            raise TypeError("正式身份会话必须接收FormalIdentityConfiguration")
        if type(analysis_only) is not bool:
            raise TypeError("analysis_only必须是布尔值")
        if not analysis_only:
            assert_trusted_formal_identity_configuration(configuration)
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
    def formal_configuration(self) -> FormalIdentityConfiguration:
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
            assert_trusted_formal_identity_configuration(
                self._formal_configuration
            )
        except (TypeError, FormalIdentityConfigurationError):
            return False
        return True


_CANONICAL_IDENTITY_SESSION_TYPE = FormalIdentitySession


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


__all__ = [
    "FORMAL_NO_SKILL_IDENTITY_5P_MODE",
    "FormalIdentityBlocker",
    "FormalIdentityConfiguration",
    "FormalIdentityConfigurationError",
    "FormalIdentityReadiness",
    "FormalIdentitySession",
    "IdentityModePolicy",
    "IdentityOutcomePolicy",
    "StandardIdentityRole",
    "TrustedFormalIdentityConfiguration",
    "assert_trusted_formal_identity_configuration",
    "inspect_formal_identity_readiness",
]
