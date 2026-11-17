"""Read verified output rows, not formula caches or fuel-energy inputs."""
import csv
import hashlib
import math
import shutil
from collections import defaultdict

import openpyxl


def numeric(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f'Invalid numeric value: {label}: {value!r}')
    return value


def export_power_workbook(root, dest):
    path = root / 'data/raw/power/HK_power_generation_2010_2025.xlsx'
    workbook = openpyxl.load_workbook(path, read_only=True, data_only=False)
    # Reading raw rows avoids treating absent Excel formula caches as zero.
    clp = defaultdict(list)
    seen = set()
    for row in workbook['CLP stations'].iter_rows(min_row=2, values_only=True):
        year, station, fuel, output, basis, _, _, url = row
        if (year, station) in seen:
            raise ValueError(f'Duplicate CLP plant/year: {year}, {station}')
        seen.add((year, station))
        if fuel not in ('Gas', 'Coal'):
            raise ValueError(f'Unexpected CLP primary fuel: {fuel}')
        numeric(output, f'CLP {year} {station}')
        if year == 2010:
            if basis != 'Annual-report generation':
                raise ValueError('Unexpected basis for 2010')
            continue  # Not established to be net sent out; retained in workbook download.
        if basis != 'Net sent out' or not url:
            raise ValueError(f'Unverified output basis/source: {year} {station}')
        clp[year].append((station, fuel, output, url))
    hke = defaultdict(list)
    seen = set()
    for row in workbook['HKE generation'].iter_rows(min_row=2, values_only=True):
        year, half, gas, coal, renewables, total, _, url = row
        if (year, half) in seen:
            raise ValueError(f'Duplicate HKE half-year: {year} {half}')
        seen.add((year, half))
        for value in (gas, coal, renewables, total):
            if numeric(value, f'HKE {year} {half}') < 0:
                raise ValueError('Negative HKE output')
        if abs(gas + coal + renewables - total) > 1 or not url:
            raise ValueError(f'HKE output conservation/source: {year} {half}')
        hke[year].append((half, gas, coal, url))
    workbook.close()
    companies = []
    for year, rows in sorted(clp.items()):
        expected = {'Black Point', 'Castle Peak'} if year < 2020 else {
            'Black Point C', 'Black Point D', 'Castle Peak A', 'Castle Peak B'}
        if {r[0] for r in rows} != expected:
            raise ValueError(f'Incomplete CLP plant coverage: {year}')
        companies.append(dict(year=year, company='CLP',
                              gas_GWh=sum(r[2] for r in rows if r[1] == 'Gas'),
                              coal_class_GWh=sum(r[2] for r in rows if r[1] == 'Coal'),
                              basis='Net sent out',
                              source_urls=' | '.join(sorted({r[3] for r in rows}))))
    for year, rows in sorted(hke.items()):
        if {r[0] for r in rows} != {'H1', 'H2'}:
            if year == max(hke) and {r[0] for r in rows} == {'H1'}:
                continue  # Preserve the partial source, but do not label it annual output.
            raise ValueError(f'Incomplete HKE year: {year}')
        companies.append(dict(year=year, company='HK Electric',
                              gas_GWh=sum(r[1] for r in rows),
                              coal_class_GWh=sum(r[2] for r in rows),
                              basis='Net sent out; coal and oil combined',
                              source_urls=' | '.join(sorted({r[3] for r in rows}))))
    combined = []
    for year in sorted(set(clp) & {r['year'] for r in companies if r['company']=='HK Electric'}):
        records = [r for r in companies if r['year'] == year]
        gas = sum(r['gas_GWh'] for r in records)
        coal = sum(r['coal_class_GWh'] for r in records)
        combined.append(dict(year=year, gas_GWh=gas, coal_class_GWh=coal,
                             selected_thermal_total_GWh=gas + coal,
                             gas_share_of_selected_thermal_pct=100 * gas / (gas + coal),
                             coal_class_note='CLP coal-plant net output + HK Electric coal and oil output; not pure-coal generation'))
    manifest = []
    for filename, rows in [('power-fuel-output.csv', combined), ('power-company-output.csv', companies)]:
        with (dest / filename).open('w') as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        manifest.append({'file': filename, 'sha256': hashlib.sha256((dest / filename).read_bytes()).hexdigest()})
    shutil.copyfile(path, dest / path.name)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest.append({'file': path.name, 'sha256': digest})
    return companies, combined, manifest
