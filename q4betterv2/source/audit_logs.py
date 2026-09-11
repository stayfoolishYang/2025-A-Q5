"""Recalculate every virtual-time increment from actual official practice request/response logs."""
import csv
import json
import math
from pathlib import Path


def main():
    base=Path(__file__).resolve().parent/'results/official_practice'
    verified=json.loads((base/'ui_verified_counts.json').read_text())
    rows=[]
    for meta in verified:
        result=json.loads((base/meta['file']).read_text())
        actions=[json.loads(s) for s in (base/Path(meta['file']).with_suffix('.jsonl')).read_text().splitlines()]
        position=(0.,0.);channel=1;virtual=0.;seen={};cleared=set();max_error=0.;distance=0.;measures=switches=attempts=0
        entered_ms=exited_ms=None
        for item in actions:
            response=item['response'];request=item['request'];path=item['path']
            if response.get('accepted') is not True:continue
            key=request['request_id']
            if key in seen:
                assert seen[key]==(path,request)
                continue
            seen[key]=(path,request)
            if path=='/enter':entered_ms=response['real_timestamp_ms']
            elif path=='/exit':exited_ms=response['real_timestamp_ms']
            else:
                p=(request['position']['x'],request['position']['y']);travel=math.dist(p,position)
                virtual+=travel/5;distance+=travel;position=p
                if path=='/measure':
                    switch=int(channel!=request['channel']);switches+=switch;measures+=1
                    virtual+=5+switch;channel=request['channel']
                else:
                    attempts+=1;success=response['clear_result']=='success';virtual+=5 if success else 3
                    if success:
                        assert request['channel'] not in cleared
                        cleared.add(request['channel'])
            max_error=max(max_error,abs(virtual-response['virtual_time_s']))
        assert max_error<1e-3 and len(cleared)==result['cleared'] and entered_ms is not None and exited_ms is not None
        rows.append(dict(problem=meta['problem'],case=meta['case'],total=meta['total'],omni=meta['omni'],directional=meta['directional'],
            cleared=len(cleared),clear_rate=len(cleared)/meta['total'],mean_time_per_source_s=result['mean_time_per_source_s'],
            virtual_time_s=result['virtual_time_s'],runtime_s=result['runtime_s'],protocol_runtime_s=(exited_ms-entered_ms)/1000,
            distance_m=distance,measure_count=measures,switch_count=switches,clear_attempts=attempts,
            max_virtual_time_recalculation_error_s=max_error,revision=meta['revision'],evidence='official_practice'))
    with (base/'summary.csv').open('w',newline='',encoding='utf-8-sig') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    print(json.dumps(rows,indent=2))


if __name__=='__main__':main()
