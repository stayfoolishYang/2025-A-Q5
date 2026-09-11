"""Existing HTTP client contract used unchanged by the offline integration."""
import io
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from simulator import Client

class Response(io.StringIO):
    status=200
    def __init__(self,body): super().__init__(json.dumps(body))

class ClientContractTests(unittest.TestCase):
    def test_rejection_retains_state_and_zero_is_not_current_time(self):
        with tempfile.TemporaryDirectory() as d:
            c=Client('offline',Path(d)/'wire.jsonl');c.virtual_time=123.;c.channel=7
            with patch('simulator.urlopen',return_value=Response(dict(accepted=False,virtual_time_s=0,clear_result='success'))):
                with self.assertRaises(RuntimeError):c.action('/clear',np.array([10.,20.]),8)
            self.assertEqual((c.virtual_time,c.channel),(123.,7));np.testing.assert_array_equal(c.position,[0.,0.])

    def test_retry_reuses_entire_request_and_clear_keeps_measure_channel(self):
        with tempfile.TemporaryDirectory() as d:
            c=Client('offline',Path(d)/'wire.jsonl');c.channel=7;calls=[]
            def send(req,timeout):
                calls.append(req.data)
                if len(calls)==1:raise OSError('lost response')
                return Response(dict(accepted=True,virtual_time_s=5.,clear_result='success'))
            with patch('simulator.urlopen',side_effect=send),patch('simulator.time.sleep'):
                r=c.action('/clear',np.zeros(2),8)
            self.assertTrue(r['accepted']);self.assertEqual(calls[0],calls[1]);self.assertEqual(c.channel,7)
            self.assertTrue(json.loads(calls[0])['request_id'])

    def test_enter_uses_actual_remaining_budget_and_unresolved_request_propagates(self):
        with tempfile.TemporaryDirectory() as d:
            c=Client('offline',Path(d)/'wire.jsonl')
            with patch('simulator.urlopen',return_value=Response(dict(accepted=True,virtual_time_s=0.,remaining_real_duration_s=91.))),patch('simulator.time.monotonic',return_value=1000.):
                c.action('/enter')
            self.assertEqual(c.deadline,1091.)
            c.deadline=time.monotonic()+100
            with patch('simulator.urlopen',side_effect=OSError('unresolved')) as call,patch('simulator.time.sleep'):
                with self.assertRaises(OSError):c.action('/measure',np.zeros(2),1)
            self.assertEqual(call.call_count,3);self.assertEqual(c.virtual_time,0.)

if __name__=='__main__':unittest.main()
