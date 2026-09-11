"""Exact Q(sqrt(3)) mesh certificate and separate specified-engine finite checks."""
import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass
from decimal import Decimal, localcontext
from fractions import Fraction as F
import hashlib
import inspect
import itertools
import json
import math
from pathlib import Path
import sys

import numpy as np
from geometry import coverage, route

A, B = 970, 1870


@dataclass(frozen=True)
class S3:
    """A rational number plus a rational multiple of sqrt(3)."""
    a: F = F(0)
    b: F = F(0)

    def __add__(self, other):
        other = other if isinstance(other, S3) else S3(F(other))
        return S3(self.a + other.a, self.b + other.b)

    def __neg__(self):
        return S3(-self.a, -self.b)

    def __sub__(self, other):
        return self + (-other if isinstance(other, S3) else -F(other))

    def __mul__(self, other):
        other = other if isinstance(other, S3) else S3(F(other))
        return S3(self.a*other.a + 3*self.b*other.b,
                  self.a*other.b + self.b*other.a)

    def sign(self):
        if not self.b:
            return (self.a > 0) - (self.a < 0)
        if not self.a:
            return (self.b > 0) - (self.b < 0)
        if (self.a > 0) == (self.b > 0):
            return 1 if self.a > 0 else -1
        difference = self.a*self.a - 3*self.b*self.b
        return ((difference > 0) - (difference < 0)) * (1 if self.a > 0 else -1)

    def number(self):
        return float(self.a) + float(self.b)*math.sqrt(3)


def sub(p, q):
    return tuple(x-y for x, y in zip(p, q))


def cross(p, q):
    return p[0]*q[1] - p[1]*q[0]


def orient(p, q, r):
    return cross(sub(q, p), sub(r, p))


def dot(p, q):
    return p[0]*q[0] + p[1]*q[1]


