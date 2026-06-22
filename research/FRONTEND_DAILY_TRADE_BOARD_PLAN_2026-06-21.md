# 前端改造计划：分地区「每日交易看板」（精确版，待你修改）

> 基于你的原始描述整理。已对照现有代码（`WeatherResearchPage.tsx` / `weather/types.ts` /
> `weather/researchAnalytics.ts` / `charts/LineChart.tsx`）逐项核实哪些是"已经有"、哪些是
> "真正要新建"，避免重复造轮子，也避免漏掉需要新加的能力。

## 0. 目标重述

对于**每一个地区**（现有 `WeatherLibraryManifest` 里的每个 `citySlug`，如 chengdu / madrid …），
在该城市的研究页面里，最显眼的位置展示「我们自己策略」的交易表现，包含 4 个模块：

- **模块 A（首屏最重要）**：每日 PnL + 买卖时间点 + 买的是哪个温度档位 + （如有条件）盘口深度
- **模块 B**：PnL 总体走势（独立的图，不和模块 A 混在一起）
- **模块 C**：模块 B 下方，每日具体数值的表格，每行可展开
- **模块 D**：展开后的当日详情 —— 类似 Polymarket 官方页面，同时显示几条主流档位走势
  （例如 Madrid 的 38/39/40°C），并把**我们买入的那条线、买入到结算这段时间**高亮出来

下面逐模块给出精确定义。

---

## 1. 现状速览：哪些已经存在，哪些要新建

| 能力 | 现状 | 结论 |
|---|---|---|
| 每日逐笔 PnL + 累计 PnL 数据 | 已有：`buildEventBacktestRows()` / `buildExecutionRows()`（`researchAnalytics.ts`），字段含 `pnl`、`cumulativePnl`、`selectedLabels`、`selectedProbabilitySum`、`entryTimestamp` | **复用，不重算** |
| 当日多档位价格走势（38/39/40°C 这种线） | 已有：`selectedEvent.outcomes` → `chartSeries`，目前是**全部 11 个档位都画出来**（赢家实色、命中候选橙色虚线、其余全部淡化虚线） | **要改**：默认应该只挑"主流几条"，不是全画 |
| 买入时间点标记 | 已有：`chartMarkers`，在 entry 时间点画一个点 | **复用** |
| 买入时刻的竖直参考线 | 已有：`chartRules`（单点竖线，无范围） | **不够**：只能画一条线，不能画一段"区间高亮" |
| 买入后那一段时间的高亮 | **没有** | **新建**：需要给 `LineChart` 加"区间底色"+"线段加粗"两种能力 |
| 盘口深度（下单时刻的 orderbook） | 已有但覆盖很窄：`WeatherOrderbookCapacityRow`/`ORDERBOOK_CAPACITY_URLS`，**目前只有 Madrid 36h 入场这一种组合**，其余地区/entry hour 没有快照数据 | **复用 + 明确告知用户覆盖范围有限** |
| 表格行展开看当日详情 | **没有**：现在点击 Event Timeline 表格行只是切换 `selectedEventSlug`，再跳到别的 tab 才能看图，不是"下拉展开" | **新建**：原地 accordion 展开 |
| 按地区切换 | 已有：`library.cities` + 侧边栏 City Library，无需新建 | **复用** |

一句话结论：**数据层基本够用，缺的是"图表能力"（区间高亮、主流档位筛选）和"交互层"（原地展开）**，不需要重新设计数据模型。

---

## 2. 模块 A：每日 PnL + 买卖点 + 档位 + 盘口深度（首屏图）

**位置**：放在页面最上方、`Selected Run` 卡片下面，比现在的 `Backtest Overview` 区块更靠前 ——
现在这块逻辑藏在 Overview tab 里、Decision Ticket 之后，需要提前。

**图表形态**：柱状图（不是折线）。

