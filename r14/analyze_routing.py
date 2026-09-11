"""Complete paired statistical report, with failures and missing cases explicit."""
from pathlib import Path
import json,argparse,hashlib
import numpy as np
import pandas as pd
ROOT=Path(__file__).resolve().parent

def cvar(x,alpha=.9):
    x=np.sort(np.asarray(x))[::-1];mass=len(x)*(1-alpha);k=int(np.floor(mass))
    return float((x[:k].sum()+(mass-k)*x[k] if k<len(x) else x.sum())/mass)

def report(cohort):
    source=ROOT/'results'/cohort;m=json.loads((source/'manifest.json').read_bytes())
    paths=list((source/'core/rows').glob('*.json'));rows=[json.loads(p.read_bytes()) for p in paths]
    df=pd.DataFrame(rows);out=ROOT/'analysis'/cohort;out.mkdir(parents=True,exist_ok=True)
    expected={(r['id'],c['name']) for r in m['records'] for c in m['configs']}
    actual={(r['id'],r['variant']) for r in rows};assert len(actual)==len(rows)
    for r in rows:assert r['scene_hash']==m['records'][r['id']]['scene_hash']
    failed=df[(df.run_status!='FULL_CLEAR')|(~df.audit_passed)]
    failed.to_csv(out/'failures.csv',index=False)
    complete=actual==expected and len(failed)==0
    # Normalize descriptive known16 flag from actual execution configuration.
    df['known16_enabled_from_config']=df.variant.map({c['name']:c['finish_after_public_max_known'] for c in m['configs']})
    df.to_csv(out/'all_rows.csv',index=False)
    status=dict(complete=complete,expected=len(expected),present=len(actual),failed=len(failed),
        missing=sorted(expected-actual),official_calls=0,
        source_hashes={str(p.relative_to(source)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths})
    (out/'AUDIT.json').write_text(json.dumps(status,indent=2),encoding='utf-8')
    if not complete:
        print(json.dumps({k:v for k,v in status.items() if k!='source_hashes'}));return
    summary=[]
    for arm,g in df.groupby('variant'):
        x=g.mean_time_per_source.to_numpy()
        summary.append(dict(arm=arm,n=len(x),mean=x.mean(),median=np.median(x),p95=np.quantile(x,.95),
            p99=np.quantile(x,.99),maximum=x.max(),cvar90=cvar(x),normalized_variance=np.var(x/x.mean(),ddof=1),
            cv=np.std(x,ddof=1)/x.mean(),mean_distance=g.distance.mean(),mean_runtime=g.runtime_s.mean(),
            mean_discovery_s=g.stage_discovery_s.mean(),mean_clear_attempts=g.clear_attempts.mean()))
    pd.DataFrame(summary).to_csv(out/'summary.csv',index=False)
    table=df.pivot(index='id',columns='variant',values='mean_time_per_source');rng=np.random.default_rng(14003);pairs=[]
    for arm in table.columns:
        if arm=='R12':continue
        delta=(table[arm]-table.R12).to_numpy();samples=delta[rng.integers(len(delta),size=(10000,len(delta)))].mean(axis=1)
        low,high=np.quantile(samples,[.0125,.9875])
        pairs.append(dict(arm=arm,mean_difference=delta.mean(),ci97_5_low=low,ci97_5_high=high,
            relative_improvement=1-table[arm].mean()/table.R12.mean(),wins=int((delta < -1e-8).sum()),
            ties=int((abs(delta)<=1e-8).sum()),losses=int((delta>1e-8).sum()),
            worst_regression=delta.max(),worst_case=int(table.index[np.argmax(delta)])))
    pd.DataFrame(pairs).to_csv(out/'paired_comparisons.csv',index=False)
    for key in ('total','directional_count'):
        df.groupby(['variant',key]).mean_time_per_source.agg(['count','mean','std','max']).to_csv(out/f'strata_{key}.csv')
    print(pd.DataFrame(summary).to_string(index=False));print(pd.DataFrame(pairs).to_string(index=False))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('cohort');a=p.parse_args();report(a.cohort)
