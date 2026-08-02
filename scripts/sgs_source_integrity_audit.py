"""三国杀模拟项目的只读源码防伪审计器。

本模块只读取指定目录内的 Python 源码，不会删除、改写或格式化任何文件。
它用于发现几类需要人工复核的信号：

* ``chosen = expected`` 紧接 ``assert chosen == expected`` 的自证式断言；
* 正式源码对已知外部 legacy 脚本的导入或路径引用；
* ``approximation`` / ``unsupported`` 显式状态标记。

最后一类只是审计线索，不会仅凭字段名判定实现有缺陷；文档字符串和普通注释也
不会被当作正式实现缺陷。输出不包含时间戳，并按路径和源码位置排序，便于复现与
版本对比。
"""

from __future__ import annotations

import argparse
import ast
from dataclasses import asdict, dataclass
from enum import Enum
import json
from pathlib import Path
import sys
from typing import Iterable, Iterator, Sequence


SCHEMA_VERSION = "1.0"
_IGNORED_DIRECTORY_NAMES = frozenset(
    {".venv", "__pycache__", ".pytest-temp"}
)

# 分段拼接是为了避免扫描器审计自身时，把默认规则清单误判成路径引用。
DEFAULT_LEGACY_FILENAMES = (
    "sgs_sim_engine_" + "worker.py",
    "sgs_sim_" + "aggregate.py",
    "sgs_ai_audit_" + "20260729.py",
)
_MARKER_NAMES = frozenset(
    {
        "approximation" + "_count",
        "unsupported" + "_rules",
        "approximation",
        "unsupported",
    }
)


class FindingKind(str, Enum):
    """稳定、机器可读的发现类型。"""

    SELF_CONFIRMING_ASSERTION = "self_confirming_assertion"
    LEGACY_IMPORT = "legacy_import"
    LEGACY_PATH_REFERENCE = "legacy_path_reference"
    EXPLICIT_APPROXIMATION_MARKER = "explicit_approximation_marker"
    EXPLICIT_UNSUPPORTED_MARKER = "explicit_unsupported_marker"
    SYNTAX_ERROR = "syntax_error"
    READ_ERROR = "read_error"


class FindingClassification(str, Enum):
    """区分确定缺陷与需要人工解释的审计线索。"""

    DEFECT = "defect"
    AUDIT_ITEM = "audit_item"


class SourceScope(str, Enum):
    """发现所在文件的粗粒度用途。"""

    FORMAL_SOURCE = "formal_source"
    TEST_CODE = "test_code"


@dataclass(frozen=True)
class AuditFinding:
    kind: FindingKind
    classification: FindingClassification
    scope: SourceScope
    path: str
    line: int
    column: int
    message: str
    evidence: str

    def to_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["kind"] = self.kind.value
        data["classification"] = self.classification.value
        data["scope"] = self.scope.value
        return data


@dataclass(frozen=True)
class SourceIntegrityAuditReport:
    schema_version: str
    root: str
    scanned_files: tuple[str, ...]
    findings: tuple[AuditFinding, ...]

    @property
    def defect_count(self) -> int:
        return sum(
            finding.classification is FindingClassification.DEFECT
            for finding in self.findings
        )

    @property
    def audit_item_count(self) -> int:
        return len(self.findings) - self.defect_count

    def to_dict(self) -> dict[str, object]:
        by_kind = {
            kind.value: sum(finding.kind is kind for finding in self.findings)
            for kind in FindingKind
            if any(finding.kind is kind for finding in self.findings)
        }
        return {
            "schema_version": self.schema_version,
            "root": self.root,
            "scanned_file_count": len(self.scanned_files),
            "scanned_files": list(self.scanned_files),
            "finding_count": len(self.findings),
            "defect_count": self.defect_count,
            "audit_item_count": self.audit_item_count,
            "formal_source_finding_count": sum(
                finding.scope is SourceScope.FORMAL_SOURCE
                for finding in self.findings
            ),
            "test_code_finding_count": sum(
                finding.scope is SourceScope.TEST_CODE for finding in self.findings
            ),
            "counts_by_kind": by_kind,
            "findings": [finding.to_dict() for finding in self.findings],
        }

    def to_json(self, *, pretty: bool = False) -> str:
        if pretty:
            return json.dumps(
                self.to_dict(), ensure_ascii=False, indent=2, sort_keys=True
            )
        return json.dumps(
            self.to_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )


class AuditInputError(ValueError):
    """调用方提供的审计根目录或 legacy 名称无效。"""


