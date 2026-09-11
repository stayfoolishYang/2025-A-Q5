"""Frozen, per-case subprocess evaluation of the supplied recovered practice engine.

No HTTP service or official application is started. Scene truth stays in the
evaluator; the online Solver uses its existing observation-only interface.
"""
import argparse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
import csv
import gzip
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import subprocess
import sys
import time

import numpy as np

BASE = Path(__file__).resolve().parent
STAGES = ('discovery', 'active_localization', 'diagnostic', 'optical_fallback', 'certified_clear')


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')


def frozen_seeds():
    patterns = [bytes(32), bytes([255])*32, bytes(range(32)), bytes(range(31,-1,-1)),
                bytes([170])*32, bytes([85])*32]
    records = [dict(seed_hex=s.hex(), family='byte_pattern') for s in patterns]
    records += [dict(seed_hex=(1 << bit).to_bytes(32, 'big').hex(), family='one_bit') for bit in range(256)]
    records += [dict(seed_hex=hashlib.sha256(f'2026B-recovered-validation-v1:{i}'.encode()).hexdigest(),
                     family='sha256_new_design') for i in range(256)]
    records.append(dict(seed_hex='b31d2f6ecf0c7b9f340ec3f739320e8f6e36a50ec3be20b6c5e6f20ca441f1f3',
                        family='supplied_all_directional_fixture'))
    assert len({r['seed_hex'] for r in records}) == len(records)
    return [dict(seed=i, **r) for i, r in enumerate(records)]


def source_hashes(sim_root):
    paths = list(BASE.glob('*.py')) + list((BASE/'directional').glob('*.py'))
    result = {'solver/'+str(p.relative_to(BASE)).replace('\\','/'): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in paths}
    for name in ('engine.py', 'scenario_io.py', 'recovered_generator.py'):
        result['engine/'+name] = hashlib.sha256((sim_root/name).read_bytes()).hexdigest()
    return result


def freeze(out, sim_root, grid_version):
    from scenario_io import generate_document
    if (out/'manifest.json').exists():
        raise FileExistsError('Use a new output directory, or --resume with the frozen manifest')
    configs = []
    for stem in ('baseline', 'route_only', 'diag_v1'):
        cfg = json.loads((BASE/'configs'/f'q4_p4_{stem}.yaml').read_text())
        cfg.update(name=cfg['name']+'_'+grid_version, grid_version=grid_version)
        configs.append(cfg)
    q3 = dict(name='P3_current_'+grid_version, enabled=False, local_order=False,
              particles=16384, grid_version=grid_version)
    seeds = frozen_seeds()
    scene_hashes = {}
    for rec in seeds:
        for problem in (3,4):
            scene = generate_document(seed_hex=rec['seed_hex'], problem=problem, format='native')
            filename = f'q{problem}_{rec["seed"]:04d}.json'
            save(out/'scenes'/filename, scene)
            scene_hashes[filename] = digest(scene)
    import io
    import contextlib
    info = io.StringIO()
    with contextlib.redirect_stdout(info):
        np.show_config()
    save(out/'manifest.json', dict(schema='recovered-benchmark-v1', seeds=seeds,
        configs={'3':[q3], '4':configs}, grid_version=grid_version,
        git_commit=subprocess.check_output(['git','rev-parse','HEAD'], text=True).strip(),
        source_hashes=source_hashes(sim_root), scene_hashes=scene_hashes, simulator_root=str(sim_root),
        python=sys.version, executable=sys.executable, numpy=np.__version__, blas=info.getvalue(),
        platform=platform.platform(), evidence='recovered_practice_engine_local',
        seed_design='New explicit 519-seed set; NOT the historical 518-seed receipts or official case seeds.',
        algorithm_changes='Only optional grid version. No first-hit recovery or retuning.',
        limits=dict(real_s=1200, virtual_s=360000), formal_tests=0))


class ProtocolError(RuntimeError):
    pass


