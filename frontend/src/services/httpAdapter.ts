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
