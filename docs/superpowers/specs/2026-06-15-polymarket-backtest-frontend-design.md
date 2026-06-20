# Polymarket Backtester Frontend — Design

Date: 2026-06-15
Status: Approved pending spec review

## 1. Purpose

Build a standalone, functionally-complete-but-not-complex frontend for the
`pm-hftbacktest` (Polymarket HftBacktest) library. The page lets a user
configure a backtest (market + strategy + params), run it, and inspect the
results (key metrics, equity/position curves, trade list), with a small history
and a two-run comparison.

The frontend is **fully decoupled from the backend**. It ships working
out-of-the-box against a built-in mock adapter, and can later be pointed at a
real Python backend without changing any UI code.

## 2. Constraints & Non-Goals

- **Decoupling is the top priority.** UI depends only on a `BacktestService`
  interface, never on a concrete data source.
- Keep the page simple: one single-page app, no routing framework, no backend
  required to run.
- **Non-goals:** building the Python web backend, real strategy execution in the
  browser, authentication, persistence beyond `localStorage`, mobile-first
  layout (desktop-first is fine; stay responsive enough not to break).

## 3. Tech Stack

- **React + Vite + TypeScript** — component-based, fast dev, type-safe data
  contract.
- **Custom lightweight SVG line-chart component** for equity/position curves.
  Rationale: the charts are multi-line time series; hand-drawn SVG gives full
  design control and avoids a heavy chart dependency. (Fallback if interactivity
  grows: swap in `uPlot` behind the same chart props.)
- **No state library** — React hooks + a single context/hook
  (`useBacktestRuns`) are enough.
- Plain CSS (CSS variables for the palette). No CSS framework.

## 4. Architecture & Decoupling

```
frontend/
  src/
    services/
      types.ts            # BacktestConfig / BacktestResult / Metric / SeriesPoint / Trade
      BacktestService.ts  # interface { run(config): Promise<BacktestResult> }
      mockAdapter.ts      # deterministic sample data, varies with config, offline
      httpAdapter.ts      # POST /api/backtest, fields map 1:1 to Python record
      index.ts            # adapter selection (default: mock)
    strategies/
      registry.ts         # strategy definitions + param schemas (drives the form)
    charts/
      LineChart.tsx       # reusable SVG multi-line chart (crosshair + tooltip)
    hooks/
      useBacktestRuns.ts  # run state, history, localStorage persistence, compare selection
    components/
      TopBar.tsx
      HistorySidebar.tsx
      ConfigPanel.tsx
      ParamField.tsx
      MetricCards.tsx
      EquityChart.tsx     # wraps LineChart with equity/equity-wo-fee/price series
      PositionChart.tsx   # wraps LineChart with position/price series
      TradesTable.tsx
      CompareView.tsx
      ResultsPanel.tsx    # tabs: Charts | Trades; hosts metric cards + charts/table
    pages/
      Dashboard.tsx       # composition root
    theme.css             # light warm palette via CSS variables
    main.tsx
```

**Key boundary:** every component that needs a backtest calls
`service.run(config)` through the `BacktestService` interface. Swapping
`mockAdapter` for `httpAdapter` (or any future adapter) requires no UI change —
only the export in `services/index.ts` (or a top-bar toggle).

### Data contract (`types.ts`)

Mirrors the Python record so a real backend maps 1:1.

```ts
type StrategyId = 'endline' | 'reverse';

interface BacktestConfig {
  slug: string;            // e.g. "btc-updown-15m-1778263200"
  strategy: StrategyId;
  params: Record<string, number>; // strategy-specific, validated by registry schema
  bookSize: number;        // e.g. 100
  resample: string;        // e.g. "1s" | "10s"
}

interface SeriesPoint {
  timestamp: number;       // epoch ms
  price: number;
  position: number;
  equityWoFee: number;     // equity_wo_fee
  fee: number;
  equity: number;          // equity_wo_fee - fee (precomputed for the UI)
}

interface Trade {
  timestamp: number;
  side: 'buy' | 'sell';
  price: number;
  qty: number;
}

interface MetricSet {       // names align with hftbacktest.stats.metrics
  earn: number;
  sr: number;               // Sharpe
  sortino: number;
  ret: number;              // Ret
  maxDrawdown: number;      // MaxDrawdown
  dailyNumberOfTrades: number;
  returnOverMdd: number;    // ReturnOverMDD
  maxPositionValue: number; // MaxPositionValue
}

interface BacktestResult {
  id: string;
  config: BacktestConfig;
  createdAt: number;
  series: SeriesPoint[];
  trades: Trade[];
  metrics: MetricSet;
}
```

### Strategy registry (`registry.ts`)

Drives the dynamic param form and client-side validation. Defaults and clamps
mirror `endline_trading` in the README example.

```ts
interface ParamSpec {
  key: string; label: string;
  default: number; min: number; max: number; step: number;
}
interface StrategyDef {
  id: StrategyId; label: string; description: string; params: ParamSpec[];
}
```

