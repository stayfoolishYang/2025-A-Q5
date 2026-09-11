"""State-level oracle rankings; no independent-state significance claims."""
import json,gzip
from pathlib import Path
import numpy as np
import pandas as pd
from scipy.stats import rankdata,spearmanr
ROOT=Path(__file__).resolve().parent;SOURCE=ROOT/'results/value_oracle'
def main():
    states=[];nodes=[]
    for p in sorted((SOURCE/'oracle').glob('*.json.gz')):
        with gzip.open(p,'rt') as f:d=json.load(f)
        s=d['state'];q=np.array([b['cost'] for b in d['branches']]);prob=np.array(d['probability_any'])
        order=np.argsort(-prob,kind='stable');optimal=np.flatnonzero(q<=q.min()+1e-6);k=min(3,len(q))
        costorder=np.argsort(q,kind='stable');rho=float(spearmanr(prob,-q).statistic) if len(q)>1 and np.ptp(prob)>0 and np.ptp(q)>0 else None
        row=dict(s,remaining_cost=q[0],spearman=rho,constant_prediction=bool(np.ptp(prob)==0),
            top1_optimal=bool(order[0] in optimal),top3_best_recall=bool(set(order[:k])&set(optimal)),
            top3_overlap=len(set(order[:k])&set(costorder[:k]))/k,
            predictor_regret=q[order[0]]-q.min(),R12_regret=q[0]-q.min(),
            predictor_gain=q[0]-q[order[0]],top3_available_gain=q[0]-q[order[:k]].min(),
            margin=prob[order[0]]-prob[0],H1_pred=d['branches'][order[0]]['hit'],H1_R12=d['branches'][0]['hit'],
            H2_pred=d['branches'][order[0]]['quick_clear'],H2_R12=d['branches'][0]['quick_clear'],
            H3_pred=d['branches'][order[0]]['release16'],H3_R12=d['branches'][0]['release16'])
        states.append(row)
        pr=rankdata(-prob);qr=rankdata(q)
        for i,b in enumerate(d['branches']):nodes.append(dict(id=s['id'],step=s['step'],group=s['sample_group'],N=s['N'],node=i,
            probability=prob[i],cost=q[i],gain=q[0]-q[i],prediction_rank=pr[i],cost_rank=qr[i],
            hit=b['hit'],quick_clear=b['quick_clear'],release16=b['release16']))
    out=ROOT/'analysis/value_oracle';out.mkdir(exist_ok=True);df=pd.DataFrame(states);df.to_csv(out/'states.csv',index=False);pd.DataFrame(nodes).to_csv(out/'nodes.csv',index=False)
    cols=['spearman','top1_optimal','top3_best_recall','top3_overlap','predictor_regret','R12_regret','predictor_gain','H1_pred','H1_R12','H2_pred','H2_R12','H3_pred','H3_R12']
    # Equal scene weights within enriched sampling groups.
    scene=df.groupby(['sample_group','id'])[cols].mean().reset_index();summary=scene.groupby('sample_group')[cols].mean()
    summary.to_csv(out/'group_summary.csv');df.groupby(['N','phase'])[cols].mean().to_csv(out/'N_phase_descriptive.csv')
    rng=np.random.default_rng(14006);intervals=[]
    for group,g in scene.groupby('sample_group'):
        for metric in ['predictor_gain','top3_best_recall','predictor_regret','R12_regret']:
            x=g[metric].dropna().to_numpy();ci=np.quantile(x[rng.integers(len(x),size=(10000,len(x)))].mean(axis=1),[.025,.975])
            intervals.append(dict(group=group,metric=metric,mean=x.mean(),low=ci[0],high=ci[1],scenes=len(x)))
    pd.DataFrame(intervals).to_csv(out/'scene_cluster_intervals.csv',index=False)
    status=dict(complete=len(states)==2000,states=len(states),branches=len(nodes),official_calls=0,
        interpretation='Offline known-world R12-tail counterfactual; not online achievable performance or global optimum')
    (out/'STATUS.json').write_text(json.dumps(status,indent=2));print(status);print(summary.to_string())
if __name__=='__main__':main()
