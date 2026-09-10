import json
import sys
import unittest
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from geometry import disk, optical_grid, contains, sample_poly
from particles import Hypotheses, feasible, signal_counts
from directional.diagnostic_recovery import choose
from directional.fallback_cost import ordered_grid
from solver import Solver
from simulator import LocalSimulator


class DiagnosticTests(unittest.TestCase):
    def test_plan_does_not_prune_real_polygon_or_particles(self):
        poly=disk((200,100),80,16); original=poly.copy()
        p=np.c_[sample_poly(poly,256,np.random.default_rng(7)),np.zeros(256),np.full(256,1000),np.zeros(256)]
        old=p.copy()
        for depth in (1,2,3):
            result=choose(poly,p,np.zeros(2),1,2,{'depth':depth,'beam_width':1,'offsets':[100]})
            self.assertTrue(np.isfinite(result['estimated_cost']))
            np.testing.assert_array_equal(poly,original);np.testing.assert_array_equal(p,old)

    def test_hypotheses_replay_history(self):
        h=Hypotheses(3,2048)
        poly=disk((500,0),50,16)
        for obs in [(np.array([0.,0.]),'direction',0.),(np.array([1700.,0.]),'no_signal',None)]:
            h.update(poly,obs)
        self.assertGreater(len(h.p),0)
        for obs in h.history:self.assertTrue(feasible(h.p,obs).all())

    def test_grid_preserves_coverage(self):
        rng=np.random.default_rng(3)
        for _ in range(12):
            poly=disk(rng.uniform(-1000,1000,2),rng.uniform(20,300),16)
            old=optical_grid(poly);new=ordered_grid(poly,np.zeros(2))
            self.assertEqual(sorted(map(tuple,old)),sorted(map(tuple,new)))
            samples=sample_poly(poly,300,rng)
            self.assertLess(np.linalg.norm(samples[:,None]-new[None],axis=2).min(axis=1).max(),20)

    def test_cpu_gpu_final_ranking(self):
        import torch
        if not torch.cuda.is_available():self.skipTest('No CUDA hardware')
        rng=np.random.default_rng(0);poly=disk((400,0),100,16)
        p=np.c_[sample_poly(poly,1024,rng),rng.uniform(-np.pi,np.pi,1024),np.full(1024,1000),rng.integers(0,2,1024)]
        cfg={'depth':1,'beam_width':4}
        cpu=choose(poly,p,np.zeros(2),1,2,cfg)
        gpu=choose(poly,p,np.zeros(2),1,2,cfg,device='cuda')
        np.testing.assert_array_equal(cpu['point'],gpu['point'])
        self.assertEqual(cpu['estimated_cost'],gpu['estimated_cost'])
        boundary=np.array([[0.,0.,0.,1000.,0.], [0.,0.,0.,1000.,1.]])
        pts=np.array([[1000.+1e-6,0.],[-1e-6,500.]])
        reference=signal_counts(boundary,pts,'cpu')
        accelerated=signal_counts(boundary,pts,'cuda',candidate_chunk=None)
        self.assertLessEqual(np.abs(reference-accelerated).max(),2)
        self.assertEqual(reference[0],0)

    def test_disabled_matches_frozen_baseline(self):
        import csv
        base=Path(__file__).resolve().parents[1]
        with (base/'results/batch_v2/cases.csv').open(encoding='utf-8-sig') as f:
            rows=list(csv.DictReader(f))
        expected=next(r for r in rows if r['seed']=='0' and r['policy']=='P4' and r['use_negative']=='True')
        api=LocalSimulator(0,True,'random');r=Solver(api,True,'P4').run()
        self.assertAlmostEqual(r['mean_time_per_source_s'],float(expected['mean_time_per_source_s']),places=8)

    def test_paired_determinism(self):
        cfg={'enabled':True,'local_order':True,'depth':2,'max_steps':3,'beam_width':4}
        results=[]
        for _ in range(2):
            api=LocalSimulator(1,True,'edge');solver=Solver(api,True,'P4',diagnostic=cfg)
            solver.run()
            self.assertGreater(sum(t['diagnostic_count'] for t in solver.trace.values()),0)
            results.append((api.virtual_time,api.log,solver.trace))
        self.assertEqual(results[0],results[1])


if __name__=='__main__':unittest.main()
