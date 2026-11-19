"""Command-line entry point. Controller commands never run inside agent workers."""
import argparse
import json
from .util import ROOT, read

def main():
    parser=argparse.ArgumentParser(prog='neta')
    sub=parser.add_subparsers(dest='command',required=True)
    sub.add_parser('prepare')
    p=sub.add_parser('validate'); p.add_argument('--case'); p.add_argument('--split',choices=['train','validation','test'])
    p=sub.add_parser('knowledge'); p.add_argument('action',choices=['ingest','build','curate','evaluate']); p.add_argument('--name',default='docs-v1'); p.add_argument('--curated',action='store_true'); p.add_argument('--run')
    p=sub.add_parser('diagnose'); p.add_argument('--case',required=True); p.add_argument('--method',default='full'); p.add_argument('--model',default='qwen2.5:1.5b'); p.add_argument('--knowledge',default='docs-v1'); p.add_argument('--category',default='pilot'); p.add_argument('--repeat',type=int,default=0); p.add_argument('--improved',action='store_true',help='Use separately identified repair-v2 follow-up protocol')
    p=sub.add_parser('experiments'); p.add_argument('action',choices=['plan','estimate','run']); p.add_argument('--manifest'); p.add_argument('--limit',type=int)
    sub.add_parser('controlled-remediation')
    sub.add_parser('analyze')
    sub.add_parser('status')
    sub.add_parser('cleanup')
    p=sub.add_parser('upstream'); p.add_argument('action',choices=['inventory','linux-probe'])
    args=parser.parse_args(); result=None
    if args.command=='prepare':
        from .datasets import prepare
        from .upstream import inventory
        result={'local_tickets':len(prepare()['cases']),'upstream':inventory()}
    elif args.command=='validate':
        from .datasets import cases,validate
        selected=[c for c in cases(args.split,standard=True) if not args.case or c['case_id']==args.case]
        if not selected: parser.error('No matching case')
        for c in selected:
            value=validate(c['case_id']); print(json.dumps({'case':c['case_id'],'status':value['status']}),flush=True)
    elif args.command=='knowledge':
        from .retrieval import ingest,build,curate,evaluate
        if args.action=='ingest': result={'chunks':ingest()}
        elif args.action=='build': result={'snapshot_id':build(args.name,args.curated)['snapshot_id']}
        elif args.action=='curate':
            if not args.run: parser.error('--run is required')
            result=curate(args.run)
        else: result=evaluate()
    elif args.command=='diagnose':
        from .experiments import run_case,config
        cfg=config(args.method,args.model,args.repeat,args.knowledge)
        if args.improved:
            cfg.update(revision='repair-v3',temperature=0,seconds=240,tokens=24000)
        category='improved' if args.improved and args.category=='pilot' else args.category
        result=run_case(args.case,cfg,category)
        result={k:result.get(k) for k in ('run_id','status','termination','metrics','repair','elapsed_total_s')}
    elif args.command=='controlled-remediation':
        from .remediation import controlled_experiments
        result=controlled_experiments()
    elif args.command=='experiments':
        from .experiments import manifest,throughput,sweep
        if args.action=='plan':
            m=manifest(); result={k:m[k] for k in ('n_jobs','manifest_hash','models','methods')}
        elif args.action=='estimate': result=throughput()
        else: result={'processed':sweep(args.manifest,args.limit)}
    elif args.command=='analyze':
        result={'note':'The consolidated report and technical documentation are in the submission root.', 'output':str(ROOT.parent/'Phase3_Implementation_and_Evaluation_24i-2545.pdf')}
    elif args.command=='status':
        from .status import status
        result=status()
    elif args.command=='cleanup':
        from .lab import Lab
        for name in ('twin','main'): Lab(name).cleanup()
        result={'cleaned':'owned main and twin labs only; original base and all unrelated resources preserved'}
    elif args.command=='upstream':
        from .upstream import inventory
        if args.action=='inventory': result=inventory()
        else:
            from .upstream import NikaAdapter
            result=NikaAdapter().probe()
    if result is not None: print(json.dumps(result,indent=2,default=str))

if __name__=='__main__': main()
