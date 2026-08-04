# -*- coding: utf-8 -*-
"""正式160张牌堆中六种基本牌的生产适配器与正式卡牌注册表。

这是里程碑B"正式160张牌无技能单挑"的第一批生产卡牌批次：普通【杀】、
火【杀】、雷【杀】、【闪】、【桃】、【酒】。六种牌的全部规则都以正式
Knowledge（《三国杀卡牌效果》《三国杀卡牌使用方式》《三国杀牌堆数据》）
为唯一来源，并从正式牌堆CSV的真实行读取实体牌元数据，不建立与CSV脱节
的假牌表。

本模块不包含任何概率近似、固定收益替代或fallback结算。未实现卡牌在
:class:`FormalCardRegistry` 中明确标记，任何结算入口遇到它们都会失败
关闭。本批次不是完整整局引擎：它只提供六种基本牌的生产规则，正式整局
仍需在全部38种卡牌接完后另行验收，本批次不得被解释为里程碑B完成。

本文件同时包含最小普通锦囊垂直切片：【无中生有】与【无懈可击】的
生产适配器，以及两者所需的普通锦囊无效响应通用基础设施。
"""

from __future__ import annotations

import csv
import itertools
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Mapping, Sequence

from ..deck_data import DeckRecord, load_deck_csv
from .actions import (
    ActionContext,
    ActionType,
    InvalidActionError,
    LegalAction,
    RuleAdapter,
    UnsupportedRuleError,
)
from .engine import DEFAULT_DECK_PATH, AuthoritativeCoreSession
from .model import EQUIPMENT_SLOTS, GameState, ZoneRef

if TYPE_CHECKING:
    from .production_batch import ProductionBasicCardBatch


PRODUCTION_BASIC_CARD_KEYS: tuple[str, ...] = (
    "sgs_basic_sha",
    "sgs_basic_huosha",
    "sgs_basic_leisha",
    "sgs_basic_shan",
    "sgs_basic_tao",
    "sgs_basic_jiu",
)

CARD_NAMES_BY_KEY: Mapping[str, str] = {
    "sgs_basic_sha": "杀",
    "sgs_basic_huosha": "火杀",
    "sgs_basic_leisha": "雷杀",
    "sgs_basic_shan": "闪",
    "sgs_basic_tao": "桃",
    "sgs_basic_jiu": "酒",
    "sgs_trick_juedou": "决斗",
    "sgs_trick_huogong": "火攻",
    "sgs_trick_nanmanruqin": "南蛮入侵",
    "sgs_trick_wanjianqifa": "万箭齐发",
    "sgs_trick_taoyuanjieyi": "桃园结义",
    "sgs_trick_tiesuolianhuan": "铁索连环",
    "sgs_trick_wugufengdeng": "五谷丰登",
    "sgs_trick_jiedaosharen": "借刀杀人",
    "sgs_weapon_zhugeliannu": "诸葛连弩",
    "sgs_weapon_qinggangjian": "青釭剑",
    "sgs_weapon_hanbingjian": "寒冰剑",
    "sgs_weapon_cixiongshuanggujian": "雌雄双股剑",
    "sgs_weapon_gudingdao": "古锭刀",
    "sgs_weapon_qinglongyanyuedao": "青龙偃月刀",
    "sgs_weapon_guanshifu": "贯石斧",
    "sgs_weapon_zhangbashemao": "丈八蛇矛",
    "sgs_weapon_fangtianhuaji": "方天画戟",
    "sgs_weapon_zhuqueyushan": "朱雀羽扇",
    "sgs_weapon_qilingong": "麒麟弓",
}

SLASH_CARD_KEYS: tuple[str, ...] = (
    "sgs_basic_sha",
    "sgs_basic_huosha",
    "sgs_basic_leisha",
)

DEFAULT_ATTACK_RANGE = 1

PRODUCTION_TRICK_KEYS: tuple[str, ...] = (
    "sgs_trick_wuzhongshengyou",
    "sgs_trick_wuxiekeji",
    "sgs_trick_guohechaiqiao",
    "sgs_trick_shunshouqianyang",
    "sgs_trick_juedou",
    "sgs_trick_huogong",
    "sgs_trick_nanmanruqin",
    "sgs_trick_wanjianqifa",
    "sgs_trick_taoyuanjieyi",
    "sgs_trick_tiesuolianhuan",
    "sgs_trick_wugufengdeng",
    "sgs_trick_jiedaosharen",
)

GROUP_TRICK_KEYS: tuple[str, ...] = (
    "sgs_trick_nanmanruqin",
    "sgs_trick_wanjianqifa",
    "sgs_trick_taoyuanjieyi",
)

PRODUCTION_WEAPON_KEYS: tuple[str, ...] = (
    "sgs_weapon_zhugeliannu",
    "sgs_weapon_qinggangjian",
    "sgs_weapon_hanbingjian",
    "sgs_weapon_cixiongshuanggujian",
    "sgs_weapon_gudingdao",
    "sgs_weapon_qinglongyanyuedao",
    "sgs_weapon_guanshifu",
    "sgs_weapon_zhangbashemao",
    "sgs_weapon_fangtianhuaji",
    "sgs_weapon_zhuqueyushan",
    "sgs_weapon_qilingong",
)

DEFAULT_STRUCTURED_CARD_CSV_PATH = Path("knowledge") / "三国杀卡牌结构化数据.csv"

_WEAPON_ATTACK_RANGES_CACHE: Mapping[str, int] | None = None