def validated_inputs(out, seed, problem, variant):
    manifest = json.loads((out/'manifest.json').read_text(encoding='utf-8'))
    config = next(c for c in manifest['configs'][str(problem)] if c['name'] == variant)
    name = f'q{problem}_{seed:04d}.json'
    raw = json.loads((out/'scenes'/name).read_text(encoding='utf-8'))
    if digest(raw) != manifest['scene_hashes'][name]:
        raise RuntimeError(f'Frozen scene fingerprint mismatch: {name}')
    if raw['generator_seed_hex'] != manifest['seeds'][seed]['seed_hex'] or raw['problem_no'] != problem:
        raise RuntimeError('Frozen scene identity mismatch')
    return manifest, config, raw


def validate_row(row, manifest, config, raw, seed, problem, variant, device=None):
    expected = dict(seed=seed, problem=problem, variant=variant, scene_hash=digest(raw),
                    config_hash=digest(config), source_hash=digest(manifest['source_hashes']),
                    total=len(raw['jammers']))
    if device is not None:
        expected['device'] = device
    if any(row.get(k) != v for k,v in expected.items()):
        raise RuntimeError(f'Stale or inconsistent case result: Q{problem} {variant} {seed}')


class EngineAdapter:
    def __init__(self, engine):
        self._engine = engine
        self.position = np.zeros(2)
        self.channel = 1
        self.virtual_time = 0.
        self.stage = 'discovery'
        self.log = []
        self.started_at = None
        self.distance = 0.
        self.switches = self.measures = self.clear_attempts = 0
        self.stages = {s:dict(travel_m=0., travel_s=0., switch_s=0., measure_s=0., clear_s=0., total_s=0., actions=0)
                       for s in STAGES}

    def action(self, path, position=None, channel=None):
        if self.started_at is not None and time.perf_counter()-self.started_at >= 1200:
            raise TimeoutError('Local runner real-time limit')
        if self._engine.ended and self._engine.end_reason == 'virtual_timeout':
            raise TimeoutError('Recovered engine virtual-time limit')
        request = {}
        if position is not None:
            p = np.asarray(position, dtype=float)
            if p.shape != (2,) or not np.isfinite(p).all() or np.abs(p).max() > 2000000:
                raise ProtocolError('Invalid coordinate')
            if isinstance(channel, bool) or not isinstance(channel, (int, np.integer)) or not 1 <= channel <= 20:
                raise ProtocolError('Invalid channel')
            request = dict(position=dict(x=float(p[0]), y=float(p[1])), channel=int(channel))
        before = self.virtual_time
        response = self._engine.apply(path, request)
        row = dict(path=path, stage=self.stage, position=p.tolist() if position is not None else None,
                   channel=channel, response=response)
        self.log.append(row)
        if response.get('accepted') is not True:
            raise ProtocolError(f'Recovered engine rejected {path}: {response}')
        after = float(response['virtual_time_s'])
        if not math.isfinite(after) or after < before-1e-6:
            raise ProtocolError('Nonfinite or decreasing virtual time')
        self.virtual_time = after
        if path == '/enter':
            self.started_at = time.perf_counter()
        if position is not None:
            length = float(np.linalg.norm(p-self.position))
            switch = int(path == '/measure' and channel != self.channel)
            measure = 5 if path == '/measure' else 0
            clear = (5 if response.get('clear_result') == 'success' else 3) if path == '/clear' else 0
            elapsed = after-before
            if abs(elapsed-(length/5+switch+measure+clear)) > 1.1e-6:
                raise ProtocolError('Per-action time ledger mismatch')
            costs = dict(travel_m=length, travel_s=elapsed-switch-measure-clear,
                         switch_s=switch, measure_s=measure, clear_s=clear, total_s=elapsed, actions=1)
            for key, value in costs.items():
                self.stages[self.stage][key] += value
            self.position = p.copy()
            self.distance += length
            self.switches += switch
            self.measures += int(path == '/measure')
            self.clear_attempts += int(path == '/clear')
            if path == '/measure':
                self.channel = int(channel)
            row.update(position=p.tolist(), **costs)
        return response


