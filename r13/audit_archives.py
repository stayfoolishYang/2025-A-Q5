"""Supplement exclusion audit: manifests/scenes inside historical zip packages."""
from run_study import ROOT,bench
from pathlib import Path
import os,json,zipfile,hashlib,re
m=json.loads((ROOT/'DEVELOPMENT_MANIFEST.json').read_bytes());fresh={r['physical_hash'] for r in m['records']};seeds={r['seed_hex'] for r in m['records']}
seen=set();records=[];errors=[];overlap=[]
for root in ['J:/2026B_runs','J:/2026B_experiments','I:/GithubRick/2025-A-Q5/交付包','I:/GithubRick/2025-A-Q5/B_solver/results']:
    for folder,dirs,files in os.walk(root):
        dirs[:]=[d for d in dirs if d not in ('.git','node_modules','__pycache__','traces','rows')]
        for name in files:
            if not name.endswith('.zip'):continue
            p=Path(folder)/name
            try:
                stat=p.stat();key=(name,stat.st_size)
                if key in seen:continue
                seen.add(key)
                with zipfile.ZipFile(p) as z:
                    for item in z.infolist():
                        n=item.filename.lower()
                        if not n.endswith('.json') or not any(k in n for k in ('scene','manifest','plan','seed')) or item.file_size>20_000_000:continue
                        raw=z.read(item);data=json.loads(raw);h=None
                        if isinstance(data,dict) and 'jammers' in data:
                            h=bench.physical_hash(data)
                            if h in fresh:overlap.append([str(p),item.filename,'physical'])
                        found=set(re.findall(r'(?<![a-fA-F0-9])[a-fA-F0-9]{64}(?![a-fA-F0-9])',raw.decode('utf-8-sig')))
                        if found&seeds:overlap.append([str(p),item.filename,'seed'])
                        records.append(dict(zip=str(p),member=item.filename,physical_hash=h))
            except Exception as e:errors.append(dict(path=str(p),error=str(e)))
report=dict(zip_packages=len(seen),members=len(records),overlap=overlap,errors=errors,records=records,limitation='Nested zip members and unavailable official source truths remain unverified.',official_calls=0)
(ROOT/'HISTORICAL_ARCHIVE_EXCLUSION.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
assert not overlap,overlap
print('Historical zip exclusion',len(seen),len(records),'overlap',len(overlap),'errors',len(errors),flush=True)
