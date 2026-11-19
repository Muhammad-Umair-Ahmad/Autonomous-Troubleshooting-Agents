"""Trusted constrained execution, equivalent faulty twins, regression checks and rollback."""
import ipaddress
from .contracts import Fault, RepairPlan, Action, Review
from .lab import Lab, INTENT, ROUTES
from .util import ROOT, now, read, write


def reference_action(raw):
    """Validation/oracle only. Never used to generate an agent plan."""
    f=Fault.model_validate(raw)
    op={'link_down':'link_up','route_missing':'route_replace','route_wrong':'route_replace',
        'address_missing':'address_add','firewall_drop':'firewall_clear'}[f.family]
    target='filter' if f.family=='firewall_drop' else f.target
    value=ROUTES[f.device][f.target] if f.family.startswith('route_') else INTENT[f.device][f.target] if f.family=='address_missing' else ''
    return {'op':op,'device':f.device,'target':target,'value':value}


def policy(plan,diagnosis,state=None):
    p=RepairPlan.model_validate(plan)
    approved=[]; blocked=[]
    measured_links={e for f in diagnosis['findings'] for e in f['evidence_ids']}
    if not set(p.evidence_ids)<=measured_links:
        return {'approved':False,'allowed':[],'blocked':[a.model_dump() for a in p.actions],'reason':'plan references evidence outside diagnosis','fundamental_containment':'always enabled'}
    faults=[Fault.model_validate(x['fault']) for x in diagnosis['findings']]
    # Restoration policy only permits changes justified by an evidence-backed diagnosed fault.
    for action in p.actions:
        candidates=[f for f in faults if f.device==action.device and (f.target==action.target or f.family=='firewall_drop' and action.target=='filter')]
        valid=False
        for f in candidates:
            try:expected=reference_action(f.model_dump())
            except (KeyError,ValueError):continue
            if action.model_dump()==expected: valid=True
        if not valid and action.op=='route_replace':
            for fault in faults:
                if fault.family not in ('address_missing','link_down') or fault.device!=action.device:continue
                intended=INTENT[fault.device].get(fault.target)
                if not intended or ROUTES[fault.device].get(action.target)!=action.value:continue
                if ipaddress.ip_address(action.value) not in ipaddress.ip_interface(intended).network:continue
                required_op='address_add' if fault.family=='address_missing' else 'link_up'
                required_value=intended if required_op=='address_add' else ''
                dependency_in_plan=any(a.op==required_op and a.device==fault.device and a.target==fault.target and a.value==required_value for a in p.actions)
                missing_at_execution=state is None or not any(r['dst']==action.target for r in state[fault.device]['routes'])
                if dependency_in_plan and missing_at_execution:valid=True
        (approved if valid else blocked).append(action.model_dump())
    return {'approved':not blocked and bool(approved),'allowed':approved,'blocked':blocked,'fundamental_containment':'always enabled'}


