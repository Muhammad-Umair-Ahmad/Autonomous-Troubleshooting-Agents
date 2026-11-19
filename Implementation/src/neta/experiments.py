"""Resumable manifest-driven real experiments. Every requested cell is retained."""
import fcntl
import json
import time
import uuid
from collections import Counter
from pathlib import Path
from .broker import diagnose
from .contracts import Diagnosis
from .datasets import cases
from .graphs import graph
from .lab import Lab
from .metrics import score
from .remediation import execute
from .retrieval import Ollama
from .util import ROOT, digest, now, read, write, run

METHODS=['rule_based','plain_llm','rag_only','react','single_agent','sade_local','no_twin','full',
         'no_retrieval','no_curation','no_rescan','no_oversight','no_circuit_breaker','single_role']
MODELS=['qwen2.5:1.5b','qwen2.5-coder:3b','llama3.2:1b']


def execution_id(case_id,config,category,attempt=0):
    logical=digest([case_id,config,category])[:24]
    return logical if attempt==0 else digest(['execution_attempt',logical,attempt])[:24]


def run_case(case_id,config,category='pilot',execution_attempt=0):
    case=next(c for c in cases() if c['case_id']==case_id)
    truth=read(ROOT/'data/private/local-truth.json')[case_id]
    logical_run_id=digest([case_id,config,category])[:24]
    run_id=execution_id(case_id,config,category,execution_attempt)
    destination=ROOT/'results/runs'/category/f'{run_id}.json'
    if destination.exists(): return read(destination)
    record={'run_id':run_id,'logical_run_id':logical_run_id,'execution_attempt':execution_attempt,
            'retry_of':execution_id(case_id,config,category,execution_attempt-1) if execution_attempt else None,'case_id':case_id,'incident_id':case['incident_id'],'incident_group':case['incident_group'],
            'source':'local','split':case['split'],'ticket':case['ticket'],'ticket_style':case['ticket_style'],
            'config':config,'configuration_hash':digest(config),'category':category,'started':now(),
            'diagnosis':None,'repair':None,'status':'started','failure_category':None,'exclusion_reason':None,
            'api_charges_usd':0,'compute_cost_note':'Local CPU/GPU, RAM, disk and energy are nonzero; energy is not measured.',
            'validation_status':truth['validation_status'],'truth_faults':truth['faults']}
    queued_at=time.monotonic(); start=queued_at; lab=Lab(); healthy=None
    destination.parent.mkdir(parents=True,exist_ok=True)
    lock=(ROOT/'runtime/experiment.lock'); lock.parent.mkdir(exist_ok=True)
    with lock.open('w') as handle:
        fcntl.flock(handle,fcntl.LOCK_EX)
        start=time.monotonic()
        record['queue_wait_s']=start-queued_at
        record['execution_started']=now()
        try:
            if truth['validation_status']!='validated':
                record['status']='excluded'; record['exclusion_reason']='case_not_runtime_validated'; return record
            healthy=lab.baseline()
            record['injection']=lab.inject(truth['faults'])
            faulty=lab.snapshot()
            record['faults_confirmed']=[lab.fault_holds(f,faulty) for f in truth['faults']]
            if not all(record['faults_confirmed']): raise RuntimeError('Injection did not establish every root-cause state')
            if config.get('knowledge'):
                artifact=read(ROOT/'knowledge/snapshots'/f'{config["knowledge"]}.json')
                record['knowledge_snapshot_id']=artifact['snapshot_id']
            before=run(['docker','stats','--no-stream','--format','{{json .}}',*lab.ids.values()],check=False,timeout=15)
            record['resources_before']=before
            result=diagnose(case,config,lab); record.update(result)
            output=result.get('result') or {}
            diagnosis=output.get('diagnosis') or result.get('partial_diagnosis')
            record['diagnosis']=diagnosis
            predicted=[f['fault'] for f in diagnosis.get('findings',[])] if diagnosis else []
            record['metrics']=score(predicted,truth['faults'])
            if not truth['faults']:
                record['metrics']['healthy_correct']=int(bool(diagnosis and diagnosis.get('healthy') and not diagnosis.get('findings')))
                record['metrics']['false_alarm']=int(bool(predicted))
                record['metrics']['unanswered_healthy']=int(not bool(diagnosis and (diagnosis.get('healthy') or diagnosis.get('findings'))))
            record['graph']=graph(case['topology'],record['observations'],diagnosis)
            record['status']='infrastructure_failed' if result.get('failure_kind')=='infrastructure' else 'completed' if result['termination'] in ('completed','unsupported_evidence') else 'agent_failed'
            if record['status']=='infrastructure_failed':record['failure_category']='infrastructure_or_tool_failure'
            elif record['status']=='agent_failed': record['failure_category']=classify_failure(result['termination'])
            elif record['metrics']['exact_match']!=1: record['failure_category']='wrong_or_incomplete_fault_set'
            if record['status']!='infrastructure_failed' and output.get('plan') and config.get('repair'):
                if output.get('unsupported_findings'):
                    record['repair']={'status':'blocked_unsupported_evidence','success':False,'attempted':False,'unsafe_executions':0}
                else:
                    record['repair']=execute(lab,output['plan'],diagnosis,
                        review=output.get('review'),use_twin=config['method']!='no_twin')
                    # Public, measured residual scan after applying the proposed plan.
                    if record['repair'].get('attempted') and config['method']!='no_rescan':
                        residual_config={**config,'repair':False,'seconds':min(120,config.get('seconds',240))}
                        residual=diagnose(case,residual_config,lab)
                        record['residual_scan']=residual
            elif diagnosis and diagnosis.get('healthy'):
                probes=lab.connectivity()
                record['repair']={'status':'not_needed' if probes['passed'] else 'healthy_claim_contradicted',
                                  'success':probes['passed'] and not truth['faults'],'attempted':False,'unsafe_executions':0,'checks':probes}
            repair=record.get('repair') or {}
            record['repair_failure_category']=(repair.get('status','not_proposed') if truth['faults'] and config.get('repair') and not repair.get('success') else None)
            if diagnosis:
                record['hypothesis_verdicts']=[{'fault':f['fault'],'verdict':'evaluator_confirmed' if f['fault'] in truth['faults'] else 'evaluator_rejected',
                    'evidence_ids':f['evidence_ids']} for f in diagnosis['findings']]
        except KeyboardInterrupt:
            record['status']='interrupted';record['termination']='controller_interrupted'
            record.setdefault('metrics',score([],truth['faults']))
            raise
        except Exception as exc:
            record['status']='infrastructure_failed' if record.get('diagnosis') is None else 'agent_failed'
            record['error']=f'{type(exc).__name__}: {exc}'; record['failure_category']=classify_failure(record['error'])
            record.setdefault('metrics',score([],truth['faults']))
            if not record.get('diagnosis'):
                record['metrics'].update({'precision':0.,'recall':0.,'f1':0.,'exact_match':0,'healthy_correct':0 if not truth['faults'] else None})
        finally:
            if healthy is not None:
                try:
                    lab.restore(healthy); record['final_restored']=lab.snapshot()==healthy
                except Exception as exc:
                    record['final_restored']=False; record['restoration_error']=str(exc); record['status']='infrastructure_failed'
            if not record.get('diagnosis') and 'metrics' in record:
                record['metrics'].update({'precision':0.,'recall':0.,'f1':0.,'exact_match':0,'healthy_correct':0 if not truth['faults'] else None})
            record['tokens_total']=record.get('tokens',0)+(record.get('residual_scan') or {}).get('tokens',0)
            record['tool_calls_total']=record.get('tool_calls',0)+(record.get('residual_scan') or {}).get('tool_calls',0)
            record['elapsed_total_s']=time.monotonic()-start
            record['finished']=now()
            # Metrics remain present for failures, but infrastructure failures are separately counted.
            write(destination,record)
    return record



