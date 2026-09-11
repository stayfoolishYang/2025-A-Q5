# Phase C status and model corrections

Phase B development: all384 complete and audited. R12 mean564.339s/source, MYOPIC808.458, TERMINAL611.951. No production adoption. Independent1024-scene validation requested by user is running for all three frozen arms.

Geometric prior defect discovered during rollout preparation: belief v1/v2/fast uses a2000m location disk, whereas frozen geometry.disk and particles use1800m. Earlier results describe the actual2000m-prior implementation, not exact adherence to the proposed target-domain prior. Do not edit their frozen source or relabel results. Correct prior in the separate Phase C version; independent final validation still needed.

conditional_noise.py provides a planning noise model whose repeated measurements persist and whose rounded bearings match retained history. It uses a bounded independent grid prior conditioned through linear constraints, with128 hit-and-run steps. This is not the recovered hash-seed posterior: no claim of exact distribution, mixing convergence, or exact Bayes spatial likelihood weighting.80 rounded-history matches and16 repeat checks passed. Full rollout still needs source-world sampling, state-only copying, R12-to-completion execution, confidence/CVaR gates, model calibration and independent advantage evidence.

Previous goal turn: progress (prediction gate, policy implementation and paired batch). Current turn: progress (completed Phase B, expanded frozen statistical experiment, conditional persistent-noise component). Goal remains active; no SOTA claim.
