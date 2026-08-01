"""通用牌堆 CSV 加载、审计、分组统计与精确抽取概率。

本模块只处理通用的牌堆记录，不包含任何具体游戏、卡牌或版本数据。
"""

from __future__ import annotations

import csv
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from fractions import Fraction
from math import comb
from pathlib import Path
from typing import Iterable, Literal, Mapping

from ._validation import ensure_int_at_least

REQUIRED_CSV_FIELDS: tuple[str, ...] = (
    "instance_id",
    "deck_id",
    "platform",
    "mode",
    "version",
    "effective_date",
    "card_name",
    "card_variant",
    "card_type",
    "suit",
    "color",
    "rank",
    "quantity",
    "card_key",
    "equip_slot",
    "distance_modifier",
    "source",
    "source_type",
    "verification_status",
    "verified_date",
    "notes",
)

OPTIONAL_EMPTY_CSV_FIELDS: frozenset[str] = frozenset(
    {"equip_slot", "distance_modifier"}
)

DeckField = Literal[
    "card_name",
    "card_variant",
    "card_type",
    "suit",
    "color",
    "rank",
]
QUERY_FIELDS: tuple[str, ...] = (
    "card_name",
    "card_variant",
    "card_type",
    "suit",
    "color",
    "rank",
)
UNRESOLVED_VALUES: frozenset[str] = frozenset(
    {"待填写", "待核验", "未注明", "未知", "N/A", "NA"}
)
_DECK_METADATA_FIELDS: tuple[str, ...] = (
    "platform",
    "mode",
    "version",
    "effective_date",
)
_IDENTITY_FIELDS: tuple[str, ...] = (
    "deck_id",
    "suit",
    "rank",
    "card_name",
    "card_variant",
)


@dataclass(frozen=True, slots=True)
class DeckRecord:
    """一张实体牌的牌堆记录。

    正式牌堆 CSV 使用唯一 ``instance_id`` 且每行 ``quantity=1``。
    手工测试仍可省略新增字段以兼容旧的聚合记录；审计会把正式 CSV
    缺少必需实例字段视为错误。``source_row`` 是 CSV 中的一基行号。
    """

    deck_id: str
    platform: str
    mode: str
    version: str
    effective_date: str
    card_name: str
    card_variant: str
    card_type: str
    suit: str
    color: str
    rank: str
    quantity: int
    source: str
    verification_status: str
    notes: str
    instance_id: str = ""
    card_key: str = ""
    equip_slot: str = ""
    distance_modifier: str = ""
    source_type: str = ""
    verified_date: str = ""
    source_row: int = 0


@dataclass(frozen=True, slots=True)
class DeckIssue:
    """牌堆审计发现的一个问题。"""

    severity: Literal["error", "warning"]
    code: str
    message: str
    rows: tuple[int, ...] = ()
    fields: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class DeckAuditReport:
    """牌堆总量、分组统计和数据质量问题。"""

    total_quantity: int
    expected_total: int | None
    counts_by_card_name: Mapping[str, int]
    counts_by_card_type: Mapping[str, int]
    counts_by_color: Mapping[str, int]
    counts_by_suit: Mapping[str, int]
    unresolved_quantity_by_field: Mapping[str, int]
    issues: tuple[DeckIssue, ...]

    @property
    def errors(self) -> tuple[DeckIssue, ...]:
        return tuple(issue for issue in self.issues if issue.severity == "error")

    @property
    def warnings(self) -> tuple[DeckIssue, ...]:
        return tuple(
            issue for issue in self.issues if issue.severity == "warning"
        )

    @property
    def is_valid(self) -> bool:
        return not self.errors


@dataclass(frozen=True, slots=True)
class MatchProbabilityResult:
    """按一个结构化字段匹配时，“至少一张”的精确值或概率边界。"""

    deck_id: str
    field: DeckField
    value: str
    deck_size: int
    draw_count: int
    known_matching_quantity: int
    unresolved_quantity: int
    probability: Fraction | None
    lower_bound: Fraction
    upper_bound: Fraction

    @property
    def is_exact(self) -> bool:
        return self.probability is not None


def _clean_text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _row_label(record: DeckRecord) -> int:
    return record.source_row


