"""Q4-only research loop. Frozen Solver owns every physical/safety action."""
import time
import numpy as np
from phase_audit import TaggedSolver
from geometry import route,coverage,mec
from discovery import refresh_remaining_route
from endpoint_cost import baseline,certified_costs
from scan_credit import choose as credit_choose,credits
from strong_route import optimize
from soft_release import support
from short_rollout import choose as rollout_choose

class StudySolver(TaggedSolver):
    instances=[]
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.modules=set(self.diagnostic.get('study_modules',[]))
        self.events=[];self.route_events=[];self.optional=[];self.active_route=None
        StudySolver.instances.append(self)
    def finish_route(self,reason):
        if self.active_route is None:return
        e=self.active_route;e['end_reason']=reason;e['route_survival_time']=self.api.virtual_time-e['time_s']
        e['fraction_of_planned_route_executed']=e['executed_m']/e['planned_m'] if e['planned_m'] else 0.
        self.active_route=None
    def make_route(self,nodes,kind):
        self.finish_route(kind)
        start=time.perf_counter();p=self.api.position.copy()
        incumbent=refresh_remaining_route(nodes,p) if kind=='localize' else list(route(np.asarray(nodes),p))
        base=np.vstack((p,incumbent));base_m=float(np.linalg.norm(np.diff(base,axis=0),axis=1).sum())
        result=optimize(incumbent,p) if 'A1' in self.modules else incumbent
        assert sorted(map(tuple,result))==sorted(map(tuple,nodes))
        pts=np.vstack((p,result));planned=float(np.linalg.norm(np.diff(pts,axis=0),axis=1).sum())
        e=dict(time_s=self.api.virtual_time,kind=kind,start=p.tolist(),nodes=np.asarray(result).tolist(),
               r12_m=base_m,planned_m=planned,snapshot_saving_s=(base_m-planned)/5,
               gap=(base_m-planned)/planned if planned else 0.,route_ms=1000*(time.perf_counter()-start),
               route_survival_nodes=0,executed_m=0.,route_survival_time=0.,fraction_of_planned_route_executed=0.)
        self.route_events.append(e);self.active_route=e
        return list(result)
    def release_discovery(self,nodes):
        if self.known16_trigger is not None and nodes:
            self.events.append(dict(kind='known16_release',time_s=self.api.virtual_time,nodes=np.asarray(nodes).tolist(),
                position=self.api.position.tolist(),remaining_targets=len(self.tracks)))
            if 'D' in self.modules:self.optional=list(nodes)
            self.finish_route('known16')
        return super().release_discovery(nodes)
    def decision(self,nodes):
        begin=time.perf_counter();old,local,explore=baseline(self,nodes);action=old
        event=dict(kind='decision',time_s=self.api.virtual_time,current_channel=self.api.channel,
            remaining_nodes=len(nodes),cleared=len(self.cleared),baseline=old,credit=credits(self,nodes))
        if 'B-lite' in self.modules:
            v=certified_costs(self,nodes)
            if v:action=v[0]
        if 'C1' in self.modules:action=credit_choose(self,nodes,'C1')
        if 'C2' in self.modules:action=credit_choose(self,nodes,'C2')
        if 'E-H2' in self.modules:action,event['rollout']=rollout_choose(self,nodes)
        if 'D' in self.modules and self.known16_trigger is not None and self.optional:
            plan=support(self,local[1],self.optional)
            if plan:
                event['support']=plan
                if plan['accepted']:action=('support',(local[1],plan['best']['index']))
        event.update(action=action,disagrees=action!=old,decision_ms=1000*(time.perf_counter()-begin))
        self.events.append(event);return action
    def run(self):
        start=time.perf_counter();self.api.action('/enter')
        nodes=self.make_route(list(coverage(True,version=self.discovery_coverage)),'initial')
        while (nodes or self.tracks) and not self.public_max_complete():
            self.release_discovery(nodes)
            action=self.decision(nodes)
            if action[0]=='support':
                self.finish_route('support');c,i=action[1];p=self.optional.pop(i)
                previous=self.api.stage;self.api.stage='active_localization'
                try:self.measure(c,p)
                finally:self.api.stage=previous
                continue
            if action[0]=='local':
                self.finish_route('localization');self.localize(action[1],one_step=True)
                if self.public_max_complete():break
                self.release_discovery(nodes)
                if nodes:nodes=self.make_route(nodes,'localize')
                continue
            p=nodes.pop(action[1])
            if self.active_route:
                self.active_route['route_survival_nodes']+=1
                self.active_route['executed_m']+=float(np.linalg.norm(p-self.api.position))
            channels=[self.api.channel]+[c for c in range(1,21) if c!=self.api.channel]
            for c in channels:
                if c in self.cleared:continue
                self.measure(c,p)
                if self.public_max_complete():break
                if self.known16_trigger is not None:self.release_discovery(nodes);break
            if self.public_max_complete():break
            if nodes:nodes=self.make_route(nodes,'after_discovery')
        self.release_discovery(nodes);self.finish_route('exit');self.api.action('/exit')
        return dict(policy=self.policy,mixed=True,cleared=len(self.cleared),virtual_time_s=self.api.virtual_time,
            mean_time_per_source_s=self.api.virtual_time/max(1,len(self.cleared)),runtime_s=time.perf_counter()-start,
            localization_observations=self.observations,optical_fallbacks=self.fallbacks,certified_clears=self.certified,
            completion_reason='public_max_cleared' if self.public_max_complete() else 'coverage_exhausted')
