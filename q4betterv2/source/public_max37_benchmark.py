"""Three frozen Q4 variants on the explicitly supplied offline engine only."""
import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import csv
from datetime import datetime, timezone
import gzip
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time
import zipfile
import numpy as np
import recovered_benchmark as rb

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE/'reporting'))
from discovery_report import audit_trace, quantiles


def fingerprints(sim):
    hashes = rb.source_hashes(sim)
    for p in [Path(__file__), BASE/'reporting/discovery_report.py', BASE/'check_coverage37.py']:
        hashes['solver/'+p.relative_to(BASE).as_posix()] = hashlib.sha256(p.read_bytes()).hexdigest()
    for name in ('protocol.py','server.py','client.py','start.py','store.py','access.py'):
        hashes['engine/'+name] = hashlib.sha256((sim/name).read_bytes()).hexdigest()
    return hashes


def freeze(out, sim):
    from scenario_io import generate_document, load_scenario
    if (out/'manifest.json').exists(): raise FileExistsError('Manifest already frozen')
    cfg = json.loads((BASE/'configs/q4_p4_diag_v1_grid_v1_refresh.yaml').read_bytes())
    configs = [dict(cfg,name=v,stop_after_public_max_clear=v!='A',
                    discovery_coverage='certified37' if v=='C' else 'legacy45') for v in 'ABC']
    for c in configs: rb.save(BASE/f'configs/q4_public_max37_{c["name"]}.yaml',c)
    records = []
    for i in range(160):
        seed = hashlib.sha256(f'2026B-public-max37-20260911-v1:{i}'.encode()).hexdigest()
        raw = generate_document(seed_hex=seed,problem=4,format='native')
        records.append(dict(id=i,cohort='development' if i<32 else 'evaluation',family='practice-gen-v1',
                            seed_hex=seed,scene=raw))
    # Sixteen legal 16-source pressure cases selected before any Solver result.
    index=0
    while len(records)<176:
        seed=hashlib.sha256(f'2026B-public-max37-stress16-v1:{index}'.encode()).hexdigest(); index+=1
        raw=generate_document(seed_hex=seed,problem=4,format='native')
        if len(raw['jammers'])==16:
            records.append(dict(id=len(records),cohort='stress',family='generated_16',seed_hex=seed,scene=raw))
    # Custom pressures retain the same engine and noise field. Separate from representative averages.
    for n,family in ((10,'boundary_outward_r1000'),(15,'near_nodes_r1000'),(16,'cluster_omni'),(16,'all_directional_boundary')):
        seed=hashlib.sha256(f'2026B-public-max37-custom:{family}'.encode()).hexdigest()
        raw=generate_document(seed_hex=seed,problem=4,format='native')
        raw=dict(format='jammers-offline-v1',problem=4,noise_seed_hex=raw['noise_seed_hex'],
                 generator_seed='custom-pressure:'+family,jammers=[])
        for i in range(n):
            angle=2*math.pi*i/n
            x,y=1799.999*math.cos(angle),1799.999*math.sin(angle)
            if family=='near_nodes_r1000':
                x,y=[(a,b) for a in (-700,0,700) for b in (-1400,-700,0,700,1400)][i]; x+=.01
            if family=='cluster_omni': x,y=300+i*.1,300+i*.1
            omni=family=='cluster_omni'
            raw['jammers'].append(dict(channel=i+1,x=round(x,6),y=round(y,6),
                 receive_radius_m=1000.,kind='omni' if omni else 'directional',
                 direction_deg=0. if omni else math.degrees(angle)%360))
        load_scenario(raw)
        records.append(dict(id=len(records),cohort='stress',family=family,seed_hex=seed,scene=raw))
    old={r['seed_hex'] for r in rb.frozen_seeds()}
    # Known historical derivations read from prepare scripts; unavailable historical raw lists stay explicit.
    history_files=[]
    for path in (BASE/'experiments').glob('prepare_*.py'):
        text=path.read_text(encoding='utf-8'); history_files.append(path.name)
        import re
        for prefix in re.findall(r"prefix\s*=\s*['\"]([^'\"]+)['\"]",text):
            old.update(hashlib.sha256((prefix+str(i)).encode()).hexdigest() for i in range(1024))
    assert not old.intersection(r['seed_hex'] for r in records)
    manifest=dict(baseline=subprocess.check_output(['git','rev-parse','HEAD'],cwd=BASE,text=True).strip(),
        frozen_at=datetime.now(timezone.utc).isoformat(),configs=configs,source_hashes=fingerprints(sim),
        simulator_root=str(sim),python=sys.version,executable=sys.executable,numpy=np.__version__,
        execution_backend='LOCAL_DEV',execution_purpose='FRAMEWORK_INTEGRATION',production_eligible=False,
        seed_design='Deterministic practice-gen-v1 design; not official IID samples',
        historical_overlap=0,historical_check_scope=dict(known_seed_count=len(old),scripts=history_files,
            limitation='Unavailable J: original lists and unarchived historical scenarios not exhaustively checked'),
        adoption_B='Correct feedback/prefix; N10-15 unchanged; full clearance and time nonregression per case',
        adoption_C='Continuous proof and engine boundaries; no new failures/timeouts; evaluation mean T/N at least 1% lower than B; P95/P99 nonincreasing',
        records=[])
    for r in records:
        raw=r.pop('scene'); filename=f'scenes/{r["id"]:04d}.json'
        rb.save(out/filename,raw)
        manifest['records'].append(dict(r,file=filename,scene_hash=rb.digest(raw),total=len(raw['jammers'])))
    rb.save(out/'manifest.json',manifest)
    with zipfile.ZipFile(out/'frozen_source.zip','x',compression=zipfile.ZIP_DEFLATED) as z:
        for name,h in manifest['source_hashes'].items():
            prefix,rel=name.split('/',1); data=((BASE if prefix=='solver' else sim)/rel).read_bytes()
            assert hashlib.sha256(data).hexdigest()==h; z.writestr(name,data)
        z.writestr('manifest.json',(out/'manifest.json').read_bytes())
    print('Frozen 32 development + 128 evaluation + 20 pressure scenarios; 540 planned core runs.',flush=True)


