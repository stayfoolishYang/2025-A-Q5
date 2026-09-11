"""Unified frozen B-problem entry. Default commands are offline only."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parent

def save(p,x):
    p.parent.mkdir(parents=True,exist_ok=True)
    with p.open('x',encoding='utf-8') as f:json.dump(x,f,ensure_ascii=False,indent=2)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    sp=parser.add_subparsers(dest='command',required=True)
    sp.add_parser('verify')
    q1=sp.add_parser('q1');q1.add_argument('--observations',type=Path);q1.add_argument('--arena-radius',type=float)
    q1.add_argument('--output',type=Path,required=True)
    q2=sp.add_parser('q2');q2.add_argument('--output',type=Path,required=True)
    local=sp.add_parser('local');local.add_argument('--problem',type=int,choices=(3,4),required=True)
    local.add_argument('--seed',type=int,choices=range(519),default=0);local.add_argument('--output',type=Path,required=True)
    sp.add_parser('practice')
    a=parser.parse_args()
    if a.command=='verify':
        hashes=json.loads((ROOT/'FILE_HASHES.json').read_bytes())
        for name,h in hashes.items():
            assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==h,name
        print('Verified',len(hashes),'frozen package files; no solver or official interface called.')
        return
    if a.command=='practice':
        if sys.platform!='win32':parser.error('Official practice requires Windows and the official app.')
        # Check other copies before launching; do not stop a running operator's client.
        command="@(Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^python(w)?\\.exe$' -and $_.CommandLine -match 'practice_resident\\.py' }).Count"
        check=subprocess.run(['powershell.exe','-NoProfile','-Command',command],capture_output=True,text=True,check=True)
        if int(check.stdout.strip()):parser.error('A practice resident is already running. Close it normally before using this package.')
        subprocess.run([sys.executable,str(ROOT/'programs/official/practice_resident.py')],check=True)
        return
    out=a.output.resolve()
    if out.exists():parser.error('Output must be new; archived evidence will not be overwritten.')
    if a.command in ('q1','q2'):
        base=ROOT/'q1q2/B_solver';sys.path.insert(0,str(base))
        from questions import solve_q1,q2_example
        import numpy as np
        if a.command=='q1':
            observations=json.loads(a.observations.read_bytes()) if a.observations else json.loads((base/'results/geometry_checks.json').read_bytes())['counterexample']['observations']
            result=solve_q1(observations,arena_radius=a.arena_radius)
            if result['status']=='bounded':
                points=np.asarray(result['polygon']);exact=float(np.linalg.norm(points[:,None]-points[None,:],axis=2).max())
                if abs(exact-result['diameter'])>1e-7:
                    raise RuntimeError('Legacy diameter disagrees with all-pairs cross-check; do not use this result.')
                result['diameter_all_pairs_crosscheck']=True
            save(out,result)
        else:
            out.mkdir(parents=True);result=q2_example(out)
            baseline=json.loads((base/'results/q2.json').read_bytes())
            assert result['candidate_count']==213
            assert np.allclose(result['solutions'][1]['point'],baseline['solutions'][1]['point'],rtol=0,atol=1e-8)
        print(json.dumps(result,ensure_ascii=False));return
    q=a.problem;root=ROOT/'runtime'/('q3_latest_79766ec' if q==3 else 'q4_latest_7228633')
    src=root/'source'/('q3better' if q==3 else 'q4better');sim=ROOT/'runtime/local_engine'
    scene=root/'cpu519/scenes'/f'q{q}_{a.seed:04d}.json'
    if q==3:
        subprocess.run([sys.executable,str(src/'run_q3.py'),'--sim-root',str(sim),'--scene',str(scene),'--output',str(out)],check=True)
    else:
        sys.path[:0]=[str(src),str(sim)]
        import known16_tri25_benchmark as bench
        raw=json.loads(scene.read_bytes());cfg=json.loads((src/'configs/q4_known16_tri25_R12.yaml').read_bytes())
        save(out/'scenes/0000.json',raw)
        save(out/'manifest.json',dict(records=[dict(id=0,file='scenes/0000.json',cohort='handoff_verification',family='canonical519',seed_hex=raw['generator_seed_hex'],scene_hash=bench.rb.digest(raw))],configs=[cfg],source_hashes=bench.fingerprints(sim)))
        row=bench.run_case((out,sim,0,'R12',False))
        assert row['run_status']=='FULL_CLEAR' and row['audit_passed']
        print(json.dumps(row,ensure_ascii=False))

if __name__=='__main__':main()
