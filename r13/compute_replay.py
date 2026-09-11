"""Fresh-process import/startup and warm strict replay timing; case0 fixed."""
import time
PROCESS_START=time.perf_counter()
import sys,json,gzip,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parent
if len(sys.argv)==1:
    records=[]
    for arm in ['R12','A1','E-H2']:
        raw=subprocess.check_output([sys.executable,__file__,arm],text=True,encoding='utf-8');records.append(json.loads(raw))
    (ROOT/'analysis/COMPUTE_COLD_WARM.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8')
else:
    from run_study import StudySolver,phase_audit,rb,np
    arm=sys.argv[1];loaded=time.perf_counter()-PROCESS_START
    folder=ROOT/'results/development';m=json.loads((folder/'manifest.json').read_bytes());cfg=next(c for c in m['configs'] if c['name']==arm)
    with gzip.open(folder/'core/traces'/f'{arm}_0000.json.gz','rt',encoding='utf-8') as f:tr=json.load(f)
    runs=[]
    for iteration in range(2):
        class Exact(phase_audit.Replay):
            def action(self,path,position=None,channel=None):
                record=self.records[self.index]
                if position is not None:assert np.array_equal(position,record['position'])
                assert rb.digest({str(c):t['hyp'].rng.bit_generator.state for c,t in s.tracks.items() if t.get('hyp') is not None})==record['rng_before']
                return super().action(path,position,channel)
        api=Exact(tr['actions']);s=StudySolver(api,True,'P4','cpu',diagnostic=cfg);start=time.perf_counter();s.run();elapsed=time.perf_counter()-start
        assert api.index==len(tr['actions']) and api.virtual_time==tr['row']['virtual_time_s']
        vals=[e['decision_ms'] for e in s.events if e['kind']=='decision']
        runs.append(dict(iteration=iteration,elapsed_s=elapsed,first_route_ms=s.route_events[0]['route_ms'],first_decision_ms=vals[0],decision_ms=dict(zip(['P50','P95','P99','max'],map(float,np.quantile(vals,[.5,.95,.99,1]))))))
    print(json.dumps(dict(arm=arm,case=0,import_s=loaded,runs=runs,limitation='One fixed case; first run process-cold, second run warm; OS file/Numba disk cache not flushed.',official_calls=0)))
