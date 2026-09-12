from pathlib import Path
import csv,gzip,hashlib,io,json,shutil,zipfile
import numpy as np
import pandas as pd

BASE=Path(__file__).resolve().parent
OUT=BASE/'Q4_写作与绘图全量交接包_20260912_v1'
OUT.mkdir(exist_ok=False)
for d in ['00_原始输入','01_写作说明','02_绘图数据','03_参考图','04_模拟原包展开','05_完整模拟轨迹','06_正式日志','07_历史对照','08_脚本']: (OUT/d).mkdir()
INPUT=Path('D:/下载')
inputs=['formal-p4-2-YEE2-FYQH-VG8N-PHYY.zip','Q4_21_R12_F_CT_模拟数据与复现包_20260912.zip','README_数据说明与复现.md']
for n in inputs:shutil.copy2(INPUT/n,OUT/'00_原始输入'/n)
def extract(z,dest):
    root=dest.resolve()
    for item in z.infolist():
        target=(root/item.filename).resolve()
        if not target.is_relative_to(root):raise ValueError('unsafe zip path')
    z.extractall(dest)
sim=OUT/'04_模拟原包展开'
with zipfile.ZipFile(INPUT/inputs[1]) as z:extract(z,sim)
with zipfile.ZipFile(sim/'archives/q4_revised_1000_full_evidence.zip') as z:extract(z,OUT/'05_完整模拟轨迹')
with zipfile.ZipFile(sim/'support/evidence/q4_local.zip') as z:extract(z,OUT/'07_历史对照')
checks=[]
for entry in json.loads((sim/'MANIFEST_SHA256.json').read_bytes())['files']:
    p=sim/entry['path'];ok=p.exists() and hashlib.sha256(p.read_bytes()).hexdigest()==entry['sha256']
    checks.append(dict(check='input_manifest',file=entry['path'],passed=ok))
assert all(x['passed'] for x in checks),'input manifest mismatch'
formal=[]
with zipfile.ZipFile(INPUT/inputs[0]) as z:
    extract(z,OUT/'06_正式日志')
    for n in z.namelist():
        b=z.read(n);assert b[:8]==b'JMBFLOG1'
        start=b.index(b'{'); header,_=json.JSONDecoder().raw_decode(b[start:].decode('utf-8',errors='replace'))
        row={k:header.get(k) for k in ['problem_no','formal_index','case_code','created_at_utc','client_version','build_id','content_encryption','payload_schema_version']}
        row.update(file=n,bytes=len(b),sha256=hashlib.sha256(b).hexdigest(),result_status='ENCRYPTED_NOT_READABLE',solver_version='UNVERIFIED',total_sources=None,cleared=None,virtual_time_s=None,seconds_per_source=None)
        formal.append(row)
data=OUT/'02_绘图数据'
pd.DataFrame(formal).to_csv(data/'formal_metadata_only.csv',index=False,encoding='utf-8-sig')
cases=pd.read_csv(sim/'support/expanded_regression/cases.csv')
reg=pd.read_csv(sim/'support/expanded_regression/pairs.csv')
assert len(cases)==1000 and cases.id.is_unique and cases.scene_hash.is_unique
assert np.allclose(cases.virtual_time_s/cases.total,cases.mean_time_per_source,rtol=0,atol=1e-10)
assert ((cases.directional_count==cases.total)==(cases.family=='all_directional')).all()
cases.to_csv(data/'simulation_cases_final.csv',index=False,encoding='utf-8-sig')
hist=pd.read_csv(OUT/'07_历史对照/pairs.csv')
assert len(hist)==1000 and hist.id.is_unique
comparison=cases[['id','scene_hash','family','total','mean_time_per_source']].merge(reg[['id','scene_hash','historical_B','revised_B']],on=['id','scene_hash'],validate='one_to_one').merge(hist,on='id',validate='one_to_one')
assert (comparison.total==comparison.N).all()
assert np.allclose(comparison.historical_B,comparison.B_s_per_source,rtol=0,atol=1e-10)
assert np.allclose(comparison.revised_B,comparison.mean_time_per_source,rtol=0,atol=1e-10)
comparison['final_minus_old_A']=comparison.revised_B-comparison.A_s_per_source
comparison['final_minus_historical_B']=comparison.revised_B-comparison.historical_B
comparison.to_csv(data/'paired_versions_same_1000.csv',index=False,encoding='utf-8-sig')
summ=[]
for group,df in [('all_1000',cases),*list(cases.groupby('family')),*[(f'N={n}',g) for n,g in cases.groupby('total')]]:
    y=df.mean_time_per_source
    summ.append(dict(group=group,n=len(df),mean=y.mean(),median=y.median(),P90=y.quantile(.9),P95=y.quantile(.95),P99=y.quantile(.99),max=y.max(),std_sample=y.std(ddof=1),normalized_variance=(y/y.mean()).var(ddof=1),mean_game_s=df.virtual_time_s.mean(),full=int((df.cleared==df.total).sum()),audited=int(df.audit_passed.sum()),failed_attempts=int(df.failed_clears.sum()),failed_games=int((df.failed_clears>0).sum()),fallbacks=int(df.fallback_count.sum())))
