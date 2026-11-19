"""Evidence-derived status. Implementation, run coverage and correctness are distinct."""
from collections import Counter
from .util import ROOT,read,write,now,digest


def status():
    from .datasets import cases
    from .recovery import select_execution_records
    raw_rows=[read(p) for p in (ROOT/'results/runs').glob('*/*.json')]
    rows=select_execution_records(raw_rows)
    validation=[read(p) for p in (ROOT/'results/validation').glob('*.json')]
    expected={c['incident_id'] for c in cases(standard=True)}
    valid={p.stem for p in (ROOT/'results/validation').glob('*.json') if read(p).get('status')=='validated'}
    remaining_validation=sorted(expected-valid)
    counts=Counter(r['status'] for r in validation)
    snapshot=ROOT/'knowledge/snapshots/curated-v1.json'
    accepted_path=ROOT/'knowledge/accepted-incidents.json'
    accepted=read(accepted_path) if accepted_path.exists() else []
    manifest_path=ROOT/'configs/experiments.main.json'
    manifest=read(manifest_path) if manifest_path.exists() else None
    plan=read(ROOT/'configs/experiment-plan.json')
    controlled_path=ROOT/'results/controlled-remediation.json'
    controlled=controlled_path.exists() and read(controlled_path).get('all_passed') is True
    blocker=ROOT/'results/prerequisites/upstream-blocker.json'
    upstream=read(blocker)['status'] if blocker.exists() else 'pending'
    actual={r.get('logical_run_id',r['run_id']):r for r in rows}
    jobs=manifest['jobs'] if manifest else []
    matched=[actual.get(digest([j['case_id'],j['config'],j['category']])[:24]) for j in jobs]
    recorded=sum(r is not None for r in matched)
    infrastructure=sum(r is not None and (r.get('status') in ('infrastructure_failed','interrupted','excluded')
                       or r.get('final_restored') is not True) for r in matched)
    local_complete=bool(manifest) and recorded==len(jobs) and infrastructure==0
    successful_repairs=[r for r in rows if r.get('status')=='completed' and r.get('final_restored') is True
                        and (r.get('repair') or {}).get('success') and (r.get('repair') or {}).get('attempted')]
    throughput_path=ROOT/'results/throughput-estimate.json'
    measured=throughput_path.exists() and read(throughput_path).get('status')=='measured'
    upstream_pending=[] if upstream=='verified_integrated' else ['published-source agent/cohort evaluation; lifecycle checks alone do not satisfy benchmark coverage']
    part2_pending=(['local validation: '+', '.join(remaining_validation)] if remaining_validation else [])+upstream_pending+['cross-source semantic overlap audit']
    extended_path=ROOT/'results/retrieval-development-extended.json'
    extended=read(extended_path) if extended_path.exists() else None
    part3_pending=([] if accepted else ['successful training curation'])+([] if snapshot.exists() else ['curated snapshot'])+([] if extended else ['expanded annotated development retrieval evaluation'])
    part6_pending=([] if manifest else ['freeze protocol'])+([] if local_complete else ['finish '+str(plan['local_total_cells'])+' local cells; retain failures'])+upstream_pending+([] if measured else ['representative development throughput'])
    report={'updated':now(),'validation':dict(counts),'validation_pending_incidents':len(remaining_validation),
            'runs':dict(Counter(r['status'] for r in rows)),'raw_execution_attempts':len(raw_rows),'raw_attempt_statuses':dict(Counter(r['status'] for r in raw_rows)),
            'runs_by_category':dict(Counter(r['category'] for r in rows)),
            'planned_local_cells':plan['local_total_cells'],'main_manifest_jobs':len(jobs) if manifest else None,
            'matrix_recorded_cells':recorded,'matrix_missing_cells':len(jobs)-recorded if manifest else None,
            'matrix_infrastructure_or_interrupted_cells':infrastructure,'local_matrix_complete':local_complete,
            'curated_snapshot':snapshot.exists(),'accepted_training_incidents':len(accepted),
            'verified_agent_repair_records':len(successful_repairs),'controlled_remediation':controlled,
            'upstream_linux_execution':upstream,'project_complete':False,
            'parts':{
              'part1':{'implemented':True,'tested':'Saved network and local-inference evidence in results/part1; current service preflight is separate.','pending':[]},
              'part2':{'implemented':'local lifecycle, grouped splits, catalogues and upstream adapter code','tested':dict(counts),'pending':part2_pending},
              'part3':{'implemented':'graph representation, BM25/dense fusion, local reranking, immutable snapshots, gated curation','tested':{'accepted_training_incidents':len(accepted),'curated_snapshot':snapshot.exists(),'retrieval_queries':extended['queries'] if extended else 4,'annotation':'developer-authored; no independent expert relevance claim'},'pending':part3_pending},
              'part4':{'implemented':'five responsibilities, typed broker, container isolation, evidence and budgets','tested':dict(Counter(r['status'] for r in rows)),'pending':[] if local_complete else ['complete healthy/single/double/triple model evaluation; inspect accuracy separately from completed status']},
              'part5':{'implemented':'typed plans, scoped policy, faulty-state twin, post-checks and rollback','tested':{'controlled_checks_passed':controlled,'verified_agent_repairs':len(successful_repairs)},'pending':([] if controlled else ['real controlled twin/rollback checks'])+([] if local_complete else ['broad agent repair, regression and rollback measurements'])},
              'part6':{'implemented':'baselines, component ablations, retry/manifest/resume and robustness','tested':{'recorded_cells':recorded,'missing_cells':len(jobs)-recorded if manifest else None},'pending':part6_pending},
              'part7':{'implemented':'coverage audit, grouped statistics, figures and provisional report generation','tested':'See software test logs and actual analysis artifacts.','pending':([] if local_complete else ['complete comparable local records'])+['final empirical report and conclusions','source overlap/retrieval/research review; human ratings only if actually supplied']}}}
    write(ROOT/'results/status.json',report)
    return report
