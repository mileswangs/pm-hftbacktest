import type {
  EntryHourSummary,
  WeatherDataset,
  WeatherEvent,
  WeatherOutcome,
  WeatherRun,
} from './types';

const USER_AGENT_NOTE = 'frontend-weather-study';
const GAMMA_BASE = 'https://gamma-api.polymarket.com';
const CLOB_BASE = 'https://clob.polymarket.com';

type EventResponse = {
  slug: string;
  title: string;
  endDate: string;
  markets: Array<{
    groupItemTitle: string;
    slug: string;
    clobTokenIds: string | string[];
    outcomePrices: string | string[];
    resolutionSource?: string | null;
  }>;
};

type HistoryPoint = [number, number];

type BuildOptions = {
  citySlug: string;
  cityLabel: string;
  anchorDate: string;
  days: number;
  entryHours: number[];
  threshold: number;
  onProgress?: (message: string) => void;
};

const eventCache = new Map<string, EventResponse | null>();
const historyCache = new Map<string, HistoryPoint[]>();

function normalizeJsonField<T>(raw: T | string): T {
  return typeof raw === 'string' ? (JSON.parse(raw) as T) : raw;
}

function buildEventSlug(citySlug: string, targetDate: Date): string {
  const month = targetDate.toLocaleString('en-US', { month: 'long', timeZone: 'UTC' }).toLowerCase();
  const day = targetDate.getUTCDate();
  const year = targetDate.getUTCFullYear();
  return `highest-temperature-in-${citySlug}-on-${month}-${day}-${year}`;
}

function sortKeyForLabel(label: string): number {
  const match = label.match(/-?\d+/);
  if (!match) return Number.POSITIVE_INFINITY;
  const value = Number(match[0]);
  const lowered = label.toLowerCase();
  if (lowered.includes('or below')) return value - 0.5;
  if (lowered.includes('or higher')) return value + 0.5;
  return value;
}

function dateRange(anchorDateIso: string, days: number): Date[] {
  const anchor = new Date(`${anchorDateIso}T00:00:00Z`);
  const out: Date[] = [];
  for (let i = days - 1; i >= 0; i -= 1) {
    out.push(new Date(anchor.getTime() - i * 24 * 60 * 60 * 1000));
  }
  return out;
}

async function fetchEvent(slug: string): Promise<EventResponse | null> {
  if (eventCache.has(slug)) return eventCache.get(slug) ?? null;
  const res = await fetch(`${GAMMA_BASE}/events?slug=${encodeURIComponent(slug)}`, {
    headers: { 'X-Client-Note': USER_AGENT_NOTE },
  });
  if (!res.ok) {
    throw new Error(`Event lookup failed for ${slug} (${res.status})`);
  }
  const data = (await res.json()) as EventResponse[];
  const event = data[0] ?? null;
  eventCache.set(slug, event);
  return event;
}

async function fetchHistory(tokenId: string): Promise<HistoryPoint[]> {
  if (historyCache.has(tokenId)) return historyCache.get(tokenId) ?? [];
  const params = new URLSearchParams({ market: tokenId, interval: 'max' });
  const res = await fetch(`${CLOB_BASE}/prices-history?${params.toString()}`, {
    headers: { 'X-Client-Note': USER_AGENT_NOTE },
  });
  if (!res.ok) {
    throw new Error(`History lookup failed for token ${tokenId} (${res.status})`);
  }
  const data = (await res.json()) as { history?: Array<{ t: number; p: number }> };
  const history = (data.history ?? []).map((point) => [point.t, point.p] as HistoryPoint);
  historyCache.set(tokenId, history);
  return history;
}

function winnerLabel(markets: EventResponse['markets']): string | null {
  for (const market of markets) {
    const prices = normalizeJsonField<string[]>(market.outcomePrices);
    if (Number(prices[0]) > 0.99) {
      return market.groupItemTitle;
    }
  }
  return null;
}

function lastPriceAtOrBefore(history: HistoryPoint[], entryTsSeconds: number): number | null {
  let lo = 0;
  let hi = history.length - 1;
  let answer = -1;
  while (lo <= hi) {
    const mid = Math.floor((lo + hi) / 2);
    if (history[mid][0] <= entryTsSeconds) {
      answer = mid;
      lo = mid + 1;
    } else {
      hi = mid - 1;
    }
  }
  return answer >= 0 ? history[answer][1] : null;
}

