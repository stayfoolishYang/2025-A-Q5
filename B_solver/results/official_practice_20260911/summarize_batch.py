"""Read-only statistics and independent timing audit of official PRACTICE logs."""
import csv
import hashlib
import json
import math
from pathlib import Path
import re
import numpy as np

ROOT = Path(__file__).resolve().parent
rows = []
for path in sorted(ROOT.glob('q[34]_*.json')):
    result = json.loads(path.read_text(encoding='utf-8'))
    ui = path.with_name(path.stem+'_ui.txt')
    if not ui.exists():
        continue
    text = ui.read_text(encoding='utf-8')
    counts = re.search(r'共(\d+)个，\s*全向(\d+)个，\s*定向(\d+)个',text)
    assert counts and '测试已结束' in text and path.stem[3:] in text
    total,omni,directional = map(int,counts.groups())
    actions = [json.loads(s) for s in path.with_suffix('.jsonl').read_text().splitlines()]
    position=(0.,0.); channel=1; virtual=0.; distance=0.; measures=switches=attempts=0
    seen={}; cleared=set(); errors=[]; max_error=0.; first_hits={}
    for item in actions:
        request,response,endpoint=item['request'],item['response'],item['path']
        if response.get('accepted') is not True:
            errors.append(response); continue
        key=request['request_id']
        if key in seen:
            assert seen[key]==(endpoint,request); continue
        seen[key]=(endpoint,request)
        if endpoint in ('/measure','/clear'):
            p=(request['position']['x'],request['position']['y'])
            travel=math.dist(position,p); distance+=travel; virtual+=travel/5; position=p
            if endpoint=='/measure':
                switch=int(channel!=request['channel']); switches+=switch; measures+=1
                channel=request['channel']; virtual+=5+switch
                if response['measure_result']!='no_signal': first_hits.setdefault(channel,response['virtual_time_s'])
            else:
                attempts+=1; success=response['clear_result']=='success'; virtual+=5 if success else 3
                if success: cleared.add(request['channel'])
        max_error=max(max_error,abs(virtual-response['virtual_time_s']))
    assert max_error<.001 and len(cleared)==result['cleared'] and total==omni+directional
    assert actions[-1]['path']=='/exit' and actions[-1]['response'].get('accepted') is True
    rows.append(dict(problem=int(path.stem[1]),case=path.stem[3:],total=total,omni=omni,directional=directional,
                     cleared=len(cleared),full_clear=len(cleared)==total,seconds_per_source=virtual/total,
                     virtual_time_s=virtual,runtime_s=result['runtime_s'],distance_m=distance,
                     measurements=measures,channel_switches=switches,clear_attempts=attempts,
                     optical_fallbacks=result['optical_fallbacks'],certified_clears=result['certified_clears'],
                     last_source_first_detection_s=max(first_hits.values()),
                     max_time_audit_error_s=max_error,protocol_error_count=len(errors)))
with (ROOT/'summary.csv').open('w',newline='',encoding='utf-8-sig') as stream:
    if rows:
        writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
statistics={}
for problem in (3,4):
    selected=[r for r in rows if r['problem']==problem]
    if not selected: continue
    values=np.array([r['seconds_per_source'] for r in selected])
    rng=np.random.default_rng(20260911+problem)
    bootstrap=rng.choice(values,(10000,len(values)),replace=True).mean(axis=1)
    statistics[str(problem)]=dict(cases=len(values),full_clear_cases=sum(r['full_clear'] for r in selected),
        sources=sum(r['total'] for r in selected),cleared=sum(r['cleared'] for r in selected),
        mean=float(values.mean()),median=float(np.median(values)),
        sample_std=float(values.std(ddof=1)) if len(values)>1 else None,
        p90=float(np.quantile(values,.9)),p95=float(np.quantile(values,.95)),
        minimum=float(values.min()),maximum=float(values.max()),
        mean_bootstrap95=np.quantile(bootstrap,[.025,.975]).tolist(),
        optical_fallbacks=sum(r['optical_fallbacks'] for r in selected),
        protocol_errors=sum(r['protocol_error_count'] for r in selected))
report=dict(statistics=statistics,formal_test_starts=0,
            inference_limit='Case-generated sample; bootstrap assumes representative independent cases, not verified. No paired baseline or causal comparison.',
            completed_cases=len(rows),planned_cases=50)
(ROOT/'statistics.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(report,ensure_ascii=False))
