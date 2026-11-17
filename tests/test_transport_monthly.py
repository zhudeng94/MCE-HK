from pathlib import Path
import sys
import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from cmhk.sectors.navigation import allocate_marine, disaggregate, ferry_passengers, SCENARIOS, extrapolate, annual_summary


def test_calendar_allocation_respects_leap_year_and_has_no_false_seasonality():
    d = allocate_marine(2012, 366., 732., pd.Series(dtype=float), SCENARIOS[0])
    assert d.loc['2012-02-01', 'passenger_marine_TJ'] == 29
    assert d.loc['2012-02-01', 'freight_marine_TJ'] == 58
    np.testing.assert_allclose(d.marine_TJ / d.index.days_in_month, 3.)


def test_monthly_passenger_counts_not_multiplied_by_days():
    dates = pd.date_range('2020-01-01', periods=12, freq='MS')
    pax = pd.Series(1., index=dates)
    pax.loc['2020-02-01'] = 2.
    d = allocate_marine(2020, 130., 366., pax, SCENARIOS[0])
    assert d.loc['2020-02-01', 'passenger_marine_TJ'] == 20
    assert d.loc['2020-01-01', 'passenger_marine_TJ'] == 10
    assert d.loc['2020-02-01', 'freight_marine_TJ'] == 29
    assert d.passenger_marine_TJ.sum() == 130
    with pytest.raises(ValueError, match='Weights'):
        allocate_marine(2020, 130., 366., pax.iloc[:-1], SCENARIOS[0])


def test_ferry_parser_keeps_only_complete_domestic_operator_panel(tmp_path):
    p = tmp_path/'ferry.csv'
    d = pd.DataFrame({'YR_MTH':[201301]*4, 'MODE':['Ferries']*3+['Railways'],
                      'TTD_PTO_CODE':['LFS','STF','NWFF','MTRC'], 'PAX':[1.,2.,3.,100.]})
    d.to_csv(p,index=False)
    assert ferry_passengers(p).iloc[0] == 6
    pd.concat([d,d.iloc[:1]]).to_csv(p,index=False)
    with pytest.raises(ValueError, match='Duplicate'):
        ferry_passengers(p)
    d.loc[1,'YR_MTH'] = 201302
    d.to_csv(p,index=False)
    with pytest.raises(ValueError, match='Incomplete'):
        ferry_passengers(p)


def test_disaggregation_preserves_total_and_refuses_stale_road():
    dates = pd.date_range('2021-01-01', periods=12, freq='MS')
    annual = pd.DataFrame([dict(year=2021, road_model_ktCO2=120.,
        road_calibrated_proxy_ktCO2=240., passenger_marine_TJ=24., freight_marine_TJ=12.,
        marine_TJ=36., marine_calibrated_proxy_ktCO2=60.,
        residual_assumed_proxy_ktCO2=15., transport_proxy_ktCO2=315.)]).set_index('year')
    road=pd.Series(10.,index=dates);ferry=pd.Series(1.,index=dates)
    result, checks = disaggregate(annual, road, ferry, dates, SCENARIOS[0])
    assert checks.passed.all()
    assert np.isclose(result.transport_proxy_ktCO2.sum(),315)
    np.testing.assert_allclose(result.transport_proxy_ktCO2,
        result.road_calibrated_proxy_ktCO2+result.marine_calibrated_proxy_ktCO2+result.residual_assumed_proxy_ktCO2)
    with pytest.raises(ValueError, match='regenerate annual'):
        disaggregate(annual, road*2, ferry, dates, SCENARIOS[0])
    with pytest.raises(ValueError, match='partial output calendar'):
        disaggregate(annual, road, ferry, dates[:-1], SCENARIOS[0])


