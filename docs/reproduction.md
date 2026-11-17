# 分步复现与日常维护

## 当前版本复现

从配套原始数据包恢复 `data/raw/`，或先下载可获取来源并导入人工输入。保留同名 `.source.json`。方法参数、时间范围、不确定性设定和部门/来源目录统一位于 `configs/`。

```bash
cmhk check-inputs  # 缺文件、来源哈希不符时停止
cmhk prepare       # PDF/API/工作簿 → data/processed
cmhk baseline      # CRT → diagnostics/sector_benchmarks.csv
cmhk estimate      # 分部门代理 → 选定方法 → 校准 → 月度/年度点估计
cmhk uncertainty   # 情景及固定种子蒙特卡洛 → 区间
cmhk validate      # 总量、覆盖、非负、未来月份、守恒和区间
cmhk export        # publication/MCE_HK_monthly.csv
```

以上顺序合并为 `cmhk run --test`。整条核心流程不刷新来源、不调用网站、不执行论文脚本。每个阶段在独立 Python 进程运行，阶段起止与返回码保存在 `outputs/provenance/pipeline.json`；失败会停止后续步骤。

```bash
cmhk run --report                 # 另生成报告和主图
cmhk run --comparisons            # 另运行官方/Climate TRACE 比较，需要比较输入
cmhk compare                      # 已有点估计时单独比较
cmhk --workspace /path/to/workspace run
```

`--workspace` 选择含 `configs/model.json`、`configs/uncertainty.json`、`configs/` 和 `data/` 的工作目录。核心运行只要求当前版本的输入，不依赖预先存在的标准化数据或输出。代码源码目录/安装环境与数据工作目录可以分开。

## 更新一个来源

1. 保留当前来源及对应结果版本。
2. 执行 `cmhk fetch --only <文件名> --refresh`，检查来源记录和字段、单位。
3. 运行 `cmhk check-inputs`。人工汇编变更需核对来源并更新输入合同；有 sidecar 的来源按 sidecar 哈希校验。
4. 运行 `cmhk run --test`，核对新增月份、历史修订与暂估标记。
5. 如需更新网站，再运行本地网站更新/部署流程。计算完成与网站发布是两项独立操作。

下载端点目录列出当前接受的年份和版次。新增年度机场文件、EMSD 新版表格时，需要明确添加目录及输入要求，并核对表义；单改日历截止时间不会自动接受新版表格。

## 测试分层

- 默认算法测试：`pytest -m 'not integration and not comparison and not research'`，使用构造数据及小型样例，CI 可运行。
- 核心回归：`cmhk run --test`，重建后检查真实缓存数据，包含历史回归、不确定性和来源记录。
- 比较结果：`pytest -m comparison`，需先生成对应比较输出。
- 论文图表：标记 `research`，依赖本地研究材料。
- 网站与部署：`local/tests/`，独立于公开计算代码。

现有历史回归样例为固定版本；新增月份后如需调整快照断言，应先确认方法及数值差异，避免只改测试以消除失败。

## 重构验证

在新目录只放计算源码、配置、测试和输入包，保持 `outputs/`、`data/processed/` 初始为空。完成核心流程后比较三张主 CSV、区间表、数据产品、缺失位置和守恒结果。代码路径调整会改变来源清单中的代码哈希，排放值与区间应保持一致。
