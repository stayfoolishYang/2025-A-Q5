"""Freeze historical519 regression only; never used for development selection."""
from run_study import *
import shutil
out=ROOT/'results/regression';assert not (out/'manifest.json').exists()
archive=Path('J:/2026B_runs/q4_latest_7228633/cpu519_repeat_20260912');old=json.loads((archive/'manifest.json').read_bytes())
cfg=json.loads((SRC/'configs/q4_known16_tri25_R12.yaml').read_bytes());records=[]
for i,r in enumerate(old['records']):
    raw=json.loads((archive/r['file']).read_bytes());file=f'scenes/{i:04d}.json';save(out/file,raw)
    records.append(dict(id=i,previous_id=i,cohort='regression',family=r.get('family','historical519'),file=file,scene_hash=rb.digest(raw),physical_hash=bench.physical_hash(raw),total=len(raw['jammers'])))
m=dict(records=records,configs=[dict(cfg,name=a,study_modules=[] if a=='R12' else [a]) for a in ['R12','A1','D']],source_hashes=bench.fingerprints(SIM),research_hashes=hashes(),official_calls=0,formal_test_count=0,execution_backend='direct_local_engine',cohort='regression',workers=8,role='regression only; D retained for known16 mechanism audit, not selection')
save(out/'manifest.json',m);save(ROOT/'REGRESSION_MANIFEST.json',m)
print('Frozen historical519 x3',flush=True)
