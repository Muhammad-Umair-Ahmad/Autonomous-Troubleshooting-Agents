"""Pinned source catalogues and controlled upstream lifecycle adapters.

Published labels, scoring rubrics and injection scripts remain controller-only.
No paid upstream agents or LLM judges are launched here.
"""
import csv
from dataclasses import asdict
import importlib.util
import re
import platform
from pathlib import Path
import yaml
from .util import ROOT, digest, run, write, read, now

SOURCES={'nika':'https://github.com/sands-lab/nika.git',
         'fault-bench':'https://github.com/Overlxrd-uwu/FaulT-Bench.git',
         'SADE-NetworkAgent':'https://github.com/Overlxrd-uwu/SADE-NetworkAgent.git'}


def inventory():
    lock={}; catalog=[]; private={}; errors=[]
    for name,url in SOURCES.items():
        path=ROOT/'vendor'/name
        commit=run(['git','-C',path,'rev-parse','HEAD'])['stdout'].strip()
        tracked=run(['git','-C',path,'ls-files','-z'])['stdout'].split('\0')
        files={relative:digest((path/relative).read_bytes()) for relative in sorted(tracked) if relative and (path/relative).is_file()}
        lock[name]={'url':url,'commit':commit,'tree_hash':digest(files),'file_hashes':files}
    source=ROOT/'vendor/fault-bench/faultbench/src/faultbench/scenario.py'
    spec=importlib.util.spec_from_file_location('fb_scenario',source)
    import sys
    module=importlib.util.module_from_spec(spec); sys.modules['fb_scenario']=module; spec.loader.exec_module(module)
    for p in sorted((ROOT/'vendor/fault-bench/dataset').glob('*_Q/**/*.txt')):
        try:
            s=module.parse_scenario(p)
            # Grounded grouping is more robust than filename suffixes: persona and misdirection derivatives share state.
            group=digest({'topology':s.topology,'injection':s.injection.__dict__})[:20]
            split=('train' if int(group[:8],16)%10<6 else 'validation' if int(group[:8],16)%10<8 else 'test')
            uid='faultbench:'+s.scenario_id
            catalog.append({'case_id':uid,'source':'fault-bench','source_id':s.scenario_id,'incident_group':group,
                            'split':split,'official_split':None,'ticket':s.prompt_to_agent,'topology_structure':s.topology,
                            'status':'pending_runtime_validation','ticket_style':s.ticket_style,'source_sha256':digest(p.read_bytes())})
            private[uid]={'path':str(p.relative_to(ROOT)),'scenario':asdict(s),'status':'pending_runtime_validation'}
        except Exception as exc: errors.append({'path':str(p),'reason':str(exc)})
    for split,file in [('validation','dev.yaml'),('test','test.yaml')]:
        data=yaml.safe_load((ROOT/'vendor/nika/benchmark/releases/0.2.0'/file).read_text())
        for i,c in enumerate(data['cases']):
            uid=f'nika:0.2.0:{file}:{i}'
            # Preserve official split; flag rather than move any overlapping templates.
            group=digest({k:v for k,v in c.items() if k not in ('root_causes','task_id','ticket','prompt')})[:20]
            catalog.append({'case_id':uid,'source':'nika','source_id':c.get('task_id',str(i)),
                            'incident_group':group,'split':split,'official_split':file,'ticket':c.get('ticket') or c.get('prompt') or '',
                            'topology_structure':c.get('scenario'),'status':'pending_runtime_validation','source_sha256':digest(c)})
            private[uid]={'definition':c,'status':'pending_runtime_validation'}
    overlaps=[]; seen={}
    for c in catalog:
        group=(c['source'],c['incident_group'])
        if group in seen and seen[group]!=c['split']: overlaps.append(c['case_id'])
        seen[group]=c['split']
    # Cross-source overlap needs canonical state/topology comparison, not lexical ticket matching alone.
    index=ROOT/'data/public/upstream-catalog.json'
    write(index,catalog); write(ROOT/'data/private/upstream-truth.json',private)
    write(ROOT/'configs/sources.lock.json',{'retrieved_utc':now(),'sources':lock})
    report={'counts':{name:sum(c['source']==name for c in catalog) for name in ('nika','fault-bench')},
            'parse_failures':errors,'official_split_overlap_flags':overlaps,
            'cross_source_overlap':'pending topology/state semantic mapping; sources must be reported separately',
            'counts_note':'catalogued tickets are not validated executable incidents',
            'current_host':platform.platform(),'linux_execution':'pending nested daemon verification',
            'upstream_notes':['NIKA requires Linux, Python 3.12+, Docker and VRF host support.',
                              'FaulT-Bench warns against Docker 29 with Kathara 3.8.3.',
                              'Original SADE and official LLM judges require paid providers; exact reruns unavailable under zero paid inference policy.']}
    write(ROOT/'results/upstream-inventory.json',report)
    return report

