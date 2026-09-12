"""Certified clear + baseline bridge; preserve the original live Python continuation."""
import ast,copy,hashlib,inspect,json,math,pickle,textwrap,time
from pathlib import Path
import numpy as np
from solver import Solver
from phase_audit import TaggedSolver
from geometry import is_certified_clear_point
from tspn_geometry import choose

MAX_US=360_000_000_000
def move_us(a,b):
    value=(1e12*math.hypot(float(b[0]-a[0]),float(b[1]-a[1])))/5_000_000
    # Match engine.go_round exactly; adding 0.5 can round twice near a tie.
    fraction,integral=math.modf(value)
    return int(integral)+(1 if fraction>=.5 else -1 if fraction<=-.5 else 0)
def request(path,p=None,c=None):return dict(path=path,position=None if p is None else np.asarray(p,float).tolist(),channel=c)

# Retain every original loop statement; only select its existing continuation.
_tree=ast.parse(textwrap.dedent(inspect.getsource(Solver.run)))
_fn=_tree.body[0];_loop=next(x for x in _fn.body if isinstance(x,ast.While))
_local=next(x for x in _loop.body if isinstance(x,ast.If) and x.body and isinstance(x.body[0],ast.Expr) and isinstance(x.body[0].value,ast.Call) and isinstance(x.body[0].value.func,ast.Attribute) and x.body[0].value.func.attr=='localize')
assert isinstance(_local.body[-1],ast.Continue)
_tail=copy.deepcopy(_local.body[1:])
_pending=ast.parse('if resume_pendin<LOCAL_PATH>').body[0]
_pending.body+=_tail;_loop.body.insert(0,_pending)
_fn.name='resume_after_clear';_fn.args=ast.parse('def f(self,nodes,channel): pass').body[0].args
_fn.body=ast.parse('start=time.perf_counter()\nresume_pending=True').body+_fn.body[3:]
ast.fix_missing_locations(_tree)
_namespace=dict(Solver.run.__globals__)
exec(compile(_tree,'<original-R12-post-localize-continuation>','exec'),_namespace)
RESUME=_namespace['resume_after_clear']

DECISION_KEYS=('mixed','policy','device','particles','use_negative','schedule','diagnostic','failure_context_repair','local_no_signal_streak','measurement_purpose','stop_after_public_max_clear','finish_after_public_max_known','confirmed','known16_trigger','discovery_coverage','clearance_point','discovery_route','discovery_channels','tracks','cleared','history','observations','fallbacks','certified')
def stable(value):
    if isinstance(value,np.ndarray):return ('array',value.dtype.str,value.shape,hashlib.sha256(value.tobytes()).hexdigest())
    if isinstance(value,np.random.Generator):return stable(value.bit_generator.state)
    if isinstance(value,dict):return tuple((str(k),stable(v)) for k,v in sorted(value.items(),key=lambda z:str(z[0])))
    if isinstance(value,(list,tuple)):return tuple(stable(v) for v in value)
    if isinstance(value,set):return tuple(sorted(value))
    if hasattr(value,'__dict__'):return (type(value).__name__,stable(vars(value)))
    return value
def decision(s,position=True,fields=False):
    d={k:getattr(s,k) for k in DECISION_KEYS}
    if d['known16_trigger'] is not None:d['known16_trigger']={k:v for k,v in d['known16_trigger'].items() if k!='time_s'}
    d['nodes']=getattr(s,'remaining_nodes',[]);d['receiver']=s.api.channel
    if position:d['position']=s.api.position
    # Diagnostic-only experiment flag cannot influence original R12 decisions.
    d['diagnostic']={k:v for k,v in d['diagnostic'].items() if k not in ('name','ctspn_enabled','tspn_mode')}
    # Hash semantic content, not pickle's incidental object-sharing memo table.
    def encode(v):
        if isinstance(v,bytes):return v.hex()
        if isinstance(v,np.generic):return v.item()
        raise TypeError(type(v).__name__)
    digest=lambda v:hashlib.sha256(json.dumps(stable(v),default=encode,separators=(',',':'),allow_nan=False).encode()).hexdigest()
    return {k:digest(v) for k,v in d.items()} if fields else digest(d)
def rng_hash(s):
    from recovered_benchmark import digest
    return digest({str(c):t['hyp'].rng.bit_generator.state for c,t in s.tracks.items() if t.get('hyp') is not None})