function describeDecision(
  outcomes: Array<{ label: string; entryPrice: number | null }>,
  selectionMode: string,
  selected: Array<{ label: string; entryPrice: number | null }>,
  threshold: number,
): string {
  const tradable = outcomes
    .filter((outcome) => outcome.entryPrice != null)
    .sort((a, b) => (b.entryPrice ?? -1) - (a.entryPrice ?? -1) || sortKeyForLabel(a.label) - sortKeyForLabel(b.label));
  if (tradable.length === 0) return 'No tradable outcome had a price snapshot at the requested entry time.';
  const top = tradable[0];
  if (selectionMode === 'single_over_threshold' && selected[0]?.entryPrice != null) {
    return `Bought only ${selected[0].label} because its implied probability was ${(selected[0].entryPrice * 100).toFixed(1)}%, above the ${(threshold * 100).toFixed(0)}% threshold.`;
  }
  if (selectionMode === 'pair_over_threshold' && selected.length === 2) {
    const sum = (selected[0].entryPrice ?? 0) + (selected[1].entryPrice ?? 0);
    return `No single outcome cleared ${(threshold * 100).toFixed(0)}%. Bought ${selected[0].label} (${((selected[0].entryPrice ?? 0) * 100).toFixed(1)}%) and ${selected[1].label} (${((selected[1].entryPrice ?? 0) * 100).toFixed(1)}%) because together they reached ${(sum * 100).toFixed(1)}%.`;
  }
  const second = tradable[1];
  if (selectionMode === 'skip_pair_below_threshold' && second?.entryPrice != null) {
    return `Skipped because ${top.label} (${((top.entryPrice ?? 0) * 100).toFixed(1)}%) and ${second.label} (${((second.entryPrice ?? 0) * 100).toFixed(1)}%) only summed to ${(((top.entryPrice ?? 0) + (second.entryPrice ?? 0)) * 100).toFixed(1)}%, below ${(threshold * 100).toFixed(0)}%.`;
  }
  if (selectionMode === 'skip_not_enough_prices') {
    return 'Skipped because fewer than two outcomes had usable price history at the entry time.';
  }
  return 'Skipped because no outcome satisfied the strategy entry rule.';
}

function selectPositions(
  outcomes: Array<{ label: string; entryPrice: number | null }>,
  threshold: number,
): { selectionMode: string; selected: Array<{ label: string; entryPrice: number | null }> } {
  const tradable = outcomes
    .filter((outcome) => outcome.entryPrice != null)
    .sort((a, b) => (b.entryPrice ?? -1) - (a.entryPrice ?? -1) || sortKeyForLabel(a.label) - sortKeyForLabel(b.label));
  if (tradable.length === 0) {
    return { selectionMode: 'skip_no_prices', selected: [] };
  }
  if ((tradable[0].entryPrice ?? 0) > threshold) {
    return { selectionMode: 'single_over_threshold', selected: [tradable[0]] };
  }
  if (tradable.length < 2) {
    return { selectionMode: 'skip_not_enough_prices', selected: [] };
  }
  const topTwo = tradable.slice(0, 2);
  const sum = (topTwo[0].entryPrice ?? 0) + (topTwo[1].entryPrice ?? 0);
  if (sum > threshold) {
    return { selectionMode: 'pair_over_threshold', selected: topTwo };
  }
  return { selectionMode: 'skip_pair_below_threshold', selected: [] };
}

export function parseEntryHours(raw: string): number[] {
  return raw
    .split(',')
    .map((part) => Number(part.trim()))
    .filter((value) => Number.isFinite(value) && value > 0);
}

export function inferCityLabel(citySlug: string): string {
  return citySlug
    .split('-')
    .filter(Boolean)
    .map((part) => part[0].toUpperCase() + part.slice(1))
    .join(' ');
}

