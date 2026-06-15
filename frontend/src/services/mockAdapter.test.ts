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