class FirstAction(BaseException):pass
class OracleAPI:
    def __init__(self,api):self.position=api.position.copy();self.channel=api.channel;self.virtual_time=api.virtual_time;self.stage='discovery';self.armed=False
    def action(self,path,p=None,c=None):
        if self.armed:
            self.request=request(path,p,c);self.request_stage=self.stage
            # Capture before original finally blocks restore purpose/stage.
            self.pre_state=decision(self.owner);self.pre_fields=decision(self.owner,fields=True);self.pre_rng=rng_hash(self.owner)
            raise FirstAction()
        assert path=='/clear'
        self.virtual_time=(round(self.virtual_time*1e6)+move_us(self.position,p)+5_000_000)/1e6
        self.position=np.asarray(p).copy()
        return dict(accepted=True,clear_result='success',virtual_time_s=self.virtual_time)

class Observed(TaggedSolver):
    def release_discovery(self,nodes):
        super().release_discovery(nodes);self.remaining_nodes=nodes
    def check_set(self,c):
        if c in self.tracks:self.target_trace(c).setdefault('conservative_sets',[]).append(dict(time=self.api.virtual_time,polygon=self.tracks[c]['poly'].tolist()))
    def measure(self,c,p):
        result=super().measure(c,p);self.check_set(c);return result
    def clear(self,c,p,certified=False):
        self.check_set(c);return super().clear(c,p,certified)

def peek_next_api_action_after_baseline_clear(s,c,z,rho):
    before=decision(s);wall=time.perf_counter()
    if not is_certified_clear_point(s.tracks[c]['poly'],z,rho) or rho>19.999:raise RuntimeError('UNCERTIFIED_ORACLE_CLEAR')
    clone=Observed.__new__(Observed)
    values={k:getattr(s,k) for k in DECISION_KEYS};values['remaining_nodes']=s.remaining_nodes
    clone.__dict__.update(copy.deepcopy(values));clone.trace={};clone.api=OracleAPI(s.api);clone.api.owner=clone
    Solver.clear(clone,c,np.asarray(z),certified=True)
    clone.api.armed=True
    try:RESUME(clone,clone.remaining_nodes,c)
    except FirstAction:pass
    else:raise RuntimeError('BRIDGE_ORACLE_NOT_RELIABLE:no next request')
    assert decision(s)==before,'ORACLE_SIDE_EFFECT'
    return dict(action=clone.api.request,stage=clone.api.request_stage,pre_bridge_state=clone.api.pre_state,pre_bridge_fields=clone.api.pre_fields,pre_bridge_rng=clone.api.pre_rng,oracle_wall_s=time.perf_counter()-wall)

class BridgeFacade:
    def __init__(self,real,solver):self.real=real;self.solver=solver;self.pending=None;self.armed=None
    def __getattr__(self,k):return getattr(self.real,k)
    @property
    def stage(self):return self.real.stage
    @stage.setter
    def stage(self,v):self.real.stage=v
    @property
    def position(self):return self.pending['z'].copy() if self.pending else self.real.position
    @property
    def virtual_time(self):return self.pending['clear_response']['virtual_time_s'] if self.pending else self.real.virtual_time
    @property
    def channel(self):return self.pending['receiver'] if self.pending else self.real.channel
    def action(self,path,p=None,c=None):
        req=request(path,p,c)
        if self.pending:
            pending=self.pending;ev=pending['event'];start=time.perf_counter()
            if req!=pending['oracle']['action']:raise RuntimeError('BRIDGE_ORACLE_REQUEST_MISMATCH')
            if decision(self.solver)!=pending['oracle']['pre_bridge_state']:
                actual=decision(self.solver,fields=True);expected=pending['oracle']['pre_bridge_fields']
                raise RuntimeError('BRIDGE_PRESTATE_MISMATCH:'+','.join(k for k in actual if actual[k]!=expected[k]))
            if rng_hash(self.solver)!=pending['oracle']['pre_bridge_rng']:raise RuntimeError('BRIDGE_RNG_MISMATCH')
            self.real.log[pending['bridge_index']]['decision_state']=decision(self.solver)
            ev.update(bridge_consumed=True,coalescence_prestate_pass=True,bridge_validation_s=time.perf_counter()-start)
            # Original stack accounts baseline movement from z; fix log-only metric.
            if p is not None:self.solver.target_trace(c)['movement_distance']+=float(np.linalg.norm(np.asarray(p)-pending['q'])-np.linalg.norm(np.asarray(p)-pending['z']))
            self.pending=None
            return pending['bridge_response']
        state=decision(self.solver)
        response=self.real.action(path,p,c);self.real.log[-1]['decision_state']=state
        if not self.armed:return response
        plan=self.armed;self.armed=None;ev=plan['event'];oracle=plan['oracle']
        if path!='/clear' or not response.get('accepted') or response.get('clear_result')!='success':raise RuntimeError('CT_CERTIFIED_CLEAR_HARD_FAIL')
        a=oracle['action'];receiver=self.real.channel;previous=self.real.stage;self.real.stage=oracle['stage']
        bridge=self.real.action(a['path'],None if a['position'] is None else np.array(a['position']),a['channel'])
        self.real.stage=previous
        if bridge.get('accepted') is not True:raise RuntimeError('BRIDGE_REJECTED')
        self.real.log[-1]['rng_before']=oracle['pre_bridge_rng']
        ev.update(bridge_response=bridge,clear_success=True,clear_end_us=round(response['virtual_time_s']*1e6),bridge_end_us=round(bridge['virtual_time_s']*1e6))
        self.pending=dict(**plan,q=np.asarray(p).copy(),receiver=receiver,clear_response=response,bridge_response=bridge,bridge_index=len(self.real.log)-1)
        return response

