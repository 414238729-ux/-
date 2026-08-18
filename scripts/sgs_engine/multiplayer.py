# -*- coding: utf-8 -*-
"""多人权威核心基础：玩家拓扑、存活环遍历、回合继任与模式胜负边界。

POST-B C1 的通用化层。本模块不是第二套引擎：它只把正式生产核心中
隐含的“两人假设”收敛为可供 N >= 2 名玩家模式消费的统一权威接口。

依据 Knowledge《三国杀基础术语与通用机制》第 4.1/4.2/6/7/8/11 节与
《三国杀模拟规范》已确认语义：

- 当前存活且仍在游戏中的角色按当前座次组成首尾相接的环（存活角色环）；
- 座次数递增方向（逆时针）为顺序方向；超过最大座次后回到最小座次；
- 已确认死亡的角色退出该环，其原座次编号保留，其他角色不重新编号；
- 回合顺序、多人响应、濒死救援、距离等默认从当前回合角色开始，按
  存活角色环的座次递增方向逐座处理；
- 基础距离取存活角色环上两个方向的边数较小值。

凡 Knowledge 未确认的规则（如具体模式的胜负条件、队友关系），本模块
一律失败关闭，绝不自行推断。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .actions import UnsupportedRuleError
from .model import GameState, PlayerState


@dataclass(frozen=True, slots=True)
class PlayerTopology:
    """N >= 2 固定玩家集合的权威拓扑视图。

    拓扑从不可变 ``GameState`` 派生；玩家初始化后，死亡只更新 ``alive``
    标记，绝不通过重新编号 seat 改变原始身份。所有顺序关系都基于当前
    座次与存活角色环，不使用 ``list.index`` 之类的散落实现。
    """

    players: tuple[PlayerState, ...]

    def __post_init__(self) -> None:
        players = tuple(self.players)
        if len(players) < 2:
            raise UnsupportedRuleError("玩家拓扑至少需要两名玩家")
        if any(not isinstance(player, PlayerState) for player in players):
            raise TypeError("玩家拓扑中的每一项都必须是PlayerState")
        player_ids = [player.player_id for player in players]
        seats = [player.seat for player in players]
        if len(set(player_ids)) != len(player_ids):
            raise UnsupportedRuleError("玩家拓扑中的玩家ID不能重复")
        if len(set(seats)) != len(seats):
            raise UnsupportedRuleError("玩家拓扑中的座次不能重复")
        if sorted(seats) != list(range(1, len(players) + 1)):
            raise UnsupportedRuleError("玩家座次必须从1开始连续编号")
        object.__setattr__(self, "players", players)

    @classmethod
    def from_state(cls, state: GameState) -> "PlayerTopology":
        """从权威不可变状态派生玩家拓扑。"""
        if not isinstance(state, GameState):
            raise TypeError("玩家拓扑来源必须是GameState")
        return cls(tuple(state.players))

    @property
    def player_count(self) -> int:
        return len(self.players)

    @property
    def player_ids(self) -> tuple[str, ...]:
        return tuple(player.player_id for player in self.players)

    def player(self, player_id: str) -> PlayerState:
        for player in self.players:
            if player.player_id == player_id:
                return player
        raise UnsupportedRuleError(f"玩家拓扑中不存在角色{player_id!r}")

    @property
    def alive_players(self) -> tuple[PlayerState, ...]:
        """按当前座次递增排序的存活角色。"""
        return tuple(
            sorted(
                (player for player in self.players if player.alive),
                key=lambda player: player.seat,
            )
        )

    @property
    def alive_ids(self) -> tuple[str, ...]:
        return tuple(player.player_id for player in self.alive_players)

    def is_alive(self, player_id: str) -> bool:
        return self.player(player_id).alive

    def next_alive(self, anchor_id: str) -> str:
        """下一名存活角色：从 anchor 沿座次递增方向寻找，跳过死亡角色并环回。

        依据基础术语第 11 节“下家”定义。anchor 自身必须仍在游戏中。
        """
        anchor = self.player(anchor_id)
        if not anchor.alive:
            raise UnsupportedRuleError(
                f"角色{anchor_id!r}已死亡，不能作为存活环继任锚点"
            )
        ring = self.alive_ids
        index = ring.index(anchor_id)
        return ring[(index + 1) % len(ring)]

    def first_alive_after(self, player_id: str) -> str:
        """从该角色座次之后沿座次递增找到第一名存活角色。

        允许 ``player_id`` 已死亡。与 ``next_alive`` / ``alive_ring_from``
        不同：那两个接口的通用锚点必须存活（失败关闭）。本方法是死亡
        座次之后的存活继任，供调用方先取得合法存活锚点，再进入存活环。
        无存活角色时失败关闭。
        """
        player = self.player(player_id)
        alive = self.alive_players
        if not alive:
            raise UnsupportedRuleError(
                f"角色{player_id!r}座次之后没有存活角色可作为继任锚点"
            )
        for candidate in alive:
            if candidate.seat > player.seat:
                return candidate.player_id
        return alive[0].player_id

    def alive_ring_from(
        self, anchor_id: str, *, include_anchor: bool = True
    ) -> tuple[str, ...]:
        """从 anchor 开始、沿存活角色环座次递增方向的顺序快照。

        Knowledge 第 6/7/8 节：多人同一时机处理顺序默认从当前回合角色
        开始逐座处理。include_anchor=False 时排除 anchor 自身（如群体
        锦囊的“其他角色”顺序）。anchor 已死亡时按失败关闭处理（通用
        顺序锚点必须是仍在游戏中的角色；具体死后技能例外由调用方提供
        专用锚点，本接口不猜测）。
        """
        anchor = self.player(anchor_id)
        if not anchor.alive:
            raise UnsupportedRuleError(
                f"角色{anchor_id!r}已死亡，不能作为存活环顺序锚点"
            )
        ring = self.alive_ids
        index = ring.index(anchor_id)
        ordered = ring[index:] + ring[:index]
        if include_anchor:
            return tuple(ordered)
        return tuple(player_id for player_id in ordered if player_id != anchor_id)

    def all_other_alive_ids(self, anchor_id: str) -> tuple[str, ...]:
        """除 anchor 外的所有存活角色，按从 anchor 开始的座次递增顺序。"""
        return self.alive_ring_from(anchor_id, include_anchor=False)

    def base_seat_distance(self, source_id: str, target_id: str) -> int:
        """存活角色环上的基础距离（两个方向边数的较小值）。

        自己到自己为 0；两名不同存活角色之间最低为 1；死亡角色失败关闭。
        与 scripts/sgs_engine/production_cards.base_seat_distance 保持同一
        权威语义，本接口是拓扑视角的等价入口，供尚未持有完整距离修正
        上下文的调用方使用。
        """
        if source_id == target_id:
            self.player(source_id)
            return 0
        source = self.player(source_id)
        target = self.player(target_id)
        if not source.alive or not target.alive:
            raise UnsupportedRuleError(
                f"角色{source_id!r}或{target_id!r}已死亡；死亡角色不参与距离环"
            )
        ring = self.alive_ids
        source_index = ring.index(source_id)
        target_index = ring.index(target_id)
        span = abs(source_index - target_index)
        distance = min(span, len(ring) - span)
        return max(1, distance)


@dataclass(frozen=True, slots=True)
class OutcomePolicy:
    """模式胜负策略的权威接口（mode-owned victory policy）。

    C1 只建立边界：formal duel 注册 DuelOutcomePolicy；其他 N > 2 模式在
    未注册具体 policy 前，死亡后的胜负判定必须失败关闭，不得自行猜测
    2v2、身份场或最后一人生存等规则。
    """

    policy_id: str

    def resolve_winner_after_death(
        self, topology: PlayerTopology, dying_id: str
    ) -> str | None:
        raise NotImplementedError

    def identity(self) -> str:
        """策略身份（进入 execution snapshot/hash，行为相关）。"""
        return f"outcome:{self.policy_id}"

    @property
    def finish_reason(self) -> str:
        """终局原因标识（进入回放 outcome，行为相关）。"""
        return "opponent_confirmed_dead"

    @property
    def draw_finish_reason(self) -> str | None:
        """平局终局原因标识（POST-B C3）。

        返回 None 表示该策略无平局终局（如 formal duel）；2v2 返回其
        牌堆耗尽平局标识。平局时 winner 为 None，终局原因使用本值。
        """
        return None


@dataclass(frozen=True, slots=True)
class DuelOutcomePolicy(OutcomePolicy):
    """formal 2-player no-skill duel：一名角色确认死亡后，另一名存活角色获胜。"""

    def __init__(self) -> None:
        object.__setattr__(self, "policy_id", "formal_two_player_duel")

    def resolve_winner_after_death(
        self, topology: PlayerTopology, dying_id: str
    ) -> str | None:
        alive = topology.alive_ids
        if len(alive) != 1:
            raise UnsupportedRuleError(
                "formal duel 胜负策略要求恰好剩一名存活角色"
            )
        winner = alive[0]
        if winner == dying_id:
            raise UnsupportedRuleError("已死亡角色不能成为 formal duel 胜利者")
        return winner


def resolve_victory_after_death(
    topology: PlayerTopology,
    dying_id: str,
    *,
    policy: OutcomePolicy | None,
    explicit_two_player_fallback: bool = False,
) -> str | None:
    """死亡后的统一胜负出口：由 mode-owned policy 决定。

    - 注册了 policy：返回 policy 结果；
    - 未注册且 explicit_two_player_fallback 且恰好两名玩家（duel 兼容）：
      返回唯一存活者；
    - 其余情况（含 N > 2 未注册 policy）：失败关闭。

    C1 不把 ``multi_player_production_proven`` 置为 true；N > 2 的正式
    胜负属于后续模式层（C3）。
    """
    if policy is not None:
        return policy.resolve_winner_after_death(topology, dying_id)
    alive = topology.alive_ids
    if explicit_two_player_fallback and topology.player_count == 2 and len(alive) == 1:
        winner = alive[0]
        if winner == dying_id:
            raise UnsupportedRuleError("已死亡角色不能成为胜利者")
        return winner
    raise UnsupportedRuleError(
        f"{topology.player_count}名玩家的对局尚未注册模式胜负策略；"
        "死亡后的胜负判定失败关闭，不得自行猜测2v2、身份场或最后一人生存规则"
    )


__all__ = [
    "DuelOutcomePolicy",
    "OutcomePolicy",
    "PlayerTopology",
    "resolve_victory_after_death",
]
