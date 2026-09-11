"""Run frozen Q4 R12 and the prior C config on all 519 existing scenes, CPU only."""
import os
os.environ.update(OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='1')
import csv,hashlib,json,shutil,sys,time
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor,as_completed
import numpy as np
ROOT=Path('J:/2026B_runs/q4_latest_7228633')
SRC=ROOT/'source/q4better'
SIM=Path('G:/QQ/jammers_linux')
OLD=Path('J:/2026B_runs/better_full519_20260911')
OUT=ROOT/'cpu519'
sys.path[:0]=[str(SRC),str(SIM)]
import known16_tri25_benchmark as bench
import recovered_benchmark as rb

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(p,x):p.write_text(json.dumps(x,ensure_ascii=False,indent=2),encoding='utf-8')
def worker(job):return bench.run_case((str(OUT),str(SIM),job[0],job[1],False))
def report():
    rows=[json.loads(p.read_bytes()) for p in sorted((OUT/'core/rows').glob('*.json'))]
    assert len(rows)==1038
    fields=sorted(set().union(*(r.keys() for r in rows)))
    with (OUT/'cases.csv').open('w',newline='',encoding='utf-8-sig') as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)
    groups={v:{r['id']:r for r in rows if r['variant']==v} for v in ('C','R12')}
    summary=dict(commit='7228633906262bb035f4ea1d859792e9f4484d20',planned=1038,completed=len(rows),official_calls=0,variants={},pairs={})
    for v,g in groups.items():
        good=[r for r in g.values() if r['run_status']=='FULL_CLEAR' and r['audit_passed']]
        x=np.array([r['mean_time_per_source'] for r in good])
        summary['variants'][v]=dict(runs=len(g),full_clear=sum(r['run_status']=='FULL_CLEAR' for r in g.values()),audited=len(good),
            mean=float(x.mean()) if len(x) else None,median=float(np.median(x)) if len(x) else None,p95=float(np.quantile(x,.95)) if len(x) else None,
            p99=float(np.quantile(x,.99)) if len(x) else None,maximum=float(x.max()) if len(x) else None,
            fallbacks=sum(r['fallback_count'] for r in good),known16_triggers=sum(r['known16_reached'] and r['known16_enabled'] for r in good),
            stage_mean_s={s:float(np.mean([r['stage_'+s+'_s'] for r in good])) for s in rb.STAGES})
    pairs=[]
    ids=[i for i in range(519) if all(groups[v][i]['run_status']=='FULL_CLEAR' and groups[v][i]['audit_passed'] for v in groups)]
    for i in ids:
        a,b=groups['C'][i],groups['R12'][i]
        pairs.append(dict(seed=i,total=a['total'],C_s_per_source=a['mean_time_per_source'],R12_s_per_source=b['mean_time_per_source'],
            delta_s_per_source=b['mean_time_per_source']-a['mean_time_per_source'],delta_distance_m=b['distance']-a['distance']))
    with (OUT/'pairs.csv').open('w',newline='',encoding='utf-8-sig') as f:
        w=csv.DictWriter(f,fieldnames=['seed','total','C_s_per_source','R12_s_per_source','delta_s_per_source','delta_distance_m']);w.writeheader();w.writerows(pairs)
    for label,pp in [('all',pairs),('N10_15',[r for r in pairs if r['total']<16]),('N16',[r for r in pairs if r['total']==16])]:
        d=np.array([r['delta_s_per_source'] for r in pp])
        summary['pairs'][label]=dict(n=len(pp),mean_delta=float(d.mean()) if len(d) else None,wins=int(sum(d<-1e-8)),ties=int(sum(abs(d)<=1e-8)),losses=int(sum(d>1e-8)),
            max_regression=float(d.max()) if len(d) else None,worst_seed=pp[int(d.argmax())]['seed'] if len(d) else None)
    mismatches=[]
    for i,r in groups['C'].items():
        old=json.loads((OLD/'runs'/f'q4_{i:04d}_C.json').read_bytes())
        if r['run_status']!='FULL_CLEAR' or abs(r['virtual_time_s']-old['virtual_time_s'])>1e-6:mismatches.append(i)
    summary['previous_C_time_mismatches']=mismatches
    save(OUT/'SUMMARY.json',summary)
    md='# Q4最新R12：519种子完整CPU复测\n\n提交 `7228633906262bb035f4ea1d859792e9f4484d20`。C与R12各519场，共1038场；8进程CPU，仅本地Engine，官方接口调用0。C使用上一轮37点配置；R12严格采用仓库发布配置（25点覆盖、已发现满16源结束盲扫、清满16源退出）。\n\n|方案|全清/已审计|平均秒/源|中位数|P95|P99|最大值|兜底次数|\n|---|---|---:|---:|---:|---:|---:|---:|\n'
    for v,r in summary['variants'].items():md+=f'|{v}|{r["full_clear"]}/519；审计{r["audited"]}|{r["mean"]:.3f}|{r["median"]:.3f}|{r["p95"]:.3f}|{r["p99"]:.3f}|{r["maximum"]:.3f}|{r["fallbacks"]}|\n'
    md+='\n|配对层|数量|平均差秒/源|胜/平/负|最大退步|最差seed|\n|---|---:|---:|---|---:|---:|\n'
    for v,r in summary['pairs'].items():md+=f'|{v}|{r["n"]}|{r["mean_delta"]:+.3f}|{r["wins"]}/{r["ties"]}/{r["losses"]}|{r["max_regression"]:+.3f}|{r["worst_seed"]}|\n'
    md+=f'\nC与上一轮C总时间不一致案例：{mismatches}。负差表示R12更快。结果按同场景配对；不是与仓库另一批256场均值比较。\n\n复用仓库known16_tri25_benchmark审计：动作/RNG记录、整数微秒计时、频道与发现节点扫描、停止条件、硬可行集合保守性、全清及剩余tracks核对。真实源只供离线审计，不输入策略决策。未修改源码与配置；源、引擎、场景哈希在前后核对。\n\n这是既有519种子回归集，不是新独立留出集或官方成绩。R12组合了25点与known16改变，不能仅凭此对照分别归因。原始逐场结果与压缩轨迹见core/rows和core/traces；阶段平均耗时见SUMMARY.json。\n'
    (OUT/'REPORT.md').write_text(md,encoding='utf-8')
    print(json.dumps(summary),flush=True)

