"""Verify cached input availability and acquisition checksums before a run."""
import hashlib
import json
from cmhk.paths import ROOT


def check_inputs():
    definition = ROOT / 'configs/required_inputs.json'
    if not definition.exists():
        raise FileNotFoundError(f'Missing input contract: {definition}')
    required = json.loads(definition.read_text())
    failures = []
    count = 0
    for item in required['inputs']:
        path = ROOT / item['path']
        if not path.is_file():
            failures.append(f"Missing {item['path']}; {item['acquisition']}")
            continue
        sidecar = path.with_suffix(path.suffix + '.source.json')
        if sidecar.exists():
            meta = json.loads(sidecar.read_text())
            if hashlib.sha256(path.read_bytes()).hexdigest() != meta['sha256']:
                failures.append(f"Checksum mismatch: {item['path']}")
        elif item.get('sha256') and hashlib.sha256(path.read_bytes()).hexdigest() != item['sha256']:
            failures.append(f"Unversioned manual input changed: {item['path']}; review and update input contract")
        count += 1
    if failures:
        raise ValueError('Input check failed:\n' + '\n'.join(failures))
    print(f'{count} required input files present; available source checksums verified.', flush=True)
    return count
