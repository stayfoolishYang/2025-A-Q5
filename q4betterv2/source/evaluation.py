"""Success-first evaluation of frozen runs; this module never runs a simulator.

``evaluate_rows`` does not mutate input evidence. ``accept`` is a validity and
completion gate, not a claim of speed improvement. Supply the expected pairs
from the experiment plan, never infer them from the observed output.
"""
import math
from collections import Counter, defaultdict
from numbers import Integral

import numpy as np


STATUSES = ('FULL_CLEAR', 'PARTIAL_CLEAR', 'ZERO_CLEAR', 'EXCEPTION',
            'TIMEOUT', 'PROTOCOL_ERROR')
REQUIRED = ('seed', 'variant', 'total', 'cleared', 'error',
            'mean_time_per_source', 'distance', 'runtime')
COUNTERS = ('fallback_count', 'grid_points', 'clear_attempts',
            'optical_clear_attempts', 'diagnostic_count', 'detect_count', 'switch_count')


def expected_pairs(seeds, variants):
    """Build the planned Cartesian product (duplicates remain detectable)."""
    return [(seed, variant) for seed in seeds for variant in variants]


def _integer(value):
    if isinstance(value, (bool, np.bool_)):
        raise ValueError('boolean is not an integer count')
    if isinstance(value, Integral):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value, 10)
        except ValueError:
            pass
    number = float(value)
    if not math.isfinite(number) or not number.is_integer() or abs(number) > 2**53:
        raise ValueError('expected finite integer')
    return int(number)


def _pair(seed, variant):
    if not isinstance(variant, str) or not variant.strip():
        raise ValueError('expected nonempty variant')
    return _integer(seed), variant


def exception_status(error):
    """Map a caught exception to a failure class; no API call is performed."""
    name = type(error).__name__ if isinstance(error, BaseException) else ''
    message = (name + ' ' + str(error)).lower()
    if isinstance(error, TimeoutError) or any(word in message for word in (
            'timeouterror', 'timed out', 'deadline', 'time budget', 'time limit')):
        return 'TIMEOUT'
    if any(word in message for word in ('protocolerror', 'protocol error',
            'http ', 'httperror', 'rejected /', 'invalid measurement result',
            'invalid clear result', 'invalid virtual time', 'accepted response',
            'missing or nonfinite bearing', 'remaining real-time budget')):
        return 'PROTOCOL_ERROR'
    return 'EXCEPTION'


def classify_run(row):
    """Return a copy carrying run_status, validation_errors, and valid_full_clear.

    Required numeric strings are accepted for CSV input. Missing/invalid evidence
    never becomes a successful row, even if its producer declared FULL_CLEAR.
    Raw measurements, including failure times, are left untouched.
    """
    result = dict(row)
    errors = [f'missing:{key}' for key in REQUIRED if key not in row]
    parsed = {}
    for key in ('seed', 'total', 'cleared', *COUNTERS):
        if key not in row:
            continue
        try:
            parsed[key] = _integer(row[key])
            if key != 'seed' and parsed[key] < (1 if key == 'total' else 0):
                raise ValueError('count outside allowed range')
        except (ValueError, TypeError, OverflowError):
            errors.append(f'invalid:{key}')
    for key in ('mean_time_per_source', 'distance', 'runtime', 'clear_rate',
                'virtual_time', 'virtual_time_s'):
        if key not in row:
            continue
        try:
            number = float(row[key])
            if isinstance(row[key], bool) or not math.isfinite(number) or number < 0:
                raise ValueError('expected finite nonnegative number')
            parsed[key] = number
        except (ValueError, TypeError, OverflowError):
            errors.append(f'invalid:{key}')
    if 'variant' in row and (not isinstance(row['variant'], str) or not row['variant'].strip()):
        errors.append('invalid:variant')
    if 'error' in row and not isinstance(row['error'], str):
        errors.append('invalid:error')
    for key in ('scene_hash', 'config_hash'):
        if key in row and (not isinstance(row[key], str) or not row[key].strip()):
            errors.append(f'invalid:{key}')
    total, cleared = parsed.get('total'), parsed.get('cleared')
    if total is not None and cleared is not None:
        if cleared > total:
            errors.append('cleared_exceeds_total')
        if total > 0 and 'clear_rate' in parsed and not math.isclose(
                parsed['clear_rate'], cleared / total, abs_tol=1e-9, rel_tol=1e-9):
            errors.append('clear_rate_inconsistent_with_counts')

    def check_finite(value, path):
        if isinstance(value, dict):
            for key, child in value.items():
                check_finite(child, f'{path}.{key}')
        elif isinstance(value, (list, tuple)):
            for index, child in enumerate(value):
                check_finite(child, f'{path}[{index}]')
        elif isinstance(value, (float, np.floating)) and not math.isfinite(value):
            errors.append(f'nonfinite:{path}')
    check_finite(row, 'row')
    declared = row.get('run_status')
    if declared is not None and declared not in STATUSES:
        errors.append('invalid:run_status')
    count_status = ('FULL_CLEAR' if total and cleared == total else
                    'PARTIAL_CLEAR' if cleared and cleared > 0 else 'ZERO_CLEAR')
    if declared in ('FULL_CLEAR', 'PARTIAL_CLEAR', 'ZERO_CLEAR') and declared != count_status:
        errors.append('run_status_inconsistent_with_counts')
    if declared in ('EXCEPTION', 'TIMEOUT', 'PROTOCOL_ERROR'):
        status = declared
    elif row.get('error'):
        status = exception_status(row['error'])
    else:
        status = count_status
    if errors and status not in ('EXCEPTION', 'TIMEOUT', 'PROTOCOL_ERROR'):
        status = 'PROTOCOL_ERROR'
    result.update(run_status=status, validation_errors=sorted(set(errors)),
                  valid_full_clear=status == 'FULL_CLEAR' and not errors)
    return result


