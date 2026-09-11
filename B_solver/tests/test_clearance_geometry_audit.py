"""New Q1/Jung and NCCP boundary requirements; no full solver run is performed."""
from fractions import Fraction
import math
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'experiments'))
from clearance_geometry_audit import (audit_clearance_geometry,
                                      diameter_circle_audit,
                                      jung_classification)
from geometry import mec, nearest_certified_clear_point


class ClearanceGeometryAuditTests(unittest.TestCase):
    def assert_strict_clearance(self, vertices, current, center, radius, result):
        point, meta = result
        self.assertTrue(np.isfinite(point).all())
        self.assertLessEqual(np.linalg.norm(np.asarray(vertices)-point, axis=1).max(), radius)
        self.assertLessEqual(np.linalg.norm(point-current), np.linalg.norm(center-current))
        for vertex in vertices:
            squared = sum((Fraction(float(x))-Fraction(float(y)))**2 for x, y in zip(point, vertex))
            self.assertLessEqual(squared, Fraction(float(radius))**2)
        self.assertLessEqual(meta['max_vertex_distance'], radius)

    def test_equilateral_triangle_is_diameter_40_counterexample(self):
        poly = np.array([[0., 0.], [40., 0.], [20., 20*math.sqrt(3)]])
        audit = audit_clearance_geometry(poly, safe_radius=20.)
        self.assertAlmostEqual(audit['diameter_circle']['diameter_m'], 40.)
        self.assertFalse(audit['diameter_circle']['diameter_circle_covers_vertices'])
        self.assertEqual(len(audit['diameter_circle']['outside_vertices']), 1)
        self.assertEqual(audit['jung']['classification'], 'INCONCLUSIVE_DIAMETER_INTERVAL')
        center, radius = mec(poly)
        self.assertAlmostEqual(radius-1e-8, 40/math.sqrt(3), places=11)
        self.assertGreater(radius, 20.)
        with self.assertRaises(ValueError):
            nearest_certified_clear_point(poly, np.zeros(2), 20., center, radius)

    def test_thin_rhombus_is_covered_by_its_diameter_circle(self):
        poly = np.array([[-20., 0.], [0., -1e-6], [20., 0.], [0., 1e-6]])
        audit = audit_clearance_geometry(poly, safe_radius=20.)
        self.assertEqual(audit['diameter_circle']['diameter_m'], 40.)
        self.assertTrue(audit['diameter_circle']['diameter_circle_covers_vertices'])
        self.assertTrue(audit['diameter_circle']['diameter_circle_is_mec'])
        np.testing.assert_array_equal(audit['diameter_circle']['diameter_circle_center_fp64'], [0., 0.])
        self.assertEqual(audit['diameter_circle']['outside_vertices'], [])
        # Same diameter interval as the equilateral example, opposite existence.
        self.assertIsNone(audit['jung']['certified_region_existence_from_diameter'])

    def test_jung_thresholds_use_squared_exact_comparisons(self):
        low = math.sqrt(3.)  # This binary64 value is just below exact sqrt(3).
        high = np.nextafter(low, np.inf)
        self.assertEqual(jung_classification([[0., 0.], [low, 0.]], 1.)['classification'],
                         'GUARANTEED_NONEMPTY_BY_JUNG')
        self.assertEqual(jung_classification([[0., 0.], [high, 0.]], 1.)['classification'],
                         'INCONCLUSIVE_DIAMETER_INTERVAL')
        radius = 19.999
        boundary = 2*radius
        self.assertEqual(jung_classification([[0., 0.], [boundary, 0.]], radius)['classification'],
                         'INCONCLUSIVE_DIAMETER_INTERVAL')
        self.assertEqual(jung_classification([[0., 0.], [np.nextafter(boundary, np.inf), 0.]], radius)['classification'],
                         'GUARANTEED_EMPTY_BY_DIAMETER')

    def test_right_triangle_point_and_equivalent_representations(self):
        poly = np.array([[0., 0.], [3., 0.], [0., 4.]])
        expected = diameter_circle_audit(poly)
        self.assertTrue(expected['diameter_circle_covers_vertices'])
        self.assertEqual(expected['thales_dot_signs'], [0, 0, 0])
        for vertices in (poly[::-1], np.roll(poly, 1, axis=0), np.vstack((poly, poly[0]))):
            self.assertEqual(diameter_circle_audit(vertices), expected)
        point = audit_clearance_geometry([[2., 3.], [2., 3.]], safe_radius=0.)
        self.assertTrue(point['diameter_circle']['diameter_circle_covers_vertices'])
        self.assertEqual(point['diameter_circle']['diameter_m'], 0.)
        self.assertTrue(point['jung']['certified_region_existence_from_diameter'])

    def test_square_and_current_equal_to_one_disk_center(self):
        poly = np.array([[-5., -5.], [5., -5.], [5., 5.], [-5., 5.]])
        current = poly[0].copy()
        center, radius = mec(poly)
        result = nearest_certified_clear_point(poly, current, 12., center, radius)
        self.assertGreater(result[1]['distance_to_current'], 0.)
        self.assert_strict_clearance(poly, current, center, 12., result)
        self.assertTrue(diameter_circle_audit(poly)['diameter_circle_covers_vertices'])

    def test_feasible_equilateral_triangle_remains_strictly_safe(self):
        poly = np.array([[-15., 0.], [15., 0.], [0., 15*math.sqrt(3)]])
        current = np.array([40., 40.])
        center, radius = mec(poly)
        self.assertLess(radius, 19.999)
        result = nearest_certified_clear_point(poly, current, 19.999, center, radius)
        self.assert_strict_clearance(poly, current, center, 19.999, result)

    def test_numerical_intersection_failure_safely_uses_known_mec(self):
        poly = np.array([[-3., 0.], [3., 0.]])
        current = np.array([0., 15.])
        center = np.zeros(2)
        ordinary = nearest_certified_clear_point(poly, current, 5., center, 3.)
        self.assertFalse(ordinary[1]['fallback'])
        # Both single-boundary radial candidates violate the other disk. Inject
        # a failed circle-intersection construction, leaving only certified MEC.
        with patch('geometry.math.sqrt', return_value=float('nan')):
            failed_enumeration = nearest_certified_clear_point(poly, current, 5., center, 3.)
        self.assertTrue(failed_enumeration[1]['fallback'])
        self.assertEqual(failed_enumeration[1]['mode'], 'mec_fallback')
        np.testing.assert_array_equal(failed_enumeration[0], center)
        self.assert_strict_clearance(poly, current, center, 5., failed_enumeration)

    def test_below_at_and_above_safe_radius_never_inflate_certificate(self):
        radius = 19.999
        poly, center = np.array([[0., 0.]]), np.zeros(2)
        values = [(np.nextafter(radius, 0.), True), (radius, True),
                  (np.nextafter(radius, np.inf), False)]
        values += [(radius+sign*tiny, sign < 0)
                   for tiny in (1e-12, 1e-10, 1e-8, 1e-6) for sign in (-1, 1)]
        for value, already_safe in values:
            current = np.array([value, 0.])
            result = nearest_certified_clear_point(poly, current, radius, center, 0.)
            self.assertEqual(result[1]['mode'] == 'already_certified', already_safe)
            if already_safe:
                np.testing.assert_array_equal(result[0], current)
                self.assertEqual(result[1]['distance_to_current'], 0.)
            else:
                self.assertGreater(result[1]['distance_to_current'], 0.)
            self.assert_strict_clearance(poly, current, center, radius, result)

    def test_invalid_audit_input_is_not_a_success_classification(self):
        for poly in ([], [[1.]], [[np.nan, 0.]], [[0., np.inf]]):
            with self.assertRaises(ValueError):
                audit_clearance_geometry(poly)
        for radius in (-1., np.nan, np.inf):
            with self.assertRaises(ValueError):
                jung_classification([[0., 0.]], radius)


if __name__ == '__main__':
    unittest.main()
