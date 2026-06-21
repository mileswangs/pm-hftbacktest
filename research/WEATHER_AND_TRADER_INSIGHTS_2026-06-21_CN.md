# Weather 与 Trader Profiling 工作记录

日期：`2026-06-21`

本文档记录本轮在 `pm-hftbacktest` 仓库内完成的工作，重点包括：

1. Madrid PMXT weather 回测复核
2. `36h` 窗口为什么当前最好
3. 更细小时网格回测的推进情况与瓶颈
4. Polymarket trader profiling 固定框架
5. 对地址 `0x6011655c4afb76f36dd1b08a137a1ba73466b31e` 的风格分析

---

## 1. 已完成的核心工作

### 1.1 Madrid PMXT 回测结果复核

已复核文件：

- [madrid_pmxt_weather_backtest_summary.json](/Users/wujinze/Desktop/pm-hftbacktest/research/data/pmxt_weather/madrid_pmxt_weather_backtest_summary.json)
- [madrid_pmxt_entry_snapshots.parquet](/Users/wujinze/Desktop/pm-hftbacktest/research/data/pmxt_weather/madrid_pmxt_entry_snapshots.parquet)

当前基线结果：

| entry hour | traded | hit rate | total pnl | avg pnl |
| --- | ---: | ---: | ---: | ---: |
| `6h` | 54 | 70.37% | 1.6720 | 0.0310 |
| `12h` | 54 | 72.22% | 1.9380 | 0.0359 |
| `18h` | 52 | 71.15% | 0.4330 | 0.0083 |
| `24h` | 49 | 82.00% | 4.2400 | 0.0865 |
| `36h` | 51 | 84.31% | 6.0700 | 0.1190 |

结论：

- `36h` 仍然是当前 Madrid 样本内最强窗口。
- `24h` 是第二强窗口。
- 短窗口 `6/12/18h` 明显弱于 `24/36h`。

### 1.2 Walk-forward 检查

做了一版无未来函数的时间切分检查。

方法：

- 按 `target_date` 做时间切分
- 前 `34` 天作为训练段
- 后 `22` 天作为测试段

结果：

| entry hour | mode | test traded | test pnl | test hit |
| --- | --- | ---: | ---: | ---: |
| `24h` | ask | 15 | 1.56 | 86.67% |
| `24h` | mid | 15 | 2.56 | 93.33% |
| `36h` | ask | 17 | 4.33 | 100.00% |
| `36h` | mid | 17 | 4.66 | 100.00% |

结论：

- `36h` 不只是全样本最优，在测试段里依然最强。
- `mid` 比 `ask` 更适合做信号。
- 真实执行仍应以 `ask` 估计成本，不能直接把 `mid` 当成交价。

### 1.3 微观结构与失败样本检查

做了两类诊断：

1. 微观结构检查
2. 失败样本温度偏移检查

微观结构观察：

- 各窗口 median spread 大致在 `0.005-0.01`
- staleness filter 基本没有带来明显增益
- tighter spread filter 反而可能伤害收益

这说明：

- 当前优势不是靠“捡非常脏的盘口”
- 更像是方向判断有 edge

失败样本观察：

#### `24h`

- 共 `8` 次亏损
- 其中 `7` 次只差 `1°C`
- 仅 `1` 次差 `4°C`

#### `36h`

- 共 `8` 次亏损
- `4` 次差 `1°C`
- `2` 次差 `2°C`
- `1` 次差 `4°C`
- `1` 次差 `5°C`

这说明：

- `36h` 不是每次都“看错很多”
- 但它确实带有更胖的尾部风险
- 它的主要风险不是连续小亏，而是少数 regime shift 式的偏差

---

## 2. 为什么 `36h` 目前最好

这是本轮最重要的策略 insight。

### 2.1 事实层面的依据

当前能确认的硬事实有四条：

1. `36h` 在全样本中 `total pnl` 和 `avg pnl` 都最高。
2. `36h` 在测试段仍然比 `24h` 强。
3. `36h` 的优势并不是由 stale/spread filtering 驱动。
4. `36h` 的大多数失败不是完全离谱，而是边界附近的 `1-2°C` 偏差。

### 2.2 更合理的机制解释

从结果推断，`36h` 最像处在这样一个窗口：

- 数值天气模型已经开始提供较强可用信息
- 市场还没有完全把这些信息压进价格
- 因而仍存在概率修正空间

而到了 `24h` 左右：

- 市场更接近充分定价
- 你虽然 still 有 edge，但 edge 已经被压薄

这里要强调：

- 这是根据结果与公开资料做出的推断
- 不是直接来自某个单一来源的明文结论

### 2.3 对真实交易的意义

`36h` 可以做，但它不是轻松的日内型机会。

如果真实交易：

- 它更像一笔短周期 swing
- 需要接受跨两个昼夜的持仓
- 需要接受少数较大的天气 regime shift 风险

如果你更看重：

- 资金占用短
- 周转快
- 心理压力低

