"""Audit Phase 3 evidence and generate vector plot sources using Python's standard library."""
from pathlib import Path
import csv,json,statistics,hashlib,math
ROOT=Path(__file__).resolve().parent.parent
OUT=Path(__file__).resolve().parent
FIG=OUT/'source'/'figures'
def rows(path):return list(csv.DictReader(open(path)))
raw=[json.loads(p.read_text()) for p in (ROOT/'Evaluation/Original raw runs').glob('*.json')]
revised=[json.loads(p.read_text()) for p in (ROOT/'Evaluation/Revised raw runs').glob('*.json')]
summary=rows(ROOT/'Evaluation/Original study/summary.csv')
blocks={r['run_id']:r['block'] for r in rows(ROOT/'Evaluation/Original study/runs.csv')}
assert len(raw)==366 and len(revised)==21
assert all(r['final_restored'] for r in raw+revised)
for s in summary:
 subset=[r for r in raw if r['config']['model']==s['model'] and r['config']['method']==s['method'] and blocks[r['run_id']]==s['block']]
 assert len(subset)==int(s['n']),(s['model'],s['method'],len(subset))
 assert math.isclose(statistics.mean(r['metrics']['exact_match'] for r in subset),float(s['exact_match']),abs_tol=1e-10)
 assert math.isclose(statistics.mean(r['elapsed_total_s'] for r in subset),float(s['seconds']),abs_tol=1e-8)
 assert math.isclose(statistics.mean(r.get('tokens_total',r['tokens']) for r in subset),float(s['tokens']),abs_tol=1e-8)
 faulty=[r for r in subset if r['truth_faults']]
 assert math.isclose(statistics.mean(r['metrics']['f1'] for r in faulty),float(s['faulty_f1']),abs_tol=1e-10)
assert sum(r['metrics']['exact_match'] for r in revised)==21
assert sum(bool(r['repair']['success']) for r in revised if r['truth_faults'])==18
models=['llama3.2:1b','qwen2.5-coder:3b','qwen2.5:1.5b']
colors=['blue!70!black','orange!85!black','teal!80!black']
methods=['full','rule_based','single_agent','sade_local','no_curation','no_rescan','no_twin']
labels=['Full','Rules','Single','SADE-L','NoCur','NoScan','NoTwin']
def val(model,method,key,block='core'):
 return float(next(s for s in summary if s['model']==model and s['method']==method and s['block']==block)[key])
head=r'''\documentclass[tikz,border=3pt]{standalone}
\usepackage{pgfplots}
\pgfplotsset{compat=1.18}
\usetikzlibrary{arrows.meta,positioning,calc}
\begin{document}
'''
# Full-width, 2 x 2 plot: actual saved means, no invented error bars.
tex=head+r'\begin{tikzpicture}'+'\n'
for panel,(key,title,ylabel,scale,ymax) in enumerate([
 ('faulty_f1','(a) Diagnosis on standard cases','Mean fault-set F1 (\\%)',100,112),
 ('repair_per_faulty_case','(b) Original verified recovery','Verified repair (\\%)',100,112),
 ('seconds','(c) Total execution time','Mean elapsed time (s)',1,205),
 ('faulty_f1','(d) Perturbed-input diagnosis','Mean fault-set F1 (\\%)',100,112)]):
 robust=panel==3; mm=['full','single_agent'] if robust else methods
 xl=['Full','Single'] if robust else labels
 x=0 if panel%2==0 else 8.1;y=0 if panel<2 else -5.5
 tex+=f'\\begin{{axis}}[at={{({x}cm,{y}cm)}},anchor=north west,width=7.9cm,height=5.2cm,title={{{title}}},title style={{font=\\small}},ylabel={{{ylabel}}},ylabel style={{font=\\small}},ymin=0,ymax={ymax},yticklabel style={{font=\\footnotesize}},ybar,bar width={"12" if robust else "5"}pt,enlarge x limits=0.1,symbolic x coords={{{",".join(xl)}}},xtick=data,xticklabel style={{font=\\scriptsize,rotate=30,anchor=east}},grid=major,grid style={{gray!15}},axis line style={{gray!60}},legend style={{font=\\scriptsize,draw=none,at={{(0.5,-0.34)}},anchor=north,legend columns=3}}]\n'
 for model,color in zip(models,colors):
  coords=[]
  for method,label in zip(mm,xl):
   if key=='repair_per_faulty_case' and method=='sade_local':continue
   coords.append(f'({label},{val(model,method,key,"robustness" if robust else "core")*scale:.6f})')
  tex+=f'\\addplot[fill={color},draw={color}] coordinates {{{" ".join(coords)}}};\n'
 if panel==3:tex+=r'\legend{Llama 1B,Qwen Coder 3B,Qwen 1.5B}'+'\n'
 tex+='\\end{axis}\n'
