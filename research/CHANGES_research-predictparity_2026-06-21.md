# 改动说明 · 分支 `research/predictparity`

日期：`2026-06-21`
目的：本分支与另一个正在改前端的分支并行，**这里说明本分支到底动了什么，便于合并协调、避免冲突。**

---

## TL;DR（给改前端的同学）

- ✅ **本分支没有修改任何前端源码**（`frontend/src/` 零改动）。
- ✅ 对前端只做了**纯新增**：多了一个数据目录 `frontend/public/data/traders/`（全是新文件）。
- ✅ 因此与你们改 `frontend/src/` 的工作**没有合并冲突风险**，可以放心各做各的。
- ⚠️ 唯一需要协调的是**未来**：如果要把研究做成可视化界面，会新增/改动几个源码文件（见下方“未来会触碰的文件”），那时再对齐即可，现在不冲突。

---

## 本分支改了哪些文件（相对 `main`，全部为新增）

### 研究文档与脚本（`research/`，与前端无关）

| 文件 | 说明 |
| --- | --- |
| `research/PREDICTPARITY_WEATHER_TRADERS_2026-06-21.md` | 天气交易者研究主报告（谁厉害、习惯统计、风格分类） |
| `research/PREDICTPARITY_FRONTEND_AND_STRATEGY_OPT_2026-06-21.md` | 前端 + 策略优化设计方案 |
| `research/predictparity_weather_discover.py` | 发现反复出现的天气钱包 |
| `research/predictparity_weather_profile.py` | 交易习惯画像 |
| `research/predictparity_weather_pnl.py` | 现金流重算 PnL / 胜率 |
| `research/predictparity_export_frontend.py` | **把研究数据导出成前端静态 JSON 的导出器** |

### 前端数据（`frontend/public/data/traders/`，纯新增，不碰源码）

| 文件 | 说明 |
| --- | --- |
| `frontend/public/data/traders/manifest.json` | 10 个交易者的画像汇总（`TradersManifest`） |
| `frontend/public/data/traders/{wallet}.fills.json` | 每个钱包的天气成交明细（`TraderFill[]`），10 个文件 |

> 数据规格与现有 `frontend/public/data/weather/*.json` 一致（纯静态、零后端）。单文件 100–660KB，合计约 4.2M，与现有 weather json（每个 5.5M）同量级。

---

## 数据契约（其他分支若要消费这份数据）

- `manifest.json` → `{ generatedAtUtc, traders: TraderProfile[] }`
  - `TraderProfile` 字段：`wallet / alias / lifetimePnl / lifetimeVolume / currentValue / weatherPct / avgTradeUsd / sellRatio / redeems / nCities / direction{yes,no} / priceRegime / entryHours{p10,median,p90} / topCities / style / nFills`
  - `style ∈ { 'no-convergence' | 'yes-forecast' | 'long-tail' | 'farmer' | 'generalist' }`（启发式标签，可在前端再细化）
  - **建议默认按 `lifetimePnl` 排序，不要按 volume/winRate**（研究结论：高量≠盈利）。
- `{wallet}.fills.json` → `TraderFill[]`，字段：`t / side / outcome / price / size / citySlug / bucketLabel / eventDate / hoursBeforeResolution`
  - 通过 `citySlug + eventDate + bucketLabel` 可与 `WeatherOutcome` 对齐，叠加到现有价格图。
- 重新生成：`python3 research/predictparity_export_frontend.py`

---

## 未来会触碰的前端源码（现在还没动，供协调）

如果之后按设计文档实现“交易者视图”，预计会改/加这些 `frontend/src/` 文件。**列出来是为了让两个分支提前认领、避免日后撞车：**

| 文件 | 改动类型 | 说明 |
| --- | --- | --- |
| `src/components/TopBar.tsx` | 改 | `AppMode` 增加 `'traders'`（现为 `'weather' \| 'dashboard'`） |
| `src/App.tsx` | 改 | 增加 `traders` 模式的渲染分支 |
| `src/pages/TradersPage.tsx`(+css) | 新增 | 交易者画像页 |
| `src/traders/types.ts` | 新增 | 交易者数据类型 |
| `src/strategies/registry.ts` | 改 | 增加 `wx-yes-forecast` / `wx-no-convergence` 两个策略预设 |
| `src/charts/LineChart.tsx` | 复用（无需改） | 已支持 marker，用来叠加成交点 |
| `src/components/CompareView.tsx` | 复用 | 交易者对比 |

> `TopBar.tsx`、`App.tsx`、`strategies/registry.ts` 是两个分支都可能改的**热点文件**——若你们也在动这几个，请提前同步，合并时重点看这三处。其余为纯新增文件，不冲突。

---

## 合并建议

1. 本分支可随时合入：对前端是纯加目录，不影响现有构建与界面。
2. “交易者视图”的源码实现建议**单独再开一个 PR**，并在动 `TopBar.tsx / App.tsx / registry.ts` 前与改前端的分支对齐，避免三处热点冲突。
