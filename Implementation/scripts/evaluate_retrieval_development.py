"""Expanded developer-annotated retrieval evaluation; no private test answers."""
from statistics import mean
from neta.retrieval import retrieve
from neta.util import ROOT,write,now,digest

queries=[
 ('link-admin','How can ip link set dev eth0 up restore an administratively down interface?',['ip-link']),
 ('link-inspect','Inspect network interface flags and administrative link state with ip link show.',['ip-link']),
 ('link-down','What is the effect of ip link set dev eth1 down on a network device?',['ip-link']),
 ('link-device','How does the dev NAME argument identify an interface in ip link commands?',['ip-link']),
 ('route-default','How do I display the default IPv4 route and its gateway using ip route?',['ip-route']),
 ('route-replace','Restore a missing IPv4 prefix route using ip route replace PREFIX via GATEWAY.',['ip-route']),
 ('route-delete','What does ip route del PREFIX remove from the routing table?',['ip-route']),
 ('route-nexthop','Explain nexthop via address and dev interface in an ip route entry.',['ip-route']),
 ('frr-static','Configure a static IPv4 route in FRR using ip route NETWORK GATEWAY.',['frr-static']),
 ('frr-distance','How is administrative distance specified for an FRR static route?',['frr-static']),
 ('frr-blackhole','How can FRR configure a blackhole or Null0 static route?',['frr-static']),
 ('frr-multipath','How does FRR static routing support multiple next hops for the same destination?',['frr-static']),
 ('filter-forward','Which iptables FORWARD chain handles packets routed through the machine?',['iptables']),
 ('filter-drop','What is the DROP target in an iptables rule?',['iptables']),
 ('filter-flush','What does iptables --flush do to rules in the selected table or chain?',['iptables']),
 ('filter-policy','How do built-in INPUT OUTPUT and FORWARD chain policies work in iptables?',['iptables']),
 ('kernel-forward','What does the Linux net.ipv4.ip_forward sysctl control?',['kernel-ip-sysctl']),
 ('kernel-rpfilter','What is Linux IPv4 reverse path filtering rp_filter?',['kernel-ip-sysctl']),
 ('kernel-redirect','Explain accept_redirects in Linux IPv4 network sysctls.',['kernel-ip-sysctl']),
 ('kernel-proxyarp','What does proxy_arp configure for Linux IPv4 interfaces?',['kernel-ip-sysctl']),
]
rows=[]
for uid,query,relevant in queries:
    result=retrieve(query,snapshot='docs-v1',k=5)
    hits=result['passages'];sources=[h['source_id'] for h in hits]
    rr=next((1/(i+1) for i,s in enumerate(sources) if s in relevant),0)
    rows.append({'id':uid,'query':query,'relevant_document_ids':relevant,
                 'retrieved_passage_ids':[h['id'] for h in hits],'retrieved_document_ids':sources,
                 'top1_document_relevance':int(bool(sources) and sources[0] in relevant),
                 'reciprocal_rank':rr,'document_recall_at_5_passages':len(set(sources)&set(relevant))/len(relevant),
                 'snapshot_id':result['snapshot_id']})
report={'generated':now(),'split':'development','annotation_provenance':'Implementation-agent-authored document-level relevance; not independent expert or human review.',
        'protocol':'20 predefined queries, four per documentation source; immutable docs-v1; hybrid fusion, no LLM reranking in this retrieval-only check.',
        'limitations':['Document-level labels do not establish exact passage relevance.','Queries explicitly mention command names and do not represent broad natural-language tickets.','This evaluation does not establish independent expert relevance or test-set diagnostic performance.'],
        'queries_hash':digest(queries),'queries':len(rows),'top1_document_accuracy':mean(r['top1_document_relevance'] for r in rows),
        'mrr_at_5':mean(r['reciprocal_rank'] for r in rows),
        'mean_document_recall_at_5_passages':mean(r['document_recall_at_5_passages'] for r in rows),'records':rows}
write(ROOT/'results/retrieval-development-extended.json',report)
print({k:v for k,v in report.items() if k not in ('records',)})
