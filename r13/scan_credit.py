"""C1/C2: conditional scan obligations; clear never switches channel."""
from geometry import mec
from endpoint_cost import scan, baseline, certified_costs, TOL

def credits(s,nodes):
    before=scan(s.api.channel,s.cleared,len(nodes))[0]
    return {c:before-scan(s.api.channel,s.cleared|{c},len(nodes))[0]
            for c,t in s.tracks.items() if mec(t['poly'])[1]<=19.999}

def choose(s,nodes,mode):
    base,local,explore=baseline(s,nodes)
    if mode=='C2':
        values=certified_costs(s,nodes,True)
        return values[0] if values else base
    credit=credits(s,nodes)
    if local[1] in credit and abs(local[0]-explore)<=TOL and credit[local[1]]>0:
        return ('local',local[1])
    return base

if __name__=='__main__':
    assert scan(1,set(),1)==(119,20)
    assert scan(1,{1},1)==(114,20)
    assert scan(20,set(),2)[0]-scan(20,{20},2)[0]==11