def _parse_quantity(value: object, row_number: int) -> int:
    text = _clean_text(value)
    if not text or not text.isascii() or not text.isdecimal():
        raise ValueError(
            f"CSV 第 {row_number} 行的 quantity 必须是正整数，"
            f"当前值为 {value!r}"
        )
    quantity = int(text)
    if quantity < 1:
        raise ValueError(
            f"CSV 第 {row_number} 行的 quantity 必须大于或等于 1，"
            f"当前值为 {quantity}"
        )
    return quantity


def _validate_effective_date(value: str, row_number: int) -> None:
    if not value:
        return
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(
            f"CSV 第 {row_number} 行的 effective_date 必须使用 "
            f"YYYY-MM-DD 格式，当前值为 {value!r}"
        ) from exc


def load_deck_csv(
    path: str | Path,
    *,
    expected_total: int | None = None,
) -> tuple[tuple[DeckRecord, ...], DeckAuditReport]:
    """读取 UTF-8 CSV，并返回记录和完整审计报告。

    缺少表头、字段数量不符、日期格式错误或数量无法解析时立即抛出带
    行号的中文异常。重复、冲突、空字段和总数差异保留在审计报告中，
    便于一次查看全部数据质量问题。
    """

    try:
        csv_path = Path(path)
    except TypeError as exc:
        raise TypeError("牌堆 CSV 路径必须是字符串或 Path 对象") from exc

    try:
        handle = csv_path.open("r", encoding="utf-8-sig", newline="")
    except (OSError, UnicodeError) as exc:
        raise OSError(f"无法读取牌堆 CSV：{csv_path}") from exc

    with handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError("牌堆 CSV 缺少表头")

        fieldnames = tuple(
            field.strip() if isinstance(field, str) else ""
            for field in reader.fieldnames
        )
        duplicate_headers = sorted(
            {
                field
                for field in fieldnames
                if field and fieldnames.count(field) > 1
            }
        )
        if duplicate_headers:
            names = "、".join(duplicate_headers)
            raise ValueError(f"牌堆 CSV 存在重复表头：{names}")

        missing_headers = [
            field for field in REQUIRED_CSV_FIELDS if field not in fieldnames
        ]
        if missing_headers:
            names = "、".join(missing_headers)
            raise ValueError(f"牌堆 CSV 缺少必需字段：{names}")

        records: list[DeckRecord] = []
        for row_number, row in enumerate(reader, start=2):
            if None in row:
                raise ValueError(
                    f"CSV 第 {row_number} 行的字段数量超过表头数量"
                )
            normalized = {
                field: _clean_text(row.get(field))
                for field in REQUIRED_CSV_FIELDS
            }
            effective_date = normalized["effective_date"]
            _validate_effective_date(effective_date, row_number)
            _validate_effective_date(normalized["verified_date"], row_number)
            quantity = _parse_quantity(row.get("quantity"), row_number)
            records.append(
                DeckRecord(
                    deck_id=normalized["deck_id"],
                    platform=normalized["platform"],
                    mode=normalized["mode"],
                    version=normalized["version"],
                    effective_date=effective_date,
                    card_name=normalized["card_name"],
                    card_variant=normalized["card_variant"],
                    card_type=normalized["card_type"],
                    suit=normalized["suit"],
                    color=normalized["color"],
                    rank=normalized["rank"],
                    quantity=quantity,
                    source=normalized["source"],
                    verification_status=normalized["verification_status"],
                    notes=normalized["notes"],
                    instance_id=normalized["instance_id"],
                    card_key=normalized["card_key"],
                    equip_slot=normalized["equip_slot"],
                    distance_modifier=normalized["distance_modifier"],
                    source_type=normalized["source_type"],
                    verified_date=normalized["verified_date"],
                    source_row=row_number,
                )
            )

    prepared_records = tuple(records)
    return (
        prepared_records,
        validate_deck_records(
            prepared_records,
            expected_total=expected_total,
        ),
    )


def _count_values(
    records: tuple[DeckRecord, ...],
    field: DeckField,
) -> dict[str, int]:
    counts: defaultdict[str, int] = defaultdict(int)
    for record in records:
        value = _clean_text(getattr(record, field))
        counts[value] += record.quantity
    return dict(sorted(counts.items()))


