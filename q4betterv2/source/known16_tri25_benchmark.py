"""Frozen four-way experiment; reuse the established offline/HTTP adapter and ledger."""
import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from collections import Counter
from fractions import Fraction
import gzip
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import time
import zipfile
import numpy as np
import public_max37_benchmark as old
import recovered_benchmark as rb
from reporting.discovery_report import quantiles, write_csv, point_in_convex_polygon_exact
if not __debug__:
    raise RuntimeError('Audit requires Python assertions enabled; -O is forbidden')
BASE = Path(__file__).resolve().parent
VARIANTS = ('R0','R1','R2','R12')
PAIRS = (('R0','R1'),('R0','R2'),('R0','R12'),('R1','R12'),('R2','R12'))
canonical_actions = old.canonical_actions
_original_fingerprints = old.fingerprints

def fingerprints(sim):
    hashes=_original_fingerprints(sim)
    for rel in ('reporting/nccp_report.py','tests/test_known16_tri25.py','tests/test_public_max.py','tests/test_public_max_protocol.py','experiments/http_known16_tri25.py','COVERAGE25.md'):
        p=BASE/rel
        if p.exists():hashes['solver/'+rel]=hashlib.sha256(p.read_bytes()).hexdigest()
    return hashes

old.fingerprints=fingerprints


def physical_hash(raw):
    from scenario_io import load_scenario
    from dataclasses import asdict
    s=load_scenario(raw)
    return rb.digest(dict(jammers=sorted([asdict(j) for j in s.jammers],key=lambda j:j['channel']),noise_seed=s.noise_seed_hex))