def execute(lab,plan,diagnosis,review=None,use_twin=True,controlled_failure=None):
    started=now(); state=lab.snapshot(); healthy=read(ROOT/'runtime/healthy.json')
    outcome={'started':started,'plan':plan,'status':'proposed','attempted':False,'success':False,
             'rollback_attempted':False,'rollback_success':None,'unsafe_executions':0,'twin_equivalent':None}
    verdict=policy(plan,diagnosis,state=state); outcome['policy']=verdict
    if not verdict['approved']:
        outcome['status']='blocked_policy'; return outcome
    if review is not None and not Review.model_validate(review).approved:
        outcome['status']='blocked_oversight'; return outcome
    outcome['preconditions_checked']=[{'fault':f['fault'],'still_holds':lab.fault_holds(f['fault'],state)} for f in diagnosis['findings']]
    if not all(c['still_holds'] for c in outcome['preconditions_checked']):
        outcome['status']='blocked_stale_precondition';return outcome
    outcome['status']='approved'
    actions=sorted(RepairPlan.model_validate(plan).actions,key=lambda a:{'link_up':0,'address_add':1,'route_replace':2,'firewall_clear':3}.get(a.op,4))
    outcome['execution_order']=[a.model_dump() for a in actions]
    def apply(target):
        return [target.action(a.model_dump()) for a in actions]
    def verify(target):
        snap=target.snapshot(); probes=target.connectivity()
        return {'passed':probes['passed'] and snap==healthy,'connectivity':probes,
                'snapshot_matches_healthy':snap==healthy,'snapshot':snap}
    if use_twin:
        twin=Lab('twin'); twin.deploy()
        try:
            twin.restore(state)
            equivalence=twin.snapshot()==state
            original_probe=lab.connectivity(); twin_probe=twin.connectivity()
            equivalence=equivalence and [r['raw']['returncode'] for r in original_probe['records']]==[r['raw']['returncode'] for r in twin_probe['records']]
            outcome['twin_equivalent']=equivalence
            if not equivalence:
                outcome['status']='blocked_twin_fidelity'; return outcome
            outcome['twin_actions']=apply(twin)
            outcome['twin_checks']=verify(twin)
            if not outcome['twin_checks']['passed']:
                outcome['status']='blocked_twin_recovery'; return outcome
        finally:
            twin.cleanup()
    try:
        outcome['attempted']=True; outcome['status']='attempted'
        outcome['actions']=apply(lab)
        if controlled_failure=='post_apply_regression':
            # Evaluator-only fault used to test the real rollback branch; excluded from agent success experiments.
            lab.action({'op':'link_down','device':'pc1','target':'eth0'})
        outcome['post_checks']=verify(lab)
        outcome['post_snapshot_matches_healthy']=outcome['post_checks']['snapshot_matches_healthy']
        outcome['success']=outcome['post_checks']['passed']
        outcome['status']='successful_repair' if outcome['success'] else 'verification_failed'
    except Exception as exc:
        outcome['status']='execution_failed'; outcome['error']=f'{type(exc).__name__}: {exc}'
    if not outcome['success']:
        outcome['rollback_attempted']=True
        try:
            lab.restore(state)
            outcome['rollback_success']=lab.snapshot()==state
            outcome['rollback_checks']=lab.connectivity()
            outcome['status']='rolled_back' if outcome['rollback_success'] else 'rollback_failed'
        except Exception as exc:
            outcome['rollback_success']=False; outcome['status']='rollback_failed'; outcome['rollback_error']=str(exc)
    return outcome


def controlled_experiments():
    import fcntl
    path=ROOT/'runtime/experiment.lock';path.parent.mkdir(exist_ok=True)
    with path.open('w') as handle:
        fcntl.flock(handle,fcntl.LOCK_EX)
        return _controlled_experiments()


def _controlled_experiments():
    """Real emulation tests, explicitly oracle-controlled rather than agent repair measurements."""
    lab=Lab(); healthy=lab.baseline(); fault={'family':'route_missing','device':'r1','target':'10.0.2.0/24'}
    diagnosis={'findings':[{'fault':fault,'evidence_ids':['controlled-fixture'],'explanation':'Trusted controlled route injection'}]}
    def plan(actions):
        return {'actions':actions,'preconditions':['controlled fixture injected'],'expected_effects':['restore connectivity'],
                'verification':['compare all captured network state and six ping paths'],'rollback':'restore_captured_state','evidence_ids':['controlled-fixture']}
    outcomes=[]
    try:
        lab.inject([fault])
        good=plan([reference_action(fault)])
        outcomes.append({'experiment':'equivalent_faulty_twin_and_repair','kind':'oracle_controlled',
                         'outcome':execute(lab,good,diagnosis,use_twin=True)})
        lab.restore(healthy); lab.inject([fault])
        outcomes.append({'experiment':'post_application_regression_rollback','kind':'oracle_controlled',
                         'outcome':execute(lab,good,diagnosis,use_twin=True,controlled_failure='post_apply_regression')})
        lab.restore(healthy)
        second={'family':'link_down','device':'r2','target':'eth1'}
        lab.inject([fault,second])
        outcomes.append({'experiment':'incomplete_repair_blocked_by_twin','kind':'oracle_controlled',
                         'outcome':execute(lab,good,diagnosis,use_twin=True)})
        bad=plan([{'op':'link_down','device':'pc1','target':'eth0'}])
        outcomes.append({'experiment':'unsafe_proposal_blocked','kind':'oracle_controlled',
                         'outcome':execute(lab,bad,diagnosis,use_twin=True)})
    finally:
        lab.restore(healthy)
    checks=[outcomes[0]['outcome']['success'],outcomes[1]['outcome']['rollback_success'],
            outcomes[2]['outcome']['status']=='blocked_twin_recovery',outcomes[3]['outcome']['status']=='blocked_policy']
    report={'all_passed':all(checks),'checks':checks,'experiments':outcomes,'timestamp':now()}
    write(ROOT/'results/controlled-remediation.json',report)
    return report
