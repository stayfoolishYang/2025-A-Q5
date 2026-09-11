"""Read-only recalculation of downloaded and newly computed evidence."""
import csv
import gzip
import hashlib
import json
import math
import sys
from pathlib import Path
import numpy as np

R=Path(__file__).resolve().parent
sys.path.insert(0,'G:/QQ/jammers_linux')
from engine import go_round

def stats(x):
    return dict(n=len(x),mean=float(np.mean(x)),p95=float(np.quantile(x,.95)),maximum=float(max(x)))

def main():
    m=json.loads((R/'SOURCE.json').read_text())
    blobs=[x for x in m['files'] if x['type']=='blob']
    for x in blobs:
        b=(R/x['path']).read_bytes()
        assert hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest()==x['sha']
    q3=list(csv.DictReader((R/'local_q3_pairs/cases.csv').open()))
    a=[float(x['mean_time_per_source_s']) for x in q3 if x['variant']=='A']
    b=[float(x['mean_time_per_source_s']) for x in q3 if x['variant']=='B']
    delta=np.array(b)-a
    for p in (R/'local_q3_pairs').glob('*.gz'):
        with gzip.open(p,'rt',encoding='utf-8') as f: data=json.load(f)
        pos=(0.,0.); ch=1; us=0; cleared=set()
        for row in data['actions']:
            resp=row['response']; assert resp['accepted'] is True
            if row['path'] in ('/measure','/clear'):
                pt=row['position']; us+=go_round(1e12*math.hypot(pt[0]-pos[0],pt[1]-pos[1])/5000000)
                if row['path']=='/measure':
                    us+=5000000+1000000*(ch!=row['channel']); ch=row['channel']
                else:
                    ok=resp['clear_result']=='success'; us+=5000000 if ok else 3000000
                    if ok: cleared.add(row['channel'])
                pos=pt
            assert round(resp['virtual_time_s']*1e6)==us
        assert len(cleared)==data['result']['total']
    q4=list(csv.DictReader((R/'q4better/results/public_max37/cases.csv').open()))
    groups={}
    for cohort in ('evaluation','stress'):
        rows=[x for x in q4 if x['cohort']==cohort]
        by={v:{x['id']:x for x in rows if x['variant']==v} for v in 'ABC'}
        for v in 'ABC':
            assert len(by[v])==len([x for x in rows if x['variant']==v])
            assert all(x['run_status']=='FULL_CLEAR' and x['cleared']==x['total'] for x in by[v].values())
        pairs={}
        for ref,v in [('A','B'),('B','C'),('A','C')]:
            assert by[ref].keys()==by[v].keys()
            assert all(by[ref][i]['scene_hash']==by[v][i]['scene_hash'] for i in by[v])
            d=np.array([float(by[v][i]['mean_time_per_source'])-float(by[ref][i]['mean_time_per_source']) for i in by[v]])
            pairs[v+'-'+ref]=dict(mean=float(d.mean()),wins=int(sum(d < -1e-8)),ties=int(sum(abs(d)<=1e-8)),losses=int(sum(d>1e-8)),max_regression=float(max(d)))
        groups[cohort]=dict(variants={v:stats([float(x['mean_time_per_source']) for x in by[v].values()]) for v in 'ABC'},pairs=pairs)
    remote=json.loads((R/'q4better/results/public_max37/frozen/manifest.json').read_text(encoding='utf-8'))
    hashes=remote['source_hashes']
    engine_match={n:hashlib.sha256((Path('G:/QQ/jammers_linux')/n).read_bytes()).hexdigest()==hashes['engine/'+n] for n in ('engine.py','scenario_io.py','recovered_generator.py')}
    out=dict(download_commit=m['sha'],verified_files=len(blobs),engine_byte_matches=engine_match,
        local_q3=dict(A=stats(a),B=stats(b),mean_delta=float(delta.mean()),wins=int(sum(delta < -1e-8)),ties=int(sum(abs(delta)<=1e-8)),losses=int(sum(delta>1e-8)),max_regression=float(max(delta)),fallbacks={v:sum(int(x['optical_fallbacks']) for x in q3 if x['variant']==v) for v in 'AB'},full_clear_runs=len(q3),integer_time_audit=True),remote_q4_recomputed=groups,official_calls=0)
    (R/'AUDIT.json').write_text(json.dumps(out,indent=2),encoding='utf-8')
    print(json.dumps(out,indent=2))

if __name__=='__main__': main()
