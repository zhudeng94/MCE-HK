"""Per-run configuration, units, observations and consistency checks."""
import json
import numpy as np
import pandas as pd
from cmhk.kernels import (MEASURED, BENCHMARK, MODELLED, allocate, constrained_months,
                          period_months, split_generation, forward_holdout)
from cmhk.paths import ROOT


class EstimationContext:
    """Mutable records belong to one run; independent contexts share no results."""
    def __init__(self, root=ROOT, config=None):
        self.root = root
        self.raw, self.clean, self.out = [root / p for p in ['data/raw', 'data/processed', 'outputs']]
        self.config = json.loads((root / 'configs/model.json').read_text()) if config is None else config
        self.start, self.end = self.config['start_year'], self.config['end_year']
        self.as_of = pd.Timestamp(self.config['as_of'])
        self.dates = pd.date_range(f'{self.start}-01-01', f'{self.end}-12-01', freq='MS')
        self.rows, self.checks, self.gaps, self.validation = [], [], [], []

    def load(self, table):
        d = pd.read_csv(self.clean / f'csd_{table}.csv', dtype={'period': str})
        return d


    def scalar(self, d, **filters):
        for key, value in filters.items():
            d = d[d[key] == value]
        if len(d) != 1:
            raise ValueError(f'Expected one row, got {len(d)}: {filters}')
        return float(d.iloc[0].figure)


    def factor(self, fuel, gross=False):
        value = self.config['ipcc_t_co2_per_tj_ncv'][fuel] / 1000
        if gross:
            value *= self.config['lpg_ncv_gcv_ratio'] if fuel == 'lpg' else self.config['natural_gas_ncv_gcv_ratio']
        return value


    def volume_tj(self, volume, fuel, unit):
        if unit == 'Tonnes':
            mass = volume
        elif unit == 'Kilolitres':
            mass = volume * self.config['assumed_density_tonne_per_kl'][fuel]
        else:
            raise ValueError(f'Unsupported fuel unit: {unit}')
        return mass * self.config['ipcc_ncv_gj_per_tonne'][fuel] / 1000


    def add(self, series, sector, fuel, scenario, label, source, benchmark='', complete=True, note=''):
        for date, energy in series.items():
            if date not in self.dates or date + pd.offsets.MonthEnd() > self.as_of or not np.isfinite(energy):
                continue
            if energy < -1e-9:
                raise ValueError('Negative estimate')
            self.rows.append(dict(date=date, sector=sector, fuel=fuel, scenario=scenario, ktCO2=float(energy),
                             estimate_label=label, source=source, benchmark_period=str(benchmark),
                             sector_complete=complete, note=note))


    def check(self, name, period, expected, actual, unit, tolerance=1e-7):
        residual = actual - expected
        self.checks.append(dict(check=name, period=str(period), expected=expected, actual=actual,
                           residual=residual, unit=unit, tolerance=tolerance,
                           passed=bool(np.isclose(expected, actual, rtol=1e-9, atol=tolerance))))


    def gap(self, sector, description):
        self.gaps.append(dict(sector=sector, description=description))


    def emsd(self, table):
        # Most recent edition wins where years overlap. Tables must retain semantics.
        frames=[]
        old_table={3:48,4:49,6:51,58:45,59:46}.get(table)
        if old_table is not None:
            old=pd.read_csv(self.raw/f'emsd_2017_{old_table:02}.csv').set_index('Year')
            if table in [58,59]:
                # Early report groups non-road modes as Others. For historical road
                # subtraction retain the whole group, not a fabricated marine split.
                old=old.rename(columns={'Others (Unit : Terajoule)':'Marine (Unit : Terajoule)'})
            frames.append(old)
        for edition in [2020,2025,2026]:
            p=self.raw/f'emsd_{edition}_{table:02}.csv'
            if p.exists():
                frames.append(pd.read_csv(p).set_index('Year'))
        result=pd.concat(frames)
        result=result[~result.index.duplicated(keep='last')].sort_index()
        return result.apply(lambda s:pd.to_numeric(s.astype(str).str.replace(',','',regex=False),errors='coerce'))


    def yearly_component(self, annual, weights, sector, fuel, scenario, ef, source, complete=True, note='', label=BENCHMARK):
        """Conserve full observed years; extrapolate only months with observed activity."""
        annual = annual.dropna().sort_index()
        for year, total in annual.items():
            if not self.start <= year <= self.end:
                continue
            try:
                energy = constrained_months(total, weights, year, 'Y')
            except ValueError:
                self.gap(sector, f'{scenario}/{fuel}/{year}: incomplete activity; no annual allocation produced')
                continue
            self.check(f'{sector}/{scenario}/{fuel}', year, total, energy.sum(), 'TJ')
            self.add(energy * ef, sector, fuel, scenario, label, source, year, complete, note)
        if annual.empty:
            return
        last = int(annual.index[-1])
        base = weights.reindex(period_months(last, 'Y'))
        if base.isna().any() or base.sum() <= 0:
            return
        for year in range(last+1, self.end+1):
            activity = weights[weights.index.year == year].dropna()
            self.add(activity * (annual.loc[last] / base.sum()) * ef, sector, fuel, scenario, MODELLED,
                source, last, complete, note + f'; extrapolated using {last} fuel/activity ratio; no current annual fuel benchmark')