def freeze(out, sim):
    from scenario_io import generate_document, load_scenario
    assert not (out/'manifest.json').exists()
    prior=BASE/'results/public_max37/frozen'
    pm=json.loads((prior/'manifest.json').read_bytes())
    cfg=json.loads((BASE/'configs/q4_public_max37_C.yaml').read_bytes())
    configs=[dict(cfg,name=v,finish_after_public_max_known=v in ('R1','R12'),
                  discovery_coverage='certified25' if v in ('R2','R12') else 'certified37') for v in VARIANTS]
    for c in configs: rb.save(BASE/f'configs/q4_known16_tri25_{c["name"]}.yaml',c)
    records=[]; used=set(); historical=set()
    for path in (BASE/'results').glob('**/scenes/*.json'):
        if path.is_relative_to(out):continue
        try: historical.add(physical_hash(json.loads(path.read_bytes())))
        except (ValueError,KeyError,TypeError): pass
    for old_id in (60,67,71,119,171):
        r=pm['records'][old_id]; raw=json.loads((prior/r['file']).read_bytes())
        assert rb.digest(raw)==r['scene_hash']
        records.append(dict(cohort='regression',family='previous_C',previous_id=old_id,scene=raw))
    # Exact count strata, chosen independently of any policy outcome.
    for cohort,count in (('development',32),('evaluation',256)):
        index=0
        for slot in range(count):
            target=10+slot%7
            while True:
                seed=hashlib.sha256(f'2026B-known16-tri25-v1:{cohort}:{index}'.encode()).hexdigest(); index+=1
                raw=generate_document(seed_hex=seed,problem=4,format='native')
                h=physical_hash(raw); kinds={j.kind for j in load_scenario(raw).jammers}
                if len(raw['jammers'])==target and kinds=={'omni','directional'} and h not in used|historical: break
            used.add(h); records.append(dict(cohort=cohort,family='strict_mixed_stratified',seed_hex=seed,scene=raw))
    from geometry import coverage
    grid=np.vstack((coverage(True,version='certified25'),coverage(True,version='certified37')))
    grid=[p for p in grid if np.linalg.norm(p)<1799]
    families=('boundary_outward','grid_vicinity','cluster_mixed','high_directional','all_omni','all_directional','generated_16','boundary_tangent')
    for slot in range(32):
        family=families[slot%8]; seed=hashlib.sha256(f'2026B-known16-tri25-pressure-v1:{slot}'.encode()).hexdigest()
        raw=generate_document(seed_hex=seed,problem=4,format='native')
        if family=='generated_16':
            k=0
            while len(raw['jammers'])!=16:
                k+=1; seed=hashlib.sha256(f'2026B-known16-tri25-pressure-v1:{slot}:{k}'.encode()).hexdigest()
                raw=generate_document(seed_hex=seed,problem=4,format='native')
        else:
            raw=dict(format='jammers-offline-v1',problem=4,noise_seed_hex=raw['noise_seed_hex'],generator_seed=seed,jammers=[])
            for i in range(16):
                angle=2*math.pi*(i/16+slot/997)
                x,y=1799.999*math.cos(angle),1799.999*math.sin(angle)
                if family=='grid_vicinity': x,y=grid[(i+slot)%len(grid)]+np.array([.001*(slot+1),-.002])
                if family=='cluster_mixed': x,y=250+slot+i*.07,-350+i*.09
                if family=='high_directional': x,y=1300*math.cos(angle),1300*math.sin(angle)
                omni=family=='all_omni' or (family!='all_directional' and i==0)
                direction=(math.degrees(angle)+(90 if family=='boundary_tangent' else 0))%360
                raw['jammers'].append(dict(channel=i+1,x=float(x),y=float(y),receive_radius_m=1000.,kind='omni' if omni else 'directional',direction_deg=0. if omni else direction))
        load_scenario(raw);h=physical_hash(raw);assert h not in used|historical
        used.add(h);records.append(dict(cohort='stress',family=family,seed_hex=seed,scene=raw))
    baseline=json.loads((out/'BASELINE.json').read_bytes())
    with zipfile.ZipFile(out/'baseline_source.zip') as z:
        assert set(z.namelist())==set(baseline['matches'])
        assert all(hashlib.sha256(z.read(name)).hexdigest()==baseline['source_hashes'][name] for name in z.namelist())
    baseline['archive_sha256']=hashlib.sha256((out/'baseline_source.zip').read_bytes()).hexdigest()
    baseline['record_sha256']=hashlib.sha256((out/'BASELINE.json').read_bytes()).hexdigest()
    manifest=dict(baseline=baseline,configs=configs,source_hashes=fingerprints(sim),
        simulator_root=str(sim),python=sys.version,numpy=np.__version__,frozen_at=__import__('datetime').datetime.now().isoformat(),
        execution_backend='LOCAL_DEV',execution_purpose='FRAMEWORK_INTEGRATION',production_eligible=False,
        design='32 development + 256 evaluation: target N=10+slot%7; reject non-strict-mixed, previous archived physical hashes, duplicates. 32 separate pressure. No parameter search.',
        historical_physical_hashes_checked=len(historical),historical_limit='Checks archived local scenarios only; inaccessible historical source lists cannot be verified.',
        adoption='State/continuous coverage and no new failures prerequisite. R1 evaluate N16, unchanged N<16. R2/R12 mean >=1% faster and P95/P99 nonincrease versus R0. Joint must beat best single; marginal<1% limited. Pressure separate.',records=[])
    for i,r in enumerate(records):
        raw=r.pop('scene');filename=f'scenes/{i:04d}.json';rb.save(out/filename,raw)
        manifest['records'].append(dict(r,id=i,file=filename,scene_hash=rb.digest(raw),physical_hash=physical_hash(raw),total=len(raw['jammers'])))
    rb.save(out/'manifest.json',manifest)
    with zipfile.ZipFile(out/'frozen_source.zip','x',zipfile.ZIP_DEFLATED) as z:
        for name,h in manifest['source_hashes'].items():
            prefix,rel=name.split('/',1);data=((BASE if prefix=='solver' else sim)/rel).read_bytes()
            assert hashlib.sha256(data).hexdigest()==h;z.writestr(name,data)
        for c in configs:z.writestr('configs/'+c['name']+'.json',json.dumps(c,indent=2))
        z.writestr('manifest.json',(out/'manifest.json').read_bytes())
    print('Frozen 325 scenes / 1300 core runs',flush=True)


