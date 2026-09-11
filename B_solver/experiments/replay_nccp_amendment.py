"""Check a safety-only amendment against every frozen NCCP action, offline."""
import argparse
from concurrent.futures import ProcessPoolExecutor
import gzip
import hashlib
import json
from pathlib import Path
import subprocess

from clearance_shadow import replay_trace


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run_one(job):
    trace_path = Path(job['trace'])
    result = {k: job[k] for k in ('cohort', 'problem', 'seed', 'variant', 'trace')}
    result['trace_sha256'] = sha(trace_path)
    try:
        with gzip.open(trace_path, 'rt', encoding='utf-8') as f:
            trace = json.load(f)
        replay = replay_trace(trace, job['config'], shadow=False, max_states=0)
        assert replay['virtual_time'] == trace['row']['virtual_time_s']
        result.update(passed=True, action_count=len(replay['actions']),
                      actions_fingerprint=replay['actions_fingerprint'],
                      virtual_time_s=replay['virtual_time'])
    except Exception as exc:
        result.update(passed=False, error=f'{type(exc).__name__}: {exc}')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--workers', type=int, default=2)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    base = Path(__file__).resolve().parents[1]
    sources = {str(p.relative_to(base)): sha(p) for p in
               [*base.glob('*.py'), *base.glob('directional/*.py'),
                Path(__file__), Path(__file__).with_name('clearance_shadow.py')]}
    jobs = []
    for cohort in ('development100', 'holdout256'):
        directory = args.root / cohort
        audit = json.loads((directory / 'NCCP_AUDIT.json').read_text(encoding='utf-8'))
        assert audit['performance_conclusion_allowed'] is True
        manifest = json.loads((directory / 'manifest.json').read_text(encoding='utf-8'))
        for problem in (3, 4):
            for seed in manifest['seeds']:
                for config in manifest['configs'][str(problem)]:
                    trace = directory / f'q{problem}' / 'traces' / f"{config['name']}_{seed['seed']:04d}.json.gz"
                    jobs.append(dict(cohort=cohort, problem=problem, seed=seed['seed'],
                                     variant=config['name'], trace=str(trace), config=config))
    plan = dict(schema='nccp-safety-amendment-replay-v1', jobs=jobs, source_hashes=sources,
                git_commit=subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
                purpose='Exact saved-action replay; no regenerated seeds, simulator, or performance retest',
                formal_runs=0)
    (args.output / 'PLAN.json').write_text(json.dumps(plan, indent=2), encoding='utf-8')
    rows = []
    with (args.output / 'cases.jsonl').open('x', encoding='utf-8') as f:
        with ProcessPoolExecutor(max_workers=args.workers) as pool:
            for result in pool.map(run_one, jobs):
                rows.append(result)
                f.write(json.dumps(result, allow_nan=False) + '\n')
                f.flush()
                if len(rows) % 50 == 0 or not result['passed'] or len(rows) == len(jobs):
                    print(f"{len(rows)}/{len(jobs)} exact replays; failures={sum(not r['passed'] for r in rows)}", flush=True)
    unchanged = all(sha(base / p) == value for p, value in sources.items())
    summary = dict(expected=len(jobs), completed=len(rows), failures=[r for r in rows if not r['passed']],
                   source_unchanged=unchanged, passed=unchanged and all(r['passed'] for r in rows),
                   action_count=sum(r.get('action_count', 0) for r in rows), formal_runs=0,
                   plan_sha256=sha(args.output / 'PLAN.json'),
                   cases_sha256=sha(args.output / 'cases.jsonl'))
    (args.output / 'AUDIT.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    if not summary['passed']:
        raise SystemExit(2)


if __name__ == '__main__':
    main()
