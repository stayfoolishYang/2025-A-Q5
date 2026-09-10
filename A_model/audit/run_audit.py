"""Full threshold trajectories, identical Q4 properties; run from A_model."""
import csv
import hashlib
import json
from pathlib import Path
import sys
import time
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from solver.fvm_cpu import solve, geometry
from physics.boundary import Boundary

DEST = Path(__file__).resolve().parent

def main():
    cases = [
        ('fixed', False, False, 'last', .5),
        ('fixed_ale', False, True, 'last', .5),
        ('moving_material', True, False, 'last', .5),
        ('moving_eulerian', True, True, 'last', .5),
        ('moving_material_dt1', True, False, 'last', 1.),
        ('moving_material_mean', True, False, 'mean', .5),
        ('moving_material_nominal', True, False, 'nominal', .5),
    ]
    results = {}
    _, weights = geometry(81)
    for name, moving, ale, tail, dt in cases:
        start = time.perf_counter()
        data, meta = solve(model=3, moving=moving, ale=ale, tail=tail,
                           n=81, dt=dt, interval=60., end=180*3600.)
        meta['wall_seconds'] = time.perf_counter()-start
        C = data[:, 83:]
        # Conditional diagnostic ONLY: appendix rho interpreted as total wet density.
        dry_ratio = (data[:, 1]/.02)**2 * ((760+90*C)/(1+C) @ weights)/((760+90*2.55)/3.55*.5)
        avg = 2*(C @ weights)
        meta.update(empirical_dry_mass_ratio_min=float(dry_ratio.min()),
                    empirical_dry_mass_ratio_final=float(dry_ratio[-1]),
                    empirical_dry_mass_min_time_h=float(data[dry_ratio.argmin(),0]/3600),
                    final_mean_C=float(avg[-1]))
        # Independently integrate the MATERIAL surface-loss law over saved samples.
        # Trapezoidal output quadrature (60s), not the internal discrete residual.
        ambient = Boundary(tail=tail).ambient(data[:,0])
        flux = -2*8e-7/data[:,1]*(C[:,-1]-ambient[:,1])
        cumulative = np.r_[0.,np.cumsum(.5*(flux[1:]+flux[:-1])*np.diff(data[:,0]))]
        mismatch = (avg-2.55-cumulative)/2.55
        meta['material_water_budget_trapezoid60s_final_relative'] = float(mismatch[-1])
        meta['material_water_budget_trapezoid60s_max_relative'] = float(np.max(np.abs(mismatch)))
        np.savez_compressed(DEST/(name+'.npz'), data=data)
        np.savetxt(DEST/(name+'_budget.csv'), np.column_stack((data[:,0],data[:,1],avg,dry_ratio,mismatch)),
                   delimiter=',', header='time_s,radius_m,mean_dry_basis_C,conditional_dry_mass_ratio,material_water_budget_relative',comments='')
        results[name] = meta
        (DEST/'results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
        print(name, meta['event_h'], 'h', meta['wall_seconds'], 's',flush=True)
    a=np.load(DEST/'fixed.npz')['data']; b=np.load(DEST/'fixed_ale.npz')['data']
    identity=float(np.max(np.abs(a-b))) if a.shape == b.shape else None
    assert identity == 0., 'Fixed-radius ALE toggle must have identical trajectories'
    assert results['moving_material']['max_cumulative_balance_relative'] < 1e-6
    (DEST/'verification.json').write_text(json.dumps(dict(fixed_toggle_full_trajectory_max_difference=identity,
        source_sha256={p:hashlib.sha256((DEST.parent/p).read_bytes()).hexdigest() for p in
        ['solver/fvm_cpu.py','physics/material.py','physics/boundary.py','data/boundary.csv','data/radius.csv']}),indent=2),encoding='utf-8')
    with (DEST/'summary.csv').open('w',newline='',encoding='utf-8-sig') as f:
        fields=['case','event_h','n','dt','ale','moving','tail','max_cumulative_balance_relative',
                'empirical_dry_mass_ratio_min','empirical_dry_mass_ratio_final','material_water_budget_trapezoid60s_final_relative']
        writer=csv.DictWriter(f,fieldnames=fields); writer.writeheader()
        for name,m in results.items(): writer.writerow({'case':name,**{k:m[k] for k in fields[1:]}})

if __name__ == '__main__': main()
