"""三国杀结构化卡牌分层数据的标准库加载与三值解析。"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Mapping


USE_MODE_FIELDS: tuple[str, ...] = (
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
)


class StructuredTriState(Enum):
    TRUE = "true"
    FALSE = "false"
    UNKNOWN_OR_NOT_APPLICABLE = "unknown_or_not_applicable"


def parse_structured_tristate(value: object) -> StructuredTriState:
    """空值保持未知，不自动变成 false、0 次或无限制。"""

    if isinstance(value, bool):
        return StructuredTriState.TRUE if value else StructuredTriState.FALSE
    if value is None:
        return StructuredTriState.UNKNOWN_OR_NOT_APPLICABLE
    if not isinstance(value, str):
        raise TypeError("三值字段必须是布尔值、字符串或 None")
    normalized = value.strip().lower()
    if normalized in {"true", "是"}:
        return StructuredTriState.TRUE
    if normalized in {"false", "否"}:
        return StructuredTriState.FALSE
    if normalized in {"", "unknown", "unknown_or_not_applicable", "未提供", "不适用"}:
        return StructuredTriState.UNKNOWN_OR_NOT_APPLICABLE
    raise ValueError(f"无法识别三值字段：{value!r}")


@dataclass(frozen=True)
class CardUseModeRecord:
    card_key: str
    use_mode: str
    timing: str
    target_scope: str
    condition: str
    limit_scope: str
    limit_count: str
    response_to: str
    response_action: str
    event_type: str
    physical_or_virtual: str
    source_row: int = 0

    def __post_init__(self) -> None:
        for name in USE_MODE_FIELDS:
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"卡牌用途字段 {name} 不能为空")
            object.__setattr__(self, name, value.strip())
        if self.limit_count != "unlimited":
            try:
                count = int(self.limit_count)
            except ValueError as exc:
                raise ValueError("用途次数必须是 unlimited 或正整数") from exc
            if count < 1:
                raise ValueError("用途次数整数必须大于或等于 1")
        if self.limit_count == "unlimited" and self.limit_scope != "none":
            raise ValueError("无限制用途的 limit_scope 必须为 none")
        if self.response_to == "none":
            if self.response_action != "none" or self.event_type != "none":
                raise ValueError("非响应用途不得声明 response_action 或 event_type")
            if self.physical_or_virtual != "not_applicable":
                raise ValueError("非响应用途的 physical_or_virtual 必须为 not_applicable")
        else:
            if self.response_to not in {"slash", "archery_attack"}:
                raise ValueError("当前结构化响应对象只支持 slash 或 archery_attack")
            expected_events = {"use": "card_used", "play": "card_played"}
            if self.response_action not in expected_events:
                raise ValueError("响应动作必须是 use 或 play")
            if self.event_type != expected_events[self.response_action]:
                raise ValueError("响应动作与事件类型不一致")
            if self.physical_or_virtual not in {"physical", "virtual"}:
                raise ValueError("响应牌形态必须是 physical 或 virtual")

    def as_mapping(self) -> Mapping[str, object]:
        return MappingProxyType(
            {name: getattr(self, name) for name in USE_MODE_FIELDS}
        )


def _read_csv_rows(path: str | Path) -> tuple[tuple[str, ...], list[dict[str, str]]]:
    csv_path = Path(path)
    try:
        handle = csv_path.open("r", encoding="utf-8-sig", newline="")
    except (OSError, UnicodeError) as exc:
        raise OSError(f"无法读取结构化 CSV：{csv_path}") from exc
    with handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError("结构化 CSV 缺少表头")
        fields = tuple(field.strip() for field in reader.fieldnames)
        if len(fields) != len(set(fields)):
            raise ValueError("结构化 CSV 表头不能重复")
        rows = []
        for row_number, row in enumerate(reader, start=2):
            if None in row:
                raise ValueError(f"结构化 CSV 第 {row_number} 行字段数量错位")
            rows.append({key: (value or "").strip() for key, value in row.items()})
    return fields, rows


def load_card_use_modes(path: str | Path) -> tuple[CardUseModeRecord, ...]:
    fields, rows = _read_csv_rows(path)
    if fields != USE_MODE_FIELDS:
        raise ValueError("卡牌使用方式 CSV 的字段顺序或字段集合不正确")
    records = tuple(
        CardUseModeRecord(
            **{field: row[field] for field in USE_MODE_FIELDS},
            source_row=index,
        )
        for index, row in enumerate(rows, start=2)
    )
    keys = [(record.card_key, record.use_mode) for record in records]
    if len(keys) != len(set(keys)):
        raise ValueError("卡牌使用方式 CSV 存在重复的 card_key/use_mode")
    return records


@dataclass(frozen=True)
class StructuredCardDataBundle:
    definitions_by_key: Mapping[str, Mapping[str, str]]
    use_modes_by_key: Mapping[str, tuple[CardUseModeRecord, ...]]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "definitions_by_key",
            MappingProxyType(dict(self.definitions_by_key)),
        )
        object.__setattr__(
            self,
            "use_modes_by_key",
            MappingProxyType(dict(self.use_modes_by_key)),
        )


def link_card_definitions_and_use_modes(
    definition_path: str | Path,
    use_mode_path: str | Path,
) -> StructuredCardDataBundle:
    """关联一牌一种定义与多用途子表，拒绝孤立用途或重复主键。"""

    fields, rows = _read_csv_rows(definition_path)
    if "card_id" not in fields or "card_name" not in fields:
        raise ValueError("卡牌定义 CSV 必须包含 card_id 与 card_name")
    if any(field.startswith("ai_") or "strategy" in field.lower() for field in fields):
        raise ValueError("AI 策略字段不得写入卡牌定义 CSV")
    definitions: dict[str, Mapping[str, str]] = {}
    for index, row in enumerate(rows, start=2):
        key = row.get("card_id", "")
        if not key:
            raise ValueError(f"卡牌定义 CSV 第 {index} 行 card_id 不能为空")
        if key in definitions:
            raise ValueError(f"卡牌定义 card_id 重复：{key}")
        definitions[key] = MappingProxyType(dict(row))

    grouped: dict[str, list[CardUseModeRecord]] = {}
    for mode in load_card_use_modes(use_mode_path):
        if mode.card_key not in definitions:
            raise ValueError(f"卡牌用途引用了不存在的 card_key：{mode.card_key}")
        grouped.setdefault(mode.card_key, []).append(mode)
    return StructuredCardDataBundle(
        definitions_by_key=definitions,
        use_modes_by_key={key: tuple(value) for key, value in grouped.items()},
    )