@pytest.mark.integration
def test_delivered_months_conserve_annual_and_leave_unsupported_years_blank():
    out = ROOT/'outputs/transport_extension'
    monthly = pd.read_csv(out/'monthly_transport_proxy.csv', parse_dates=['date']).set_index('date')
    annual = pd.read_csv(out/'annual_transport_proxy.csv',index_col='year')
    totals = monthly.transport_proxy_ktCO2.groupby(monthly.index.year).sum(min_count=12)
    np.testing.assert_allclose(totals.loc[:2024], annual.loc[:2024].transport_proxy_ktCO2, equal_nan=True, rtol=1e-10)
    assert monthly.transport_proxy_ktCO2.notna().sum() == 17*12+12+8
    assert monthly.loc['2025':'2026-08','extrapolated'].all()
    assert monthly.loc['2026-09':,'transport_proxy_ktCO2'].isna().all()
    assert monthly.loc[:'2007','transport_proxy_ktCO2'].isna().all()
    scenarios = pd.read_csv(out/'monthly_transport_scenarios.csv',parse_dates=['date'])
    assert not scenarios.duplicated(['date','scenario']).any()
    assert pd.read_csv(out/'monthly_conservation_checks.csv').passed.all()


def test_extrapolation_uses_fixed_intensity_not_partial_year_rescaling():
    historical=pd.date_range('2024-01-01',periods=12,freq='MS')
    dates=pd.date_range('2025-01-01',periods=3,freq='MS')
    ferry=pd.Series(10.,index=historical).combine_first(pd.Series([5.,20.,30.],index=dates))
    road=pd.Series([10.,12.,14.],index=dates)
    annual=pd.DataFrame([dict(year=2021,road_model_ktCO2=100.,road_calibrated_proxy_ktCO2=200.,
        marine_TJ=50.,marine_calibrated_proxy_ktCO2=100.,transport_proxy_ktCO2=330.),
        dict(year=2024,passenger_marine_TJ=240.,freight_marine_TJ=366.)]).set_index('year')
    empty=pd.DataFrame({'transport_proxy_ktCO2':np.nan,'status':'missing','scenario':SCENARIOS[0]},index=dates)
    result,coeff=extrapolate(empty,annual,road,ferry,'2025-02-28')
    assert coeff['passenger_TJ_per_thousand_journeys']==2
    assert coeff['freight_TJ_per_day']==1
    assert result.loc['2025-01-01','passenger_marine_TJ']==10
    assert result.loc['2025-02-01','passenger_marine_TJ']==40
    assert result.loc['2025-02-01','freight_marine_TJ']==28
    assert np.isclose(result.loc['2025-02-01','transport_proxy_ktCO2'],(24+(40+28)*2)*1.1)
    assert pd.isna(result.loc['2025-03-01','transport_proxy_ktCO2'])
    # Future activity cannot affect earlier estimates.
    changed=ferry.copy();changed.loc['2025-03-01']=9999
    again,_=extrapolate(empty,annual,road,changed,'2025-02-28')
    np.testing.assert_allclose(result.transport_proxy_ktCO2,again.transport_proxy_ktCO2,equal_nan=True)
    missing,_=extrapolate(empty,annual,road,ferry.drop(pd.Timestamp('2025-02-01')),'2025-02-28')
    assert pd.isna(missing.loc['2025-02-01','transport_proxy_ktCO2'])
    with pytest.raises(ValueError,match='reference-year'):
        extrapolate(empty,annual,road,ferry.drop(pd.Timestamp('2024-02-01')),'2025-02-28')


def test_partial_year_summary_compares_identical_months_only():
    dates=pd.date_range('2025-01-01','2026-12-01',freq='MS')
    data=pd.DataFrame({'transport_proxy_ktCO2':[10.]*12+[12.]*7+[np.nan]*5,
                       'extrapolated':True},index=dates)
    data['complete']=data.transport_proxy_ktCO2.notna()
    summary=annual_summary(data)
    assert summary.loc[2026,'months']==7
    assert not summary.loc[2026,'full_year']
    assert summary.loc[2026,'transport_proxy_ktCO2']==84
    assert np.isclose(summary.loc[2026,'yoy_same_months_pct'],20)
