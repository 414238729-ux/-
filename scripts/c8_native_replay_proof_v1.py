# -*- coding: utf-8 -*-
"""原生 fresh replay provenance、显式采纳与 cell proof；旧验收入口不变。

独立 config/policy/audit SHA256 必须由可信调用方传入，不从待验对象取 pin。
本模块位于引擎目录外：完整 verifier inventory 包含本文件，游戏身份不改。
"""
from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

from scripts.sgs_engine import c8_timed_replay_version_compatibility_v1 as c
from scripts.sgs_engine import c8_verified_replay_result_adoption_v1 as old
from scripts.sgs_engine import c8_timed_8p_full_game_production_replay_v1 as g3
from scripts.sgs_engine import c8_timed_8p_full_game_contract_v1 as g1
from scripts.sgs_engine import formal_duel

MODULE = 'scripts.c8_native_replay_proof_v1'
AUTHORITY = 'NATIVE_FRESH_RESULT_ADOPTION_V1'
CONTRACT = c.identity(dict(schema='C8NativeReplayProvenanceContractV1', version=1,
    comparison='UNCHANGED_G3_FRESH_INNER_AND_FRESH_TIMED_EXACT',
    trust='INDEPENDENT_CONFIG_POLICY_AUDIT_PINS',
    workers='FRESH_OS_PROCESS_PER_KIND_CLAIM_RESULT_EXIT_RECEIPT',
    adoption='EXACT_CELL_SEED_INPUT_WORKER_VERIFIER_RESULT_PAIR',
    history='NO_REWRITE_NO_RETROACTIVE_PROVENANCE'))


def root(): return Path(__file__).resolve().parents[1]
def sha(path): return c.file_hash(Path(path))
def eq(a, b, label): return c._equal(a, b, label)
def obj(v, keys, label): return c._object(v, keys, label)
def seal(v, key='identity'): return {**v, key: c.identity(v)}
def read(p): return c.strict_json(Path(p).read_bytes())
def write(p, v):
    with Path(p).open('xb') as f:
        f.write(c.canonical(v)); f.flush(); os.fsync(f.fileno())
def ptr(p): return dict(path=str(Path(p).resolve()), sha256=sha(p))
def pointer(v):
    obj(v, 'path sha256', '固定文件指针')
    if type(v['path']) is not str or not Path(v['path']).is_absolute():
        raise ValueError('固定文件需要绝对路径')
    raw=Path(v['path']).read_bytes()
    eq(hashlib.sha256(raw).hexdigest(), c._digest(v['sha256']), '固定文件字节')
    return raw
def pinned(p, expected):
    raw=Path(p).read_bytes(); eq(hashlib.sha256(raw).hexdigest(),c._digest(expected),'独立信任 pin')
    v=c.strict_json(raw)
    if raw!=c.canonical(v):raise ValueError('必须使用 canonical 文件字节')
    return v
def self_id(v): eq(v['identity'],c.identity({k:x for k,x in v.items() if k!='identity'}),'材料 identity')
def environment():
    return dict(version=sys.version,executable_sha256=sha(sys.executable),runtime_image_sha256=process_identity()['image_sha256'],hashseed=os.environ.get('PYTHONHASHSEED'))
def cell(v):
    if type(v['seed']) is not int: raise ValueError('seed 必须为整数')
    ref=g1.FullGameCellRefV1(v['cell_id'],g1.C8_G1_BASE_MODE_ID,v['seed'])
    if ref not in g1.CANONICAL_BASELINE_CELLS_V1: raise ValueError('cell/seed 必须为正式 baseline 精确配对')
def comparison(kind): return old.comparison_contract_v1(kind)


