# -*- coding: utf-8 -*-
"""显式的第二验收路径：采纳被独立 pin 的真实 fresh replay 证据。

JSON/hash 自洽不是授权。调用方必须从独立信任配置传入 policy / audit
的预期 SHA256；绝不从待验证 envelope/proof 自述读取信任锚。
原 fresh-worker 入口、比较器、current-only gate 与历史 artifact 均不改。
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import inspect
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Mapping

from . import c8_timed_replay_version_compatibility_v1 as compat
from . import c8_timed_8p_full_game_contract_v1 as contract
from . import c8_timed_8p_full_game_production_replay_v1 as g3
from . import production_replay as c6
from . import formal_duel

AUTHORITY = "VERIFIED_RESULT_ADOPTION_AUTHORITY"
FRESH_AUTHORITY = "FRESH_WORKER_AUTHORITY"
SCHEMA = "C8VerifiedReplayResultAdoptionEnvelopeV1"
POLICY_SCHEMA = "C8VerifiedReplayResultAdoptionPolicyV1"
LATCH_SCHEMA = "C8CurrentReplayAdoptionLatchV1"
PROOF_SCHEMA = "C8VerifiedResultAdoptionCellProofV1"
VERSION = 1
FILES = frozenset("natural inner_result inner_claim inner_preflight inner_script inner_helper inner_manifest inner_pre_authority inner_invariants timed_result timed_conditions timed_summary timed_progress timed_driver timed_runner timed_manifest timed_config timed_config_pointer timed_budget prior_policy prior_envelope prior_audit prior_audit_manifest old_latches current_compat_policy current_compat_envelope".split())
AUDIT_FLAGS = {
    "VERIFIED_RESULT_ADOPTION_CONTRACT": "PASSED",
    "FRESH_EXECUTION_PROVENANCE_PRESERVED": "PASSED",
    "NO_REPLAY_CORRECTNESS_WEAKENING": "PASSED",
    "CURRENT_LATCH_RESIGN": "PASSED",
    "ALLOW_C8G_FG_000_CELL_PROOF": "YES",
}
DESCRIPTOR = {
    "schema": "C8VerifiedReplayResultAdoptionContractV1", "version": 1,
    "authority_path": AUTHORITY, "result_kinds": ["INNER", "TIMED"],
    "trust": "INDEPENDENT_POLICY_SHA256_AND_FINAL_AUDIT_SHA256",
    "admission": "EXACT_PINNED_RESULT_INPUT_PRODUCER_EXECUTION_COMPARISON_VERIFIER_PAIR",
    "freshness": "PRESERVE_RECORDED_FRESH_EXECUTION_NOT_NEW_EXECUTION",
    "equality": "CANONICAL_BYTES_EXACT_NO_FIELD_REMOVAL",
    "proof": "REVALIDATE_ALL_COMPONENTS_AND_AUDITED_CURRENT_LATCH",
    "old_fresh_worker_path": "UNCHANGED", "historical_write": False,
}
CONTRACT_IDENTITY = compat.identity(DESCRIPTOR)


class AdoptionError(ValueError):
    pass


def _eq(a: object, b: object, label: str) -> None:
    if compat.canonical(a) != compat.canonical(b):
        raise AdoptionError(label + "不匹配")


def _object(value: object, keys: str | frozenset[str], label: str) -> dict:
    expected = frozenset(keys.split()) if isinstance(keys, str) else keys
    if type(value) is not dict or frozenset(value) != expected:
        raise AdoptionError(label + "字段必须完整且精确")
    return value


def _sha(value: object) -> str:
    if type(value) is not str or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise AdoptionError("必须使用精确 SHA256")
    return value


def _id(value: dict, key: str) -> None:
    _eq(value[key], compat.identity({k: v for k, v in value.items() if k != key}), key)


def _seal(value: dict, key: str) -> dict:
    return {**value, key: compat.identity(value)}


def _root() -> Path:
    return Path(__file__).resolve().parents[2]


def comparison_contract_v1(kind: str) -> dict:
    if kind == "TIMED":
        return compat.comparison_contract_v1("G3_FULL_TIMED")
    if kind != "INNER":
        raise AdoptionError("只支持 INNER 或 TIMED")
    # 描述已执行的原函数；不追改原结果 schema 或其 execution identity。
    return _seal({
        "schema": "C8ControllerNeutralInnerComparisonDescriptorV1", "version": 1,
        "replay_schema": c6.REEXECUTION_SCHEMA,
        "path": "FULL_C6_V1_AND_INCREMENTAL",
        "equality": "CANONICAL_BYTES_EXACT_NO_FIELD_REMOVAL",
        "required_comparisons": ["SIGNED_ACTIONS_AND_ORDERED_LEGAL_TUPLE", "INITIAL_CONFIGURATION_AND_PRIVATE_SIGNING_MATERIAL", "PRE_POST_STATE_AND_EXECUTION", "EVENTS_AND_EVENT_HASH_CHAIN", "RNG", "REVISION_AND_STEP_COUNTERS", "COMPLETE_PRIVATE_RECORD", "TERMINAL", "INNER_TIMED_ORIGINAL_ORDERED_SEQUENCE"],
        "original_functions": {name: hashlib.sha256(inspect.getsource(fn).encode("utf-8")).hexdigest()
                               for name, fn in [("g3._fresh_inner", g3._fresh_inner), ("c6.reexecute_production_replay", c6.reexecute_production_replay)]},
    }, "identity")


@dataclass(frozen=True, slots=True)
class PinnedAdoptionPolicyV1:
    raw: bytes
    expected_sha256: str

    @classmethod
    def load(cls, path: Path, *, expected_sha256: str) -> "PinnedAdoptionPolicyV1":
        value = cls(Path(path).read_bytes(), _sha(expected_sha256))
        value.validate()
        return value

    def validate(self) -> dict:
        _eq(hashlib.sha256(self.raw).hexdigest(), _sha(self.expected_sha256), "独立 policy pin")
        p = _object(compat.strict_json(self.raw), "schema version generation contract_identity current_sources current_verifier_identity global_source_identity source_fingerprint python producer_root historical_verifier_root files pairs supersedes policy_identity", "adoption policy")
        _eq([p["schema"], p["version"], p["contract_identity"]], [POLICY_SCHEMA, VERSION, CONTRACT_IDENTITY], "policy contract")
        if type(p["generation"]) is not int or p["generation"] <= 0:
            raise AdoptionError("current latch generation 必须为正整数")
        _id(p, "policy_identity")
        if self.raw != compat.canonical(p):
            raise AdoptionError("policy 必须使用 canonical bytes")
        compat._verify_manifest(_root(), p["current_sources"])
        _eq(p["current_verifier_identity"], compat.verifier_identity_v1(p["current_sources"]), "当前 verifier")
        _eq(p["source_fingerprint"], compat.identity(p["current_sources"]), "完整源码 fingerprint")
        _eq(p["global_source_identity"], formal_duel.implementation_identity(_root()), "实际 global inventory identity")
        _eq(p["python"], {"version": sys.version, "executable_sha256": compat.file_hash(Path(sys.executable)), "hashseed": os.environ.get("PYTHONHASHSEED")}, "当前解释器/profile")
        _eq(os.environ.get("PYTHONHASHSEED"), "0", "启动前 PYTHONHASHSEED")
        _object(p["files"], FILES, "evidence 文件登记")
        for entry in p["files"].values():
            _object(entry, "path sha256", "evidence pointer")
            if type(entry["path"]) is not str or not Path(entry["path"]).is_absolute():
                raise AdoptionError("evidence 必须独立固定绝对路径")
            _sha(entry["sha256"])
        _object(p["pairs"], "INNER TIMED", "exact result pair")
        if type(p["supersedes"]) is not list or not p["supersedes"]:
            raise AdoptionError("必须登记被替代的历史 latch/disposition")
        for value in p["supersedes"]:
            _sha(value)
        return p


def _read_evidence(p: dict) -> dict[str, bytes]:
    result = {}
    for name, entry in p["files"].items():
        try:
            raw = Path(entry["path"]).read_bytes()
        except OSError as exc:
            raise AdoptionError("读取固定 evidence 失败：" + name) from exc
        _eq(hashlib.sha256(raw).hexdigest(), entry["sha256"], name + " exact artifact hash")
        result[name] = raw
    return result


def _finish(policy: PinnedAdoptionPolicyV1, p: dict) -> None:
    """在验证事务结束再次 fail closed，避免读取期间发生文件替换。"""
    policy.validate()
    for name, entry in p["files"].items():
        _eq(compat.file_hash(Path(entry["path"])), entry["sha256"], "结束时 evidence " + name)


def _current_compat(p: dict, raw: Mapping[str, bytes]) -> compat.PinnedCompatibilityPolicyV1:
    return compat.PinnedCompatibilityPolicyV1(raw["current_compat_policy"], p["files"]["current_compat_policy"]["sha256"], Path(p["producer_root"]), _root())


_HISTORICAL_PREFLIGHT = '''from pathlib import Path
import sys,json,hashlib
sys.path.insert(0,str(Path.cwd()))
from scripts.sgs_engine import c8_timed_replay_version_compatibility_v1 as c
from scripts.sgs_engine import c8_timed_8p_full_game_production_replay_v1 as g3
q=c.strict_json(sys.stdin.buffer.read())
p=c.PinnedCompatibilityPolicyV1.load(Path(q['policy']),expected_sha256=q['pin'],producer_root=Path(q['producer']),verifier_root=Path.cwd())
raw=Path(q['natural']).read_bytes()
with c._verification_scope(Path(q['envelope']).read_bytes(),raw,p):
    d=g3.preflight_composition_v1(raw,full_game=True)
print(json.dumps({'status':'PASSED','artifact_sha256':hashlib.sha256(raw).hexdigest(),'artifact_identity':d['artifact_identity']}))
'''


def _preflight_original_composition(p: dict, raw: Mapping[str, bytes]) -> dict:
    """在独立固定的原审计源码域只读解析；不重跑、重签或改写旧执行身份。

    当前 E certificate/driver 变更后，不能用当前常量伪装旧 G1/F/G3。
    当前 compatibility pair 和原 worker pair 都必须精确匹配。子进程只调用
    原 preflight parser；其原始字节、源码域及返回 artifact commitment 均核验。
    当前 fresh-worker/replay/current-only gates 不经过此 adoption 专属入口。
    """
    cp = _current_compat(p, raw)
    compat.validate_envelope_v1(raw["current_compat_envelope"], raw["natural"], policy=cp)
    prior = compat.strict_json(raw["prior_policy"])
    root = Path(p["historical_verifier_root"]).resolve()
    compat._verify_manifest(root, prior["verifier_sources"])
    request = dict(policy=p["files"]["prior_policy"]["path"], pin=p["files"]["prior_policy"]["sha256"],
                   producer=p["producer_root"], natural=p["files"]["natural"]["path"],
                   envelope=p["files"]["prior_envelope"]["path"])
    try:
        result = subprocess.run([sys.executable, "-B", "-c", _HISTORICAL_PREFLIGHT], cwd=root,
            input=compat.canonical(request), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env=dict(os.environ, PYTHONHASHSEED="0", PYTHONDONTWRITEBYTECODE="1"), timeout=60)
        if result.returncode:
            raise AdoptionError("原审计源码域的只读 preflight 未通过")
        d = compat.strict_json(raw["natural"])
        _eq(compat.strict_json(result.stdout), {"status": "PASSED",
            "artifact_sha256": hashlib.sha256(raw["natural"]).hexdigest(),
            "artifact_identity": d["artifact_identity"]}, "原域只读 parser receipt")
        return d
    except subprocess.TimeoutExpired as exc:
        raise AdoptionError("原审计源码域的只读 preflight 超时；不得采纳") from exc
    finally:
        compat._verify_manifest(root, prior["verifier_sources"])
        cp.validate()


def _material(p: dict, raw: Mapping[str, bytes]) -> tuple[dict, dict[str, dict]]:
    j = {k: compat.strict_json(v) for k, v in raw.items() if k not in {"inner_script", "inner_helper", "timed_driver", "timed_runner", "timed_config_pointer", "prior_audit", "timed_progress"}}
    natural, inner, timed = j["natural"], j["inner_result"], j["timed_result"]
    prior, old_envelope = j["prior_policy"], j["prior_envelope"]
    _eq(j["prior_audit_manifest"]["FINAL_GROK_REPORT.md"], p["files"]["prior_audit"]["sha256"], "原 audit manifest/report")
    for name, leaf in {"inner_script":"inner_once.py", "inner_helper":"authority_check.py", "inner_result":"INNER_COLD_REPLAY_RESULT.json", "inner_claim":"INNER_ONCE_CLAIM.json", "inner_preflight":"INNER_PREFLIGHT_PASS.json"}.items():
        _eq(j["inner_manifest"][leaf], p["files"][name]["sha256"], "原 inner worker/dependency manifest " + name)
    for name, leaf in {"timed_driver":"full_driver.py", "timed_runner":"run.py", "timed_result":"FULL_TIMED_RESULT.json", "timed_conditions":"FULL_TIMED_CONDITIONS.json", "timed_budget":"BUDGET.json"}.items():
        _eq(j["timed_manifest"][leaf], p["files"][name]["sha256"], "原 timed worker/dependency manifest " + name)
    _eq(raw["timed_config_pointer"].decode("utf-8").strip(), p["files"]["timed_config"]["path"], "原 timed invocation config pointer")
    _eq(j["timed_config"]["natural_artifact"], p["files"]["natural"]["path"], "原 timed config input path")
    _eq(j["timed_config"]["policy_sha256"], p["files"]["prior_policy"]["sha256"], "原 timed config independent pin")
    _id(prior, "policy_identity"); _id(old_envelope, "envelope_identity")
    compat._verify_manifest(Path(p["producer_root"]), prior["producer_sources"])
    compat._verify_manifest(Path(p["historical_verifier_root"]), prior["verifier_sources"])
    _eq(prior["verifier_identity"], compat.verifier_identity_v1(prior["verifier_sources"]), "历史 worker verifier manifest")
    _eq(old_envelope["scope"], "DEVELOPMENT_VERIFICATION_ONLY", "旧 envelope 原 scope")
    _eq(old_envelope["promotion"], False, "旧 envelope 未晋升")
    _eq(old_envelope["artifact_sha256"], p["files"]["natural"]["sha256"], "旧 envelope input")
    _eq(old_envelope["policy_identity"], prior["policy_identity"], "旧 envelope policy")
    _eq(old_envelope["verifier_identity"], prior["verifier_identity"], "旧 envelope verifier")
    _eq(old_envelope["comparison_contract"], comparison_contract_v1("TIMED"), "旧 timed comparison")
    pair = {k: old_envelope[k] for k in ("lane", "artifact_sha256", "producer_identity", "verifier_identity")}
    pair["comparison_identity"] = old_envelope["comparison_contract"]["identity"]
    if compat.canonical(pair) not in {compat.canonical(v) for v in prior["pairs"]}:
        raise AdoptionError("原 execution compatibility pair 未登记")
    audit = raw["prior_audit"].decode("utf-8")
    for flag, value in {"FINAL_INDEPENDENT_AUDIT": "PASSED", "FULL_TIMED_MATCH_EVIDENCE": "ACCEPTED", "OLD_ARTIFACT_IDENTITY_PRESERVATION": "PASSED"}.items():
        if flag + " = " + value not in audit:
            raise AdoptionError("缺少原独立审计 authority")
    d = _preflight_original_composition(p, raw)
    t = d["timed_artifact"]; private = t["private_production_record"]
    _eq(d["cell_id"], contract.canonical_cell_id_v1(t["seed"]), "seed/cell")
    _eq(t["completed_production_steps"], len(d["ordered_production_sequence"]), "完整 accepted count")
    _eq(private["outcome"]["step_count"], t["completed_production_steps"], "natural terminal steps")
    _eq(old_envelope["producer_identity"], d["g3_binding"]["current_c8_implementation_identity"], "旧 producer")
    _id(inner, "result_identity"); _id(timed, "result_identity")
    _eq([inner["schema"], inner["version"], inner["status"], inner["comparison_status"]], ["C8ControllerNeutralInnerColdReplayResultV1", 1, "PASSED", "MATCH"], "完整 inner 类型/状态")
    _eq([inner["formal_result"]["status"], inner["formal_result"]["path"], inner["formal_result"]["full_game"]], ["MATCH", "FULL_C6_V1_AND_INCREMENTAL", True], "正式 inner 路径")
    _eq([timed["schema"], timed["version"], timed["status"]], [compat.RESULT_SCHEMA, 1, "MATCH"], "完整 timed 类型/状态")
    _eq(timed["comparison_contract"], comparison_contract_v1("TIMED"), "timed comparison contract")
    _eq(timed["comparison_results"], {k: "MATCH" for k in timed["comparison_contract"]["required_comparisons"]}, "全部 timed comparisons")
    for result in (inner["formal_result"], timed["details"]["timed"]):
        _eq(result["ordered_sequence"], d["ordered_production_sequence"], "inner/timed/original signed sequence")
        _eq(result["private_record_identity"], private["record_identity"], "inner/timed/original private record")
    _eq(inner["terminal_result"], private["outcome"], "inner terminal")
    _eq([inner["accepted"], inner["windows"]], [t["completed_production_steps"], t["completed_windows"]], "inner 完整结果计数")
    _eq([inner["inner_invocations"], inner["full_timed_invocations"]], [1, 0], "inner 独立调用")
    _eq(inner["natural_sha256"], p["files"]["natural"]["sha256"], "inner input")
    _eq(inner["original_producer_identity"], old_envelope["producer_identity"], "inner old producer")
    _eq(inner["current_verifier_identity"], prior["verifier_identity"], "inner 原 worker source identity")
    _eq(inner["compatibility_envelope_identity"], old_envelope["envelope_identity"], "inner 原 envelope")
    _eq(inner["accepted_timed_result_sha256"], p["files"]["timed_result"]["sha256"], "inner/timed result hash")
    _eq(inner["accepted_timed_result_identity"], timed["result_identity"], "inner/timed result identity")
    _eq(inner["final_audit_sha256"], p["files"]["prior_audit"]["sha256"], "inner 原 audit")
    for key in ("producer_identity", "verifier_identity", "policy_identity", "envelope_identity", "artifact_sha256"):
        _eq(timed[key], old_envelope[key], "timed 原绑定 " + key)
    for result in (inner, timed):
        _eq([result["cell_proof"], result["historical_status_updated"]], [False, False], "旧结果不能追溯晋升")
    claim, ipre = j["inner_claim"], j["inner_preflight"]
    _eq(claim["process"], inner["process"], "inner fresh process")
    _eq(ipre["process"], claim["process"], "inner preflight process")
    _eq([claim["invocation"], claim["maximum_invocations"], claim["fresh_from_step0"], claim["resume"], claim["full_timed_replay"]], [1, 1, True, False, False], "inner 一次性 step0 provenance")
    _eq(claim["script_sha256"], p["files"]["inner_script"]["sha256"], "inner worker script")
    _eq(claim["natural_sha256"], p["files"]["natural"]["sha256"], "inner claim input")
    _eq(claim["pre_authority_sha256"], p["files"]["inner_pre_authority"]["sha256"], "inner 前置 authority")
    _eq(ipre["artifact_identity"], d["artifact_identity"], "inner preflight artifact")
    _eq(ipre["cell_execution_identity"], t["cell_execution_identity"], "inner preflight execution")
    _eq(ipre["status"], "PASS", "inner preflight")
    for key in ("pid", "creation_filetime"):
        if type(claim["process"].get(key)) is not int or claim["process"][key] <= 0:
            raise AdoptionError("inner fresh 进程实例 provenance 缺失")
    _sha(claim["process"]["image_sha256"])
    _eq(j["inner_pre_authority"]["verifier_identity"], prior["verifier_identity"], "inner pre worker identity")
    _eq(j["inner_invariants"]["inner_result_readback"]["sha256"], p["files"]["inner_result"]["sha256"], "inner immutable readback")
    conditions, summary = j["timed_conditions"], j["timed_summary"]
    _eq(conditions["input_sha256"], p["files"]["natural"]["sha256"], "timed step0 input")
    _eq(conditions["driver_sha256"], p["files"]["timed_driver"]["sha256"], "timed worker source")
    _eq(conditions["verifier_identity"], prior["verifier_identity"], "timed worker verifier")
    _eq(conditions["independently_pinned_policy_sha256"], p["files"]["prior_policy"]["sha256"], "timed 独立原 policy pin")
    _eq([summary["status"], summary["run_count"], summary["exact_comparison_status"]], ["PASS", 1, "MATCH"], "timed 一次完整 fresh execution")
    _eq(summary["result_identity"], timed["result_identity"], "timed completion identity")
    _eq([summary["completed_steps"], summary["completed_windows"]], [t["completed_production_steps"], t["completed_windows"]], "timed 完整计数")
    runs = [v for v in j["timed_budget"]["experiments"] if v["kind"] == "full"]
    if len(runs) != 1:
        raise AdoptionError("timed fresh run provenance 必须唯一")
    run = runs[0]
    _eq([run["status"], run["exit_code"], run["seconds"]], ["PASS", 0, summary["wall_seconds"]], "timed 原执行完成")
    _eq(run["argv"], [p["files"]["timed_driver"]["path"], "full"], "timed fresh worker command")
    progress = [compat.strict_json(line.encode("utf-8")) for line in raw["timed_progress"].decode("utf-8").splitlines()]
    _eq(progress[0]["stage"], "COMPATIBILITY_VERIFICATION_START", "timed start")
    _eq(progress[0]["artifact_sha256"], p["files"]["natural"]["sha256"], "timed start input")
    starts = [v for v in progress if v["stage"] == "TIMED_EXECUTION_STARTED"]
    _eq(len(starts), 1, "timed step0 fresh start 数量")
    _eq([starts[0]["accepted_steps"], starts[0]["completed_windows"]], [0, 0], "timed 从 step0")
    _eq([progress[-1]["stage"], progress[-1]["result_identity"]], ["EXACT_COMPARISONS_MATCH", timed["result_identity"]], "timed complete comparator")
    ends = [v for v in progress if v["stage"] == "TIMED_GENERATION_FINISHED_COMPARISON_STILL_REQUIRED"]
    _eq(len(ends), 1, "timed 唯一 generation completion")
    _eq([ends[0]["last_accepted_step"], ends[0]["last_fully_evidenced_step"], ends[0]["completed_window_count"]], [t["completed_production_steps"], t["completed_production_steps"], t["completed_windows"]], "timed fully evidenced")
    _eq([conditions["python"], conditions["hashseed"]], [prior["python"]["version"], "0"], "timed 原环境")
    _eq(claim["process"]["python"], prior["python"]["version"], "inner 原环境")
    _eq(p["supersedes"][0], p["files"]["old_latches"]["sha256"], "历史 latch supersession anchor")
    if len(set(p["supersedes"])) != len(p["supersedes"]):
        raise AdoptionError("supersedes 不得重复")
    descriptors = {}
    for kind, result, provenance_names, worker in [
        ("INNER", inner, ["inner_claim", "inner_preflight", "inner_script", "inner_helper", "inner_manifest", "inner_pre_authority", "inner_invariants"], claim["process"]),
        ("TIMED", timed, ["timed_conditions", "timed_summary", "timed_progress", "timed_driver", "timed_runner", "timed_manifest", "timed_config", "timed_config_pointer", "timed_budget", "prior_audit"], {"kind": "RECORDED_EXECUTION_EVIDENCE", "os_pid": "NOT_RECORDED", "original_command": run["argv"], "started_utc": progress[0]["utc"], "completed_utc": progress[-1]["utc"]}),
    ]:
        provenance = {name: p["files"][name]["sha256"] for name in provenance_names}
        execution = {"worker": worker, "source_identity": prior["verifier_identity"], "environment": prior["python"], "profile": t["construction"]["execution_order_profile"], "evidence_sha256": provenance, "result_identity": result["result_identity"]}
        descriptors[kind] = {
            "result_type": kind, "result_artifact_sha256": p["files"][kind.lower()+"_result"]["sha256"],
            "seed": t["seed"], "cell_id": d["cell_id"], "natural_sha256": p["files"]["natural"]["sha256"],
            "original_producer_identity": d["g3_binding"]["current_c8_implementation_identity"],
            "original_cell_execution_identity": t["cell_execution_identity"],
            "fresh_execution_identity": compat.identity(execution), "fresh_execution_provenance": execution,
            "result_schema": result["schema"], "result_version": result["version"], "result_identity": result["result_identity"],
            "result_status": result["status"], "comparison_status": "MATCH", "complete": True,
            "comparison_contract": comparison_contract_v1(kind),
            "worker_source_identity": prior["verifier_identity"],
            "current_verifier_identity": p["current_verifier_identity"],
            "prior_compatibility_policy_identity": prior["policy_identity"],
            "prior_compatibility_envelope_identity": old_envelope["envelope_identity"],
            "existing_final_audit_sha256": p["files"]["prior_audit"]["sha256"],
        }
    return d, descriptors


def derive_registered_pairs_v1(policy: PinnedAdoptionPolicyV1) -> dict:
    """供受信配置构建器登记候选；此函数不签 latch 或 proof。"""
    p = policy.validate()
    _, rows = _material(p, _read_evidence(p))
    _finish(policy, p)
    return rows


def build_envelope_v1(kind: str, *, policy: PinnedAdoptionPolicyV1) -> bytes:
    p = policy.validate()
    if kind not in ("INNER", "TIMED"):
        raise AdoptionError("result type 非法")
    raw = compat.canonical(_seal({"schema": SCHEMA, "version": VERSION, "authority_path": AUTHORITY, "policy_identity": p["policy_identity"], "policy_version": p["version"], "contract_identity": CONTRACT_IDENTITY, "binding": p["pairs"][kind]}, "envelope_identity"))
    validate_envelope_v1(raw, expected_kind=kind, policy=policy)
    return raw


def _envelope(raw: bytes, kind: str, p: dict) -> dict:
    e = _object(compat.strict_json(raw), "schema version authority_path policy_identity policy_version contract_identity binding envelope_identity", "adoption envelope")
    _id(e, "envelope_identity")
    _eq([e["schema"], e["version"], e["authority_path"], e["policy_identity"], e["policy_version"], e["contract_identity"]], [SCHEMA, VERSION, AUTHORITY, p["policy_identity"], p["version"], CONTRACT_IDENTITY], "adoption envelope authority")
    if kind not in ("INNER", "TIMED"):
        raise AdoptionError("结果类型必须显式指定")
    _eq(e["binding"], p["pairs"][kind], "exact 已登记 result pair")
    _eq(e["binding"]["result_type"], kind, "INNER/TIMED 禁止互换")
    return e


def validate_envelope_v1(raw: bytes, *, expected_kind: str, policy: PinnedAdoptionPolicyV1) -> dict:
    if type(policy) is not PinnedAdoptionPolicyV1:
        raise AdoptionError("需要 exact independently pinned adoption policy")
    p = policy.validate(); e = _envelope(raw, expected_kind, p)
    _, rows = _material(p, _read_evidence(p))
    _eq(e["binding"], rows[expected_kind], "真实 fresh provenance 与 admission pair")
    _finish(policy, p)
    return e


def _validated_pair(policy: PinnedAdoptionPolicyV1, inner: bytes, timed: bytes) -> tuple[dict, dict, dict, dict]:
    compat.reject_recording_v1()
    if type(policy) is not PinnedAdoptionPolicyV1:
        raise AdoptionError("需要 exact independently pinned adoption policy")
    p = policy.validate()
    ie, te = _envelope(inner, "INNER", p), _envelope(timed, "TIMED", p)
    d, rows = _material(p, _read_evidence(p))
    _eq(p["pairs"], rows, "精确两类 fresh execution provenance")
    _finish(policy, p)
    return p, d, ie, te


def implementation_identity_v1(p: dict) -> str:
    return compat.identity({"schema": "C8CurrentAdoptionImplementationV1", "contract_identity": CONTRACT_IDENTITY, "current_verifier_identity": p["current_verifier_identity"], "source_fingerprint": p["source_fingerprint"], "global_source_identity": p["global_source_identity"]})


def _latch(p: dict, d: dict, ie: dict, te: dict) -> dict:
    t = d["timed_artifact"]
    return _seal({"schema": LATCH_SCHEMA, "version": VERSION, "authority_path": AUTHORITY, "generation": p["generation"], "policy_identity": p["policy_identity"], "policy_sha256": hashlib.sha256(compat.canonical(p)).hexdigest(), "current_verifier_identity": p["current_verifier_identity"], "current_implementation_identity": implementation_identity_v1(p), "source_fingerprint": p["source_fingerprint"], "global_source_identity": p["global_source_identity"], "cell_id": d["cell_id"], "seed": t["seed"], "natural_sha256": p["files"]["natural"]["sha256"], "original_g1_g2_g3_binding": d["g3_binding"], "original_cell_execution_identity": t["cell_execution_identity"], "execution_order_profile": t["construction"]["execution_order_profile"], "inner_adoption_identity": ie["envelope_identity"], "timed_adoption_identity": te["envelope_identity"], "inner_binding": ie["binding"], "timed_binding": te["binding"], "existing_final_audit_sha256": p["files"]["prior_audit"]["sha256"], "supersedes": p["supersedes"], "new_independent_audit_gate": "REQUIRED_BEFORE_CELL_PROOF", "historical_status_updated": False}, "latch_identity")


def resign_current_latch_v1(*, policy: PinnedAdoptionPolicyV1, inner_envelope: bytes, timed_envelope: bytes) -> bytes:
    p, d, ie, te = _validated_pair(policy, inner_envelope, timed_envelope)
    # Policy bytes must be canonical so file and material pins cannot diverge.
    if policy.raw != compat.canonical(p):
        raise AdoptionError("policy 必须使用 canonical bytes")
    return compat.canonical(_latch(p, d, ie, te))


def validate_current_latch_v1(raw: bytes, *, policy: PinnedAdoptionPolicyV1, inner_envelope: bytes, timed_envelope: bytes) -> dict:
    p, d, ie, te = _validated_pair(policy, inner_envelope, timed_envelope)
    latch = compat.strict_json(raw)
    _eq(latch, _latch(p, d, ie, te), "current latch 全字段/epoch/supersession")
    return latch


@dataclass(frozen=True, slots=True)
class IndependentAuditAuthorityV1:
    """expected hashes 来自独立审计调用方，绝不能从 proof 中取得。"""
    report: bytes
    expected_report_sha256: str
    subject: bytes
    expected_subject_sha256: str

    def validate(self, p: dict, policy_hash: str, latch: bytes, inner: bytes, timed: bytes) -> dict:
        _eq(hashlib.sha256(self.report).hexdigest(), _sha(self.expected_report_sha256), "独立 Grok report pin")
        _eq(hashlib.sha256(self.subject).hexdigest(), _sha(self.expected_subject_sha256), "独立 Grok subject pin")
        subject = _object(compat.strict_json(self.subject), "schema version policy_sha256 current_verifier_identity current_implementation_identity source_fingerprint latch_sha256 inner_envelope_sha256 timed_envelope_sha256 targeted_tests_sha256 preservation_sha256", "audit subject")
        _eq([subject["schema"], subject["version"]], ["C8AdoptionAuditSubjectV1", 1], "audit subject schema")
        for key, value in {"policy_sha256": policy_hash, "current_verifier_identity": p["current_verifier_identity"], "current_implementation_identity": implementation_identity_v1(p), "source_fingerprint": p["source_fingerprint"], "latch_sha256": hashlib.sha256(latch).hexdigest(), "inner_envelope_sha256": hashlib.sha256(inner).hexdigest(), "timed_envelope_sha256": hashlib.sha256(timed).hexdigest()}.items():
            _eq(subject[key], value, "final audited " + key)
        for key in ("targeted_tests_sha256", "preservation_sha256"):
            _sha(subject[key])
        blocks = re.findall(r"```json\s*(\{.*?\})\s*```", self.report.decode("utf-8"), flags=re.S)
        if len(blocks) != 1:
            raise AdoptionError("Grok final 必须恰好一个 JSON decision block")
        verdict = _object(compat.strict_json(blocks[0].encode("utf-8")), frozenset(AUDIT_FLAGS) | {"AUDIT_SUBJECT_SHA256"}, "Grok final decision")
        _eq(verdict, {**AUDIT_FLAGS, "AUDIT_SUBJECT_SHA256": self.expected_subject_sha256}, "最终独立审计全部 PASS + YES")
        return {"report_sha256": self.expected_report_sha256, "subject_sha256": self.expected_subject_sha256, "verdict": verdict}


def _formal_report(p: dict, d: dict) -> dict:
    """相同 G1 flags 与 witness 语义；不恢复序列化 live token。

