import numpy as np
from geometry import optical_grid, diameter, mec


def ordered_grid(poly, current, local=True):
    """Reorder every original grid point. No spatial or particle pruning."""
    pts = optical_grid(poly)
    if not local:
        return pts[np.argsort(np.linalg.norm(pts-current, axis=1))]
    _, a, b = diameter(poly)
    u = (b-a)/max(np.linalg.norm(b-a), 1e-12)
    v = np.array([-u[1], u[0]])
    xy = np.rint(np.c_[pts@u, pts@v]/20).astype(int)
    paths = []
    for axis in (0, 1):
        groups = []
        for j, val in enumerate(np.unique(xy[:, axis])):
            ids = np.flatnonzero(xy[:, axis] == val)
            ids = ids[np.argsort(xy[ids, 1-axis])]
            groups.extend(ids[::1 if j % 2 == 0 else -1])
        path = pts[groups]
        paths.extend((path, path[::-1]))
    return min(paths, key=lambda p: travel(p, current))


def travel(points, current):
    return float(np.linalg.norm(points[0]-current) + np.linalg.norm(np.diff(points, axis=0), axis=1).sum()) if len(points) else 0.


def estimate_optical_fallback_cost(poly, current, exact=True, local=True):
    """Full traversal estimate, not expected time to encounter the unknown target."""
    center, radius = mec(poly)
    if radius <= 19.999:
        return float(np.linalg.norm(center-current)/5+5)
    if exact:
        pts = ordered_grid(poly, current, local)
        return travel(pts, current)/5 + 3*len(pts)+2
    # Cheap planning surrogate: bounding rectangle count and one 20m hop per point.
    _, a, b = diameter(poly)
    u = (b-a)/max(np.linalg.norm(b-a), 1e-12)
    basis = np.array([u, [-u[1], u[0]]]).T
    q = poly@basis
    n = np.prod(np.ceil(q.max(axis=0)/20)-np.floor(q.min(axis=0)/20)+1)
    return float(np.linalg.norm(center-current)/5+7*n+2)
