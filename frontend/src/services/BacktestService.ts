import type { BacktestConfig, BacktestResult } from './types';

export interface BacktestService {
  run(config: BacktestConfig): Promise<BacktestResult>;
}
