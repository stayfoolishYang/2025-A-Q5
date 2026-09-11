"""Small development-only budget selection; no old planner reruns."""
import json,hashlib,argparse
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor,as_completed
import run_routing as batch
from collect import ROOT,SRC,SIM,rb,bench,generate_document,StudySolver
from routing_solver import RoutingSolver
from belief1800 import DiscoveryBelief
from bounded_rerank import choose
OUT=ROOT/'results/bounded_development128'
ARMS=['R12','B0','B5','B10','B20']
class BoundedSolver(RoutingSolver):
    def __init__(self,*a,**kw):
        super().__init__(*a,**kw);self.belief=DiscoveryBelief()
    def decision(self,nodes):
        action=StudySolver.decision(self,nodes)
        if action[0]!='explore' or self.mode=='R12':return action
        for c,h in self.history.items():
            for point,result,_ in h[self.cursor[c]:]:self.belief.observe(c,point,result)
            self.cursor[c]=len(h)
        assert self.belief.seen==self.confirmed
        index,event=choose(self.belief,nodes,self.api.position,float(self.mode[1:]),.05)
        event.update(time_s=self.api.virtual_time,mode=self.mode)
        self.routing_events.append(event)
        return 'explore',index

def extra_hashes():return {n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in ['run_bounded.py','bounded_rerank.py','belief1800.py','REVISED_PLAN.md']}
def freeze():
    assert not(OUT/'manifest.json').exists()
    used={r['physical_hash'] for p in (ROOT/'results').glob('*/manifest.json') for r in json.loads(p.read_bytes())['records'] if 'physical_hash' in r}
    records=[]
    for i in range(128):
        seed=hashlib.sha256(f'2026B-R14-BOUNDED-DEV-v1-{i}'.encode()).hexdigest()
        raw=generate_document(seed_hex=seed,problem=4,format='native');h=bench.physical_hash(raw)
        assert h not in used;used.add(h);file=f'scenes/{i:04d}.json';rb.save(OUT/file,raw)
        records.append(dict(id=i,file=file,cohort='development',family='native_unconditioned',scene_hash=rb.digest(raw),physical_hash=h,total=len(raw['jammers'])))
    cfg=json.loads((SRC/'configs/q4_known16_tri25_R12.yaml').read_bytes())
    rb.save(OUT/'manifest.json',dict(records=records,configs=[dict(cfg,name=a,study_modules=[],belief_routing=a) for a in ARMS],
        source_hashes=bench.fingerprints(SIM),research_hashes=batch.hashes(),extra_hashes=extra_hashes(),
        exclusion_scope='all R14 frozen physical scenes; new seed namespace',official_calls=0))
    print('FROZEN 128 x 5 bounded development',flush=True)
def worker(job):
    m=json.loads((OUT/'manifest.json').read_bytes());assert extra_hashes()==m['extra_hashes']
    batch.OUT=OUT;batch.RoutingSolver=BoundedSolver
    return batch.worker(job)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['freeze','run']);a=p.parse_args()
    if a.action=='freeze':freeze()
    else:
        jobs=[(i,a) for i in range(128) for a in ARMS if not(OUT/'routing_events'/f'{a}_{i:04d}.json.gz').exists()]
        with ProcessPoolExecutor(max_workers=8) as pool:
            for i,f in enumerate(as_completed([pool.submit(worker,j) for j in jobs]),1):
                r=f.result()
                if r[2]!='FULL_CLEAR' or not r[3]:print('FAILED_KEEP',r,flush=True)
                if i%16==0:print(i,len(jobs),r,flush=True)
