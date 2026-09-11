"""Run the retained R12 on an archived case using the specified original engine."""
import argparse,gzip,json,sys
from pathlib import Path
import known16_tri25_benchmark as bench

def main():
 p=argparse.ArgumentParser();p.add_argument('--sim-root',type=Path,required=True);p.add_argument('--case',type=int,choices=(50,218,253,288,298,311),default=50);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
 sim=a.sim_root.resolve();sys.path.insert(0,str(sim));out=a.output.resolve()
 if out.exists():p.error('Use a new output directory; archived results are never overwritten')
 prior=Path(__file__).resolve().parent/'results/known16_tri25_factorial_20260911_v1';m=json.loads((prior/'manifest.json').read_bytes());rec=dict(m['records'][a.case]);raw=json.loads((prior/rec['file']).read_bytes());assert bench.rb.digest(raw)==rec['scene_hash']
 rec.update(id=0,file='scenes/0000.json',cohort='regression',previous_id=a.case)
 cfg=next(c for c in m['configs'] if c['name']=='R12')
 bench.rb.save(out/rec['file'],raw);bench.rb.save(out/'manifest.json',dict(records=[rec],configs=[cfg],source_hashes=bench.fingerprints(sim),simulator_root=str(sim)))
 row=bench.run_case((out,sim,0,'R12',None))
 with gzip.open(out/'core/traces/R12_0000.json.gz','rt',encoding='utf-8') as f:current=json.load(f)
 with gzip.open(prior/f'core/traces/R12_{a.case:04d}.json.gz','rt',encoding='utf-8') as f:old=json.load(f)
 check=dict(case=a.case,full_clear=row['run_status']=='FULL_CLEAR',audit_passed=row['audit_passed'],exact_actions_rng=bench.canonical_actions(current)==bench.canonical_actions(old),virtual_time_s=row['virtual_time_s'])
 bench.rb.save(out/'CHECK.json',check);print(json.dumps(check));assert all(check[k] for k in ('full_clear','audit_passed','exact_actions_rng'))
if __name__=='__main__':main()
