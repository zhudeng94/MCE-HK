"""Normalize cached official sources to explicit units and dates."""
import calendar
import json
import logging
import re
from pathlib import Path
import numpy as np
import pandas as pd
import pdfplumber

from cmhk.paths import ROOT, code_hashes
RAW, CLEAN = ROOT / 'data/raw', ROOT / 'data/processed'
CFG = json.loads((ROOT/'configs/model.json').read_text())
START, END = CFG['start_year'], CFG['end_year']
MONTHS = {v: k for k, v in enumerate(calendar.month_abbr) if v}

def csd(table):
    obj = json.loads((RAW / f'csd_{table}.json').read_text())
    if obj['header']['status']['code'] != 0:
        raise ValueError(f'C&SD query unsuccessful: {table}')
    d = pd.DataFrame(obj['dataSet'])
    d['figure'] = pd.to_numeric(d.figure, errors='coerce')
    d['period'] = d.period.astype(str)
    return d

def write(d, name):
    CLEAN.mkdir(parents=True, exist_ok=True)
    d.to_csv(CLEAN / name, index=False)

def complete_oil_quarters(d):
    """C&SD publishes Q1-Q3 and annual totals. Derive Q4 by subtraction."""
    d = d.copy()
    d['derivation'] = 'published'
    added = []
    for _, annual in d[d.freq == 'Y'].iterrows():
        q = d[(d.freq == 'Q') & (d.period.str[:4] == annual.period) &
              (d.SALES_TYPEDesc == annual.SALES_TYPEDesc) & (d.PROD_TYPE == annual.PROD_TYPE)]
        if set(q.period) != {annual.period+s for s in ['03','06','09']} or q.figure.isna().any() or pd.isna(annual.figure):
            continue
        row = annual.copy()
        row['freq'], row['period'] = 'Q', annual.period+'12'
        row['figure'] = annual.figure - q.figure.sum()
        row['derivation'] = 'annual minus published Q1-Q3'
        if row['figure'] < 0:
            raise ValueError('Negative derived Q4 oil sales')
        added.append(row)
    return pd.concat([d, pd.DataFrame(added)], ignore_index=True)

def airport():
    rows = []
    for year in range(max(2005, START), END+1):
        source = RAW / f'airport_{year}.pdf'
        if not source.exists() and year >= END - 1:
            continue  # Current annual source may not have been published yet.
        with pdfplumber.open(source) as doc:
            text = doc.pages[0].extract_text()
            line = next(x for x in text.splitlines() if re.match(r'\(d\)\s+Total', x))
            # Older PDF embeds artificial spaces within decimal monthly counts.
            if year <= 2012:
                line=re.sub(r'(\d)\s+(\d\.\d)',r'\1\2',line)
                line=re.sub(r'(\d)\s+(\.\d)',r'\1\2',line)
            values = [float(x) * 1000 for x in re.findall(r'\d+(?:\.\d+)?', line)]
            if not 2 <= len(values) <= 13 or (year < END-1 and len(values)!=13):
                raise ValueError(f'Airport monthly column parse failed: {year}: {line}')
            if abs(sum(values[:-1])-values[-1])>6500:
                raise ValueError(f'Airport monthly counts do not reconcile with rounded annual total: {year}')
            # The last column is year-to-date; monthly counts are rounded to 1,000.
            for month, value in enumerate(values[:-1], 1):
                rows.append(dict(date=f'{year}-{month:02}-01', movements=value,
                                 source=f'airport_{year}.pdf', resolution='1000 movements'))
    write(pd.DataFrame(rows), 'airport.csv')

def marine():
    rows = []
    for name in ['marine_2_m_a1.pdf', 'marine_1_m_a1.pdf']:
        with pdfplumber.open(RAW / name) as doc:
            for page in doc.pages:
                text = page.extract_text()
                kind = ('Ocean' if '\nOcean Vessels\n' in text else
                        'River' if '\nRiver Vessels\n' in text else 'Overall')
                if kind == 'Overall':
                    continue
                table = page.find_tables()[0]
                boxes = [c.bbox for c in table.columns][1:]
                # A merged header spans all three columns; use successive left edges.
                bounds = [(b[0], b[1], boxes[i+1][0] if i+1 < len(boxes) else b[2], b[3])
                          for i, b in enumerate(boxes)]
                words = page.extract_words()
                stop = min((w['top'] for w in words if w['text'] == 'Year-on-year'), default=page.height)
                year = None
                for month_word in words:
                    if month_word['text'] not in MONTHS or month_word['top'] >= stop:
                        continue
                    line = [w for w in words if abs(w['top'] - month_word['top']) < 2]
                    years = [int(w['text']) for w in line if re.fullmatch(r'20\d\d|19\d\d', w['text'])
                             and w['x1'] < month_word['x0']]
                    if years:
                        year = years[0]
                    if year is None or year < START:
                        continue
                    values = []
                    for box in bounds:
                        lo, _, hi, _ = box
                        mid = (lo + hi) / 2
                        for left, right in [(lo, mid), (mid, hi)]:
                            digits = ''.join(w['text'] for w in line
                                             if left <= (w['x0'] + w['x1']) / 2 < right)
                            values.append(float(digits) if digits.isdigit() else np.nan)
                    if len(values) != 6 or not np.isfinite(values[4]):
                        continue
                    # Historical counts are rounded to tens; retain published subtotal.
                    tolerance = 10 if year <= 2009 else 0
                    if not np.isclose(values[0] + values[2], values[4],atol=tolerance,rtol=0):
                        raise ValueError(f'Vessel columns do not sum: {name}, {year}, {month_word}')
                    rows.append(dict(date=f'{year}-{MONTHS[month_word["text"]]:02}-01', kind=kind,
                                     cargo_arrivals=values[0], passenger_arrivals=values[2],
                                     arrivals=values[4], net_tonnage_thousand=values[5], source=name,
                                     count_rounding_tolerance=tolerance))
    d = pd.DataFrame(rows).drop_duplicates(['date', 'kind'], keep='last')
    write(d.sort_values(['date', 'kind']), 'marine.csv')

