import { describe, it, expect, beforeEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useBacktestRuns } from './useBacktestRuns';
import { mockAdapter } from '../services/mockAdapter';
import type { BacktestConfig } from '../services/types';

const cfg: BacktestConfig = {
  slug: 's',
  strategy: 'endline',
  params: { up_trigger: 0.84, stop_long: 0.4, order_qty: 5 },
  bookSize: 100,
  resample: '1s',
};

beforeEach(() => localStorage.clear());

describe('useBacktestRuns', () => {
  it('runs a backtest, stores it, sets it active', async () => {
    const { result } = renderHook(() => useBacktestRuns(mockAdapter));
    await act(async () => {
      await result.current.run(cfg);
    });
    expect(result.current.runs.length).toBe(1);
    expect(result.current.activeRun?.config.slug).toBe('s');
    expect(result.current.status).toBe('idle');
  });

  it('persists runs to localStorage', async () => {
    const { result } = renderHook(() => useBacktestRuns(mockAdapter));
    await act(async () => {
      await result.current.run(cfg);
    });
    expect(localStorage.getItem('pm-bt-runs')).toContain('"slug":"s"');
  });

  it('toggleCompare selects at most two runs', async () => {
    const { result } = renderHook(() => useBacktestRuns(mockAdapter));
    await act(async () => {
      await result.current.run(cfg);
    });
    await act(async () => {
      await result.current.run({ ...cfg, slug: 's2' });
    });
    const [a, b] = result.current.runs.map((r) => r.id);
    act(() => {
      result.current.toggleCompare(a);
    });
    act(() => {
      result.current.toggleCompare(b);
    });
    expect(result.current.compareIds).toEqual([a, b]);
  });
});