def process_identity(pid=None):
    """绑定 PID + Windows creation FILETIME；无权打开即拒绝，不猜测身份。"""
    if os.name!='nt': raise ValueError('此正式 worker 需要 Windows 进程实例证明')
    pid=os.getpid() if pid is None else pid
    k=ctypes.WinDLL('kernel32',use_last_error=True)
    k.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]; k.OpenProcess.restype=wintypes.HANDLE
    k.GetProcessTimes.argtypes=[wintypes.HANDLE]+[ctypes.POINTER(wintypes.FILETIME)]*4
    k.QueryFullProcessImageNameW.argtypes=[wintypes.HANDLE,wintypes.DWORD,wintypes.LPWSTR,ctypes.POINTER(wintypes.DWORD)]
    k.CloseHandle.argtypes=[wintypes.HANDLE]
    h=k.OpenProcess(0x1000,False,pid)
    if not h: raise OSError(ctypes.get_last_error(),'无法打开 worker 进程实例')
    try:
        times=[wintypes.FILETIME() for _ in range(4)]
        if not k.GetProcessTimes(h,*[ctypes.byref(t) for t in times]): raise OSError('读取创建时间失败')
        buf=ctypes.create_unicode_buffer(32768); n=wintypes.DWORD(len(buf))
        if not k.QueryFullProcessImageNameW(h,0,buf,ctypes.byref(n)): raise OSError('读取实际进程映像失败')
        class Entry(ctypes.Structure):
            _fields_=[('dwSize',wintypes.DWORD),('cntUsage',wintypes.DWORD),('th32ProcessID',wintypes.DWORD),('th32DefaultHeapID',ctypes.c_size_t),('th32ModuleID',wintypes.DWORD),('cntThreads',wintypes.DWORD),('th32ParentProcessID',wintypes.DWORD),('pcPriClassBase',wintypes.LONG),('dwFlags',wintypes.DWORD),('szExeFile',wintypes.WCHAR*260)]
        k.CreateToolhelp32Snapshot.argtypes=[wintypes.DWORD,wintypes.DWORD];k.CreateToolhelp32Snapshot.restype=wintypes.HANDLE
        k.Process32FirstW.argtypes=[wintypes.HANDLE,ctypes.POINTER(Entry)];k.Process32NextW.argtypes=k.Process32FirstW.argtypes
        snap=k.CreateToolhelp32Snapshot(2,0)
        if snap==wintypes.HANDLE(-1).value:raise OSError('进程父实例枚举失败')
        try:
            entry=Entry();entry.dwSize=ctypes.sizeof(entry);ok=k.Process32FirstW(snap,ctypes.byref(entry));parent=None
            while ok:
                if entry.th32ProcessID==pid:parent=int(entry.th32ParentProcessID);break
                ok=k.Process32NextW(snap,ctypes.byref(entry))
            if parent is None:raise OSError('进程父实例未知')
        finally:k.CloseHandle(snap)
        return dict(pid=pid,parent_pid=parent,creation_filetime=(times[0].dwHighDateTime<<32)|times[0].dwLowDateTime,
                    image=str(Path(buf.value).resolve()),image_sha256=sha(buf.value))
    finally: k.CloseHandle(h)


CONFIG_KEYS='schema version contract_identity cell_id seed natural natural_provenance worker_root worker_sources worker_verifier_identity worker_g3_binding python interpreter output_root authorization comparisons identity'
def load_config(path, pin):
    q=pinned(path,pin); obj(q,CONFIG_KEYS,'worker config'); self_id(q); cell(q)
    eq([q['schema'],q['version'],q['contract_identity']],['C8NativeReplayExecutionConfigV1',1,CONTRACT],'config schema')
    c._verify_manifest(Path(q['worker_root']),q['worker_sources'])
    eq(q['worker_verifier_identity'],c.verifier_identity_v1(q['worker_sources']),'worker 源码身份')
    eq(q['python'],environment(),'原 worker 环境')
    eq(q['python']['hashseed'],'0','启动前 hashseed')
    eq(sha(q['interpreter']),q['python']['executable_sha256'],'解释器')
    eq(q['authorization'],f"C8_NATIVE_REPLAY_{q['cell_id']}_SEED_{q['seed']}_INNER_TIMED_ONLY",'exact execution authorization')
    eq(q['comparisons'],{k:comparison(k) for k in ('INNER','TIMED')},'原 exact 比较合同')
    pointer(q['natural'])
    obj(q['natural_provenance'],'launch_plan session_claim process_metadata run_result terminal_evidence','natural provenance')
    for v in q['natural_provenance'].values(): pointer(v)
    return q


def command(q,path,pin,kind):
    if kind not in ('INNER','TIMED'):raise ValueError('worker kind 非法')
    return [q['interpreter'],'-B','-m',MODULE,'worker','--config',str(Path(path).resolve()),'--pin',pin,'--kind',kind]


