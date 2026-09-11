"""Phase B only changes next discovery destination, after frozen scheduler decision."""
import json
from pathlib import Path
from collect import StudySolver
from belief_fast import DiscoveryBelief
from terminal_route import choose

class RoutingSolver(StudySolver):
    instances=[]
    def __init__(self,*a,**kw):
        super().__init__(*a,**kw)
        self.belief=DiscoveryBelief();self.cursor={c:0 for c in range(1,21)};self.routing_events=[]
        self.mode=self.diagnostic.get('belief_routing','R12');RoutingSolver.instances.append(self)
    def decision(self,nodes):
        action=super().decision(nodes)
        if action[0]!='explore' or self.mode=='R12':return action
        for c,h in self.history.items():
            for point,result,angle in h[self.cursor[c]:]:self.belief.observe(c,point,result)
            self.cursor[c]=len(h)
        assert self.belief.seen==self.confirmed
        index,event=choose(self.belief,nodes,self.api.position,self.api.channel,self.cleared,self.mode)
        event.update(time_s=self.api.virtual_time,selected_index=index,mode=self.mode)
        self.routing_events.append(event)
        return 'explore',index
