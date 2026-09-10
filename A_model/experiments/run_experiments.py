"""Current Q4 validation by default; --legacy explicitly runs the old baseline."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import json
import time
import numpy as np
from scipy.stats import qmc
from solver.fvm_cpu import solve
from physics.material import MODEL_Q1, MODEL_Q23, MODEL_Q4

ROOT=Path(__file__).resolve().parents[1]

def legacy_main():
    path=ROOT/'results'/'experiments.json'
    records=json.loads(path.read_text()) if path.exists() else []
    done={r['name'] for r in records}
    def run(name,**kwargs):
        if name in done: return
        start=time.perf_counter()
        options=dict(n=41,dt=2.,end=432000.,interval=60.,event=True,ale=True,tail='last')
        options.update(kwargs)
        data,meta=solve(**options)
        meta.update(name=name,wall_seconds=time.perf_counter()-start)
        meta['last_T']=data[-1,2:2+meta['n']].tolist()
        meta['last_C']=data[-1,2+meta['n']:].tolist()
        records.append(meta)
        path.write_text(json.dumps(records,indent=2),encoding='utf-8')
        print(name,meta['event_h'],f"{meta['wall_seconds']:.2f}s",flush=True)
    for model,moving,label in ((MODEL_Q23,False,'q3'),(MODEL_Q4,True,'q4')):
        for n in (21,41,81):
            run(f'{label}_grid_{n}',model=model,moving=moving,n=n,dt=1.)
        for dt in (4.,2.,1.,.5):
            run(f'{label}_dt_{dt:g}',model=model,moving=moving,n=81,dt=dt)
        run(f'{label}_bdf2',model=model,moving=moving,n=81,dt=1.,scheme='bdf2')
        run(f'{label}_linear',model=model,moving=moving,interpolation='linear')
        run(f'{label}_tail_mean',model=model,moving=moving,tail='mean')
    for n in (21,41,81):
        run(f'q1_grid_{n}',model=1,n=n,dt=.5,end=1800,interval=1,event=False)
    for omega in (.5,.7,.85,1.):
        run(f'picard_{omega}',model=2,omega=omega,end=1800,interval=2,event=False)
    run('q3_fixed_parameters',model=2,mode=2,end=864000.)
    run('q3_oneway',model=2,mode=1)
    run('q3_q1_properties_240h_censored',model=1,end=864000.,event=False)
    run('q4_fixed_radius',model=MODEL_Q4,moving=False,end=864000.)
    run('q4_material_coordinate',model=MODEL_Q4,moving=True,ale=False)
    for model,moving,label in ((MODEL_Q23,False,'q3'),(MODEL_Q4,True,'q4')):
        for j,param in enumerate(('D','hm','hT','k')):
            for factor in (.8,.9,1.,1.1,1.2):
                scales=np.ones(4); scales[j]=factor
                run(f'{label}_{param}_{factor}',model=model,moving=moving,scales=scales)
    samples=qmc.LatinHypercube(4,seed=2026).random(24)*.4+.8
    np.savetxt(ROOT/'results'/'lhs_samples.csv',samples,delimiter=',',header='D,hm,hT,k',comments='')
    for i,scales in enumerate(samples):
        run(f'lhs_{i:02}',model=2,scales=scales)

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--legacy',action='store_true')
    if parser.parse_args().legacy:legacy_main()
    else:
        from q4_validation import main
        main()
