"""Audit full 1.A.3 CO2 coverage before extending the road-only estimator.

Non-road CRT benchmarks are not independently estimated monthly emissions.
A road-model + official-non-road sum is diagnostic only: the current road fuel
residual may contain non-road uses and must be reconciled before production use.
"""
from pathlib import Path
import hashlib
import json
import re
import numpy as np
import pandas as pd
from cmhk.benchmarks.official import crt_value

from cmhk.paths import ROOT, code_hashes
CATEGORIES = {
    '1.A.3.a': ('Domestic aviation', '1.A.3.a.'),
    '1.A.3.b': ('Road transportation', '1.A.3.b.'),
    '1.A.3.c': ('Railways', '1.A.3.c.'),
    '1.A.3.d': ('Domestic navigation', '1.A.3.d.'),
    '1.A.3.e': ('Other transportation', '1.A.3.e.'),
}


def extract_transport(book):
    """Read five top-level transport categories, excluding children and bunkers."""
    frame = pd.read_excel(book, sheet_name='Table1.A(a)s3', header=None)
    labels = frame[1].fillna('').astype(str).str.strip()
    rows = []
    for code, (name, prefix) in CATEGORIES.items():
        # A space following the category dot distinguishes e. from e.i./e.ii.
        hits = frame[labels.str.match('^' + re.escape(prefix) + r'\s')]
        if len(hits) != 1:
            raise ValueError(f'Ambiguous transport category {code} in {book}')
        row = hits.iloc[0]
        value = row[7]
        if not isinstance(value, (int, float, np.number)) or not np.isfinite(value) or value < 0:
            raise ValueError(f'Numeric CO2 benchmark required for {code}: {value}')
        rows.append(dict(category=code, name=name, official_ktCO2=float(value),
                         sheet='Table1.A(a)s3', cell=f'H{int(hits.index[0])+1}'))
    total, _ = crt_value(book, 'Table1.A(a)s3', '1.A.3  Transport')
    if not np.isclose(sum(r['official_ktCO2'] for r in rows), total, rtol=1e-9, atol=1e-6):
        raise ValueError(f'1.A.3 children fail reconciliation: {book}')
    return pd.DataFrame(rows), total


