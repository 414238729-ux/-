# -*- coding: utf-8 -*-
"""原生 replay provenance 的廉价边界测试，不执行游戏或 replay。"""
import copy
import json
import os
import functools
from pathlib import Path
import pytest
from scripts import c8_native_replay_proof_v1 as n


@pytest.fixture(autouse=True)
def prohibit_all_replay_workers(monkeypatch):
    for owner,name in [(n,'worker'),(n,'supervise'),(n.g3,'_fresh_inner'),(n.g3,'_fresh_timed'),(n.g3,'_cold_workers')]:
        original=getattr(owner,name)
        @functools.wraps(original)
        def forbidden(*args,**kwargs):pytest.fail('静态 provenance/proof 测试禁止执行 replay')
        monkeypatch.setattr(owner,name,forbidden)


@pytest.mark.parametrize('cell,seed',[('C8G-FG-000',0),('C8G-FG-001',1),('C8G-FG-049',49)])
def test_native_cell_generic_valid(cell,seed):
    n.cell(dict(cell_id=cell,seed=seed))


@pytest.mark.parametrize('cell,seed',[('C8G-FG-000',1),('C8G-FG-001',0),('C8G-FG-001',49),('C8G-FG-001',True),('C8G-FG-*',1),('C8G-FG-002',2),('C8G-FG-049',1)])
def test_native_cell_wrong_pair(cell,seed):
    with pytest.raises(ValueError):n.cell(dict(cell_id=cell,seed=seed))


def test_process_instance_is_real_and_stable():
    a=n.process_identity(); b=n.process_identity()
    assert a==b and a['pid']==os.getpid() and a['creation_filetime']>0
    assert a['parent_pid']==os.getppid()
    assert a['image_sha256']==n.environment()['runtime_image_sha256']


def test_unknown_process_fail_closed():
    with pytest.raises(OSError):n.process_identity(0)


def test_independent_pin_and_exclusive_writer(tmp_path):
    p=tmp_path/'x.json';n.write(p,{'a':1})
    assert n.pinned(p,n.sha(p))=={'a':1}
    with pytest.raises(ValueError):n.pinned(p,'0'*64)
    with pytest.raises(FileExistsError):n.write(p,{'a':2})
    assert n.read(p)=={'a':1}


def test_claim_self_hash_is_not_policy_authority(tmp_path):
    p=tmp_path/'fake.json';n.write(p,n.seal({'schema':'fake','status':'PASSED'}))
    with pytest.raises(ValueError):n.Policy(p,n.sha(p)).validate()


def test_comparison_contract_is_existing_exact_contract():
    for kind in ('INNER','TIMED'):
        assert n.comparison(kind)==n.old.comparison_contract_v1(kind)
    with pytest.raises(ValueError):n.comparison('UNKNOWN')


@pytest.fixture(scope='module')
def real():
    path=os.environ.get('C8_NATIVE_PROOF_TEST_CONFIG')
    if not path:pytest.skip('需原生执行完成后的独立 authority；不自动执行 replay')
    q=json.loads(Path(path).read_bytes())
    return q,n.Policy(Path(q['policy']),q['policy_pin']),n.read(q['inner']),n.read(q['timed']),n.read(q['latch'])


@pytest.mark.parametrize('mutation',['seed','cell','natural','verifier','generation','inner','timed','missing','schema','policy','global','producer'])
def test_current_latch_tamper_even_rehashed_rejected(real,mutation):
    q,p,i,t,l=real;v=copy.deepcopy(l)
    if mutation=='seed':v['seed']=49
    elif mutation=='cell':v['cell_id']='C8G-FG-000'
    elif mutation=='natural':v['natural_sha256']='0'*64
    elif mutation=='verifier':v['current_verifier_identity']='0'*64
    elif mutation=='generation':v['generation']+=1
    elif mutation in ('inner','timed'):v[mutation]='0'*64
    elif mutation=='missing':del v['bindings']['TIMED']
    elif mutation=='schema':v['schema']='C8CurrentReplayAdoptionLatchV1'
    elif mutation=='policy':v['policy_sha256']='0'*64
    elif mutation=='global':v['global_source_identity']='0'*64
    elif mutation=='producer':v['bindings']['INNER']['natural_producer_identity']='0'*64
    v=n.seal({k:x for k,x in v.items() if k!='identity'})
    with pytest.raises(ValueError):n.validate_latch(v,p,i,t)