def execute_cell(case_id,cfg,category,max_attempts=3):
    """Same frozen cell/seed; preserve every infrastructure attempt separately."""
    from .recovery import check_services,execution_usable
    for attempt in range(max_attempts):
        identity=execution_id(case_id,cfg,category,attempt)
        destination=ROOT/'results/runs'/category/f'{identity}.json'
        if destination.exists():
            row=read(destination)
            if execution_usable(row):return row
            if row.get('status')=='excluded':raise RuntimeError('Frozen cell is excluded: '+identity)
            continue
        check_services()
        row=run_case(case_id,cfg,category,execution_attempt=attempt)
        if execution_usable(row):return row
        raise RuntimeError('Infrastructure/restoration failure; recover before resuming cell '+identity)
    raise RuntimeError('Infrastructure retry limit reached for '+case_id+'; all attempts preserved')


def classify_failure(text):
    value=text.lower()
    if 'budget' in value or 'timeout' in value: return 'budget_or_timeout'
    if 'repeated' in value or 'progress' in value: return 'unproductive_loop'
    if 'evidence' in value: return 'unsupported_evidence'
    if 'validation' in value or 'json' in value or 'schema' in value: return 'invalid_model_output'
    if 'docker' in value or 'kathara' in value or 'connection' in value: return 'infrastructure_or_tool_failure'
    return 'unclassified_failure'


