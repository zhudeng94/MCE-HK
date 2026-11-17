"""Road activity proxies and fuel-to-CO2 formulas; see docs/sectors.md."""
import json
import numpy as np
import pandas as pd
from cmhk.kernels import (MEASURED, BENCHMARK, MODELLED, allocate, constrained_months,
                          period_months, split_generation, forward_holdout)


def road_activities(ctx):
    # Fixed, pre-existing three-harbour-crossing panel. No changing detector count.
    traffic = pd.concat([pd.read_csv(ctx.raw / f'td_{n}.csv') for n in ['31a', '31b', '31c']])
    traffic['date'] = pd.to_datetime(traffic.YR_MTH.astype(str), format='%Y%m')
    traffic = traffic[traffic.date.dt.year.between(ctx.start, ctx.end)]
    classes = [1, 2, 3, 5, 15, 16]
    panel = traffic.groupby(['date', 'TUN_BRIDGE_CODE', 'VEHICLE_CLASS_CODE']).NO_VEHICLE.sum(min_count=1).unstack(['TUN_BRIDGE_CODE', 'VEHICLE_CLASS_CODE'])
    expected = pd.MultiIndex.from_product([['CHT', 'EHC', 'WHC'], classes])
    if not set(expected).issubset(panel.columns):
        raise ValueError('Traffic panel class columns changed')
    panel = panel[expected].dropna()
    counts = panel.T.groupby(level=1).sum().T
    vkt = pd.read_csv(ctx.clean/'annual_vkt.csv').set_index('year')
    year_counts = counts.sum(axis=1).groupby(counts.index.year).sum()
    calibration = vkt.annual_vkt / year_counts.reindex(vkt.index)
    diagnostic = vkt.join(year_counts.rename('panel_crossings'))
    diagnostic['km_per_panel_crossing'] = calibration
    diagnostic['vkt_yoy'] = diagnostic.annual_vkt.pct_change()
    diagnostic['panel_yoy'] = diagnostic.panel_crossings.pct_change()
    diagnostic.to_csv(ctx.out/'diagnostics/road_vkt_diagnostics.csv')
    multipliers = pd.Series([calibration.loc[min(date.year,int(calibration.index.max()))]
                             for date in counts.index],index=counts.index)
    reg = pd.read_csv(ctx.raw / 'td_44.csv')
    reg['date'] = pd.to_datetime(reg.YR_MTH.astype(str), format='%Y%m')
    mapping = {1:1, 2:2, 3:3, 5:5, 9:15, 10:15, 4:16, 11:16, 12:16}
    reg = reg[reg.VEHICLE_CLASS_CODE.isin(mapping)].copy()
    reg['class'] = reg.VEHICLE_CLASS_CODE.map(mapping)
    registered = reg.groupby(['date', 'class', 'FUEL_TYPE_CODE']).NO_LIC.sum().unstack('FUEL_TYPE_CODE').fillna(0)
    outputs, raw_outputs = {}, {}
    for ev_ratio in ctx.config['road_ev_relative_mileage']:
        indices = {}
        for fuel, name in [('PETROL','petrol'), ('DIESEL','diesel'), ('LPGAS','lpg')]:
            parts = []
            for cls in classes:
                r = registered.xs(cls, level='class')
                denominator = r.sum(axis=1) + (ev_ratio-1) * r.ELECTRIC
                fraction = r[fuel] / denominator
                parts.append(counts[cls] * fraction.reindex(counts.index) * ctx.config['road_assumed_litres_per_km'][str(cls)])
            indices[name] = pd.concat(parts, axis=1).sum(axis=1, min_count=len(parts))
        raw_outputs[f'ev_mileage_{ev_ratio:g}'] = pd.DataFrame(indices).dropna()
        outputs[f'ev_mileage_{ev_ratio:g}'] = raw_outputs[f'ev_mileage_{ev_ratio:g}'].mul(multipliers,axis=0).dropna()
    pd.concat(outputs, names=['scenario','date']).to_csv(ctx.clean / 'road_activity.csv')
    return outputs, raw_outputs


