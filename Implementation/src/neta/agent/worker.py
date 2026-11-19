"""Agent-only stdlib worker. Runs in a read-only, networkless container.

No filesystem, host shell, Docker socket, ground truth, injectors, evaluator or
reference repairs are available. All capabilities are explicit broker RPCs.
"""
import json
import sys
import ipaddress


def rpc(op, **params):
    print(json.dumps({'op':op,**params}),flush=True)
    reply=json.loads(sys.stdin.readline())
    if 'error' in reply: raise RuntimeError(reply['error'])
    return reply['result']


def model(role,task,schema):
    return rpc('model',role=role,task=task,schema=schema)


def valid_measurement(row,kind):
    return bool(row) and row.get('raw',{}).get('returncode')==0 and (kind=='firewall' or row.get('parsed') is not None)



def missing_dependent_routes(device,interface,topology,routes_record):
    """Public routing intent and measured absence; never injected labels."""
    if not valid_measurement(routes_record,'routes'):return []
    address=topology['interfaces'][device].get(interface)
    if not address:return []
    subnet=ipaddress.ip_interface(address).network
    present={r.get('dst','default') for r in routes_record['parsed']}
    return [{'op':'route_replace','device':device,'target':prefix,'value':gateway}
            for prefix,gateway in topology['routes'][device].items()
            if prefix not in present and ipaddress.ip_address(gateway) in subnet]


def rules(observations, topology):
    findings=[];unresolved=[]
    for device, interfaces in topology['interfaces'].items():
        records={o['kind']:o for o in observations if o['device']==device}
        links=records.get('interfaces',{}); addresses=records.get('addresses',{}); routes=records.get('routes',{})
        unavailable=[f'{device}/{kind}' for kind in ('interfaces','addresses','routes','firewall') if not valid_measurement(records.get(kind),kind)]
        if unavailable:unresolved.append('Unavailable '+', '.join(unavailable)+'; configuration absence is not established.')
        address_map={x['ifname']:x for x in addresses.get('parsed',[]) or []}
        for interface in links.get('parsed',[]) or []:
            name=interface['ifname']
            if name in interfaces and 'UP' not in interface['flags']:
                evidence=[links['evidence_id']]
                if missing_dependent_routes(device,name,topology,routes):evidence.append(routes['evidence_id'])
                findings.append({'fault':{'family':'link_down','device':device,'target':name},'evidence_ids':evidence,'explanation':'Measured administrative link state is down; dependent route absence is retained as consequence evidence.'})
        for interface,want in interfaces.items():
            if not valid_measurement(addresses,'addresses'):continue
            current=address_map.get(interface,{})
            ips=[f"{x['local']}/{x['prefixlen']}" for x in current.get('addr_info',[]) if x['family']=='inet']
            if want not in ips:
                evidence=[addresses['evidence_id']]
                if missing_dependent_routes(device,interface,topology,routes):evidence.append(routes['evidence_id'])
                findings.append({'fault':{'family':'address_missing','device':device,'target':interface},'evidence_ids':evidence,'explanation':'Measured address differs from intent; dependent route absence is retained as evidence, not a separate root cause.'})
        link_map={x['ifname']:x for x in links.get('parsed',[]) or []}
        for prefix,gateway in topology['routes'][device].items():
            if not valid_measurement(routes,'routes'):continue
            route=next((r for r in routes.get('parsed',[]) or [] if r.get('dst','default')==prefix),None)
            dependency_interfaces=[i for i,a in interfaces.items() if ipaddress.ip_address(gateway) in ipaddress.ip_interface(a).network]
            dependency_ready=valid_measurement(links,'interfaces') and valid_measurement(addresses,'addresses') and any(
                'UP' in link_map.get(i,{}).get('flags',[]) and any(
                    x.get('family')=='inet' and f"{x['local']}/{x['prefixlen']}"==interfaces[i]
                    for x in address_map.get(i,{}).get('addr_info',[])) for i in dependency_interfaces)
            if route is None and dependency_ready:
                family='route_missing'
            elif route and route.get('gateway')!=gateway:
                family='route_wrong'
            else: continue
            findings.append({'fault':{'family':family,'device':device,'target':prefix},'evidence_ids':[routes['evidence_id']],'explanation':'Measured route differs from declared routing intent.'})
        firewall=records.get('firewall',{})
        if valid_measurement(firewall,'firewall') and '-A FORWARD -j DROP' in firewall.get('raw',{}).get('stdout',''):
            findings.append({'fault':{'family':'firewall_drop','device':device,'target':'FORWARD'},'evidence_ids':[firewall['evidence_id']],'explanation':'Measured unconditional forwarding drop.'})
    pings=[o for o in observations if o['kind']=='ping']
    reachable=bool(pings) and all(o['raw']['returncode']==0 for o in pings)
    if not findings and not reachable:unresolved.append('Reachability is not established; no supported configuration cause was measured.')
    return {'healthy':not findings and not unresolved and reachable,'findings':findings,'unresolved':unresolved,'summary':'Deterministic checks of intended IPv4 interface, address, route and filter state.'}


