import { describe, it, expect, vi, afterEach } from 'vitest';
import { createHttpAdapter } from './httpAdapter';
import type { BacktestConfig, BacktestResult } from './types';

const cfg: BacktestConfig = {
  slug: 's',
  strategy: 'endline',
  params: { up_trigger: 0.84, stop_long: 0.4, order_qty: 5 },
  bookSize: 100,
  resample: '1s',
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
