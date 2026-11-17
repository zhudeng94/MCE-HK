"""Read-only comparison of model outputs with official inventory benchmarks."""
import json
import hashlib
import os
import re
from pathlib import Path
import numpy as np
import pandas as pd
import pdfplumber

from cmhk.paths import ROOT, code_hashes
OUT=ROOT/'outputs/official_inventory_comparison'
os.environ.setdefault('MPLCONFIGDIR',str(ROOT/'.tmp/matplotlib'))
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.ticker import MaxNLocator
from cmhk.benchmarks.official import crt_value, crt_benchmarks

from cmhk.sources.inventory import published_inventory, SOURCE
from cmhk.aggregation import LOCAL, with_transport_sum


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    monthly=pd.read_csv(ROOT/'outputs/hong_kong_sector_monthly.csv',parse_dates=['date'])
    monthly['year']=monthly.date.dt.year
    grouped=monthly.groupby(['year','sector']).ktCO2.agg(['sum','count'])
    annual=grouped['sum'].where(grouped['count']==12).unstack('sector')
    annual=with_transport_sum(annual)
    road=pd.read_csv(ROOT/'outputs/diagnostics/road_monthly_proxy.csv',parse_dates=['date'])
    road=road.groupby(road.date.dt.year).ktCO2.agg(['sum','count'])
    annual['Road']=road['sum'].where(road['count']==12)
    official=published_inventory()
    official.to_csv(OUT/'official_ghg_1990_2024.csv')
    refs=crt_benchmarks()
    refs['model_ktCO2']=[annual.loc[r.year,r.sector] for r in refs.itertuples()]
    refs['bias_ktCO2']=refs.model_ktCO2-refs.official_ktCO2
    refs['bias_pct']=(refs.model_ktCO2/refs.official_ktCO2-1)*100
    aligned=[]
    for year,d in refs.groupby('year'):
        for scope,include in [('covered_local_sectors',LOCAL),('covered_plus_international',LOCAL+['International Aviation','International Shipping'])]:
            sub=d[d.sector.isin(include)]
            aligned.append(dict(year=year,sector=scope,official_ktCO2=sub.official_ktCO2.sum(),
                model_ktCO2=sub.model_ktCO2.sum(min_count=len(include)),calibration_anchor=bool(sub.calibration_anchor.all()),source='sum of matched CRT categories',sheet='',cell=''))
    refs=pd.concat([refs,pd.DataFrame(aligned)],ignore_index=True)
    refs['bias_ktCO2']=refs.model_ktCO2-refs.official_ktCO2
    refs['bias_pct']=(refs.model_ktCO2/refs.official_ktCO2-1)*100
    refs.to_csv(OUT/'matched_co2_benchmarks.csv',index=False)
    changes=[]
    for sector,d in refs.groupby('sector'):
        d=d.set_index('year')
        for first,last in [(2005,2020),(2005,2021),(2020,2021)]:
            m=(d.loc[last,'model_ktCO2']/d.loc[first,'model_ktCO2']-1)*100
            o=(d.loc[last,'official_ktCO2']/d.loc[first,'official_ktCO2']-1)*100
            changes.append(dict(sector=sector,period=f'{first}-{last}',model_change_pct=m,
                official_change_pct=o,difference_pp=m-o,same_direction=(np.sign(m)==np.sign(o)) if pd.notna(m) else np.nan,
                calibration_anchor=(last == 2021 and sector != 'Road')))
    changes=pd.DataFrame(changes)
    changes.to_csv(OUT/'matched_co2_changes.csv',index=False)
    mappings={'covered_vs_full_inventory':(annual[LOCAL].sum(axis=1,min_count=len(LOCAL)),official.total_ghg),
              'covered_vs_energy_inventory':(annual[LOCAL].sum(axis=1,min_count=len(LOCAL)),official.energy_ghg),
              'power_vs_energy_industries':(annual.Power,official.energy_industries),
              'transport_vs_domestic_transport':(annual.Transport,official.transport),
              'other_fuel_approximate':(annual[['Industry','Residential','Commercial']].sum(axis=1,min_count=3),official.other_fuel)}
    trends=[];stats=[]
    for name,(m,o) in mappings.items():
        d=pd.concat([m.rename('model_ktCO2'),o.rename('official_ktCO2e')],axis=1).loc[2005:2024].dropna()
        d['model_yoy_pct']=d.model_ktCO2.pct_change()*100
        d['official_yoy_pct']=d.official_ktCO2e.pct_change()*100
        d['yoy_difference_pp']=d.model_yoy_pct-d.official_yoy_pct
        d['comparison']=name
        # Numerical gaps across different boundaries are not estimation errors.
        d['numerical_gap_kt']=d.model_ktCO2-d.official_ktCO2e
        d['numerical_gap_pct']=(d.model_ktCO2/d.official_ktCO2e-1)*100
        trends.append(d.reset_index())
        valid=d.dropna()
        stats.append(dict(comparison=name,start_year=int(d.index.min()),end_year=int(d.index.max()),n_years=len(d),n_yoy=len(valid),
            same_direction_years=int((np.sign(valid.model_yoy_pct)==np.sign(valid.official_yoy_pct)).sum()),
            mean_abs_yoy_difference_pp=valid.yoy_difference_pp.abs().mean(),
            yoy_correlation=valid.model_yoy_pct.corr(valid.official_yoy_pct),
            model_peak_year=int(d.model_ktCO2.idxmax()),official_peak_year=int(d.official_ktCO2e.idxmax()),
            model_2014_2024_pct=(d.loc[2024,'model_ktCO2']/d.loc[2014,'model_ktCO2']-1)*100,
            official_2014_2024_pct=(d.loc[2024,'official_ktCO2e']/d.loc[2014,'official_ktCO2e']-1)*100))
    trend=pd.concat(trends,ignore_index=True)
    stats=pd.DataFrame(stats)
    trend.to_csv(OUT/'annual_trend_reference.csv',index=False)
    stats.to_csv(OUT/'trend_summary.csv',index=False)
    latest=trend[trend.year==official.index.max()]
    latest.to_csv(OUT/'latest_year_reference.csv',index=False)
    fig,axes=plt.subplots(1,3,figsize=(15,4.5))
    panels=[('power_vs_energy_industries','Power / energy industries'),
            ('transport_vs_domestic_transport','Full transport / domestic transport'),
            ('other_fuel_approximate','Industry + homes + commerce / other fuel')]
    for ax,(key,title) in zip(axes,panels):
        d=trend[trend.comparison==key]
        ax.plot(d.year,d.model_ktCO2/1000,label='Model: Mt CO2')
        ax.plot(d.year,d.official_ktCO2e/1000,label='Official: Mt CO2e',ls='--')
        ax.set_title(title,fontsize=10)
        ax.set_xlabel('Year');ax.grid(alpha=.2);ax.legend(fontsize=8)
        ax.xaxis.set_major_locator(MaxNLocator(integer=True,nbins=5))
    fig.suptitle('Annual sector comparison: gas coverage and sector boundaries differ')
    fig.tight_layout()
    fig.savefig(OUT/'annual_sector_reference.png',dpi=180)
    fig.savefig(OUT/'annual_sector_reference.pdf');plt.close(fig)
    # Visuals separate matched CO2 bias from broader GHG trend reference.
    fig,axes=plt.subplots(2,2,figsize=(13,9))
    base=trend[trend.comparison=='covered_vs_full_inventory'].set_index('year')
    axes[0,0].plot(base.index,base.model_ktCO2/base.loc[2014,'model_ktCO2']*100,label='Model: covered CO2')
    axes[0,0].plot(base.index,base.official_ktCO2e/base.loc[2014,'official_ktCO2e']*100,label='Official: all GHG',ls='--')
    axes[0,0].set_title('Broad trend reference: 2014 = 100 (different scope)')
    axes[0,1].bar(base.index-.2,base.model_yoy_pct,width=.4,label='Model: covered CO2')
    axes[0,1].bar(base.index+.2,base.official_yoy_pct,width=.4,label='Official: all GHG')
    axes[0,1].set_title('Year-on-year change (%) — scope differs')
    b=refs[(refs.year==2021)&refs.sector.isin(LOCAL+['International Aviation','International Shipping'])].set_index('sector')
    b.bias_pct.plot.bar(ax=axes[1,0],color=['#4787a8' if not x else '#aaaaaa' for x in b.calibration_anchor])
    axes[1,0].set_title('2021 matched CO2 bias (%) — grey = calibrated')
    c=changes[(changes.period=='2020-2021')&changes.sector.isin(LOCAL)].set_index('sector')
    c[['model_change_pct','official_change_pct']].rename(columns={'model_change_pct':'Model','official_change_pct':'Official CRT'}).plot.bar(ax=axes[1,1])
    axes[1,1].set_title('2020–2021 matched CO2 change (%)')
    for ax in axes.flat: ax.axhline(0,color='gray',lw=.5);ax.grid(alpha=.2,axis='y')
    axes[0,0].legend();axes[0,1].legend()
    for ax in axes[0]: ax.xaxis.set_major_locator(MaxNLocator(integer=True,nbins=7))
    fig.tight_layout()
    fig.savefig(OUT/'comparison.png',dpi=180);fig.savefig(OUT/'comparison.pdf');plt.close(fig)
    write_report(refs,changes,trend,stats)
    inputs=[ROOT/'outputs/hong_kong_sector_monthly.csv',ROOT/'outputs/diagnostics/road_monthly_proxy.csv',ROOT/'data/raw/official_ghg_sector_2024.pdf',ROOT/'outputs/diagnostics/official_baseline_calibration.csv']
    inputs+=sorted((ROOT/'data/raw/inventory/China_BTR1_CRT_2024-12-31_HKSAR').glob('*.xlsx'))
    (OUT/'comparison_manifest.json').write_text(json.dumps({
        'inputs_sha256':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs},
        'official_continuous_series_unit':'ktCO2e AR5; January 2026 version, through 2024',
        'crt_unit':'ktCO2; archived 2024 CRT version for 2005/2020/2021',
        'model_changed':False, 'published_transport_scope':'Road includes residual transport; road + navigation = full 1.A.3','industrial_anchor_years':[2021],
        'transport_scope':'1.A.3; Road is a separate diagnostic, excluded from aggregate sums',
        'transport_calibration_year':2021,
        'official_baseline_year':2021, 'all_published_sectors_calibrated_in_2021':True,
        'code_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()},indent=2))
    print(stats.to_string(index=False))
    print(refs[refs.year==2021][['sector','model_ktCO2','official_ktCO2','bias_pct']].to_string(index=False))
    print(changes[changes.period=='2020-2021'].to_string(index=False))

def write_report(refs,changes,trend,stats):
    def fmt(value, digits=3):
        return '—' if pd.isna(value) else f'{value:.{digits}f}'
    labels={'covered_vs_full_inventory':'本地六部门 / 全清单',
            'covered_vs_energy_inventory':'本地六部门 / 能源小计',
            'power_vs_energy_industries':'电力 / 发电及其他能源工业',
            'transport_vs_domestic_transport':'完整运输 1.A.3 / 官方运输',
            'other_fuel_approximate':'工业＋居民＋商业 / 其他燃料耗用'}
    latest=trend[trend.year==trend.year.max()]
    local=refs[(refs.year==2021)&refs.sector.eq('covered_local_sectors')].iloc[0]
    transport=refs[(refs.year==2020)&refs.sector.eq('Transport')].iloc[0]
    lines=['# 香港清单对比：官方基准与相对活动估算','',
        f'2021 年匹配清单类别的本地合计，模型为 {local.model_ktCO2/1000:.3f} MtCO₂，CRT 为 {local.official_ktCO2/1000:.3f} MtCO₂，差 {local.bias_pct:+.2f}%。',
        f'八部门均采用 2021 CRT 标定，该年吻合属于校准检查；运输 2020 年回溯核查差 {transport.bias_pct:+.2f}%。',
        '本报告所有表格和数值摘要由当前数据生成。缺失部门不补零，2005 年完整运输及本地合计没有可比模型值。','',
        '## 口径和标定依赖','',
        '- Transport 对齐 CRT **1.A.3 总运输 CO₂**，包含本地航运等；Road 仅为原道路输入的单列诊断，绝不再次加入总量。',
        '- Power 对齐 1.A.1.a，Industry 对齐 1.A.2，Commercial/Residential 对齐 1.A.4.a/b；国际航空、航运供油取 Table1.D，单列比较。',
        '- 八部门的 2021 年均为标定锚点；2005/2020 所有部门用于回溯检查，均未用于排放标定。',
        '- 连续官方表是 AR5 全温室气体 CO₂e，不能直接等同于模型 CO₂。能源工业还含煤气制造，全清单还含废弃物、工业过程等。国际供油不在地域清单总量内。',
        '- 完整总量及 Transport 的共同年度范围是 2008–2024；部分其他部门可从 2005 年比较，表中逐项报告时间范围。','',
        f'## {int(latest.year.max())} 年直接对照','',
        '| 对照 | 模型 MtCO₂ | 官方 MtCO₂e | 跨口径数值差额 | 模型同比 | 官方同比 |',
        '|---|---:|---:|---:|---:|---:|']
    for r in latest.itertuples():
        lines.append(f'| {labels[r.comparison]} | {r.model_ktCO2/1000:.3f} | {r.official_ktCO2e/1000:.3f} | {r.numerical_gap_pct:+.2f}% | {r.model_yoy_pct:+.2f}% | {r.official_yoy_pct:+.2f}% |')
    lines+=['','差额为模型数值/官方数值−1，不是同口径误差。官方表有三位有效数字舍入；同比可能与未舍入新闻稿略有差异。','',
        '![年度部门对照](annual_sector_reference.png)','',
        '## 连续年度变化','',
        '| 对照 | 年份 | 同向同比年数 | 平均绝对同比差（百分点） | 同比相关系数 | 2014–2024 模型/官方变化 |',
        '|---|---|---:|---:|---:|---|']
    for r in stats.itertuples():
        lines.append(f'| {labels[r.comparison]} | {r.start_year}–{r.end_year} | {r.same_direction_years}/{r.n_yoy} | {r.mean_abs_yoy_difference_pp:.2f} | {r.yoy_correlation:.3f} | {r.model_2014_2024_pct:+.1f}% / {r.official_2014_2024_pct:+.1f}% |')
    lines+=['','## 匹配类别 CO₂ 核查','',
        '| 年份 | 部门 | 模型 MtCO₂ | CRT MtCO₂ | 差额 % | 直接标定锚点 |',
        '|---|---|---:|---:|---:|---|']
    for r in refs.sort_values(['year','sector']).itertuples():
        lines.append(f'| {r.year} | {r.sector} | {fmt(r.model_ktCO2/1000)} | {fmt(r.official_ktCO2/1000)} | {fmt(r.bias_pct,2)} | {"是" if r.calibration_anchor else "否；合计仍可能含标定项" if r.sector.startswith("covered") else "否"} |')
    lines+=['','## 匹配类别变化','',
        '| 部门 | 时段 | 模型变化 % | CRT 变化 % | 差（百分点） |',
        '|---|---|---:|---:|---:|']
    for r in changes.itertuples():
        lines.append(f'| {r.sector} | {r.period} | {fmt(r.model_change_pct,2)} | {fmt(r.official_change_pct,2)} | {fmt(r.difference_pp,2)} |')
    lines+=['','## 解释','',
        '全运输方法已用清单确定总量基准；年度和月度变化仍依赖道路指数、EMSD 海运能耗及渡轮客流/日历分配。小的锚点偏差不能证明月度变化准确。',
        '电力与供油绝对水平由 2021 CRT 确定，其他年份检验相对变化。活动边界和燃料结构变化仍影响指数；固定校准不能消除时变偏差。',
        '2025 起运输按固定海运强度外推；本次官方清单到 2024 年，故不对更新年份作清单验证。','',
        '![清单比较](comparison.png)','',
        '## 数据和复现','',
        '`matched_co2_benchmarks.csv` 保留源工作簿、工作表、单元格；`annual_trend_reference.csv` 保留逐年数值，`trend_summary.csv` 为统计摘要。',
        f'[官方连续 GHG 部门表]({SOURCE})；CRT 为已缓存的 2024 年提交版本。',
        '运行 `python src/cmhk/analysis/inventory.py`；总量年度趋势图运行 `python scripts/plot_annual_inventory.py`。']
    (OUT/'report.md').write_text('\n'.join(lines)+'\n')

if __name__=='__main__':main()
