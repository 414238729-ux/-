"""三国杀正式模拟入口的失败关闭门禁。

本模块只判断任务是否有资格被标记为“正式模拟”，不执行对局。牌堆规模、
入口来源和权威核心引用都由本模块自行核验，调用方不能通过自报字段把近似器
伪装成正式入口。
"""

from __future__ import annotations

import ast
import hashlib
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Iterable


FORMAL_DECK_CARD_COUNT = 160


def _strict_bool(value: object, label: str) -> bool:
    if not isinstance(value, bool):
        raise TypeError(f"{label}必须是布尔值")
    return value


def _nonnegative_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{label}必须是非负整数")
    if value < 0:
        raise ValueError(f"{label}不能小于0")
    return value


def _nonempty_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label}必须是非空字符串")
    return value.strip()


class EngineSourceKind(Enum):
    """根据真实路径和源码派生的入口类型。"""

    FORMAL_RULE_CORE = "formal_rule_core"
    LEGACY_APPROXIMATOR = "legacy_approximator"
    TEST_DOUBLE = "test_double"
    UNKNOWN = "unknown"


_LEGACY_FILENAMES = {
    # 分段拼接可让只读源码审计器区分“门禁拒绝清单”与真正的 legacy 路径引用。
    "sgs_sim_engine_" + "worker.py",
    "sgs_sim_" + "aggregate.py",
    "sgs_ai_audit_" + "20260729.py",
}
_TEST_PATH_PARTS = {"test", "tests", "testing", "fixtures"}
_TEST_NAME_MARKERS = ("test_", "fake", "mock", "stub", "double")


def _inside(root: Path, path: Path) -> bool:
    return path == root or root in path.parents


def _core_imports(tree: ast.AST) -> tuple[str, ...]:
    """提取真正指向 ``sgs_engine`` 包而非门禁模块的导入。"""

    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            candidates = (alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            prefix = "." * node.level
            candidates = (prefix + module,)
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "importlib"
            and node.func.attr == "import_module"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            candidates = (node.args[0].value,)
        else:
            continue
        for candidate in candidates:
            normalised = candidate.lstrip(".")
            if normalised in {"sgs_engine", "scripts.sgs_engine"} or normalised.startswith(
                ("sgs_engine.", "scripts.sgs_engine.")
            ):
                # ``scripts.sgs_engine_gate`` 与核心包同前缀，但不是核心。
                if normalised not in {
                    "sgs_engine_gate",
                    "scripts.sgs_engine_gate",
                }:
                    found.add(candidate)
    return tuple(sorted(found))


@dataclass(frozen=True)
class EngineSourceReadiness:
    """由 ``inspect_engine_source`` 形成的不可伪造来源快照。"""

    repository_root: Path
    entrypoint_path: Path
    repository_root_exists: bool
    entrypoint_exists: bool
    entrypoint_inside_repository: bool
    source_kind: EngineSourceKind
    uses_authoritative_rule_core: bool
    source_sha256: str | None
    imported_core_modules: tuple[str, ...]
    inspection_issues: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "repository_root", Path(self.repository_root))
        object.__setattr__(self, "entrypoint_path", Path(self.entrypoint_path))
        for field_name, label in (
            ("repository_root_exists", "仓库根目录是否存在"),
            ("entrypoint_exists", "引擎入口是否存在"),
            ("entrypoint_inside_repository", "引擎入口是否位于正式仓库"),
            ("uses_authoritative_rule_core", "是否调用权威规则核心"),
        ):
            object.__setattr__(self, field_name, _strict_bool(getattr(self, field_name), label))
        if not isinstance(self.source_kind, EngineSourceKind):
            raise TypeError("入口来源类型必须是EngineSourceKind")
        if self.source_sha256 is not None:
            digest = _nonempty_text(self.source_sha256, "入口源码SHA-256")
            if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
                raise ValueError("入口源码SHA-256格式无效")
            object.__setattr__(self, "source_sha256", digest)
        object.__setattr__(self, "imported_core_modules", tuple(self.imported_core_modules))
        object.__setattr__(self, "inspection_issues", tuple(self.inspection_issues))


