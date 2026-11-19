"""Fail-closed service checks and explicit, preserved development-pilot retries."""
import requests
from .util import ROOT, read, run


def check_services():
    run(['docker','info','--format','{{.ServerVersion}}'],timeout=20)
    response=requests.get('http://127.0.0.1:11434/api/tags',timeout=10)
    response.raise_for_status()
    return {'docker':True,'ollama':True}



def execution_usable(row):
    return row.get('status') in ('completed','agent_failed') and row.get('final_restored') is True


def select_execution_records(rows):
    """Select the earliest restored model outcome, never the most accurate retry."""
    grouped={}
    for row in rows:grouped.setdefault(row.get('logical_run_id',row['run_id']),[]).append(row)
    selected=[]
    for attempts in grouped.values():
        ordered=sorted(attempts,key=lambda r:(r.get('execution_attempt',0),r.get('finished','')))
        selected.append(next((r for r in ordered if execution_usable(r)),ordered[-1]))
    return selected


def pilot_usable(row):
    # A wrong diagnosis or model-output failure is still an empirical model outcome.
    # Infrastructure failure or unverified restoration is not representative throughput.
    return (row.get('status') in ('completed','agent_failed')
            and row.get('final_restored') is True
            and row.get('elapsed_total_s',0)>0
            and row.get('tokens_total',row.get('tokens',0))>0
            and bool(row.get('model_calls')))


def development_pilot(case_id,cfg,max_attempts=5):
    from .experiments import run_case
    from .util import digest
    previous=None
    for attempt in range(max_attempts):
        candidate={**cfg,'development_attempt':attempt}
        if previous: candidate['retry_of']=previous
        run_id=digest([case_id,candidate,'pilot'])[:24]
        path=ROOT/'results/runs/pilot'/f'{run_id}.json'
        if path.exists():
            row=read(path)
            if pilot_usable(row):return row
            previous=row['run_id']
            continue
        check_services()
        row=run_case(case_id,candidate,'pilot')
        if pilot_usable(row):return row
        # Stop immediately; do not create one failed row for every remaining model.
        raise RuntimeError('Development pilot infrastructure/restoration gate failed; preserve '+row['run_id']+
                           ' and recover services/lab before resuming. Status: '+row['status'])
    raise RuntimeError('Development pilot retry limit reached; inspect preserved attempts for '+case_id)
