import pytest
from pathlib import Path
import json
import sys
import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from cmhk.nowcast import ratio, quarterly, backtest, intensity_prediction, company_mix
from cmhk.revision_history import record_snapshot


def test_quarter_ratio_uses_only_prior_complete_quarters():
    periods=pd.period_range('2020Q1',periods=12,freq='Q')
    x=pd.Series(10.,index=periods); y=pd.Series(20.,index=periods)
    assert ratio(y,x,periods[8],4)==2.
    y.loc[periods[8]:]=9999
    assert ratio(y,x,periods[8],4)==2.
    y.loc[periods[7]]=np.nan
    assert np.isnan(ratio(y,x,periods[8],4))
    monthly=pd.Series([1.,2.,3.,4.,5.],index=pd.date_range('2021-01-01',periods=5,freq='MS'))
    assert len(quarterly(monthly))==1 and quarterly(monthly).iloc[0]==6


def test_selection_is_unchanged_by_evaluation_targets():
    dates=pd.date_range('2013-01-01','2025-12-01',freq='MS')
    x=pd.Series(np.arange(len(dates))+10.,index=dates)
    target=quarterly(x)*2
    settings={'ratio_windows':[4,8],'selection_start_year':2017,'selection_end_year':2022,
              'evaluation_start_year':2023,'evaluation_end_year':2025}
    _,_,name,window=backtest(target,{'one':x,'two':x**2},settings)
    target.loc['2023Q1':]*=20
    records,_,name2,window2=backtest(target,{'one':x,'two':x**2},settings)
    assert (name,window)==(name2,window2)
    assert (pd.PeriodIndex(records.training_through,freq='Q')<pd.PeriodIndex(records.period,freq='Q')).all()


def test_intensity_forecast_excludes_target_and_limits_trend():
    history=pd.Series({2020:1.,2021:.5,2022:.1,2023:900.})
    settings={'power_trend_damping':.5,'power_max_annual_change':.1}
    assert np.isclose(intensity_prediction(history,2023,'damped_trend',settings),.09)
    assert intensity_prediction(history,2023,'hold',settings)==.1


def test_hke_half_update_is_weighted_and_not_assigned_to_all_hong_kong(tmp_path):
    import openpyxl
    import shutil
    (tmp_path/'outputs').mkdir()
    (tmp_path/'data/raw/power').mkdir(parents=True)
    book=openpyxl.Workbook()
    clp=book.active;clp.title='CLP stations';clp.append(['year','station','fuel','output','basis','x','y','url'])
    for station,fuel in [('Black Point C','Gas'),('Black Point D','Gas'),('Castle Peak A','Coal'),('Castle Peak B','Coal')]:
        clp.append([2025,station,fuel,100,'Net sent out','','','https://example.test/source'])
    hke=book.create_sheet('HKE generation');hke.append(['year','half','gas','coal','re','total','x','url'])
    for year,half,g,c in [(2025,'H1',50,50),(2025,'H2',50,50),(2026,'H1',100,0)]:
        hke.append([year,half,g,c,0,g+c,'','https://example.test/source'])
    book.save(tmp_path/'data/raw/power/HK_power_generation_2010_2025.xlsx')
    settings={'company_proxy_gas_tCO2_per_MWh':.4,'company_proxy_coal_tCO2_per_MWh':.9,'as_of':'2026-08-01'}
    update=company_mix(tmp_path,2025,settings,tmp_path/'outputs')
    factor,refs=update(pd.Timestamp('2026-06-01'))
    assert np.isclose(factor,2/3+(1/3)*(.4/.65))
    assert '2026H1' in refs
    assert update(pd.Timestamp('2026-08-01'))==(1.,'')  # No H2 observation fabricated.


@pytest.mark.integration
def test_snapshots_idempotent_and_revision_replaces_forecast(tmp_path):
    d=pd.DataFrame(dict(date=pd.to_datetime(['2026-07-01']),sector=['Power'],ktCO2=[10.],
        temporal_status=['activity_nowcast'],prediction_model=['ratio'],reference_period=['2026Q2'],as_of=['2026-09-01']))
    record_snapshot(d,tmp_path)
    folder=tmp_path/'outputs/near_realtime/history'
    previous=json.loads((folder/'latest.json').read_text())
    record_snapshot(d,tmp_path)
    assert json.loads((folder/'latest.json').read_text())==previous
    d['ktCO2']=12.;d['temporal_status']='statistically_constrained'
    record_snapshot(d,tmp_path)
    latest=json.loads((folder/'latest.json').read_text())
    changes=pd.read_csv(folder/f"revisions_{latest['sha256']}.csv")
    assert changes.revision_ktCO2.item()==2 and np.isclose(changes.revision_pct.item(),20)


@pytest.mark.integration
def test_delivered_forecasts_and_quarter_conservation():
    points=pd.read_csv(ROOT/'outputs/hong_kong_sector_monthly.csv',parse_dates=['date'])
    assert points.loc[points.temporal_status.eq('activity_nowcast'),'nowcast_log_sigma'].gt(0).all()
    for sector in ['Power','International Aviation','International Shipping']:
        block=points[points.sector.eq(sector)].set_index('date')
        assert block.loc['2026-07-01','temporal_status']=='activity_nowcast'
        assert block.loc['2026-08-01','temporal_status']=='activity_nowcast'
        cfg=json.loads((ROOT/'configs/model.json').read_text())
        assert block.loc[block.index+pd.offsets.MonthEnd()>pd.Timestamp(cfg['as_of']),'ktCO2'].isna().all()
    raw=pd.read_csv(ROOT/'outputs/diagnostics/monthly_scenarios.csv',parse_dates=['date'])
    shipping=raw[raw.sector.eq('International Shipping')].copy()
    shipping['quarter']=shipping.date.dt.to_period('Q')
    complete=shipping[shipping.date.between('2013-01-01','2026-06-01')].groupby(['quarter','scenario']).ktCO2.sum().unstack()
    np.testing.assert_allclose(complete.net_tonnage,complete.all_arrivals,rtol=1e-12)
    historical=shipping[shipping.date<'2013-01-01'].groupby([shipping.date.dt.year,'scenario']).ktCO2.sum().unstack()
    np.testing.assert_allclose(historical.net_tonnage,historical.all_arrivals,rtol=1e-12)
    selection=json.loads((ROOT/'outputs/near_realtime/manifest.json').read_text())['selection']
    assert selection['International Shipping']['proxy']=='net_tonnage'
    cfg=json.loads((ROOT/'configs/model.json').read_text())
    dates=points.loc[points.ktCO2.notna(),'date']
    assert (dates+pd.offsets.MonthEnd()<=pd.Timestamp(cfg['as_of'])).all()