export async function buildWeatherDataset(options: BuildOptions): Promise<WeatherDataset> {
  const { citySlug, cityLabel, anchorDate, days, entryHours, threshold, onProgress } = options;
  const events: WeatherEvent[] = [];
  const summaryMap = new Map<number, EntryHourSummary>();
  for (const hour of entryHours) {
    summaryMap.set(hour, {
      entryHours: hour,
      tradedCount: 0,
      hitRate: 0,
      totalPnl: 0,
      avgPnl: 0,
      singleCount: 0,
      pairCount: 0,
      skipCount: 0,
      avgProbabilitySum: 0,
    });
  }

  const targets = dateRange(anchorDate, days);
  for (let index = 0; index < targets.length; index += 1) {
    const targetDate = targets[index];
    const slug = buildEventSlug(citySlug, targetDate);
    onProgress?.(`Loading event ${index + 1}/${targets.length}: ${slug}`);
    const event = await fetchEvent(slug);
    if (!event) continue;

    const markets = [...event.markets].sort((a, b) => sortKeyForLabel(a.groupItemTitle) - sortKeyForLabel(b.groupItemTitle));
    const winner = winnerLabel(markets);
    const outcomes: WeatherOutcome[] = await Promise.all(
      markets.map(async (market) => {
        const tokenId = String(normalizeJsonField<string[]>(market.clobTokenIds)[0]);
        const history = await fetchHistory(tokenId);
        return {
          label: market.groupItemTitle,
          marketSlug: market.slug,
          yesTokenId: tokenId,
          isWinner: market.groupItemTitle === winner,
          points: history.map(([t, p]) => ({ t: t * 1000, p })),
        };
      }),
    );

    const endTime = new Date(event.endDate);
    const runs: WeatherRun[] = entryHours.map((hours) => {
      const entryTimestamp = endTime.getTime() - hours * 60 * 60 * 1000;
      const snapshots = outcomes.map((outcome) => ({
        label: outcome.label,
        entryPrice: lastPriceAtOrBefore(
          outcome.points.map((point) => [Math.floor(point.t / 1000), point.p]),
          Math.floor(entryTimestamp / 1000),
        ),
      }));
      const { selectionMode, selected } = selectPositions(snapshots, threshold);
      const selectedProbabilitySum = selected.reduce((acc, item) => acc + (item.entryPrice ?? 0), 0);
      const didHit = selected.some((item) => item.label === winner);
      const pnl = (didHit ? 1 : 0) - selectedProbabilitySum;
      return {
        entryHours: hours,
        entryTimeUtc: new Date(entryTimestamp).toISOString(),
        entryTimestamp,
        selectionMode,
        reason: describeDecision(snapshots, selectionMode, selected, threshold),
        selectedLabels: selected.map((item) => item.label),
        selectedPrices: selected.map((item) => item.entryPrice ?? 0),
        selectedProbabilitySum,
        pnl,
        didHit,
        topCandidates: [...snapshots]
          .filter((item) => item.entryPrice != null)
          .sort((a, b) => (b.entryPrice ?? -1) - (a.entryPrice ?? -1) || sortKeyForLabel(a.label) - sortKeyForLabel(b.label))
          .slice(0, 3)
          .map((item) => ({ label: item.label, price: item.entryPrice ?? 0 })),
      };
    });

    for (const run of runs) {
      const summary = summaryMap.get(run.entryHours);
      if (!summary) continue;
      if (run.selectedLabels.length > 0) {
        summary.tradedCount += 1;
        summary.totalPnl += run.pnl;
        summary.avgProbabilitySum += run.selectedProbabilitySum;
        if (run.didHit) summary.hitRate += 1;
        if (run.selectionMode === 'single_over_threshold') summary.singleCount += 1;
        if (run.selectionMode === 'pair_over_threshold') summary.pairCount += 1;
      } else {
        summary.skipCount += 1;
      }
    }

    events.push({
      date: endTime.toISOString().slice(0, 10),
      eventSlug: event.slug,
      eventTitle: event.title,
      endTimeUtc: endTime.toISOString(),
      winnerLabel: winner,
      resolutionSource: markets[0]?.resolutionSource ?? null,
      outcomes,
      runs,
    });
  }

  const summaryByEntryHour = [...summaryMap.values()]
    .map((item) => ({
      ...item,
      hitRate: item.tradedCount > 0 ? item.hitRate / item.tradedCount : 0,
      avgPnl: item.tradedCount > 0 ? item.totalPnl / item.tradedCount : 0,
      avgProbabilitySum: item.tradedCount > 0 ? item.avgProbabilitySum / item.tradedCount : 0,
    }))
    .sort((a, b) => a.entryHours - b.entryHours);

  const bestEntryHour = summaryByEntryHour.reduce<number | null>((best, item) => {
    if (best == null) return item.entryHours;
    const current = summaryByEntryHour.find((row) => row.entryHours === best);
    if (!current) return item.entryHours;
    return item.totalPnl > current.totalPnl ? item.entryHours : best;
  }, null);

  return {
    generatedAtUtc: new Date().toISOString(),
    citySlug,
    cityLabel,
    anchorDate,
    days,
    threshold,
    entryHours,
    bestEntryHour,
    summaryByEntryHour,
    events,
  };
}
