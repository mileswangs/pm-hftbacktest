# Weather Research Handoff — 2026-06-20

This document captures the current state of the weather research and frontend work in this repository so another machine or Codex session can resume without rebuilding context.

## Branch and status

- Working branch: `frontend-backtester`
- Intended final destination: `main`
- Frontend dev server was previously run on port `9120`

## What was implemented

### 1. Weather alpha backtest scripts

- `research/weather_backtest.py`
  - Public Gamma + CLOB price-history event backtest.
  - Strategy:
    - If one bucket probability > `threshold`, buy that bucket.
    - Else buy top two buckets if combined probability > `threshold`.
    - Hold to settlement.
- `research/build_weather_dashboard_data.py`
  - Builds frontend-ready JSON datasets.
  - Now enriches each outcome with market-capacity proxy fields:
    - `volume`
    - `volume24hr`
    - `liquidity`
    - `spread`
    - `bestBid`
    - `bestAsk`
    - `lastTradePrice`
    - `rewardsMinSize`
    - `rewardsMaxSpread`
    - `orderMinSize`
    - `orderPriceMinTickSize`
  - Fixed target-date parsing to use the event slug rather than `endTimeUtc`, which avoided timezone-crossing date errors for Madrid and similar markets.
- `research/build_weather_city_library.py`
  - Builds a local city archive under `frontend/public/data/weather/`.
  - Generates `manifest.json` plus one dataset per city.
- `research/multi_city_weather_scan.py`
  - Multi-city scan across a preset city list and multiple entry hours.

### 2. Frontend weather research workspace

- `frontend/src/pages/WeatherResearchPage.tsx`
  - Weather page is now a research workspace rather than only a single-day chart.
  - Supports:
    - local city archive loading from `frontend/public/data/weather/manifest.json`
    - city switching that actually swaps the loaded dataset
    - full backtest overview for a chosen entry hour
    - event timeline table
    - daily drill-down chart with buy markers
    - alpha notes
    - capacity and friction proxies
    - conservative execution reality check with user-adjustable assumptions
  - Conservative controls currently include:
    - `Slip / leg`
    - `Fee / leg`
    - `Max stale min`
    - `Min updates 6h`
  - Conservative metrics currently shown:
    - raw cumulative pnl
    - conservative cumulative pnl
    - blocked trades
    - max drawdown
    - max concurrent capital
    - average conservative cost
- `frontend/src/pages/WeatherResearchPage.css`
  - Added layout styles for the research dashboard, event timeline, city archive board, and conservative execution sections.
- `frontend/src/weather/buildDataset.ts`
  - Browser-side dataset builder mirrors the Python logic.
  - Also fixed target-date parsing from event slug.
- `frontend/src/weather/types.ts`
  - Expanded weather dataset types with `marketStats` and local archive manifest types.
- `frontend/src/weather/cityCatalog.ts`
  - Shared tested city preset list.

### 3. Local weather archive

Local city archive exists under:

- `frontend/public/data/weather/`

Cities included:

- `beijing`
- `chengdu`
- `guangzhou`
- `hong-kong`
- `london`
- `los-angeles`
- `madrid`
- `paris`
- `seoul`
- `shanghai`
- `shenzhen`
- `singapore`
- `taipei`
- `tokyo`

The archive is intended for research convenience rather than permanent canonical storage.

## Prior conclusions already established

### Chengdu

- On the earlier `17`-day window ending `2026-06-19`, Chengdu looked best at `12h`.
- This was one of the user’s original observations and was preserved in the frontend sample work.

### Multi-city

The weather signal does not generalize with one single global entry hour. It is city-specific.

### LP research

Separate LP research scripts and docs were added earlier:

- `research/weather_lp_scanner.py`
- `research/weather_lp_backtest.py`
- `research/WEATHER_LP_FEASIBILITY.md`
- `research/WEATHER_LP_BACKTEST.md`

The main conclusion was:

- Weather/climate LP rewards can be selectively viable.
- They are not broadly attractive without careful market selection.

## Current Madrid status

### Archive range

The Madrid local archive was extended as far back as public event discovery currently supports:

- earliest event found: `2026-03-16`
- latest event in current archive: `2026-06-19`

Current archive file:

- `frontend/public/data/weather/madrid.json`

### Important nuance

There is a difference between:

- event existence
- strategy-tradable history

For Madrid:

- Events exist back to `2026-03-16`.
- But the `36h` strategy only becomes tradable on `2026-05-22`.

Reason:

- Earlier events do not have usable price history far enough before settlement to support a `36h` entry.
- These early rows are therefore `skip_no_prices`, not missing events.

