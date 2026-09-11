"""Focused D2 checks using fixed geometry and an in-memory observation interface."""
from collections import Counter
import hashlib
import json
from pathlib import Path
import pickle
import sys
import unittest
from unittest.mock import patch

import numpy as np

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))

from discovery import refresh_remaining_route, workload_remaining_route
from geometry import coverage, route
from particles import Hypotheses
from solver import Solver


def tracks_with(particles, channel=7):
    hyp = Hypotheses(seed=123, count=32)
    hyp.p = np.asarray(particles, dtype=float).reshape(-1, 5).copy()
    hyp.history = [(np.array([-2000., -2000.]), 'no_signal', None)]
    return {channel: dict(hyp=hyp, poly=np.array([[-1700., -100.], [1700., -100.], [0., 1700.]]),
                          n=1, negatives=0, views=[np.array([-2000., -2000.])])}


class RecordingAPI:
    """No engine, HTTP, file output or hidden-source interface."""
    def __init__(self):
        self.position = np.zeros(2)
        self.channel, self.virtual_time, self.calls = 1, 0., []

    def action(self, path, position=None, channel=None):
        result = {'accepted': True}
        if position is not None:
            point = np.asarray(position, dtype=float)
            self.virtual_time += float(np.linalg.norm(point-self.position))/5
            if path == '/measure':
                self.virtual_time += 5+int(channel != self.channel)
                self.channel = channel
                result['measure_result'] = 'no_signal'
            elif path == '/clear':
                self.virtual_time += 5
                result['clear_result'] = 'success'
            self.position = point.copy()
        result['virtual_time_s'] = self.virtual_time
        self.calls.append(dict(path=path, position=None if position is None else self.position.tolist(),
                               channel=channel, response=result.copy()))
        return result


