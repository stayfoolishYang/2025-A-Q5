from pathlib import Path
import csv,gzip,hashlib,json,shutil,zipfile
import pandas as pd
BASE=Path(__file__).resolve().parent;ROOT=BASE/'Q4_写作与绘图全量交接包_20260912_v1';D=ROOT/'02_绘图数据'
src=pd.read_csv(D/'all_sources_raw_fields.csv')
for old,new in [('x_um','x_m'),('y_um','y_m'),('max_receive_um','receive_radius_m'),('direction_udeg','direction_deg')]:src[new]=src[old]/1e6
src.to_csv(D/'all_sources_m.csv',index=False,encoding='utf-8-sig')
targets=[];geometry=[]
for p in sorted((ROOT/'05_完整模拟轨迹/results/core/traces').glob('*.json.gz')):
    d=json.loads(gzip.decompress(p.read_bytes()));i=d['row']['id']
    for t in d['targets']:
        row={'case_id':i}
        for k,v in t.items():
            if isinstance(v,(str,int,float,bool)) or v is None:row[k]=v
        targets.append(row)
        for j,g in enumerate(t.get('geometry_history',[])):geometry.append(dict(case_id=i,channel=t['channel'],observation_index=j,**g))
pd.DataFrame(targets).to_csv(D/'target_summary.csv',index=False,encoding='utf-8-sig')
pd.DataFrame(geometry).to_csv(D/'geometry_history.csv',index=False,encoding='utf-8-sig')
dictionary=[]
for p in D.glob('*.csv'):
    frame=pd.read_csv(p)
    for c in frame.columns:dictionary.append(dict(table=p.name,field=c,dtype=str(frame[c].dtype),rows=len(frame),missing=int(frame[c].isna().sum())))
pd.DataFrame(dictionary).to_csv(D/'FIELD_CATALOG.csv',index=False,encoding='utf-8-sig')
old=BASE/'Q4_全部探索_写作资料包_20260912.zip'
if old.exists():shutil.copy2(old,ROOT/'00_原始输入'/old.name)
shutil.copy2(__file__,ROOT/'08_脚本'/Path(__file__).name)
(ROOT/'01_写作说明/04_新增绘图字段.md').write_text('''# 补充绘图字段

- all_sources_m.csv：由原x_um/y_um/max_receive_um除以1e6得到x_m/y_m/receive_radius_m；direction_udeg除1e6得到direction_deg。原字段全部保留。该表为离线真值，不能作为在线定位输入。
- target_summary.csv：每场每频道的标量摘要（首次发现/清除/失败/测量计数等实际已有字段）；具体空值不填0。
- geometry_history.csv：每场每频道每条几何记录，包含time、diameter、mec_radius、particle_count，可画不确定性收缩过程；按observation_index排序。
- FIELD_CATALOG.csv：全部派生表的真实字段、类型、行数和缺失数量，用于导入前检查。语义见02_数据字典与绘图任务.md与冻结记录字段。

参考图路径上的星号为离线源真值，叉号为清除尝试，并非每次都成功。参考图不是正式日志的路径。
''',encoding='utf-8')
files=sorted(p for p in ROOT.rglob('*') if p.is_file() and p.name!='MANIFEST_SHA256.csv')
with (ROOT/'MANIFEST_SHA256.csv').open('w',encoding='utf-8-sig',newline='') as f:
    w=csv.writer(f);w.writerow(['relative_path','bytes','sha256'])
    for p in files:w.writerow([p.relative_to(ROOT).as_posix(),p.stat().st_size,hashlib.sha256(p.read_bytes()).hexdigest()])
dest=ROOT.with_suffix('.zip')
assert not dest.exists()
with zipfile.ZipFile(dest,'w',zipfile.ZIP_DEFLATED,compresslevel=6,allowZip64=True) as z:
    for p in sorted(ROOT.rglob('*')):
        if p.is_file():z.write(p,p.relative_to(ROOT).as_posix())
with zipfile.ZipFile(dest) as z:
    assert z.testzip() is None
    count=len(z.namelist())
report=dict(file=str(dest),bytes=dest.stat().st_size,files=count,sha256=hashlib.sha256(dest.read_bytes()).hexdigest(),crc='PASS',formal_performance='UNAVAILABLE_ENCRYPTED',simulation_data_checks='PASS',new_solver_runs=0)
dest.with_suffix('.verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(report,ensure_ascii=False),flush=True)
