"""Parse the cached published annual GHG inventory (comparison/audit input)."""
import re
import pandas as pd
import pdfplumber
from cmhk.paths import ROOT
SOURCE='https://cnsd.gov.hk/wp-content/uploads/2026/01/Data-Tables_2024_AR5_Sector-r4.pdf'
COLS=['year','energy_industries','transport','other_fuel','waste','ippu','afolu','total_ghg']

def published_inventory():
    path=ROOT/'data/raw/official_ghg_sector_2024.pdf'
    if not path.exists():
        raise FileNotFoundError(f'{path}: acquire sources first with cmhk fetch')
    rows=[]
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            lines=(page.extract_text() or '').splitlines()
            for i,line in enumerate(lines):
                if re.match(r'^(199\d|20[0-2]\d)\s+',line):
                    values=re.findall(r'\b\d[\d,]*\b',line)
                    if len(values)==8:
                        rows.append([int(v.replace(',','')) for v in values])
                elif i+1<len(lines) and lines[i+1].strip()=='2024':
                    values=re.findall(r'\b\d[\d,]*\b',line)
                    if len(values)==7:
                        rows.append([2024]+[int(v.replace(',','')) for v in values])
    d=pd.DataFrame(rows,columns=COLS).set_index('year').sort_index()
    if d.index.duplicated().any() or set(d.index)!=set(range(1990,2025)):
        raise ValueError('Official GHG table parse incomplete')
    d['energy_ghg']=d[['energy_industries','transport','other_fuel']].sum(axis=1)
    return d
