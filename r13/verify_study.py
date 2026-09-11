"""One meaningful invariance check: exact frozen action replay plus geometry checks."""
from run_study import *
from route_reference import verify

def main():
    verify()
    import runpy
    runpy.run_path(str(ROOT/'scan_credit.py'),run_name='__main__')
    cfg=json.loads((SRC/'configs/q4_known16_tri25_R12.yaml').read_bytes())
    archive=Path('J:/2026B_runs/q4_latest_7228633/cpu519_repeat_20260912')
    for seed in (0,67,261,518):
        with gzip.open(archive/'core/traces'/f'R12_{seed:04d}.json.gz','rt',encoding='utf-8') as f:data=json.load(f)
        class Exact(phase_audit.Replay):
            def action(self,path,position=None,channel=None):
                record=self.records[self.index]
                if position is not None:assert np.array_equal(position,record['position'])
                assert rb.digest({str(c):t['hyp'].rng.bit_generator.state for c,t in s.tracks.items() if t.get('hyp') is not None})==record['rng_before']
                return super().action(path,position,channel)
        api=Exact(data['actions']);s=StudySolver(api,True,'P4','cpu',diagnostic=cfg);s.run()
        assert api.index==len(data['actions']) and api.virtual_time==data['row']['virtual_time_s']
        print('Exact baseline replay',seed,flush=True)
    save(ROOT/'BASELINE_LOOP_VERIFICATION.json',dict(seeds=[0,67,261,518],exact_positions=True,exact_rng=True,exact_final_time=True,official_calls=0))
if __name__=='__main__':main()
