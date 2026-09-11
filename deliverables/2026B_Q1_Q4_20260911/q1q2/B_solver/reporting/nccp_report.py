"""Read-only NCCP evidence audit and paired report; never launches a solver.

Only REPORT.md, NCCP_AUDIT.json and NCCP_PAIRS.csv are written in the supplied
cohort. Raw rows, traces, frozen scenes and existing acceptance files stay intact.
"""
import argparse
import csv
import gzip
import hashlib
import json
import math
from fractions import Fraction
from pathlib import Path
import sys

import numpy as np

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))
from evaluation import classify_run, evaluate_rows, expected_pairs, json_safe

PHYSICAL = ('seed_hex', 'problem', 'variant', 'run_status', 'engine_end_reason',
            'total', 'cleared', 'clear_rate', 'error', 'mean_time_per_source',
            'virtual_time_s', 'distance', 'fallback_count', 'grid_points',
            'clear_attempts', 'optical_clear_attempts', 'diagnostic_count',
            'detect_count', 'switch_count', 'config_hash', 'scene_hash',
            'directional_count', 'grid_version', 'stage_discovery_s',
            'stage_active_localization_s', 'stage_diagnostic_s',
            'stage_optical_fallback_s', 'stage_certified_clear_s', 'stage_sum_error_s')
NUMERIC_BOOKKEEPING_TOL = 1e-9


def read_json(path):
    path = Path(path)
    if path.suffix == '.gz':
        with gzip.open(path, 'rt', encoding='utf-8') as file:
            return json.load(file)
    return json.loads(path.read_text(encoding='utf-8'))


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def close(a, b, tolerance=NUMERIC_BOOKKEEPING_TOL):
    try:
        return math.isfinite(float(a)) and math.isfinite(float(b)) and abs(float(a)-float(b)) <= tolerance
    except (ValueError, TypeError):
        return False


def exact_squared_distance(a, b):
    """Distance of the stored binary floats, before any rounded subtraction."""
    return sum((Fraction(float(x))-Fraction(float(y)))**2 for x, y in zip(a, b))


