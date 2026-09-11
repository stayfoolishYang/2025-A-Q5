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


def nearest_certified_clear_point(poly, current, clearance_radius=19.999,
                                  mec_center=None, mec_radius=None):
    """Project the current position onto the intersection of vertex-centred disks.

    The supplied MEC certificate must be valid with radius <= clearance_radius.
    If neither centre nor radius is supplied, ``mec`` supplies that certificate.
    An optimum is the current point, a radial projection onto one boundary, or
    an intersection of two boundaries. We enumerate those candidates and retain
    only positions certified against every vertex. A valid MEC centre remains
    the fallback and a strict upper bound on the returned travel distance.

    Boundary constructions can round outward. Such candidates are moved towards
    the known feasible centre, with increasing representable inward steps. The
    guard used to consider candidates NEVER enlarges the certification radius:
    returned points pass FP64 norm checks AND exact binary-rational squared-
    distance checks. Near-degenerate cases may therefore return the MEC centre
    rather than an uncertifiable numerical approximation to the optimum.
    Enumerating O(m**2) boundary candidates and checking m vertices gives
    O(m**3) worst-case arithmetic work, not O(m**2).
    """
    from fractions import Fraction

    vertices = np.asarray(poly, dtype=np.float64)
    position = np.asarray(current, dtype=np.float64)
    radius = float(clearance_radius)
    if vertices.ndim != 2 or vertices.shape[1] != 2 or not len(vertices):
        raise ValueError('Expected a non-empty polygon with shape (n, 2)')
    if position.shape != (2,) or not np.isfinite(position).all():
        raise ValueError('Current position must be a finite 2-D point')
    if not np.isfinite(vertices).all() or not math.isfinite(radius) or radius < 0:
        raise ValueError('Polygon and nonnegative clearance radius must be finite')
    vertices = np.unique(vertices, axis=0)
    if (mec_center is None) != (mec_radius is None):
        raise ValueError('MEC centre and radius must be supplied together')
    if mec_center is None:
        mec_center, mec_radius = mec(vertices)
    center = np.asarray(mec_center, dtype=np.float64)
    certificate_radius = float(mec_radius)
    if center.shape != (2,) or not np.isfinite(center).all():
        raise ValueError('MEC centre must be a finite 2-D point')
    if not math.isfinite(certificate_radius) or not 0 <= certificate_radius <= radius:
        raise ValueError('MEC certificate radius must be nonnegative and <= clearance radius')

    def rational_point(point):
        return tuple(Fraction(float(value)) for value in point)

    exact_vertices = [rational_point(vertex) for vertex in vertices]
    exact_position = rational_point(position)
    exact_radius_squared = Fraction(radius)**2

    def squared_distance(a, b):
        return (a[0]-b[0])**2 + (a[1]-b[1])**2

    def max_distance(point):
        return float(np.linalg.norm(vertices-point, axis=1).max())

    def certified(point, bound=radius, exact_bound=exact_radius_squared):
        if not np.isfinite(point).all() or max_distance(point) > bound:
            return False
        exact = rational_point(point)
        return all(squared_distance(exact, vertex) <= exact_bound for vertex in exact_vertices)

    if not certified(center, certificate_radius, Fraction(certificate_radius)**2):
        raise ValueError('Invalid MEC certificate: its circle does not contain every vertex')
    center_distance = float(np.linalg.norm(center-position))
    exact_center_distance_squared = squared_distance(rational_point(center), exact_position)
    if not math.isfinite(center_distance):
        raise ValueError('Travel distance is not finite')

    candidate_count = 0
    adjusted_count = 0

    def metadata(point, mode, adjustment=0., fallback=False):
        return {
            'mode': mode, 'fallback': bool(fallback),
            'max_vertex_distance': max_distance(point),
            'distance_to_current': float(np.linalg.norm(point-position)),
            'mec_distance': center_distance, 'clearance_radius': radius,
            'mec_certificate_radius': certificate_radius,
            'candidate_count': candidate_count, 'adjusted_candidate_count': adjusted_count,
            'numerical_adjustment_m': float(adjustment),
            'certification': 'FP64 norms and exact binary-rational squared distances',
        }

    if certified(position):
        return position.copy(), metadata(position, 'already_certified')

    # This guard only keeps slightly outside candidates available for inward
    # repair. All returned values still use the strict certified() predicate.
    scale = max(1., radius, float(np.abs(vertices).max()), float(np.abs(position).max()),
                float(np.abs(center).max()))
    construction_guard = 128*np.finfo(np.float64).eps*scale
    candidates = []
    for vertex in vertices:
        delta = position-vertex
        length = float(np.linalg.norm(delta))
        if length > 0:
            candidates.append((vertex+(radius/length)*delta, 'radial_projection'))
    for i, a in enumerate(vertices):
        for b in vertices[i+1:]:
            delta = b-a
            distance = float(np.linalg.norm(delta))
            if distance == 0 or distance > 2*radius:
                continue
            half = distance/2
            height = math.sqrt(max(0., (radius-half)*(radius+half)))
            midpoint = a+delta/2
            perpendicular = np.array([-delta[1], delta[0]])/distance
            candidates.append((midpoint+height*perpendicular, 'circle_intersection'))
            if height > 0:
                candidates.append((midpoint-height*perpendicular, 'circle_intersection'))
    candidate_count = len(candidates)
    candidates.sort(key=lambda item: (float(np.linalg.norm(item[0]-position)),
                                       item[1], float(item[0][0]), float(item[0][1])))
    best, best_mode, best_adjustment = center.copy(), 'mec_fallback', 0.
    best_distance = center_distance

    for candidate, mode in candidates:
        if float(np.linalg.norm(candidate-position)) > best_distance+construction_guard:
            continue
        if max_distance(candidate) > radius+construction_guard:
            continue
        repaired = candidate
        if not certified(repaired):
            # At a true singleton intersection only the endpoint may certify.
            # Geometric increase handles very small slack without cancellation-
            # prone formulas dividing by (radius - MEC radius).
            for exponent in range(-48, 1, 4):
                fraction = 2.**exponent
                repaired = center.copy() if fraction == 1. else candidate+fraction*(center-candidate)
                if certified(repaired):
                    break
            else:
                repaired = center.copy()
            adjusted_count += 1
        distance = float(np.linalg.norm(repaired-position))
        if distance >= best_distance:
            continue
        exact_distance = squared_distance(rational_point(repaired), exact_position)
        if exact_distance > exact_center_distance_squared:
            continue
        best, best_mode = repaired.copy(), mode
        best_distance = distance
        best_adjustment = float(np.linalg.norm(repaired-candidate))

    # Keeping the check at the public boundary protects later refactors of the
    # candidate constructor from silently weakening the clearance certificate.
    if not certified(best) or float(np.linalg.norm(best-position)) > center_distance:
        best, best_mode, best_adjustment = center.copy(), 'mec_fallback', 0.
    return best, metadata(best, best_mode, best_adjustment, best_mode == 'mec_fallback')


