import unittest
from pydantic import ValidationError
from neta.contracts import ToolRequest,Diagnosis,Fault,Scan
from neta.broker import Budget,BudgetExceeded
from neta.metrics import score
from neta.remediation import policy
from neta.datasets import normalize,cases
from neta.util import ROOT,read
from neta.graphs import graph
from neta.lab import topology

class Contracts(unittest.TestCase):
    def test_shell_and_private_access_denied(self):
        for request in ({'device':'r1','kind':'shell','target':'cat data/private/local-truth.json'},
                        {'device':'r1; rm -rf /','kind':'routes'},
                        {'device':'r1','kind':'ping','target':'8.8.8.8'}):
            with self.assertRaises(ValidationError):ToolRequest.model_validate(request)
    def test_budget_before_tool(self):
        b=Budget(tools=1);b.tool({'kind':'routes'})
        with self.assertRaises(BudgetExceeded):b.tool({'kind':'addresses'})
    def test_circuit_breaker(self):
        b=Budget()
        for _ in range(3): b.tool({'same':True})
        with self.assertRaises(BudgetExceeded):b.tool({'same':True})
    def test_circuit_ablation_keeps_hard_cap(self):
        b=Budget(circuit=False,tools=4)
        for _ in range(4):b.tool({'same':True})
        with self.assertRaises(BudgetExceeded):b.tool({'same':True})
    def test_set_metrics_do_not_count_duplicate_predictions(self):
        f={'family':'link_down','device':'r1','target':'eth0'}
        other={'family':'link_down','device':'r2','target':'eth0'}
        s=score([f,f],[f,other]);self.assertEqual(s['precision'],1);self.assertEqual(s['recall'],.5)
        self.assertAlmostEqual(s['f1'],2/3)
    def test_healthy_false_alarm(self):
        f={'family':'link_down','device':'r1','target':'eth0'}
        self.assertEqual(score([],[])['exact_match'],1)
        self.assertEqual(score([f],[])['false_alarm'],1)
    def test_no_template_or_rewrite_split_leakage(self):
        group_splits={}; template_splits={}; truth=read(ROOT/'data/private/local-truth.json')
        for c in cases():
            group_splits.setdefault(c['incident_group'],set()).add(c['split'])
            for t in truth[c['case_id']]['fault_templates']:template_splits.setdefault(t,set()).add(c['split'])
        self.assertTrue(all(len(s)==1 for s in group_splits.values()))
        self.assertTrue(all(len(s)==1 for s in template_splits.values()))
    def test_normalization_preserves_identifiers_and_lies(self):
        self.assertEqual(normalize('  r2\n eth0 is definitely faulty 10.0.12.1/30 '),'r2 eth0 is definitely faulty 10.0.12.1/30')
    def test_unsafe_plan_is_blocked(self):
        plan={'actions':[{'op':'link_down','device':'pc1','target':'eth0'}],
              'preconditions':['x'],'expected_effects':['x'],'verification':['x'],'evidence_ids':['e']}
        finding={'fault':{'family':'link_down','device':'pc1','target':'eth0'},'evidence_ids':['e'],'explanation':'x'}
        self.assertFalse(policy(plan,{'findings':[finding]})['approved'])
    def test_history_not_deleted(self):
        obs={'evidence_id':'e1','timestamp_utc':'2000','device':'r1','kind':'routes','origin':'measured','raw':{'returncode':0,'stdout':'','stderr':''}}
        g=graph(topology(),[obs],{'findings':[]})
        self.assertTrue(any(n['id']=='e1' for n in g['nodes']))
    def test_typed_scan_has_root_definitions(self):
        schema=Scan.model_json_schema();self.assertIn('$defs',schema)
        self.assertIn('ToolRequest',schema['$defs'])
    def test_incomplete_or_unrestored_training_run_cannot_be_curated(self):
        import tempfile,json
        from pathlib import Path
        from neta.retrieval import curate
        for status,restored in [('interrupted',True),('completed',False)]:
            with self.subTest(status=status,restored=restored), tempfile.TemporaryDirectory() as d:
                p=Path(d)/'r.json'
                p.write_text(json.dumps({'split':'train','status':status,'final_restored':restored,
                    'metrics':{'exact_match':1},'repair':{'success':True,'twin_equivalent':True,'post_snapshot_matches_healthy':True}}))
                with self.assertRaises(ValueError):curate(p)

    def test_test_incident_cannot_be_curated(self):
        import tempfile,json
        from pathlib import Path
        from neta.retrieval import curate
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'r.json';p.write_text(json.dumps({'split':'test'}))
            with self.assertRaises(PermissionError):curate(p)

if __name__=='__main__':unittest.main()

class Statistics(unittest.TestCase):
    def test_single_group_does_not_invent_uncertainty(self):
        from neta.analysis import interval
        self.assertEqual(interval([.8]),[None,None])
    def test_holm_adjustment_is_monotone(self):
        from neta.analysis import holm
        self.assertEqual(holm([.01,.04,.03]),[.03,.06,.06])
    def test_token_and_wall_budgets(self):
        b=Budget(tokens=1);b.tokens=1
        with self.assertRaises(BudgetExceeded):b.check()
        b=Budget(seconds=0)
        with self.assertRaises(BudgetExceeded):b.check()
