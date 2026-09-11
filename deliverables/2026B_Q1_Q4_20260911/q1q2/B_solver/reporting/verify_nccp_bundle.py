"""Read-only delivery verification: ZIP hashes, 2136 row/trace pairs, 12 summaries.

Usage: python verify_nccp_bundle.py delivery.zip
No extraction, local evidence lookup, policy execution or network access.
This checks delivery integrity and recorded performance arithmetic, not geometry
proofs or the original experimental outcomes by rerunning them.
"""
import argparse
from collections import defaultdict
import csv
import gzip
import hashlib
import io
import json
import math
import ntpath
from pathlib import PurePosixPath
import re
import stat
import sys
import zipfile


COHORTS = {'development100': 100, 'holdout256': 256}
SELECTORS = ('mec_center', 'nccp', 'segment_entry')
ROOTS = {'evidence', 'B_solver', 'reference_grid_v1_519', 'engine'}
OPTIONAL_ROOTS = {'inputs'}
TOP_LEVEL_FILES = {'README.md', 'BUILD_BUNDLE.py'}
STAGES = ('discovery', 'active_localization', 'diagnostic', 'optical_fallback', 'certified_clear')
REQUIRED_ROW = ('seed', 'seed_hex', 'problem', 'variant', 'run_status', 'total', 'cleared', 'clear_rate',
                'error', 'mean_time_per_source', 'virtual_time_s', 'distance', 'config_hash', 'scene_hash',
                'source_hash', 'clearance_point', 'clear_attempts', 'detect_count', 'switch_count')
SUMMARY_TOLERANCE_S = 1e-9


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def reject_constant(value):
    raise ValueError('Nonfinite JSON constant: '+value)


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, 'Duplicate JSON key: '+key)
        result[key] = value
    return result


def read_json(data):
    return json.loads(data.decode('utf-8-sig'), object_pairs_hook=unique_object, parse_constant=reject_constant)


def safe_member(name):
    require(isinstance(name, str) and name and '\\' not in name and ':' not in name and
            not any(ord(char) < 32 for char in name), 'Unsafe ZIP member name: '+repr(name))
    path = name[:-1] if name.endswith('/') else name
    parts = path.split('/')
    require(not PurePosixPath(path).is_absolute() and all(part not in ('', '.', '..') for part in parts),
            'Absolute or traversing ZIP member: '+repr(name))
    reserved = {'CON', 'PRN', 'AUX', 'NUL'} | {prefix+str(n) for prefix in ('COM', 'LPT') for n in range(1, 10)}
    require(all(part == part.rstrip(' .') and part.split('.')[0].upper() not in reserved for part in parts),
            'Unsafe Windows ZIP member: '+repr(name))
    return path.casefold()


def original_key(path):
    require(isinstance(path, str) and path and (ntpath.isabs(path) or path.startswith('/')),
            'Manifest original_path is not absolute: '+repr(path))
    return ntpath.normcase(ntpath.normpath(path.replace('/', '\\')))


def finite(value, label):
    require(not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value),
            'Missing or nonfinite number: '+label)
    return float(value)


def percentile(sorted_values, percentile_value):
    """Linear interpolation at (n-1)*q, independently of NumPy."""
    position = (len(sorted_values)-1)*percentile_value/100
    lower = math.floor(position)
    upper = math.ceil(position)
    return sorted_values[lower]+(sorted_values[upper]-sorted_values[lower])*(position-lower)