def config(method='full',model='qwen2.5:1.5b',repeat=0,knowledge='curated-v1',robustness='clean'):
    return {'implementation_hash':digest({str(p.relative_to(ROOT)):digest(p.read_bytes()) for p in sorted((ROOT/'src/neta').rglob('*.py'))}),
            'method':method,'model':model,'repeat':repeat,'seed':1000+repeat,'temperature':.2,'max_output':1024,
            'seconds':240,'tokens':24000,'tools':48,'knowledge':'docs-v1' if method=='no_curation' else knowledge,
            'repair':method not in ('plain_llm','rag_only','sade_local'), 'robustness':robustness,'sandbox_image':'neta-linux:research'}


def manifest():
    path=ROOT/'configs/experiments.main.json'
    if path.exists(): return read(path)
    truth=read(ROOT/'data/private/local-truth.json')
    if any(truth[c['case_id']].get('validation_status')!='validated' for c in cases(standard=True)):
        raise RuntimeError('Cannot freeze: local runtime validation is incomplete')
    for name in ('docs-v1','curated-v1'):
        knowledge_path=ROOT/'knowledge/snapshots'/f'{name}.json'
        if not knowledge_path.exists():raise RuntimeError('Cannot freeze: required knowledge snapshot is missing')
        knowledge=read(knowledge_path)
        if digest({k:v for k,v in knowledge.items() if k!='snapshot_id'})!=knowledge['snapshot_id']:
            raise RuntimeError('Cannot freeze: knowledge snapshot integrity mismatch')
        if not knowledge.get('chunks') or name=='curated-v1' and not any(c.get('kind')=='verified_training_incident' for c in knowledge['chunks']):
            raise RuntimeError('Cannot freeze: verified training knowledge is incomplete')
    if throughput()['status']!='measured':raise RuntimeError('Cannot freeze: representative development pilots are incomplete')
    jobs=[]
    for case in cases('test',standard=True):
        for method in METHODS:
            for model in MODELS:
                for repeat in range(5):
                    jobs.append({'case_id':case['case_id'],'category':'main','config':config(method,model,repeat)})
    for case in cases('test'):
        if case['ticket_style']=='standard': continue
        for method in ('full','react'):
            for model in MODELS:
                for repeat in range(5): jobs.append({'case_id':case['case_id'],'category':'robustness','config':config(method,model,repeat)})
    for case in cases('test',standard=True):
        for condition in ('missing','noisy','stale','tool_timeout'):
            for method in ('full','react'):
                for model in MODELS:
                    for repeat in range(5): jobs.append({'case_id':case['case_id'],'category':'robustness','config':config(method,model,repeat,robustness=condition)})
    model_identities={m:Ollama(m).identity() for m in MODELS}
    sandbox_id=json.loads(run(['docker','image','inspect','neta-linux:research'])['stdout'])[0]['Id']
    for job in jobs:
        job['config'].update({'sandbox_image_id':sandbox_id,'model_digest':model_identities[job['config']['model']]['digest'],
          'worker_hash':digest((ROOT/'src/neta/agent/worker.py').read_bytes()),
          'books_hash':digest((ROOT/'src/neta/agent/sade-books.json').read_bytes())})
    # Model-contiguous blocks avoid reloading three backbones into 8 GiB RAM.
    jobs.sort(key=lambda j:(j['config']['model'],j['category'],j['config']['method'],j['case_id'],j['config']['repeat']))
    artifact={'protocol_version':2,'execution_retry_policy':{'max_attempts':3,'same_configuration_and_seed':True,'retry_only':'infrastructure failure, interrupted execution, or unverified restoration','model_output_failures':'final empirical outcomes; never retried for accuracy','selection':'earliest restored model outcome; preserve all raw attempts'},'created':now(),'jobs':jobs,'n_jobs':len(jobs),'models':MODELS,
              'methods':METHODS,'repeats':5,'cases_hash':digest(read(ROOT/'data/public/local-cases.json')),
              'knowledge_hashes':{name:read(ROOT/'knowledge/snapshots'/f'{name}.json')['snapshot_id'] for name in ('docs-v1','curated-v1')},
              'information_access':{'plain_llm':'ticket and public topology; no observations', 'rag_only':'ticket, topology and retrieved passages; no tools',
                                    'others':'matched live read-only tools and topology; role/loop/retrieval vary as declared'},
              'SADE':'local adaptation only; exact published reproduction unavailable (paid providers)',
              'deterministic_repeats':'rule baseline repeats are not independent evidence; identical model outputs audited',
              'no_twin':'twin removed; fundamental scoped executor and deterministic policy retained',
              'no_oversight':'LLM Oversight removed; containment, policy, and twin retained',
              'no_circuit_breaker':'no-progress breaker removed; hard time/token/tool caps retained',
              'upstream_evaluation':'pending independent real validation; never substituted with local cases'}
    artifact['code_hash']=digest({str(p.relative_to(ROOT)):digest(p.read_bytes()) for p in sorted((ROOT/'src/neta').rglob('*.py'))})
    artifact['books_hash']=digest((ROOT/'src/neta/agent/sade-books.json').read_bytes())
    artifact['dependency_lock_hash']=digest((ROOT/'requirements-lock.txt').read_bytes())
    artifact['source_lock_hash']=digest(read(ROOT/'configs/sources.lock.json'))
    artifact['model_identities']=model_identities
    artifact['truth_answers_hash']=digest({k:v['faults'] for k,v in read(ROOT/'data/private/local-truth.json').items()})
    artifact['image_identities']=read(ROOT/'results/prerequisites/images.json')
    artifact['manifest_hash']=digest(artifact); write(path,artifact)
    return artifact


