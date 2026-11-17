"""Disaggregate the annual 1.A.3 road + domestic marine proxy conservatively.

Observed ferry passenger journeys shape only passenger-marine energy. Freight
marine energy uses calendar days. Before the ferry snapshot starts in 2013,
passenger marine also uses days. Neither allocation measures monthly fuel use.
"""
from pathlib import Path
import hashlib
import json
import os
import numpy as np
import pandas as pd

from cmhk.paths import ROOT, code_hashes
os.environ.setdefault('MPLCONFIGDIR', str(ROOT / '.tmp/matplotlib'))
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from cmhk.kernels import constrained_months

FERRY_OPERATORS = ['LFS', 'NWFF', 'STF']
FERRY_START_YEAR = 2013
SCENARIOS = ['ferry_passengers_freight_days', 'all_marine_calendar_days']


def ferry_passengers(path):
    data = pd.read_csv(path)
    data = data[data.MODE.eq('Ferries')].copy()
    if set(data.TTD_PTO_CODE) != set(FERRY_OPERATORS):
        raise ValueError('Ferry operator coverage changed; review table definition')
    data['date'] = pd.to_datetime(data.YR_MTH.astype(str), format='%Y%m')
    if data.duplicated(['date', 'TTD_PTO_CODE']).any():
        raise ValueError('Duplicate ferry operator/month')
    data['PAX'] = pd.to_numeric(data.PAX, errors='raise')
    if not np.isfinite(data.PAX).all() or data.PAX.lt(0).any():
        raise ValueError('Invalid ferry passenger counts')
    panel = data.pivot(index='date', columns='TTD_PTO_CODE', values='PAX').reindex(columns=FERRY_OPERATORS)
    if panel.index.min() != pd.Timestamp('2013-01-01'):
        raise ValueError('Ferry history changed; review early calendar fallback')
    if panel.isna().any().any():
        raise ValueError('Incomplete ferry operator panel')
    result = panel.sum(axis=1, min_count=len(FERRY_OPERATORS)).rename('ferry_passengers_thousand')
    return result


def allocate_marine(year, passenger_tj, freight_tj, ferry, scenario):
    if scenario not in SCENARIOS:
        raise ValueError(f'Unknown allocation scenario: {scenario}')
    dates = pd.date_range(f'{year}-01-01', periods=12, freq='MS')
    days = pd.Series(dates.days_in_month.astype(float), index=dates)
    if scenario == SCENARIOS[0] and year >= FERRY_START_YEAR:
        weights = ferry.reindex(dates)
        method = 'TD monthly ferry passengers; excludes kaitos; passenger-energy proxy'
    else:
        weights = days
        method = 'calendar days; pre-2013 ferry history unavailable' if year < FERRY_START_YEAR else 'calendar days; sensitivity alternative'
    # constrained_months rejects incomplete years rather than rescaling surviving months.
    result = pd.DataFrame(index=dates)
    result['passenger_marine_TJ'] = constrained_months(passenger_tj, weights, year, 'Y')
    result['freight_marine_TJ'] = constrained_months(freight_tj, days, year, 'Y')
    result['marine_TJ'] = result.passenger_marine_TJ + result.freight_marine_TJ
    result['passenger_allocation'] = method
    result['freight_allocation'] = 'calendar days; monthly domestic freight-fuel activity unavailable'
    return result


