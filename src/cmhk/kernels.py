"""Numerical kernels. Quantities must have explicit, consistent units upstream."""
import numpy as np
import pandas as pd
from scipy.optimize import brentq

MEASURED = 'Measured-energy estimate'
BENCHMARK = 'Benchmark-constrained estimate'
MODELLED = 'Modelled estimate'

def allocate(total, weights):
    """Allocate a known total, refusing missing or invalid weights (including zeros)."""
    w = pd.Series(weights, dtype=float)
    if not np.isfinite(total) or total < 0:
        raise ValueError('Total must be finite and nonnegative')
    if w.empty or not np.isfinite(w).all() or (w < 0).any() or w.sum() <= 0:
        raise ValueError('Weights must be complete, nonnegative and have positive sum')
    return w / w.sum() * total

def period_months(period, freq):
    p = pd.Period(str(period), freq=freq)
    return pd.date_range(p.start_time, p.end_time, freq='MS')

def constrained_months(total, weights, period, freq):
    """Never allocate a full-year/quarter benchmark to a partial set of months."""
    return allocate(total, weights.reindex(period_months(period, freq)))

def split_generation(generation, gas_total, responsiveness=0.0):
    """Positive dispatch matching every month's generation and annual gas generation.

    Gas shares respond to daily demand on the log-odds scale. Intercept is solved,
    so changing responsiveness cannot change annual gas/coal totals.
    """
    g = pd.Series(generation, dtype=float)
    if not np.isfinite(g).all() or (g <= 0).any() or not 0 <= gas_total <= g.sum():
        raise ValueError('Invalid generation margins')
    if gas_total == 0:
        return g * 0, g.copy()
    if np.isclose(gas_total, g.sum()):
        return g.copy(), g * 0
    daily = g / g.index.days_in_month
    covariate = np.log(daily / daily.mean()) * responsiveness
    def share(intercept):
        return 1 / (1 + np.exp(-(intercept + covariate)))
    intercept = brentq(lambda a: float((g * share(a)).sum() - gas_total), -50, 50)
    gas = g * share(intercept)
    return gas, g - gas

def forward_holdout(benchmarks, activity, min_training=2):
    """Predict each benchmark from PRIOR periods only; no target-total rescaling.

    A hindcast using today's revised historical data, not a real-time vintage test.
    """
    d = pd.concat([benchmarks.rename('observed'), activity.rename('activity')], axis=1).dropna().sort_index()
    result = []
    for i in range(min_training, len(d)):
        train, target = d.iloc[:i], d.iloc[i]
        if train.activity.sum() <= 0 or target.activity <= 0:
            continue
        prediction = train.observed.sum() / train.activity.sum() * target.activity
        result.append(dict(period=str(d.index[i]), observed=target.observed, predicted=prediction,
                           error=prediction-target.observed,
                           relative_error=(prediction/target.observed-1) if target.observed else np.nan,
                           training_through=str(d.index[i-1])))
    return pd.DataFrame(result)
