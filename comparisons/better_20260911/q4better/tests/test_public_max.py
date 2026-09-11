"""Public feedback only; synthetic responses test control flow, not model quality."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from solver import Solver
from geometry import coverage


class Feedback:
    def __init__(self, n):
        self.n = n
        self.position = np.zeros(2)
        self.channel = 1
        self.virtual_time = 0.
        self.log = []

    def action(self, path, position=None, channel=None):
        r = dict(accepted=True)
        if position is not None:
            self.virtual_time += float(np.linalg.norm(position-self.position))/5
            self.position = np.asarray(position).copy()
        if path == '/measure':
            self.virtual_time += 5 + int(channel != self.channel)
            self.channel = channel
            r['measure_result'] = 'near' if channel <= self.n else 'no_signal'
        if path == '/clear':
            self.virtual_time += 5
            r['clear_result'] = 'success'
        if path == '/exit':
            r['exit_reason'] = 'user_exit'
        r['virtual_time_s'] = self.virtual_time
        self.log.append((path, self.position.tolist(), channel, r.copy()))
        return r


class PublicMaxTests(unittest.TestCase):
    def test_full_sequences_and_prefix_for_all_legal_counts(self):
        for n in range(10, 17):
            runs = []
            for stop in (False, True):
                api = Feedback(n)
                s = Solver(api, True, 'P4', diagnostic={'stop_after_public_max_clear': stop})
                with patch('solver.coverage', return_value=np.array([[0., 0.], [700., 0.]])):
                    result = s.run()
                self.assertEqual(len(s.cleared), n)
                self.assertEqual(sum(a[0] == '/exit' for a in api.log), 1)
                runs.append(api.log)
            if n < 16:
                self.assertEqual(*runs)
            else:
                end = next(i for i, a in enumerate(runs[0]) if a[0] == '/clear' and a[2] == 16)
                self.assertEqual(runs[1][:-1], runs[0][:end+1])
                self.assertEqual(runs[1][-1][0], '/exit')
                self.assertEqual(result['completion_reason'], 'public_max_cleared')

    def test_distinct_accepted_success_only_and_errors_propagate(self):
        api = Feedback(16)
        s = Solver(api, True, 'P4', diagnostic={'stop_after_public_max_clear': True})
        for _ in range(16):
            s.clear(1, np.zeros(2))
        self.assertEqual(s.cleared, {1})
        self.assertFalse(s.public_max_complete())
        for r in ({'accepted': False, 'clear_result': 'success'},
                  {'accepted': True, 'clear_result': 'no_target_in_range'}):
            with patch.object(api, 'action', return_value=r):
                if not r['accepted']:
                    with self.assertRaises(RuntimeError): s.clear(2, np.zeros(2))
                else:
                    self.assertFalse(s.clear(2, np.zeros(2)))
            self.assertEqual(s.cleared, {1})
        with patch.object(api, 'action', side_effect=OSError('unresolved')):
            with self.assertRaises(OSError): s.clear(2, np.zeros(2))
        for c in range(2, 17): s.clear(c, np.zeros(2))
        self.assertTrue(s.public_max_complete())
        for action in (s.clear, s.measure):
            with self.assertRaises(RuntimeError): action(17, np.zeros(2))
        s.cleared.add(17)
        with self.assertRaises(RuntimeError): s.public_max_complete()

    def test_all_clear_paths_finish_local_bookkeeping(self):
        # Fifteen accepted successes followed by the sixteenth through each real path.
        from directional.diagnostic_recovery import recover
        for mode in ('certificate', 'near', 'active', 'diagnostic', 'optical'):
            api = Feedback(16)
            cfg = {'stop_after_public_max_clear': True, 'grid_version': 'grid_v1'}
            s = Solver(api, True, 'P4', diagnostic=cfg)
            for c in range(1, 16): s.clear(c, np.zeros(2))
            poly = np.array([[-1., -1.], [1., -1.], [1., 1.], [-1., 1.]])
            s.tracks[16] = dict(poly=poly, n=2, negatives=0, views=[], hyp=None)
            if mode == 'certificate': s.clear_certified_polygon(16, np.zeros(2), 2.)
            elif mode == 'near': s.measure(16, np.zeros(2))
            elif mode == 'active': s.localize(16)
            elif mode == 'diagnostic': self.assertTrue(recover(s, 16, cfg))
            else:
                s.tracks[16]['poly'] *= 100
                s.tracks[16]['n'] = 8
                with patch('directional.fallback_cost.ordered_grid', return_value=[np.zeros(2)]):
                    s.localize(16)
            self.assertTrue(s.public_max_complete(), mode)
            self.assertTrue(s.trace[16]['success'])
            self.assertEqual(s.trace[16]['clear_attempts'], 1)
            self.assertEqual(api.log[-1][0], '/clear')
            if mode == 'certificate':
                self.assertTrue(s.trace[16]['certified_clearance_events'][-1]['success'])

    def test_coverage_and_q3_defaults(self):
        a = coverage(True)
        c = coverage(True, version='certified37')
        np.testing.assert_array_equal(c, a[np.abs(a).sum(axis=1) <= 2800])
        self.assertEqual((len(a), len(c), len(coverage())), (45, 37, 7))
        for cfg in ({'stop_after_public_max_clear': True}, {'discovery_coverage': 'certified37'}):
            with self.assertRaises(ValueError): Solver(None, False, 'P3', diagnostic=cfg)

if __name__ == '__main__': unittest.main()
