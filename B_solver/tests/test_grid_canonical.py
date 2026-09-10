"""Regression and coverage checks for the optional canonical optical lattice."""
import hashlib
from pathlib import Path
import sys
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from geometry import canonical_grid, disk, mec, optical_grid
from directional.fallback_cost import estimate_optical_fallback_cost, ordered_grid, travel


class CanonicalGridTests(unittest.TestCase):
    def setUp(self):
        self.triangle = np.array([[0., 0.], [1520., 0.], [760., 60.]])
        self.current = np.array([17., 25.])

    def test_frozen_legacy_grid_and_route_are_unchanged(self):
        # Captured before introducing grid_v1: covers the reported row-jump case.
        grid = optical_grid(self.triangle)
        route = ordered_grid(self.triangle, self.current)
        self.assertEqual(len(grid), 308)
        self.assertEqual(hashlib.sha256(grid.tobytes()).hexdigest(),
                         'd5e6d9dac300828c96345f65d4a939dab6b231e66930d2c5ab1bf66ece3e0e84')
        self.assertEqual(hashlib.sha256(route.tobytes()).hexdigest(),
                         '0fa14ea0d390c88035810767a6a7a8fdfd2ba537f34a75caae7977c6578190d0')
        np.testing.assert_array_equal(grid, optical_grid(self.triangle, 'grid_v0'))
        self.assertEqual(estimate_optical_fallback_cost(self.triangle, self.current),
                         2160.0464865831323)
        self.assertEqual(estimate_optical_fallback_cost(self.triangle, self.current, exact=False),
                         2306.6840946436437)

    def test_equivalent_polygon_representations_are_identical(self):
        polygons = [self.triangle, disk((350., -275.), 130., 16),
                    np.array([[0., 0.], [100., 0.], [100., 100.], [0., 100.]]),
                    np.array([[10., 20.], [10., 60.], [10., 110.]])]
        for poly in polygons:
            expected = canonical_grid(poly)
            expected_routes = [ordered_grid(poly, self.current, local=local, grid_version='grid_v1')
                               for local in (False, True)]
            for shift in range(len(poly)):
                for rev in (False, True):
                    candidate = np.roll(poly[::-1] if rev else poly, shift, axis=0)
                    # A repeated closing point is an equivalent representation too.
                    candidate = np.vstack((candidate, candidate[0], candidate[0]))
                    actual = canonical_grid(candidate)
                    for key in ('basis', 'index_bounds', 'indices', 'points', 'diameter_endpoints'):
                        np.testing.assert_array_equal(actual[key], expected[key])
                    for local, route in zip((False, True), expected_routes):
                        np.testing.assert_array_equal(
                            ordered_grid(candidate, self.current, local=local, grid_version='grid_v1'), route)

    def test_near_tied_diameters_and_axis_sign_are_canonical(self):
        square = np.array([[0., 0.], [100., 0.], [100., 100.], [0., 100.]])
        expected = canonical_grid(square)
        square[1, 0] += 1e-10  # Other diagonal is longer by numerical noise.
        actual = canonical_grid(square)
        np.testing.assert_array_equal(actual['diameter_endpoints'], expected['diameter_endpoints'])
        np.testing.assert_array_equal(actual['basis'], expected['basis'])
        for poly in (square, np.array([[0., 100.], [0., -100.]])):
            axis = canonical_grid(poly)['basis'][:, 0]
            self.assertTrue(axis[0] > 1e-12 or (abs(axis[0]) <= 1e-12 and axis[1] > 0))

    def test_no_loss_of_coverage_under_small_perturbations(self):
        rng = np.random.default_rng(61)
        polygons = [self.triangle, np.array([[-50., -20.], [130., -20.], [130., 80.], [-50., 80.]])]
        for base in polygons:
            for epsilon in (0., 1e-12, 1e-10, 1e-8, 1e-6):
                for sign in (-1, 1):
                    poly = base.copy() + sign*epsilon*np.array([0.37, 1.])
                    poly[1] += sign*epsilon*np.array([0.5, -0.2])
                    grid = canonical_grid(poly)
                    weights = rng.random((300, len(poly)))
                    interior = weights/weights.sum(axis=1, keepdims=True) @ poly
                    t = np.linspace(0., 1., 65)[:, None]
                    edges = np.vstack([(1-t)*a+t*b for a, b in zip(poly, np.roll(poly, -1, axis=0))])
                    samples = np.vstack((interior, edges))
                    basis, bounds = grid['basis'], grid['index_bounds']
                    np.testing.assert_allclose(basis.T @ basis, np.eye(2), rtol=0, atol=1e-14)
                    # A nearest integer lattice point must exist in the actual
                    # generated index rectangle, and be within sqrt(200) m.
                    ids = np.rint(samples @ basis / 20).astype(np.int64)
                    self.assertTrue((ids >= bounds[0]).all() and (ids <= bounds[1]).all())
                    nearest = (ids*20.) @ basis.T
                    self.assertLessEqual(np.linalg.norm(nearest-samples, axis=1).max(), np.sqrt(200)+1e-8)
                    point_ids = set(map(tuple, grid['indices']))
                    self.assertTrue(all(tuple(idx) in point_ids for idx in ids))

    def test_padding_absorbs_reported_tiny_translation(self):
        reference = canonical_grid(self.triangle)
        for epsilon in (-1e-10, 1e-10):
            shifted = canonical_grid(self.triangle+np.array([0., epsilon]))
            np.testing.assert_array_equal(shifted['index_bounds'], reference['index_bounds'])
            self.assertEqual(shifted['count'], reference['count'])

    def test_executor_and_both_cost_modes_use_the_same_grid(self):
        for poly in (self.triangle, disk((200., 100.), 75., 16)):
            metadata = optical_grid(poly, 'grid_v1', return_metadata=True)
            cheap_metadata = canonical_grid(poly, materialize=False)
            self.assertNotIn('points', cheap_metadata)
            for key in ('basis', 'index_bounds', 'count'):
                np.testing.assert_array_equal(metadata[key], cheap_metadata[key])
            center, _ = mec(poly)
            for local in (False, True):
                route = ordered_grid(poly, self.current, local, 'grid_v1')
                self.assertEqual(set(map(tuple, route)), set(map(tuple, metadata['points'])))
                self.assertEqual(len(route), metadata['count'])
                exact = estimate_optical_fallback_cost(poly, self.current, local=local, grid_version='grid_v1')
                self.assertEqual(exact, travel(route, self.current)/5+3*len(route)+2)
                cheap = estimate_optical_fallback_cost(poly, self.current, exact=False, local=local,
                                                       grid_version='grid_v1')
                self.assertAlmostEqual((cheap-np.linalg.norm(center-self.current)/5-2)/7,
                                       len(route), places=9)

    def test_explicit_version_validation_and_point_region(self):
        for fn in (lambda: optical_grid(self.triangle, 'typo'),
                   lambda: ordered_grid(self.triangle, self.current, grid_version='typo'),
                   lambda: estimate_optical_fallback_cost(self.triangle, self.current, grid_version='typo')):
            with self.assertRaises(ValueError):
                fn()
        poly = np.array([[13., -27.]])
        result = canonical_grid(poly)
        self.assertLess(np.linalg.norm(result['points']-poly[0], axis=1).min(), 20)
        self.assertEqual(estimate_optical_fallback_cost(poly, self.current, grid_version='grid_v1'),
                         np.linalg.norm(poly[0]-self.current)/5+5)


if __name__ == '__main__':
    unittest.main()