def run_case(job):
    out,sim,index,variant,http_url=job
    out,sim=Path(out),Path(sim); sys.path.insert(0,str(sim))
    from engine import Engine, go_round
    from scenario_io import load_scenario
    from phase_audit import TaggedSolver
    from simulator import Client
    m=json.loads((out/'manifest.json').read_bytes()); rec=m['records'][index]
    cfg=next(c for c in m['configs'] if c['name']==variant)
    assert fingerprints(sim)==m['source_hashes'], 'Source changed after freeze'
    raw=json.loads((out/rec['file']).read_bytes()); assert rb.digest(raw)==rec['scene_hash']
    tag=f'{variant}_{index:04d}'; folder=out/('http' if http_url else 'core')
    if (folder/'rows'/f'{tag}.json').exists(): raise FileExistsError('Do not overwrite completed/failed run')
    truth=load_scenario(raw)
    if http_url:
        from client import ControlClient
        control=ControlClient(http_url)
        # Ports/ownership verified by parent before launching each HTTP run.
        state=control.status()
        if state.get('closing_listener'): raise RuntimeError('Previous listener is closing')
        control.start(mode='practice',problem=4,scenario=raw,robot_id='q4-offline-validation',wait=15)
        robot_url=http_url.rsplit(':',1)[0]+':'+str(int(http_url.rsplit(':',1)[1])-1)
        client=Client('q4-offline-validation',folder/'wire'/f'{tag}.jsonl',base_url=robot_url)
        class Backend:
            ended=False; end_reason=None
            def apply(self,path,request):
                p=request.get('position')
                result=client.action(path,np.array([p['x'],p['y']]) if p else None,request.get('channel'))
                if path=='/exit': self.ended=True; self.end_reason=result['exit_reason']
                return result
        engine=Backend()
    else: engine=Engine(truth)
    class Adapter(rb.EngineAdapter):
        def action(self,path,position=None,channel=None):
            rng=rb.digest({str(c): t['hyp'].rng.bit_generator.state for c,t in solver.tracks.items() if t.get('hyp') is not None})
            before_us=round(self.virtual_time*1e6); old=self.position.copy(); old_channel=self.channel
            response=super().action(path,position,channel)
            self.log[-1]['rng_before']=rng
            if position is not None:
                move=go_round(1e12*math.hypot(float(position[0]-old[0]),float(position[1]-old[1]))/5000000)
                extra=(5000000+1000000*int(channel!=old_channel)) if path=='/measure' else (5000000 if response['clear_result']=='success' else 3000000)
                assert round(self.virtual_time*1e6)==before_us+move+extra, 'Integer microsecond ledger mismatch'
            return response
    api=Adapter(engine)
    solver=TaggedSolver(api,True,'P4','cpu',cfg.get('particles',16384),diagnostic=cfg)
    start=time.perf_counter(); error=''; result={}
    try: result=solver.run()
    except Exception as exc: error=f'{type(exc).__name__}: {exc}'
    elapsed=time.perf_counter()-start
    cleared={a['channel'] for a in api.log if a['path']=='/clear' and a['response'].get('accepted') is True and a['response'].get('clear_result')=='success'}
    status=('TIMEOUT' if 'Timeout' in error else 'PROTOCOL_ERROR' if 'Protocol' in error or 'Rejected' in error else 'EXCEPTION') if error else ('FULL_CLEAR' if len(cleared)==len(truth.jammers) else 'PARTIAL_CLEAR')
    targets=list(solver.trace.values())
    row=dict(id=index,cohort=rec['cohort'],family=rec['family'],variant=variant,run_status=status,error=error,
        total=len(truth.jammers),cleared=len(cleared),virtual_time_s=api.virtual_time,
        mean_time_per_source=api.virtual_time/len(truth.jammers),original_time_per_cleared=api.virtual_time/max(1,len(cleared)),
        distance=api.distance,detect_count=api.measures,switch_count=api.switches,clear_attempts=api.clear_attempts,
        failed_clears=sum(a['path']=='/clear' and a['response'].get('accepted') is True and a['response'].get('clear_result')!='success' for a in api.log),
        runtime_s=elapsed,completion_reason=result.get('completion_reason'),engine_end_reason=engine.end_reason,
        fallback_count=solver.fallbacks,diagnostic_count=sum(t['diagnostic_count'] for t in targets),
        directional_count=sum(j.kind=='directional' for j in truth.jammers),
        scene_hash=rec['scene_hash'],source_hash=rb.digest(m['source_hashes']),config_hash=rb.digest(cfg),
        remaining_tracks=len(solver.tracks),transport='HTTP' if http_url else 'core')
    for stage,costs in api.stages.items(): row['stage_'+stage+'_s']=costs['total_s']
    trace=dict(row=row,targets=targets,actions=api.log,stages=api.stages)
    try:
        metrics,audit=audit_trace(trace,row,raw,cfg)
        row.update(metrics); row['audit_passed']=audit['passed'] and not solver.tracks
        trace['audit']=audit
    except Exception as exc: row['audit_passed']=False; trace['audit']=dict(error=repr(exc))
    folder.joinpath('traces').mkdir(parents=True,exist_ok=True)
    with gzip.open(folder/'traces'/f'{tag}.json.gz','wt',encoding='utf-8') as f: json.dump(trace,f,ensure_ascii=False)
    rb.save(folder/'rows'/f'{tag}.json',row)
    return row


