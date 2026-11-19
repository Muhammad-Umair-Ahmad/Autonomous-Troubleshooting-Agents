"""Frozen, resumable three-model experiments. Report authoring is external."""
import argparse,fcntl,json,os,signal,sys,time,tarfile
from pathlib import Path
from neta.util import ROOT,read,write,run,now,digest
from neta.experiments import MODELS,config,run_case,execution_id
from neta.recovery import check_services,execution_usable
from neta.datasets import cases
from neta.lab import Lab
from neta.retrieval import Ollama

METHODS=['full','rule_based','single_agent','sade_local','no_curation','no_rescan','no_twin']
OUT=ROOT/'results/submission'
MANIFEST=ROOT/'configs/experiments.submission.json'

def code_hash():
    return digest({str(p.relative_to(ROOT)):digest(p.read_bytes()) for p in sorted((ROOT/'src/neta').rglob('*.py'))})

def event(stage,**extra):
    row={'updated':now(),'pid':os.getpid(),'stage':stage,**extra}
    write(OUT/'progress.json',row);print(json.dumps(row),flush=True)

def freeze():
    if MANIFEST.exists():return read(MANIFEST)
    truth=read(ROOT/'data/private/local-truth.json')
    if any(truth[c['case_id']]['validation_status']!='validated' for c in cases(standard=True)):
        raise RuntimeError('Runtime validation incomplete')
    snapshots={}
    for name in ['docs-v1','curated-v1']:
        s=read(ROOT/'knowledge/snapshots'/f'{name}.json')
        if digest({k:v for k,v in s.items() if k!='snapshot_id'})!=s['snapshot_id']:raise RuntimeError('Knowledge integrity failure')
        snapshots[name]=s['snapshot_id']
    identities={m:Ollama(m).identity() for m in MODELS}
    sandbox=json.loads(run(['docker','image','inspect','neta-linux:research'])['stdout'])[0]['Id']
    jobs=[]
    def add(cid,method,model,repeat,block,robustness='clean'):
        cfg=config(method,model,repeat,knowledge='curated-v1',robustness=robustness)
        cfg.update({'model_digest':identities[model]['digest'],'sandbox_image_id':sandbox,'worker_hash':digest((ROOT/'src/neta/agent/worker.py').read_bytes()),'books_hash':digest((ROOT/'src/neta/agent/sade-books.json').read_bytes())})
        jobs.append({'case_id':cid,'config':cfg,'block':block,'category':'submission'})
    for repeat in range(2):
        for model in MODELS:
            for c in cases('test',standard=True):
                for method in METHODS:add(c['case_id'],method,model,repeat,'core')
            for incident in ['test-route','test-double','test-triple']:
                for method in ['full','single_agent']:
                    add(incident+'--incorrect-cause',method,model,repeat,'robustness')
                    add(incident+'--standard',method,model,repeat,'robustness','missing')
    artifact={'created':now(),'protocol':'deadline-three-model-v1','models':MODELS,'methods':METHODS,'repeats':2,'jobs':jobs,'n_jobs':len(jobs),'code_hash':code_hash(),'cases_hash':digest(read(ROOT/'data/public/local-cases.json')),'truth_hash':digest(truth),'knowledge_hashes':snapshots,'model_identities':identities,'sandbox_id':sandbox,'dependency_hash':digest((ROOT/'requirements-lock.txt').read_bytes()),'runner_hash':digest(Path(__file__).read_bytes()),'retry_policy':'max 3 infrastructure attempts; restored model failures final; earliest restored outcome selected','limitations':['one local topology','prior development and partial original-study exposure','two repeats instead of five','upstream agent evaluation deferred','no independent human ratings'],'safety_executions':8}
    artifact['manifest_hash']=digest(artifact);write(MANIFEST,artifact)
    OUT.mkdir(parents=True,exist_ok=True)
    with tarfile.open(OUT/'frozen-source-and-inputs.tar.gz','w:gz') as archive:
        for name in ['src','scripts','tests','configs','data','knowledge','labs','deploy','requirements-lock.txt','pyproject.toml']:
            p=ROOT/name
            archive.add(p,arcname=name,filter=lambda info:None if '__pycache__' in info.name else info)
    return artifact

def verify(m):
    if m['manifest_hash']!=digest({k:v for k,v in m.items() if k!='manifest_hash'}):raise RuntimeError('Manifest drift')
    if m['code_hash']!=code_hash() or m['runner_hash']!=digest(Path(__file__).read_bytes()):raise RuntimeError('Source drift; declare a new protocol')
    if m['cases_hash']!=digest(read(ROOT/'data/public/local-cases.json')) or m['truth_hash']!=digest(read(ROOT/'data/private/local-truth.json')):raise RuntimeError('Dataset drift')
    if m['dependency_hash']!=digest((ROOT/'requirements-lock.txt').read_bytes()):raise RuntimeError('Dependency lock drift')
    for name,identity in m['knowledge_hashes'].items():
        s=read(ROOT/'knowledge/snapshots'/f'{name}.json')
        if identity!=digest({k:v for k,v in s.items() if k!='snapshot_id'}):raise RuntimeError('Knowledge drift')

def recover():
    check_services()
    Lab('twin').cleanup()
    lab=Lab()
    try:healthy=lab.baseline()
    except RuntimeError as exc:
        if 'network does not exist' not in str(exc):raise
        # Docker restarts may leave owned stopped containers on vanished networks.
        # Scoped cleanup verifies registry/labels before recreating this lab only.
        event('recover_missing_owned_network')
        lab.cleanup();lab=Lab();healthy=lab.baseline()
    if lab.snapshot()!=healthy or not lab.connectivity()['passed']:raise RuntimeError('Baseline recovery failed')