def audit_events(trace, row, selector):
    """Independently recompute every vertex and travel certificate from raw data.

    Safety/non-increasing-distance inequalities are checked in FP64 and with
    exact binary-rational squared distances, strictly and without epsilon.
    A 1e-9 tolerance is used only when comparing redundant stored bookkeeping.
    This checks feasibility and local non-increase, not mathematical optimality
    of the point selector or whole-run non-increase.
    """
    failures, events, clear_actions = [], [], []
    actions = trace.get('actions', [])
    before, position_before = 0., [0., 0.]
    for index, action in enumerate(actions):
        after = action.get('response', {}).get('virtual_time_s')
        if action.get('path') == '/clear' and action.get('stage') == 'certified_clear':
            clear_actions.append((index, before, position_before, action))
        before = after
        if action.get('position') is not None:
            position_before = action['position']
    for target in trace.get('targets', []):
        for event in target.get('certified_clearance_events', []):
            events.append((target.get('channel'), event))
    used, distances, centers, savings, maxdist = set(), [], [], [], []
    zero_count, fallback_count, current_certified_count = 0, 0, 0
    for ordinal, (channel, event) in enumerate(events):
        prefix = f'event[{ordinal}]'
        try:
            polygon = np.asarray(event['polygon'], dtype=float)
            point = np.asarray(event['point'], dtype=float)
            start = np.asarray(event['start'], dtype=float)
            center = np.asarray(event['mec_center'], dtype=float)
            radius = float(event['clearance_radius'])
            mec_radius = float(event['mec_radius'])
            if (polygon.ndim != 2 or polygon.shape[1] != 2 or not len(polygon)
                    or any(value.shape != (2,) for value in (point, start, center))
                    or not all(np.isfinite(value).all() for value in (polygon, point, start, center))
                    or radius != 19.999 or not math.isfinite(mec_radius) or not 0 <= mec_radius <= radius):
                raise ValueError('invalid polygon/coordinates/radius or changed trigger')
            worst = float(np.max(np.linalg.norm(polygon-point, axis=1)))
            center_worst = float(np.max(np.linalg.norm(polygon-center, axis=1)))
            travel = float(np.linalg.norm(point-start))
            mec_travel = float(np.linalg.norm(center-start))
            if worst > radius:
                failures.append(f'{prefix}: unsafe_vertex_distance')
            if center_worst > radius:
                failures.append(f'{prefix}: infeasible_reference_mec_center')
            if center_worst > mec_radius:
                failures.append(f'{prefix}: mec_radius_understates_vertices')
            if travel > mec_travel:
                failures.append(f'{prefix}: same_state_travel_increased')
            # sqrt/norm and coordinate subtraction can round downward. Convert
            # each original stored float to Fraction before doing arithmetic.
            radius_squared = Fraction(radius)**2
            mec_radius_squared = Fraction(mec_radius)**2
            if any(exact_squared_distance(vertex, point) > radius_squared for vertex in polygon):
                failures.append(f'{prefix}: unsafe_vertex_distance_exact')
            if any(exact_squared_distance(vertex, center) > mec_radius_squared for vertex in polygon):
                failures.append(f'{prefix}: mec_radius_understates_vertices_exact')
            if exact_squared_distance(point, start) > exact_squared_distance(center, start):
                failures.append(f'{prefix}: same_state_travel_increased_exact')
            current_worst = float(np.max(np.linalg.norm(polygon-start, axis=1)))
            current_certified_count += int(current_worst <= radius and all(
                exact_squared_distance(vertex, start) <= radius_squared for vertex in polygon))
            if event['selector'] != selector:
                failures.append(f'{prefix}: wrong_selector')
            if selector == 'mec_center' and not np.array_equal(point, center):
                failures.append(f'{prefix}: baseline_landing_changed')
            for key, calculated in (('max_vertex_distance', worst), ('travel_m', travel),
                                    ('mec_travel_m', mec_travel), ('same_state_saving_m', mec_travel-travel)):
                if not close(event.get(key), calculated):
                    failures.append(f'{prefix}: incorrect_{key}')
            if event.get('zero_move') is not (travel == 0.):
                failures.append(f'{prefix}: incorrect_zero_move')
            matches = [(index, action) for index, start_time, actual_start, action in clear_actions
                       if index not in used and action.get('channel') == channel
                       and actual_start == event['start']
                       and action.get('position') == event['point']
                       and start_time == event['time_before']
                       and action.get('response', {}).get('virtual_time_s') == event.get('time_after')]
            if len(matches) != 1:
                failures.append(f'{prefix}: not_one_matching_clear_action')
            else:
                index, action = matches[0]
                used.add(index)
                if (event.get('success') is not True or action['response'].get('accepted') is not True
                        or action['response'].get('clear_result') != 'success'):
                    failures.append(f'{prefix}: unsuccessful_certified_clear')
                if not close(action.get('travel_m'), travel):
                    failures.append(f'{prefix}: action_travel_does_not_match_event')
                if not close(event['time_after']-event['time_before'], travel/5+5, 1.1e-6):
                    failures.append(f'{prefix}: clear_time_ledger_mismatch')
            zero_count += int(travel == 0.)
            fallback_count += int(bool(event['selection'].get('fallback')))
            distances.append(travel)
            centers.append(mec_travel)
            savings.append(mec_travel-travel)
            maxdist.append(worst)
        except (KeyError, TypeError, ValueError, IndexError, OverflowError) as exc:
            failures.append(f'{prefix}: malformed_certificate:{exc}')
    near_count = 0
    for index, _, _, action in clear_actions:
        if index in used:
            continue
        previous = actions[index-1] if index else {}
        if (previous.get('path') == '/measure' and previous.get('channel') == action.get('channel')
                and previous.get('response', {}).get('measure_result') == 'near'
                and previous.get('position') == action.get('position')
                and action.get('travel_m') == 0.
                and action.get('response', {}).get('accepted') is True
                and action.get('response', {}).get('clear_result') == 'success'):
            near_count += 1
        else:
            failures.append(f'action[{index}]: certified_clear_has_no_polygon_or_near_certificate')
    totals = dict(polygon_certified_count=len(events), near_certified_count=near_count,
                  polygon_clear_travel_m=sum(distances), polygon_clear_mec_travel_m=sum(centers),
                  same_state_clear_saving_m=sum(savings), polygon_zero_move_count=zero_count,
                  nccp_fallback_count=fallback_count,
                  max_clearance_vertex_distance=max(maxdist, default=0.))
    for key, calculated in totals.items():
        if not close(row.get(key), calculated):
            failures.append(f'row: incorrect_or_missing_{key}')
    if row.get('certificate_audit_violations') != 0:
        failures.append('row: reported_or_missing_certificate_violations')
    if row.get('clearance_point') != selector:
        failures.append('row: wrong_or_missing_clearance_point')
    return dict(passed=not failures, failure_count=len(failures), failures=failures,
                certified_action_count=len(clear_actions),
                current_position_certified_count=current_certified_count,
                current_position_certified_case_count=int(current_certified_count > 0),
                zero_move_clear_count=zero_count+near_count,
                zero_move_clear_case_count=int(zero_count+near_count > 0),
                minimum_same_state_saving_m=min(savings, default=None), **totals)


