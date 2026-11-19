"""Evaluator-only overlap audit; candidate risks are not declared semantic identity."""
from collections import Counter,defaultdict
from neta.util import ROOT,read,write,digest,now

catalog=read(ROOT/'data/public/upstream-catalog.json')
truth=read(ROOT/'data/private/upstream-truth.json')
local=read(ROOT/'data/public/local-cases.json')
if isinstance(local,dict):local=local['cases']
by_source=Counter(c['source'] for c in catalog)
nonempty=defaultdict(list)
for c in catalog:
    ticket=' '.join(c.get('ticket','').split()).lower()
    if ticket:nonempty[ticket].append(c)
text_duplicates=[{'case_ids':[c['case_id'] for c in values],'sources':sorted({c['source'] for c in values})}
                 for values in nonempty.values() if len({c['source'] for c in values})>1]
groups=defaultdict(list)
for c in catalog:groups[(c['source'],c['incident_group'])].append(c)
split_flags=[{'source':s,'incident_group':g,'splits':sorted({c['split'] for c in values}),
              'case_ids':[c['case_id'] for c in values]} for (s,g),values in groups.items() if len({c['split'] for c in values})>1]
# Explicit conservative family correspondence. Family membership is not graph/state equality.
family={'dc_clos_bgp':'clos_family','dc_clos':'clos_family','sdn_l3_clos':'clos_family','min3clos':'clos_family',
        'ospf_enterprise_static':'enterprise_family','enterprise_branch':'enterprise_family'}
potential=[]
for f in sorted(set(family.values())):
    members=[c for c in catalog if family.get(c['topology_structure'])==f]
    if len({c['source'] for c in members})>1:
        potential.append({'family':f,'source_case_counts':dict(Counter(c['source'] for c in members)),
                          'topology_names':sorted({c['topology_structure'] for c in members}),
                          'decision':'potential related topology family; do not pool or assume independent incidents',
                          'case_ids':[c['case_id'] for c in members]})
# Verify that the current accepted knowledge contains only local training incidents.
accepted=read(ROOT/'knowledge/accepted-incidents.json')
knowledge_sources=[]
for entry in accepted:
    run=read(entry['source_url'])
    knowledge_sources.append({'run_id':run['run_id'],'source':run['source'],'split':run['split'],
                              'source_hash_matches':digest(run)==entry['source_hash']})
assert all(r['source']=='local' and r['split']=='train' and r['source_hash_matches'] for r in knowledge_sources)
report={'generated':now(),'status':'completed_conservative_catalog_audit_semantic_identity_unresolved',
        'source_counts':dict(by_source),'input_catalog_hash':digest(catalog),'private_definition_hash':digest(truth),
        'nonempty_exact_cross_source_ticket_duplicates':text_duplicates,
        'missing_or_empty_ticket_counts':dict(Counter(c['source'] for c in catalog if not c.get('ticket','').strip())),
        'within_source_group_split_conflicts':split_flags,'potential_cross_source_family_overlap':potential,
        'current_knowledge_sources':knowledge_sources,
        'verified_current_upstream_training_knowledge_leakage':False,
        'policy':['Keep all published source evaluations separate; no pooled independent-incident claim.',
                  'Do not curate published incidents or tune on their answers until canonical graph/state correspondence and splits are validated.',
                  'Preserve official NIKA splits and explicitly flag any conflicts rather than moving official cases silently.',
                  'Downloaded catalogues do not establish real deployment or compatible agent coverage.'],
        'limitations':['Exact text matching cannot establish semantic non-overlap.',
                       'Clos/enterprise aliases are conservative families, not proof of identical graphs or injections.',
                       'FaulT-Bench programmatic environments import the legacy nika.net_env API from the pinned SADE tree; compatibility with current NIKA 1.0 cannot be assumed.',
                       'NIKA release definitions have no public ticket in this catalogue when the release supplies only scenario/injection/root-cause records; do not expose those private labels as tickets.'],
        'evidence_files':['vendor/fault-bench/faultbench/src/faultbench/lab.py',
                          'vendor/SADE-NetworkAgent/src/nika/net_env/net_env_pool.py',
                          'vendor/nika/benchmark/releases/0.2.0/dev.yaml','vendor/nika/benchmark/releases/0.2.0/test.yaml']}
write(ROOT/'results/source-overlap-audit.json',report)
print({k:report[k] for k in ('status','source_counts','missing_or_empty_ticket_counts','verified_current_upstream_training_knowledge_leakage')})
