import type { AdapterKind } from './types';
import type { BacktestService } from './BacktestService';
import { mockAdapter } from './mockAdapter';
import { createHttpAdapter } from './httpAdapter';

export function getService(kind: AdapterKind = 'mock'): BacktestService {
  return kind === 'http' ? createHttpAdapter() : mockAdapter;
}

export type { BacktestService } from './BacktestService';