def disaggregate(annual, road, ferry, dates, scenario):
    if annual.index.has_duplicates or road.index.has_duplicates or ferry.index.has_duplicates:
        raise ValueError('Duplicate input periods')
    result = pd.DataFrame(index=dates)
    result.index.name = 'date'
    columns = ['road_model_ktCO2', 'road_calibrated_proxy_ktCO2', 'passenger_marine_TJ',
               'freight_marine_TJ', 'marine_TJ', 'marine_calibrated_proxy_ktCO2',
               'residual_assumed_proxy_ktCO2', 'transport_proxy_ktCO2']
    for col in columns:
        result[col] = np.nan
    result['status'] = 'annual marine/transport benchmark unavailable'
    result['passenger_allocation'] = ''
    result['freight_allocation'] = ''
    result['scenario'] = scenario
    result['ferry_passengers_thousand'] = ferry.reindex(dates)
    checks = []
    for year, row in annual.dropna(subset=['transport_proxy_ktCO2']).iterrows():
        marine = allocate_marine(int(year), row.passenger_marine_TJ, row.freight_marine_TJ, ferry, scenario)
        months = marine.index
        if not months.isin(dates).all():
            raise ValueError('Cannot allocate a full-year benchmark to a partial output calendar')
        r = road.reindex(months)
        if not np.isfinite(r).all() or r.lt(0).any() or r.sum() <= 0:
            raise ValueError(f'Incomplete/invalid road year: {year}')
        if not np.isclose(r.sum(), row.road_model_ktCO2, rtol=1e-10):
            raise ValueError('Monthly road data do not match annual proxy inputs; regenerate annual proxy')
        block = marine.copy()
        block['road_model_ktCO2'] = r
        block['road_calibrated_proxy_ktCO2'] = r / r.sum() * row.road_calibrated_proxy_ktCO2
        block['marine_calibrated_proxy_ktCO2'] = marine.marine_TJ / row.marine_TJ * row.marine_calibrated_proxy_ktCO2
        combined = block.road_calibrated_proxy_ktCO2 + block.marine_calibrated_proxy_ktCO2
        annual_combined = row.road_calibrated_proxy_ktCO2 + row.marine_calibrated_proxy_ktCO2
        block['residual_assumed_proxy_ktCO2'] = combined / annual_combined * row.residual_assumed_proxy_ktCO2
        block['transport_proxy_ktCO2'] = combined + block.residual_assumed_proxy_ktCO2
        for col in columns + ['passenger_allocation', 'freight_allocation']:
            result.loc[months, col] = block[col]
        result.loc[months, 'status'] = 'annual-constrained modelled monthly allocation'
        for col in ['passenger_marine_TJ', 'freight_marine_TJ', 'marine_TJ',
                    'road_calibrated_proxy_ktCO2', 'marine_calibrated_proxy_ktCO2',
                    'residual_assumed_proxy_ktCO2', 'transport_proxy_ktCO2']:
            actual = block[col].sum(min_count=12)
            expected = row[col]
            passed = bool(np.isclose(actual, expected, rtol=1e-10, atol=1e-8))
            checks.append(dict(year=year, scenario=scenario, variable=col,
                               annual_target=expected, monthly_sum=actual,
                               residual=actual-expected, passed=passed))
            if not passed:
                raise ValueError(f'Annual conservation failed: {year}/{col}')
    result['complete'] = result.transport_proxy_ktCO2.notna()
    result['estimate_label'] = 'Modelled monthly allocation; not observed fuel emissions'
    result['baseline_year'] = 2021
    previous = result.transport_proxy_ktCO2.reindex(result.index-pd.DateOffset(years=1)).to_numpy()
    result['yoy_pct'] = (result.transport_proxy_ktCO2.to_numpy()/previous-1)*100
    return result, pd.DataFrame(checks)


