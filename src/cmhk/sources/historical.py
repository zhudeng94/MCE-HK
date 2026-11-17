"""Read annual fuel/generation benchmarks from archived official energy reports.

Keep PDF page numbers and original values. Earlier annual constraints must never
be described as quarterly observations.
"""
import re
import pandas as pd
import pdfplumber

def numbers_at(words, top, boundaries):
    line=[w for w in words if abs(w['top']-top)<2]
    values=[]
    for left,right in zip(boundaries[:-1],boundaries[1:]):
        s=''.join(w['text'] for w in line if left<=(w['x0']+w['x1'])/2<right
                  and re.fullmatch(r'-?\d+',w['text']))
        values.append(float(s) if s else float('nan'))
    return values

def parse_energy_reports(raw):
    fuels=[];balance=[]
    for edition in [2009,2010,2011,2012,2013]:
        name=f'csd_energy_{edition}.pdf'
        with pdfplumber.open(raw/name) as doc:
            for page_index,page in enumerate(doc.pages):
                if not 8 <= page_index <= 26: continue
                text=page.extract_text() or ''
                words=page.extract_words()
                if 'overall energy balance' in text.lower() and 'electricity generation' in text.lower():
                    for w in words:
                        if w['text'].lower()!='generation':continue
                        yrs=[a for a in words if re.fullmatch(r'20\d\d',a['text']) and a['top']<w['top'] and a['x0']<220]
                        if not yrs:continue
                        year=int(max(yrs,key=lambda a:a['top'])['text'])
                        if not 2005<=year<=2012:continue
                        values=numbers_at(words,w['top'],[215,285,355,425,490,560])
                        if any(pd.isna(values)) or values[0]>=0 or values[1]>=0 or values[2]<=0:
                            raise ValueError(f'Invalid historical energy extraction {name}:{page_index+1}: {values}')
                        if abs(sum(values[:4])-values[4])>2:
                            raise ValueError(f'Historical energy transformation does not reconcile: {name}:{year}')
                        for fuel,v in zip(['COAL','OIL','ELEC','GAS','TOTAL'],values):
                            balance.append(dict(period=str(year),freq='Y',EN_REQ_TYPE='Elect_gen',
                                PROD_TYPE=fuel,sv='F_EN_REQ',figure=v,source=name,pdf_page=page_index+1))
                match=re.search(r'Sales of oil products by type of users for (20\d\d)',text)
                if not match:continue
                year=int(match.group(1))
                if not 2005<=year<=2012:continue
                table_rows={}
                for key,user in [('Ship','Ship stores'),('Aircraft','Aircraft stores'),('Subtotal','Sales for local consumption'),
                                 ('Re-exports','Re-exports'),('Overall','Overall sales')]:
                    label=next((w for w in words if w['text']==key and w['x0']<200),None)
                    if label is None:raise ValueError(f'Missing {key} in {name}')
                    # Chinese data line immediately precedes the English label/percentage line.
                    candidates=[w['top'] for w in words if label['top']-18<w['top']<label['top']-3
                                and w['x0']>205 and re.fullmatch(r'\d+',w['text'])]
                    if not candidates:raise ValueError(f'Missing numeric line {key}/{name}')
                    lpg_boundary=500 if edition==2013 else 520
                    values=numbers_at(words,max(candidates),[180,275,335,385,457,lpg_boundary,575])
                    if any(pd.isna(values)):raise ValueError(f'Bad oil columns {name}/{year}/{key}: {values}')
                    table_rows[user]=values
                    for fuel,v in zip(['E_1','E_2b','E_5','E_3','E_4','E_6'],values):
                        fuels.append(dict(period=str(year),freq='Y',SALES_TYPEDesc=user,PROD_TYPE=fuel,
                            figure=v,svDesc='Tonnes' if fuel=='E_6' else 'Kilolitres',
                            derivation='historical published annual benchmark',source=name,pdf_page=page_index+1))
                for i in range(6):
                    summed=sum(table_rows[k][i] for k in ['Ship stores','Aircraft stores','Sales for local consumption','Re-exports'])
                    if abs(summed-table_rows['Overall sales'][i])>2:
                        raise ValueError(f'Historical fuel table does not reconcile: {name}/{year}/column{i}: {summed} vs {table_rows["Overall sales"][i]}')
    f=pd.DataFrame(fuels).drop_duplicates(['period','SALES_TYPEDesc','PROD_TYPE'],keep='last')
    b=pd.DataFrame(balance).drop_duplicates(['period','PROD_TYPE'],keep='last')
    if set(f.period)!=set(map(str,range(2005,2013))) or set(b.period)!=set(map(str,range(2005,2013))):
        raise ValueError(f'Incomplete historical annual report coverage: fuel={sorted(set(f.period))}, energy={sorted(set(b.period))}')
    return f,b
