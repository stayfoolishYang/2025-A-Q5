"""B-lite: certified endpoints only; all values in seconds."""
import numpy as np
from geometry import route, mec
TOL=1e-8

def route_m(nodes,start):
    if not len(nodes):return 0.
    p=np.vstack((start,route(np.asarray(nodes),start)))
    return float(np.linalg.norm(np.diff(p,axis=0),axis=1).sum())

def scan(current,cleared,n):
    cost=0
    for _ in range(n):
        order=[current]+[c for c in range(1,21) if c!=current]
        for c in order:
            if c not in cleared:cost+=5+int(c!=current);current=c
    return cost,current

def baseline(s,nodes):
    choices=[]
    for c,t in s.tracks.items():
        p,r=mec(t['poly'])
        choices.append((float(np.linalg.norm(p-s.api.position)/5+(5 if r<=19.999 else 20+r/5)),c))
    local=min(choices) if choices else (float('inf'),None)
    explore=float(np.linalg.norm(nodes[0]-s.api.position)/5+(20-len(s.cleared))*6) if nodes else float('inf')
    if not s.schedule:explore=float('inf')
    action=('local',local[1]) if local[1] is not None and (not nodes or local[0]<=explore) else ('explore',0)
    return action,local,explore

def certified_costs(s,nodes,future_scan=False):
    base,local,_=baseline(s,nodes)
    if not nodes or local[1] is None or mec(s.tracks[local[1]]['poly'])[1]>19.999:return None
    values=[];p=nodes[0];suffix=nodes[1:]
    immediate_scan,end_channel=scan(s.api.channel,s.cleared,1)
    q=float(np.linalg.norm(p-s.api.position)/5)+immediate_scan+route_m(suffix,p)/5
    if future_scan:q+=scan(end_channel,s.cleared,len(suffix))[0]
    values.append((q,('explore',0)))
    for c,t in s.tracks.items():
        center,r=mec(t['poly'])
        if r>19.999:continue
        q=float(np.linalg.norm(center-s.api.position)/5)+5+route_m(nodes,center)/5
        if future_scan:q+=scan(s.api.channel,s.cleared|{c},len(nodes))[0]
        values.append((q,('local',c)))
    # Stable incumbent on numerical ties.
    incumbent=next((v for v in values if v[1]==base),None)
    best=min(values,key=lambda v:(v[0],v[1]))
    if incumbent and incumbent[0]<=best[0]+TOL:best=incumbent
    return best[1],values