def natural_material(q):
    d=g3.preflight_composition_v1(pointer(q['natural']),full_game=True)
    eq([d['cell_id'],d['timed_artifact']['seed']],[q['cell_id'],q['seed']],'natural cell/seed')
    eq(d['g3_binding'],q['worker_g3_binding'],'exact producer / worker G3 配对')
    p={k:c.strict_json(pointer(v)) for k,v in q['natural_provenance'].items() if k!='terminal_evidence'}
    ids=p['launch_plan']['identities']
    eq(p['session_claim']['identities'],ids,'natural claim identities')
    eq(p['process_metadata']['identities'],ids,'natural process identities')
    eq([p['session_claim']['cell_id'],p['session_claim']['seed'],p['session_claim']['step_start'],p['session_claim']['resume']], [q['cell_id'],q['seed'],0,False],'natural step0 claim')
    eq(ids['cell_execution_identity'],d['timed_artifact']['cell_execution_identity'],'natural execution identity')
    eq(p['run_result']['terminal_evidence']['sha256'],q['natural_provenance']['terminal_evidence']['sha256'],'natural terminal evidence')
    return d


def worker(path,pin,kind):
    q=load_config(path,pin)
    eq(str(root()),str(Path(q['worker_root']).resolve()),'worker 必须从固定源码域运行')
    out=Path(q['output_root'])/kind; out.mkdir(exist_ok=False)
    argv=command(q,path,pin,kind)
    eq(sys.argv[1:],argv[4:],'实际 worker 参数')
    claim=seal(dict(schema='C8NativeReplayWorkerClaimV1',version=1,config_sha256=pin,
        kind=kind,cell_id=q['cell_id'],seed=q['seed'],process=process_identity(),parent_process=process_identity(os.getppid()),
        command=argv,worker_verifier_identity=q['worker_verifier_identity'],natural_sha256=q['natural']['sha256'],
        comparison_contract=q['comparisons'][kind],fresh_from_step0=True,invocation=1,started_ns=time.time_ns()))
    write(out/'CLAIM.json',claim)
    ack=Path(q['output_root'])/(kind+'_PROCESS.json'); deadline=time.monotonic()+60
    while not ack.exists():
        if time.monotonic()>deadline:raise ValueError('父进程独立观察 handshake 超时，未运行 replay')
        time.sleep(0.05)
    eq(read(ack)['process'],claim['process'],'父进程独立确认 worker 实例')
    d=natural_material(q)
    write(out/'PREFLIGHT.json',seal(dict(status='PASSED',claim_sha256=sha(out/'CLAIM.json'),artifact_identity=d['artifact_identity'],cell_execution_identity=d['timed_artifact']['cell_execution_identity'])))
    start=time.monotonic()
    formal=g3._fresh_inner(d) if kind=='INNER' else g3._fresh_timed(d)
    eq(formal['ordered_sequence'],d['ordered_production_sequence'],'完整 ordered sequence')
    eq(formal['private_record_identity'],d['timed_artifact']['private_production_record']['record_identity'],'完整 private record')
    eq(formal['status'],'MATCH','fresh 比较结果')
    load_config(path,pin)
    result=seal(dict(schema='C8NativeFreshReplayResultV1',version=1,contract_identity=CONTRACT,
        cell_id=q['cell_id'],seed=q['seed'],kind=kind,status='PASSED',comparison_status='MATCH',
        config_sha256=pin,claim_sha256=sha(out/'CLAIM.json'),preflight_sha256=sha(out/'PREFLIGHT.json'),
        original_producer_identity=d['g3_binding']['current_c8_implementation_identity'],
        original_cell_execution_identity=d['timed_artifact']['cell_execution_identity'],natural_sha256=q['natural']['sha256'],
        worker_verifier_identity=q['worker_verifier_identity'],execution_identity=c.identity(claim),
        comparison_contract=q['comparisons'][kind],comparison_results={x:'MATCH' for x in q['comparisons'][kind]['required_comparisons']},
        formal_result=formal,terminal_result=d['timed_artifact']['private_production_record']['outcome'],
        accepted=d['timed_artifact']['completed_production_steps'],windows=d['timed_artifact']['completed_windows'],
        elapsed_seconds=time.monotonic()-start,completed_ns=time.time_ns(),new_execution=True,cell_proof=False))
    write(out/'RESULT.json',result)


