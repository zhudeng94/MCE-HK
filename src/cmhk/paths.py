"""Workspace paths and code fingerprints shared by all pipeline stages."""
import hashlib
import os
from pathlib import Path

ROOT = Path(os.environ.get('CMHK_WORKSPACE', Path(__file__).resolve().parents[2])).resolve()
PACKAGE = Path(__file__).resolve().parent
MODULES = {'model': 'kernels', 'totals': 'aggregation', 'official_baseline': 'benchmarks.official', 'fetch_data': 'sources.download', 'prepare_data': 'sources.prepare', 'historical': 'sources.historical', 'industry': 'sectors.industry', 'transport_inventory': 'benchmarks.transport', 'transport_proxy': 'sectors.transport_annual', 'transport_monthly': 'sectors.navigation', 'road_proxy': 'sectors.road_proxy', 'near_realtime': 'nowcast', 'revision_history': 'revision_history', 'point_estimate': 'assembly', 'uncertainty': 'uncertainty.monte_carlo', 'scenario_uncertainty': 'uncertainty.scenarios', 'uncertainty_totals': 'uncertainty.totals', 'report': 'analysis.report', 'compare_inventory': 'analysis.inventory', 'compare_climate_trace': 'analysis.climate_trace', 'estimate': 'estimation'}


def code_hashes(root=None, names=None):
    """Hash implementations, including sector formula modules, never legacy shims."""
    paths = sorted(PACKAGE.rglob('*.py')) if names is None else [
        PACKAGE / (MODULES.get(Path(n).stem, Path(n).stem).replace('.', '/') + '.py') for n in names]
    return {'src/cmhk/' + str(p.relative_to(PACKAGE)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
