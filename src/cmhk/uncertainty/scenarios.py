"""Monthly model-sensitivity envelopes, conditional on cached benchmarks.

Scenarios have no assigned probabilities. These are neither 95% confidence
intervals nor a complete emissions uncertainty budget.
"""
from pathlib import Path
import hashlib
import json
import os

import numpy as np
import pandas as pd
from cmhk.benchmarks.official import calibrate_scenarios

from cmhk.paths import ROOT, code_hashes
NAMES = {'Power': '电力', 'Industry': '工业燃烧', 'Road Transport': '道路运输', 'Domestic Navigation': '本地航运',
         'Residential': '居民', 'Commercial': '商业',
         'International Aviation': '国际航空供油', 'International Shipping': '国际航运供油'}
DRIVERS = {
    'Power': 'pooled liquid share; gas dispatch responsiveness',
    'Industry': 'annual non-electric fuel; observed proxy versus calendar allocation',
    'Road Transport': 'road EV mileage', 'Domestic Navigation': 'marine allocation; forward marine reference year',
    'Residential': 'gas versus calendar allocation; trace fuel 0/1 TJ',
    'Commercial': 'gas versus calendar allocation',
    'International Aviation': 'aircraft movements versus calendar allocation',
    'International Shipping': 'all arrivals versus ocean arrivals versus net tonnage',
}


def calendar_alternative(series, frequency):
    """Reallocate only complete benchmark periods, including leap days."""
    if series.index.has_duplicates:
        raise ValueError('Duplicate calendar months')
    result = pd.Series(np.nan, index=series.index, dtype=float)
    for period, block in series.groupby(series.index.to_period(frequency)):
        months = pd.date_range(period.start_time, period.end_time, freq='MS')
        values = series.reindex(months)
        if values.isna().any():
            continue
        if not np.isfinite(values).all() or values.lt(0).any():
            raise ValueError('Invalid emissions for calendar allocation')
        result.loc[months] = values.sum() * months.days_in_month / np.sum(months.days_in_month)
    return result


def industry_alternatives(components, anchors):
    """Monthly activity or calendar allocation, preserving annual fuel targets."""
    total=components.pivot(index='date',columns='component',values='ktCO2').sum(axis=1,min_count=2)
    return {'selected/observed_proxy':total,
            'selected/calendar_days':calendar_alternative(total,'Y')}


def transport_alternatives(scenarios, marine_scenarios, annual, ferry, baseline,
                           base_year, reference_years, production_reference_year):
    """Cross road/marine choices and recalibrate EACH road path to CRT."""
    paths = {}
    multiplier = baseline['transport'] / (baseline['road'] + baseline['marine'])
    marine_factor = baseline['marine'] / annual.loc[base_year, 'marine_TJ']
    for road_name, road_frame in scenarios[scenarios.sector.eq('Road')].groupby('scenario'):
        road = road_frame.set_index('date').ktCO2.sort_index()
        base = road.reindex(pd.date_range(f'{base_year}-01-01', periods=12, freq='MS'))
        if base.isna().any() or base.sum() <= 0:
            raise ValueError('Incomplete transport road calibration year')
        calibrated = road * baseline['road'] / base.sum()
        for marine_name, block in marine_scenarios.groupby('scenario'):
            block = block.set_index('date').sort_index()
            for ref_year in reference_years:
                marine = block.marine_calibrated_proxy_ktCO2.copy()
                ref_dates = pd.date_range(f'{ref_year}-01-01', periods=12, freq='MS')
                pax = ferry.reindex(ref_dates)
                if pax.isna().any() or pax.sum() <= 0:
                    raise ValueError('Incomplete marine reference activity')
                forward = block.index.year > production_reference_year
                dates = block.index[forward]
                marine.loc[dates] = marine_factor * (
                    ferry.reindex(dates) * annual.loc[ref_year, 'passenger_marine_TJ'] / pax.sum()
                    + dates.days_in_month * annual.loc[ref_year, 'freight_marine_TJ'] / np.sum(ref_dates.days_in_month))
                values = (calibrated.reindex(block.index) + marine) * multiplier
                # Preserve published coverage, even when an alternative has extra activity.
                values = values.where(block.transport_proxy_ktCO2.notna())
                paths[f'{road_name}/{marine_name}/reference_{ref_year}'] = values
    return paths