def exact_squared_distance(a, b):
    """Squared distance between represented finite coordinates, without rounding."""
    from fractions import Fraction
    return sum((Fraction(float(x))-Fraction(float(y)))**2 for x, y in zip(a, b))


def is_certified_clear_point(poly, point, radius=19.999):
    """Strict FP64 AND exact squared-distance check; invalid input is false."""
    from fractions import Fraction
    try:
        vertices, position = np.asarray(poly, dtype=float), np.asarray(point, dtype=float)
        bound = float(radius)
        if (vertices.ndim != 2 or vertices.shape[1] != 2 or not len(vertices)
                or position.shape != (2,) or not np.isfinite(vertices).all()
                or not np.isfinite(position).all() or not math.isfinite(bound) or bound < 0):
            return False
        if float(np.linalg.norm(vertices-position, axis=1).max()) > bound:
            return False
        return all(exact_squared_distance(vertex, position) <= Fraction(bound)**2 for vertex in vertices)
    except (TypeError, ValueError, ArithmeticError):
        return False


def segment_certified_clear_point(poly, current, clearance_radius=19.999,
                                 mec_center=None, mec_radius=None):
    """Stop at the first safe position on the original current-to-MEC segment.

    We parameterise backwards as q(s)=M+s*(current-M), so q(0)=M is
    certified and the largest feasible s in [0,1] is sought. Each disk gives
    one quadratic upper root. The stable root formula avoids cancellation
    when its linear coefficient is positive. Construction and each final
    feasibility check are O(m), with a fixed cap on inward repairs.

    This is a conservatively verified FP64 segment point, not an exact claim
    about the first real-valued intersection. Rounding may move the point
    inward or force MEC fallback. Clearance is strict for represented output
    coordinates; the ideal fixed-next-waypoint two-leg theorem additionally
    assumes exact collinearity (FP64 interpolation has rounding residual).
    """
    import json

    vertices, position = np.asarray(poly, dtype=float), np.asarray(current, dtype=float)
    radius = float(clearance_radius)
    if (vertices.ndim != 2 or vertices.shape[1] != 2 or not len(vertices)
            or not np.isfinite(vertices).all() or position.shape != (2,)
            or not np.isfinite(position).all() or not math.isfinite(radius) or radius < 0):
        raise ValueError('Expected finite non-empty polygon, position and nonnegative clearance radius')
    if (mec_center is None) != (mec_radius is None):
        raise ValueError('MEC centre and radius must be supplied together')
    if mec_center is None:
        mec_center, mec_radius = mec(vertices)
    center, certificate_radius = np.asarray(mec_center, dtype=float), float(mec_radius)
    if (not math.isfinite(certificate_radius) or not 0 <= certificate_radius <= radius
            or not is_certified_clear_point(vertices, center, certificate_radius)):
        raise ValueError('Invalid MEC certificate')
    mec_distance = float(np.linalg.norm(position-center))
    if not math.isfinite(mec_distance):
        raise ValueError('Travel distance is not finite')

    def finish(point, mode, s, reason=None):
        return point.copy(), {
            'mode': mode, 'fallback': mode == 'mec_fallback', 'fallback_reason': reason,
            'max_vertex_distance': float(np.linalg.norm(vertices-point, axis=1).max()),
            'distance_to_current': float(np.linalg.norm(point-position)),
            'mec_distance': mec_distance, 'clearance_radius': radius,
            'mec_certificate_radius': certificate_radius,
            'segment_parameter_from_current': 1.-s,
            'certification': 'FP64 norms and exact binary-rational squared distances after JSON roundtrip',
        }

    if is_certified_clear_point(vertices, position, radius):
        return finish(position, 'already_certified', 1.)
    delta = position-center
    quadratic = float(delta@delta)
    if quadratic == 0 or not math.isfinite(quadratic):
        return finish(center, 'mec_fallback', 0., 'degenerate_segment')
    s = 1.
    for vertex in vertices:
        offset = center-vertex
        linear = float(delta@offset)
        # The exact verified centre is inside: a positive computed constant
        # here can only be rounding. Clamping it to zero is conservative.
        constant = min(0., float(offset@offset-radius*radius))
        discriminant = linear*linear-quadratic*constant
        if not math.isfinite(discriminant) or discriminant < 0:
            return finish(center, 'mec_fallback', 0., 'unresolved_quadratic')
        root_term = math.sqrt(discriminant)
        if linear >= 0:
            denominator = root_term+linear
            root = -constant/denominator if denominator else 0.
        else:
            root = (root_term-linear)/quadratic
        if not math.isfinite(root) or root < 0:
            return finish(center, 'mec_fallback', 0., 'unresolved_root')
        s = min(s, root)
    if s == 0:
        return finish(center, 'mec_fallback', 0., 'segment_entry_is_mec')

    baseline_squared = exact_squared_distance(position, center)
    # ponytail: fixed inward repair cap, not a second optimisation algorithm.
    for repair in (0., *(2.**exponent for exponent in range(-48, 1, 4))):
        inward_s = s*(1.-repair)
        point = center.copy() if inward_s == 0 else center+inward_s*delta
        point = np.asarray(json.loads(json.dumps(point.tolist(), allow_nan=False)), dtype=float)
        if (is_certified_clear_point(vertices, point, radius)
                and float(np.linalg.norm(point-position)) <= mec_distance
                and exact_squared_distance(point, position) <= baseline_squared):
            mode = 'segment_entry' if inward_s > 0 else 'mec_fallback'
            result, details = finish(point, mode, inward_s,
                                     'inward_repair_to_mec' if inward_s == 0 else None)
            details['inward_repair_fraction'] = repair
            return result, details
    return finish(center, 'mec_fallback', 0., 'no_verified_segment_candidate')


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


