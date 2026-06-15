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
