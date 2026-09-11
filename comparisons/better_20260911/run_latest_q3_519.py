"""Frozen GitHub Q3 revision D versus A on all existing 519 CPU scenes."""
import os
os.environ.update(OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='1')
import csv,gzip,hashlib,json,shutil,sys,time
from concurrent.futures import ProcessPoolExecutor,as_completed
from pathlib import Path
import numpy as np

ROOT=Path('J:/2026B_runs/q3_latest_79766ec')
SRC=ROOT/'source/q3better'
OLD=Path('J:/2026B_runs/better_full519_20260911')
SIM=Path('G:/QQ/jammers_linux')
OUT=ROOT/'cpu519'
sys.path[:0]=[str(SRC),str(SRC/'B_solver'),str(SRC/'B_solver/experiments'),str(SIM)]
from active_failure import ActiveFailureSolver
from phase_audit import TaggedSolver
from q3_stop16_pilot import CONFIG,audit
from recovered_benchmark import EngineAdapter
from engine import Engine
from scenario_io import load_scenario

def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(p,x):p.write_text(json.dumps(x,ensure_ascii=False,indent=2),encoding='utf-8')
def worker(job):
    seed,v=job;raw=json.loads((OUT/'scenes'/f'q3_{seed:04d}.json').read_bytes())
    engine=Engine(load_scenario(raw));api=EngineAdapter(engine)
    cfg=dict(CONFIG,local_order=v=='D');cls=ActiveFailureSolver if v=='D' else TaggedSolver
    s=cls(api,False,'P3',device='cpu',diagnostic=cfg)
    if v=='D':s.discovery_route='refresh_after_localize'
    start=time.perf_counter()
    try:
        r=s.run();nodes=audit(api.log,False)
        assert not s.tracks and engine.cleared=={j.channel for j in engine.scenario.jammers}
        r.update(status='FULL_CLEAR',audit=True,discovery_nodes=nodes)
    except Exception as ex:r=dict(status='FAILED',audit=False,error=repr(ex))
    r.update(problem=3,seed=seed,variant=v,total=len(raw['jammers']),wall_s=time.perf_counter()-start,
             distance_m=api.distance,measures=api.measures,clear_attempts=api.clear_attempts,
             stages=api.stages,execution_backend='LOCAL_DEV',device='cpu')
    dest=OUT/'runs'/f'q3_{seed:04d}_{v}.json'
    with gzip.open(dest.with_suffix('.json.gz'),'wt',encoding='utf-8') as f:json.dump(api.log,f)
    save(dest,r)
    return r

