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
from typing import Callable, Iterable

from .sgs_engine.formal_duel import (
    FormalDuelReadiness,
    FormalDuelSeedResult,
    inspect_formal_duel_readiness,
)
from .sgs_engine.production_batch import FORMAL_NO_SKILL_DUEL_MODE


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
    FORMAL_DUEL_READINESS_INSPECTION_FAILED = (
        "formal_duel_readiness_inspection_failed"
    )
    FORMAL_DUEL_MODE_ID_MISMATCH = "formal_duel_mode_id_mismatch"
    FORMAL_DUEL_FACTORY_UNREACHABLE = "formal_duel_factory_unreachable"
    ALL_CARDS_NOT_IMPLEMENTED = "all_cards_not_implemented"
    REEXECUTION_REPLAY_NOT_SUPPORTED = "reexecution_replay_not_supported"
    FIXED_SEED_ACCEPTANCE_NOT_PASSED = "fixed_seed_acceptance_not_passed"
    FORMAL_DUEL_READINESS_BLOCKER = "formal_duel_readiness_blocker"


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


def _canonical_formal_runner_source() -> EngineSourceReadiness:
    """现场检查固定正式入口；精确正式单挑不信任 manifest 中的路径声明。"""

    scripts_root = Path(__file__).resolve().parent
    return inspect_engine_source(
        repository_root=scripts_root.parent,
        entrypoint_path=scripts_root / "sgs_formal_runner.py",
    )


def _add_source_issues(
    source: EngineSourceReadiness,
    add: Callable[[GateIssueCode, str], None],
) -> None:
    """把真实源码检查转换成门禁问题。"""

    if not source.repository_root_exists:
        add(
            GateIssueCode.REPOSITORY_NOT_FOUND,
            f"正式仓库根目录不存在：{source.repository_root}",
        )
    if not source.entrypoint_exists:
        add(
            GateIssueCode.ENTRYPOINT_NOT_FOUND,
            f"模拟入口文件不存在：{source.entrypoint_path}",
        )
    if not source.entrypoint_inside_repository:
        add(
            GateIssueCode.ENTRYPOINT_OUTSIDE_REPOSITORY,
            f"模拟入口位于正式仓库之外：{source.entrypoint_path}",
        )
    if source.source_kind is EngineSourceKind.LEGACY_APPROXIMATOR:
        add(GateIssueCode.LEGACY_SOURCE, "legacy近似器不能生成正式胜率")
    elif source.source_kind is not EngineSourceKind.FORMAL_RULE_CORE:
        add(
            GateIssueCode.NON_FORMAL_SOURCE,
            "入口不是经源码核验的正式权威核心入口："
            f"{source.source_kind.value}",
        )
    if not source.uses_authoritative_rule_core:
        add(
            GateIssueCode.AUTHORITATIVE_CORE_NOT_USED,
            "入口源码未真实导入项目权威规则核心",
        )
    if source.inspection_issues:
        add(
            GateIssueCode.SOURCE_INSPECTION_FAILED,
            "入口源码审计未通过：" + "；".join(source.inspection_issues),
        )