class WorkloadDiscoveryTests(unittest.TestCase):
    def test_first_hit_itself_costs_six_and_last_hit_equals_never_cost(self):
        nodes = np.array([[0., 0.], [1000., 0.], [2000., 0.]])
        samples = [([-100., 0., 0., 1100., 1.], [1, 0, 0, 0], 6.),
                   ([1500., 0., 0., 1000., 1.], [0, 0, 1, 0], 18.),
                   ([0., -1500., -np.pi/2, 1000., 1.], [0, 0, 0, 1], 18.)]
        for particle, histogram, expected in samples:
            with self.subTest(histogram=histogram), patch('discovery.route', return_value=nodes.copy()):
                _, event = workload_remaining_route(nodes, np.zeros(2), tracks_with([particle]))
            self.assertEqual(event['supports'][0]['first_hit_counts'], [histogram, histogram])
            self.assertEqual(event['workload_s'], [expected, expected])

    def test_repeated_support_preserves_cross_node_correlation_and_never_mass(self):
        nodes = np.array([[0., 0.], [1000., 0.], [2000., 0.]])
        particles = [[-100., 0., 0., 1100., 1.], [1500., 0., 0., 1000., 1.],
                     [0., -1500., -np.pi/2, 1000., 1.]]
        with patch('discovery.route', return_value=nodes.copy()):
            _, correlated = workload_remaining_route(nodes, np.zeros(2), tracks_with(particles[:2]))
            _, with_never = workload_remaining_route(nodes, np.zeros(2), tracks_with(particles))
        # First two nodes both support particle 0. Independent q=1/2 would
        # incorrectly charge 6*(1+1/2+1/4)=10.5 rather than 12 seconds.
        self.assertEqual(correlated['supports'][0]['first_hit_counts'][0], [1, 0, 1, 0])
        self.assertEqual(correlated['workload_s'], [12., 12.])
        self.assertEqual(with_never['supports'][0]['first_hit_counts'][0], [1, 0, 1, 1])
        self.assertEqual(with_never['workload_s'], [14., 14.])

    def test_all_existing_particles_contribute_without_a_1024_sample_cap(self):
        nodes = np.array([[0., 0.], [1000., 0.], [2000., 0.]])
        never = [0., -1500., -np.pi/2, 1000., 1.]
        particles = np.vstack((np.tile(never, (2048, 1)), [-100., 0., 0., 1100., 1.]))
        with patch('discovery.route', return_value=nodes.copy()):
            _, event = workload_remaining_route(nodes, np.zeros(2), tracks_with(particles))
        support = event['supports'][0]
        self.assertEqual(support['particle_count'], 2049)
        self.assertEqual(support['first_hit_counts'][0], [1, 0, 0, 2048])
        self.assertAlmostEqual(event['workload_s'][0], 6*(1+2048*3)/2049)
        self.assertEqual(support['particle_sha256'], hashlib.sha256(particles.tobytes()).hexdigest())

    def test_no_hypotheses_or_constant_workload_returns_exact_d1_choice(self):
        cached = np.array([[2., 0.], [0., 0.], [1., 0.]])
        candidate = np.array([[0., 0.], [1., 0.], [2., 0.]])
        cases = [{}, {1: {'hyp': None}}, tracks_with([]), tracks_with([[0., 0., 0., 1500., 0.]])]
        for tracks in cases:
            with self.subTest(tracks=len(tracks)), patch('discovery.route', return_value=candidate.copy()):
                d1 = refresh_remaining_route(cached, np.array([-1., 0.]))
                d2, event = workload_remaining_route(cached, np.array([-1., 0.]), tracks)
            np.testing.assert_array_equal(d2, d1)
            self.assertEqual(event['workload_s'][0], event['workload_s'][1])
            self.assertEqual(event['selected_choice'], event['distance_choice'])
            if not tracks or next(iter(tracks.values()))['hyp'] is None:
                self.assertEqual(event['supports'], [])

    def test_longer_route_requires_strictly_enough_workload_credit(self):
        # A west-facing absence/east-facing signal: the long route reaches B
        # first and saves one surrogate scan, worth 6 s (not an actual clear).
        for gap, accept_long in ((1., True), (30., False), (100., False)):
            short = np.array([[0., 0.], [gap, 0.]])
            long = short[::-1].copy()
            tracks = tracks_with([[gap/2, 0., 0., 1000., 1.]])
            for cached, candidate, expected_index in ((long, short, 0 if accept_long else 1),
                                                        (short, long, 1 if accept_long else 0)):
                with self.subTest(gap=gap, cached=cached.tolist()), patch('discovery.route', return_value=candidate):
                    chosen, event = workload_remaining_route(cached, np.array([-1., 0.]), tracks)
                np.testing.assert_array_equal(chosen, long if accept_long else short)
                self.assertEqual(event['selected_choice'], expected_index)
                if accept_long:
                    self.assertNotEqual(event['selected_choice'], event['distance_choice'])
                    self.assertLess(event['score_s'][expected_index], event['score_s'][event['distance_choice']])
                else:
                    self.assertEqual(event['selected_choice'], event['distance_choice'])

    def test_constant_workload_preserves_d1_distance_tolerance_in_metres(self):
        cached = np.array([[1., 0.], [0., 0.]])
        refreshed = cached[::-1].copy()
        tracks = tracks_with([[0., 0., 0., 1000., 0.]])
        # Complete-path improvements straddle the old 1e-8 metre threshold;
        # applying that threshold after division by speed would change D1.
        for shift, expected in ((4e-9, 0), (6e-9, 1)):
            current = np.array([0.5-shift, 0.])
            with self.subTest(shift=shift), patch('discovery.route', return_value=refreshed):
                d1 = refresh_remaining_route(cached, current)
                d2, event = workload_remaining_route(cached, current, tracks)
            self.assertEqual(event['distance_choice'], expected)
            self.assertEqual(event['selected_choice'], expected)
            np.testing.assert_array_equal(d2, d1)

    def test_empty_route_and_identical_candidates(self):
        with patch('discovery.route', side_effect=AssertionError('No empty route optimization')):
            self.assertEqual(workload_remaining_route([], np.zeros(2), {}), ([], None))
        nodes = np.array([[700., 0.]])
        with patch('discovery.route', return_value=nodes.copy()):
            chosen, event = workload_remaining_route(nodes, np.zeros(2), tracks_with([[0., 0., 0., 1000., 0.]]))
        np.testing.assert_array_equal(chosen, nodes)
        self.assertEqual(event['selected_choice'], 0)
        self.assertEqual(event['workload_s'], [6., 6.])

    def test_preserves_all_45_nodes_and_does_not_touch_particles_history_or_rng(self):
        nodes = route(coverage(True), np.zeros(2))
        current = np.array([1740., -480.])
        tracks = tracks_with([[-100., 0., 0., 1100., 1.], [1500., 0., 0., 1000., 1.]])
        hyp = tracks[7]['hyp']
        for value in (nodes, current, hyp.p, tracks[7]['poly']):
            value.setflags(write=False)
        before = pickle.dumps((nodes, current, tracks))
        with patch.object(hyp, 'update', side_effect=AssertionError('Planner must not update hypotheses')):
            chosen, event = workload_remaining_route(nodes, current, tracks)
        self.assertEqual(before, pickle.dumps((nodes, current, tracks)))
        self.assertEqual(len(chosen), 45)
        self.assertEqual(Counter(map(tuple, chosen)), Counter(map(tuple, nodes)))
        self.assertEqual(event['start'], current.tolist())
        self.assertEqual(sorted(event['refreshed_order']), list(range(45)))

    def certificate_fixture(self, config):
        api = RecordingAPI()
        solver = Solver(api, True, 'P4', diagnostic=config)
        solver.tracks[7] = dict(poly=np.array([[29., -1.], [31., -1.], [31., 1.], [29., 1.]]),
                                n=2, negatives=0, views=[], hyp=None)
        return api, solver

    def test_q4_only_and_config_keeps_mec_diagnostic_and_channel_rules(self):
        baseline = json.loads((BASE/'configs/q4_p4_diag_v1_grid_v1.yaml').read_text())
        config = json.loads((BASE/'configs/q4_p4_diag_v1_grid_v1_workload.yaml').read_text())
        strip = lambda c: {k:v for k,v in c.items() if k not in ('name','discovery_route','discovery_channels')}
        self.assertEqual(strip(config), strip(baseline))
        self.assertEqual(config['discovery_channels'], 'legacy')
        solver = Solver(None, True, 'P4', diagnostic=config)
        self.assertEqual(solver.clearance_point, 'mec_center')
        for mixed, policy in ((False, 'P3'), (True, 'P3'), (True, 'P2'), (False, 'P4')):
            with self.subTest(mixed=mixed, policy=policy), self.assertRaises(ValueError):
                Solver(None, mixed, policy, diagnostic=config)

    def test_d0_and_d1_never_invoke_d2_or_create_d2_event_logs(self):
        results = []
        nodes = np.array([[0., 0.], [100., 0.], [200., 0.]])
        for config in ({}, {'discovery_route':'legacy'}, {'discovery_route':'refresh_after_localize'}):
            api, solver = self.certificate_fixture(config)
            with patch('solver.coverage', return_value=nodes), \
                    patch('discovery.workload_remaining_route', side_effect=AssertionError('D2 hook entered legacy/D1')):
                solver.run()
            self.assertTrue(all('discovery_refresh_events' not in v for v in solver.trace.values()))
            results.append((api.calls, solver.trace, api.virtual_time))
        self.assertEqual(results[0], results[1])

    def test_hook_reads_actual_post_clear_state_and_preserves_every_scan(self):
        api, solver = self.certificate_fixture({'discovery_route':'workload_after_localize'})
        nodes = coverage(True)
        calls = []

        def checked(remaining, current, tracks):
            self.assertEqual(solver.cleared, {7})
            self.assertIs(tracks, solver.tracks)
            self.assertNotIn(7, tracks)
            np.testing.assert_array_equal(current, [30., 0.])
            calls.append(Counter(map(tuple, remaining)))
            return workload_remaining_route(remaining, current, tracks)

        with patch('solver.coverage', return_value=nodes), patch('discovery.workload_remaining_route', side_effect=checked):
            solver.run()
        self.assertEqual(calls, [Counter(map(tuple, nodes))])
        measured = Counter((tuple(a['position']), a['channel']) for a in api.calls if a['path']=='/measure')
        expected = Counter((tuple(p), c) for p in nodes for c in range(1,21) if c != 7)
        self.assertEqual(measured, expected)
        events = solver.trace[7]['discovery_refresh_events']
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]['start'], [30., 0.])
        self.assertEqual(events[0]['supports'], [])
        self.assertEqual(solver.clearance_point, 'mec_center')


if __name__ == '__main__':
    unittest.main()
