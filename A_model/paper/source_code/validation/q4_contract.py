"""Shared fail-closed contract for the current Q4 primary artifacts."""
from pathlib import Path
import json
import numpy as np
ROOT=Path(__file__).resolve().parents[1]

def require_current_q4(meta):
    required={'model':4,'moving':True,'ale':False,'tail':'mean',
              'mode':0,'scales':[1.,1.,1.,1.],
              'balance_quantity':'material_integral_uniform_dry_density'}
    for key,value in required.items():
        if key not in meta or meta[key]!=value:
            raise ValueError(f'Q4 primary model mismatch: {key} must be {value!r}; got {meta.get(key)!r}')

def load_current_q4():
    meta=json.loads((ROOT/'results/q4.json').read_text())
    require_current_q4(meta)
    if abs(meta['event_h']-meta['event_s']/3600)>1e-12:
        raise ValueError('Q4 hours and seconds are inconsistent')
    data=np.load(ROOT/'results/q4.npz')['data'];n=meta['n']
    if data.shape[1]!=2*n+2 or data[-1,0]!=meta['event_s']:
        raise ValueError('Q4 NPZ and metadata do not match')
    if np.max(data[-1,2+n:])!=meta['final_max_C'] or meta['final_max_C']>.15:
        raise ValueError('Q4 endpoint or threshold does not match metadata')
    return data,meta
