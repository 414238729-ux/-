"""仅用于冻结 C8 的原 nodeid 测试；隔离导入和源码，禁止把开发树放行成旧身份。"""
from pathlib import Path
import hashlib
import json
import os
import subprocess
import sys

FROZEN_COMMIT = "9991abc8091943e7316875734bae2e5967cc6e64"
HISTORY = Path("C:/Users/ASUS/.codex/visualizations/2026/09/07/01a07b9b-7e1b-75e1-9392-8be3b6b5a941/IDENTITY_MIGRATION.json")
HISTORY_SHA256 = "0e151444acca694dd10a6e9955d9a5694e84ba16bcd7465a552434210329fd7a"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(root, *args):
    return subprocess.check_output(["git", "--no-optional-locks", "-c", "safe.directory="+str(root),
        "-c", "core.autocrlf=false", *args], cwd=root, stderr=subprocess.PIPE)


def extract_frozen(repo, frozen):
    """独立临时 Git index + 只读共享对象库；不改用户 checkout、refs 或 tag。"""
    assert git(repo,"rev-parse","c8-timed-8p-deterministic-virtual-time-v1-audited^{}").decode().strip()==FROZEN_COMMIT
    common=Path(git(repo,"rev-parse","--git-common-dir").decode().strip())
    if not common.is_absolute():common=(repo/common).resolve()
    frozen.mkdir(exist_ok=False)
    git(frozen,"init","--quiet")
    (frozen/".git/objects/info/alternates").write_bytes((str(common/"objects").replace("\\","/")+"\n").encode("utf-8"))
    (frozen/".git/HEAD").write_bytes((FROZEN_COMMIT+"\n").encode("ascii"))
    git(frozen,"read-tree",FROZEN_COMMIT)
    git(frozen,"checkout-index","--all")
    expected={}
    for entry in git(repo,"ls-tree","-r","-z",FROZEN_COMMIT).split(b"\0"):
        if not entry:continue
        header,name=entry.split(b"\t",1); mode,kind,oid=header.split()
        assert kind==b"blob" and mode in (b"100644",b"100755")
        name=name.decode("utf-8"); blob=(frozen/name).read_bytes()
        actual=hashlib.sha1(b"blob "+str(len(blob)).encode()+b"\0"+blob).hexdigest()
        assert actual==oid.decode(), "FROZEN_SOURCE_DRIFT:"+name
        # Git 在提交时归一行尾，但旧 C8 raw-byte pins 包含当时的混合行尾。
        # 仅当当前文件归一后逐字节等于固定 commit blob，才保留其原始包装。
        # 开发内容变化的文件绝不借此进入冻结树；旧 verifier 的 raw pins 仍严格检查。
        current=repo/name
        if current.is_file():
            raw=current.read_bytes()
            if raw.replace(b"\r\n",b"\n")==blob:
                blob=raw
                (frozen/name).write_bytes(raw)
        expected[name]=hashlib.sha256(blob).hexdigest()
    return expected


def main():
    request=json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    assert request["commit"]==FROZEN_COMMIT
    repo=Path(request["repo"]); frozen=Path(request["frozen_root"]); evidence=Path(request["evidence"])
    expected=extract_frozen(repo,frozen)
    for name in {node.split("::",1)[0] for node in request["nodeids"]}:
        assert digest(repo/name)==expected[name], "冻结测试本身已改动，请在当前开发测试中显式验收："+name
    os.chdir(frozen); sys.path.insert(0,str(frozen))
    # 第一次 production import 必须来自冻结树，不能复用父进程的模块缓存。
    from scripts.sgs_engine import c8_baseline_launcher_v1 as launch
    assert Path(launch.__file__).resolve().is_relative_to(frozen)
    from scripts.current_c8_implementation_pin import C8_CURRENT_IMPLEMENTATION_IDENTITY
    assert launch.g3.formal_duel.implementation_identity()==C8_CURRENT_IMPLEMENTATION_IDENTITY
    # 仅测试的 report-only harness；所有请求执行的代码路径仍由原测试禁止。
    harness=evidence/"never_launch.py"
    harness.write_text("raise AssertionError('冻结测试禁止启动 natural/replay/harness')\n",encoding="utf-8")
    release={"schema":"C8BaselineLaunchReleaseV1", "repo_root":str(frozen),
        "source_sha256":expected,
        "shared_implementation_identity":launch.contract.identity_v1(launch.g3.current_c8_g3_development_snapshot_v1(frozen)),
        "interpreter":str(Path(sys.executable).resolve()), "interpreter_sha256":digest(Path(sys.executable)),
        "execution_order_profile":launch.runner.validate_execution_order_profile_v1(),
        "run_parent":str(evidence/"unused-runs"), "harness_path":str(harness),
        "harness_sha256":digest(harness), "external_source_sha256":{str(harness):digest(harness)}}
    release_path=evidence/"TEST_ONLY_RELEASE.json"
    release_path.write_text(json.dumps(release,ensure_ascii=False),encoding="utf-8")
    assert digest(HISTORY)==HISTORY_SHA256, "历史迁移资料漂移，不允许替换历史 pin"
    os.environ.update(C8_BASELINE_TEST_RELEASE=str(release_path),
        C8_BASELINE_TEST_RELEASE_SHA256=digest(release_path), C8_BASELINE_TEST_HISTORY_MIGRATION=str(HISTORY))
    import pytest
    class ActualReports:
        def pytest_runtest_logreport(self, report):
            with (evidence/"reports.jsonl").open("a",encoding="utf-8") as stream:
                stream.write(json.dumps(report._to_json(),ensure_ascii=False)+"\n")
    code=pytest.main(["-q","-p","no:cacheprovider","--rootdir",str(frozen),
        "--confcutdir",str(frozen),"--basetemp",str(evidence/"bt"),*request["nodeids"]],plugins=[ActualReports()])
    same=all(digest(frozen/name)==value for name,value in expected.items())
    (evidence/"source_verified.json").write_text(json.dumps({"frozen_commit":FROZEN_COMMIT,
        "source_sha256":expected,"before_after_equal":same,"pytest_exit_code":int(code)},ensure_ascii=False,indent=2),encoding="utf-8")
    return int(code) if same else 3


if __name__=="__main__":
    raise SystemExit(main())
