"""确定性回放记录、规范 JSON 与逐步完整性校验。

回放保存事件负载和每一步的状态快照。状态哈希可以证明载入后的快照没有
被意外改写；前向哈希链同时覆盖事件顺序、事件负载和回放头。它是完整性
检查，不是带密钥的数字签名，也不是规则重执行。依赖 ``random.Random``
调用序列的逐位复现只在相同且已记录的 Python／随机实现范围内承诺；调用
方应把运行时版本和随机算法标识写入回放头元数据。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from enum import Enum
import hashlib
import json
import math
from pathlib import Path
from types import MappingProxyType
from typing import Any, Iterator, Mapping, Sequence


class ReplayError(ValueError):
    """回放模块的基础错误。"""


class ReplayFormatError(ReplayError):
    """回放文件结构或编码无效。"""


class ReplayIntegrityError(ReplayError):
    """回放内容与记录的哈希不一致。"""


NOT_LOADED_HASH = "NOT_LOADED"
_SHA256_LENGTH = 64
_HEX_DIGITS = frozenset("0123456789abcdef")


def _deep_freeze(value: Any) -> Any:
    """递归冻结规范 JSON 值，阻止载入后绕过哈希校验直接改写。"""

    if isinstance(value, Mapping):
        return MappingProxyType({key: _deep_freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_deep_freeze(item) for item in value)
    if isinstance(value, tuple):
        return tuple(_deep_freeze(item) for item in value)
    return value


def _deep_copy_json(value: Any) -> Any:
    """从冻结值生成独立且可 JSON 序列化的深拷贝。"""

    if isinstance(value, Mapping):
        return {key: _deep_copy_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_deep_copy_json(item) for item in value]
    if isinstance(value, list):
        return [_deep_copy_json(item) for item in value]
    return value


def _required_nonempty_text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ReplayFormatError(f"回放头 {name} 必须是非空字符串")
    return value.strip()


def _required_sha256(
    value: Any,
    name: str,
    *,
    allow_not_loaded: bool = False,
) -> str:
    """规范化来源摘要；基础设施可显式写 ``NOT_LOADED``，不得伪造摘要。"""

    text = _required_nonempty_text(value, name)
    if allow_not_loaded and text == NOT_LOADED_HASH:
        return text
    lowered = text.casefold()
    if len(lowered) != _SHA256_LENGTH or any(char not in _HEX_DIGITS for char in lowered):
        suffix = f"或明确值 {NOT_LOADED_HASH}" if allow_not_loaded else ""
        raise ReplayFormatError(f"回放头 {name} 必须是64位SHA-256十六进制摘要{suffix}")
    return lowered


def _normalize(value: Any, *, path: str = "$") -> Any:
    """转换为可规范序列化的 JSON 值，拒绝不稳定的 ``repr``。"""

    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ReplayFormatError(f"回放字段 {path} 必须是有限数值")
        return value
    if isinstance(value, Enum):
        return _normalize(value.value, path=path)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, bytes):
        return {"__bytes_hex__": value.hex()}
    if isinstance(value, range):
        return list(value)
    if is_dataclass(value) and not isinstance(value, type):
        return _normalize(asdict(value), path=path)
    to_replay_dict = getattr(value, "to_replay_dict", None)
    if callable(to_replay_dict):
        return _normalize(to_replay_dict(), path=path)
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ReplayFormatError(f"回放映射 {path} 的键必须是字符串")
            result[key] = _normalize(item, path=f"{path}.{key}")
        return result
    if isinstance(value, (list, tuple)):
        return [
            _normalize(item, path=f"{path}[{index}]")
            for index, item in enumerate(value)
        ]
    if isinstance(value, (set, frozenset)):
        items = [_normalize(item, path=f"{path}[]") for item in value]
        return sorted(items, key=canonical_json)
    raise ReplayFormatError(
        f"回放字段 {path} 的类型 {type(value).__name__} 无法稳定序列化；"
        "请使用 dataclass 或实现 to_replay_dict()"
    )


def canonical_json(value: Any) -> str:
    """返回 UTF-8 友好的确定性 JSON 文本。"""

    return json.dumps(
        _normalize(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def sha256_value(value: Any) -> str:
    """计算规范 JSON 值的 SHA-256 十六进制摘要。"""

    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def state_sha256(state: Any) -> str:
    """计算一个游戏状态快照的 SHA-256 摘要。"""

    return sha256_value(state)


@dataclass(frozen=True, slots=True)
class ReplayHeader:
    """回放的版本与可复现性元数据。"""

    engine_version: str
    mode: str
    seed: int
    ruleset_hash: str
    deck_hash: str
    general_data_hash: str
    strategy_version: str
    schema_version: str = "1.0"
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("engine_version", "mode", "strategy_version"):
            object.__setattr__(
                self,
                name,
                _required_nonempty_text(getattr(self, name), name),
            )
        object.__setattr__(
            self,
            "ruleset_hash",
            _required_sha256(self.ruleset_hash, "ruleset_hash", allow_not_loaded=True),
        )
        object.__setattr__(
            self,
            "deck_hash",
            _required_sha256(self.deck_hash, "deck_hash"),
        )
        object.__setattr__(
            self,
            "general_data_hash",
            _required_sha256(
                self.general_data_hash,
                "general_data_hash",
                allow_not_loaded=True,
            ),
        )
        if isinstance(self.seed, bool) or not isinstance(self.seed, int):
            raise ReplayFormatError("回放头 seed 必须是整数，不能使用布尔值")
        if self.schema_version != "1.0":
            raise ReplayFormatError(
                f"不支持的回放 schema_version：{self.schema_version!r}；当前仅支持 1.0"
            )
        if not isinstance(self.metadata, Mapping):
            raise ReplayFormatError("回放头 metadata 必须是对象")
        normalized_metadata = _normalize(self.metadata, path="$.header.metadata")
        object.__setattr__(self, "metadata", _deep_freeze(normalized_metadata))

    def to_dict(self) -> dict[str, Any]:
        return _deep_copy_json(_normalize(
            {
                "schema_version": self.schema_version,
                "engine_version": self.engine_version,
                "mode": self.mode,
                "seed": self.seed,
                "ruleset_hash": self.ruleset_hash,
                "deck_hash": self.deck_hash,
                "general_data_hash": self.general_data_hash,
                "strategy_version": self.strategy_version,
                "metadata": self.metadata,
            }
        ))

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ReplayHeader":
        if not isinstance(value, Mapping):
            raise ReplayFormatError("回放头必须是 JSON 对象")
        try:
            required = {
                "schema_version",
                "engine_version",
                "mode",
                "seed",
                "ruleset_hash",
                "deck_hash",
                "general_data_hash",
                "strategy_version",
            }
            missing = sorted(required.difference(value))
            if missing:
                raise ReplayFormatError(f"回放头缺少字段：{', '.join(missing)}")
            allowed = required | {"metadata"}
            extra = sorted(set(value).difference(allowed))
            if extra:
                raise ReplayFormatError(f"回放头包含未知字段：{', '.join(extra)}")
            seed = value["seed"]
            if isinstance(seed, bool) or not isinstance(seed, int):
                raise ReplayFormatError("回放头 seed 必须是整数")
            metadata = value.get("metadata", {})
            if not isinstance(metadata, Mapping):
                raise ReplayFormatError("回放头 metadata 必须是对象")
            return cls(
                schema_version=value["schema_version"],
                engine_version=value["engine_version"],
                mode=value["mode"],
                seed=seed,
                ruleset_hash=value["ruleset_hash"],
                deck_hash=value["deck_hash"],
                general_data_hash=value["general_data_hash"],
                strategy_version=value["strategy_version"],
                metadata=_normalize(metadata),
            )
        except ReplayError:
            raise
        except (TypeError, ValueError) as exc:
            raise ReplayFormatError(f"回放头字段无效：{exc}") from exc


@dataclass(frozen=True, slots=True)
class ReplayEntry:
    """一项事件及其结算完成后的状态快照。"""

    index: int
    event_type: str
    payload: Any
    state_snapshot: Any
    state_sha256: str
    previous_entry_sha256: str
    entry_sha256: str

    def __post_init__(self) -> None:
        if isinstance(self.index, bool) or not isinstance(self.index, int) or self.index < 0:
            raise ReplayFormatError("回放事件 index 必须是非负整数")
        if not isinstance(self.event_type, str) or not self.event_type:
            raise ReplayFormatError("回放事件 event_type 必须是非空字符串")
        normalized_payload = _normalize(self.payload, path="$.payload")
        normalized_state = _normalize(self.state_snapshot, path="$.state_snapshot")
        object.__setattr__(self, "payload", _deep_freeze(normalized_payload))
        object.__setattr__(self, "state_snapshot", _deep_freeze(normalized_state))

    @property
    def sequence(self) -> int:
        return self.index

    def _hash_material(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "event_type": self.event_type,
            "payload": self.payload,
            "state_sha256": self.state_sha256,
            "previous_entry_sha256": self.previous_entry_sha256,
        }

    def calculate_entry_sha256(self) -> str:
        return sha256_value(self._hash_material())

    def to_dict(self) -> dict[str, Any]:
        return _deep_copy_json({
            "index": self.index,
            "event_type": self.event_type,
            "payload": self.payload,
            "state_snapshot": self.state_snapshot,
            "state_sha256": self.state_sha256,
            "previous_entry_sha256": self.previous_entry_sha256,
            "entry_sha256": self.entry_sha256,
        })

    @classmethod
    def create(
        cls,
        *,
        index: int,
        event_type: str,
        payload: Any,
        state_snapshot: Any,
        previous_entry_sha256: str,
    ) -> "ReplayEntry":
        if not event_type:
            raise ReplayFormatError("回放事件类型不能为空")
        normalized_payload = _normalize(payload, path="$.payload")
        normalized_state = _normalize(state_snapshot, path="$.state_snapshot")
        entry = cls(
            index=index,
            event_type=event_type,
            payload=normalized_payload,
            state_snapshot=normalized_state,
            state_sha256=state_sha256(normalized_state),
            previous_entry_sha256=previous_entry_sha256,
            entry_sha256="",
        )
        return cls(
            index=entry.index,
            event_type=entry.event_type,
            payload=entry.payload,
            state_snapshot=entry.state_snapshot,
            state_sha256=entry.state_sha256,
            previous_entry_sha256=entry.previous_entry_sha256,
            entry_sha256=entry.calculate_entry_sha256(),
        )

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ReplayEntry":
        if not isinstance(value, Mapping):
            raise ReplayFormatError("回放事件必须是 JSON 对象")
        required = {
            "index",
            "event_type",
            "payload",
            "state_snapshot",
            "state_sha256",
            "previous_entry_sha256",
            "entry_sha256",
        }
        missing = sorted(required.difference(value))
        if missing:
            raise ReplayFormatError(f"回放事件缺少字段：{', '.join(missing)}")
        extra = sorted(set(value).difference(required))
        if extra:
            raise ReplayFormatError(f"回放事件包含未知字段：{', '.join(extra)}")
        index = value["index"]
        if isinstance(index, bool) or not isinstance(index, int) or index < 0:
            raise ReplayFormatError("回放事件 index 必须是非负整数")
        event_type = value["event_type"]
        if not isinstance(event_type, str) or not event_type:
            raise ReplayFormatError("回放事件 event_type 必须是非空字符串")
        return cls(
            index=index,
            event_type=event_type,
            payload=_normalize(value["payload"], path="$.payload"),
            state_snapshot=_normalize(
                value["state_snapshot"], path="$.state_snapshot"
            ),
            state_sha256=str(value["state_sha256"]),
            previous_entry_sha256=str(value["previous_entry_sha256"]),
            entry_sha256=str(value["entry_sha256"]),
        )


class ReplayRecord:
    """包含哈希链的完整回放。

    ``verify_integrity`` 只验证已记录快照和事件链的完整性；它不会重新执行
    三国杀规则。规则重执行必须由权威引擎逐步产生状态，再通过
    ``iter_verified_entries(expected_states=...)`` 对照。
    """

    __slots__ = ("_header", "_entries")

    def __init__(self, header: ReplayHeader) -> None:
        if not isinstance(header, ReplayHeader):
            raise TypeError("回放 header 必须是 ReplayHeader")
        self._header = header
        self._entries: list[ReplayEntry] = []

    @property
    def header(self) -> ReplayHeader:
        return self._header

    @property
    def entries(self) -> tuple[ReplayEntry, ...]:
        """返回只读事件序列；只能通过 ``add_entry`` 追加新事件。"""

        return tuple(self._entries)

    @property
    def header_sha256(self) -> str:
        return sha256_value(self.header.to_dict())

    def add_entry(
        self, event_type: str, payload: Any, state_snapshot: Any
    ) -> ReplayEntry:
        previous = (
            self._entries[-1].entry_sha256
            if self._entries
            else self.header_sha256
        )
        entry = ReplayEntry.create(
            index=len(self._entries),
            event_type=event_type,
            payload=payload,
            state_snapshot=state_snapshot,
            previous_entry_sha256=previous,
        )
        self._entries.append(entry)
        return entry

    append = add_entry

    def _verify_entry(
        self,
        entry: ReplayEntry,
        *,
        expected_index: int,
        expected_previous: str,
        expected_state: Any | None = None,
    ) -> None:
        label = f"第 {expected_index} 步"
        if entry.index != expected_index:
            raise ReplayIntegrityError(
                f"{label}序号不连续：记录为 {entry.index}"
            )
        if entry.previous_entry_sha256 != expected_previous:
            raise ReplayIntegrityError(f"{label}前向哈希不匹配，回放顺序或回放头已被改写")
        actual_state_hash = state_sha256(entry.state_snapshot)
        if actual_state_hash != entry.state_sha256:
            raise ReplayIntegrityError(f"{label}状态 SHA-256 不匹配，状态快照可能被篡改")
        if expected_state is not None and state_sha256(expected_state) != entry.state_sha256:
            raise ReplayIntegrityError(f"{label}重放状态与记录状态不一致")
        actual_entry_hash = entry.calculate_entry_sha256()
        if actual_entry_hash != entry.entry_sha256:
            raise ReplayIntegrityError(f"{label}事件 SHA-256 不匹配，事件内容可能被篡改")

    def iter_verified_entries(
        self, expected_states: Sequence[Any] | None = None
    ) -> Iterator[ReplayEntry]:
        """按顺序校验并逐项产出事件，首个错误立即失败。"""

        if expected_states is not None and len(expected_states) != len(self._entries):
            raise ReplayIntegrityError(
                "外部状态数量与回放事件数量不一致，无法逐步校验"
            )
        previous = self.header_sha256
        for index, entry in enumerate(self._entries):
            expected_state = (
                None if expected_states is None else expected_states[index]
            )
            self._verify_entry(
                entry,
                expected_index=index,
                expected_previous=previous,
                expected_state=expected_state,
            )
            previous = entry.entry_sha256
            yield entry

    def verify_integrity(self, expected_states: Sequence[Any] | None = None) -> bool:
        tuple(self.iter_verified_entries(expected_states))
        return True

    verify = verify_integrity

    def verify_state(self, index: int, state: Any) -> bool:
        self.verify_integrity()
        if isinstance(index, bool) or not isinstance(index, int):
            raise TypeError("回放步骤序号必须是整数")
        if index < 0 or index >= len(self._entries):
            raise IndexError("回放步骤序号超出范围")
        if state_sha256(state) != self._entries[index].state_sha256:
            raise ReplayIntegrityError(f"第 {index} 步重放状态与记录状态不一致")
        return True

    def to_dict(self) -> dict[str, Any]:
        return {
            "header": self.header.to_dict(),
            "entries": [entry.to_dict() for entry in self._entries],
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ReplayRecord":
        if not isinstance(value, Mapping):
            raise ReplayFormatError("回放根节点必须是 JSON 对象")
        if "header" not in value or "entries" not in value:
            raise ReplayFormatError("回放必须包含 header 和 entries")
        extra = sorted(set(value).difference({"header", "entries"}))
        if extra:
            raise ReplayFormatError(f"回放根节点包含未知字段：{', '.join(extra)}")
        entries = value["entries"]
        if not isinstance(entries, list):
            raise ReplayFormatError("回放 entries 必须是数组")
        record = cls(header=ReplayHeader.from_dict(value["header"]))
        record._entries.extend(ReplayEntry.from_dict(entry) for entry in entries)
        record.verify_integrity()
        return record

    def to_json(self) -> str:
        self.verify_integrity()
        return canonical_json(self.to_dict())

    def to_jsonl(self) -> str:
        self.verify_integrity()
        lines = [
            canonical_json(
                {"record_type": "header", "data": self.header.to_dict()}
            )
        ]
        lines.extend(
            canonical_json({"record_type": "entry", "data": entry.to_dict()})
            for entry in self._entries
        )
        return "\n".join(lines)

    def save(self, path: str | Path, *, format: str | None = None) -> Path:
        target = Path(path)
        selected = format or ("jsonl" if target.suffix.lower() == ".jsonl" else "json")
        if selected not in {"json", "jsonl"}:
            raise ReplayFormatError("回放格式必须是 json 或 jsonl")
        content = self.to_jsonl() if selected == "jsonl" else self.to_json()
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content + "\n", encoding="utf-8")
        except OSError as exc:
            raise ReplayError(f"保存回放失败：{target}：{exc}") from exc
        return target

    def save_json(self, path: str | Path) -> Path:
        return self.save(path, format="json")

    def save_jsonl(self, path: str | Path) -> Path:
        return self.save(path, format="jsonl")

    @classmethod
    def load(cls, path: str | Path, *, format: str | None = None) -> "ReplayRecord":
        source = Path(path)
        try:
            text = source.read_text(encoding="utf-8-sig")
        except UnicodeDecodeError as exc:
            raise ReplayFormatError("回放文件不是有效的 UTF-8 文本") from exc
        except OSError as exc:
            raise ReplayError(f"读取回放失败：{source}：{exc}") from exc
        if not text.strip():
            raise ReplayFormatError("回放文件为空")
        selected = format or ("jsonl" if source.suffix.lower() == ".jsonl" else "json")
        if selected == "json":
            return cls.from_json(text)
        if selected == "jsonl":
            return cls.from_jsonl(text)
        raise ReplayFormatError("回放格式必须是 json 或 jsonl")

    @classmethod
    def load_json(cls, path: str | Path) -> "ReplayRecord":
        return cls.load(path, format="json")

    @classmethod
    def load_jsonl(cls, path: str | Path) -> "ReplayRecord":
        return cls.load(path, format="jsonl")

    @classmethod
    def from_json(cls, text: str) -> "ReplayRecord":
        try:
            value = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ReplayFormatError(
                f"回放 JSON 解析失败：第 {exc.lineno} 行第 {exc.colno} 列"
            ) from exc
        return cls.from_dict(value)

    @classmethod
    def from_jsonl(cls, text: str) -> "ReplayRecord":
        lines = [(number, line) for number, line in enumerate(text.splitlines(), 1) if line.strip()]
        if not lines:
            raise ReplayFormatError("回放 JSONL 文件为空")
        parsed: list[tuple[int, Any]] = []
        for number, line in lines:
            try:
                parsed.append((number, json.loads(line)))
            except json.JSONDecodeError as exc:
                raise ReplayFormatError(
                    f"回放 JSONL 第 {number} 行解析失败：第 {exc.colno} 列"
                ) from exc
        first_number, first = parsed[0]
        if not isinstance(first, Mapping) or first.get("record_type") != "header":
            raise ReplayFormatError(f"回放 JSONL 第 {first_number} 行必须是 header")
        first_extra = sorted(set(first).difference({"record_type", "data"}))
        if first_extra:
            raise ReplayFormatError(
                f"回放 JSONL 第 {first_number} 行包含未知字段：{', '.join(first_extra)}"
            )
        if "data" not in first:
            raise ReplayFormatError("回放 JSONL 的 header 缺少 data")
        entries: list[ReplayEntry] = []
        for number, item in parsed[1:]:
            if not isinstance(item, Mapping) or item.get("record_type") != "entry":
                raise ReplayFormatError(f"回放 JSONL 第 {number} 行必须是 entry")
            item_extra = sorted(set(item).difference({"record_type", "data"}))
            if item_extra:
                raise ReplayFormatError(
                    f"回放 JSONL 第 {number} 行包含未知字段：{', '.join(item_extra)}"
                )
            if "data" not in item:
                raise ReplayFormatError(f"回放 JSONL 第 {number} 行缺少 data")
            entries.append(ReplayEntry.from_dict(item["data"]))
        record = cls(header=ReplayHeader.from_dict(first["data"]))
        record._entries.extend(entries)
        record.verify_integrity()
        return record


__all__ = [
    "NOT_LOADED_HASH",
    "ReplayEntry",
    "ReplayError",
    "ReplayFormatError",
    "ReplayHeader",
    "ReplayIntegrityError",
    "ReplayRecord",
    "canonical_json",
    "sha256_value",
    "state_sha256",
]