def supervise(path,pin,kind):
    q=load_config(path,pin); out=Path(q['output_root']); out.mkdir(exist_ok=True)
    launch=out/(kind+'_SUPERVISOR.json')
    write(launch,seal(dict(kind=kind,config_sha256=pin,process=process_identity(),command=command(q,path,pin,kind))))
    with (out/(kind+'.stdout')).open('xb') as so,(out/(kind+'.stderr')).open('xb') as se:
        proc=subprocess.Popen(command(q,path,pin,kind),cwd=q['worker_root'],env=dict(os.environ),stdout=so,stderr=se)
        launcher_process=process_identity(proc.pid)
        claim_path=out/kind/'CLAIM.json';deadline=time.monotonic()+60
        while not claim_path.exists():
            if proc.poll() is not None or time.monotonic()>deadline:raise ValueError('worker 未产生 claim，禁止验收')
            time.sleep(0.05)
        claim=read(claim_path);observed=process_identity(claim['process']['pid'])
        eq(observed,claim['process'],'独立观察 worker 实例')
        eq(claim['parent_process'],launcher_process,'venv launcher 父实例')
        eq(observed['parent_pid'],launcher_process['pid'],'worker OS 父进程')
        eq(launcher_process['parent_pid'],os.getpid(),'launcher OS 父进程')
        write(out/(kind+'_PROCESS.json'),seal(dict(kind=kind,process=observed,launcher_process=launcher_process,supervisor_sha256=sha(launch))))
        code=proc.wait()
    receipt=seal(dict(schema='C8NativeReplayExitReceiptV1',kind=kind,config_sha256=pin,
        supervisor_sha256=sha(launch),process_record_sha256=sha(out/(kind+'_PROCESS.json')),process=observed,
        exit_code=code,result_sha256=sha(out/kind/'RESULT.json') if (out/kind/'RESULT.json').exists() else None,completed_ns=time.time_ns()))
    write(out/(kind+'_EXIT.json'),receipt)
    if code: raise ValueError('fresh worker 失败；保留全部原件，不自动重试')
    print(json.dumps(dict(kind=kind,status='COMPLETED',receipt=ptr(out/(kind+'_EXIT.json')))))


@dataclass(frozen=True)
class Policy:
    path: Path
    pin: str

    def validate(self):
        p=pinned(self.path,self.pin)
        obj(p,'schema version contract_identity cell_id seed config current_sources current_verifier_identity global_source_identity source_fingerprint files pairs generation supersedes identity','native adoption policy')
        self_id(p); cell(p)
        eq([p['schema'],p['version'],p['contract_identity']],['C8NativeAdoptionPolicyV1',1,CONTRACT],'adoption policy schema')
        c._verify_manifest(root(),p['current_sources'])
        eq(p['current_verifier_identity'],c.verifier_identity_v1(p['current_sources']),'current verifier')
        eq(p['source_fingerprint'],c.identity(p['current_sources']),'current fingerprint')
        eq(p['global_source_identity'],formal_duel.implementation_identity(root()),'global source')
        if type(p['generation']) is not int or p['generation']<1:raise ValueError('generation 非法')
        if type(p['supersedes']) is not list or not p['supersedes']:raise ValueError('必须保留原结果身份')
        for v in p['supersedes']:pointer(v)
        pointer(p['config']); q=load_config(p['config']['path'],p['config']['sha256'])
        eq([p['cell_id'],p['seed']],[q['cell_id'],q['seed']],'policy/config pair')
        obj(p['pairs'],'INNER TIMED','exact pair registry')
        obj(p['files'],'INNER TIMED','worker files registry')
        for v in p['files'].values():
            obj(v,'claim preflight result supervisor process exit','worker provenance files')
            for entry in v.values():pointer(entry)
        return p,q