def compare_reference(row, trace, reference_row, reference_trace):
    failures = [f'physical_metric:{key}' for key in PHYSICAL
                if key not in row or key not in reference_row or row[key] != reference_row[key]]
    left, right = trace.get('actions'), reference_trace.get('actions')
    if not isinstance(left, list) or not isinstance(right, list):
        failures.append('missing_actions')
    elif left != right:
        failures.append(f'action_count:{len(left)}!={len(right)}' if len(left) != len(right)
                        else 'action_content_mismatch')
        for index, (a, b) in enumerate(zip(left, right)):
            if a != b:
                failures.append(f'first_different_action:{index}')
                break
    return failures


def physical_summary(rows, certificates, planned_count):
    classified = [classify_run(row) for row in rows]
    valid = [r for r in classified if r['valid_full_clear']]
    values = np.array([r['mean_time_per_source'] for r in valid], dtype=float)
    def total(field, selected=None):
        try:
            result = sum(float(r[field]) for r in (valid if selected is None else selected))
            return result if math.isfinite(result) else None
        except (KeyError, TypeError, ValueError):
            return None
    try:
        polygon_mean = float(np.mean([r['polygon_clear_travel_m']/r['total'] for r in valid])) if valid else None
    except (KeyError, TypeError, ValueError):
        polygon_mean = None
    status_counts = {status: sum(r['run_status'] == status for r in classified)
                     for status in ('FULL_CLEAR', 'PARTIAL_CLEAR', 'ZERO_CLEAR', 'EXCEPTION', 'TIMEOUT', 'PROTOCOL_ERROR')}
    audited = [certificates[(r['seed'], r['variant'])] for r in rows
               if (r['seed'], r['variant']) in certificates]
    def audited_total(field):
        return sum(record[field] for record in audited)
    return dict(n=len(valid), planned_count=planned_count, observed_count=len(rows),
                full_clear_count=len(valid), full_clear_rate=len(valid)/planned_count if planned_count else None,
                exception_count=status_counts['EXCEPTION'], protocol_count=status_counts['PROTOCOL_ERROR'],
                timeout_count=status_counts['TIMEOUT'], partial_clear_count=status_counts['PARTIAL_CLEAR'],
                zero_clear_count=status_counts['ZERO_CLEAR'], status_counts=status_counts,
                invalid_evidence_count=sum(bool(r['validation_errors']) for r in classified),
                mean=float(values.mean()) if valid else None,
                P50=float(np.percentile(values, 50)) if valid else None,
                P95=float(np.percentile(values, 95)) if valid else None,
                P99=float(np.percentile(values, 99)) if valid else None, max=float(values.max()) if valid else None,
                total_virtual_time_s=total('virtual_time_s'), total_distance_m=total('distance'),
                total_observed_virtual_time_s=total('virtual_time_s', rows),
                total_observed_distance_m=total('distance', rows),
                mean_polygon_clear_travel_m_per_source=polygon_mean,
                total_polygon_clear_travel_m=total('polygon_clear_travel_m'),
                same_state_counterfactual_saving_m=total('same_state_clear_saving_m'),
                polygon_certified_count=total('polygon_certified_count'),
                near_certified_count=total('near_certified_count'),
                polygon_zero_move_count=total('polygon_zero_move_count'),
                nccp_fallback_count=total('nccp_fallback_count'),
                current_position_certified_count=audited_total('current_position_certified_count'),
                current_position_certified_case_count=audited_total('current_position_certified_case_count'),
                zero_move_clear_count=audited_total('zero_move_clear_count'),
                zero_move_clear_case_count=audited_total('zero_move_clear_case_count'),
                audited_case_count=len(audited),
                minimum_same_state_saving_m=min((r['minimum_same_state_saving_m'] for r in audited
                    if r['minimum_same_state_saving_m'] is not None), default=None))