def _normalise_legacy_names(names: Iterable[str]) -> tuple[str, ...]:
    normalised: set[str] = set()
    for raw_name in names:
        if not isinstance(raw_name, str) or not raw_name.strip():
            raise AuditInputError("legacy 文件名必须是非空字符串")
        name = Path(raw_name.strip().replace("\\", "/")).name.casefold()
        if name in {".", ".."}:
            raise AuditInputError("legacy 文件名不能是目录标记")
        normalised.add(name)
    if not normalised:
        raise AuditInputError("至少需要提供一个 legacy 文件名")
    return tuple(sorted(normalised))


def _iter_python_files(root: Path) -> Iterator[Path]:
    candidates: list[Path] = []
    for path in root.rglob("*.py"):
        try:
            relative = path.relative_to(root)
        except ValueError:
            continue
        if any(part in _IGNORED_DIRECTORY_NAMES for part in relative.parts[:-1]):
            continue
        if path.is_file():
            candidates.append(path)
    yield from sorted(candidates, key=lambda item: item.relative_to(root).as_posix())


def _scope_for(relative_path: Path) -> SourceScope:
    lowered_parts = tuple(part.casefold() for part in relative_path.parts)
    if "tests" in lowered_parts or relative_path.name.casefold().startswith("test_"):
        return SourceScope.TEST_CODE
    return SourceScope.FORMAL_SOURCE


def _line_evidence(lines: Sequence[str], line_number: int) -> str:
    if not 1 <= line_number <= len(lines):
        return ""
    return lines[line_number - 1].strip()[:300]


def _node_evidence(lines: Sequence[str], node: ast.AST) -> str:
    start = getattr(node, "lineno", 0)
    end = getattr(node, "end_lineno", start)
    if not start or not lines:
        return ""
    snippets = [line.strip() for line in lines[start - 1 : min(end, len(lines))]]
    return " ".join(part for part in snippets if part)[:300]


def _assigned_expected_name(statement: ast.stmt) -> bool:
    if isinstance(statement, ast.Assign):
        return (
            len(statement.targets) == 1
            and isinstance(statement.targets[0], ast.Name)
            and statement.targets[0].id == "chosen"
            and isinstance(statement.value, ast.Name)
            and statement.value.id == "expected"
        )
    if isinstance(statement, ast.AnnAssign):
        return (
            isinstance(statement.target, ast.Name)
            and statement.target.id == "chosen"
            and isinstance(statement.value, ast.Name)
            and statement.value.id == "expected"
        )
    return False


def _asserts_chosen_equals_expected(statement: ast.stmt) -> bool:
    if not isinstance(statement, ast.Assert):
        return False
    test = statement.test
    if not (
        isinstance(test, ast.Compare)
        and len(test.ops) == 1
        and isinstance(test.ops[0], ast.Eq)
        and len(test.comparators) == 1
    ):
        return False
    left, right = test.left, test.comparators[0]
    return (
        isinstance(left, ast.Name)
        and left.id == "chosen"
        and isinstance(right, ast.Name)
        and right.id == "expected"
    ) or (
        isinstance(left, ast.Name)
        and left.id == "expected"
        and isinstance(right, ast.Name)
        and right.id == "chosen"
    )


def _statement_lists(tree: ast.AST) -> Iterator[list[ast.stmt]]:
    """逐一返回 AST 中的语句列表，不跨分支拼接相邻关系。"""

    for node in ast.walk(tree):
        for _field_name, value in ast.iter_fields(node):
            if isinstance(value, list) and value and all(
                isinstance(item, ast.stmt) for item in value
            ):
                yield value


def _self_confirming_findings(
    tree: ast.AST,
    *,
    relative_path: str,
    scope: SourceScope,
    lines: Sequence[str],
) -> list[AuditFinding]:
    findings: list[AuditFinding] = []
    for statements in _statement_lists(tree):
        for assignment, assertion in zip(statements, statements[1:]):
            if not (
                _assigned_expected_name(assignment)
                and _asserts_chosen_equals_expected(assertion)
            ):
                continue
            evidence = (
                f"{_node_evidence(lines, assignment)}; "
                f"{_node_evidence(lines, assertion)}"
            )
            findings.append(
                AuditFinding(
                    kind=FindingKind.SELF_CONFIRMING_ASSERTION,
                    classification=FindingClassification.DEFECT,
                    scope=scope,
                    path=relative_path,
                    line=getattr(assertion, "lineno", 0),
                    column=getattr(assertion, "col_offset", 0) + 1,
                    message=(
                        "检测到 chosen 直接取 expected 后再断言二者相等；"
                        "该断言未验证真实程序路径"
                    ),
                    evidence=evidence,
                )
            )
    return findings


