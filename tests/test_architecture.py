"""Contracts protecting a calculation-only repository and explicit input handling."""
import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest

from cmhk.context import EstimationContext
from cmhk.benchmarks.official import MAPPING
from cmhk.sources import download


def test_sector_contexts_do_not_share_results_or_configuration():
    a = EstimationContext(config={'start_year':2021,'end_year':2021,'as_of':'2021-12-31'})
    b = EstimationContext(config={'start_year':2022,'end_year':2022,'as_of':'2022-12-31'})
    a.add(pd.Series([1.], index=pd.to_datetime(['2021-01-01'])), 'Power', 'coal', 'test', 'test', 'fixture')
    assert len(a.rows) == 1 and not b.rows
    assert a.dates[0].year == 2021 and b.dates[0].year == 2022


def test_published_mapping_and_scopes_use_one_consistent_sector_set():
    published = {x['sector'] for x in MAPPING['categories'] if x['published']}
    assert published == set(MAPPING['scopes']['covered_sectors_plus_international_bunkers'])
    assert len(published) == 8 and len(MAPPING['scopes']['covered_local_sectors']) == 6
    road = next(x for x in MAPPING['categories'] if x['sector']=='Road Transport')
    assert road['operation'] == 'transport_minus_navigation'
    assert MAPPING['baseline_year'] == 2021
    assert 2021 not in MAPPING['validation_years']


def test_cached_download_never_silently_refreshes_missing_metadata(tmp_path, monkeypatch):
    monkeypatch.setattr(download, 'RAW', tmp_path)
    path=tmp_path/'sample.csv'; path.write_text('a,b\n1,2\n')
    def unexpected_request(*args, **kwargs):
        raise AssertionError('Cache-only validation must not request the network')
    monkeypatch.setattr(download.requests, 'get', unexpected_request)
    with pytest.raises(ValueError, match='no source sidecar'):
        download.fetch(path.name, 'https://example.invalid/data')
    sidecar=path.with_suffix('.csv.source.json')
    sidecar.write_text(json.dumps({'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}))
    assert download.fetch(path.name, 'https://example.invalid/data') == path
    path.write_text('changed')
    with pytest.raises(ValueError, match='checksum mismatch'):
        download.fetch(path.name, 'https://example.invalid/data')


def test_bad_download_preserves_existing_snapshot(tmp_path, monkeypatch):
    monkeypatch.setattr(download, 'RAW', tmp_path)
    path=tmp_path/'sample.csv';path.write_text('a,b\n1,2\n')
    class Response:
        content=b'<html>temporarily unavailable</html>'
        def raise_for_status(self): pass
    monkeypatch.setattr(download.requests, 'get', lambda *a, **kw:Response())
    with pytest.raises(ValueError, match='HTML'):
        download.fetch(path.name, 'https://example.invalid/data', refresh=True)
    assert path.read_text() == 'a,b\n1,2\n'


def test_calculation_package_has_no_frontend_imports():
    import ast
    import cmhk
    for path in Path(cmhk.__file__).parent.rglob('*.py'):
        tree=ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert not (node.module or '').startswith(('web', 'satellite'))
        assert "root/'local/web/" not in path.read_text()


def test_cli_workspace_flags_are_not_forwarded_to_stage_parser(monkeypatch):
    import cmhk.cli as cli
    import sys
    calls=[]
    monkeypatch.setattr(cli.runpy, 'run_module', lambda module, **kw:calls.append((module,sys.argv.copy())))
    monkeypatch.setenv('CMHK_WORKSPACE', str(Path(__file__).resolve().parents[1]))
    assert cli.main(['--workspace', str(Path(__file__).resolve().parents[1]), 'validate']) is None
    assert calls == [('cmhk.validation', ['cmhk validate'])]


def test_cli_success_returns_no_console_exit_value(monkeypatch):
    from cmhk.cli import main
    from cmhk.sources import audit
    monkeypatch.setattr(audit, 'check_inputs', lambda:87)
    assert main(['check-inputs']) is None
