import numpy as np
from geometry import mec, diameter


def candidates(poly, current, history=(), offsets=(100, 200, 300, 500, 700)):
    c, _ = mec(poly)
    _, a, b = diameter(poly)
    u = (b-a)/max(np.linalg.norm(b-a), 1e-12)
    if not u.any():
        u = np.array([1., 0.])
    v = np.array([-u[1], u[0]])
    ray = c-current
    side = np.array([-ray[1], ray[0]])/max(np.linalg.norm(ray), 1e-12)
    pts = [c]
    for d in offsets:
        for e in (u, v):
            pts.extend((c+d*e, c-d*e))
        pts.extend((current+0.5*ray+d*side, current+0.5*ray-d*side))
    accepted = []
    for p in pts:
        if not np.isfinite(p).all() or np.abs(p).max() > 2e6:
            continue
        if np.linalg.norm(p-current) < 0.1 or any(np.linalg.norm(p-q) < 0.1 for q in history):
            continue
        if not any(np.linalg.norm(p-q) < 0.1 for q in accepted):
            accepted.append(p)
    return np.asarray(accepted, dtype=float).reshape(-1, 2)
