"""自用可玩配置；规则与候选抽样／控制器参数明确分层。"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from math import isfinite
from typing import Mapping

from .generals import create_authoritative_general_batch_v1_registry


AI_VERSION = "production-heuristic-v1.1"
INFORMATION_VERSION = "public-timer-and-context-qa-v1"
MODE_SEATS = {"duel": 2, "2v2": 4, "doudizhu": 3, "identity5": 5,
              "identity8": 8, "identity8_heir": 8}
CONTROL_MODES = ("ALL_HUMAN", "HUMAN_VS_AI", "AI_VS_AI")
PRODUCTION_GENERALS = ("shamoke", "zhugezhan", "wangyuanji")
SOLDIER = "soldier"


def canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False)


def derive_seed(seed: int, domain: str) -> int:
    return int.from_bytes(hashlib.sha256(canonical([seed, domain]).encode()).digest()[:16], "big")


def integer(value: object, label: str, minimum: int | None = None) -> int:
    if type(value) is not int or (minimum is not None and value < minimum):
        raise ValueError(f"{label}必须是整数" + (f"且不小于{minimum}" if minimum is not None else ""))
    return value


@dataclass(frozen=True)
class GameConfig:
    mode: str = "2v2"
    seed: int = 0
    ai_seed: int = 0
    control: str = "HUMAN_VS_AI"
    human_seats: tuple[int, ...] = (1,)
    enabled_generals: tuple[str, ...] = PRODUCTION_GENERALS
    selection: str = "fixed"
    fixed_generals: tuple[str, ...] = ()
    candidate_count: int = 3
    # 按固定物理座位排列；空值为规则允许的随机身份／交互叫价。
    identities: tuple[str, ...] = ()
    landlord_seat: int | None = None
    mulligan: bool = True
    ai_version: str = AI_VERSION
    ai_parameters: tuple[tuple[str, float], ...] = ()
    max_steps: int = 20000
    omniscient_debug: bool = False

    def __post_init__(self) -> None:
        if self.mode not in MODE_SEATS:
            raise ValueError(f"不支持模式{self.mode!r}；可用：{', '.join(MODE_SEATS)}")
        n = MODE_SEATS[self.mode]
        for key in ("seed", "ai_seed"):
            integer(getattr(self, key), key)
        for key in ("human_seats", "enabled_generals", "fixed_generals", "identities"):
            value = getattr(self, key)
            if not isinstance(value, (tuple, list)):
                raise ValueError(f"{key}必须是列表")
            object.__setattr__(self, key, tuple(value))
        if self.control not in CONTROL_MODES:
            raise ValueError("control必须为ALL_HUMAN、HUMAN_VS_AI或AI_VS_AI")
        if any(type(x) is not int or not 1 <= x <= n for x in self.human_seats):
            raise ValueError(f"人工物理座位必须在1..{n}内")
        if len(set(self.human_seats)) != len(self.human_seats):
            raise ValueError("人工座位不能重复")
        if self.control == "HUMAN_VS_AI" and not 0 < len(self.human_seats) < n:
            raise ValueError("混合模式至少需要一名人工与一名AI")
        if self.selection not in ("fixed", "candidates"):
            raise ValueError("selection必须为fixed或candidates")
        available = {*PRODUCTION_GENERALS, SOLDIER}
        if not self.enabled_generals or any(type(x) is not str or x not in available for x in self.enabled_generals):
            raise ValueError("启用池只允许完整生产武将shamoke、zhugezhan、wangyuanji及显式soldier；其他武将尚无完整生产技能")
        if len(set(self.enabled_generals)) != len(self.enabled_generals):
            raise ValueError("启用武将池不能重复")
        integer(self.candidate_count, "候选数", 1)
        if self.selection == "candidates":
            if self.candidate_count > len(self.enabled_generals):
                raise ValueError("候选数不能超过自定义启用池大小")
            if self.fixed_generals:
                raise ValueError("候选选将不能同时提供固定阵容")
        elif self.fixed_generals and (len(self.fixed_generals) != n or
                any(x not in self.enabled_generals for x in self.fixed_generals)):
            raise ValueError("固定阵容须逐物理座位覆盖全部角色，且武将在启用池内")
        if self.identities:
            expected = ["lord"] + ["loyalist"] * (2 if n == 8 else 1) + ["rebel"] * (4 if n == 8 else 2) + ["spy"]
            if not self.mode.startswith("identity") or sorted(self.identities) != sorted(expected):
                raise ValueError("固定身份须符合所选模式的主忠反内人数，按物理座位给出")
        if self.landlord_seat is not None:
            integer(self.landlord_seat, "固定地主座位", 1)
            if self.mode != "doudizhu" or self.landlord_seat > 3:
                raise ValueError("固定地主仅用于斗地主物理座位1..3")
        for key in ("mulligan", "omniscient_debug"):
            if type(getattr(self, key)) is not bool:
                raise ValueError(f"{key}必须是布尔值")
        if self.omniscient_debug and self.control != "ALL_HUMAN":
            raise ValueError("全知调试只允许ALL_HUMAN；AI必须使用正常玩家视图")
        if self.ai_version != AI_VERSION:
            raise ValueError(f"未知AI版本{self.ai_version!r}")
        params = self.ai_parameters
        if isinstance(params, Mapping):
            params = tuple(params.items())
        if not isinstance(params, (tuple, list)):
            raise ValueError("AI参数必须是映射或键值对列表")
        normalized = []
        for pair in params:
            if not isinstance(pair, (list, tuple)) or len(pair) != 2:
                raise ValueError("AI参数必须是键值对")
            key, value = pair
            if key not in ("aggression", "preservation", "tie_randomness"):
                raise ValueError(f"未知AI参数{key!r}")
            if type(value) not in (int, float) or not isfinite(value) or not 0 <= value <= 10:
                raise ValueError("AI参数必须是0..10内有限数值")
            normalized.append((key, float(value)))
        if len(dict(normalized)) != len(normalized):
            raise ValueError("AI参数不能重复")
        object.__setattr__(self, "ai_parameters", tuple(sorted(normalized)))
        integer(self.max_steps, "工程动作上限", 1)

    @property
    def player_ids(self) -> tuple[str, ...]:
        return tuple(f"p{i}" for i in range(1, MODE_SEATS[self.mode] + 1))

    @property
    def human_player_ids(self) -> tuple[str, ...]:
        if self.control == "ALL_HUMAN":
            return self.player_ids
        return () if self.control == "AI_VS_AI" else tuple(f"p{i}" for i in self.human_seats)

    @property
    def mulligan_limit(self) -> int:
        return 8 if self.mulligan and self.mode in ("doudizhu", "identity8", "identity8_heir") else 0

    def to_dict(self) -> dict:
        value = asdict(self)
        value["ai_parameters"] = dict(self.ai_parameters)
        return json.loads(canonical(value))

    @classmethod
    def from_dict(cls, value: object) -> "GameConfig":
        if type(value) is not dict:
            raise ValueError("对局配置必须是JSON对象")
        unknown = set(value) - set(cls.__dataclass_fields__)
        if unknown:
            raise ValueError(f"未知对局配置字段：{sorted(unknown)}")
        return cls(**value)


def general_catalog() -> list[dict]:
    registry = create_authoritative_general_batch_v1_registry()
    return [registry.get_general(key).to_dict() for key in PRODUCTION_GENERALS] + [
        {"general_key": SOLDIER, "name": "无技能士兵（显式测试配置）", "starting_hp": 4, "max_hp": 4, "skill_ids": []}]