def envelopes(points, scenarios):
    keys = ['date', 'sector']
    if points.duplicated(keys).any() or scenarios.duplicated(keys + ['scenario']).any():
        raise ValueError('Duplicate uncertainty records')
    if scenarios.ktCO2.dropna().lt(0).any() or np.isinf(scenarios.ktCO2).any():
        raise ValueError('Invalid scenario emissions')
    bands = scenarios.groupby(keys).ktCO2.agg(
        lower_ktCO2='min', upper_ktCO2='max', available_scenarios='count').reset_index()
    result = points.merge(bands, on=keys, how='left', validate='one_to_one')
    valid = result.ktCO2.notna()
    if result.loc[valid, ['lower_ktCO2', 'upper_ktCO2']].isna().any().any():
        raise ValueError('Missing uncertainty scenarios for published estimate')
    if ((result.loc[valid, 'lower_ktCO2'] > result.loc[valid, 'ktCO2'] + 1e-8)
            | (result.loc[valid, 'upper_ktCO2'] < result.loc[valid, 'ktCO2'] - 1e-8)).any():
        raise ValueError('Envelope does not include published estimate')
    result.loc[~valid, ['lower_ktCO2', 'upper_ktCO2']] = np.nan
    result['down_ktCO2'] = (result.ktCO2 - result.lower_ktCO2).clip(lower=0)
    result['up_ktCO2'] = (result.upper_ktCO2 - result.ktCO2).clip(lower=0)
    denominator = result.ktCO2.where(result.ktCO2 > 0)
    result['down_pct'] = result.down_ktCO2 / denominator * 100
    result['up_pct'] = result.up_ktCO2 / denominator * 100
    result['max_abs_deviation_pct'] = result[['down_pct', 'up_pct']].max(axis=1)
    result['half_range_pct'] = (result.upper_ktCO2 - result.lower_ktCO2) / (2 * denominator) * 100
    result['available_scenarios'] = result.available_scenarios.fillna(0).astype(int)
    result['status'] = np.where(valid, 'conditional_model_sensitivity', 'no_estimate')
    result['uncertainty_drivers'] = result.sector.map(DRIVERS)
    result['range_meaning'] = 'model scenario envelope; not a confidence interval or total uncertainty'
    return result