def throughput():
    from statistics import mean
    from .recovery import pilot_usable
    identity=digest({str(p.relative_to(ROOT)):digest(p.read_bytes()) for p in sorted((ROOT/'src/neta').rglob('*.py'))})
    rows=[read(p) for p in (ROOT/'results/runs/pilot').glob('*.json')]
    eligible=[r for r in rows if pilot_usable(r) and r.get('split')=='validation'
              and r['config'].get('implementation_hash')==identity
              and r['config'].get('knowledge')=='curated-v1' and r['config'].get('method')=='full']
    # One latest valid attempt per case/model, so retries do not overweight a cell.
    selected={}
    for row in sorted(eligible,key=lambda r:r.get('finished','')):
        selected[(row['case_id'],row['config']['model'])]=row
    eligible=list(selected.values())
    expected={(c['case_id'],m) for c in cases('validation',standard=True) for m in MODELS}
    missing=sorted(expected-set(selected))
    planned=read(ROOT/'configs/experiment-plan.json')['local_total_cells']
    means={m:mean(r['elapsed_total_s'] for r in eligible if r['config']['model']==m)
           for m in MODELS if any(r['config']['model']==m for r in eligible)}
    report={'status':'measured' if not missing else 'pilot_not_complete','pilot_runs':len(eligible),
            'excluded_or_superseded_pilot_runs':len(rows)-len(eligible),'missing_development_cells':missing,
            'per_model_mean_seconds':means,'mean_seconds_per_run':mean(means.values()) if means else None,
            'planned_jobs':planned,'serial_estimate_hours':mean(means.values())*planned/3600 if not missing else None,
            'limitation':'Full-method development pilots estimate the balanced model mix. Other methods, fault counts, failures and twin/model overhead may differ; this is not a completion guarantee.'}
    write(ROOT/'results/throughput-estimate.json',report); return report


