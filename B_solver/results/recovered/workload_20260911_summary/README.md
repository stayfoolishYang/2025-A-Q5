# D2 workload refresh: frozen evidence summary

Execution commit: dcb62ac. The final decision is STOP_D2_NO_PARAMETER_SWEEP; retain D1 as the Q4 candidate and MEC as the clearance default.

This round contains 480 full runs on 160 new seeds (development 32 x 3; holdout 128 x 3), plus 6 runs on two previously known counterexamples. All 486 runs achieved full clearance. The four historical reference traces are comparisons, not additional new runs. Official/formal runs: 0.

Start with RESULTS.md and AUDIT.json. CASES.csv and PAIRS.csv provide all case and paired measurements; figures show the full holdout comparison. HOLDOUT_CASE_AUDIT.json and KNOWN_CASE_AUDIT.json explain the selected boundary cases without rerunning the solver. The evidence directory preserves the predeclared plan and test records: 113 algorithm/regression tests and a separate 4 report tests.

Raw scenes, rows, traces, frozen source and historical references are in J:/2026B_experiments/workload_20260911 and in the corresponding 2026B_Q4_Workload_486 audit ZIP under the repository's delivery directory. This mirror alone does not contain raw traces. Existing absolute paths identify provenance; the packaged README describes portable read-only recomputation.

ARTIFACT_MANIFEST.json covers the generated report files. SUMMARY_MANIFEST.json additionally covers the copied case audits, evidence, figures and this README. Neither manifest includes itself. The original report and development gate remain unchanged.
