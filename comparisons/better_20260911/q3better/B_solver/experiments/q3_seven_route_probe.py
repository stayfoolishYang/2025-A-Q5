"""Q3 seven-node pilot: reuse the existing post-localization route refresh."""
import argparse
import csv
import gzip
import hashlib
import json
import os
from pathlib import Path
import sys
import time

os.environ.update(OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1')
BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))
import numpy as np
import discovery
from phase_audit import TaggedSolver
from recovered_benchmark import EngineAdapter, digest, save, source_hashes
from q3_stop16_pilot import CONFIG, audit


def path_length(points, start):
    return float(np.linalg.norm(np.diff(np.vstack((start, points)), axis=0), axis=1).sum())


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--sim-root', type=Path, required=True)
    p.add_argument('--source', type=Path, default=BASE/'results/q3_stop16_pilot_01')
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--count', type=int, default=32)
    a = p.parse_args()
    assert 1 <= a.count <= 32
    sim, source, out = a.sim_root.resolve(), a.source.resolve(), a.output.resolve()
    if out.exists():
        raise FileExistsError('Use a new output directory; never overwrite evidence')
    sys.path.insert(0, str(sim))
    from engine import Engine
    from scenario_io import load_scenario
    original = discovery.refresh_remaining_route
    assert original([], np.zeros(2)) == []
    manifest = json.loads((source/'manifest.json').read_bytes())
    records = [r for r in manifest['records'] if r['cohort'] == 'pilot32'][:a.count]
    hashes = source_hashes(sim)
    assert hashes == manifest['source_hashes'], 'Baseline source changed since original pilot'
    out.mkdir(parents=True)
    (out/'traces').mkdir()
    save(out/'manifest.json', dict(records=records, source_directory=str(source), config=CONFIG,
        variants={'A': 'Q3 original seven nodes, legacy scheduling and stop',
                  'B': 'Same Q3 with existing refresh_after_localize hook enabled on pilot instance'},
        simulator_root=str(sim), source_hashes=hashes, python=sys.version, executable=sys.executable,
        script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        execution_backend='LOCAL_DEV', execution_purpose='FRAMEWORK_INTEGRATION', production_eligible=False,
        scope='32 reused exploratory scenes; no new holdout, no HTTP, no default changes, no truth in online policy'))
    rows, pairs = [], []
    for rec in records:
        raw = json.loads((source/rec['file']).read_bytes())
        assert digest(raw) == rec['scene_hash']
        with gzip.open(source/'traces'/f'A_{rec["id"]:03d}.json.gz', 'rt', encoding='utf-8') as f:
            historical = json.load(f)
        pair_rows = []
        for variant in 'AB':
            events = []
            def checked_refresh(nodes, current):
                refreshed = original(nodes, current)
                before, after = path_length(nodes, current), path_length(refreshed, current)
                assert sorted(map(tuple, nodes)) == sorted(map(tuple, refreshed))
                assert after <= before + 1e-8
                events.append(dict(position=np.asarray(current).tolist(), before_nodes=np.asarray(nodes).tolist(),
                    after_nodes=np.asarray(refreshed).tolist(), before_m=before, after_m=after,
                    changed=not np.array_equal(nodes, refreshed)))
                return refreshed
            engine = Engine(load_scenario(raw))
            api = EngineAdapter(engine)
            solver = TaggedSolver(api, False, 'P3', diagnostic=CONFIG)
            # Pilot only: reuse a tested Q4 hook; Q3 constructor guard and defaults remain intact.
            if variant == 'B':
                solver.discovery_route = 'refresh_after_localize'
                discovery.refresh_remaining_route = checked_refresh
            start, error, result, nodes = time.perf_counter(), '', {}, None
            baseline_match = None
            try:
                result = solver.run()
                nodes = audit(api.log, False)
                assert not solver.tracks
                assert engine.cleared == {j.channel for j in engine.scenario.jammers}
                if variant == 'A':
                    baseline_match = api.log == historical['actions']
                    assert baseline_match, 'Fresh A diverged from historical action log'
            except Exception as e:
                error = repr(e)
            finally:
                discovery.refresh_remaining_route = original
            row = dict(id=rec['id'], variant=variant, total=rec['total'], cleared=len(engine.cleared),
                virtual_time_s=api.virtual_time, seconds_per_source=api.virtual_time/rec['total'],
                runtime_s=time.perf_counter()-start, full_clear=len(engine.cleared)==rec['total'],
                audit_passed=not error, error=error, nodes=nodes, completion_reason=result.get('completion_reason'),
                baseline_exact_match=baseline_match, distance_m=api.distance, measures=api.measures,
                switches=api.switches, clear_attempts=api.clear_attempts, fallbacks=solver.fallbacks,
                refresh_calls=len(events), route_changes=sum(e['changed'] for e in events), scene_hash=rec['scene_hash'])
            for stage, metrics in api.stages.items():
                row[stage+'_s'] = metrics['total_s']
            rows.append(row)
            pair_rows.append(row)
            with gzip.open(out/'traces'/f'{variant}_{rec["id"]:03d}.json.gz', 'wt', encoding='utf-8') as f:
                json.dump(dict(row=row, actions=api.log, targets=list(solver.trace.values()), stages=api.stages,
                               refresh_events=events), f)
        baseline, candidate = pair_rows
        saved = baseline['virtual_time_s']-candidate['virtual_time_s']
        pair = dict(id=rec['id'], total=rec['total'], saved_total_s=saved, saved_s_per_source=saved/rec['total'],
            both_success=all(r['full_clear'] and r['audit_passed'] for r in pair_rows),
            baseline_exact_match=baseline['baseline_exact_match'])
        pairs.append(pair)
        save(out/'rows'/f'{rec["id"]:03d}.json', dict(rows=pair_rows, pair=pair))
        print(f'{len(pairs)}/{len(records)} scene={rec["id"]} saved={saved:.6f}s pass={pair["both_success"]}', flush=True)
    assert source_hashes(sim) == hashes
    for name, data in (('cases.csv', rows), ('pairs.csv', pairs)):
        with (out/name).open('w', newline='', encoding='utf-8-sig') as f:
            w = csv.DictWriter(f, fieldnames=list(data[0])); w.writeheader(); w.writerows(data)
    variants = {}
    for variant in 'AB':
        rr = [r for r in rows if r['variant'] == variant]
        tt = [r['seconds_per_source'] for r in rr]
        variants[variant] = dict(n=len(rr), full=sum(r['full_clear'] for r in rr),
            mean_total_s=float(np.mean([r['virtual_time_s'] for r in rr])), mean_per_source_s=float(np.mean(tt)),
            p95_per_source_s=float(np.percentile(tt, 95)), p99_per_source_s=float(np.percentile(tt, 99)),
            mean_stages_s={stage:float(np.mean([r[stage+'_s'] for r in rr])) for stage in api.stages})
    summary = dict(variants=variants, mean_saved_total_s=float(np.mean([r['saved_total_s'] for r in pairs])),
        mean_saved_per_source_s=float(np.mean([r['saved_s_per_source'] for r in pairs])),
        wins=sum(r['saved_total_s']>1e-6 for r in pairs), losses=sum(r['saved_total_s'] < -1e-6 for r in pairs),
        ties=sum(abs(r['saved_total_s'])<=1e-6 for r in pairs),
        worst_pair=min(pairs, key=lambda r:r['saved_total_s']), best_pair=max(pairs, key=lambda r:r['saved_total_s']),
        refresh_calls=sum(r['refresh_calls'] for r in rows), route_changes=sum(r['route_changes'] for r in rows),
        all_integrity_passed=all(r['both_success'] and r['baseline_exact_match'] for r in pairs))
    save(out/'summary.json', summary)
    print(json.dumps(summary), flush=True)
    assert summary['all_integrity_passed']


if __name__ == '__main__':
    main()