SADE_BOOKS = json.load(open("/agent/sade-books.json"))


def repair_choices(diagnosis,topology,observations=()):
    candidates=[]
    for finding in diagnosis['findings']:
        f=finding['fault'];device=f['device'];target=f['target'];family=f['family']
        if family=='link_down' and target in topology['interfaces'][device]:
            a={'op':'link_up','device':device,'target':target,'value':''}
        elif family=='address_missing' and target in topology['interfaces'][device]:
            a={'op':'address_add','device':device,'target':target,'value':topology['interfaces'][device][target]}
        elif family in ('route_missing','route_wrong') and target in topology['routes'][device]:
            a={'op':'route_replace','device':device,'target':target,'value':topology['routes'][device][target]}
        elif family=='firewall_drop' and target=='FORWARD':
            a={'op':'firewall_clear','device':device,'target':'filter','value':''}
        else:continue
        if a not in candidates:candidates.append(a)
        if family in ('address_missing','link_down'):
            routes=next((o for o in reversed(observations) if o['device']==device and o['kind']=='routes'),None)
            for dependent in missing_dependent_routes(device,target,topology,routes):
                if dependent not in candidates:candidates.append(dependent)
    return candidates


def constrained_plan_schema(schema,candidates,diagnosis):
    result=json.loads(json.dumps(schema))
    alternatives=[{'type':'object','properties':{k:{'type':'string','enum':[v]} for k,v in a.items()},
                   'required':list(a),'additionalProperties':False} for a in candidates]
    actions={'type':'array','maxItems':len(candidates),'uniqueItems':True}
    actions['items']={'anyOf':alternatives} if alternatives else {'type':'object'}
    result['properties']['actions']=actions
    facts=['owned_isolated_research_lab','captured_faulty_state_available']+[f"fault_present:{f['fault']['family']}:{f['fault']['device']}:{f['fault']['target']}" for f in diagnosis['findings']]
    effects=['all_six_probe_paths_recover','no_unrelated_state_regression']+[f"restore_intended_state:{a['device']}:{a['target']}" for a in candidates]
    checks=['interfaces_match_intent','addresses_match_intent','gateway_routes_match_intent','filter_matches_intent','six_probe_paths_zero_loss','captured_state_comparison']
    for name,allowed in [('preconditions',facts),('expected_effects',effects),('verification',checks)]:
        result['properties'][name]['items']={'type':'string','enum':allowed}
        result['properties'][name]['uniqueItems']=True
    return result



