"""Passive collector vs original frozen R12: full physical action equality."""
import sys,json,gzip
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from collect import ROOT,SIM,bench,rb
out=ROOT/'results/collector_invariance';source=ROOT/'results/prediction'
m=json.loads((source/'manifest.json').read_bytes())
for r in m['records']:r['file']=str(source/r['file'])
if not(out/'manifest.json').exists():rb.save(out/'manifest.json',m)
results=[]
for index in (0,127,128,383):
    original=source/'core/traces'/f'R12_{index:04d}.json.gz'
    if not original.exists():continue
    rowpath=out/'core/rows'/f'R12_{index:04d}.json'
    row=json.loads(rowpath.read_bytes()) if rowpath.exists() else bench.run_case((str(out),str(SIM),index,'R12',False))
    with gzip.open(original,'rt',encoding='utf-8') as f:a=json.load(f)
    with gzip.open(out/'core/traces'/f'R12_{index:04d}.json.gz','rt',encoding='utf-8') as f:b=json.load(f)
    equal=bench.canonical_actions(a)==bench.canonical_actions(b)
    assert equal and row['audit_passed'] and row['run_status']=='FULL_CLEAR'
    results.append(dict(id=index,physical_actions_equal=equal,actions=len(a['actions'])))
rb.save(ROOT/'COLLECTOR_INVARIANCE.json',dict(complete=len(results)==4,results=results,official_calls=0))
print(results,flush=True)