def validate_deck_records(
    records: Iterable[DeckRecord],
    *,
    expected_total: int | None = None,
) -> DeckAuditReport:
    """审计牌堆总量、空字段、未解析值、重复记录和冲突记录。"""

    try:
        prepared = tuple(records)
    except TypeError as exc:
        raise TypeError("牌堆记录必须是可迭代对象") from exc

    if expected_total is not None:
        ensure_int_at_least(expected_total, "预期总牌数", 0)

    issues: list[DeckIssue] = []
    empty_rows: defaultdict[str, list[int]] = defaultdict(list)
    unresolved_rows: defaultdict[str, list[int]] = defaultdict(list)
    unresolved_quantities: defaultdict[str, int] = defaultdict(int)
    valid_quantity_records: list[DeckRecord] = []

    if not prepared:
        issues.append(
            DeckIssue(
                severity="error",
                code="empty_deck",
                message="牌堆记录不能为空",
            )
        )

    for index, record in enumerate(prepared, start=1):
        if not isinstance(record, DeckRecord):
            raise TypeError(
                f"第 {index} 个牌堆记录必须是 DeckRecord，"
                f"当前类型为 {type(record).__name__}"
            )

        row = _row_label(record)
        if isinstance(record.quantity, bool) or not isinstance(
            record.quantity, int
        ):
            issues.append(
                DeckIssue(
                    severity="error",
                    code="invalid_quantity",
                    message=(
                        f"第 {row or index} 条记录的 quantity 必须是正整数，"
                        f"当前值为 {record.quantity!r}"
                    ),
                    rows=(row,) if row else (),
                    fields=("quantity",),
                )
            )
            continue
        if record.quantity < 1:
            issues.append(
                DeckIssue(
                    severity="error",
                    code="invalid_quantity",
                    message=(
                        f"第 {row or index} 条记录的 quantity 必须大于或等于 1，"
                        f"当前值为 {record.quantity}"
                    ),
                    rows=(row,) if row else (),
                    fields=("quantity",),
                )
            )
            continue
        valid_quantity_records.append(record)

        if _clean_text(record.instance_id) and record.quantity != 1:
            issues.append(
                DeckIssue(
                    severity="error",
                    code="invalid_instance_quantity",
                    message=(
                        f"实体牌 {record.instance_id!r} 必须一行一张且 quantity=1"
                    ),
                    rows=(row,) if row else (),
                    fields=("instance_id", "quantity"),
                )
            )

        for field in REQUIRED_CSV_FIELDS:
            if field == "quantity":
                continue
            raw_value = getattr(record, field)
            value = _clean_text(raw_value)
            if not value and field not in OPTIONAL_EMPTY_CSV_FIELDS:
                empty_rows[field].append(row)
            if field in QUERY_FIELDS and (
                not value or value in UNRESOLVED_VALUES
            ):
                unresolved_rows[field].append(row)
                unresolved_quantities[field] += record.quantity

    for field, rows in sorted(empty_rows.items()):
        shown_rows = tuple(row for row in rows if row)
        row_text = "、".join(str(row) for row in shown_rows) or "手工记录"
        issues.append(
            DeckIssue(
                severity="error",
                code="empty_field",
                message=f"字段 {field} 存在空值，位置：{row_text}",
                rows=shown_rows,
                fields=(field,),
            )
        )

    for field, rows in sorted(unresolved_rows.items()):
        shown_rows = tuple(row for row in rows if row)
        issues.append(
            DeckIssue(
                severity="warning",
                code="unresolved_field",
                message=(
                    f"字段 {field} 有 {unresolved_quantities[field]} 张牌未解析；"
                    "依赖该字段的概率只能报告上下界"
                ),
                rows=shown_rows,
                fields=(field,),
            )
        )

    total_quantity = sum(
        record.quantity for record in valid_quantity_records
    )
    if expected_total is not None and total_quantity != expected_total:
        issues.append(
            DeckIssue(
                severity="error",
                code="total_mismatch",
                message=(
                    f"牌堆 quantity 之和为 {total_quantity}，"
                    f"与预期总牌数 {expected_total} 不一致，"
                    f"差值为 {total_quantity - expected_total:+d}"
                ),
                fields=("quantity",),
            )
        )

    metadata_groups: defaultdict[
        str, defaultdict[tuple[str, str, str, str], list[int]]
    ] = defaultdict(lambda: defaultdict(list))
    identity_groups: defaultdict[
        tuple[str, str, str, str, str], list[DeckRecord]
    ] = defaultdict(list)
    instance_groups: defaultdict[
        tuple[str, str], list[DeckRecord]
    ] = defaultdict(list)

    for record in valid_quantity_records:
        deck_id = _clean_text(record.deck_id)
        metadata = tuple(
            _clean_text(getattr(record, field))
            for field in _DECK_METADATA_FIELDS
        )
        metadata_groups[deck_id][metadata].append(_row_label(record))
        instance_id = _clean_text(record.instance_id)
        if instance_id:
            instance_groups[(deck_id, instance_id)].append(record)
        else:
            identity = tuple(
                _clean_text(getattr(record, field))
                for field in _IDENTITY_FIELDS
            )
            identity_groups[identity].append(record)

    for deck_id, groups in sorted(metadata_groups.items()):
        if len(groups) <= 1:
            continue
        rows = tuple(
            sorted(
                row
                for grouped_rows in groups.values()
                for row in grouped_rows
                if row
            )
        )
        issues.append(
            DeckIssue(
                severity="error",
                code="deck_metadata_conflict",
                message=(
                    f"deck_id={deck_id!r} 对应多个平台、模式、版本或日期，"
                    "禁止将它们作为同一牌堆混合"
                ),
                rows=rows,
                fields=("deck_id",) + _DECK_METADATA_FIELDS,
            )
        )

    comparison_fields = tuple(
        field
        for field in REQUIRED_CSV_FIELDS
        if field not in {"quantity"}
    )

    grouped_identities: list[
        tuple[str, tuple[str, ...], list[DeckRecord], tuple[str, ...]]
    ] = []
    grouped_identities.extend(
        (
            "实体牌实例",
            identity,
            group,
            ("deck_id", "instance_id"),
        )
        for identity, group in sorted(instance_groups.items())
    )
    grouped_identities.extend(
        ("旧版逻辑牌记录", identity, group, _IDENTITY_FIELDS)
        for identity, group in sorted(identity_groups.items())
    )
    for label, identity, group, identity_fields in grouped_identities:
        if len(group) <= 1:
            continue
        rows = tuple(
            sorted(record.source_row for record in group if record.source_row)
        )
        fingerprints = {
            tuple(
                _clean_text(getattr(record, field))
                for field in comparison_fields
            )
            for record in group
        }
        identity_text = "/".join(identity)
        if len(fingerprints) == 1:
            issues.append(
                DeckIssue(
                    severity="error",
                    code="duplicate_record",
                    message=(
                        f"{label}重复：{identity_text}；"
                        "正式实例表必须保持一行一张且实例标识唯一"
                    ),
                    rows=rows,
                    fields=identity_fields,
                )
            )
        else:
            issues.append(
                DeckIssue(
                    severity="error",
                    code="conflicting_record",
                    message=(
                        f"{label}存在冲突：{identity_text}；"
                        "停止合并并核对各行属性"
                    ),
                    rows=rows,
                    fields=identity_fields,
                )
            )

    valid_records_tuple = tuple(valid_quantity_records)
    return DeckAuditReport(
        total_quantity=total_quantity,
        expected_total=expected_total,
        counts_by_card_name=_count_values(
            valid_records_tuple, "card_name"
        ),
        counts_by_card_type=_count_values(
            valid_records_tuple, "card_type"
        ),
        counts_by_color=_count_values(valid_records_tuple, "color"),
        counts_by_suit=_count_values(valid_records_tuple, "suit"),
        unresolved_quantity_by_field={
            field: unresolved_quantities.get(field, 0)
            for field in QUERY_FIELDS
        },
        issues=tuple(issues),
    )