def run_case(job):
    # Evaluation-only hook: truth never enters a strategy method or decision.
    import phase_audit
    Original=phase_audit.TaggedSolver
    out,sim,index,v,http=job;out=Path(out);sys.path.insert(0,str(sim))
    from scenario_io import load_scenario
    m=json.loads((out/'manifest.json').read_bytes());raw=json.loads((out/m['records'][index]['file']).read_bytes())
    truth={j.channel: (Fraction(j.x),Fraction(j.y)) for j in load_scenario(raw).jammers}
    class Audited(Original):
        def check_set(self,c):
            if c in self.tracks:
                poly=self.tracks[c]['poly']
                self.target_trace(c).setdefault('conservative_sets',[]).append(dict(time=self.api.virtual_time,polygon=poly.tolist()))
                assert c in truth and point_in_convex_polygon_exact(truth[c],poly), f'True source outside conservative set channel {c}'
        def measure(self,c,p):
            result=super().measure(c,p);self.check_set(c);return result
        def clear(self,c,p,certified=False):
            self.check_set(c);return super().clear(c,p,certified)
    phase_audit.TaggedSolver=Audited
    try: row=old.run_case(job)
    finally: phase_audit.TaggedSolver=Original
    folder=out/('http' if http else 'core');tag=f'{v}_{index:04d}'
    with gzip.open(folder/'traces'/f'{tag}.json.gz','rt',encoding='utf-8') as f:trace=json.load(f)
    known=set();cleared=set();trigger=None
    for a in trace['actions']:
        r=a['response'];c=a['channel']
        if r.get('accepted') is True:
            if r.get('clear_result')=='success':cleared.add(c);known.add(c)
            if r.get('measure_result') in ('direction','near'):known.add(c)
        if len(known)==16 and trigger is None:
            trigger=dict(time_s=r['virtual_time_s'],cleared=len(cleared),unresolved=len(known-cleared),channels=sorted(known))
    row.update(known16_reached=trigger is not None,known16_enabled=v in ('R1','R12'),
        known16_time_s=trigger['time_s'] if trigger else None,known16_cleared=trigger['cleared'] if trigger else None,
        known16_unresolved=trigger['unresolved'] if trigger else None,post_known16_s=row['virtual_time_s']-trigger['time_s'] if trigger else None,
        conservative_set_checks=sum(len(t.get('conservative_sets',[])) for t in trace['targets']))
    trace['known16_evidence']=trigger;trace['row']=row
    with gzip.open(folder/'traces'/f'{tag}.json.gz','wt',encoding='utf-8') as f:json.dump(trace,f,ensure_ascii=False)
    rb.save(folder/'rows'/f'{tag}.json',row);return row


