import pytest
from pathlib import Path
import pandas as pd
import numpy as np
ROOT=Path(__file__).resolve().parents[1]

@pytest.mark.integration
def test_historical_fuel_columns_reconcile():
    d=pd.read_csv(ROOT/'data/processed/historical_fuel_benchmarks.csv')
    p=d.pivot(index=['period','PROD_TYPE'],columns='SALES_TYPEDesc',values='figure')
    np.testing.assert_allclose(p[['Ship stores','Aircraft stores','Sales for local consumption','Re-exports']].sum(axis=1),p['Overall sales'],atol=2,rtol=0)
    assert p.loc[(2009,'E_1'),'Aircraft stores']==4476500
    assert p.loc[(2005,'E_4'),'Ship stores']==4304520

@pytest.mark.integration
def test_historical_annual_constraints():
    c=pd.read_csv(ROOT/'outputs/diagnostics/consistency_checks.csv')
    historic=c[c['check'].str.contains('historical_annual')]
    assert len(historic)>0 and historic.passed.all()
    a=pd.read_csv(ROOT/'data/processed/airport.csv')
    assert (a[a.date<'2013-01-01'].groupby(a.date.str[:4]).size()==12).all()
    assert a[a.date=='2005-01-01'].movements.item()==20300

@pytest.mark.integration
def test_activity_overlap_preserved_since_2020_after_removing_calibration():
    old=pd.read_csv(ROOT/'tests/fixtures/sector_monthly_before_history_extension.csv')
    new=pd.read_csv(ROOT/'outputs/hong_kong_sector_monthly.csv')
    overlap=old.merge(new,on=['date','sector'],suffixes=['_old','_new'])
    overlap=overlap[(overlap.date>='2020-01-01') & ~overlap.sector.isin(['Transport','Road Transport','Domestic Navigation','International Shipping','Industry']) & (overlap.date<='2026-06-01')]
    np.testing.assert_allclose(overlap.ktCO2_old,overlap.ktCO2_new/overlap.calibration_scale,equal_nan=True,rtol=1e-10,atol=1e-8)

@pytest.mark.integration
def test_industrial_historical_years_are_validation_only():
    from cmhk.benchmarks.official import crt_benchmarks
    refs=crt_benchmarks()
    assert not refs[refs.year.isin([2005,2020])].calibration_anchor.any()
    d=pd.read_csv(ROOT/'outputs/diagnostics/industry_proxy_components.csv')
    assert d.anchor_year.eq(2021).all()
    assert d.coefficient.nunique()==1
