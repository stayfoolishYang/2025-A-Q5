"""One GPU per independent paired worker. Never connects to official simulator."""
import argparse
import csv
import json
import os
import subprocess
import sys
from pathlib import Path


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--gpus',default='0');p.add_argument('--count',type=int,default=1000)
    p.add_argument('--start',type=int,default=0);p.add_argument('--output',default='B_solver/results/diagnostic/server')
    p.add_argument('--configs',nargs='+',default=['q4_p4_baseline','q4_p4_diag_v1','q4_p4_diag_v2'])
    a=p.parse_args();out=Path(a.output).resolve();out.mkdir(parents=True,exist_ok=True)
    ids=a.gpus.split(',');children=[]
    for i,gpu in enumerate(ids):
        first=a.start+a.count*i//len(ids);end=a.start+a.count*(i+1)//len(ids)
        if first==end:continue
        worker=out/f'worker_{i}';worker.mkdir(exist_ok=True)
        log=(worker/'stdout.log').open('w',encoding='utf-8')
        env=dict(os.environ,CUDA_VISIBLE_DEVICES=gpu,OMP_NUM_THREADS='1',MKL_NUM_THREADS='1')
        cmd=[sys.executable,str(Path(__file__).with_name('paired_q4.py')),'--count',str(end-first),
             '--start',str(first),'--workers','1','--device','cuda','--output',str(worker),'--configs',*a.configs]
        children.append((subprocess.Popen(cmd,env=env,stdout=log,stderr=subprocess.STDOUT),log,worker))
    codes=[]
    for proc,log,_ in children:
        codes.append(proc.wait());log.close()
    if any(codes):raise SystemExit(f'Worker process errors {codes}; retain all partial traces')
    rows=[];manifests=[]
    for _,_,worker in children:
        manifests.append(json.loads((worker/'manifest.json').read_text()))
        with (worker/'cases.csv').open(encoding='utf-8-sig') as f:
            for r in csv.DictReader(f):
                for key in list(r):
                    if key in ('stress','variant','error','config_hash'):continue
                    r[key]=float(r[key]) if key in ('clear_rate','mean_time_per_source','distance','runtime') else int(r[key])
                rows.append(r)
    from paired_q4 import summarize
    if len({(r['seed'],r['variant']) for r in rows}) != a.count*len(a.configs):
        raise RuntimeError('Missing or duplicate paired cases')
    (out/'worker_manifests.json').write_text(json.dumps(manifests,indent=2),encoding='utf-8')
    summarize(rows,out)


if __name__=='__main__':main()
