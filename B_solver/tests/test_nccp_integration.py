"""Exercise both certificate paths and near observations against the local engine."""
import os
from pathlib import Path
import sys
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
from geometry import mec
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
        for steps in (0, 1):
            with self.subTest(max_steps=steps):
                api, solver = self.make_solver('nccp')
                self.assertTrue(recovery.recover(solver, 2, {'max_steps': steps}))
                event = self.check_certified_event(api, solver)
                self.assertGreater(event['same_state_saving_m'], 9.)

    def test_near_observation_keeps_zero_movement_clear(self):
        api, solver = self.make_solver('nccp', source_x=1.)
        solver.measure(2, np.zeros(2))
        self.assertEqual(api.log[-2]['response']['measure_result'], 'near')
        self.assertEqual(api.log[-1]['position'], [0., 0.])
        self.assertEqual(api.log[-1]['travel_m'], 0.)
        self.assertNotIn('certified_clearance_events', solver.trace[2])
        self.assertEqual(solver.certified, 1)

    def test_invalid_geometric_result_cannot_reach_engine(self):
        api, solver = self.make_solver('nccp')
        before = len(api.log)
        with patch('geometry.nearest_certified_clear_point', return_value=(np.array([0., 0.]), {})):
            with self.assertRaisesRegex(RuntimeError, 'strict distance audit'):
                solver.localize(2)
        self.assertEqual(len(api.log), before)
        self.assertEqual(solver.certified, 0)

    def test_wider_region_cannot_bypass_original_mec_trigger(self):
        api, solver = self.make_solver('nccp')
        solver.tracks[2]['poly'] *= 3
        center, radius = mec(solver.tracks[2]['poly'])
        with self.assertRaisesRegex(RuntimeError, 'existing MEC certificate'):
            solver.clear_certified_polygon(2, center, radius)
        self.assertEqual(len(api.log), 1)


if __name__ == '__main__':
    unittest.main()
