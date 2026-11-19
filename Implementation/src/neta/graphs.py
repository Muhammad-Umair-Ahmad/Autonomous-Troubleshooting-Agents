"""Temporal topology/dependency/symptom projection; history is never deleted."""
import ipaddress
from .util import digest

def graph(topology,observations,diagnosis):
    nodes=[];edges=[];address_owner={};symptoms={}
    for device,ifs in topology['interfaces'].items():
        nodes.append({'id':device,'type':'device'})
        for iface,address in ifs.items():
            iid=device+':'+iface;address_owner[address.split('/')[0]]=iid
            nodes.append({'id':iid,'type':'interface','intended_address':address})
            edges.append({'from':device,'to':iid,'kind':'contains'})
    for a,b in topology['links']:edges.append({'from':a,'to':b,'kind':'link'})
    for device,routes in topology['routes'].items():
        for prefix,gateway in routes.items():
            rid=device+':route:'+prefix
            nodes.append({'id':rid,'type':'route_dependency','prefix':prefix,'next_hop':gateway})
            edges.append({'from':device,'to':rid,'kind':'depends_on_route'})
            if gateway in address_owner:edges.append({'from':rid,'to':address_owner[gateway],'kind':'requires_gateway'})
    for o in observations:
        eid=o['evidence_id'];nodes.append({'id':eid,'type':'observation','timestamp':o['timestamp_utc'],'origin':o['origin'],'kind':o['kind']})
        edges.append({'from':o['device'],'to':eid,'kind':'observed_at'})
        descriptions=[]
        if o['raw']['returncode']!=0:descriptions.append('probe_or_tool_failure')
        if o['kind']=='interfaces' and o.get('parsed'):
            for interface in o['parsed']:
                if interface['ifname'] in topology['interfaces'][o['device']] and 'UP' not in interface['flags']:
                    descriptions.append('administratively_down:'+interface['ifname'])
        for description in descriptions:
            sid='symptom:'+eid+':'+description;symptoms.setdefault(eid,[]).append(sid)
            nodes.append({'id':sid,'type':'symptom','description':description,'timestamp':o['timestamp_utc'],'explanation_state':'unexplained'})
            edges.append({'from':eid,'to':sid,'kind':'measures'})
    for finding in (diagnosis or {}).get('findings',[]):
        fid='hypothesis:'+digest(finding['fault'])[:16]
        nodes.append({'id':fid,'type':'hypothesis','fault':finding['fault']})
        for evidence in finding['evidence_ids']:
            edges.append({'from':fid,'to':evidence,'kind':'evidence_link','verified_by_oracle':False})
            for sid in symptoms.get(evidence,[]):
                edges.append({'from':fid,'to':sid,'kind':'claims_explanation'})
                for node in nodes:
                    if node['id']==sid:node['explanation_state']='explained_by_diagnosis_claim'
    return {'nodes':nodes,'edges':edges,'history_preserved':True,'explanation_note':'Claims retain evidence history; evaluator confirmation is logged separately.'}
