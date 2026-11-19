"""Real development regression; oracle plans are never agent benchmark scores."""
import fcntl
from neta.util import ROOT,write,now
from neta.lab import Lab,topology
from neta.broker import diagnose
from neta.experiments import config
from neta.remediation import execute,reference_action
with (ROOT/'runtime/experiment.lock').open('a') as lock:
 fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
 lab=Lab();healthy=lab.baseline()
 faults=[{'family':'link_down','device':'r2','target':'eth0'},{'family':'route_missing','device':'pc1','target':'default'}]
 def plan(actions,evidence):
  return {'actions':actions,'preconditions':['controlled development fixture'],'expected_effects':['restore connectivity'],'verification':['full healthy snapshot and connectivity'],'rollback':'restore_captured_state','evidence_ids':evidence}
 try:
  lab.inject(faults)
  diagnostic=diagnose({'case_id':'controlled-dev-link-dependency','ticket':'Controlled development link/route dependency regression','topology':topology()}, {**config('rule_based'),'repair':False},lab)
  diagnosis=diagnostic['result']['diagnosis']
  exact=sorted(faults,key=str)==sorted([f['fault'] for f in diagnosis['findings']],key=str)
  evidence=[e for f in diagnosis['findings'] for e in f['evidence_ids']]
  root_actions=[reference_action(f) for f in faults]
  partial=execute(lab,plan(root_actions,evidence),diagnosis,use_twin=True)
  complete=execute(lab,plan([{'op':'route_replace','device':'r2','target':'10.0.1.0/24','value':'10.0.12.1'}]+root_actions,evidence),diagnosis,use_twin=True)
 finally:lab.restore(healthy)
 result={'timestamp':now(),'kind':'oracle_controlled_not_agent_score','diagnostic':diagnostic,'exact_root_set':exact,'partial':partial,'complete':complete,'final_restored':lab.snapshot()==healthy}
 result['all_passed']=exact and partial['status']=='blocked_twin_recovery' and complete['success'] and result['final_restored']
 write(ROOT/'results/link-dependency-live.json',result)
 print({k:result[k] for k in ('all_passed','exact_root_set','final_restored')},flush=True)
 assert result['all_passed']
