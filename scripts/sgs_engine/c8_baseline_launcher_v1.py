# -*- coding: utf-8 -*-
"""C8 baseline 原生身份和一次性 detached natural 启动；默认只做 dry-run。"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys

from . import c8_timed_8p_full_game_contract_v1 as contract
from . import c8_timed_8p_full_game_runner_v1 as runner
from . import c8_timed_8p_full_game_production_replay_v1 as g3
from . import c8_timed_replay_version_compatibility_v1 as compatibility

ALLOWED_BASELINE_CELLS = tuple(c.cell_id for c in contract.CANONICAL_BASELINE_CELLS_V1)
CREATE_FLAGS = 0x00000008 | 0x00000200 | 0x01000000
_MODULE = "scripts.sgs_engine.c8_baseline_launcher_v1"
_SHA = re.compile(r"[0-9a-f]{64}")
_ATTEMPT = re.compile(r"attempt-[0-9]{3}")


def _root() -> Path:
    return Path(__file__).resolve().parents[2]


def _hash(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def _equal(actual: object, expected: object, label: str) -> None:
    if contract.canonical_json_bytes_v1(actual) != contract.canonical_json_bytes_v1(expected):
        raise ValueError(label + "不匹配")


def baseline_cell_v1(cell_id: str, seed: int):
    cell = contract.FullGameCellRefV1(cell_id, contract.C8_G1_BASE_MODE_ID, seed)
    if cell not in contract.CANONICAL_BASELINE_CELLS_V1:
        raise ValueError("不支持的baseline cell；sentinel需要独立正式入口")
    return cell


def construct_baseline_identity_v1(*, cell_id: str, seed: int) -> dict:
    """仅构造正式 step-0 session；不调用 step、natural 或 replay worker。"""
    compatibility.reject_recording_v1()
    cell = baseline_cell_v1(cell_id, seed)
    shared = g3.current_c8_g3_development_snapshot_v1(_root())
    run_label = cell.cell_id.lower() + "-s" + str(seed)
    session = runner.construct_baseline_session_identity_v1(seed=seed, run_label=run_label, cell_id=cell_id)
    execution = runner.construct_timed_execution_identity_v1(repo_root=_root(), session_binding_identity=session["session_binding_identity"],
        seed=seed, run_label=run_label, max_steps=4000, max_windows=8192)
    seed_material = {"schema": "C8BaselineSeedInputIdentityV1", "cell": cell.to_dict(),
                     "session_binding_identity": session["session_binding_identity"]}
    material = {
        "schema": "C8BaselineExecutionIdentityV1", "cell_id": cell_id, "seed": seed,
        "run_label": run_label,
        "shared_implementation_identity": contract.identity_v1(shared),
        "g3_current_implementation_identity": shared["current_c8_implementation_identity"],
        "global_source_identity": shared["global_source_identity"],
        "g1_identity": shared["prior"]["prior"]["current_c8_implementation_identity"],
        "g2_identity": shared["prior"]["current_c8_implementation_identity"],
        "driver_identity": contract.C8_G1_DRIVER_POLICY_IDENTITY,
        "execution_order_profile": execution["construction"]["execution_order_profile"],
        "seed_specific_input_identity": contract.identity_v1(seed_material),
        **session,
        "cell_execution_identity": execution["cell_execution_identity"],
        # G1 public ordinal progress formally uses cell execution as run binding.
        "run_binding_identity": execution["cell_execution_identity"],
        "construction": execution["construction"],
    }
    return {**material, "identity": contract.identity_v1(material)}


def validate_baseline_identity_v1(value: dict, *, cell_id: str, seed: int) -> dict:
    expected = construct_baseline_identity_v1(cell_id=cell_id, seed=seed)
    _equal(value, expected, "正式shared/cell身份材料")
    return expected


def _plain_path(value: str) -> Path:
    if type(value) is not str or not value:
        raise ValueError("路径必须是非空绝对路径字符串")
    path = Path(value)
    if not path.is_absolute() or ".." in path.parts:
        raise ValueError("拒绝相对路径或父目录跳转")
    for part in (path, *path.parents):
        if part.is_symlink() or part.is_junction():
            raise ValueError("拒绝symlink/junction路径")
    return path.resolve()


def load_release_v1(path: Path, *, expected_sha256: str) -> dict:
    """独立命令参数提供可信 pin；不从 release 自述 hash 获取信任。"""
    if type(expected_sha256) is not str or not _SHA.fullmatch(expected_sha256):
        raise ValueError("release必须由独立canonical SHA256 pin绑定")
    _equal(_hash(path), expected_sha256, "release独立pin")
    value = compatibility.strict_json(path.read_bytes())
    keys = {"schema", "repo_root", "source_sha256", "shared_implementation_identity",
            "interpreter", "interpreter_sha256", "execution_order_profile", "run_parent",
            "harness_path", "harness_sha256", "external_source_sha256"}
    if set(value) != keys or value["schema"] != "C8BaselineLaunchReleaseV1":
        raise ValueError("未知或不完整release材料")
    _equal(str(_plain_path(value["repo_root"])), str(_root()), "release仓库")
    source = value["source_sha256"]
    if type(source) is not dict or not source:
        raise ValueError("缺少固定源码清单")
    inventory = subprocess.check_output(["git", "--no-optional-locks", "-c",
        "safe.directory=" + str(_root()), "ls-files", "-z", "--cached", "--others",
        "--exclude-standard"], cwd=_root(), stderr=subprocess.PIPE).decode("utf-8")
    _equal(sorted(source), sorted(set(filter(None, inventory.split("\0")))), "完整源码清单")
    for relative, digest in source.items():
        candidate = _root() / relative
        if not candidate.resolve().is_relative_to(_root()):
            raise ValueError("源码清单越界")
        _equal(_hash(candidate), digest, "共享源码 " + relative)
    if type(value["external_source_sha256"]) is not dict:
        raise ValueError("harness依赖必须为固定清单")
    for absolute, digest in value["external_source_sha256"].items():
        _equal(_hash(_plain_path(absolute)), digest, "harness固定依赖")
    harness = _plain_path(value["harness_path"])
    _equal(_hash(harness), value["harness_sha256"], "harness源码")
    if value["external_source_sha256"].get(str(harness)) != value["harness_sha256"]:
        raise ValueError("harness入口未纳入清单")
    _equal(str(_plain_path(value["interpreter"])), str(Path(sys.executable).resolve()), "当前解释器")
    _equal(_hash(Path(sys.executable)), value["interpreter_sha256"], "解释器hash")
    runner.validate_execution_order_profile_v1(value["execution_order_profile"])
    if os.environ.get("PYTHONDONTWRITEBYTECODE") != "1" or not sys.dont_write_bytecode:
        raise ValueError("必须在启动前设置PYTHONDONTWRITEBYTECODE=1")
    shared = g3.current_c8_g3_development_snapshot_v1(_root())
    _equal(contract.identity_v1(shared), value["shared_implementation_identity"], "共享implementation")
    parent = _plain_path(value["run_parent"])
    if parent.is_relative_to(_root()) or _root().is_relative_to(parent):
        raise ValueError("run parent必须在repo外且不能包含repo")
    return value


def _run_root(release: dict, cell_id: str, artifact_root: str, *, fresh: bool) -> Path:
    root = _plain_path(artifact_root)
    parent = _plain_path(release["run_parent"])
    if root.parent != parent / cell_id or not _ATTEMPT.fullmatch(root.name):
        raise ValueError("artifact root必须为专属run parent/cell_id/attempt-NNN")
    if fresh and root.exists():
        raise ValueError("拒绝复用已有artifact/proof/run root")
    return root


def launch_plan_v1(*, release_path: Path, release_sha256: str, cell_id: str,
                   seed: int, artifact_root: str) -> dict:
    return _launch_plan(release_path=release_path, release_sha256=release_sha256,
        cell_id=cell_id, seed=seed, artifact_root=artifact_root, fresh=True)


def _launch_plan(*, release_path: Path, release_sha256: str, cell_id: str,
                 seed: int, artifact_root: str, fresh: bool) -> dict:
    release = load_release_v1(release_path, expected_sha256=release_sha256)
    baseline_cell_v1(cell_id, seed)
    if seed == contract.C8_G1_BASELINE_SEEDS[0]:
        raise ValueError("已封存的baseline首cell禁止重新启动")
    root = _run_root(release, cell_id, artifact_root, fresh=fresh)
    identities = construct_baseline_identity_v1(cell_id=cell_id, seed=seed)
    _equal(identities["shared_implementation_identity"], release["shared_implementation_identity"], "launch共享身份")
    action = cell_id.replace("-", "_") + "_SEED" + str(seed) + "_NATURAL_FASTPATH_V2"
    common = [release["interpreter"], "-B", "-m", _MODULE,
        "--release", str(release_path.resolve()), "--release-sha256", release_sha256,
        "--cell-id", cell_id, "--seed", str(seed), "--artifact-root", str(root)]
    return {"schema": "C8BaselineLaunchPlanV1", "status": "DRY_RUN_NOT_STARTED",
        "release_path": str(release_path.resolve()), "release_sha256": release_sha256,
        "cell_id": cell_id, "seed": seed, "root": str(root), "identities": identities,
        "launch_command": common + ["--launch-natural", "--authorization", action],
        "owner_command": common + ["--owner", "--authorization", action],
        "authorization": action, "cwd": str(_root()),
        "environment": {"PYTHONHASHSEED": "0", "PYTHONDONTWRITEBYTECODE": "1"},
        "interpreter": release["interpreter"], "interpreter_sha256": release["interpreter_sha256"],
        "harness": {"path": release["harness_path"], "sha256": release["harness_sha256"], "scope": "REPORT_ONLY"},
        "detached_owner": {"creationflags": CREATE_FLAGS, "close_fds": True,
            "stdin": "DEVNULL", "fallback": "FORBIDDEN", "wait": False},
        "limits": {"max_steps": 4000, "max_windows": 8192, "timeout_chain": 8},
        "full_game": True, "test_only": False, "resume": False, "retry": False,
        "natural_started": False, "pid": None}


def _write_new(path: Path, value: dict) -> None:
    with path.open("xb") as handle:
        handle.write(contract.canonical_json_bytes_v1(value))
        handle.flush()
        os.fsync(handle.fileno())


def _load_harness(release: dict):
    path = Path(release["harness_path"])
    sys.path.insert(0, str(path.parent))
    spec = importlib.util.spec_from_file_location("c8_baseline_report_only_harness", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def detached_launch_v1(plan: dict, *, authorization: str) -> dict:
    expected = launch_plan_v1(release_path=Path(plan["release_path"]),
        release_sha256=plan["release_sha256"], cell_id=plan["cell_id"],
        seed=plan["seed"], artifact_root=plan["root"])
    _equal(plan, expected, "启动计划全部材料")
    _equal(authorization, plan["authorization"], "下一任务exact授权")
    if os.name != "nt":
        raise ValueError("detached owner仅支持已验证Windows平台")
    root = Path(plan["root"])
    root.mkdir(parents=True, exist_ok=False)
    (root / "private").mkdir()
    _write_new(root / "LAUNCH_PLAN.json", plan)
    env = {**os.environ, **plan["environment"]}
    with (root / "private/stdout.log").open("xb") as out, (root / "private/stderr.log").open("xb") as err:
        child = subprocess.Popen(plan["owner_command"], cwd=plan["cwd"], env=env,
            stdin=subprocess.DEVNULL, stdout=out, stderr=err, close_fds=True, creationflags=CREATE_FLAGS)
    receipt = {"pid": child.pid, "parent_pid": os.getpid(), "root": str(root),
               "cell_id": plan["cell_id"], "seed": plan["seed"], "plan_identity": contract.identity_v1(plan)}
    _write_new(root / "PROCESS_LAUNCH.json", receipt)
    return receipt


def natural_owner_v1(args) -> int:
    release = load_release_v1(args.release, expected_sha256=args.release_sha256)
    baseline_cell_v1(args.cell_id, args.seed)
    if args.seed == contract.C8_G1_BASELINE_SEEDS[0]:
        raise ValueError("封存cell不可启动owner")
    root = _run_root(release, args.cell_id, args.artifact_root, fresh=False)
    plan = compatibility.strict_json((root / "LAUNCH_PLAN.json").read_bytes())
    expected = _launch_plan(release_path=args.release, release_sha256=args.release_sha256,
        cell_id=args.cell_id, seed=args.seed, artifact_root=args.artifact_root, fresh=False)
    _equal(plan, expected, "owner启动计划全部材料")
    identities = validate_baseline_identity_v1(plan["identities"], cell_id=args.cell_id, seed=args.seed)
    _equal([plan["root"], plan["cell_id"], plan["seed"]], [str(root), args.cell_id, args.seed], "owner cell/run绑定")
    action = args.cell_id.replace("-", "_") + "_SEED" + str(args.seed) + "_NATURAL_FASTPATH_V2"
    _equal(args.authorization, action, "owner exact授权")
    _write_new(root / "SESSION_CLAIM.json", {"cell_id": args.cell_id, "seed": args.seed,
        "once_only": True, "step_start": 0, "resume": False, "identities": identities})
    harness = _load_harness(release)
    io = harness.DurableIO()
    obs = harness.ObserverV2(root, identity=identities, io=io)
    bundle = None
    try:
        bundle = runner.create_canonical_session_bundle_v1(seed=args.seed, run_label=identities["run_label"],
            baseline_cell_id=args.cell_id)
        io.write(root / "private/PROCESS_METADATA.json", {"pid": os.getpid(), "parent_pid": os.getppid(),
            "command": [sys.executable] + sys.argv, "identities": identities})
        obs.install()
        sink = harness.LightweightDiagnosticSinkV2(root / "diagnostics", obs)
        timed = runner._execute_timed_v3(repo_root=_root(), bundle=bundle, seed=args.seed,
            max_steps=4000, max_windows=8192, run_label=identities["run_label"],
            full_game=True, test_only=False, test_only_factory=None,
            expected_initial_record=None, diagnostic_sink=sink)
        obs.stop()
        if obs.fatal:
            raise RuntimeError("report-only observer发生致命写入错误")
        _equal(timed["cell_execution_identity"], identities["cell_execution_identity"], "natural实际cell identity")
        receipt = obs.terminal_dump(timed)
        if receipt is None:
            raise OSError("terminal report-only dump失败")
        io.write(root / "RUN_RESULT.json", {"status": "FORMAL_RUNNER_TERMINAL_OBSERVED_PENDING_SEPARATE_PROOF",
            "cell_id": args.cell_id, "seed": args.seed, "terminal_evidence": receipt,
            "accepted_steps": timed["completed_production_steps"], "windows": timed["completed_windows"],
            "cold_replay": "NOT_RUN", "cell_proof": "NOT_ISSUED"})
        return 0
    except BaseException as exc:
        obs.stop()
        obs.full_dump(exc, stage="NATURAL_OWNER_OR_RUNNER_FAILURE")
        obs.safe_write("RUN_RESULT.json", {"status": "FAILED", "cell_id": args.cell_id,
            "seed": args.seed, "error_type": type(exc).__name__, "retry": False,
            "accepted_steps": None if bundle is None else bundle.session.step_count})
        return 1
    finally:
        obs.stop()
        load_release_v1(args.release, expected_sha256=args.release_sha256)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--release", type=Path, required=True)
    ap.add_argument("--release-sha256", required=True)
    ap.add_argument("--cell-id", required=True)
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--artifact-root", required=True)
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--launch-natural", action="store_true")
    mode.add_argument("--owner", action="store_true")
    ap.add_argument("--authorization")
    args = ap.parse_args()
    if args.owner:
        return natural_owner_v1(args)
    plan = launch_plan_v1(release_path=args.release, release_sha256=args.release_sha256,
        cell_id=args.cell_id, seed=args.seed, artifact_root=args.artifact_root)
    result = detached_launch_v1(plan, authorization=args.authorization) if args.launch_natural else plan
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
