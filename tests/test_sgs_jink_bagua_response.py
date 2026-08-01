from __future__ import annotations

from pathlib import Path

import pytest
import scripts

from scripts.sgs_general_rules import (
    JiliTurnState,
    mingzhe_draw_opportunities,
    resolve_jili_card_event,
)
from scripts.sgs_incremental_generals import WuMarkState, resolve_wu_card_event
from scripts.sgs_jink_response import (
    JinkResponseSource,
    ResponseAction,
    ResponseCardForm,
    resolve_bagua_array_judgment,
    resolve_jink_response,
)
from scripts.sgs_structured_data import link_card_definitions_and_use_modes


ROOT = Path(__file__).resolve().parents[1]
KNOWLEDGE = ROOT / "knowledge"
DEFINITIONS = KNOWLEDGE / "三国杀卡牌结构化数据.csv"
USE_MODES = KNOWLEDGE / "三国杀卡牌使用方式.csv"


@pytest.mark.parametrize("source", ["杀", "火杀", "雷杀"])
def test_bagua_red_judgment_against_slash_creates_only_card_used(source: str) -> None:
    result = resolve_bagua_array_judgment(
        source,
        response_provider="目标",
        activate=True,
        judgment_color="红",
    )

    event = result.response_event
    assert event is not None
    assert event.response_action is ResponseAction.USE
    assert event.event_codes == ("card_used",)
    assert event.creates_card_used_event
    assert not event.creates_card_played_event
    assert event.physical_or_virtual is ResponseCardForm.VIRTUAL


def test_bagua_red_judgment_against_archery_creates_only_card_played() -> None:
    result = resolve_bagua_array_judgment(
        "万箭齐发",
        response_provider="目标",
        activate=True,
        judgment_color="红",
    )

    event = result.response_event
    assert event is not None
    assert event.source_card is JinkResponseSource.ARCHERY_ATTACK
    assert event.response_action is ResponseAction.PLAY
    assert event.event_codes == ("card_played",)
    assert not event.creates_card_used_event
    assert event.creates_card_played_event
    assert event.physical_or_virtual is ResponseCardForm.VIRTUAL


@pytest.mark.parametrize("source", ["杀", "万箭齐发"])
def test_bagua_both_routes_count_for_jili_without_merging_event_types(source: str) -> None:
    event = resolve_bagua_array_judgment(
        source,
        response_provider="沙摩柯",
        activate=True,
        judgment_color="红",
    ).response_event
    assert event is not None and event.counts_for_use_or_play_total

    jili = resolve_jili_card_event(
        JiliTurnState(),
        event_kind=event.jili_event_kind,
        attack_range_before_card_effect=1,
    )
    assert jili.counted and jili.triggered and jili.draw_count == 1


def test_only_slash_route_enters_qinghe_first_used_card_check() -> None:
    slash_event = resolve_bagua_array_judgment(
        "杀",
        response_provider="目标",
        activate=True,
        judgment_color="红",
    ).response_event
    archery_event = resolve_bagua_array_judgment(
        "万箭齐发",
        response_provider="目标",
        activate=True,
        judgment_color="红",
    ).response_event
    assert slash_event is not None and archery_event is not None

    slash_wu = resolve_wu_card_event(
        WuMarkState(frozenset({"闪"})),
        event_is_use=slash_event.enters_first_used_card_check,
        original_entity_name="闪",
    )
    archery_wu = resolve_wu_card_event(
        WuMarkState(frozenset({"闪"})),
        event_is_use=archery_event.enters_first_used_card_check,
        original_entity_name="闪",
    )
    assert slash_wu.occupied_first_use and slash_wu.hp_loss == 1
    assert not archery_wu.occupied_first_use and archery_wu.hp_loss == 0


