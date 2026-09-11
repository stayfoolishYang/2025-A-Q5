"""Offline response replay: assert every action matches archived trajectories exactly."""
import argparse
import csv
import json
from itertools import groupby
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
import numpy as np
from solver import Solver
import directional.diagnostic_recovery as recovery

BASE=Path(__file__).resolve().parent
original_recover=recovery.recover


def tagged_recover(solver, channel, config):
    # Importing the audit module must not break ordinary, untagged clients.
    if not hasattr(solver.api, 'stage'):
        return original_recover(solver, channel, config)
    previous=solver.api.stage
    solver.api.stage='diagnostic'
    try:return original_recover(solver,channel,config)
    finally:solver.api.stage=previous


recovery.recover=tagged_recover


def optical_runs(actions):
    result=[]
    for (stage,channel),group in groupby(actions,key=lambda r:(r['stage'],r['channel'])):
        if stage != 'optical_fallback':continue
        run=list(group)
        result.append(dict(channel=channel,attempts=len(run),distance_m=sum(x['travel_m'] for x in run),
            time_s=sum(x['total_s'] for x in run),unique_positions=len({(x['x'],x['y']) for x in run}),
            longest_hop_m=max(x['travel_m'] for x in run)))
    return result


class Replay:
    def __init__(self, records):
        self.records=records;self.index=0;self.position=np.zeros(2);self.channel=1
        self.virtual_time=0.;self.stage='discovery';self.actions=[]

    def action(self,path,position=None,channel=None):
        record=self.records[self.index];self.index+=1
        assert record['path']==path, (self.index,path,record['path'])
        response=record['response']
        if path in ('/enter','/exit'):
            self.virtual_time=response['virtual_time_s'];return response
        assert channel==record['channel'],(self.index,channel,record['channel'])
        point=np.asarray(record['position'])
        assert np.linalg.norm(point-position)<1e-6,(self.index,point,position)
        distance=float(np.linalg.norm(point-self.position))
        switch=int(path=='/measure' and channel!=self.channel)
        measure=5 if path=='/measure' else 0
        clear=(5 if response['clear_result']=='success' else 3) if path=='/clear' else 0
        elapsed=distance/5+switch+measure+clear
        assert abs(self.virtual_time+elapsed-response['virtual_time_s'])<1e-3
        self.actions.append(dict(index=self.index,stage=self.stage,path=path,channel=channel,
            x=float(point[0]),y=float(point[1]),travel_m=distance,travel_s=distance/5,
            switch_s=switch,measure_s=measure,clear_s=clear,total_s=elapsed,
            result=response.get('measure_result',response.get('clear_result'))))
        self.position=point.copy();self.virtual_time=response['virtual_time_s']
        if path=='/measure':self.channel=channel
        return response


class TaggedSolver(Solver):
    def localize(self,c,one_step=False):
        previous=self.api.stage;self.api.stage='active_localization'
        try:return super().localize(c,one_step)
        finally:self.api.stage=previous

    def clear(self,c,p,certified=False):
        previous=self.api.stage;self.api.stage='certified_clear' if certified else 'optical_fallback'
        try:return super().clear(c,p,certified)
        finally:self.api.stage=previous


def run_replay(job):
    filename, config, device, case_id, outdir, official = job
    if official:
        raw=[json.loads(line) for line in Path(filename).read_text().splitlines()]
        records=[];seen=set()
        for r in raw:
            req=r['request']
            if not r['response'].get('accepted') or req['request_id'] in seen:continue
            seen.add(req['request_id']);p=req.get('position')
            records.append(dict(path=r['path'],position=[p['x'],p['y']] if p else None,
                                channel=req.get('channel'),response=r['response']))
        total=10
    else:
        payload=json.loads(Path(filename).read_text(encoding='utf-8'))
        records=[dict(path='/enter',response=dict(virtual_time_s=0))]+payload['actions']
        total=payload['row']['total']
    api=Replay(records);solver=TaggedSolver(api,True,'P4',device,diagnostic=config)
    solver.run()
    assert api.index==len(records)
    stages=defaultdict(lambda:dict(travel_m=0.,travel_s=0.,switch_s=0.,measure_s=0.,clear_s=0.,total_s=0.,actions=0))
    bytarget=defaultdict(lambda:defaultdict(float))
    for row in api.actions:
        for k in ('travel_m','travel_s','switch_s','measure_s','clear_s','total_s'):
            stages[row['stage']][k]+=row[k]
        stages[row['stage']]['actions']+=1
        bytarget[row['channel']][row['stage']]+=row['total_s']
    keys=[(r['path'],r['channel'],round(r['x'],6),round(r['y'],6)) for r in api.actions]
    counts=Counter(keys)
    clear_runs=optical_runs(api.actions)
    summary=dict(case=case_id,variant=config['name'],total_sources=total,exact_replay=True,
        virtual_time_s=api.virtual_time,mean_time_per_source=api.virtual_time/total,stages=dict(stages),
        by_target=dict(bytarget),optical_runs=clear_runs,
        repeated_action_signatures=sum(v-1 for v in counts.values() if v>1),
        max_signature_repeats=max(counts.values()),
        repeated_clear_signatures=sum(v-1 for k,v in counts.items() if k[0]=='/clear' and v>1),
        fallback_reasons={str(c):t['fallback_trigger_reason'] for c,t in solver.trace.items() if t['fallback_trigger_reason']})
    out=Path(outdir);out.mkdir(parents=True,exist_ok=True)
    (out/f'{case_id}_{config["name"]}.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    with (out/f'{case_id}_{config["name"]}_actions.csv').open('w',newline='',encoding='utf-8-sig') as f:
        w=csv.DictWriter(f,fieldnames=list(api.actions[0]));w.writeheader();w.writerows(api.actions)
    return summary


def main():
    p=argparse.ArgumentParser();p.add_argument('--workers',type=int,default=4)
    p.add_argument('--output',default=str(BASE/'results/diagnostic/phase_audit'));a=p.parse_args()
    root=BASE/'results/diagnostic/paired100'
    audit=json.loads((root/'tail_analysis.json').read_text())
    # Include baseline worst ten, candidate worst ten, and largest known regression.
    with (root/'cases.csv').open(encoding='utf-8-sig') as f:rows=list(csv.DictReader(f))
    seeds={x['seed'] for x in audit['worst10']}|{3}
    seeds.update(int(r['seed']) for r in sorted([r for r in rows if r['variant']=='P4_diagnostic_v1'],
                                               key=lambda r:float(r['mean_time_per_source']),reverse=True)[:10])
    jobs=[]
    for variant in ('baseline','diag_v1','diag_v2'):
        config=json.loads((BASE/'configs'/f'q4_p4_{variant}.yaml').read_text())
        for seed in sorted(seeds):
            jobs.append((str(root/'traces'/f'{config["name"]}_{seed:05d}.json'),config,'cpu',str(seed),a.output,False))
    with ProcessPoolExecutor(max_workers=a.workers) as pool:results=list(pool.map(run_replay,jobs))
    config=json.loads((BASE/'configs/q4_p4_baseline.yaml').read_text())
    results.append(run_replay((str(BASE/'results/official_practice/q4_NVR3-565D-QRRT-M7E9.jsonl'),
                   config,'cuda','official_NVR3',a.output,True)))
    (Path(a.output)/'summary.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
    print(f'Exact offline replay passed for {len(results)} saved trajectories; no network client used.')


if __name__=='__main__':main()
