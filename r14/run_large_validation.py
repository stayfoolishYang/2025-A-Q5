"""User-requested large independent statistical validation: 1024 x 3 frozen arms."""
import json,hashlib,os,argparse
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor,as_completed
import run_routing as batch
from collect import ROOT,SIM,bench,rb,generate_document
OUT=ROOT/'results/routing_validation1024'
def freeze():
    assert not(OUT/'manifest.json').exists()
    source=json.loads((ROOT/'results/routing_development/manifest.json').read_bytes())
    used=set()
    for base in (Path('J:/2026B_runs'),Path('J:/2026B_experiments')):
        for folder,dirs,files in os.walk(base):
            dirs[:]=[d for d in dirs if d not in ('.git','traces','rows','node_modules','__pycache__')]
            if 'scene' not in Path(folder).name.lower():continue
            for name in files:
                if name.endswith('.json'):
                    raw=json.loads((Path(folder)/name).read_bytes())
                    if 'jammers' in raw:used.add(bench.physical_hash(raw))
    records=[]
    for i in range(1024):
        seed=hashlib.sha256(f'2026B-R14-INDEPENDENT-1024-v1-{i}'.encode()).hexdigest()
        raw=generate_document(seed_hex=seed,problem=4,format='native');h=bench.physical_hash(raw)
        assert h not in used;used.add(h);file=f'scenes/{i:04d}.json';rb.save(OUT/file,raw)
        records.append(dict(id=i,file=file,cohort='independent_validation',family='native_unconditioned',
            seed_hex=seed,physical_hash=h,scene_hash=rb.digest(raw),total=len(raw['jammers'])))
    source.update(records=records,large_harness_hash=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        note='Frozen existing 2000m soft-prior arms; no tuning or correction within this comparison. Future corrected prior is a separate version.')
    rb.save(OUT/'manifest.json',source);print('FROZEN 1024 x 3',flush=True)
def worker(job):
    batch.OUT=OUT
    return batch.worker(job)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['freeze','run']);a=p.parse_args()
    if a.action=='freeze':freeze()
    else:
        jobs=[(i,a) for i in range(1024) for a in batch.ARMS if not(OUT/'routing_events'/f'{a}_{i:04d}.json.gz').exists()]
        with ProcessPoolExecutor(max_workers=8) as pool:
            for i,f in enumerate(as_completed([pool.submit(worker,j) for j in jobs]),1):
                r=f.result()
                if r[2]!='FULL_CLEAR' or not r[3]:print('FAILED_KEEP',r,flush=True)
                if i%24==0:print(i,len(jobs),r,flush=True)
        print('COMPLETE',flush=True)
