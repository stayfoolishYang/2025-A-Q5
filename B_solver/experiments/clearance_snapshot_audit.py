"""Three landing rules on the same archived certificate, with a fixed next action.

No engine is run. The exact support-circle check is an offline audit only.
It does not replace the online FP64 MEC or extend its clearance trigger.
"""
import argparse
import csv
from fractions import Fraction as F
import gzip
import hashlib
from itertools import combinations
import json
import math
from pathlib import Path
import sys
from time import perf_counter_ns

import numpy as np

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))
from geometry import nearest_certified_clear_point, segment_certified_clear_point
from clearance_geometry_audit import diameter_circle_audit


def sq(a, b):
    return sum((x-y)**2 for x, y in zip(a, b))


def exact_mec_witness(poly):
    """A covering diameter circle or acute support triple certifies minimality.

    # ponytail: exhaustive triples are for tiny offline polygons only; use a
    # certified geometry library if archived polygons become substantially larger.
    """
    data = diameter_circle_audit(poly)
    if data['diameter_circle_is_mec']:
        return tuple(map(F, data['diameter_circle_center_exact'])), F(data['diameter_squared_exact'])/4, 2
    points = [tuple(F(float(x)) for x in p) for p in np.unique(poly, axis=0)]
    for a, b, c in combinations(points, 3):
        if any(sum((q[k]-p[k])*(r[k]-p[k]) for k in (0, 1)) < 0
               for p, q, r in ((a,b,c), (b,a,c), (c,a,b))):
            continue
        u, v = tuple(b[k]-a[k] for k in (0,1)), tuple(c[k]-a[k] for k in (0,1))
        det = 2*(u[0]*v[1]-u[1]*v[0])
        if not det:
            continue
        uu, vv = sum(x*x for x in u), sum(x*x for x in v)
        center = (a[0]+(v[1]*uu-u[1]*vv)/det, a[1]+(u[0]*vv-v[0]*uu)/det)
        radius2 = sq(center, a)
        if all(sq(center, p) <= radius2 for p in points):
            return center, radius2, 3
    raise ArithmeticError('No exact MEC support witness found')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def snapshot(trace, event, channel, ordinal):
    poly, x, center = (np.array(event[k], dtype=float) for k in ('polygon', 'start', 'mec_center'))
    actions = trace['actions']
    matches = [i for i, a in enumerate(actions) if a['path']=='/clear' and a['channel']==channel
               and a['position']==event['point'] and a['response']['virtual_time_s']==event['time_after']]
    assert len(matches)==1
    following = next((a for a in actions[matches[0]+1:] if a.get('position') is not None), None)
    y = np.array(following['position']) if following else None
    exact_center, radius2, supports = exact_mec_witness(poly)
    delta2 = F(19.999)**2-radius2
    assert delta2 >= 0
    center_error = math.sqrt(float(sq(tuple(F(float(v)) for v in center), exact_center)))
    bound = math.sqrt(float(delta2))/5
    record = dict(channel=channel, ordinal=ordinal, action_index=matches[0], vertex_count=len(poly),
                  mec_radius_stored=event['mec_radius'], true_mec_radius=math.sqrt(float(radius2)),
                  exact_radius_squared=str(radius2), exact_center=json.dumps([str(v) for v in exact_center]),
                  support_size=supports, stored_center_error_m=center_error,
                  refined_bound_s_numeric_display=bound,
                  stored_center_adjusted_bound_s_numeric_display=bound+center_error/5,
                  next_action=json.dumps(following, separators=(',', ':')) if following else None,
                  baseline_terminal_distance_m=float(np.linalg.norm(x-center)))
    for name, select in (('nccp', nearest_certified_clear_point), ('segment', segment_certified_clear_point)):
        started = perf_counter_ns()
        point, meta = select(poly, x, 19.999, center, event['mec_radius'])
        elapsed = (perf_counter_ns()-started)/1e6
        # Verify precisely the round-tripped coordinates that would be submitted.
        point = np.array(json.loads(json.dumps(point.tolist(), allow_nan=False)))
        exact_point = tuple(F(float(v)) for v in point)
        assert all(sq(tuple(F(float(v)) for v in p), exact_point) <= F(19.999)**2 for p in poly)
        assert sq(tuple(F(float(v)) for v in x), exact_point) <= sq(tuple(F(float(v)) for v in x), tuple(F(float(v)) for v in center))
        distance = float(np.linalg.norm(x-point))
        saving = (record['baseline_terminal_distance_m']-distance)/5
        # This is only a sanity check of displayed square roots, not a relaxed safety certificate.
        assert saving <= bound+center_error/5+1e-9
        twoleg = distance+float(np.linalg.norm(point-y))-record['baseline_terminal_distance_m']-float(np.linalg.norm(center-y)) if y is not None else None
        if name=='segment' and twoleg is not None:
            assert twoleg <= 1e-9, 'Segment entry worsened a fixed-next-waypoint route'
        record.update({name+'_point':json.dumps(point.tolist()), name+'_rho_m':float(np.linalg.norm(poly-point,axis=1).max()),
                       name+'_travel_m':distance, name+'_saving_s':saving, name+'_compute_ms':elapsed,
                       name+'_status':meta['mode'], name+'_fallback':bool(meta['fallback']),
                       name+'_fixed_next_twoleg_delta_m':twoleg})
    return record


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    a.output.mkdir(parents=True, exist_ok=False)
    source_files = [Path(__file__), BASE/'geometry.py', Path(__file__).with_name('clearance_geometry_audit.py')]
    plan = dict(scope='All polygon certificates in the baseline MEC traces of both frozen cohorts; same state and fixed original next action',
                source_hashes={str(f):sha(f) for f in source_files}, formal_runs=0,
                timing='Single-call wall clock on this host; includes exact certification, excludes support-circle audit; not an isolated CPU benchmark',
                tight_bound='Exact support circle of supplied binary64 vertices; square roots are numerical displays, with stored-center error explicitly separated')
    rows, inputs = [], {}
    with (a.output/'cases.csv').open('x', newline='', encoding='utf-8-sig') as f:
        writer = None
        for cohort in ('development100', 'holdout256'):
            folder = a.root/cohort
            manifest = json.loads((folder/'manifest.json').read_text(encoding='utf-8'))
            for problem in (3,4):
                config = manifest['configs'][str(problem)][0]
                for seed in manifest['seeds']:
                    path = folder/f'q{problem}'/'traces'/f"{config['name']}_{seed['seed']:04d}.json.gz"
                    inputs[str(path)] = sha(path)
                    with gzip.open(path, 'rt', encoding='utf-8') as stream:
                        trace = json.load(stream)
                    for target in trace['targets']:
                        for ordinal, event in enumerate(target.get('certified_clearance_events', [])):
                            row = dict(cohort=cohort, problem=problem, seed=seed['seed'], total=trace['row']['total'],
                                       **snapshot(trace, event, target['channel'], ordinal))
                            if writer is None:
                                writer = csv.DictWriter(f, fieldnames=list(row)); writer.writeheader()
                            writer.writerow(row); rows.append(row)
                    if seed['seed'] % 25==0:
                        f.flush(); print(f'{cohort} Q{problem} seed {seed["seed"]}: {len(rows)} snapshots', flush=True)
    summaries = {}
    for problem in (3,4):
        group = [r for r in rows if r['problem']==problem]
        summaries[str(problem)] = dict(n=len(group),
            metrics={key:dict(mean=float(np.mean([r[key] for r in group])), p50=float(np.median([r[key] for r in group])),
                             p95=float(np.percentile([r[key] for r in group],95)), maximum=max(r[key] for r in group))
                     for key in ('true_mec_radius', 'refined_bound_s_numeric_display', 'stored_center_error_m',
                                 'nccp_saving_s', 'segment_saving_s', 'nccp_compute_ms', 'segment_compute_ms')},
            nccp_fixed_next_regressions=sum(r['nccp_fixed_next_twoleg_delta_m'] is not None and r['nccp_fixed_next_twoleg_delta_m']>1e-9 for r in group),
            segment_fixed_next_regressions=sum(r['segment_fixed_next_twoleg_delta_m'] is not None and r['segment_fixed_next_twoleg_delta_m']>1e-9 for r in group),
            nccp_fallbacks=sum(r['nccp_fallback'] for r in group), segment_fallbacks=sum(r['segment_fallback'] for r in group))
    assert all(sha(f)==value for f,value in plan['source_hashes'].items())
    plan['inputs_sha256'] = inputs
    (a.output/'PLAN.json').write_text(json.dumps(plan,indent=2), encoding='utf-8')
    (a.output/'SUMMARY.json').write_text(json.dumps(dict(passed=True, n=len(rows), problems=summaries,
        cases_sha256=sha(a.output/'cases.csv'), plan_sha256=sha(a.output/'PLAN.json')),indent=2),encoding='utf-8')


if __name__ == '__main__':
    main()
