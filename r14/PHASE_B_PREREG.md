# Phase B preregistration

Phase A passed on 128 development + 256 independent holdout scenes (PREDICTION_GATE.json). No outcomes from those scenes will select Phase B parameters.

Freeze 128 fresh native scenes, unconditioned by outcomes, namespace R14-ROUTING-v1. Compare R12, MYOPIC, TERMINAL. Same source/particle count/random initialization. Only replace discovery destination when frozen R12 scheduler already chooses discovery. Full sweep, channel order, all mandatory nodes, known16 legal release, active localization and MEC unchanged.

MYOPIC maximizes expected_new/(travel/5+full sweep seconds). TERMINAL enumerates every first node plus original R12 route; each suffix uses frozen R12 routing; minimizes correlated expected cost until first discovery-node sweep OR exhaustion. Survival computed from shared latent detection-pattern histograms and exact existence mixture. Known-source effects, near-clear time and future localization are outside this surrogate, explicitly requiring Phase C validation. No optimality claim. No tuning of particle prior, coefficients or gate.

Measure paired total time/source, full clear, audits, normalized variance, CVaR0.9, P95/P99, maximum, discovery time, real runtime. Development selects direction for complete rollout; it does not authorize production adoption. Final independent advantage remains required.
