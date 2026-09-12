"""Independent integer-time recount and packaging of the frozen replay."""
import csv, gzip, hashlib, importlib.util, json, math, zipfile
from collections import Counter
from pathlib import Path
HERE=Path(__file__).resolve().parent; OUT=HERE/'results'; SUPPORT=HERE.parent/'support/expanded_regression'

def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def save(p,v): p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v,ensure_ascii=False,indent=2),encoding='utf-8')

def check_actions(aa,total,cleared,time_s):
    done=[];failed=0;us=0;pos=[0.,0.];channel=1;max_error=0;failed_stages={}
    for a in aa:
        path=a['path'];req=a.get('request',a);resp=a['response']
        assert resp.get('accepted') is True
        if path in ('/measure','/clear'):
            p=req['position'];p=[p['x'],p['y']] if isinstance(p,dict) else p
            us+=math.floor(math.hypot(p[0]-pos[0],p[1]-pos[1])*200000+.5)
            c=req['channel']
            if path=='/measure':us+=5000000+1000000*(c!=channel);channel=c
            else:
                success=resp.get('clear_result')=='success';us+=5000000 if success else 3000000
                if success:done.append(c)
                else:
                    failed+=1;k=a.get('stage','not_preserved');failed_stages[k]=failed_stages.get(k,0)+1
            pos=p
        max_error=max(max_error,abs(us-round(resp['virtual_time_s']*1e6)))
    assert len(done)==len(set(done))==int(cleared)==int(total)
    assert abs(aa[-1]['response']['virtual_time_s']-float(time_s))<1e-7
    assert aa[-1]['path']=='/exit'
    return dict(failed=failed,failed_stages=failed_stages,accounting_max_residual_us=max_error)
def main():
    manifest=json.loads((OUT/'manifest.json').read_bytes())
    rows=[]; errors=[]; stages=Counter(); events=Counter(); pending=0; residuals=[]; actions=0; ct_adopted=0; ct_bad=[]; ct_margin=[]; ct_saving=0
    files={}
    for i in range(1000):
        rowfile=OUT/'core/rows'/f'B_{i:04d}.json'; tracefile=OUT/'core/traces'/f'B_{i:04d}.json.gz'; eventfile=OUT/'events'/f'B_{i:04d}.json'
        r=json.loads(rowfile.read_bytes());t=json.load(gzip.open(tracefile,'rt',encoding='utf-8'));e=json.loads(eventfile.read_bytes())
        assert t['row']==r
        check=check_actions(t['actions'],r['total'],r['cleared'],r['virtual_time_s'])
        assert check['failed']==r['failed_clears']
        residuals.append(check['accounting_max_residual_us']);stages.update(check['failed_stages']);actions+=len(t['actions'])
        pending+=e['pending_bridge']
        events.update(x.get('model','unspecified') for x in e['events'])
        for ev in e['events']:
            if ev.get('adopted'):
                ct_adopted+=1;ct_saving+=ev.get('saving_us',0)
                q=ev['q']; margin=20-max(math.hypot(q[0]-v[0],q[1]-v[1]) for v in ev['polygon']);ct_margin.append(margin)
                if margin < -1e-7 or ev.get('clear_success') is not True or ev.get('saving_us',0)<0 or not ev.get('bridge_consumed') or not ev.get('coalescence_prestate_pass'):ct_bad.append(dict(id=i,event=len(ct_margin)-1,margin=margin))
        if not r['audit_passed']: errors.append(i)
        for p in [rowfile,tracefile,eventfile,OUT/f'scenes/{i:04d}.json']:
            files[p.relative_to(HERE).as_posix()]=sha(p)
        rows.append(r)
    for name,h in manifest['source_hashes'].items(): assert sha(HERE/name)==h
    verification=dict(runs=len(rows),actions=actions,trace_row_matches=1000,events_preserved=1000,
        every_scene_full_clear=all(r['run_status']=='FULL_CLEAR' for r in rows),failed_clears=sum(r['failed_clears'] for r in rows),
        failed_clear_stages=dict(stages),max_integer_time_residual_us=max(residuals),failed_audits=errors,
        ct_event_types=dict(events),ct_adopted=ct_adopted,ct_invalid_adopted=ct_bad,ct_min_vertex_clearance_margin_m=min(ct_margin),ct_saving_us_sum=ct_saving,
        pending_bridges_at_end=pending,source_hashes_match=True,
        identity='New revised-code historical-scene replay, not recovery of original trajectories',
        statistical_units=1000,independent_new_scenes=0)
    save(OUT/'verification.json',verification);save(OUT/'file_hashes.json',files)
    SUPPORT.mkdir(parents=True,exist_ok=True)
    (SUPPORT/'README.md').write_bytes((HERE/'README.md').read_bytes())
    (SUPPORT/'historical_search.json').write_bytes((HERE/'historical_search.json').read_bytes())
    for name in ['summary.json','execution.json','verification.json','cases.csv','pairs.csv']:
        (SUPPORT/name).write_bytes((OUT/name).read_bytes())
    with zipfile.ZipFile(SUPPORT/'freeze_and_manifest.zip','w',zipfile.ZIP_DEFLATED,9) as z:
        for name in manifest['source_hashes']: z.write(HERE/name,name)
        for name in ['manifest.json','file_hashes.json']:z.write(OUT/name,'results/'+name)
        z.write(Path(__file__),'verify_and_package.py')
    full=HERE/'q4_revised_1000_full_evidence.zip'
    with zipfile.ZipFile(full,'w',zipfile.ZIP_DEFLATED,9) as z:
        for p in sorted(OUT.rglob('*')):
            if p.is_file():z.write(p,'results/'+p.relative_to(OUT).as_posix())
        for name in manifest['source_hashes']:z.write(HERE/name,name)
        z.write(Path(__file__),'verify_and_package.py')
        z.write(HERE/'historical_search.json','historical_search.json')
        z.write(HERE/'README.md','README.md')
    save(SUPPORT/'full_evidence_archive.json',dict(filename=full.name,bytes=full.stat().st_size,sha256=sha(full),
        contents='1000 scenes, 1000 revised action traces, 1000 CT-event files, rows, hashes, source freeze; local only'))
    print(json.dumps(verification,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