def _legacy_match(value: str, legacy_names: Sequence[str]) -> str | None:
    folded = value.replace("\\", "/").casefold()
    for filename in legacy_names:
        stem = filename[:-3] if filename.endswith(".py") else filename
        if filename in folded or stem in folded:
            return filename
    return None


def _is_docstring_node(node: ast.Constant, parents: dict[ast.AST, ast.AST]) -> bool:
    parent = parents.get(node)
    if not isinstance(parent, ast.Expr):
        return False
    grandparent = parents.get(parent)
    body = getattr(grandparent, "body", None)
    return isinstance(body, list) and bool(body) and body[0] is parent


def _legacy_findings(
    tree: ast.AST,
    *,
    relative_path: str,
    scope: SourceScope,
    lines: Sequence[str],
    legacy_names: Sequence[str],
) -> list[AuditFinding]:
    findings: list[AuditFinding] = []
    seen: set[tuple[FindingKind, int, int, str]] = set()
    parents: dict[ast.AST, ast.AST] = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parents[child] = parent

    def add(node: ast.AST, kind: FindingKind, matched: str) -> None:
        line = getattr(node, "lineno", 0)
        column = getattr(node, "col_offset", 0) + 1
        key = (kind, line, column, matched)
        if key in seen:
            return
        seen.add(key)
        classification = (
            FindingClassification.DEFECT
            if scope is SourceScope.FORMAL_SOURCE
            else FindingClassification.AUDIT_ITEM
        )
        findings.append(
            AuditFinding(
                kind=kind,
                classification=classification,
                scope=scope,
                path=relative_path,
                line=line,
                column=column,
                message=f"源码引用了外部 legacy 文件：{matched}",
                evidence=_node_evidence(lines, node),
            )
        )

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                matched = _legacy_match(alias.name, legacy_names)
                if matched:
                    add(node, FindingKind.LEGACY_IMPORT, matched)
        elif isinstance(node, ast.ImportFrom) and node.module:
            matched = _legacy_match(node.module, legacy_names)
            if matched:
                add(node, FindingKind.LEGACY_IMPORT, matched)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if _is_docstring_node(node, parents):
                continue
            matched = _legacy_match(node.value, legacy_names)
            if matched:
                add(node, FindingKind.LEGACY_PATH_REFERENCE, matched)

    return findings


def _marker_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id.casefold()
    if isinstance(node, ast.Attribute):
        return node.attr.casefold()
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        value = node.value.casefold()
        return value if value in _MARKER_NAMES else None
    return None


def _marker_findings(
    tree: ast.AST,
    *,
    relative_path: str,
    scope: SourceScope,
    lines: Sequence[str],
) -> list[AuditFinding]:
    """收集代码字段标记；忽略文档字符串、注释及任意叙述文本。"""

    candidates: list[ast.AST] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Name, ast.Attribute)):
            candidates.append(node)
        elif isinstance(node, ast.keyword) and node.arg:
            candidates.append(node)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            # 只允许精确字段名；普通字符串中的说明文字不算代码标记。
            if node.value.casefold() in _MARKER_NAMES:
                candidates.append(node)

    findings: list[AuditFinding] = []
    seen: set[tuple[int, str]] = set()
    for node in candidates:
        name = node.arg.casefold() if isinstance(node, ast.keyword) else _marker_name(node)
        if name not in _MARKER_NAMES:
            continue
        line = getattr(node, "lineno", 0)
        column = getattr(node, "col_offset", 0) + 1
        # 同一行里的字段名、属性访问和同名字符串键属于同一个审计事实。
        key = (line, name)
        if key in seen:
            continue
        seen.add(key)
        kind = (
            FindingKind.EXPLICIT_APPROXIMATION_MARKER
            if name.startswith("approximation")
            else FindingKind.EXPLICIT_UNSUPPORTED_MARKER
        )
        findings.append(
            AuditFinding(
                kind=kind,
                classification=FindingClassification.AUDIT_ITEM,
                scope=scope,
                path=relative_path,
                line=line,
                column=column,
                message=(
                    f"发现显式状态标记 {name}；需结合赋值和调用链人工判断，"
                    "该标记本身不等于实现缺陷"
                ),
                evidence=_line_evidence(lines, line),
            )
        )
    return findings


def _finding_sort_key(finding: AuditFinding) -> tuple[object, ...]:
    return (
        finding.path,
        finding.line,
        finding.column,
        finding.kind.value,
        finding.evidence,
    )


