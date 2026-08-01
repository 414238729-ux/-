"""附件确认的武将 AI V2.1 轻量决策工具。

这里只提供可解释的枚举和边际收益比较，不把计算策略写成技能规则。
调用方传入的收益必须来自当前角色依法可知的信息；本模块不会读取隐藏牌。
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import permutations, product
from math import isfinite
from typing import Callable, Iterable, Sequence


def _nonempty(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label}必须是非空字符串")
    return value.strip()


def _finite(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{label}必须是有限数值")
    number = float(value)
    if not isfinite(number):
        raise ValueError(f"{label}必须是有限数值")
    return number


@dataclass(frozen=True)
class DianhuaChoice:
    ordered_card_ids: tuple[str, ...]
    score: float
    evaluated_permutations: int


def optimize_dianhua_order(
    viewed_card_ids: Sequence[str],
    public_information_scorer: Callable[[tuple[str, ...]], float],
) -> DianhuaChoice:
    """对至多四张点化牌全排列，并按合法公开信息评分。"""

    if isinstance(viewed_card_ids, (str, bytes)) or not isinstance(
        viewed_card_ids, Sequence
    ):
        raise TypeError("点化牌必须是实体牌标识序列")
    cards = tuple(_nonempty(card, "点化实体牌标识") for card in viewed_card_ids)
    if len(cards) > 4:
        raise ValueError("点化全排列最多处理四张牌")
    if len(set(cards)) != len(cards):
        raise ValueError("点化实体牌标识不能重复")
    if not callable(public_information_scorer):
        raise TypeError("点化评分器必须可调用")
    orders = tuple(permutations(cards)) if cards else ((),)
    best_order = orders[0]
    best_score = _finite(public_information_scorer(best_order), "点化方案得分")
    for order in orders[1:]:
        score = _finite(public_information_scorer(order), "点化方案得分")
        if score > best_score:
            best_order, best_score = order, score
    return DianhuaChoice(best_order, best_score, len(orders))


@dataclass(frozen=True)
class JinfanCardOption:
    card_id: str
    suit: str
    card_name: str
    preserve_value: float = 0.0
    replacement_expectation: float = 0.0
    slot_value: float = 0.0
    clearing_value: float = 0.0
    sheque_value: float = 0.0
    zhangba_value: float = 0.0
    public_information_cost: float = 0.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "card_id", _nonempty(self.card_id, "锦帆实体牌标识"))
        object.__setattr__(self, "card_name", _nonempty(self.card_name, "锦帆牌名"))
        suit = _nonempty(self.suit, "锦帆花色")
        if suit not in {"♠", "♣", "♥", "♦"}:
            raise ValueError("锦帆花色只能是♠、♣、♥或♦")
        object.__setattr__(self, "suit", suit)
        for name in (
            "preserve_value",
            "replacement_expectation",
            "slot_value",
            "clearing_value",
            "sheque_value",
            "zhangba_value",
            "public_information_cost",
        ):
            object.__setattr__(self, name, _finite(getattr(self, name), name))

    @property
    def net_value(self) -> float:
        return (
            self.replacement_expectation
            + self.slot_value
            + self.clearing_value
            + self.sheque_value
            + self.zhangba_value
            - self.preserve_value
            - self.public_information_cost
        )


@dataclass(frozen=True)
class JinfanChoice:
    selected_cards: tuple[JinfanCardOption, ...]
    score: float
    evaluated_combinations: int


def optimize_jinfan_storage(
    cards: Sequence[JinfanCardOption],
    *,
    max_new_bells: int = 4,
) -> JinfanChoice:
    """联合枚举选择哪些花色、每种花色的哪张牌，不按花色逐项贪心。"""

    if isinstance(cards, (str, bytes)) or not isinstance(cards, Sequence):
        raise TypeError("锦帆候选必须是牌选项序列")
    if isinstance(max_new_bells, bool) or not isinstance(max_new_bells, int):
        raise TypeError("锦帆新增上限必须是整数")
    if not 0 <= max_new_bells <= 4:
        raise ValueError("锦帆新增上限必须在0至4之间")
    normalized = tuple(cards)
    if any(not isinstance(card, JinfanCardOption) for card in normalized):
        raise TypeError("锦帆候选必须是 JinfanCardOption")
    ids = [card.card_id for card in normalized]
    if len(ids) != len(set(ids)):
        raise ValueError("锦帆候选实体牌标识不能重复")
    by_suit = {
        suit: tuple(card for card in normalized if card.suit == suit)
        for suit in ("♠", "♣", "♥", "♦")
    }
    combinations = tuple(
        choice
        for choice in product(*( (None,) + by_suit[suit] for suit in by_suit))
        if sum(card is not None for card in choice) <= max_new_bells
    )
    best_cards: tuple[JinfanCardOption, ...] = ()
    best_score = 0.0
    for choice in combinations:
        selected = tuple(card for card in choice if card is not None)
        score = sum(card.net_value for card in selected)
        if score > best_score:
            best_cards, best_score = selected, score
    return JinfanChoice(best_cards, best_score, len(combinations))


@dataclass(frozen=True)
class ShequeFactors:
    kill_value: float = 0.0
    target_on_damage_benefit: float = 0.0
    zhangqiying_gouchen_cost: float = 0.0
    identity_exposure_cost: float = 0.0
    slash_resource_cost: float = 0.0

    def __post_init__(self) -> None:
        for name, value in vars(self).items():
            object.__setattr__(self, name, _finite(value, name))


def sheque_net_value(factors: ShequeFactors) -> float:
    if not isinstance(factors, ShequeFactors):
        raise TypeError("射却因素必须是 ShequeFactors")
    return (
        factors.kill_value
        - factors.target_on_damage_benefit
        - factors.zhangqiying_gouchen_cost
        - factors.identity_exposure_cost
        - factors.slash_resource_cost
    )


@dataclass(frozen=True)
class ZhangbaMaterialOption:
    card_id: str
    preserve_value: float = 0.0
    bell_replacement_value: float = 0.0
    slot_clearing_value: float = 0.0
    defense_value: float = 0.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "card_id", _nonempty(self.card_id, "丈八材料标识"))
        for name in (
            "preserve_value",
            "bell_replacement_value",
            "slot_clearing_value",
            "defense_value",
        ):
            object.__setattr__(self, name, _finite(getattr(self, name), name))

    @property
    def opportunity_cost(self) -> float:
        return (
            self.preserve_value
            + self.defense_value
            - self.bell_replacement_value
            - self.slot_clearing_value
        )


def choose_zhangba_materials(
    options: Sequence[ZhangbaMaterialOption],
) -> tuple[ZhangbaMaterialOption, ZhangbaMaterialOption]:
    """从实体牌中选恰好两张总机会成本最低的丈八材料。"""

    if isinstance(options, (str, bytes)) or not isinstance(options, Sequence):
        raise TypeError("丈八材料候选必须是序列")
    normalized = tuple(options)
    if len(normalized) < 2:
        raise ValueError("丈八蛇矛转化需要两张实体牌")
    if any(not isinstance(item, ZhangbaMaterialOption) for item in normalized):
        raise TypeError("丈八材料必须是 ZhangbaMaterialOption")
    if len({item.card_id for item in normalized}) != len(normalized):
        raise ValueError("丈八材料实体牌标识不能重复")
    pairs = tuple(
        (normalized[i], normalized[j])
        for i in range(len(normalized))
        for j in range(i + 1, len(normalized))
    )
    return min(pairs, key=lambda pair: sum(item.opportunity_cost for item in pair))


@dataclass(frozen=True)
class LingrenOpportunity:
    target_id: str
    expected_value: float
    known_hand_fraction: float = 0.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "target_id", _nonempty(self.target_id, "凌人目标"))
        object.__setattr__(self, "expected_value", _finite(self.expected_value, "凌人预期收益"))
        known = _finite(self.known_hand_fraction, "凌人手牌信息完整度")
        if not 0 <= known <= 1:
            raise ValueError("凌人手牌信息完整度必须在0至1之间")
        object.__setattr__(self, "known_hand_fraction", known)

    @property
    def decision_value(self) -> float:
        return self.expected_value + 0.25 * self.known_hand_fraction


def should_use_lingren_now(
    current: LingrenOpportunity,
    possible_later: Sequence[LingrenOpportunity] = (),
    *,
    play_phase_ending: bool = False,
) -> bool:
    """凌人只在当前机会不劣于可预见后续，或阶段将结束时使用。"""

    if not isinstance(current, LingrenOpportunity):
        raise TypeError("当前凌人机会必须是 LingrenOpportunity")
    if not isinstance(play_phase_ending, bool):
        raise TypeError("出牌阶段是否即将结束必须是布尔值")
    later = tuple(possible_later)
    if any(not isinstance(item, LingrenOpportunity) for item in later):
        raise TypeError("后续凌人机会必须是 LingrenOpportunity")
    if play_phase_ending or not later:
        return current.decision_value > 0
    return current.decision_value >= max(item.decision_value for item in later)


@dataclass(frozen=True)
class WeaponSwapStep:
    weapon_name: str
    draw_gain: float = 0.0
    kill_value: float = 0.0
    retained_weapon_value: float = 0.0
    defense_and_range_value: float = 0.0
    replacement_tempo_cost: float = 0.0
    replacement_loss: float = 0.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "weapon_name", _nonempty(self.weapon_name, "武器名称"))
        for name in (
            "draw_gain",
            "kill_value",
            "retained_weapon_value",
            "defense_and_range_value",
            "replacement_tempo_cost",
            "replacement_loss",
        ):
            object.__setattr__(self, name, _finite(getattr(self, name), name))

    @property
    def marginal_value(self) -> float:
        return (
            self.draw_gain
            + self.kill_value
            + self.retained_weapon_value
            + self.defense_and_range_value
            - self.replacement_tempo_cost
            - self.replacement_loss
        )


def choose_shamoke_weapon_chain(
    ordered_steps: Sequence[WeaponSwapStep],
) -> tuple[WeaponSwapStep, ...]:
    """在合法武器顺序的各前缀中选净收益最高者；允许完全不换。"""

    if isinstance(ordered_steps, (str, bytes)) or not isinstance(
        ordered_steps, Sequence
    ):
        raise TypeError("武器链必须是有序步骤序列")
    steps = tuple(ordered_steps)
    if any(not isinstance(step, WeaponSwapStep) for step in steps):
        raise TypeError("武器链步骤必须是 WeaponSwapStep")
    best_length = 0
    best_value = 0.0
    running = 0.0
    for index, step in enumerate(steps, start=1):
        running += step.marginal_value
        if running > best_value:
            best_length, best_value = index, running
    return steps[:best_length]
