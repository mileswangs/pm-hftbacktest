# Polymarket Backtester Frontend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a standalone React frontend for the `pm-hftbacktest` library that lets a user configure and run Polymarket backtests and inspect metrics, equity/position charts, trades, history, and a two-run comparison — fully decoupled from any backend via a swappable `BacktestService` adapter.

**Architecture:** A Vite + React + TypeScript single-page app. All UI depends only on the `BacktestService` interface. A built-in `mockAdapter` (deterministic, offline) makes the app work with zero backend; an `httpAdapter` (`POST /api/backtest`, fields 1:1 with the Python record) can be swapped in with no UI change. Pure logic (PRNG, metrics, registry, adapters, hook) is TDD-tested with Vitest; visual components are built with the frontend-design skill against fixed prop contracts and render tests.

**Tech Stack:** React 18, Vite, TypeScript, Vitest + @testing-library/react + jsdom, plain CSS variables. Custom SVG charts (no chart library).

**Reference spec:** `docs/superpowers/specs/2026-06-15-polymarket-backtest-frontend-design.md`

**Design tokens (light warm palette) — use everywhere:**
`--bg #FAF6EF`, `--surface #FFFDF8`, `--surface-2 #F3EBDD`, `--border #E8DCC8`, `--text #2B2520`, `--text-muted #7A6E5F`, `--accent #C2580E`, `--accent-soft #F6E4D2`, `--pos #2F7A4F`, `--neg #C0432F`. Numerics in a monospace font; labels in Inter.

**Conventions:** All paths are relative to `frontend/` unless noted. Commit after every task with the shown message. Run `npm test` from `frontend/`.

---

## Task 0: Scaffold the frontend project

**Files:**
- Create: `frontend/` (Vite React-TS scaffold)
- Create: `frontend/vitest.config.ts`, `frontend/src/test/setup.ts`
- Modify: `frontend/package.json`

- [ ] **Step 1: Scaffold Vite app**

From repo root:
```bash
npm create vite@latest frontend -- --template react-ts
cd frontend
npm install
npm install -D vitest @testing-library/react @testing-library/jest-dom @testing-library/user-event jsdom
```

- [ ] **Step 2: Add test config**

Create `frontend/vitest.config.ts`:
```ts
import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
  },
});
```

Create `frontend/src/test/setup.ts`:
```ts
import '@testing-library/jest-dom';
```

- [ ] **Step 3: Add test script**

In `frontend/package.json` `"scripts"`, add:
```json
"test": "vitest run",
"test:watch": "vitest"
```

- [ ] **Step 4: Add a smoke test and run it**

Create `frontend/src/test/smoke.test.ts`:
```ts
import { describe, it, expect } from 'vitest';
describe('smoke', () => {
  it('runs', () => { expect(1 + 1).toBe(2); });
});
```
Run: `npm test`
Expected: PASS (1 test).

- [ ] **Step 5: Remove default boilerplate**

Delete `frontend/src/App.css` contents and the demo markup in `frontend/src/App.tsx` (leave `export default function App() { return null; }` for now). Delete `frontend/src/assets/react.svg` usage. Delete `frontend/public/vite.svg` reference in `index.html` title — set `<title>pm-hftbacktest · Polymarket Backtester</title>`.

- [ ] **Step 6: Commit**

```bash
git add frontend
git commit -m "chore(frontend): scaffold vite react-ts app with vitest"
```

---

## Task 1: Data contract types

**Files:**
- Create: `src/services/types.ts`

- [ ] **Step 1: Write the types**

Create `src/services/types.ts`:
```ts
export type StrategyId = 'endline' | 'reverse';
export type AdapterKind = 'mock' | 'http';

export interface BacktestConfig {
  slug: string;
  strategy: StrategyId;
  params: Record<string, number>;
  bookSize: number;
  resample: string;
}

export interface SeriesPoint {
  timestamp: number; // epoch ms
  price: number;
  position: number;
  equityWoFee: number;
  fee: number;
  equity: number; // equityWoFee - fee
}

export interface Trade {
  timestamp: number;
  side: 'buy' | 'sell';
  price: number;
  qty: number;
}

export interface MetricSet {
  earn: number;
  sr: number;
  sortino: number;
  ret: number; // fraction of bookSize
  maxDrawdown: number; // fraction of bookSize, positive number
  dailyNumberOfTrades: number;
  returnOverMdd: number;
  maxPositionValue: number;
}

export interface BacktestResult {
  id: string;
  config: BacktestConfig;
  createdAt: number;
  series: SeriesPoint[];
  trades: Trade[];
  metrics: MetricSet;
}
```

- [ ] **Step 2: Typecheck**

Run: `npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add src/services/types.ts
git commit -m "feat(frontend): add backtest data contract types"
```

---

## Task 2: Deterministic PRNG utility

**Files:**
- Create: `src/services/prng.ts`
- Test: `src/services/prng.test.ts`

- [ ] **Step 1: Write the failing test**

Create `src/services/prng.test.ts`:
```ts
import { describe, it, expect } from 'vitest';
import { hashString, mulberry32 } from './prng';

describe('prng', () => {
  it('hashString is deterministic and order-sensitive', () => {
    expect(hashString('abc')).toBe(hashString('abc'));
    expect(hashString('abc')).not.toBe(hashString('acb'));
  });

  it('mulberry32 yields deterministic sequence in [0,1)', () => {
    const a = mulberry32(123);
    const b = mulberry32(123);
    const seqA = [a(), a(), a()];
    const seqB = [b(), b(), b()];
    expect(seqA).toEqual(seqB);
    for (const v of seqA) { expect(v).toBeGreaterThanOrEqual(0); expect(v).toBeLessThan(1); }
  });

  it('different seeds differ', () => {
    expect(mulberry32(1)()).not.toBe(mulberry32(2)());
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test -- prng`
Expected: FAIL (module not found).

- [ ] **Step 3: Implement**

Create `src/services/prng.ts`:
```ts
export function hashString(s: string): number {
  let h = 2166136261 >>> 0;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

export function mulberry32(seed: number): () => number {
  let a = seed >>> 0;
  return function () {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm test -- prng`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/services/prng.ts src/services/prng.test.ts
git commit -m "feat(frontend): add deterministic prng utility"
```

---

## Task 3: Metric computation

**Files:**
- Create: `src/services/metrics.ts`
- Test: `src/services/metrics.test.ts`

- [ ] **Step 1: Write the failing test**

Create `src/services/metrics.test.ts`:
```ts
import { describe, it, expect } from 'vitest';
import { computeMetrics } from './metrics';
import type { SeriesPoint, Trade } from './types';

function pt(timestamp: number, price: number, position: number, equityWoFee: number, fee: number): SeriesPoint {
  return { timestamp, price, position, equityWoFee, fee, equity: equityWoFee - fee };
}

