import sys
from pathlib import Path
import unittest
from unittest.mock import patch
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from solver import Solver
from geometry import coverage, optical_grid
from test_public_max import Feedback

class KnownTests(unittest.TestCase):
    def test_near_and_unchanged_under16(self):
        for version in ('certified37','certified25'):
            for n in range(10,17):
                logs=[]
                for flag in (False,True):
                    api=Feedback(n);s=Solver(api,True,'P4',diagnostic=dict(stop_after_public_max_clear=True,discovery_coverage=version,finish_after_public_max_known=flag))
                    with patch('solver.coverage',return_value=np.array([[0.,0.],[700.,0.]])):s.run()
                    self.assertEqual(s.confirmed,set(range(1,n+1)))
                    self.assertEqual(len(s.cleared),n);logs.append(api.log)
                    self.assertEqual(s.known16_trigger is not None,flag and n==16)
                self.assertEqual(*logs)
    def test_distinct_and_rejected(self):
        api=Feedback(16);s=Solver(api,True,'P4',diagnostic=dict(finish_after_public_max_known=True))
        for _ in range(3):s.measure(1,np.zeros(2))
        self.assertEqual(s.confirmed,{1})
        for response in (dict(accepted=False,measure_result='direction',svd_deg=0),dict(accepted=False,clear_result='success')):
            with patch.object(api,'action',return_value=response):
                with self.assertRaises(RuntimeError):
                    (s.measure if 'measure_result' in response else s.clear)(2,np.zeros(2))
        with patch.object(api,'action',return_value=dict(accepted=True,clear_result='no_target_in_range')):self.assertFalse(s.clear(2,np.zeros(2)))
        with patch.object(api,'action',return_value=dict(accepted=True,measure_result='no_signal')):s.measure(2,np.zeros(2))
        self.assertEqual(s.confirmed,{1})
    def test_direction_sweep_releases_but_finishes_tracks(self):
        class Directions(Feedback):
            def action(self,path,position=None,channel=None):
                r=super().action(path,position,channel)
                if path=='/measure' and channel<=16:r.update(measure_result='direction',svd_deg=0.)
                return r
        api=Directions(16);s=Solver(api,True,'P4',particles=16,diagnostic=dict(stop_after_public_max_clear=True,finish_after_public_max_known=True))
        # Keep real measure/bookkeeping, avoid particle sampling as this is a state test.
        class Hyp:
            history=[];p=[]
            def __init__(self,*a):pass
            def update(self,*a):pass
        with patch('solver.Hypotheses',Hyp),patch('solver.coverage',return_value=np.array([[0.,0.],[700.,0.]])),patch.object(s,'localize',side_effect=lambda c,one_step=False:s.clear(c,api.position)):
            s.run()
        self.assertEqual(s.cleared,set(range(1,17)))
        self.assertEqual(s.known16_trigger['unresolved'],16)
        self.assertEqual(len([a for a in api.log if a[0]=='/measure']),16)
        self.assertEqual(api.log[-1][0],'/exit')
    def test_exact_hull_roundoff_and_malformed_order(self):
        from fractions import Fraction
        from reporting.discovery_report import point_in_convex_polygon_exact as inside
        square=[[0.,0.],[1.,0.],[1.,1.],[0.,1.]]
        point=(Fraction(1,2),Fraction(1,2))
        self.assertTrue(inside(point,square))
        self.assertFalse(inside(point,[square[i] for i in (0,2,1,3)]))
        self.assertFalse(inside((Fraction(-1,10**15),Fraction(1,2)),square))
        tiny=square+[[0.,1.-1e-15]]
        self.assertTrue(inside(point,tiny))
    def test_contradiction_and_defaults(self):
        s=Solver(Feedback(16),True,'P4',diagnostic=dict(finish_after_public_max_known=True))
        for c in range(1,17):s.confirm_channel(c)
        with self.assertRaises(RuntimeError):s.release_discovery([1])
        self.assertEqual((len(coverage()),len(coverage(True)),len(coverage(True,version='certified25'))),(7,45,25))
        for cfg in (dict(finish_after_public_max_known=True),dict(discovery_coverage='certified25')):
            with self.assertRaises(ValueError):Solver(None,False,'P3',diagnostic=cfg)
        with self.assertRaises(ValueError):Solver(None,True,'P4',diagnostic=dict(finish_after_public_max_known=1))
        self.assertNotIn('certified25',__import__('inspect').getsource(optical_grid))

if __name__=='__main__':unittest.main()