FG-TIMER-09 的独立 unresolved worker 没有本次 adoption 证据，保持原
missing witness；既有 G1 cell gate 本来就不要求此条件性 matrix witness。
"""
    t = d["timed_artifact"]
    witnesses = g3._derive_full_game_witnesses(d, None)
    observed = {w.obligation_id for w in witnesses if w.status is contract.WitnessStatusV1.OBSERVED}
    facts = {"PRODUCTION_REACHABLE", "NATURAL_FULL_GAME", "CANONICAL_C6_MODE_PROVEN", "FORMAL_DRIVER_POLICY_PROVEN", "TIMER_AUTHORITY_PROVEN", "PUBLIC_ADAPTER_AUTHORITY_PROVEN", "CONTROLLER_AUTHORITY_PROVEN", "MULTIWINDOW_CONTINUITY_PROVEN", "NATURAL_TERMINAL_PROVEN", "TERMINAL_WINDOWS_CLEAN_PROVEN", "INNER_PRODUCTION_REPLAY_PROVEN", "OUTER_TIMER_REPLAY_PROVEN", "FULL_GAME_REPLAY_STRICT_VERIFIED", "IDENTITY_PROFILE_DRIVER_BINDING_PROVEN"}
    for obligation, fact in (("FG-TIMER-01", "ON_TIME_TRACE_PROVEN"), ("FG-TIMER-02", "TIMEOUT_TRACE_PROVEN"), ("FG-TIMER-03", "SAME_CONTEXT_NO_REFRESH_PROVEN"), ("FG-TIMER-04", "PHASE_CLEANUP_PROVEN"), ("FG-TIMER-05", "TURN_ACTOR_CLEANUP_PROVEN"), ("FG-TIMER-06", "STALE_EVIDENCE_REJECTION_PROVEN")):
        if obligation in observed:
            facts.add(fact)
    result = contract._fresh_full_game_result_v1(cell_id=d["cell_id"], seed=t["seed"], mode_id=contract.C8_G1_BASE_MODE_ID,
        registry_identity=t["registry"]["registry_identity"], current_implementation_identity=implementation_identity_v1(p),
        contract_identity=contract.C8_G1_CONTRACT_IDENTITY, timer_profile_id=contract.C8_G1_TIMER_PROFILE_ID,
        driver_policy_identity=contract.C8_G1_DRIVER_POLICY_IDENTITY, replay_schema=contract.C8_G1_REPLAY_SCHEMA,
        replay_scope=contract.C8_G1_SCOPE_MARKER, production_adapter_id=contract.C8_G1_E_ADAPTER_ID,
        production_adapter_contract_identity=contract.C8_G1_E_CONTRACT_IDENTITY, controller_contract_identity=contract.C8_G1_C_CONTROLLER_CONTRACT_IDENTITY,
        artifact_scope=contract.CandidateScopeV1.FORMAL_QUALITY_CANDIDATE, run_status=contract.CellRunStatusV1.COMPLETE,
        artifact_complete=True, full_game=True, formal_matrix_cell=True, natural_terminal=True, safety_cap_hit=False,
        strict_replay_verified=True, replay_identity=d["artifact_identity"], artifact_identity=d["artifact_identity"],
        verified_fact_ids=frozenset(facts), required_event_witnesses=witnesses,
        successful_rescue_evidence_identities=tuple(v["evidence_identity"] for v in t["private_production_record"]["successful_rescue_evidence"]))
    if result.proof_flags()["CELL_PROOF"] is not True:
        raise AdoptionError("原 G1 cell proof gate 未满足")
    return result.to_report_dict()


def issue_cell_proof_v1(*, policy: PinnedAdoptionPolicyV1, inner_envelope: bytes, timed_envelope: bytes, current_latch: bytes, audit: IndependentAuditAuthorityV1) -> bytes:
    if type(audit) is not IndependentAuditAuthorityV1:
        raise AdoptionError("需要 exact independently pinned final audit authority")
    p, d, ie, te = _validated_pair(policy, inner_envelope, timed_envelope)
    latch = compat.strict_json(current_latch)
    _eq(latch, _latch(p, d, ie, te), "正式 current latch")
    approval = audit.validate(p, policy.expected_sha256, current_latch, inner_envelope, timed_envelope)
    t = d["timed_artifact"]
    material = {"schema": PROOF_SCHEMA, "version": VERSION, "authority_path": AUTHORITY,
        "contract_identity": CONTRACT_IDENTITY, "cell_id": d["cell_id"], "seed": t["seed"],
        "natural_sha256": p["files"]["natural"]["sha256"], "natural_artifact_identity": d["artifact_identity"],
        "original_producer_identity": d["g3_binding"]["current_c8_implementation_identity"],
        "original_g1_g2_g3_binding": d["g3_binding"], "original_cell_execution_identity": t["cell_execution_identity"],
        "current_verifier_identity": p["current_verifier_identity"], "current_implementation_identity": implementation_identity_v1(p),
        "global_source_identity": p["global_source_identity"], "source_fingerprint": p["source_fingerprint"],
        "driver_policy_identity": contract.C8_G1_DRIVER_POLICY_IDENTITY,
        "execution_order_profile": t["construction"]["execution_order_profile"],
        "adoption_policy_identity": p["policy_identity"], "adoption_policy_sha256": policy.expected_sha256,
        "inner_adoption_envelope": ie, "timed_adoption_envelope": te,
        "current_latch_identity": latch["latch_identity"], "current_latch_sha256": hashlib.sha256(current_latch).hexdigest(),
        "final_audit_authority": approval, "terminal_result": t["private_production_record"]["outcome"],
        "accepted": t["completed_production_steps"], "fully_evidenced": len(d["ordered_production_sequence"]), "windows": t["completed_windows"],
        "formal_cell_report": _formal_report(p, d), "historical_status_updated": False, "new_replay_executions": 0}
    _finish(policy, p)
    return compat.canonical(_seal(material, "proof_identity"))


def verify_cell_proof_v1(proof: bytes, **authority: object) -> dict:
    """Fresh 静态验证所有 provenance、current latch、最终审计，再比较整份 proof。"""
    incoming = compat.strict_json(proof)
    expected = compat.strict_json(issue_cell_proof_v1(**authority))
    _eq(incoming, expected, "正式 adoption cell proof 完整 readback")
    return {"status": "PASSED", "cell_id": expected["cell_id"], "proof_identity": expected["proof_identity"], "authority_path": AUTHORITY, "new_replay_executions": 0}
