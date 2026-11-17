"""Publish and validate the compact monthly data record used in the manuscript."""
from pathlib import Path
import hashlib
import json
import shutil

import numpy as np
import pandas as pd

from cmhk.aggregation import LOCAL, SCOPES
from cmhk.paths import ROOT

COLUMNS = ['date', 'sector', 'ktco2', 'ktco2_lower', 'ktco2_upper']
SECTORS = SCOPES['covered_sectors_plus_international_bunkers']


def publish(root=ROOT):
    """Copy the manuscript CSV without changing its values, precision or row set."""
    source = root / 'outputs/publication/MCE_HK_monthly.csv'
    folder = root / 'results'
    folder.mkdir(exist_ok=True)
    path = folder / source.name
    shutil.copyfile(source, path)
    data = pd.read_csv(path, dtype={'date': str})
    coverage = data.groupby('sector').date.agg(['min', 'max', 'count'])
    common = data.groupby('date').sector.nunique()
    common = common[common.eq(len(SECTORS) + 1)].index
    manifest = {
        'file': path.name, 'unit': 'ktCO2', 'date_format': 'YYYYMM',
        'columns': COLUMNS, 'rows': len(data),
        'common_period': [common.min(), common.max()],
        'coverage': coverage.to_dict('index'),
        'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
        'as_of': json.loads((root/'configs/model.json').read_text())['as_of'],
        'config_sha256': {name: hashlib.sha256((root/name).read_bytes()).hexdigest()
                          for name in ['configs/model.json', 'configs/uncertainty.json', 'configs/sector_mapping.json']},
    }
    (folder/'manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
    lines = [
        '# MCE-HK monthly emissions', '',
        'One UTF-8 CSV: [MCE_HK_monthly.csv](MCE_HK_monthly.csv). Emissions are in kt CO₂ (1 kt = 1,000 tonnes).', '',
        '| Column | Description |', '|---|---|',
        '| `date` | Calendar month, YYYYMM. |',
        '| `sector` | Eight sector accounts or `Local_total`. |',
        '| `ktco2` | Monthly combustion CO₂ estimate. |',
        '| `ktco2_lower`, `ktco2_upper` | Lower and upper bounds of the central 95% model interval. |', '',
        '## Coverage', '', '| Account | First month | Last month | Records |', '|---|---|---|---:|',
    ]
    lines += [f'| {sector} | {row["min"]} | {row["max"]} | {row["count"]} |'
              for sector, row in coverage.iterrows()]
    lines += ['', f'All eight sectors and the local total are available from {common.min()} to {common.max()}.', '',
              '`Local_total` sums Power, Industry, Road Transport, Domestic Navigation, Residential and Commercial. International aviation and shipping are separate accounts for fuel supplied in Hong Kong. Road Transport includes the remaining domestic transport categories after subtracting domestic navigation.', '',
              'Unavailable observations are omitted; an absent row is not zero. Local totals require all six sectors. Their interval bounds are calculated from aligned joint draws and are not sums of sector bounds.', '',
              'The 95% intervals are conditional on the configured input-error distributions and structural assumptions. Recent observations may use activity nowcasts or extrapolated fuel intensities. The local total covers the included combustion sectors, rather than the complete territorial greenhouse-gas inventory.', '',
              'The snapshot date, per-account coverage, model-configuration checksums and CSV checksum are recorded in [manifest.json](manifest.json).', '']
    (folder/'README.md').write_text('\n'.join(lines))
    return validate(root)


def validate(root=ROOT):
    """Check the published file using its schema, accounting identities and hashes."""
    folder = Path(root) / 'results'
    manifest = json.loads((folder/'manifest.json').read_text())
    path = folder/'MCE_HK_monthly.csv'
    if manifest['file'] != path.name or manifest['sha256'] != hashlib.sha256(path.read_bytes()).hexdigest():
        raise ValueError('Published CSV checksum mismatch')
    data = pd.read_csv(path, dtype={'date': str})
    if list(data.columns) != COLUMNS or manifest['columns'] != COLUMNS:
        raise ValueError('Unexpected publication columns')
    if data.empty or len(data) != manifest['rows'] or data.duplicated(['date','sector']).any():
        raise ValueError('Empty, duplicate or inconsistent publication records')
    if not data.date.str.fullmatch(r'\d{6}').all():
        raise ValueError('Publication dates must use YYYYMM')
    dates = pd.to_datetime(data.date, format='%Y%m')
    if set(data.sector) != set(SECTORS) | {'Local_total'}:
        raise ValueError('Unexpected publication sector set')
    values = data[COLUMNS[2:]].to_numpy()
    if not np.isfinite(values).all() or (values < 0).any() or not data.ktco2_lower.le(data.ktco2_upper).all():
        raise ValueError('Invalid emission values or interval endpoints')
    if not data[['date','sector']].equals(data.sort_values(['date','sector'])[['date','sector']]):
        raise ValueError('Publication records must be sorted by month and sector')
    cutoff = pd.Timestamp(manifest['as_of'])
    if (dates + pd.offsets.MonthEnd() > cutoff).any():
        raise ValueError('Future or incomplete-month observations in the publication')
    frame = data.pivot(index='date', columns='sector', values='ktco2')
    expected = frame[LOCAL].sum(axis=1, min_count=len(LOCAL))
    actual = frame['Local_total']
    if not expected.notna().equals(actual.notna()) or not np.allclose(expected, actual, equal_nan=True):
        raise ValueError('Published local total does not equal its six sectors')
    coverage = data.groupby('sector').date.agg(['min','max','count']).to_dict('index')
    if coverage != manifest['coverage']:
        raise ValueError('Publication coverage metadata mismatch')
    common = data.groupby('date').sector.nunique()
    common = common[common.eq(len(SECTORS)+1)].index
    if common.empty or [common.min(), common.max()] != manifest['common_period']:
        raise ValueError('Publication common period mismatch')
    for name, digest in manifest['config_sha256'].items():
        if hashlib.sha256((Path(root)/name).read_bytes()).hexdigest() != digest:
            raise ValueError(f'Configuration differs from the published snapshot: {name}')
    result = {'file': str(path), 'rows': len(data), 'common_period': manifest['common_period'], 'checks': 'passed'}
    print(json.dumps(result, indent=2))
    return result


if __name__ == '__main__':
    validate()
