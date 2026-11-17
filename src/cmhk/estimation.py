"""Build sector proxies, transport accounts and calibrated eight-sector results."""
import json
from importlib.metadata import version
from cmhk.paths import ROOT, code_hashes
from cmhk.context import EstimationContext
from cmhk.sectors.buildings import observed_gas, stationary
from cmhk.sectors.bunkers import bunkers
from cmhk.sectors.road import road
from cmhk.sectors.power import power
from cmhk.diagnostics import summarize


def main():
    ctx = EstimationContext()
    ctx.out.mkdir(exist_ok=True)
    for folder in ['diagnostics', 'provenance']:
        (ctx.out / folder).mkdir(exist_ok=True)
    stationary(ctx, observed_gas(ctx))
    bunkers(ctx)
    road(ctx)
    power(ctx)
    if ctx.config.get('near_realtime', {}).get('enabled'):
        from cmhk.nowcast import apply
        ctx.rows[:] = apply(ctx.rows, ctx.config, ctx.root)
    summarize(ctx)
    from cmhk.sectors.road_proxy import export_road_proxy
    from cmhk.benchmarks.transport import main as audit_transport
    from cmhk.sectors.transport_annual import main as annual_transport
    from cmhk.sectors.navigation import main as monthly_transport
    export_road_proxy(ctx.root)
    audit_transport()
    annual_transport()
    monthly_transport()
    from cmhk.assembly import build_point_estimate
    build_point_estimate(ctx.root)
    manifest = {'as_of': ctx.config['as_of'], 'config': ctx.config,
        'package_versions': {p: version(p) for p in ['pandas','numpy','scipy','requests','pdfplumber','matplotlib','holidays','openpyxl']},
        'sources': {str(p.relative_to(ctx.raw)): json.loads(p.read_text()) for p in sorted(ctx.raw.rglob('*.source.json'))},
        'code_sha256': code_hashes(),
        'stages': ['buildings', 'bunkers', 'road', 'power', 'nowcast', 'transport', 'official_calibration', 'aggregation']}
    (ctx.out / 'provenance/run_manifest.json').write_text(json.dumps(manifest, indent=2))


if __name__ == '__main__':
    main()
