"""Prior-period activity nowcasts; selections never use the evaluation period."""
from pathlib import Path
import hashlib
import json
from cmhk.paths import code_hashes

import numpy as np
import pandas as pd


def quarterly(series):
    grouped = series.groupby(series.index.to_period('Q'))
    return grouped.sum(min_count=3).where(grouped.count().eq(3)).dropna()


def ratio(target, activity, period, window, lag=1):
    """Only the exact previous window of complete periods; missing is not zero."""
    periods = pd.period_range(end=period-lag, periods=window, freq='Q')
    y, x = target.reindex(periods), activity.reindex(periods)
    if y.isna().any() or x.isna().any() or x.le(0).any() or y.lt(0).any():
        return np.nan
    return float(y.sum()/x.sum())


def backtest(target, activities, settings):
    records = []
    for name, monthly in activities.items():
        activity = quarterly(monthly)
        for window in settings['ratio_windows']:
            for period, actual in target.items():
                if period.year < settings['selection_start_year'] or actual <= 0:
                    continue
                coefficient = ratio(target, activity, period, window)
                x = activity.get(period, np.nan)
                if not np.isfinite(coefficient*x):
                    continue
                predicted = coefficient*x
                split = ('selection' if period.year <= settings['selection_end_year'] else
                         'evaluation' if settings['evaluation_start_year'] <= period.year <= settings['evaluation_end_year'] else 'monitoring')
                records.append(dict(period=str(period), proxy=name, window=window,
                    split=split, observed=actual, predicted=predicted,
                    relative_error=predicted/actual-1, training_through=str(period-1)))
    result = pd.DataFrame(records)
    if result.empty:
        raise ValueError('No nowcast backtest observations')
    # Compare all candidates on identical periods.
    candidates = len(activities)*len(settings['ratio_windows'])
    common = result.groupby('period').size()
    result = result[result.period.isin(common[common.eq(candidates)].index)].copy()
    summary = result.assign(ape=result.relative_error.abs()).groupby(['proxy','window','split']).agg(
        quarters=('period','size'), mape=('ape','mean'), bias=('relative_error','mean')).reset_index()
    choices = summary[summary.split.eq('selection') & summary.quarters.ge(8)]
    if choices.empty:
        raise ValueError('Insufficient pre-evaluation selection period')
    selected = choices.sort_values(['mape','proxy','window']).iloc[0]
    return result, summary, str(selected.proxy), int(selected.window)


def intensity_prediction(history, year, method, settings):
    prior = history.loc[history.index < year].dropna().sort_index()
    if prior.empty:
        return np.nan
    base_year, level = int(prior.index[-1]), float(prior.iloc[-1])
    growth = 0.
    if method == 'damped_trend' and len(prior) >= 3:
        tail = prior.iloc[-3:]
        if np.diff(tail.index).max() != 1:
            return np.nan
        growth = np.expm1(np.log(tail.iloc[-1]/tail.iloc[0])/2)*settings['power_trend_damping']
        growth = np.clip(growth, -settings['power_max_annual_change'], settings['power_max_annual_change'])
    return level*(1+growth)**(year-base_year)


def company_mix(root, fuel_year, settings, out):
    """Use verified workbook rows; compare new HKE halves to the same prior half.

    Company weights stay at the last common complete year. Unobserved companies
    are held, so one utility's change is never assigned to all of Hong Kong.
    """
    import openpyxl
    from cmhk.sources.power_workbook import export_power_workbook
    dest = out/'company_inputs'
    dest.mkdir(exist_ok=True)
    companies, _, _ = export_power_workbook(root, dest)
    d = pd.DataFrame(companies)
    gas, coal = settings['company_proxy_gas_tCO2_per_MWh'], settings['company_proxy_coal_tCO2_per_MWh']
    d['output'] = d.gas_GWh+d.coal_class_GWh
    d['mix_intensity'] = (gas*d.gas_GWh+coal*d.coal_class_GWh)/d.output
    eligible = d[d.year.le(fuel_year)].groupby('year').company.nunique()
    base_year = int(eligible[eligible.eq(2)].index.max())
    base = d[d.year.eq(base_year)].set_index('company')
    weight = base.output/base.output.sum()
    workbook = openpyxl.load_workbook(root/'data/raw/power/HK_power_generation_2010_2025.xlsx', read_only=True, data_only=True)
    halves = {}
    for row in workbook['HKE generation'].iter_rows(min_row=2, values_only=True):
        year, half, g, c, *_ = row
        halves[(int(year), half)] = (gas*g+coal*c)/(g+c)
    workbook.close()
    audit = []
    for row in d.itertuples():
        audit.append(dict(company=row.company, year=row.year, half='annual',
                          mix_intensity=row.mix_intensity, reference_year=base_year,
                          weight=weight[row.company], available_for_update=row.year>fuel_year))
    for (year, half), value in halves.items():
        audit.append(dict(company='HK Electric', year=year, half=half, mix_intensity=value,
            reference_year=base_year, weight=weight['HK Electric'], available_for_update=year>fuel_year))
    pd.DataFrame(audit).to_csv(out/'company_intensity_inputs.csv', index=False)

    def update(date):
        indices = {'CLP':1., 'HK Electric':1.}
        references = []
        for company in indices:
            available = d[(d.company==company) & (d.year>fuel_year) & (d.year<date.year)]
            if len(available):
                latest = available.sort_values('year').iloc[-1]
                indices[company] = latest.mix_intensity/base.loc[company,'mix_intensity']
                references.append(f'{company}:{int(latest.year)}')
        half = 'H1' if date.month<=6 else 'H2'
        # A cached current half may inform a retrospective estimate only after it ends.
        half_end = pd.Timestamp(date.year, 6 if half=='H1' else 12, 1)+pd.offsets.MonthEnd()
        if date.year>fuel_year and half_end<=pd.Timestamp(settings['as_of']) and (date.year,half) in halves and (base_year,half) in halves:
            indices['HK Electric'] = halves[(date.year,half)]/halves[(base_year,half)]
            references.append(f'HK Electric:{date.year}{half}')
        return float(sum(weight[k]*indices[k] for k in indices)), '; '.join(references)
    return update