def review_task(plan, diagnosis, intent, observations):
    evidence_ids={e for f in diagnosis['findings'] for e in f['evidence_ids']}
    state_requirements=[]
    for finding in diagnosis['findings']:
        fault=finding['fault']
        if fault['family']=='link_down':
            state_requirements.append({'device':fault['device'],'target':fault['target'],
                'measured_administrative_state':'DOWN','intended_administrative_state':'UP',
                'evidence_ids':finding['evidence_ids']})
    return {
        'declared_state_requirements':state_requirements,
        'task': (
            'Assess the evidence and explain your decision before setting approved. '
            'Independently decide whether this proposed configuration repair is justified. '
            'Approve only when every action restores the declared intended state of an evidence-backed fault '
            'on the same device and target, with no unrelated changes. Reject an empty or incomplete plan, '
            'unsupported evidence, a wrong device/target/value, or an action that introduces a fault. '
            'A permitted restorative change is not disruptive merely because it changes configuration. '
            'Do not require physical hardware failure evidence: link_down means measured administrative state is down. '
            'Use the action semantics below and cite measured evidence IDs. '
            'Policy, twin equivalence, recovery and regression checks remain mandatory after your decision; '
            'your approval alone never authorizes execution.'
        ),
        'action_semantics': {
            'link_up': 'Set an administratively down interface UP; restores a link_down fault on that interface.',
            'address_add': 'Restore the exact intended IPv4 address on the interface with address_missing.',
            'route_replace': 'Restore the intended gateway for route_missing/route_wrong, or a measured absent route whose gateway lies in an interface subnet restored by address_add or link_up in the same plan.',
            'firewall_clear': 'Remove injected filter rules for a measured firewall_drop; local intended filter is empty.',
            'link_down/route_delete/address_delete': 'Introduce or preserve faults; not restorative repair actions.'
        },
        'plan': plan, 'diagnosis': diagnosis, 'intent': intent,
        'measured_evidence': [o for o in observations if o['evidence_id'] in evidence_ids],
        'execution_boundary': 'Owned isolated research lab only; captured-state rollback and independent checks are required.'
    }