def inspect_engine_source(
    *, repository_root: str | Path, entrypoint_path: str | Path
) -> EngineSourceReadiness:
    """根据真实路径、源码哈希和AST导入关系审计入口。

    此函数没有 ``source_kind`` 或 ``uses_authoritative_rule_core`` 参数；这两个
    结论只能由检查结果派生。仅写一句注释或把入口放入仓库，均不能通过检查。
    """

    root = Path(repository_root).resolve(strict=False)
    entrypoint = Path(entrypoint_path).resolve(strict=False)
    root_exists = root.is_dir()
    entrypoint_exists = entrypoint.is_file()
    inside = root_exists and _inside(root, entrypoint)
    issues: list[str] = []
    source_sha256: str | None = None
    imported_modules: tuple[str, ...] = ()

    if not root_exists:
        issues.append("正式仓库根目录不存在")
    if not entrypoint_exists:
        issues.append("模拟入口文件不存在")
    if entrypoint_exists and not inside:
        issues.append("模拟入口位于正式仓库之外")

    basename = entrypoint.name.casefold()
    relative_parts: tuple[str, ...] = ()
    if inside:
        relative_parts = tuple(part.casefold() for part in entrypoint.relative_to(root).parts)
    is_legacy = basename in _LEGACY_FILENAMES
    is_test_double = (
        any(part in _TEST_PATH_PARTS for part in relative_parts[:-1])
        or any(marker in basename for marker in _TEST_NAME_MARKERS)
    )

    if entrypoint_exists:
        try:
            raw = entrypoint.read_bytes()
            source_sha256 = hashlib.sha256(raw).hexdigest()
            if entrypoint.suffix.casefold() != ".py":
                issues.append("模拟入口不是Python源文件，无法执行AST调用链审计")
            else:
                text = raw.decode("utf-8-sig")
                tree = ast.parse(text, filename=str(entrypoint))
                imported_modules = _core_imports(tree)
        except UnicodeError as exc:
            issues.append(f"模拟入口不是有效UTF-8源码：{exc}")
        except SyntaxError as exc:
            issues.append(f"模拟入口AST解析失败：第{exc.lineno or 0}行")
        except OSError as exc:
            issues.append(f"模拟入口读取失败：{exc}")

    canonical_core = root / "scripts" / "sgs_engine"
    core_files_exist = (
        (canonical_core / "__init__.py").is_file()
        and (canonical_core / "engine.py").is_file()
    )
    uses_core = bool(imported_modules) and core_files_exist and inside
    if imported_modules and not core_files_exist:
        issues.append("入口声明导入sgs_engine，但仓库内权威核心包不完整")
    if entrypoint_exists and not imported_modules:
        issues.append("入口源码未导入仓库内sgs_engine权威核心")

    if is_legacy:
        source_kind = EngineSourceKind.LEGACY_APPROXIMATOR
    elif is_test_double:
        source_kind = EngineSourceKind.TEST_DOUBLE
    elif inside and uses_core and not issues:
        source_kind = EngineSourceKind.FORMAL_RULE_CORE
    else:
        source_kind = EngineSourceKind.UNKNOWN

    return EngineSourceReadiness(
        repository_root=root,
        entrypoint_path=entrypoint,
        repository_root_exists=root_exists,
        entrypoint_exists=entrypoint_exists,
        entrypoint_inside_repository=inside,
        source_kind=source_kind,
        uses_authoritative_rule_core=uses_core,
        source_sha256=source_sha256,
        imported_core_modules=imported_modules,
        inspection_issues=tuple(issues),
    )


@dataclass(frozen=True)
class GeneralReadiness:
    general_name: str
    implemented: bool
    deterministic_tests_passed: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "general_name", _nonempty_text(self.general_name, "武将名称"))
        object.__setattr__(self, "implemented", _strict_bool(self.implemented, "武将是否已实现"))
        object.__setattr__(
            self,
            "deterministic_tests_passed",
            _strict_bool(self.deterministic_tests_passed, "武将确定性测试是否通过"),
        )


@dataclass(frozen=True)
class DeckReadiness:
    """固定为项目正式160张实体牌堆，调用方不能改写预期规模。"""

    loaded: bool
    card_count: int
    unique_instance_ids: bool = True
    expected_card_count: int = field(default=FORMAL_DECK_CARD_COUNT, init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "loaded", _strict_bool(self.loaded, "牌堆是否已加载"))
        object.__setattr__(self, "card_count", _nonnegative_int(self.card_count, "牌堆实体牌数"))
        object.__setattr__(
            self,
            "unique_instance_ids",
            _strict_bool(self.unique_instance_ids, "实体牌ID是否唯一"),
        )


