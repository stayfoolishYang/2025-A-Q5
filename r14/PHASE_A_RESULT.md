# Phase A result

384 frozen fresh scenes completed (128 development, 256 independent holdout). All full clear and audited; passive collector also matched original R12 physical actions on four prespecified cases. No official interface calls.

Holdout, equal weight per scene:
- R12 next-node hit: 0.2869935; belief top-node hit: 0.5811139 (+102.483% relative).
- MRR: distance 0.4279964, belief 0.6335721; paired improvement 0.2055757, bootstrap 95% CI [0.1882033, 0.2223967].
- Brier: geometry-only 0.2392606, geometry + no_signal 0.1581691.
- Top3: geometry-only 0.6834036, belief 0.6771903. Belief does not dominate every ranking metric.
- No unavailable posterior fallbacks observed.

Both preregistered cohorts pass prediction gate. This is counterfactual node prediction under R12 visitation states, not a closed-loop speedup and not SOTA evidence. Phase B starts on separate fresh scenes.

Evaluation implementation was accelerated with deterministic detection/mass caching. Fifty predictions were bitwise equal to the reference, and all saved metrics on two additional scenes were identical. Existing reference results retained; remaining results used the cached implementation. EVALUATION_CACHE_RESUME.json records split and hashes. All 384 evaluated.

Phase B benchmark caveat: the legacy wrapper labels known16_enabled by hardcoded variant names. In new arms that display field is not authoritative; the frozen configuration finish_after_public_max_known is authoritative. Execution and coverage audits read configuration. Preserve raw files, derive corrected descriptive metadata in the analysis rather than altering the source benchmark.
