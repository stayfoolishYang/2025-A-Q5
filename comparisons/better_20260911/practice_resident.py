"""One launch, multiple user-started official practice sessions; no UI clicking."""
import csv,json,math,msvcrt,os,queue,re,statistics,subprocess,sys,threading,time
from pathlib import Path
import tkinter as tk
from tkinter import ttk
HERE=Path(__file__).resolve().parent
ROOT=Path('J:/2026B_runs/official_latest')
STATE=ROOT/'resident';STATE.mkdir(parents=True,exist_ok=True)
CODE=r'[A-Z0-9]{4}(?:-[A-Z0-9]{4}){3}'
def save(p,obj):
    tmp=p.with_suffix(p.suffix+'.tmp');tmp.write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding='utf-8');tmp.replace(p)
def parse_ui(s):
    if '队号 202627002054' not in s:return None
    m=re.search(r'问题([34])\s+(演练|正式)\s+测试\s+([^\n]+)',s)
    code=re.search(r'测试案例编码\s+('+CODE+')',s)
    if not m or not code:return None
    total=re.search(r'本次演练测试干扰源数量\s+共\s*(\d+)\s*个',s)
    return dict(problem=int(m[1]),mode=m[2],status=m[3],case=code[1],total=int(total[1]) if total else None)
def snapshot():
    r=subprocess.run(['powershell.exe','-NoProfile','-File',str(HERE/'read_practice_ui.ps1')],capture_output=True,timeout=12,creationflags=subprocess.CREATE_NO_WINDOW)
    if r.returncode:raise RuntimeError('模拟器窗口不可读，请保持模拟器打开')
    d=json.loads(r.stdout.decode('utf-8-sig'));return d
def wire_summary(folder):
    p=folder/'wire.jsonl'
    if not p.exists():return dict(cleared=0,requests=0,normal_exit=False)
    actions=[json.loads(x) for x in p.read_text(encoding='utf-8').splitlines()]
    good=[a for a in actions if a['response'].get('accepted') is True]
    return dict(cleared=len({a['request']['channel'] for a in good if a['path']=='/clear' and a['response'].get('clear_result')=='success'}),
                requests=len(actions),normal_exit=bool(good and good[-1]['path']=='/exit' and good[-1]['response'].get('exit_reason')=='user_exit'))
