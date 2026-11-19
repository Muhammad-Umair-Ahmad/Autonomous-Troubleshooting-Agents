"""Scoped real FaulT-Bench case validation; never launches upstream global cleanup."""
import json,re,subprocess,time
from Kathara.manager.Kathara import Kathara
from Kathara.parser.netkit.LabParser import LabParser
from func_timeout import func_timeout
from pathlib import Path
from datetime import datetime,timezone

base=Path('/opt/neta-research/vendor/nika/.venv/bin')
lab=Path('/tmp/neta-faultbench/Kath2')
report={'case_id':'faultbench:kath2-router1-r0-link-down',
        'kind':'oracle_controlled_published_case_validation_not_agent_evaluation',
        'started':datetime.now(timezone.utc).isoformat(),'records':[],'checks':{}}
owned=[];injected=False;kathara_lab=None;api=Kathara.get_instance()

def run(args,timeout=60,check=True):
    p=subprocess.run([str(a) for a in args],capture_output=True,text=True,timeout=timeout)
    result={'args':[str(a) for a in args],'returncode':p.returncode,'stdout':p.stdout,'stderr':p.stderr}
    report['records'].append(result)
    if check and p.returncode:raise RuntimeError(str(result))
    return result


def cmd(device,command):
    if device not in devices:raise PermissionError('Device outside scoped lab')
    out,err,code=func_timeout(45,lambda:api.exec(machine_name=device,command=['sh','-c',command],lab=kathara_lab,wait=(60,.5),stream=False))
    result={'device':device,'command':command,'returncode':code,'stdout':out.decode(errors='replace') if isinstance(out,bytes) else str(out or ''),'stderr':err.decode(errors='replace') if isinstance(err,bytes) else str(err or '')}
    report['records'].append(result)
    return result


def ping(device,target):
    result=cmd(device,f'ping -n -c 2 -W 1 {target}')
    match=re.search(r'(\d+(?:\.\d+)?)%\s+packet loss',result['stdout']+result['stderr'])
    return {'record':result,'loss_percent':float(match.group(1)) if match else None}


try:
    original=(lab/'lab.conf').read_text()
    devices=sorted(set(re.findall(r'^([A-Za-z0-9_]+)\[\d+\]',original,re.M)))
    images=dict(re.findall(r'^([A-Za-z0-9_]+)\[image\]\s*=\s*"([^"]+)"',original,re.M))
    identities={}
    for tag in sorted(set(images.values())|{'kathara/base'}):
        result=run(['docker','image','inspect',tag],check=False)
        if result['returncode']:
            run(['docker','pull',tag],timeout=300)
            result=run(['docker','image','inspect',tag])
        identities[tag]=json.loads(result['stdout'])[0]['Id']
    report['image_identities']=identities
    pinned=re.sub(r'^[A-Za-z0-9_]+\[image\].*\n','',original,flags=re.M)
    pinned+='\n'+'\n'.join(f'{d}[image]="{identities[images.get(d,"kathara/base")]}"' for d in devices)+'\n'
    (lab/'lab.conf').write_text(pinned)
    before=set(run(['docker','ps','-aq'])['stdout'].split())
    kathara_lab=LabParser().parse(str(lab))
    kathara_lab.name='neta_faultbench_kath2_validation'
    func_timeout(300,lambda:api.deploy_lab(kathara_lab))
    after=set(run(['docker','ps','-aq'])['stdout'].split());owned=sorted(after-before)
    report['owned_container_ids']=owned
    if len(owned)!=len(devices):raise RuntimeError('Owned container count mismatch')
    metadata=json.loads(run(['docker','inspect',*owned])['stdout'])
    labels={m['Config']['Labels'].get('lab_hash') for m in metadata}
    if len(labels)!=1 or any(m['Config']['Labels'].get('app')!='kathara' for m in metadata):
        raise RuntimeError('Ambiguous lab ownership')
    report['lab_hash']=next(iter(labels))
    for d in devices:
        result=cmd(d,'ip -brief address')
        if result['returncode']:raise RuntimeError('Startup inspection failed on '+d)
    # Allow routing startup, keeping all unsuccessful probes rather than discarding them.
    healthy=False
    for _ in range(20):
        a=ping('tpo','128.168.0.2');b=ping('it_hod','192.168.3.2')
        if a['loss_percent']==0 and b['loss_percent']==0:healthy=True;break
        time.sleep(2)
    if not healthy:raise RuntimeError('Published-case healthy paths never became zero-loss')
    before_link=cmd('router1','ip -j link show eth2')
    if 'UP' not in json.loads(before_link['stdout'])[0]['flags']:raise RuntimeError('Healthy target link not administratively UP')
    report['checks']['healthy_baseline']=True
    result=cmd('router1','ip link set eth2 down');injected=True
    if result['returncode']:raise RuntimeError('Injection command failed')
    link=cmd('router1','ip -j link show eth2')
    if 'UP' in json.loads(link['stdout'])[0]['flags']:raise RuntimeError('Injected link state not established')
    report['checks']['root_state']=True
    unaffected=ping('tpo','128.168.0.2');affected=ping('it_hod','192.168.3.2')
    if unaffected['loss_percent']!=0 or affected['loss_percent'] is None or affected['loss_percent']==0:
        raise RuntimeError('Published differential impact checks failed')
    report['checks']['published_impact_and_control']=True
    result=cmd('router1','ip link set eth2 up')
    if result['returncode']:raise RuntimeError('Reference restoration failed')
    injected=False
    recovered=False
    for _ in range(25):
        a=ping('tpo','128.168.0.2');b=ping('it_hod','192.168.3.2')
        if a['loss_percent']==0 and b['loss_percent']==0:recovered=True;break
        time.sleep(2)
    if not recovered:raise RuntimeError('Post-restoration paths did not recover')
    report['checks']['restoration']=True
except BaseException as exc:report['error']=f'{type(exc).__name__}: {exc}'
finally:
    try:
        if injected:cmd('router1','ip link set eth2 up')
        if kathara_lab is not None:func_timeout(180,lambda:api.undeploy_lab(lab=kathara_lab))
        remaining=[]
        for identity in owned:
            if run(['docker','inspect',identity],check=False)['returncode']==0:remaining.append(identity)
        report['checks']['owned_cleanup']=not remaining
    except BaseException as exc:report['cleanup_error']=f'{type(exc).__name__}: {exc}'
    report['all_passed']=not report.get('error') and not report.get('cleanup_error') and len(report['checks'])==5 and all(report['checks'].values())
    report['finished']=datetime.now(timezone.utc).isoformat()
    Path('/tmp/neta-faultbench-validation.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'all_passed':report['all_passed'],'checks':report['checks'],'error':report.get('error'),'cleanup_error':report.get('cleanup_error')}),flush=True)
raise SystemExit(0 if report['all_passed'] else 1)
