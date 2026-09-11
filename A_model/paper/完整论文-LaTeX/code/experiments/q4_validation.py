"""Full Q4 material/mean convergence, interpolation and parameter experiments."""
from pathlib import Path
import sys,json,csv,time,hashlib
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from solver.fvm_cpu import solve
from physics.material import MODEL_Q4
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'results'

def main():
    states=OUT/'q4_validation_states';states.mkdir(exist_ok=True)
    records=[]
    cases=[(f'grid_{n}',dict(n=n,dt=1.)) for n in (41,81,161)]
    cases += [(f'dt_{dt:g}',dict(n=81,dt=dt)) for dt in (4.,2.,.5)]
    cases += [('bdf2',dict(scheme='bdf2',dt=1.)),('linear',dict(interpolation='linear',dt=1.))]
    for j,p in enumerate(('D','hm','hT','k')):
        for f in (.8,.9,1.1,1.2):
            scales=np.ones(4);scales[j]=f
            cases.append((f'{p}_{f:g}',dict(scales=scales,dt=1.)))
    for name,override in cases:
        options=dict(model=MODEL_Q4,moving=True,ale=False,tail='mean',n=81,dt=1.,
                     end=120*3600.,interval=600.,event=True)
        options.update(override);start=time.perf_counter();d,m=solve(**options)
        m.update(name=name,wall_seconds=time.perf_counter()-start,output_interval_s=600.)
        assert m['ale'] is False and m['tail']=='mean' and m['model']==MODEL_Q4
        assert m['max_cumulative_balance_relative']<1e-8
        np.savez_compressed(states/f'{name}.npz',data=d)
        records.append(m)
        (OUT/'q4_validation.json').write_text(json.dumps(records,indent=2),encoding='utf-8')
        print(name,m['event_h'],flush=True)
    by={r['name']:r for r in records};base=by['grid_81']['event_h']
    with (OUT/'q4_sensitivity.csv').open('w',newline='',encoding='utf-8-sig') as f:
        w=csv.writer(f);w.writerow(['parameter','factor','event_h','change_percent','source_case'])
        for p in ('D','hm','hT','k'):
            for factor in (.8,.9,1.,1.1,1.2):
                name='grid_81' if factor==1 else f'{p}_{factor:g}'
                value=by[name]['event_h'];w.writerow([p,factor,value,100*(value/base-1),name])
    with (OUT/'q4_convergence.csv').open('w',newline='',encoding='utf-8-sig') as f:
        fields=['name','n','dt','scheme','interpolation','event_h']
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader()
        for r in records[:8]:w.writerow({k:r[k] for k in fields})
    main_meta=json.loads((OUT/'q4.json').read_text())
    assert by['dt_0.5']['event_s']==main_meta['event_s']
    proof=dict(model=MODEL_Q4,ale=False,tail='mean',full_trajectories=len(records),
        primary_event_match=True,baseline_for_sensitivity='grid_81 (N=81, BE dt=1s)',
        code_sha256={p:hashlib.sha256((ROOT/p).read_bytes().replace(b'\r\n',b'\n')).hexdigest() for p in
        ['physics/material.py','physics/boundary.py','solver/fvm_cpu.py','experiments/q4_validation.py']})
    (OUT/'q4_validation_provenance.json').write_text(json.dumps(proof,indent=2),encoding='utf-8')

if __name__=='__main__':main()
