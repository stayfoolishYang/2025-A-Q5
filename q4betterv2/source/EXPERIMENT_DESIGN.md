# TSPN predeclared experiment design
Baseline: original R12 D1/P4, certified25, refresh_after_localize, legacy channel order, known16, grid_v1. F and all P/CDR/RX innovations OFF. Only selected polygon certified-clear destination changes. Near-certified clears retain current location.

Phase A/B/C: official and engine rules, conditional hard geometry proofs, and 40-case historical opportunity before policy execution. A read-only instrumented baseline is archived as opportunity_baseline; final code OFF is rerun against the same historical canonical actions after code freeze.

Development: same 40 USED DEVELOPMENT CASES from P2 archive (8 CDR +32 prior P), A/B/C paired. No fitted weights or policy tuning. Development acceptance requires full clearance and hard audits on all cases; mean T/N improvement at least 0.1 s/source; mean movement reduction at least 1 m/case; no per-case increase in failed clear; aggregate diagnostic and optical time no greater; P95/P99/slowest5 no greater (strict conservative interpretation of no serious tail deterioration); average optimizer under 100 ms/clear and maximum under 1 s/clear. Reject unsafe/hidden-truth/certificate/termination problems immediately.

If both variants pass, choose larger physical mean T/N gain; if their means differ less than 0.1 s/source choose simpler MEC. Freeze source and config before generating fresh128. If development fails, stop without fresh scenes or tuning.

Fresh128: deterministic new strict mixed scenes, N=10+i%7; reject duplicated physical and geometry hashes from all locally archived scenes. One frozen A versus chosen B/C; same sources, noise field and engine. Local development/integration evidence only, production_eligible=false. Accept only all128 full and hard-audit PASS; mean improvement >=0.1 s/source and movement >=1 m/case; P95/P99/slowest5 and N16 mean nonincreasing; no per-case added failed clears; average improvement still positive after excluding three greatest winners. No fresh tuning. Numerical tie threshold1e-9 s.

Numerics: physical radius20 m, preserve R12's operational19.999 m. MEC inner disk r=19.999-rho. EXACT is vertex-disk intersection, numerical optimizer is a candidate generator with independent exact-binary-rational vertex safety and local two-leg checks. Numeric gap bounds distinguish feasible savings from proven exact optimum; no coarse grid. Fallback EXACT to MEC to original center. Cases and failed runs are retained. Slowest5 means five slowest cases, not five percent. Quantiles NumPy linear.

Execution: CPU four isolated workers, each numeric BLAS thread1. Physical time from actual engine integer microseconds; optimizer wall and CPU measured separately. No HTTP/server/production claim. No default source change and no GitHub push.
