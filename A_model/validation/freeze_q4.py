"""Write a release manifest once, or verify it without modifying frozen files."""
from pathlib import Path
import argparse,hashlib,json
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
MANIFEST=ROOT/'results/q4_freeze_manifest.json'

def digest(path):
    blob=path.read_bytes()
    mode='raw' if path.suffix in ('.npz','.xlsx','.png') else 'LF-normalized'
    if mode=='LF-normalized':blob=blob.replace(b'\r\n',b'\n')
    return dict(sha256=hashlib.sha256(blob).hexdigest(),mode=mode)

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--write',action='store_true');args=parser.parse_args()
    meta=json.loads((ROOT/'results/q4.json').read_text());d=np.load(ROOT/'results/q4.npz')['data']
    assert meta['ale'] is False and meta['moving'] is True and meta['tail']=='mean'
    assert meta['n']==81 and meta['dt']==.5 and meta['model']==4
    assert meta['balance_quantity']=='material_integral_uniform_dry_density'
    assert meta['max_cumulative_balance_relative']<1e-8
    assert d[-1,0]==meta['event_s'] and np.max(d[-1,83:])<.15
    assert np.array_equal(d,np.load(ROOT/'results/q4_scenarios/material_mean.npz')['data'])
    for name in ('material_last','material_nominal'):
        other=np.load(ROOT/f'results/q4_scenarios/{name}.npz')['data']
        assert np.array_equal(d[d[:,0]<=14400],other[other[:,0]<=14400])
    if args.write:
        paths=['run.py','report.py','Q4_FREEZE.md','STATUS.md','README.md','physics/material.py',
            'physics/boundary.py','solver/fvm_cpu.py','experiments/q4_release.py','export/prepare_outputs.py',
            'export/workbooks.mjs','validation/validate_exports.py','validation/freeze_q4.py',
            'data/boundary.csv','data/radius.csv','data/manifest.json','data/templates/result4.xlsx',
            'results/q4.npz','results/q4.json','results/result4.xlsx','results/table6.csv',
            'results/q4_radius_output.csv','results/q4_ablation.csv','results/q4_release_experiments.json',
            'results/export_validation.json','results/求解报告.md','results/index.html']
        paths += [p.relative_to(ROOT).as_posix() for p in sorted((ROOT/'results/q4_scenarios').glob('*')) if p.is_file()]
        paths += [f'results/figures/{name}.{ext}' for name in ('q4_drying','q4_scenarios','q4_boundary','ablation') for ext in ('png','svg')]
        obj=dict(version='q4-material-mean-v1',date='2026-09-10',event_h=meta['event_h'],
            assumptions='Uniform material shrinkage; mean tail; appendix rho is effective thermal density',
            files={p:digest(ROOT/p) for p in paths})
        MANIFEST.write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding='utf-8')
    obj=json.loads(MANIFEST.read_text(encoding='utf-8'))
    for p,expected in obj['files'].items():assert digest(ROOT/p)==expected,p
    print(json.dumps(dict(version=obj['version'],files_verified=len(obj['files']),
        event_h=meta['event_h'],scenario_prefix_identity=True,status='passed'),indent=2))

if __name__=='__main__':main()
