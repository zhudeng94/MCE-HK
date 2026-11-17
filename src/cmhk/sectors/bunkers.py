"""Bunkers activity proxies and fuel-to-CO2 formulas; see docs/sectors.md."""
import json
import numpy as np
import pandas as pd
from cmhk.kernels import (MEASURED, BENCHMARK, MODELLED, allocate, constrained_months,
                          period_months, split_generation, forward_holdout)


def bunkers(ctx):
    d = ctx.load('915-91106')
    a = pd.read_csv(ctx.clean / 'airport.csv', parse_dates=['date']).set_index('date').movements
    marine = pd.read_csv(ctx.clean / 'marine.csv', parse_dates=['date'])
    arrivals = marine.pivot(index='date', columns='kind', values='arrivals')
    nt = marine.groupby('date').net_tonnage_thousand.sum(min_count=2)
    activities = {'International Aviation': {'movements': a},
                  'International Shipping': {'all_arrivals': arrivals.sum(axis=1, min_count=2),
                                             'ocean_arrivals': arrivals.Ocean, 'net_tonnage': nt}}
    fuels = {'E_1': 'jet_kerosene', 'E_2b': 'petrol', 'E_3': 'diesel', 'E_4': 'fuel_oil', 'E_5': 'jet_kerosene', 'E_6': 'lpg'}
    for sector, user in [('International Aviation', 'Aircraft stores'), ('International Shipping', 'Ship stores')]:
        sub = d[(d.freq == 'Q') & (d.SALES_TYPEDesc == user)].copy()
        sub['quarter'] = pd.to_datetime(sub.period, format='%Y%m').dt.to_period('Q')
        for scenario, activity in activities[sector].items():
            historical=d[(d.freq=='Y')&(d.SALES_TYPEDesc==user)&(d.period.astype(int)<2013)]
            for _,row in historical.iterrows():
                fuel=fuels[row.PROD_TYPE]
                tj=ctx.volume_tj(row.figure,fuel,row.svDesc)
                monthly=constrained_months(tj,activity,row.period,'Y')
                ctx.check(f'{sector}/{scenario}/{row.PROD_TYPE}/historical_annual',row.period,tj,monthly.sum(),'TJ')
                ctx.add(monthly*ctx.factor(fuel),sector,row.PROD_TYPE+'_'+fuel,scenario,BENCHMARK,
                    f'{row.source} page {row.pdf_page}; annual activity allocation',row.period,
                    note='Historical annual fuel benchmark, not quarterly fuel observations; supplied fuel boundary')
            for _, row in sub.iterrows():
                if pd.isna(row.figure):
                    continue
                fuel = fuels[row.PROD_TYPE]
                tj = ctx.volume_tj(row.figure, fuel, row.svDesc)
                try:
                    monthly = constrained_months(tj, activity, row.quarter, 'Q')
                except ValueError:
                    ctx.gap(sector, f'{scenario}/{row.quarter}: missing month(s), quarterly fuel not allocated')
                    continue
                ctx.check(f'{sector}/{scenario}/{row.PROD_TYPE}', row.quarter, tj, monthly.sum(), 'TJ')
                ctx.add(monthly * ctx.factor(fuel), sector, row.PROD_TYPE + '_' + fuel, scenario, BENCHMARK,
                    f'C&SD 915-91106 + {"HKIA" if sector.endswith("Aviation") else "Marine Department"}', row.quarter,
                    note='Fuel supplied in HK; not territorial emissions. Default densities. Activity estimates sale timing. '+str(row.derivation))
            # Quarterly target withheld; conversion is irrelevant to fuel sales/activity test.
            primary = 'E_1' if sector.endswith('Aviation') else 'E_4'
            target = sub[sub.PROD_TYPE == primary].set_index('quarter').figure
            qa = activity.groupby(activity.index.to_period('Q')).agg(['sum', 'count'])
            v = forward_holdout(target, qa['sum'].where(qa['count'] == 3), min_training=4)
            if not v.empty:
                v['sector'], v['scenario'], v['unit'] = sector, scenario, 'kL '+primary
                ctx.validation.append(v)
    ctx.gap('International Aviation', 'No weekly estimate: historical daily flights not obtained; published monthly HKIA counts are rounded to 1,000.')
    ctx.gap('International Shipping', 'No calibrated vessel-class fuel-demand or AIS model. Arrival/ocean/tonnage alternatives are sensitivity scenarios, not measured bunker delivery timing.')


