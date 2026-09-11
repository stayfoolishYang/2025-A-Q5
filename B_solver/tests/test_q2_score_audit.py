"""Small Q2 scoring fixtures; no full candidate sweep or simulator instance."""
import itertools
import math
import os
from pathlib import Path
import sys
import unittest

import numpy as np

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE/'experiments'))
sys.path.insert(0, os.environ.get('JAMMERS_SIM_ROOT', 'G:/QQ/jammers_linux'))
from engine import quantize_bearing
from q2_score_audit import (ERROR_DEG, continuous_envelope, initial_compatible,
                            pair_diameter, response, source_grid, wedge)


class Q2ScoreAuditTests(unittest.TestCase):
    def test_pair_diameter_degenerate_and_triangle(self):
        self.assertEqual(pair_diameter(np.empty((0, 2))), 0.)
        self.assertEqual(pair_diameter(np.array([[7., -2.]])), 0.)
        self.assertEqual(pair_diameter(np.array([[0., 0.], [1., 0.], [3., 0.]])), 3.)
        triangle = np.array([[0., 0.], [3., 0.], [0., 4.]])
        self.assertEqual(pair_diameter(triangle), 5.)

    def test_near_and_coverage_boundaries_do_not_make_bearings(self):
        def forbidden(*args):
            self.fail('Non-direction response must not quantize a bearing')

        for radius in (0., math.nextafter(5., 0.), 5.):
            with self.subTest(radius=radius):
                self.assertEqual(response([radius, 0.], np.zeros(2), 0., forbidden), ('near', None))
        self.assertEqual(response([math.nextafter(5., math.inf), 0.], np.zeros(2), 0., quantize_bearing),
                         ('direction', 0.))
        self.assertEqual(response([1500., 0.], np.zeros(2), 0., quantize_bearing), ('direction', 0.))
        self.assertEqual(response([math.nextafter(1500., math.inf), 0.], np.zeros(2), 0., forbidden),
                         ('no_signal', None))

    def test_report_and_wedge_wrap_at_zero(self):
        point = [100*math.cos(math.radians(-.01)), 100*math.sin(math.radians(-.01))]
        self.assertEqual(response(point, np.zeros(2), 0., quantize_bearing), ('direction', 359.99))
        self.assertEqual(quantize_bearing(359.99, .02), .01)
        poly = np.array([[10., -4.], [30., -4.], [30., 4.], [10., 4.]])
        posts = [wedge(poly, np.zeros(2), z) for z in (-.01, 359.99, 719.99)]
        for post in posts[1:]:
            np.testing.assert_allclose(post, posts[0], atol=1e-11, rtol=0.)

    def test_expanded_wedge_contains_endpoints_and_children_across_wrap(self):
        poly = np.array([[10., -4.], [30., -4.], [30., 4.], [10., 4.]])
        station, center, half = np.zeros(2), 359.8, .6
        parent = wedge(poly, station, center, ERROR_DEG+half)
        parent_diameter = pair_diameter(parent)
        for z, error in ((center-half, ERROR_DEG), (center, ERROR_DEG),
                         (center+half, ERROR_DEG), (center-half/2, ERROR_DEG+half/2),
                         (center+half/2, ERROR_DEG+half/2)):
            post = wedge(poly, station, z, error)
            # Independent polar containment avoids reproducing clipping inequalities.
            for point in post:
                angle = math.degrees(math.atan2(point[1], point[0]))
                separation = abs((angle-center+180)%360-180)
                self.assertLessEqual(separation, ERROR_DEG+half+1e-10)
            self.assertLessEqual(pair_diameter(post), parent_diameter+1e-8)

    def test_continuous_envelope_contains_independent_dense_angle_scan(self):
        poly = np.array([[10., -4.], [20., -4.], [20., 6.], [10., 6.]])
        evaluate = lambda z, e: pair_diameter(wedge(poly, np.zeros(2), z, e))
        result = continuous_envelope(evaluate, tolerance=.02, max_splits=5000)
        self.assertTrue(result['converged'], result)
        self.assertLessEqual(result['gap_m'], .02)
        # Uniform dense angles and stdlib all-pairs distance are independent of
        # the adaptive heap and its diameter helper. This is a fixture, not Q2's 213 points.
        dense = 0.
        for z in np.linspace(0., 360., 7201):
            post = wedge(poly, np.zeros(2), z, ERROR_DEG)
            dense = max(dense, max((math.dist(a, b) for a, b in itertools.combinations(post, 2)), default=0.))
        self.assertGreater(dense, 5.)
        self.assertLessEqual(dense, result['upper_m']+1e-8)
        self.assertLessEqual(result['lower_m'], dense+.02)
        leaves = result['leaves']
        self.assertEqual(leaves[0][0], 0.)
        self.assertEqual(leaves[-1][1], 360.)
        self.assertTrue(all(a[1] == b[0] for a, b in zip(leaves, leaves[1:])))
        self.assertLessEqual(result['nesting_residual_m'], 1e-6)

    def test_envelope_budget_and_overwide_initial_cells(self):
        poly = np.array([[10., -4.], [20., -4.], [20., 6.], [10., 6.]])
        evaluate = lambda z, e: pair_diameter(wedge(poly, np.zeros(2), z, e))
        result = continuous_envelope(evaluate, tolerance=1e-12, max_splits=0, initial_bins=8)
        self.assertFalse(result['converged'])
        self.assertEqual(result['splits'], 0)
        self.assertEqual(len(result['leaves']), 8)
        self.assertGreater(result['gap_m'], 0.)
        for bins in (0, 1, 2):
            with self.subTest(bins=bins), self.assertRaises(ValueError):
                continuous_envelope(lambda *_: self.fail('Must reject before evaluation'), initial_bins=bins)

    def test_source_grids_are_nested_and_initial_observation_compatible(self):
        coarse, fine = source_grid(9, 17), source_grid(17, 33)
        np.testing.assert_array_equal(coarse, fine.reshape(17, 33, 2)[::2, ::2].reshape(-1, 2))
        self.assertEqual(coarse.shape, (153, 2))
        self.assertEqual(fine.shape, (561, 2))
        bad = [i for i, p in enumerate(fine) if not initial_compatible(p, quantize_bearing)]
        self.assertEqual(bad, [], 'Frozen grid points must admit the first direction=30 response')
        ray = np.array([math.cos(math.radians(30)), math.sin(math.radians(30))])
        self.assertFalse(initial_compatible(np.zeros(2), quantize_bearing))
        self.assertFalse(initial_compatible(5*ray, quantize_bearing))
        self.assertTrue(initial_compatible(6*ray, quantize_bearing))
        self.assertFalse(initial_compatible(1501*ray, quantize_bearing))
        self.assertFalse(initial_compatible(np.array([100., 0.]), quantize_bearing))


if __name__ == '__main__':
    unittest.main()
