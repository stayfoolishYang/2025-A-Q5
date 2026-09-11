"""Q2-only stable scores; shared Q1/Q3/Q4 geometry remains frozen."""
from pathlib import Path
from functools import lru_cache
import sys
import time
import numpy as np
from geometry import ERROR_DEG, wedge, intersect_disk

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


def adaptive_score(task):
    """Same outer-polygon directional proxy as the frozen 213-point audit."""
    started = time.perf_counter()
    q, poly = (np.asarray(x, dtype=float) for x in task[:2])
    tolerance = task[2] if len(task)>2 else .01
    if np.array_equal(q, np.zeros(2)):
        value = pair_diameter(poly)
        return dict(D_lower_m=value,D_upper_m=value,inner_gap_m=0.,near_possible=False,near_upper_m=0.,
                    reception='same_first_position',direction_envelope=dict(leaves=[],converged=True),
                    posterior_evaluations=0,max_clip_residual_m=0.,elapsed_s=time.perf_counter()-started,
                    observation_state='repeat_preserves_first_observation')
    calls, residual = 0, 0.
    edges = np.roll(poly, -1, axis=0)-poly
    lengths = np.linalg.norm(edges, axis=1)

    @lru_cache(None)
    def evaluate(z, error):
        nonlocal calls, residual
        post = wedge(poly, q, z, error)
        calls += 1
        if len(post):
            delta = post[:, None]-poly[None]
            signed = (edges[None,:,0]*delta[:,:,1]-edges[None,:,1]*delta[:,:,0])/lengths
            lo, hi = np.deg2rad([z-error,z+error])
            normals = np.array([[np.sin(lo),-np.cos(lo)],[-np.sin(hi),np.cos(hi)]])
            residual = max(residual, float(-signed.min()), float(((post-q)@normals.T).max()))
            if residual > 1e-6:
                raise ArithmeticError('Posterior clipping residual exceeds 1e-6 m')
        return pair_diameter(post)

    envelope = continuous_envelope(evaluate, tolerance=tolerance, max_splits=20000, initial_bins=72)
    near_poly = intersect_disk(poly, q, 5)
    near_upper = min(10., pair_diameter(near_poly))
    # The direction proxy retains the old conservative near-compatible positions.
    lower = envelope['lower_m']
    upper = max(envelope['upper_m'], near_upper)
    if not envelope['converged'] or upper-lower > tolerance+1e-9:
        raise ArithmeticError('Unresolved directional/near numerical score interval')
    return dict(D_lower_m=lower, D_upper_m=upper, inner_gap_m=upper-lower,
                near_possible=bool(len(near_poly)), near_upper_m=near_upper,
                reception='certified_before_scoring', direction_envelope=envelope,
                posterior_evaluations=calls, max_clip_residual_m=residual,
                elapsed_s=time.perf_counter()-started)
