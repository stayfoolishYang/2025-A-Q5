import json
from concurrent.futures import ProcessPoolExecutor,as_completed
import audit_posterior_measure as audit
from grid_measure import GridMeasure
GridMeasure.draw=GridMeasure.draw_pivot
audit.OUT=audit.ROOT/'results/posterior_measure_pivot';audit.OUT.mkdir(exist_ok=True)
if __name__=='__main__':
    audit.analytic()
    states=json.loads((audit.ROOT/'results/posterior_measure/selection.json').read_bytes())
    jobs=[dict(s,bank_repeat=r,source_count=512,noise_budgets=[512],noise_repeats=1) for s in states for r in range(3)]
    with ProcessPoolExecutor(max_workers=6) as pool:
        for n,f in enumerate(as_completed([pool.submit(audit.worker,s) for s in jobs]),1):f.result();print('INDEPENDENT_BANKS',n,len(jobs),flush=True)