def construct():
    axial = [(i, j) for i in range(-2, 3) for j in range(-2, 3)
             if max(abs(i), abs(j), abs(i+j)) <= 2]
    index = {p: k for k, p in enumerate(axial)}
    vertices = [(S3(F(A*(2*i+j), 2)), S3(F(0), F(A*j, 2))) for i, j in axial]
    vertices += [(S3(0, F(B, 2)), S3(F(B, 2))), (S3(), S3(F(B))),
                 (S3(0, F(-B, 2)), S3(F(B, 2))),
                 (S3(0, F(-B, 2)), S3(F(-B, 2))), (S3(), S3(F(-B))),
                 (S3(0, F(B, 2)), S3(F(-B, 2)))]
    triangles = []
    for i in range(-2, 3):
        for j in range(-2, 3):
            for triangle in (((i, j), (i+1, j), (i, j+1)),
                             ((i+1, j), (i+1, j+1), (i, j+1))):
                if all(p in index for p in triangle):
                    triangles.append(tuple(index[p] for p in triangle))
    assert len(triangles) == 24
    corners = [(2, 0), (0, 2), (-2, 2), (-2, 0), (0, -2), (2, -2)]
    boundary = []
    for k, corner in enumerate(corners):
        next_corner = corners[(k+1) % 6]
        middle = tuple((x+y)//2 for x, y in zip(corner, next_corner))
        u, m, v, q = index[corner], index[middle], index[next_corner], 19+k
        triangles.extend(((u, q, m), (m, q, v)))
        boundary.extend((u, q))
    return axial, vertices, triangles, boundary


def exact_mesh_check():
    axial, vertices, triangles, boundary = construct()
    assert len(vertices) == len(set(vertices)) == 25
    assert len(triangles) == len(set(tuple(sorted(t)) for t in triangles)) == 36
    assert set(itertools.chain.from_iterable(triangles)) == set(range(25))
    directed = Counter((t[k], t[(k+1) % 3]) for t in triangles for k in range(3))
    incidence = defaultdict(list)
    for t_index, triangle in enumerate(triangles):
        for k in range(3):
            incidence[tuple(sorted((triangle[k], triangle[(k+1) % 3])))].append(t_index)
    edges = sorted(incidence)
    boundary_edges = {(boundary[k], boundary[(k+1) % 12]) for k in range(12)}
    assert len(edges) == 60 and Counter(map(len, incidence.values())) == {1: 12, 2: 48}
    assert {edge for edge in directed if len(incidence[tuple(sorted(edge))]) == 1} == boundary_edges
    assert all(directed[(u, v)] == directed[(v, u)] == 1
               for (u, v), faces in incidence.items() if len(faces) == 2)
    assert 25 - len(edges) + len(triangles) == 1
    twice_areas = [orient(*(vertices[i] for i in t)) for t in triangles]
    assert all(value.sign() > 0 for value in twice_areas)
    assert sum(twice_areas, S3()) == S3(F(12*A*B))
    assert sum((cross(vertices[u], vertices[v]) for u, v in boundary_edges), S3()) == S3(F(12*A*B))
    # Every boundary edge is supporting; every other boundary vertex is strictly left.
    assert all(orient(vertices[u], vertices[v], vertices[w]).sign() > 0
               for u, v in boundary_edges for w in boundary if w not in (u, v))
    assert all(orient(vertices[u], vertices[v], p).sign() >= 0
               for u, v in boundary_edges for p in vertices)
    # Exact planar embedding: no vertex in a nonincident edge and no disjoint crossings.
    for u, v in edges:
        for w, p in enumerate(vertices):
            if w not in (u, v) and orient(vertices[u], vertices[v], p).sign() == 0:
                assert dot(sub(p, vertices[u]), sub(p, vertices[v])).sign() > 0
    for (u, v), (w, x) in itertools.combinations(edges, 2):
        if len({u, v, w, x}) < 4:
            continue
        signs = [orient(vertices[a], vertices[b], vertices[c]).sign()
                 for a, b, c in ((u, v, w), (u, v, x), (w, x, u), (w, x, v))]
        assert not (signs[0]*signs[1] < 0 and signs[2]*signs[3] < 0)
    for triangle in triangles:
        for w, point in enumerate(vertices):
            if w not in triangle:
                assert not all(orient(vertices[triangle[k]], vertices[triangle[(k+1) % 3]], point).sign() > 0
                               for k in range(3)), 'A triangle contains a nonincident vertex'
    reached = {0}
    while True:
        new = reached | {v for u, v in directed if u in reached}
        if new == reached:
            break
        reached = new
    assert len(reached) == 25
    # Exact squared diameter and disk-containment inequalities.
    delta = S3(F(B), F(-A))
    diameter_squared = S3(F(A*A)) + delta*delta
    edge_squared = [dot(sub(vertices[u], vertices[v]), sub(vertices[u], vertices[v])) for u, v in edges]
    assert all((diameter_squared-length).sign() >= 0 for length in edge_squared)
    assert all(length == S3(F(A*A)) for t in triangles[:24]
               for u, v in zip(t, t[1:]+t[:1])
               for length in [dot(sub(vertices[u], vertices[v]), sub(vertices[u], vertices[v]))])
    assert (S3(F(989*989))-diameter_squared).sign() > 0
    source_shift_radius = F('1806.000001')
    for u, v in boundary_edges:
        determinant = cross(vertices[u], vertices[v])
        length_squared = dot(sub(vertices[u], vertices[v]), sub(vertices[u], vertices[v]))
        assert determinant == S3(F(A*B)) and length_squared == diameter_squared
        assert (determinant*determinant-length_squared*(source_shift_radius**2)).sign() > 0
    # Prove a coordinate error bound for the actual FP64 nodes using rational sqrt bounds.
    with localcontext() as context:
        context.prec = 90
        scale = 10**70
        lower = F(int(Decimal(3).sqrt()*scale), scale)
    upper = lower + F(1, scale)
    assert lower*lower < 3 < upper*upper
    nodes = coverage(True, version='certified25')
    r = math.sqrt(3)
    literal = [[A*(i+j/2), A*r*j/2] for i, j in axial]
    literal += [[B*r/2, B/2], [0, B], [-B*r/2, B/2],
                [-B*r/2, -B/2], [0, -B], [B*r/2, -B/2]]
    assert np.array_equal(nodes, np.asarray(literal, dtype=float)), 'Runtime node order/coordinates differ'
    assert json.loads(json.dumps(nodes.tolist(), allow_nan=False)) == nodes.tolist()
    coordinate_error = F(0)
    for represented, exact in zip(nodes.ravel(), itertools.chain.from_iterable(vertices)):
        endpoints = (exact.a+exact.b*lower, exact.a+exact.b*upper)
        error = max(abs(F(float(represented))-endpoint) for endpoint in endpoints)
        coordinate_error = max(coordinate_error, error)
    assert coordinate_error < F(1, 10**10)
    # Thus Euclidean node error < 1e-9 m; strict witness margins survive serialization.
    length = math.sqrt(diameter_squared.number())
    return nodes, triangles, {
        'status': 'PASS', 'arithmetic': 'Exact rational arithmetic in Q(sqrt(3)); no geometric tolerance',
        'vertex_index_base': 0, 'vertices_m': nodes.tolist(), 'internal_axial_coordinates': axial,
        'vertices_exact_a_plus_b_sqrt3': [[[str(c.a), str(c.b)] for c in point] for point in vertices],
        'triangles_ccw': triangles, 'triangle_count': len(triangles),
        'edges': [{'vertices': edge, 'incident_triangles': incidence[edge]} for edge in edges],
        'edge_count': len(edges), 'interior_edge_count': 48, 'boundary_edge_count': 12,
        'boundary_ccw': boundary, 'euler_characteristic': 1, 'area_m2': 6*A*B,
        'embedding': 'Connected, no edge crossings/T junctions; matched opposite interior edges',
        'convexity': 'All other boundary vertices strictly left of each oriented boundary edge',
        'delta_m': delta.number(), 'max_triangle_diameter_m': length,
        'inradius_m': A*B/length, 'required_shifted_source_radius_m': float(source_shift_radius),
        'source_disk_inclusion_margin_m': A*B/length-float(source_shift_radius),
        'strict_ideal_witness_projection_min_m': 6., 'strict_ideal_witness_distance_max_m': length+6,
        'coordinate_error_upper_bound_m': float(coordinate_error),
        'certified_euclidean_representation_error_bound_m': 1e-9,
        'represented_witness_projection_lower_bound_m': 6.-1e-9,
        'represented_witness_distance_upper_bound_m': length+6+1e-9,
        'continuous_proof': 'COVERAGE25.md; engine samples below are separate finite evidence',
    }


def engine_check(sim_root, nodes, triangles):
    sim_root = sim_root.resolve()
    sys.path.insert(0, str(sim_root))
    import engine
    assert Path(engine.__file__).resolve() == sim_root/'engine.py'
    Engine, Jammer, Scenario = engine.Engine, engine.Jammer, engine.Scenario

    def scene(point, direction, radius=1000., kind='directional'):
        value = Scenario('0123456789abcdef', 4,
                         (Jammer(1, float(point[0]), float(point[1]), radius, kind, direction),))
        return Scenario.from_dict(json.loads(json.dumps(value.to_dict(), allow_nan=False)))

    def observe(point, direction=0., source=(0., 0.), radius=1000., kind='directional'):
        e = Engine(scene(source, direction, radius, kind))
        assert e.apply('/enter', {})['accepted']
        request = json.loads(json.dumps({'position': {'x': float(point[0]), 'y': float(point[1])},
                                         'channel': 1}, allow_nan=False))
        reply = e.apply('/measure', request)
        assert reply['accepted']
        return reply

    boundaries = [
        ('coincidence_near', (0., 0.), 180., 'near'),
        ('near_closed_5m', (5., 0.), 0., 'near'),
        ('near_next_float_outside', (math.nextafter(5., math.inf), 0.), 0., 'direction'),
        ('radius_closed_1000m', (1000., 0.), 0., 'direction'),
        ('radius_next_float_outside', (math.nextafter(1000., math.inf), 0.), 0., 'no_signal'),
        ('halfplane_boundary', (0., 1000.), 0., 'direction'),
        ('angle_engine_tolerance_inside', (700., 0.), 90.+0.5e-9, 'direction'),
        ('angle_engine_tolerance_outside', (700., 0.), 90.+2e-9, 'no_signal'),
        ('opposite_no_near_exception', (-5., 0.), 0., 'no_signal'),
    ]
    boundary_results = []
    for label, point, direction, expected in boundaries:
        reply = observe(point, direction)
        assert reply['measure_result'] == expected, (label, reply)
        boundary_results.append({'case': label, 'point_m': point, 'direction_deg': direction,
                                 'expected': expected, 'reply': reply})
    assert all(engine.normalize(value) == 0. for value in (0., -0., 360., -360., 720.))
    assert observe((700., 0.), engine.normalize(360.)) == observe((700., 0.), 0.)
    try:
        scene((0., 0.), 360.)
    except ValueError:
        pass
    else:
        raise AssertionError('Expected scenario parser to reject unnormalized source angle 360')
    scene((1800.000001, 0.), 0.)
    try:
        scene((math.nextafter(1800.000001, math.inf), 0.), 0.)
    except ValueError:
        pass
    else:
        raise AssertionError('Expected exact source-domain tolerance enforcement')

    points = set()
    internal = [tuple(p) for p in nodes[:19] if math.hypot(*p) <= 1800]
    for p in internal:
        points.add(p)
        for offset in (1e-8, -1e-8, 1e-4, -1e-4):
            points.update(((p[0]+offset, p[1]), (p[0], p[1]+offset)))
    for t in triangles:
        for i in range(3):
            p, q = nodes[t[i]], nodes[t[(i+1) % 3]]
            for fraction in (1/3, 1/2, 2/3):
                value = p+fraction*(q-p)
                if math.hypot(*value) <= 1800:
                    points.add(tuple(value))
    for direction in range(0, 360, 3):
        radians = math.radians(direction)
        points.add((1800*math.cos(radians), 1800*math.sin(radians)))
    points.add((1800.000001, 0.))
    mesh = nodes[np.asarray(triangles)]
    e1, e2 = mesh[:, 1]-mesh[:, 0], mesh[:, 2]-mesh[:, 0]
    determinants = e1[:, 0]*e2[:, 1]-e1[:, 1]*e2[:, 0]
    observed_min_projection, observed_max_distance, count = math.inf, 0., 0
    test_angle_normalization_edge_cases = []

    def witness_case(point, direction):
        nonlocal observed_min_projection, observed_max_distance, count
        raw_direction = direction
        direction = engine.normalize(direction)
        # fmod(tiny_negative)+360 can round to 360. Record the actual engine
        # behavior, then express this generated test angle as legal equivalent 0.
        if direction == 360.:
            test_angle_normalization_edge_cases.append({
                'raw_direction_deg': raw_direction, 'engine_normalize_result': direction,
                'legal_test_direction_deg': 0., 'source_m': point})
            direction = 0.
        u = np.array([math.cos(math.radians(direction)), math.sin(math.radians(direction))])
        z = np.asarray(point)+6*u
        relative = z-mesh[:, 0]
        w1 = (relative[:, 0]*e2[:, 1]-relative[:, 1]*e2[:, 0])/determinants
        w2 = (e1[:, 0]*relative[:, 1]-e1[:, 1]*relative[:, 0])/determinants
        containing = np.flatnonzero((w1 >= -1e-11) & (w2 >= -1e-11) & (w1+w2 <= 1+1e-11))
        assert len(containing), {'source': point, 'direction': direction, 'z': z.tolist()}
        triangle = mesh[containing[0]]
        projections = (triangle-point)@u
        q = triangle[int(np.argmax(projections))]
        projection = float(np.max(projections))
        distance = math.hypot(*(q-point))
        assert projection > 5.9999999 and 5. < distance < 1000., (point, direction, q)
        reply = observe(q, direction, point)
        assert reply['measure_result'] == 'direction', {
            'source': point, 'direction': direction, 'witness': q.tolist(), 'reply': reply}
        observed_min_projection = min(observed_min_projection, projection)
        observed_max_distance = max(observed_max_distance, distance)
        count += 1

    for point in sorted(points):
        for direction in (*range(0, 360, 15), -360., 360., math.nextafter(360., 0.)):
            witness_case(point, direction)
    # Target every node's half-plane boundary for legal grid points and circle points.
    direction_boundary_sources = internal+[(1800*math.cos(k*math.pi/6), 1800*math.sin(k*math.pi/6)) for k in range(12)]
    for point in direction_boundary_sources:
        for node in nodes:
            if np.array_equal(node, point):
                continue
            alpha = math.degrees(math.atan2(node[1]-point[1], node[0]-point[0]))
            for sign in (-1, 1):
                for perturbation in (-1e-7, 0., 1e-7):
                    witness_case(point, alpha+sign*90+perturbation)
    omni_checks = 0
    for point in internal:
        nearby = nodes[np.argmin(np.linalg.norm(nodes-point, axis=1))]
        assert observe(nearby, 0., point, kind='omni')['measure_result'] == 'near'
        omni_checks += 1
    return {
        'status': 'PASS', 'evidence': 'FINITE REAL SPECIFIED-ENGINE CHECKS; not a continuous proof or full-game result',
        'engine_path': str(Path(engine.__file__).resolve()),
        'engine_sha256': hashlib.sha256(Path(engine.__file__).read_bytes()).hexdigest(),
        'scene_parser': 'Scenario.from_dict after JSON serialization; all witnesses use actual Engine.apply',
        'source_position_count': len(points), 'source_direction_witness_cases': count,
        'all_witnesses_returned_accepted_direction': True,
        'min_observed_projection_m': observed_min_projection, 'max_observed_distance_m': observed_max_distance,
        'omni_coincidence_checks': omni_checks, 'boundary_checks': boundary_results,
        'zero_360_normalization': 'PASS; normalize(360)=0; raw scenario angle 360 correctly rejected',
        'test_angle_normalization_edge_cases': test_angle_normalization_edge_cases,
        'source_radius_1800_000001_boundary': 'PASS; next representable outside value rejected',
    }


def check(sim_root):
    nodes, triangles, result = exact_mesh_check()
    result['engine_checks'] = engine_check(sim_root, nodes, triangles)
    routes, lengths = {}, {}
    for version in ('certified37', 'certified25'):
        path = route(coverage(True, version=version), np.zeros(2))
        routes[version] = path.tolist()
        lengths[version] = float(np.linalg.norm(np.diff(np.vstack(([0., 0.], path)), axis=0), axis=1).sum())
    result['static_routes_m'] = routes
    result['static_route_m'] = lengths
    result['static_distance_reduction_percent'] = 100*(1-lengths['certified25']/lengths['certified37'])
    result['static_movement_saving_s_at_5mps'] = (lengths['certified37']-lengths['certified25'])/5
    result['route_function_sha256'] = hashlib.sha256(inspect.getsource(route).encode()).hexdigest()
    result['static_route_scope'] = 'Origin-start open discovery tours only; no localization actions or global optimality claim'
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sim-root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    try:
        result = check(args.sim_root)
    except Exception as error:
        args.output.write_text(json.dumps({'status': 'FAIL', 'error_type': type(error).__name__,
                                          'minimal_failure_context': str(error)}, indent=2), encoding='utf-8')
        raise
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False), encoding='utf-8')
    print(json.dumps({key: result[key] for key in ('status', 'triangle_count', 'edge_count',
                     'boundary_edge_count', 'area_m2', 'max_triangle_diameter_m', 'inradius_m',
                     'static_route_m', 'static_distance_reduction_percent', 'static_movement_saving_s_at_5mps')}))
    print(json.dumps({key: result['engine_checks'][key] for key in
                     ('status', 'source_position_count', 'source_direction_witness_cases',
                      'min_observed_projection_m', 'max_observed_distance_m')}))


if __name__ == '__main__':
    main()