def road(ctx):
    activities, raw_activities = road_activities(ctx)
    annual = ctx.emsd(6)
    passenger, freight = ctx.emsd(59), ctx.emsd(58)
    sales = ctx.load('915-91106')
    sales = sales[(sales.freq == 'Y') & (sales.PROD_TYPE == 'E_2b') & (sales.SALES_TYPEDesc == 'Sales for local consumption')]
    petrol = pd.Series([ctx.volume_tj(r.figure, 'petrol', r.svDesc) for _, r in sales.iterrows()], index=sales.period.astype(int))
    # The public EMSD table has grouped fuels, not the road-by-fuel cross-tab.
    # Experimental decomposition: marine entirely liquid fuel, gas entirely road LPG.
    marine_energy = passenger['Marine (Unit : Terajoule)'] + freight['Marine (Unit : Terajoule)']
    road_liquid = annual.iloc[:,2] - marine_energy
    diesel = road_liquid - petrol.reindex(annual.index)
    if (diesel.dropna() < 0).any():
        raise ValueError('Road fuel reconciliation gives negative diesel')
    benchmarks = pd.DataFrame({'petrol': petrol.reindex(annual.index), 'diesel': diesel, 'lpg': annual.iloc[:,0],
                               'marine_subtracted_TJ': marine_energy, 'road_liquid_TJ': road_liquid})
    benchmarks.loc[ctx.start:ctx.end].to_csv(ctx.out / 'diagnostics/road_inferred_benchmarks.csv', index_label='year')
    for scenario, index in activities.items():
        history=pd.read_csv(ctx.clean/'historical_road_activity.csv',parse_dates=['date']).set_index('date')
        index=pd.concat([history,index]).sort_index()
        for fuel in ['petrol','diesel','lpg']:
            ctx.yearly_component(benchmarks[fuel].loc[ctx.start:], index[fuel], 'Road', fuel, scenario,
                             ctx.factor(fuel, gross=(fuel == 'lpg')), 'EMSD 2026 tables 06/58/59; C&SD local petrol; TD 31a/b/c+44',
                             note='Experimental annual fuel split; tunnel mix scaled to aggregate annual VKT, not observed fuel-specific VKT. Road scope approximate.', label=MODELLED)
        qsales = ctx.load('915-91106')
        qsales = qsales[(qsales.freq == 'Q') & (qsales.PROD_TYPE == 'E_2b') & (qsales.SALES_TYPEDesc == 'Sales for local consumption')]
        target = pd.Series(qsales.figure.to_numpy(), index=pd.PeriodIndex(pd.to_datetime(qsales.period,format='%Y%m'),freq='Q'))
        # Same-year annual VKT was not available during each target quarter.
        # Use the uncalibrated monthly panel for this forward fuel test.
        raw = raw_activities[scenario]
        qa = raw.petrol.groupby(raw.index.to_period('Q')).agg(['sum','count'])
        v = forward_holdout(target, qa['sum'].where(qa['count']==3), min_training=4)
        if not v.empty:
            v['sector'], v['scenario'], v['unit'] = 'Road',scenario,'kL local petrol (scope imperfect)'
            ctx.validation.append(v)
    ctx.gap('Road', 'Public EMSD tables do not supply road-by-fuel totals. Experimental split assumes transport gas is road LPG, local marine energy is liquid fuel, local petrol sales are road petrol; diesel is the residual. Rail electricity is excluded implicitly by using only gas/oil categories.')
    ctx.gap('Road', 'Aggregate annual VKT is integrated; fuel/class-specific VKT and representative network weights remain unavailable. Three fixed harbour crossings are an unvalidated timing proxy. Post-2024 VKT/panel conversion is held fixed; no weekly detector estimates.')


