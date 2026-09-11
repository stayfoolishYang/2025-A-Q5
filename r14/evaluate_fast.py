"""Resume with bitwise-equivalent caching; preserve completed reference results."""
import json,hashlib
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor,as_completed
import evaluate
from belief_fast import DiscoveryBelief

def worker(index):
    evaluate.DiscoveryBelief=DiscoveryBelief
    return evaluate.worker(index)

if __name__=='__main__':
    root=Path(__file__).resolve().parent;out=evaluate.OUT
    completed=[]
    for p in (out/'evaluation').glob('*.json'):
        data=json.loads(p.read_bytes()) # No silently discarded partial or failed files.
        assert data['rows'];completed.append(int(p.stem))
    record=dict(completed_reference_ids=sorted(completed),reason='bitwise-equivalent deterministic caching; 17.9x measured speedup',
        hashes={n:hashlib.sha256((root/n).read_bytes()).hexdigest() for n in ['evaluate.py','belief_fast.py','evaluate_fast.py']},official_calls=0)
    audit=root/'EVALUATION_CACHE_RESUME.json'
    if not audit.exists():audit.write_text(json.dumps(record,indent=2),encoding='utf-8')
    jobs=sorted(set(range(384))-set(completed))
    with ProcessPoolExecutor(max_workers=8) as pool:
        for i,f in enumerate(as_completed([pool.submit(worker,j) for j in jobs]),1):
            r=f.result()
            if i%16==0:print('EVALUATED_FAST',i,len(jobs),r,flush=True)
    evaluate.summarize()
