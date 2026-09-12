import audit_receive_rb as audit
import json
from concurrent.futures import ProcessPoolExecutor,as_completed
audit.OUT=audit.ROOT/'results/rb64'
if __name__=='__main__':
 states=json.loads((audit.OUT/'selection.json').read_bytes())
 with ProcessPoolExecutor(max_workers=6) as pool:
  for n,f in enumerate(as_completed([pool.submit(audit.worker,(s,b)) for s in states for b in range(3)]),1):
   f.result()
   if n%24==0:print('RB64_BANKS',n,192,flush=True)
