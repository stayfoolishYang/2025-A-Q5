"""Segment-entry geometry and fixed-next-waypoint guarantees, without scenarios."""
import json
import math
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import numpy as np
from scipy.optimize import brentq

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))
from geometry import (exact_squared_distance, is_certified_clear_point, mec,
                      nearest_certified_clear_point, segment_certified_clear_point)


class SegmentCertifiedTests(unittest.TestCase):
    def assert_safe(self, poly, current, center, radius, result):
        point, meta = result
        parsed = np.asarray(json.loads(json.dumps(point.tolist(), allow_nan=False)))
        np.testing.assert_array_equal(point, parsed)
        self.assertTrue(is_certified_clear_point(poly, parsed, radius))
        self.assertLessEqual(np.linalg.norm(point-current), np.linalg.norm(center-current))
        self.assertLessEqual(exact_squared_distance(point, current), exact_squared_distance(center, current))
        self.assertLessEqual(meta['max_vertex_distance'], radius)
        self.assertGreaterEqual(meta['segment_parameter_from_current'], 0.)
        self.assertLessEqual(meta['segment_parameter_from_current'], 1.)

    def test_analytic_lens_and_already_safe(self):
        poly, center = np.array([[-3., 0.], [3., 0.]]), np.zeros(2)
        current = np.array([0., 15.])
        result = segment_certified_clear_point(poly, current, 5., center, 3.)
        np.testing.assert_allclose(result[0], [0., 4.], rtol=0, atol=1e-12)
        self.assertEqual(result[1]['mode'], 'segment_entry')
        self.assert_safe(poly, current, center, 5., result)
        current = np.array([0., 1.])
        result = segment_certified_clear_point(poly, current, 5., center, 3.)
        np.testing.assert_array_equal(result[0], current)
        self.assertEqual(result[1]['mode'], 'already_certified')

    def test_tangent_tiny_lens_single_point_and_zero_radius(self):
        radius = 19.999
        for half in (radius, np.nextafter(radius, 0.), radius-1e-8):
            poly, current, center = np.array([[-half, 0.], [half, 0.]]), np.array([0., 60.]), np.zeros(2)
            result = segment_certified_clear_point(poly, current, radius, center, half)
            self.assert_safe(poly, current, center, radius, result)
            if half == radius:
                np.testing.assert_array_equal(result[0], center)
                self.assertTrue(result[1]['fallback'])
        poly, current, center = np.array([[3., 4.], [3., 4.]]), np.array([100., 80.]), np.array([3., 4.])
        for radius in (0., 19.999):
            result = segment_certified_clear_point(poly, current, radius, center, 0.)
            self.assert_safe(poly, current, center, radius, result)

    def test_boundary_and_unresolved_quadratic_never_relax_radius(self):
        radius, poly, center = 19.999, np.array([[0., 0.]]), np.zeros(2)
        for coordinate in (np.nextafter(radius, 0.), radius, np.nextafter(radius, np.inf), radius+1e-10):
            current = np.array([coordinate, 0.])
            result = segment_certified_clear_point(poly, current, radius, center, 0.)
            self.assert_safe(poly, current, center, radius, result)
            self.assertEqual(result[1]['mode'] == 'already_certified', coordinate <= radius)
        poly, current = np.array([[-3., 0.], [3., 0.]]), np.array([0., 15.])
        with patch('geometry.math.sqrt', return_value=float('nan')):
            result = segment_certified_clear_point(poly, current, 5., center, 3.)
        self.assertTrue(result[1]['fallback'])
        self.assert_safe(poly, current, center, 5., result)

    def test_invalid_witness_is_rejected(self):
        for poly, center, radius in (([], [0., 0.], 0.), ([[np.nan, 0.]], [0., 0.], 0.),
                                     ([[0., 0.]], [100., 0.], 1.)):
            with self.assertRaises(ValueError):
                segment_certified_clear_point(poly, [20., 30.], 19.999, center, radius)

    def test_given_two_leg_counterexample_and_segment_nonworsening(self):
        radius = 19.999
        poly = radius*np.array([[-.5, 0.], [.5, 0.], [0., .25]])
        current, center = radius*np.array([39.5, 30.]), np.zeros(2)
        next_point = -radius*np.array([.3, .6])
        nccp = nearest_certified_clear_point(poly, current, radius, center, radius/2)
        segment = segment_certified_clear_point(poly, current, radius, center, radius/2)
        self.assert_safe(poly, current, center, radius, segment)
        np.testing.assert_allclose(nccp[0], radius*np.array([.3, .6]), rtol=0, atol=1e-9)
        route = lambda point: np.linalg.norm(current-point)+np.linalg.norm(point-next_point)
        self.assertLess(np.linalg.norm(nccp[0]-current), np.linalg.norm(center-current))
        self.assertGreater(route(nccp[0]), route(center)+1.)
        self.assertAlmostEqual(route(nccp[0])-route(center), 1.398193, delta=1e-6)
        # This epsilon concerns FP64 path addition/collinearity, not clearance.
        self.assertLessEqual(route(segment[0]), route(center)+1e-10)
        self.assertLessEqual(np.linalg.norm(poly-current, axis=1).max(), 1000.)

    def test_random_small_sets_against_independent_scalar_root(self):
        rng = np.random.default_rng(392)
        for _ in range(30):
            center = rng.uniform(-1000., 1000., 2)
            angles = np.arange(6)*np.pi/3
            poly = center+rng.uniform(2., 15.)*np.c_[np.cos(angles), np.sin(angles)]
            center, bound = mec(poly)
            radius = 19.999
            current = center+rng.uniform(100., 1500.)*np.array([math.cos(angles[0]+.3), math.sin(angles[0]+.3)])
            result = segment_certified_clear_point(poly, current, radius, center, bound)
            self.assert_safe(poly, current, center, radius, result)
            residual = lambda t: np.linalg.norm(poly-(current+t*(center-current)), axis=1).max()-radius
            t = brentq(residual, 0., 1., xtol=1e-14)
            oracle = current+t*(center-current)
            self.assertLess(np.linalg.norm(result[0]-oracle), 1e-8)
            for following in (center, center+[0., 100.], center+[-100., 20.], current):
                baseline = np.linalg.norm(current-center)+np.linalg.norm(center-following)
                actual = np.linalg.norm(current-result[0])+np.linalg.norm(result[0]-following)
                self.assertLessEqual(actual, baseline+1e-9)

    def test_segment_configs_change_only_name_and_selector(self):
        for stem in ('q3_p3_grid_v1', 'q4_p4_diag_v1_grid_v1'):
            nccp = json.loads((BASE/'configs'/f'{stem}_nccp.yaml').read_text())
            segment = json.loads((BASE/'configs'/f'{stem}_segment_entry.yaml').read_text())
            self.assertEqual({k for k in set(nccp)|set(segment) if nccp.get(k) != segment.get(k)},
                             {'name', 'clearance_point'})
            self.assertEqual(segment['clearance_point'], 'segment_entry')


if __name__ == '__main__':
    unittest.main()
