"""Cross-check saved official UI totals against accepted unique clear actions."""
import json,re
from pathlib import Path
root=Path('J:/2026B_runs/official_latest')
rows=[]
for name in ('q3_GNE4-NMEN-V3JY-FZAX','q4_RG5Z-GCHN-CSK9-7N8X'):
    p=root/name;r=json.loads((p/'result.json').read_bytes())
    ui=(p/'after.txt').read_text(encoding='utf-8')
    assert r['case'] in ui and f'问题{r["problem"]}\n演练\n测试\n测试已结束' in ui
    n=int(re.search(r'共(\d+)个',ui)[1])
    actions=[json.loads(l) for l in (p/'wire.jsonl').read_text(encoding='utf-8').splitlines()]
    assert actions[0]['path']=='/enter' and actions[-1]['path']=='/exit'
    assert all(a['response'].get('accepted') is True for a in actions)
    assert len({a['request']['request_id'] for a in actions})==len(actions)
    cleared={a['request']['channel'] for a in actions if a['path']=='/clear' and a['response'].get('clear_result')=='success'}
    assert len(cleared)==n==r['cleared']
    assert actions[-1]['response']['exit_reason']=='user_exit'
    assert actions[-1]['response']['virtual_time_s']==r['virtual_time_s']
    audit=dict(case=r['case'],problem=r['problem'],variant=r['variant'],official_practice=True,full_clear_verified=True,
               official_total=n,unique_cleared=len(cleared),requests=len(actions),seconds_per_source=r['virtual_time_s']/n,
               wall_runtime_s=r['runtime_s'],source_of_total='after.txt official UI',formal_tests=0)
    (p/'verification.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2),encoding='utf-8');rows.append(audit)
text='# 官方新版接入故障排查与验证\n\n等待机器狗进入时没有Python策略进程，也没有新版请求日志；点击模拟器演练按钮不会自动启动外部策略。此前仅完成了入口准备。\n\n另修复启动器对J盘exFAT两秒时间取整的误判：界面证据mtime可能略晚于当前时间，允许最多2秒取整误差，仍保留120秒新鲜度上限和演练/问题/案例/队号检查。策略未修改。\n\n'
text+='|问题/策略|案例|全清|虚拟秒/源|程序运行秒|\n|---|---|---:|---:|---:|\n'
for r in rows:text+=f'|Q{r["problem"]} {r["variant"]}|{r["case"]}|{r["unique_cleared"]}/{r["official_total"]}|{r["seconds_per_source"]:.2f}|{r["wall_runtime_s"]:.2f}|\n'
text+='\n均核对官方结束界面与HTTP逐请求日志，正常退出，正式测试0次。每题仅一次接入验证，不用来推断统计性能。后续每次开启新演练，仍须启动一次客户端；没有安装自动常驻服务。\n'
(root/'INTEGRATION_VERIFIED.md').write_text(text,encoding='utf-8')
print(json.dumps(rows,ensure_ascii=False))