def main():
    out = ROOT / 'outputs/transport_extension'
    out.mkdir(parents=True, exist_ok=True)
    monthly = pd.read_csv(ROOT / 'outputs/diagnostics/road_monthly_proxy.csv', parse_dates=['date'])
    road = monthly[monthly.sector == 'Road'].copy()
    road['year'] = road.date.dt.year
    road = road.groupby('year').ktCO2.agg(['sum', 'count'])
    records, diagnostic, hashes = [], [], {}
    folder = ROOT / 'data/raw/inventory/China_BTR1_CRT_2024-12-31_HKSAR'
    for book in sorted(folder.glob('*.xlsx')):
        match = re.search(r'-V[\d.]+-(\d{4})-', book.name)
        if not match:
            raise ValueError(f'Cannot identify inventory year: {book}')
        year = int(match.group(1))
        frame, total = extract_transport(book)
        source = str(book.relative_to(ROOT))
        frame['year'], frame['source'] = year, source
        frame['share_of_transport_pct'] = frame.official_ktCO2 / total * 100
        records.append(frame)
        hashes[source] = hashlib.sha256(book.read_bytes()).hexdigest()
        nonroad = frame.loc[frame.category != '1.A.3.b', 'official_ktCO2'].sum()
        model_road = road.loc[year, 'sum'] if year in road.index and road.loc[year, 'count'] == 12 else np.nan
        reference_road = frame.loc[frame.category == '1.A.3.b', 'official_ktCO2'].item()
        diagnostic.append(dict(year=year, model_road_ktCO2=model_road,
            official_road_ktCO2=reference_road, official_nonroad_ktCO2=nonroad,
            official_transport_ktCO2=total, nonroad_share_pct=nonroad / total * 100,
            diagnostic_model_road_plus_official_nonroad_ktCO2=model_road + nonroad,
            diagnostic_difference_pct=((model_road + nonroad) / total - 1) * 100,
            production_ready=False,
            limitation='Hybrid diagnostic; official non-road inputs; unresolved overlap in model road fuel residual'))
    if not records:
        raise ValueError('No CRT workbooks found')
    benchmarks = pd.concat(records, ignore_index=True).sort_values(['year', 'category'])
    benchmarks.to_csv(out / 'crt_transport_components.csv', index=False)
    diagnostics = pd.DataFrame(diagnostic).sort_values('year')
    diagnostics.to_csv(out / 'annual_extension_diagnostic.csv', index=False)
    gaps = [
        ('1.A.3.a', 'Domestic aviation', 'CRT annual anchors only',
         'Domestic flight/heli fuel or activity; exclude international aircraft stores and check boundary of cross-border flights'),
        ('1.A.3.b', 'Road transportation', 'Current monthly model',
         'Reconcile fuel residual: non-road liquid uses must be removed before adding their emissions separately'),
        ('1.A.3.c', 'Railways', 'CRT direct-combustion annual anchors only',
         'Diesel/direct fuel use; do not add electricity generation emissions already in Power'),
        ('1.A.3.d', 'Domestic navigation', 'CRT anchors; EMSD annual marine energy from newer editions',
         'Fuel split/heat basis and local monthly vessel activity; ocean/river arrivals are not a validated domestic fuel proxy; early Others is not a marine-only series'),
        ('1.A.3.e', 'Other transportation', 'CRT Off-road annual anchors; pipeline marked NO in cached tables',
         'Off-road fuel/activity and sector allocation; do not equate EMSD passenger Others to CRT Other transportation'),
    ]
    pd.DataFrame(gaps, columns=['category', 'name', 'available', 'required']).to_csv(out / 'coverage_and_gaps.csv', index=False)
    hashes['outputs/diagnostics/road_monthly_proxy.csv'] = hashlib.sha256((ROOT / 'outputs/diagnostics/road_monthly_proxy.csv').read_bytes()).hexdigest()
    code = code_hashes(names=['transport_inventory.py'])
    (out / 'manifest.json').write_text(json.dumps(dict(inputs_and_code_sha256={**hashes, **code},
        unit='ktCO2, not CO2e', source_version='China BTR1 CRT 2024',
        audit_only=True, scope='1.A.3.a through 1.A.3.e; excludes Table1.D international bunkers',
        status='Coverage audit and annual hybrid diagnostic; not a completed monthly transport model'), indent=2) + '\n')
    lines = ['# 1.A.3 Transport 扩展核对', '',
        '目标：从现行道路交通扩展到完整 1.A.3 的直接燃烧 CO₂。国际供油仍属于单列项目，铁路用电排放不在此重复加入。', '',
        '**当前产物为清单分项提取和年度混合诊断，本页的直接相加诊断不用于主结果；主结果采用另行落定的合成指数方法。**',
        '现有 CRT 只有 2005、2020、2021 年锚点。其他年份及非道路月度分配缺少足够输入，不做隐含插值、不把缺失当零。', '',
        '## 清单分项（MtCO₂）', '',
        '| 年份 | 本地航空 | 道路 | 铁路燃油 | 本地航运 | 其他运输 | 1.A.3 合计 |',
        '|---|---:|---:|---:|---:|---:|---:|']
    for year, frame in benchmarks.groupby('year'):
        v = frame.set_index('category').official_ktCO2 / 1000
        lines.append(f'| {year} | ' + ' | '.join(f'{v[c]:.4f}' for c in CATEGORIES) + f' | {v.sum():.4f} |')
    lines += ['', '## 年度混合诊断（不能作为新增主结果）', '',
        '仅计算“原道路估算＋官方非道路清单值”，用于量化扩展规模。非道路项来自清单，不能据此声称独立验证成功。', '',
        '| 年份 | 原道路估算 MtCO₂ | 官方非道路 MtCO₂ | 混合诊断 MtCO₂ | 官方全运输 MtCO₂ | 数值差额 |',
        '|---|---:|---:|---:|---:|---:|']
    for r in diagnostics.itertuples():
        lines.append(f'| {r.year} | {r.model_road_ktCO2/1000:.3f} | {r.official_nonroad_ktCO2/1000:.3f} | {r.diagnostic_model_road_plus_official_nonroad_ktCO2/1000:.3f} | {r.official_transport_ktCO2/1000:.3f} | {r.diagnostic_difference_pct:+.2f}% |')
    lines += ['', '## 完整计算前必须解决的口径', '',
        '1. 现行道路柴油＝运输油品−海运能耗−汽油；该残差不保证已剔除铁路燃油、航空和非道路用途。直接加四项存在重复计算风险。应先取得运输方式×燃料的能量分解，再分别计算。',
        '2. EMSD 2017 版 Others 被旧代码用于非道路扣除，不应视为已识别的海运量。新版 passenger Others 也不等于 CRT 1.A.3.e 的 Off-road。',
        '3. 本地航运不能直接使用国际 Ship stores 或港口全部到港船次替代；铁路 Rail 总能耗不能全部乘燃油因子。',
        '4. 本地航空需识别清单国内/国际边界；机场总起降和全部航空供油不能直接归入本地航空。',
        '5. 每个子项需有年度燃料基准、月度分配依据、来源和覆盖标记；全部子项齐全才生成完整运输合计。', '',
        '代码：`python src/cmhk/benchmarks/transport.py`。分项 CSV 保留源工作簿、工作表、单元格和份额；manifest 保存文件哈希。',
        '主结果的 `Transport` 已采用道路＋本地航运合成代理。本页是清单覆盖审计；采用的方法见 [年度方法](proxy_report.md)和[月度方法](monthly_report.md)。', '',
        '文件：`crt_transport_components.csv`、`annual_extension_diagnostic.csv`、`coverage_and_gaps.csv`。']
    (out / 'report.md').write_text('\n'.join(lines) + '\n')
    print(diagnostics.to_string(index=False))


if __name__ == '__main__':
    main()
