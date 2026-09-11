# Large statistical validation, requested by user

1024 fresh native Q4 scenes x R12/MYOPIC/TERMINAL = 3072 runs. Freeze all three strategies exactly as Phase B (including the now-recognized 2000m soft prior). No outcome-conditioned scene selection or excluded failure cases. No official calls.

Primary: paired mean time/source; two comparisons against R12, 10000 scene bootstrap resamples, simultaneous 97.5% two-sided intervals (Bonferroni for two). Secondary: median, P95, P99, maximum, CVaR0.9, normalized sample variance Var(T/mean(T)), CV, paired wins/ties/losses, discovery time, distance, clear attempts, runtime. Stratify by source count N=10..16 and directional count; report counts, avoid posthoc subgroup adoption. Report full-clear and audit failures explicitly; never average away failed runs. If any missing/failing runs, primary completion claim is withheld and failures shown.

This validates these frozen arms only. Corrected 1800m prior and complete rollout must use separate development and independent final validation. This experiment does not prove general SOTA.
