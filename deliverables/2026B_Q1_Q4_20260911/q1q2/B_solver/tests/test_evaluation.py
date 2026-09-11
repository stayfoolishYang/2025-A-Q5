"""Failure injection and evidence-integrity checks; no network or UI calls."""
import copy
import csv
import io
import json
import math
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from evaluation import classify_run, evaluate_rows, expected_pairs, exception_status
from paired_q4 import run_case, summarize
from paired_multi_gpu import collect_worker_results


def row(seed=0, variant='baseline', cleared=10, elapsed=1000., **extra):
    result = dict(seed=seed, variant=variant, total=10, cleared=cleared,
                  clear_rate=cleared/10, error='', mean_time_per_source=elapsed,
                  distance=100., runtime=1., fallback_count=0, grid_points=0,
                  clear_attempts=10, optical_clear_attempts=0, diagnostic_count=0,
                  detect_count=10, switch_count=0)
    result.update(extra)
    return result


class EvaluationTests(unittest.TestCase):
    def evaluate(self, rows, seeds=(0,), variants=('baseline', 'candidate')):
        return evaluate_rows(rows, expected_pairs(seeds, variants), 'baseline')

    def test_zero_clear_exception_cannot_win_by_ending_early(self):
        rows = [row(), row(variant='candidate', cleared=0, elapsed=0., error='RuntimeError("failed")')]
        result = self.evaluate(rows)
        candidate = result['summary']['candidate']
        self.assertEqual(candidate['paired_wins'], 0)
        self.assertEqual(candidate['paired_success_losses'], 1)
        self.assertEqual(candidate['timed_n'], 0)
        self.assertIsNone(candidate['mean'])
        self.assertEqual(result['classified_rows'][1]['mean_time_per_source'], 0.)
        self.assertFalse(result['acceptance']['accept'])
        self.assertEqual(result['acceptance']['exception_count'], 1)

    def test_partial_clear_is_failure_despite_faster_time(self):
        result = self.evaluate([row(), row(variant='candidate', cleared=9, elapsed=500.)])
        self.assertEqual(result['classified_rows'][1]['run_status'], 'PARTIAL_CLEAR')
        self.assertEqual(result['summary']['candidate']['paired_success_losses'], 1)
        self.assertEqual(result['summary']['candidate']['paired_wins'], 0)

    def test_success_beats_failure_without_a_timing_win(self):
        result = self.evaluate([row(cleared=0, elapsed=0), row(variant='candidate', elapsed=2000)])
        candidate = result['summary']['candidate']
        self.assertEqual(candidate['paired_success_wins'], 1)
        self.assertEqual(candidate['paired_time_n'], 0)
        self.assertEqual(candidate['paired_wins'], 0)
        self.assertFalse(result['acceptance']['speed_comparison_valid'])

    def test_two_failures_enter_failure_audit_only(self):
        result = self.evaluate([row(cleared=4), row(variant='candidate', cleared=8, elapsed=20)])
        candidate = result['summary']['candidate']
        self.assertEqual(candidate['paired_both_failed'], 1)
        self.assertEqual(candidate['paired_wins'], 0)
        self.assertEqual(candidate['paired_losses'], 0)

    def test_only_joint_successes_enter_paired_time(self):
        rows = [row(0), row(0, 'candidate', elapsed=900),
                row(1, cleared=0), row(1, 'candidate', elapsed=500),
                row(2), row(2, 'candidate', cleared=5, elapsed=1)]
        candidate = self.evaluate(rows, seeds=range(3))['summary']['candidate']
        self.assertEqual(candidate['paired_time_n'], 1)
        self.assertEqual(candidate['paired_mean_delta'], -100.)
        self.assertEqual(candidate['paired_wins'], 1)
        self.assertEqual(candidate['paired_success_wins'], 1)
        self.assertEqual(candidate['paired_success_losses'], 1)
        self.assertEqual(candidate['mean'], 700.)

    def test_validity_acceptance_is_separate_from_speed_improvement(self):
        result = self.evaluate([row(), row(variant='candidate', elapsed=1500)])
        self.assertTrue(result['acceptance']['accept'])
        self.assertTrue(result['acceptance']['speed_comparison_valid'])
        self.assertEqual(result['acceptance']['performance']['candidate']['outcome'], 'regressed')

    def test_timeout_protocol_and_exception_statuses(self):
        self.assertEqual(exception_status(TimeoutError('budget')), 'TIMEOUT')
        self.assertEqual(exception_status(RuntimeError('Rejected /measure: not accepted')), 'PROTOCOL_ERROR')
        self.assertEqual(exception_status(RuntimeError('unexpected geometry')), 'EXCEPTION')
        for status in ('TIMEOUT', 'PROTOCOL_ERROR', 'EXCEPTION'):
            result = classify_run(row(run_status=status))
            self.assertEqual(result['run_status'], status)
            self.assertFalse(result['valid_full_clear'])

    def test_misdeclared_full_clear_and_missing_error_fail_closed(self):
        self.assertFalse(classify_run(row(cleared=9, run_status='FULL_CLEAR'))['valid_full_clear'])
        malformed = row()
        del malformed['error']
        self.assertIn('missing:error', classify_run(malformed)['validation_errors'])

    def test_missing_duplicate_and_wrong_pair_are_reported_exactly(self):
        result = self.evaluate([row(), row(), row(5, 'candidate')])
        acceptance = result['acceptance']
        self.assertFalse(acceptance['accept'])
        self.assertEqual(acceptance['duplicate_pairs'], [(0, 'baseline')])
        self.assertEqual(acceptance['missing_pairs'], [(0, 'candidate')])
        self.assertEqual(acceptance['unexpected_pairs'], [(5, 'candidate')])
        self.assertEqual(result['summary']['baseline']['timed_n'], 0)

    def test_same_unique_pair_count_does_not_hide_wrong_seed(self):
        result = self.evaluate([row(), row(8, 'candidate')])
        self.assertFalse(result['acceptance']['all_expected_pairs_present'])
        self.assertFalse(result['acceptance']['accept'])

    def test_no_rows_no_plan_and_noncartesian_plan_fail_closed(self):
        for result in (self.evaluate([]), evaluate_rows([row()]),
                       evaluate_rows([row()], []),
                       evaluate_rows([row()], [(0, 'a'), (1, 'b')]),
                       evaluate_rows([row()], [(0, 'baseline'), (0, 'baseline')])):
            self.assertFalse(result['acceptance']['accept'])

    def test_nonfinite_negative_missing_and_bad_counts_are_rejected(self):
        bad = [row(mean_time_per_source=math.nan), row(distance=math.inf),
               row(runtime='NaN'), row(total=0), row(cleared=11), row(total=True),
               row(clear_rate=0.5), row(mean_time_per_source=-1),
               row(phases={'discovery': float('inf')}), row(scene_hash={'bad': 1})]
        missing = row()
        del missing['distance']
        bad.append(missing)
        for sample in bad:
            with self.subTest(sample=sample):
                result = self.evaluate([sample, row(variant='candidate')])
                self.assertFalse(result['acceptance']['accept'])
                self.assertGreater(result['acceptance']['invalid_row_count'], 0)
                self.assertEqual(result['summary']['baseline']['timed_n'], 0)

    def test_scene_source_count_and_configuration_mismatch_reject_pairing(self):
        cases = ([row(scene_hash='a'), row(variant='candidate', scene_hash='b')],
                 [row(), row(variant='candidate', total=5, cleared=5, clear_rate=1.)],
                 [row(scene_hash='a'), row(variant='candidate')])
        for rows in cases:
            result = self.evaluate(rows)
            self.assertFalse(result['acceptance']['speed_comparison_valid'])
            self.assertEqual(result['summary']['candidate']['paired_time_n'], 0)
        rows = [row(0, config_hash='a'), row(0, 'candidate', config_hash='b'),
                row(1, config_hash='changed'), row(1, 'candidate', config_hash='b')]
        self.assertFalse(self.evaluate(rows, seeds=range(2))['acceptance']['accept'])

    def test_csv_numeric_strings_and_64_bit_seeds_are_exact(self):
        seeds = (2**63 + 1, 2**63 + 2)
        rows = [row(seed, variant) for seed in seeds for variant in ('baseline', 'candidate')]
        rows = [{key: str(value) for key, value in r.items()} for r in rows]
        result = self.evaluate(rows, seeds=seeds)
        self.assertTrue(result['acceptance']['accept'])
        self.assertEqual(result['summary']['candidate']['paired_time_n'], 2)

    def test_input_evidence_is_unchanged(self):
        rows = [row(), row(variant='candidate', phases={'a': [1, 2, 3]})]
        original = copy.deepcopy(rows)
        self.evaluate(rows)
        self.assertEqual(rows, original)

    def test_single_variant_q3_can_pass_without_a_speed_comparison(self):
        result = evaluate_rows([row(variant='Q3')], [(0, 'Q3')], 'Q3')
        self.assertTrue(result['acceptance']['accept'])
        self.assertFalse(result['acceptance']['speed_comparison_valid'])
        self.assertEqual(result['acceptance']['performance'], {})

    def test_raw_csv_not_overwritten_and_derived_json_is_strict(self):
        with tempfile.TemporaryDirectory() as directory, redirect_stdout(io.StringIO()):
            out = Path(directory)
            rows = [row(), row(variant='candidate', mean_time_per_source=math.nan)]
            plan = expected_pairs([0], ['baseline', 'candidate'])
            summarize(rows, out, plan, 'baseline')
            original = (out/'cases.csv').read_bytes()
            with self.assertRaises(FileExistsError):
                summarize(rows, out, plan, 'baseline')
            summarize(rows, out, plan, 'baseline', write_cases=False)
            self.assertEqual(original, (out/'cases.csv').read_bytes())
            for name in ('acceptance', 'summary', 'worst10'):
                text = (out/f'{name}.json').read_text(encoding='utf-8')
                json.loads(text, parse_constant=lambda value: self.fail(f'invalid JSON constant {value}'))
            self.assertIn('nan', (out/'cases.csv').read_text(encoding='utf-8-sig'))

    def test_worker_failure_still_writes_rejecting_acceptance(self):
        with tempfile.TemporaryDirectory() as directory, redirect_stdout(io.StringIO()):
            out = Path(directory)
            worker = out/'worker_0'
            worker.mkdir()
            (worker/'manifest.json').write_text('{}', encoding='utf-8')
            records = [row(run_status='FULL_CLEAR'), row(variant='candidate', run_status='FULL_CLEAR')]
            with (worker/'cases.csv').open('w', newline='', encoding='utf-8-sig') as f:
                writer = csv.DictWriter(f, fieldnames=list(records[1]))
                writer.writeheader()
                writer.writerows(records)
            acceptance = collect_worker_results([worker], out,
                expected_pairs([0], ['baseline', 'candidate']), 'baseline', ['worker exited 1'])
            self.assertFalse(acceptance['accept'])
            self.assertIn('worker_execution_or_evidence_error', acceptance['failure_reasons'])
            self.assertTrue((out/'cases.csv').exists())

    def test_missing_worker_output_is_not_a_successful_empty_benchmark(self):
        with tempfile.TemporaryDirectory() as directory, redirect_stdout(io.StringIO()):
            out = Path(directory)
            acceptance = collect_worker_results([out/'missing_worker'], out,
                expected_pairs([0], ['baseline', 'candidate']), 'baseline')
            self.assertFalse(acceptance['accept'])
            self.assertEqual(acceptance['observed_run_count'], 0)
            self.assertEqual(len(acceptance['missing_pairs']), 2)
            self.assertEqual(len(acceptance['worker_errors']), 2)

    def test_solver_initialization_failure_is_retained(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch('paired_q4.AuditedSolver', side_effect=RuntimeError('constructor failure')):
                result = run_case((0, {'name': 'broken'}, 'cpu', directory))
            self.assertEqual(result['run_status'], 'EXCEPTION')
            self.assertEqual(result['cleared'], 0)
            evidence = json.loads((Path(directory)/'traces/broken_00000.json').read_text(encoding='utf-8'))
            self.assertIn('constructor failure', evidence['row']['error'])


if __name__ == '__main__':
    unittest.main()
