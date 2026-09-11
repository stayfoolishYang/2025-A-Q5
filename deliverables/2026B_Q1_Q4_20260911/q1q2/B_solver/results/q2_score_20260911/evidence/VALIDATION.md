# Validation record

Seven focused unittest checks passed before the full experiment (0.178 seconds reported by the test runner). Command: python -B -m unittest discover -s B_solver/tests -p test_q2_score_audit.py -v. Subsequent pre-freeze edits affected evidence counters, frozen-copy assertions, and documentation only. All 213 candidates then completed using the frozen execution code.

The main experiment performed 834518 posterior constructions, separate from the independent two-pass calipers diagnostic (6390 old-scenario reconstructions). The test fixtures are not included in either count. No full solver, simulator instance, official endpoint, or formal test was run.

The report reader verified all 213 candidate records and frozen SHA256 values. The final local report additionally checked the live sources with --check-live-sources. Its default frozen-only reader was separately checked with file access confined to the experiment directory, without replaying geometry.
