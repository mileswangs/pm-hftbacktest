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
    pt(2000, 0.4, 5, 4, 1), // drawdown here
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
