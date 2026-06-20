export interface WeatherPoint {
  t: number;
  p: number;
}

export interface WeatherOutcome {
  label: string;
  marketSlug: string;
  yesTokenId: string;
  isWinner: boolean;
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
}
