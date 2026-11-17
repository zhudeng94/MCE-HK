from pathlib import Path
import json
import sys

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from cmhk.benchmarks.official import calibrate_series, crt_benchmarks
from cmhk.uncertainty.monte_carlo import relative_fuel_draws


def test_relative_activity_preserves_partial_year_and_rejects_missing_anchor():
    dates = pd.date_range('2021-01-01', '2022-03-01', freq='MS')
    proxy = pd.Series([10.]*12 + [20., 20., np.nan], index=dates)
    result, scale = calibrate_series(proxy, 60., 2021)
    assert scale == .5 and result.loc['2021'].sum() == 60
    assert result.loc['2022'].sum() == 20  # Two months, never a full-year allocation.
    assert pd.isna(result.iloc[-1])
    incomplete = proxy.copy()
    incomplete.iloc[2] = np.nan
    with pytest.raises(ValueError, match='baseline required'):
        calibrate_series(incomplete, 60., 2021)


@pytest.mark.integration
def test_published_sectors_match_official_baseline_and_preserve_activity_ratios():
    config = json.loads((ROOT/'configs/model.json').read_text())
    year = config['official_baseline']['year']
    refs = crt_benchmarks().query('year == @year').set_index('sector')
    points = pd.read_csv(ROOT/'outputs/hong_kong_sector_monthly.csv', parse_dates=['date'])
    actual = points[points.date.dt.year.eq(year)].groupby('sector').ktCO2.agg(['sum','count'])
    assert actual['count'].eq(12).all()
    np.testing.assert_allclose(actual['sum'], refs.official_ktCO2.reindex(actual.index), rtol=1e-12)
    comparison = pd.read_csv(ROOT/'outputs/diagnostics/baseline_calibration_comparison.csv')
    sectors = config['official_baseline']['rescale_sectors']
    assert comparison[comparison.sector.isin(sectors)].yoy_difference_pp.dropna().abs().max() < 1e-10
    raw = pd.read_csv(ROOT/'outputs/diagnostics/sector_monthly_before_baseline_calibration.csv', parse_dates=['date'])
    joined = points.merge(raw, on=['date','sector'], suffixes=('', '_proxy'))
    assert joined.ktCO2.isna().equals(joined.ktCO2_proxy.isna())
    np.testing.assert_allclose(joined.ktCO2, joined.ktCO2_proxy*joined.calibration_scale, equal_nan=True)


@pytest.mark.integration
def test_each_structural_path_has_its_own_official_annual_baseline():
    config = json.loads((ROOT/'configs/model.json').read_text())
    scenarios = pd.read_csv(ROOT/'outputs/uncertainty/scenario_sensitivity/monthly_scenarios.csv', parse_dates=['date'])
    year = config['official_baseline']['year']
    base = scenarios[scenarios.date.dt.year.eq(year) & scenarios.sector.isin(config['official_baseline']['rescale_sectors'])]
    refs = crt_benchmarks().query('year == @year').set_index('sector').official_ktCO2
    totals = base.groupby(['sector','scenario']).ktCO2.agg(['sum','count'])
    assert totals['count'].eq(12).all()
    np.testing.assert_allclose(totals['sum'], [refs.loc[s] for s,_ in totals.index], rtol=1e-12)


def test_factor_error_cancels_for_single_fuel_but_retains_mix_changes():
    factors = {'coal':np.array([.8, 1., 1.2]), 'gas':np.array([1.2, 1., .8])}
    cols = np.arange(3)
    single = relative_fuel_draws(pd.DataFrame({'coal':[10.,20.]}), pd.DataFrame({'coal':[50.,50.]}), factors, cols)
    np.testing.assert_allclose(single, np.tile([[10.],[20.]], (1,3)))
    mixed_base = pd.DataFrame({'coal':[25.,25.], 'gas':[25.,25.]})
    unchanged = relative_fuel_draws(mixed_base, mixed_base, factors, cols)
    np.testing.assert_allclose(unchanged.sum(axis=0), 100.)
    changed = relative_fuel_draws(pd.DataFrame({'coal':[100.], 'gas':[0.]}), mixed_base, factors, cols)
    np.testing.assert_allclose(changed, [[80.,100.,120.]])
