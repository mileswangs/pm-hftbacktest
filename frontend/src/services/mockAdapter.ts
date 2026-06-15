import type { BacktestConfig, BacktestResult, SeriesPoint, Trade } from './types';
import type { BacktestService } from './BacktestService';
import { hashString, mulberry32 } from './prng';
import { computeMetrics } from './metrics';

const N_POINTS = 180; // resampled points
const STEP_MS = 1000;

function seedFor(config: BacktestConfig): number {
  const paramStr = Object.keys(config.params)
    .sort()
    .map((k) => `${k}=${config.params[k]}`)
    .join(',');
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
      const enterLevel =
        config.strategy === 'endline'
          ? config.params.up_trigger ?? 0.84
          : config.params.entry_price ?? 0.07;
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
      trades.push({
        timestamp: series[lastIdx].timestamp,
        side: position > 0 ? 'sell' : 'buy',
        price: settlePrice,
        qty: Math.abs(position),
      });
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