def weapon_attack_ranges(
    path: str | Path = DEFAULT_STRUCTURED_CARD_CSV_PATH,
) -> Mapping[str, int]:
    """读取正式结构化CSV中的11种武器攻击范围并缓存。

    攻击范围以 `knowledge/三国杀卡牌结构化数据.csv` 的 ``attack_range``
    列为唯一来源；缺失、非正整数或键缺失时立即失败关闭，不猜测数值。
    """

    global _WEAPON_ATTACK_RANGES_CACHE
    if _WEAPON_ATTACK_RANGES_CACHE is not None:
        return _WEAPON_ATTACK_RANGES_CACHE
    try:
        with open(path, encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
    except (OSError, UnicodeError) as exc:
        raise UnsupportedRuleError(
            f"无法读取正式结构化卡牌CSV：{path}"
        ) from exc
    result: dict[str, int] = {}
    for row in rows:
        card_id = str(row.get("card_id") or "").strip()
        if card_id not in PRODUCTION_WEAPON_KEYS:
            continue
        raw = str(row.get("attack_range") or "").strip()
        try:
            value = int(raw)
        except ValueError as exc:
            raise UnsupportedRuleError(
                f"正式结构化CSV中武器{card_id}的攻击范围缺失或非法：{raw!r}"
            ) from exc
        if value < 1:
            raise UnsupportedRuleError(
                f"正式结构化CSV中武器{card_id}的攻击范围必须为正整数"
            )
        result[card_id] = value
    missing = set(PRODUCTION_WEAPON_KEYS).difference(result)
    if missing:
        raise UnsupportedRuleError(
            "正式结构化CSV缺少武器攻击范围：" + "、".join(sorted(missing))
        )
    _WEAPON_ATTACK_RANGES_CACHE = MappingProxyType(result)
    return _WEAPON_ATTACK_RANGES_CACHE


def attack_range_of(state: GameState, player_id: str) -> int:
    """返回角色的当前攻击范围；每次从当前装备区动态计算。

    无武器时返回默认攻击范围1；装备武器时读取正式结构化CSV登记的攻击
    范围；武器槽状态非法或攻击范围未登记时失败关闭，绝不返回近似值。
    """

    weapon_ids = state.card_ids_in(ZoneRef.equipment(player_id, "weapon"))
    if not weapon_ids:
        return DEFAULT_ATTACK_RANGE
    if len(weapon_ids) != 1:
        raise UnsupportedRuleError(
            f"角色{player_id}的武器槽必须恰好包含一张武器牌；当前为{len(weapon_ids)}张"
        )
    weapon = state.cards_by_id[weapon_ids[0]]
    ranges = weapon_attack_ranges()
    try:
        return ranges[weapon.card_key]
    except KeyError as exc:
        raise UnsupportedRuleError(
            f"武器{weapon.card_key}未在正式结构化CSV登记攻击范围；失败关闭"
        ) from exc


def actual_distance(state: GameState, source_id: str, target_id: str) -> int:
    """按当前座次的环形座次计算实际距离。

    距离 = 顺时针与逆时针座位步数中的较小值。本批次未实现坐骑，距离
    修正不适用；若将来接入坐骑，必须在本函数同步补充。
    """

    players = state.players_by_id
    if source_id not in players or target_id not in players:
        raise UnsupportedRuleError(f"计算距离时找不到角色{source_id!r}或{target_id!r}")
    if source_id == target_id:
        return 0
    seats = sorted(player.seat for player in state.players)
    source_seat = players[source_id].seat
    target_seat = players[target_id].seat
    span = abs(source_seat - target_seat)
    ring_size = len(seats)
    return min(span, ring_size - span)


def is_valid_slash_target(state: GameState, attacker_id: str, target_id: str) -> bool:
    """真实执行【杀】系列的目标与距离合法性检查。"""

    if attacker_id == target_id:
        return False
    return actual_distance(state, attacker_id, target_id) <= attack_range_of(
        state, attacker_id
    )


_WEAPON_GATE_DECISIONS: frozenset[str] = frozenset(
    {
        "use_slash",
        "forced_slash",
        "play_slash",
        "slash_damage",
        "slash_dodged",
    }
)


def check_weapon_skill_gate(
    state: GameState,
    *,
    actor_id: str,
    decision: str,
    target_id: str | None = None,
    slash_card_key: str | None = None,
    slash_used_count: int = 0,
) -> None:
    """集中式武器技能影响门禁（CP-04K）。

    11种武器只实现牌本体，专属技能全部保持 partial。本函数在首次需要
    作出相关判断前检查：若能以当前完整公开状态证明专属技能不可能影响
    本次合法性、可选动作或结算结果则直接返回；否则抛出
    ``UnsupportedRuleError`` 失败关闭。失败发生在任何状态、事件、RNG、
    pending或处理区变化之前。禁止把未知条件当作 false，禁止把武器技能
    近似为无效果。
    """

    if decision not in _WEAPON_GATE_DECISIONS:
        raise UnsupportedRuleError(
            f"武器技能门禁不支持决策类型{decision!r}；失败关闭"
        )
    weapon_ids = state.card_ids_in(ZoneRef.equipment(actor_id, "weapon"))
    if not weapon_ids:
        return
    if len(weapon_ids) != 1:
        raise UnsupportedRuleError(
            f"角色{actor_id}的武器槽必须恰好包含一张武器牌；当前为{len(weapon_ids)}张"
        )
    weapon_key = state.cards_by_id[weapon_ids[0]].card_key
    if weapon_key not in PRODUCTION_WEAPON_KEYS:
        raise UnsupportedRuleError(
            f"武器{weapon_key}未在武器技能影响矩阵中登记；失败关闭"
        )

    if weapon_key == "sgs_weapon_zhugeliannu":
        # 技能：你使用【杀】无次数限制。主动出杀次数已用尽时，
        # 合法动作集合依赖该技能，必须失败关闭；借刀强制杀绕过次数
        # 限制来自借刀规则本身，不依赖连弩，因此不失败关闭。
        if decision == "use_slash" and slash_used_count >= 1:
            raise UnsupportedRuleError(
                "诸葛连弩的无限出杀技能未实现；当前主动出杀合法性依赖该技能，失败关闭"
            )
        return

    if weapon_key == "sgs_weapon_qinggangjian":
        # 技能：使用【杀】指定目标时无视其防具。防具槽为空可证明
        # 技能不影响本次结算；防具槽被占用时无法证明，失败关闭。
        if decision in ("use_slash", "forced_slash") and target_id is not None:
            if state.card_ids_in(ZoneRef.equipment(target_id, "armor")):
                raise UnsupportedRuleError(
                    "青釭剑无视防具技能未实现；目标装备防具时失败关闭"
                )
        return

    if weapon_key == "sgs_weapon_hanbingjian":
        # 技能：使用【杀】将要造成伤害时可以防止伤害并弃置目标2张牌。
        # 伤害结算可能被该技能改变，无法从当前状态证明不发动，失败关闭。
        if decision == "slash_damage":
            raise UnsupportedRuleError(
                "寒冰剑防止伤害并弃置目标牌技能未实现；杀伤害结算前失败关闭"
            )
        return

    if weapon_key == "sgs_weapon_cixiongshuanggujian":
        # 技能：使用【杀】指定异性角色为目标时可令其选择。PlayerState
        # 没有性别字段，缺少性别数据不能证明目标非异性，因此对另一
        # 角色使用【杀】时一律失败关闭，不得当作白板武器。
        if decision in ("use_slash", "forced_slash") and target_id is not None:
            raise UnsupportedRuleError(
                "雌雄双股剑技能需要性别判定；PlayerState无性别字段，无法证明目标非异性，失败关闭"
            )
        return

    if weapon_key == "sgs_weapon_gudingdao":
        # 技能：对没有手牌的角色使用【杀】时伤害+1。目标在手牌为0的
        # 状态被指定时技能必然生效，无法按无属性杀结算，失败关闭。
        if decision in ("use_slash", "forced_slash") and target_id is not None:
            if not state.card_ids_in(ZoneRef.hand(target_id)):
                raise UnsupportedRuleError(
                    "古锭刀对无手牌目标伤害+1技能未实现；失败关闭"
                )
        return

    if weapon_key == "sgs_weapon_qinglongyanyuedao":
        # 技能：使用的【杀】被【闪】响应后可继续对该目标使用【杀】。
        # 被闪后若手中仍有【杀】，可选动作集合可能扩大，失败关闭。
        if decision == "slash_dodged":
            if any(
                state.cards_by_id[instance_id].card_key in SLASH_CARD_KEYS
                for instance_id in state.card_ids_in(ZoneRef.hand(actor_id))
            ):
                raise UnsupportedRuleError(
                    "青龙偃月刀被闪后继续使用杀技能未实现；失败关闭"
                )
        return

    if weapon_key == "sgs_weapon_guanshifu":
        # 技能：被【闪】响应后可弃置手牌区与装备区合计2张牌强制造成伤害。
        # 可支付牌不足2张时可证明技能不可发动；否则失败关闭。
        if decision == "slash_dodged":
            hand_count = len(state.card_ids_in(ZoneRef.hand(actor_id)))
            equip_count = sum(
                len(state.card_ids_in(ZoneRef.equipment(actor_id, slot)))
                for slot in EQUIPMENT_SLOTS
            )
            if hand_count + equip_count >= 2:
                raise UnsupportedRuleError(
                    "贯石斧弃两张牌强制命中技能未实现；失败关闭"
                )
        return

    if weapon_key == "sgs_weapon_zhangbashemao":
        # 技能：可将2张手牌当作普通【杀】使用或打出。手牌数达到2张时
        # 合法杀集合可能扩大，无法证明不影响，失败关闭；不足2张时
        # 不存在转化材料，可证明不影响，继续按实体杀流程。
        if decision in ("use_slash", "forced_slash", "play_slash"):
            if len(state.card_ids_in(ZoneRef.hand(actor_id))) >= 2:
                raise UnsupportedRuleError(
                    "丈八蛇矛两张手牌转化杀技能未实现；合法杀集合可能扩大，失败关闭"
                )
        return

    if weapon_key == "sgs_weapon_fangtianhuaji":
        # 技能：使用作为最后一张手牌的【杀】时可指定至多3个目标。
        # 当前生产切片为双人环，额外目标不存在，目标集合可证明不变；
        # 三人以上无法证明，失败关闭。
        if len(state.players) != 2:
            raise UnsupportedRuleError(
                "方天画戟多目标技能未实现；当前不是双人切片，无法证明目标集合不变，失败关闭"
            )
        return

    if weapon_key == "sgs_weapon_zhuqueyushan":
        # 技能：使用普通【杀】指定目标时可将其转为【火杀】。实体普通杀
        # 的属性选择可能改变伤害与传导，失败关闭；实体火杀／雷杀不受
        # 本技能影响，可继续。
        if decision in ("use_slash", "forced_slash"):
            if slash_card_key == "sgs_basic_sha":
                raise UnsupportedRuleError(
                    "朱雀羽扇普通杀转火杀技能未实现；实体普通杀失败关闭"
                )
        return

    if weapon_key == "sgs_weapon_qilingong":
        # 技能：使用【杀】对目标造成伤害时可以弃置目标装备区一张坐骑牌。
        # 目标坐骑槽为空时可证明技能无法弃置；否则失败关闭。
        if decision == "slash_damage" and target_id is not None:
            mounts = state.card_ids_in(
                ZoneRef.equipment(target_id, "attack_horse")
            ) + state.card_ids_in(
                ZoneRef.equipment(target_id, "defense_horse")
            )
            if mounts:
                raise UnsupportedRuleError(
                    "麒麟弓弃置坐骑技能未实现；目标有坐骑时失败关闭"
                )
        return

    raise UnsupportedRuleError(
        f"武器{weapon_key}的技能影响矩阵未覆盖决策{decision!r}；失败关闭"
    )


def normalize_target_order(
    state: GameState,
    user_id: str,
    target_ids: Iterable[str],
) -> tuple[str, ...]:
    """以使用者为锚点按行动顺序规范化目标结算顺序。

    与群体锦囊目标序列同一口径：从使用者开始沿当前座次数字递增方向
    循环（基础术语第4.1节）。玩家提交的目标集合不因提交顺序改变结算
    顺序，服务器始终按本函数生成固定序列。
    """

    user_seat = state.players_by_id[user_id].seat
    ring_size = max(1, len(state.players))
    return tuple(
        sorted(
            target_ids,
            key=lambda player_id: (
                state.players_by_id[player_id].seat - user_seat
            )
            % ring_size,
        )
    )


def target_zone_refs(player_id: str) -> tuple[ZoneRef, ...]:
    """“区域内的牌”对应的三个玩家区域：手牌区、装备区、判定区。

    这是【过河拆桥】与【顺手牵羊】共用的目标区域基础设施；装备区按
    正式装备栏顺序展开，不把五个装备栏静默合并成一个区域。
    """

    zones: list[ZoneRef] = [ZoneRef.hand(player_id)]
    zones.extend(
        ZoneRef.equipment(player_id, slot) for slot in sorted(EQUIPMENT_SLOTS)
    )
    zones.append(ZoneRef.judgment(player_id))
    return tuple(zones)


def has_target_zone_cards(state: GameState, player_id: str) -> bool:
    """目标角色的手牌区、装备区与判定区合计至少存在一张实体牌。"""

    return any(state.card_ids_in(zone) for zone in target_zone_refs(player_id))


def is_valid_shunshou_target(
    state: GameState, source_id: str, target_id: str
) -> bool:
    """【顺手牵羊】的真实目标合法性：其他角色且实际距离为 1。

    距离条件调用正式 ``actual_distance`` 接口，不使用座位编号差或
    攻击范围代替。坐骑距离修正尚未实现：当参与该距离的坐骑栏被占用时
    失败关闭，绝不返回近似距离。
    """

    if source_id == target_id:
        return False
    if state.card_ids_in(ZoneRef.equipment(source_id, "attack_horse")) or (
        state.card_ids_in(ZoneRef.equipment(target_id, "defense_horse"))
    ):
        raise UnsupportedRuleError(
            "坐骑距离修正尚未实现，不能判定【顺手牵羊】的实际距离条件；"
            "本批次失败关闭"
        )
    return actual_distance(state, source_id, target_id) == 1


class BasicCardAdapter(RuleAdapter):
    """六种基本牌生产适配器的公共基类。

    适配器自身是无状态规则对象；所有可变运行状态都存放在生产批处理
    会话的运行时中，由会话统一提交。适配器被正式注册表按 ``card_key``
    映射，并被会话注册表绑定到 ``(模式, "card:<key>")`` 以便动作防伪
    指纹覆盖每一张生产卡牌的版本。
    """

    card_key: str
    card_name: str

    def __init__(self, session: "ProductionBasicCardBatch | None" = None) -> None:
        self._session = session

    @property
    def adapter_version(self) -> str:
        return f"production-basic-cards.{self.card_key}.v1"

    def audit_state(self) -> Mapping[str, object]:
        return {}

    @property
    def implemented(self) -> bool:
        return True

    @property
    def tested(self) -> bool:
        return True

    @property
    def production_adapter(self) -> bool:
        return True

    def rule_spec(self) -> dict[str, object]:
        raise NotImplementedError

    def _require_session(self) -> "ProductionBasicCardBatch":
        if self._session is None:
            raise UnsupportedRuleError(
                f"卡牌适配器{self.card_key}尚未绑定生产批处理会话，不能单独结算"
            )
        return self._session


class SlashAdapter(BasicCardAdapter):
    """普通【杀】／火【杀】／雷【杀】的生产适配器。

    三种【杀】的区别落实到伤害属性事件：``damage_type`` 分别记录为
    "无属性"、"火属性"、"雷属性"，而不是只体现在牌名上。
    """

    def __init__(
        self,
        card_key: str,
        damage_nature: str,
        session: "ProductionBasicCardBatch | None" = None,
    ) -> None:
        super().__init__(session)
        if card_key not in SLASH_CARD_KEYS:
            raise ValueError(f"{card_key}不是本批次的【杀】卡牌键")
        self.card_key = card_key
        self.card_name = CARD_NAMES_BY_KEY[card_key]
        self._damage_nature = damage_nature

    @property
    def damage_nature(self) -> str:
        return self._damage_nature

    def rule_spec(self) -> dict[str, object]:
        return {
            "card_key": self.card_key,
            "card_name": self.card_name,
            "use_timing": "own_play_phase",
            "use_limit": "one_slash_per_play_phase",
            "target_count": 1,
            "target_filter": "one_character_in_attack_range_excluding_self",
            "distance_rule": "actual_distance(actor,target)<=attack_range(actor)",
            "response_requirements": [
                {
                    "response_card_key": "sgs_basic_shan",
                    "action": "use",
                    "event_type": "card_used",
                }
            ],
            "nullification_eligible": False,
            "movement_lifecycle": "hand->processing->discard",
            "effect_resolution": "dodge_cancels_effect;otherwise_damage_event",
            "damage_nature": self._damage_nature,
            "completion_event": (
                "card_effect_cancelled|damage(+dying_rescue) then card_moved_to_discard"
            ),
            "adapter_version": self.adapter_version,
            "implemented": self.implemented,
            "tested": self.tested,
            "production_adapter": self.production_adapter,
        }

    def enumerate_legal_actions(
        self, state: GameState, context: ActionContext
    ) -> tuple[LegalAction, ...]:
        session = self._require_session()
        if session.phase.value != "play":
            return ()
        if session.runtime.slash_used_counts.get(context.actor_id, 0) > 0:
            # 达到通常上限：仍须先经过武器技能门禁，避免把连弩等技能
            # 可能扩展的合法动作静默当作不存在（不得错误允许或错误禁止）。
            check_weapon_skill_gate(
                state,
                actor_id=context.actor_id,
                decision="use_slash",
                target_id=session.opponent_of(context.actor_id),
                slash_used_count=session.runtime.slash_used_counts.get(
                    context.actor_id, 0
                ),
            )
            return ()
        actions: list[LegalAction] = []
        for instance_id in state.card_ids_in(ZoneRef.hand(context.actor_id)):
            card = state.cards_by_id[instance_id]
            if card.card_key != self.card_key:
                continue
            target = session.opponent_of(context.actor_id)
            if not is_valid_slash_target(state, context.actor_id, target):
                continue
            check_weapon_skill_gate(
                state,
                actor_id=context.actor_id,
                decision="use_slash",
                target_id=target,
                slash_card_key=self.card_key,
                slash_used_count=session.runtime.slash_used_counts.get(
                    context.actor_id, 0
                ),
            )
            actions.append(
                LegalAction(
                    action_type=ActionType.USE_CARD,
                    actor_id=context.actor_id,
                    card_instance_id=instance_id,
                    target_ids=(target,),
                    payload={
                        "operation": "use_slash",
                        "card_key": self.card_key,
                        "card_name": self.card_name,
                    },
                )
            )
        return tuple(actions)

    def apply_action(
        self, state: GameState, context: ActionContext, action: LegalAction
    ) -> GameState:
        session = self._require_session()
        if session.phase.value == "play":
            return session.apply_slash_use(state, context, action, self)
        if (
            session.phase.value == "slash_response"
            and action.action_type is ActionType.PASS
        ):
            return session.apply_slash_damage(state, context, action, self)
        raise InvalidActionError(
            f"{self.card_name}生产适配器不能处理当前阶段的动作"
        )


class DodgeAdapter(BasicCardAdapter):
    """【闪】的生产适配器。

    本批次只实现响应三种【杀】的正式生产路径：动作类型是"使用一张
    【闪】"，生成 ``card_used`` 且不生成普通 ``card_played``。响应
    【万箭齐发】的"打出【闪】"不属于本批次，遇到该响应上下文时失败
    关闭，不提前伪造结算。
    """

    def __init__(self, session: "ProductionBasicCardBatch | None" = None) -> None:
        super().__init__(session)
        self.card_key = "sgs_basic_shan"
        self.card_name = "闪"

    def rule_spec(self) -> dict[str, object]:
        return {
            "card_key": self.card_key,
            "card_name": self.card_name,
            "use_timing": "slash_response_window",
            "use_limit": "no_independent_quota;requires_real_entity_and_legal_window",
            "target_count": 0,
            "target_filter": "self",
            "distance_rule": "not_applicable",
            "response_requirements": [
                {
                    "response_to": "杀|火杀|雷杀",
                    "action": "use",
                    "event_type": "card_used",
                }
            ],
            "nullification_eligible": False,
            "movement_lifecycle": "hand->processing->discard",
            "effect_resolution": "respond_to_slash:card_used_and_cancel_slash",
            "damage_nature": "不适用",
            "completion_event": (
                "card_used(no card_played) + card_effect_cancelled(source slash)"
            ),
            "adapter_version": self.adapter_version,
            "implemented": self.implemented,
            "tested": self.tested,
            "production_adapter": self.production_adapter,
        }

    def enumerate_legal_actions(
        self, state: GameState, context: ActionContext
    ) -> tuple[LegalAction, ...]:
        session = self._require_session()
        if session.phase.value != "slash_response":
            return ()
        actions: list[LegalAction] = []
        for instance_id in state.card_ids_in(ZoneRef.hand(context.actor_id)):
            card = state.cards_by_id[instance_id]
            if card.card_key != self.card_key:
                continue
            actions.append(
                LegalAction(
                    action_type=ActionType.USE_CARD,
                    actor_id=context.actor_id,
                    card_instance_id=instance_id,
                    payload={
                        "operation": "play_dodge",
                        "card_key": self.card_key,
                        "card_name": self.card_name,
                    },
                )
            )
        return tuple(actions)

    def apply_action(
        self, state: GameState, context: ActionContext, action: LegalAction
    ) -> GameState:
        session = self._require_session()
        if session.phase.value == "slash_response":
            return session.apply_dodge(state, context, action, self)
        raise InvalidActionError("【闪】生产适配器只能响应【杀】响应窗口")


class PeachAdapter(BasicCardAdapter):
    """【桃】的生产适配器。

    三种用途分别结算：出牌阶段受伤自用、濒死自救、救援其他濒死角色。
    三种用途均无基础次数限制且不共享额度；回复不能超过体力上限。
    """

    def __init__(self, session: "ProductionBasicCardBatch | None" = None) -> None:
        super().__init__(session)
        self.card_key = "sgs_basic_tao"
        self.card_name = "桃"

    def rule_spec(self) -> dict[str, object]:
        return {
            "card_key": self.card_key,
            "card_name": self.card_name,
            "use_timing": "own_play_phase|legal_dying_rescue_window",
            "use_limit": "no_basic_quota;context_checked_each_time",
            "target_count": 1,
            "target_filter": "wounded_self(play)|dying_character(rescue)",
            "distance_rule": "not_applicable",
            "response_requirements": [],
            "nullification_eligible": False,
            "movement_lifecycle": "hand->processing->discard",
            "effect_resolution": "heal_1_capped_at_max_hp;rescue_stops_at_hp>=1",
            "damage_nature": "不适用",
            "completion_event": "card_used + heal; card_moved_to_discard",
            "adapter_version": self.adapter_version,
            "implemented": self.implemented,
            "tested": self.tested,
            "production_adapter": self.production_adapter,
        }

    def enumerate_legal_actions(
        self, state: GameState, context: ActionContext
    ) -> tuple[LegalAction, ...]:
        session = self._require_session()
        actions: list[LegalAction] = []
        if session.phase.value == "play":
            player = state.players_by_id[context.actor_id]
            if player.hp >= player.max_hp:
                return ()
            for instance_id in state.card_ids_in(ZoneRef.hand(context.actor_id)):
                card = state.cards_by_id[instance_id]
                if card.card_key != self.card_key:
                    continue
                actions.append(
                    LegalAction(
                        action_type=ActionType.USE_CARD,
                        actor_id=context.actor_id,
                        card_instance_id=instance_id,
                        target_ids=(context.actor_id,),
                        payload={
                            "operation": "heal_self",
                            "card_key": self.card_key,
                            "card_name": self.card_name,
                        },
                    )
                )
            return tuple(actions)
        if session.phase.value == "dying_rescue":
            dying_id = session.runtime.pending_dying_id
            assert dying_id is not None
            for instance_id in state.card_ids_in(ZoneRef.hand(context.actor_id)):
                card = state.cards_by_id[instance_id]
                if card.card_key != self.card_key:
                    continue
                actions.append(
                    LegalAction(
                        action_type=ActionType.USE_CARD,
                        actor_id=context.actor_id,
                        card_instance_id=instance_id,
                        target_ids=(dying_id,),
                        payload={
                            "operation": "rescue_with_peach",
                            "card_key": self.card_key,
                            "card_name": self.card_name,
                        },
                    )
                )
            return tuple(actions)
        return ()

    def apply_action(
        self, state: GameState, context: ActionContext, action: LegalAction
    ) -> GameState:
        session = self._require_session()
        if session.phase.value == "play":
            return session.apply_peach_self_heal(state, context, action, self)
        if session.phase.value == "dying_rescue":
            return session.apply_peach_rescue(state, context, action, self)
        raise InvalidActionError("【桃】生产适配器不能处理当前阶段的动作")


class WineAdapter(BasicCardAdapter):
    """【酒】的生产适配器。

    两种用途分开记录：出牌阶段强化下一张【杀】（每个独立出牌阶段限
    一次）与濒死自救回复1点体力（无基础次数限制）。两种用途不共享
    额度；濒死自救不建立加伤状态，出牌阶段强化不直接回复体力。
    """

    def __init__(self, session: "ProductionBasicCardBatch | None" = None) -> None:
        super().__init__(session)
        self.card_key = "sgs_basic_jiu"
        self.card_name = "酒"

    def rule_spec(self) -> dict[str, object]:
        return {
            "card_key": self.card_key,
            "card_name": self.card_name,
            "use_timing": "own_play_phase|dying_self_rescue",
            "use_limit": (
                "slash_buff_once_per_own_play_phase;dying_self_rescue_unlimited"
            ),
            "target_count": 1,
            "target_filter": "self",
            "distance_rule": "not_applicable",
            "response_requirements": [],
            "nullification_eligible": False,
            "movement_lifecycle": "hand->processing->discard",
            "effect_resolution": (
                "buff_next_qualifying_slash_damage+1|dying_self_heal_1"
            ),
            "damage_nature": "由受其加成的杀决定；濒死自救不造成伤害",
            "completion_event": (
                "card_used(purpose split);buff_consumed_by_next_slash_or_cleared_at_turn_end"
            ),
            "adapter_version": self.adapter_version,
            "implemented": self.implemented,
            "tested": self.tested,
            "production_adapter": self.production_adapter,
        }

    def enumerate_legal_actions(
        self, state: GameState, context: ActionContext
    ) -> tuple[LegalAction, ...]:
        session = self._require_session()
        actions: list[LegalAction] = []
        if session.phase.value == "play":
            if session.runtime.wine_buff_used_this_play_phase:
                return ()
            for instance_id in state.card_ids_in(ZoneRef.hand(context.actor_id)):
                card = state.cards_by_id[instance_id]
                if card.card_key != self.card_key:
                    continue
                actions.append(
                    LegalAction(
                        action_type=ActionType.USE_CARD,
                        actor_id=context.actor_id,
                        card_instance_id=instance_id,
                        target_ids=(context.actor_id,),
                        payload={
                            "operation": "use_wine_buff",
                            "card_key": self.card_key,
                            "card_name": self.card_name,
                        },
                    )
                )
            return tuple(actions)
        if session.phase.value == "dying_rescue":
            dying_id = session.runtime.pending_dying_id
            assert dying_id is not None
            if context.actor_id != dying_id:
                return ()
            for instance_id in state.card_ids_in(ZoneRef.hand(context.actor_id)):
                card = state.cards_by_id[instance_id]
                if card.card_key != self.card_key:
                    continue
                actions.append(
                    LegalAction(
                        action_type=ActionType.USE_CARD,
                        actor_id=context.actor_id,
                        card_instance_id=instance_id,
                        target_ids=(context.actor_id,),
                        payload={
                            "operation": "rescue_with_wine",
                            "card_key": self.card_key,
                            "card_name": self.card_name,
                        },
                    )
                )
            return tuple(actions)
        return ()

    def apply_action(
        self, state: GameState, context: ActionContext, action: LegalAction
    ) -> GameState:
        session = self._require_session()
        if session.phase.value == "play":
            return session.apply_wine_buff(state, context, action, self)
        if session.phase.value == "dying_rescue":
            return session.apply_wine_self_rescue(state, context, action, self)
        raise InvalidActionError("【酒】生产适配器不能处理当前阶段的动作")


class TrickCardAdapter(BasicCardAdapter):
    """普通锦囊生产适配器的公共基类。

    本轮仅接入【无中生有】与【无懈可击】两个普通锦囊：前者在出牌
    阶段使用并建立【无懈可击】响应窗口，后者只在合法锦囊响应窗口
    使用。其余普通锦囊、延时锦囊与装备继续由注册表标记为未实现并
    失败关闭。
    """


class WuzhongshengyouAdapter(TrickCardAdapter):
    """【无中生有】的生产适配器。

    效果为摸2张牌，目标为自己；使用后建立【无懈可击】响应窗口，
    未被无效时执行摸牌，被无效时不摸牌但仍记录为已经使用。
    """

    def __init__(self, session: "ProductionBasicCardBatch | None" = None) -> None:
        super().__init__(session)
        self.card_key = "sgs_trick_wuzhongshengyou"
        self.card_name = "无中生有"

    def rule_spec(self) -> dict[str, object]:
        return {
            "card_key": self.card_key,
            "card_name": self.card_name,
            "use_timing": "own_play_phase",
            "use_limit": "unlimited_base;requires_entity_card",
            "target_count": 1,
            "target_filter": "self",
            "distance_rule": "not_applicable",
            "response_requirements": [
                {
                    "response_card_key": "sgs_trick_wuxiekeji",
                    "action": "use",
                    "event_type": "card_used",
                }
            ],
            "nullification_eligible": True,
            "movement_lifecycle": "hand->processing->discard",
            "effect_resolution": "nullification_window;draw_2_when_active",
            "damage_nature": "不适用",
            "completion_event": (
                "card_used + nullification_window + draw_2 or effect_cancelled"
            ),
            "adapter_version": self.adapter_version,
            "implemented": self.implemented,
            "tested": self.tested,
            "production_adapter": self.production_adapter,
        }

    def enumerate_legal_actions(
        self, state: GameState, context: ActionContext
    ) -> tuple[LegalAction, ...]:
        session = self._require_session()
        if session.phase.value != "play":
            return ()
        if context.actor_id != session.current_player_id:
            return ()
        actions: list[LegalAction] = []
        for instance_id in state.card_ids_in(ZoneRef.hand(context.actor_id)):
            card = state.cards_by_id[instance_id]
            if card.card_key != self.card_key:
                continue
            actions.append(
                LegalAction(
                    action_type=ActionType.USE_CARD,
                    actor_id=context.actor_id,
                    card_instance_id=instance_id,
                    target_ids=(context.actor_id,),
                    payload={
                        "operation": "use_wuzhong",
                        "card_key": self.card_key,
                        "card_name": self.card_name,
                    },
                )
            )
        return tuple(actions)

    def apply_action(
        self, state: GameState, context: ActionContext, action: LegalAction
    ) -> GameState:
        session = self._require_session()
        if session.phase.value == "play":
            return session.apply_wuzhong_use(state, context, action, self)
        raise InvalidActionError("【无中生有】生产适配器只能在出牌阶段使用")


class WuxiekejiAdapter(TrickCardAdapter):
    """【无懈可击】的生产适配器。

    只在合法普通锦囊响应窗口使用；响应动作生成 ``card_used`` 且不
    生成普通 ``card_played``。对【无懈可击】继续使用【无懈可击】时
    依项目确认的连续响应规则处理：响应顺序从当前回合角色开始按座次
    递增循环询问，连续一整轮无人响应后窗口关闭并按最终生效状态结算。
    每张响应事件的 ``response_to`` 指向当前直接响应对象（第一张指向
    原锦囊，之后逐张指向前一张【无懈可击】），``root_trick_instance_id``
    始终指向原锦囊实体。当前生产批次只实现双人座次响应链，不代表军八、
    2v2或斗地主多人响应链已经完成。
    """

    def __init__(self, session: "ProductionBasicCardBatch | None" = None) -> None:
        super().__init__(session)
        self.card_key = "sgs_trick_wuxiekeji"
        self.card_name = "无懈可击"

    def rule_spec(self) -> dict[str, object]:
        return {
            "card_key": self.card_key,
            "card_name": self.card_name,
            "use_timing": "trick_response_window",
            "use_limit": "unlimited_base;requires_legal_window_and_entity",
            "target_count": 1,
            "target_filter": "the_trick_effect_on_one_character",
            "distance_rule": "not_applicable",
            "response_requirements": [
                {
                    "response_to": (
                        "current_direct_response_object"
                        "(previous_wuxiekeji_or_original_trick)"
                    ),
                    "root_trick_instance_id": "original_trick_instance",
                    "action": "use",
                    "event_type": "card_used",
                }
            ],
            "nullification_eligible": True,
            "movement_lifecycle": "hand->processing->discard",
            "effect_resolution": (
                "cancel_one_trick_effect_on_one_character;"
                "itself_nullifiable_by_another_wuxiekeji"
            ),
            "damage_nature": "不适用",
            "completion_event": "card_used(response) + effect_cancelled(source trick)",
            "adapter_version": self.adapter_version,
            "implemented": self.implemented,
            "tested": self.tested,
            "production_adapter": self.production_adapter,
        }

    def enumerate_legal_actions(
        self, state: GameState, context: ActionContext
    ) -> tuple[LegalAction, ...]:
        session = self._require_session()
        if session.phase.value != "trick_response":
            return ()
        trick = session.runtime.pending_trick
        if trick is None:
            return ()
        actions: list[LegalAction] = []
        for instance_id in state.card_ids_in(ZoneRef.hand(context.actor_id)):
            card = state.cards_by_id[instance_id]
            if card.card_key != self.card_key:
                continue
            direct_response_to = session.runtime.trick_direct_response_to
            if direct_response_to is None:
                direct_response_to = trick.trick_instance_id
            actions.append(
                LegalAction(
                    action_type=ActionType.USE_CARD,
                    actor_id=context.actor_id,
                    card_instance_id=instance_id,
                    target_ids=(trick.target_id,),
                    payload={
                        "operation": "use_wuxie",
                        "card_key": self.card_key,
                        "card_name": self.card_name,
                        "response_to": direct_response_to,
                        "root_trick_instance_id": trick.trick_instance_id,
                    },
                )
            )
        return tuple(actions)

    def apply_action(
        self, state: GameState, context: ActionContext, action: LegalAction
    ) -> GameState:
        session = self._require_session()
        if session.phase.value == "trick_response":
            return session.apply_wuxie(state, context, action, self)
        raise InvalidActionError("【无懈可击】只能在合法锦囊响应窗口使用")


class GuoheChaiqiaoAdapter(TrickCardAdapter):
    """【过河拆桥】的生产适配器。

    出牌阶段以一名其他角色为目标使用；目标的手牌区、装备区与判定区
    合计必须至少存在一张合法实体牌。使用后建立与【无中生有】相同的
    【无懈可击】响应窗口；最终生效时进入目标区域选牌动作，把目标区域
    内的一张实体牌直接置入弃牌堆。本适配器不检查距离条件，也不把
    【顺手牵羊】的距离限制错误继承到本牌。
    """

    def __init__(self, session: "ProductionBasicCardBatch | None" = None) -> None:
        super().__init__(session)
        self.card_key = "sgs_trick_guohechaiqiao"
        self.card_name = "过河拆桥"

    def rule_spec(self) -> dict[str, object]:
        return {
            "card_key": self.card_key,
            "card_name": self.card_name,
            "use_timing": "own_play_phase",
            "use_limit": "unlimited_base;requires_entity_card",
            "target_count": 1,
            "target_filter": (
                "one_other_character_with_zone_card(hand|equipment|judgment)"
            ),
            "distance_rule": "not_applicable",
            "response_requirements": [
                {
                    "response_card_key": "sgs_trick_wuxiekeji",
                    "action": "use",
                    "event_type": "card_used",
                }
            ],
            "nullification_eligible": True,
            "movement_lifecycle": (
                "trick:hand->processing->discard;"
                "target_zone_card->discard(no_gain_then_discard)"
            ),
            "effect_resolution": (
                "nullification_window;discard_one_target_zone_card"
            ),
            "damage_nature": "不适用",
            "completion_event": (
                "card_used + nullification_window + "
                "card_moved(target->discard)+card_discarded or effect_cancelled"
            ),
            "adapter_version": self.adapter_version,
            "implemented": self.implemented,
            "tested": self.tested,
            "production_adapter": self.production_adapter,
        }

    def enumerate_legal_actions(
        self, state: GameState, context: ActionContext
    ) -> tuple[LegalAction, ...]:
        session = self._require_session()
        if session.phase.value == "play":
            if context.actor_id != session.current_player_id:
                return ()
            actions: list[LegalAction] = []
            for instance_id in state.card_ids_in(ZoneRef.hand(context.actor_id)):
                card = state.cards_by_id[instance_id]
                if card.card_key != self.card_key:
                    continue
                for target_id in state.players_by_id:
                    if target_id == context.actor_id:
                        continue
                    if not has_target_zone_cards(state, target_id):
                        continue
                    actions.append(
                        LegalAction(
                            action_type=ActionType.USE_CARD,
                            actor_id=context.actor_id,
                            card_instance_id=instance_id,
                            target_ids=(target_id,),
                            payload={
                                "operation": "use_guohe",
                                "card_key": self.card_key,
                                "card_name": self.card_name,
                            },
                        )
                    )
            return tuple(actions)
        if session.phase.value == "zone_choice":
            choice = session.runtime.pending_zone_choice
            if choice is None or choice.trick_key != self.card_key:
                return ()
            return session.enumerate_zone_choice_actions(state, context)
        return ()

    def apply_action(
        self, state: GameState, context: ActionContext, action: LegalAction
    ) -> GameState:
        session = self._require_session()
        if session.phase.value == "play":
            return session.apply_guohe_use(state, context, action, self)
        if session.phase.value == "zone_choice":
            return session.apply_zone_card_choice(state, context, action, self)
        raise InvalidActionError("【过河拆桥】生产适配器不能处理当前阶段的动作")


class ShunshouQianyangAdapter(TrickCardAdapter):
    """【顺手牵羊】的生产适配器。

    出牌阶段以与使用者实际距离为 1 的一名其他角色为目标使用；目标合法
    性调用正式 ``actual_distance`` 接口，武器攻击范围不影响该条件。
    坐骑距离修正尚未实现：坐骑栏占用导致距离无法判定时，本适配器不
    提供该目标的使用动作（失败关闭），应用层再次检查仍失败关闭。
    最终生效时进入目标区域选牌动作，把目标区域内的一张实体牌直接移入
    使用者手牌，不先公开目标手牌再选择。
    """

    def __init__(self, session: "ProductionBasicCardBatch | None" = None) -> None:
        super().__init__(session)
        self.card_key = "sgs_trick_shunshouqianyang"
        self.card_name = "顺手牵羊"

    def rule_spec(self) -> dict[str, object]:
        return {
            "card_key": self.card_key,
            "card_name": self.card_name,
            "use_timing": "own_play_phase",
            "use_limit": "unlimited_base;requires_entity_card",
            "target_count": 1,
            "target_filter": (
                "one_other_character_at_actual_distance_1_with_zone_card"
            ),
            "distance_rule": (
                "actual_distance(user,target)==1;"
                "weapon_attack_range_ignored;mount_modifiers_fail_closed"
            ),
            "response_requirements": [
                {
                    "response_card_key": "sgs_trick_wuxiekeji",
                    "action": "use",
                    "event_type": "card_used",
                }
            ],
            "nullification_eligible": True,
            "movement_lifecycle": (
                "trick:hand->processing->discard;"
                "target_zone_card->user_hand(direct_move)"
            ),
            "effect_resolution": (
                "nullification_window;gain_one_target_zone_card_into_user_hand"
            ),
            "damage_nature": "不适用",
            "completion_event": (
                "card_used + nullification_window + "
                "card_moved(target->user_hand)+card_lost+card_gained "
                "or effect_cancelled"
            ),
            "adapter_version": self.adapter_version,
            "implemented": self.implemented,
            "tested": self.tested,
            "production_adapter": self.production_adapter,
        }

    def enumerate_legal_actions(
        self, state: GameState, context: ActionContext
    ) -> tuple[LegalAction, ...]:
        session = self._require_session()
        if session.phase.value == "play":
            if context.actor_id != session.current_player_id:
                return ()
            actions: list[LegalAction] = []
            for instance_id in state.card_ids_in(ZoneRef.hand(context.actor_id)):
                card = state.cards_by_id[instance_id]
                if card.card_key != self.card_key:
                    continue
                for target_id in state.players_by_id:
                    if target_id == context.actor_id:
                        continue
                    if not has_target_zone_cards(state, target_id):
                        continue
                    try:
                        if not is_valid_shunshou_target(
                            state, context.actor_id, target_id
                        ):
                            continue
                    except UnsupportedRuleError:
                        # 坐骑修正未实现导致距离不可判定：不提供该动作，
                        # 不把“所有对手都可指定”硬编码进合法集合。
                        continue
                    actions.append(
                        LegalAction(
                            action_type=ActionType.USE_CARD,
                            actor_id=context.actor_id,
                            card_instance_id=instance_id,
                            target_ids=(target_id,),
                            payload={
                                "operation": "use_shunshou",
                                "card_key": self.card_key,
                                "card_name": self.card_name,
                            },
                        )
                    )
            return tuple(actions)
        if session.phase.value == "zone_choice":
            choice = session.runtime.pending_zone_choice
            if choice is None or choice.trick_key != self.card_key:
                return ()
            return session.enumerate_zone_choice_actions(state, context)
        return ()

    def apply_action(
        self, state: GameState, context: ActionContext, action: LegalAction
    ) -> GameState:
        session = self._require_session()
        if session.phase.value == "play":
            return session.apply_shunshou_use(state, context, action, self)
        if session.phase.value == "zone_choice":
            return session.apply_zone_card_choice(state, context, action, self)
        raise InvalidActionError("【顺手牵羊】生产适配器不能处理当前阶段的动作")


class JuedouAdapter(TrickCardAdapter):
    """【决斗】的生产适配器。

    出牌阶段以一名其他角色为目标使用，无距离限制、无基础每回合次数
    限制。使用后建立与【无中生有】相同的【无懈可击】响应窗口；生效后
    从目标开始，使用者和目标轮流打出【杀】，先停止或无法继续的一方
    受到另1名仍参与角色造成的1点无属性伤害。响应【决斗】的【杀】记录
    为打出（``card_played``）而非使用；已生成并开始结算的【决斗】不因
    来源死亡自动取消，但死亡角色不能继续打出【杀】，轮到死亡角色继续
    响应时【决斗】按项目已确认规则立即结束。
    """

    def __init__(self, session: "ProductionBasicCardBatch | None" = None) -> None:
        super().__init__(session)
        self.card_key = "sgs_trick_juedou"
        self.card_name = "决斗"

    def rule_spec(self) -> dict[str, object]:
        return {
            "card_key": self.card_key,
            "card_name": self.card_name,
            "use_timing": "own_play_phase",
            "use_limit": "unlimited_base;requires_entity_card",
            "target_count": 1,
            "target_filter": "one_other_character",
            "distance_rule": "not_applicable",
            "response_requirements": [
                {
                    "response_card_key": "sgs_trick_wuxiekeji",
                    "action": "use",
                    "event_type": "card_used",
                },
                {
                    "response_card_key": "any_slash(sgs_basic_sha|huosha|leisha)",
                    "action": "play",
                    "event_type": "card_played",
                    "note": (
                        "当前卡名为【杀】的正式实体【杀】才能响应；"
                        "只在使用时临时视为【杀】的材料牌不自动计入"
                    ),
                },
            ],
            "nullification_eligible": True,
            "movement_lifecycle": (
                "trick:hand->processing->discard;"
                "duel_slash:hand->processing->discard(played)"
            ),
            "effect_resolution": (
                "nullification_window;alternating_play_slash;"
                "stop_or_unable_side_takes_1_neutral_damage_from_other_side"
            ),
            "damage_nature": "无属性",
            "completion_event": (
                "card_used + nullification_window + card_played(duel slashes) + "
                "damage(+dying_rescue) or effect_cancelled"
            ),
            "adapter_version": self.adapter_version,
            "implemented": self.implemented,
            "tested": self.tested,
            "production_adapter": self.production_adapter,
        }

    def enumerate_legal_actions(
        self, state: GameState, context: ActionContext
    ) -> tuple[LegalAction, ...]:
        session = self._require_session()
        if session.phase.value == "play":
            if context.actor_id != session.current_player_id:
                return ()
            actions: list[LegalAction] = []
            for instance_id in state.card_ids_in(ZoneRef.hand(context.actor_id)):
                card = state.cards_by_id[instance_id]
                if card.card_key != self.card_key:
                    continue
                for target_id in state.players_by_id:
                    if target_id == context.actor_id:
                        continue
                    if not state.players_by_id[target_id].alive:
                        continue
                    actions.append(
                        LegalAction(
                            action_type=ActionType.USE_CARD,
                            actor_id=context.actor_id,
                            card_instance_id=instance_id,
                            target_ids=(target_id,),
                            payload={
                                "operation": "use_duel",
                                "card_key": self.card_key,
                                "card_name": self.card_name,
                            },
                        )
                    )
            return tuple(actions)
        if session.phase.value == "duel_response":
            return session.enumerate_duel_response_actions(state, context)
        return ()

    def apply_action(
        self, state: GameState, context: ActionContext, action: LegalAction
    ) -> GameState:
        session = self._require_session()
        if session.phase.value == "play":
            return session.apply_duel_use(state, context, action, self)
        if session.phase.value == "duel_response":
            return session.apply_duel_slash_play(state, context, action, self)
        raise InvalidActionError("【决斗】生产适配器不能处理当前阶段的动作")


class HuogongAdapter(TrickCardAdapter):
    """【火攻】的生产适配器。

    出牌阶段以一名至少有一张手牌的角色为目标使用，可包括自己，无距离
    限制、无基础每回合次数限制。使用后建立【无懈可击】响应窗口；生效后
    由目标选择一张手牌展示（展示牌不移动区域并公开牌面），再由使用者
    选择弃置一张与展示牌花色相同的手牌或不弃置；成功弃置则对目标造成
    1点火焰伤害。结算到展示步骤时若目标已无手牌，本次【火攻】无效果
    完成。目标选择展示牌时使用仅绑定选择窗口的不透明句柄，未展示手牌
    不进入其他角色决策视图。
    """

    def __init__(self, session: "ProductionBasicCardBatch | None" = None) -> None:
        super().__init__(session)
        self.card_key = "sgs_trick_huogong"
        self.card_name = "火攻"

    def rule_spec(self) -> dict[str, object]:
        return {
            "card_key": self.card_key,
            "card_name": self.card_name,
            "use_timing": "own_play_phase",
            "use_limit": "unlimited_base;requires_entity_card",
            "target_count": 1,
            "target_filter": (
                "one_character_with_at_least_one_hand_card_including_self"
            ),
            "distance_rule": "not_applicable",
            "response_requirements": [
                {
                    "response_card_key": "sgs_trick_wuxiekeji",
                    "action": "use",
                    "event_type": "card_used",
                },
                {
                    "response_action": "target_reveals_one_hand_card",
                    "event_type": "card_revealed",
                },
                {
                    "response_action": (
                        "user_discards_one_same_suit_hand_card_or_pass"
                    ),
                    "event_type": "card_discarded|no_discard",
                },
            ],
            "nullification_eligible": True,
            "movement_lifecycle": (
                "trick:hand->processing->discard;"
                "discarded_same_suit_card:hand->discard(direct)"
            ),
            "effect_resolution": (
                "nullification_window;target_reveal_one_hand_card;"
                "user_discard_same_suit_or_pass;if_discard_fire_damage_1"
            ),
            "damage_nature": "火属性",
            "completion_event": (
                "card_used + nullification_window + card_revealed + "
                "card_moved/lost/discarded(same_suit) + "
                "damage(+dying_rescue) or no_discard or effect_cancelled"
            ),
            "adapter_version": self.adapter_version,
            "implemented": self.implemented,
            "tested": self.tested,
            "production_adapter": self.production_adapter,
        }

    def enumerate_legal_actions(
        self, state: GameState, context: ActionContext
    ) -> tuple[LegalAction, ...]:
        session = self._require_session()
        if session.phase.value == "play":
            if context.actor_id != session.current_player_id:
                return ()
            actions: list[LegalAction] = []
            for instance_id in state.card_ids_in(ZoneRef.hand(context.actor_id)):
                card = state.cards_by_id[instance_id]
                if card.card_key != self.card_key:
                    continue
                for target_id in state.players_by_id:
                    if not state.players_by_id[target_id].alive:
                        continue
                    if not state.card_ids_in(ZoneRef.hand(target_id)):
                        continue
                    actions.append(
                        LegalAction(
                            action_type=ActionType.USE_CARD,
                            actor_id=context.actor_id,
                            card_instance_id=instance_id,
                            target_ids=(target_id,),
                            payload={
                                "operation": "use_fire_attack",
                                "card_key": self.card_key,
                                "card_name": self.card_name,
                            },
                        )
                    )
            return tuple(actions)
        if session.phase.value in (
            "fire_attack_reveal",
            "fire_attack_discard",
        ):
            return session.enumerate_fire_attack_actions(state, context)
        return ()

    def apply_action(
        self, state: GameState, context: ActionContext, action: LegalAction
    ) -> GameState:
        session = self._require_session()
        if session.phase.value == "play":
            return session.apply_fire_attack_use(state, context, action, self)
        if session.phase.value == "fire_attack_reveal":
            return session.apply_fire_attack_reveal(state, context, action, self)
        if session.phase.value == "fire_attack_discard":
            return session.apply_fire_attack_discard(state, context, action, self)
        raise InvalidActionError("【火攻】生产适配器不能处理当前阶段的动作")


class TiesuoLianhuanAdapter(TrickCardAdapter):
    """【铁索连环】牌本体的生产适配器。

    正常使用选择一名或两名互不相同的角色（可包含使用者，无距离限制）；
    目标结算顺序由服务器以使用者为锚点按行动顺序规范化，不信任玩家提交
    顺序。原锦囊保持在处理区直到全部目标结算完成；每名目标拥有独立
    【无懈可击】窗口，未被无懈的目标切换横置状态并产生可审计的
    ``chained_state`` 事件。重铸不是使用也不是打出：不产生普通
    ``card_used``／``card_played``、不指定目标、不接受【无懈可击】，
    实体从手牌直接进入弃牌堆后通过正式摸牌接口摸 1 张。

    CP-04J 起完整语义已接入统一生产伤害管线：横置角色实际受到大于0点
    火／雷属性伤害后解除横置并按当前回合角色为锚点的座次递增顺序建立
    确定性传导，每名候选以根基数继承原始来源、实体牌与伤害属性，濒死
    救援期间挂起，胜利成立时确定性清理未开始目标。
    """

    def __init__(
        self, session: "ProductionBasicCardBatch | None" = None
    ) -> None:
        super().__init__(session)
        self.card_key = "sgs_trick_tiesuolianhuan"
        self.card_name = "铁索连环"

    @property
    def adapter_version(self) -> str:
        return "production-basic-cards.sgs_trick_tiesuolianhuan.v2"

    def rule_spec(self) -> dict[str, object]:
        return {
            "card_key": self.card_key,
            "card_name": self.card_name,
            "use_timing": "own_play_phase",
            "use_limit": "unlimited_base;requires_entity_card_and_legal_targets",
            "target_count": "one_or_two",
            "target_filter": (
                "one_or_two_distinct_alive_characters_including_self;"
                "no_distance_requirement"
            ),
            "distance_rule": "not_applicable",
            "response_requirements": [
                {
                    "response_card_key": "sgs_trick_wuxiekeji",
                    "action": "use",
                    "event_type": "card_used",
                    "note": (
                        "多目标逐名结算，一张无懈只取消对当前角色的效果"
                    ),
                }
            ],
            "nullification_eligible": True,
            "movement_lifecycle": (
                "trick:hand->processing->discard(after_all_targets);"
                "recast:hand->discard(direct)+draw_1(tiesuo_recast)"
            ),
            "effect_resolution": (
                "per_target_nullification_window;"
                "per_target_chained_toggle(chained_state)"
            ),
            "damage_type": "不适用",
            "completion_event": (
                "card_used + per_target(chained_state + "
                "group_target_resolved|cancelled) + "
                "card_moved_to_discard_after_all_targets"
            ),
            "recast": {
                "legal": True,
                "event_type": "card_recast",
                "targetless": True,
                "no_wuxie_window": True,
                "no_card_used_or_played": True,
                "draw_after_recast": 1,
            },
            "chain_damage_implemented": True,
            "full_semantics_complete": True,
            "adapter_version": self.adapter_version,
            "implemented": self.implemented,
            "tested": self.tested,
            "production_adapter": self.production_adapter,
        }

    def _target_combinations(
        self, state: GameState, actor_id: str
    ) -> tuple[tuple[str, ...], ...]:
        alive_ids = tuple(
            player.player_id for player in state.players if player.alive
        )
        combinations: list[tuple[str, ...]] = []
        for size in (1, 2):
            for combo in itertools.combinations(alive_ids, size):
                combinations.append(
                    normalize_target_order(state, actor_id, combo)
                )
        return tuple(combinations)

    def enumerate_legal_actions(
        self, state: GameState, context: ActionContext
    ) -> tuple[LegalAction, ...]:
        session = self._require_session()
        if session.phase.value != "play":
            return ()
        if context.actor_id != session.current_player_id:
            return ()
        actions: list[LegalAction] = []
        for instance_id in state.card_ids_in(ZoneRef.hand(context.actor_id)):
            card = state.cards_by_id[instance_id]
            if card.card_key != self.card_key:
                continue
            for targets in self._target_combinations(state, context.actor_id):
                actions.append(
                    LegalAction(
                        action_type=ActionType.USE_CARD,
                        actor_id=context.actor_id,
                        card_instance_id=instance_id,
                        target_ids=targets,
                        payload={
                            "operation": "use_tiesuo",
                            "card_key": self.card_key,
                            "card_name": self.card_name,
                        },
                    )
                )
            actions.append(
                LegalAction(
                    action_type=ActionType.MOVE_CARD,
                    actor_id=context.actor_id,
                    card_instance_id=instance_id,
                    target_ids=(),
                    payload={
                        "operation": "recast_tiesuo",
                        "card_key": self.card_key,
                        "card_name": self.card_name,
                    },
                )
            )
        return tuple(actions)

    def apply_action(
        self, state: GameState, context: ActionContext, action: LegalAction
    ) -> GameState:
        session = self._require_session()
        if session.phase.value != "play":
            raise InvalidActionError(
                "【铁索连环】生产适配器只能在出牌阶段处理动作"
            )
        operation = str(action.payload.get("operation", ""))
        if operation == "use_tiesuo":
            return session.apply_tiesuo_use(state, context, action, self)
        if operation == "recast_tiesuo":
            return session.apply_tiesuo_recast(state, context, action, self)
        raise InvalidActionError("【铁索连环】出牌阶段动作负载无效")


class WugufengdengAdapter(TrickCardAdapter):
    """【五谷丰登】的生产适配器。

    使用时只提交使用动作，不提交目标列表：引擎按当前存活且仍在游戏中的
    角色数量快照目标序列，并一次性从牌堆展示等量实体牌到公共 REVEALED
    区域；展示池全部公开。从使用者开始按行动顺序逐名结算，每名目标拥有
    独立【无懈可击】窗口，被取消的目标不选牌；当前目标从公开展示池选择
    一张并获得。全部目标结算完成后剩余展示牌统一进入弃牌堆，原锦囊此时
    才从处理区进入弃牌堆；游戏提前结束也执行确定性清理。三人以上展示
    数量与完整顺序仍未由正式生产入口证明。
    """

    includes_self = True
    wounded_targets_only = False

    def __init__(
        self, session: "ProductionBasicCardBatch | None" = None
    ) -> None:
        super().__init__(session)
        self.card_key = "sgs_trick_wugufengdeng"
        self.card_name = "五谷丰登"

    def rule_spec(self) -> dict[str, object]:
        return {
            "card_key": self.card_key,
            "card_name": self.card_name,
            "use_timing": "own_play_phase",
            "use_limit": "unlimited_base;requires_entity_card_and_legal_targets",
            "target_count": "all_alive_characters_server_generated",
            "target_filter": (
                "all_alive_characters_including_user;"
                "snapshot_at_use_time"
            ),
            "distance_rule": "not_applicable",
            "response_requirements": [
                {
                    "response_card_key": "sgs_trick_wuxiekeji",
                    "action": "use",
                    "event_type": "card_used",
                    "note": (
                        "每名目标独立无懈窗口；一张无懈只取消当前目标的"
                        "选择，展示池保持并继续下一目标"
                    ),
                }
            ],
            "nullification_eligible": True,
            "movement_lifecycle": (
                "trick:hand->processing->discard(after_all_targets);"
                "pool:draw_pile->revealed->hand(picked)|discard(remaining)"
            ),
            "effect_resolution": (
                "reveal_public_pool;per_target_nullification_window;"
                "per_target_public_pick;remaining_to_discard;"
                "early_end_cleanup"
            ),
            "damage_type": "不适用",
            "completion_event": (
                "card_used + card_revealed(pool) + "
                "per_target(group_target_resolved picked|cancelled) + "
                "remaining_pool_card_moved + "
                "card_moved_to_discard_after_all_targets"
            ),
            "adapter_version": self.adapter_version,
            "implemented": self.implemented,
            "tested": self.tested,
            "production_adapter": self.production_adapter,
        }

    def enumerate_legal_actions(
        self, state: GameState, context: ActionContext
    ) -> tuple[LegalAction, ...]:
        session = self._require_session()
        if session.phase.value == "play":
            if context.actor_id != session.current_player_id:
                return ()
            actions: list[LegalAction] = []
            for instance_id in state.card_ids_in(ZoneRef.hand(context.actor_id)):
                card = state.cards_by_id[instance_id]
                if card.card_key != self.card_key:
                    continue
                actions.append(
                    LegalAction(
                        action_type=ActionType.USE_CARD,
                        actor_id=context.actor_id,
                        card_instance_id=instance_id,
                        target_ids=(),
                        payload={
                            "operation": "use_wugu",
                            "card_key": self.card_key,
                            "card_name": self.card_name,
                        },
                    )
                )
            return tuple(actions)
        if session.phase.value == "wugu_pick":
            return session.enumerate_wugu_pick_actions(state, context)
        return ()

    def apply_action(
        self, state: GameState, context: ActionContext, action: LegalAction
    ) -> GameState:
        session = self._require_session()
        if session.phase.value == "play":
            return session.apply_wugu_use(state, context, action, self)
        if session.phase.value == "wugu_pick":
            return session.apply_wugu_pick(state, context, action, self)
        raise InvalidActionError(
            "【五谷丰登】生产适配器不能处理当前阶段的动作"
        )


class GroupTargetTrickAdapter(TrickCardAdapter):
    """群体普通锦囊的公共适配器基类。

    三张群体锦囊（【南蛮入侵】【万箭齐发】【桃园结义】）共用同一套
    “自动目标序列＋按行动顺序逐目标结算”基础设施：使用时由服务器在
    运行时生成固定目标序列，玩家不能提交、修改、删减或重排目标；每个
    目标依次打开独立【无懈可击】窗口，当前目标被无懈只取消该目标效果。
    本适配器只描述卡牌自身参数，逐目标状态机由生产批处理会话统一推进，
    不为每张牌复制一套目标队列代码。
    """

    card_key: str
    card_name: str
    response_card_keys: tuple[str, ...] = ()
    includes_self: bool = False
    wounded_targets_only: bool = False
    damage_type: str = "无属性"
    response_phase_value: str | None = None
    response_operation: str | None = None

    def __init__(
        self, session: "ProductionBasicCardBatch | None" = None
    ) -> None:
        super().__init__(session)
        if self.card_key not in GROUP_TRICK_KEYS:
            raise ValueError(f"{self.card_key}不是本批次的群体普通锦囊卡牌键")

    def rule_spec(self) -> dict[str, object]:
        response_requirements: list[dict[str, object]] = [
            {
                "response_card_key": "sgs_trick_wuxiekeji",
                "action": "use",
                "event_type": "card_used",
                "note": (
                    "多目标锦囊逐名结算，一张无懈只抵消对当前角色的效果"
                ),
            }
        ]
        if self.response_card_keys:
            response_requirements.append(
                {
                    "response_card_key": (
                        "|".join(self.response_card_keys)
                    ),
                    "action": "play",
                    "event_type": "card_played",
                }
            )
        return {
            "card_key": self.card_key,
            "card_name": self.card_name,
            "use_timing": "own_play_phase",
            "use_limit": "unlimited_base;requires_entity_card_and_legal_targets",
            "target_count": "all_auto_generated_by_server",
            "target_filter": (
                "wounded_characters_including_self"
                if self.wounded_targets_only
                else "all_other_characters"
            ),
            "distance_rule": "not_applicable",
            "response_requirements": response_requirements,
            "nullification_eligible": True,
            "movement_lifecycle": (
                "trick:hand->processing->discard(after_all_targets);"
                "response_card:hand->processing->discard(played)"
            ),
            "effect_resolution": (
                "per_target_nullification_window;then_per_target_effect;"
                "target_sequence_advanced_by_server"
            ),
            "damage_type": self.damage_type,
            "completion_event": (
                "card_used + per_target(card_played|damage|recover|cancel) + "
                "card_moved_to_discard_after_all_targets"
            ),
            "adapter_version": self.adapter_version,
            "implemented": self.implemented,
            "tested": self.tested,
            "production_adapter": self.production_adapter,
        }

    def enumerate_legal_actions(
        self, state: GameState, context: ActionContext
    ) -> tuple[LegalAction, ...]:
        session = self._require_session()
        if session.phase.value == "play":
            if context.actor_id != session.current_player_id:
                return ()
            actions: list[LegalAction] = []
            for instance_id in state.card_ids_in(ZoneRef.hand(context.actor_id)):
                card = state.cards_by_id[instance_id]
                if card.card_key != self.card_key:
                    continue
                actions.append(
                    LegalAction(
                        action_type=ActionType.USE_CARD,
                        actor_id=context.actor_id,
                        card_instance_id=instance_id,
                        payload={
                            "operation": (
                                "use_nanman"
                                if self.card_key == "sgs_trick_nanmanruqin"
                                else "use_wanjian"
                                if self.card_key == "sgs_trick_wanjianqifa"
                                else "use_taoyuan"
                            ),
                            "card_key": self.card_key,
                            "card_name": self.card_name,
                        },
                    )
                )
            return tuple(actions)
        if session.phase.value == self.response_phase_value:
            if self.response_operation is None:
                return ()
            return session.enumerate_group_response_actions(
                state, context, self
            )
        return ()

    def apply_action(
        self, state: GameState, context: ActionContext, action: LegalAction
    ) -> GameState:
        session = self._require_session()
        if session.phase.value == "play":
            return session.apply_group_trick_use(
                state, context, action, self
            )
        if session.phase.value == self.response_phase_value:
            if self.response_operation is None:
                raise InvalidActionError(
                    f"{self.card_name}没有响应阶段动作"
                )
            return session.apply_group_response_play(
                state, context, action, self
            )
        raise InvalidActionError(
            f"{self.card_name}生产适配器不能处理当前阶段的动作"
        )


class NanmanRuqinAdapter(GroupTargetTrickAdapter):
    """【南蛮入侵】的生产适配器。

    目标为除使用者外的所有其他角色；每名目标依次结算，未打出1张【杀】
    的目标受到使用者造成的1点无属性伤害。
    """

    def __init__(
        self, session: "ProductionBasicCardBatch | None" = None
    ) -> None:
        self.card_key = "sgs_trick_nanmanruqin"
        self.card_name = "南蛮入侵"
        self.response_card_keys = SLASH_CARD_KEYS
        self.response_phase_value = "nanman_response"
        self.response_operation = "play_slash_for_nanman"
        super().__init__(session)


class WanjianQifaAdapter(GroupTargetTrickAdapter):
    """【万箭齐发】的生产适配器。

    目标为除使用者外的所有其他角色；每名目标依次结算，未打出1张【闪】
    的目标受到使用者造成的1点无属性伤害。
    """

    def __init__(
        self, session: "ProductionBasicCardBatch | None" = None
    ) -> None:
        self.card_key = "sgs_trick_wanjianqifa"
        self.card_name = "万箭齐发"
        self.response_card_keys = ("sgs_basic_shan",)
        self.response_phase_value = "wanjian_response"
        self.response_operation = "play_jink_for_wanjian"
        super().__init__(session)


class TaoyuanJieyiAdapter(GroupTargetTrickAdapter):
    """【桃园结义】的生产适配器。

    目标为所有已受伤角色（包括使用者）；每名目标依次结算，受伤目标恢复
    1点体力且不超过体力上限，未受伤目标结算为无效果。目标集合在使用时
    由服务器快照生成，结算时不动态增删目标。
    """

    def __init__(
        self, session: "ProductionBasicCardBatch | None" = None
    ) -> None:
        self.card_key = "sgs_trick_taoyuanjieyi"
        self.card_name = "桃园结义"
        self.includes_self = True
        self.wounded_targets_only = True
        super().__init__(session)


class WeaponCardAdapter(BasicCardAdapter):
    """11种武器牌本体的通用生产适配器（CP-04K）。

    只实现牌本体：出牌阶段主动使用、武器进入weapon槽、同槽替换把旧武器
    原子移入弃牌堆、攻击范围按正式结构化CSV登记值动态计算、装备区公开。
    武器专属技能全部保持 partial，由 ``check_weapon_skill_gate`` 集中
    失败关闭，不近似为无效果。
    """

    def __init__(
        self,
        card_key: str,
        session: "ProductionBasicCardBatch | None" = None,
    ) -> None:
        super().__init__(session)
        if card_key not in PRODUCTION_WEAPON_KEYS:
            raise ValueError(f"{card_key}不是本批次的武器卡牌键")
        self.card_key = card_key
        self.card_name = CARD_NAMES_BY_KEY[card_key]
        self._attack_range = weapon_attack_ranges()[card_key]

    def rule_spec(self) -> dict[str, object]:
        return {
            "card_key": self.card_key,
            "card_name": self.card_name,
            "use_timing": "own_play_phase",
            "use_limit": "unlimited_base;requires_entity_card",
            "target_count": 0,
            "target_filter": "self_equip_weapon_slot",
            "equipment_slot": "weapon",
            "attack_range": self._attack_range,
            "skill_status": "partial",
            "skill_effect": "not_implemented_fail_closed",
            "movement_lifecycle": "hand->processing->weapon_slot",
            "replacement": "old_weapon_atomic_to_discard",
            "adapter_version": self.adapter_version,
            "implemented": self.implemented,
            "tested": self.tested,
            "production_adapter": self.production_adapter,
        }

    def enumerate_legal_actions(
        self, state: GameState, context: ActionContext
    ) -> tuple[LegalAction, ...]:
        session = self._require_session()
        if session.phase.value != "play":
            return ()
        if context.actor_id != session.runtime.current_player_id:
            return ()
        actions: list[LegalAction] = []
        for instance_id in state.card_ids_in(ZoneRef.hand(context.actor_id)):
            card = state.cards_by_id[instance_id]
            if card.card_key != self.card_key:
                continue
            actions.append(
                LegalAction(
                    action_type=ActionType.USE_CARD,
                    actor_id=context.actor_id,
                    card_instance_id=instance_id,
                    target_ids=(context.actor_id,),
                    payload={
                        "operation": "use_weapon",
                        "card_key": self.card_key,
                        "card_name": self.card_name,
                    },
                )
            )
        return tuple(actions)

    def apply_action(
        self, state: GameState, context: ActionContext, action: LegalAction
    ) -> GameState:
        session = self._require_session()
        if session.phase.value == "play":
            return session.apply_weapon_use(state, context, action, self)
        raise InvalidActionError(
            f"{self.card_name}生产适配器不能处理当前阶段的动作"
        )


class JiedaoSharenAdapter(TrickCardAdapter):
    """【借刀杀人】的生产适配器（CP-04K）。

    出牌阶段选择第一目标（装备区有武器的其他角色）与第二目标（第一目标
    攻击范围内、应使用【杀】的角色）。锦囊只以第一目标为无懈目标；生效
    后第一目标选择使用一张实体普通／火／雷【杀】或拒绝；使用后视为履行
    要求，拒绝或无法使用时把第一目标当前武器交给借刀使用者手牌。
    """

    def __init__(self, session: "ProductionBasicCardBatch | None" = None) -> None:
        super().__init__(session)
        self.card_key = "sgs_trick_jiedaosharen"
        self.card_name = "借刀杀人"

    def rule_spec(self) -> dict[str, object]:
        return {
            "card_key": self.card_key,
            "card_name": self.card_name,
            "use_timing": "own_play_phase",
            "use_limit": "unlimited_base;requires_entity_card",
            "target_count": 1,
            "target_filter": (
                "first_target_other_with_weapon;"
                "second_target_in_first_target_attack_range"
            ),
            "nullification_eligible": True,
            "nullification_target": "first_target_only",
            "movement_lifecycle": "trick:hand->processing->discard",
            "effect": (
                "first_target_uses_slash_on_second_target_or_"
                "delivers_current_weapon_to_user_hand"
            ),
            "adapter_version": self.adapter_version,
            "implemented": self.implemented,
            "tested": self.tested,
            "production_adapter": self.production_adapter,
        }

    def _enumerate_use(
        self, state: GameState, context: ActionContext
    ) -> tuple[LegalAction, ...]:
        session = self._require_session()
        if context.actor_id != session.runtime.current_player_id:
            return ()
        actions: list[LegalAction] = []
        for instance_id in state.card_ids_in(ZoneRef.hand(context.actor_id)):
            card = state.cards_by_id[instance_id]
            if card.card_key != self.card_key:
                continue
            for first_target in state.players_by_id:
                if first_target == context.actor_id:
                    continue
                if not state.card_ids_in(
                    ZoneRef.equipment(first_target, "weapon")
                ):
                    continue
                for second_target in state.players_by_id:
                    if second_target == first_target:
                        continue
                    if not is_valid_slash_target(
                        state, first_target, second_target
                    ):
                        continue
                    actions.append(
                        LegalAction(
                            action_type=ActionType.USE_CARD,
                            actor_id=context.actor_id,
                            card_instance_id=instance_id,
                            target_ids=(first_target,),
                            payload={
                                "operation": "use_jiedao",
                                "card_key": self.card_key,
                                "card_name": self.card_name,
                                "second_target_id": second_target,
                                "purpose": "force_slash_or_weapon_gain",
                            },
                        )
                    )
        return tuple(actions)

    def enumerate_legal_actions(
        self, state: GameState, context: ActionContext
    ) -> tuple[LegalAction, ...]:
        session = self._require_session()
        if session.phase.value == "play":
            return self._enumerate_use(state, context)
        if session.phase.value == "borrowed_sword_choice":
            return session.enumerate_borrowed_sword_actions(state, context)
        return ()

    def apply_action(
        self, state: GameState, context: ActionContext, action: LegalAction
    ) -> GameState:
        session = self._require_session()
        if session.phase.value == "play":
            return session.apply_jiedao_use(state, context, action, self)
        if session.phase.value == "borrowed_sword_choice":
            operation = str(action.payload.get("operation", ""))
            if operation in (
                "choose_borrowed_sword_slash",
                "refuse_borrowed_sword_slash",
            ):
                return session.apply_borrowed_sword_slash_choice(
                    state, context, action
                )
        raise InvalidActionError(
            f"{self.card_name}生产适配器不能处理当前阶段的动作"
        )

def _default_adapters() -> dict[str, RuleAdapter]:
    return {
        "sgs_basic_sha": SlashAdapter("sgs_basic_sha", "无属性"),
        "sgs_basic_huosha": SlashAdapter("sgs_basic_huosha", "火属性"),
        "sgs_basic_leisha": SlashAdapter("sgs_basic_leisha", "雷属性"),
        "sgs_basic_shan": DodgeAdapter(),
        "sgs_basic_tao": PeachAdapter(),
        "sgs_basic_jiu": WineAdapter(),
        "sgs_trick_wuzhongshengyou": WuzhongshengyouAdapter(),
        "sgs_trick_wuxiekeji": WuxiekejiAdapter(),
        "sgs_trick_guohechaiqiao": GuoheChaiqiaoAdapter(),
        "sgs_trick_shunshouqianyang": ShunshouQianyangAdapter(),
        "sgs_trick_juedou": JuedouAdapter(),
        "sgs_trick_huogong": HuogongAdapter(),
        "sgs_trick_nanmanruqin": NanmanRuqinAdapter(),
        "sgs_trick_wanjianqifa": WanjianQifaAdapter(),
        "sgs_trick_taoyuanjieyi": TaoyuanJieyiAdapter(),
        "sgs_trick_tiesuolianhuan": TiesuoLianhuanAdapter(),
        "sgs_trick_wugufengdeng": WugufengdengAdapter(),
        "sgs_trick_jiedaosharen": JiedaoSharenAdapter(),
        "sgs_weapon_zhugeliannu": WeaponCardAdapter("sgs_weapon_zhugeliannu"),
        "sgs_weapon_qinggangjian": WeaponCardAdapter("sgs_weapon_qinggangjian"),
        "sgs_weapon_hanbingjian": WeaponCardAdapter("sgs_weapon_hanbingjian"),
        "sgs_weapon_cixiongshuanggujian": WeaponCardAdapter(
            "sgs_weapon_cixiongshuanggujian"
        ),
        "sgs_weapon_gudingdao": WeaponCardAdapter("sgs_weapon_gudingdao"),
        "sgs_weapon_qinglongyanyuedao": WeaponCardAdapter(
            "sgs_weapon_qinglongyanyuedao"
        ),
        "sgs_weapon_guanshifu": WeaponCardAdapter("sgs_weapon_guanshifu"),
        "sgs_weapon_zhangbashemao": WeaponCardAdapter(
            "sgs_weapon_zhangbashemao"
        ),
        "sgs_weapon_fangtianhuaji": WeaponCardAdapter(
            "sgs_weapon_fangtianhuaji"
        ),
        "sgs_weapon_zhuqueyushan": WeaponCardAdapter(
            "sgs_weapon_zhuqueyushan"
        ),
        "sgs_weapon_qilingong": WeaponCardAdapter("sgs_weapon_qilingong"),
    }


class FormalCardRegistry:
    """由正式160张牌堆CSV建立的正式卡牌注册表。

    注册表保证：总实体牌数仍为160、每张牌实例ID唯一、六种基本牌映射到
    生产适配器、其他卡牌明确标记为未实现。未实现卡牌不能通过fallback
    继续结算；测试专用适配器永远不会进入本注册表。
    """

    def __init__(
        self,
        records: Sequence[DeckRecord],
        *,
        adapters: Mapping[str, RuleAdapter] | None = None,
        session: "ProductionBasicCardBatch | None" = None,
    ) -> None:
        prepared = tuple(records)
        if not prepared:
            raise UnsupportedRuleError("正式卡牌注册表不能为空")
        if len(prepared) != 160:
            raise UnsupportedRuleError(
                f"正式卡牌注册表必须恰好包含160张实体牌；当前为{len(prepared)}"
            )
        instance_ids = [record.instance_id for record in prepared]
        if any(not instance_id.strip() for instance_id in instance_ids):
            raise UnsupportedRuleError("正式卡牌注册表的实例ID不能为空")
        if len(instance_ids) != len(set(instance_ids)):
            raise UnsupportedRuleError("正式卡牌注册表的实例ID必须全局唯一")
        self._records = prepared
        self._by_key: dict[str, tuple[DeckRecord, ...]] = {}
        for record in prepared:
            self._by_key.setdefault(record.card_key, []).append(record)
        self._by_key = {
            key: tuple(items) for key, items in self._by_key.items()
        }
        selected = dict(adapters) if adapters is not None else _default_adapters()
        for key, adapter in selected.items():
            if not isinstance(adapter, RuleAdapter):
                raise TypeError(f"卡牌{key}的生产适配器必须是RuleAdapter")
            if adapter.card_key != key:
                raise UnsupportedRuleError(
                    f"适配器声明键{adapter.card_key}与注册键{key}不一致"
                )
            adapter._session = session
        self._adapters = dict(selected)
        self._implemented_instances = frozenset(
            record.instance_id
            for record in prepared
            if record.card_key in self._adapters
        )
        self._unimplemented_keys = tuple(
            sorted(set(self._by_key).difference(self._adapters))
        )

    @classmethod
    def from_formal_csv(
        cls,
        deck_path: str | Path = DEFAULT_DECK_PATH,
        *,
        session: "ProductionBasicCardBatch | None" = None,
        adapters: Mapping[str, RuleAdapter] | None = None,
    ) -> "FormalCardRegistry":
        records, audit = load_deck_csv(Path(deck_path), expected_total=160)
        AuthoritativeCoreSession._validate_formal_deck(records, audit)
        return cls(records, adapters=adapters, session=session)

    @property
    def records(self) -> tuple[DeckRecord, ...]:
        return self._records

    @property
    def card_count(self) -> int:
        return len(self._records)

    @property
    def instance_ids(self) -> tuple[str, ...]:
        return tuple(record.instance_id for record in self._records)

    @property
    def implemented_card_keys(self) -> tuple[str, ...]:
        return tuple(sorted(self._adapters))

    @property
    def unimplemented_card_keys(self) -> tuple[str, ...]:
        return self._unimplemented_keys

    @property
    def adapters(self) -> Mapping[str, RuleAdapter]:
        return MappingProxyType(dict(self._adapters))

    def instances_of(self, card_key: str) -> tuple[DeckRecord, ...]:
        try:
            return self._by_key[card_key]
        except KeyError as exc:
            raise UnsupportedRuleError(f"正式牌堆不存在卡牌{card_key!r}") from exc

    def adapter_for(self, card_key: str) -> BasicCardAdapter:
        try:
            return self._adapters[card_key]
        except KeyError as exc:
            raise UnsupportedRuleError(
                f"卡牌{card_key!r}尚未实现生产适配器；禁止fallback或近似结算"
            ) from exc

    def rule_spec_for(self, card_key: str) -> dict[str, object]:
        return self.adapter_for(card_key).rule_spec()

    def is_implemented_instance(self, instance_id: str) -> bool:
        return instance_id in self._implemented_instances

    def ensure_all_basic_cards_implemented(self) -> bool:
        missing = set(PRODUCTION_BASIC_CARD_KEYS).difference(self._adapters)
        if missing:
            raise UnsupportedRuleError(
                "六种基本牌必须全部接入生产适配器；缺少："
                + "、".join(sorted(missing))
            )
        return True

    def assert_no_unimplemented_fallback(self) -> None:
        if self._unimplemented_keys:
            raise UnsupportedRuleError(
                "正式整局仍被未实现卡牌阻塞："
                + "、".join(self._unimplemented_keys)
                + "；不得跳过这些卡牌继续整局"
            )


__all__ = [
    "CARD_NAMES_BY_KEY",
    "DEFAULT_ATTACK_RANGE",
    "GROUP_TRICK_KEYS",
    "PRODUCTION_BASIC_CARD_KEYS",
    "PRODUCTION_TRICK_KEYS",
    "SLASH_CARD_KEYS",
    "GuoheChaiqiaoAdapter",
    "GroupTargetTrickAdapter",
    "HuogongAdapter",
    "JiedaoSharenAdapter",
    "JuedouAdapter",
    "NanmanRuqinAdapter",
    "PRODUCTION_WEAPON_KEYS",
    "ShunshouQianyangAdapter",
    "TaoyuanJieyiAdapter",
    "TiesuoLianhuanAdapter",
    "TrickCardAdapter",
    "WanjianQifaAdapter",
    "WugufengdengAdapter",
    "WuxiekejiAdapter",
    "WuzhongshengyouAdapter",
    "WeaponCardAdapter",
    "BasicCardAdapter",
    "DodgeAdapter",
    "FormalCardRegistry",
    "PeachAdapter",
    "SlashAdapter",
    "WineAdapter",
    "actual_distance",
    "attack_range_of",
    "check_weapon_skill_gate",
    "weapon_attack_ranges",
    "has_target_zone_cards",
    "is_valid_shunshou_target",
    "is_valid_slash_target",
    "normalize_target_order",
    "target_zone_refs",
]
