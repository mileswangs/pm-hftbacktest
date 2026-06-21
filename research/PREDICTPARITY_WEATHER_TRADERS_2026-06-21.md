# Predict Parity 天气交易者研究

日期：`2026-06-21`
分支：`research/predictparity`
作者：本轮自动化研究

本文档记录：在 [predictparity.com](https://predictparity.com/markets?inc=weather%2Cclimate-and-weather&exc=) 的 weather / climate-and-weather 板块上，**如何找到厉害的天气交易者、并统计他们的交易习惯**。全过程、方法、原始数据脚本、结论都在这里。

配套机读数据（`research/data/weather_traders/`，已被 `.gitignore` 忽略）：

- `discovery.json` —— 反复出现的天气钱包发现结果
- `profiles.json` / `winner_profiles.json` —— 交易习惯画像
- `pnl.json` —— 从 activity 现金流重算的已实现 PnL / 事件胜率
- `lifetime_pnl.json` —— 来自 Polymarket 官方 lb-api 的权威终身 PnL

配套脚本（在 `research/` 下，可复现）：

- `predictparity_weather_discover.py`
- `predictparity_weather_profile.py`
- `predictparity_weather_pnl.py`

> 与本仓库已有的 [POLYMARKET_TRADER_PROFILING.md](POLYMARKET_TRADER_PROFILING.md)、[WEATHER_AND_TRADER_INSIGHTS_2026-06-21_CN.md](WEATHER_AND_TRADER_INSIGHTS_2026-06-21_CN.md) 一脉相承，是其延伸：从“只分析单个 `HighTempTation`”扩展到“系统化找出全部盈利天气专家并归纳打法”。

---

## 0. 一句话结论

Predict Parity 的天气榜单背后是 Polymarket 的每日气温市场。真正赚钱的天气交易者**不是靠押中一城一日的神预测，而是靠在全球 40+ 城市、每天 50+ 事件上系统化地重复同一套小额下注**。他们的“习惯”高度一致，且分成两大可识别的盈利打法（**早进场的 YES 预报派** 与 **晚进场的 NO 收敛派**）。而**高成交量 ≠ 赚钱**：刷量/做市型钱包成交上千万美元却巨亏。

---

## 1. Predict Parity 是什么 / 数据从哪来

Predict Parity 是一个 **Polymarket 数据分析前端**（Next.js SPA + `api-prod.predictparity.com` 后端，后端需登录鉴权，401）。它的页面顶栏有 `MARKETS / TRADERS / TRACKERS / ACTIVITY / PORTFOLIO`，`TRADERS` 页公开渲染出每个钱包的 **Total PnL / Volume / Win Rate / Positions**，钱包地址即 Polymarket 链上地址。

关键发现：

- predictparity 的 `/traders` 页即使带 `?inc=weather` 参数，**渲染出来仍是全站榜**（weather 过滤是登录后客户端调鉴权 API 完成的），所以不能直接拿到“天气专属榜单”。
- 但它的数据全部源于 **Polymarket 公开 API**（无需鉴权），我们可以直接走源头，做得比网站更细：
  - `gamma-api.polymarket.com` —— 市场/事件元数据
  - `data-api.polymarket.com` —— `/holders`、`/activity`、`/positions`、`/value`
  - `lb-api.polymarket.com/profit|volume` —— 官方终身 PnL / 成交量
  - `user-pnl-api.polymarket.com/user-pnl` —— PnL 时间序列

天气市场结构：事件名为 `Highest/Lowest temperature in {City} on {Date}`，标签 `weather / daily-temperature / highest-temperature(104596)` + 城市标签；每个事件下约 11 个温度区间桶市场，每桶一个 conditionId。当前活跃天气事件 **114 个，覆盖 50+ 城市**，单事件成交量最高约 **$32.8 万**。（外部背景：Polymarket 天气类目约 209 个市场、其中温度 158 个，每日结算，提前一个月准确率 >94%。）

---

## 2. 方法：怎么从“一堆地址”里找到天气专家

三步管线（脚本可复现）：

1. **发现（discover）**：拉取按量排名前 60 的活跃天气事件，遍历其全部温度桶市场（660 个），用 `/holders` 取每个市场的持有人，按“**出现在多少个不同天气事件 + 总敞口**”聚合 → 找出反复出现的天气钱包。共扫出 **3,688 个钱包**。
2. **画像（profile）**：对头部钱包拉全量 `/activity`，过滤天气交易，统计：天气集中度、买卖比、赎回数、平均单笔、价格档位、城市分布、方向（Yes/No）、**下单距结算的小时数**。
3. **定盈亏（pnl）**：
   - 从 activity 现金流重算已实现 PnL（`卖出 + 赎回 − 买入`）+ 事件级胜率；
   - **再用 Polymarket 官方 `lb-api/profit` 取权威终身 PnL 做最终排名**（因为这些钱包几乎 100% 只做天气，全市场 PnL ≈ 天气 PnL）。

> ⚠️ 方法学要点：对“持有到结算”型且当前开仓很多的交易者，**只看 `/positions` 快照或只看已实现现金流会系统性低估其盈利**——因为很多买入仓位还没到结算赎回（日度市场要 1–2 天结算）。例：1DVSBSTD 已实现 −$12k 但还有 $37.6k 开仓市值，官方口径实际为 **+$2.9k**。所以最终排名以 `lb-api/profit` 为准。

---

## 3. 反直觉发现：高量 ≠ 盈利

先看“看起来很猛、其实在亏”的钱包（终身口径）：

| 钱包 | 终身 PnL | 终身成交量 | 解读 |
| --- | ---: | ---: | --- |
| `pootytherewardfarmer` | **−$179,819** | $19.4M | 高换手、卖出比 0.25，长期向市场送流动性 |
| `0x1aBc2b46…` | **−$189,666** | $1.0M | 小量大亏，方向错 |
| `TENETENET` | +$6,443 | **$40.9M** | 0.1¢ 微单刷返佣，交易本身近乎打平 |
| `LegendaryBets` | −$8,464 | $0.9M | |
| `L.X` | −$7,661 | $1.3M | 卖出比 0.52，频繁主动进出但没 edge |

**教训**：在天气市场，成交量榜、活跃度榜会把“刷返佣的做市/搬砖钱包”和“真正有预报 edge 的钱包”混在一起。必须用**终身 PnL** 而不是 volume / win-rate 单列来筛。（predictparity 的 TRADERS 页默认就是按这些易误导的维度排。）

还有一个伪“巨鲸”：地址 `0xa5ef39c3…` 在我们扫描的 660 个市场里**每个都持仓**、`/value` 显示 $164 亿——这是 Polymarket 的合约/AMM 地址，不是人，已剔除。

---

## 4. 真正盈利的天气专家排行（权威终身 PnL）

来源：`lb-api.polymarket.com/profit?window=all`（≈ 天气 PnL，因这些钱包几乎纯做天气）。

| 排名 | 别名 | 钱包 | 终身 PnL | 终身成交量 | 当前组合市值 |
| ---: | --- | --- | ---: | ---: | ---: |
| 1 | **Poligarch** | `0xb40e8967…a6e2a7cc9` | **+$165,378** | $21.8M | $96,049 |
| 2 | **0xfBd8C9C2…** | `0xfbd8c9c2…fdc684027` | **+$135,975** | $9.8M | $1,094 |
| 3 | **ultralisk** | `0x74957ea2…59ff67fcf` | **+$85,102** | $13.5M | $88,622 |
| 4 | **Lavincey** | `0x1cdd071b…697de595` | **+$72,557** | $30.5M | $44,508 |
| 5 | **Corlys** | `0xd23f8c8a…faf9894a1` | **+$62,663** | $4.9M | $2,102 |
| 6 | **OnlyLuckNoBrain** | `0x6a8d1709…278350f9` | **+$27,617** | $2.0M | $8,784 |
| 7 | **badatmath.** | `0x8fbd7cf5…7229a959` | **+$25,407** | $1.5M | $16,107 |
| 8 | **HighTempTation** | `0x6011655c…73466b31e` | **+$18,671** | $0.47M | $6 |

> 注：`HighTempTation` 是本仓库上一轮重点分析的对象，放在这里做交叉验证——它在天气专家里其实**规模偏小**（盈利第 8、成交量最低），但**单笔最大、最“职业”**（见 §6）。

---

## 5. 头部专家的交易习惯（量化画像）

下表为各赢家的天气交易习惯（来自 `winner_profiles.json`；`entryHrs` = 下单时点距结算的中位小时数，越大=越早进场）：

| 别名 | 天气占比 | 天气量 | 平均单笔 | 卖出比 | 赎回数 | 城市数 | 方向 | 主价格档 | entryHrs(中位) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- | ---: |
| Poligarch | 93.7% | $18.7k | $5.9 | 0.00 | 104 | 48 | Yes/No 各半 | 全档分散 | **11.2**（晚） |
| 0xfBd8C9C2 | 53.6% | $15.0k | $9.6 | 0.02 | 111 | 46 | **97% No** | >90¢ 为主 | 11.8（晚） |
| ultralisk | 31% | $1.9k | $2.8 | 0.00 | 614 | 46 | 77% Yes | **<10¢ 尾部** | 38.9（早） |
| Lavincey | 31.7% | $4.8k | $5.5 | 0.00 | 1 | 49 | 偏 Yes | 10–40¢ | 27.8 |
| Corlys | 32.8% | $5.9k | $8.9 | 0.00 | 5 | 34 | **99.7% No** | >90¢ 为主 | 29.7 |
| OnlyLuckNoBrain | 100% | $20.7k | $6.4 | 0.07 | 238 | 47 | 73% Yes | 10–40¢+尾部 | **44.3**（最早） |
| badatmath. | 100% | $12.3k | $3.8 | 0.00 | 27 | 45 | Yes/No 各半 | 10–40¢ | 15.5 |
| HighTempTation | 99.6% | $441.8k | **$176.9** | **0.67** | 7 | 43 | **96% No** | >90¢ 为主 | 13.1 |

---

## 6. 盈利天气打法的风格分类

把上面的习惯归纳，盈利天气交易者落在三类（与 [POLYMARKET_TRADER_PROFILING.md](POLYMARKET_TRADER_PROFILING.md) 的 taxonomy 对齐）：

### 风格 A：NO 收敛派 / 高确定性消化（High-probability resolution scalper）
代表：**0xfBd8C9C2、Corlys、HighTempTation**

- 几乎只买 **No**（97–99.7% No），价格集中在 **>90¢**。
- 逻辑：在临近结算、某些温度桶已经几乎不可能命中时，**买它的 No / 卖它的 Yes**，吃 `0.95 → 1.00` 的收敛。
- 胜率极高（HighTempTation 事件胜率约 98.8%、Profit Factor ~6.6），单笔利润薄。
- **HighTempTation 是其中最“职业”的**：卖出比 0.67（主动兑现而非死等结算）、平均单笔 $177（远大于其他人的个位数美元），即“先建仓 → 收敛时主动卖出”。

### 风格 B：YES 预报派 / 早进场分布下注（Weather forecast arb）
代表：**OnlyLuckNoBrain、badatmath.、Poligarch（双向版）**

- 偏买 **Yes**、价格在 **10–40¢**（即“被低估的、有一定概率命中的桶”）。
- **进场更早**：OnlyLuckNoBrain 中位 44h、ultralisk 39h——在数值天气模型已给出信息、但市场还没完全定价的窗口建仓，**持有到结算**（赎回数高、卖出比≈0）。
- edge 来自预报，而非临门收敛。

### 风格 C：长尾彩票 / 广撒小注（Long-tail mispricing hunter）
代表：**ultralisk（部分）、Lavincey**

- 大量 **<10¢ 的便宜 Yes 尾部**、单笔极小（$2–3）、几百上千笔、广覆盖所有城市。
- 多数归零，靠少数大赔率命中拉正期望。注意这两位的**真正利润大部分来自天气以外的盘**（天气占比仅 ~31%、天气名义量很小），更像“广撒 + 全品类做市/搬砖”的通才。

---

## 7. 所有赢家的共性习惯（最值得记的部分）

1. **极致广度，系统化而非主观**：每人覆盖 **34–49 个城市、几乎全部当日事件**。这不是“我懂纽约天气”，而是“我有一套模型扫全球”。这是天气赛道盈利的第一前提。
2. **专注 `Highest temperature`**：纯天气专家 100% 集中在“最高温”事件（少数兼做 lowest）。
3. **小额、多笔、分散**：除 HighTempTation 外，平均单笔仅 **$3–10**，靠成百上千笔分散，而不是单笔重仓。
4. **大多持有到结算**（卖出比≈0、赎回数高）；只有 HighTempTation 这类“主动兑现派”卖出比高。
5. **进场时点分两派且都成立**：
   - **早派（≈36–44h）**：吃预报 edge（OnlyLuckNoBrain、ultralisk）。
   - **晚派（≈11–13h）**：吃临门收敛 / NO 确定性（Poligarch、0xfBd8C9、HighTempTation）。

---

## 8. 与本仓库自有研究的交叉验证（重要）

本仓库的 Madrid PMXT 回测结论是：**`24–36h` 是天气预报 edge 最强的进场窗口**（`36h` 全样本与测试段都最优，见 [WEATHER_AND_TRADER_INSIGHTS_2026-06-21_CN.md](WEATHER_AND_TRADER_INSIGHTS_2026-06-21_CN.md)）。

本轮**独立地**从最赚钱的“早派预报交易者”实盘行为里看到：

- OnlyLuckNoBrain 中位进场 **44.3h**、ultralisk **38.9h**、Lavincey/Corlys/badatmath 在 **15–30h**。

也就是说，盈利预报派的实盘进场时点正好**包住了我们回测得出的 24–36h 最优窗口**。这等于用“别人的真金白银”交叉验证了我们自己的 `36h` 结论——这是本轮最有价值的连接点。

---

## 9. 可复制 / 不可复制

**可以借鉴的（习惯层面）：**

- 把天气当成**组合化、系统化、多城市**的业务来做，而不是单点押注。
- 单笔小、笔数多、分散到几十个城市，控制单事件风险。
- 明确选边：要么做“早派 YES 预报”（需要真模型，进场 24–36h），要么做“晚派 NO 收敛”（需要纪律和对盘口的理解，进场 <13h）。

**不要照抄的（表象层面）：**

- 不要只看“98% 胜率”就去买 99.9¢ 的 No——没有定价判断的话，你只是在临门给别人提供流动性（参见亏 $18 万的 `pootytherewardfarmer`、亏的 `L.X`）。
- 不要用 volume / win-rate 单列选人；先看终身 PnL。
- 高换手、主动兑现（HighTempTation 模式）需要单笔更大、对收敛节奏判断更准，新手照抄风险高。

---

## 10. 复现步骤

```bash
# 1. 发现反复出现的天气钱包
python3 research/predictparity_weather_discover.py
# 2. 画像头部钱包的交易习惯
python3 research/predictparity_weather_profile.py
# 3. 用现金流重算 PnL / 胜率（再配合 lb-api 官方 PnL 排名）
python3 research/predictparity_weather_pnl.py
```

原始 JSON 落在 `research/data/weather_traders/`（gitignore）。所有口径均为 `2026-06-21` 快照。

---

## 11. 局限与下一步

- 终身 PnL 用 `lb-api/profit`（全市场），对纯天气钱包 ≈ 天气 PnL；对天气占比仅 ~31% 的 ultralisk/Lavincey 会高估其“天气 edge”，已在 §6 标注为通才。
- `/activity` 分页有上限，极早期历史可能截断；进场时点用“结算日 23:00 UTC”近似。
- 下一步最值得做：
  1. 给“早派 YES 预报”钱包（OnlyLuckNoBrain、badatmath）做**逐城市命中率**拆解，看他们在哪些城市最强，与我们 Madrid/多城市回测对照。
  2. 跟踪 `Poligarch`（头号）的**逐日 PnL 曲线**（`user-pnl-api`），判断其 edge 是否在衰减。
  3. 把“晚派 NO 收敛”策略在我们自己的 PMXT 盘口数据上做成本敏感回测，验证 `<13h` 窗口净收益（扣点差）是否为正。
