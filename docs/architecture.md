# 工程结构与维护入口

本项目计算香港月度直接燃烧 CO₂，发布八个部门、六部门本地合计及含国际供油合计。单位为 ktCO₂。核心包为 `src/cmhk/`。

```text
configs/sources.json                 下载文件名、URL、发布机构
configs/required_inputs.json         当前版本的复现输入要求
configs/model.json                         时间范围、排放因子和方法选择
configs/sector_mapping.json          CRT 基准、部门边界、汇总范围
configs/uncertainty.json              误差分布、随机种子、抽样次数

src/cmhk/
  sources/                          下载、PDF/API/工作簿解析和输入检查
  benchmarks/                       CRT 单元格读取、运输类别核对
  sectors/                          按部门组织的活动代理与计算公式
  context.py                        单次运行的配置、单位换算和一致性记录
  kernels.py                        守恒分配、发电拆分、留出检验
  estimation.py                     部门计算顺序
  assembly.py                       选定方法、2021 校准、结果表组装
  aggregation.py                    部门范围与完整合计
  nowcast.py                        缺失季度暂估、电力强度与两电更新
  uncertainty/                      情景轨迹、蒙特卡洛和联合汇总
  validation.py                     缺失、守恒、总量及区间检查
  export.py                         对外月度数据产品
  analysis/                         可选报告及清单比较
  pipeline.py, cli.py                统一运行入口
```

## 数据流

```text
下载或导入原始快照
  → sources.prepare：标准化单位、日期和字段
  → benchmarks.official：读取 CRT 并导出来源单元格
  → sectors：构造月度燃料/活动代理
  → nowcast：补足有活动支持的近期暂估
  → assembly：选择方法、按 2021 基准校准、组装八部门
  → uncertainty：传播误差并先汇总抽样、后取分位数
  → validation：检验缺失、守恒、边界和区间
  → export：发布月度 CSV
```

网站和论文读取结果，不参与核心计算。`local/web/scripts/power_workbook.py` 现在只是调用计算包的适配入口。两电原始工作簿位于 `data/raw/power/`。

## 文件的职责

- `data/raw/`：原始输入和 `.source.json` 来源记录；按版本保存，刷新下载必须显式指定。
- `data/processed/`：标准化缓存，可以从原始输入重建。
- `outputs/diagnostics/`：基准、燃料分量、情景和守恒检验；部分是后续计算的阶段输入。
- `outputs/provenance/`：参数、代码/输入哈希、阶段执行记录。
- `outputs/near_realtime/history/`：已发布估计及修订记录，属于追溯资料。
- `outputs/publication/`：月度 CSV 数据产品。
- `local/archive/`：整理前备份和历史研究；不进入代码发布包。
- `local/`：网站、卫星研究、部署、本地测试和历史材料，整目录由 Git 忽略。

`src/` 仅保留 `cmhk/` 计算包；旧命令兼容入口归档到 `local/legacy/src/`。本地日更任务直接运行计算包模块。

## 修改顺序

1. 新增数据来源：编辑来源目录，增加解析和来源校验，参见 [原始数据](acquisition.md)。
2. 调整类别归属：编辑部门映射，检查 `baseline` 导出的单元格和基准，参见 [基准映射](benchmarks.md)。
3. 调整部门模型：修改对应 `sectors/` 模块及参数，参见 [部门公式](sectors.md)。
4. 执行相应单元测试，再重建并检查完整结果；方法变化应独立记录版本。

旧路径兼容用于保留现有本地日更任务。部署入口与计算入口分开：`cmhk run` 完全使用 Python 和缓存输入；现有日更任务另行负责检查来源及发布网站。

## GitHub 范围

`.gitignore` 忽略 `/local/`、`/data/`、`/outputs/`、`/.tmp/`、环境和生成缓存。计算源码、配置、现行文档和测试默认可以跟踪。新增计算文件无需修改导出白名单。

Git 只上传提交过的文件；忽略规则作用于未跟踪文件，已经跟踪的文件需要先从索引移除。项目使用独立 Git 仓库，远程地址为 `git@github.com:zhudeng94/MCE-HK.git`，主分支为 `main`。

现有定时任务路径 `scripts/daily_update.sh` 保留为转发脚本，其实现、设置和网站均位于 `local/`。该转发脚本也由 Git 忽略。