@pytest.mark.parametrize('mutation',['seed','cell','result','producer','verifier','schema','policy','kind','execution','worker','missing'])
def test_adoption_envelope_tamper_rejected(real,mutation):
    q,p,i,t,l=real;v=copy.deepcopy(i);b=v['binding']
    mapping=dict(result='result_sha256',producer='natural_producer_identity',verifier='current_verifier_identity',execution='original_execution_identity',worker='worker_verifier_identity')
    if mutation in mapping:b[mapping[mutation]]='0'*64
    elif mutation=='seed':b['seed']=0
    elif mutation=='cell':b['cell_id']='C8G-FG-049'
    elif mutation=='schema':v['schema']='unknown'
    elif mutation=='policy':v['policy_sha256']='0'*64
    elif mutation=='kind':b['kind']='TIMED'
    elif mutation=='missing':del b['provenance_identity']
    v=n.seal({k:x for k,x in v.items() if k!='identity'})
    with pytest.raises(ValueError):n.latch(p,v,t)


def test_valid_current_latch(real):
    q,p,i,t,l=real;n.validate_latch(l,p,i,t)


def test_result_raw_whitespace_tamper_rejected(real,monkeypatch):
    q,p,i,t,l=real;policy=n.read(p.path);target=Path(policy['files']['INNER']['result']['path']);original=Path.read_bytes
    def altered(path):
        v=original(path)
        return v+b'\n' if path==target else v
    monkeypatch.setattr(Path,'read_bytes',altered)
    with pytest.raises(ValueError):n.materials(p)


def test_missing_component_rejected(real,monkeypatch):
    q,p,i,t,l=real;policy=n.read(p.path);target=Path(policy['files']['TIMED']['exit']['path']);original=Path.read_bytes
    def missing(path):
        if path==target:raise FileNotFoundError('缺少 exit receipt')
        return original(path)
    monkeypatch.setattr(Path,'read_bytes',missing)
    with pytest.raises((ValueError,OSError)):n.materials(p)


@pytest.mark.parametrize('mutation',['valid','worker_pid','parent_instance','command','claim_input','claim_verifier','not_fresh','invocation','result_schema','result_status','result_config','comparison','execution','exit_code','exit_kind','preflight','extra_field'])
def test_rehashed_native_provenance_inconsistency_rejected(real,tmp_path,mutation):
    # 绕开外层文件 pin 的独立单元测试：为变更文件重算其 hash 和引用，
    # 仍必须被内层 provenance 关系拒绝。完整 policy 测试另验独立 pin。
    _,policy,_,_,_=real;p,q=policy.validate();p=copy.deepcopy(p);q=copy.deepcopy(q)
    kind='INNER';old=p['files'][kind];values={k:n.read(v['path']) for k,v in old.items()}
    q['output_root']=str(tmp_path)
    paths=dict(claim=tmp_path/kind/'CLAIM.json',preflight=tmp_path/kind/'PREFLIGHT.json',result=tmp_path/kind/'RESULT.json',supervisor=tmp_path/(kind+'_SUPERVISOR.json'),process=tmp_path/(kind+'_PROCESS.json'),exit=tmp_path/(kind+'_EXIT.json'))
    (tmp_path/kind).mkdir()
    claim,result,receipt=values['claim'],values['result'],values['exit']
    if mutation=='worker_pid':claim['process']['pid']+=1
    elif mutation=='parent_instance':claim['parent_process']['creation_filetime']+=1
    elif mutation=='command':claim['command'][-1]='TIMED'
    elif mutation=='claim_input':claim['natural_sha256']='0'*64
    elif mutation=='claim_verifier':claim['worker_verifier_identity']='0'*64
    elif mutation=='not_fresh':claim['fresh_from_step0']=False
    elif mutation=='invocation':claim['invocation']=2
    elif mutation=='result_schema':result['schema']='C8FullTimedReplayResultV1'
    elif mutation=='result_status':result['status']='FAILED'
    elif mutation=='result_config':result['config_sha256']='0'*64
    elif mutation=='comparison':result['comparison_results']={}
    elif mutation=='execution':result['execution_identity']='0'*64
    elif mutation=='exit_code':receipt['exit_code']=1
    elif mutation=='exit_kind':receipt['kind']='TIMED'
    elif mutation=='preflight':values['preflight']['status']='FAILED'
    elif mutation=='extra_field':result['trusted']=True
    for key in ['supervisor','process','claim','preflight','result','exit']:
        value=values[key]
        if key=='preflight':value['claim_sha256']=n.sha(paths['claim'])
        if key=='result':
            value['claim_sha256']=n.sha(paths['claim']);value['preflight_sha256']=n.sha(paths['preflight'])
        if key=='exit':value['result_sha256']=n.sha(paths['result'])
        n.write(paths[key],n.seal({k:v for k,v in value.items() if k!='identity'}))
    p['files'][kind]={k:n.ptr(v) for k,v in paths.items()}
    if mutation=='valid':assert n.validate_result(q,p,kind)['status']=='PASSED'
    else:
        with pytest.raises(ValueError):n.validate_result(q,p,kind)
