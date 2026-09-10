"""Conservative 2-D bearing geometry. Angles at the public boundary are degrees."""
import math
import numpy as np

ERROR_DEG = 1.00500001  # 1 degree instrument error + 0.005 degree rounding.


def cross(a, b):
    return a[..., 0] * b[..., 1] - a[..., 1] * b[..., 0]


def clip(poly, normal, bound):
    """Sutherland-Hodgman clipping by normal @ x <= bound."""
    if not len(poly):
        return np.empty((0, 2))
    d = poly @ normal - bound
    inside = d <= 1e-9
    if inside.all():
        return poly.copy()
    if not inside.any():
        return np.empty((0, 2))
    result = []
    for i in range(len(poly)):
        j = (i + 1) % len(poly)
        if inside[i]:
            result.append(poly[i])
        if inside[i] != inside[j]:
            result.append(poly[i] + (poly[j] - poly[i]) * d[i] / (d[i] - d[j]))
    return np.asarray(result).reshape(-1, 2)


def disk(center=(0, 0), radius=1800, sides=128):
    """Circumscribed polygon, never an inscribed under-approximation."""
    a = (np.arange(sides) + 0.5) * 2 * np.pi / sides
    return np.asarray(center) + radius / np.cos(np.pi / sides) * np.c_[np.cos(a), np.sin(a)]


def intersect_disk(poly, center, radius, sides=64):
    for a in np.arange(sides) * 2 * np.pi / sides:
        n = np.array([np.cos(a), np.sin(a)])
        poly = clip(poly, n, radius + n @ center)
    return poly


def wedge(poly, point, bearing, error=ERROR_DEG):
    lo, hi = np.deg2rad([bearing - error, bearing + error])
    for n in (np.array([np.sin(lo), -np.cos(lo)]), np.array([-np.sin(hi), np.cos(hi)])):
        poly = clip(poly, n, n @ point)
    return poly


def area(poly):
    return abs(float(cross(poly, np.roll(poly, -1, axis=0)).sum())) / 2 if len(poly) > 2 else 0.


def diameter(poly):
    """Rotating calipers for a CCW convex polygon; returns distance and endpoints."""
    n = len(poly)
    if n == 0:
        raise ValueError('Empty feasible region')
    if n <= 2:
        return float(np.linalg.norm(poly[-1] - poly[0])), poly[0], poly[-1]
    best, pair, j = -1., (0, 0), 1
    for i in range(n):
        ni = (i + 1) % n
        edge = poly[ni] - poly[i]
        for _ in range(n):
            nj = (j + 1) % n
            if cross(edge, poly[nj] - poly[i]) > cross(edge, poly[j] - poly[i]) + 1e-10:
                j = nj
            else:
                break
        for a, b in ((i, j), (ni, j), (i, (j + 1) % n), (ni, (j + 1) % n)):
            d = float(np.sum((poly[a] - poly[b]) ** 2))
            if d > best:
                best, pair = d, (a, b)
    return math.sqrt(best), poly[pair[0]], poly[pair[1]]


def mec(poly):
    """Randomized incremental enclosing circle; final radius checked against all points."""
    if not len(poly):
        raise ValueError('Empty feasible region')
    points = np.random.default_rng(42).permutation(poly)
    c, r = points[0].copy(), 0.
    for i, a in enumerate(points):
        if np.linalg.norm(a - c) <= r + 1e-9:
            continue
        c, r = a.copy(), 0.
        for j, b in enumerate(points[:i]):
            if np.linalg.norm(b - c) <= r + 1e-9:
                continue
            c, r = (a + b) / 2, np.linalg.norm(a - b) / 2
            for d in points[:j]:
                if np.linalg.norm(d - c) <= r + 1e-9:
                    continue
                u, v = b - a, d - a
                det = 2 * cross(u, v)
                if abs(det) < 1e-12:
                    pair = max(((a, b), (a, d), (b, d)), key=lambda z: np.sum((z[0]-z[1])**2))
                    c, r = (pair[0] + pair[1]) / 2, np.linalg.norm(pair[0] - pair[1]) / 2
                else:
                    c = a + np.array([v[1]* (u@u) - u[1]*(v@v), u[0]*(v@v) - v[0]*(u@u)]) / det
                    r = np.linalg.norm(c - a)
    return c, float(np.max(np.linalg.norm(poly - c, axis=1))) + 1e-8


def contains(poly, points, tolerance=1e-7):
    points = np.atleast_2d(points)
    edges = np.roll(poly, -1, axis=0) - poly
    return (cross(edges[:, None, :], points[None, :, :] - poly[:, None, :]) >= -tolerance).all(axis=0)


