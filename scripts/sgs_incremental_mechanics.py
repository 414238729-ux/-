"""三国杀跨武将增量机制的轻量、可组合状态接口。

本模块只保存用户已确认的通用边界：伤害触发计数、铁索伤害来源、武将
牌旁实体特殊牌权限、当前卡名计数、已生成牌生命周期，以及使用牌生命
周期。它不会补全具体武将技能，也不替代完整的卡牌合法性与伤害结算引擎。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Callable, Iterable, Sequence

from ._validation import ensure_int_at_least
from .sgs_card_rules import DamageType


def _nonempty(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label}必须是非空字符串")
    return value.strip()


def _coerce_enum(value: object, enum_type: type[Enum], label: str) -> Enum:
    if isinstance(value, enum_type):
        return value
    try:
        return enum_type(value)
    except (TypeError, ValueError) as exc:
        choices = "、".join(member.value for member in enum_type)
        raise ValueError(f"{label}只能是：{choices}") from exc


def _bool(value: object, label: str) -> bool:
    if not isinstance(value, bool):
        raise TypeError(f"{label}必须是布尔值")
    return value


class DamageTriggerBasis(Enum):
    """伤害技能按实际点数或按独立事件计数。"""

    PER_DAMAGE_POINT = "每点伤害"
    PER_DAMAGE_EVENT = "每个伤害事件"


_PER_POINT_TEXTS = ("每造成1点伤害", "每受到1点伤害")
_PER_EVENT_TEXTS = (
    "造成伤害后",
    "受到伤害后",
    "当你造成伤害时",
    "当你受到伤害时",
)


def damage_trigger_basis_from_text(skill_text: str) -> DamageTriggerBasis:
    """从已确认的两类标准措辞识别伤害触发计数口径。"""

    text = _nonempty(skill_text, "伤害技能文字")
    if any(marker in text for marker in _PER_POINT_TEXTS):
        return DamageTriggerBasis.PER_DAMAGE_POINT
    if any(marker in text for marker in _PER_EVENT_TEXTS):
        return DamageTriggerBasis.PER_DAMAGE_EVENT
    raise ValueError("技能文字未包含可识别的每点伤害或每个伤害事件措辞")


def damage_trigger_count(
    actual_damage: int,
    basis: DamageTriggerBasis | str,
) -> int:
    """按最终实际伤害返回触发次数；0点伤害不产生伤害触发。"""

    damage = ensure_int_at_least(actual_damage, "最终实际伤害", 0)
    resolved = _coerce_enum(basis, DamageTriggerBasis, "伤害触发口径")
    if damage == 0:
        return 0
    if resolved is DamageTriggerBasis.PER_DAMAGE_POINT:
        return damage
    return 1


@dataclass(frozen=True)
class OriginatingPhysicalCard:
    """造成原始伤害的实体牌归属快照，可表示多实体转化牌。"""

    card_name: str
    physical_card_ids: tuple[str, ...]
    owner_id: str | None

    def __post_init__(self) -> None:
        object.__setattr__(self, "card_name", _nonempty(self.card_name, "原始伤害牌名"))
        if not isinstance(self.physical_card_ids, tuple) or not self.physical_card_ids:
            raise ValueError("原始伤害实体牌标识必须是非空元组")
        normalized = tuple(
            _nonempty(card_id, "实体牌标识") for card_id in self.physical_card_ids
        )
        if len(set(normalized)) != len(normalized):
            raise ValueError("原始伤害实体牌标识不能重复")
        object.__setattr__(self, "physical_card_ids", normalized)
        if self.owner_id is not None:
            object.__setattr__(self, "owner_id", _nonempty(self.owner_id, "实体牌归属角色"))


@dataclass(frozen=True)
class DamageProvenance:
    """伤害来源、属性及原实体牌归属。"""

    source_id: str | None
    damage_type: DamageType | str
    originating_card: OriginatingPhysicalCard | None = None

    def __post_init__(self) -> None:
        if self.source_id is not None:
            object.__setattr__(self, "source_id", _nonempty(self.source_id, "伤害来源"))
        object.__setattr__(
            self,
            "damage_type",
            _coerce_enum(self.damage_type, DamageType, "伤害属性"),
        )
        if self.originating_card is not None and not isinstance(
            self.originating_card,
            OriginatingPhysicalCard,
        ):
            raise TypeError("原始伤害牌必须是 OriginatingPhysicalCard 或 None")


@dataclass(frozen=True)
class AttributedDamageEvent:
    """带完整来源元数据的一次独立伤害事件。"""

    event_id: int
    target_id: str
    actual_damage: int
    provenance: DamageProvenance
    parent_event_id: int | None = None
    is_chain_propagation: bool = False

    def __post_init__(self) -> None:
        ensure_int_at_least(self.event_id, "伤害事件编号", 1)
        object.__setattr__(self, "target_id", _nonempty(self.target_id, "受伤角色"))
        ensure_int_at_least(self.actual_damage, "最终实际伤害", 0)
        if not isinstance(self.provenance, DamageProvenance):
            raise TypeError("伤害来源信息必须是 DamageProvenance")
        if self.parent_event_id is not None:
            ensure_int_at_least(self.parent_event_id, "父伤害事件编号", 1)
            if self.parent_event_id == self.event_id:
                raise ValueError("伤害事件不能把自己作为父事件")
        _bool(self.is_chain_propagation, "是否为铁索传导伤害")

    @property
    def trigger_is_independent_damage_event(self) -> bool:
        return True


def derive_chain_damage_events(
    original_event: AttributedDamageEvent,
    recipient_damages: Iterable[tuple[str, int]],
    *,
    first_event_id: int | None = None,
) -> tuple[AttributedDamageEvent, ...]:
    """为各传导角色建立独立事件，并原样继承来源、属性和实体牌归属。

    ``recipient_damages`` 保存每名角色自身防具、减伤等处理后的最终伤害，
    因而伤害点数可以不同；来源元数据不会改写为【铁索连环】、横置状态或
    第一个受伤角色。
    """

    if not isinstance(original_event, AttributedDamageEvent):
        raise TypeError("原始伤害必须是 AttributedDamageEvent")
    if original_event.actual_damage <= 0:
        raise ValueError("原始伤害未实际造成伤害，不能产生铁索传导事件")
    if original_event.provenance.damage_type not in {
        DamageType.FIRE,
        DamageType.THUNDER,
    }:
        raise ValueError("只有火属性或雷属性伤害可以建立铁索传导事件")
    if recipient_damages is None:
        raise TypeError("传导目标伤害列表不能是 None")
    try:
        recipients = tuple(recipient_damages)
    except TypeError as exc:
        raise TypeError("传导目标伤害必须是可迭代对象") from exc
    start = original_event.event_id + 1 if first_event_id is None else first_event_id
    ensure_int_at_least(start, "首个传导伤害事件编号", 1)
    if start <= original_event.event_id:
        raise ValueError("传导伤害事件编号必须晚于原始伤害事件")

    result: list[AttributedDamageEvent] = []
    for offset, item in enumerate(recipients):
        if not isinstance(item, tuple) or len(item) != 2:
            raise TypeError("每个传导目标必须表示为（角色标识，最终伤害）二元组")
        target, actual_damage = item
        result.append(
            AttributedDamageEvent(
                event_id=start + offset,
                parent_event_id=original_event.event_id,
                target_id=_nonempty(target, "传导受伤角色"),
                actual_damage=ensure_int_at_least(
                    actual_damage,
                    "传导最终实际伤害",
                    0,
                ),
                provenance=original_event.provenance,
                is_chain_propagation=True,
            )
        )
    return tuple(result)


class SpecialCardVisibility(Enum):
    PUBLIC = "公开"
    FACE_DOWN = "扣置或背面朝上"
    HIDDEN = "隐藏"
    OWNER_ONLY = "仅指定角色可见"


class SpecialCardAction(Enum):
    USE = "使用"
    RESPOND = "打出或响应"
    ZHANGBA_MATERIAL = "丈八蛇矛材料"
    DISCARD_HAND_COST = "弃置手牌成本"
    GIVE_HAND_COST = "交给手牌成本"
    SHOW_HAND_COST = "展示手牌成本"
    EXCHANGE_HAND_COST = "交换手牌成本"
    COUNT_AS_HAND = "计入手牌数"


@dataclass(frozen=True)
class GeneralSidePhysicalCard:
    """武将牌旁的实体特殊牌；没有隐藏文字时默认公开。"""

    card_id: str
    card_name: str
    category: str
    visibility: SpecialCardVisibility | str = SpecialCardVisibility.PUBLIC
    can_act_as_hand_for_use_or_response: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "card_id", _nonempty(self.card_id, "特殊牌标识"))
        object.__setattr__(self, "card_name", _nonempty(self.card_name, "特殊牌牌名"))
        object.__setattr__(self, "category", _nonempty(self.category, "特殊牌类别"))
        object.__setattr__(
            self,
            "visibility",
            _coerce_enum(self.visibility, SpecialCardVisibility, "特殊牌可见性"),
        )
        _bool(
            self.can_act_as_hand_for_use_or_response,
            "特殊牌能否当作手牌使用或打出",
        )

    @property
    def is_public(self) -> bool:
        return self.visibility is SpecialCardVisibility.PUBLIC

    @property
    def public_face_information(self) -> tuple[str, ...]:
        if not self.is_public:
            return ()
        return ("牌名", "花色", "点数", "类别", "其他正常牌面信息")


@dataclass(frozen=True)
class CardRestrictions:
    """使用或响应时需要叠加检查的禁止条件。"""

    hand_use_forbidden: bool = False
    hand_response_forbidden: bool = False
    all_card_use_forbidden: bool = False
    all_card_response_forbidden: bool = False
    current_card_unrespondable: bool = False
    forbidden_card_names: frozenset[str] = frozenset()
    forbidden_categories: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        for name in (
            "hand_use_forbidden",
            "hand_response_forbidden",
            "all_card_use_forbidden",
            "all_card_response_forbidden",
            "current_card_unrespondable",
        ):
            _bool(getattr(self, name), name)
        if not isinstance(self.forbidden_card_names, frozenset):
            raise TypeError("禁止牌名必须是 frozenset")
        if not isinstance(self.forbidden_categories, frozenset):
            raise TypeError("禁止牌类别必须是 frozenset")
        object.__setattr__(
            self,
            "forbidden_card_names",
            frozenset(_nonempty(item, "禁止牌名") for item in self.forbidden_card_names),
        )
        object.__setattr__(
            self,
            "forbidden_categories",
            frozenset(_nonempty(item, "禁止牌类别") for item in self.forbidden_categories),
        )


@dataclass(frozen=True)
class SpecialCardPermission:
    allowed: bool
    reason: str
    counts_as_normal_hand_card: bool = False


_HAND_ONLY_COST_ACTIONS = frozenset(
    {
        SpecialCardAction.DISCARD_HAND_COST,
        SpecialCardAction.GIVE_HAND_COST,
        SpecialCardAction.SHOW_HAND_COST,
        SpecialCardAction.EXCHANGE_HAND_COST,
        SpecialCardAction.COUNT_AS_HAND,
    }
)


def check_general_side_card_permission(
    card: GeneralSidePhysicalCard,
    action: SpecialCardAction | str,
    *,
    restrictions: CardRestrictions | None = None,
    effective_card_name: str | None = None,
    effective_category: str | None = None,
    zhangba_output_action: SpecialCardAction | str = SpecialCardAction.USE,
) -> SpecialCardPermission:
    """检查特殊牌作为牌使用、响应或丈八材料的通用权限。

    “只禁止手牌”不会封锁特殊牌；全局禁用、不可响应、牌名及类别限制
    仍然生效。丈八材料按最终转化出的【杀】和实际使用/响应动作检查。
    """

    if not isinstance(card, GeneralSidePhysicalCard):
        raise TypeError("武将牌旁特殊牌必须是 GeneralSidePhysicalCard")
    resolved_action = _coerce_enum(action, SpecialCardAction, "特殊牌动作")
    limits = restrictions or CardRestrictions()
    if not isinstance(limits, CardRestrictions):
        raise TypeError("卡牌禁止条件必须是 CardRestrictions 或 None")

    if resolved_action in _HAND_ONLY_COST_ACTIONS:
        return SpecialCardPermission(
            False,
            "当作手牌使用或打出不等于普通手牌，不能支付该手牌专属成本",
        )
    if not card.can_act_as_hand_for_use_or_response:
        return SpecialCardPermission(False, "具体技能没有授予当作手牌使用或打出的权限")

    output_action = resolved_action
    name = card.card_name if effective_card_name is None else _nonempty(
        effective_card_name,
        "实际使用或打出的牌名",
    )
    category = card.category if effective_category is None else _nonempty(
        effective_category,
        "实际使用或打出的牌类别",
    )
    if resolved_action is SpecialCardAction.ZHANGBA_MATERIAL:
        output_action = _coerce_enum(
            zhangba_output_action,
            SpecialCardAction,
            "丈八转化后的动作",
        )
        if output_action not in {SpecialCardAction.USE, SpecialCardAction.RESPOND}:
            raise ValueError("丈八转化后的动作只能是使用或打出响应")
        name = "杀"
        category = "基本牌"

    if name in limits.forbidden_card_names:
        return SpecialCardPermission(False, f"当前禁止使用或打出【{name}】")
    if category in limits.forbidden_categories:
        return SpecialCardPermission(False, f"当前禁止使用或打出{category}")
    if output_action is SpecialCardAction.USE:
        if limits.all_card_use_forbidden:
            return SpecialCardPermission(False, "当前不能使用牌，特殊区牌不能绕过")
        # hand_use_forbidden 刻意不拦截：特殊牌并非普通手牌。
        return SpecialCardPermission(True, "特殊牌不是普通手牌，且其他使用条件均允许")
    if output_action is SpecialCardAction.RESPOND:
        if limits.all_card_response_forbidden:
            return SpecialCardPermission(False, "当前不能响应，特殊区牌不能绕过")
        if limits.current_card_unrespondable:
            return SpecialCardPermission(False, "当前牌不可被响应，特殊区牌同样不能响应")
        # hand_response_forbidden 刻意不拦截。
        return SpecialCardPermission(True, "特殊牌不是普通手牌，且当前存在合法响应权限")
    raise ValueError("该特殊牌动作不属于可使用、打出或转化的合法范围")


class CardEffectOutcome(Enum):
    RESOLVED = "牌效正常结算"
    CANCELLED_BY_NULLIFICATION = "被无懈可击抵消"
    INVALIDATED = "被技能或规则真正无效"


@dataclass(frozen=True)
class CardUseLifecycle:
    """严格分离使用事件、打出事件、无懈抵消、真正无效和完成节点。

    ``card_responded`` 是旧字段名，仅为兼容保留；它在本类中表示明确的
    ``card_played`` 事件，不能用来表示所有响应窗口。
    """

    card_name: str
    card_used: bool
    card_responded: bool
    effect_cancelled_by_nullification: bool
    card_or_effect_invalidated: bool
    card_use_completed: bool
    effect_resolved: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "card_name", _nonempty(self.card_name, "卡牌名称"))
        for name in (
            "card_used",
            "card_responded",
            "effect_cancelled_by_nullification",
            "card_or_effect_invalidated",
            "card_use_completed",
            "effect_resolved",
        ):
            _bool(getattr(self, name), name)
        if self.card_used and self.card_responded:
            raise ValueError("同一动作不能同时标记为使用牌和普通打出牌")
        if (
            self.effect_cancelled_by_nullification
            and self.card_or_effect_invalidated
        ):
            raise ValueError("无懈抵消和真正无效不能合并为同一状态")
        if self.effect_resolved and not self.card_use_completed:
            raise ValueError("牌效已经结算时必须存在使用结算完成节点")

    @property
    def card_played(self) -> bool:
        """返回明确的打出牌事件；旧字段 ``card_responded`` 的语义别名。"""

        return self.card_responded


def resolve_card_use_lifecycle(
    card_name: str,
    outcome: CardEffectOutcome | str = CardEffectOutcome.RESOLVED,
) -> CardUseLifecycle:
    """记录一次合法使用牌；三类结果仍全部保留 ``card_used``。"""

    name = _nonempty(card_name, "卡牌名称")
    resolved = _coerce_enum(outcome, CardEffectOutcome, "牌效果结果")
    if resolved is CardEffectOutcome.RESOLVED:
        return CardUseLifecycle(name, True, False, False, False, True, True)
    if resolved is CardEffectOutcome.CANCELLED_BY_NULLIFICATION:
        return CardUseLifecycle(name, True, False, True, False, True, False)
    return CardUseLifecycle(name, True, False, False, True, False, False)


def record_card_response(card_name: str) -> CardUseLifecycle:
    """记录已明确属于“打出”的普通响应。

    【闪】的动作由响应对象决定，必须改用
    :func:`scripts.sgs_jink_response.resolve_jink_response`；本函数拒绝在
    缺少响应对象时把【闪】统一记录成打出。
    """

    name = _nonempty(card_name, "响应牌名称")
    if name == "闪":
        raise ValueError("【闪】必须按响应对象区分使用或打出，请调用 resolve_jink_response")

    return CardUseLifecycle(
        card_name=name,
        card_used=False,
        card_responded=True,
        effect_cancelled_by_nullification=False,
        card_or_effect_invalidated=False,
        card_use_completed=False,
        effect_resolved=False,
    )


# ---------------------------------------------------------------------------
# 当前卡名、距离文本、已生成牌与明确伤害来源


_CURRENT_SLASH_NAMES = frozenset({"杀", "火杀", "雷杀"})


@dataclass(frozen=True)
class PhysicalCardIdentity:
    """一张实体牌在当前时点的名称、转化和区域快照。

    ``current_card_name`` 表示持续效果已经真正改写后的当前卡名；
    ``use_as_card_name`` 只表示某次使用或打出时的临时身份。两者必须分开，
    以免把丈八材料或临时视为【杀】的牌计入“手牌中的【杀】”。
    """

    card_id: str
    original_card_name: str
    current_card_name: str
    use_as_card_name: str | None = None
    physical_zone: str = "手牌区"
    counts_as_hand_card: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "card_id", _nonempty(self.card_id, "实体牌编号"))
        object.__setattr__(
            self,
            "original_card_name",
            _nonempty(self.original_card_name, "原始牌名"),
        )
        object.__setattr__(
            self,
            "current_card_name",
            _nonempty(self.current_card_name, "当前卡名"),
        )
        if self.use_as_card_name is not None:
            object.__setattr__(
                self,
                "use_as_card_name",
                _nonempty(self.use_as_card_name, "临时视为牌名"),
            )
        object.__setattr__(self, "physical_zone", _nonempty(self.physical_zone, "实体区域"))
        _bool(self.counts_as_hand_card, "是否计入手牌")


def counts_as_current_hand_slash(card: PhysicalCardIdentity) -> bool:
    """仅按当前卡名和当前是否计入手牌判断是否属于“手牌中的【杀】”。"""

    if not isinstance(card, PhysicalCardIdentity):
        raise TypeError("当前卡名计数必须使用 PhysicalCardIdentity")
    return card.counts_as_hand_card and card.current_card_name in _CURRENT_SLASH_NAMES


def count_current_hand_slashes(cards: Iterable[PhysicalCardIdentity]) -> int:
    """统计普通【杀】、火【杀】、雷【杀】及持续改名后的【杀】。"""

    if cards is None:
        raise TypeError("待统计卡牌不能是 None")
    try:
        prepared = tuple(cards)
    except TypeError as exc:
        raise TypeError("待统计卡牌必须是可迭代对象") from exc
    if not all(isinstance(card, PhysicalCardIdentity) for card in prepared):
        raise TypeError("待统计卡牌都必须是 PhysicalCardIdentity")
    return sum(counts_as_current_hand_slash(card) for card in prepared)


def actual_distance_within_limit(actual_distance: int, limit: int) -> bool:
    """按“距离不大于X”判断；距离0（自己）自然满足距离1以内。"""

    distance = ensure_int_at_least(actual_distance, "实际距离", 0)
    maximum = ensure_int_at_least(limit, "距离上限", 0)
    return distance <= maximum


@dataclass(frozen=True)
class GeneratedCardContinuation:
    """来源死亡后，一张已经合法生成的牌是否继续结算。"""

    generated_card_started: bool
    continues_after_source_death: bool
    next_step_can_be_performed: bool
    resolution_ends_now: bool
    reason: str


def resolve_generated_card_after_source_death(
    *,
    generated_legally: bool,
    source_alive: bool,
    game_ended: bool = False,
    rule_requires_source_alive: bool = False,
    targets_still_legal: bool = True,
    next_step_requires_source_action: bool = False,
) -> GeneratedCardContinuation:
    """处理“牌已生成后来源死亡”的通用边界。

    已经合法生成的牌不会仅因来源死亡而倒带取消；但游戏已经结束、具体
    规则要求来源存活、目标重检失败，或下一步必须由死亡来源执行时，均
    会在相应节点停止。
    """

    for value, label in (
        (generated_legally, "是否已合法生成"),
        (source_alive, "来源是否存活"),
        (game_ended, "游戏是否结束"),
        (rule_requires_source_alive, "规则是否要求来源存活"),
        (targets_still_legal, "目标是否仍合法"),
        (next_step_requires_source_action, "下一步是否要求来源行动"),
    ):
        _bool(value, label)
    if not generated_legally:
        return GeneratedCardContinuation(False, False, False, True, "牌未合法生成")
    if game_ended:
        return GeneratedCardContinuation(True, False, False, True, "游戏已经结束")
    if not targets_still_legal:
        return GeneratedCardContinuation(True, False, False, True, "重检后目标不再合法")
    if not source_alive and rule_requires_source_alive:
        return GeneratedCardContinuation(True, False, False, True, "具体规则要求来源存活")
    if not source_alive and next_step_requires_source_action:
        return GeneratedCardContinuation(True, True, False, True, "已生成牌继续到当前节点，但死亡来源不能执行下一步")
    return GeneratedCardContinuation(
        True,
        not source_alive,
        True,
        False,
        "已合法生成的牌按正常流程继续结算",
    )


@dataclass(frozen=True)
class ExplicitDamageSourceResult:
    """技能明确写成“A对B造成伤害”时的来源与身份奖惩归属。"""

    source_id: str
    skill_owner_id: str
    target_id: str
    kill_reward_or_penalty_owner_id: str


def resolve_explicit_damage_source(
    *,
    actor_id: str,
    skill_owner_id: str,
    target_id: str,
) -> ExplicitDamageSourceResult:
    """返回明确执行伤害的角色；技能发动者不会自动覆盖伤害来源。"""

    actor = _nonempty(actor_id, "伤害执行者")
    owner = _nonempty(skill_owner_id, "技能发动者")
    target = _nonempty(target_id, "伤害目标")
    return ExplicitDamageSourceResult(actor, owner, target, actor)


# ---------------------------------------------------------------------------
# “获得牌时”队列与牌使用者／伤害来源资格


@dataclass(frozen=True)
class PendingGainCard:
    """尚未实际进入任何角色区域的一张待获得实体牌。"""

    card_id: str
    card_name: str
    suit: str | None = None
    intended_zone: str = "手牌区"

    def __post_init__(self) -> None:
        object.__setattr__(self, "card_id", _nonempty(self.card_id, "待获得牌编号"))
        object.__setattr__(self, "card_name", _nonempty(self.card_name, "待获得牌名"))
        if self.suit is not None:
            object.__setattr__(self, "suit", _nonempty(self.suit, "待获得牌花色"))
        object.__setattr__(self, "intended_zone", _nonempty(self.intended_zone, "预定进入区域"))


@dataclass(frozen=True)
class ActualZoneEntry:
    """获得时队列全部结束后发生的一次真实区域进入。"""

    card_id: str
    recipient_id: str
    zone: str
    redirected: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "card_id", _nonempty(self.card_id, "实际进入区域牌编号"))
        object.__setattr__(self, "recipient_id", _nonempty(self.recipient_id, "最终获得者"))
        object.__setattr__(self, "zone", _nonempty(self.zone, "实际进入区域"))
        _bool(self.redirected, "是否改由其他角色获得")


@dataclass(frozen=True)
class GainTimeObservation:
    """某项获得时效果处理时仍在待获得集合中的牌。"""

    actor_id: str
    effect_id: str
    pending_card_ids: tuple[str, ...]


class GainEventContext:
    """获得时处理器使用的短生命周期可变上下文。"""

    def __init__(self, pending_cards: Sequence[PendingGainCard]) -> None:
        self._pending = list(pending_cards)
        self._redirected: list[ActualZoneEntry] = []
        self._observations: list[GainTimeObservation] = []

    @property
    def pending_cards(self) -> tuple[PendingGainCard, ...]:
        return tuple(self._pending)

    def observe(self, actor_id: str, effect_id: str) -> None:
        """记录该效果看到的当前待获得集合，不表示牌已进入区域。"""

        actor = _nonempty(actor_id, "获得时效果角色")
        effect = _nonempty(effect_id, "获得时效果标识")
        self._observations.append(
            GainTimeObservation(actor, effect, tuple(card.card_id for card in self._pending))
        )

    def redirect_card(
        self,
        card_id: str,
        *,
        recipient_id: str,
        zone: str = "手牌区",
    ) -> PendingGainCard:
        """从待获得集合移走一张牌，并登记其最终实际进入区域。"""

        selected = _nonempty(card_id, "被改由其他角色获得的牌编号")
        for index, card in enumerate(self._pending):
            if card.card_id == selected:
                self._pending.pop(index)
                self._redirected.append(
                    ActualZoneEntry(selected, recipient_id, zone, redirected=True)
                )
                return card
        raise ValueError("指定牌已不在当前待获得集合中")

    @property
    def redirected_entries(self) -> tuple[ActualZoneEntry, ...]:
        return tuple(self._redirected)

    @property
    def observations(self) -> tuple[GainTimeObservation, ...]:
        return tuple(self._observations)


GainTimeHandler = Callable[[GainEventContext], None]


@dataclass(frozen=True)
class GainTimeEffect:
    """同一获得时窗口中由一名角色处理的一项效果。"""

    actor_id: str
    effect_id: str
    handler: GainTimeHandler

    def __post_init__(self) -> None:
        object.__setattr__(self, "actor_id", _nonempty(self.actor_id, "获得时效果角色"))
        object.__setattr__(self, "effect_id", _nonempty(self.effect_id, "获得时效果标识"))
        if not callable(self.handler):
            raise TypeError("获得时效果处理器必须可调用")


@dataclass(frozen=True)
class GainEventResolution:
    """获得时效果处理完毕后，牌才实际进入最终区域。"""

    original_recipient_id: str
    pending_cards_before: tuple[PendingGainCard, ...]
    effect_order: tuple[str, ...]
    observations: tuple[GainTimeObservation, ...]
    actual_zone_entries: tuple[ActualZoneEntry, ...]

    def entries_for(self, recipient_id: str) -> tuple[ActualZoneEntry, ...]:
        recipient = _nonempty(recipient_id, "查询最终获得者")
        return tuple(entry for entry in self.actual_zone_entries if entry.recipient_id == recipient)


def resolve_gain_time_queue(
    *,
    original_recipient_id: str,
    pending_cards: Sequence[PendingGainCard],
    actor_order: Sequence[str],
    effects: Sequence[GainTimeEffect],
) -> GainEventResolution:
    """按给定当前座次顺序处理同一“获得牌时”队列，再执行真实入区。"""

    recipient = _nonempty(original_recipient_id, "原定获得者")
    if isinstance(pending_cards, (str, bytes)) or not isinstance(pending_cards, Sequence):
        raise TypeError("待获得牌必须是序列")
    cards = tuple(pending_cards)
    if any(not isinstance(card, PendingGainCard) for card in cards):
        raise TypeError("待获得牌必须使用 PendingGainCard 表示")
    card_ids = tuple(card.card_id for card in cards)
    if len(card_ids) != len(set(card_ids)):
        raise ValueError("同一待获得集合中的实体牌编号不能重复")

    if isinstance(actor_order, (str, bytes)) or not isinstance(actor_order, Sequence):
        raise TypeError("获得时角色顺序必须是序列")
    order = tuple(_nonempty(actor, "获得时角色顺序") for actor in actor_order)
    if not order or len(order) != len(set(order)):
        raise ValueError("获得时角色顺序不能为空且不能重复")
    if recipient not in order:
        raise ValueError("原定获得者必须存在于当前获得时角色顺序中")

    if isinstance(effects, (str, bytes)) or not isinstance(effects, Sequence):
        raise TypeError("获得时效果必须是序列")
    queued = tuple(effects)
    if any(not isinstance(effect, GainTimeEffect) for effect in queued):
        raise TypeError("获得时效果必须使用 GainTimeEffect 表示")
    unknown = {effect.actor_id for effect in queued} - set(order)
    if unknown:
        raise ValueError("获得时效果角色不在当前角色顺序中：" + "、".join(sorted(unknown)))

    positions = {actor: index for index, actor in enumerate(order)}
    indexed = tuple(enumerate(queued))
    sorted_effects = tuple(
        effect for _, effect in sorted(indexed, key=lambda item: (positions[item[1].actor_id], item[0]))
    )
    context = GainEventContext(cards)
    effect_order: list[str] = []
    for effect in sorted_effects:
        context.observe(effect.actor_id, effect.effect_id)
        effect.handler(context)
        effect_order.append(effect.effect_id)

    normal_entries = tuple(
        ActualZoneEntry(card.card_id, recipient, card.intended_zone, redirected=False)
        for card in context.pending_cards
    )
    return GainEventResolution(
        original_recipient_id=recipient,
        pending_cards_before=cards,
        effect_order=tuple(effect_order),
        observations=context.observations,
        actual_zone_entries=context.redirected_entries + normal_entries,
    )


@dataclass(frozen=True)
class DamageContext:
    """把使用者、伤害来源、发动者、装备拥有者和击杀归属分开保存。"""

    card_user_id: str | None
    damage_source_id: str | None
    damage_card_name: str | None
    damage_target_id: str
    card_type: str | None = None
    skill_activator_id: str | None = None
    equipment_owner_id: str | None = None
    source_replaced: bool = False

    def __post_init__(self) -> None:
        for name, label in (
            ("card_user_id", "卡牌使用者"),
            ("damage_source_id", "伤害来源"),
            ("damage_card_name", "伤害牌名"),
            ("card_type", "伤害牌类别"),
            ("skill_activator_id", "技能发动者"),
            ("equipment_owner_id", "装备拥有者"),
        ):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, _nonempty(value, label))
        object.__setattr__(self, "damage_target_id", _nonempty(self.damage_target_id, "伤害目标"))
        _bool(self.source_replaced, "伤害来源是否被替换")

    @property
    def kill_owner_id(self) -> str | None:
        return self.damage_source_id


@dataclass(frozen=True)
class EffectRequirements:
    """一项技能或装备效果对事件角色和牌属性的资格要求。"""

    requires_card_user: bool = False
    requires_damage_source: bool = False
    requires_same_user_and_source: bool = False
    requires_card_name: str | None = None
    requires_card_type: str | None = None
    requires_equipment_owner: bool = False

    def __post_init__(self) -> None:
        for name in (
            "requires_card_user",
            "requires_damage_source",
            "requires_same_user_and_source",
            "requires_equipment_owner",
        ):
            _bool(getattr(self, name), name)
        for name, label in (
            ("requires_card_name", "要求牌名"),
            ("requires_card_type", "要求牌类别"),
        ):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, _nonempty(value, label))


def effect_requirements_satisfied(
    actor_id: str,
    context: DamageContext,
    requirements: EffectRequirements,
) -> bool:
    """按效果原文要求判断角色资格，不把来源替换误当成使用者替换。"""

    actor = _nonempty(actor_id, "待检查效果角色")
    if not isinstance(context, DamageContext):
        raise TypeError("伤害事件必须使用 DamageContext 表示")
    if not isinstance(requirements, EffectRequirements):
        raise TypeError("效果资格必须使用 EffectRequirements 表示")
    if requirements.requires_same_user_and_source and not (
        context.card_user_id == actor == context.damage_source_id
    ):
        return False
    if requirements.requires_card_user and context.card_user_id != actor:
        return False
    if requirements.requires_damage_source and context.damage_source_id != actor:
        return False
    if requirements.requires_equipment_owner and context.equipment_owner_id != actor:
        return False
    if requirements.requires_card_name is not None and (
        context.damage_card_name != requirements.requires_card_name
    ):
        return False
    if requirements.requires_card_type is not None and context.card_type != requirements.requires_card_type:
        return False
    return True
