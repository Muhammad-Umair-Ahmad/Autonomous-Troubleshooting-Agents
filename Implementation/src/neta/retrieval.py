"""Reproducible BM25 + cached local dense retrieval and local LLM reranking."""
import math
import re
from collections import Counter
from html.parser import HTMLParser
import requests
from .util import ROOT, digest, read, write, now

DOCS={
 'kernel-ip-sysctl':('https://www.kernel.org/doc/html/latest/networking/ip-sysctl.html','Linux latest; retrieved bytes pinned'),
 'frr-static':('https://docs.frrouting.org/en/stable-10.2/static.html','FRR 10.2'),
 'ip-link':('https://man7.org/linux/man-pages/man8/ip-link.8.html','iproute2 manual; retrieved bytes pinned'),
 'ip-route':('https://man7.org/linux/man-pages/man8/ip-route.8.html','iproute2 manual; retrieved bytes pinned'),
 'iptables':('https://man7.org/linux/man-pages/man8/iptables.8.html','iptables manual; retrieved bytes pinned'),
}

class TextHTML(HTMLParser):
    def __init__(self): super().__init__(); self.parts=[]; self.skip=0
    def handle_starttag(self,tag,attrs):
        if tag in ('script','style'): self.skip+=1
    def handle_endtag(self,tag):
        if tag in ('script','style'): self.skip=max(0,self.skip-1)
    def handle_data(self,data):
        if not self.skip: self.parts.append(data)

def tokenize(text): return re.findall(r'[a-z0-9_.:/-]+',text.lower())

class Ollama:
    def __init__(self,model='qwen2.5:1.5b',seed=0,temperature=0.2,max_output=512,context=8192):
        self.model=model; self.seed=seed; self.temperature=temperature; self.max_output=max_output; self.context=context
        self.tokens=0; self.calls=[]; self.base='http://127.0.0.1:11434'
    def chat(self,system,user,schema=None,timeout=90):
        import time
        start=time.monotonic()
        payload={'model':self.model,'stream':False,'keep_alive':'2m','messages':[{'role':'system','content':system},{'role':'user','content':user}],
                 'options':{'temperature':self.temperature,'seed':self.seed,'num_ctx':self.context,'num_predict':self.max_output}}
        if schema: payload['format']=schema
        else: payload['format']='json'
        r=requests.post(self.base+'/api/chat',json=payload,timeout=timeout); r.raise_for_status(); body=r.json()
        used=body.get('prompt_eval_count',0)+body.get('eval_count',0)
        self.tokens+=used
        self.calls.append({'model':self.model,'seed_requested':self.seed,'seed_guarantee':'Ollama accepts seed option; determinism empirically audited, not assumed',
                           'input_tokens':body.get('prompt_eval_count'), 'output_tokens':body.get('eval_count'),
                           'duration_ns':body.get('total_duration'),'elapsed_s':time.monotonic()-start,
                           'prompt_sha256':digest([system,user]),'response':body['message']['content']})
        import json
        return json.loads(body['message']['content'])
    def identity(self):
        r=requests.get(self.base+'/api/tags',timeout=10); r.raise_for_status()
        return next(x for x in r.json()['models'] if x['name']==self.model)


def ingest():
    chunks=[]
    for sid,(url,version) in DOCS.items():
        raw=requests.get(url,timeout=60); raw.raise_for_status()
        dest=ROOT/'knowledge/raw'/f'{sid}.html'; dest.parent.mkdir(parents=True,exist_ok=True); dest.write_bytes(raw.content)
        parser=TextHTML(); parser.feed(raw.text)
        text=' '.join(' '.join(parser.parts).split())
        # Overlapping word windows preserve nearby command context.
        words=text.split()
        for offset in range(0,len(words),180):
            passage=' '.join(words[offset:offset+240])
            if len(passage)<80: continue
            chunks.append({'id':f'{sid}:{offset}','source_id':sid,'source_url':url,'version':version,'retrieved_utc':now(),
                           'source_hash':digest(raw.content),'text':passage,'content_hash':digest(passage),'kind':'documentation'})
    write(ROOT/'knowledge/documentation.json',chunks)
    return len(chunks)


def embed(text, model='all-minilm:latest'):
    identity=requests.get('http://127.0.0.1:11434/api/tags',timeout=10).json()
    model_id=next(m['digest'] for m in identity['models'] if m['name']==model)
    key=digest([text,model_id]); path=ROOT/'.cache/embeddings'/f'{key}.json'
    if path.exists(): return read(path)
    r=requests.post('http://127.0.0.1:11434/api/embed',json={'model':model,'input':text,'keep_alive':'2m'},timeout=60)
    r.raise_for_status(); vector=r.json()['embeddings'][0]; write(path,vector)
    return vector


def build(name,curated=False):
    path=ROOT/'knowledge/snapshots'/f'{name}.json'
    if path.exists(): return read(path) # immutable snapshots
    docs=read(ROOT/'knowledge/documentation.json')
    incidents=read(ROOT/'knowledge/accepted-incidents.json') if curated and (ROOT/'knowledge/accepted-incidents.json').exists() else []
    chunks=docs+incidents
    vectors=[embed(c['text']) for c in chunks]
    artifact={'name':name,'created':now(),'chunks':chunks,'vectors':vectors,'embedding_model':'all-minilm:latest',
              'embedding_digest':next(m['digest'] for m in requests.get('http://127.0.0.1:11434/api/tags').json()['models'] if m['name']=='all-minilm:latest'),
              'curated':curated,'content_hash':digest(chunks),'bm25':{'k1':1.5,'b':0.75},'fusion':'RRF(k=60)','reranker':'local backbone relevance ordering'}
    artifact['snapshot_id']=digest(artifact)
    write(path,artifact)
    return artifact


