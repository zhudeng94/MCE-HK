"""Single documented proxy estimate; no assumed industrial LPG shares."""
import hashlib
import json
from pathlib import Path
import numpy as np
import pandas as pd
from cmhk.kernels import MODELLED
from cmhk.aggregation import SCOPES, sum_complete
from cmhk.benchmarks.official import crt_benchmarks, calibrate_series, activity_baseline

from cmhk.paths import ROOT, code_hashes

from cmhk.sectors.industry import industrial_estimate


def build_point_estimate(root=ROOT):
    out=root/'outputs'
    (out/'diagnostics').mkdir(parents=True, exist_ok=True)
    (out/'provenance').mkdir(exist_ok=True)
    config=json.loads((root/'configs/model.json').read_text())
    selections=config['point_estimate_sector_methods'].copy()
    realtime = json.loads((out/'near_realtime/manifest.json').read_text()) if config.get('near_realtime',{}).get('enabled') else None
    if realtime:
        selections['International Shipping'] = realtime['selection']['International Shipping']['proxy']
    previous=pd.read_csv(out/'diagnostics/monthly_scenarios.csv',parse_dates=['date'])
    dates=pd.date_range(f'{config["start_year"]}-01-01',f'{config["end_year"]}-12-01',freq='MS')
    industry,sources=industrial_estimate(root)
    frame=pd.DataFrame(index=dates)
    frame['Industry']=industry
    for sector,method in selections.items():
        if sector in ['Road Transport','Domestic Navigation']:
            transport=pd.read_csv(out/'transport_extension/monthly_transport_proxy.csv',parse_dates=['date'])
            if sector == 'Road Transport':
                road=pd.read_csv(out/'diagnostics/road_monthly_proxy.csv',parse_dates=['date']).set_index('date').ktCO2
                target=crt_benchmarks(root,years=(2021,)).query("sector == 'Road Transport'").iloc[0].official_ktCO2
                frame[sector],_=calibrate_series(road,target,2021)
            else:
                frame[sector]=transport.set_index('date').marine_calibrated_proxy_ktCO2
            continue
        s=previous[(previous.sector==sector)&(previous.scenario==method)]
        if s.empty or s.date.duplicated().any():
            raise ValueError(f'Missing or duplicate point method: {sector}/{method}')
        frame[sector]=s.set_index('date').ktCO2
    frame=frame.reindex(columns=SCOPES['covered_sectors_plus_international_bunkers'])
    uncalibrated = frame.copy()
    baseline_config = config['official_baseline']
    year = baseline_config['year']
    if year != 2021:
        raise ValueError('Changing 2021 baseline requires reviewing Industry/Transport and reports')
    refs = crt_benchmarks(root, baseline_year=year)
    baseline = refs[refs.year.eq(year) & refs.sector.isin(frame.columns)].set_index('sector').copy()
    scales = pd.Series(1., index=frame.columns)
    for sector in baseline_config['rescale_sectors']:
        frame[sector], scales[sector] = calibrate_series(frame[sector], baseline.loc[sector, 'official_ktCO2'], year)
    for sector in frame:
        if not np.isclose(activity_baseline(frame[sector], year), baseline.loc[sector, 'official_ktCO2']):
            raise ValueError(f'Official baseline mismatch: {sector}')
    baseline['proxy_baseline_ktCO2'] = [activity_baseline(uncalibrated[s], year) for s in baseline.index]
    baseline['scale'] = scales.reindex(baseline.index)
    baseline['role'] = ['sector_activity_ratio' if s in baseline_config['rescale_sectors'] else 'existing_CRT_calibration' for s in baseline.index]
    baseline.to_csv(out/'diagnostics/official_baseline_calibration.csv')
    uncalibrated.rename_axis('date').reset_index().melt(id_vars='date', var_name='sector', value_name='ktCO2').to_csv(
        out/'diagnostics/sector_monthly_before_baseline_calibration.csv', index=False)
    comparisons = []
    before, after = uncalibrated.copy(), frame.copy()
    for scope, members in SCOPES.items():
        before[scope] = sum_complete(uncalibrated[members])
        after[scope] = sum_complete(frame[members])
    for sector in before:
        for target_year, block in after[sector].groupby(after.index.year):
            valid = block.dropna()
            dates_valid = valid.index
            old = before[sector].reindex(dates_valid)
            prior_dates = dates_valid - pd.DateOffset(years=1)
            old_prior = before[sector].reindex(prior_dates)
            new_prior = after[sector].reindex(prior_dates)
            def change(current, prior):
                return (current.sum()/prior.sum()-1)*100 if len(current) and prior.notna().all() and prior.sum()>0 else np.nan
            comparisons.append(dict(year=target_year, sector=sector, months=len(valid), full_year=len(valid)==12,
                before_ktCO2=old.sum() if len(valid) else np.nan, after_ktCO2=valid.sum() if len(valid) else np.nan,
                before_yoy_same_months_pct=change(old, old_prior), after_yoy_same_months_pct=change(valid, new_prior)))
    comparison = pd.DataFrame(comparisons)
    comparison['level_change_pct'] = (comparison.after_ktCO2/comparison.before_ktCO2-1)*100
    comparison['yoy_difference_pp'] = comparison.after_yoy_same_months_pct-comparison.before_yoy_same_months_pct
    comparison.to_csv(out/'diagnostics/baseline_calibration_comparison.csv', index=False)
    frame.loc[frame.index + pd.offsets.MonthEnd() > pd.Timestamp(config['as_of']), :] = np.nan
    frame.index.name='date'
    # Long form includes missing months explicitly.
    monthly=frame.reset_index().melt(id_vars='date',var_name='sector',value_name='ktCO2')
    monthly['method']=monthly.sector.map(selections).fillna('CRT2021 × annual industrial non-electric fuel ratio; monthly gas/electricity allocation')
    early=monthly.date.dt.year<2013
    monthly.loc[early&monthly.sector.eq('Domestic Navigation'),'method']='CRT2021 navigation; calendar allocation before 2013'
    monthly.loc[early&monthly.sector.isin(['International Aviation','International Shipping']),'method']='historical annual supplied fuel + monthly aircraft/vessel activity'
    monthly.loc[early&monthly.sector.eq('Power'),'method']='historical annual fuel/generation + monthly electricity sales profile'
    extra_dates=transport.loc[transport.extrapolated,'date']
    monthly.loc[monthly.sector.eq('Domestic Navigation') & monthly.date.isin(extra_dates),'method']='CRT2021 navigation; marine extrapolated from 2024 TJ/ferry-passenger and TJ/day'
    monthly['activity_method'] = monthly['method']
    anchored = monthly.sector.isin(baseline_config['rescale_sectors'])
    monthly.loc[anchored, 'method'] = f'CRT{year} baseline × relative activity; ' + monthly.loc[anchored, 'method']
    monthly['baseline_year'] = year
    monthly['calibration_scale'] = monthly.sector.map(scales)
    monthly['temporal_status'] = np.where(monthly.ktCO2.notna(), 'activity_model', 'no_estimate')
    monthly['prediction_model'] = ''
    monthly['reference_period'] = ''
    monthly['nowcast_log_sigma'] = 0.
    monthly['intensity_log_sigma'] = 0.
    if realtime:
        status = pd.read_csv(out/'near_realtime/component_status.csv',parse_dates=['date'])
        selected_status = pd.concat([status[status.sector.eq(s)&status.scenario.eq(m)] for s,m in selections.items()])
        selected_status = selected_status.groupby(['date','sector'],as_index=False).agg(
            temporal_status=('temporal_status','first'), prediction_model=('prediction_model','first'),
            reference_period=('reference_period','first'), nowcast_log_sigma=('nowcast_log_sigma','max'),
            intensity_log_sigma=('intensity_log_sigma','max'))
        monthly = monthly.drop(columns=['temporal_status','prediction_model','reference_period','nowcast_log_sigma','intensity_log_sigma']).merge(
            selected_status,on=['date','sector'],how='left',validate='one_to_one')
        monthly['temporal_status'] = monthly.temporal_status.fillna('activity_model').where(monthly.ktCO2.notna(),'no_estimate')
        monthly['nowcast_log_sigma'] = monthly.nowcast_log_sigma.fillna(0.)
        monthly['intensity_log_sigma'] = monthly.intensity_log_sigma.fillna(0.)
        for col in ['prediction_model','reference_period']:
            monthly[col] = monthly[col].fillna('')
        forecast = monthly.temporal_status.isin(['activity_nowcast','intensity_nowcast']) & monthly.ktCO2.notna()
        monthly.loc[forecast,'method'] += '; '+monthly.loc[forecast,'temporal_status']+': '+monthly.loc[forecast,'prediction_model']
    industrial_status=pd.read_csv(out/'diagnostics/industry_proxy_components.csv',parse_dates=['date']).groupby('date').temporal_status.first()
    mask=monthly.sector.eq('Industry') & monthly.ktCO2.notna()
    monthly.loc[mask,'temporal_status']=monthly.loc[mask,'date'].map(industrial_status)
    monthly['estimate_label']=MODELLED
    monthly['as_of']=config['as_of']
    if realtime:
        from cmhk.revision_history import record_snapshot
        record_snapshot(monthly,root)
    monthly.to_csv(out/'hong_kong_sector_monthly.csv',index=False)
    coverage=monthly.dropna(subset=['ktCO2']).groupby('sector').date.agg(['min','max','count'])
    coverage.to_csv(out/'diagnostics/historical_coverage.csv')
    records=[]
    annual=[]
    for scope,sectors in SCOPES.items():
        sub=frame[sectors]
        summed=sum_complete(sub)
        status_by_date = monthly[monthly.sector.isin(sectors)].groupby('date').temporal_status.agg(
            lambda s: int(s.isin(['activity_nowcast','intensity_nowcast']).sum()))
        for date,value in summed.items():
            records.append(dict(date=date,scope=scope,ktCO2=value,available_sectors=int(sub.loc[date].count()),
                                required_sectors=len(sectors),complete=bool(pd.notna(value)),
                                estimate_label=MODELLED,as_of=config['as_of'],
                                nowcast_sectors=int(status_by_date.loc[date]),
                                temporal_status='no_estimate' if pd.isna(value) else 'contains_nowcast' if status_by_date.loc[date]>0 else 'activity_model'))
        for year,block in summed.groupby(summed.index.year):
            valid=block.dropna()
            prior=summed.reindex(valid.index-pd.DateOffset(years=1))
            comparable=len(valid)>0 and prior.notna().all()
            annual.append(dict(year=year,scope=scope,ktCO2=valid.sum() if len(valid) else np.nan,
                months=len(valid),full_year=len(valid)==12,first_month=valid.index.min(),last_month=valid.index.max(),
                nowcast_months=int(status_by_date.reindex(valid.index).gt(0).sum()),
                yoy_same_months_pct=(valid.sum()/prior.sum()-1)*100 if comparable and prior.sum()>0 else np.nan))
    m=pd.DataFrame(records)
    m['yoy_pct']=m.groupby('scope').ktCO2.transform(lambda x:x.pct_change(12,fill_method=None)*100)
    m.to_csv(out/'hong_kong_total_monthly.csv',index=False)
    pd.DataFrame(annual).to_csv(out/'hong_kong_total_annual.csv',index=False)
    (out/'provenance/point_estimate_manifest.json').write_text(json.dumps(dict(
        as_of=config['as_of'],industry_sources=sources,sector_methods=selections,
        official_baseline=baseline_config,
        near_realtime=realtime,
        baseline_calibration_sha256=hashlib.sha256((out/'diagnostics/official_baseline_calibration.csv').read_bytes()).hexdigest(),
        calibration_sources=baseline.reset_index().to_dict(orient='records'),
        transport_method=config['transport_proxy'],
        transport_manifest_sha256=hashlib.sha256((out/'transport_extension/monthly_manifest.json').read_bytes()).hexdigest(),
        industry_method='EMSD annual town gas/LPG + oil/coal energy, excluding electricity; common 2021 CRT CO2 per TJ scale. Monthly gas/electricity allocation; latest fuel/activity ratio after annual coverage.',
        historical_road_proxy=dict(path='data/raw/legacy/HK.xlsx',sha256=hashlib.sha256((root/'data/raw/legacy/HK.xlsx').read_bytes()).hexdigest(),
            coverage='2005-2012',scope='Monthly oil demand, not road fuel measured consumption'),
        limitation='Industrial annual non-electric fuel constraint; fixed 2021 aggregate CO2/TJ coefficient. Before 2013 annual rather than quarterly fuel benchmarks and road demand proxies. Combustion only, covered sectors only.'),indent=2))
    return frame,m,pd.DataFrame(annual)

if __name__=='__main__':
    build_point_estimate()