那 `24h` 会更现实。

如果你更看重：

- 单笔 edge 更厚
- 愿意接受时间更长的持仓

那 `36h` 仍然值得重点研究。

---

## 3. 更细小时网格的工作进展

### 3.1 已完成的代码修改

已修改：

- [run_madrid_pmxt_backtest.py](/Users/wujinze/Desktop/pm-hftbacktest/research/run_madrid_pmxt_backtest.py)

新增能力：

- 支持自定义 `--entry-hours`
- 支持自定义 `--output-stem`
- 支持自定义 `--workers`
- 可以在不覆盖基线文件的前提下，跑细网格版本

这一步很重要，因为后续：

- 可以单独跑 `24h-42h`
- 可以只跑 `30/33/36/39h`
- 可以把不同实验结果分文件保存

### 3.2 为什么细网格还没有完整跑穿

根本原因不是本地算力，而是 PMXT 数据层吞吐。

观察到的现实情况：

- PMXT 单小时原始 parquet 常见是 `300MB` 级别
- `30h/33h/39h` 这种非既有整点窗口，需要补很多此前未提取的小时切片
- 远端 hydrate 与本地过滤速度明显慢于本地回测本身

这意味着：

- 回测逻辑不是瓶颈
- 原始 PMXT 小时数据准备才是瓶颈

### 3.3 当前细网格阶段性结果

我先用当前本地已覆盖数据，对 `30h / 33h / 36h` 做了局部比较。

阶段性结果：

| entry hour | events | traded | hit rate | total pnl | avg pnl |
| --- | ---: | ---: | ---: | ---: | ---: |
| `30h` | 10 | 10 | 80.00% | 0.99 | 0.099 |
| `33h` | 11 | 11 | 72.73% | 0.44 | 0.040 |
| `36h` | 51 | 51 | 84.31% | 6.07 | 0.119 |

这组结果还不能下最终结论，因为：

- `30h` 和 `33h` 的可用样本还太少
- 它们缺的 PMXT 小时切片还没有补完

但它至少说明：

- 在当前已覆盖部分里，`36h` 没有被 `30h/33h` 轻易击败
- `36h` 不是一个一碰细化就立刻崩塌的假最优

### 3.4 下一步最合理的推进方式

不要再全范围乱扫。

应该只围绕：

- `24h`
- `27h`
- `30h`
- `33h`
- `36h`
- `39h`
- `42h`

做定向补数与回测。

原因：

- 这才是和真实交易决策最相关的窗口带
- `6/12/18h` 已经可以确认不是最佳主战场

---

## 4. Trader Profiling 固定框架

已新增文档：

- [POLYMARKET_TRADER_PROFILING.md](/Users/wujinze/Desktop/pm-hftbacktest/research/POLYMARKET_TRADER_PROFILING.md)

### 4.1 为什么要有这个固定框架

后续用户可能会持续给出新的 Polymarket 地址，希望快速回答：

- 这个人怎么赚钱
- 属于哪一派
- 胜率为什么高
- 是 forecast trader、carry trader、arb trader，还是 market maker

如果每次都临时发挥：

- 浪费 token
- 输出口径不稳定
- 很难积累统一标签体系

所以这里做了一个轻量、固定、可复用的 profiling 流程。

### 4.2 固定输出 schema

后续建议固定返回：

- `wallet`
- `alias`
- `as_of_date`
- `primary_style`
- `secondary_style`
- `confidence`
- `core_evidence`
- `risk_notes`
- `what_they_are_actually_doing`

### 4.3 当前设定的主要流派

文档里定义了以下核心风格：

- `High-probability resolution scalper`
- `Weather forecast arb`
- `Long-tail mispricing hunter`
- `Momentum/news trader`
- `Passive carry / event carry`
- `Market maker / spread recycler`

这个分类不是为了学术完美，而是为了实用：

- 足够区分主要赚钱机制
- 足够轻量
- 适合后续批量分析钱包

---

## 5. 地址 `0x6011655c4afb76f36dd1b08a137a1ba73466b31e` 的分析

别名：

- `HighTempTation`
- `@hightemptation`

主要参考来源：

