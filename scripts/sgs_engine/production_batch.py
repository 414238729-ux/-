# -*- coding: utf-8 -*-
"""正式160张牌堆中六种基本牌的生产批处理会话。

本模块在权威核心（GameState、EventQueue、ResponseWindow、DamageEvent、
LegalAction、单一 DeterministicRNG 与状态哈希）之上，为六种基本牌和
最小普通锦囊垂直切片（【无中生有】、【无懈可击】）提供真实的生产结算
路径。它明确不是完整整局引擎：只包含本批次卡牌完成使用、响应、无效、
伤害、濒死、救援、死亡与胜负所需的阶段与窗口；遇到未实现卡牌时在
注册表层失败关闭。

所有动作都经过：

    enumerate_legal_actions -> validate_action -> apply_action

控制器、测试或任何调用方都不能直接修改状态；合法动作一旦签发就绑定
状态、上下文、注册表指纹与适配器审计状态，过期或伪造动作会被拒绝。
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
import hashlib
import hmac
import json
from pathlib import Path
import secrets
from types import MappingProxyType
from typing import Iterable, Mapping, Sequence

from ..deck_data import DeckRecord, load_deck_csv
from .actions import (
    ActionContext,
    ActionType,
    InvalidActionError,
    LegalAction,
    RuleAdapter,
    RuleRegistry,
    UnsupportedRuleError,
    apply_action,
    enumerate_legal_actions,
    validate_action,
)
from .engine import (
    DEFAULT_DECK_PATH,
    ENGINE_VERSION,
    AuthoritativeCoreSession,
    canonical_state_snapshot,
)
from .events import (
    DamageEvent,
    EventQueue,
    EventType,
    GameEvent,
    ResponseWindow,
)
from .model import (
    DISCARD_PILE,
    DRAW_PILE,
    EQUIPMENT_SLOTS,
    PROCESSING_ZONE,
    REVEALED_ZONE,
    CardInstance,
    GameState,
    PlayerState,
    ZoneKind,
    ZoneRef,
)
from .production_cards import (
    FormalCardRegistry,
    GroupTargetTrickAdapter,
    GuoheChaiqiaoAdapter,
    HuogongAdapter,
    JuedouAdapter,
    NanmanRuqinAdapter,
    ShunshouQianyangAdapter,
    SlashAdapter,
    TaoyuanJieyiAdapter,
    TiesuoLianhuanAdapter,
    WanjianQifaAdapter,
    WugufengdengAdapter,
    WuxiekejiAdapter,
    WuzhongshengyouAdapter,
    PRODUCTION_ARMOR_KEYS,
    SLASH_CARD_KEYS,
    actual_distance,
    check_weapon_skill_gate,
    equipped_weapon_key,
    hand_limit_of,
    has_target_zone_cards,
    is_valid_shunshou_target,
    is_valid_slash_target,
    normalize_target_order,
    target_zone_refs,
)
from .replay import canonical_json, sha256_value, state_sha256
from .rng import DeterministicRNG, RNGCall


PRODUCTION_BASIC_CARDS_MODE = "production_basic_cards_batch"


class ProductionPhase(str, Enum):
    PREPARE = "prepare"
    JUDGMENT = "judgment"
    JUDGMENT_WUXIE = "judgment_wuxie"
    DRAW = "draw"
    PLAY = "play"
    SLASH_RESPONSE = "slash_response"
    TRICK_RESPONSE = "trick_response"
    ZONE_CHOICE = "zone_choice"
    DUEL_RESPONSE = "duel_response"
    FIRE_ATTACK_REVEAL = "fire_attack_reveal"
    FIRE_ATTACK_DISCARD = "fire_attack_discard"
    BORROWED_SWORD_CHOICE = "borrowed_sword_choice"
    NANMAN_RESPONSE = "nanman_response"
    WANJIAN_RESPONSE = "wanjian_response"
    WUGU_PICK = "wugu_pick"
    WEAPON_AFTER_DAMAGE = "weapon_after_damage"
    WEAPON_SLASH_CHOICE = "weapon_slash_choice"
    WEAPON_DISCARD_TWO = "weapon_discard_two"
    HANBING_DISCARD = "hanbing_discard"
    DYING_RESCUE = "dying_rescue"
    DISCARD = "discard"
    END = "end"
    FINISHED = "finished"


BATCH_PHASES: tuple[ProductionPhase, ...] = (
    ProductionPhase.PREPARE,
    ProductionPhase.JUDGMENT,
    ProductionPhase.JUDGMENT_WUXIE,
    ProductionPhase.DRAW,
    ProductionPhase.PLAY,
    ProductionPhase.SLASH_RESPONSE,
    ProductionPhase.TRICK_RESPONSE,
    ProductionPhase.ZONE_CHOICE,
    ProductionPhase.DUEL_RESPONSE,
    ProductionPhase.FIRE_ATTACK_REVEAL,
    ProductionPhase.FIRE_ATTACK_DISCARD,
    ProductionPhase.BORROWED_SWORD_CHOICE,
    ProductionPhase.NANMAN_RESPONSE,
    ProductionPhase.WANJIAN_RESPONSE,
    ProductionPhase.WUGU_PICK,
    ProductionPhase.WEAPON_AFTER_DAMAGE,
    ProductionPhase.WEAPON_SLASH_CHOICE,
    ProductionPhase.WEAPON_DISCARD_TWO,
    ProductionPhase.HANBING_DISCARD,
    ProductionPhase.DYING_RESCUE,
    ProductionPhase.DISCARD,
    ProductionPhase.END,
)


class ProductionBatchError(RuntimeError):
    """生产基本牌批处理会话不能继续执行时的基础异常。"""


class ProductionBatchFinishedError(ProductionBatchError):
    """胜利已经成立后仍尝试继续推进对局。"""


class ProductionBatchSafetyLimitError(ProductionBatchError):
    """动作步数超过显式安全上限时失败关闭。"""


class ProductionBatchDeckExhaustedError(ProductionBatchError):
    """牌堆与可重洗弃牌堆合计不足时失败关闭。"""


@dataclass(frozen=True, slots=True)
class BatchPhaseEntry:
    turn_number: int
    turn_player_id: str
    phase: ProductionPhase


@dataclass(frozen=True, slots=True)
class _PendingSlash:
    attacker_id: str
    target_id: str
    slash_instance_id: str
    boosted: bool
    # CP-04P 武器技能状态：青釭剑本次杀令目标防具无效（armor invalid），
    # 起点为“使用【杀】指定一个目标后”，持续至闪结算完成或本次伤害结算
    # 完成（Knowledge 7.2.1 用户移动版实测确认）。古锭刀伤害+1 不由本结构
    # 快照：判定点在“造成伤害时”，由统一伤害判定点（_weapon_damage_bonus_
    # at_damage）按目标当前权威手牌动态计算（Knowledge 7.5.1，
    # IN_GAME_CARD_TEXT_CONFIRMED＋USER_CONFIRMED_MOBILE_RULE）。
    ignore_armor: bool = False
    # CP-04P 朱雀羽扇：普通【杀】完成目标指定后可选转为【火杀】（7.10）。
    fire_converted: bool = False
    # CP-04P 丈八蛇矛（7.8 当前确认）：两张手牌当作普通【杀】使用或打出。
    # 虚拟杀不是新的实体卡牌：不进入 state.cards / zones，牌守恒继续针对
    # 实体牌成立；两张实体材料按正式规则进入弃牌堆。virtual_id 为确定性
    # 合成标识（回合＋两张材料），可被 replay / strict reexecute / events /
    # player_visible 正确表示。
    virtual: bool = False
    material_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class _PendingTrick:
    user_id: str
    target_id: str
    trick_instance_id: str
    trick_key: str


@dataclass(frozen=True, slots=True)
class _PendingZoneChoice:
    """普通锦囊生效后打开的目标区域选牌窗口。

    该窗口绑定原锦囊实例、使用者、目标角色与选择窗口标识；隐藏手牌
    候选只通过不透明句柄暴露，真实实体映射保存在运行时的
    ``zone_choice_handles`` 中，由权威引擎解析。
    """

    user_id: str
    target_id: str
    trick_instance_id: str
    trick_key: str
    window_id: str
    zones: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _PendingDuel:
    """【决斗】生效后的交替打出【杀】结算状态。

    保存根【决斗】实体、使用者、目标、当前响应者、对方参与者、当前
    第几次响应与已打出【杀】的次序，供事件审计与失败关闭校验。
    """

    user_id: str
    target_id: str
    trick_instance_id: str
    responder_id: str
    opponent_id: str
    round_index: int = 0
    response_index: int = 0
    slash_sequence: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class _PendingFireAttack:
    """【火攻】生效后的展示与同花色弃置结算状态。"""

    user_id: str
    target_id: str
    trick_instance_id: str
    reveal_window_id: str
    revealed_instance_id: str | None = None
    revealed_suit: str | None = None


@dataclass(frozen=True, slots=True)
class _PendingGroupTrick:
    """群体普通锦囊逐目标结算状态机。

    保存根锦囊实体、使用者、使用时快照的固定目标序列、当前目标索引、
    已完成目标与当前响应目标。目标集合由服务器在使用时自动生成，不
    接收玩家提交、删减或重排的目标；每个目标依次建立独立的
    【无懈可击】窗口与效果步骤，前一目标的无懈状态不会泄漏到后一目标。
    濒死救援期间本状态保留在运行时中，救援完成后按索引继续推进。
    """

    user_id: str
    trick_instance_id: str
    trick_key: str
    target_sequence: tuple[str, ...]
    current_target_index: int = 0
    completed_target_ids: tuple[str, ...] = ()
    responder_id: str | None = None


@dataclass(frozen=True, slots=True)
class _PendingWugu:
    """五谷丰登公开展示池与逐目标选择状态机。

    展示池实体以公共 REVEALED 区域的权威顺序为唯一事实，``pool_digest``
    是使用时与每次选牌后更新的一次性有序摘要；公共选择动作必须同时绑定
    会话、当前窗口、根锦囊实例、当前选择目标、当前目标索引、展示池有序
    摘要与状态哈希，任何过期、跨窗口或伪造选择都会失败关闭。
    """

    user_id: str
    trick_instance_id: str
    trick_key: str
    pool: tuple[str, ...]
    pool_digest: str
    target_sequence: tuple[str, ...]
    current_target_index: int = 0
    completed_target_ids: tuple[str, ...] = ()
    window_id: str | None = None


@dataclass(frozen=True, slots=True)
class _PendingBorrowedSword:
    """【借刀杀人】的外层根结算挂起状态。

    借刀是整个外层根；被要求使用的【杀】是其子结算。该结构不得覆盖
    pending_slash／pending_trick／pending_chain／pending_dying 等既有
    挂起字段，子结算结束后通过明确出口恢复本状态。``weapon_instance_id``
    只作审计快照，不作为交付时唯一依据；``chosen_slash_instance_id``
    只存在于权威端，私有句柄材料不进入玩家可见回放。
    """

    user_id: str
    trick_instance_id: str
    first_target_id: str
    second_target_id: str
    effect_active: bool
    stage: str
    weapon_instance_id: str | None = None
    slash_choice_snapshot_digest: str | None = None
    chosen_slash_instance_id: str | None = None
    decision: str | None = None
    session_id: str = ""
    requirement_fulfilled: bool = False
    game_over_cleanup: bool = False
    root_discarded: bool = False


@dataclass(frozen=True, slots=True)
class _PendingJudgment:
    """延时锦囊判定结算挂起状态（CP-04L）。

    判定阶段选中当前角色判定区下一张延时锦囊后建立：先进入判定前
    【无懈可击】窗口（awaiting_wuxie），未被抵消后翻判定牌并进入效果
    结算（resolving_effect）；闪电伤害、传导与濒死期间保持挂起，
    子结算完成后恢复判定阶段。"""

    trick_instance_id: str
    trick_key: str
    target_id: str
    stage: str
    entry_index: int = 0
    wuxie_nullified: bool = False
    cleanup_done: bool = False

class _ChainStepOutcome(str, Enum):
    """传导目标结算后的明确控制流结果。"""

    CONTINUE = "continue_chain"
    FINISHED = "chain_finished"
    PAUSED = "paused_for_rescue"


@dataclass(frozen=True, slots=True)
class _PendingChainDamage:
    """属性伤害传导的统一确定性挂起结构。

    原始横置角色实际受到大于0点火／雷属性伤害后建立；每名候选在真正
    轮到时动态检查存活与横置状态，并按根基数继承原始来源、实体牌与
    伤害属性。濒死救援期间保持挂起，救援结束后从准确索引恢复；胜利
    成立时确定性清理全部未开始目标。
    """

    root_damage_event_id: str
    root_damage_source_id: str | None
    root_card_instance_id: str
    root_card_key: str
    root_card_user: str
    damage_type: str
    chain_base_damage: int
    original_target_id: str
    processed_target_ids: tuple[str, ...] = ()
    candidate_order: tuple[str, ...] = ()
    current_index: int = 0
    current_target_id: str | None = None
    pause_reason: str | None = None
    parent: "_PendingChainDamage | None" = None
    session_id: str = ""


@dataclass(frozen=True, slots=True)
class _PendingWeaponChoice:
    """CP-04P 武器触发选择窗口挂起状态（当前用于麒麟弓弃坐骑）。

    麒麟弓时序（USER_CONFIRMED_MOBILE_RULE＋IN_GAME_CARD_TEXT_CONFIRMED，
    2026-08-08 用户移动版卡面文本与牌局记录确认）：本次【杀】确定将造成
    伤害（防具解析后 final_amount>0）→ 麒麟弓触发窗口（弃坐骑／放弃）→
    坐骑正式离开装备区并完成对应牌移动/事件 → 然后本次伤害正式结算、
    HP 扣减／DAMAGE event → HP<=0 再进入 dying/rescue → 后续正式结算。
    因此窗口在 HP 扣减与 DAMAGE event 之前打开，挂起参数用于窗口关闭后
    执行真正的伤害结算。"""

    weapon_key: str
    kind: str
    attacker_id: str
    target_id: str
    slash_instance_id: str
    damage_event_id: str | None
    window_id: str
    # 窗口关闭后执行真正伤害结算所需的原始参数（HP扣减+DAMAGE+濒死/传导/根牌）
    damage_amount: int
    damage_type: str
    card_key: str
    card_user: str | None
    source_id: str | None
    kill_credit: str | None
    resolved_reason: str
    death_reason: str
    rescue_reason: str
    defer_root_finish: bool
    declared_amount: int = 0
    modifiers: tuple[str, ...] = ()
    armor_ignored: bool = False
    extra_payload: Mapping[str, object] = MappingProxyType({})


@dataclass(frozen=True, slots=True)
class _PendingSlashChoice:
    """CP-04P 被闪后/伤害前武器选择窗口（贯石斧强制命中、寒冰剑防止伤害）。"""

    weapon_key: str
    kind: str  # guanshifu_force_hit | hanbing_prevent
    attacker_id: str
    target_id: str
    window_id: str
    pending_slash: _PendingSlash
    # 青龙偃月刀继续使用【杀】的隐藏手牌句柄快照（仅 kind=qinglong_continue）
    handles: Mapping[str, str] = MappingProxyType({})
    snapshot_digest: str | None = None


@dataclass(frozen=True, slots=True)
class _PendingDiscardTwo:
    """CP-04P 弃2张窗口（贯石斧弃自己手牌+装备、寒冰剑弃目标手牌+装备）。"""

    chooser_id: str
    cards_owner_id: str
    source_kind: str  # guanshifu_force_hit（寒冰剑改用独立逐张弃置状态机）
    window_id: str
    selected_ids: tuple[str, ...] = ()
    selected_zones: Mapping[str, str] = MappingProxyType({})
    handles: Mapping[str, str] = MappingProxyType({})
    snapshot_digest: str | None = None
    # 贯石斧自身不能作为发动代价（USER_CONFIRMED_MOBILE_RULE，2026-08-08
    # 用户移动版实测确认）：窗口打开时记录当前提供技能的贯石斧实体，
    # 枚举、选择与提交三个层面对其一致排除。
    excluded_instance_id: str | None = None


@dataclass(frozen=True, slots=True)
class _PendingHanbingDiscard:
    """CP-04P 寒冰剑逐张弃置状态（2026-08-08 用户移动版实测确认）。

    寒冰剑“弃置目标2张牌”是一张一张顺序弃置：防止伤害后进入第一次
    弃牌选择，选择并正式弃置第1张牌；第1张离区及其状态变化（含装备
    离区钩子）完成后，根据此刻最新权威状态重新枚举第2张可弃牌，再
    选择并正式弃置第2张。两次弃置是两个连续的正式弃置步骤，各自独立
    enumerate→validate→apply，第二次选择不得使用第一次弃置前的旧
    zone快照；与贯石斧“一次选择两张→一次批量弃置代价”不是同一种
    正式结算状态机。"""

    attacker_id: str
    target_id: str
    window_id: str
    step: int  # 1 或 2
    handles: Mapping[str, str] = MappingProxyType({})
    snapshot_digest: str | None = None


@dataclass(frozen=True, slots=True)
class _BatchRuntime:
    current_player_id: str
    turn_number: int = 1
    phase: ProductionPhase = ProductionPhase.PREPARE
    slash_used_counts: Mapping[str, int] = MappingProxyType({})
    judgment_entry_indices: Mapping[str, int] = MappingProxyType({})
    judgment_entry_counter: int = 0
    processed_judgment_instance_ids: tuple[str, ...] = ()
    pending_judgment: _PendingJudgment | None = None
    skipped_phases: Mapping[str, str] = MappingProxyType({})
    phase_skip_reasons: Mapping[str, str] = MappingProxyType({})
    defer_damage_card_finish: bool = False
    # CP-04P 贯石斧：强制命中时【杀】本体已因【闪】完成结算进入弃牌堆，
    # 伤害管线不再重复 finish；该标记在结算收尾路径统一跳过。
    damage_card_already_finished: bool = False
    wine_buff_owner_id: str | None = None
    wine_buff_used_this_play_phase: bool = False
    pending_slash: _PendingSlash | None = None
    pending_trick: _PendingTrick | None = None
    trick_effect_active: bool = False
    trick_consecutive_passes: int = 0
    trick_response_order: tuple[str, ...] = ()
    trick_response_index: int = 0
    trick_decision_count: int = 0
    trick_direct_response_to: str | None = None
    pending_dying_id: str | None = None
    rescue_order: tuple[str, ...] = ()
    rescue_index: int = 0
    rescue_decision_count: int = 0
    response_window_id: str | None = None
    response_window_order: tuple[str, ...] = ()
    response_window_source_sequence: int | None = None
    pending_zone_choice: _PendingZoneChoice | None = None
    zone_choice_handles: Mapping[str, str] = MappingProxyType({})
    zone_choice_snapshot_digest: str | None = None
    pending_duel: _PendingDuel | None = None
    pending_fire_attack: _PendingFireAttack | None = None
    fire_attack_reveal_handles: Mapping[str, str] = MappingProxyType({})
    pending_group_trick: _PendingGroupTrick | None = None
    group_response_handles: Mapping[str, str] = MappingProxyType({})
    group_response_snapshot_digest: str | None = None
    pending_wugu: _PendingWugu | None = None
    pending_borrowed_sword: _PendingBorrowedSword | None = None
    borrowed_sword_slash_handles: Mapping[str, str] = MappingProxyType({})
    borrowed_sword_slash_snapshot_digest: str | None = None
    pending_damage_card_id: str | None = None
    pending_damage_source_id: str | None = None
    pending_damage_kill_credit: str | None = None
    pending_damage_rescue_reason: str | None = None
    pending_damage_death_reason: str | None = None
    pending_chain: _PendingChainDamage | None = None
    winner_id: str | None = None
    bagua_attempted: bool = False
    # CP-04O 批量弃牌：选择窗口只累积待选集合，最终确认前不移动任何牌
    discard_phase_window_id: str | None = None
    discard_phase_selected_ids: tuple[str, ...] = ()
    discard_phase_handles: Mapping[str, str] = MappingProxyType({})
    discard_phase_snapshot_digest: str | None = None
    pending_weapon_choice: _PendingWeaponChoice | None = None
    pending_slash_choice: _PendingSlashChoice | None = None
    pending_discard_two: _PendingDiscardTwo | None = None
    pending_hanbing_discard: _PendingHanbingDiscard | None = None

    def audit_value(self) -> dict[str, object]:
        pending = None
        if self.pending_slash is not None:
            pending = {
                "attacker_id": self.pending_slash.attacker_id,
                "target_id": self.pending_slash.target_id,
                "slash_instance_id": self.pending_slash.slash_instance_id,
                "boosted": self.pending_slash.boosted,
            }
        pending_trick = None
        if self.pending_trick is not None:
            pending_trick = {
                "user_id": self.pending_trick.user_id,
                "target_id": self.pending_trick.target_id,
                "trick_instance_id": self.pending_trick.trick_instance_id,
                "trick_key": self.pending_trick.trick_key,
            }
        pending_zone_choice = None
        if self.pending_zone_choice is not None:
            pending_zone_choice = {
                "user_id": self.pending_zone_choice.user_id,
                "target_id": self.pending_zone_choice.target_id,
                "trick_instance_id": (
                    self.pending_zone_choice.trick_instance_id
                ),
                "trick_key": self.pending_zone_choice.trick_key,
                "window_id": self.pending_zone_choice.window_id,
                "zones": list(self.pending_zone_choice.zones),
            }
        pending_group_trick = None
        if self.pending_group_trick is not None:
            group = self.pending_group_trick
            pending_group_trick = {
                "user_id": group.user_id,
                "trick_instance_id": group.trick_instance_id,
                "trick_key": group.trick_key,
                "target_sequence": list(group.target_sequence),
                "current_target_index": group.current_target_index,
                "completed_target_ids": list(group.completed_target_ids),
                "responder_id": group.responder_id,
            }
        pending_wugu = None
        if self.pending_wugu is not None:
            wugu = self.pending_wugu
            pending_wugu = {
                "user_id": wugu.user_id,
                "trick_instance_id": wugu.trick_instance_id,
                "trick_key": wugu.trick_key,
                "pool": list(wugu.pool),
                "pool_digest": wugu.pool_digest,
                "target_sequence": list(wugu.target_sequence),
                "current_target_index": wugu.current_target_index,
                "completed_target_ids": list(wugu.completed_target_ids),
                "window_id": wugu.window_id,
            }
        return {
            "current_player_id": self.current_player_id,
            "turn_number": self.turn_number,
            "phase": self.phase.value,
            "slash_used_counts": dict(self.slash_used_counts),
            "judgment_entry_indices": dict(self.judgment_entry_indices),
            "judgment_entry_counter": self.judgment_entry_counter,
            "processed_judgment_instance_ids": list(
                self.processed_judgment_instance_ids
            ),
            "pending_judgment": self._pending_judgment_value(),
            "skipped_phases": dict(self.skipped_phases),
            "phase_skip_reasons": dict(self.phase_skip_reasons),
            "defer_damage_card_finish": self.defer_damage_card_finish,
            "wine_buff_owner_id": self.wine_buff_owner_id,
            "wine_buff_used_this_play_phase": self.wine_buff_used_this_play_phase,
            "pending_slash": pending,
            "pending_trick": pending_trick,
            "trick_effect_active": self.trick_effect_active,
            "trick_consecutive_passes": self.trick_consecutive_passes,
            "trick_response_order": list(self.trick_response_order),
            "trick_response_index": self.trick_response_index,
            "trick_decision_count": self.trick_decision_count,
            "trick_direct_response_to": self.trick_direct_response_to,
            "pending_dying_id": self.pending_dying_id,
            "rescue_order": list(self.rescue_order),
            "rescue_index": self.rescue_index,
            "rescue_decision_count": self.rescue_decision_count,
            "response_window_id": self.response_window_id,
            "response_window_order": list(self.response_window_order),
            "response_window_source_sequence": self.response_window_source_sequence,
            "pending_zone_choice": pending_zone_choice,
            "zone_choice_handles": dict(self.zone_choice_handles),
            "zone_choice_snapshot_digest": self.zone_choice_snapshot_digest,
            "pending_duel": self._pending_duel_value(),
            "pending_fire_attack": self._pending_fire_attack_value(),
            "fire_attack_reveal_handles": dict(self.fire_attack_reveal_handles),
            "pending_group_trick": pending_group_trick,
            "group_response_handles": dict(self.group_response_handles),
            "group_response_snapshot_digest": (
                self.group_response_snapshot_digest
            ),
            "pending_wugu": pending_wugu,
            "pending_damage_card_id": self.pending_damage_card_id,
            "pending_damage_source_id": self.pending_damage_source_id,
            "pending_damage_kill_credit": self.pending_damage_kill_credit,
            "pending_damage_rescue_reason": self.pending_damage_rescue_reason,
            "pending_damage_death_reason": self.pending_damage_death_reason,
            "pending_chain": self._pending_chain_value(self.pending_chain),
            "pending_borrowed_sword": self._pending_borrowed_sword_value(),
            "borrowed_sword_slash_handles": dict(
                self.borrowed_sword_slash_handles
            ),
            "borrowed_sword_slash_snapshot_digest": (
                self.borrowed_sword_slash_snapshot_digest
            ),
            "winner_id": self.winner_id,
            "bagua_attempted": self.bagua_attempted,
            "discard_phase_window_id": self.discard_phase_window_id,
            "discard_phase_selected_ids": list(
                self.discard_phase_selected_ids
            ),
            "discard_phase_handles": dict(self.discard_phase_handles),
            "discard_phase_snapshot_digest": (
                self.discard_phase_snapshot_digest
            ),
            "pending_weapon_choice": (
                None
                if self.pending_weapon_choice is None
                else {
                    "weapon_key": self.pending_weapon_choice.weapon_key,
                    "kind": self.pending_weapon_choice.kind,
                    "attacker_id": self.pending_weapon_choice.attacker_id,
                    "target_id": self.pending_weapon_choice.target_id,
                    "slash_instance_id": (
                        self.pending_weapon_choice.slash_instance_id
                    ),
                    "damage_event_id": (
                        self.pending_weapon_choice.damage_event_id
                    ),
                    "window_id": self.pending_weapon_choice.window_id,
                }
            ),
        }

    def _pending_borrowed_sword_value(
        self
    ) -> dict[str, object] | None:
        pending = self.pending_borrowed_sword
        if pending is None:
            return None
        return {
            "user_id": pending.user_id,
            "trick_instance_id": pending.trick_instance_id,
            "first_target_id": pending.first_target_id,
            "second_target_id": pending.second_target_id,
            "effect_active": pending.effect_active,
            "stage": pending.stage,
            "weapon_instance_id": pending.weapon_instance_id,
            "slash_choice_snapshot_digest": (
                pending.slash_choice_snapshot_digest
            ),
            "chosen_slash_instance_id": pending.chosen_slash_instance_id,
            "decision": pending.decision,
            "session_id": pending.session_id,
            "requirement_fulfilled": pending.requirement_fulfilled,
            "game_over_cleanup": pending.game_over_cleanup,
            "root_discarded": pending.root_discarded,
        }

    def _pending_judgment_value(self) -> dict[str, object] | None:
        pending = self.pending_judgment
        if pending is None:
            return None
        return {
            "trick_instance_id": pending.trick_instance_id,
            "trick_key": pending.trick_key,
            "target_id": pending.target_id,
            "stage": pending.stage,
            "entry_index": pending.entry_index,
            "wuxie_nullified": pending.wuxie_nullified,
            "cleanup_done": pending.cleanup_done,
        }

    def _pending_duel_value(self) -> dict[str, object] | None:
        if self.pending_duel is None:
            return None
        duel = self.pending_duel
        return {
            "user_id": duel.user_id,
            "target_id": duel.target_id,
            "trick_instance_id": duel.trick_instance_id,
            "responder_id": duel.responder_id,
            "opponent_id": duel.opponent_id,
            "round_index": duel.round_index,
            "response_index": duel.response_index,
            "slash_sequence": list(duel.slash_sequence),
        }

    def _pending_fire_attack_value(self) -> dict[str, object] | None:
        if self.pending_fire_attack is None:
            return None
        fire = self.pending_fire_attack
        return {
            "user_id": fire.user_id,
            "target_id": fire.target_id,
            "trick_instance_id": fire.trick_instance_id,
            "reveal_window_id": fire.reveal_window_id,
            "revealed_instance_id": fire.revealed_instance_id,
            "revealed_suit": fire.revealed_suit,
        }

    @staticmethod
    def _pending_chain_value(
        chain: "_PendingChainDamage | None", depth: int = 0
    ) -> dict[str, object] | None:
        if chain is None:
            return None
        if depth > 8:
            raise ProductionBatchError("传导挂起上下文嵌套超过安全上限")
        parent = None
        if chain.parent is not None:
            parent = _BatchRuntime._pending_chain_value(chain.parent, depth + 1)
        return {
            "root_damage_event_id": chain.root_damage_event_id,
            "root_damage_source_id": chain.root_damage_source_id,
            "root_card_instance_id": chain.root_card_instance_id,
            "root_card_key": chain.root_card_key,
            "root_card_user": chain.root_card_user,
            "damage_type": chain.damage_type,
            "chain_base_damage": chain.chain_base_damage,
            "original_target_id": chain.original_target_id,
            "processed_target_ids": list(chain.processed_target_ids),
            "candidate_order": list(chain.candidate_order),
            "current_index": chain.current_index,
            "current_target_id": chain.current_target_id,
            "pause_reason": chain.pause_reason,
            "parent": parent,
            "session_id": chain.session_id,
        }


def _zone_payload(zone: ZoneRef) -> dict[str, object]:
    return {
        "kind": zone.kind.value,
        "owner_id": zone.owner_id,
        "equipment_slot": zone.equipment_slot,
        "special_zone": zone.special_zone,
    }


def _card_key(state: GameState, instance_id: str) -> str:
    return state.cards_by_id[instance_id].card_key


ZHANGBA_MATERIAL_HANDLE_PREFIX = "zb_"
ZHANGBA_MATERIAL_HANDLE_HEX_CHARS = 32


def _zhangba_material_message(
    session_id: str,
    window_id: str,
    actor_id: str,
    snapshot_digest: str,
    material_ids: tuple[str, str],
) -> str:
    """构造丈八蛇矛材料对句柄的HMAC消息。

    消息绑定会话标识、选择窗口、材料所属角色、当前手牌快照摘要与两张
    材料实体；保密性完全来自会话级随机秘密。动作负载只携带句柄，不携带
    材料实体ID，避免在使用前泄露隐藏手牌。"""

    return canonical_json(
        {
            "session_id": session_id,
            "zhangba_material_window": window_id,
            "actor_id": actor_id,
            "hand_snapshot_sha256": snapshot_digest,
            "material_a": material_ids[0],
            "material_b": material_ids[1],
            "execution_context": "production_basic_cards_batch:zhangba_material",
        }
    )


def _zhangba_material_handle(
    session_id: str,
    session_secret: bytes,
    window_id: str,
    actor_id: str,
    snapshot_digest: str,
    material_ids: tuple[str, str],
) -> str:
    """生成绑定当前丈八材料对的不透明句柄。"""

    # UNREACHABLE while zhangba PARTIAL/fail-closed（VIRTUAL_CARD_SUBCARD_
    # LIFECYCLE_RULE_GAP）：仅由丈八虚拟杀枚举/apply路径调用，丈八门禁
    # 失败关闭后不可达；不得被其他路径当作已证明正式生产能力使用。

    digest = hmac.new(
        session_secret,
        _zhangba_material_message(
            session_id,
            window_id,
            actor_id,
            snapshot_digest,
            material_ids,
        ).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return ZHANGBA_MATERIAL_HANDLE_PREFIX + digest[:ZHANGBA_MATERIAL_HANDLE_HEX_CHARS]


def _resolve_zhangba_material_handle(
    session_id: str,
    session_secret: bytes,
    state: GameState,
    window_id: str,
    actor_id: str,
    snapshot_digest: str | None,
    snapshot_handles: Mapping[str, tuple[str, str]],
    handle: object,
) -> tuple[str, str] | None:
    """把丈八材料句柄解析为窗口快照中的真实材料对；任何绑定不符返回None。"""

    # UNREACHABLE while zhangba PARTIAL/fail-closed：旧快照解析实现，
    # 当前无调用点（apply 使用 direct 重算版本），待丈八恢复时清理或复用。

    if snapshot_digest is None or not isinstance(handle, str):
        return None
    material_ids = snapshot_handles.get(handle)
    if material_ids is None:
        return None
    expected = _zhangba_material_handle(
        session_id,
        session_secret,
        window_id,
        actor_id,
        snapshot_digest,
        material_ids,
    )
    if not hmac.compare_digest(expected, handle):
        return None
    for instance_id in material_ids:
        if state.location_of(instance_id) != ZoneRef.hand(actor_id):
            return None
    current_digest = sha256_value(
        tuple(state.card_ids_in(ZoneRef.hand(actor_id)))
    )
    if not hmac.compare_digest(current_digest, snapshot_digest):
        return None
    return material_ids


def _resolve_zhangba_handle_direct(
    session_id: str,
    session_secret: bytes,
    state: GameState,
    window_id: str,
    actor_id: str,
    handle: object,
) -> tuple[str, str] | None:
    """把丈八材料句柄与当前权威手牌逐对重算比对（服务端direct解析）。

    枚举不修改运行时（合法动作枚举必须无副作用），因此 apply 时直接对
    当前手牌的全部两两组合重算HMAC句柄并比对提交句柄；句柄绑定当前
    手牌摘要，任何手牌变化都会使旧句柄失效。"""

    # UNREACHABLE while zhangba PARTIAL/fail-closed：仅由丈八虚拟杀
    # apply 路径调用。

    if not isinstance(handle, str):
        return None
    hand_ids = tuple(state.card_ids_in(ZoneRef.hand(actor_id)))
    snapshot_digest = sha256_value(hand_ids)
    for index, first in enumerate(hand_ids):
        for second in hand_ids[index + 1 :]:
            material_ids = (first, second)
            expected = _zhangba_material_handle(
                session_id,
                session_secret,
                window_id,
                actor_id,
                snapshot_digest,
                material_ids,
            )
            if hmac.compare_digest(expected, handle):
                return material_ids
    return None


def _zhangba_virtual_card(
    state: GameState,
    instance_id: str,
    material_ids: tuple[str, ...],
) -> CardInstance:
    """返回丈八虚拟【杀】的规则身份对象。

    虚拟杀不是新的实体卡牌：不进入 state.cards / zones，牌守恒继续针对
    实体牌成立。颜色按 Knowledge 7.8：两张材料均为红色→红、均为黑色→黑、
    一红一黑→无色；转化出的【杀】没有花色和点数。"""

    # UNREACHABLE while zhangba PARTIAL/fail-closed：仅由丈八虚拟杀路径调用。

    if len(material_ids) != 2:
        raise ProductionBatchError("丈八虚拟杀必须恰好由两张材料组成")
    colors = tuple(
        state.cards_by_id[instance].color
        for instance in material_ids
    )
    if colors[0] == colors[1] == "红":
        color = "红"
    elif colors[0] == colors[1] == "黑":
        color = "黑"
    else:
        color = "无"
    return CardInstance(
        instance_id=instance_id,
        deck_id="virtual",
        card_key="sgs_basic_sha",
        card_name="杀",
        card_type="基本牌",
        suit="无",
        color=color,
        rank="无",
        card_variant="zhangba_virtual",
    )


def _virtual_slash_card(
    state: GameState, runtime: "_BatchRuntime", instance_id: str
) -> CardInstance | None:
    """返回当前挂起虚拟【杀】（丈八蛇矛）的规则身份对象；非虚拟返回None。"""

    # UNREACHABLE while zhangba PARTIAL/fail-closed：_slash_card 的虚拟
    # 分支仅在 pending_slash.virtual=True 时可达，丈八门禁关闭后不可达；
    # 实体牌路径直接查 state.cards_by_id，行为与撤回前完全一致。

    pending = runtime.pending_slash
    if (
        pending is None
        or not pending.virtual
        or pending.slash_instance_id != instance_id
    ):
        return None
    return _zhangba_virtual_card(state, instance_id, pending.material_ids)


ZONE_CHOICE_TRICK_KEYS: tuple[str, ...] = (
    "sgs_trick_guohechaiqiao",
    "sgs_trick_shunshouqianyang",
)


def _zone_id(zone: ZoneRef) -> str:
    """选牌区域标识：hand / judgment / equipment:<槽位>。"""

    if zone.kind is ZoneKind.HAND:
        return "hand"
    if zone.kind is ZoneKind.JUDGMENT:
        return "judgment"
    if zone.kind is ZoneKind.EQUIPMENT:
        if zone.equipment_slot is None:
            raise ProductionBatchError("装备区缺少槽位标识，无法生成区域标识")
        return f"equipment:{zone.equipment_slot}"
    raise ProductionBatchError(
        f"不支持的选牌目标区域：{zone.kind.value!r}"
    )


def _zone_from_id(zone_id: object, owner_id: str) -> ZoneRef:
    """把选牌区域标识解析回权威牌区引用。"""

    if not isinstance(zone_id, str):
        raise InvalidActionError("选牌区域标识必须是字符串")
    if zone_id == "hand":
        return ZoneRef.hand(owner_id)
    if zone_id == "judgment":
        return ZoneRef.judgment(owner_id)
    if zone_id.startswith("equipment:"):
        slot = zone_id.split(":", 1)[1]
        return ZoneRef.equipment(owner_id, slot)
    raise InvalidActionError(f"无法识别的选牌区域标识：{zone_id!r}")


HAND_CHOICE_HANDLE_PREFIX = "h_"
HAND_CHOICE_HANDLE_HEX_CHARS = 32


def _hand_choice_message(
    session_id: str,
    window_id: str,
    target_id: str,
    zone: str,
    snapshot_digest: str,
    instance_id: str,
) -> str:
    """构造隐藏手牌选择句柄的HMAC消息。

    消息由会话标识、选择窗口ID、目标角色、区域、当前手牌快照摘要与实体牌ID
    组成；其中除会话标识外全部可以在公开回放或对局中被观测，因此消息本身
    不提供保密性，保密性完全来自会话级随机秘密。
    """

    return canonical_json(
        {
            "session_id": session_id,
            "zone_choice_window": window_id,
            "target_id": target_id,
            "zone": zone,
            "hand_snapshot_sha256": snapshot_digest,
            "instance_id": instance_id,
        }
    )


def _hand_choice_handle(
    session_id: str,
    session_secret: bytes,
    window_id: str,
    target_id: str,
    zone: str,
    snapshot_digest: str,
    instance_id: str,
) -> str:
    """生成绑定当前会话与选择窗口的隐藏手牌选择句柄。

    句柄是 HMAC-SHA256（会话级256位随机秘密，消息含会话标识＋窗口ID＋目标＋
    区域＋当前手牌快照摘要＋实体牌ID）的前128位；会话秘密由
    ``secrets.token_bytes(32)`` 创建，只保存在服务端会话与权威回放私有材料中，
    公开窗口ID、正式牌堆160个实体ID、正式CSV牌面与公开seed均不足以重建句柄。
    """

    digest = hmac.new(
        session_secret,
        _hand_choice_message(
            session_id, window_id, target_id, zone, snapshot_digest, instance_id
        ).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return HAND_CHOICE_HANDLE_PREFIX + digest[:HAND_CHOICE_HANDLE_HEX_CHARS]


def _resolve_hand_choice_handle(
    session_id: str,
    session_secret: bytes,
    state: GameState,
    window_id: str,
    target_id: str,
    zone: str,
    snapshot_digest: str | None,
    snapshot_handles: Mapping[str, str],
    handle: object,
) -> str | None:
    """把隐藏手牌句柄解析为窗口快照中的真实实体；任何绑定不符都返回None。

    校验顺序：
    1. 句柄必须存在于当前窗口打开时的服务端快照映射（跨窗口、跨会话、伪造
       句柄在此失败关闭）；
    2. 句柄必须与HMAC-SHA256重算值一致（防伪造与防密钥被替换）；
    3. 实体必须仍在目标手牌中；
    4. 当前手牌摘要必须仍等于窗口打开时的快照摘要（手牌变化后旧句柄失败关闭）。
    """

    if zone != "hand" or not isinstance(handle, str):
        return None
    if snapshot_digest is None:
        return None
    instance_id = snapshot_handles.get(handle)
    if instance_id is None:
        return None
    expected = _hand_choice_handle(
        session_id,
        session_secret,
        window_id,
        target_id,
        zone,
        snapshot_digest,
        instance_id,
    )
    if not hmac.compare_digest(expected, handle):
        return None
    if state.location_of(instance_id) != ZoneRef.hand(target_id):
        return None
    current_digest = sha256_value(
        tuple(state.card_ids_in(ZoneRef.hand(target_id)))
    )
    if not hmac.compare_digest(current_digest, snapshot_digest):
        return None
    return instance_id


GROUP_RESPONSE_HANDLE_PREFIX = "gr_"
GROUP_RESPONSE_HANDLE_HEX_CHARS = 32


def _group_response_handle_message(
    session_id: str,
    window_id: str,
    target_id: str,
    snapshot_digest: str,
    instance_id: str,
) -> str:
    """构造群体锦囊响应句柄的HMAC消息。

    消息由会话标识、响应窗口ID、当前目标角色、手牌快照摘要与实体牌ID
    组成；保密性完全来自会话级随机秘密，与隐藏手牌选择句柄同一机制。
    """

    return canonical_json(
        {
            "session_id": session_id,
            "group_response_window": window_id,
            "target_id": target_id,
            "hand_snapshot_sha256": snapshot_digest,
            "instance_id": instance_id,
        }
    )


def _group_response_handle(
    session_id: str,
    session_secret: bytes,
    window_id: str,
    target_id: str,
    snapshot_digest: str,
    instance_id: str,
) -> str:
    """生成仅对当前群体锦囊响应窗口有效的不透明句柄。

    句柄是 HMAC-SHA256（会话级256位随机秘密）前128位；决策输入不携带
    实体牌ID、牌名、花色或点数，玩家可见回放不能据此还原未打出的手牌。
    """

    digest = hmac.new(
        session_secret,
        _group_response_handle_message(
            session_id, window_id, target_id, snapshot_digest, instance_id
        ).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return GROUP_RESPONSE_HANDLE_PREFIX + digest[:GROUP_RESPONSE_HANDLE_HEX_CHARS]


def _resolve_group_response_handle(
    session_id: str,
    session_secret: bytes,
    state: GameState,
    window_id: str,
    target_id: str,
    snapshot_digest: str | None,
    snapshot_handles: Mapping[str, str],
    handle: object,
) -> str | None:
    """把群体响应句柄解析为窗口快照中的真实实体；任何绑定不符都返回None。

    校验顺序：句柄必须存在于窗口打开时的服务端快照映射；句柄必须与
    HMAC-SHA256重算值一致；实体必须仍在目标手牌中；当前手牌摘要必须
    仍等于窗口打开时的快照摘要。
    """

    if not isinstance(handle, str):
        return None
    if snapshot_digest is None:
        return None
    instance_id = snapshot_handles.get(handle)
    if instance_id is None:
        return None
    expected = _group_response_handle(
        session_id,
        session_secret,
        window_id,
        target_id,
        snapshot_digest,
        instance_id,
    )
    if not hmac.compare_digest(expected, handle):
        return None
    if state.location_of(instance_id) != ZoneRef.hand(target_id):
        return None
    current_digest = sha256_value(
        tuple(state.card_ids_in(ZoneRef.hand(target_id)))
    )
    if not hmac.compare_digest(current_digest, snapshot_digest):
        return None
    return instance_id


def _zone_choice_handle_snapshot(
    session_id: str,
    session_secret: bytes,
    state: GameState,
    target_id: str,
    window_id: str,
    snapshot_digest: str,
) -> Mapping[str, str]:
    """为当前选择窗口生成目标手牌的隐藏句柄快照（服务端私有映射）。

    该映射只保存在会话运行时与权威执行快照中，不进入玩家决策上下文、普通
    合法动作负载或玩家可见回放导出。
    """

    return MappingProxyType(
        {
            _hand_choice_handle(
                session_id,
                session_secret,
                window_id,
                target_id,
                "hand",
                snapshot_digest,
                instance_id,
            ): instance_id
            for instance_id in state.card_ids_in(ZoneRef.hand(target_id))
        }
    )


def _fire_reveal_handle(
    session_id: str,
    session_secret: bytes,
    window_id: str,
    instance_id: str,
) -> str:
    """生成仅对当前【火攻】展示窗口有效的不透明选择句柄。

    句柄是 HMAC-SHA256（会话级256位随机秘密，消息含会话标识＋展示窗口ID＋
    目标角色＋区域＋实体牌ID）的前128位；会话秘密只保存在服务端会话与权威
    回放私有材料中，公开窗口ID、正式牌堆160个实体ID、正式CSV牌面与公开seed
    均不足以离线枚举重建句柄。决策输入不携带实体牌ID、牌名、花色或点数，
    无法从句柄反推出牌面。句柄只绑定当前窗口与目标手牌，目标手牌变化后
    旧句柄不能解析到任何真实实体。
    """

    digest = hmac.new(
        session_secret,
        canonical_json(
            {
                "session_id": session_id,
                "fire_attack_reveal_window": window_id,
                "target_id": "hand_target",
                "zone": "hand",
                "instance_id": instance_id,
            }
        ).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return "h_" + digest[:32]


def _fire_reveal_handle_snapshot(
    session_id: str,
    session_secret: bytes,
    state: GameState,
    target_id: str,
    window_id: str,
) -> Mapping[str, str]:
    """为当前展示窗口生成目标手牌的不透明句柄快照（句柄到实体ID映射）。

    该映射只保存在会话运行时与权威执行快照中，不进入玩家决策上下文、
    普通合法动作负载或玩家可见回放导出。
    """

    return MappingProxyType(
        {
            _fire_reveal_handle(
                session_id, session_secret, window_id, instance_id
            ): instance_id
            for instance_id in state.card_ids_in(ZoneRef.hand(target_id))
        }
    )


def _resolve_fire_reveal_handle(
    session_id: str,
    session_secret: bytes,
    state: GameState,
    window_id: str,
    target_id: str,
    handle: object,
) -> str | None:
    """把展示句柄解析为目标当前手牌中的真实实体；无法解析时返回None。

    校验顺序：
    1. 句柄必须是字符串；
    2. 句柄必须与HMAC-SHA256重算值一致（防伪造、防离线枚举）；
    3. 实体必须仍在目标手牌中。
    """

    if not isinstance(handle, str):
        return None
    for instance_id in state.card_ids_in(ZoneRef.hand(target_id)):
        if (
            _fire_reveal_handle(
                session_id, session_secret, window_id, instance_id
            )
            == handle
        ):
            return instance_id
    return None


BORROWED_SWORD_HANDLE_PREFIX = "bs_"
BORROWED_SWORD_HANDLE_HEX_CHARS = 32


def _borrowed_sword_slash_message(
    session_id: str,
    window_id: str,
    first_target_id: str,
    second_target_id: str,
    snapshot_digest: str,
    instance_id: str,
    card_key: str,
    stage: str,
) -> str:
    """构造借刀【杀】选择句柄的HMAC消息。

    消息绑定会话标识、选择窗口、第一目标、第二目标、手牌快照摘要、
    杀实体ID、卡牌键与当前阶段；保密性完全来自会话级随机秘密，消息
    中的公开字段本身不提供保密性。
    """

    return canonical_json(
        {
            "session_id": session_id,
            "borrowed_sword_slash_window": window_id,
            "first_target_id": first_target_id,
            "second_target_id": second_target_id,
            "hand_snapshot_sha256": snapshot_digest,
            "slash_instance_id": instance_id,
            "card_key": card_key,
            "stage": stage,
            "execution_context": "production_basic_cards_batch:borrowed_sword_choice",
        }
    )


def _borrowed_sword_slash_handle(
    session_id: str,
    session_secret: bytes,
    window_id: str,
    first_target_id: str,
    second_target_id: str,
    snapshot_digest: str,
    instance_id: str,
    card_key: str,
    stage: str,
) -> str:
    """生成绑定当前借刀选择窗口的不透明【杀】选择句柄。"""

    digest = hmac.new(
        session_secret,
        _borrowed_sword_slash_message(
            session_id,
            window_id,
            first_target_id,
            second_target_id,
            snapshot_digest,
            instance_id,
            card_key,
            stage,
        ).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return (
        BORROWED_SWORD_HANDLE_PREFIX
        + digest[:BORROWED_SWORD_HANDLE_HEX_CHARS]
    )


def _borrowed_sword_slash_snapshot(
    session_id: str,
    session_secret: bytes,
    state: GameState,
    first_target_id: str,
    second_target_id: str,
    window_id: str,
    stage: str,
) -> tuple[Mapping[str, str], str]:
    """生成当前选择窗口的句柄快照与手牌摘要。

    只把第一目标手牌中的实体普通／火／雷【杀】纳入候选；映射只保存在
    会话运行时与权威执行快照中，不进入玩家决策上下文、普通合法动作
    负载或玩家可见回放导出。
    """

    hand_ids = tuple(state.card_ids_in(ZoneRef.hand(first_target_id)))
    snapshot_digest = sha256_value(hand_ids)
    snapshot: dict[str, str] = {}
    for instance_id in hand_ids:
        card_key = state.cards_by_id[instance_id].card_key
        if card_key not in SLASH_CARD_KEYS:
            continue
        snapshot[
            _borrowed_sword_slash_handle(
                session_id,
                session_secret,
                window_id,
                first_target_id,
                second_target_id,
                snapshot_digest,
                instance_id,
                card_key,
                stage,
            )
        ] = instance_id
    return MappingProxyType(snapshot), snapshot_digest


def _resolve_borrowed_sword_slash_handle(
    session_id: str,
    session_secret: bytes,
    state: GameState,
    first_target_id: str,
    second_target_id: str,
    window_id: str,
    snapshot_digest: str | None,
    snapshot_handles: Mapping[str, str],
    handle: object,
    stage: str,
) -> str | None:
    """把借刀【杀】选择句柄解析为真实实体；任何绑定不符都返回None。"""

    if snapshot_digest is None or not isinstance(handle, str):
        return None
    instance_id = snapshot_handles.get(handle)
    if instance_id is None:
        return None
    card_key = state.cards_by_id[instance_id].card_key
    expected = _borrowed_sword_slash_handle(
        session_id,
        session_secret,
        window_id,
        first_target_id,
        second_target_id,
        snapshot_digest,
        instance_id,
        card_key,
        stage,
    )
    if not hmac.compare_digest(expected, handle):
        return None
    if state.location_of(instance_id) != ZoneRef.hand(first_target_id):
        return None
    current_digest = sha256_value(
        tuple(state.card_ids_in(ZoneRef.hand(first_target_id)))
    )
    if not hmac.compare_digest(current_digest, snapshot_digest):
        return None
    return instance_id


def _replace_player(
    state: GameState,
    player_id: str,
    *,
    hp: int | None = None,
    alive: bool | None = None,
    chained: bool | None = None,
) -> GameState:
    """只由批处理会话调用的不可变玩家状态事务。"""

    players: list[PlayerState] = []
    found = False
    for player in state.players:
        if player.player_id != player_id:
            players.append(player)
            continue
        found = True
        players.append(
            replace(
                player,
                hp=player.hp if hp is None else hp,
                alive=player.alive if alive is None else alive,
                chained=player.chained if chained is None else chained,
            )
        )
    if not found:
        raise ProductionBatchError(f"找不到玩家{player_id!r}")
    return replace(state, players=tuple(players), revision=state.revision + 1)


def _assert_deck_available(
    state: GameState, count: int, label: str
) -> None:
    """统一牌量可用性预检：牌堆与可重洗弃牌堆合计不足即失败关闭。

    必须在任何事件、状态、RNG 或运行时提交前调用，保证失败动作整体表现为
    从未提交（原子不可见），不产生“事件已登记但状态未提交”的中间态。
    """

    if (
        len(state.card_ids_in(DRAW_PILE))
        + len(state.card_ids_in(DISCARD_PILE))
        < count
    ):
        raise ProductionBatchDeckExhaustedError(
            f"{label}需要{count}张牌，但牌堆与可重洗弃牌堆合计不足；"
            "生产批处理会话失败关闭且当前动作未被提交"
        )


@dataclass(frozen=True, slots=True)
class ArmorDamageResolution:
    """统一防具伤害修正结果（CP-04M）。

    ``final_amount`` 是经过全部已实现防具修正后的最终实际伤害（非负）；
    ``modifiers`` 按确定顺序记录实际生效的修正原因；``prevented`` 表示
    最终伤害为0（本批四种防具不会自然归零，该分支由统一接口保留给未来
    防止类效果）；``armor_ignored`` 表示本次效果处于目标防具无效（armor invalid）上下文，
    全部防具修正被抑制。
    """

    declared_amount: int
    final_amount: int
    modifiers: tuple[str, ...]
    prevented: bool
    armor_ignored: bool


def _armor_slot_instance(state: GameState, owner_id: str) -> str | None:
    """读取角色防具槽的唯一实体（0或1张；多张即状态损坏失败关闭）。"""

    ids = state.card_ids_in(ZoneRef.equipment(owner_id, "armor"))
    if len(ids) > 1:
        raise ProductionBatchError(
            f"角色{owner_id}的防具槽必须至多包含一张防具牌；当前为{len(ids)}张"
        )
    return ids[0] if ids else None


def resolve_armor_damage(
    state: GameState,
    *,
    victim_id: str,
    damage_type: str,
    declared_amount: int,
    ignore_armor: bool = False,
) -> ArmorDamageResolution:
    """统一防具伤害修正：藤甲火属性伤害+1，再按白银狮子限制（2点或更多
    改为1点）。修正顺序确定、可序列化、可回放；最终伤害不得为负。

    ``ignore_armor=True`` 表示当前效果处于目标防具无效（armor invalid）上下文（代码历史字段名保留；未来武器
    技能接入的统一入口）；此时全部防具修正被抑制。本批四种防具不会把
    伤害归零，``prevented`` 分支由统一接口保留。"""

    if not isinstance(state, GameState):
        raise TypeError("统一防具解析必须接收GameState")
    if victim_id not in state.players_by_id:
        raise ValueError(f"找不到防具解析目标角色{victim_id!r}")
    if not isinstance(damage_type, str) or not damage_type.strip():
        raise ValueError("伤害属性必须是非空字符串")
    if isinstance(declared_amount, bool) or not isinstance(declared_amount, int):
        raise TypeError("声明伤害必须是整数")
    if declared_amount < 0:
        raise ValueError("声明伤害不能为负数")
    if not isinstance(ignore_armor, bool):
        raise TypeError("防具无效上下文（ignore_armor）必须是布尔值")

    modifiers: list[str] = []
    final_amount = declared_amount
    armor_id = _armor_slot_instance(state, victim_id)
    if armor_id is None or ignore_armor:
        return ArmorDamageResolution(
            declared_amount=declared_amount,
            final_amount=final_amount,
            modifiers=tuple(modifiers),
            prevented=final_amount == 0,
            armor_ignored=ignore_armor,
        )
    armor_key = state.cards_by_id[armor_id].card_key
    if armor_key == "sgs_armor_tengjia" and damage_type == "火属性":
        final_amount += 1
        modifiers.append("tengjia_fire_plus_one")
    if armor_key == "sgs_armor_baiyinshizi" and final_amount >= 2:
        final_amount = 1
        modifiers.append("baiyin_cap_one")
    if final_amount < 0:
        raise ProductionBatchError("防具修正后伤害不得为负；失败关闭")
    return ArmorDamageResolution(
        declared_amount=declared_amount,
        final_amount=final_amount,
        modifiers=tuple(modifiers),
        prevented=final_amount == 0,
        armor_ignored=False,
    )


def armor_invalidates_effect(
    state: GameState,
    *,
    victim_id: str,
    card_instance_id: str,
    card_key: str,
    ignore_armor: bool = False,
    card_color: str | None = None,
) -> tuple[str, str] | None:
    """统一防具“牌无效”判断：返回（无效原因，防具实体ID）或None。

    仁王盾：黑色“杀”（普通／火／雷【杀】按实体牌颜色判断）对装备者无效；
    藤甲：普通【杀】、【南蛮入侵】、【万箭齐发】对装备者无效。无色牌与
    防具无效（armor invalid）上下文不触发。``card_color`` 供虚拟牌（丈八蛇矛转化杀）提供
    规则颜色；未提供时按实体牌颜色判断。返回原因用于在响应窗口前产生
    统一取消事件，不在【杀】代码中静默return。"""

    if not isinstance(state, GameState):
        raise TypeError("统一防具无效判断必须接收GameState")
    if victim_id not in state.players_by_id:
        raise ValueError(f"找不到防具无效判断目标角色{victim_id!r}")
    if not isinstance(card_instance_id, str) or not card_instance_id.strip():
        raise ValueError("防具无效判断必须提供实体牌ID")
    if not isinstance(card_key, str) or not card_key.strip():
        raise ValueError("防具无效判断必须提供卡牌键")
    if not isinstance(ignore_armor, bool):
        raise TypeError("无视防具上下文必须是布尔值")
    if ignore_armor:
        return None
    armor_id = _armor_slot_instance(state, victim_id)
    if armor_id is None:
        return None
    armor_key = state.cards_by_id[armor_id].card_key
    if armor_key == "sgs_armor_renwangdun" and card_key in SLASH_CARD_KEYS:
        if card_color is None:
            card_color = state.cards_by_id[card_instance_id].color
        if card_color == "黑":
            return "renwangdun_black_slash", armor_id
        return None
    if armor_key == "sgs_armor_tengjia" and card_key in (
        "sgs_basic_sha",
        "sgs_trick_nanmanruqin",
        "sgs_trick_wanjianqifa",
    ):
        return "tengjia_invalidates", armor_id
    return None


def _chain_trigger_conditions(
    damage_type: str,
    victim_chained: bool,
    actual_damage: int,
) -> bool:
    """属性伤害传导的统一触发判定（纯函数）。

    只有火／雷属性伤害、原始角色横置且最终实际伤害大于0时才触发；无属性
    伤害、未横置角色与实际伤害0均不触发，也不解除横置。
    """

    if damage_type not in ("火属性", "雷属性"):
        return False
    if not victim_chained:
        return False
    if isinstance(actual_damage, bool) or not isinstance(actual_damage, int):
        raise TypeError("实际伤害必须是整数")
    return actual_damage > 0


def _weapon_damage_bonus_at_damage(
    state: GameState, attacker_id: str, target_id: str
) -> int:
    """古锭刀“造成伤害时”判定（USER_CONFIRMED_MOBILE_RULE＋
    IN_GAME_CARD_TEXT_CONFIRMED，2026-08-08 用户移动版游戏内文本与实测）。

    游戏内文本：“锁定技，当你使用【杀】对目标角色造成伤害时，若该角色
    没有手牌，则此伤害+1。”判定时机是造成伤害时，不是使用/指定目标时；
    必须在此刻读取目标当前权威 hand zone——目标从被指定到伤害发生之间的
    手牌变化必须影响最终判定，不得使用指定目标时保存的旧 hand_count。"""

    if (
        equipped_weapon_key(state, attacker_id) == "sgs_weapon_gudingdao"
        and not state.card_ids_in(ZoneRef.hand(target_id))
    ):
        return 1
    return 0


def _ordered_chain_candidate_ids(
    players: Sequence[PlayerState],
    anchor_id: str,
    original_id: str,
) -> tuple[str, ...]:
    """以当前回合角色为锚点、按座次递增方向循环的确定性候选顺序。

    原始受伤角色永久排除；死亡与中途解除横置者不在排序阶段剔除，而是由
    逐名动态检查确定性跳过，保证顺序不依赖玩家提交。
    """

    if not players:
        return ()
    by_id = {player.player_id: player for player in players}
    if anchor_id not in by_id:
        raise ValueError(f"找不到传导顺序锚点角色{anchor_id!r}")
    if original_id not in by_id:
        raise ValueError(f"找不到原始受伤角色{original_id!r}")
    anchor_seat = by_id[anchor_id].seat
    total = len(players)
    ordered = sorted(
        (player for player in players if player.player_id != original_id),
        key=lambda player: (player.seat - anchor_seat) % total,
    )
    return tuple(player.player_id for player in ordered)


def _chain_dynamic_skip_reason(*, alive: bool, chained: bool) -> str | None:
    """传导候选轮到时动态检查：返回跳过标签或None表示需要结算。"""

    if not isinstance(alive, bool) or not isinstance(chained, bool):
        raise TypeError("存活与横置状态必须是布尔值")
    if not alive:
        return "skipped_dead"
    if not chained:
        return "skipped_unchained"
    return None


def _chain_recipient_outcome(actual_damage: int) -> tuple[bool, str]:
    """传导目标实际伤害结果：返回（是否解除横置，结算结果标签）。"""

    if isinstance(actual_damage, bool) or not isinstance(actual_damage, int):
        raise TypeError("实际伤害必须是整数")
    if actual_damage <= 0:
        return False, "prevented_zero"
    return True, "damaged"


def _chain_recipient_base(
    chain_base_damage: int,
    previous_actual_damage: int | None,
) -> int:
    """每名候选都以根基数开始；局部修正不改变后续候选使用的基数。"""

    if (
        isinstance(chain_base_damage, bool)
        or not isinstance(chain_base_damage, int)
        or chain_base_damage <= 0
    ):
        raise ValueError("传导根基数必须是正整数")
    if previous_actual_damage is not None and (
        isinstance(previous_actual_damage, bool)
        or not isinstance(previous_actual_damage, int)
        or previous_actual_damage < 0
    ):
        raise ValueError("前一名目标实际伤害必须是非负整数")
    return chain_base_damage


class BatchActionIdController:
    """只从当前真实合法集合中返回指定ID，用于测试与规则重执行。"""

    strategy_version = "production-batch-action-id-controller.v1"

    def __init__(self, action_id: str) -> None:
        self._action_id = action_id

    def choose(
        self, legal_actions: Sequence[LegalAction], context: ActionContext
    ) -> LegalAction:
        del context
        for action in legal_actions:
            if action.action_id == self._action_id:
                return action
        raise ProductionBatchError(
            "指定动作不在当前真实合法动作集合中，可能已过期或系伪造"
        )


class BatchReferenceController:
    """验收用确定性控制器；只从已经签发的合法动作集合中选择。

    这不是AI。固定优先级只用于让同一状态得到稳定、可解释的验收路径。
    """

    strategy_version = "production-batch-reference-controller.v1"

    def choose(
        self, legal_actions: Sequence[LegalAction], context: ActionContext
    ) -> LegalAction:
        if not legal_actions:
            raise ProductionBatchError("规则适配器没有返回任何合法动作")
        if any(action.action_id is None for action in legal_actions):
            raise ProductionBatchError("控制器只能接收已经签发ID的合法动作")

        def priority(action: LegalAction) -> tuple[int, str, str]:
            operation = str(action.payload.get("operation", ""))
            if context.phase == ProductionPhase.SLASH_RESPONSE.value:
                rank = 0 if operation == "play_dodge" else 9
            elif context.phase == ProductionPhase.TRICK_RESPONSE.value:
                rank = 0 if operation == "use_wuxie" else 1
            elif context.phase == ProductionPhase.ZONE_CHOICE.value:
                rank = 0 if operation == "choose_target_zone_card" else 9
            elif context.phase == ProductionPhase.DYING_RESCUE.value:
                if operation == "rescue_with_peach" and action.target_ids == (
                    action.actor_id,
                ):
                    rank = 0
                elif operation == "rescue_with_wine":
                    rank = 1
                elif operation == "rescue_with_peach":
                    rank = 2
                else:
                    rank = 9
            elif context.phase in (
                ProductionPhase.PREPARE.value,
                ProductionPhase.JUDGMENT.value,
                ProductionPhase.DRAW.value,
            ):
                rank = 0
            elif context.phase == ProductionPhase.JUDGMENT_WUXIE.value:
                # 自然对局默认不主动无懈判定窗口：先判牌，无懈路径由脚本控制器显式驱动
                rank = 0 if action.action_type is ActionType.PASS else 1
            elif context.phase == ProductionPhase.PLAY.value:
                if operation == "heal_self":
                    rank = 0
                elif operation == "use_wine_buff":
                    rank = 1
                elif operation == "use_slash":
                    rank = 2
                else:
                    rank = 9
            elif context.phase == ProductionPhase.DISCARD.value:
                # 提交动作只在已选数量==excess时枚举，因此先选牌后提交
                if operation == "discard_phase_submit":
                    rank = 0
                elif operation == "select_discard_card":
                    rank = 1
                elif operation == "unselect_discard_card":
                    rank = 2
                else:
                    rank = 9
            else:
                rank = 0 if action.action_type is not ActionType.PASS else 1
            return rank, action.card_instance_id or "", action.action_id or ""

        return min(legal_actions, key=priority)


class ScriptedBatchController:
    """按预置操作序列从真实合法集合中选动作。

    序列用尽后回退到 BatchReferenceController。用于录制包含【杀】【闪】
    【桃】【酒】的固定生产路径，不绕过合法动作集合。
    """

    strategy_version = "production-batch-scripted-controller.v1"

    def __init__(self, specs: Sequence[Mapping[str, object]]) -> None:
        self._specs: list[Mapping[str, object]] = [dict(spec) for spec in specs]
        self._reference = BatchReferenceController()

    def choose(
        self, legal_actions: Sequence[LegalAction], context: ActionContext
    ) -> LegalAction:
        for index, spec in enumerate(self._specs):
            candidates = [
                action for action in legal_actions if self._matches(action, spec)
            ]
            if candidates:
                del self._specs[index]
                return min(candidates, key=lambda action: action.action_id or "")
        return self._reference.choose(legal_actions, context)

    @staticmethod
    def _matches(action: LegalAction, spec: Mapping[str, object]) -> bool:
        for key, value in spec.items():
            if key == "operation":
                if action.payload.get("operation") != value:
                    return False
            elif key == "card_key":
                if action.payload.get("card_key") != value:
                    return False
            elif key == "target":
                if not action.target_ids or action.target_ids[0] != value:
                    return False
            elif key == "card_instance_id":
                if action.card_instance_id != value:
                    return False
            elif key == "zone":
                if action.payload.get("zone") != value:
                    return False
            elif key == "handle":
                if action.payload.get("handle") != value:
                    return False
            else:
                return False
        return True


class _BatchRuleAdapter(RuleAdapter):
    """生产基本牌批处理会话的阶段处理器；不包含任何卡牌规则。"""

    def __init__(self, session: "ProductionBasicCardBatch") -> None:
        self._session = session

    @property
    def adapter_version(self) -> str:
        return "production-basic-cards-batch-rules.v1"

    def audit_state(self) -> Mapping[str, object]:
        return MappingProxyType(self._session.runtime.audit_value())

    def enumerate_legal_actions(
        self, state: GameState, context: ActionContext
    ) -> Iterable[LegalAction]:
        return self._session._enumerate_for_adapter(state, context)

    def apply_action(
        self, state: GameState, context: ActionContext, action: LegalAction
    ) -> GameState:
        return self._session._apply_for_adapter(state, context, action)


@dataclass(frozen=True, slots=True)
class ProductionBatchResult:
    """生产批处理会话运行结束后的只读结果。"""

    winner_id: str
    step_count: int
    turn_count: int
    final_state: GameState
    events: tuple[GameEvent, ...]
    rng_calls: tuple[RNGCall, ...]
    phase_history: tuple[BatchPhaseEntry, ...]

class ProductionBasicCardBatch:
    """正式160张牌堆上六种基本牌的生产批处理会话。

    会话从正式牌堆CSV真实读取160张实体牌并建立
    :class:`FormalCardRegistry`，只允许六种基本牌接入生产适配器；其他
    卡牌保持未实现标记且不能fallback结算。阶段机只包含完成六种基本牌
    使用、响应、伤害、濒死、救援、死亡与胜负所需的阶段与窗口，不是
    完整整局引擎，也不允许把本批次解释为里程碑B完成。
    """

    __test__ = False

    def __init__(
        self,
        *,
        seed: int,
        deck_path: str | Path = DEFAULT_DECK_PATH,
        player_hp: tuple[int, int] = (4, 4),
        player_max_hp: tuple[int, int] = (4, 4),
        initial_hand_count: int = 4,
        shuffle: bool = True,
        session_id: str | None = None,
        session_secret: bytes | None = None,
    ) -> None:
        if isinstance(seed, bool) or not isinstance(seed, int):
            raise TypeError("随机种子必须是整数")
        if len(player_hp) != 2 or len(player_max_hp) != 2:
            raise ValueError("生产批处理会话必须提供恰好两名角色的体力")
        for index, (hp, max_hp) in enumerate(
            zip(player_hp, player_max_hp), start=1
        ):
            if (
                isinstance(hp, bool)
                or not isinstance(hp, int)
                or isinstance(max_hp, bool)
                or not isinstance(max_hp, int)
            ):
                raise TypeError(f"第{index}名角色的初始体力与上限必须是整数")
            if hp < 1 or max_hp < 1:
                raise ValueError(f"第{index}名角色必须以至少1点体力开始")
            if hp > max_hp:
                raise ValueError(f"第{index}名角色的初始体力不能高于体力上限")
        if (
            isinstance(initial_hand_count, bool)
            or not isinstance(initial_hand_count, int)
            or initial_hand_count < 1
        ):
            raise ValueError("初始手牌数必须是正整数")
        if not isinstance(shuffle, bool):
            raise TypeError("shuffle必须是布尔值")

        if session_id is None:
            session_id = secrets.token_hex(16)
        if not isinstance(session_id, str) or not session_id:
            raise ValueError("会话标识必须是非空字符串")
        if session_secret is None:
            session_secret = secrets.token_bytes(32)
        if not isinstance(session_secret, bytes):
            raise TypeError("会话秘密必须是bytes")
        if len(session_secret) < 32:
            raise ValueError("会话秘密至少需要256位（32字节）")

        deck_path = Path(deck_path)
        records, audit = load_deck_csv(deck_path, expected_total=160)
        AuthoritativeCoreSession._validate_formal_deck(records, audit)
        self._deck_path = deck_path
        self._session_id = session_id
        self._session_secret = session_secret
        self._rng = DeterministicRNG(seed)
        self._formal_registry = FormalCardRegistry(records, session=self)
        self._formal_registry.ensure_all_basic_cards_implemented()

        first_player_id = self._rng.choice(("p1", "p2"))
        self._first_player_id = first_player_id
        ordered_ids = [record.instance_id for record in records]
        if shuffle:
            self._rng.shuffle(ordered_ids)
        p1_hand = tuple(
            ordered_ids[index]
            for index in range(0, 2 * initial_hand_count, 2)
        )
        p2_hand = tuple(
            ordered_ids[index]
            for index in range(1, 2 * initial_hand_count, 2)
        )
        dealt = set(p1_hand) | set(p2_hand)
        draw_order = tuple(
            instance_id
            for instance_id in ordered_ids
            if instance_id not in dealt
        )
        players = (
            PlayerState("p1", 1, player_hp[0], player_max_hp[0]),
            PlayerState("p2", 2, player_hp[1], player_max_hp[1]),
        )
        locations = {
            instance_id: (
                ZoneRef.hand("p1")
                if instance_id in p1_hand
                else ZoneRef.hand("p2")
                if instance_id in p2_hand
                else DRAW_PILE
            )
            for instance_id in ordered_ids
        }
        self._state = GameState(
            cards=tuple(
                CardInstance.from_deck_record(record) for record in records
            ),
            players=players,
            card_locations=locations,
            zone_order={
                ZoneRef.hand("p1"): p1_hand,
                ZoneRef.hand("p2"): p2_hand,
                DRAW_PILE: draw_order,
                DISCARD_PILE: (),
                PROCESSING_ZONE: (),
            },
            deck_id=records[0].deck_id,
        )
        self._state.assert_card_conservation()
        self._events = EventQueue()
        for player_id, hand in (("p1", p1_hand), ("p2", p2_hand)):
            self._events.extend(
                GameEvent(
                    event_type=EventType.CARD_GAINED,
                    card_instance_id=instance_id,
                    card_key=_card_key(self._state, instance_id),
                    target_ids=(player_id,),
                    payload={"reason": "initial_hand"},
                )
                for instance_id in hand
            )
        # CP-04L：首名角色也必须经过完整阶段流（PREPARE→JUDGMENT→DRAW→PLAY），
        # 不再在初始化时直接摸2并进入PLAY；摸2在DRAW阶段以正式动作完成。
        self._runtime = _BatchRuntime(current_player_id=first_player_id)
        self._phase_history: list[BatchPhaseEntry] = [
            BatchPhaseEntry(1, first_player_id, ProductionPhase.PREPARE)
        ]
        self._step_count = 0
        self._registry = RuleRegistry()
        for phase in BATCH_PHASES:
            self._registry.register(
                PRODUCTION_BASIC_CARDS_MODE, phase.value, _BatchRuleAdapter(self)
            )
        for key, adapter in self._formal_registry.adapters.items():
            self._registry.register(
                PRODUCTION_BASIC_CARDS_MODE, f"card:{key}", adapter
            )

    @property
    def state(self) -> GameState:
        return self._state

    @property
    def registry(self) -> RuleRegistry:
        return self._registry

    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def session_secret_hex(self) -> str:
        return self._session_secret.hex()

    @property
    def formal_registry(self) -> FormalCardRegistry:
        return self._formal_registry

    @property
    def runtime(self) -> _BatchRuntime:
        return self._runtime

    @property
    def phase(self) -> ProductionPhase:
        return self._runtime.phase

    @property
    def current_player_id(self) -> str:
        return self._runtime.current_player_id

    @property
    def first_player_id(self) -> str:
        return self._first_player_id

    @property
    def is_finished(self) -> bool:
        return self._runtime.phase is ProductionPhase.FINISHED

    @property
    def winner_id(self) -> str | None:
        return self._runtime.winner_id

    @property
    def events(self) -> tuple[GameEvent, ...]:
        return self._events.snapshot()

    @property
    def rng_calls(self) -> tuple[RNGCall, ...]:
        return self._rng.calls

    @property
    def phase_history(self) -> tuple[BatchPhaseEntry, ...]:
        return tuple(self._phase_history)

    @property
    def step_count(self) -> int:
        return self._step_count

    @property
    def current_actor_id(self) -> str:
        runtime = self._runtime
        if runtime.phase is ProductionPhase.SLASH_RESPONSE:
            if runtime.pending_slash is None:
                raise ProductionBatchError("响应阶段缺少待响应的【杀】")
            return runtime.pending_slash.target_id
        if runtime.phase is ProductionPhase.TRICK_RESPONSE:
            if runtime.pending_trick is None:
                raise ProductionBatchError("锦囊响应阶段缺少待响应的锦囊")
            if not runtime.trick_response_order:
                raise ProductionBatchError("锦囊响应顺序为空")
            if runtime.trick_response_index >= len(runtime.trick_response_order):
                raise ProductionBatchError("锦囊响应顺序已经耗尽")
            return runtime.trick_response_order[runtime.trick_response_index]
        if runtime.phase is ProductionPhase.ZONE_CHOICE:
            if runtime.pending_zone_choice is None:
                raise ProductionBatchError("目标区域选牌阶段缺少选牌窗口")
            return runtime.pending_zone_choice.user_id
        if runtime.phase is ProductionPhase.DUEL_RESPONSE:
            if runtime.pending_duel is None:
                raise ProductionBatchError("【决斗】响应阶段缺少结算状态")
            return runtime.pending_duel.responder_id
        if runtime.phase is ProductionPhase.FIRE_ATTACK_REVEAL:
            if runtime.pending_fire_attack is None:
                raise ProductionBatchError("【火攻】展示阶段缺少结算状态")
            return runtime.pending_fire_attack.target_id
        if runtime.phase is ProductionPhase.FIRE_ATTACK_DISCARD:
            if runtime.pending_fire_attack is None:
                raise ProductionBatchError("【火攻】弃牌阶段缺少结算状态")
            return runtime.pending_fire_attack.user_id
        if runtime.phase is ProductionPhase.WEAPON_AFTER_DAMAGE:
            if runtime.pending_weapon_choice is None:
                raise ProductionBatchError("武器触发选择阶段缺少挂起状态")
            return runtime.pending_weapon_choice.attacker_id
        if runtime.phase is ProductionPhase.WEAPON_SLASH_CHOICE:
            if runtime.pending_slash_choice is None:
                raise ProductionBatchError("被闪后/伤害前武器选择缺少挂起状态")
            return runtime.pending_slash_choice.attacker_id
        if runtime.phase is ProductionPhase.WEAPON_DISCARD_TWO:
            if runtime.pending_discard_two is None:
                raise ProductionBatchError("弃2张窗口缺少挂起状态")
            return runtime.pending_discard_two.chooser_id
        if runtime.phase is ProductionPhase.HANBING_DISCARD:
            if runtime.pending_hanbing_discard is None:
                raise ProductionBatchError("寒冰剑逐张弃置窗口缺少挂起状态")
            return runtime.pending_hanbing_discard.attacker_id
        if runtime.phase is ProductionPhase.WUGU_PICK:
            if runtime.pending_wugu is None:
                raise ProductionBatchError("五谷选牌阶段缺少选牌状态")
            if (
                runtime.pending_wugu.current_target_index
                >= len(runtime.pending_wugu.target_sequence)
            ):
                raise ProductionBatchError("五谷目标索引越界")
            return runtime.pending_wugu.target_sequence[
                runtime.pending_wugu.current_target_index
            ]
        if runtime.phase in (
            ProductionPhase.NANMAN_RESPONSE,
            ProductionPhase.WANJIAN_RESPONSE,
        ):
            if (
                runtime.pending_group_trick is None
                or runtime.pending_group_trick.responder_id is None
            ):
                raise ProductionBatchError(
                    "群体锦囊响应阶段缺少当前响应目标"
                )
            return runtime.pending_group_trick.responder_id
        if runtime.phase is ProductionPhase.DYING_RESCUE:
            if not runtime.rescue_order:
                raise ProductionBatchError("濒死阶段缺少救援顺序")
            if runtime.rescue_index >= len(runtime.rescue_order):
                raise ProductionBatchError("濒死救援顺序已经耗尽")
            return runtime.rescue_order[runtime.rescue_index]
        if runtime.phase in (
            ProductionPhase.PREPARE,
            ProductionPhase.JUDGMENT,
            ProductionPhase.DRAW,
            ProductionPhase.PLAY,
            ProductionPhase.DISCARD,
            ProductionPhase.END,
        ):
            return runtime.current_player_id
        if runtime.phase is ProductionPhase.JUDGMENT_WUXIE:
            if not runtime.trick_response_order:
                raise ProductionBatchError("判定无懈窗口缺少响应顺序")
            if runtime.trick_response_index >= len(runtime.trick_response_order):
                raise ProductionBatchError("判定无懈响应顺序已经耗尽")
            return runtime.trick_response_order[runtime.trick_response_index]
        if runtime.phase is ProductionPhase.BORROWED_SWORD_CHOICE:
            pending = runtime.pending_borrowed_sword
            if pending is None or pending.stage != "slash_request":
                raise ProductionBatchError(
                    "借刀选牌阶段缺少当前选择目标"
                )
            return pending.first_target_id
        raise ProductionBatchError(
            f"阶段{runtime.phase.value!r}没有可行动角色"
        )

    @staticmethod
    def opponent_of(player_id: str) -> str:
        if player_id == "p1":
            return "p2"
        if player_id == "p2":
            return "p1"
        raise ProductionBatchError(f"生产批处理会话不存在玩家{player_id!r}")

    def _context(self) -> ActionContext:
        if self.is_finished:
            raise ProductionBatchFinishedError(
                "胜利已经成立，对局不得继续执行动作"
            )
        runtime = self._runtime
        return ActionContext(
            mode=PRODUCTION_BASIC_CARDS_MODE,
            phase=runtime.phase.value,
            actor_id=self.current_actor_id,
            turn_player_id=runtime.current_player_id,
            response_window_id=runtime.response_window_id,
            expected_revision=self.state.revision,
            metadata={
                "turn_number": runtime.turn_number,
                "slash_used_counts": dict(runtime.slash_used_counts),
                "judgment_entry_indices": dict(runtime.judgment_entry_indices),
                "processed_judgment_instance_ids": list(
                    runtime.processed_judgment_instance_ids
                ),
                "skipped_phases": dict(runtime.skipped_phases),
                "wine_buff_owner_id": runtime.wine_buff_owner_id,
                "wine_buff_used_this_play_phase": (
                    runtime.wine_buff_used_this_play_phase
                ),
                "pending_trick": (
                    None
                    if runtime.pending_trick is None
                    else {
                        "user_id": runtime.pending_trick.user_id,
                        "target_id": runtime.pending_trick.target_id,
                        "trick_instance_id": (
                            runtime.pending_trick.trick_instance_id
                        ),
                        "trick_key": runtime.pending_trick.trick_key,
                        "root_trick_instance_id": (
                            runtime.pending_trick.trick_instance_id
                        ),
                    }
                ),
                "pending_group_trick": (
                    None
                    if runtime.pending_group_trick is None
                    else {
                        "user_id": runtime.pending_group_trick.user_id,
                        "trick_instance_id": (
                            runtime.pending_group_trick.trick_instance_id
                        ),
                        "trick_key": runtime.pending_group_trick.trick_key,
                        "target_sequence": list(
                            runtime.pending_group_trick.target_sequence
                        ),
                        "current_target_index": (
                            runtime.pending_group_trick.current_target_index
                        ),
                        "completed_target_ids": list(
                            runtime.pending_group_trick.completed_target_ids
                        ),
                        "responder_id": (
                            runtime.pending_group_trick.responder_id
                        ),
                    }
                ),
                "pending_wugu": (
                    None
                    if runtime.pending_wugu is None
                    else {
                        "user_id": runtime.pending_wugu.user_id,
                        "trick_instance_id": (
                            runtime.pending_wugu.trick_instance_id
                        ),
                        "trick_key": runtime.pending_wugu.trick_key,
                        "pool": list(runtime.pending_wugu.pool),
                        "pool_digest": runtime.pending_wugu.pool_digest,
                        "target_sequence": list(
                            runtime.pending_wugu.target_sequence
                        ),
                        "current_target_index": (
                            runtime.pending_wugu.current_target_index
                        ),
                        "completed_target_ids": list(
                            runtime.pending_wugu.completed_target_ids
                        ),
                        "window_id": runtime.pending_wugu.window_id,
                    }
                ),
                "trick_effect_active": runtime.trick_effect_active,
                "trick_consecutive_passes": (
                    runtime.trick_consecutive_passes
                ),
                "trick_response_index": runtime.trick_response_index,
                "trick_direct_response_to": (
                    runtime.trick_direct_response_to
                ),
                "pending_zone_choice": (
                    None
                    if runtime.pending_zone_choice is None
                    else {
                        "user_id": runtime.pending_zone_choice.user_id,
                        "target_id": runtime.pending_zone_choice.target_id,
                        "trick_instance_id": (
                            runtime.pending_zone_choice.trick_instance_id
                        ),
                        "trick_key": runtime.pending_zone_choice.trick_key,
                        "window_id": runtime.pending_zone_choice.window_id,
                        "zones": list(runtime.pending_zone_choice.zones),
                    }
                ),
                "discard_phase_selected_ids": list(
                    runtime.discard_phase_selected_ids
                ),
                "pending_weapon_choice": (
                    None
                    if runtime.pending_weapon_choice is None
                    else {
                        "weapon_key": runtime.pending_weapon_choice.weapon_key,
                        "kind": runtime.pending_weapon_choice.kind,
                        "attacker_id": (
                            runtime.pending_weapon_choice.attacker_id
                        ),
                        "target_id": runtime.pending_weapon_choice.target_id,
                        "window_id": runtime.pending_weapon_choice.window_id,
                    }
                ),
                "pending_judgment": (
                    None
                    if runtime.pending_judgment is None
                    else {
                        "trick_instance_id": (
                            runtime.pending_judgment.trick_instance_id
                        ),
                        "trick_key": runtime.pending_judgment.trick_key,
                        "target_id": runtime.pending_judgment.target_id,
                        "stage": runtime.pending_judgment.stage,
                        "entry_index": runtime.pending_judgment.entry_index,
                        "wuxie_nullified": (
                            runtime.pending_judgment.wuxie_nullified
                        ),
                        "cleanup_done": (
                            runtime.pending_judgment.cleanup_done
                        ),
                    }
                ),
                "pending_dying_id": runtime.pending_dying_id,
                "rescue_index": runtime.rescue_index,
            },
        )

    def legal_actions(self) -> tuple[LegalAction, ...]:
        return enumerate_legal_actions(
            self.state, self._context(), self.registry
        )

    def step(
        self,
        controller: (
            BatchActionIdController
            | BatchReferenceController
            | ScriptedBatchController
            | None
        ) = None,
    ) -> LegalAction:
        if self.is_finished:
            raise ProductionBatchFinishedError(
                "胜利已经成立，对局不得继续执行动作"
            )
        selected = controller or BatchReferenceController()
        context = self._context()
        legal = enumerate_legal_actions(self.state, context, self.registry)
        chosen = selected.choose(legal, context)
        validated = validate_action(self.state, context, chosen, self.registry)
        self._state = apply_action(
            self.state, context, validated, self.registry
        )
        self._step_count += 1
        self._state.assert_card_conservation()
        return validated

    def run(
        self,
        controller: (
            BatchActionIdController
            | BatchReferenceController
            | ScriptedBatchController
            | None
        ) = None,
        *,
        max_steps: int = 500,
    ) -> ProductionBatchResult:
        if (
            isinstance(max_steps, bool)
            or not isinstance(max_steps, int)
            or max_steps < 1
        ):
            raise ValueError("安全动作上限必须是正整数")
        selected = controller or BatchReferenceController()
        executed = 0
        while not self.is_finished and executed < max_steps:
            self.step(selected)
            executed += 1
        if not self.is_finished:
            raise ProductionBatchSafetyLimitError(
                f"生产批处理会话在{max_steps}个动作后仍未结束；"
                "禁止静默判胜或近似收尾"
            )
        assert self.winner_id is not None
        return ProductionBatchResult(
            winner_id=self.winner_id,
            step_count=self.step_count,
            turn_count=self._runtime.turn_number,
            final_state=self.state,
            events=self.events,
            rng_calls=self.rng_calls,
            phase_history=self.phase_history,
        )

    @property
    def execution_snapshot(self) -> dict[str, object]:
        """返回可序列化的稳定执行快照，供严格重执行逐步比较。"""

        snapshot = {
            "schema": "production-basic-batch-execution-v1",
            "mode": PRODUCTION_BASIC_CARDS_MODE,
            "runtime": self._runtime.audit_value(),
            "first_player_id": self.first_player_id,
            "current_actor_id": (
                None if self.is_finished else self.current_actor_id
            ),
            "step_count": self.step_count,
            "event_count": len(self.events),
            "events": [event.to_replay_dict() for event in self.events],
            "rng_call_count": len(self.rng_calls),
            "rng_calls": [call.to_dict() for call in self.rng_calls],
            "phase_history": [
                {
                    "turn_number": entry.turn_number,
                    "turn_player_id": entry.turn_player_id,
                    "phase": entry.phase.value,
                }
                for entry in self.phase_history
            ],
            "game_state": canonical_state_snapshot(self.state),
        }
        normalized = json.loads(canonical_json(snapshot))
        assert isinstance(normalized, dict)
        return normalized

    @property
    def execution_hash(self) -> str:
        return sha256_value(self.execution_snapshot)

    def _enumerate_for_adapter(
        self, state: GameState, context: ActionContext
    ) -> tuple[LegalAction, ...]:
        if (
            context.mode != PRODUCTION_BASIC_CARDS_MODE
            or context.phase != self.phase.value
        ):
            raise ProductionBatchError(
                "行动上下文与生产批处理会话当前阶段不一致"
            )
        actor = context.actor_id
        actions: list[LegalAction] = []
        if self.phase is ProductionPhase.PREPARE:
            actions.append(
                LegalAction(
                    action_type=ActionType.PASS,
                    actor_id=actor,
                    payload={"operation": "proceed_prepare"},
                )
            )
        elif self.phase is ProductionPhase.JUDGMENT:
            actions.append(
                LegalAction(
                    action_type=ActionType.PASS,
                    actor_id=actor,
                    payload={"operation": "proceed_judgment"},
                )
            )
        elif self.phase is ProductionPhase.DRAW:
            actions.append(
                LegalAction(
                    action_type=ActionType.PASS,
                    actor_id=actor,
                    payload={"operation": "proceed_draw"},
                )
            )
        elif self.phase is ProductionPhase.JUDGMENT_WUXIE:
            for adapter in self._formal_registry.adapters.values():
                actions.extend(adapter.enumerate_legal_actions(state, context))
            actions.append(
                LegalAction(
                    action_type=ActionType.PASS,
                    actor_id=actor,
                    payload={"operation": "pass_judgment_wuxie"},
                )
            )
        elif self.phase is ProductionPhase.PLAY:
            for adapter in self._formal_registry.adapters.values():
                actions.extend(adapter.enumerate_legal_actions(state, context))
            # CP-04P 丈八蛇矛（7.8 当前确认）：两张手牌当作普通【杀】使用。
            # 虚拟杀不是新的实体卡牌：action 的 card_instance_id 为确定性
            # 合成虚拟标识（回合＋两张材料），材料对只通过不透明HMAC句柄
            # 暴露；出牌阶段使用虚拟杀消耗正常【杀】额度。
            if (
                equipped_weapon_key(state, actor) == "sgs_weapon_zhangbashemao"
                and self._runtime.slash_used_counts.get(actor, 0) == 0
            ):
                # G-003 统一 fail-closed：丈八蛇矛保持 PARTIAL（VIRTUAL_CARD_
                # SUBCARD_LIFECYCLE_RULE_GAP），在正式枚举 virtual proposal
                # 之前直接门禁拒绝（decision=use_slash，手牌≥2时抛
                # UnsupportedRuleError），不生成 virtual:zhangba:* candidate
                # 后再撞公共实体验证器。
                check_weapon_skill_gate(
                    state,
                    actor_id=actor,
                    decision="use_slash",
                    target_id=self.opponent_of(actor),
                    slash_used_count=self._runtime.slash_used_counts.get(
                        actor, 0
                    ),
                )
                hand_ids = tuple(state.card_ids_in(ZoneRef.hand(actor)))
                if len(hand_ids) >= 2:
                    window_id = (
                        f"zhangba:{self._runtime.turn_number}:{actor}"
                    )
                    snapshot_digest = sha256_value(hand_ids)
                    for index, first in enumerate(hand_ids):
                        for second in hand_ids[index + 1 :]:
                            material_ids = (first, second)
                            handle = _zhangba_material_handle(
                                self._session_id,
                                self._session_secret,
                                window_id,
                                actor,
                                snapshot_digest,
                                material_ids,
                            )
                            virtual_id = (
                                f"virtual:zhangba:"
                                f"{self._runtime.turn_number}:"
                                f"{first}:{second}"
                            )
                            actions.append(
                                LegalAction(
                                    action_type=ActionType.USE_CARD,
                                    actor_id=actor,
                                    card_instance_id=virtual_id,
                                    target_ids=(self.opponent_of(actor),),
                                    payload={
                                        "operation": "use_slash",
                                        "card_key": "sgs_basic_sha",
                                        "card_name": "杀",
                                        "zhangba_virtual": True,
                                        "handle": handle,
                                        "window_id": window_id,
                                    },
                                )
                            )
            actions.append(
                LegalAction(
                    action_type=ActionType.PASS,
                    actor_id=actor,
                    payload={"operation": "end_play_phase"},
                )
            )
        elif self.phase is ProductionPhase.END:
            actions.append(
                LegalAction(
                    action_type=ActionType.PASS,
                    actor_id=actor,
                    payload={"operation": "end_turn"},
                )
            )
        elif self.phase is ProductionPhase.DISCARD:
            runtime = self._runtime
            hand_ids = state.card_ids_in(ZoneRef.hand(actor))
            hand_limit = hand_limit_of(state, actor)
            excess = len(hand_ids) - hand_limit
            if excess > 0:
                if (
                    runtime.discard_phase_window_id is None
                    or runtime.discard_phase_snapshot_digest is None
                ):
                    raise ProductionBatchError(
                        "弃牌阶段缺少批量选择窗口状态"
                    )
                if sha256_value(
                    tuple(hand_ids)
                ) != runtime.discard_phase_snapshot_digest:
                    # 选择窗口打开后手牌已变化：不再铸造任何选择句柄，
                    # 旧句柄与旧提交无法继续枚举或应用，失败关闭。
                    return ()
                state_hash = state_sha256(
                    canonical_state_snapshot(state)
                )
                selected_set = set(runtime.discard_phase_selected_ids)
                base = {
                    "window_id": runtime.discard_phase_window_id,
                    "state_hash": state_hash,
                    "excess_count": excess,
                }
                for instance_id in hand_ids:
                    if instance_id in selected_set:
                        continue
                    actions.append(
                        LegalAction(
                            action_type=ActionType.CHOOSE_OPTION,
                            actor_id=actor,
                            card_instance_id=instance_id,
                            target_ids=(actor,),
                            payload={
                                **base,
                                "operation": "select_discard_card",
                                "handle": _hand_choice_handle(
                                    self._session_id,
                                    self._session_secret,
                                    runtime.discard_phase_window_id,
                                    actor,
                                    "hand",
                                    runtime.discard_phase_snapshot_digest,
                                    instance_id,
                                ),
                            },
                        )
                    )
                for instance_id in runtime.discard_phase_selected_ids:
                    if instance_id not in hand_ids:
                        # 已选实体已离开手牌：不再提供取消动作
                        continue
                    actions.append(
                        LegalAction(
                            action_type=ActionType.CHOOSE_OPTION,
                            actor_id=actor,
                            card_instance_id=instance_id,
                            target_ids=(actor,),
                            payload={
                                **base,
                                "operation": "unselect_discard_card",
                                "handle": _hand_choice_handle(
                                    self._session_id,
                                    self._session_secret,
                                    runtime.discard_phase_window_id,
                                    actor,
                                    "hand",
                                    runtime.discard_phase_snapshot_digest,
                                    instance_id,
                                ),
                            },
                        )
                    )
                if len(selected_set) == excess:
                    actions.append(
                        LegalAction(
                            action_type=ActionType.CHOOSE_OPTION,
                            actor_id=actor,
                            target_ids=(actor,),
                            payload={
                                **base,
                                "operation": "discard_phase_submit",
                                "selected_count": len(selected_set),
                            },
                        )
                    )
        elif self.phase is ProductionPhase.WEAPON_AFTER_DAMAGE:
            runtime = self._runtime
            choice = runtime.pending_weapon_choice
            if choice is None:
                raise ProductionBatchError("武器触发选择阶段缺少挂起状态")
            if context.actor_id != choice.attacker_id:
                return ()
            if choice.kind == "qilingong_discard_mount":
                for slot in ("attack_horse", "defense_horse"):
                    zone = ZoneRef.equipment(choice.target_id, slot)
                    for instance_id in state.card_ids_in(zone):
                        actions.append(
                            LegalAction(
                                action_type=ActionType.MOVE_CARD,
                                actor_id=context.actor_id,
                                card_instance_id=instance_id,
                                target_ids=(choice.target_id,),
                                payload={
                                    "operation": "weapon_discard_mount",
                                    "card_key": _card_key(state, instance_id),
                                    "window_id": choice.window_id,
                                },
                            )
                        )
                actions.append(
                    LegalAction(
                        action_type=ActionType.PASS,
                        actor_id=context.actor_id,
                        payload={
                            "operation": "pass_weapon_choice",
                            "window_id": choice.window_id,
                        },
                    )
                )
        elif self.phase is ProductionPhase.WEAPON_SLASH_CHOICE:
            runtime = self._runtime
            choice = runtime.pending_slash_choice
            if choice is None:
                raise ProductionBatchError("被闪后/伤害前武器选择缺少挂起状态")
            if context.actor_id != choice.attacker_id:
                return ()
            base = {"window_id": choice.window_id}
            if choice.kind == "guanshifu_force_hit":
                actions.append(
                    LegalAction(
                        action_type=ActionType.PASS,
                        actor_id=context.actor_id,
                        target_ids=(choice.target_id,),
                        payload={**base, "operation": "weapon_force_hit"},
                    )
                )
            elif choice.kind == "hanbing_prevent":
                actions.append(
                    LegalAction(
                        action_type=ActionType.PASS,
                        actor_id=context.actor_id,
                        target_ids=(choice.target_id,),
                        payload={
                            **base,
                            "operation": "weapon_prevent_damage",
                        },
                    )
                )
            elif choice.kind == "qinglong_continue":
                # CP-04P 青龙偃月刀（7.6 用户整理解释）：被【闪】响应后可
                # 继续对该目标使用一张【杀】。候选杀只接受隐藏手牌句柄，
                # 客户端不得提交裸实体ID；攻击范围与距离在窗口打开时已按
                # 原目标校验，实际使用前在应用层再次动态重检。
                if (
                    choice.snapshot_digest is None
                    or sha256_value(
                        tuple(
                            state.card_ids_in(
                                ZoneRef.hand(choice.attacker_id)
                            )
                        )
                    )
                    != choice.snapshot_digest
                ):
                    return ()
                state_hash = state_sha256(canonical_state_snapshot(state))
                for handle in choice.handles:
                    actions.append(
                        LegalAction(
                            action_type=ActionType.RESPOND,
                            actor_id=context.actor_id,
                            target_ids=(choice.target_id,),
                            payload={
                                **base,
                                "operation": "qinglong_use_slash",
                                "handle": handle,
                                "state_hash": state_hash,
                            },
                        )
                    )
            actions.append(
                LegalAction(
                    action_type=ActionType.PASS,
                    actor_id=context.actor_id,
                    payload={**base, "operation": "pass_weapon_choice"},
                )
            )
        elif self.phase is ProductionPhase.WEAPON_DISCARD_TWO:
            runtime = self._runtime
            discard_two = runtime.pending_discard_two
            if discard_two is None:
                raise ProductionBatchError("弃2张窗口缺少挂起状态")
            if context.actor_id != discard_two.chooser_id:
                return ()
            if (
                discard_two.snapshot_digest is None
                or sha256_value(
                    tuple(
                        state.card_ids_in(
                            ZoneRef.hand(discard_two.cards_owner_id)
                        )
                    )
                )
                != discard_two.snapshot_digest
            ):
                return ()
            state_hash = state_sha256(canonical_state_snapshot(state))
            selected = set(discard_two.selected_ids)
            base = {
                "window_id": discard_two.window_id,
                "state_hash": state_hash,
            }
            for instance_id in state.card_ids_in(
                ZoneRef.hand(discard_two.cards_owner_id)
            ):
                if instance_id in selected:
                    continue
                actions.append(
                    LegalAction(
                        action_type=ActionType.CHOOSE_OPTION,
                        actor_id=context.actor_id,
                        card_instance_id=instance_id,
                        target_ids=(discard_two.cards_owner_id,),
                        payload={
                            **base,
                            "operation": "select_discard_two",
                            "handle": _hand_choice_handle(
                                self._session_id,
                                self._session_secret,
                                discard_two.window_id,
                                discard_two.cards_owner_id,
                                "hand",
                                discard_two.snapshot_digest,
                                instance_id,
                            ),
                        },
                    )
                )
            for slot in EQUIPMENT_SLOTS:
                for instance_id in state.card_ids_in(
                    ZoneRef.equipment(discard_two.cards_owner_id, slot)
                ):
                    if instance_id in selected:
                        continue
                    if instance_id == discard_two.excluded_instance_id:
                        # 贯石斧自身不能作为发动代价（USER_CONFIRMED_MOBILE_RULE，
                        # 2026-08-08 用户移动版实测确认）：当前正在发动技能的
                        # 【贯石斧】实体必须排除在候选集合之外；通用“牌=手牌区＋
                        # 装备区”区域规则不变，这只是贯石斧自身的特殊排除。
                        continue
                    actions.append(
                        LegalAction(
                            action_type=ActionType.MOVE_CARD,
                            actor_id=context.actor_id,
                            card_instance_id=instance_id,
                            target_ids=(discard_two.cards_owner_id,),
                            payload={
                                **base,
                                "operation": "select_discard_two",
                                "zone": f"equipment:{slot}",
                                "card_key": _card_key(state, instance_id),
                            },
                        )
                    )
            for instance_id in discard_two.selected_ids:
                zone = discard_two.selected_zones.get(instance_id, "hand")
                if zone != "hand":
                    actions.append(
                        LegalAction(
                            action_type=ActionType.MOVE_CARD,
                            actor_id=context.actor_id,
                            card_instance_id=instance_id,
                            target_ids=(discard_two.cards_owner_id,),
                            payload={
                                **base,
                                "operation": "unselect_discard_two",
                                "zone": zone,
                                "card_key": _card_key(state, instance_id),
                            },
                        )
                    )
                    continue
                actions.append(
                    LegalAction(
                        action_type=ActionType.CHOOSE_OPTION,
                        actor_id=context.actor_id,
                        card_instance_id=instance_id,
                        target_ids=(discard_two.cards_owner_id,),
                        payload={
                            **base,
                            "operation": "unselect_discard_two",
                            "handle": _hand_choice_handle(
                                self._session_id,
                                self._session_secret,
                                discard_two.window_id,
                                discard_two.cards_owner_id,
                                "hand",
                                discard_two.snapshot_digest,
                                instance_id,
                            ),
                        },
                    )
                )
            equipment_count = sum(
                len(
                    state.card_ids_in(
                        ZoneRef.equipment(discard_two.cards_owner_id, slot)
                    )
                )
                for slot in EQUIPMENT_SLOTS
            )
            required = min(
                2,
                len(state.card_ids_in(ZoneRef.hand(discard_two.cards_owner_id)))
                + equipment_count,
            )
            if len(selected) == required:
                actions.append(
                    LegalAction(
                        action_type=ActionType.PASS,
                        actor_id=context.actor_id,
                        target_ids=(discard_two.cards_owner_id,),
                        payload={
                            **base,
                            "operation": "discard_two_submit",
                        },
                    )
                )
        elif self.phase is ProductionPhase.HANBING_DISCARD:
            runtime = self._runtime
            hanbing = runtime.pending_hanbing_discard
            if hanbing is None:
                raise ProductionBatchError("寒冰剑逐张弃置窗口缺少挂起状态")
            if context.actor_id != hanbing.attacker_id:
                return ()
            if (
                hanbing.snapshot_digest is None
                or sha256_value(
                    tuple(
                        state.card_ids_in(ZoneRef.hand(hanbing.target_id))
                    )
                )
                != hanbing.snapshot_digest
            ):
                return ()
            state_hash = state_sha256(canonical_state_snapshot(state))
            base = {
                "window_id": hanbing.window_id,
                "state_hash": state_hash,
                "step": hanbing.step,
            }
            for instance_id in state.card_ids_in(
                ZoneRef.hand(hanbing.target_id)
            ):
                actions.append(
                    LegalAction(
                        action_type=ActionType.CHOOSE_OPTION,
                        actor_id=context.actor_id,
                        card_instance_id=instance_id,
                        target_ids=(hanbing.target_id,),
                        payload={
                            **base,
                            "operation": "hanbing_discard_card",
                            "handle": _hand_choice_handle(
                                self._session_id,
                                self._session_secret,
                                hanbing.window_id,
                                hanbing.target_id,
                                "hand",
                                hanbing.snapshot_digest,
                                instance_id,
                            ),
                        },
                    )
                )
            for slot in EQUIPMENT_SLOTS:
                for instance_id in state.card_ids_in(
                    ZoneRef.equipment(hanbing.target_id, slot)
                ):
                    actions.append(
                        LegalAction(
                            action_type=ActionType.MOVE_CARD,
                            actor_id=context.actor_id,
                            card_instance_id=instance_id,
                            target_ids=(hanbing.target_id,),
                            payload={
                                **base,
                                "operation": "hanbing_discard_card",
                                "zone": f"equipment:{slot}",
                                "card_key": _card_key(state, instance_id),
                            },
                        )
                    )
        elif self.phase is ProductionPhase.SLASH_RESPONSE:
            for adapter in self._formal_registry.adapters.values():
                actions.extend(adapter.enumerate_legal_actions(state, context))
            actions.append(
                LegalAction(
                    action_type=ActionType.PASS,
                    actor_id=actor,
                    payload={"operation": "pass_slash_response"},
                )
            )
        elif self.phase is ProductionPhase.TRICK_RESPONSE:
            for adapter in self._formal_registry.adapters.values():
                actions.extend(adapter.enumerate_legal_actions(state, context))
            actions.append(
                LegalAction(
                    action_type=ActionType.PASS,
                    actor_id=actor,
                    payload={"operation": "pass_trick_response"},
                )
            )
        elif self.phase is ProductionPhase.ZONE_CHOICE:
            for adapter in self._formal_registry.adapters.values():
                actions.extend(adapter.enumerate_legal_actions(state, context))
        elif self.phase is ProductionPhase.DUEL_RESPONSE:
            for adapter in self._formal_registry.adapters.values():
                actions.extend(adapter.enumerate_legal_actions(state, context))
            actions.append(
                LegalAction(
                    action_type=ActionType.PASS,
                    actor_id=actor,
                    payload={"operation": "pass_duel_slash"},
                )
            )
        elif self.phase is ProductionPhase.FIRE_ATTACK_REVEAL:
            for adapter in self._formal_registry.adapters.values():
                actions.extend(adapter.enumerate_legal_actions(state, context))
        elif self.phase is ProductionPhase.FIRE_ATTACK_DISCARD:
            for adapter in self._formal_registry.adapters.values():
                actions.extend(adapter.enumerate_legal_actions(state, context))
            actions.append(
                LegalAction(
                    action_type=ActionType.PASS,
                    actor_id=actor,
                    payload={"operation": "pass_fire_attack_discard"},
                )
            )
        elif self.phase is ProductionPhase.BORROWED_SWORD_CHOICE:
            for adapter in self._formal_registry.adapters.values():
                actions.extend(adapter.enumerate_legal_actions(state, context))
        elif self.phase is ProductionPhase.NANMAN_RESPONSE:
            for adapter in self._formal_registry.adapters.values():
                actions.extend(adapter.enumerate_legal_actions(state, context))
            actions.append(
                LegalAction(
                    action_type=ActionType.PASS,
                    actor_id=actor,
                    payload={"operation": "pass_nanman_slash"},
                )
            )
        elif self.phase is ProductionPhase.WANJIAN_RESPONSE:
            for adapter in self._formal_registry.adapters.values():
                actions.extend(adapter.enumerate_legal_actions(state, context))
            actions.append(
                LegalAction(
                    action_type=ActionType.PASS,
                    actor_id=actor,
                    payload={"operation": "pass_wanjian_jink"},
                )
            )
        elif self.phase is ProductionPhase.WUGU_PICK:
            for adapter in self._formal_registry.adapters.values():
                actions.extend(adapter.enumerate_legal_actions(state, context))
        elif self.phase is ProductionPhase.DYING_RESCUE:
            for adapter in self._formal_registry.adapters.values():
                actions.extend(adapter.enumerate_legal_actions(state, context))
            actions.append(
                LegalAction(
                    action_type=ActionType.PASS,
                    actor_id=actor,
                    payload={"operation": "pass_rescue"},
                )
            )
        else:
            raise ProductionBatchError(
                f"阶段{self.phase.value!r}不能枚举合法动作"
            )
        return tuple(actions)

    def _apply_for_adapter(
        self, state: GameState, context: ActionContext, action: LegalAction
    ) -> GameState:
        if (
            context.mode != PRODUCTION_BASIC_CARDS_MODE
            or context.phase != self.phase.value
        ):
            raise ProductionBatchError(
                "行动上下文与生产批处理会话当前阶段不一致"
            )
        operation = str(action.payload.get("operation", ""))

        if self.phase is ProductionPhase.PREPARE:
            if action.action_type is ActionType.PASS and operation == (
                "proceed_prepare"
            ):
                return self.apply_proceed_prepare(state, context, action)
            raise InvalidActionError("准备阶段只能推进判定阶段")

        if self.phase is ProductionPhase.JUDGMENT:
            if action.action_type is ActionType.PASS and operation == (
                "proceed_judgment"
            ):
                return self.apply_proceed_judgment(state, context, action)
            raise InvalidActionError("判定阶段只能推进判定结算")

        if self.phase is ProductionPhase.DRAW:
            if action.action_type is ActionType.PASS and operation == (
                "proceed_draw"
            ):
                return self.apply_proceed_draw(state, context, action)
            raise InvalidActionError("摸牌阶段只能推进摸牌")

        if self.phase is ProductionPhase.JUDGMENT_WUXIE:
            if operation == "use_wuxie":
                return self._formal_registry.adapter_for(
                    "sgs_trick_wuxiekeji"
                ).apply_action(state, context, action)
            if action.action_type is ActionType.PASS and operation == (
                "pass_judgment_wuxie"
            ):
                return self.apply_pass_trick_response(state, context, action)
            raise InvalidActionError("判定无懈窗口不支持当前动作")

        if self.phase is ProductionPhase.PLAY:
            if operation == "use_slash":
                adapter = self._adapter_for_action(state, action)
                return adapter.apply_action(state, context, action)
            if operation == "heal_self":
                return self._formal_registry.adapter_for(
                    "sgs_basic_tao"
                ).apply_action(state, context, action)
            if operation == "use_wine_buff":
                return self._formal_registry.adapter_for(
                    "sgs_basic_jiu"
                ).apply_action(state, context, action)
            if operation == "use_wuzhong":
                return self._formal_registry.adapter_for(
                    "sgs_trick_wuzhongshengyou"
                ).apply_action(state, context, action)
            if operation == "use_guohe":
                return self._formal_registry.adapter_for(
                    "sgs_trick_guohechaiqiao"
                ).apply_action(state, context, action)
            if operation == "use_shunshou":
                return self._formal_registry.adapter_for(
                    "sgs_trick_shunshouqianyang"
                ).apply_action(state, context, action)
            if operation == "use_duel":
                return self._formal_registry.adapter_for(
                    "sgs_trick_juedou"
                ).apply_action(state, context, action)
            if operation == "use_fire_attack":
                return self._formal_registry.adapter_for(
                    "sgs_trick_huogong"
                ).apply_action(state, context, action)
            if operation == "use_nanman":
                return self._formal_registry.adapter_for(
                    "sgs_trick_nanmanruqin"
                ).apply_action(state, context, action)
            if operation == "use_wanjian":
                return self._formal_registry.adapter_for(
                    "sgs_trick_wanjianqifa"
                ).apply_action(state, context, action)
            if operation == "use_taoyuan":
                return self._formal_registry.adapter_for(
                    "sgs_trick_taoyuanjieyi"
                ).apply_action(state, context, action)
            if operation == "use_tiesuo":
                return self._formal_registry.adapter_for(
                    "sgs_trick_tiesuolianhuan"
                ).apply_action(state, context, action)
            if operation == "recast_tiesuo":
                return self._formal_registry.adapter_for(
                    "sgs_trick_tiesuolianhuan"
                ).apply_action(state, context, action)
            if operation == "use_wugu":
                return self._formal_registry.adapter_for(
                    "sgs_trick_wugufengdeng"
                ).apply_action(state, context, action)
            if operation == "use_jiedao":
                return self._formal_registry.adapter_for(
                    "sgs_trick_jiedaosharen"
                ).apply_action(state, context, action)
            if operation == "use_weapon":
                return self._formal_registry.adapter_for(
                    action.payload.get("card_key", "")
                ).apply_action(state, context, action)
            if operation == "use_armor":
                return self._formal_registry.adapter_for(
                    action.payload.get("card_key", "")
                ).apply_action(state, context, action)
            if operation == "use_mount":
                return self._formal_registry.adapter_for(
                    action.payload.get("card_key", "")
                ).apply_action(state, context, action)
            if operation in (
                "use_lebusi",
                "use_bingliang",
                "use_shandian",
            ):
                return self._formal_registry.adapter_for(
                    action.payload.get("card_key", "")
                ).apply_action(state, context, action)
            if action.action_type is ActionType.PASS and operation == (
                "end_play_phase"
            ):
                return self._apply_end_play_phase(state, context, action)
            raise InvalidActionError(
                "出牌阶段不支持当前动作；动作未经过合法枚举或已过期"
            )

        if self.phase is ProductionPhase.END:
            if action.action_type is ActionType.PASS and operation == "end_turn":
                return self._apply_end_turn(state, context, action)
            raise InvalidActionError("结束阶段只能结束回合")

        if self.phase is ProductionPhase.DISCARD:
            if operation == "select_discard_card":
                return self.apply_select_discard_card(state, context, action)
            if operation == "unselect_discard_card":
                return self.apply_unselect_discard_card(state, context, action)
            if operation == "discard_phase_submit":
                return self.apply_discard_phase_submit(state, context, action)
            raise InvalidActionError("弃牌阶段只支持选择与提交批量弃牌动作")

        if self.phase is ProductionPhase.WEAPON_AFTER_DAMAGE:
            if operation == "weapon_discard_mount":
                return self.apply_weapon_discard_mount(state, context, action)
            if operation == "pass_weapon_choice":
                return self.apply_pass_weapon_choice(state, context, action)
            raise InvalidActionError("武器触发选择阶段只支持弃坐骑或放弃")

        if self.phase is ProductionPhase.WEAPON_SLASH_CHOICE:
            if operation == "weapon_force_hit":
                return self.apply_weapon_force_hit(state, context, action)
            if operation == "weapon_prevent_damage":
                return self.apply_weapon_prevent_damage(state, context, action)
            if operation == "qinglong_use_slash":
                return self.apply_qinglong_continue_slash(
                    state, context, action
                )
            if operation == "pass_weapon_choice":
                return self.apply_pass_weapon_slash_choice(
                    state, context, action
                )
            raise InvalidActionError("被闪后/伤害前武器选择阶段只支持发动或放弃")

        if self.phase is ProductionPhase.WEAPON_DISCARD_TWO:
            if operation == "select_discard_two":
                return self.apply_select_discard_two(state, context, action)
            if operation == "unselect_discard_two":
                return self.apply_unselect_discard_two(state, context, action)
            if operation == "discard_two_submit":
                return self.apply_discard_two_submit(state, context, action)
            raise InvalidActionError("弃2张窗口只支持选择、取消与提交")

        if self.phase is ProductionPhase.HANBING_DISCARD:
            if operation == "hanbing_discard_card":
                return self.apply_hanbing_discard_card(state, context, action)
            raise InvalidActionError("寒冰剑逐张弃置窗口只支持选择并弃置一张牌")

        if self.phase is ProductionPhase.SLASH_RESPONSE:
            if operation == "play_dodge":
                return self._formal_registry.adapter_for(
                    "sgs_basic_shan"
                ).apply_action(state, context, action)
            if operation == "activate_bagua":
                return self._formal_registry.adapter_for(
                    "sgs_armor_baguazhen"
                ).apply_action(state, context, action)
            if action.action_type is ActionType.PASS and operation == (
                "pass_slash_response"
            ):
                return self.apply_slash_damage(state, context, action)
            raise InvalidActionError("【杀】响应阶段不支持当前动作")

        if self.phase is ProductionPhase.TRICK_RESPONSE:
            if operation == "use_wuxie":
                return self._formal_registry.adapter_for(
                    "sgs_trick_wuxiekeji"
                ).apply_action(state, context, action)
            if action.action_type is ActionType.PASS and operation == (
                "pass_trick_response"
            ):
                return self.apply_pass_trick_response(state, context, action)
            raise InvalidActionError("锦囊响应阶段不支持当前动作")

        if self.phase is ProductionPhase.DYING_RESCUE:
            if operation == "rescue_with_peach":
                return self._formal_registry.adapter_for(
                    "sgs_basic_tao"
                ).apply_action(state, context, action)
            if operation == "rescue_with_wine":
                return self._formal_registry.adapter_for(
                    "sgs_basic_jiu"
                ).apply_action(state, context, action)
            if action.action_type is ActionType.PASS and operation == (
                "pass_rescue"
            ):
                return self.apply_pass_rescue(state, context, action)
            raise InvalidActionError("濒死救援阶段不支持当前动作")

        if self.phase is ProductionPhase.ZONE_CHOICE:
            if operation == "choose_target_zone_card":
                choice = self._runtime.pending_zone_choice
                if choice is None:
                    raise InvalidActionError("当前没有打开的目标区域选牌窗口")
                return self._formal_registry.adapter_for(
                    choice.trick_key
                ).apply_action(state, context, action)
            raise InvalidActionError("目标区域选牌阶段不支持当前动作")

        if self.phase is ProductionPhase.DUEL_RESPONSE:
            if operation == "play_slash_for_duel":
                return self._formal_registry.adapter_for(
                    "sgs_trick_juedou"
                ).apply_action(state, context, action)
            if action.action_type is ActionType.PASS and operation == (
                "pass_duel_slash"
            ):
                return self.apply_pass_duel_slash(state, context, action)
            raise InvalidActionError("【决斗】响应阶段不支持当前动作")

        if self.phase is ProductionPhase.FIRE_ATTACK_REVEAL:
            if operation == "reveal_card_for_fire_attack":
                return self._formal_registry.adapter_for(
                    "sgs_trick_huogong"
                ).apply_action(state, context, action)
            raise InvalidActionError("【火攻】展示阶段不支持当前动作")

        if self.phase is ProductionPhase.FIRE_ATTACK_DISCARD:
            if operation == "discard_same_suit_for_fire_attack":
                return self._formal_registry.adapter_for(
                    "sgs_trick_huogong"
                ).apply_action(state, context, action)
            if action.action_type is ActionType.PASS and operation == (
                "pass_fire_attack_discard"
            ):
                return self.apply_pass_fire_attack_discard(
                    state, context, action
                )
            raise InvalidActionError("【火攻】弃牌阶段不支持当前动作")

        if self.phase is ProductionPhase.NANMAN_RESPONSE:
            if operation == "play_slash_for_nanman":
                return self._formal_registry.adapter_for(
                    "sgs_trick_nanmanruqin"
                ).apply_action(state, context, action)
            if action.action_type is ActionType.PASS and operation == (
                "pass_nanman_slash"
            ):
                return self.apply_pass_nanman_slash(state, context, action)
            raise InvalidActionError("【南蛮入侵】响应阶段不支持当前动作")

        if self.phase is ProductionPhase.WANJIAN_RESPONSE:
            if operation == "play_jink_for_wanjian":
                return self._formal_registry.adapter_for(
                    "sgs_trick_wanjianqifa"
                ).apply_action(state, context, action)
            if operation == "activate_bagua":
                return self._formal_registry.adapter_for(
                    "sgs_armor_baguazhen"
                ).apply_action(state, context, action)
            if action.action_type is ActionType.PASS and operation == (
                "pass_wanjian_jink"
            ):
                return self.apply_pass_wanjian_jink(state, context, action)
            raise InvalidActionError("【万箭齐发】响应阶段不支持当前动作")

        if self.phase is ProductionPhase.WUGU_PICK:
            if operation == "pick_wugu_card":
                return self._formal_registry.adapter_for(
                    "sgs_trick_wugufengdeng"
                ).apply_action(state, context, action)
            raise InvalidActionError("五谷选牌阶段不支持当前动作")

        if self.phase is ProductionPhase.BORROWED_SWORD_CHOICE:
            if operation in (
                "choose_borrowed_sword_slash",
                "refuse_borrowed_sword_slash",
            ):
                return self._formal_registry.adapter_for(
                    "sgs_trick_jiedaosharen"
                ).apply_action(state, context, action)
            raise InvalidActionError("借刀选牌阶段不支持当前动作")

        raise ProductionBatchError(
            f"阶段{self.phase.value!r}不能应用动作"
        )

    def _adapter_for_action(
        self, state: GameState, action: LegalAction
    ) -> SlashAdapter:
        if action.card_instance_id is None:
            raise InvalidActionError("卡牌动作必须指定实体牌")
        if str(action.card_instance_id).startswith("virtual:"):
            # 丈八蛇矛虚拟杀：不是实体牌，卡牌键由动作负载提供。
            card_key = str(action.payload.get("card_key", ""))
        else:
            card_key = state.cards_by_id[action.card_instance_id].card_key
        adapter = self._formal_registry.adapter_for(card_key)
        if not isinstance(adapter, SlashAdapter):
            raise InvalidActionError(
                f"实体牌{action.card_instance_id!r}不是本批次【杀】"
            )
        return adapter

    def _build_window(self, runtime: _BatchRuntime) -> ResponseWindow:
        if (
            runtime.response_window_id is None
            or not runtime.response_window_order
        ):
            raise ProductionBatchError("当前阶段没有已建立的响应窗口")
        source = None
        if runtime.response_window_source_sequence is not None:
            for event in self._events.snapshot():
                if event.sequence == runtime.response_window_source_sequence:
                    source = event
                    break
            if source is None:
                raise ProductionBatchError(
                    "响应窗口的来源事件不存在，状态或回放异常"
                )
        return ResponseWindow(
            responder_order=runtime.response_window_order,
            window_id=runtime.response_window_id,
            source_event=source,
            close_on_first_response=True,
            allowed_event_types=(EventType.CARD_USED,),
        )

    def _commit_runtime(
        self, previous: _BatchRuntime, next_runtime: _BatchRuntime
    ) -> None:
        previous_entry = (
            previous.turn_number,
            previous.current_player_id,
            previous.phase,
        )
        next_entry = (
            next_runtime.turn_number,
            next_runtime.current_player_id,
            next_runtime.phase,
        )
        self._runtime = next_runtime
        if next_entry != previous_entry:
            self._phase_history.append(
                BatchPhaseEntry(
                    next_runtime.turn_number,
                    next_runtime.current_player_id,
                    next_runtime.phase,
                )
            )

    def _return_to_play(self, runtime: _BatchRuntime) -> _BatchRuntime:
        return replace(
            runtime,
            phase=ProductionPhase.PLAY,
            pending_slash=None,
            pending_trick=None,
            trick_effect_active=False,
            trick_consecutive_passes=0,
            trick_response_order=(),
            trick_response_index=0,
            trick_decision_count=0,
            trick_direct_response_to=None,
            pending_dying_id=None,
            rescue_order=(),
            rescue_index=0,
            rescue_decision_count=0,
            response_window_id=None,
            response_window_order=(),
            response_window_source_sequence=None,
            pending_zone_choice=None,
            zone_choice_handles=MappingProxyType({}),
            pending_duel=None,
            pending_fire_attack=None,
            fire_attack_reveal_handles=MappingProxyType({}),
            pending_group_trick=None,
            group_response_handles=MappingProxyType({}),
            group_response_snapshot_digest=None,
            pending_wugu=None,
            borrowed_sword_slash_handles=MappingProxyType({}),
            borrowed_sword_slash_snapshot_digest=None,
            defer_damage_card_finish=False,
            pending_damage_card_id=None,
            pending_damage_source_id=None,
            pending_damage_kill_credit=None,
            pending_damage_rescue_reason=None,
            pending_damage_death_reason=None,
            pending_chain=None,
            discard_phase_window_id=None,
            discard_phase_selected_ids=(),
            discard_phase_handles=MappingProxyType({}),
            discard_phase_snapshot_digest=None,
            pending_weapon_choice=None,
            pending_slash_choice=None,
            pending_discard_two=None,
            pending_hanbing_discard=None,
            damage_card_already_finished=False,
        )

    # ------------------------------------------------------------------
    # 属性伤害传导（CP-04J）：统一入口、挂起、恢复与确定性清理
    # ------------------------------------------------------------------

    def _chain_started_event(
        self, chain: _PendingChainDamage
    ) -> GameEvent:
        return GameEvent(
            event_type=EventType.CHAIN_DAMAGE_STARTED,
            card_instance_id=chain.root_card_instance_id,
            card_key=chain.root_card_key,
            card_user=chain.root_card_user,
            damage_source=chain.root_damage_source_id,
            target_ids=(chain.original_target_id,),
            payload={
                "root_damage_event_id": chain.root_damage_event_id,
                "source_id": chain.root_damage_source_id,
                "original_target_id": chain.original_target_id,
                "damage_type": chain.damage_type,
                "root_card_instance_id": chain.root_card_instance_id,
                "chain_base_damage": chain.chain_base_damage,
                "candidate_order": list(chain.candidate_order),
            },
        )

    def _chain_target_resolved_event(
        self,
        chain: _PendingChainDamage,
        target_id: str,
        target_index: int,
        result: str,
        *,
        actual_damage: int,
        chained_old: bool,
        chained_new: bool,
    ) -> GameEvent:
        return GameEvent(
            event_type=EventType.CHAIN_TARGET_RESOLVED,
            card_instance_id=chain.root_card_instance_id,
            card_key=chain.root_card_key,
            card_user=chain.root_card_user,
            damage_source=chain.root_damage_source_id,
            target_ids=(target_id,),
            payload={
                "root_damage_event_id": chain.root_damage_event_id,
                "target_id": target_id,
                "target_index": target_index,
                "result": result,
                "chain_base_damage": chain.chain_base_damage,
                "actual_damage": actual_damage,
                "chained_old": chained_old,
                "chained_new": chained_new,
            },
        )

    def _chain_finished_event(
        self,
        chain: _PendingChainDamage,
        processed_targets: Sequence[str],
        skipped_targets: Sequence[str],
        stop_reason: str,
    ) -> GameEvent:
        return GameEvent(
            event_type=EventType.CHAIN_DAMAGE_FINISHED,
            card_instance_id=chain.root_card_instance_id,
            card_key=chain.root_card_key,
            card_user=chain.root_card_user,
            damage_source=chain.root_damage_source_id,
            target_ids=(chain.original_target_id,),
            payload={
                "root_damage_event_id": chain.root_damage_event_id,
                "processed_targets": list(processed_targets),
                "skipped_targets": list(skipped_targets),
                "stop_reason": stop_reason,
            },
        )

    def _begin_chain(
        self,
        state: GameState,
        runtime: _BatchRuntime,
        *,
        victim_id: str,
        damage_type: str,
        chain_base_damage: int,
        card_instance_id: str,
        card_key: str,
        card_user: str,
        source_id: str | None,
        root_damage_event_id: int,
    ) -> tuple[GameState, _BatchRuntime]:
        """原始角色实际受到大于0点属性伤害后解除横置并建立传导根。"""

        victim = state.players_by_id[victim_id]
        if not _chain_trigger_conditions(
            damage_type, victim.chained, chain_base_damage
        ):
            return state, runtime
        next_state = _replace_player(state, victim_id, chained=False)
        candidate_order = _ordered_chain_candidate_ids(
            next_state.players, runtime.current_player_id, victim_id
        )
        chain = _PendingChainDamage(
            root_damage_event_id=str(root_damage_event_id),
            root_damage_source_id=source_id,
            root_card_instance_id=card_instance_id,
            root_card_key=card_key,
            root_card_user=card_user,
            damage_type=damage_type,
            chain_base_damage=chain_base_damage,
            original_target_id=victim_id,
            candidate_order=candidate_order,
            session_id=self._session_id,
        )
        self._events.extend(
            (
                GameEvent(
                    event_type=EventType.CHAINED_STATE,
                    card_instance_id=card_instance_id,
                    card_key=card_key,
                    card_user=card_user,
                    target_ids=(victim_id,),
                    payload={
                        "old_value": True,
                        "new_value": False,
                        "reason": "chain_damage_original_unchained",
                        "root_damage_event_id": str(root_damage_event_id),
                    },
                ),
                self._chain_started_event(chain),
            )
        )
        return next_state, replace(runtime, pending_chain=chain)

    def _apply_damage_and_maybe_chain(
        self,
        state: GameState,
        runtime: _BatchRuntime,
        *,
        victim_id: str,
        amount: int,
        damage_type: str,
        card_instance_id: str,
        card_key: str,
        card_user: str | None,
        source_id: str | None,
        kill_credit: str | None,
        payload: Mapping[str, object] | None = None,
        resolved_reason: str,
        death_reason: str,
        rescue_reason: str,
        defer_root_finish: bool = False,
        ignore_armor: bool = False,
        weapon_choice: tuple[str, str, int] | None = None,
        card_already_finished: bool = False,
    ) -> tuple[GameState, _BatchRuntime]:
        """统一正式伤害管线：原始伤害、横置解除、传导根与濒死挂起。

        ``defer_root_finish`` 供闪电等根牌使用：根牌完成时点由
        ``_complete_root_resolution`` 控制（传导/濒死子结算完成后再弃置），
        避免在传导开始前提前弃置本体。``ignore_armor`` 表示目标防具无效（armor invalid）上下文，
        上下文（统一接口，本批无真实武器调用者），修正顺序由统一
        ``resolve_armor_damage`` 决定并进入事件审计。"""

        victim = state.players_by_id[victim_id]
        resolution = resolve_armor_damage(
            state,
            victim_id=victim_id,
            damage_type=damage_type,
            declared_amount=amount,
            ignore_armor=ignore_armor,
        )
        amount = resolution.final_amount
        if amount == 0:
            # 最终伤害为0：不扣减HP、不进入濒死、不触发传导；记录统一
            # 防止事件并按根牌完成出口收尾（不产生 damage 事件）。
            prevented_event = GameEvent(
                event_type=EventType.DAMAGE_PREVENTED,
                card_instance_id=card_instance_id,
                card_key=card_key,
                card_user=card_user,
                target_ids=(victim_id,),
                payload={
                    "victim_id": victim_id,
                    "card_key": card_key,
                    "declared_amount": resolution.declared_amount,
                    "final_amount": 0,
                    "modifiers": list(resolution.modifiers),
                    "armor_ignored": resolution.armor_ignored,
                },
            )
            self._events.extend((prevented_event,))
            # R1-NEW-002：非 damage 路径（防止/无效）在本次 resolution
            # 结束即清除青釭剑防具无效状态（Hanbing prevention 等各自
            # resolution 结束时清理，不跨结算泄漏）。
            if runtime.pending_slash is not None:
                runtime = replace(
                    runtime,
                    pending_slash=replace(
                        runtime.pending_slash, ignore_armor=False
                    ),
                )
            if defer_root_finish:
                if runtime.pending_chain is not None:
                    return self._advance_chain(state, runtime)
                return self._complete_root_resolution(state, runtime)
            if not card_already_finished:
                next_state, finish_event = self._finish_slash_processing(
                    state, runtime, card_instance_id, resolved_reason
                )
                if finish_event is not None:
                    self._events.extend((finish_event,))
            else:
                next_state = state
            if runtime.pending_chain is not None:
                return self._advance_chain(next_state, runtime)
            return self._complete_root_resolution(next_state, runtime)
        if weapon_choice is not None:
            # CP-04P 麒麟弓（USER_CONFIRMED_MOBILE_RULE＋IN_GAME_CARD_TEXT_
            # CONFIRMED，2026-08-08 用户移动版卡面文本与牌局记录确认）：本次
            # 【杀】确定将造成伤害（防具解析后 final_amount>0）时，在 HP 扣减
            # 与 DAMAGE event 之前打开麒麟弓触发窗口；弃置坐骑/放弃完成后，
            # 由 _continue_after_weapon_choice 执行真正的伤害结算（HP扣减→
            # DAMAGE→濒死/传导/根牌）。不再把麒麟弓放在 HP 已扣、DAMAGE
            # 已生成之后。
            weapon_key, choice_target = weapon_choice
            pending = _PendingWeaponChoice(
                weapon_key=weapon_key,
                kind="qilingong_discard_mount",
                attacker_id=card_user or "",
                target_id=choice_target,
                slash_instance_id=card_instance_id,
                damage_event_id=None,
                window_id=(
                    f"weapon-after-damage:{runtime.turn_number}:"
                    f"{card_instance_id}"
                ),
                # R1-NEW-001：使用统一防具解析后的 authoritative final
                # amount（amount 已由 resolution.final_amount 覆盖），
                # 不使用上游 pre-armor base amount；窗口关闭后按同一
                # resolved final amount 执行 HP/DAMAGE。
                damage_amount=amount,
                damage_type=damage_type,
                card_key=card_key,
                card_user=card_user,
                source_id=source_id,
                kill_credit=kill_credit,
                resolved_reason=resolved_reason,
                death_reason=death_reason,
                rescue_reason=rescue_reason,
                defer_root_finish=defer_root_finish,
                declared_amount=resolution.declared_amount,
                modifiers=tuple(resolution.modifiers),
                armor_ignored=resolution.armor_ignored,
                extra_payload=MappingProxyType(dict(payload or {})),
            )
            return state, replace(
                runtime,
                phase=ProductionPhase.WEAPON_AFTER_DAMAGE,
                pending_weapon_choice=pending,
            )
        return self._apply_resolved_damage_and_settle(
            state,
            runtime,
            victim_id=victim_id,
            amount=amount,
            damage_type=damage_type,
            card_instance_id=card_instance_id,
            card_key=card_key,
            card_user=card_user,
            source_id=source_id,
            kill_credit=kill_credit,
            payload=payload,
            resolution=resolution,
            resolved_reason=resolved_reason,
            death_reason=death_reason,
            rescue_reason=rescue_reason,
            defer_root_finish=defer_root_finish,
            card_already_finished=card_already_finished,
        )

    def _apply_resolved_damage_and_settle(
        self,
        state: GameState,
        runtime: _BatchRuntime,
        *,
        victim_id: str,
        amount: int,
        damage_type: str,
        card_instance_id: str,
        card_key: str,
        card_user: str | None,
        source_id: str | None,
        kill_credit: str | None,
        payload: Mapping[str, object] | None,
        resolution: ArmorDamageResolution,
        resolved_reason: str,
        death_reason: str,
        rescue_reason: str,
        defer_root_finish: bool,
        card_already_finished: bool,
    ) -> tuple[GameState, _BatchRuntime]:
        """真正伤害结算：HP 扣减 → DAMAGE event → 濒死/传导/根牌收尾。

        普通杀伤害与麒麟弓窗口关闭后共用本路径，保证 DAMAGE event 永远
        在 HP 扣减时产生，且麒麟弓相关坐骑移动/失牌事件先于 DAMAGE。"""

        victim = state.players_by_id[victim_id]
        next_state = _replace_player(state, victim_id, hp=victim.hp - amount)
        damage_event = DamageEvent(
            target_id=victim_id,
            amount=amount,
            damage_type=damage_type,
            card_instance_id=card_instance_id,
            card_key=card_key,
            card_user=card_user,
            damage_source=source_id,
            kill_credit=kill_credit,
            payload={
                **(dict(payload or {})),
                "declared_amount": resolution.declared_amount,
                "final_amount": amount,
                "modifiers": list(resolution.modifiers),
                "armor_ignored": resolution.armor_ignored,
            },
        )
        (damage_event,) = self._events.extend((damage_event,))
        # R1-NEW-002：青釭剑防具无效状态在本次 damage 真正完成（HP 扣减＋
        # DAMAGE event 产生）之后清除，早于 dying/after-damage/follow-up
        # 正式效果边界（Knowledge 7.2.1：终点B=本次伤害结算完成，清除后
        # 防具恢复）。麒麟弓窗口期间防具无效状态保持（窗口在 damage 真正
        # 发生之前打开），不再出现“damage 尚未发生、armor-invalid 已被
        # 清除”的可观察状态机阶段。
        if runtime.pending_slash is not None:
            runtime = replace(
                runtime,
                pending_slash=replace(
                    runtime.pending_slash, ignore_armor=False
                ),
            )
        return self._settle_after_damage(
            next_state,
            runtime,
            victim_id=victim_id,
            card_instance_id=card_instance_id,
            card_key=card_key,
            card_user=card_user,
            source_id=source_id,
            kill_credit=kill_credit,
            damage_type=damage_type,
            amount=amount,
            damage_event_sequence=damage_event.sequence,
            resolved_reason=resolved_reason,
            death_reason=death_reason,
            rescue_reason=rescue_reason,
            defer_root_finish=defer_root_finish,
            card_already_finished=card_already_finished,
        )

    def _settle_after_damage(
        self,
        state: GameState,
        runtime: _BatchRuntime,
        *,
        victim_id: str,
        card_instance_id: str,
        card_key: str,
        card_user: str | None,
        source_id: str | None,
        kill_credit: str | None,
        damage_type: str,
        amount: int,
        damage_event_sequence: int | None,
        resolved_reason: str,
        death_reason: str,
        rescue_reason: str,
        defer_root_finish: bool,
        card_already_finished: bool = False,
    ) -> tuple[GameState, _BatchRuntime]:
        """伤害事件后的统一收尾：横置解除传导、濒死挂起、根牌完成。"""

        next_state = state
        next_runtime = runtime
        victim = next_state.players_by_id[victim_id]
        if _chain_trigger_conditions(damage_type, victim.chained, amount):
            next_state, next_runtime = self._begin_chain(
                next_state,
                runtime,
                victim_id=victim_id,
                damage_type=damage_type,
                chain_base_damage=amount,
                card_instance_id=card_instance_id,
                card_key=card_key,
                card_user=card_user,
                source_id=source_id,
                root_damage_event_id=damage_event_sequence,
            )
        runtime = next_runtime
        if next_state.players_by_id[victim_id].hp <= 0:
            dying_event = GameEvent(
                event_type=EventType.DYING,
                damage_source=source_id,
                kill_credit=kill_credit,
                target_ids=(victim_id,),
            )
            self._events.extend((dying_event,))
            dying_sequence = self._events.snapshot()[-1].sequence
            assert dying_sequence is not None
            rescue_order = (
                runtime.current_player_id,
                self.opponent_of(runtime.current_player_id),
            )
            return next_state, replace(
                runtime,
                phase=ProductionPhase.DYING_RESCUE,
                pending_dying_id=victim_id,
                rescue_order=rescue_order,
                rescue_index=0,
                rescue_decision_count=0,
                response_window_id=(
                    f"dying:{runtime.turn_number}:{victim_id}"
                    ":seat0:dec0"
                ),
                response_window_order=(rescue_order[0],),
                response_window_source_sequence=dying_sequence,
                pending_damage_card_id=card_instance_id,
                pending_damage_source_id=source_id,
                pending_damage_kill_credit=kill_credit,
                pending_damage_rescue_reason=rescue_reason,
                pending_damage_death_reason=death_reason,
                defer_damage_card_finish=defer_root_finish,
                damage_card_already_finished=(
                    card_already_finished
                    or (
                        runtime.pending_slash is not None
                        and runtime.pending_slash.virtual
                        and runtime.pending_slash.slash_instance_id
                        == card_instance_id
                    )
                ),
            )
        if defer_root_finish:
            # 根牌（闪电）完成时点由 _complete_root_resolution 控制
            if runtime.pending_chain is not None:
                return self._advance_chain(next_state, runtime)
            return self._complete_root_resolution(next_state, runtime)
        if not card_already_finished:
            next_state, finish_event = self._finish_slash_processing(
                next_state, runtime, card_instance_id, resolved_reason
            )
            if finish_event is not None:
                self._events.extend((finish_event,))
        if runtime.pending_chain is not None:
            return self._advance_chain(next_state, runtime)
        return self._complete_root_resolution(next_state, runtime)

    def apply_weapon_discard_mount(
        self,
        state: GameState,
        context: ActionContext,
        action: LegalAction,
    ) -> GameState:
        """CP-04P 麒麟弓：弃置目标装备区一张坐骑牌并恢复伤害后结算。"""

        runtime = self._runtime
        if runtime.phase is not ProductionPhase.WEAPON_AFTER_DAMAGE:
            raise InvalidActionError("只有武器触发选择阶段可以弃置坐骑")
        choice = runtime.pending_weapon_choice
        if choice is None or choice.kind != "qilingong_discard_mount":
            raise InvalidActionError("当前没有可弃坐骑的麒麟弓触发窗口")
        if context.actor_id != choice.attacker_id:
            raise InvalidActionError("只有武器持有者可以发动麒麟弓")
        if action.payload.get("window_id") != choice.window_id:
            raise InvalidActionError("弃坐骑动作不属于当前武器触发窗口")
        if action.card_instance_id is None:
            raise InvalidActionError("麒麟弓必须指定目标装备区的一张坐骑牌")
        if action.card_instance_id not in (
            state.card_ids_in(
                ZoneRef.equipment(choice.target_id, "attack_horse")
            )
            + state.card_ids_in(
                ZoneRef.equipment(choice.target_id, "defense_horse")
            )
        ):
            raise InvalidActionError("只能弃置目标装备区中的坐骑牌")
        card_key = _card_key(state, action.card_instance_id)
        next_state = state.move_card(action.card_instance_id, DISCARD_PILE)
        self._events.extend(
            (
                GameEvent(
                    event_type=EventType.CARD_MOVED,
                    card_instance_id=action.card_instance_id,
                    card_key=card_key,
                    card_user=context.actor_id,
                    payload={
                        "source": _zone_payload(
                            state.location_of(action.card_instance_id)
                        ),
                        "destination": _zone_payload(DISCARD_PILE),
                        "reason": "qilingong_mount_discard",
                        "window_id": choice.window_id,
                    },
                ),
                GameEvent(
                    event_type=EventType.CARD_LOST,
                    card_instance_id=action.card_instance_id,
                    card_key=card_key,
                    target_ids=(choice.target_id,),
                    payload={
                        "reason": "qilingong_mount_discard",
                        "source_zone": _zone_id(
                            state.location_of(action.card_instance_id)
                        ),
                    },
                ),
                GameEvent(
                    event_type=EventType.CARD_DISCARDED,
                    card_instance_id=action.card_instance_id,
                    card_key=card_key,
                    card_user=context.actor_id,
                    target_ids=(choice.target_id,),
                    payload={
                        "reason": "qilingong_mount_discard",
                        "source_zone": _zone_id(
                            state.location_of(action.card_instance_id)
                        ),
                    },
                ),
            )
        )
        next_state, next_runtime = self._continue_after_weapon_choice(
            next_state, runtime
        )
        self._commit_runtime(runtime, next_runtime)
        return next_state

    def apply_pass_weapon_choice(
        self,
        state: GameState,
        context: ActionContext,
        action: LegalAction,
    ) -> GameState:
        """放弃武器触发选择并恢复伤害后结算。"""

        runtime = self._runtime
        if runtime.phase is not ProductionPhase.WEAPON_AFTER_DAMAGE:
            raise InvalidActionError("只有武器触发选择阶段可以放弃")
        choice = runtime.pending_weapon_choice
        if choice is None:
            raise InvalidActionError("当前没有武器触发窗口")
        if context.actor_id != choice.attacker_id:
            raise InvalidActionError("只有武器持有者可以放弃武器触发窗口")
        if action.payload.get("window_id") != choice.window_id:
            raise InvalidActionError("放弃动作不属于当前武器触发窗口")
        next_state, next_runtime = self._continue_after_weapon_choice(
            state, runtime
        )
        self._commit_runtime(runtime, next_runtime)
        return next_state

    def _continue_after_weapon_choice(
        self,
        state: GameState,
        runtime: _BatchRuntime,
    ) -> tuple[GameState, _BatchRuntime]:
        """武器触发选择窗口关闭后，用挂起参数执行真正伤害结算。

        麒麟弓窗口在 HP 扣减与 DAMAGE event 之前打开；窗口关闭（弃坐骑或
        放弃）后，这里才执行 HP 扣减 → DAMAGE event → 濒死/传导/根牌收尾，
        保证麒麟弓相关坐骑移动/失牌事件先于 DAMAGE（USER_CONFIRMED_MOBILE_
        RULE＋IN_GAME_CARD_TEXT_CONFIRMED）。"""

        choice = runtime.pending_weapon_choice
        if choice is None:
            raise ProductionBatchError("武器触发选择缺少挂起状态")
        resolution = ArmorDamageResolution(
            declared_amount=choice.declared_amount,
            final_amount=choice.damage_amount,
            modifiers=choice.modifiers,
            prevented=choice.damage_amount == 0,
            armor_ignored=choice.armor_ignored,
        )
        next_state, next_runtime = self._apply_resolved_damage_and_settle(
            state,
            runtime,
            victim_id=choice.target_id,
            amount=choice.damage_amount,
            damage_type=choice.damage_type,
            card_instance_id=choice.slash_instance_id,
            card_key=choice.card_key,
            card_user=choice.card_user,
            source_id=choice.source_id,
            kill_credit=choice.kill_credit,
            payload=choice.extra_payload,
            resolution=resolution,
            resolved_reason=choice.resolved_reason,
            death_reason=choice.death_reason,
            rescue_reason=choice.rescue_reason,
            defer_root_finish=choice.defer_root_finish,
            card_already_finished=False,
        )
        return next_state, replace(
            next_runtime,
            pending_weapon_choice=None,
        )

    def _apply_chain_damage_to_target(
        self,
        state: GameState,
        runtime: _BatchRuntime,
        chain: _PendingChainDamage,
        target_id: str,
        *,
        amount: int | None = None,
    ) -> tuple[GameState, _BatchRuntime, _ChainStepOutcome]:
        """对当前合法候选应用一条独立传导伤害事件。

        返回明确的控制流结果：``continue_chain``／``chain_finished``／
        ``paused_for_rescue``。``amount`` 仅供状态机单元测试注入最终实际
        伤害（正式调用不传，自动按根基数计算），用于在没有减伤机制时验证
        ``prevented_zero`` 分支；注入负值一律拒绝。
        """

        if target_id in chain.processed_target_ids:
            raise ProductionBatchError("传导目标被重复处理")
        armor_resolution: ArmorDamageResolution | None = None
        if amount is None:
            base = _chain_recipient_base(chain.chain_base_damage, None)
            # 每名传导目标独立应用自身防具修正（藤甲火+1、白银狮子限伤）；
            # 局部变化只影响该角色，不改变后续候选使用的传导基础伤害。
            armor_resolution = resolve_armor_damage(
                state,
                victim_id=target_id,
                damage_type=chain.damage_type,
                declared_amount=base,
            )
            amount = armor_resolution.final_amount
        else:
            if isinstance(amount, bool) or not isinstance(amount, int):
                raise TypeError("注入的传导目标伤害必须是整数")
            if amount < 0:
                raise ValueError("注入的传导目标伤害不能为负数")
            armor_resolution = ArmorDamageResolution(
                declared_amount=amount,
                final_amount=amount,
                modifiers=(),
                prevented=amount == 0,
                armor_ignored=False,
            )
        victim = state.players_by_id[target_id]
        chained_old = victim.chained
        unchain, result = _chain_recipient_outcome(amount)
        if not unchain:
            # 最终伤害为0／被防止：不产生伤害事件，记录结果并结束传导根。
            self._events.extend(
                (
                    self._chain_target_resolved_event(
                        chain,
                        target_id,
                        chain.current_index,
                        result,
                        actual_damage=0,
                        chained_old=chained_old,
                        chained_new=chained_old,
                    ),
                )
            )
            finished_state, finished_runtime = self._finish_chain(
                state, runtime, stop_reason="prevented_zero"
            )
            return (
                finished_state,
                finished_runtime,
                _ChainStepOutcome.FINISHED,
            )

        if chain.root_card_key in SLASH_CARD_KEYS:
            check_weapon_skill_gate(
                state,
                actor_id=chain.root_card_user,
                decision="slash_damage",
                target_id=target_id,
            )
        next_state = _replace_player(state, target_id, hp=victim.hp - amount)
        damage_event = DamageEvent(
            target_id=target_id,
            amount=amount,
            damage_type=chain.damage_type,
            card_instance_id=chain.root_card_instance_id,
            card_key=chain.root_card_key,
            card_user=chain.root_card_user,
            damage_source=chain.root_damage_source_id,
            kill_credit=chain.root_damage_source_id,
            payload={
                "is_chain_transmitted": True,
                "root_damage_event_id": chain.root_damage_event_id,
                "chain_base_damage": chain.chain_base_damage,
                "chain_target_index": chain.current_index,
                "declared_amount": armor_resolution.declared_amount,
                "final_amount": amount,
                "modifiers": list(armor_resolution.modifiers),
                "armor_ignored": armor_resolution.armor_ignored,
            },
        )
        self._events.extend((damage_event,))
        if unchain:
            next_state = _replace_player(next_state, target_id, chained=False)
            self._events.extend(
                (
                    GameEvent(
                        event_type=EventType.CHAINED_STATE,
                        card_instance_id=chain.root_card_instance_id,
                        card_key=chain.root_card_key,
                        card_user=chain.root_card_user,
                        target_ids=(target_id,),
                        payload={
                            "old_value": chained_old,
                            "new_value": False,
                            "reason": "chain_damage_target_unchained",
                            "root_damage_event_id": (
                                chain.root_damage_event_id
                            ),
                        },
                    ),
                    self._chain_target_resolved_event(
                        chain,
                        target_id,
                        chain.current_index,
                        result,
                        actual_damage=amount,
                        chained_old=chained_old,
                        chained_new=False,
                    ),
                )
            )

        processed = chain.processed_target_ids + (target_id,)
        next_chain = replace(
            chain,
            processed_target_ids=processed,
            current_index=chain.current_index + 1,
            current_target_id=None,
            pause_reason=None,
        )
        next_runtime = replace(runtime, pending_chain=next_chain)
        if next_state.players_by_id[target_id].hp <= 0:
            dying_event = GameEvent(
                event_type=EventType.DYING,
                damage_source=chain.root_damage_source_id,
                kill_credit=chain.root_damage_source_id,
                target_ids=(target_id,),
            )
            self._events.extend((dying_event,))
            dying_sequence = self._events.snapshot()[-1].sequence
            assert dying_sequence is not None
            rescue_order = (
                runtime.current_player_id,
                self.opponent_of(runtime.current_player_id),
            )
            return next_state, replace(
                next_runtime,
                phase=ProductionPhase.DYING_RESCUE,
                pending_dying_id=target_id,
                rescue_order=rescue_order,
                rescue_index=0,
                rescue_decision_count=0,
                response_window_id=(
                    f"dying:{runtime.turn_number}:{target_id}"
                    ":seat0:dec0"
                ),
                response_window_order=(rescue_order[0],),
                response_window_source_sequence=dying_sequence,
                pending_damage_card_id=chain.root_card_instance_id,
                pending_damage_source_id=chain.root_damage_source_id,
                pending_damage_kill_credit=chain.root_damage_source_id,
                pending_damage_rescue_reason=(
                    "chain_damage_target_resolved_after_rescue"
                ),
                pending_damage_death_reason=(
                    "chain_damage_target_resolved_with_death"
                ),
                pending_chain=replace(
                    next_chain,
                    current_target_id=target_id,
                    pause_reason="recipient_dying",
                ),
            ), _ChainStepOutcome.PAUSED
        return next_state, next_runtime, _ChainStepOutcome.CONTINUE

    def _finish_chain(
        self,
        state: GameState,
        runtime: _BatchRuntime,
        *,
        stop_reason: str,
    ) -> tuple[GameState, _BatchRuntime]:
        """确定性结束传导根：记录结束原因并清理挂起状态。"""

        chain = runtime.pending_chain
        if chain is None:
            raise ProductionBatchError("当前没有可结束的传导根")
        processed = chain.processed_target_ids
        skipped = tuple(
            candidate
            for candidate in chain.candidate_order[: chain.current_index]
            if candidate not in processed
        )
        if stop_reason in ("prevented_zero", "winner"):
            skipped = skipped + tuple(
                chain.candidate_order[chain.current_index :]
            )
        self._events.extend(
            (self._chain_finished_event(chain, processed, skipped, stop_reason),)
        )
        next_runtime = replace(runtime, pending_chain=None)
        if stop_reason == "winner":
            return state, next_runtime
        return self._complete_root_resolution(state, next_runtime)

    def _advance_chain(
        self,
        state: GameState,
        runtime: _BatchRuntime,
        *,
        amount_override: int | None = None,
    ) -> tuple[GameState, _BatchRuntime]:
        """从挂起索引继续处理传导候选；濒死时挂起等待救援恢复。

        子调用返回 ``chain_finished`` 时立即返回（不再次进入循环、不重复
        产生结束事件）；返回 ``paused_for_rescue`` 时立即返回等待救援。
        ``amount_override`` 仅供状态机单元测试注入（prevented_zero 分支），
        正式调用不得传入。
        """

        while True:
            chain = runtime.pending_chain
            if chain is None:
                raise ProductionBatchError("当前没有挂起的传导根")
            if runtime.winner_id is not None or (
                runtime.phase is ProductionPhase.FINISHED
            ):
                return self._finish_chain(
                    state, runtime, stop_reason="winner"
                )
            if not chain.candidate_order:
                return self._finish_chain(
                    state, runtime, stop_reason="no_candidates"
                )
            if chain.current_index >= len(chain.candidate_order):
                return self._finish_chain(
                    state, runtime, stop_reason="completed"
                )
            target_id = chain.candidate_order[chain.current_index]
            target = state.players_by_id[target_id]
            skip_reason = _chain_dynamic_skip_reason(
                alive=target.alive, chained=target.chained
            )
            if skip_reason is not None:
                self._events.extend(
                    (
                        self._chain_target_resolved_event(
                            chain,
                            target_id,
                            chain.current_index,
                            skip_reason,
                            actual_damage=0,
                            chained_old=target.chained,
                            chained_new=target.chained,
                        ),
                    )
                )
                runtime = replace(
                    runtime,
                    pending_chain=replace(
                        chain,
                        current_index=chain.current_index + 1,
                        current_target_id=None,
                    ),
                )
                continue
            next_state, next_runtime, outcome = (
                self._apply_chain_damage_to_target(
                    state,
                    runtime,
                    chain,
                    target_id,
                    amount=amount_override,
                )
            )
            if outcome is _ChainStepOutcome.FINISHED:
                if next_runtime.pending_chain is not None:
                    raise ProductionBatchError(
                        "传导结束结果仍残留挂起状态"
                    )
                return next_state, next_runtime
            if outcome is _ChainStepOutcome.PAUSED:
                if (
                    next_runtime.pending_chain is None
                    or next_runtime.phase is not ProductionPhase.DYING_RESCUE
                ):
                    raise ProductionBatchError(
                        "传导暂停结果与挂起状态不一致"
                    )
                return next_state, next_runtime
            state, runtime = next_state, next_runtime

    def _resume_chain_after_rescue(
        self,
        state: GameState,
        runtime: _BatchRuntime,
        dying_id: str,
        *,
        rescued: bool,
    ) -> tuple[GameState, _BatchRuntime]:
        """濒死救援结束后恢复传导：原始角色先完成根牌结算再继续。"""

        chain = runtime.pending_chain
        if chain is None:
            raise ProductionBatchError("濒死救援完成但缺少传导挂起状态")
        if dying_id == chain.original_target_id:
            if (
                runtime.defer_damage_card_finish
                or runtime.damage_card_already_finished
            ):
                # 闪电等需要延迟根牌结算的伤害（CP-04L）：闪电本体在
                # PROCESSING 中等待完整传导与伤害结算结束后，由
                # _complete_root_resolution 统一弃置；此处不得提前 finish，
                # 否则传导结束后重复弃置会失败关闭。贯石斧强制命中时
                # 【杀】本体已因【闪】完成结算，同样不再重复 finish。
                next_state = state
            else:
                next_state, finish_event = self._finish_processing(
                    state,
                    self._pending_damage_card_id(runtime),
                    self._pending_damage_rescue_reason(runtime),
                )
                self._events.extend((finish_event,))
            return self._advance_chain(next_state, runtime)
        del rescued
        return self._advance_chain(state, runtime)

    # ------------------------------------------------------------------
    # 卡牌与阶段结算（全部经过适配器路由，绝不直接修改状态）
    # ------------------------------------------------------------------

    def apply_slash_use(
        self,
        state: GameState,
        context: ActionContext,
        action: LegalAction,
        adapter: SlashAdapter,
    ) -> GameState:
        runtime = self._runtime
        if runtime.phase is not ProductionPhase.PLAY:
            raise InvalidActionError("【杀】只能在出牌阶段使用")
        equipped_weapon = equipped_weapon_key(state, context.actor_id)
        if (
            runtime.slash_used_counts.get(context.actor_id, 0) > 0
            and equipped_weapon != "sgs_weapon_zhugeliannu"
        ):
            # CP-04P：诸葛连弩“你使用【杀】无次数限制”（Knowledge 7.1
            # 用户整理解释）豁免通常出牌阶段次数上限；其余武器不改变次数。
            raise InvalidActionError("本出牌阶段已经使用过【杀】，受次数限制")
        if action.card_instance_id is None or len(action.target_ids) != 1:
            raise InvalidActionError("【杀】必须指定一张实体牌和恰好一名目标")
        # CP-04P 丈八蛇矛（7.8 当前确认）：两张手牌当作普通【杀】使用。
        # 虚拟杀不是新的实体卡牌：action.card_instance_id 为确定性合成
        # 虚拟标识，两张实体材料按正式规则进入弃牌堆；出牌阶段使用虚拟杀
        # 消耗正常【杀】额度（与实体杀一致）。
        zhangba_virtual = bool(action.payload.get("zhangba_virtual"))
        zhangba_materials: tuple[str, str] | None = None
        if zhangba_virtual:
            if (
                equipped_weapon != "sgs_weapon_zhangbashemao"
                or str(action.payload.get("card_key", "")) != "sgs_basic_sha"
            ):
                raise InvalidActionError(
                    "只有装备丈八蛇矛时才能把两张手牌当作普通【杀】使用"
                )
            window_id = (
                f"zhangba:{runtime.turn_number}:{context.actor_id}"
            )
            material_ids = _resolve_zhangba_handle_direct(
                self._session_id,
                self._session_secret,
                state,
                window_id,
                context.actor_id,
                action.payload.get("handle"),
            )
            if material_ids is None:
                raise InvalidActionError(
                    "丈八材料句柄无效：伪造、跨窗口、跨会话或手牌已变化"
                )
            zhangba_materials = material_ids
            card = _zhangba_virtual_card(
                state, action.card_instance_id, material_ids
            )
        else:
            card = state.cards_by_id[action.card_instance_id]
        if card.card_key != adapter.card_key:
            raise InvalidActionError("【杀】动作的实体牌与适配器卡牌键不一致")
        if str(action.payload.get("card_key", "")) != adapter.card_key:
            raise InvalidActionError("【杀】动作负载与适配器卡牌键不一致")
        target = action.target_ids[0]
        if target == context.actor_id or not is_valid_slash_target(
            state, context.actor_id, target
        ):
            raise InvalidActionError("【杀】目标不在攻击范围内或目标非法")
        check_weapon_skill_gate(
            state,
            actor_id=context.actor_id,
            decision="use_slash",
            target_id=target,
            slash_card_key=adapter.card_key,
            slash_used_count=runtime.slash_used_counts.get(
                context.actor_id, 0
            ),
        )
        if not zhangba_virtual and state.location_of(
            action.card_instance_id
        ) != ZoneRef.hand(context.actor_id):
            raise InvalidActionError("只能使用行动角色真实手牌中的实体牌")

        if zhangba_virtual:
            assert zhangba_materials is not None
            material_window_id = (
                f"zhangba-materials:{runtime.turn_number}:{context.actor_id}"
            )
            next_state, material_events = self._discard_zhangba_materials(
                state,
                actor_id=context.actor_id,
                material_ids=zhangba_materials,
                window_id=material_window_id,
                purpose="use_slash",
            )
            move_event = None
        else:
            next_state, move_event = self._move_to_processing(
                state, action.card_instance_id, context.actor_id, "slash_use"
            )
        boosted = runtime.wine_buff_owner_id == context.actor_id
        if zhangba_virtual:
            used_event = GameEvent(
                event_type=EventType.CARD_USED,
                card_instance_id=action.card_instance_id,
                card_key=adapter.card_key,
                card_user=context.actor_id,
                target_ids=(target,),
                payload={
                    "damage_nature": adapter.damage_nature,
                    "boosted": boosted,
                    "physical_or_virtual": "virtual",
                    "virtual_source": "sgs_weapon_zhangbashemao",
                    "material_card_instance_ids": list(
                        zhangba_materials
                    ),
                    "material_window_id": (
                        f"zhangba-materials:{runtime.turn_number}:"
                        f"{context.actor_id}"
                    ),
                },
            )
            queued = self._events.extend(
                (used_event, *material_events)
            )
        else:
            used_event = GameEvent(
                event_type=EventType.CARD_USED,
                card_instance_id=action.card_instance_id,
                card_key=adapter.card_key,
                card_user=context.actor_id,
                target_ids=(target,),
                payload={
                    "damage_nature": adapter.damage_nature,
                    "boosted": boosted,
                },
            )
            queued = self._events.extend((used_event, move_event))
        used_sequence = queued[0].sequence
        assert used_sequence is not None
        # CP-04P 朱雀羽扇：动作负载 explicit 声明“转火杀”才转换（可由服务端
        # 枚举得到的动作携带，客户端不能伪造）；伤害属性在结算时按转换结果。
        fire_converted = bool(action.payload.get("converted_to_fire"))
        if fire_converted and (
            adapter.card_key != "sgs_basic_sha"
            or equipped_weapon != "sgs_weapon_zhuqueyushan"
        ):
            raise InvalidActionError(
                "只有装备朱雀羽扇时使用普通【杀】才能选择转为【火杀】"
            )
        next_counts = {**runtime.slash_used_counts,
                       context.actor_id: runtime.slash_used_counts.get(
                           context.actor_id, 0
                       ) + 1}
        ignore_armor = equipped_weapon == "sgs_weapon_qinggangjian"
        if fire_converted:
            # 朱雀羽扇转火杀（7.10＋基础术语20.6）：转化后的【杀】不再被
            # 藤甲普通杀免疫；转化未提供颜色（记为“无”），不触发仁王盾
            # 黑色杀无效化。八卦阵等响应判定不受影响（只有青釭剑抑制）。
            invalidation = None
        else:
            # CP-04P 青釭剑（Knowledge 7.2 用户整理解释）：使用【杀】指定
            # 目标后令其防具无效（armor invalid）。ignore_armor（代码历史字段）
            # 在指定目标后快照到本次【杀】结算，驱动真实防具无效化与防具伤害
            # 修正两个统一入口；杀结算结束后随 pending_slash 清理，不残留、
            # 不永久修改目标防具槽。
            invalidation = armor_invalidates_effect(
                state,
                victim_id=target,
                card_instance_id=action.card_instance_id,
                card_key=adapter.card_key,
                ignore_armor=ignore_armor,
                card_color=(
                    card.color if zhangba_virtual else None
                ),
            )
        if invalidation is not None:
            # 仁王盾／藤甲令【杀】对目标无效：不开闪响应窗口、不造成伤害、
            # 不消耗【闪】、不触发濒死或传导；杀仍算已经使用并进入弃牌堆。
            invalid_reason, armor_id = invalidation
            next_state, finish_event = self._finish_slash_processing(
                next_state,
                runtime,
                action.card_instance_id,
                f"slash_invalidated_by_{invalid_reason}",
            )
            cancelled_event = GameEvent(
                event_type=EventType.CARD_EFFECT_CANCELLED,
                card_instance_id=action.card_instance_id,
                card_key=adapter.card_key,
                card_user=context.actor_id,
                target_ids=(target,),
                payload={
                    "reason": invalid_reason,
                    "armor_instance_id": armor_id,
                    "armor_key": _card_key(state, armor_id),
                    "invalidated_by_armor": True,
                },
            )
            if finish_event is not None:
                self._events.extend((cancelled_event, finish_event))
            else:
                self._events.extend((cancelled_event,))
            next_runtime = replace(
                runtime,
                slash_used_counts=MappingProxyType(next_counts),
                wine_buff_owner_id=None,
                bagua_attempted=False,
            )
            next_state, next_runtime = self._complete_root_resolution(
                next_state, next_runtime
            )
            self._commit_runtime(runtime, next_runtime)
            return next_state
        next_runtime = replace(
            runtime,
            phase=ProductionPhase.SLASH_RESPONSE,
            slash_used_counts=MappingProxyType(next_counts),
            wine_buff_owner_id=None,
            pending_slash=_PendingSlash(
                context.actor_id,
                target,
                action.card_instance_id,
                boosted,
                ignore_armor=ignore_armor,
                fire_converted=fire_converted,
                virtual=zhangba_virtual,
                material_ids=(
                    zhangba_materials if zhangba_virtual else ()
                ),
            ),
            response_window_id=(
                f"slash:{runtime.turn_number}:{action.card_instance_id}"
            ),
            response_window_order=(target,),
            response_window_source_sequence=used_sequence,
            bagua_attempted=False,
        )
        self._commit_runtime(runtime, next_runtime)
        return next_state

    def apply_dodge(
        self,
        state: GameState,
        context: ActionContext,
        action: LegalAction,
        adapter: object,
    ) -> GameState:
        del adapter
        runtime = self._runtime
        if runtime.phase is not ProductionPhase.SLASH_RESPONSE:
            raise InvalidActionError("【闪】只能响应【杀】响应窗口")
        if runtime.pending_slash is None:
            raise InvalidActionError("当前没有待响应的【杀】")
        if context.actor_id != runtime.pending_slash.target_id:
            raise InvalidActionError("只有【杀】目标可以响应")
        if action.card_instance_id is None:
            raise InvalidActionError("响应【杀】必须使用真实实体【闪】")
        card = state.cards_by_id[action.card_instance_id]
        if card.card_key != "sgs_basic_shan":
            raise InvalidActionError("响应【杀】的实体牌必须是【闪】")
        if state.location_of(action.card_instance_id) != ZoneRef.hand(
            context.actor_id
        ):
            raise InvalidActionError("只能使用行动角色真实手牌中的实体牌")
        check_weapon_skill_gate(
            state,
            actor_id=runtime.pending_slash.attacker_id,
            decision="slash_dodged",
            target_id=runtime.pending_slash.target_id,
        )

        window = self._build_window(runtime)
        dodge_event = GameEvent(
            event_type=EventType.CARD_USED,
            card_instance_id=action.card_instance_id,
            card_key="sgs_basic_shan",
            card_user=context.actor_id,
            payload={"response_to": runtime.pending_slash.slash_instance_id},
        )
        record = window.respond(context.actor_id, dodge_event)
        assert record.response_event is not None
        bound_event = record.response_event
        next_state, dodge_move_events = self._consume_immediately(
            state,
            action.card_instance_id,
            context.actor_id,
            "dodge_response_complete",
        )
        slash_id = runtime.pending_slash.slash_instance_id
        next_state, slash_finish = self._finish_slash_processing(
            next_state, runtime, slash_id, "slash_cancelled_by_dodge"
        )
        cancelled_event = GameEvent(
            event_type=EventType.CARD_EFFECT_CANCELLED,
            card_instance_id=slash_id,
            card_key=(
                "sgs_basic_sha"
                if runtime.pending_slash.virtual
                else _card_key(state, slash_id)
            ),
            target_ids=(context.actor_id,),
            payload={"reason": "dodge"},
        )
        if slash_finish is not None:
            self._events.extend(
                (
                    bound_event,
                    *dodge_move_events,
                    cancelled_event,
                    slash_finish,
                )
            )
        else:
            self._events.extend(
                (bound_event, *dodge_move_events, cancelled_event)
            )
        pending = runtime.pending_slash
        assert pending is not None
        # CP-04P 青釭剑生命周期终点A（Knowledge 7.2.1 用户移动版实测确认）：
        # 目标以【闪】成功完成本次响应时，在该【闪】相关结算完成后，本次
        # 【杀】的青釭剑防具无效状态即清除；此后该目标防具恢复正常，后续
        # 武器窗口与后续独立牌结算不再受本次青釭剑影响（不移除防具实体、
        # 不永久改变装备状态）。
        lifecycle_slash = replace(pending, ignore_armor=False)
        # CP-04P 贯石斧（7.7 当前确认）：使用的【杀】被【闪】响应后，可弃置
        # 自己手牌区与装备区合计2张牌使此【杀】强制造成伤害。贯石斧自身
        # 不能作为代价之一（USER_CONFIRMED_MOBILE_RULE，2026-08-08 用户移动版
        # 实测确认），可弃牌数不足2张时无法发动，直接完成；否则打开选择
        # 窗口（杀已因闪进入弃牌堆）。
        guanshifu_affordable = False
        weapon_key = equipped_weapon_key(state, pending.attacker_id)
        if weapon_key == "sgs_weapon_guanshifu":
            weapon_ids = state.card_ids_in(
                ZoneRef.equipment(pending.attacker_id, "weapon")
            )
            own_cards = len(
                state.card_ids_in(ZoneRef.hand(pending.attacker_id))
            ) + sum(
                len(state.card_ids_in(ZoneRef.equipment(pending.attacker_id, slot)))
                for slot in EQUIPMENT_SLOTS
            )
            if weapon_ids:
                # 排除当前提供技能的贯石斧自身
                own_cards -= 1
            guanshifu_affordable = own_cards >= 2
        if guanshifu_affordable:
            next_runtime = replace(
                runtime,
                phase=ProductionPhase.WEAPON_SLASH_CHOICE,
                pending_slash=lifecycle_slash,
                pending_slash_choice=_PendingSlashChoice(
                    weapon_key="sgs_weapon_guanshifu",
                    kind="guanshifu_force_hit",
                    attacker_id=pending.attacker_id,
                    target_id=pending.target_id,
                    window_id=(
                        f"weapon-slash-choice:{runtime.turn_number}:"
                        f"{pending.slash_instance_id}"
                    ),
                    pending_slash=lifecycle_slash,
                ),
            )
        elif weapon_key == "sgs_weapon_qinglongyanyuedao" and any(
            state.cards_by_id[instance_id].card_key in SLASH_CARD_KEYS
            for instance_id in state.card_ids_in(
                ZoneRef.hand(pending.attacker_id)
            )
        ):
            # CP-04P 青龙偃月刀（7.6 用户整理解释）：使用的【杀】被【闪】
            # 响应后，可继续对该目标使用一张【杀】。攻击者手牌中仍有
            # 【杀】候选时打开选择窗口；候选只暴露不透明句柄，客户端
            # 不得提交裸实体ID。攻击范围与距离在窗口打开时按原目标
            # 校验，实际使用前应用层再次动态重检。
            window_id = (
                f"weapon-slash-choice:{runtime.turn_number}:"
                f"{pending.slash_instance_id}"
            )
            hand_ids = tuple(
                state.card_ids_in(ZoneRef.hand(pending.attacker_id))
            )
            snapshot_digest = sha256_value(hand_ids)
            handles = MappingProxyType(
                {
                    _hand_choice_handle(
                        self._session_id,
                        self._session_secret,
                        window_id,
                        pending.attacker_id,
                        "hand",
                        snapshot_digest,
                        instance_id,
                    ): instance_id
                    for instance_id in hand_ids
                    if state.cards_by_id[instance_id].card_key
                    in SLASH_CARD_KEYS
                }
            )
            next_runtime = replace(
                runtime,
                phase=ProductionPhase.WEAPON_SLASH_CHOICE,
                pending_slash=lifecycle_slash,
                pending_slash_choice=_PendingSlashChoice(
                    weapon_key="sgs_weapon_qinglongyanyuedao",
                    kind="qinglong_continue",
                    attacker_id=pending.attacker_id,
                    target_id=pending.target_id,
                    window_id=window_id,
                    pending_slash=lifecycle_slash,
                    handles=handles,
                    snapshot_digest=snapshot_digest,
                ),
            )
        else:
            next_state, next_runtime = self._complete_root_resolution(
                next_state, replace(runtime, pending_slash=lifecycle_slash)
            )
        self._commit_runtime(runtime, next_runtime)
        return next_state

    def apply_slash_damage(
        self,
        state: GameState,
        context: ActionContext,
        action: LegalAction,
    ) -> GameState:
        del action
        runtime = self._runtime
        if runtime.phase is not ProductionPhase.SLASH_RESPONSE:
            raise InvalidActionError("【杀】伤害结算只能在响应窗口进行")
        if runtime.pending_slash is None:
            raise InvalidActionError("当前没有待结算的【杀】")
        if context.actor_id != runtime.pending_slash.target_id:
            raise InvalidActionError("只有【杀】目标可以放弃响应")
        check_weapon_skill_gate(
            state,
            actor_id=runtime.pending_slash.attacker_id,
            decision="slash_damage",
            target_id=runtime.pending_slash.target_id,
        )

        pending = runtime.pending_slash
        # CP-04P 寒冰剑（7.3）：使用【杀】将要造成伤害时，可以防止此伤害；
        # 若如此做，弃置目标2张牌（基础术语第12节：牌=手牌区+装备区）。
        # 目标可弃牌数不足1张时无法发动（7.3特殊说明），直接进入伤害结算。
        if (
            equipped_weapon_key(state, pending.attacker_id)
            == "sgs_weapon_hanbingjian"
        ):
            target_discardable = (
                len(state.card_ids_in(ZoneRef.hand(pending.target_id)))
                + len(state.card_ids_in(ZoneRef.equipment(pending.target_id, "armor")))
                + len(state.card_ids_in(ZoneRef.equipment(pending.target_id, "weapon")))
                + len(
                    state.card_ids_in(
                        ZoneRef.equipment(pending.target_id, "attack_horse")
                    )
                )
                + len(
                    state.card_ids_in(
                        ZoneRef.equipment(pending.target_id, "defense_horse")
                    )
                )
            )
            if target_discardable >= 1:
                next_runtime = replace(
                    runtime,
                    phase=ProductionPhase.WEAPON_SLASH_CHOICE,
                    pending_slash_choice=_PendingSlashChoice(
                        weapon_key="sgs_weapon_hanbingjian",
                        kind="hanbing_prevent",
                        attacker_id=pending.attacker_id,
                        target_id=pending.target_id,
                        window_id=(
                            f"weapon-slash-choice:{runtime.turn_number}:"
                            f"{pending.slash_instance_id}"
                        ),
                        pending_slash=pending,
                    ),
                )
                self._commit_runtime(runtime, next_runtime)
                return state
        next_state, next_runtime = self._continue_slash_damage(
            state, runtime
        )
        self._commit_runtime(runtime, next_runtime)
        return next_state

    def _continue_slash_damage(
        self,
        state: GameState,
        runtime: _BatchRuntime,
    ) -> tuple[GameState, _BatchRuntime]:
        """【杀】伤害结算的统一继续路径：目标放弃响应后进入伤害管线。

        寒冰剑（7.3）选择不发动（放弃）时与目标直接放弃响应走同一条
        路径；选择发动时由弃牌窗口完成防止路径，不进入本方法。"""

        pending = runtime.pending_slash
        if pending is None:
            raise ProductionBatchError("当前没有待结算的【杀】")
        slash = self._slash_card(state, runtime, pending.slash_instance_id)
        adapter = self._formal_registry.adapter_for(slash.card_key)
        if not isinstance(adapter, SlashAdapter):
            raise InvalidActionError("【杀】伤害结算必须使用【杀】生产适配器")
        window = self._build_window(runtime)
        window.pass_response(pending.target_id)

        # CP-04P 古锭刀（USER_CONFIRMED_MOBILE_RULE＋IN_GAME_CARD_TEXT_
        # CONFIRMED，2026-08-08 用户移动版游戏内文本与实测）：游戏内文本
        # “当你使用【杀】对目标角色造成伤害时，若该角色没有手牌，则此
        # 伤害+1”——判定时机是造成伤害时，必须在伤害管线前读取目标当前
        # 权威手牌，不使用指定目标时的旧快照。
        weapon_damage_bonus = _weapon_damage_bonus_at_damage(
            state, pending.attacker_id, pending.target_id
        )
        base_amount = (2 if pending.boosted else 1) + weapon_damage_bonus
        damage_type = (
            "火属性" if pending.fire_converted else adapter.damage_nature
        )
        # CP-04P 麒麟弓（7.11）：使用【杀】对目标造成伤害时可选弃置目标
        # 装备区一张坐骑牌。仅在目标实际有坐骑且伤害>0时打开窗口。
        # R1-NEW-001：weapon_choice 不再携带 pre-armor base amount——
        # 真正完成 resolve_armor_damage 的函数以 resolution.final_amount
        # 创建 Qilin pending，避免在 Qilin 窗口关闭后用旧 base 重新扣血
        # （如 Wine Slash base=2＋白银狮子 final=1、Fire Slash base=1＋
        # 藤甲 final=2 等 armor resolution 差异）。
        weapon_choice = None
        if (
            equipped_weapon_key(state, pending.attacker_id)
            == "sgs_weapon_qilingong"
            and base_amount > 0
        ):
            target_mounts = state.card_ids_in(
                ZoneRef.equipment(pending.target_id, "attack_horse")
            ) + state.card_ids_in(
                ZoneRef.equipment(pending.target_id, "defense_horse")
            )
            if target_mounts:
                weapon_choice = ("sgs_weapon_qilingong", pending.target_id)
        next_state, next_runtime = self._apply_damage_and_maybe_chain(
            state,
            runtime,
            victim_id=pending.target_id,
            amount=base_amount,
            damage_type=damage_type,
            card_instance_id=pending.slash_instance_id,
            card_key=slash.card_key,
            card_user=pending.attacker_id,
            source_id=pending.attacker_id,
            kill_credit=pending.attacker_id,
            ignore_armor=pending.ignore_armor,
            payload={
                "weapon_damage_bonus": weapon_damage_bonus,
            },
            weapon_choice=weapon_choice,
            resolved_reason="slash_damage_resolved",
            death_reason="slash_damage_resolved_with_death",
            rescue_reason="slash_damage_resolved_after_rescue",
        )
        return next_state, next_runtime

    # ------------------------------------------------------------------
    # CP-04P 武器选择窗口（贯石斧强制命中／寒冰剑防止伤害／青龙偃月刀
    # 继续使用杀）与弃2张窗口
    # ------------------------------------------------------------------

    def _enter_weapon_discard_two(
        self,
        state: GameState,
        runtime: _BatchRuntime,
        *,
        chooser_id: str,
        cards_owner_id: str,
        source_kind: str,
        window_id: str,
    ) -> tuple[GameState, _BatchRuntime]:
        """打开武器弃2张选择窗口（贯石斧：攻击者弃自己手牌＋装备；
        寒冰剑：攻击者选择目标手牌＋装备共2张弃置）。"""

        excluded_instance_id = None
        if source_kind == "guanshifu_force_hit":
            weapon_ids = state.card_ids_in(
                ZoneRef.equipment(cards_owner_id, "weapon")
            )
            if len(weapon_ids) == 1:
                excluded_instance_id = weapon_ids[0]
        hand_ids = tuple(state.card_ids_in(ZoneRef.hand(cards_owner_id)))
        snapshot_digest = sha256_value(hand_ids)
        handles = _zone_choice_handle_snapshot(
            self._session_id,
            self._session_secret,
            state,
            cards_owner_id,
            window_id,
            snapshot_digest,
        )
        next_runtime = replace(
            runtime,
            phase=ProductionPhase.WEAPON_DISCARD_TWO,
            pending_discard_two=_PendingDiscardTwo(
                chooser_id=chooser_id,
                cards_owner_id=cards_owner_id,
                source_kind=source_kind,
                window_id=window_id,
                handles=handles,
                snapshot_digest=snapshot_digest,
                excluded_instance_id=excluded_instance_id,
            ),
        )
        return state, next_runtime

    def apply_weapon_force_hit(
        self,
        state: GameState,
        context: ActionContext,
        action: LegalAction,
    ) -> GameState:
        """贯石斧：发动强制命中，进入弃自己手牌＋装备2张的选择窗口。"""

        runtime = self._runtime
        if runtime.phase is not ProductionPhase.WEAPON_SLASH_CHOICE:
            raise InvalidActionError("贯石斧强制命中只能在被闪后的武器选择窗口发动")
        choice = runtime.pending_slash_choice
        if choice is None or choice.kind != "guanshifu_force_hit":
            raise InvalidActionError("当前没有可发动的贯石斧强制命中窗口")
        if context.actor_id != choice.attacker_id:
            raise InvalidActionError("只有武器持有者可以发动贯石斧")
        if action.payload.get("window_id") != choice.window_id:
            raise InvalidActionError("贯石斧发动动作不属于当前武器选择窗口")
        attacker = state.players_by_id[choice.attacker_id]
        if not attacker.alive:
            raise InvalidActionError("已死亡角色不能发动贯石斧")
        next_state, next_runtime = self._enter_weapon_discard_two(
            state,
            runtime,
            chooser_id=choice.attacker_id,
            cards_owner_id=choice.attacker_id,
            source_kind="guanshifu_force_hit",
            window_id=(
                f"weapon-discard-two:{runtime.turn_number}:"
                f"{choice.pending_slash.slash_instance_id}"
            ),
        )
        self._commit_runtime(runtime, next_runtime)
        return next_state

    def apply_weapon_prevent_damage(
        self,
        state: GameState,
        context: ActionContext,
        action: LegalAction,
    ) -> GameState:
        """寒冰剑：发动防止伤害，进入第一次逐张弃置窗口（step 1）。

        2026-08-08 用户移动版实测确认：寒冰剑“弃置目标2张牌”是一张一张
        弃置，不是同时选择、同时弃置；每次窗口只选择并正式弃置1张，
        第1张完成后基于最新权威状态重新枚举第2张。"""

        runtime = self._runtime
        if runtime.phase is not ProductionPhase.WEAPON_SLASH_CHOICE:
            raise InvalidActionError("寒冰剑防止伤害只能在伤害前的武器选择窗口发动")
        choice = runtime.pending_slash_choice
        if choice is None or choice.kind != "hanbing_prevent":
            raise InvalidActionError("当前没有可发动的寒冰剑防止伤害窗口")
        if context.actor_id != choice.attacker_id:
            raise InvalidActionError("只有武器持有者可以发动寒冰剑")
        if action.payload.get("window_id") != choice.window_id:
            raise InvalidActionError("寒冰剑发动动作不属于当前武器选择窗口")
        attacker = state.players_by_id[choice.attacker_id]
        target = state.players_by_id[choice.target_id]
        if not attacker.alive or not target.alive:
            raise InvalidActionError("寒冰剑发动时角色已死亡")
        next_state, next_runtime = self._enter_hanbing_discard_step(
            state,
            runtime,
            step=1,
        )
        self._commit_runtime(runtime, next_runtime)
        return next_state

    def _enter_hanbing_discard_step(
        self,
        state: GameState,
        runtime: _BatchRuntime,
        *,
        step: int,
    ) -> tuple[GameState, _BatchRuntime]:
        """打开寒冰剑第 step 次逐张弃置窗口（基于最新权威状态重新快照）。"""

        choice = runtime.pending_slash_choice
        if choice is None or choice.kind != "hanbing_prevent":
            raise ProductionBatchError("寒冰剑逐张弃置缺少防止伤害窗口")
        pending = choice.pending_slash
        window_id = (
            f"hanbing-discard:{runtime.turn_number}:"
            f"{pending.slash_instance_id}:step{step}"
        )
        hand_ids = tuple(state.card_ids_in(ZoneRef.hand(pending.target_id)))
        snapshot_digest = sha256_value(hand_ids)
        handles = _zone_choice_handle_snapshot(
            self._session_id,
            self._session_secret,
            state,
            pending.target_id,
            window_id,
            snapshot_digest,
        )
        next_runtime = replace(
            runtime,
            phase=ProductionPhase.HANBING_DISCARD,
            pending_hanbing_discard=_PendingHanbingDiscard(
                attacker_id=pending.attacker_id,
                target_id=pending.target_id,
                window_id=window_id,
                step=step,
                handles=handles,
                snapshot_digest=snapshot_digest,
            ),
        )
        return state, next_runtime

    def apply_hanbing_discard_card(
        self,
        state: GameState,
        context: ActionContext,
        action: LegalAction,
    ) -> GameState:
        """寒冰剑逐张弃置：选择并正式弃置当前窗口的一张牌。

        每次动作只移动一张牌并登记其独立弃置事件；第1张弃置完成后，
        根据最新权威状态重新枚举并打开第2次窗口；第2张弃置完成后完成
        寒冰剑防止结算。stale／伪造动作失败关闭，且不会回滚已经合法
        完成的第1次弃置，也不会错误地直接完成寒冰剑。"""

        runtime = self._runtime
        if runtime.phase is not ProductionPhase.HANBING_DISCARD:
            raise InvalidActionError("寒冰剑逐张弃置只能在寒冰剑弃置窗口进行")
        hanbing = runtime.pending_hanbing_discard
        if hanbing is None:
            raise InvalidActionError("当前没有打开的寒冰剑逐张弃置窗口")
        if context.actor_id != hanbing.attacker_id:
            raise InvalidActionError("只有寒冰剑持有者可以选择弃置目标牌")
        if action.payload.get("operation") != "hanbing_discard_card":
            raise InvalidActionError("弃置动作负载无效")
        if action.payload.get("window_id") != hanbing.window_id:
            raise InvalidActionError("弃置动作不属于当前寒冰剑弃置窗口")
        if action.payload.get("step") != hanbing.step:
            raise InvalidActionError("弃置动作绑定的弃置步数与当前窗口不一致")
        if str(action.payload.get("state_hash", "")) != state_sha256(
            canonical_state_snapshot(state)
        ):
            raise InvalidActionError("弃置动作绑定的状态哈希已过期")
        target = state.players_by_id[hanbing.target_id]
        attacker = state.players_by_id[hanbing.attacker_id]
        if not target.alive or not attacker.alive:
            raise InvalidActionError("寒冰剑弃置时角色已死亡")
        zone_id = str(action.payload.get("zone", "hand"))
        if zone_id == "hand":
            instance_id = _resolve_hand_choice_handle(
                self._session_id,
                self._session_secret,
                state,
                hanbing.window_id,
                hanbing.target_id,
                "hand",
                hanbing.snapshot_digest,
                hanbing.handles,
                action.payload.get("handle"),
            )
            if instance_id is None:
                raise InvalidActionError(
                    "寒冰剑弃置手牌句柄无效：伪造、跨窗口、跨会话或手牌已变化"
                )
            source = ZoneRef.hand(hanbing.target_id)
        else:
            instance_id = action.card_instance_id
            if instance_id is None:
                raise InvalidActionError("寒冰剑弃置装备区牌必须指定实体牌")
            source = _zone_from_id(zone_id, hanbing.target_id)
            if state.location_of(instance_id) != source:
                raise InvalidActionError(
                    "寒冰剑弃置装备区牌不在指定装备槽中"
                )
        # 当前窗口内每次只能弃置一张牌（逐张弃置语义）。
        next_state = state.move_cards({instance_id: DISCARD_PILE})
        card_key = _card_key(next_state, instance_id)
        events: list[GameEvent] = [
            GameEvent(
                event_type=EventType.CARD_MOVED,
                card_instance_id=instance_id,
                card_key=card_key,
                card_user=hanbing.attacker_id,
                payload={
                    "source": _zone_payload(source),
                    "destination": _zone_payload(DISCARD_PILE),
                    "reason": "hanbing_discard",
                    "window_id": hanbing.window_id,
                    "hanbing_step": hanbing.step,
                },
            ),
            GameEvent(
                event_type=EventType.CARD_LOST,
                card_instance_id=instance_id,
                card_key=card_key,
                target_ids=(hanbing.target_id,),
                payload={
                    "reason": "hanbing_discard",
                    "source_zone": _zone_id(source),
                    "window_id": hanbing.window_id,
                    "hanbing_step": hanbing.step,
                },
            ),
            GameEvent(
                event_type=EventType.CARD_DISCARDED,
                card_instance_id=instance_id,
                card_key=card_key,
                card_user=hanbing.attacker_id,
                target_ids=(hanbing.target_id,),
                payload={
                    "reason": "hanbing_discard",
                    "source_zone": _zone_id(source),
                    "window_id": hanbing.window_id,
                    "hanbing_step": hanbing.step,
                },
            ),
        ]
        if source.kind is ZoneKind.EQUIPMENT and source.equipment_slot == (
            "armor"
        ):
            # 防具离区统一钩子：第1张弃置造成白银狮子离区时立即回复，
            # 第2次选择必须看到该状态变化。
            next_state, recovery_events = self._apply_armor_leave_recovery(
                next_state,
                instance_id=instance_id,
                owner_id=hanbing.target_id,
                reason="hanbing_discard",
            )
            events.extend(recovery_events)
        self._events.extend(tuple(events))
        if hanbing.step == 1:
            # 第1张弃置完成：根据此刻最新权威状态重新枚举第2张可弃牌。
            remaining = len(
                next_state.card_ids_in(ZoneRef.hand(hanbing.target_id))
            ) + sum(
                len(
                    next_state.card_ids_in(
                        ZoneRef.equipment(hanbing.target_id, slot)
                    )
                )
                for slot in EQUIPMENT_SLOTS
            )
            if remaining >= 1:
                next_state, next_runtime = self._enter_hanbing_discard_step(
                    next_state, runtime, step=2
                )
                self._commit_runtime(runtime, next_runtime)
                return next_state
        next_state, next_runtime = self._finish_hanbing_prevent(
            next_state, runtime
        )
        self._commit_runtime(runtime, next_runtime)
        return next_state

    def _finish_hanbing_prevent(
        self,
        state: GameState,
        runtime: _BatchRuntime,
    ) -> tuple[GameState, _BatchRuntime]:
        """寒冰剑防止路径完成：通过响应窗口、登记统一防止事件并完成
        本次【杀】结算。不扣减HP、不产生damage事件、不进入濒死或传导。"""

        choice = runtime.pending_slash_choice
        if choice is None or choice.kind != "hanbing_prevent":
            raise ProductionBatchError("寒冰剑防止完成缺少防止伤害窗口")
        pending = choice.pending_slash
        window = self._build_window(runtime)
        window.pass_response(pending.target_id)
        base_amount = (2 if pending.boosted else 1) + (
            _weapon_damage_bonus_at_damage(
                state, pending.attacker_id, pending.target_id
            )
        )
        prevented_event = GameEvent(
            event_type=EventType.DAMAGE_PREVENTED,
            card_instance_id=pending.slash_instance_id,
            card_key=_card_key(state, pending.slash_instance_id),
            card_user=pending.attacker_id,
            target_ids=(pending.target_id,),
            payload={
                "victim_id": pending.target_id,
                "card_key": _card_key(state, pending.slash_instance_id),
                "declared_amount": base_amount,
                "final_amount": 0,
                "modifiers": ["hanbing_prevent"],
                "armor_ignored": False,
            },
        )
        self._events.extend((prevented_event,))
        next_state, finish_event = self._finish_processing(
            state,
            pending.slash_instance_id,
            "hanbing_damage_prevented",
        )
        self._events.extend((finish_event,))
        next_state, next_runtime = self._complete_root_resolution(
            next_state,
            replace(
                runtime,
                pending_slash_choice=None,
                pending_discard_two=None,
                pending_hanbing_discard=None,
            ),
        )
        return next_state, next_runtime

    def _resolve_weapon_slash_choice_handle(
        self,
        state: GameState,
        runtime: _BatchRuntime,
        handle: object,
    ) -> str | None:
        """解析青龙偃月刀继续杀窗口的隐藏手牌句柄为真实【杀】实体。"""

        choice = runtime.pending_slash_choice
        if choice is None or choice.kind != "qinglong_continue":
            return None
        return _resolve_hand_choice_handle(
            self._session_id,
            self._session_secret,
            state,
            choice.window_id,
            choice.attacker_id,
            "hand",
            choice.snapshot_digest,
            choice.handles,
            handle,
        )

    def apply_qinglong_continue_slash(
        self,
        state: GameState,
        context: ActionContext,
        action: LegalAction,
    ) -> GameState:
        """青龙偃月刀：被闪后选择一张手牌【杀】继续对原目标使用。"""

        runtime = self._runtime
        if runtime.phase is not ProductionPhase.WEAPON_SLASH_CHOICE:
            raise InvalidActionError("青龙偃月刀继续杀只能在被闪后的武器选择窗口使用")
        choice = runtime.pending_slash_choice
        if choice is None or choice.kind != "qinglong_continue":
            raise InvalidActionError("当前没有可继续使用【杀】的青龙偃月刀窗口")
        if context.actor_id != choice.attacker_id:
            raise InvalidActionError("只有武器持有者可以继续使用【杀】")
        if action.payload.get("window_id") != choice.window_id:
            raise InvalidActionError("继续使用【杀】动作不属于当前武器选择窗口")
        if str(action.payload.get("state_hash", "")) != state_sha256(
            canonical_state_snapshot(state)
        ):
            raise InvalidActionError("继续使用【杀】动作绑定的状态哈希已过期")
        attacker = state.players_by_id[choice.attacker_id]
        target = state.players_by_id.get(choice.target_id)
        if not attacker.alive or target is None or not target.alive:
            raise InvalidActionError(
                "继续使用【杀】时原目标已失效，不能使用【杀】"
            )
        # 第二次动态重检：攻击范围与距离按原目标当前状态重新判定。
        if not is_valid_slash_target(
            state, choice.attacker_id, choice.target_id
        ):
            raise InvalidActionError(
                "第二次检测失败：原目标已不在当前攻击范围内"
            )
        instance_id = self._resolve_weapon_slash_choice_handle(
            state, runtime, action.payload.get("handle")
        )
        if instance_id is None:
            raise InvalidActionError(
                "继续使用【杀】句柄无效、过期或伪造；不接受裸实体ID提交"
            )
        card = state.cards_by_id[instance_id]
        if card.card_key not in SLASH_CARD_KEYS:
            raise InvalidActionError("继续使用实体必须是普通／火／雷【杀】")
        if state.location_of(instance_id) != ZoneRef.hand(
            choice.attacker_id
        ):
            raise InvalidActionError("继续使用【杀】实体必须仍在攻击者手牌中")
        # 武器技能门禁：继续使用的【杀】仍受攻击者当前武器技能约束。
        check_weapon_skill_gate(
            state,
            actor_id=choice.attacker_id,
            decision="use_slash",
            target_id=choice.target_id,
            slash_card_key=card.card_key,
            slash_used_count=runtime.slash_used_counts.get(
                choice.attacker_id, 0
            ),
        )
        next_state, next_runtime = self._apply_qinglong_slash_use(
            state,
            runtime,
            slash_instance_id=instance_id,
            attacker_id=choice.attacker_id,
            target_id=choice.target_id,
        )
        self._commit_runtime(runtime, next_runtime)
        return next_state

    def _apply_qinglong_slash_use(
        self,
        state: GameState,
        runtime: _BatchRuntime,
        *,
        slash_instance_id: str,
        attacker_id: str,
        target_id: str,
    ) -> tuple[GameState, _BatchRuntime]:
        """青龙偃月刀继续【杀】的正式使用子结算。

        继续使用的【杀】由青龙偃月刀技能授权，不受“通常每个出牌阶段只能
        使用1张【杀】”限制，且不消耗普通出牌阶段【杀】使用次数额度
        （USER_CONFIRMED_MOBILE_RULE，2026-08-08 用户移动版实测确认：
        正常使用【杀】→被【闪】→青龙追杀后，手牌中其他【杀】仍保持可
        正常使用状态）。每一张追杀仍是一次真实的【杀】使用：产生独立
        CARD_USED 事件并进入完整闪响应、伤害、濒死、救援结算（A.历史
        意义保留），但 `slash_used_counts`（普通出牌阶段额度）不因追杀
        增加（B.额度意义）。后续【杀】按正常流程结算。"""

        card = state.cards_by_id[slash_instance_id]
        adapter = self._formal_registry.adapter_for(card.card_key)
        if not isinstance(adapter, SlashAdapter):
            raise ProductionBatchError("青龙偃月刀继续杀必须使用【杀】生产适配器")
        next_state, move_event = self._move_to_processing(
            state, slash_instance_id, attacker_id, "qinglong_continue_slash_use"
        )
        boosted = runtime.wine_buff_owner_id == attacker_id
        used_event = GameEvent(
            event_type=EventType.CARD_USED,
            card_instance_id=slash_instance_id,
            card_key=card.card_key,
            card_user=attacker_id,
            target_ids=(target_id,),
            payload={
                "damage_nature": adapter.damage_nature,
                "boosted": boosted,
                "weapon_continue_context": "qinglongyanyuedao",
                "ignore_slash_use_limit": True,
                "root_slash_instance_id": (
                    runtime.pending_slash_choice.pending_slash.slash_instance_id
                    if runtime.pending_slash_choice is not None
                    else None
                ),
            },
        )
        queued = self._events.extend((used_event, move_event))
        used_sequence = queued[0].sequence
        assert used_sequence is not None
        # 青龙偃月刀自身不提供令目标防具无效／伤害修正；青釭剑、古锭刀与
        # 朱雀羽扇不可能同时装备，按当前武器槽读取快照保持统一口径。
        equipped_weapon = equipped_weapon_key(state, attacker_id)
        ignore_armor = equipped_weapon == "sgs_weapon_qinggangjian"
        next_runtime = replace(
            runtime,
            phase=ProductionPhase.SLASH_RESPONSE,
            wine_buff_owner_id=None,
            pending_slash=_PendingSlash(
                attacker_id,
                target_id,
                slash_instance_id,
                boosted,
                ignore_armor=ignore_armor,
            ),
            pending_slash_choice=None,
            pending_discard_two=None,
            response_window_id=(
                f"slash:{runtime.turn_number}:{slash_instance_id}"
            ),
            response_window_order=(target_id,),
            response_window_source_sequence=used_sequence,
            bagua_attempted=False,
        )
        return next_state, next_runtime

    # ------------------------------------------------------------------
    # CP-04P 丈八蛇矛：两张手牌当作普通【杀】使用或打出（虚拟杀）
    # ------------------------------------------------------------------

    def _slash_card(
        self,
        state: GameState,
        runtime: _BatchRuntime,
        instance_id: str,
    ) -> CardInstance:
        """统一【杀】身份查询：实体杀查 state.cards_by_id；丈八虚拟杀查
        当前挂起虚拟杀（不进入实体牌目录）。"""

        # 实体路径（所有当前已证明生产路径）直接查 state.cards_by_id，
        # 与撤回 virtual: 放行前行为完全一致；虚拟分支仅 pending_slash.
        # virtual=True 时可达，而丈八保持 PARTIAL/fail-closed 后不可达。

        if instance_id in state.cards_by_id:
            return state.cards_by_id[instance_id]
        virtual = _virtual_slash_card(state, runtime, instance_id)
        if virtual is None:
            raise ProductionBatchError(
                f"找不到实体牌或当前挂起虚拟杀{instance_id!r}"
            )
        return virtual

    def _finish_slash_processing(
        self,
        state: GameState,
        runtime: _BatchRuntime,
        instance_id: str,
        reason: str,
    ) -> tuple[GameState, GameEvent | None]:
        """实体【杀】完成结算；丈八虚拟杀无实体在PROCESSING，跳过finish。

        虚拟杀的两张实体材料在转换时已按正式规则进入弃牌堆，结算完成
        不产生额外的实体牌移动事件；重执行路径一致。"""

        # 实体路径等价 _finish_processing（所有已证明生产路径不变）；
        # 虚拟分支仅 pending_slash.virtual=True 时可达，丈八 fail-closed
        # 后不可达（UNREACHABLE while zhangba PARTIAL）。

        pending = runtime.pending_slash
        if (
            pending is not None
            and pending.virtual
            and pending.slash_instance_id == instance_id
        ):
            return state, None
        return self._finish_processing(state, instance_id, reason)

    def _discard_zhangba_materials(
        self,
        state: GameState,
        *,
        actor_id: str,
        material_ids: tuple[str, str],
        window_id: str,
        purpose: str,
    ) -> tuple[GameState, tuple[GameEvent, ...]]:
        """丈八虚拟杀的两张实体材料作为本次转换的 subcards 随虚拟杀
        使用/打出一次性进入弃牌堆。

        UNREACHABLE while zhangba PARTIAL/fail-closed：仅由丈八虚拟杀
        使用/打出 apply 路径调用；不得被其他路径当作已证明正式生产能力。

        依据基础术语第20.4/20.6节（当前确认）与第12节措辞通则：丈八蛇矛
        文本“将两张手牌当【杀】使用或打出”没有“弃置”字样，材料不是
        一次独立的弃置动作（discard cost）——不得产生 CARD_DISCARDED
        事件（基础术语：除非具体效果明确使用“弃置”一词，否则不得自动
        视为某名角色执行了一次“弃置牌”的操作）；材料作为虚拟杀的材料
        实体（subcards）随本次 CARD_USED/CARD_PLAYED 进入弃牌堆，离开
        手牌登记 CARD_LOST（失去牌）。材料必须是当前真实手牌（装备区、
        判定区不得作为材料）；任一非法则整批不移动。两张材料属于同一次
        转换，共享同一转换窗口ID。

        规则缺口记录（VIRTUAL_CARD_SUBCARD_LIFECYCLE_RULE_GAP）：
        材料在“使用/打出”时的精确 zone 生命周期时点（A.先作为 subcards
        进入PROCESSING、结算完成后再进入弃牌堆；B.开始结算前直接进入
        弃牌堆）在项目 Knowledge 中没有明确确认通则；当前按“材料随本次
        虚拟杀使用/打出进入弃牌堆”的最小一致模型实现，待用户确认。"""

        hand_set = set(state.card_ids_in(ZoneRef.hand(actor_id)))
        for instance_id in material_ids:
            if instance_id not in hand_set:
                raise ProductionBatchError(
                    "丈八材料必须是当前真实手牌；装备区、判定区不得作为材料"
                )
        if len(set(material_ids)) != len(material_ids):
            raise ProductionBatchError("丈八材料不允许重复选择同一实体")
        next_state = state.move_cards(
            {instance_id: DISCARD_PILE for instance_id in material_ids}
        )
        events: list[GameEvent] = []
        for instance_id in material_ids:
            source = state.location_of(instance_id)
            card_key = _card_key(next_state, instance_id)
            events.extend(
                (
                    GameEvent(
                        event_type=EventType.CARD_MOVED,
                        card_instance_id=instance_id,
                        card_key=card_key,
                        card_user=actor_id,
                        payload={
                            "source": _zone_payload(source),
                            "destination": _zone_payload(DISCARD_PILE),
                            "reason": "zhangba_material",
                            "window_id": window_id,
                            "purpose": purpose,
                        },
                    ),
                    GameEvent(
                        event_type=EventType.CARD_LOST,
                        card_instance_id=instance_id,
                        card_key=card_key,
                        target_ids=(actor_id,),
                        payload={
                            "reason": "zhangba_material",
                            "source_zone": _zone_id(source),
                            "window_id": window_id,
                            "purpose": purpose,
                        },
                    ),
                )
            )
        return next_state, tuple(events)

    def _zhangba_virtual_id(
        self, runtime: _BatchRuntime, material_ids: tuple[str, str]
    ) -> str:
        # UNREACHABLE while zhangba PARTIAL/fail-closed：当前无调用点
        # （virtual id 在各枚举/apply 点内联构造），待丈八恢复时清理或复用。
        return (
            f"virtual:zhangba:{runtime.turn_number}:"
            f"{material_ids[0]}:{material_ids[1]}"
        )

    def apply_pass_weapon_slash_choice(
        self,
        state: GameState,
        context: ActionContext,
        action: LegalAction,
    ) -> GameState:
        """放弃被闪后/伤害前武器选择：贯石斧与青龙偃月刀放弃时按被闪
        完成收尾；寒冰剑放弃时按正常伤害结算继续。"""

        runtime = self._runtime
        if runtime.phase is not ProductionPhase.WEAPON_SLASH_CHOICE:
            raise InvalidActionError("放弃武器选择只能在被闪后/伤害前窗口进行")
        choice = runtime.pending_slash_choice
        if choice is None:
            raise InvalidActionError("当前没有打开的被闪后/伤害前武器选择窗口")
        if context.actor_id != choice.attacker_id:
            raise InvalidActionError("只有武器持有者可以放弃武器选择")
        if action.payload.get("window_id") != choice.window_id:
            raise InvalidActionError("放弃动作不属于当前武器选择窗口")
        if choice.kind == "hanbing_prevent":
            # 寒冰剑放弃发动：继续本次【杀】的正常伤害结算。
            next_state, next_runtime = self._continue_slash_damage(
                state, runtime
            )
        else:
            # 贯石斧／青龙偃月刀放弃：本次【杀】已因【闪】结束。
            next_state, next_runtime = self._complete_root_resolution(
                state, replace(runtime, pending_slash_choice=None)
            )
        self._commit_runtime(runtime, next_runtime)
        return next_state

    def apply_select_discard_two(
        self,
        state: GameState,
        context: ActionContext,
        action: LegalAction,
    ) -> GameState:
        """弃2张窗口选择动作：把一张手牌或装备区牌加入待弃集合。

        选择过程不移动牌、不产生正式弃牌事件；只有提交动作确认后才统一
        弃置。手牌只接受隐藏句柄，装备区牌接受实体ID（装备区公开）。"""

        runtime = self._runtime
        if runtime.phase is not ProductionPhase.WEAPON_DISCARD_TWO:
            raise InvalidActionError("只有武器弃2张窗口可以选择待弃牌")
        discard_two = runtime.pending_discard_two
        if discard_two is None:
            raise InvalidActionError("当前没有打开的武器弃2张窗口")
        if context.actor_id != discard_two.chooser_id:
            raise InvalidActionError("只有选择者可以选择待弃牌")
        if action.payload.get("operation") != "select_discard_two":
            raise InvalidActionError("选择动作负载无效")
        if action.payload.get("window_id") != discard_two.window_id:
            raise InvalidActionError("选择动作不属于当前弃2张窗口")
        if str(action.payload.get("state_hash", "")) != state_sha256(
            canonical_state_snapshot(state)
        ):
            raise InvalidActionError("选择动作绑定的状态哈希已过期")
        if len(discard_two.selected_ids) >= 2:
            raise InvalidActionError("弃2张窗口最多选择2张牌")
        zone_id = str(action.payload.get("zone", "hand"))
        if zone_id == "hand":
            instance_id = _resolve_hand_choice_handle(
                self._session_id,
                self._session_secret,
                state,
                discard_two.window_id,
                discard_two.cards_owner_id,
                "hand",
                discard_two.snapshot_digest,
                discard_two.handles,
                action.payload.get("handle"),
            )
            if instance_id is None:
                raise InvalidActionError(
                    "待弃手牌句柄无效：伪造、跨窗口、跨会话或手牌已变化"
                )
        else:
            instance_id = action.card_instance_id
            if instance_id is None:
                raise InvalidActionError("装备区待弃牌必须指定实体牌")
            zone = _zone_from_id(zone_id, discard_two.cards_owner_id)
            if state.location_of(instance_id) != zone:
                raise InvalidActionError("装备区待弃牌不在指定装备槽中")
            if (
                discard_two.source_kind == "guanshifu_force_hit"
                and zone == ZoneRef.equipment(
                    discard_two.cards_owner_id, "weapon"
                )
            ):
                # 纵深防御：贯石斧自身不能作为发动代价（枚举层已排除，
                # 应用层再次拒绝任何指向武器槽的选择动作）。
                raise InvalidActionError(
                    "贯石斧自身不能作为发动代价的弃牌候选"
                )
        if instance_id in discard_two.selected_ids:
            raise InvalidActionError("同一张牌不能重复加入待弃集合")
        next_runtime = replace(
            runtime,
            pending_discard_two=replace(
                discard_two,
                selected_ids=(*discard_two.selected_ids, instance_id),
                selected_zones=MappingProxyType(
                    {
                        **discard_two.selected_zones,
                        instance_id: zone_id,
                    }
                ),
            ),
        )
        self._commit_runtime(runtime, next_runtime)
        return state

    def apply_unselect_discard_two(
        self,
        state: GameState,
        context: ActionContext,
        action: LegalAction,
    ) -> GameState:
        """弃2张窗口取消选择动作：把一张已选牌移出待弃集合。"""

        runtime = self._runtime
        if runtime.phase is not ProductionPhase.WEAPON_DISCARD_TWO:
            raise InvalidActionError("只有武器弃2张窗口可以取消选择待弃牌")
        discard_two = runtime.pending_discard_two
        if discard_two is None:
            raise InvalidActionError("当前没有打开的武器弃2张窗口")
        if context.actor_id != discard_two.chooser_id:
            raise InvalidActionError("只有选择者可以取消选择待弃牌")
        if action.payload.get("operation") != "unselect_discard_two":
            raise InvalidActionError("取消选择动作负载无效")
        if action.payload.get("window_id") != discard_two.window_id:
            raise InvalidActionError("取消选择动作不属于当前弃2张窗口")
        zone_id = str(action.payload.get("zone", "hand"))
        if zone_id == "hand":
            instance_id = _resolve_hand_choice_handle(
                self._session_id,
                self._session_secret,
                state,
                discard_two.window_id,
                discard_two.cards_owner_id,
                "hand",
                discard_two.snapshot_digest,
                discard_two.handles,
                action.payload.get("handle"),
            )
            if instance_id is None:
                raise InvalidActionError(
                    "待弃手牌句柄无效：伪造、跨窗口、跨会话或手牌已变化"
                )
        else:
            instance_id = action.card_instance_id
            if instance_id is None:
                raise InvalidActionError("装备区待弃牌必须指定实体牌")
        if instance_id not in discard_two.selected_ids:
            raise InvalidActionError("只能取消选择已在待弃集合中的牌")
        next_runtime = replace(
            runtime,
            pending_discard_two=replace(
                discard_two,
                selected_ids=tuple(
                    instance
                    for instance in discard_two.selected_ids
                    if instance != instance_id
                ),
                selected_zones=MappingProxyType(
                    {
                        key: value
                        for key, value in discard_two.selected_zones.items()
                        if key != instance_id
                    }
                ),
            ),
        )
        self._commit_runtime(runtime, next_runtime)
        return state

    def apply_discard_two_submit(
        self,
        state: GameState,
        context: ActionContext,
        action: LegalAction,
    ) -> GameState:
        """贯石斧弃2张窗口提交：把待弃集合一次性原子弃置并强制造成伤害。

        贯石斧（7.7）：两张牌一起选择并一起弃置的发动代价——恰好弃置
        攻击者自己手牌＋装备2张后按原【杀】参数强制造成伤害。寒冰剑
        已改用独立逐张弃置状态机（HANBING_DISCARD），不进入本窗口。"""

        runtime = self._runtime
        if runtime.phase is not ProductionPhase.WEAPON_DISCARD_TWO:
            raise InvalidActionError("只有武器弃2张窗口可以提交弃置")
        discard_two = runtime.pending_discard_two
        choice = runtime.pending_slash_choice
        if discard_two is None or choice is None:
            raise InvalidActionError("当前没有可提交的武器弃2张窗口")
        if discard_two.source_kind != "guanshifu_force_hit":
            raise InvalidActionError("弃2张窗口只支持贯石斧批量代价")
        if context.actor_id != discard_two.chooser_id:
            raise InvalidActionError("只有选择者可以提交弃置")
        if action.payload.get("operation") != "discard_two_submit":
            raise InvalidActionError("提交动作负载无效")
        if action.payload.get("window_id") != discard_two.window_id:
            raise InvalidActionError("提交动作不属于当前弃2张窗口")
        if str(action.payload.get("state_hash", "")) != state_sha256(
            canonical_state_snapshot(state)
        ):
            raise InvalidActionError("提交动作绑定的状态哈希已过期")
        if (
            discard_two.snapshot_digest is None
            or sha256_value(
                tuple(
                    state.card_ids_in(
                        ZoneRef.hand(discard_two.cards_owner_id)
                    )
                )
            )
            != discard_two.snapshot_digest
        ):
            raise InvalidActionError(
                "弃2张窗口打开后被弃手牌已变化，旧提交失败关闭"
            )
        selected_ids = tuple(discard_two.selected_ids)
        if len(selected_ids) == 0:
            raise InvalidActionError("弃2张窗口至少需要选择1张牌")
        if len(set(selected_ids)) != len(selected_ids):
            raise InvalidActionError("弃2张窗口不允许重复选择同一实体")
        if (
            discard_two.excluded_instance_id is not None
            and discard_two.excluded_instance_id in selected_ids
        ):
            # 提交时权威验证（不能只依赖枚举阶段曾经排除）：贯石斧自身
            # 不能作为发动代价，任一非法则整批不移动（USER_CONFIRMED_
            # MOBILE_RULE，2026-08-08 用户移动版实测确认）。
            raise InvalidActionError(
                "贯石斧自身不能作为发动代价；提交失败关闭且整批不移动"
            )
        hand_set = set(
            state.card_ids_in(ZoneRef.hand(discard_two.cards_owner_id))
        )
        equipment_set: set[str] = set()
        for slot in EQUIPMENT_SLOTS:
            equipment_set.update(
                state.card_ids_in(
                    ZoneRef.equipment(discard_two.cards_owner_id, slot)
                )
            )
        # 提交时权威验证：贯石斧自身（当前武器槽中的【贯石斧】实体）不能
        # 作为发动代价（USER_CONFIRMED_MOBILE_RULE）；不能只依赖枚举层
        # 的排除，提交必须再次校验。任一非法则整批不移动。
        weapon_ids = set(
            state.card_ids_in(
                ZoneRef.equipment(discard_two.cards_owner_id, "weapon")
            )
        )
        for instance_id in selected_ids:
            if instance_id in weapon_ids:
                raise InvalidActionError(
                    "贯石斧自身不能作为发动代价；整批弃置失败关闭"
                )
        for instance_id in selected_ids:
            if (
                instance_id not in hand_set
                and instance_id not in equipment_set
            ):
                raise InvalidActionError(
                    "弃2张只能包含被弃角色当前手牌与装备区牌，"
                    "不允许判定区或其他角色牌"
                )
        if len(selected_ids) != 2:
            raise InvalidActionError("贯石斧必须恰好弃置2张牌")
        # 一次性原子弃置：全部选中牌在同一窗口ID下统一离开原区域。
        next_state = state.move_cards(
            {instance_id: DISCARD_PILE for instance_id in selected_ids}
        )
        reason = "guanshifu_discard"
        events: list[GameEvent] = []
        for instance_id in selected_ids:
            source = state.location_of(instance_id)
            card_key = _card_key(next_state, instance_id)
            move_event = GameEvent(
                event_type=EventType.CARD_MOVED,
                card_instance_id=instance_id,
                card_key=card_key,
                card_user=context.actor_id,
                payload={
                    "source": _zone_payload(source),
                    "destination": _zone_payload(DISCARD_PILE),
                    "reason": reason,
                    "window_id": discard_two.window_id,
                },
            )
            lost_event = GameEvent(
                event_type=EventType.CARD_LOST,
                card_instance_id=instance_id,
                card_key=card_key,
                target_ids=(discard_two.cards_owner_id,),
                payload={
                    "reason": reason,
                    "source_zone": _zone_id(source),
                    "window_id": discard_two.window_id,
                },
            )
            discarded_event = GameEvent(
                event_type=EventType.CARD_DISCARDED,
                card_instance_id=instance_id,
                card_key=card_key,
                card_user=context.actor_id,
                target_ids=(discard_two.cards_owner_id,),
                payload={
                    "reason": reason,
                    "source_zone": _zone_id(source),
                    "window_id": discard_two.window_id,
                },
            )
            events.extend((move_event, lost_event, discarded_event))
            if source.kind is ZoneKind.EQUIPMENT and source.equipment_slot == (
                "armor"
            ):
                # 防具离区统一钩子：白银狮子被武器效果弃置时恢复1点体力。
                next_state, recovery_events = (
                    self._apply_armor_leave_recovery(
                        next_state,
                        instance_id=instance_id,
                        owner_id=discard_two.cards_owner_id,
                        reason=reason,
                    )
                )
                events.extend(recovery_events)
        self._events.extend(tuple(events))
        # 贯石斧强制命中：弃牌完成后按原【杀】参数直接造成伤害。
        pending = choice.pending_slash
        slash = self._slash_card(state, runtime, pending.slash_instance_id)
        adapter = self._formal_registry.adapter_for(slash.card_key)
        if not isinstance(adapter, SlashAdapter):
            raise ProductionBatchError("贯石斧强制命中必须使用【杀】适配器")
        base_amount = (2 if pending.boosted else 1) + (
            _weapon_damage_bonus_at_damage(
                state, pending.attacker_id, pending.target_id
            )
        )
        damage_type = (
            "火属性" if pending.fire_converted else adapter.damage_nature
        )
        next_state, next_runtime = self._apply_damage_and_maybe_chain(
            next_state,
            runtime,
            victim_id=pending.target_id,
            amount=base_amount,
            damage_type=damage_type,
            card_instance_id=pending.slash_instance_id,
            card_key=slash.card_key,
            card_user=pending.attacker_id,
            source_id=pending.attacker_id,
            kill_credit=pending.attacker_id,
            ignore_armor=pending.ignore_armor,
            payload={
                "weapon_damage_bonus": _weapon_damage_bonus_at_damage(
                    state, pending.attacker_id, pending.target_id
                ),
                "weapon_effect": "guanshifu_force_hit",
            },
            card_already_finished=True,
            resolved_reason="guanshifu_force_hit_damage",
            death_reason="guanshifu_force_hit_with_death",
            rescue_reason="guanshifu_force_hit_after_rescue",
        )
        next_runtime = replace(
            next_runtime,
            pending_slash_choice=None,
            pending_discard_two=None,
        )
        self._commit_runtime(runtime, next_runtime)
        return next_state

    # ------------------------------------------------------------------
    # 普通锦囊结算（【无中生有】与【无懈可击】）
    # ------------------------------------------------------------------

    def _trick_window_id(
        self, runtime: _BatchRuntime, decision_index: int
    ) -> str:
        group = runtime.pending_group_trick
        if group is not None:
            return (
                f"trick:{runtime.turn_number}:"
                f"{group.trick_instance_id}:gt{group.current_target_index}:"
                f"dec{decision_index}"
            )
        if runtime.pending_trick is None:
            raise ProductionBatchError("锦囊响应窗口缺少待响应的锦囊")
        return (
            f"trick:{runtime.turn_number}:"
            f"{runtime.pending_trick.trick_instance_id}:dec{decision_index}"
        )

    def apply_wuzhong_use(
        self,
        state: GameState,
        context: ActionContext,
        action: LegalAction,
        adapter: WuzhongshengyouAdapter,
    ) -> GameState:
        runtime = self._runtime
        if runtime.phase is not ProductionPhase.PLAY:
            raise InvalidActionError("【无中生有】只能在出牌阶段使用")
        if context.actor_id != runtime.current_player_id:
            raise InvalidActionError("只有当前回合角色可以使用【无中生有】")
        if action.card_instance_id is None:
            raise InvalidActionError("使用【无中生有】必须指定实体牌")
        card = state.cards_by_id[action.card_instance_id]
        if card.card_key != adapter.card_key:
            raise InvalidActionError(
                "【无中生有】动作的实体牌与适配器卡牌键不一致"
            )
        if action.target_ids != (context.actor_id,):
            raise InvalidActionError("【无中生有】只能以自己为目标")
        if state.location_of(action.card_instance_id) != ZoneRef.hand(
            context.actor_id
        ):
            raise InvalidActionError("只能使用行动角色真实手牌中的实体牌")

        next_state, move_event = self._move_to_processing(
            state, action.card_instance_id, context.actor_id, "wuzhong_use"
        )
        used_event = GameEvent(
            event_type=EventType.CARD_USED,
            card_instance_id=action.card_instance_id,
            card_key=adapter.card_key,
            card_user=context.actor_id,
            target_ids=(context.actor_id,),
            payload={"purpose": "draw_2", "card_name": adapter.card_name},
        )
        queued = self._events.extend((used_event, move_event))
        used_sequence = queued[0].sequence
        assert used_sequence is not None
        order = (
            runtime.current_player_id,
            self.opponent_of(runtime.current_player_id),
        )
        next_runtime = replace(
            runtime,
            phase=ProductionPhase.TRICK_RESPONSE,
            pending_trick=_PendingTrick(
                context.actor_id,
                context.actor_id,
                action.card_instance_id,
                adapter.card_key,
            ),
            trick_effect_active=True,
            trick_consecutive_passes=0,
            trick_response_order=order,
            trick_response_index=0,
            trick_decision_count=0,
            trick_direct_response_to=action.card_instance_id,
            response_window_id=(
                f"trick:{runtime.turn_number}:"
                f"{action.card_instance_id}:dec0"
            ),
            response_window_order=(order[0],),
            response_window_source_sequence=used_sequence,
        )
        self._commit_runtime(runtime, next_runtime)
        return next_state

    def apply_wuxie(
        self,
        state: GameState,
        context: ActionContext,
        action: LegalAction,
        adapter: WuxiekejiAdapter,
    ) -> GameState:
        del adapter
        runtime = self._runtime
        if runtime.phase not in (
            ProductionPhase.TRICK_RESPONSE,
            ProductionPhase.JUDGMENT_WUXIE,
        ):
            raise InvalidActionError("【无懈可击】只能在合法锦囊或判定无懈响应窗口使用")
        trick = runtime.pending_trick
        if trick is None:
            raise InvalidActionError("当前没有待响应的锦囊")
        if not runtime.trick_response_order:
            raise InvalidActionError("锦囊响应顺序为空")
        if runtime.trick_response_index >= len(runtime.trick_response_order):
            raise InvalidActionError("锦囊响应顺序已经耗尽")
        if (
            context.actor_id
            != runtime.trick_response_order[runtime.trick_response_index]
        ):
            raise InvalidActionError("当前不是该角色的锦囊响应时机")
        if action.card_instance_id is None:
            raise InvalidActionError("响应锦囊必须使用真实实体【无懈可击】")
        card = state.cards_by_id[action.card_instance_id]
        if card.card_key != "sgs_trick_wuxiekeji":
            raise InvalidActionError("响应锦囊的实体牌必须是【无懈可击】")
        if action.target_ids != (trick.target_id,):
            raise InvalidActionError(
                "【无懈可击】只能以当前锦囊效果对应的角色为目标"
            )
        if action.payload.get("response_to") != runtime.trick_direct_response_to:
            raise InvalidActionError(
                "【无懈可击】的响应对象与当前直接响应对象不一致，拒绝伪造或过期响应"
            )
        if action.payload.get("root_trick_instance_id") != trick.trick_instance_id:
            raise InvalidActionError(
                "【无懈可击】的根锦囊标识与当前结算锦囊不一致"
            )
        if state.location_of(action.card_instance_id) != ZoneRef.hand(
            context.actor_id
        ):
            raise InvalidActionError("只能使用行动角色真实手牌中的实体牌")

        window = self._build_window(runtime)
        wuxie_event = GameEvent(
            event_type=EventType.CARD_USED,
            card_instance_id=action.card_instance_id,
            card_key="sgs_trick_wuxiekeji",
            card_user=context.actor_id,
            target_ids=(trick.target_id,),
            payload={
                "response_to": runtime.trick_direct_response_to,
                "root_trick_instance_id": trick.trick_instance_id,
                "response_action": "use",
                "purpose": "nullify_trick_effect",
                "creates_card_used_event": True,
                "creates_card_played_event": False,
                "counts_for_use_or_play_total": True,
                "physical_or_virtual": "physical",
                "response_provider": context.actor_id,
            },
        )
        record = window.respond(context.actor_id, wuxie_event)
        assert record.response_event is not None
        next_state, move_events = self._consume_immediately(
            state, action.card_instance_id, context.actor_id, "wuxie_response"
        )
        self._events.extend((record.response_event, *move_events))
        next_index = (runtime.trick_response_index + 1) % len(
            runtime.trick_response_order
        )
        next_runtime = replace(
            runtime,
            trick_effect_active=not runtime.trick_effect_active,
            trick_consecutive_passes=0,
            trick_direct_response_to=action.card_instance_id,
            trick_response_index=next_index,
            trick_decision_count=runtime.trick_decision_count + 1,
            response_window_id=self._trick_window_id(
                runtime, runtime.trick_decision_count + 1
            ),
            response_window_order=(runtime.trick_response_order[next_index],),
        )
        self._commit_runtime(runtime, next_runtime)
        return next_state

    def apply_pass_trick_response(
        self,
        state: GameState,
        context: ActionContext,
        action: LegalAction,
    ) -> GameState:
        del action
        runtime = self._runtime
        if runtime.phase not in (
            ProductionPhase.TRICK_RESPONSE,
            ProductionPhase.JUDGMENT_WUXIE,
        ):
            raise InvalidActionError("放弃响应只能在锦囊或判定无懈响应窗口进行")
        trick = runtime.pending_trick
        if trick is None or not runtime.trick_response_order:
            raise InvalidActionError("当前没有进行中的锦囊响应")
        if runtime.trick_response_index >= len(runtime.trick_response_order):
            raise InvalidActionError("锦囊响应顺序已经耗尽")
        if (
            context.actor_id
            != runtime.trick_response_order[runtime.trick_response_index]
        ):
            raise InvalidActionError("当前不是该角色的锦囊响应时机")
        window = self._build_window(runtime)
        window.pass_response(context.actor_id)

        next_passes = runtime.trick_consecutive_passes + 1
        if next_passes >= len(runtime.trick_response_order):
            # 连续一整轮无人响应：窗口关闭，按最终生效状态结算。
            if runtime.trick_effect_active:
                if runtime.pending_judgment is not None:
                    next_state, next_runtime = self._resolve_judgment_after_wuxie(
                        state, runtime
                    )
                elif trick.trick_key == "sgs_trick_wuzhongshengyou":
                    next_state, draw_events = self._draw_cards(
                        state, trick.target_id, 2
                    )
                    self._events.extend(draw_events)
                    next_state, finish_event = self._finish_processing(
                        next_state,
                        trick.trick_instance_id,
                        "wuzhong_effect_resolved",
                    )
                    self._events.extend((finish_event,))
                    next_runtime = self._return_to_play(runtime)
                elif trick.trick_key in ZONE_CHOICE_TRICK_KEYS:
                    next_state, next_runtime = self._open_zone_choice(
                        state, runtime, trick
                    )
                elif trick.trick_key == "sgs_trick_juedou":
                    next_state, next_runtime = self._open_duel(
                        state, runtime, trick
                    )
                elif trick.trick_key == "sgs_trick_huogong":
                    next_state, next_runtime = self._open_fire_attack(
                        state, runtime, trick
                    )
                elif trick.trick_key == "sgs_trick_jiedaosharen":
                    next_state, next_runtime = self._open_borrowed_sword(
                        state, runtime, trick
                    )
                elif runtime.pending_group_trick is not None:
                    next_state, next_runtime = (
                        self._resolve_group_trick_target(state, runtime, trick)
                    )
                else:
                    raise ProductionBatchError(
                        f"卡牌{trick.trick_key!r}尚未实现锦囊生效结算；失败关闭"
                    )
            elif runtime.pending_judgment is not None:
                next_state, next_runtime = self._resolve_judgment_nullified(
                    state, runtime
                )
            elif runtime.pending_group_trick is not None:
                # 群体锦囊：一张无懈只取消当前目标的效果，
                # 当前目标取消后不响应【杀】／【闪】、不受伤或不回复，
                # 并继续推进下一目标；原锦囊不到全部目标完成不进入弃牌堆。
                next_state, next_runtime = (
                    self._resolve_group_trick_target(state, runtime, trick)
                )
            else:
                cancelled_event = GameEvent(
                    event_type=EventType.CARD_EFFECT_CANCELLED,
                    card_instance_id=trick.trick_instance_id,
                    card_key=trick.trick_key,
                    card_user=trick.user_id,
                    target_ids=(trick.target_id,),
                    payload={"reason": "nullified_by_wuxie"},
                )
                nullified_reason = (
                    "wuzhong_nullified"
                    if trick.trick_key == "sgs_trick_wuzhongshengyou"
                    else f"{trick.trick_key}_nullified"
                )
                next_state, finish_event = self._finish_processing(
                    state,
                    trick.trick_instance_id,
                    nullified_reason,
                )
                self._events.extend((cancelled_event, finish_event))
                cleared_runtime = runtime
                if trick.trick_key == "sgs_trick_jiedaosharen":
                    cleared_runtime = replace(
                        runtime, pending_borrowed_sword=None
                    )
                next_runtime = self._return_to_play(cleared_runtime)
        else:
            next_state = state
            next_index = (runtime.trick_response_index + 1) % len(
                runtime.trick_response_order
            )
            next_runtime = replace(
                runtime,
                trick_consecutive_passes=next_passes,
                trick_response_index=next_index,
                trick_decision_count=runtime.trick_decision_count + 1,
                response_window_id=self._trick_window_id(
                    runtime, runtime.trick_decision_count + 1
                ),
                response_window_order=(runtime.trick_response_order[next_index],),
            )
        self._commit_runtime(runtime, next_runtime)
        return next_state

    # ------------------------------------------------------------------
    # 【过河拆桥】【顺手牵羊】与目标区域选牌（普通锦囊第二批）
    # ------------------------------------------------------------------

    def apply_guohe_use(
        self,
        state: GameState,
        context: ActionContext,
        action: LegalAction,
        adapter: GuoheChaiqiaoAdapter,
    ) -> GameState:
        runtime = self._runtime
        if runtime.phase is not ProductionPhase.PLAY:
            raise InvalidActionError("【过河拆桥】只能在出牌阶段使用")
        if context.actor_id != runtime.current_player_id:
            raise InvalidActionError("只有当前回合角色可以使用【过河拆桥】")
        if action.card_instance_id is None or len(action.target_ids) != 1:
            raise InvalidActionError(
                "使用【过河拆桥】必须指定一张实体牌和恰好一名目标"
            )
        card = state.cards_by_id[action.card_instance_id]
        if card.card_key != adapter.card_key:
            raise InvalidActionError("【过河拆桥】动作的实体牌与适配器卡牌键不一致")
        if str(action.payload.get("card_key", "")) != adapter.card_key:
            raise InvalidActionError("【过河拆桥】动作负载与适配器卡牌键不一致")
        target = action.target_ids[0]
        if target == context.actor_id:
            raise InvalidActionError("【过河拆桥】不能以自己为目标")
        if not has_target_zone_cards(state, target):
            raise InvalidActionError(
                "【过河拆桥】目标的手牌区、装备区与判定区必须至少存在一张牌"
            )
        if state.location_of(action.card_instance_id) != ZoneRef.hand(
            context.actor_id
        ):
            raise InvalidActionError("只能使用行动角色真实手牌中的实体牌")
        return self._open_trick_use_window(
            state,
            runtime,
            context,
            action,
            adapter,
            target,
            move_reason="guohechaiqiao_use",
            purpose="discard_one_target_zone_card",
        )

    def apply_shunshou_use(
        self,
        state: GameState,
        context: ActionContext,
        action: LegalAction,
        adapter: ShunshouQianyangAdapter,
    ) -> GameState:
        runtime = self._runtime
        if runtime.phase is not ProductionPhase.PLAY:
            raise InvalidActionError("【顺手牵羊】只能在出牌阶段使用")
        if context.actor_id != runtime.current_player_id:
            raise InvalidActionError("只有当前回合角色可以使用【顺手牵羊】")
        if action.card_instance_id is None or len(action.target_ids) != 1:
            raise InvalidActionError(
                "使用【顺手牵羊】必须指定一张实体牌和恰好一名目标"
            )
        card = state.cards_by_id[action.card_instance_id]
        if card.card_key != adapter.card_key:
            raise InvalidActionError("【顺手牵羊】动作的实体牌与适配器卡牌键不一致")
        if str(action.payload.get("card_key", "")) != adapter.card_key:
            raise InvalidActionError("【顺手牵羊】动作负载与适配器卡牌键不一致")
        target = action.target_ids[0]
        if target == context.actor_id:
            raise InvalidActionError("【顺手牵羊】不能以自己为目标")
        if not is_valid_shunshou_target(state, context.actor_id, target):
            raise InvalidActionError(
                "【顺手牵羊】目标与使用者的实际距离必须为 1"
            )
        if not has_target_zone_cards(state, target):
            raise InvalidActionError(
                "【顺手牵羊】目标的手牌区、装备区与判定区必须至少存在一张牌"
            )
        if state.location_of(action.card_instance_id) != ZoneRef.hand(
            context.actor_id
        ):
            raise InvalidActionError("只能使用行动角色真实手牌中的实体牌")
        return self._open_trick_use_window(
            state,
            runtime,
            context,
            action,
            adapter,
            target,
            move_reason="shunshouqianyang_use",
            purpose="gain_one_target_zone_card",
        )

    def _open_trick_use_window(
        self,
        state: GameState,
        runtime: _BatchRuntime,
        context: ActionContext,
        action: LegalAction,
        adapter: WuzhongshengyouAdapter,
        target_id: str,
        *,
        move_reason: str,
        purpose: str,
    ) -> GameState:
        """普通锦囊使用的公共开窗步骤：实体牌进入处理区并建立响应链。"""

        if action.card_instance_id is None:
            raise InvalidActionError("使用普通锦囊必须指定实体牌")
        next_state, move_event = self._move_to_processing(
            state, action.card_instance_id, context.actor_id, move_reason
        )
        used_event = GameEvent(
            event_type=EventType.CARD_USED,
            card_instance_id=action.card_instance_id,
            card_key=adapter.card_key,
            card_user=context.actor_id,
            target_ids=(target_id,),
            payload={"purpose": purpose, "card_name": adapter.card_name},
        )
        queued = self._events.extend((used_event, move_event))
        used_sequence = queued[0].sequence
        assert used_sequence is not None
        order = (
            runtime.current_player_id,
            self.opponent_of(runtime.current_player_id),
        )
        next_runtime = replace(
            runtime,
            phase=ProductionPhase.TRICK_RESPONSE,
            pending_trick=_PendingTrick(
                context.actor_id,
                target_id,
                action.card_instance_id,
                adapter.card_key,
            ),
            trick_effect_active=True,
            trick_consecutive_passes=0,
            trick_response_order=order,
            trick_response_index=0,
            trick_decision_count=0,
            trick_direct_response_to=action.card_instance_id,
            response_window_id=(
                f"trick:{runtime.turn_number}:"
                f"{action.card_instance_id}:dec0"
            ),
            response_window_order=(order[0],),
            response_window_source_sequence=used_sequence,
        )
        self._commit_runtime(runtime, next_runtime)
        return next_state

    def _open_zone_choice(
        self,
        state: GameState,
        runtime: _BatchRuntime,
        trick: _PendingTrick,
    ) -> tuple[GameState, _BatchRuntime]:
        """目标区域选牌锦囊生效后按结算时目标状态打开选牌窗口。

        无懈链结束时若目标三个区域合计已经没有任何合法牌：不把原使用
        追溯为非法，不凭空选牌、不移动不存在的牌，原锦囊仍按已经使用
        处理并进入弃牌堆，结算移动事件记录“结算时无合法区域牌”原因。
        """
        if not has_target_zone_cards(state, trick.target_id):
            next_state, finish_event = self._finish_processing(
                state,
                trick.trick_instance_id,
                f"{trick.trick_key}_effect_resolved_no_legal_zone_card",
                extra={"no_legal_zone_card": True},
            )
            self._events.extend((finish_event,))
            return next_state, self._return_to_play(runtime)
        window_id = (
            f"zone-choice:{runtime.turn_number}:{trick.trick_instance_id}"
        )
        snapshot_digest = sha256_value(
            tuple(state.card_ids_in(ZoneRef.hand(trick.target_id)))
        )
        next_runtime = replace(
            runtime,
            phase=ProductionPhase.ZONE_CHOICE,
            pending_zone_choice=_PendingZoneChoice(
                user_id=trick.user_id,
                target_id=trick.target_id,
                trick_instance_id=trick.trick_instance_id,
                trick_key=trick.trick_key,
                window_id=window_id,
                zones=tuple(
                    _zone_id(zone) for zone in target_zone_refs(trick.target_id)
                ),
            ),
            zone_choice_snapshot_digest=snapshot_digest,
            zone_choice_handles=_zone_choice_handle_snapshot(
                self._session_id,
                self._session_secret,
                state,
                trick.target_id,
                window_id,
                snapshot_digest,
            ),
            trick_consecutive_passes=0,
            trick_response_order=(),
            trick_response_index=0,
            trick_decision_count=0,
            trick_direct_response_to=None,
            response_window_id=None,
            response_window_order=(),
            response_window_source_sequence=None,
        )
        return state, next_runtime

    def enumerate_zone_choice_actions(
        self, state: GameState, context: ActionContext
    ) -> tuple[LegalAction, ...]:
        """枚举目标区域选牌动作。

        公开区域（装备区、判定区）以明确实体候选展示；隐藏手牌区只暴露
        绑定当前状态、目标与选择窗口的不透明句柄，不泄露牌名、花色、
        点数或可识别实体ID。
        """
        runtime = self._runtime
        if runtime.phase is not ProductionPhase.ZONE_CHOICE:
            raise ProductionBatchError("目标区域选牌动作只能在选牌阶段枚举")
        choice = runtime.pending_zone_choice
        if choice is None:
            raise ProductionBatchError("目标区域选牌阶段缺少选牌窗口")
        if context.actor_id != choice.user_id:
            return ()
        if state.location_of(choice.trick_instance_id) != PROCESSING_ZONE:
            raise ProductionBatchError(
                "原锦囊已不在处理区，选牌窗口不能继续枚举动作"
            )
        state_hash = state_sha256(canonical_state_snapshot(state))
        actions: list[LegalAction] = []
        for zone_id in choice.zones:
            zone = _zone_from_id(zone_id, choice.target_id)
            base = {
                "operation": "choose_target_zone_card",
                "trick_instance_id": choice.trick_instance_id,
                "root_trick_instance_id": choice.trick_instance_id,
                "user_id": choice.user_id,
                "target_id": choice.target_id,
                "zone": zone_id,
                "window_id": choice.window_id,
                "state_hash": state_hash,
            }
            if zone.kind is ZoneKind.HAND:
                snapshot_digest = runtime.zone_choice_snapshot_digest
                if snapshot_digest is None:
                    raise ProductionBatchError(
                        "选牌窗口缺少手牌快照摘要，无法生成隐藏手牌句柄"
                    )
                if sha256_value(
                    tuple(state.card_ids_in(zone))
                ) != snapshot_digest:
                    # 手牌相对窗口打开时的快照已变化：不再铸造任何句柄，
                    # 旧句柄无法继续枚举或应用，失败关闭。
                    continue
                for instance_id in state.card_ids_in(zone):
                    actions.append(
                        LegalAction(
                            action_type=ActionType.MOVE_CARD,
                            actor_id=context.actor_id,
                            target_ids=(choice.target_id,),
                            payload={
                                **base,
                                "handle": _hand_choice_handle(
                                    self._session_id,
                                    self._session_secret,
                                    choice.window_id,
                                    choice.target_id,
                                    zone_id,
                                    snapshot_digest,
                                    instance_id,
                                ),
                            },
                        )
                    )
            else:
                for instance_id in state.card_ids_in(zone):
                    actions.append(
                        LegalAction(
                            action_type=ActionType.MOVE_CARD,
                            actor_id=context.actor_id,
                            card_instance_id=instance_id,
                            target_ids=(choice.target_id,),
                            payload={
                                **base,
                                "card_key": _card_key(state, instance_id),
                            },
                        )
                    )
        return tuple(actions)

    def apply_zone_card_choice(
        self,
        state: GameState,
        context: ActionContext,
        action: LegalAction,
        adapter: GuoheChaiqiaoAdapter | ShunshouQianyangAdapter,
    ) -> GameState:
        """权威解析目标区域选牌动作并完成实体牌移动。

        隐藏句柄由权威引擎解析为真实实体；过期或伪造句柄、区域或实体
        篡改一律失败关闭。过河拆桥直接把牌置入弃牌堆（不经过先获得再
        弃置），顺手牵羊把牌直接从原区域移入使用者手牌。
        """
        runtime = self._runtime
        if runtime.phase is not ProductionPhase.ZONE_CHOICE:
            raise InvalidActionError("目标区域选牌动作只能在选牌阶段执行")
        choice = runtime.pending_zone_choice
        if choice is None:
            raise InvalidActionError("当前没有打开的目标区域选牌窗口")
        if context.actor_id != choice.user_id:
            raise InvalidActionError("只有锦囊使用者可以选择目标区域牌")
        if adapter.card_key != choice.trick_key:
            raise InvalidActionError("选牌动作的适配器与当前选牌窗口不一致")
        if not runtime.trick_effect_active:
            raise InvalidActionError(
                "锦囊效果已被【无懈可击】无效，不能再选择目标区域牌"
            )
        if action.action_type is not ActionType.MOVE_CARD:
            raise InvalidActionError("目标区域选牌动作必须是move_card类型")
        payload = action.payload
        if str(payload.get("operation", "")) != "choose_target_zone_card":
            raise InvalidActionError("目标区域选牌动作负载无效")
        if payload.get("trick_instance_id") != choice.trick_instance_id:
            raise InvalidActionError("选牌动作绑定的锦囊实例与当前窗口不一致")
        if payload.get("root_trick_instance_id") != choice.trick_instance_id:
            raise InvalidActionError("选牌动作绑定的根锦囊与当前窗口不一致")
        if payload.get("user_id") != choice.user_id:
            raise InvalidActionError("选牌动作绑定的使用者与当前窗口不一致")
        if payload.get("target_id") != choice.target_id:
            raise InvalidActionError("选牌动作绑定的目标角色与当前窗口不一致")
        if payload.get("window_id") != choice.window_id:
            raise InvalidActionError("选牌动作绑定的选择窗口已过期")
        if payload.get("state_hash") != state_sha256(
            canonical_state_snapshot(state)
        ):
            raise InvalidActionError("选牌动作绑定的状态哈希与当前状态不一致")
        zone_id = payload.get("zone")
        if not isinstance(zone_id, str) or zone_id not in choice.zones:
            raise InvalidActionError("选牌动作绑定的目标区域不在当前窗口内")
        zone = _zone_from_id(zone_id, choice.target_id)
        if state.location_of(choice.trick_instance_id) != PROCESSING_ZONE:
            raise InvalidActionError(
                "原锦囊已不在处理区，选牌窗口已过期"
            )

        from_hidden = zone.kind is ZoneKind.HAND
        if from_hidden:
            if action.card_instance_id is not None:
                raise InvalidActionError(
                    "隐藏手牌选择不得携带实体牌ID，避免泄露牌面"
                )
            instance_id = _resolve_hand_choice_handle(
                self._session_id,
                self._session_secret,
                state,
                choice.window_id,
                choice.target_id,
                zone_id,
                runtime.zone_choice_snapshot_digest,
                runtime.zone_choice_handles,
                payload.get("handle"),
            )
            if instance_id is None:
                raise InvalidActionError(
                    "隐藏选择句柄无法解析为当前手牌中的真实实体，"
                    "句柄已过期或系伪造"
                )
        else:
            if payload.get("handle") is not None:
                raise InvalidActionError(
                    "公开区域选择不得携带隐藏选择句柄"
                )
            instance_id = action.card_instance_id
            if instance_id is None or state.location_of(instance_id) != zone:
                raise InvalidActionError(
                    "所选实体牌已不在目标区域，选择已过期"
                )
            if payload.get("card_key") != _card_key(state, instance_id):
                raise InvalidActionError(
                    "所选实体牌的卡牌键与选牌动作不一致"
                )

        if choice.trick_key == "sgs_trick_guohechaiqiao":
            next_state, effect_events = self._discard_target_zone_card(
                state,
                instance_id,
                zone,
                choice,
                context.actor_id,
                from_hidden,
            )
            self._events.extend(effect_events)
            next_state, finish_event = self._finish_processing(
                next_state,
                choice.trick_instance_id,
                "guohechaiqiao_effect_resolved",
            )
            self._events.extend((finish_event,))
        elif choice.trick_key == "sgs_trick_shunshouqianyang":
            next_state, effect_events = self._gain_target_zone_card_into_user_hand(
                state,
                instance_id,
                zone,
                choice,
                context.actor_id,
                from_hidden,
            )
            self._events.extend(effect_events)
            next_state, finish_event = self._finish_processing(
                next_state,
                choice.trick_instance_id,
                "shunshouqianyang_effect_resolved",
            )
            self._events.extend((finish_event,))
        else:
            raise InvalidActionError(
                f"卡牌{choice.trick_key!r}尚未实现目标区域选牌结算"
            )
        self._commit_runtime(runtime, self._return_to_play(runtime))
        return next_state

    def _discard_target_zone_card(
        self,
        state: GameState,
        instance_id: str,
        zone: ZoneRef,
        choice: _PendingZoneChoice,
        user_id: str,
        from_hidden: bool,
    ) -> tuple[GameState, tuple[GameEvent, ...]]:
        """【过河拆桥】把目标区域牌直接置入弃牌堆，不经过先获得再弃置。"""

        next_state = state.move_card(instance_id, DISCARD_PILE)
        extra_events: list[GameEvent] = []
        if zone == ZoneRef.equipment(choice.target_id, "armor"):
            # 防具离区统一钩子：白银狮子被弃置时恢复装备者1点体力。
            next_state, recovery_events = self._apply_armor_leave_recovery(
                next_state,
                instance_id=instance_id,
                owner_id=choice.target_id,
                reason="guohechaiqiao_discard",
            )
            extra_events.extend(recovery_events)
        card_key = _card_key(state, instance_id)
        move_event = GameEvent(
            event_type=EventType.CARD_MOVED,
            card_instance_id=instance_id,
            card_key=card_key,
            card_user=user_id,
            target_ids=(choice.target_id,),
            payload={
                "source": _zone_payload(zone),
                "destination": _zone_payload(DISCARD_PILE),
                "reason": "guohechaiqiao_effect",
                "trick_instance_id": choice.trick_instance_id,
                "from_hidden_zone": from_hidden,
                "movement": "discard_direct",
            },
        )
        lost_event = GameEvent(
            event_type=EventType.CARD_LOST,
            card_instance_id=instance_id,
            card_key=card_key,
            target_ids=(choice.target_id,),
            payload={
                "reason": "guohechaiqiao_discard",
                "source_zone": _zone_id(zone),
                "trick_instance_id": choice.trick_instance_id,
                "from_hidden_zone": from_hidden,
            },
        )
        discarded_event = GameEvent(
            event_type=EventType.CARD_DISCARDED,
            card_instance_id=instance_id,
            card_key=card_key,
            card_user=user_id,
            target_ids=(choice.target_id,),
            payload={
                "reason": "guohechaiqiao_effect",
                "source_zone": _zone_id(zone),
                "trick_instance_id": choice.trick_instance_id,
                "from_hidden_zone": from_hidden,
            },
        )
        return next_state, (
            move_event,
            lost_event,
            discarded_event,
            *extra_events,
        )

    def _gain_target_zone_card_into_user_hand(
        self,
        state: GameState,
        instance_id: str,
        zone: ZoneRef,
        choice: _PendingZoneChoice,
        user_id: str,
        from_hidden: bool,
    ) -> tuple[GameState, tuple[GameEvent, ...]]:
        """【顺手牵羊】把目标区域牌直接从原区域移入使用者手牌。"""

        destination = ZoneRef.hand(user_id)
        next_state = state.move_card(instance_id, destination)
        extra_events: list[GameEvent] = []
        if zone == ZoneRef.equipment(choice.target_id, "armor"):
            # 防具离区统一钩子：白银狮子被获得时恢复装备者1点体力。
            next_state, recovery_events = self._apply_armor_leave_recovery(
                next_state,
                instance_id=instance_id,
                owner_id=choice.target_id,
                reason="shunshouqianyang_gain",
            )
            extra_events.extend(recovery_events)
        card_key = _card_key(state, instance_id)
        move_event = GameEvent(
            event_type=EventType.CARD_MOVED,
            card_instance_id=instance_id,
            card_key=card_key,
            card_user=user_id,
            target_ids=(choice.target_id,),
            payload={
                "source": _zone_payload(zone),
                "destination": _zone_payload(destination),
                "reason": "shunshouqianyang_effect",
                "trick_instance_id": choice.trick_instance_id,
                "from_hidden_zone": from_hidden,
                "movement": "gain_direct",
            },
        )
        lost_event = GameEvent(
            event_type=EventType.CARD_LOST,
            card_instance_id=instance_id,
            card_key=card_key,
            target_ids=(choice.target_id,),
            payload={
                "reason": "shunshouqianyang_gain",
                "source_zone": _zone_id(zone),
                "trick_instance_id": choice.trick_instance_id,
                "from_hidden_zone": from_hidden,
            },
        )
        gained_event = GameEvent(
            event_type=EventType.CARD_GAINED,
            card_instance_id=instance_id,
            card_key=card_key,
            target_ids=(user_id,),
            payload={
                "reason": "shunshouqianyang_effect",
                "source_zone": _zone_id(zone),
                "trick_instance_id": choice.trick_instance_id,
                "from_hidden_zone": from_hidden,
            },
        )
        return next_state, (
            move_event,
            lost_event,
            gained_event,
            *extra_events,
        )

    # ------------------------------------------------------------------
    # 【决斗】交替打出【杀】（普通锦囊第三批）
    # ------------------------------------------------------------------

    def apply_duel_use(
        self,
        state: GameState,
        context: ActionContext,
        action: LegalAction,
        adapter: JuedouAdapter,
    ) -> GameState:
        runtime = self._runtime
        if runtime.phase is not ProductionPhase.PLAY:
            raise InvalidActionError("【决斗】只能在出牌阶段使用")
        if context.actor_id != runtime.current_player_id:
            raise InvalidActionError("只有当前回合角色可以使用【决斗】")
        if action.card_instance_id is None or len(action.target_ids) != 1:
            raise InvalidActionError(
                "使用【决斗】必须指定一张实体牌和恰好一名目标"
            )
        card = state.cards_by_id[action.card_instance_id]
        if card.card_key != adapter.card_key:
            raise InvalidActionError("【决斗】动作的实体牌与适配器卡牌键不一致")
        if str(action.payload.get("card_key", "")) != adapter.card_key:
            raise InvalidActionError("【决斗】动作负载与适配器卡牌键不一致")
        target = action.target_ids[0]
        if target == context.actor_id:
            raise InvalidActionError("【决斗】不能以自己为目标")
        if not state.players_by_id[target].alive:
            raise InvalidActionError("【决斗】不能以已死亡角色为目标")
        if state.location_of(action.card_instance_id) != ZoneRef.hand(
            context.actor_id
        ):
            raise InvalidActionError("只能使用行动角色真实手牌中的实体牌")
        return self._open_trick_use_window(
            state,
            runtime,
            context,
            action,
            adapter,
            target,
            move_reason="duel_use",
            purpose="duel_alternating_slash",
        )

    def _open_duel(
        self,
        state: GameState,
        runtime: _BatchRuntime,
        trick: _PendingTrick,
    ) -> tuple[GameState, _BatchRuntime]:
        """无懈链结束后【决斗】生效，进入交替打出【杀】状态。

        结算时重新检查目标是否存活；目标已死亡时按必要结算条件不再
        合法完成无效果结算，不向死亡角色补结算伤害。
        """
        if not state.players_by_id[trick.target_id].alive:
            next_state, finish_event = self._finish_processing(
                state,
                trick.trick_instance_id,
                "duel_effect_resolved_no_valid_target",
            )
            self._events.extend((finish_event,))
            return next_state, self._return_to_play(runtime)
        next_runtime = replace(
            runtime,
            phase=ProductionPhase.DUEL_RESPONSE,
            pending_duel=_PendingDuel(
                user_id=trick.user_id,
                target_id=trick.target_id,
                trick_instance_id=trick.trick_instance_id,
                responder_id=trick.target_id,
                opponent_id=trick.user_id,
            ),
            pending_trick=None,
            trick_effect_active=False,
            trick_consecutive_passes=0,
            trick_response_order=(),
            trick_response_index=0,
            trick_decision_count=0,
            trick_direct_response_to=None,
            response_window_id=None,
            response_window_order=(),
            response_window_source_sequence=None,
        )
        return state, next_runtime

    def enumerate_duel_response_actions(
        self, state: GameState, context: ActionContext
    ) -> tuple[LegalAction, ...]:
        """枚举【决斗】响应动作：当前响应者打出合法【杀】。

        响应【决斗】只接受当前卡名为【杀】的正式实体【杀】（普通／火／
        雷）；只在使用时临时视为【杀】的材料牌不自动计入。动作类型为
        打出（``PLAY_CARD``）。
        """
        runtime = self._runtime
        if runtime.phase is not ProductionPhase.DUEL_RESPONSE:
            raise ProductionBatchError("【决斗】响应动作只能在决斗响应阶段枚举")
        duel = runtime.pending_duel
        if duel is None:
            raise ProductionBatchError("当前没有进行中的【决斗】")
        if context.actor_id != duel.responder_id:
            return ()
        if not state.players_by_id[duel.responder_id].alive:
            # 死亡角色不能继续打出【杀】；轮到死亡角色继续响应时，
            # 只保留放弃响应路径，由 apply_pass_duel_slash 立即结束决斗。
            return ()
        actions: list[LegalAction] = []
        for instance_id in state.card_ids_in(ZoneRef.hand(context.actor_id)):
            card = state.cards_by_id[instance_id]
            if card.card_key not in SLASH_CARD_KEYS:
                continue
            actions.append(
                LegalAction(
                    action_type=ActionType.PLAY_CARD,
                    actor_id=context.actor_id,
                    card_instance_id=instance_id,
                    target_ids=(duel.target_id,),
                    payload={
                        "operation": "play_slash_for_duel",
                        "card_key": card.card_key,
                        "card_name": card.card_name,
                        "response_to": duel.trick_instance_id,
                        "root_trick_instance_id": duel.trick_instance_id,
                        "duel_user_id": duel.user_id,
                        "duel_target_id": duel.target_id,
                        "duel_response_index": duel.response_index,
                        "duel_round": duel.round_index,
                    },
                )
            )
        # CP-04P 丈八蛇矛（7.8 当前确认）：响应【决斗】需要打出【杀】时
        # 同样可以把两张手牌当作普通【杀】打出；材料对只通过不透明句柄
        # 暴露。
        if (
            equipped_weapon_key(state, context.actor_id)
            == "sgs_weapon_zhangbashemao"
            and len(state.card_ids_in(ZoneRef.hand(context.actor_id))) >= 2
        ):
            # G-003 统一 fail-closed：丈八蛇矛保持 PARTIAL（VIRTUAL_CARD_
            # SUBCARD_LIFECYCLE_RULE_GAP），在正式枚举 virtual proposal
            # 之前直接门禁拒绝（decision=play_slash，手牌≥2时抛
            # UnsupportedRuleError），不生成 virtual:zhangba:* candidate
            # 后再撞公共实体验证器；不恢复全局 virtual: 豁免。
            check_weapon_skill_gate(
                state,
                actor_id=context.actor_id,
                decision="play_slash",
            )
            window_id = (
                f"duel-zhangba:{runtime.turn_number}:"
                f"{duel.trick_instance_id}"
            )
            hand_ids = tuple(
                state.card_ids_in(ZoneRef.hand(context.actor_id))
            )
            snapshot_digest = sha256_value(hand_ids)
            for index, first in enumerate(hand_ids):
                for second in hand_ids[index + 1 :]:
                    material_ids = (first, second)
                    material_handle = _zhangba_material_handle(
                        self._session_id,
                        self._session_secret,
                        window_id,
                        context.actor_id,
                        snapshot_digest,
                        material_ids,
                    )
                    virtual_id = (
                        f"virtual:zhangba:{runtime.turn_number}:"
                        f"{first}:{second}"
                    )
                    actions.append(
                        LegalAction(
                            action_type=ActionType.PLAY_CARD,
                            actor_id=context.actor_id,
                            card_instance_id=virtual_id,
                            target_ids=(duel.target_id,),
                            payload={
                                "operation": "play_slash_for_duel",
                                "card_key": "sgs_basic_sha",
                                "card_name": "杀",
                                "response_to": duel.trick_instance_id,
                                "root_trick_instance_id": (
                                    duel.trick_instance_id
                                ),
                                "duel_user_id": duel.user_id,
                                "duel_target_id": duel.target_id,
                                "duel_response_index": (
                                    duel.response_index
                                ),
                                "duel_round": duel.round_index,
                                "handle": material_handle,
                                "window_id": window_id,
                                "zhangba_virtual": True,
                            },
                        )
                    )
        return tuple(actions)

    def apply_duel_slash_play(
        self,
        state: GameState,
        context: ActionContext,
        action: LegalAction,
        adapter: object,
    ) -> GameState:
        del adapter
        runtime = self._runtime
        if runtime.phase is not ProductionPhase.DUEL_RESPONSE:
            raise InvalidActionError("响应【决斗】只能在决斗响应阶段进行")
        duel = runtime.pending_duel
        if duel is None:
            raise InvalidActionError("当前没有进行中的【决斗】")
        if context.actor_id != duel.responder_id:
            raise InvalidActionError("只有当前响应者可以打出【杀】")
        if not state.players_by_id[duel.responder_id].alive:
            raise InvalidActionError("死亡角色不能继续打出【杀】；决斗应当立即结束")
        if action.action_type is not ActionType.PLAY_CARD:
            raise InvalidActionError("响应【决斗】的【杀】动作类型必须是打出")
        if action.card_instance_id is None:
            raise InvalidActionError("响应【决斗】必须指定真实实体【杀】")
        payload = action.payload
        if str(payload.get("operation", "")) != "play_slash_for_duel":
            raise InvalidActionError("【决斗】响应动作负载无效")
        if payload.get("root_trick_instance_id") != duel.trick_instance_id:
            raise InvalidActionError(
                "【决斗】响应动作绑定的根锦囊与当前结算不一致"
            )
        if payload.get("response_to") != duel.trick_instance_id:
            raise InvalidActionError(
                "【决斗】响应动作的响应对象与当前结算不一致"
            )
        if payload.get("duel_response_index") != duel.response_index:
            raise InvalidActionError(
                "【决斗】响应动作绑定的响应轮次已过期"
            )
        if payload.get("duel_round") != duel.round_index:
            raise InvalidActionError("【决斗】响应动作绑定的回合轮次已过期")

        zhangba_virtual = bool(payload.get("zhangba_virtual"))
        if zhangba_virtual:
            # 丈八蛇矛虚拟打出：响应【决斗】时把两张手牌当作普通【杀】
            # 打出；材料对只通过不透明句柄解析。
            if (
                equipped_weapon_key(state, context.actor_id)
                != "sgs_weapon_zhangbashemao"
            ):
                raise InvalidActionError(
                    "丈八蛇矛在选择前已失去，旧转化动作失败关闭"
                )
            window_id = (
                f"duel-zhangba:{runtime.turn_number}:"
                f"{duel.trick_instance_id}"
            )
            if payload.get("window_id") != window_id:
                raise InvalidActionError("丈八材料选择窗口已过期")
            material_ids = _resolve_zhangba_handle_direct(
                self._session_id,
                self._session_secret,
                state,
                window_id,
                context.actor_id,
                payload.get("handle"),
            )
            if material_ids is None:
                raise InvalidActionError(
                    "丈八材料句柄无效：伪造、跨窗口、跨会话或手牌已变化"
                )
            virtual_id = (
                f"virtual:zhangba:{runtime.turn_number}:"
                f"{material_ids[0]}:{material_ids[1]}"
            )
            if action.card_instance_id != virtual_id:
                raise InvalidActionError(
                    "丈八虚拟杀动作与材料组合不一致"
                )
            check_weapon_skill_gate(
                state,
                actor_id=context.actor_id,
                decision="play_slash",
            )
            next_state, material_events = (
                self._discard_zhangba_materials(
                    state,
                    actor_id=context.actor_id,
                    material_ids=material_ids,
                    window_id=(
                        f"zhangba-materials:{runtime.turn_number}:"
                        f"{context.actor_id}"
                    ),
                    purpose="duel_slash_response",
                )
            )
            played_event = GameEvent(
                event_type=EventType.CARD_PLAYED,
                card_instance_id=virtual_id,
                card_key="sgs_basic_sha",
                card_user=context.actor_id,
                target_ids=(duel.target_id,),
                payload={
                    "response_to": duel.trick_instance_id,
                    "root_trick_instance_id": duel.trick_instance_id,
                    "response_action": "play",
                    "purpose": "duel_slash_response",
                    "creates_card_used_event": False,
                    "creates_card_played_event": True,
                    "counts_for_use_or_play_total": True,
                    "physical_or_virtual": "virtual",
                    "virtual_source": "sgs_weapon_zhangbashemao",
                    "material_card_instance_ids": list(material_ids),
                    "response_provider": context.actor_id,
                    "duel_user_id": duel.user_id,
                    "duel_target_id": duel.target_id,
                    "duel_response_index": duel.response_index,
                    "duel_round": duel.round_index,
                    "next_responder": duel.opponent_id,
                },
            )
            self._events.extend((played_event, *material_events))
            next_round = (duel.response_index + 1) // 2
            next_duel = replace(
                duel,
                responder_id=duel.opponent_id,
                opponent_id=duel.responder_id,
                round_index=next_round,
                response_index=duel.response_index + 1,
                slash_sequence=(*duel.slash_sequence, virtual_id),
            )
            if not state.players_by_id[next_duel.responder_id].alive:
                next_state, finish_event = self._finish_processing(
                    next_state,
                    duel.trick_instance_id,
                    "duel_resolved_responder_dead",
                    extra={
                        "dead_responder": next_duel.responder_id,
                        "root_trick_instance_id": duel.trick_instance_id,
                    },
                )
                self._events.extend((finish_event,))
                next_runtime = self._return_to_play(runtime)
            else:
                next_runtime = replace(
                    runtime,
                    pending_duel=next_duel,
                )
            self._commit_runtime(runtime, next_runtime)
            return next_state

        card = state.cards_by_id[action.card_instance_id]
        if card.card_key not in SLASH_CARD_KEYS:
            raise InvalidActionError(
                "响应【决斗】的实体牌必须是当前卡名为【杀】的正式实体【杀】"
            )
        if state.location_of(action.card_instance_id) != ZoneRef.hand(
            context.actor_id
        ):
            raise InvalidActionError("只能打出行动角色真实手牌中的实体牌")
        check_weapon_skill_gate(
            state,
            actor_id=context.actor_id,
            decision="play_slash",
        )

        played_event = GameEvent(
            event_type=EventType.CARD_PLAYED,
            card_instance_id=action.card_instance_id,
            card_key=card.card_key,
            card_user=context.actor_id,
            target_ids=(duel.target_id,),
            payload={
                "response_to": duel.trick_instance_id,
                "root_trick_instance_id": duel.trick_instance_id,
                "response_action": "play",
                "purpose": "duel_slash_response",
                "creates_card_used_event": False,
                "creates_card_played_event": True,
                "counts_for_use_or_play_total": True,
                "physical_or_virtual": "physical",
                "response_provider": context.actor_id,
                "duel_user_id": duel.user_id,
                "duel_target_id": duel.target_id,
                "duel_response_index": duel.response_index,
                "duel_round": duel.round_index,
                "next_responder": duel.opponent_id,
            },
        )
        next_state, move_events = self._consume_immediately(
            state, action.card_instance_id, context.actor_id, "duel_slash_response"
        )
        self._events.extend((played_event, *move_events))
        next_round = (duel.response_index + 1) // 2
        next_duel = replace(
            duel,
            responder_id=duel.opponent_id,
            opponent_id=duel.responder_id,
            round_index=next_round,
            response_index=duel.response_index + 1,
            slash_sequence=(*duel.slash_sequence, action.card_instance_id),
        )
        if not state.players_by_id[next_duel.responder_id].alive:
            # 死亡角色不能继续打出【杀】；轮到死亡角色继续响应时，
            # 后续【决斗】立即结束，不向死亡角色凭空补结算伤害。
            next_state, finish_event = self._finish_processing(
                next_state,
                duel.trick_instance_id,
                "duel_resolved_responder_dead",
                extra={
                    "dead_responder": next_duel.responder_id,
                    "root_trick_instance_id": duel.trick_instance_id,
                },
            )
            self._events.extend((finish_event,))
            next_runtime = self._return_to_play(runtime)
        else:
            next_runtime = replace(
                runtime,
                pending_duel=next_duel,
            )
        self._commit_runtime(runtime, next_runtime)
        return next_state

    def apply_pass_duel_slash(
        self,
        state: GameState,
        context: ActionContext,
        action: LegalAction,
    ) -> GameState:
        del action
        runtime = self._runtime
        if runtime.phase is not ProductionPhase.DUEL_RESPONSE:
            raise InvalidActionError("放弃【决斗】响应只能在决斗响应阶段进行")
        duel = runtime.pending_duel
        if duel is None:
            raise InvalidActionError("当前没有进行中的【决斗】")
        if context.actor_id != duel.responder_id:
            raise InvalidActionError("只有当前响应者可以放弃响应")
        if not state.players_by_id[duel.responder_id].alive:
            # 轮到死亡角色继续响应：后续【决斗】立即结束，
            # 不向死亡角色凭空补结算一次伤害。
            next_state, finish_event = self._finish_processing(
                state,
                duel.trick_instance_id,
                "duel_resolved_responder_dead",
                extra={
                    "dead_responder": duel.responder_id,
                    "root_trick_instance_id": duel.trick_instance_id,
                },
            )
            self._events.extend((finish_event,))
            next_runtime = self._return_to_play(runtime)
            self._commit_runtime(runtime, next_runtime)
            return next_state
        # 当前响应者停止打出【杀】：受到另1名仍参与角色造成的1点无属性伤害。
        next_state, next_runtime = self._apply_trick_damage(
            state,
            victim_id=duel.responder_id,
            source_id=duel.opponent_id,
            card_instance_id=duel.trick_instance_id,
            card_key="sgs_trick_juedou",
            card_user=duel.user_id,
            damage_type="无属性",
            resolved_reason="duel_damage_resolved",
            death_reason="duel_damage_resolved_with_death",
            rescue_reason="duel_damage_resolved_after_rescue",
        )
        self._commit_runtime(runtime, next_runtime)
        return next_state

    # ------------------------------------------------------------------
    # 【火攻】展示与同花色弃置（普通锦囊第三批）
    # ------------------------------------------------------------------

    def apply_fire_attack_use(
        self,
        state: GameState,
        context: ActionContext,
        action: LegalAction,
        adapter: HuogongAdapter,
    ) -> GameState:
        runtime = self._runtime
        if runtime.phase is not ProductionPhase.PLAY:
            raise InvalidActionError("【火攻】只能在出牌阶段使用")
        if context.actor_id != runtime.current_player_id:
            raise InvalidActionError("只有当前回合角色可以使用【火攻】")
        if action.card_instance_id is None or len(action.target_ids) != 1:
            raise InvalidActionError(
                "使用【火攻】必须指定一张实体牌和恰好一名目标"
            )
        card = state.cards_by_id[action.card_instance_id]
        if card.card_key != adapter.card_key:
            raise InvalidActionError("【火攻】动作的实体牌与适配器卡牌键不一致")
        if str(action.payload.get("card_key", "")) != adapter.card_key:
            raise InvalidActionError("【火攻】动作负载与适配器卡牌键不一致")
        target = action.target_ids[0]
        if not state.players_by_id[target].alive:
            raise InvalidActionError("【火攻】不能以已死亡角色为目标")
        if not state.card_ids_in(ZoneRef.hand(target)):
            raise InvalidActionError(
                "【火攻】目标必须至少有一张手牌；装备区与判定区的牌不能代替"
            )
        if state.location_of(action.card_instance_id) != ZoneRef.hand(
            context.actor_id
        ):
            raise InvalidActionError("只能使用行动角色真实手牌中的实体牌")
        return self._open_trick_use_window(
            state,
            runtime,
            context,
            action,
            adapter,
            target,
            move_reason="fire_attack_use",
            purpose="fire_attack_reveal_and_discard",
        )

    def _open_fire_attack(
        self,
        state: GameState,
        runtime: _BatchRuntime,
        trick: _PendingTrick,
    ) -> tuple[GameState, _BatchRuntime]:
        """无懈链结束后【火攻】生效，重新检查目标手牌并打开展示窗口。

        结算到展示步骤时若目标已无手牌：不把原使用追溯为非法，不凭空
        展示、不弃置、不造成伤害，本次【火攻】无效果完成并记录原因。
        """
        if not state.card_ids_in(ZoneRef.hand(trick.target_id)):
            next_state, finish_event = self._finish_processing(
                state,
                trick.trick_instance_id,
                "fire_attack_effect_resolved_no_legal_reveal_card",
            )
            self._events.extend((finish_event,))
            return next_state, self._return_to_play(runtime)
        window_id = (
            f"fire-reveal:{runtime.turn_number}:{trick.trick_instance_id}"
        )
        next_runtime = replace(
            runtime,
            phase=ProductionPhase.FIRE_ATTACK_REVEAL,
            pending_fire_attack=_PendingFireAttack(
                user_id=trick.user_id,
                target_id=trick.target_id,
                trick_instance_id=trick.trick_instance_id,
                reveal_window_id=window_id,
            ),
            fire_attack_reveal_handles=_fire_reveal_handle_snapshot(
                self._session_id,
                self._session_secret,
                state,
                trick.target_id,
                window_id,
            ),
            pending_trick=None,
            trick_effect_active=False,
            trick_consecutive_passes=0,
            trick_response_order=(),
            trick_response_index=0,
            trick_decision_count=0,
            trick_direct_response_to=None,
            response_window_id=None,
            response_window_order=(),
            response_window_source_sequence=None,
        )
        return state, next_runtime

    def enumerate_fire_attack_actions(
        self, state: GameState, context: ActionContext
    ) -> tuple[LegalAction, ...]:
        """枚举【火攻】展示与同花色弃置动作。

        展示动作由目标角色自己选择，只暴露绑定当前选择窗口的不透明
        句柄，不泄露未展示手牌的实体ID、牌名、花色、点数或可识别
        摘要；弃置动作由使用者从当前手牌中同花色的真实实体中选择。
        """
        runtime = self._runtime
        fire = runtime.pending_fire_attack
        if fire is None:
            return ()
        if runtime.phase is ProductionPhase.FIRE_ATTACK_REVEAL:
            if context.actor_id != fire.target_id:
                return ()
            if fire.revealed_instance_id is not None:
                return ()
            state_hash = state_sha256(canonical_state_snapshot(state))
            actions: list[LegalAction] = []
            for instance_id in state.card_ids_in(ZoneRef.hand(fire.target_id)):
                actions.append(
                    LegalAction(
                        action_type=ActionType.RESPOND,
                        actor_id=context.actor_id,
                        target_ids=(fire.target_id,),
                        payload={
                            "operation": "reveal_card_for_fire_attack",
                            "trick_instance_id": fire.trick_instance_id,
                            "root_trick_instance_id": fire.trick_instance_id,
                            "user_id": fire.user_id,
                            "target_id": fire.target_id,
                            "window_id": fire.reveal_window_id,
                            "state_hash": state_hash,
                            "handle": _fire_reveal_handle(
                                self._session_id,
                                self._session_secret,
                                fire.reveal_window_id,
                                instance_id,
                            ),
                        },
                    )
                )
            return tuple(actions)
        if runtime.phase is ProductionPhase.FIRE_ATTACK_DISCARD:
            if context.actor_id != fire.user_id:
                return ()
            if fire.revealed_suit is None or fire.revealed_instance_id is None:
                raise ProductionBatchError(
                    "【火攻】弃牌阶段缺少已展示牌信息"
                )
            actions = []
            for instance_id in state.card_ids_in(ZoneRef.hand(fire.user_id)):
                card = state.cards_by_id[instance_id]
                if card.suit != fire.revealed_suit:
                    continue
                actions.append(
                    LegalAction(
                        action_type=ActionType.MOVE_CARD,
                        actor_id=context.actor_id,
                        card_instance_id=instance_id,
                        target_ids=(fire.target_id,),
                        payload={
                            "operation": "discard_same_suit_for_fire_attack",
                            "card_key": card.card_key,
                            "trick_instance_id": fire.trick_instance_id,
                            "root_trick_instance_id": fire.trick_instance_id,
                            "user_id": fire.user_id,
                            "target_id": fire.target_id,
                            "revealed_instance_id": fire.revealed_instance_id,
                            "revealed_suit": fire.revealed_suit,
                        },
                    )
                )
            return tuple(actions)
        return ()

    def apply_fire_attack_reveal(
        self,
        state: GameState,
        context: ActionContext,
        action: LegalAction,
        adapter: object,
    ) -> GameState:
        del adapter
        runtime = self._runtime
        if runtime.phase is not ProductionPhase.FIRE_ATTACK_REVEAL:
            raise InvalidActionError("展示【火攻】手牌只能在展示阶段进行")
        fire = runtime.pending_fire_attack
        if fire is None:
            raise InvalidActionError("当前没有进行中的【火攻】")
        if context.actor_id != fire.target_id:
            raise InvalidActionError("只有【火攻】目标可以选择展示牌")
        if fire.revealed_instance_id is not None:
            raise InvalidActionError("【火攻】展示已经完成，不能重复展示")
        payload = action.payload
        if str(payload.get("operation", "")) != "reveal_card_for_fire_attack":
            raise InvalidActionError("【火攻】展示动作负载无效")
        if payload.get("trick_instance_id") != fire.trick_instance_id:
            raise InvalidActionError("展示动作绑定的锦囊与当前结算不一致")
        if payload.get("root_trick_instance_id") != fire.trick_instance_id:
            raise InvalidActionError("展示动作绑定的根锦囊与当前结算不一致")
        if payload.get("user_id") != fire.user_id:
            raise InvalidActionError("展示动作绑定的使用者与当前结算不一致")
        if payload.get("target_id") != fire.target_id:
            raise InvalidActionError("展示动作绑定的目标与当前结算不一致")
        if payload.get("window_id") != fire.reveal_window_id:
            raise InvalidActionError("展示动作绑定的选择窗口已过期")
        if payload.get("state_hash") != state_sha256(
            canonical_state_snapshot(state)
        ):
            raise InvalidActionError("展示动作绑定的状态哈希与当前状态不一致")
        if action.card_instance_id is not None:
            raise InvalidActionError(
                "目标展示选择不得携带实体牌ID，避免在决策前泄露牌面"
            )
        instance_id = _resolve_fire_reveal_handle(
            self._session_id,
            self._session_secret,
            state,
            fire.reveal_window_id,
            fire.target_id,
            payload.get("handle"),
        )
        if instance_id is None:
            raise InvalidActionError(
                "展示句柄无法解析为当前手牌中的真实实体，句柄已过期或系伪造"
            )
        card = state.cards_by_id[instance_id]
        reveal_event = GameEvent(
            event_type=EventType.CARD_REVEALED,
            card_instance_id=instance_id,
            card_key=card.card_key,
            card_user=fire.target_id,
            target_ids=(fire.target_id,),
            payload={
                "reason": "fire_attack_reveal",
                "trick_instance_id": fire.trick_instance_id,
                "root_trick_instance_id": fire.trick_instance_id,
                "revealed_by": fire.target_id,
                "card_name": card.card_name,
                "suit": card.suit,
                "rank": card.rank,
            },
        )
        self._events.extend((reveal_event,))
        next_runtime = replace(
            runtime,
            phase=ProductionPhase.FIRE_ATTACK_DISCARD,
            pending_fire_attack=replace(
                fire,
                revealed_instance_id=instance_id,
                revealed_suit=card.suit,
            ),
            fire_attack_reveal_handles=MappingProxyType({}),
        )
        self._commit_runtime(runtime, next_runtime)
        return state

    def apply_fire_attack_discard(
        self,
        state: GameState,
        context: ActionContext,
        action: LegalAction,
        adapter: object,
    ) -> GameState:
        del adapter
        runtime = self._runtime
        if runtime.phase is not ProductionPhase.FIRE_ATTACK_DISCARD:
            raise InvalidActionError("弃置同花色手牌只能在【火攻】弃牌阶段进行")
        fire = runtime.pending_fire_attack
        if fire is None:
            raise InvalidActionError("当前没有进行中的【火攻】")
        if context.actor_id != fire.user_id:
            raise InvalidActionError("只有【火攻】使用者可以选择弃置")
        if fire.revealed_suit is None or fire.revealed_instance_id is None:
            raise InvalidActionError("【火攻】弃牌阶段缺少已展示牌信息")
        payload = action.payload
        if str(payload.get("operation", "")) != "discard_same_suit_for_fire_attack":
            raise InvalidActionError("【火攻】弃置动作负载无效")
        if payload.get("root_trick_instance_id") != fire.trick_instance_id:
            raise InvalidActionError("弃置动作绑定的根锦囊与当前结算不一致")
        if payload.get("user_id") != fire.user_id:
            raise InvalidActionError("弃置动作绑定的使用者与当前结算不一致")
        if payload.get("target_id") != fire.target_id:
            raise InvalidActionError("弃置动作绑定的目标与当前结算不一致")
        if payload.get("revealed_instance_id") != fire.revealed_instance_id:
            raise InvalidActionError("弃置动作绑定的展示牌与当前结算不一致")
        if payload.get("revealed_suit") != fire.revealed_suit:
            raise InvalidActionError("弃置动作绑定的展示花色与当前结算不一致")
        if action.card_instance_id is None:
            raise InvalidActionError("弃置同花色牌必须指定真实实体牌")
        if action.card_instance_id == fire.trick_instance_id:
            raise InvalidActionError("原【火攻】已在处理区，不能作为弃置材料")
        card = state.cards_by_id[action.card_instance_id]
        if card.suit != fire.revealed_suit:
            raise InvalidActionError(
                "只能弃置与展示牌花色相同的当前手牌实体"
            )
        if state.location_of(action.card_instance_id) != ZoneRef.hand(
            fire.user_id
        ):
            raise InvalidActionError("只能弃置使用者当前手牌中的真实实体牌")
        if payload.get("card_key") != card.card_key:
            raise InvalidActionError("弃置动作的卡牌键与实体牌不一致")

        source = ZoneRef.hand(fire.user_id)
        next_state = state.move_card(action.card_instance_id, DISCARD_PILE)
        card_key = _card_key(state, action.card_instance_id)
        self._events.extend(
            (
                GameEvent(
                    event_type=EventType.CARD_MOVED,
                    card_instance_id=action.card_instance_id,
                    card_key=card_key,
                    card_user=fire.user_id,
                    target_ids=(fire.target_id,),
                    payload={
                        "source": _zone_payload(source),
                        "destination": _zone_payload(DISCARD_PILE),
                        "reason": "fire_attack_discard_same_suit",
                        "trick_instance_id": fire.trick_instance_id,
                        "revealed_instance_id": fire.revealed_instance_id,
                        "revealed_suit": fire.revealed_suit,
                    },
                ),
                GameEvent(
                    event_type=EventType.CARD_LOST,
                    card_instance_id=action.card_instance_id,
                    card_key=card_key,
                    target_ids=(fire.user_id,),
                    payload={
                        "reason": "fire_attack_discard_same_suit",
                        "source_zone": _zone_id(source),
                        "trick_instance_id": fire.trick_instance_id,
                    },
                ),
                GameEvent(
                    event_type=EventType.CARD_DISCARDED,
                    card_instance_id=action.card_instance_id,
                    card_key=card_key,
                    card_user=fire.user_id,
                    target_ids=(fire.target_id,),
                    payload={
                        "reason": "fire_attack_discard_same_suit",
                        "source_zone": _zone_id(source),
                        "trick_instance_id": fire.trick_instance_id,
                        "revealed_instance_id": fire.revealed_instance_id,
                        "revealed_suit": fire.revealed_suit,
                    },
                ),
            )
        )
        next_state, next_runtime = self._apply_trick_damage(
            next_state,
            victim_id=fire.target_id,
            source_id=fire.user_id,
            card_instance_id=fire.trick_instance_id,
            card_key="sgs_trick_huogong",
            card_user=fire.user_id,
            damage_type="火属性",
            resolved_reason="fire_attack_effect_resolved",
            death_reason="fire_attack_damage_resolved_with_death",
            rescue_reason="fire_attack_damage_resolved_after_rescue",
        )
        self._commit_runtime(runtime, next_runtime)
        return next_state

    def apply_pass_fire_attack_discard(
        self,
        state: GameState,
        context: ActionContext,
        action: LegalAction,
    ) -> GameState:
        del action
        runtime = self._runtime
        if runtime.phase is not ProductionPhase.FIRE_ATTACK_DISCARD:
            raise InvalidActionError("放弃弃置只能在【火攻】弃牌阶段进行")
        fire = runtime.pending_fire_attack
        if fire is None:
            raise InvalidActionError("当前没有进行中的【火攻】")
        if context.actor_id != fire.user_id:
            raise InvalidActionError("只有【火攻】使用者可以选择不弃置")
        next_state, finish_event = self._finish_processing(
            state,
            fire.trick_instance_id,
            "fire_attack_effect_resolved_no_discard",
            extra={"revealed_instance_id": fire.revealed_instance_id},
        )
        self._events.extend((finish_event,))
        next_runtime = self._return_to_play(runtime)
        self._commit_runtime(runtime, next_runtime)
        return next_state

    # ------------------------------------------------------------------
    # 武器牌本体与【借刀杀人】（CP-04K）
    # ------------------------------------------------------------------

    def apply_weapon_use(
        self,
        state: GameState,
        context: ActionContext,
        action: LegalAction,
        adapter: WeaponCardAdapter,
    ) -> GameState:
        """从手牌主动装备武器：处理区→weapon槽，同槽替换原子化（CP-04K）。"""
        return self._apply_equipment_use(
            state,
            context,
            action,
            adapter,
            slot="weapon",
            operation="use_weapon",
            reason_prefix="weapon_equip",
        )

    def apply_armor_use(
        self,
        state: GameState,
        context: ActionContext,
        action: LegalAction,
        adapter: object,
    ) -> GameState:
        """从手牌主动装备防具：处理区→armor槽，同槽替换原子化（CP-04M）。

        旧防具因替换进入弃牌堆并触发统一装备离区事件；白银狮子离区恢复
        挂在统一离区钩子上，不在单张锦囊代码里特殊处理。"""
        return self._apply_equipment_use(
            state,
            context,
            action,
            adapter,
            slot="armor",
            operation="use_armor",
            reason_prefix="armor_equip",
        )

    def apply_mount_use(
        self,
        state: GameState,
        context: ActionContext,
        action: LegalAction,
        adapter: object,
    ) -> GameState:
        """从手牌主动装备坐骑：处理区→坐骑栏，同栏位替换原子化（CP-04N）。

        坐骑栏由实体牌 equipment_slot 决定（attack_horse／defense_horse）；
        进攻与防御坐骑可同时存在、互不覆盖；坐骑离区不触发防具恢复。"""
        card = state.cards_by_id[action.card_instance_id]
        slot = card.equipment_slot
        if slot not in ("attack_horse", "defense_horse"):
            raise InvalidActionError("该实体牌不是坐骑栏装备牌")
        return self._apply_equipment_use(
            state,
            context,
            action,
            adapter,
            slot=slot,
            operation="use_mount",
            reason_prefix="mount_equip",
        )

    def _apply_equipment_use(
        self,
        state: GameState,
        context: ActionContext,
        action: LegalAction,
        adapter: object,
        *,
        slot: str,
        operation: str,
        reason_prefix: str,
    ) -> GameState:
        """通用装备主动使用：手牌→处理区→装备槽，同槽替换原子化。

        旧装备因替换进入弃牌堆，不伪造“玩家主动弃置”；装备、移除与
        替换三个最小装备事件按固定顺序登记，进入事件哈希链；防具槽替换
        时旧防具离区先挂统一离区钩子（白银狮子恢复），再登记移除事件。"""

        runtime = self._runtime
        if runtime.phase is not ProductionPhase.PLAY:
            raise InvalidActionError("装备只能在出牌阶段进行")
        if context.actor_id != runtime.current_player_id:
            raise InvalidActionError("只有当前回合角色可以装备")
        if action.card_instance_id is None:
            raise InvalidActionError("装备必须指定实体牌")
        card = state.cards_by_id[action.card_instance_id]
        if card.card_key != getattr(adapter, "card_key", None):
            raise InvalidActionError("装备动作的实体牌与适配器卡牌键不一致")
        if str(action.payload.get("card_key", "")) != getattr(
            adapter, "card_key", None
        ):
            raise InvalidActionError("装备动作负载与适配器卡牌键不一致")
        if state.location_of(action.card_instance_id) != ZoneRef.hand(
            context.actor_id
        ):
            raise InvalidActionError("只能装备行动角色真实手牌中的实体牌")
        if card.card_type != "装备牌" or card.equipment_slot != slot:
            raise InvalidActionError(f"该实体牌不是{slot}槽装备牌")
        if action.target_ids != (context.actor_id,):
            raise InvalidActionError(f"{slot}装备只能以自己为目标")

        next_state, enter_event = self._move_to_processing(
            state,
            action.card_instance_id,
            context.actor_id,
            f"{reason_prefix}:enter_processing",
        )
        used_event = GameEvent(
            event_type=EventType.CARD_USED,
            card_instance_id=action.card_instance_id,
            card_key=card.card_key,
            card_user=context.actor_id,
            target_ids=(context.actor_id,),
            payload={
                "purpose": "equip",
                "equipment_slot": slot,
                "card_name": getattr(adapter, "card_name", card.card_name),
            },
        )
        self._events.extend((used_event, enter_event))

        target_slot = ZoneRef.equipment(context.actor_id, slot)
        old_ids = next_state.card_ids_in(target_slot)
        if len(old_ids) > 1:
            raise ProductionBatchError(f"{slot}槽必须至多包含一张装备牌")
        equip_events: list[GameEvent] = []
        if old_ids:
            old_id = old_ids[0]
            next_state = next_state.move_cards(
                {
                    old_id: DISCARD_PILE,
                    action.card_instance_id: target_slot,
                }
            )
            if slot == "armor":
                # 统一装备离区钩子：白银狮子离开装备区时恢复1点体力。
                next_state, recovery_events = self._apply_armor_leave_recovery(
                    next_state,
                    instance_id=old_id,
                    owner_id=context.actor_id,
                    reason="equip_replaced",
                )
                equip_events.extend(recovery_events)
            equip_events.append(
                GameEvent(
                    event_type=EventType.CARD_MOVED,
                    card_instance_id=old_id,
                    card_key=_card_key(state, old_id),
                    card_user=context.actor_id,
                    payload={
                        "source": _zone_payload(target_slot),
                        "destination": _zone_payload(DISCARD_PILE),
                        "reason": f"{reason_prefix}:replaced_old_to_discard",
                        "equipment_slot": slot,
                    },
                )
            )
            equip_events.append(
                GameEvent(
                    event_type=EventType.EQUIPMENT_REMOVED,
                    card_instance_id=old_id,
                    card_key=_card_key(state, old_id),
                    equipment_owner=context.actor_id,
                    target_ids=(context.actor_id,),
                    payload={"slot": slot, "reason": "replaced"},
                )
            )
            equip_events.append(
                GameEvent(
                    event_type=EventType.EQUIPMENT_REPLACED,
                    card_instance_id=action.card_instance_id,
                    card_key=card.card_key,
                    equipment_owner=context.actor_id,
                    target_ids=(context.actor_id,),
                    payload={
                        "slot": slot,
                        "old_instance_id": old_id,
                        "new_instance_id": action.card_instance_id,
                    },
                )
            )
        else:
            next_state = next_state.move_card(action.card_instance_id, target_slot)
        equip_events.append(
            GameEvent(
                event_type=EventType.CARD_MOVED,
                card_instance_id=action.card_instance_id,
                card_key=card.card_key,
                card_user=context.actor_id,
                payload={
                    "source": _zone_payload(PROCESSING_ZONE),
                    "destination": _zone_payload(target_slot),
                    "reason": f"{reason_prefix}:equipped",
                    "equipment_slot": slot,
                },
            )
        )
        equip_events.append(
            GameEvent(
                event_type=EventType.EQUIPMENT_EQUIPPED,
                card_instance_id=action.card_instance_id,
                card_key=card.card_key,
                equipment_owner=context.actor_id,
                target_ids=(context.actor_id,),
                payload={"slot": slot, "reason": "equip"},
            )
        )
        self._events.extend(tuple(equip_events))
        return next_state

    def _apply_armor_leave_recovery(
        self,
        state: GameState,
        *,
        instance_id: str,
        owner_id: str,
        reason: str,
    ) -> tuple[GameState, tuple[GameEvent, ...]]:
        """统一装备离区钩子（CP-04M）：【白银狮子】离开装备区时恢复1点体力。

        只处理防具实体从本人防具槽离区的情形；恢复不超过体力上限；角色
        已死亡或满体力时不恢复（死亡清理路径不调用本钩子，任务口径：
        死亡清理不非法恢复）。同一实例每次离区只触发一次。"""

        card = state.cards_by_id[instance_id]
        if card.card_key != "sgs_armor_baiyinshizi":
            return state, ()
        owner = state.players_by_id[owner_id]
        if not owner.alive or owner.hp >= owner.max_hp:
            return state, ()
        next_state = _replace_player(
            state, owner_id, hp=min(owner.max_hp, owner.hp + 1)
        )
        event = GameEvent(
            event_type=EventType.ARMOR_RECOVERED,
            card_instance_id=instance_id,
            card_key=card.card_key,
            target_ids=(owner_id,),
            payload={
                "armor_instance_id": instance_id,
                "armor_key": card.card_key,
                "owner_id": owner_id,
                "hp_before": owner.hp,
                "hp_after": next_state.players_by_id[owner_id].hp,
                "reason": reason,
            },
        )
        return next_state, (event,)

    def apply_bagua_activate(
        self,
        state: GameState,
        context: ActionContext,
        action: LegalAction,
        adapter: object,
    ) -> GameState:
        """【八卦阵】发动判定：需要使用／打出【闪】的响应窗口内可选发动。

        判定为红色时视为使用／打出一张虚拟【闪】（响应【杀】只产生
        card_used，响应【万箭齐发】只产生 card_played，不创建正式牌堆
        实体）；判定为黑色时本次发动失败，角色仍可继续选择真实【闪】或
        不响应（同一窗口不得再次发动）。判定牌从牌堆顶公开后置入弃牌堆；
        判定前不打开【无懈可击】窗口；牌堆与可重洗弃牌堆合计不足时原子
        失败关闭。全部改动在一个 step 内提交，可严格重执行。"""

        runtime = self._runtime
        phase = runtime.phase
        if phase not in (
            ProductionPhase.SLASH_RESPONSE,
            ProductionPhase.WANJIAN_RESPONSE,
        ):
            raise InvalidActionError("【八卦阵】只能在需要闪的响应窗口发动")
        if runtime.bagua_attempted:
            raise InvalidActionError("本响应窗口已经发动过【八卦阵】")
        if phase is ProductionPhase.SLASH_RESPONSE:
            pending = runtime.pending_slash
            if pending is None or context.actor_id != pending.target_id:
                raise InvalidActionError("只有当前【杀】目标可以发动【八卦阵】")
            response_to_card_key = state.cards_by_id[
                pending.slash_instance_id
            ].card_key
            window_id = runtime.response_window_id
            if window_id is None:
                raise InvalidActionError("【杀】响应窗口缺少窗口标识")
        else:
            group = runtime.pending_group_trick
            if (
                group is None
                or group.responder_id is None
                or context.actor_id != group.responder_id
            ):
                raise InvalidActionError(
                    "只有当前【万箭齐发】响应目标可以发动【八卦阵】"
                )
            response_to_card_key = group.trick_key
            window_id = (
                f"{group.trick_key}:{runtime.turn_number}:"
                f"{group.trick_instance_id}:gt{group.current_target_index}"
            )
        if action.payload.get("response_window_id") != window_id:
            raise InvalidActionError("【八卦阵】发动动作绑定的响应窗口已过期")
        if action.payload.get("response_to_card_key") != response_to_card_key:
            raise InvalidActionError(
                "【八卦阵】发动动作绑定的响应对象与当前窗口不一致"
            )
        armor_ids = state.card_ids_in(
            ZoneRef.equipment(context.actor_id, "armor")
        )
        if len(armor_ids) != 1:
            raise InvalidActionError("【八卦阵】发动要求装备区恰好一张防具")
        armor_id = armor_ids[0]
        if state.cards_by_id[armor_id].card_key != "sgs_armor_baguazhen":
            raise InvalidActionError("【八卦阵】发动要求装备【八卦阵】")
        if action.card_instance_id != armor_id:
            raise InvalidActionError("【八卦阵】发动动作的实体牌与装备区不一致")
        if str(action.payload.get("card_key", "")) != "sgs_armor_baguazhen":
            raise InvalidActionError("【八卦阵】发动动作负载与适配器卡牌键不一致")

        # 判定（原子）：先预检牌量，再取判定牌公开并弃置
        _assert_deck_available(state, 1, "八卦阵判定需要1张牌")
        started_event = GameEvent(
            event_type=EventType.ARMOR_JUDGMENT_STARTED,
            card_instance_id=armor_id,
            card_key="sgs_armor_baguazhen",
            target_ids=(context.actor_id,),
            payload={
                "armor_instance_id": armor_id,
                "armor_key": "sgs_armor_baguazhen",
                "target_id": context.actor_id,
                "response_to_card_key": response_to_card_key,
                "response_window_id": window_id,
            },
        )
        next_state, take_events, judge_id, judge_card = (
            self._bagua_take_judgment_card(
                state, armor_id, context.actor_id
            )
        )
        success = judge_card.color == "红"
        virtual_kind: str | None
        if success:
            virtual_kind = (
                "use_dodge"
                if phase is ProductionPhase.SLASH_RESPONSE
                else "play_jink"
            )
        else:
            virtual_kind = None
        result_event = GameEvent(
            event_type=EventType.ARMOR_JUDGMENT_RESULT,
            card_instance_id=judge_id,
            card_key=judge_card.card_key,
            target_ids=(context.actor_id,),
            payload={
                "armor_instance_id": armor_id,
                "judgment_card_instance_id": judge_id,
                "judgment_suit": judge_card.suit,
                "judgment_color": judge_card.color,
                "success": success,
                "virtual_response_kind": virtual_kind,
            },
        )
        self._events.extend((started_event, *take_events, result_event))
        next_runtime = replace(runtime, bagua_attempted=True)
        if not success:
            # 判定失败：保持当前响应窗口，角色仍可选择真实【闪】或不响应。
            self._commit_runtime(runtime, next_runtime)
            return next_state
        if phase is ProductionPhase.SLASH_RESPONSE:
            pending = runtime.pending_slash
            assert pending is not None
            virtual_dodge = GameEvent(
                event_type=EventType.CARD_USED,
                card_instance_id=None,
                card_key="sgs_basic_shan",
                card_user=context.actor_id,
                target_ids=(context.actor_id,),
                payload={
                    "response_to": pending.slash_instance_id,
                    "purpose": "bagua_virtual_dodge",
                    "physical_or_virtual": "virtual",
                    "virtual_source": "sgs_armor_baguazhen",
                    "creates_card_used_event": True,
                    "creates_card_played_event": False,
                },
            )
            next_state, slash_finish = self._finish_slash_processing(
                next_state,
                runtime,
                pending.slash_instance_id,
                "slash_cancelled_by_bagua",
            )
            cancelled_event = GameEvent(
                event_type=EventType.CARD_EFFECT_CANCELLED,
                card_instance_id=pending.slash_instance_id,
                card_key=(
                    "sgs_basic_sha"
                    if pending.virtual
                    else _card_key(state, pending.slash_instance_id)
                ),
                card_user=pending.attacker_id,
                target_ids=(context.actor_id,),
                payload={
                    "reason": "bagua_dodge",
                    "armor_instance_id": armor_id,
                    "virtual_response": True,
                },
            )
            if slash_finish is not None:
                self._events.extend(
                    (virtual_dodge, cancelled_event, slash_finish)
                )
            else:
                self._events.extend((virtual_dodge, cancelled_event))
            next_state, next_runtime = self._complete_root_resolution(
                next_state, next_runtime
            )
        else:
            group = runtime.pending_group_trick
            assert group is not None and group.responder_id is not None
            current = group.target_sequence[group.current_target_index]
            virtual_jink = GameEvent(
                event_type=EventType.CARD_PLAYED,
                card_instance_id=None,
                card_key="sgs_basic_shan",
                card_user=context.actor_id,
                target_ids=(current,),
                payload={
                    "response_to": group.trick_instance_id,
                    "root_trick_instance_id": group.trick_instance_id,
                    "response_action": "play",
                    "purpose": "bagua_virtual_jink",
                    "physical_or_virtual": "virtual",
                    "virtual_source": "sgs_armor_baguazhen",
                    "creates_card_used_event": False,
                    "creates_card_played_event": True,
                    "counts_for_use_or_play_total": True,
                    "group_target_id": current,
                    "group_target_index": group.current_target_index,
                    "group_target_count": len(group.target_sequence),
                    "group_user_id": group.user_id,
                },
            )
            resolved = self._group_resolved_event(
                next_state, group, current, result="responded"
            )
            self._events.extend((virtual_jink, resolved))
            next_state, next_runtime = self._advance_group_target(
                next_state, next_runtime, group, current
            )
        self._commit_runtime(runtime, next_runtime)
        return next_state

    def _bagua_take_judgment_card(
        self,
        state: GameState,
        armor_id: str,
        target_id: str,
    ) -> tuple[GameState, tuple[GameEvent, ...], str, object]:
        """八卦阵判定牌生命周期：牌堆顶→REVEALED→公开→弃牌堆。

        与延时锦囊判定共用同一判定基础设施（预检、重洗、REVEALED 区、
        判定牌弃置去向）；判定牌与防具本体实例ID必须不同；结束后
        REVEALED 不得残留。"""

        _assert_deck_available(state, 1, "八卦阵判定需要1张牌")
        next_state = state
        events: list[GameEvent] = []
        if not next_state.card_ids_in(DRAW_PILE):
            discard_ids = list(next_state.card_ids_in(DISCARD_PILE))
            self._rng.shuffle(discard_ids)
            sources = {
                instance_id: next_state.location_of(instance_id)
                for instance_id in discard_ids
            }
            next_state = next_state.reorder_zone(DRAW_PILE, tuple(discard_ids))
            events.extend(
                GameEvent(
                    event_type=EventType.CARD_MOVED,
                    card_instance_id=instance_id,
                    card_key=_card_key(next_state, instance_id),
                    payload={
                        "source": _zone_payload(sources[instance_id]),
                        "destination": _zone_payload(DRAW_PILE),
                        "reason": "reshuffle",
                    },
                )
                for instance_id in discard_ids
            )
        judge_id = next_state.card_ids_in(DRAW_PILE)[0]
        if judge_id == armor_id:
            raise ProductionBatchError(
                "八卦阵判定牌不得与防具本体相同；失败关闭"
            )
        judge_card = next_state.cards_by_id[judge_id]
        take_event = GameEvent(
            event_type=EventType.CARD_MOVED,
            card_instance_id=judge_id,
            card_key=judge_card.card_key,
            payload={
                "source": _zone_payload(DRAW_PILE),
                "destination": _zone_payload(REVEALED_ZONE),
                "reason": "bagua_judgment_take",
                "armor_instance_id": armor_id,
            },
        )
        next_state = next_state.move_card(judge_id, REVEALED_ZONE)
        reveal_event = GameEvent(
            event_type=EventType.CARD_REVEALED,
            card_instance_id=judge_id,
            card_key=judge_card.card_key,
            target_ids=(target_id,),
            payload={
                "reason": "bagua_judgment",
                "instance_id": judge_id,
                "card_key": judge_card.card_key,
                "name": judge_card.card_name,
                "suit": judge_card.suit,
                "rank": judge_card.rank,
                "target_id": target_id,
                "armor_instance_id": armor_id,
            },
        )
        resolve_event = GameEvent(
            event_type=EventType.CARD_MOVED,
            card_instance_id=judge_id,
            card_key=judge_card.card_key,
            payload={
                "source": _zone_payload(REVEALED_ZONE),
                "destination": _zone_payload(DISCARD_PILE),
                "reason": "judgment_card_resolved",
                "armor_instance_id": armor_id,
            },
        )
        next_state = next_state.move_card(judge_id, DISCARD_PILE)
        return next_state, (
            take_event,
            reveal_event,
            resolve_event,
        ), judge_id, judge_card

    def apply_jiedao_use(
        self,
        state: GameState,
        context: ActionContext,
        action: LegalAction,
        adapter: JiedaoSharenAdapter,
    ) -> GameState:
        """使用【借刀杀人】：第一次目标检测并建立作用于第一目标的无懈链。

        card_used 的 target_ids 只包含第一目标；第二目标与 purpose 以
        公开负载记录。借刀实体由手牌进入处理区，无懈链结束后按最终生效
        状态进入杀请求或武器交付。"""

        runtime = self._runtime
        if runtime.phase is not ProductionPhase.PLAY:
            raise InvalidActionError("【借刀杀人】只能在出牌阶段使用")
        if context.actor_id != runtime.current_player_id:
            raise InvalidActionError("只有当前回合角色可以使用【借刀杀人】")
        if action.card_instance_id is None or len(action.target_ids) != 1:
            raise InvalidActionError(
                "使用【借刀杀人】必须指定实体牌与恰好一名第一目标"
            )
        card = state.cards_by_id[action.card_instance_id]
        if card.card_key != adapter.card_key:
            raise InvalidActionError(
                "【借刀杀人】动作的实体牌与适配器卡牌键不一致"
            )
        if str(action.payload.get("card_key", "")) != adapter.card_key:
            raise InvalidActionError("【借刀杀人】动作负载与适配器卡牌键不一致")
        if state.location_of(action.card_instance_id) != ZoneRef.hand(
            context.actor_id
        ):
            raise InvalidActionError("只能使用行动角色真实手牌中的实体牌")
        first_target = action.target_ids[0]
        second_target = str(action.payload.get("second_target_id", ""))
        if first_target == context.actor_id:
            raise InvalidActionError("第一目标不能是借刀使用者")
        if first_target == second_target:
            raise InvalidActionError("第一目标与第二目标不能相同")
        first = state.players_by_id.get(first_target)
        second = state.players_by_id.get(second_target)
        if first is None or second is None:
            raise InvalidActionError("借刀目标必须存在于游戏中")
        if not first.alive or not second.alive:
            raise InvalidActionError("借刀目标必须存活且在游戏中")
        if not state.card_ids_in(ZoneRef.equipment(first_target, "weapon")):
            raise InvalidActionError("第一目标必须装备武器")
        if not is_valid_slash_target(state, first_target, second_target):
            raise InvalidActionError(
                "第二目标必须处于第一目标当前攻击范围内且为合法杀目标"
            )

        next_state, move_event = self._move_to_processing(
            state, action.card_instance_id, context.actor_id, "jiedaosharen_use"
        )
        used_event = GameEvent(
            event_type=EventType.CARD_USED,
            card_instance_id=action.card_instance_id,
            card_key=adapter.card_key,
            card_user=context.actor_id,
            target_ids=(first_target,),
            payload={
                "purpose": "force_slash_or_weapon_gain",
                "card_name": adapter.card_name,
                "second_target_id": second_target,
            },
        )
        queued = self._events.extend((used_event, move_event))
        used_sequence = queued[0].sequence
        assert used_sequence is not None
        order = (
            runtime.current_player_id,
            self.opponent_of(runtime.current_player_id),
        )
        weapon_ids = state.card_ids_in(
            ZoneRef.equipment(first_target, "weapon")
        )
        weapon_instance_id = weapon_ids[0] if weapon_ids else None
        next_runtime = replace(
            runtime,
            phase=ProductionPhase.TRICK_RESPONSE,
            pending_trick=_PendingTrick(
                context.actor_id,
                first_target,
                action.card_instance_id,
                adapter.card_key,
            ),
            trick_effect_active=True,
            trick_consecutive_passes=0,
            trick_response_order=order,
            trick_response_index=0,
            trick_decision_count=0,
            trick_direct_response_to=action.card_instance_id,
            response_window_id=(
                f"trick:{runtime.turn_number}:"
                f"{action.card_instance_id}:dec0"
            ),
            response_window_order=(order[0],),
            response_window_source_sequence=used_sequence,
            pending_borrowed_sword=_PendingBorrowedSword(
                user_id=context.actor_id,
                trick_instance_id=action.card_instance_id,
                first_target_id=first_target,
                second_target_id=second_target,
                effect_active=True,
                stage="awaiting_wuxie",
                weapon_instance_id=weapon_instance_id,
                session_id=self._session_id,
            ),
        )
        self._commit_runtime(runtime, next_runtime)
        return next_state


    def _open_borrowed_sword(
        self,
        state: GameState,
        runtime: _BatchRuntime,
        trick: _PendingTrick,
    ) -> tuple[GameState, _BatchRuntime]:
        """无懈链结束且借刀生效后的第二次动态检测与杀选择窗口。"""

        pending = runtime.pending_borrowed_sword
        if pending is None or pending.trick_instance_id != trick.trick_instance_id:
            raise ProductionBatchError("借刀生效结算缺少挂起状态")
        first_target = pending.first_target_id
        second_target = pending.second_target_id
        first = state.players_by_id.get(first_target)
        second = state.players_by_id.get(second_target)
        if first is None or second is None or not first.alive or not second.alive:
            return self._borrowed_sword_weapon_gain(
                state, runtime, decision="no_legal_slash"
            )
        if not is_valid_slash_target(state, first_target, second_target):
            return self._borrowed_sword_weapon_gain(
                state, runtime, decision="no_legal_slash"
            )
        hand_ids = tuple(state.card_ids_in(ZoneRef.hand(first_target)))
        slash_candidates = [
            instance_id
            for instance_id in hand_ids
            if state.cards_by_id[instance_id].card_key in SLASH_CARD_KEYS
        ]
        if not slash_candidates:
            return self._borrowed_sword_weapon_gain(
                state, runtime, decision="no_legal_slash"
            )
        # 武器技能门禁：任何候选杀可能受第一目标当前武器专属技能影响时
        # 在选择窗口打开前失败关闭，不进入部分结算。
        for instance_id in slash_candidates:
            check_weapon_skill_gate(
                state,
                actor_id=first_target,
                decision="forced_slash",
                target_id=second_target,
                slash_card_key=state.cards_by_id[instance_id].card_key,
            )
        window_id = (
            f"borrowed_sword:{runtime.turn_number}:"
            f"{trick.trick_instance_id}"
        )
        handles, digest = _borrowed_sword_slash_snapshot(
            self._session_id,
            self._session_secret,
            state,
            first_target,
            second_target,
            window_id,
            "slash_request",
        )
        next_runtime = replace(
            runtime,
            phase=ProductionPhase.BORROWED_SWORD_CHOICE,
            pending_borrowed_sword=replace(
                pending,
                stage="slash_request",
                slash_choice_snapshot_digest=digest,
            ),
            borrowed_sword_slash_handles=handles,
            borrowed_sword_slash_snapshot_digest=digest,
            response_window_id=window_id,
            response_window_order=(first_target,),
            response_window_source_sequence=None,
        )
        return state, next_runtime

    def enumerate_borrowed_sword_actions(
        self, state: GameState, context: ActionContext
    ) -> tuple[LegalAction, ...]:
        """枚举借刀【杀】选择窗口动作：不透明句柄选择或拒绝。

        决策输入不携带实体ID、牌名、花色、点数或可识别摘要；真实实体
        由权威引擎通过会话级HMAC句柄解析。"""

        runtime = self._runtime
        pending = runtime.pending_borrowed_sword
        if pending is None or pending.stage != "slash_request":
            return ()
        if runtime.phase is not ProductionPhase.BORROWED_SWORD_CHOICE:
            return ()
        if context.actor_id != pending.first_target_id:
            return ()
        window_id = runtime.response_window_id
        if window_id is None:
            return ()
        state_hash = state_sha256(canonical_state_snapshot(state))
        base_payload: dict[str, object] = {
            "operation": "choose_borrowed_sword_slash",
            "trick_instance_id": pending.trick_instance_id,
            "root_trick_instance_id": pending.trick_instance_id,
            "user_id": pending.user_id,
            "first_target_id": pending.first_target_id,
            "second_target_id": pending.second_target_id,
            "window_id": window_id,
            "state_hash": state_hash,
        }
        actions: list[LegalAction] = []
        for handle in runtime.borrowed_sword_slash_handles:
            actions.append(
                LegalAction(
                    action_type=ActionType.RESPOND,
                    actor_id=pending.first_target_id,
                    target_ids=(pending.first_target_id,),
                    payload={**base_payload, "handle": handle},
                )
            )
            # CP-04P 朱雀羽扇×借刀杀人（2026-08-08 用户移动版实测确认）：
            # 被【借刀杀人】要求使用【杀】时同样可以发动朱雀羽扇，把普通
            # 【杀】转换为火【杀】。只有第一目标当前装备朱雀羽扇且候选是
            # 普通【杀】时才提供转换动作；应用层在 apply 时再次动态校验
            # （武器在选择前失去则旧转换动作 stale 失败关闭）。
            instance_id = runtime.borrowed_sword_slash_handles.get(handle)
            if (
                instance_id is not None
                and state.cards_by_id[instance_id].card_key
                == "sgs_basic_sha"
                and equipped_weapon_key(state, pending.first_target_id)
                == "sgs_weapon_zhuqueyushan"
            ):
                actions.append(
                    LegalAction(
                        action_type=ActionType.RESPOND,
                        actor_id=pending.first_target_id,
                        target_ids=(pending.first_target_id,),
                        payload={
                            **base_payload,
                            "handle": handle,
                            "converted_to_fire": True,
                        },
                    )
                )
        actions.append(
            LegalAction(
                action_type=ActionType.PASS,
                actor_id=pending.first_target_id,
                payload={
                    **base_payload,
                    "operation": "refuse_borrowed_sword_slash",
                },
            )
        )
        return tuple(actions)

    def apply_borrowed_sword_slash_choice(
        self,
        state: GameState,
        context: ActionContext,
        action: LegalAction,
    ) -> GameState:
        """第一目标选择借刀【杀】或拒绝；选择实体只接受不透明句柄。"""

        runtime = self._runtime
        if runtime.phase is not ProductionPhase.BORROWED_SWORD_CHOICE:
            raise InvalidActionError("借刀【杀】选择只能在借刀选择窗口进行")
        pending = runtime.pending_borrowed_sword
        if pending is None or pending.stage != "slash_request":
            raise InvalidActionError("当前没有打开的借刀【杀】选择窗口")
        if context.actor_id != pending.first_target_id:
            raise InvalidActionError("只有第一目标可以选择借刀【杀】")
        payload = action.payload
        if str(payload.get("trick_instance_id", "")) != (
            pending.trick_instance_id
        ):
            raise InvalidActionError("借刀选择动作绑定的根锦囊与当前结算不一致")
        if str(payload.get("root_trick_instance_id", "")) != (
            pending.trick_instance_id
        ):
            raise InvalidActionError("借刀选择动作绑定的根锦囊标识不一致")
        if str(payload.get("user_id", "")) != pending.user_id:
            raise InvalidActionError("借刀选择动作绑定的使用者不一致")
        if str(payload.get("first_target_id", "")) != (
            pending.first_target_id
        ):
            raise InvalidActionError("借刀选择动作绑定的第一目标不一致")
        if str(payload.get("second_target_id", "")) != (
            pending.second_target_id
        ):
            raise InvalidActionError("借刀选择动作绑定的第二目标不一致")
        if str(payload.get("window_id", "")) != runtime.response_window_id:
            raise InvalidActionError("借刀选择窗口标识已过期")
        if str(payload.get("state_hash", "")) != state_sha256(
            canonical_state_snapshot(state)
        ):
            raise InvalidActionError("借刀选择动作绑定的状态哈希已过期")
        operation = str(payload.get("operation", ""))
        if operation == "refuse_borrowed_sword_slash":
            next_state, next_runtime = self._borrowed_sword_weapon_gain(
                state, runtime, decision="refuse"
            )
            self._commit_runtime(runtime, next_runtime)
            return next_state
        if operation != "choose_borrowed_sword_slash":
            raise InvalidActionError("借刀选择动作负载无效")
        # 第二次动态重检：不使用使用借刀时保存的旧合法性结果。
        first = state.players_by_id[pending.first_target_id]
        second = state.players_by_id.get(pending.second_target_id)
        if not first.alive or second is None or not second.alive:
            raise InvalidActionError(
                "第二次检测失败：借刀目标已失效，不能使用【杀】"
            )
        if not is_valid_slash_target(
            state, pending.first_target_id, pending.second_target_id
        ):
            raise InvalidActionError(
                "第二次检测失败：第二目标已不在第一目标当前攻击范围内"
            )
        handle = payload.get("handle")
        instance_id = _resolve_borrowed_sword_slash_handle(
            self._session_id,
            self._session_secret,
            state,
            pending.first_target_id,
            pending.second_target_id,
            runtime.response_window_id or "",
            pending.slash_choice_snapshot_digest,
            runtime.borrowed_sword_slash_handles,
            handle,
            "slash_request",
        )
        if instance_id is None:
            raise InvalidActionError(
                "借刀【杀】句柄无效、过期或伪造；不接受裸实体ID提交"
            )
        card = state.cards_by_id[instance_id]
        if card.card_key not in SLASH_CARD_KEYS:
            raise InvalidActionError("借刀选择实体必须是普通／火／雷【杀】")
        if state.location_of(instance_id) != ZoneRef.hand(
            pending.first_target_id
        ):
            raise InvalidActionError("借刀【杀】实体必须仍在第一目标手牌中")
        fire_converted = bool(action.payload.get("converted_to_fire"))
        if fire_converted:
            # 朱雀羽扇×借刀：应用层动态重检——必须是普通【杀】且第一目标
            # 当前仍装备朱雀羽扇；武器在选择前失去则旧转换动作失败关闭。
            if card.card_key != "sgs_basic_sha":
                raise InvalidActionError(
                    "朱雀羽扇只能把普通【杀】转换为火【杀】"
                )
            if (
                equipped_weapon_key(state, pending.first_target_id)
                != "sgs_weapon_zhuqueyushan"
            ):
                raise InvalidActionError(
                    "朱雀羽扇在选择前已失去，旧转换动作失败关闭"
                )
        check_weapon_skill_gate(
            state,
            actor_id=pending.first_target_id,
            decision="forced_slash",
            target_id=pending.second_target_id,
            slash_card_key=card.card_key,
        )
        next_state, next_runtime = self._apply_forced_slash_use(
            state,
            runtime,
            slash_instance_id=instance_id,
            attacker_id=pending.first_target_id,
            target_id=pending.second_target_id,
            fire_converted=fire_converted,
        )
        self._commit_runtime(runtime, next_runtime)
        return next_state


    def _apply_forced_slash_use(
        self,
        state: GameState,
        runtime: _BatchRuntime,
        *,
        slash_instance_id: str,
        attacker_id: str,
        target_id: str,
        fire_converted: bool = False,
    ) -> tuple[GameState, _BatchRuntime]:
        """借刀要求的正式【杀】使用子结算。

        绕过“通常出杀次数上限”这一项前置检查（绕过来自借刀规则本身），
        但仍增加第一目标自己的计数；产生第一目标自己的正常 ``card_used``，
        正常进入闪响应、伤害、濒死、救援、死亡与属性传导。"""

        pending = runtime.pending_borrowed_sword
        if pending is None or pending.stage != "slash_request":
            raise ProductionBatchError("强制使用杀缺少借刀挂起状态")
        card = state.cards_by_id[slash_instance_id]
        adapter = self._formal_registry.adapter_for(card.card_key)
        if not isinstance(adapter, SlashAdapter):
            raise ProductionBatchError("借刀强制使用杀必须使用【杀】生产适配器")
        next_state, move_event = self._move_to_processing(
            state, slash_instance_id, attacker_id, "borrowed_sword_slash_use"
        )
        boosted = runtime.wine_buff_owner_id == attacker_id
        damage_nature = (
            "火属性" if fire_converted else adapter.damage_nature
        )
        use_payload: dict[str, object] = {
            "damage_nature": damage_nature,
            "boosted": boosted,
            "forced_use_context": "borrowed_sword",
            "ignore_slash_use_limit": True,
            "root_trick_instance_id": pending.trick_instance_id,
            "root_trick_user_id": pending.user_id,
        }
        if fire_converted:
            use_payload["converted_to_fire"] = True
            use_payload["weapon_convert_context"] = (
                "zhuqueyushan_borrowed_sword"
            )
        used_event = GameEvent(
            event_type=EventType.CARD_USED,
            card_instance_id=slash_instance_id,
            card_key=card.card_key,
            card_user=attacker_id,
            target_ids=(target_id,),
            payload=use_payload,
        )
        queued = self._events.extend((used_event, move_event))
        used_sequence = queued[0].sequence
        assert used_sequence is not None
        next_counts = {
            **runtime.slash_used_counts,
            attacker_id: runtime.slash_used_counts.get(attacker_id, 0) + 1,
        }
        # CP-04P：借刀强制【杀】同样按武器技能来源读取第一目标的当前
        # 武器槽（青釭剑无视目标防具；古锭刀伤害+1由伤害时统一判定点按
        # 目标当前权威手牌动态计算，不在使用/指定目标时快照；武器技能
        # 只读取第一目标当前武器槽，不读取借刀使用者的武器，与借刀
        # 第二目标距离口径一致）。
        equipped_weapon = equipped_weapon_key(state, attacker_id)
        ignore_armor = equipped_weapon == "sgs_weapon_qinggangjian"
        # CP-04P 朱雀羽扇×借刀：转火杀按火【杀】身份结算——从使用入口
        # 开始，藤甲普通杀免疫等无效化检查按转化后的身份处理（转换后
        # 不再被藤甲免疫；未转换的普通杀仍按普通杀身份接受无效化检查）。
        if not fire_converted:
            invalidation = armor_invalidates_effect(
                state,
                victim_id=target_id,
                card_instance_id=slash_instance_id,
                card_key=card.card_key,
                ignore_armor=ignore_armor,
            )
            if invalidation is not None:
                invalid_reason, armor_id = invalidation
                next_state, finish_event = self._finish_processing(
                    next_state,
                    slash_instance_id,
                    f"slash_invalidated_by_{invalid_reason}",
                )
                cancelled_event = GameEvent(
                    event_type=EventType.CARD_EFFECT_CANCELLED,
                    card_instance_id=slash_instance_id,
                    card_key=card.card_key,
                    card_user=attacker_id,
                    target_ids=(target_id,),
                    payload={
                        "reason": invalid_reason,
                        "armor_instance_id": armor_id,
                        "armor_key": _card_key(state, armor_id),
                        "invalidated_by_armor": True,
                        "forced_use_context": "borrowed_sword",
                    },
                )
                self._events.extend((cancelled_event, finish_event))
                base_runtime = replace(
                    runtime,
                    slash_used_counts=MappingProxyType(next_counts),
                    wine_buff_owner_id=None,
                    pending_slash=None,
                    pending_borrowed_sword=replace(
                        pending,
                        stage="slash_resolving",
                        chosen_slash_instance_id=slash_instance_id,
                        decision="use_slash",
                        requirement_fulfilled=True,
                    ),
                    borrowed_sword_slash_handles=MappingProxyType({}),
                    borrowed_sword_slash_snapshot_digest=None,
                )
                next_state, next_runtime = self._complete_root_resolution(
                    next_state, base_runtime
                )
                return next_state, next_runtime
        next_runtime = replace(
            runtime,
            phase=ProductionPhase.SLASH_RESPONSE,
            slash_used_counts=MappingProxyType(next_counts),
            wine_buff_owner_id=None,
            pending_slash=_PendingSlash(
                attacker_id,
                target_id,
                slash_instance_id,
                boosted,
                ignore_armor=ignore_armor,
                fire_converted=fire_converted,
            ),
            pending_borrowed_sword=replace(
                pending,
                stage="slash_resolving",
                chosen_slash_instance_id=slash_instance_id,
                decision="use_slash",
                requirement_fulfilled=True,
            ),
            borrowed_sword_slash_handles=MappingProxyType({}),
            borrowed_sword_slash_snapshot_digest=None,
            response_window_id=(
                f"slash:{runtime.turn_number}:{slash_instance_id}"
            ),
            response_window_order=(target_id,),
            response_window_source_sequence=used_sequence,
        )
        return next_state, next_runtime

    def _borrowed_sword_weapon_gain(
        self,
        state: GameState,
        runtime: _BatchRuntime,
        *,
        decision: str,
    ) -> tuple[GameState, _BatchRuntime]:
        """拒绝／无法使用杀时：动态读取第一目标当前武器并交付使用者手牌。

        武器从第一目标装备区直接进入借刀使用者手牌，不经过第一目标手牌、
        不进入使用者装备区、不触发装备替换；无武器或使用者已死亡时记录
        ``no_weapon_to_transfer`` 且不移动任何牌。"""

        pending = runtime.pending_borrowed_sword
        if pending is None:
            raise ProductionBatchError("借刀武器交付缺少挂起状态")
        if pending.root_discarded or pending.stage in ("finishing", "finished"):
            raise ProductionBatchError("借刀结算不能重复执行武器交付")
        user = state.players_by_id[pending.user_id]
        weapon_ids = state.card_ids_in(
            ZoneRef.equipment(pending.first_target_id, "weapon")
        )
        next_state = state
        events: list[GameEvent] = []
        no_weapon_to_transfer = False
        if not weapon_ids or not user.alive:
            no_weapon_to_transfer = True
        else:
            weapon_id = weapon_ids[0]
            destination = ZoneRef.hand(pending.user_id)
            source = ZoneRef.equipment(pending.first_target_id, "weapon")
            next_state = state.move_card(weapon_id, destination)
            card_key = _card_key(state, weapon_id)
            events.append(
                GameEvent(
                    event_type=EventType.CARD_MOVED,
                    card_instance_id=weapon_id,
                    card_key=card_key,
                    card_user=pending.user_id,
                    target_ids=(pending.first_target_id,),
                    payload={
                        "source": _zone_payload(source),
                        "destination": _zone_payload(destination),
                        "reason": "jiedaosharen_weapon_gain",
                        "trick_instance_id": pending.trick_instance_id,
                        "movement": "gain_direct",
                    },
                )
            )
            events.append(
                GameEvent(
                    event_type=EventType.CARD_LOST,
                    card_instance_id=weapon_id,
                    card_key=card_key,
                    target_ids=(pending.first_target_id,),
                    payload={
                        "reason": "jiedaosharen_weapon_gain",
                        "source_zone": _zone_id(source),
                        "trick_instance_id": pending.trick_instance_id,
                    },
                )
            )
            events.append(
                GameEvent(
                    event_type=EventType.CARD_GAINED,
                    card_instance_id=weapon_id,
                    card_key=card_key,
                    target_ids=(pending.user_id,),
                    payload={
                        "reason": "jiedaosharen_weapon_gain",
                        "source_zone": _zone_id(source),
                        "trick_instance_id": pending.trick_instance_id,
                    },
                )
            )
        self._events.extend(tuple(events))
        next_state, finish_event = self._finish_processing(
            next_state,
            pending.trick_instance_id,
            "jiedaosharen_finished",
            extra={
                "decision": decision,
                "no_weapon_to_transfer": no_weapon_to_transfer,
                "weapon_delivered": not no_weapon_to_transfer,
            },
        )
        self._events.extend((finish_event,))
        base_runtime = self._return_to_play(runtime)
        next_runtime = replace(base_runtime, pending_borrowed_sword=None)
        return next_state, next_runtime

    # ------------------------------------------------------------------
    # 群体普通锦囊：逐目标结算状态机（【南蛮入侵】【万箭齐发】【桃园结义】）
    # ------------------------------------------------------------------

    def apply_group_trick_use(
        self,
        state: GameState,
        context: ActionContext,
        action: LegalAction,
        adapter: GroupTargetTrickAdapter,
    ) -> GameState:
        runtime = self._runtime
        if runtime.phase is not ProductionPhase.PLAY:
            raise InvalidActionError(f"{adapter.card_name}只能在出牌阶段使用")
        if context.actor_id != runtime.current_player_id:
            raise InvalidActionError(
                f"只有当前回合角色可以使用{adapter.card_name}"
            )
        if action.card_instance_id is None:
            raise InvalidActionError(f"使用{adapter.card_name}必须指定实体牌")
        card = state.cards_by_id[action.card_instance_id]
        if card.card_key != adapter.card_key:
            raise InvalidActionError(
                f"{adapter.card_name}动作的实体牌与适配器卡牌键不一致"
            )
        if str(action.payload.get("card_key", "")) != adapter.card_key:
            raise InvalidActionError(
                f"{adapter.card_name}动作负载与适配器卡牌键不一致"
            )
        if action.target_ids:
            raise InvalidActionError(
                f"{adapter.card_name}的目标集合由服务器自动生成，"
                "不接受玩家提交、删减或重排的目标"
            )
        if state.location_of(action.card_instance_id) != ZoneRef.hand(
            context.actor_id
        ):
            raise InvalidActionError("只能使用行动角色真实手牌中的实体牌")

        sequence = self._group_target_sequence(
            state, context.actor_id, adapter
        )
        if not sequence:
            raise InvalidActionError(
                f"{adapter.card_name}当前没有合法目标，不能使用"
            )

        next_state, move_event = self._move_to_processing(
            state,
            action.card_instance_id,
            context.actor_id,
            f"{adapter.card_key}_use",
        )
        used_event = GameEvent(
            event_type=EventType.CARD_USED,
            card_instance_id=action.card_instance_id,
            card_key=adapter.card_key,
            card_user=context.actor_id,
            target_ids=sequence,
            payload={
                "purpose": (
                    "nanman_sequential_slash_response"
                    if adapter.card_key == "sgs_trick_nanmanruqin"
                    else "wanjian_sequential_jink_response"
                    if adapter.card_key == "sgs_trick_wanjianqifa"
                    else "taoyuan_sequential_recovery"
                ),
                "card_name": adapter.card_name,
            },
        )
        queued = self._events.extend((used_event, move_event))
        used_sequence = queued[0].sequence
        assert used_sequence is not None
        group = _PendingGroupTrick(
            user_id=context.actor_id,
            trick_instance_id=action.card_instance_id,
            trick_key=adapter.card_key,
            target_sequence=sequence,
        )
        first_target = sequence[0]
        order = (
            runtime.current_player_id,
            self.opponent_of(runtime.current_player_id),
        )
        next_runtime = replace(
            runtime,
            phase=ProductionPhase.TRICK_RESPONSE,
            pending_group_trick=group,
            pending_trick=_PendingTrick(
                context.actor_id,
                first_target,
                action.card_instance_id,
                adapter.card_key,
            ),
            trick_effect_active=True,
            trick_consecutive_passes=0,
            trick_response_order=order,
            trick_response_index=0,
            trick_decision_count=0,
            trick_direct_response_to=action.card_instance_id,
            response_window_id=(
                f"trick:{runtime.turn_number}:"
                f"{action.card_instance_id}:gt0:dec0"
            ),
            response_window_order=(order[0],),
            response_window_source_sequence=used_sequence,
        )
        self._commit_runtime(runtime, next_runtime)
        return next_state

    def _group_target_sequence(
        self,
        state: GameState,
        user_id: str,
        adapter: GroupTargetTrickAdapter,
    ) -> tuple[str, ...]:
        """服务器自动生成群体锦囊目标序列（使用时快照）。

        顺序采用项目通用行动顺序：从使用者开始沿当前座次数字递增方向
        循环（基础术语第4.1节），跳过已确认死亡的角色；【南蛮入侵】与
        【万箭齐发】排除使用者，【桃园结义】只包含已受伤角色且包括
        使用者。序列在使用时固定，结算时不动态增删目标。
        """

        user_seat = state.players_by_id[user_id].seat
        ring_size = max(1, len(state.players))
        ordered = sorted(
            (player for player in state.players if player.alive),
            key=lambda player: (player.seat - user_seat) % ring_size,
        )
        if not adapter.includes_self:
            ordered = [
                player for player in ordered if player.player_id != user_id
            ]
        if adapter.wounded_targets_only:
            ordered = [
                player for player in ordered if player.hp < player.max_hp
            ]
        return tuple(player.player_id for player in ordered)

    def _group_resolved_event(
        self,
        state: GameState,
        group: _PendingGroupTrick,
        target_id: str,
        *,
        result: str,
        damage_amount: int | None = None,
        damage_type: str | None = None,
        damage_source_id: str | None = None,
        recover_amount: int | None = None,
        rescued: bool | None = None,
    ) -> GameEvent:
        """当前目标的独立、可审计的逐目标结算事件。"""

        next_index = group.current_target_index + 1
        next_target_id = None
        if next_index < len(group.target_sequence):
            next_target_id = group.target_sequence[next_index]
        payload: dict[str, object] = {
            "root_trick_instance_id": group.trick_instance_id,
            "user_id": group.user_id,
            "target_index": group.current_target_index,
            "target_count": len(group.target_sequence),
            "result": result,
            "next_target_id": next_target_id,
            "next_target_index": (
                next_index if next_target_id is not None else None
            ),
        }
        if damage_amount is not None:
            payload["damage_amount"] = damage_amount
        if damage_type is not None:
            payload["damage_type"] = damage_type
        if damage_source_id is not None:
            payload["damage_source_id"] = damage_source_id
        if recover_amount is not None:
            payload["recover_amount"] = recover_amount
        if rescued is not None:
            payload["rescued"] = rescued
        return GameEvent(
            event_type=EventType.GROUP_TARGET_RESOLVED,
            card_instance_id=group.trick_instance_id,
            card_key=group.trick_key,
            card_user=group.user_id,
            target_ids=(target_id,),
            payload=payload,
        )

    def _hp_recover_event(
        self,
        group: _PendingGroupTrick,
        target_id: str,
        amount: int,
    ) -> GameEvent:
        """正式恢复事件：记录恢复原因、目标、实际恢复量与根锦囊归属。"""

        return GameEvent(
            event_type=EventType.HP_RECOVER,
            card_instance_id=group.trick_instance_id,
            card_key=group.trick_key,
            card_user=group.user_id,
            target_ids=(target_id,),
            payload={
                "amount": amount,
                "actual_amount": amount,
                "root_trick_instance_id": group.trick_instance_id,
                "target_index": group.current_target_index,
                "target_count": len(group.target_sequence),
                "reason": "taoyuan_jieyi_effect",
                "user_id": group.user_id,
            },
        )

    def _resolve_group_trick_target(
        self,
        state: GameState,
        runtime: _BatchRuntime,
        trick: _PendingTrick,
    ) -> tuple[GameState, _BatchRuntime]:
        """当前目标的无懈链结束后：取消、跳过死亡目标或进入目标效果。"""

        group = runtime.pending_group_trick
        if group is None:
            raise ProductionBatchError("群体锦囊结算缺少逐目标状态")
        if (
            group.trick_key != trick.trick_key
            or group.trick_instance_id != trick.trick_instance_id
        ):
            raise ProductionBatchError("群体锦囊结算状态与当前锦囊不一致")
        if group.current_target_index >= len(group.target_sequence):
            raise ProductionBatchError("群体锦囊目标索引越界")
        current = group.target_sequence[group.current_target_index]
        if current != trick.target_id:
            raise ProductionBatchError(
                "群体锦囊当前目标与响应窗口目标不一致"
            )
        if not runtime.trick_effect_active:
            cancelled_event = GameEvent(
                event_type=EventType.CARD_EFFECT_CANCELLED,
                card_instance_id=group.trick_instance_id,
                card_key=group.trick_key,
                card_user=group.user_id,
                target_ids=(current,),
                payload={
                    "reason": "nullified_by_wuxie",
                    "root_trick_instance_id": group.trick_instance_id,
                    "target_index": group.current_target_index,
                    "target_count": len(group.target_sequence),
                },
            )
            resolved = self._group_resolved_event(
                state, group, current, result="cancelled"
            )
            self._events.extend((cancelled_event, resolved))
            return self._advance_group_target(
                state, runtime, group, current
            )
        if not state.players_by_id[current].alive:
            # 目标在轮到自己前死亡：跳过，不响应、不受伤或不回复。
            resolved = self._group_resolved_event(
                state, group, current, result="skipped_dead"
            )
            self._events.extend((resolved,))
            return self._advance_group_target(
                state, runtime, group, current
            )
        if group.trick_key == "sgs_trick_taoyuanjieyi":
            return self._taoyuan_resolve_target(
                state, runtime, group, current
            )
        if group.trick_key == "sgs_trick_wugufengdeng":
            return self._open_wugu_pick_phase(
                state, runtime, group, current
            )
        if group.trick_key == "sgs_trick_tiesuolianhuan":
            return self._tiesuo_resolve_target(
                state, runtime, group, current
            )
        if group.trick_key in (
            "sgs_trick_nanmanruqin",
            "sgs_trick_wanjianqifa",
        ):
            invalidation = armor_invalidates_effect(
                state,
                victim_id=current,
                card_instance_id=group.trick_instance_id,
                card_key=group.trick_key,
            )
            if invalidation is not None:
                # 【藤甲】令【南蛮入侵】／【万箭齐发】对当前目标无效：
                # 不打开响应阶段、不要求打出【杀】／【闪】、不造成伤害。
                invalid_reason, armor_id = invalidation
                cancelled_event = GameEvent(
                    event_type=EventType.CARD_EFFECT_CANCELLED,
                    card_instance_id=group.trick_instance_id,
                    card_key=group.trick_key,
                    card_user=group.user_id,
                    target_ids=(current,),
                    payload={
                        "reason": invalid_reason,
                        "armor_instance_id": armor_id,
                        "armor_key": _card_key(state, armor_id),
                        "invalidated_by_armor": True,
                        "root_trick_instance_id": group.trick_instance_id,
                        "target_index": group.current_target_index,
                        "target_count": len(group.target_sequence),
                    },
                )
                resolved = self._group_resolved_event(
                    state, group, current, result="armor_invalidated"
                )
                self._events.extend((cancelled_event, resolved))
                return self._advance_group_target(
                    state, runtime, group, current
                )
            return self._open_group_response_phase(
                state, runtime, group, current
            )
        raise ProductionBatchError(
            f"群体锦囊{group.trick_key!r}未实现逐目标结算；失败关闭"
        )

    def _group_response_window_id(
        self, runtime: _BatchRuntime, group: _PendingGroupTrick
    ) -> str:
        return (
            f"{group.trick_key}:{runtime.turn_number}:"
            f"{group.trick_instance_id}:gt{group.current_target_index}"
        )

    def _open_group_response_phase(
        self,
        state: GameState,
        runtime: _BatchRuntime,
        group: _PendingGroupTrick,
        target_id: str,
    ) -> tuple[GameState, _BatchRuntime]:
        """当前目标效果生效：为【南蛮入侵】／【万箭齐发】打开响应阶段。"""

        if group.trick_key == "sgs_trick_nanmanruqin":
            phase = ProductionPhase.NANMAN_RESPONSE
        elif group.trick_key == "sgs_trick_wanjianqifa":
            phase = ProductionPhase.WANJIAN_RESPONSE
        else:
            raise ProductionBatchError(
                f"群体锦囊{group.trick_key!r}没有响应阶段"
            )
        window_id = self._group_response_window_id(runtime, group)
        digest = sha256_value(
            tuple(state.card_ids_in(ZoneRef.hand(target_id)))
        )
        legal_keys = (
            SLASH_CARD_KEYS
            if group.trick_key == "sgs_trick_nanmanruqin"
            else ("sgs_basic_shan",)
        )
        handles = MappingProxyType(
            {
                _group_response_handle(
                    self._session_id,
                    self._session_secret,
                    window_id,
                    target_id,
                    digest,
                    instance_id,
                ): instance_id
                for instance_id in state.card_ids_in(
                    ZoneRef.hand(target_id)
                )
                if state.cards_by_id[instance_id].card_key in legal_keys
            }
        )
        next_runtime = replace(
            runtime,
            phase=phase,
            pending_group_trick=replace(
                group, responder_id=target_id
            ),
            pending_trick=None,
            trick_effect_active=True,
            trick_consecutive_passes=0,
            trick_response_order=(),
            trick_response_index=0,
            trick_decision_count=0,
            trick_direct_response_to=None,
            response_window_id=None,
            response_window_order=(),
            response_window_source_sequence=None,
            group_response_handles=handles,
            group_response_snapshot_digest=digest,
            bagua_attempted=False,
        )
        return state, next_runtime

    def _advance_group_target(
        self,
        state: GameState,
        runtime: _BatchRuntime,
        group: _PendingGroupTrick,
        resolved_target: str,
    ) -> tuple[GameState, _BatchRuntime]:
        """推进到下一目标（建立新的无懈窗口）或完成整张群体锦囊。"""

        completed = (*group.completed_target_ids, resolved_target)
        next_index = group.current_target_index + 1
        wugu = runtime.pending_wugu
        next_wugu = wugu
        if wugu is not None and wugu.trick_instance_id == group.trick_instance_id:
            current_pool = tuple(state.card_ids_in(REVEALED_ZONE))
            next_wugu = replace(
                wugu,
                pool=current_pool,
                pool_digest=sha256_value(current_pool),
                current_target_index=next_index,
                completed_target_ids=completed,
                window_id=None,
            )
        if next_index >= len(group.target_sequence):
            # 全部目标完成：原锦囊此时才从处理区进入弃牌堆。
            next_state = state
            if next_wugu is not None:
                next_state, discard_events = self._discard_revealed_pool(
                    next_state,
                    next_wugu,
                    reason="wugu_remaining_to_discard",
                )
                self._events.extend(discard_events)
            next_state, finish_event = self._finish_processing(
                next_state,
                group.trick_instance_id,
                f"{group.trick_key}_all_targets_resolved",
            )
            self._events.extend((finish_event,))
            next_runtime = self._return_to_play(runtime)
            return next_state, replace(next_runtime, pending_wugu=None)
        next_target = group.target_sequence[next_index]
        order = (
            runtime.current_player_id,
            self.opponent_of(runtime.current_player_id),
        )
        last_events = self._events.snapshot()
        source_sequence = last_events[-1].sequence if last_events else None
        next_group = replace(
            group,
            current_target_index=next_index,
            completed_target_ids=completed,
            responder_id=None,
        )
        next_runtime = replace(
            runtime,
            phase=ProductionPhase.TRICK_RESPONSE,
            pending_group_trick=next_group,
            pending_wugu=next_wugu,
            pending_trick=_PendingTrick(
                group.user_id,
                next_target,
                group.trick_instance_id,
                group.trick_key,
            ),
            trick_effect_active=True,
            trick_consecutive_passes=0,
            trick_response_order=order,
            trick_response_index=0,
            trick_decision_count=0,
            trick_direct_response_to=group.trick_instance_id,
            response_window_id=(
                f"trick:{runtime.turn_number}:"
                f"{group.trick_instance_id}:gt{next_index}:dec0"
            ),
            response_window_order=(order[0],),
            response_window_source_sequence=source_sequence,
            group_response_handles=MappingProxyType({}),
            group_response_snapshot_digest=None,
        )
        return state, next_runtime

    def _taoyuan_resolve_target(
        self,
        state: GameState,
        runtime: _BatchRuntime,
        group: _PendingGroupTrick,
        target_id: str,
    ) -> tuple[GameState, _BatchRuntime]:
        """【桃园结义】当前目标：受伤恢复1点，满体力结算为无效果。"""

        player = state.players_by_id[target_id]
        events: list[GameEvent] = []
        if player.hp < player.max_hp:
            next_state = _replace_player(
                state,
                target_id,
                hp=min(player.max_hp, player.hp + 1),
            )
            events.append(
                self._hp_recover_event(group, target_id, 1)
            )
            resolved = self._group_resolved_event(
                next_state,
                group,
                target_id,
                result="recovered",
                recover_amount=1,
            )
        else:
            next_state = state
            resolved = self._group_resolved_event(
                state,
                group,
                target_id,
                result="no_effect",
                recover_amount=0,
            )
        events.append(resolved)
        self._events.extend(events)
        return self._advance_group_target(
            next_state, runtime, group, target_id
        )

    def _tiesuo_resolve_target(
        self,
        state: GameState,
        runtime: _BatchRuntime,
        group: _PendingGroupTrick,
        target_id: str,
    ) -> tuple[GameState, _BatchRuntime]:
        """【铁索连环】当前目标生效：切换横置状态并记录状态事件。"""

        player = state.players_by_id[target_id]
        old_value = player.chained
        new_value = not old_value
        next_state = _replace_player(
            state, target_id, chained=new_value
        )
        self._events.extend(
            (
                GameEvent(
                    event_type=EventType.CHAINED_STATE,
                    card_instance_id=group.trick_instance_id,
                    card_key=group.trick_key,
                    card_user=group.user_id,
                    target_ids=(target_id,),
                    payload={
                        "actor": group.user_id,
                        "target": target_id,
                        "old_value": old_value,
                        "new_value": new_value,
                        "root_card_instance_id": group.trick_instance_id,
                        "reason": "tiesuolianhuan_toggle",
                        "target_index": group.current_target_index,
                        "target_count": len(group.target_sequence),
                    },
                ),
                self._group_resolved_event(
                    next_state,
                    group,
                    target_id,
                    result="toggled",
                ),
            )
        )
        return self._advance_group_target(
            next_state, runtime, group, target_id
        )

    def _discard_revealed_pool(
        self,
        state: GameState,
        wugu: _PendingWugu,
        *,
        reason: str,
    ) -> tuple[GameState, tuple[GameEvent, ...]]:
        """把公共展示池剩余实体按权威顺序统一置入弃牌堆。"""

        pool = tuple(state.card_ids_in(REVEALED_ZONE))
        if not pool:
            return state, ()
        next_state = state.move_cards(
            {instance_id: DISCARD_PILE for instance_id in pool}
        )
        events = tuple(
            GameEvent(
                event_type=EventType.CARD_MOVED,
                card_instance_id=instance_id,
                card_key=_card_key(next_state, instance_id),
                card_user=wugu.user_id,
                payload={
                    "source": _zone_payload(REVEALED_ZONE),
                    "destination": _zone_payload(DISCARD_PILE),
                    "reason": reason,
                    "root_trick_instance_id": wugu.trick_instance_id,
                },
            )
            for instance_id in pool
        )
        return next_state, events

    def _reveal_cards(
        self,
        state: GameState,
        count: int,
        *,
        user_id: str,
        trick_instance_id: str,
        window_id: str,
        reason: str,
    ) -> tuple[GameState, tuple[GameEvent, ...]]:
        """从牌堆顶展示指定数量实体牌到公共 REVEALED 区域。

        复用正式摸牌同一套确定性 RNG 消费与弃牌重洗逻辑：牌堆不足时把
        弃牌堆洗入牌堆再继续，合计仍不足则失败关闭；不建立另一套补牌
        逻辑。
        """

        _assert_deck_available(state, count, f"展示{count}张牌")
        next_state = state
        events: list[GameEvent] = []
        for pool_index in range(count):
            if not next_state.card_ids_in(DRAW_PILE):
                discard_ids = list(next_state.card_ids_in(DISCARD_PILE))
                self._rng.shuffle(discard_ids)
                sources = {
                    instance_id: next_state.location_of(instance_id)
                    for instance_id in discard_ids
                }
                next_state = next_state.move_cards(
                    {instance_id: DRAW_PILE for instance_id in discard_ids}
                )
                events.extend(
                    GameEvent(
                        event_type=EventType.CARD_MOVED,
                        card_instance_id=instance_id,
                        card_key=_card_key(next_state, instance_id),
                        payload={
                            "source": _zone_payload(sources[instance_id]),
                            "destination": _zone_payload(DRAW_PILE),
                            "reason": "reshuffle",
                        },
                    )
                    for instance_id in discard_ids
                )
            instance_id = next_state.card_ids_in(DRAW_PILE)[0]
            source = next_state.location_of(instance_id)
            next_state = next_state.move_card(instance_id, REVEALED_ZONE)
            card = next_state.cards_by_id[instance_id]
            events.extend(
                (
                    GameEvent(
                        event_type=EventType.CARD_MOVED,
                        card_instance_id=instance_id,
                        card_key=card.card_key,
                        card_user=user_id,
                        payload={
                            "source": _zone_payload(source),
                            "destination": _zone_payload(REVEALED_ZONE),
                            "reason": reason,
                        },
                    ),
                    GameEvent(
                        event_type=EventType.CARD_REVEALED,
                        card_instance_id=instance_id,
                        card_key=card.card_key,
                        card_user=user_id,
                        target_ids=tuple(
                            player.player_id
                            for player in next_state.players
                            if player.alive
                        ),
                        payload={
                            "reason": reason,
                            "card_name": card.card_name,
                            "suit": card.suit,
                            "rank": card.rank,
                            "pool_index": pool_index,
                            "pool_size": count,
                            "root_trick_instance_id": trick_instance_id,
                            "trick_instance_id": trick_instance_id,
                            "window_id": window_id,
                        },
                    ),
                )
            )
        return next_state, tuple(events)

    def apply_wugu_use(
        self,
        state: GameState,
        context: ActionContext,
        action: LegalAction,
        adapter: WugufengdengAdapter,
    ) -> GameState:
        runtime = self._runtime
        if runtime.phase is not ProductionPhase.PLAY:
            raise InvalidActionError("【五谷丰登】只能在出牌阶段使用")
        if context.actor_id != runtime.current_player_id:
            raise InvalidActionError("只有当前回合角色可以使用【五谷丰登】")
        if action.card_instance_id is None:
            raise InvalidActionError("使用【五谷丰登】必须指定实体牌")
        card = state.cards_by_id[action.card_instance_id]
        if card.card_key != adapter.card_key:
            raise InvalidActionError(
                "【五谷丰登】动作的实体牌与适配器卡牌键不一致"
            )
        if str(action.payload.get("card_key", "")) != adapter.card_key:
            raise InvalidActionError(
                "【五谷丰登】动作负载与适配器卡牌键不一致"
            )
        if action.target_ids:
            raise InvalidActionError(
                "【五谷丰登】的目标集合由服务器自动生成，"
                "不接受玩家提交、删减或重排的目标"
            )
        if state.location_of(action.card_instance_id) != ZoneRef.hand(
            context.actor_id
        ):
            raise InvalidActionError("只能使用行动角色真实手牌中的实体牌")

        sequence = self._group_target_sequence(
            state, context.actor_id, adapter
        )
        if not sequence:
            raise InvalidActionError(
                "【五谷丰登】当前没有合法目标，不能使用"
            )

        # 原子性预检：展示牌量不足必须在任何事件登记前失败关闭。
        _assert_deck_available(
            state, len(sequence), f"五谷丰登展示{len(sequence)}张牌"
        )

        next_state, move_event = self._move_to_processing(
            state,
            action.card_instance_id,
            context.actor_id,
            "wugufengdeng_use",
        )
        used_event = GameEvent(
            event_type=EventType.CARD_USED,
            card_instance_id=action.card_instance_id,
            card_key=adapter.card_key,
            card_user=context.actor_id,
            target_ids=sequence,
            payload={
                "purpose": "wugu_sequential_public_pool_pick",
                "card_name": adapter.card_name,
                "pool_size": len(sequence),
            },
        )
        queued = self._events.extend((used_event, move_event))
        used_sequence = queued[0].sequence
        assert used_sequence is not None

        reveal_window_id = (
            f"wugu-reveal:{runtime.turn_number}:"
            f"{action.card_instance_id}"
        )
        pool_state, reveal_events = self._reveal_cards(
            next_state,
            len(sequence),
            user_id=context.actor_id,
            trick_instance_id=action.card_instance_id,
            window_id=reveal_window_id,
            reason="wugu_reveal",
        )
        self._events.extend(reveal_events)
        pool = tuple(pool_state.card_ids_in(REVEALED_ZONE))
        if len(pool) != len(sequence):
            raise ProductionBatchError(
                "五谷展示池数量与目标序列不一致"
            )
        pool_digest = sha256_value(pool)

        group = _PendingGroupTrick(
            user_id=context.actor_id,
            trick_instance_id=action.card_instance_id,
            trick_key=adapter.card_key,
            target_sequence=sequence,
        )
        first_target = sequence[0]
        order = (
            runtime.current_player_id,
            self.opponent_of(runtime.current_player_id),
        )
        next_runtime = replace(
            runtime,
            phase=ProductionPhase.TRICK_RESPONSE,
            pending_group_trick=group,
            pending_wugu=_PendingWugu(
                user_id=context.actor_id,
                trick_instance_id=action.card_instance_id,
                trick_key=adapter.card_key,
                pool=pool,
                pool_digest=pool_digest,
                target_sequence=sequence,
            ),
            pending_trick=_PendingTrick(
                context.actor_id,
                first_target,
                action.card_instance_id,
                adapter.card_key,
            ),
            trick_effect_active=True,
            trick_consecutive_passes=0,
            trick_response_order=order,
            trick_response_index=0,
            trick_decision_count=0,
            trick_direct_response_to=action.card_instance_id,
            response_window_id=(
                f"trick:{runtime.turn_number}:"
                f"{action.card_instance_id}:gt0:dec0"
            ),
            response_window_order=(order[0],),
            response_window_source_sequence=used_sequence,
        )
        self._commit_runtime(runtime, next_runtime)
        return pool_state

    def _open_wugu_pick_phase(
        self,
        state: GameState,
        runtime: _BatchRuntime,
        group: _PendingGroupTrick,
        target_id: str,
    ) -> tuple[GameState, _BatchRuntime]:
        """当前目标无懈链结束后：进入公共展示池选牌阶段。"""

        wugu = runtime.pending_wugu
        if wugu is None or wugu.trick_instance_id != group.trick_instance_id:
            raise ProductionBatchError("五谷结算缺少展示池状态")
        if wugu.current_target_index >= len(wugu.target_sequence):
            raise ProductionBatchError("五谷目标索引越界")
        if wugu.target_sequence[wugu.current_target_index] != target_id:
            raise ProductionBatchError(
                "五谷当前目标与选牌窗口目标不一致"
            )
        current_pool = tuple(state.card_ids_in(REVEALED_ZONE))
        if sha256_value(current_pool) != wugu.pool_digest:
            raise ProductionBatchError("五谷展示池摘要与结算状态不一致")
        window_id = (
            f"wugu-pick:{runtime.turn_number}:"
            f"{group.trick_instance_id}:gt{wugu.current_target_index}"
        )
        next_runtime = replace(
            runtime,
            phase=ProductionPhase.WUGU_PICK,
            pending_wugu=replace(wugu, window_id=window_id),
            pending_trick=None,
            trick_effect_active=False,
            trick_consecutive_passes=0,
            trick_response_order=(),
            trick_response_index=0,
            trick_decision_count=0,
            trick_direct_response_to=None,
            response_window_id=None,
            response_window_order=(),
            response_window_source_sequence=None,
        )
        return state, next_runtime

    def enumerate_wugu_pick_actions(
        self, state: GameState, context: ActionContext
    ) -> tuple[LegalAction, ...]:
        """枚举五谷当前目标的公开展示池选择动作。

        展示池全部公开，候选直接携带公开实体ID；动作同时绑定会话、当前
        窗口、根锦囊、当前目标与索引、展示池有序摘要和状态哈希。
        """

        runtime = self._runtime
        if runtime.phase is not ProductionPhase.WUGU_PICK:
            raise ProductionBatchError("五谷选牌动作只能在选牌阶段枚举")
        group = runtime.pending_group_trick
        wugu = runtime.pending_wugu
        if group is None or wugu is None:
            raise ProductionBatchError("五谷选牌阶段缺少结算状态")
        if (
            group.trick_key != wugu.trick_key
            or group.trick_instance_id != wugu.trick_instance_id
        ):
            raise ProductionBatchError("五谷选牌阶段状态不一致")
        if wugu.current_target_index >= len(wugu.target_sequence):
            raise ProductionBatchError("五谷目标索引越界")
        current_target = wugu.target_sequence[wugu.current_target_index]
        if context.actor_id != current_target:
            return ()
        if wugu.window_id is None:
            raise ProductionBatchError("五谷选牌窗口未建立")
        if state.location_of(wugu.trick_instance_id) != PROCESSING_ZONE:
            raise ProductionBatchError(
                "原五谷已不在处理区，选牌窗口不能继续枚举动作"
            )
        state_hash = state_sha256(canonical_state_snapshot(state))
        actions: list[LegalAction] = []
        pool = state.card_ids_in(REVEALED_ZONE)
        for pool_index, instance_id in enumerate(pool):
            card = state.cards_by_id[instance_id]
            actions.append(
                LegalAction(
                    action_type=ActionType.MOVE_CARD,
                    actor_id=context.actor_id,
                    card_instance_id=instance_id,
                    target_ids=(current_target,),
                    payload={
                        "operation": "pick_wugu_card",
                        "card_key": card.card_key,
                        "trick_instance_id": wugu.trick_instance_id,
                        "root_trick_instance_id": wugu.trick_instance_id,
                        "user_id": wugu.user_id,
                        "target_id": current_target,
                        "target_index": wugu.current_target_index,
                        "pool_index": pool_index,
                        "window_id": wugu.window_id,
                        "pool_digest": wugu.pool_digest,
                        "state_hash": state_hash,
                        "card_instance_id": instance_id,
                    },
                )
            )
        return tuple(actions)

    def apply_wugu_pick(
        self,
        state: GameState,
        context: ActionContext,
        action: LegalAction,
        adapter: object,
    ) -> GameState:
        del adapter
        runtime = self._runtime
        if runtime.phase is not ProductionPhase.WUGU_PICK:
            raise InvalidActionError("五谷选牌只能在选牌阶段进行")
        group = runtime.pending_group_trick
        wugu = runtime.pending_wugu
        if group is None or wugu is None:
            raise InvalidActionError("当前没有进行中的五谷选牌")
        if group.trick_instance_id != wugu.trick_instance_id:
            raise InvalidActionError("五谷选牌状态与当前结算不一致")
        if wugu.current_target_index >= len(wugu.target_sequence):
            raise InvalidActionError("五谷目标索引越界")
        current_target = wugu.target_sequence[wugu.current_target_index]
        if context.actor_id != current_target:
            raise InvalidActionError("只有当前五谷目标可以选择展示牌")
        payload = action.payload
        if str(payload.get("operation", "")) != "pick_wugu_card":
            raise InvalidActionError("五谷选牌动作负载无效")
        if payload.get("trick_instance_id") != wugu.trick_instance_id:
            raise InvalidActionError("选牌动作绑定的锦囊与当前结算不一致")
        if payload.get("root_trick_instance_id") != wugu.trick_instance_id:
            raise InvalidActionError("选牌动作绑定的根锦囊与当前结算不一致")
        if payload.get("user_id") != wugu.user_id:
            raise InvalidActionError("选牌动作绑定的使用者与当前结算不一致")
        if payload.get("target_id") != current_target:
            raise InvalidActionError(
                "选牌动作绑定的目标不是当前五谷目标"
            )
        if payload.get("target_index") != wugu.current_target_index:
            raise InvalidActionError("选牌动作绑定的目标索引已过期")
        if payload.get("window_id") != wugu.window_id:
            raise InvalidActionError("选牌动作绑定的选择窗口已过期")
        current_digest = sha256_value(
            tuple(state.card_ids_in(REVEALED_ZONE))
        )
        if current_digest != wugu.pool_digest:
            raise InvalidActionError("五谷展示池摘要已过期")
        if payload.get("pool_digest") != wugu.pool_digest:
            raise InvalidActionError("选牌动作绑定的展示池摘要已过期")
        if payload.get("state_hash") != state_sha256(
            canonical_state_snapshot(state)
        ):
            raise InvalidActionError(
                "选牌动作绑定的状态哈希与当前状态不一致"
            )
        if action.card_instance_id is None:
            raise InvalidActionError("五谷选牌必须指定展示池中的实体牌")
        picked = action.card_instance_id
        if picked != payload.get("card_instance_id"):
            raise InvalidActionError("选牌动作负载与实体牌不一致")
        if state.location_of(picked) != REVEALED_ZONE:
            raise InvalidActionError("只能选择当前展示池中的实体牌")
        if state.location_of(wugu.trick_instance_id) != PROCESSING_ZONE:
            raise InvalidActionError("原五谷已不在处理区，选牌不能继续")

        next_state = state.move_card(picked, ZoneRef.hand(current_target))
        card = next_state.cards_by_id[picked]
        self._events.extend(
            (
                GameEvent(
                    event_type=EventType.CARD_MOVED,
                    card_instance_id=picked,
                    card_key=card.card_key,
                    card_user=wugu.user_id,
                    payload={
                        "source": _zone_payload(REVEALED_ZONE),
                        "destination": _zone_payload(
                            ZoneRef.hand(current_target)
                        ),
                        "reason": "wugu_pick",
                        "root_trick_instance_id": wugu.trick_instance_id,
                        "target_index": wugu.current_target_index,
                        "target_count": len(wugu.target_sequence),
                    },
                ),
                GameEvent(
                    event_type=EventType.CARD_GAINED,
                    card_instance_id=picked,
                    card_key=card.card_key,
                    card_user=wugu.user_id,
                    target_ids=(current_target,),
                    payload={
                        "reason": "wugu_pick",
                        "root_trick_instance_id": wugu.trick_instance_id,
                        "target_index": wugu.current_target_index,
                    },
                ),
            )
        )
        resolved = self._group_resolved_event(
            next_state, group, current_target, result="picked"
        )
        self._events.extend((resolved,))
        next_state, next_runtime = self._advance_group_target(
            next_state, runtime, group, current_target
        )
        self._commit_runtime(runtime, next_runtime)
        return next_state

    def apply_tiesuo_use(
        self,
        state: GameState,
        context: ActionContext,
        action: LegalAction,
        adapter: TiesuoLianhuanAdapter,
    ) -> GameState:
        runtime = self._runtime
        if runtime.phase is not ProductionPhase.PLAY:
            raise InvalidActionError("【铁索连环】只能在出牌阶段使用")
        if context.actor_id != runtime.current_player_id:
            raise InvalidActionError("只有当前回合角色可以使用【铁索连环】")
        if action.card_instance_id is None:
            raise InvalidActionError("使用【铁索连环】必须指定实体牌")
        card = state.cards_by_id[action.card_instance_id]
        if card.card_key != adapter.card_key:
            raise InvalidActionError(
                "【铁索连环】动作的实体牌与适配器卡牌键不一致"
            )
        if str(action.payload.get("card_key", "")) != adapter.card_key:
            raise InvalidActionError(
                "【铁索连环】动作负载与适配器卡牌键不一致"
            )
        if len(action.target_ids) not in (1, 2):
            raise InvalidActionError(
                "【铁索连环】必须指定一名或两名互不相同的目标"
            )
        if len(set(action.target_ids)) != len(action.target_ids):
            raise InvalidActionError("【铁索连环】不能重复指定同一名目标")
        for target_id in action.target_ids:
            player = state.players_by_id.get(target_id)
            if player is None:
                raise InvalidActionError(f"目标角色{target_id!r}不存在")
            if not player.alive:
                raise InvalidActionError(
                    f"目标角色{target_id!r}已死亡，不能成为目标"
                )
        if state.location_of(action.card_instance_id) != ZoneRef.hand(
            context.actor_id
        ):
            raise InvalidActionError("只能使用行动角色真实手牌中的实体牌")

        sequence = normalize_target_order(
            state, context.actor_id, action.target_ids
        )
        next_state, move_event = self._move_to_processing(
            state,
            action.card_instance_id,
            context.actor_id,
            "tiesuolianhuan_use",
        )
        used_event = GameEvent(
            event_type=EventType.CARD_USED,
            card_instance_id=action.card_instance_id,
            card_key=adapter.card_key,
            card_user=context.actor_id,
            target_ids=sequence,
            payload={
                "purpose": "tiesuo_sequential_chain_toggle",
                "card_name": adapter.card_name,
            },
        )
        queued = self._events.extend((used_event, move_event))
        used_sequence = queued[0].sequence
        assert used_sequence is not None
        group = _PendingGroupTrick(
            user_id=context.actor_id,
            trick_instance_id=action.card_instance_id,
            trick_key=adapter.card_key,
            target_sequence=sequence,
        )
        first_target = sequence[0]
        order = (
            runtime.current_player_id,
            self.opponent_of(runtime.current_player_id),
        )
        next_runtime = replace(
            runtime,
            phase=ProductionPhase.TRICK_RESPONSE,
            pending_group_trick=group,
            pending_trick=_PendingTrick(
                context.actor_id,
                first_target,
                action.card_instance_id,
                adapter.card_key,
            ),
            trick_effect_active=True,
            trick_consecutive_passes=0,
            trick_response_order=order,
            trick_response_index=0,
            trick_decision_count=0,
            trick_direct_response_to=action.card_instance_id,
            response_window_id=(
                f"trick:{runtime.turn_number}:"
                f"{action.card_instance_id}:gt0:dec0"
            ),
            response_window_order=(order[0],),
            response_window_source_sequence=used_sequence,
        )
        self._commit_runtime(runtime, next_runtime)
        return next_state

    def apply_tiesuo_recast(
        self,
        state: GameState,
        context: ActionContext,
        action: LegalAction,
        adapter: TiesuoLianhuanAdapter,
    ) -> GameState:
        runtime = self._runtime
        if runtime.phase is not ProductionPhase.PLAY:
            raise InvalidActionError("【铁索连环】重铸只能在出牌阶段进行")
        if context.actor_id != runtime.current_player_id:
            raise InvalidActionError("只有当前回合角色可以重铸【铁索连环】")
        if action.card_instance_id is None:
            raise InvalidActionError("重铸【铁索连环】必须指定实体牌")
        card = state.cards_by_id[action.card_instance_id]
        if card.card_key != adapter.card_key:
            raise InvalidActionError("重铸动作的实体牌必须属于【铁索连环】")
        if action.target_ids:
            raise InvalidActionError("重铸不能指定目标")
        if state.location_of(action.card_instance_id) != ZoneRef.hand(
            context.actor_id
        ):
            raise InvalidActionError("只能重铸自己手牌中的【铁索连环】")

        source = state.location_of(action.card_instance_id)
        # 原子实现（局部不可变状态完成后一次性提交事件）：先在局部状态上
        # 完成“重铸铁索进入弃牌堆→正式摸1张”，全部成功后统一登记事件。
        # 不按动作前旧牌量预检：重铸牌自身先进入弃牌堆，即构成至少1张可
        # 重洗实体；因此正式语义下重铸摸1张不存在真实可达的牌量不足路径
        # （牌堆与弃牌堆在动作前均为空时，该铁索也会被洗回牌堆并摸回）。
        next_state = state.move_card(action.card_instance_id, DISCARD_PILE)
        recast_event = GameEvent(
            event_type=EventType.CARD_RECAST,
            card_instance_id=action.card_instance_id,
            card_key=card.card_key,
            card_user=context.actor_id,
            payload={
                "source": _zone_payload(source),
                "destination": _zone_payload(DISCARD_PILE),
                "reason": "recast",
                "recast_by": context.actor_id,
            },
        )
        next_state, draw_events = self._draw_cards(
            next_state, context.actor_id, 1, reason="tiesuo_recast"
        )
        self._events.extend((recast_event, *draw_events))
        return next_state

    def _apply_group_trick_damage(
        self,
        state: GameState,
        runtime: _BatchRuntime,
        group: _PendingGroupTrick,
        victim_id: str,
    ) -> tuple[GameState, _BatchRuntime]:
        """群体锦囊当前目标不响应时造成1点无属性伤害。

        伤害来源为群体锦囊使用者；濒死时暂停目标队列并进入正式救援，
        救援完成后从下一目标继续；原锦囊在全部目标完成前不进入弃牌堆。
        """

        if group.current_target_index >= len(group.target_sequence):
            raise ProductionBatchError("群体锦囊目标索引越界")
        current = group.target_sequence[group.current_target_index]
        if current != victim_id:
            raise ProductionBatchError("群体锦囊伤害目标不是当前目标")
        victim = state.players_by_id[victim_id]
        next_state = _replace_player(state, victim_id, hp=victim.hp - 1)
        damage_event = DamageEvent(
            target_id=victim_id,
            amount=1,
            damage_type="无属性",
            card_instance_id=group.trick_instance_id,
            card_key=group.trick_key,
            card_user=group.user_id,
            damage_source=group.user_id,
            kill_credit=group.user_id,
            payload={
                "root_trick_instance_id": group.trick_instance_id,
                "target_index": group.current_target_index,
                "target_count": len(group.target_sequence),
            },
        )
        if next_state.players_by_id[victim_id].hp <= 0:
            dying_event = GameEvent(
                event_type=EventType.DYING,
                damage_source=group.user_id,
                kill_credit=group.user_id,
                target_ids=(victim_id,),
            )
            self._events.extend((damage_event, dying_event))
            dying_sequence = self._events.snapshot()[-1].sequence
            assert dying_sequence is not None
            rescue_order = (
                runtime.current_player_id,
                self.opponent_of(runtime.current_player_id),
            )
            next_runtime = replace(
                runtime,
                phase=ProductionPhase.DYING_RESCUE,
                pending_dying_id=victim_id,
                rescue_order=rescue_order,
                rescue_index=0,
                rescue_decision_count=0,
                response_window_id=(
                    f"dying:{runtime.turn_number}:{victim_id}"
                    ":seat0:dec0"
                ),
                response_window_order=(rescue_order[0],),
                response_window_source_sequence=dying_sequence,
                pending_damage_card_id=group.trick_instance_id,
                pending_damage_source_id=group.user_id,
                pending_damage_kill_credit=group.user_id,
                pending_damage_rescue_reason=(
                    f"{group.trick_key}_target_resolved_after_rescue"
                ),
                pending_damage_death_reason=(
                    f"{group.trick_key}_target_resolved_with_death"
                ),
            )
            return next_state, next_runtime
        self._events.extend((damage_event,))
        resolved = self._group_resolved_event(
            next_state,
            group,
            victim_id,
            result="damaged",
            damage_amount=1,
            damage_type="无属性",
            damage_source_id=group.user_id,
        )
        self._events.extend((resolved,))
        return self._advance_group_target(
            next_state, runtime, group, victim_id
        )

    def _resume_group_after_damage(
        self,
        state: GameState,
        runtime: _BatchRuntime,
        victim_id: str,
        *,
        rescued: bool,
    ) -> tuple[GameState, _BatchRuntime]:
        """濒死救援结束后恢复群体目标队列继续位置。"""

        group = runtime.pending_group_trick
        if group is None:
            raise ProductionBatchError(
                "濒死救援完成但缺少群体锦囊继续状态"
            )
        if (
            group.current_target_index >= len(group.target_sequence)
            or group.target_sequence[group.current_target_index] != victim_id
        ):
            raise ProductionBatchError(
                "群体锦囊救援恢复的目标不是当前目标"
            )
        resolved = self._group_resolved_event(
            state,
            group,
            victim_id,
            result="damaged",
            damage_amount=1,
            damage_type="无属性",
            damage_source_id=group.user_id,
            rescued=rescued,
        )
        self._events.extend((resolved,))
        return self._advance_group_target(
            state, runtime, group, victim_id
        )

    def enumerate_group_response_actions(
        self,
        state: GameState,
        context: ActionContext,
        adapter: GroupTargetTrickAdapter,
    ) -> tuple[LegalAction, ...]:
        """枚举当前目标的合法响应动作（打出【杀】或【闪】）。

        候选只以绑定当前响应窗口的不透明句柄暴露，不在动作负载中携带
        实体牌ID、牌名、花色或点数；未打出的目标手牌不会进入玩家可见
        回放材料。
        """

        runtime = self._runtime
        group = runtime.pending_group_trick
        if group is None or group.trick_key != adapter.card_key:
            return ()
        if runtime.phase.value != adapter.response_phase_value:
            return ()
        if group.responder_id is None or group.responder_id != context.actor_id:
            return ()
        current = group.target_sequence[group.current_target_index]
        if not state.players_by_id[current].alive:
            return ()
        window_id = self._group_response_window_id(runtime, group)
        if runtime.group_response_snapshot_digest is None:
            return ()
        if sha256_value(
            tuple(state.card_ids_in(ZoneRef.hand(current)))
        ) != runtime.group_response_snapshot_digest:
            # 响应窗口打开后手牌已变化：不再铸造任何动作，旧句柄失败关闭。
            return ()
        actions: list[LegalAction] = []
        for handle in sorted(runtime.group_response_handles):
            actions.append(
                LegalAction(
                    action_type=ActionType.PLAY_CARD,
                    actor_id=context.actor_id,
                    target_ids=(current,),
                    payload={
                        "operation": adapter.response_operation,
                        "response_to": group.trick_instance_id,
                        "root_trick_instance_id": group.trick_instance_id,
                        "target_id": current,
                        "target_index": group.current_target_index,
                        "window_id": window_id,
                        "state_hash": state_sha256(
                            canonical_state_snapshot(state)
                        ),
                        "handle": handle,
                    },
                )
            )
        # CP-04P 丈八蛇矛（7.8 当前确认）：响应需要打出【杀】的入口
        # （【南蛮入侵】）同样可以把两张手牌当作普通【杀】打出；材料对
        # 只通过不透明句柄暴露。
        if (
            any(
                card_key in SLASH_CARD_KEYS
                for card_key in adapter.response_card_keys
            )
            and equipped_weapon_key(state, current)
            == "sgs_weapon_zhangbashemao"
            and len(state.card_ids_in(ZoneRef.hand(current))) >= 2
        ):
            # G-003 统一 fail-closed：丈八蛇矛保持 PARTIAL（VIRTUAL_CARD_
            # SUBCARD_LIFECYCLE_RULE_GAP），在正式枚举 virtual proposal
            # 之前直接门禁拒绝（decision=play_slash），不生成
            # virtual:zhangba:* candidate 后再撞公共实体验证器。
            check_weapon_skill_gate(
                state,
                actor_id=context.actor_id,
                decision="play_slash",
            )
            hand_ids = tuple(state.card_ids_in(ZoneRef.hand(current)))
            snapshot_digest = sha256_value(hand_ids)
            for index, first in enumerate(hand_ids):
                for second in hand_ids[index + 1 :]:
                    material_ids = (first, second)
                    material_handle = _zhangba_material_handle(
                        self._session_id,
                        self._session_secret,
                        window_id,
                        current,
                        snapshot_digest,
                        material_ids,
                    )
                    virtual_id = (
                        f"virtual:zhangba:{runtime.turn_number}:"
                        f"{first}:{second}"
                    )
                    actions.append(
                        LegalAction(
                            action_type=ActionType.PLAY_CARD,
                            actor_id=context.actor_id,
                            card_instance_id=virtual_id,
                            target_ids=(current,),
                            payload={
                                "operation": adapter.response_operation,
                                "response_to": group.trick_instance_id,
                                "root_trick_instance_id": (
                                    group.trick_instance_id
                                ),
                                "target_id": current,
                                "target_index": (
                                    group.current_target_index
                                ),
                                "window_id": window_id,
                                "state_hash": state_sha256(
                                    canonical_state_snapshot(state)
                                ),
                                "handle": material_handle,
                                "zhangba_virtual": True,
                            },
                        )
                    )
        return tuple(actions)

    def apply_group_response_play(
        self,
        state: GameState,
        context: ActionContext,
        action: LegalAction,
        adapter: GroupTargetTrickAdapter,
    ) -> GameState:
        """权威解析群体锦囊响应动作：当前目标打出合法【杀】或【闪】。"""

        runtime = self._runtime
        if runtime.phase.value != adapter.response_phase_value:
            raise InvalidActionError(
                f"响应{adapter.card_name}只能在对应响应阶段进行"
            )
        group = runtime.pending_group_trick
        if group is None or group.trick_key != adapter.card_key:
            raise InvalidActionError("当前没有进行中的群体锦囊响应")
        if group.responder_id is None or context.actor_id != group.responder_id:
            raise InvalidActionError("只有当前响应目标可以打出响应牌")
        if action.action_type is not ActionType.PLAY_CARD:
            raise InvalidActionError(f"响应{adapter.card_name}的动作类型必须是打出")
        current = group.target_sequence[group.current_target_index]
        payload = action.payload
        if str(payload.get("operation", "")) != adapter.response_operation:
            raise InvalidActionError(f"{adapter.card_name}响应动作负载无效")
        if payload.get("root_trick_instance_id") != group.trick_instance_id:
            raise InvalidActionError(
                f"{adapter.card_name}响应动作绑定的根锦囊与当前结算不一致"
            )
        if payload.get("response_to") != group.trick_instance_id:
            raise InvalidActionError(
                f"{adapter.card_name}响应动作的响应对象与当前结算不一致"
            )
        if payload.get("target_id") != current:
            raise InvalidActionError(
                f"{adapter.card_name}响应动作绑定的目标不是当前目标"
            )
        if payload.get("target_index") != group.current_target_index:
            raise InvalidActionError(
                f"{adapter.card_name}响应动作绑定的目标索引已过期"
            )
        if payload.get("window_id") != self._group_response_window_id(
            runtime, group
        ):
            raise InvalidActionError(f"{adapter.card_name}响应窗口已过期")
        if payload.get("state_hash") != state_sha256(
            canonical_state_snapshot(state)
        ):
            raise InvalidActionError(
                f"{adapter.card_name}响应动作绑定的状态哈希与当前状态不一致"
            )
        if bool(payload.get("zhangba_virtual")):
            # 丈八蛇矛虚拟打出：响应【南蛮入侵】时把两张手牌当作普通
            # 【杀】打出；材料对只通过不透明句柄解析。
            if adapter.card_key != "sgs_trick_nanmanruqin":
                raise InvalidActionError(
                    "只有响应【南蛮入侵】要求打出【杀】时可以使用丈八转化"
                )
            if (
                equipped_weapon_key(state, context.actor_id)
                != "sgs_weapon_zhangbashemao"
            ):
                raise InvalidActionError(
                    "丈八蛇矛在选择前已失去，旧转化动作失败关闭"
                )
            window_id = self._group_response_window_id(runtime, group)
            material_ids = _resolve_zhangba_handle_direct(
                self._session_id,
                self._session_secret,
                state,
                window_id,
                context.actor_id,
                payload.get("handle"),
            )
            if material_ids is None:
                raise InvalidActionError(
                    "丈八材料句柄无效：伪造、跨窗口、跨会话或手牌已变化"
                )
            virtual_id = (
                f"virtual:zhangba:{runtime.turn_number}:"
                f"{material_ids[0]}:{material_ids[1]}"
            )
            if action.card_instance_id != virtual_id:
                raise InvalidActionError(
                    "丈八虚拟杀动作与材料组合不一致"
                )
            check_weapon_skill_gate(
                state,
                actor_id=context.actor_id,
                decision="play_slash",
            )
            next_state, material_events = (
                self._discard_zhangba_materials(
                    state,
                    actor_id=context.actor_id,
                    material_ids=material_ids,
                    window_id=(
                        f"zhangba-materials:{runtime.turn_number}:"
                        f"{context.actor_id}"
                    ),
                    purpose=f"{group.trick_key}_response",
                )
            )
            played_event = GameEvent(
                event_type=EventType.CARD_PLAYED,
                card_instance_id=virtual_id,
                card_key="sgs_basic_sha",
                card_user=context.actor_id,
                target_ids=(current,),
                payload={
                    "response_to": group.trick_instance_id,
                    "root_trick_instance_id": group.trick_instance_id,
                    "response_action": "play",
                    "purpose": f"{group.trick_key}_response",
                    "creates_card_used_event": False,
                    "creates_card_played_event": True,
                    "counts_for_use_or_play_total": True,
                    "physical_or_virtual": "virtual",
                    "virtual_source": "sgs_weapon_zhangbashemao",
                    "material_card_instance_ids": list(material_ids),
                    "response_provider": context.actor_id,
                    "group_target_id": current,
                    "group_target_index": group.current_target_index,
                    "group_target_count": len(group.target_sequence),
                    "group_user_id": group.user_id,
                },
            )
            self._events.extend((played_event, *material_events))
            resolved = self._group_resolved_event(
                next_state, group, current, result="responded"
            )
            self._events.extend((resolved,))
            next_state, next_runtime = self._advance_group_target(
                next_state, runtime, group, current
            )
            self._commit_runtime(runtime, next_runtime)
            return next_state
        handle = payload.get("handle")
        instance_id = _resolve_group_response_handle(
            self._session_id,
            self._session_secret,
            state,
            self._group_response_window_id(runtime, group),
            current,
            runtime.group_response_snapshot_digest,
            runtime.group_response_handles,
            handle,
        )
        if instance_id is None:
            raise InvalidActionError(
                f"{adapter.card_name}响应句柄无效、伪造或已过期"
            )
        card = state.cards_by_id[instance_id]
        if card.card_key not in adapter.response_card_keys:
            raise InvalidActionError(
                f"响应{adapter.card_name}的实体牌必须是合法响应牌"
            )
        if state.location_of(instance_id) != ZoneRef.hand(context.actor_id):
            raise InvalidActionError("只能打出行动角色真实手牌中的实体牌")
        if adapter.card_key == "sgs_trick_nanmanruqin":
            # 【南蛮入侵】要求打出【杀】：丈八蛇矛等打出转化可能改变
            # 合法响应集合，在首次判断前失败关闭。
            check_weapon_skill_gate(
                state,
                actor_id=context.actor_id,
                decision="play_slash",
            )

        played_event = GameEvent(
            event_type=EventType.CARD_PLAYED,
            card_instance_id=instance_id,
            card_key=card.card_key,
            card_user=context.actor_id,
            target_ids=(current,),
            payload={
                "response_to": group.trick_instance_id,
                "root_trick_instance_id": group.trick_instance_id,
                "response_action": "play",
                "purpose": f"{group.trick_key}_response",
                "creates_card_used_event": False,
                "creates_card_played_event": True,
                "counts_for_use_or_play_total": True,
                "physical_or_virtual": "physical",
                "response_provider": context.actor_id,
                "group_target_id": current,
                "group_target_index": group.current_target_index,
                "group_target_count": len(group.target_sequence),
                "group_user_id": group.user_id,
            },
        )
        next_state, move_events = self._consume_immediately(
            state,
            instance_id,
            context.actor_id,
            f"{group.trick_key}_response",
        )
        self._events.extend((played_event, *move_events))
        resolved = self._group_resolved_event(
            next_state, group, current, result="responded"
        )
        self._events.extend((resolved,))
        next_state, next_runtime = self._advance_group_target(
            next_state, runtime, group, current
        )
        self._commit_runtime(runtime, next_runtime)
        return next_state

    def apply_pass_group_response(
        self,
        state: GameState,
        context: ActionContext,
        action: LegalAction,
        adapter: GroupTargetTrickAdapter,
    ) -> GameState:
        """当前目标主动不响应：受到1点无属性伤害并进入濒死／继续流程。"""

        del action
        runtime = self._runtime
        if runtime.phase.value != adapter.response_phase_value:
            raise InvalidActionError(
                f"放弃{adapter.card_name}响应只能在对应响应阶段进行"
            )
        group = runtime.pending_group_trick
        if group is None or group.trick_key != adapter.card_key:
            raise InvalidActionError("当前没有进行中的群体锦囊响应")
        if group.responder_id is None or context.actor_id != group.responder_id:
            raise InvalidActionError("只有当前响应目标可以放弃响应")
        current = group.target_sequence[group.current_target_index]
        next_state, next_runtime = self._apply_group_trick_damage(
            state, runtime, group, current
        )
        self._commit_runtime(runtime, next_runtime)
        return next_state

    def apply_pass_nanman_slash(
        self,
        state: GameState,
        context: ActionContext,
        action: LegalAction,
    ) -> GameState:
        return self.apply_pass_group_response(
            state,
            context,
            action,
            self._formal_registry.adapter_for("sgs_trick_nanmanruqin"),
        )

    def apply_pass_wanjian_jink(
        self,
        state: GameState,
        context: ActionContext,
        action: LegalAction,
    ) -> GameState:
        return self.apply_pass_group_response(
            state,
            context,
            action,
            self._formal_registry.adapter_for("sgs_trick_wanjianqifa"),
        )

    def _apply_trick_damage(
        self,
        state: GameState,
        *,
        victim_id: str,
        source_id: str,
        card_instance_id: str,
        card_key: str,
        card_user: str,
        damage_type: str,
        resolved_reason: str,
        death_reason: str,
        rescue_reason: str,
    ) -> tuple[GameState, _BatchRuntime]:
        """普通锦囊伤害的公共结算：伤害事件、濒死救援或完成结算。

        伤害来源、击杀归属与伤害关联牌由调用方按规则传入；濒死时记录
        通用伤害来源字段，救援完成或死亡时由救援流程完成原锦囊结算。
        """
        runtime = self._runtime
        next_state, next_runtime = self._apply_damage_and_maybe_chain(
            state,
            runtime,
            victim_id=victim_id,
            amount=1,
            damage_type=damage_type,
            card_instance_id=card_instance_id,
            card_key=card_key,
            card_user=card_user,
            source_id=source_id,
            kill_credit=source_id,
            resolved_reason=resolved_reason,
            death_reason=death_reason,
            rescue_reason=rescue_reason,
        )
        return next_state, next_runtime

    def apply_peach_self_heal(
        self,
        state: GameState,
        context: ActionContext,
        action: LegalAction,
        adapter: object,
    ) -> GameState:
        del adapter
        runtime = self._runtime
        if runtime.phase is not ProductionPhase.PLAY:
            raise InvalidActionError("【桃】普通回复只能在出牌阶段使用")
        player = state.players_by_id[context.actor_id]
        if player.hp >= player.max_hp:
            raise InvalidActionError("满体力时不能通过普通自用【桃】获得回复")
        if action.card_instance_id is None:
            raise InvalidActionError("使用【桃】必须指定实体牌")
        card = state.cards_by_id[action.card_instance_id]
        if card.card_key != "sgs_basic_tao":
            raise InvalidActionError("回复动作的实体牌必须是【桃】")
        if action.target_ids != (context.actor_id,):
            raise InvalidActionError("出牌阶段普通自用【桃】只能以自己为目标")
        if state.location_of(action.card_instance_id) != ZoneRef.hand(
            context.actor_id
        ):
            raise InvalidActionError("只能使用行动角色真实手牌中的实体牌")

        next_state, move_events = self._consume_immediately(
            state, action.card_instance_id, context.actor_id, "peach_resolve"
        )
        healed = next_state.players_by_id[context.actor_id]
        next_state = _replace_player(
            next_state,
            context.actor_id,
            hp=min(healed.max_hp, healed.hp + 1),
        )
        self._events.extend(
            (
                GameEvent(
                    event_type=EventType.CARD_USED,
                    card_instance_id=action.card_instance_id,
                    card_key="sgs_basic_tao",
                    card_user=context.actor_id,
                    target_ids=(context.actor_id,),
                    payload={"purpose": "heal_self"},
                ),
                *move_events,
            )
        )
        self._commit_runtime(runtime, runtime)
        return next_state

    def apply_wine_buff(
        self,
        state: GameState,
        context: ActionContext,
        action: LegalAction,
        adapter: object,
    ) -> GameState:
        del adapter
        runtime = self._runtime
        if runtime.phase is not ProductionPhase.PLAY:
            raise InvalidActionError("【酒】强化用途只能在出牌阶段使用")
        if runtime.wine_buff_used_this_play_phase:
            raise InvalidActionError("出牌阶段【酒】强化用途每出牌阶段限一次")
        if action.card_instance_id is None:
            raise InvalidActionError("使用【酒】必须指定实体牌")
        card = state.cards_by_id[action.card_instance_id]
        if card.card_key != "sgs_basic_jiu":
            raise InvalidActionError("强化动作的实体牌必须是【酒】")
        if action.target_ids != (context.actor_id,):
            raise InvalidActionError("出牌阶段【酒】只能以自己为目标")
        if state.location_of(action.card_instance_id) != ZoneRef.hand(
            context.actor_id
        ):
            raise InvalidActionError("只能使用行动角色真实手牌中的实体牌")

        next_state, move_events = self._consume_immediately(
            state, action.card_instance_id, context.actor_id, "wine_buff_resolve"
        )
        self._events.extend(
            (
                GameEvent(
                    event_type=EventType.CARD_USED,
                    card_instance_id=action.card_instance_id,
                    card_key="sgs_basic_jiu",
                    card_user=context.actor_id,
                    target_ids=(context.actor_id,),
                    payload={"purpose": "play_phase_slash_buff"},
                ),
                *move_events,
            )
        )
        next_runtime = replace(
            runtime,
            wine_buff_owner_id=context.actor_id,
            wine_buff_used_this_play_phase=True,
        )
        self._commit_runtime(runtime, next_runtime)
        return next_state

    def _pending_damage_card_id(self, runtime: _BatchRuntime) -> str:
        if runtime.pending_slash is not None:
            return runtime.pending_slash.slash_instance_id
        if runtime.pending_damage_card_id is not None:
            return runtime.pending_damage_card_id
        raise ProductionBatchError("濒死结算缺少伤害来源实体牌")

    def _pending_damage_rescue_reason(self, runtime: _BatchRuntime) -> str:
        if runtime.pending_slash is not None:
            return "slash_damage_resolved_after_rescue"
        if runtime.pending_damage_rescue_reason is not None:
            return runtime.pending_damage_rescue_reason
        raise ProductionBatchError("濒死结算缺少救援完成原因")

    def _pending_damage_death_reason(self, runtime: _BatchRuntime) -> str:
        if runtime.pending_slash is not None:
            return "slash_damage_resolved_with_death"
        if runtime.pending_damage_death_reason is not None:
            return runtime.pending_damage_death_reason
        raise ProductionBatchError("濒死结算缺少死亡完成原因")

    def _pending_damage_source(self, runtime: _BatchRuntime) -> str | None:
        if runtime.pending_slash is not None:
            return runtime.pending_slash.attacker_id
        if runtime.pending_damage_source_id is not None:
            return runtime.pending_damage_source_id
        return None

    def _rescue_window_id(
        self, runtime: _BatchRuntime, seat: int, decision_count: int
    ) -> str:
        assert runtime.pending_dying_id is not None
        return (
            f"dying:{runtime.turn_number}:{runtime.pending_dying_id}"
            f":seat{seat}:dec{decision_count}"
        )

    def apply_peach_rescue(
        self,
        state: GameState,
        context: ActionContext,
        action: LegalAction,
        adapter: object,
    ) -> GameState:
        del adapter
        runtime = self._runtime
        if runtime.phase is not ProductionPhase.DYING_RESCUE:
            raise InvalidActionError("【桃】救援只能在濒死救援窗口使用")
        dying_id = runtime.pending_dying_id
        if dying_id is None or not runtime.rescue_order:
            raise InvalidActionError("当前没有进行中的濒死救援")
        if runtime.rescue_index >= len(runtime.rescue_order):
            raise InvalidActionError("濒死救援顺序已经耗尽")
        if context.actor_id != runtime.rescue_order[runtime.rescue_index]:
            raise InvalidActionError("当前不是该角色的救援时机")
        if action.card_instance_id is None:
            raise InvalidActionError("救援必须使用真实实体【桃】")
        card = state.cards_by_id[action.card_instance_id]
        if card.card_key != "sgs_basic_tao":
            raise InvalidActionError("救援动作的实体牌必须是【桃】")
        if action.target_ids != (dying_id,):
            raise InvalidActionError("救援【桃】只能以濒死角色为目标")
        if state.players_by_id[dying_id].hp >= 1:
            raise InvalidActionError("目标已经脱离濒死，无需继续救援")
        if state.location_of(action.card_instance_id) != ZoneRef.hand(
            context.actor_id
        ):
            raise InvalidActionError("只能使用救援角色真实手牌中的实体牌")

        window = self._build_window(runtime)
        rescue_event = GameEvent(
            event_type=EventType.CARD_USED,
            card_instance_id=action.card_instance_id,
            card_key="sgs_basic_tao",
            card_user=context.actor_id,
            target_ids=(dying_id,),
            payload={"purpose": "dying_rescue"},
        )
        record = window.respond(context.actor_id, rescue_event)
        assert record.response_event is not None
        next_state, move_events = self._consume_immediately(
            state, action.card_instance_id, context.actor_id, "dying_rescue"
        )
        dying = next_state.players_by_id[dying_id]
        next_state = _replace_player(
            next_state, dying_id, hp=min(dying.max_hp, dying.hp + 1)
        )
        pending_events: list[GameEvent] = [
            record.response_event,
            *move_events,
        ]
        if next_state.players_by_id[dying_id].hp >= 1:
            if runtime.pending_group_trick is not None:
                self._events.extend(pending_events)
                # 群体锦囊：救援完成后恢复逐目标队列，原锦囊继续留在
                # 处理区，直到全部目标完成才进入弃牌堆。
                next_state, next_runtime = self._resume_group_after_damage(
                    next_state, runtime, dying_id, rescued=True
                )
            elif runtime.pending_chain is not None:
                self._events.extend(pending_events)
                # 属性伤害传导：原始角色或传导目标救援完成后，从准确索引
                # 恢复传导；原始角色先完成根牌结算再继续。
                next_state, next_runtime = self._resume_chain_after_rescue(
                    next_state, runtime, dying_id, rescued=True
                )
            else:
                if (
                    runtime.defer_damage_card_finish
                    or runtime.damage_card_already_finished
                ):
                    next_state = next_state
                else:
                    next_state, finish_event = self._finish_processing(
                        next_state,
                        self._pending_damage_card_id(runtime),
                        self._pending_damage_rescue_reason(runtime),
                    )
                    pending_events.append(finish_event)
                self._events.extend(pending_events)
                next_state, next_runtime = self._complete_root_resolution(
                    next_state, runtime
                )
        else:
            self._events.extend(pending_events)
            decision_count = runtime.rescue_decision_count + 1
            next_runtime = replace(
                runtime,
                rescue_decision_count=decision_count,
                response_window_id=self._rescue_window_id(
                    runtime, runtime.rescue_index, decision_count
                ),
                response_window_order=(context.actor_id,),
            )
        self._commit_runtime(runtime, next_runtime)
        return next_state

    def apply_wine_self_rescue(
        self,
        state: GameState,
        context: ActionContext,
        action: LegalAction,
        adapter: object,
    ) -> GameState:
        del adapter
        runtime = self._runtime
        if runtime.phase is not ProductionPhase.DYING_RESCUE:
            raise InvalidActionError("【酒】自救只能在濒死救援窗口使用")
        dying_id = runtime.pending_dying_id
        if dying_id is None or not runtime.rescue_order:
            raise InvalidActionError("当前没有进行中的濒死救援")
        if runtime.rescue_index >= len(runtime.rescue_order):
            raise InvalidActionError("濒死救援顺序已经耗尽")
        if context.actor_id != runtime.rescue_order[runtime.rescue_index]:
            raise InvalidActionError("当前不是该角色的救援时机")
        if context.actor_id != dying_id:
            raise InvalidActionError("濒死自救【酒】只能对濒死的自己使用")
        if action.card_instance_id is None:
            raise InvalidActionError("自救必须使用真实实体【酒】")
        card = state.cards_by_id[action.card_instance_id]
        if card.card_key != "sgs_basic_jiu":
            raise InvalidActionError("自救动作的实体牌必须是【酒】")
        if action.target_ids != (context.actor_id,):
            raise InvalidActionError("濒死自救【酒】只能以自己为目标")
        if state.players_by_id[dying_id].hp >= 1:
            raise InvalidActionError("角色已经脱离濒死，无需继续自救")
        if state.location_of(action.card_instance_id) != ZoneRef.hand(
            context.actor_id
        ):
            raise InvalidActionError("只能使用自救角色真实手牌中的实体牌")

        window = self._build_window(runtime)
        rescue_event = GameEvent(
            event_type=EventType.CARD_USED,
            card_instance_id=action.card_instance_id,
            card_key="sgs_basic_jiu",
            card_user=context.actor_id,
            target_ids=(context.actor_id,),
            payload={"purpose": "dying_self_rescue"},
        )
        record = window.respond(context.actor_id, rescue_event)
        assert record.response_event is not None
        next_state, move_events = self._consume_immediately(
            state, action.card_instance_id, context.actor_id, "dying_self_rescue"
        )
        dying = next_state.players_by_id[dying_id]
        next_state = _replace_player(
            next_state, dying_id, hp=min(dying.max_hp, dying.hp + 1)
        )
        pending_events: list[GameEvent] = [
            record.response_event,
            *move_events,
        ]
        if next_state.players_by_id[dying_id].hp >= 1:
            if runtime.pending_group_trick is not None:
                self._events.extend(pending_events)
                # 群体锦囊：救援完成后恢复逐目标队列，原锦囊继续留在
                # 处理区，直到全部目标完成才进入弃牌堆。
                next_state, next_runtime = self._resume_group_after_damage(
                    next_state, runtime, dying_id, rescued=True
                )
            elif runtime.pending_chain is not None:
                self._events.extend(pending_events)
                # 属性伤害传导：救援完成后恢复挂起队列。
                next_state, next_runtime = self._resume_chain_after_rescue(
                    next_state, runtime, dying_id, rescued=True
                )
            else:
                if (
                    runtime.defer_damage_card_finish
                    or runtime.damage_card_already_finished
                ):
                    next_state = next_state
                else:
                    next_state, finish_event = self._finish_processing(
                        next_state,
                        self._pending_damage_card_id(runtime),
                        self._pending_damage_rescue_reason(runtime),
                    )
                    pending_events.append(finish_event)
                self._events.extend(pending_events)
                next_state, next_runtime = self._complete_root_resolution(
                    next_state, runtime
                )
        else:
            self._events.extend(pending_events)
            decision_count = runtime.rescue_decision_count + 1
            next_runtime = replace(
                runtime,
                rescue_decision_count=decision_count,
                response_window_id=self._rescue_window_id(
                    runtime, runtime.rescue_index, decision_count
                ),
                response_window_order=(context.actor_id,),
            )
        self._commit_runtime(runtime, next_runtime)
        return next_state

    def apply_pass_rescue(
        self,
        state: GameState,
        context: ActionContext,
        action: LegalAction,
    ) -> GameState:
        del action
        runtime = self._runtime
        if runtime.phase is not ProductionPhase.DYING_RESCUE:
            raise InvalidActionError("放弃救援只能在濒死救援窗口进行")
        dying_id = runtime.pending_dying_id
        if dying_id is None or not runtime.rescue_order:
            raise InvalidActionError("当前没有进行中的濒死救援")
        if runtime.rescue_index >= len(runtime.rescue_order):
            raise InvalidActionError("濒死救援顺序已经耗尽")
        if context.actor_id != runtime.rescue_order[runtime.rescue_index]:
            raise InvalidActionError("当前不是该角色的救援时机")
        window = self._build_window(runtime)
        window.pass_response(context.actor_id)

        next_index = runtime.rescue_index + 1
        if next_index < len(runtime.rescue_order):
            next_runtime = replace(
                runtime,
                rescue_index=next_index,
                rescue_decision_count=0,
                response_window_id=self._rescue_window_id(
                    runtime, next_index, 0
                ),
                response_window_order=(runtime.rescue_order[next_index],),
            )
            self._commit_runtime(runtime, next_runtime)
            return state
        dying = state.players_by_id[dying_id]
        if dying.hp >= 1:
            if runtime.pending_group_trick is not None:
                # 群体锦囊：救援完成后恢复逐目标队列，原锦囊继续留在
                # 处理区，直到全部目标完成才进入弃牌堆。
                next_state, next_runtime = self._resume_group_after_damage(
                    state, runtime, dying_id, rescued=True
                )
                self._commit_runtime(runtime, next_runtime)
                return next_state
            if runtime.pending_chain is not None:
                # 属性伤害传导：救援完成后恢复挂起队列。
                next_state, next_runtime = self._resume_chain_after_rescue(
                    state, runtime, dying_id, rescued=True
                )
                self._commit_runtime(runtime, next_runtime)
                return next_state
            if (
                runtime.defer_damage_card_finish
                or runtime.damage_card_already_finished
            ):
                # 根牌（闪电）完成时点由 _complete_root_resolution 控制
                next_state = state
            else:
                next_state, finish_event = self._finish_processing(
                    state,
                    self._pending_damage_card_id(runtime),
                    self._pending_damage_rescue_reason(runtime),
                )
                self._events.extend((finish_event,))
            next_state, next_runtime = self._complete_root_resolution(
                next_state, runtime
            )
            self._commit_runtime(runtime, next_runtime)
            return next_state
        if runtime.pending_wugu is not None:
            # 胜利成立前若仍有进行中的五谷结算：按确定性顺序清理展示池
            # 与原五谷，不允许实体滞留在临时区域。当前正式卡牌组合下
            # 五谷／铁索结算不产生伤害，此分支是面向未来的引擎不变量。
            next_state, pool_events = self._discard_revealed_pool(
                state,
                runtime.pending_wugu,
                reason="wugu_early_end_remaining_to_discard",
            )
            self._events.extend(pool_events)
            next_state, wugu_finish_event = self._finish_processing(
                next_state,
                runtime.pending_wugu.trick_instance_id,
                "wugu_early_end_cleared",
            )
            self._events.extend((wugu_finish_event,))
        else:
            next_state = state
        chain = runtime.pending_chain
        if chain is not None and dying_id != chain.original_target_id:
            # 传导目标死亡时根牌已完成结算，不再重复处理根牌。
            finish_events: list[GameEvent] = []
        elif (
            runtime.defer_damage_card_finish
            or runtime.damage_card_already_finished
        ):
            # 根牌（闪电）完成时点由本路径统一清理
            finish_events = []
        else:
            next_state, finish_event = self._finish_processing(
                next_state,
                self._pending_damage_card_id(runtime),
                self._pending_damage_death_reason(runtime),
            )
            finish_events = [finish_event]
        pending_judgment = runtime.pending_judgment
        if (
            pending_judgment is not None
            and pending_judgment.stage == "resolving_effect"
            and not pending_judgment.cleanup_done
        ):
            next_state, judgment_finish = self._finish_processing(
                next_state,
                pending_judgment.trick_instance_id,
                "shandian_victory_cleanup",
                extra={
                    "judgment_zone_entry_index": pending_judgment.entry_index,
                    "game_over_cleanup": True,
                },
            )
            finish_events = [*finish_events, judgment_finish]
        # 死亡区域清理：死亡角色手牌区、装备区、判定区全部牌进入弃牌堆；
        # 判定区实体离开后其 entry_index 一并移除（复审观察项二）。
        dying_judgment_ids = set(
            next_state.card_ids_in(ZoneRef.judgment(dying_id))
        )
        next_state, cleanup_events = self._death_zone_cleanup(
            next_state, dying_id
        )
        judgment_entry_indices_after_death = MappingProxyType(
            {
                key: value
                for key, value in runtime.judgment_entry_indices.items()
                if key not in dying_judgment_ids
            }
        )
        borrowed = runtime.pending_borrowed_sword
        if (
            borrowed is not None
            and borrowed.stage == "slash_resolving"
            and not borrowed.root_discarded
        ):
            # 终局清理：根借刀从处理区确定性进入弃牌堆，不遗留处理区。
            next_state, borrowed_finish = self._finish_processing(
                next_state,
                borrowed.trick_instance_id,
                "jiedaosharen_victory_cleanup",
                extra={
                    "game_over_cleanup": True,
                    "requirement_fulfilled": True,
                },
            )
            finish_events = [*finish_events, borrowed_finish]
        next_state = _replace_player(next_state, dying_id, alive=False)
        winner = self.opponent_of(dying_id)
        damage_source = self._pending_damage_source(runtime)
        final_events: list[GameEvent] = (
            finish_events + list(cleanup_events)
            + [
            GameEvent(
                event_type=EventType.DEATH,
                damage_source=damage_source,
                kill_credit=damage_source,
                target_ids=(dying_id,),
            ),
                GameEvent(
                    event_type=EventType.VICTORY,
                    target_ids=(winner,),
                ),
            ]
        )
        if chain is not None:
            skipped = tuple(
                candidate
                for candidate in chain.candidate_order
                if candidate not in chain.processed_target_ids
            )
            final_events.append(
                self._chain_finished_event(
                    chain,
                    chain.processed_target_ids,
                    skipped,
                    "winner",
                )
            )
        self._events.extend(final_events)
        next_runtime = replace(
            runtime,
            phase=ProductionPhase.FINISHED,
            winner_id=winner,
            pending_slash=None,
            pending_dying_id=None,
            rescue_order=(),
            rescue_index=0,
            rescue_decision_count=0,
            response_window_id=None,
            response_window_order=(),
            response_window_source_sequence=None,
            pending_zone_choice=None,
            zone_choice_handles=MappingProxyType({}),
            pending_duel=None,
            pending_fire_attack=None,
            fire_attack_reveal_handles=MappingProxyType({}),
            pending_group_trick=None,
            group_response_handles=MappingProxyType({}),
            group_response_snapshot_digest=None,
            pending_wugu=None,
            pending_borrowed_sword=None,
            borrowed_sword_slash_handles=MappingProxyType({}),
            borrowed_sword_slash_snapshot_digest=None,
            pending_damage_card_id=None,
            pending_damage_source_id=None,
            pending_damage_kill_credit=None,
            pending_chain=None,
            pending_judgment=None,
            processed_judgment_instance_ids=(),
            judgment_entry_indices=judgment_entry_indices_after_death,
            skipped_phases=MappingProxyType({}),
            phase_skip_reasons=MappingProxyType({}),
            defer_damage_card_finish=False,
            discard_phase_window_id=None,
            discard_phase_selected_ids=(),
            discard_phase_handles=MappingProxyType({}),
            discard_phase_snapshot_digest=None,
            pending_weapon_choice=None,
            pending_slash_choice=None,
            pending_discard_two=None,
            pending_hanbing_discard=None,
            damage_card_already_finished=False,
        )
        self._commit_runtime(runtime, next_runtime)
        return next_state

    def apply_delayed_trick_use(
        self,
        state: GameState,
        context: ActionContext,
        action: LegalAction,
        adapter: DelayedTrickAdapter,
    ) -> GameState:
        """出牌阶段使用延时锦囊：直接进入目标判定区（CP-04L）。

        不经过处理区、不开普通锦囊TRICK_RESPONSE窗口；判定区公开；进入
        判定区时分配单调递增 judgment_zone_entry_index；同名延时锦囊
        不得在同一角色判定区共存（枚举与apply双重验证）。
        """
        runtime = self._runtime
        if runtime.phase is not ProductionPhase.PLAY:
            raise InvalidActionError(f"{adapter.card_name}只能在出牌阶段使用")
        if context.actor_id != runtime.current_player_id:
            raise InvalidActionError("只有当前回合角色可以使用延时锦囊")
        if action.card_instance_id is None or len(action.target_ids) != 1:
            raise InvalidActionError("使用延时锦囊必须指定实体牌与恰好一名目标")
        card = state.cards_by_id[action.card_instance_id]
        if card.card_key != adapter.card_key:
            raise InvalidActionError("延时锦囊动作的实体牌与适配器卡牌键不一致")
        if str(action.payload.get("card_key", "")) != adapter.card_key:
            raise InvalidActionError("延时锦囊动作负载与适配器卡牌键不一致")
        if state.location_of(action.card_instance_id) != ZoneRef.hand(
            context.actor_id
        ):
            raise InvalidActionError("只能使用行动角色真实手牌中的实体牌")
        target = action.target_ids[0]
        if adapter.card_key == "sgs_delayed_shandian":
            if target != context.actor_id:
                raise InvalidActionError("【闪电】只能对自己使用")
        else:
            if target == context.actor_id:
                raise InvalidActionError(f"{adapter.card_name}不能对自己使用")
            if not state.players_by_id[target].alive:
                raise InvalidActionError("延时锦囊目标必须存活")
            if adapter.card_key == "sgs_delayed_bingliang":
                if actual_distance(state, context.actor_id, target) != 1:
                    raise InvalidActionError(
                        "【兵粮寸断】目标必须与使用者实际距离为1"
                    )
        # 同名限制（apply层重复验证）
        if any(
            state.cards_by_id[instance_id].card_key == adapter.card_key
            for instance_id in state.card_ids_in(ZoneRef.judgment(target))
        ):
            raise InvalidActionError(
                f"目标判定区不得已有同名{adapter.card_name}"
            )
        # 直接：手牌 → 目标判定区（不经处理区）
        source = state.location_of(action.card_instance_id)
        target_zone = ZoneRef.judgment(target)
        next_state = state.move_card(action.card_instance_id, target_zone)
        entry_index = runtime.judgment_entry_counter + 1
        placed_event = GameEvent(
            event_type=EventType.CARD_MOVED,
            card_instance_id=action.card_instance_id,
            card_key=adapter.card_key,
            card_user=context.actor_id,
            payload={
                "source": _zone_payload(source),
                "destination": _zone_payload(target_zone),
                "reason": "delayed_trick_placed",
                "judgment_zone_entry_index": entry_index,
            },
        )
        used_event = GameEvent(
            event_type=EventType.CARD_USED,
            card_instance_id=action.card_instance_id,
            card_key=adapter.card_key,
            card_user=context.actor_id,
            target_ids=(target,),
            payload={
                "purpose": "place_delayed_trick",
                "card_name": adapter.card_name,
                "judgment_zone_entry_index": entry_index,
            },
        )
        self._events.extend((used_event, placed_event))
        next_runtime = replace(
            runtime,
            judgment_entry_indices=MappingProxyType(
                {**runtime.judgment_entry_indices,
                 action.card_instance_id: entry_index}
            ),
            judgment_entry_counter=entry_index,
        )
        self._commit_runtime(runtime, next_runtime)
        return next_state

    def apply_proceed_prepare(
        self, state: GameState, context: ActionContext, action: LegalAction
    ) -> GameState:
        del action
        runtime = self._runtime
        if runtime.phase is not ProductionPhase.PREPARE:
            raise InvalidActionError("只有准备阶段可以进入判定阶段")
        if context.actor_id != runtime.current_player_id:
            raise InvalidActionError("只有当前回合角色可以推进准备阶段")
        next_runtime = replace(runtime, phase=ProductionPhase.JUDGMENT)
        self._commit_runtime(runtime, next_runtime)
        return state

    def apply_proceed_judgment(
        self, state: GameState, context: ActionContext, action: LegalAction
    ) -> GameState:
        del action
        runtime = self._runtime
        if runtime.phase is not ProductionPhase.JUDGMENT:
            raise InvalidActionError("只有判定阶段可以推进判定结算")
        if context.actor_id != runtime.current_player_id:
            raise InvalidActionError("只有当前回合角色可以推进判定阶段")
        unprocessed = [
            instance_id
            for instance_id in state.card_ids_in(
                ZoneRef.judgment(runtime.current_player_id)
            )
            if instance_id not in runtime.processed_judgment_instance_ids
        ]
        if unprocessed:
            next_state, next_runtime = self._open_next_judgment(state, runtime)
        else:
            next_state, next_runtime = self._advance_past_judgment(state, runtime)
        self._commit_runtime(runtime, next_runtime)
        return next_state

    def apply_proceed_draw(
        self, state: GameState, context: ActionContext, action: LegalAction
    ) -> GameState:
        del action
        runtime = self._runtime
        if runtime.phase is not ProductionPhase.DRAW:
            raise InvalidActionError("只有摸牌阶段可以摸牌")
        if context.actor_id != runtime.current_player_id:
            raise InvalidActionError("只有当前回合角色可以摸牌")
        next_state, draw_events = self._draw_cards(
            state, runtime.current_player_id, 2, reason="draw_phase"
        )
        self._events.extend(draw_events)
        events: list[GameEvent] = []
        next_phase = ProductionPhase.PLAY
        if "play" in runtime.skipped_phases:
            trick_id = runtime.skipped_phases["play"]
            events.append(
                GameEvent(
                    event_type=EventType.PHASE_SKIPPED,
                    card_instance_id=trick_id,
                    card_key=_card_key(state, trick_id),
                    target_ids=(runtime.current_player_id,),
                    payload={
                        "player_id": runtime.current_player_id,
                        "turn_number": runtime.turn_number,
                        "skipped_phase": "play",
                        "reason": runtime.phase_skip_reasons.get(
                            "play", "lebusi_judgment_hit"
                        ),
                        "delayed_trick_instance_id": trick_id,
                    },
                )
            )
            next_phase = ProductionPhase.DISCARD
        self._events.extend(tuple(events))
        next_runtime = replace(runtime, phase=next_phase)
        if next_runtime.phase is ProductionPhase.DISCARD:
            next_state, next_runtime = self._enter_discard_or_end(
                next_state, next_runtime
            )
        self._commit_runtime(runtime, next_runtime)
        return next_state

    def _open_next_judgment(
        self, state: GameState, runtime: _BatchRuntime
    ) -> tuple[GameState, _BatchRuntime]:
        """动态LIFO：读取当前判定区、排除本阶段已处理实例、选entry_index最大者。"""
        self._assert_judgment_entry_invariants(state, runtime)
        judgment_ids = state.card_ids_in(
            ZoneRef.judgment(runtime.current_player_id)
        )
        unprocessed = [
            instance_id
            for instance_id in judgment_ids
            if instance_id not in runtime.processed_judgment_instance_ids
        ]
        if not unprocessed:
            raise ProductionBatchError("当前没有待处理的判定区延时锦囊")

        def index_of(instance_id: str) -> int:
            index = runtime.judgment_entry_indices.get(instance_id)
            if index is None:
                raise ProductionBatchError(
                    f"判定区实体{instance_id}缺少judgment_zone_entry_index；失败关闭"
                )
            if isinstance(index, bool) or not isinstance(index, int) or index < 0:
                raise ProductionBatchError(
                    f"判定区实体{instance_id}的judgment_zone_entry_index非法；失败关闭"
                )
            return index

        next_id = max(unprocessed, key=index_of)
        card = state.cards_by_id[next_id]
        entry_index = index_of(next_id)
        pending = _PendingJudgment(
            trick_instance_id=next_id,
            trick_key=card.card_key,
            target_id=runtime.current_player_id,
            stage="awaiting_wuxie",
            entry_index=entry_index,
        )
        trick = _PendingTrick(
            runtime.current_player_id,
            runtime.current_player_id,
            next_id,
            card.card_key,
        )
        order = (
            runtime.current_player_id,
            self.opponent_of(runtime.current_player_id),
        )
        next_runtime = replace(
            runtime,
            phase=ProductionPhase.JUDGMENT_WUXIE,
            pending_judgment=pending,
            pending_trick=trick,
            trick_effect_active=True,
            trick_consecutive_passes=0,
            trick_response_order=order,
            trick_response_index=0,
            trick_decision_count=0,
            trick_direct_response_to=next_id,
            response_window_id=(
                f"judgment_wuxie:{runtime.turn_number}:{next_id}"
            ),
            response_window_order=(order[0],),
            response_window_source_sequence=None,
        )
        started = GameEvent(
            event_type=EventType.JUDGMENT_STARTED,
            card_instance_id=next_id,
            card_key=card.card_key,
            target_ids=(runtime.current_player_id,),
            payload={
                "delayed_trick_instance_id": next_id,
                "target_id": runtime.current_player_id,
                "judgment_zone_entry_index": entry_index,
            },
        )
        self._events.extend((started,))
        return state, next_runtime

    def _assert_judgment_entry_invariants(
        self, state: GameState, runtime: _BatchRuntime
    ) -> None:
        """判定区进入序号防御性不变量（CP-04L 审计修复 N4）。

        选择下一张判定牌前整体校验：所有处于判定区的实体必须有合法整数
        索引（bool 拒绝、正式约定从1开始）；活动判定区实体索引全局唯一
        （judgment_entry_counter 全局单调）；counter 不得落后于任何现存
        entry_index。任一不满足即失败关闭，不修改状态、事件、RNG 或
        pending。
        """

        indices = runtime.judgment_entry_indices
        active: list[tuple[str, int]] = []
        for player in state.players:
            if not player.alive:
                continue
            for instance_id in state.card_ids_in(
                ZoneRef.judgment(player.player_id)
            ):
                index = indices.get(instance_id)
                if index is None:
                    raise ProductionBatchError(
                        f"判定区实体{instance_id}缺少judgment_zone_entry_index；"
                        "失败关闭"
                    )
                if (
                    isinstance(index, bool)
                    or not isinstance(index, int)
                    or index < 1
                ):
                    raise ProductionBatchError(
                        f"判定区实体{instance_id}的judgment_zone_entry_index非法；"
                        "失败关闭"
                    )
                active.append((instance_id, index))
        seen: dict[int, str] = {}
        for instance_id, index in active:
            previous = seen.get(index)
            if previous is not None:
                raise ProductionBatchError(
                    f"判定区实体{instance_id}与{previous}的"
                    f"judgment_zone_entry_index重复（{index}）；失败关闭"
                )
            seen[index] = instance_id
        active_instance_ids = {instance_id for instance_id, _ in active}
        stale = sorted(
            set(indices).difference(active_instance_ids)
        )
        if stale:
            raise ProductionBatchError(
                f"判定区实体{'、'.join(stale)}的judgment_zone_entry_index"
                "残留（已不在判定区）；失败关闭"
            )
        if active and runtime.judgment_entry_counter < max(
            index for _, index in active
        ):
            raise ProductionBatchError(
                "judgment_entry_counter落后于现存判定区entry_index；失败关闭"
            )

    def _advance_past_judgment(
        self, state: GameState, runtime: _BatchRuntime
    ) -> tuple[GameState, _BatchRuntime]:
        """判定阶段无待处理牌后按本回合跳过标记推进：DRAW→PLAY→END。"""
        next_state = state
        events: list[GameEvent] = []
        next_runtime = replace(runtime, phase=ProductionPhase.DRAW)
        if "draw" in runtime.skipped_phases:
            trick_id = runtime.skipped_phases["draw"]
            events.append(
                GameEvent(
                    event_type=EventType.PHASE_SKIPPED,
                    card_instance_id=trick_id,
                    card_key=_card_key(state, trick_id),
                    target_ids=(runtime.current_player_id,),
                    payload={
                        "player_id": runtime.current_player_id,
                        "turn_number": runtime.turn_number,
                        "skipped_phase": "draw",
                        "reason": runtime.phase_skip_reasons.get(
                            "draw", "bingliang_judgment_hit"
                        ),
                        "delayed_trick_instance_id": trick_id,
                    },
                )
            )
            next_runtime = replace(
                next_runtime, phase=ProductionPhase.PLAY
            )
        if (
            next_runtime.phase is ProductionPhase.PLAY
            and "play" in runtime.skipped_phases
        ):
            trick_id = runtime.skipped_phases["play"]
            events.append(
                GameEvent(
                    event_type=EventType.PHASE_SKIPPED,
                    card_instance_id=trick_id,
                    card_key=_card_key(state, trick_id),
                    target_ids=(runtime.current_player_id,),
                    payload={
                        "player_id": runtime.current_player_id,
                        "turn_number": runtime.turn_number,
                        "skipped_phase": "play",
                        "reason": runtime.phase_skip_reasons.get(
                            "play", "lebusi_judgment_hit"
                        ),
                        "delayed_trick_instance_id": trick_id,
                    },
                )
            )
            next_runtime = replace(next_runtime, phase=ProductionPhase.DISCARD)
            next_state, next_runtime = self._enter_discard_or_end(
                next_state, next_runtime
            )
        self._events.extend(tuple(events))
        return next_state, next_runtime


    def _resolve_judgment_after_wuxie(
        self, state: GameState, runtime: _BatchRuntime
    ) -> tuple[GameState, _BatchRuntime]:
        """判定前无懈窗口关闭且未被抵消：翻判定牌并结算效果。"""
        pending = runtime.pending_judgment
        if pending is None or pending.stage != "awaiting_wuxie":
            raise ProductionBatchError("判定结算缺少挂起状态")
        next_state, take_events, result = self._judgment_card_take(
            state, runtime, pending
        )
        self._events.extend(take_events)
        return self._apply_delayed_trick_judged(
            next_state, runtime, pending, result
        )

    def _resolve_judgment_nullified(
        self, state: GameState, runtime: _BatchRuntime
    ) -> tuple[GameState, _BatchRuntime]:
        """判定前无懈窗口关闭且已被抵消：不翻判定牌，按牌自身规则处理去向。"""
        pending = runtime.pending_judgment
        if pending is None or pending.stage != "awaiting_wuxie":
            raise ProductionBatchError("判定取消结算缺少挂起状态")
        trick_id = pending.trick_instance_id
        cancelled = GameEvent(
            event_type=EventType.CARD_EFFECT_CANCELLED,
            card_instance_id=trick_id,
            card_key=pending.trick_key,
            card_user=runtime.current_player_id,
            target_ids=(pending.target_id,),
            payload={"reason": "nullified_by_wuxie"},
        )
        if pending.trick_key == "sgs_delayed_shandian":
            # 闪电被无懈：从当前角色判定区直接转移，不经过PROCESSING
            self._events.extend((cancelled,))
            return self._transfer_lightning(
                state, runtime, pending, from_processing=False
            )
        self._events.extend((cancelled,))
        next_state, enter_event = self._move_zone_to_processing(
            state, trick_id, ZoneRef.judgment(pending.target_id), None,
            "delayed_trick_nullified_enter_processing",
        )
        next_state, finish_event = self._finish_processing(
            next_state, trick_id, "delayed_trick_nullified_leave_processing"
        )
        self._events.extend((enter_event, finish_event))
        processed = (*runtime.processed_judgment_instance_ids, trick_id)
        base_runtime = self._return_to_play(runtime)
        next_runtime = replace(
            base_runtime,
            phase=ProductionPhase.JUDGMENT,
            pending_judgment=None,
            processed_judgment_instance_ids=processed,
            judgment_entry_indices=self._without_judgment_index(
                runtime, trick_id
            ),
        )
        return next_state, next_runtime

    def _judgment_card_take(
        self,
        state: GameState,
        runtime: _BatchRuntime,
        pending: _PendingJudgment,
    ) -> tuple[GameState, tuple[GameEvent, ...], dict[str, object]]:
        """原子取判定牌：预检→重洗→牌堆顶→REVEALED→公开→结果→弃置。"""
        # 原子预检：牌堆 + 可重洗弃牌堆 >= 1（在任何状态/RNG变化前失败关闭）
        _assert_deck_available(state, 1, "判定需要1张牌")
        next_state = state
        if not next_state.card_ids_in(DRAW_PILE):
            discard_ids = list(next_state.card_ids_in(DISCARD_PILE))
            self._rng.shuffle(discard_ids)
            sources = {
                instance_id: next_state.location_of(instance_id)
                for instance_id in discard_ids
            }
            next_state = next_state.reorder_zone(DRAW_PILE, tuple(discard_ids))
            self._events.extend(
                GameEvent(
                    event_type=EventType.CARD_MOVED,
                    card_instance_id=instance_id,
                    card_key=_card_key(next_state, instance_id),
                    payload={
                        "source": _zone_payload(sources[instance_id]),
                        "destination": _zone_payload(DRAW_PILE),
                        "reason": "reshuffle",
                    },
                )
                for instance_id in discard_ids
            )
        judge_id = next_state.card_ids_in(DRAW_PILE)[0]
        judge_card = next_state.cards_by_id[judge_id]
        take_event = GameEvent(
            event_type=EventType.CARD_MOVED,
            card_instance_id=judge_id,
            card_key=judge_card.card_key,
            payload={
                "source": _zone_payload(DRAW_PILE),
                "destination": _zone_payload(REVEALED_ZONE),
                "reason": "judgment_take",
                "delayed_trick_instance_id": pending.trick_instance_id,
            },
        )
        next_state = next_state.move_card(judge_id, REVEALED_ZONE)
        reveal_event = GameEvent(
            event_type=EventType.CARD_REVEALED,
            card_instance_id=judge_id,
            card_key=judge_card.card_key,
            target_ids=(pending.target_id,),
            payload={
                "reason": "judgment",
                "instance_id": judge_id,
                "card_key": judge_card.card_key,
                "name": judge_card.card_name,
                "suit": judge_card.suit,
                "rank": judge_card.rank,
                "target_id": pending.target_id,
                "delayed_trick_instance_id": pending.trick_instance_id,
            },
        )
        hit, skipped_phase, damage_amount, damage_type = self._judgment_outcome(
            pending.trick_key, judge_card.suit, judge_card.rank
        )
        result_event = GameEvent(
            event_type=EventType.JUDGMENT_RESULT,
            card_instance_id=judge_id,
            card_key=judge_card.card_key,
            target_ids=(pending.target_id,),
            payload={
                "delayed_trick_instance_id": pending.trick_instance_id,
                "judgment_card_instance_id": judge_id,
                "target_id": pending.target_id,
                "suit": judge_card.suit,
                "rank": judge_card.rank,
                "hit": hit,
                "skipped_phase": skipped_phase,
                "damage_amount": damage_amount,
                "damage_type": damage_type,
                "effect_applied": hit,
            },
        )
        resolve_event = GameEvent(
            event_type=EventType.CARD_MOVED,
            card_instance_id=judge_id,
            card_key=judge_card.card_key,
            payload={
                "source": _zone_payload(REVEALED_ZONE),
                "destination": _zone_payload(DISCARD_PILE),
                "reason": "judgment_card_resolved",
                "delayed_trick_instance_id": pending.trick_instance_id,
            },
        )
        next_state = next_state.move_card(judge_id, DISCARD_PILE)
        return next_state, (
            take_event,
            reveal_event,
            result_event,
            resolve_event,
        ), {
            "judgment_card_instance_id": judge_id,
            "suit": judge_card.suit,
            "rank": judge_card.rank,
            "hit": hit,
            "skipped_phase": skipped_phase,
            "damage_amount": damage_amount,
            "damage_type": damage_type,
        }

    @staticmethod
    def _judgment_outcome(
        trick_key: str, suit: str, rank: str
    ) -> tuple[bool, str | None, int | None, str | None]:
        if trick_key == "sgs_delayed_lebusi":
            return suit != "♥", "play" if suit != "♥" else None, None, None
        if trick_key == "sgs_delayed_bingliang":
            return suit != "♣", "draw" if suit != "♣" else None, None, None
        if trick_key == "sgs_delayed_shandian":
            try:
                numeric_rank = int(rank)
            except ValueError:
                numeric_rank = 0
            if suit == "♠" and 2 <= numeric_rank <= 9:
                return True, None, 3, "雷属性"
            return False, None, None, None
        raise UnsupportedRuleError(
            f"延时锦囊{trick_key}没有已实现的判定结果规则；失败关闭"
        )

    def _apply_delayed_trick_judged(
        self,
        state: GameState,
        runtime: _BatchRuntime,
        pending: _PendingJudgment,
        result: Mapping[str, object],
    ) -> tuple[GameState, _BatchRuntime]:
        trick_id = pending.trick_instance_id
        hit = bool(result["hit"])
        if pending.trick_key in ("sgs_delayed_lebusi", "sgs_delayed_bingliang"):
            base_runtime = runtime
            if hit:
                skipped_phase = str(result["skipped_phase"])
                skipped = {**runtime.skipped_phases, skipped_phase: trick_id}
                reasons = {
                    **runtime.phase_skip_reasons,
                    skipped_phase: (
                        "lebusi_judgment_hit"
                        if pending.trick_key == "sgs_delayed_lebusi"
                        else "bingliang_judgment_hit"
                    ),
                }
                base_runtime = replace(
                    runtime,
                    skipped_phases=MappingProxyType(skipped),
                    phase_skip_reasons=MappingProxyType(reasons),
                )
            next_state, enter_event = self._move_zone_to_processing(
                state, trick_id, ZoneRef.judgment(pending.target_id), None,
                "delayed_trick_use_resolution",
            )
            next_state, finish_event = self._finish_processing(
                next_state, trick_id, f"{pending.trick_key}_resolved"
            )
            self._events.extend((enter_event, finish_event))
            processed = (*base_runtime.processed_judgment_instance_ids, trick_id)
            next_runtime = replace(
                self._return_to_play(base_runtime),
                phase=ProductionPhase.JUDGMENT,
                pending_judgment=None,
                processed_judgment_instance_ids=processed,
                judgment_entry_indices=self._without_judgment_index(
                    base_runtime, trick_id
                ),
            )
            return next_state, next_runtime
        # 闪电
        next_state, enter_event = self._move_zone_to_processing(
            state, trick_id, ZoneRef.judgment(pending.target_id), None,
            "delayed_trick_use_resolution",
        )
        self._events.extend((enter_event,))
        if not hit:
            return self._transfer_lightning(
                next_state, runtime, pending, from_processing=True
            )
        resolving_runtime = replace(
            runtime,
            pending_judgment=replace(pending, stage="resolving_effect"),
            judgment_entry_indices=self._without_judgment_index(
                runtime, trick_id
            ),
        )
        return self._apply_damage_and_maybe_chain(
            next_state,
            resolving_runtime,
            victim_id=pending.target_id,
            amount=3,
            damage_type="雷属性",
            card_instance_id=trick_id,
            card_key="sgs_delayed_shandian",
            card_user=None,
            source_id=None,
            kill_credit=None,
            payload={"judgment_hit": True},
            resolved_reason="shandian_damage_resolved",
            death_reason="shandian_damage_resolved_with_death",
            rescue_reason="shandian_damage_resolved_after_rescue",
            defer_root_finish=True,
        )


    def _next_lightning_target(
        self, state: GameState, owner_id: str
    ) -> str:
        """从当前结算角色下家开始，按存活座次递增搜索无闪电的合法角色。"""
        players = list(state.players_by_id.values())
        owner_seat = state.players_by_id[owner_id].seat
        ring = len(players)

        def cyclic_step(player_id: str) -> int:
            return (state.players_by_id[player_id].seat - owner_seat) % ring

        ordered = sorted(
            [p for p in players if p.player_id != owner_id],
            key=lambda p: cyclic_step(p.player_id),
        )
        for player in ordered:
            if not player.alive:
                continue
            if any(
                state.cards_by_id[instance_id].card_key == "sgs_delayed_shandian"
                for instance_id in state.card_ids_in(
                    ZoneRef.judgment(player.player_id)
                )
            ):
                continue
            return player.player_id
        # 无其他合法角色：回置当前角色自己的判定区
        return owner_id

    def _transfer_lightning(
        self,
        state: GameState,
        runtime: _BatchRuntime,
        pending: _PendingJudgment,
        *,
        from_processing: bool,
    ) -> tuple[GameState, _BatchRuntime]:
        """闪电转移或回置：追加新entry_index，不弃置、不覆盖、不立即判定。"""
        trick_id = pending.trick_instance_id
        next_owner = self._next_lightning_target(state, pending.target_id)
        new_index = runtime.judgment_entry_counter + 1
        source_zone = (
            PROCESSING_ZONE
            if from_processing
            else ZoneRef.judgment(pending.target_id)
        )
        destination = ZoneRef.judgment(next_owner)
        next_state = state.move_card(trick_id, destination)
        moved = GameEvent(
            event_type=EventType.CARD_MOVED,
            card_instance_id=trick_id,
            card_key=pending.trick_key,
            payload={
                "source": _zone_payload(source_zone),
                "destination": _zone_payload(destination),
                "reason": "shandian_transfer",
                "judgment_zone_entry_index": new_index,
            },
        )
        transferred = GameEvent(
            event_type=EventType.DELAYED_TRICK_TRANSFERRED,
            card_instance_id=trick_id,
            card_key=pending.trick_key,
            target_ids=(next_owner,),
            payload={
                "from_player_id": pending.target_id,
                "to_player_id": next_owner,
                "judgment_zone_entry_index": new_index,
                "reason": (
                    "shandian_transfer"
                    if next_owner != pending.target_id
                    else "shandian_self_restore"
                ),
            },
        )
        self._events.extend((moved, transferred))
        processed = (*runtime.processed_judgment_instance_ids, trick_id)
        base_runtime = self._return_to_play(runtime)
        next_runtime = replace(
            base_runtime,
            phase=ProductionPhase.JUDGMENT,
            pending_judgment=None,
            processed_judgment_instance_ids=processed,
            judgment_entry_indices=MappingProxyType(
                {
                    **{
                        key: value
                        for key, value in runtime.judgment_entry_indices.items()
                        if key != trick_id
                    },
                    trick_id: new_index,
                }
            ),
            judgment_entry_counter=new_index,
        )
        return next_state, next_runtime

    def _without_judgment_index(
        self,
        runtime: _BatchRuntime,
        instance_id: str,
    ) -> Mapping[str, int]:
        """移除指定实例的判定区进入索引（CP-04L 复审观察项二）。"""

        return MappingProxyType(
            {
                key: value
                for key, value in runtime.judgment_entry_indices.items()
                if key != instance_id
            }
        )

    def _move_zone_to_processing(
        self,
        state: GameState,
        instance_id: str,
        source_zone: ZoneRef,
        card_user: str | None,
        reason: str,
    ) -> tuple[GameState, GameEvent]:
        """把实体牌从指定区域进入PROCESSING（CP-04L最小泛化）。"""
        source = state.location_of(instance_id)
        if source != source_zone:
            raise ProductionBatchError(
                f"只能从{str(source_zone)}进入处理区"
            )
        next_state = state.move_card(instance_id, PROCESSING_ZONE)
        return next_state, GameEvent(
            event_type=EventType.CARD_MOVED,
            card_instance_id=instance_id,
            card_key=_card_key(state, instance_id),
            card_user=card_user,
            payload={
                "source": _zone_payload(source),
                "destination": _zone_payload(PROCESSING_ZONE),
                "reason": reason,
            },
        )

    def _death_zone_cleanup(
        self, state: GameState, player_id: str
    ) -> tuple[GameState, tuple[GameEvent, ...]]:
        """角色正式死亡：手牌区、装备区、判定区全部牌以系统区域移动事件进入弃牌堆。"""
        zones: list[ZoneRef] = [ZoneRef.hand(player_id)]
        for slot in (
            "weapon",
            "armor",
            "attack_horse",
            "defense_horse",
            "treasure",
        ):
            zones.append(ZoneRef.equipment(player_id, slot))
        zones.append(ZoneRef.judgment(player_id))
        next_state = state
        events: list[GameEvent] = []
        for zone in zones:
            for instance_id in next_state.card_ids_in(zone):
                next_state = next_state.move_card(instance_id, DISCARD_PILE)
                events.append(
                    GameEvent(
                        event_type=EventType.CARD_MOVED,
                        card_instance_id=instance_id,
                        card_key=_card_key(state, instance_id),
                        payload={
                            "source": _zone_payload(zone),
                            "destination": _zone_payload(DISCARD_PILE),
                            "reason": "death_cleanup",
                        },
                    )
                )
        return next_state, tuple(events)

    def _complete_root_resolution(
        self,
        state: GameState,
        runtime: _BatchRuntime,
    ) -> tuple[GameState, _BatchRuntime]:
        """根结算完成出口：优先恢复pending_judgment（闪电），再恢复
        pending_borrowed_sword，否则返回正常阶段。"""
        pending_judgment = runtime.pending_judgment
        if (
            pending_judgment is not None
            and pending_judgment.stage == "resolving_effect"
        ):
            if pending_judgment.cleanup_done:
                raise ProductionBatchError("判定根不能重复清理")
            next_state, finish_event = self._finish_processing(
                state,
                pending_judgment.trick_instance_id,
                "shandian_resolved",
                extra={
                    "judgment_zone_entry_index": pending_judgment.entry_index,
                },
            )
            self._events.extend((finish_event,))
            processed = (
                *runtime.processed_judgment_instance_ids,
                pending_judgment.trick_instance_id,
            )
            base_runtime = self._return_to_play(runtime)
            next_runtime = replace(
                base_runtime,
                phase=ProductionPhase.JUDGMENT,
                pending_judgment=None,
                processed_judgment_instance_ids=processed,
                defer_damage_card_finish=False,
            )
            return next_state, next_runtime
        pending = runtime.pending_borrowed_sword
        if pending is not None and pending.stage == "slash_resolving":
            if pending.root_discarded:
                raise ProductionBatchError("借刀根锦囊不能重复弃置")
            next_state, finish_event = self._finish_processing(
                state,
                pending.trick_instance_id,
                "jiedaosharen_fulfilled",
                extra={
                    "decision": pending.decision,
                    "chosen_slash_instance_id": pending.chosen_slash_instance_id,
                    "requirement_fulfilled": True,
                },
            )
            self._events.extend((finish_event,))
            base_runtime = self._return_to_play(runtime)
            next_runtime = replace(base_runtime, pending_borrowed_sword=None)
            return next_state, next_runtime
        return state, self._return_to_play(runtime)

    def _apply_end_play_phase(
        self,
        state: GameState,
        context: ActionContext,
        action: LegalAction,
    ) -> GameState:
        del action
        runtime = self._runtime
        if runtime.phase is not ProductionPhase.PLAY:
            raise InvalidActionError("只有出牌阶段可以结束出牌阶段")
        if context.actor_id != runtime.current_player_id:
            raise InvalidActionError("只有当前回合角色可以结束出牌阶段")
        next_state, next_runtime = self._enter_discard_or_end(state, runtime)
        self._commit_runtime(runtime, next_runtime)
        return next_state

    def _enter_discard_or_end(
        self,
        state: GameState,
        runtime: _BatchRuntime,
    ) -> tuple[GameState, _BatchRuntime]:
        """进入弃牌阶段：手牌数超过手牌上限时停留，否则自动进入结束阶段。

        手牌上限默认等于当前体力值（Knowledge 3.5）；装备区与判定区不计入
        手牌数。excess<=0 时自动完成弃牌阶段并进入 END，不开放伪弃牌动作。
        需要弃牌时打开一次性批量选择窗口：服务端记录手牌快照摘要与隐藏
        句柄，客户端选择过程只累积待选集合，最终确认前不移动任何牌。"""

        player_id = runtime.current_player_id
        hand_count = len(state.card_ids_in(ZoneRef.hand(player_id)))
        hand_limit = hand_limit_of(state, player_id)
        if hand_count <= hand_limit:
            return state, replace(runtime, phase=ProductionPhase.END)
        window_id = f"discard-phase:{runtime.turn_number}:{player_id}"
        hand_ids = tuple(state.card_ids_in(ZoneRef.hand(player_id)))
        snapshot_digest = sha256_value(hand_ids)
        next_runtime = replace(
            runtime,
            phase=ProductionPhase.DISCARD,
            discard_phase_window_id=window_id,
            discard_phase_selected_ids=(),
            discard_phase_handles=_zone_choice_handle_snapshot(
                self._session_id,
                self._session_secret,
                state,
                player_id,
                window_id,
                snapshot_digest,
            ),
            discard_phase_snapshot_digest=snapshot_digest,
        )
        return state, next_runtime

    def _resolve_discard_handle(
        self,
        state: GameState,
        runtime: _BatchRuntime,
        actor_id: str,
        handle: object,
    ) -> str | None:
        """解析弃牌选择句柄为窗口快照中的真实手牌实体。

        复用隐藏手牌句柄安全体系：句柄必须存在于窗口打开时的服务端快照
        映射、HMAC重算一致、实体仍在该角色手牌且手牌摘要未变；任何绑定
        不符都返回None，由调用方失败关闭。"""

        if (
            runtime.discard_phase_window_id is None
            or runtime.discard_phase_snapshot_digest is None
        ):
            return None
        return _resolve_hand_choice_handle(
            self._session_id,
            self._session_secret,
            state,
            runtime.discard_phase_window_id,
            actor_id,
            "hand",
            runtime.discard_phase_snapshot_digest,
            runtime.discard_phase_handles,
            handle,
        )

    def apply_select_discard_card(
        self,
        state: GameState,
        context: ActionContext,
        action: LegalAction,
    ) -> GameState:
        """弃牌阶段选择动作：把一张待弃手牌加入本次批量选择的待选集合。

        选择过程不移动牌、不产生任何正式弃牌／失牌事件；只有提交动作
        （discard_phase_submit）确认后，全部选中牌才作为同一次弃牌阶段
        操作统一离开手牌。选择动作只接受绑定当前选择窗口的隐藏句柄，
        句柄解析失败、重复选择、非当前角色、过期窗口均失败关闭。"""

        runtime = self._runtime
        if runtime.phase is not ProductionPhase.DISCARD:
            raise InvalidActionError("只有弃牌阶段可以选择待弃手牌")
        if context.actor_id != runtime.current_player_id:
            raise InvalidActionError("只有当前回合角色可以选择待弃手牌")
        player = state.players_by_id[context.actor_id]
        if not player.alive:
            raise InvalidActionError("已死亡角色不能继续选择待弃手牌")
        if action.payload.get("operation") != "select_discard_card":
            raise InvalidActionError("选择动作负载无效")
        if action.payload.get("window_id") != runtime.discard_phase_window_id:
            raise InvalidActionError("选择动作不属于当前弃牌选择窗口")
        instance_id = self._resolve_discard_handle(
            state, runtime, context.actor_id, action.payload.get("handle")
        )
        if instance_id is None:
            raise InvalidActionError(
                "待弃手牌句柄无效：伪造、跨窗口、跨会话或手牌已变化"
            )
        if instance_id in runtime.discard_phase_selected_ids:
            raise InvalidActionError("同一张手牌不能重复加入待弃集合")
        next_runtime = replace(
            runtime,
            discard_phase_selected_ids=(
                *runtime.discard_phase_selected_ids,
                instance_id,
            ),
        )
        self._commit_runtime(runtime, next_runtime)
        return state

    def apply_unselect_discard_card(
        self,
        state: GameState,
        context: ActionContext,
        action: LegalAction,
    ) -> GameState:
        """弃牌阶段取消选择动作：把一张已选待弃手牌移出待选集合。"""

        runtime = self._runtime
        if runtime.phase is not ProductionPhase.DISCARD:
            raise InvalidActionError("只有弃牌阶段可以取消选择待弃手牌")
        if context.actor_id != runtime.current_player_id:
            raise InvalidActionError("只有当前回合角色可以取消选择待弃手牌")
        if action.payload.get("operation") != "unselect_discard_card":
            raise InvalidActionError("取消选择动作负载无效")
        if action.payload.get("window_id") != runtime.discard_phase_window_id:
            raise InvalidActionError("取消选择动作不属于当前弃牌选择窗口")
        instance_id = self._resolve_discard_handle(
            state, runtime, context.actor_id, action.payload.get("handle")
        )
        if instance_id is None:
            raise InvalidActionError(
                "待弃手牌句柄无效：伪造、跨窗口、跨会话或手牌已变化"
            )
        if instance_id not in runtime.discard_phase_selected_ids:
            raise InvalidActionError("只能取消选择已在待弃集合中的手牌")
        next_runtime = replace(
            runtime,
            discard_phase_selected_ids=tuple(
                instance
                for instance in runtime.discard_phase_selected_ids
                if instance != instance_id
            ),
        )
        self._commit_runtime(runtime, next_runtime)
        return state

    def apply_discard_phase_submit(
        self,
        state: GameState,
        context: ActionContext,
        action: LegalAction,
    ) -> GameState:
        """弃牌阶段提交动作：把本次批量选择的全部手牌一次性弃置。

        提交是唯一产生正式弃牌状态转换的动作：权威状态实时重算手牌数、
        手牌上限与excess，验证待选集合数量恰好等于excess、无重复、全部
        是该角色当前真实手牌（装备区／判定区／其他角色牌不可能进入待选
        集合），随后以一次原子move_cards把全部选中牌移入弃牌堆并统一
        登记事件。选择窗口打开后HP、手牌或上限发生变化的旧提交失败关闭；
        任意一张非法则一张都不能移动。"""

        runtime = self._runtime
        if runtime.phase is not ProductionPhase.DISCARD:
            raise InvalidActionError("只有弃牌阶段可以提交批量弃置")
        if context.actor_id != runtime.current_player_id:
            raise InvalidActionError("只有当前回合角色可以提交批量弃置")
        player = state.players_by_id[context.actor_id]
        if not player.alive:
            raise InvalidActionError("已死亡角色不能提交批量弃置")
        if action.payload.get("operation") != "discard_phase_submit":
            raise InvalidActionError("提交动作负载无效")
        if action.payload.get("window_id") != runtime.discard_phase_window_id:
            raise InvalidActionError("提交动作不属于当前弃牌选择窗口")
        if (
            runtime.discard_phase_snapshot_digest is None
            or sha256_value(
                tuple(state.card_ids_in(ZoneRef.hand(context.actor_id)))
            ) != runtime.discard_phase_snapshot_digest
        ):
            raise InvalidActionError(
                "弃牌选择窗口打开后手牌已变化，旧提交失败关闭"
            )
        hand_ids = state.card_ids_in(ZoneRef.hand(context.actor_id))
        hand_limit = hand_limit_of(state, context.actor_id)
        excess = len(hand_ids) - hand_limit
        if excess <= 0:
            raise InvalidActionError("手牌数未超过手牌上限，不需要弃牌")
        selected_ids = tuple(runtime.discard_phase_selected_ids)
        if len(selected_ids) != excess:
            raise InvalidActionError(
                f"批量弃置必须恰好提交{excess}张当前手牌，"
                f"实际选择{len(selected_ids)}张"
            )
        if len(set(selected_ids)) != len(selected_ids):
            raise InvalidActionError("批量弃置不允许重复选择同一实体")
        hand_set = set(hand_ids)
        for instance_id in selected_ids:
            if instance_id not in hand_set:
                raise InvalidActionError(
                    "批量弃置只能包含该角色当前真实手牌，"
                    "不允许装备区、判定区或其他角色牌"
                )
        # 批次身份使用公开稳定的选择窗口ID（turn＋player限定，同一回合唯一）；
        # 不用会话绑定的action_id作事件身份，避免跨记录公共视图依赖会话密钥
        # 而不可区分（见重洗顺序脱敏测试）。提交动作本身在回放decisions中
        # 权威记录，作为该批次的root action。
        batch_window_id = runtime.discard_phase_window_id
        next_state = state.move_cards(
            {instance_id: DISCARD_PILE for instance_id in selected_ids}
        )
        events: list[GameEvent] = []
        for instance_id in selected_ids:
            card_key = _card_key(next_state, instance_id)
            move_event = GameEvent(
                event_type=EventType.CARD_MOVED,
                card_instance_id=instance_id,
                card_key=card_key,
                card_user=context.actor_id,
                payload={
                    "source": _zone_payload(
                        ZoneRef.hand(context.actor_id)
                    ),
                    "destination": _zone_payload(DISCARD_PILE),
                    "reason": "discard_phase",
                    "window_id": batch_window_id,
                },
            )
            lost_event = GameEvent(
                event_type=EventType.CARD_LOST,
                card_instance_id=instance_id,
                card_key=card_key,
                target_ids=(context.actor_id,),
                payload={
                    "reason": "discard_phase",
                    "source_zone": _zone_id(
                        ZoneRef.hand(context.actor_id)
                    ),
                    "window_id": batch_window_id,
                },
            )
            discarded_event = GameEvent(
                event_type=EventType.CARD_DISCARDED,
                card_instance_id=instance_id,
                card_key=card_key,
                card_user=context.actor_id,
                target_ids=(context.actor_id,),
                payload={
                    "reason": "discard_phase",
                    "source_zone": _zone_id(
                        ZoneRef.hand(context.actor_id)
                    ),
                    "window_id": batch_window_id,
                },
            )
            events.extend((move_event, lost_event, discarded_event))
        self._events.extend(tuple(events))
        next_runtime = replace(
            runtime,
            phase=ProductionPhase.END,
            discard_phase_window_id=None,
            discard_phase_selected_ids=(),
            discard_phase_handles=MappingProxyType({}),
            discard_phase_snapshot_digest=None,
            pending_weapon_choice=None,
        )
        self._commit_runtime(runtime, next_runtime)
        return next_state

    def _apply_end_turn(
        self,
        state: GameState,
        context: ActionContext,
        action: LegalAction,
    ) -> GameState:
        del action
        runtime = self._runtime
        if runtime.phase is not ProductionPhase.END:
            raise InvalidActionError("只有结束阶段可以结束回合")
        if context.actor_id != runtime.current_player_id:
            raise InvalidActionError("只有当前回合角色可以结束回合")
        next_player = self.opponent_of(runtime.current_player_id)
        next_state = state
        next_runtime = replace(
            runtime,
            current_player_id=next_player,
            turn_number=runtime.turn_number + 1,
            phase=ProductionPhase.PREPARE,
            slash_used_counts=MappingProxyType(
                {**runtime.slash_used_counts, next_player: 0}
            ),
            wine_buff_owner_id=None,
            wine_buff_used_this_play_phase=False,
            pending_slash=None,
            pending_trick=None,
            trick_effect_active=False,
            trick_consecutive_passes=0,
            trick_response_order=(),
            trick_response_index=0,
            trick_decision_count=0,
            trick_direct_response_to=None,
            pending_dying_id=None,
            rescue_order=(),
            rescue_index=0,
            rescue_decision_count=0,
            response_window_id=None,
            response_window_order=(),
            response_window_source_sequence=None,
            pending_group_trick=None,
            group_response_handles=MappingProxyType({}),
            group_response_snapshot_digest=None,
            pending_wugu=None,
            pending_chain=None,
            # 本回合判定与阶段跳过状态在回合结束时清理；entry_index跨回合保留
            processed_judgment_instance_ids=(),
            pending_judgment=None,
            skipped_phases=MappingProxyType({}),
            phase_skip_reasons=MappingProxyType({}),
            defer_damage_card_finish=False,
            bagua_attempted=False,
            discard_phase_window_id=None,
            discard_phase_selected_ids=(),
            discard_phase_handles=MappingProxyType({}),
            discard_phase_snapshot_digest=None,
            pending_weapon_choice=None,
        )
        self._commit_runtime(runtime, next_runtime)
        return next_state

    # ------------------------------------------------------------------
    # 实体牌移动与摸牌事务（真实 move_card / move_cards 原子移动）
    # ------------------------------------------------------------------

    def _move_to_processing(
        self,
        state: GameState,
        instance_id: str,
        card_user: str,
        reason: str,
    ) -> tuple[GameState, GameEvent]:
        source = state.location_of(instance_id)
        if source != ZoneRef.hand(card_user):
            raise ProductionBatchError(
                "只能处理当前行动角色真实手牌中的实体牌"
            )
        next_state = state.move_card(instance_id, PROCESSING_ZONE)
        return next_state, GameEvent(
            event_type=EventType.CARD_MOVED,
            card_instance_id=instance_id,
            card_key=_card_key(state, instance_id),
            card_user=card_user,
            payload={
                "source": _zone_payload(source),
                "destination": _zone_payload(PROCESSING_ZONE),
                "reason": reason,
            },
        )

    def _finish_processing(
        self,
        state: GameState,
        instance_id: str,
        reason: str,
        *,
        extra: Mapping[str, object] | None = None,
    ) -> tuple[GameState, GameEvent]:
        source = state.location_of(instance_id)
        if source != PROCESSING_ZONE:
            raise ProductionBatchError("只有处理区中的实体牌可以完成结算")
        next_state = state.move_card(instance_id, DISCARD_PILE)
        payload: dict[str, object] = {
            "source": _zone_payload(source),
            "destination": _zone_payload(DISCARD_PILE),
            "reason": reason,
        }
        if extra is not None:
            payload.update(extra)
        return next_state, GameEvent(
            event_type=EventType.CARD_MOVED,
            card_instance_id=instance_id,
            card_key=_card_key(state, instance_id),
            payload=payload,
        )

    def _consume_immediately(
        self,
        state: GameState,
        instance_id: str,
        card_user: str,
        reason: str,
    ) -> tuple[GameState, tuple[GameEvent, GameEvent]]:
        processing_state, enter_event = self._move_to_processing(
            state, instance_id, card_user, f"{reason}:enter_processing"
        )
        finished_state, leave_event = self._finish_processing(
            processing_state, instance_id, f"{reason}:leave_processing"
        )
        return finished_state, (enter_event, leave_event)

    def _draw_cards(
        self,
        state: GameState,
        player_id: str,
        count: int,
        *,
        reason: str = "draw_phase",
    ) -> tuple[GameState, tuple[GameEvent, ...]]:
        _assert_deck_available(state, count, f"摸{count}张牌")
        next_state = state
        events: list[GameEvent] = []
        for _ in range(count):
            if not next_state.card_ids_in(DRAW_PILE):
                discard_ids = list(next_state.card_ids_in(DISCARD_PILE))
                self._rng.shuffle(discard_ids)
                sources = {
                    instance_id: next_state.location_of(instance_id)
                    for instance_id in discard_ids
                }
                next_state = next_state.move_cards(
                    {instance_id: DRAW_PILE for instance_id in discard_ids}
                )
                events.extend(
                    GameEvent(
                        event_type=EventType.CARD_MOVED,
                        card_instance_id=instance_id,
                        card_key=_card_key(next_state, instance_id),
                        payload={
                            "source": _zone_payload(sources[instance_id]),
                            "destination": _zone_payload(DRAW_PILE),
                            "reason": "reshuffle",
                        },
                    )
                    for instance_id in discard_ids
                )
            instance_id = next_state.card_ids_in(DRAW_PILE)[0]
            source = next_state.location_of(instance_id)
            next_state = next_state.move_card(
                instance_id, ZoneRef.hand(player_id)
            )
            events.extend(
                (
                    GameEvent(
                        event_type=EventType.CARD_MOVED,
                        card_instance_id=instance_id,
                        card_key=_card_key(next_state, instance_id),
                        payload={
                            "source": _zone_payload(source),
                            "destination": _zone_payload(
                                ZoneRef.hand(player_id)
                            ),
                            "reason": reason,
                        },
                    ),
                    GameEvent(
                        event_type=EventType.CARD_GAINED,
                        card_instance_id=instance_id,
                        card_key=_card_key(next_state, instance_id),
                        target_ids=(player_id,),
                        payload={"reason": reason},
                    ),
                )
            )
        return next_state, tuple(events)


__all__ = [
    "BATCH_PHASES",
    "PRODUCTION_BASIC_CARDS_MODE",
    "BatchActionIdController",
    "BatchPhaseEntry",
    "BatchReferenceController",
    "ProductionBatchDeckExhaustedError",
    "ProductionBatchError",
    "ProductionBatchFinishedError",
    "ProductionBatchResult",
    "ProductionBatchSafetyLimitError",
    "ProductionBasicCardBatch",
    "ProductionPhase",
    "ScriptedBatchController",
]