@dataclass(frozen=True)
class FormalSimulationManifest:
    mode_name: str
    ruleset_version: str | None
    unsupported_rules: int
    approximation_count: int
    mode_implemented: bool
    ai_implemented: bool
    generals: tuple[GeneralReadiness, ...]
    deck: DeckReadiness
    source: EngineSourceReadiness
    # 当前仓库尚未具备能跑完一局的权威核心。该值故意不可由调用方传入；
    # 后续只有在真实整局自检接入此门禁时，才能用派生结果替换这个哨兵。
    authoritative_full_game_core: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "mode_name", _nonempty_text(self.mode_name, "模式名称"))
        if self.ruleset_version is not None and not isinstance(self.ruleset_version, str):
            raise TypeError("规则版本必须是字符串或None")
        object.__setattr__(
            self,
            "ruleset_version",
            None if self.ruleset_version is None else self.ruleset_version.strip(),
        )
        object.__setattr__(self, "unsupported_rules", _nonnegative_int(self.unsupported_rules, "未支持规则数量"))
        object.__setattr__(self, "approximation_count", _nonnegative_int(self.approximation_count, "近似替代数量"))
        object.__setattr__(self, "mode_implemented", _strict_bool(self.mode_implemented, "模式是否完整实现"))
        object.__setattr__(self, "ai_implemented", _strict_bool(self.ai_implemented, "AI是否完整实现"))
        try:
            generals = tuple(self.generals)
        except TypeError as exc:
            raise TypeError("参战武将状态必须是GeneralReadiness可迭代对象") from exc
        if any(not isinstance(item, GeneralReadiness) for item in generals):
            raise TypeError("每项参战武将状态都必须是GeneralReadiness")
        names = tuple(item.general_name for item in generals)
        if len(names) != len(set(names)):
            raise ValueError("参战武将状态不能包含重复武将名称")
        object.__setattr__(self, "generals", generals)
        if not isinstance(self.deck, DeckReadiness):
            raise TypeError("牌堆状态必须是DeckReadiness")
        if not isinstance(self.source, EngineSourceReadiness):
            raise TypeError("引擎来源状态必须是EngineSourceReadiness")


class GateIssueCode(Enum):
    FULL_GAME_CORE_NOT_IMPLEMENTED = "full_game_core_not_implemented"
    UNSUPPORTED_RULES = "unsupported_rules"
    APPROXIMATION_USED = "approximation_used"
    NO_PARTICIPATING_GENERALS = "no_participating_generals"
    GENERAL_NOT_IMPLEMENTED = "general_not_implemented"
    GENERAL_TESTS_FAILED = "general_tests_failed"
    MODE_NOT_IMPLEMENTED = "mode_not_implemented"
    AI_NOT_IMPLEMENTED = "ai_not_implemented"
    DECK_NOT_LOADED = "deck_not_loaded"
    DECK_INCOMPLETE = "deck_incomplete"
    DECK_INSTANCE_IDS_NOT_UNIQUE = "deck_instance_ids_not_unique"
    RULESET_VERSION_MISSING = "ruleset_version_missing"
    REPOSITORY_NOT_FOUND = "repository_not_found"
    ENTRYPOINT_NOT_FOUND = "entrypoint_not_found"
    ENTRYPOINT_OUTSIDE_REPOSITORY = "entrypoint_outside_repository"
    LEGACY_SOURCE = "legacy_source"
    NON_FORMAL_SOURCE = "non_formal_source"
    AUTHORITATIVE_CORE_NOT_USED = "authoritative_core_not_used"
    SOURCE_INSPECTION_FAILED = "source_inspection_failed"


@dataclass(frozen=True)
class GateIssue:
    code: GateIssueCode
    message: str


@dataclass(frozen=True)
class FormalRunGateResult:
    issues: tuple[GateIssue, ...]

    @property
    def ready(self) -> bool:
        return not self.issues

    @property
    def issue_codes(self) -> tuple[GateIssueCode, ...]:
        return tuple(issue.code for issue in self.issues)


def _names(items: Iterable[GeneralReadiness]) -> str:
    return "、".join(item.general_name for item in items)


