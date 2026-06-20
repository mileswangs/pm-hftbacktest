# pm-hftbacktest · Frontend

A standalone web UI for the [pm-hftbacktest](../README.rst) Polymarket backtesting
engine. Configure a strategy, run a backtest, and inspect metrics, equity &
position curves, the trade log, run history, and a two-run comparison.

The frontend is **fully decoupled from the backend**. It ships working
out-of-the-box against a built-in mock adapter (deterministic, offline), and can
be pointed at a real Python backend without changing any UI code.

Aesthetic: a warm "paper ledger" quant workbench — cream/espresso tones,
Fraunces + IBM Plex Mono, a single terracotta accent.

## Quick start

```bash
cd frontend
npm install
npm run dev      # http://localhost:5173
```

Other scripts:

```bash
npm test         # run the Vitest suite (48 tests)
npm run typecheck
npm run build    # type-check + production build to dist/
```

> **Node version:** the toolchain is pinned to the Rollup-based **Vite 5** line so
> it runs on Node 21 as well as Node 20.19+/22+. (Vite 8/rolldown requires
> Node 20.19+ or 22.12+ and will not load its native binding on Node 21.)

## Architecture — decoupling

The UI depends only on the `BacktestService` interface. Adapters are
interchangeable behind it.

```
 UI components ──▶ BacktestService (interface)
                       ├── mockAdapter   deterministic sample data, offline
                       └── httpAdapter   POST /api/backtest  (real backend)
```

Key files:

| Path | Responsibility |
|------|----------------|
| `src/services/types.ts` | Data contract (`BacktestConfig`, `BacktestResult`, `MetricSet`, `SeriesPoint`, `Trade`) |
| `src/services/BacktestService.ts` | The `run(config) → Promise<BacktestResult>` interface |
| `src/services/mockAdapter.ts` | Built-in deterministic adapter (seeded by config) |
| `src/services/httpAdapter.ts` | `POST /api/backtest` adapter + error handling |
| `src/services/index.ts` | `getService(kind)` — selects the adapter |
| `src/services/metrics.ts` | Metric computation (Sharpe, Sortino, drawdown, …) |
| `src/strategies/registry.ts` | Strategy definitions + param specs (drive the form) |
| `src/hooks/useBacktestRuns.ts` | Run state, history (localStorage), compare selection |
| `src/charts/LineChart.tsx` | Reusable dependency-free SVG line chart |
| `src/components/*` | Presentational UI (config, metrics, charts, trades, sidebar, compare) |
| `src/pages/Dashboard.tsx` | Composition root |

Switch the adapter at runtime from the **Adapter** dropdown in the top bar
(`Mock` ↔ `HTTP`).

## Connecting a real backend

1. In the UI, set the Adapter dropdown to **HTTP** (or change the default in
   `src/services/index.ts`).
2. Implement an HTTP endpoint `POST /api/backtest` that accepts a
   `BacktestConfig` JSON body and returns a `BacktestResult` JSON.
3. The field names in `src/services/types.ts` map **1:1** to the Python
   `hftbacktest` record (`timestamp`, `price`, `position`, `equity_wo_fee`,
   `fee`) plus `hftbacktest.stats` metrics (`SR`, `Sortino`, `Ret`,
   `MaxDrawdown`, `ReturnOverMDD`, `MaxPositionValue`, …) and `earn`. A thin
   FastAPI wrapper that runs a strategy and serializes `Recorder` output +
   `PolyAssetRecord(...).stats(...)` is enough.

Example backend contract:

```jsonc
// POST /api/backtest  (request body = BacktestConfig)
{ "slug": "btc-updown-15m-1778263200", "strategy": "endline",
  "params": { "up_trigger": 0.84, "stop_long": 0.4, "order_qty": 5 },
  "bookSize": 100, "resample": "1s" }

// 200 response body = BacktestResult
{ "id": "...", "config": { ... }, "createdAt": 1718000000000,
  "series": [ { "timestamp": 1718000000000, "price": 0.5, "position": 0,
               "equityWoFee": 0, "fee": 0, "equity": 0 } ],
  "trades": [ { "timestamp": 1718000000000, "side": "buy", "price": 0.6, "qty": 5 } ],
  "metrics": { "earn": 0, "sr": 0, "sortino": 0, "ret": 0, "maxDrawdown": 0,
               "dailyNumberOfTrades": 0, "returnOverMdd": 0, "maxPositionValue": 0 } }
```

## Adding a strategy

Add an entry to `STRATEGIES` in `src/strategies/registry.ts` with a param
schema. The config form, validation, and defaults update automatically.