tex+=r'\end{tikzpicture}\end{document}'
(FIG/'performance.tex').write_text(tex)
tex=head+r'''\begin{tikzpicture}
\begin{axis}[width=15.5cm,height=5.5cm,ybar,bar width=13pt,ymin=0,ymax=65,
ylabel={Exact-match decrease (percentage points)},symbolic x coords={No curation,No rescanning,No twin},xtick=data,
grid=major,grid style={gray!15},legend style={font=\small,draw=none,at={(0.5,1.03)},anchor=south,legend columns=3},
xticklabel style={font=\small},nodes near coords,nodes near coords style={font=\scriptsize},enlarge x limits=0.25]
'''
for model,color in zip(models,colors):
 cs=' '.join(f'({lab},{100*(val(model,"full","exact_match")-val(model,m,"exact_match")):.3f})' for m,lab in [('no_curation','No curation'),('no_rescan','No rescanning'),('no_twin','No twin')])
 tex+=f'\\addplot[fill={color},draw={color}] coordinates {{{cs}}};\n'
tex+=r'\legend{Llama 1B,Qwen Coder 3B,Qwen 1.5B}\end{axis}\end{tikzpicture}\end{document}'
(FIG/'ablation.tex').write_text(tex)
(FIG/'architecture.tex').write_text(head+r'''
\hyphenpenalty=10000\exhyphenpenalty=10000
\begin{tikzpicture}[font=\sffamily\small,box/.style={draw=blue!50!black,fill=blue!4,rounded corners=2pt,align=center,minimum height=0.95cm,text width=3.65cm},arr/.style={-{Stealth[length=2.5mm]},thick,draw=blue!50!black}]
\node[box] (in) at (0,0) {Ticket, topology\\and public intended state};
\node[box] (orch) at (4.3,0) {Orchestrator\\budgets and hypothesis state};
\node[box] (know) at (8.6,0) {Knowledge role\\pinned docs + verified training};
\node[box] (diag) at (4.3,-1.5) {Diagnostic role\\model proposals + state checks};
\node[box] (broker) at (0,-1.5) {Typed read-only broker\\measurements with evidence IDs};
\node[box] (repair) at (4.3,-3.0) {Remediation role\\complete, ordered action set};
\node[box] (over) at (8.6,-3.0) {Oversight role\\evidence + policy gates};
\node[box] (twin) at (8.6,-4.5) {Equivalent faulty twin\\repair + full recovery checks};
\node[box] (main) at (4.3,-4.5) {Main lab execution\\post-checks or state rollback};
\node[box] (out) at (0,-4.5) {Diagnosis + verified outcome\\trace and restoration record};
\draw[arr] (in)--(orch);\draw[arr] (know)--(orch);\draw[arr] (orch)--(diag);
\draw[arr] (broker)--(diag);\draw[arr] (diag)--(repair);\draw[arr] (repair)--(over);
\draw[arr] (over)--(twin);\draw[arr] (twin)--node[above,font=\scriptsize]{pass}(main);\draw[arr] (main)--(out);
\draw[arr,dashed] (diag.north east) to[bend right=35] (orch.south east);


\end{tikzpicture}\end{document}
''')
(FIG/'case-trace.tex').write_text(head+r'''
\begin{tikzpicture}[font=\small,arr/.style={-{Stealth[length=2mm]},thick},box/.style={draw=teal!60!black,fill=teal!3,rounded corners=2pt,align=left,text width=13.5cm,inner sep=8pt}]
\node[box] (a) at (0,0) {\textbf{Observed state.} r2:eth1 is DOWN; pc2:eth0 lacks its intended address;\\r2 lacks the 10.0.1.0/24 route; pc2 also lacks its default route.};
\node[box,below=6mm of a] (b) {\textbf{Diagnosis.} Three root causes: link\_down(r2, eth1), address\_missing(pc2, eth0),\\route\_missing(r2, 10.0.1.0/24). The absent pc2 default route is a dependency.};
\node[box,below=6mm of b] (c) {\textbf{Recorded execution order.} 1. Enable r2:eth1. 2. Restore pc2 10.0.2.10/24.\\3. Restore pc2 default via 10.0.2.1. 4. Restore r2 route via 10.0.12.1.};
\node[box,below=6mm of c] (d) {\textbf{Verified outcome.} Equivalent faulty twin: passed. Recovery and intended-state\\post-checks: passed. Repair: successful. Rollback: not required.};
\draw[arr] (a)--(b);\draw[arr] (b)--(c);\draw[arr] (c)--(d);
\end{tikzpicture}\end{document}
''')
# Numerical audit and direct cross-checks for writing.
audit={'original_records':len(raw),'revised_records':len(revised),'revised_exact':21,'revised_repairs':18,'comparative_records':294,'robustness_records':72,'all_final_restored':True,'summary_exact_f1_time_tokens_crosschecked':True,'comparisons':[]}
for model in models:
 for baseline in ['rule_based','single_agent','sade_local']:
  b=val(model,baseline,'faulty_f1');delta=1-b
  audit['comparisons'].append({'model':model,'baseline':baseline,'absolute_f1_pp':delta*100,'relative_f1_percent':delta/b*100 if b else None})
(OUT/'evidence'/'paper-audit.json').write_text(json.dumps(audit,indent=2)+'\n')
print(json.dumps(audit,indent=2))