def audit_cohort(cohort, reference, development_audit=None):
    manifest = read_json(cohort/'manifest.json')
    failures, problems, pairs = [], {}, []
    details = []
    reference_manifest = read_json(reference/'manifest.json')
    if manifest.get('reference_manifest_sha256') != sha256(reference/'manifest.json'):
        failures.append('reference_manifest_sha256_mismatch')
    seeds = manifest['seeds']
    if [record.get('seed') for record in seeds] != list(range(len(seeds))):
        failures.append('seed_indices_not_contiguous')
    if len({record.get('seed_hex') for record in seeds}) != len(seeds):
        failures.append('duplicate_seed_hex')
    if any(not isinstance(r.get('seed_hex'), str) or len(r['seed_hex']) != 64
           or any(ch not in '0123456789abcdef' for ch in r['seed_hex']) for r in seeds):
        failures.append('invalid_256bit_seed_encoding')
    if not isinstance(manifest.get('shared_seed_plan_hash'), str) or not manifest['shared_seed_plan_hash']:
        failures.append('missing_shared_seed_plan_hash')
    source_hash = digest(manifest['source_hashes'])
    baseline_checked, baseline_mismatched, event_count = 0, 0, 0
    mapping_present = [record.get('source_seed') is not None for record in seeds]
    development = manifest.get('cohort') == 'development100'
    holdout = manifest.get('cohort') == 'holdout256'
    if not (development or holdout):
        failures.append('unknown_cohort_type')
    if len(seeds) != (100 if development else 256):
        failures.append('cohort_count_differs_from_frozen_design')
    if set(manifest['configs']) != {'3', '4'}:
        failures.append('both_Q3_and_Q4_required_by_NCCP_plan')
    if development and not all(mapping_present):
        failures.append('development_missing_reference_seed_mapping')
    if holdout:
        if any(mapping_present):
            failures.append('holdout_must_not_reuse_reference_mapping')
        historical = {record['seed_hex'] for record in reference_manifest['seeds']}
        if historical & {record['seed_hex'] for record in seeds}:
            failures.append('holdout_overlaps_reference_seed_hex')
        path = Path(development_audit or manifest.get('development_audit_path') or
                    cohort.parent/'development100'/'NCCP_AUDIT.json')
        try:
            predecessor = read_json(path)
            if (predecessor.get('performance_conclusion_allowed') is not True
                    or predecessor.get('cohort') != 'development100'
                    or predecessor.get('shared_seed_plan_hash') != manifest.get('shared_seed_plan_hash')
                    or predecessor.get('source_hash') != source_hash):
                failures.append('development_prerequisite_failed_or_different_source_plan')
        except (OSError, ValueError) as exc:
            failures.append(f'development_audit_unavailable:{exc}')
    for problem_string, configs in sorted(manifest['configs'].items()):
        problem = int(problem_string)
        baseline, candidate = configs[0]['name'], configs[1]['name']
        prefix = f'Q{problem}'
        if len(configs) != 2 or configs[0].get('clearance_point', 'mec_center') != 'mec_center' or configs[1].get('clearance_point') != 'nccp':
            failures.append(f'{prefix}: incorrect_AB_configuration')
        original = next((c for c in reference_manifest['configs'][problem_string] if c['name'] == baseline), None)
        if original != configs[0]:
            failures.append(f'{prefix}: baseline_configuration_changed')
        expected_candidate = dict(configs[0], name=candidate, clearance_point='nccp')
        if configs[1] != expected_candidate:
            failures.append(f'{prefix}: candidate_changed_more_than_clearance_selector')
        folder = cohort/f'q{problem}'
        expected = expected_pairs(range(len(seeds)), (baseline, candidate))
        expected_rows = {f'{variant}_{seed:04d}.json' for seed, variant in expected}
        actual_rows = {path.name for path in (folder/'rows').glob('*.json')}
        if expected_rows != actual_rows:
            failures.append(f'{prefix}: missing_or_unexpected_row_files')
        expected_traces = {name[:-5]+'.json.gz' for name in expected_rows}
        if expected_traces != {path.name for path in (folder/'traces').glob('*.json.gz')}:
            failures.append(f'{prefix}: missing_or_unexpected_trace_files')
        rows, certificates = [], {}
        for seed, variant in expected:
            label = f'{prefix}:{seed}:{variant}'
            try:
                row = read_json(folder/'rows'/f'{variant}_{seed:04d}.json')
                trace = read_json(folder/'traces'/f'{variant}_{seed:04d}.json.gz')
                cfg = next(config for config in configs if config['name'] == variant)
                scene_name = f'q{problem}_{seed:04d}.json'
                scene = read_json(cohort/'scenes'/scene_name)
                expected_identity = dict(seed=seed, seed_hex=seeds[seed]['seed_hex'], problem=problem,
                                         variant=variant, source_hash=source_hash,
                                         config_hash=digest(cfg), scene_hash=digest(scene), total=len(scene['jammers']))
                bad_identity = [key for key, value in expected_identity.items() if row.get(key) != value]
                missing_metrics = [key for key in PHYSICAL if key not in row]
                if missing_metrics:
                    failures.append(f'{label}: missing_physical_metrics:{missing_metrics}')
                if (digest(scene) != manifest['scene_hashes'][scene_name]
                        or scene['generator_seed_hex'] != seeds[seed]['seed_hex'] or scene['problem_no'] != problem):
                    bad_identity.append('frozen_scene')
                if bad_identity:
                    failures.append(f'{label}: identity_mismatch:{bad_identity}')
                if trace.get('row') != row:
                    failures.append(f'{label}: trace_row_mismatch')
                result = audit_events(trace, row, cfg.get('clearance_point', 'mec_center'))
                certificates[(seed, variant)] = result
                event_count += result['polygon_certified_count']
                if not result['passed']:
                    failures.append(f'{label}: certificate_audit_failed')
                detail = dict(problem=problem, seed=seed, variant=variant, certificate_audit=result)
                if variant == baseline and seeds[seed].get('source_seed') is not None:
                    old_seed = seeds[seed]['source_seed']
                    if seeds[seed]['seed_hex'] != reference_manifest['seeds'][old_seed]['seed_hex']:
                        failures.append(f'{label}: incorrect_reference_seed_mapping')
                    old_row = read_json(reference/f'q{problem}'/'rows'/f'{baseline}_{old_seed:04d}.json')
                    old_trace = read_json(reference/f'q{problem}'/'traces'/f'{baseline}_{old_seed:04d}.json.gz')
                    mismatches = compare_reference(row, trace, old_row, old_trace)
                    baseline_checked += 1
                    baseline_mismatched += bool(mismatches)
                    detail['baseline_reference'] = dict(source_seed=old_seed, exact_match=not mismatches,
                                                        mismatches=mismatches)
                    if mismatches:
                        failures.append(f'{label}: baseline_not_reproduced')
                details.append(detail)
                rows.append(row)
            except (OSError, ValueError, KeyError, TypeError, IndexError, EOFError) as exc:
                failures.append(f'{label}: missing_or_invalid_evidence:{exc}')
        evaluated = evaluate_rows(rows, expected, baseline)
        acceptance = read_json(folder/'acceptance.json')
        if acceptance.get('accept') is not True or evaluated['acceptance']['accept'] is not True:
            failures.append(f'{prefix}: evaluation_acceptance_failed')
        for key in ('expected_run_count', 'observed_run_count', 'full_clear_rate', 'status_counts'):
            if acceptance.get(key) != evaluated['acceptance'].get(key):
                failures.append(f'{prefix}: stale_acceptance:{key}')
        try:
            with (folder/'cases.csv').open(encoding='utf-8-sig', newline='') as file:
                csv_rows = list(csv.DictReader(file))
            csv_map = {(int(r['seed']), r['variant']): r for r in csv_rows}
            if len(csv_map) != len(csv_rows) or set(csv_map) != set(expected):
                failures.append(f'{prefix}: stale_or_duplicate_cases_csv')
            for row in rows:
                saved = csv_map.get((row['seed'], row['variant']), {})
                if any(saved.get(key) != ('' if value is None else str(value)) for key, value in row.items()):
                    failures.append(f'{prefix}:{row["seed"]}:{row["variant"]}: csv_row_mismatch')
        except (OSError, ValueError, KeyError) as exc:
            failures.append(f'{prefix}: cases_csv_unavailable:{exc}')
        by_pair = {(r['seed'], r['variant']): r for r in rows}
        problem_pairs = []
        for seed in range(len(seeds)):
            a, b = by_pair.get((seed, candidate)), by_pair.get((seed, baseline))
            if a is None or b is None:
                continue
            success = lambda r: classify_run(r)['valid_full_clear']
            jointly_successful = success(a) and success(b)
            delta = a['mean_time_per_source']-b['mean_time_per_source'] if jointly_successful else None
            record = dict(problem=problem, seed=seed, seed_hex=seeds[seed]['seed_hex'],
                          source_seed=seeds[seed].get('source_seed'), baseline=baseline, candidate=candidate,
                          baseline_status=b.get('run_status'), candidate_status=a.get('run_status'),
                          baseline_time_per_source=b.get('mean_time_per_source'), candidate_time_per_source=a.get('mean_time_per_source'),
                          time_delta_s_per_source=delta,
                          comparison=('not_timed_failure' if delta is None else 'win' if delta < -1e-6 else 'loss' if delta > 1e-6 else 'tie'),
                          actual_polygon_clear_travel_delta_m=(a.get('polygon_clear_travel_m', 0)-b.get('polygon_clear_travel_m', 0)),
                          candidate_same_state_counterfactual_saving_m=a.get('same_state_clear_saving_m'),
                          whole_run_distance_delta_m=a['distance']-b['distance'])
            # These additive fields keep the requested A/B counters and travel
            # ledger independently reproducible from the compact paired CSV.
            for label, source in (('baseline', b), ('candidate', a)):
                classified = classify_run(source)
                record[label+'_status'] = classified['run_status']
                record[label+'_valid_full_clear'] = classified['valid_full_clear']
                record[label+'_invalid_evidence'] = bool(classified['validation_errors'])
                for field in ('total', 'cleared', 'virtual_time_s', 'distance',
                              'polygon_clear_travel_m', 'same_state_clear_saving_m',
                              'polygon_certified_count', 'near_certified_count',
                              'polygon_zero_move_count', 'nccp_fallback_count'):
                    record[label+'_'+field] = source.get(field)
                certificate = certificates.get((seed, source['variant']), {})
                for field in ('current_position_certified_count', 'current_position_certified_case_count',
                              'zero_move_clear_count', 'zero_move_clear_case_count',
                              'minimum_same_state_saving_m'):
                    record[label+'_'+field] = certificate.get(field)
            problem_pairs.append(record)
        pairs.extend(problem_pairs)
        timed = [r for r in problem_pairs if r['time_delta_s_per_source'] is not None]
        baseline_rows = [r for r in rows if r['variant'] == baseline]
        candidate_rows = [r for r in rows if r['variant'] == candidate]
        problems[problem_string] = dict(expected_cases_per_variant=len(seeds), baseline=baseline, candidate=candidate,
            evaluation_acceptance=acceptance, recomputed_acceptance=evaluated['acceptance'],
            baseline_metrics=physical_summary(baseline_rows, certificates, len(seeds)),
            candidate_metrics=physical_summary(candidate_rows, certificates, len(seeds)),
            paired=dict(n=len(timed), wins=sum(r['comparison']=='win' for r in timed),
                        losses=sum(r['comparison']=='loss' for r in timed), ties=sum(r['comparison']=='tie' for r in timed),
                        mean_delta_s_per_source=float(np.mean([r['time_delta_s_per_source'] for r in timed])) if timed else None,
                        maximum_regression=max(0., max(r['time_delta_s_per_source'] for r in timed)) if timed else None,
                        maximum_time_delta=max((r['time_delta_s_per_source'] for r in timed), default=None),
                        worst_regression_case=max(timed, key=lambda r:r['time_delta_s_per_source']) if timed else None))
    if development and baseline_checked != len(seeds)*len(manifest['configs']):
        failures.append('not_all_development_baselines_compared_to_reference')
    if event_count == 0:
        failures.append('polygon_clearance_branch_not_exercised')
    return dict(schema='nccp-evidence-audit-v1', cohort=manifest.get('cohort'),
                input_directory=str(cohort), reference_directory=str(reference),
                manifest_sha256=sha256(cohort/'manifest.json'), source_hash=source_hash,
                solver_reference_commit=manifest.get('solver_reference_commit'),
                reference_manifest_commit=reference_manifest.get('git_commit'),
                shared_seed_plan_hash=manifest.get('shared_seed_plan_hash'),
                report_script_sha256=sha256(__file__),
                certificate_checks=dict(fp64=True, exact_binary_rational_squared_distances=True,
                    mec_radius_content_checked=True, safety_tolerance=0.,
                    redundant_bookkeeping_tolerance=NUMERIC_BOOKKEEPING_TOL),
                baseline_reference=dict(applicable=development, checked=baseline_checked,
                                        mismatched=baseline_mismatched,
                                        note='New holdout scenes have no historical output; require the development reproduction gate.'),
                polygon_event_count=event_count, problems=problems,
                performance_conclusion_allowed=not failures, failure_reasons=sorted(set(failures)),
                metric_definitions=dict(
                    full_clear_rate='schema-valid FULL_CLEAR rows / planned cases per variant',
                    exception_count='classified EXCEPTION runs; TIMEOUT and PROTOCOL_ERROR are separate disjoint categories',
                    protocol_count='classified PROTOCOL_ERROR runs, including malformed evidence reclassification',
                    time_quantiles='linear percentiles of T/N over valid FULL_CLEAR cases only; P50 is the median',
                    movement_totals='unqualified movement/time totals use valid FULL_CLEAR rows; total_observed_* retain all observed rows',
                    current_position_certified_case_count='cases with at least one polygon certificate event whose start passes FP64 and exact binary-rational radius checks; excludes near-only clears',
                    zero_move_clear_count='successful zero-travel polygon-certified plus near-observation clear events',
                    minimum_same_state_saving_m='minimum stored-state MEC travel minus actual polygon clear travel, independently recomputed from raw events'),
                local_research_acceptance='NOT_ASSESSED: shadow action equivalence and the full requested acceptance checklist are separate evidence',
                evidence='local recovered practice engine; not official tests; designed deterministic seeds, not IID sampling',
                guarantee='Per polygon-certified clear: feasible landing and same-state travel no greater than MEC-center travel. No whole-run non-increase guarantee.',
                certificate_details=details), pairs


