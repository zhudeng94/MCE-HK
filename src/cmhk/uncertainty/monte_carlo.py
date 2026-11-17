"""Model-based central 95% intervals, conditional on explicit PDFs and priors."""
from pathlib import Path
import hashlib
import json
import os
import numpy as np
import pandas as pd
from scipy.stats import norm
from cmhk.uncertainty.scenarios import NAMES, main as build_sensitivity

from cmhk.paths import ROOT, code_hashes
Z95 = norm.ppf(.975)


def lognormal_parameters(lower, upper):
    """Exactly match positive 2.5% and 97.5% quantiles."""
    if not 0 < lower <= upper or not np.isfinite([lower, upper]).all():
        raise ValueError('Positive finite ordered distribution bounds required')
    return .5*np.log(lower*upper), np.log(upper/lower)/(2*Z95)


def bounded_multiplier(rng, size, width_pct):
    width = width_pct/100
    mu, sigma = lognormal_parameters(1-width, 1+width)
    return np.exp(mu + sigma*rng.standard_normal(size))


def structural_paths(sector, scenarios, dates):
    """Published is not an extra model; missing annual allocations use proxy."""
    if sector == 'Industry':
        raise ValueError('Industry uses annual fuel and a shared baseline, not structural paths')
    data = scenarios[scenarios.sector.eq(sector)].pivot(index='date', columns='scenario', values='ktCO2').reindex(dates)
    if sector == 'International Aviation':
        data = pd.DataFrame({'movements': data.movements,
                             'calendar_days': data.calendar_days_Y.combine_first(data.calendar_days_Q)})
    else:
        data = data.drop(columns='published')
    if data.isna().any().any() or (data < 0).any().any():
        raise ValueError(f'Incomplete or invalid structural paths: {sector}')
    return data


def industry_from_anchors(components, anchors, dates, multipliers):
    """Apply the single shared 2021 calibration to allocated non-electric fuel."""
    if list(anchors.index) != [2021]:
        raise ValueError('Industry requires only the 2021 baseline')
    multipliers=np.asarray(multipliers,dtype=float)
    if multipliers.ndim != 2 or multipliers.shape[0] != 1 or not np.isfinite(multipliers).all() or (multipliers<=0).any():
        raise ValueError('Positive shared baseline multipliers required')
    fuel=components.pivot(index='date',columns='component',values='fuel_TJ').reindex(dates)
    if fuel.isna().any().any() or not np.isfinite(fuel).all().all() or (fuel<0).any().any():
        raise ValueError('Complete nonnegative industrial fuel required')
    return fuel.sum(axis=1).to_numpy()[:,None]*anchors.loc[2021,'coefficient']*multipliers


def fuel_parts(sector, path, dates, components, energy, config):
    """Exact scenario components, including the inferred coal/oil split."""
    method = 'movements' if sector == 'International Aviation' else path
    sub = components[components.sector.eq(sector) & components.scenario.eq(method)]
    table = sub.pivot(index='date', columns='fuel', values='ktCO2').reindex(dates)
    if table.empty or table.isna().any().any():
        raise ValueError(f'Missing fuel components: {sector}/{path}')
    if sector == 'Power':
        share = float(path.split('_')[1])
        anchor = energy.reindex(np.minimum(dates.year, int(energy.index.max())))
        coal = -anchor.COAL.to_numpy()*config['ipcc_t_co2_per_tj_ncv']['coal']
        oil = -anchor.OIL.to_numpy()*share*config['ipcc_t_co2_per_tj_ncv']['fuel_oil']
        fraction = oil/(coal+oil)
        return pd.DataFrame({'natural_gas': table.natural_gas_inferred,
                             'coal': table.coal_oil_inferred*(1-fraction),
                             'fuel_oil': table.coal_oil_inferred*fraction}, index=dates)
    mapped = {}
    for fuel in table:
        key = {'town_gas':'town_gas', 'lpg_residual':'lpg', 'oil_coal_unsplit':'diesel'}.get(fuel)
        if key is None:
            key = next((f for f in config['ipcc_t_co2_per_tj_ncv'] if fuel.endswith('_'+f)), None)
        if key is None:
            raise ValueError(f'Unmapped fuel: {fuel}')
        mapped[key] = mapped.get(key, 0) + table[fuel]
    return pd.DataFrame(mapped, index=dates)