def _validate_field(field: str) -> DeckField:
    if field not in QUERY_FIELDS:
        names = "、".join(QUERY_FIELDS)
        raise ValueError(
            f"统计字段必须是以下之一：{names}；当前值为 {field!r}"
        )
    return field  # type: ignore[return-value]


def _select_deck(
    records: Iterable[DeckRecord],
    deck_id: str,
) -> tuple[DeckRecord, ...]:
    if not isinstance(deck_id, str) or not deck_id.strip():
        raise ValueError("deck_id 必须是非空字符串")
    requested_id = deck_id.strip()
    try:
        prepared = tuple(records)
    except TypeError as exc:
        raise TypeError("牌堆记录必须是可迭代对象") from exc

    selected = tuple(
        record
        for record in prepared
        if isinstance(record, DeckRecord)
        and _clean_text(record.deck_id) == requested_id
    )
    if not selected:
        available = sorted(
            {
                _clean_text(record.deck_id)
                for record in prepared
                if isinstance(record, DeckRecord)
                and _clean_text(record.deck_id)
            }
        )
        suffix = f"；可用 deck_id：{'、'.join(available)}" if available else ""
        raise ValueError(f"找不到 deck_id={requested_id!r} 的牌堆{suffix}")

    report = validate_deck_records(selected)
    if report.errors:
        messages = "；".join(issue.message for issue in report.errors)
        raise ValueError(
            f"deck_id={requested_id!r} 的牌堆未通过校验：{messages}"
        )
    return selected


