"""Exercise both certificate paths and near observations against the local engine."""
import os
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))
SIM = Path(os.environ.get('JAMMERS_SIM_ROOT', 'G:/QQ/jammers_linux'))
sys.path.insert(0, str(SIM))

from engine import Engine, Jammer, Scenario
from recovered_benchmark import EngineAdapter
from phase_audit import TaggedSolver
from geometry import mec, is_certified_clear_point
import directional.diagnostic_recovery as recovery


class NCCPIntegrationTests(unittest.TestCase):
    def make_solver(self, selector=None, source_x=100.):
        api = EngineAdapter(Engine(Scenario('0123456789abcdef', 4, (Jammer(2, source_x, 0., 1000.),))))
        api.action('/enter')
        cfg = {} if selector is None else {'clearance_point': selector}
        solver = TaggedSolver(api, True, 'P4', diagnostic=cfg)
        solver.tracks[2] = dict(poly=np.array([[90., -1.], [110., -1.], [110., 1.], [90., 1.]]),
                                n=2, negatives=0, views=[], hyp=None)
        return api, solver

    def check_certified_event(self, api, solver):
        event = solver.trace[2]['certified_clearance_events'][0]
        point = np.array(event['point'])
        worst = np.linalg.norm(np.array(event['polygon'])-point, axis=1).max()
        self.assertLessEqual(worst, 19.999)
        self.assertLessEqual(event['travel_m'], event['mec_travel_m'])
        self.assertEqual(event['point'], api.log[-1]['position'])
        self.assertEqual(api.log[-1]['stage'], 'certified_clear')
        self.assertEqual(api.log[-1]['response']['clear_result'], 'success')
        self.assertTrue(event['success'])
        self.assertEqual(solver.certified, 1)
        self.assertAlmostEqual(event['time_after']-event['time_before'], event['travel_m']/5+5, places=5)
        return event

    def test_default_retains_mec_center_and_old_action_cost(self):
        api, solver = self.make_solver()
        solver.localize(2)
        event = self.check_certified_event(api, solver)
        np.testing.assert_array_equal(event['point'], [100., 0.])
        self.assertEqual(api.virtual_time, 25.)
        self.assertEqual(event['same_state_saving_m'], 0.)

    def test_localization_uses_shorter_certified_point(self):
        api, solver = self.make_solver('nccp')
        solver.localize(2)
        event = self.check_certified_event(api, solver)
        self.assertGreater(event['same_state_saving_m'], 9.)
        self.assertLess(api.virtual_time, 23.3)

    def test_both_diagnostic_certificate_exits_use_nccp(self):
        for selector in ('nccp', 'segment_entry'):
            for steps in (0, 1):
                with self.subTest(selector=selector, max_steps=steps):
                    api, solver = self.make_solver(selector)
                    self.assertTrue(recovery.recover(solver, 2, {'max_steps': steps}))
                    event = self.check_certified_event(api, solver)
                    self.assertGreater(event['same_state_saving_m'], 9.)

    def test_near_observation_keeps_zero_movement_clear(self):
        for selector in ('nccp', 'segment_entry'):
            api, solver = self.make_solver(selector, source_x=1.)
            solver.measure(2, np.zeros(2))
            self.assertEqual(api.log[-2]['response']['measure_result'], 'near')
            self.assertEqual(api.log[-1]['position'], [0., 0.])
            self.assertEqual(api.log[-1]['travel_m'], 0.)
            self.assertNotIn('certified_clearance_events', solver.trace[2])
            self.assertEqual(solver.certified, 1)

    def test_invalid_geometric_result_falls_back_to_verified_mec(self):
        api, solver = self.make_solver('nccp')
        with patch('geometry.nearest_certified_clear_point', return_value=(np.array([0., 0.]), {})):
            solver.localize(2)
        event = self.check_certified_event(api, solver)
        np.testing.assert_array_equal(event['point'], [100., 0.])
        self.assertEqual(event['verification_status'], 'MEC_FALLBACK')
        self.assertIn('strict clearance/travel audit', event['selection']['fallback_reason'])

    def test_wider_region_cannot_bypass_original_mec_trigger(self):
        api, solver = self.make_solver('nccp')
        solver.tracks[2]['poly'] *= 3
        center, radius = mec(solver.tracks[2]['poly'])
        self.assertFalse(solver.clear_certified_polygon(2, center, radius))
        self.assertEqual(len(api.log), 1)
        self.assertEqual(solver.trace[2]['certificate_failures'][-1]['reason'], 'invalid_mec_radius')
        self.assertNotIn('certified_clearance_events', solver.trace[2])

    def test_segment_localization_submits_a_verified_point(self):
        api, solver = self.make_solver('segment_entry')
        solver.localize(2)
        event = self.check_certified_event(api, solver)
        self.assertEqual(event['verification_status'], 'SEGMENT_ENTRY_VERIFIED')
        self.assertGreater(event['same_state_saving_m'], 9.)
        self.assertEqual(event['submitted_position'], dict(x=event['point'][0], y=event['point'][1]))

    def test_selector_numerical_errors_fall_back_but_transport_errors_do_not(self):
        for selector, function in (('nccp', 'nearest_certified_clear_point'),
                                   ('segment_entry', 'segment_certified_clear_point')):
            for error in (ValueError('injected numeric error'), FloatingPointError('injected FP failure'),
                          RuntimeError('NUMERICAL_UNRESOLVED')):
                api, solver = self.make_solver(selector)
                with patch('geometry.'+function, side_effect=error):
                    solver.localize(2)
                event = self.check_certified_event(api, solver)
                self.assertTrue(event['selection']['fallback'])
                self.assertEqual(event['same_state_saving_m'], 0.)
        for error in (TimeoutError('transport unresolved'), RuntimeError('protocol rejection')):
            api, solver = self.make_solver('nccp')
            with patch.object(api, 'action', side_effect=error) as action:
                with self.assertRaises(type(error)):
                    solver.localize(2)
            self.assertEqual(action.call_count, 1)
            self.assertEqual(solver.certified, 0)

    def test_invalid_polygon_or_witness_is_false_without_clear(self):
        for poly, center, radius in ((np.empty((0, 2)), [0., 0.], 0.),
                                     (np.array([[np.nan, 0.]]), [0., 0.], 1.),
                                     (np.array([[100., 0.]]), [0., 0.], 1.)):
            api, solver = self.make_solver('nccp')
            solver.tracks[2]['poly'] = poly
            self.assertFalse(solver.clear_certified_polygon(2, center, radius))
            self.assertEqual(len(api.log), 1)
            self.assertEqual(solver.certified, 0)
            self.assertTrue(solver.trace[2]['certificate_failures'])
            self.assertNotIn('certified_clearance_events', solver.trace[2])

    def test_unavailable_certificate_continues_original_localization_measure(self):
        api, solver = self.make_solver('nccp')
        # A finite wide hard domain plus an under-reported radius: wrapper must
        # refuse it, then the existing P1 side-step still supplies a measurement.
        solver.policy = 'P1'
        solver.mixed = False
        solver.tracks[2]['poly'] = np.array([[70., -10.], [130., -10.], [130., 10.], [70., 10.]])
        with patch('solver.mec', return_value=(np.array([100., 0.]), 1.)):
            solver.localize(2, one_step=True)
        self.assertEqual(api.log[-1]['path'], '/measure')
        self.assertFalse(any(a['path'] == '/clear' for a in api.log))
        self.assertEqual(solver.trace[2]['certificate_failures'][0]['reason'], 'invalid_mec_certificate')

    def test_actual_client_json_coordinates_match_submission_audit(self):
        from simulator import Client
        from solver import Solver
        for selector in ('mec_center', 'nccp', 'segment_entry'):
            with tempfile.TemporaryDirectory() as temp:
                api = Client('offline-fixture', Path(temp)/'http.jsonl')
                solver = Solver(api, diagnostic={'clearance_point': selector})
                poly = np.array([[90., -1.], [110., -1.], [110., 1.], [90., 1.]])
                solver.tracks[2] = {'poly': poly}
                submitted = []

                def response(request, timeout):
                    payload = json.loads(request.data.decode('utf-8'))
                    submitted.append(payload['position'])
                    point = np.array([payload['position']['x'], payload['position']['y']])
                    self.assertTrue(is_certified_clear_point(poly, point, 19.999))
                    reply = io.StringIO(json.dumps(dict(accepted=True, clear_result='success',
                                                       virtual_time_s=float(np.linalg.norm(point)/5+5))))
                    reply.status = 200
                    return reply

                with patch('simulator.urlopen', side_effect=response):
                    self.assertTrue(solver.clear_certified_polygon(2, *mec(poly)))
                event = solver.trace[2]['certified_clearance_events'][0]
                self.assertEqual(submitted, [event['submitted_position']])
                self.assertEqual(event['point'], [submitted[0]['x'], submitted[0]['y']])
                self.assertTrue(event['json_roundtrip_verified'])


if __name__ == '__main__':
    unittest.main()