def run_single(out, sim_root, seed, problem, variant, device):
    from engine import Engine
    from scenario_io import load_scenario
    from phase_audit import TaggedSolver
    from geometry import contains
    manifest, config, raw = validated_inputs(out, seed, problem, variant)
    if source_hashes(sim_root) != manifest['source_hashes']:
        raise RuntimeError('Source fingerprint changed since freeze; refuse mixed-version benchmark')
    engine = Engine(load_scenario(raw))
    api = EngineAdapter(engine)

    class AuditedSolver(TaggedSolver):
        def measure(self, c, p):
            super().measure(c, p)
            if c in self.tracks:
                truth = engine.sources[c]
                if not contains(self.tracks[c]['poly'], [truth.x, truth.y], tolerance=1e-5)[0]:
                    raise AssertionError(f'Outer polygon lost truth on channel {c}')

    solver = AuditedSolver(api, problem == 4, 'P4' if problem == 4 else 'P3', device,
                           config.get('particles',16384), diagnostic=config)
    start = time.perf_counter()
    error = ''
    status = ''
    try:
        solver.run()
    except TimeoutError as exc:
        status, error = 'TIMEOUT', repr(exc)
    except ProtocolError as exc:
        status, error = 'PROTOCOL_ERROR', repr(exc)
    except Exception as exc:
        status, error = 'EXCEPTION', repr(exc)
    duration = time.perf_counter()-start
    if engine.end_reason == 'virtual_timeout' or duration >= 1200:
        status, error = 'TIMEOUT', error or 'Execution budget exhausted'
    total, cleared = len(engine.sources), len(engine.cleared)
    if not status:
        status = 'FULL_CLEAR' if total == cleared else 'PARTIAL_CLEAR' if cleared else 'ZERO_CLEAR'
    traces = list(solver.trace.values())
    clearance_events = [event for target in traces for event in target.get('certified_clearance_events', [])]
    rec = manifest['seeds'][seed]
    row = dict(seed=seed, seed_hex=rec['seed_hex'], stress=rec['family'], problem=problem,
        variant=variant, run_status=status, engine_end_reason=engine.end_reason,
        total=total, cleared=cleared, clear_rate=cleared/total,
        error=error, mean_time_per_source=api.virtual_time/total, virtual_time_s=api.virtual_time,
        distance=api.distance, runtime=duration, device=device,
        fallback_count=solver.fallbacks, grid_points=sum(t['optical_grid_points'] for t in traces),
        clear_attempts=api.clear_attempts, optical_clear_attempts=sum(t['optical_clear_attempts'] for t in traces),
        diagnostic_count=sum(t['diagnostic_count'] for t in traces), detect_count=api.measures,
        switch_count=api.switches, config_hash=digest(config), scene_hash=digest(raw),
        source_hash=digest(manifest['source_hashes']),
        directional_count=sum(j['kind']=='directional' for j in raw['jammers']),
        evidence='recovered_practice_engine_local', grid_version=manifest['grid_version'])
    row.update(clearance_point=config.get('clearance_point', 'mec_center'),
        polygon_certified_count=len(clearance_events),
        near_certified_count=solver.certified-sum(bool(e.get('success')) for e in clearance_events),
        polygon_clear_travel_m=sum(e['travel_m'] for e in clearance_events),
        polygon_clear_mec_travel_m=sum(e['mec_travel_m'] for e in clearance_events),
        same_state_clear_saving_m=sum(e['same_state_saving_m'] for e in clearance_events),
        polygon_zero_move_count=sum(e['zero_move'] for e in clearance_events),
        nccp_fallback_count=sum(bool(e['selection'].get('fallback')) for e in clearance_events),
        max_clearance_vertex_distance=max((e['max_vertex_distance'] for e in clearance_events), default=0.),
        certificate_audit_violations=sum(e['max_vertex_distance'] > e['clearance_radius'] or
                                       e['travel_m'] > e['mec_travel_m'] for e in clearance_events))
    for stage, costs in api.stages.items():
        row['stage_'+stage+'_s'] = costs['total_s']
    row['stage_sum_error_s'] = abs(sum(v['total_s'] for v in api.stages.values())-api.virtual_time)
    if row['stage_sum_error_s'] > 1e-5:
        row.update(error='Stage ledger does not sum to total', run_status='EXCEPTION')
    if row['certificate_audit_violations']:
        row.update(error='Clearance certificate audit failed', run_status='EXCEPTION')
    folder = out/f'q{problem}'
    trace = folder/'traces'/f'{variant}_{seed:04d}.json.gz'
    trace.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(trace, 'wt', encoding='utf-8') as f:
        json.dump(dict(row=row, stages=api.stages, targets=traces, actions=api.log,
                       scene_file=f'scenes/q{problem}_{seed:04d}.json'), f, ensure_ascii=False, allow_nan=False)
    save(folder/'rows'/f'{variant}_{seed:04d}.json', row)
    print(json.dumps({k:row[k] for k in ('seed','problem','variant','run_status','cleared','total','mean_time_per_source','error')}), flush=True)