def extrapolate(frame, annual, road, ferry, cutoff, reference_year=2024, base_year=2021):
    """Extend only months with activity; never divide by an incomplete target year."""
    reference=annual.loc[reference_year]
    base=annual.loc[base_year]
    ref_dates=pd.date_range(f'{reference_year}-01-01',periods=12,freq='MS')
    ref_pax=ferry.reindex(ref_dates)
    if not np.isfinite(ref_pax).all() or ref_pax.lt(0).any() or ref_pax.sum()<=0:
        raise ValueError('Complete positive reference-year ferry activity required')
    ref_days=int(np.sum(ref_dates.days_in_month))
    coefficients=dict(reference_year=int(reference_year),
        passenger_TJ_per_thousand_journeys=float(reference.passenger_marine_TJ/ref_pax.sum()),
        freight_TJ_per_day=float(reference.freight_marine_TJ/ref_days),
        road_calibration=float(base.road_calibrated_proxy_ktCO2/base.road_model_ktCO2),
        marine_ktCO2_per_TJ=float(base.marine_calibrated_proxy_ktCO2/base.marine_TJ),
        full_transport_multiplier=float(base.transport_proxy_ktCO2/(base.road_calibrated_proxy_ktCO2+base.marine_calibrated_proxy_ktCO2)))
    if any(not np.isfinite(v) or v<=0 for v in coefficients.values()):
        raise ValueError('Invalid extrapolation coefficients')
    result=frame.copy()
    result['extrapolated']=False
    result['extrapolation_reference_year']=np.nan
    candidates=result.index[(result.index.year>reference_year)&(result.index+pd.offsets.MonthEnd()<=pd.Timestamp(cutoff))]
    for date in candidates:
        if pd.notna(result.loc[date,'transport_proxy_ktCO2']):
            continue
        r=road.get(date,np.nan);p=ferry.get(date,np.nan)
        if not np.isfinite(r) or not np.isfinite(p):
            result.loc[date,'status']='missing road or ferry activity; no extrapolation'
            continue
        if r<0 or p<0:raise ValueError('Negative extrapolation activity')
        # Primary and sensitivity share the same forward model. The sensitivity
        # experiment compares historical allocation, not unobserved annual totals.
        passenger=p*coefficients['passenger_TJ_per_thousand_journeys']
        freight=date.days_in_month*coefficients['freight_TJ_per_day']
        marine=(passenger+freight)*coefficients['marine_ktCO2_per_TJ']
        calibrated_road=r*coefficients['road_calibration']
        combined=calibrated_road+marine
        total=combined*coefficients['full_transport_multiplier']
        for key,value in dict(road_model_ktCO2=r,road_calibrated_proxy_ktCO2=calibrated_road,
            passenger_marine_TJ=passenger,freight_marine_TJ=freight,marine_TJ=passenger+freight,
            marine_calibrated_proxy_ktCO2=marine,residual_assumed_proxy_ktCO2=total-combined,
            transport_proxy_ktCO2=total).items():result.loc[date,key]=value
        result.loc[date,'passenger_allocation']='extrapolated: reference-year TJ per ferry passenger'
        result.loc[date,'freight_allocation']='extrapolated: reference-year TJ per calendar day'
        result.loc[date,'status']='modelled extrapolation; no target-year marine energy benchmark'
        result.loc[date,'estimate_label']='Modelled extrapolation; fixed marine intensity'
        result.loc[date,'extrapolated']=True
        result.loc[date,'extrapolation_reference_year']=reference_year
    result['complete']=result.transport_proxy_ktCO2.notna()
    previous=result.transport_proxy_ktCO2.reindex(result.index-pd.DateOffset(years=1)).to_numpy()
    result['yoy_pct']=(result.transport_proxy_ktCO2.to_numpy()/previous-1)*100
    return result,coefficients


def annual_summary(primary):
    rows=[]
    for year,block in primary.groupby(primary.index.year):
        valid=block[block.complete]
        prior=primary.transport_proxy_ktCO2.reindex(valid.index-pd.DateOffset(years=1))
        total=valid.transport_proxy_ktCO2.sum() if len(valid) else np.nan
        comparable=len(valid)>0 and prior.notna().all() and prior.sum()>0
        rows.append(dict(year=year,transport_proxy_ktCO2=total,months=len(valid),
            full_year=len(valid)==12,first_month=valid.index.min(),last_month=valid.index.max(),
            extrapolated_months=int(valid.extrapolated.sum()),
            yoy_same_months_pct=(total/prior.sum()-1)*100 if comparable else np.nan))
    return pd.DataFrame(rows).set_index('year')


