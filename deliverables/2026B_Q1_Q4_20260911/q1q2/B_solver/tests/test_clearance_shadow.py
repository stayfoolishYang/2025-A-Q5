"""Small offline shadow checks; no scene generator, solver.run, HTTP or UI."""
import copy
import functools
import sys
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(BASE))
sys.path.insert(0,str(BASE/'experiments'))
from clearance_shadow import (ShadowCollector, StrictReplay, active_hooks,
    compute_state_metrics, diagnostic_hook, fingerprint, record_hypothesis_rngs,
    rng_snapshot, compare_shadow_replays)


POLY = np.array([[-40.,-40.],[40.,-40.],[40.,40.],[-40.,40.]])
PARTICLES = np.array([[-39.,0.,0.,1000.,0.],[39.,0.,0.,1000.,0.]])


class ClearanceShadowTests(unittest.TestCase):
    def test_weights_are_fixed_scenarios_not_observation_bins(self):
        result = compute_state_metrics(POLY,PARTICLES,[-100.,0.],[[-39.,0.],[2000.,0.]],
            planner_kind='diagnostic_v1',candidate_current_scores={0:100.},chosen_index=0,max_scenarios=2)
        first,second = result['candidate_records']
        self.assertAlmostEqual(first['sampled_cert_score'],0.5)
        self.assertAlmostEqual(second['sampled_cert_score'],0.)
        self.assertEqual(len(first['outcomes']),6)
        self.assertEqual(sum(o['outcome']=='near' for o in first['outcomes']),3)
        self.assertTrue(all(o['weight']==1/6 for o in first['outcomes']))
        # The three near witnesses produce one near observation; three bearings
        # produce three different observations. Counting bins would give 1/4.
        self.assertNotEqual(first['sampled_cert_score'],1/4)
        self.assertEqual(result['scenario_design']['scenario_count'],6)

    def test_extra_possible_no_signal_has_zero_certificate_weight(self):
        particles=np.array([[0.,0.,0.,1000.,0.],[0.,0.,np.pi,1000.,1.]])
        result=compute_state_metrics(POLY,particles,[-100.,0.],[[100.,0.]],
            planner_kind='diagnostic_v1',max_scenarios=1)
        row=result['candidate_records'][0]
        extras=[o for o in row['outcomes'] if o['scenario_id']=='conservative_no_signal_witness']
        self.assertEqual(len(extras),1)
        self.assertEqual(extras[0]['weight'],0.)
        self.assertAlmostEqual(row['sampled_weight_sum'],1.)
        self.assertAlmostEqual(row['G_worst'],result['current_G'])
        self.assertTrue(row['no_signal_keeps_hard_polygon'])

    def test_empty_hypotheses_do_not_create_probability(self):
        result=compute_state_metrics(POLY,np.empty((0,5)),[-100.,0.],[[100.,0.],[-100.,100.]],
            planner_kind='q4_active')
        self.assertTrue(result['GAP_DEGENERATE_STATE'])
        self.assertTrue(result['G_rule_matches_min_move_time'])
        self.assertTrue(all(r['sampled_cert_score'] is None for r in result['candidate_records']))

    def test_outside_beam_original_score_is_null(self):
        result=compute_state_metrics(POLY,PARTICLES,[-100.,0.],[[100.,0.],[200.,0.]],
            planner_kind='diagnostic_v1',candidate_current_scores={0:25.},chosen_index=0,max_scenarios=1)
        self.assertEqual(result['candidate_records'][0]['current_v1_score'],25.)
        self.assertIsNone(result['candidate_records'][1]['current_v1_score'])
        self.assertIsNone(result['candidate_records'][1]['rank_current'])
        self.assertEqual(result['candidate_records'][1]['current_v1_score_reason'],'outside_original_v1_beam')

    def test_capture_does_not_change_inputs_or_global_rng(self):
        poly,particles=POLY.copy(),PARTICLES.copy()
        original=fingerprint((poly,particles));state=rng_snapshot()
        collector=ShadowCollector(max_states=None,max_scenarios=1)
        collector.capture(poly,particles,np.array([-100.,0.]),np.array([[100.,0.]]),planner_kind='q4_active')
        self.assertEqual(original,fingerprint((poly,particles)))
        self.assertEqual(state,rng_snapshot())
        self.assertTrue(collector.states[0]['rng_and_inputs_unchanged'])

    def test_diagnostic_policy_runs_once_and_plan_is_unchanged(self):
        import directional.diagnostic_recovery as recovery
        config=dict(depth=1,beam_width=2,offsets=[25],grid_version='grid_v1')
        original=recovery.choose
        expected=original(POLY,PARTICLES,np.array([-100.,0.]),1,2,config)
        calls=[]
        @functools.wraps(original)
        def counted(*args,**kwargs):
            calls.append(1);return original(*args,**kwargs)
        collector=ShadowCollector(max_states=None,max_scenarios=1)
        with patch.object(recovery,'choose',counted):
            with diagnostic_hook(collector):
                actual=recovery.choose(POLY,PARTICLES,np.array([-100.,0.]),1,2,config)
        self.assertEqual(len(calls),1)
        self.assertEqual(fingerprint(actual),fingerprint(expected))
        self.assertEqual(len(collector.states),1)
        self.assertEqual(collector.states[0]['current_score_count'],2)
        self.assertGreater(collector.states[0]['candidate_count'],2)

    def test_q3_q4_hooks_capture_original_policy_once(self):
        import solver,particles
        old_q3,old_q4=solver.next_view,particles.Hypotheses.next
        hyp=particles.Hypotheses(7,16);hyp.p=PARTICLES.copy()
        expected_q3=old_q3(POLY,np.array([-100.,0.]))
        expected_q4=old_q4(hyp,POLY,np.array([-100.,0.]))
        calls={'q3':0,'q4':0}
        @functools.wraps(old_q3)
        def q3(*args,**kwargs):
            calls['q3']+=1;return old_q3(*args,**kwargs)
        @functools.wraps(old_q4)
        def q4(*args,**kwargs):
            calls['q4']+=1;return old_q4(*args,**kwargs)
        collector=ShadowCollector(max_states=None,max_scenarios=1)
        rng=fingerprint(hyp.rng.bit_generator.state)
        with patch.object(solver,'next_view',q3),patch.object(particles.Hypotheses,'next',q4):
            with active_hooks(collector):
                actual_q3=solver.next_view(POLY,np.array([-100.,0.]))
                actual_q4=hyp.next(POLY,np.array([-100.,0.]))
        self.assertEqual(calls,{'q3':1,'q4':1})
        self.assertEqual(fingerprint(expected_q3),fingerprint(actual_q3))
        np.testing.assert_array_equal(actual_q4,expected_q4)
        self.assertEqual(rng,fingerprint(hyp.rng.bit_generator.state))
        self.assertEqual([r['planner_kind'] for r in collector.states],['q3_active','q4_active'])
        self.assertTrue(all(r['current_score_count']==r['candidate_count'] for r in collector.states))

    def test_actual_execution_override_and_rejected_plan_are_separate(self):
        solver=SimpleNamespace(trace={2:{'diagnostic_decisions':[{'accepted':False,'grid_cost':10.}]}},tracks={})
        collector=ShadowCollector(solver)
        collector.states=[dict(planner_kind='q3_active',planner_selected_point=[1.,1.],action_index_before_selection=0),
                          dict(planner_kind='diagnostic_v1',planner_selected_point=[2.,2.],action_index_before_selection=1,
                               metadata={'target_channel':2,'decision_index':0})]
        collector.finalize([dict(path='/measure',position=[25.,25.],channel=1),dict(path='/clear',position=[3.,3.],channel=2)])
        self.assertTrue(collector.states[0]['execution_override_detected'])
        self.assertFalse(collector.states[1]['original_plan_accepted'])
        self.assertFalse(collector.states[1]['executed_planned_measurement'])

    def test_strict_replay_rejects_subnanometer_action_drift(self):
        actions=[dict(path='/measure',position=[1.,2.],channel=1,response={'virtual_time_s':5.})]
        replay=StrictReplay(actions)
        with self.assertRaises(AssertionError):
            replay.action('/measure',[1.+1e-12,2.],1)
        self.assertEqual(replay.index,0)

    def test_rng_inventory_keeps_cleared_hypotheses(self):
        from particles import Hypotheses
        with record_hypothesis_rngs() as inventory:
            hyp=Hypotheses(17,16)
            before=fingerprint(hyp.rng.bit_generator.state)
            hyp.rng.random(4)
            del hyp
        self.assertEqual(len(inventory),1)
        self.assertNotEqual(before,fingerprint(inventory[0][2].rng.bit_generator.state))

    def test_trace_fingerprint_excludes_no_fields(self):
        trace={1:{'certified_clearance_events':[dict(selection_runtime_s=0.01,time_before=100.,
                                                   time_after=105.,point=[1.,2.])],
                  'diagnostic_decisions':[{'plan':{'estimated_cost':25.}}]}}
        changed=copy.deepcopy(trace)
        changed[1]['certified_clearance_events'][0]['selection_runtime_s']=9.
        self.assertNotEqual(fingerprint(trace),fingerprint(changed))
        self.assertEqual(trace[1]['certified_clearance_events'][0]['selection_runtime_s'],0.01)
        for field in ('time_after','point'):
            damaged=copy.deepcopy(trace)
            damaged[1]['certified_clearance_events'][0][field]=106. if field=='time_after' else [1.+1e-12,2.]
            self.assertNotEqual(fingerprint(trace),fingerprint(damaged))
        changed=copy.deepcopy(trace)
        changed[1]['diagnostic_decisions'][0]['plan']['estimated_cost']=24.
        self.assertNotEqual(fingerprint(trace),fingerprint(changed))
        changed=copy.deepcopy(trace);changed[1]['other_runtime']=1.
        self.assertNotEqual(fingerprint(trace),fingerprint(changed))

    def test_off_on_gate_rejects_actions_and_virtual_time_changes(self):
        off=dict(actions=[],actions_fingerprint='a',solver_trace_fingerprint='b',
                 solver_trace_excluded_fields=[],
                 policy_rng_fingerprint='c',hypothesis_rng_creation_count=3,virtual_time=100.)
        self.assertTrue(compare_shadow_replays(off,copy.deepcopy(off))['passed'])
        for field in ('actions_fingerprint','solver_trace_fingerprint','virtual_time'):
            on=copy.deepcopy(off);on[field]=101. if field=='virtual_time' else 'changed'
            with self.assertRaises(AssertionError):compare_shadow_replays(off,on)


if __name__=='__main__':
    unittest.main()
