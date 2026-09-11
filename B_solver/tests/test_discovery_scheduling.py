"""Coverage obligations and default compatibility of optional Q4 permutations."""
from collections import Counter
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import numpy as np

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))
sys.path.insert(0, os.environ.get('JAMMERS_SIM_ROOT', 'G:/QQ/jammers_linux'))

from discovery import refresh_remaining_route, unknown_first
from engine import Engine, Jammer, Scenario
from geometry import coverage, route
from recovered_benchmark import EngineAdapter
from solver import Solver


class DiscoverySchedulingTests(unittest.TestCase):
    def test_refresh_preserves_all_45_coordinates_without_mutating_inputs(self):
        nodes = route(coverage(True), np.zeros(2))
        original = nodes.copy()
        current = np.array([1740., -480.])
        start = current.copy()
        refreshed = np.asarray(refresh_remaining_route(nodes, current))
        self.assertEqual(len(refreshed), 45)
        self.assertEqual(Counter(map(tuple, refreshed)), Counter(map(tuple, original)))
        old_length = np.linalg.norm(np.diff(np.vstack((start, original)), axis=0), axis=1).sum()
        new_length = np.linalg.norm(np.diff(np.vstack((start, refreshed)), axis=0), axis=1).sum()
        self.assertLessEqual(new_length, old_length+1e-8)
        np.testing.assert_array_equal(nodes, original)
        np.testing.assert_array_equal(current, start)

    def test_refresh_rejects_worse_or_equal_route_and_handles_empty_or_singleton(self):
        nodes = np.array([[1., 0.], [2., 0.], [3., 0.]])
        current = np.zeros(2)
        for candidate in (nodes[::-1], nodes.copy()):
            with self.subTest(candidate=candidate.tolist()), patch('discovery.route', return_value=candidate):
                np.testing.assert_array_equal(refresh_remaining_route(nodes, current), nodes)
        with patch('discovery.route', side_effect=AssertionError('Empty route must not be optimized')):
            self.assertEqual(refresh_remaining_route([], current), [])
        np.testing.assert_array_equal(refresh_remaining_route(nodes[:1], current), nodes[:1])

    def test_unknown_first_is_stable_complete_and_keeps_known_current_first(self):
        channels = [7, 1, 2, 3, 4, 5, 6, 8]
        original = channels.copy()
        tracks = {7: object(), 2: object(), 5: object()}
        result = unknown_first(channels, tracks)
        self.assertEqual(result, [7, 1, 3, 4, 6, 8, 2, 5])
        self.assertEqual(Counter(result), Counter(channels))
        self.assertEqual(channels, original)
        self.assertEqual(set(tracks), {7, 2, 5})
        self.assertEqual(unknown_first([], tracks), [])

    def test_config_ablation_changes_only_allowed_flags_and_rejects_non_q4(self):
        baseline = json.loads((BASE/'configs/q4_p4_diag_v1_grid_v1.yaml').read_text())
        modes = {'refresh': ('refresh_after_localize', 'legacy'),
                 'unknown': ('legacy', 'unknown_first'),
                 'refresh_unknown': ('refresh_after_localize', 'unknown_first')}
        for suffix, flags in modes.items():
            config = json.loads((BASE/f'configs/q4_p4_diag_v1_grid_v1_{suffix}.yaml').read_text())
            self.assertEqual((config['discovery_route'], config['discovery_channels']), flags)
            self.assertEqual({k: v for k, v in config.items()
                              if k not in ('name', 'discovery_route', 'discovery_channels')},
                             {k: v for k, v in baseline.items() if k != 'name'})
            self.assertEqual(Solver(None, True, 'P4', diagnostic=config).clearance_point, 'mec_center')
            for mixed, policy in ((False, 'P3'), (True, 'P3')):
                with self.assertRaises(ValueError):
                    Solver(None, mixed, policy, diagnostic=config)
        for config in ({'discovery_route': 'drop_nodes'}, {'discovery_channels': 'skip_known'}):
            with self.assertRaises(ValueError):
                Solver(None, True, 'P4', diagnostic=config)
        self.assertEqual(Solver(None, False, 'P3').discovery_route, 'legacy')

    def certificate_fixture(self, config):
        api = EngineAdapter(Engine(Scenario('0123456789abcdef', 4, (Jammer(7, 30., 0., 1000.),))))
        solver = Solver(api, True, 'P4', diagnostic=config)
        solver.tracks[7] = dict(poly=np.array([[29., -1.], [31., -1.], [31., 1.], [29., 1.]]),
                                n=2, negatives=0, views=[], hyp=None)
        return api, solver

    def test_default_and_explicit_legacy_have_identical_actions_and_trace(self):
        results = []
        nodes = np.array([[0., 0.], [100., 0.], [200., 0.]])
        for config in ({}, {'discovery_route': 'legacy', 'discovery_channels': 'legacy'}):
            api, solver = self.certificate_fixture(config)
            with patch('solver.coverage', return_value=nodes), \
                    patch('discovery.refresh_remaining_route', side_effect=AssertionError('Default refresh')), \
                    patch('discovery.unknown_first', side_effect=AssertionError('Default channel reorder')):
                solver.run()
            self.assertEqual(api._engine.cleared, {7})
            results.append((api.log, solver.trace, api.virtual_time))
        self.assertEqual(results[0], results[1])

    def test_refresh_hook_uses_real_post_clear_position_and_preserves_scan_obligations(self):
        api, solver = self.certificate_fixture({'discovery_route': 'refresh_after_localize'})
        nodes = np.array([[0., 0.], [100., 0.], [200., 0.]])
        calls = []

        def checked_refresh(remaining, current):
            self.assertEqual(solver.cleared, {7})
            self.assertNotIn(7, solver.tracks)
            np.testing.assert_array_equal(current, [30., 0.])
            calls.append(Counter(map(tuple, remaining)))
            return refresh_remaining_route(remaining, current)

        with patch('solver.coverage', return_value=nodes), \
                patch('discovery.refresh_remaining_route', side_effect=checked_refresh):
            solver.run()
        self.assertEqual(calls, [Counter(map(tuple, nodes))])
        measures = [a for a in api.log if a['path'] == '/measure']
        actual = Counter((tuple(a['position']), a['channel']) for a in measures)
        expected = Counter((tuple(p), c) for p in nodes for c in range(1, 21) if c != 7)
        self.assertEqual(actual, expected)
        self.assertEqual(solver.clearance_point, 'mec_center')

    def test_unknown_hook_keeps_every_uncleared_channel_and_skips_newly_cleared(self):
        # Isolate run()'s scheduling loop: measurement inference is covered by
        # existing engine/geometry tests, and must not mask a missing obligation.
        class RecordingAPI:
            def __init__(self):
                self.position, self.channel, self.virtual_time = np.zeros(2), 5, 0.

            def action(self, path):
                return {}

        class SweepProbe(Solver):
            def __init__(self):
                super().__init__(RecordingAPI(), True, 'P4', diagnostic={'discovery_channels': 'unknown_first'})
                far = np.array([[100000., 0.], [100002., 0.], [100001., 2.]])
                self.tracks = {2: {'poly': far}, 7: {'poly': far}}
                self.cleared = {3}
                self.measured = []

            def measure(self, c, p):
                self.measured.append((tuple(p), c))
                self.api.position, self.api.channel = p.copy(), c
                if c == 6:
                    self.cleared.add(c)  # An immediate near clear within the first sweep.

            def localize(self, c, one_step=False):
                self.tracks.pop(c)
                self.cleared.add(c)

        solver = SweepProbe()
        nodes = np.array([[0., 0.], [10., 0.], [20., 0.]])
        with patch('solver.coverage', return_value=nodes):
            solver.run()
        batches = [[c for p, c in solver.measured if p == tuple(node)] for node in nodes]
        self.assertEqual(batches[0][0], 5)
        self.assertEqual(batches[0][-2:], [2, 7])
        self.assertEqual(batches[1][0], 7)  # Known current channel retains priority.
        for index, batch in enumerate(batches):
            self.assertEqual(len(batch), len(set(batch)))
            self.assertEqual(set(batch), set(range(1, 21))-({3} if index == 0 else {3, 6}))
            self.assertTrue({2, 7}.issubset(batch))  # Known, uncleared sources are not pruned.


if __name__ == '__main__':
    unittest.main()
