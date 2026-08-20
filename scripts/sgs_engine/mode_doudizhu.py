# -*- coding: utf-8 -*-
"""POST-B C4：正式无武将技能斗地主模式层。

本模块不是第二套引擎：斗地主只提供 mode profile / camp 模型 /
OutcomePolicy / mode policy（初始化、跋扈修饰器、飞扬与农民死亡奖励钩子）/
可见性配置，全部消费统一生产核心（ProductionBasicCardBatch、PlayerTopology、
OutcomePolicy、既有 events/actions/damage/dying/death/phase loop）。

规则源：Knowledge《三国杀模式规则》第 3 章斗地主模式（当前确认），
含 3.1-3.2 座次（地主确定后固定1号位，逆时针2号位，顺时针3号位）、
3.3 地主技能（飞扬与跋扈）、3.4 地主初始体力（5/5 pre-game 加成）、
3.5 初始手牌（4/4/4）、3.6 手牌三方互盲可见性、3.7 农民死亡奖励
（回1血/摸2张/两项都不要）、第 1 章牌堆复用（160张）、牌堆耗尽平局（§2.11 继承）、
客户端15分钟评分裁定（CONFIRMED_OUT_OF_SIMULATION_SCOPE，本轮不实现）。
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from types import MappingProxyType
from typing import Mapping, Sequence

from .actions import UnsupportedRuleError
from .model import (
    CharacterGender,
    CharacterMetadata,
    GameState,
    ZoneRef,
)
from .multiplayer import OutcomePolicy, PlayerTopology
from .production_batch import (
    ProductionBasicCardBatch,
    ProductionPhase,
    _PendingPeasantDeathReward,
)

FORMAL_NO_SKILL_DOUDIZHU_MODE = "formal_no_skill_doudizhu"

_CAMP_LANDLORD = "landlord"
_CAMP_PEASANTS = "peasants"

_SEAT_CAMP_IDS: Mapping[int, str] = MappingProxyType(
    {1: _CAMP_LANDLORD, 2: _CAMP_PEASANTS, 3: _CAMP_PEASANTS}
)

_TRUSTED_DOUDIZHU_CAPABILITY = object()


class FormalDoudizhuConfigurationError(ValueError):
    """正式斗地主配置非法。"""


@dataclass(frozen=True, slots=True)
class FormalDoudizhuConfiguration:
    """正式 no-skill 斗地主的 canonical profile（规则源：《三国杀模式规则》§3）。

    座次顺序=player_ids 顺序（1..3号位）；阵营由座次确定（1号位地主、2/3号位农民），
    初始化后不变。初始手牌 4/4/4（§3.5）；测试角色基础体力 4/4，地主在进入游戏前
    直接初始化为 5/5（§3.4 基础属性+1/+1 pre-game 调整）；先手=1号位地主（§3.2.1）；
    地主永久拥有飞扬（§3.3）与跋扈（准备阶段摸1张牌，出牌阶段杀次数上限2）；
    农民死亡奖励三选一（§3.7）；牌堆供给口径为 no_reshuffle_draw（耗尽平局）。
    """

    player_ids: tuple[str, str, str] = ("p1", "p2", "p3")
    base_hp: tuple[int, int, int] = (5, 4, 4)
    base_max_hp: tuple[int, int, int] = (5, 4, 4)
    initial_hand_counts: tuple[int, int, int] = (4, 4, 4)
    first_player_id: str = "p1"
    hand_qi_ka_allowed: bool = False
    feiyang_seat: int = 1
    feiyang_enabled: bool = True
    bahu_prepare_draw_enabled: bool = True
    bahu_slash_limit: int = 2
    peasant_slash_limit: int = 1
    death_reward_mode: str = "choice_heal1_draw2_decline"
    deck_supply_mode: str = "no_reshuffle_draw"

    def __post_init__(self) -> None:
        if len(self.player_ids) != 3:
            raise FormalDoudizhuConfigurationError("正式斗地主必须恰好3名角色")
        if any(
            not isinstance(value, str) or not value.strip()
            for value in self.player_ids
        ):
            raise FormalDoudizhuConfigurationError("player_ids必须是非空字符串")
        if len(set(self.player_ids)) != 3:
            raise FormalDoudizhuConfigurationError("player_ids不能重复")
        for label, values in (
            ("base_hp", self.base_hp),
            ("base_max_hp", self.base_max_hp),
            ("initial_hand_counts", self.initial_hand_counts),
        ):
            if len(values) != 3 or any(
                isinstance(value, bool)
                or not isinstance(value, int)
                or value < 1
                for value in values
            ):
                raise FormalDoudizhuConfigurationError(f"{label}必须是3个正整数")
        if any(
            hp > max_hp
            for hp, max_hp in zip(self.base_hp, self.base_max_hp)
        ):
            raise FormalDoudizhuConfigurationError("初始体力不能高于体力上限")
        if sum(self.initial_hand_counts) != 12:
            raise FormalDoudizhuConfigurationError(
                "正式斗地主初始手牌按座次4/4/4合计12张（§3.5）"
            )
        if self.first_player_id != self.player_ids[0]:
            raise FormalDoudizhuConfigurationError(
                "正式斗地主先手必须是1号位地主（§3.2.1）"
            )
        if self.deck_supply_mode != "no_reshuffle_draw":
            raise FormalDoudizhuConfigurationError(
                "正式斗地主牌堆供给口径必须是no_reshuffle_draw"
            )
        if not isinstance(self.hand_qi_ka_allowed, bool):
            raise FormalDoudizhuConfigurationError("hand_qi_ka_allowed必须是布尔值")
        if not isinstance(self.feiyang_seat, int) or self.feiyang_seat != 1:
            raise FormalDoudizhuConfigurationError("feiyang_seat必须是1号位地主")
        if not isinstance(self.feiyang_enabled, bool) or not self.feiyang_enabled:
            raise FormalDoudizhuConfigurationError("地主飞扬必须启用")
        if (
            not isinstance(self.bahu_prepare_draw_enabled, bool)
            or not self.bahu_prepare_draw_enabled
        ):
            raise FormalDoudizhuConfigurationError("地主跋扈准备阶段摸牌必须启用")
        if (
            isinstance(self.bahu_slash_limit, bool)
            or not isinstance(self.bahu_slash_limit, int)
            or self.bahu_slash_limit != 2
        ):
            raise FormalDoudizhuConfigurationError("地主跋扈出牌阶段杀上限必须为2")
        if (
            isinstance(self.peasant_slash_limit, bool)
            or not isinstance(self.peasant_slash_limit, int)
            or self.peasant_slash_limit != 1
        ):
            raise FormalDoudizhuConfigurationError("农民出牌阶段杀上限必须为1")
        if self.death_reward_mode != "choice_heal1_draw2_decline":
            raise FormalDoudizhuConfigurationError(
                "农民死亡奖励模式必须是choice_heal1_draw2_decline（§3.7）"
            )
        object.__setattr__(
            self,
            "player_ids",
            tuple(value.strip() for value in self.player_ids),
        )

    def camp_of(self, seat: int) -> str:
        """按座次返回阵营（1=landlord, 2/3=peasants；§3.1-§3.2）。"""
        camp = _SEAT_CAMP_IDS.get(seat)
        if camp is None:
            raise FormalDoudizhuConfigurationError(
                f"座次{seat!r}不是正式斗地主座次"
            )
        return camp

    def camps_by_player(self) -> Mapping[str, str]:
        return MappingProxyType(
            {
                player_id: self.camp_of(index + 1)
                for index, player_id in enumerate(self.player_ids)
            }
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": "formal-no-skill-doudizhu-configuration-v1",
            "player_ids": list(self.player_ids),
            "base_hp": list(self.base_hp),
            "base_max_hp": list(self.base_max_hp),
            "initial_hand_counts": list(self.initial_hand_counts),
            "first_player_id": self.first_player_id,
            "hand_qi_ka_allowed": self.hand_qi_ka_allowed,
            "feiyang_seat": self.feiyang_seat,
            "feiyang_enabled": self.feiyang_enabled,
            "bahu_prepare_draw_enabled": self.bahu_prepare_draw_enabled,
            "bahu_slash_limit": self.bahu_slash_limit,
            "peasant_slash_limit": self.peasant_slash_limit,
            "death_reward_mode": self.death_reward_mode,
            "deck_supply_mode": self.deck_supply_mode,
        }

    @classmethod
    def from_dict(
        cls, value: Mapping[str, object]
    ) -> "FormalDoudizhuConfiguration":
        if not isinstance(value, Mapping):
            raise FormalDoudizhuConfigurationError("正式斗地主配置必须是JSON对象")
        expected_fields = {
            "schema",
            "player_ids",
            "base_hp",
            "base_max_hp",
            "initial_hand_counts",
            "first_player_id",
            "hand_qi_ka_allowed",
            "feiyang_seat",
            "feiyang_enabled",
            "bahu_prepare_draw_enabled",
            "bahu_slash_limit",
            "peasant_slash_limit",
            "death_reward_mode",
            "deck_supply_mode",
        }
        if set(value) != expected_fields:
            raise FormalDoudizhuConfigurationError("正式斗地主配置字段集不合法")
        if value["schema"] != "formal-no-skill-doudizhu-configuration-v1":
            raise FormalDoudizhuConfigurationError("正式斗地主配置schema不受支持")
        return cls(
            player_ids=tuple(value["player_ids"]),  # type: ignore[arg-type]
            base_hp=tuple(value["base_hp"]),  # type: ignore[arg-type]
            base_max_hp=tuple(value["base_max_hp"]),  # type: ignore[arg-type]
            initial_hand_counts=tuple(value["initial_hand_counts"]),  # type: ignore[arg-type]
            first_player_id=str(value["first_player_id"]),
            hand_qi_ka_allowed=bool(value["hand_qi_ka_allowed"]),
            feiyang_seat=int(value["feiyang_seat"]),  # type: ignore[arg-type]
            feiyang_enabled=bool(value["feiyang_enabled"]),
            bahu_prepare_draw_enabled=bool(value["bahu_prepare_draw_enabled"]),
            bahu_slash_limit=int(value["bahu_slash_limit"]),  # type: ignore[arg-type]
            peasant_slash_limit=int(value["peasant_slash_limit"]),  # type: ignore[arg-type]
            death_reward_mode=str(value["death_reward_mode"]),
            deck_supply_mode=str(value["deck_supply_mode"]),
        )

    @staticmethod
    def formal_profile() -> "TrustedFormalDoudizhuConfiguration":
        """canonical formal no-skill doudizhu profile（唯一正式来源）。"""
        return _canonical_formal_doudizhu_profile_value()

    @classmethod
    def from_canonical_profile_value(
        cls, value: Mapping[str, object]
    ) -> "FormalDoudizhuConfiguration":
        """校验 payload 与 canonical formal profile 完全一致后返回可信配置。"""
        from json import dumps, loads

        from .replay import canonical_json

        canonical_value = loads(
            dumps(cls.formal_profile().to_dict(), sort_keys=True)
        )
        submitted = loads(canonical_json(value))
        if submitted != canonical_value:
            raise FormalDoudizhuConfigurationError(
                "正式斗地主配置必须与项目 canonical formal profile 完全一致；"
                "payload 不能自行获得可信规则来源"
            )
        return cls.formal_profile()


class TrustedFormalDoudizhuConfiguration(FormalDoudizhuConfiguration):
    """仅由模块内 canonical factory 构造的 trusted 配置。"""

    _capability_token: object = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        super().__post_init__()
        object.__setattr__(
            self, "_capability_token", _TRUSTED_DOUDIZHU_CAPABILITY
        )


def _canonical_formal_doudizhu_profile_value(
) -> "TrustedFormalDoudizhuConfiguration":
    return TrustedFormalDoudizhuConfiguration(
        player_ids=("p1", "p2", "p3"),
        base_hp=(5, 4, 4),
        base_max_hp=(5, 4, 4),
        initial_hand_counts=(4, 4, 4),
        first_player_id="p1",
        hand_qi_ka_allowed=False,
        feiyang_seat=1,
        feiyang_enabled=True,
        bahu_prepare_draw_enabled=True,
        bahu_slash_limit=2,
        peasant_slash_limit=1,
        death_reward_mode="choice_heal1_draw2_decline",
        deck_supply_mode="no_reshuffle_draw",
    )


def assert_trusted_formal_doudizhu_configuration(
    configuration: FormalDoudizhuConfiguration,
) -> None:
    """正式斗地主 trusted authority boundary（exact type + capability + value）。"""
    if not isinstance(configuration, FormalDoudizhuConfiguration):
        raise TypeError("正式斗地主会话必须接收FormalDoudizhuConfiguration")
    if type(configuration) is not TrustedFormalDoudizhuConfiguration:
        raise FormalDoudizhuConfigurationError(
            "正式斗地主结果只接受内部 canonical factory 返回的 "
            "TrustedFormalDoudizhuConfiguration（exact type 校验）；调用方配置"
            "不能自我授权"
        )
    if (
        getattr(configuration, "_capability_token", None)
        is not _TRUSTED_DOUDIZHU_CAPABILITY
    ):
        raise FormalDoudizhuConfigurationError(
            "正式斗地主结果只接受真实持有模块私有 capability token 的 "
            "TrustedFormalDoudizhuConfiguration（capability identity 校验）"
        )
    if (
        configuration.to_dict()
        != _canonical_formal_doudizhu_profile_value().to_dict()
    ):
        raise FormalDoudizhuConfigurationError(
            "正式斗地主配置的 profile value 必须精确等于项目 canonical "
            "formal no-skill doudizhu profile；type/token 正确但值非 canonical "
            "的对象同样失败关闭（canonical value invariant）"
        )


@dataclass(frozen=True, slots=True)
class DoudizhuOutcomePolicy(OutcomePolicy):
    """正式斗地主胜负策略（§3.1-§3.2 当前确认）。

    - 地主确认死亡 → 农民阵营获胜（winner = "peasants"）；
    - 两名农民均确认死亡 → 地主获胜（winner = "landlord"）；
    - 一名农民死亡、另一名仍存活 → winner = None，游戏继续；
    - 两阵营同时无存活成员在顺序确认死亡下不可达，防御性失败关闭；
    - 牌堆耗尽平局：winner=None + draw_finish_reason="doudizhu_draw_deck_exhausted"。
    """

    camps: Mapping[str, str] = MappingProxyType({})

    def __init__(self, camps: Mapping[str, str]) -> None:
        if not isinstance(camps, Mapping) or not camps:
            raise FormalDoudizhuConfigurationError(
                "斗地主胜负策略需要非空阵营映射"
            )
        if set(camps.values()) != {_CAMP_LANDLORD, _CAMP_PEASANTS}:
            raise FormalDoudizhuConfigurationError(
                "正式斗地主必须恰好包含地主与农民两个阵营"
            )
        object.__setattr__(self, "policy_id", "formal_no_skill_doudizhu")
        object.__setattr__(self, "camps", MappingProxyType(dict(camps)))

    def resolve_winner_after_death(
        self, topology: PlayerTopology, dying_id: str
    ) -> str | None:
        alive_by_camp: dict[str, int] = {_CAMP_LANDLORD: 0, _CAMP_PEASANTS: 0}
        for player in topology.players:
            camp = self.camps.get(player.player_id)
            if camp is None:
                raise UnsupportedRuleError(
                    f"角色{player.player_id!r}未注册正式斗地主阵营"
                )
            if player.alive:
                alive_by_camp[camp] = alive_by_camp.get(camp, 0) + 1
        eliminated = [
            camp for camp, count in alive_by_camp.items() if count == 0
        ]
        if len(eliminated) == 0:
            return None
        if len(eliminated) == 1:
            winners = [
                camp for camp in alive_by_camp if camp != eliminated[0]
            ]
            return winners[0]
        raise UnsupportedRuleError(
            "正式斗地主顺序确认死亡下两阵营不应同时无存活成员；失败关闭"
        )

    @property
    def finish_reason(self) -> str:
        return "team_eliminated"

    @property
    def draw_finish_reason(self) -> str:
        return "doudizhu_draw_deck_exhausted"


@dataclass(frozen=True, slots=True)
class DoudizhuModePolicy:
    """正式斗地主模式层：初始化输入与阶段/修饰器钩子（统一生产核心消费）。

    - initial_hand_counts / first_player_id：由 canonical profile 提供；
    - deck_supply_mode：no_reshuffle_draw（核心按此执行原子取牌与牌堆耗尽平局）；
    - feiyang_available：地主永久拥有飞扬（§3.3），每个地主判定阶段开始时均有资格；
    - bahu_prepare_draw：地主永久拥有跋扈，准备阶段额外摸1张牌（§3.3）；
    - slash_limit：出牌阶段使用【杀】次数上限地主为2、农民为1（§3.3）；
    - death_confirmed_hook：一名农民确认死亡后，若游戏继续，另一名存活农民
      进入专属选择窗口（回复1体力 / 摸2张 / 两项都不要，§3.7）。
    """

    configuration: FormalDoudizhuConfiguration
    camps: Mapping[str, str] = MappingProxyType({})

    def __init__(self, configuration: FormalDoudizhuConfiguration) -> None:
        if not isinstance(configuration, FormalDoudizhuConfiguration):
            raise TypeError("斗地主模式层必须接收FormalDoudizhuConfiguration")
        object.__setattr__(self, "configuration", configuration)
        object.__setattr__(
            self,
            "camps",
            MappingProxyType(dict(configuration.camps_by_player())),
        )

    @property
    def identity(self) -> str:
        return "mode:formal_no_skill_doudizhu"

    @property
    def initial_hand_counts(self) -> tuple[int, ...]:
        return self.configuration.initial_hand_counts

    @property
    def first_player_id(self) -> str:
        return self.configuration.first_player_id

    @property
    def deck_supply_mode(self) -> str:
        return self.configuration.deck_supply_mode

    def camp_of(self, player_id: str) -> str:
        camp = self.camps.get(player_id)
        if camp is None:
            raise FormalDoudizhuConfigurationError(
                f"角色{player_id!r}未注册正式斗地主阵营"
            )
        return camp

    def is_landlord(self, player_id: str) -> bool:
        return self.camp_of(player_id) == _CAMP_LANDLORD

    def seat_of(self, player_id: str) -> int:
        try:
            return self.configuration.player_ids.index(player_id) + 1
        except ValueError as exc:
            raise FormalDoudizhuConfigurationError(
                f"角色{player_id!r}未注册正式斗地主座次"
            ) from exc

    def surviving_peasant_id(self, state: GameState) -> str | None:
        """寻找当前唯一存活的农民。若两名均存活或两名均死亡返回 None。"""
        peasants = [
            pid for pid in self.configuration.player_ids
            if self.camp_of(pid) == _CAMP_PEASANTS
        ]
        alive_peasants = [
            pid for pid in peasants if state.players_by_id[pid].alive
        ]
        if len(alive_peasants) == 1:
            return alive_peasants[0]
        return None

    def feiyang_available(
        self, *, player_id: str, seat: int, turn_number: int
    ) -> bool:
        """地主永久“飞扬”可用性（§3.3：每回合判定阶段限一次）。"""
        del player_id, turn_number
        return (
            self.configuration.feiyang_enabled
            and seat == self.configuration.feiyang_seat
        )

    def bahu_prepare_draw(self, player_id: str) -> bool:
        """地主永久“跋扈”准备阶段摸1张牌修饰器（§3.3）。"""
        return (
            self.configuration.bahu_prepare_draw_enabled
            and self.is_landlord(player_id)
        )

    def slash_limit(self, player_id: str) -> int:
        """出牌阶段使用【杀】次数上限：地主为2，农民为1（§3.3）。"""
        if self.is_landlord(player_id):
            return self.configuration.bahu_slash_limit
        return self.configuration.peasant_slash_limit

    def death_confirmed_hook(
        self,
        session: object,
        state: GameState,
        runtime: object,
        dying_id: str,
    ) -> tuple[GameState, object]:
        """POST-B C4：农民死亡确认钩子（§3.7 当前确认：存活农民三选一）。

        只在胜负未成立（winner=None 继续分支）时由生产核心调用。
        若死亡角色为农民，找到唯一存活农民，挂起 `_PendingPeasantDeathReward`
        并将阶段切换为 `ProductionPhase.PEASANT_REWARD_CHOICE`。
        核心检测到该阶段后执行真正的暂停（commit runtime 并挂起 continuation），
        等待存活农民提交动作。
        """
        del session
        if self.camp_of(dying_id) != _CAMP_PEASANTS:
            return state, runtime
        surviving = self.surviving_peasant_id(state)
        if surviving is None:
            raise FormalDoudizhuConfigurationError(
                "正式斗地主非终局农民死亡必须存在存活农民；失败关闭"
            )
        turn_num = getattr(runtime, "turn_number", 0)
        window_id = f"peasant_reward:{turn_num}:{dying_id}:{surviving}"
        pending_chain = getattr(runtime, "pending_chain", None)
        current_pid = getattr(runtime, "current_player_id", "")
        is_nonterminal_chain_child = (
            pending_chain is not None and dying_id != current_pid
        )
        pending = _PendingPeasantDeathReward(
            dead_peasant_id=dying_id,
            chooser_id=surviving,
            window_id=window_id,
            is_nonterminal_chain_child=is_nonterminal_chain_child,
        )
        next_runtime = replace(
            runtime,  # type: ignore[arg-type]
            phase=ProductionPhase.PEASANT_REWARD_CHOICE,
            pending_peasant_reward=pending,
        )
        return state, next_runtime


# ----------------------------------------------------------------------
# POST-B C4：正式斗地主 canonical 会话与现场就绪门禁
# ----------------------------------------------------------------------

_FORMAL_DOUDIZHU_EXECUTION_RELEASED = True

_CANONICAL_DOUDIZHU_TEST_CHARACTER = "soldier"


class FormalDoudizhuSession(ProductionBasicCardBatch):
    """正式 no-skill 斗地主 canonical 会话（直接复用统一生产核心）。

    配置注入 canonical profile（座次/阵营/初始手牌4/4/4/先手地主/体力5/4/4）、
    阵营胜负策略（DoudizhuOutcomePolicy）与模式层（DoudizhuModePolicy：
    飞扬跋扈、农民死亡奖励、no_reshuffle_draw 牌堆供给）。测试角色 =
    无技能士兵档案（性别 NONE，雌雄双股剑“异性”判定不触发）。
    """

    MODE_ID = FORMAL_NO_SKILL_DOUDIZHU_MODE

    def __init__(
        self,
        *,
        seed: int,
        configuration: FormalDoudizhuConfiguration,
        analysis_only: bool = False,
        session_id: str | None = None,
        session_secret: bytes | None = None,
    ) -> None:
        if type(self) is not _CANONICAL_DOUDIZHU_SESSION_TYPE:
            raise TypeError(
                "正式斗地主 canonical 会话不允许通过子类覆写释放或配置边界"
            )
        if not isinstance(configuration, FormalDoudizhuConfiguration):
            raise TypeError("正式斗地主会话必须接收FormalDoudizhuConfiguration")
        if not isinstance(analysis_only, bool):
            raise TypeError("analysis_only必须是布尔值")
        if not analysis_only:
            assert_trusted_formal_doudizhu_configuration(configuration)
        if not _FORMAL_DOUDIZHU_EXECUTION_RELEASED:
            raise FormalDoudizhuConfigurationError(
                "正式斗地主仍有模式/回放门禁未关闭，禁止生成正式结果"
            )
        self._formal_configuration = configuration
        self._analysis_only = analysis_only
        super().__init__(
            seed=seed,
            player_hp=configuration.base_hp,
            player_max_hp=configuration.base_max_hp,
            player_ids=configuration.player_ids,
            outcome_policy=DoudizhuOutcomePolicy(
                configuration.camps_by_player()
            ),
            initial_hand_counts=configuration.initial_hand_counts,
            first_player_id=configuration.first_player_id,
            mode_policy=DoudizhuModePolicy(configuration),
            shuffle=True,
            session_id=session_id,
            session_secret=session_secret,
        )
        soldier = CharacterMetadata(
            _CANONICAL_DOUDIZHU_TEST_CHARACTER,
            CharacterGender.NONE,
            CharacterGender.NONE,
        )
        players = tuple(
            replace(player, character=soldier)
            for player in self.state.players
        )
        self._state = replace(self.state, players=players)

    @property
    def formal_configuration(self) -> FormalDoudizhuConfiguration:
        return self._formal_configuration

    @property
    def analysis_only(self) -> bool:
        return self._analysis_only

    @property
    def formal_result_eligible(self) -> bool:
        return (
            _FORMAL_DOUDIZHU_EXECUTION_RELEASED
            and not self._analysis_only
            and isinstance(
                self._formal_configuration, TrustedFormalDoudizhuConfiguration
            )
        )


_CANONICAL_DOUDIZHU_SESSION_TYPE = FormalDoudizhuSession


@dataclass(frozen=True, slots=True)
class FormalDoudizhuBlocker:
    code: str
    category: str
    message: str

    def to_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "category": self.category,
            "message": self.message,
        }


@dataclass(frozen=True, slots=True)
class FormalDoudizhuReadiness:
    """正式 no-skill 斗地主现场就绪状态（静态执行资格；不是验收证据）。"""

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
    formal_doudizhu_no_skill_ready: bool
    doudizhu_ready: bool
    client_timeout_score_adjudication: bool
    blockers: tuple[FormalDoudizhuBlocker, ...]

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
            "formal_doudizhu_no_skill_ready": (
                self.formal_doudizhu_no_skill_ready
            ),
            "doudizhu_ready": self.doudizhu_ready,
            "client_timeout_score_adjudication": (
                self.client_timeout_score_adjudication
            ),
            "blockers": [item.to_dict() for item in self.blockers],
        }


def inspect_formal_doudizhu_readiness() -> FormalDoudizhuReadiness:
    """从当前正式牌堆、注册表与 canonical factory 现场派生斗地主就绪状态。

    ``doudizhu_ready`` 的精确定义：现场 canonical 会话可达 + 160 张正式牌堆 +
    3 名角色座次/阵营/初始手牌/先手/体力符合 canonical profile + 卡牌语义
    复用 C2 全局闭合（38/38）+ 严格回放支持正式斗地主模式 + 现场 blocker
    派生的 unsupported/approximation 为 0。绝不包含客户端15分钟评分裁定。
    """
    from .production_cards import FormalCardRegistry

    registry = FormalCardRegistry.from_formal_csv()
    registered_keys = frozenset(registry.implemented_card_keys)
    deck_keys = frozenset(record.card_key for record in registry.records)
    global_card_semantics_complete = (
        len(registry.records) == 160
        and len(deck_keys) == 38
        and registered_keys == deck_keys
    )
    blockers: list[FormalDoudizhuBlocker] = []
    mode_runtime_reachable = False
    try:
        probe = FormalDoudizhuSession(
            seed=0,
            configuration=FormalDoudizhuConfiguration.formal_profile(),
            analysis_only=True,
            session_id="formal-doudizhu-readiness-probe",
            session_secret=b"formal-doudizhu-readiness-probe-1",  # 32字节
        )
        state = probe.state
        hand_sizes = tuple(
            len(state.card_ids_in(ZoneRef.hand(player_id)))
            for player_id in ("p1", "p2", "p3")
        )
        mode_runtime_reachable = (
            probe.mode_id == FORMAL_NO_SKILL_DOUDIZHU_MODE
            and len(state.cards) == 160
            and len(state.players) == 3
            and hand_sizes == (4, 4, 4)
            and probe.state.players_by_id["p1"].hp == 5
            and probe.state.players_by_id["p1"].max_hp == 5
            and probe.state.players_by_id["p2"].hp == 4
            and probe.state.players_by_id["p3"].hp == 4
            and probe.first_player_id == "p1"
            and dict(probe.mode_policy.camps)
            == {"p1": "landlord", "p2": "peasants", "p3": "peasants"}
            and probe.deck_supply_mode == "no_reshuffle_draw"
            and probe.outcome_policy is not None
            and probe.outcome_policy.identity()
            == "outcome:formal_no_skill_doudizhu"
            and probe.runtime.phase is ProductionPhase.PREPARE
        )
    except Exception as exc:  # pragma: no cover
        blockers.append(
            FormalDoudizhuBlocker(
                "FORMAL_DOUDIZHU_FACTORY_UNREACHABLE",
                "MODE_GAP",
                f"正式斗地主 canonical factory 现场自检失败："
                f"{type(exc).__name__}:{exc}",
            )
        )
    if not mode_runtime_reachable:
        blockers.append(
            FormalDoudizhuBlocker(
                "FORMAL_DOUDIZHU_RUNTIME_NOT_REACHABLE",
                "MODE_GAP",
                "正式斗地主模式不能从canonical factory到达统一生产核心",
            )
        )
    if not global_card_semantics_complete:
        blockers.append(
            FormalDoudizhuBlocker(
                "FORMAL_DOUDIZHU_CARD_SEMANTICS_INCOMPLETE",
                "CARD_GAP",
                "正式斗地主依赖C2全局卡牌语义闭合（38/38），当前不满足",
            )
        )
    from .production_replay import (
        SUPPORTED_REPLAY_MODES,
        record_reference_production_batch,
        reexecute_production_replay,
    )

    replay_supported = (
        callable(record_reference_production_batch)
        and callable(reexecute_production_replay)
        and FORMAL_NO_SKILL_DOUDIZHU_MODE in SUPPORTED_REPLAY_MODES
    )
    if not replay_supported:
        blockers.append(
            FormalDoudizhuBlocker(
                "FORMAL_DOUDIZHU_REPLAY_UNSUPPORTED",
                "MODE_GAP",
                "严格回放不支持正式斗地主模式（含平局终局与阵营映射）",
            )
        )
    unsupported_rules = len(blockers)
    approximation_count = 0
    mode_implemented = mode_runtime_reachable and not blockers
    ready = (
        mode_implemented
        and replay_supported
        and global_card_semantics_complete
        and unsupported_rules == 0
        and approximation_count == 0
    )
    return FormalDoudizhuReadiness(
        mode_id=FORMAL_NO_SKILL_DOUDIZHU_MODE,
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
        formal_doudizhu_no_skill_ready=ready,
        doudizhu_ready=ready,
        client_timeout_score_adjudication=False,
        blockers=tuple(blockers),
    )


__all__ = [
    "FORMAL_NO_SKILL_DOUDIZHU_MODE",
    "FormalDoudizhuBlocker",
    "FormalDoudizhuConfiguration",
    "FormalDoudizhuConfigurationError",
    "FormalDoudizhuReadiness",
    "FormalDoudizhuSession",
    "DoudizhuModePolicy",
    "DoudizhuOutcomePolicy",
    "TrustedFormalDoudizhuConfiguration",
    "assert_trusted_formal_doudizhu_configuration",
    "inspect_formal_doudizhu_readiness",
]
