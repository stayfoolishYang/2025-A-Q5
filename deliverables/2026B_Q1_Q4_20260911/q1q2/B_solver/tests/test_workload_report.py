"""Failure-sensitive checks of the independent workload report, no simulator."""
import copy
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

import numpy as np

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(BASE/'reporting'))
from discovery import workload_remaining_route
from workload_report import adoption_gate, audit_workload_events, comparisons, paired_summary


class WorkloadReportTests(unittest.TestCase):
    def test_real_histogram_event_and_modified_evidence(self):
        nodes, current = np.array([[700., 0.], [0., 0.]]), np.array([349.9, 0.])
        hyp = SimpleNamespace(p=np.array([[1500., 0., 0., 1000., 0.]]))
        _, event = workload_remaining_route(nodes, current, {1: {'hyp': hyp}})
        self.assertEqual(event['distance_choice'], 1)
        self.assertEqual(event['selected_choice'], 0)
        self.assertEqual(event['workload_s'], [6., 12.])  # The hit measurement is included.
        trace = {'targets': [{'discovery_refresh_events': [event]}]}
        check = audit_workload_events(trace, 'D2')
        self.assertTrue(check['passed'], check)
        self.assertEqual(check['changed_from_D1'], 1)
        self.assertFalse(audit_workload_events(trace, 'D1')['passed'])
        for field, value in (('workload_s', [0., 6.]), ('refreshed_order', [1, 1]), ('selected_choice', 1)):
            altered = copy.deepcopy(trace)
            altered['targets'][0]['discovery_refresh_events'][0][field] = value
            self.assertFalse(audit_workload_events(altered, 'D2')['passed'], field)
        altered = copy.deepcopy(trace)
        altered['targets'][0]['discovery_refresh_events'][0]['supports'][0]['first_hit_counts'][0] = [0, 0, 2]
        self.assertFalse(audit_workload_events(altered, 'D2')['passed'])

    def test_no_support_and_never_hit_preserve_distance_choice(self):
        nodes, current = np.array([[0., 0.], [700., 0.]]), np.array([349.9, 0.])
        for tracks, expected in (({}, [0., 0.]),
                                  ({1: {'hyp': SimpleNamespace(p=np.array([[3000., 0., 0., 1000., 0.]]))}}, [12., 12.])):
            _, event = workload_remaining_route(nodes, current, tracks)
            self.assertEqual(event['workload_s'], expected)  # Never-hit cost is N, not N+1.
            self.assertEqual(event['selected_choice'], event['distance_choice'])
            check = audit_workload_events({'targets': [{'discovery_refresh_events': [event]}]}, 'D2')
            self.assertTrue(check['passed'], check)

    def case(self, mode, time, seen, cohort='development32', status='FULL_CLEAR'):
        return dict(cohort=cohort, seed=0, mode=mode, variant=mode, total=10, cleared=10,
                    error='' if status == 'FULL_CLEAR' else 'test failure', run_status=status,
                    mean_time_per_source=time, virtual_time_s=time*10, distance=1000., runtime=1.,
                    last_source_first_seen_s=seen, audit_passed=True, seed_hex='a'*64, scene_hash='same-scene')

    def test_failed_pairs_not_counted_as_speedups_and_known_cohort_kept_separate(self):
        rows = [self.case('D0', 100., 800.), self.case('D1', 95., 900.), self.case('D2', 0., 0., status='EXCEPTION')]
        rows += [self.case(mode, value, 500., 'known_counterexamples2') for mode, value in (('D0', 100.), ('D1', 90.), ('D2', 80.))]
        pairs = comparisons(rows)
        self.assertEqual(len(pairs), 4)
        selected = [p for p in pairs if p['cohort'] == 'development32']
        summaries = paired_summary(selected)
        self.assertEqual(summaries['D1-D0']['time_comparisons'], {'win': 1})
        self.assertEqual(summaries['D1-D0']['last_discovery_comparisons'], {'loss': 1})
        self.assertEqual(summaries['D2-D1']['invalid_pairs'], 1)
        self.assertIsNone(summaries['D2-D1']['metrics']['mean_time_per_source']['mean'])
        self.assertIsNone(next(p for p in selected if p['contrast'] == 'D2-D1')['mean_time_per_source_delta'])

    def test_adoption_requires_one_percent_and_both_tails_and_integrity(self):
        cohorts = {'holdout128': {'summaries': {
            'D1': {'physical': dict(mean=100., P95=120., P99=130.)},
            'D2': {'physical': dict(mean=99., P95=120., P99=130.)}}}}
        self.assertTrue(adoption_gate(cohorts, True, True)['passed'])
        self.assertFalse(adoption_gate(cohorts, False, True)['passed'])
        self.assertFalse(adoption_gate(cohorts, True, False)['evaluated'])
        for key, value in (('mean', 99.1), ('P95', 120.1), ('P99', 130.1)):
            altered = copy.deepcopy(cohorts)
            altered['holdout128']['summaries']['D2']['physical'][key] = value
            self.assertEqual(adoption_gate(altered, True, True)['decision'], 'STOP_D2_NO_PARAMETER_SWEEP')


if __name__ == '__main__':
    unittest.main()