def apply(rows, config, root):
    """Return component rows, including labelled forecast tails and intensity paths."""
    settings = dict(config['near_realtime'], as_of=config['as_of'])
    out = root/'outputs/near_realtime'
    out.mkdir(parents=True, exist_ok=True)
    data = pd.DataFrame(rows)
    data['date'] = pd.to_datetime(data.date)
    data['temporal_status'] = np.where(data.note.fillna('').str.contains('extrapolated|carried forward'), 'fuel_activity_extrapolation', 'statistically_constrained')
    data['prediction_model'] = ''
    data['reference_period'] = data.benchmark_period.astype(str)
    data['nowcast_log_sigma'] = 0.
    data['intensity_log_sigma'] = 0.
    diagnostics, scores, selection = [], [], {}
    airport = pd.read_csv(root/'data/processed/airport.csv', parse_dates=['date']).set_index('date').movements
    marine = pd.read_csv(root/'data/processed/marine.csv', parse_dates=['date'])
    arrivals = marine.pivot(index='date', columns='kind', values='arrivals')
    activities = {
        'International Aviation': {'movements':airport},
        'International Shipping': {'all_arrivals':arrivals.sum(axis=1,min_count=2),
            'ocean_arrivals':arrivals.Ocean,
            'net_tonnage':marine.groupby('date').net_tonnage_thousand.sum(min_count=2)},
    }
    sales = pd.read_csv(root/'data/processed/csd_915-91201.csv', dtype={'period':str})
    sales = sales[(sales.freq=='M') & (sales.sv=='ELEC_LOCAL') & (sales.USER_TYPEDesc=='Total')]
    sales = pd.Series(sales.figure.to_numpy(), index=pd.to_datetime(sales.period,format='%Y%m')).sort_index()
    generation = pd.read_csv(root/'data/processed/power_generation.csv',parse_dates=['date']).set_index('date').generation_TJ
    activities['Power'] = {'electricity_sales':sales}
    extensions = []
    dates = pd.date_range(f'{config["start_year"]}-01-01',f'{config["end_year"]}-12-01',freq='MS')
    targets = {}
    for sector, proxies in activities.items():
        existing = data[data.sector.eq(sector)]
        primary = 'movements' if sector.endswith('Aviation') else 'all_arrivals' if sector.endswith('Shipping') else 'liquid_0_response_0'
        source = existing[existing.scenario.eq(primary)].groupby('date').ktCO2.sum()
        target = quarterly(generation) if sector=='Power' else quarterly(source)
        target = target[target.index.year>=2013]
        targets[sector] = target
        predictions, summary, chosen, window = backtest(target, proxies, settings)
        diagnostics.append(predictions.assign(sector=sector))
        scores.append(summary.assign(sector=sector))
        chosen_errors = predictions[(predictions.proxy==chosen)&(predictions.window==window)&predictions.split.eq('selection')]
        sigma = float(np.sqrt(np.mean(np.log(chosen_errors.observed/chosen_errors.predicted)**2)))
        selection[sector] = dict(proxy=chosen, window=window, training_end=settings['selection_end_year'], nowcast_log_sigma=sigma)
        last = target.index.max()
        last_date = last.end_time.normalize()
        for scenario, block in existing.groupby('scenario'):
            proxy_name = 'electricity_sales' if sector=='Power' else scenario
            activity = proxies[proxy_name]
            qactivity = quarterly(activity)
            # Apply the selected window to each sensitivity proxy; no future quarter total used.
            recent = block[block.date.dt.to_period('Q').eq(last)]
            totals = recent.groupby('fuel').ktCO2.sum()
            shares = totals/totals.sum()
            qtarget = target
            for date in dates:
                if date<=last_date or date+pd.offsets.MonthEnd()>pd.Timestamp(config['as_of']):
                    continue
                if date>last_date+pd.DateOffset(months=settings['max_forward_months']):
                    continue
                x = activity.get(date,np.nan)
                coefficient = ratio(qtarget,qactivity,date.to_period('Q'),window)
                if not np.isfinite(x*coefficient) or x<0:
                    continue
                predicted = float(x*coefficient)
                if sector=='Power':
                    # Intensity will be updated below. Keep the current fuel proportions.
                    predicted *= float(recent.ktCO2.sum()/generation.reindex(recent.date.unique()).sum())
                for fuel, share in shares.items():
                    template = recent[recent.fuel.eq(fuel)].iloc[-1].to_dict()
                    template.update(date=date, ktCO2=predicted*share, estimate_label='Modelled estimate',
                        benchmark_period=str(last), temporal_status='activity_nowcast',
                        prediction_model=f'{proxy_name}/trailing_{window}_quarters', reference_period=str(last),
                        nowcast_log_sigma=sigma,
                        note=f'Quarter not yet observed; prior {window} complete quarters; revised-data backtest')
                    extensions.append(template)
    data = pd.concat([data,pd.DataFrame(extensions)],ignore_index=True)
    pd.concat(diagnostics).to_csv(out/'quarterly_backtest.csv',index=False)
    pd.concat(scores).to_csv(out/'quarterly_scores.csv',index=False)

    # Annual fuel-based intensity: withhold each target year when predicting.
    power = data[data.sector.eq('Power')].copy()
    selected = power[power.scenario.eq('liquid_0_response_0') & power.temporal_status.eq('statistically_constrained')]
    annual_emissions = selected.groupby(selected.date.dt.year).ktCO2.sum(min_count=12)
    annual_generation = generation.groupby(generation.index.year).sum(min_count=12)
    energy = pd.read_csv(root/'data/processed/csd_915-91001.csv')
    fuel_year = int(energy[(energy.EN_REQ_TYPE=='Elect_gen')&(energy.sv=='F_EN_REQ')].period.max())
    intensity = (annual_emissions/annual_generation).dropna().loc[:fuel_year]
    trials = []
    for year, observed in intensity.items():
        if year<settings['selection_start_year']:
            continue
        for method in ['hold','damped_trend']:
            predicted = intensity_prediction(intensity,year,method,settings)
            trials.append(dict(year=year, method=method, observed=observed, predicted=predicted,
                relative_error=predicted/observed-1,
                split='selection' if year<=settings['selection_end_year'] else 'evaluation' if year<=settings['evaluation_end_year'] else 'monitoring',
                training_through=year-1))
    trials = pd.DataFrame(trials)
    ranking = trials[trials.split.eq('selection')].groupby('method').relative_error.agg(lambda x:x.abs().mean())
    method = str(ranking.sort_values().index[0])
    residual = trials[trials.split.eq('selection') & trials.method.eq(method)]
    intensity_sigma = float(np.sqrt(np.mean(np.log(residual.observed/residual.predicted)**2)))
    trials.to_csv(out/'power_intensity_backtest.csv',index=False)
    update = company_mix(root,fuel_year,settings,out)
    selection['Power']['intensity_method'] = method
    selection['Power']['intensity_last_fuel_year'] = fuel_year
    selection['Power']['intensity_log_sigma'] = intensity_sigma
    intensity_rows, alternatives = [], []
    for date in sorted(power.date.unique()):
        date = pd.Timestamp(date)
        if date.year<=fuel_year:
            continue
        held = intensity_prediction(intensity,date.year,'hold',settings)
        trend = intensity_prediction(intensity,date.year,'damped_trend',settings)
        company_ratio, company_refs = update(date)
        chosen = held*company_ratio if company_refs else intensity_prediction(intensity,date.year,method,settings)
        factor = chosen/held
        ix = data.sector.eq('Power') & data.date.eq(date)
        data.loc[ix,'ktCO2'] *= factor
        data.loc[ix,'intensity_log_sigma'] = intensity_sigma*np.sqrt(date.year-fuel_year)
        data.loc[ix & ~data.temporal_status.eq('activity_nowcast'),'temporal_status'] = 'intensity_nowcast'
        data.loc[ix,'prediction_model'] = data.loc[ix,'prediction_model'] + f'; intensity:{"company_mix" if company_refs else method}'
        intensity_rows.append(dict(date=date, reference_year=fuel_year, held_intensity=held,
            trend_intensity=trend, selected_intensity=chosen, scale=factor,
            company_references=company_refs, method='company_mix' if company_refs else method))
    # Complete historical paths plus alternative current-year intensities.
    primary = data[data.sector.eq('Power')&data.scenario.eq('liquid_0_response_0')]
    info = pd.DataFrame(intensity_rows).set_index('date') if intensity_rows else pd.DataFrame()
    for name in ['hold','damped_trend']:
        alt = primary.copy()
        alt['scenario'] = f'liquid_0_response_0_intensity_{name}'
        for date,row in info.iterrows():
            desired = row.held_intensity if name=='hold' else row.trend_intensity
            alt.loc[alt.date.eq(date),'ktCO2'] *= desired/row.selected_intensity
        alternatives.append(alt)
    data = pd.concat([data,*alternatives],ignore_index=True)
    if intensity_rows:
        pd.DataFrame(intensity_rows).to_csv(out/'power_intensity_update.csv',index=False)
    else:
        pd.DataFrame(columns=['date','reference_year','held_intensity','trend_intensity','selected_intensity','scale','company_references','method']).to_csv(out/'power_intensity_update.csv',index=False)
    paths = ['configs/model.json','data/processed/airport.csv','data/processed/marine.csv',
        'data/processed/power_generation.csv','data/processed/csd_915-91201.csv',
        'data/processed/csd_915-91001.csv','data/processed/csd_915-91106.csv',
        'data/raw/power/HK_power_generation_2010_2025.xlsx']
    manifest = dict(settings=settings, selection=selection,
        limitation='Revised-data pseudo holdout; actual publication vintages unavailable. Quarterly errors do not validate within-quarter timing. Company mix uses fixed output weights and proxy factors.',
        inputs_sha256={p:hashlib.sha256((root/p).read_bytes()).hexdigest() for p in paths},
        code_sha256=code_hashes())
    (out/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    lines = ['# 近实时暂估与留出回测', '',
        '2017–2022 用于方法选择；2023–2025 留出评价；2026 单列监测。每个目标只使用以前的完整季度/年度。',
        '这是当前修订数据上的伪样本外回测，未重现实际历史发布日期。季度总量误差不验证季度内月度形状。', '',
        '| 部门 | 已选代理 | 参考季度数 | 选择期 MAPE | 评价期 MAPE |', '|---|---|---:|---:|---:|']
    summary = pd.concat(scores)
    for sector, choice in selection.items():
        sub = summary[(summary.sector==sector)&(summary.proxy==choice['proxy'])&(summary.window==choice['window'])].set_index('split')
        lines.append(f"| {sector} | {choice['proxy']} | {choice['window']} | {sub.loc['selection','mape']:.2%} | {sub.loc['evaluation','mape']:.2%} |")
    lines += ['', '## 电力强度', '',
        f'按选择期误差采用 `{method}`；固定强度和阻尼趋势均保留为敏感性路径。',
        '两电原始工作簿输入已接入。以最近共同年度的输出份额作为公司权重；有更新年份的完整公司数据则更新其份额代理，港灯半年数据按同一半年比较。另一公司无新资料时保持其已知水平。',
        '煤/油类与燃气类的相对强度采用明确代理参数，不视为实测排放因子；企业资料更新情景未获得足够历史发布版本做独立回测。',
        '当前是否使用新企业数据见 power_intensity_update.csv 的 company_references；空白表示没有晚于年度燃料基准的新资料。', '',
        '## 暂估与修订', '',
        '仅填充最后已知完整季度之后、已有月度活动且已结束的月份。最长外推六个月；缺少要求的连续参考季度则留空。不将部分季度归一化成整个季度。',
        '季度统计到齐后，重新运行会用统计约束值替代活动暂估。每次内容变更保存 history/ 快照和同月修订表；初次方法变化不当作预测误差。',
        '暂估区间增加选择期对数残差 RMS，季度误差在同季度各月共享；电力强度误差在同年共享，并替代原固定 ±5% 电力外推漂移。它们是回测误差模型，未证明 95% 覆盖率。', '',
        '原始回测、评分及公司数据分别见 quarterly_backtest.csv、quarterly_scores.csv、power_intensity_backtest.csv、company_intensity_inputs.csv。']
    (out/'report.md').write_text('\n'.join(lines)+'\n')
    data.to_csv(out/'component_status.csv',index=False)
    return data.to_dict('records')