def controlled_safety():
    from neta.remediation import execute,reference_action
    path=OUT/'controlled-safety.json'
    if path.exists() and read(path).get('all_passed'):return read(path)
    lock=ROOT/'runtime/experiment.lock'
    with lock.open('a+') as handle:
        fcntl.flock(handle,fcntl.LOCK_EX)
        lab=Lab();healthy=lab.baseline();results=[]
        fault={'family':'route_missing','device':'r1','target':'10.0.2.0/24'}
        diagnosis={'findings':[{'fault':fault,'evidence_ids':['controlled'],'explanation':'Evaluator controlled fixture'}]}
        def plan(actions):return {'actions':actions,'preconditions':['fixture injected'],'expected_effects':['recover intended state'],'verification':['full state and six probe paths'],'rollback':'restore_captured_state','evidence_ids':['controlled']}
        try:
            for twin in [True,False]:
                for kind in ['valid','incomplete','unsafe','post_regression']:
                    event('controlled_safety',condition=kind,twin=twin)
                    lab.restore(healthy);lab.inject([fault])
                    if kind=='incomplete':lab.inject([{'family':'link_down','device':'r2','target':'eth1'}])
                    actions=[{'op':'link_down','device':'pc1','target':'eth0'}] if kind=='unsafe' else [reference_action(fault)]
                    result=execute(lab,plan(actions),diagnosis,use_twin=twin,controlled_failure='post_apply_regression' if kind=='post_regression' else None)
                    expected=result['success'] if kind=='valid' else result['status']=='blocked_policy' if kind=='unsafe' else result['rollback_success'] is True if kind=='post_regression' or not twin else result['status']=='blocked_twin_recovery'
                    results.append({'kind':kind,'use_twin':twin,'expected_behavior_passed':bool(expected),'outcome':result})
        finally:lab.restore(healthy)
    result={'kind':'oracle-controlled; not agent accuracy','generated':now(),'all_passed':all(r['expected_behavior_passed'] for r in results),'executions':results}
    write(path,result)
    if not result['all_passed']:raise RuntimeError('Controlled safety check failed; inspect saved evidence')
    return result

def report(m,package=False):
    return {'note':'Report authoring is not part of the submission runner; all experiment records remain saved.'}

def execute_job(job):
    cfg=job['config'];cid=job['case_id']
    for attempt in range(3):
        path=ROOT/'results/runs/submission'/f'{execution_id(cid,cfg,"submission",attempt)}.json'
        if path.exists():
            row=read(path)
            if execution_usable(row):return row
            continue
        if attempt:recover()
        check_services()
        row=run_case(cid,cfg,'submission',execution_attempt=attempt)
        if execution_usable(row):return row
        event('infrastructure_retry',case=cid,model=cfg['model'],attempt=attempt,error=row.get('error'),restored=row.get('final_restored'))
    raise RuntimeError('Three infrastructure attempts exhausted; inspect raw records before restarting')

def main(args):
    OUT.mkdir(parents=True,exist_ok=True)
    if args.analyze:
        print(json.dumps(report(read(MANIFEST),package=True)));return
    check_services();m=freeze();verify(m)
    if args.plan:print(json.dumps({'jobs':m['n_jobs'],'models':m['models'],'manifest_hash':m['manifest_hash']}));return
    event('preflight',planned=m['n_jobs']);recover();controlled_safety();report(m)
    active=None;done=0
    for i,job in enumerate(m['jobs']):
        verify(m)
        if shutil_disk_free()<2*1024**3:raise RuntimeError('Less than 2 GiB free disk')
        model=job['config']['model']
        if model!=active:
            for other in MODELS:
                if other!=model:run(['ollama','stop',other],check=False,timeout=20)
            if Ollama(model).identity()['digest']!=m['model_identities'][model]['digest']:raise RuntimeError('Model digest drift')
            if json.loads(run(['docker','image','inspect','neta-linux:research'])['stdout'])[0]['Id']!=m['sandbox_id']:raise RuntimeError('Sandbox image drift')
            active=model
        event('running',index=i+1,total=len(m['jobs']),case=job['case_id'],method=job['config']['method'],model=model,block=job['block'],repeat=job['config']['repeat'])
        row=execute_job(job);done+=1
        event('cell_saved',index=i+1,total=len(m['jobs']),run_id=row['run_id'],status=row['status'],restored=row['final_restored'],seconds=row.get('elapsed_total_s'))
        if done%7==0:report(m)
        if args.limit and done>=args.limit:break
    coverage=report(m,package=True)
    event('complete' if coverage.get('complete') else 'partial',coverage={k:v for k,v in coverage.items() if k!='missing'})

def shutil_disk_free():
    import shutil
    return shutil.disk_usage(ROOT).free

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--plan',action='store_true');parser.add_argument('--analyze',action='store_true');parser.add_argument('--limit',type=int)
    args=parser.parse_args()
    if args.analyze:main(args)
    else:
        path=ROOT/'runtime/workflow.lock';path.parent.mkdir(exist_ok=True)
        with path.open('a+') as lock:
            try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:raise SystemExit('A workflow already owns the lab; no duplicate started')
            signal.signal(signal.SIGTERM,lambda *_:(_ for _ in ()).throw(KeyboardInterrupt('termination requested')))
            try:main(args)
            except BaseException as exc:
                event('failed',error=f'{type(exc).__name__}: {exc}')
                if MANIFEST.exists():
                    try:report(read(MANIFEST),package=True)
                    except Exception as report_error:print('Report error:',report_error,flush=True)
                raise