def sample_poly(poly, count, rng):
    """Area-uniform triangulation proposals; this is a design distribution, not a prior fact."""
    if len(poly) < 3 or area(poly) < 1e-12:
        return np.repeat(poly.mean(axis=0)[None], count, axis=0)
    a = poly[0]
    b, c = poly[1:-1], poly[2:]
    weights = abs(cross(b-a, c-a))
    k = rng.choice(len(b), count, p=weights/weights.sum())
    u, v = np.sqrt(rng.random(count)), rng.random(count)
    return (1-u[:, None])*a + (u*(1-v))[:, None]*b[k] + (u*v)[:, None]*c[k]


def coverage(mixed=False, ring=1130.):
    if not mixed:
        a = np.arange(6) * np.pi / 3
        return np.vstack(([0., 0.], ring * np.c_[np.cos(a), np.sin(a)]))
    return np.array([(x, y) for x in range(-2100, 2101, 700) for y in range(-2100, 2101, 700)
                     if x*x + y*y <= 2800**2], dtype=float)


def route(points, start):
    """Open nearest-neighbour tour with 2-opt; no return-to-origin requirement."""
    remaining, ordered, p = list(range(len(points))), [], np.asarray(start)
    while remaining:
        j = min(remaining, key=lambda i: np.linalg.norm(points[i] - p))
        remaining.remove(j)
        ordered.append(points[j])
        p = points[j]
    path = np.vstack((start, ordered)) if ordered else np.asarray([start])
    for _ in range(3):
        changed = False
        for i in range(1, len(path)-1):
            for j in range(i+1, len(path)):
                old = np.linalg.norm(path[i-1]-path[i])
                new = np.linalg.norm(path[i-1]-path[j])
                if j+1 < len(path):
                    old += np.linalg.norm(path[j]-path[j+1])
                    new += np.linalg.norm(path[i]-path[j+1])
                if new < old - 1e-8:
                    path[i:j+1] = path[i:j+1][::-1]
                    changed = True
        if not changed:
            break
    return path[1:]


def optical_grid(poly):
    """20 m spacing rotated to the polygon long axis: covering radius sqrt(200)<20."""
    _, a, b = diameter(poly)
    u = (b-a) / max(np.linalg.norm(b-a), 1e-12)
    if not u.any():
        return np.asarray([a])
    basis = np.array([u, [-u[1], u[0]]]).T
    local = poly @ basis
    lo, hi = np.floor(local.min(axis=0)/20), np.ceil(local.max(axis=0)/20)
    # ponytail: bounding rectangle overcovers a narrow wedge; no fragile polygon-offset dependency.
    pts = [(x*20, y*20) for x in range(int(lo[0]), int(hi[0])+1) for y in range(int(lo[1]), int(hi[1])+1)]
    return np.asarray(pts) @ basis.T


def candidate_views(poly, current):
    c, r = mec(poly)
    _, a, b = diameter(poly)
    u = (b-a) / max(np.linalg.norm(b-a), 1e-9)
    v = np.array([-u[1], u[0]])
    pts = [c]
    for frac in (0.4, 0.75, 1.):
        base = current + frac * (c-current)
        for side in (-1, 1):
            pts.append(base + side * max(25., min(200., r*0.3)) * v)
    for angle in np.arange(8)*np.pi/4:
        pts.append(c + max(30., min(250., r*0.5))*np.array([np.cos(angle), np.sin(angle)]))
    points = np.asarray(pts)
    return points[np.linalg.norm(points-current, axis=1) > 0.1]


def next_view(poly, current, lam=0.2, candidates=None, safe_only=False):
    """Sampled minimax, including a conservative no-signal outcome outside safe region."""
    candidates = candidate_views(poly, current) if candidates is None else candidates
    representatives = np.vstack((poly, poly.mean(axis=0)))
    if len(representatives) > 9:
        representatives = representatives[np.linspace(0, len(representatives)-1, 9).astype(int)]
    old_d = diameter(poly)[0]
    records = []
    for s in candidates:
        safe = np.max(np.linalg.norm(poly-s, axis=1)) <= 1000
        if safe_only and not safe:
            continue
        worst = 0. if safe else old_d
        angles = np.rad2deg(np.arctan2(representatives[:, 1]-s[1], representatives[:, 0]-s[0]))
        for z in angles:
            for e in (-ERROR_DEG, 0., ERROR_DEG):
                post = wedge(poly, s, z+e)
                if len(post):
                    worst = max(worst, diameter(post)[0])
        cost = np.linalg.norm(s-current)/5 + 5
        records.append((worst + lam*cost, s, worst, cost, safe))
    if not records:
        raise ValueError('No admissible candidate views')
    best = min(records, key=lambda row: row[0])
    return best[1], records
