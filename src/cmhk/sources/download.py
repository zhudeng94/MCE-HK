"""Cache official source files and record provenance; never cache HTTP errors as data."""
from concurrent.futures import ThreadPoolExecutor
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import requests

from cmhk.paths import ROOT, code_hashes
RAW = ROOT / 'data/raw'

def fetch(name, url, refresh=False):
    path = RAW / name
    meta = path.with_suffix(path.suffix + '.source.json')
    if path.exists() and meta.exists() and not refresh:
        expected = json.loads(meta.read_text())['sha256']
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError(f'Cached source checksum mismatch: {path}; fetch with --refresh')
        return path
    if path.exists() and not refresh:
        raise ValueError(f'Cached file has no source sidecar: {path}; inspect it before --refresh')
    response = requests.get(url, timeout=45, headers={'User-Agent': 'Mozilla/5.0'})
    response.raise_for_status()
    if not response.content:
        raise ValueError(f'Empty response: {url}')
    if path.suffix == '.pdf' and not response.content.startswith(b'%PDF'):
        raise ValueError(f'Not a PDF: {url}')
    if path.suffix in ('.csv', '.json', '.pdf') and response.content.lstrip().lower().startswith((b'<!doctype html', b'<html')):
        raise ValueError(f'HTML instead of data: {url}')
    if path.suffix == '.json':
        body = response.json()
        if body.get('header', {}).get('status', {}).get('code', 0) != 0:
            raise ValueError(f'API reported failure: {url}')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(response.content)
    meta.write_text(json.dumps(dict(url=url, retrieved_at=datetime.now(timezone.utc).isoformat(),
                                   sha256=hashlib.sha256(response.content).hexdigest()), indent=2))
    return path

def sources():
    catalog = json.loads((ROOT / 'configs/sources.json').read_text())
    for source in catalog['sources']:
        if source['acquisition'] == 'download':
            yield source['file'], source['url']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--refresh', action='store_true', help='Replace cached snapshots with newly retrieved sources')
    parser.add_argument('--list', action='store_true', help='List endpoints without downloading')
    parser.add_argument('--only', action='append', help='Download exact file name (repeatable)')
    args = parser.parse_args()
    items = list(sources())
    if args.only:
        unknown = set(args.only) - {name for name, _ in items}
        if unknown:
            parser.error(f'Unknown source files: {sorted(unknown)}')
        items = [(name,url) for name,url in items if name in args.only]
    if args.list:
        for name, url in items:
            print(f'{name}  {url}')
        return
    def run(item):
        try:
            p = fetch(*item, refresh=args.refresh)
            return {'file': item[0], 'url': item[1], 'status': 'ok', 'bytes': p.stat().st_size}
        except Exception as e:
            return {'file': item[0], 'url': item[1], 'status': 'unavailable', 'error': str(e)}
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(run, items))
    RAW.mkdir(parents=True, exist_ok=True)
    (RAW / 'download_log.json').write_text(json.dumps(results, indent=2))
    for r in results:
        print(r['file'], r['status'], r.get('bytes', r.get('error')))
    if any(r['status'] != 'ok' for r in results):
        raise SystemExit(1)

if __name__ == '__main__':
    main()