def count_by_field(
    records: Iterable[DeckRecord],
    *,
    deck_id: str,
    field: DeckField,
) -> dict[str, int]:
    """统计一个明确 ``deck_id`` 中各字段值的牌数。"""

    selected = _select_deck(records, deck_id)
    validated_field = _validate_field(field)
    return _count_values(selected, validated_field)


def exact_probability_at_least_one(
    population_size: int,
    matching_count: int,
    draw_count: int,
) -> Fraction:
    """精确计算均匀不放回抽取时至少一张匹配对象的概率。"""

    population = ensure_int_at_least(population_size, "牌堆总数", 0)
    matching = ensure_int_at_least(matching_count, "匹配牌数", 0)
    draws = ensure_int_at_least(draw_count, "抽取数量", 0)

    if matching > population:
        raise ValueError(
            f"匹配牌数不能超过牌堆总数，当前为 {matching}>{population}"
        )
    if draws > population:
        raise ValueError(
            f"抽取数量不能超过牌堆总数，当前为 {draws}>{population}"
        )
    if draws == 0 or matching == 0:
        return Fraction(0, 1)
    if draws > population - matching:
        return Fraction(1, 1)

    total_combinations = comb(population, draws)
    no_match_combinations = comb(population - matching, draws)
    return Fraction(
        total_combinations - no_match_combinations,
        total_combinations,
    )


def probability_at_least_one_by_field(
    records: Iterable[DeckRecord],
    *,
    deck_id: str,
    field: DeckField,
    value: str,
    draw_count: int,
) -> MatchProbabilityResult:
    """按牌名、类别、颜色、花色、点数或变体查询至少一张的概率。

    ``verification_status`` 只描述来源核验状态，不会把已有结构化字段
    判为未知。仅当本次查询字段本身为空或使用未解析占位词时，结果才
    改为上下界。
    """

    selected = _select_deck(records, deck_id)
    validated_field = _validate_field(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError("匹配值必须是非空字符串")
    requested_value = value.strip()
    if requested_value in UNRESOLVED_VALUES:
        raise ValueError(f"不能把未解析占位词 {requested_value!r} 作为匹配值")

    deck_size = sum(record.quantity for record in selected)
    known_matching_quantity = 0
    unresolved_quantity = 0
    for record in selected:
        field_value = _clean_text(getattr(record, validated_field))
        if not field_value or field_value in UNRESOLVED_VALUES:
            unresolved_quantity += record.quantity
        elif field_value == requested_value:
            known_matching_quantity += record.quantity

    lower_bound = exact_probability_at_least_one(
        deck_size,
        known_matching_quantity,
        draw_count,
    )
    upper_bound = exact_probability_at_least_one(
        deck_size,
        known_matching_quantity + unresolved_quantity,
        draw_count,
    )
    probability = lower_bound if unresolved_quantity == 0 else None

    return MatchProbabilityResult(
        deck_id=deck_id.strip(),
        field=validated_field,
        value=requested_value,
        deck_size=deck_size,
        draw_count=draw_count,
        known_matching_quantity=known_matching_quantity,
        unresolved_quantity=unresolved_quantity,
        probability=probability,
        lower_bound=lower_bound,
        upper_bound=upper_bound,
    )


__all__ = [
    "QUERY_FIELDS",
    "REQUIRED_CSV_FIELDS",
    "UNRESOLVED_VALUES",
    "DeckAuditReport",
    "DeckField",
    "DeckIssue",
    "DeckRecord",
    "MatchProbabilityResult",
    "count_by_field",
    "exact_probability_at_least_one",
    "load_deck_csv",
    "probability_at_least_one_by_field",
    "validate_deck_records",
]