summary=pd.DataFrame(summ);summary.to_csv(data/'summary_by_family_and_N.csv',index=False,encoding='utf-8-sig')
expected=json.loads((sim/'support/expanded_regression/summary.json').read_bytes())
assert abs(summary.iloc[0]['mean']-expected['all']['mean'])<1e-9
assert abs(summary.iloc[0]['P95']-expected['all']['P95'])<1e-9
ecdf=[]
for family,g in cases.groupby('family'):
    for rank,(_,r) in enumerate(g.sort_values(['mean_time_per_source','id']).iterrows(),1):ecdf.append(dict(family=family,id=int(r.id),seconds_per_source=r.mean_time_per_source,cumulative_probability=rank/len(g)))
pd.DataFrame(ecdf).to_csv(data/'ecdf_by_family.csv',index=False,encoding='utf-8-sig')
actions=[];sources=[];stages=[];events=[];geometries=[];trajectory_checks=[]
full=OUT/'05_完整模拟轨迹/results'
for _,r in cases.iterrows():
    i=int(r.id);tr=json.loads(gzip.decompress((full/f'core/traces/B_{i:04d}.json.gz').read_bytes()))
    scene=json.loads((full/f'scenes/{i:04d}.json').read_bytes())
    canonical=json.dumps(scene,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()
    # Source hash convention is owned by frozen runner; retain both original hash and actual file digest.
    assert abs(tr['row']['virtual_time_s']-r.virtual_time_s)<1e-9
    assert len(scene['jammers'])==int(r.total)
    for j in scene['jammers']:sources.append(dict(case_id=i,**j))
    x=y=previous=0.;totals={k:0. for k in ['travel_s','measure_s','switch_s','clear_s']}
    for idx,a in enumerate(tr['actions']):
        response=a.get('response',{});t=float(response.get('virtual_time_s',previous));p=a.get('position');nx,ny=(p if p is not None else [x,y])
        row=dict(case_id=i,action_index=idx,path=a.get('path'),stage=a.get('stage'),channel=a.get('channel'),start_x_m=x,start_y_m=y,end_x_m=nx,end_y_m=ny,time_before_s=previous,time_after_s=t,delta_s=t-previous,accepted=response.get('accepted'),measure_result=response.get('measure_result'),clear_result=response.get('clear_result'))
        for k in totals:row[k]=a.get(k,0.);totals[k]+=float(row[k])
        actions.append(row);x,y,previous=nx,ny,t
    error=sum(totals.values())-float(r.virtual_time_s)
    assert abs(error)<1e-5,(i,error)
    trajectory_checks.append(dict(case_id=i,action_count=len(tr['actions']),cost_sum_s=sum(totals.values()),end_time_s=previous,ledger_error_s=error))
    for stage,v in tr['stages'].items():stages.append(dict(case_id=i,family=r.family,total_sources=int(r.total),stage=stage,**v))
    ev=json.loads((full/f'events/B_{i:04d}.json').read_bytes())
    for idx,e in enumerate(ev['events']):
        row=dict(case_id=i,event_index=idx)
        for k,v in e.items():
            if isinstance(v,(str,int,float,bool)) or v is None:row[k]=v
        for k in ['start','z','q']:
            if k in e:row[k+'_x_m'],row[k+'_y_m']=e[k]
        if e.get('action',{}).get('position') is not None:row['next_x_m'],row['next_y_m']=e['action']['position']
        events.append(row)
        for idxv,v in enumerate(e.get('polygon',[])):geometries.append(dict(case_id=i,event_index=idx,vertex_index=idxv,x_m=v[0],y_m=v[1]))
    if i%200==0:print('exported',i,flush=True)
for name,rows in [('all_actions',actions),('all_sources_raw_fields',sources),('stage_costs',stages),('ct_events',events),('ct_polygons',geometries),('trajectory_ledger_checks',trajectory_checks)]:
    pd.DataFrame(rows).to_csv(data/(name+'.csv'),index=False,encoding='utf-8-sig')
selection=[]
for family,g in cases.groupby('family'):
    for tag,q in [('median',.5),('p95',.95),('worst',1.)]:
        target=g.mean_time_per_source.quantile(q);selected=g.assign(gap=(g.mean_time_per_source-target).abs()).sort_values(['gap','id']).iloc[0]
        selection.append(dict(family=family,selection=tag,quantile_target=target,case_id=int(selected.id),seconds_per_source=selected.mean_time_per_source))
pd.DataFrame(selection).to_csv(data/'representative_cases.csv',index=False,encoding='utf-8-sig')
checks.extend([dict(check='1000_unique_cases',passed=True),dict(check='case_time_per_source',passed=True),dict(check='three_versions_join',passed=True),dict(check='all_action_ledgers',passed=True),dict(check='formal_results_readable',passed=False,reason='AES-GCM payload; metadata only')])
(OUT/'DATA_VERIFICATION.json').write_text(json.dumps(dict(checks=checks,actions=len(actions),ct_events=len(events),formal_q4=sum(r['problem_no']==4 for r in formal),formal_q3=sum(r['problem_no']==3 for r in formal),no_new_simulations=True),ensure_ascii=False,indent=2),encoding='utf-8')
shutil.copy2(__file__,OUT/'08_脚本'/Path(__file__).name)
print('EXPORT_DONE',str(OUT),len(actions),len(events),flush=True)
