"""Component/scenario outputs and conservation checks."""
import json
import numpy as np
import pandas as pd
from cmhk.kernels import (MEASURED, BENCHMARK, MODELLED, allocate, constrained_months,
                          period_months, split_generation, forward_holdout)


def summarize(ctx):
    result = pd.DataFrame(ctx.rows).sort_values(['sector','scenario','date','fuel'])
    if result.duplicated(['date','sector','fuel','scenario']).any():
        raise ValueError('Duplicate emission components')
    result.to_csv(ctx.out / 'diagnostics/monthly_components.csv', index=False)
    keys = ['date','sector','scenario']
    total = result.groupby(keys).agg(available_components_ktCO2=('ktCO2','sum'),
            sector_complete=('sector_complete','all'), components=('fuel','nunique')).reset_index()
    # Require the same component set for each scenario. No treating missing as zero.
    expected = result.groupby(['sector','scenario']).fuel.nunique()
    expected_count = [expected.loc[(r.sector,r.scenario)] for r in total.itertuples()]
    total['model_components_complete'] = total.components == expected_count
    total['sector_complete'] &= total.model_components_complete
    total['comparable_components_ktCO2'] = total.available_components_ktCO2.where(total.model_components_complete)
    ranks = {MEASURED:0, BENCHMARK:1, MODELLED:2}
    label = result.assign(rank=result.estimate_label.map(ranks)).groupby(keys)['rank'].max().map({v:k for k,v in ranks.items()})
    total['estimate_label'] = total.set_index(keys).index.map(label)
    total['ktCO2'] = total.available_components_ktCO2.where(total.sector_complete)
    total.to_csv(ctx.out / 'diagnostics/monthly_scenarios.csv', index=False)
    bands = total.groupby(['date','sector']).agg(ktCO2_min=('ktCO2','min'),ktCO2_max=('ktCO2','max'),
                 available_components_min=('comparable_components_ktCO2','min'),
                 available_components_max=('comparable_components_ktCO2','max'),
                 scenarios=('scenario','nunique'), comparable_scenarios=('comparable_components_ktCO2','count'),
                 complete_scenarios=('ktCO2','count')).reset_index()
    grid = pd.MultiIndex.from_product([ctx.dates, ['Power','Industry','Road','Residential','Commercial',
                  'International Aviation','International Shipping']], names=['date','sector']).to_frame(index=False)
    grid = grid.merge(bands,on=['date','sector'],how='left')
    labels = total.groupby(['date','sector']).estimate_label.agg(lambda x: max(x,key=lambda v:ranks[v]))
    grid['estimate_label'] = grid.set_index(['date','sector']).index.map(labels)
    grid['status'] = np.where(grid.ktCO2_min.notna(), 'estimated',
                            np.where(grid.available_components_min.notna(), 'partial_components_only','no_estimate'))
    grid['range_meaning'] = 'scenario range, not a confidence interval'
    grid['method_status'] = grid.sector.map({'Power':'experimental_fuel_mix','Road':'experimental_fuel_split',
        'Industry':'assumed_lpg_and_unresolved_scope','Residential':'residual_fuel_assumptions','Commercial':'residual_fuel_assumptions',
        'International Aviation':'method_baseline','International Shipping':'method_baseline_with_sensitivity'})
    grid['as_of'] = ctx.config['as_of']
    grid.to_csv(ctx.out / 'diagnostics/monthly_2019_2026.csv', index=False)
    total['year'] = total.date.dt.year
    yearly = total.groupby(['year','sector','scenario']).agg(ktCO2=('ktCO2',lambda x:x.sum(min_count=1)),
                     months=('ktCO2','count'), component_months=('comparable_components_ktCO2','count'),
                     available_components_ktCO2=('comparable_components_ktCO2',lambda x:x.sum(min_count=1))).reset_index()
    yearly['full_year'] = yearly.months == 12
    yearly.to_csv(ctx.out / 'diagnostics/annual_scenarios.csv', index=False)
    pd.DataFrame(ctx.checks).to_csv(ctx.out / 'diagnostics/consistency_checks.csv', index=False)
    pd.DataFrame(ctx.gaps).drop_duplicates().to_csv(ctx.out / 'diagnostics/data_gaps.csv', index=False)
    if ctx.validation:
        pd.concat(ctx.validation,ignore_index=True).to_csv(ctx.out / 'diagnostics/holdout_predictions.csv', index=False)
    # Residual rounding in published quarterly supply identity is an observational diagnostic.
    c = pd.DataFrame(ctx.checks)
    hard = c[~c['check'].str.contains('supply_identity')]
    if not hard.passed.all():
        raise ValueError('A mass-balance constraint failed')
    print(grid.groupby(['sector','status']).size().to_string())
    print(f'{len(result)} component rows; {len(hard)} exact constraints passed.')


