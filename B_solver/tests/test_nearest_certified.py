"""Analytic and independent optimisation checks for nearest certified clearance."""
from fractions import Fraction
from pathlib import Path
import sys
import unittest

import numpy as np
from scipy.optimize import minimize
from scipy.spatial import ConvexHull

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from geometry import mec, nearest_certified_clear_point


class NearestCertifiedTests(unittest.TestCase):
    def assert_certificate(self, poly, current, center, radius, result):
        point, meta = result
        poly = np.asarray(poly, dtype=float)
        self.assertLessEqual(float(np.linalg.norm(poly-point, axis=1).max()), radius)
        self.assertLessEqual(float(np.linalg.norm(point-current)), float(np.linalg.norm(center-current)))
        exact_radius_squared = Fraction(float(radius))**2
        for vertex in poly:
            exact_distance_squared = sum((Fraction(float(x))-Fraction(float(y)))**2
                                         for x, y in zip(point, vertex))
            self.assertLessEqual(exact_distance_squared, exact_radius_squared)
        self.assertEqual(meta['max_vertex_distance'], float(np.linalg.norm(poly-point, axis=1).max()))
        self.assertEqual(meta['distance_to_current'], float(np.linalg.norm(point-current)))

    def test_single_disk_analytic_projection(self):
        poly = np.array([[3., -4.]])
        current = np.array([3., 10.])
        result = nearest_certified_clear_point(poly, current, 5., poly[0], 0.)
        np.testing.assert_array_equal(result[0], [3., 1.])
        self.assertEqual(result[1]['mode'], 'radial_projection')
        self.assertEqual(result[1]['distance_to_current'], 9.)
        self.assert_certificate(poly, current, poly[0], 5., result)

    def test_two_circle_lens_analytic_projection(self):
        poly = np.array([[-3., 0.], [3., 0.]])
        current = np.array([0., 15.])
        result = nearest_certified_clear_point(poly, current, 5., np.zeros(2), 3.)
        np.testing.assert_array_equal(result[0], [0., 4.])
        self.assertEqual(result[1]['mode'], 'circle_intersection')
        self.assert_certificate(poly, current, np.zeros(2), 5., result)

    def test_zero_movement_when_current_is_certified(self):
        poly = np.array([[-3., 0.], [3., 0.], [0., 2.]])
        current = np.array([0., 1.])
        result = nearest_certified_clear_point(poly, current, 5., np.zeros(2), 3.)
        np.testing.assert_array_equal(result[0], current)
        self.assertEqual(result[1]['mode'], 'already_certified')
        self.assertEqual(result[1]['distance_to_current'], 0.)
        self.assert_certificate(poly, current, np.zeros(2), 5., result)

    def test_duplicate_and_reordered_vertices_do_not_change_projection(self):
        poly = np.array([[-10., 0.], [10., 0.], [0., 8.]])
        current = np.array([4., 40.])
        center, r = mec(poly)
        expected = nearest_certified_clear_point(poly, current, 19.999, center, r)
        for points in (poly[::-1], np.roll(poly, 1, axis=0), np.vstack((poly, poly[[0, 1, 1]]))):
            result = nearest_certified_clear_point(points, current, 19.999, center, r)
            np.testing.assert_array_equal(result[0], expected[0])
            self.assertEqual(result[1], expected[1])
            self.assert_certificate(points, current, center, 19.999, result)

    def test_tangent_disks_and_zero_radius(self):
        radius = 19.999
        poly = np.array([[-radius, 0.], [radius, 0.]])
        current = np.array([50., 20.])
        result = nearest_certified_clear_point(poly, current, radius, np.zeros(2), radius)
        np.testing.assert_array_equal(result[0], np.zeros(2))
        self.assertTrue(result[1]['fallback'])
        self.assert_certificate(poly, current, np.zeros(2), radius, result)
        poly = np.array([[3., 4.], [3., 4.]])
        result = nearest_certified_clear_point(poly, current, 0., poly[0], 0.)
        np.testing.assert_array_equal(result[0], poly[0])
        self.assert_certificate(poly, current, poly[0], 0., result)

    def test_one_ulp_outside_is_never_certified_with_tolerance(self):
        radius = 19.999
        poly = np.array([[0., 0.]])
        current = np.array([np.nextafter(radius, np.inf), 0.])
        result = nearest_certified_clear_point(poly, current, radius, np.zeros(2), 0.)
        self.assertNotEqual(result[1]['mode'], 'already_certified')
        self.assertGreater(result[1]['distance_to_current'], 0.)
        self.assert_certificate(poly, current, np.zeros(2), radius, result)

    def test_squared_distance_catches_outside_point_whose_norm_rounds_down(self):
        poly = np.array([[0., 0.]])
        current = np.array([1., 2.**-27])
        self.assertEqual(np.linalg.norm(current), 1.)
        # The ordinary rounded norm equals the radius, while 1 + 2**-54 > 1.
        result = nearest_certified_clear_point(poly, current, 1., np.zeros(2), 0.)
        self.assertNotEqual(result[1]['mode'], 'already_certified')
        self.assertGreater(result[1]['numerical_adjustment_m'], 0.)
        self.assert_certificate(poly, current, np.zeros(2), 1., result)

    def test_small_radius_and_invalid_certificates_fail_explicitly(self):
        cases = [
            (np.empty((0, 2)), np.zeros(2), 2., np.zeros(2), 0.),
            (np.array([[-1., 0.], [1., 0.]]), np.zeros(2), .999, np.zeros(2), 1.),
            (np.array([[-1., 0.], [1., 0.]]), np.zeros(2), 2., np.zeros(2), .5),
            (np.array([[np.nan, 0.]]), np.zeros(2), 2., np.zeros(2), 0.),
            (np.array([[0., 0.]]), np.zeros(2), 2., np.zeros(2), -1.),
            (np.array([[0., 0.]]), np.zeros(2), 2., np.array([3., 0.]), 2.),
        ]
        for args in cases:
            with self.assertRaises(ValueError):
                nearest_certified_clear_point(*args)
        with self.assertRaises(ValueError):
            nearest_certified_clear_point([[0., 0.]], [0., 0.], mec_center=[0., 0.])

    def test_random_convex_polygons_match_independent_slsqp(self):
        rng = np.random.default_rng(20260911)
        for _ in range(40):
            raw = rng.uniform(-8., 8., (10, 2)) + rng.uniform(-50., 50., 2)
            poly = raw[ConvexHull(raw).vertices]
            center, r = mec(poly)
            radius = max(12., r+1.)
            angle = rng.uniform(-np.pi, np.pi)
            current = center+rng.uniform(30., 100.)*np.array([np.cos(angle), np.sin(angle)])
            result = nearest_certified_clear_point(poly, current, radius, center, r)
            self.assert_certificate(poly, current, center, radius, result)
            # Independent constrained optimisation: no circle intersection or
            # radial candidate construction is used by this oracle.
            oracle = minimize(
                lambda q: .5*float((q-current)@(q-current)), center,
                jac=lambda q: q-current, method='SLSQP',
                constraints=[{'type': 'ineq',
                              'fun': lambda q: radius**2-np.sum((q-poly)**2, axis=1),
                              'jac': lambda q: -2*(q-poly)}],
                options={'ftol': 1e-10, 'maxiter': 500})
            self.assertLessEqual(float(np.linalg.norm(poly-oracle.x, axis=1).max()), radius+1e-7)
            self.assertAlmostEqual(result[1]['distance_to_current'],
                                   float(np.linalg.norm(oracle.x-current)), delta=1e-6)

    def test_automatic_mec_and_narrow_lens_remain_certified(self):
        poly = np.array([[-2., 0.], [2., 0.], [0., 1.]])
        current = np.array([20., 20.])
        center, _ = mec(poly)
        result = nearest_certified_clear_point(poly, current)
        self.assert_certificate(poly, current, center, 19.999, result)
        radius = 19.999
        half_distance = np.nextafter(radius, 0.)
        poly = np.array([[-half_distance, 0.], [half_distance, 0.]])
        result = nearest_certified_clear_point(poly, current, radius, np.zeros(2), half_distance)
        self.assert_certificate(poly, current, np.zeros(2), radius, result)


if __name__ == '__main__':
    unittest.main()
