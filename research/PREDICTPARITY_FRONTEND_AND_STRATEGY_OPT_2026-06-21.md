# 前端优化 + 策略优化设计（基于 Predict Parity 天气交易者研究）

日期：`2026-06-21`
分支：`research/predictparity`

承接 [PREDICTPARITY_WEATHER_TRADERS_2026-06-21.md](PREDICTPARITY_WEATHER_TRADERS_2026-06-21.md)。本文回答两件事：

1. **怎么优化我们的前端**，让我们能方便地研究这些天气交易者的策略；
2. **怎么用这些发现优化我们自己的策略**。

所有建议都落到 `frontend/` 现有代码的具体文件，按“复用已有基建、最小改动”原则给出。

---

## A. 前端现状评估（基于实际代码）

| 模块 | 现状 | 与“研究交易者”的关系 |
| --- | --- | --- |
| `pages/WeatherResearchPage.tsx` | 已很成熟：按 `entryHours` 算 edge、`ExecutionPolicy`（滑点/手续费）、near-lock board、edge-to-settlement | 研究的是**市场/结果**，不是人 |
| `weather/types.ts` | `WeatherOutcome.points[]` 已是每个温度桶的**价格时间序列**；`WeatherEvent.runs[]` 是入场模拟 | 已有可叠加成交点的画布 |
| `charts/LineChart.tsx` | 支持 `ChartSeries / ChartMarker / ChartRule` | **可直接叠加交易者成交标记** |
| `components/CompareView.tsx` | 已有多组对比能力 | 可复用做“交易者对比” |
| `strategies/registry.ts` | 只有 `endline / reverse` 两个通用策略 | 缺“天气专家打法”预设 |
| `services/BacktestService.ts` + mock/http adapter | 回测服务抽象 | 可接入交易者驱动的回测 |
| 数据来源 | `public/data/weather/manifest.json` 等静态 JSON | 交易者数据也走同样的静态 JSON 即可 |

**一句话**：前端缺的不是图表能力，而是**“交易者（钱包）这一层数据与视图”**。而且画布、对比、执行成本模型都已经现成，加这一层的边际成本很低。

---

## B. 前端优化方案（5 个阶段，从易到难）

### 阶段 1：Trader 模式 + 交易者画像表 ⭐（先做这个）

- 在 `TopBar` 的 `AppMode` 增加第三个模式 `'traders'`（现有 `'weather' | 'dashboard'`），`App.tsx` 加一个分支渲染新页 `pages/TradersPage.tsx`。
- 页面顶部是**可排序交易者榜**，列就是研究里的画像字段：
  `别名 / 终身PnL / 终身量 / 天气占比 / 平均单笔 / 卖出比 / 赎回数 / 城市数 / 方向(Yes/No) / 主价格档 / entryHrs(中位) / 风格标签`。
- **默认按终身 PnL 排序，而不是 volume / win-rate**（研究结论：高量≠盈利，predictparity 默认排序会误导）。
- 数据来源：新增 `public/data/traders/manifest.json`，由 Python 管线导出（见 §D 的 `export_frontend.py`）。

### 阶段 2：把交易者真实成交叠加到现有价格图 ⭐⭐（最有价值）

- 复用 `WeatherOutcome.points[]` + `LineChart` 的 `ChartMarker`：在某个城市/某天/某温度桶的价格曲线上，**画出选定交易者在该桶的每一笔买/卖点**（颜色区分 buy/sell，大小表示 size）。
- 叠加一条竖直 `ChartRule` 标出“结算前 24h / 36h”——一眼看出**赢家是否在我们回测出的最优窗口进场**。
- 价值：把抽象的“median entryHrs=44h”变成**可视的进场时点 vs edge 窗口**，直接验证/证伪“预报派 early、收敛派 late”的结论。

### 阶段 3：交易者对比 + 风格分类徽章 ⭐⭐

- 复用 `CompareView` 把 2–4 个交易者并排：PnL 曲线（来自 `user-pnl-api` 时间序列）、进场时点分布、价格档分布、城市热力。
- 自动风格徽章（规则见研究 §6）：
  - `NO 收敛派`：No 占比 >90% 且主价 >90¢
  - `YES 预报派`：Yes 偏多、主价 10–40¢、entryHrs >24h
  - `长尾彩票`：<10¢ 占比高、单笔极小
  - `刷量/做市（避坑）`：volume 巨大但 PnL≈0 或为负