def traffic_census():
    rows = []
    for edition, page_index in [(2014,16),(2016,16),(2018,16),(2020,16),(2022,17),(2024,19)]:
        name = f'traffic_census_{edition}.pdf'
        with pdfplumber.open(RAW/name) as doc:
            text = doc.pages[page_index].extract_text()
            if 'Average Daily Vehicle-kilometre' not in text:
                raise ValueError('Traffic census layout changed')
            line = next(line for line in text.splitlines() if re.match(r'^Total\s+\d',line))
            groups = re.findall(r'\d+', line)
            if len(groups) != 6:
                raise ValueError(f'Unexpected VKT total: {line}')
            for i, year in enumerate([edition-1,edition]):
                daily = int(''.join(groups[i*3:i*3+3]))
                rows.append(dict(year=year, daily_vkt=daily, annual_vkt=daily*(366 if calendar.isleap(year) else 365),
                                 source=name, pdf_page=page_index+1))
    write(pd.DataFrame(rows), 'annual_vkt.csv')

def main():
    logging.getLogger('pdfminer').setLevel(logging.ERROR)
    from cmhk.sources.historical import parse_energy_reports
    historical_fuel,historical_balance=parse_energy_reports(RAW)
    write(historical_fuel,'historical_fuel_benchmarks.csv')
    write(historical_balance,'historical_energy_balance.csv')
    for table in ['915-91201', '915-91106', '915-91203', '915-91001', '610-65001']:
        d = csd(table)
        if table == '915-91106':
            d = complete_oil_quarters(d)
            d = pd.concat([historical_fuel,d],ignore_index=True)
        if table == '915-91001':
            d = pd.concat([historical_balance,d],ignore_index=True)
        write(d[d.period.str[:4].astype(int).between(START, END)], f'csd_{table}.csv')
    temperatures = []
    for year in range(2019, END+1):
        if not (RAW / f'temperature_{year}.csv').exists() and year >= END-1:
            continue
        d = pd.read_csv(RAW / f'temperature_{year}.csv', skiprows=2)
        d.columns = ['year', 'month', 'day', 'temperature_c', 'completeness']
        for c in ['year', 'month', 'day', 'temperature_c']:
            d[c] = pd.to_numeric(d[c], errors='coerce')
        d = d.dropna(subset=['year', 'month', 'day', 'temperature_c'])
        d['date'] = pd.to_datetime(d[['year', 'month', 'day']])
        temperatures.append(d[['date', 'temperature_c', 'completeness']])
    write(pd.concat(temperatures), 'temperature.csv')
    airport()
    marine()
    traffic_census()
    # Existing CEIC workbook: historical fuel demand indices, NOT road fuel measurements.
    book=ROOT/'data/raw/legacy/HK.xlsx'
    legacy=pd.read_excel(book,index_col=0).iloc[28:]
    legacy.index=pd.to_datetime(legacy.index)
    prefix='Energy Balance: Secondary: Total Oil Products: '
    columns={'petrol':prefix+'Motor and Aviation Gasoline: Demand',
             'diesel':prefix+'Gas or Diesel Oil: Demand',
             'lpg':prefix+'Liquefied Petroleum Gases: Demand'}
    activity=legacy.loc['2005':'2012',list(columns.values())].apply(pd.to_numeric,errors='coerce')
    activity.columns=list(columns)
    if len(activity)!=96 or activity.isna().any().any() or (activity<=0).any().any():
        raise ValueError('Historical oil demand proxy is incomplete')
    activity.to_csv(CLEAN/'historical_road_activity.csv',index_label='date')
    print('Normalized official data in', CLEAN)

if __name__ == '__main__':
    main()