def scan_python_sources(
    root: str | Path,
    *,
    legacy_filenames: Iterable[str] = DEFAULT_LEGACY_FILENAMES,
) -> SourceIntegrityAuditReport:
    """递归审计 ``root`` 内的 Python 文件并返回稳定报告。

    ``.venv``、``__pycache__`` 和 ``.pytest-temp`` 目录始终排除。读取或解析失败会成为缺陷项，
    不会被吞掉，也不会触发任何源码写入。
    """

    root_path = Path(root).resolve(strict=False)
    if not root_path.exists():
        raise AuditInputError(f"审计根目录不存在：{root_path}")
    if not root_path.is_dir():
        raise AuditInputError(f"审计根路径不是目录：{root_path}")
    legacy_names = _normalise_legacy_names(legacy_filenames)

    scanned_files: list[str] = []
    findings: list[AuditFinding] = []
    for path in _iter_python_files(root_path):
        relative = path.relative_to(root_path)
        relative_text = relative.as_posix()
        scanned_files.append(relative_text)
        scope = _scope_for(relative)
        try:
            source = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            findings.append(
                AuditFinding(
                    kind=FindingKind.READ_ERROR,
                    classification=FindingClassification.DEFECT,
                    scope=scope,
                    path=relative_text,
                    line=0,
                    column=0,
                    message=f"无法以 UTF-8 读取源码：{exc}",
                    evidence="",
                )
            )
            continue
        lines = source.splitlines()
        try:
            tree = ast.parse(source, filename=relative_text)
        except SyntaxError as exc:
            findings.append(
                AuditFinding(
                    kind=FindingKind.SYNTAX_ERROR,
                    classification=FindingClassification.DEFECT,
                    scope=scope,
                    path=relative_text,
                    line=exc.lineno or 0,
                    column=exc.offset or 0,
                    message=f"Python 语法解析失败：{exc.msg}",
                    evidence=_line_evidence(lines, exc.lineno or 0),
                )
            )
            continue

        findings.extend(
            _self_confirming_findings(
                tree,
                relative_path=relative_text,
                scope=scope,
                lines=lines,
            )
        )
        findings.extend(
            _legacy_findings(
                tree,
                relative_path=relative_text,
                scope=scope,
                lines=lines,
                legacy_names=legacy_names,
            )
        )
        # 审计器实现本身必须描述这些标记；若把自身规则词表列为项目线索，
        # 会污染默认正式源码报告。仅豁免当前实际加载的审计器文件，不按文件
        # 名泛化豁免其他源码。
        if path.resolve(strict=False) != Path(__file__).resolve(strict=False):
            findings.extend(
                _marker_findings(
                    tree,
                    relative_path=relative_text,
                    scope=scope,
                    lines=lines,
                )
            )

    return SourceIntegrityAuditReport(
        schema_version=SCHEMA_VERSION,
        root=str(root_path),
        scanned_files=tuple(scanned_files),
        findings=tuple(sorted(findings, key=_finding_sort_key)),
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="只读扫描 Python 源码中的自证断言、legacy 引用和近似标记"
    )
    parser.add_argument("root", nargs="?", default=".", help="待扫描的根目录")
    parser.add_argument(
        "--legacy-name",
        action="append",
        default=[],
        metavar="FILE",
        help="追加一个需审计的外部 legacy 文件名，可重复使用",
    )
    parser.add_argument("--pretty", action="store_true", help="缩进输出 JSON")
    parser.add_argument(
        "--fail-on-defect",
        action="store_true",
        help="发现 defect 时返回退出码 1；默认仅报告并返回 0",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    legacy_names = (*DEFAULT_LEGACY_FILENAMES, *args.legacy_name)
    try:
        report = scan_python_sources(args.root, legacy_filenames=legacy_names)
    except AuditInputError as exc:
        error = {
            "schema_version": SCHEMA_VERSION,
            "error": {"type": "input_error", "message": str(exc)},
        }
        print(
            json.dumps(error, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            file=sys.stderr,
        )
        return 2
    print(report.to_json(pretty=args.pretty))
    if args.fail_on_defect and report.defect_count:
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover - 由命令行直接调用
    raise SystemExit(main())


__all__ = [
    "AuditFinding",
    "AuditInputError",
    "DEFAULT_LEGACY_FILENAMES",
    "FindingClassification",
    "FindingKind",
    "SCHEMA_VERSION",
    "SourceIntegrityAuditReport",
    "SourceScope",
    "main",
    "scan_python_sources",
]
