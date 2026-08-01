"""【闪】与【八卦阵】的轻量响应事件模型。

当前规则把“响应”视为窗口，而不是统一的“打出牌”动作。响应【杀】时
使用【闪】，响应【万箭齐发】时打出【闪】；【八卦阵】判红产生的虚拟
【闪】继承当前窗口要求的动作类型，且只生成其中一种牌事件。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .sgs_general_rules import CardEventKind, CardLossEvent


class JinkResponseSource(str, Enum):
    ORDINARY_SLASH = "slash"
    FIRE_SLASH = "fire_slash"
    THUNDER_SLASH = "thunder_slash"
    ARCHERY_ATTACK = "archery_attack"


class ResponseAction(str, Enum):
    USE = "use"
    PLAY = "play"


class ResponseCardForm(str, Enum):
    PHYSICAL = "physical"
    VIRTUAL = "virtual"


_SOURCE_ALIASES: dict[str, JinkResponseSource] = {
    "杀": JinkResponseSource.ORDINARY_SLASH,
    "普通杀": JinkResponseSource.ORDINARY_SLASH,
    "slash": JinkResponseSource.ORDINARY_SLASH,
    "火杀": JinkResponseSource.FIRE_SLASH,
    "fire_slash": JinkResponseSource.FIRE_SLASH,
    "雷杀": JinkResponseSource.THUNDER_SLASH,
    "thunder_slash": JinkResponseSource.THUNDER_SLASH,
    "万箭齐发": JinkResponseSource.ARCHERY_ATTACK,
    "archery_attack": JinkResponseSource.ARCHERY_ATTACK,
}


def _coerce_source(value: JinkResponseSource | str) -> JinkResponseSource:
    if isinstance(value, JinkResponseSource):
        return value
    if not isinstance(value, str) or not value.strip():
        raise ValueError("【闪】响应对象必须是非空字符串或 JinkResponseSource")
    try:
        return _SOURCE_ALIASES[value.strip()]
    except KeyError as exc:
        raise ValueError("当前轻量模型只处理【杀】、【火杀】、【雷杀】与【万箭齐发】") from exc


def _coerce_form(value: ResponseCardForm | str) -> ResponseCardForm:
    if isinstance(value, ResponseCardForm):
        return value
    try:
        return ResponseCardForm(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("响应牌形态必须是 physical 或 virtual") from exc


@dataclass(frozen=True)
class JinkResponseEvent:
    """一次已成功提供【闪】的互斥事件路由。"""

    source_card: JinkResponseSource
    response_card: str
    response_action: ResponseAction
    creates_card_used_event: bool
    creates_card_played_event: bool
    counts_for_use_or_play_total: bool
    response_provider: str
    physical_or_virtual: ResponseCardForm

    def __post_init__(self) -> None:
        if self.response_card != "闪":
            raise ValueError("该事件模型只允许响应牌为【闪】")
        if not isinstance(self.response_provider, str) or not self.response_provider.strip():
            raise ValueError("响应提供者必须是非空字符串")
        object.__setattr__(self, "response_provider", self.response_provider.strip())
        if self.creates_card_used_event == self.creates_card_played_event:
            raise ValueError("【闪】必须且只能生成 card_used 或 card_played 中的一种")
        expected_used = self.response_action is ResponseAction.USE
        if self.creates_card_used_event is not expected_used:
            raise ValueError("响应动作与 card_used 事件不一致")
        if self.creates_card_played_event is expected_used:
            raise ValueError("响应动作与 card_played 事件不一致")
        if not self.counts_for_use_or_play_total:
            raise ValueError("合法提供的【闪】必须计入“使用或打出”总数")

    @property
    def event_codes(self) -> tuple[str, ...]:
        return ("card_used",) if self.creates_card_used_event else ("card_played",)

    @property
    def jili_event_kind(self) -> CardEventKind:
        """两种动作都能进入【蒺藜】，但保持各自事件类型。"""

        return CardEventKind.USE if self.creates_card_used_event else CardEventKind.RESPOND

    @property
    def enters_first_used_card_check(self) -> bool:
        """清河公主“第一张使用牌”只读取 card_used。"""

        return self.creates_card_used_event

    def to_physical_card_loss_event(
        self,
        *,
        card_id: str,
        color: str,
        outside_owner_turn: bool = True,
    ) -> CardLossEvent:
        """把实体【闪】转换为失牌事件，供【明哲】等技能读取真实动作类型。"""

        if self.physical_or_virtual is not ResponseCardForm.PHYSICAL:
            raise ValueError("虚拟【闪】没有对应的实体手牌失去事件")
        return CardLossEvent(
            card_id=card_id,
            from_zone="手牌",
            to_zone="弃牌堆",
            reason="使用" if self.creates_card_used_event else "打出",
            color=color,
            outside_owner_turn=outside_owner_turn,
        )


def resolve_jink_response(
    source_card: JinkResponseSource | str,
    *,
    response_provider: str,
    physical_or_virtual: ResponseCardForm | str = ResponseCardForm.PHYSICAL,
) -> JinkResponseEvent:
    """根据当前响应对象生成且仅生成一种【闪】牌事件。"""

    source = _coerce_source(source_card)
    form = _coerce_form(physical_or_virtual)
    action = (
        ResponseAction.PLAY
        if source is JinkResponseSource.ARCHERY_ATTACK
        else ResponseAction.USE
    )
    return JinkResponseEvent(
        source_card=source,
        response_card="闪",
        response_action=action,
        creates_card_used_event=action is ResponseAction.USE,
        creates_card_played_event=action is ResponseAction.PLAY,
        counts_for_use_or_play_total=True,
        response_provider=response_provider,
        physical_or_virtual=form,
    )


@dataclass(frozen=True)
class BaguaArrayResult:
    activated: bool
    judgment_performed: bool
    judgment_color: str | None
    red_judgment: bool
    response_event: JinkResponseEvent | None


def resolve_bagua_array_judgment(
    source_card: JinkResponseSource | str,
    *,
    response_provider: str,
    activate: bool,
    judgment_color: str | None = None,
) -> BaguaArrayResult:
    """结算【八卦阵】判定；判红时虚拟【闪】继承当前窗口动作。"""

    source = _coerce_source(source_card)
    if not isinstance(activate, bool):
        raise TypeError("八卦阵发动标识必须是布尔值")
    if not activate:
        if judgment_color is not None:
            raise ValueError("不发动【八卦阵】时不应提供判定颜色")
        return BaguaArrayResult(False, False, None, False, None)
    if not isinstance(judgment_color, str) or judgment_color.strip() not in {"红", "黑"}:
        raise ValueError("八卦阵判定颜色必须是“红”或“黑”")
    color = judgment_color.strip()
    response = (
        resolve_jink_response(
            source,
            response_provider=response_provider,
            physical_or_virtual=ResponseCardForm.VIRTUAL,
        )
        if color == "红"
        else None
    )
    return BaguaArrayResult(True, True, color, color == "红", response)
