"""Scene-paired summaries and mechanism evidence, no solver execution."""
from pathlib import Path
import json,gzip,argparse,hashlib
import numpy as np
import pandas as pd
ROOT=Path(__file__).resolve().parent
OUT=ROOT/'analysis';OUT.mkdir(exist_ok=True)

def csv(df,name):df.to_csv(OUT/name,index=False,encoding='utf-8-sig')
def trace(path):
    with gzip.open(path,'rt',encoding='utf-8') as f:return json.load(f)

def analyze(cohort):
    folder=ROOT/'results'/cohort;m=json.loads((folder/'manifest.json').read_bytes())
    rows=pd.DataFrame([json.loads(p.read_bytes()) for p in sorted((folder/'core/rows').glob('*.json'))])
    assert len(rows)==len(m['records'])*len(m['configs']),(len(rows),len(m['records']),len(m['configs']))
    base=rows[rows.variant=='R12'].set_index('id');summaries=[];pairs=[];strata=[];routes=[];decisions=[];credits=[];releases=[];extremes=[]
    for method,g in rows.groupby('variant',sort=False):
        g=g.sort_values('id');b=base.loc[g.id];x=g.mean_time_per_source.to_numpy();bx=b.mean_time_per_source.to_numpy();delta=x-bx
        n=len(x);n16=g[g.total==16];safe=bool(((g.run_status=='FULL_CLEAR')&g.audit_passed&(g.cleared==g.total)).all())
        improvement=100*(1-x.mean()/bx.mean());cv=x.std(ddof=1)/x.mean()
        rng=np.random.default_rng(20260912);ids=rng.integers(0,n,(2000,n))
        def qi(v,q):return float(np.quantile(v,q))
        tail=lambda q:100*(qi(x,q)/qi(bx,q)-1)
        benefit=any(tail(q)<=-2 for q in (.95,.99,1)) or cv<=(bx.std(ddof=1)/bx.mean())*.98
        bn16=b[b.total==16]
        benefit|=int((n16.fallback_count>0).sum())<int((bn16.fallback_count>0).sum())
        risky=tail(.95)>2 or tail(.99)>2 or tail(1)>5
        decision='BASELINE' if method=='R12' else 'REJECT' if not safe else 'RISKY' if improvement>0 and risky else 'STRONG' if improvement>=1 and not risky else 'RETAIN' if improvement>=.3 and benefit else 'STOP'
        if cohort=='regression':decision='REGRESSION_ONLY'
        s=dict(method=method,development_or_holdout=cohort,runs=n,full_clear=int((g.run_status=='FULL_CLEAR').sum()),safety_pass=safe,
            mean_s_per_source=x.mean(),improvement_pct=improvement,P50=qi(x,.5),P95=qi(x,.95),P99=qi(x,.99),max=x.max(),
            normalized_variance=float(np.var(x/x.mean(),ddof=1)),CV=cv,movement_km=g.distance.mean()/1000,
            measure_count=g.detect_count.mean(),switch_count=g.switch_count.mean(),diagnostic_count=g.diagnostic_count.mean(),fallback_count=g.fallback_count.mean(),
            confirmed16_s=g.known16_time_s.mean(),last_detection_s=g.last_source_first_seen_s.mean(),route_compute_ms_p95=g.route_compute_ms_p95.mean(),decision_compute_ms_p95=g.decision_compute_ms_p95.mean(),
            wins=int((delta<-1e-6).sum()),ties=int((abs(delta)<=1e-6).sum()),losses=int((delta>1e-6).sum()),mean_delta=delta.mean(),median_delta=np.median(delta),max_regression=delta.max(),
            N16_mean=n16.mean_time_per_source.mean(),N16_P95=n16.mean_time_per_source.quantile(.95),N16_max=n16.mean_time_per_source.max(),classification=decision,
            mean_delta_ci_low=qi(delta[ids].mean(axis=1),.025),mean_delta_ci_high=qi(delta[ids].mean(axis=1),.975),
            P95_change_pct=tail(.95),P99_change_pct=tail(.99),max_change_pct=tail(1))
        for metric,q in [('mean',None),('P95',.95),('P99',.99)]:
            a=x[ids].mean(axis=1) if q is None else np.quantile(x[ids],q,axis=1)
            z=bx[ids].mean(axis=1) if q is None else np.quantile(bx[ids],q,axis=1)
            s[metric+'_improvement_ci_low']=qi(100*(1-a/z),.025);s[metric+'_improvement_ci_high']=qi(100*(1-a/z),.975)
        summaries.append(s)
        for N,gn in g.groupby('total'):
            xx=gn.mean_time_per_source.to_numpy();bb=base.loc[gn.id].mean_time_per_source.to_numpy()
            strata.append(dict(cohort=cohort,method=method,N=N,n=len(xx),mean=xx.mean(),improvement_pct=100*(1-xx.mean()/bb.mean()),normalized_variance=np.var(xx/xx.mean(),ddof=1),CV=xx.std(ddof=1)/xx.mean(),P95=qi(xx,.95),max=xx.max()))
        for j,r in enumerate(g.to_dict('records')):
            case=r['id'];tr=trace(folder/'core/traces'/f'{method}_{case:04d}.json.gz')
            for i,e in enumerate(tr['route_events']):routes.append(dict(cohort=cohort,method=method,id=case,index=i,**{k:v for k,v in e.items() if k not in ('nodes','start')}))
            for i,e in enumerate(tr['study_events']):
                if e['kind']=='decision':
                    decisions.append(dict(cohort=cohort,method=method,id=case,index=i,time_s=e['time_s'],decision_ms=e['decision_ms'],disagrees=e['disagrees'],action=e['action'][0],current_channel=e['current_channel'],remaining_nodes=e['remaining_nodes']))
                    for c,v in e['credit'].items():credits.append(dict(cohort=cohort,method=method,id=case,time_s=e['time_s'],channel=c,current_channel=e['current_channel'],nodes=e['remaining_nodes'],credit_s=v,action=e['action'][0]))
                    if 'support' in e:
                        p=e['support'];releases.append(dict(cohort=cohort,method=method,id=case,kind='support_decision',time_s=e['time_s'],accepted=p['accepted'],**p['best']))
                elif e['kind']=='known16_release':
                    nodes=np.asarray(e['nodes']);p=np.asarray(e['position'])
                    releases.append(dict(cohort=cohort,method=method,id=case,kind='release',time_s=e['time_s'],remaining_nodes=len(nodes),remaining_targets=e['remaining_targets'],nearest_node_m=np.linalg.norm(nodes-p,axis=1).min()))
            pairs.append(dict(cohort=cohort,method=method,id=case,N=r['total'],baseline_s=bx[j],candidate_s=x[j],delta_s=delta[j],improvement_pct=100*(1-x[j]/bx[j]),distance_delta_m=r['distance']-b.iloc[j].distance,measure_delta=r['detect_count']-b.iloc[j].detect_count,
                post_known16_s=r['post_known16_s'],baseline_post_known16_s=b.iloc[j].post_known16_s,trace_path=str(folder/'core/traces'/f'{method}_{case:04d}.json.gz')))
        if method!='R12':
            order=np.argsort(delta,kind='stable')
            for kind,indices in [('best',order[:10]),('worst',order[-10:][::-1])]:
                for rank,j in enumerate(indices,1):extremes.append(dict(cohort=cohort,method=method,kind=kind,rank=rank,id=int(g.iloc[j].id),delta_s=float(delta[j])))
            worst=int(g.iloc[order[-1]].id);opt=trace(folder/'core/traces'/f'{method}_{worst:04d}.json.gz');ref=trace(folder/'core/traces'/f'R12_{worst:04d}.json.gz')
            mining=OUT/'failure_mining'/cohort/method;mining.mkdir(parents=True,exist_ok=True)
            for name,t in [('R12',ref),(method,opt)]:
                pd.DataFrame(t['actions']).to_csv(mining/f'{name}_full_trajectory.csv',index=False,encoding='utf-8-sig')
            report=dict(id=worst,delta_s_per_source=float(delta[order[-1]]),candidate=opt['row'],baseline=ref['row'],candidate_stages=opt['stages'],baseline_stages=ref['stages'],candidate_route_events=opt['route_events'],baseline_route_events=ref['route_events'])
            (mining/'MAX_REGRESSION.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    for data,name in [(rows,'rows'),(pd.DataFrame(summaries),'summary'),(pd.DataFrame(pairs),'pairs'),(pd.DataFrame(strata),'strata'),(pd.DataFrame(routes),'routes'),(pd.DataFrame(decisions),'decisions'),(pd.DataFrame(credits),'credits'),(pd.DataFrame(releases),'known16'),(pd.DataFrame(extremes),'extremes')]:csv(data,f'{cohort}_{name}.csv')
    # Replace per-case averaged compute quantiles with pooled decision/route samples.
    sf=pd.DataFrame(summaries)
    for i,r in sf.iterrows():
        rr=pd.DataFrame(routes);dd=pd.DataFrame(decisions)
        sf.loc[i,'route_compute_ms_p95']=rr.loc[rr.method==r.method,'route_ms'].quantile(.95)
        sf.loc[i,'decision_compute_ms_p95']=dd.loc[dd.method==r.method,'decision_ms'].quantile(.95)
    csv(sf,f'{cohort}_summary.csv')
    print(sf[['method','full_clear','mean_s_per_source','improvement_pct','P95','P99','max','classification']].to_string(index=False))
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('cohort');analyze(p.parse_args().cohort)