def main():
    assert (ROOT/'source/SOURCE.json').exists()
    OUT.mkdir(exist_ok=False)
    (OUT/'scenes').mkdir();(OUT/'core/rows').mkdir(parents=True)
    old=json.loads((OLD/'PLAN.json').read_bytes())
    for p,h in old['hashes'].items():
        if Path(p).parent==SIM:assert sha(Path(p))==h,p
    configs=[json.loads((OLD/'configs/q4_C.json').read_bytes()),json.loads((SRC/'configs/q4_known16_tri25_R12.yaml').read_bytes())]
    records=[]
    for r in old['seeds']:
        i=r['seed'];name=f'scenes/q4_{i:04d}.json';shutil.copy2(OLD/name,OUT/name)
        raw=json.loads((OUT/name).read_bytes());records.append(dict(id=i,cohort='canonical519_regression',family=r['family'],seed_hex=r['seed_hex'],file=name,scene_hash=rb.digest(raw)))
    fingerprints=bench.fingerprints(SIM)
    save(OUT/'manifest.json',dict(commit='7228633906262bb035f4ea1d859792e9f4484d20',configs=configs,records=records,source_hashes=fingerprints,workers=8,device='cpu',planned=1038,official_calls=0,python=sys.version,numpy=np.__version__))
    paths=list(SRC.rglob('*.py'))+list(SRC.glob('configs/*'))+list(SIM.glob('*.py'))+list((OUT/'scenes').glob('*.json'))+[Path(__file__)]
    hashes={str(p):sha(p) for p in paths if p.is_file()};save(OUT/'HASHES.json',hashes)
    with ProcessPoolExecutor(max_workers=8) as pool:
        fs=[pool.submit(worker,(i,v)) for i in range(519) for v in ('C','R12')]
        for n,f in enumerate(as_completed(fs),1):
            r=f.result()
            if n%25==0 or r['run_status']!='FULL_CLEAR' or not r['audit_passed']:print(n,'/1038',r['id'],r['variant'],r['run_status'],'audit',r['audit_passed'],flush=True)
    assert bench.fingerprints(SIM)==fingerprints
    assert all(sha(Path(p))==h for p,h in hashes.items())
    report()
if __name__=='__main__':main()
