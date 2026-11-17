from pathlib import Path
import hashlib
import json
import sys
import numpy as np
import pandas as pd
import pytest
from scipy.stats import norm

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from cmhk.uncertainty import monte_carlo as mc


def test_input_quantiles_are_95_bounds_not_standard_deviations():
    mu, sigma = mc.lognormal_parameters(.9, 1.3)
    np.testing.assert_allclose(np.exp(mu+sigma*norm.ppf([.025, .975])), [.9, 1.3])
    with pytest.raises(ValueError):
        mc.lognormal_parameters(-1, 1)
    with pytest.raises(ValueError):
        mc.lognormal_parameters(2, 1)


def test_monte_carlo_propagation_matches_analytic_product_distribution():
    rng = np.random.default_rng(16)
    n = 200000
    a = mc.bounded_multiplier(rng, n, 5)
    b = mc.bounded_multiplier(rng, n, 10)
    mu_a, sigma_a = mc.lognormal_parameters(.95, 1.05)
    mu_b, sigma_b = mc.lognormal_parameters(.90, 1.10)
    analytic = 100*np.exp(mu_a+mu_b+norm.ppf([.025, .975])*np.hypot(sigma_a, sigma_b))
    result = mc.quantile_summary((100*a*b)[None, :], np.array([100.]))
    np.testing.assert_allclose([result['lower_95_ktCO2'][0], result['upper_95_ktCO2'][0]], analytic, rtol=.002)


@pytest.mark.integration
def test_zero_errors_single_model_reconstruct_published_estimates(monkeypatch):
    config = json.loads((ROOT/'configs/model.json').read_text())
    settings = json.loads((ROOT/'configs/uncertainty.json').read_text())
    settings.update(draws=1000, activity_95_pct=0, town_gas_factor_95_pct=0,
                    extrapolation_annual_drift_95_pct=0, crt_calibration_95_pct={'Industry':0, 'Transport':0})
    settings['crt_calibration_95_pct'] = {k:0 for k in json.loads((ROOT/'configs/uncertainty.json').read_text())['crt_calibration_95_pct']}
    settings['factor_95_bounds_tCO2_per_TJ'] = {k:[v,v] for k,v in config['ipcc_t_co2_per_tj_ncv'].items()}
    points = pd.read_csv(ROOT/'outputs/hong_kong_sector_monthly.csv', parse_dates=['date'])
    # Include an observed full-year month and a month with extrapolation.
    points = points[points.date.isin(pd.to_datetime(['2021-02-01', '2026-08-01']))].copy()
    points[['nowcast_log_sigma','intensity_log_sigma']] = 0.
    def one_path(sector, scenarios, dates):
        method = config['point_estimate_sector_methods'].get(sector, 'industry')
        if sector == 'International Shipping':
            method = json.loads((ROOT/'outputs/near_realtime/manifest.json').read_text())['selection'][sector]['proxy']
        return points[points.sector.eq(sector)].set_index('date')[['ktCO2']].reindex(dates).rename(columns={'ktCO2':method})
    monkeypatch.setattr(mc, 'structural_paths', one_path)
    components = pd.read_csv(ROOT/'outputs/diagnostics/monthly_components.csv', parse_dates=['date'])
    energy = pd.read_csv(ROOT/'data/processed/csd_915-91001.csv')
    energy = energy[energy.sv.eq('F_EN_REQ') & energy.EN_REQ_TYPE.eq('Elect_gen')].pivot(index='period', columns='PROD_TYPE', values='figure')
    energy.index = energy.index.astype(int)
    industry_components=pd.read_csv(ROOT/'outputs/diagnostics/industry_proxy_components.csv',parse_dates=['date'])
    industry_anchors=pd.read_csv(ROOT/'outputs/diagnostics/industry_proxy_calibration.csv',index_col='year')
    result, weights, _, checks = mc.simulate(points, None, components, energy, config, settings,
        industry_components=industry_components,industry_anchors=industry_anchors,
        baseline_calibration=pd.read_csv(ROOT/'outputs/diagnostics/official_baseline_calibration.csv',index_col='sector'))
    for col in ['lower_95_ktCO2', 'median_ktCO2', 'upper_95_ktCO2']:
        np.testing.assert_allclose(result[col], result.ktCO2, rtol=1e-12)
    assert (weights.probability == 1).all()
    assert checks.passed.all()


def test_industrial_fuel_draws_share_one_baseline_in_all_years():
    dates=pd.to_datetime(['2005-01-01','2020-01-01','2021-01-01','2026-01-01'])
    anchors=pd.DataFrame({'coefficient':[2.]},index=[2021])
    components=pd.concat([pd.DataFrame({'date':dates,'component':name,'fuel_TJ':[3.,4.,5.,6.]})
                          for name in ['gaseous_fuels','liquid_and_solid_fuels']])
    scales=np.array([[.9,1.1]])
    result=mc.industry_from_anchors(components,anchors,dates,scales)
    np.testing.assert_allclose(result,np.array([12.,16.,20.,24.])[:,None]*scales)
    with pytest.raises(ValueError,match='only the 2021'):
        mc.industry_from_anchors(components,anchors.rename(index={2021:2005}),dates,scales)


@pytest.mark.integration
def test_delivered_95_intervals_preserve_points_and_missingness():
    out = ROOT/'outputs/uncertainty'
    points = pd.read_csv(ROOT/'outputs/hong_kong_sector_monthly.csv').set_index(['date','sector']).sort_index()
    result = pd.read_csv(out/'sector_monthly_uncertainty.csv').set_index(['date','sector']).sort_index()
    pd.testing.assert_index_equal(points.index, result.index)
    np.testing.assert_allclose(points.ktCO2, result.ktCO2, equal_nan=True)
    assert points.ktCO2.isna().equals(result.lower_95_ktCO2.isna())
    assert points.ktCO2.isna().equals(result.upper_95_ktCO2.isna())
    valid = result.dropna(subset=['ktCO2'])
    assert valid.lower_95_ktCO2.gt(0).all()
    assert valid.lower_95_ktCO2.lt(valid.median_ktCO2).all()
    assert valid.upper_95_ktCO2.gt(valid.median_ktCO2).all()
    assert valid.coverage_probability.eq(.95).all()
    assert valid.draws.eq(100000).all()
    assert pd.read_csv(out/'checks.csv').passed.all()
    probabilities = pd.read_csv(out/'scenario_probabilities.csv')
    np.testing.assert_allclose(probabilities.groupby('sector').probability.sum(), 1)
    assert probabilities.groupby('sector').sampled_draws.sum().eq(100000).all()
    assert not probabilities.scenario.eq('published').any()
    industry=probabilities[probabilities.sector.eq('Industry')]
    assert len(industry)==1 and industry.iloc[0].probability==1
    assert industry.iloc[0].scenario=='annual_fuel/shared_2021_baseline'


@pytest.mark.integration
def test_mc_provenance_tracks_assumptions_sources_and_code():
    manifest = json.loads((ROOT/'outputs/uncertainty/manifest.json').read_text())
    assert manifest['settings'] == json.loads((ROOT/'configs/uncertainty.json').read_text())
    for key in ['input_sha256', 'code_sha256']:
        for path, checksum in manifest[key].items():
            assert hashlib.sha256((ROOT/path).read_bytes()).hexdigest() == checksum, path
    assert manifest['checks_passed']
