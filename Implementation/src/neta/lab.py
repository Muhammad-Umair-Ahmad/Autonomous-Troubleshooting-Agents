"""Trusted controller. Never copied into the agent sandbox."""
import json
import re
import shutil
import uuid
from pathlib import Path
from .contracts import ToolRequest, Observation, Action, Fault
from .util import ROOT, now, run, read, write, digest

INTENT = {
 'pc1': {'eth0': '10.0.1.10/24'},
 'r1': {'eth0': '10.0.1.1/24', 'eth1': '10.0.12.1/30'},
 'r2': {'eth0': '10.0.12.2/30', 'eth1': '10.0.2.1/24'},
 'pc2': {'eth0': '10.0.2.10/24'},
}
ROUTES = {'pc1': {'default': '10.0.1.1'}, 'r1': {'10.0.2.0/24': '10.0.12.2'},
          'r2': {'10.0.1.0/24': '10.0.12.1'}, 'pc2': {'default': '10.0.2.1'}}

def topology():
    return {'id': 'four_device_chain_v1', 'interfaces': INTENT, 'routes': ROUTES,
            'links': [['pc1:eth0','r1:eth0'],['r1:eth1','r2:eth0'],['r2:eth1','pc2:eth0']],
            'scope': 'IPv4 static routing and packet filtering; no DNS/OSPF/BGP services'}

