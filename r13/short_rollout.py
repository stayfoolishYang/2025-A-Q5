"""E-H2: bounded frozen-information rollout; no hidden observations."""
import numpy as np
from geometry import mec
from endpoint_cost import baseline, route_m, scan, TOL

def choose(s,nodes):
    incumbent,local,_=baseline(s,nodes)
    if not nodes:return incumbent,[]
    best_channel=local[1]
    if best_channel is not None:
        t=s.tracks[best_channel]
        if mec(t['poly'])[1]>19.999 and (t['n']>=8 or t['negatives']>=3):return incumbent,[]
    centers={c:mec(t['poly']) for c,t in s.tracks.items()}
    def proxy(position,remaining):
        return min((float(np.linalg.norm(centers[c][0]-position))/5+(5 if centers[c][1]<=19.999 else 20+centers[c][1]/5) for c in remaining),default=0.)
    def actions(position,channel,remaining_nodes,remaining_tracks,used_local):
        result=[]
        if best_channel in remaining_tracks and not used_local:
            c=best_channel;t=s.tracks[c];center,radius=centers[c]
            if radius<=19.999:
                point=center;cost=float(np.linalg.norm(point-position))/5+5
                result.append((('local',c),cost,point,channel,remaining_nodes,remaining_tracks-{c},True,s.cleared|{c}))
            elif t['hyp'] is not None:
                point=t['hyp'].next(t['poly'],position)
                if any(np.linalg.norm(point-old)<.1 for old in t['views']):point=center+np.array([25.,25.])
                cost=float(np.linalg.norm(point-position))/5+5+int(channel!=c)
                result.append((('local',c),cost,point,c,remaining_nodes,remaining_tracks,True,s.cleared))
        ids=sorted(remaining_nodes,key=lambda i:(float(np.linalg.norm(nodes[i]-position)),i))[:6-len(result)]
        for i in ids:
            point=nodes[i];cost,end=scan(channel,s.cleared,1)
            result.append((('explore',i),cost+float(np.linalg.norm(point-position))/5,point,end,[j for j in remaining_nodes if j!=i],remaining_tracks,used_local,s.cleared))
        return result
    def expand(position,channel,ids,tracks,used,cleared,depth):
        if depth==0:return route_m([nodes[i] for i in ids],position)/5+proxy(position,tracks)
        values=[]
        for _,cost,p,ch,left,ts,ul,cs in actions(position,channel,ids,tracks,used):
            # Correct scan prefixes after a certified clear; channels remain physical measurement state.
            if cs==s.cleared and cleared!=s.cleared:
                if len(left)<len(ids):cost+=scan(channel,cleared,1)[0]-scan(channel,s.cleared,1)[0];ch=scan(channel,cleared,1)[1]
                cs=cleared
            values.append(cost+expand(p,ch,left,ts,ul,cs,depth-1))
        return min(values) if values else route_m([nodes[i] for i in ids],position)/5+proxy(position,tracks)
    records=[]
    for action,cost,p,ch,ids,tracks,used,cleared in actions(s.api.position,s.api.channel,list(range(len(nodes))),set(s.tracks),False):
        records.append((cost+expand(p,ch,ids,tracks,used,cleared,1),action))
    if not records:return incumbent,[]
    best=min(records,key=lambda x:(x[0],x[1]))
    old=next((r for r in records if r[1]==incumbent),None)
    if old and old[0]<=best[0]+TOL:best=old
    return best[1],records