def main():
    out = ROOT/'outputs/transport_extension'
    config = json.loads((ROOT/'configs/model.json').read_text())
    if config['transport_proxy']['monthly_method'] != SCENARIOS[0] or config['transport_proxy']['baseline_year'] != 2021:
        raise ValueError('Unsupported production transport configuration')
    annual_path = out/'annual_transport_proxy.csv'
    road_path = ROOT/'outputs/diagnostics/road_monthly_proxy.csv'
    ferry_path = ROOT/'data/raw/td_21.csv'
    if not ferry_path.exists():
        raise FileNotFoundError('Missing td_21.csv; run python src/cmhk/sources/download.py to obtain the ferry snapshot')
    annual = pd.read_csv(annual_path, index_col='year')
    model = pd.read_csv(road_path, parse_dates=['date'])
    road = model[model.sector.eq('Road')].set_index('date').ktCO2
    ferry = ferry_passengers(ferry_path)
    dates = pd.date_range(f'{config["start_year"]}-01-01', f'{config["end_year"]}-12-01', freq='MS')
    frames, checks = [], []
    for scenario in SCENARIOS:
        frame, audit = disaggregate(annual, road, ferry, dates, scenario)
        if frame.loc[frame.index+pd.offsets.MonthEnd() > pd.Timestamp(config['as_of']), 'complete'].any():
            raise ValueError('Annual allocation would fill months beyond the configured cutoff')
        frame,coefficients=extrapolate(frame,annual,road,ferry,config['as_of'],config['transport_proxy']['extrapolation_reference_year'])
        frames.append(frame); checks.append(audit)
    primary, alternative = frames
    primary.to_csv(out/'monthly_transport_proxy.csv')
    summary=annual_summary(primary)
    summary.to_csv(out/'annual_transport_monthly_summary.csv')
    pd.concat(frames).to_csv(out/'monthly_transport_scenarios.csv')
    pd.concat(checks, ignore_index=True).to_csv(out/'monthly_conservation_checks.csv', index=False)
    sensitivity = pd.DataFrame({'primary_ktCO2': primary.transport_proxy_ktCO2,
                                'all_days_ktCO2': alternative.transport_proxy_ktCO2})
    sensitivity['difference_ktCO2'] = sensitivity.primary_ktCO2-sensitivity.all_days_ktCO2
    sensitivity['difference_pct_of_primary'] = sensitivity.difference_ktCO2/sensitivity.primary_ktCO2*100
    sensitivity.to_csv(out/'monthly_allocation_sensitivity.csv')
    ferry.to_csv(ROOT/'data/processed/domestic_ferry_passengers.csv')
    inputs = [annual_path, out/'proxy_manifest.json', road_path, ferry_path,
              ferry_path.with_suffix('.csv.source.json'), ROOT/'data/raw/td_dictionary.pdf', ROOT/'configs/model.json']
    (out/'monthly_manifest.json').write_text(json.dumps(dict(
        extrapolation=coefficients,
        extrapolation_requires='finite nonnegative monthly road and ferry observations; complete month at/before cutoff',
        baseline_year=2021, annual_proxy='annual_transport_proxy.csv',
        primary_scenario=SCENARIOS[0], sensitivity_scenario=SCENARIOS[1],
        unit='ktCO2; marine energy TJ; ferry passengers thousand journeys',
        assumptions=['passenger marine energy follows ferry passengers within each year',
                     'freight marine energy constant per calendar day',
                     'passenger energy before 2013 constant per calendar day',
                     'remaining 1.A.3 components follow combined monthly road/marine proxy'],
        model_cutoff=config['as_of'], ferry_snapshot=json.loads(ferry_path.with_suffix('.csv.source.json').read_text()),
        source_scope='TD Ferries: franchised/licensed inner-harbour services, excludes kaitos; not a complete domestic navigation activity measure',
        used_by_main_transport=True,
        inputs_sha256={str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs},
        code_sha256=code_hashes(names=['transport_monthly.py', 'model.py'])
    ), indent=2)+'\n')
    plot(primary, alternative, out)
    report(primary, sensitivity, out)
    from cmhk.sectors.transport_annual import plot as annual_plot
    annual_plot(annual,out,summary)
    valid = primary[primary.complete]
    print(f'{len(valid)} monthly estimates: {valid.index.min().date()} to {valid.index.max().date()}; {sum(len(c) for c in checks)} conservation checks passed')
    print(f'Maximum allocation-scenario difference: {sensitivity.difference_pct_of_primary.abs().max():.3f}% of monthly transport proxy')


