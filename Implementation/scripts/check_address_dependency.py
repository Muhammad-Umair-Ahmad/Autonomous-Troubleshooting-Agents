import fcntl
from neta.util import ROOT,write,now
from neta.lab import Lab
from neta.remediation import execute,reference_action
with (ROOT/'runtime/experiment.lock').open('a') as lock:
 fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
 lab=Lab(); healthy=lab.baseline()
 fault={'family':'address_missing','device':'pc1','target':'eth0'}
 diagnosis={'findings':[{'fault':fault,'evidence_ids':['controlled-address-fixture'],'explanation':'Controller-only regression fixture'}]}
 def plan(actions):
  return {'actions':actions,'preconditions':['controlled missing address'],'expected_effects':['restore connectivity'],'verification':['full healthy snapshot and connectivity'],'rollback':'restore_captured_state','evidence_ids':['controlled-address-fixture']}
 try:
  lab.inject([fault])
  partial=execute(lab,plan([reference_action(fault)]),diagnosis,use_twin=True)
  complete=execute(lab,plan([{'op':'route_replace','device':'pc1','target':'default','value':'10.0.1.1'},reference_action(fault)]),diagnosis,use_twin=True)
 finally:
  lab.restore(healthy)
 result={'timestamp':now(),'kind':'oracle_controlled_not_agent_score','partial':partial,'complete':complete,'final_restored':lab.snapshot()==healthy}
 result['all_passed']=partial['status']=='blocked_twin_recovery' and complete['success'] and result['final_restored']
 write(ROOT/'results/address-dependency-live.json',result)
 print({k:result[k] for k in ('all_passed','final_restored')},flush=True)
 assert result['all_passed'], result
