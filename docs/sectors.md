# 分部门计算公式与代码位置

下列公式对应当前生产方法。`m` 为月份，`y` 为年度，`q` 为季度，`b=2021`。`B` 为 CRT 官方 ktCO₂，`H` 为燃料热量 TJ，`w` 为活动权重，`P` 为校准前代理，`E` 为发布结果。

## 共用换算与分配

实现：`context.py:factor/volume_tj/yearly_component`、`kernels.py:allocate/constrained_months`。

```text
热量 TJ = 质量 t × 净热值 GJ/t / 1000
质量 t = 体积 kL × 密度 t/kL
排放 ktCO₂ = 热量 TJ × 因子 tCO₂/TJ / 1000
月度热量 H[m] = 年/季热量 H[p] × w[m] / Σ(w[p的全部月份])
```

因子、密度、热值及热值口径换算均在 `configs/model.json`。例：1000 kL 航煤 × 0.8 t/kL × 44.1 GJ/t /1000 = 35.28 TJ；再乘 71.5/1000 = 2.52252 ktCO₂。城煤气按 `2.549/48` ktCO₂/TJ 计算终端直接燃烧。

年度/季度约束必须有完整活动月份，缺少月份则保留缺失；不把整个年度分给已有的部分月份。后续外推使用最近完整年“燃料/活动”比率，并标记暂估身份。

## Power：电力

入口：`sectors/power.py:power`；近期更新：`nowcast.py:apply/company_mix`；最终校准：`assembly.py`。

输入为 C&SD 发电投入、季度供电平衡及月度用电。季度内先用月度用电和按天分配的平衡调整项构造权重，再约束到季度本地发电总量：

```text
调整项 = 自用及损耗 + 出口 − 进口
月度初始发电权重 = 月度用电 + 调整项 × 当月天数/季度天数
月度发电 G[m] = 季度本地发电 × 权重[m]/Σ季度权重
```

2013 年前采用年度发电约束。投入表中发电燃料消耗为负数，代码取其相反数得到正燃料热量；OIL 合并项包括天然气。按情景液体份额拆分油气，用燃气/煤效率推断分燃料发电份额；月度分配同时保持全年燃料排放总量。主情景为 `liquid_0_response_0`。

```text
P[m] = Hgas[m] × EFgas + Hcoal[m] × EFcoal + Hoil[m] × EFoil
E[m] = Bpower × P[m]/ΣP[b]
```

近期缺失季度用已观测月度用电估计；最新燃料年后的强度采用留出选择的持平/阻尼趋势，结合核验过的两电产出混合更新。港灯一家变化按固定公司权重计入；其燃煤含燃油类别，不能当作全港纯煤占比。公司代理系数在 `configs/model.json.near_realtime`。

## Industry：工业

入口：`sectors/industry.py:annual_fuel/monthly_fuel`；系数与输出：`sectors/industry.py:industrial_estimate`。

使用 EMSD 年度“城煤气及 LPG”和“油及煤”两组热量，排除电力。重叠年份采用较新版数据。气体组按工业煤气月度活动分配，油煤组按工业用电月度活动分配：

```text
Hgas[y,m] = Hgas[y] × 工业煤气[m]/Σ工业煤气[y]
Hliquid_solid[y,m] = Hliquid_solid[y] × 工业用电[m]/Σ工业用电[y]
k = Bindustry / (Hgas[b] + Hliquid_solid[b])
E[m] = k × (Hgas[m] + Hliquid_solid[m])
```

年度非电力能耗约束覆盖 2005–2024。后续月份保持最近年度每组燃料/活动比率。工业用电仅作为分配权重，未另计购电排放。诊断表为 `industry_annual_fuel.csv`、`industry_proxy_components.csv` 和 `industry_proxy_calibration.csv`。

## Residential / Commercial：居民与商业

入口：`sectors/buildings.py:stationary`；主情景分别为 `gas_profile_trace_0`、`gas_profile`。

月度煤气直接来自 C&SD。EMSD 年度合并气体减去全年煤气，剩余项按 LPG 处理；若为负值则报错。油煤合并项按柴油因子近似，残余气体按 LPG 热值口径换算后的因子处理：

```text
LPG残余[y] = EMSD合并气体[y] − Σ煤气[y]
P[m] = 煤气[m] × EFtown_gas
     + LPG残余月分配[m] × EFlpg
     + 油煤月分配[m] × EFdiesel
E[m] = Bsector × P[m]/ΣP[b]
```