def validate_result(q,p,kind):
    f=p['files'][kind]; v={k:c.strict_json(pointer(x)) for k,x in f.items()}
    claim,result,receipt=v['claim'],v['result'],v['exit']
    for x in v.values():self_id(x)
    obj(v['preflight'],'status claim_sha256 artifact_identity cell_execution_identity identity','preflight')
    obj(v['supervisor'],'kind config_sha256 process command identity','supervisor')
    obj(v['process'],'kind process launcher_process supervisor_sha256 identity','parent process record')
    obj(receipt,'schema kind config_sha256 supervisor_sha256 process_record_sha256 process exit_code result_sha256 completed_ns identity','exit receipt')
    eq(receipt['schema'],'C8NativeReplayExitReceiptV1','exit schema')
    for x in (v['supervisor'],v['process'],receipt):eq(x['kind'],kind,'parent kind')
    eq(v['supervisor']['config_sha256'],p['config']['sha256'],'parent config pin')
    eq(v['process']['supervisor_sha256'],f['supervisor']['sha256'],'parent record supervisor pin')
    expected_paths={'claim':Path(q['output_root'])/kind/'CLAIM.json','preflight':Path(q['output_root'])/kind/'PREFLIGHT.json','result':Path(q['output_root'])/kind/'RESULT.json',
        'supervisor':Path(q['output_root'])/(kind+'_SUPERVISOR.json'),'process':Path(q['output_root'])/(kind+'_PROCESS.json'),'exit':Path(q['output_root'])/(kind+'_EXIT.json')}
    eq({k:x['path'] for k,x in f.items()},{k:str(x.resolve()) for k,x in expected_paths.items()},'原生 writer 路径')
    obj(claim,'schema version config_sha256 kind cell_id seed process parent_process command worker_verifier_identity natural_sha256 comparison_contract fresh_from_step0 invocation started_ns identity','worker claim')
    obj(result,'schema version contract_identity cell_id seed kind status comparison_status config_sha256 claim_sha256 preflight_sha256 original_producer_identity original_cell_execution_identity natural_sha256 worker_verifier_identity execution_identity comparison_contract comparison_results formal_result terminal_result accepted windows elapsed_seconds completed_ns new_execution cell_proof identity','native result')
    eq([claim['schema'],claim['version'],claim['fresh_from_step0'],claim['invocation']],['C8NativeReplayWorkerClaimV1',1,True,1],'claim freshness')
    eq([result['schema'],result['version'],result['contract_identity'],result['status'],result['comparison_status'],result['new_execution'],result['cell_proof']],['C8NativeFreshReplayResultV1',1,CONTRACT,'PASSED','MATCH',True,False],'native result schema/status')
    for x in (claim,result):
        for k,value in dict(cell_id=p['cell_id'],seed=p['seed'],kind=kind,config_sha256=p['config']['sha256'],natural_sha256=q['natural']['sha256'],worker_verifier_identity=q['worker_verifier_identity'],comparison_contract=q['comparisons'][kind]).items():eq(x[k],value,'native binding '+k)
    eq(claim['command'],command(q,p['config']['path'],p['config']['sha256'],kind),'exact original command')
    eq(v['supervisor']['command'],claim['command'],'parent command')
    eq(claim['parent_process'],v['process']['launcher_process'],'launcher process instance')
    eq(claim['parent_process']['parent_pid'],v['supervisor']['process']['pid'],'launcher supervisor OS pair')
    eq(claim['process']['parent_pid'],claim['parent_process']['pid'],'worker launcher OS pair')
    eq(claim['process'],v['process']['process'],'supervisor observed child')
    eq(receipt['process'],claim['process'],'completion child instance')
    for proc in (claim['process'],claim['parent_process'],v['supervisor']['process']):
        obj(proc,'pid parent_pid creation_filetime image image_sha256','原进程实例')
        if any(type(proc[k]) is not int or proc[k]<=0 for k in ('pid','creation_filetime')):raise ValueError('原进程实例缺失')
        eq(proc['image_sha256'],q['python']['executable_sha256'] if proc==claim['parent_process'] else q['python']['runtime_image_sha256'],'原进程映像')
    eq(receipt['exit_code'],0,'worker exit')
    eq(receipt['result_sha256'],f['result']['sha256'],'parent result readback')
    eq(receipt['config_sha256'],p['config']['sha256'],'exit config')
    eq(receipt['supervisor_sha256'],f['supervisor']['sha256'],'exit supervisor')
    eq(receipt['process_record_sha256'],f['process']['sha256'],'exit process record')
    eq(result['claim_sha256'],f['claim']['sha256'],'result claim')
    eq(result['preflight_sha256'],f['preflight']['sha256'],'result preflight')
    eq(result['execution_identity'],c.identity(claim),'原 execution identity')
    eq(v['preflight']['claim_sha256'],f['claim']['sha256'],'preflight claim')
    eq(v['preflight']['status'],'PASSED','preflight status')
    eq(result['comparison_results'],{x:'MATCH' for x in q['comparisons'][kind]['required_comparisons']},'all exact comparisons')
    if not claim['started_ns']<=result['completed_ns']<=receipt['completed_ns']:raise ValueError('执行起止记录不一致')
    if type(result['elapsed_seconds']) not in (int,float) or result['elapsed_seconds']<=0:raise ValueError('执行耗时缺失')
    return result