def plot(primary, alternative, out):
    valid = primary[primary.complete]
    fig, axes = plt.subplots(2, 1, figsize=(12, 7), gridspec_kw={'height_ratios':[2,1]})
    axes[0].plot(valid.index, valid.transport_proxy_ktCO2/1000, color='#176B87', lw=1.2, label='Full 1.A.3 monthly proxy')
    extra=valid[valid.extrapolated]
    axes[0].plot(extra.index,extra.transport_proxy_ktCO2/1000,color='#D28A2D',lw=1.5,label='Fixed-intensity extrapolation')
    axes[0].set_ylabel('Mt CO2 / month');axes[0].set_title('Monthly transport CO2 | road + domestic marine proxy', loc='left')
    year = valid[~valid.extrapolated].index.year.max()
    a, b = primary.loc[str(year)], alternative.loc[str(year)]
    axes[1].plot(a.index.month, a.transport_proxy_ktCO2/1000, '-o', color='#176B87', label='Ferry passenger profile + freight by days')
    axes[1].plot(b.index.month, b.transport_proxy_ktCO2/1000, '--', color='#D28A2D', label='All marine energy by calendar days')
    axes[1].set_title(f'{year}: sensitivity to marine monthly allocation (same annual totals)',loc='left',fontsize=11)
    axes[1].set_xticks(range(1,13));axes[1].set_xlabel('Month');axes[1].set_ylabel('Mt CO2 / month')
    for ax in axes: ax.legend(fontsize=9);ax.grid(alpha=.2)
    fig.text(.08,.02,'Modelled monthly allocation, not measured fuel use. Pre-2013 marine: days only. After 2024: fixed-intensity extrapolation from ferry passengers and days.',fontsize=9)
    fig.tight_layout(rect=[0,.05,1,1])
    for ext in ['png','pdf']:fig.savefig(out/f'monthly_transport_proxy.{ext}',dpi=200)
    plt.close(fig)


