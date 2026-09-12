"""Frozen revised Q4 replay, all 1000 historical scenes; local engine only."""
import os
os.environ.update(OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1')
import argparse, csv, hashlib, io, json, platform, sys, time, zipfile
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed
import numpy as np

HERE=Path(__file__).resolve().parent
CODE=HERE/'frozen/code'; ENGINE=HERE/'frozen/runtime'; OUT=HERE/'results'
sys.path[:0]=[str(CODE/'source'),str(ENGINE)]
import geometry, solver, phase_audit
import recovered_benchmark as rb
import public_max37_benchmark as base
from ctspn import CTSolver
ORIGINAL_COVERAGE=geometry.coverage

def hashes(_=None):
    paths=list((CODE/'source').rglob('*.py'))+list(ENGINE.glob('*.py'))
    paths += [CODE/'config_21r12ctf.json', CODE/'points21.json', Path(__file__).resolve()]
    return {p.relative_to(HERE).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(paths)}

def prepare():
    if OUT.exists(): raise FileExistsError('Frozen results already exist')
    archive=HERE.parent/'support/evidence/q4_local.zip'
    with zipfile.ZipFile(archive) as z:
        old=list(csv.DictReader(io.StringIO(z.read('cases.csv').decode('utf-8-sig'))))
        records=[]
        for i in range(1000):
            raw=json.loads(z.read(f'scenes/{i:04d}.json'))
            filename=f'scenes/{i:04d}.json'; rb.save(OUT/filename,raw)
            records.append(dict(id=i,total=len(raw['jammers']),file=filename,scene_hash=rb.digest(raw),
                cohort='historical_scene_replay',family='mixed' if any(j['kind']!='directional' for j in raw['jammers']) else 'all_directional'))
    rb.save(OUT/'historical_cases.json',old)
    cfg=json.loads((CODE/'config_21r12ctf.json').read_bytes())
    rb.save(OUT/'manifest.json',dict(records=records,configs=[cfg],source_hashes=hashes(),
        historical_archive_sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),
        python=platform.python_version(),numpy=np.__version__,execution_backend='LOCAL_DEV',
        production_eligible=False,scope='Revised 21+R12+F+CT replay on all 1000 historical scenes; not original missing trajectories and not independent test scenes',
        plan=dict(runs=1000,workers=6,selection='Every indexed historical scene, no outcome filtering',
                  statistics='all-clear, audit, failed clears, per-scene T/N mean and linear P95/P99, paired historical B differences',
                  retain='Every action trace, CT events, row, scene and frozen source; retain failures without rerunning')))

def run(i):
    points=np.asarray(json.loads((CODE/'points21.json').read_bytes())['points'])
    def coverage(mixed=False,ring=1130.,*,version='legacy45'):
        return points.copy() if mixed and version=='certified25' else ORIGINAL_COVERAGE(mixed,ring,version=version)
    class Captured(CTSolver):
        def run(self):
            try: return super().run()
            finally: rb.save(OUT/'events'/f'B_{i:04d}.json',dict(events=self.ct_events,pending_bridge=self.api.pending is not None))
    geometry.coverage=solver.coverage=coverage; phase_audit.TaggedSolver=Captured; base.fingerprints=hashes
    return base.run_case((OUT,ENGINE,i,'B',None))

def summarize():
    rows=[json.loads(p.read_bytes()) for p in sorted((OUT/'core/rows').glob('*.json'))]
    old={int(r['id']):r for r in json.loads((OUT/'historical_cases.json').read_bytes()) if r['variant']=='B'}
    pairs=[]
    for r in rows:
        h=old[r['id']]; assert r['scene_hash']==h['scene_hash']
        pairs.append(dict(id=r['id'],scene_hash=r['scene_hash'],total=r['total'],directional_count=r['directional_count'],
            historical_B=float(h['mean_time_per_source']),revised_B=r['mean_time_per_source'],
            delta=r['mean_time_per_source']-float(h['mean_time_per_source']),
            historical_failed=int(h['failed_clears']),revised_failed=r['failed_clears'],
            full=r['run_status']=='FULL_CLEAR',audit=r['audit_passed']))
    def stats(group):
        vals=[r['mean_time_per_source'] for r in group]
        return dict(runs=len(group),full=sum(r['run_status']=='FULL_CLEAR' for r in group),audited=sum(r['audit_passed'] for r in group),
                    mean=float(np.mean(vals)),P95=float(np.quantile(vals,.95)),P99=float(np.quantile(vals,.99)),maximum=max(vals),
                    failed_clears=sum(r['failed_clears'] for r in group),failed_games=sum(r['failed_clears']>0 for r in group),
                    fallback_count=sum(r['fallback_count'] for r in group),runtime_sum_s=sum(r['runtime_s'] for r in group))
    result=dict(complete=len(rows)==1000,all=stats(rows),mixed=stats([r for r in rows if r['directional_count']<r['total']]),
        all_directional=stats([r for r in rows if r['directional_count']==r['total']]),
        comparison=dict(mean_delta=float(np.mean([p['delta'] for p in pairs])),wins=sum(p['delta']< -1e-9 for p in pairs),
                        losses=sum(p['delta']>1e-9 for p in pairs),ties=sum(abs(p['delta'])<=1e-9 for p in pairs)))
    rb.save(OUT/'summary.json',result)
    for name,data in [('cases.csv',rows),('pairs.csv',pairs)]:
        with (OUT/name).open('w',newline='',encoding='utf-8-sig') as f:
            w=csv.DictWriter(f,fieldnames=sorted(set().union(*(r.keys() for r in data))));w.writeheader();w.writerows(data)
    print(json.dumps(result),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--prepare',action='store_true');p.add_argument('--summarize',action='store_true');p.add_argument('--workers',type=int,default=6)
    a=p.parse_args()
    if a.prepare: prepare()
    elif a.summarize: summarize()
    else:
        assert hashes()==json.loads((OUT/'manifest.json').read_bytes())['source_hashes']
        ids=[i for i in range(1000) if not (OUT/'core/rows'/f'B_{i:04d}.json').exists()]
        start=time.perf_counter()
        with ProcessPoolExecutor(max_workers=a.workers) as pool:
            futures={pool.submit(run,i):i for i in ids}
            for n,f in enumerate(as_completed(futures),1):
                try:
                    r=f.result();print(f'{n}/{len(ids)} id={r["id"]} {r["run_status"]} audit={r["audit_passed"]} failures={r["failed_clears"]} wall={r["runtime_s"]:.1f}',flush=True)
                except Exception as e:
                    rb.save(OUT/'worker_errors'/f'{futures[f]:04d}.json',dict(id=futures[f],error=str(e),type=type(e).__name__))
                    print(f'WORKER_ERROR id={futures[f]} {type(e).__name__}: {e}',flush=True)
        rb.save(OUT/'execution.json',dict(workers=a.workers,wall_clock_s=time.perf_counter()-start,scheduled=len(ids)))
        summarize()

