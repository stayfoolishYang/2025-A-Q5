"""Post-hoc geometry opportunity, never a scored policy outcome."""
import csv,json
from pathlib import Path
import numpy as np
from geometry import area
from tspn_benchmark import OUT,read,rb
from tspn_geometry import choose,length,R_CLEAR

def write_csv(p,rows):
    rows=list(rows);p=Path(p);p.parent.mkdir(parents=True,exist_ok=True)
    keys=list(dict.fromkeys(k for r in rows for k in r))
    with p.open('w',newline='',encoding='utf-8-sig') as f:
        w=csv.DictWriter(f,keys);w.writeheader()
        for row in rows:w.writerow({k:json.dumps(v,ensure_ascii=False) if isinstance(v,(dict,list)) else v for k,v in row.items()})

def main():
    rows=[]
    for f in sorted((OUT/'development/core/traces').glob('A_*.json.gz')):
        t=read(f)
        for c in t['targets']:
            for e in c.get('certified_clearance_events',[]):
                poly,x,m=np.array(e['polygon']),np.array(e['start']),np.array(e['mec_center']);u=e['next_mandatory_anchor'];u=None if u is None else np.array(u)
                a,am=choose(poly,x,m,e['mec_radius'],u,'MEC');b,bm=choose(poly,x,m,e['mec_radius'],u,'EXACT')
                rows.append(dict(case_id=t['row']['id'],channel=c['channel'],current_position=x.tolist(),R12_clear_point=e['point'],hard_region_area=area(poly),MEC_center=m.tolist(),MEC_radius=e['mec_radius'],R_clear=20.,safe_MEC_radius=20-e['mec_radius'],operational_safe_radius=am['safe_radius'],exact_neighborhood_available=True,next_mandatory_anchor=e['next_mandatory_anchor'],baseline_insertion_distance=length(x,m,u),best_MEC_insertion_distance=am['optimized_local_length'],best_EXACT_insertion_distance=bm['optimized_local_length'],saving_MEC=am['local_saving'],saving_EXACT=bm['local_saving'],MEC_gap_bound=am['optimality_gap_bound'],EXACT_gap_bound=bm['optimality_gap_bound'],MEC_fallback=am['fallback'],EXACT_fallback=bm['fallback']))
    write_csv(OUT/'clear_neighborhood_opportunity.csv',rows)
    r=np.array([e['safe_MEC_radius'] for e in rows]);a=sum(e['saving_MEC'] for e in rows);b=sum(e['saving_EXACT'] for e in rows)
    result=dict(passed=bool(a>1e-6 or b>1e-6),events=len(rows),safe_radius_mean=float(r.mean()),safe_radius_quantiles=dict(zip(['min','P25','median','P75','P90','P95','max'],np.quantile(r,[0,.25,.5,.75,.9,.95,1]).tolist())),zero_slack_ratio=float(np.mean(r<=1e-9)),positive_slack_ratio=float(np.mean(r>1e-9)),MEC_total_local_saving_m=a,EXACT_total_local_saving_m=b,EXACT_extra_local_saving_m=b-a,numerics='Certified feasible numerical candidates; gap bounds supplied, not exact optimizer oracle',scope='POST_HOC_OPPORTUNITY_ONLY; NOT WHOLE-GAME SAVING')
    rb.save(OUT/'OPPORTUNITY.json',result);print(json.dumps(result,ensure_ascii=False))
if __name__=='__main__':main()