def report(primary, sensitivity, out):
    valid=primary[primary.complete]
    summary=annual_summary(primary)
    recent=summary.loc[2025:]
    lines=['# 完整 1.A.3 月度代理估算','',
        f'已生成 {valid.index.min():%Y-%m} 至 {valid.index.max():%Y-%m} 的 {len(valid)} 个月。继承年度代理的 2021 CRT 权重及总量标定。',
        '2008–2024 为年度约束下的月度分配，2025 起为固定强度外推，均不是观测到的月度燃料排放；主数据表的 Transport 已采用本方法，代表完整 1.A.3；道路输入另存 diagnostics/road_monthly_proxy.csv。','',
        '## 月度构造','',
        '1. 道路沿用现有月度变化，按年度代理中的 CRT 标定道路分量缩放。',
        '2. 海运客运：EMSD 年度客运 Marine 能耗 × 当月渡轮客运量 / 全年渡轮客运量。2013 年起使用运输署表 2.1 的 Ferries，汇总 LFS、NWFF、STF，PAX 已是当月千人次，不再乘天数。',
        '3. 海运货运：EMSD 年度货运 Marine 能耗按各月天数分配。2008–2012 年客运也按天数分配，明确标记为缺乏早期客流历史的假设。',
        '4. 两类海运月度能耗之和 × 年度代理采用的固定清单/能耗系数，得到海运月度 CO₂ 代理。',
        '5. 道路与海运相加后，以年度方法的同一比例扩展至整个 1.A.3；剩余约 3.6% 随综合月度变化。','',
        '2008–2024 年的海运客运能耗、货运能耗、道路标定分量、海运标定分量、残余分量及全运输排放都严格回到各自年度值。2025 起不强制保持 2024 年总量。缺失活动月份不按零处理，也不将年度基准压到部分月份。','',
        '## 月度代理的限制','',
        '- 运输署定义的 Ferries 包括专营和持牌本地渡轮，不含街渡；不代表全部本地航运。客流还受载客率影响，燃油不必与客流成正比。',
        '- 海运货运缺少合适的本地月度耗油/活动序列，按天数分配不反映真实货运季节性。',
        '- 不用国际供油、全部到港船次或跨境旅客替代本地海运活动。',
        '- 2005–2007 仍留空；2025 起客运能耗＝2024 年客运 TJ/全年客流 × 当月客流；货运能耗＝2024 年货运 TJ/366 天 × 当月天数。无未来客流或道路数据的月份留空，不按部分年份强行分配全年基准。',
        '- 源渡轮表为新增下载快照，获取时间见 sidecar/manifest；并非声称与原模型每项输入在同一天获取。','',
        '## 月度分配敏感性','',
        '另输出“全部海运按天数”的历史分配对照；2008–2024 两方案年度值完全相同。2025 起两方案共用已落定的客流外推，不把相同值误当成外推没有不确定性。这个差异只反映该分配选择，不是总不确定度或置信区间。',
        f'在全部有效月份中，两方案全运输月值最大差异为 {sensitivity.difference_pct_of_primary.abs().max():.2f}%（相对于主代理月值）。','',
        '![月度运输代理](monthly_transport_proxy.png)','',
        '## 文件与复现','',
        '- `monthly_transport_proxy.csv`：主方案，日期为月初；含道路/海运/残余分量、分配方法、状态、同比。',
        '- `annual_transport_monthly_summary.csv`：月度结果年度/部分年份累计，含 months、full_year、外推月数和同月范围同比；2026 不年化。',
        '- `extrapolated`、`extrapolation_reference_year` 明确外推状态与强度参考年；源年度基准仍保存在 annual_transport_proxy.csv。',
        '- `monthly_transport_scenarios.csv`：两个方案，唯一键为 date＋scenario。',
        '- `monthly_conservation_checks.csv`：年度守恒检查；`monthly_allocation_sensitivity.csv`：分配敏感性。',
        '- 单位：`*_ktCO2` 为千吨 CO₂，`*_TJ` 为太焦耳，`ferry_passengers_thousand` 为千人次，`yoy_pct` 为同月同比百分比。',
        '- `complete` 仅表示该月所需输入可用；`status` 与 allocation 字段区分日历假设与渡轮客流代理。',
        '- 下载入口：`python src/cmhk/sources/download.py`（新增 `td_21.csv`）；复现：先 `python src/cmhk/sectors/transport_annual.py`，再 `python src/cmhk/sectors/navigation.py`。',
        '- [运输署表 2.1 原始 CSV](https://www.td.gov.hk/datagovhk_tis/mttd-csv/en/table21_eng.csv)；[字段说明](https://www.td.gov.hk/datagovhk_tis/mttd-csv/en/mttd_dataspec_eng.pdf)。']
    lines += ['','## 新增外推累计（不是年度基准）','','| 年份 | 月数 | 全年 | 运输 MtCO₂ | 同月范围同比 |','|---|---:|---|---:|---:|']
    for r in recent.itertuples():
        lines.append(f'| {r.Index} | {r.months} | {r.full_year} | {r.transport_proxy_ktCO2/1000:.3f} | {r.yoy_same_months_pct:+.2f}% |')
    (out/'monthly_report.md').write_text('\n'.join(lines)+'\n')


if __name__=='__main__':main()
