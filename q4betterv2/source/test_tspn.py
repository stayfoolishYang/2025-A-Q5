import inspect,sys,unittest
from types import SimpleNamespace
from unittest.mock import patch
import numpy as np
from tspn_benchmark import SIM,OUT,read,Observed
sys.path.insert(0,str(SIM))
from engine import Engine,Scenario,Jammer
from solver import Solver
from geometry import mec,is_certified_clear_point,exact_squared_distance
from tspn_geometry import choose,R_CERT,length
from tspn_policy import NeighborhoodSolver

class SafetyTests(unittest.TestCase):
    def setUp(self):
        self.p=np.array([[-4.,-3.],[4.,-3.],[4.,3.],[-4.,3.]])
        self.m,self.r=mec(self.p);self.x=np.array([-50.,15.]);self.u=np.array([70.,35.])
    def point(self,mode='MEC',**kw):return choose(self.p,self.x,self.m,self.r,self.u,mode,**kw)
    def test_r12_canonical_replay(self):self.assertTrue(read(OUT/'R12_CANONICAL_REPLAY.json')['passed'])
    def test_tspn_off_equals_r12(self):
        s=NeighborhoodSolver(None,True,'P4',diagnostic={'tspn_mode':'OFF'})
        with patch.object(Observed,'clear_certified_polygon',return_value=True) as f:
            self.assertTrue(s.clear_certified_polygon(2,self.m,self.r));f.assert_called_once_with(2,self.m,self.r)
    def test_safe_disk_derivation(self):
        q,e=self.point();self.assertLessEqual(np.linalg.norm(q-self.m)+self.r,R_CERT+1e-12)
    def test_safe_disk_zero_radius(self):
        p=np.zeros((1,2));q,e=choose(p,self.x,np.zeros(2),R_CERT,self.u)
        np.testing.assert_array_equal(q,[0,0]);self.assertEqual(e['status'],'ZERO_RADIUS')
    def test_safe_disk_positive_radius(self):
        q,e=self.point();self.assertGreater(e['safe_radius'],0);self.assertGreater(e['local_saving'],0)
    def test_baseline_clear_point_feasible(self):self.assertTrue(is_certified_clear_point(self.p,self.m,R_CERT))
    def test_tspn_point_inside_safe_neighborhood(self):
        for mode in ('MEC','EXACT'):
            q,e=self.point(mode);self.assertTrue(is_certified_clear_point(self.p,q,R_CERT));self.assertLessEqual(length(self.x,q,self.u),length(self.x,self.m,self.u))
    def engine_clear(self,s,q,kind='directional'):
        eng=Engine(Scenario('0'*16,4,(Jammer(2,float(s[0]),float(s[1]),1000.,kind,0.),)))
        eng.apply('/enter',{});r=eng.apply('/clear',{'channel':2,'position':dict(x=float(q[0]),y=float(q[1]))})
        return eng,r
    def test_adversarial_boundary_source_clear_safe(self):
        q,e=self.point();d=self.m-q;d/=np.linalg.norm(d);s=self.m+self.r*d
        self.assertEqual(self.engine_clear(s,q)[1]['clear_result'],'success')
    def test_exact_vertex_constraints(self):
        q,e=self.point('EXACT');self.assertTrue(is_certified_clear_point(self.p,q,R_CERT))
    def test_exact_continuous_region_proof_assumption(self):
        q,e=self.point('EXACT')
        # Convex combinations exercise the proved convex-hull representation.
        rng=np.random.default_rng(13);w=rng.dirichlet(np.ones(4),200)
        self.assertTrue(np.all(np.linalg.norm(w@self.p-q,axis=1)<=R_CERT))
    def test_optimizer_failure_falls_back(self):
        def fail(*a,**k):return SimpleNamespace(success=False,nit=1,message='INJECTED',x=np.zeros(2))
        q,e=self.point('EXACT',optimizer=fail);self.assertTrue(e['fallback']);np.testing.assert_array_equal(q,self.m)
    def test_numerical_margin_falls_back(self):
        def nan(*a,**k):return SimpleNamespace(success=True,nit=1,message='INJECTED',x=np.array([np.nan,0.]))
        q,e=self.point(optimizer=nan);self.assertTrue(e['fallback']);np.testing.assert_array_equal(q,self.m)
    def test_infeasible_output_falls_back(self):
        def bad(*a,**k):return SimpleNamespace(success=True,nit=1,message='INJECTED',x=np.array([1e5,0.]))
        q,e=self.point(optimizer=bad);self.assertTrue(e['fallback']);np.testing.assert_array_equal(q,self.m)
    def test_boundary_precision(self):
        self.assertFalse(is_certified_clear_point(np.zeros((1,2)),[np.nextafter(R_CERT,np.inf),0.],R_CERT))
        self.assertTrue(is_certified_clear_point(np.zeros((1,2)),[R_CERT,0.],R_CERT))
    def test_negative_slack_hard_fail(self):
        with self.assertRaisesRegex(RuntimeError,'HARD_FAIL'):choose(self.p,self.x,self.m,20.1)
    def test_clear_rule_unchanged(self):
        for kind in ('omni','directional'):
            eng,r=self.engine_clear([20,0],[0,0],kind);self.assertEqual(r['clear_result'],'success');self.assertEqual(eng.channel,1);self.assertEqual(eng.virtual_us,5000000)
            eng,r=self.engine_clear([20.00001,0],[0,0],kind);self.assertEqual(r['clear_result'],'no_target_in_range');self.assertEqual(eng.virtual_us,3000000)
    def test_no_early_clear(self):self.assertIs(NeighborhoodSolver.localize,Observed.localize)
    def test_no_delayed_clear(self):self.assertIs(NeighborhoodSolver.run,Solver.run)
    def test_no_task_reorder(self):self.assertIs(NeighborhoodSolver.run,Solver.run)
    def test_no_discovery_skip(self):self.assertIs(NeighborhoodSolver.measure_discovery,Solver.measure_discovery)
    def test_no_hidden_truth(self):
        import tspn_policy,tspn_geometry
        text=inspect.getsource(tspn_policy)+inspect.getsource(tspn_geometry)
        for token in ('.sources','.scenario','load_scenario','jammers','noise_seed'):self.assertNotIn(token,text)
    def test_no_particle_as_certificate(self):
        import tspn_geometry
        text=inspect.getsource(tspn_geometry)
        for token in ('Hypotheses',"['hyp']",'sample_poly'):self.assertNotIn(token,text)
    def test_finite_termination(self):self.assertIs(NeighborhoodSolver.public_max_complete,Solver.public_max_complete)
    def test_clear_success_all_possible_vertices(self):
        for mode in ('MEC','EXACT'):
            q,e=self.point(mode)
            for v in self.p:self.assertEqual(self.engine_clear(v,q)[1]['clear_result'],'success')
    def test_anchor_observation_does_not_mutate(self):
        s=NeighborhoodSolver(None,True,'P4');nodes=[np.array([1.,2.])];s.release_discovery(nodes)
        np.testing.assert_array_equal(s.anchor(),nodes[0]);self.assertEqual(len(nodes),1)
        s.known16_trigger={};s.cleared=set(range(1,17));s.release_discovery(nodes);self.assertIsNone(s.anchor())

if __name__=='__main__':unittest.main(verbosity=2)
