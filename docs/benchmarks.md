# 官方基准与部门映射

唯一映射表是 `configs/sector_mapping.json`，计算读取该文件。2021 为生产校准年，2005 和 2020 为留出核对年。

```bash
cmhk baseline
```

生成 `outputs/diagnostics/sector_benchmarks.csv`，逐条列出年份、部门、官方 ktCO₂、校准/验证身份、源工作簿、工作表、单元格表达式和工作簿 SHA-256。

| 发布部门 | CRT 类别 | 工作表 | CO₂ 列（从 0 起） |
|---|---|---|---:|
| Power | 1.A.1.a | Table1.A(a)s1 | 7（H） |
| Industry | 1.A.2 | Table1.A(a)s2 | 7（H） |
| Road Transport | **1.A.3 合计 − 1.A.3.d** | Table1.A(a)s3 | 7（H） |
| Domestic Navigation | 1.A.3.d | Table1.A(a)s3 | 7（H） |
| Commercial | 1.A.4.a | Table1.A(a)s4 | 7（H） |
| Residential | 1.A.4.b | Table1.A(a)s4 | 7（H） |
| International Aviation | 1.D.1.a | Table1.D | 6（G） |
| International Shipping | 1.D.1.b | Table1.D | 6（G） |

读取按类别行名前缀定位，并要求唯一命中及有限正值。Road Transport 发布账户包含道路和本地航空、铁路直接燃烧、其他运输的剩余项；**不能把它解释为纯道路 1.A.3.b**。纯道路和全运输额外保留为诊断行，供对账使用。

## 校准公式

对电力、居民、商业和两项国际供油，先构造月度代理 P，再计算：

`E[s,m] = B[s,2021] × P[s,m] / Σ(P[s,2021月份])`

要求 2021 十二个月代理完整、非负、总量为正。每条不确定性结构轨迹使用自己的 2021 分母。工业和运输的基准也为 2021，具体分配见 [部门公式](sectors.md)。

2021 年对齐属于校准守恒；2005 和 2020 的差异才用于留出核对。工作表版本、单位和类别边界需和公式一起审阅。

## 汇总边界

- `covered_local_sectors`：Power、Industry、Road Transport、Domestic Navigation、Residential、Commercial。
- `covered_sectors_plus_international_bunkers`：上述六部门，加国际航空和国际航运供油。

两项供油是香港供应的国际燃料，不代表全部在香港境内燃烧。本地六部门合计是所覆盖的直接燃烧范围，未包含全部过程、废弃物等清单来源。

只在范围内所有部门都有值时计算总量；缺失不作零。年度表标明有效月份数和 `full_year`，同比分母使用上年相同月份。

## 修改映射

先编辑 JSON 中的类别行、工作表或显式派生规则，再运行 `baseline` 审阅来源单元格；运输合计需等于五个 1.A.3 子类别之和。改变基准年份还需同时修改方法参数并重审工业、运输和不确定性，现行代码会阻止只改一个年份参数的操作。