def report():
    rows=[json.loads(p.read_bytes()) for p in sorted((OUT/'runs').glob('*.json'))]
    assert len(rows)==1038
    with (OUT/'cases.csv').open('w',newline='',encoding='utf-8-sig') as f:
        fields=sorted(set().union(*(r.keys() for r in rows)) - {'stages'})
        w=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore');w.writeheader();w.writerows(rows)
    groups={v:{r['seed']:r for r in rows if r['variant']==v} for v in 'AD'}
    groups['previous_B']={i:json.loads((OLD/'runs'/f'q3_{i:04d}_B.json').read_bytes()) for i in range(519)}
    summary=dict(commit='79766ecf0d2577289f814edba310327f55424111',planned=1038,completed=len(rows),official_calls=0,variants={},pairs={})
    for v,g in groups.items():
        good=[r for r in g.values() if r['status']=='FULL_CLEAR'];x=np.array([r['mean_time_per_source_s'] for r in good])
        summary['variants'][v]=dict(runs=len(g),full_clear=len(good),mean=float(x.mean()),median=float(np.median(x)),p95=float(np.quantile(x,.95)),maximum=float(x.max()),fallbacks=sum(r['optical_fallbacks'] for r in good))
    pairs=[]
    for ref in ('A','previous_B'):
        ids=sorted(i for i in groups['D'] if groups['D'][i]['status']==groups[ref][i]['status']=='FULL_CLEAR')
        ds=np.array([groups['D'][i]['mean_time_per_source_s']-groups[ref][i]['mean_time_per_source_s'] for i in ids])
        summary['pairs']['D-'+ref]=dict(n=len(ids),mean_delta=float(ds.mean()),median_delta=float(np.median(ds)),wins=int(sum(ds<-1e-8)),ties=int(sum(abs(ds)<=1e-8)),losses=int(sum(ds>1e-8)),max_regression=float(ds.max()),worst_seed=ids[int(ds.argmax())])
        pairs.extend(dict(seed=i,reference=ref,delta_s_per_source=float(d)) for i,d in zip(ids,ds))
    with (OUT/'pairs.csv').open('w',newline='',encoding='utf-8-sig') as f:
        w=csv.DictWriter(f,fieldnames=list(pairs[0]));w.writeheader();w.writerows(pairs)
    differences=[]
    for i,r in groups['A'].items():
        old=json.loads((OLD/'runs'/f'q3_{i:04d}_A.json').read_bytes())
        if r['status']!='FULL_CLEAR' or abs(r['virtual_time_s']-old['virtual_time_s'])>1e-6:differences.append(i)
    summary['baseline_previous_time_mismatches']=differences
    save(OUT/'SUMMARY.json',summary)
    md='# 最新Q3 D版完整CPU 519种子复测\n\n提交 `79766ecf0d2577289f814edba310327f55424111`。A、D各519场，8个CPU进程；复用原场景逐字节副本，未接官方接口。D严格采用仓库默认构造，MEC、七点和停止条件保持源码原样。\n\n|方案|全清|均值秒/源|中位数|P95|最大值|兜底总次数|\n|---|---:|---:|---:|---:|---:|---:|\n'
    for v,r in summary['variants'].items():md+=f'|{v}|{r["full_clear"]}/519|{r["mean"]:.3f}|{r["median"]:.3f}|{r["p95"]:.3f}|{r["maximum"]:.3f}|{r["fallbacks"]}|\n'
    md+='\n|配对|数量|均值变化秒/源|胜/平/负|最大退步|最差seed|\n|---|---:|---:|---|---:|---:|\n'
    for v,r in summary['pairs'].items():md+=f'|{v}|{r["n"]}|{r["mean_delta"]:+.3f}|{r["wins"]}/{r["ties"]}/{r["losses"]}|{r["max_regression"]:+.3f}|{r["worst_seed"]}|\n'
    md+=f'\nA与上一轮A总时间不一致案例：{differences}。负差表示D更快。previous_B取自上一轮已保存完整运行，不重复冒称新实验。\n\n每场审核全清、七点扫描义务、频道次序、动作接受状态、整数微秒计时和正常退出。保留失败行与全部动作日志。固定519种子是既有回归集，不是新的独立留出集，也不是官方成绩；比较D与A涉及三个组合改动，不能单独归因给失败计数修复。\n'
    (OUT/'REPORT.md').write_text(md,encoding='utf-8')
    print(json.dumps(summary),flush=True)

def main():
    assert (ROOT/'source/SOURCE.json').exists(),'Source retrieval must finish first'
    OUT.mkdir(exist_ok=False)
    for d in ('runs','scenes'):(OUT/d).mkdir()
    oldplan=json.loads((OLD/'PLAN.json').read_bytes())
    for p,h in oldplan['hashes'].items():
        if Path(p).parent==SIM:assert digest(Path(p))==h, p
    for i in range(519):shutil.copy2(OLD/'scenes'/f'q3_{i:04d}.json',OUT/'scenes'/f'q3_{i:04d}.json')
    paths=list(SRC.rglob('*.py'))+list(SIM.glob('*.py'))+list((OUT/'scenes').glob('*.json'))+[Path(__file__)]
    hashes={str(p):digest(p) for p in paths}
    save(OUT/'PLAN.json',dict(commit='79766ecf0d2577289f814edba310327f55424111',seeds=oldplan['seeds'],hashes=hashes,workers=8,planned=1038,device='cpu',official_calls=0,configs={v:dict(CONFIG,local_order=v=='D') for v in 'AD'},candidate_route='refresh_after_localize'))
    with ProcessPoolExecutor(max_workers=8) as pool:
        futures=[pool.submit(worker,(i,v)) for i in range(519) for v in 'AD']
        for n,f in enumerate(as_completed(futures),1):
            r=f.result()
            if n%25==0 or r['status']!='FULL_CLEAR':print(n,'/1038',r['seed'],r['variant'],r['status'],flush=True)
    assert all(digest(Path(p))==h for p,h in hashes.items())
    report()
if __name__=='__main__':main()
