"""Annual 1.A.3 CO2 proxy from road and domestic-marine changes.

Use CRT baseline category weights, rather than adding the current road fuel
residual to marine emissions as if the two were disjoint measured components.
"""
from pathlib import Path
import hashlib
import json
import os
import re
import numpy as np
import pandas as pd

from cmhk.paths import ROOT, code_hashes
os.environ.setdefault('MPLCONFIGDIR', str(ROOT / '.tmp/matplotlib'))
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.ticker import MaxNLocator
from cmhk.benchmarks.transport import extract_transport
from cmhk.sources.inventory import published_inventory

BASE_YEAR = 2021


def marine_energy(root=ROOT):
    """Use explicit Marine columns only; never relabel early Others as Marine."""
    frames, paths = [], []
    for edition in [2020, 2025, 2026]:
        tables = []
        for table, name in [(58, 'freight_marine_TJ'), (59, 'passenger_marine_TJ')]:
            path = root / f'data/raw/emsd_{edition}_{table}.csv'
            d = pd.read_csv(path).set_index('Year')
            values = pd.to_numeric(d['Marine (Unit : Terajoule)'].astype(str).str.replace(',', '', regex=False), errors='coerce')
            tables.append(values.rename(name))
            paths.append(path)
        frame = pd.concat(tables, axis=1)
        frame['marine_TJ'] = frame[['freight_marine_TJ', 'passenger_marine_TJ']].sum(axis=1, min_count=2)
        frame['emsd_edition'] = edition
        frame['source_tables'] = f'emsd_{edition}_58.csv;emsd_{edition}_59.csv'
        frames.append(frame)
    result = pd.concat(frames)
    result = result[~result.index.duplicated(keep='last')].sort_index()
    if result.marine_TJ.isna().any() or (result.marine_TJ <= 0).any():
        raise ValueError('Missing or non-positive domestic marine energy')
    result.index.name = 'year'
    return result, paths


def proxy_series(road, marine, baseline, base_year=BASE_YEAR):
    """Return a baseline-calibrated aggregate; unsupported years stay missing."""
    if road.index.has_duplicates or marine.index.has_duplicates:
        raise ValueError('Duplicate annual observations')
    if not np.isfinite(road.loc[base_year]) or road.loc[base_year] <= 0 or not np.isfinite(marine.loc[base_year]) or marine.loc[base_year] <= 0:
        raise ValueError('Positive, complete baseline inputs required')
    if any(not np.isfinite(v) or v <= 0 for v in baseline.values()):
        raise ValueError('Positive CRT baseline values required')
    for series in [road, marine]:
        if (series.dropna() < 0).any() or np.isinf(series.dropna()).any():
            raise ValueError('Invalid annual activity')
    if baseline['transport'] < baseline['road'] + baseline['marine']:
        raise ValueError('Transport total cannot be smaller than its road and marine components')
    out = pd.concat([road.rename('road_model_ktCO2'), marine.rename('marine_TJ')], axis=1)
    out['road_index'] = out.road_model_ktCO2 / road.loc[base_year]
    out['marine_index'] = out.marine_TJ / marine.loc[base_year]
    out['road_calibrated_proxy_ktCO2'] = baseline['road'] * out.road_index
    out['marine_calibrated_proxy_ktCO2'] = baseline['marine'] * out.marine_index
    denom = baseline['road'] + baseline['marine']
    out['road_marine_index'] = (out.road_calibrated_proxy_ktCO2 + out.marine_calibrated_proxy_ktCO2) / denom
    out['transport_proxy_ktCO2'] = baseline['transport'] * out.road_marine_index
    out['residual_assumed_proxy_ktCO2'] = (baseline['transport'] - denom) * out.road_marine_index
    out['complete'] = out.transport_proxy_ktCO2.notna()
    out['baseline_year'] = base_year
    out['estimate_label'] = 'Modelled annual proxy; CRT-calibrated'
    out.index.name = 'year'
    # No implicit bridging of missing years when calculating annual change.
    previous = out.transport_proxy_ktCO2.reindex(out.index - 1).to_numpy()
    out['yoy_pct'] = (out.transport_proxy_ktCO2.to_numpy() / previous - 1) * 100
    return out


