# PMXT Weather Pipeline

This pipeline builds a weather-only local dataset from the public PMXT Polymarket archive.

## Why this exists

The public `prices-history` endpoint is useful for quick scans, but it is too limited for larger historical weather research:

- it gives last-price style history, not full execution-aware book updates
- it does not scale well when you want many cities and longer windows
- it cannot replace actual hourly orderbook event archives

PMXT v2 fixes that by publishing hourly parquet files for the full Polymarket CLOB stream.

## Source assumptions

Based on the PMXT v2 public docs:

- archive starts at `2026-04-13T19:00 UTC`
- one parquet file per UTC hour
- public HTTPS, no credentials required
- direct pattern:
  - `https://r2v2.pmxt.dev/polymarket_orderbook_YYYY-MM-DDTHH.parquet`

## What the script does

Script:

- [pmxt_weather_data.py](/Users/wujinze/Desktop/pm-hftbacktest/research/pmxt_weather_data.py)

It has three subcommands:

1. `catalog`
   - fetches historical weather events from Gamma
   - records `city/date/event_slug/bucket/condition_id/yes_token_id`

2. `extract`
   - computes the hourly PMXT files needed for each event
   - downloads each parquet
   - filters rows to weather `asset_id`s only
   - merges PMXT rows with weather market metadata
   - writes cleaned weather-only parquet files

3. `stats`
   - summarizes extraction status from the manifest

## Output layout

Default local output directory:

- `research/data/pmxt_weather/`

Files written there:

- `weather_market_catalog.json`
- `pmxt_weather_manifest.json`
- `weather_hourly/*.weather.parquet`
- optionally `raw_cache/*.parquet` if `--keep-raw` is used

## Commands

Build a catalog:

```bash
python3 research/pmxt_weather_data.py catalog \
  --cities chengdu \
  --start-date 2026-06-10 \
  --end-date 2026-06-10
```

Extract PMXT weather rows:

```bash
python3 research/pmxt_weather_data.py extract \
  --catalog research/data/pmxt_weather/weather_market_catalog.json \
  --cities chengdu \
  --start-date 2026-06-10 \
  --end-date 2026-06-10 \
  --lookback-hours 48
```

Summarize results:

```bash
python3 research/pmxt_weather_data.py stats
```

## Current validated sample

A small validated local sample already exists:

- catalog: `research/data/pmxt_weather/weather_market_catalog.json`
- filtered parquet:
  - `research/data/pmxt_weather/weather_hourly/2026-06-10T12.weather.parquet`

Validation result on that hour:

- rows: `4831`
- event types:
  - `price_change`: `4781`
  - `book`: `48`
  - `last_trade_price`: `2`

## Practical guidance

- Start with one city and one short date range.
- Increase `lookback_hours` only as needed for your strategy horizon.
- Do not try to ingest every PMXT hour for every city immediately.
- First build the weather catalog, then pull only the event windows you actually need.

## Important limitation

This pipeline now gets you from PMXT raw parquet to weather-only cleaned parquet.

It still does **not** yet build:

- reconstructed best-ask snapshots at entry timestamps
- size-aware dual-leg fill simulation
- final execution-aware backtest outputs

That is the next layer to build on top of these cleaned weather parquet slices.