def statistics_files(rows):
    means={q:statistics.mean([r['score'] for r in rows if r['problem']==q and r['status']=='FULL_CLEAR' and r.get('score') is not None]) for q in (3,4) if any(r['problem']==q and r['status']=='FULL_CLEAR' and r.get('score') is not None for r in rows)}
    columns=['problem','case','variant','status','total','cleared','score','normalized_score','runtime_s','requests','returncode']
    with (STATE/'cases.csv').open('w',newline='',encoding='utf-8-sig') as f:
        w=csv.DictWriter(f,fieldnames=columns,extrasaction='ignore');w.writeheader()
        for r in rows:w.writerow(dict(r,normalized_score=r['score']/means[r['problem']] if r['status']=='FULL_CLEAR' and r.get('score') is not None and means.get(r['problem'],0)>0 else None))
    stats={}
    for q in (3,4):
        g=[r.copy() for r in rows if r['problem']==q];ok=[r for r in g if r['status']=='FULL_CLEAR' and r.get('score') is not None];x=sorted(r['score'] for r in ok)
        def pct(p):
            k=(len(x)-1)*p;i=math.floor(k);return x[i]+(x[min(i+1,len(x)-1)]-x[i])*(k-i)
        mean=statistics.mean(x) if x else None
        normalized=[v/mean for v in x] if mean and mean>0 else []
        stats[q]=dict(attempts=len(g),full=len(ok),failed=sum(r['status']=='FAILED' for r in g),unverified=sum(r['status']=='UNVERIFIED' for r in g),
            mean=mean,median=statistics.median(x) if x else None,std_s_per_source=statistics.stdev(x) if len(x)>1 else None,
            normalization='score / same-problem mean among verified full-clear cases',variance_ddof=1,
            normalized_variance=statistics.variance(normalized) if len(normalized)>1 else None,
            normalized_std=statistics.stdev(normalized) if len(normalized)>1 else None,
            p95=pct(.95) if x else None,minimum=min(x) if x else None,maximum=max(x) if x else None)
    save(STATE/'SUMMARY.json',stats)
    lines=['# 连续官方演练统计','', '仅统计常驻程序接入的场次；均值等指标只针对经官方界面核实全清的场次，失败与未核实数量单列。每题不同随机场景，非同种子配对；小样本P95只作描述。', '', '归一化定义：x_i=虚拟总时间/本局源数，z_i=x_i/本题当前全清样本均值。Q3/Q4分别计算。样本方差=sum((z_i-1)^2)/(n-1)，无量纲；归一化标准差等于变异系数CV。不足2场留空。随着样本增加，归一化基准随本题均值更新；CSV中的normalized_score也同步更新。均值、中位数、P95及极值仍为秒/源。', '', '|问题|接入|全清|失败|未核实|均值|中位数|归一化样本方差|归一化标准差(CV)|P95|最小|最大|','|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
    fmt=lambda x:'—' if x is None else f'{x:.2f}'
    for q,s in stats.items():lines.append(f'|Q{q}|{s["attempts"]}|{s["full"]}|{s["failed"]}|{s["unverified"]}|'+ '|'.join(('—' if s[k] is None else f'{s[k]:.6f}') if k.startswith('normalized_') else fmt(s[k]) for k in ('mean','median','normalized_variance','normalized_std','p95','minimum','maximum'))+'|')
    (STATE/'REPORT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    return stats
class App:
    def __init__(self):
        self.lock=(STATE/'resident.lock').open('a+b');self.lock.seek(0)
        try:msvcrt.locking(self.lock.fileno(),msvcrt.LK_NBLCK,1)
        except OSError:raise SystemExit('常驻程序已在运行，不重复启动')
        self.rows=json.loads((STATE/'sessions.json').read_bytes()) if (STATE/'sessions.json').exists() else []
        self.events=queue.Queue();self.enabled=True;self.closing=False;self.child=None
        self.window=tk.Tk();self.window.title('B题 · 多局演练自动接入');self.window.geometry('760x430')
        ttk.Label(self.window,text='一次启动，连续接入 Q3 D / Q4 R12',font=('Microsoft YaHei',16)).pack(pady=12)
        ttk.Label(self.window,text='在官方模拟器点“开始演练”即可；本窗口自动接入，结束后继续等待。\n仅识别演练，不点击任何开局按钮。请保持模拟器窗口打开。',justify='center').pack()
        self.status=tk.StringVar(value='正在连接界面观察器…');ttk.Label(self.window,textvariable=self.status,wraplength=720).pack(pady=14)
        self.table=ttk.Treeview(self.window,columns=('n','ok','bad','mean','std','p95'),show='tree headings',height=2)
        self.table.heading('#0',text='策略');self.table.column('#0',width=100)
        for k,t in [('n','接入'),('ok','全清'),('bad','失败/未核实'),('mean','均值秒/源'),('std','归一化方差'),('p95','P95秒/源')]:self.table.heading(k,text=t);self.table.column(k,width=95)
        self.table.pack(padx=10,pady=10)
        self.pause=ttk.Button(self.window,text='暂停自动接入',command=self.toggle);self.pause.pack(pady=4)
        ttk.Button(self.window,text='打开统计文件夹',command=lambda:os.startfile(STATE)).pack(pady=4)
        ttk.Label(self.window,text='关闭窗口：当前局完成后退出。模型参数冻结；正式测试不接入。').pack(pady=8)
        self.window.protocol('WM_DELETE_WINDOW',self.close)
        threading.Thread(target=self.loop,daemon=True).start();self.window.after(300,self.refresh)
    def toggle(self):self.enabled=not self.enabled;self.pause.config(text='继续自动接入' if not self.enabled else '暂停自动接入')
    def close(self):self.enabled=False;self.closing=True;self.status.set('正在结束观察；当前局如在运行，将等它完成…')
    def refresh(self):
        while not self.events.empty():
            msg=self.events.get()
            if msg=='QUIT':self.window.destroy();return
            self.status.set(msg)
        s=statistics_files(self.rows)
        for item in self.table.get_children():self.table.delete(item)
        for q,r in s.items():
            fmt=lambda x:'—' if x is None else f'{x:.2f}'
            variance='—' if r['normalized_variance'] is None else f'{r["normalized_variance"]:.6f}'
            self.table.insert('',tk.END,text='Q3 D' if q==3 else 'Q4 R12',values=(r['attempts'],r['full'],f'{r["failed"]}/{r["unverified"]}',fmt(r['mean']),variance,fmt(r['p95'])))
        self.window.after(1500,self.refresh)
    def loop(self):
        seen={r['case'] for r in self.rows};log=None;active=None;finished_at=None
        while True:
            try:
                if self.closing and self.child is None:self.events.put('QUIT');return
                try:
                    snap=snapshot();text=snap['text'];ui=parse_ui(text)
                except Exception:
                    snap=None;text='';ui=None
                if self.child is not None:
                    rc=self.child.poll()
                    if rc is None:self.events.put(f'Q{active["problem"]} {active["case"]} 策略运行中…')
                    else:
                        if finished_at is None:finished_at=time.monotonic()
                        folder=ROOT/f'q{active["problem"]}_{active["case"]}'
                        ended=bool(ui and ui['mode']=='演练' and ui['case']==active['case'] and ui['status']=='测试已结束' and ui['total'] is not None)
                        if ended or time.monotonic()-finished_at>20 or rc!=0:
                            log.close();folder.mkdir(exist_ok=True);active.update(wire_summary(folder));active['returncode']=rc
                            result=json.loads((folder/'result.json').read_bytes()) if (folder/'result.json').exists() else {}
                            active['runtime_s']=result.get('runtime_s');active['total']=ui['total'] if ended else None
                            active['status']='FULL_CLEAR' if ended and rc==0 and active['normal_exit'] and active['cleared']==active['total'] else ('FAILED' if rc!=0 or ended else 'UNVERIFIED')
                            active['score']=result.get('virtual_time_s',0)/active['total'] if active['total'] else None
                            if ended:(folder/'after.txt').write_text(text,encoding='utf-8')
                            save(folder/'resident_verification.json',active);save(STATE/'sessions.json',self.rows)
                            self.events.put(f'本局 {active["status"]}；已恢复等待下一场演练。');self.child=None;active=None;finished_at=None
                elif self.enabled and ui and ui['mode']=='演练' and ui['status']=='等待机器狗进入' and ui['case'] not in seen:
                    if Path(snap['executable']).name!='jammers-simulator-full.exe':raise RuntimeError('窗口进程不匹配')
                    folder=ROOT/f'q{ui["problem"]}_{ui["case"]}'
                    if folder.exists():seen.add(ui['case']);continue
                    before=STATE/(ui['case']+'_before.txt');before.write_text(text,encoding='utf-8')
                    active=dict(problem=ui['problem'],case=ui['case'],variant='D' if ui['problem']==3 else 'R12',status='RUNNING')
                    seen.add(ui['case']);self.rows.append(active);save(STATE/'sessions.json',self.rows)
                    log=(STATE/(ui['case']+'_console.log')).open('w',encoding='utf-8')
                    self.child=subprocess.Popen([sys.executable,str(HERE/'run_latest_practice.py'),'--problem',str(ui['problem']),'--case',ui['case'],'--before',str(before)],stdout=log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
                    self.events.put(f'已自动接入 Q{ui["problem"]} {ui["case"]}')
                elif self.child is None:self.events.put('已暂停自动接入' if not self.enabled else ('模拟器窗口不可读：暂停接入，等待恢复' if snap is None else ('检测到正式测试：不发送请求' if ui and ui['mode']=='正式' else '等待新演练：请在官方模拟器点击 Q3 或 Q4 的“开始演练”')))
            except Exception as e:
                self.events.put('等待界面恢复：'+str(e))
                if self.closing and (self.child is None or self.child.poll() is not None):self.events.put('QUIT');return
            time.sleep(1)
if __name__=='__main__':App().window.mainloop()