def main():
    config=json.loads((ROOT/'configs/model.json').read_text())
    if config['transport_proxy']['baseline_year'] != BASE_YEAR:
        raise ValueError('Changing the transport baseline requires revalidating the method')
    out = ROOT / 'outputs/transport_extension'
    out.mkdir(parents=True, exist_ok=True)
    source = ROOT / 'outputs/diagnostics/road_monthly_proxy.csv'
    model = pd.read_csv(source, parse_dates=['date'])
    road = model[model.sector == 'Road'].copy()
    road['year'] = road.date.dt.year
    road = road.groupby('year').ktCO2.agg(['sum', 'count'])
    road = road['sum'].where(road['count'] == 12)
    marine, inputs = marine_energy()
    inventory, totals = {}, {}
    books = sorted((ROOT / 'data/raw/inventory/China_BTR1_CRT_2024-12-31_HKSAR').glob('*.xlsx'))
    for book in books:
        year = int(re.search(r'-V[\d.]+-(\d{4})-', book.name).group(1))
        frame, total = extract_transport(book)
        inventory[year] = frame.set_index('category').official_ktCO2
        totals[year] = total
    anchor = inventory[BASE_YEAR]
    baseline = dict(road=float(anchor['1.A.3.b']), marine=float(anchor['1.A.3.d']), transport=totals[BASE_YEAR])
    result = proxy_series(road, marine.marine_TJ, baseline).join(marine.drop(columns='marine_TJ'))
    result['official_transport_ktCO2'] = pd.Series(totals)
    result['crt_calibration_year'] = result.index == BASE_YEAR
    result['crt_difference_pct'] = (result.transport_proxy_ktCO2 / result.official_transport_ktCO2 - 1) * 100
    official = published_inventory()
    result['official_transport_ktCO2e'] = official.transport
    result['official_ghg_yoy_pct'] = official.transport.pct_change(fill_method=None) * 100
    result.to_csv(out / 'annual_transport_proxy.csv')
    checks = []
    for year, values in inventory.items():
        checks.append(dict(year=year, road_marine_share_pct=(values['1.A.3.b'] + values['1.A.3.d']) / totals[year] * 100,
                           official_total_ktCO2=totals[year], official_marine_ktCO2=values['1.A.3.d'],
                           proxy_total_ktCO2=result.loc[year, 'transport_proxy_ktCO2'],
                           proxy_marine_ktCO2=result.loc[year, 'marine_calibrated_proxy_ktCO2'],
                           calibration_year=year == BASE_YEAR))
    checks = pd.DataFrame(checks).sort_values('year')
    checks.to_csv(out / 'proxy_anchor_checks.csv', index=False)
    inputs += books + [source, ROOT/'configs/model.json', ROOT / 'data/raw/official_ghg_sector_2024.pdf']
    manifest = dict(baseline_year=BASE_YEAR, baseline_ktCO2=baseline,
                    road_weight=baseline['road']/(baseline['road']+baseline['marine']),
                    marine_weight=baseline['marine']/(baseline['road']+baseline['marine']),
                    nonroad_nonmarine_share=1-(baseline['road']+baseline['marine'])/baseline['transport'],
                    method='CRT-weighted road index and EMSD marine-energy index; residual follows composite index',
                    status='Adopted annual 1.A.3 proxy; feeds main monthly Transport',
                    input_sha256={str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs},
                    code_sha256=code_hashes(names=['transport_proxy.py', 'transport_inventory.py', 'compare_inventory.py']))
    (out / 'proxy_manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
    plot(result, out)
    write_report(result, checks, baseline, manifest, out)
    print(result[['transport_proxy_ktCO2','marine_calibrated_proxy_ktCO2','official_transport_ktCO2e','yoy_pct']].tail(8).to_string())
    print(checks.to_string(index=False))


def plot(result, out, summary=None):
    d = result[result.complete]
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.8))
    ax = axes[0]
    ax.plot(d.index, d.transport_proxy_ktCO2/1000, color='#176B87', lw=2.3, label='Full transport proxy (CO2)')
    ax.plot(d.index, d.official_transport_ktCO2e/1000, color='#D28A2D', ls='--', lw=2, label='Official transport (all GHG)')
    refs = result.dropna(subset=['official_transport_ktCO2'])
    ax.scatter(refs.index, refs.official_transport_ktCO2/1000, color='#333333', marker='D', s=35, label='CRT CO2 (2021 = calibration)', zorder=5)
    if summary is not None:
        full=summary[summary.full_year & summary.transport_proxy_ktCO2.notna()]
        forward=full.loc[full.index>=d.index.max()]
        ax.plot(forward.index,forward.transport_proxy_ktCO2/1000,color='#B15B30',ls='--',marker='o',label='Ferry-intensity extrapolation (full years)')
    ax.set_ylabel('Mt CO2 / Mt CO2e');ax.set_title('Annual transport total: gas coverage differs')
    ax = axes[1]
    ax.plot(d.index, d.road_index*100, label='Road index', color='#176B87')
    ax.plot(d.index, d.marine_index*100, label='Domestic marine energy index', color='#D28A2D')
    ax.plot(d.index, d.road_marine_index*100, label='Weighted composite', color='#7C8393', ls='--')
    ax.set_ylabel('2021 = 100');ax.set_title('Components of the transport proxy')
    for ax in axes:
        ax.legend(fontsize=8);ax.grid(alpha=.2);ax.set_xlabel('Year')
        ax.xaxis.set_major_locator(MaxNLocator(integer=True, nbins=6))
    fig.suptitle('Hong Kong 1.A.3 | road + domestic navigation proxy', fontsize=14)
    fig.text(.07,.018,'Complete years only; after 2024: fixed marine intensity. Partial-year totals in monthly summary CSV; not annualized.',fontsize=8)
    fig.tight_layout(rect=[0,.055,1,.94])
    for ext in ['png','pdf']: fig.savefig(out/f'annual_transport_proxy.{ext}',dpi=200)
    plt.close(fig)