def _quantiles(values):
    if not values:
        return {key: None for key in ('mean', 'median', 'P90', 'P95', 'P99', 'max')}
    values = np.asarray(values, dtype=float)
    return dict(mean=float(values.mean()), median=float(np.median(values)),
                **{f'P{q}': float(np.percentile(values, q)) for q in (90, 95, 99)},
                max=float(values.max()))


def evaluate_rows(rows, expected_pairs=None, baseline_name='P4_current'):
    """Evaluate raw dictionaries against an explicit list of (seed, variant).

    Returns summary, acceptance, classified_rows, and worst10. Only successful,
    schema-valid, uniquely identified planned runs enter timing statistics.
    Both paired runs must additionally describe the same scene (when supplied).
    All output is JSON-serializable except raw nonfinite evidence, which callers
    should preserve in CSV and sanitize to null in derived JSON artifacts.
    """
    rows = [classify_run(row) for row in rows]
    expected, plan_errors = [], []
    if expected_pairs is None:
        plan_errors.append('expected_pairs_not_supplied')
    else:
        for index, pair in enumerate(expected_pairs):
            try:
                if len(pair) != 2:
                    raise ValueError('not a pair')
                expected.append(_pair(*pair))
            except (ValueError, TypeError, OverflowError):
                plan_errors.append(f'invalid_expected_pair:{index}')
    expected_set = set(expected)
    if not expected:
        plan_errors.append('empty_expected_plan')
    if len(expected_set) != len(expected):
        plan_errors.append('duplicate_expected_pairs')
    if expected_set:
        seeds = {pair[0] for pair in expected_set}
        variants = {pair[1] for pair in expected_set}
        if expected_set != {(seed, variant) for seed in seeds for variant in variants}:
            plan_errors.append('expected_plan_not_cartesian')
    observed = defaultdict(list)
    for row in rows:
        try:
            observed[_pair(row.get('seed'), row.get('variant'))].append(row)
        except (ValueError, TypeError, OverflowError):
            pass
    duplicates = sorted(pair for pair, items in observed.items() if len(items) != 1)
    missing = sorted(expected_set - set(observed))
    unexpected = sorted(set(observed) - expected_set)
    unique = {pair: items[0] for pair, items in observed.items()
              if len(items) == 1 and pair in expected_set}
    scene_mismatches, total_mismatches, config_mismatches = [], [], []
    for seed in sorted({pair[0] for pair in expected_set}):
        same_seed = [row for (s, _), row in unique.items() if seed == s]
        hashes = [row.get('scene_hash') if isinstance(row.get('scene_hash'), str) else None
                  for row in same_seed]
        if any(hashes) and (not all(hashes) or len(set(hashes)) != 1):
            scene_mismatches.append(seed)
        totals = {_integer(row['total']) for row in same_seed if not row['validation_errors']}
        if len(totals) > 1:
            total_mismatches.append(seed)
    for variant in sorted({pair[1] for pair in expected_set}):
        same_variant = [row for (_, v), row in unique.items() if v == variant]
        hashes = [row.get('config_hash') if isinstance(row.get('config_hash'), str) else None
                  for row in same_variant]
        if any(hashes) and (not all(hashes) or len(set(hashes)) != 1):
            config_mismatches.append(variant)
    invalid = [dict(index=index, seed=row.get('seed'), variant=row.get('variant'),
                    errors=row['validation_errors']) for index, row in enumerate(rows)
               if row['validation_errors']]
    failure_reasons = list(plan_errors)
    if not rows:
        failure_reasons.append('empty_observed_rows')
    for condition, reason in ((missing, 'missing_expected_pairs'),
                              (unexpected, 'unexpected_pairs'),
                              (duplicates, 'duplicate_pairs'),
                              (invalid, 'invalid_run_evidence'),
                              (scene_mismatches, 'paired_scene_hash_mismatch'),
                              (total_mismatches, 'paired_source_count_mismatch'),
                              (config_mismatches, 'variant_config_hash_mismatch')):
        if condition:
            failure_reasons.append(reason)
    counts = Counter(row['run_status'] for row in rows)
    planned_successes = sum(row['valid_full_clear'] for row in unique.values())
    if planned_successes != len(expected_set) or not expected_set:
        failure_reasons.append('not_all_expected_runs_full_clear')
    experiment_valid = bool(rows) and not (plan_errors or missing or unexpected or duplicates or invalid or
                            scene_mismatches or total_mismatches or config_mismatches)
    summaries = {}
    names = sorted({p[1] for p in expected_set} |
                   {row['variant'] for row in rows if isinstance(row.get('variant'), str)})
    for name in names:
        observed_rows = [row for row in rows if row.get('variant') == name]
        planned_rows = [row for (_, variant), row in unique.items() if variant == name]
        valid = [row for row in planned_rows if row['valid_full_clear']]
        valid_counts = [row for row in planned_rows if not row['validation_errors']]
        total = sum(int(float(row['total'])) for row in valid_counts)
        summary = dict(n=len(observed_rows), expected_n=sum(p[1] == name for p in expected_set),
                       all_clear=len(valid), timed_n=len(valid),
                       status_counts={status: sum(r['run_status'] == status for r in observed_rows)
                                      for status in STATUSES},
                       clear_rate=(sum(int(float(r['cleared'])) for r in valid_counts) / total
                                   if total else None),
                       timing_scope='valid_full_clear_unique_planned_runs_only',
                       **_quantiles([float(row['mean_time_per_source']) for row in valid]))
        summary['mean_distance'] = float(np.mean([float(r['distance']) for r in valid])) if valid else None
        summary['P95_distance'] = float(np.percentile([float(r['distance']) for r in valid], 95)) if valid else None
        for key in COUNTERS:
            summary[key] = (sum(int(float(r[key])) for r in valid)
                            if valid and all(key in r for r in valid) else None)
        fallback = [int(float(r['fallback_count'])) for r in valid if 'fallback_count' in r]
        summary['fallback_rate'] = float(np.mean(np.array(fallback) > 0)) if len(fallback) == len(valid) and valid else None
        summary['mean_fallback_grid_points'] = (summary['grid_points'] / len(valid)
                                               if valid and summary['grid_points'] is not None else None)
        summary.update(paired_time_n=0, paired_wins=0, paired_losses=0, paired_ties=0,
                       paired_success_wins=0, paired_success_losses=0, paired_both_failed=0,
                       paired_invalid_or_missing=0, paired_mean_delta=None)
        deltas = []
        if name != baseline_name:
            for seed, variant in sorted(expected_set):
                if variant != name:
                    continue
                candidate, baseline = unique.get((seed, name)), unique.get((seed, baseline_name))
                if (candidate is None or baseline is None or candidate['validation_errors']
                        or baseline['validation_errors'] or seed in scene_mismatches
                        or seed in total_mismatches or name in config_mismatches
                        or baseline_name in config_mismatches):
                    summary['paired_invalid_or_missing'] += 1
                    continue
                a, b = candidate['valid_full_clear'], baseline['valid_full_clear']
                if a and b:
                    deltas.append(float(candidate['mean_time_per_source']) - float(baseline['mean_time_per_source']))
                elif a:
                    summary['paired_success_wins'] += 1
                elif b:
                    summary['paired_success_losses'] += 1
                else:
                    summary['paired_both_failed'] += 1
        if deltas:
            summary.update(paired_time_n=len(deltas), paired_mean_delta=float(np.mean(deltas)),
                           paired_wins=sum(delta < -1e-6 for delta in deltas),
                           paired_losses=sum(delta > 1e-6 for delta in deltas),
                           paired_ties=sum(abs(delta) <= 1e-6 for delta in deltas))
        summaries[name] = summary
    candidates = [name for name in names if name != baseline_name]
    all_full = bool(expected_set) and planned_successes == len(expected_set)
    speed_valid = bool(candidates) and baseline_name in names and experiment_valid and all_full
    performance = {}
    for name in candidates:
        summary = summaries[name]
        comparison_valid = (experiment_valid and summary['expected_n'] > 0 and
                            summary['paired_time_n'] == summary['expected_n'])
        delta = summary['paired_mean_delta']
        performance[name] = dict(valid=comparison_valid, paired_time_n=summary['paired_time_n'],
                                 mean_delta=delta,
                                 outcome=('not_evaluable' if not comparison_valid else
                                          'improved' if delta < -1e-6 else
                                          'regressed' if delta > 1e-6 else 'tied'),
                                 criterion='paired mean time per source; descriptive, not a significance test')
    acceptance = dict(schema_version=1, baseline_name=baseline_name,
        expected_run_count=len(expected_set), observed_run_count=len(rows),
        all_expected_pairs_present=bool(expected_set) and not missing,
        no_unexpected_pairs=not unexpected, no_duplicate_pairs=not duplicates,
        expected_plan_valid=not plan_errors, experiment_valid=experiment_valid,
        all_runs_completed=experiment_valid and not any(counts[s] for s in ('EXCEPTION', 'TIMEOUT', 'PROTOCOL_ERROR')),
        all_runs_full_clear=experiment_valid and all_full,
        full_clear_rate=planned_successes / len(expected_set) if expected_set else None,
        status_counts={status: counts[status] for status in STATUSES},
        exception_count=counts['EXCEPTION'], timeout_count=counts['TIMEOUT'],
        protocol_error_count=counts['PROTOCOL_ERROR'], invalid_row_count=len(invalid),
        missing_pairs=missing, unexpected_pairs=unexpected, duplicate_pairs=duplicates,
        scene_hash_mismatch_seeds=scene_mismatches, invalid_rows=invalid,
        source_count_mismatch_seeds=total_mismatches, config_hash_mismatch_variants=config_mismatches,
        speed_comparison_valid=speed_valid, performance=performance,
        accept=experiment_valid and all_full, failure_reasons=sorted(set(failure_reasons)),
        accept_scope='planned data integrity and full completion only; performance reported separately')
    def worst_key(row):
        try:
            number = float(row.get('mean_time_per_source', 0))
            number = number if math.isfinite(number) else math.inf
        except (ValueError, TypeError):
            number = math.inf
        return not row['valid_full_clear'], number
    return dict(summary=summaries, acceptance=acceptance, classified_rows=rows,
                worst10=sorted(rows, key=worst_key, reverse=True)[:10])


def json_safe(value):
    """Derived JSON uses null for invalid numeric evidence (CSV retains raw data)."""
    if isinstance(value, dict):
        return {key: json_safe(child) for key, child in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(child) for child in value]
    if isinstance(value, (float, np.floating)):
        return float(value) if math.isfinite(value) else None
    if isinstance(value, np.integer):
        return int(value)
    return value
