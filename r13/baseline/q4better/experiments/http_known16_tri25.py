"""HTTP integration of frozen scenes; verify listener ownership before every enter."""
import argparse
import gzip
import json
from pathlib import Path
import subprocess
import sys
import time

BASE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(BASE))
import simulator
import known16_tri25_benchmark as bench


def main():
    p=argparse.ArgumentParser();p.add_argument('--sim-root',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--server-pid',type=int,required=True)
    p.add_argument('--control-port',type=int,default=32027);p.add_argument('--ids',type=int,nargs='+',default=[0,1])
    args=p.parse_args();out=args.output.resolve();sim=args.sim_root.resolve()
    sys.path.insert(0,str(sim));from client import ControlClient
    control_url=f'http://127.0.0.1:{args.control_port}'; control=ControlClient(control_url)
    original=simulator.Client
    proofs=[]
    class OwnedClient(original):
        def action(self,path,position=None,channel=None):
            if path=='/enter':
                ps=f"$p = Get-CimInstance Win32_Process -Filter 'ProcessId = {args.server_pid}'; $n = Get-NetTCPConnection -State Listen -LocalPort {args.control_port-1}; @{{pid=$p.ProcessId; command=$p.CommandLine; owners=@($n.OwningProcess)}} | ConvertTo-Json -Compress"
                proof=json.loads(subprocess.check_output(['powershell','-NoProfile','-Command',ps],encoding='utf-8'))
                assert proof['pid']==args.server_pid and proof['owners']==[args.server_pid], proof
                assert str(sim/'start.py').casefold() in proof['command'].casefold(), proof
                proofs.append(proof)
                bench.rb.save(out/'http/ownership.json',proofs)
            return super().action(path,position,channel)
    simulator.Client=OwnedClient
    comparisons=[]
    for index in args.ids:
        for v in bench.VARIANTS:
            deadline=time.monotonic()+15
            while control.status().get('closing_listener'):
                if time.monotonic()>deadline: raise TimeoutError('Prior listener did not close')
                time.sleep(.05)
            row=bench.run_case((out,sim,index,v,control_url))
            print(json.dumps(row),flush=True)
            with gzip.open(out/'core/traces'/f'{v}_{index:04d}.json.gz','rt',encoding='utf-8') as f:core=json.load(f)
            with gzip.open(out/'http/traces'/f'{v}_{index:04d}.json.gz','rt',encoding='utf-8') as f:http=json.load(f)
            a,b=bench.canonical_actions(core),bench.canonical_actions(http)
            # Exact physical fields, RNG snapshots, decisions and virtual time. Enter transport metadata separately kept.
            keys=('measure_result','clear_result','svd_deg','accepted','virtual_time_s','exit_reason')
            for actions in (a,b):
                for action in actions: action['response']={k:v for k,v in action['response'].items() if k in keys}
            result=dict(id=index,variant=v,core_http_physical_rng_equal=a==b,
                        full=row['run_status']=='FULL_CLEAR',audit_passed=row['audit_passed'],
                        virtual_time_s=row['virtual_time_s'],action_count=len(b))
            comparisons.append(result);bench.rb.save(out/'http/comparison.json',comparisons)
            assert all(result[k] for k in ('core_http_physical_rng_equal','full','audit_passed')), result

if __name__=='__main__':main()
