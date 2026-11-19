"""Software-only failure recovery contracts; not live experimental evidence."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from neta.util import digest,write
from neta.recovery import pilot_usable,development_pilot
from neta.experiments import throughput,MODELS


def row(status='completed',restored=True,seconds=20):
    return {'run_id':'fixture','status':status,'final_restored':restored,'elapsed_total_s':seconds,
            'tokens_total':100,'model_calls':[{'fixture':True}]}


class Recovery(unittest.TestCase):
    def test_accuracy_failure_remains_empirical_but_infrastructure_does_not(self):
        self.assertTrue(pilot_usable(row('agent_failed')))
        self.assertFalse(pilot_usable(row('infrastructure_failed',seconds=.01)))
        self.assertFalse(pilot_usable(row(restored=False)))
        empty=row();empty['model_calls']=[]
        self.assertFalse(pilot_usable(empty))

    def test_service_failure_stops_before_recording_more_pilots(self):
        with tempfile.TemporaryDirectory() as d,patch('neta.recovery.ROOT',Path(d)),patch('neta.recovery.check_services',side_effect=RuntimeError('offline')),patch('neta.experiments.run_case') as run_case:
            with self.assertRaisesRegex(RuntimeError,'offline'):development_pilot('dev',{'seed':1030})
            run_case.assert_not_called()

    def test_cached_failed_attempt_is_preserved_and_retry_keeps_seed(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);cfg={'seed':1030};initial={**cfg,'development_attempt':0}
            first=digest(['dev',initial,'pilot'])[:24]
            old={**row('infrastructure_failed'),'run_id':first}
            path=root/'results/runs/pilot'/f'{first}.json';write(path,old);before=path.read_bytes()
            with patch('neta.recovery.ROOT',root),patch('neta.recovery.check_services'),patch('neta.experiments.run_case',return_value=row()) as run_case:
                result=development_pilot('dev',cfg)
            self.assertTrue(pilot_usable(result));self.assertEqual(path.read_bytes(),before)
            retried=run_case.call_args.args[1]
            self.assertEqual(retried['seed'],1030);self.assertEqual(retried['development_attempt'],1)
            self.assertEqual(retried['retry_of'],first)

    def test_new_infrastructure_failure_fails_fast(self):
        with tempfile.TemporaryDirectory() as d,patch('neta.recovery.ROOT',Path(d)),patch('neta.recovery.check_services'),patch('neta.experiments.run_case',return_value=row('infrastructure_failed')) as run_case:
            with self.assertRaisesRegex(RuntimeError,'gate failed'):development_pilot('dev',{'seed':1030})
            self.assertEqual(run_case.call_count,1)

    def test_throughput_excludes_outages_and_does_not_freeze_manifest(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);write(root/'configs/experiment-plan.json',{'local_total_cells':3150})
            for i,model in enumerate(MODELS):
                value={**row(seconds=10*(i+1)),'case_id':'dev','split':'validation','finished':str(i),
                       'config':{'model':model,'implementation_hash':digest({}),'knowledge':'curated-v1','method':'full'}}
                write(root/'results/runs/pilot'/f'{i}.json',value)
            outage={**value,**row('infrastructure_failed',seconds=.001)}
            write(root/'results/runs/pilot/outage.json',outage)
            with patch('neta.experiments.ROOT',root),patch('neta.experiments.cases',return_value=[{'case_id':'dev'}]):result=throughput()
            self.assertEqual(result['status'],'measured');self.assertEqual(result['pilot_runs'],3)
            self.assertEqual(result['mean_seconds_per_run'],20)
            self.assertEqual(result['excluded_or_superseded_pilot_runs'],1)
            self.assertFalse((root/'configs/experiments.main.json').exists())

class MainExecutionRecovery(unittest.TestCase):
    def test_cached_infrastructure_failure_gets_separate_same_config_attempt(self):
        from neta.experiments import execute_cell,execution_id
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);cfg={'seed':1000};first=execution_id('test',cfg,'main')
            path=root/'results/runs/main'/f'{first}.json'
            write(path,{**row('infrastructure_failed'),'run_id':first});before=path.read_bytes()
            with patch('neta.experiments.ROOT',root),patch('neta.recovery.check_services'),patch('neta.experiments.run_case',return_value=row()) as run_case:
                result=execute_cell('test',cfg,'main')
            self.assertEqual(result['status'],'completed');self.assertEqual(path.read_bytes(),before)
            self.assertEqual(run_case.call_args.args,('test',cfg,'main'))
            self.assertEqual(run_case.call_args.kwargs,{'execution_attempt':1})
            self.assertNotEqual(first,execution_id('test',cfg,'main',1))

    def test_restored_model_failure_is_not_retried_for_score(self):
        from neta.experiments import execute_cell
        with tempfile.TemporaryDirectory() as d,patch('neta.experiments.ROOT',Path(d)),patch('neta.recovery.check_services'),patch('neta.experiments.run_case',return_value=row('agent_failed')) as run_case:
            self.assertEqual(execute_cell('test',{'seed':1000},'main')['status'],'agent_failed')
            self.assertEqual(run_case.call_count,1)

    def test_analysis_selects_first_valid_outcome_not_best_later_score(self):
        from neta.recovery import select_execution_records
        attempts=[{**row('infrastructure_failed'),'run_id':'a','logical_run_id':'cell','execution_attempt':0},
                  {**row('agent_failed'),'run_id':'b','logical_run_id':'cell','execution_attempt':1,'score':0},
                  {**row(),'run_id':'c','logical_run_id':'cell','execution_attempt':2,'score':1}]
        self.assertEqual(select_execution_records(attempts)[0]['run_id'],'b')

class FailureAttribution(unittest.TestCase):
    def test_transport_outage_is_not_a_model_prediction_failure(self):
        import requests,json
        from neta.broker import infrastructure_exception,BudgetExceeded
        self.assertTrue(infrastructure_exception(requests.ConnectionError('offline')))
        self.assertTrue(infrastructure_exception(RuntimeError('docker rc=1: unavailable')))
        response=requests.Response();response.status_code=503
        self.assertTrue(infrastructure_exception(requests.HTTPError(response=response)))
        response.status_code=400
        self.assertFalse(infrastructure_exception(requests.HTTPError(response=response)))
        self.assertFalse(infrastructure_exception(json.JSONDecodeError('bad model JSON','{',0)))
        self.assertFalse(infrastructure_exception(BudgetExceeded('wall_clock_budget')))
        self.assertFalse(infrastructure_exception(requests.ReadTimeout('declared per-call model deadline')))

class ManifestReadiness(unittest.TestCase):
    def test_manifest_cannot_freeze_before_measured_pilots(self):
        from neta.experiments import manifest
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            write(root/'data/private/local-truth.json',{'case':{'validation_status':'validated'}})
            for name in ('docs-v1','curated-v1'):
                snapshot={'chunks':[{'kind':'verified_training_incident' if name=='curated-v1' else 'documentation'}]}
                snapshot['snapshot_id']=digest(snapshot)
                write(root/'knowledge/snapshots'/f'{name}.json',snapshot)
            with patch('neta.experiments.ROOT',root),patch('neta.experiments.cases',return_value=[{'case_id':'case'}]),patch('neta.experiments.throughput',return_value={'status':'pilot_not_complete'}),patch('neta.experiments.run') as run:
                with self.assertRaisesRegex(RuntimeError,'development pilots'):manifest()
                run.assert_not_called()
            self.assertFalse((root/'configs/experiments.main.json').exists())

class AddressDependencyPolicy(unittest.TestCase):
    def plan(self,actions):
        return {'actions':actions,'preconditions':['address absent'],'expected_effects':['restore intent'],
                'verification':['state and probes'],'evidence_ids':['address','routes']}

    def test_only_exact_same_subnet_dependency_with_address_repair_is_permitted(self):
        from neta.remediation import policy
        address={'op':'address_add','device':'pc1','target':'eth0','value':'10.0.1.10/24'}
        route={'op':'route_replace','device':'pc1','target':'default','value':'10.0.1.1'}
        diagnosis={'findings':[{'fault':{'family':'address_missing','device':'pc1','target':'eth0'},'evidence_ids':['address','routes']}]}
        self.assertTrue(policy(self.plan([address,route]),diagnosis,{'pc1':{'routes':[]}})['approved'])
        self.assertFalse(policy(self.plan([route]),diagnosis,{'pc1':{'routes':[]}})['approved'])
        wrong={**route,'value':'10.0.12.1'}
        self.assertFalse(policy(self.plan([address,wrong]),diagnosis)['approved'])
        unrelated={'op':'route_replace','device':'r1','target':'10.0.2.0/24','value':'10.0.12.2'}
        self.assertFalse(policy(self.plan([address,unrelated]),diagnosis)['approved'])
        already_present={'pc1':{'routes':[{'dst':'default','gateway':'10.0.1.1'}]}}
        self.assertFalse(policy(self.plan([address,route]),diagnosis,already_present)['approved'])

    def test_link_dependency_requires_matching_link_restore_and_absent_intended_route(self):
        from neta.remediation import policy
        link={'op':'link_up','device':'r2','target':'eth0','value':''}
        route={'op':'route_replace','device':'r2','target':'10.0.1.0/24','value':'10.0.12.1'}
        diagnosis={'findings':[{'fault':{'family':'link_down','device':'r2','target':'eth0'},'evidence_ids':['address','routes']}]}
        self.assertTrue(policy(self.plan([link,route]),diagnosis,{'r2':{'routes':[]}})['approved'])
        self.assertFalse(policy(self.plan([route]),diagnosis,{'r2':{'routes':[]}})['approved'])
        present={'r2':{'routes':[{'dst':'10.0.1.0/24','gateway':'10.0.12.1'}]}}
        self.assertFalse(policy(self.plan([link,route]),diagnosis,present)['approved'])