def materials(policy):
    if type(policy) is not Policy:raise ValueError('需要独立固定 policy')
    p,q=policy.validate(); d=natural_material(q)
    results={k:validate_result(q,p,k) for k in ('INNER','TIMED')}
    t=d['timed_artifact']; rows={}
    for kind,r in results.items():
        eq(r['formal_result'],dict(status='MATCH',path='FULL_C6_V1_AND_INCREMENTAL' if kind=='INNER' else 'FRESH_A_B_C_E_TIMED',private_record_identity=t['private_production_record']['record_identity'],ordered_sequence=d['ordered_production_sequence'],full_game=True),'native result exact natural equivalence')
        for key,value in dict(original_producer_identity=d['g3_binding']['current_c8_implementation_identity'],original_cell_execution_identity=t['cell_execution_identity'],terminal_result=t['private_production_record']['outcome'],accepted=t['completed_production_steps'],windows=t['completed_windows']).items():eq(r[key],value,key)
        pre=c.strict_json(pointer(p['files'][kind]['preflight']))
        eq([pre['artifact_identity'],pre['cell_execution_identity']],[d['artifact_identity'],t['cell_execution_identity']],'preflight artifact binding')
        rows[kind]=dict(cell_id=p['cell_id'],seed=p['seed'],kind=kind,natural_sha256=q['natural']['sha256'],natural_producer_identity=r['original_producer_identity'],result_sha256=p['files'][kind]['result']['sha256'],result_identity=r['identity'],original_execution_identity=r['execution_identity'],worker_verifier_identity=r['worker_verifier_identity'],current_verifier_identity=p['current_verifier_identity'],comparison_contract_identity=r['comparison_contract']['identity'],provenance_identity=c.identity(p['files'][kind]))
    policy.validate()
    return p,q,d,rows


def envelope(policy,kind):
    p,q,d,rows=materials(policy);eq(p['pairs'],rows,'独立登记结果配对')
    return _envelope(policy,kind,rows)


def _envelope(policy,kind,rows):
    if kind not in rows:raise ValueError('kind 非法')
    return seal(dict(schema='C8NativeVerifiedReplayResultAdoptionEnvelopeV1',version=1,contract_identity=CONTRACT,policy_sha256=policy.pin,binding=rows[kind]))


def latch(policy,inner,timed):
    p,q,d,rows=materials(policy)
    return _latch(policy,inner,timed,p,q,d,rows)


def _latch(policy,inner,timed,p,q,d,rows):
    eq(p['pairs'],rows,'独立登记结果配对')
    eq(inner,_envelope(policy,'INNER',rows),'inner adoption envelope');eq(timed,_envelope(policy,'TIMED',rows),'timed adoption envelope')
    return seal(dict(schema='C8NativeCurrentReplayLatchV1',version=1,authority=AUTHORITY,contract_identity=CONTRACT,cell_id=p['cell_id'],seed=p['seed'],generation=p['generation'],policy_sha256=policy.pin,current_verifier_identity=p['current_verifier_identity'],source_fingerprint=p['source_fingerprint'],global_source_identity=p['global_source_identity'],natural_sha256=q['natural']['sha256'],original_g1_g2_g3_binding=d['g3_binding'],execution_order_profile=d['timed_artifact']['construction']['execution_order_profile'],inner=inner['identity'],timed=timed['identity'],bindings=rows,supersedes=p['supersedes']))


