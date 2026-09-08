# -*- coding: utf-8 -*-
"""精确、不可提升的旧执行材料/新验证器兼容验证。

Policy 的 SHA256 来自调用方的独立可信配置，绝不从 envelope 中取得。
Producer source bindings 仅在已验证 envelope 的私有 scope 内重建原证据；
它们不是新源码的身份。新 verifier 的完整 manifest 在 scope 两端校验。
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from types import MappingProxyType
from typing import Iterator, Mapping

SCHEMA = "C8TimedReplayVersionCompatibilityEnvelopeV1"
POLICY_SCHEMA = "C8TimedReplayVersionCompatibilityPolicyV1"
RESULT_SCHEMA = "C8TimedReplayVersionCompatibilityResultV1"
CORPUS_SCHEMA = "C8DOriginalExecutionArtifactsV1"
VERSION = 1
_SCOPE: ContextVar[object | None] = ContextVar("c8_verified_compatibility_scope", default=None)


class C8CompatibilityError(ValueError):
    pass


def canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def identity(value: object) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def file_hash(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise C8CompatibilityError("兼容 JSON 存在重复字段")
        result[key] = value
    return result


def strict_json(raw: bytes) -> dict:
    if type(raw) is not bytes:
        raise C8CompatibilityError("兼容入口必须接收原始 bytes")
    try:
        value = json.loads(raw, object_pairs_hook=_pairs,
                           parse_constant=lambda _: (_ for _ in ()).throw(C8CompatibilityError("非有限 JSON 数值")))
    except (ValueError, UnicodeError) as exc:
        raise C8CompatibilityError("兼容材料不是 strict JSON") from exc
    if type(value) is not dict:
        raise C8CompatibilityError("兼容材料根必须是 object")
    return value


def _object(value: object, fields: str, label: str) -> dict:
    if type(value) is not dict or set(value) != set(fields.split()):
        raise C8CompatibilityError(label + "字段不精确")
    return value


def _equal(actual: object, expected: object, label: str) -> None:
    if canonical(actual) != canonical(expected):
        raise C8CompatibilityError(label + "不匹配")


def _digest(value: object) -> str:
    if type(value) is not str or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise C8CompatibilityError("必须提供精确 SHA256")
    return value


def _relative(value: str) -> Path:
    path = Path(value)
    if type(value) is not str or path.is_absolute() or ".." in path.parts or "\\" in value or path.as_posix() != value:
        raise C8CompatibilityError("源码 manifest 路径越界或非 canonical")
    return path


def comparison_contract_v1(lane: str) -> dict:
    from . import c8_strict_replay_v1 as d
    from . import c8_timed_8p_full_game_contract_v1 as g1
    from . import c8_timed_8p_full_game_replay_v1 as replay
    if lane == "D_CORPUS":
        schema, contract = d.C8_D_REPLAY_SCHEMA, d.C8_D_CONTRACT_IDENTITY
        comparisons = ["EXACT_D_EXECUTION_EVIDENCE", "EXACT_D_PUBLIC_PROJECTION", "D_TYPED_PARSER_AND_CURRENT_PRODUCER_LATCH"]
    elif lane in {"G3_FULL_TIMED", "G3_BOUNDED"}:
        schema, contract = g1.C8_G1_REPLAY_SCHEMA, replay.C8_G1_REPLAY_CONTRACT_IDENTITY
        if lane == "G3_BOUNDED":
            from . import c8_timed_8p_full_game_production_replay_v1 as g3
            schema = g3.C8_G3_BOUNDED_SCHEMA
        comparisons = ["FULL_COMPOSITION_PREFLIGHT", "EXACT_COMPLETE_TIMED_TRANSCRIPT",
                       "ORDERED_SIGNED_ACTIONS", "STATES", "EVENTS", "RNG", "WINDOWS",
                       "TIMEOUT_AND_REJECTED_OPERATIONS", "TERMINAL", "ORDERED_PRODUCTION_SEQUENCE"]
    else:
        raise C8CompatibilityError("未支持的兼容 lane")
    material = dict(schema="C8ExactReplayComparisonContractV1", version=1, lane=lane,
                    replay_schema=schema, replay_contract_identity=contract,
                    equality="CANONICAL_BYTES_EXACT_NO_FIELD_REMOVAL", required_comparisons=comparisons)
    return {**material, "identity": identity(material)}


def verifier_identity_v1(sources: Mapping[str, str]) -> str:
    return identity(dict(schema="C8CompatibilityVerifierIdentityV1", version=1, source_sha256=dict(sources)))


def _verify_manifest(root: Path, sources: dict) -> None:
    if type(sources) is not dict or not sources:
        raise C8CompatibilityError("源码清单不能为空")
    for relative, digest in sources.items():
        path = root / _relative(relative)
        if not path.is_file() or file_hash(path) != _digest(digest):
            raise C8CompatibilityError("源码清单漂移：" + relative)
    for directory in ("scripts", "tests"):
        actual = {p.relative_to(root).as_posix() for p in (root/directory).rglob("*.py")}
        expected = {p for p in sources if p.startswith(directory+"/") and p.endswith(".py")}
        if actual != expected:
            raise C8CompatibilityError("源码清单成员漂移：" + directory)


@dataclass(frozen=True, slots=True)
class PinnedCompatibilityPolicyV1:
    """只保存已由独立 expected_sha256 核对的原字节，避免嵌套 dict 被改。"""
    raw: bytes
    expected_sha256: str
    producer_root: Path
    verifier_root: Path

    @classmethod
    def load(cls, path: Path, *, expected_sha256: str, producer_root: Path,
             verifier_root: Path) -> "PinnedCompatibilityPolicyV1":
        value = cls(Path(path).read_bytes(), _digest(expected_sha256),
                    Path(producer_root).resolve(), Path(verifier_root).resolve())
        value.validate()
        return value

    def validate(self) -> dict:
        if hashlib.sha256(self.raw).hexdigest() != self.expected_sha256:
            raise C8CompatibilityError("独立固定的 policy hash 不匹配")
        p = _object(strict_json(self.raw), "schema version producer_sources verifier_sources verifier_identity comparison_contracts pairs python policy_identity", "policy")
        _equal([p["schema"], p["version"]], [POLICY_SCHEMA, VERSION], "policy schema/version")
        _equal(p["policy_identity"], identity({k:v for k,v in p.items() if k != "policy_identity"}), "policy identity")
        _equal(p["verifier_identity"], verifier_identity_v1(p["verifier_sources"]), "verifier manifest identity")
        _verify_manifest(self.producer_root, p["producer_sources"])
        _verify_manifest(self.verifier_root, p["verifier_sources"])
        if self.verifier_root != Path(__file__).resolve().parents[2]:
            raise C8CompatibilityError("验证器必须绑定实际运行源码目录")
        _equal(p["python"], {"version":sys.version, "executable_sha256":file_hash(Path(sys.executable)),
                              "hashseed":os.environ.get("PYTHONHASHSEED")}, "解释器/profile")
        if os.environ.get("PYTHONHASHSEED") != "0":
            raise C8CompatibilityError("必须在启动前设置 PYTHONHASHSEED=0")
        if type(p["pairs"]) is not list or not p["pairs"]:
            raise C8CompatibilityError("policy 必须明确登记 old→new 对")
        seen = set()
        for row in p["pairs"]:
            _object(row, "lane artifact_sha256 producer_identity verifier_identity comparison_identity", "pair")
            for key in ("artifact_sha256", "producer_identity", "verifier_identity", "comparison_identity"):
                _digest(row[key])
            _equal(row["verifier_identity"], p["verifier_identity"], "pair verifier")
            _equal(p["comparison_contracts"].get(row["lane"]), comparison_contract_v1(row["lane"]), "comparison policy")
            _equal(row["comparison_identity"], comparison_contract_v1(row["lane"])["identity"], "pair comparison")
            key = canonical(row)
            if key in seen:
                raise C8CompatibilityError("policy pair 重复")
            seen.add(key)
        return p


def _producer_identity(raw: dict, lane: str) -> str:
    if lane == "D_CORPUS":
        _object(raw, "schema producer_identity artifacts", "D corpus")
        _equal(raw["schema"], CORPUS_SCHEMA, "D corpus schema")
        if type(raw["artifacts"]) is not dict or not raw["artifacts"]:
            raise C8CompatibilityError("D 原始 artifacts 不能为空")
        for entry in raw["artifacts"].values():
            _object(entry, "raw_utf8 sha256", "D 原始 artifact")
            data = entry["raw_utf8"].encode("utf-8")
            _equal(hashlib.sha256(data).hexdigest(), entry["sha256"], "D constituent exact bytes")
            _equal(strict_json(data)["c8_d_current_implementation_identity"], raw["producer_identity"], "D constituent producer")
        return _digest(raw["producer_identity"])
    return _digest(raw["g3_binding"]["current_c8_implementation_identity"])


def build_envelope_v1(artifact: bytes, *, lane: str, policy: PinnedCompatibilityPolicyV1) -> bytes:
    p = policy.validate()
    material = dict(schema=SCHEMA, version=VERSION, lane=lane,
                    artifact_sha256=hashlib.sha256(artifact).hexdigest(),
                    producer_identity=_producer_identity(strict_json(artifact), lane),
                    verifier_identity=p["verifier_identity"], policy_identity=p["policy_identity"],
                    policy_version=p["version"], comparison_contract=comparison_contract_v1(lane),
                    scope="DEVELOPMENT_VERIFICATION_ONLY", promotion=False)
    raw = canonical({**material, "envelope_identity":identity(material)})
    validate_envelope_v1(raw, artifact, policy=policy)
    return raw


def validate_envelope_v1(envelope: bytes, artifact: bytes, *, policy: PinnedCompatibilityPolicyV1) -> dict:
    p = policy.validate()
    e = _object(strict_json(envelope), "schema version lane artifact_sha256 producer_identity verifier_identity policy_identity policy_version comparison_contract scope promotion envelope_identity", "envelope")
    _equal([e["schema"], e["version"], e["scope"], e["promotion"]],
           [SCHEMA, VERSION, "DEVELOPMENT_VERIFICATION_ONLY", False], "envelope schema/scope")
    _equal(e["envelope_identity"], identity({k:v for k,v in e.items() if k != "envelope_identity"}), "envelope identity")
    _equal(e["artifact_sha256"], hashlib.sha256(artifact).hexdigest(), "原 artifact exact hash")
    _equal([e["policy_identity"], e["policy_version"]], [p["policy_identity"], p["version"]], "compatibility policy")
    _equal(e["verifier_identity"], p["verifier_identity"], "当前 verifier")
    _equal(e["producer_identity"], _producer_identity(strict_json(artifact), e["lane"]), "原 producer")
    _equal(e["comparison_contract"], comparison_contract_v1(e["lane"]), "exact comparison contract/schema")
    row = {k:e[k] for k in ("lane", "artifact_sha256", "producer_identity", "verifier_identity")}
    row["comparison_identity"] = e["comparison_contract"]["identity"]
    if canonical(row) not in {canonical(v) for v in p["pairs"]}:
        raise C8CompatibilityError("未明确登记的 artifact/producer/verifier 组合")
    return e


@dataclass(frozen=True, slots=True)
class _VerifiedScope:
    policy: PinnedCompatibilityPolicyV1
    producer_sources: Mapping[str, str]
    producer_global_identity: str
    envelope: bytes
    artifact: bytes


def active_v1() -> bool:
    return type(_SCOPE.get()) is _VerifiedScope


def reject_recording_v1() -> None:
    if active_v1():
        raise C8CompatibilityError("compatibility scope 只允许验证，禁止签发执行 artifact 或正式 proof")


@contextmanager
def _verification_scope(envelope: bytes, artifact: bytes, policy: PinnedCompatibilityPolicyV1) -> Iterator[dict]:
    if _SCOPE.get() is not None:
        raise C8CompatibilityError("禁止嵌套兼容 scope")
    e = validate_envelope_v1(envelope, artifact, policy=policy)
    from . import formal_duel
    material = policy.validate()
    scope = _VerifiedScope(policy, MappingProxyType(dict(material["producer_sources"])),
                           formal_duel.implementation_identity(policy.producer_root), envelope, artifact)
    token = _SCOPE.set(scope)
    try:
        yield e
    finally:
        _SCOPE.reset(token)
        policy.validate()  # Fail closed if either source set changed while verifying.


def execution_source_digest_v1(path: Path) -> str | None:
    """原执行身份材料的 source digest；不声称它是当前文件的 digest。"""
    scope = _SCOPE.get()
    if type(scope) is not _VerifiedScope:
        return None
    try:
        relative = Path(path).resolve().relative_to(scope.policy.verifier_root).as_posix()
    except ValueError:
        # Interpreter and external audit evidence retain their real file hashes.
        return None
    try:
        return scope.producer_sources[relative]
    except KeyError as exc:
        raise C8CompatibilityError("原执行 source binding 未登记") from exc


def assert_execution_source_pair_v1(expected: Mapping[Path, str]) -> bool:
    if not active_v1():
        return False
    for path, digest in expected.items():
        _equal(execution_source_digest_v1(path), digest, "原执行固定源码绑定")
    return True  # Current verifier manifest was independently validated at scope entry.


def execution_global_identity_v1() -> str | None:
    scope = _SCOPE.get()
    if type(scope) is not _VerifiedScope:
        return None
    return scope.producer_global_identity


def d_original_artifacts_v1() -> dict:
    scope = _SCOPE.get()
    if type(scope) is not _VerifiedScope:
        raise C8CompatibilityError("需要已验证 D envelope")
    _equal(strict_json(scope.envelope)["lane"], "D_CORPUS", "D lane")
    return strict_json(scope.artifact)["artifacts"]


def d_reexecution_request_v1(request: dict) -> dict | None:
    scope = _SCOPE.get()
    if type(scope) is not _VerifiedScope:
        return None
    originals = [strict_json(v["raw_utf8"].encode("utf-8")) for v in d_original_artifacts_v1().values()]
    if not any(canonical([v["initial_material"],v["commands"]]) == canonical([request["initial_material"],request["commands"]]) for v in originals):
        raise C8CompatibilityError("D request 不属于 envelope 绑定的原执行材料")
    payload = dict(policy_utf8=scope.policy.raw.decode("utf-8"), policy_sha256=scope.policy.expected_sha256,
                   producer_root=str(scope.policy.producer_root), envelope_utf8=scope.envelope.decode("utf-8"),
                   artifact_utf8=scope.artifact.decode("utf-8"), request=request)
    completed = subprocess.run([sys.executable, "-B", "-m", __name__, "--d-worker"],
                               input=canonical(payload), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               cwd=scope.policy.verifier_root, env=dict(os.environ, PYTHONHASHSEED="0", PYTHONDONTWRITEBYTECODE="1"), timeout=30)
    if completed.returncode:
        raise C8CompatibilityError("兼容 D fresh worker 失败：" + completed.stderr.decode("utf-8",errors="replace")[-1500:])
    return strict_json(completed.stdout)


def _d_worker() -> int:
    payload = strict_json(sys.stdin.buffer.read())
    p = PinnedCompatibilityPolicyV1(payload["policy_utf8"].encode("utf-8"), payload["policy_sha256"],
                                    Path(payload["producer_root"]), Path(__file__).resolve().parents[2])
    with _verification_scope(payload["envelope_utf8"].encode("utf-8"), payload["artifact_utf8"].encode("utf-8"), p):
        from . import c8_strict_replay_v1 as d
        request = payload["request"]
        originals = [strict_json(v["raw_utf8"].encode("utf-8")) for v in d_original_artifacts_v1().values()]
        if not any(canonical([v["initial_material"],v["commands"]]) == canonical([request["initial_material"],request["commands"]]) for v in originals):
            raise C8CompatibilityError("子进程 D request splice")
        initial = d.C8ReplayInitialMaterialV1.from_dict(request["initial_material"])
        commands = tuple(d.C8ReplayCommandV1.from_dict(v) for v in request["commands"])
        evidence = d._ReplayExecution(initial).run(commands)
        response = dict(schema="sgs-c8-d-isolated-worker-response-v1", contract_version=1, execution_evidence=evidence.to_dict())
    sys.stdout.buffer.write(canonical(response))
    return 0


def verify_compatibility_v1(envelope: bytes, artifact: bytes, *, policy: PinnedCompatibilityPolicyV1,
                            diagnostic_sink: object | None = None) -> dict:
    with _verification_scope(envelope, artifact, policy) as e:
        if e["lane"] == "D_CORPUS":
            from . import c8_strict_replay_v1 as d
            details = {name:d.strict_reexecute_c8_replay_v1(v["raw_utf8"].encode("utf-8")).to_dict()
                       for name,v in d_original_artifacts_v1().items()}
        else:
            from . import c8_timed_8p_full_game_production_replay_v1 as g3
            full = e["lane"] == "G3_FULL_TIMED"
            parsed = g3.preflight_composition_v1(artifact, full_game=full)
            timed = g3._fresh_timed(parsed, diagnostic_sink=diagnostic_sink)
            g3._equal(timed["ordered_sequence"], parsed["ordered_production_sequence"], "compat complete ordered production sequence")
            details = {"timed":timed, "preflight":"PASS"}
    result = dict(schema=RESULT_SCHEMA, version=1, status="MATCH", scope="NEW_VERIFIER_DEVELOPMENT_EVIDENCE_ONLY",
                  artifact_sha256=e["artifact_sha256"], producer_identity=e["producer_identity"],
                  verifier_identity=e["verifier_identity"], policy_identity=e["policy_identity"],
                  envelope_identity=e["envelope_identity"], comparison_contract=e["comparison_contract"],
                  comparison_results={k:"MATCH" for k in e["comparison_contract"]["required_comparisons"]},
                  details=details, promotion=False, cell_proof=False, historical_status_updated=False)
    return {**result, "result_identity":identity(result)}


if __name__ == "__main__":
    # Use the package module instance so integrations share the same ContextVar.
    from scripts.sgs_engine import c8_timed_replay_version_compatibility_v1 as module
    if sys.argv[1:] == ["--d-worker"]:
        raise SystemExit(module._d_worker())
    raise SystemExit("需要显式兼容调用方和独立 policy trust anchor")