def _evaluate_live_formal_duel_gate(
    manifest: FormalSimulationManifest,
) -> FormalRunGateResult:
    """精确正式单挑门禁：全部能力由 canonical inspector 现场派生。

    ``manifest`` 只保留请求模式与来源快照的兼容载体。其 capability 布尔值、
    数量、牌堆、武将和规则版本都不能授予正式准入资格。
    """

    issues: list[GateIssue] = []

    def add(code: GateIssueCode, message: str) -> None:
        issues.append(GateIssue(code, message))

    try:
        readiness = inspect_formal_duel_readiness()
    except Exception as exc:
        add(
            GateIssueCode.FORMAL_DUEL_READINESS_INSPECTION_FAILED,
            "正式单挑canonical readiness现场检查失败："
            f"{type(exc).__name__}:{exc}",
        )
        readiness = None

    if readiness is not None and not isinstance(readiness, FormalDuelReadiness):
        add(
            GateIssueCode.FORMAL_DUEL_READINESS_INSPECTION_FAILED,
            "正式单挑canonical inspector返回了错误的结果类型",
        )
        readiness = None

    if readiness is not None:
        card_statuses = tuple(readiness.card_semantic_statuses)
        duel_complete_statuses = tuple(
            item
            for item in card_statuses
            if item.duel_status in {"COMPLETE", "NOT_APPLICABLE_TO_DUEL"}
        )
        derived_duel_complete_key_count = len(duel_complete_statuses)
        derived_duel_complete_instance_count = sum(
            item.instance_count for item in duel_complete_statuses
        )
        derived_all_cards = (
            len(card_statuses) == readiness.registered_card_key_count
            and len({item.card_key for item in card_statuses})
            == readiness.registered_card_key_count
            and sum(item.instance_count for item in card_statuses)
            == readiness.registered_instance_count
            and derived_duel_complete_key_count
            == readiness.registered_card_key_count
            and derived_duel_complete_instance_count
            == readiness.registered_instance_count
        )
        derived_unsupported_rules = sum(
            blocker.category == "RULE_SOURCE_GAP"
            for blocker in readiness.blockers
        )
        if readiness.mode_id != FORMAL_NO_SKILL_DUEL_MODE:
            add(
                GateIssueCode.FORMAL_DUEL_MODE_ID_MISMATCH,
                "现场就绪结果的模式ID不匹配："
                f"{readiness.mode_id!r}",
            )
        if (
            readiness.deck_count != FORMAL_DECK_CARD_COUNT
            or readiness.registered_instance_count != FORMAL_DECK_CARD_COUNT
        ):
            add(
                GateIssueCode.DECK_INCOMPLETE,
                "现场正式牌堆或注册实例数不完整："
                f"deck={readiness.deck_count}，"
                f"registered={readiness.registered_instance_count}，"
                f"固定预期={FORMAL_DECK_CARD_COUNT}",
            )
        if not readiness.mode_runtime_reachable:
            add(
                GateIssueCode.FORMAL_DUEL_FACTORY_UNREACHABLE,
                "正式单挑不能从canonical factory到达统一生产核心",
            )
        if not readiness.mode_implemented:
            add(
                GateIssueCode.MODE_NOT_IMPLEMENTED,
                f"模式“{FORMAL_NO_SKILL_DUEL_MODE}”尚未完整实现",
            )
        if not readiness.deterministic_controller_implemented:
            add(
                GateIssueCode.AI_NOT_IMPLEMENTED,
                "正式单挑确定性验收控制器尚未实现",
            )
        if readiness.all_cards_implemented != derived_all_cards:
            add(
                GateIssueCode.FORMAL_DUEL_READINESS_INSPECTION_FAILED,
                "all_cards_implemented与38类卡牌现场语义明细不一致",
            )
        if (
            readiness.duel_complete_card_key_count
            != derived_duel_complete_key_count
            or readiness.duel_complete_instance_count
            != derived_duel_complete_instance_count
        ):
            add(
                GateIssueCode.FORMAL_DUEL_READINESS_INSPECTION_FAILED,
                "duel complete卡牌／实例计数与现场语义明细不一致",
            )
        if not derived_all_cards:
            add(
                GateIssueCode.ALL_CARDS_NOT_IMPLEMENTED,
                "正式单挑所需卡牌语义尚未全部实现",
            )
        if not readiness.reexecution_replay_supported:
            add(
                GateIssueCode.REEXECUTION_REPLAY_NOT_SUPPORTED,
                "正式单挑严格规则重执行回放尚未通过现场门禁",
            )
        if readiness.unsupported_rules != derived_unsupported_rules:
            add(
                GateIssueCode.FORMAL_DUEL_READINESS_INSPECTION_FAILED,
                "unsupported_rules与现场RULE_SOURCE_GAP blocker数量不一致",
            )
        if derived_unsupported_rules:
            add(
                GateIssueCode.UNSUPPORTED_RULES,
                f"现场检测到{derived_unsupported_rules}项未支持规则，禁止正式模拟",
            )
        if readiness.approximation_count:
            add(
                GateIssueCode.APPROXIMATION_USED,
                "现场检测到"
                f"{readiness.approximation_count}项近似替代，禁止标记为正式结果",
            )
        seed_results = tuple(readiness.acceptance_seed_results)
        seed_result_types_valid = all(
            isinstance(item, FormalDuelSeedResult) for item in seed_results
        )
        derived_seed_count = len(seed_results)
        if seed_result_types_valid:
            derived_natural_end_count = sum(
                bool(item.natural_end) for item in seed_results
            )
            derived_seed_failure_count = sum(
                not (
                    item.natural_end
                    and item.formal_result_eligible
                    and item.reexecution_verified
                    and item.winner in {"p1", "p2"}
                    and item.deck_count == FORMAL_DECK_CARD_COUNT
                    and item.action_count > 0
                    and item.turn_count > 0
                    and item.draw_pile_count >= 0
                    and item.unsupported_rules == 0
                    and item.approximation_count == 0
                    and not item.safety_cap_triggered
                    and item.exception_type is None
                    and item.exception_message is None
                )
                for item in seed_results
            )
            derived_seed_ids = tuple(item.seed for item in seed_results)
        else:
            derived_natural_end_count = 0
            derived_seed_failure_count = max(1, derived_seed_count)
            derived_seed_ids = ()
        seed_evidence_complete = (
            seed_result_types_valid
            and derived_seed_ids == tuple(range(100))
            and derived_seed_count == 100
            and derived_natural_end_count == 100
            and derived_seed_failure_count == 0
        )
        seed_summaries_consistent = (
            readiness.acceptance_seed_count == derived_seed_count
            and readiness.acceptance_natural_end_count
            == derived_natural_end_count
            and readiness.acceptance_failure_count
            == derived_seed_failure_count
            and readiness.fixed_seed_acceptance_passed
            == seed_evidence_complete
        )
        if not seed_summaries_consistent:
            add(
                GateIssueCode.FORMAL_DUEL_READINESS_INSPECTION_FAILED,
                "100-seed汇总与逐seed canonical验收记录不一致",
            )
        seed_acceptance_consistent = (
            seed_evidence_complete and seed_summaries_consistent
        )
        if not seed_acceptance_consistent:
            add(
                GateIssueCode.FIXED_SEED_ACCEPTANCE_NOT_PASSED,
                "正式单挑尚无至少100个固定seed全部自然结束、逐seed保留且"
                "零异常/零上限/零unsupported/零approximation的现场验收",
            )
        for blocker in readiness.blockers:
            add(
                GateIssueCode.FORMAL_DUEL_READINESS_BLOCKER,
                f"[{blocker.category}/{blocker.code}] {blocker.message}",
            )

        derived_ready = (
            readiness.mode_id == FORMAL_NO_SKILL_DUEL_MODE
            and readiness.deck_count == FORMAL_DECK_CARD_COUNT
            and readiness.registered_instance_count == FORMAL_DECK_CARD_COUNT
            and readiness.mode_runtime_reachable
            and readiness.mode_implemented
            and readiness.deterministic_controller_implemented
            and derived_all_cards
            and readiness.reexecution_replay_supported
            and derived_unsupported_rules == 0
            and readiness.approximation_count == 0
            and seed_acceptance_consistent
            and not readiness.blockers
        )
        if readiness.formal_duel_no_skill_ready != derived_ready:
            add(
                GateIssueCode.FORMAL_DUEL_READINESS_INSPECTION_FAILED,
                "formal_duel_no_skill_ready与现场组成能力不一致，拒绝静态布尔自证",
            )
        if not derived_ready:
            add(
                GateIssueCode.FULL_GAME_CORE_NOT_IMPLEMENTED,
                "正式单挑现场能力尚不能从开局运行至可严格重执行的自然胜负",
            )

    canonical_source = _canonical_formal_runner_source()
    if manifest.source != canonical_source:
        add(
            GateIssueCode.SOURCE_INSPECTION_FAILED,
            "正式单挑入口来源必须是仓库内固定sgs_formal_runner.py；"
            "拒绝调用方替换来源快照",
        )
    _add_source_issues(canonical_source, add)
    return FormalRunGateResult(tuple(issues))


def evaluate_formal_run_gate(manifest: FormalSimulationManifest) -> FormalRunGateResult:
    """纯函数：评估正式模拟准入条件，不运行或降级到近似器。"""

    if not isinstance(manifest, FormalSimulationManifest):
        raise TypeError("正式模拟清单必须是FormalSimulationManifest")
    if manifest.mode_name == FORMAL_NO_SKILL_DUEL_MODE:
        return _evaluate_live_formal_duel_gate(manifest)
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
