"""Software-only mocked RPC contract test, not network experiment evidence."""
import importlib.util
import io
import json
import unittest
from pathlib import Path
from unittest.mock import patch
from neta.lab import topology
from neta.contracts import Diagnosis,RepairPlan,Review,Scan
from neta.util import ROOT

class AblationContract(unittest.TestCase):
    def run_worker(self,method,compound=False,healthy=False,missing_routes=False,failed_firewall=False,missing_all=False,fail_remediation=False,address_missing=False,link_route_lost=False,improved=False,revision="repair-v2"):
        library=(ROOT/'src/neta/agent/sade-books.json').read_text()
        original_open=open
        def safe_open(path,*args,**kwargs):
            if str(path)=='/agent/sade-books.json':return io.StringIO(library)
            return original_open(path,*args,**kwargs)
        spec=importlib.util.spec_from_file_location('agent_under_test',ROOT/'src/neta/agent/worker.py')
        worker=importlib.util.module_from_spec(spec)
        with patch('builtins.open',safe_open):spec.loader.exec_module(worker)
        calls=[];roles=[];finished=[];t=topology();self.worker_calls=calls
        fault={'family':'link_down','device':'r1','target':'eth0'}
        diagnosis={'healthy':False,'findings':[{'fault':fault,'evidence_ids':['r1-interfaces'],'explanation':'software fixture measured down'}],'unresolved':[],'summary':'fixture'}
        def rpc(op,**params):
            calls.append((op,params))
            if op=='inspect':
                req=params['request'];d=req['device'];kind=req['kind'];parsed=None
                if kind=='interfaces':parsed=[{'ifname':i,'flags':[] if not healthy and ((d=='r1' and i=='eth0') or (compound and d=='r2' and i=='eth1')) else ['UP']} for i in t['interfaces'][d]]
                elif kind=='addresses':parsed=[{'ifname':i,'addr_info':[{'family':'inet','local':a.split('/')[0],'prefixlen':int(a.split('/')[1])}]} for i,a in t['interfaces'][d].items()]
                elif kind=='routes':parsed=[{'dst':k,'gateway':v} for k,v in t['routes'][d].items()]
                if link_route_lost and d=='r1' and kind=='interfaces':parsed=[{'ifname':i,'flags':[] if i=='eth1' else ['UP']} for i in t['interfaces'][d]]
                if link_route_lost and d=='r1' and kind=='routes':parsed=[]
                if address_missing and d=='pc1' and kind=='addresses':parsed=[{'ifname':'eth0','addr_info':[]}]
                if address_missing and d=='pc1' and kind=='routes':parsed=[]
                unavailable=missing_all or (missing_routes and d=='r2' and kind=='routes') or (failed_firewall and d=='r2' and kind=='firewall')
                if unavailable:parsed=None
                return {'device':d,'kind':kind,'evidence_id':d+'-'+kind,'timestamp_utc':'fixture','origin':'measured','parsed':parsed,'raw':{'returncode':1 if unavailable or (kind=='ping' and not healthy) else 0,'stdout':'','stderr':''}}
            if op=='retrieve':return {'snapshot_id':'software-fixture','passages':[]}
            if op=='diagnosis_ready':return {'recorded':True}
            if op=='progress':return {'stop':True}
            if op=='model':
                roles.append(params['role']);props=params['schema']['properties']
                if fail_remediation and params['role']=='Remediation':raise RuntimeError('controlled late repair-format failure')
                if 'checks' in props:return {'checks':[]}
                if 'findings' in props:return diagnosis
                if 'actions' in props:return {'actions':[{'op':'link_up','device':'r1','target':'eth0','value':''}], 'preconditions':['owned_isolated_research_lab'],'expected_effects':['all_six_probe_paths_recover'],'verification':['six_probe_paths_zero_loss'],'rollback':'restore_captured_state','evidence_ids':['r1-interfaces']}
                return {'approved':True,'reason':'software fixture','evidence_ids':['r1-interfaces']}
            if op=='finish':finished.append(params['result']);return {'accepted':True}
            raise AssertionError(op)
        worker.rpc=rpc
        job={'config':{'method':method,'repair':True,**({'revision':revision} if improved else {})},'case':{'ticket':'fixture','topology':t},'schemas':{'scan':Scan.model_json_schema(),'diagnosis':Diagnosis.model_json_schema(),'repair':RepairPlan.model_json_schema(),'review':Review.model_json_schema()}}
        with patch('sys.stdin',io.StringIO(json.dumps(job)+'\n')):worker.main()
        return [p['request'] for op,p in calls if op=='inspect'],roles,finished[0]

    def test_improved_requires_complete_distinct_action_set(self):
        _,roles,result=self.run_worker('full',compound=True,improved=True)
        self.assertFalse(result['review']['approved'])
        self.assertIn('Incomplete',result['review']['reason'])
        self.assertNotIn('Oversight',roles)
        task=next(p for op,p in self.worker_calls if op=='model' and p['role']=='Remediation')
        actions=task['schema']['properties']['actions']
        self.assertEqual(actions['minItems'],2)
        self.assertEqual(actions['maxItems'],2)
        self.assertTrue(actions['uniqueItems'])

    def test_improved_retries_missing_measurements_and_preserves_uncertainty(self):
        checks,_,result=self.run_worker('full',missing_routes=True,improved=True)
        self.assertEqual(sum(r['device']=='r2' and r['kind']=='routes' for r in checks),2)
        self.assertTrue(result['diagnosis']['unresolved'])

    def test_improved_keeps_independent_oversight(self):
        _,roles,result=self.run_worker('full',improved=True)
        self.assertIn('Oversight',roles)
        self.assertTrue(result['review']['approved'])
        task=next(p['task'] for op,p in self.worker_calls if op=='model' and p['role']=='Oversight')
        self.assertEqual(task['required_restorative_actions'],result['plan']['actions'])

    def test_v3_keeps_model_advice_and_requires_complete_evidence(self):
        _,roles,result=self.run_worker('full',improved=True,revision='repair-v3')
        self.assertIn('Oversight',roles)
        self.assertIn('advisory_review',result)
        self.assertTrue(result['review']['approved'])
        self.assertTrue(result['review']['evidence_ids'])
        _,_,uncertain=self.run_worker('full',missing_routes=True,improved=True,revision='repair-v3')
        self.assertFalse(uncertain['review']['approved'])

    def test_single_role_preserves_information_and_safety_stages(self):
        full,roles,a=self.run_worker('full')
        single,single_roles,b=self.run_worker('single_role')
        self.assertEqual(full,single)
        self.assertEqual(len(roles),len(single_roles))
        self.assertTrue({'Diagnostic','Remediation','Oversight'}<=set(roles))
        self.assertEqual(set(single_roles),{'Orchestrator'})
        self.assertEqual(a['plan'],b['plan']);self.assertEqual(a['review'],b['review'])

    def test_no_rescan_keeps_all_initially_measured_faults(self):
        _,_,full=self.run_worker('full',compound=True)
        _,_,ablated=self.run_worker('no_rescan',compound=True)
        self.assertEqual(len(full['diagnosis']['findings']),2)
        self.assertEqual(ablated['diagnosis']['findings'],full['diagnosis']['findings'])

    def test_unavailable_route_measurement_does_not_invent_a_missing_route(self):
        _,_,result=self.run_worker('full',missing_routes=True)
        faults=[f['fault'] for f in result['diagnosis']['findings']]
        self.assertEqual(faults,[{'family':'link_down','device':'r1','target':'eth0'}])
        self.assertTrue(any('r2/routes' in message for message in result['diagnosis']['unresolved']))

    def test_unavailable_firewall_measurement_prevents_healthy_claim(self):
        _,_,result=self.run_worker('full',healthy=True,failed_firewall=True)
        self.assertFalse(result['diagnosis']['healthy'])
        self.assertEqual(result['diagnosis']['findings'],[])
        self.assertTrue(any('r2/firewall' in message for message in result['diagnosis']['unresolved']))

    def test_all_unavailable_measurements_remain_uncertain_and_schema_bounded(self):
        _,_,result=self.run_worker('full',missing_all=True)
        diagnosis=Diagnosis.model_validate(result['diagnosis'])
        self.assertFalse(diagnosis.healthy)
        self.assertEqual(diagnosis.findings,[])
        self.assertTrue(diagnosis.unresolved)
        self.assertLessEqual(len(diagnosis.unresolved),6)

    def test_diagnosis_is_checkpointed_before_late_remediation_failure(self):
        with self.assertRaisesRegex(RuntimeError,'late repair-format failure'):
            self.run_worker('full',fail_remediation=True)
        checkpoints=[p['diagnosis'] for op,p in self.worker_calls if op=='diagnosis_ready']
        self.assertEqual(len(checkpoints),1)
        self.assertEqual(checkpoints[0]['findings'][0]['fault'],{'family':'link_down','device':'r1','target':'eth0'})

    def test_address_repair_candidates_include_measured_lost_default_route(self):
        self.run_worker('full',address_missing=True)
        task=next(p['task'] for op,p in self.worker_calls if op=='model' and p['role']=='Remediation')
        choices=task['allowed_research_action_templates']
        self.assertIn({'op':'address_add','device':'pc1','target':'eth0','value':'10.0.1.10/24'},choices)
        self.assertIn({'op':'route_replace','device':'pc1','target':'default','value':'10.0.1.1'},choices)
        address_finding=next(f for f in task['diagnosis']['findings'] if f['fault']['family']=='address_missing')
        self.assertIn('pc1-routes',address_finding['evidence_ids'])

    def test_link_route_consequence_is_not_an_extra_root_and_has_repair_candidate(self):
        self.run_worker('rule_based',link_route_lost=True)
        task=next(p['task'] for op,p in self.worker_calls if op=='model' and p['role']=='Remediation')
        self.assertEqual([f['fault'] for f in task['diagnosis']['findings']],[{'family':'link_down','device':'r1','target':'eth1'}])
        self.assertIn({'op':'route_replace','device':'r1','target':'10.0.2.0/24','value':'10.0.12.2'},task['allowed_research_action_templates'])
        self.assertIn('r1-routes',task['diagnosis']['findings'][0]['evidence_ids'])