- X 轴：按日期（`event.date`），每天一根柱
- Y 轴：当日 PnL（`run.pnl`），正绿负红
- 每根柱上方/悬浮 tooltip 显示：
  - 买入时间（`run.entryTimeUtc`，用 `fmtEdtTimestamp()` 转成 EDT 显示）
  - 买的档位（`run.selectedLabels.join(' + ')`）
  - 买入价格（`run.selectedProbabilitySum`）
  - 命中/未命中（`run.didHit`）
- 盘口深度：**在有数据的情况下**（目前仅 Madrid 36h），鼠标悬浮柱子时额外显示一行，例如
  `ask 71% · +1¢ 深度 1.2k sh`，数据来自 `WeatherOrderbookCapacityRow.snapshotBestAsk` /
  `cumSizePlus1c`，按 `(citySlug, date, bucketLabel)` 关联。没有数据的地区/日期，这行直接不显示
  （不报错、不显示"无数据"占位，保持干净）。

**新增小函数**（建议放 `researchAnalytics.ts`）：
```ts
buildDailyTradeRows(dataset, entryHours, orderbookByDateAndBucket?) -> DailyTradeRow[]
// DailyTradeRow = { date, pnl, cumulativePnl, entryTimeUtc, selectedLabels,
//                    selectedProbabilitySum, didHit, depthHint?: string }
```

---

## 3. 模块 B：PnL 总体走势（独立图）

- 和模块 A **分开一个图**，不复用同一个 `LineChart` 实例
- 折线图：X 轴日期，Y 轴累计 PnL（`cumulativePnl`）
- 保留现有的"selected day"标记点（`backtestOverviewSeries` 里已有这个 marker 模式，直接照搬）
- 数据源：和模块 A 同一份 `buildDailyTradeRows()` 结果，只是画法不同（一个画柱状逐日 PnL，一个
  画累计折线），**避免两处各算一遍**

---

## 4. 模块 C：每日明细表（在模块 B 下方，支持展开）

**列**：日期 | 当日 PnL | 累计 PnL | 买入档位 | 买入价格 | 命中 | 展开箭头

**展开交互**（这是和现状最大的行为差异，需要你确认）：

- 现状：点击表格行 = 切换 `selectedEventSlug`，要去其他 tab 才能看图
- 新计划：表格行点击**依然**保留切换 `selectedEventSlug`（不破坏现有联动），但行尾新增一个
  独立的展开箭头按钮，点击后在**该行下方原地插入**模块 D 的当日详情图，不需要切 tab

**需要你决定**：
- 同时只能展开一行（accordion，点开新行自动收起旧行），还是允许多行同时展开？
  → 多行展开方便对比，但表格会变很长。**建议先做单行 accordion**，量大了再考虑多选对比。

---

## 5. 模块 D：当日详情图（多档位走势 + 高亮交易区间）

这是整个计划里**唯一需要给 `LineChart.tsx` 加新能力**的部分，详细拆开说：

### 5.1 只画"主流几条"，不是全部 11 档

现状 `chartSeries` 把 `selectedEvent.outcomes` 全部画出来（11 条线，大部分是淡化虚线）。
新计划：默认只画 —— 买入的档位 + 结算赢家档位 + 这两者附近 ±2 档（用现有的
`bucketKey()` 算数值距离）。对 Madrid 来说效果就是恰好显示 38/39/40°C 这种 3~5 条线，
和 Polymarket 官方页面的视觉密度一致。其余档位默认隐藏，但可以加一个"显示全部档位"的
小开关，给想看长尾的人用。

### 5.2 高亮"买入那条线、买入到结算这段时间"

两层叠加，缺一不可（对应你强调了两次的"高亮"）：

1. **背景区间底色**：在图表上画一个从 `entryTimestamp` 到 `event.endTimeUtc` 的半透明竖直
   色块，让人一眼看到"这是持仓区间"。这是 `LineChart` 目前完全没有的能力，需要新增：
   ```ts
   export interface ChartBand {
     x1: number;
     x2: number;
     color: string;
     opacity?: number;
     label?: string;
   }
   ```
   渲染顺序：grid → bands（新增）→ series → markers，避免色块盖住线条。