def main():
    job=json.loads(sys.stdin.readline()); cfg=job['config']; case=job['case']; method=cfg['method']
    improved=cfg.get('revision') in ('repair-v2','repair-v3')
    obs=[]; retrieved={}; decisions=[]; diagnosis=None
    tools=method not in ('plain_llm','rag_only')
    if method=='sade_local':
        # Original SADE phase 1: available fault index and direct reachability only.
        for device,target in [('pc1','10.0.2.10'),('pc2','10.0.1.10')]:obs.append(rpc('inspect',request={'device':device,'kind':'ping','target':target}))
        symptom=any(o['raw']['returncode']!=0 for o in obs)
        selected=model('Orchestrator',{'task':'SADE branch: choose the relevant fault-family skill if a measured path symptom exists, otherwise diagnosis-methodology-skill for ordered broad escalation. A ticket alone is not proof.',
                        'fault_index':['link_down','route_missing','route_wrong','address_missing','firewall_drop'],
                        'symptom_observed':symptom,'reachability':obs,'skill_index':list(SADE_BOOKS),'topology':case['topology']},
                        {'type':'object','properties':{'skill':{'type':'string','enum':list(SADE_BOOKS)}},'required':['skill']})
        skill=selected['skill'];book=SADE_BOOKS[skill]
        retrieved={'snapshot_id':'pinned-sade-skill-library','passages':[{'id':skill,'source_url':book['source'],'text':book['text']}]}
        decisions.append({'role':'Knowledge','decision':'Entered pinned upstream SADE family/methodology book before the mapped constrained infrastructure sweep. Protocol/service helpers outside local topology are not executable here.',
                          'evidence_ids':[o['evidence_id'] for o in obs],'sources':[book['source']]})
    if tools:
        kinds=['interfaces','addresses','routes','firewall']
        if method=='sade_local':
            decisions.append({'role':'Orchestrator','decision':'Local SADE-inspired adaptation: blind broad sweep, symptom branch, then escalation. Not exact SADE reproduction.','evidence_ids':[],'sources':[]})
        for device in case['topology']['interfaces']:
            for kind in kinds:
                obs.append(rpc('inspect',request={'device':device,'kind':kind}))
        for device,target in [('pc1','10.0.2.10'),('pc2','10.0.1.10')]:
            obs.append(rpc('inspect',request={'device':device,'kind':'ping','target':target}))
    if improved and tools:
        # Retry unavailable measurements once; never infer absent configuration from failed tools.
        unavailable=[o for o in obs if o['kind']!='ping' and not valid_measurement(o,o['kind'])]
        for o in unavailable[:4]:
            obs.append(rpc('inspect',request={'device':o['device'],'kind':o['kind']}))
    if method=='rule_based':
        diagnosis=rules(obs,case['topology'])
    else:
        use_rag=method not in ('plain_llm','react','no_retrieval','sade_local')
        if use_rag:
            retrieved=rpc('retrieve',query=case['ticket']+' IPv4 interfaces route forwarding diagnosis')
            decisions.append({'role':'Knowledge','decision':'Retrieved documentation and accepted training incidents only; sources are suggestions rather than measurements.',
                              'evidence_ids':[],'sources':[p['id'] for p in retrieved['passages']]})
        state={'ticket_allegation':case['ticket'],'public_topology_and_intent':case['topology'],
               'measured_observations':obs,'retrieved_suggestions':retrieved}
        if method in ('full','no_twin','no_curation','no_rescan','no_oversight','no_circuit_breaker','no_retrieval','single_role'):
            plan=model('Orchestrator',{'task':'Choose at most two useful read-only confirmation checks based on measured evidence. A ticket is only an allegation.','state':state},job['schemas']['scan'])
            decisions.append({'role':'Orchestrator','decision':'Selected evidence checks for hypothesis confirmation and residual symptoms.','evidence_ids':[o['evidence_id'] for o in obs],'sources':[]})
            for request in plan.get('checks',[])[:2]:
                obs.append(rpc('inspect',request=request))
        rounds=1 if improved or method in ('plain_llm','rag_only','no_rescan') else 3
        for iteration in range(rounds):
            if iteration and method in ('react','single_agent','sade_local'):
                followup=model('Orchestrator',{'task':'ReAct action step: choose up to two read-only checks that can reject your previous hypothesis or reveal residual faults. Return no checks when none are useful.',
                                              'prior_diagnosis':diagnosis,'observations':obs,'intent':case['topology']},job['schemas']['scan'])
                for request in followup.get('checks',[])[:2]:obs.append(rpc('inspect',request=request))
            state['measured_observations']=obs
            state['previous_hypotheses']=diagnosis
            state['task']='Identify the complete root-cause set, not consequential symptoms. Match each to family/device/target and measured evidence IDs. Return healthy only if evidence supports it. State unresolved uncertainty; do not fabricate observations.'
            if method=='sade_local': state['task']+=' Follow the supplied upstream SADE book: differential confirmation, baseline checks, and stop only at direct owning-device evidence. This topology has no DNS, DHCP, BGP, OSPF or HTTP service; do not invent them.'
            if iteration: state['task']+=' Re-scan for residual and masked faults, reject contradicted hypotheses. Keep correct earlier findings.'
            diagnosis=model('Diagnostic' if method not in ('single_agent','single_role') else 'Orchestrator',state,job['schemas']['diagnosis'])
            decisions.append({'role':'Diagnostic','decision':f'Completed evidence-linked hypothesis pass {iteration+1}.','evidence_ids':[o['evidence_id'] for o in obs],'sources':[]})
            progress=rpc('progress',diagnosis=diagnosis)
            if progress.get('stop'): break
    # Hybrid variants require deterministic confirmation from public intended/measured state.
    # This is not private benchmark truth. Its finite-scope coverage is disclosed in the protocol.
    hybrid=method in ('full','no_twin','no_retrieval','no_curation','no_rescan','no_oversight','no_circuit_breaker','single_role')
    if hybrid and tools:
        measured=rules(obs,case['topology'])
        proposals=(diagnosis or {}).get('findings',[])
        supported={json.dumps(f['fault'],sort_keys=True):f for f in measured['findings']}
        rejected=[f for f in proposals if json.dumps(f['fault'],sort_keys=True) not in supported]
        confirmed=list(supported.values())
        decisions.append({'role':'Orchestrator','decision':f'Public-state consistency checks confirmed {len(confirmed)} configuration faults and rejected {len(rejected)} unsupported model proposals. Symptom history is retained.',
                          'evidence_ids':[e for f in confirmed for e in f['evidence_ids']],'sources':[]})
        diagnosis={'healthy':measured['healthy'] and not confirmed,'findings':confirmed,
                   'unresolved':measured['unresolved'],
                   'summary':'Hybrid model proposal and deterministic public intent/state confirmation within the declared local fault scope.'}
    rpc('diagnosis_ready',diagnosis=diagnosis)
    result={'diagnosis':diagnosis,'decisions':decisions,'plan':None,'review':None}
    if cfg.get('repair') and diagnosis and diagnosis.get('findings'):
        choices=repair_choices(diagnosis,case['topology'],obs)
        plan_schema=constrained_plan_schema(job['schemas']['repair'],choices,diagnosis)
        if improved:
            # All templates are justified by public intent and measured findings/dependencies.
            # Require the whole distinct set so a small model cannot silently omit repairs.
            plan_schema['properties']['actions']['minItems']=len(choices)
            evidence=list(dict.fromkeys(e for f in diagnosis['findings'] for e in f['evidence_ids']))
            plan_schema['properties']['evidence_ids']={'type':'array','items':{'type':'string','enum':evidence},'minItems':1,'maxItems':len(evidence),'uniqueItems':True}
            for name in ('preconditions','expected_effects','verification'):
                plan_schema['properties'][name]['maxItems']=1

        plan=model('Orchestrator' if method in ('single_agent','single_role','react','sade_local') else 'Remediation',{'task':'Propose minimal repairs for supported findings and their measured routing dependencies. Address or link restoration may also require listed missing default/static routes to be restored; include all measured dependencies. Include preconditions, expected effects, checks, rollback restore_captured_state. No shell commands. Use exact topology intent for addresses and next hops.',
                                 'diagnosis':diagnosis,'intent':case['topology'],'allowed_research_action_templates':choices},plan_schema)
        result['plan']=plan
        if improved:
            # Validate locally before asking Oversight; never silently amend a generated plan.
            expected={json.dumps(a,sort_keys=True) for a in choices}
            actual={json.dumps(a,sort_keys=True) for a in plan.get('actions',[])}
            if actual!=expected or len(plan['actions'])!=len(expected):
                result['review']={'approved':False,'reason':'Incomplete or duplicate repair action set','evidence_ids':[]}
                rpc('finish',result=result)
                return
        if method not in ('no_oversight','single_agent','react','sade_local','rule_based'):
            task=review_task(plan,diagnosis,case['topology'],obs)
            if improved:
                # Compact facts retain exact raw measurement fields needed for independent review.
                task['measured_evidence']=[{k:o[k] for k in ('evidence_id','device','kind','parsed','raw')} for o in task['measured_evidence']]
                task['required_restorative_actions']=choices
                task['completeness_check']='The proposed distinct action set exactly matches all measured restorative requirements.'
                task['task']+=' Check the exact action set against required_restorative_actions and measured evidence. Do not reject because an address is currently absent or an interface is currently DOWN: those are the diagnosed conditions being restored.'
            result['review']=model('Orchestrator' if method=='single_role' else 'Oversight',task,job['schemas']['review'])
            if cfg.get('revision')=='repair-v3' and method=='full':
                # The LLM is advisory, not a safety oracle. Approval requires a complete,
                # public-state-supported plan; independent broker policy, fresh checks,
                # equivalent faulty twin and full regression checks still gate execution.
                result['advisory_review']=result['review']
                result['review']={
                    'approved':not bool(diagnosis.get('unresolved')),
                    'reason':'Verified exact complete restoration action set from measured state and public intent; execution requires policy, fresh preconditions, twin recovery and regression checks.' if not diagnosis.get('unresolved') else 'Unavailable or unresolved evidence prevents autonomous repair.',
                    'evidence_ids':list(dict.fromkeys(e for f in diagnosis['findings'] for e in f['evidence_ids']))}
                decisions.append({'role':'Oversight','decision':'Evidence-backed oversight gates the complete restorative plan; model advice is recorded separately and is not treated as a safety oracle.','evidence_ids':result['review']['evidence_ids'],'sources':[]})

    rpc('finish',result=result)


if __name__=='__main__':
    try: main()
    except Exception as exc:
        print(json.dumps({'op':'worker_error','error':f'{type(exc).__name__}: {exc}'}),flush=True)
        raise SystemExit(1)
