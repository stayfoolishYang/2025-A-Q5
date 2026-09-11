# R14: certified-belief discovery routing

Status: implementation; no advantage established. R13 and R12 remain immutable.
Previous goal turn: preparatory reading, no implementation; this turn starts implementation.

## Required evidence
A. Frozen R12 on fresh development 128 and prediction holdout 256 scenes; compare uniform, geometry-only, geometry+no_signal. Brier, reliability, top1/top3, MRR, scene-clustered paired intervals. Gate: relative top1 lift >=15% or positive MRR improvement with 95% lower bound >0 on independent holdout. Do not tune on holdout.
B. Only after A passes, compare R12, expected-new-count/time, probabilistic-terminal routing on separate development scenes; retain every mandatory node and original full sweep semantics.
C. Top3 candidates plus R12, 32 paired belief worlds, actual R12 continuation to completion, baseline confidence and CVaR0.9 deviation gates. Evaluation truth must never enter planning. Need a complete joint state/noise conditioning audit before claiming faithful rollout.
D. Independent final paired comparison, full-clear and coverage audits, normalized variance, P95/P99/CVaR and compute cost; advantage must be supported independently. Global SOTA requires appropriate external comparator coverage, not just beating R12.

## Corrections established from source
- engine.py:198-206 applies radius and direction before near. Near does not override direction.
- q_cond is conditional on channel existence; q_uncond already includes existence and must not be multiplied again.
- Equal existence priors need not remain equal after different negative histories. Use a public N=10..16 uniform prior and exact finite-channel existence conditioning; report prior sensitivity later as a separate experiment.
- Never obtain labels for unvisited nodes from execution logs alone: counterfactual labels require an evaluation-only oracle. Separate planner inputs and labels.
- R12 completes a node sweep unless legal known16/public completion. It also replans without new discoveries. Short route survival alone is not a causal explanation.
- The finite survival-cost sum measures time to detection OR route exhaustion; retain exhaustion probability. Across-node detection events are correlated.
- Particle approximation is soft only. Exhaustion/degeneracy returns an unavailable prediction, never authorizes removal of nodes.

## Literature checked 2026-09-12
https://arxiv.org/abs/2601.12701 : RPT*, submitted Jan 19 2026; probabilistic terminals, history-dependent expected path cost, Bayesian filtering. Its optimality guarantee does not transfer to our heuristic.
https://arxiv.org/abs/2410.06069 : Provable Methods for Searching with an Imperfect Sensor, submitted Oct 8 2024; movement and sensing costs under a time budget. ICRA venue not established by this abstract page.

Official calls and formal tests prohibited. Reuse frozen benchmark and geometry; no new dependencies.
