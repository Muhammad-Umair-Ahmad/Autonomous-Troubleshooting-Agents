"""Opt-in real emulation verification. No mocks; never runs by default."""
import os
import unittest
from neta.util import ROOT,read

@unittest.skipUnless(os.environ.get('NETA_LIVE_TESTS')=='1','set NETA_LIVE_TESTS=1 for real isolated emulation tests')
class LiveRecovery(unittest.TestCase):
    def test_faulty_twin_failed_plan_and_real_rollback(self):
        from neta.remediation import controlled_experiments
        result=controlled_experiments()
        self.assertTrue(result['all_passed'],result)
    def test_agent_filesystem_and_network_boundary(self):
        from neta.util import run,write
        import json
        worker=ROOT/'src/neta/agent/worker.py'
        code='import json,os,socket; print(json.dumps({"truth_access":os.path.exists("/research/data/private/local-truth.json"),"socket_access":os.path.exists("/var/run/docker.sock"),"mounted_worker":os.path.isfile("/agent/worker.py"),"uid":os.getuid()}))'
        result=run(['docker','run','--rm','--network','none','--read-only','--cap-drop','ALL','--security-opt','no-new-privileges',
                    '--user','65534:65534','--mount',f'type=bind,src={worker},dst=/agent/worker.py,readonly',
                    'neta-linux:research','python3','-c',code])
        actual=json.loads(result['stdout']);write(ROOT/'results/isolation-proof.json',actual)
        self.assertFalse(actual['truth_access']);self.assertFalse(actual['socket_access']);self.assertTrue(actual['mounted_worker']);self.assertEqual(actual['uid'],65534)