2. **买入档位线本身分段变色**：同一条线，买入时刻之前淡（现状的 0.28 透明度虚线风格），
   买入时刻到结算这一段**加粗、不透明、用强调色**（建议直接用 `COMPARE_COLORS[0]`
   `#bc4a1c`，和现有"selected"配色体系一致）。
   实现上等于把买入档位的 `outcome.points` 切成两段，喂给 `LineChart` 两条 series，但要让
   它们在图例（legend）里**合并显示成一条**，不能出现重复图例。现状 `LineChart` 用
   `s.label` 同时做 React key 和图例 key，两段必须共享 label 就会 key 冲突 —— 这里需要给
   `ChartSeries` 加一个独立的 `id`（做 key）和保留 `label`（做图例去重），是个具体的实现
   细节，先在这里标出来，写代码时不要漏掉。

3. 已有的买入点标记（`chartMarkers` 画的圆点）保留，不用动。

---

## 6. 盘口深度的覆盖范围（重要的预期管理）

`WeatherOrderbookCapacityRow` 数据目前**只有 Madrid + 36 小时入场**这一种组合有快照
（见 `ORDERBOOK_CAPACITY_URLS`），其它地区/entry hour 没有抓取过对应时刻的 orderbook。

这意味着：
- 模块 A 的"盘口深度"提示，目前只会在 Madrid 36h 这一种情况下出现，其它地区看不到，
  **这不是 bug，是数据没采**
- 如果你希望"每个地区"都能看到盘口深度，需要先扩展数据抓取脚本（类似现有 PMXT 回放
  抓取逻辑），把抓取范围从 Madrid 36h 扩到其它城市/entry hour —— **这是一个独立的数据
  管线任务，不在这次前端改造范围内**，建议先用 Madrid 验证这套展示方式，跑通后再决定
  要不要扩数据覆盖

---

## 7. 建议的文件改动清单（非强制，方便你规划）

- `frontend/src/charts/LineChart.tsx` —— 加 `bands?: ChartBand[]` prop；`ChartSeries` 加
  `id`（key 用）与保留 `label`（图例去重用）
- `frontend/src/weather/researchAnalytics.ts` —— 新增 `buildDailyTradeRows()`、
  `nearbyBucketLabels(event, run, radius)` 两个纯函数
- 新文件 `frontend/src/weather/DailyTradeBoard.tsx` —— 模块 A（柱状图）+ 模块 C（表格 +
  展开），对外只接收 `dataset` / `selectedEntryHours` / 当前展开的 `expandedDate`
- 新文件 `frontend/src/weather/DailyDetailChart.tsx` —— 模块 D，输入一个 `event` +
  `run`，输出多档位高亮图，被模块 C 展开行和（未来可能保留的）旧 Audit tab 共用
- `frontend/src/pages/WeatherResearchPage.tsx` —— 在 `Selected Run` 卡片下方挂载模块
  A + B + C；现有的 "Backtest Overview" 区块（`backtestOverviewSeries` 那段，约
  1278-1333 行）可以被模块 A+B 取代，避免页面里出现两份同质图表

---

## 8. 整体布局调整：把"策略 config"收进右上角工具框

你确认了模块 A-D 没问题，并补了一条布局要求：策略参数不要常驻占屏幕，收进右上角一个
下拉/工具框，主屏幕专门留给数据图表。现状是 3 栏布局（`col-history` 日期列表 +
`col-config` 参数表单/导航 + `col-results` 图表区），要改成：**顶部右侧一个按钮，点开
浮层工具框装所有配置；主屏幕收成一栏，专门铺模块 A/B/C/D。**

### 8.1 哪些东西算"策略 config"，收进工具框

- Research Controls 表单全部字段：City / City slug / City label / Anchor date / Days /
  Entry hours / Threshold / Slip per leg / Fee per leg / Max stale min / Min updates 6h /
  Max paid prob / Min signal margin / Max pre-entry 6h move
