"""Build auditable paired tail comparisons and worst-target explanations."""
import argparse
import csv
import gzip
import json
from pathlib import Path
import numpy as np


def main():
    p=argparse.ArgumentParser();p.add_argument('directory');a=p.parse_args();out=Path(a.directory)
    with (out/'cases.csv').open(encoding='utf-8-sig') as f:rows=list(csv.DictReader(f))
    baseline={int(r['seed']):r for r in rows if r['variant']=='P4_current'}
    comparisons={}
    for name in sorted({r['variant'] for r in rows}-{'P4_current'}):
        group=sorted([r for r in rows if r['variant']==name],key=lambda r:int(r['seed']))
        b=np.array([float(baseline[int(r['seed'])]['mean_time_per_source']) for r in group])
        v=np.array([float(r['mean_time_per_source']) for r in group])
        rng=np.random.default_rng(2026)
        draws=rng.integers(0,len(b),(2000,len(b)))
        diffs=np.percentile(v[draws],95,axis=1)-np.percentile(b[draws],95,axis=1)
        hold=np.array([int(r['seed'])>=20 for r in group])
        comparisons[name]=dict(paired_P95_difference=float(np.percentile(v,95)-np.percentile(b,95)),
            paired_bootstrap_P95_difference_95_interval=np.percentile(diffs,[2.5,97.5]).tolist(),
            heldout_20plus=dict(n=int(hold.sum()),baseline_P95=float(np.percentile(b[hold],95)),
                variant_P95=float(np.percentile(v[hold],95)),baseline_P99=float(np.percentile(b[hold],99)),
                variant_P99=float(np.percentile(v[hold],99)),mean_delta=float((v[hold]-b[hold]).mean())) if hold.any() else None)
    worst=sorted(baseline.values(),key=lambda r:float(r['mean_time_per_source']),reverse=True)[:10]
    detail=[]
    for original in worst:
        seed=int(original['seed']);entry=dict(seed=seed,stress=original['stress'],variants=[])
        for r in sorted([r for r in rows if int(r['seed'])==seed],key=lambda r:r['variant']):
            trace=out/'traces'/f"{r['variant']}_{seed:05d}.json"
            payload=json.loads(trace.read_text(encoding='utf-8'))
            targets=sorted(payload['targets'],key=lambda t:t['movement_distance'],reverse=True)[:3]
            entry['variants'].append(dict(metrics=r,largest_travel_targets=[{k:t[k] for k in
                ('channel','movement_distance','num_direction_obs','num_no_signal_obs','fallback_trigger_reason',
                 'diagnostic_count','optical_grid_points','optical_clear_attempts','success')} for t in targets]))
            dest=out/'worst10_traces'/trace.name.replace('.json','.json.gz');dest.parent.mkdir(exist_ok=True)
            with gzip.open(dest,'wb') as f:f.write(trace.read_bytes())
        detail.append(entry)
    (out/'tail_analysis.json').write_text(json.dumps(dict(comparisons=comparisons,worst10=detail),indent=2),encoding='utf-8')
    print(json.dumps(comparisons,indent=2))


if __name__=='__main__':main()
