# Weather LP Feasibility

Date checked: `2026-06-19`

## What was built

- `research/weather_lp_scanner.py`
  - Fetches current reward configs from `GET /rewards/markets/current`
  - Joins them to Gamma markets
  - Filters weather-style markets
  - Emits a coarse LP viability classification

## Repro

```bash
python3 research/weather_lp_scanner.py --page-size 100
```

## Current result

As of `2026-06-19`, the scanner finds reward-bearing weather/climate markets, but not the city-temperature contracts we tested for directional trading.

Observed rewarded weather/climate markets:

- `min-arctic-sea-ice-extent-this-summer`
  - `<4m sq km` looked like the best current LP candidate
  - One bucket had a visible spread inside the reward cutoff with midpoint near `0.50`
- `where-will-2026-rank-among-the-hottest-years-on-record`
  - Reward rate was effectively dust (`0.001/day`)

Observed non-result:

- Chengdu temperature event buckets had `weather_fees`, `rewardsMinSize`, and `rewardsMaxSpread` fields on the market object
- But they had no overlap with the current active rewards sets
- Therefore: no current LP reward pool was live on the Chengdu daily temperature ladder

## Feasibility conclusion

This is feasible in principle, but conditional in practice.

Why feasible:

- Polymarket exposes a public rewards config API
- Rewards are formulaic and documented
- Order scoring status and real-time reward percentages are available with authenticated CLOB access
- Weather markets already expose reward-related market metadata

Why conditional:

- Weather rewards are not always active
- Even when active, some buckets are too extreme, so the rules favor two-sided quoting and inventory risk rises sharply
- If the visible spread is already wider than the reward cutoff, you must improve the book to score

## Practical implication

The right architecture is:

1. Scan current rewards
2. Filter to weather/climate
3. Rank markets by:
   - `total_daily_rate`
   - visible spread vs reward cutoff
   - midpoint extremity
   - liquidity / competition
4. Only then decide whether to deploy LP capital

Directional weather trading and LP farming should be treated as separate strategies that can later be combined into a biased quoting model.
