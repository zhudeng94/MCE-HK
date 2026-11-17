"""Industrial fuel benchmarks and conservative monthly allocation."""
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from cmhk.paths import ROOT, code_hashes
from cmhk.benchmarks.official import crt_benchmarks
from cmhk.kernels import MODELLED
FUEL_COLUMNS = {
    'Town Gas & Liquefied Petroleum Gas (Unit : Terajoule)': 'gas_lpg_TJ',
    'Oil & Coal Products (Unit : Terajoule)': 'oil_coal_TJ',
    'Electricity (Unit : Terajoule)': 'electricity_excluded_TJ',
}


def annual_fuel(root=ROOT):
    config = json.loads((root/'configs/model.json').read_text())
    frames, sources = [], []
    for edition, table in sorted(config['industry']['annual_sources'].items()):
        path = root/f'data/raw/emsd_{edition}_{table:02}.csv'
        checksum = hashlib.sha256(path.read_bytes()).hexdigest()
        meta = json.loads(path.with_suffix('.csv.source.json').read_text())
        if checksum != meta['sha256']:
            raise ValueError(f'Industrial source checksum mismatch: {path}')
        d = pd.read_csv(path).rename(columns=FUEL_COLUMNS)
        d = d[['Year', *FUEL_COLUMNS.values()]].rename(columns={'Year':'year'})
        for col in FUEL_COLUMNS.values():
            d[col] = pd.to_numeric(d[col].astype(str).str.replace(',', '', regex=False), errors='raise')
        if d[list(FUEL_COLUMNS.values())].isna().any().any() or (d[list(FUEL_COLUMNS.values())] < 0).any().any():
            raise ValueError('Industrial annual energy must be complete and nonnegative')
        d['source_edition'], d['source_table'] = int(edition), table
        d['source_path'], d['source_sha256'] = str(path.relative_to(root)), checksum
        frames.append(d)
        sources.append(dict(edition=int(edition),table=table,path=str(path.relative_to(root)),**meta))
    all_rows = pd.concat(frames, ignore_index=True)
    annual = all_rows.drop_duplicates('year', keep='last').set_index('year').sort_index()
    annual = annual.loc[config['start_year']:]
    if list(annual.index) != list(range(config['start_year'], int(annual.index.max())+1)):
        raise ValueError('Industrial annual fuel coverage has gaps')
    annual['fuel_TJ'] = annual.gas_lpg_TJ + annual.oil_coal_TJ
    out = root/'data/processed'
    out.mkdir(parents=True, exist_ok=True)
    all_rows.to_csv(out/'industry_fuel_source_versions.csv', index=False)
    annual.to_csv(out/'industry_annual_fuel.csv')
    return annual, sources


def monthly_fuel(annual, activity, start_year, as_of):
    """Preserve each observed annual fuel group; extrapolate only beyond coverage."""
    if activity.index.has_duplicates:
        raise ValueError('Duplicate industrial activity months')
    activity = activity.loc[f'{start_year}-01-01':].copy()
    activity = activity.loc[activity.index + pd.offsets.MonthEnd() <= pd.Timestamp(as_of)]
    last = int(annual.index.max())
    records = []
    groups = [('gaseous_fuels','gas_lpg_TJ','GASC_LOCAL'),
              ('liquid_and_solid_fuels','oil_coal_TJ','ELEC_LOCAL')]
    for year, block in activity.groupby(activity.index.year):
        for component, fuel, proxy in groups:
            weights = block[proxy]
            if year <= last:
                if year not in annual.index:
                    raise ValueError(f'Missing industrial annual energy: {year}')
                expected = pd.date_range(f'{year}-01-01', periods=12, freq='MS')
                full = weights.reindex(expected)
                if full.isna().any() or not np.isfinite(full).all() or (full < 0).any() or full.sum() <= 0:
                    continue
                energy = annual.loc[year,fuel]*full/full.sum()
                status, ref = 'annual_fuel_constrained', year
            else:
                reference = activity[proxy].reindex(pd.date_range(f'{last}-01-01', periods=12, freq='MS'))
                if reference.isna().any() or reference.sum() <= 0:
                    raise ValueError('Incomplete industrial extrapolation reference')
                energy = weights.where(np.isfinite(weights) & weights.ge(0))*annual.loc[last,fuel]/reference.sum()
                status, ref = 'fuel_activity_extrapolated', last
            for date, value in energy.items():
                records.append(dict(date=date,component=component,fuel_TJ=value,proxy=proxy,
                    proxy_TJ=activity.loc[date,proxy],reference_year=ref,temporal_status=status))
    return pd.DataFrame(records)


def industrial_estimate(root=ROOT):
    """Annual non-electric energy, monthly activity shares, one 2021 CO2 scale."""
    config=json.loads((root/'configs/model.json').read_text())
    annual,sources=annual_fuel(root)
    d=pd.read_csv(root/'data/processed/csd_915-91201.csv',dtype={'period':str})
    d=d[(d.freq=='M') & (d.USER_TYPEDesc=='Industrial')].copy()
    d['date']=pd.to_datetime(d.period,format='%Y%m')
    activity=d.pivot(index='date',columns='sv',values='figure')
    components=monthly_fuel(annual,activity,config['start_year'],config['as_of'])
    ref=crt_benchmarks(root,years=(2021,)).query("sector == 'Industry'").iloc[0]
    coefficient=ref.official_ktCO2/annual.loc[2021,'fuel_TJ']
    components['coefficient']=coefficient
    components['ktCO2']=components.fuel_TJ*coefficient
    components['sector']='Industry'
    components['anchor_year']=2021
    components['estimate_label']=MODELLED
    total=components.pivot(index='date',columns='component',values='ktCO2').sum(axis=1,min_count=2)
    if not np.isclose(total.loc['2021'].sum(),ref.official_ktCO2):
        raise ValueError('Industrial baseline calibration failed')
    annual['model_ktCO2']=annual.fuel_TJ*coefficient
    anchor=pd.DataFrame([dict(year=2021,total_ktCO2=ref.official_ktCO2,
        fuel_TJ=annual.loc[2021,'fuel_TJ'],coefficient=coefficient)])
    out=root/'outputs'
    (out/'diagnostics').mkdir(parents=True,exist_ok=True)
    components.to_csv(out/'diagnostics/industry_proxy_components.csv',index=False)
    annual.to_csv(out/'diagnostics/industry_annual_fuel.csv')
    anchor.to_csv(out/'diagnostics/industry_proxy_calibration.csv',index=False)
    sources.append(dict(year=2021,path=ref.source,sheet=ref.sheet,cell=ref.cell,sha256=ref.sha256))
    return total,sources