def canonical_actions(trace):
    # Keep all physical feedback including virtual time; transport budget is not physical feedback.
    return [dict(path=a['path'],position=a['position'],channel=a['channel'],rng_before=a.get('rng_before'),
        response={k:v for k,v in a['response'].items() if k not in ('remaining_real_duration_s','remaining_virtual_duration_s','arena_id','robot_id','request_id')}) for a in trace['actions']]


def report(out,cohort):
    m=json.loads((out/'manifest.json').read_bytes()); records=[r for r in m['records'] if r['cohort']==cohort]
    rows=[]; pairs=[]; integrity=[]
    for rec in records:
        group={}; traces={}
        for v in 'ABC':
            p=out/'core/rows'/f'{v}_{rec["id"]:04d}.json'
            if not p.exists(): continue
            group[v]=json.loads(p.read_bytes()); rows.append(group[v])
            with gzip.open(out/'core/traces'/f'{v}_{rec["id"]:04d}.json.gz','rt',encoding='utf-8') as f: traces[v]=json.load(f)
            assert group[v]==traces[v]['row']
            assert group[v]['scene_hash']==rec['scene_hash'] and group[v]['source_hash']==rb.digest(m['source_hashes'])
            assert group[v]['config_hash']==rb.digest(next(c for c in m['configs'] if c['name']==v))
        if set(group)!=set('ABC'): integrity.append(dict(id=rec['id'],error='missing runs')); continue
        a,b=canonical_actions(traces['A']),canonical_actions(traces['B'])
        if rec['total']<16: prefix_ok=a==b
        else:
            cleared=set(); end=None
            for i,action in enumerate(a):
                if action['path']=='/clear' and action['response'].get('accepted') is True and action['response'].get('clear_result')=='success':
                    cleared.add(action['channel'])
                    if len(cleared)==16: end=i; break
            prefix_ok=end is not None and b[:-1]==a[:end+1] and b[-1]['path']=='/exit'
        integrity.append(dict(id=rec['id'],prefix_ok=prefix_ok,nonincrease=group['B']['virtual_time_s']<=group['A']['virtual_time_s'],
                              all_full=all(r['run_status']=='FULL_CLEAR' and r['audit_passed'] for r in group.values())))
        for before,after in (('A','B'),('B','C'),('A','C')):
            x,y=group[before],group[after]
            pairs.append(dict(id=rec['id'],total=rec['total'],family=rec['family'],comparison=after+'-'+before,
                 delta_s_per_source=y['mean_time_per_source']-x['mean_time_per_source'],delta_total_s=y['virtual_time_s']-x['virtual_time_s'],
                 delta_move_s=(y['distance']-x['distance'])/5,delta_measure_s=5*(y['detect_count']-x['detect_count']),
                 delta_switch_s=y['switch_count']-x['switch_count'],delta_failed_clear_s=3*(y['failed_clears']-x['failed_clears']),
                 directional_fraction=x['directional_count']/x['total'],both_full=x['run_status']==y['run_status']=='FULL_CLEAR'))
    summary={}
    for v in 'ABC':
        g=[r for r in rows if r['variant']==v]; good=[r for r in g if r['run_status']=='FULL_CLEAR' and r['audit_passed']]
        summary[v]=dict(runs=len(g),full=sum(r['run_status']=='FULL_CLEAR' for r in g),audited=len(good),
                       statuses=dict(__import__('collections').Counter(r['run_status'] for r in g)),
                       per_source=quantiles([r['mean_time_per_source'] for r in good]),
                       total_time=quantiles([r['virtual_time_s'] for r in good]),
                       early_exit=sum(r['completion_reason']=='public_max_cleared' for r in g))
    comparisons={}
    for comp in ('B-A','C-B','C-A'):
        p=[p for p in pairs if p['comparison']==comp and p['both_full']]
        d=[r['delta_s_per_source'] for r in p]
        comparisons[comp]=dict(delta=quantiles(d),wins=sum(x< -1e-9 for x in d),ties=sum(abs(x)<=1e-9 for x in d),losses=sum(x>1e-9 for x in d),
            by_count={label:quantiles([r['delta_s_per_source'] for r in p if (r['total']==16)==sixteen]) for label,sixteen in (('10-15',False),('16',True))},
            by_direction={label:quantiles([r['delta_s_per_source'] for r in p if (r['directional_fraction']>=.75)==high]) for label,high in (('below75pct',False),('atleast75pct',True))})
    complete=len(rows)==len(records)*3
    b_ok=complete and all(r.get('prefix_ok') and r.get('nonincrease') and r.get('all_full') for r in integrity)
    c_ok=b_ok and summary['C']['per_source']['mean']<=.99*summary['B']['per_source']['mean'] and all(summary['C']['per_source'][q]<=summary['B']['per_source'][q] for q in ('P95','P99'))
    result=dict(cohort=cohort,complete=complete,summary=summary,comparisons=comparisons,integrity=integrity,B_pass=b_ok,C_pass=c_ok)
    rb.save(out/f'{cohort}_summary.json',result)
    for name,data in ((f'{cohort}_cases.csv',rows),(f'{cohort}_pairs.csv',pairs)):
        if data:
            with (out/name).open('w',newline='',encoding='utf-8-sig') as f:
                w=csv.DictWriter(f,fieldnames=sorted(set().union(*(r.keys() for r in data)))); w.writeheader();w.writerows(data)
    print(json.dumps({k:v for k,v in result.items() if k!='integrity'},ensure_ascii=False),flush=True)
    return result


