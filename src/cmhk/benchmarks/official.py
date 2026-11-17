"""Official CO2 levels and activity-ratio calibration, independent of reports."""
from pathlib import Path
import hashlib

import numpy as np
import pandas as pd

from cmhk.paths import ROOT, code_hashes
import json
MAPPING = json.loads((ROOT / 'configs/sector_mapping.json').read_text())
CATEGORIES = {r['sector']: (r['sheet'], r['row_prefix'], r['column_index']) for r in MAPPING['categories']}



def crt_value(book, sheet, category, column=7):
    data = pd.read_excel(book, sheet_name=sheet, header=None)
    hit = data[data[1].fillna('').astype(str).str.strip().str.startswith(category)]
    if len(hit) != 1:
        raise ValueError(f'CRT category ambiguous: {book.name}/{sheet}/{category}')
    value = hit.iloc[0, column]
    if not isinstance(value, (int, float, np.number)) or not np.isfinite(value) or value <= 0:
        raise ValueError(f'Invalid CRT benchmark: {category}/{value}')
    return float(value), f'{chr(65+column)}{int(hit.index[0])+1}'


def crt_benchmarks(root=ROOT, years=(2005, 2020, 2021), baseline_year=2021):
    rows = []
    for year in years:
        books = list((root/'data/raw/inventory/China_BTR1_CRT_2024-12-31_HKSAR').glob(f'*-{year}-*.xlsx'))
        if len(books) != 1:
            raise ValueError(f'Expected one official workbook for {year}')
        book = books[0]
        checksum = hashlib.sha256(book.read_bytes()).hexdigest()
        for sector, (sheet, label, column) in CATEGORIES.items():
            value, cell = crt_value(book, sheet, label, column)
            rule = next(r for r in MAPPING['categories'] if r['sector'] == sector)
            if rule['operation'] == 'transport_minus_navigation':
                transport,transport_cell=crt_value(book,'Table1.A(a)s3','1.A.3  Transport',7)
                navigation,navigation_cell=crt_value(book,'Table1.A(a)s3','1.A.3.d.',7)
                value=transport-navigation
                cell=f'{transport_cell}-{navigation_cell}'
            rows.append(dict(year=year, sector=sector, official_ktCO2=value,
                calibration_anchor=(sector not in ['Road','Transport'] and year == baseline_year),
                source=str(book.relative_to(root)), sheet=sheet, cell=cell, sha256=checksum))
    return pd.DataFrame(rows)


def activity_baseline(series, year):
    dates = pd.date_range(f'{year}-01-01', periods=12, freq='MS')
    if series.index.has_duplicates:
        raise ValueError('Duplicate activity months')
    base = series.reindex(dates)
    if not np.isfinite(base).all() or base.lt(0).any() or base.sum() <= 0:
        raise ValueError(f'Complete positive activity baseline required: {year}')
    return float(base.sum())


def calibrate_series(series, official_ktCO2, year):
    """E_m = official annual E_b * P_m / sum(P_b); partial years stay partial."""
    if not np.isfinite(official_ktCO2) or official_ktCO2 <= 0:
        raise ValueError('Positive official CO2 baseline required')
    if series.dropna().lt(0).any() or np.isinf(series).any():
        raise ValueError('Invalid activity proxy')
    coefficient = official_ktCO2 / activity_baseline(series, year)
    return series * coefficient, coefficient


def calibrate_scenarios(data, config, calibration):
    """Every structural path uses its OWN baseline, preserving activity ratios."""
    result = data.copy()
    year = config['official_baseline']['year']
    anchored = set(config['official_baseline']['rescale_sectors'])
    for (sector, scenario), block in result.groupby(['sector', 'scenario']):
        if sector not in anchored:
            continue
        series = block.set_index('date').ktCO2
        values, _ = calibrate_series(series, calibration.loc[sector, 'official_ktCO2'], year)
        result.loc[block.index, 'ktCO2'] = values.reindex(block.date).to_numpy()
    return result


def main():
    """Export the auditable benchmark table before any emission calculations."""
    table = crt_benchmarks()
    out = ROOT / 'outputs/diagnostics'
    out.mkdir(parents=True, exist_ok=True)
    table.to_csv(out / 'sector_benchmarks.csv', index=False)
    print(table[['year', 'sector', 'official_ktCO2', 'calibration_anchor', 'sheet', 'cell']].to_string(index=False))


if __name__ == '__main__':
    main()
