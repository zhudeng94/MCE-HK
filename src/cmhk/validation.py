"""Data-driven release checks; no frozen latest-month or historical-value assertions."""
import argparse
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd

from cmhk.paths import ROOT
from cmhk.aggregation import SCOPES


def validate(root, previous=None):
    config=json.loads((root/'configs/model.json').read_text())
    sectors=pd.read_csv(root/'outputs/hong_kong_sector_monthly.csv',parse_dates=['date'])
    totals=pd.read_csv(root/'outputs/hong_kong_total_monthly.csv',parse_dates=['date'])
    annual=pd.read_csv(root/'outputs/hong_kong_total_annual.csv')
    assert not sectors.duplicated(['date','sector']).any()
    assert not totals.duplicated(['date','scope']).any()
    assert sectors.ktCO2.dropna().ge(0).all() and np.isfinite(sectors.ktCO2.dropna()).all()
    future=sectors.date+pd.offsets.MonthEnd()>pd.Timestamp(config['as_of'])
    assert sectors.loc[future,'ktCO2'].isna().all(),'Future/incomplete months were filled'
    frame=sectors.pivot(index='date',columns='sector',values='ktCO2')
    latest={}
    for scope,names in SCOPES.items():
        actual=totals[totals.scope.eq(scope)].set_index('date').sort_index()
        expected=frame[names].sum(axis=1,min_count=len(names)).reindex(actual.index)
        np.testing.assert_allclose(expected,actual.ktCO2,equal_nan=True)
        assert actual.complete.equals(expected.notna())
        prior=actual.ktCO2.reindex(actual.index-pd.DateOffset(years=1)).to_numpy()
        with np.errstate(divide='ignore',invalid='ignore'):
            expected_yoy=(actual.ktCO2.to_numpy()/prior-1)*100
        np.testing.assert_allclose(expected_yoy,actual.yoy_pct,equal_nan=True)
        latest[scope]=actual.ktCO2.dropna().index.max().strftime('%Y-%m-%d')
        for row in annual[annual.scope.eq(scope)].itertuples():
            block=actual[actual.index.year==row.year].ktCO2.dropna()
            assert row.months==len(block) and row.full_year==(len(block)==12)
            if block.empty:
                assert pd.isna(row.ktCO2)
                continue
            assert np.isclose(block.sum(),row.ktCO2)
            prior=actual.ktCO2.reindex(block.index-pd.DateOffset(years=1))
            expected=(block.sum()/prior.sum()-1)*100 if prior.notna().all() and prior.sum()>0 else np.nan
            np.testing.assert_allclose(expected,row.yoy_same_months_pct,equal_nan=True)
    for file,keys,main in [('sector_monthly_uncertainty.csv',['date','sector'],sectors),('total_monthly_uncertainty.csv',['date','scope'],totals)]:
        bands=pd.read_csv(root/'outputs/uncertainty'/file,parse_dates=['date']).set_index(keys).sort_index()
        values=main.set_index(keys).sort_index().ktCO2
        pd.testing.assert_index_equal(values.index,bands.index)
        np.testing.assert_allclose(values,bands.ktCO2,equal_nan=True)
        assert values.isna().equals(bands.lower_95_ktCO2.isna())
        assert values.isna().equals(bands.upper_95_ktCO2.isna())
        valid=bands.dropna(subset=['ktCO2'])
        assert np.isfinite(valid[['lower_95_ktCO2','upper_95_ktCO2']]).all().all()
        assert valid.lower_95_ktCO2.le(valid.upper_95_ktCO2).all()
    for path in ['diagnostics/consistency_checks.csv','uncertainty/checks.csv','transport_extension/monthly_conservation_checks.csv']:
        checks=pd.read_csv(root/'outputs'/path)
        assert not checks.empty and checks.passed.all(),path
    changes_path = root/'outputs/figures/annual_sector_change_contributions.csv'
    if changes_path.exists():
        changes = pd.read_csv(changes_path)
        for _,block in changes.groupby(['year','scope']):
            assert np.isclose(block.change_MtCO2.sum(),block.net_change_MtCO2.iloc[0])
    if previous:
        old=pd.read_csv(previous/'outputs/hong_kong_sector_monthly.csv').set_index(['date','sector']).ktCO2.dropna()
        new=sectors.assign(date=sectors.date.dt.strftime('%Y-%m-%d')).set_index(['date','sector']).ktCO2
        assert new.reindex(old.index).notna().all(),'Previously published observations disappeared'
    return {'latest_complete_months':latest,'sector_rows':len(sectors),'checks':'passed'}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--previous',type=Path)
    args=parser.parse_args()
    print(json.dumps(validate(ROOT,args.previous),indent=2))