def number(value, decimals=3):
    return '—' if value is None else f'{value:.{decimals}f}'


def markdown(audit):
    allowed = audit['performance_conclusion_allowed']
    lines = [f'# NCCP 配对实验：{audit["cohort"]}', '',
             ('证据门禁通过，可以比较本次测得的性能。' if allowed else
              '**证据门禁未通过：下列数字只供排错，拒绝性能结论。**'), '',
             '本报告只使用虚拟时间。每方案的平均秒/源为合法全清除案例 T/N 的等权平均；P50 为中位数，分位数采用线性插值。全清除率以计划案例数为分母，失败另列而不进入耗时分位数。', '',
             '本次使用本地恢复的演练引擎及预先固定的确定性种子，不是官方正式测试，也不是 IID 抽样。', '',
             f'历史基线逐动作精确比对：{audit["baseline_reference"]["checked"]} 条，差异 {audit["baseline_reference"]["mismatched"]} 条。', '']
    for problem in ('4', '3'):
        if problem not in audit['problems']:
            continue
        data = audit['problems'][problem]
        lines += [f'## Q{problem}', '', '| 方案 | 合法全清除/计划 | 全清除率 | 平均秒/源 | P50 | P95 | P99 | 最大 | 总虚拟时间/s |',
                  '|---|---:|---:|---:|---:|---:|---:|---:|---:|']
        for label, key in (('冻结基线', 'baseline_metrics'), ('NCCP', 'candidate_metrics')):
            values = data[key]
            rate = values.get('full_clear_rate')
            lines.append(f'| {label} | {values.get("n",0)}/{data["expected_cases_per_variant"]} | '+
                         ('—' if rate is None else f'{100*rate:.2f}%')+' | '+
                         ' | '.join(number(values.get(field)) for field in ('mean','P50','P95','P99','max','total_virtual_time_s'))+' |')
        paired = data['paired']
        lines += ['', f'双方成功的配对共 {paired["n"]} 例：NCCP 胜 {paired["wins"]}、负 {paired["losses"]}、平 {paired["ties"]}。'
                  f'平均差（NCCP−基线）为 {number(paired["mean_delta_s_per_source"])} 秒/源；'
                  f'最大回退为 {number(paired["maximum_regression"])} 秒/源。', '',
                  '| 指标 | 冻结基线 | NCCP |', '|---|---:|---:|']
        fields = [('异常案例数（EXCEPTION）', 'exception_count'),
                  ('协议失败案例数（PROTOCOL_ERROR）', 'protocol_count'),
                  ('超时案例数（TIMEOUT）', 'timeout_count'),
                  ('部分清除案例数', 'partial_clear_count'),
                  ('零清除案例数', 'zero_clear_count'),
                  ('证据格式异常案例数（可与上述状态重叠）', 'invalid_evidence_count'),
                  ('全部已观察案例虚拟时间/s（含失败）', 'total_observed_virtual_time_s'),
                  ('全部已观察案例移动总米数（含失败）', 'total_observed_distance_m'),
                  ('多边形证书 clear 实际移动总米数', 'total_polygon_clear_travel_m'),
                  ('多边形证书 clear 平均移动米/源', 'mean_polygon_clear_travel_m_per_source'),
                  ('同状态 MEC 圆心反事实节省总米数', 'same_state_counterfactual_saving_m'),
                  ('全程实际移动总米数', 'total_distance_m'),
                  ('多边形证书清除次数', 'polygon_certified_count'),
                  ('near 观测后原地清除次数', 'near_certified_count'),
                  ('多边形证书零移动清除次数', 'polygon_zero_move_count'),
                  ('当前位置已具多边形证书的案例数', 'current_position_certified_case_count'),
                  ('当前位置已具多边形证书的事件数', 'current_position_certified_count'),
                  ('全部零移动清除次数（near+多边形）', 'zero_move_clear_count'),
                  ('含零移动清除的案例数', 'zero_move_clear_case_count'),
                  ('单事件同状态节省最小值/m', 'minimum_same_state_saving_m'),
                  ('NCCP 回退 MEC 次数', 'nccp_fallback_count')]
        for label, field in fields:
            lines.append(f'| {label} | {number(data["baseline_metrics"].get(field))} | {number(data["candidate_metrics"].get(field))} |')
        worst = paired['worst_regression_case']
        if worst:
            lines += ['', f'最大差案例：本批索引 {worst["seed"]}，完整种子 `{worst["seed_hex"]}`；'
                      f'基线 {number(worst["baseline_time_per_source"])} → NCCP {number(worst["candidate_time_per_source"])} 秒/源。']
        if allowed and data['baseline_metrics'].get('n') and data['candidate_metrics'].get('n'):
            changes = {field:100*(1-data['candidate_metrics'][field]/data['baseline_metrics'][field])
                       for field in ('mean','P50','P95','P99','max')}
            lines += ['', 'NCCP 相对基线的下降比例（负数表示变差）：'+
                      '、'.join(f'{field} {value:.4f}%' for field,value in changes.items())+'。']
        lines.append('')
    lines += ['## 解释边界', '',
              'NCCP 只证明：在同一当前状态、清除触发条件不变时，认证落点覆盖整个可行多边形，且当前 clear 段不比前往 MEC 圆心更远。落点改变会影响后续测点、发现路线与调度，不能据此推出全程不劣。', '',
              '“同状态反事实节省”是在候选自己的每个清除状态比较两个落点后求和；它不是独立基线轨迹的移动差，也不是全程虚拟时间差。near 原地清除与多边形证书零移动事件分开统计。', '',
              '“当前位置已具多边形证书”使用每个清除事件保存的 polygon 和 start 重新检查，因此基线即使选择移动到 MEC 中心，也会计入这个状态指标。案例数对每个案例至多计一次；near 不计入这个多边形状态指标。', '',
              '证书审计使用 FP64 范数与 Fraction(float) 精确二进制有理数平方距离双检，重新检查全部顶点到清除落点不超过安全半径、MEC 中心到全部顶点不超过声明的 MEC 半径、当前段不长于前往 MEC 中心，并将事件逐一匹配真实 clear 动作和成功响应。精确检查在坐标相减前转换为有理数，防止范数或减法向下舍入。安全与局部不劣条件不添加 epsilon；仅冗余账本核对允许 1e-9 米浮点差，动作虚拟时间账本容许 1.1e-6 秒的序列化误差。', '',
              '运行秒数不用于得分或 CPU/CUDA 加速结论。验收文件只作为有效性门禁，性能改善与证据有效性分开报告。', '',
              '本报告的 performance_conclusion_allowed 只表示这批配对证据可用于描述性能，不代表本地研发 ACCEPT。shadow 模式动作轨迹一致性、完整测试与其余验收条件仍须由独立证据确认。']
    if audit['failure_reasons']:
        lines += ['', '## 拒绝原因', '']+[f'- {reason}' for reason in audit['failure_reasons']]
    return '\n'.join(lines)+'\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True, type=Path)
    parser.add_argument('--reference', required=True, type=Path)
    parser.add_argument('--development-audit', type=Path)
    args = parser.parse_args()
    cohort, reference = args.input.resolve(), args.reference.resolve()
    try:
        audit, pairs = audit_cohort(cohort, reference, args.development_audit)
    except Exception as exc:
        audit, pairs = dict(schema='nccp-evidence-audit-v1', cohort=cohort.name,
            performance_conclusion_allowed=False, failure_reasons=[f'incomplete_or_invalid_evidence:{type(exc).__name__}:{exc}'],
            baseline_reference=dict(checked=0, mismatched=0), polygon_event_count=0, problems={},
            report_script_sha256=sha256(__file__)), []
    (cohort/'NCCP_AUDIT.json').write_text(json.dumps(json_safe(audit), ensure_ascii=False,
        indent=2, allow_nan=False), encoding='utf-8')
    (cohort/'REPORT.md').write_text(markdown(audit), encoding='utf-8')
    fields = list(pairs[0]) if pairs else ['problem','seed','baseline','candidate','comparison']
    with (cohort/'NCCP_PAIRS.csv').open('w', encoding='utf-8-sig', newline='') as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        writer.writerows(pairs)
    print(json.dumps(dict(cohort=audit['cohort'], performance_conclusion_allowed=audit['performance_conclusion_allowed'],
                         baseline_reference=audit['baseline_reference'], polygon_event_count=audit['polygon_event_count'],
                         failure_reasons=audit['failure_reasons']), ensure_ascii=False, indent=2))
    if not audit['performance_conclusion_allowed']:
        raise SystemExit(2)


if __name__ == '__main__':
    main()