class CTSolver(Observed):
    def __init__(self,*a,**kw):
        super().__init__(*a,**kw);self.ct_events=[];self.api=BridgeFacade(self.api,self)
        self.ct_enabled=self.diagnostic.get('ctspn_enabled',False)
        if type(self.ct_enabled) is not bool or self.policy!='P4' or not self.mixed:raise ValueError('CT only boolean Q4/P4')
    def clear_certified_polygon(self,c,z,rho):
        # A /clear bridge is already frozen: do not overlap or optimize it again.
        if not self.ct_enabled or self.api.pending:return super().clear_certified_polygon(c,z,rho)
        started=time.perf_counter();poly=self.tracks[c]['poly'];x=self.api.position.copy();z=np.asarray(z,float)
        oracle=peek_next_api_action_after_baseline_clear(self,c,z,rho);a=oracle['action']
        if a['path'] not in ('/measure','/clear','/exit'):return super().clear_certified_polygon(c,z,rho)
        p=None if a['path']=='/exit' else np.asarray(a['position'],float)
        q,meta=choose(poly,x,z,rho,p,'EXACT')
        wire=json.loads(json.dumps(q.tolist(),allow_nan=False));q=np.array(wire)
        if not is_certified_clear_point(poly,q,19.999):q=z.copy();meta['fallback']=True;meta['fallback_reason']='WIRE_CERTIFICATE'
        j0=move_us(x,z)+(0 if p is None else move_us(z,p));j=move_us(x,q)+(0 if p is None else move_us(q,p))
        service=0 if p is None else 5_000_000+(1_000_000*int(a['channel']!=self.api.channel) if a['path']=='/measure' else 0)
        distance=lambda q:math.hypot(*(q-x))+(0 if p is None else math.hypot(*(p-q)))
        allowed=j<j0 and distance(q)<=distance(z) and round(self.api.virtual_time*1e6)+j+5_000_000+service<MAX_US
        if not allowed:q=z.copy();j=j0
        ev=dict(channel=c,start=x.tolist(),z=z.tolist(),q=q.tolist(),polygon=poly.tolist(),rho=rho,action=a,oracle=oracle,model='CT',adopted=bool(allowed),baseline_bridge_us=j0,candidate_bridge_us=j,saving_us=j0-j,baseline_bridge_distance=float(np.linalg.norm(x-z)+(0 if p is None else np.linalg.norm(z-p))),candidate_bridge_distance=float(np.linalg.norm(x-q)+(0 if p is None else np.linalg.norm(q-p))),optimizer=meta,bridge_consumed=False,coalescence_prestate_pass=False,time_before=self.api.virtual_time)
        self.ct_events.append(ev)
        if allowed:self.api.armed=dict(z=z.copy(),oracle=oracle,event=ev)
        # Same already-selected clear, with original target bookkeeping.
        event=dict(selector='CT',start=x.tolist(),polygon=poly.tolist(),mec_center=z.tolist(),mec_radius=float(rho),point=q.tolist(),clearance_radius=19.999,max_vertex_distance=float(np.linalg.norm(poly-q,axis=1).max()),travel_m=float(np.linalg.norm(q-x)),mec_travel_m=float(np.linalg.norm(z-x)),time_before=self.api.virtual_time,model='CT')
        self.target_trace(c).setdefault('certified_clearance_events',[]).append(event)
        success=self.clear(c,q,certified=True)
        event.update(success=bool(success),time_after=self.api.virtual_time)
        ev['total_planning_wall_s']=time.perf_counter()-started
        if not allowed:ev.update(bridge_consumed=True,coalescence_prestate_pass=True,fallback_z=True)
        return success
