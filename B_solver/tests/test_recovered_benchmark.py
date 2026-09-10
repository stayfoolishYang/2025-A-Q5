"""Regression checks for the local recovered-engine evaluation boundary.

These use direct Python calls and temporary files. No server, official program,
or full benchmark is started. Set JAMMERS_SIM_ROOT when the supplied simulator
package is stored elsewhere.
"""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))
import recovered_benchmark as benchmark

SIM_ROOT = Path(os.environ.get("JAMMERS_SIM_ROOT", "G:/QQ/jammers_linux"))
if (SIM_ROOT / "engine.py").is_file():
    sys.path.insert(0, str(SIM_ROOT))
    from engine import Engine, Jammer, Scenario


@unittest.skipUnless((SIM_ROOT / "engine.py").is_file(), "Supplied simulator package is unavailable")
class EngineBoundaryTests(unittest.TestCase):
    def make_adapter(self, channel=2, x=100., y=0.):
        scene = Scenario("0123456789abcdef", 3, (Jammer(channel, x, y, 1000.),))
        return benchmark.EngineAdapter(Engine(scene))

    def test_rejected_action_cannot_reset_elapsed_time_or_position(self):
        api = self.make_adapter()
        api.action("/enter")
        api.action("/measure", [10., 0.], 2)
        before = copy.deepcopy((api.virtual_time, api.position, api.log, api.stages))
        with self.assertRaises(benchmark.ProtocolError):
            api.action("/enter")
        self.assertEqual(api.virtual_time, before[0])
        np.testing.assert_array_equal(api.position, before[1])
        self.assertEqual(api.log[:len(before[2])], before[2])
        self.assertFalse(api.log[-1]["response"]["accepted"])
        self.assertEqual(api.stages, before[3])

    def test_stage_ledger_charges_clear_without_radio_switch(self):
        api = self.make_adapter()
        api.action("/enter")
        api.action("/measure", [0., 0.], 2)  # 1 switch + 5 measurement
        api.stage = "optical_fallback"
        api.action("/clear", [50., 0.], 2)  # 10 movement + 3 failed clear
        self.assertEqual(api.channel, 2)
        api.stage = "certified_clear"
        api.action("/clear", [100., 0.], 2)  # 10 movement + 5 success
        api.stage = "discovery"
        api.action("/measure", [100., 0.], 1)  # 1 switch + 5 measurement
        api.action("/exit")
        self.assertEqual(api.virtual_time, 40.)
        self.assertEqual(api.stages["discovery"]["total_s"], 12.)
        self.assertEqual(api.stages["optical_fallback"]["total_s"], 13.)
        self.assertEqual(api.stages["certified_clear"]["total_s"], 15.)
        self.assertEqual(sum(s["total_s"] for s in api.stages.values()), api.virtual_time)
        self.assertEqual((api.distance, api.switches, api.measures, api.clear_attempts), (100., 2, 2, 2))

    def test_virtual_limit_boundary_is_retained_and_next_action_is_blocked(self):
        api = self.make_adapter(channel=1)
        api.action("/enter")
        result = api.action("/measure", [1799975., 0.], 1)
        self.assertTrue(result["accepted"])
        self.assertEqual(api.virtual_time, 360000.)
        self.assertEqual(api._engine.end_reason, "virtual_timeout")
        before = api.virtual_time
        with self.assertRaises(TimeoutError):
            api.action("/clear", [100., 0.], 1)
        self.assertEqual(api.virtual_time, before)
        self.assertEqual(api.clear_attempts, 0)

    def test_real_limit_blocks_engine_before_sending_an_action(self):
        api = self.make_adapter()
        with patch.object(benchmark.time, "perf_counter", return_value=100.):
            api.action("/enter")
        with patch.object(benchmark.time, "perf_counter", return_value=1300.):
            with self.assertRaises(TimeoutError):
                api.action("/measure", [0., 0.], 2)
        self.assertEqual(api._engine.virtual_us, 0)
        self.assertEqual(len(api.log), 1)

    def test_solver_runs_through_an_observation_only_facade(self):
        from solver import Solver

        api = self.make_adapter(channel=1, x=150., y=30.)

        class ObservationOnly:
            def __getattr__(self, key):
                if key not in {"action", "position", "channel", "virtual_time"}:
                    raise AssertionError("Policy attempted to read evaluator state: " + key)
                return getattr(api, key)

        result = Solver(ObservationOnly(), False, "P3", device="cpu").run()
        self.assertEqual(result["cleared"], 1)
        self.assertEqual(api._engine.cleared, {1})
        for action in api.log:
            self.assertFalse({"sources", "jammers", "scenario", "noise_seed_hex", "generator_seed_hex"}
                             .intersection(action["response"]))

    def test_two_engines_and_adapters_do_not_share_mutable_state(self):
        first, second = self.make_adapter(), self.make_adapter()
        first.action("/enter")
        first.action("/clear", [100., 0.], 2)
        self.assertEqual(first._engine.cleared, {2})
        self.assertEqual(second._engine.cleared, set())
        self.assertFalse(second._engine.entered)
        self.assertEqual(second.log, [])
        self.assertEqual(second.virtual_time, 0.)
        np.testing.assert_array_equal(second.position, [0., 0.])


class FrozenEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.out = Path(self.temp.name)
        self.variant = "candidate_grid_v1"
        self.cfg = {"name": self.variant, "grid_version": "grid_v1"}
        self.raw = {"generator_seed_hex": "00" * 32, "problem_no": 4,
                    "jammers": [{"channel": 1, "x_um": 120000000, "y_um": 0}]}
        self.manifest = {
            "configs": {"4": [self.cfg]}, "seeds": [{"seed": 0, "seed_hex": "00" * 32}],
            "source_hashes": {"solver/solver.py": "frozen-source-fingerprint"},
            "scene_hashes": {"q4_0000.json": benchmark.digest(self.raw)},
        }
        benchmark.save(self.out / "scenes/q4_0000.json", self.raw)
        benchmark.save(self.out / "manifest.json", self.manifest)

    def valid_row(self):
        return dict(seed=0, problem=4, variant=self.variant, device="cpu", total=1, cleared=1,
                    run_status="FULL_CLEAR", error="", scene_hash=benchmark.digest(self.raw),
                    config_hash=benchmark.digest(self.cfg), source_hash=benchmark.digest(self.manifest["source_hashes"]))

    def test_new_seed_set_is_unique_and_explicitly_reproducible(self):
        first, second = benchmark.frozen_seeds(), benchmark.frozen_seeds()
        self.assertEqual(first, second)
        self.assertEqual(len(first), 519)
        self.assertEqual(len({r["seed_hex"] for r in first}), 519)
        self.assertEqual([r["seed"] for r in first], list(range(519)))
        basis = [int(r["seed_hex"], 16) for r in first if r["family"] == "one_bit"]
        self.assertEqual(set(basis), {1 << bit for bit in range(256)})

    def test_scene_mutation_is_rejected_before_running_solver(self):
        benchmark.validated_inputs(self.out, 0, 4, self.variant)
        changed = copy.deepcopy(self.raw)
        changed["jammers"][0]["x_um"] += 1
        benchmark.save(self.out / "scenes/q4_0000.json", changed)
        with self.assertRaisesRegex(RuntimeError, "fingerprint"):
            benchmark.validated_inputs(self.out, 0, 4, self.variant)

    def test_scene_identity_must_match_seed_and_problem_even_with_matching_hash(self):
        for field, changed in [("generator_seed_hex", "ff" * 32), ("problem_no", 3)]:
            with self.subTest(field=field):
                raw = copy.deepcopy(self.raw)
                raw[field] = changed
                manifest = copy.deepcopy(self.manifest)
                manifest["scene_hashes"]["q4_0000.json"] = benchmark.digest(raw)
                benchmark.save(self.out / "manifest.json", manifest)
                benchmark.save(self.out / "scenes/q4_0000.json", raw)
                with self.assertRaisesRegex(RuntimeError, "identity"):
                    benchmark.validated_inputs(self.out, 0, 4, self.variant)

    def test_resume_rejects_different_scene_config_source_identity_or_device(self):
        for field, replacement in [("seed", 1), ("problem", 3), ("variant", "wrong"),
                                   ("scene_hash", "wrong"), ("config_hash", "wrong"),
                                   ("source_hash", "wrong"), ("device", "cuda")]:
            with self.subTest(field=field):
                row = self.valid_row()
                row[field] = replacement
                benchmark.save(self.out / "q4/rows" / f"{self.variant}_0000.json", row)
                with patch.object(benchmark.subprocess, "run") as process:
                    with self.assertRaises(RuntimeError):
                        benchmark.launch_case((self.out, SIM_ROOT, 0, 4, self.variant, "cpu", True))
                    process.assert_not_called()

    def test_process_timeout_retains_an_explicit_unsuccessful_result(self):
        with patch.object(benchmark.subprocess, "run", side_effect=subprocess.TimeoutExpired("case", 1210)) as process:
            row = benchmark.launch_case((self.out, SIM_ROOT, 0, 4, self.variant, "cpu", False))
        self.assertEqual(process.call_args.kwargs["timeout"], 1210)
        self.assertEqual(row["run_status"], "TIMEOUT")
        self.assertTrue(row["partial_state_unknown"])
        self.assertTrue(row["error"])
        self.assertEqual(row["cleared"], 0)
        benchmark.validate_row(row, self.manifest, self.cfg, self.raw, 0, 4, self.variant, "cpu")

    @unittest.skipUnless((SIM_ROOT / "engine.py").is_file(), "Supplied simulator package is unavailable")
    def test_freeze_records_each_scene_hash_and_matches_supplied_original_fixture(self):
        seed = dict(seed=0, seed_hex=bytes(range(32)).hex(), family="fixture")
        frozen = self.out / "frozen"
        with patch.object(benchmark, "frozen_seeds", return_value=[seed]):
            benchmark.freeze(frozen, SIM_ROOT, "grid_v0")
        manifest = json.loads((frozen / "manifest.json").read_text(encoding="utf-8"))
        for problem in (3, 4):
            raw = json.loads((frozen / f"scenes/q{problem}_0000.json").read_text(encoding="utf-8"))
            self.assertEqual(benchmark.digest(raw), manifest["scene_hashes"][f"q{problem}_0000.json"])
        expected = json.loads((SIM_ROOT / "tests/fixtures/original_practice_q4.json").read_text(encoding="utf-8"))
        self.assertEqual(raw, expected)
        with self.assertRaises(FileExistsError):
            benchmark.freeze(frozen, SIM_ROOT, "grid_v0")


if __name__ == "__main__":
    unittest.main()
