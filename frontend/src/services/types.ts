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