主方法按月度煤气形状分配年度残余；按天分配保留作情景。居民 2021 年后原表缺失/微量油煤项采用 0 与 1 TJ/年两种情景，主方法为 0 TJ。诊断保留燃料残余和口径兼容性。

## Road Transport：道路及剩余运输

入口：`sectors/road.py:road_activities/road`；主方法 `ev_mileage_1`；最终发布校准在 `assembly.py`。

采用固定三条过海隧道与六类车辆的月度交通面板，按年度车公里标度、登记燃料份额及各类车辆假设耗油强度合成代理。电动车相对里程情景为 0.7、1、1.3。2005–2012 使用 CEIC 月度油品需求代理，属于全用途需求而非观测道路燃料。

```text
燃料份额[c,f,m] = 登记车辆[c,f,m] /
                  (全部登记车辆[c,m] + (EV相对里程−1) × EV车辆[c,m])
活动[f,m] = Σc(隧道交通[c,m] × 燃料份额[c,f,m] × 假设L/km[c]) × 年度车公里标度
柴油热量[y] = 运输油煤热量[y] − 客货海运热量[y] − 当地汽油热量[y]
R[m] = 各燃料年度约束/月度外推排放之和
Eroad[m] = (Btransport − Bnavigation) × R[m]/ΣR[b]
```

年度燃料拆分是代理构造假设。发布账户始终由道路代理驱动，包含全运输扣除本地航运后的剩余类别；不随本地航运月度形状再分配。`road_monthly_proxy.csv` 保留未按发布边界校准的道路代理。

## Domestic Navigation：本地航运

入口：`sectors/transport_annual.py:marine_energy`、`sectors/navigation.py:allocate_marine/disaggregate/extrapolate`；发布取 `marine_calibrated_proxy_ktCO2`。

```text
2008–2024：
  客运热量[m] = 客运热量[y] × 渡轮客流[m]/Σ渡轮客流[y]  （2013年起）
  客运热量[m] = 客运热量[y] × 当月天数/全年天数          （2008–2012）
  货运热量[m] = 货运热量[y] × 当月天数/全年天数
  E[m] = Bnavigation × (客运热量[m]+货运热量[m])/海运总热量[b]
2025年起：
  客运热量[m] = 渡轮客流[m] × 客运热量[2024]/Σ渡轮客流[2024]
  货运热量[m] = 当月天数 × 货运热量[2024]/全年天数[2024]
```

2005–2007 缺少海运年度支持，保留缺失，因此完整本地合计从 2008 年开始。历史全运输合成指标仍作为诊断保留；最终发布的道路与航运采用上述独立账户。2021 两项合计等于 CRT 完整 1.A.3。

## International Aviation / Shipping：国际航空及航运供油

入口：`sectors/bunkers.py:bunkers`、`nowcast.py:apply`。

分别筛选 C&SD `Aircraft stores` 和 `Ship stores`，按油品、体积/质量单位转换为热量。2013 年前使用年度供油量，之后使用季度供油量；Q4 在官方只给全年和 Q1–Q3 时按差额推导。

```text
P[m] = Σf(供油热量[f,p] × 活动[m]/Σ活动[p] × EF[f])
E[m] = Bsector × P[m]/ΣP[b]
```

航空按 HKIA 起降架次分配。航运从全部到港、海洋船到港、净吨位代理中，使用 2017–2022 选择期选定方法，2023–2025 独立评价；主表的 `activity_method` 和 near_realtime manifest 保存实际选择。近期缺失季度按历史燃料/活动比率暂估，不填未来月份。

## 不确定性与汇总

`uncertainty/scenarios.py` 构造替代结构；`uncertainty/monte_carlo.py` 按明确分布传播误差；`uncertainty/totals.py` 对齐抽样后汇总。随机种子、10 万次抽样及误差范围在 `configs/uncertainty.json`。95% 区间是条件于这些设定的模型区间。

工业使用共享 2021 系数误差和目标年/基准年的年度活动比误差；不再使用多个工业基准插值。总量和同比先对联合抽样求和或作差，再取分位数。不能相加各部门区间端点。

每次重构应核对点值、缺失位置、单位、校准年守恒、年度/季度守恒、总量范围和固定种子的区间。公式或参数改变需作为方法修订单独审阅。