- [Polydata trader page](https://polydata.pro/traders/hightemptation)
- [Predicts.guru checker search result](https://www.predicts.guru/checker/0x6011655c4afb76f36dd1b08a137a1ba73466b31e)
- Struct explorer 市场页样本

### 5.1 结论先行

我给这个地址的分类是：

- `Primary: Weather forecast arb`
- `Secondary: Active exit sniper / high-probability monetizer`

它不是最典型的“纯猜方向型 trader”。

它更像：

1. 利用天气市场定价错误建立仓位
2. 再在市场极度收敛时主动卖出兑现
3. 通过高命中率、小到中等单笔利润、频繁实现收益来堆积 PnL

### 5.2 为什么他的胜率这么高

不同平台口径不同，但大方向一致：

- Polydata：截至 `2026-06-18 14:23`
  - `1169 trades`
  - `638 markets`
  - `98% weather`
  - `245W / 8L`
  - `96.8%` trade win rate
  - `193W / 0L` event win rate
- Predicts.guru 搜索摘要：
  - 几乎全是 weather
  - 高胜率
  - 大量 closed trades

关键 insight：

他的高胜率不是靠搏高赔率，而是靠“主动兑现”。

### 5.3 最关键的证据

#### 证据 1：极高 weather concentration

Polydata 直接给出：

- `98% weather`

这说明他不是泛市场交易员，而是单赛道 specialist。

#### 证据 2：高 sell ratio

Polydata 给出：

- `355B / 814S`
- sell 占比很高

这很重要。

如果一个 trader：

- 主要靠持有到结算
- 纯买入等待兑现

那么 sell ratio 往往不会这么高。

这里更像：

- 先建仓
- 再在更高确定性的价格区间主动平仓

#### 证据 3：Struct 市场页显示大量 `No / 99.9¢`

多个 Struct 市场样本里都能看到：

- `HighTempTation`
- `No / 99.9¢`
- 且经常表现为负 shares

这更像卖出或退出，而不是简单追高买入。

样本链接：

- [Taipei 33C on May 22](https://explorer.struct.to/markets/highest-temperature-in-taipei-on-may-22-2026-33c)
- [Istanbul 17C on May 22](https://explorer.struct.to/markets/highest-temperature-in-istanbul-on-may-22-2026-17c)
- [Singapore 31C on May 25](https://explorer.struct.to/markets/highest-temperature-in-singapore-on-may-25-2026-31c)

#### 证据 4：盈亏结构像高胜率兑现型系统

Polydata 给出的盈亏结构：

- `Avg Win $66`
- `Avg Loss -$82`
- `Profit Factor 24.61x`

这表示：

- 胜率极高
- 但一旦错，并不是没有伤害
- 说明不是无风险 carry，而是“高命中 + 少量尾部损失”

### 5.4 他实际在做什么

最可能的真实 playbook：

1. 只做 weather，说明他有专门的外部信息或模型流程。
2. 在具体城市、具体温度桶上建立方向。
3. 不是被动等结算，而是高概率区间主动卖出。
4. 通过很多笔高命中、小中型利润累积 PnL。

一句话总结：

他不是靠“98% 的神迹预测”赚钱，而是靠：

`weather specialization + timing discipline + active monetization`

### 5.5 不应该误学的地方

不能只复制表面胜率。

因为这个地址背后的难点在于：

- 你要先有天气市场的定价判断能力
- 你要知道何时建仓
- 还要知道何时卖出兑现

如果只学到：

- “去买 99.9¢”

那大概率只会变成替别人提供流动性，而不是复制他的 edge。

---

## 6. 对 Polymarket 常见交易模式的总结

结合公开资料与当前观察，Polymarket 上最常见、也最值得跟踪的模式大概有这些：

### 6.1 Weather / model arb

- 用外部 forecast / model / data 与市场概率做比较
- weather 是最典型场景

### 6.2 Event-based discretionary

- 对某个领域有深研究
- 先判断事件本身，再择时建仓

### 6.3 Momentum / news trading

- 跟价格趋势与新闻流走
- 持仓短
- 非常依赖速度

### 6.4 Late-resolution carry

- 接近结算才进
- 赚最后几分钱
- 胜率往往高，但单位资金收益薄

### 6.5 Cross-market / cross-platform arb

- 同一事件不同市场之间的价差
- 或跨平台搬砖

### 6.6 Market making / spread recycle

- 高频双边挂单
- 依靠 spread 与 inventory 管理赚钱

### 6.7 Long-tail mispricing hunting

- 买便宜尾部
- 胜率低但赔率高
- 常见于便宜 bucket 或低概率极端事件

### 6.8 当前最值得做的实际研究方向

对我们这个仓库来说，最值得继续深化的是：

- weather specialist wallets
- 是否倾向主动止盈
- 是否集中在某些城市
- 是否围绕 forecast update cycle 交易

原因：

- 这和我们自己的 Madrid weather 研究直接同源
- 可以互相验证
- 更容易沉淀成可执行策略，而不是停留在泛泛观察

---

## 7. 当前阶段的最终判断

### 关于 Madrid

- `36h` 目前仍然是最强窗口。
- `24h` 是更现实的备选窗口。
- `36h` 不是假最优，但需要继续用细网格验证周边窗口。

### 关于 trader profiling

- 固定框架已经搭好。
- 后续可以低 token 成本地持续分析新钱包。

### 关于 `HighTempTation`

- 本质不是“神预测”
- 而是 weather specialist + 主动兑现型 trader

这比单纯看一个 `98%` 胜率有用得多。

真正值得学的不是：

- “他胜率很高”

而是：

- “他靠什么结构把胜率抬高”
- “他在哪一类市场里稳定重复这个动作”
- “他的高胜率是不是来自主动 exit，而不是简单 hold to resolve”

这才是后续能转成系统化研究的部分。
