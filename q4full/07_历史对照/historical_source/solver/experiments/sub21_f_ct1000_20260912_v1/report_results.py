"""Frozen two-policy fresh1000 comparison; no post-result policy selection."""
import csv,gzip,json
import numpy as np

def report():
    from run_pilot import OUT,read,rb,SIM,fingerprints
    from ctspn import move_us
    from geometry import is_certified_clear_point
    m=read(OUT/'manifest.json');assert fingerprints(SIM)==m['source_hashes']
    rows=[read(p) for p in sorted((OUT/'core/rows').glob('*.json'))];assert len(rows)==2000
    by={(r['variant'],r['id']):r for r in rows};assert len(by)==2000
    checks=[];events=[];counter_events=0
    for rec in m['records']:
        i=rec['id'];assert rb.digest(read(OUT/rec['file']))==rec['scene_hash']
        for v in 'AB':
            r=by[v,i]
            assert r['scene_hash']==rec['scene_hash'] and r['source_hash']==rb.digest(m['source_hashes'])
            assert r['config_hash']==rb.digest(next(c for c in m['configs'] if c['name']==v))
            with gzip.open(OUT/f'core/traces/{v}_{i:04}.json.gz','rt',encoding='utf-8') as f:t=json.load(f)
            assert t['row']==r
            errors=[];ce=read(OUT/f'ct_events/{v}_{i:04}.json');actions=t['actions']
            if r['run_status']!='FULL_CLEAR' or not r['audit_passed']:errors.append('run_or_base_audit')
            if ce['pending_bridge']:errors.append('unconsumed_bridge')
            for e in ce['events']:
                p=e['action']['position'];j0=move_us(e['start'],e['z'])+(0 if p is None else move_us(e['z'],p));j=move_us(e['start'],e['q'])+(0 if p is None else move_us(e['q'],p))
                if (j0,j)!=(e['baseline_bridge_us'],e['candidate_bridge_us']) or j>j0 or j0-j!=e['saving_us']:errors.append('event_ledger')
                if not is_certified_clear_point(e['polygon'],e['q'],19.999):errors.append('unsafe_clear_point')
                if not e['bridge_consumed'] or not e['coalescence_prestate_pass']:errors.append('coalescence')
                k=next((k for k,a in enumerate(actions) if a['path']=='/clear' and a['channel']==e['channel'] and a['position']==e['q']),None)
                if k is None:errors.append('missing_clear');continue
                if actions[k]['response'].get('clear_result')!='success':errors.append('ct_clear_failed')
                if e['adopted']:
                    if not j<j0:errors.append('adopted_without_gain')
                    if k+1>=len(actions):errors.append('missing_bridge');continue
                    b=actions[k+1]
                    if e['action']!=dict(path=b['path'],position=b['position'],channel=b['channel']):errors.append('bridge_request')
                    if b.get('decision_state')!=e['oracle']['pre_bridge_state'] or b.get('rng_before')!=e['oracle']['pre_bridge_rng']:errors.append('bridge_state_rng')
                events.append(dict(id=i,variant=v,channel=e['channel'],adopted=e['adopted'],saving_us=e['saving_us'],planning_wall_s=e['total_planning_wall_s']+e.get('bridge_validation_s',0)))
            for target in t['targets']:
                for e in target.get('certified_clearance_events',[]):
                    if not e['success'] or not is_certified_clear_point(e['polygon'],e['point'],19.999):errors.append('certified_clearance_event')
            if v=='B':
                lookup={(a['channel'],a['response']['virtual_time_s']):a for a in actions if a['path']=='/measure' and a['response'].get('accepted')}
                for target in t['targets']:
                    streak=0
                    for e in target['failure_counter_events']:
                        a=lookup[target['channel'],e['time_s']]
                        if a['response']['measure_result']!=e['result'] or (a['stage']=='discovery')!=(e['purpose']=='discovery') or e['before']!=streak:errors.append('counter_context')
                        if e['result'] in ('direction','near'):streak=0
                        elif e['result']=='no_signal' and a['stage']!='discovery':streak+=1
                        if e['after']!=streak:errors.append('counter_value')
                        counter_events+=1
            checks.append(dict(id=i,variant=v,passed=not errors,errors=sorted(set(errors)),ct_events=len(ce['events'])))
        if i%100==99:print('Audited',i+1,'paired scenes',flush=True)
    def stats(group):
        x=np.array([r['mean_time_per_source'] for r in group]);tail=max(1,int(np.ceil(.05*len(x))))
        return dict(n=len(group),mean=float(x.mean()),P50=float(np.quantile(x,.5)),P95=float(np.quantile(x,.95)),P99=float(np.quantile(x,.99)),worst=float(x.max()),slowest5pct_mean=float(np.sort(x)[-tail:].mean()),game_mean=float(np.mean([r['virtual_time_s'] for r in group])),full=sum(r['run_status']=='FULL_CLEAR' for r in group),audited=sum(r['audit_passed'] for r in group),failed_clear_attempts=sum(r['failed_clears'] for r in group),failed_clear_games=sum(r['failed_clears']>0 for r in group),fallback_count=sum(r['fallback_count'] for r in group),runtime_mean=float(np.mean([r['runtime_s'] for r in group])),runtime_max=max(r['runtime_s'] for r in group))
    pairs=[]
    for i in range(1000):
        a,b=by['A',i],by['B',i];pairs.append(dict(id=i,N=a['total'],A_s_per_source=a['mean_time_per_source'],B_s_per_source=b['mean_time_per_source'],delta_s_per_source=b['mean_time_per_source']-a['mean_time_per_source'],delta_game_s=b['virtual_time_s']-a['virtual_time_s'],A_failed_clears=a['failed_clears'],B_failed_clears=b['failed_clears']))
    def compare(group):
        d=np.array([p['delta_s_per_source'] for p in group]);loss=d[d>1e-9]
        return dict(mean_delta=float(d.mean()),mean_game_delta=float(np.mean([p['delta_game_s'] for p in group])),wins=int(sum(d<-1e-9)),ties=int(sum(abs(d)<=1e-9)),losses=int(sum(d>1e-9)),loss_mean=float(loss.mean()) if len(loss) else 0,loss_over10=int(sum(d>10)),loss_over30=int(sum(d>30)),loss_over60=int(sum(d>60)),worst=max(group,key=lambda p:p['delta_s_per_source']),best=min(group,key=lambda p:p['delta_s_per_source']))
    passed=all(c['passed'] for c in checks)
    summary=dict(status='PASS' if passed else 'FAIL',full_sample_metrics_valid=passed,variants={v:stats([r for r in rows if r['variant']==v]) for v in 'AB'},comparison=compare(pairs),strata={str(n):dict(variants={v:stats([r for r in rows if r['variant']==v and r['total']==n]) for v in 'AB'},comparison=compare([p for p in pairs if p['N']==n])) for n in sorted({r['total'] for r in rows})},checks_passed=sum(c['passed'] for c in checks),ct_events=len(events),ct_adopted=sum(e['adopted'] for e in events),failure_counter_events_checked=counter_events,execution_backend='LOCAL_DEV',execution_purpose='FRAMEWORK_INTEGRATION',production_eligible=False)
    rb.save(OUT/'SUMMARY.json',summary);rb.save(OUT/'CHECKS.json',checks)
    for name,data in [('cases',rows),('pairs',pairs),('worst_regressions',sorted(pairs,key=lambda p:p['delta_s_per_source'],reverse=True)[:30]),('ct_events',events)]:
        keys=list(dict.fromkeys(k for r in data for k in r))
        with (OUT/f'{name}.csv').open('w',encoding='utf-8-sig',newline='') as f:w=csv.DictWriter(f,keys);w.writeheader();w.writerows(data)
    text='# 新1000场景：25+R12+CT 对比 21+R12+F+CT\n\n'
    text+='A=25点+R12+CT；B=21点+R12+F+CT。两组各1000次，共2000次。连续固定新种子、相同场景配对，无结果筛选。配置与上一批对应D/F组一致，CT和21点坐标逐字节保留。\n\n'
    text+=f'验证状态：{summary["status"]}。完整逐次检查通过{summary["checks_passed"]}/2000。\n\n|指标|A 25+R12+CT|B 21+R12+F+CT|\n|---|---:|---:|\n'
    for k in ['mean','P50','P95','P99','slowest5pct_mean','worst','game_mean','full','audited','failed_clear_attempts','failed_clear_games','fallback_count','runtime_mean','runtime_max']:
        text+=f"|{k}|{summary['variants']['A'][k]:.3f}|{summary['variants']['B'][k]:.3f}|\n"
    c=summary['comparison'];text+=f"\n候选B减基线A：平均{c['mean_delta']:.6f}秒/源，每局{c['mean_game_delta']:.6f}秒；胜/平/负={c['wins']}/{c['ties']}/{c['losses']}。退步案例平均慢{c['loss_mean']:.3f}秒/源；慢超过10/30/60秒/源分别{c['loss_over10']}/{c['loss_over30']}/{c['loss_over60']}例。最坏：{json.dumps(c['worst'],ensure_ascii=False)}。\n"
    text+='\n|源数|场景数|A平均秒/源|B平均秒/源|B-A|胜/平/负|\n|---|---:|---:|---:|---:|---|\n'
    for n,g in summary['strata'].items():
        a,b=g['variants']['A'],g['variants']['B'];c=g['comparison'];text+=f"|{n}|{a['n']}|{a['mean']:.3f}|{b['mean']:.3f}|{c['mean_delta']:.3f}|{c['wins']}/{c['ties']}/{c['losses']}|\n"
    text+=f'\n## 证据和口径\n\n检查{len(events)}个CT事件，其中采用{summary["ct_adopted"]}个；覆盖安全清除点、整数微秒费用、实际下一动作及预期决策/RNG状态。B组{counter_events}条失败计数事件按实际动作/阶段重建。场景、配置、源文件哈希以及轨迹/结果行逐一匹配。\n\n'
    text+='每源时间指每局总虚拟时间除以该局源数，跨1000局等权平均；P95/P99同一指标的跨局分位数，不是单个源完成时刻分位数。slowest5pct_mean为最慢50局均值。runtime为本地真实计算秒数，受8进程并行负载影响。全清除不代表每次尝试都成功；中途失败次数另列。\n\n'
    text+='本轮新1000场景与已有本地结果manifest中的种子/场景哈希无重合，未归档历史数据不在检查范围。practice-gen-v1本地生成器证据，不是官方隐藏样本；LOCAL_DEV / FRAMEWORK_INTEGRATION / production_eligible=false。不重新审计用户覆盖证明，不更改默认或GitHub。\n\n'
    text+='复现：run_pilot.py --report重建汇总；不带参数补跑缺失结果。输入场景scenes/，配置/哈希manifest.json，源frozen_source.zip，真实动作core/traces/，CT事件ct_events/，逐例pairs.csv，最严重退步worst_regressions.csv。\n'
    (OUT/'REPORT.md').write_text(text,encoding='utf-8')
    print(json.dumps({k:v for k,v in summary.items() if k!='strata'},ensure_ascii=False),flush=True)

if __name__=='__main__':report()
