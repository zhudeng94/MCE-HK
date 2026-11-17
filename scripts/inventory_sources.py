"""Inventory local source snapshots; do not infer licenses or retrieval dates."""
import csv
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    rows = []
    for path in sorted((ROOT / 'data/raw').rglob('*')):
        if not path.is_file() or path.name.endswith('.source.json') or path.name == 'README.md':
            continue
        sidecar = path.with_suffix(path.suffix + '.source.json')
        meta = json.loads(sidecar.read_text()) if sidecar.exists() else {}
        checksum = hashlib.sha256(path.read_bytes()).hexdigest()
        if meta.get('sha256') and meta['sha256'] != checksum:
            raise ValueError(f'Source checksum mismatch: {path.relative_to(ROOT)}')
        rows.append(dict(path=str(path.relative_to(ROOT)), bytes=path.stat().st_size,
                         sha256=checksum, url=meta.get('url', ''),
                         retrieved_at=meta.get('retrieved_at', ''),
                         provenance='source sidecar verified' if meta else 'local snapshot; provenance incomplete',
                         redistribution_status='not assessed'))
    target = ROOT / 'docs/source_inventory.csv'
    with target.open('w', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=['path', 'bytes', 'sha256', 'url', 'retrieved_at', 'provenance', 'redistribution_status'])
        writer.writeheader()
        writer.writerows(rows)
    print(f'Inventoried {len(rows)} source files: {target.relative_to(ROOT)}')


if __name__ == '__main__':
    main()