class Lab:
    def __init__(self, name='main'):
        if name not in ('main', 'twin'):
            raise ValueError('Only owned main/twin labs supported')
        self.name = name
        self.path = ROOT / 'runtime' / 'labs' / name
        self.registry = ROOT / 'runtime' / f'{name}.json'
        self.ids = read(self.registry)['ids'] if self.registry.exists() else {}
        self.seq = 0

    def deploy(self):
        if self.ids:
            self.assert_owned(require_running=False)
            run(['docker','start',*self.ids.values()],timeout=90)
            self.assert_owned()
            return
        before = set(run(['docker','ps','-aq'])['stdout'].split())
        self.path.mkdir(parents=True, exist_ok=True)
        shutil.copytree(ROOT / 'labs/base', self.path, dirs_exist_ok=True)
        conf = self.path / 'lab.conf'
        text = conf.read_text().replace('autonomous_agent_base', f'neta_research_{self.name}')
        # Pin local container identities, not mutable image tags.
        images = read(ROOT / 'results/prerequisites/images.json')
        for im in images:
            for tag in im.get('RepoTags', []):
                text = text.replace(f'"{tag}"', f'"{im["Id"]}"')
        conf.write_text(text)
        result = run(['kathara','lstart','-d',self.path,'--noterminals','--no-hosthome','--no-shared'], timeout=180, check=False)
        after = set(run(['docker','ps','-aq'])['stdout'].split())
        candidates = list(after - before)
        meta = json.loads(run(['docker','inspect',*candidates])['stdout']) if candidates else []
        labels = {m['Config']['Labels'].get('lab_hash') for m in meta if m['Config'].get('Labels',{}).get('app')=='kathara'}
        if len(labels) != 1:
            raise RuntimeError(f'Cannot uniquely register owned lab: {result}')
        self.ids = {m['Config']['Labels']['name']: m['Id'] for m in meta if m['Config'].get('Labels',{}).get('lab_hash') in labels}
        write(self.registry, {'ids':self.ids,'lab_hash':labels.pop(),'path':str(self.path),'created':now()})
        self.assert_owned()
        for d in INTENT:
            run(['kathara','exec','-d',self.path,'--wait',d,'ip -brief address'], timeout=90)
        if result['returncode']:
            raise RuntimeError(str(result))

    def assert_owned(self, require_running=True):
        registered = read(self.registry)
        if registered['path'] != str(self.path) or set(self.ids) != set(INTENT):
            raise PermissionError('Invalid owned lab registry')
        meta = json.loads(run(['docker','inspect',*self.ids.values()])['stdout'])
        for m in meta:
            labels = m['Config'].get('Labels',{})
            if labels.get('app')!='kathara' or labels.get('lab_hash') != registered['lab_hash'] or (require_running and not m['State']['Running']):
                raise PermissionError('Container identity/lab ownership mismatch')

    def cmd(self, device, argv, check=True, timeout=15, stdin=None):
        if device not in self.ids:
            raise PermissionError('Device not registered to this lab')
        args = ['docker','exec'] + (['-i'] if stdin is not None else []) + [self.ids[device], *argv]
        return run(args, check=check, timeout=timeout, input=stdin)

    def inspect(self, request):
        req = ToolRequest.model_validate(request)
        commands = {'interfaces':['ip','-j','link','show'], 'addresses':['ip','-j','address','show'],
                    'routes':['ip','-j','route','show'], 'firewall':['iptables-save','-t','filter']}
        argv = commands.get(req.kind)
        if req.kind == 'ping':
            if req.target is None: raise ValueError('Ping requires an allowed IPv4 target')
            argv = ['ping','-n','-c','2','-W','1', req.target]
        result = self.cmd(req.device, argv, check=False)
        self.seq += 1
        parsed = None
        if req.kind in ('interfaces','addresses','routes') and result['returncode']==0:
            parsed = json.loads(result['stdout'])
        return Observation(evidence_id=f'{self.name}-{uuid.uuid4().hex[:12]}', timestamp_utc=now(),
                           device=req.device, kind=req.kind, raw=result, parsed=parsed).model_dump()

    def snapshot(self):
        result = {}
        for d in INTENT:
            address = json.loads(self.cmd(d,['ip','-j','address','show'])['stdout'])
            interfaces = {}
            for interface in address:
                n = interface['ifname']
                if n in INTENT[d]:
                    interfaces[n] = {'up':'UP' in interface['flags'],
                                     'addresses':sorted(f"{a['local']}/{a['prefixlen']}" for a in interface['addr_info'] if a['family']=='inet')}
            routes = json.loads(self.cmd(d,['ip','-j','route','show'])['stdout'])
            routes = sorted([{'dst':r.get('dst','default'),'gateway':r['gateway']} for r in routes if r.get('gateway')],key=lambda r:r['dst'])
            self.cmd(d,['iptables','-S'])
            fw = self.cmd(d,['iptables-save','-t','filter'])['stdout']
            fw = '\n'.join(x for x in fw.splitlines() if not x.startswith('#'))
            fw = re.sub(r'\[\d+:\d+\]', '[0:0]', fw)
            result[d] = {'interfaces':interfaces,'routes':routes,'firewall':fw}
        return result

    def restore(self, state):
        for d, s in state.items():
            for iface, value in s['interfaces'].items():
                self.cmd(d,['ip','address','flush','dev',iface,'scope','global'])
                for addr in value['addresses']:
                    self.cmd(d,['ip','address','add',addr,'dev',iface])
                self.cmd(d,['ip','link','set',iface,'up' if value['up'] else 'down'])
            current = json.loads(self.cmd(d,['ip','-j','route','show'])['stdout'])
            for route in current:
                if route.get('gateway'):
                    self.cmd(d,['ip','route','del',route.get('dst','default')],check=False)
            for route in s['routes']:
                self.cmd(d,['ip','route','replace',route['dst'],'via',route['gateway']])
            self.cmd(d,['iptables-restore'],stdin=s['firewall']+'\n')
        actual = self.snapshot()
        if actual != state:
            write(ROOT/'results/fidelity-failure.json',{'expected':state,'actual':actual})
            raise RuntimeError('Snapshot restoration fidelity check failed')

    def baseline(self):
        self.deploy()
        path = ROOT/'runtime/healthy.json'
        if path.exists(): self.restore(read(path))
        else:
            state = self.snapshot()
            for d in INTENT:
                if any(not v['up'] or v['addresses'] != [INTENT[d][i]] for i,v in state[d]['interfaces'].items()):
                    raise RuntimeError('Bad healthy startup interfaces')
                if {r['dst']:r['gateway'] for r in state[d]['routes']} != ROUTES[d]:
                    raise RuntimeError('Bad healthy startup routes')
            if not self.connectivity()['passed']: raise RuntimeError('Healthy baseline connectivity failed')
            write(path,state)
        return self.snapshot()

    def connectivity(self):
        pairs=[('pc1','10.0.2.10'),('pc2','10.0.1.10'),('pc1','10.0.1.1'),('pc2','10.0.2.1'),('r1','10.0.12.2'),('r2','10.0.12.1')]
        warmup=[{'device':d,'target':t,'result':self.cmd(d,['ping','-n','-c','1','-W','1',t],check=False)} for d,t in pairs]
        records=[self.inspect({'device':d,'kind':'ping','target':t}) for d,t in pairs]
        passed=all(r['raw']['returncode']==0 and re.search(r'(?<!\d)0% packet loss',r['raw']['stdout']) for r in records)
        return {'passed':bool(passed),'records':records,'warmup':warmup}

    def action(self, action):
        a=Action.model_validate(action)
        iface_ops={'link_up','link_down','address_add','address_delete'}
        if a.op in iface_ops and a.target not in INTENT[a.device]: raise PermissionError('Unknown interface')
        if a.op.startswith('route_') and a.target not in ROUTES[a.device]: raise PermissionError('Unknown route prefix')
        if a.op=='route_replace' and a.value not in {'10.0.1.1','10.0.2.1','10.0.12.1','10.0.12.2','10.0.12.3'}:
            raise PermissionError('Next hop outside research scope')
        if a.op.startswith('address_') and a.value != INTENT[a.device][a.target]: raise PermissionError('Address outside intent')
        if a.op in ('link_up','link_down'): argv=['ip','link','set',a.target,'up' if a.op=='link_up' else 'down']
        elif a.op in ('address_add','address_delete'): argv=['ip','address','replace' if a.op=='address_add' else 'del',a.value,'dev',a.target]
        elif a.op=='route_replace': argv=['ip','route','replace',a.target,'via',a.value]
        elif a.op=='route_delete': argv=['ip','route','del',a.target]
        elif a.op=='firewall_clear':
            if a.target!='filter' or a.value: raise PermissionError('Invalid firewall scope')
            argv=['iptables','-F']
        else: raise PermissionError('Firewall restore is controller-only through captured state')
        return self.cmd(a.device,argv)

    def inject(self, faults):
        records=[]
        for raw in faults:
            f=Fault.model_validate(raw)
            if f.family=='firewall_drop':
                if f.target!='FORWARD' or f.device not in ('r1','r2'): raise ValueError('Bad firewall injection')
                records.append(self.cmd(f.device,['iptables','-A','FORWARD','-j','DROP']))
                continue
            op={'link_down':'link_down','route_missing':'route_delete','route_wrong':'route_replace','address_missing':'address_delete'}[f.family]
            value=INTENT[f.device].get(f.target,'') if f.family=='address_missing' else ''
            if f.family=='route_wrong': value='10.0.12.1' if f.device=='r1' else '10.0.12.2'
            records.append(self.action({'op':op,'device':f.device,'target':f.target,'value':value}))
        return records

    def fault_holds(self, fault, state=None):
        f=Fault.model_validate(fault); s=(state or self.snapshot())[f.device]
        if f.family=='link_down': return not s['interfaces'][f.target]['up']
        if f.family=='address_missing': return INTENT[f.device][f.target] not in s['interfaces'][f.target]['addresses']
        if f.family=='firewall_drop': return '-A FORWARD -j DROP' in s['firewall']
        route=next((r for r in s['routes'] if r['dst']==f.target),None)
        if f.family=='route_missing': return route is None
        return route is not None and route['gateway'] != ROUTES[f.device][f.target]

    def cleanup(self):
        if self.registry.exists():
            self.assert_owned(require_running=False)
            run(['kathara','lclean','-d',self.path],timeout=120)
            self.registry.unlink()
            self.ids={}
