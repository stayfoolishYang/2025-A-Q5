# Paired value estimator qualification

Latest user scope accepted: sampler compatibility -> paired full R12 value estimator -> qualification on existing2000 oracle states -> uncertainty/baseline gate -> only then fresh end-to-end development and holdout. No new1024 end-to-end batch.

Implemented public-history sampler includes source count10..16, channel existence, positions within1800m, type/direction/range, persistent noise, all past negative/positive/bearing/near observations, failed/successful clears. Every generated world replays every public response exactly or returns unavailable. No evaluated scene seed, coordinates or true N is an input.

Important approximations: known-source location proposals are uniform in clipped polygons followed by compatibility rejection; conditional noise is bounded-grid hit-and-run128steps, without integrating noise-feasibility volume into spatial likelihood. This is a compatible proposal distribution, not a proven calibrated posterior. Failure and unavailability must be reported, never conditioned away. Further qualification may show it unusable.

CRN correction: future noise-grid values are keyed by(world noise seed,grid coordinates), independent of visit order; observed constrained values retained. Initial12world checks passed full historical response replay and future query-order invariance. Larger compatibility and estimator tests remain.

Estimator receives explicit public solver-state projection, public actions and remaining nodes. It reuses verified R12 continuation with only sampled engines. All candidates share each world; solver/particle RNG states copied identically. Candidate set probability top3 plusR12, unchanged. Paired differences, planned looks8/16/32/64, eliminate when model t-UCB<=0, accept only at final look with LCB>0 and empirical CVaR0.9(candidate-minus-base)<=0. Bonferroni3candidates*4looks; no exact statistical or safety guarantee under model bias/non-normality claimed. DefaultR12 on unavailable samples/continuations.

Still required: per-state sign accuracy with ties separate; deviation precision/recall; accepted oracle gain and false-positive loss/CVaR; regret against candidate set; compute and sampler failure rates. Group by scene in resampling. Existing oracle aggregate results already inspected, so internal qualification is not a fresh final holdout. Do not select gates using its validation labels. Final independent scenes required before adoption. Candidate generation still leaves27%-46% of oracle improvement uncaptured; it is not proven an irrelevant bottleneck.