def report(out,cohort):
    m=json.loads((out/'manifest.json').read_bytes());records=[r for r in m['records'] if r['cohort']==cohort]
    rows=[];pairs=[];interaction=[];integrity=[]
    for rec in records:
        group={};traces={}
        for v in VARIANTS:
            p=out/'core/rows'/f'{v}_{rec["id"]:04d}.json'
            if not p.exists():continue
            row=json.loads(p.read_bytes());group[v]=row;rows.append(row)
            with gzip.open(out/'core/traces'/f'{v}_{rec["id"]:04d}.json.gz','rt',encoding='utf-8') as f:traces[v]=json.load(f)
            assert traces[v]['row']==row and row['scene_hash']==rec['scene_hash'] and row['source_hash']==rb.digest(m['source_hashes'])
        if set(group)!=set(VARIANTS):integrity.append(dict(id=rec['id'],passed=False,error='missing'));continue
        exact=[]
        for base,opt in (('R0','R1'),('R2','R12')):
            a,b=canonical_actions(traces[base]),canonical_actions(traces[opt])
            if rec['total']<16:exact.append(a==b)
            else:
                k=set();end=None
                for i,action in enumerate(a):
                    r=action['response']
                    if r.get('accepted') is True and (r.get('measure_result') in ('direction','near') or r.get('clear_result')=='success'):k.add(action['channel'])
                    if len(k)==16:end=i;break
                exact.append(end is not None and a[:end+1]==b[:end+1])
        full=all(r['run_status']=='FULL_CLEAR' and r['audit_passed'] for r in group.values())
        integrity.append(dict(id=rec['id'],prefix_equal=all(exact),all_full=full,passed=all(exact) and full))
        for base,opt in PAIRS:
            x,y=group[base],group[opt];delta=y['mean_time_per_source']-x['mean_time_per_source']
            pairs.append(dict(id=rec['id'],cohort=cohort,total=rec['total'],family=rec['family'],comparison=opt+'-'+base,
                delta_s_per_source=delta,delta_percent=100*delta/x['mean_time_per_source'],baseline_s_per_source=x['mean_time_per_source'],
                delta_total_s=y['virtual_time_s']-x['virtual_time_s'],valid=full))
        interaction.append(dict(id=rec['id'],total=rec['total'],cohort=cohort,family=rec['family'],valid=full,
            interaction_s_per_source=group['R12']['mean_time_per_source']-group['R1']['mean_time_per_source']-group['R2']['mean_time_per_source']+group['R0']['mean_time_per_source']))
    summary={}
    for v in VARIANTS:
        g=[r for r in rows if r['variant']==v];good=[r for r in g if r['run_status']=='FULL_CLEAR' and r['audit_passed']]
        metrics=('virtual_time_s','distance','detect_count','switch_count','failed_clears','runtime_s','known16_time_s','known16_cleared','known16_unresolved','post_known16_s')+tuple('stage_'+s+'_s' for s in rb.STAGES)
        summary[v]=dict(runs=len(g),full=sum(r['run_status']=='FULL_CLEAR' for r in g),audited=len(good),statuses=dict(Counter(r['run_status'] for r in g)),
            per_source=quantiles([r['mean_time_per_source'] for r in good]),metrics={k:quantiles([r[k] for r in good]) for k in metrics},
            known16_triggers=sum(r['known16_reached'] and r['known16_enabled'] for r in g),clear16_exits=sum(r['completion_reason']=='public_max_cleared' for r in g))
    comparisons={}
    for base,opt in PAIRS:
        comp=opt+'-'+base;p=[r for r in pairs if r['comparison']==comp and r['valid']]
        def stats(p):
            d=[r['delta_s_per_source'] for r in p];baseline=[r['baseline_s_per_source'] for r in p]
            return dict(delta=quantiles(d),percent=100*np.mean(d)/np.mean(baseline) if d else None,
                wins=sum(x<-1e-9 for x in d),ties=sum(abs(x)<=1e-9 for x in d),losses=sum(x>1e-9 for x in d),worst=max(p,key=lambda r:r['delta_s_per_source'],default=None))
        comparisons[comp]=dict(all=stats(p),by_count={label:stats([r for r in p if (r['total']==16)==sixteen]) for label,sixteen in (('10-15',False),('16',True))})
    passed=bool(records) and len(rows)==len(records)*4 and all(r['passed'] for r in integrity)
    result=dict(cohort=cohort,passed=passed,summary=summary,comparisons=comparisons,integrity=integrity,
        interaction=quantiles([r['interaction_s_per_source'] for r in interaction if r['valid']]),
        strata=dict(Counter(r['total'] for r in records)))
    rb.save(out/f'{cohort}_summary.json',result)
    for name,data in (('cases',rows),('pairs',pairs),('interaction',interaction)):write_csv(out/f'{cohort}_{name}.csv',data)
    print(json.dumps(dict(cohort=cohort,passed=passed,runs=len(rows),means={v:summary[v]['per_source']['mean'] for v in VARIANTS})),flush=True)
    return result


def main():
    p=argparse.ArgumentParser();p.add_argument('--sim-root',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--freeze',action='store_true');p.add_argument('--cohort',choices=('development','evaluation','stress','regression'))
    p.add_argument('--workers',type=int,default=4);p.add_argument('--report',action='store_true');p.add_argument('--resume',action='store_true')
    p.add_argument('--single',type=int);p.add_argument('--variant',choices=VARIANTS);p.add_argument('--http-control')
    args=p.parse_args();out=args.output.resolve();sim=args.sim_root.resolve();sys.path.insert(0,str(sim))
    if args.freeze:freeze(out,sim);return
    if args.single is not None:print(json.dumps(run_case((out,sim,args.single,args.variant,args.http_control))));return
    if args.report:report(out,args.cohort);return
    if args.cohort=='evaluation':assert json.loads((out/'development_summary.json').read_bytes())['passed'],'Development gate failed'
    m=json.loads((out/'manifest.json').read_bytes());assert fingerprints(sim)==m['source_hashes']
    jobs=[(out,sim,r['id'],v,None) for r in m['records'] if r['cohort']==args.cohort for v in VARIANTS
        if not(args.resume and (out/'core/rows'/f'{v}_{r["id"]:04d}.json').exists())]
    os.environ.update(OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='1')
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        futures=[pool.submit(run_case,j) for j in jobs]
        for n,f in enumerate(as_completed(futures),1):
            r=f.result();print(f'{n}/{len(jobs)} {r["variant"]} {r["id"]} {r["run_status"]} audit={r["audit_passed"]} wall={r["runtime_s"]:.1f}s',flush=True)
    report(out,args.cohort)

if __name__=='__main__':main()