def launch_case(job):
    out, sim_root, seed, problem, variant, device, resume = job
    result = out/f'q{problem}'/'rows'/f'{variant}_{seed:04d}.json'
    manifest, cfg, scene = validated_inputs(out, seed, problem, variant)
    if resume and result.exists():
        row = json.loads(result.read_text(encoding='utf-8'))
        validate_row(row, manifest, cfg, scene, seed, problem, variant, device)
        return row
    command = [sys.executable, '-B', str(Path(__file__).resolve()), '--sim-root', str(sim_root),
               '--output', str(out), '--single', str(seed), '--problem', str(problem), '--variant', variant, '--device', device]
    env = dict(os.environ, OMP_NUM_THREADS='1', MKL_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1')
    try:
        run = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', timeout=1210,
                             env=env, creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        if run.returncode != 0:
            raise RuntimeError(run.stderr[-6000:] or run.stdout[-6000:])
        row = json.loads(result.read_text(encoding='utf-8'))
        validate_row(row, manifest, cfg, scene, seed, problem, variant, device)
        return row
    except Exception as exc:
        row = dict(seed=seed, problem=problem, variant=variant, total=len(scene['jammers']), cleared=0,
                   clear_rate=0., error=repr(exc), mean_time_per_source=0., distance=0., runtime=1210. if isinstance(exc,subprocess.TimeoutExpired) else 0.,
                   run_status='TIMEOUT' if isinstance(exc,subprocess.TimeoutExpired) else 'EXCEPTION',
                   config_hash=digest(cfg), scene_hash=digest(scene), source_hash=digest(manifest['source_hashes']),
                   device=device, partial_state_unknown=True)
        save(result,row)
        return row


def summarize_runs(out, indices, problems):
    from paired_q4 import summarize
    manifest = json.loads((out/'manifest.json').read_text(encoding='utf-8'))
    for problem in problems:
        variants = [c['name'] for c in manifest['configs'][str(problem)]]
        expected = [(seed,v) for seed in indices for v in variants]
        folder = out/f'q{problem}'
        rows = []
        for seed, variant in expected:
            path = folder/'rows'/f'{variant}_{seed:04d}.json'
            if path.exists():
                row = json.loads(path.read_text(encoding='utf-8'))
                checked, cfg, raw = validated_inputs(out, seed, problem, variant)
                validate_row(row, checked, cfg, raw, seed, problem, variant)
                rows.append(row)
        folder.mkdir(parents=True,exist_ok=True)
        report_folder = folder if indices == list(range(len(manifest['seeds']))) else folder/'subsets'/digest(indices)[:12]
        report_folder.mkdir(parents=True,exist_ok=True)
        summarize(rows, report_folder, expected_pairs=expected, baseline_name=variants[0],
                  write_cases=not (report_folder/'cases.csv').exists())
        profile = {}
        for variant in variants:
            group = [r for r in rows if r['variant']==variant and r.get('run_status')=='FULL_CLEAR' and not r['error']]
            if not group:
                continue
            total = np.array([r['virtual_time_s'] for r in group])
            counts = np.array([r['total'] for r in group])
            per_source = total/counts
            tail = per_source >= np.percentile(per_source,95)
            values = {}
            for stage in STAGES:
                t = np.array([r['stage_'+stage+'_s'] for r in group])
                values[stage] = dict(median_fraction=float(np.median(t/total)),
                    aggregate_fraction=float(t.sum()/total.sum()), P95_seconds=float(np.percentile(t,95)),
                    P99_seconds=float(np.percentile(t,99)),
                    P95_seconds_per_source=float(np.percentile(t/counts,95)),
                    P99_seconds_per_source=float(np.percentile(t/counts,99)),
                    correlation_with_total=float(np.corrcoef(t,total)[0,1]) if np.std(t)>1e-12 and np.std(total)>1e-12 else None,
                    correlation_with_per_source_total=float(np.corrcoef(t/counts,per_source)[0,1]) if np.std(t/counts)>1e-12 and np.std(per_source)>1e-12 else None,
                    tail_aggregate_fraction=float(t[tail].sum()/total[tail].sum()))
            profile[variant] = dict(n=len(group), tail_metric='mean_time_per_source',
                                   tail_cases=[group[i]['seed'] for i in np.flatnonzero(tail)], stages=values)
        save(report_folder/'stage_profile.json',profile)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--sim-root', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--grid-version', default='grid_v1', choices=['grid_v0','grid_v1'])
    p.add_argument('--workers',type=int,default=4)
    p.add_argument('--device',default='cpu')
    p.add_argument('--start',type=int,default=0)
    p.add_argument('--count',type=int)
    p.add_argument('--problems',type=int,nargs='+',default=[3,4],choices=[3,4])
    p.add_argument('--resume',action='store_true')
    p.add_argument('--freeze-only',action='store_true')
    p.add_argument('--summarize-only',action='store_true')
    p.add_argument('--single',type=int)
    p.add_argument('--problem',type=int,choices=[3,4])
    p.add_argument('--variant')
    args = p.parse_args()
    sim_root, out = args.sim_root.resolve(), args.output.resolve()
    sys.path.insert(0,str(sim_root))
    if args.single is not None:
        run_single(out,sim_root,args.single,args.problem,args.variant,args.device)
        return
    if not args.resume:
        freeze(out,sim_root,args.grid_version)
    manifest = json.loads((out/'manifest.json').read_text(encoding='utf-8'))
    if source_hashes(sim_root) != manifest['source_hashes']:
        raise RuntimeError('Source fingerprint changed since freeze')
    indices = list(range(args.start,min(len(manifest['seeds']),args.start+args.count if args.count is not None else len(manifest['seeds']))))
    if args.freeze_only:
        print(f'Frozen {len(manifest["seeds"])} seeds; no solver runs yet.')
        return
    if not args.summarize_only:
        jobs = [(out,sim_root,i,problem,cfg['name'],args.device,args.resume)
                for i in indices for problem in args.problems for cfg in manifest['configs'][str(problem)]]
        save(out/'run_request.json',dict(indices=indices,problems=args.problems,device=args.device,workers=args.workers,jobs=len(jobs)))
        done = 0
        errors = 0
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = [pool.submit(launch_case,j) for j in jobs]
            for future in as_completed(futures):
                row = future.result()
                done += 1
                errors += row.get('run_status')!='FULL_CLEAR' or bool(row['error'])
                if done % 10 == 0 or row.get('run_status')!='FULL_CLEAR':
                    print(f'{done}/{len(jobs)} complete; unsuccessful={errors}; last={row["seed"]} Q{row["problem"]} {row["variant"]} {row.get("run_status")}',flush=True)
        save(out/'completion.json',dict(completed_jobs=done,unsuccessful=errors))
    summarize_runs(out,indices,args.problems)


if __name__ == '__main__':
    main()