def validate_latch(value,policy,inner,timed):eq(value,latch(policy,inner,timed),'current latch exact readback')


def audit_subject(policy,inner,timed,current_latch,tests,preservation):
    validate_latch(current_latch,policy,inner,timed)
    return _subject(policy,inner,timed,current_latch,tests,preservation)


def _subject(policy,inner,timed,current_latch,tests,preservation):
    return seal(dict(schema='C8NativeAdoptionAuditSubjectV1',version=1,cell_id=current_latch['cell_id'],seed=current_latch['seed'],policy_sha256=policy.pin,inner_identity=inner['identity'],timed_identity=timed['identity'],latch_identity=current_latch['identity'],tests_sha256=c._digest(tests),preservation_sha256=c._digest(preservation)))


@dataclass(frozen=True)
class Audit:
    report: Path
    report_pin: str
    subject: Path
    subject_pin: str

    def validate(self,policy,inner,timed,current_latch):
        report=pointer(dict(path=str(self.report),sha256=self.report_pin)).decode('utf-8')
        subject=pinned(self.subject,self.subject_pin)
        expected=_subject(policy,inner,timed,current_latch,subject['tests_sha256'],subject['preservation_sha256'])
        eq(subject,expected,'independent audit subject')
        blocks=re.findall(r'```json\s*(\{.*?\})\s*```',report,re.S)
        if len(blocks)!=1:raise ValueError('审计必须恰好一个 JSON decision')
        eq(json.loads(blocks[0]),dict(AUDIT_SUBJECT_SHA256=self.subject_pin,CELL_ID=subject['cell_id'],SEED=subject['seed'],NATIVE_PROVENANCE_CONTRACT='PASSED',EXACT_REPLAY_COMPARATORS='PASSED',CURRENT_LATCH_AUTHORITY='PASSED',HISTORICAL_FAILURE_PRESERVATION='PASSED',ALLOW_CELL_PROOF='YES'),'独立 Grok 全部 verdict')
        return dict(report_sha256=self.report_pin,subject_sha256=self.subject_pin)


def proof(policy,inner,timed,current_latch,audit):
    c.reject_recording_v1()
    if type(audit) is not Audit:raise ValueError('必须提供独立审计 authority')
    p,q,d,rows=materials(policy)
    eq(current_latch,_latch(policy,inner,timed,p,q,d,rows),'current latch exact readback')
    approved=audit.validate(policy,inner,timed,current_latch)
    report=old._formal_report(p,d)
    return seal(dict(schema='C8NativeAdoptionCellProofV1',version=1,contract_identity=CONTRACT,authority=AUTHORITY,cell_id=p['cell_id'],seed=p['seed'],natural_sha256=q['natural']['sha256'],natural_producer_identity=d['g3_binding']['current_c8_implementation_identity'],original_g1_g2_g3_binding=d['g3_binding'],original_cell_execution_identity=d['timed_artifact']['cell_execution_identity'],current_verifier_identity=p['current_verifier_identity'],global_source_identity=p['global_source_identity'],source_fingerprint=p['source_fingerprint'],driver_identity=g1.C8_G1_DRIVER_POLICY_IDENTITY,execution_order_profile=d['timed_artifact']['construction']['execution_order_profile'],policy_sha256=policy.pin,adoption_bindings=rows,inner=inner,timed=timed,current_latch=current_latch,audit=approved,terminal=d['timed_artifact']['private_production_record']['outcome'],accepted=d['timed_artifact']['completed_production_steps'],windows=d['timed_artifact']['completed_windows'],formal_cell_report=report,historical_status_updated=False))


def verify_proof(value,**authority):
    expected=proof(**authority);eq(value,expected,'formal cell proof 全字段 fresh readback')
    return dict(status='PASSED',cell_id=value['cell_id'],proof_identity=value['identity'],new_replay_executions=0)


if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('mode',choices=['worker','supervise']);ap.add_argument('--config',required=True);ap.add_argument('--pin',required=True);ap.add_argument('--kind',required=True,choices=['INNER','TIMED']);args=ap.parse_args()
    (worker if args.mode=='worker' else supervise)(Path(args.config),args.pin,args.kind)
