# 原始数据下载与导入

下载入口为 `cmhk fetch`，可编辑目录为 `configs/sources.json`。每条记录列出文件名、URL、发布机构和获取方式。运行前用 `cmhk check-inputs` 检查当前版本所需输入。

```bash
# 查看全部下载地址，不发出下载请求
cmhk fetch --list
# 仅下载指定文件；可重复 --only
cmhk fetch --only td_21.csv
# 下载目录内的支持来源；已有且哈希吻合的快照直接复用
cmhk fetch
# 显式更新来源快照；随后重新计算并记录新版本
cmhk fetch --only td_21.csv --refresh
cmhk check-inputs
```

下载记录写入 `data/raw/download_log.json`。失败项保留错误并返回非零状态。每个成功来源有同名 `.source.json`，记录 URL、UTC 获取时间和 SHA-256；缓存校验失败会停止使用，已有但没有来源记录的文件需要先核实。

## 来源与处理字段

| 来源 | 原始文件 | 字段与用途 | 解析入口 |
|---|---|---|---|
| C&SD 915-91201 | `csd_915-91201.json` | `period/freq/sv/USER_TYPEDesc/figure`；月度煤气、分部门用电 | `sources/prepare.py:csd` |
| C&SD 915-91106 | `csd_915-91106.json` | `SALES_TYPEDesc/PROD_TYPE/svDesc/figure`；年度/季度当地及国际供油 | `sources/prepare.py:complete_oil_quarters` |
| C&SD 915-91203 | `csd_915-91203.json` | 本地发电、自用损耗、进出口、电力供应平衡 | `sources/prepare.py:csd` |
| C&SD 915-91001 | `csd_915-91001.json` | 发电投入煤、合并油气热量及电力产出；投入符号在电力模块处理 | `sources/prepare.py:csd` |
| C&SD 历史能源年报 | `csd_energy_2009.pdf` 至 `2013.pdf` | 提取 2005–2012 年燃料供销和发电平衡；保留报告页码 | `sources/historical.py:parse_energy_reports` |
| EMSD | `emsd_<edition>_<table>.csv` | 建筑、工业、运输年度能耗；不同版表号不同，重叠年采用较新版 | `context.py:emsd`、`sectors/industry.py:annual_fuel` |
| 运输署 | `td_31a/b/c.csv`、`td_44.csv`、交通普查 PDF | 固定三隧道车辆类别计数、燃料车辆登记、年度车公里 | `sources/prepare.py:traffic_census`、`sectors/road.py:road_activities` |
| 运输署渡轮 | `td_21.csv` | Ferries 月度千人次；2013 年起分配本地客运海运能耗 | `sectors/navigation.py:ferry_passengers` |
| HKIA | `airport_<year>.pdf` | 月度起降架次；原表按千架次取整 | `sources/prepare.py:airport` |
| 海事处 | `marine_1_m_a1.pdf`、`marine_2_m_a1.pdf` | 海洋/内河船到港数量、净吨位；用于国际航运代理 | `sources/prepare.py:marine` |
| HK Electric | `hke_fuel_mix.csv` | 半年度分燃料送出电量；本地日更合入经核验工作簿 | 本地 `local/ops/automation/workbook.py` |
| 两电资料汇编 | `power/HK_power_generation_2010_2025.xlsx` | CLP 电厂与港灯半年原始工作表；2010 口径独立，半年度不冒充全年 | `sources/power_workbook.py` |
| CRT | `inventory/.../*.xlsx` | 2005、2020、2021 官方燃烧 CO₂ 基准 | `benchmarks/official.py` |
| CEIC | `legacy/HK.xlsx` | 2005–2012 月度汽油、柴油、LPG 总需求代理 | `sources/prepare.py` 末段 |
| IPCC / EPD | 参考 PDF、`configs/model.json` | 排放因子、热值及不确定性参数依据 | `context.py`、`uncertainty/` |

`configs/required_inputs.json` 是当前配置的核心复现要求；`docs/source_inventory.csv` 是本地所有来源快照清单，包含比较或检索背景资料。二者用途不同。

## 需要导入的数据

以下输入仍需要配套数据包或人工获取：

1. **CRT 工作簿**：放入 `data/raw/inventory/China_BTR1_CRT_2024-12-31_HKSAR/`，保留含年份的原始文件名。原始获取日期/URL尚不完整；现有哈希和读取单元格已记录。
2. **CEIC 工作簿**：放入 `data/raw/legacy/HK.xlsx`。现有代码需要其 2005–2012 月度需求列。分发权限尚未确认，公开代码包不包含它。
3. **两电工作簿**：恢复到 `data/raw/power/`。这是逐来源整理的输入汇编，不能用下载一份港灯 CSV 替代整个历史汇编。原始工作表保留各年来源 URL。
4. **可选比较数据**：Climate TRACE API 快照与外部清单工作簿单独恢复；不影响核心排放计算入口。

`check-inputs` 对有来源 sidecar 的文件校验该 sidecar；对缺少 sidecar 的人工输入校验输入合同中的固定哈希。人工修订后先核对来源、保留旧版本，再更新合同。更新基准年份、历史起点或新增数据年度时，应同步复核输入合同。

## 新增来源的步骤

1. 在来源目录中填入真实文件名和地址；下载一个样例，确认内容、单位和字段。
2. 在 `sources/` 中增加标准化解析，保留原始值及转换依据。
3. 将生产必需文件加入输入合同；为解析失败、缺失值和单位变化增加测试。
4. 在对应部门公式中使用标准化数据，运行守恒及覆盖检验。

来源清单保存文件哈希和再分发状态。公开数据包只包含已确认可分发的内容；代码仓库始终提供输入位置及获取要求。
