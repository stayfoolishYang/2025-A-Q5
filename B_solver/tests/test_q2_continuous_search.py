"""Requested mathematical regressions; no simulator or official interface."""
import csv
from fractions import Fraction as F
import json
import math
from pathlib import Path
import sys
import tempfile
import unittest
import numpy as np

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(BASE))
from geometry import ERROR_DEG, diameter
from q2_scoring import pair_diameter, adaptive_score
from q2_visibility import (explicit_safe_inner_region_q0, direction_region_q5,
    verify_guaranteed_reception as verify, first_response_disposition,
    unit_intervals, pi_interval, exact_disk)
from q2_continuous_search import baseline, regions, refinement_proposals, PLAN
from questions import q2_example


def sources(radii, angles, p=(0,0)):
    return np.array(p)+np.array([[r*math.cos(a),r*math.sin(a)]
        for r in radii for a in np.deg2rad(angles)])


def reception_residual(q, gs, p=(0,0)):
    return float(np.max(np.linalg.norm(gs-q,axis=1)-np.maximum(1000,np.linalg.norm(gs-p,axis=1))))


class Q2Tests(unittest.TestCase):
    def test_01_definition(self):
        g = np.array([1200.,0.])
        self.assertEqual(max(1000,np.linalg.norm(g)),1200)
        self.assertGreater(np.linalg.norm(g-[0,100]),1200)

    def test_02_old_subset(self):
        poly,legacy,_ = baseline()
        regs = regions(poly)
        self.assertTrue(all(verify(q,regs['Csafe'])['verified'] and verify(q,regs['Q5'])['verified'] for q in legacy))
        self.assertTrue(all(verify(q,regs['Q0'])['verified'] for q in legacy))

    def test_03_q0_membership(self):
        q0 = explicit_safe_inner_region_q0(theta=0)
        self.assertTrue(verify([900,0],q0)['verified'])
        self.assertFalse(verify([1001,0],q0)['verified'])

    def test_04_q0_reception(self):
        gs = sources([0,5,999,1000,1001,1500],np.linspace(-ERROR_DEG,ERROR_DEG,101))
        self.assertLessEqual(reception_residual([500,800],gs),0)
        self.assertTrue(verify([500,800],explicit_safe_inner_region_q0(theta=0))['verified'])

    def test_05_target_circle_clip(self):
        p = np.array([3000.,0.]); q = np.array([1200.,0.])
        gs = sources(np.linspace(1200,1500,101),np.linspace(180-ERROR_DEG,180+ERROR_DEG,101),p)
        gs = gs[np.linalg.norm(gs,axis=1)<=1800]
        self.assertLessEqual(reception_residual(q,gs,p),0)
        self.assertFalse(verify(q,explicit_safe_inner_region_q0(p,180))['verified'])
        with self.assertRaisesRegex(ValueError,'CLIPPED_UNCERTIFIED'):
            direction_region_q5(p,180)

    def test_06_wedge_endpoints(self):
        gs = sources([5,1000,1500],[-ERROR_DEG,ERROR_DEG])
        self.assertLessEqual(reception_residual([500,800],gs),0)

    def test_07_near_boundary(self):
        gs = sources([5,5+1e-9,5.01],np.linspace(-ERROR_DEG,ERROR_DEG,101))
        self.assertLessEqual(reception_residual([1001,0],gs),0)
        self.assertTrue(verify([1001,0],direction_region_q5(theta=0))['verified'])

    def test_08_radius1000(self):
        gs = sources([1000-1e-9,1000,1000+1e-9],[-ERROR_DEG,0,ERROR_DEG])
        self.assertLessEqual(reception_residual([500,800],gs),0)

    def test_09_radius1500(self):
        gs = sources([1500-1e-9,1500],[-ERROR_DEG,0,ERROR_DEG])
        self.assertLessEqual(reception_residual([1001,0],gs),0)

    def test_10_alpha_boundary(self):
        self.assertTrue(verify([0,0],explicit_safe_inner_region_q0(theta=0,alpha=90))['verified'])
        self.assertFalse(verify([1e-6,0],explicit_safe_inner_region_q0(theta=0,alpha=90))['verified'])
        with self.assertRaises(ValueError):
            explicit_safe_inner_region_q0(alpha=90.001)
        centers = sources([1000],[-120,120])
        q = np.array([-500.,0.])
        self.assertTrue(all(np.linalg.norm(q-c)<=1000 for c in centers))
        self.assertGreater(reception_residual(q,np.array([[1000.,0.]])),0)

    def test_11_exact_boundary(self):
        self.assertTrue(verify([1000,0],explicit_safe_inner_region_q0(theta=0,alpha=0))['verified'])

    def test_12_just_outside(self):
        self.assertFalse(verify([np.nextafter(1000.,np.inf),0],explicit_safe_inner_region_q0(theta=0,alpha=0))['verified'])

    def test_13_first_near(self):
        self.assertFalse(first_response_disposition('near')['second_station_needed'])
        self.assertEqual(first_response_disposition('near')['actions_sent'],0)

    def test_14_first_direction(self):
        self.assertTrue(first_response_disposition('direction')['second_station_needed'])
        self.assertEqual(first_response_disposition('direction')['source_distance_lower_exclusive_m'],5)

    def test_15_refinement_schedule(self):
        poly,_,anchor = baseline()
        for previous,step in zip(PLAN['steps_m'],PLAN['steps_m'][1:]):
            proposals = refinement_proposals([('anchor',anchor)],regions(poly)['Q0'],anchor,step,previous)
            self.assertTrue(any(np.array_equal(q,anchor) for q,_ in proposals))
            self.assertTrue(all(np.linalg.norm(q-anchor)<2100 for q,_ in proposals))
        self.assertEqual(PLAN['steps_m'][-1],1)

    def test_16_legacy_reproduction(self):
        with tempfile.TemporaryDirectory() as directory:
            result = q2_example(Path(directory))
            with (Path(directory)/'q2_candidates.csv').open(encoding='utf-8-sig') as stream:
                new = list(csv.DictReader(stream))
        with (BASE/'results/q2_candidates.csv').open(encoding='utf-8-sig') as stream:
            old = list(csv.DictReader(stream))
        self.assertEqual(len(new),213)
        error = max(abs(float(a['worst_sampled_diameter_m'])-float(b['worst_sampled_diameter_m'])) for a,b in zip(new,old))
        self.assertLess(error,1e-10)
        self.assertTrue(np.allclose(result['solutions'][1]['point'],[476.121593216773,875.333209967908],rtol=0,atol=1e-9))

    def test_17_stable_diameter(self):
        cases = [([[0,0],[3,0],[0,4]],5), ([[0,0],[1,0],[1,1],[0,1]],math.sqrt(2)),
                 ([[0,0],[1,0],[2,0]],2), ([[0,0],[0,0],[2,0],[2,0]],2),
                 ([[0,0],[1e-13,0],[1000,1e-12],[1000,0]],1000)]
        known = json.loads((BASE/'results/q2_score_20260911/CALIPERS_DIAGNOSTIC.json').read_text())['worst']
        cases.append((known['polygon'],known['numpy_pair_diameter_m']))
        self.assertGreater(pair_diameter(np.array(known['polygon']))-diameter(np.array(known['polygon']))[0],.69)
        for vertices,expected in cases:
            p = np.array(vertices,dtype=float)
            for i in range(len(p)):
                self.assertAlmostEqual(pair_diameter(np.roll(p,i,axis=0)),expected,places=10)
            self.assertAlmostEqual(pair_diameter(p[::-1]),expected,places=10)

    def test_18_dense_falsification(self):
        rng = np.random.default_rng(20260911)
        gs = sources(np.r_[np.linspace(5,1500,101),999.999,1000.001],np.linspace(-ERROR_DEG,ERROR_DEG,61))
        checked = 0
        for q in rng.uniform([0,-1100],[1100,1100],size=(600,2)):
            if verify(q,direction_region_q5(theta=0))['verified']:
                self.assertLessEqual(reception_residual(q,gs),1e-9)
                checked += 1
        self.assertGreater(checked,100)

    def test_19_vertex_counterexample(self):
        vertices = np.array([[10,-.1],[10,.1],[1500,0]])
        self.assertLess(reception_residual([400,900],vertices),0)
        self.assertGreater(reception_residual([400,900],np.array([[1000.,0.]])),0)

    def test_20_trig_interval(self):
        lo,hi = pi_interval()
        # Decimal reference only cross-checks; proof uses exact alternating-series bounds.
        reference = F('3.141592653589793238462643383279502884197169399375105820974944592307816406286')
        self.assertLess(lo,reference); self.assertGreater(hi,reference)
        for angle in [-179,-91,-30,0,29-ERROR_DEG,30+ERROR_DEG,179,360]:
            bounds = unit_intervals(F(angle))
            for (a,b),reference in zip(bounds,[math.cos(math.radians(angle)),math.sin(math.radians(angle))]):
                self.assertLessEqual(float(a)-1e-15,reference)
                self.assertGreaterEqual(float(b)+1e-15,reference)

    def test_21_requested_counterexample_rigid_motion(self):
        vertices = np.array([[10,0],[1490,-10],[1490,10]],dtype=float)
        q = np.array([350,900]); g = np.array([[1000,0]])
        for angle in [0,30,359.9]:
            a = math.radians(angle)
            rotation = np.array([[math.cos(a),-math.sin(a)],[math.sin(a),math.cos(a)]])
            p = np.array([170,-270])
            self.assertLess(reception_residual(q@rotation.T+p,vertices@rotation.T+p,p),0)
            self.assertGreater(reception_residual(q@rotation.T+p,g@rotation.T+p,p),110)

    def test_22_p_membership_repeat(self):
        self.assertTrue(verify([0,0],direction_region_q5())['verified'])
        self.assertFalse(verify([0,0],[exact_disk([1500,0])])['verified'])
        poly,_,_ = baseline()
        score = adaptive_score((np.zeros(2),poly))
        self.assertEqual(score['D_upper_m'],pair_diameter(poly))
        self.assertEqual(score['posterior_evaluations'],0)

    def test_23_invalid_and_unresolved(self):
        with self.assertRaises(ValueError): verify([0,0],[])
        with self.assertRaises(ValueError): verify([math.nan,0],[exact_disk([0,0])])
        with self.assertRaises(ValueError): verify([0],[exact_disk([0,0])])
        disk = dict(center=[(F(-1,10**9),F(1,10**9)),(F(0),F(0))],radius=F(1000))
        self.assertEqual(verify([1000,0],[disk])['status'],'UNRESOLVED')
        self.assertEqual(verify([1001,0],[disk])['status'],'UNSAFE')

    def test_24_cross_zero_rotation(self):
        for theta in [-.2,359.8,719.8]:
            q = sources([900],[theta])[0]
            self.assertTrue(verify(q,explicit_safe_inner_region_q0(theta=theta))['verified'])

    def test_25_arc_and_intersection_perturbations(self):
        from q2_continuous_search import circle_intersections
        discs = [exact_disk([0,0]),exact_disk([1000,0])]
        for q in circle_intersections(np.array([0.,0.]),1000,np.array([1000.,0.]),1000):
            inward = q+1e-5*(np.array([500.,0.])-q)/1000
            outward = q-1e-5*(np.array([500.,0.])-q)/1000
            self.assertTrue(verify(inward,discs)['verified'])
            self.assertFalse(verify(outward,discs)['verified'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