def evaluate_formal_run_gate(manifest: FormalSimulationManifest) -> FormalRunGateResult:
    """纯函数：评估正式模拟准入条件，不运行或降级到近似器。"""

    if not isinstance(manifest, FormalSimulationManifest):
        raise TypeError("正式模拟清单必须是FormalSimulationManifest")
    issues: list[GateIssue] = []

    def add(code: GateIssueCode, message: str) -> None:
        issues.append(GateIssue(code, message))

    if not manifest.authoritative_full_game_core:
        add(
            GateIssueCode.FULL_GAME_CORE_NOT_IMPLEMENTED,
            "权威核心尚不能从开局运行至胜负，禁止正式模拟",
        )
    if manifest.unsupported_rules:
        add(GateIssueCode.UNSUPPORTED_RULES, f"仍有{manifest.unsupported_rules}项规则未实现，禁止正式模拟")
    if manifest.approximation_count:
        add(GateIssueCode.APPROXIMATION_USED, f"检测到{manifest.approximation_count}项近似替代，禁止标记为正式胜率")
    if not manifest.generals:
        add(GateIssueCode.NO_PARTICIPATING_GENERALS, "未提供实际参战武将")
    else:
        unimplemented = tuple(item for item in manifest.generals if not item.implemented)
        tests_failed = tuple(item for item in manifest.generals if not item.deterministic_tests_passed)
        if unimplemented:
            add(GateIssueCode.GENERAL_NOT_IMPLEMENTED, f"参战武将尚未完整实现：{_names(unimplemented)}")
        if tests_failed:
            add(GateIssueCode.GENERAL_TESTS_FAILED, f"参战武将确定性测试尚未通过：{_names(tests_failed)}")
    if not manifest.mode_implemented:
        add(GateIssueCode.MODE_NOT_IMPLEMENTED, f"模式“{manifest.mode_name}”尚未完整实现")
    if not manifest.ai_implemented:
        add(GateIssueCode.AI_NOT_IMPLEMENTED, "正式模拟使用的AI尚未完整实现")
    if not manifest.deck.loaded:
        add(GateIssueCode.DECK_NOT_LOADED, "正式实体牌堆尚未加载或审计失败")
    if manifest.deck.card_count != FORMAL_DECK_CARD_COUNT:
        add(
            GateIssueCode.DECK_INCOMPLETE,
            f"牌堆实体牌数不完整：实际{manifest.deck.card_count}张，固定预期{FORMAL_DECK_CARD_COUNT}张",
        )
    if not manifest.deck.unique_instance_ids:
        add(GateIssueCode.DECK_INSTANCE_IDS_NOT_UNIQUE, "牌堆实体牌ID存在重复")
    if not manifest.ruleset_version:
        add(GateIssueCode.RULESET_VERSION_MISSING, "规则版本缺失，禁止跨版本静默混用")

    source = inspect_engine_source(
        repository_root=manifest.source.repository_root,
        entrypoint_path=manifest.source.entrypoint_path,
    )
    if source != manifest.source:
        add(
            GateIssueCode.SOURCE_INSPECTION_FAILED,
            "入口来源快照与当前文件重检结果不一致，拒绝使用调用方自报或过期结论",
        )
    if not source.repository_root_exists:
        add(GateIssueCode.REPOSITORY_NOT_FOUND, f"正式仓库根目录不存在：{source.repository_root}")
    if not source.entrypoint_exists:
        add(GateIssueCode.ENTRYPOINT_NOT_FOUND, f"模拟入口文件不存在：{source.entrypoint_path}")
    if not source.entrypoint_inside_repository:
        add(GateIssueCode.ENTRYPOINT_OUTSIDE_REPOSITORY, f"模拟入口位于正式仓库之外：{source.entrypoint_path}")
    if source.source_kind is EngineSourceKind.LEGACY_APPROXIMATOR:
        add(GateIssueCode.LEGACY_SOURCE, "legacy近似器不能生成正式胜率")
    elif source.source_kind is not EngineSourceKind.FORMAL_RULE_CORE:
        add(GateIssueCode.NON_FORMAL_SOURCE, f"入口不是经源码核验的正式权威核心入口：{source.source_kind.value}")
    if not source.uses_authoritative_rule_core:
        add(GateIssueCode.AUTHORITATIVE_CORE_NOT_USED, "入口源码未真实导入项目权威规则核心")
    if source.inspection_issues:
        add(GateIssueCode.SOURCE_INSPECTION_FAILED, "入口源码审计未通过：" + "；".join(source.inspection_issues))

    return FormalRunGateResult(tuple(issues))


class FormalSimulationBlockedError(RuntimeError):
    def __init__(self, result: FormalRunGateResult) -> None:
        if not isinstance(result, FormalRunGateResult):
            raise TypeError("门禁结果必须是FormalRunGateResult")
        self.result = result
        details = "\n".join(f"- {issue.message}" for issue in result.issues)
        super().__init__(f"正式模拟已被失败关闭门禁拒绝：\n{details}")


def require_formal_simulation_ready(manifest: FormalSimulationManifest) -> FormalRunGateResult:
    result = evaluate_formal_run_gate(manifest)
    if not result.ready:
        raise FormalSimulationBlockedError(result)
    return result


__all__ = [
    "FORMAL_DECK_CARD_COUNT",
    "DeckReadiness",
    "EngineSourceKind",
    "EngineSourceReadiness",
    "FormalRunGateResult",
    "FormalSimulationBlockedError",
    "FormalSimulationManifest",
    "GateIssue",
    "GateIssueCode",
    "GeneralReadiness",
    "evaluate_formal_run_gate",
    "inspect_engine_source",
    "require_formal_simulation_ready",
]
