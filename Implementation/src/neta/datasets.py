"""Dataset preparation is evaluator-only; public projections exclude answers."""
import itertools
import re
import unicodedata
from collections import Counter
from .lab import topology, Lab
from .util import ROOT, digest, read, write, now


def normalize(text):
    # Preserve all identifiers, punctuation and misleading statements.
    return ' '.join(unicodedata.normalize('NFC', text).split())


def prepare():
    def f(family,device,target): return {'family':family,'device':device,'target':target}
    definitions=[
      ('train-link','train',[f('link_down','r1','eth0')]),
      ('train-route','train',[f('route_missing','r1','10.0.2.0/24')]),
      ('train-filter','train',[f('firewall_drop','r2','FORWARD')]),
      ('dev-address','validation',[f('address_missing','pc1','eth0')]),
      ('dev-route','validation',[f('route_wrong','r1','10.0.2.0/24')]),
      ('dev-double','validation',[f('link_down','r2','eth0'),f('route_missing','pc1','default')]),
      ('test-healthy','test',[]),
      ('test-link','test',[f('link_down','r2','eth1')]),
      ('test-route','test',[f('route_missing','r2','10.0.1.0/24')]),
      ('test-address','test',[f('address_missing','pc2','eth0')]),
      ('test-double','test',[f('link_down','r2','eth1'),f('route_missing','r2','10.0.1.0/24')]),
      ('test-triple','test',[f('link_down','r2','eth1'),f('route_missing','r2','10.0.1.0/24'),f('address_missing','pc2','eth0')]),
      ('test-filter','test',[f('firewall_drop','r1','FORWARD')]),
    ]
    # Rewrites and all incident templates sharing constituent fault identities stay together.
    parent=list(range(len(definitions)))
    def root(i):
        while parent[i]!=i: i=parent[i]
        return i
    for i,a in enumerate(definitions):
        for j,b in enumerate(definitions[:i]):
            if any(x in b[2] for x in a[2]): parent[root(i)]=root(j)
    cases=[]; private={}; groups={}
    for i,(cid,split,faults) in enumerate(definitions):
        group='local-group-'+definitions[root(i)][0]
        if group in groups and groups[group]!=split: raise ValueError('Constituent template crosses splits')
        groups[group]=split
        tickets={'standard':'Please check connectivity between pc1 and pc2 and identify any actual fault.',
                 'vague':'The network seems broken. Please investigate.',
                 'incorrect-cause':'The DNS service is definitely broken; fix name resolution.',
                 'incorrect-device':'pc1 is definitely the faulty device; please investigate.',
                 'false-premise':'Both routers have failed and every interface is down.'}
        for style,ticket in tickets.items():
            if split!='test' and style!='standard': continue
            case_id=cid+'--'+style
            public={'case_id':case_id,'incident_id':cid,'incident_group':group,'split':split,'source':'local',
                    'topology':topology(),'ticket':ticket,'normalized_ticket':normalize(ticket),'ticket_style':style}
            cases.append(public)
            private[case_id]={'faults':faults,'fault_templates':[digest(x) for x in faults],
                             'validation_status':'pending','exclusion_reason':None,'masked':len(faults)>1}
    projection={'schema_version':1,'cases':cases}
    target=ROOT/'data/public/local-cases.json'
    if target.exists() and read(target)!=projection:
        raise RuntimeError('Frozen cases changed: create a new dataset version explicitly')
    write(target,projection)
    truth=ROOT/'data/private/local-truth.json'
    if not truth.exists(): write(truth,private)
    write(ROOT/'data/dataset-freeze.json',{'public_sha256':digest(projection),'private_sha256':digest(private),
          'created':now(),'test_frozen':True,'group_policy':'connected components of constituent fault identities and ticket rewrites',
          'counts':{'tickets':len(cases),'incidents':len(definitions),'incident_groups':len(groups),
                    'fault_templates':len(set(digest(f) for _,_,fs in definitions for f in fs)),
                    'topology_structures':1,'fault_families':len(set(f['family'] for _,_,fs in definitions for f in fs))}})
    return projection


def cases(split=None, standard=False):
    rows=read(ROOT/'data/public/local-cases.json')['cases']
    return [x for x in rows if (split is None or x['split']==split) and (not standard or x['ticket_style']=='standard')]


def validate(case_id):
    import fcntl
    lock=ROOT/'runtime/experiment.lock'
    lock.parent.mkdir(parents=True,exist_ok=True)
    with lock.open('w') as handle:
        fcntl.flock(handle,fcntl.LOCK_EX)
        return _validate(case_id)


def _validate(case_id):
    case=next(c for c in cases() if c['case_id']==case_id)
    all_truth=read(ROOT/'data/private/local-truth.json'); truth=all_truth[case_id]
    lab=Lab(); record={'case_id':case_id,'timestamp':now(),'stages':{},'status':'failed'}
    healthy=lab.baseline()
    try:
        record['stages']['healthy']=lab.connectivity()
        record['stages']['injection']=lab.inject(truth['faults'])
        faulty=lab.snapshot()
        holds=[lab.fault_holds(f,faulty) for f in truth['faults']]
        impact=lab.connectivity()
        record['stages']['root_state']={'all_hold':all(holds),'per_fault':holds,'snapshot':faulty}
        record['stages']['impact']=impact
        partial=[]
        # Each fault is repaired alone from the compound faulty snapshot, then residual faults rechecked.
        from .remediation import reference_action
        for f in truth['faults']:
            lab.restore(faulty)
            lab.action(reference_action(f))
            remaining=[x for x in truth['faults'] if x!=f]
            residual=[lab.fault_holds(x) for x in remaining]
            partial.append({'repaired':f,'remaining':remaining,'residual_holds':residual,'connectivity':lab.connectivity()})
        record['stages']['partial_repairs']=partial
        valid=record['stages']['healthy']['passed'] and all(holds) and impact['passed']==(not truth['faults'])
        valid=valid and all(all(p['residual_holds']) for p in partial)
        record['status']='validated' if valid else 'failed'
    except Exception as exc:
        record['error']=f'{type(exc).__name__}: {exc}'
    finally:
        try:
            lab.restore(healthy)
            record['stages']['restored']=lab.connectivity()
            if not record['stages']['restored']['passed']: record['status']='failed'
        except Exception as exc:
            record['status']='failed'; record['restoration_error']=str(exc)
    for c in cases():
        if c['incident_id']==case['incident_id']:
            all_truth[c['case_id']]['validation_status']=record['status']
            all_truth[c['case_id']]['exclusion_reason']=record.get('error') or (None if record['status']=='validated' else 'state, impact or residual consistency failed')
    write(ROOT/'data/private/local-truth.json',all_truth)
    write(ROOT/'results/validation-history'/f'{case["incident_id"]}-{digest(record)[:12]}.json',record)
    write(ROOT/'results/validation'/f'{case["incident_id"]}.json',record)
    return record
