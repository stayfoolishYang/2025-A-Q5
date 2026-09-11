"""Phase A evaluation; truth used only AFTER predictions, never in belief."""
import os
os.environ.update(OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='1',NUMEXPR_NUM_THREADS='1')
import sys,json,gzip,math,argparse
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor,as_completed
import numpy as np
from belief_v2 import DiscoveryBelief
ROOT=Path(__file__).resolve().parent;OUT=ROOT/'results/prediction'
sys.path.insert(0,str(ROOT.parent/'r13/local_engine'))
from scenario_io import load_scenario
from engine import Engine

def oracle(scene, snap):
    labels=[]
    for point in snap['nodes']:
        engine=Engine(scene);engine.apply('/enter',{})
        count=0
        for c in range(1,21):
            if c in snap['confirmed']:continue
            r=engine.apply('/measure',dict(position=dict(x=point[0],y=point[1]),channel=c))
            assert r['accepted'];count+=r['measure_result']!='no_signal'
        labels.append(count)
    return np.array(labels)

def rank_metrics(order, y):
    ranked=y[order]>0;where=np.flatnonzero(ranked)
    return dict(top1=float(ranked[0]),top3=float(ranked[:3].any()),
                mrr=1/(int(where[0])+1) if len(where) else 0.)

def worker(index):
    m=json.loads((OUT/'manifest.json').read_bytes());rec=m['records'][index]
    with gzip.open(OUT/'snapshots'/f'{index:04d}.json.gz','rt',encoding='utf-8') as f:snaps=json.load(f)
    scene=load_scenario(json.loads((OUT/rec['file']).read_bytes()))
    belief=DiscoveryBelief();counts={str(c):0 for c in range(1,21)};rows=[];bins=[]
    for step,s in enumerate(snaps):
        for c,h in s['history'].items():
            for p,r,a in h[counts[c]:]:belief.observe(int(c),p,r)
            counts[c]=len(h)
        assert belief.seen==set(s['confirmed'])
        nodes=np.array(s['nodes']);dist=np.linalg.norm(nodes-np.array(s['position']),axis=1)
        predictions={name:belief.predict(nodes,conditioned=conditioned)
                     for name,conditioned in [('geometry',False),('belief',True)]}
        # Evaluation-only oracle; no result is supplied to belief.
        y=oracle(scene,s);binary=y>0;n=len(y);hits=int(binary.sum())
        for name,p in predictions.items():
            fallback=not p['available']
            if fallback:p=predictions['geometry']
            order=np.argsort(-p['expected_new'],kind='stable') if not fallback else np.arange(n)
            q=p['probability_any']
            rows.append(dict(id=index,cohort=rec['cohort'],step=step,method=name,nodes=n,
                has_hit=bool(hits),fallback=fallback,brier=float(np.mean((q-binary)**2)),
                **rank_metrics(order,y)))
            for lo in range(10):
                mask=(np.minimum((q*10).astype(int),9)==lo)
                if mask.any():bins.append(dict(id=index,method=name,bin=lo,count=int(mask.sum()),
                    predicted_sum=float(q[mask].sum()),observed_sum=int(binary[mask].sum())))
        for name,order in [('R12',np.arange(n)),('distance',np.argsort(dist,kind='stable'))]:
            rows.append(dict(id=index,cohort=rec['cohort'],step=step,method=name,nodes=n,has_hit=bool(hits),fallback=False,
                             **rank_metrics(order,y)))
        # Uniform random ranking, integrated exactly rather than arbitrary tie order.
        mrr=0.;surv=1.
        for k in range(1,n+1):
            hazard=hits/(n-k+1)
            if hazard>1:break
            mrr+=surv*hazard/k;surv*=1-hazard
        top3=1-math.comb(n-hits,min(3,n))/math.comb(n,min(3,n)) if n-hits>=min(3,n) else 1.
        q=float(predictions['geometry']['probability_any'].mean())
        rows.append(dict(id=index,cohort=rec['cohort'],step=step,method='uniform',nodes=n,has_hit=bool(hits),fallback=False,
            top1=hits/n,top3=top3,mrr=mrr,brier=float(np.mean((q-binary)**2))))
    path=OUT/'evaluation'/f'{index:04d}.json';path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(dict(rows=rows,bins=bins)),encoding='utf-8')
    return index,len(snaps)

def summarize():
    import pandas as pd
    paths=sorted((OUT/'evaluation').glob('*.json'));data=[json.loads(p.read_bytes()) for p in paths]
    df=pd.DataFrame([r for d in data for r in d['rows']]);out=ROOT/'analysis';out.mkdir(exist_ok=True)
    df.to_csv(out/'prediction_states.csv',index=False)
    means=df.groupby(['cohort','id','method'])[['top1','top3','mrr','brier','fallback']].mean().reset_index()
    means.to_csv(out/'prediction_scene_means.csv',index=False)
    summary=means.groupby(['cohort','method'])[['top1','top3','mrr','brier','fallback']].mean()
    summary.to_csv(out/'prediction_summary.csv')
    bins=pd.DataFrame([r for d in data for r in d['bins']]);bins.groupby(['method','bin'])[['count','predicted_sum','observed_sum']].sum().to_csv(out/'reliability.csv')
    rng=np.random.default_rng(14002);gates={}
    for cohort,g in means.groupby('cohort'):
        table=g.pivot(index='id',columns='method',values='mrr');delta=(table.belief-table.distance).to_numpy()
        ci=np.quantile(delta[rng.integers(len(delta),size=(10000,len(delta)))].mean(axis=1),[.025,.975])
        top=g.groupby('method').top1.mean();lift=float(top.belief/top.R12-1)
        gates[cohort]=dict(scenes=len(table),relative_top1_lift=lift,mrr_difference=float(delta.mean()),
            mrr_difference_ci95=ci.tolist(),passes=bool(lift>=.15 or ci[0]>0))
    complete=len(paths)==384
    result=dict(complete=complete,cohorts=gates,phase_A_pass=bool(complete and all(g['passes'] for g in gates.values())),
        aggregation='equal scene weight; state averages within scene; paired bootstrap by scene',
        ranking='descending expected_new; stable R12-order ties; fallback R12 order with geometry probability',
        uniform='analytical random ranking; spatial constant probability equals geometry node average',official_calls=0)
    (out/'PREDICTION_GATE.json').write_text(json.dumps(result,indent=2),encoding='utf-8');print(json.dumps(result),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['run','summarize']);p.add_argument('--workers',type=int,default=4);a=p.parse_args()
    if a.action=='summarize':summarize()
    else:
        jobs=[int(p.name.split('.')[0]) for p in (OUT/'snapshots').glob('*.json.gz') if not(OUT/'evaluation'/f'{int(p.name.split(".")[0]):04d}.json').exists()]
        with ProcessPoolExecutor(max_workers=a.workers) as pool:
            for i,f in enumerate(as_completed([pool.submit(worker,j) for j in sorted(jobs)]),1):
                r=f.result()
                if i%8==0:print('EVALUATED',i,len(jobs),r,flush=True)