The first tradable dates by entry hour were checked:

- `6h` first tradable: `2026-05-20`
- `12h` first tradable: `2026-05-21`
- `18h` first tradable: `2026-05-21`
- `24h` first tradable: `2026-05-21`
- `36h` first tradable: `2026-05-22`

### Madrid expanded-window summary

Using the expanded window ending `2026-06-19`:

- days requested: `96`
- resolved events written: `93`
- missing dates in this archive window:
  - `2026-03-31`
  - `2026-05-17`
  - `2026-05-18`

Madrid summary by entry hour:

- `6h`: traded `31`, hit rate `67.74%`, total pnl `1.5335`
- `12h`: traded `30`, hit rate `76.67%`, total pnl `3.6950`
- `18h`: traded `30`, hit rate `76.67%`, total pnl `3.1800`
- `24h`: traded `30`, hit rate `96.67%`, total pnl `6.1300`
- `36h`: traded `27`, hit rate `100.00%`, total pnl `6.9800`

So Madrid remained strong after expanding the sample and `36h` stayed best under the current proxy-based method.

## Reality-check findings already added

The frontend now explicitly distinguishes:

- event existence
- traded events
- raw cumulative pnl
- conservative cumulative pnl

Current default conservative assumptions shown in the UI:

- slippage per leg: `0.015`
- fee per leg: `0.005`
- max stale minutes: `90`
- min updates in last 6h: `3`

Under these default assumptions, Madrid `36h` still looked positive:

- raw cumulative pnl around `3.67` on the earlier short window
- conservative cumulative pnl around `3.07`
- blocked trades `0`

This suggested Madrid was not immediately collapsing under a mild friction penalty, but this is still not a true ask-side execution replay.

## Most important current limitations

These are the key reasons the current backtest is still not production-grade:

1. `weather_backtest.py` uses public last-price history as the entry-price proxy, not the actual contemporaneous `ask`.
2. No true historical L2 replay is used in the current weather alpha scripts.
3. Dual-bucket fills are still treated as if both legs can be bought cleanly at the sampled proxy prices.
4. Fees and slippage are only approximated in the frontend “reality check”, not in the canonical Python backtest.
5. Sample selection risk remains:
   - multiple cities
   - multiple entry hours
   - best performer chosen after the fact

## PMDATA and PMXT investigation status

### PMDATA

The user provided a PMDATA key during the conversation.

What was confirmed:

- PMDATA works for known crypto slugs used elsewhere in the repo.
- PMDATA returned `404` for tested Madrid weather market slugs under:
  - `poly_l2/<weather-market-slug>.parquet`
  - `poly_trades/<weather-market-slug>.parquet`

Conclusion:

- PMDATA is not currently giving us the weather-market L2 history we want through the tested endpoints.

### PMXT

The user then asked whether PMXT could be used instead.

What was concluded:

- Yes, PMXT is the more promising path for realistic weather execution backtesting.
- PMXT archive structure is hourly parquet dumps for all Polymarket orderbook traffic.
- It is not pre-partitioned by weather, so the right design is:
  - build a weather market catalog first
  - scan hourly PMXT parquet files
  - keep only rows for weather-related `market` / `asset_id`
  - write a weather-only warehouse or local subset

Important PMXT caveat:

- v2 coverage starts around `2026-04-13T19:00 UTC`
- so PMXT v2 can improve post-`2026-04-13` weather execution research
- but it cannot fully recover the earliest Madrid event period back to `2026-03-16`

## Recommended next steps

The next highest-value work item is:

### Build a PMXT weather-only execution prototype

Suggested order:

1. Create a `weather market catalog`
   - map city/date/outcome to `condition_id` and `asset_id`
2. Build a Madrid-only PMXT extractor
   - scan hourly PMXT parquet
   - filter only Madrid weather markets
3. Reconstruct book snapshots at entry times
   - use actual best ask / depth
4. Replace proxy weather backtest with execution-aware backtest
   - size-aware
   - dual-leg fill-aware
   - partial-fill aware
5. Compare:
   - current proxy result
   - conservative friction model
   - true PMXT execution result

### Storage advice already given

- Do not ingest full PMXT archive unless needed.
- Build a weather-only subset instead.
- For local work, a few GB budget is likely feasible for a small weather-only slice.
- For larger-scale work, ClickHouse or object-storage plus DuckDB/ClickHouse is the right direction.

## Validation already completed

The following checks were run during this work:

- `frontend`: `npm run build`
- `frontend`: `npm test`
- Madrid archive rebuild after the date fix
- city archive manifest sync

At the time of writing, frontend build and tests were passing.
