"""Read attachments without modifying them; preserve source hashes."""
from pathlib import Path
import csv
import hashlib
import json
import shutil
import sys
import openpyxl

ROOT = Path(__file__).resolve().parents[1]

def main(source):
    source = Path(source)
    dest = ROOT / 'data'
    dest.mkdir(exist_ok=True)
    manifest = {}
    for filename, output, header in [('附件1.xlsx', 'boundary.csv', ['time_s', 'temperature_C', 'moisture_kg_kg']), ('附件2.xlsx', 'radius.csv', ['time_s', 'radius_cm'])]:
        path = source / '附件' / filename
        rows = list(openpyxl.load_workbook(path, data_only=True).active.values)[1:]
        assert all(all(isinstance(v, (int, float)) for v in row) for row in rows)
        assert rows[0][0] == 0 and all(a[0] < b[0] for a, b in zip(rows, rows[1:]))
        with (dest / output).open('w', newline='', encoding='utf-8') as f:
            w = csv.writer(f); w.writerow(header); w.writerows(rows)
        manifest[filename] = {'source': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'rows': len(rows), 'last_time_s': rows[-1][0]}
    (dest / 'templates').mkdir(exist_ok=True)
    for path in (source / '附件' / '附件3').glob('*.xlsx'):
        shutil.copy2(path, dest / 'templates' / path.name)
    pdf = source / 'A题.pdf'
    shutil.copy2(pdf, dest / pdf.name)
    manifest[pdf.name] = {'source': str(pdf), 'sha256': hashlib.sha256(pdf.read_bytes()).hexdigest()}
    (dest / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(manifest, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    main(sys.argv[1])
