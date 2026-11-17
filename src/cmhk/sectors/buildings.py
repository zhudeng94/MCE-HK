"""Buildings activity proxies and fuel-to-CO2 formulas; see docs/sectors.md."""
import json
import numpy as np
import pandas as pd
from cmhk.kernels import (MEASURED, BENCHMARK, MODELLED, allocate, constrained_months,
                          period_months, split_generation, forward_holdout)


def observed_gas(ctx):
    d = ctx.load('915-91201')
    d = d[(d.freq == 'M') & (d.sv == 'GASC_LOCAL')]
    d['date'] = pd.to_datetime(d.period, format='%Y%m')
    return d.pivot(index='date', columns='USER_TYPEDesc', values='figure').rename(
        columns={'Domestic': 'Residential', 'Industrial': 'Industry'})


def stationary(ctx, gas):
    tg_ef = ctx.config['town_gas_kg_co2_per_48_mj'] / 48
    shares = []
    for sector, table in [('Residential', 3), ('Commercial', 4)]:
        annual = ctx.emsd(table)
        gas_sum = gas[sector].resample('YS').sum(min_count=12)
        gas_sum.index = gas_sum.index.year
        combined = annual.iloc[:, 0]
        oil = annual.iloc[:, 2]
        residual = combined - gas_sum.reindex(combined.index)
        # A negative residual is a scope conflict, not zero LPG consumption.
        negative = residual.loc[ctx.start:].lt(0)
        for year in residual.loc[ctx.start:].index:
            observed = gas_sum.get(year, np.nan)
            shares.append(dict(sector=sector, year=year, observed_town_gas_TJ=observed,
                               emsd_combined_gas_TJ=combined.loc[year], residual_TJ=residual.loc[year],
                               emsd_oil_coal_TJ=oil.loc[year],
                               observed_gas_share_of_combustion=observed/(combined.loc[year]+oil.loc[year]),
                               compatible=bool(residual.loc[year] >= 0)))
        if negative.any():
            raise ValueError(f'{sector}: combined gas is below observed town gas; cannot infer LPG')
        if oil.loc[ctx.start:].isna().any():
            ctx.gap(sector, 'EMSD residential oil/coal CSV has blanks (PDF dash) from 2022 and rounds <1 TJ in 2021 to zero. Report residual fuel as a 0-1 TJ/year sensitivity, not observed zero.')
        profiles = {'gas_profile': gas[sector],
                    'flat_daily': pd.Series(ctx.dates.days_in_month, index=ctx.dates).where(ctx.dates <= gas.index.max())}
        scenarios = {name: (w, 'oil') for name, w in profiles.items()}
        if sector == 'Residential':
            scenarios = {f'{name}_trace_{trace}': (w, 'oil') for name,w in profiles.items() for trace in [0,1]}
        for scenario, (weights, mix) in scenarios.items():
            # Missing LPG invalidates total, but preserve real measured gas.
            ctx.add(gas[sector] * tg_ef, sector, 'town_gas', scenario, MEASURED, 'C&SD 915-91201; EPD CO2 factor',
                complete=True, note='End-user combustion only; manufacture excluded')
            ef = ctx.factor('coal' if mix == 'coal' else 'diesel')
            scenario_oil = oil.copy()
            if sector == 'Residential':
                trace = int(scenario.rsplit('_',1)[-1])
                scenario_oil.loc[scenario_oil.index >= 2021] = float(trace)
            ctx.yearly_component(scenario_oil, weights, sector, 'oil_coal_unsplit', scenario, ef,
                f'EMSD 2026 table {table:02}', complete=True,
                note=f'Aggregate oil/coal treated as {mix}; fuel composition is not observed', label=MODELLED)
            if not negative.any():
                ctx.yearly_component(residual.clip(lower=0), weights, sector, 'lpg_residual', scenario, ctx.factor('lpg', gross=True),
                    f'EMSD 2026 table {table:02} minus C&SD gas',
                    note='Residual assumed LPG, although EMSD also includes biogas; not a directly observed LPG series', label=MODELLED)
    pd.DataFrame(shares).to_csv(ctx.out / 'diagnostics/fuel_share_diagnostics.csv', index=False)