def verify_manifest(archive):
    infos, names, normalized = archive.infolist(), {}, set()
    for info in infos:
        key = safe_member(info.filename)
        require(key not in normalized, 'Duplicate or case-colliding ZIP member: '+info.filename)
        normalized.add(key)
        require(not stat.S_ISLNK(info.external_attr >> 16), 'ZIP symbolic link: '+info.filename)
        names[info.filename] = info
    require('BUNDLE_MANIFEST.json' in names, 'Top-level BUNDLE_MANIFEST.json missing')
    files = {name for name, info in names.items() if not info.is_dir() and name != 'BUNDLE_MANIFEST.json'}
    require(all(name.split('/')[0] in ROOTS | OPTIONAL_ROOTS or name in TOP_LEVEL_FILES for name in files),
            'Unexpected top-level payload path')
    require(ROOTS.issubset({name.split('/')[0] for name in files}), 'Required bundle section missing')
    file_keys = {name.casefold() for name in files}
    for name in files:
        parent = PurePosixPath(name).parent
        while str(parent) != '.':
            require(str(parent).casefold() not in file_keys, 'ZIP file/directory collision: '+str(parent))
            parent = parent.parent
    manifest = read_json(archive.read('BUNDLE_MANIFEST.json'))
    require(isinstance(manifest.get('files'), list) and manifest['files'], 'Manifest file list missing or empty')
    records, original_paths, total_bytes = {}, defaultdict(list), 0
    for record in manifest['files']:
        name = record['path']
        safe_member(name)
        require(name not in records and name in files, 'Duplicate or absent manifest payload: '+name)
        require(isinstance(record.get('bytes'), int) and not isinstance(record['bytes'], bool) and record['bytes'] >= 0,
                'Invalid manifest byte count: '+name)
        require(isinstance(record.get('sha256'), str) and re.fullmatch('[0-9a-fA-F]{64}', record['sha256']),
                'Invalid manifest SHA256: '+name)
        require(names[name].file_size == record['bytes'], 'ZIP/manifest size mismatch: '+name)
        digest, count = hashlib.sha256(), 0
        with archive.open(name) as stream:
            for chunk in iter(lambda: stream.read(1024*1024), b''):
                digest.update(chunk)
                count += len(chunk)
        require(count == record['bytes'] and digest.hexdigest() == record['sha256'].lower(),
                'Payload SHA256/size mismatch: '+name)
        records[name] = record
        original_paths[original_key(record['original_path'])].append(name)
        total_bytes += count
    require(set(records) == files, 'Unlisted ZIP payloads: '+repr(sorted(files-set(records))[:5]))
    for original, members in original_paths.items():
        require(len({(records[name]['sha256'].lower(), records[name]['bytes']) for name in members}) == 1,
                'Same original_path maps to different payloads: '+original)
        members.sort()
    reference_traces = sum(name.startswith('reference_grid_v1_519/') and '/traces/' in name and name.endswith('.json.gz') for name in files)
    require(reference_traces == 200, 'Expected 200 archived reference traces')
    require(sum(name.startswith('engine/') and name.endswith('.py') for name in files) == 3,
            'Expected three recovered-engine Python files')
    return records, original_paths, dict(payload_files=len(files), payload_bytes=total_bytes,
                                       reference_traces=reference_traces, manifest_sha256=hashlib.sha256(archive.read('BUNDLE_MANIFEST.json')).hexdigest())


def verify_row(csv_row, row, trace_row):
    label = '/'.join(csv_row[key] for key in ('cohort', 'problem', 'seed', 'selector'))
    require(all(key in row for key in REQUIRED_ROW), 'Required physical/identity fields missing: '+label)
    require(isinstance(trace_row, dict) and trace_row == row, 'trace.row differs from original row: '+label)
    for field, value in row.items():
        require(field in csv_row and csv_row[field] == ('' if value is None else str(value)),
                'Threeway CSV differs from original row: '+label+'/'+field)
        if isinstance(value, (int, float)):
            finite(value, label+'/'+field)
    total, cleared = row['total'], row['cleared']
    require(isinstance(total, int) and total > 0 and isinstance(cleared, int) and 0 <= cleared <= total,
            'Invalid source counts: '+label)
    require(row['seed'] >= 0 and row['clearance_point'] == csv_row['selector'], 'Seed/selector mismatch: '+label)
    require(math.isclose(row['clear_rate'], cleared/total, rel_tol=0, abs_tol=1e-12), 'Clear rate mismatch: '+label)
    for field in ('virtual_time_s', 'distance', 'mean_time_per_source'):
        require(finite(row[field], label+'/'+field) >= 0, 'Negative physical metric: '+label+'/'+field)
    if cleared:
        require(math.isclose(row['mean_time_per_source'], row['virtual_time_s']/cleared, rel_tol=0, abs_tol=1e-8),
                'Time/source denominator mismatch: '+label)
    present = [f'stage_{name}_s' in row for name in STAGES]
    if any(present):
        require(all(present), 'Incomplete stage-cost fields: '+label)
        require(math.isclose(math.fsum(row[f'stage_{name}_s'] for name in STAGES), row['virtual_time_s'],
                             rel_tol=0, abs_tol=1e-6), 'Stage/virtual-time mismatch: '+label)
    for field in ('scene_hash', 'config_hash', 'source_hash', 'seed_hex'):
        require(isinstance(row[field], str) and re.fullmatch('[0-9a-fA-F]{64}', row[field]), 'Malformed '+field+': '+label)
    valid_full = row['run_status'] == 'FULL_CLEAR' and cleared == total and not row['error']
    require(valid_full, 'Final delivery includes a non-full-clear case: '+label)
    return valid_full


