"""Q4 material/mean release and matched full-trajectory comparisons."""
from pathlib import Path
import sys,json,csv,time
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from solver.fvm_cpu import solve
from physics.boundary import Boundary

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'results'

def main():
    folder=OUT/'q4_scenarios';folder.mkdir(exist_ok=True)
    cases=[('material_mean',{}),('material_last',{'tail':'last'}),
           ('material_nominal',{'tail':'nominal'}),('fixed_mean',{'moving':False}),
           ('eulerian_mean',{'ale':True}),('material_mean_dt1',{'dt':1.}),
           ('material_mean_grid41',{'n':41})]
    records=[]
    for name,overrides in cases:
        options=dict(model=4,moving=True,ale=False,tail='mean',n=81,dt=.5,
                     end=180*3600.,interval=60.,event=True)
        options.update(overrides)
        start=time.perf_counter(); data,meta=solve(**options)
        meta.update(name=name,wall_seconds=time.perf_counter()-start,
                    boundary_plateau=Boundary(tail=options['tail']).tail.tolist())
        np.savez_compressed(folder/f'{name}.npz',data=data)
        (folder/f'{name}.json').write_text(json.dumps(meta,indent=2),encoding='utf-8')
        if name=='material_mean':
            np.savez_compressed(OUT/'q4.npz',data=data)
            (OUT/'q4.json').write_text(json.dumps(meta,indent=2),encoding='utf-8')
        records.append(meta)
        print(name,meta['event_h'],flush=True)
    (OUT/'q4_release_experiments.json').write_text(json.dumps(records,indent=2),encoding='utf-8')
    fields=['name','event_h','moving','ale','tail','n','dt','max_cumulative_balance_relative']
    with (OUT/'q4_ablation.csv').open('w',newline='',encoding='utf-8-sig') as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader()
        for r in records:w.writerow({k:r[k] for k in fields})

if __name__=='__main__':main()
