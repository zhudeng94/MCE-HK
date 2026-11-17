"""Compare the current full-transport dataset with cached Climate TRACE CO2."""
from pathlib import Path
import datetime
import hashlib
import json
import os
import numpy as np
import pandas as pd

from cmhk.paths import ROOT, code_hashes
OUT = ROOT/'outputs/climate_trace_comparison'
RAW = ROOT/'data/raw/climate_trace'
os.environ.setdefault('MPLCONFIGDIR', str(ROOT/'.tmp/matplotlib'))
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt


def series(data):
    return pd.Series({pd.Timestamp(r['year'],r['month'],1):r['value']/1e6 for r in data['emissions']})


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    raw=json.loads((RAW/'climate_trace_raw.json').read_text())
    ct=pd.DataFrame({'total':series(raw)})
    for sector in raw['sectors']:
        ct[sector['sector']]=pd.Series({pd.Timestamp(r['year'],r['month'],1):next(x['value']/1e6 for x in r['sectors'] if x['sector']==sector['sector']) for r in raw['emissions']})
    for path in RAW.glob('ct_*.json'):
        if path.stem=='ct_2025':continue
        data=json.loads(path.read_text());name=path.stem[3:]
        if not np.isclose(data['totals']['value'],next(s['value'] for s in raw['subsectors'] if s['subsector']==name)):
            raise ValueError('Cached Climate TRACE query totals differ')
        ct[name]=series(data)
    np.testing.assert_allclose(ct[[s['sector'] for s in raw['sectors']]].sum(axis=1),ct.total)
    ct['transport_excluding_international']=ct.transportation-ct['international-aviation']-ct['international-shipping']
    ct['total_excluding_international']=ct.total-ct['international-aviation']-ct['international-shipping']
    if ct.transport_excluding_international.lt(-1e-8).any():
        raise ValueError('Negative residual CT transport')
    cm=pd.read_csv(ROOT/'outputs/hong_kong_sector_monthly.csv',parse_dates=['date']).pivot(index='date',columns='sector',values='ktCO2')/1000
    from cmhk.aggregation import with_transport_sum
    cm=with_transport_sum(cm)
    road_path=ROOT/'outputs/diagnostics/road_monthly_proxy.csv'
    cm['Road input']=pd.read_csv(road_path,parse_dates=['date']).set_index('date').ktCO2/1000
    mt=pd.read_csv(ROOT/'outputs/hong_kong_total_monthly.csv',parse_dates=['date']).pivot(index='date',columns='scope',values='ktCO2')/1000
    common=ct.index.intersection(mt.dropna().index).sort_values()
    if common.empty:raise ValueError('No complete common comparison months')
    c,t,m=cm.loc[common],ct.loc[common],mt.loc[common]
    monthly=pd.DataFrame({'cmhk_local':m.covered_local_sectors,
        'cmhk_with_bunkers':m.covered_sectors_plus_international_bunkers,
        'ct_all_excluding_forestry':t.total,
        'ct_excluding_international_aviation_shipping':t.total_excluding_international,
        'cmhk_transport':c.Transport,'ct_transport_excluding_international':t.transport_excluding_international})
    monthly.index.name='date';monthly.to_csv(OUT/'monthly_totals_MtCO2.csv')
    ct.index.name='date';ct.to_csv(OUT/'climate_trace_monthly_MtCO2.csv')
    annual=monthly.groupby(monthly.index.year).sum(min_count=1)
    annual['months']=monthly.groupby(monthly.index.year).size()
    annual['cmhk_with_bunkers_minus_ct_pct']=(annual.cmhk_with_bunkers/annual.ct_all_excluding_forestry-1)*100
    annual['local_difference_pct']=(annual.cmhk_local/annual.ct_excluding_international_aviation_shipping-1)*100
    annual.to_csv(OUT/'annual_comparison_MtCO2.csv')
    pairs={'Power':('electricity-generation','electricity generation; attribution may differ'),
        'Transport':('transport_excluding_international','CMHK road + navigation vs CT transportation minus international aviation/shipping; other transport/vessel attribution can differ'),
        'Road Transport':('road-transportation','Road account includes residual domestic transport; CT road only'),
        'Domestic Navigation':('domestic-shipping','Domestic navigation vs CT domestic-shipping attribution'),
        'Road input':('road-transportation','uncalibrated road activity input only; not an additional main sector'),
        'Residential':('residential-onsite-fuel-usage','residential combustion'),
        'Commercial':('non-residential-onsite-fuel-usage','commercial vs non-residential'),
        'Industry':('manufacturing','combustion vs manufacturing including processes'),
        'International Aviation':('international-aviation','fuel supply vs flight attribution'),
        'International Shipping':('international-shipping','fuel supply vs voyage attribution')}
    rows=[];metrics=[]
    for year in annual.index:
        for sector,(target,note) in pairs.items():
            a=c.loc[c.index.year==year,sector].sum(min_count=int(annual.loc[year,'months']))
            b=t.loc[t.index.year==year,target].sum(min_count=int(annual.loc[year,'months']))
            rows.append(dict(year=year,months=int(annual.loc[year,'months']),cmhk_sector=sector,ct_sector=target,
                cmhk_MtCO2=a,ct_MtCO2=b,cmhk_minus_ct_MtCO2=a-b,
                cmhk_minus_ct_pct=(a/b-1)*100 if b else np.nan,boundary_note=note))
    sectors=pd.DataFrame(rows);sectors.to_csv(OUT/'annual_sector_comparison.csv',index=False)
    for sector,(target,note) in pairs.items():
        metrics.append(dict(cmhk_sector=sector,ct_sector=target,months=len(common),
            monthly_pearson_r=c[sector].corr(t[target]),boundary_note=note))
    pd.DataFrame(metrics).to_csv(OUT/'monthly_correlations.csv',index=False)
    year=int(annual[annual.months.eq(12)].index.max())
    fig,axes=plt.subplots(2,2,figsize=(13,8))
    ax=axes[0,0];ax.plot(common,m.covered_local_sectors,label='CMHK covered local sectors')
    ax.plot(common,t.total_excluding_international,label='CT excluding international aviation/shipping')
    ax.set_title('Local totals: remaining scope differences');ax.legend(fontsize=8)
    for ax,a,b,title in [(axes[0,1],'Power','electricity-generation','Electricity generation'),
                        (axes[1,0],'Transport','transport_excluding_international','Road + navigation / CT excluding international')]:
        ax.plot(common,c[a],label='CMHK');ax.plot(common,t[b],label='Climate TRACE')
        ax.set_title(title,fontsize=10);ax.legend(fontsize=8)
    for ax in [axes[0,0],axes[0,1],axes[1,0]]:ax.set_ylabel('Mt CO2 / month');ax.grid(alpha=.2)
    s=sectors[(sectors.year==year)&~sectors.cmhk_sector.isin(['Road input','Transport'])]
    ax=axes[1,1];idx=np.arange(len(s))
    ax.barh(idx-.18,s.cmhk_MtCO2,height=.36,label='CMHK')
    ax.barh(idx+.18,s.ct_MtCO2,height=.36,label='CT mapped category')
    ax.set_yticks(idx,s.cmhk_sector);ax.set_xlabel('Mt CO2 / year')
    ax.set_title(f'{year}: sector totals (boundary differences)');ax.legend(fontsize=8)
    fig.tight_layout()
    for ext in ['png','pdf']:fig.savefig(OUT/f'comparison.{ext}',dpi=180)
    plt.close(fig)
    files=[ROOT/'outputs/hong_kong_sector_monthly.csv',ROOT/'outputs/hong_kong_total_monthly.csv',road_path,*RAW.glob('*.json')]
    (OUT/'comparison_manifest.json').write_text(json.dumps(dict(
        analysis_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        query='https://api.c10e.org/v7/app/emissions?years=2021-2026&gas=co2&subsectors=&timeGranularity=month&excludeForestry=true&gadmId=HKG',
        ct_unit='tonnes CO2 divided by 1e6',cmhk_unit='ktCO2 divided by 1000',
        common_months=len(common),start=str(common.min().date()),end=str(common.max().date()),
        transport_mapping=pairs['Transport'],
        input_sha256={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in files},
        code_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()),indent=2)+'\n')
    lines=['# CMHK 与 Climate TRACE：现行完整运输方法','',
        f'共同比较窗口为 **{common.min():%Y-%m} 至 {common.max():%Y-%m}，{len(common)} 个月**。仅使用双方都有完整总量的月份；2025 起运输使用固定强度外推；不完整年份按表列月数累计，不年化。',
        '双方均为 CO₂，图表单位为 MtCO₂；估算方法与部门边界仍有差异。','',
        '## 总量','',
        '| 年份 | 月数 | CMHK 本地 | CT 扣国际航空/航运 | CMHK 含国际供油 | CT 全部（不含林业） | 含供油数值差额 |',
        '|---|---:|---:|---:|---:|---:|---:|']
    for r in annual.itertuples():
        lines.append(f'| {r.Index} | {r.months} | {r.cmhk_local:.3f} | {r.ct_excluding_international_aviation_shipping:.3f} | {r.cmhk_with_bunkers:.3f} | {r.ct_all_excluding_forestry:.3f} | {r.cmhk_with_bunkers_minus_ct_pct:+.2f}% |')
    lines+=['','## 运输与各部门','',
        'CMHK Transport 已代表完整 1.A.3，故 CT 对照为 transportation 减 international-aviation 和 international-shipping，不能再直接对应 road-transportation。该残差还受 CT 其他运输和船舶归属规则影响，不宣称严格同口径。',
        '本地总量对照保留 CT domestic-shipping；只扣国际航空、国际航运。CT 仍含模型未覆盖的工业过程、废弃物等。',
        'Road input 单独展示原道路活动输入，用于诊断；它不再代表主表 Transport，也不额外加入任何总量。','',
        f'### {year} 年（MtCO₂）','',
        '| 部门 | CMHK | CT 对应类别 | 数值差额 |', '|---|---:|---:|---:|']
    for r in sectors[sectors.year==year].itertuples():
        lines.append(f'| {r.cmhk_sector} | {r.cmhk_MtCO2:.3f} | {r.ct_MtCO2:.3f} | {r.cmhk_minus_ct_pct:+.2f}% |')
    lines+=['','## 月度相关性','', '| 部门 | Pearson r |', '|---|---:|']
    for r in metrics:lines.append(f'| {r["cmhk_sector"]} | {r["monthly_pearson_r"]:.3f} |')
    lines+=['','相关性和总量接近不构成准确性证明；运输 2021 由 CRT 标定，月度海运含客流/日历假设。国际供油与 CT 航程归属口径不同，工业燃烧与制造业含过程排放也不同。',
        '', '![比较图](comparison.png)','',
        '源缓存位于 `data/raw/climate_trace/`；运行 `python src/cmhk/analysis/climate_trace.py` 同时重建数据、图和本报告。',
        '源查询及输入 SHA-256 见 `comparison_manifest.json`；本次没有刷新 Climate TRACE 快照。']
    (OUT/'report.md').write_text('\n'.join(lines)+'\n')
    print(f'Climate TRACE comparison rebuilt: {len(common)} months, {common.min():%Y-%m} to {common.max():%Y-%m}')


if __name__=='__main__':main()
