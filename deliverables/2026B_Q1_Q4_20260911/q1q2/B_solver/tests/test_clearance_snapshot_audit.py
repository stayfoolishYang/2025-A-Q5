"""Independent support-circle checks used only in the offline savings audit."""
from fractions import Fraction as F
from pathlib import Path
import sys
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'experiments'))
from clearance_snapshot_audit import exact_mec_witness, sq


class ExactSnapshotCircleTests(unittest.TestCase):
    def test_support_circles_and_redundant_interior_vertices(self):
        fixtures = [([[3.,4.]], (F(3),F(4)), F(0)),
                    ([[-2.,0.],[2.,0.],[0.,0.1]], (F(0),F(0)), F(4)),
                    ([[-1.,0.],[1.,0.],[0.,2.],[0.,1.]], (F(0),F(3,4)), F(25,16)),
                    ([[-1.,-1.],[1.,-1.],[1.,1.],[-1.,1.]], (F(0),F(0)), F(2))]
        for vertices, expected_center, expected_radius2 in fixtures:
            for points in (vertices, list(reversed(vertices))):
                center, radius2, _ = exact_mec_witness(np.asarray(points))
                self.assertEqual(center, expected_center)
                self.assertEqual(radius2, expected_radius2)
                self.assertTrue(all(sq(center, tuple(F(v) for v in point))<=radius2 for point in points))


if __name__=='__main__':
    unittest.main()