def retrieve(query,snapshot='docs-v1',k=4,model=None):
    index=read(ROOT/'knowledge/snapshots'/f'{snapshot}.json')
    if digest({key:value for key,value in index.items() if key!='snapshot_id'})!=index['snapshot_id']: raise RuntimeError('Knowledge snapshot content hash mismatch')
    tags=requests.get('http://127.0.0.1:11434/api/tags',timeout=10).json()['models']
    if next(m['digest'] for m in tags if m['name']==index['embedding_model'])!=index['embedding_digest']: raise RuntimeError('Embedding model freeze drift')
    chunks=index['chunks']
    terms=[Counter(tokenize(c['text'])) for c in chunks]; n=len(terms); avg=sum(sum(x.values()) for x in terms)/max(n,1)
    df=Counter(t for row in terms for t in row)
    bm=[]
    for row in terms:
        length=sum(row.values()); total=0
        for term in tokenize(query):
            freq=row[term]
            total+=math.log(1+(n-df[term]+0.5)/(df[term]+0.5)) * freq*2.5/(freq+1.5*(.25+.75*length/max(avg,1))) if freq else 0
        bm.append(total)
    vector=embed(query)
    cosine=lambda a,b:sum(x*y for x,y in zip(a,b))/(math.sqrt(sum(x*x for x in a)*sum(y*y for y in b)) or 1)
    dense=[cosine(vector,v) for v in index['vectors']]
    fusion=Counter()
    for scores in (bm,dense):
        for rank,i in enumerate(sorted(range(n),key=lambda i:scores[i],reverse=True)[:20]): fusion[i]+=1/(61+rank)
    candidates=[dict(chunks[i],fusion_score=fusion[i]) for i,_ in fusion.most_common(max(k,6))]
    if model and candidates:
        import json
        schema={'type':'object','properties':{'ids':{'type':'array','items':{'type':'string'}}},'required':['ids']}
        response=model.chat('Rank these passages by usefulness for the query. Return JSON ids in descending relevance; never invent IDs.',
                            json.dumps({'query':query,'passages':[{'id':c['id'],'text':c['text']} for c in candidates]}),schema)
        ordered={x:i for i,x in enumerate(response.get('ids',[]))}
        candidates.sort(key=lambda c:ordered.get(c['id'],999))
    return {'snapshot_id':index['snapshot_id'],'query':query,'passages':candidates[:k]}


def curate(run_path):
    """Deterministic acceptance gates; no LLM verdict is treated as ground truth."""
    record=read(run_path)
    if record['split']!='train': raise PermissionError('Only training incidents can be curated')
    if record.get('status')!='completed' or record.get('final_restored') is not True:
        raise ValueError('Need a completed run with verified final lab restoration')
    if record.get('metrics',{}).get('exact_match')!=1: raise ValueError('Diagnosis not independently verified')
    repair=record.get('repair',{})
    if not repair.get('success') or not repair.get('post_snapshot_matches_healthy') or not repair.get('twin_equivalent'):
        raise ValueError('Need verified twin, post-repair recovery and absence of regression')
    findings=record.get('diagnosis',{}).get('findings',[])
    measured={o['evidence_id'] for o in record.get('observations',[])}
    if any(not set(f['evidence_ids'])<=measured for f in findings): raise ValueError('Unmeasured evidence reference')
    text='Verified training incident. '+record['ticket']+'\n'+str(findings)+'\nRepair: '+str(repair.get('plan'))
    entry={'id':'incident:'+record['incident_id'],'source_id':record['run_id'],'source_url':str(run_path),
           'version':'verified-v1','retrieved_utc':now(),'content_hash':digest(text),'source_hash':digest(record),
           'kind':'verified_training_incident','text':text,'incident_group':record['incident_group'],
           'acceptance':['training_only','exact_fault_set','evidence_links','twin_fidelity','recovery','regression_checks']}
    path=ROOT/'knowledge/accepted-incidents.json'; entries=read(path) if path.exists() else []
    if not any(e['incident_group']==entry['incident_group'] for e in entries): entries.append(entry)
    write(path,entries)
    return entry


def evaluate():
    queries=[{'id':'dev-interface','query':'An interface is administratively down. Which command enables the link?','relevant':['ip-link']},
             {'id':'dev-route','query':'IPv4 remote subnet route missing static route next hop','relevant':['ip-route','frr-static']},
             {'id':'dev-filter','query':'Forwarded packets blocked by iptables DROP FORWARD rule','relevant':['iptables']},
             {'id':'dev-forward','query':'Enable IPv4 forwarding ip_forward sysctl','relevant':['kernel-ip-sysctl']}]
    records=[]
    for q in queries:
        hits=retrieve(q['query'],k=5)['passages']; ids=[h['source_id'] for h in hits]
        relevant=set(q['relevant']); found=set(ids)&relevant
        rr=next((1/(i+1) for i,x in enumerate(ids) if x in relevant),0)
        records.append({**q,'retrieved':ids,'recall_at_5':len(found)/len(relevant),'reciprocal_rank':rr,
                        'precision_at_5':sum(i in relevant for i in ids)/5})
    report={'annotation':'developer-authored document-level relevance on development-only queries; not independent expert annotation',
            'records':records,'mean_recall_at_5':sum(r['recall_at_5'] for r in records)/len(records),
            'mrr':sum(r['reciprocal_rank'] for r in records)/len(records)}
    write(ROOT/'results/retrieval-evaluation.json',report); return report
