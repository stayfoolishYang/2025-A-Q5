"""Q2-only stable scores; shared Q1/Q3/Q4 geometry remains frozen."""
from pathlib import Path
import sys
import numpy as np
from geometry import ERROR_DEG, wedge

sys.path.insert(0, str(Path(__file__).resolve().parent / 'experiments'))
from q2_score_audit import pair_diameter, continuous_envelope


def stable_legacy_next_view(poly, current, lam=.2, candidates=None, safe_only=True):
    """Preserve the old 15 scenarios, replacing only the diameter implementation."""
    representatives = np.vstack((poly, poly.mean(axis=0)))
    if len(representatives) > 9:
        representatives = representatives[np.linspace(0, len(representatives)-1, 9).astype(int)]
    records = []
    for q in candidates:
        safe = bool(np.max(np.linalg.norm(poly-q, axis=1)) <= 1000)
        if safe_only and not safe:
            continue
        worst = 0. if safe else pair_diameter(poly)
        angles = np.rad2deg(np.arctan2(representatives[:, 1]-q[1], representatives[:, 0]-q[0]))
        for z in angles:
            for e in (-ERROR_DEG, 0., ERROR_DEG):
                worst = max(worst, pair_diameter(wedge(poly, q, z+e)))
        cost = float(np.linalg.norm(q-current)/5+5)
        records.append((worst+lam*cost, q, worst, cost, safe))
    if not records:
        raise ValueError('No admissible candidate views')
    return min(records, key=lambda r:r[0])[1], records
