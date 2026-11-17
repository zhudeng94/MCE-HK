"""Aggregate aligned Monte Carlo draws, retaining temporal/fuel dependence."""
import numpy as np
import pandas as pd
from cmhk.aggregation import SCOPES, sum_complete


def interval(draws):
    lower, median, upper = np.quantile(draws, [.025, .5, .975], axis=-1)
    return dict(lower_95_ktCO2=lower, median_ktCO2=median, upper_95_ktCO2=upper)


class JointTotals:
    def __init__(self, points, n):
        self.points = points.pivot(index='date', columns='sector', values='ktCO2').sort_index()
        self.dates = pd.DatetimeIndex(self.points.index)
        self.draws = {scope: np.zeros((len(self.dates), n)) for scope in SCOPES}
        self.seen = set()
        self.sector_annual = []

    def add(self, sector, dates, draws):
        if sector in self.seen:
            raise ValueError('Duplicate sector draws')
        positions = self.dates.get_indexer(dates)
        if (positions < 0).any() or len(positions) != len(draws):
            raise ValueError('Draw dates do not match the output calendar')
        self.seen.add(sector)
        for scope, sectors in SCOPES.items():
            if sector in sectors:
                self.draws[scope][positions] += draws
        for year in np.unique(dates.year):
            mask = dates.year == year
            self.sector_annual.append(dict(year=int(year), sector=sector, months=int(mask.sum()),
                full_year=bool(mask.sum() == 12), ktCO2=self.points.loc[dates[mask], sector].sum(),
                **interval(draws[mask].sum(axis=0))))

    def summarize(self):
        if self.seen != set(self.points.columns):
            raise ValueError('Missing sector draws')
        monthly, annual, changes = [], [], []
        for scope, sectors in SCOPES.items():
            point = sum_complete(self.points[sectors])
            valid = point.notna().to_numpy()
            frame = pd.DataFrame({'date':self.dates, 'scope':scope, 'ktCO2':point.to_numpy()})
            for column, values in interval(self.draws[scope][valid]).items():
                frame[column] = np.nan
                frame.loc[valid, column] = values
            monthly.append(frame)
            for year in np.unique(self.dates.year):
                positions = np.flatnonzero(valid & (self.dates.year == year))
                months = self.dates[positions]
                row = dict(year=int(year), scope=scope, months=len(months), full_year=len(months)==12,
                           ktCO2=point.iloc[positions].sum() if len(months) else np.nan)
                if len(months):
                    values = self.draws[scope][positions].sum(axis=0)
                    row.update(interval(values))
                    previous = self.dates.get_indexer(months-pd.DateOffset(years=1))
                    if (previous >= 0).all() and valid[previous].all():
                        # Subtract matched trajectories before taking quantiles.
                        difference = values-self.draws[scope][previous].sum(axis=0)
                        changes.append(dict(year=int(year), scope=scope, months=len(months),
                            full_year=len(months)==12, compared_months=','.join(map(str, months.month)),
                            ktCO2=row['ktCO2']-point.iloc[previous].sum(), **interval(difference)))
                annual.append(row)
        frames = dict(total_monthly_uncertainty=pd.concat(monthly, ignore_index=True),
                      total_annual_uncertainty=pd.DataFrame(annual),
                      annual_change_uncertainty=pd.DataFrame(changes),
                      sector_annual_uncertainty=pd.DataFrame(self.sector_annual))
        for frame in frames.values():
            frame['coverage_probability'] = .95
        return frames