def write_report(result, summary, latest, out):
    date = latest.date.iloc[0].strftime('%Y-%m')
    lines = ['# 各部门月度排放不确定性：模型情景敏感性', '',
             '已逐月计算八部门主估计的情景下限、上限、上下偏差和相对偏差，单位 ktCO₂。',
             '**这是固定输入基准下的模型敏感性范围，不是 95% 置信区间，也不是包含所有误差来源的总不确定性。**', '',
             '## 计算定义', '',
             '`L=min(E₀,E₁,…); U=max(E₀,E₁,…)`；E₀ 为已发布主估计，主估计始终纳入范围。',
             '`down_pct=100×(E₀−L)/E₀`；`up_pct=100×(U−E₀)/E₀`。',
             '`max_abs_deviation_pct=max(down_pct,up_pct)`；`half_range_pct=100×(U−L)/(2E₀)`。',
             '范围通常不对称，不能把半宽直接写成围绕主估计的 ± 区间。分母为零时相对指标留空。', '',
             f'## 最新共同完整月份：{date}', '',
             '| 部门 | 主估计 ktCO₂ | 情景下限 | 情景上限 | 向下偏差 | 向上偏差 |',
             '|---|---:|---:|---:|---:|---:|']
    for r in latest.itertuples():
        lines.append(f'| {NAMES[r.sector]} | {r.ktCO2:.3f} | {r.lower_ktCO2:.3f} | {r.upper_ktCO2:.3f} | {r.down_pct:.2f}% | {r.up_pct:.2f}% |')
    lines += ['', '## 情景设计', '',
              '电力、居民、商业、国际供油的每个方案均用自身 2021 年年度值归一化到官方 CRT 基准；范围反映相对活动及分月选择。',
              '- 电力：合并油/气液体份额与天然气调度响应组合，增加固定强度和阻尼趋势外推情景。',
              '- 居民：煤气曲线/按天数分配，以及 0/1 TJ 微量燃料；商业：煤气曲线/按天数分配。',
              '- 国际航运：总到港艘次、远洋到港艘次、净吨位三个已有分配方案。',
              '- 国际航空：起降架次与按天数分配。2005–2012 保持年度供油排放，2013 起保持季度供油排放；新增按天数方案只是分配对照；缺季度统计的暂估月份沿用起降活动，不归一化部分季度。',
              '- 工业：年度非电力燃料约束、2021 CRT 单基准；比较月度活动与日历天数分配，各完整年度总量保持不变。',
              '- 完整运输：三个道路 EV 相对里程方案与两个海运分配方案交叉，再比较最近两个年度海运基准的外推强度。每个道路方案分别以自身 2021 全年值重新标定，保持完整 1.A.3 边界。替代外推参考年只作用于主方法开始外推的年份以后，不覆盖已有年度海运基准。', '',
              '## 覆盖与限制', '',
              '保留主表全部月份及缺失值，不补零、不为未发布月份产生不确定性范围。不同年份可用的分配对照数量不同，详见 available_scenarios。重复数值不代表额外独立证据；情景没有概率权重。',
              '没有为活动数据、排放因子、热值、密度、CRT 清单误差和部门边界误差指定概率分布，因此尚未量化这些误差。电力效率、道路燃料归属、本地货运季节性与残余运输结构等未被全部覆盖。',
              '工业分月对照保持年度燃料总量；运输比较不同外推参考年。',
              '下表是各月最大单侧相对偏差的中位数和最大值，**不是年度总排放的不确定性**，也不能跨部门进行独立误差平方和合成。', '',
              '| 部门 | 有效月份 | 月度最大偏差中位数 | 月度最大偏差峰值 |',
              '|---|---:|---:|---:|']
    for r in summary[summary.period.eq('all_available')].itertuples():
        lines.append(f'| {NAMES[r.sector]} | {r.months} | {r.median_max_abs_deviation_pct:.2f}% | {r.maximum_max_abs_deviation_pct:.2f}% |')
    lines += ['', '## 输出与复现', '',
              '- [逐月不确定性表](sector_monthly_uncertainty.csv)',
              '- [部门汇总](sector_summary.csv)；[最新共同月份](latest_common_month.csv)',
              '- [完整情景值](monthly_scenarios.csv)；[一致性检验](checks.csv)；[输入、代码哈希](manifest.json)',
              '- `python src/cmhk/uncertainty/scenarios.py`；主入口 `python src/cmhk/uncertainty/monte_carlo.py` 也会更新本对照。', '',
              '![月度范围](monthly_uncertainty.png)', '']
    (out / 'report.md').write_text('\n'.join(lines))


def plot(result, out):
    os.environ.setdefault('MPLCONFIGDIR', str(ROOT / '.tmp/matplotlib'))
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(4, 2, figsize=(13, 12), sharex=True)
    for ax, sector in zip(axes.flat, NAMES):
        d = result[result.sector.eq(sector)].sort_values('date')
        ax.fill_between(d.date, d.lower_ktCO2 / 1000, d.upper_ktCO2 / 1000,
                        color='#db923a', alpha=.35, label='Scenario envelope')
        ax.plot(d.date, d.ktCO2 / 1000, color='#195e7b', lw=1, label='Published estimate')
        ax.set_title(sector, loc='left'); ax.set_ylabel('Mt CO2 / month'); ax.grid(alpha=.2)
    # Eight sector panels are populated.
    handles, labels = axes.flat[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc='lower center', ncol=2, frameon=False)
    fig.suptitle('Hong Kong monthly emissions | conditional model sensitivity')
    fig.text(.06, .015, 'No probability coverage assigned. Input, emission-factor and inventory errors are not included.', fontsize=10)
    fig.tight_layout(rect=[0, .04, 1, .96])
    for ext in ['png', 'pdf']:
        fig.savefig(out / f'monthly_uncertainty.{ext}', dpi=180)
    plt.close(fig)


