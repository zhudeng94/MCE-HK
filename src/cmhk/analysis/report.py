"""Report the single proxy estimate requested by the user."""
from pathlib import Path
import os
import json
import pandas as pd
from cmhk.paths import ROOT, code_hashes
os.environ.setdefault('MPLCONFIGDIR',str(ROOT/'.tmp/matplotlib'))
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
OUT=ROOT/'outputs'

def main():
    (OUT/'figures').mkdir(parents=True, exist_ok=True)
    sectors=pd.read_csv(OUT/'hong_kong_sector_monthly.csv',parse_dates=['date'])
    monthly=pd.read_csv(OUT/'hong_kong_total_monthly.csv',parse_dates=['date'])
    annual=pd.read_csv(OUT/'hong_kong_total_annual.csv')
    sector_bands=pd.read_csv(OUT/'uncertainty/sector_monthly_uncertainty.csv',parse_dates=['date'])
    total_bands=pd.read_csv(OUT/'uncertainty/total_monthly_uncertainty.csv',parse_dates=['date'])
    sectors=sectors.merge(sector_bands[['date','sector','lower_95_ktCO2','upper_95_ktCO2']],
                          on=['date','sector'],validate='one_to_one')
    monthly=monthly.merge(total_bands[['date','scope','lower_95_ktCO2','upper_95_ktCO2']],
                          on=['date','scope'],validate='one_to_one')
    calibration=pd.read_csv(OUT/'diagnostics/official_baseline_calibration.csv')
    baseline_year=json.loads((ROOT/'configs/model.json').read_text())['official_baseline']['year']
    anchors=pd.read_csv(OUT/'diagnostics/industry_proxy_calibration.csv')
    names={'covered_local_sectors':'本项目本地部门合计','covered_sectors_plus_international_bunkers':'含国际运输供油合计'}
    rows=[]
    for r in annual.itertuples():
        if r.months == 0:
            continue
        yoy='—' if pd.isna(r.yoy_same_months_pct) else f'{r.yoy_same_months_pct:+.2f}%'
        rows.append(f'| {r.year} | {names[r.scope]} | {r.months} | {r.ktCO2/1000:.3f} | {yoy} |')
    report='''# 香港月度 CO₂：单一基准估算与部门合计

主结果以 2021 年官方 CRT CO₂ 清单确定排放水平，以年度/季度统计刻画相对变化，以月度活动分配。
电力、居民、商业、国际航空和航运由旧活动模型按各部门固定系数校准；工业和运输保留原 CRT 标定。
本版在官方基准上增加季度统计公布前的月度活动暂估、经留出回测选择的航运代理及电力强度情景；暂估随新统计修订。
[暂估方法与留出回测](near_realtime/report.md)；主表 temporal_status 区分统计约束、强度外推和季度活动暂估。
情景对照另存诊断文件，不是置信区间。
索引保留 **2005–2026**；完整部门合计覆盖 **2008-01 至 2026-06**。近期原模型观测截止 **2026-10-13**；渡轮客流为新增快照，具体获取时间见源文件旁的 `.source.json`。
运输拆为 Road Transport（1.A.3.b 加其余运输项）和 Domestic Navigation（1.A.3.d），相加保持完整 1.A.3。2005–2007 缺少海运基准，本地航运及完整总量留空，道路含剩余项可单列。2025 起按 2024 年海运客运 TJ/客流及货运 TJ/天外推，运输可到 2026-07；完整总量当前由运输覆盖限制，电力及国际供油通过活动暂估已延至 2026-08。
工业采用 EMSD 年度非电力燃料能耗约束，以 2021 CRT 校准；煤气和用电只用于分月及近期外推。

## 结果

- [月度部门值](hong_kong_sector_monthly.csv)：264 个月 × 7 部门，单位 ktCO₂。
- [逐月 95% 不确定性与方法](uncertainty/report.md)：10 万次蒙特卡洛传播，条件于显式输入误差及模型概率假设，未验证实际置信覆盖率。
- [月度 Hong Kong total](hong_kong_total_monthly.csv)：两种口径的单一值及同比。
- [年度及部分年份合计](hong_kong_total_annual.csv)：包含月数与同月范围同比。
- [工业分项](diagnostics/industry_proxy_components.csv)、[工业标定参数](diagnostics/industry_proxy_calibration.csv)。

本项目本地部门合计＝电力＋工业燃烧＋道路运输＋本地航运＋居民＋商业。
含国际运输供油合计＝以上五部门＋国际航空供油＋国际航运供油。
未包含煤气制造、工业过程等全部来源，因此本地部门合计**不是完整香港地域清单总量**。
国际供油排放也不等于在香港境内发生的排放。只有全部部门有值时才汇总。
共同覆盖 **2008-01 至 2026-06**。其他部门仍保留有数据支持的早期和近期月份；缺失运输的月份不生成完整总量。年度表保留缺失年份，months=0、ktCO2 留空。

| 年份 | 口径 | 月数 | MtCO₂ | 同月范围同比 |
|---|---|---:|---:|---:|
'''+ '\n'.join(rows)+'''

![总量](figures/hong_kong_total.png)

## 官方基准和相对活动

`E(s,y,m) = CRT(s,2021) × P(s,y,m) / sum_m P(s,2021,m)`。
P 为原燃料/活动综合指标。全年齐全时，等价于“官方基准 × 年度活动指数 × 月度权重”；部分年直接逐月计算，不归一化到全年。
固定校准保持部门同比和月内形状；各部门权重变化会影响合计同比。校准系数包含统计边界及转换差异，不是物理排放因子。
每个敏感性方案均以自身的 2021 年活动量分别校准。年度/季度能源统计约束的是活动，2021 CRT 约束排放水平。
国际供油统计作为相应 CRT 类别的活动代理；单年校准不能消除供油/航程边界随时间变化的风险。
八部门统一使用 2021 排放基准；工业年度变化由非电力燃料能耗决定。

BASELINE_TABLE

[逐部门基准、原值、校准系数及来源](diagnostics/official_baseline_calibration.csv)；
[新旧年度/部分年排放、同比与合计对照](diagnostics/baseline_calibration_comparison.csv)；
[校准前活动模型月度值](diagnostics/sector_monthly_before_baseline_calibration.csv)。
2021 吻合为标定；2005/2020 各类别可供回溯比较，不能用校准后的 2021 零偏差证明准确。

## 完整运输（1.A.3）：已落定方法

2021 年 CRT 给出道路和本地航运合计占运输 CO₂ 的 96.41%。用该年两项 CO₂ 的相对份额作为权重：

```
R_y = 原道路年度代理(y) / 原道路年度代理(2021)
M_y = EMSD 客运与货运 Marine 能耗(y) / Marine 能耗(2021)
道路（含剩余项）CO₂(y) = (CRT 2021 全运输 − CRT 2021 本地航运) × R_y
本地航运 CO₂(y) = CRT 2021 本地航运 × M_y
全运输 CO₂(y) = 道路（含剩余项）CO₂(y) + 本地航运 CO₂(y)
```

月度道路沿用已有变化，经 CRT 道路基准缩放；海运客运从 2013 年起按运输署 Ferries 月度客流分配年度能耗，货运按天数分配。
2008–2012 海运客运也按天数分配。其余航空、铁路燃油、其他运输约 3.59% 随道路活动变化，并全部并入 Road Transport。
Road Transport = 道路标定值 + 剩余运输；Domestic Navigation = 海运标定值。两项合计覆盖完整运输；仅 2021 年保持清单总量。
铁路用电的发电排放不重复加入；国际航空、航运供油仍单列。

2025 起海运客运能耗＝2024 年客运能耗/全年客流 × 当月客流；货运能耗＝2024 年货运能耗/366 × 当月天数。无道路或渡轮活动的月份留空。

这是一种代理估算：客流不等于燃油，货运月度季节性尚未观测，残余部门未逐项估计。道路油品残差的边界近似仍会影响指数。
2021 全运输吻合属于标定，不是独立验证。每年全部月值严格保持原年度基准。
道路原始序列保存在 `diagnostics/road_monthly_proxy.csv`，不再次加入总量。

- [月度方法与分配敏感性](transport_extension/monthly_report.md)
- [年度方法及清单锚点检查](transport_extension/proxy_report.md)
- [月度运输分量](transport_extension/monthly_transport_proxy.csv)

## 工业计算

EMSD 工业年度非电力能耗 F(y) = 煤气及石油气 + 油及煤产品（TJ）。电力从年度燃料总量中排除。
各版本逐年拼接，重叠年份优先新版；2017/2020/2024/2025/2026 版覆盖 2005–2024 年。

```
k = CRT 工业燃烧 CO₂(2021) / F(2021)
E(y) = k × F(y)
```

煤气/LPG 按月度工业煤气分配，油/煤按月度工业用电分配；各分项保持年度燃料总量。
2025 年起沿用 2024 年各燃料组与对应年度活动的比例，逐月估算。
2005 和 2020 年清单不参与标定，留作验证。

[年度燃料与来源](diagnostics/industry_annual_fuel.csv)；[月度分配](diagnostics/industry_proxy_components.csv)。

## 其他部门的单一基准选择

| 部门 | 采用的方法 |
|---|---|
| 居民、商业 | 2021 CRT 基准 × 煤气及其他燃料综合活动相对变化，按煤气月度比例分配。居民 <1 TJ/横线项按可忽略处理，不额外添加任意微量燃料。 |
| 运输 1.A.3 | 道路＋本地海运综合指数；海运客运按渡轮客流分月、货运按天数，2021 CRT 标定。 |
| 国际航空供油 | 2021 CRT 基准 × 供油综合指数，季度供油按月起降架次分配；Q4＝年度减前三季度，未公布时用最近四季度比例暂估。 |
| 国际航运供油 | 2021 CRT 基准 × 供油综合指数，季度供油按留出回测选定的船舶活动代理分配；缺季度值时按最近四季度供油/活动比例暂估。 |
| 电力 | 2021 CRT 基准 × 年度燃料综合指数，季度发电约束、固定年度燃料份额；月用电引导，不额外设定无法识别的季节调度。 |

## 2005–2012 的历史重建

早期数据不能沿用近期相同频率，以下替代方法在部门 CSV 的 `method` 字段单独标明：

- 航空/航运：从统计处 2009–2013 能源年报提取 2005–2012 **年度**分燃料供油，按机场月起降/海事处月到港量分配；2013 起改用季度供油约束。
- 电力：年报提供年度煤与油/气投入、本地发电；按月用电分配年度本地发电。早期没有逐季进出口/损耗约束，不能声称月度燃料结构被观测。
- 道路：年度能耗基准仍来自 EMSD 和本地汽油销售；2005–2012 用项目已有 CEIC 月度汽油、柴油、LPG 需求作分燃料 proxy。
  它是全用途油品需求，不是道路专属燃料消费；2013 起才使用固定隧道交通面板、领牌燃料比例和年度 VKT。
- 居民/商业：补充 EMSD 2017/2020/2025 版历史年度基准，重叠年份优先选新版。2017 版表 48/49 对应新版表 03/04，不能直接按表号拼接。
- 2005–2007 运输旧表的“其他”未单列本地船运，计算道路油量时扣除该整个非主要道路用途组，仍有口径近似。

年报油品表通过逐燃料“本地销售＋转口＋船舶供油＋航空供油＝总销售”检查；年报原值、版本和 PDF 页码保存在
`data/processed/historical_fuel_benchmarks.csv` 与 `historical_energy_balance.csv`。跨出版版本修订、代理变化可影响 2012/2013 接缝，不能解释为纯粹真实排放突变。

统计处部分煤气/用电资料可到 1979 年，但本项目当前工业年度燃料序列始于 2005，
且更早道路燃料和其他部门基准尚未完成同口径接入。因此部分部门可以从 2005 年估算；完整运输受海运基准限制，**现行主结果的共同起点为 2008 年**。
不能仅凭某一活动序列更长，就把所有部门总量延至 1979 年。

这是一条明确的方法选择，不是从不同计算路径平均得到的“最佳值”。
**电力和道路仍有较强假设，输出单一值不代表限制已解决**：电力把统计处油/气合并投入暂按天然气处理，
使用固定效率推断发电份额。两电年度/半年资料作为强度更新代理，月度分燃料发电仍缺乏完整观测。道路年度分燃料使用 EMSD 运输组减本地船运、
汽油销售和剩余柴油的拆分近似。居民/商业 LPG 使用合并气体减煤气残差，仍有沼气与边界误差。
其他非运输部门在 2025–2026 缺少 EMSD 年度值时沿用原外推方法；电力 2026 使用 2025 热量/发电强度。完整运输从 2025 年起按固定海运强度和当月渡轮客流外推，不强制保持 2024 年总量。2026 合计为 1–6 月累计，同比分母使用上年同月。

## 核验和复现

八部门 2021 月值加总均重现对应 CRT CO₂；2005/2020 留作验证。年度吻合仅是计算一致性，不是独立验证。
每月 total 严格等于所选部门值之和，缺失部门不补零；运输有效至 2026-07，完整部门总量有效至 2026-06；2026 不年化。
配置见 `configs/model.json` 的 `point_estimate_sector_methods`；工业源单元格与哈希见 `provenance/point_estimate_manifest.json`。
主结果使用本报告列出的 `hong_kong_*.csv`，旧敏感性输出只作为内部核查资料。

运行 `python src/cmhk/estimation.py` 和 `python src/cmhk/analysis/report.py`；测试 `python -m pytest -q`。
原始数据均已缓存，来源为统计处、EMSD、运输署、海事处、HKIA，以及项目保存的香港 CRT 工作簿。

![部门趋势](figures/monthly_emissions.png)
'''
    baseline_rows = ['| 部门 | 官方 2021 ktCO₂ | 校准前 2021 ktCO₂ | 校准系数 |', '|---|---:|---:|---:|']
    baseline_rows += [f'| {r.sector} | {r.official_ktCO2:.3f} | {r.proxy_baseline_ktCO2:.3f} | {r.scale:.6f} |' for r in calibration.itertuples()]
    report = report.replace('BASELINE_TABLE', '\n'.join(baseline_rows))
    if baseline_year != 2021:
        raise ValueError('Review report and historical calibration before changing baseline year')
    valid=monthly.dropna(subset=['ktCO2'])
    counts=valid.groupby('date').scope.nunique()
    common=counts[counts.eq(len(names))].index
    first_month,last_month=common.min().strftime('%Y-%m'),common.max().strftime('%Y-%m')
    transport_end=sectors.loc[sectors.sector.eq('Domestic Navigation')&sectors.ktCO2.notna(),'date'].max().strftime('%Y-%m')
    report=report.replace('2008-01 至 2026-06',f'{first_month} 至 {last_month}')
    report=report.replace('2026-07',transport_end).replace('2026-06',last_month)
    report=report.replace('2005–2026',f'{sectors.date.dt.year.min()}–{sectors.date.dt.year.max()}')
    report=report.replace('2026-10-13',str(sectors.as_of.iloc[0]))
    report=report.replace('264 个月',f'{sectors.date.nunique()} 个月')
    report=report.replace('2022–2026 沿用',f'2022–{sectors.date.dt.year.max()} 沿用')
    report=report.replace('其他非运输部门在 2025–2026 缺少 EMSD 年度值时','其他非运输部门在缺少 EMSD 年度值时')
    report=report.replace('电力 2026 使用 2025 热量/发电强度','电力在缺少年度燃料投入时使用最近完整年度热量/发电强度')
    report=report.replace('2026 合计为 1–6 月累计，同比分母使用上年同月','最新年份仅累计已有完整月份，同比分母使用上年同月')
    report=report.replace('2026 不年化','部分年份不年化')
    (OUT/'report.md').write_text(report)
    fig,axes=plt.subplots(2,1,figsize=(11,7),sharex=True)
    for ax,scope in zip(axes,names):
        s=monthly[(monthly.scope==scope)&monthly.ktCO2.notna()]
        ax.fill_between(s.date,s.lower_95_ktCO2/1000,s.upper_95_ktCO2/1000,
                        color='#db923a',alpha=.30,label='95% uncertainty interval')
        ax.plot(s.date,s.ktCO2/1000,color='#195e7b',lw=1.5,label='Published estimate')
        ax.set_title('Covered local sectors' if scope=='covered_local_sectors' else 'Covered sectors + international bunker fuels',loc='left')
        ax.set_ylabel('Mt CO2 / month'); ax.grid(alpha=.2)
        ax.legend(loc='upper right',fontsize=8,frameon=False)
    fig.suptitle('Hong Kong | monthly totals with 95% uncertainty intervals')
    fig.text(.1,.015,'Shading: model-based 95% interval. Shared Monte Carlo draws summed before quantiles; not a full territorial inventory.',fontsize=8)
    fig.tight_layout(rect=[0,.04,1,.95])
    for ext in ['png','pdf']: fig.savefig(OUT/f'figures/hong_kong_total.{ext}',dpi=180)
    plt.close(fig)
    fig,axes=plt.subplots(4,2,figsize=(12,11),sharex=True)
    for ax,(sector,s) in zip(axes.flat,sectors.groupby('sector',sort=False)):
        ax.fill_between(s.date,s.lower_95_ktCO2/1000,s.upper_95_ktCO2/1000,
                        color='#db923a',alpha=.30,label='95% uncertainty interval')
        ax.plot(s.date,s.ktCO2/1000,color='#195e7b',lw=1.1,label='Published estimate'); ax.set_title(sector,loc='left')
        ax.set_ylabel('Mt CO2 / month'); ax.grid(alpha=.2)
    # Eight sectors fill all panels.
    fig.legend(*axes.flat[0].get_legend_handles_labels(),loc='lower center',ncol=2,frameon=False)
    fig.suptitle('Monthly sector estimates | 95% uncertainty intervals')
    fig.text(.07,.012,'Intervals are conditional on configured input distributions and model weights.',fontsize=9)
    fig.tight_layout(rect=[0,.035,1,.96])
    for ext in ['png','pdf']: fig.savefig(OUT/f'figures/monthly_emissions.{ext}',dpi=180)
    plt.close(fig)
    print(annual[annual.year.isin([2024,2025,2026])].to_string(index=False))

if __name__=='__main__': main()