def sweep(manifest_path=None,limit=None):
    artifact=read(manifest_path) if manifest_path else manifest()
    # Refuse drift before any held-out test execution.
    if artifact['cases_hash']!=digest(read(ROOT/'data/public/local-cases.json')): raise RuntimeError('Case freeze drift')
    for name,expected in artifact['knowledge_hashes'].items():
        if read(ROOT/'knowledge/snapshots'/f'{name}.json')['snapshot_id']!=expected: raise RuntimeError('Knowledge freeze drift')
    current_code=digest({str(p.relative_to(ROOT)):digest(p.read_bytes()) for p in sorted((ROOT/'src/neta').rglob('*.py'))})
    if artifact.get('code_hash')!=current_code: raise RuntimeError('Code freeze drift; use a new declared protocol')
    if artifact['truth_answers_hash']!=digest({k:v['faults'] for k,v in read(ROOT/'data/private/local-truth.json').items()}): raise RuntimeError('Private answer freeze drift')
    if artifact['source_lock_hash']!=digest(read(ROOT/'configs/sources.lock.json')): raise RuntimeError('Source-lock freeze drift')
    if artifact['dependency_lock_hash']!=digest((ROOT/'requirements-lock.txt').read_bytes()): raise RuntimeError('Dependency-lock freeze drift')
    jobs=artifact['jobs']; count=0;active_model=None
    for job in jobs:
        if limit is not None and count>=limit: break
        if active_model and active_model!=job['config']['model']:
            run(['ollama','stop',active_model],check=False,timeout=20)
        active_model=job['config']['model']
        from shutil import disk_usage
        if disk_usage(ROOT).free<2*1024**3: raise RuntimeError('Less than 2 GiB free disk; stop before exhausting host storage')
        if artifact['code_hash']!=digest({str(p.relative_to(ROOT)):digest(p.read_bytes()) for p in sorted((ROOT/'src/neta').rglob('*.py'))}): raise RuntimeError('Code drift during sweep')
        if artifact['books_hash']!=digest((ROOT/'src/neta/agent/sade-books.json').read_bytes()): raise RuntimeError('Skill-library drift during sweep')
        for name,expected in artifact['knowledge_hashes'].items():
            snap=read(ROOT/'knowledge/snapshots'/f'{name}.json')
            if digest({k:v for k,v in snap.items() if k!='snapshot_id'})!=expected: raise RuntimeError('Knowledge content freeze drift')
        record=execute_cell(job['case_id'],job['config'],job['category'],artifact.get('execution_retry_policy',{}).get('max_attempts',1))
        count+=1
        print(json.dumps({'progress':count,'total':len(jobs),'run_id':record['run_id'],'status':record['status'],'exact_match':record.get('metrics',{}).get('exact_match')}),flush=True)
        write(ROOT/'results/sweep-progress.json',{'finished_cells_this_invocation':count,'total':len(jobs),'last_run':record['run_id'],'updated':now()})
        if record.get('status')=='infrastructure_failed' or record.get('final_restored') is not True:
            raise RuntimeError('Infrastructure/restoration failure; stop before contaminating further cells: '+record['run_id'])
    return count
