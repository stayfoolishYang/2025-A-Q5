import json
from pathlib import Path
import numpy as np
import pandas as pd
ROOT=Path(__file__).resolve().parent;SOURCE=ROOT/'results/prior_comparison128'
def main():
    allrows=[];bins=[]
    for radius in (2000,1800):
        files=list((SOURCE/f'evaluation{radius}').glob('*.json'));assert len(files)==128
        for p in files:
            d=json.loads(p.read_bytes())
            allrows.extend([dict(r,prior_radius=radius) for r in d['rows']])
            bins.extend([dict(r,prior_radius=radius) for r in d['bins']])
    df=pd.DataFrame(allrows);out=ROOT/'analysis/prior_comparison128';out.mkdir(exist_ok=True)
    scene=df.groupby(['prior_radius','id','method'])[['top1','top3','mrr','brier','fallback']].mean().reset_index()
    scene.to_csv(out/'scene_metrics.csv',index=False)
    summary=scene.groupby(['prior_radius','method'])[['top1','top3','mrr','brier','fallback']].mean()
    summary.to_csv(out/'summary.csv');pd.DataFrame(bins).groupby(['prior_radius','method','bin'])[['count','predicted_sum','observed_sum']].sum().to_csv(out/'reliability.csv')
    rng=np.random.default_rng(14004);pairs=[]
    for metric in ('top1','top3','mrr','brier'):
        p=scene[scene.method=='belief'].pivot(index='id',columns='prior_radius',values=metric);d=(p[1800]-p[2000]).to_numpy()
        ci=np.quantile(d[rng.integers(len(d),size=(10000,len(d)))].mean(axis=1),[.025,.975])
        pairs.append(dict(metric=metric,difference1800_minus2000=d.mean(),ci95_low=ci[0],ci95_high=ci[1]))
    pd.DataFrame(pairs).to_csv(out/'paired_prior_differences.csv',index=False)
    print(summary.to_string());print(pd.DataFrame(pairs).to_string(index=False))
if __name__=='__main__':main()