describe('computeMetrics', () => {
  const series: SeriesPoint[] = [
    pt(0, 0.5, 0, 0, 0),
    pt(1000, 0.6, 5, 10, 1),
    pt(2000, 0.4, 5, 4, 1),     // drawdown here
    pt(3000, 1.0, 0, 20, 2),
  ];
  const trades: Trade[] = [
    { timestamp: 1000, side: 'buy', price: 0.6, qty: 5 },
    { timestamp: 3000, side: 'sell', price: 1.0, qty: 5 },
  ];

  it('earn equals last equity', () => {
    const m = computeMetrics(series, trades, 100);
    expect(m.earn).toBeCloseTo(18, 6); // 20 - 2
  });

  it('ret is earn over bookSize', () => {
    const m = computeMetrics(series, trades, 100);
    expect(m.ret).toBeCloseTo(0.18, 6);
  });

  it('maxDrawdown is positive peak-to-trough fraction of bookSize', () => {
    const m = computeMetrics(series, trades, 100);
    // equity peaks at 9 (t=1000), troughs at 3 (t=2000) -> dd 6 -> 0.06
    expect(m.maxDrawdown).toBeCloseTo(0.06, 6);
  });

  it('returnOverMdd = ret / maxDrawdown', () => {
    const m = computeMetrics(series, trades, 100);
    expect(m.returnOverMdd).toBeCloseTo(0.18 / 0.06, 4);
  });

  it('maxPositionValue is max |position| * price', () => {
    const m = computeMetrics(series, trades, 100);
    expect(m.maxPositionValue).toBeCloseTo(5 * 0.6, 6); // 3.0
  });

  it('handles empty series without throwing', () => {
    const m = computeMetrics([], [], 100);
    expect(m.earn).toBe(0);
    expect(m.maxDrawdown).toBe(0);
    expect(Number.isFinite(m.sr)).toBe(true);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test -- metrics`
Expected: FAIL (module not found).

- [ ] **Step 3: Implement**

Create `src/services/metrics.ts`:
```ts
import type { MetricSet, SeriesPoint, Trade } from './types';

const SECONDS_PER_DAY = 86400;

export function computeMetrics(series: SeriesPoint[], trades: Trade[], bookSize: number): MetricSet {
  if (series.length === 0) {
    return {
      earn: 0, sr: 0, sortino: 0, ret: 0, maxDrawdown: 0,
      dailyNumberOfTrades: 0, returnOverMdd: 0, maxPositionValue: 0,
    };
  }

  const equity = series.map((p) => p.equity);
  const earn = equity[equity.length - 1];
  const ret = bookSize > 0 ? earn / bookSize : 0;

  // Max drawdown (absolute equity terms), reported as fraction of bookSize.
  let peak = equity[0];
  let maxDd = 0;
  for (const e of equity) {
    if (e > peak) peak = e;
    const dd = peak - e;
    if (dd > maxDd) maxDd = dd;
  }
  const maxDrawdown = bookSize > 0 ? maxDd / bookSize : 0;

  // Per-step equity changes for SR / Sortino.
  const diffs: number[] = [];
  for (let i = 1; i < equity.length; i++) diffs.push(equity[i] - equity[i - 1]);
  const mean = diffs.length ? diffs.reduce((a, b) => a + b, 0) / diffs.length : 0;
  const variance = diffs.length ? diffs.reduce((a, b) => a + (b - mean) ** 2, 0) / diffs.length : 0;
  const std = Math.sqrt(variance);
  const downside = diffs.filter((d) => d < 0);
  const downsideStd = downside.length
    ? Math.sqrt(downside.reduce((a, b) => a + b * b, 0) / downside.length)
    : 0;

  // Annualization factor from sampling interval.
  const spanSec = (series[series.length - 1].timestamp - series[0].timestamp) / 1000;
  const stepSec = diffs.length && spanSec > 0 ? spanSec / diffs.length : 1;
  const periodsPerYear = stepSec > 0 ? (SECONDS_PER_DAY * 365) / stepSec : 0;
  const ann = Math.sqrt(periodsPerYear);

  const sr = std > 0 ? (mean / std) * ann : 0;
  const sortino = downsideStd > 0 ? (mean / downsideStd) * ann : 0;

  const days = spanSec > 0 ? spanSec / SECONDS_PER_DAY : 1;
  const dailyNumberOfTrades = days > 0 ? trades.length / days : trades.length;

  const returnOverMdd = maxDrawdown > 0 ? ret / maxDrawdown : 0;

  let maxPositionValue = 0;
  for (const p of series) {
    const v = Math.abs(p.position) * p.price;
    if (v > maxPositionValue) maxPositionValue = v;
  }

  return { earn, sr, sortino, ret, maxDrawdown, dailyNumberOfTrades, returnOverMdd, maxPositionValue };
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm test -- metrics`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add src/services/metrics.ts src/services/metrics.test.ts
git commit -m "feat(frontend): add metric computation"
```

---

## Task 4: Strategy registry

**Files:**
- Create: `src/strategies/registry.ts`
- Test: `src/strategies/registry.test.ts`

- [ ] **Step 1: Write the failing test**

Create `src/strategies/registry.test.ts`:
```ts
import { describe, it, expect } from 'vitest';
import { STRATEGIES, defaultParams, clampParams, validateParams } from './registry';

describe('registry', () => {
  it('exposes endline and reverse with params', () => {
    expect(STRATEGIES.endline.params.map((p) => p.key)).toEqual(['up_trigger', 'stop_long', 'order_qty']);
    expect(STRATEGIES.reverse.params.map((p) => p.key)).toEqual(['entry_price', 'stop_earn', 'cancel_after_s', 'order_qty']);
  });

  it('defaultParams returns spec defaults', () => {
    expect(defaultParams('endline')).toEqual({ up_trigger: 0.84, stop_long: 0.4, order_qty: 5 });
  });

  it('clampParams clamps out-of-range and rounds integer params', () => {
    const c = clampParams('reverse', { entry_price: 2, stop_earn: -1, cancel_after_s: 12.7, order_qty: -3 });
    expect(c.entry_price).toBe(0.99);
    expect(c.stop_earn).toBe(0.01);
    expect(c.cancel_after_s).toBe(13);
    expect(c.order_qty).toBe(0);
  });

  it('validateParams reports out-of-range keys', () => {
    expect(validateParams('endline', { up_trigger: 0.84, stop_long: 0.4, order_qty: 5 })).toEqual([]);
    const errs = validateParams('endline', { up_trigger: 5, stop_long: 0.4, order_qty: 5 });
    expect(errs.length).toBe(1);
    expect(errs[0]).toContain('up_trigger');
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test -- registry`
Expected: FAIL (module not found).

- [ ] **Step 3: Implement**

Create `src/strategies/registry.ts`:
```ts
import type { StrategyId } from '../services/types';

export interface ParamSpec {
  key: string;
  label: string;
  default: number;
  min: number;
  max: number;
  step: number;
  integer?: boolean;
}

export interface StrategyDef {
  id: StrategyId;
  label: string;
  description: string;
  params: ParamSpec[];
}

export const STRATEGIES: Record<StrategyId, StrategyDef> = {
  endline: {
    id: 'endline',
    label: 'Endline (扫尾盘)',
    description: '尾盘确定性突破：向上突破买 UP，向下突破买 DOWN，触达止损线平仓。',
    params: [
      { key: 'up_trigger', label: 'Up trigger', default: 0.84, min: 0.01, max: 0.99, step: 0.01 },
      { key: 'stop_long', label: 'Stop long', default: 0.4, min: 0.01, max: 0.99, step: 0.01 },
      { key: 'order_qty', label: 'Order qty', default: 5, min: 0, max: 1000, step: 1 },
    ],
  },
  reverse: {
    id: 'reverse',
    label: 'Reverse (反转)',
    description: '低价挂单博弈反转，到达止盈价或超时撤单。',
    params: [
      { key: 'entry_price', label: 'Entry price', default: 0.07, min: 0.01, max: 0.99, step: 0.01 },
      { key: 'stop_earn', label: 'Stop earn', default: 0.9, min: 0.01, max: 0.99, step: 0.01 },
      { key: 'cancel_after_s', label: 'Cancel after (s)', default: 270, min: 0, max: 3600, step: 1, integer: true },
      { key: 'order_qty', label: 'Order qty', default: 5, min: 0, max: 1000, step: 1 },
    ],
  },
};

export function defaultParams(id: StrategyId): Record<string, number> {
  const out: Record<string, number> = {};
  for (const p of STRATEGIES[id].params) out[p.key] = p.default;
  return out;
}

export function clampParams(id: StrategyId, params: Record<string, number>): Record<string, number> {
  const out: Record<string, number> = {};
  for (const p of STRATEGIES[id].params) {
    let v = params[p.key];
    if (v == null || Number.isNaN(v)) v = p.default;
    v = Math.min(p.max, Math.max(p.min, v));
    if (p.integer) v = Math.round(v);
    out[p.key] = v;
  }
  return out;
}

export function validateParams(id: StrategyId, params: Record<string, number>): string[] {
  const errs: string[] = [];
  for (const p of STRATEGIES[id].params) {
    const v = params[p.key];
    if (v == null || Number.isNaN(v)) {
      errs.push(`${p.label} (${p.key}) is required`);
    } else if (v < p.min || v > p.max) {
      errs.push(`${p.label} (${p.key}) must be between ${p.min} and ${p.max}`);
    }
  }
  return errs;
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm test -- registry`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add src/strategies/registry.ts src/strategies/registry.test.ts
git commit -m "feat(frontend): add strategy registry with param specs"
```

---

## Task 5: BacktestService interface + mock adapter

**Files:**
- Create: `src/services/BacktestService.ts`
- Create: `src/services/mockAdapter.ts`
- Test: `src/services/mockAdapter.test.ts`

- [ ] **Step 1: Write the interface**

Create `src/services/BacktestService.ts`:
```ts
import type { BacktestConfig, BacktestResult } from './types';

export interface BacktestService {
  run(config: BacktestConfig): Promise<BacktestResult>;
}
```

- [ ] **Step 2: Write the failing test**

Create `src/services/mockAdapter.test.ts`:
```ts
import { describe, it, expect } from 'vitest';
import { mockAdapter } from './mockAdapter';
import type { BacktestConfig } from './types';

const cfg: BacktestConfig = {
  slug: 'btc-updown-15m-1778263200',
  strategy: 'endline',
  params: { up_trigger: 0.84, stop_long: 0.4, order_qty: 5 },
  bookSize: 100,
  resample: '1s',
};

describe('mockAdapter', () => {
  it('returns a result with series, trades, metrics', async () => {
    const r = await mockAdapter.run(cfg);
    expect(r.series.length).toBeGreaterThan(10);
    expect(r.config).toEqual(cfg);
    expect(Number.isFinite(r.metrics.earn)).toBe(true);
    // equity column is equityWoFee - fee
    const p = r.series[r.series.length - 1];
    expect(p.equity).toBeCloseTo(p.equityWoFee - p.fee, 6);
  });

  it('is deterministic for identical config', async () => {
    const a = await mockAdapter.run(cfg);
    const b = await mockAdapter.run(cfg);
    expect(a.metrics).toEqual(b.metrics);
    expect(a.series.map((s) => s.price)).toEqual(b.series.map((s) => s.price));
  });

  it('changes when a param changes', async () => {
    const a = await mockAdapter.run(cfg);
    const b = await mockAdapter.run({ ...cfg, params: { ...cfg.params, up_trigger: 0.6 } });
    expect(a.metrics.earn).not.toBe(b.metrics.earn);
  });

  it('produces a settlement price near 0 or 1 at the end', async () => {
    const r = await mockAdapter.run(cfg);
    const last = r.series[r.series.length - 1].price;
    expect(last === 0 || last === 1).toBe(true);
  });
});
```

- [ ] **Step 3: Run test to verify it fails**

Run: `npm test -- mockAdapter`
Expected: FAIL (module not found).

- [ ] **Step 4: Implement**

Create `src/services/mockAdapter.ts`:
```ts
import type { BacktestConfig, BacktestResult, SeriesPoint, Trade } from './types';
import type { BacktestService } from './BacktestService';
import { hashString, mulberry32 } from './prng';
import { computeMetrics } from './metrics';

const N_POINTS = 180; // resampled points
const STEP_MS = 1000;

function seedFor(config: BacktestConfig): number {
  const paramStr = Object.keys(config.params).sort().map((k) => `${k}=${config.params[k]}`).join(',');
  return hashString(`${config.slug}|${config.strategy}|${paramStr}|${config.resample}|${config.bookSize}`);
}

export const mockAdapter: BacktestService = {
  async run(config: BacktestConfig): Promise<BacktestResult> {
    const rng = mulberry32(seedFor(config));
    const start = Date.UTC(2026, 0, 1, 0, 0, 0);

    // Settlement outcome: bias by a price-ish param when present.
    const bias = config.params.up_trigger ?? config.params.entry_price ?? 0.5;
    const settleUp = rng() < bias;

    const qty = config.params.order_qty ?? 5;

    let price = 0.5;
    let position = 0;
    let balance = 0; // cash flow from fills
    let fee = 0;
    const series: SeriesPoint[] = [];
    const trades: Trade[] = [];

    for (let i = 0; i < N_POINTS; i++) {
      const t = start + i * STEP_MS;
      const progress = i / (N_POINTS - 1);
      // Random walk drifting toward the settlement outcome as time passes.
      const target = settleUp ? 1 : 0;
      const drift = (target - price) * 0.02 * progress;
      const noise = (rng() - 0.5) * 0.03;
      price = Math.min(0.99, Math.max(0.01, price + drift + noise));

      // Simple entry/exit model: enter once price crosses a param threshold,
      // exit near the end. Generates position changes -> trades.
      const enterLevel = config.strategy === 'endline'
        ? (config.params.up_trigger ?? 0.84)
        : (config.params.entry_price ?? 0.07);
      if (position === 0 && i > 5 && price >= enterLevel && i < N_POINTS - 20) {
        position = qty;
        balance -= price * qty;
        fee += price * qty * 0.001;
        trades.push({ timestamp: t, side: 'buy', price, qty });
      } else if (position !== 0 && i >= N_POINTS - 10) {
        balance += price * position;
        fee += price * Math.abs(position) * 0.001;
        trades.push({ timestamp: t, side: 'sell', price, qty: position });
        position = 0;
      }

      const equityWoFee = balance + position * price;
      series.push({ timestamp: t, price, position, equityWoFee, fee, equity: equityWoFee - fee });
    }

    // Settlement: force last price to 0/1 and mark equity to settlement.
    const settlePrice = settleUp ? 1 : 0;
    const lastIdx = series.length - 1;
    if (position !== 0) {
      balance += settlePrice * position;
      fee += Math.abs(position) * settlePrice * 0.001;
      trades.push({ timestamp: series[lastIdx].timestamp, side: position > 0 ? 'sell' : 'buy', price: settlePrice, qty: Math.abs(position) });
      position = 0;
    }
    series[lastIdx] = {
      ...series[lastIdx],
      price: settlePrice,
      position: 0,
      equityWoFee: balance,
      fee,
      equity: balance - fee,
    };

    // Scale equity into bookSize terms so charts/metrics are meaningful.
    const metrics = computeMetrics(series, trades, config.bookSize);

    // Simulate latency so the "running" state is visible.
    await new Promise((res) => setTimeout(res, 350 + Math.floor(rng() * 250)));

    return {
      id: `${Date.now()}-${Math.floor(rng() * 1e6)}`,
      config,
      createdAt: Date.now(),
      series,
      trades,
      metrics,
    };
  },
};
```

- [ ] **Step 5: Run test to verify it passes**

Run: `npm test -- mockAdapter`
Expected: PASS (4 tests).

- [ ] **Step 6: Commit**

```bash
git add src/services/BacktestService.ts src/services/mockAdapter.ts src/services/mockAdapter.test.ts
git commit -m "feat(frontend): add BacktestService interface and deterministic mock adapter"
```

---

## Task 6: HTTP adapter

**Files:**
- Create: `src/services/httpAdapter.ts`
- Test: `src/services/httpAdapter.test.ts`

- [ ] **Step 1: Write the failing test**

Create `src/services/httpAdapter.test.ts`:
```ts
import { describe, it, expect, vi, afterEach } from 'vitest';
import { createHttpAdapter } from './httpAdapter';
import type { BacktestConfig, BacktestResult } from './types';

const cfg: BacktestConfig = {
  slug: 's', strategy: 'endline', params: { up_trigger: 0.84, stop_long: 0.4, order_qty: 5 },
  bookSize: 100, resample: '1s',
};
const result: BacktestResult = {
  id: 'r1', config: cfg, createdAt: 1, series: [], trades: [],
  metrics: { earn: 1, sr: 0, sortino: 0, ret: 0, maxDrawdown: 0, dailyNumberOfTrades: 0, returnOverMdd: 0, maxPositionValue: 0 },
};

afterEach(() => vi.restoreAllMocks());

describe('httpAdapter', () => {
  it('POSTs config to /api/backtest and returns parsed result', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => result });
    const adapter = createHttpAdapter('/api/backtest', fetchMock as unknown as typeof fetch);
    const r = await adapter.run(cfg);
    expect(r.id).toBe('r1');
    expect(fetchMock).toHaveBeenCalledWith('/api/backtest', expect.objectContaining({
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(cfg),
    }));
  });

  it('throws a descriptive error on non-ok response', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: false, status: 500, text: async () => 'boom' });
    const adapter = createHttpAdapter('/api/backtest', fetchMock as unknown as typeof fetch);
    await expect(adapter.run(cfg)).rejects.toThrow(/500/);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test -- httpAdapter`
Expected: FAIL (module not found).

- [ ] **Step 3: Implement**

Create `src/services/httpAdapter.ts`:
```ts
import type { BacktestConfig, BacktestResult } from './types';
import type { BacktestService } from './BacktestService';

export function createHttpAdapter(
  endpoint = '/api/backtest',
  fetchImpl: typeof fetch = fetch,
): BacktestService {
  return {
    async run(config: BacktestConfig): Promise<BacktestResult> {
      const res = await fetchImpl(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(config),
      });
      if (!res.ok) {
        const detail = await res.text().catch(() => '');
        throw new Error(`Backtest request failed (${res.status}): ${detail}`);
      }
      return (await res.json()) as BacktestResult;
    },
  };
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm test -- httpAdapter`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add src/services/httpAdapter.ts src/services/httpAdapter.test.ts
git commit -m "feat(frontend): add http adapter with error handling"
```

---

## Task 7: Adapter selection entrypoint

**Files:**
- Create: `src/services/index.ts`
- Test: `src/services/index.test.ts`

- [ ] **Step 1: Write the failing test**

Create `src/services/index.test.ts`:
```ts
import { describe, it, expect } from 'vitest';
import { getService } from './index';
import { mockAdapter } from './mockAdapter';

describe('getService', () => {
  it('defaults to mock adapter', () => {
    expect(getService()).toBe(mockAdapter);
    expect(getService('mock')).toBe(mockAdapter);
  });

  it('returns an object with run() for http', () => {
    const svc = getService('http');
    expect(typeof svc.run).toBe('function');
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test -- services/index`
Expected: FAIL (module not found).

- [ ] **Step 3: Implement**

Create `src/services/index.ts`:
```ts
import type { AdapterKind } from './types';
import type { BacktestService } from './BacktestService';
import { mockAdapter } from './mockAdapter';
import { createHttpAdapter } from './httpAdapter';

export function getService(kind: AdapterKind = 'mock'): BacktestService {
  return kind === 'http' ? createHttpAdapter() : mockAdapter;
}

export type { BacktestService } from './BacktestService';
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm test -- services/index`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add src/services/index.ts src/services/index.test.ts
git commit -m "feat(frontend): add adapter selection entrypoint"
```

---

## Task 8: useBacktestRuns hook (state, history, compare, persistence)

**Files:**
- Create: `src/hooks/useBacktestRuns.ts`
- Test: `src/hooks/useBacktestRuns.test.tsx`

- [ ] **Step 1: Write the failing test**

Create `src/hooks/useBacktestRuns.test.tsx`:
```tsx
import { describe, it, expect, beforeEach } from 'vitest';
import { renderHook, act, waitFor } from '@testing-library/react';
import { useBacktestRuns } from './useBacktestRuns';
import { mockAdapter } from '../services/mockAdapter';
import type { BacktestConfig } from '../services/types';

const cfg: BacktestConfig = {
  slug: 's', strategy: 'endline', params: { up_trigger: 0.84, stop_long: 0.4, order_qty: 5 },
  bookSize: 100, resample: '1s',
};

beforeEach(() => localStorage.clear());

describe('useBacktestRuns', () => {
  it('runs a backtest, stores it, sets it active', async () => {
    const { result } = renderHook(() => useBacktestRuns(mockAdapter));
    await act(async () => { await result.current.run(cfg); });
    expect(result.current.runs.length).toBe(1);
    expect(result.current.activeRun?.config.slug).toBe('s');
    expect(result.current.status).toBe('idle');
  });

  it('persists runs to localStorage', async () => {
    const { result } = renderHook(() => useBacktestRuns(mockAdapter));
    await act(async () => { await result.current.run(cfg); });
    expect(localStorage.getItem('pm-bt-runs')).toContain('"slug":"s"');
  });

  it('toggleCompare selects at most two runs', async () => {
    const { result } = renderHook(() => useBacktestRuns(mockAdapter));
    await act(async () => { await result.current.run(cfg); });
    await act(async () => { await result.current.run({ ...cfg, slug: 's2' }); });
    const [a, b] = result.current.runs.map((r) => r.id);
    act(() => { result.current.toggleCompare(a); });
    act(() => { result.current.toggleCompare(b); });
    expect(result.current.compareIds).toEqual([a, b]);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test -- useBacktestRuns`
Expected: FAIL (module not found).

- [ ] **Step 3: Implement**

Create `src/hooks/useBacktestRuns.ts`:
```ts
import { useCallback, useEffect, useMemo, useState } from 'react';
import type { BacktestConfig, BacktestResult } from '../services/types';
import type { BacktestService } from '../services/BacktestService';

const STORAGE_KEY = 'pm-bt-runs';
const MAX_RUNS = 20;

type Status = 'idle' | 'running' | 'error';

function loadRuns(): BacktestResult[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? (JSON.parse(raw) as BacktestResult[]) : [];
  } catch {
    return [];
  }
}

export function useBacktestRuns(service: BacktestService) {
  const [runs, setRuns] = useState<BacktestResult[]>(() => loadRuns());
  const [activeId, setActiveId] = useState<string | null>(() => loadRuns()[0]?.id ?? null);
  const [compareIds, setCompareIds] = useState<string[]>([]);
  const [status, setStatus] = useState<Status>('idle');
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(runs));
    } catch {
      /* ignore quota errors */
    }
  }, [runs]);

  const run = useCallback(async (config: BacktestConfig) => {
    setStatus('running');
    setError(null);
    try {
      const result = await service.run(config);
      setRuns((prev) => [result, ...prev].slice(0, MAX_RUNS));
      setActiveId(result.id);
      setStatus('idle');
      return result;
    } catch (e) {
      setStatus('error');
      setError(e instanceof Error ? e.message : String(e));
      throw e;
    }
  }, [service]);

  const selectRun = useCallback((id: string) => setActiveId(id), []);

  const toggleCompare = useCallback((id: string) => {
    setCompareIds((prev) => {
      if (prev.includes(id)) return prev.filter((x) => x !== id);
      if (prev.length >= 2) return [prev[1], id];
      return [...prev, id];
    });
  }, []);

  const clearCompare = useCallback(() => setCompareIds([]), []);

  const activeRun = useMemo(() => runs.find((r) => r.id === activeId) ?? null, [runs, activeId]);
  const compareRuns = useMemo(
    () => compareIds.map((id) => runs.find((r) => r.id === id)).filter(Boolean) as BacktestResult[],
    [compareIds, runs],
  );

  return {
    runs, activeRun, activeId, status, error,
    compareIds, compareRuns,
    run, selectRun, toggleCompare, clearCompare,
  };
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm test -- useBacktestRuns`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add src/hooks/useBacktestRuns.ts src/hooks/useBacktestRuns.test.tsx
git commit -m "feat(frontend): add useBacktestRuns hook with persistence and compare"
```

---

## Task 9: Formatting helpers

**Files:**
- Create: `src/lib/format.ts`
- Test: `src/lib/format.test.ts`

- [ ] **Step 1: Write the failing test**

Create `src/lib/format.test.ts`:
```ts
import { describe, it, expect } from 'vitest';
import { fmtMoney, fmtPct, fmtNum, fmtTime } from './format';

describe('format', () => {
  it('fmtMoney', () => { expect(fmtMoney(1234.5)).toBe('$1,234.50'); });
  it('fmtPct', () => { expect(fmtPct(0.1234)).toBe('12.34%'); });
  it('fmtNum', () => { expect(fmtNum(3.14159, 2)).toBe('3.14'); });
  it('fmtTime returns HH:MM:SS', () => { expect(fmtTime(Date.UTC(2026, 0, 1, 1, 2, 3))).toMatch(/01:02:03/); });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test -- format`
Expected: FAIL (module not found).

- [ ] **Step 3: Implement**

Create `src/lib/format.ts`:
```ts
export function fmtMoney(v: number): string {
  return v.toLocaleString('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: 2, maximumFractionDigits: 2 });
}
export function fmtPct(v: number, digits = 2): string {
  return `${(v * 100).toFixed(digits)}%`;
}
export function fmtNum(v: number, digits = 2): string {
  return v.toFixed(digits);
}
export function fmtTime(ms: number): string {
  return new Date(ms).toISOString().slice(11, 19);
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm test -- format`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add src/lib/format.ts src/lib/format.test.ts
git commit -m "feat(frontend): add formatting helpers"
```

---

## Task 10: Theme + global styles

**Files:**
- Create: `src/theme.css`
- Modify: `src/main.tsx` (import theme.css)

> **Use the frontend-design skill for this and all following UI tasks.** Realize a precise, bright, warm "quant workbench" aesthetic — not the generic AI gradient look.

- [ ] **Step 1: Create theme.css**

Create `src/theme.css` defining the palette as CSS variables on `:root` (exact tokens from the plan header), a CSS reset, base typography (Inter for text via system fallback stack `Inter, ui-sans-serif, system-ui`; monospace numerics via a `.mono` utility class using `ui-monospace, "JetBrains Mono", monospace`), `body { background: var(--bg); color: var(--text); }`, and utility classes `.card` (surface bg, 1px var(--border), radius 10px, subtle warm shadow), `.muted` (var(--text-muted)), `.pos`/`.neg` colors.

- [ ] **Step 2: Import it**

In `src/main.tsx`, add `import './theme.css';` (keep or replace `index.css`).

- [ ] **Step 3: Verify build**

Run: `npx tsc --noEmit && npm run build`
Expected: build succeeds.

- [ ] **Step 4: Commit**

```bash
git add src/theme.css src/main.tsx
git commit -m "style(frontend): add light warm theme and base styles"
```

---

## Task 11: LineChart (reusable SVG component)

**Files:**
- Create: `src/charts/LineChart.tsx`
- Test: `src/charts/LineChart.test.tsx`

**Contract (do not change prop names — later tasks depend on them):**
```ts
export interface ChartSeries {
  label: string;
  color: string;
  axis?: 'left' | 'right';   // default 'left'
  dashed?: boolean;
  points: { x: number; y: number }[];
}
export interface LineChartProps {
  series: ChartSeries[];
  height?: number;           // default 280
  xFormat?: (x: number) => string;
  yFormat?: (y: number) => string;
  yRightFormat?: (y: number) => string;
}
```

- [ ] **Step 1: Write the failing test**

Create `src/charts/LineChart.test.tsx`:
```tsx
import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/react';
import { LineChart } from './LineChart';

describe('LineChart', () => {
  it('renders one path per non-empty series', () => {
    const { container } = render(
      <LineChart series={[
        { label: 'A', color: '#000', points: [{ x: 0, y: 0 }, { x: 1, y: 1 }] },
        { label: 'B', color: '#111', points: [{ x: 0, y: 1 }, { x: 1, y: 0 }] },
      ]} />,
    );
    expect(container.querySelectorAll('path.series-line').length).toBe(2);
  });

  it('renders nothing breaking for empty series', () => {
    const { container } = render(<LineChart series={[]} />);
    expect(container.querySelector('svg')).toBeTruthy();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test -- LineChart`
Expected: FAIL (module not found).

- [ ] **Step 3: Implement with frontend-design skill**

Create `src/charts/LineChart.tsx`. Requirements:
- Pure SVG, responsive width via a container ref or `viewBox` + `preserveAspectRatio`, fixed `height` prop.
- Compute left-axis min/max from all `axis !== 'right'` series; right-axis min/max from `axis === 'right'` series. Map points to SVG coords with ~36px padding for axes.
- Each series renders as `<path class="series-line" stroke={color} fill="none">`; honor `dashed` via `stroke-dasharray`.
- Warm hairline grid (`var(--border)`), axis tick labels using `xFormat`/`yFormat`/`yRightFormat`, a legend chip row above the chart.
- Crosshair + tooltip on `mousemove` (nearest x index) showing each series value; hide on mouse leave. Keep it dependency-free.
- The `series-line` class on each line path is required by the test.

- [ ] **Step 4: Run test to verify it passes**

Run: `npm test -- LineChart`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add src/charts/LineChart.tsx src/charts/LineChart.test.tsx
git commit -m "feat(frontend): add reusable SVG LineChart"
```

---

## Task 12: MetricCards

**Files:**
- Create: `src/components/MetricCards.tsx`
- Test: `src/components/MetricCards.test.tsx`

**Contract:** `export function MetricCards({ metrics }: { metrics: MetricSet }): JSX.Element`

- [ ] **Step 1: Write the failing test**

Create `src/components/MetricCards.test.tsx`:
```tsx
import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MetricCards } from './MetricCards';

const metrics = {
  earn: 18.5, sr: 1.2, sortino: 1.5, ret: 0.18, maxDrawdown: 0.06,
  dailyNumberOfTrades: 4, returnOverMdd: 3, maxPositionValue: 30,
};

describe('MetricCards', () => {
  it('renders earn and key metric labels', () => {
    render(<MetricCards metrics={metrics} />);
    expect(screen.getByText(/earn/i)).toBeTruthy();
    expect(screen.getByText(/Sharpe/i)).toBeTruthy();
    expect(screen.getByText(/Max Drawdown/i)).toBeTruthy();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test -- MetricCards`
Expected: FAIL (module not found).

- [ ] **Step 3: Implement with frontend-design skill**

Create `src/components/MetricCards.tsx`. A horizontal row of `.card` cells, each with a muted label and a large `.mono` value. Cards: Earn (`fmtMoney`), Sharpe (sr, `fmtNum`), Sortino (`fmtNum`), Return (`fmtPct(ret)`), Max Drawdown (`fmtPct(maxDrawdown)`), Daily Trades (`fmtNum(.,1)`), Return/MDD (`fmtNum`), Max Pos Value (`fmtMoney`). Color Earn and Return with `.pos`/`.neg` by sign. Labels must include the exact strings "Earn", "Sharpe", "Max Drawdown" (test depends on them).

- [ ] **Step 4: Run test to verify it passes**

Run: `npm test -- MetricCards`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/components/MetricCards.tsx src/components/MetricCards.test.tsx
git commit -m "feat(frontend): add metric cards"
```

---

## Task 13: EquityChart and PositionChart

**Files:**
- Create: `src/components/EquityChart.tsx`
- Create: `src/components/PositionChart.tsx`
- Test: `src/components/Charts.test.tsx`

**Contract:** each takes `{ result: BacktestResult }`.

- [ ] **Step 1: Write the failing test**

Create `src/components/Charts.test.tsx`:
```tsx
import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/react';
import { EquityChart } from './EquityChart';
import { PositionChart } from './PositionChart';
import type { BacktestResult } from '../services/types';

const result: BacktestResult = {
  id: 'r', createdAt: 0,
  config: { slug: 's', strategy: 'endline', params: {}, bookSize: 100, resample: '1s' },
  series: [
    { timestamp: 0, price: 0.5, position: 0, equityWoFee: 0, fee: 0, equity: 0 },
    { timestamp: 1000, price: 0.6, position: 5, equityWoFee: 10, fee: 1, equity: 9 },
  ],
  trades: [],
  metrics: { earn: 9, sr: 0, sortino: 0, ret: 0.09, maxDrawdown: 0, dailyNumberOfTrades: 0, returnOverMdd: 0, maxPositionValue: 3 },
};

describe('charts', () => {
  it('EquityChart renders an svg with series lines', () => {
    const { container } = render(<EquityChart result={result} />);
    expect(container.querySelectorAll('path.series-line').length).toBeGreaterThanOrEqual(2);
  });
  it('PositionChart renders an svg with series lines', () => {
    const { container } = render(<PositionChart result={result} />);
    expect(container.querySelectorAll('path.series-line').length).toBeGreaterThanOrEqual(1);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test -- Charts`
Expected: FAIL (module not found).

- [ ] **Step 3: Implement**

Create `src/components/EquityChart.tsx`: build `ChartSeries[]` from `result.series` — Equity (`equity / bookSize * 100`, color `var(--accent)`, left axis), Equity w/o fee (`equityWoFee / bookSize * 100`, muted color, left axis), Price (`price`, color muted/black at low alpha, right axis, dashed). Pass `xFormat={fmtTime}`, `yFormat={(v)=>v.toFixed(1)+'%'}`, `yRightFormat={(v)=>v.toFixed(2)}`. Wrap in a titled `.card`.

Create `src/components/PositionChart.tsx`: Position (`position`, left axis, accent) + Price (`price`, right axis, muted dashed). Same formatting pattern. Titled `.card`.

Read the values from CSS tokens via literal hex from the plan header (e.g. accent `#C2580E`) to keep charts pure.

- [ ] **Step 4: Run test to verify it passes**

Run: `npm test -- Charts`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add src/components/EquityChart.tsx src/components/PositionChart.tsx src/components/Charts.test.tsx
git commit -m "feat(frontend): add equity and position charts"
```

---

## Task 14: TradesTable

**Files:**
- Create: `src/components/TradesTable.tsx`
- Test: `src/components/TradesTable.test.tsx`

**Contract:** `export function TradesTable({ trades }: { trades: Trade[] }): JSX.Element`

- [ ] **Step 1: Write the failing test**

Create `src/components/TradesTable.test.tsx`:
```tsx
import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { TradesTable } from './TradesTable';

describe('TradesTable', () => {
  it('renders a row per trade', () => {
    render(<TradesTable trades={[
      { timestamp: 0, side: 'buy', price: 0.6, qty: 5 },
      { timestamp: 1000, side: 'sell', price: 1.0, qty: 5 },
    ]} />);
    expect(screen.getAllByRole('row').length).toBe(3); // header + 2
  });

  it('shows an empty state when no trades', () => {
    render(<TradesTable trades={[]} />);
    expect(screen.getByText(/no trades/i)).toBeTruthy();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test -- TradesTable`
Expected: FAIL (module not found).

- [ ] **Step 3: Implement with frontend-design skill**

Create `src/components/TradesTable.tsx`. A `<table>` with header row (Time / Side / Price / Qty) and one `<tr>` per trade; `buy` side colored `.pos`, `sell` colored `.neg`; numerics in `.mono`; `fmtTime`/`fmtNum` formatting. When `trades` is empty, render a muted "No trades" message (no `<tr>` body rows). Scrollable container with sticky header.

- [ ] **Step 4: Run test to verify it passes**

Run: `npm test -- TradesTable`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add src/components/TradesTable.tsx src/components/TradesTable.test.tsx
git commit -m "feat(frontend): add trades table"
```

---

## Task 15: ParamField and ConfigPanel

**Files:**
- Create: `src/components/ParamField.tsx`
- Create: `src/components/ConfigPanel.tsx`
- Test: `src/components/ConfigPanel.test.tsx`

**Contracts:**
```ts
// ParamField
export function ParamField(props: {
  spec: ParamSpec; value: number; onChange: (v: number) => void;
}): JSX.Element;

// ConfigPanel
export function ConfigPanel(props: {
  running: boolean;
  onRun: (config: BacktestConfig) => void;
}): JSX.Element;
```

- [ ] **Step 1: Write the failing test**

Create `src/components/ConfigPanel.test.tsx`:
```tsx
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { ConfigPanel } from './ConfigPanel';

describe('ConfigPanel', () => {
  it('renders endline params by default and runs with a config', () => {
    const onRun = vi.fn();
    render(<ConfigPanel running={false} onRun={onRun} />);
    // endline params present
    expect(screen.getByLabelText(/Up trigger/i)).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: /run backtest/i }));
    expect(onRun).toHaveBeenCalledTimes(1);
    const cfg = onRun.mock.calls[0][0];
    expect(cfg.strategy).toBe('endline');
    expect(cfg.params.up_trigger).toBe(0.84);
  });

  it('switching strategy swaps the param fields', () => {
    render(<ConfigPanel running={false} onRun={vi.fn()} />);
    fireEvent.change(screen.getByLabelText(/strategy/i), { target: { value: 'reverse' } });
    expect(screen.getByLabelText(/Entry price/i)).toBeTruthy();
  });

  it('disables run button while running', () => {
    render(<ConfigPanel running={true} onRun={vi.fn()} />);
    expect(screen.getByRole('button', { name: /running/i })).toBeDisabled();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test -- ConfigPanel`
Expected: FAIL (module not found).

- [ ] **Step 3: Implement with frontend-design skill**

Create `src/components/ParamField.tsx`: a labeled numeric `<input type="number">` bound to `spec.min/max/step`; the `<label>` text is `spec.label` and is associated via `htmlFor`/`id = spec.key` so `getByLabelText` works; calls `onChange(Number(e.target.value))`.

Create `src/components/ConfigPanel.tsx`:
- Local state: `slug` (default `btc-updown-15m-1778263200`), `strategy` (default `endline`), `params` (from `defaultParams(strategy)`), `bookSize` (100), `resample` (`1s`).
- A `<select>` labeled "Strategy" (id `strategy`) listing `Object.values(STRATEGIES)`. On change, reset `params` via `defaultParams(newId)`.
- Render a `ParamField` per `STRATEGIES[strategy].params`.
- Inputs for `slug` (text), `bookSize` (number), `resample` (`<select>`: 1s, 10s, 1m).
- Run button: when `running`, label "Running…" and `disabled`; else "Run backtest". On click, build `config`, `clampParams` the params, run `validateParams`; if errors, show them inline and do not call `onRun`; else call `onRun(config)`.
- Wrap in `.card` with a panel title.

- [ ] **Step 4: Run test to verify it passes**

Run: `npm test -- ConfigPanel`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add src/components/ParamField.tsx src/components/ConfigPanel.tsx src/components/ConfigPanel.test.tsx
git commit -m "feat(frontend): add config panel with dynamic strategy params"
```

---

## Task 16: HistorySidebar

**Files:**
- Create: `src/components/HistorySidebar.tsx`
- Test: `src/components/HistorySidebar.test.tsx`

**Contract:**
```ts
export function HistorySidebar(props: {
  runs: BacktestResult[];
  activeId: string | null;
  compareIds: string[];
  onSelect: (id: string) => void;
  onToggleCompare: (id: string) => void;
  onCompare: () => void;
}): JSX.Element;
```

- [ ] **Step 1: Write the failing test**

Create `src/components/HistorySidebar.test.tsx`:
```tsx
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { HistorySidebar } from './HistorySidebar';
import type { BacktestResult } from '../services/types';

const mk = (id: string, slug: string): BacktestResult => ({
  id, createdAt: 0, config: { slug, strategy: 'endline', params: {}, bookSize: 100, resample: '1s' },
  series: [], trades: [],
  metrics: { earn: 1, sr: 0, sortino: 0, ret: 0.01, maxDrawdown: 0, dailyNumberOfTrades: 0, returnOverMdd: 0, maxPositionValue: 0 },
});

describe('HistorySidebar', () => {
  it('lists runs and fires onSelect', () => {
    const onSelect = vi.fn();
    render(<HistorySidebar runs={[mk('a', 's1'), mk('b', 's2')]} activeId="a" compareIds={[]}
      onSelect={onSelect} onToggleCompare={vi.fn()} onCompare={vi.fn()} />);
    fireEvent.click(screen.getByText('s2'));
    expect(onSelect).toHaveBeenCalledWith('b');
  });

  it('enables Compare only when two are selected', () => {
    const onCompare = vi.fn();
    const { rerender } = render(<HistorySidebar runs={[mk('a', 's1'), mk('b', 's2')]} activeId="a" compareIds={['a']}
      onSelect={vi.fn()} onToggleCompare={vi.fn()} onCompare={onCompare} />);
    expect(screen.getByRole('button', { name: /compare/i })).toBeDisabled();
    rerender(<HistorySidebar runs={[mk('a', 's1'), mk('b', 's2')]} activeId="a" compareIds={['a', 'b']}
      onSelect={vi.fn()} onToggleCompare={vi.fn()} onCompare={onCompare} />);
    expect(screen.getByRole('button', { name: /compare/i })).not.toBeDisabled();
  });

  it('shows empty state with no runs', () => {
    render(<HistorySidebar runs={[]} activeId={null} compareIds={[]}
      onSelect={vi.fn()} onToggleCompare={vi.fn()} onCompare={vi.fn()} />);
    expect(screen.getByText(/no runs yet/i)).toBeTruthy();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test -- HistorySidebar`
Expected: FAIL (module not found).

- [ ] **Step 3: Implement with frontend-design skill**

Create `src/components/HistorySidebar.tsx`. A vertical list; each item is clickable (calls `onSelect(id)`), shows the slug, strategy, and `earn` (`.pos`/`.neg`), and is highlighted when `id === activeId`. Each item has a compare checkbox calling `onToggleCompare(id)` (checked when in `compareIds`). A "Compare" button at the bottom, `disabled` unless `compareIds.length === 2`, calling `onCompare`. When `runs` is empty, show a muted "No runs yet" message. Use exact strings "Compare" and "No runs yet".

- [ ] **Step 4: Run test to verify it passes**

Run: `npm test -- HistorySidebar`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add src/components/HistorySidebar.tsx src/components/HistorySidebar.test.tsx
git commit -m "feat(frontend): add history sidebar with compare selection"
```

---

## Task 17: CompareView

**Files:**
- Create: `src/components/CompareView.tsx`
- Test: `src/components/CompareView.test.tsx`

**Contract:** `export function CompareView({ runs, onClose }: { runs: BacktestResult[]; onClose: () => void }): JSX.Element`

- [ ] **Step 1: Write the failing test**

Create `src/components/CompareView.test.tsx`:
```tsx
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { CompareView } from './CompareView';
import type { BacktestResult } from '../services/types';

const mk = (id: string, slug: string, earn: number): BacktestResult => ({
  id, createdAt: 0, config: { slug, strategy: 'endline', params: {}, bookSize: 100, resample: '1s' },
  series: [
    { timestamp: 0, price: 0.5, position: 0, equityWoFee: 0, fee: 0, equity: 0 },
    { timestamp: 1000, price: 0.6, position: 5, equityWoFee: earn, fee: 0, equity: earn },
  ],
  trades: [],
  metrics: { earn, sr: 0, sortino: 0, ret: earn / 100, maxDrawdown: 0, dailyNumberOfTrades: 0, returnOverMdd: 0, maxPositionValue: 0 },
});

describe('CompareView', () => {
  it('overlays both equity curves and lists both slugs', () => {
    const { container } = render(<CompareView runs={[mk('a', 's1', 9), mk('b', 's2', 12)]} onClose={vi.fn()} />);
    expect(container.querySelectorAll('path.series-line').length).toBeGreaterThanOrEqual(2);
    expect(screen.getByText('s1')).toBeTruthy();
    expect(screen.getByText('s2')).toBeTruthy();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test -- CompareView`
Expected: FAIL (module not found).

- [ ] **Step 3: Implement with frontend-design skill**

Create `src/components/CompareView.tsx`. Renders a `LineChart` overlaying each run's equity curve (`equity / bookSize * 100`) as a distinct-colored series labeled by slug, plus a side-by-side metric table (rows = metric names, columns = each run's values via `fmtMoney`/`fmtPct`/`fmtNum`). A header with a "Close" button calling `onClose`. Wrap in `.card`.

- [ ] **Step 4: Run test to verify it passes**

Run: `npm test -- CompareView`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/components/CompareView.tsx src/components/CompareView.test.tsx
git commit -m "feat(frontend): add two-run compare view"
```

---

## Task 18: ResultsPanel (tabs + states)

**Files:**
- Create: `src/components/ResultsPanel.tsx`
- Test: `src/components/ResultsPanel.test.tsx`

**Contract:**
```ts
export function ResultsPanel(props: {
  status: 'idle' | 'running' | 'error';
  error: string | null;
  result: BacktestResult | null;
}): JSX.Element;
```

- [ ] **Step 1: Write the failing test**

Create `src/components/ResultsPanel.test.tsx`:
```tsx
import { describe, it, expect } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { ResultsPanel } from './ResultsPanel';
import type { BacktestResult } from '../services/types';

const result: BacktestResult = {
  id: 'r', createdAt: 0,
  config: { slug: 's', strategy: 'endline', params: {}, bookSize: 100, resample: '1s' },
  series: [
    { timestamp: 0, price: 0.5, position: 0, equityWoFee: 0, fee: 0, equity: 0 },
    { timestamp: 1000, price: 1, position: 0, equityWoFee: 9, fee: 0, equity: 9 },
  ],
  trades: [{ timestamp: 0, side: 'buy', price: 0.6, qty: 5 }],
  metrics: { earn: 9, sr: 1, sortino: 1, ret: 0.09, maxDrawdown: 0, dailyNumberOfTrades: 1, returnOverMdd: 0, maxPositionValue: 3 },
};

describe('ResultsPanel', () => {
  it('shows empty prompt when idle with no result', () => {
    render(<ResultsPanel status="idle" error={null} result={null} />);
    expect(screen.getByText(/run a backtest/i)).toBeTruthy();
  });
  it('shows error state', () => {
    render(<ResultsPanel status="error" error="boom" result={null} />);
    expect(screen.getByText(/boom/)).toBeTruthy();
  });
  it('shows metrics and can switch to trades tab', () => {
    render(<ResultsPanel status="idle" error={null} result={result} />);
    expect(screen.getByText(/Sharpe/i)).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: /trades/i }));
    expect(screen.getByRole('table')).toBeTruthy();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test -- ResultsPanel`
Expected: FAIL (module not found).

- [ ] **Step 3: Implement with frontend-design skill**

Create `src/components/ResultsPanel.tsx`:
- If `status === 'running'`: a skeleton/spinner block.
- Else if `status === 'error'`: an error `.card` showing `error` (the message text must render).
- Else if `result == null`: a muted empty prompt containing "Run a backtest to see results".
- Else: render `<MetricCards metrics={result.metrics} />`, then a tab bar with buttons "Charts" and "Trades"; Charts tab shows `EquityChart` + `PositionChart`; Trades tab shows `TradesTable`. Default tab is Charts.

- [ ] **Step 4: Run test to verify it passes**

Run: `npm test -- ResultsPanel`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add src/components/ResultsPanel.tsx src/components/ResultsPanel.test.tsx
git commit -m "feat(frontend): add results panel with tabs and states"
```

---

## Task 19: TopBar

**Files:**
- Create: `src/components/TopBar.tsx`
- Test: `src/components/TopBar.test.tsx`

**Contract:**
```ts
export function TopBar(props: {
  adapter: AdapterKind;
  onAdapterChange: (a: AdapterKind) => void;
}): JSX.Element;
```

- [ ] **Step 1: Write the failing test**

Create `src/components/TopBar.test.tsx`:
```tsx
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { TopBar } from './TopBar';

describe('TopBar', () => {
  it('shows the title and current adapter, fires change', () => {
    const onChange = vi.fn();
    render(<TopBar adapter="mock" onAdapterChange={onChange} />);
    expect(screen.getByText(/Polymarket Backtester/i)).toBeTruthy();
    fireEvent.change(screen.getByLabelText(/adapter/i), { target: { value: 'http' } });
    expect(onChange).toHaveBeenCalledWith('http');
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test -- TopBar`
Expected: FAIL (module not found).

- [ ] **Step 3: Implement with frontend-design skill**

Create `src/components/TopBar.tsx`: a header bar with the title "pm-hftbacktest · Polymarket Backtester" and a `<select>` labeled "Adapter" (id `adapter`) with options `mock` and `http`, calling `onAdapterChange(e.target.value as AdapterKind)`.

- [ ] **Step 4: Run test to verify it passes**

Run: `npm test -- TopBar`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/components/TopBar.tsx src/components/TopBar.test.tsx
git commit -m "feat(frontend): add top bar with adapter toggle"
```

---

## Task 20: Dashboard composition + App wiring

**Files:**
- Create: `src/pages/Dashboard.tsx`
- Modify: `src/App.tsx`
- Test: `src/pages/Dashboard.test.tsx`

**Contract:** `export function Dashboard(): JSX.Element`

- [ ] **Step 1: Write the failing test**

Create `src/pages/Dashboard.test.tsx`:
```tsx
import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { Dashboard } from './Dashboard';

beforeEach(() => localStorage.clear());

describe('Dashboard', () => {
  it('runs a backtest end-to-end with the mock adapter', async () => {
    render(<Dashboard />);
    fireEvent.click(screen.getByRole('button', { name: /run backtest/i }));
    // After the mock latency resolves, metrics appear and a history item is added.
    await waitFor(() => expect(screen.getByText(/Sharpe/i)).toBeTruthy(), { timeout: 3000 });
    await waitFor(() => expect(screen.getByText(/btc-updown/i)).toBeTruthy());
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test -- Dashboard`
Expected: FAIL (module not found).

- [ ] **Step 3: Implement**

Create `src/pages/Dashboard.tsx`:
- `const [adapter, setAdapter] = useState<AdapterKind>('mock');`
- `const service = useMemo(() => getService(adapter), [adapter]);`
- `const bt = useBacktestRuns(service);`
- `const [comparing, setComparing] = useState(false);`
- Layout: `<TopBar adapter onAdapterChange={setAdapter} />`, then a 3-column grid: `<HistorySidebar … onCompare={() => setComparing(true)} />`, `<ConfigPanel running={bt.status==='running'} onRun={bt.run} />`, and the right column showing `comparing && bt.compareRuns.length===2 ? <CompareView runs={bt.compareRuns} onClose={() => { setComparing(false); bt.clearCompare(); }} /> : <ResultsPanel status={bt.status} error={bt.error} result={bt.activeRun} />`.
- Wire `HistorySidebar` props from `bt` (runs, activeId, compareIds, onSelect=bt.selectRun, onToggleCompare=bt.toggleCompare).

Modify `src/App.tsx`:
```tsx
import { Dashboard } from './pages/Dashboard';
export default function App() {
  return <Dashboard />;
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm test -- Dashboard`
Expected: PASS.

- [ ] **Step 5: Run full suite + build**

Run: `npm test && npx tsc --noEmit && npm run build`
Expected: all tests PASS, no type errors, build succeeds.

- [ ] **Step 6: Commit**

```bash
git add src/pages/Dashboard.tsx src/App.tsx src/pages/Dashboard.test.tsx
git commit -m "feat(frontend): wire dashboard end-to-end"
```

---

## Task 21: Layout polish + responsive grid (frontend-design)

**Files:**
- Create: `src/pages/Dashboard.css` (or extend `theme.css`)
- Modify: `src/pages/Dashboard.tsx` (class names only)

- [ ] **Step 1: Apply the grid + polish with frontend-design skill**

Implement the 3-column desktop layout (`history | config | results`) with the warm aesthetic: sticky top bar, sidebar with `--surface-2`, comfortable spacing, focus-visible rings in `--accent`, hover states, and a sensible single-column stack under ~1000px. Charts fill available width. Do not change component prop contracts or `data-testid`/labels.

- [ ] **Step 2: Verify nothing broke**

Run: `npm test && npm run build`
Expected: all PASS, build succeeds.

- [ ] **Step 3: Manual visual check**

Run: `npm run dev`, open the URL, run a backtest, switch tabs, add a second run, select two and Compare. Confirm the warm light theme, charts, and interactions look right.

- [ ] **Step 4: Commit**

```bash
git add src/pages/Dashboard.tsx src/pages/Dashboard.css src/theme.css
git commit -m "style(frontend): polish dashboard layout and responsive grid"
```

---

## Task 22: Frontend README + backend contract note

**Files:**
- Create: `frontend/README.md`

- [ ] **Step 1: Write the README**

Create `frontend/README.md` documenting: what the app is; `npm install`, `npm run dev`, `npm test`, `npm run build`; the decoupling design (UI → `BacktestService` → `mockAdapter`/`httpAdapter`); how to point at a real backend (set the adapter to `http`, implement `POST /api/backtest` returning a `BacktestResult` JSON whose fields match `src/services/types.ts`, which in turn map 1:1 to the Python `hftbacktest` record + `hftbacktest.stats` metrics); and the strategy registry as the place to add strategies.

- [ ] **Step 2: Commit**

```bash
git add frontend/README.md
git commit -m "docs(frontend): add README with decoupling and backend contract"
```

---

## Self-Review Notes

- **Spec coverage:** decoupling/adapters (Tasks 5–7), data contract aligned to Python record (Task 1), strategy selector + dynamic params (Tasks 4, 15), metric cards (Task 12), equity/position charts (Tasks 11, 13), trades table (Task 14), history sidebar + localStorage (Tasks 8, 16), two-run compare (Task 17), light warm palette (Task 10, 21), error/empty/running states (Tasks 8, 18), tests (every task). All covered.
- **Type consistency:** `BacktestService.run`, `ChartSeries`/`LineChartProps`, `MetricSet` keys (`sr`, `sortino`, `ret`, `maxDrawdown`, `dailyNumberOfTrades`, `returnOverMdd`, `maxPositionValue`, `earn`), `AdapterKind`, `getService`, `useBacktestRuns` return shape — used consistently across tasks.
- **No placeholders:** all logic tasks contain full code; UI tasks specify exact prop contracts, render tests, exact label/string requirements, and delegate only visual craft to the frontend-design skill.
