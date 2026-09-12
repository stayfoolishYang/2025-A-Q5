import audit_defensive_proposal as audit
import json
from concurrent.futures import ProcessPoolExecutor,as_completed
audit.BASELINE=True;audit.OUT=audit.ROOT/'results/defensive_matched_baseline';audit.OUT.mkdir(exist_ok=True)
if __name__=='__main__':
 states=json.loads((audit.ROOT/'results/posterior_measure/selection.json').read_bytes())
 with ProcessPoolExecutor(max_workers=6) as pool:
  for n,f in enumerate(as_completed([pool.submit(audit.worker,(s,b)) for s in states for b in range(3)]),1):f.result();print('MATCHED_BASELINE',n,36,flush=True)
