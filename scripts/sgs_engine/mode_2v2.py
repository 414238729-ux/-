# -*- coding: utf-8 -*-
"""POST-B C3：正式无武将技能 2v2 模式层。

本模块不是第二套引擎：2v2 只提供 mode profile / team 模型 /
OutcomePolicy / mode policy（初始化与阶段钩子）/ 可见性配置，全部消费
C1/C2 的统一生产核心（ProductionBasicCardBatch、PlayerTopology、
OutcomePolicy、既有 events/actions/damage/dying/death/phase loop）。

规则源：Knowledge《三国杀模式规则》第 2 章 2v2 排位模式（当前确认），
含 2.9 胜利条件、2.10 初始体力、2.11 牌堆耗尽平局、2.12 客户端30分钟
（CONFIRMED_OUT_OF_SIMULATION_SCOPE，本轮不实现墙钟/评分裁定）。
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
from .production_batch import ProductionBasicCardBatch

FORMAL_NO_SKILL_2V2_MODE = "formal_no_skill_2v2"

_TEAM_A = "team_a"  # 初始1+4号位
_TEAM_B = "team_b"  # 初始2+3号位

_SEAT_TEAM_IDS: Mapping[int, str] = MappingProxyType(
    {1: _TEAM_A, 2: _TEAM_B, 3: _TEAM_B, 4: _TEAM_A}
)

_TRUSTED_2V2_CAPABILITY = object()


class Formal2v2ConfigurationError(ValueError):
    """正式 2v2 配置非法。"""


@dataclass(frozen=True, slots=True)
class Formal2v2Configuration:
    """正式 no-skill 2v2 的 canonical profile（规则源：《三国杀模式规则》§2）。

    座次顺序=player_ids 顺序（1..4号位）；队伍由初始座次固定（1+4、2+3），
    初始化后不变。初始手牌按座次 3/4/4/5（§2.3）；测试角色基础体力 4/4
    （§2.10：模式不修改基础属性）；先手=1号位（§2.2）；默认禁手气卡
    （§2.5）；4号位首轮“飞扬”（§2.6）；死亡奖励：存活队友摸1张（§2.7）。
    """

    player_ids: tuple[str, str, str, str]
    base_hp: tuple[int, int, int, int] = (4, 4, 4, 4)
    base_max_hp: tuple[int, int, int, int] = (4, 4, 4, 4)
    initial_hand_counts: tuple[int, int, int, int] = (3, 4, 4, 5)
    hand_qi_ka_allowed: bool = False
    feiyang_seat: int = 4
    feiyang_first_round_only: bool = True
    death_reward_draw_count: int = 1
    deck_supply_mode: str = "no_reshuffle_draw"

    def __post_init__(self) -> None:
        if len(self.player_ids) != 4:
            raise Formal2v2ConfigurationError("正式2v2必须恰好4名角色")
        if any(not isinstance(value, str) or not value.strip() for value in self.player_ids):
            raise Formal2v2ConfigurationError("player_ids必须是非空字符串")
        if len(set(self.player_ids)) != 4:
            raise Formal2v2ConfigurationError("player_ids不能重复")
        for label, values in (
            ("base_hp", self.base_hp),
            ("base_max_hp", self.base_max_hp),
            ("initial_hand_counts", self.initial_hand_counts),
        ):
            if len(values) != 4 or any(
                isinstance(value, bool) or not isinstance(value, int) or value < 1
                for value in values
            ):
                raise Formal2v2ConfigurationError(f"{label}必须是4个正整数")
        if any(
            hp > max_hp
            for hp, max_hp in zip(self.base_hp, self.base_max_hp)
        ):
            raise Formal2v2ConfigurationError("初始体力不能高于体力上限")
        if sum(self.initial_hand_counts) != 16:
            raise Formal2v2ConfigurationError(
                "正式2v2初始手牌按座次3/4/4/5合计16张（§2.3）"
            )
        if self.deck_supply_mode != "no_reshuffle_draw":
            raise Formal2v2ConfigurationError(
                "正式2v2牌堆供给口径必须是no_reshuffle_draw（§2.11）"
            )
        if not isinstance(self.hand_qi_ka_allowed, bool):
            raise Formal2v2ConfigurationError("hand_qi_ka_allowed必须是布尔值")
        if not isinstance(self.feiyang_seat, int) or self.feiyang_seat not in (
            1,
            2,
            3,
            4,
        ):
            raise Formal2v2ConfigurationError("feiyang_seat必须是1..4座次")
        if not isinstance(self.feiyang_first_round_only, bool):
            raise Formal2v2ConfigurationError("feiyang_first_round_only必须是布尔值")
        if not isinstance(self.death_reward_draw_count, int) or self.death_reward_draw_count < 0:
            raise Formal2v2ConfigurationError("死亡奖励摸牌数必须是非负整数")
        object.__setattr__(
            self,
            "player_ids",
            tuple(value.strip() for value in self.player_ids),
        )

    def team_of(self, seat: int) -> str:
        """按初始座次返回队伍ID（1+4=A、2+3=B；§2.1 当前确认）。"""
        team = _SEAT_TEAM_IDS.get(seat)
        if team is None:
            raise Formal2v2ConfigurationError(f"座次{seat!r}不是正式2v2座次")
        return team

    def teams_by_player(self) -> Mapping[str, str]:
        return MappingProxyType(
            {
                player_id: self.team_of(index + 1)
                for index, player_id in enumerate(self.player_ids)
            }
        )

    def teammate_of(self, player_id: str) -> str:
        teams = self.teams_by_player()
        team = teams[player_id]
        for candidate, candidate_team in teams.items():
            if candidate != player_id and candidate_team == team:
                return candidate
        raise Formal2v2ConfigurationError(
            f"角色{player_id!r}没有合法队友"
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": "formal-no-skill-2v2-configuration-v1",
            "player_ids": list(self.player_ids),
            "base_hp": list(self.base_hp),
            "base_max_hp": list(self.base_max_hp),
            "initial_hand_counts": list(self.initial_hand_counts),
            "hand_qi_ka_allowed": self.hand_qi_ka_allowed,
            "feiyang_seat": self.feiyang_seat,
            "feiyang_first_round_only": self.feiyang_first_round_only,
            "death_reward_draw_count": self.death_reward_draw_count,
            "deck_supply_mode": self.deck_supply_mode,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "Formal2v2Configuration":
        if not isinstance(value, Mapping):
            raise Formal2v2ConfigurationError("正式2v2配置必须是JSON对象")
        if set(value) != {
            "schema",
            "player_ids",
            "base_hp",
            "base_max_hp",
            "initial_hand_counts",
            "hand_qi_ka_allowed",
            "feiyang_seat",
            "feiyang_first_round_only",
            "death_reward_draw_count",
            "deck_supply_mode",
        }:
            raise Formal2v2ConfigurationError("正式2v2配置字段集不合法")
        if value["schema"] != "formal-no-skill-2v2-configuration-v1":
            raise Formal2v2ConfigurationError("正式2v2配置schema不受支持")
        return cls(
            player_ids=tuple(value["player_ids"]),  # type: ignore[arg-type]
            base_hp=tuple(value["base_hp"]),  # type: ignore[arg-type]
            base_max_hp=tuple(value["base_max_hp"]),  # type: ignore[arg-type]
            initial_hand_counts=tuple(value["initial_hand_counts"]),  # type: ignore[arg-type]
            hand_qi_ka_allowed=bool(value["hand_qi_ka_allowed"]),
            feiyang_seat=int(value["feiyang_seat"]),  # type: ignore[arg-type]
            feiyang_first_round_only=bool(value["feiyang_first_round_only"]),
            death_reward_draw_count=int(value["death_reward_draw_count"]),  # type: ignore[arg-type]
            deck_supply_mode=str(value["deck_supply_mode"]),
        )

    @staticmethod
    def formal_profile() -> "TrustedFormal2v2Configuration":
        """canonical formal no-skill 2v2 profile（唯一正式来源）。"""
        return _canonical_formal_2v2_profile_value()

    @classmethod
    def from_canonical_profile_value(
        cls, value: Mapping[str, object]
    ) -> "Formal2v2Configuration":
        """校验 payload 与 canonical formal profile 完全一致后返回可信配置。

        replay／strict reexecute 加载正式记录时验证的是 canonical profile
        内容本身（逐字段深比较，经 canonical JSON 归一化后元组/列表等价），
        而不是让 payload 自行获得 trusted provenance。任何字段缺失、多余
        或数值不同都失败关闭。
        """
        from json import dumps, loads

        from .replay import canonical_json

        canonical_value = loads(
            dumps(cls.formal_profile().to_dict(), sort_keys=True)
        )
        submitted = loads(canonical_json(value))
        if submitted != canonical_value:
            raise Formal2v2ConfigurationError(
                "正式2v2配置必须与项目 canonical formal profile 完全一致；"
                "payload 不能自行获得可信规则来源"
            )
        return cls.formal_profile()


class TrustedFormal2v2Configuration(Formal2v2Configuration):
    """仅由模块内 canonical factory 构造的 trusted 配置。

    调用方通过 from_dict / 普通构造 / 低层反射伪造同值对象都不能取得
    trusted provenance；会话边界用 exact type + capability token +
    canonical value 三项校验（与 Milestone B formal duel 同一设计）。
    """

    _capability_token: object = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        super().__post_init__()
        object.__setattr__(self, "_capability_token", _TRUSTED_2V2_CAPABILITY)


def _canonical_formal_2v2_profile_value() -> "TrustedFormal2v2Configuration":
    return TrustedFormal2v2Configuration(
        player_ids=("p1", "p2", "p3", "p4"),
        base_hp=(4, 4, 4, 4),
        base_max_hp=(4, 4, 4, 4),
        initial_hand_counts=(3, 4, 4, 5),
        hand_qi_ka_allowed=False,
        feiyang_seat=4,
        feiyang_first_round_only=True,
        death_reward_draw_count=1,
        deck_supply_mode="no_reshuffle_draw",
    )


def assert_trusted_formal_2v2_configuration(
    configuration: Formal2v2Configuration,
) -> None:
    """正式 2v2 trusted authority boundary（exact type + capability + value）。"""
    if not isinstance(configuration, Formal2v2Configuration):
        raise TypeError("正式2v2会话必须接收Formal2v2Configuration")
    if type(configuration) is not TrustedFormal2v2Configuration:
        raise Formal2v2ConfigurationError(
            "正式2v2结果只接受内部 canonical factory 返回的 "
            "TrustedFormal2v2Configuration（exact type 校验）；调用方配置"
            "不能自我授权"
        )
    if (
        getattr(configuration, "_capability_token", None)
        is not _TRUSTED_2V2_CAPABILITY
    ):
        raise Formal2v2ConfigurationError(
            "正式2v2结果只接受真实持有模块私有 capability token 的 "
            "TrustedFormal2v2Configuration（capability identity 校验）"
        )
    if configuration.to_dict() != _canonical_formal_2v2_profile_value().to_dict():
        raise Formal2v2ConfigurationError(
            "正式2v2配置的 profile value 必须精确等于项目 canonical "
            "formal no-skill 2v2 profile；type/token 正确但值非 canonical "
            "的对象同样失败关闭（canonical value invariant）"
        )


@dataclass(frozen=True, slots=True)
class TwoVsTwoOutcomePolicy(OutcomePolicy):
    """正式 2v2 胜负策略（§2.9 当前确认）。

    一方两名角色全部确认死亡后另一方立即获胜；获胜方以队伍ID
    （team_a / team_b）作为终局胜者标识进入 VICTORY 事件与回放 outcome。
    逐次死亡顺序判定，不建立“同时死亡”抽象；两队同时无存活成员在顺序
    确认死亡下不可达，防御性失败关闭。牌堆耗尽平局：winner=None +
    draw_finish_reason（§2.11）。
    """

    teams: Mapping[str, str] = MappingProxyType({})

    def __init__(self, teams: Mapping[str, str]) -> None:
        if not isinstance(teams, Mapping) or not teams:
            raise Formal2v2ConfigurationError("2v2胜负策略需要非空队伍映射")
        if len(set(teams.values())) != 2:
            raise Formal2v2ConfigurationError("正式2v2必须恰好两个队伍")
        object.__setattr__(self, "policy_id", "formal_no_skill_2v2")
        object.__setattr__(self, "teams", MappingProxyType(dict(teams)))

    def resolve_winner_after_death(
        self, topology: PlayerTopology, dying_id: str
    ) -> str | None:
        alive_by_team: dict[str, int] = {}
        for player in topology.players:
            team = self.teams.get(player.player_id)
            if team is None:
                raise UnsupportedRuleError(
                    f"角色{player.player_id!r}未注册正式2v2队伍"
                )
            if player.alive:
                alive_by_team[team] = alive_by_team.get(team, 0) + 1
        eliminated = [
            team for team in set(self.teams.values()) if alive_by_team.get(team, 0) == 0
        ]
        if len(eliminated) == 0:
            return None
        if len(eliminated) == 1:
            winners = [
                team for team in set(self.teams.values()) if team != eliminated[0]
            ]
            return winners[0]
        raise UnsupportedRuleError(
            "正式2v2顺序确认死亡下两队不应同时无存活成员；失败关闭"
        )

    @property
    def finish_reason(self) -> str:
        return "team_eliminated"

    @property
    def draw_finish_reason(self) -> str:
        return "2v2_draw_deck_exhausted"


@dataclass(frozen=True, slots=True)
class TwoVsTwoModePolicy:
    """正式 2v2 模式层：初始化输入与阶段钩子（统一生产核心消费）。

    - initial_hand_counts / first_player_id：由 canonical profile 提供；
    - deck_supply_mode：no_reshuffle_draw（§2.11，核心按此执行原子取牌
      与牌堆耗尽平局）；
    - death_reward：确认死亡后存活队友立即摸 1 张（§2.7），只在游戏
      继续（胜负未成立）时触发；
    - feiyang：4号位首轮判定阶段开始窗口（§2.6），由核心在判定阶段
      入口调用 judgment_phase_entry_hook 进入。
    """

    configuration: Formal2v2Configuration
    teams: Mapping[str, str] = MappingProxyType({})

    def __init__(self, configuration: Formal2v2Configuration) -> None:
        if not isinstance(configuration, Formal2v2Configuration):
            raise TypeError("2v2模式层必须接收Formal2v2Configuration")
        object.__setattr__(self, "configuration", configuration)
        object.__setattr__(
            self, "teams", MappingProxyType(dict(configuration.teams_by_player()))
        )

    @property
    def identity(self) -> str:
        return "mode:formal_no_skill_2v2"

    @property
    def initial_hand_counts(self) -> tuple[int, ...]:
        return self.configuration.initial_hand_counts

    @property
    def first_player_id(self) -> str:
        return self.configuration.player_ids[0]

    @property
    def deck_supply_mode(self) -> str:
        return self.configuration.deck_supply_mode

    def team_of(self, player_id: str) -> str:
        team = self.teams.get(player_id)
        if team is None:
            raise Formal2v2ConfigurationError(
                f"角色{player_id!r}未注册正式2v2队伍"
            )
        return team

    def teammate_of(self, player_id: str) -> str:
        return self.configuration.teammate_of(player_id)

    def seat_of(self, player_id: str) -> int:
        """按初始化 player_ids 顺序返回座次（1-based）。"""
        try:
            return self.configuration.player_ids.index(player_id) + 1
        except ValueError as exc:
            raise Formal2v2ConfigurationError(
                f"角色{player_id!r}未注册正式2v2座次"
            ) from exc

    def feiyang_available(
        self, *, player_id: str, seat: int, turn_number: int
    ) -> bool:
        """4号位首轮“飞扬”可用性（§2.6：每回合限一次、按回合独立额度）。"""
        del player_id
        return (
            seat == self.configuration.feiyang_seat
            and (
                not self.configuration.feiyang_first_round_only
                or turn_number <= 4
            )
        )

    def death_confirmed_hook(
        self,
        session: object,
        state: GameState,
        runtime: object,
        dying_id: str,
        death_context: object | None = None,
    ) -> tuple[GameState, object]:
        """POST-B C3：死亡确认钩子（§2.7 当前确认：存活队友摸1张）。

        只在胜负未成立（winner=None 继续分支）时由生产核心调用。奖励
        摸牌复用核心统一摸牌事务（原子预检→完整取牌→完成后牌堆为0立即
        平局）：预检不足时核心在死亡已成立的权威状态上就地形成平局，
        绝不执行半截取牌。返回 (state, runtime)，平局时 runtime 携带
        game_over_reason 与 FINISHED 阶段。
        """
        del death_context
        count = self.configuration.death_reward_draw_count
        if count <= 0:
            return state, runtime
        teammate = self.teammate_of(dying_id)
        if not state.players_by_id[teammate].alive:
            raise Formal2v2ConfigurationError(
                "正式2v2死亡奖励需要存活队友；失败关闭"
            )
        reward_draw = getattr(session, "_mode_death_reward_draw")
        return reward_draw(
            state,
            runtime,
            teammate,
            count,
            reason="death_reward_teammate_draw",
        )


# ----------------------------------------------------------------------
# POST-B C3：正式2v2 canonical 会话与现场就绪门禁
# ----------------------------------------------------------------------

_FORMAL_2V2_EXECUTION_RELEASED = True

_CANONICAL_2V2_TEST_CHARACTER = "soldier"


class Formal2v2Session(ProductionBasicCardBatch):
    """正式 no-skill 2v2 canonical 会话（不是第二套引擎）。

    直接复用统一生产核心 ``ProductionBasicCardBatch``：只替换模式ID、
    注入 canonical profile（座次/队伍/初始手牌/先手/体力）、队伍胜负
    策略（TwoVsTwoOutcomePolicy）与模式层（TwoVsTwoModePolicy：死亡
    奖励、飞扬、no_reshuffle_draw 牌堆供给）。测试角色 = 无技能士兵
    档案（base_hp/base_max_hp=4/4，§2.10：模式不修改基础属性；性别
    NONE 使雌雄双股剑“异性”判定在测试档案下不触发）。
    """

    MODE_ID = FORMAL_NO_SKILL_2V2_MODE

    def __init__(
        self,
        *,
        seed: int,
        configuration: Formal2v2Configuration,
        analysis_only: bool = False,
        session_id: str | None = None,
        session_secret: bytes | None = None,
    ) -> None:
        if type(self) is not _CANONICAL_2V2_SESSION_TYPE:
            raise TypeError(
                "正式2v2 canonical 会话不允许通过子类覆写释放或配置边界"
            )
        if not isinstance(configuration, Formal2v2Configuration):
            raise TypeError("正式2v2会话必须接收Formal2v2Configuration")
        if not isinstance(analysis_only, bool):
            raise TypeError("analysis_only必须是布尔值")
        if not analysis_only:
            assert_trusted_formal_2v2_configuration(configuration)
        if not _FORMAL_2V2_EXECUTION_RELEASED:
            raise Formal2v2ConfigurationError(
                "正式2v2仍有模式/回放门禁未关闭，禁止生成正式结果"
            )
        self._formal_configuration = configuration
        self._analysis_only = analysis_only
        super().__init__(
            seed=seed,
            player_hp=configuration.base_hp,
            player_max_hp=configuration.base_max_hp,
            player_ids=configuration.player_ids,
            outcome_policy=TwoVsTwoOutcomePolicy(
                configuration.teams_by_player()
            ),
            initial_hand_counts=configuration.initial_hand_counts,
            first_player_id=configuration.player_ids[0],
            mode_policy=TwoVsTwoModePolicy(configuration),
            shuffle=True,
            session_id=session_id,
            session_secret=session_secret,
        )
        soldier = CharacterMetadata(
            _CANONICAL_2V2_TEST_CHARACTER,
            CharacterGender.NONE,
            CharacterGender.NONE,
        )
        players = tuple(
            replace(player, character=soldier)
            for player in self.state.players
        )
        self._state = replace(self.state, players=players)

    @property
    def formal_configuration(self) -> Formal2v2Configuration:
        return self._formal_configuration

    @property
    def analysis_only(self) -> bool:
        return self._analysis_only

    @property
    def formal_result_eligible(self) -> bool:
        return (
            _FORMAL_2V2_EXECUTION_RELEASED
            and not self._analysis_only
            and isinstance(
                self._formal_configuration, TrustedFormal2v2Configuration
            )
        )


_CANONICAL_2V2_SESSION_TYPE = Formal2v2Session


@dataclass(frozen=True, slots=True)
class Formal2v2Blocker:
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
class Formal2v2Readiness:
    """正式 no-skill 2v2 现场就绪状态（静态执行资格；不是验收证据）。"""

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
    # 2v2 正式门禁：静态执行资格（canonical factory 可达 + 卡牌语义
    # 复用 C2 全局闭合 + 严格回放支持）。unsupported_rules 由现场
    # blocker 计数派生，不得硬编码 0 自我证明。True 只表示“可以开始
    # 正式执行”，不代表 §2.11 全部 sibling 路径已由本函数证明；那些
    # 路径由 production regression tests 作为证据。也不包含客户端
    # 30分钟墙钟/评分裁定（CONFIRMED_OUT_OF_SIMULATION_SCOPE）。
    formal_2v2_no_skill_ready: bool
    # 兼容轨命名：2v2_ready == formal_2v2_no_skill_ready（同一门禁）。
    ready_2v2: bool
    # 客户端30分钟裁定（§2.12）：永不进入模拟门禁。
    client_timeout_score_adjudication: bool
    blockers: tuple[Formal2v2Blocker, ...]

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
            "formal_2v2_no_skill_ready": self.formal_2v2_no_skill_ready,
            "2v2_ready": self.ready_2v2,
            "client_timeout_score_adjudication": (
                self.client_timeout_score_adjudication
            ),
            "blockers": [item.to_dict() for item in self.blockers],
        }


def inspect_formal_2v2_readiness() -> Formal2v2Readiness:
    """从当前正式牌堆、注册表与 canonical factory 现场派生 2v2 就绪状态。

    ``2v2_ready`` 的精确定义：现场 canonical 会话可达 + 160 张正式牌堆 +
    4 名角色座次/队伍/初始手牌/先手符合 canonical profile + 卡牌语义
    复用 C2 全局闭合（38/38）+ 严格回放支持正式2v2模式 + 现场 blocker
    派生的 unsupported/approximation 为 0。它是静态执行资格，不是
    §2.11 平局 sibling 路径的自我证明；那些路径由
    ``tests/test_post_b_c3_2v2_draw_remediation.py`` 等 production
    regression 作为证据。绝不包含客户端30分钟墙钟/评分裁定（§2.12）。
    """
    from .production_batch import ProductionPhase
    from .production_cards import FormalCardRegistry

    registry = FormalCardRegistry.from_formal_csv()
    registered_keys = frozenset(registry.implemented_card_keys)
    deck_keys = frozenset(record.card_key for record in registry.records)
    global_card_semantics_complete = (
        len(registry.records) == 160
        and len(deck_keys) == 38
        and registered_keys == deck_keys
    )
    blockers: list[Formal2v2Blocker] = []
    mode_runtime_reachable = False
    try:
        probe = Formal2v2Session(
            seed=0,
            configuration=Formal2v2Configuration.formal_profile(),
            analysis_only=True,
            session_id="formal-2v2-readiness-probe",
            session_secret=b"formal-2v2-readiness-probe-00001",  # 32字节
        )
        state = probe.state
        hand_sizes = tuple(
            len(state.card_ids_in(ZoneRef.hand(player_id)))
            for player_id in ("p1", "p2", "p3", "p4")
        )
        mode_runtime_reachable = (
            probe.mode_id == FORMAL_NO_SKILL_2V2_MODE
            and len(state.cards) == 160
            and len(state.players) == 4
            and hand_sizes == (3, 4, 4, 5)
            and probe.first_player_id == "p1"
            and dict(probe.mode_policy.teams)
            == {"p1": "team_a", "p2": "team_b", "p3": "team_b", "p4": "team_a"}
            and probe.deck_supply_mode == "no_reshuffle_draw"
            and probe.outcome_policy is not None
            and probe.outcome_policy.identity()
            == "outcome:formal_no_skill_2v2"
            and probe.runtime.phase is ProductionPhase.PREPARE
        )
    except Exception as exc:  # pragma: no cover - 现场损坏进入结构化阻塞
        blockers.append(
            Formal2v2Blocker(
                "FORMAL_2V2_FACTORY_UNREACHABLE",
                "MODE_GAP",
                f"正式2v2 canonical factory 现场自检失败："
                f"{type(exc).__name__}:{exc}",
            )
        )
    if not mode_runtime_reachable:
        blockers.append(
            Formal2v2Blocker(
                "FORMAL_2V2_RUNTIME_NOT_REACHABLE",
                "MODE_GAP",
                "正式2v2模式不能从canonical factory到达统一生产核心",
            )
        )
    if not global_card_semantics_complete:
        blockers.append(
            Formal2v2Blocker(
                "FORMAL_2V2_CARD_SEMANTICS_INCOMPLETE",
                "CARD_GAP",
                "正式2v2依赖C2全局卡牌语义闭合（38/38），当前不满足",
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
        and FORMAL_NO_SKILL_2V2_MODE in SUPPORTED_REPLAY_MODES
    )
    if not replay_supported:
        blockers.append(
            Formal2v2Blocker(
                "FORMAL_2V2_REPLAY_UNSUPPORTED",
                "MODE_GAP",
                "严格回放不支持正式2v2模式（含平局终局与队伍映射）",
            )
        )
    # 由现场 blocker 派生，禁止硬编码 0 当作“规则已全部正确”的证明。
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
    return Formal2v2Readiness(
        mode_id=FORMAL_NO_SKILL_2V2_MODE,
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
        formal_2v2_no_skill_ready=ready,
        ready_2v2=ready,
        client_timeout_score_adjudication=False,
        blockers=tuple(blockers),
    )


__all__ = [
    "FORMAL_NO_SKILL_2V2_MODE",
    "Formal2v2Blocker",
    "Formal2v2Configuration",
    "Formal2v2ConfigurationError",
    "Formal2v2Readiness",
    "Formal2v2Session",
    "TwoVsTwoModePolicy",
    "TwoVsTwoOutcomePolicy",
    "TrustedFormal2v2Configuration",
    "assert_trusted_formal_2v2_configuration",
    "inspect_formal_2v2_readiness",
]