### 阶段 4：交易者 ↔ 我们的 entryHour edge 关联

- 在交易者画像里嵌一个小图：把该交易者的 entryHrs 分布**叠到** `summaryByEntryHour`（我们自己的 edge 曲线）上，回答“他进场的时点，是不是我们 edge 最高的时点”。

### 阶段 5：一键“以该交易者为基准回测”

- 选中一个交易者 → 用他的（方向 / 价格档 / entryHrs / hold-or-exit）参数填充策略，跑 `WeatherResearchPage` 的回测，和我们自己的参数对照。把“看别人”闭环到“改自己”。

> 实施顺序建议：**阶段 1 → 2 先做**（投入小、洞察大），3/4/5 视需要。所有阶段都不需要新依赖（项目目前只依赖 react），沿用现有 `LineChart` / `CompareView` / 静态 JSON 模式即可。

---

## C. 前端交易者数据 schema（新增，贴合现有风格）

新增 `frontend/src/traders/types.ts`：

```ts
export interface TraderFill {        // 单笔成交（叠加到价格图用）
  t: number;                         // epoch s
  side: 'buy' | 'sell';
  outcome: 'Yes' | 'No';
  price: number;
  size: number;                      // usdc
  citySlug: string;
  bucketLabel: string;               // 如 "80-81°F"
  eventDate: string;                 // YYYY-MM-DD
  hoursBeforeResolution: number;
}

export interface TraderProfile {
  wallet: string;
  alias: string | null;
  asOf: string;
  lifetimePnl: number;               // lb-api/profit
  lifetimeVolume: number;
  currentValue: number;
  weatherPct: number;
  avgTradeUsd: number;
  sellRatio: number;
  redeems: number;
  nCities: number;
  direction: { yes: number; no: number };
  priceRegime: Record<string, number>;
  entryHours: { p10: number; median: number; p90: number };
  topCities: [string, number][];
  style: 'no-convergence' | 'yes-forecast' | 'long-tail' | 'farmer' | 'generalist';
  pnlSeries?: { t: number; p: number }[];   // user-pnl-api
}

export interface TradersManifest {
  generatedAtUtc: string;
  traders: TraderProfile[];
}
```

`TraderFill[]` 按 `citySlug+eventDate+bucketLabel` 与 `WeatherOutcome` 对齐即可叠加到现有图。

---

## D. 数据管线接线

研究阶段已经有 3 个脚本（`predictparity_weather_{discover,profile,pnl}.py`）。新增一个**导出器** `research/predictparity_export_frontend.py`：

1. 读 `discovery.json / winner_profiles.json / lifetime_pnl.json`；
2. 拉每个目标钱包的天气 `/activity` → 生成 `TraderFill[]`，以及 `user-pnl-api` 的 `pnlSeries`；
3. 套 §6 规则打 `style` 标签；
4. 输出到 `frontend/public/data/traders/manifest.json` 和 `frontend/public/data/traders/{wallet}.fills.json`。

这样前端零后端、纯静态即可消费，和现有 `weather/manifest.json` 模式一致。（导出器骨架已随本轮提交，见同目录。）

---

## E. 策略优化（用研究结论改我们自己的打法）

### E.1 把两种已验证的盈利打法做成策略预设

研究证明天气赛道有两条稳定正期望的路径，应在 `strategies/registry.ts` 增加两个预设（并在 weather 回测里支持方向/价格档）：

**预设 1：`wx-yes-forecast`（早派 YES 预报）**

- 方向：买 Yes（被低估、有命中概率的桶）
- 入场价档：`0.10–0.40`
- 入场窗口：**结算前 24–44h**（赢家 OnlyLuckNoBrain 中位 44h、ultralisk 39h、badatmath 15–30h）
- 持有：到结算（hold-to-resolve）
- **与我们 Madrid 回测的 `36h` 最优窗口完全吻合** → 这是我们最该自己做的方向。

