"""Single monthly publication product; detailed provenance remains in model outputs."""
from pathlib import Path
import hashlib,json
import numpy as np
import pandas as pd
from cmhk.paths import ROOT
OUT=ROOT/'outputs';DEST=OUT/'publication'
LOCAL=['Power','Industry','Road Transport','Domestic Navigation','Residential','Commercial']

def main():
    DEST.mkdir(exist_ok=True)
    inputs=['hong_kong_sector_monthly.csv','hong_kong_total_monthly.csv','uncertainty/sector_monthly_uncertainty.csv','uncertainty/total_monthly_uncertainty.csv']
    points,totals,bands,total_bands=[pd.read_csv(OUT/name) for name in inputs]
    def merge(p,b,keys):
        d=p.merge(b[keys+['ktCO2','lower_95_ktCO2','upper_95_ktCO2']],on=keys,how='outer',validate='one_to_one',suffixes=('','_band'),indicator=True)
        assert d['_merge'].eq('both').all()
        np.testing.assert_allclose(d.ktCO2,d.ktCO2_band,equal_nan=True)
        assert d.ktCO2.isna().equals(d.lower_95_ktCO2.isna()) and d.ktCO2.isna().equals(d.upper_95_ktCO2.isna())
        return d.drop(columns=['ktCO2_band','_merge'])
    sectors=merge(points,bands,['date','sector'])
    total=merge(totals[totals.scope.eq('covered_local_sectors')],total_bands[total_bands.scope.eq('covered_local_sectors')],['date','scope'])
    total['sector']='Local_total'
    expected=points.pivot(index='date',columns='sector',values='ktCO2')[LOCAL].sum(axis=1,min_count=6)
    np.testing.assert_allclose(total.set_index('date').ktCO2,expected.reindex(total.date),equal_nan=True)
    fields=['date','sector','ktCO2','lower_95_ktCO2','upper_95_ktCO2']
    data=pd.concat([sectors[fields],total[fields]],ignore_index=True).dropna(subset=['ktCO2'])
    data['date']=pd.to_datetime(data.date).dt.strftime('%Y%m')
    data=data.rename(columns={'ktCO2':'ktco2','lower_95_ktCO2':'ktco2_lower','upper_95_ktCO2':'ktco2_upper'}).sort_values(['date','sector']).reset_index(drop=True)
    assert not data.duplicated(['date','sector']).any() and data.date.str.fullmatch(r'\d{6}').all()
    assert np.isfinite(data[['ktco2','ktco2_lower','ktco2_upper']]).all().all() and data.ktco2_lower.le(data.ktco2_upper).all()
    path=DEST/'MCE_HK_monthly.csv';data.to_csv(path,index=False)
    coverage=data.groupby('sector').date.agg(['min','max','count']);common=data.groupby('date').sector.nunique();common=common[common.eq(9)].index
    (DEST/'manifest.json').write_text(json.dumps(dict(file=path.name,rows=len(data),fields=list(data.columns),unit='ktCO2',date_format='YYYYMM',common_period=[common.min(),common.max()],coverage=coverage.to_dict('index'),sha256=hashlib.sha256(path.read_bytes()).hexdigest(),input_sha256={n:hashlib.sha256((OUT/n).read_bytes()).hexdigest() for n in inputs},exporter_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()),indent=2)+'\n')
    lines=['# MCE-HK monthly emissions','','One UTF-8 CSV file: MCE_HK_monthly.csv.','',
        '| Field | Meaning |','|---|---|','| date | Calendar month as YYYYMM. |','| sector | One of the eight accounts below, or Local_total. |','| ktco2 | Monthly emission estimate, in kt CO2. |','| ktco2_lower | Lower bound of the conditional central 95% interval, in kt CO2. |','| ktco2_upper | Upper bound of the conditional central 95% interval, in kt CO2. |','',
        '## Coverage','','| Account | First month | Last month | Records |','|---|---|---|---:|']
    lines += [f'| {k} | {r["min"]} | {r["max"]} | {r["count"]} |' for k,r in coverage.iterrows()]
    lines += ['',f'All nine labels are available from {common.min()} through {common.max()}.',
        'Unavailable estimates are omitted; absence of a row is not zero emissions.',
        'Local_total sums Power, Industry, Road Transport, Domestic Navigation, Residential and Commercial. It excludes international aviation/shipping and is not a complete IPCC territorial inventory. Do not add Local_total to its component sectors.',
        'Local_total interval bounds come from aligned joint draws; do not sum sector lower/upper bounds.',
        'Power and international bunkers in 202607–202608 are missing-quarter activity nowcasts. All 2026 Power values use extrapolated intensity. Other extrapolations follow the manuscript methods.',
        'Detailed forecast status, reference periods and revision history remain in the model repository rather than this five-field file.',
        'Source snapshots have individual acquisition dates; the industrial historical-fuel update is recorded in the source manifest. CSV values retain full precision.',
        'Rebuild with python scripts/export_publication_data.py after regenerating model outputs.',
        'The old four-product package is retained only in legacy_v6/ and is not part of this publication product.','']
    (DEST/'README.md').write_text('\n'.join(lines));print(coverage.to_string());print(f'{len(data)} records; 5 fields; common period {common.min()}–{common.max()}')
if __name__=='__main__':main()