class NikaAdapter:
    """Trusted scoped NIKA lifecycle on the configured dedicated Linux VM."""
    def __init__(self):
        self.session=None
        self.last_deployment=None
        config_path=ROOT/'configs/upstream-runtime.json'
        if not config_path.exists():raise RuntimeError('Configure the dedicated upstream runtime first; see deploy/README.md')
        self.runtime=read(config_path)
        if self.runtime.get('backend')!='lima':raise ValueError('Unsupported upstream runtime; no implicit Docker Desktop fallback')

    def _vm(self,args,timeout=240):
        import os
        environment=os.environ.copy();environment['LIMA_HOME']=self.runtime['lima_home']
        return run([ROOT/'tools/lima/bin/limactl','shell',self.runtime['instance'],*args],timeout=timeout,env=environment)

    def command(self,args,timeout=240):
        import shlex
        project=self.runtime['project_dir']
        command='cd '+shlex.quote(project)+' && exec '+shlex.join([project+'/.venv/bin/nika',*map(str,args)])
        return self._vm(['sudo','-n','bash','-c',command],timeout)

    def probe(self):
        code=("import json,platform,subprocess; from pathlib import Path; "
              "print(json.dumps({'kernel':platform.release(),'architecture':platform.machine(),"
              "'vrf_module_loaded':Path('/sys/module/vrf').exists(),"
              "'docker_version':subprocess.check_output(['docker','version','--format','{{.Server.Version}}'],text=True).strip()}))")
        import json
        report=json.loads(self._vm(['sudo','-n','python3','-c',code],timeout=30)['stdout'])
        report['expected_source_commit']=self.runtime['source_commit']
        actual=self._vm(['git','-C',self.runtime['project_dir'],'rev-parse','HEAD'],timeout=20)['stdout'].strip()
        report['actual_source_commit']=actual
        if actual!=self.runtime['source_commit']:raise RuntimeError('Upstream source identity drift')
        if not report['vrf_module_loaded'] or not report['docker_version'].startswith('28.'):
            raise RuntimeError('Upstream kernel/Docker compatibility preflight failed: '+str(report))
        return report

    def deploy(self,scenario='dc_clos',size='s'):
        if self.session:raise RuntimeError('Clean up the owned session before deploying another')
        args=['env','run',scenario,'--result_dir',self.runtime['results_dir']]
        if size is not None:args+=['-s',size]
        out=self.command(args,timeout=600)
        match=re.search(r'session_id[=:\s]+([\w-]+)',out['stdout'])
        if not match:raise RuntimeError('No upstream session ID; inspect deployment evidence: '+str(out))
        self.session=match.group(1);self.last_deployment=(scenario,size)
        return out

    def inject(self,problem,params):
        if not self.session:raise RuntimeError('No owned upstream session')
        args=['failure','inject',problem,'--session_id',self.session]
        for key,value in params.items():args+=['--set',f'{key}={value}']
        return self.command(args)

    def inspect(self,device,command):
        if not self.session:raise RuntimeError('No owned upstream session')
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}',device):raise ValueError('Invalid scenario device')
        return self.command(['exec','--session_id',self.session,device,command])

    def restore(self):
        if self.last_deployment is None:raise RuntimeError('No deployment to restore')
        scenario,size=self.last_deployment
        self.cleanup()
        return self.deploy(scenario,size)

    def cleanup(self):
        if self.session:
            # Clear ownership only after the normal scoped upstream cleanup succeeds.
            result=self.command(['session','close','--session_id',self.session,'--yes'])
            self.session=None
            return result

class FaultBenchAdapter:
    """Own scoped copied lab, real injection/checks; never calls global pruning helpers.

    Trusted caller selects a pinned scenario. Agent access uses only separate public inputs.
    """
    def __init__(self,case_id):
        record=read(ROOT/'data/private/upstream-truth.json')[case_id]
        self.scenario=record['scenario']; self.name=self.scenario['topology']
        if self.name not in ('Kath1','Kath2','Kath3','Kath4','Kath5'):
            raise RuntimeError('This FaulT-Bench case uses a programmatic NIKA environment; use the pinned upstream Linux API')
        self.path=ROOT/'runtime/upstream-labs'/case_id.replace(':','_')
    def deploy(self):
        import shutil
        shutil.copytree(ROOT/'vendor/fault-bench/topology_kathara'/self.name,self.path,dirs_exist_ok=True)
        return run(['kathara','lstart','-d',self.path,'--noterminals','--no-hosthome','--no-shared'],timeout=240)
    def trusted_exec(self,device,command):
        if not re.fullmatch(r'[a-zA-Z0-9_-]+',device): raise ValueError('Invalid scenario device')
        import shlex
        wrapped='sh -c '+shlex.quote(command)
        return run(['kathara','exec','-d',self.path,'--wait',device,wrapped],timeout=60,check=False)
    def inject(self):
        inj=self.scenario['injection']
        return self.trusted_exec(inj['device'],inj['command']) if inj.get('command') else {'note':inj.get('note'),'applied':False}
    def inspect(self):
        return [{'check':c,'result':self.trusted_exec(c['device'],c['command'])} for c in self.scenario['post_inject_check']]
    def restore(self):
        self.cleanup(); return self.deploy()
    def cleanup(self):
        return run(['kathara','lclean','-d',self.path],timeout=180)
