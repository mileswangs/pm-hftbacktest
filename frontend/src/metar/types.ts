// Mirrors the JSON written by research/export_metar_strategy_frontend.py.
// All computation happens there; this page only renders the precomputed result.

export interface MetarThresholdSummary {
  threshold: number;
  tradeCount: number;
  uniqueDays?: number;
  hitRate?: number;
  avgPnlPerShare?: number;
  totalPnlPerShare?: number;
  avgNoEntryPrice?: number;
}

export interface MetarTrade {
  eventSlug: string;
  targetDate: string;
  bucketLabel: string;
  deathTimeUtc: string;
  deathLocalHour: number;
  runningMaxC: number;
  noEntryPrice: number;
  actualIsWinner: boolean;
  pnlPerShare: number;
}

export interface MetarStrategyDataset {
  generatedAtUtc: string;
  citySlug: string;
  cityLabel: string;
  station: string;
  stationLabel: string;
  resolutionSource: string | null;
  eventsTotal: number;
  dateRange: { start: string; end: string } | null;
  thresholds: number[];
  summaryByThreshold: MetarThresholdSummary[];
  trades: MetarTrade[];
  noMetarDataDays: string[];
}
