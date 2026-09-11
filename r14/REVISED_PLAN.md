# Revised research plan following user review

3072/3072 prior validation complete, no audit or clearing failures. TERMINAL mean586.238 vs R12 548.427s/source; paired +37.811,97.5% CI[33.891,41.605]. Stop further batches of unconstrained TERMINAL and MYOPIC.

P0 scan audit: P4 does not interrupt on ordinary direction. Only known16/public completion exits a sweep early; near can immediately clear at the same point. All unknown channels at actual discovery decision snapshots share the same negative-location history under frozen full sweeps. Consequently their probabilities tie under the symmetric prior. Belief-based ordering among these channels supplies no differentiating information. Unknown-first may help the final known16 sweep, but is a separate scheduling rule and changes ending channel; do not claim general zero-cost improvement. No P3 probability-channel experiment planned without contrary evidence.

P1/P2: rank probability_any among baseline route plus candidate-first/frozen-R12-tail routes with excess planned travel/5 <=B. B=0 (strict tolerance1e-8m),5,10,20s; fixed probability margin0.05, no margin sweep. Select budget once on a fresh128-scene development set; evaluate winner on new independent scenes. Preserve R12 on tied probabilities. No negative budget credit carried forward. Report per-decision and cumulative positive planned-detour expenditure.

Important limitation: one replanning-state suffix budget is NOT a whole-game travel bound. Repeated replanning and localization alter realized routes; B=0 cannot certify whole-game non-regression. Do not assert this prevents28km paths. Keep all mandatory nodes and evaluate actual tail risk.

Prior correction: compare2000m and1800m on a fresh128-scene R12 prediction set first; no3072-run rerun of stopped planners. Rank metrics, calibration, probability margin. No training or parameter fitting on old holdouts. Full belief-filtered R12 rollout remains required afterwards.

Citations:2409.04653 is budgeted stochastic orienteering with chance constraints.2010.09832 is Dream and Search to Control (latent-space MBRL), not the classic frozen-base rollout source.2304.13033 is SmartChoices, not SPIBB. Use verified Bertsekas-Castanon1999 and Laroche et al.ICML2019 for those respective claims. No transferred guarantee asserted.