- 三个操作按钮：Refresh From APIs / Load Local Archive / Reset Defaults
- Entry Hour 选择：现状是主屏幕里一大块"Entry Hour Grid"卡片墙，改成工具框里一个紧凑的
  分段控件（6h / 12h / 18h / 24h / 36h 挑一个），不再占主屏幕空间
- City 切换：现状"Local City Library"卡片墙，改成工具框顶部一个地区下拉选择器

### 8.2 工具框交互形态（默认方案，非强制）

建议用**右侧滑出的浮层面板**（不是挡住下面图表的 modal 弹窗）：点击右上角"策略参数"
按钮滑出，点击面板外部或再点一次按钮收起；面板内部字段保持现状分组（Setup 区 /
Policy 区），改动字段后图表照常实时重新计算，只是位置挪到浮层里，行为不变。选这个
而不是 dropdown，是因为字段有 13+ 个，纯下拉框会很挤；选这个而不是阻塞式 modal，是
因为你可能想边调参数边看图表反应。

### 8.3 原 `col-history`（日期列表）和 `Date × Entry Hour` 矩阵怎么处理

这两个本质上都是"选日期"的导航工具，功能和新的**模块 C（每日表格）**重叠——模块 C
本身就能逐日浏览、点击展开。建议：

- `col-history` 的日期列表整体**删除**，靠模块 C 表格做日期导航
- `Date × Entry Hour` 矩阵（现状在 Explore tab，按日期 × entry hour 给一格 PnL 热力图）
  **保留，但挪进工具框里一个默认收起的"高级"折叠区**，给想横向对比不同 entry hour 的人
  用，不是默认可见的东西

### 8.4 主屏幕收口后，从上到下的顺序

1. `Selected Run` 概览卡（保留——告诉你现在看的是哪一天/哪个 entry hour）
2. **模块 A**：每日 PnL + 买卖点 + 档位 + 盘口深度（首屏最重要）
3. **模块 B**：PnL 总体走势
4. **模块 C**：每日明细表（可展开 → 模块 D）
5. 原有的 Decision Ticket / Signal Lab / Liquidity / Risk / Audit 几个 tab，作为"更深入
   的分析"放在模块 A-D 下方，不再和它们竞争首屏空间

### 8.5 文件改动清单补充

- `frontend/src/components/TopBar.tsx` —— 加一个"策略参数"按钮，控制浮层开关
- 新文件 `frontend/src/weather/StrategyConfigPanel.tsx` —— 浮层本体，把现状 Setup tab
  表单 + 操作按钮 + Entry Hour 分段控件 + 折叠的 Date×EntryHour 矩阵都搬进来
- `frontend/src/pages/WeatherResearchPage.tsx` —— 删掉 `col-history` / `col-config` 两栏，
  布局改单栏；原有 state（`citySlugInput` 等一大串）不用动，只是渲染位置从侧栏挪到浮层

## 9. 需要你拍板的几个开放问题

1. **模块 C 展开方式**：单行 accordion，还是允许多行同时展开对比？（影响 state 设计）
2. **模块 B 的累计 PnL 用哪条口径**：现状有"raw 累计 PnL"和"risk-adjusted 累计 PnL"（过完
   护栏过滤的）两条线，分别在不同 tab。模块 B 默认显示哪一条作为"总体走势"的主图？另一条
   是否仍保留在原 tab 里作为对照？
3. **柱状图（模块 A）颜色 & 标签密度**：每天一根柱，如果回测窗口很长（比如几十天），柱子
   会很密集，X 轴日期标签要不要做成可滚动/可缩放，还是先不管，等数据量大了再优化？
4. **"主流几条线"的默认范围（±2 档）是否合适**：如果某天买的是 tail 档位（比如离赢家很远
   的偏门档位），±2 档可能不包含赢家本身，要不要改成"买入档位 ±2 档 **以及** 赢家档位"
   两个中心点各自扩展？（已在第 5.1 节按"两者都扩展"写了，这里只是提醒你确认这条规则
   读起来是否符合你的预期）
