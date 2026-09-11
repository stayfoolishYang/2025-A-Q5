"""Read-only Q1/Jung geometry helpers; never imported by the online planner.

Predicates use exact rational arithmetic on the supplied binary64 coordinates.
This avoids enlarging a radius or changing an inconclusive diameter interval
into a clearance certificate because a rounded square root looks equal.
Floating output coordinates and lengths are explanatory metadata only.
"""
from fractions import Fraction
import math

import numpy as np


def _vertices(poly):
    points = np.asarray(poly, dtype=np.float64)
    if points.ndim != 2 or points.shape[1] != 2 or not len(points):
        raise ValueError('Expected a non-empty (n, 2) vertex array')
    if not np.isfinite(points).all():
        raise ValueError('Vertices must be finite')
    # A convex hull has the same diameter and disk constraints as its vertices;
    # order and repeated closing vertices cannot affect these predicates.
    points = np.unique(points, axis=0)
    exact = [tuple(Fraction(float(x)) for x in point) for point in points]
    return points, exact


def _diameter_data(poly):
    points, exact = _vertices(poly)
    pair, squared = (0, 0), Fraction(0)
    for i, a in enumerate(exact):
        for j in range(i+1, len(exact)):
            b = exact[j]
            value = (a[0]-b[0])**2+(a[1]-b[1])**2
            if value > squared:
                pair, squared = (i, j), value
    return points, exact, pair, squared


def diameter_circle_audit(poly):
    """Test whether a farthest-pair diameter circle covers every vertex.

    For the exact midpoint c=(a+b)/2 and D=||a-b||,
    ||v-c||² <= D²/4 iff (v-a) dot (v-b) <= 0.
    The exact dot predicate is decisive; the displayed FP64 midpoint is not a
    replacement execution certificate. If coverage holds, this circle is an
    MEC since every enclosing circle already needs radius at least D/2.
    """
    points, exact, pair, squared = _diameter_data(poly)
    a, b = (exact[i] for i in pair)
    center_exact = tuple((x+y)/2 for x, y in zip(a, b))
    center = np.asarray([float(x) for x in center_exact])
    dots = [(v[0]-a[0])*(v[0]-b[0])+(v[1]-a[1])*(v[1]-b[1]) for v in exact]
    maximum = max(dots)
    return {
        'predicate': 'exact_thales_dot_on_binary64_vertices',
        'diameter_m': math.sqrt(float(squared)),
        'diameter_squared_exact': str(squared),
        'diameter_pair_indices_in_sorted_unique_vertices': list(pair),
        'diameter_endpoints': points[list(pair)].tolist(),
        'diameter_circle_center_fp64': center.tolist(),
        'diameter_circle_center_exact': [str(x) for x in center_exact],
        'diameter_circle_radius_m': math.sqrt(float(squared))/2,
        'diameter_circle_covers_vertices': maximum <= 0,
        'diameter_circle_is_mec': maximum <= 0,
        'max_thales_dot_exact': str(maximum),
        'thales_dot_signs': [int(value > 0)-int(value < 0) for value in dots],
        'outside_vertices': points[[i for i, value in enumerate(dots) if value > 0]].tolist(),
        'max_vertex_distance_to_fp64_midpoint_m': float(np.linalg.norm(points-center, axis=1).max()),
    }


def jung_classification(poly, safe_radius=19.999):
    """Classify by D² <= 3r², D² > 4r², or the inconclusive middle interval.

    Jung supplies existence only; it does not construct/validate a floating
    clearance point. The middle interval can contain both feasible sets and
    impossible ones, so no boolean success is inferred there.
    """
    radius = float(safe_radius)
    if not math.isfinite(radius) or radius < 0:
        raise ValueError('safe_radius must be finite and nonnegative')
    _, _, _, squared = _diameter_data(poly)
    radius_squared = Fraction(radius)**2
    if squared <= 3*radius_squared:
        classification, existence = 'GUARANTEED_NONEMPTY_BY_JUNG', True
    elif squared > 4*radius_squared:
        classification, existence = 'GUARANTEED_EMPTY_BY_DIAMETER', False
    else:
        classification, existence = 'INCONCLUSIVE_DIAMETER_INTERVAL', None
    return {
        'classification': classification,
        'certified_region_existence_from_diameter': existence,
        'safe_radius_m': radius,
        'diameter_m': math.sqrt(float(squared)),
        'diameter_squared_exact': str(squared),
        'jung_threshold_m_display_only': math.sqrt(3)*radius,
        'impossibility_threshold_m_display_only': 2*radius,
        'predicate': 'exact_D_squared_vs_3r_squared_and_4r_squared',
        'execution_certificate_provided': False,
    }


def audit_clearance_geometry(poly, safe_radius=19.999):
    """Return both independent audit records without consulting/changing MEC."""
    return {'diameter_circle': diameter_circle_audit(poly),
            'jung': jung_classification(poly, safe_radius)}
