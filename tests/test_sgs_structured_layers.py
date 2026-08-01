from __future__ import annotations

import csv
from pathlib import Path

import pandas as pd
import pytest

from scripts.sgs_card_rules import CardUseContext, resolve_structured_card_usage
from scripts.sgs_structured_data import (
    StructuredTriState,
    link_card_definitions_and_use_modes,
    load_card_use_modes,
    parse_structured_tristate,
)


ROOT = Path(__file__).resolve().parents[1]
DEFINITIONS = ROOT / "knowledge" / "三国杀卡牌结构化数据.csv"
USE_MODES = ROOT / "knowledge" / "三国杀卡牌使用方式.csv"


def test_use_mode_csv_is_readable_by_standard_csv_and_pandas() -> None:
    with USE_MODES.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
    assert reader.fieldnames == [
        "card_key",
        "use_mode",
        "timing",
        "target_scope",
        "condition",
        "limit_scope",
        "limit_count",
        "response_to",
        "response_action",
        "event_type",
        "physical_or_virtual",
    ]
    assert len(rows) == 9
    assert all(None not in row for row in rows)

    frame = pd.read_csv(USE_MODES, dtype=str, keep_default_na=False, encoding="utf-8")
    assert frame.shape == (9, 11)


def test_card_instances_definitions_and_use_modes_link() -> None:
    bundle = link_card_definitions_and_use_modes(DEFINITIONS, USE_MODES)

    assert len(bundle.definitions_by_key) == 38
    assert set(bundle.use_modes_by_key) == {
        "sgs_basic_tao",
        "sgs_basic_jiu",
        "sgs_basic_shan",
        "sgs_armor_baguazhen",
    }
    assert len(bundle.use_modes_by_key["sgs_basic_tao"]) == 3
    assert len(bundle.use_modes_by_key["sgs_basic_jiu"]) == 2
    assert len(bundle.use_modes_by_key["sgs_basic_shan"]) == 2
    assert len(bundle.use_modes_by_key["sgs_armor_baguazhen"]) == 2


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (True, StructuredTriState.TRUE),
        ("是", StructuredTriState.TRUE),
        ("true", StructuredTriState.TRUE),
        (False, StructuredTriState.FALSE),
        ("否", StructuredTriState.FALSE),
        ("false", StructuredTriState.FALSE),
        ("", StructuredTriState.UNKNOWN_OR_NOT_APPLICABLE),
        (None, StructuredTriState.UNKNOWN_OR_NOT_APPLICABLE),
    ],
)
def test_structured_tristate_does_not_turn_empty_into_false(raw, expected) -> None:
    assert parse_structured_tristate(raw) is expected


def test_external_use_mode_is_the_single_source_for_peach_modes() -> None:
    bundle = link_card_definitions_and_use_modes(DEFINITIONS, USE_MODES)
    definition = bundle.definitions_by_key["sgs_basic_tao"]
    mode = next(
        item
        for item in bundle.use_modes_by_key["sgs_basic_tao"]
        if item.use_mode == "rescue_other_dying_character"
    )

    parsed = resolve_structured_card_usage(
        definition,
        use_context=CardUseContext.RESCUE_OTHER_DYING_CHARACTER,
        use_mode_row=mode.as_mapping(),
    )

    assert parsed.default_timing == "legal_dying_rescue_window"
    assert parsed.target_scope == "other_dying_character"
    assert parsed.requires_target_dying is True
    assert parsed.base_use_limit == "unlimited"


def test_blank_embedded_modes_are_not_treated_as_unlimited_without_subtable() -> None:
    bundle = link_card_definitions_and_use_modes(DEFINITIONS, USE_MODES)
    definition = bundle.definitions_by_key["sgs_basic_tao"]

    with pytest.raises(ValueError, match="独立用途记录"):
        resolve_structured_card_usage(
            definition,
            use_context=CardUseContext.OWN_PLAY_PHASE_SELF_HEAL,
        )


def test_ai_strategy_fields_are_not_stored_in_card_definitions() -> None:
    with DEFINITIONS.open(encoding="utf-8", newline="") as handle:
        fields = csv.DictReader(handle).fieldnames
    assert fields is not None
    assert not any(field.startswith("ai_") or "strategy" in field.lower() for field in fields)
