from pathlib import Path
import sys

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from cmhk.uncertainty.scenarios import calendar_alternative, industry_alternatives, envelopes, transport_alternatives


def test_calendar_preserves_quarters_and_leap_days_but_not_partial_periods():
    dates = pd.date_range('2024-01-01', periods=5, freq='MS')
    source = pd.Series([10., 20., 61., 100., 200.], index=dates)
    result = calendar_alternative(source, 'Q')
    np.testing.assert_allclose(result.iloc[:3], [31., 29., 31.])
    assert result.iloc[3:].isna().all()
    assert np.isclose(result.iloc[:3].sum(), source.iloc[:3].sum())


def test_asymmetric_envelope_missing_zero_and_duplicate_records():
    dates = pd.date_range('2024-01-01', periods=3, freq='MS')
    point = pd.DataFrame(dict(date=dates, sector='Power', ktCO2=[100., 0., np.nan]))
    scenarios = pd.concat([point.assign(scenario='primary'),
                           point.assign(scenario='lower', ktCO2=[90., 0., 5.]),
                           point.assign(scenario='upper', ktCO2=[140., 1., 8.])])
    result = envelopes(point, scenarios)
    assert result.loc[0, 'down_pct'] == 10
    assert result.loc[0, 'up_pct'] == 40
    assert result.loc[0, 'half_range_pct'] == 25
    assert result.loc[1, ['down_pct', 'up_pct']].isna().all()
    assert result.loc[2, ['lower_ktCO2', 'upper_ktCO2']].isna().all()
    with pytest.raises(ValueError, match='Duplicate'):
        envelopes(point, pd.concat([scenarios, scenarios.iloc[:1]]))


def test_industrial_calendar_preserves_each_annual_fuel_total():
    dates=pd.date_range('2020-01-01','2023-03-01',freq='MS')
    parts=pd.concat([pd.DataFrame(dict(date=dates,component=name,ktCO2=np.arange(len(dates))+1.))
                     for name in ['gaseous_fuels','liquid_and_solid_fuels']])
    paths=industry_alternatives(parts,None)
    for year in [2020,2021,2022]:
        assert np.isclose(paths['selected/observed_proxy'].loc[str(year)].sum(),paths['selected/calendar_days'].loc[str(year)].sum())
    assert paths['selected/calendar_days'].loc['2023'].isna().all()


def test_transport_recalibrates_each_road_and_preserves_benchmark_years():
    dates = pd.date_range('2021-01-01', '2025-02-01', freq='MS')
    roads = pd.concat([pd.DataFrame(dict(date=dates, sector='Road', scenario=name, ktCO2=value))
                       for name, value in [('one', 10.), ('two', 20.)]])
    marine = pd.DataFrame(dict(date=dates, scenario='ferry',
                               marine_calibrated_proxy_ktCO2=5., transport_proxy_ktCO2=15.))
    marine.loc[marine.date.eq('2025-02-01'), 'transport_proxy_ktCO2'] = np.nan
    annual = pd.DataFrame(dict(year=[2021, 2023, 2024], marine_TJ=[60., 60., 120.],
                                passenger_marine_TJ=[30., 30., 60.],
                                freight_marine_TJ=[30., 30., 60.])).set_index('year')
    ferry = pd.Series(1., index=dates)
    result = transport_alternatives(roads, marine, annual, ferry,
                                    {'road': 120., 'marine': 60., 'transport': 198.},
                                    2021, [2023, 2024], 2024)
    np.testing.assert_allclose(result['one/ferry/reference_2024'], result['two/ferry/reference_2024'], equal_nan=True)
    assert np.isclose(result['one/ferry/reference_2024'].loc['2021'].sum(), 198)
    np.testing.assert_allclose(result['one/ferry/reference_2023'].loc[:'2024'],
                               result['one/ferry/reference_2024'].loc[:'2024'])
    assert result['one/ferry/reference_2023'].loc['2025-01-01'] < result['one/ferry/reference_2024'].loc['2025-01-01']
    assert all(pd.isna(v.loc['2025-02-01']) for v in result.values())


@pytest.mark.integration
def test_delivered_ranges_cover_all_published_months_without_changing_estimates():
    main = pd.read_csv(ROOT / 'outputs/hong_kong_sector_monthly.csv').set_index(['date', 'sector']).sort_index()
    result = pd.read_csv(ROOT / 'outputs/uncertainty/scenario_sensitivity/sector_monthly_uncertainty.csv').set_index(['date', 'sector']).sort_index()
    pd.testing.assert_index_equal(main.index, result.index)
    np.testing.assert_allclose(main.ktCO2, result.ktCO2, equal_nan=True)
    assert result.lower_ktCO2.isna().equals(main.ktCO2.isna())
    assert result.upper_ktCO2.isna().equals(main.ktCO2.isna())
    valid = result.dropna(subset=['ktCO2'])
    assert (valid.lower_ktCO2 <= valid.ktCO2 + 1e-8).all()
    assert (valid.upper_ktCO2 >= valid.ktCO2 - 1e-8).all()
    assert (valid.available_scenarios >= 2).all()
    assert pd.read_csv(ROOT / 'outputs/uncertainty/scenario_sensitivity/checks.csv').passed.all()
    aviation = valid.xs('International Aviation', level='sector')
    assert aviation.max_abs_deviation_pct.max() > 0


@pytest.mark.integration
def test_delivered_bands_match_scenarios_and_latest_snapshot():
    out = ROOT / 'outputs/uncertainty/scenario_sensitivity'
    scenarios = pd.read_csv(out / 'monthly_scenarios.csv')
    result = pd.read_csv(out / 'sector_monthly_uncertainty.csv').set_index(['date', 'sector']).sort_index()
    grouped = scenarios.groupby(['date', 'sector']).ktCO2
    np.testing.assert_allclose(result.lower_ktCO2, grouped.min().reindex(result.index), equal_nan=True)
    np.testing.assert_allclose(result.upper_ktCO2, grouped.max().reindex(result.index), equal_nan=True)
    latest = pd.read_csv(out / 'latest_common_month.csv')
    common = result.ktCO2.unstack('sector').dropna().index.max()
    assert set(latest.date) == {common}
    assert len(latest) == 8