def _legacy_optical_grid(poly):
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


def canonical_grid(poly, *, materialize=True):
    """Construct grid_v1 and its integer-lattice metadata from a convex polygon.

    Equivalent cyclic/reversed vertex lists have exactly the same construction.
    The axis is a deterministically selected (possibly numerically tied)
    diameter, never a covariance/PCA axis.  One outward padding is applied to
    the projected bounding rectangle.  Its complete 20 m lattice has covering
    radius sqrt(200) m; padding can add points and never snaps a bound inward.

    Small geometric perturbations need not have identical lattice bounds.
    ``materialize=False`` returns the same bounds/count without allocating the
    point set, for the cheap planning estimate.
    """
    vertices = np.asarray(poly, dtype=np.float64)
    if vertices.ndim != 2 or vertices.shape[1] != 2 or not len(vertices):
        raise ValueError('Expected a non-empty polygon with shape (n, 2)')
    if not np.isfinite(vertices).all():
        raise ValueError('Polygon coordinates must be finite')
    # Sorting also removes duplicate closing vertices. Pair enumeration below
    # therefore has no dependency on perimeter start, orientation or duplicates.
    vertices = np.unique(vertices, axis=0)
    if len(vertices) == 1:
        a = b = vertices[0]
        u = np.array([1., 0.])
        longest = 0.
        axis_tolerance_m = 1e-8
    else:
        i, j = np.triu_indices(len(vertices), 1)
        differences = vertices[j] - vertices[i]
        lengths = np.linalg.norm(differences, axis=1)
        longest = float(lengths.max())
        axis_tolerance_m = 1e-8 + 1e-12 * longest
        # Lexicographically first endpoint pair wins a near-equal-diameter tie.
        # This tolerance changes orientation selection only, not the outer set.
        selected = int(np.flatnonzero(lengths >= longest-axis_tolerance_m)[0])
        a, b = vertices[i[selected]], vertices[j[selected]]
        u = differences[selected] / lengths[selected]
        if (u[0] < -1e-12) or (abs(u[0]) <= 1e-12 and u[1] < 0):
            u = -u
    basis = np.column_stack((u, [-u[1], u[0]]))
    origin = np.zeros(2, dtype=np.float64)
    projected = vertices @ basis
    # The fixed margin absorbs the observed ~1e-10 m boundary noise; the scale
    # term and nextafter additionally cover normal FP64 projection/rounding.
    padding_m = 1e-8 + 64*np.finfo(np.float64).eps*max(1., float(np.abs(vertices).max()))
    lower = np.nextafter(projected.min(axis=0)-padding_m, -np.inf)
    upper = np.nextafter(projected.max(axis=0)+padding_m, np.inf)
    index_lo = np.floor(lower/20.).astype(np.int64)
    index_hi = np.ceil(upper/20.).astype(np.int64)
    count = int(index_hi[0]-index_lo[0]+1) * int(index_hi[1]-index_lo[1]+1)
    result = {
        'grid_version': 'grid_v1', 'spacing_m': 20., 'origin': origin,
        'basis': basis, 'index_bounds': np.vstack((index_lo, index_hi)),
        'count': count, 'padding_m': padding_m,
        'projected_bounds': np.vstack((lower, upper)),
        'diameter_endpoints': np.vstack((a, b)), 'diameter_m': longest,
        'axis_tolerance_m': axis_tolerance_m,
    }
    if materialize:
        ix, iy = np.meshgrid(np.arange(index_lo[0], index_hi[0]+1, dtype=np.int64),
                             np.arange(index_lo[1], index_hi[1]+1, dtype=np.int64),
                             indexing='ij')
        indices = np.column_stack((ix.ravel(), iy.ravel()))
        result['indices'] = indices
        result['points'] = origin + (indices*20.) @ basis.T
    return result


def optical_grid(poly, grid_version='grid_v0', return_metadata=False):
    """Return a complete optical lattice, preserving grid_v0 by default.

    grid_v1 callers may request the canonical constructor metadata, including
    integer point identifiers; legacy metadata intentionally is not supported.
    """
    if grid_version == 'grid_v0':
        if return_metadata:
            raise ValueError('Canonical metadata requires grid_version=grid_v1')
        return _legacy_optical_grid(poly)
    if grid_version != 'grid_v1':
        raise ValueError('Unknown optical grid version: '+str(grid_version))
    grid = canonical_grid(poly)
    return grid if return_metadata else grid['points']


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
