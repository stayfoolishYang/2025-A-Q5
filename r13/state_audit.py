"""Strict archived-response replay; no Engine or network calls."""
import os
os.environ.update(OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='1')
from pathlib import Path
import sys,json,gzip,time,hashlib,csv
from concurrent.futures import ProcessPoolExecutor,as_completed
import numpy as np
ROOT=Path(__file__).resolve().parent
SRC=ROOT/'baseline/q4better'
sys.path.insert(0,str(SRC))
from phase_audit import Replay,TaggedSolver
import discovery
from geometry import mec
from route_reference import distances,strong,exact,length,verify
ARCHIVE=Path('J:/2026B_runs/q4_latest_7228633/cpu519_repeat_20260912')
OUT=ROOT/'results/state_audit'
CFG=json.loads((SRC/'configs/q4_known16_tri25_R12.yaml').read_bytes())

def digest(x):return hashlib.sha256(json.dumps(x,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def scan_cost(current,cleared,n):
    seconds=0
    for _ in range(n):
        order=[current]+[c for c in range(1,21) if c!=current]
        for c in order:
            if c not in cleared:seconds+=5+int(c!=current);current=c
    return seconds

def worker(seed):
    with gzip.open(ARCHIVE/'core/traces'/f'R12_{seed:04d}.json.gz','rt',encoding='utf-8') as f:raw=json.load(f)
    records=raw['actions'];events=[];known=[];states=[]
    class StrictReplay(Replay):
        def action(self,path,position=None,channel=None):
            record=self.records[self.index]
            if position is not None:assert np.array_equal(np.asarray(position),record['position']),('position changed',seed,self.index)
            if 'rng_before' in record:
                import recovered_benchmark as rb
                assert rb.digest({str(c):t['hyp'].rng.bit_generator.state for c,t in solver.tracks.items() if t.get('hyp') is not None})==record['rng_before'],('RNG changed',seed,self.index)
            return super().action(path,position,channel)
    api=StrictReplay(records);solver=TaggedSolver(api,True,'P4','cpu',diagnostic=CFG)
    original=discovery.refresh_remaining_route;release=solver.release_discovery
    def capture(nodes,current):
        before=np.asarray(nodes).copy();then=time.perf_counter();result=original(nodes,current);wall=time.perf_counter()-then
        event=dict(seed=seed,index=len(events),position=np.asarray(current).tolist(),remaining_before=before.tolist(),r12_route=np.asarray(result).tolist(),current_channel=int(api.channel),confirmed=len(solver.confirmed),cleared=sorted(solver.cleared),time_s=api.virtual_time,route_wall_s=wall)
        events.append(event);return result
    def release_capture(nodes):
        if solver.known16_trigger is not None and len(nodes):
            supports=np.asarray(nodes).tolist();targets=[]
            for c,t in solver.tracks.items():
                center,radius=mec(t['poly']);hyp=t.get('hyp');particles=hyp.p if hyp is not None else np.empty((0,5))
                targets.append(dict(channel=int(c),polygon=t['poly'].tolist(),center=center.tolist(),radius=radius,n=t['n'],negatives=t['negatives'],particles=particles[np.linspace(0,len(particles)-1,min(1024,len(particles))).astype(int)].tolist() if len(particles) else [],history=[np.asarray(x[0]).tolist() for x in solver.history[c]]))
            known.append(dict(seed=seed,position=api.position.tolist(),current_channel=int(api.channel),time_s=api.virtual_time,nodes=supports,cleared=sorted(solver.cleared),targets=targets))
        # Capture outer scheduling inputs, without asking a hypothesis to generate an action.
        if len(nodes):
            certified=[]
            for c,t in solver.tracks.items():
                center,radius=mec(t['poly'])
                if radius<=19.999:
                    credit=scan_cost(api.channel,solver.cleared,len(nodes))-scan_cost(api.channel,solver.cleared|{c},len(nodes))
                    certified.append(dict(channel=int(c),center=center.tolist(),radius=radius,scan_credit_s=credit))
            if certified:states.append(dict(seed=seed,time_s=api.virtual_time,position=api.position.tolist(),nodes=np.asarray(nodes).tolist(),current_channel=int(api.channel),cleared=sorted(solver.cleared),certified=certified))
        return release(nodes)
    discovery.refresh_remaining_route=capture;solver.release_discovery=release_capture
    try:solver.run()
    finally:discovery.refresh_remaining_route=original
    assert api.index==len(records) and api.virtual_time==raw['row']['virtual_time_s']
    rows=[]
    for e in events:
        p=e['r12_route'];d=distances(e['position'],p);n=len(p);base=length(np.arange(1,n+1),d)
        begin=time.perf_counter()
        if n<=16:reference=exact(d);kind='exact_dp_fp64'
        else:_,reference=strong(d);kind='multistart_2opt_relocate'
        elapsed=time.perf_counter()-begin
        assert reference<=base+1e-6
        rows.append(dict(seed=seed,index=e['index'],remaining=n,r12_m=base,reference_m=reference,gap=(base-reference)/reference if reference else 0.,saving_s=(base-reference)/5,reference_kind=kind,reference_wall_s=elapsed,r12_wall_s=e['route_wall_s']))
    payload=dict(seed=seed,strict_replay=True,total=raw['row']['total'],final_time_s=api.virtual_time,events=events,known16_release=known,certified_states=states,gaps=rows,official_calls=0)
    with gzip.open(OUT/f'{seed:04d}.json.gz','wt',encoding='utf-8') as f:json.dump(payload,f,ensure_ascii=False)
    return dict(seed=seed,snapshots=len(events),known16=len(known),certified=len(states),gaps=rows)

def main():
    OUT.mkdir(parents=True,exist_ok=False);verify()
    rows=[];cases=[]
    with ProcessPoolExecutor(max_workers=8) as pool:
        futures=[pool.submit(worker,i) for i in range(519)]
        for n,f in enumerate(as_completed(futures),1):
            r=f.result();rows.extend(r.pop('gaps'));cases.append(r)
            if n%25==0:print(n,'/519 strict replay',flush=True)
    rows.sort(key=lambda r:(r['seed'],r['index']))
    with (OUT/'route_gaps.csv').open('w',newline='',encoding='utf-8-sig') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    gaps=np.array([r['gap'] for r in rows]);report=dict(cases=519,snapshots=len(rows),strict_replay=True,exact_threshold=16,gap_mean=float(gaps.mean()),gap_p50=float(np.quantile(gaps,.5)),gap_p95=float(np.quantile(gaps,.95)),gap_p99=float(np.quantile(gaps,.99)),gap_max=float(gaps.max()),known16_release_states=sum(r['known16'] for r in cases),certified_states=sum(r['certified'] for r in cases),official_calls=0,cases_detail=cases)
    (OUT/'SUMMARY.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps({k:v for k,v in report.items() if k!='cases_detail'}),flush=True)

if __name__=='__main__':main()
