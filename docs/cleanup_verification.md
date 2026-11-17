# 整理与验证记录 — 2026-11-17

本轮按下载、标准化、CRT 映射、部门公式、汇总、不确定性及检查重组计算代码，保持现行方法参数与数据结果。

## 迁移记录

- 计算实现迁入 `src/cmhk/`，原 `src/*.py` 为本地兼容入口。
- `estimate.py` 中的建筑、道路、国际供油和电力公式拆入 `sectors/`；每次计算使用独立 `EstimationContext`。
- 两电工作簿从 `outputs/` 迁至 `data/raw/power/`；解析从网站迁入 `sources/power_workbook.py`。网站通过适配入口调用计算包。
- 下载地址抽出为 `configs/sources.json`；CRT 读取与部门汇总范围统一由 `configs/sector_mapping.json` 控制。
- 核心复现与报告、比较、论文、网站部署分开；有数据与无数据测试分层。
- 公开代码采用明确文件清单导出，附逐文件 SHA-256。

整理前代码、文档、配置和关键输出保存在本地 `local/archive/reorganization-20261117/`；其中 `before_sha256.json` 记录整理前数据/产物指纹，`migration_map.json` 记录模块和工作簿路径迁移。原始输入保持原内容。

## 验证

整理前测试：86 项通过。整理后核心回归 67 项、可选比较/图表 5 项、本地网站/部署 22 项均通过，共 94 项；其中 43 项算法测试在无生产数据的代码导出目录中独立通过。独立重算目录初始不含前端、论文、标准化数据或旧输出，仅含计算源码、配置、测试和所需原始输入。

独立重算后，下列关键文件与整理前逐字节一致；扩展核对包含全部十张不确定性 CSV，共 14 个文件：

- `hong_kong_sector_monthly.csv`
- `hong_kong_total_monthly.csv`
- `hong_kong_total_annual.csv`
- `uncertainty/sector_monthly_uncertainty.csv`
- `uncertainty/total_monthly_uncertainty.csv`
- `uncertainty/total_annual_uncertainty.csv`
- `publication/MCE_HK_monthly.csv`

阶段来源清单中的代码路径/哈希随迁移更新。原始文件读取跟踪识别出 87 个核心输入。独立代码导出包通过无生产数据算法测试，安装包在独立环境验证了输入检查和结果检验命令。完整检验、输入读取记录和最终验收结果写入本地整理档案的 `verification.json`。

## 本地资料与公开范围

网站、卫星研究、缓存、回滚目录和部署设置保留在本地，其内容不进入公开代码包。论文版本已迁入 `local/archive/manuscript/`，原输出路径保留兼容链接；设计生成素材迁入 `local/archive/design-assets/`。本地日更的临时工作目录不再复制论文档案。它们可能包含历史运行或研究记录，未按目录名整体删除。以后清理这些大文件，应先确定保留版本，再单独处理。

本轮没有创建 GitHub 仓库、提交、推送或发布网站。代码许可证、原始输入获取和分发条件仍按发布准备文档处理。

## 最终验收

- 87 个核心原始输入已通过实际文件读取跟踪与哈希检查。
- 工作目录和独立复现目录的 14 个结果 CSV 均与整理前逐字节一致。
- 计算包已构建并安装到独立环境，从项目目录外执行输入检查和结果检验成功。
- 官方/Climate TRACE 比较可单独重建；网站数据导出适配运行成功。
- 公开代码导出目录共 84 个文件，附 SHA-256 清单；无生产原始数据、前端、部署设置和历史论文。
- 验证使用现有已安装科学计算依赖；未进行联网的全新依赖安装或公开数据包下载测试。

## 根目录第二轮整理

方法配置统一迁至 `configs/model.json` 和 `configs/uncertainty.json`，依赖版本位于 `configs/requirements.txt`。前端、部署、卫星研究、论文与旧入口集中到 `local/`，计算源码仅保留 `src/cmhk/`。

GitHub 范围直接由 `.gitignore` 控制，已用 Git 枚举确认：83 个可跟踪文件全部属于计算源码、参数、文档、测试和 CI；`local/`、输入数据、输出和缓存均被忽略。可选导出工具也读取同一份 `.gitignore`。

目录调整后，67 项计算回归、22 项本地流程测试、无生产数据的 43 项算法测试均通过；前端在 `local/web/` 构建成功。已有原始输入及结果 CSV 内容未改变。定时任务旧入口保留为转发脚本，部署和临时运行路径已更新。

本轮迁移与验证记录位于本地 `local/archive/root-layout-20261117/`。未创建 GitHub 仓库或推送、未发布网站。
