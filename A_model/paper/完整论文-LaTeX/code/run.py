"""Full calculation. Run from any directory: python A_model/run.py."""
from pathlib import Path
import argparse
import json
import time
import numpy as np
from solver.fvm_cpu import solve
from physics.material import MODEL_Q1, MODEL_Q23, MODEL_Q4

ROOT = Path(__file__).resolve().parent

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--n',type=int,default=81)
    parser.add_argument('--dt',type=float,default=.5)
    parser.add_argument('--questions', type=int, nargs='+', choices=range(1,5), default=[1,2,3,4])
    args=parser.parse_args()
    outdir=ROOT/'results'; outdir.mkdir(exist_ok=True)
    for q in args.questions:
        start=time.perf_counter()
        out,meta=solve(model=MODEL_Q1 if q==1 else MODEL_Q4 if q==4 else MODEL_Q23, moving=q==4,n=args.n,dt=args.dt,
                       end=1800 if q==1 else 10800 if q==2 else 432000,interval=1 if q<=2 else 60,event=q>=3,
                       ale=q!=4, tail='mean' if q==4 else 'last')
        meta['wall_seconds']=time.perf_counter()-start
        np.savez_compressed(outdir/f'q{q}.npz',data=out)
        (outdir/f'q{q}.json').write_text(json.dumps(meta,indent=2),encoding='utf-8')
        print(f'Q{q} '+json.dumps(meta),flush=True)

if __name__=='__main__': main()
