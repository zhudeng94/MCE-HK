"""Power activity proxies and fuel-to-CO2 formulas; see docs/sectors.md."""
import json
import numpy as np
import pandas as pd
from cmhk.kernels import (MEASURED, BENCHMARK, MODELLED, allocate, constrained_months,
                          period_months, split_generation, forward_holdout)


def power(ctx):
    balance = ctx.load('915-91001')
    b = balance[(balance.sv == 'F_EN_REQ') & (balance.EN_REQ_TYPE == 'Elect_gen')]
    annual = b.pivot(index='period', columns='PROD_TYPE', values='figure')
    annual.index = annual.index.astype(int)
    q = ctx.load('915-91203')
    q = q[q.freq == 'Q'].copy()
    q['quarter'] = pd.to_datetime(q.period, format='%Y%m').dt.to_period('Q')
    q = q.pivot(index='quarter', columns='sv', values='figure')
    obs = ctx.load('915-91201')
    obs = obs[(obs.freq == 'M') & (obs.sv == 'ELEC_LOCAL') & (obs.USER_TYPEDesc == 'Total')]
    sales = pd.Series(obs.figure.to_numpy(), index=pd.to_datetime(obs.period, format='%Y%m'))
    generation = pd.Series(index=ctx.dates, dtype=float)
    for year,row in annual.iterrows():
        if year>=2013 or year<ctx.start:continue
        months=period_months(year,'Y')
        monthly=allocate(row.ELEC,sales.reindex(months))
        generation.loc[months]=monthly
        ctx.check('Power/historical_annual_generation',year,row.ELEC,monthly.sum(),'TJ electricity')
    for period, row in q.iterrows():
        months = period_months(period, 'Q')
        consumption = sales.reindex(months)
        if consumption.isna().any():
            continue
        day_weight = pd.Series(months.days_in_month, index=months, dtype=float)
        # Supply balance: generation = final use + own use/loss + export - import.
        adjustment = row.ELE_IND_OWN + row.ELE_EX_CHN - row.ELE_IM_CHN
        raw = consumption + allocate(abs(adjustment), day_weight) * np.sign(adjustment)
        if (raw <= 0).any():
            ctx.gap('Power', f'{period}: generation balance nonpositive, no allocation')
            continue
        monthly = allocate(row.ELE_GEN_LOCAL, raw)
        generation.loc[months] = monthly
        ctx.check('Power/quarterly_generation', period, row.ELE_GEN_LOCAL, monthly.sum(), 'TJ electricity')
        ctx.check('Power/quarterly_supply_identity', period, row.ELE_GEN_LOCAL,
              row.ELEC_LOCAL + adjustment, 'TJ electricity', tolerance=2.5)
    generation.rename('generation_TJ').to_csv(ctx.clean / 'power_generation.csv', index_label='date')
    last = int(annual.index.max())
    for year in range(ctx.start, ctx.end+1):
        g = generation[generation.index.year == year].dropna()
        if g.empty:
            continue
        anchor_year = min(year, last)
        if anchor_year not in annual.index:
            continue
        anchor = annual.loc[anchor_year]
        scale = 1.0 if year <= last else g.sum() / anchor.ELEC
        if year <= last and len(g) != 12:
            ctx.gap('Power', f'{year}: annual fuel available but generation months incomplete; withheld')
            continue
        coal_heat, pooled_heat = -anchor.COAL * scale, -anchor.OIL * scale
        for liquid_share in ctx.config['power_liquid_share_of_pooled_oil_gas_heat']:
            gas_heat, oil_heat = pooled_heat*(1-liquid_share), pooled_heat*liquid_share
            gas_output = gas_heat * ctx.config['natural_gas_ncv_gcv_ratio'] * ctx.config['power_assumed_efficiency']['gas']
            coal_output = (coal_heat+oil_heat) * ctx.config['power_assumed_efficiency']['coal']
            gas_total = g.sum() * gas_output / (gas_output+coal_output)
            for response in ctx.config['power_gas_responsiveness']:
                scenario = f'liquid_{liquid_share:g}_response_{response:g}'
                gas_g, coal_g = split_generation(g, gas_total, response)
                ctx.check(f'Power/{scenario}/gas_generation', year, gas_total, gas_g.sum(), 'TJ electricity')
                gas_e = gas_g/gas_g.sum() * gas_heat * ctx.factor('natural_gas', gross=True)
                coal_e = coal_g/coal_g.sum() * (coal_heat*ctx.factor('coal')+oil_heat*ctx.factor('fuel_oil'))
                note = 'Experimental fuel mix inferred from annual coal and pooled oil/gas heat; assumed efficiencies; renewable generation not separately resolved'
                if year > last:
                    note += f'; {last} heat/generation intensity carried forward, partial-year nowcast'
                for fuel, emissions in [('natural_gas_inferred',gas_e),('coal_oil_inferred',coal_e)]:
                    ctx.add(emissions, 'Power', fuel, scenario, MODELLED, 'C&SD 915-91001/91203/91201', anchor_year, note=note)
                ctx.check(f'Power/{scenario}/annual_fuel_emissions', year,
                      gas_heat*ctx.factor('natural_gas',gross=True)+coal_heat*ctx.factor('coal')+oil_heat*ctx.factor('fuel_oil'),
                      (gas_e+coal_e).sum(), 'ktCO2')
    ctx.gap('Power', 'HK Electric half-year fuel generation is cached but cannot be used as the entire Hong Kong fuel mix. Historical matching CLP fuel-specific generation is missing. This experimental model uses C&SD annual fuel-input groups and assumed efficiencies instead; pooled oil products include natural gas.')