def test_physical_jink_uses_the_same_context_route() -> None:
    slash = resolve_jink_response("杀", response_provider="甲")
    archery = resolve_jink_response("万箭齐发", response_provider="甲")

    assert slash.physical_or_virtual is ResponseCardForm.PHYSICAL
    assert slash.event_codes == ("card_used",)
    assert archery.physical_or_virtual is ResponseCardForm.PHYSICAL
    assert archery.event_codes == ("card_played",)


@pytest.mark.parametrize(
    ("source", "expected_reason"),
    [("杀", "使用"), ("万箭齐发", "打出")],
)
def test_physical_red_jink_routes_real_action_into_mingzhe(
    source: str,
    expected_reason: str,
) -> None:
    event = resolve_jink_response(source, response_provider="王元姬")
    loss = event.to_physical_card_loss_event(
        card_id="red-jink-1",
        color="红",
        outside_owner_turn=True,
    )

    assert loss.reason == expected_reason
    assert mingzhe_draw_opportunities((loss,)) == 1


def test_virtual_bagua_jink_does_not_fabricate_physical_mingzhe_loss() -> None:
    event = resolve_bagua_array_judgment(
        "杀",
        response_provider="王元姬",
        activate=True,
        judgment_color="红",
    ).response_event
    assert event is not None

    with pytest.raises(ValueError, match="虚拟【闪】没有对应"):
        event.to_physical_card_loss_event(card_id="不存在", color="红")


def test_jink_and_bagua_context_router_is_exported_by_scripts_package() -> None:
    names = {
        "BaguaArrayResult",
        "JinkResponseEvent",
        "JinkResponseSource",
        "ResponseAction",
        "ResponseCardForm",
        "resolve_bagua_array_judgment",
        "resolve_jink_response",
    }
    assert names <= set(scripts.__all__)
    assert all(hasattr(scripts, name) for name in names)


def test_bagua_black_or_declined_provides_no_virtual_jink() -> None:
    black = resolve_bagua_array_judgment(
        "杀",
        response_provider="甲",
        activate=True,
        judgment_color="黑",
    )
    declined = resolve_bagua_array_judgment(
        "杀",
        response_provider="甲",
        activate=False,
    )

    assert black.judgment_performed and black.response_event is None
    assert not declined.judgment_performed and declined.response_event is None


def test_structured_modes_keep_jink_and_bagua_response_routes_separate() -> None:
    bundle = link_card_definitions_and_use_modes(DEFINITIONS, USE_MODES)
    jink = {mode.use_mode: mode for mode in bundle.use_modes_by_key["sgs_basic_shan"]}
    bagua = {
        mode.use_mode: mode
        for mode in bundle.use_modes_by_key["sgs_armor_baguazhen"]
    }

    assert (jink["slash_response"].response_action, jink["slash_response"].event_type) == (
        "use",
        "card_used",
    )
    assert (
        jink["archery_attack_response"].response_action,
        jink["archery_attack_response"].event_type,
    ) == ("play", "card_played")
    assert bagua["bagua_slash_response"].physical_or_virtual == "virtual"
    assert bagua["bagua_slash_response"].event_type == "card_used"
    assert bagua["bagua_archery_attack_response"].event_type == "card_played"


def test_formal_files_do_not_describe_bagua_as_always_playing_jink() -> None:
    cards = (KNOWLEDGE / "三国杀卡牌效果.md").read_text(encoding="utf-8")
    mechanics = (KNOWLEDGE / "三国杀基础术语与通用机制.md").read_text(
        encoding="utf-8"
    )
    bagua_section = cards.split("### 8.1 【八卦阵】", 1)[1].split("### 8.2", 1)[0]

    assert "需要使用或打出【闪】" in bagua_section
    assert "响应“杀”时只生成 `card_used`" in bagua_section
    assert "响应【万箭齐发】时只生成 `card_played`" in bagua_section
    assert "判定结果为红色，视为你打出一张【闪】" not in bagua_section
    assert "八卦阵】的文字为“当你需要使用或打出【闪】时”" in mechanics