def verify_threeway(archive, records, original_paths):
    csv_path, audit_path = 'evidence/threeway/THREEWAY_CASES.csv', 'evidence/threeway/AUDIT.json'
    require(csv_path in records and audit_path in records, 'Threeway evidence missing')
    reader = csv.DictReader(io.StringIO(archive.read(csv_path).decode('utf-8-sig')))
    require(reader.fieldnames and len(reader.fieldnames) == len(set(reader.fieldnames)), 'Missing or duplicate CSV columns')
    cases, audit = list(reader), read_json(archive.read(audit_path))
    require(len(cases) == 2136, 'Expected exactly 2136 threeway cases')
    require(audit.get('passed') is True and audit.get('formal_runs') == 0, 'Threeway audit not accepted or includes formal runs')
    require(audit.get('original_runs_referenced') == 1424 and audit.get('new_segment_runs') == 712,
            'Threeway run provenance counts differ')
    expected = {(cohort, str(problem), str(seed), selector) for cohort, count in COHORTS.items()
                for problem in (3, 4) for seed in range(count) for selector in SELECTORS}
    found, groups, scenes, used_paths = set(), defaultdict(list), defaultdict(set), set()
    for case in cases:
        key = tuple(case[field] for field in ('cohort', 'problem', 'seed', 'selector'))
        require(key in expected and key not in found, 'Unexpected or duplicate case identity: '+repr(key))
        found.add(key)
        members = {}
        for kind in ('row', 'trace'):
            original = original_key(case[kind+'_path'])
            require(original in original_paths, 'Referenced '+kind+' absent from manifest: '+case[kind+'_path'])
            name = original_paths[original][0]
            require(records[name]['sha256'].lower() == case[kind+'_sha256'].lower(), 'CSV/manifest hash mismatch: '+name)
            require((kind, original) not in used_paths, 'Case row/trace path reused: '+case[kind+'_path'])
            used_paths.add((kind, original))
            members[kind] = name
        row = read_json(archive.read(members['row']))
        trace = read_json(gzip.decompress(archive.read(members['trace'])))
        full = verify_row(case, row, trace.get('row'))
        groups['/'.join((key[0], key[1], key[3]))].append((row, full))
        scenes[key[:3]].add((row['seed_hex'], row['scene_hash'], row['total']))
    require(found == expected, 'Missing threeway cases')
    require(all(len(values) == 1 for values in scenes.values()), 'Paired selectors use different scenes/source counts')
    require(set(audit.get('summaries', {})) == set(groups) and len(groups) == 12, 'Expected exactly 12 recorded summary groups')
    recalculated = {}
    for group, selected in sorted(groups.items()):
        valid = [row for row, full in selected if full]
        values = sorted(row['mean_time_per_source'] for row in valid)
        summary = dict(n=len(valid), observed_count=len(selected), planned_count=COHORTS[group.split('/')[0]],
                       full_clear_count=len(valid), full_clear_rate=len(valid)/len(selected),
                       mean=math.fsum(values)/len(values), P50=percentile(values, 50), P95=percentile(values, 95),
                       P99=percentile(values, 99), max=values[-1])
        recorded = audit['summaries'][group]
        for field, value in summary.items():
            other = finite(recorded.get(field), group+'/'+field)
            tolerance = SUMMARY_TOLERANCE_S if field in ('mean', 'P50', 'P95', 'P99', 'max') else 0
            require(math.isclose(value, other, rel_tol=0, abs_tol=tolerance), 'Recomputed summary mismatch: '+group+'/'+field)
        recalculated[group] = summary
    return dict(rows_verified=len(cases), traces_verified=len(cases), full_clear_count=sum(v['full_clear_count'] for v in recalculated.values()),
                groups_verified=len(groups), summaries=recalculated, row_trace_comparison='entire original row, exact',
                csv_row_comparison='every original row field, exact string serialization',
                summary_absolute_tolerance_s=SUMMARY_TOLERANCE_S, percentile_method='linear at (n-1)*q')


def verify_bundle(path):
    with zipfile.ZipFile(path, 'r') as archive:
        records, original_paths, manifest_result = verify_manifest(archive)
        evidence_result = verify_threeway(archive, records, original_paths)
    return dict(passed=True, zip=str(path), manifest=manifest_result, threeway=evidence_result,
                execution='read-only ZIP; no extraction, solver, simulator or network',
                limitation='Integrity and arithmetic verification; no independent rerun of geometry certificates or experiments')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('zip', help='Final delivery ZIP path')
    args = parser.parse_args()
    try:
        result = verify_bundle(args.zip)
    except (KeyError, TypeError, ValueError, OSError, RuntimeError, zipfile.BadZipFile, EOFError) as exc:
        print(json.dumps(dict(passed=False, error=f'{type(exc).__name__}: {exc}'), ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
