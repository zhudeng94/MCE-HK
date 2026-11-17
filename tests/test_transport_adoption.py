import pytest
"""Integration checks for production scope and comparison boundaries."""
from pathlib import Path
import hashlib
import json
import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]


@pytest.mark.integration
@pytest.mark.comparison
def test_climate_trace_transport_mapping_preserves_domestic_shipping():
    folder=ROOT/'outputs/climate_trace_comparison'
    ct=pd.read_csv(folder/'climate_trace_monthly_MtCO2.csv',index_col='date')
    monthly=pd.read_csv(folder/'monthly_totals_MtCO2.csv',index_col='date')
    assert len(monthly)==len(pd.date_range(monthly.index.min(),monthly.index.max(),freq='MS'))
    assert monthly.index.min()=='2021-01-01'
    expected=ct.transportation-ct['international-aviation']-ct['international-shipping']
    np.testing.assert_allclose(monthly.ct_transport_excluding_international,expected.reindex(monthly.index))
    expected_total=ct.total-ct['international-aviation']-ct['international-shipping']
    np.testing.assert_allclose(monthly.ct_excluding_international_aviation_shipping,expected_total.reindex(monthly.index))
    mapping=pd.read_csv(folder/'annual_sector_comparison.csv')
    assert set(mapping[mapping.cmhk_sector.eq('Transport')].ct_sector)=={'transport_excluding_international'}
    assert set(mapping[mapping.cmhk_sector.eq('Road input')].ct_sector)=={'road-transportation'}


@pytest.mark.integration
def test_pipeline_provenance_is_current_and_transport_has_no_output_feedback():
    for name in ['proxy_manifest.json','monthly_manifest.json']:
        obj=json.loads((ROOT/'outputs/transport_extension'/name).read_text())
        inputs=obj.get('input_sha256',obj.get('inputs_sha256'))
        assert 'outputs/diagnostics/road_monthly_proxy.csv' in inputs
        assert 'outputs/hong_kong_sector_monthly.csv' not in inputs
        for path,checksum in inputs.items():
            assert hashlib.sha256((ROOT/path).read_bytes()).hexdigest()==checksum,path
    point=json.loads((ROOT/'outputs/provenance/point_estimate_manifest.json').read_text())
    assert point['transport_manifest_sha256']==hashlib.sha256((ROOT/'outputs/transport_extension/monthly_manifest.json').read_bytes()).hexdigest()
    run=json.loads((ROOT/'outputs/provenance/run_manifest.json').read_text())
    for name,checksum in run['code_sha256'].items():
        assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==checksum,name


@pytest.mark.integration
def test_diagnostic_road_is_not_labelled_full_transport():
    data=pd.read_csv(ROOT/'outputs/diagnostics/monthly_scenarios.csv')
    assert 'Road' in set(data.sector)
    assert 'Transport' not in set(data.sector)
    main=pd.read_csv(ROOT/'outputs/hong_kong_sector_monthly.csv')
    assert 'Transport' not in set(main.sector)
    assert {'Road Transport','Domestic Navigation'}.issubset(set(main.sector))
    assert 'Road' not in set(main.sector)
