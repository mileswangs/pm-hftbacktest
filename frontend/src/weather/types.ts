export interface WeatherPoint {
  t: number;
  p: number;
}

export interface WeatherMarketStats {
  volume: number | null;
  volume24hr: number | null;
  liquidity: number | null;
  spread: number | null;
  bestBid: number | null;
  bestAsk: number | null;
  lastTradePrice: number | null;
  rewardsMinSize: number | null;
  rewardsMaxSpread: number | null;
  orderMinSize: number | null;
  orderPriceMinTickSize: number | null;
}

export interface WeatherOutcome {
  label: string;
  marketSlug: string;
  yesTokenId: string;
  isWinner: boolean;
  marketStats: WeatherMarketStats;
  points: WeatherPoint[];
}

export interface WeatherCandidate {
  label: string;
  price: number;
}

export interface WeatherRun {
  entryHours: number;
  entryTimeUtc: string;
  entryTimestamp: number;
  selectionMode: string;
  reason: string;
  selectedLabels: string[];
  selectedPrices: number[];
  selectedProbabilitySum: number;
  pnl: number;
  didHit: boolean;
  topCandidates: WeatherCandidate[];
}

export interface WeatherEvent {
  date: string;
  eventSlug: string;
  eventTitle: string;
  endTimeUtc: string;
  winnerLabel: string | null;
  resolutionSource: string | null;
  outcomes: WeatherOutcome[];
  runs: WeatherRun[];
}

export interface EntryHourSummary {
  entryHours: number;
  tradedCount: number;
  hitRate: number;
  totalPnl: number;
  avgPnl: number;
  singleCount: number;
  pairCount: number;
  skipCount: number;
  avgProbabilitySum: number;
}

export interface WeatherDataset {
  generatedAtUtc: string;
  citySlug: string;
  cityLabel: string;
  anchorDate: string;
  days: number;
  threshold: number;
  entryHours: number[];
  bestEntryHour: number | null;
  summaryByEntryHour: EntryHourSummary[];
  events: WeatherEvent[];
  dataSource?: string;
  dataSourceDetail?: string;
  timezoneNote?: string;
}

export interface WeatherLibraryEntry {
  citySlug: string;
  cityLabel: string;
  path: string;
  anchorDate: string;
  days: number;
  entryHours: number[];
  threshold: number;
  eventCount: number;
  bestEntryHour: number | null;
  bestTotalPnl: number;
}

export interface WeatherLibraryManifest {
  generatedAtUtc: string;
  cities: WeatherLibraryEntry[];
}

export interface WeatherOrderbookCapacityRow {
  citySlug: string;
  targetDate: string;
  eventSlug: string;
  bucketLabel: string;
  entryHours: number;
  entryTimeUtc: string;
  selectedProbability: number;
  snapshotBestAsk: number | null;
  snapshotBestBid: number | null;
  snapshotSide: string | null;
  snapshotSize: number | null;
  snapshotTimestampReceived: string | null;
  topAskPrice: number | null;
  topAskSize: number | null;
  cumSizePlus1c: number | null;
  cumSizePlus2c: number | null;
  cumSizePlus5c: number | null;
  bookTimestampReceived: string | null;
  bookAgeMinutes: number | null;
}

export interface WeatherOrderbookCapacityDataset {
  generatedAtUtc: string;
  citySlug: string;
  entryHours: number;
  rows: WeatherOrderbookCapacityRow[];
}