```
params: entry_hours_min=24, entry_hours_max=44, price_lo=0.10, price_hi=0.40,
        direction=yes, exit=hold_to_resolve, order_qty=...
```

**预设 2：`wx-no-convergence`（晚派 NO 收敛）**

- 方向：买 No（几乎不可能命中的桶），吃 `0.95→1.00` 收敛
- 入场价档：`>0.90`
- 入场窗口：结算前 `<13h`（Poligarch 11h、0xfBd8C9 12h、HighTempTation 13h）
- 持有：到结算或临门主动卖出（HighTempTation 卖出比 0.67）

```
params: entry_hours_max=13, price_lo=0.90, direction=no,
        exit=hold_or_active, order_qty=...
```

### E.2 用执行成本守住 edge（losers 给的最大教训）

- 研究里 `pootytherewardfarmer` 量 $19.4M 却亏 $18 万、`L.X` 卖出比 0.52 仍亏——说明**没有定价判断就高换手 = 给别人送流动性**。
- 落地：所有预设回测**必须经过现有 `ExecutionPolicy`**（`slippagePerLeg / feePerLeg / maxStaleMinutes / minUpdates6h`），用 `conservativePnl` 而非 `rawPnl` 判定。尤其 NO 收敛派单笔利润薄，对点差极敏感，必须扣成本后仍为正才采用。

### E.3 用赢家的 entryHrs 分布校准我们的入场窗口

- 把赢家 entryHrs 分布作为先验，叠到我们的 `summaryByEntryHour` 上：
  - 若我们 edge 峰值（36h）落在“早派”簇里 → 早派预报是主战场，加大该窗口采样/补数；
  - NO 收敛派的 `<13h` 窗口我们尚未系统回测 → 列为新实验（见 E.5）。

### E.4 选边而不是混做

- 早派 YES 与晚派 NO 是两套独立系统，混在一起会互相稀释。建议：
  - 有预报模型能力 → 主攻 `wx-yes-forecast`（和仓库现有 PMXT/Madrid 研究同源，最易落地）；
  - 暂无模型 → 先小规模试 `wx-no-convergence`，靠纪律和盘口收敛吃确定性。

### E.5 下一步可执行实验

1. 在 `wx-no-convergence` 上跑 `<13h` 窗口、扣 `ExecutionPolicy` 成本的回测，验证净收益是否为正（我们目前只系统验证过 24–36h 的 YES 边）。
2. 对早派赢家做**逐城市命中率**拆解，找出他们最强的城市，与我们多城市回测对照，集中火力。
3. 跟踪头号赢家 `Poligarch` 的 `user-pnl` 曲线，判断 edge 是否在衰减——衰减则说明该窗口在变拥挤。

---

## F. 改动文件清单（便于后续实现）

| 改动 | 文件 | 类型 |
| --- | --- | --- |
| 增加 `'traders'` 模式 | `frontend/src/components/TopBar.tsx`、`App.tsx` | 改 |
| 交易者画像页 | `frontend/src/pages/TradersPage.tsx`(+css) | 新 |
| 交易者数据类型 | `frontend/src/traders/types.ts` | 新 |
| 成交叠加（复用） | `charts/LineChart.tsx`（已支持 marker，无需改） | 复用 |
| 对比（复用） | `components/CompareView.tsx` | 复用 |
| 两个策略预设 | `strategies/registry.ts` + weather 回测方向/价格档支持 | 改 |
| 前端数据导出器 | `research/predictparity_export_frontend.py` | 新 |
| 静态数据 | `frontend/public/data/traders/*.json` | 新（生成） |

---

## G. 小结

- 前端只差“交易者这一层”，且画布/对比/执行成本模型都现成——**阶段 1+2（画像表 + 成交叠加）性价比最高**。
- 策略侧最大收获：研究用别人的真金白银**独立验证了我们 `24–36h` 的 YES 预报窗口**，并指出一条我们尚未系统化的 `<13h` NO 收敛新路径。
- 最该守住的纪律：**按净（扣成本）PnL 选打法、按终身 PnL 选标杆**，别掉进“高量刷返佣”的陷阱。