def main():
    p=argparse.ArgumentParser();p.add_argument('--sim-root',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--freeze',action='store_true');p.add_argument('--cohort',choices=['development','evaluation','stress'])
    p.add_argument('--workers',type=int,default=4);p.add_argument('--report',action='store_true');p.add_argument('--single',type=int)
    p.add_argument('--variant',choices=list('ABC'));p.add_argument('--http-control');p.add_argument('--resume',action='store_true')
    args=p.parse_args();out=args.output.resolve();sim=args.sim_root.resolve();sys.path.insert(0,str(sim))
    if args.freeze: freeze(out,sim);return
    if args.single is not None:
        print(json.dumps(run_case((out,sim,args.single,args.variant,args.http_control))));return
    if args.report: report(out,args.cohort);return
    if args.cohort=='evaluation':
        gate=json.loads((out/'development_summary.json').read_bytes())
        assert gate['B_pass'], 'Development integrity gate failed'
    m=json.loads((out/'manifest.json').read_bytes());assert fingerprints(sim)==m['source_hashes']
    jobs=[(out,sim,r['id'],v,None) for r in m['records'] if r['cohort']==args.cohort for v in 'ABC'
          if not(args.resume and (out/'core/rows'/f'{v}_{r["id"]:04d}.json').exists())]
    os.environ.update(OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='1')
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        futures={pool.submit(run_case,j):j for j in jobs}
        for n,f in enumerate(as_completed(futures),1):
            r=f.result();print(f'{n}/{len(jobs)} {r["variant"]} {r["id"]} {r["run_status"]} audit={r["audit_passed"]} wall={r["runtime_s"]:.1f}s',flush=True)
    report(out,args.cohort)

if __name__=='__main__': main()
