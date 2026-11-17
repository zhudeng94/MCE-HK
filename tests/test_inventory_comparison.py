import pytest
from pathlib import Path
import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'outputs/official_inventory_comparison'

@pytest.mark.integration
@pytest.mark.comparison
def test_official_pdf_years_and_wrapped_last_row():
    d=pd.read_csv(OUT/'official_ghg_1990_2024.csv').set_index('year')
    assert list(d.index)==list(range(1990,2025))
    assert d.loc[2024,'total_ghg']==33200
    assert d.loc[2024,'energy_industries']==20400

@pytest.mark.integration
@pytest.mark.comparison
def test_matched_transport_and_bunker_scope():
    d=pd.read_csv(OUT/'matched_co2_benchmarks.csv')
    y=d[d.year==2021].set_index('sector')
    assert np.isclose(y.loc['Transport','official_ktCO2'],6338.25666002)
    assert np.isclose(y.loc['Road','official_ktCO2'],5558.1985875)
    assert not bool(y.loc['Transport','calibration_anchor'])
    local=['Power','Industry','Road Transport','Domestic Navigation','Residential','Commercial']
    assert np.isclose(y.loc[local,'official_ktCO2'].sum(),y.loc['covered_local_sectors','official_ktCO2'])
    assert bool(y.loc['Industry','calibration_anchor'])
    assert bool(y.loc['Power','calibration_anchor'])
    assert y.loc[local+['International Aviation','International Shipping'],'calibration_anchor'].all()
    assert np.isclose(y.loc['covered_plus_international','official_ktCO2'],
        y.loc['covered_local_sectors','official_ktCO2']+y.loc['International Aviation','official_ktCO2']+y.loc['International Shipping','official_ktCO2'])

@pytest.mark.integration
@pytest.mark.comparison
def test_change_computed_from_matched_co2_not_ghg():
    d=pd.read_csv(OUT/'matched_co2_changes.csv')
    r=d[(d.sector=='covered_local_sectors')&(d.period=='2020-2021')].iloc[0]
    b=pd.read_csv(OUT/'matched_co2_benchmarks.csv')
    local=b[b.sector.eq('covered_local_sectors')].set_index('year')
    expected=(local.loc[2021,'official_ktCO2']/local.loc[2020,'official_ktCO2']-1)*100
    assert np.isclose(r.official_change_pct,expected)
    assert pd.isna(local.loc[2005,'model_ktCO2'])
    other=d[(d.sector=='Residential')&(d.period=='2020-2021')].iloc[0]
    assert other.model_change_pct<0<other.official_change_pct
