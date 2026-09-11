"""Large offline oracle study, isolated from deployable strategy modules."""
import json,gzip,hashlib,argparse
from concurrent.futures import ProcessPoolExecutor,as_completed
import numpy as np
from collect import ROOT,SIM,SRC,bench,rb,phase_audit,Collector,StudySolver,generate_document
from scenario_io import load_scenario
from oracle_replay import run_branch
from belief1800 import DiscoveryBelief
OUT=ROOT/'results/value_oracle'
def freeze():
    assert not(OUT/'manifest.json').exists()
    used={r['physical_hash'] for p in (ROOT/'results').glob('*/manifest.json') for r in json.loads(p.read_bytes())['records'] if 'physical_hash' in r}
    records=[];attempt=0
    for i in range(1024):
        want=16 if i<512 else 10+(i-512)%6
        while True:
            seed=hashlib.sha256(f'2026B-R14-VALUE-ORACLE-v1-{attempt}'.encode()).hexdigest();attempt+=1
            raw=generate_document(seed_hex=seed,problem=4,format='native')
            if len(raw['jammers'])==want:break
        h=bench.physical_hash(raw);assert h not in used;used.add(h);file=f'scenes/{i:04d}.json';rb.save(OUT/file,raw)
        records.append(dict(id=i,file=file,cohort='oracle_audit',family='N_stratified',total=want,scene_hash=rb.digest(raw),physical_hash=h))
    cfg=json.loads((SRC/'configs/q4_known16_tri25_R12.yaml').read_bytes())
    rb.save(OUT/'manifest.json',dict(records=records,configs=[dict(cfg,name='R12',study_modules=[])],source_hashes=bench.fingerprints(SIM),
        code_hashes={n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in ['run_oracle_study.py','oracle_replay.py','belief1800.py','belief_fast.py','collect.py']},official_calls=0))
    print('FROZEN1024',flush=True)
def verify():
    m=json.loads((OUT/'manifest.json').read_bytes())
    for n,h in m['code_hashes'].items():assert hashlib.sha256((ROOT/n).read_bytes()).hexdigest()==h
    return m

def collect_case(i):
    verify();p=OUT/'snapshots'/f'{i:04d}.json.gz'
    if p.exists():return i
    Collector.instances.clear();StudySolver.instances.clear();old=phase_audit.TaggedSolver;phase_audit.TaggedSolver=Collector
    try:r=bench.run_case((str(OUT),str(SIM),i,'R12',False))
    finally:phase_audit.TaggedSolver=old
    assert r['run_status']=='FULL_CLEAR' and r['audit_passed'];p.parent.mkdir(exist_ok=True)
    with gzip.open(p,'wt') as f:json.dump(Collector.instances[-1].snapshots,f)
    return i

def select():
    m=verify();states=[]
    for r in m['records']:
        with gzip.open(OUT/'snapshots'/f'{r["id"]:04d}.json.gz','rt') as f:snap=json.load(f)
        for j,s in enumerate(snap):
            phase='early' if j/len(snap)<1/3 else 'middle' if j/len(snap)<2/3 else 'late'
            states.append(dict(id=r['id'],step=j,phase=phase,N=r['total'],time_s=s['time_s'],nodes=len(s['nodes'])))
    rng=np.random.default_rng(14005);chosen=[];used=set()
    for group in ['early','middle','late','N16_late']:
        candidates=[s for s in states if (s['id'],s['step']) not in used and
                    (s['phase']==group if group!='N16_late' else s['N']==16 and s['phase']=='late')]
        assert len(candidates)>=500,(group,len(candidates),'expand unique state pool')
        for k in rng.choice(len(candidates),500,replace=False):
            s=dict(candidates[k],sample_group=group);chosen.append(s);used.add((s['id'],s['step']))
    assert len(used)==2000
    rb.save(OUT/'selection.json',dict(states=chosen,branches=sum(s['nodes'] for s in chosen),pool_states=len(states),official_calls=0))
    print('SELECTED2000',sum(s['nodes'] for s in chosen),'branches',flush=True)

class OracleCapture(StudySolver):
    selected={};completed=[];reference_finish=0
    def decision(self,nodes):
        action=super().decision(nodes)
        if action[0]!='explore':return action
        step=getattr(self,'ordinal',0);self.ordinal=step+1
        if step not in self.selected:return action
        state=self.selected[step];i=state['id'];path=OUT/'oracle'/f'{i:04d}_{step:02d}.json.gz'
        if path.exists():return action
        assert self.api.virtual_time==state['time_s']
        b=DiscoveryBelief()
        for c,h in self.history.items():
            for p,r,_ in h:b.observe(c,p,r)
        pred=b.predict(nodes);assert pred['available']
        branches=[]
        for q in range(len(nodes)):
            branch=run_branch(self,nodes,q)
            if q==0:assert abs(branch['cost']-(self.reference_finish-self.api.virtual_time))<1e-6
            branch['index']=q;branches.append(branch)
        path.parent.mkdir(exist_ok=True)
        with gzip.open(path,'wt') as f:json.dump(dict(state=state,probability_any=pred['probability_any'].tolist(),expected_new=pred['expected_new'].tolist(),branches=branches),f)
        self.completed.append((i,step));return action

def oracle_case(i):
    m=verify();selection=json.loads((OUT/'selection.json').read_bytes())['states'];selected={s['step']:s for s in selection if s['id']==i}
    if all((OUT/'oracle'/f'{i:04d}_{j:02d}.json.gz').exists() for j in selected):return i
    # Original solver replays the baseline prefix while candidates branch privately.
    from engine import Engine
    raw=json.loads((OUT/m['records'][i]['file']).read_bytes());api=rb.EngineAdapter(Engine(load_scenario(raw)))
    cfg=m['configs'][0];s=OracleCapture(api,True,'P4','cpu',cfg.get('particles',16384),diagnostic=cfg)
    s.selected=selected;s.reference_finish=json.loads((OUT/'core/rows'/f'R12_{i:04d}.json').read_bytes())['virtual_time_s']
    s.run();assert abs(api.virtual_time-s.reference_finish)<1e-6
    StudySolver.instances.clear();return i

def parallel(fn,jobs,label):
    with ProcessPoolExecutor(max_workers=8) as pool:
        for n,f in enumerate(as_completed([pool.submit(fn,j) for j in jobs]),1):
            f.result()
            if n%16==0:print(label,n,len(jobs),flush=True)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['freeze','collect','select','oracle']);a=p.parse_args()
    if a.action=='freeze':freeze()
    elif a.action=='collect':parallel(collect_case,list(range(1024)),'BASELINES')
    elif a.action=='select':select()
    else:
        ids=sorted({s['id'] for s in json.loads((OUT/'selection.json').read_bytes())['states']});parallel(oracle_case,ids,'ORACLE_SCENES')
