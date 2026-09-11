"""Fresh local CPU reruns, matched to the official sample's source counts."""
import os
os.environ.update(OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1')
import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
import hashlib
import json
from pathlib import Path
import shutil
import sys

BASE = Path('J:/2026B_runs')
OUT = BASE/'practice_comparison_20260911'
SNAP = BASE/'official_latest/resident/snapshot_q3_30_20260911_195454'
ROOTS = {3: BASE/'q3_latest_79766ec', 4: BASE/'q4_latest_7228633'}

def save(p, value):
    p.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')

def worker(job):
    q, seed = job
    if q == 3:
        import run_latest_q3_519 as runner
        runner.OUT = OUT/'local_q3'
        return runner.worker((seed, 'D'))
    import run_latest_q4_519 as runner
    runner.OUT = OUT/'local_q4'
    return runner.worker((seed, 'R12'))

def main():
    p = argparse.ArgumentParser()
    p.add_argument('--problem', type=int, choices=[3, 4], required=True)
    a = p.parse_args(); q = a.problem
    dest = OUT/f'local_q{q}'; dest.mkdir(parents=True, exist_ok=False)
    (dest/'scenes').mkdir()
    old = ROOTS[q]/'cpu519'
    hashes = json.loads((old/('PLAN.json' if q == 3 else 'HASHES.json')).read_bytes())
    if q == 3: hashes = hashes['hashes']
    frozen = {k:v for k,v in hashes.items() if '/source/' in k.replace('\\','/') or k.replace('\\','/').startswith('G:/QQ/jammers_linux/')}
    assert frozen
    for path, h in frozen.items():
        assert hashlib.sha256(Path(path).read_bytes()).hexdigest() == h, path
    official = [r for r in json.loads((SNAP/'sessions.json').read_bytes()) if r['problem'] == q]
    counts = Counter(r['total'] for r in official)
    candidates = []
    for seed in range(519):
        scene = old/'scenes'/f'q{q}_{seed:04d}.json'
        raw = scene.read_bytes()
        candidates.append((hashlib.sha256(b'practice-match-20260911-v1:'+raw).hexdigest(), seed, len(json.loads(raw)['jammers'])))
    selected = []
    for n, count in sorted(counts.items()):
        pool = sorted(x for x in candidates if x[2] == n)
        assert len(pool) >= count
        selected.extend(s for _,s,_ in pool[:count])
    selected.sort()
    if q == 3:
        (dest/'runs').mkdir()
    else:
        (dest/'core/rows').mkdir(parents=True)
        manifest = json.loads((old/'manifest.json').read_bytes())
        # Preserve original record indices because the existing runner indexes this list.
        save(dest/'manifest.json', manifest)
    for seed in selected:
        name = f'q{q}_{seed:04d}.json'
        shutil.copy2(old/'scenes'/name, dest/'scenes'/name)
    save(dest/'PLAN.json', dict(problem=q, selected=selected, source_count_histogram=dict(counts),
         selection='Within each N, smallest SHA256(practice-match-20260911-v1: + raw scene bytes); no score used',
         reuse='Existing regression scenes, freshly executed; not a new independent holdout',
         workers=4, official_calls=0, hashes=frozen, official_snapshot=str(SNAP)))
    results=[]
    with ProcessPoolExecutor(max_workers=4) as pool:
        fs=[pool.submit(worker,(q,s)) for s in selected]
        for f in as_completed(fs):
            r=f.result(); results.append(r)
            print(q, len(results), '/', len(selected), r.get('status',r.get('run_status')), flush=True)
    mismatches=[]
    for seed in selected:
        rel=Path('runs')/f'q3_{seed:04d}_D.json' if q==3 else Path('core/rows')/f'R12_{seed:04d}.json'
        before=json.loads((old/rel).read_bytes()); after=json.loads((dest/rel).read_bytes())
        if abs(before['virtual_time_s']-after['virtual_time_s'])>1e-6:mismatches.append(seed)
    for path,h in frozen.items():
        assert hashlib.sha256(Path(path).read_bytes()).hexdigest()==h, path
    save(dest/'COMPLETION.json',dict(planned=len(selected),completed=len(results),
        full_clear=sum(r.get('status',r.get('run_status'))=='FULL_CLEAR' for r in results),
        audited=sum(bool(r.get('audit',r.get('audit_passed'))) for r in results),
        previous_virtual_time_mismatches=mismatches,source_hashes_unchanged=True,official_calls=0))

if __name__=='__main__':main()