def quantile_summary(draws, points):
    lower, median, upper = np.quantile(draws, [.025, .5, .975], axis=1)
    first = np.quantile(draws[:, :draws.shape[1]//2], [.025, .975], axis=1)
    second = np.quantile(draws[:, draws.shape[1]//2:], [.025, .975], axis=1)
    denom = np.where(np.asarray(points) > 0, points, np.nan)
    error = np.max(np.abs(first-second), axis=0)/denom*100
    return dict(lower_95_ktCO2=lower, median_ktCO2=median, upper_95_ktCO2=upper,
                mean_ktCO2=draws.mean(axis=1), std_ktCO2=draws.std(axis=1, ddof=1),
                mc_endpoint_change_pct=error)


def relative_fuel_draws(parts, baseline_parts, factors, selected):
    """Normalize each draw by the SAME sampled fuel factors in the base year.

    parts are already calibrated monthly values; baseline_parts can be raw.
    A constant single-fuel factor cancels exactly, while mixture errors remain.
    """
    totals = baseline_parts.sum(axis=0)
    denominator = sum(totals[f] * factors[f][selected] for f in totals.index) / totals.sum()
    numerator = sum(parts[f].to_numpy()[:, None] * factors[f][selected] for f in parts)
    return numerator / denominator[None, :]


def simulate(points, scenarios, components, energy, config, settings, on_sector_draws=None,
             industry_components=None, industry_anchors=None, baseline_calibration=None):
    n = settings['draws']
    if n < 1000 or settings['coverage_probability'] != .95:
        raise ValueError('At least 1000 draws and 95% coverage required')
    rng = np.random.default_rng(settings['seed'])
    factors, parameter_rows = {}, []
    for fuel, (lower, upper) in settings['factor_95_bounds_tCO2_per_TJ'].items():
        central = config['ipcc_t_co2_per_tj_ncv'][fuel]
        mu, sigma = lognormal_parameters(lower/central, upper/central)
        factors[fuel] = np.exp(mu + sigma*rng.standard_normal(n))
        parameter_rows.append(dict(parameter=f'EF/{fuel}', central=central, lower_95=lower,
                                   upper_95=upper, unit='tCO2/TJ', basis='IPCC Table 1.4; coal fuel-type assumption'))
    factors['town_gas'] = bounded_multiplier(rng, n, settings['town_gas_factor_95_pct'])
    results, weights, checks = [], [], []
    anchored = set(config.get('official_baseline', {}).get('rescale_sectors', []))
    baseline_year = config.get('official_baseline', {}).get('year', 2021)
    if anchored and baseline_calibration is None:
        raise ValueError('Official baseline calibration required for relative activity uncertainty')
    if anchored and (baseline_calibration.index.has_duplicates or
                     not baseline_calibration.loc[list(anchored), 'year'].eq(baseline_year).all()):
        raise ValueError('Official calibration year/sector mismatch')
    for sector_index, sector in enumerate(NAMES):
        # Independent streams prevent future sector-specific changes from
        # changing another sector's Monte Carlo samples. Fuel draws stay shared.
        rng = np.random.default_rng(np.random.SeedSequence([settings['seed'], sector_index+1]))
        block = points[points.sector.eq(sector) & points.ktCO2.notna()].sort_values('date')
        dates = pd.DatetimeIndex(block.date)
        if sector == 'Industry':
            if industry_components is None or industry_anchors is None:
                raise ValueError('Industrial calibration anchors and proxy activity required')
            if list(industry_anchors.index) != settings['industry_uncertainty']['anchor_years']:
                raise ValueError('Industrial anchor years do not match uncertainty configuration')
            central = industry_from_anchors(industry_components, industry_anchors, dates,
                                           np.ones((len(industry_anchors),1)))[:,0]
            if not np.allclose(central,block.ktCO2,rtol=1e-10,atol=1e-8):
                raise ValueError('Industrial anchors do not reconstruct published estimates')
            checks.append(dict(check='Industry/annual_fuel_reconstructs_published',passed=True))
            width = settings['crt_calibration_95_pct']['Industry']
            multiplier = bounded_multiplier(rng,(len(industry_anchors),n),width)
            draws = industry_from_anchors(industry_components,industry_anchors,dates,multiplier)
            weights.append(dict(sector=sector,scenario='annual_fuel/shared_2021_baseline',
                                probability=1.,sampled_draws=n,basis='annual non-electric fuel; shared 2021 calibration'))
            for year,anchor in industry_anchors.iterrows():
                for coefficient in ['coefficient']:
                    value = anchor[coefficient]
                    parameter_rows.append(dict(parameter=f'Industry/{year}/{coefficient}',central=value,
                        lower_95=value*(1-width/100),upper_95=value*(1+width/100),unit='ktCO2/proxy_TJ',
                        basis='2021 CRT/non-electric fuel coefficient; shared across years'))
            names = []
        else:
            paths = structural_paths(sector, scenarios, dates)
            if sector in anchored and (dates.year == baseline_year).sum() == 12:
                totals = paths.loc[dates.year == baseline_year].sum(axis=0)
                if not np.allclose(totals, baseline_calibration.loc[sector, 'official_ktCO2']):
                    raise ValueError(f'Structural paths do not match official baseline: {sector}')
            names = list(paths.columns)
            choice = rng.integers(0, len(names), size=n)  # Independent sector choices, shared across months.
            draws = np.zeros((len(dates), n))
        part_cache = {}
        for i, name in enumerate(names):
            selected = np.flatnonzero(choice == i)
            base = paths[name].to_numpy()
            weights.append(dict(sector=sector, scenario=name, probability=1/len(names),
                                sampled_draws=len(selected), basis='analyst equal-weight structural prior'))
            if sector in ['Road Transport','Domestic Navigation']:
                draws[:, selected] = base[:, None]
                continue
            parts = fuel_parts(sector, name, dates, components, energy, config)
            if sector in anchored or (sector == 'International Aviation' and name == 'calendar_days'):
                total = parts.sum(axis=1).to_numpy()
                ratio = np.divide(base, total, out=np.ones(len(base)), where=total != 0)
                parts = parts.mul(ratio, axis=0)
            if not np.allclose(parts.sum(axis=1), base, rtol=1e-10, atol=1e-8):
                raise ValueError(f'Components do not reconstruct path: {sector}/{name}')
            part_cache[name] = parts
            if sector in anchored:
                baseline_dates = pd.date_range(f'{baseline_year}-01-01', periods=12, freq='MS')
                baseline_parts = fuel_parts(sector, name, baseline_dates, components, energy, config)
                values = relative_fuel_draws(parts, baseline_parts, factors, selected)
            else:
                values = np.zeros((len(dates), len(selected)))
                for fuel in parts:
                    values += parts[fuel].to_numpy()[:, None]*factors[fuel][selected]
            draws[:, selected] = values
            checks.append(dict(check=f'components/{sector}/{name}', passed=True))
        if sector in settings['crt_calibration_95_pct'] and sector != 'Industry':
            # Composite CRT coefficients already include fuel conversion.
            draws *= bounded_multiplier(rng, n, settings['crt_calibration_95_pct'][sector])
        relative_activity = sector in anchored or sector in ['Industry','Road Transport','Domestic Navigation']
        baseline_activity = bounded_multiplier(rng, n, settings['activity_95_pct']) if relative_activity else np.ones(n)
        for year in np.unique(dates.year):
            activity = baseline_activity if relative_activity and year == baseline_year else bounded_multiplier(rng, n, settings['activity_95_pct'])
            draws[dates.year == year] *= activity / baseline_activity
        reference = settings['extrapolation_last_benchmark'].get(sector)
        if sector == 'Power' and 'intensity_log_sigma' in block:
            reference = None  # Empirical annual error replaces assumed 5% drift.
        if reference is not None:
            drift = np.ones(n)
            for year in range(reference+1, int(dates.year.max())+1):
                drift *= bounded_multiplier(rng, n, settings['extrapolation_annual_drift_95_pct'])
                mask = dates.year == year
                if sector in ['Residential', 'Commercial']:
                    for i, name in enumerate(names):
                        cols = np.flatnonzero(choice == i)
                        if not len(cols) or not mask.any():
                            continue
                        parts = part_cache[name]
                        gas = parts.town_gas.to_numpy()[mask, None]*factors['town_gas'][cols]
                        total = sum(parts[f].to_numpy()[mask, None]*factors[f][cols] for f in parts)
                        fraction = np.divide(gas, total, out=np.zeros_like(gas), where=total != 0)
                        ix = np.ix_(np.flatnonzero(mask), cols)
                        # Observed town gas is not extrapolated.
                        draws[ix] *= fraction+(1-fraction)*drift[cols]
                else:
                    draws[mask] *= drift
        if 'nowcast_log_sigma' in block:
            # Backtest errors concern quarter totals; share a residual across
            # the missing quarter's months, rather than independent month noise.
            for period, forecast in block[block.temporal_status.eq('activity_nowcast')].groupby(block.date.dt.to_period('Q')):
                sigma = float(forecast.nowcast_log_sigma.max())
                mask = dates.to_period('Q') == period
                draws[mask] *= np.exp(sigma*rng.standard_normal(n))
        if sector == 'Power' and 'intensity_log_sigma' in block:
            for year, forecast in block[block.intensity_log_sigma.gt(0)].groupby(block.date.dt.year):
                draws[dates.year==year] *= np.exp(float(forecast.intensity_log_sigma.max())*rng.standard_normal(n))
        if not np.isfinite(draws).all() or (draws < 0).any():
            raise ValueError('Invalid Monte Carlo draw')
        if on_sector_draws is not None:
            on_sector_draws(sector, dates, draws)
        summary = quantile_summary(draws, block.ktCO2.to_numpy())
        row = block.copy()
        for column, values in summary.items():
            row[column] = values
        results.append(row)
        print(f'Monte Carlo: {sector}; {len(dates)} months × {n} draws', flush=True)
        del draws
    result = points.merge(pd.concat(results)[['date', 'sector', *summary]], on=['date', 'sector'],
                          how='left', validate='one_to_one')
    denominator = result.ktCO2.where(result.ktCO2 > 0)
    result['lower_deviation_pct'] = 100*(result.lower_95_ktCO2/denominator-1)
    result['upper_deviation_pct'] = 100*(result.upper_95_ktCO2/denominator-1)
    result['relative_half_width_95_pct'] = 100*(result.upper_95_ktCO2-result.lower_95_ktCO2)/(2*denominator)
    result['coverage_probability'] = .95
    result['draws'] = np.where(result.ktCO2.notna(), n, 0)
    result['status'] = np.where(result.ktCO2.notna(), 'model_based_95pct_interval', 'no_estimate')
    result['interval_interpretation'] = 'central 95% probability under configured distributions and model weights; not empirically coverage-calibrated'
    threshold = settings['convergence_max_endpoint_change_pct_of_point']
    checks.append(dict(check='split_sample_endpoint_change_below_configured_tolerance',
                       passed=bool(result.mc_endpoint_change_pct.dropna().le(threshold).all())))
    return result, pd.DataFrame(weights), pd.DataFrame(parameter_rows), pd.DataFrame(checks)


def report(result, latest, settings, out):
    lines = ['# 各部门月度排放：95% 不确定性区间', '',
             f'采用 {settings["draws"]:,} 次蒙特卡洛抽样，随机种子 {settings["seed"]}；每月取排放分布的 2.5% 和 97.5% 分位数。',
             '**这是给定输入分布及模型权重下的 95% 不确定性区间。现有数据不足以验证频率学意义下的 95% 置信覆盖率。**',
             '主表 ktCO2 保留原估计；模拟均值与中位数另列，不把主估计强行放在区间中心。', '',
             f'## 最新共同月份：{latest.date.iloc[0]:%Y-%m}', '',
             '| 部门 | 主估计 ktCO₂ | 95% 下限 | 95% 上限 | 下限相对偏差 | 上限相对偏差 |',
             '|---|---:|---:|---:|---:|---:|']
    for r in latest.itertuples():
        lines.append(f'| {NAMES[r.sector]} | {r.ktCO2:.2f} | {r.lower_95_ktCO2:.2f} | {r.upper_95_ktCO2:.2f} | {r.lower_deviation_pct:+.2f}% | {r.upper_deviation_pct:+.2f}% |')
    lines += ['', '## 分布及误差传播', '',
              '1. 工业采用年度非电力燃料和共享的 2021 排放校准；其他部门采用命名结构方案等权抽样。',
              '2. 活动乘数的 95% 两端为 0.95/1.05，依据为 IPCC 缺少本地资料时的燃料统计默认值；将其用于代理是本项目假设；新校准五部门采用目标年/2021 的误差比，2021 年分子分母共享抽样并抵消。不同年份误差独立为分析假设。',
              '3. 排放因子按 IPCC 表 1.4 的分燃料上下限拟合对数正态分布。电力煤/油合并排放先按该方案投入比例拆分；煤种暂对应 Other Bituminous Coal。煤气因子 ±5% 为项目假设。新校准五部门的同一燃料因子同时进入当月分子和各方案的 2021 年分母；单一燃料因子完全抵消，燃料混合比例变化仍有影响。',
              '4. 八部门各使用跨时序共享的 2021 CRT 基准乘数，95% 范围为 ±10%；工业使用单一燃料能耗比例，固定综合因子在归一化中抵消。',
              '5. 外推年增加年度独立的乘法漂移，各年增量的 95% 两端为 0.95/1.05，跨年累积；这是额外假设。起点为工业/运输/居民/商业 2024。居民及商业只对非煤气分项施加漂移；电力用选择期年度强度对数残差 RMS 替代固定漂移。', '',
              '对于正的上下限 L/U，取 `μ=(ln L+ln U)/2`，`σ=(ln U−ln L)/(2×1.95996398454)`，抽取 `exp(μ+σZ)`。输入两端恰为 2.5%/97.5% 分位数；主模型因子不一定等于拟合分布中位数。',
              '工业年度活动误差采用当年与 2021 年乘数之比；2021 年活动误差抵消。年度燃料基准结束后增加外推漂移。',
              '结构方案跨月共用；同燃料因子跨月跨部门共用；部门活动误差在同年各月及燃料间共用。工业各月通过共享 2021 校准保持时间相关性；各非工业部门 CRT 基准误差在全时序共用、部门间独立；新校准部门另共享基准年的活动误差。其他误差族暂设独立，外推漂移累积。每个部门使用独立且固定种子的随机数流，共享燃料因子的抽样不变。',
              '年度/季度分月方案在误差传播前保持总量；抽样时基准总量本身也存在不确定性。合计和年度区间先对同一次抽样加总，再取分位数；年度变化先减去同次抽样的上年相同月份，保留跨年相关性。缺少任一部门的月份不生成合计，部分年份不年化。', '',
              '季度活动暂估另乘以选择期季度预测对数残差 RMS 所定义的乘数，同季度各月共享；电力强度误差同年共享。留出期不用于误差拟合。季度误差不能验证月内分配误差，实际覆盖率仍待后续发布快照检验。', '',
              '## 假设与限制', '',
              '**结构方案等权、CRT ±10%、煤气因子 ±5%、外推年度漂移 ±5% 是显式分析假设，未由本地重复观测或专家评估标定。** 参数均在 configs/uncertainty.json，区间宽度会随这些选择变化。',
              '工业使用年度非电力燃料能耗、固定综合 CO₂/TJ 系数和月度分配；按天数分配另作敏感性对照。',
              '密度、净热值与总/净热值转换、发电效率、未覆盖来源及超出所列情景的月度分配误差保持固定；不声称覆盖全部系统偏差。未将跨年真实波动或季度预测残差直接当作月度测量误差。',
              '输出为各月边际 95% 区间，不是整条时序同时具有 95% 覆盖率。缺失值维持缺失，相对偏差带符号，区间不必以主估计为中心。', '',
              '## 数值稳定性', '',
              f'两个独立半样本的各月两端分位数最大差异为主估计的 {result.mc_endpoint_change_pct.max():.3f}%；阈值为 {settings["convergence_max_endpoint_change_pct_of_point"]:.2f}%。这只检验数值稳定性，不验证实际覆盖率。', '',
              '## 输出与复现', '',
              '- [逐月 95% 区间](sector_monthly_uncertainty.csv)、[最新共同月份](latest_common_month.csv)、[部门汇总](sector_summary.csv)。',
              '- [月度总量区间](total_monthly_uncertainty.csv)、[年度总量区间](total_annual_uncertainty.csv)、[年度净变化区间](annual_change_uncertainty.csv)、[部门年度区间](sector_annual_uncertainty.csv)。',
              '- [抽样参数](input_parameters.csv)、[模型概率](scenario_probabilities.csv)、[配置及哈希](manifest.json)、[检验](checks.csv)。',
              '- [原情景范围](scenario_sensitivity/report.md)保留为诊断对照，不能与本表混用。',
              '- `python src/cmhk/uncertainty/monte_carlo.py` 或 `python scripts/reproduce.py --skip-comparisons`。', '',
              '依据：[IPCC Volume 1 Chapter 3](%s)；[Volume 2 Chapter 1，§1.5.2、Table 1.4](%s)。' % (settings['sources']['ipcc_uncertainty'], settings['sources']['ipcc_energy']), '',
              '![95% 不确定性区间](monthly_uncertainty.png)', '']
    (out/'report.md').write_text('\n'.join(lines))


def plot(result, out):
    os.environ.setdefault('MPLCONFIGDIR', str(ROOT/'.tmp/matplotlib'))
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(4, 2, figsize=(13, 12), sharex=True)
    for ax, sector in zip(axes.flat, NAMES):
        d = result[result.sector.eq(sector)].sort_values('date')
        ax.fill_between(d.date, d.lower_95_ktCO2/1000, d.upper_95_ktCO2/1000,
                        color='#db923a', alpha=.35, label='95% model-based interval')
        ax.plot(d.date, d.ktCO2/1000, color='#195e7b', lw=1, label='Published estimate')
        ax.set_title(sector, loc='left'); ax.set_ylabel('Mt CO2 / month'); ax.grid(alpha=.2)
    # All eight panels populated.
    fig.legend(*axes.flat[0].get_legend_handles_labels(), loc='lower center', ncol=2, frameon=False)
    fig.suptitle('Hong Kong monthly emissions | 95% uncertainty intervals')
    fig.text(.06, .015, 'Conditional on input PDFs and production industrial interpolation; not empirically coverage-calibrated.', fontsize=9)
    fig.tight_layout(rect=[0, .04, 1, .96])
    for ext in ['png', 'pdf']:
        fig.savefig(out/f'monthly_uncertainty.{ext}', dpi=180)
    plt.close(fig)


def main(root=ROOT):
    _, scenarios = build_sensitivity(root)
    config = json.loads((root/'configs/model.json').read_text())
    settings = json.loads((root/'configs/uncertainty.json').read_text())
    points = pd.read_csv(root/'outputs/hong_kong_sector_monthly.csv', parse_dates=['date'])
    components = pd.read_csv(root/'outputs/diagnostics/monthly_components.csv', parse_dates=['date'])
    industry_components = pd.read_csv(root/'outputs/diagnostics/industry_proxy_components.csv',parse_dates=['date'])
    industry_anchors = pd.read_csv(root/'outputs/diagnostics/industry_proxy_calibration.csv',index_col='year').sort_index()
    baseline_calibration = pd.read_csv(root/'outputs/diagnostics/official_baseline_calibration.csv', index_col='sector')
    energy = pd.read_csv(root/'data/processed/csd_915-91001.csv')
    energy = energy[energy.sv.eq('F_EN_REQ') & energy.EN_REQ_TYPE.eq('Elect_gen')]
    energy = energy.pivot(index='period', columns='PROD_TYPE', values='figure')
    energy.index = energy.index.astype(int)
    from cmhk.uncertainty.totals import JointTotals
    joint = JointTotals(points, settings['draws'])
    result, weights, parameters, checks = simulate(points, scenarios, components, energy, config, settings, joint.add,
                                                  industry_components, industry_anchors, baseline_calibration)
    out = root/'outputs/uncertainty'
    for name, frame in joint.summarize().items():
        frame.to_csv(out/f'{name}.csv', index=False)
    del joint
    valid = result[result.ktCO2.notna()]
    common = valid.groupby('date').sector.nunique()
    latest = result[result.date.eq(common[common.eq(len(NAMES))].index.max())]
    summary = valid.groupby('sector').agg(months=('date', 'count'), first_month=('date', 'min'),
        last_month=('date', 'max'), median_relative_half_width_95_pct=('relative_half_width_95_pct', 'median'),
        max_relative_half_width_95_pct=('relative_half_width_95_pct', 'max')).reset_index()
    result.to_csv(out/'sector_monthly_uncertainty.csv', index=False)
    latest.to_csv(out/'latest_common_month.csv', index=False)
    summary.to_csv(out/'sector_summary.csv', index=False)
    weights.to_csv(out/'scenario_probabilities.csv', index=False)
    assumptions = []
    for name, width, basis in [('activity', settings['activity_95_pct'], settings['activity_basis']),
                               ('town_gas_factor', settings['town_gas_factor_95_pct'], settings['town_gas_factor_basis']),
                               ('annual_extrapolation_increment', settings['extrapolation_annual_drift_95_pct'], settings['extrapolation_basis'])]:
        assumptions.append(dict(parameter=name, central=1, lower_95=1-width/100, upper_95=1+width/100, unit='multiplier', basis=basis))
    for sector, width in settings['crt_calibration_95_pct'].items():
        assumptions.append(dict(parameter=f'CRT/{sector}', central=1, lower_95=1-width/100,
                                upper_95=1+width/100, unit='multiplier', basis=settings['crt_calibration_basis']))
    pd.concat([parameters, pd.DataFrame(assumptions)], ignore_index=True).to_csv(out/'input_parameters.csv', index=False)
    checks.to_csv(out/'checks.csv', index=False)
    report(result, latest, settings, out)
    plot(result, out)
    inputs = ['configs/model.json', 'configs/uncertainty.json', 'outputs/hong_kong_sector_monthly.csv',
              'outputs/diagnostics/monthly_components.csv', 'data/processed/csd_915-91001.csv',
              'outputs/diagnostics/industry_proxy_components.csv', 'outputs/diagnostics/industry_proxy_calibration.csv',
              'outputs/diagnostics/official_baseline_calibration.csv',
              'outputs/uncertainty/scenario_sensitivity/monthly_scenarios.csv',
              'outputs/uncertainty/scenario_sensitivity/manifest.json', 'data/raw/ipcc_energy_intro.pdf',
              'data/raw/ipcc_uncertainties_2006.pdf', 'outputs/near_realtime/manifest.json',
              'outputs/near_realtime/quarterly_backtest.csv', 'outputs/near_realtime/power_intensity_backtest.csv']
    manifest = dict(method=settings['method'], coverage_probability=.95, settings=settings,
                    latest_common_month=str(latest.date.iloc[0].date()),
                    maximum_mc_endpoint_change_pct=float(result.mc_endpoint_change_pct.max()),
                    checks_passed=bool(checks.passed.all()),
                    input_sha256={p:hashlib.sha256((root/p).read_bytes()).hexdigest() for p in inputs},
                    code_sha256=code_hashes(root, ['uncertainty.py', 'scenario_uncertainty.py', 'uncertainty_totals.py', 'official_baseline.py']),
                    versions=dict(numpy=np.__version__, pandas=pd.__version__))
    (out/'manifest.json').write_text(json.dumps(manifest, indent=2, ensure_ascii=False)+'\n')
    # The exact legacy scenarios now live in scenario_sensitivity/.
    legacy = out/'monthly_scenarios.csv'
    if legacy.exists():
        legacy.unlink()
    if not checks.passed.all():
        raise ValueError('Monte Carlo convergence tolerance not met; increase draws')
    print(latest[['sector','ktCO2','lower_95_ktCO2','upper_95_ktCO2',
                  'lower_deviation_pct','upper_deviation_pct']].to_string(index=False))
    return result


if __name__ == '__main__':
    main()