- `endline` — params (from `endline_trading` in README): `up_trigger` (0.84,
  0.01–0.99), `stop_long` (0.40, 0.01–0.99), `order_qty` (5, ≥0).
- `reverse` — params (from `reverse_trading` in `example/reverse.ipynb`):
  `entry_price` (0.07, 0.01–0.99), `stop_earn` (0.9, 0.01–0.99),
  `cancel_after_s` (270, ≥0, integer), `order_qty` (5, ≥0).

### Mock adapter behaviour

- **Deterministic**: seed a PRNG from `(slug + strategy + params + resample)` so
  identical config → identical result, and changing a param visibly changes the
  equity curve, trades, and metrics.
- Generates a settlement-style Polymarket price path (drifts toward 0 or 1),
  applies a simple position/fill model from the params, and produces `series`,
  `trades`, and a computed `MetricSet` (including `earn` =
  `equity_woFee - fee` at the last point, matching `Stats.earn`).
- Simulated latency (~300–600ms) so the "running" state is visible.

### Http adapter behaviour

- `POST /api/backtest` with `BacktestConfig` as JSON body; expects
  `BacktestResult` JSON back. On non-2xx or network error, throws a typed error
  surfaced by the UI. Field names match `types.ts` so a FastAPI wrapper over the
  library maps directly.

## 5. Page Layout & UX

Single page, desktop-first, light warm "quant workbench" aesthetic.

```
+-----------------------------------------------------------------------+
| pm-hftbacktest · Polymarket Backtester              [adapter: Mock ▾]  |
+----------+------------------------------------------------------------+
| HISTORY  |  CONFIG                    |  RESULTS                       |
| ───────  |  Market slug [_________]   |  [earn][SR][Sortino][MaxDD]…   |
| ▸ run #3 |  Strategy  [endline ▾]     |   metric cards row             |
| ▸ run #2 |  ── params (dynamic) ──    |                                |
| ▸ run #1 |  up_trigger [0.84]         |  Equity chart                  |
|  ☐ compare  stop_long  [0.40]         |   (equity / w/o fee / price)   |
| [Compare]|  order_qty  [5]            |                                |
|          |  book_size  [100]          |  Position chart                |
|          |  resample   [1s ▾]         |                                |
|          |  [ ▶ Run backtest ]        |  [ Charts | Trades ] tabs      |
+----------+------------------------------------------------------------+
```

- **TopBar**: title + adapter indicator/toggle (Mock / Http).
- **HistorySidebar**: each Run appended to `localStorage`; click to re-view;
  checkboxes select exactly two runs to enable **Compare**.
- **ConfigPanel**: slug input, strategy dropdown, dynamic params (from
  registry), `bookSize`, `resample`, Run button. Inline range validation.
- **ResultsPanel**: metric cards row + tabs `Charts` (equity + position) and
  `Trades` (table: time / side / price / qty).
- **CompareView**: replaces the results main area when two runs are selected;
  overlays equity curves and shows a side-by-side metric table. Closing returns
  to the single-run view.

### States
- Empty (no run yet) → friendly prompt in results area.
- Running → button spinner + skeleton in results.
- Error → error card in results area with message; config preserved.
- Success → metrics + charts + trades.

## 6. Visual Design — Light Warm Palette

CSS variables in `theme.css`:

| Token | Value (approx) | Use |
|-------|----------------|-----|
| `--bg` | `#FAF6EF` (warm cream) | page background |
| `--surface` | `#FFFDF8` | cards / panels |
| `--surface-2` | `#F3EBDD` | sidebar / subtle fills |
| `--border` | `#E8DCC8` | hairline borders, grid |
| `--text` | `#2B2520` (warm near-black) | primary text |
| `--text-muted` | `#7A6E5F` | secondary text/labels |
| `--accent` | `#C2580E` (burnt amber/terracotta) | primary actions, focus |
| `--accent-soft` | `#F6E4D2` | accent backgrounds/hover |
| `--pos` | `#2F7A4F` (warm green) | profit/up |
| `--neg` | `#C0432F` (warm red) | loss/down |

- Numerics in a monospace face (e.g. IBM Plex Mono / JetBrains Mono); labels in
  a clean sans (e.g. Inter).
- Subtle warm hairline grid on charts; single accent for the primary equity
  line; muted gray for the price reference line.
- Restrained, precise, generous spacing — bright and warm, not the generic
  AI gradient look.

## 7. Testing

- **Unit**: mock adapter determinism (same config → identical result; param
  change → different metrics); `MetricSet`/`earn` computation; registry param
  validation/clamping; `httpAdapter` request/response mapping + error path
  (mocked `fetch`).
- **Component**: ConfigPanel renders params per strategy and validates ranges;
  ResultsPanel renders metric cards from a fixture; LineChart renders expected
  paths for a fixture series.
- Tooling: Vitest + React Testing Library.

## 8. Out of Scope (explicit)

- Real strategy execution / Python backend implementation.
- Auth, multi-user, server-side persistence.
- Live trading, websocket streaming.
- More than two-run comparison.
