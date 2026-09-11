"""D: one receding optional support, using frozen diagnostic branch estimates."""
import numpy as np
from geometry import mec
from directional.diagnostic_recovery import choose, branches
from directional.fallback_cost import estimate_optical_fallback_cost
from endpoint_cost import TOL

def support(s,channel,nodes):
    if not nodes or channel is None:return None
    t=s.tracks[channel];poly=t['poly']
    if mec(poly)[1]<=19.999:return None
    p=t['hyp'].p if t['hyp'] is not None else np.empty((0,5))
    if len(p):p=p[np.linspace(0,len(p)-1,min(len(p),1024)).astype(int)]
    cfg=s.diagnostic
    def terminal(poly,point):
        return estimate_optical_fallback_cost(poly,point,exact=False,grid_version=cfg['grid_version'])
    direct=terminal(poly,s.api.position)
    plan=choose(poly,p,s.api.position,s.api.channel,channel,cfg,[o[0] for o in s.history[channel]],device='cpu')
    if plan:direct=min(direct,plan['estimated_cost'])
    records=[]
    for i,q in enumerate(nodes):
        move=float(np.linalg.norm(q-s.api.position))/5
        predicted=sum(w*terminal(post,q) for w,post,_ in branches(poly,p,q))
        estimate=move+5+int(channel!=s.api.channel)+predicted
        records.append(dict(index=i,point=np.asarray(q).tolist(),estimated_cost=estimate,direct_cost=direct,
                            estimated_value_s=direct-estimate,travel_m=move*5))
    best=min(records,key=lambda r:(r['estimated_cost'],r['index']))
    return dict(best=best,accepted=best['estimated_cost']<direct-TOL,candidates=records)
