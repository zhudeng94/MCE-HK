"""Command-line stages: fetch -> prepare -> baseline -> estimate -> uncertainty."""
import argparse
import os
from pathlib import Path
import runpy


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', type=Path, help='Directory containing configs/model.json, configs/, data/ and outputs/')
    sub = parser.add_subparsers(dest='command', required=True)
    fetch = sub.add_parser('fetch', help='Acquire raw inputs using configs/sources.json')
    fetch.add_argument('--refresh', action='store_true')
    fetch.add_argument('--list', action='store_true')
    fetch.add_argument('--only', action='append')
    for command, help_ in [
        ('check-inputs', 'Check required snapshots and sidecar hashes without downloading'),
        ('prepare', 'Normalize cached raw inputs'),
        ('baseline', 'Export CRT benchmarks and source cells'),
        ('estimate', 'Calculate department proxies, calibrate and aggregate'),
        ('uncertainty', 'Propagate uncertainty using configured draws'),
        ('validate', 'Check core result invariants'),
        ('export', 'Export the monthly results data package'),
        ('report', 'Build the optional result report and figures'),
        ('compare', 'Compare to cached official/Climate TRACE inventories')]:
        sub.add_parser(command, help=help_)
    run = sub.add_parser('run', help='Reproduce the core dataset from cached inputs')
    run.add_argument('--comparisons', action='store_true')
    run.add_argument('--report', action='store_true')
    run.add_argument('--test', action='store_true')
    args = parser.parse_args(argv)
    if args.workspace:
        os.environ['CMHK_WORKSPACE'] = str(args.workspace.resolve())
    # Import after selecting the workspace; individual stages run in fresh processes.
    from cmhk.paths import ROOT
    if not (ROOT/'configs/model.json').exists():
        parser.error(f'Workspace has no configs/model.json: {ROOT}. Pass --workspace /path/to/workspace')
    if args.command == 'run':
        from cmhk.sources.audit import check_inputs
        check_inputs()
        from cmhk.pipeline import run
        run(ROOT, comparisons=args.comparisons, report=args.report, tests=args.test)
        return None
    if args.command == 'fetch':
        import sys
        options = ['--refresh'] if args.refresh else []
        if args.list:
            options.append('--list')
        for name in args.only or []:
            options += ['--only', name]
        sys.argv = ['cmhk fetch', *options]
        runpy.run_module('cmhk.sources.download', run_name='__main__')
        return None
    if args.command == 'check-inputs':
        from cmhk.sources.audit import check_inputs
        check_inputs()
        return None
    if args.command == 'compare':
        from cmhk.pipeline import COMPARISONS
        import subprocess, sys
        for _, module in COMPARISONS:
            subprocess.run([sys.executable, '-m', module], check=True)
        return
    stages = dict(__import__('cmhk.pipeline', fromlist=['CORE']).CORE)
    stages['report'] = 'cmhk.analysis.report'
    import sys
    sys.argv = [f'cmhk {args.command}']
    runpy.run_module(stages[args.command], run_name='__main__')
    return None
