import pytest
from pathlib import Path
import sys
import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from cmhk.aggregation import SCOPES
from cmhk.uncertainty.totals import JointTotals


def test_joint_quantiles_preserve_covariance_and_same_month_year_changes():
    dates=pd.date_range('2020-01-01','2021-12-01',freq='MS')
    sectors=SCOPES['covered_sectors_plus_international_bunkers']
    points=pd.MultiIndex.from_product([dates,sectors],names=['date','sector']).to_frame(index=False)
    points['ktCO2']=10.
    # Future months must not be normalized to a year or interpreted as zeros.
    points.loc[points.date.ge('2021-07-01'),'ktCO2']=np.nan
    accumulator=JointTotals(points,100)
    for sector in sectors:
        valid=dates[:18]
        factor=np.linspace(0,20,100) if sector=='Power' else np.linspace(20,0,100) if sector=='Industry' else np.full(100,10.)
        accumulator.add(sector,valid,np.tile(factor,(18,1)))
    tables=accumulator.summarize()
    monthly=tables['total_monthly_uncertainty']
    local=monthly[monthly.scope.eq('covered_local_sectors')]
    # Power and Industry are perfectly anticorrelated: sum has no uncertainty.
    np.testing.assert_allclose(local.lower_95_ktCO2.iloc[:18],60)
    np.testing.assert_allclose(local.upper_95_ktCO2.iloc[:18],60)
    assert local.lower_95_ktCO2.iloc[18:].isna().all()
    annual=tables['total_annual_uncertainty']
    row=annual[annual.year.eq(2021)&annual.scope.eq('covered_local_sectors')].iloc[0]
    assert row.months==6 and not row.full_year and row.ktCO2==360
    changes=tables['annual_change_uncertainty']
    assert changes.year.eq(2021).all()
    assert changes.months.eq(6).all()
    np.testing.assert_allclose(changes[['ktCO2','lower_95_ktCO2','upper_95_ktCO2']],0,atol=1e-12)
    # Temporal correlation also persists in individual annual intervals.
    power=tables['sector_annual_uncertainty'].query("sector=='Power' and year==2021").iloc[0]
    assert np.isclose(power.lower_95_ktCO2,6*.5)
    assert np.isclose(power.upper_95_ktCO2,6*19.5)


@pytest.mark.integration
def test_delivered_aggregate_points_coverage_and_complete_years():
    folder=ROOT/'outputs/uncertainty'
    for period,key in [('monthly','date'),('annual','year')]:
        main=pd.read_csv(ROOT/f'outputs/hong_kong_total_{period}.csv').set_index([key,'scope']).sort_index()
        bands=pd.read_csv(folder/f'total_{period}_uncertainty.csv').set_index([key,'scope']).sort_index()
        pd.testing.assert_index_equal(main.index,bands.index)
        np.testing.assert_allclose(main.ktCO2,bands.ktCO2,equal_nan=True)
        assert main.ktCO2.isna().equals(bands.lower_95_ktCO2.isna())
        assert main.ktCO2.isna().equals(bands.upper_95_ktCO2.isna())
        valid=bands.dropna(subset=['ktCO2'])
        assert valid.lower_95_ktCO2.le(valid.median_ktCO2).all()
        assert valid.upper_95_ktCO2.ge(valid.median_ktCO2).all()


@pytest.mark.integration
@pytest.mark.research
def test_annual_change_figure_matches_uncertainty():
    folder=ROOT/'outputs/uncertainty'
    changes=pd.read_csv(folder/'annual_change_uncertainty.csv')
    plotted=pd.read_csv(ROOT/'outputs/figures/annual_sector_change_contributions.csv')
    check=plotted.drop_duplicates(['year','scope']).merge(changes,on=['year','scope'])
    assert len(check)==len(changes)
    np.testing.assert_allclose(check.net_change_MtCO2*1000,check.ktCO2)
    assert check.months_x.equals(check.months_y)
