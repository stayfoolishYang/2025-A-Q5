"""OFFLINE ORACLE ONLY: exact world clones; never imported by an online planner."""
import copy
import numpy as np
from collect import StudySolver,rb
from solver import Solver

class OracleAdapter(rb.EngineAdapter):
    def action(self,path,position=None,channel=None):
        if path=='/enter':
            assert self._engine.entered and not self.log
            return dict(accepted=True,virtual_time_s=self.virtual_time)
        rng=rb.digest({str(c):t['hyp'].rng.bit_generator.state for c,t in self.solver.tracks.items() if t.get('hyp') is not None})
        r=super().action(path,position,channel);self.log[-1]['rng_before']=rng
        return r

class Continuation(StudySolver):
    def make_route(self,nodes,kind):
        if kind=='initial':return list(self.saved_nodes.copy())
        return super().make_route(nodes,kind)
    def decision(self,nodes):
        if self.forced is not None:
            i=self.forced;self.forced=None;return ('explore',i)
        if self.sweep_end is None:
            self.sweep_end=self.api.virtual_time;self.sweep_confirmed=set(self.confirmed)
        return super().decision(nodes)

def clone_at_decision(original,nodes,index):
    # Copy solver state without copying the adapter, hidden-world closure, or
    # Collector buffers. Engine truth is copied separately in this oracle only.
    blank=Solver(None,True,'P4','cpu',original.particles,diagnostic=original.diagnostic)
    fields=set(blank.__dict__)-{'api'}
    clone=object.__new__(Continuation)
    clone.__dict__.update(copy.deepcopy({k:original.__dict__[k] for k in fields}))
    clone.modules=set();clone.events=[];clone.route_events=[];clone.optional=[];clone.active_route=None
    clone.saved_nodes=np.asarray(nodes).copy();clone.forced=index;clone.sweep_end=None;clone.sweep_confirmed=None
    engine=copy.deepcopy(original.api._engine)
    api=OracleAdapter(engine);api.position=original.api.position.copy();api.channel=original.api.channel
    api.virtual_time=original.api.virtual_time;api.stage=original.api.stage;api.solver=clone;clone.api=api
    return clone

def run_branch(original,nodes,index,tau=120.):
    before=original.api.virtual_time;known=set(original.confirmed)
    clone=clone_at_decision(original,nodes,index);clone.run()
    if clone.sweep_end is None:clone.sweep_end=clone.api.virtual_time;clone.sweep_confirmed=set(clone.confirmed)
    new={};clear={}
    for a in clone.api.log:
        r=a['response'];c=a['channel'];time=r['virtual_time_s']
        if c not in known and r.get('measure_result') in ('direction','near') and time<=clone.sweep_end:
            new.setdefault(c,time)
        if r.get('clear_result')=='success':clear[c]=time
    assert len(clone.cleared)==len(clone.api._engine.sources),'Oracle continuation incomplete'
    assert original.api.virtual_time==before
    return dict(cost=clone.api.virtual_time-before,hit=bool(new),
        quick_clear=any(c in clear and clear[c]-t<=tau for c,t in new.items()),
        release16=len(clone.sweep_confirmed)==16 and len(known)<16,
        stages=clone.api.stages,actions=clone.api.log)
