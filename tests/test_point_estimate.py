import pytest
from pathlib import Path
import sys
import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from cmhk.aggregation import sum_complete,SCOPES

def test_missing_sector_never_becomes_zero():
    frame=pd.DataFrame({'a':[10,10],'b':[2,np.nan]})
    result=sum_complete(frame)
    assert result.iloc[0]==12 and pd.isna(result.iloc[1])

@pytest.mark.integration
def test_industry_annual_fuel_excludes_electricity_and_only_calibrates_2021():
    d=pd.read_csv(ROOT/'outputs/diagnostics/industry_proxy_components.csv',parse_dates=['date'])
    a=pd.read_csv(ROOT/'outputs/diagnostics/industry_proxy_calibration.csv').set_index('year')
    f=pd.read_csv(ROOT/'outputs/diagnostics/industry_annual_fuel.csv').set_index('year')
    assert list(a.index)==[2021]
    assert np.isclose(a.loc[2021,'total_ktCO2'],647.815559413)
    np.testing.assert_allclose(f.fuel_TJ,f.gas_lpg_TJ+f.oil_coal_TJ)
    totals=d.groupby(d.date.dt.year).ktCO2.sum()
    np.testing.assert_allclose(totals.reindex(f.index),f.fuel_TJ/f.loc[2021,'fuel_TJ']*a.loc[2021,'total_ktCO2'])
    assert f.loc[2005,'source_edition']==2017 and f.loc[2020,'source_edition']==2026
    assert np.isclose(f.loc[2005,'fuel_TJ'],5173)
    assert np.isclose(f.loc[2021,'fuel_TJ'],4044)
    for name,col in [('gaseous_fuels','gas_lpg_TJ'),('liquid_and_solid_fuels','oil_coal_TJ')]:
        sums=d[d.component.eq(name)].groupby(d.date.dt.year).fuel_TJ.sum()
        np.testing.assert_allclose(sums.reindex(f.index),f[col])


@pytest.mark.integration
def test_total_reconciles_and_annual_uses_same_months():
    sectors=pd.read_csv(ROOT/'outputs/hong_kong_sector_monthly.csv',parse_dates=['date']).pivot(index='date',columns='sector',values='ktCO2')
    monthly=pd.read_csv(ROOT/'outputs/hong_kong_total_monthly.csv',parse_dates=['date'])
    annual=pd.read_csv(ROOT/'outputs/hong_kong_total_annual.csv')
    assert len(monthly)==22*12*2 and not monthly.duplicated(['date','scope']).any()
    for scope,cols in SCOPES.items():
        actual=monthly[monthly.scope==scope].set_index('date').ktCO2
        np.testing.assert_allclose(actual,sum_complete(sectors[cols]),equal_nan=True)
        assert actual.dropna().index.max()==sectors[list(SCOPES[scope])].dropna().index.max()
        assert actual.dropna().index.min()==pd.Timestamp('2008-01-01')
        a=annual[(annual.scope==scope)&(annual.year==2024)].iloc[0]
        assert a.months==12 and a.full_year
        assert np.isclose(a.ktCO2,actual.loc['2024'].sum())
        prior=actual.loc['2023'].sum()
        assert np.isclose(a.yoy_same_months_pct,(a.ktCO2/prior-1)*100)
        for missing_year in [2005,2006,2007]:
            absent=annual[(annual.scope==scope)&(annual.year==missing_year)].iloc[0]
            assert absent.months==0 and not absent.full_year and pd.isna(absent.ktCO2)
            assert pd.isna(absent.yoy_same_months_pct)


@pytest.mark.integration
def test_road_and_residual_follow_only_road_activity():
    sectors=pd.read_csv(ROOT/'outputs/hong_kong_sector_monthly.csv',parse_dates=['date']).pivot(index='date',columns='sector',values='ktCO2')
    proxy=pd.read_csv(ROOT/'outputs/transport_extension/monthly_transport_proxy.csv',parse_dates=['date']).set_index('date')
    assert len(sectors.columns)==8 and 'Transport' not in sectors
    nav=sectors['Domestic Navigation']
    road=sectors['Road Transport']
    np.testing.assert_allclose(nav,proxy.marine_calibrated_proxy_ktCO2,equal_nan=True)
    raw=pd.read_csv(ROOT/'outputs/diagnostics/road_monthly_proxy.csv',parse_dates=['date']).set_index('date').ktCO2.reindex(road.index)
    from cmhk.benchmarks.official import crt_benchmarks
    refs=crt_benchmarks(years=(2021,)).set_index('sector').official_ktCO2
    expected=raw*refs['Road Transport']/raw.loc['2021'].sum()
    np.testing.assert_allclose(road,expected,equal_nan=True)
    assert np.isclose((road+nav).loc['2021'].sum(),refs['Transport'])
    scenarios=pd.read_csv(ROOT/'outputs/uncertainty/scenario_sensitivity/monthly_scenarios.csv')
    road_paths=scenarios[scenarios.sector.eq('Road Transport')].scenario.unique()
    assert set(road_paths)=={'published','ev_mileage_0.7','ev_mileage_1','ev_mileage_1.3'}
    assert not any('ev_mileage' in x for x in scenarios[scenarios.sector.eq('Domestic Navigation')].scenario.unique())
    assert road.loc['2005'].notna().all() and nav.loc['2005'].isna().all()


@pytest.mark.integration
def test_recent_totals_are_partial_not_annualized():
    annual=pd.read_csv(ROOT/'outputs/hong_kong_total_annual.csv')
    monthly=pd.read_csv(ROOT/'outputs/hong_kong_total_monthly.csv',parse_dates=['date'])
    for scope in SCOPES:
        row=annual[(annual.scope==scope)&(annual.year==2026)].iloc[0]
        d=monthly[monthly.scope.eq(scope)].set_index('date').ktCO2
        assert row.months==d.loc['2026'].notna().sum() and not row.full_year
        assert np.isclose(row.ktCO2,d.loc['2026'].sum())
        assert np.isclose(row.yoy_same_months_pct,(row.ktCO2/d.reindex(d.loc['2026'].dropna().index-pd.DateOffset(years=1)).sum()-1)*100)