def main(root=ROOT):
    inputs = ['configs/model.json', 'outputs/hong_kong_sector_monthly.csv',
              'outputs/diagnostics/monthly_scenarios.csv',
              'outputs/diagnostics/industry_proxy_components.csv',
              'outputs/diagnostics/industry_proxy_calibration.csv',
              'outputs/transport_extension/monthly_transport_scenarios.csv',
              'outputs/transport_extension/annual_transport_proxy.csv',
              'outputs/transport_extension/proxy_manifest.json',
              'data/processed/domestic_ferry_passengers.csv',
              'outputs/diagnostics/official_baseline_calibration.csv']
    config = json.loads((root / inputs[0]).read_text())
    points = pd.read_csv(root / inputs[1], parse_dates=['date'])
    existing = pd.read_csv(root / inputs[2], parse_dates=['date'])
    calibration = pd.read_csv(root / inputs[9], index_col='sector')
    existing = calibrate_scenarios(existing, config, calibration)
    components = pd.read_csv(root / inputs[3], parse_dates=['date'])
    anchors = pd.read_csv(root / inputs[4], index_col='year').sort_index()
    marine = pd.read_csv(root / inputs[5], parse_dates=['date'])
    annual = pd.read_csv(root / inputs[6], index_col='year')
    baseline = json.loads((root / inputs[7]).read_text())['baseline_ktCO2']
    ferry = pd.read_csv(root / inputs[8], parse_dates=['date']).set_index('date').ferry_passengers_thousand
    frames = [points[['date', 'sector', 'ktCO2']].assign(scenario='published')]
    frames.append(existing[existing.sector.isin(set(NAMES) - {'Industry', 'Road Transport', 'Domestic Navigation'})]
                  [['date', 'sector', 'scenario', 'ktCO2']])
    checks = []

    def append(sector, name, values):
        frames.append(values.rename('ktCO2').rename_axis('date').reset_index().assign(sector=sector, scenario=name))

    def check(name, actual, expected):
        passed = bool(np.allclose(actual, expected, rtol=1e-10, atol=1e-8, equal_nan=True))
        checks.append(dict(check=name, passed=passed))
        if not passed:
            raise ValueError(f'Uncertainty consistency check failed: {name}')

    industry = industry_alternatives(components, anchors)
    for name, values in industry.items():
        append('Industry', name, values)
        for year in anchors.index:
            check(f'Industry/{name}/anchor/{year}', values[values.index.year == year].sum(min_count=12), anchors.loc[year, 'total_ktCO2'])
    check('Industry/reconstruct_published', industry['selected/observed_proxy'],
          points[points.sector.eq('Industry')].set_index('date').ktCO2.reindex(industry['selected/observed_proxy'].index))

    aviation = points[points.sector.eq('International Aviation')].set_index('date').ktCO2
    for mask, freq in [(aviation.index.year < 2013, 'Y'), (aviation.index.year >= 2013, 'Q')]:
        original = aviation[mask]
        alt = calendar_alternative(original, freq)
        # No complete quarter margin exists in the forecast tail. Keep its
        # movement-based forecast, without normalizing two months to a quarter.
        forecasts = points[points.sector.eq('International Aviation') & points.get('temporal_status',pd.Series('',index=points.index)).eq('activity_nowcast')].date
        alt.loc[alt.index.isin(forecasts)] = original.reindex(alt.index[alt.index.isin(forecasts)])
        append('International Aviation', f'calendar_days_{freq}', alt)
        complete_periods = original.groupby(original.index.to_period(freq)).count()
        complete_periods = complete_periods[complete_periods.eq(12 if freq=='Y' else 3)].index
        check(f'Aviation/{freq}/conservation', alt.groupby(alt.index.to_period(freq)).sum(min_count=1).reindex(complete_periods),
              original.groupby(original.index.to_period(freq)).sum(min_count=1).reindex(complete_periods))

    transport_config = config['transport_proxy']
    reference = transport_config['extrapolation_reference_year']
    reference_years = sorted(annual.loc[:reference].dropna(subset=['marine_TJ']).index)[-2:]
    from cmhk.benchmarks.official import calibrate_series
    for road_name,road_block in existing[existing.sector.eq('Road')].groupby('scenario'):
        road,_=calibrate_series(road_block.set_index('date').ktCO2,baseline['transport']-baseline['marine'],2021)
        append('Road Transport',road_name,road)
        check(f'Road Transport/{road_name}/CRT2021',road.loc['2021'].sum(),baseline['transport']-baseline['marine'])
    for marine_name,block in marine.groupby('scenario'):
        block=block.set_index('date').sort_index()
        for ref_year in reference_years:
            navigation=block.marine_calibrated_proxy_ktCO2.copy()
            ref_dates=pd.date_range(f'{ref_year}-01-01',periods=12,freq='MS')
            dates=block.index[block.index.year>reference]
            navigation.loc[dates]=baseline['marine']/annual.loc[2021,'marine_TJ']*(
                ferry.reindex(dates)*annual.loc[ref_year,'passenger_marine_TJ']/ferry.reindex(ref_dates).sum()
                +dates.days_in_month*annual.loc[ref_year,'freight_marine_TJ']/np.sum(ref_dates.days_in_month))
            name=f'{marine_name}/reference_{ref_year}'
            append('Domestic Navigation',name,navigation)
            check(f'Navigation/{name}/CRT2021',navigation.loc['2021'].sum(),baseline['marine'])

    scenarios = pd.concat(frames, ignore_index=True)
    coverage = points[['date', 'sector', 'ktCO2']].rename(columns={'ktCO2': 'point'})
    scenarios = scenarios.merge(coverage, on=['date', 'sector'], how='inner', validate='many_to_one')
    scenarios['ktCO2'] = scenarios.ktCO2.where(scenarios.point.notna())
    scenarios = scenarios.drop(columns='point').sort_values(['sector', 'date', 'scenario'])
    result = envelopes(points, scenarios).sort_values(['sector', 'date'])
    valid = result[result.ktCO2.notna()]
    common = valid.groupby('date').sector.nunique()
    latest_date = common[common.eq(len(NAMES))].index.max()
    latest = result[result.date.eq(latest_date)]
    full_years = valid.groupby([valid.date.dt.year, 'sector']).size().unstack('sector')
    latest_year = int(full_years.index[full_years.eq(12).all(axis=1)].max())
    summaries = []
    for period, block in [('all_available', valid), (str(latest_year), valid[valid.date.dt.year.eq(latest_year)])]:
        summaries.append(block.groupby('sector').agg(
            first_month=('date', 'min'), last_month=('date', 'max'), months=('date', 'count'),
            median_down_pct=('down_pct', 'median'), median_up_pct=('up_pct', 'median'),
            median_max_abs_deviation_pct=('max_abs_deviation_pct', 'median'),
            maximum_max_abs_deviation_pct=('max_abs_deviation_pct', 'max')).reset_index().assign(period=period))
    summary = pd.concat(summaries, ignore_index=True)
    out = root / 'outputs/uncertainty/scenario_sensitivity'
    out.mkdir(parents=True, exist_ok=True)
    result.to_csv(out / 'sector_monthly_uncertainty.csv', index=False)
    scenarios.to_csv(out / 'monthly_scenarios.csv', index=False)
    summary.to_csv(out / 'sector_summary.csv', index=False)
    latest.to_csv(out / 'latest_common_month.csv', index=False)
    pd.DataFrame(checks).to_csv(out / 'checks.csv', index=False)
    write_report(result, summary, latest, out)
    plot(result, out)
    manifest = dict(method='deterministic conditional model-sensitivity envelope', confidence_level=None,
                    input_error_distributions=None, transport_reference_years=reference_years,
                    latest_common_month=str(latest_date.date()), latest_complete_year=latest_year,
                    as_of=config['as_of'], official_baseline=config['official_baseline'],
                    checks_passed=all(c['passed'] for c in checks),
                    input_sha256={p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in inputs},
                    code_sha256=code_hashes(root, ['scenario_uncertainty.py', 'official_baseline.py']),
                    versions=dict(numpy=np.__version__, pandas=pd.__version__))
    (out / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(latest[['date', 'sector', 'ktCO2', 'lower_ktCO2', 'upper_ktCO2', 'down_pct', 'up_pct']].to_string(index=False))
    print(f'{len(valid)} estimated months; {len(checks)} consistency checks passed. Output: {out}')
    return result, scenarios


if __name__ == '__main__':
    main()
