# Weather Data Warehouse

This repository now has a normalized local weather-history warehouse in SQLite.

## Why it exists

The frontend city archives under `frontend/public/data/weather/` are useful for browsing, but they are not a good raw-data layer:

- each city file is several MB
- history is duplicated across derived JSON outputs
- rebuilding large windows forces repeated API fetches
- extending to more cities and longer date windows becomes awkward

The warehouse keeps the raw layers locally, then lets the existing export scripts build frontend datasets from that local store.

## Location

Default SQLite path:

- `research/data/weather_warehouse/weather.sqlite3`

Default sync report:

- `research/data/weather_warehouse/sync_report.txt`

## What is stored

Tables:

- `cities`
  - one row per configured city
- `events`
  - one row per discovered Polymarket weather event
- `outcomes`
  - one row per event outcome / temperature bucket
- `price_history`
  - one row per `(yes_token_id, timestamp)` price point

This is still based on the public Gamma + CLOB history path, not PMXT execution replay.

## Sync historical data

Example: sync a large local window for all default cities:

```bash
python3 research/weather_data_warehouse.py sync \
  --anchor-date 2026-06-19 \
  --days 120
```

Example: explicit date range for a few cities:

```bash
python3 research/weather_data_warehouse.py sync \
  --cities "madrid,london,paris" \
  --start-date 2026-03-01 \
  --end-date 2026-06-19
```

Inspect counts:

```bash
python3 research/weather_data_warehouse.py stats
```

## Build frontend datasets from the warehouse

Once the SQLite file exists, the existing builders automatically prefer it.

Single city:

```bash
python3 research/build_weather_dashboard_data.py \
  --city-slug madrid \
  --city-label Madrid \
  --anchor-date 2026-06-19 \
  --days 96 \
  --output frontend/public/data/weather/madrid.json
```

Multi-city library:

```bash
python3 research/build_weather_city_library.py \
  --anchor-date 2026-06-19 \
  --days 96
```

You can also override the DB path explicitly:

```bash
python3 research/build_weather_city_library.py \
  --warehouse-db /abs/path/to/weather.sqlite3
```

## Current scope

This warehouse solves the local-history organization problem. It does **not** yet solve execution realism.

Still missing for production-grade research:

- PMXT weather-only extractor
- real best-ask reconstruction at entry time
- size-aware and partial-fill-aware execution backtests
- dual-leg fill realism for pair trades

That should be the next layer built on top of this warehouse, not instead of it.