def write_report(result, checks, baseline, manifest, out):
    d = result[result.complete]
    latest = d.iloc[-1]
    w = manifest['road_weight']
    lines = ['# 道路＋本地航运：完整 1.A.3 年度变化代理', '',
        '**采用道路和本地航运推算整个运输部门的年度变化，基准年为 2021。该方法已落定：年度基准经月度分配后进入主数据表的 Transport（完整 1.A.3）。**', '',
        '## 方法', '',
        '道路指数 R(y)＝现有道路年度估算(y) / 现有道路年度估算(2021)。',
        '航运指数 M(y)＝EMSD 客运 Marine 与货运 Marine 年能耗之和(y) / 对应 2021 年能耗。',
        '本地航运 CO₂ 代理＝CRT 2021 本地航运 CO₂ × M(y)。其系数是清单/能耗比，不是已知纯燃料排放因子；假定该比值跨年稳定。',
        f'综合指数 I(y)＝{w:.6f} × R(y) ＋ {1-w:.6f} × M(y)。权重由 CRT 2021 道路和本地航运 CO₂ 占两项合计的比例确定。',
        f'完整运输 CO₂(y)＝{baseline["transport"]/1000:.6f} MtCO₂ × I(y)。',
        f'其余航空、铁路燃油和其他运输合计占基准年 {manifest["nonroad_nonmarine_share"]*100:.2f}%，假定随综合指数变化。', '',
        '这与“原道路排放＋海运排放”直接相加不同：道路序列只提供时间变化，基准权重和总量均来自 CRT。',
        '可避免直接把未清晰拆分的道路油品残差与海运当成互不重叠的实测分项相加，但不能消除道路指数中非道路用途造成的趋势污染。', '',
        '## 数据支持范围', '',
        f'年度海运基准支持 {int(d.index.min())}–{int(d.index.max())} 年。新版优先使用 EMSD 2026/2025/2020 表 58、59 的显式 Marine 列。',
        '2005–2007 的旧 Others 未拆出海运，不将其冒充海运；2025 起在月度步骤中按 2024 年客运 TJ/客流和货运 TJ/天外推；累计结果见 `annual_transport_monthly_summary.csv`，本年度基准表不伪造新增基准。',
        '未使用国际 Ship stores、国际航运排放或港口全部到港船次代替本地航运。',
        '月度扩展现由 `src/cmhk/sectors/navigation.py` 实现：客运采用渡轮客流代理、货运采用日历天数，早期客运也采用天数；均为模型分配，见 [月度方法报告](monthly_report.md)。', '',
        '## 清单覆盖与核查', '',
        '| 年份 | 道路＋航运占 1.A.3 | 完整运输代理 MtCO₂ | CRT MtCO₂ | 是否标定年 |',
        '|---|---:|---:|---:|---|']
    for r in checks.itertuples():
        estimate='缺失' if pd.isna(r.proxy_total_ktCO2) else f'{r.proxy_total_ktCO2/1000:.3f}'
        lines.append(f'| {r.year} | {r.road_marine_share_pct:.2f}% | {estimate} | {r.official_total_ktCO2/1000:.3f} | {"是" if r.calibration_year else "否"} |')
    lines += ['', '2021 一致是标定结果；2020 是未用于本次标定的回溯核查，但模型和清单可能共享底层数据，不能称完全独立验证。',
        '2005 两项占比仍可核查，但因海运活动缺失，不能核查本方法当年的估算值。三个锚点约 96% 的覆盖支持将该方法作为候选，不证明其他年份残余部门的趋势相同。', '',
        f'## 最新有年度海运基准的年份：{int(d.index.max())}', '',
        f'- 本地航运代理：{latest.marine_calibrated_proxy_ktCO2/1000:.3f} MtCO₂。',
        f'- 完整运输代理：{latest.transport_proxy_ktCO2/1000:.3f} MtCO₂；同比 {latest.yoy_pct:+.2f}%。',
        f'- 官方运输：{latest.official_transport_ktCO2e/1000:.3f} MtCO₂e；同比 {latest.official_ghg_yoy_pct:+.2f}%。两者气体口径不同。', '',
        '## 使用限制', '',
        '- 非道路残余部门在疫情等时期可能与道路/航运脱钩；需补充更多清单年份或燃料资料检验。',
        '- 海运能耗与清单本地航运可能存在边界、热值和燃料结构差异；固定标定比仅是明确的代理假设。',
        '- 道路原模型的年度燃料拆分、电动化变化和历史版本修订误差仍会传递；道路从 2013 年切换月度代理不等于年度基准同步变化。',
        '- 用 2021 锚点回溯是事后重建，不是实时预测；结果也不能当成三项残余部门各自的观测。',
        '- 不根据官方 2024 全 GHG 运输总量再调参，避免把比较数据直接当拟合目标。', '',
        '![年度运输代理](annual_transport_proxy.png)', '',
        '## 输出与复现', '',
        '- `python src/cmhk/sectors/transport_annual.py`；依赖已生成的道路月度结果及缓存的原始 EMSD/CRT。',
        '- `annual_transport_monthly_summary.csv`：含外推的完整年/部分年运输累计；由月度步骤生成，months 与 full_year 必须一并使用。',
        '- `annual_transport_proxy.csv`：年度基准支持的指数、代理排放、同比、源数据版本、缺失状态和比较值。',
        '- `proxy_anchor_checks.csv`：锚点占比及未标定年份核查。',
        '- `proxy_manifest.json`：基准值、权重、代码及输入 SHA-256。',
        '- 所有 `_ktCO2` 为千吨 CO₂，`_ktCO2e` 为千吨 CO₂ 当量，能耗 `_TJ` 为太焦耳；指数基准年为 1。',
        '- `road_calibrated_proxy_ktCO2` 为道路指数经 CRT 基准缩放后的诊断分量，不是原道路结果；`residual_assumed_proxy_ktCO2` 为随综合指数变化的剩余三类合计。',
        '- `complete` 表示本年度两类输入齐全，不代表统计观测或方法验证完成；空白不等于零。']
    (out/'proxy_report.md').write_text('\n'.join(lines)+'\n')


if __name__ == '__main__':
    main()
