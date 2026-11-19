"""Real scoped upstream lifecycle checks. Controller/oracle evidence, not agent scores."""
import base64
import json
import re
import subprocess
import sys
from datetime import datetime,timezone
from pathlib import Path

sid=sys.argv[1]
root=Path('/opt/neta-research/vendor/nika')
report={'session_id':sid,'kind':'oracle_controlled_upstream_lifecycle_validation_not_agent_evaluation',
        'started':datetime.now(timezone.utc).isoformat(),'records':[],'checks':{},
        'published_healthy_case':'nika:0.2.0:test.yaml:84','published_development_dns_case':'nika:0.2.0:dev.yaml:23',
        'additional_variant':'host_missing_ip on dc_clos small is an adapter check, not the published missing-IP row'}

def cli(*args):
    p=subprocess.run([str(root/'.venv/bin/nika'),*args],cwd=root,capture_output=True,text=True,timeout=180)
    record={'args':list(args),'returncode':p.returncode,'stdout':p.stdout,'stderr':p.stderr}
    report['records'].append(record)
    if p.returncode:raise RuntimeError(str(record))
    return p.stdout

def inspect(node,command):
    marked=command+'; printf "\\nNETA_EXIT=%s\\n" "$?"'
    out=cli('exec','--session_id',sid,'--timeout','30',node,marked)
    found=re.search(r'NETA_EXIT=(\d+)',out)
    if not found:raise RuntimeError('Container command exit marker missing')
    return {'output':out[:found.start()].strip(),'exit_code':int(found.group(1))}

def passed(node,command):
    result=inspect(node,command)
    if result['exit_code']!=0:raise RuntimeError(str(result))
    return result

from nika.workflows.session.containers import list_session_containers
_,lab_name,owned=list_session_containers(sid)
report['lab_name']=lab_name
report['owned_containers']=owned
resolv=None
fault_started=False
try:
    report['healthy_client_address']=passed('client_0','ip -4 -j addr show dev eth0')
    report['healthy_client_routes']=passed('client_0','ip -j route show')
    report['healthy_ping']=passed('client_0','ping -n -c 3 -W 1 10.0.1.2')
    report['healthy_reverse_ping']=passed('webserver0_pod0','ping -n -c 3 -W 1 192.168.0.2')
    report['healthy_dns']=passed('client_0','dig +time=1 +tries=1 +short web0.pod0')
    if '10.0.1.2' not in report['healthy_dns']['output']:raise RuntimeError('Unexpected DNS answer')
    report['healthy_http']=passed('client_0','curl -fsS --connect-timeout 2 --max-time 5 -o /dev/null -w "%{http_code}" http://web0.pod0/')
    if report['healthy_http']['output']!='200':raise RuntimeError('HTTP recovery criterion failed')
    report['bgp_summary']=passed('leaf_router_0_0',"vtysh -c 'show bgp summary'")
    report['checks']['healthy_services']=True
    fault_started=True
    cli('failure','inject','host_missing_ip','--session_id',sid,'--set','host_name=client_0','--set','intf_name=eth0')
    missing=passed('client_0','ip -4 -o addr show dev eth0 scope global')
    if 'inet ' in missing['output']:raise RuntimeError('Missing-IP injection not established')
    failed=inspect('client_0','ping -n -c 2 -W 1 10.0.1.2')
    if failed['exit_code']==0:raise RuntimeError('Missing-IP impact not observed')
    report['checks']['missing_ip_root_and_impact']=True
    passed('client_0','ip address replace 192.168.0.2/24 dev eth0')
    passed('client_0','ip route replace default via 192.168.0.1 dev eth0')
    passed('client_0','ping -n -c 3 -W 1 10.0.1.2')
    fault_started=False
    report['checks']['missing_ip_restoration']=True
    resolv=passed('client_0','cat /etc/resolv.conf')['output']+'\n'
    cli('failure','inject','host_incorrect_dns','--session_id',sid,'--set','host_name=client_0')
    changed=passed('client_0','cat /etc/resolv.conf')['output']+'\n'
    if changed==resolv:raise RuntimeError('DNS injection made no resolver change')
    dns=inspect('client_0','timeout 4 dig +time=1 +tries=1 +short web0.pod0')
    if dns['exit_code']==0 and '10.0.1.2' in dns['output']:raise RuntimeError('DNS impact not established')
    report['checks']['published_dns_root_and_impact']=True
    encoded=base64.b64encode(resolv.encode()).decode()
    passed('client_0',f'printf %s {encoded} | base64 -d > /etc/resolv.conf')
    restored=passed('client_0','dig +time=1 +tries=1 +short web0.pod0')
    if '10.0.1.2' not in restored['output']:raise RuntimeError('DNS recovery failed')
    report['checks']['published_dns_restoration']=True
    resolv=None
except BaseException as exc:
    report['error']=f'{type(exc).__name__}: {exc}'
finally:
    try:
        if fault_started:
            passed('client_0','ip address replace 192.168.0.2/24 dev eth0')
            passed('client_0','ip route replace default via 192.168.0.1 dev eth0')
        if resolv is not None:
            encoded=base64.b64encode(resolv.encode()).decode()
            passed('client_0',f'printf %s {encoded} | base64 -d > /etc/resolv.conf')
        cli('session','close','--session_id',sid,'--yes')
        remaining=[]
        for item in owned:
            p=subprocess.run(['docker','inspect',item['container_id']],capture_output=True,text=True,timeout=20)
            if p.returncode==0:remaining.append(item['container_id'])
        report['checks']['owned_cleanup']=not remaining
        report['remaining_owned_container_ids']=remaining
    except BaseException as exc:report['cleanup_error']=f'{type(exc).__name__}: {exc}'
    report['all_passed']=not report.get('error') and not report.get('cleanup_error') and all(report['checks'].values()) and len(report['checks'])==6
    report['finished']=datetime.now(timezone.utc).isoformat()
    Path('/tmp/neta-upstream-validation.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'all_passed':report['all_passed'],'checks':report['checks'],'error':report.get('error'),'cleanup_error':report.get('cleanup_error')}),flush=True)
raise SystemExit(0 if report['all_passed'] else 1)
