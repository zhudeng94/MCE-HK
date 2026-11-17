"""Ordered, isolated calculation stages; source refresh is always explicit."""
import json
import os
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timezone

from cmhk.paths import ROOT, PACKAGE

CORE = [
    ('prepare', 'cmhk.sources.prepare'),
    ('baseline', 'cmhk.benchmarks.official'),
    ('estimate', 'cmhk.estimation'),
    ('uncertainty', 'cmhk.uncertainty.monte_carlo'),
    ('validate', 'cmhk.validation'),
    ('export', 'cmhk.export'),
]
COMPARISONS = [('inventory', 'cmhk.analysis.inventory'), ('climate-trace', 'cmhk.analysis.climate_trace')]


def run(root=ROOT, *, comparisons=False, report=False, tests=False):
    """Use one process per stage, so each workspace/config has independent state."""
    stages = CORE.copy()
    if report:
        stages += [('report', 'cmhk.analysis.report')]
    if comparisons:
        stages += COMPARISONS
    env = os.environ.copy()
    env['CMHK_WORKSPACE'] = str(root)
    env['PYTHONPATH'] = str(PACKAGE.parent) + os.pathsep + env.get('PYTHONPATH', '')
    env.setdefault('MPLCONFIGDIR', str(root / '.tmp/matplotlib'))
    env.update(OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1')
    records = []
    out = root / 'outputs/provenance'
    out.mkdir(parents=True, exist_ok=True)
    for i, (name, module) in enumerate(stages, 1):
        print(f'[{i}/{len(stages)}] {name}: {module}', flush=True)
        record = {'stage': name, 'module': module, 'started_at': datetime.now(timezone.utc).isoformat()}
        records.append(record)
        (out / 'pipeline.json').write_text(json.dumps(records, indent=2))
        result = subprocess.run([sys.executable, '-m', module], cwd=root, env=env)
        record.update(returncode=result.returncode, finished_at=datetime.now(timezone.utc).isoformat())
        (out / 'pipeline.json').write_text(json.dumps(records, indent=2))
        if result.returncode:
            raise SystemExit(result.returncode)
    if tests:
        subprocess.run([sys.executable, '-m', 'pytest', '-q', 'tests', '-m', 'not comparison and not research'], cwd=root, env=env, check=True)
    return records
