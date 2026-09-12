"""Score completed predictions against oracle only after their decisions are frozen."""
import json,gzip,collections,time
import numpy as np
import pandas as pd
from collect import ROOT
OUT=ROOT/'analysis/tie_rollout200';OUT.mkdir(exist_ok=True);SOURCE=ROOT/'results/tie_rollout200'
def main():
 selection=json.loads((SOURCE/'selection.json').read_bytes());rows=[];actions=[]
 for s in selection:
  p=SOURCE/f'{s["id"]:04d}_{s["step"]:02d}.json'
  if not p.exists():continue
  r=json.loads(p.read_bytes())
  if not r.get('complete'):continue
  with gzip.open(ROOT/'results/value_oracle/oracle'/f'{s["id"]:04d}_{s["step"]:02d}.json.gz','rt') as f:o=json.load(f)
  costs={b['index']:b['cost'] for b in o['branches']};sel=r.get('selected',0);delta=costs[0]-costs[sel]
  row=dict(id=s['id'],step=s['step'],group=s['sample_group'],status=r['status'],selected=sel,deviate=sel!=0,oracle_gain=delta,candidates=len(r['candidates']),worlds=len(r['paired']),seconds=r.get('seconds'),candidate_opportunity=max(costs[0]-costs[c] for c in r['candidates'])>0,reason=r.get('reason',''))
  rows.append(row)
  for key,v in r.get('estimates',{}).items():
   c=int(key);actions.append(dict(id=s['id'],step=s['step'],candidate=c,oracle_delta=costs[0]-costs[c],**v))
 df=pd.DataFrame(rows);df.to_csv(OUT/'states.csv',index=False);pd.DataFrame(actions).to_csv(OUT/'candidate_estimates.csv',index=False)
 dev=df[df.deviate] if len(df) else df
 summary=dict(planned=200,completed=len(df),statuses=dict(collections.Counter(df.status)) if len(df) else {},deviations=len(dev),deviation_coverage=len(dev)/200,precision=float((dev.oracle_gain>0).mean()) if len(dev) else None,mean_oracle_gain_on_deviations=float(dev.oracle_gain.mean()) if len(dev) else None,official_calls=0,meaning='oracle single-decision continuation seconds, not end-to-end deployment gain')
 if len(dev):
  loss=np.maximum(0,-dev.oracle_gain.to_numpy());summary['wrong_deviation_mean_loss']=float((-dev.loc[dev.oracle_gain<0,'oracle_gain']).mean()) if (dev.oracle_gain<0).any() else 0.
  from paired_value_estimator import tail_mean
  summary['deviation_loss_cvar90']=tail_mean(loss)
 (OUT/'summary.json').write_text(json.dumps(summary,indent=2))
 (OUT/'状态与结果.md').write_text('# Tie-aware + full R12 rollout 校准\n\n'+f'完成 {len(df)}/200 状态。状态计数：{summary["statuses"]}。\n\n'+f'门控偏离 {len(dev)} 次；偏离 precision：{summary["precision"]}。样本不足时不作稳定收益结论。\n\n'+'epsilon=0.2 pp，最多8候选，超限整状态回退；16个同世界配对续跑。置信界为有限样本 t 近似，经验 CVaR 不是风险保证。\n\n'+'真实 oracle 成本仅在预测文件完成后用于此评分。当前为分层开发校准，尚非独立验证，也非部署整局收益。正式测试和官方调用为0。\n',encoding='utf-8')
 print(json.dumps(summary,indent=2))
if __name__=='__main__':main()
